import { describe, expect, it } from "vitest";
import { LIMITS, bodyTooLarge, clampLimit, readAccountConfig, readAuthConfig, readSyncToken } from "../src/config.js";

describe("free-tier limits", () => {
  it("keeps rows and request bodies explicitly bounded", () => {
    expect(LIMITS.maxRows).toBeLessThanOrEqual(50);
    expect(LIMITS.maxBodyBytes).toBeLessThanOrEqual(16_384);
    expect(LIMITS.rateLimitRequests).toBeLessThanOrEqual(30);
    expect(LIMITS.maxTrackedClients).toBeLessThanOrEqual(1_000);
  });

  it("clamps invalid and oversized row requests", () => {
    expect(clampLimit(null)).toBe(LIMITS.maxRows);
    expect(clampLimit("0")).toBe(LIMITS.maxRows);
    expect(clampLimit("999")).toBe(LIMITS.maxRows);
    expect(clampLimit("3")).toBe(3);
  });

  it("fails closed when the account is not explicitly free-tier", () => {
    expect(readAccountConfig({})).toBeNull();
    expect(readAccountConfig({ FREE_TIER_ENABLED: "true", ACCOUNT_PLAN: "paid", DAILY_REQUEST_QUOTA: "10" })).toBeNull();
    expect(readAccountConfig({ FREE_TIER_ENABLED: "true", ACCOUNT_PLAN: "free", DAILY_REQUEST_QUOTA: "1001" })).toBeNull();
    expect(readAccountConfig({ FREE_TIER_ENABLED: "true", ACCOUNT_PLAN: "free", DAILY_REQUEST_QUOTA: "10" })).toEqual({
      accountPlan: "free",
      dailyRequestQuota: 10,
    });
  });

  it("refuses a state-changing body that is oversized or of undeclared length", () => {
    expect(bodyTooLarge("GET", null)).toBe(false);
    expect(bodyTooLarge("POST", null)).toBe(true);
    expect(bodyTooLarge("PUT", "-1")).toBe(true);
    expect(bodyTooLarge("PUT", String(LIMITS.maxBodyBytes + 1))).toBe(true);
    expect(bodyTooLarge("PUT", String(LIMITS.maxBodyBytes))).toBe(false);
  });

  it("requires explicit owner identity and a strong session secret", () => {
    expect(readAuthConfig({})).toBeNull();
    expect(readAuthConfig({
      GITHUB_CLIENT_ID: "synthetic-client",
      GITHUB_CALLBACK_URL: "https://example.invalid/auth/callback",
      OWNER_GITHUB_ID: "not-numeric",
      SESSION_SECRET: "short",
    })).toBeNull();
    expect(readAuthConfig({
      GITHUB_CLIENT_ID: "synthetic-client",
      GITHUB_CALLBACK_URL: "https://example.invalid/auth/callback",
      OWNER_GITHUB_ID: "12345",
      SESSION_SECRET: "12345678901234567890123456789012",
    })?.ownerGithubId).toBe("12345");
  });

  it("refuses a missing or short sync token", () => {
    expect(readSyncToken({})).toBeNull();
    expect(readSyncToken({ SYNC_TOKEN: "short" })).toBeNull();
    expect(readSyncToken({ SYNC_TOKEN: "x".repeat(32) })).toBe("x".repeat(32));
  });
});
