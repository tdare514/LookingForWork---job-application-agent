"""Board repository -- the only place that reads or writes job rows."""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass
from typing import Any

from jobagent.core.storage import Storage, utcnow
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
    first_seen_at: str
    state_changed_at: str | None


def _normalise_company(name: str) -> str:
    cleaned = re.sub(r"[^a-z0-9 ]", "", name.lower())
    cleaned = re.sub(r"\b(inc|ltd|llc|corp|corporation|company|co|group|bank)\b", "", cleaned)
    return " ".join(cleaned.split())


def _fingerprint(company: str, title: str, location: str | None) -> str:
    basis = f"{_normalise_company(company)}|{title.lower().strip()}|{(location or '').lower()}"
    return hashlib.sha256(basis.encode()).hexdigest()[:24]


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
    ) -> tuple[Job, bool]:
        """Add an opportunity. Returns (job, created). Re-adding is a no-op."""
        fp = _fingerprint(company, title, location)
        now = utcnow()
        existing = (
            self.store.connect()
            .execute("SELECT id FROM jobs WHERE fingerprint = ?", (fp,))
            .fetchone()
        )
        if existing is not None:
            self.store.connect().execute(
                "UPDATE jobs SET last_seen_at = ? WHERE id = ?", (now, existing["id"])
            )
            self.store.connect().commit()
            job = self.get(int(existing["id"]))
            assert job is not None
            return job, False

        with self.store.transaction() as conn:
            cur = conn.execute(
                "INSERT INTO jobs (fingerprint, title, company, company_norm, location, url,"
                " deadline, state, first_seen_at, last_seen_at, state_changed_at)"
                " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    fp,
                    title,
                    company,
                    _normalise_company(company),
                    location,
                    url,
                    deadline,
                    str(state),
                    now,
                    now,
                    now,
                ),
            )
        self.store.append_audit("job.add", {"company": company, "title": title})
        job = self.get(int(cur.lastrowid or 0))
        assert job is not None
        return job, True

    def get(self, job_id: int) -> Job | None:
        row = (
            self.store.connect()
            .execute(
                "SELECT id, company, title, url, location, deadline, state, notes,"
                " first_seen_at, state_changed_at FROM jobs WHERE id = ?",
                (job_id,),
            )
            .fetchone()
        )
        return None if row is None else Job(**dict(row))

    def all(self, include_closed: bool = True) -> list[Job]:
        rows = self.store.connect().execute(
            "SELECT id, company, title, url, location, deadline, state, notes,"
            " first_seen_at, state_changed_at FROM jobs"
        )
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
