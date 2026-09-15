"""Posting descriptions and closing dates (#62).

The list endpoint gives a row; the detail endpoint gives the posting. The field
that earns this is `endDate` -- the application deadline, which the board has had
a column for since M0002 and which only a human ever filled in.

The detail payload below is a real RBC response captured on 2026-09-15, trimmed.
"""

from __future__ import annotations

import httpx
import pytest

from jobagent.discovery.adapter import RawPosting
from jobagent.discovery.http import PoliteClient, SourceDeclined
from jobagent.discovery.text import html_to_text
from jobagent.discovery.workday import RBC, UnexpectedSchema

DETAIL_PAYLOAD = {
    "userAuthenticated": False,
    "hiringOrganization": {"name": "RBC"},
    "jobPostingInfo": {
        "id": "abc",
        "title": "2027 Winter - GRM, Counterparty Credit Risk Intern (4 Months)",
        "jobReqId": "R-0000186717",
        "jobDescription": (
            "<div><p><b>What is the opportunity?</b></p>"
            "<p>Support Counterparty Credit Risk portfolio analytics.</p>"
            "<p><b>Must-have</b></p><ul><li>Value-at-Risk measurement</li>"
            "<li>Python&nbsp;and SQL</li></ul></div>"
        ),
        "startDate": "2026-09-15",
        "endDate": "2026-09-21",
        "timeType": "Full time",
        "country": {"descriptor": "Canada"},
    },
}

LIST_POSTING = RawPosting(
    source="workday:rbc",
    source_id="R-0000186717",
    title="2027 Winter - GRM, Counterparty Credit Risk Intern (4 Months)",
    company="RBC",
    raw={"externalPath": "/job/TORONTO-Ontario-Canada/Intern_R-0000186717-1"},
)


def _client(handler: object, hosts: set[str]) -> PoliteClient:
    return PoliteClient(
        hosts,
        min_interval_seconds=0.0,
        transport=httpx.MockTransport(handler),  # type: ignore[arg-type]
    )


# -- the detail fetch ---------------------------------------------------------


def test_the_closing_date_comes_back_as_the_deadline() -> None:
    """The reason this exists. Everything else is a bonus."""

    def handler(request: httpx.Request) -> httpx.Response:
        assert "/wday/cxs/rbc/rbcearlytalent1/job/" in str(request.url)
        return httpx.Response(200, json=DETAIL_PAYLOAD)

    filled = RBC.fetch_detail(_client(handler, RBC.hosts), LIST_POSTING)
    assert filled.deadline == "2026-09-21"
    assert filled.employment_type == "Full time"


def test_the_description_arrives_as_text_not_markup() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=DETAIL_PAYLOAD)

    filled = RBC.fetch_detail(_client(handler, RBC.hosts), LIST_POSTING)
    assert filled.description is not None
    assert "<" not in filled.description
    assert "Must-have" in filled.description
    assert "- Value-at-Risk measurement" in filled.description


def test_the_original_posting_is_not_mutated() -> None:
    """A failure downstream must cost the detail, not the row."""

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=DETAIL_PAYLOAD)

    RBC.fetch_detail(_client(handler, RBC.hosts), LIST_POSTING)
    assert LIST_POSTING.deadline is None
    assert LIST_POSTING.description is None


def test_the_raw_detail_is_kept_alongside_the_list_row() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=DETAIL_PAYLOAD)

    filled = RBC.fetch_detail(_client(handler, RBC.hosts), LIST_POSTING)
    assert filled.raw["externalPath"] == LIST_POSTING.raw["externalPath"]
    assert filled.raw["jobPostingInfo"]["jobReqId"] == "R-0000186717"  # type: ignore[index]


def test_an_unexpected_detail_shape_names_what_it_got() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"posting": {}, "meta": {}})

    with pytest.raises(UnexpectedSchema, match="no 'jobPostingInfo'"):
        RBC.fetch_detail(_client(handler, RBC.hosts), LIST_POSTING)


def test_a_declining_tenant_still_stops_the_adapter() -> None:
    """The boundary from #58 and ADR 0008 does not get a detail-shaped exception."""

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(403)

    with pytest.raises(SourceDeclined):
        RBC.fetch_detail(_client(handler, RBC.hosts), LIST_POSTING)


def test_a_posting_with_no_path_is_returned_unchanged() -> None:
    """Nothing to fetch is not an error."""
    bare = RawPosting(source="workday:rbc", source_id="x", title="Analyst", company="RBC")
    calls = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        return httpx.Response(200, json=DETAIL_PAYLOAD)

    assert RBC.fetch_detail(_client(handler, RBC.hosts), bare) is bare
    assert calls == 0


# -- html_to_text -------------------------------------------------------------


def test_list_items_keep_their_structure() -> None:
    """A requirement on its own line is a different parse from mid-paragraph."""
    text = html_to_text("<ul><li>Python</li><li>SQL</li></ul>")
    assert text.splitlines() == ["- Python", "- SQL"]


def test_deeply_nested_divs_do_not_become_a_page_of_blank_lines() -> None:
    """Workday wraps one paragraph in roughly forty bare divs."""
    text = html_to_text("<div>" * 40 + "<p>Hello</p>" + "</div>" * 40)
    assert text == "Hello"


def test_entities_and_non_breaking_spaces_are_decoded() -> None:
    """A stray \\xa0 breaks every regex downstream of here."""
    text = html_to_text("<p>Python&nbsp;&amp;&nbsp;SQL</p>")
    assert text == "Python & SQL"
    assert "\xa0" not in text


def test_script_and_style_content_is_dropped() -> None:
    text = html_to_text("<div><script>var x = 1;</script><p>Real text</p></div>")
    assert "var x" not in text
    assert text == "Real text"


def test_missing_or_empty_html_is_empty_text_not_a_crash() -> None:
    assert html_to_text(None) == ""
    assert html_to_text("") == ""


def test_malformed_markup_still_yields_its_text() -> None:
    """Third-party HTML written by whoever pasted into the requisition form."""
    assert "Analyst" in html_to_text("<p>Analyst<div><b>unclosed")
