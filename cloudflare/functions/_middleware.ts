import type { PagesFunction } from "@cloudflare/workers-types";
import { LIMITS } from "../src/config.js";
import { withSecurityHeaders } from "../src/security.js";

type Env = { DB: D1Database };

const requestCounts = new Map<string, { count: number; windowStarted: number }>();

function clientKey(request: Request): string {
  return request.headers.get("CF-Connecting-IP") ?? "local";
}

function rateLimited(request: Request, now: number): boolean {
  const key = clientKey(request);
  const previous = requestCounts.get(key);
  if (!previous || now - previous.windowStarted >= LIMITS.rateLimitWindowSeconds * 1000) {
    requestCounts.set(key, { count: 1, windowStarted: now });
    return false;
  }
  previous.count += 1;
  return previous.count > LIMITS.rateLimitRequests;
}

export const onRequest: PagesFunction<Env> = async (context) => {
  if (rateLimited(context.request, Date.now())) {
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
