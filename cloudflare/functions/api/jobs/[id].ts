import type { PagesFunction } from "@cloudflare/workers-types";
import { parseSyncBody } from "../../../src/sync.js";
import { updateJob } from "../../../src/tracker.js";

type Env = { DB: D1Database };

const noStore = { "cache-control": "no-store" };

export const onRequestPut: PagesFunction<Env> = async ({ request, env, params }) => {
  const expectedVersion = Number.parseInt(request.headers.get("if-match") ?? "", 10);
  if (!Number.isInteger(expectedVersion) || expectedVersion < 1) {
    return Response.json({ error: "If-Match version is required" }, { status: 428, headers: noStore });
  }
  let body: unknown;
  try {
    body = await request.json();
  } catch {
    return Response.json({ error: "invalid JSON" }, { status: 400, headers: noStore });
  }
  if (!body || typeof body !== "object" || Array.isArray(body)) {
    return Response.json({ error: "invalid tracker fields" }, { status: 400, headers: noStore });
  }
  const parsed = parseSyncBody({ applications: [{ ...body, id: params.id, version: expectedVersion }] });
  const row = parsed?.applications[0];
  if (!row) return Response.json({ error: "invalid tracker fields" }, { status: 400, headers: noStore });

  const result = await updateJob(env.DB, row, expectedVersion, new Date().toISOString());
  if (result.outcome === "missing") return Response.json({ error: "no such job" }, { status: 404, headers: noStore });
  if (result.outcome === "conflict") {
    return Response.json({ error: "version conflict", version: result.version }, { status: 409, headers: noStore });
  }
  return Response.json(result.row, { headers: noStore });
};
