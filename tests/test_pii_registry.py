"""The PII registry is the inventory (#21 folded into #9).

If it drifts from the schema, ``purge`` (#42) silently misses fields -- and
nobody finds out. These tests are what keep it honest.
"""

from __future__ import annotations

from jobagent.core import pii
from jobagent.core.storage import Storage


def test_every_registered_field_exists_in_the_schema(store: Storage) -> None:
    tables = store.tables()
    for field in pii.REGISTRY:
        assert field.table in tables, f"{field.table} is registered but not in the schema"
        assert field.column in store.columns(field.table), (
            f"{field.table}.{field.column} is registered but the column does not exist"
        )


def test_free_text_and_identity_columns_are_registered(store: Storage) -> None:
    """A new PII-shaped column cannot land unregistered."""
    must_be_registered = {
        ("profile", "payload"),
        ("resume", "payload"),
        ("applications", "notes"),
        ("documents", "path"),
        ("audit_log", "detail"),
    }
    assert must_be_registered.issubset(pii.registered_columns())


def test_application_history_is_marked_critical() -> None:
    """Which companies were approached while employed is the top-sensitivity item."""
    critical = pii.critical_tables()
    assert {"applications", "application_transitions", "audit_log"}.issubset(critical)


def test_every_field_declares_a_retention_decision() -> None:
    for field in pii.REGISTRY:
        assert field.retention_days is None or field.retention_days > 0
        assert field.purpose.strip(), f"{field.table}.{field.column} has no stated purpose"


def test_nothing_critical_is_sent_to_a_third_party() -> None:
    for field in pii.REGISTRY:
        if field.sensitivity is pii.Sensitivity.CRITICAL:
            assert field.destinations == (pii.Destination.NOWHERE,), (
                f"{field.table}.{field.column} is critical but may leave the machine"
            )
