# 0006 — The repository is the project memory

**Status:** Accepted
**Date:** 2026-09-15

## Context

This project is built across chat sessions that end. Everything decided in one and not written down is gone by the next — which is how a personal project reaches week six with three half-remembered conventions and no way to tell which one is current.

The problem is not coordination. There is one contributor. The problem is **continuity**: a future session, possibly driven by a different tool, must be able to pick the work up from the repository alone.

Structure borrowed from a larger multi-contributor repo, with the team machinery removed.

## Decision

`AGENTS.md` is the canonical, tool-agnostic briefing. `CLAUDE.md` imports it with `@AGENTS.md` and holds only Claude Code specifics. `AGENTS.md` is the convention Codex, Cursor and Copilot read natively, so the rules survive a change of tool.

Alongside it:

| File | Holds |
| --- | --- |
| `STATUS.md` | Snapshot of now — what works, what is next, what is broken |
| `docs/architecture.md` | System structure |
| `docs/adr/` | Why, and what was rejected |
| `CONTRIBUTING.md` | Branch, commit, PR workflow |
| `scripts/check_context.py` | The deterministic half of keeping the above true |

**One owner per fact.** Each fact lives in exactly one file; others link. The ownership table is in `AGENTS.md`. There is no changelog — git history and merged PRs are the record.

## What was deliberately not borrowed

The source repo is five people racing a submission deadline. Most of its process is a cost with no benefit here:

- **Review gates** ("CI green plus one review") — there is no second person. Self-review of the diff replaces it, and the PR exists for the diff view and CI, not for approval.
- **Phase discipline and work claiming** — an owner table and "never advance the phase yourself" solve contention between people.
- **A Context Sync Protocol document** — the ceremony collapses into a script and a PR checkbox.
- **Hackathon framing** — demo readiness, judging, submission dates. This tool has to work for one real job search, which is a longer and less forgiving standard than a demo.

## Consequences

- A future session gets identical context from a clone, with no access to any chat.
- Three project-specific rules are stated once, in `AGENTS.md`, rather than re-derived: nothing is sent without a human, tailoring may never invent a claim, and the dossier stays local.
- The budget constraint is now written down where an agent will read it before proposing an architecture that needs a metered API key.
- Cost: the docs must be kept current. Mitigated by `scripts/check_context.py`, which catches broken links, unindexed ADRs, oversized instruction files, a stale `STATUS.md`, and tracked secrets or data artefacts. Each of those failure modes was verified to fail the check before this was accepted.
- `AGENTS.md` must stay small — agents read it every session. It is capped at 200 lines by the check; detail goes into linked documents.
