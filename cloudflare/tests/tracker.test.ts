import { beforeEach, describe, expect, it } from "vitest";
import { onRequestPost as postPurge } from "../functions/api/purge.js";
import { onRequestGet as getSync, onRequestPost as postSync } from "../functions/api/sync.js";
import { LIMITS } from "../src/config.js";
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
    expect(await syncJobs(d1.asD1(), [row()], NOW)).toEqual({
      accepted: [{ id: "synthetic-100", version: 1 }],
      conflicts: [],
    });
    expect(versionOf("synthetic-100")).toBe(1);
  });

  it("keeps accepting a row as its version advances", async () => {
    // The regression: the upsert once compared against a hard-coded 1, so the
    // third sync of a row silently wrote nothing and still reported success.
    await syncJobs(d1.asD1(), [row()], NOW);
    for (const version of [1, 2, 3]) {
      const result = await syncJobs(d1.asD1(), [row({ version, status: "applied" })], NOW);
      expect(result).toEqual({ accepted: [{ id: "synthetic-100", version: version + 1 }], conflicts: [] });
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
    expect(await first.json()).toEqual({ accepted: [{ id: "synthetic-100", version: 1 }], count: 1, removed: 0 });
    expect((await post({ applications: [row()] })).status).toBe(409);
  });

  it("refuses notes outright", async () => {
    expect((await post({ applications: [{ ...row(), notes: "names a recruiter" }] })).status).toBe(400);
  });
});

describe("GET /api/sync", () => {
  const get = async (after?: string) => {
    const url = `https://companion.example.invalid/api/sync${after ? `?after=${after}` : ""}`;
    const handler = getSync as unknown as (c: object) => Promise<Response>;
    return (await handler({ request: new Request(url), env: { DB: d1.asD1() } })).json() as Promise<{
      applications: SyncApplication[];
      next: string | null;
    }>;
  };

  it("pages through every row by id, including the phone-only fields", async () => {
    const rows = Array.from({ length: LIMITS.maxRows + 3 }, (_, i) => row({ id: `row-${String(i).padStart(3, "0")}` }));
    for (let i = 0; i < rows.length; i += LIMITS.maxRows) await syncJobs(d1.asD1(), rows.slice(i, i + LIMITS.maxRows), NOW);
    const first = await get();
    expect(first.applications).toHaveLength(LIMITS.maxRows);
    expect(first.next).not.toBeNull();
    const second = await get(first.next ?? "");
    expect(second.next).toBeNull();
    const ids = [...first.applications, ...second.applications].map((r) => r.id);
    expect(ids).toContain("synthetic-001");
    expect(new Set(ids).size).toBe(LIMITS.maxRows + 3 + 2);
    expect(Object.keys(first.applications[0] ?? {})).toEqual(
      ["id", "company", "title", "location", "url", "deadline", "status", "nextAction", "nextActionDate", "version"],
    );
  });
});

describe("POST /api/sync removals and empty urls", () => {
  const post = async (body: unknown) => {
    const request = new Request("https://companion.example.invalid/api/sync", { method: "POST", body: JSON.stringify(body) });
    return (postSync as unknown as (c: object) => Promise<Response>)({ request, env: { DB: d1.asD1() } });
  };

  it("removes rows the laptop no longer has, and accepts a row with no posting url", async () => {
    const response = await post({ applications: [row({ url: "" })], remove: ["synthetic-001"] });
    expect(response.status).toBe(200);
    expect((await response.json()).removed).toBe(1);
    expect(d1.db.prepare("SELECT id FROM jobs WHERE id = 'synthetic-001'").get()).toBeUndefined();
  });

  it("refuses to both write and remove one id, and a non-http url", async () => {
    expect((await post({ applications: [row()], remove: ["synthetic-100"] })).status).toBe(400);
    expect((await post({ applications: [row({ url: "javascript:alert(1)" })] })).status).toBe(400);
  });

  it("removes nothing when the batch has a conflict", async () => {
    await syncJobs(d1.asD1(), [row()], NOW);
    expect((await post({ applications: [row({ version: 0 })], remove: ["synthetic-001"] })).status).toBe(409);
    expect(d1.db.prepare("SELECT id FROM jobs WHERE id = 'synthetic-001'").get()).toBeDefined();
  });
});

describe("POST /api/purge", () => {
  it("empties every table and says so", async () => {
    d1.db.prepare("INSERT INTO owner_sessions (id, owner_github_id, created_at, expires_at) VALUES ('s', '1', 'x', 'y')").run();
    const handler = postPurge as unknown as (c: object) => Promise<Response>;
    const response = await handler({ request: new Request("https://x.invalid/api/purge", { method: "POST" }), env: { DB: d1.asD1() } });
    expect(response.status).toBe(200);
    const body = await response.json();
    expect(body).toMatchObject({ clean: true, removed: { jobs: 2, owner_sessions: 1 } });
    expect(body.remaining).toEqual({ jobs: 0, owner_sessions: 0, oauth_states: 0 });
  });
});
