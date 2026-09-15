"""De-duplication and sighting history (#28).

Each test here is one acceptance criterion from the issue. The ones worth
reading twice are the two that are easy to get backwards: a repost must attach
to the job it is a repost *of*, and two genuinely different roles at one company
must survive fuzzy matching intact.
"""

from __future__ import annotations

from jobagent.core.storage import Storage
from jobagent.tracking.repo import BoardRepo


def test_the_same_posting_from_two_sources_collapses_to_one_job(store: Storage) -> None:
    repo = BoardRepo(store)
    first, created_first = repo.add(
        company="Bank of Montreal",
        title="Client Service Associate",
        location="Calgary, AB, CAN",
        source="workday:bmo",
        source_id="R260026567",
    )
    second, created_second = repo.add(
        company="BMO",
        title="Client Service Associate",
        location="Calgary, Alberta, Canada",
        source="greenhouse:bmo",
        source_id="99001",
    )

    assert created_first is True
    assert created_second is False
    assert second.id == first.id
    assert store.count("jobs") == 1

    seen = repo.sightings(first.id)
    assert {s.source for s in seen} == {"workday:bmo", "greenhouse:bmo"}


def test_a_repost_attaches_as_a_sighting_rather_than_a_new_job(store: Storage) -> None:
    """Six weeks later, same requisition, new posting date."""
    repo = BoardRepo(store)
    job, _ = repo.add(
        company="RBC",
        title="2027 Winter - Business Analyst",
        location="TORONTO, Ontario, Canada",
        source="workday:rbc",
        source_id="R-0000123",
    )
    again, created = repo.add(
        company="RBC",
        title="2027 Winter - Business Analyst",
        location="Toronto, ON",
        source="workday:rbc",
        source_id="R-0000123",
    )
    assert created is False
    assert again.id == job.id
    assert store.count("jobs") == 1


def test_two_different_roles_with_similar_titles_stay_separate(store: Storage) -> None:
    """The case fuzzy matching gets wrong, per the issue."""
    repo = BoardRepo(store)
    repo.add(company="TD", title="Data Scientist", location="Toronto, Ontario")
    repo.add(company="TD", title="Senior Data Scientist", location="Toronto, Ontario")
    repo.add(company="TD", title="Analyst, Risk", location="Toronto, Ontario")
    repo.add(company="TD", title="Analyst, Credit", location="Toronto, Ontario")
    assert store.count("jobs") == 4


def test_similar_titles_at_different_companies_never_merge(store: Storage) -> None:
    """Across employers, a shared title is the norm and means nothing."""
    repo = BoardRepo(store)
    repo.add(company="RBC", title="Business Analyst", location="Toronto, ON")
    repo.add(company="BMO", title="Business Analyst", location="Toronto, ON")
    assert store.count("jobs") == 2


def test_a_department_prefix_collapses_onto_the_existing_job(store: Storage) -> None:
    """RBC prefixes the group onto the title. Same requisition, two spellings."""
    repo = BoardRepo(store)
    job, _ = repo.add(
        company="RBC",
        title="Counterparty Credit Risk Intern",
        location="TORONTO, Ontario, Canada",
    )
    same, created = repo.add(
        company="RBC",
        title="2027 Winter - GRM, Counterparty Credit Risk Intern (4 Months)",
        location="Toronto, ON",
    )
    assert created is False
    assert same.id == job.id


# -- sighting history ---------------------------------------------------------


def test_re_running_fetch_the_same_day_does_not_invent_a_sighting(store: Storage) -> None:
    """Otherwise a stable posting looks like it is being aggressively reposted."""
    repo = BoardRepo(store)
    job, _ = repo.add(
        company="RBC", title="Business Analyst", source="workday:rbc", source_id="R-1"
    )
    repo.add(company="RBC", title="Business Analyst", source="workday:rbc", source_id="R-1")
    repo.add(company="RBC", title="Business Analyst", source="workday:rbc", source_id="R-1")
    assert len(repo.sightings(job.id)) == 1


def test_sightings_from_different_sources_both_count(store: Storage) -> None:
    repo = BoardRepo(store)
    job, _ = repo.add(
        company="RBC", title="Business Analyst", source="workday:rbc", source_id="R-1"
    )
    repo.record_sighting(job.id, "greenhouse:rbc", "42")
    assert len(repo.sightings(job.id)) == 2
    assert repo.sighting_counts()[job.id] == 2


def test_a_repost_on_a_later_day_is_a_second_sighting(store: Storage) -> None:
    repo = BoardRepo(store)
    job, _ = repo.add(
        company="RBC", title="Business Analyst", source="workday:rbc", source_id="R-1"
    )
    repo.record_sighting(job.id, "workday:rbc", "R-1", seen_at="2026-11-01T09:00:00+00:00")
    assert len(repo.sightings(job.id)) == 2


# -- fields the issue is explicit about ---------------------------------------


def test_undisclosed_compensation_is_null_and_not_a_disqualifier(store: Storage) -> None:
    """It is common, not a signal. A job with no band is still a job."""
    repo = BoardRepo(store)
    job, _ = repo.add(company="RBC", title="Business Analyst")
    row = (
        store.connect()
        .execute(
            "SELECT compensation_min, compensation_max, currency FROM jobs WHERE id = ?",
            (job.id,),
        )
        .fetchone()
    )
    assert row["compensation_min"] is None
    assert row["compensation_max"] is None
    assert job in BoardRepo(store).all()


def test_seniority_is_stored_normalized_not_as_published(store: Storage) -> None:
    repo = BoardRepo(store)
    job, _ = repo.add(company="RBC", title="2027 Winter - Analyst Intern (4 Months)")
    assert job.seniority == "intern"


def test_a_later_sighting_fills_gaps_but_never_overwrites(store: Storage) -> None:
    """A deadline typed in by hand outranks one a fetch supplied."""
    repo = BoardRepo(store)
    job, _ = repo.add(company="RBC", title="Business Analyst", deadline="2026-09-20")
    repo.add(company="RBC", title="Business Analyst", deadline="2026-12-31", url="https://x/y")
    refreshed = repo.get(job.id)
    assert refreshed is not None
    assert refreshed.deadline == "2026-09-20", "a hand-entered deadline must survive a fetch"
    assert refreshed.url == "https://x/y", "but an empty field is filled"


# -- rows that predate the migration ------------------------------------------


def test_backfill_populates_old_rows_without_merging_them(store: Storage) -> None:
    """Merging board rows someone is already tracking is their call, not a migration's."""
    repo = BoardRepo(store)
    repo.add(company="Bank of Montreal", title="Client Service Associate", location="Calgary, AB")
    # Simulate a row written before M0003: keys blanked out.
    with store.transaction() as conn:
        conn.execute("UPDATE jobs SET dedupe_key = '', title_norm = '', location_norm = ''")
        conn.execute(
            "INSERT INTO jobs (fingerprint, title, company, company_norm, first_seen_at,"
            " last_seen_at, state) VALUES ('legacy', 'Client Service Associate', 'BMO',"
            " 'bmo', '2026-01-01', '2026-01-01', 'new')"
        )

    filled = repo.backfill_normalized()
    assert filled == 2
    assert store.count("jobs") == 2, "backfill must not merge rows the user is tracking"

    # Idempotent: a second run has nothing to do.
    assert repo.backfill_normalized() == 0


def test_raw_payloads_are_kept_once_per_day_not_once_per_run(store: Storage) -> None:
    """The 30-day retention window is meaningless if every run appends again."""
    repo = BoardRepo(store)
    for _ in range(3):
        repo.store_raw("workday:rbc", "R-1", {"title": "Business Analyst"})
    assert store.count("raw_payloads") == 1
