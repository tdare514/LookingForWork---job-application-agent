# Cloudflare companion scaffold

This is the first, deliberately small companion slice for `jobagent`: a static
Cloudflare Pages frontend and same-origin Pages Functions API backed by a local
D1-compatible schema. The Python application and its local dossier remain the
source of truth. The seed migration contains synthetic examples only.

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

Run focused checks with `npm test` and `npm run typecheck`.

## Safety boundary

This scaffold does **not** create Cloudflare resources, deploy, or require
credentials. Do not add credentials to this directory. There are no paid
services, Workers AI, queues, pipelines, email, analytics, premium
observability, or custom-domain assumptions.

The API has explicit free-tier-safe limits: 50 returned rows, a 16 KiB body
budget for future write routes, and 30 requests per client per 60 seconds.
The in-memory limiter is only a local/dev guard; it is not a distributed quota.
Future write routes must enforce the body limit and validate input before D1.
Security headers are applied by the Pages middleware. No route submits an
application or sends dossier data.
