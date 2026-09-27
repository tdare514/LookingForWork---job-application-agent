# 0011 — A daily fetch that runs without the laptop

**Status:** Proposed
**Date:** 2026-09-25
**Amends:** [0010](0010-hosted-tracker-companion.md), which keeps every fetch on the laptop

## Context

The daily fetch runs on the laptop (`scripts/launchd/`, `docs/scheduling.md`). It
only runs when the Mac is awake at the scheduled time, and a new posting reaches
the phone only after a hand-run `jobagent sync --yes`. The owner asked for new
postings to turn up every day without the computer, and to be able to trigger a
run from the phone.

Three things the rest of the design holds fixed shape any answer:

- **Scoring needs the profile, and the profile stays local.** Filters and scores
  read titles, seniority, locations, skills, deal-breakers, work authorization
  and the pay floor. `profile.payload` is HIGH in `jobagent.core.pii`, and its only
  permitted destination is a model provider. A cloud copy of it is a new third
  party holding the most complete statement of what the owner is looking for.
- **The laptop decides which rows exist.** `jobagent sync` removes hosted rows
  that are not on the board. Anything found in the cloud has to come *to* the
  board, not appear beside it.
- **Workday's terms are unread.** STATUS records `allows_automated_access` as
  `unverified` for every Workday tenant, and tenants commonly refuse cloud
  datacentre addresses. Greenhouse publishes its board API for programmatic use.

## Decision (proposed)

A second Cloudflare Worker, `jobagent-fetcher`, on the free plan, with a daily
Cron Trigger. It shares the companion's D1 database and nothing else.

- **Greenhouse only.** It fetches a fixed allowlist of board slugs held in the
  Worker's configuration, through the documented public board API. No Workday
  tenant is fetched from the cloud; the laptop's schedule keeps doing that.
- **Leads, not jobs.** Results go to a new D1 table, `hosted_leads`, holding only
  employer-published fields: source, source id, company, title, location, URL,
  first seen. No description (it is large, and the free plan's CPU budget per
  invocation is small), no score, no status.
- **A coarse filter, not the profile.** The Worker keeps a lead only when its
  location matches a short list of places held in its own configuration (for
  example `Toronto, Mississauga, Guelph, Canada, Remote`) and its title matches a
  short list of terms (`intern, co-op, new grad, student`). That list reveals
  little more than the board already does; the profile never leaves.
- **The phone shows leads apart from the board**, labelled as found and not yet
  judged. A "fetch now" control on the page calls a session-protected route that
  runs the same job, rate-limited to a few runs a day.
- **The laptop imports them.** `jobagent sync` pulls `hosted_leads` onto the board
  through `BoardRepo.add` (so de-duplication and sightings behave exactly as a
  local fetch), deletes what it imported, and scores locally as usual. A lead is
  a candidate until the laptop has seen it; nothing about it is ranked in the
  cloud.
- **Registry.** The watched-board list and the coarse filter are configuration,
  not dossier, but together they name the employers being considered — the same
  disclosure 0009 accepted for the snapshot's company list. Each `hosted_leads`
  column is registered in `jobagent.core.pii` against `HOSTED_TRACKER`, and
  `purge` empties the table with the rest.

Nothing here submits anything or contacts an employer beyond reading a public
job board. Rule 1 is untouched. The fetch runs on a schedule the owner set, which
is the same act as the laptop's launchd job, moved.

## Alternatives considered

- **Wake the Mac to fetch.** `pmset repeat wakeorpoweron` can wake a sleeping
  Mac a few minutes before the launchd job. No cloud change at all, full scoring,
  Workday included. It needs the Mac plugged in with the lid open or on a
  display, and a new posting still reaches the phone only after a sync. The
  cheapest option, and the right first step whatever is decided here.
- **Run the whole pipeline in the cloud.** Real scoring on the phone, but only
  by putting the profile off-machine. Refused for the reason above.
- **GitHub Actions on a schedule.** Free, but this repository is public: board
  data would pass through public-repository runners and their logs. Refused.
- **Workday from the cloud too.** Unread terms and likely refusals. Revisit only
  after someone has read a tenant's terms and the laptop's fetch has shown a
  cloud address is accepted.

## Consequences

- A second deployable (`cloudflare/fetcher/` or a second entry point), with its
  own free-plan limits: cron triggers, a daily request budget, and a per-run CPU
  budget that a large board's JSON can exceed. Fetch one board per invocation if
  that bites.
- Leads from the cloud carry no description until the laptop imports them and
  a local fetch fills it; the phone lists them, it does not rank them.
- The laptop is still required for ranking, for Workday, and for anything the
  owner applies to. What changes is that nothing is *missed* while it sleeps.

## To accept

The owner decides. If accepted, the work splits into: the Worker and its table
(with the registry entries and purge), the phone's leads view and fetch-now
route, and the `sync` import. Each lands as its own PR.
