"""PII registry.

Issue #21 originally called for a standalone inventory document. It was folded
into the schema instead: two artifacts means one of them rots, and it would have
been the document. This registry is the inventory, and it sits next to the
columns it describes.

Every PII-bearing column must be registered here. ``test_pii_registry`` asserts
that the schema and this registry agree, so a new PII column cannot land
unregistered -- which is what makes ``purge`` (#42) verifiable rather than
hopeful.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum


class Sensitivity(StrEnum):
    """How bad is disclosure of this field."""

    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    # Which companies were approached while employed elsewhere. Disclosure is a
    # career event, not an inconvenience.
    CRITICAL = "critical"


class Destination(StrEnum):
    """Where a field is permitted to travel."""

    NOWHERE = "nowhere"
    MODEL = "model_provider"
    JOB_SITE = "job_site"


@dataclass(frozen=True)
class PIIField:
    table: str
    column: str
    purpose: str
    sensitivity: Sensitivity
    destinations: tuple[Destination, ...]
    retention_days: int | None  # None == until the user deletes it


# Retention defaults mirror docs/security-privacy.md.
RETENTION_UNTIL_DELETED = None
RETENTION_POSTINGS = 180
RETENTION_DRAFTS = 30
RETENTION_RAW = 30
RETENTION_AUDIT = 365


REGISTRY: tuple[PIIField, ...] = (
    PIIField(
        "profile",
        "payload",
        "Declared job-search intent: titles, locations, compensation floor, "
        "work authorization. Drives every filter and score.",
        Sensitivity.HIGH,
        (Destination.MODEL,),
        RETENTION_UNTIL_DELETED,
    ),
    PIIField(
        "resume",
        "payload",
        "Resume source of truth. The complete set of claims tailoring may make.",
        Sensitivity.HIGH,
        (Destination.MODEL, Destination.JOB_SITE),
        RETENTION_UNTIL_DELETED,
    ),
    PIIField(
        "applications",
        "job_id",
        "Which company was applied to. Combined with timestamps this is the "
        "record of approaching employers while employed elsewhere.",
        Sensitivity.CRITICAL,
        (Destination.NOWHERE,),
        RETENTION_UNTIL_DELETED,
    ),
    PIIField(
        "applications",
        "notes",
        "Free-text notes on an application, which routinely contain names of "
        "recruiters and internal contacts.",
        Sensitivity.CRITICAL,
        (Destination.NOWHERE,),
        RETENTION_UNTIL_DELETED,
    ),
    PIIField(
        "application_transitions",
        "occurred_at",
        "Timestamped application history. Drives follow-ups and the funnel report.",
        Sensitivity.CRITICAL,
        (Destination.NOWHERE,),
        RETENTION_UNTIL_DELETED,
    ),
    PIIField(
        "documents",
        "path",
        "Path to a generated resume or cover letter containing full contact PII.",
        Sensitivity.HIGH,
        (Destination.JOB_SITE,),
        RETENTION_DRAFTS,
    ),
    PIIField(
        "audit_log",
        "detail",
        "What the agent did and what a human approved. Itself a record of which "
        "companies were approached.",
        Sensitivity.CRITICAL,
        (Destination.NOWHERE,),
        RETENTION_AUDIT,
    ),
    PIIField(
        "raw_payloads",
        "body",
        "Unparsed source responses, kept only so a mapping bug is fixable without re-fetching.",
        Sensitivity.LOW,
        (Destination.NOWHERE,),
        RETENTION_RAW,
    ),
)


def registered_columns() -> set[tuple[str, str]]:
    return {(f.table, f.column) for f in REGISTRY}


def by_table(table: str) -> tuple[PIIField, ...]:
    return tuple(f for f in REGISTRY if f.table == table)


def critical_tables() -> set[str]:
    """Tables that ``purge`` must empty completely."""
    return {f.table for f in REGISTRY if f.sensitivity is Sensitivity.CRITICAL}
