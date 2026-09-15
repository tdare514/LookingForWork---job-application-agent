"""Hard filters (#31).

Every rule gets two tests: one that it cuts when it should, and one that it does
**not** cut when the posting simply did not say. The second is the one worth
having. A filter that cuts too little produces a long list somebody skims; a
filter that cuts too much produces an empty board, which is indistinguishable
from a quiet week and which nobody investigates.
"""

from __future__ import annotations

import pytest

from jobagent.core.profile import Compensation, Profile, WorkAuthorization
from jobagent.core.vocabulary import Seniority
from jobagent.matching.extract import Requirements
from jobagent.matching.filters import Listing, apply_filters


def make_profile(**overrides: object) -> Profile:
    base: dict[str, object] = {
        "target_titles": ["Data Analyst", "Risk Analyst"],
        "target_seniority": [Seniority.INTERN, Seniority.JUNIOR],
        "locations": ["Toronto"],
        "work_arrangements": ["onsite", "hybrid"],
        "must_have_skills": ["python", "sql"],
        "work_authorization": WorkAuthorization(authorized_in=["CA"], needs_sponsorship=False),
    }
    base.update(overrides)
    return Profile(**base)  # type: ignore[arg-type]  # a test builder, keyed by field name


def listing(**overrides: object) -> Listing:
    base: dict[str, object] = {
        "company": "RBC",
        "title": "2027 Winter - Risk Analyst Intern",
        "location": "TORONTO, Ontario, Canada",
    }
    base.update(overrides)
    return Listing(**base)  # type: ignore[arg-type]


EMPTY = Requirements()


def test_a_clean_posting_passes() -> None:
    assert apply_filters(listing(), EMPTY, make_profile()).passed


# -- company blocklist ----------------------------------------------------


def test_blocklist_cuts_through_a_company_alias() -> None:
    """ "BMO" on the blocklist has to catch "Bank of Montreal" on the posting."""
    profile = make_profile(company_blocklist=["BMO"])
    verdict = apply_filters(listing(company="Bank of Montreal"), EMPTY, profile)
    assert not verdict.passed
    assert verdict.rule == "company_blocklist"


def test_an_empty_blocklist_blocks_nothing() -> None:
    assert apply_filters(listing(company="Anyone"), EMPTY, make_profile()).passed


# -- sponsorship ----------------------------------------------------------


def test_a_stated_refusal_cuts_when_sponsorship_is_needed() -> None:
    profile = make_profile(
        work_authorization=WorkAuthorization(authorized_in=["IN"], needs_sponsorship=True)
    )
    requirements = Requirements(sponsorship="not_offered")
    verdict = apply_filters(listing(), requirements, profile)
    assert not verdict.passed
    assert verdict.rule == "sponsorship"


def test_silence_on_sponsorship_is_not_a_refusal() -> None:
    """The overwhelmingly common case. None means the posting did not say."""
    profile = make_profile(
        work_authorization=WorkAuthorization(authorized_in=["IN"], needs_sponsorship=True)
    )
    assert apply_filters(listing(), Requirements(sponsorship=None), profile).passed


def test_sponsorship_is_irrelevant_when_none_is_needed() -> None:
    verdict = apply_filters(listing(), Requirements(sponsorship="not_offered"), make_profile())
    assert verdict.passed


# -- seniority ------------------------------------------------------------


def test_a_stated_level_far_from_target_is_cut() -> None:
    verdict = apply_filters(listing(title="Director, Capital Markets"), EMPTY, make_profile())
    assert not verdict.passed
    assert verdict.rule == "seniority"


def test_one_rung_out_is_a_stretch_not_a_cut() -> None:
    """Staff sits one rung above senior, which is a stretch worth reading."""
    profile = make_profile(target_seniority=[Seniority.SENIOR])
    verdict = apply_filters(listing(title="Staff Risk Analyst"), EMPTY, profile)
    assert verdict.passed


def test_two_rungs_out_is_a_cut() -> None:
    """Senior is two rungs from junior -- a different job, not a stretch."""
    profile = make_profile(target_seniority=[Seniority.JUNIOR])
    verdict = apply_filters(listing(title="Senior Risk Analyst"), EMPTY, profile)
    assert not verdict.passed
    assert verdict.rule == "seniority"


def test_an_unmarked_title_is_never_cut_on_the_mid_fallback() -> None:
    """The decision that keeps the board from emptying itself.

    "Counterparty Credit Risk, Capital Markets" carries no level marker at all,
    so `seniority_of` falls back to MID -- two rungs from an intern target. It
    must survive the filter and be judged by the score instead, because MID here
    is an assumption this tool made, not something the employer wrote.
    """
    unmarked = listing(title="Counterparty Credit Risk, Capital Markets")
    profile = make_profile(target_seniority=[Seniority.INTERN])
    assert apply_filters(unmarked, EMPTY, profile).passed


# -- work arrangement -----------------------------------------------------


def test_an_unaccepted_arrangement_is_cut() -> None:
    profile = make_profile(work_arrangements=["onsite"])
    verdict = apply_filters(listing(work_arrangement="remote"), EMPTY, profile)
    assert not verdict.passed
    assert verdict.rule in {"work_arrangement", "location"}


def test_an_unstated_arrangement_passes() -> None:
    assert apply_filters(listing(work_arrangement=None), EMPTY, make_profile()).passed


# -- location -------------------------------------------------------------


def test_a_different_city_is_cut() -> None:
    verdict = apply_filters(listing(location="Calgary, Alberta, Canada"), EMPTY, make_profile())
    assert not verdict.passed
    assert verdict.rule == "location"


def test_the_same_city_spelled_differently_is_not_cut() -> None:
    assert apply_filters(listing(location="Toronto, ON"), EMPTY, make_profile()).passed


def test_an_unknown_location_passes() -> None:
    assert apply_filters(listing(location=None), EMPTY, make_profile()).passed


def test_a_remote_role_elsewhere_survives_when_remote_is_accepted() -> None:
    """A remote job's city is not where the work happens, so it must not decide."""
    profile = make_profile(work_arrangements=["hybrid", "remote"])
    remote = listing(location="Vancouver, British Columbia", work_arrangement="remote")
    assert apply_filters(remote, EMPTY, profile).passed


# -- compensation ---------------------------------------------------------


def test_a_band_entirely_below_the_floor_is_cut() -> None:
    profile = make_profile(compensation=Compensation(floor=70_000, currency="CAD"))
    low = listing(compensation_min=40_000, compensation_max=50_000, currency="CAD")
    verdict = apply_filters(low, EMPTY, profile)
    assert not verdict.passed
    assert verdict.rule == "compensation"


def test_a_band_straddling_the_floor_is_not_cut() -> None:
    """ "Entirely below" means the top of the band, not the bottom."""
    profile = make_profile(compensation=Compensation(floor=70_000, currency="CAD"))
    straddle = listing(compensation_min=60_000, compensation_max=85_000, currency="CAD")
    assert apply_filters(straddle, EMPTY, profile).passed


def test_an_undisclosed_band_never_disqualifies() -> None:
    profile = make_profile(compensation=Compensation(floor=70_000, currency="CAD"))
    assert apply_filters(listing(), EMPTY, profile).passed


def test_a_foreign_currency_is_not_compared_numerically() -> None:
    """50,000 USD is not below a 70,000 CAD floor in any sense worth acting on.

    No conversion rate belongs in an offline tool, so the honest move is to
    decline to judge rather than to judge wrongly.
    """
    profile = make_profile(compensation=Compensation(floor=70_000, currency="CAD"))
    usd = listing(compensation_min=45_000, compensation_max=50_000, currency="USD")
    assert apply_filters(usd, EMPTY, profile).passed


def test_no_floor_means_no_compensation_filter() -> None:
    low = listing(compensation_min=1, compensation_max=2, currency="CAD")
    assert apply_filters(low, EMPTY, make_profile()).passed


# -- deal-breakers --------------------------------------------------------


def test_a_deal_breaker_phrase_in_the_body_cuts() -> None:
    profile = make_profile(deal_breakers=["security clearance"])
    posting = listing(description="You will need an active security clearance for this role.")
    verdict = apply_filters(posting, EMPTY, profile)
    assert not verdict.passed
    assert verdict.rule == "deal_breaker"
    assert "security clearance" in (verdict.reason or "")


def test_a_deal_breaker_does_not_match_inside_a_longer_word() -> None:
    """Word boundaries, so "ai" does not fire on "said"."""
    profile = make_profile(deal_breakers=["ai"])
    posting = listing(description="The manager said the team ships weekly.")
    assert apply_filters(posting, EMPTY, profile).passed


def test_no_description_means_no_deal_breaker_match() -> None:
    profile = make_profile(deal_breakers=["clearance"])
    assert apply_filters(listing(description=None), EMPTY, profile).passed


# -- the invariant, stated once more --------------------------------------


@pytest.mark.parametrize(
    "requirements",
    [Requirements(), Requirements(required_skills=("python",))],
)
def test_a_posting_that_says_nothing_is_never_cut(requirements: Requirements) -> None:
    """A bare row -- company, title, nothing else -- survives every rule.

    This is the shape of every row the moment it lands from `fetch`, before
    `fetch --details` has run. If this test ever fails, the board empties itself
    the first time someone ingests a source and the tool looks like it is
    working.
    """
    bare = Listing(company="Someone", title="Analyst")
    profile = make_profile(
        company_blocklist=["BMO"],
        deal_breakers=["clearance"],
        compensation=Compensation(floor=200_000, currency="CAD"),
        work_authorization=WorkAuthorization(authorized_in=["IN"], needs_sponsorship=True),
    )
    assert apply_filters(bare, requirements, profile).passed


@pytest.mark.parametrize("location", [None, "2 Locations", "Multiple Locations"])
@pytest.mark.parametrize("separator", [" ", "\n", "\r\n"])
def test_explicit_body_location_resolves_unknown_location(
    location: str | None, separator: str
) -> None:
    row = listing(
        location=location,
        description=f"Work Location:{separator}Wilmington, Delaware, United States of America\n"
        "Hours:\n40",
    )
    verdict = apply_filters(row, EMPTY, make_profile())
    assert verdict.rule == "location"
    assert "Wilmington" in (verdict.reason or "")
    assert "description" in (verdict.reason or "")


@pytest.mark.parametrize(
    "description",
    [
        "Our headquarters are in Wilmington, Delaware, United States of America",
        "Work Location:\nHours:\n40",
        "Work Location: Multiple Locations",
        "Work Location: Toronto or Wilmington, Delaware, United States of America",
        "Work Location: Wilmington, Delaware, United States of America\nWork Location: TBD",
    ],
)
def test_ambiguous_body_location_remains_unknown(description: str) -> None:
    assert apply_filters(
        listing(location="2 Locations", description=description), EMPTY, make_profile()
    ).passed


def test_body_location_accepts_any_explicit_alternative() -> None:
    row = listing(
        location="2 Locations",
        description=(
            "Work Location: Wilmington, Delaware, United States of America\n"
            "Work Location:\nToronto, Ontario, Canada\nHours:\n40"
        ),
    )
    assert apply_filters(row, EMPTY, make_profile()).passed


def test_body_location_does_not_override_a_real_location_or_remote_arrangement() -> None:
    description = "Work Location:\nWilmington, Delaware, United States of America"
    assert apply_filters(listing(description=description), EMPTY, make_profile()).passed
    assert apply_filters(
        listing(location="2 Locations", description=description, work_arrangement="remote"),
        EMPTY,
        make_profile(work_arrangements=["remote"]),
    ).passed
