// Every SQL statement the tracker routes run. Kept out of functions/ so the
// tests execute exactly this SQL against a real SQLite.
import type { SyncApplication, TrackerApplication } from "./types.js";

const COLUMNS = `id, company, title, location, url, deadline, status,
  next_action AS nextAction, next_action_date AS nextActionDate,
  updated_at AS updatedAt, version`;

export async function listJobs(db: D1Database, limit: number): Promise<TrackerApplication[]> {
  const result = await db
    .prepare(`SELECT ${COLUMNS} FROM jobs ORDER BY COALESCE(deadline, '9999-12-31'), updated_at DESC LIMIT ?`)
    .bind(limit)
    .all<TrackerApplication>();
  return result.results;
}

export type UpdateResult =
  | { outcome: "updated"; row: TrackerApplication }
  | { outcome: "missing" }
  | { outcome: "conflict"; version: number };

export async function updateJob(
  db: D1Database,
  row: SyncApplication,
  expectedVersion: number,
  now: string,
): Promise<UpdateResult> {
  const result = await db
    .prepare(
      `UPDATE jobs SET company = ?, title = ?, location = ?, url = ?, deadline = ?, status = ?,
        next_action = ?, next_action_date = ?, version = version + 1, updated_at = ?
       WHERE id = ? AND version = ?`,
    )
    .bind(
      row.company, row.title, row.location, row.url, row.deadline, row.status,
      row.nextAction, row.nextActionDate, now, row.id, expectedVersion,
    )
    .run();
  const current = await db.prepare(`SELECT ${COLUMNS} FROM jobs WHERE id = ?`).bind(row.id).first<TrackerApplication>();
  if (!current) return { outcome: "missing" };
  if (!result.meta.changes) return { outcome: "conflict", version: current.version };
  return { outcome: "updated", row: current };
}

export type SyncResult = { accepted: string[]; conflicts: { id: string; version: number | undefined }[] };

// A row the server has never seen is inserted at version 1. A row it has seen
// is written only if the client names the version it currently holds. Stale
// rows are reported, never overwritten, and nothing is written if any row is
// stale when the batch is checked.
export async function syncJobs(db: D1Database, rows: SyncApplication[], now: string): Promise<SyncResult> {
  const current = new Map<string, number>();
  if (rows.length) {
    const placeholders = rows.map(() => "?").join(", ");
    const result = await db
      .prepare(`SELECT id, version FROM jobs WHERE id IN (${placeholders})`)
      .bind(...rows.map((row) => row.id))
      .all<{ id: string; version: number }>();
    for (const row of result.results) current.set(row.id, row.version);
  }
  const stale = rows.filter((row) => current.has(row.id) && current.get(row.id) !== row.version);
  if (stale.length) {
    return { accepted: [], conflicts: stale.map((row) => ({ id: row.id, version: current.get(row.id) })) };
  }
  if (!rows.length) return { accepted: [], conflicts: [] };

  const statements = rows.map((row) =>
    db
      .prepare(
        `INSERT INTO jobs (id, company, title, location, url, deadline, status,
          next_action, next_action_date, created_at, updated_at, version)
         VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 1)
         ON CONFLICT(id) DO UPDATE SET company = excluded.company, title = excluded.title,
          location = excluded.location, url = excluded.url, deadline = excluded.deadline,
          status = excluded.status, next_action = excluded.next_action,
          next_action_date = excluded.next_action_date, updated_at = excluded.updated_at,
          version = jobs.version + 1
         WHERE jobs.version = ?`,
      )
      .bind(
        row.id, row.company, row.title, row.location, row.url, row.deadline, row.status,
        row.nextAction, row.nextActionDate, now, now, row.version,
      ),
  );
  const results = await db.batch(statements);
  // A write that raced this batch leaves its row unchanged here; say so rather
  // than reporting it accepted.
  const accepted: string[] = [];
  const conflicts: SyncResult["conflicts"] = [];
  rows.forEach((row, index) => {
    if (results[index]?.meta.changes) accepted.push(row.id);
    else conflicts.push({ id: row.id, version: undefined });
  });
  return { accepted, conflicts };
}
