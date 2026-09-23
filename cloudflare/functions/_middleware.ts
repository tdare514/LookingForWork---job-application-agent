import type { PagesFunction } from "@cloudflare/workers-types";
import { bodyTooLarge, LIMITS, readAccountConfig } from "../src/config.js";
import { withSecurityHeaders } from "../src/security.js";

type Env = { FREE_TIER_ENABLED?: string; ACCOUNT_PLAN?: string; DAILY_REQUEST_QUOTA?: string };

// Per-isolate counters. Cloudflare runs many isolates and recycles them, so this
// is a brake on a runaway client, not a distributed quota.
const requestCounts = new Map<string, { count: number; windowStarted: number }>();
let dailyCount = { count: 0, day: "" };

function clientKey(request: Request): string {
  return request.headers.get("CF-Connecting-IP") ?? "local";
}

function rateLimited(request: Request, now: number, quota: number): boolean {
  const key = clientKey(request);
  const day = new Date(now).toISOString().slice(0, 10);
  if (dailyCount.day !== day) dailyCount = { count: 0, day };
  if (dailyCount.count >= quota) return true;
  for (const [storedKey, entry] of requestCounts) {
    if (now - entry.windowStarted >= LIMITS.rateLimitWindowSeconds * 1000) {
      requestCounts.delete(storedKey);
    }
  }
  if (!requestCounts.has(key) && requestCounts.size >= LIMITS.maxTrackedClients) {
    const oldest = requestCounts.keys().next().value;
    if (oldest !== undefined) requestCounts.delete(oldest);
  }
  const previous = requestCounts.get(key);
  if (!previous || now - previous.windowStarted >= LIMITS.rateLimitWindowSeconds * 1000) {
    requestCounts.set(key, { count: 1, windowStarted: now });
    dailyCount.count += 1;
    return false;
  }
  previous.count += 1;
  if (previous.count > LIMITS.rateLimitRequests) return true;
  dailyCount.count += 1;
  return false;
}

const refuse = (status: number, error: string): Response =>
  withSecurityHeaders(
    new Response(JSON.stringify({ error }), {
      status,
      headers: { "content-type": "application/json", "cache-control": "no-store" },
    }),
  );

export const onRequest: PagesFunction<Env> = async (context) => {
  const pathname = new URL(context.request.url).pathname;
  if (!pathname.startsWith("/api/") || pathname === "/api/health") {
    return withSecurityHeaders(await context.next());
  }
  const account = readAccountConfig(context.env as unknown as Record<string, string | undefined>);
  if (account === null) return refuse(503, "free-tier configuration required");
  if (bodyTooLarge(context.request.method, context.request.headers.get("content-length"))) {
    return refuse(413, "request body too large or of undeclared length");
  }
  if (rateLimited(context.request, Date.now(), account.dailyRequestQuota)) {
    return refuse(429, "rate limit exceeded");
  }
  return withSecurityHeaders(await context.next());
};
