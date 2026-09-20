import type { PagesFunction } from "@cloudflare/workers-types";
import { parseSyncBody } from "../../../src/sync.js";
import type { TrackerApplication } from "../../../src/types.js";

type Env = { DB: D1Database };

export const onRequestPut: PagesFunction<Env> = async ({ request, env, params }) => {
  const expectedVersion = Number.parseInt(request.headers.get("if-match") ?? "", 10);
  if (!Number.isInteger(expectedVersion) || expectedVersion < 1) {
    return Response.json({ error: "If-Match version is required" }, { status: 428 });
  }
  let body: unknown;
  try {
    body = await request.json();
  } catch {
    return Response.json({ error: "invalid JSON" }, { status: 400 });
  }
  const parsed = parseSyncBody({ applications: [{ ...(body as object), id: params.id, version: expectedVersion }] });
  if (!parsed) return Response.json({ error: "invalid tracker fields" }, { status: 400 });
  const row = parsed.applications[0];
  const now = new Date().toISOString();
  const result = await env.DB.prepare(
    `UPDATE jobs SET company = ?, title = ?, location = ?, url = ?, deadline = ?, status = ?,
      notes = ?, next_action = ?, next_action_date = ?, version = version + 1, updated_at = ?
     WHERE id = ? AND version = ?`,
  ).bind(
    row.company, row.title, row.location, row.url, row.deadline, row.status, row.notes,
    row.nextAction, row.nextActionDate, now, row.id, expectedVersion,
  ).run();
  if (!result.meta.changes) {
    return Response.json({ error: "version conflict" }, { status: 409 });
  }
  const updated = await env.DB.prepare(
    `SELECT id, company, title, location, url, deadline, status, notes,
      next_action AS nextAction, next_action_date AS nextActionDate,
      updated_at AS updatedAt, version FROM jobs WHERE id = ?`,
  ).bind(row.id).first<TrackerApplication>();
  return Response.json(updated, { headers: { "cache-control": "no-store" } });
};
