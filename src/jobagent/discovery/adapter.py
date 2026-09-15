"""The source adapter contract.

An adapter maps one job source into the canonical shape the board understands.
It declares where it fetches from and how fast; it never opens a connection
itself. That is what makes the rate limit and the allowlist enforceable rather
than advisory.

Adding a source means writing one adapter and registering it. Nothing else in
the codebase should learn a source's name.
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass, field
from typing import Protocol

from jobagent.discovery.http import PoliteClient


@dataclass(frozen=True)
class RawPosting:
    """One posting as the source described it, before any interpretation.

    `raw` is kept so a mapping bug can be fixed without re-fetching, and so a
    field this version ignores is still recoverable later.

    The detail fields below are optional because most sources describe a posting
    in two calls: a list, then the posting itself. A row from the list alone is
    still a useful row.
    """

    source: str
    source_id: str
    title: str
    company: str
    location: str | None = None
    url: str | None = None
    posted_text: str | None = None
    # Populated only by a detail fetch, which is opt-in because it costs one
    # request per posting. A list-only fetch leaves these None, and everything
    # downstream has to keep working when they are.
    description: str | None = None
    deadline: str | None = None
    employment_type: str | None = None
    raw: dict[str, object] = field(default_factory=dict)


@dataclass(frozen=True)
class SourceTerms:
    """What was checked before this adapter was written.

    Recorded in code rather than in someone's memory, because "is this source
    allowed" is a question that gets asked again in six months.
    """

    allows_automated_access: str
    checked_on: str
    notes: str = ""


class Adapter(Protocol):
    """What every source must provide."""

    name: str
    hosts: set[str]
    min_interval_seconds: float
    terms: SourceTerms

    def fetch(self, client: PoliteClient, *, limit: int) -> Iterable[RawPosting]:
        """Yield postings, newest first where the source permits it."""
        ...


_REGISTRY: dict[str, Adapter] = {}


def register(adapter: Adapter) -> Adapter:
    if adapter.name in _REGISTRY:
        raise ValueError(f"adapter already registered: {adapter.name}")
    _REGISTRY[adapter.name] = adapter
    return adapter


def get(name: str) -> Adapter | None:
    return _REGISTRY.get(name)


def registered() -> list[Adapter]:
    return sorted(_REGISTRY.values(), key=lambda a: a.name)


def allowed_hosts() -> set[str]:
    """Every host any registered adapter may reach -- the allowlist, derived."""
    hosts: set[str] = set()
    for adapter in _REGISTRY.values():
        hosts |= {h.lower() for h in adapter.hosts}
    return hosts


def clear_registry_for_tests() -> None:
    _REGISTRY.clear()
