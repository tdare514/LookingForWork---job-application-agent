import { describe, expect, it } from "vitest";
import { SYNTHETIC_APPLICATIONS } from "../src/fixtures.js";
import { APPLICATION_STATUSES, isApplicationStatus } from "../src/types.js";

describe("synthetic tracker contract", () => {
  it("keeps fixtures within the allowlisted status vocabulary", () => {
    expect(SYNTHETIC_APPLICATIONS).toHaveLength(2);
    expect(SYNTHETIC_APPLICATIONS.every((row) => isApplicationStatus(row.status))).toBe(true);
    expect(APPLICATION_STATUSES).not.toContain("submitted");
  });

  it("contains no dossier fields", () => {
    const forbidden = ["resume", "email", "phone", "workAuthorization", "password"];
    for (const row of SYNTHETIC_APPLICATIONS) {
      expect(Object.keys(row)).not.toEqual(expect.arrayContaining(forbidden));
    }
  });
});
