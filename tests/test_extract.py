"""Rule-based requirement extraction, and its evaluation (#30).

Two kinds of test here, doing different jobs.

The unit tests pin individual rules against text taken from real postings. The
**evaluation harness** at the bottom is the one #30 actually asks for: it runs
extraction over a hand-labelled corpus and reports per-field precision and
recall, failing when a field drops below a floor. Without it, a rule change that
quietly degrades every downstream score looks exactly like a rule change that
does not.

The labels in `fixtures/labels.json` were read off the posting text, not copied
from this extractor's output. Labels derived from the thing under test measure
nothing.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

import pytest

from jobagent.matching.extract import RULESET_VERSION, Requirements, extract

FIXTURES = Path(__file__).parent / "fixtures"
POSTINGS = json.loads((FIXTURES / "postings.json").read_text())
LABELS = {
    k: v
    for k, v in json.loads((FIXTURES / "labels.json").read_text()).items()
    if not k.startswith("_")
}
BY_ID = {p["source_id"]: p for p in POSTINGS}


# -- sections: the failure that makes everything downstream wrong -------------


def test_a_benefits_list_is_not_a_requirements_list() -> None:
    """The trap. Both are bulleted, adjacent, and look identical.

    RBC puts "What's in it for you?" directly after the requirements, with
    bullets like "Leaders who support your development". Reading those as things
    the candidate must have would poison every score built on this.
    """
    result = extract(
        "What do you need to succeed?\n"
        "Must-have\n"
        "- Good command of Excel, VBA programming and SQL\n"
        "What's in it for you?\n"
        "- Leaders who support your development through coaching\n"
        "- Opportunities to do challenging work\n"
    )
    assert result.required_bullets == ("Good command of Excel, VBA programming and SQL",)
    assert "Leaders who support your development through coaching" not in result.required_bullets
    assert result.preferred_bullets == ()


def test_required_and_preferred_are_distinguished() -> None:
    result = extract(
        "Must-have\n- Excel and SQL\nNice-to-have\n- Experience with Python and PySpark\n"
    )
    assert "sql" in result.required_skills
    assert "python" in result.preferred_skills
    assert "python" not in result.required_skills


def test_unlabelled_bullets_contribute_nothing() -> None:
    """Most of a posting is prose about the company. Silence is the safe default."""
    result = extract("We are a great place to work.\n- We have free coffee\n- And a gym\n")
    assert result.required_bullets == ()
    assert result.required_skills == ()


# -- compensation -------------------------------------------------------------


def test_a_band_is_read_when_the_line_is_about_pay() -> None:
    result = extract("Salary:\n$85,500.00 - $185,000.00\nPay Type:\nSalaried\n")
    assert (result.compensation_min, result.compensation_max) == (85500, 185000)


def test_a_dollar_figure_that_is_not_a_salary_is_not_a_band() -> None:
    """Postings are full of money that is not pay: portfolios, budgets, deals."""
    result = extract("Manage a $2,500,000 portfolio of commercial accounts.\n")
    assert result.compensation_min is None


def test_currency_is_kept_when_stated() -> None:
    result = extract("Pay Details:\n$76,290 - $114,440 USD\n")
    assert result.currency == "USD"
    assert (result.compensation_min, result.compensation_max) == (76290, 114440)


def test_undisclosed_compensation_is_null_not_zero() -> None:
    """It is the common case, and it is not a disqualifier."""
    result = extract("Must-have\n- Excel\n")
    assert result.compensation_min is None
    assert result.currency is None


# -- the deadline, which is what this project runs on -------------------------


def test_the_day_prior_note_moves_the_real_deadline_back() -> None:
    """RBC labels the 21st and then says applications close the day before.

    Believing the label means believing you have a day you do not have. This is
    the most expensive mistake available to this tool.
    """
    result = extract(
        "Application Deadline:\n2026-09-21\n"
        "Note: Applications will be accepted until 11:59 PM on the day prior to "
        "the application deadline date above\n"
    )
    assert result.application_deadline == "2026-09-20"


def test_a_plain_labelled_deadline_is_taken_as_stated() -> None:
    """BMO says 09/24/2026 and means it."""
    result = extract("Application Deadline:\n09/24/2026\nAddress:\n250 Yonge Street\n")
    assert result.application_deadline == "2026-09-24"


def test_a_deadline_written_in_prose_is_already_the_effective_date() -> None:
    result = extract("Please note that the formal application deadline is September 20, 2026.\n")
    assert result.application_deadline == "2026-09-20"


# -- years, arrangement, sponsorship ------------------------------------------


def test_the_lowest_stated_experience_requirement_wins() -> None:
    """Taking the highest would filter out roles the candidate qualifies for."""
    result = extract("Qualifications:\n- 2+ years of experience\n- 5+ years would be ideal\n")
    assert result.min_years == 2


def test_a_range_of_years_keeps_both_ends() -> None:
    result = extract("Qualifications:\n- Typically between 5 - 7 years of relevant experience\n")
    assert (result.min_years, result.max_years) == (5, 7)


def test_work_arrangement_is_read_from_the_body() -> None:
    assert extract("This is an in-office position in Wilmington, DE.").work_arrangement == "onsite"
    assert extract("Our teams work in a hybrid model.").work_arrangement == "hybrid"


def test_sponsorship_language_is_detected_but_silence_is_not_a_no() -> None:
    assert extract("You must be legally authorized to work in Canada.").sponsorship == "not_offered"
    assert extract("Visa sponsorship is available for this role.").sponsorship == "offered"
    assert extract("Must-have\n- Excel\n").sponsorship is None


# -- robustness: #30 requires one bad posting not to abort a run --------------


@pytest.mark.parametrize("bad", ["", "   ", "\n\n\n", "<<<>>>", "- " * 500])
def test_nothing_defeats_the_extractor(bad: str) -> None:
    result = extract(bad)
    assert isinstance(result, Requirements)
    assert result.ruleset_version == RULESET_VERSION


def test_a_missing_description_is_an_empty_extraction_not_a_crash() -> None:
    assert extract(None).required_skills == ()


def test_every_extraction_records_the_ruleset_that_produced_it() -> None:
    """Traceability: a quality change must point at a rule change."""
    assert extract("Must-have\n- SQL\n").ruleset_version == RULESET_VERSION


# -- the evaluation harness ---------------------------------------------------


@dataclass
class Score:
    field: str
    correct: int = 0
    predicted: int = 0
    labelled: int = 0

    @property
    def precision(self) -> float:
        return self.correct / self.predicted if self.predicted else 1.0

    @property
    def recall(self) -> float:
        return self.correct / self.labelled if self.labelled else 1.0


def _evaluate() -> dict[str, Score]:
    """Score each field over the labelled corpus.

    Precision is "of what it claimed, how much was right"; recall is "of what
    the posting stated, how much it found". A field the posting does not state
    counts toward neither -- predicting nothing for an absent field is correct
    behaviour, not a miss.
    """
    scores = {f: Score(f) for f in ("deadline", "compensation", "years", "arrangement")}
    for source_id, label in LABELS.items():
        result = extract(BY_ID[source_id]["description"])
        predictions = {
            "deadline": result.application_deadline,
            "compensation": (
                [result.compensation_min, result.compensation_max, result.currency]
                if result.compensation_min is not None
                else None
            ),
            "years": (
                [result.min_years, result.max_years] if result.min_years is not None else None
            ),
            "arrangement": result.work_arrangement,
        }
        truths = {
            "deadline": label["deadline"],
            "compensation": label["comp"] if label["comp"][0] is not None else None,
            "years": label["years"] if label["years"][0] is not None else None,
            "arrangement": label["arrangement"],
        }
        for field_name, score in scores.items():
            predicted, truth = predictions[field_name], truths[field_name]
            score.predicted += predicted is not None
            score.labelled += truth is not None
            score.correct += predicted is not None and predicted == truth
    return scores


# Floors, not targets: set at what this ruleset achieves on this corpus, so a
# regression fails CI. Raise them when a rule improves; never lower one to make
# a change pass.
#
# They are all 1.0, and that number deserves suspicion rather than pride. The
# corpus is twelve postings from three tenants that share a platform, and these
# four fields are the *mechanical* ones -- a labelled date, a dollar band, a
# number before "years", a keyword. The fields rules are actually bad at, like
# reading a skill out of a sentence, are not scored here because labelling them
# is a judgement about this job search. A perfect score on the easy half is not
# evidence the hard half works.
FLOORS: dict[str, tuple[float, float]] = {
    "deadline": (1.0, 1.0),
    "compensation": (1.0, 1.0),
    "years": (1.0, 1.0),
    "arrangement": (1.0, 1.0),
}


def test_extraction_quality_has_not_regressed() -> None:
    """The acceptance criterion: per-field precision and recall, enforced in CI."""
    scores = _evaluate()
    report = "\n".join(
        f"  {s.field:13} precision={s.precision:.2f} recall={s.recall:.2f} "
        f"(correct {s.correct}/{s.predicted} predicted, {s.labelled} labelled)"
        for s in scores.values()
    )
    failures = [
        f"{name}: precision {scores[name].precision:.2f} < {p:.2f}"
        if scores[name].precision < p
        else f"{name}: recall {scores[name].recall:.2f} < {r:.2f}"
        for name, (p, r) in FLOORS.items()
        if scores[name].precision < p or scores[name].recall < r
    ]
    assert not failures, "extraction quality regressed:\n" + report + "\n" + "\n".join(failures)


def test_the_corpus_is_real_and_every_posting_is_labelled() -> None:
    """A harness scoring against a corpus that drifted from its labels is noise."""
    assert set(LABELS) == set(BY_ID), "postings.json and labels.json disagree"
    assert len(LABELS) >= 12
    for posting in POSTINGS:
        assert posting["description"], f"{posting['source_id']} has no description"
