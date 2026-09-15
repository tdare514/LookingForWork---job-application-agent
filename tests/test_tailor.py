"""Selection and ordering. The truthfulness gate is tested in test_truthfulness."""

from __future__ import annotations

from pathlib import Path

from jobagent.application.resume import Resume, load
from jobagent.application.tailor import Posting, score, tailor

EXAMPLE = Path(__file__).resolve().parents[1] / "resume.example.yaml"


def _resume() -> Resume:
    return load(EXAMPLE)


BA_POSTING = Posting(
    company="BMO",
    title="Business Analyst, Winter 2027",
    description=(
        "Gather and document business requirements, write user stories, and work "
        "with stakeholders and developers. Experience with Jira and Agile delivery "
        "is an asset. Strong documentation and communication skills required."
    ),
)

ENG_POSTING = Posting(
    company="Scotiabank",
    title="Software Engineer Intern",
    description=(
        "Build services in Python, integrate REST APIs, and contribute to data "
        "ingestion pipelines. Testing and quality assurance experience valued."
    ),
)


def test_a_requirements_posting_ranks_requirements_work_first() -> None:
    resume = _resume()
    ranked = sorted(
        (score(a, BA_POSTING) for a in resume.all_accomplishments()),
        key=lambda s: -s.score,
    )
    top_ids = {s.accomplishment.id for s in ranked[:4]}
    assert top_ids & {"launchpath-requirements", "launchpath-stories", "launchpath-jira"}


def test_an_engineering_posting_ranks_engineering_work_first() -> None:
    """The same resume must rank differently for a different posting, or selection is noise."""
    resume = _resume()
    ba_top = max(resume.all_accomplishments(), key=lambda a: score(a, BA_POSTING).score).id
    eng_top = max(resume.all_accomplishments(), key=lambda a: score(a, ENG_POSTING).score).id
    assert ba_top != eng_top


def test_declared_skills_outweigh_incidental_word_overlap() -> None:
    resume = _resume()
    jira = resume.accomplishment("launchpath-jira")
    assert jira is not None
    scored = score(jira, BA_POSTING)
    assert "jira" in scored.matched
    assert scored.score > 0


def test_a_measured_accomplishment_wins_a_tie() -> None:
    """Equal relevance, one with a number: the number is more persuasive."""
    from jobagent.application.resume import Accomplishment

    posting = Posting(company="X", title="Y", description="documentation")
    measured = Accomplishment(
        id="m", text="Wrote documentation", metric="40 pages", skills=["documentation"]
    )
    unmeasured = Accomplishment(id="u", text="Wrote documentation", skills=["documentation"])

    assert score(measured, posting).score > score(unmeasured, posting).score


def test_a_measurement_does_not_outrank_genuine_relevance() -> None:
    """A metric breaks ties. It must not promote an irrelevant bullet."""
    from jobagent.application.resume import Accomplishment

    posting = Posting(company="X", title="Y", description="documentation requirements")
    relevant = Accomplishment(
        id="r", text="Wrote requirements documentation", skills=["documentation", "requirements"]
    )
    irrelevant = Accomplishment(id="i", text="Played bass", metric="3 gigs", skills=["bass"])

    assert score(relevant, posting).score > score(irrelevant, posting).score


def test_no_role_is_stripped_to_nothing() -> None:
    """An employer with no bullets reads as a gap -- worse than an off-target bullet."""
    resume = _resume()
    irrelevant = Posting(company="X", title="Marine Biologist", description="coral reefs")
    result = tailor(resume, irrelevant)
    assert len(result.roles) == len(resume.roles)
    for tailored in result.roles:
        assert len(tailored.bullets) >= 2


def test_bullets_are_verbatim_from_the_source() -> None:
    """Selection must not rewrite. That is what makes it fabrication-free."""
    resume = _resume()
    result = tailor(resume, BA_POSTING)
    for bullet in result.bullets():
        source = resume.accomplishment(bullet.source_id)
        assert source is not None
        assert bullet.text == source.text


def test_tailoring_passes_the_truthfulness_gate() -> None:
    """tailor() calls enforce() itself; if it ever stops, this fails."""
    resume = _resume()
    result = tailor(resume, BA_POSTING)
    assert result.bullets()
    assert result.selected


def test_budget_is_respected() -> None:
    resume = _resume()
    result = tailor(resume, BA_POSTING, max_bullets_per_role=2)
    for tailored in result.roles:
        assert len(tailored.bullets) <= 2


def test_dropped_bullets_are_reported_not_silently_lost() -> None:
    resume = _resume()
    result = tailor(resume, BA_POSTING, max_bullets_per_role=2)
    assert result.dropped
    kept = {s.accomplishment.id for s in result.selected}
    dropped = {s.accomplishment.id for s in result.dropped}
    assert not (kept & dropped)
