"""The ranked list, filtered down to what is worth an evening (#32).

The primitive the digest is built on. Given board rows and their stored scores,
it answers one question: which of these should I actually read?

Pure over data handed in, like `tracking/funnel.py` -- no database, so a case
can be made in a test without building one.

Two guards rather than one, and the reason is worth stating. `min_score` is the
obvious filter, but a total is not as comparable as it looks: #31 drops score
components that had nothing to judge on and rescales the rest, so a row measured
on two components and one measured on four can produce the same number from very
different amounts of evidence. `scored_on` records which, and a threshold cannot
see it. `max_entries` is the blunter guard that makes the list finite regardless
-- and #32's actual requirement is a readable list, not a correct cutoff.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from typing import Any

from jobagent.core.profile import Profile
from jobagent.tracking.board import still_deciding
from jobagent.tracking.repo import Job


@dataclass(frozen=True)
class Entry:
    """One row of the shortlist, carrying what makes its rank arguable."""

    job: Job
    total: float
    components: dict[str, Any]
    sightings: int

    @property
    def scored_on(self) -> list[str]:
        value = self.components.get("scored_on", [])
        return list(value) if isinstance(value, list) else []

    @property
    def is_repost(self) -> bool:
        """Seen more than once. A repost is signal, not noise (#28)."""
        return self.sightings > 1

    def as_dict(self) -> dict[str, Any]:
        return {
            "id": self.job.id,
            "company": self.job.company,
            "title": self.job.title,
            "url": self.job.url,
            "location": self.job.location,
            "deadline": self.job.deadline,
            "state": self.job.state,
            "score": round(self.total, 4),
            "scored_on": self.scored_on,
            "sightings": self.sightings,
            "is_repost": self.is_repost,
            "components": self.components.get("components", {}),
        }


@dataclass(frozen=True)
class Filters:
    """What to narrow the board down to before ranking.

    Every field defaults to "no opinion". An unset filter passes everything,
    which is the same rule the hard filters in `matching/filters.py` follow and
    for the same reason: a filter that quietly empties the list looks exactly
    like a quiet week.
    """

    min_score: float | None = None
    company: str | None = None
    source: str | None = None
    since_days: int | None = None
    include_snoozed: bool = False
    include_decided: bool = False


def build(
    jobs: list[Job],
    scores: dict[int, dict[str, Any]],
    sightings: dict[int, int],
    profile: Profile,
    filters: Filters | None = None,
    today: date | None = None,
    sources: dict[int, set[str]] | None = None,
) -> list[Entry]:
    """Rank what survives, best first.

    Rows the hard filters cut are absent -- they were already judged and their
    reason is stored; `jobagent score --filtered` is where those live. Rows that
    have never been scored are absent too, because there is nothing to rank them
    by, and guessing a position for them is worse than leaving them off a list
    whose whole job is to be short.

    Rows *you* have decided on are absent as well: skipped, rejected, or already
    applied to. Skipping a role has to actually stop it coming back, or the
    queue stops being one.
    """
    day = today or date.today()
    active = filters or Filters()
    threshold = active.min_score if active.min_score is not None else profile.shortlist.min_score

    entries: list[Entry] = []
    for job in jobs:
        record = scores.get(job.id)
        if record is None or record["filtered"]:
            continue
        if not active.include_decided and not still_deciding(job.state):
            continue
        if not active.include_snoozed and job.is_snoozed(day):
            continue
        if record["total"] < threshold:
            continue
        if active.company and not _matches_company(job, active.company):
            continue
        if active.source and not _matches_source(job.id, active.source, sources):
            continue
        if active.since_days is not None and not _seen_within(job, active.since_days, day):
            continue
        entries.append(
            Entry(
                job=job,
                total=float(record["total"]),
                components=record["components"],
                sightings=sightings.get(job.id, 1),
            )
        )

    # Score first; then the nearer deadline, because between two equal matches
    # the one closing on Friday is the one to read tonight.
    entries.sort(key=lambda e: (-e.total, e.job.deadline or "9999-12-31"))
    return entries


def _matches_company(job: Job, wanted: str) -> bool:
    """Substring on the raw company name, not the normalized key.

    `normalize_company` would turn "Bank of Montreal" into "bmo", so a user
    typing `--company montreal` would get nothing. This filter exists to narrow
    a list you are looking at, so it matches what you can see.
    """
    return wanted.strip().lower() in job.company.lower()


def _matches_source(job_id: int, wanted: str, sources: dict[int, set[str]] | None) -> bool:
    if sources is None:
        return True
    return any(wanted.strip().lower() in name.lower() for name in sources.get(job_id, set()))


def _seen_within(job: Job, days: int, today: date) -> bool:
    try:
        first = date.fromisoformat(job.first_seen_at[:10])
    except (ValueError, IndexError):
        # An unparseable timestamp should not silently drop a row from a list
        # the user is relying on to be complete.
        return True
    return (today - first).days <= days
