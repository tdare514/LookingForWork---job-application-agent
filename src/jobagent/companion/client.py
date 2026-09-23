"""The only code that talks to the hosted tracker.

Everything it sends has already been reduced to the contract in `contract.py`;
this module adds transport, credentials and one refusal: it will not send
anything to a companion whose Cloudflare Access gate is off (ADR 0010).

Credentials come from the environment, never a file or the database:

- ``JOBAGENT_COMPANION_URL`` -- the Pages project's https origin.
- ``JOBAGENT_SYNC_TOKEN`` -- the companion's ``SYNC_TOKEN`` secret.
- ``JOBAGENT_ACCESS_CLIENT_ID`` / ``JOBAGENT_ACCESS_CLIENT_SECRET`` -- a Cloudflare
  Access service token, so the laptop can pass the gate a browser logs in to.
"""

from __future__ import annotations

import json
import os
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any
from urllib.parse import urlsplit

import httpx

from jobagent.discovery.http import USER_AGENT

ENV_URL = "JOBAGENT_COMPANION_URL"
ENV_TOKEN = "JOBAGENT_SYNC_TOKEN"
ENV_ACCESS_ID = "JOBAGENT_ACCESS_CLIENT_ID"
ENV_ACCESS_SECRET = "JOBAGENT_ACCESS_CLIENT_SECRET"

# Below the companion's 16 KiB body limit, with room for the envelope.
MAX_BATCH_BYTES = 14_000
MAX_BATCH_ROWS = 50


class CompanionNotConfigured(RuntimeError):
    """Some of the four environment variables are missing."""


class AccessGateOff(RuntimeError):
    """The companion answered an anonymous request. Nothing may be sent to it."""


class CompanionError(RuntimeError):
    """The companion refused or failed a request."""


@dataclass(frozen=True)
class CompanionConfig:
    url: str
    sync_token: str
    access_client_id: str
    access_client_secret: str

    @classmethod
    def from_env(cls, env: Mapping[str, str] | None = None) -> CompanionConfig | None:
        """None when no companion is configured at all; an error when half is."""
        source = os.environ if env is None else env
        values = {
            name: source.get(name, "").strip()
            for name in (ENV_URL, ENV_TOKEN, ENV_ACCESS_ID, ENV_ACCESS_SECRET)
        }
        if not any(values.values()):
            return None
        missing = [name for name, value in values.items() if not value]
        if missing:
            raise CompanionNotConfigured(f"set {', '.join(missing)}")
        parts = urlsplit(values[ENV_URL])
        if parts.scheme != "https" or not parts.hostname or parts.path not in ("", "/"):
            raise CompanionNotConfigured(
                f"{ENV_URL} must be an https origin, e.g. https://name.pages.dev"
            )
        return cls(
            url=f"https://{parts.netloc}",
            sync_token=values[ENV_TOKEN],
            access_client_id=values[ENV_ACCESS_ID],
            access_client_secret=values[ENV_ACCESS_SECRET],
        )


def gate_is_on(response: httpx.Response) -> bool:
    """Does an anonymous request get the Access login rather than the page?

    Access answers a browser with a redirect to the team's
    ``*.cloudflareaccess.com`` login, and a non-browser with 401/403. Anything
    else -- above all a 200 -- means the project is readable without logging in.
    """
    if response.status_code in (401, 403):
        return True
    if response.status_code in (301, 302, 303, 307, 308):
        host = urlsplit(response.headers.get("location", "")).hostname or ""
        return host == "cloudflareaccess.com" or host.endswith(".cloudflareaccess.com")
    return False


def batches(rows: list[dict[str, Any]], removals: list[str]) -> list[dict[str, Any]]:
    """Split one sync into bodies the companion will accept."""
    out: list[dict[str, Any]] = []
    current: list[dict[str, Any]] = []
    size = 0
    for row in rows:
        encoded = len(json.dumps(row))
        if current and (len(current) >= MAX_BATCH_ROWS or size + encoded > MAX_BATCH_BYTES):
            out.append({"applications": current})
            current, size = [], 0
        current.append(row)
        size += encoded
    if current:
        out.append({"applications": current})
    for start in range(0, len(removals), MAX_BATCH_ROWS):
        out.append({"applications": [], "remove": removals[start : start + MAX_BATCH_ROWS]})
    return out


class CompanionClient:
    def __init__(
        self, config: CompanionConfig, transport: httpx.BaseTransport | None = None
    ) -> None:
        self.config = config
        self._http = httpx.Client(
            base_url=config.url,
            transport=transport,
            timeout=20.0,
            follow_redirects=False,
            headers={"User-Agent": USER_AGENT},
        )

    def close(self) -> None:
        self._http.close()

    def __enter__(self) -> CompanionClient:
        return self

    def __exit__(self, *_: object) -> None:
        self.close()

    def _authorised(self) -> dict[str, str]:
        return {
            "Authorization": f"Bearer {self.config.sync_token}",
            "CF-Access-Client-Id": self.config.access_client_id,
            "CF-Access-Client-Secret": self.config.access_client_secret,
        }

    def check_gate(self) -> None:
        """Refuse to go on unless an anonymous request is stopped by Access."""
        response = self._http.get("/")
        if not gate_is_on(response):
            raise AccessGateOff(
                f"{self.config.url} answered an anonymous request with {response.status_code}, "
                "not the Cloudflare Access login. Configure the Access application "
                "(cloudflare/README.md) before syncing anything."
            )

    def _call(
        self, method: str, path: str, body: dict[str, Any] | None = None, **params: str
    ) -> httpx.Response:
        response = self._http.request(
            method, path, json=body, params=params or None, headers=self._authorised()
        )
        if response.status_code in (301, 302, 303, 307, 308):
            raise CompanionError("the Access service token was not accepted (redirected to login)")
        return response

    def pull(self) -> list[dict[str, Any]]:
        rows: list[dict[str, Any]] = []
        after = ""
        while True:
            response = (
                self._call("GET", "/api/sync", after=after)
                if after
                else self._call("GET", "/api/sync")
            )
            if response.status_code != 200:
                raise CompanionError(f"pull failed: {response.status_code} {response.text[:200]}")
            payload = response.json()
            rows.extend(payload["applications"])
            after = payload.get("next") or ""
            if not after:
                return rows

    def push(self, body: dict[str, Any]) -> tuple[int, dict[str, Any]]:
        """One batch. Returns (status, payload) so the caller can handle 409."""
        response = self._call("POST", "/api/sync", body)
        if response.status_code not in (200, 409):
            raise CompanionError(f"push failed: {response.status_code} {response.text[:200]}")
        return response.status_code, response.json()

    def purge(self) -> dict[str, Any]:
        response = self._call("POST", "/api/purge", {})
        if response.status_code not in (200, 500):
            raise CompanionError(f"purge failed: {response.status_code} {response.text[:200]}")
        result: dict[str, Any] = response.json()
        return result


def connect(config: CompanionConfig) -> CompanionClient:
    """The CLI's way in. A seam, so tests can put a fake companion behind it."""
    return CompanionClient(config)
