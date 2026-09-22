"""Guards on what the phone snapshot may carry off this machine.

ADR 0009 let one field -- `jobs.state` -- leave, and nothing else. These tests
are what keeps "nothing else" true as the schema grows.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import fields
from datetime import UTC, date, datetime

from jobagent.core import pii
from jobagent.tracking.repo import Job
from jobagent.tracking.snapshot import NEVER_SNAPSHOT, SNAPSHOT_FIELDS, build

GENERATED_AT = datetime(2026, 9, 22, 12, 0, tzinfo=UTC)


def test_snapshot_emits_exactly_the_allowlisted_fields(make_job: Callable[..., Job]) -> None:
    payload = build([make_job(1)], generated_at=GENERATED_AT).as_dict()
    assert set(payload["rows"][0]) == set(SNAPSHOT_FIELDS)


def test_the_two_lists_never_overlap() -> None:
    assert not set(SNAPSHOT_FIELDS) & set(NEVER_SNAPSHOT)


def test_every_board_field_is_either_allowed_or_refused() -> None:
    """A new column on `Job` must be classified, not silently published.

    `NEVER_SNAPSHOT` also names `description`, which is a `jobs` column that the
    `Job` dataclass does not carry -- named anyway so the refusal is on record.
    """
    classified = set(SNAPSHOT_FIELDS) | set(NEVER_SNAPSHOT)
    unclassified = {f.name for f in fields(Job)} - classified
    assert not unclassified, f"unclassified board fields: {sorted(unclassified)}"


def test_everything_that_travels_is_permitted_by_the_registry() -> None:
    """The allowlist may not contradict `jobagent.core.pii`.

    Adding a registered NOWHERE column to `SNAPSHOT_FIELDS` fails here, which is
    the point: the registry stays the authority on what may leave.
    """
    registered = {f.column: f for f in pii.by_table("jobs")}
    for column in SNAPSHOT_FIELDS:
        field = registered.get(column)
        if field is None:
            continue
        assert pii.Destination.PUBLIC_SNAPSHOT in field.destinations, (
            f"{column} is in the snapshot but the registry does not let it travel"
        )


def test_notes_are_not_emitted_even_when_present(make_job: Callable[..., Job]) -> None:
    job = make_job(1, notes="Recruiter: a real person's name and number")
    payload = build([job], generated_at=GENERATED_AT).as_dict()
    assert "notes" not in payload["rows"][0]
    assert "real person" not in str(payload)


def test_state_reason_is_not_emitted_even_when_present(make_job: Callable[..., Job]) -> None:
    job = make_job(1, state_reason="Passed: the team looked disorganised")
    payload = build([job], generated_at=GENERATED_AT).as_dict()
    assert "state_reason" not in payload["rows"][0]
    assert "disorganised" not in str(payload)


def test_snoozed_rows_are_left_out(make_job: Callable[..., Job]) -> None:
    snoozed = make_job(1, snoozed_until="2026-12-01")
    awake = make_job(2)
    payload = build([snoozed, awake], generated_at=GENERATED_AT, today=date(2026, 9, 22)).as_dict()
    assert [row["id"] for row in payload["rows"]] == [2]


def test_the_snapshot_says_how_old_it_is(make_job: Callable[..., Job]) -> None:
    """A static file that looks live is worse than one that admits its age."""
    payload = build([make_job(1)], generated_at=GENERATED_AT).as_dict()
    assert payload["generated_at"] == "2026-09-22T12:00:00+00:00"
