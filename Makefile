# Always go through the project interpreter: a bare `mypy` or `ruff` on PATH may
# belong to a different Python and will disagree with CI.
PY ?= python3

.PHONY: check lint format typecheck test install hooks

install:
	$(PY) -m pip install -e ".[dev]"

check: lint typecheck test

lint:
	$(PY) -m ruff check src tests
	$(PY) -m ruff format --check src tests

format:
	$(PY) -m ruff format src tests
	$(PY) -m ruff check --fix src tests

typecheck:
	$(PY) -m mypy

test:
	$(PY) -m pytest -q

hooks:
	cp scripts/pre-commit .git/hooks/pre-commit && chmod +x .git/hooks/pre-commit
	@echo "pre-commit hook installed"
