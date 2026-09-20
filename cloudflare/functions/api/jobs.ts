import type { PagesFunction } from "@cloudflare/workers-types";
import { clampLimit } from "../../src/config.js";

type Env = { DB: D1Database };

export const onRequestGet: PagesFunction<Env> = async ({ request, env }) => {
  const url = new URL(request.url);
  const limit = clampLimit(url.searchParams.get("limit"));
  const result = await env.DB.prepare(
    "SELECT id, company, title, location, url FROM jobs ORDER BY created_at DESC LIMIT ?",
  )
    .bind(limit)
    .all();

  return Response.json({ jobs: result.results, limit });
};
