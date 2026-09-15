"""One posting, as the filters and the scorer need to see it.

A `Job` row is what the board tracks; a `Requirements` is what extraction found.
Ranking needs both at once, plus a couple of columns the board's own dataclass
never carried because the board never needed them. Rather than widen `Job` --
which is read by the TUI, the funnel and the follow-up rules -- this is the
shape the matching pipeline asks the repository for.

Deliberately flat and free of behaviour. The filters and the scorer both take
one of these, and neither can reach back into the database through it.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from jobagent.matching.extract import Requirements


@dataclass(frozen=True)
class Candidate:
    job_id: int
    company: str
    title: str
    location: str | None = None
    description: str | None = None
    work_arrangement: str | None = None
    compensation_min: int | None = None
    compensation_max: int | None = None
    currency: str | None = None
    posted_at: str | None = None
    first_seen_at: str | None = None
    requirements: Requirements = field(default_factory=Requirements)

    @property
    def text(self) -> str:
        """Title and body together, which is what most rules want to read.

        The title carries signal the body often does not repeat -- "Intern",
        "Senior", the division -- so a rule that reads only the description is
        reading half the posting.
        """
        return f"{self.title}\n{self.description or ''}"
