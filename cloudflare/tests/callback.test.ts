import { beforeEach, describe, expect, it } from "vitest";
import { onRequestGet } from "../functions/api/auth/callback.js";
import { SESSION_SECONDS } from "../src/config.js";
import { seal, randomToken } from "../src/auth.js";
import { TestD1 } from "./d1.js";

const CONFIG = {
  FREE_TIER_ENABLED: "true",
  ACCOUNT_PLAN: "free",
  DAILY_REQUEST_QUOTA: "1000",
  GITHUB_CLIENT_ID: "synthetic-client",
  GITHUB_CALLBACK_URL: "https://example.invalid/auth/callback",
  OWNER_GITHUB_ID: "12345",
  SESSION_SECRET: "12345678901234567890123456789012",
  GITHUB_CLIENT_SECRET: "synthetic-secret",
};

let d1: TestD1;

beforeEach(() => {
  d1 = new TestD1();
});

describe("OAuth callback session duration", () => {
  it("stores a session that expires in 30 days", async () => {
    const secret = CONFIG.SESSION_SECRET;
    const state = "synthetic-state";
    const verifier = randomToken(43); // PKCE verifier is 43-128 characters

    const sealed = await seal(JSON.stringify({ state }), secret);
    const cookie = `jobagent_oauth=${sealed}`;

    // Insert the OAuth state with a future expiry
    const now = new Date();
    const stateExpiry = new Date(now.getTime() + 10 * 60_000); // 10 minutes
    await d1.asD1().prepare(
      "INSERT INTO oauth_states (state, verifier, expires_at) VALUES (?, ?, ?)",
    ).bind(state, verifier, stateExpiry.toISOString()).run();

    // Mock fetch to simulate GitHub OAuth flow
    const originalFetch = globalThis.fetch;
    let callCount = 0;
    globalThis.fetch = (async (url: string | URL, init?: RequestInit) => {
      callCount += 1;
      if (String(url).includes("/login/oauth/access_token")) {
        return new Response(JSON.stringify({ access_token: "synthetic-token" }), {
          ok: true,
          status: 200,
          headers: new Headers({ "content-type": "application/json" }),
        });
      }
      if (String(url).includes("/api.github.com/user")) {
        return new Response(JSON.stringify({ id: 12345 }), {
          ok: true,
          status: 200,
          headers: new Headers({ "content-type": "application/json" }),
        });
      }
      return originalFetch(url, init);
    }) as unknown as typeof fetch;

    try {
      const request = new Request("https://example.invalid/auth/callback?code=synthetic&state=synthetic-state", {
        headers: { cookie },
      });

      const response = await onRequestGet({
        request,
        env: { ...CONFIG, DB: d1.asD1() } as unknown as Parameters<typeof onRequestGet>[0]["env"],
      } as Parameters<typeof onRequestGet>[0]);

      expect(response.status).toBe(302);

      // Check that a session was created
      const session = await d1.asD1().prepare(
        "SELECT expires_at FROM owner_sessions ORDER BY created_at DESC LIMIT 1",
      ).first<{ expires_at: string }>();

      expect(session).toBeDefined();
      if (session) {
        const expiresAt = new Date(session.expires_at);
        const createdAt = new Date();
        const expirationDays = (expiresAt.getTime() - createdAt.getTime()) / (1000 * 86_400);

        // Should be ~30 days, allow 1 minute tolerance for test execution time
        expect(expirationDays).toBeGreaterThan(29.9999);
        expect(expirationDays).toBeLessThan(30.0001);
      }
    } finally {
      globalThis.fetch = originalFetch;
    }
  });
});
