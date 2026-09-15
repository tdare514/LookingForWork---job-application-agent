"""The truthfulness check.

Tailoring may select, reorder and rephrase facts from the resume source of
truth. It may not add one. This module is what makes that a guarantee rather
than a hope.

The failure mode it exists for is not the obvious lie -- nobody invents an
employer. It is quiet promotion:

    source:  "Conducted data validation across 100+ tracked work items"
    output:  "Owned data quality across the project portfolio"

That reads better, survives a skim, and has silently added both a scope claim
(owned) and a breadth claim (portfolio) that are not in the source. It is
exactly the sentence an interviewer probes.

Every finding here is a refusal, not a warning. A package with one unsupported
claim does not ship.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from jobagent.application.resume import Accomplishment, Resume

# Words that assert a level of ownership. Ranked: a bullet may state the scope
# its source holds or less, never more.
SCOPE_RANK: dict[str, int] = {"contributed": 0, "owned": 1, "led": 2}

SCOPE_WORDS: dict[str, tuple[str, ...]] = {
    "led": ("led", "leading", "headed", "directed", "spearheaded", "drove", "ran"),
    "owned": ("owned", "owning", "responsible for", "accountable for"),
}

# Claims of breadth. Cheap to write, expensive to defend.
BREADTH_PATTERNS: tuple[str, ...] = (
    r"\bacross the (platform|company|organi[sz]ation|business|portfolio)\b",
    r"\bcompany-?wide\b",
    r"\borgani[sz]ation-?wide\b",
    r"\bend-to-end ownership\b",
    r"\bfrom scratch\b",
)

NUMBER = re.compile(r"\d[\d,.]*\+?%?")


@dataclass(frozen=True)
class Violation:
    kind: str
    claim: str
    detail: str

    def __str__(self) -> str:
        return f"[{self.kind}] {self.detail}  ->  {self.claim!r}"


@dataclass(frozen=True)
class TailoredBullet:
    """A bullet in a tailored variant, bound to the fact it came from."""

    text: str
    source_id: str


def _numbers(text: str) -> set[str]:
    return {m.group(0).rstrip(".").replace(",", "") for m in NUMBER.finditer(text)}


def _claimed_scope(text: str) -> str | None:
    lowered = text.lower()
    for scope in ("led", "owned"):
        if any(re.search(rf"\b{re.escape(w)}\b", lowered) for w in SCOPE_WORDS[scope]):
            return scope
    return None


def check_bullet(bullet: TailoredBullet, source: Accomplishment) -> list[Violation]:
    """Every way a rephrase can quietly become a fabrication."""
    violations: list[Violation] = []
    source_text = f"{source.text} {source.metric or ''}"

    # 1. Numbers may be dropped, never invented or changed. A number that is not
    #    in the source is the most checkable kind of lie.
    invented = _numbers(bullet.text) - _numbers(source_text)
    for number in sorted(invented):
        violations.append(
            Violation(
                "invented-number",
                bullet.text,
                f"{number!r} does not appear in the source accomplishment",
            )
        )

    # 2. Scope may be stated at or below what was actually held.
    claimed = _claimed_scope(bullet.text)
    if claimed is not None and SCOPE_RANK[claimed] > SCOPE_RANK[source.scope]:
        violations.append(
            Violation(
                "scope-inflation",
                bullet.text,
                f"claims {claimed!r} but the source records {source.scope!r}",
            )
        )

    # 3. Breadth claims must be present in the source, not added for effect.
    lowered_source = source_text.lower()
    for pattern in BREADTH_PATTERNS:
        match = re.search(pattern, bullet.text.lower())
        if match and not re.search(pattern, lowered_source):
            violations.append(
                Violation(
                    "invented-breadth",
                    bullet.text,
                    f"{match.group(0)!r} is not supported by the source",
                )
            )

    return violations


def check(bullets: list[TailoredBullet], resume: Resume) -> list[Violation]:
    """Validate a whole tailored variant against the source of truth."""
    violations: list[Violation] = []
    for bullet in bullets:
        source = resume.accomplishment(bullet.source_id)
        if source is None:
            # An unbound bullet is the worst case: prose with no fact behind it.
            violations.append(
                Violation(
                    "unsourced",
                    bullet.text,
                    f"source_id {bullet.source_id!r} is not in the resume",
                )
            )
            continue
        violations.extend(check_bullet(bullet, source))
    return violations


class TruthfulnessError(RuntimeError):
    """Raised when a tailored variant makes a claim the resume does not support."""

    def __init__(self, violations: list[Violation]) -> None:
        self.violations = violations
        body = "\n  ".join(str(v) for v in violations)
        super().__init__(f"{len(violations)} unsupported claim(s):\n  {body}")


def enforce(bullets: list[TailoredBullet], resume: Resume) -> None:
    """Refuse the variant if anything is unsupported. No warn-and-continue."""
    violations = check(bullets, resume)
    if violations:
        raise TruthfulnessError(violations)
