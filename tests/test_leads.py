"""Importing a triaged shortlist onto the board (#77).

The tests that matter here are the destructive ones. This command writes
somebody else's judgement into a live personal board, so what it must never do
is more important than what it does: never lose a hand-typed note, never walk a
row backwards from applied, never write anything at all when the file is
malformed.
"""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml
from pydantic import ValidationError

from jobagent.core.storage import Storage
from jobagent.tracking.board import State
from jobagent.tracking.leads import (
    NOTE_MARKER,
    Shortlist,
    apply_to_board,
    load_file,
    merge_notes,
)
from jobagent.tracking.repo import BoardRepo

EXAMPLE = Path(__file__).resolve().parents[1] / "shortlist.example.yaml"


def _shortlist(**overrides: object) -> Shortlist:
    base: dict[str, object] = {
        "source": "chatgpt-daily-search",
        "retrieved": "2026-09-15",
        "leads": [
            {
                "company": "RBC Borealis",
                "title": "AI Business Analyst (Winter 2027, 8 months)",
                "location": "Toronto, ON",
                "deadline": "2026-09-20",
                "verdict": "apply",
                "fit": 9.8,
                "why": "Requirements gathering, Jira, stakeholder decks, AI MVPs.",
                "gaps": "No formal SQL.",
            }
        ],
    }
    base.update(overrides)
    return Shortlist.model_validate(base)


def _write(tmp_path: Path, payload: object) -> Path:
    target = tmp_path / "shortlist.yaml"
    target.write_text(yaml.safe_dump(payload))
    return target


# -- the example ---------------------------------------------------------------


def test_the_example_shortlist_is_valid() -> None:
    """Validated in CI so the file people copy cannot rot."""
    shortlist = load_file(EXAMPLE)
    assert shortlist.source
    assert len(shortlist.leads) >= 2


# -- importing -----------------------------------------------------------------


def test_a_lead_lands_on_the_board_with_its_reasoning(store: Storage) -> None:
    repo = BoardRepo(store)
    report = apply_to_board(repo, _shortlist())

    assert report.added == 1
    job = repo.all()[0]
    assert job.company == "RBC Borealis"
    assert job.state == State.READY
    assert job.deadline == "2026-09-20"
    assert job.notes is not None
    assert "9.8/10" in job.notes
    assert "Requirements gathering" in job.notes


def test_the_note_says_who_judged_it_and_when(store: Storage) -> None:
    """A fit score with no date reads as current. In three weeks it is not."""
    repo = BoardRepo(store)
    apply_to_board(repo, _shortlist())
    notes = repo.all()[0].notes or ""
    assert "chatgpt-daily-search" in notes
    assert "2026-09-15" in notes


def test_a_verdict_maps_to_the_board_state(store: Storage) -> None:
    repo = BoardRepo(store)
    apply_to_board(
        repo,
        _shortlist(
            leads=[
                {"company": "A", "title": "Applyable role", "verdict": "apply"},
                {"company": "B", "title": "Maybe role", "verdict": "maybe"},
                {"company": "C", "title": "Skippable role", "verdict": "skip"},
            ]
        ),
    )
    states = {job.company: job.state for job in repo.all()}
    assert states == {"A": State.READY, "B": State.NEW, "C": State.SKIPPED}


def test_maybe_does_not_shout(store: Storage) -> None:
    """A board where every row is yellow has no signal left in it."""
    repo = BoardRepo(store)
    apply_to_board(repo, _shortlist(leads=[{"company": "A", "title": "T", "verdict": "maybe"}]))
    assert repo.all()[0].state == State.NEW


def test_re_importing_the_same_digest_changes_nothing(store: Storage) -> None:
    repo = BoardRepo(store)
    shortlist = _shortlist()
    apply_to_board(repo, shortlist)
    before = repo.all()[0]

    second = apply_to_board(repo, shortlist)
    after = repo.all()[0]

    assert len(repo.all()) == 1
    assert second.added == 0
    assert after.notes == before.notes


# -- what it must never do -----------------------------------------------------


def test_a_row_already_applied_to_is_left_alone(store: Storage) -> None:
    """The expensive mistake: an overnight search dragging a submitted
    application back to "needs you", so it gets applied to twice."""
    repo = BoardRepo(store)
    job, _ = repo.add(
        "RBC Borealis", "AI Business Analyst (Winter 2027, 8 months)", location="Toronto, ON"
    )
    repo.set_state(job.id, State.APPLIED)

    report = apply_to_board(repo, _shortlist())

    assert report.left_alone == 1
    assert report.added == 0
    reloaded = repo.get(job.id)
    assert reloaded is not None
    assert reloaded.state == State.APPLIED


def test_an_interviewing_row_is_left_alone(store: Storage) -> None:
    repo = BoardRepo(store)
    job, _ = repo.add(
        "RBC Borealis", "AI Business Analyst (Winter 2027, 8 months)", location="Toronto, ON"
    )
    repo.set_state(job.id, State.INTERVIEW)
    apply_to_board(repo, _shortlist())
    reloaded = repo.get(job.id)
    assert reloaded is not None
    assert reloaded.state == State.INTERVIEW


def test_hand_typed_notes_survive_an_import(store: Storage) -> None:
    """The most valuable text on the board is the recruiter's name somebody
    typed at 9pm. An importer that overwrites it is worse than none."""
    repo = BoardRepo(store)
    job, _ = repo.add(
        "RBC Borealis", "AI Business Analyst (Winter 2027, 8 months)", location="Toronto, ON"
    )
    repo.set_notes(job.id, "Referred by Sam on the platform team. Ask about the GenAI rollout.")

    apply_to_board(repo, _shortlist())

    reloaded = repo.get(job.id)
    assert reloaded is not None
    assert reloaded.notes is not None
    assert "Referred by Sam" in reloaded.notes
    assert "9.8/10" in reloaded.notes


def test_re_importing_replaces_only_the_imported_block() -> None:
    """Otherwise a daily digest grows the note by a paragraph a day."""
    hand_typed = "Spoke to the recruiter."
    first = merge_notes(hand_typed, f"{NOTE_MARKER} source, 2026-09-14\nfit 9/10 — apply")
    second = merge_notes(first, f"{NOTE_MARKER} source, 2026-09-15\nfit 8/10 — apply")

    assert second.count(NOTE_MARKER) == 1
    assert "2026-09-14" not in second
    assert hand_typed in second


def test_a_dry_run_writes_nothing(store: Storage) -> None:
    repo = BoardRepo(store)
    report = apply_to_board(repo, _shortlist(), dry_run=True)
    assert report.added == 1  # what it *would* do
    assert repo.all() == []


# -- invalid input -------------------------------------------------------------


def test_a_missing_file_says_where_it_looked(tmp_path: Path) -> None:
    with pytest.raises(FileNotFoundError, match="shortlist"):
        load_file(tmp_path / "nope.yaml")


def test_an_unknown_verdict_is_refused() -> None:
    with pytest.raises(ValidationError, match="verdict"):
        _shortlist(leads=[{"company": "A", "title": "T", "verdict": "probably"}])


def test_a_malformed_deadline_names_the_field() -> None:
    with pytest.raises(ValidationError, match="deadline"):
        _shortlist(
            leads=[{"company": "A", "title": "T", "verdict": "apply", "deadline": "Sept 20"}]
        )


def test_a_fit_score_outside_the_scale_is_refused() -> None:
    with pytest.raises(ValidationError, match="fit"):
        _shortlist(leads=[{"company": "A", "title": "T", "verdict": "apply", "fit": 98}])


def test_an_empty_shortlist_is_refused() -> None:
    with pytest.raises(ValidationError, match="leads"):
        _shortlist(leads=[])


def test_a_file_that_is_not_a_mapping_is_refused(tmp_path: Path) -> None:
    target = _write(tmp_path, ["just", "a", "list"])
    with pytest.raises(ValueError, match="mapping"):
        load_file(target)


def test_nothing_is_written_when_the_file_is_invalid(tmp_path: Path, store: Storage) -> None:
    """Validation happens before the board is touched, so a typo in lead nine
    does not leave leads one through eight half-imported."""
    repo = BoardRepo(store)
    target = _write(
        tmp_path,
        {
            "source": "s",
            "retrieved": "2026-09-15",
            "leads": [
                {"company": "Good", "title": "Fine role", "verdict": "apply"},
                {"company": "Bad", "title": "Broken role", "verdict": "nonsense"},
            ],
        },
    )
    with pytest.raises(ValidationError):
        load_file(target)
    assert repo.all() == []


def test_a_lead_with_a_location_does_not_match_a_row_without_one(store: Storage) -> None:
    """A known sharp edge, pinned rather than hidden.

    The board's de-duplication keys on company, title AND city (#28), so a row
    typed in by hand with no location is a different row from the same job
    imported with "Toronto, ON". This is the board's own notion of sameness and
    is not worth a second one here -- but it means a digest can land beside a
    hand-added row rather than on it. Give hand-added rows a location, or expect
    to merge two.
    """
    repo = BoardRepo(store)
    repo.add("RBC Borealis", "AI Business Analyst (Winter 2027, 8 months)")  # no location

    report = apply_to_board(repo, _shortlist())  # lead carries "Toronto, ON"

    assert report.added == 1
    assert len(repo.all()) == 2
