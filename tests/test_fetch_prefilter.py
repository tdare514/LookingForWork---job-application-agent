"""`jobagent fetch` drops clear location and seniority misses before the board (#111).

Dropped postings never reach the board, so the summary line is the only record
of them; these tests hold it to the arithmetic as well as the rows.
"""

from __future__ import annotations

import json
from collections.abc import Callable
from typing import Any

import httpx
import pytest
from typer.testing import CliRunner

from jobagent.cli import main as cli
from jobagent.core.profile import Profile
from jobagent.core.profile import store as store_profile
from jobagent.core.storage import Storage
from jobagent.discovery import http as discovery_http
from jobagent.tracking.repo import BoardRepo

MIXED = [
    ("Risk Analyst Intern", "Toronto, ON"),
    ("Senior Risk Analyst", "San Francisco, CA"),
    ("Risk Analyst Intern", ""),
    ("Senior Risk Analyst", "Toronto, ON"),
]


def _board(jobs: list[tuple[str, str]]) -> dict[str, Any]:
    return {
        "jobs": [
            {
                "id": i,
                "title": title,
                "location": {"name": location},
                "absolute_url": f"https://boards.example.invalid/{i}",
                "updated_at": "2026-09-10T12:00:00Z",
            }
            for i, (title, location) in enumerate(jobs)
        ]
    }


@pytest.fixture()
def serve(monkeypatch: pytest.MonkeyPatch) -> Callable[[dict[str, Any]], None]:
    """Answer every request `fetch` makes with one board body, no network."""

    def install(body: dict[str, Any]) -> None:
        real = discovery_http.PoliteClient

        def client(hosts: set[str], **_: object) -> discovery_http.PoliteClient:
            transport = httpx.MockTransport(lambda _request: httpx.Response(200, json=body))
            return real(hosts, min_interval_seconds=0.0, transport=transport)

        monkeypatch.setattr(discovery_http, "PoliteClient", client)

    return install


def _fetch(*args: str) -> str:
    result = CliRunner().invoke(cli.app, ["fetch", "greenhouse:example", *args])
    assert result.exit_code == 0, result.output
    return " ".join(result.output.split())  # Rich wraps long lines


def _board_rows(store: Storage) -> list[tuple[str, str]]:
    return sorted((job.title, job.location or "") for job in BoardRepo(store).all())


def test_clear_misses_are_dropped_and_counted_per_rule(
    store: Storage,
    make_profile: Callable[..., Profile],
    serve: Callable[[dict[str, Any]], None],
) -> None:
    store_profile(store, make_profile())
    serve(_board(MIXED))

    output = _fetch()

    assert "kept 2 of 4 from greenhouse:example (dropped 1 location, 1 seniority)" in output
    # The unknown location is kept: absence never cuts.
    assert _board_rows(store) == [
        ("Risk Analyst Intern", ""),
        ("Risk Analyst Intern", "Toronto, ON"),
    ]


def test_the_limit_applies_after_the_filter(
    store: Storage,
    make_profile: Callable[..., Profile],
    serve: Callable[[dict[str, Any]], None],
) -> None:
    store_profile(store, make_profile())
    serve(_board([("Risk Analyst Intern", "San Francisco, CA")] * 30 + [MIXED[0]]))

    output = _fetch("--limit", "5")

    assert "kept 1 of 31 from greenhouse:example (dropped 30 location)" in output
    assert _board_rows(store) == [("Risk Analyst Intern", "Toronto, ON")]


def test_the_summary_says_when_the_limit_cuts_passing_postings(
    store: Storage,
    make_profile: Callable[..., Profile],
    serve: Callable[[dict[str, Any]], None],
) -> None:
    store_profile(store, make_profile())
    serve(_board([(f"Risk Analyst Intern {i}", "Toronto, ON") for i in range(4)]))

    output = _fetch("--limit", "3")

    assert (
        "kept 4 of 4 from greenhouse:example (dropped none); the limit takes the first 3" in output
    )
    assert len(_board_rows(store)) == 3


def test_no_prefilter_lands_everything_up_to_the_limit(
    store: Storage,
    make_profile: Callable[..., Profile],
    serve: Callable[[dict[str, Any]], None],
) -> None:
    store_profile(store, make_profile())
    serve(_board(MIXED))

    output = _fetch("--no-prefilter", "--limit", "3")

    assert "kept" not in output
    assert len(_board_rows(store)) == 3


def test_without_a_profile_nothing_is_filtered(
    store: Storage, serve: Callable[[dict[str, Any]], None]
) -> None:
    serve(_board(MIXED))

    output = _fetch()

    assert "No profile stored; fetching without the pre-filter." in output
    assert len(_board_rows(store)) == 4


def test_workday_prefilter_stays_on_the_first_page_before_details(
    store: Storage,
    make_profile: Callable[..., Profile],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Workday must honor the requested limit, then fetch details only for passes."""
    from jobagent.discovery.workday import RBC

    store_profile(store, make_profile())
    jobs = MIXED + [("Risk Analyst Intern", "San Francisco, CA")] * 16
    page = {
        "jobPostings": [
            {
                "title": title,
                "externalPath": f"/job/{index}",
                "locationsText": location,
                "bulletFields": [f"req-{index}"],
            }
            for index, (title, location) in enumerate(jobs)
        ],
        "total": 1800,
    }
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        if request.method == "POST":
            # If a regression asks for more than the first page, stop safely;
            # the request-count assertion below will expose the extra page.
            if json.loads(request.content).get("offset") == 0:
                return httpx.Response(200, json=page)
            return httpx.Response(200, json={"jobPostings": [], "total": 1800})
        return httpx.Response(
            200,
            json={"jobPostingInfo": {"jobDescription": "Role details", "endDate": ""}},
        )

    real = discovery_http.PoliteClient

    def client(hosts: set[str], **_: object) -> discovery_http.PoliteClient:
        return real(hosts, min_interval_seconds=0.0, transport=httpx.MockTransport(handler))

    monkeypatch.setattr(discovery_http, "PoliteClient", client)
    result = CliRunner().invoke(cli.app, ["fetch", RBC.name, "--details"])

    assert result.exit_code == 0, result.output
    list_requests = [request for request in requests if request.method == "POST"]
    detail_requests = [request for request in requests if request.method == "GET"]
    assert len(list_requests) == 1
    assert list_requests[0].url == RBC.endpoint
    assert json.loads(list_requests[0].content) == {
        "appliedFacets": {},
        "limit": 20,
        "offset": 0,
        "searchText": "",
    }
    assert {request.url.path for request in detail_requests} == {
        "/wday/cxs/rbc/rbcearlytalent1/job/0",
        "/wday/cxs/rbc/rbcearlytalent1/job/2",
    }
    assert len(detail_requests) == 2
    assert _board_rows(store) == [
        ("Risk Analyst Intern", ""),
        ("Risk Analyst Intern", "Toronto, ON"),
    ]
