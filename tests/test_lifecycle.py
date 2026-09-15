"""Export and purge. The verification is the feature."""

from __future__ import annotations

import tarfile
from pathlib import Path

import pytest

from jobagent.core.lifecycle import export, purge, registered_tables
from jobagent.core.paths import ensure_data_dir
from jobagent.core.storage import Storage
from jobagent.tracking.repo import BoardRepo


def _populate(store: Storage) -> None:
    repo = BoardRepo(store)
    repo.add("BMO", "Business Analyst")
    repo.set_notes(1, "Recruiter: Jane Smith, jane@example.com")
    store.append_audit("test", {"note": "applied to BMO"})


def test_export_produces_one_portable_archive(store: Storage, tmp_path: Path) -> None:
    _populate(store)
    store.close()
    archive = export(tmp_path / "out")
    assert archive.is_file()
    with tarfile.open(archive) as tar:
        names = tar.getnames()
    assert any(n.endswith("jobagent.db") for n in names)


def test_the_archive_is_owner_only(store: Storage, tmp_path: Path) -> None:
    """The export is the most sensitive artefact this tool produces."""
    import stat

    _populate(store)
    store.close()
    archive = export(tmp_path / "out")
    assert stat.S_IMODE(archive.stat().st_mode) == 0o600


def test_purge_leaves_nothing_recoverable(store: Storage) -> None:
    """The commitment in docs/security-privacy.md, actually checked."""
    _populate(store)
    data_dir = ensure_data_dir()
    store.close()

    report = purge()
    assert report.removed_files > 0
    assert report.clean, f"survived purge: {report.remaining}"
    assert not data_dir.exists()


def test_purge_removes_the_application_history_specifically(store: Storage) -> None:
    """The highest-sensitivity item: which companies were approached."""
    _populate(store)
    data_dir = ensure_data_dir()
    store.close()

    # Assert over the whole directory, not just jobagent.db: SQLite runs in WAL
    # mode, so a recent write may still live in a sidecar file at this point.
    def holds_company(root: Path) -> bool:
        return any(p.is_file() and b"BMO" in p.read_bytes() for p in root.rglob("*"))

    assert holds_company(data_dir), "fixture did not land; the test would pass vacuously"

    purge()
    assert not (data_dir / "jobagent.db").exists()
    if data_dir.exists():
        assert not holds_company(data_dir)


def test_purging_nothing_is_not_an_error(store: Storage) -> None:
    store.close()
    purge()
    report = purge()  # second time: already gone
    assert report.clean and report.removed_files == 0


def test_export_without_a_data_directory_fails_loudly(tmp_path: Path) -> None:
    with pytest.raises(FileNotFoundError):
        export(tmp_path / "out", data_dir=tmp_path / "nope")


def test_purge_checklist_comes_from_the_pii_registry() -> None:
    """If a table holds PII but is not registered, purge cannot know about it."""
    tables = registered_tables()
    assert {"jobs", "applications", "audit_log", "documents"}.issubset(set(tables))
