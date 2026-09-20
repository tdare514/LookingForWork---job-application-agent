import { execFileSync } from "node:child_process";
import { describe, expect, it } from "vitest";

describe("deployment preflight", () => {
  it("refuses when the free-tier configuration is not explicit", () => {
    expect(() =>
      execFileSync(process.execPath, ["scripts/verify-free-plan.mjs"], {
        cwd: process.cwd(),
        env: {
          ...process.env,
          CLOUDFLARE_ACCOUNT_ID: "00000000000000000000000000000000",
          CLOUDFLARE_API_TOKEN: "synthetic-token",
          FREE_TIER_ENABLED: "true",
          ACCOUNT_PLAN: "unknown",
        },
        stdio: "pipe",
      }),
    ).toThrow();
  });
});
