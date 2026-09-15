"""Workday and Greenhouse adapters.

The Workday mapping is written against the documented CXS shape but was never
verified against a live tenant -- outbound network is blocked in the build
environment. So the tests concentrate on the thing that protects us from that:
a wrong assumption must FAIL LOUDLY, never produce half-mapped rows.
"""

from __future__ import annotations

import httpx
import pytest

from jobagent.discovery.greenhouse import GreenhouseAdapter
from jobagent.discovery.greenhouse import UnexpectedSchema as GreenhouseSchema
from jobagent.discovery.http import PoliteClient, SourceDeclined
from jobagent.discovery.workday import ALL, RBC, UnexpectedSchema, WorkdayAdapter

WORKDAY_PAGE = {
    "total": 2,
    "jobPostings": [
        {
            "title": "Business Analyst, Winter 2027",
            "externalPath": "/job/Toronto-Ontario-Canada/Business-Analyst_R-0000123",
            "locationsText": "Toronto, Ontario, Canada",
            "postedOn": "Posted 5 Days Ago",
            "bulletFields": ["R-0000123"],
        },
        {
            "title": "Technical Systems Analyst",
            "externalPath": "/job/Toronto/Tech-Systems-Analyst_R-0000456",
            "locationsText": "Toronto, Ontario, Canada",
            "postedOn": "Posted Today",
        },
    ],
}

GREENHOUSE_PAGE = {
    "jobs": [
        {
            "id": 4567,
            "title": "Product Analyst Intern",
            "location": {"name": "Toronto, ON"},
            "absolute_url": "https://boards.greenhouse.io/acme/jobs/4567",
            "updated_at": "2026-09-10T12:00:00Z",
        }
    ]
}


def _client(handler: object, hosts: set[str]) -> PoliteClient:
    return PoliteClient(
        hosts,
        min_interval_seconds=0.0,
        transport=httpx.MockTransport(handler),  # type: ignore[arg-type]
    )


# -- Workday: the happy path --------------------------------------------------


def test_workday_maps_a_documented_page() -> None:
    postings = RBC.parse_response(WORKDAY_PAGE)
    assert [p.title for p in postings] == [
        "Business Analyst, Winter 2027",
        "Technical Systems Analyst",
    ]
    first = postings[0]
    assert first.company == "RBC"
    assert first.source_id == "R-0000123"
    assert first.location == "Toronto, Ontario, Canada"
    assert first.url == (
        "https://rbc.wd3.myworkdayjobs.com/en-US/rbcearlytalent1"
        "/job/Toronto-Ontario-Canada/Business-Analyst_R-0000123"
    )
    assert first.raw["bulletFields"] == ["R-0000123"]


def test_workday_fetches_through_the_polite_client() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.method == "POST"
        assert "/wday/cxs/rbc/rbcearlytalent1/jobs" in str(request.url)
        return httpx.Response(200, json=WORKDAY_PAGE)

    postings = list(RBC.fetch(_client(handler, RBC.hosts), limit=2))
    assert len(postings) == 2


# -- Workday: a wrong assumption must fail loudly -----------------------------


def test_a_missing_jobpostings_key_names_what_it_actually_got() -> None:
    """If the endpoint shape differs from the documented one, say so."""
    with pytest.raises(UnexpectedSchema, match="no 'jobPostings'"):
        RBC.parse_response({"items": [], "count": 0})


def test_a_posting_missing_required_fields_raises_rather_than_half_mapping() -> None:
    """A board quietly full of rows titled 'None' is worse than a crash."""
    with pytest.raises(UnexpectedSchema, match="missing title or externalPath"):
        RBC.parse_response({"jobPostings": [{"locationsText": "Toronto"}]})


def test_a_wrong_shaped_jobpostings_raises() -> None:
    with pytest.raises(UnexpectedSchema, match="expected a list"):
        RBC.parse_response({"jobPostings": {"title": "x"}})


def test_a_tenant_that_declines_stops_the_adapter(caplog: object) -> None:
    """Bot protection answers 403. That is a stop signal, not a puzzle."""

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(403)

    with pytest.raises(SourceDeclined, match="declined automated access"):
        list(RBC.fetch(_client(handler, RBC.hosts), limit=5))


# -- Workday: the tenants -----------------------------------------------------


def test_the_four_banks_are_configured_and_distinct() -> None:
    assert {a.company for a in ALL} == {"RBC", "BMO", "Scotiabank", "TD"}
    assert len({a.host for a in ALL}) == 4
    assert len({a.name for a in ALL}) == 4


def test_every_adapter_declares_a_rate_limit_and_terms() -> None:
    for adapter in ALL:
        assert adapter.min_interval_seconds >= 1.0
        assert adapter.terms.checked_on
        assert "unverified" in adapter.terms.allows_automated_access


def test_a_new_tenant_needs_no_new_class() -> None:
    """Adding a bank is configuration, not code."""
    other = WorkdayAdapter(
        name="workday:other",
        company="Other Bank",
        tenant="other",
        site="Careers",
        host="other.wd1.myworkdayjobs.com",
    )
    assert other.endpoint == "https://other.wd1.myworkdayjobs.com/wday/cxs/other/Careers/jobs"


# -- Greenhouse ---------------------------------------------------------------


def test_greenhouse_maps_its_documented_shape() -> None:
    adapter = GreenhouseAdapter(board="acme", company="Acme")
    postings = adapter.parse_response(GREENHOUSE_PAGE)
    assert len(postings) == 1
    assert postings[0].source_id == "4567"
    assert postings[0].location == "Toronto, ON"
    assert postings[0].url == "https://boards.greenhouse.io/acme/jobs/4567"


def test_greenhouse_tolerates_a_missing_location() -> None:
    """Remote roles legitimately have no location. That is not a schema error."""
    adapter = GreenhouseAdapter(board="acme", company="Acme")
    postings = adapter.parse_response({"jobs": [{"id": 1, "title": "Analyst"}]})
    assert postings[0].location is None


def test_greenhouse_raises_on_an_unexpected_shape() -> None:
    adapter = GreenhouseAdapter(board="acme", company="Acme")
    with pytest.raises(GreenhouseSchema, match="no 'jobs'"):
        adapter.parse_response({"results": []})


def test_greenhouse_terms_are_unambiguous_unlike_workdays() -> None:
    """The one source whose automated access is documented, not inferred."""
    adapter = GreenhouseAdapter(board="acme", company="Acme")
    assert adapter.terms.allows_automated_access.startswith("yes")
