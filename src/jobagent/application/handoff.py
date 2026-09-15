"""Hand off an application to Claude in Chrome.

The board deliberately does not automate submission. Claude in Chrome runs in the
user's own browser, in their own session, with them watching -- which is both the
only thing that works against Workday-style portals without fighting bot
protection, and the human gate that keeps a bad draft from reaching a recruiter.

So "apply" here means: open the posting, and put a ready prompt on the clipboard.
"""

from __future__ import annotations

import shutil
import subprocess
import webbrowser
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class Applicant:
    """The answers every co-op portal asks for. Facts, never regenerated."""

    name: str
    email: str
    phone: str
    location: str
    linkedin: str
    github: str
    school: str
    degree: str
    grad: str
    authorization: str
    availability: str


DEFAULT_APPLICANT = Applicant(
    name="Oluwatoby Dare",
    email="dareoluwatoby@gmail.com",
    phone="226-337-5946",
    location="Mississauga, ON",
    linkedin="linkedin.com/in/oluwatoby-dare",
    github="github.com/tdare514",
    school="University of Guelph",
    degree="Bachelor of Computing (Honours), Computer Science",
    grad="Expected 2026",
    authorization="Canadian citizen / authorized to work in Canada",
    availability="Available for a Winter 2027 term, starting January 2027",
)


def build_prompt(
    company: str,
    title: str,
    url: str | None,
    applicant: Applicant = DEFAULT_APPLICANT,
    resume_path: Path | None = None,
) -> str:
    """The prompt handed to Claude in Chrome on the posting page."""
    resume_line = (
        f"My resume is at {resume_path}. Upload it when the form asks for a file."
        if resume_path
        else "Upload the resume file I have ready when the form asks for one."
    )
    return f"""\
I'm applying to this role. Please fill in the application form on this page using \
the details below. Do not submit it -- stop when the form is complete and tell me \
what still needs my input, and I'll review and submit myself.

Role: {title}
Company: {company}
{f"Posting: {url}" if url else ""}

My details:
- Name: {applicant.name}
- Email: {applicant.email}
- Phone: {applicant.phone}
- Location: {applicant.location}
- LinkedIn: {applicant.linkedin}
- GitHub: {applicant.github}
- School: {applicant.school}
- Program: {applicant.degree}, {applicant.grad}
- Work authorization: {applicant.authorization}
- Availability: {applicant.availability}

{resume_line}

Rules:
1. Do not invent anything about my experience. If a field needs information I \
have not given you, leave it blank and tell me.
2. Do not click the final submit button.
3. If the form asks a free-text question (why this company, greatest strength), \
draft an answer and flag it so I can edit it before submitting.
"""


def copy_to_clipboard(text: str) -> str | None:
    """Copy text using whatever the platform provides. Returns the tool used."""
    candidates = [
        ("pbcopy", ["pbcopy"]),
        ("wl-copy", ["wl-copy"]),
        ("xclip", ["xclip", "-selection", "clipboard"]),
        ("xsel", ["xsel", "--clipboard", "--input"]),
        ("clip.exe", ["clip.exe"]),
    ]
    for name, cmd in candidates:
        if shutil.which(cmd[0]) is None:
            continue
        try:
            subprocess.run(cmd, input=text.encode(), check=True, timeout=5)
            return name
        except (subprocess.SubprocessError, OSError):
            continue
    return None


def open_posting(url: str) -> bool:
    try:
        return webbrowser.open(url)
    except Exception:
        return False
