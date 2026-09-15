"""Selection and ordering for a tailored resume variant.

Deliberately conservative: bullets are selected from the source of truth
**verbatim**, reordered by relevance to one posting, and trimmed to a budget.
Nothing is rewritten.

That is not a limitation to fix later -- it is the safest thing that is still
useful. Selection and ordering carry real signal (a posting asking for
requirements work should not open with a Python bullet) and carry zero
fabrication risk, because every word already appeared in the source. Rephrasing
toward a posting's vocabulary is the part that can quietly invent a claim, so it
comes later and goes through the same gate.

Rule-based throughout. No metered API call -- see AGENTS.md, Budget constraint.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from jobagent.application.resume import Accomplishment, Resume, Role
from jobagent.application.truthfulness import TailoredBullet, enforce

# Words carrying no signal when matching a posting against a resume.
_STOPWORD_TEXT = (
    "a ability able all an and any applicant applicants are as at be both by can candidate"
    "candidates could day days did do does each excellent experience few for from good great"
    "had has have how if in into is it its may might month months more most must new no not"
    "of on opportunity or other our over position role should skills so some strong such team"
    "teams than that the their them then these they this those to under we what when where"
    "which who whom will with work working works would year years yes you your"
)
STOPWORDS = frozenset(_STOPWORD_TEXT.split())

TOKEN = re.compile(r"[a-z][a-z0-9+#.-]{1,}")


@dataclass
class Posting:
    """A job posting, reduced to what matching needs."""

    company: str
    title: str
    description: str = ""

    def keywords(self) -> set[str]:
        text = f"{self.title} {self.description}".lower()
        return {t for t in TOKEN.findall(text) if t not in STOPWORDS and len(t) > 2}


@dataclass
class ScoredAccomplishment:
    accomplishment: Accomplishment
    score: float
    matched: set[str] = field(default_factory=set)


def score(acc: Accomplishment, posting: Posting) -> ScoredAccomplishment:
    """Overlap between what an accomplishment demonstrates and what a posting asks for.

    Declared skills weigh more than incidental word overlap: a posting that says
    "Jira" and an accomplishment that lists Jira as a skill is a real match; the
    same word appearing in prose is weaker evidence.
    """
    wanted = posting.keywords()

    skill_tokens: set[str] = set()
    for skill in acc.skills:
        skill_tokens |= {t for t in TOKEN.findall(skill.lower()) if t not in STOPWORDS}
    skill_hits = skill_tokens & wanted

    text_tokens = {t for t in TOKEN.findall(acc.text.lower()) if t not in STOPWORDS}
    text_hits = (text_tokens & wanted) - skill_hits

    total = 3.0 * len(skill_hits) + 1.0 * len(text_hits)

    # A measured accomplishment is more persuasive than an unmeasured one, so it
    # wins ties. It does not outrank genuine relevance.
    if acc.metric:
        total += 0.5

    return ScoredAccomplishment(acc, total, skill_hits | text_hits)


@dataclass
class TailoredRole:
    role: Role
    bullets: list[TailoredBullet]


@dataclass
class TailoredResume:
    posting: Posting
    roles: list[TailoredRole]
    selected: list[ScoredAccomplishment]
    dropped: list[ScoredAccomplishment]

    def bullets(self) -> list[TailoredBullet]:
        return [b for r in self.roles for b in r.bullets]


def tailor(
    resume: Resume,
    posting: Posting,
    *,
    max_bullets_per_role: int = 4,
    min_bullets_per_role: int = 2,
) -> TailoredResume:
    """Select and order bullets for one posting, then prove the result is truthful."""
    scored_by_id = {
        s.accomplishment.id: s for s in (score(a, posting) for a in resume.all_accomplishments())
    }

    roles: list[TailoredRole] = []
    selected: list[ScoredAccomplishment] = []
    dropped: list[ScoredAccomplishment] = []

    for role in resume.roles:
        ranked = sorted(
            (scored_by_id[a.id] for a in role.accomplishments),
            key=lambda s: (-s.score, s.accomplishment.id),
        )
        keep = ranked[:max_bullets_per_role]
        # Never strip a role to nothing: an employer with no bullets reads as a
        # gap, which is worse than a mildly off-target bullet.
        if len(keep) < min_bullets_per_role:
            keep = ranked[:min_bullets_per_role]

        selected.extend(keep)
        dropped.extend(ranked[len(keep) :])
        roles.append(
            TailoredRole(
                role=role,
                bullets=[
                    TailoredBullet(text=s.accomplishment.text, source_id=s.accomplishment.id)
                    for s in keep
                ],
            )
        )

    result = TailoredResume(posting=posting, roles=roles, selected=selected, dropped=dropped)

    # Selection alone cannot fabricate -- the text is verbatim. Enforce anyway:
    # this is the gate every future path must pass through, and a gate that is
    # only wired up later is a gate that is wired up wrong.
    enforce(result.bullets(), resume)
    return result
