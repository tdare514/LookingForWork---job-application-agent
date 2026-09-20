import { describe, expect, it } from "vitest";
import { LIMITS, clampLimit } from "../src/config.js";

describe("free-tier limits", () => {
  it("keeps rows and request bodies explicitly bounded", () => {
    expect(LIMITS.maxRows).toBeLessThanOrEqual(50);
    expect(LIMITS.maxBodyBytes).toBeLessThanOrEqual(16_384);
    expect(LIMITS.rateLimitRequests).toBeLessThanOrEqual(30);
  });

  it("clamps invalid and oversized row requests", () => {
    expect(clampLimit(null)).toBe(LIMITS.maxRows);
    expect(clampLimit("0")).toBe(LIMITS.maxRows);
    expect(clampLimit("999")).toBe(LIMITS.maxRows);
    expect(clampLimit("3")).toBe(3);
  });
});
