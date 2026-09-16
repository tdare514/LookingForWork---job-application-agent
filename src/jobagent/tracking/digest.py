"""The reading queue (#32).

Ten minutes over coffee, three to six roles worth pursuing. #32 states its own
failure mode and it is the right one to design against: *a digest that gets
skipped is the whole phase wasted*. So every section here is capped, and the
default is to say less rather than more.

Four sections, because four questions are worth asking each morning:

1. **New** — what appeared since I last looked, above the threshold.
2. **Moved** — what changed its mind, and which component changed it. A total
   that went from 0.41 to 0.58 is not actionable; "skill overlap rose because
   the description finally got fetched" is.
3. **Reposts** — a role seen repeatedly is either a hard requisition to fill or
   a phantom posting (#28). Both are worth knowing *before* spending an evening
   on a cover letter, which is why they are flagged rather than counted as new.
4. **Filtered** — an aggregate of what the hard filters removed, by rule. Not a
   list: the point is to notice a rule eating the board, and thirty rows cut by
   `location` says that in one line where thirty rows do not.

Pure over data handed in, like `funnel.build` and `shortlist.build`.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from typing import Any

from jobagent.core.profile import Profile
from jobagent.tracking.repo import Job
from jobagent.tracking.shortlist import Entry, Filters
from jobagent.tracking.shortlist import build as build_shortlist

# How many rows a section may show before it stops being a reading queue.
# `max_entries` from the profile caps the section that matters most; these cap
# the rest, because four uncapped sections is a report, not a digest.
MAX_MOVED = 5
MAX_REPOSTS = 5

# A move smaller than this is noise -- a rescale after one component became
# available, or a freshness decay of a day. Reporting it trains you to ignore
# the section.
MOVEMENT_THRESHOLD = 0.05


@dataclass(frozen=True)
class Moved:
    """A role whose score changed, and the components that explain it."""

    entry: Entry
    previous: float
    latest: float
    changed: tuple[str, ...] = ()
    # True when the row was above the threshold and no longer is. The single
    # most actionable kind of movement, and the easiest to hide by accident:
    # building this section only from rows currently on the list means a role
    # that dropped off simply vanishes with no explanation.
    dropped_off: bool = False

    @property
    def delta(self) -> float:
        return self.latest - self.previous

    @property
    def direction(self) -> str:
        return "rose" if self.delta > 0 else "fell"

    def as_dict(self) -> dict[str, Any]:
        return {
            **self.entry.as_dict(),
            "previous": round(self.previous, 4),
            "latest": round(self.latest, 4),
            "delta": round(self.delta, 4),
            "direction": self.direction,
            "changed": list(self.changed),
            "dropped_off": self.dropped_off,
        }


@dataclass(frozen=True)
class Digest:
    since: str
    since_source: str
    new: list[Entry] = field(default_factory=list)
    moved: list[Moved] = field(default_factory=list)
    reposts: list[Entry] = field(default_factory=list)
    filtered: dict[str, int] = field(default_factory=dict)
    total_filtered: int = 0
    scored_count: int = 0

    @property
    def is_empty(self) -> bool:
        return not (self.new or self.moved or self.reposts)

    def as_dict(self) -> dict[str, Any]:
        return {
            "since": self.since,
            "since_source": self.since_source,
            "new": [e.as_dict() for e in self.new],
            "moved": [m.as_dict() for m in self.moved],
            "reposts": [e.as_dict() for e in self.reposts],
            "filtered": {"total": self.total_filtered, "by_rule": self.filtered},
            "scored_count": self.scored_count,
        }


def since_cutoff(
    last_run: dict[str, Any] | None, fallback_days: int, today: date
) -> tuple[date, str, str]:
    """When "new" starts, and an honest label for how that was decided.

    Prefers the last recorded digest run, which is what "since I last looked"
    actually means. Falls back to a window when there is none -- a fresh
    install, or after `purge` clears the audit log -- and says so, because
    "new since yesterday" and "new since you last looked" are different claims
    and the digest should not make the stronger one by accident.
    """
    if last_run is not None:
        stamp = str(last_run.get("occurred_at", ""))
        try:
            when = datetime.fromisoformat(stamp.replace("Z", "+00:00")).date()
            return when, when.isoformat(), "your last digest"
        except ValueError:
            pass
    cutoff = today - timedelta(days=fallback_days)
    return cutoff, cutoff.isoformat(), f"the last {fallback_days} day(s) -- no previous digest"


def build(
    jobs: list[Job],
    scores: dict[int, dict[str, Any]],
    sightings: dict[int, int],
    movement: dict[int, tuple[dict[str, Any], dict[str, Any]]],
    filtered: list[tuple[Job, str]],
    profile: Profile,
    last_run: dict[str, Any] | None = None,
    fallback_days: int = 1,
    today: date | None = None,
) -> Digest:
    day = today or date.today()
    cutoff, since, since_source = since_cutoff(last_run, fallback_days, day)

    threshold = profile.shortlist.min_score
    ranked = build_shortlist(jobs, scores, sightings, profile, Filters(), day)

    # A second pass with no threshold, so movement can see a row that fell off
    # the list. Everything else -- decided, snoozed, filtered, unscored -- is
    # still excluded, because those were deliberate and are not news.
    considered = build_shortlist(jobs, scores, sightings, profile, Filters(min_score=0.0), day)
    by_id = {entry.job.id: entry for entry in considered}

    new = [e for e in ranked if _first_seen_on_or_after(e.job, cutoff) and not e.is_repost]
    reposts = [e for e in ranked if e.is_repost]

    moved: list[Moved] = []
    for job_id, (before, after) in movement.items():
        entry = by_id.get(job_id)
        if entry is None:
            continue
        previous, latest = float(before["total"]), float(after["total"])
        if abs(latest - previous) < MOVEMENT_THRESHOLD:
            continue
        # One side or the other has to clear the bar. A role that was never
        # worth reading and still is not has not become news by wobbling.
        if previous < threshold and latest < threshold:
            continue
        moved.append(
            Moved(
                entry=entry,
                previous=previous,
                latest=latest,
                changed=changed_components(before, after),
                dropped_off=previous >= threshold > latest,
            )
        )
    moved.sort(key=lambda m: -abs(m.delta))

    by_rule: dict[str, int] = {}
    for _job, reason in filtered:
        rule = reason.split(":", 1)[0].strip() if ":" in reason else "unknown"
        by_rule[rule] = by_rule.get(rule, 0) + 1

    return Digest(
        since=since,
        since_source=since_source,
        new=new[: profile.shortlist.max_entries],
        moved=moved[:MAX_MOVED],
        reposts=reposts[:MAX_REPOSTS],
        filtered=dict(sorted(by_rule.items(), key=lambda kv: -kv[1])),
        total_filtered=len(filtered),
        scored_count=len(ranked),
    )


def _component_map(record: dict[str, Any]) -> dict[str, Any]:
    payload = record.get("components", {})
    if not isinstance(payload, dict):
        return {}
    inner = payload.get("components", {})
    return inner if isinstance(inner, dict) else {}


def changed_components(before: dict[str, Any], after: dict[str, Any]) -> tuple[str, ...]:
    """Which components differ between two stored decompositions.

    Names, not prose -- the renderer turns them into a sentence. An empty result
    is a real answer and means the total moved without any component value
    changing, which happens when a component became available or unavailable and
    the remaining weights rescaled (#31). Saying nothing is better than naming
    the largest current component and implying it was the one that moved.
    """
    # Two levels down, and the nesting is easy to get wrong: a stored record is
    # {"total": ..., "components": <the whole decomposition>}, and the
    # decomposition is itself {"total", "scored_on", "unavailable",
    # "components": {name: {...}}}. Reading one level too shallow compares the
    # decomposition's own keys, finds no "value" on either side, and silently
    # reports that nothing ever changes.
    old = _component_map(before)
    new = _component_map(after)
    if not old and not new:
        return ()
    changed: list[str] = []
    for name, current in new.items():
        was = old.get(name, {})
        if (
            isinstance(was, dict)
            and isinstance(current, dict)
            and was.get("value") != current.get("value")
        ):
            changed.append(name)
    return tuple(changed)


def _first_seen_on_or_after(job: Job, cutoff: date) -> bool:
    try:
        return date.fromisoformat(job.first_seen_at[:10]) >= cutoff
    except (ValueError, IndexError):
        return False
