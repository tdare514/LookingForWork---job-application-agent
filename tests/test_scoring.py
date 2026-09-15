"""Hard filters and decomposed scoring (#31).

Two kinds of test here, and they fail for different reasons.

The unit tests pin judgement calls: silence is not a no, a straddling pay band
survives, an unknown component scores as unknown rather than as zero. Those are
decisions, and the comments say why each one went the way it did.

The regression at the bottom is the one that matters. It runs the whole
pipeline over twelve real postings with hand-labelled verdicts and asserts only
what the labels justify: nothing I would apply to may be cut by a filter, and
nothing I would not open may outrank something I would. It deliberately does not
pin exact scores -- that would fail on every weight change, including the ones
that make the ranking better.
"""

from __future__ import annotations

import json
from datetime import date
from pathlib import Path

from jobagent.core.profile import Profile, load_file
from jobagent.core.storage import Storage
from jobagent.core.vocabulary import Seniority
from jobagent.matching.candidate import Candidate
from jobagent.matching.extract import Requirements, extract
from jobagent.matching.filters import FilterReason, apply
from jobagent.matching.score import Component, score
from jobagent.tracking.repo import BoardRepo

ROOT = Path(__file__).resolve().parents[1]
EXAMPLE_PROFILE = ROOT / "profile.example.yaml"
POSTINGS = json.loads((Path(__file__).parent / "fixtures" / "postings.json").read_text())
LABELS = json.loads((Path(__file__).parent / "fixtures" / "scoring_labels.json").read_text())


def _profile(**overrides: object) -> Profile:
    """The example profile, optionally bent for one test."""
    base = load_file(EXAMPLE_PROFILE).model_dump()
    base.update(overrides)
    return Profile.model_validate(base)


def _candidate(**overrides: object) -> Candidate:
    base: dict[str, object] = {
        "job_id": 1,
        "company": "RBC",
        "title": "2027 Winter - Data Analyst Intern (4 Months)",
        "location": "TORONTO, Ontario, Canada",
        "description": "Support reporting and analysis. SQL and Excel required.",
        "requirements": Requirements(required_skills=("sql", "excel")),
    }
    base.update(overrides)
    return Candidate(**base)  # type: ignore[arg-type]  # test helper, keys are the field names


# -- hard filters: what they cut ----------------------------------------------


def test_a_blocked_company_is_cut_under_any_of_its_names() -> None:
    profile = _profile(company_blocklist=["Bank of Montreal"])
    verdict = apply(_candidate(company="BMO Capital Markets"), profile)
    assert not verdict.passed
    assert verdict.reason is FilterReason.BLOCKED_COMPANY


def test_a_posting_in_the_wrong_city_is_cut() -> None:
    verdict = apply(_candidate(location="New York, New York, United States"), _profile())
    assert not verdict.passed
    assert verdict.reason is FilterReason.LOCATION


def test_seniority_more_than_one_rung_out_is_cut() -> None:
    verdict = apply(_candidate(title="Senior Manager, Analytics and Insights"), _profile())
    assert not verdict.passed
    assert verdict.reason is FilterReason.SENIORITY


def test_one_rung_out_survives() -> None:
    """A junior posting for an intern-and-junior profile is exactly the stretch
    the rule is meant to allow through."""
    assert apply(_candidate(title="Junior Data Analyst"), _profile()).passed


def test_a_deal_breaker_in_the_body_is_cut_with_the_phrase_named() -> None:
    verdict = apply(
        _candidate(description="Applicants must hold an active security clearance."),
        _profile(),
    )
    assert not verdict.passed
    assert verdict.reason is FilterReason.DEAL_BREAKER
    assert "security clearance" in verdict.detail


# -- hard filters: what they must NOT cut -------------------------------------


def test_undisclosed_compensation_never_disqualifies() -> None:
    """The common case. Filtering on absence would cut most of a real board."""
    assert apply(_candidate(), _profile()).passed


def test_a_band_straddling_the_floor_survives() -> None:
    """The bottom of a posted range is not the offer."""
    profile = _profile(compensation={"floor": 25, "currency": "CAD"})
    candidate = _candidate(compensation_min=20, compensation_max=32, currency="CAD")
    assert apply(candidate, profile).passed


def test_a_band_entirely_below_the_floor_is_cut() -> None:
    profile = _profile(compensation={"floor": 25, "currency": "CAD"})
    candidate = _candidate(compensation_min=15, compensation_max=18, currency="CAD")
    verdict = apply(candidate, profile)
    assert not verdict.passed
    assert verdict.reason is FilterReason.COMPENSATION


def test_a_band_in_another_currency_is_not_compared() -> None:
    """Converting needs a rate this tool does not have and will not fetch."""
    profile = _profile(compensation={"floor": 25, "currency": "CAD"})
    candidate = _candidate(compensation_min=15, compensation_max=18, currency="USD")
    assert apply(candidate, profile).passed


def test_silence_about_sponsorship_is_not_a_refusal() -> None:
    profile = _profile(work_authorization={"authorized_in": ["CA"], "needs_sponsorship": True})
    assert apply(_candidate(), profile).passed


def test_a_stated_refusal_to_sponsor_cuts_only_when_sponsorship_is_needed() -> None:
    needs = _profile(work_authorization={"authorized_in": ["CA"], "needs_sponsorship": True})
    does_not = _profile()
    candidate = _candidate(requirements=Requirements(sponsorship="not_offered"))
    assert not apply(candidate, needs).passed
    assert apply(candidate, does_not).passed


def test_a_remote_posting_is_not_cut_for_its_city() -> None:
    profile = _profile(work_arrangements=["hybrid", "remote"])
    candidate = _candidate(location="Vancouver, BC", work_arrangement="remote")
    assert apply(candidate, profile).passed


def test_an_unknown_location_passes() -> None:
    """Not knowing where a job is differs from knowing it is in the wrong place."""
    assert apply(_candidate(location=None), _profile()).passed


# -- components ----------------------------------------------------------------


def test_required_skills_count_for_more_than_preferred() -> None:
    profile = _profile(must_have_skills=["SQL"], nice_to_have_skills=[])
    hits_required = _candidate(
        requirements=Requirements(required_skills=("sql",), preferred_skills=("tableau",))
    )
    hits_preferred = _candidate(
        requirements=Requirements(required_skills=("tableau",), preferred_skills=("sql",))
    )
    a = score(hits_required, profile).component(Component.SKILL_OVERLAP).value
    b = score(hits_preferred, profile).component(Component.SKILL_OVERLAP).value
    assert a > b


def test_a_posting_listing_no_skills_scores_unknown_not_zero() -> None:
    """Zero is a claim about the posting. The rules simply did not find any."""
    part = score(_candidate(requirements=Requirements()), _profile()).component(
        Component.SKILL_OVERLAP
    )
    assert part.value == 0.5
    assert "no skills" in part.reason


def test_the_skill_reason_names_hits_and_misses() -> None:
    profile = _profile(must_have_skills=["SQL"], nice_to_have_skills=[])
    candidate = _candidate(requirements=Requirements(required_skills=("sql", "sas")))
    reason = score(candidate, profile).component(Component.SKILL_OVERLAP).reason
    assert "sql" in reason and "sas" in reason


def test_profile_skills_go_through_the_same_vocabulary_as_postings() -> None:
    """ "Power BI" typed by a person and "powerbi" printed by a job board are one
    skill. Comparing raw strings would score zero on exactly the real matches."""
    profile = _profile(must_have_skills=["Power BI"], nice_to_have_skills=[])
    candidate = _candidate(requirements=Requirements(required_skills=("power bi",)))
    assert score(candidate, profile).component(Component.SKILL_OVERLAP).value == 1.0


def test_seniority_fit_is_full_on_the_target_rung() -> None:
    profile = _profile(target_seniority=[Seniority.INTERN])
    assert score(_candidate(), profile).component(Component.SENIORITY_FIT).value == 1.0


def test_freshness_decays_and_says_how_old() -> None:
    today = date(2026, 9, 15)
    fresh = _candidate(posted_at="2026-09-15T00:00:00+00:00")
    old = _candidate(posted_at="2026-08-01T00:00:00+00:00")
    fresh_part = score(fresh, _profile(), today=today).component(Component.FRESHNESS)
    old_part = score(old, _profile(), today=today).component(Component.FRESHNESS)
    assert fresh_part.value > old_part.value
    assert "days since posted" in old_part.reason


def test_an_undated_posting_scores_freshness_as_unknown() -> None:
    part = score(_candidate(), _profile()).component(Component.FRESHNESS)
    assert part.value == 0.5
    assert part.reason == "no posting date"


def test_semantic_fit_is_reported_as_absent_rather_than_faked() -> None:
    part = score(_candidate(), _profile()).component(Component.SEMANTIC_FIT)
    assert part.value == 0.0
    assert "no local embedding backend" in part.reason


def test_the_total_uses_the_profiles_weights_not_constants() -> None:
    """Someone changing domains sets domain relevance near zero; the ranking has
    to move when they do, or the weights are decoration."""
    candidate = _candidate(
        description="Reporting and analysis of counterparty credit risk portfolios.",
        requirements=Requirements(required_skills=("sql",)),
    )
    skills_matter = _profile(
        weights={"skill_overlap": 1.0, "seniority_fit": 0, "domain_relevance": 0, "freshness": 0}
    )
    freshness_matters = _profile(
        weights={"skill_overlap": 0, "seniority_fit": 0, "domain_relevance": 0, "freshness": 1.0}
    )
    assert score(candidate, skills_matter).total != score(candidate, freshness_matters).total


def test_the_explanation_names_the_strongest_and_the_weakest() -> None:
    explanation = score(_candidate(), _profile()).explain()
    assert "strongest" in explanation and "weakest" in explanation


# -- storage: a cut is recorded, not discarded ---------------------------------


def test_filtered_rows_are_queryable_with_their_reason(store: Storage) -> None:
    repo = BoardRepo(store)
    job, _ = repo.add("RBC", "Senior Manager, Analytics", location="Toronto, ON")
    profile = _profile()
    candidate = _candidate(job_id=job.id, title="Senior Manager, Analytics")

    verdict = apply(candidate, profile)
    assert not verdict.passed
    repo.save_filtered(job.id, verdict)

    filtered = repo.filtered_out()
    assert [j.id for j, _reason in filtered] == [job.id]
    assert "seniority" in filtered[0][1]


def test_the_shortlist_ranks_by_total_and_keeps_the_decomposition(store: Storage) -> None:
    repo = BoardRepo(store)
    low, _ = repo.add("RBC", "Low match")
    high, _ = repo.add("BMO", "High match")
    profile = _profile()

    repo.save_score(score(_candidate(job_id=low.id, requirements=Requirements()), profile))
    repo.save_score(
        score(
            _candidate(job_id=high.id, requirements=Requirements(required_skills=("sql", "excel"))),
            profile,
        )
    )

    ranked = repo.shortlist()
    assert [job.id for job, _total, _parts in ranked] == [high.id, low.id]
    components = ranked[0][2]
    assert set(components) == {str(c) for c in Component}
    assert "reason" in components["skill_overlap"]


def test_rescoring_replaces_the_previous_run(store: Storage) -> None:
    repo = BoardRepo(store)
    job, _ = repo.add("RBC", "Analyst Intern")
    repo.save_score(score(_candidate(job_id=job.id), _profile()))
    repo.clear_scores()
    repo.save_score(score(_candidate(job_id=job.id), _profile()))
    assert len(repo.shortlist()) == 1


# -- the regression that matters ----------------------------------------------


def _labelled_candidates() -> list[tuple[str, Candidate]]:
    """The twelve real postings, extracted the way `jobagent extract` would."""
    by_id = {p["source_id"]: p for p in POSTINGS}
    out: list[tuple[str, Candidate]] = []
    for index, label in enumerate(LABELS["labels"], start=1):
        posting = by_id[label["source_id"]]
        out.append(
            (
                label["verdict"],
                Candidate(
                    job_id=index,
                    company=posting["company"],
                    title=posting["title"],
                    location=posting.get("location"),
                    description=posting.get("description"),
                    requirements=extract(posting.get("description")),
                ),
            )
        )
    return out


def test_every_posting_worth_applying_to_survives_the_filters() -> None:
    """The expensive failure. A filter that quietly removes the one job worth an
    evening is indistinguishable, from the outside, from a quiet market."""
    profile = load_file(EXAMPLE_PROFILE)
    for verdict, candidate in _labelled_candidates():
        if verdict != "pursue":
            continue
        result = apply(candidate, profile)
        assert result.passed, f"{candidate.title} was cut: {result.label}"


def _surviving(verdict_wanted: str) -> list[tuple[str, float]]:
    profile = load_file(EXAMPLE_PROFILE)
    today = date(2026, 9, 15)
    out: list[tuple[str, float]] = []
    for verdict, candidate in _labelled_candidates():
        if verdict != verdict_wanted or not apply(candidate, profile).passed:
            continue
        out.append((candidate.title, score(candidate, profile, today=today).total))
    return out


def test_nothing_i_would_skip_outranks_something_i_would_pursue() -> None:
    pursued = _surviving("pursue")
    skipped = _surviving("skip")

    assert pursued, "the fixture set has no surviving pursue -- the test proves nothing"
    worst_pursued = min(pursued, key=lambda row: row[1])
    for title, total in skipped:
        assert total < worst_pursued[1], (
            f"{title} scored {total:.3f}, above {worst_pursued[0]} at {worst_pursued[1]:.3f}"
        )


def test_the_ordering_claim_is_not_vacuous() -> None:
    """The ordering test above only means something if a skip reaches the scorer.

    Most labelled skips are cut by a hard filter -- wrong country, wrong rung --
    and a comparison with an empty list passes by having no work to do. One skip
    does survive: a Wilmington posting whose location field reads "2 Locations",
    which the filters correctly treat as unknown rather than elsewhere. It is
    what makes the ordering assertion evidence rather than decoration, so this
    fails if the fixture set ever stops producing one.
    """
    assert _surviving("skip"), (
        "every labelled skip is now cut by a filter, so the ordering test proves "
        "nothing -- add a skip that survives filtering, or the score ordering is "
        "untested against real labels"
    )


def test_the_filters_cut_the_set_measurably() -> None:
    """If the filters remove nothing, they are not filters."""
    profile = load_file(EXAMPLE_PROFILE)
    candidates = [candidate for _verdict, candidate in _labelled_candidates()]
    survivors = [c for c in candidates if apply(c, profile).passed]
    assert 0 < len(survivors) < len(candidates)


def test_the_labels_and_the_postings_have_not_drifted_apart() -> None:
    """A label referring to a posting that no longer exists silently stops
    testing anything, which is the failure mode of every fixture set."""
    posting_ids = {p["source_id"] for p in POSTINGS}
    label_ids = {label["source_id"] for label in LABELS["labels"]}
    assert label_ids == posting_ids


def test_a_multi_location_placeholder_is_unknown_not_elsewhere() -> None:
    """Workday publishes "2 Locations" when a posting spans several, and the
    cities are then only in the body. Reading that literally cut real TD rows
    for being in a city called "2 locations"."""
    assert apply(_candidate(location="2 Locations"), _profile()).passed
