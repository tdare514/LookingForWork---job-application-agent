"""CLI tests for global options (#26).

Global options live on the root callback so every command answers to them.
- `--version` prints the version and exits 0.
- `--data-dir` sets the data directory, refusing paths inside the repository.
- Without `--data-dir`, environment variables are unchanged.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from typer.testing import CliRunner

from jobagent import __version__
from jobagent.cli import main as cli


def test_version_flag_prints_version() -> None:
    """--version prints 'jobagent <version>' and exits 0."""
    runner = CliRunner()
    result = runner.invoke(cli.app, ["--version"])

    assert result.exit_code == 0, result.output
    assert result.output.strip() == f"jobagent {__version__}"


def test_data_dir_flag_sets_environment_variable(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """--data-dir <path> init creates the directory at that path, not the default."""
    # Set, not deleted: the callback writes os.environ directly, and monkeypatch
    # only restores a variable it has recorded. delenv on an unset name records
    # nothing, so the flag's value would leak into every later test.
    monkeypatch.setenv("JOBAGENT_DATA_DIR", str(tmp_path / "not-this-one"))

    target_dir = tmp_path / "custom_data"
    runner = CliRunner()
    result = runner.invoke(cli.app, ["--data-dir", str(target_dir), "init"])

    assert result.exit_code == 0, result.output
    # The directory should be created at the specified path
    assert target_dir.exists()
    # The database file should exist to prove init ran
    assert (target_dir / "jobagent.db").exists()
    assert not (tmp_path / "not-this-one").exists()


def test_data_dir_inside_repository_is_refused(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """--data-dir pointing inside a .git repository is refused with exit code 2."""
    monkeypatch.setenv("JOBAGENT_DATA_DIR", str(tmp_path / "not-this-one"))

    # Create a fake repository structure in tmp_path
    fake_repo = tmp_path / "fake_repo"
    fake_repo.mkdir()
    (fake_repo / ".git").mkdir()

    # Change to the fake repo so _repository_root can find it
    monkeypatch.chdir(fake_repo)

    # Try to set data directory inside the repo
    data_dir_inside_repo = fake_repo / "data"

    runner = CliRunner()
    result = runner.invoke(cli.app, ["--data-dir", str(data_dir_inside_repo), "init"])

    # Should exit with code 2 (refusal)
    assert result.exit_code == 2, result.output
    # The directory should NOT be created
    assert not data_dir_inside_repo.exists()
    # The error message should mention the refusal and the rule
    assert "Refusing" in result.output
    assert "docs/adr/0003" in result.output


def test_without_data_dir_flag_uses_environment_variable(
    data_dir: Path,
) -> None:
    """Without --data-dir, the command uses JOBAGENT_DATA_DIR from the environment.

    The callback returns early if --data-dir is not provided, leaving env vars alone.
    The data_dir fixture sets JOBAGENT_DATA_DIR and ensures it is used.
    """
    runner = CliRunner()
    # Use init without --data-dir (it will use the env var set by the data_dir fixture)
    result = runner.invoke(cli.app, ["init"])

    assert result.exit_code == 0, result.output
    # Verify that the directory used was the one from the fixture
    assert data_dir.exists()
    assert (data_dir / "jobagent.db").exists()
