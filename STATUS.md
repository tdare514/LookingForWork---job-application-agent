# Status

Snapshot of **now**, not a changelog. Update it in the same commit as the change that made it stale. Keep it under ~60 lines; git history holds the rest.

Last updated: 2026-09-15

Current focus: the board is usable. Next is resume tailoring from a structured source of truth (#33, #34).

## What works

- `jobagent init` / `status` / `pii` / `audit` — data directory outside the working tree at `0o700`, SQLite with forward-only migrations, append-only audit trail.
- `jobagent add` / `list` / `board` — opportunities tracked one row each, with traffic lights: green sent, yellow wants attention today, red dead. Needs-action sorts first, then by deadline. De-duplicates across company-name variants.
- Claude in Chrome handoff (`c` on the board): opens the posting and copies a prompt that carries my standing answers and forbids both submitting and inventing.
- 28 tests. `make check` runs ruff, strict mypy and pytest clean. CI runs the same on push.
- Pre-commit hook blocks databases, rendered documents and credential shapes. Verified firing on a fake key.

## In progress

Nothing in flight.

## Next

1. Resume source of truth seeded from my real resume and cover letter (#33).
2. Tailoring with the truthfulness check, and the test that proves a fabricated claim is caught (#34).
3. PDF/DOCX rendering that survives an ATS parser (#36).

## Known limitations

- Opportunities are entered by hand. Workday's public job API is in maintenance as of September 2026, and RBC, BMO, Scotiabank and TD all run Workday — so auto-fetch would miss exactly the employers that matter. Greenhouse and Lever remain free and open if a target uses them (#27, #29).
- Scoring is not built. When it is, it is rule-based: no metered API calls in the core loop.
- Mail ingestion is deferred (#39) — OAuth costs a day and manual status updates take seconds at this volume.
- The four commits before PR #44 are authored by `Claude <noreply@anthropic.com>` and do not count as contributions. Fixing that needs a history rewrite.

## Deadlines that drive this

Winter 2027 co-op applications, tracked on the board. RBC and BMO close 2026-09-20; Scotiabank 2026-10-02. The tool exists to serve these — a feature that does not help before those dates is not urgent.
