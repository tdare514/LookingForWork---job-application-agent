"""Capturing board rows as eval fixtures (#65, #76).

These fixtures go into a **public** repository, read out of a data directory
holding a real dossier. So the tests that matter are not about what gets
exported -- they are about what cannot.

The guarantee is a field allowlist living in the repository layer beside the
query. The risk it defends against is nobody's malice and everybody's Tuesday:
someone adds a column to `jobs`, a `SELECT *` somewhere picks it up, and a note
naming a recruiter ends up in a git history that cannot be rewritten.
"""

from __future__ import annotations

import json
from pathlib import Path

from jobagent.core.storage import Storage
from jobagent.tracking.board import State
from jobagent.tracking.repo import BoardRepo

FIXTURES = Path(__file__).parent / "fixtures" / "postings.json"


def test_the_allowlist_matches_the_fixture_shape() -> None:
    """Drift either way is a bug: a missing field breaks the corpus, an extra
    one publishes something nobody reviewed."""
    published = set(json.loads(FIXTURES.read_text())[0])
    assert set(BoardRepo.FIXTURE_FIELDS) == published


def test_nothing_personal_is_exported_even_when_populated(store: Storage) -> None:
    """The test this file exists for.

    Every personal column is filled in with a marker, and the export must not
    contain any of them anywhere -- not under its own key, not smuggled into
    another field's value.
    """
    repo = BoardRepo(store)
    job, _ = repo.add(
        company="RBC",
        title="Risk Analyst Intern",
        location="Toronto, ON",
        description="A real posting body, which is the employer's own public text.",
        url="https://example.invalid/private-link",
    )
    repo.set_notes(job.id, "NOTES_MARKER referred by Sam, ask about the GenAI rollout")
    repo.set_state(job.id, State.SKIPPED, reason="REASON_MARKER the manager was rude")

    rows = repo.fixture_rows()
    assert len(rows) == 1
    blob = json.dumps(rows)

    for marker in ("NOTES_MARKER", "REASON_MARKER", "private-link"):
        assert marker not in blob, f"{marker} reached the export"
    for column in BoardRepo.NEVER_EXPORTED:
        assert column not in rows[0], f"{column} is exported"


def test_the_export_carries_exactly_the_allowlisted_keys(store: Storage) -> None:
    repo = BoardRepo(store)
    repo.add(company="TD", title="Data Analyst Intern", description="Body text.")
    assert set(repo.fixture_rows()[0]) == set(BoardRepo.FIXTURE_FIELDS)


def test_the_two_lists_do_not_overlap() -> None:
    """A column cannot be both allowed and forbidden; that would read as safe."""
    assert not set(BoardRepo.FIXTURE_FIELDS) & set(BoardRepo.NEVER_EXPORTED)


def test_a_row_without_a_description_is_not_captured(store: Storage) -> None:
    """A label has to be read off the posting text.

    Capturing a text-less row adds something nobody can honestly label, and
    `test_every_posting_carries_a_label` would then fail for a row that should
    never have been offered.
    """
    repo = BoardRepo(store)
    repo.add(company="BMO", title="Analyst")  # hand-added, no description
    repo.add(company="RBC", title="Intern", description="Has a body.")

    rows = repo.fixture_rows()
    assert [r["company"] for r in rows] == ["RBC"]


def test_provenance_survives_the_round_trip(store: Storage) -> None:
    """Source and source_id are what make a captured row traceable to a posting."""
    repo = BoardRepo(store)
    repo.add(
        company="RBC",
        title="Risk Analyst Intern",
        description="Body.",
        source="workday:rbc",
        source_id="R-0000186717",
    )
    row = repo.fixture_rows()[0]
    assert row["source"] == "workday:rbc"
    assert row["source_id"] == "R-0000186717"


def test_a_hand_added_row_still_gets_usable_provenance(store: Storage) -> None:
    """`jobagent add` records source 'manual' and the dedupe key as the id.

    Not a requisition number, because a hand-typed row never had one -- but
    stable across runs and derived from company, title and city, so `--new-only`
    can tell it from a genuinely new capture.
    """
    repo = BoardRepo(store)
    repo.add(company="RBC", title="Intern", description="Body.")
    row = repo.fixture_rows()[0]
    assert row["source"] == "manual"
    assert row["source_id"], "a row with no id cannot be de-duplicated on re-capture"
    assert "rbc" in row["source_id"]


def test_employment_type_is_null_rather_than_guessed(store: Storage) -> None:
    """It lives on the adapter's RawPosting; the board never persists it."""
    repo = BoardRepo(store)
    repo.add(company="RBC", title="Intern", description="Body.")
    assert repo.fixture_rows()[0]["employment_type"] is None


def test_the_script_writes_nothing(store: Storage) -> None:
    """Stdout only. Nothing in the repository is touched by a capture run."""
    import subprocess
    import sys

    repo = BoardRepo(store)
    repo.add(company="RBC", title="Intern", description="Body text here.")

    script = Path(__file__).resolve().parents[1] / "scripts" / "capture_postings.py"
    before = FIXTURES.read_bytes()

    result = subprocess.run(
        [sys.executable, str(script)], capture_output=True, text=True, check=False
    )

    assert result.returncode == 0, result.stderr
    assert FIXTURES.read_bytes() == before, "the capture script modified a fixture"
    captured = json.loads(result.stdout)
    assert captured[0]["company"] == "RBC"
    assert set(captured[0]) == set(BoardRepo.FIXTURE_FIELDS)


def test_the_script_says_so_when_there_is_nothing_to_capture(store: Storage) -> None:
    """A silent empty capture would look like a successful one."""
    import subprocess
    import sys

    script = Path(__file__).resolve().parents[1] / "scripts" / "capture_postings.py"
    result = subprocess.run(
        [sys.executable, str(script)], capture_output=True, text=True, check=False
    )

    assert result.returncode == 1
    assert "fetch" in result.stderr
    assert result.stdout.strip() == "", "nothing should reach stdout when there is nothing to say"


def test_already_captured_is_a_different_message_from_nothing_to_capture(
    store: Storage,
) -> None:
    """Two problems, two fixes: fetch more, versus fetch at all.

    Found by running it -- `--new-only` on a fully-captured board said "run
    `jobagent fetch --details` first", which is advice for a different problem.
    """
    import subprocess
    import sys

    known = json.loads(FIXTURES.read_text())[0]
    repo = BoardRepo(store)
    repo.add(
        company=known["company"],
        title=known["title"],
        location=known.get("location"),
        description="Body text.",
        source=known["source"],
        source_id=known["source_id"],
    )

    script = Path(__file__).resolve().parents[1] / "scripts" / "capture_postings.py"
    result = subprocess.run(
        [sys.executable, str(script), "--new-only"],
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 1
    assert "already in" in result.stderr
    assert "jobagent fetch" not in result.stderr, "that is advice for the other problem"
