import type { PagesFunction } from "@cloudflare/workers-types";
import { LIMITS } from "../../src/config.js";
import { parseRemovals, parseSyncBody } from "../../src/sync.js";
import { pageForSync, removeJobs, syncJobs } from "../../src/tracker.js";

type Env = { DB: D1Database };

const noStore = { "cache-control": "no-store" };

// A page of rows after the `after` cursor. `next` is null on the last page.
export const onRequestGet: PagesFunction<Env> = async ({ request, env }) => {
  const after = new URL(request.url).searchParams.get("after") ?? "";
  if (after.length > 100) return Response.json({ error: "invalid cursor" }, { status: 400, headers: noStore });
  const applications = await pageForSync(env.DB, after, LIMITS.maxRows);
  const next = applications.length === LIMITS.maxRows ? (applications.at(-1)?.id ?? null) : null;
  return Response.json({ applications, next }, { headers: noStore });
};

export const onRequestPost: PagesFunction<Env> = async ({ request, env }) => {
  let body: unknown;
  try {
    body = await request.json();
  } catch {
    return Response.json({ error: "invalid JSON" }, { status: 400, headers: noStore });
  }
  const parsed = parseSyncBody(body);
  const removals = parseRemovals((body as { remove?: unknown } | null)?.remove);
  if (!parsed || removals === null) {
    return Response.json({ error: "invalid sync payload" }, { status: 400, headers: noStore });
  }
  const ids = parsed.applications.map((row) => row.id);
  if (new Set(ids).size !== ids.length || ids.some((id) => removals.includes(id))) {
    return Response.json({ error: "duplicate job id" }, { status: 400, headers: noStore });
  }
  const result = await syncJobs(env.DB, parsed.applications, new Date().toISOString());
  if (result.conflicts.length) {
    return Response.json({ error: "version conflict", ...result }, { status: 409, headers: noStore });
  }
  const removed = await removeJobs(env.DB, removals);
  return Response.json({ accepted: result.accepted, count: result.accepted.length, removed }, { headers: noStore });
};
