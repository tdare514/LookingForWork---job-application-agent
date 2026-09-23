import type { PagesFunction } from "@cloudflare/workers-types";
import { cookie, randomToken, seal } from "../../../src/auth.js";
import { readAuthConfig } from "../../../src/config.js";

type Env = { DB: D1Database; GITHUB_CLIENT_ID?: string; GITHUB_CALLBACK_URL?: string; SESSION_SECRET?: string; OWNER_GITHUB_ID?: string };

export const onRequestGet: PagesFunction<Env> = async ({ env }) => {
  const config = readAuthConfig(env as unknown as Record<string, string | undefined>);
  if (!config) return Response.json({ error: "authentication unavailable" }, { status: 503 });
  // Abandoned logins would otherwise accumulate for ever.
  await env.DB.prepare("DELETE FROM oauth_states WHERE expires_at <= ?").bind(new Date().toISOString()).run();
  const state = randomToken();
  const verifier = randomToken(48);
  await env.DB.prepare("INSERT INTO oauth_states (state, verifier, expires_at) VALUES (?, ?, ?)")
    .bind(state, verifier, new Date(Date.now() + 600_000).toISOString()).run();
  const transaction = await seal(JSON.stringify({ state, verifier, issuedAt: Date.now() }), config.sessionSecret);
  const authorize = new URL("https://github.com/login/oauth/authorize");
  authorize.searchParams.set("client_id", config.githubClientId);
  authorize.searchParams.set("redirect_uri", config.githubCallbackUrl);
  authorize.searchParams.set("state", state);
  authorize.searchParams.set("code_challenge", await challenge(verifier));
  authorize.searchParams.set("code_challenge_method", "S256");
  return new Response(null, {
    status: 302,
    headers: { location: authorize.toString(), "set-cookie": cookie("jobagent_oauth", transaction, 600) },
  });
};

async function challenge(verifier: string): Promise<string> {
  return btoa(String.fromCharCode(...new Uint8Array(await crypto.subtle.digest("SHA-256", new TextEncoder().encode(verifier)))))
    .replaceAll("+", "-").replaceAll("/", "_").replaceAll("=", "");
}
