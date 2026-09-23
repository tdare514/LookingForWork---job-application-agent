import { describe, expect, it } from "vitest";
import { parseSyncBody } from "../src/sync.js";

const row = {
  id: "synthetic-001",
  company: "Example North",
  title: "Operations Analyst",
  location: "Toronto, ON",
  url: "https://example.invalid/jobs/1",
  deadline: "2026-09-20",
  status: "ready",
  nextAction: "Review package",
  nextActionDate: "2026-09-19",
  version: 1,
};

describe("tracker sync validation", () => {
  it("accepts only the hosted tracker allowlist", () => {
    expect(parseSyncBody({ applications: [row] })).toEqual({ applications: [row] });
    expect(parseSyncBody({ applications: [{ ...row, resume: "secret" }] })).toBeNull();
    expect(parseSyncBody({ applications: [{ ...row, workAuthorization: true }] })).toBeNull();
    // Free text that names people is CRITICAL locally and refused here.
    expect(parseSyncBody({ applications: [{ ...row, notes: "Synthetic note" }] })).toBeNull();
    expect(parseSyncBody({ applications: [{ ...row, stateReason: "Synthetic reason" }] })).toBeNull();
  });

  it("rejects malformed, oversized, or unsafe values", () => {
    expect(parseSyncBody({ applications: [{ ...row, status: "submitted" }] })).toBeNull();
    expect(parseSyncBody({ applications: [{ ...row, url: "javascript:alert(1)" }] })).toBeNull();
    expect(parseSyncBody({ applications: [{ ...row, nextAction: "x".repeat(501) }] })).toBeNull();
    expect(parseSyncBody({ applications: [{ ...row, status: "pursue" }] })).toBeNull();
    expect(parseSyncBody({ applications: new Array(51).fill(row) })).toBeNull();
  });

  it("allows version zero for first import and null optional fields", () => {
    expect(parseSyncBody({
      applications: [{
        ...row,
        version: 0,
        deadline: null,
        nextAction: null,
        nextActionDate: null,
      }],
    })).not.toBeNull();
  });
});
