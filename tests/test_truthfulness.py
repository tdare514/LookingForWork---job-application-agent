"""The tests are the guarantee. The validator is just how it is implemented."""

from __future__ import annotations

import pytest

from jobagent.application.resume import (
    Accomplishment,
    Contact,
    Education,
    Resume,
    Role,
)
from jobagent.application.truthfulness import (
    TailoredBullet,
    TruthfulnessError,
    check,
    enforce,
)


def _resume() -> Resume:
    return Resume(
        contact=Contact(
            name="Oluwatoby Dare",
            email="dareoluwatoby@gmail.com",
            phone="226-337-5946",
            location="Mississauga, ON",
        ),
        summary="Computer Science student moving into business analysis.",
        education=[
            Education(
                school="University of Guelph",
                credential="Bachelor of Computing (Honours), Computer Science",
                location="Guelph, ON",
                graduation="Expected 2026",
            )
        ],
        roles=[
            Role(
                title="Project Manager",
                organization="ProjectGenova",
                location="Hybrid, ON",
                start="June 2026",
                accomplishments=[
                    Accomplishment(
                        id="genova-validation",
                        text=(
                            "Conducted data validation and quality checks using Excel "
                            "formulas across tracked work items"
                        ),
                        metric="100+ tracked work items",
                        skills=["Excel", "data validation"],
                        scope="contributed",
                    ),
                    Accomplishment(
                        id="genova-event",
                        text="Coordinated logistics and stakeholder outreach for an event",
                        metric="100 attendees, $7K budget",
                        skills=["stakeholder communication"],
                        scope="owned",
                    ),
                ],
            )
        ],
    )


# -- the failure this module exists for --------------------------------------


def test_scope_inflation_is_caught() -> None:
    """ "Conducted" must not become "owned" because a posting wanted ownership."""
    bullets = [
        TailoredBullet(
            text="Owned data quality across 100+ tracked work items",
            source_id="genova-validation",
        )
    ]
    violations = check(bullets, _resume())
    assert [v.kind for v in violations] == ["scope-inflation"]
    assert "contributed" in violations[0].detail


def test_leadership_claim_on_a_contribution_is_caught() -> None:
    bullets = [
        TailoredBullet(
            text="Led data validation initiatives using Excel",
            source_id="genova-validation",
        )
    ]
    assert [v.kind for v in check(bullets, _resume())] == ["scope-inflation"]


def test_invented_breadth_is_caught() -> None:
    bullets = [
        TailoredBullet(
            text="Conducted data validation across the platform",
            source_id="genova-validation",
        )
    ]
    assert [v.kind for v in check(bullets, _resume())] == ["invented-breadth"]


def test_invented_number_is_caught() -> None:
    """Numbers may be dropped. They may never be conjured."""
    bullets = [
        TailoredBullet(
            text="Conducted data validation across 500 tracked work items",
            source_id="genova-validation",
        )
    ]
    violations = check(bullets, _resume())
    assert [v.kind for v in violations] == ["invented-number"]
    assert "500" in violations[0].detail


def test_a_drifting_metric_is_caught() -> None:
    bullets = [
        TailoredBullet(
            text="Coordinated an event for 250 attendees on a $7K budget",
            source_id="genova-event",
        )
    ]
    assert [v.kind for v in check(bullets, _resume())] == ["invented-number"]


def test_unsourced_prose_is_caught() -> None:
    """A bullet with no fact behind it is the worst case, not an edge case."""
    bullets = [TailoredBullet(text="Delivered transformational business value", source_id="nope")]
    assert [v.kind for v in check(bullets, _resume())] == ["unsourced"]


# -- what must still be allowed ----------------------------------------------


def test_faithful_rephrasing_passes() -> None:
    """The check must not be so strict that legitimate tailoring is impossible."""
    bullets = [
        TailoredBullet(
            text=(
                "Performed data validation and quality checks in Excel across "
                "100+ tracked work items"
            ),
            source_id="genova-validation",
        ),
        TailoredBullet(
            text="Owned logistics and stakeholder outreach for a 100-attendee event",
            source_id="genova-event",
        ),
    ]
    assert check(bullets, _resume()) == []


def test_dropping_a_number_is_allowed() -> None:
    bullets = [
        TailoredBullet(
            text="Conducted data validation and quality checks using Excel",
            source_id="genova-validation",
        )
    ]
    assert check(bullets, _resume()) == []


def test_stating_less_scope_than_held_is_allowed() -> None:
    bullets = [
        TailoredBullet(
            text="Coordinated logistics for a 100-attendee event",
            source_id="genova-event",
        )
    ]
    assert check(bullets, _resume()) == []


# -- enforcement --------------------------------------------------------------


def test_enforce_refuses_rather_than_warning() -> None:
    bullets = [
        TailoredBullet(
            text="Led data quality across the organization",
            source_id="genova-validation",
        )
    ]
    with pytest.raises(TruthfulnessError) as excinfo:
        enforce(bullets, _resume())
    kinds = {v.kind for v in excinfo.value.violations}
    assert kinds == {"scope-inflation", "invented-breadth"}


def test_enforce_passes_a_clean_variant() -> None:
    bullets = [
        TailoredBullet(
            text="Conducted data validation using Excel formulas",
            source_id="genova-validation",
        )
    ]
    enforce(bullets, _resume())  # must not raise


def test_duplicate_accomplishment_ids_are_rejected() -> None:
    resume = _resume()
    dup = resume.roles[0].accomplishments[0].model_copy()
    with pytest.raises(ValueError, match="duplicate accomplishment id"):
        Resume.model_validate(
            {
                **resume.model_dump(),
                "roles": [
                    {
                        **resume.roles[0].model_dump(),
                        "accomplishments": [
                            *[a.model_dump() for a in resume.roles[0].accomplishments],
                            dup.model_dump(),
                        ],
                    }
                ],
            }
        )


def test_the_committed_example_resume_stays_valid() -> None:
    """The example is documentation. Validated in CI so it cannot rot."""
    from pathlib import Path

    from jobagent.application.resume import load

    resume = load(Path(__file__).resolve().parents[1] / "resume.example.yaml")
    assert resume.all_accomplishments()
    assert all(a.id for a in resume.all_accomplishments())


def test_the_example_resume_carries_no_real_contact_details() -> None:
    """This repository is public. Real PII lives in the untracked data dir."""
    from pathlib import Path

    text = (Path(__file__).resolve().parents[1] / "resume.example.yaml").read_text()
    for leak in ("dareoluwatoby@", "226-337-5946", "Mississauga"):
        assert leak not in text, f"{leak!r} must not be committed to a public repo"
