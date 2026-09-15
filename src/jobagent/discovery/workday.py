"""Workday adapter.

Workday careers sites are backed by a public, unauthenticated JSON endpoint --
the same call the browser makes when you page through listings:

    POST https://{tenant}.wd{N}.myworkdayjobs.com/wday/cxs/{tenant}/{site}/jobs

That is the site's own public API, not scraped HTML and not a bypass of
anything. It matters here because RBC, BMO, Scotiabank and TD all run Workday,
and they are the employers this tool exists to chase.

If a tenant fronts that endpoint with bot protection it will answer 401 or 403,
and PoliteClient raises rather than retrying. That is the correct outcome: the
source declined, so we use a different route (the Claude in Chrome handoff)
rather than arguing with it.

**The field mapping below is written against Workday's documented CXS response
shape and has NOT been verified against a live tenant from this environment --
outbound network access is blocked here.** Rather than let a wrong assumption
produce silently mismapped rows, `parse_response` validates hard and raises with
the offending payload's keys named. A loud failure on first run is recoverable;
a board quietly full of rows titled "None" is not.
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from typing import Any

from jobagent.discovery.adapter import RawPosting, SourceTerms
from jobagent.discovery.http import PoliteClient

PAGE_SIZE = 20


class UnexpectedSchema(RuntimeError):
    """The response did not look like a Workday job listing.

    Raised instead of returning partial rows: a mapping that half-works is worse
    than one that fails, because nobody notices it.
    """


@dataclass(frozen=True)
class WorkdayAdapter:
    """One Workday tenant. RBC, BMO and the rest are instances, not subclasses."""

    name: str
    company: str
    tenant: str
    site: str
    host: str
    min_interval_seconds: float = 2.0
    terms: SourceTerms = SourceTerms(
        allows_automated_access="unverified - public careers endpoint, no auth required",
        checked_on="2026-09-15",
        notes=(
            "Reads the careers site's own public JSON endpoint. A 401/403 is "
            "treated as a refusal and stops the adapter; no circumvention."
        ),
    )

    @property
    def hosts(self) -> set[str]:
        return {self.host}

    @property
    def endpoint(self) -> str:
        return f"https://{self.host}/wday/cxs/{self.tenant}/{self.site}/jobs"

    def posting_url(self, external_path: str) -> str:
        return f"https://{self.host}/en-US/{self.site}{external_path}"

    def fetch(self, client: PoliteClient, *, limit: int = PAGE_SIZE) -> Iterable[RawPosting]:
        collected: list[RawPosting] = []
        offset = 0
        while len(collected) < limit:
            body = client.post_json(
                self.endpoint,
                {
                    "appliedFacets": {},
                    "limit": min(PAGE_SIZE, limit - len(collected)),
                    "offset": offset,
                    "searchText": "",
                },
            )
            page = self.parse_response(body)
            if not page:
                break
            collected.extend(page)
            offset += len(page)
        return collected[:limit]

    def parse_response(self, body: dict[str, Any]) -> list[RawPosting]:
        if "jobPostings" not in body:
            raise UnexpectedSchema(
                f"{self.name}: response has no 'jobPostings'. Keys were: "
                f"{sorted(body)[:12]}. The endpoint shape may have changed."
            )
        postings = body["jobPostings"]
        if not isinstance(postings, list):
            raise UnexpectedSchema(
                f"{self.name}: 'jobPostings' is {type(postings).__name__}, expected a list"
            )

        out: list[RawPosting] = []
        for entry in postings:
            if not isinstance(entry, dict):
                raise UnexpectedSchema(f"{self.name}: a posting was {type(entry).__name__}")
            title = entry.get("title")
            path = entry.get("externalPath")
            if not title or not path:
                raise UnexpectedSchema(
                    f"{self.name}: posting missing title or externalPath. "
                    f"Keys were: {sorted(entry)[:12]}"
                )
            out.append(
                RawPosting(
                    source=self.name,
                    # externalPath ends in the requisition id and is stable;
                    # bulletFields is where Workday usually repeats it, but not
                    # every tenant populates it, so the path is the safer key.
                    source_id=str(path).rsplit("_", 1)[-1] or str(path),
                    title=str(title),
                    company=self.company,
                    location=_first_str(entry, "locationsText", "locations"),
                    url=self.posting_url(str(path)),
                    posted_text=_first_str(entry, "postedOn", "startDate"),
                    raw=entry,
                )
            )
        return out


def _first_str(entry: dict[str, Any], *keys: str) -> str | None:
    for key in keys:
        value = entry.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    return None


# The four Canadian banks this tool actually targets. Tenants are configured
# independently, so one declining says nothing about the others.
RBC = WorkdayAdapter(
    name="workday:rbc",
    company="RBC",
    tenant="rbc",
    site="rbcearlytalent1",
    host="rbc.wd3.myworkdayjobs.com",
)
BMO = WorkdayAdapter(
    name="workday:bmo",
    company="BMO",
    tenant="bmo",
    site="External",
    host="bmo.wd3.myworkdayjobs.com",
)
SCOTIABANK = WorkdayAdapter(
    name="workday:scotiabank",
    company="Scotiabank",
    tenant="scotiabank",
    site="Scotiabank_Careers",
    host="scotiabank.wd3.myworkdayjobs.com",
)
TD = WorkdayAdapter(
    name="workday:td",
    company="TD",
    tenant="td",
    site="TD_Bank_Careers",
    host="td.wd3.myworkdayjobs.com",
)

ALL: tuple[WorkdayAdapter, ...] = (RBC, BMO, SCOTIABANK, TD)
