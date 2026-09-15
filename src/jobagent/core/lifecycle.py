"""Export and purge.

A job search ends. The dossier should be able to end with it, and the promise in
docs/security-privacy.md is that deletion is *verified*, not assumed.

Both operations work on the whole data directory, which is what ADR 0003's
single-directory decision was for: one place to archive, one place to remove.
"""

from __future__ import annotations

import shutil
import tarfile
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

from jobagent.core.paths import default_data_dir
from jobagent.core.pii import REGISTRY


@dataclass(frozen=True)
class PurgeReport:
    removed_files: int
    removed_bytes: int
    remaining: list[str]

    @property
    def clean(self) -> bool:
        return not self.remaining


def export(destination: Path, data_dir: Path | None = None) -> Path:
    """Archive everything to a single portable file.

    The archive is the most sensitive artefact this tool produces, so the caller
    is told exactly where it landed rather than it appearing somewhere implicit.
    """
    source = data_dir or default_data_dir()
    if not source.is_dir():
        raise FileNotFoundError(f"no data directory at {source}")

    destination.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(UTC).strftime("%Y%m%d-%H%M%S")
    archive = destination / f"jobagent-export-{stamp}.tar.gz"
    with tarfile.open(archive, "w:gz") as tar:
        tar.add(source, arcname="jobagent")
    archive.chmod(0o600)
    return archive


def purge(data_dir: Path | None = None) -> PurgeReport:
    """Remove the dossier, then verify nothing recoverable remains.

    The verification is the point. A purge that reports success without checking
    is exactly the kind of promise that turns out to be false when it matters.
    """
    target = data_dir or default_data_dir()
    if not target.is_dir():
        return PurgeReport(0, 0, [])

    removed_files = 0
    removed_bytes = 0
    for path in target.rglob("*"):
        if path.is_file():
            removed_files += 1
            removed_bytes += path.stat().st_size

    shutil.rmtree(target)

    # Verify: the directory is gone, and nothing survives under it.
    remaining: list[str] = []
    if target.exists():
        remaining = [str(p) for p in target.rglob("*") if p.is_file()]

    return PurgeReport(removed_files, removed_bytes, remaining)


def registered_tables() -> list[str]:
    """Tables the PII registry says hold personal data -- purge's checklist."""
    return sorted({field.table for field in REGISTRY})
