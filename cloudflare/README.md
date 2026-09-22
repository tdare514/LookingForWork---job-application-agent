# Cloudflare companion scaffold

This is a deliberately small companion slice for `jobagent`: a mobile-first,
installable Cloudflare Pages tracker and same-origin Pages Functions API backed
by a local D1-compatible schema. It shows application status, deadlines, notes,
and next actions using an explicit allowlisted TypeScript contract. The Python
application and its local dossier remain the source of truth. The seed
migration and offline snapshot contain synthetic examples only.

## Local development

```sh
cd cloudflare
npm install
npx wrangler pages dev public
```

The local Pages server serves `public/` and routes `/api/health` and
`/api/jobs` through `functions/`. To initialize a local D1 database, use a
local database name and the checked-in migration:

```sh
npx wrangler d1 migrations apply jobagent-local --local
```

Without a D1 binding, `/api/jobs` serves the checked-in synthetic fixtures.
The UI caches the last successful fixture response for read-only offline
viewing and labels it as an offline snapshot. It has no write route and no
application-submission path.

Run focused checks with `npm test` and `npm run typecheck`.

## Synthetic dev deployment

Remote deployment is deliberately separate from local development and is
fail-closed. It requires a Cloudflare API token with Account Read, Pages write,
and D1 write permissions, plus the account ID. The free-plan check validates
account access and requires the operator to explicitly configure
`FREE_TIER_ENABLED=true` and `ACCOUNT_PLAN=free`; it does not infer billing
from an endpoint that may require unavailable Billing Read permission. OAuth
login is not configured by this procedure; do not add a callback URL or secrets
for a synthetic deploy.

After confirming that the account is free-only, create only the clearly named
development resources:

```sh
export CLOUDFLARE_ACCOUNT_ID=...
export CLOUDFLARE_API_TOKEN=...
export FREE_TIER_ENABLED=true
export ACCOUNT_PLAN=free
npm run verify:free
npx wrangler d1 create jobagent-companion-dev --location enam
npx wrangler pages project create jobagent-companion-dev --production-branch main
cp wrangler.dev.toml.example wrangler.dev.toml
# Replace REPLACE_WITH_DEV_D1_UUID with the UUID printed by d1 create.
export CF_DEV_PAGES_PROJECT=jobagent-companion-dev
export CF_DEV_D1_DATABASE_ID=...
npm run deploy:dev
```

`verify:free` rejects missing credentials, account-access errors, missing free
configuration, and any plan other than the explicitly configured `free` value.
`deploy:dev` also rejects a non-dev Pages name, a non-UUID D1 binding, a
missing config, or paid-feature bindings before invoking Wrangler. Pages
rejects `--config` when it names a custom file, so the script stages the
validated `wrangler.dev.toml` as the default `wrangler.toml`, along with the
`public/`, `functions/`, and `src/` trees, in a temporary directory before
invoking the supported Pages deploy command. Including `src/` preserves the
relative imports used by the TypeScript Pages Functions bundle. The temporary
directory is removed afterward. It does not create resources, set secrets,
upload real data, or deploy the OAuth callback.

If the account plan check or the required Cloudflare API token is unavailable,
stop rather than using the interactive Wrangler OAuth token as a substitute.
If GitHub OAuth is later enabled, its exact callback URL is a separate
operator decision and must be configured before testing authenticated routes.

## Safety boundary

This scaffold does **not** create Cloudflare resources, deploy, or require
credentials. Do not add credentials to this directory. There are no paid
services, Workers AI, queues, pipelines, email, analytics, premium
observability, or custom-domain assumptions.

The API fails closed unless `FREE_TIER_ENABLED=true`, `ACCOUNT_PLAN=free`, and
`DAILY_REQUEST_QUOTA` is a positive value no greater than 1,000. It then
enforces explicit free-tier-safe limits: 50 returned rows, a 16 KiB body
budget, and 30 requests per client per 60 seconds, with a daily request quota.
The in-memory limiter is only a local/dev guard; it is not a distributed quota.
Future write routes must validate input before D1.

## Authentication foundation

`/api/auth/github` starts GitHub OAuth with an encrypted, short-lived
HttpOnly transaction cookie and PKCE. The callback accepts only the configured
numeric `OWNER_GITHUB_ID`, stores a rotated opaque session in D1, and never
persists the provider token. Set `GITHUB_CLIENT_ID`, `GITHUB_CLIENT_SECRET`,
`GITHUB_CALLBACK_URL`, `OWNER_GITHUB_ID`, and a randomly generated
`SESSION_SECRET` (at least 32 characters) as deployment secrets/variables.
Authenticated API requests require the session cookie; state-changing requests
also require the same-origin `jobagent_csrf` cookie value in
`X-CSRF-Token`. Logout revokes the D1 session.
Security headers are applied by the Pages middleware. No route submits an
application or sends dossier data.
