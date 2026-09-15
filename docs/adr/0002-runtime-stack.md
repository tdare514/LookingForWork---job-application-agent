# 0002 — Runtime stack

**Status:** Accepted
**Date:** 2026-09-15

## Context

Every Phase 1 issue was blocked on this. The workload: rate-limited HTTP
fetching, text extraction from messy posting descriptions, embedding and LLM
calls, an embedded relational database, PDF and DOCX rendering, and a CLI.
Single user, local execution, no server.

The two-week window sharpened the decision. There is no time to fight an
ecosystem.

## Decision

**Python 3.11**, with:

| Concern | Choice |
| --- | --- |
| CLI | Typer |
| Validation | Pydantic v2 |
| Storage | SQLite via the standard library |
| HTTP | httpx |
| Lint and format | Ruff |
| Types | mypy, strict |
| Tests | pytest |

## Why not the alternatives

**TypeScript on Node** gives types by default but is weakest exactly where
Block 3 lives — PDF and DOCX generation that survives an ATS parser leans on
thinner libraries.

**Go** has the best distribution story, which does not matter for a single-user
local tool, and the weakest ecosystem for the document and text work, which is
most of the actual difficulty.

Python's real weakness is optional typing. That is fixed by strict mypy in CI,
which Block 1 sets up regardless.

## Consequences

- No packaging or distribution work: `pip install -e .` and a console script.
- Document rendering has real options in Block 3 rather than one risky library.
- Strict mypy is non-negotiable from the first commit; retrofitting it onto two
  weeks of existing code does not happen.
