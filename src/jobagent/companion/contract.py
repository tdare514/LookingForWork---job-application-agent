"""The hosted tracker's field contract, seen from this side.

`cloudflare/src/types.ts` is the server's copy. This is the local one: which
board column each hosted field is read from. `tests/test_cloudflare_contract.py`
holds the two to each other and to `jobagent.core.pii`, so a field cannot start
travelling without the registry granting it.
"""

from __future__ import annotations

# Hosted field -> the `jobs` column it carries. Every one of these columns is
# registered with `Destination.HOSTED_TRACKER`, and nothing else is.
FROM_BOARD: dict[str, str] = {
    "company": "company",
    "title": "title",
    "location": "location",
    "url": "url",
    "deadline": "deadline",
    "status": "state",
}

# Hosted fields with no local column. They are set on the phone and live only in
# D1; a push carries back whatever the hosted row already holds, so syncing from
# the laptop never wipes them.
HOSTED_ONLY: tuple[str, ...] = ("nextAction", "nextActionDate")

# Row identity and the optimistic-concurrency version. Not data about anyone.
IDENTIFIERS: tuple[str, ...] = ("id", "version")

# The one field a phone edit may change on the board. Everything else in
# FROM_BOARD is the employer's text or a date; the laptop stays their source.
PULLED_BACK: tuple[str, ...] = ("status",)
