"""Greenhouse adapter.

Greenhouse publishes a documented, keyless board API:

    GET https://boards-api.greenhouse.io/v1/boards/{board}/jobs

It is the one source in this project whose automated access is unambiguous --
the endpoint exists to be consumed programmatically. It covers startups and
scale-ups rather than the Canadian banks, so it complements Workday instead of
replacing it.
"""

from __future__ import annotations

import html as html_module
from collections.abc import Iterable
from dataclasses import dataclass
from typing import Any

from jobagent.discovery.adapter import RawPosting, SourceTerms
from jobagent.discovery.http import PoliteClient
from jobagent.discovery.text import html_to_text

HOST = "boards-api.greenhouse.io"


class UnexpectedSchema(RuntimeError):
    """The board response did not look like a Greenhouse listing."""


@dataclass(frozen=True)
class GreenhouseAdapter:
    """One Greenhouse board, identified by its slug."""

    board: str
    company: str
    min_interval_seconds: float = 1.0
    terms: SourceTerms = SourceTerms(
        allows_automated_access="yes - documented public board API, no key required",
        checked_on="2026-09-15",
        notes="Greenhouse publishes this endpoint for programmatic use.",
    )

    @property
    def name(self) -> str:
        return f"greenhouse:{self.board}"

    @property
    def hosts(self) -> set[str]:
        return {HOST}

    @property
    def endpoint(self) -> str:
        # Request content=true to get HTML descriptions in each job's content field.
        # Greenhouse's API returns escaped HTML that must be unescaped before parsing.
        return f"https://{HOST}/v1/boards/{self.board}/jobs?content=true"

    def fetch(self, client: PoliteClient, *, limit: int = 50) -> Iterable[RawPosting]:
        body = client.get_json(self.endpoint)
        if not isinstance(body, dict):
            raise UnexpectedSchema(f"{self.name}: expected an object, got a list")
        return self.parse_response(body)[:limit]

    def parse_response(self, body: dict[str, Any]) -> list[RawPosting]:
        if "jobs" not in body:
            raise UnexpectedSchema(
                f"{self.name}: response has no 'jobs'. Keys were: {sorted(body)[:12]}"
            )
        jobs = body["jobs"]
        if not isinstance(jobs, list):
            raise UnexpectedSchema(f"{self.name}: 'jobs' is {type(jobs).__name__}, expected a list")

        out: list[RawPosting] = []
        for entry in jobs:
            if not isinstance(entry, dict):
                raise UnexpectedSchema(f"{self.name}: a job was {type(entry).__name__}")
            title = entry.get("title")
            job_id = entry.get("id")
            if not title or job_id is None:
                raise UnexpectedSchema(
                    f"{self.name}: job missing title or id. Keys were: {sorted(entry)[:12]}"
                )
            location = entry.get("location")
            # Extract content from the job entry if present. Greenhouse returns escaped HTML
            # (e.g., &lt;p&gt;...) which must be unescaped before parsing to plain text.
            # `or None` as Workday does: markup that renders to nothing is no
            # description, and an empty string would read downstream as one.
            content = entry.get("content")
            description = (
                html_to_text(html_module.unescape(content)) or None
                if isinstance(content, str)
                else None
            )
            out.append(
                RawPosting(
                    source=self.name,
                    source_id=str(job_id),
                    title=str(title),
                    company=self.company,
                    location=(
                        str(location.get("name"))
                        if isinstance(location, dict) and location.get("name")
                        else None
                    ),
                    url=str(entry.get("absolute_url")) if entry.get("absolute_url") else None,
                    posted_text=str(entry.get("updated_at")) if entry.get("updated_at") else None,
                    description=description,
                    raw=entry,
                )
            )
        return out
