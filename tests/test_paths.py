"""The data directory must not be publishable by accident."""

from __future__ import annotations

import stat
from pathlib import Path

import pytest

from jobagent.core.paths import (
    default_data_dir,
    ensure_data_dir,
    is_inside_repository,
)


def test_default_data_dir_is_outside_the_working_tree(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("JOBAGENT_DATA_DIR", raising=False)
    monkeypatch.delenv("XDG_DATA_HOME", raising=False)
    repo_root = Path(__file__).resolve().parents[1]
    assert not is_inside_repository(default_data_dir(), repo_root)


def test_data_dir_is_owner_only(data_dir: Path) -> None:
    created = ensure_data_dir()
    mode = stat.S_IMODE(created.stat().st_mode)
    assert mode == 0o700, f"expected 0o700, got {oct(mode)}"


def test_ensure_creates_document_and_raw_subdirs(data_dir: Path) -> None:
    created = ensure_data_dir()
    assert (created / "documents").is_dir()
    assert (created / "raw").is_dir()


def test_env_override_is_respected(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    target = tmp_path / "elsewhere"
    monkeypatch.setenv("JOBAGENT_DATA_DIR", str(target))
    assert default_data_dir() == target.resolve()
