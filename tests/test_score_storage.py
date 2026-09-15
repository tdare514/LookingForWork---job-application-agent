"""Storing scores and filter reasons (#31).

The acceptance criterion that matters here is "filtered jobs are queryable with
their reason". A cut that is not recorded is a job that vanished, and a board
that quietly shrinks is the failure mode this whole feature is written around.
"""

from __future__ import annotations

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
