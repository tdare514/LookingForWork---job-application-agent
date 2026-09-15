"""Data directory resolution.

The data directory holds the whole dossier: profile, resume, jobs, applications,
generated documents, and the audit log. It lives OUTSIDE the working tree by
default so that a stray ``git add -A`` cannot publish an application history.

See docs/adr/0003-local-first-storage.md.
"""

from __future__ import annotations

import os
from pathlib import Path

ENV_DATA_DIR = "JOBAGENT_DATA_DIR"
_DEFAULT_DIRNAME = "jobagent"


def default_data_dir() -> Path:
    """Platform-appropriate data directory, outside any repository."""
    override = os.environ.get(ENV_DATA_DIR)
    if override:
        return Path(override).expanduser().resolve()

    xdg = os.environ.get("XDG_DATA_HOME")
    if xdg:
        return Path(xdg).expanduser().resolve() / _DEFAULT_DIRNAME

    return Path.home().resolve() / ".local" / "share" / _DEFAULT_DIRNAME


def ensure_data_dir(path: Path | None = None) -> Path:
    """Create the data directory with owner-only permissions and return it."""
    target = path.expanduser().resolve() if path is not None else default_data_dir()
    target.mkdir(parents=True, exist_ok=True)
    # 0o700: the dossier is readable by its owner and nobody else.
    target.chmod(0o700)
    (target / "documents").mkdir(exist_ok=True)
    (target / "raw").mkdir(exist_ok=True)
    return target


def database_path(data_dir: Path | None = None) -> Path:
    return ensure_data_dir(data_dir) / "jobagent.db"


def is_inside_repository(path: Path, repo_root: Path) -> bool:
    """True when ``path`` sits inside ``repo_root`` -- used to assert it does not."""
    try:
        path.resolve().relative_to(repo_root.resolve())
    except ValueError:
        return False
    return True
