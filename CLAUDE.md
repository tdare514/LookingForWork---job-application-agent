@AGENTS.md
@STATUS.md

# Claude Code notes

Everything imported above is the shared, tool-agnostic briefing. This file holds only what is specific to Claude Code. Keep it under 30 lines; shared instructions belong in `AGENTS.md`.

- Solo repo. There is no reviewer, so self-review is the only review: read the final diff before every push and say what you would have flagged.
- Commits must be authored as `tdare514 <143902012+tdare514@users.noreply.github.com>`, otherwise they do not count as contributions. Keep `Co-Authored-By: Claude` on the trailer.
- `.claude/settings.json` denies reading `.env` files and private keys. Use `.env.example`.
- Never read or write outside the repo into the real data directory (`~/.local/share/jobagent`) — it holds live personal data. Tests set `JOBAGENT_DATA_DIR` to a temp path; do the same for any manual run.
- Run `python3 scripts/check_context.py` before marking a PR ready. It is deterministic and also runs in CI.
- Use plan mode for anything touching storage, the PII registry, or the three non-negotiable rules in `AGENTS.md`.
- Don't update `STATUS.md` *Current focus* unless I ask.
- Prefer `make check` over invoking `ruff`/`mypy`/`pytest` directly — a bare binary on `PATH` may be a different interpreter and will disagree with CI.
