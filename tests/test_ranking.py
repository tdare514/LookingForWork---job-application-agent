"""The ranking regression set (#31).

Unit tests prove each component computes what it says. They cannot tell you that
the whole pipeline puts the right jobs at the top, because every one of them
agrees with whatever the code currently does.

This does the other job: twelve real postings from live RBC, BMO and TD tenants,
hand-labelled in `fixtures/ranking_labels.json`, asserting the relationships a
tuning change must not break. A weight nudged, a skill added to the vocabulary,
a filter loosened -- any of those can look like an improvement in isolation and
still flip a clear case. This is what notices.

What is deliberately NOT asserted is any absolute score. Pinning "the credit
risk intern scores 0.53" would fail on every honest change to the weights and
teach whoever is on call to update the number rather than read it.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from jobagent.core.profile import Profile, WorkAuthorization
from jobagent.core.vocabulary import Seniority
from jobagent.matching.extract import extract
from jobagent.matching.filters import Listing, apply_filters
from jobagent.matching.score import score

FIXTURES = Path(__file__).parent / "fixtures"


def build_profile() -> Profile:
    """The search the labels were judged against.

    A Winter 2027 co-op search out of Toronto. Changing this invalidates every
    label in `ranking_labels.json`; the README in that file says so too.
    """
    return Profile(
        target_titles=["Risk Analyst", "Data Analyst", "Quantitative Analyst"],
        target_seniority=[Seniority.INTERN, Seniority.JUNIOR],
        locations=["Toronto"],
        work_arrangements=["onsite", "hybrid"],
        must_have_skills=["python", "sql", "excel"],
        nice_to_have_skills=["r", "sas", "tableau", "statistics", "risk management"],
        work_authorization=WorkAuthorization(authorized_in=["CA"], needs_sponsorship=False),
    )


def load_postings() -> dict[str, dict[str, Any]]:
    raw = json.loads((FIXTURES / "postings.json").read_text())
    return {posting["source_id"]: posting for posting in raw}


def load_labels() -> dict[str, dict[str, str]]:
    raw = json.loads((FIXTURES / "ranking_labels.json").read_text())
    labels: dict[str, dict[str, str]] = raw["postings"]
    return labels


def evaluate(source_id: str) -> tuple[Any, float]:
    """Run one posting through the real pipeline: extract, filter, score."""
    posting = load_postings()[source_id]
    listing = Listing(
        company=posting["company"],
        title=posting["title"],
        location=posting.get("location"),
        work_arrangement=posting.get("work_arrangement"),
        description=posting.get("description"),
    )
    requirements = extract(posting.get("description"))
    profile = build_profile()
    verdict = apply_filters(listing, requirements, profile)
    result = score(listing, requirements, profile, posting.get("posted_at"))
    return verdict, result.total


def labelled(kind: str) -> list[str]:
    return [sid for sid, label in load_labels().items() if label.get("label") == kind]


def filtered_labels() -> list[tuple[str, str]]:
    return [
        (sid, label["filtered_by"])
        for sid, label in load_labels().items()
        if "filtered_by" in label
    ]


# -- the corpus itself ----------------------------------------------------


@pytest.mark.parametrize("kind", ["pursue", "borderline", "skip"])
def test_every_scored_tier_has_a_real_posting(kind: str) -> None:
    """An empty verdict tier removes coverage, so fail rather than skip."""
    assert labelled(kind), (
        f"the ranking corpus needs at least one {kind} posting; "
        "read the posting text to label it, not the scorer's output"
    )


def test_every_posting_carries_a_label() -> None:
    """An unlabelled posting is silently excluded from every assertion below."""
    unlabelled = set(load_postings()) - set(load_labels())
    assert not unlabelled, f"postings with no ranking label: {sorted(unlabelled)}"


def test_every_label_explains_itself() -> None:
    for source_id, label in load_labels().items():
        assert label.get("why", "").strip(), f"{source_id} has no stated reason"
        assert ("label" in label) ^ ("filtered_by" in label), (
            f"{source_id} must be either scored (label) or cut (filtered_by), not both"
        )


# -- the hard filters -----------------------------------------------------


@pytest.mark.parametrize(("source_id", "expected_rule"), filtered_labels())
def test_a_row_expected_to_be_cut_is_cut_by_the_named_rule(
    source_id: str, expected_rule: str
) -> None:
    """The rule name is asserted, not just the cut.

    If seniority starts swallowing rows that location used to cut, the board
    ends up the same size and nothing looks wrong -- but the filter doing the
    work has changed, and that is worth being told about.
    """
    verdict, _ = evaluate(source_id)
    assert not verdict.passed, f"{source_id} was expected to be cut by {expected_rule}"
    assert verdict.rule == expected_rule, (
        f"{source_id} was cut by {verdict.rule}, expected {expected_rule}: {verdict.reason}"
    )


@pytest.mark.parametrize(
    "source_id", labelled("pursue") + labelled("skip") + labelled("borderline")
)
def test_a_row_expected_to_be_scored_survives_the_filters(source_id: str) -> None:
    """The half that catches an over-eager filter.

    A filter quietly widening its reach shows up here as a labelled job
    vanishing, which is the failure that otherwise looks like a quiet week.
    """
    verdict, _ = evaluate(source_id)
    assert verdict.passed, f"{source_id} was cut by {verdict.rule}: {verdict.reason}"


def test_the_filters_do_not_empty_the_board() -> None:
    survivors = [sid for sid in load_postings() if evaluate(sid)[0].passed]
    assert survivors, "every posting was filtered out -- a rule is far too aggressive"


# -- the ranking ----------------------------------------------------------


def test_every_clear_pursue_outranks_every_clear_skip() -> None:
    """The relationship the whole pipeline exists to get right."""
    pursue = {sid: evaluate(sid)[1] for sid in labelled("pursue")}
    skip = {sid: evaluate(sid)[1] for sid in labelled("skip")}
    assert pursue and skip, "the corpus needs at least one of each to mean anything"

    worst_pursue = min(pursue, key=lambda sid: pursue[sid])
    best_skip = max(skip, key=lambda sid: skip[sid])
    assert pursue[worst_pursue] > skip[best_skip], (
        f"{worst_pursue} ({pursue[worst_pursue]:.3f}) should outrank "
        f"{best_skip} ({skip[best_skip]:.3f})"
    )


def test_a_borderline_row_still_beats_the_clear_skips() -> None:
    """Borderline is arguable against a pursue, not against a skip.

    Asserting it lands below the pursues too would pin the one relationship
    that is genuinely uncertain, and fail on every honest tuning change.
    """
    borderline = labelled("borderline")
    assert borderline, "the ranking corpus needs at least one borderline posting"
    skips = [evaluate(sid)[1] for sid in labelled("skip")]
    assert skips, "the ranking corpus needs at least one skip posting"
    for source_id in borderline:
        assert evaluate(source_id)[1] > max(skips), (
            f"borderline {source_id} fell below a clear skip"
        )


def test_the_best_match_is_the_target_role() -> None:
    """The RBC Winter 2027 risk internship in Toronto is what this search is for.

    Stated as its own case because it is the one a reader of this file would
    check by hand, and because "the top of the list is right" is the claim the
    tool actually makes.
    """
    scored = {
        sid: total
        for sid, (verdict, total) in ((s, evaluate(s)) for s in load_postings())
        if verdict.passed
    }
    top = max(scored, key=lambda sid: scored[sid])
    assert top == "R-0000186717", f"expected the RBC credit risk internship on top, got {top}"


def test_scores_stay_within_range() -> None:
    for source_id in load_postings():
        verdict, total = evaluate(source_id)
        assert 0.0 <= total <= 1.0, f"{source_id} scored {total}, outside [0, 1]"
