"""CLI tests for digest, especially the --no-record flag (#98).

The --no-record flag prevents an unattended run (daily) from marking the digest
as read, which would break "new since you last looked" silently.
"""

from __future__ import annotations

import json

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
    """After daily runs, the next digest still measures "new" from the owner's last read.

    The critical test from #98. "New" is every row first seen on or after the date
    of the last recorded digest, so an unattended daily that recorded one would
    move that date forward every morning, and anything not read on its first day
    would drop out of "new". Asserting on the baseline rather than on a particular
    row appearing keeps this independent of whether that row clears the
    shortlist's score threshold.
    """
    store_profile(store, _make_profile())
    BoardRepo(store).add("RBC", "Risk Analyst")

    runner = CliRunner()
    # No --source, so no network: daily extracts, scores and prints the digest.
    result = runner.invoke(cli.app, ["daily"])
    assert result.exit_code == 0, result.output

    digest_entries = [e for e in store.audit_entries(limit=100) if e["action"] == "digest"]
    assert digest_entries == [], "daily must not record a digest read"

    result = runner.invoke(cli.app, ["digest", "--json", "--no-record"])
    assert result.exit_code == 0, result.output
    payload = json.loads(result.output)
    assert "no previous digest" in payload["since_source"]
