# Phone snapshot

A static, read-only view of the board, for reading on a phone. Decided in
[ADR 0009](../docs/adr/0009-phone-snapshot.md).

`public/` is the whole thing: four files and no build step. No framework, no
`package.json`, no database, no API, no write route. The page reads
`snapshot.json` sitting beside it and renders it.

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
