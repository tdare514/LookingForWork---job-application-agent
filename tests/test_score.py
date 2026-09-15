"""Decomposed scoring (#31).

Two things are being defended here. The component arithmetic, which is ordinary.
And the rule that an absent component is dropped rather than zeroed, which is
the decision that makes a half-fetched board rankable and which is easy to undo
by accident -- a stray `or 0.0` in the wrong place turns "we don't know" into
"it's bad" and nothing fails loudly.
"""

from __future__ import annotations

from datetime import date, timedelta

from jobagent.core.profile import Profile, Weights, WorkAuthorization
from jobagent.core.vocabulary import Seniority
from jobagent.matching.extract import Requirements
from jobagent.matching.filters import Listing
from jobagent.matching.score import FRESHNESS_HALF_LIFE_DAYS, Component, Score, score

TODAY = date(2026, 9, 15)


def make_profile(**overrides: object) -> Profile:
    base: dict[str, object] = {
        "target_titles": ["Risk Analyst"],
        "target_seniority": [Seniority.INTERN],
        "locations": ["Toronto"],
        "work_arrangements": ["onsite", "hybrid"],
        "must_have_skills": ["python", "sql"],
        "nice_to_have_skills": ["tableau"],
        "work_authorization": WorkAuthorization(authorized_in=["CA"], needs_sponsorship=False),
    }
    base.update(overrides)
    return Profile(**base)  # type: ignore[arg-type]


INTERN_LISTING = Listing(company="RBC", title="2027 Winter - Risk Analyst Intern")


def component(result: Score, name: str) -> Component:
    return next(c for c in result.components if c.name == name)


def value_of(result: Score, name: str) -> float:
    """The component's value, insisting it has one.

    Every caller below is asserting about a component it expects to have been
    measured; if one comes back None the test should say so rather than compare
    against None and fail somewhere less obvious.
    """
    found = component(result, name).value
    assert found is not None, f"{name} was expected to have a value"
    return found


# -- the absence rule -----------------------------------------------------


def test_a_bare_listing_still_scores() -> None:
    """No description, no posted date -- the shape of every freshly fetched row.

    It has to come out with a usable number, or the board is unrankable until
    `fetch --details` has run over every posting.
    """
    result = score(INTERN_LISTING, Requirements(), make_profile(), None, TODAY)
    assert 0.0 < result.total <= 1.0
    assert "skill_overlap" in result.unavailable
    assert "freshness" in result.unavailable
    assert "seniority_fit" in result.scored_on


def test_an_absent_component_is_dropped_not_zeroed() -> None:
    """The decision this module exists to protect.

    Two listings identical but for a description. If absence were scored as
    zero, the one we know less about would rank lower for that reason alone, and
    running `fetch --details` would reshuffle the board.
    """
    profile = make_profile()
    described = Requirements(required_skills=("python", "sql"))

    bare = score(INTERN_LISTING, Requirements(), profile, None, TODAY)
    full = score(INTERN_LISTING, described, profile, None, TODAY)

    # The described one matches every skill, so it should score at least as
    # well -- but the bare one must not be dragged toward zero by the gap.
    assert full.total >= bare.total
    assert bare.total > 0.5, "an unknown component must not behave like a bad one"


def test_a_description_read_and_found_empty_scores_zero_not_unknown() -> None:
    """Knowing less about a job must never flatter it.

    A long posting body naming none of the profile's skills has been measured,
    and the measurement is zero. Treating it as unknown drops it from the total
    and lets an off-target role float up on its remaining components -- which is
    exactly how a TD contact centre posting outranked an RBC risk internship on
    the fixture set.
    """
    described = Listing(
        company="TD",
        title="2027 Winter - Risk Analyst Intern",
        description="A long posting about customer service, with no analytical skills named.",
    )
    result = score(described, Requirements(), make_profile(), None, TODAY)
    assert value_of(result, "skill_overlap") == 0.0
    assert "skill_overlap" in result.scored_on


def test_an_unextracted_posting_is_unknown_even_with_a_description() -> None:
    """The bug that hid one layer up from the one above.

    A posting can have a description stored and never have been run through
    `extract`. Its empty `Requirements` looks identical to one the extractor
    produced and found nothing in -- but nobody looked, so the honest answer is
    that we do not know.
    """
    described = Listing(
        company="TD",
        title="2027 Winter - Risk Analyst Intern",
        description="Requires Python, SQL and Excel -- never run through the extractor.",
    )
    result = score(described, Requirements(), make_profile(), None, TODAY, extracted=False)
    assert component(result, "skill_overlap").value is None
    assert "nothing read yet" in component(result, "skill_overlap").basis


def test_weights_are_rescaled_over_what_was_measured() -> None:
    """With one component at 1.0 and the rest absent, the total is 1.0."""
    profile = make_profile(
        weights=Weights(skill_overlap=0.5, seniority_fit=0.5, domain_relevance=0, freshness=0)
    )
    perfect = Requirements(required_skills=("python", "sql"))
    result = score(INTERN_LISTING, perfect, profile, None, TODAY)
    assert result.total == 1.0


def test_semantic_fit_is_always_recorded_as_unavailable() -> None:
    """Five components, one of them explaining itself rather than missing."""
    result = score(INTERN_LISTING, Requirements(), make_profile(), None, TODAY)
    assert len(result.components) == 5
    assert "semantic_fit" in result.unavailable
    basis = component(result, "semantic_fit").basis
    assert "embedding" in basis


def test_a_zeroed_weight_removes_the_component_from_the_total() -> None:
    """Someone switching a component off must not have it creep back in."""
    off = make_profile(
        weights=Weights(skill_overlap=1.0, seniority_fit=0, domain_relevance=0, freshness=0)
    )
    # Seniority is a perfect match and would lift the total if it counted.
    bad_skills = Requirements(required_skills=("cobol", "fortran"))
    result = score(INTERN_LISTING, bad_skills, off, None, TODAY)
    assert result.total == 0.0


# -- components -----------------------------------------------------------


def test_skill_overlap_weights_required_above_preferred() -> None:
    profile = make_profile(must_have_skills=["python"], nice_to_have_skills=[])
    got_required = Requirements(required_skills=("python",), preferred_skills=("cobol",))
    got_preferred = Requirements(required_skills=("cobol",), preferred_skills=("python",))

    better = value_of(score(INTERN_LISTING, got_required, profile, None, TODAY), "skill_overlap")
    worse = value_of(score(INTERN_LISTING, got_preferred, profile, None, TODAY), "skill_overlap")
    assert better > worse


def test_skill_overlap_is_a_share_of_what_the_posting_asks_for() -> None:
    """A long profile should not be punished for listing skills nobody wants."""
    profile = make_profile(must_have_skills=["python", "sql", "r", "sas", "excel", "tableau"])
    result = score(INTERN_LISTING, Requirements(required_skills=("python",)), profile, None, TODAY)
    assert value_of(result, "skill_overlap") == 1.0


def test_seniority_fit_is_full_on_an_exact_match() -> None:
    result = score(INTERN_LISTING, Requirements(), make_profile(), None, TODAY)
    assert value_of(result, "seniority_fit") == 1.0


def test_seniority_fit_says_when_the_level_was_assumed() -> None:
    unmarked = Listing(company="RBC", title="Counterparty Credit Risk, Capital Markets")
    result = score(unmarked, Requirements(), make_profile(), None, TODAY)
    assert "assumed" in component(result, "seniority_fit").basis


def test_domain_relevance_reads_the_title_against_the_targets() -> None:
    profile = make_profile(target_titles=["Risk Analyst"])
    on_target = score(INTERN_LISTING, Requirements(), profile, None, TODAY)
    off_target = score(
        Listing(company="RBC", title="Warehouse Logistics Supervisor"),
        Requirements(),
        profile,
        None,
        TODAY,
    )
    assert value_of(on_target, "domain_relevance") > value_of(off_target, "domain_relevance")


def test_freshness_halves_over_the_half_life() -> None:
    posted = (TODAY - timedelta(days=int(FRESHNESS_HALF_LIFE_DAYS))).isoformat()
    result = score(INTERN_LISTING, Requirements(), make_profile(), posted, TODAY)
    assert abs(value_of(result, "freshness") - 0.5) < 0.01


def test_freshness_is_absent_rather_than_backfilled_from_first_seen() -> None:
    """`first_seen_at` records when we looked, not when it was posted.

    Using it would make a two-month-old posting read as brand new on the day it
    is first fetched -- a number about us, not about the job.
    """
    result = score(INTERN_LISTING, Requirements(), make_profile(), None, TODAY)
    assert component(result, "freshness").value is None


def test_an_unparseable_posted_at_is_absent_rather_than_guessed() -> None:
    result = score(INTERN_LISTING, Requirements(), make_profile(), "last Tuesday", TODAY)
    assert component(result, "freshness").value is None


# -- the stored shape -----------------------------------------------------


def test_the_decomposition_survives_a_round_trip_to_json() -> None:
    """`scores.components` is what makes a ranking arguable, so it must be complete."""
    import json

    result = score(INTERN_LISTING, Requirements(required_skills=("python",)), make_profile())
    payload = json.loads(json.dumps(result.as_dict()))
    assert set(payload["components"]) == {
        "skill_overlap",
        "seniority_fit",
        "domain_relevance",
        "freshness",
        "semantic_fit",
    }
    for component_payload in payload["components"].values():
        assert component_payload["basis"], "every component has to say what it looked at"
