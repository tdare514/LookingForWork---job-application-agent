# 0009 — A read-only phone snapshot, behind Cloudflare Access

**Status:** Proposed
**Date:** 2026-09-22

Extends 0003. The local-first decision stands; this carves one narrow, named
exception out of it.

## Context

0003 chose local-first storage and accepted the cost in its own words: "no
cross-device access and no sharing... If it becomes one, that is a new threat
model and a superseding ADR, not a config flag." This is that ADR.

The need is small and real: knowing which applications are outstanding, and
where each one stands, while away from the machine. The board is a Textual TUI
on one laptop; a phone cannot reach it.

## Decision

`jobagent snapshot <path>` writes a JSON file holding one row per live board
entry, carrying **only** `id`, `company`, `title`, `location`, `deadline`,
`state` and `url`. A human uploads that file to a Cloudflare Pages project
served behind a Cloudflare Access login. The page is read-only: no write route,
no sync endpoint, no application-submission path.

`jobs.state` is reclassified in `jobagent.core.pii` from
`CRITICAL`/`NOWHERE` to `HIGH`/`PUBLIC_SNAPSHOT` to permit this.

**The risk was not reassessed. It was accepted.** Paired with a company name,
`state` is still the record of approaching employers while employed elsewhere,
and disclosure is still a career event — 0003's framing is unchanged and still
correct. The owner traded that risk for phone access, with the Access login as
the mitigation.

One consequence deserves to be stated rather than discovered later:
`test_nothing_critical_is_sent_to_a_third_party` still passes, untouched. It did
not approve this change — it constrains fields marked `CRITICAL`, and the
reclassification moved `state` out of its reach. The guard is intact for
everything else and silent about this one field by construction.

Refused, and named in `NEVER_SNAPSHOT` so the refusal is on record: `notes` and
`state_reason` (free text that routinely names recruiters and carries judgements
about employers), `state_changed_at` and `first_seen_at` (timestamped
application history), `description`, and everything in `applications`,
`application_transitions`, `scores` and `audit_log`.

Nothing in this tool uploads anything. The push is a separate, deliberate human
act, consistent with rule 1: no code path ends in an outbound transmission.

## Why not the alternatives

A live Cloudflare D1 database with a sync endpoint and OAuth sessions was
scaffolded and rejected: it keeps a writable copy of the board off-machine
permanently and adds an authenticated write path that has to be secured before
real data goes near it. A static file has no write path to get wrong.

Client-side encryption — pushing ciphertext only Cloudflare cannot read — was
considered and declined as more machinery than this warrants for a file behind a
login gate.

## Consequences

The snapshot is as current as the last upload. It carries `generated_at` and the
page shows it, because a static file that looks live is worse than one that
admits its age.

**The Access gate is the whole mitigation.** A Pages project served without it
is world-readable by URL to anyone who finds it, which is a larger disclosure
than anything else this repository does. If the gate is removed or misconfigured,
this decision no longer holds and the snapshot should stop being published.

Removing the exception is cheap: restore the registry entry, delete the command.
Nothing depends on it. What cannot be undone is any snapshot already uploaded.
