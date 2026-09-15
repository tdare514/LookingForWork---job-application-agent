"""Follow-up rules.

Follow-ups measurably move applications forward, and they are exactly what gets
forgotten in week nine with thirty applications in flight and no memory of which
ones are overdue.

Driven by time in state, because that is the only thing the tracker knows for
certain. The agent drafts and surfaces; sending is always the user's action --
the agent has no mail access and is not getting any (#39).
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, date, datetime

from jobagent.tracking.board import State
from jobagent.tracking.repo import Job

# Thresholds in days. Configurable later; these are the defaults that match how
# co-op hiring actually moves.
DEFAULT_RULES: dict[State, int] = {
    State.APPLIED: 10,  # submitted, no acknowledgement
    State.WAITING: 10,  # acknowledged, then silence
    State.INTERVIEW: 5,  # post-interview, no word
}

# Any row untouched this long is stale, whatever state it claims.
STALE_AFTER_DAYS = 30


@dataclass(frozen=True)
class FollowUp:
    job: Job
    days_in_state: int
    reason: str
    stale: bool = False


def _days_since(stamp: str | None, today: date) -> int | None:
    if not stamp:
        return None
    try:
        when = datetime.fromisoformat(stamp)
    except ValueError:
        return None
    if when.tzinfo is None:
        when = when.replace(tzinfo=UTC)
    return (today - when.date()).days


def due(
    jobs: list[Job],
    *,
    today: date | None = None,
    rules: dict[State, int] | None = None,
) -> list[FollowUp]:
    """Which rows want action today, most overdue first."""
    today = today or datetime.now(UTC).date()
    rules = rules or DEFAULT_RULES

    out: list[FollowUp] = []
    for job in jobs:
        days = _days_since(job.state_changed_at, today)
        if days is None:
            continue

        try:
            state = State(job.state)
        except ValueError:
            continue

        # Terminal states are done. Chasing a rejection is not a follow-up.
        if state in {State.REJECTED, State.SKIPPED, State.OFFER}:
            continue

        if days >= STALE_AFTER_DAYS:
            out.append(
                FollowUp(
                    job, days, f"No movement in {days} days — mark it stale or chase it.", True
                )
            )
            continue

        threshold = rules.get(state)
        if threshold is not None and days >= threshold:
            out.append(FollowUp(job, days, _reason_for(state, days)))

    out.sort(key=lambda f: -f.days_in_state)
    return out


def _reason_for(state: State, days: int) -> str:
    if state is State.APPLIED:
        return f"Submitted {days} days ago with no acknowledgement — follow up."
    if state is State.WAITING:
        return f"Waiting {days} days — check in."
    if state is State.INTERVIEW:
        return f"{days} days since the interview — send a note."
    return f"{days} days in {state.value}."
