# Roadmap — January to April 2027

Four phases, one per month, each ending in something usable. The ordering is
deliberate: nothing in a later phase can be built safely until the storage and
privacy foundations from Phase 1 exist.

| Phase | Window | Theme | Ships |
| --- | --- | --- | --- |
| 1 | Jan 4 – Jan 31 | Foundation, security, privacy | An agent that can hold your data safely and do nothing else |
| 2 | Feb 1 – Feb 28 | Discovery and matching | A daily ranked shortlist of real postings |
| 3 | Mar 1 – Mar 28 | Resume and application generation | Approved, tailored application packages |
| 4 | Mar 29 – Apr 30 | Tracking, analytics, hardening | A tracked pipeline with funnel metrics and a clean exit path |

Cross-cutting work — security review, docs, CI — is not a phase. It is a
standing cost attached to every issue.

---

## Phase 1 — Foundation (January)

**Goal:** a trustworthy container for personal data, plus the skeleton every
later phase plugs into.

Scope:
- Runtime stack decision, recorded as an ADR before any code lands.
- Package layout, linting, formatting, type checking, test harness, CI.
- Configuration and profile schema — the declared description of what the user
  wants, versioned and validated.
- Local storage (embedded relational DB) with forward-only migrations.
- Secrets handling: credentials come from the OS keychain or environment, never
  from a file in the repo and never from the database.
- PII inventory and retention policy, written down before data is collected.
- Outbound request policy: per-source allowlist, rate limits, identifiable user
  agent, respect for `robots.txt` and terms of service.
- Structured logging and an append-only audit trail of agent actions.
- Human-in-the-loop guardrail enforced at the architecture level: no code path
  that transmits an application without a recorded approval.

**Exit criteria**
- `make check` runs lint, types, and tests green in CI on every push.
- A profile can be loaded, validated, and stored; a bad profile fails loudly.
- Secret scanning and dependency audit run in CI and block on findings.
- The PII inventory lists every field the system will store, its purpose, and
  its retention window.
- A threat model document exists and names the accepted risks.

---

## Phase 2 — Discovery and matching (February)

**Goal:** every morning, a ranked shortlist worth reading.

Scope:
- Source adapter interface: fetch, paginate, map to the canonical job schema,
  declare its own rate limit and terms constraints.
- Two adapters implemented end to end, chosen for coverage of the target market.
- Canonical job schema plus de-duplication — the same role reposted across
  sources and weeks collapses to one record with a history.
- Requirement extraction: pull skills, seniority, compensation band, and work
  arrangement out of free-text descriptions.
- Match scoring: a hybrid of explicit rules (hard filters — location, visa,
  compensation floor) and semantic similarity against the profile, with the
  score decomposed so a low score is explainable.
- Shortlist generation, filters, and a daily digest.

**Exit criteria**
- A scheduled run ingests from both adapters, de-duplicates, scores, and writes
  a shortlist without manual intervention.
- Every score is explainable: the digest shows which components drove it.
- Scoring is regression-tested against a fixture set of labeled postings.
- Rate limits are enforced by the framework, not by adapter discipline.

---

## Phase 3 — Resume and application generation (March)

**Goal:** turn a shortlisted role into an application package a human is willing
to send.

Scope:
- Structured resume as the single source of truth — every claim the agent can
  make lives here, with dates and evidence.
- Tailoring engine: selects and reorders existing facts for a target posting.
  Constrained so generated text cannot introduce a claim absent from the source
  of truth; violations fail the build of that package.
- Cover letter generation with tone and length controls.
- Answer library for recurring application questions, reused rather than
  regenerated.
- Rendering and export to PDF and DOCX with a stable, ATS-readable layout.
- Approval workflow: package assembled, diffed against the source of truth,
  presented for review, approved or rejected with a reason.

**Exit criteria**
- A shortlisted job yields a complete package: tailored resume, cover letter,
  and prefilled question answers.
- The truthfulness check has test coverage proving a fabricated claim is caught.
- Rejected packages record why, and the reason feeds back into tailoring.
- Exported documents survive a round trip through a common ATS parser.

---

## Phase 4 — Tracking, analytics, and hardening (late March to April)

**Goal:** know the state of every application, and leave the system in a state
that can be handed over or deleted.

Scope:
- Application tracker: one record per application, with an explicit state
  machine (drafted, approved, submitted, acknowledged, screening, interviewing,
  offer, rejected, withdrawn, stale).
- Read-only status ingestion from a mail account to suggest state transitions,
  never to apply them silently.
- Follow-up scheduling and reminders driven by time in state.
- Funnel analytics: conversion at each stage, cut by source, role type, and
  match score, so the next month's effort goes where it converts.
- Backup, full export, and a verified delete path.
- Release hardening: dependency pinning, a security review of the whole surface,
  and an operational runbook.

**Exit criteria**
- No application can be in an unknown state; staleness is detected, not guessed.
- The funnel report answers "which sources are worth my February" with data.
- `export` produces a portable archive; `purge` provably removes stored PII.
- A final security review is complete with findings resolved or accepted in
  writing.

---

## How the issues are organized

Each phase has a tracking epic. Task issues hang off their epic as sub-issues
and carry the phase label plus an area label (`architecture`, `security`,
`privacy`, `matching`, `resume`, `tracking`, `infra`, `docs`).

An issue is done when its acceptance criteria are checked, tests cover the
behavior, and any user-visible change is documented.

## Open decisions

Tracked as ADRs in [`docs/adr/`](docs/adr/). The first one to settle is the
runtime stack — it blocks everything in Phase 1.
