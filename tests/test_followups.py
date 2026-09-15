"""Follow-up rules. Boundaries matter: off-by-one here means nagging or silence."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from jobagent.core.storage import Storage
from jobagent.tracking.board import State
from jobagent.tracking.followups import STALE_AFTER_DAYS, due
from jobagent.tracking.repo import BoardRepo


def _job_aged(store: Storage, company: str, state: State, days: int) -> int:
    repo = BoardRepo(store)
    job, _ = repo.add(company, "Analyst")
    repo.set_state(job.id, state)
    stamp = (datetime.now(UTC) - timedelta(days=days)).isoformat(timespec="seconds")
    with store.transaction() as conn:
        conn.execute("UPDATE jobs SET state_changed_at = ? WHERE id = ?", (stamp, job.id))
    return job.id


def test_applied_with_no_acknowledgement_fires_at_ten_days(store: Storage) -> None:
    _job_aged(store, "BMO", State.APPLIED, 10)
    followups = due(BoardRepo(store).all())
    assert len(followups) == 1
    assert "no acknowledgement" in followups[0].reason


def test_it_does_not_fire_a_day_early(store: Storage) -> None:
    """Nagging a recruiter on day nine is worse than waiting."""
    _job_aged(store, "BMO", State.APPLIED, 9)
    assert due(BoardRepo(store).all()) == []


def test_post_interview_fires_sooner(store: Storage) -> None:
    _job_aged(store, "RBC", State.INTERVIEW, 5)
    followups = due(BoardRepo(store).all())
    assert len(followups) == 1
    assert "interview" in followups[0].reason.lower()


def test_a_rejection_is_never_chased(store: Storage) -> None:
    _job_aged(store, "TD", State.REJECTED, 60)
    assert due(BoardRepo(store).all()) == []


def test_an_offer_is_not_a_follow_up(store: Storage) -> None:
    _job_aged(store, "TD", State.OFFER, 60)
    assert due(BoardRepo(store).all()) == []


def test_anything_untouched_for_a_month_is_stale(store: Storage) -> None:
    """Most applications end in silence. Stale must be detected, not guessed."""
    _job_aged(store, "Scotiabank", State.READY, STALE_AFTER_DAYS)
    followups = due(BoardRepo(store).all())
    assert len(followups) == 1
    assert followups[0].stale is True


def test_most_overdue_comes_first(store: Storage) -> None:
    _job_aged(store, "Recent", State.APPLIED, 11)
    _job_aged(store, "Ancient", State.APPLIED, 25)
    followups = due(BoardRepo(store).all())
    assert [f.job.company for f in followups] == ["Ancient", "Recent"]


def test_a_row_with_no_timestamp_is_skipped_not_crashed(store: Storage) -> None:
    repo = BoardRepo(store)
    job, _ = repo.add("Odd", "Analyst")
    with store.transaction() as conn:
        conn.execute("UPDATE jobs SET state_changed_at = NULL WHERE id = ?", (job.id,))
    assert due(repo.all()) == []


@pytest.mark.parametrize("days", [0, 1, 5])
def test_a_fresh_application_is_left_alone(store: Storage, days: int) -> None:
    _job_aged(store, "Fresh", State.APPLIED, days)
    assert due(BoardRepo(store).all()) == []
