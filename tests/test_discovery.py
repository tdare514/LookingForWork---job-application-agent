"""The polite client and the adapter contract.

Most of these are about restraint: what the client refuses to do.
"""

from __future__ import annotations

from collections.abc import Iterable

import httpx
import pytest

from jobagent.discovery.adapter import (
    Adapter,
    RawPosting,
    SourceTerms,
    allowed_hosts,
    clear_registry_for_tests,
    get,
    register,
    registered,
)
from jobagent.discovery.http import (
    USER_AGENT,
    HostNotAllowed,
    PoliteClient,
    SourceDeclined,
)


def _client(handler: object, **kwargs: object) -> PoliteClient:
    return PoliteClient(
        {"example.com"},
        min_interval_seconds=0.0,
        transport=httpx.MockTransport(handler),  # type: ignore[arg-type]
        **kwargs,  # type: ignore[arg-type]
    )


# -- what it refuses ----------------------------------------------------------


def test_a_host_off_the_allowlist_is_refused() -> None:
    """No adapter may quietly reach somewhere nobody reviewed."""
    client = _client(lambda r: httpx.Response(200, json={}))
    with pytest.raises(HostNotAllowed, match="allowlist"):
        client.get_json("https://not-reviewed.example.org/jobs")


@pytest.mark.parametrize("status", [401, 403])
def test_a_declined_request_stops_rather_than_retrying(status: int) -> None:
    """A 403 means the source declined. Retrying it is circumvention.

    This is the boundary in docs/architecture.md, so it is a test, not a note.
    """
    calls = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        return httpx.Response(status)

    client = _client(handler)
    with pytest.raises(SourceDeclined, match="declined automated access"):
        client.get_json("https://example.com/jobs")
    assert calls == 1, "a declined request must not be retried"


def test_the_user_agent_identifies_the_tool() -> None:
    """A client that hides what it is has already decided it is misbehaving."""
    seen: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request.headers["User-Agent"])
        return httpx.Response(200, json={"ok": True})

    _client(handler).get_json("https://example.com/jobs")
    assert seen == [USER_AGENT]
    assert "jobagent" in seen[0] and "github.com" in seen[0]


def test_a_non_json_body_is_an_error_not_a_silent_empty_result() -> None:
    client = _client(lambda r: httpx.Response(200, json="a string"))
    with pytest.raises(SourceDeclined, match="expected a JSON object"):
        client.post_json("https://example.com/jobs", {})


# -- what it does -------------------------------------------------------------


def test_a_transient_error_is_retried_then_succeeds() -> None:
    attempts = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal attempts
        attempts += 1
        if attempts == 1:
            return httpx.Response(503)
        return httpx.Response(200, json={"jobs": []})

    assert _client(handler).get_json("https://example.com/jobs") == {"jobs": []}
    assert attempts == 2


def test_retries_are_bounded() -> None:
    attempts = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal attempts
        attempts += 1
        return httpx.Response(500)

    client = _client(handler, max_retries=1)
    with pytest.raises(SourceDeclined):
        client.get_json("https://example.com/jobs")
    assert attempts == 2, "one initial call plus one retry"


def test_rate_limiting_is_applied_per_host() -> None:
    """The adapter never sees a socket, so it cannot opt out of this."""
    client = PoliteClient(
        {"example.com"},
        min_interval_seconds=0.05,
        transport=httpx.MockTransport(lambda r: httpx.Response(200, json={})),
    )
    client.get_json("https://example.com/a")
    slept = client.limiter.wait("example.com")
    assert slept > 0


# -- the registry -------------------------------------------------------------


class _Fake:
    name = "fake"
    hosts = {"example.com"}
    min_interval_seconds = 1.0
    terms = SourceTerms(allows_automated_access="yes", checked_on="2026-09-15")

    def fetch(self, client: PoliteClient, *, limit: int) -> Iterable[RawPosting]:
        return [RawPosting(source="fake", source_id="1", title="Analyst", company="Co")]


def test_registration_and_lookup() -> None:
    clear_registry_for_tests()
    adapter: Adapter = _Fake()
    register(adapter)
    assert get("fake") is adapter
    assert [a.name for a in registered()] == ["fake"]
    clear_registry_for_tests()


def test_registering_the_same_name_twice_is_an_error() -> None:
    clear_registry_for_tests()
    register(_Fake())
    with pytest.raises(ValueError, match="already registered"):
        register(_Fake())
    clear_registry_for_tests()


def test_the_allowlist_is_derived_from_adapters_not_hand_maintained() -> None:
    """A hand-kept allowlist drifts from what adapters actually reach."""
    clear_registry_for_tests()
    register(_Fake())
    assert allowed_hosts() == {"example.com"}
    clear_registry_for_tests()


def test_every_adapter_must_record_its_terms_position() -> None:
    """ "Is this source allowed" gets asked again in six months."""
    adapter = _Fake()
    assert adapter.terms.allows_automated_access
    assert adapter.terms.checked_on
