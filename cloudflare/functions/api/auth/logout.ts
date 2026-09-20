import type { PagesFunction } from "@cloudflare/workers-types";
import { cookie, parseCookies } from "../../../src/auth.js";

type Env = { DB: D1Database };

export const onRequestPost: PagesFunction<Env> = async ({ request, env }) => {
  const session = parseCookies(request.headers.get("cookie")).get("jobagent_session");
  if (session) await env.DB.prepare("UPDATE owner_sessions SET revoked_at = ? WHERE id = ?").bind(new Date().toISOString(), session).run();
  const headers = new Headers();
  headers.append("set-cookie", cookie("jobagent_session", "", 0));
  headers.append("set-cookie", cookie("jobagent_csrf", "", 0));
  return new Response(null, { status: 204, headers });
};
