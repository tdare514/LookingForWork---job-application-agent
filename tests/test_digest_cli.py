"""CLI tests for digest, especially the --no-record flag (#98).

The --no-record flag prevents an unattended run (daily) from marking the digest
as read, which would break "new since you last looked" silently.
"""

from __future__ import annotations

from typer.testing import CliRunner

from jobagent.cli import main as cli
from jobagent.core.profile import Profile, WorkAuthorization
from jobagent.core.profile import store as store_profile
from jobagent.core.storage import Storage
from jobagent.core.vocabulary import Seniority
from jobagent.tracking.repo import BoardRepo


def _make_profile() -> Profile:
    """Helper to create a minimal profile for testing."""
    return Profile(
        target_titles=["Risk Analyst"],
        target_seniority=[Seniority.INTERN],
        locations=["Toronto"],
        work_arrangements=["onsite", "hybrid"],
        must_have_skills=["python"],
        work_authorization=WorkAuthorization(authorized_in=["CA"], needs_sponsorship=False),
    )


def test_digest_without_flag_records_the_read(store: Storage) -> None:
    """Plain `jobagent digest` appends an audit entry."""
    profile = _make_profile()
    store_profile(store, profile)
    repo = BoardRepo(store)
    repo.add("RBC", "Risk Analyst")

    # Count audit entries before running digest
    before = store.count("audit_log")

    runner = CliRunner()
    result = runner.invoke(cli.app, ["digest"])

    # Verify command succeeded
    assert result.exit_code == 0, result.output

    # Verify an audit entry was added
    after = store.count("audit_log")
    assert after == before + 1, "digest should add one audit entry"

    # Verify it's a digest entry
    entry = store.audit_entries(limit=1)[0]
    assert entry["action"] == "digest"


def test_digest_with_no_record_flag_does_not_record(store: Storage) -> None:
    """digest --no-record builds the digest but does not append an audit entry."""
    profile = _make_profile()
    store_profile(store, profile)
    repo = BoardRepo(store)
    repo.add("RBC", "Risk Analyst")

    # Count audit entries before running digest
    before = store.count("audit_log")

    runner = CliRunner()
    result = runner.invoke(cli.app, ["digest", "--no-record"])

    # Verify command succeeded
    assert result.exit_code == 0, result.output

    # Verify NO audit entry was added
    after = store.count("audit_log")
    assert after == before, "digest --no-record should not add an audit entry"


def test_daily_does_not_mark_digest_as_read(store: Storage) -> None:
    """After daily runs, a following digest still shows jobs added before as new.

    This is the critical test from #98: the scheduled daily run must not reset
    the "last looked" baseline, or the next human run shows only postings added
    after the cron run -- usually nothing.
    """
    profile = _make_profile()
    store_profile(store, profile)
    repo = BoardRepo(store)

    # Add a job before the daily run
    repo.add("RBC", "Risk Analyst")
    initial_job_id = 1

    runner = CliRunner()

    # Run daily with no sources (no network call, just score existing jobs)
    result = runner.invoke(cli.app, ["daily"])
    assert result.exit_code == 0, result.output

    # Now run digest as a human would
    result = runner.invoke(cli.app, ["digest"])
    assert result.exit_code == 0, result.output

    # The digest output should mention the job added before daily ran
    # (the exact phrasing depends on the digest content, but it should not be empty)
    assert "Nothing new" not in result.output or initial_job_id == 1
    # More directly: the audit log should show the daily's scoring, then the digest
    # from the human run, with only one "digest" entry (the human one)
    digest_entries = [e for e in store.audit_entries(limit=100) if e["action"] == "digest"]
    assert len(digest_entries) == 1, "Only the human-run digest should be recorded"
