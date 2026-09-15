"""Assemble a complete application package for one posting.

Everything a portal will ask for, in one directory: a tailored resume in both
formats, a cover letter, and the answers to the questions that recur.

Nothing here sends anything. The package ends at the approval gate -- the
handoff prompt and the human at the browser (ADR 0005).
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

from jobagent.application.answers import (
    AnswerLibrary,
    cover_letter,
    why_this_company_draft,
)
from jobagent.application.render import RenderedDocuments, render
from jobagent.application.resume import Resume
from jobagent.application.tailor import Posting, TailoredResume, tailor


@dataclass
class Package:
    directory: Path
    posting: Posting
    tailored: TailoredResume
    documents: RenderedDocuments
    cover_letter_path: Path
    answers_path: Path

    def summary(self) -> list[tuple[str, str]]:
        return [
            ("Company", self.posting.company),
            ("Role", self.posting.title),
            ("Resume (PDF)", self.documents.pdf.name),
            ("Resume (DOCX)", self.documents.docx.name),
            ("Cover letter", self.cover_letter_path.name),
            ("Answers", self.answers_path.name),
            ("Bullets selected", str(len(self.tailored.bullets()))),
            ("Bullets dropped", str(len(self.tailored.dropped))),
        ]


def build(
    resume: Resume,
    posting: Posting,
    library: AnswerLibrary,
    out_dir: Path,
    *,
    max_bullets_per_role: int = 4,
) -> Package:
    """Tailor, validate, render, and write the whole package to disk."""
    # tailor() runs the truthfulness gate itself and raises on any unsupported
    # claim, so nothing below can render an unvalidated variant.
    tailored = tailor(resume, posting, max_bullets_per_role=max_bullets_per_role)

    out_dir.mkdir(parents=True, exist_ok=True)
    documents = render(resume, tailored, out_dir)

    # The strongest three bullets carry the letter; more turns it into a resume.
    highlights = [
        s.accomplishment.text for s in sorted(tailored.selected, key=lambda s: -s.score)[:3]
    ]
    letter_path = out_dir / "cover-letter.txt"
    letter_path.write_text(cover_letter(resume, posting, highlights))

    draft = why_this_company_draft(posting)
    answers = [
        {"question": a.question, "answer": a.text, "needs_you": not a.standing}
        for a in [*library.answers, draft]
    ]
    answers_path = out_dir / "answers.json"
    answers_path.write_text(json.dumps(answers, indent=2))

    return Package(
        directory=out_dir,
        posting=posting,
        tailored=tailored,
        documents=documents,
        cover_letter_path=letter_path,
        answers_path=answers_path,
    )
