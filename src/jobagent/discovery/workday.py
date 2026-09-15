"""Workday adapter.

Workday careers sites are backed by a public, unauthenticated JSON endpoint --
the same call the browser makes when you page through listings:

    POST https://{tenant}.wd{N}.myworkdayjobs.com/wday/cxs/{tenant}/{site}/jobs

That is the site's own public API, not scraped HTML and not a bypass of
anything. It matters here because RBC, BMO and TD run Workday, and they are
among the employers this tool exists to chase.

If a tenant fronts that endpoint with bot protection it will answer 401 or 403,
and PoliteClient raises rather than retrying. That is the correct outcome: the
source declined, so we use a different route (the Claude in Chrome handoff)
rather than arguing with it.

Verified against live tenants on 2026-09-15 (see #57). RBC, BMO and TD each
answered 200 with the documented shape: top-level `facets` / `jobPostings` /
`total` / `userAuthenticated`, and postings carrying `title`, `externalPath`,
`locationsText`, `postedOn` and `bulletFields`. The constructed posting URLs
resolve. An earlier 403 recorded here came from the build container's proxy,
not from a tenant.

Reachability is not permission. A 200 says the endpoint answered; it says
nothing about whether the terms allow automated access, so `terms` still reads
`unverified` and that is not an oversight.

`parse_response` still validates hard and raises with the offending payload's
keys named, because the shape is verified as of one date, not guaranteed for
the next one. A loud failure is recoverable; a board quietly full of rows
titled "None" is not.
"""

from __future__ import annotations

import re
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
                    source_id=_requisition_id(entry, str(path)),
                    title=str(title),
                    company=self.company,
                    location=_first_str(entry, "locationsText", "locations"),
                    url=self.posting_url(str(path)),
                    posted_text=_first_str(entry, "postedOn", "startDate"),
                    raw=entry,
                )
            )
        return out


# Workday appends "-1", "-2", ... to the path of a requisition that has been
# reposted. Live RBC pages carry it on roughly a third of rows.
#
# Bounded to one or two digits on purpose. RBC ids are themselves "R-0000186717"
# -- a greedy `-\d+$` strips the id down to "R". Two digits is more repost
# counter than any real posting needs, and erring short is the safe direction:
# a missed strip leaves two rows to merge by hand, an over-eager one silently
# fuses two different requisitions.
_REPOST_SUFFIX = re.compile(r"-\d{1,2}$")


def _requisition_id(entry: dict[str, Any], path: str) -> str:
    """The stable id for a posting, preferring what the tenant states outright.

    `bulletFields[0]` is the requisition id on every live tenant checked, and it
    is the only source that survives two things the path does not:

    - **Underscores inside the id.** TD's ids look like `R_1468577`, so taking
      the path's last underscore-delimited segment yields `1468577` and drops
      the prefix.
    - **Reposts.** A reposted requisition gets `-1` appended to its path while
      `bulletFields` keeps the original id. Deriving from the path would make a
      repost look like a different job, which is exactly the case #28 has to
      collapse into one job with two sightings.

    Not every tenant populates `bulletFields`, so the path remains the fallback
    -- with the repost suffix stripped, so at least reposts still collapse.
    """
    bullets = entry.get("bulletFields")
    if isinstance(bullets, list) and bullets:
        first = bullets[0]
        if isinstance(first, str) and first.strip():
            return first.strip()
    tail = path.rsplit("/", 1)[-1].rsplit("_", 1)[-1]
    trimmed = _REPOST_SUFFIX.sub("", tail)
    # If trimming left nothing identifying behind, the match was part of the id.
    if trimmed and any(c.isdigit() for c in trimmed):
        return trimmed
    return tail or path


def _first_str(entry: dict[str, Any], *keys: str) -> str | None:
    for key in keys:
        value = entry.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    return None


# The Canadian banks this tool targets that actually run Workday. Tenants are
# configured independently, so one declining says nothing about the others.
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
# Scotiabank is deliberately absent. It is not on Workday: jobs.scotiabank.com
# runs SAP SuccessFactors (hcm17.sapsf.com) and the page carries no Workday
# reference, which is why every candidate `scotiabank.wd3` site slug returns an
# identical empty-message 422 -- the tenant does not exist. No slug fixes that.
# Scotiabank closes 2026-10-02; the Claude in Chrome handoff is its route until
# a SuccessFactors adapter earns its place.
TD = WorkdayAdapter(
    name="workday:td",
    company="TD",
    tenant="td",
    site="TD_Bank_Careers",
    host="td.wd3.myworkdayjobs.com",
)

ALL: tuple[WorkdayAdapter, ...] = (RBC, BMO, TD)
