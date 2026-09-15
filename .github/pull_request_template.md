## What changed

<!-- One or two sentences. The PR title becomes the squash commit: make it a Conventional Commit. -->

## Why

<!-- Link the issue. If there isn't one, say what prompted this. -->

## How I tested

<!-- Commands run and what they returned. What you could not run, and why. -->

## Skipped, assumed, or left broken

<!-- None, or the honest list. This is the part a future session actually needs. -->

## Checklist

- [ ] `make check` green (ruff, strict mypy, pytest)
- [ ] `python3 scripts/check_context.py` green
- [ ] Final diff read for scope, secrets and leftovers
- [ ] `STATUS.md` matches reality
- [ ] ADR added or updated if a decision was made or reversed
- [ ] No test guarding the three rules in `AGENTS.md` was weakened
- [ ] Commits authored as `tdare514`, not as Claude
- [ ] This PR covers **one** issue (or is an explicit link in a stack)
