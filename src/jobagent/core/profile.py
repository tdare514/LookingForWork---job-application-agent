"""The profile: declared intent.

The resume says what happened. The profile says what is wanted, and it is the
input to every hard filter and every score component in Phase 2. That asymmetry
is why validation here is strict to the point of rudeness: a resume with a typo
produces a document somebody proofreads, while a profile with an empty
``target_titles`` produces a shortlist of noise that looks exactly like a
working system. A silently empty filter is the failure this module exists to
prevent, so a malformed profile is a hard failure with the offending field
named.

The file is an import, not the store. ``jobagent profile set`` validates YAML
and writes it into the ``profile`` singleton; everything downstream reads
storage. That is what gives ``schema_version`` and the upgrade chain below
something to do -- a stored profile written months ago has to keep loading
after the shape changes mid-search.

What is deliberately NOT here: the prose answers a portal asks for. The
sentence "Canadian citizen, no sponsorship required" lives in the resume's
``standing`` block with the other things said verbatim to an employer. This
module holds the structured form of the same situation -- which countries, and
whether sponsorship is needed -- because a filter needs a boolean, not a
sentence. One fact, two shapes, neither derived from the other by guessing.
"""

from __future__ import annotations

import re
from collections.abc import Callable
from pathlib import Path
from typing import Any

import yaml
from pydantic import BaseModel, Field, field_validator, model_validator

from jobagent.core.storage import Storage, reject_secret_shaped
from jobagent.core.vocabulary import Seniority

# Bumped when the stored shape changes. A stored profile carrying an older
# version is upgraded through _UPGRADES on read; a newer one is refused, because
# guessing at a shape from the future is how a filter silently empties.
CURRENT_SCHEMA_VERSION = 1

# Upgraders keyed by the version they read. Empty at v1 -- the hook exists so
# that the first shape change is a small diff in a place already tested, rather
# than a decision made in a hurry mid-search.
_UPGRADES: dict[int, Callable[[dict[str, Any]], dict[str, Any]]] = {}

WORK_ARRANGEMENTS = ("onsite", "hybrid", "remote")


class WorkAuthorization(BaseModel):
    """Structured, because filters need a boolean and not a sentence.

    The prose version an employer reads stays in the resume's ``standing``
    block. Keeping both here would mean two owners for one fact, and the one
    that rots is always the one nobody reads.
    """

    authorized_in: list[str] = Field(
        min_length=1,
        description="Country codes where work is authorized without sponsorship, e.g. [CA].",
    )
    needs_sponsorship: bool = Field(
        description="True if an employer must sponsor. Drives a hard filter, so it is required."
    )

    @field_validator("authorized_in")
    @classmethod
    def _country_codes(cls, v: list[str]) -> list[str]:
        cleaned = [code.strip().upper() for code in v if code.strip()]
        if not cleaned:
            raise ValueError("authorized_in cannot be empty -- name at least one country")
        bad = [c for c in cleaned if not re.fullmatch(r"[A-Z]{2}", c)]
        if bad:
            raise ValueError(f"authorized_in wants ISO country codes like 'CA', got {bad}")
        return cleaned


class Compensation(BaseModel):
    """A floor, not a target. Undisclosed pay is common and never disqualifies.

    ``floor`` of None means "no floor stated", which is a different thing from
    zero and is treated as such by the filters: a posting with no band cannot
    fail a floor that does not exist.
    """

    floor: int | None = None
    currency: str = "CAD"

    @field_validator("floor")
    @classmethod
    def _non_negative(cls, v: int | None) -> int | None:
        if v is not None and v < 0:
            raise ValueError(f"compensation floor cannot be negative, got {v}")
        return v

    @field_validator("currency")
    @classmethod
    def _currency_code(cls, v: str) -> str:
        code = v.strip().upper()
        if not re.fullmatch(r"[A-Z]{3}", code):
            raise ValueError(f"currency wants a three-letter code like 'CAD', got {v!r}")
        return code


class Weights(BaseModel):
    """Scoring weights. Configuration, not constants.

    ``docs/job-matching.md`` argues the case: someone changing domains wants
    domain relevance near zero, and the system should not fight them.

    ``semantic_fit`` is the exception and is why this model validates rather
    than merely holding numbers. It needs an embedding model; the budget
    constraint rules out a metered API in the core loop, and no local backend
    has been decided (#31). So it stays in the schema -- the component is real
    and the vocabulary matches the design doc -- but a non-zero value is
    refused rather than stored and silently ignored. A weight that does nothing
    is worse than one that is absent, because the score it produces looks
    complete.
    """

    skill_overlap: float = 0.40
    seniority_fit: float = 0.20
    domain_relevance: float = 0.27
    freshness: float = 0.13
    semantic_fit: float = 0.0

    @field_validator("*")
    @classmethod
    def _non_negative(cls, v: float) -> float:
        if v < 0:
            raise ValueError(f"a weight cannot be negative, got {v}")
        return v

    @model_validator(mode="after")
    def _semantic_fit_has_no_backend(self) -> Weights:
        if self.semantic_fit != 0:
            raise ValueError(
                f"weights.semantic_fit: {self.semantic_fit} cannot be scored -- it needs an "
                "embedding model, and no local backend has been decided (see #31). A metered "
                "embeddings API is out of scope per the budget constraint in AGENTS.md. "
                "Set it to 0 or leave it out; the other weights renormalize."
            )
        return self

    @model_validator(mode="after")
    def _something_is_weighted(self) -> Weights:
        if self.total == 0:
            raise ValueError("weights sum to zero -- every posting would score the same")
        return self

    @property
    def total(self) -> float:
        return (
            self.skill_overlap
            + self.seniority_fit
            + self.domain_relevance
            + self.freshness
            + self.semantic_fit
        )

    def normalized(self) -> dict[str, float]:
        """Weights as fractions of one.

        Callers should not have to care whether the profile's numbers were
        written as fractions, percentages, or 1-to-10 preferences. They are a
        statement of relative importance, so they are normalized on read and the
        scorer only ever sees a set that sums to one.
        """
        total = self.total
        return {
            "skill_overlap": self.skill_overlap / total,
            "seniority_fit": self.seniority_fit / total,
            "domain_relevance": self.domain_relevance / total,
            "freshness": self.freshness / total,
            "semantic_fit": self.semantic_fit / total,
        }


class Profile(BaseModel):
    """Declared intent. Every hard filter and score component reads this."""

    schema_version: int = CURRENT_SCHEMA_VERSION

    # Required, and required to be non-empty: each of these is a filter input,
    # and an empty one means the filter passes everything.
    target_titles: list[str] = Field(min_length=1)
    target_seniority: list[Seniority] = Field(min_length=1)
    locations: list[str] = Field(min_length=1)
    work_arrangements: list[str] = Field(min_length=1)
    must_have_skills: list[str] = Field(min_length=1)
    work_authorization: WorkAuthorization

    # Optional: absent means "no opinion", which is a real answer.
    nice_to_have_skills: list[str] = Field(default_factory=list)
    deal_breakers: list[str] = Field(default_factory=list)
    company_blocklist: list[str] = Field(default_factory=list)
    compensation: Compensation = Field(default_factory=Compensation)
    narrative: str = ""
    weights: Weights = Field(default_factory=Weights)

    @field_validator("work_arrangements")
    @classmethod
    def _known_arrangements(cls, v: list[str]) -> list[str]:
        cleaned = [a.strip().lower() for a in v if a.strip()]
        unknown = [a for a in cleaned if a not in WORK_ARRANGEMENTS]
        if unknown:
            raise ValueError(
                f"work_arrangements must be from {list(WORK_ARRANGEMENTS)}, got {unknown}"
            )
        if not cleaned:
            raise ValueError("work_arrangements cannot be empty")
        return cleaned

    @field_validator("target_titles", "must_have_skills", "locations")
    @classmethod
    def _no_blank_entries(cls, v: list[str]) -> list[str]:
        cleaned = [item.strip() for item in v if item.strip()]
        if not cleaned:
            raise ValueError("list cannot be empty or made only of blank entries")
        return cleaned

    @field_validator("schema_version")
    @classmethod
    def _version_is_known(cls, v: int) -> int:
        if v > CURRENT_SCHEMA_VERSION:
            raise ValueError(
                f"profile schema_version {v} is newer than this build understands "
                f"({CURRENT_SCHEMA_VERSION}). Upgrade jobagent rather than editing the number."
            )
        if v < 1:
            raise ValueError(f"profile schema_version must be 1 or greater, got {v}")
        return v

    @model_validator(mode="after")
    def _holds_no_credentials(self) -> Profile:
        """The profile is a config file, which is where API keys get pasted.

        Storage refuses credential-shaped *keys* on write. This refuses
        credential-shaped *values* at load, so `profile validate` catches it
        before anything touches the database.
        """
        reject_secret_shaped(self.model_dump())
        return self

    # Matching a blocklist entry to a posting's company, or a wanted city to a
    # posting's location, needs the canonicalisation in `matching.normalize`.
    # That comparison therefore lives with the hard filters (#31), which may
    # import both this module and that one -- rather than here, which would make
    # `core` depend on a package built on top of it.

    @classmethod
    def from_yaml(cls, path: Path) -> Profile:
        raw = yaml.safe_load(path.read_text())
        if not isinstance(raw, dict):
            raise ValueError(f"{path} does not contain a YAML mapping")
        return cls.model_validate(_upgrade(raw))


def _upgrade(payload: dict[str, Any]) -> dict[str, Any]:
    """Walk a stored payload forward to the current shape.

    One step at a time rather than a single jump, so that a profile written two
    versions ago goes through the same code as one written yesterday. The chain
    is empty at v1; the test suite still exercises it, because the first time it
    matters is the worst time to discover it was never run.
    """
    data = dict(payload)
    version = int(data.get("schema_version", 1))
    while version < CURRENT_SCHEMA_VERSION:
        upgrade = _UPGRADES.get(version)
        if upgrade is None:
            raise ValueError(
                f"no upgrade path from profile schema_version {version} to {CURRENT_SCHEMA_VERSION}"
            )
        data = upgrade(data)
        version = int(data.get("schema_version", version + 1))
    return data


def load_file(path: Path) -> Profile:
    """Validate a profile YAML. A malformed profile is a hard failure."""
    if not path.is_file():
        raise FileNotFoundError(f"no profile at {path}")
    return Profile.from_yaml(path)


def store(storage: Storage, profile: Profile) -> None:
    """Write the profile into the singleton it shares with nothing else."""
    storage.put_singleton("profile", profile.model_dump(mode="json"), profile.schema_version)
    # The profile is declared intent, not an action taken on the user's behalf,
    # so the audit entry records that it changed and nothing about what it says.
    storage.append_audit("profile.set", {"schema_version": profile.schema_version})


def load(storage: Storage) -> Profile | None:
    """Read the stored profile, upgrading an older shape on the way through.

    None means no profile has been set yet -- a normal state on day one, and the
    caller's job to complain about rather than this function's.
    """
    payload = storage.get_singleton("profile")
    if payload is None:
        return None
    return Profile.model_validate(_upgrade(payload))
