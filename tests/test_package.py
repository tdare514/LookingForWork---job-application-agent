"""Answer library, cover letter, rendering and package assembly."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from jobagent.application.answers import (
    cover_letter,
    standing_answers,
    why_this_company_draft,
)
from jobagent.application.package import build
from jobagent.application.render import render
from jobagent.application.resume import load
from jobagent.application.tailor import Posting, tailor

EXAMPLE = Path(__file__).resolve().parents[1] / "resume.example.yaml"

POSTING = Posting(
    company="BMO",
    title="Business Analyst, Winter 2027",
    description="Requirements gathering, user stories, Jira, stakeholder communication.",
)


def _library() -> object:
    return standing_answers(
        authorization="Authorized to work in Canada; no sponsorship required.",
        availability="Available from January 2027.",
        term_lengths="4, 8 or 12 months.",
        notice="None.",
        compensation="Open to the posted range.",
        relocation="Able to commute to the office.",
    )


# -- the answer library -------------------------------------------------------


def test_a_rephrased_question_finds_its_stored_answer() -> None:
    """Portals never ask the same question twice the same way."""
    library = standing_answers(
        authorization="Authorized to work in Canada; no sponsorship required.",
        availability="Available from January 2027.",
        term_lengths="4, 8 or 12 months.",
        notice="None.",
        compensation="Open to the posted range.",
        relocation="Able to commute.",
    )
    found = library.find("Do you require sponsorship for employment in Canada?")
    assert found is not None
    assert "no sponsorship" in found.text


def test_an_unrelated_question_matches_nothing() -> None:
    """A loose matcher that answers the wrong question is worse than no matcher."""
    library = standing_answers(
        authorization="a",
        availability="b",
        term_lengths="c",
        notice="d",
        compensation="e",
        relocation="f",
    )
    assert library.find("Describe a time you resolved a conflict on a team.") is None


def test_work_authorization_is_a_stored_fact_not_generated() -> None:
    library = standing_answers(
        authorization="Authorized to work in Canada; no sponsorship required.",
        availability="x",
        term_lengths="x",
        notice="x",
        compensation="x",
        relocation="x",
    )
    for answer in library.answers:
        assert answer.standing is True


def test_why_this_company_is_a_draft_that_demands_the_human() -> None:
    """Generating enthusiasm invents a motive the applicant does not hold."""
    draft = why_this_company_draft(POSTING)
    assert draft.standing is False
    assert "needs your input" in draft.text.lower()
    assert "BMO" in draft.text


# -- the cover letter ---------------------------------------------------------


def test_cover_letter_highlights_come_from_the_resume() -> None:
    resume = load(EXAMPLE)
    highlights = ["Created and organized 13+ user stories"]
    letter = cover_letter(resume, POSTING, highlights)
    assert highlights[0] in letter
    assert resume.contact.name in letter
    assert "BMO" in letter


def test_cover_letter_leaves_the_company_paragraph_to_the_human() -> None:
    resume = load(EXAMPLE)
    letter = cover_letter(resume, POSTING, ["something"])
    assert "[YOUR PARAGRAPH" in letter


# -- rendering ----------------------------------------------------------------


def test_both_formats_render_from_one_structure(tmp_path: Path) -> None:
    resume = load(EXAMPLE)
    tailored = tailor(resume, POSTING)
    docs = render(resume, tailored, tmp_path)
    assert docs.pdf.is_file() and docs.pdf.stat().st_size > 1000
    assert docs.docx.is_file() and docs.docx.stat().st_size > 1000


def test_rendered_pdf_is_a_single_page(tmp_path: Path) -> None:
    import re

    resume = load(EXAMPLE)
    docs = render(resume, tailor(resume, POSTING), tmp_path)
    data = docs.pdf.read_bytes()
    assert len(re.findall(rb"/Type\s*/Page[^s]", data)) == 1


def test_filenames_carry_no_pii_beyond_the_applicants_own_name(tmp_path: Path) -> None:
    resume = load(EXAMPLE)
    docs = render(resume, tailor(resume, POSTING), tmp_path)
    for path in (docs.pdf, docs.docx):
        assert "@" not in path.name
        assert not any(ch.isdigit() and ch in "0123456789" for ch in path.stem.split("-")[-1])


# -- package assembly ---------------------------------------------------------


def test_package_contains_everything_a_portal_asks_for(tmp_path: Path) -> None:
    resume = load(EXAMPLE)
    package = build(resume, POSTING, _library(), tmp_path)  # type: ignore[arg-type]
    assert package.documents.pdf.is_file()
    assert package.documents.docx.is_file()
    assert package.cover_letter_path.is_file()
    answers = json.loads(package.answers_path.read_text())
    assert any(a["needs_you"] for a in answers), "the human's paragraph must be flagged"
    assert any("sponsorship" in a["question"].lower() for a in answers)


def test_package_bullets_are_all_traceable_to_the_resume(tmp_path: Path) -> None:
    """If this ever fails, something rendered a claim with no fact behind it."""
    resume = load(EXAMPLE)
    package = build(resume, POSTING, _library(), tmp_path)  # type: ignore[arg-type]
    for bullet in package.tailored.bullets():
        assert resume.accomplishment(bullet.source_id) is not None


def test_a_resume_that_fails_the_truth_check_never_renders(tmp_path: Path) -> None:
    """The gate sits before rendering, not after."""
    from jobagent.application.truthfulness import TruthfulnessError

    resume = load(EXAMPLE)
    acc = resume.roles[0].accomplishments[0]
    object.__setattr__(acc, "text", "Led data quality across the platform for 900 items")

    with pytest.raises(TruthfulnessError):
        build(resume, POSTING, _library(), tmp_path)  # type: ignore[arg-type]
    assert not list(tmp_path.glob("*.pdf")), "nothing may render after a failed check"
