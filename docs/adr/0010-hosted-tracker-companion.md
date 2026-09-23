# 0010 — A hosted tracker companion with owner-only writes

**Status:** Accepted
**Date:** 2026-09-22
**Supersedes:** the "Why not the alternatives" paragraph of [0009](0009-phone-snapshot.md) that rejected a D1 database, a sync endpoint and OAuth sessions. The rest of 0009 stands.

## Context

0009 put a read-only board snapshot behind Cloudflare Access and rejected a live
database with a sync endpoint: "it keeps a writable copy of the board
off-machine permanently and adds an authenticated write path that has to be
secured before real data goes near it." Both halves of that are still true.

The need 0009 did not meet is updating a row from the phone — marking something
applied, moving a next action — without waiting to get back to the laptop. A
static file cannot take a write.

## Decision

Build a Cloudflare Pages companion under `cloudflare/`, on the free plan only:

- **Toolchain.** Node, TypeScript, `wrangler` and `vitest`, pinned by
  `cloudflare/package-lock.json` and tested in CI. It is a second toolchain in a
  Python repository; it stays inside `cloudflare/` and nothing in `src/` imports it.
- **Storage.** One D1 database holding tracker rows only. Forward-only migrations
  in `cloudflare/migrations/`, as for the local database.
- **Fields.** The 0009 allowlist plus what a phone edit needs: `id`, `company`,
  `title`, `location`, `url`, `deadline`, `status`, `next_action`,
  `next_action_date`, `updated_at`, `version`. `status` uses the local board's
  state names so a row round-trips. **`notes` and `state_reason` are refused**,
  for the same reason 0009 refused them: they are free text that names people.
- **Access.** Cloudflare Access stays in front of the whole project. Behind it,
  API routes additionally require a GitHub OAuth session for one numeric owner ID,
  and state-changing requests require a same-origin CSRF token.
- **Writes.** Optimistic concurrency: every write names the version it read, and a
  stale write is a `409`, never last-writer-wins.
- **Cost.** The API refuses to serve unless the deployment declares itself
  free-tier, and deploy scripts refuse a config that names a paid binding.

Nothing here submits an application or contacts an employer. Rule 1 is untouched.

## What must be true before real data goes up

This ADR does not by itself permit uploading real rows. That needs, in order:

1. The PII registry gains a destination for the hosted tracker, and each field
   above is registered against it, so `test_nothing_critical_is_sent_to_a_third_party`
   covers the new path rather than being stepped around as 0009 describes.
2. A local sync client that sends only those fields and pulls phone edits back
   through the same version check.
3. `jobagent purge` reaches the D1 copy, or states plainly that it cannot.
4. The Access gate is verified from a private window, as `cloudflare/README.md` orders.

## Consequences

The off-machine copy becomes writable and permanent until purged, which is what
0009 declined. The mitigation is layered — Access, then an owner-only session,
then a field allowlist enforced on write — and each layer is tested on its own.

Rate limiting is per-isolate and in memory, so it brakes a runaway client but is
not a quota. The free plan's own limits are the real ceiling.

If this is rejected, the snapshot from 0009 keeps working unchanged: the phone
page falls back to `snapshot.json` when the API is absent.
