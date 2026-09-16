"""Board repository -- the only place that reads or writes job rows."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import date
from typing import Any

from jobagent.core.storage import Storage, utcnow
from jobagent.matching.extract import Requirements
from jobagent.matching.filters import Listing, Verdict
from jobagent.matching.normalize import (
    dedupe_key,
    normalize_company,
    normalize_location,
    normalize_seniority,
    normalize_title,
    same_role,
)
from jobagent.matching.score import Score
from jobagent.tracking.board import State, rank_for


@dataclass
class Job:
    id: int
    company: str
    title: str
    url: str | None
    location: str | None
    deadline: str | None
    state: str
    notes: str | None
    seniority: str | None
    first_seen_at: str
    state_changed_at: str | None
    # Both added by M0004 (#32). Optional with defaults so a row read before the
    # migration, or a Job built by hand in a test, still constructs.
    state_reason: str | None = None
    snoozed_until: str | None = None

    def is_snoozed(self, today: date) -> bool:
        """Snoozed rows leave the digest until the date passes, then return.

        Deliberately not a state: "not now" is not a decision, and making it one
        would mean remembering to undo it. The row keeps whatever state it had.
        """
        if not self.snoozed_until:
            return False
        return self.snoozed_until > today.isoformat()


@dataclass(frozen=True)
class Sighting:
    """One time a source showed us a role.

    A role reposted three times in six weeks is either a hard requisition to
    fill or a phantom posting. Both are worth knowing before spending an evening
    on a cover letter, and neither is visible from a single row.
    """

    source: str
    source_id: str
    url: str | None
    seen_at: str


def _fingerprint(company: str, title: str, location: str | None) -> str:
    """Exact identity, kept because the column is UNIQUE and already populated.

    `dedupe_key` is strictly coarser than this, and it is checked first, so an
    insert can never reach a fingerprint collision.
    """
    basis = f"{normalize_company(company)}|{title.lower().strip()}|{(location or '').lower()}"
    return hashlib.sha256(basis.encode()).hexdigest()[:24]


_JOB_COLUMNS = (
    "id, company, title, url, location, deadline, state, notes, seniority,"
    " first_seen_at, state_changed_at, state_reason, snoozed_until"
)


class BoardRepo:
    def __init__(self, store: Storage) -> None:
        self.store = store

    def add(
        self,
        company: str,
        title: str,
        url: str | None = None,
        location: str | None = None,
        deadline: str | None = None,
        state: State = State.NEW,
        source: str = "manual",
        source_id: str | None = None,
        description: str | None = None,
    ) -> tuple[Job, bool]:
        """Add an opportunity. Returns (job, created).

        A role already on the board is not added again -- it gains a sighting.
        That is the whole of #28 in one method: the same posting from two
        sources, or the same requisition reposted next term, is one job.
        """
        now = utcnow()
        key = dedupe_key(company, title, location)
        existing = self._match(company, title, key)

        if existing is not None:
            self.record_sighting(existing.id, source, source_id or key, url, now)
            with self.store.transaction() as conn:
                conn.execute("UPDATE jobs SET last_seen_at = ? WHERE id = ?", (now, existing.id))
                # Fill gaps a later sighting knows about, never overwrite. A
                # deadline typed in by hand outranks one a fetch guessed at.
                if description:
                    conn.execute(
                        "UPDATE jobs SET description = ? WHERE id = ? AND"
                        " (description IS NULL OR description = '')",
                        (description, existing.id),
                    )
                if deadline:
                    conn.execute(
                        "UPDATE jobs SET deadline = ? WHERE id = ? AND"
                        " (deadline IS NULL OR deadline = '')",
                        (deadline, existing.id),
                    )
                if url:
                    conn.execute(
                        "UPDATE jobs SET url = ? WHERE id = ? AND (url IS NULL OR url = '')",
                        (url, existing.id),
                    )
            refreshed = self.get(existing.id)
            assert refreshed is not None
            return refreshed, False

        with self.store.transaction() as conn:
            cur = conn.execute(
                "INSERT INTO jobs (fingerprint, title, company, company_norm, title_norm,"
                " location, location_norm, dedupe_key, seniority, description, url,"
                " deadline, state, first_seen_at, last_seen_at, state_changed_at)"
                " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    _fingerprint(company, title, location),
                    title,
                    company,
                    normalize_company(company),
                    normalize_title(title),
                    location,
                    normalize_location(location),
                    key,
                    str(normalize_seniority(title, description)),
                    description,
                    url,
                    deadline,
                    str(state),
                    now,
                    now,
                    now,
                ),
            )
        job_id = int(cur.lastrowid or 0)
        self.record_sighting(job_id, source, source_id or key, url, now)
        self.store.append_audit("job.add", {"company": company, "title": title})
        job = self.get(job_id)
        assert job is not None
        return job, True

    def find(self, company: str, title: str, location: str | None = None) -> Job | None:
        """The row this role is already on the board as, if it is.

        Public so that feature code asking "do I already have this?" gets the
        board's own answer, rather than inventing a second notion of sameness --
        which is how a tracker starts showing one job twice.
        """
        return self._match(company, title, dedupe_key(company, title, location))

    def _match(self, company: str, title: str, key: str) -> Job | None:
        """Find the job this posting already is, if any.

        Two passes. The exact key collapses the cross-source and repost cases,
        which is the overwhelming majority. The fuzzy pass exists for the one
        real case the key misses: a source that prefixes its own department onto
        the title, so "GRM, Counterparty Credit Risk Intern" and "Counterparty
        Credit Risk Intern" are the same requisition spelled two ways.

        The fuzzy pass is scoped to one company and one city on purpose. Across
        companies, similar titles are the norm and merging them would be wrong
        every time.
        """
        conn = self.store.connect()
        exact = conn.execute(
            f"SELECT {_JOB_COLUMNS} FROM jobs WHERE dedupe_key = ? ORDER BY id LIMIT 1", (key,)
        ).fetchone()
        if exact is not None:
            return Job(**dict(exact))

        company_norm, _, location_norm = key.split("|")
        candidates = conn.execute(
            f"SELECT {_JOB_COLUMNS} FROM jobs WHERE company_norm = ? AND location_norm = ?"
            " ORDER BY id",
            (company_norm, location_norm),
        )
        for row in candidates:
            if same_role(title, row["title"]):
                return Job(**dict(row))
        return None

    # -- sightings ---------------------------------------------------------

    def record_sighting(
        self,
        job_id: int,
        source: str,
        source_id: str,
        url: str | None = None,
        seen_at: str | None = None,
    ) -> bool:
        """Record that a source showed this role. One sighting per source per day.

        Re-running `fetch` twice on a Tuesday is a thing people do. It should not
        invent two sightings and make a stable posting look like it is being
        aggressively reposted.
        """
        stamp = seen_at or utcnow()
        day = stamp[:10]
        conn = self.store.connect()
        already = conn.execute(
            "SELECT 1 FROM job_sightings WHERE job_id = ? AND source = ? AND source_id = ?"
            " AND substr(seen_at, 1, 10) = ?",
            (job_id, source, source_id, day),
        ).fetchone()
        if already is not None:
            return False
        with self.store.transaction() as txn:
            txn.execute(
                "INSERT INTO job_sightings (job_id, source, source_id, url, seen_at)"
                " VALUES (?, ?, ?, ?, ?)",
                (job_id, source, source_id, url, stamp),
            )
        return True

    def sightings(self, job_id: int) -> list[Sighting]:
        rows = self.store.connect().execute(
            "SELECT source, source_id, url, seen_at FROM job_sightings WHERE job_id = ?"
            " ORDER BY seen_at",
            (job_id,),
        )
        return [Sighting(**dict(r)) for r in rows]

    def sources_by_job(self) -> dict[int, set[str]]:
        """Which sources have shown each role. One job can come from several."""
        rows = self.store.connect().execute("SELECT job_id, source FROM job_sightings")
        out: dict[int, set[str]] = {}
        for row in rows:
            out.setdefault(int(row["job_id"]), set()).add(str(row["source"]))
        return out

    def sighting_counts(self) -> dict[int, int]:
        """How many times each job has been seen. Reposts are signal."""
        rows = self.store.connect().execute(
            "SELECT job_id, COUNT(*) c FROM job_sightings GROUP BY job_id"
        )
        return {int(r["job_id"]): int(r["c"]) for r in rows}

    def store_raw(self, source: str, source_id: str, body: dict[str, Any]) -> None:
        """Keep the unparsed payload so a mapping bug is fixable without re-fetching.

        Registered in the PII registry at 30 days. #58 is exactly why this
        exists: the mapping was wrong twice and the fix needed the real shape.

        One payload per source per day, for the same reason sightings are capped
        that way: fetching twice on a Tuesday should not double the table. The
        30-day retention bounds it, but an unbounded write every run makes the
        window meaningless.
        """
        today = utcnow()[:10]
        conn = self.store.connect()
        already = conn.execute(
            "SELECT 1 FROM raw_payloads WHERE source = ? AND source_id = ?"
            " AND substr(fetched_at, 1, 10) = ?",
            (source, source_id, today),
        ).fetchone()
        if already is not None:
            return
        with self.store.transaction() as txn:
            txn.execute(
                "INSERT INTO raw_payloads (source, source_id, body, fetched_at)"
                " VALUES (?, ?, ?, ?)",
                (source, source_id, json.dumps(body, default=str), utcnow()),
            )

    # -- extracted requirements -------------------------------------------

    def save_requirements(self, job_id: int, requirements: Requirements) -> None:
        """Store one extraction, stamped with the ruleset that produced it.

        `prompt_version` in M0001 assumed an LLM. It holds a ruleset version
        instead (ADR 0008), which is the same idea doing the same job: a quality
        change has to be traceable to a rule change, or the evaluation harness
        cannot tell improvement from drift.
        """
        with self.store.transaction() as conn:
            conn.execute(
                "INSERT INTO job_requirements (job_id, payload, prompt_version, extracted_at)"
                " VALUES (?, ?, ?, ?)",
                (
                    job_id,
                    json.dumps(requirements.as_dict()),
                    requirements.ruleset_version,
                    utcnow(),
                ),
            )
        # Fields the canonical job row owns, filled only where it is silent.
        with self.store.transaction() as conn:
            if requirements.compensation_min is not None:
                conn.execute(
                    "UPDATE jobs SET compensation_min = ?, compensation_max = ?, currency = ?"
                    " WHERE id = ? AND compensation_min IS NULL",
                    (
                        requirements.compensation_min,
                        requirements.compensation_max,
                        requirements.currency,
                        job_id,
                    ),
                )
            if requirements.work_arrangement:
                conn.execute(
                    "UPDATE jobs SET work_arrangement = ? WHERE id = ?"
                    " AND (work_arrangement IS NULL OR work_arrangement = '')",
                    (requirements.work_arrangement, job_id),
                )
            if requirements.application_deadline:
                conn.execute(
                    "UPDATE jobs SET deadline = ? WHERE id = ?"
                    " AND (deadline IS NULL OR deadline = '')",
                    (requirements.application_deadline, job_id),
                )

    def latest_requirements(self, job_id: int) -> dict[str, Any] | None:
        row = (
            self.store.connect()
            .execute(
                "SELECT payload FROM job_requirements WHERE job_id = ? ORDER BY id DESC LIMIT 1",
                (job_id,),
            )
            .fetchone()
        )
        if row is None:
            return None
        loaded: dict[str, Any] = json.loads(row["payload"])
        return loaded

    # -- scoring inputs ----------------------------------------------------

    def scoring_rows(self) -> list[tuple[int, Listing, str | None]]:
        """Every job as (id, listing, posted_at), ready for filters and scoring.

        A separate read rather than widening `Job`. `Job` is the board's row and
        is carried through the TUI, the funnel and the followups; adding six
        columns it never renders would make every one of those pay for this.
        """
        rows = self.store.connect().execute(
            "SELECT id, company, title, location, work_arrangement, description,"
            " compensation_min, compensation_max, currency, posted_at FROM jobs"
        )
        return [
            (
                int(r["id"]),
                Listing(
                    company=r["company"],
                    title=r["title"],
                    location=r["location"],
                    work_arrangement=r["work_arrangement"],
                    description=r["description"],
                    compensation_min=r["compensation_min"],
                    compensation_max=r["compensation_max"],
                    currency=r["currency"],
                ),
                r["posted_at"],
            )
            for r in rows
        ]

    # -- scores ------------------------------------------------------------

    def save_score(self, job_id: int, score: Score, verdict: Verdict) -> None:
        """Store one scoring pass, filtered or not, with its decomposition.

        Appended rather than replaced, matching `save_requirements` above and
        for the same reason: the history is what lets #32 say "this role's score
        moved" instead of only ever knowing the latest number.

        A filtered job is stored with a total of 0 and its reason. It is kept
        rather than dropped so that a filter cutting too aggressively is
        discoverable -- an empty board and a board whose every row was cut by
        one over-eager rule look identical from the outside otherwise.
        """
        with self.store.transaction() as conn:
            conn.execute(
                "INSERT INTO scores (job_id, total, components, filtered, filter_reason,"
                " scored_at) VALUES (?, ?, ?, ?, ?, ?)",
                (
                    job_id,
                    score.total if verdict.passed else 0.0,
                    json.dumps(score.as_dict()),
                    0 if verdict.passed else 1,
                    None if verdict.passed else f"{verdict.rule}: {verdict.reason}",
                    utcnow(),
                ),
            )

    def latest_scores(self) -> dict[int, dict[str, Any]]:
        """The most recent score per job, keyed by job id.

        `MAX(id)` rather than `MAX(scored_at)`: two runs in the same second are
        a thing that happens in tests and on a fast machine, and a timestamp
        cannot order them.
        """
        rows = self.store.connect().execute(
            "SELECT s.job_id, s.total, s.components, s.filtered, s.filter_reason, s.scored_at"
            " FROM scores s JOIN (SELECT job_id, MAX(id) AS newest FROM scores GROUP BY job_id) m"
            " ON s.id = m.newest"
        )
        return {
            int(r["job_id"]): {
                "total": float(r["total"]),
                "components": json.loads(r["components"]),
                "filtered": bool(r["filtered"]),
                "filter_reason": r["filter_reason"],
                "scored_at": r["scored_at"],
            }
            for r in rows
        }

    def filtered_jobs(self) -> list[tuple[Job, str]]:
        """Every job cut by the hard filters, with the reason it was cut.

        The acceptance criterion #31 asks for by name. Without it a filter that
        is eating the board is invisible.
        """
        latest = self.latest_scores()
        out: list[tuple[Job, str]] = []
        for job_id, record in latest.items():
            if not record["filtered"]:
                continue
            job = self.get(job_id)
            if job is not None:
                out.append((job, str(record["filter_reason"] or "no reason recorded")))
        out.sort(key=lambda pair: (pair[0].company.lower(), pair[0].title.lower()))
        return out

    def jobs_with_descriptions(self) -> list[tuple[int, str]]:
        rows = self.store.connect().execute(
            "SELECT id, description FROM jobs WHERE description IS NOT NULL AND description != ''"
        )
        return [(int(r["id"]), str(r["description"])) for r in rows]

    def backfill_normalized(self) -> int:
        """Populate the normalized columns for rows that predate M0003.

        Idempotent and non-destructive: it fills the new columns and touches
        nothing else. Rows that are now revealed to be duplicates of each other
        are deliberately left alone -- merging board rows the user has been
        tracking is their call, not a migration's.
        """
        conn = self.store.connect()
        rows = conn.execute(
            "SELECT id, company, title, location, description FROM jobs WHERE dedupe_key = ''"
        ).fetchall()
        for row in rows:
            with self.store.transaction() as txn:
                txn.execute(
                    "UPDATE jobs SET company_norm = ?, title_norm = ?, location_norm = ?,"
                    " dedupe_key = ?, seniority = COALESCE(seniority, ?) WHERE id = ?",
                    (
                        normalize_company(row["company"]),
                        normalize_title(row["title"]),
                        normalize_location(row["location"]),
                        dedupe_key(row["company"], row["title"], row["location"]),
                        str(normalize_seniority(row["title"], row["description"])),
                        row["id"],
                    ),
                )
        return len(rows)

    def get(self, job_id: int) -> Job | None:
        row = (
            self.store.connect()
            .execute(f"SELECT {_JOB_COLUMNS} FROM jobs WHERE id = ?", (job_id,))
            .fetchone()
        )
        return None if row is None else Job(**dict(row))

    def all(self, include_closed: bool = True) -> list[Job]:
        rows = self.store.connect().execute(f"SELECT {_JOB_COLUMNS} FROM jobs")
        jobs = [Job(**dict(r)) for r in rows]
        if not include_closed:
            jobs = [j for j in jobs if j.state not in {State.REJECTED, State.SKIPPED}]
        # Needs-action first, then by deadline, then newest.
        jobs.sort(key=lambda j: (rank_for(j.state), j.deadline or "9999", j.company.lower()))
        return jobs

    def set_state(self, job_id: int, state: State, reason: str | None = None) -> None:
        """Move a row, optionally recording why.

        The reason is the point of #32's skip handling: three weeks later, a
        skip with no reason is indistinguishable from one you would now reverse.
        It is stored on the row and aggregated by the funnel report.

        A `None` reason leaves any existing one alone rather than clearing it.
        The board's `s` key passes no reason, and it should not silently erase
        one typed at the CLI.
        """
        with self.store.transaction() as conn:
            conn.execute(
                "UPDATE jobs SET state = ?, state_changed_at = ? WHERE id = ?",
                (str(state), utcnow(), job_id),
            )
            if reason is not None:
                conn.execute("UPDATE jobs SET state_reason = ? WHERE id = ?", (reason, job_id))
        # The reason names a company and a judgement about it, so it stays out
        # of the audit detail -- `audit_log.detail` is CRITICAL but it is also
        # the thing most likely to be pasted somewhere while debugging.
        self.store.append_audit(
            "job.state",
            {"job_id": job_id, "state": str(state), "reason_given": reason is not None},
        )

    def snooze(self, job_id: int, until: date) -> None:
        """Hide a row from the digest until a date, without deciding anything."""
        with self.store.transaction() as conn:
            conn.execute(
                "UPDATE jobs SET snoozed_until = ? WHERE id = ?", (until.isoformat(), job_id)
            )
        self.store.append_audit("job.snooze", {"job_id": job_id, "until": until.isoformat()})

    def unsnooze(self, job_id: int) -> None:
        with self.store.transaction() as conn:
            conn.execute("UPDATE jobs SET snoozed_until = NULL WHERE id = ?", (job_id,))

    def score_movement(self) -> dict[int, tuple[dict[str, Any], dict[str, Any]]]:
        """`{job_id: (previous, latest)}` for rows scored more than once.

        Free, because #31 appends scores rather than replacing them. Each half
        is the full stored record -- total *and* decomposition -- because "the
        score moved" is not useful on its own and the component that moved is
        the whole point of the section it feeds.

        Rows scored once are absent: there is no movement to report on a first
        reading, and rendering 0.0 -> 0.62 as a rise would report the day the
        tool was installed rather than anything about the job.
        """
        rows = self.store.connect().execute(
            "SELECT job_id, total, components FROM scores WHERE filtered = 0"
            " ORDER BY job_id, id DESC"
        )
        seen: dict[int, list[dict[str, Any]]] = {}
        for row in rows:
            seen.setdefault(int(row["job_id"]), []).append(
                {"total": float(row["total"]), "components": json.loads(row["components"])}
            )
        return {
            job_id: (records[1], records[0])
            for job_id, records in seen.items()
            if len(records) >= 2
        }

    def set_notes(self, job_id: int, notes: str) -> None:
        with self.store.transaction() as conn:
            conn.execute("UPDATE jobs SET notes = ? WHERE id = ?", (notes, job_id))

    def delete(self, job_id: int) -> None:
        with self.store.transaction() as conn:
            conn.execute("DELETE FROM jobs WHERE id = ?", (job_id,))
        self.store.append_audit("job.delete", {"job_id": job_id})

    def counts(self) -> dict[str, int]:
        rows = self.store.connect().execute("SELECT state, COUNT(*) c FROM jobs GROUP BY state")
        return {r["state"]: int(r["c"]) for r in rows}

    def as_dicts(self) -> list[dict[str, Any]]:
        return [j.__dict__ for j in self.all()]
