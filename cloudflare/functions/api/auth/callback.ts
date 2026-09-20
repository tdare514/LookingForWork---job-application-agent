import type { PagesFunction } from "@cloudflare/workers-types";
import { cookie, csrfCookie, denied, open, parseCookies, randomToken } from "../../../src/auth.js";
import { readAuthConfig } from "../../../src/config.js";

type Env = {
  DB: D1Database;
  GITHUB_CLIENT_ID?: string;
  GITHUB_CALLBACK_URL?: string;
  OWNER_GITHUB_ID?: string;
  SESSION_SECRET?: string;
  GITHUB_CLIENT_SECRET?: string;
};

export const onRequestGet: PagesFunction<Env> = async ({ request, env }) => {
  const config = readAuthConfig(env as unknown as Record<string, string | undefined>);
  if (!config) return Response.json({ error: "authentication unavailable" }, { status: 503 });
  const url = new URL(request.url);
  const code = url.searchParams.get("code");
  const state = url.searchParams.get("state");
  const transaction = parseCookies(request.headers.get("cookie")).get("jobagent_oauth");
  if (!code || !state || !transaction) return denied();
  const stored = await open(transaction, config.sessionSecret);
  if (!stored) return denied();
  const row = await env.DB.prepare("SELECT verifier, expires_at FROM oauth_states WHERE state = ?")
    .bind(state).first<{ verifier: string; expires_at: string }>();
  if (!row || new Date(row.expires_at).getTime() <= Date.now()) return denied();
  let values: { state: string };
  try {
    values = JSON.parse(stored) as { state: string };
  } catch {
    return denied();
  }
  if (values.state !== state) return denied();

  if (!env.GITHUB_CLIENT_SECRET) return Response.json({ error: "authentication unavailable" }, { status: 503 });
  const tokenResponse = await fetch("https://github.com/login/oauth/access_token", {
    method: "POST",
    headers: { accept: "application/json", "content-type": "application/json" },
    body: JSON.stringify({ client_id: config.githubClientId, client_secret: env.GITHUB_CLIENT_SECRET, code, redirect_uri: config.githubCallbackUrl, code_verifier: row.verifier }),
  });
  if (!tokenResponse.ok) return denied();
  const token = (await tokenResponse.json()) as { access_token?: string };
  if (!token.access_token) return denied();
  const identityHeaders = new Headers();
  identityHeaders.set("authorization", "Bearer " + token.access_token);
  identityHeaders.set("user-agent", "jobagent-companion");
  const identityResponse = await fetch("https://api.github.com/user", { headers: identityHeaders });
  if (!identityResponse.ok) return denied();
  const identity = (await identityResponse.json()) as { id?: number };
  if (identity.id === undefined || String(identity.id) !== config.ownerGithubId) return denied();
  await env.DB.prepare("DELETE FROM oauth_states WHERE state = ?").bind(state).run();
  const sessionId = randomToken();
  const now = new Date();
  const expires = new Date(now.getTime() + 86_400_000);
  await env.DB.prepare("INSERT INTO owner_sessions (id, owner_github_id, created_at, expires_at) VALUES (?, ?, ?, ?)")
    .bind(sessionId, config.ownerGithubId, now.toISOString(), expires.toISOString()).run();
  const headers = new Headers({ location: "/" });
  headers.append("set-cookie", cookie("jobagent_oauth", "", 0));
  headers.append("set-cookie", cookie("jobagent_session", sessionId, 86_400));
  headers.append("set-cookie", csrfCookie(randomToken()));
  return new Response(null, { status: 302, headers });
};
