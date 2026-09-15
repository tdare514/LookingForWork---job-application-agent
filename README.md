# LookingForWork — Job Application Agent

A personal, human-in-the-loop agent for a focused job search, built in
**a two-week sprint (Sept 15–28, 2026)**: it finds relevant roles, scores them against a
declared profile, drafts tailored resumes and cover letters, and tracks every
application through to an outcome.

The agent **never submits anything on its own.** Every outbound artifact passes
through an explicit human approval step. See
[`docs/security-privacy.md`](docs/security-privacy.md) for why that is a hard
constraint rather than a default setting.

## Status

In build. Two-week sprint running **Sept 15–28, 2026**, tracked as four block
epics (#1–#4) over 29 task issues. See [`ROADMAP.md`](ROADMAP.md) for the
day-by-day schedule and what was cut to fit the window.

## What it does

| Capability | Description |
| --- | --- |
| Discover | Pulls postings from a configured set of sources through pluggable adapters |
| Normalize | Collapses source-specific payloads into one job schema and de-duplicates reposts |
| Match | Scores each posting against the profile: skills, seniority, compensation, location, culture signals |
| Tailor | Drafts a resume variant and cover letter per shortlisted role, constrained to verifiable facts |
| Approve | Presents a review queue; nothing leaves the machine without a human "yes" |
| Track | Records every application, its state, follow-up dates, and outcome |
| Report | Surfaces funnel metrics — what is converting, what is not, where time is going |

## Documentation

- [`AGENTS.md`](AGENTS.md) — working rules, commands, definition of done (start here)
- [`STATUS.md`](STATUS.md) — what works right now
- [`CONTRIBUTING.md`](CONTRIBUTING.md) — setup and the git workflow
- [`ROADMAP.md`](ROADMAP.md) — phased plan, dates, exit criteria
- [`docs/architecture.md`](docs/architecture.md) — components, data flow, storage
- [`docs/security-privacy.md`](docs/security-privacy.md) — threat model, PII handling, guardrails
- [`docs/job-matching.md`](docs/job-matching.md) — discovery and scoring workflow
- [`docs/application-tracking.md`](docs/application-tracking.md) — resume management and pipeline tracking
- [`docs/adr/`](docs/adr/) — architecture decision records

## Design principles

1. **Local first.** Profile, resume, and application history live on the user's
   machine. Nothing is uploaded to a service the user did not choose.
2. **Truthful output.** The tailoring engine may reorder, select, and rephrase
   facts from the resume source of truth. It may not invent them.
3. **Respectful automation.** Rate-limited, adapter-per-source, and bound by each
   source's terms. No credential stuffing, no scraping behind a login the user
   has not authorized, no evasion of bot protection.
4. **Reversible.** Every stored byte can be exported or deleted with one command.
5. **Small surface.** Four months is the budget. Features that do not move an
   application closer to a human recruiter do not ship.
