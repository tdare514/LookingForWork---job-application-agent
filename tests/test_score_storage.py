"""Storing scores and filter reasons (#31).

The acceptance criterion that matters here is "filtered jobs are queryable with
their reason". A cut that is not recorded is a job that vanished, and a board
that quietly shrinks is the failure mode this whole feature is written around.
"""

from __future__ import annotations

import json

from jobagent.core import pii
from jobagent.core.storage import Storage
from jobagent.matching.filters import Verdict
from jobagent.matching.score import Component, Score
from jobagent.tracking.repo import BoardRepo


def a_score(total: float = 0.75) -> Score:
    return Score(
        total=total,
        components=(
            Component("skill_overlap", 0.8, 0.4, "4/5 required matched by the profile"),
            Component("freshness", None, 0.13, "the posting does not publish a date"),
        ),
    )


def test_a_score_round_trips_with_its_decomposition(store: Storage) -> None:
    repo = BoardRepo(store)
    job, _ = repo.add(company="RBC", title="Risk Analyst Intern")

    repo.save_score(job.id, a_score(0.62), Verdict(passed=True))

    record = repo.latest_scores()[job.id]
    assert record["total"] == 0.62
    assert not record["filtered"]
    assert record["components"]["components"]["skill_overlap"]["value"] == 0.8
    assert record["components"]["components"]["freshness"]["value"] is None


def test_a_filtered_job_is_queryable_with_its_reason(store: Storage) -> None:
    repo = BoardRepo(store)
    kept, _ = repo.add(company="RBC", title="Risk Analyst Intern")
    cut, _ = repo.add(company="BMO", title="Director, Strategy")

    repo.save_score(kept.id, a_score(), Verdict(passed=True))
    repo.save_score(
        cut.id,
        a_score(),
        Verdict(passed=False, rule="seniority", reason="reads as director, 5 rungs off"),
    )

    filtered = repo.filtered_jobs()
    assert [job.company for job, _ in filtered] == ["BMO"]
    reason = filtered[0][1]
    assert "seniority" in reason and "director" in reason


def test_a_filtered_job_scores_zero_rather_than_keeping_its_number(store: Storage) -> None:
    """A cut job must not sit in the ranking on a score it was never eligible for."""
    repo = BoardRepo(store)
    job, _ = repo.add(company="BMO", title="Director, Strategy")
    repo.save_score(
        job.id, a_score(0.9), Verdict(passed=False, rule="seniority", reason="too senior")
    )
    assert repo.latest_scores()[job.id]["total"] == 0.0


def test_scores_are_appended_so_movement_stays_visible(store: Storage) -> None:
    """Re-scoring keeps the old row. #32 needs the history to say a score moved."""
    repo = BoardRepo(store)
    job, _ = repo.add(company="RBC", title="Risk Analyst Intern")

    repo.save_score(job.id, a_score(0.40), Verdict(passed=True))
    repo.save_score(job.id, a_score(0.65), Verdict(passed=True))

    assert store.count("scores") == 2
    assert repo.latest_scores()[job.id]["total"] == 0.65


def test_scoring_rows_carry_what_the_filters_need(store: Storage) -> None:
    repo = BoardRepo(store)
    repo.add(
        company="TD",
        title="Quantitative Analyst",
        location="Toronto, Ontario",
        description="Requires SQL and Python.",
    )
    rows = repo.scoring_rows()
    assert len(rows) == 1
    _, listing, _posted_at = rows[0]
    assert listing.company == "TD"
    assert listing.location == "Toronto, Ontario"
    assert listing.description is not None


def test_the_score_columns_are_in_the_pii_registry(store: Storage) -> None:
    """`purge` walks the registry, so an unregistered column is one it does not clear.

    The decomposition and the filter reason both restate declared intent against
    a named employer -- which companies were considered, and how closely each
    matched. That is the shortlist, per row.
    """
    registered = pii.registered_columns()
    assert ("scores", "components") in registered
    assert ("scores", "filter_reason") in registered
    for table, column in (("scores", "components"), ("scores", "filter_reason")):
        assert column in store.columns(table)


# -- skip reasons and snooze (#32) ----------------------------------------


def test_a_skip_reason_round_trips(store: Storage) -> None:
    """Three weeks on, a skip with no reason is indistinguishable from one to reverse."""
    from jobagent.tracking.board import State

    repo = BoardRepo(store)
    job, _ = repo.add(company="TD", title="Contact Centre Rep")
    repo.set_state(job.id, State.SKIPPED, reason="not an analytical role")

    refreshed = repo.get(job.id)
    assert refreshed is not None
    assert refreshed.state == State.SKIPPED
    assert refreshed.state_reason == "not an analytical role"


def test_a_state_change_without_a_reason_does_not_erase_one(store: Storage) -> None:
    """The board's `s` key passes no reason and must not wipe one typed at the CLI."""
    from jobagent.tracking.board import State

    repo = BoardRepo(store)
    job, _ = repo.add(company="TD", title="Contact Centre Rep")
    repo.set_state(job.id, State.SKIPPED, reason="not analytical")
    repo.set_state(job.id, State.READY)

    refreshed = repo.get(job.id)
    assert refreshed is not None
    assert refreshed.state_reason == "not analytical"


def test_the_audit_entry_does_not_carry_the_reason_text(store: Storage) -> None:
    """The reason names a company and a judgement about it.

    `audit_log.detail` is CRITICAL, but it is also the field most likely to be
    pasted into a terminal while debugging. It records *that* a reason was
    given, not what it said.
    """
    from jobagent.tracking.board import State

    repo = BoardRepo(store)
    job, _ = repo.add(company="TD", title="Contact Centre Rep")
    repo.set_state(job.id, State.SKIPPED, reason="the hiring manager was rude")

    entry = store.last_audit("job.state")
    assert entry is not None
    assert entry["detail"]["reason_given"] is True
    assert "rude" not in json.dumps(entry["detail"])


def test_snooze_hides_a_row_until_the_date_passes(store: Storage) -> None:
    from datetime import date

    repo = BoardRepo(store)
    job, _ = repo.add(company="RBC", title="Risk Analyst Intern")
    repo.snooze(job.id, date(2026, 9, 20))

    refreshed = repo.get(job.id)
    assert refreshed is not None
    assert refreshed.snoozed_until == "2026-09-20"
    assert refreshed.is_snoozed(date(2026, 9, 16))
    assert not refreshed.is_snoozed(date(2026, 9, 21))
    assert refreshed.state == "new", "snooze is not a state and changes none"


def test_unsnooze_clears_it(store: Storage) -> None:
    from datetime import date

    repo = BoardRepo(store)
    job, _ = repo.add(company="RBC", title="Risk Analyst Intern")
    repo.snooze(job.id, date(2026, 12, 1))
    repo.unsnooze(job.id)

    refreshed = repo.get(job.id)
    assert refreshed is not None
    assert refreshed.snoozed_until is None


def test_score_movement_needs_two_readings(store: Storage) -> None:
    """A first score is not a rise from zero -- that would report the install date."""
    repo = BoardRepo(store)
    job, _ = repo.add(company="RBC", title="Risk Analyst Intern")

    repo.save_score(job.id, a_score(0.40), Verdict(passed=True))
    assert repo.score_movement() == {}

    repo.save_score(job.id, a_score(0.75), Verdict(passed=True))
    movement = repo.score_movement()
    previous, latest = movement[job.id]
    assert previous["total"] == 0.40
    assert latest["total"] == 0.75
    assert "components" in latest, "the decomposition comes too, or 'why' is unanswerable"


def test_score_movement_ignores_filtered_readings(store: Storage) -> None:
    repo = BoardRepo(store)
    job, _ = repo.add(company="BMO", title="Director, Strategy")
    repo.save_score(job.id, a_score(0.4), Verdict(passed=False, rule="seniority", reason="x"))
    repo.save_score(job.id, a_score(0.9), Verdict(passed=False, rule="seniority", reason="x"))
    assert repo.score_movement() == {}


def test_last_audit_finds_the_newest_entry_for_one_action(store: Storage) -> None:
    store.append_audit("digest", {"new": 1})
    store.append_audit("score", {"jobs": 5})
    store.append_audit("digest", {"new": 9})

    entry = store.last_audit("digest")
    assert entry is not None
    assert entry["detail"]["new"] == 9
    assert store.last_audit("never-ran") is None
