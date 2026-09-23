import type { PagesFunction } from "@cloudflare/workers-types";
import { parseSyncBody } from "../../src/sync.js";
import { syncJobs } from "../../src/tracker.js";

type Env = { DB: D1Database };

const noStore = { "cache-control": "no-store" };

export const onRequestPost: PagesFunction<Env> = async ({ request, env }) => {
  let body: unknown;
  try {
    body = await request.json();
  } catch {
    return Response.json({ error: "invalid JSON" }, { status: 400, headers: noStore });
  }
  const parsed = parseSyncBody(body);
  if (!parsed) return Response.json({ error: "invalid sync payload" }, { status: 400, headers: noStore });
  const ids = parsed.applications.map((row) => row.id);
  if (new Set(ids).size !== ids.length) {
    return Response.json({ error: "duplicate job id" }, { status: 400, headers: noStore });
  }
  const result = await syncJobs(env.DB, parsed.applications, new Date().toISOString());
  if (result.conflicts.length) {
    return Response.json({ error: "version conflict", ...result }, { status: 409, headers: noStore });
  }
  return Response.json({ accepted: result.accepted, count: result.accepted.length }, { headers: noStore });
};
