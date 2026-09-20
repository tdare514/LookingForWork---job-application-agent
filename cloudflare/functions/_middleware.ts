import type { PagesFunction } from "@cloudflare/workers-types";
import { LIMITS, readAccountConfig } from "../src/config.js";
import { withSecurityHeaders } from "../src/security.js";

type Env = { DB: D1Database };

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

export const onRequest: PagesFunction<Env> = async (context) => {
  const account = readAccountConfig(context.env as unknown as Record<string, string | undefined>);
  if (account === null) {
    return withSecurityHeaders(new Response(JSON.stringify({ error: "free-tier configuration required" }), {
      status: 503,
      headers: { "content-type": "application/json" },
    }));
  }
  const contentLength = Number.parseInt(context.request.headers.get("content-length") ?? "0", 10);
  if (!Number.isInteger(contentLength) || contentLength > LIMITS.maxBodyBytes) {
    return withSecurityHeaders(new Response(JSON.stringify({ error: "request body too large" }), {
      status: 413,
      headers: { "content-type": "application/json" },
    }));
  }
  if (rateLimited(context.request, Date.now(), account.dailyRequestQuota)) {
    return withSecurityHeaders(
      new Response(JSON.stringify({ error: "rate limit exceeded" }), {
        status: 429,
        headers: { "content-type": "application/json" },
      }),
    );
  }

  const response = await context.next();
  return withSecurityHeaders(response);
};
