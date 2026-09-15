"""Hard filters: the cheap, boolean pass that runs before scoring (#31).

These are the rules that answer "this one is not worth reading", and they run
first because everything downstream is more expensive than a string comparison.

**The invariant that matters is that absence is never a refusal.** A posting
that does not state its compensation has not offered a low one. A posting silent
on sponsorship has not declined to sponsor. A title with no level marker is not
a senior role. Every rule below is written so that missing data passes, and the
tests are built around that half rather than the cutting half -- because a
filter that cuts too much produces an empty board, an empty board looks exactly
like "no good jobs this week", and nobody investigates a quiet system.

`core.profile` is blunt about the same failure and defers the comparisons here
on purpose: matching a blocklist entry to a company, or a wanted city to a
posting's location, needs `matching.normalize`, and making `core` import this
package would invert the layering.

Nothing here does I/O. A cut is returned, not applied; the caller stores it with
its reason, because a filter cutting too aggressively has to be discoverable
after the fact rather than inferred from what is missing.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from jobagent.core.profile import Profile
from jobagent.core.vocabulary import Seniority
from jobagent.matching.extract import Requirements
from jobagent.matching.normalize import (
    normalize_company,
    normalize_location,
    seniority_distance,
    seniority_of,
)

# More than this many rungs from the nearest target and the role is a different
# job, not a stretch. One rung is the stretch; two is a career change.
MAX_SENIORITY_DISTANCE = 1

# Location strings that are a source's placeholder rather than a place. TD posts
# "2 Locations" in the city field for any role open in more than one office, and
# Workday writes "Multiple Locations" for the same thing. Normalized, these read
# as a city that matches nothing, so the location filter cut a Toronto-eligible
# quant role for being "in 2 Locations" -- a cut caused entirely by the source's
# formatting. They mean the city is unstated, which is a pass, not a mismatch.
_PLACEHOLDER_LOCATION = re.compile(r"^(\d+|multiple|various|several)\s+locations?$")


@dataclass(frozen=True)
class Verdict:
    """The outcome of the filter pass for one listing.

    `rule` is the machine-readable half -- it is what makes "which filter is
    eating everything" a query rather than a guess. `reason` is the half a human
    reads on the board.
    """

    passed: bool
    rule: str | None = None
    reason: str | None = None


PASSED = Verdict(passed=True)


@dataclass(frozen=True)
class Listing:
    """What the filters and the scorer need from a job row.

    A plain value object rather than `tracking.repo.Job`, so this module stays a
    pure function over data and the tests do not need a database to make a case.

    Named `Listing` and not `Posting` because `application.tailor.Posting`
    already exists and means something else -- the text a tailored resume is
    written against. Two classes with one name in one codebase is a bug waiting
    for a tired evening.
    """

    company: str
    title: str
    location: str | None = None
    work_arrangement: str | None = None
    description: str | None = None
    compensation_min: int | None = None
    compensation_max: int | None = None
    currency: str | None = None


def _cut(rule: str, reason: str) -> Verdict:
    return Verdict(passed=False, rule=rule, reason=reason)


def company_blocklisted(listing: Listing, profile: Profile) -> Verdict:
    """Compared on the normalized company, so "BMO" blocks "Bank of Montreal"."""
    if not profile.company_blocklist:
        return PASSED
    blocked = {normalize_company(name) for name in profile.company_blocklist}
    blocked.discard("")
    company = normalize_company(listing.company)
    if company and company in blocked:
        return _cut("company_blocklist", f"{listing.company} is on the company blocklist")
    return PASSED


def sponsorship_unavailable(requirements: Requirements, profile: Profile) -> Verdict:
    """Only a stated refusal cuts.

    `Requirements.sponsorship` is None for the overwhelming majority of
    postings, and the extractor's docstring is explicit that null means the
    posting did not say -- never that it said no. Treating silence as a refusal
    here would cut nearly everything.
    """
    if not profile.work_authorization.needs_sponsorship:
        return PASSED
    if requirements.sponsorship == "not_offered":
        return _cut(
            "sponsorship",
            "the posting states sponsorship is not offered and the profile needs it",
        )
    return PASSED


def seniority_mismatch(listing: Listing, profile: Profile) -> Verdict:
    """Cuts only on a level the posting actually stated.

    `seniority_of` returns whether the ladder placement was read or assumed, and
    an assumed one does not cut. Roughly half of bank postings carry no level
    marker at all, so filtering on the MID fallback would cut most of the board
    for saying nothing.
    """
    level, stated = seniority_of(listing.title, listing.description)
    if not stated:
        return PASSED
    targets: list[Seniority] = list(profile.target_seniority)
    distance = min(seniority_distance(level, target) for target in targets)
    if distance > MAX_SENIORITY_DISTANCE:
        wanted = ", ".join(str(t) for t in targets)
        return _cut(
            "seniority",
            f"reads as {level}, {distance} rungs from the closest target ({wanted})",
        )
    return PASSED


def arrangement_incompatible(listing: Listing, profile: Profile) -> Verdict:
    """An unknown arrangement passes; most postings never state one."""
    arrangement = (listing.work_arrangement or "").strip().lower()
    if not arrangement:
        return PASSED
    if arrangement not in profile.work_arrangements:
        accepted = ", ".join(profile.work_arrangements)
        return _cut("work_arrangement", f"is {arrangement}; the profile accepts {accepted}")
    return PASSED


def location_incompatible(listing: Listing, profile: Profile) -> Verdict:
    """City-level, and remote work is checked before the city is.

    A remote role in Vancouver is not a Vancouver job, so comparing its city
    against the profile's would cut it for a detail that does not apply. The
    arrangement decides first.
    """
    if (listing.work_arrangement or "").strip().lower() == "remote":
        if "remote" in profile.work_arrangements:
            return PASSED
        return _cut("location", "is remote; the profile does not accept remote work")

    city = normalize_location(listing.location)
    if not city or _PLACEHOLDER_LOCATION.match(city):
        return PASSED
    wanted = {normalize_location(place) for place in profile.locations}
    wanted.discard("")
    if not wanted or city in wanted:
        return PASSED
    return _cut(
        "location", f"is in {listing.location}; the profile wants {', '.join(sorted(wanted))}"
    )


def below_compensation_floor(listing: Listing, profile: Profile) -> Verdict:
    """Cuts only when the whole disclosed band sits under the floor.

    Three ways this declines to cut, all of them deliberate:

    - No floor set, or no band disclosed. An undisclosed band is the normal case
      and never disqualifies -- `core.profile.Compensation` says so directly.
    - The band's top is at or above the floor. "Entirely below" means the top,
      not the bottom.
    - The currencies disagree. Comparing 60,000 USD against a 70,000 CAD floor
      as though they were the same number is not a filter, it is a bug wearing
      one, and no conversion rate belongs in an offline tool.
    """
    floor = profile.compensation.floor
    if floor is None:
        return PASSED
    top = (
        listing.compensation_max
        if listing.compensation_max is not None
        else listing.compensation_min
    )
    if top is None:
        return PASSED
    listed_currency = (listing.currency or "").strip().upper()
    if listed_currency and listed_currency != profile.compensation.currency:
        return PASSED
    if top < floor:
        return _cut(
            "compensation",
            f"pays up to {top:,} {profile.compensation.currency}, below the {floor:,} floor",
        )
    return PASSED


def deal_breaker_present(listing: Listing, profile: Profile) -> Verdict:
    """Profile deal-breakers matched against the posting text on word boundaries.

    Substring matching would make "clearance" hit "clearances processed", which
    is fine, and "ai" hit "said", which is not. Word boundaries keep the obvious
    false positives out; anything subtler than that is a job for a human reading
    the stored reason.
    """
    if not profile.deal_breakers:
        return PASSED
    haystack = f"{listing.title}\n{listing.description or ''}".lower()
    for phrase in profile.deal_breakers:
        needle = phrase.strip().lower()
        if not needle:
            continue
        if re.search(rf"\b{re.escape(needle)}\b", haystack):
            return _cut("deal_breaker", f"mentions the deal-breaker {phrase!r}")
    return PASSED


def apply_filters(listing: Listing, requirements: Requirements, profile: Profile) -> Verdict:
    """Run every hard filter, returning the first cut.

    Ordered by cost and by certainty, cheapest and most certain first: a
    blocklisted company is a decision already made, while a deal-breaker match
    scans the whole posting body. Returning the first cut rather than collecting
    all of them is deliberate -- the stored reason should be the one that
    settles it, not a list to read through.
    """
    for verdict in (
        company_blocklisted(listing, profile),
        sponsorship_unavailable(requirements, profile),
        seniority_mismatch(listing, profile),
        arrangement_incompatible(listing, profile),
        location_incompatible(listing, profile),
        below_compensation_floor(listing, profile),
        deal_breaker_present(listing, profile),
    ):
        if not verdict.passed:
            return verdict
    return PASSED
