"""Decomposed scoring.

The decomposition is the feature. A bare 0.63 is not arguable; "ranked seventh
because skill overlap is 0.9 and domain relevance is 0.2" tells the user
something they can act on -- including that the score is wrong, which is the
most useful thing a score can say in week one.

So every component is computed separately, stored separately, and printed
separately. Nothing here rolls up until the last step, and the weights that do
the rolling up come from the profile rather than from constants: someone
changing domains wants domain relevance near zero and the system should not
argue with them.

Every component is rule-based. ADR 0008 records why there is no model call in
this path, and `Component.SEMANTIC_FIT` is the one the rules cannot do -- it is
reported as absent rather than faked, and the profile refuses to weight it.

A component returns a number in [0, 1] **and a sentence**. The sentence is not
decoration: "skill overlap 0.4" invites an argument that "matched sql, excel;
missed sas, risk management" settles.
"""

from __future__ import annotations

import math
import re
from dataclasses import dataclass
from datetime import UTC, date, datetime
from enum import StrEnum

from jobagent.core.profile import Profile
from jobagent.core.vocabulary import Seniority
from jobagent.matching.candidate import Candidate
from jobagent.matching.extract import canonical_skills
from jobagent.matching.filters import posting_seniority
from jobagent.matching.normalize import seniority_distance

# A component with nothing to go on scores here rather than at zero. Zero is a
# claim -- "this posting does not match" -- and an unstated fact is not evidence
# for it. Half says "unknown", and the stored reason says which.
UNKNOWN = 0.5

# A required skill counts for this much more than a preferred one. The posting
# says "must-have" and "nice-to-have" for a reason, and flattening them makes a
# posting asking for one thing you have look like one asking for five.
REQUIRED_WEIGHT = 2.0

# Freshness halves roughly every two weeks. A month-old posting is not dead, but
# it has been read by everyone; the decay is gentle because a co-op posting with
# a September deadline is worth applying to on the last day.
FRESHNESS_HALF_LIFE_DAYS = 14.0

_WORD = re.compile(r"[a-z][a-z+#.]{2,}")
_STOPWORDS = frozenset(
    [
        "the",
        "and",
        "for",
        "with",
        "you",
        "your",
        "our",
        "will",
        "are",
        "that",
        "this",
        "have",
        "has",
        "not",
        "who",
        "which",
        "from",
        "them",
        "their",
        "about",
        "able",
        "would",
        "could",
        "should",
        "work",
        "working",
        "role",
        "team",
        "teams",
        "business",
        "company",
        "opportunity",
        "opportunities",
        "experience",
        "experiences",
        "year",
        "years",
        "strong",
        "ability",
        "excellent",
        "including",
        "include",
        "includes",
        "such",
        "other",
        "others",
        "within",
        "across",
        "support",
        "supporting",
        "help",
        "helping",
        "new",
        "using",
        "use",
        "used",
        "per",
        "via",
        "job",
        "jobs",
        "position",
        "positions",
        "candidate",
        "candidates",
        "apply",
        "application",
        "applications",
    ]
)


class Component(StrEnum):
    SKILL_OVERLAP = "skill_overlap"
    SENIORITY_FIT = "seniority_fit"
    DOMAIN_RELEVANCE = "domain_relevance"
    FRESHNESS = "freshness"
    SEMANTIC_FIT = "semantic_fit"


@dataclass(frozen=True)
class Part:
    """One component's verdict: the number, and why it is that number."""

    component: Component
    value: float
    reason: str

    def as_dict(self) -> dict[str, object]:
        return {"value": round(self.value, 4), "reason": self.reason}


@dataclass(frozen=True)
class Score:
    job_id: int
    total: float
    parts: tuple[Part, ...]

    def component(self, name: Component) -> Part:
        return next(p for p in self.parts if p.component is name)

    def as_dict(self) -> dict[str, object]:
        return {str(p.component): p.as_dict() for p in self.parts}

    def explain(self) -> str:
        """One line naming what carried the score and what dragged it down.

        Deliberately mentions the weakest component as well as the strongest:
        a ranking that only ever explains its enthusiasm is a sales pitch.
        """
        scored = [p for p in self.parts if p.component is not Component.SEMANTIC_FIT]
        best = max(scored, key=lambda p: p.value)
        worst = min(scored, key=lambda p: p.value)
        if best.component is worst.component:
            return f"{best.component.value.replace('_', ' ')}: {best.reason}"
        strongest = best.component.value.replace("_", " ")
        weakest = worst.component.value.replace("_", " ")
        return (
            f"strongest {strongest} ({best.value:.2f}) — {best.reason}; "
            f"weakest {weakest} ({worst.value:.2f}) — {worst.reason}"
        )


def _tokens(text: str) -> set[str]:
    return {w for w in _WORD.findall(text.lower()) if w not in _STOPWORDS}


def skill_overlap(candidate: Candidate, profile: Profile) -> Part:
    """Required and preferred skills against the profile's, required weighted up.

    Both sides go through the extractor's own vocabulary, so "Power BI" in a
    profile and "powerbi" in a posting are one skill. Comparing raw strings
    would score zero on exactly the matches that matter.
    """
    required = set(candidate.requirements.required_skills)
    preferred = set(candidate.requirements.preferred_skills)
    if not required and not preferred:
        return Part(
            Component.SKILL_OVERLAP,
            UNKNOWN,
            "posting lists no skills the rules recognise",
        )

    mine = set(canonical_skills(" ".join(profile.must_have_skills + profile.nice_to_have_skills)))
    hit_required = required & mine
    hit_preferred = preferred & mine
    earned = REQUIRED_WEIGHT * len(hit_required) + len(hit_preferred)
    possible = REQUIRED_WEIGHT * len(required) + len(preferred)
    value = earned / possible if possible else UNKNOWN

    matched = sorted(hit_required | hit_preferred)
    missed = sorted((required | preferred) - mine)
    reason = f"matched {', '.join(matched) or 'nothing'}"
    if missed:
        reason += f"; missed {', '.join(missed)}"
    return Part(Component.SKILL_OVERLAP, value, reason)


def seniority_fit(candidate: Candidate, profile: Profile) -> Part:
    """Distance on the shared ladder, not the source's title inflation."""
    rung: Seniority = posting_seniority(candidate)
    distance = min(seniority_distance(rung, wanted) for wanted in profile.target_seniority)
    # 0 rungs is a match, 1 is a stretch worth reading, and anything beyond has
    # already been cut by the hard filter -- so the curve only needs three points.
    value = {0: 1.0, 1: 0.5}.get(distance, 0.0)
    wanted = ", ".join(str(s) for s in profile.target_seniority)
    reason = f"posting reads as {rung}, target is {wanted}"
    return Part(Component.SENIORITY_FIT, value, reason)


def domain_relevance(candidate: Candidate, profile: Profile) -> Part:
    """Vocabulary shared between the posting and what the user says they do.

    This is a proxy and is labelled as one. Real domain relevance means industry
    and problem-domain overlap; what is computed here is how much of the
    profile's own language -- its narrative and the titles it targets -- turns up
    in the posting. It catches a credit-risk posting for someone who writes
    about risk, and it misses a synonym, which is precisely the gap
    `semantic_fit` exists to fill and cannot yet.
    """
    vocabulary = _tokens(" ".join([profile.narrative, *profile.target_titles]))
    if not vocabulary:
        return Part(
            Component.DOMAIN_RELEVANCE,
            UNKNOWN,
            "profile states no narrative to compare against",
        )
    posting = _tokens(candidate.text)
    if not posting:
        return Part(Component.DOMAIN_RELEVANCE, UNKNOWN, "posting has no text to compare")

    shared = vocabulary & posting
    # Share of the profile's vocabulary that appears, not of the posting's: a
    # long posting should not be penalised for containing words about benefits.
    value = len(shared) / len(vocabulary)
    # Overlap above a third of a personal narrative is already a strong signal;
    # scaling to that keeps the component usefully spread instead of bunched
    # near zero, where nothing distinguishes seventh place from twentieth.
    value = min(1.0, value * 3)
    top = ", ".join(sorted(shared)[:6]) or "nothing"
    return Part(Component.DOMAIN_RELEVANCE, value, f"shares {len(shared)} terms: {top}")


def freshness(candidate: Candidate, *, today: date | None = None) -> Part:
    """Decay from when the posting appeared.

    Falls back to when this tool first saw the row, which is later than the real
    posting date and therefore flatters an old posting. Stated in the reason
    rather than corrected for, because the correction would be a guess.
    """
    now = today or datetime.now(UTC).date()
    stamp = candidate.posted_at or candidate.first_seen_at
    if not stamp:
        return Part(Component.FRESHNESS, UNKNOWN, "no posting date")
    try:
        when = datetime.fromisoformat(stamp)
    except ValueError:
        return Part(Component.FRESHNESS, UNKNOWN, f"unreadable date {stamp!r}")
    days = max(0, (now - when.date()).days)
    value = math.pow(0.5, days / FRESHNESS_HALF_LIFE_DAYS)
    source = "posted" if candidate.posted_at else "first seen"
    return Part(Component.FRESHNESS, value, f"{days} days since {source}")


def semantic_fit() -> Part:
    """Always absent, deliberately, and stored so the gap is visible.

    It needs an embedding model. A metered embeddings API is out of scope under
    the budget constraint, and no local backend has been decided (#31), so the
    profile refuses to weight this above zero. Reporting it as 0 with a reason
    beats omitting it: a reader comparing this output to `docs/job-matching.md`
    should be able to see which component is missing and why.
    """
    return Part(Component.SEMANTIC_FIT, 0.0, "not scored: no local embedding backend")


def score(candidate: Candidate, profile: Profile, *, today: date | None = None) -> Score:
    """Every component, then one weighted total.

    The weights are normalized first, so a profile written in percentages, in
    fractions, or in 1-to-10 preferences all mean the same thing.
    """
    parts = (
        skill_overlap(candidate, profile),
        seniority_fit(candidate, profile),
        domain_relevance(candidate, profile),
        freshness(candidate, today=today),
        semantic_fit(),
    )
    weights = profile.weights.normalized()
    total = sum(part.value * weights[str(part.component)] for part in parts)
    return Score(candidate.job_id, total, parts)
