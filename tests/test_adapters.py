"""Workday and Greenhouse adapters.

The Workday fixtures below are real responses captured from live RBC, BMO and
TD tenants on 2026-09-15 (#57), trimmed to a few rows and otherwise unedited.
That matters: the two id defects these tests now pin were invisible against the
hand-written fixtures this file used to carry, because those fixtures were
written from the same wrong assumption as the code.

The loud-failure tests stay. The shape is verified as of one date, not
guaranteed for the next, so a wrong assumption must still fail rather than
produce half-mapped rows.
"""

from __future__ import annotations

import httpx
import pytest

from jobagent.discovery.greenhouse import GreenhouseAdapter
from jobagent.discovery.greenhouse import UnexpectedSchema as GreenhouseSchema
from jobagent.discovery.http import PoliteClient, SourceDeclined
from jobagent.discovery.workday import ALL, BMO, RBC, TD, UnexpectedSchema, WorkdayAdapter

# Captured from https://rbc.wd3.myworkdayjobs.com/wday/cxs/rbc/rbcearlytalent1/jobs
# on 2026-09-15. The first row is a reposted requisition -- note the "-1" its
# path carries and its bulletFields does not.
RBC_LIVE_PAGE = {
    "total": 156,
    "userAuthenticated": False,
    "facets": [],
    "jobPostings": [
        {
            "title": "2027 Winter - GRM, Counterparty Credit Risk Intern (4 Months)",
            "externalPath": (
                "/job/TORONTO-Ontario-Canada/XMLNAME-2027-Winter---GRM--Counterparty-"
                "Credit-Risk-Intern--4-Months-_R-0000186717-1"
            ),
            "locationsText": "TORONTO, Ontario, Canada",
            "postedOn": "Posted Today",
            "bulletFields": ["R-0000186717"],
        },
        {
            "title": "2027 Winter - Technology Analyst Intern (8 Months)",
            "externalPath": (
                "/job/TORONTO-Ontario-Canada/XMLNAME-2027-Winter---Technology-"
                "Analyst-Intern--8-Months-_R-0000187520"
            ),
            "locationsText": "TORONTO, Ontario, Canada",
            "postedOn": "Posted 5 Days Ago",
            "bulletFields": ["R-0000187520"],
        },
    ],
}

# Captured from td.wd3. TD requisition ids contain an underscore, which is what
# broke the old path-splitting derivation.
TD_LIVE_PAGE = {
    "total": 1756,
    "jobPostings": [
        {
            "title": "Bilingual Contact Center Representative",
            "externalPath": (
                "/job/7250-Mile-End-Montreal-Quebec/Bilingual-Contact-Center-"
                "Representative--Canadian-Banking--Easyline_R_1468577-1"
            ),
            "locationsText": "7250 Mile End, Montreal, Quebec",
            "postedOn": "Posted Yesterday",
            "remoteType": "Hybrid",
            "bulletFields": ["R_1468577", "Contact Centre"],
        },
    ],
}

# Captured from bmo.wd3.
BMO_LIVE_PAGE = {
    "total": 1039,
    "jobPostings": [
        {
            "title": "Client Service Associate",
            "externalPath": "/job/Calgary-AB-CAN/Client-Service-Associate_R260026567",
            "locationsText": "Calgary, AB, CAN",
            "postedOn": "Posted Today",
            "bulletFields": ["R260026567"],
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


def test_workday_maps_a_live_rbc_page() -> None:
    postings = RBC.parse_response(RBC_LIVE_PAGE)
    assert [p.title for p in postings] == [
        "2027 Winter - GRM, Counterparty Credit Risk Intern (4 Months)",
        "2027 Winter - Technology Analyst Intern (8 Months)",
    ]
    first = postings[0]
    assert first.company == "RBC"
    assert first.location == "TORONTO, Ontario, Canada"
    assert first.posted_text == "Posted Today"
    assert first.url is not None
    assert first.url.startswith(
        "https://rbc.wd3.myworkdayjobs.com/en-US/rbcearlytalent1/job/TORONTO-Ontario-Canada/"
    )
    assert first.raw["bulletFields"] == ["R-0000186717"]


def test_workday_fetches_through_the_polite_client() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.method == "POST"
        assert "/wday/cxs/rbc/rbcearlytalent1/jobs" in str(request.url)
        return httpx.Response(200, json=RBC_LIVE_PAGE)

    postings = list(RBC.fetch(_client(handler, RBC.hosts), limit=2))
    assert len(postings) == 2


# -- Workday: the id has to survive reposts and underscores -------------------
#
# Both of these came back wrong against live data and neither was caught by the
# hand-written fixtures this file used to carry.


def test_a_repost_keeps_the_original_requisition_id() -> None:
    """Workday appends "-1" to a reposted path; the requisition is unchanged.

    #28 has to collapse a repost into one job with two sightings. It cannot do
    that if the id moves every time the posting is refreshed.
    """
    reposted, fresh = RBC.parse_response(RBC_LIVE_PAGE)
    assert str(reposted.raw["externalPath"]).endswith("-1")
    assert reposted.source_id == "R-0000186717"
    assert fresh.source_id == "R-0000187520"


def test_an_id_containing_an_underscore_is_not_truncated() -> None:
    """TD ids look like `R_1468577`. Splitting the path on "_" loses the prefix."""
    posting = TD.parse_response(TD_LIVE_PAGE)[0]
    assert posting.source_id == "R_1468577"


def test_bmo_ids_map_straight_through() -> None:
    posting = BMO.parse_response(BMO_LIVE_PAGE)[0]
    assert posting.source_id == "R260026567"
    assert posting.company == "BMO"


def test_a_tenant_without_bulletfields_falls_back_to_the_path() -> None:
    """Not every tenant populates bulletFields, so the path is still a fallback."""
    postings = RBC.parse_response(
        {"jobPostings": [{"title": "Analyst", "externalPath": "/job/Toronto/Analyst_R-0000999"}]}
    )
    assert postings[0].source_id == "R-0000999"


def test_the_path_fallback_also_strips_the_repost_suffix() -> None:
    postings = RBC.parse_response(
        {"jobPostings": [{"title": "Analyst", "externalPath": "/job/Toronto/Analyst_R-0000999-2"}]}
    )
    assert postings[0].source_id == "R-0000999"


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


def test_only_banks_that_actually_run_workday_are_registered() -> None:
    """Scotiabank is not one of them.

    jobs.scotiabank.com runs SAP SuccessFactors; the `scotiabank.wd3` tenant
    does not exist, and every candidate site slug returns an identical
    empty-message 422. An adapter that can only ever fail is worse than no
    adapter, because it reads as coverage.
    """
    assert {a.company for a in ALL} == {"RBC", "BMO", "TD"}
    assert "Scotiabank" not in {a.company for a in ALL}
    assert len({a.host for a in ALL}) == len(ALL)
    assert len({a.name for a in ALL}) == len(ALL)


def test_every_adapter_declares_a_rate_limit_and_terms() -> None:
    """The endpoints answered 200 in September. That is reachability, not consent.

    Nothing about a live 200 tells us the terms permit automated access, so this
    stays `unverified` until someone reads them. Loosening it because the fetch
    works would be the wrong lesson to draw from #57.
    """
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


# -- CLI support for Greenhouse sources ----------------------------------------


def test_greenhouse_fetch_through_the_polite_client() -> None:
    """A greenhouse source can be fetched just like a Workday source."""

    def handler(request: httpx.Request) -> httpx.Response:
        assert request.method == "GET"
        assert "/v1/boards/acme/jobs" in str(request.url)
        return httpx.Response(200, json=GREENHOUSE_PAGE)

    adapter = GreenhouseAdapter(board="acme", company="Acme")
    postings = list(adapter.fetch(_client(handler, adapter.hosts), limit=2))
    assert len(postings) == 1
    assert postings[0].company == "Acme"


def test_fetch_selects_a_greenhouse_adapter_with_the_default_company_name() -> None:
    """No --company given: the CLI's own defaulting title-cases the board slug."""
    from jobagent.cli.main import _select_adapters

    adapters = _select_adapters("greenhouse:my-startup", None, ())
    assert len(adapters) == 1
    assert isinstance(adapters[0], GreenhouseAdapter)
    assert adapters[0].board == "my-startup"
    assert adapters[0].company == "My-Startup"


def test_fetch_selects_a_greenhouse_adapter_with_an_explicit_company_name() -> None:
    """--company overrides the title-cased default."""
    from jobagent.cli.main import _select_adapters

    adapters = _select_adapters("greenhouse:my-startup", "My Startup Inc", ())
    assert adapters[0].company == "My Startup Inc"


def test_fetch_rejects_a_greenhouse_source_with_no_board_slug() -> None:
    from jobagent.cli.main import _select_adapters

    with pytest.raises(ValueError, match="invalid greenhouse source"):
        _select_adapters("greenhouse:", None, ())


def test_fetch_all_means_every_workday_tenant_never_greenhouse() -> None:
    """'all' must keep meaning Workday only -- a greenhouse board is opt-in by name."""
    from jobagent.cli.main import _select_adapters

    workday = (RBC, BMO)
    assert _select_adapters("all", None, workday) == list(workday)


def test_fetch_selects_the_named_workday_tenant() -> None:
    from jobagent.cli.main import _select_adapters

    workday = (RBC, BMO)
    assert _select_adapters("workday:rbc", None, workday) == [RBC]


def test_fetch_finds_nothing_for_an_unknown_source() -> None:
    from jobagent.cli.main import _select_adapters

    assert _select_adapters("nonsense", None, (RBC,)) == []


def test_greenhouse_adapter_fails_on_unknown_board_with_unambiguous_error() -> None:
    """An unknown greenhouse board fails with a clear schema error."""

    def handler(request: httpx.Request) -> httpx.Response:
        # Simulate a 404 or unexpected response from a non-existent board
        return httpx.Response(200, json={"error": "board not found"})

    adapter = GreenhouseAdapter(board="nonexistent", company="Nonexistent")
    with pytest.raises(GreenhouseSchema, match="no 'jobs'"):
        list(adapter.fetch(_client(handler, adapter.hosts), limit=5))
