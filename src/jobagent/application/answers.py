"""The answer library.

Co-op applications ask the same questions. Sponsorship status, availability,
term length, notice period, expected pay. These are facts, not prose -- they
come from the profile and are reused verbatim. Regenerating them per
application is both wasteful and a fresh chance to get one wrong, and getting
work authorization wrong on a bank application is not a small error.

Only the company-specific answer ("why this company") is drafted per posting,
and it is drafted as a prompt for a human to finish rather than invented here.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from jobagent.application.resume import Resume
from jobagent.application.tailor import Posting


@dataclass(frozen=True)
class Answer:
    question: str
    text: str
    # A standing fact is reused verbatim. A draft needs a human before it is sent.
    standing: bool = True


@dataclass
class AnswerLibrary:
    answers: list[Answer] = field(default_factory=list)

    def find(self, question: str) -> Answer | None:
        """Match a rephrased question to a stored answer by keyword overlap."""
        asked = _keywords(question)
        if not asked:
            return None
        best: tuple[float, Answer] | None = None
        for answer in self.answers:
            stored = _keywords(answer.question)
            if not stored:
                continue
            overlap = len(asked & stored) / len(asked | stored)
            if overlap >= 0.34 and (best is None or overlap > best[0]):
                best = (overlap, answer)
        return best[1] if best else None


_WORD = re.compile(r"[a-z]{3,}")
_IGNORE_TEXT = (
    "are you your the and for what when will with that this have has any please"
    " tell about able would could should from"
)
_IGNORE = frozenset(_IGNORE_TEXT.split())


def _keywords(text: str) -> set[str]:
    return {w for w in _WORD.findall(text.lower()) if w not in _IGNORE}


def standing_answers(
    *,
    authorization: str,
    availability: str,
    term_lengths: str,
    notice: str,
    compensation: str,
    relocation: str,
) -> AnswerLibrary:
    """The facts every co-op portal asks for. Stated once, reused everywhere."""
    return AnswerLibrary(
        [
            Answer("Are you legally authorized to work in Canada?", authorization),
            Answer("Will you require sponsorship for employment?", authorization),
            Answer("What is your availability / start date?", availability),
            Answer("What work term lengths can you commit to?", term_lengths),
            Answer("What is your notice period?", notice),
            Answer("What are your compensation expectations?", compensation),
            Answer("Are you willing to relocate or commute to the office?", relocation),
        ]
    )


def why_this_company_draft(posting: Posting) -> Answer:
    """A scaffold, not an answer.

    Generating enthusiasm for a company from its own job posting produces the
    exact paragraph every reviewer has read a hundred times. Worse, it invents a
    motive the applicant does not hold. So this returns a draft that names what
    the human has to supply, and is marked as needing them.
    """
    return Answer(
        question=f"Why do you want to work at {posting.company}?",
        text=(
            f"[DRAFT - needs your input before sending]\n"
            f"Role: {posting.title} at {posting.company}.\n"
            f"Write two or three sentences covering:\n"
            f"  1. One specific thing about {posting.company} you actually know "
            f"(a product, a team, something you have used or read).\n"
            f"  2. Which part of your experience the role builds on.\n"
            f"  3. What you want to learn there.\n"
            f"Do not write that you are 'passionate about their mission' unless "
            f"you can name the mission."
        ),
        standing=False,
    )


def cover_letter(resume: Resume, posting: Posting, highlights: list[str]) -> str:
    """Assemble a cover letter from facts already in the resume.

    Every substantive sentence is a selected accomplishment, so the letter
    inherits the truthfulness guarantee. The opening and closing are structural.
    The company-specific paragraph is left for the human, deliberately.
    """
    c = resume.contact
    bullet_lines = "\n".join(f"- {h}" for h in highlights)
    return f"""{c.name}
{c.location}  |  {c.phone}  |  {c.email}

Hiring Team
{posting.company}

Dear Hiring Team,

I am applying for the {posting.title} position at {posting.company}. I am a \
Computer Science student at the University of Guelph with three work terms \
spanning business analysis, project coordination and software development.

What I would bring to this role:

{bullet_lines}

[YOUR PARAGRAPH: two or three sentences on why {posting.company} specifically. \
Name something concrete. This is the only part a reviewer can tell was written \
for them.]

I would welcome the chance to discuss how my experience fits your team.

Sincerely,
{c.name}
"""
