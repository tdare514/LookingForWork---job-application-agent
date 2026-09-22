"""The phone snapshot: the board reduced to what may leave this machine.

ADR 0009 decided that a read-only view of the board may be pushed to Cloudflare
Pages behind a Cloudflare Access login, so status is reachable from a phone.
This module is the reduction that makes that safe to do.

The safety property is the allowlist below, and it is built the same way as
``BoardRepo.FIXTURE_FIELDS``: the fields that may travel are named, the fields
that may not are *also* named, and a test asserts both -- so adding a column to
``jobs`` cannot silently widen what gets published.

There is no I/O here and no push. This builds a dict; the CLI writes it, and a
human uploads it. Nothing in this package reaches the network.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime
from typing import Any

from jobagent.tracking.repo import Job

# Every field that may appear in the snapshot. `state` is here only because the
# owner deliberately downgraded it from CRITICAL -- see the note in
# `jobagent.core.pii` and ADR 0009 before adding to this tuple.
SNAPSHOT_FIELDS: tuple[str, ...] = (
    "id",
    "company",
    "title",
    "location",
    "deadline",
    "state",
    "url",
)

# Named rather than merely absent, so a test can assert on them by name and a
# reader can see what was considered and refused.
#
# `notes` and `state_reason` are free text that routinely names recruiters and
# carries judgements about employers; both stay CRITICAL/NOWHERE in the
# registry. `state_changed_at` is timestamped application history, the same
# class of data as `application_transitions.occurred_at`, and the snapshot does
# not need it to be useful. `description` is bulk posting text that would bloat
# a file meant to be read on a phone.
NEVER_SNAPSHOT: tuple[str, ...] = (
    "notes",
    "state_reason",
    "snoozed_until",
    "state_changed_at",
    "first_seen_at",
    "description",
    "seniority",
)


@dataclass(frozen=True)
class SnapshotRow:
    id: int
    company: str
    title: str
    location: str | None
    deadline: str | None
    state: str
    url: str | None

    def as_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "company": self.company,
            "title": self.title,
            "location": self.location,
            "deadline": self.deadline,
            "state": self.state,
            "url": self.url,
        }


@dataclass(frozen=True)
class Snapshot:
    generated_at: str
    rows: tuple[SnapshotRow, ...]

    def as_dict(self) -> dict[str, Any]:
        return {
            "generated_at": self.generated_at,
            "rows": [row.as_dict() for row in self.rows],
        }


def build(
    jobs: list[Job],
    *,
    generated_at: datetime,
    today: date | None = None,
) -> Snapshot:
    """Reduce board rows to the snapshot's allowlisted shape.

    Snoozed rows are left out: a snooze means "not now", and a phone view that
    shows them is noise. ``generated_at`` is carried so the page can say how
    stale it is -- a static snapshot that looks live is worse than one that
    admits its age.
    """
    current = today or date.today()
    return Snapshot(
        generated_at=generated_at.isoformat(),
        rows=tuple(
            SnapshotRow(
                id=job.id,
                company=job.company,
                title=job.title,
                location=job.location,
                deadline=job.deadline,
                state=job.state,
                url=job.url,
            )
            for job in jobs
            if not job.is_snoozed(current)
        ),
    )
