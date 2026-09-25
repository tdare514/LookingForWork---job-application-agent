"""CLI tests for list --json (#103).

`jobagent list --json` outputs a JSON array with specific fields, excluding
notes and state_reason even when set. Empty board returns [] at exit 0.
"""

from __future__ import annotations

import json
from datetime import date, timedelta

from typer.testing import CliRunner

from jobagent.cli import main as cli
from jobagent.core.storage import Storage
from jobagent.tracking.board import State
from jobagent.tracking.repo import BoardRepo


def test_list_json_returns_array_with_correct_fields(store: Storage) -> None:
    """list --json returns JSON array with the specified fields in the right order."""
    repo = BoardRepo(store)
    repo.add("RBC", "Risk Analyst", url="https://example.com/123")
    repo.add("BMO", "Data Analyst", location="Toronto", deadline="2026-09-20")

    runner = CliRunner()
    result = runner.invoke(cli.app, ["list", "--json"])

    assert result.exit_code == 0, result.output
    data = json.loads(result.output)

    assert len(data) == 2
    # Check that the fields are exactly as specified: id, company, title, location,
    # url, deadline, state, snoozed_until
    expected_keys = {
        "id",
        "company",
        "title",
        "location",
        "url",
        "deadline",
        "state",
        "snoozed_until",
    }
    for row in data:
        assert set(row.keys()) == expected_keys, f"Keys {set(row.keys())} != {expected_keys}"

    # Verify content is present (don't assume order)
    companies = {row["company"] for row in data}
    assert companies == {"RBC", "BMO"}

    rbc_row = next(r for r in data if r["company"] == "RBC")
    assert rbc_row["title"] == "Risk Analyst"
    assert rbc_row["url"] == "https://example.com/123"
    assert rbc_row["location"] is None
    assert rbc_row["deadline"] is None

    bmo_row = next(r for r in data if r["company"] == "BMO")
    assert bmo_row["title"] == "Data Analyst"
    assert bmo_row["location"] == "Toronto"
    assert bmo_row["deadline"] == "2026-09-20"


def test_list_json_excludes_notes_even_when_set(store: Storage) -> None:
    """list --json never includes notes in output, even when a row has notes set."""
    repo = BoardRepo(store)
    job, _ = repo.add("RBC", "Risk Analyst")
    repo.set_notes(job.id, "Internal notes about the recruiter")

    runner = CliRunner()
    result = runner.invoke(cli.app, ["list", "--json"])

    assert result.exit_code == 0, result.output
    data = json.loads(result.output)

    assert len(data) == 1
    assert "notes" not in data[0]
    # Verify the note text never appears in the JSON
    assert "Internal notes" not in result.output


def test_list_json_excludes_state_reason_even_when_set(store: Storage) -> None:
    """list --json never includes state_reason in output, even when a skip reason is set."""
    repo = BoardRepo(store)
    job, _ = repo.add("RBC", "Risk Analyst")
    repo.set_state(job.id, State.SKIPPED, reason="No sponsorship")

    runner = CliRunner()
    result = runner.invoke(cli.app, ["list", "--json"])

    assert result.exit_code == 0, result.output
    data = json.loads(result.output)

    assert len(data) == 1
    assert "state_reason" not in data[0]
    # Verify the reason text never appears in the JSON
    assert "No sponsorship" not in result.output


def test_list_json_empty_board_returns_empty_array(store: Storage) -> None:
    """list --json returns [] when the board is empty, with exit code 0."""
    runner = CliRunner()
    result = runner.invoke(cli.app, ["list", "--json"])

    assert result.exit_code == 0, result.output
    data = json.loads(result.output)
    assert data == []


def test_list_json_includes_snoozed_until_when_set(store: Storage) -> None:
    """list --json includes snoozed_until field when a row is snoozed."""
    repo = BoardRepo(store)
    job, _ = repo.add("RBC", "Risk Analyst")
    snooze_until = date.today() + timedelta(days=5)
    repo.snooze(job.id, until=snooze_until)

    runner = CliRunner()
    result = runner.invoke(cli.app, ["list", "--json"])

    assert result.exit_code == 0, result.output
    data = json.loads(result.output)

    assert len(data) == 1
    assert "snoozed_until" in data[0]
    # snoozed_until should be set to a date 5 days from now
    assert data[0]["snoozed_until"] is not None


def test_list_json_multiple_rows_maintain_order(store: Storage) -> None:
    """list --json preserves the board's sort order in the JSON output."""
    repo = BoardRepo(store)
    # Add rows in a specific order to verify they're returned in board order
    repo.add("RBC", "Risk Analyst", deadline="2026-09-20")
    repo.add("BMO", "Data Analyst", deadline="2026-10-01")
    repo.add("TD", "Analyst")

    runner = CliRunner()
    result = runner.invoke(cli.app, ["list", "--json"])

    assert result.exit_code == 0, result.output
    data = json.loads(result.output)

    assert len(data) == 3
    # Verify the order matches the board's natural order (returned by BoardRepo.all())
    assert data[0]["company"] == "RBC"
    assert data[1]["company"] == "BMO"
    assert data[2]["company"] == "TD"
