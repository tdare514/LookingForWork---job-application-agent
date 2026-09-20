import type { PagesFunction } from "@cloudflare/workers-types";
import { clampLimit } from "../../src/config.js";
import { SYNTHETIC_APPLICATIONS } from "../../src/fixtures.js";
import type { TrackerApplication, TrackerResponse } from "../../src/types.js";

type Env = { DB?: D1Database };

export const onRequestGet: PagesFunction<Env> = async ({ request, env }) => {
  const url = new URL(request.url);
  const limit = clampLimit(url.searchParams.get("limit"));
  let applications: TrackerApplication[] = SYNTHETIC_APPLICATIONS;

  if (env.DB) {
    const result = await env.DB.prepare(
      `SELECT id, company, title, location, url, deadline, status, notes,
        next_action AS nextAction, next_action_date AS nextActionDate,
        updated_at AS updatedAt, version
       FROM jobs ORDER BY COALESCE(deadline, '9999-12-31'), updated_at DESC LIMIT ?`,
    )
      .bind(limit)
      .all<TrackerApplication>();
    applications = result.results;
  }

  const response: TrackerResponse = {
    applications: applications.slice(0, limit),
    limit,
    source: env.DB ? "d1" : "synthetic",
  };
  return Response.json(response, {
    headers: { "Cache-Control": "no-store" },
  });
};
