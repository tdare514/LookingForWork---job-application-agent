"""The polite HTTP client every adapter fetches through.

Issue #22 was closed as superseded when the crawler was dropped. The crawler is
back, so the rate limiter is back with it -- and the reasoning has not changed:
politeness that depends on each adapter's author remembering to be polite is not
politeness. An adapter declares its limit; the framework applies it, and an
adapter cannot opt out because it never sees a socket.

Two hard rules, both from docs/architecture.md:

- A host not on the allowlist is refused. No adapter can quietly reach somewhere
  it was not reviewed for.
- No circumvention of bot protection, ever. A 403 means stop, not retry with a
  different user agent. If a source does not want automated access, the answer
  is a different source.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any

import httpx

# Identifies the tool and gives an operator something to contact. A client that
# hides what it is has already decided it is doing something it should not.
USER_AGENT = (
    "jobagent/0.1 (personal job-search tool; "
    "+https://github.com/tdare514/LookingForWork---job-application-agent)"
)

# A 403 or 401 means the source declined. Retrying is circumvention.
DECLINED = frozenset({401, 403})
RETRYABLE = frozenset({429, 500, 502, 503, 504})


class HostNotAllowed(RuntimeError):
    """A request was attempted against a host nobody reviewed."""


class SourceDeclined(RuntimeError):
    """The source refused us. This is a stop signal, not a retry signal."""


@dataclass
class RateLimiter:
    """One token bucket per host, enforced in-process.

    Deliberately simple: a personal tool makes tens of requests, not thousands.
    The point is never to hammer a careers site, not to maximise throughput.
    """

    min_interval_seconds: float = 1.0
    _last_call: dict[str, float] = field(default_factory=dict)

    def wait(self, host: str) -> float:
        now = time.monotonic()
        last = self._last_call.get(host)
        slept = 0.0
        if last is not None:
            remaining = self.min_interval_seconds - (now - last)
            if remaining > 0:
                time.sleep(remaining)
                slept = remaining
        self._last_call[host] = time.monotonic()
        return slept


class PoliteClient:
    """The only way out to the network for job data."""

    def __init__(
        self,
        allowed_hosts: set[str],
        *,
        min_interval_seconds: float = 1.0,
        timeout: float = 20.0,
        max_retries: int = 2,
        transport: httpx.BaseTransport | None = None,
    ) -> None:
        self.allowed_hosts = {h.lower() for h in allowed_hosts}
        self.limiter = RateLimiter(min_interval_seconds)
        self.max_retries = max_retries
        self._client = httpx.Client(
            timeout=timeout,
            headers={"User-Agent": USER_AGENT, "Accept": "application/json"},
            transport=transport,
            follow_redirects=True,
        )

    def _check_host(self, url: str) -> str:
        host = (httpx.URL(url).host or "").lower()
        if host not in self.allowed_hosts:
            raise HostNotAllowed(
                f"{host!r} is not on the allowlist. Add it deliberately, "
                "after checking the source's terms."
            )
        return host

    def post_json(self, url: str, payload: dict[str, Any]) -> dict[str, Any]:
        body = self._request("POST", url, json=payload)
        if not isinstance(body, dict):
            raise SourceDeclined(f"expected a JSON object from {url}, got {type(body).__name__}")
        return body

    def get_json(self, url: str) -> dict[str, Any] | list[Any]:
        body = self._request("GET", url)
        if not isinstance(body, dict | list):
            raise SourceDeclined(f"expected JSON from {url}, got {type(body).__name__}")
        return body

    def _request(self, method: str, url: str, **kwargs: Any) -> Any:
        host = self._check_host(url)
        last_error: Exception | None = None

        for attempt in range(self.max_retries + 1):
            self.limiter.wait(host)
            try:
                response = self._client.request(method, url, **kwargs)
            except httpx.HTTPError as exc:  # network-level
                last_error = exc
                continue

            if response.status_code in DECLINED:
                # Do not retry, do not vary the user agent, do not route around.
                raise SourceDeclined(
                    f"{host} returned {response.status_code}. The source declined "
                    "automated access; use a different route rather than retrying."
                )

            if response.status_code in RETRYABLE:
                retry_after = response.headers.get("Retry-After")
                delay = float(retry_after) if (retry_after or "").isdigit() else 2.0 * (attempt + 1)
                last_error = SourceDeclined(f"{host} returned {response.status_code}")
                if attempt < self.max_retries:
                    time.sleep(min(delay, 10.0))
                continue

            response.raise_for_status()
            return response.json()

        raise SourceDeclined(f"{host} did not return a usable response: {last_error}")

    def close(self) -> None:
        self._client.close()

    def __enter__(self) -> PoliteClient:
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()
