# Contributing

Single contributor, two-week build. This file exists so a fresh machine gets
running in under a minute.

## Setup

```bash
python3 -m venv .venv && source .venv/bin/activate
make install     # pip install -e ".[dev]"
make hooks       # install the pre-commit hook
```

## Daily loop

```bash
make check       # ruff + mypy (strict) + pytest -- run before every push
make format      # apply ruff formatting and safe fixes
```

## First run

```bash
jobagent init    # create the data directory and apply migrations
jobagent status  # where data lives and what is in it
jobagent pii     # what is stored, why, and for how long
jobagent audit   # the append-only trail of what the agent did
```

## Where data lives

**Not in this repository.** `~/.local/share/jobagent` by default, mode `0o700`,
overridable with `JOBAGENT_DATA_DIR`. See
[`docs/adr/0003-local-first-storage.md`](docs/adr/0003-local-first-storage.md).

The pre-commit hook refuses any commit containing a database, a rendered PDF or
DOCX, anything under `data/`, or a credential-shaped string. If it fires, it is
right — move the value to the environment or the keychain.

## Rules that are not style preferences

1. **Secrets never touch the database.** `Storage` rejects credential-shaped
   keys, and a test asserts it.
2. **A new PII column must be registered** in `jobagent.core.pii`. A test fails
   otherwise, because `purge` walks that registry.
3. **The audit log is append-only.** There is no delete path, and a test asserts
   no such method exists.
4. **Nothing is sent without a recorded approval** (#24). The gate is
   structural, not a setting.
