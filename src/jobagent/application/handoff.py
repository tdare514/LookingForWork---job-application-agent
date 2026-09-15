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

from jobagent.application.resume import Resume


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


def applicant_from(resume: Resume, *, authorization: str, availability: str) -> Applicant:
    """Derive the portal answers from the resume, so there is one owner per fact.

    Contact details are never hardcoded here: this repository is public, and the
    real values live in the data directory. A test asserts the source tree stays
    free of them.
    """
    edu = resume.education[0] if resume.education else None
    return Applicant(
        name=resume.contact.name,
        email=resume.contact.email,
        phone=resume.contact.phone,
        location=resume.contact.location,
        linkedin=resume.contact.linkedin or "",
        github=resume.contact.github or "",
        school=edu.school if edu else "",
        degree=edu.credential if edu else "",
        grad=edu.graduation if edu else "",
        authorization=authorization,
        availability=availability,
    )


def build_prompt(
    company: str,
    title: str,
    url: str | None,
    applicant: Applicant,
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
