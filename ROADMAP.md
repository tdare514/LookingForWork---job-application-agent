# Roadmap — a two-week build

**Window: September 15 – September 28, 2026.** Personal tool, single user, built
fast and used immediately.

The original plan spread this over four months. That was wrong for the actual
need: Winter 2027 co-op deadlines are live *now* (RBC and BMO close Sept 20,
Scotiabank Oct 2), so a tool that ships in April is a tool that missed the
season. Two weeks, four blocks, aggressively scoped.

| Block | Days | Dates | Ships |
| --- | --- | --- | --- |
| 1 | 1–3 | Sep 15–17 | Foundation: storage, profile, secrets, CLI, guardrails |
| 2 | 4–7 | Sep 18–21 | Discovery and matching: a ranked shortlist |
| 3 | 8–12 | Sep 22–26 | Resume tailoring and application packages |
| 4 | 13–14 | Sep 27–28 | Tracking, funnel report, export/purge |

## What "personal scale" changes

The security and privacy model stays. It is not enterprise ceremony — this repo
holds a real dossier: employment history, GPA, immigration status, and a record
of which companies were approached while employed. That risk is the same at any
team size.

What gets cut is process weight, not controls:

| Cut | Why |
| --- | --- |
| Blocking CI with dependency audit and secret scanning (#7) | Reduced to one workflow running tests. A solo build gets its safety from the pre-commit hook and `.gitignore`, not from branch protection. |
| Standalone PII inventory document (#21) | Folded into the storage schema (#9) as annotations. Same information, one artifact instead of two. |
| Read-only mail ingestion (#39) | Deferred. OAuth setup alone costs a day, and manual status updates are fine at this volume. |

Everything else ships.

---

## Block 1 — Foundation (Days 1–3, Sep 15–17)

Python, SQLite, Typer CLI. The container for the data and the guardrails that
keep it from leaking.

- **Day 1** — #5 stack ADR · #6 scaffold · #9 storage and migrations
- **Day 2** — #8 profile schema · #15 secrets · #26 CLI surface
- **Day 3** — #23 logging and audit trail · #25 LLM boundary · #22 rate limiter · #24 approval gate

**Done when:** a profile loads and validates, the database is created outside the
working tree, secrets resolve from the environment, and no submission path exists
without a recorded approval.

## Block 2 — Discovery and matching (Days 4–7, Sep 18–21)

- **Day 4** — #27 adapter interface · #28 canonical schema and de-duplication
- **Day 5** — #29 first two source adapters
- **Day 6** — #30 requirement extraction
- **Day 7** — #31 hard filters and scoring · #32 shortlist and digest

**Done when:** one command ingests, de-duplicates, scores, and prints a ranked
shortlist with an explainable score breakdown.

## Block 3 — Resume and applications (Days 8–12, Sep 22–26)

Seeded from real material: the existing resume, cover letter, and SOI drafts.

- **Day 8** — #33 resume source of truth
- **Day 9** — #34 tailoring with the truthfulness constraint
- **Day 10** — #35 cover letters and answer library
- **Day 11** — #36 PDF and DOCX rendering
- **Day 12** — #37 package assembly and review

**Done when:** a shortlisted role produces a tailored resume and cover letter
that pass the truthfulness check, render to ATS-readable PDF and DOCX, and wait
at the approval gate.

## Block 4 — Tracking and wrap-up (Days 13–14, Sep 27–28)

- **Day 13** — #38 tracker and state machine · #40 follow-up scheduling
- **Day 14** — #41 funnel report · #42 export and purge · #43 runbook

**Done when:** every application has a known state, the funnel report runs on
partial data, and `purge` provably removes the dossier.

---

## Deferred

Tracked, labeled `deferred`, not in the two weeks:

- #39 — read-only mail ingestion for status transitions
- Additional source adapters beyond the first two
- Embedding-based semantic scoring, if rule-based scoring proves good enough

## Reference

- [`docs/architecture.md`](docs/architecture.md)
- [`docs/security-privacy.md`](docs/security-privacy.md)
- [`docs/job-matching.md`](docs/job-matching.md)
- [`docs/application-tracking.md`](docs/application-tracking.md)
- [`docs/adr/`](docs/adr/)
