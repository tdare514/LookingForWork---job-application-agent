from __future__ import annotations

import pytest

from jobagent.core.migrations import MIGRATIONS
from jobagent.core.storage import SecretLeakError, Storage


def test_migrations_apply_on_a_fresh_database(store: Storage) -> None:
    assert store.schema_version() == MIGRATIONS[-1].version
    expected = {"jobs", "job_sightings", "applications", "audit_log", "documents"}
    assert expected.issubset(store.tables())


def test_migrations_are_idempotent(store: Storage) -> None:
    before = store.schema_version()
    store.close()
    with Storage(store.path) as reopened:
        assert reopened.schema_version() == before


def test_profile_round_trips(store: Storage) -> None:
    payload = {"target_titles": ["Business Analyst"], "locations": ["Toronto, ON"]}
    store.put_singleton("profile", payload, version=1)
    assert store.get_singleton("profile") == payload


def test_profile_overwrites_rather_than_duplicating(store: Storage) -> None:
    store.put_singleton("profile", {"a": 1}, version=1)
    store.put_singleton("profile", {"a": 2}, version=2)
    assert store.count("profile") == 1
    assert store.get_singleton("profile") == {"a": 2}


def test_audit_log_is_readable_newest_first(store: Storage) -> None:
    store.append_audit("first", {"n": 1})
    store.append_audit("second", {"n": 2})
    entries = store.audit_entries()
    assert [e["action"] for e in entries] == ["second", "first"]


def test_storage_exposes_no_way_to_delete_audit_entries() -> None:
    """The append-only guarantee is structural, not a convention."""
    forbidden = {"delete_audit", "update_audit", "clear_audit", "remove_audit"}
    assert forbidden.isdisjoint(dir(Storage))


@pytest.mark.parametrize(
    "payload",
    [
        {"api_key": "sk-live-abc123"},
        {"nested": {"access_token": "abc"}},
        {"items": [{"password": "hunter2"}]},
    ],
)
def test_secrets_cannot_be_written_to_the_database(
    store: Storage, payload: dict[str, object]
) -> None:
    """Credentials belong in the keychain (#15). A shared path is the bug."""
    with pytest.raises(SecretLeakError):
        store.put_singleton("profile", payload, version=1)
