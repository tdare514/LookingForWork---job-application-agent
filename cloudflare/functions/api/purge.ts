import type { PagesFunction } from "@cloudflare/workers-types";
import { purgeAll } from "../../src/tracker.js";

type Env = { DB: D1Database };

// Called by `jobagent purge`. Deletes every row the companion holds and reports
// what is left, which should be nothing. It cannot reach D1 Time Travel,
// Cloudflare's logs or earlier Pages deployments; the CLI says so.
export const onRequestPost: PagesFunction<Env> = async ({ env }) => {
  const result = await purgeAll(env.DB);
  const clean = Object.values(result.remaining).every((n) => n === 0);
  return Response.json({ ...result, clean }, { status: clean ? 200 : 500, headers: { "cache-control": "no-store" } });
};
