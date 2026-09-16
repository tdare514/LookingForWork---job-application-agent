"""Importing a triaged shortlist onto the board.

Named `leads` and not `shortlist` because `tracking.shortlist` already means
something else: the ranked list this tool builds from its own stored scores
(#32). What arrives here is the opposite direction -- judgements formed by an
outside search, which this tool did not compute and must not pretend it did.
Two modules called shortlist, one producing a ranking and one consuming
somebody else's, is a confusion waiting for a tired evening.

The daily search that finds these roles runs outside this tool. What it produces
is not a list of postings -- it is a list of *judgements*: a fit score, a verdict,
why the role fits, and what is missing. Retyping that as `jobagent add` lines
keeps the company and the title and throws away the reason, which is the only
part that tells you which of eleven rows to open first on a Tuesday night.

So this imports the judgement with the row, under three rules.

**Attributed and dated.** A fit score from another tool is an opinion, and in a
month it is a stale opinion. Every imported note carries its source and the date
it was formed, so nobody mistakes it for something this tool worked out.

**It never feeds the score.** `jobagent score` is rule-based and explains itself
component by component. Blending an outside number into that total would make
the decomposition a lie. The two numbers sit next to each other and the human
compares them.

**It never walks a row backwards.** A role already applied to, waiting, or
interviewing has moved past anything a search result knows about. An import
saying "apply" leaves it exactly where it is.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import date
from enum import StrEnum
from pathlib import Path

import yaml
from pydantic import BaseModel, Field, field_validator

from jobagent.tracking.board import State
from jobagent.tracking.repo import BoardRepo, Job

# The notes this writes are fenced, so re-importing replaces its own block and
# leaves anything typed by hand alone. Losing a note about a recruiter's name to
# a routine re-import would be a small disaster of exactly the avoidable kind.
NOTE_MARKER = "[imported shortlist]"

_ISO_DATE = re.compile(r"^\d{4}-\d{2}-\d{2}$")

# States that mean the human has already acted. An outside search result knows
# nothing that should override these.
SETTLED: frozenset[State] = frozenset(
    {State.APPLIED, State.WAITING, State.INTERVIEW, State.OFFER, State.REJECTED}
)


def _as_iso_date(value: object, field: str) -> str | None:
    """Accept what YAML actually produces for a date.

    An unquoted `2026-09-20` comes back from `yaml.safe_load` as a `date`, not a
    string -- so the most natural way to write the file would otherwise fail
    with "input should be a valid string", which tells the user nothing about
    what to do. Both spellings are accepted and normalised to one.
    """
    if value is None:
        return None
    if isinstance(value, date):
        return value.isoformat()
    if isinstance(value, str):
        text = value.strip()
        if _ISO_DATE.match(text):
            return text
        raise ValueError(f"{field} must be YYYY-MM-DD, got {value!r}")
    raise ValueError(f"{field} must be a date written as YYYY-MM-DD, got {type(value).__name__}")


class Verdict(StrEnum):
    APPLY = "apply"
    MAYBE = "maybe"
    SKIP = "skip"


# What a verdict means on the board. `maybe` deliberately lands in NEW rather
# than READY: "worth a look" is not "needs you today", and a board where
# everything is yellow is a board with no signal in it.
VERDICT_STATE: dict[Verdict, State] = {
    Verdict.APPLY: State.READY,
    Verdict.MAYBE: State.NEW,
    Verdict.SKIP: State.SKIPPED,
}


class Lead(BaseModel):
    company: str = Field(min_length=1)
    title: str = Field(min_length=1)
    verdict: Verdict
    location: str | None = None
    url: str | None = None
    deadline: str | None = None
    # A score out of ten, as the searching tool reported it. Optional: a lead
    # can be worth importing without one.
    fit: float | None = Field(default=None, ge=0, le=10)
    why: str = ""
    gaps: str = ""

    @field_validator("deadline", mode="before")
    @classmethod
    def _iso_date(cls, v: object) -> str | None:
        return _as_iso_date(v, "deadline")

    @field_validator("company", "title")
    @classmethod
    def _not_blank(cls, v: str) -> str:
        if not v.strip():
            raise ValueError("cannot be blank")
        return v.strip()


class Shortlist(BaseModel):
    """One run of an outside search, with the judgements it produced."""

    source: str = Field(min_length=1, description="What produced this, e.g. chatgpt-daily-search.")
    retrieved: str = Field(description="The date these judgements were formed, YYYY-MM-DD.")
    leads: list[Lead] = Field(min_length=1)

    @field_validator("retrieved", mode="before")
    @classmethod
    def _iso_date(cls, v: object) -> str:
        parsed = _as_iso_date(v, "retrieved")
        if parsed is None:
            raise ValueError("retrieved is required, as YYYY-MM-DD")
        return parsed


@dataclass
class Outcome:
    """What happened to one lead. Reported, not logged and forgotten."""

    company: str
    title: str
    action: str  # added | updated | unchanged | left alone
    detail: str = ""


@dataclass
class Report:
    outcomes: list[Outcome] = field(default_factory=list)

    def count(self, action: str) -> int:
        return sum(1 for o in self.outcomes if o.action == action)

    @property
    def added(self) -> int:
        return self.count("added")

    @property
    def updated(self) -> int:
        return self.count("updated")

    @property
    def left_alone(self) -> int:
        return self.count("left alone")


def load_file(path: Path) -> Shortlist:
    """Validate a shortlist file. A malformed one writes nothing."""
    if not path.is_file():
        raise FileNotFoundError(f"no shortlist at {path}")
    raw = yaml.safe_load(path.read_text())
    if not isinstance(raw, dict):
        raise ValueError(f"{path} does not contain a YAML mapping")
    return Shortlist.model_validate(raw)


def note_block(lead: Lead, shortlist: Shortlist) -> str:
    """The fenced note an import owns, attributed and dated.

    The date is the point. In three weeks "fit 9.8" with no date reads as a
    current judgement about a posting that may have closed.
    """
    fit = f"fit {lead.fit:g}/10 — " if lead.fit is not None else ""
    lines = [f"{NOTE_MARKER} {shortlist.source}, {shortlist.retrieved}", f"{fit}{lead.verdict}"]
    if lead.why:
        lines.append(f"Why: {lead.why.strip()}")
    if lead.gaps:
        lines.append(f"Gaps: {lead.gaps.strip()}")
    return "\n".join(lines)


def merge_notes(existing: str | None, block: str) -> str:
    """Replace this importer's own block, leave everything else untouched.

    Hand-typed notes are the most valuable text on the board -- a recruiter's
    name, a referral, what was said on a call. An importer that overwrites them
    is worse than one that writes nothing.
    """
    current = (existing or "").strip()
    if not current:
        return block
    kept = [
        part.strip()
        for part in current.split(NOTE_MARKER)[:1]
        if part.strip()  # everything before our marker is theirs
    ]
    return "\n\n".join([*kept, block])


def apply_to_board(repo: BoardRepo, shortlist: Shortlist, *, dry_run: bool = False) -> Report:
    """Put a shortlist on the board, reporting what it did to each row.

    `dry_run` computes the same report and writes nothing, because this is the
    one command in the tool that writes somebody else's judgement into a live
    personal board.
    """
    report = Report()
    for lead in shortlist.leads:
        existing = _find(repo, lead)
        wanted = VERDICT_STATE[lead.verdict]
        block = note_block(lead, shortlist)

        if existing is None:
            if not dry_run:
                job, _created = repo.add(
                    company=lead.company,
                    title=lead.title,
                    url=lead.url,
                    location=lead.location,
                    deadline=lead.deadline,
                    state=wanted,
                    source=f"shortlist:{shortlist.source}",
                )
                repo.set_notes(job.id, block)
            report.outcomes.append(Outcome(lead.company, lead.title, "added", str(wanted)))
            continue

        current = State(existing.state)
        if current in SETTLED:
            report.outcomes.append(
                Outcome(
                    lead.company,
                    lead.title,
                    "left alone",
                    f"already {current}; an import does not walk that back",
                )
            )
            continue

        merged = merge_notes(existing.notes, block)
        changed = merged != (existing.notes or "") or current is not wanted
        if not dry_run:
            repo.set_notes(existing.id, merged)
            if current is not wanted:
                repo.set_state(existing.id, wanted)
        report.outcomes.append(
            Outcome(
                lead.company,
                lead.title,
                "updated" if changed else "unchanged",
                str(wanted) if current is not wanted else "",
            )
        )
    return report


def _find(repo: BoardRepo, lead: Lead) -> Job | None:
    """The row this lead is already on the board as, via the board's own matcher."""
    return repo.find(lead.company, lead.title, lead.location)
