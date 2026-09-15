"""The resume source of truth.

One structured document holds every claim the agent is allowed to make. This is
not a formatting document -- it is the fact base. Tailored variants are derived
from it; it is never derived from them.

Each accomplishment carries the raw material tailoring needs in order to choose
well, and the material the truthfulness check needs in order to refuse: the
measurement, the technologies, and the scope actually held.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml
from pydantic import BaseModel, Field, field_validator, model_validator


class Contact(BaseModel):
    name: str
    email: str
    phone: str
    location: str
    linkedin: str | None = None
    github: str | None = None


class Accomplishment(BaseModel):
    """One thing that actually happened. The atom of everything downstream."""

    id: str = Field(description="Stable handle, referenced by tailored bullets.")
    text: str = Field(description="What was done, as it may be stated.")
    # None means unmeasured. Say so rather than implying a number.
    metric: str | None = None
    skills: list[str] = Field(default_factory=list)
    # Scope is the field that stops the most dangerous fabrication: quiet
    # promotion. "Contributed to" must not become "led" because a posting
    # wanted leadership.
    scope: str = Field(
        default="contributed",
        description="One of: contributed, owned, led. What was actually held.",
    )

    @field_validator("scope")
    @classmethod
    def _known_scope(cls, v: str) -> str:
        allowed = {"contributed", "owned", "led"}
        if v not in allowed:
            raise ValueError(f"scope must be one of {sorted(allowed)}, got {v!r}")
        return v

    @field_validator("id")
    @classmethod
    def _id_shape(cls, v: str) -> str:
        if not v or " " in v:
            raise ValueError("accomplishment id must be non-empty and contain no spaces")
        return v


class Role(BaseModel):
    title: str
    organization: str
    location: str
    start: str
    end: str | None = None  # None means current
    accomplishments: list[Accomplishment] = Field(default_factory=list)

    @property
    def is_current(self) -> bool:
        return self.end is None


class Education(BaseModel):
    school: str
    credential: str
    location: str
    graduation: str
    coursework: list[str] = Field(default_factory=list)
    honours: str | None = None


class Project(BaseModel):
    name: str
    tech: list[str] = Field(default_factory=list)
    date: str | None = None
    accomplishments: list[Accomplishment] = Field(default_factory=list)


class Standing(BaseModel):
    """Answers every portal asks for. Facts, so they live with the other facts."""

    authorization: str = ""
    availability: str = ""
    term_lengths: str = ""
    notice: str = ""
    compensation: str = ""
    relocation: str = ""


class Resume(BaseModel):
    contact: Contact
    summary: str
    education: list[Education]
    roles: list[Role]
    projects: list[Project] = Field(default_factory=list)
    leadership: list[Accomplishment] = Field(default_factory=list)
    skills: dict[str, list[str]] = Field(default_factory=dict)
    standing: Standing = Field(default_factory=Standing)

    @model_validator(mode="after")
    def _unique_accomplishment_ids(self) -> Resume:
        seen: set[str] = set()
        for acc in self.all_accomplishments():
            if acc.id in seen:
                raise ValueError(f"duplicate accomplishment id: {acc.id!r}")
            seen.add(acc.id)
        return self

    def all_accomplishments(self) -> list[Accomplishment]:
        out: list[Accomplishment] = []
        for role in self.roles:
            out.extend(role.accomplishments)
        for project in self.projects:
            out.extend(project.accomplishments)
        out.extend(self.leadership)
        return out

    def accomplishment(self, acc_id: str) -> Accomplishment | None:
        return next((a for a in self.all_accomplishments() if a.id == acc_id), None)

    @classmethod
    def from_yaml(cls, path: Path) -> Resume:
        data: dict[str, Any] = yaml.safe_load(path.read_text())
        return cls.model_validate(data)


def load(path: Path) -> Resume:
    """Load and validate. A malformed resume is a hard failure, not a warning."""
    if not path.is_file():
        raise FileNotFoundError(f"no resume at {path}")
    return Resume.from_yaml(path)
