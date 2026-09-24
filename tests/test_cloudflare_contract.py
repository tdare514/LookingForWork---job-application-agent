"""The hosted tracker (ADR 0010) must not drift from the local board or the PII registry.

`cloudflare/` is TypeScript and nothing here imports it, so the contract is read
from source and the D1 migrations are applied to an in-memory SQLite. Either
drifting would be silent: a phone edit writing a state the board cannot read, or
a critical column quietly gaining an off-machine copy.
"""

import re
import sqlite3
from pathlib import Path

from jobagent.companion.contract import FROM_BOARD, HOSTED_ONLY, IDENTIFIERS, PULLED_BACK
from jobagent.core.pii import REGISTRY, Destination, Sensitivity, by_table
from jobagent.tracking.board import State
from jobagent.tracking.snapshot import NEVER_SNAPSHOT

CLOUDFLARE = Path(__file__).resolve().parent.parent / "cloudflare"
TYPES = (CLOUDFLARE / "src" / "types.ts").read_text()


def _ts_array(name: str) -> list[str]:
    match = re.search(rf"export const {name} = \[(.*?)\] as const;", TYPES, re.S)
    assert match, f"{name} not found in cloudflare/src/types.ts"
    return re.findall(r'"([^"]+)"', match.group(1))


def _snake(name: str) -> str:
    return re.sub(r"(?<!^)(?=[A-Z])", "_", name).lower()


def _hosted_columns() -> set[str]:
    db = sqlite3.connect(":memory:")
    for migration in sorted((CLOUDFLARE / "migrations").glob("*.sql")):
        db.executescript(migration.read_text())
    return {row[1] for row in db.execute("PRAGMA table_info(jobs)")}


CRITICAL_JOB_COLUMNS = {f.column for f in by_table("jobs") if f.sensitivity is Sensitivity.CRITICAL}


def test_hosted_statuses_are_the_board_states() -> None:
    assert _ts_array("APPLICATION_STATUSES") == [state.value for state in State]


def test_sync_fields_carry_nothing_critical_or_refused() -> None:
    fields = {_snake(name) for name in _ts_array("SYNC_FIELDS")}
    assert "notes" not in fields
    assert fields.isdisjoint(CRITICAL_JOB_COLUMNS)
    assert fields.isdisjoint(NEVER_SNAPSHOT)


def test_hosted_table_holds_nothing_critical_or_refused() -> None:
    columns = _hosted_columns()
    assert "status" in columns  # the check is looking at the real table
    assert columns.isdisjoint(CRITICAL_JOB_COLUMNS)
    assert columns.isdisjoint(NEVER_SNAPSHOT)


def test_every_hosted_field_is_accounted_for() -> None:
    """A field added to the TypeScript contract must be placed here, or this fails."""
    sync_fields = set(_ts_array("SYNC_FIELDS"))
    assert sync_fields == set(FROM_BOARD) | set(HOSTED_ONLY) | set(IDENTIFIERS)
    assert set(PULLED_BACK) <= set(FROM_BOARD)


def test_the_registry_grants_exactly_what_the_contract_carries() -> None:
    granted = {
        (f.table, f.column) for f in REGISTRY if Destination.HOSTED_TRACKER in f.destinations
    }
    assert granted == {("jobs", column) for column in FROM_BOARD.values()}
