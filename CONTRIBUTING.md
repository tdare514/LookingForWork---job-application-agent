# Working on this repo

One contributor. These rules exist to protect me from myself six weeks from now, not to coordinate a team.

## Setup

```bash
python3 -m venv .venv && source .venv/bin/activate
make install     # pip install -e ".[dev]"
make hooks       # install the pre-commit hook -- do this once per clone
```

## The loop

```bash
git switch -c feat/short-description    # never work on main
# ... change things ...
make check                              # ruff + strict mypy + pytest
python3 scripts/check_context.py        # docs and code still agree
git push -u origin feat/short-description
```

Then open a PR. Squash merge. Delete the branch.

## Why a PR at all, working alone

Three reasons that survive having no reviewer:

1. **The diff gets read once, deliberately.** Self-review is the only review here. Reading your own diff in the PR view catches scope creep and leftover debug output that `git diff` in a terminal does not.
2. **CI runs before it reaches `main`.** A red `main` on a solo repo is discovered weeks later.
3. **It is the record.** There is no changelog. The PR description is where "what I skipped and why" lives, and it is what a future session reads instead of this chat.

A PR does not need to wait for anyone. Open it, let CI go green, read the diff, merge.

## Branches

`type/short-description` — `feat/`, `fix/`, `docs/`, `chore/`, `refactor/`.

**One issue per branch, one PR per branch.** This is the rule that is easiest to
break when the work is flowing and everything passes: you finish an issue, the
next one is right there, and six issues later the branch holds a diff nobody can
review. It already happened once here — PR #44 reached fifteen issues before it
was split into a stack.

The cost is not theoretical:

- An issue cannot link to the PR that closed it, so the tracker stops meaning
  anything.
- Nothing can be reverted independently. One bad change means reverting five
  good ones.
- The diff view — the only review this repo gets — becomes useless past a few
  hundred lines.

When later work genuinely depends on earlier work, **stack** the PRs: each one's
base is the previous branch, merged in order. That keeps each diff small without
pretending the dependency does not exist.

Never commit to `main`. Never rewrite `main` history.

## Commits

Conventional Commits for the subject line, because the PR title becomes the squash commit:

```
feat(board): sort needs-action above everything else
fix(storage): reject credential-shaped keys before write
docs(adr): accept 0005, board-first with Claude in Chrome
```

Body: why, not what — the diff already says what. Note anything skipped or assumed.

Every commit must be authored as `tdare514 <143902012+tdare514@users.noreply.github.com>`. Any other author and it does not count as a contribution on the profile graph. Check with:

```bash
git log --format='%an <%ae>' -5
```

## Before pushing

- [ ] `make check` green
- [ ] `python3 scripts/check_context.py` green
- [ ] Final diff read — scope, secrets, leftovers
- [ ] `STATUS.md` matches reality if the change moved it
- [ ] An ADR exists if a decision was made or reversed

## What never goes in a commit

The pre-commit hook enforces the first two; the rest is judgement.

- Anything under the data directory, any `*.db`, any rendered `*.pdf` or `*.docx`
- Anything credential-shaped — API keys, tokens, private keys, a real `.env`
- A weakened test guarding the three rules in `AGENTS.md`. Change one deliberately, in its own commit, and say why.

The repository is public. Assume everything committed is permanent.

## Decisions

A choice that is expensive to reverse gets an ADR in `docs/adr/`: context, options, decision, consequences. Numbered, immutable once accepted, superseded rather than edited.

A file naming convention is not an architecture decision. Storage engine, data location, whether the agent may submit an application — those are.
