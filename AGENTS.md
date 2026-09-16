# AGENTS.md

Canonical briefing for AI coding agents (Claude Code, Codex, Cursor, Copilot, Gemini CLI) and for me reading this repo in three months. Claude Code loads it through `CLAUDE.md`. An explicit instruction from me overrides this file.

## Project

**jobagent** — a personal, human-in-the-loop job application agent. It tracks opportunities on a keyboard-driven board, drafts tailored resumes and cover letters from a single source of truth, and hands the actual applying to Claude in Chrome. One user: me. Not a product, not a team project, not a demo.

Python 3.11, SQLite, Typer, Textual. Decided in `docs/adr/0002` and `0003`. Architecture: `docs/architecture.md`. The board-first shape and why the crawler was dropped: `docs/adr/0005`.

## The three rules that are not negotiable

Everything else here is a convention. These three are why the project is safe to run:

1. **Nothing is sent without me.** The agent never submits an application. Applying is a handoff — it opens the posting and stages a prompt; I am at the browser. No code path may end in an outbound submission.
2. **Never invent a claim.** Tailoring may select, reorder and rephrase facts from the resume source of truth. It may not add one. "Reduced p99 latency 40%" becoming "led latency reduction across the platform" is a fabrication, and it is the kind that survives a skim and dies in an interview.
3. **The dossier stays on this machine.** Employment history, work authorization, and a record of which companies I approached while employed elsewhere. The data directory lives outside the working tree at `0o700`. Nothing marked critical in the PII registry may leave.

## Budget constraint

**No paid API in the core loop.** A Claude subscription carries no API credit — API usage bills separately. Anything requiring an `ANTHROPIC_API_KEY` is out of scope unless I say otherwise.

Where judgement is needed: rule-based first, then Claude Code (already paid for), then Claude in Chrome for form filling. If a feature only works with metered API calls, it does not ship — say so rather than building it.

## Repository layout

| Path | Purpose |
|---|---|
| `src/jobagent/core/` | `paths` (data dir resolution), `storage` (SQLite + repository layer), `migrations` (forward-only), `pii` (the PII registry), `profile` (declared intent, validated on load), `vocabulary` (terms more than one package shares). Depends on nothing above it. |
| `src/jobagent/tracking/` | `board` (states and traffic lights), `repo` (board repository), `app` (the Textual TUI), `shortlist` + `digest` (the ranked list and the reading queue this tool builds), `leads` (importing an outside search's triage), `funnel`, `followups` |
| `src/jobagent/application/` | `handoff` (Claude in Chrome prompt, clipboard, browser) |
| `src/jobagent/discovery/` | `adapter` (the source contract and registry), `http` (rate-limited client, host allowlist), `workday`, `greenhouse` |
| `src/jobagent/matching/` | `normalize` (company, title, location and seniority canonicalization, and the de-duplication key), `extract` (rule-based requirements from posting text). Pure functions, no I/O. |
| `src/jobagent/cli/` | Typer entry point. Every command lives here. |
| `tests/` | Mirrors `src/`. `conftest.py` isolates the data directory per test. |
| `docs/adr/` | Decision records. Numbered, immutable once accepted, superseded rather than edited. |
| `scripts/` | `pre-commit` hook, `check_context.py`, `capture_postings.py` (board rows as eval fixtures, stdout only). |

## One owner per fact

A fact lives in exactly one place; everything else links to it. Fix duplication when you see it. Delete stale text rather than annotating it.

| Information | Lives in |
|---|---|
| What this is, how to run it | `README.md` |
| What works now, what is in flight, what is broken | `STATUS.md` |
| System structure, data flow, boundaries | `docs/architecture.md` |
| Why a decision was made, what was rejected | `docs/adr/` |
| Threat model, PII handling, retention | `docs/security-privacy.md` |
| What is stored and for how long | `jobagent.core.pii` (code, not prose) |
| Matching and scoring design | `docs/job-matching.md` |
| Resume and tracking design | `docs/application-tracking.md` |
| Commands, working rules, definition of done | this file |
| Claude Code specifics | `CLAUDE.md`, `.claude/` |
| Branch, commit, PR workflow | `CONTRIBUTING.md` |
| Schedule and scope cuts | `ROADMAP.md` |

There is no changelog. Git history and merged PRs are the record.

## Commands

```
make install     # pip install -e ".[dev]"
make hooks       # install the pre-commit hook
make check       # ruff + strict mypy + pytest -- run before every push
make format      # apply ruff formatting and safe fixes

jobagent init                       # create the data directory, apply migrations
jobagent add -c BMO -t "Analyst" -d 2026-09-20 --ready
jobagent board                      # the command board
jobagent list                       # same, non-interactive
jobagent pii                        # what is stored, why, how long
jobagent audit                      # append-only trail

python3 scripts/check_context.py    # deterministic doc/context check (also in CI)
```

Always go through `make` or `python3 -m`. A bare `mypy` or `ruff` on `PATH` may belong to a different interpreter and will disagree with CI.

## Session start

Load what the task needs, in this order. Do not read all of `docs/` by default.

1. This file, plus `STATUS.md` for current state.
2. The task. Restate it in one sentence. Ask only if two readings lead to materially different work.
3. `git status -sb` — never work directly on `main`.
4. `docs/architecture.md` if the change crosses a module boundary.
5. ADR titles in `docs/adr/README.md`; open only the ones that apply.
6. The code and its tests.

## Working rules

- **Standing authorization (2026-09-16):** Agents may review and merge routine PRs in this repository on my behalf once the required checks pass and they have reviewed the final diff. Use your judgment on ranking labels, grounded in the posting text and the declared search profile. No additional merge confirmation is needed within this scope. Follow the branch and PR workflow in `CONTRIBUTING.md`; the three non-negotiable rules and hard constraints still apply.
- **One issue, one branch, one PR.** Never batch several issues into one branch, even when they are sequential and the work is going well — a PR covering five issues cannot be reviewed, reverted, or pointed at from an issue. When later work depends on earlier work, stack the PRs (each based on the previous) rather than merging them into one.
- One concern per branch. Small diffs.
- Ruff and mypy are the authority on style. Do not argue formatting.
- Strict typing everywhere, no per-file opt-outs, no `# type: ignore` without a reason on the same line.
- New dependency of consequence → an ADR. Propose it, do not slip it in.
- Stay in scope. Do not refactor or reformat files the task does not touch.
- Write tests where breakage would be silent — the privacy controls, the board state, the handoff prompt. Do not pad coverage.
- No feature code writes SQL directly; it goes through the repository layer.
- Every PII-bearing column is registered in `jobagent.core.pii`, or the test suite fails. This is what makes `purge` verifiable.
- Secrets come from the keychain or the environment. Never a file, never the database, never a log line.
- The audit log is append-only. Do not add a delete path.
- Simplest thing that works for one real job search. A working vertical slice beats a platform.

## Hard constraints

- Never commit secrets, real `.env` files, a database, or a rendered resume. The repository is public.
- Never commit anything from the data directory.
- Never weaken or delete a test that guards the three rules above. If one is wrong, change it deliberately and say so in the PR.
- Never claim a check passed when it did not. Paste the failure.
- Never rewrite `main` history.
- Never set an ADR to `accepted` on my behalf — propose it and let me decide.

## Definition of done

1. The requested behaviour exists and nothing else changed.
2. `make check` passes. Paste failures rather than describing them.
3. The final diff has been read for scope, secrets and leftovers.
4. No module boundary crossed without an ADR.
5. `STATUS.md` matches reality; docs the change affected are updated and no others.
6. What was skipped, assumed or left broken is stated in the PR description.
7. A future session can continue from the repo alone, with no access to this chat.
