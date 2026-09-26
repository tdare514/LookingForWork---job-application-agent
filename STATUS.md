# Status

Snapshot of **now**, not a changelog. Update it in the same commit as the change that made it stale. Keep it under ~60 lines; git history holds the rest.

Last updated: 2026-09-26

Current focus: Block 2 is done — fetch, extract, filter, score, shortlist, digest. Everything left before the 20th is mine: the company paragraph and the "why this company" answer for the two nearest-deadline applications.

## What works

- `jobagent init` / `status` / `pii` / `audit` — data directory outside the working tree at `0o700`, SQLite with forward-only migrations, append-only audit trail.
- `jobagent add` / `list` / `board` — opportunities tracked one row each, with traffic lights: green sent, yellow wants attention today, red dead. Needs-action sorts first, then by deadline. De-duplicates across company-name variants.
- Claude in Chrome handoff (`c` on the board): opens the posting and copies a prompt that carries my standing answers and forbids both submitting and inventing.
- Profile (`profile.example.yaml`, `jobagent profile set` / `show`): what I am looking for — titles, seniority rungs, locations, must-have skills, deal-breakers, work authorization as a boolean the filters can read, and the scoring weights. The file is an import; the database is what the agent reads. An empty required field is refused, because an empty filter passes everything and looks like it is working.
- Resume source of truth (`resume.example.yaml`, `jobagent resume validate`): every claim the agent may make, each accomplishment carrying its metric and the scope actually held.
- Truthfulness check: a tailored bullet must cite a source accomplishment and may not invent a number, claim more scope than was held, or add breadth. Refuses rather than warns.
- The board closes the loop: `d` drafts the package for a row, `c` stages the Claude in Chrome prompt pointing at the drafted resume, `a` marks it applied. A `Pkg` column shows which rows have one.
- Tailoring (`jobagent draft <job-id>`): selects and orders bullets for one posting, renders a one-page resume to PDF and DOCX, drafts a cover letter, and writes the recurring answers. Bullets are selected verbatim, so selection cannot fabricate.
- 479 tests pass, none skipped. Missing pursue, borderline or skip ranking tiers fail the suite (#76). `make check` runs ruff, strict mypy, pytest and the context check. CI runs the same on push.
- `jobagent followups` — fires at 10 days submitted with no reply, 5 days post-interview, stale at 30. The board shows the count.
- `jobagent fetch <source>` — pulls postings onto the board through a rate-limited client with a host allowlist. Sources: `workday:rbc`, `workday:bmo`, `workday:td`, `greenhouse:<board>` (with `--company`; descriptions come in the list call), or `all` (Workday only). With a profile stored it drops clear location and seniority misses before anything is written (#111) — the two existing filters, which pass anything unknown — and prints the drops per rule, the only record of them. A Greenhouse board is filtered before `--limit`, so the limit keeps relevant postings; `--no-prefilter` turns it off.
- Canonical normalization and de-duplication (#28): one job, many sightings. The same role from two sources collapses; a repost attaches as a sighting rather than a new row; two levels of one title stay separate. Company aliases (`Bank of Montreal` = `BMO`), city-level locations, and a seniority ladder independent of title inflation.
- `jobagent fetch <source> --details` — pulls each posting's description and **closing date** from the source's own posting page. Deadlines fill `jobs.deadline` only when empty, so a date typed in by hand always wins.
- `jobagent extract` — rule-based requirements from posting text (#30): required vs preferred skills, years, compensation, work arrangement, and the closing date. Evaluated against 12 hand-labelled real postings with per-field precision and recall enforced in CI.
- `jobagent import <file>` — a triaged shortlist onto the board (#77). The daily search runs outside this tool; this brings its judgement across with the row, so the fit score, why it fits and what is missing land in the notes, attributed and dated. `apply` becomes needs-you, `maybe` stays new, `skip` is skipped with the reason kept. It never overwrites a hand-typed note, never moves a row already applied to, and never feeds `jobagent score`. `--dry-run` shows what it would do.
- `jobagent report` — funnel with denominators stated, small samples flagged, and a plain "nothing submitted yet" when that is the truth.
- `jobagent export` / `purge` — one archive out, and a delete that verifies nothing recoverable remains.
- `jobagent score` — hard filters then a decomposed score, both stored per job. Filters cut for a stated reason (`--filtered` lists them); absence never cuts, so a posting silent on pay, sponsorship or level is judged, not dropped. `--explain <id>` prints the five components with the weight each carried and a line on what it looked at. A component with nothing to judge on is dropped and the remaining weights rescale, so a row with no description still ranks.
- `jobagent shortlist` / `digest` / `daily` — the reading queue (#32). The digest is four capped sections: new since you last looked, roles whose score moved and which component moved it, reposts with their sighting count, and what the filters cut aggregated by rule. `daily` chains fetch → extract → score → digest unattended and never marks the digest read; it fetches only sources named explicitly. Both take `--json`. `make schedule` (#112) copies the venv and `src/` to `~/.local/share/jobagent-runtime/`, because macOS blocks launchd from reading `~/Documents`, and installs the plist there, keeping its sources and time; re-run it after every pull. Counts-only Mac notification; `docs/scheduling.md`, including a `pmset` wake. **The job is not loaded**: it failed with "Operation not permitted" from `~/Documents` and was unloaded on purpose. `make schedule` then `launchctl load` on the laptop is mine.
- `jobagent skip <id> -r "..."` / `snooze <id> --days N` — a skip records why, and `report` aggregates the reasons. A snooze hides a row until a date and it returns on its own; it is not a state, so nothing has to be undone.
- Pre-commit hook blocks databases, rendered documents, snapshots and credential shapes. Verified firing on a fake key and on a real `snapshot.json`.

## In progress

- **ADRs 0008 and 0011 are `Proposed` and waiting on me.** 0008 supersedes 0005's claim that Workday's API is in maintenance — it is not, and the 403 that corroborated it was our own proxy; the decision stands, only its reasoning changes. 0011 (#114) is a daily fetch that runs without the laptop; nothing is built for it. ADR 0009 is accepted: the phone snapshot (`jobagent snapshot`, `cloudflare/public/`) downgrades `jobs.state` from critical to let a read-only board view sit behind a Cloudflare Access login. ADR 0010 is accepted: a hosted companion under `cloudflare/` with owner-only writes (Pages Functions, D1, GitHub OAuth), built and tested on synthetic data only. `jobagent sync` reconciles the board with it by hand only (a dry run unless `--yes`; refuses if the Access gate answers anonymously), and the registry now grants each hosted field. `jobagent purge` empties the hosted copy first and names what it cannot reach (D1 Time Travel, old Pages deployments). The Pages project is deployed behind Access, and its D1 database is created, bound and migrated. The phone page now has a sign-in button and a 30-day session (#113), merged but not yet redeployed. Still mine: the Access service token, `SYNC_TOKEN`, the laptop's `JOBAGENT_*` variables, the redeploy, and the first `jobagent sync`.

## Next

1. Send the two nearest-deadline applications. Packages are built; the company paragraph and the "why this company" answer still need me.
2. Rephrasing toward a posting's vocabulary, through the same truthfulness gate.
3. Extend the extraction eval corpus toward the 50 postings #30 asks for (#65). Twelve is enough to catch a gross regression and not enough to trust a precision number.

## Known limitations

- **Workday fetch is verified against live RBC, BMO and TD tenants** (2026-09-15, #57) — real rows, correct ids, resolving URLs. The 403 previously recorded here was the build container's proxy, not a tenant. A 200 is reachability, not permission: `terms.allows_automated_access` stays `unverified` until someone reads them.
- **Scotiabank has no Workday adapter and cannot have one.** `jobs.scotiabank.com` runs SAP SuccessFactors; the `scotiabank.wd3` tenant does not exist. Scotiabank closes 2026-10-02 — use the Claude in Chrome handoff.
- A 401/403 from a tenant is treated as a refusal and stops that adapter, with the Claude in Chrome handoff as the fallback. No circumvention.
- **Semantic fit does not ship and the profile refuses a non-zero weight for it.** It needs an embedding model; a metered embeddings API is out of scope and no local backend has been chosen. It is recorded in every decomposition as explicitly unavailable rather than silently ignored.
- Scoring totals are strictly comparable only between postings measured on the same components. Every score records which ones those were, and `jobagent score` prints the count per row — a row scored on 2 of 5 is a thinner judgement than one scored on 4.
- Location filtering resolves missing or placeholder locations from explicit `Work Location: city, region, country` lines in descriptions. Ambiguous formats remain unknown; the Wilmington fixture is now cut for location.
- Domain relevance compares title vocabulary against the profile's target titles, not industry history. There is no industry field on the profile to read.
- Extraction is evaluated on 12 postings, not the 50 #30 asks for, and only on its mechanical fields (date, pay band, years, arrangement). Skill extraction is unscored.
- **Growing either eval corpus needs a machine with network access.** A build container's proxy refuses every job-board host at the CONNECT stage, before a request is made, so it is not a tenant declining and no adapter change helps. `scripts/capture_postings.py` is the path: fetch on a machine that can reach them, then print board rows as fixtures to stdout. It writes nothing and emits only employer-published fields.
- `--json` exists on `shortlist`, `digest` and `list` only; every other command prints a Rich table and composes with nothing. Global flags `--data-dir` and `--version` exist; `--config` and `--verbose` do not yet. Exit codes are documented in the README (#120); `--verbose` is #121.
- Mail ingestion is deferred (#39) — OAuth costs a day and manual status updates take seconds at this volume.
- Commit signing is configured in the build container but its key is empty, so no commit carries a signature and none will show GitHub's Verified badge. Authorship is correct; verification needs a real signing key set up locally.

## Deadlines that drive this

Winter 2027 co-op applications, tracked on the board. Two close 2026-09-20; Scotiabank 2026-10-02. The tool exists to serve these — a feature that does not help before those dates is not urgent.
