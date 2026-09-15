"""Funnel analytics.

The risk with a report is not that it crashes -- it is that it says something
confident and wrong off four data points. Most of these tests are about honesty
at small sample sizes.
"""

from __future__ import annotations

import itertools
from datetime import UTC, datetime, timedelta

from jobagent.core.storage import Storage
from jobagent.tracking.board import State
from jobagent.tracking.followups import STALE_AFTER_DAYS, due
from jobagent.tracking.funnel import SMALL_SAMPLE, build
from jobagent.tracking.repo import BoardRepo

_SEQ = itertools.count()


def _add(store: Storage, company: str, state: State, days_ago: int = 0) -> int:
    """Distinct titles on purpose: the board de-duplicates identical rows, so a
    fixture reusing one title would silently build a single job."""
    repo = BoardRepo(store)
    job, _ = repo.add(company, f"Analyst {next(_SEQ)} at {company}")
    repo.set_state(job.id, state)
    if days_ago:
        stamp = (datetime.now(UTC) - timedelta(days=days_ago)).isoformat(timespec="seconds")
        with store.transaction() as conn:
            conn.execute("UPDATE jobs SET state_changed_at = ? WHERE id = ?", (stamp, job.id))
    return job.id


# -- running on nothing -------------------------------------------------------


def test_an_empty_board_reports_rather_than_crashes(store: Storage) -> None:
    """This gets run in week one, when nothing has an outcome."""
    report = build(BoardRepo(store).all())
    assert report.total == 0
    assert report.has_outcomes is False
    assert all(s.reached == 0 for s in report.stages)
    assert all(s.conversion is None for s in report.stages)


def test_a_board_with_no_applications_has_no_outcomes(store: Storage) -> None:
    _add(store, "BMO", State.READY)
    _add(store, "RBC", State.NEW)
    report = build(BoardRepo(store).all())
    assert report.has_outcomes is False


# -- honesty about sample size ------------------------------------------------


def test_small_samples_are_flagged(store: Storage) -> None:
    """ "50% interview rate" off two applications is noise wearing a suit."""
    _add(store, "BMO", State.APPLIED)
    _add(store, "RBC", State.INTERVIEW)
    report = build(BoardRepo(store).all())
    assert report.thin_overall is True
    assert all(s.thin for s in report.stages if s.conversion is not None)


def test_a_large_enough_sample_is_not_flagged(store: Storage) -> None:
    for i in range(SMALL_SAMPLE + 2):
        _add(store, f"Company {i}", State.APPLIED)
    report = build(BoardRepo(store).all())
    assert report.thin_overall is False


def test_a_zero_denominator_yields_no_rate_not_zero_percent(store: Storage) -> None:
    """No one reached the previous stage, so the rate is undefined, not 0%."""
    _add(store, "BMO", State.NEW)
    report = build(BoardRepo(store).all())
    for stage in report.stages:
        if stage.previous_total == 0:
            assert stage.conversion is None


# -- the funnel actually funnels ----------------------------------------------


def test_reaching_a_late_stage_counts_toward_the_earlier_ones(store: Storage) -> None:
    """Someone interviewing obviously also applied. Otherwise rates are nonsense."""
    _add(store, "RBC", State.INTERVIEW)
    report = build(BoardRepo(store).all())
    reached = {s.state: s.reached for s in report.stages}
    assert reached[State.APPLIED] == 1
    assert reached[State.INTERVIEW] == 1
    assert reached[State.OFFER] == 0


def test_rejections_are_counted_separately_not_folded_into_the_funnel(
    store: Storage,
) -> None:
    """A rejection is an outcome, not a stage. Counting it as 'reached' would
    quietly inflate every conversion rate above it."""
    _add(store, "TD", State.REJECTED)
    _add(store, "BMO", State.APPLIED)
    report = build(BoardRepo(store).all())
    reached = {s.state: s.reached for s in report.stages}
    assert report.rejected == 1
    assert reached[State.APPLIED] == 1, "the rejected row must not count as applied"


def test_conversion_is_computed_against_the_previous_stage(store: Storage) -> None:
    for _ in range(4):
        _add(store, "A", State.APPLIED)
    _add(store, "B", State.INTERVIEW)
    report = build(BoardRepo(store).all())
    stages = {s.state: s for s in report.stages}
    assert stages[State.APPLIED].reached == 5
    assert stages[State.INTERVIEW].reached == 1
    assert stages[State.INTERVIEW].conversion == 1 / 5


# -- cuts and time ------------------------------------------------------------


def test_companies_are_ranked_by_applications_not_by_rows_tracked(
    store: Storage,
) -> None:
    """Which source produced applications matters; which produced clutter does not."""
    for _ in range(5):
        _add(store, "Noisy", State.NEW)  # five tracked, none applied
    _add(store, "Productive", State.APPLIED)
    report = build(BoardRepo(store).all())
    assert report.by_company[0][0] == "Productive"


def test_stale_rows_are_counted(store: Storage) -> None:
    _add(store, "Old", State.APPLIED, days_ago=45)
    _add(store, "Fresh", State.APPLIED, days_ago=1)
    report = build(BoardRepo(store).all())
    assert report.stale == 1


def test_the_report_and_the_board_agree_on_stale(store: Storage) -> None:
    """One threshold, not two.

    The report used to carry its own literal 30. Nothing failed when they
    matched, and nothing would have failed on the day they stopped: the board
    would nag about a row the report called fresh, and the only symptom is a
    number quietly disagreeing with the screen next to it.
    """
    _add(store, "Just stale", State.APPLIED, days_ago=STALE_AFTER_DAYS)
    _add(store, "Just fresh", State.APPLIED, days_ago=STALE_AFTER_DAYS - 1)
    jobs = BoardRepo(store).all()

    assert build(jobs).stale == 1
    assert [f.job.company for f in due(jobs) if f.stale] == ["Just stale"]


def test_median_time_in_state_is_reported(store: Storage) -> None:
    _add(store, "A", State.APPLIED, days_ago=2)
    _add(store, "B", State.APPLIED, days_ago=10)
    _add(store, "C", State.APPLIED, days_ago=30)
    report = build(BoardRepo(store).all())
    assert report.median_days_in_state == 10


def test_a_row_with_no_timestamp_does_not_break_the_report(store: Storage) -> None:
    job_id = _add(store, "Odd", State.APPLIED)
    with store.transaction() as conn:
        conn.execute("UPDATE jobs SET state_changed_at = NULL WHERE id = ?", (job_id,))
    report = build(BoardRepo(store).all())
    assert report.total == 1


def test_waiting_counts_as_applied_not_as_its_own_stage(store: Storage) -> None:
    """ "Waiting" means applied with no reply yet -- a sub-state, not progress.

    Treating it as a stage would put a near-empty denominator under the
    interview rate and distort everything above it.
    """
    from jobagent.tracking.funnel import FUNNEL_ORDER

    assert State.WAITING not in FUNNEL_ORDER

    _add(store, "A", State.WAITING)
    _add(store, "B", State.APPLIED)
    report = build(BoardRepo(store).all())
    reached = {s.state: s.reached for s in report.stages}
    assert reached[State.APPLIED] == 2


def test_untriaged_rows_are_reported_so_the_funnel_top_reconciles(
    store: Storage,
) -> None:
    """Without this the funnel's first stage reads lower than the tracked total
    with no explanation, which looks like a bug in the report."""
    _add(store, "A", State.NEW)
    _add(store, "B", State.NEW)
    _add(store, "C", State.READY)
    report = build(BoardRepo(store).all())
    assert report.total == 3
    assert report.untriaged == 2
    assert report.stages[0].reached == 1
