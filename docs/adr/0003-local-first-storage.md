# 0003 — Local-first storage

**Status:** Proposed
**Date:** TBD

## Context

The system holds a complete employment dossier, including a record of which
companies the user approached while employed elsewhere. Disclosure of that
record is a career event.

## Decision

All state lives in a single embedded relational database file on the user's
machine, with generated documents on disk beside it. No hosted database, no sync
service, no telemetry.

The data directory sits outside the working tree by default so that a stray
`git add -A` cannot publish it.

## Consequences

Backup and deletion become trivial and verifiable — one directory to archive,
one directory to remove, which is what the retention and purge commitments in
`docs/security-privacy.md` rest on.

The cost is no cross-device access and no sharing. For a four-month single-user
job search, that is not a real loss. If it ever becomes one, that is a new threat
model and a superseding ADR, not a config flag.
