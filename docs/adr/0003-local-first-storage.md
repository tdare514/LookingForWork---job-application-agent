# 0003 — Local-first storage

**Status:** Accepted
**Date:** 2026-09-15

## Context

The system holds a complete employment dossier: history, GPA, work
authorization, and a record of which companies were approached while employed
elsewhere. Disclosure of that last item is a career event.

## Decision

All state lives in a single SQLite file in a data directory on the user's
machine, with generated documents on disk beside it. No hosted database, no sync
service, no telemetry.

The data directory resolves outside the working tree by default
(`~/.local/share/jobagent`, overridable via `JOBAGENT_DATA_DIR`) and is created
`0o700`, so a stray `git add -A` cannot publish an application history. Tests
assert both properties.

## Consequences

Backup and deletion are trivial and verifiable — one directory to archive, one
to remove. That is what the retention and purge commitments in
`docs/security-privacy.md` rest on, and what makes the Block 4 `purge` test
possible at all.

The cost is no cross-device access and no sharing. For a two-week single-user
build that is not a real loss. If it becomes one, that is a new threat model and
a superseding ADR, not a config flag.
