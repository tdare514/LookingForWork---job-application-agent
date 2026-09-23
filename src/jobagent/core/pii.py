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
    # The phone snapshot (ADR 0009): a static file pushed to Cloudflare Pages
    # behind a Cloudflare Access login. Reachable by the user on a phone, by
    # nobody else. Cloudflare can read what is stored there, so this is a real
    # third party -- it is narrower than `NOWHERE`, not equivalent to it.
    PUBLIC_SNAPSHOT = "public_snapshot"
    # The hosted tracker (ADR 0010): a Cloudflare D1 database behind Access and
    # an owner-only session, written by `jobagent sync` and editable from the
    # phone. Wider than the snapshot in one way that matters: it is a writable
    # copy that persists until purged, not a file replaced on each upload.
    HOSTED_TRACKER = "hosted_tracker"


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
    # Downgraded from CRITICAL/NOWHERE to HIGH/PUBLIC_SNAPSHOT deliberately, by
    # the owner's decision, so the phone snapshot can show it (ADR 0009).
    #
    # Nothing about the underlying risk was reassessed: paired with the company
    # name this is still the record of approaching employers while employed
    # elsewhere, and disclosure is still a career event. What changed is that
    # the owner accepted that risk in exchange for seeing status on a phone,
    # with the Cloudflare Access login as the mitigation. Read the ADR before
    # widening this further -- the reclassification is the whole reason
    # `test_nothing_critical_is_sent_to_a_third_party` no longer covers it.
    PIIField(
        "jobs",
        "state",
        "Where an application stands. With the company name this is the record "
        "of approaching employers while employed elsewhere. Leaves the machine "
        "only for the phone snapshot and the hosted tracker, both behind "
        "Cloudflare Access.",
        Sensitivity.HIGH,
        (Destination.PUBLIC_SNAPSHOT, Destination.HOSTED_TRACKER),
        RETENTION_UNTIL_DELETED,
    ),
    # The rest of what the phone shows. Registered so that ADR 0010's field list
    # is the registry's to grant, not the TypeScript contract's to assume, and so
    # `tests/test_cloudflare_contract.py` can hold the two to each other.
    #
    # MEDIUM rather than LOW: one of these alone is a public posting, but the set
    # of them is the list of employers on the board. Paired with `state`, that is
    # the record 0009 accepted as HIGH.
    *(
        PIIField(
            "jobs",
            column,
            purpose,
            Sensitivity.MEDIUM,
            (Destination.PUBLIC_SNAPSHOT, Destination.HOSTED_TRACKER),
            RETENTION_UNTIL_DELETED,
        )
        for column, purpose in (
            ("company", "The employer. Across the board, the list of who is being considered."),
            ("title", "The role, as the employer published it."),
            ("location", "Where the role is, as the employer published it."),
            ("url", "The posting's own address, for opening it from the phone."),
            ("deadline", "When the posting closes. Drives the board's ordering."),
        )
    ),
    PIIField(
        "jobs",
        "notes",
        "Free-text notes on an opportunity, which routinely name recruiters and internal contacts.",
        Sensitivity.CRITICAL,
        (Destination.NOWHERE,),
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
        "jobs",
        "description",
        "Posting text as the employer published it. Third-party content, not "
        "personal data -- but it is the input to extraction, and purge walks "
        "this registry, so an unregistered column is one purge does not clear.",
        Sensitivity.LOW,
        (Destination.NOWHERE,),
        RETENTION_POSTINGS,
    ),
    PIIField(
        "raw_payloads",
        "body",
        "Unparsed source responses, kept only so a mapping bug is fixable without re-fetching.",
        Sensitivity.LOW,
        (Destination.NOWHERE,),
        RETENTION_RAW,
    ),
    PIIField(
        "jobs",
        "state_reason",
        "Why a role was passed over. Free text naming an employer and a "
        "judgement about them -- the same class of disclosure as `notes`.",
        Sensitivity.CRITICAL,
        (Destination.NOWHERE,),
        RETENTION_UNTIL_DELETED,
    ),
    PIIField(
        "jobs",
        "snoozed_until",
        "When a role comes back into the digest. A date against a named "
        "employer is part of the record of who was being considered, and when.",
        Sensitivity.HIGH,
        (Destination.NOWHERE,),
        RETENTION_UNTIL_DELETED,
    ),
    PIIField(
        "scores",
        "components",
        "The score decomposition: declared intent applied to a named company. "
        "Reading it tells you what the user is looking for and how closely each "
        "employer matched, which is the shortlist restated per row.",
        Sensitivity.HIGH,
        (Destination.NOWHERE,),
        RETENTION_POSTINGS,
    ),
    PIIField(
        "companion_sync",
        "agreed_status",
        "The status the board and the hosted tracker last agreed on, per job. A "
        "copy of `jobs.state` kept only to detect conflicting edits.",
        Sensitivity.HIGH,
        (Destination.NOWHERE,),
        RETENTION_UNTIL_DELETED,
    ),
    PIIField(
        "companion_sync",
        "synced_at",
        "When each board row was last agreed with the hosted tracker. Keyed by "
        "job, so it is a dated list of which employers were on the board.",
        Sensitivity.HIGH,
        (Destination.NOWHERE,),
        RETENTION_UNTIL_DELETED,
    ),
    PIIField(
        "scores",
        "filter_reason",
        "Why a role was cut. Quotes the profile back -- the compensation floor, "
        "the blocklist, the sponsorship need -- against a named employer.",
        Sensitivity.HIGH,
        (Destination.NOWHERE,),
        RETENTION_POSTINGS,
    ),
)


def registered_columns() -> set[tuple[str, str]]:
    return {(f.table, f.column) for f in REGISTRY}


def by_table(table: str) -> tuple[PIIField, ...]:
    return tuple(f for f in REGISTRY if f.table == table)


def critical_tables() -> set[str]:
    """Tables that ``purge`` must empty completely."""
    return {f.table for f in REGISTRY if f.sensitivity is Sensitivity.CRITICAL}
