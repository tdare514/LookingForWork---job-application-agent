"""Canonical normalization (#28).

These are pure functions over strings, which makes them cheap to test and the
right place to pin the judgement calls. The cases below are drawn from real
payloads captured in #58 rather than invented, because the last round of
hand-written fixtures encoded the same assumption as the code and caught
nothing.
"""

from __future__ import annotations

from jobagent.core.vocabulary import Seniority
from jobagent.matching.normalize import (
    dedupe_key,
    normalize_company,
    normalize_location,
    normalize_seniority,
    normalize_title,
    same_role,
    seniority_distance,
    title_similarity,
)

# -- company ------------------------------------------------------------------


def test_legal_forms_collapse_to_one_employer() -> None:
    assert normalize_company("Acme, Inc.") == normalize_company("Acme Inc")
    assert normalize_company("Acme Inc") == normalize_company("ACME")


def test_a_trading_name_and_a_legal_name_are_one_employer() -> None:
    """The case a suffix stripper cannot reach, and the one that matters here."""
    assert normalize_company("Bank of Montreal") == normalize_company("BMO")
    assert normalize_company("Royal Bank of Canada") == normalize_company("RBC")
    assert normalize_company("The Toronto-Dominion Bank") == normalize_company("TD")


def test_the_word_bank_is_not_stripped() -> None:
    """It used to be, which turned "Bank of Montreal" into "of montreal".

    That is not a cosmetic bug: every Canadian bank on the target list has
    "Bank" in its legal name, so stripping it was wrong for exactly the
    employers this tool exists to chase.
    """
    assert normalize_company("Bank of Montreal") == "bmo"
    assert normalize_company("Bank of Nova Scotia") == "scotiabank"


def test_a_name_that_is_only_a_legal_form_is_not_erased() -> None:
    """Stripping everything would make every such company the same company."""
    assert normalize_company("Group Ltd") != ""


# -- title --------------------------------------------------------------------


def test_campus_posting_noise_is_stripped_from_the_title() -> None:
    """Workday bakes the term, the length and an encoding artefact into titles."""
    assert (
        normalize_title("XMLNAME 2027 Winter - Technology Analyst Intern (8 Months)")
        == "technology analyst intern"
    )


def test_the_same_role_next_term_normalizes_identically() -> None:
    assert normalize_title("2027 Winter - Business Analyst") == normalize_title(
        "2028 Summer - Business Analyst"
    )


def test_seniority_survives_normalization() -> None:
    """It is the guard that stops two levels of one role merging, so it must stay."""
    assert "senior" in normalize_title("Senior Data Scientist")


# -- location -----------------------------------------------------------------


def test_two_spellings_of_one_city_agree() -> None:
    assert normalize_location("TORONTO, Ontario, Canada") == normalize_location("Toronto, ON")


def test_a_street_address_still_yields_the_city() -> None:
    """Workday leads with the building: "7250 Mile End, Montreal, Quebec"."""
    assert normalize_location("7250 Mile End, Montreal, Quebec") == "montreal"
    assert normalize_location("ROYAL BANK PLAZA, 200 BAY ST:TORONTO") == "toronto"


def test_a_missing_location_is_empty_not_an_error() -> None:
    """Remote roles legitimately have none."""
    assert normalize_location(None) == ""


# -- seniority ----------------------------------------------------------------


def test_the_ladder_is_independent_of_title_inflation() -> None:
    assert normalize_seniority("Senior Data Scientist") is Seniority.SENIOR
    assert normalize_seniority("Data Scientist") is Seniority.MID
    assert normalize_seniority("2027 Winter - Analyst Intern") is Seniority.INTERN


def test_the_most_specific_match_wins() -> None:
    """A "Senior Manager" is a manager, not a senior individual contributor."""
    assert normalize_seniority("Senior Manager, Risk") is Seniority.MANAGER


def test_distance_is_what_the_hard_filters_will_use() -> None:
    assert seniority_distance(Seniority.INTERN, Seniority.JUNIOR) == 1
    assert seniority_distance(Seniority.INTERN, Seniority.DIRECTOR) > 1


# -- same_role ----------------------------------------------------------------


def test_a_department_prefix_does_not_make_a_new_role() -> None:
    """RBC prefixes the group onto the title; it is the same requisition."""
    assert same_role(
        "2027 Winter - GRM, Counterparty Credit Risk Intern (4 Months)",
        "Counterparty Credit Risk Intern",
    )


def test_two_levels_of_one_role_stay_separate() -> None:
    """The case #28 calls out as the one fuzzy matching gets wrong."""
    assert not same_role("Data Scientist", "Senior Data Scientist")


def test_a_level_number_makes_a_different_role() -> None:
    """One character apart, and a different job. String distance cannot see it."""
    assert not same_role("Analyst I", "Analyst II")
    assert not same_role("Engineer 1", "Engineer 2")


def test_two_different_roles_sharing_a_word_stay_separate() -> None:
    assert not same_role("Analyst, Risk", "Analyst, Credit")
    assert not same_role("Senior Data Scientist", "Senior Data Engineer")


def test_a_plural_or_typo_still_matches() -> None:
    assert same_role("Data Scientist", "Data Scientists")


def test_similarity_is_reported_not_just_thresholded() -> None:
    """A tunable threshold needs a number you can look at when tuning it."""
    assert title_similarity("Business Analyst", "Business Analyst") == 1.0
    assert title_similarity("Analyst, Risk", "Analyst, Credit") < 0.5


# -- the key ------------------------------------------------------------------


def test_the_same_posting_from_two_sources_keys_identically() -> None:
    assert dedupe_key("Bank of Montreal", "Client Service Associate", "Calgary, AB, CAN") == (
        dedupe_key("BMO", "Client Service Associate", "Calgary, Alberta, Canada")
    )


def test_a_department_named_after_the_c_suite_is_not_an_executive_role() -> None:
    """Found against live RBC data, not invented.

    RBC posts "2027 CFO, Winter Financial Analyst" -- a student role in the CFO
    group. Reading "CFO" as the level would have filtered a co-op posting out of
    a co-op job search as an executive role.
    """
    assert normalize_seniority("2027 CFO, Winter Financial Analyst, ALM Macro Hedging") is (
        Seniority.INTERN
    )
    assert normalize_seniority("Chief Financial Officer") is Seniority.EXECUTIVE


def test_a_term_and_a_year_together_mark_a_campus_posting() -> None:
    assert normalize_seniority("2027 Winter - Financial Analyst") is Seniority.INTERN
    assert normalize_seniority("Financial Analyst") is not Seniority.INTERN
