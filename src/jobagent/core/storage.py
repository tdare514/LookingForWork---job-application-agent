"""SQLite storage and the repository layer.

One database file, per docs/adr/0003-local-first-storage.md. The single-file
property is what makes backup, export, and purge verifiable rather than
aspirational -- it is a privacy control as much as a storage decision.

No feature code executes SQL directly; it goes through ``Storage``.
"""

from __future__ import annotations

import json
import re
import sqlite3
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import UTC, datetime
from pathlib import Path
from types import TracebackType
from typing import Any

from jobagent.core.migrations import MIGRATIONS
from jobagent.core.paths import database_path

# Secrets never reach this database. They resolve from the keychain or the
# environment (#15); a shared code path between the two is a bug with a test.
FORBIDDEN_COLUMN_SUBSTRINGS = ("secret", "token", "password", "api_key", "apikey")

# Credential shapes, in values rather than keys. Deliberately narrow, matching
# scripts/check_context.py: a check that fires on ordinary prose gets disabled,
# and a disabled check protects nothing.
SECRET_VALUE = re.compile(
    r"(sk-[A-Za-z0-9]{16,}|ghp_[A-Za-z0-9]{20,}|AKIA[0-9A-Z]{16}"
    r"|-----BEGIN [A-Z ]*PRIVATE KEY-----)"
)


def utcnow() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds")


class SecretLeakError(RuntimeError):
    """Raised when a write looks like it is storing a credential."""


class Storage:
    """Owns the connection and the schema. Use as a context manager."""

    def __init__(self, path: Path | None = None) -> None:
        self.path = path or database_path()
        self._conn: sqlite3.Connection | None = None

    # -- lifecycle ---------------------------------------------------------

    def connect(self) -> sqlite3.Connection:
        if self._conn is None:
            conn = sqlite3.connect(self.path)
            conn.row_factory = sqlite3.Row
            conn.execute("PRAGMA foreign_keys = ON")
            conn.execute("PRAGMA journal_mode = WAL")
            self._conn = conn
            self._migrate(conn)
        return self._conn

    def close(self) -> None:
        if self._conn is not None:
            self._conn.close()
            self._conn = None

    def __enter__(self) -> Storage:
        self.connect()
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None:
        self.close()

    # -- migrations --------------------------------------------------------

    def _migrate(self, conn: sqlite3.Connection) -> None:
        conn.execute(
            "CREATE TABLE IF NOT EXISTS schema_migrations ("
            " version INTEGER PRIMARY KEY, name TEXT NOT NULL, applied_at TEXT NOT NULL)"
        )
        applied = {row[0] for row in conn.execute("SELECT version FROM schema_migrations")}
        for migration in MIGRATIONS:
            if migration.version in applied:
                continue
            conn.executescript(migration.sql)
            conn.execute(
                "INSERT INTO schema_migrations (version, name, applied_at) VALUES (?, ?, ?)",
                (migration.version, migration.name, utcnow()),
            )
            conn.commit()

    def schema_version(self) -> int:
        row = self.connect().execute("SELECT MAX(version) FROM schema_migrations").fetchone()
        return int(row[0]) if row and row[0] is not None else 0

    def tables(self) -> set[str]:
        rows = self.connect().execute(
            "SELECT name FROM sqlite_master WHERE type = 'table' AND name NOT LIKE 'sqlite_%'"
        )
        return {r[0] for r in rows}

    def columns(self, table: str) -> set[str]:
        rows = self.connect().execute(f"PRAGMA table_info({table})")
        return {r[1] for r in rows}

    @contextmanager
    def transaction(self) -> Iterator[sqlite3.Connection]:
        conn = self.connect()
        try:
            yield conn
            conn.commit()
        except Exception:
            conn.rollback()
            raise

    # -- singletons: profile and resume -----------------------------------

    def put_singleton(self, table: str, payload: dict[str, Any], version: int) -> None:
        if table not in {"profile", "resume"}:
            raise ValueError(f"not a singleton table: {table}")
        reject_secret_shaped(payload)
        with self.transaction() as conn:
            conn.execute(
                f"INSERT INTO {table} (id, payload, version, updated_at) VALUES (1, ?, ?, ?) "
                f"ON CONFLICT(id) DO UPDATE SET payload = excluded.payload, "
                f"version = excluded.version, updated_at = excluded.updated_at",
                (json.dumps(payload), version, utcnow()),
            )

    def get_singleton(self, table: str) -> dict[str, Any] | None:
        if table not in {"profile", "resume"}:
            raise ValueError(f"not a singleton table: {table}")
        row = self.connect().execute(f"SELECT payload FROM {table} WHERE id = 1").fetchone()
        if row is None:
            return None
        loaded: dict[str, Any] = json.loads(row["payload"])
        return loaded

    # -- audit trail -------------------------------------------------------

    def append_audit(self, action: str, detail: dict[str, Any]) -> int:
        """Append-only. There is deliberately no update or delete counterpart."""
        with self.transaction() as conn:
            cur = conn.execute(
                "INSERT INTO audit_log (action, detail, occurred_at) VALUES (?, ?, ?)",
                (action, json.dumps(detail), utcnow()),
            )
        return int(cur.lastrowid or 0)

    def audit_entries(self, limit: int = 50) -> list[dict[str, Any]]:
        rows = self.connect().execute(
            "SELECT action, detail, occurred_at FROM audit_log ORDER BY id DESC LIMIT ?",
            (limit,),
        )
        return [
            {
                "action": r["action"],
                "detail": json.loads(r["detail"]),
                "occurred_at": r["occurred_at"],
            }
            for r in rows
        ]

    def last_audit(self, action: str) -> dict[str, Any] | None:
        """The most recent entry for one action, or None if it never ran.

        A read, so the append-only rule above is untouched. This is what lets
        the digest answer "since you last looked" without a table of its own:
        the audit log already records that `score` and `digest` ran, and that is
        the same fact a run-marker would have stored.

        None is a normal answer -- a fresh install, or after `purge` clears the
        log -- and the caller falls back to a window rather than implying a
        comparison it could not make.
        """
        row = (
            self.connect()
            .execute(
                "SELECT action, detail, occurred_at FROM audit_log WHERE action = ?"
                " ORDER BY id DESC LIMIT 1",
                (action,),
            )
            .fetchone()
        )
        if row is None:
            return None
        return {
            "action": row["action"],
            "detail": json.loads(row["detail"]),
            "occurred_at": row["occurred_at"],
        }

    def count(self, table: str) -> int:
        if table not in self.tables():
            raise ValueError(f"unknown table: {table}")
        row = self.connect().execute(f"SELECT COUNT(*) FROM {table}").fetchone()
        return int(row[0])


def reject_secret_shaped(payload: dict[str, Any]) -> None:
    """Refuse a payload that looks like it is carrying a credential.

    Cheap, and it catches the realistic accident: an API key pasted into a
    profile file and saved straight into the dossier.

    Both halves are needed. A key named `api_key` is the careless case; a value
    that is a key under an innocent name like `notes` is the one that actually
    happens, because the person pasting it is not thinking about the field name.
    Callers may run this before a write (`put_singleton`) or at load, so a
    validate command can refuse without touching the database.
    """
    for key, value in _walk(payload):
        lowered = key.lower()
        if any(bad in lowered for bad in FORBIDDEN_COLUMN_SUBSTRINGS):
            raise SecretLeakError(
                f"refusing to store {key!r}: credentials belong in the keychain, not the database"
            )
        if isinstance(value, str) and SECRET_VALUE.search(value):
            raise SecretLeakError(
                f"the value of {key!r} looks like a credential: credentials belong in the "
                "keychain or the environment, never in a file and never in the database"
            )


def _walk(value: Any, key: str = "<root>") -> Iterator[tuple[str, Any]]:
    """Every (key, value) pair in a nested structure, keys carrying their name."""
    yield key, value
    if isinstance(value, dict):
        for k, v in value.items():
            yield from _walk(v, str(k))
    elif isinstance(value, list):
        for item in value:
            yield from _walk(item, key)
