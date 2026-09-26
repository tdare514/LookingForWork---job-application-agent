"""`--verbose` shows each request on stderr, and never a secret (#121).

Assertions read the runner's stderr and stdout, not pytest's log capture:
capture raises the root level itself, so a test reading it would pass whether
or not the flag did anything.
"""

from __future__ import annotations

import logging
from collections.abc import Iterator

import httpx
import pytest
from typer.testing import CliRunner, Result

from jobagent.cli import main as cli
from jobagent.companion import client as companion
from jobagent.discovery import http as discovery_http

TOKEN = "synthetic-sync-token-0123456789abcdef"
ACCESS_SECRET = "synthetic-access-secret-0123456789"
URL = "https://companion.example.invalid"


@pytest.fixture(autouse=True)
def quiet_logger() -> Iterator[None]:
    """Each test starts, and leaves, the `jobagent` logger as it found it.

    The verbose handler holds the runner's stderr, which closes when the
    invocation ends; left attached, it would break every later test that logs.
    """
    logger = logging.getLogger("jobagent")
    handlers, level = list(logger.handlers), logger.level
    yield
    logger.handlers[:] = handlers
    logger.setLevel(level)


@pytest.fixture()
def board(monkeypatch: pytest.MonkeyPatch, data_dir: object) -> None:
    """One Greenhouse posting behind a mock transport; no network."""
    body = {
        "jobs": [
            {
                "id": 1,
                "title": "Risk Analyst Intern",
                "location": {"name": "Toronto, ON"},
                "absolute_url": "https://boards.example.invalid/1",
                "updated_at": "2026-09-10T12:00:00Z",
            }
        ]
    }
    real = discovery_http.PoliteClient

    def client(hosts: set[str], **_: object) -> discovery_http.PoliteClient:
        transport = httpx.MockTransport(lambda _request: httpx.Response(200, json=body))
        return real(hosts, min_interval_seconds=0.0, transport=transport)

    monkeypatch.setattr(discovery_http, "PoliteClient", client)


def _run(*args: str) -> Result:
    return CliRunner().invoke(cli.app, list(args))


REQUEST_LINE = "GET boards-api.greenhouse.io/v1/boards/example/jobs 200"


def test_verbose_puts_the_request_on_stderr_and_leaves_stdout_alone(board: None) -> None:
    result = _run("--verbose", "fetch", "greenhouse:example", "--no-prefilter")

    assert result.exit_code == 0, result.output
    assert REQUEST_LINE in result.stderr
    assert "attempt=0" in result.stderr
    assert "GET" not in result.stdout
    # The endpoint is `...?content=true`; the query string stays out.
    assert "content=true" not in result.stderr


def test_without_verbose_there_is_no_request_line(board: None) -> None:
    result = _run("fetch", "greenhouse:example", "--no-prefilter")

    assert result.exit_code == 0, result.output
    assert "GET" not in result.output


def test_running_twice_in_one_process_keeps_one_handler(board: None) -> None:
    """A second handler would print every line twice, the first to a dead stream."""
    before = len(logging.getLogger("jobagent").handlers)
    _run("--verbose", "fetch", "greenhouse:example", "--no-prefilter")
    _run("--verbose", "fetch", "greenhouse:example", "--no-prefilter")

    assert len(logging.getLogger("jobagent").handlers) == before + 1


class FakeCompanion:
    """Access in front, then a sync endpoint that answers with an empty board."""

    def __init__(self, gate: bool) -> None:
        self.gate = gate

    def handle(self, request: httpx.Request) -> httpx.Response:
        if "authorization" not in request.headers:
            if self.gate:
                return httpx.Response(403)  # Access, to a non-browser
            return httpx.Response(200, text="open to anyone")
        if request.url.path == "/api/sync":
            return httpx.Response(200, json={"applications": [], "next": None})
        return httpx.Response(404)


def _companion(monkeypatch: pytest.MonkeyPatch, gate: bool) -> None:
    for name, value in {
        "JOBAGENT_COMPANION_URL": URL,
        "JOBAGENT_SYNC_TOKEN": TOKEN,
        "JOBAGENT_ACCESS_CLIENT_ID": "synthetic.access",
        "JOBAGENT_ACCESS_CLIENT_SECRET": ACCESS_SECRET,
    }.items():
        monkeypatch.setenv(name, value)
    server = FakeCompanion(gate)
    monkeypatch.setattr(
        companion,
        "connect",
        lambda config: companion.CompanionClient(
            config, transport=httpx.MockTransport(server.handle)
        ),
    )


def test_a_companion_call_is_logged_without_its_credentials(
    monkeypatch: pytest.MonkeyPatch, data_dir: object
) -> None:
    _companion(monkeypatch, gate=True)

    result = _run("--verbose", "sync")

    assert result.exit_code == 0, result.output
    assert "GET /api/sync 200" in result.stderr
    for secret in (TOKEN, ACCESS_SECRET):
        assert secret not in result.stdout
        assert secret not in result.stderr


def test_a_refused_companion_call_does_not_leak_credentials_either(
    monkeypatch: pytest.MonkeyPatch, data_dir: object
) -> None:
    _companion(monkeypatch, gate=False)

    result = _run("--verbose", "sync")

    assert result.exit_code != 0
    assert "not the Cloudflare Access login" in result.output
    for secret in (TOKEN, ACCESS_SECRET):
        assert secret not in result.stdout
        assert secret not in result.stderr
