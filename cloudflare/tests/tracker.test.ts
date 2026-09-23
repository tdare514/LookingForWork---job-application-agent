import { beforeEach, describe, expect, it } from "vitest";
import { onRequestPost as postSync } from "../functions/api/sync.js";
import { listJobs, syncJobs, updateJob } from "../src/tracker.js";
import type { SyncApplication } from "../src/types.js";
import { TestD1 } from "./d1.js";

const NOW = "2026-09-22T12:00:00Z";
let d1: TestD1;

const row = (overrides: Partial<SyncApplication> = {}): SyncApplication => ({
  id: "synthetic-100",
  company: "Example East",
  title: "Data Analyst Co-op",
  location: "Ottawa, ON",
  url: "https://example.invalid/jobs/100",
  deadline: "2026-10-01",
  status: "new",
  nextAction: null,
  nextActionDate: null,
  version: 0,
  ...overrides,
});

const versionOf = (id: string) =>
  (d1.db.prepare("SELECT version FROM jobs WHERE id = ?").get(id) as { version: number } | undefined)?.version;

beforeEach(() => {
  d1 = new TestD1();
});

describe("migrations", () => {
  it("leave no notes column and only local board states", () => {
    const columns = (d1.db.prepare("PRAGMA table_info(jobs)").all() as { name: string }[]).map((c) => c.name);
    expect(columns).not.toContain("notes");
    const statuses = (d1.db.prepare("SELECT DISTINCT status FROM jobs").all() as { status: string }[]).map((r) => r.status);
    expect(statuses.sort()).toEqual(["ready"]);
  });
});

describe("syncJobs", () => {
  it("inserts an unseen row at version 1", async () => {
    expect(await syncJobs(d1.asD1(), [row()], NOW)).toEqual({ accepted: ["synthetic-100"], conflicts: [] });
    expect(versionOf("synthetic-100")).toBe(1);
  });

  it("keeps accepting a row as its version advances", async () => {
    // The regression: the upsert once compared against a hard-coded 1, so the
    // third sync of a row silently wrote nothing and still reported success.
    await syncJobs(d1.asD1(), [row()], NOW);
    for (const version of [1, 2, 3]) {
      const result = await syncJobs(d1.asD1(), [row({ version, status: "applied" })], NOW);
      expect(result).toEqual({ accepted: ["synthetic-100"], conflicts: [] });
      expect(versionOf("synthetic-100")).toBe(version + 1);
    }
  });

  it("refuses a stale row and writes nothing in that batch", async () => {
    await syncJobs(d1.asD1(), [row()], NOW);
    await syncJobs(d1.asD1(), [row({ version: 1, status: "applied" })], NOW);
    const result = await syncJobs(d1.asD1(), [row({ id: "synthetic-101", version: 0 }), row({ version: 1, status: "skipped" })], NOW);
    expect(result).toEqual({ accepted: [], conflicts: [{ id: "synthetic-100", version: 2 }] });
    expect(versionOf("synthetic-101")).toBeUndefined();
    expect((d1.db.prepare("SELECT status FROM jobs WHERE id = 'synthetic-100'").get() as { status: string }).status).toBe("applied");
  });
});

describe("updateJob", () => {
  it("writes at the version read, and reports a stale or missing row", async () => {
    await syncJobs(d1.asD1(), [row()], NOW);
    const updated = await updateJob(d1.asD1(), row({ status: "ready", nextAction: "Tailor resume" }), 1, NOW);
    expect(updated).toMatchObject({ outcome: "updated", row: { status: "ready", nextAction: "Tailor resume", version: 2 } });
    expect(await updateJob(d1.asD1(), row({ status: "skipped" }), 1, NOW)).toEqual({ outcome: "conflict", version: 2 });
    expect(await updateJob(d1.asD1(), row({ id: "nope" }), 1, NOW)).toEqual({ outcome: "missing" });
  });
});

describe("listJobs", () => {
  it("returns tracker fields only, deadline first", async () => {
    const rows = await listJobs(d1.asD1(), 50);
    expect(rows.map((r) => r.id)).toEqual(["synthetic-001", "synthetic-002"]);
    expect(Object.keys(rows[0] ?? {})).not.toContain("notes");
  });
});

describe("POST /api/sync", () => {
  const post = async (body: unknown) => {
    const request = new Request("https://companion.example.invalid/api/sync", {
      method: "POST",
      body: JSON.stringify(body),
    });
    const handler = postSync as unknown as (c: object) => Promise<Response>;
    return handler({ request, env: { DB: d1.asD1() } });
  };

  it("accepts a fresh row, then 409s the same stale write", async () => {
    const first = await post({ applications: [row()] });
    expect(first.status).toBe(200);
    expect(await first.json()).toEqual({ accepted: ["synthetic-100"], count: 1 });
    expect((await post({ applications: [row()] })).status).toBe(409);
  });

  it("refuses notes outright", async () => {
    expect((await post({ applications: [{ ...row(), notes: "names a recruiter" }] })).status).toBe(400);
  });
});
