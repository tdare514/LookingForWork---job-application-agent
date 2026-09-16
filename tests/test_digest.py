"""The reading queue (#32).

#32 names its own failure mode -- *a digest that gets skipped is the whole phase
wasted* -- so the tests that matter here are about restraint: the caps hold, a
repost is never dressed up as new, and a move too small to act on is not
reported at all.
"""

from __future__ import annotations

from collections.abc import Callable
from datetime import date
from typing import Any

from jobagent.core.profile import Profile, Shortlist
from jobagent.tracking.digest import MOVEMENT_THRESHOLD, build, changed_components, since_cutoff
from jobagent.tracking.repo import Job

MakeJob = Callable[..., Job]
MakeProfile = Callable[..., Profile]
MakeScore = Callable[..., dict[str, Any]]

TODAY = date(2026, 9, 16)
YESTERDAY = "2026-09-15T09:00:00+00:00"
LAST_MONTH = "2026-08-10T09:00:00+00:00"


def record(total: float, **components: Any) -> dict[str, Any]:
    return {"total": total, "components": {"components": components}}


def test_a_new_row_above_the_threshold_is_reported(
    make_job: MakeJob, make_profile: MakeProfile, make_score: MakeScore
) -> None:
    jobs = [make_job(1, first_seen_at="2026-09-16T08:00:00+00:00")]
    result = build(jobs, {1: make_score(0.8)}, {}, {}, [], make_profile(), today=TODAY)
    assert [e.job.id for e in result.new] == [1]


def test_a_row_first_seen_before_the_cutoff_is_not_new(
    make_job: MakeJob, make_profile: MakeProfile, make_score: MakeScore
) -> None:
    jobs = [make_job(1, first_seen_at=LAST_MONTH)]
    result = build(jobs, {1: make_score(0.8)}, {}, {}, [], make_profile(), today=TODAY)
    assert result.new == []


def test_a_repost_is_never_presented_as_new(
    make_job: MakeJob, make_profile: MakeProfile, make_score: MakeScore
) -> None:
    """#32 asks for this by name: reposts are flagged, not counted as new."""
    jobs = [make_job(1, first_seen_at="2026-09-16T08:00:00+00:00")]
    result = build(jobs, {1: make_score(0.8)}, {1: 3}, {}, [], make_profile(), today=TODAY)
    assert result.new == []
    assert [e.job.id for e in result.reposts] == [1]
    assert result.reposts[0].sightings == 3


def test_the_new_section_is_capped_at_the_profile_entry_limit(
    make_job: MakeJob, make_profile: MakeProfile, make_score: MakeScore
) -> None:
    profile = make_profile(shortlist=Shortlist(min_score=0.1, max_entries=3))
    jobs = [make_job(i, first_seen_at="2026-09-16T08:00:00+00:00") for i in range(1, 11)]
    scores = {i: make_score(0.5) for i in range(1, 11)}
    result = build(jobs, scores, {}, {}, [], profile, today=TODAY)
    assert len(result.new) == 3
    assert result.scored_count == 10, "the cap trims what is shown, not what was scored"


# -- score movement -------------------------------------------------------


def test_a_moved_score_names_the_component_that_moved(
    make_job: MakeJob, make_profile: MakeProfile, make_score: MakeScore
) -> None:
    jobs = [make_job(1, first_seen_at=LAST_MONTH)]
    movement = {
        1: (
            record(0.40, skill_overlap={"value": 0.2}, seniority_fit={"value": 1.0}),
            record(0.75, skill_overlap={"value": 0.9}, seniority_fit={"value": 1.0}),
        )
    }
    result = build(jobs, {1: make_score(0.75)}, {}, movement, [], make_profile(), today=TODAY)
    assert len(result.moved) == 1
    moved = result.moved[0]
    assert moved.direction == "rose"
    assert moved.changed == ("skill_overlap",)
    assert "seniority_fit" not in moved.changed


def test_a_move_too_small_to_act_on_is_not_reported(
    make_job: MakeJob, make_profile: MakeProfile, make_score: MakeScore
) -> None:
    """Reporting a freshness decay of one day trains you to skip the section."""
    jobs = [make_job(1, first_seen_at=LAST_MONTH)]
    tiny = MOVEMENT_THRESHOLD / 2
    movement = {1: (record(0.50), record(0.50 + tiny))}
    result = build(jobs, {1: make_score(0.5)}, {}, movement, [], make_profile(), today=TODAY)
    assert result.moved == []


def test_a_fall_is_reported_as_a_fall(
    make_job: MakeJob, make_profile: MakeProfile, make_score: MakeScore
) -> None:
    jobs = [make_job(1, first_seen_at=LAST_MONTH)]
    movement = {1: (record(0.80), record(0.40))}
    result = build(jobs, {1: make_score(0.4)}, {}, movement, [], make_profile(), today=TODAY)
    assert result.moved[0].direction == "fell"
    assert result.moved[0].delta < 0


def test_a_rescale_with_no_component_change_says_so_rather_than_guessing(
    make_job: MakeJob, make_profile: MakeProfile, make_score: MakeScore
) -> None:
    """The total can move because a component appeared and the weights rescaled.

    Naming the biggest current component would imply it moved. It did not.
    """
    jobs = [make_job(1, first_seen_at=LAST_MONTH)]
    same = {"seniority_fit": {"value": 1.0}}
    movement = {1: (record(0.50, **same), record(0.70, **same))}
    result = build(jobs, {1: make_score(0.7)}, {}, movement, [], make_profile(), today=TODAY)
    assert result.moved[0].changed == ()


def test_movement_entirely_below_the_threshold_is_not_reported(
    make_job: MakeJob, make_profile: MakeProfile, make_score: MakeScore
) -> None:
    """A role that was never worth reading has not become news by wobbling."""
    profile = make_profile(shortlist=Shortlist(min_score=0.6))
    jobs = [make_job(1, first_seen_at=LAST_MONTH)]
    movement = {1: (record(0.10), record(0.30))}
    result = build(jobs, {1: make_score(0.3)}, {}, movement, [], profile, today=TODAY)
    assert result.moved == []


def test_a_role_that_fell_off_the_list_is_still_reported(
    make_job: MakeJob, make_profile: MakeProfile, make_score: MakeScore
) -> None:
    """The most actionable movement there is, and the easiest to hide.

    Found end to end: building this section only from rows currently above the
    threshold meant a role that dropped below it simply vanished from the digest
    with no explanation -- which is precisely the thing worth being told.
    """
    profile = make_profile(shortlist=Shortlist(min_score=0.35))
    jobs = [make_job(1, first_seen_at=LAST_MONTH)]
    movement = {1: (record(0.45), record(0.20))}
    result = build(jobs, {1: make_score(0.20)}, {}, movement, [], profile, today=TODAY)

    assert len(result.moved) == 1
    assert result.moved[0].dropped_off
    assert result.moved[0].direction == "fell"
    assert result.new == [], "and it is certainly not new"


def test_a_role_that_climbed_onto_the_list_is_reported(
    make_job: MakeJob, make_profile: MakeProfile, make_score: MakeScore
) -> None:
    profile = make_profile(shortlist=Shortlist(min_score=0.35))
    jobs = [make_job(1, first_seen_at=LAST_MONTH)]
    movement = {1: (record(0.20), record(0.60))}
    result = build(jobs, {1: make_score(0.60)}, {}, movement, [], profile, today=TODAY)

    assert len(result.moved) == 1
    assert not result.moved[0].dropped_off
    assert result.moved[0].direction == "rose"


def test_a_decided_row_reports_no_movement(
    make_job: MakeJob, make_profile: MakeProfile, make_score: MakeScore
) -> None:
    """Skipping a role stops it coming back, including through this section."""
    jobs = [make_job(1, first_seen_at=LAST_MONTH, state="skipped")]
    movement = {1: (record(0.80), record(0.20))}
    result = build(jobs, {1: make_score(0.20)}, {}, movement, [], make_profile(), today=TODAY)
    assert result.moved == []


# -- the filter aggregate -------------------------------------------------


def test_filtered_rows_are_aggregated_by_rule_not_listed(
    make_job: MakeJob, make_profile: MakeProfile
) -> None:
    """One line per rule is what makes an over-eager filter visible."""
    cut = [
        (make_job(9), "location: is in Calgary; the profile wants toronto"),
        (make_job(8), "location: is in Montreal; the profile wants toronto"),
        (make_job(7), "seniority: reads as director, 6 rungs off"),
    ]
    result = build([], {}, {}, {}, cut, make_profile(), today=TODAY)
    assert result.total_filtered == 3
    assert result.filtered == {"location": 2, "seniority": 1}
    assert list(result.filtered)[0] == "location", "most-cut rule first"


def test_a_reason_without_a_rule_prefix_is_counted_not_dropped(
    make_job: MakeJob, make_profile: MakeProfile
) -> None:
    cut = [(make_job(9), "no reason recorded")]
    result = build([], {}, {}, {}, cut, make_profile(), today=TODAY)
    assert result.filtered == {"unknown": 1}


# -- snooze ---------------------------------------------------------------


def test_a_snoozed_row_leaves_every_section(
    make_job: MakeJob, make_profile: MakeProfile, make_score: MakeScore
) -> None:
    jobs = [make_job(1, first_seen_at="2026-09-16T08:00:00+00:00", snoozed_until="2026-10-01")]
    movement = {1: (record(0.20), record(0.90))}
    result = build(jobs, {1: make_score(0.9)}, {1: 3}, movement, [], make_profile(), today=TODAY)
    assert result.new == []
    assert result.moved == []
    assert result.reposts == []
    assert result.is_empty


# -- "since when" ---------------------------------------------------------


def test_since_prefers_the_last_digest_run() -> None:
    when, label, source = since_cutoff({"occurred_at": "2026-09-14T07:30:00+00:00"}, 1, TODAY)
    assert when == date(2026, 9, 14)
    assert label == "2026-09-14"
    assert "last digest" in source


def test_since_falls_back_to_a_window_and_says_so() -> None:
    """A fresh install, or after `purge` clears the audit log.

    "New since yesterday" and "new since you last looked" are different claims.
    The digest must not make the stronger one by accident.
    """
    when, _label, source = since_cutoff(None, 3, TODAY)
    assert when == date(2026, 9, 13)
    assert "no previous digest" in source


def test_an_unparseable_run_timestamp_falls_back_rather_than_crashing() -> None:
    when, _label, source = since_cutoff({"occurred_at": "whenever"}, 1, TODAY)
    assert when == date(2026, 9, 15)
    assert "no previous digest" in source


# -- the serialized shape -------------------------------------------------


def test_the_json_shape_carries_every_section(
    make_job: MakeJob, make_profile: MakeProfile, make_score: MakeScore
) -> None:
    import json

    jobs = [make_job(1, first_seen_at="2026-09-16T08:00:00+00:00")]
    result = build(
        jobs,
        {1: make_score(0.8)},
        {},
        {},
        [(make_job(9), "location: elsewhere")],
        make_profile(),
        today=TODAY,
    )
    payload = json.loads(json.dumps(result.as_dict()))
    assert set(payload) >= {"since", "since_source", "new", "moved", "reposts", "filtered"}
    assert payload["filtered"] == {"total": 1, "by_rule": {"location": 1}}
    assert payload["new"][0]["company"] == "RBC"


def test_changed_components_tolerates_a_malformed_stored_decomposition() -> None:
    assert changed_components({"components": "not a dict"}, {"components": {}}) == ()
