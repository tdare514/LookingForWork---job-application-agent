import { describe, expect, it } from "vitest";
import { cookie, csrfCookie, open, parseCookies, seal } from "../src/auth.js";
import { SESSION_SECONDS } from "../src/config.js";

describe("authentication primitives", () => {
  it("seals transaction data and rejects tampering", async () => {
    const secret = "12345678901234567890123456789012";
    const sealed = await seal("synthetic-state", secret);
    expect(await open(sealed, secret)).toBe("synthetic-state");
    expect(await open(`${sealed}x`, secret)).toBeNull();
  });

  it("accepts a secret of any length the config allows", async () => {
    // 32 random bytes, base64: the length `openssl rand -base64 32` produces.
    const secret = "q3N0bW9yZS1yYW5kb20tYnl0ZXMtaGVyZS0xMjM0NTY=";
    expect(secret.length).toBe(44);
    expect(await open(await seal("synthetic-state", secret), secret)).toBe("synthetic-state");
    expect(await open(await seal("synthetic-state", secret), `${secret}x`)).toBeNull();
  });

  it("formats and parses secure session cookies", () => {
    const header = cookie("jobagent_session", "synthetic", 60);
    expect(header).toContain("HttpOnly");
    expect(header).toContain("Secure");
    expect(parseCookies(`${header}; jobagent_csrf=token`).get("jobagent_session")).toBe("synthetic");
  });

  it("gives the CSRF cookie the 30-day session lifetime", () => {
    expect(SESSION_SECONDS).toBe(30 * 86_400);
    expect(csrfCookie("synthetic-token")).toContain("Max-Age=2592000;");
  });
});
