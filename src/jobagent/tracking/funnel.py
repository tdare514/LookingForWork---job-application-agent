"""Funnel analytics.

The payoff of the whole pipeline: everything before this produces data, and this
turns it into a decision about where the remaining weeks go.

Two things shape the design, and both come from the scale this actually runs at.

A personal job search produces dozens of applications, not thousands. So every
rate here carries its denominator, and anything computed from a handful of rows
is labelled as such rather than presented as a finding. "50% interview rate"
from two applications is noise wearing a suit.

And the report has to run on partial data from day one -- it will be run in week
one, when almost nothing has an outcome yet. An empty funnel is a valid answer,
not a crash.
"""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass, field
from datetime import UTC, date, datetime

from jobagent.tracking.board import State
from jobagent.tracking.followups import STALE_AFTER_DAYS
from jobagent.tracking.repo import Job

# Below this many observations, a percentage is not evidence. Chosen because a
# co-op season produces tens of applications: high enough that noise is obvious,
# low enough that the report still says something by mid-season.
SMALL_SAMPLE = 10

# The pipeline in order. Each stage counts rows that reached it *or beyond*,
# which is what makes stage-to-stage conversion meaningful.
#
# WAITING is deliberately NOT a stage. It means "applied, no reply yet" -- a
# sub-state of applied, not progress past it. Someone who goes straight from
# applied to an interview never passes through it, so treating it as a stage
# would put a near-empty denominator under the interview rate and distort every
# number above it.
FUNNEL_ORDER: tuple[State, ...] = (
    State.READY,
    State.APPLIED,
    State.INTERVIEW,
    State.OFFER,
)

# Reaching a later stage implies having passed the earlier ones.
_REACHED: dict[State, tuple[State, ...]] = {
    State.READY: (
        State.READY,
        State.APPLIED,
        State.WAITING,
        State.INTERVIEW,
        State.OFFER,
    ),
    State.APPLIED: (State.APPLIED, State.WAITING, State.INTERVIEW, State.OFFER),
    State.INTERVIEW: (State.INTERVIEW, State.OFFER),
    State.OFFER: (State.OFFER,),
}


@dataclass(frozen=True)
class Stage:
    state: State
    reached: int
    # Conversion from the previous stage. None at the top, or when the previous
    # stage had nobody in it -- a rate with a zero denominator is not 0%.
    conversion: float | None
    previous_total: int

    @property
    def thin(self) -> bool:
        return self.previous_total < SMALL_SAMPLE


@dataclass
class Report:
    total: int
    stages: list[Stage]
    rejected: int
    skipped: int
    stale: int
    # Rows not yet triaged into the funnel. Without this the top of the funnel
    # reads lower than the tracked total with no explanation.
    untriaged: int = 0
    by_company: list[tuple[str, int, int]] = field(default_factory=list)
    median_days_in_state: int | None = None
    # Why rows were skipped, most common first (#32). Aggregated rather than
    # listed: the question this answers is "am I ruling out the same thing over
    # and over", and thirty rows do not answer it as well as one count does.
    # Skips with no reason are counted separately rather than dropped, because
    # "I did not say" is itself worth seeing next to the ones that did.
    skip_reasons: list[tuple[str, int]] = field(default_factory=list)
    skipped_without_reason: int = 0

    @property
    def has_outcomes(self) -> bool:
        """Anything actually submitted yet? Drives whether rates mean anything."""
        applied = next((s.reached for s in self.stages if s.state is State.APPLIED), 0)
        return applied > 0

    @property
    def thin_overall(self) -> bool:
        return self.total < SMALL_SAMPLE


def _reached_count(jobs: list[Job], stage: State) -> int:
    wanted = set(_REACHED[stage])
    count = 0
    for job in jobs:
        try:
            state = State(job.state)
        except ValueError:
            continue
        # A rejection still passed through every stage before it. Without this,
        # rejections vanish from the funnel and conversion reads far too high.
        if state is State.REJECTED:
            continue
        if state in wanted:
            count += 1
    return count


def _days_in_state(job: Job, today: date) -> int | None:
    if not job.state_changed_at:
        return None
    try:
        when = datetime.fromisoformat(job.state_changed_at)
    except ValueError:
        return None
    if when.tzinfo is None:
        when = when.replace(tzinfo=UTC)
    return (today - when.date()).days


def build(jobs: list[Job], *, today: date | None = None) -> Report:
    """Compute the funnel. Safe on an empty or partial board."""
    today = today or datetime.now(UTC).date()
    counts = Counter(job.state for job in jobs)

    stages: list[Stage] = []
    previous: int | None = None
    for state in FUNNEL_ORDER:
        reached = _reached_count(jobs, state)
        conversion = None
        if previous is not None and previous > 0:
            conversion = reached / previous
        stages.append(
            Stage(
                state=state,
                reached=reached,
                conversion=conversion,
                previous_total=previous or 0,
            )
        )
        previous = reached

    # Per company: how many tracked, how many reached applied-or-beyond.
    per_company: dict[str, list[int]] = {}
    for job in jobs:
        row = per_company.setdefault(job.company, [0, 0])
        row[0] += 1
        try:
            state = State(job.state)
        except ValueError:
            continue
        if state in set(_REACHED[State.APPLIED]):
            row[1] += 1
    # Ranked by applications, not by rows tracked: which source produced real
    # applications is the question. Which produced the most clutter is not.
    by_company = sorted(
        ((name, tracked, applied) for name, (tracked, applied) in per_company.items()),
        key=lambda r: (-r[2], -r[1], r[0].lower()),
    )

    ages = sorted(d for d in (_days_in_state(j, today) for j in jobs) if d is not None)
    median = ages[len(ages) // 2] if ages else None

    reasons: dict[str, int] = {}
    unexplained = 0
    for job in jobs:
        if job.state != State.SKIPPED:
            continue
        reason = (job.state_reason or "").strip()
        if reason:
            reasons[reason] = reasons.get(reason, 0) + 1
        else:
            unexplained += 1

    return Report(
        total=len(jobs),
        stages=stages,
        rejected=counts.get(State.REJECTED, 0),
        skipped=counts.get(State.SKIPPED, 0),
        untriaged=counts.get(State.NEW, 0),
        # The same threshold the follow-up rules use, imported rather than
        # repeated: a report that called a row fresh while the board was
        # nagging about it would be two answers to one question.
        stale=sum(
            1 for j in jobs if (d := _days_in_state(j, today)) is not None and d >= STALE_AFTER_DAYS
        ),
        by_company=by_company,
        skip_reasons=sorted(reasons.items(), key=lambda kv: (-kv[1], kv[0].lower())),
        skipped_without_reason=unexplained,
        median_days_in_state=median,
    )
