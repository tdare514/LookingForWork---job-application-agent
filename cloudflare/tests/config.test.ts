import { describe, expect, it } from "vitest";
import { LIMITS, clampLimit, readAccountConfig } from "../src/config.js";

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
});
