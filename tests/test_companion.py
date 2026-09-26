"""`jobagent sync` against a fake companion (ADR 0010).

The fake speaks the real routes' contract -- versions, 409 on a stale write,
removals, paging -- so these tests exercise the client and the planner, not a
mock of either. What breaks silently here is what leaves the machine, so most
of these assert on the bytes that were sent.
"""

from __future__ import annotations

import inspect
import json
from typing import Any

import httpx
import pytest
from typer.testing import CliRunner

from jobagent.cli import main as cli
from jobagent.cli.exit_codes import ExitCode
from jobagent.companion import client as companion
from jobagent.companion.client import CompanionClient, CompanionConfig, gate_is_on
from jobagent.companion.contract import FROM_BOARD, HOSTED_ONLY, IDENTIFIERS
from jobagent.companion.state import SyncStateRepo
from jobagent.core.storage import Storage
from jobagent.tracking.board import State
from jobagent.tracking.repo import BoardRepo

URL = "https://companion.example.invalid"
TOKEN = "synthetic-sync-token-0123456789abcdef"
ENV = {
    "JOBAGENT_COMPANION_URL": URL,
    "JOBAGENT_SYNC_TOKEN": TOKEN,
    "JOBAGENT_ACCESS_CLIENT_ID": "synthetic.access",
    "JOBAGENT_ACCESS_CLIENT_SECRET": "synthetic-access-secret",
}
ALLOWED_KEYS = set(FROM_BOARD) | set(HOSTED_ONLY) | set(IDENTIFIERS)


class FakeCompanion:
    """Just enough of the hosted tracker to be honest about versions."""

    def __init__(self, gate: bool = True, page: int = 50) -> None:
        self.gate = gate
        self.page = page
        self.rows: dict[str, dict[str, Any]] = {}
        self.posts: list[dict[str, Any]] = []
        self.purged = False

    def phone_edit(self, job_id: int, **changes: Any) -> None:
        row = self.rows[str(job_id)]
        row.update(changes)
        row["version"] += 1

    def handle(self, request: httpx.Request) -> httpx.Response:
        path = request.url.path
        if "authorization" not in request.headers:
            if self.gate:
                return httpx.Response(
                    302, headers={"location": "https://team.cloudflareaccess.com/login"}
                )
            return httpx.Response(200, text="<html>the board</html>")
        assert request.headers["authorization"] == f"Bearer {TOKEN}"
        assert request.headers["cf-access-client-id"] == ENV["JOBAGENT_ACCESS_CLIENT_ID"]
        if path == "/api/sync" and request.method == "GET":
            after = request.url.params.get("after", "")
            ordered = [self.rows[k] for k in sorted(self.rows) if k > after][: self.page]
            nxt = ordered[-1]["id"] if len(ordered) == self.page else None
            return httpx.Response(200, json={"applications": ordered, "next": nxt})
        if path == "/api/sync" and request.method == "POST":
            body = json.loads(request.content)
            self.posts.append(body)
            stale = [
                {"id": r["id"], "version": self.rows[r["id"]]["version"]}
                for r in body["applications"]
                if r["id"] in self.rows and self.rows[r["id"]]["version"] != r["version"]
            ]
            if stale:
                return httpx.Response(409, json={"accepted": [], "conflicts": stale})
            accepted = []
            for r in body["applications"]:
                version = self.rows[r["id"]]["version"] + 1 if r["id"] in self.rows else 1
                self.rows[r["id"]] = {**r, "version": version}
                accepted.append({"id": r["id"], "version": version})
            removed = sum(1 for key in body.get("remove", []) if self.rows.pop(key, None))
            return httpx.Response(
                200, json={"accepted": accepted, "count": len(accepted), "removed": removed}
            )
        if path == "/api/purge":
            self.rows.clear()
            self.purged = True
            zero = {"jobs": 0, "owner_sessions": 0, "oauth_states": 0}
            return httpx.Response(200, json={"removed": zero, "remaining": zero, "clean": True})
        return httpx.Response(404)


@pytest.fixture()
def fake(monkeypatch: pytest.MonkeyPatch, data_dir: object) -> FakeCompanion:
    server = FakeCompanion()
    for name, value in ENV.items():
        monkeypatch.setenv(name, value)
    monkeypatch.setattr(
        companion,
        "connect",
        lambda config: CompanionClient(config, transport=httpx.MockTransport(server.handle)),
    )
    return server


def _board(*rows: tuple[str, str, State]) -> list[int]:
    ids = []
    with Storage() as store:
        repo = BoardRepo(store)
        for company, title, state in rows:
            job, _ = repo.add(
                company, title, url=f"https://jobs.example.invalid/{title}", state=state
            )
            repo.set_notes(job.id, "Recruiter: a real person's name")
            ids.append(job.id)
    return ids


def _sync(*args: str) -> Any:
    return CliRunner().invoke(cli.app, ["sync", *args])


def _state(job_id: int) -> str:
    with Storage() as store:
        job = BoardRepo(store).get(job_id)
        assert job is not None
        return job.state


def test_refuses_when_the_access_gate_is_off(fake: FakeCompanion) -> None:
    fake.gate = False
    _board(("Example North", "Analyst", State.READY))
    result = _sync("--yes")
    assert result.exit_code == ExitCode.AGENT_FAILURE
    assert "not the Cloudflare Access login" in result.output
    assert fake.posts == []


def test_gate_check_reads_access_answers() -> None:
    assert gate_is_on(httpx.Response(302, headers={"location": "https://t.cloudflareaccess.com/x"}))
    assert gate_is_on(httpx.Response(403))
    assert not gate_is_on(httpx.Response(200))
    assert not gate_is_on(
        httpx.Response(302, headers={"location": "https://evil.example/cloudflareaccess.com"})
    )


def test_a_dry_run_sends_nothing(fake: FakeCompanion) -> None:
    _board(("Example North", "Analyst", State.READY))
    result = _sync()
    assert result.exit_code == 0, result.output
    assert "Dry run" in result.output
    assert fake.posts == []


def test_first_sync_sends_the_contract_and_never_notes(fake: FakeCompanion) -> None:
    ids = _board(
        ("Example North", "Analyst", State.READY), ("Sample Works", "Co-op", State.APPLIED)
    )
    result = _sync("--yes")
    assert result.exit_code == 0, result.output
    sent = [row for body in fake.posts for row in body["applications"]]
    assert {row["id"] for row in sent} == {str(i) for i in ids}
    for row in sent:
        assert set(row) == ALLOWED_KEYS
    assert "real person" not in json.dumps(fake.posts)
    with Storage() as store:
        assert set(SyncStateRepo(store).all()) == set(ids)


def test_a_phone_status_change_comes_back_to_the_board(fake: FakeCompanion) -> None:
    (job_id,) = _board(("Example North", "Analyst", State.READY))
    _sync("--yes")
    fake.phone_edit(job_id, status="applied", nextAction="Follow up Friday")
    result = _sync("--yes")
    assert result.exit_code == 0, result.output
    assert _state(job_id) == "applied"
    # Nothing to push back, and the phone-only field survived.
    assert fake.rows[str(job_id)]["nextAction"] == "Follow up Friday"
    assert "real person" not in json.dumps(fake.posts)


def test_a_board_change_goes_up_and_keeps_phone_only_fields(fake: FakeCompanion) -> None:
    (job_id,) = _board(("Example North", "Analyst", State.READY))
    _sync("--yes")
    fake.phone_edit(job_id, nextAction="Tailor resume")
    with Storage() as store:
        BoardRepo(store).set_state(job_id, State.APPLIED)
    assert _sync("--yes").exit_code == 0
    assert fake.rows[str(job_id)]["status"] == "applied"
    assert fake.rows[str(job_id)]["nextAction"] == "Tailor resume"


def test_both_sides_changed_is_a_conflict_and_neither_is_overwritten(fake: FakeCompanion) -> None:
    (job_id,) = _board(("Example North", "Analyst", State.READY))
    _sync("--yes")
    fake.phone_edit(job_id, status="skipped")
    with Storage() as store:
        BoardRepo(store).set_state(job_id, State.APPLIED)
    result = _sync("--yes")
    assert result.exit_code == ExitCode.AGENT_FAILURE
    assert "conflict" in result.output
    assert _state(job_id) == "applied"
    assert fake.rows[str(job_id)]["status"] == "skipped"


def test_a_row_gone_from_the_board_is_removed_hosted(fake: FakeCompanion) -> None:
    keep, drop = _board(
        ("Example North", "Analyst", State.READY), ("Sample Works", "Co-op", State.NEW)
    )
    fake.rows["synthetic-001"] = {"id": "synthetic-001", "status": "ready", "version": 1}
    _sync("--yes")
    with Storage() as store:
        BoardRepo(store).delete(drop)
    assert _sync("--yes").exit_code == 0
    assert set(fake.rows) == {str(keep)}


def test_many_rows_are_split_under_the_body_limit(fake: FakeCompanion) -> None:
    fake.page = 7
    _board(*[(f"Company {i}", f"Role {i}", State.NEW) for i in range(60)])
    assert _sync("--yes").exit_code == 0
    assert len(fake.rows) == 60
    assert all(len(json.dumps(body)) < 16_384 for body in fake.posts)
    assert all(len(body["applications"]) <= 50 for body in fake.posts)
    # A second sync pages through all 60 and finds nothing to do.
    fake.posts.clear()
    result = _sync("--yes")
    assert "Already in agreement" in result.output
    assert fake.posts == []


def test_half_a_configuration_is_refused(monkeypatch: pytest.MonkeyPatch, data_dir: object) -> None:
    monkeypatch.setenv("JOBAGENT_COMPANION_URL", URL)
    for name in (
        "JOBAGENT_SYNC_TOKEN",
        "JOBAGENT_ACCESS_CLIENT_ID",
        "JOBAGENT_ACCESS_CLIENT_SECRET",
    ):
        monkeypatch.delenv(name, raising=False)
    result = _sync()
    assert result.exit_code == ExitCode.USER_ERROR
    assert "JOBAGENT_SYNC_TOKEN" in result.output


def test_only_an_https_origin_is_accepted() -> None:
    for url in ("http://companion.example.invalid", "https://x.example.invalid/api", "companion"):
        with pytest.raises(companion.CompanionNotConfigured):
            CompanionConfig.from_env({**ENV, "JOBAGENT_COMPANION_URL": url})


def test_daily_never_syncs() -> None:
    """`daily` is the cron entry point; sending anything off-machine must stay a human act."""
    assert "sync" not in inspect.getsource(cli.daily)
    assert "companion" not in inspect.getsource(cli.daily)


# -- purge (ADR 0010, precondition 3) ----------------------------------------


def _purge(*args: str) -> Any:
    return CliRunner().invoke(cli.app, ["purge", *args])


def test_purge_empties_the_hosted_copy_then_the_machine(fake: FakeCompanion, data_dir: Any) -> None:
    _board(("Example North", "Analyst", State.READY))
    _sync("--yes")
    result = _purge("--yes")
    assert result.exit_code == 0, result.output
    assert fake.purged and fake.rows == {}
    assert not data_dir.exists()
    # What it cannot reach is said, not implied away.
    assert "Time Travel" in result.output
    assert "Pages deployments" in result.output


def test_purge_stops_before_deleting_anything_if_the_hosted_copy_is_unreachable(
    fake: FakeCompanion, data_dir: Any
) -> None:
    _board(("Example North", "Analyst", State.READY))
    fake.gate = False
    result = _purge("--yes")
    assert result.exit_code == ExitCode.AGENT_FAILURE
    assert "Nothing was deleted" in result.output
    assert data_dir.exists()
    assert not fake.purged


def test_skip_hosted_purges_the_machine_anyway(fake: FakeCompanion, data_dir: Any) -> None:
    _board(("Example North", "Analyst", State.READY))
    fake.gate = False
    result = _purge("--yes", "--skip-hosted")
    assert result.exit_code == 0, result.output
    assert not data_dir.exists()


def test_purge_without_a_companion_is_local_only(
    monkeypatch: pytest.MonkeyPatch, data_dir: Any
) -> None:
    for name in ENV:
        monkeypatch.delenv(name, raising=False)
    _board(("Example North", "Analyst", State.READY))
    result = _purge("--yes")
    assert result.exit_code == 0, result.output
    assert "purging this machine only" in result.output
    assert not data_dir.exists()


def test_purge_without_yes_names_the_hosted_copy(fake: FakeCompanion) -> None:
    result = _purge()
    assert result.exit_code == ExitCode.USER_ERROR
    assert URL in result.output
    assert not fake.purged
