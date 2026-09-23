"""Repository for `companion_sync`: what the laptop and the hosted tracker last agreed."""

from __future__ import annotations

from dataclasses import dataclass

from jobagent.core.storage import Storage, utcnow


@dataclass(frozen=True)
class Agreed:
    remote_version: int
    pushed_digest: str
    status: str


class SyncStateRepo:
    def __init__(self, store: Storage) -> None:
        self.store = store

    def all(self) -> dict[int, Agreed]:
        rows = self.store.connect().execute(
            "SELECT job_id, remote_version, pushed_digest, agreed_status FROM companion_sync"
        )
        return {
            int(r["job_id"]): Agreed(
                int(r["remote_version"]), str(r["pushed_digest"]), str(r["agreed_status"])
            )
            for r in rows
        }

    def record(self, job_id: int, agreed: Agreed) -> None:
        with self.store.transaction() as conn:
            conn.execute(
                "INSERT INTO companion_sync"
                " (job_id, remote_version, pushed_digest, agreed_status, synced_at)"
                " VALUES (?, ?, ?, ?, ?) ON CONFLICT(job_id) DO UPDATE SET"
                " remote_version = excluded.remote_version,"
                " pushed_digest = excluded.pushed_digest,"
                " agreed_status = excluded.agreed_status, synced_at = excluded.synced_at",
                (job_id, agreed.remote_version, agreed.pushed_digest, agreed.status, utcnow()),
            )

    def forget(self, job_ids: list[int]) -> None:
        """Drop agreement for rows that are no longer on the hosted tracker."""
        with self.store.transaction() as conn:
            conn.executemany("DELETE FROM companion_sync WHERE job_id = ?", [(i,) for i in job_ids])

    def forget_all(self) -> None:
        """After a hosted purge nothing is agreed any more; the next sync starts fresh."""
        with self.store.transaction() as conn:
            conn.execute("DELETE FROM companion_sync")
