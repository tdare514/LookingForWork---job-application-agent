"""Decomposed match scoring (#31).

The decomposition is the feature, not an implementation detail. A bare 0.63 is
not something you can argue with; "ranked 7th because skill overlap is 0.9 but
domain relevance is 0.2" tells you to either apply anyway or fix the profile.
So every component is stored with the weight it carried and a line saying what
it looked at.

**A component with no basis is dropped, not zeroed.** Most rows on the board
have no stored description until `fetch --details` has run, and no `posted_at`
at all -- Workday's list endpoint does not publish one. Scoring those as zero
would rank a posting last for a fetch that has not happened yet, and re-running
the fetch would reshuffle the whole board for reasons that have nothing to do
with the jobs. Instead the remaining weights rescale and the decomposition
records what was missing and why, which is the same habit the funnel report has
about denominators: say what the number is out of.

The cost of that choice is that totals are only strictly comparable between
postings scored on the same components, and `Score.scored_on` is what makes that
visible rather than hidden.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime
from typing import Any

from jobagent.core.profile import Profile
from jobagent.matching.extract import Requirements
from jobagent.matching.filters import Listing
from jobagent.matching.normalize import normalize_title, seniority_distance, seniority_of

# A required skill the posting asks for counts for three times what a preferred
# one does. Both matter -- a posting's "nice to have" list is where the real
# differentiators hide -- but missing a must-have is the one that gets a resume
# filtered by a human.
REQUIRED_SHARE = 0.75
PREFERRED_SHARE = 0.25

# Freshness half-life. `docs/job-matching.md`: "week-old postings are already
# crowded". Two weeks to half is the gentler reading of that, chosen because a
# co-op posting open for a month is still worth applying to.
FRESHNESS_HALF_LIFE_DAYS = 14.0

# Seniority fit by rungs of distance. Beyond one rung the hard filter has
# usually already cut it; this is what happens when the level was inferred and
# so could not be cut on.
_SENIORITY_FIT = {0: 1.0, 1: 0.5}


@dataclass(frozen=True)
class Component:
    """One dimension of the score, and why it came out that way.

    `value` of None means there was nothing to judge on. That is a different
    statement from 0.0, which means "judged, and it is a poor match", and
    keeping them distinct is the whole reason this dataclass exists instead of a
    plain dict of floats.
    """

    name: str
    value: float | None
    weight: float
    basis: str

    def as_dict(self) -> dict[str, Any]:
        return {
            "value": self.value,
            "weight": round(self.weight, 4),
            "basis": self.basis,
        }


@dataclass(frozen=True)
class Score:
    total: float
    components: tuple[Component, ...]

    @property
    def scored_on(self) -> tuple[str, ...]:
        """The components that actually carried a value."""
        return tuple(c.name for c in self.components if c.value is not None)

    @property
    def unavailable(self) -> tuple[str, ...]:
        return tuple(c.name for c in self.components if c.value is None)

    def as_dict(self) -> dict[str, Any]:
        return {
            "total": round(self.total, 4),
            "scored_on": list(self.scored_on),
            "unavailable": list(self.unavailable),
            "components": {c.name: c.as_dict() for c in self.components},
        }


def _tokens(text: str) -> set[str]:
    return {token for token in normalize_title(text).split() if len(token) > 2}


def _skill_overlap(requirements: Requirements, profile: Profile, was_read: bool) -> Component:
    """Posting skills against profile skills, required weighted above preferred.

    Measured as the share of what the *posting* asks for that the profile
    covers, not the other way round. A profile listing twenty skills should not
    score badly against a posting that needs three of them.

    `was_read` separates two cases that look identical in `Requirements` and are
    not remotely the same thing:

    - **Nobody looked.** No description has been fetched, or one has but the
      extractor has not been run over it. No skill could have been found.
      Genuinely unknown, and dropped from the total.
    - **Read it, found nothing.** A full posting body, run through the
      extractor, naming none of the profile's skills. That is a measurement,
      and its result is zero.

    Conflating them was a real bug caught on the fixture set: a TD contact
    centre role with a 12,000-character description mentioning no analytical
    skill was scored as "unknown", dropped from the total, and so outranked an
    RBC risk intern posting that had actually been measured and scored 0.25.
    Knowing less about a job should never flatter it.
    """
    have = {s.strip().lower() for s in profile.must_have_skills + profile.nice_to_have_skills}
    have.discard("")
    required = tuple(s.lower() for s in requirements.required_skills)
    preferred = tuple(s.lower() for s in requirements.preferred_skills)

    if not required and not preferred:
        if not was_read:
            return Component(
                "skill_overlap",
                None,
                0.0,
                "nothing read yet -- run `fetch --details` and `extract`",
            )
        return Component(
            "skill_overlap",
            0.0,
            0.0,
            "the description names none of the profile's skills",
        )

    parts: list[tuple[float, float]] = []  # (share of this group matched, its weight)
    detail: list[str] = []
    if required:
        hit = sum(1 for skill in required if skill in have)
        parts.append((hit / len(required), REQUIRED_SHARE if preferred else 1.0))
        detail.append(f"{hit}/{len(required)} required")
    if preferred:
        hit = sum(1 for skill in preferred if skill in have)
        parts.append((hit / len(preferred), PREFERRED_SHARE if required else 1.0))
        detail.append(f"{hit}/{len(preferred)} preferred")

    weight_total = sum(w for _, w in parts)
    value = sum(share * w for share, w in parts) / weight_total
    return Component("skill_overlap", value, 0.0, ", ".join(detail) + " matched by the profile")


def _seniority_fit(listing: Listing, profile: Profile) -> Component:
    level, stated = seniority_of(listing.title, listing.description)
    distance = min(seniority_distance(level, target) for target in profile.target_seniority)
    value = _SENIORITY_FIT.get(distance, 0.0)
    read = "stated" if stated else "assumed -- the posting carries no level marker"
    return Component(
        "seniority_fit", value, 0.0, f"reads as {level} ({read}), {distance} rungs off"
    )


def _domain_relevance(listing: Listing, profile: Profile) -> Component:
    """Title vocabulary against the profile's target titles.

    Named `domain_relevance` because that is the weight the profile exposes and
    the name `docs/job-matching.md` uses. What it actually measures is narrower
    than the design doc's "industry and problem-domain overlap with history" --
    there is no industry field on the profile to read, so this compares the
    words. The basis string says so rather than letting the name imply more.
    """
    wanted: set[str] = set()
    for title in profile.target_titles:
        wanted |= _tokens(title)
    listing_tokens = _tokens(listing.title)
    if not wanted or not listing_tokens:
        return Component("domain_relevance", None, 0.0, "no title vocabulary to compare")
    shared = wanted & listing_tokens
    value = len(shared) / len(listing_tokens)
    words = ", ".join(sorted(shared)) if shared else "nothing"
    return Component(
        "domain_relevance",
        value,
        0.0,
        f"title shares {words} with the target titles",
    )


def _freshness(posted_at: str | None, today: date) -> Component:
    """Decay from `posted_at`, and from nothing else.

    `first_seen_at` is deliberately not a fallback. It records when this tool
    first looked, so a posting that has been open for two months would read as
    brand new on the day it is first fetched -- a number that is not wrong so
    much as about us rather than the job.
    """
    if not posted_at:
        return Component("freshness", None, 0.0, "the posting does not publish a date")
    try:
        posted = datetime.fromisoformat(posted_at.replace("Z", "+00:00")).date()
    except ValueError:
        return Component("freshness", None, 0.0, f"unparseable posted_at {posted_at!r}")
    age = (today - posted).days
    if age < 0:
        return Component("freshness", 1.0, 0.0, f"posted {posted}, in the future -- treated as new")
    value = 0.5 ** (age / FRESHNESS_HALF_LIFE_DAYS)
    return Component("freshness", value, 0.0, f"posted {posted}, {age} days ago")


def _semantic_fit() -> Component:
    """Always unavailable, and recorded anyway.

    `core.profile.Weights` refuses a non-zero weight for this, because no local
    embedding backend has been decided and a metered embeddings API is out of
    scope. Listing it here as an explicit absence keeps the decomposition
    complete: a reader who knows the design doc's five components should see
    five, with one of them saying why it is empty, rather than four and a
    silence.
    """
    return Component(
        "semantic_fit",
        None,
        0.0,
        "no local embedding model; a metered API is out of scope (AGENTS.md)",
    )


def score(
    listing: Listing,
    requirements: Requirements,
    profile: Profile,
    posted_at: str | None = None,
    today: date | None = None,
    extracted: bool = True,
) -> Score:
    """Score one listing, keeping every component and its weight.

    Weights come from the profile and are renormalized twice: once by
    `Weights.normalized()` so the numbers are relative importance rather than
    fractions the user had to make sum to one, and once here over the components
    that actually had a value.

    `extracted` says whether the extractor has actually been run over this
    posting. It defaults to True because every caller that builds `Requirements`
    from `extract()` has, by definition, extracted; the caller that reads a
    stored extraction has to pass False when there is none, or an empty
    `Requirements` is mistaken for a posting that genuinely asks for nothing.
    """
    day = today or date.today()
    weights = profile.weights.normalized()

    # Built in two passes. Each component function decides its own value and
    # basis and leaves the weight at zero, because what a component measures has
    # nothing to do with how much the user cares about it -- and a function that
    # took the weight in order to ignore it would invite someone to start using
    # it. The weights are attached here, in the one place that reads the profile.
    measured = (
        _skill_overlap(requirements, profile, extracted and bool(listing.description)),
        _seniority_fit(listing, profile),
        _domain_relevance(listing, profile),
        _freshness(posted_at, day),
        _semantic_fit(),
    )
    components = tuple(
        Component(c.name, c.value, weights.get(c.name, 0.0), c.basis) for c in measured
    )

    # A weight of zero means the user switched the component off, and a switched
    # off component must not creep back into the total. Only components with
    # both a value and a weight contribute.
    contributing = [c for c in components if c.value is not None and c.weight > 0]
    weight_total = sum(c.weight for c in contributing)
    total = (
        sum(c.value * c.weight for c in contributing if c.value is not None) / weight_total
        if weight_total > 0
        else 0.0
    )
    return Score(total=total, components=components)
