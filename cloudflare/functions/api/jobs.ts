import type { PagesFunction } from "@cloudflare/workers-types";
import { clampLimit } from "../../src/config.js";
import { SYNTHETIC_APPLICATIONS } from "../../src/fixtures.js";
import { listJobs } from "../../src/tracker.js";
import type { TrackerResponse } from "../../src/types.js";

type Env = { DB?: D1Database };

export const onRequestGet: PagesFunction<Env> = async ({ request, env }) => {
  const limit = clampLimit(new URL(request.url).searchParams.get("limit"));
  const applications = env.DB ? await listJobs(env.DB, limit) : SYNTHETIC_APPLICATIONS.slice(0, limit);
  const response: TrackerResponse = { applications, limit, source: env.DB ? "d1" : "synthetic" };
  return Response.json(response, { headers: { "cache-control": "no-store" } });
};
