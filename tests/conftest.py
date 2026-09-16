from __future__ import annotations

from collections.abc import Callable, Iterator
from pathlib import Path
from typing import Any

import pytest

from jobagent.core.profile import Profile, WorkAuthorization
from jobagent.core.storage import Storage
from jobagent.core.vocabulary import Seniority
from jobagent.tracking.repo import Job


@pytest.fixture()
def data_dir(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    target = tmp_path / "data"
    monkeypatch.setenv("JOBAGENT_DATA_DIR", str(target))
    return target


@pytest.fixture()
def store(data_dir: Path) -> Iterator[Storage]:
    with Storage() as s:
        yield s


# -- builders for the shortlist and digest tests (#32) --------------------
#
# Factory fixtures rather than module-level helpers, because `test_digest` and
# `test_shortlist` both need them and importing one test module from another
# gives the file two module names and breaks mypy.


@pytest.fixture()
def make_profile() -> Callable[..., Profile]:
    def build(**overrides: object) -> Profile:
        base: dict[str, object] = {
            "target_titles": ["Risk Analyst"],
            "target_seniority": [Seniority.INTERN],
            "locations": ["Toronto"],
            "work_arrangements": ["onsite", "hybrid"],
            "must_have_skills": ["python"],
            "work_authorization": WorkAuthorization(authorized_in=["CA"], needs_sponsorship=False),
        }
        base.update(overrides)
        return Profile(**base)  # type: ignore[arg-type]  # keyed by field name

    return build


@pytest.fixture()
def make_job() -> Callable[..., Job]:
    def build(job_id: int, company: str = "RBC", **overrides: Any) -> Job:
        base: dict[str, Any] = {
            "id": job_id,
            "company": company,
            "title": f"Risk Analyst Intern {job_id}",
            "url": None,
            "location": "Toronto",
            "deadline": None,
            "state": "new",
            "notes": None,
            "seniority": "intern",
            "first_seen_at": "2026-09-16T08:00:00+00:00",
            "state_changed_at": None,
        }
        base.update(overrides)
        return Job(**base)

    return build


@pytest.fixture()
def make_score() -> Callable[..., dict[str, Any]]:
    """A stored score record, shaped as `BoardRepo.latest_scores` returns it."""

    def build(total: float, filtered: bool = False) -> dict[str, Any]:
        return {
            "total": total,
            "filtered": filtered,
            "filter_reason": None,
            "scored_at": "2026-09-16T08:00:00+00:00",
            "components": {
                "total": total,
                "scored_on": ["seniority_fit", "domain_relevance"],
                "unavailable": ["skill_overlap", "freshness", "semantic_fit"],
                "components": {},
            },
        }

    return build
