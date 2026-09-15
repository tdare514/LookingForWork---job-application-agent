"""Hard filters: the boolean cuts that run before anything is scored.

Two rules shape every filter here.

**Silence is not a no.** A posting that does not state its compensation, its
work arrangement or its sponsorship policy has not failed anything -- most
postings state none of the three. Filtering on absence would quietly cut the
majority of a board and leave a short list that looks decisive.

**A cut is recorded, never discarded.** Every verdict carries the reason and
the detail that produced it, and `jobagent shortlist --filtered` reads them
back. A filter that is cutting too aggressively has to be visible; the failure
mode otherwise is a shortlist that looks thin because the market is thin.

Order matters only for cost and for which reason a row is labelled with. The
cheapest, most categorical cuts run first, so a blocked company is reported as
blocked rather than as, say, underpaid.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from enum import StrEnum

from jobagent.core.profile import Profile
from jobagent.core.vocabulary import Seniority
from jobagent.matching.candidate import Candidate
from jobagent.matching.normalize import (
    normalize_company,
    normalize_location,
    normalize_seniority,
    seniority_distance,
)

# One rung either side of the target band is close enough to be worth reading;
# two is a different job. `docs/job-matching.md` states the rule, this is where
# it is enforced.
MAX_SENIORITY_DISTANCE = 1

# Workday tenants publish "2 Locations" in the location field when a posting
# spans several, and the cities are then only in the body. Read literally that is
# a city called "2 locations", which matches nothing and cuts the row -- a
# posting the source declined to place is unknown, not elsewhere. Found by
# running the filters over real TD rows, where it silently removed two.
_PLACEHOLDER_LOCATION = re.compile(r"^\s*\d+\s+locations?\s*$", re.I)


def _is_placeholder(location: str) -> bool:
    return bool(_PLACEHOLDER_LOCATION.match(location))


class FilterReason(StrEnum):
    """Why a posting was cut. Stored, so these strings are a small contract."""

    BLOCKED_COMPANY = "blocked_company"
    DEAL_BREAKER = "deal_breaker"
    SENIORITY = "seniority"
    ARRANGEMENT = "work_arrangement"
    LOCATION = "location"
    COMPENSATION = "compensation_below_floor"
    SPONSORSHIP = "sponsorship_not_offered"


@dataclass(frozen=True)
class Verdict:
    passed: bool
    reason: FilterReason | None = None
    detail: str = ""

    @property
    def label(self) -> str:
        return "" if self.passed else f"{self.reason}: {self.detail}"


PASSED = Verdict(True)


def _cut(reason: FilterReason, detail: str) -> Verdict:
    return Verdict(False, reason, detail)


def blocked_company(candidate: Candidate, profile: Profile) -> Verdict:
    """The blocklist, matched on the canonical name.

    Blocking "Bank of Montreal" also blocks a posting that says "BMO Capital
    Markets". A blocklist that only catches the spelling the user happened to
    type is not a blocklist.
    """
    blocked = {normalize_company(name) for name in profile.company_blocklist}
    if normalize_company(candidate.company) in blocked:
        return _cut(FilterReason.BLOCKED_COMPANY, candidate.company)
    return PASSED


def deal_breaker(candidate: Candidate, profile: Profile) -> Verdict:
    """Free-text deal-breakers, matched against the whole posting.

    Whole-phrase and case-insensitive, with word boundaries so that "unpaid"
    does not fire on "unpaid leave is available" -- it does, and that is the
    known cost of a cheap rule. The reason is stored with the matched phrase so
    a false positive is visible rather than mysterious.
    """
    haystack = candidate.text.lower()
    for phrase in profile.deal_breakers:
        needle = phrase.strip().lower()
        if not needle:
            continue
        if re.search(rf"\b{re.escape(needle)}\b", haystack):
            return _cut(FilterReason.DEAL_BREAKER, phrase)
    return PASSED


def seniority(candidate: Candidate, profile: Profile) -> Verdict:
    """More than one rung outside the target band.

    The posting's rung comes from its title first and its description second --
    the same placement the board uses -- so a "2027 Winter Analyst Intern" is an
    intern here and everywhere else.
    """
    posting_rung = normalize_seniority(candidate.title, candidate.description)
    distances = [seniority_distance(posting_rung, wanted) for wanted in profile.target_seniority]
    closest = min(distances)
    if closest > MAX_SENIORITY_DISTANCE:
        wanted = ", ".join(str(s) for s in profile.target_seniority)
        return _cut(
            FilterReason.SENIORITY,
            f"posting reads as {posting_rung}, {closest} rungs from {wanted}",
        )
    return PASSED


def arrangement(candidate: Candidate, profile: Profile) -> Verdict:
    """Onsite/hybrid/remote, when the posting says.

    Silence passes. Most postings do not state an arrangement in a field, and
    the ones that state it in the body are handled by extraction, not here.
    """
    stated = (candidate.work_arrangement or candidate.requirements.work_arrangement or "").lower()
    if not stated:
        return PASSED
    if stated not in profile.work_arrangements:
        return _cut(
            FilterReason.ARRANGEMENT,
            f"posting is {stated}, profile wants {', '.join(profile.work_arrangements)}",
        )
    return PASSED


def location(candidate: Candidate, profile: Profile) -> Verdict:
    """City, compared canonically -- unless the work is remote.

    Remote is checked first and ignores the city on purpose: a remote role the
    profile accepts should not be cut for the office it nominally reports to.
    An unknown location passes, because not knowing where a job is is not the
    same as knowing it is in the wrong place.
    """
    stated = (candidate.work_arrangement or candidate.requirements.work_arrangement or "").lower()
    if stated == "remote" and "remote" in profile.work_arrangements:
        return PASSED
    if not candidate.location or _is_placeholder(candidate.location):
        return PASSED
    wanted = {normalize_location(name) for name in profile.locations}
    city = normalize_location(candidate.location)
    if city and city not in wanted:
        return _cut(
            FilterReason.LOCATION, f"{candidate.location} is not in {', '.join(sorted(wanted))}"
        )
    return PASSED


def compensation(candidate: Candidate, profile: Profile) -> Verdict:
    """Cut only when a disclosed band sits *entirely* below the floor.

    Undisclosed pay is the common case and never disqualifies. A band that
    straddles the floor stays: the top of the range is negotiable and the
    bottom of it is not the offer.
    """
    floor = profile.compensation.floor
    if floor is None:
        return PASSED
    top = candidate.compensation_max or candidate.requirements.compensation_max
    bottom = candidate.compensation_min or candidate.requirements.compensation_min
    highest = top if top is not None else bottom
    if highest is None:
        return PASSED
    currency = candidate.currency or candidate.requirements.currency
    if currency and currency.upper() != profile.compensation.currency:
        # Comparing across currencies needs a rate this tool does not have and
        # will not fetch. Say nothing rather than guess.
        return PASSED
    if highest < floor:
        return _cut(
            FilterReason.COMPENSATION,
            f"tops out at {highest} {profile.compensation.currency}, floor is {floor}",
        )
    return PASSED


def sponsorship(candidate: Candidate, profile: Profile) -> Verdict:
    """Only bites when the user needs sponsorship and the posting refuses it.

    If the profile needs no sponsorship the field is irrelevant, and if the
    posting says nothing then nothing is known. Both pass.
    """
    if not profile.work_authorization.needs_sponsorship:
        return PASSED
    if candidate.requirements.sponsorship == "not_offered":
        return _cut(FilterReason.SPONSORSHIP, "posting states sponsorship is not available")
    return PASSED


# Cheapest and most categorical first, so the recorded reason is the most
# informative one rather than whichever rule happened to run.
FILTERS = (
    blocked_company,
    deal_breaker,
    seniority,
    arrangement,
    location,
    compensation,
    sponsorship,
)


def apply(candidate: Candidate, profile: Profile) -> Verdict:
    """Run every filter, stopping at the first cut."""
    for rule in FILTERS:
        verdict = rule(candidate, profile)
        if not verdict.passed:
            return verdict
    return PASSED


def posting_seniority(candidate: Candidate) -> Seniority:
    """Where a posting sits on the ladder. Shared with the scorer, which needs
    the same answer the seniority filter used -- computing it twice from two
    places is how the filter and the score start disagreeing."""
    return normalize_seniority(candidate.title, candidate.description)
