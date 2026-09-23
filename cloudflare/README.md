# Phone view

Two things live here:

- **The snapshot** ([ADR 0009](../docs/adr/0009-phone-snapshot.md), accepted):
  `public/` is a static, read-only page that renders `snapshot.json` sitting
  beside it. No build step, no API, no write route. Everything from *What it
  carries* to *Local check* below is about this.
- **The hosted companion** ([ADR 0010](../docs/adr/0010-hosted-tracker-companion.md),
  accepted): Pages Functions, a D1 database and owner-only writes. It is built
  and tested against synthetic data only. See *Companion* at the end.

## What it carries

One row per live board entry: `id`, `company`, `title`, `location`, `deadline`,
`state`, `url`. Snoozed rows are left out.

Not carried, ever: `notes` and `state_reason` (free text that names recruiters
and carries judgements), application history and timestamps, scores, the audit
log, the resume, and the profile. The allowlist lives in
`src/jobagent/tracking/snapshot.py` and `tests/test_snapshot.py` enforces it.

## Set it up once

**Configure Cloudflare Access before uploading anything real.** The gate is the
entire mitigation — without it, a Pages URL is readable by anyone who finds it,
and the file names every company on the board along with where each one stands.

1. Create the Pages project (Cloudflare dashboard, or `wrangler pages project create`).
2. Deploy `public/` **while `snapshot.json` does not exist yet**, so the first
   thing published is an empty shell.
3. In Cloudflare Zero Trust → Access → Applications, add a self-hosted
   application covering the project's domain, with a policy that allows your
   email and nothing else.
4. Open the URL in a private window. If it serves the page without asking you to
   log in, the gate is not on. Stop and fix that before step 5.
5. Only then generate and upload a real snapshot.

## Each time

```sh
JOBAGENT_DATA_DIR=... jobagent snapshot cloudflare/public/snapshot.json
npx wrangler pages deploy cloudflare/public --project-name <your-project>
```

`jobagent snapshot` only writes the file. It never uploads: pushing is a
deliberate human act, which is the same rule that keeps the agent from
submitting an application.

`snapshot.json` is covered by `.gitignore` and refused by the pre-commit hook,
because this repository is public.

## Local check

Any static server works, e.g. `python3 -m http.server` from `public/`. With no
`snapshot.json` present the page renders empty and reports "No snapshot", which
is also what a failed fetch looks like.

## Companion

Not for real data until ADR 0010's preconditions are met.

```sh
cd cloudflare
npm ci                  # the locked toolchain; never a bare `npm install`
npm run typecheck
npm test                # also runs in CI
npx wrangler pages dev public
```

The API refuses to serve unless `FREE_TIER_ENABLED=true`, `ACCOUNT_PLAN=free` and
`DAILY_REQUEST_QUOTA` (1–1000) are set, as `wrangler.toml` does for local runs.
It caps rows at 50, bodies at 16 KiB (and refuses a write that does not declare
its length), and requests at 30 per client per minute. The limiter is in memory
per isolate: a brake, not a quota.

### Owner-only sign-in

Cloudflare Access stays in front of everything. Behind it, every API route
except `/api/health` and `/api/auth/*` needs a session, and a write also needs
the request's `Origin` to match and the `jobagent_csrf` cookie echoed in
`X-CSRF-Token`.

`/api/auth/github` starts GitHub OAuth with PKCE and an encrypted, ten-minute,
HttpOnly transaction cookie. The callback admits only the numeric
`OWNER_GITHUB_ID`, consumes the OAuth state whether or not it succeeds, keeps
no GitHub token, and stores a one-day opaque session in D1. Logout revokes it.

Set as deployment variables and secrets, never in a file: `GITHUB_CLIENT_ID`,
`GITHUB_CLIENT_SECRET`, `GITHUB_CALLBACK_URL` (exact), `OWNER_GITHUB_ID`, and
`SESSION_SECRET` (at least 32 characters, e.g. `openssl rand -base64 32`).
Without them the auth routes answer 503. Apply `migrations/` before first use.

### Tracker API

Behind the session gate:

- `GET /api/jobs` — up to 50 rows, deadline first. Without a D1 binding it
  serves two synthetic fixtures and says so (`source: "synthetic"`); the page
  ignores those and falls back to `snapshot.json`.
- `PUT /api/jobs/:id` — replace one row's tracker fields. `If-Match` must carry
  the version read; a stale one is `409` with the current version, never an
  overwrite.
- `POST /api/sync` — up to 50 rows from the laptop. Unseen rows land at
  version 1; seen rows must name their current version. If any row is stale,
  nothing in the batch is written.

The fields are `SYNC_FIELDS` in `src/types.ts`, and a payload carrying any
other field is refused rather than trimmed. `notes` and `state_reason` are not
among them and the table has no column for them; `status` takes exactly the
local board's states. `tests/test_cloudflare_contract.py` fails if either drifts.

All SQL lives in `src/tracker.ts`, and the tests run it against node:sqlite,
which rejects a mis-bound statement just as D1 does.

Not built yet: the local sync client (nothing in `src/jobagent/` calls these
routes), edit controls on the page, and a `purge` that reaches D1. ADR 0010
lists these as preconditions for real data.

### Synthetic dev deployment

Separate from local development, and fail-closed. It needs a Cloudflare API
token with Account Read, Pages write and D1 write, plus the account ID. The
free-plan check confirms the token can read the account and requires you to
declare the plan explicitly; it does not infer billing.

```sh
export CLOUDFLARE_ACCOUNT_ID=... CLOUDFLARE_API_TOKEN=...
export FREE_TIER_ENABLED=true ACCOUNT_PLAN=free
npm run verify:free
npx wrangler d1 create jobagent-companion-dev --location enam
npx wrangler pages project create jobagent-companion-dev --production-branch main
cp wrangler.dev.toml.example wrangler.dev.toml   # fill in the D1 UUID
export CF_DEV_PAGES_PROJECT=jobagent-companion-dev CF_DEV_D1_DATABASE_ID=...
npm run deploy:dev
```

`deploy:dev` refuses a Pages project not named `jobagent-companion-dev`, a
non-UUID D1 id, a config missing the free-tier settings or naming a paid
binding, a `public/snapshot.json` (real rows do not go to a synthetic
project), and a missing `node_modules` (so the locked `wrangler` is the one
that runs). Pages will not take `--config` pointing at a custom file, so the
script stages `public/`, `functions/`, `src/` and the validated config as
`wrangler.toml` in a temporary directory, deploys from there, and removes it.

It creates no resources, sets no secrets and uploads no real data.
