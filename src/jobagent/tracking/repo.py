"""Board repository -- the only place that reads or writes job rows."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from typing import Any

from jobagent.core.storage import Storage, utcnow
from jobagent.matching.normalize import (
    dedupe_key,
    normalize_company,
    normalize_location,
    normalize_seniority,
    normalize_title,
    same_role,
)
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
    " first_seen_at, state_changed_at"
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

    def set_state(self, job_id: int, state: State) -> None:
        with self.store.transaction() as conn:
            conn.execute(
                "UPDATE jobs SET state = ?, state_changed_at = ? WHERE id = ?",
                (str(state), utcnow(), job_id),
            )
        self.store.append_audit("job.state", {"job_id": job_id, "state": str(state)})

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
