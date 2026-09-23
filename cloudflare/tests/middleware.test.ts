import { beforeEach, describe, expect, it } from "vitest";
import { onRequest } from "../functions/_middleware.js";
import { TestD1 } from "./d1.js";

const ORIGIN = "https://companion.example.invalid";
const FREE = { FREE_TIER_ENABLED: "true", ACCOUNT_PLAN: "free", DAILY_REQUEST_QUOTA: "1000" };
const TOKEN = "synthetic-sync-token-0123456789abcdef";
let d1: TestD1;
let client = 0;

function addSession(id: string, { expiresIn = 3_600_000, revoked = false } = {}): void {
  d1.db.prepare(
    "INSERT INTO owner_sessions (id, owner_github_id, created_at, expires_at, revoked_at) VALUES (?, '1', ?, ?, ?)",
  ).run(id, new Date().toISOString(), new Date(Date.now() + expiresIn).toISOString(),
    revoked ? new Date().toISOString() : null);
}

async function call(
  path: string,
  { method = "GET", headers = {}, env = FREE }: { method?: string; headers?: Record<string, string>; env?: object } = {},
): Promise<Response> {
  client += 1; // a fresh client per call keeps the per-client limiter out of these tests
  const request = new Request(`${ORIGIN}${path}`, {
    method,
    headers: { "CF-Connecting-IP": `test-${client}`, ...headers },
  });
  const context = { request, env: { ...env, DB: d1.asD1() }, next: async () => new Response("reached") };
  return (onRequest as unknown as (c: typeof context) => Promise<Response>)(context);
}

const session = (id: string, csrf?: string) =>
  ({ cookie: `jobagent_session=${id}${csrf ? `; jobagent_csrf=${csrf}` : ""}` });

beforeEach(() => {
  d1 = new TestD1();
});

describe("api gate", () => {
  it("serves the static page and health check without a session", async () => {
    expect(await (await call("/")).text()).toBe("reached");
    expect((await call("/api/health")).status).toBe(200);
  });

  it("refuses every other API route unless the deployment declares itself free-tier", async () => {
    expect((await call("/api/jobs", { env: {} })).status).toBe(503);
    expect((await call("/api/auth/github", { env: {} })).status).toBe(503);
  });

  it("lets login through without a session, but still limited", async () => {
    expect((await call("/api/auth/github")).status).toBe(200);
    expect((await call("/api/auth/logout", { method: "POST" })).status).toBe(413);
  });

  it("refuses a missing, unknown, revoked or expired session", async () => {
    addSession("revoked", { revoked: true });
    addSession("expired", { expiresIn: -1 });
    expect((await call("/api/jobs")).status).toBe(401);
    for (const id of ["unknown", "revoked", "expired"]) {
      expect((await call("/api/jobs", { headers: session(id) })).status).toBe(401);
    }
  });

  it("admits a live session to a read", async () => {
    addSession("live");
    const response = await call("/api/jobs", { headers: session("live") });
    expect(await response.text()).toBe("reached");
    expect(response.headers.get("X-Frame-Options")).toBe("DENY");
  });

  it("requires same origin and a matching CSRF token on a write", async () => {
    addSession("live");
    const write = (headers: Record<string, string>) =>
      call("/api/jobs/a", { method: "PUT", headers: { "content-length": "2", ...headers } });
    expect((await write({ ...session("live", "t"), origin: ORIGIN })).status).toBe(403);
    expect((await write({ ...session("live", "t"), origin: "https://evil.invalid", "x-csrf-token": "t" })).status).toBe(403);
    expect((await write({ ...session("live", "t"), origin: ORIGIN, "x-csrf-token": "other" })).status).toBe(403);
    expect((await write({ ...session("live"), origin: ORIGIN, "x-csrf-token": "" })).status).toBe(403);
    expect(await (await write({ ...session("live", "t"), origin: ORIGIN, "x-csrf-token": "t" })).text()).toBe("reached");
  });
});

describe("machine routes", () => {
  const withToken = { ...FREE, SYNC_TOKEN: TOKEN };

  it("answer 503 until a sync token is configured", async () => {
    expect((await call("/api/sync", { headers: { authorization: `Bearer ${TOKEN}` } })).status).toBe(503);
  });

  it("admit the bearer token and nothing else", async () => {
    addSession("live");
    expect((await call("/api/sync", { env: withToken })).status).toBe(401);
    expect((await call("/api/sync", { env: withToken, headers: { authorization: "Bearer wrong" } })).status).toBe(401);
    expect((await call("/api/sync", { env: withToken, headers: { authorization: TOKEN } })).status).toBe(401);
    // A browser session is not a sync credential.
    expect((await call("/api/purge", { method: "POST", env: withToken, headers: { ...session("live", "t"), origin: ORIGIN, "x-csrf-token": "t", "content-length": "0" } })).status).toBe(401);
    const ok = await call("/api/sync", { env: withToken, headers: { authorization: `Bearer ${TOKEN}` } });
    expect(await ok.text()).toBe("reached");
  });

  it("still apply the size limit to a token-bearing write", async () => {
    const headers = { authorization: `Bearer ${TOKEN}` };
    expect((await call("/api/purge", { method: "POST", env: withToken, headers })).status).toBe(413);
    expect(await (await call("/api/purge", { method: "POST", env: withToken, headers: { ...headers, "content-length": "0" } })).text()).toBe("reached");
  });

  it("do not let the token open the page's routes", async () => {
    expect((await call("/api/jobs", { env: withToken, headers: { authorization: `Bearer ${TOKEN}` } })).status).toBe(401);
  });
});
