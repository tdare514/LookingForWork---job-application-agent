"""Board state model.

Traffic lights, because at a glance the only questions that matter are "what have
I sent", "what is dead", and "what needs me today".
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum


class State(StrEnum):
    NEW = "new"  # found, not triaged
    READY = "ready"  # triaged in, needs action from me
    APPLIED = "applied"
    WAITING = "waiting"  # applied, no response yet
    INTERVIEW = "interview"
    OFFER = "offer"
    REJECTED = "rejected"
    SKIPPED = "skipped"


@dataclass(frozen=True)
class Light:
    """How a state renders on the board."""

    dot: str
    colour: str
    label: str


GREEN = "green"
YELLOW = "yellow"
RED = "red"
GREY = "grey58"

LIGHTS: dict[State, Light] = {
    State.NEW: Light("○", GREY, "New"),
    State.READY: Light("●", YELLOW, "Needs you"),
    State.APPLIED: Light("●", GREEN, "Applied"),
    State.WAITING: Light("●", YELLOW, "Waiting"),
    State.INTERVIEW: Light("●", GREEN, "Interview"),
    State.OFFER: Light("★", GREEN, "Offer"),
    State.REJECTED: Light("●", RED, "Rejected"),
    State.SKIPPED: Light("○", GREY, "Skipped"),
}

# Ordering for the board: things needing action float to the top, dead rows sink.
SORT_RANK: dict[State, int] = {
    State.READY: 0,
    State.NEW: 1,
    State.INTERVIEW: 2,
    State.OFFER: 3,
    State.WAITING: 4,
    State.APPLIED: 5,
    State.REJECTED: 6,
    State.SKIPPED: 7,
}


def light_for(state: str) -> Light:
    try:
        return LIGHTS[State(state)]
    except ValueError:
        return Light("?", GREY, state)


def rank_for(state: str) -> int:
    try:
        return SORT_RANK[State(state)]
    except ValueError:
        return 99
