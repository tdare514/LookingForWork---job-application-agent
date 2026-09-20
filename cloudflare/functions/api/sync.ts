import type { PagesFunction } from "@cloudflare/workers-types";
import { parseSyncBody } from "../../src/sync.js";
import type { SyncApplication } from "../../src/types.js";

type Env = { DB: D1Database };

export const onRequestPost: PagesFunction<Env> = async ({ request, env }) => {
  let body: unknown;
  try {
    body = await request.json();
  } catch {
    return Response.json({ error: "invalid JSON" }, { status: 400 });
  }
  const parsed = parseSyncBody(body);
  if (!parsed) return Response.json({ error: "invalid sync payload" }, { status: 400 });
  const ids = parsed.applications.map((row) => row.id);
  if (new Set(ids).size !== ids.length) return Response.json({ error: "duplicate job id" }, { status: 400 });
  const current = new Map<string, SyncApplication>();
  if (ids.length) {
    const placeholders = ids.map(() => "?").join(", ");
    const result = await env.DB.prepare(
      `SELECT id, company, title, location, url, deadline, status, notes,
        next_action AS nextAction, next_action_date AS nextActionDate, version
       FROM jobs WHERE id IN (${placeholders})`,
    ).bind(...ids).all<SyncApplication>();
    for (const row of result.results) current.set(row.id, row);
  }
  const conflicts = parsed.applications
    .filter((row) => current.has(row.id) && current.get(row.id)?.version !== row.version)
    .map((row) => ({ id: row.id, version: current.get(row.id)?.version }));
  if (conflicts.length) return Response.json({ error: "version conflict", conflicts }, { status: 409 });

  const now = new Date().toISOString();
  const statements = parsed.applications.map((row) => env.DB.prepare(
    `INSERT INTO jobs (id, company, title, location, url, deadline, status, notes,
      next_action, next_action_date, created_at, updated_at, version)
     VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 1)
     ON CONFLICT(id) DO UPDATE SET company = excluded.company, title = excluded.title,
      location = excluded.location, url = excluded.url, deadline = excluded.deadline,
      status = excluded.status, notes = excluded.notes, next_action = excluded.next_action,
      next_action_date = excluded.next_action_date, updated_at = excluded.updated_at,
      version = jobs.version + 1
     WHERE jobs.version = excluded.version`,
  ).bind(
    row.id, row.company, row.title, row.location, row.url, row.deadline, row.status,
    row.notes, row.nextAction, row.nextActionDate, now, now, row.version,
  ));
  if (statements.length) await env.DB.batch(statements);
  return Response.json({ accepted: parsed.applications.map((row) => row.id), count: parsed.applications.length }, {
    headers: { "cache-control": "no-store" },
  });
};
