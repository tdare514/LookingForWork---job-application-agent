"""The ranked list and its filters (#32).

The rule under test throughout: an unset filter passes everything. A shortlist
that quietly narrows to nothing is indistinguishable from a week with no good
jobs in it, which is the same failure the hard filters in #31 are written
around.
"""

from __future__ import annotations

from collections.abc import Callable
from datetime import date
from typing import Any

from jobagent.core.profile import Profile, Shortlist
from jobagent.tracking.repo import Job
from jobagent.tracking.shortlist import Filters, build

# Builders come from conftest so `test_digest` can share them without importing
# this module, which would give the file two module names and break mypy.
MakeJob = Callable[..., Job]
MakeProfile = Callable[..., Profile]
MakeScore = Callable[..., dict[str, Any]]

TODAY = date(2026, 9, 16)


def test_ranks_best_first(
    make_job: MakeJob, make_profile: MakeProfile, make_score: MakeScore
) -> None:
    jobs = [make_job(1), make_job(2), make_job(3)]
    scores = {1: make_score(0.4), 2: make_score(0.9), 3: make_score(0.6)}
    entries = build(jobs, scores, {}, make_profile(), Filters(), TODAY)
    assert [e.job.id for e in entries] == [2, 3, 1]


def test_the_nearer_deadline_breaks_a_tie(
    make_job: MakeJob, make_profile: MakeProfile, make_score: MakeScore
) -> None:
    """Between two equal matches, the one closing Friday is tonight's reading."""
    jobs = [make_job(1, deadline="2026-10-30"), make_job(2, deadline="2026-09-20")]
    scores = {1: make_score(0.7), 2: make_score(0.7)}
    entries = build(jobs, scores, {}, make_profile(), Filters(), TODAY)
    assert [e.job.id for e in entries] == [2, 1]


def test_the_profile_threshold_applies_when_no_flag_is_given(
    make_job: MakeJob, make_profile: MakeProfile, make_score: MakeScore
) -> None:
    profile = make_profile(shortlist=Shortlist(min_score=0.5))
    jobs = [make_job(1), make_job(2)]
    scores = {1: make_score(0.45), 2: make_score(0.55)}
    entries = build(jobs, scores, {}, profile, Filters(), TODAY)
    assert [e.job.id for e in entries] == [2]


def test_an_explicit_threshold_overrides_the_profile(
    make_job: MakeJob, make_profile: MakeProfile, make_score: MakeScore
) -> None:
    profile = make_profile(shortlist=Shortlist(min_score=0.9))
    jobs = [make_job(1)]
    scores = {1: make_score(0.45)}
    assert build(jobs, scores, {}, profile, Filters(min_score=0.2), TODAY)


def test_filtered_rows_are_absent(
    make_job: MakeJob, make_profile: MakeProfile, make_score: MakeScore
) -> None:
    """A cut row was already judged; `score --filtered` is where it lives."""
    jobs = [make_job(1), make_job(2)]
    scores = {1: make_score(0.9, filtered=True), 2: make_score(0.5)}
    entries = build(jobs, scores, {}, make_profile(), Filters(), TODAY)
    assert [e.job.id for e in entries] == [2]


def test_an_unscored_row_is_absent_rather_than_guessed_at(
    make_job: MakeJob, make_profile: MakeProfile, make_score: MakeScore
) -> None:
    jobs = [make_job(1), make_job(2)]
    entries = build(jobs, {2: make_score(0.5)}, {}, make_profile(), Filters(), TODAY)
    assert [e.job.id for e in entries] == [2]


# -- filters --------------------------------------------------------------


def test_an_empty_filter_set_passes_everything_above_the_threshold(
    make_job: MakeJob, make_profile: MakeProfile, make_score: MakeScore
) -> None:
    jobs = [make_job(1, "RBC"), make_job(2, "BMO"), make_job(3, "TD")]
    scores = {i: make_score(0.6) for i in (1, 2, 3)}
    assert len(build(jobs, scores, {}, make_profile(), Filters(), TODAY)) == 3


def test_company_matches_what_you_can_see_not_the_normalized_key(
    make_job: MakeJob, make_profile: MakeProfile, make_score: MakeScore
) -> None:
    """`--company montreal` must find "Bank of Montreal", which normalizes to "bmo"."""
    jobs = [make_job(1, "Bank of Montreal"), make_job(2, "RBC")]
    scores = {1: make_score(0.6), 2: make_score(0.6)}
    entries = build(jobs, scores, {}, make_profile(), Filters(company="montreal"), TODAY)
    assert [e.job.id for e in entries] == [1]


def test_source_filters_on_where_the_row_was_seen(
    make_job: MakeJob, make_profile: MakeProfile, make_score: MakeScore
) -> None:
    jobs = [make_job(1), make_job(2)]
    scores = {1: make_score(0.6), 2: make_score(0.6)}
    sources = {1: {"workday:rbc"}, 2: {"greenhouse:acme"}}
    entries = build(
        jobs, scores, {}, make_profile(), Filters(source="workday"), TODAY, sources=sources
    )
    assert [e.job.id for e in entries] == [1]


def test_since_days_keeps_only_recently_seen_rows(
    make_job: MakeJob, make_profile: MakeProfile, make_score: MakeScore
) -> None:
    jobs = [
        make_job(1, first_seen_at="2026-09-15T08:00:00+00:00"),
        make_job(2, first_seen_at="2026-08-01T08:00:00+00:00"),
    ]
    scores = {1: make_score(0.6), 2: make_score(0.6)}
    entries = build(jobs, scores, {}, make_profile(), Filters(since_days=7), TODAY)
    assert [e.job.id for e in entries] == [1]


def test_an_unparseable_first_seen_is_kept_rather_than_dropped(
    make_job: MakeJob, make_profile: MakeProfile, make_score: MakeScore
) -> None:
    """A bad timestamp is our bug, and must not silently shorten the user's list."""
    jobs = [make_job(1, first_seen_at="not a date")]
    entries = build(jobs, {1: make_score(0.6)}, {}, make_profile(), Filters(since_days=1), TODAY)
    assert len(entries) == 1


# -- snooze ---------------------------------------------------------------


def test_a_snoozed_row_is_hidden_until_the_date_passes(
    make_job: MakeJob, make_profile: MakeProfile, make_score: MakeScore
) -> None:
    jobs = [make_job(1, snoozed_until="2026-09-20")]
    scores = {1: make_score(0.9)}
    assert build(jobs, scores, {}, make_profile(), Filters(), TODAY) == []


def test_a_snoozed_row_returns_on_its_own(
    make_job: MakeJob, make_profile: MakeProfile, make_score: MakeScore
) -> None:
    """Snooze is not a state, so nothing has to be undone by hand."""
    jobs = [make_job(1, snoozed_until="2026-09-16")]
    entries = build(jobs, {1: make_score(0.9)}, {}, make_profile(), Filters(), date(2026, 9, 17))
    assert [e.job.id for e in entries] == [1]


def test_snoozed_rows_can_be_asked_for_explicitly(
    make_job: MakeJob, make_profile: MakeProfile, make_score: MakeScore
) -> None:
    jobs = [make_job(1, snoozed_until="2026-12-01")]
    entries = build(
        jobs, {1: make_score(0.9)}, {}, make_profile(), Filters(include_snoozed=True), TODAY
    )
    assert len(entries) == 1


# -- reposts --------------------------------------------------------------


def test_a_repost_carries_its_sighting_count(
    make_job: MakeJob, make_profile: MakeProfile, make_score: MakeScore
) -> None:
    entries = build([make_job(1)], {1: make_score(0.6)}, {1: 4}, make_profile(), Filters(), TODAY)
    assert entries[0].is_repost
    assert entries[0].sightings == 4


def test_a_row_seen_once_is_not_a_repost(
    make_job: MakeJob, make_profile: MakeProfile, make_score: MakeScore
) -> None:
    entries = build([make_job(1)], {1: make_score(0.6)}, {1: 1}, make_profile(), Filters(), TODAY)
    assert not entries[0].is_repost


def test_an_entry_carries_the_evidence_its_rank_rests_on(
    make_job: MakeJob, make_profile: MakeProfile, make_score: MakeScore
) -> None:
    entries = build([make_job(1)], {1: make_score(0.6)}, {}, make_profile(), Filters(), TODAY)
    payload = entries[0].as_dict()
    assert payload["score"] == 0.6
    assert payload["scored_on"] == ["seniority_fit", "domain_relevance"]


# -- decisions already made -----------------------------------------------


def test_a_skipped_row_does_not_come_back(
    make_job: MakeJob, make_profile: MakeProfile, make_score: MakeScore
) -> None:
    """Skipping has to actually stop it returning, or the queue stops being one.

    Found end to end: `jobagent skip` set the state and the row kept appearing
    on the next shortlist, because `repo.all()` includes closed rows.
    """
    jobs = [make_job(1, state="skipped"), make_job(2, state="new")]
    scores = {1: make_score(0.9), 2: make_score(0.5)}
    entries = build(jobs, scores, {}, make_profile(), Filters(), TODAY)
    assert [e.job.id for e in entries] == [2]


def test_a_row_already_applied_to_is_not_a_reading_queue_entry(
    make_job: MakeJob, make_profile: MakeProfile, make_score: MakeScore
) -> None:
    jobs = [make_job(i, state=s) for i, s in enumerate(("applied", "waiting", "interview"), 1)]
    scores = {i: make_score(0.9) for i in (1, 2, 3)}
    assert build(jobs, scores, {}, make_profile(), Filters(), TODAY) == []


def test_a_triaged_row_is_still_on_the_list(
    make_job: MakeJob, make_profile: MakeProfile, make_score: MakeScore
) -> None:
    """`ready` means "needs me", which is exactly what a reading queue is for."""
    jobs = [make_job(1, state="ready")]
    assert len(build(jobs, {1: make_score(0.9)}, {}, make_profile(), Filters(), TODAY)) == 1


def test_decided_rows_can_be_asked_for_explicitly(
    make_job: MakeJob, make_profile: MakeProfile, make_score: MakeScore
) -> None:
    jobs = [make_job(1, state="skipped")]
    entries = build(
        jobs, {1: make_score(0.9)}, {}, make_profile(), Filters(include_decided=True), TODAY
    )
    assert len(entries) == 1


def test_an_unrecognised_state_stays_visible_rather_than_vanishing(
    make_job: MakeJob, make_profile: MakeProfile, make_score: MakeScore
) -> None:
    """Hiding a row on a state we cannot read would be guessing at a decision."""
    jobs = [make_job(1, state="something-new")]
    assert len(build(jobs, {1: make_score(0.9)}, {}, make_profile(), Filters(), TODAY)) == 1
