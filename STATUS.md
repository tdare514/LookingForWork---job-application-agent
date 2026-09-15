# Status

Snapshot of **now**, not a changelog. Update it in the same commit as the change that made it stale. Keep it under ~60 lines; git history holds the rest.

Last updated: 2026-09-15

Current focus: the resume source of truth and its truthfulness check are in. Next is rendering a tailored variant to PDF/DOCX (#36).

## What works

- `jobagent init` / `status` / `pii` / `audit` — data directory outside the working tree at `0o700`, SQLite with forward-only migrations, append-only audit trail.
- `jobagent add` / `list` / `board` — opportunities tracked one row each, with traffic lights: green sent, yellow wants attention today, red dead. Needs-action sorts first, then by deadline. De-duplicates across company-name variants.
- Claude in Chrome handoff (`c` on the board): opens the posting and copies a prompt that carries my standing answers and forbids both submitting and inventing.
- Resume source of truth (`resume.example.yaml`, `jobagent resume validate`): every claim the agent may make, each accomplishment carrying its metric and the scope actually held.
- Truthfulness check: a tailored bullet must cite a source accomplishment and may not invent a number, claim more scope than was held, or add breadth. Refuses rather than warns.
- The board closes the loop: `d` drafts the package for a row, `c` stages the Claude in Chrome prompt pointing at the drafted resume, `a` marks it applied. A `Pkg` column shows which rows have one.
- Tailoring (`jobagent draft <job-id>`): selects and orders bullets for one posting, renders a one-page resume to PDF and DOCX, drafts a cover letter, and writes the recurring answers. Bullets are selected verbatim, so selection cannot fabricate.
- 100 tests. `make check` runs ruff, strict mypy, pytest and the context check. CI runs the same on push.
- `jobagent followups` — fires at 10 days submitted with no reply, 5 days post-interview, stale at 30. The board shows the count.
- `jobagent report` — funnel with denominators stated, small samples flagged, and a plain "nothing submitted yet" when that is the truth.
- `jobagent export` / `purge` — one archive out, and a delete that verifies nothing recoverable remains.
- Pre-commit hook blocks databases, rendered documents and credential shapes. Verified firing on a fake key.

## In progress

Nothing in flight.

## Next

1. Send the RBC and BMO applications. Packages are built; the company paragraph and the "why this company" answer still need me.
2. Rephrasing toward a posting's vocabulary, through the same truthfulness gate.
3. Greenhouse/Lever adapters if a target uses them (#27, #29).

## Known limitations

- Opportunities are entered by hand. Workday's public job API is in maintenance as of September 2026, and RBC, BMO, Scotiabank and TD all run Workday — so auto-fetch would miss exactly the employers that matter. Greenhouse and Lever remain free and open if a target uses them (#27, #29).
- Scoring is not built. When it is, it is rule-based: no metered API calls in the core loop.
- Mail ingestion is deferred (#39) — OAuth costs a day and manual status updates take seconds at this volume.
- Commit signing is configured in the build container but its key is empty, so no commit carries a signature and none will show GitHub's Verified badge. Authorship is correct; verification needs a real signing key set up locally.

## Deadlines that drive this

Winter 2027 co-op applications, tracked on the board. RBC and BMO close 2026-09-20; Scotiabank 2026-10-02. The tool exists to serve these — a feature that does not help before those dates is not urgent.
