import { describe, expect, it } from "vitest";
import { cookie, open, parseCookies, seal } from "../src/auth.js";

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
});
