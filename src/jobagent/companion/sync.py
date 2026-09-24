"""`jobagent sync`: reconcile the board with the hosted tracker (ADR 0010).

Pure planning first, then I/O. `plan` looks at the board, the hosted rows and
what the two last agreed, and decides per row; `run` carries a plan out. The
split is what makes the rules testable without a network.

The rules, per board row:

- Never seen by the tracker: push it.
- Changed only on the laptop: push it, naming the version last agreed.
- Changed only on the phone: take the phone's status onto the board. Other
  fields stay the laptop's, and are pushed back if the phone changed them.
- Changed on both, to different statuses: a conflict. Neither side is
  overwritten; the row is reported and left for a human.

Hosted rows with no live board row behind them are removed. The laptop is the
source of truth for which rows exist.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import date
from typing import Any

from jobagent.companion.client import CompanionClient, batches
from jobagent.companion.contract import FROM_BOARD, HOSTED_ONLY
from jobagent.companion.state import Agreed
from jobagent.tracking.board import State
from jobagent.tracking.repo import Job


def board_fields(job: Job) -> dict[str, Any]:
    """The hosted fields a board row supplies, and nothing else."""
    values = {
        "company": job.company,
        "title": job.title,
        "location": job.location or "",
        "url": job.url or "",
        "deadline": job.deadline,
        "status": job.state,
    }
    assert set(values) == set(FROM_BOARD)  # the contract, not this function, decides
    return values


def digest(fields: dict[str, Any]) -> str:
    return hashlib.sha256(json.dumps(fields, sort_keys=True).encode()).hexdigest()[:32]


@dataclass(frozen=True)
class Pull:
    job_id: int
    status: str
    remote_version: int


@dataclass(frozen=True)
class Conflict:
    job_id: int
    board_status: str
    hosted_status: str


@dataclass
class Plan:
    pushes: list[dict[str, Any]] = field(default_factory=list)
    pulls: list[Pull] = field(default_factory=list)
    removals: list[str] = field(default_factory=list)
    conflicts: list[Conflict] = field(default_factory=list)
    # Rows already in agreement whose recorded state needs catching up.
    settled: list[tuple[int, Agreed]] = field(default_factory=list)

    @property
    def empty(self) -> bool:
        return not (self.pushes or self.pulls or self.removals or self.settled)


def plan(
    jobs: list[Job],
    hosted: list[dict[str, Any]],
    agreed: dict[int, Agreed],
    today: date | None = None,
) -> Plan:
    current = today or date.today()
    live = {str(job.id): job for job in jobs if not job.is_snoozed(current)}
    by_id = {str(row["id"]): row for row in hosted}
    out = Plan()

    for key, job in live.items():
        mine = board_fields(job)
        theirs = by_id.get(key)
        last = agreed.get(job.id)

        if theirs is None:
            # Never sent, or removed hosted (a purge): send it fresh.
            out.pushes.append(_row(key, mine, None, version=0))
            continue

        remote_version = int(theirs["version"])
        hosted_fields = {name: theirs.get(name) for name in FROM_BOARD}

        if last is None:
            # First contact with a row that already exists hosted: the laptop's
            # view wins, because nothing says the phone's is newer.
            if hosted_fields == mine:
                out.settled.append((job.id, Agreed(remote_version, digest(mine), job.state)))
            else:
                out.pushes.append(_row(key, mine, theirs, remote_version))
            continue

        phone_status = str(theirs["status"])
        phone_moved_status = phone_status != last.status
        board_moved_status = job.state != last.status
        if phone_moved_status and board_moved_status and phone_status != job.state:
            out.conflicts.append(Conflict(job.id, job.state, phone_status))
            continue
        if phone_moved_status and not board_moved_status:
            out.pulls.append(Pull(job.id, phone_status, remote_version))
            mine = {**mine, "status": phone_status}

        # Every other field is the laptop's. If the phone changed one, put it back.
        if hosted_fields != mine:
            out.pushes.append(_row(key, mine, theirs, remote_version))
        elif remote_version != last.remote_version or digest(mine) != last.pushed_digest:
            out.settled.append((job.id, Agreed(remote_version, digest(mine), str(mine["status"]))))

    out.removals = sorted(key for key in by_id if key not in live)
    return out


def _row(
    key: str, fields: dict[str, Any], hosted: dict[str, Any] | None, version: int
) -> dict[str, Any]:
    carried = {name: (hosted or {}).get(name) for name in HOSTED_ONLY}
    return {"id": key, **fields, **carried, "version": version}


@dataclass(frozen=True)
class Outcome:
    pushed: int
    pulled: int
    removed: int
    conflicts: list[Conflict]


def run(
    client: CompanionClient,
    the_plan: Plan,
    *,
    set_state: Callable[[int, State], None],
    record: Callable[[int, Agreed], None],
    forget: Callable[[list[int]], None],
) -> Outcome:
    """Carry a plan out. Pulls land on the board first, then pushes go up.

    Pulls first, so a push can never carry a status the board has not taken.
    A 409 on push means the phone moved after the pull: that batch wrote
    nothing, its rows are reported as conflicts, and the next sync re-plans.
    """
    for pull in the_plan.pulls:
        set_state(pull.job_id, State(pull.status))
    for job_id, agreement in the_plan.settled:
        record(job_id, agreement)

    by_key = {row["id"]: row for row in the_plan.pushes}
    pushed = removed = 0
    conflicts = list(the_plan.conflicts)
    for body in batches(the_plan.pushes, the_plan.removals):
        status, payload = client.push(body)
        if status == 409:
            for item in payload.get("conflicts", []):
                row = by_key.get(str(item["id"]), {})
                conflicts.append(
                    Conflict(int(item["id"]), str(row.get("status")), "changed on the phone")
                )
            continue
        for item in payload["accepted"]:
            row = by_key[str(item["id"])]
            fields = {name: row[name] for name in FROM_BOARD}
            record(
                int(item["id"]), Agreed(int(item["version"]), digest(fields), str(row["status"]))
            )
            pushed += 1
        removed += int(payload.get("removed", 0))
        forget([int(key) for key in body.get("remove", []) if key.isdigit()])
    return Outcome(pushed, len(the_plan.pulls), removed, conflicts)
