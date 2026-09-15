from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path

import pytest

from jobagent.core.storage import Storage


@pytest.fixture()
def data_dir(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    target = tmp_path / "data"
    monkeypatch.setenv("JOBAGENT_DATA_DIR", str(target))
    return target


@pytest.fixture()
def store(data_dir: Path) -> Iterator[Storage]:
    with Storage() as s:
        yield s
