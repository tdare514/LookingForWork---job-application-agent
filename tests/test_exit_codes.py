"""CLI exit codes (#120).

Exit codes distinguish user error from agent failure, so scripts and operators
can branch on the type of failure.

- `OK = 0`: successful execution.
- `USER_ERROR = 1`: user-caused failure (bad input, unknown id, missing config).
- `USAGE = 2`: POSIX usage error (bad flag, missing required argument).
- `AGENT_FAILURE = 3`: agent failure (source declined, companion error).
- `NOTHING_TO_DO = 4`: reserved; no command uses it yet.

AGENT_FAILURE is exercised where it happens, against a fake companion:
`tests/test_companion.py` (the Access gate off, a sync conflict, a purge that
cannot reach the hosted copy).
"""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

from typer.testing import CliRunner

from jobagent.cli import main as cli
from jobagent.cli.exit_codes import ExitCode
from jobagent.core.profile import Profile


def test_user_error_on_unknown_job_id(data_dir: Path) -> None:
    """An unknown job id exits with USER_ERROR."""
    runner = CliRunner()
    result = runner.invoke(cli.app, ["skip", "999", "-r", "test"])
    assert result.exit_code == ExitCode.USER_ERROR


def test_usage_error_on_missing_required_argument() -> None:
    """A missing required argument (Click's error) exits with USAGE.

    The skip command requires -r/--reason.
    """
    runner = CliRunner()
    result = runner.invoke(cli.app, ["skip", "1"])
    # Click will set exit code 2 for missing required options
    assert result.exit_code == ExitCode.USAGE


def test_user_error_on_uninitialized_data_dir(tmp_path: Path) -> None:
    """An uninitialized data directory exits with USER_ERROR."""
    runner = CliRunner()
    # Use --data-dir to point to a directory that does not exist
    result = runner.invoke(cli.app, ["--data-dir", str(tmp_path / "missing"), "status"])
    assert result.exit_code == ExitCode.USER_ERROR


def test_user_error_on_no_profile(data_dir: Path) -> None:
    """No profile set exits with USER_ERROR."""
    runner = CliRunner()
    result = runner.invoke(cli.app, ["shortlist"])
    assert result.exit_code == ExitCode.USER_ERROR


def test_user_error_on_unknown_source(data_dir: Path) -> None:
    """An unknown source name exits with USER_ERROR."""
    runner = CliRunner()
    result = runner.invoke(cli.app, ["fetch", "invalid-source", "--limit", "1"])
    assert result.exit_code == ExitCode.USER_ERROR


def test_user_error_on_invalid_job_id_for_extract(data_dir: Path) -> None:
    """An unknown job id for extract exits with USER_ERROR."""
    runner = CliRunner()
    result = runner.invoke(cli.app, ["extract", "999"])
    assert result.exit_code == ExitCode.USER_ERROR


def test_a_refused_flag_value_is_a_usage_error(data_dir: Path) -> None:
    """`--days 0` is a flag value snooze refuses, which Click would call usage."""
    runner = CliRunner()
    result = runner.invoke(cli.app, ["snooze", "1", "--days", "0"])
    assert result.exit_code == ExitCode.USAGE


def test_user_error_on_snooze_unknown_id(data_dir: Path) -> None:
    """An unknown job id for snooze exits with USER_ERROR."""
    runner = CliRunner()
    result = runner.invoke(cli.app, ["snooze", "999", "--days", "1"])
    assert result.exit_code == ExitCode.USER_ERROR


def test_no_literal_exit_code_integers_in_cli() -> None:
    """No `typer.Exit(code=<int literal>)` remains in src/jobagent/cli/.

    All exit calls must use ExitCode members, not literal integers.
    """
    import re

    cli_dir = Path(__file__).parent.parent / "src" / "jobagent" / "cli"
    for py_file in cli_dir.glob("*.py"):
        content = py_file.read_text()
        # Look for typer.Exit(code=<digit>) or raise typer.Exit(<digit>)
        # Exclude comments and the exit_codes.py file itself
        if py_file.name == "exit_codes.py":
            continue
        for line_no, line in enumerate(content.split("\n"), start=1):
            # Skip comments
            if line.strip().startswith("#"):
                continue
            # Match typer.Exit(code=<digit>) or typer.Exit(<digit>)
            if re.search(r"typer\.Exit\((?:code=)?\d+\)", line):
                raise AssertionError(
                    f"{py_file.name}:{line_no} has a literal exit code: {line.strip()}"
                )


def test_daily_exits_zero_on_quiet_day_with_no_sources(
    data_dir: Path, make_profile: Callable[..., Profile]
) -> None:
    """The `daily` command exits 0 when run without sources (no fetch attempted).

    The `daily` command requires a profile. When no sources are specified, it
    skips fetching and goes straight to digest, exiting 0 on a quiet board.
    """
    from jobagent.core.profile import store as store_profile
    from jobagent.core.storage import Storage

    # Create and store a minimal profile so daily can run
    profile = make_profile()
    with Storage() as store:
        store_profile(store, profile)

    runner = CliRunner()
    # Run daily with no sources: it will skip fetch and digest, exiting 0
    result = runner.invoke(cli.app, ["daily"])
    assert result.exit_code == 0


def test_list_exits_zero_on_empty_board(data_dir: Path) -> None:
    """The `list` command exits 0 when the board is empty."""
    runner = CliRunner()
    result = runner.invoke(cli.app, ["list"])
    assert result.exit_code == 0


def test_shortlist_exits_zero_on_nothing_above_threshold(
    data_dir: Path, make_profile: Callable[..., Profile]
) -> None:
    """The `shortlist` command exits 0 when nothing meets the threshold.

    This is a quiet result, not an error.
    """
    from jobagent.core.profile import store as store_profile
    from jobagent.core.storage import Storage

    profile = make_profile()
    with Storage() as store:
        store_profile(store, profile)

    runner = CliRunner()
    result = runner.invoke(cli.app, ["shortlist", "--min-score", "999"])
    assert result.exit_code == 0


def test_digest_exits_zero_on_empty_digest(
    data_dir: Path, make_profile: Callable[..., Profile]
) -> None:
    """The `digest` command exits 0 when there is nothing new to read."""
    from jobagent.core.profile import store as store_profile
    from jobagent.core.storage import Storage

    profile = make_profile()
    with Storage() as store:
        store_profile(store, profile)

    runner = CliRunner()
    result = runner.invoke(cli.app, ["digest"])
    assert result.exit_code == 0
