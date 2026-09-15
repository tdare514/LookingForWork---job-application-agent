"""Rule-based requirement extraction from posting text (#30).

#30 specifies extraction "through the LLM boundary from #25". That boundary does
not exist and will not: AGENTS.md forbids a metered API in the core loop, and
ADR 0008 records the consequence. So this is rules, or it does not ship.

Rules are a real constraint and it is worth being honest about where they lose.
A model would read "comfortable picking up new languages" as a skill signal;
this will not. What rules give back is that every output is traceable to a line
you can point at, they cost nothing to run over a full ingest, and they do not
change their mind between runs -- which is what makes the evaluation in
`tests/test_extract.py` mean anything.

The section classifier is the part that earns its keep. A posting's requirement
bullets and its *benefit* bullets look identical:

    What do you need to succeed?        What's in it for you?
    Must-have                           - Leaders who support your development
    - Good command of Excel, VBA        - Opportunities to do challenging work

Reading the second list as requirements is the failure mode that makes every
downstream score wrong, so headings are classified explicitly and anything
unrecognised contributes nothing.
"""

from __future__ import annotations

import re
from collections.abc import Iterable
from dataclasses import dataclass, field
from datetime import date, timedelta
from enum import StrEnum

# Bump when a rule changes. Stored with every extraction so a quality change is
# traceable to a rule change -- the acceptance criterion #30 asks for, with a
# ruleset standing in for the prompt version it assumed.
RULESET_VERSION = "rules-2026-09-15.1"


class Section(StrEnum):
    REQUIRED = "required"
    PREFERRED = "preferred"
    IGNORED = "ignored"


# Headings seen across live RBC, BMO and TD postings. Order matters: "nice to
# have" must be tested before "have", and the benefit headings before anything
# generic, because a benefits list is bulleted exactly like a requirements list.
_HEADINGS: tuple[tuple[re.Pattern[str], Section], ...] = (
    (
        re.compile(
            r"^(what'?s in it for you|our total rewards|total rewards|we offer|benefits|"
            r"why (join|work)|about (us|the team|bmo|rbc|td)|who we are|accommodation|"
            r"interview process|training|colleague development|inclusion|diversity|"
            r"our employment opportunities|join our talent community)",
            re.I,
        ),
        Section.IGNORED,
    ),
    (
        re.compile(
            r"^(nice[- ]to[- ]have|nice to have|preferred|assets?|bonus|"
            r"desirable|would be an asset|additional assets)",
            re.I,
        ),
        Section.PREFERRED,
    ),
    (
        re.compile(
            r"^(must[- ]have|must have|required|requirements|qualifications|"
            r"what do you need to succeed|who you are|what you bring|job skills|"
            r"skills|experience|education)",
            re.I,
        ),
        Section.REQUIRED,
    ),
)

# A curated vocabulary rather than open-ended phrase extraction. Scanning for
# known skills is the part rules do well; inventing skill phrases out of prose is
# the part they do badly, and a list of half-sentences is not something you can
# score against a profile.
SKILL_VOCABULARY: dict[str, tuple[str, ...]] = {
    "python": ("python", "pyspark", "pandas"),
    "sql": ("sql", "t-sql", "pl/sql"),
    "excel": ("excel", "vba"),
    "r": (r"\br\b", "rstudio"),
    "sas": ("sas",),
    "tableau": ("tableau",),
    "power bi": ("power bi", "powerbi"),
    "java": (r"\bjava\b",),
    "c++": (r"c\+\+",),
    "matlab": ("matlab",),
    "machine learning": ("machine learning", "deep learning", "neural network"),
    "statistics": ("statistic", "regression", "econometric", "time series"),
    "data visualization": ("data visualisation", "data visualization", "dashboard", "plotly"),
    "git": (r"\bgit\b", "github", "gitlab"),
    "cloud": (r"\baws\b", r"\bazure\b", "google cloud", r"\bgcp\b"),
    "etl": (r"\betl\b", "data pipeline", "data warehouse"),
    "risk management": ("value-at-risk", "var measurement", "credit risk", "market risk"),
    "financial modelling": ("financial model", "valuation", "derivative"),
    "communication": ("communication skill", "written and oral", "interpersonal"),
    "project management": ("project management", "agile", "scrum", "jira"),
}
_COMPILED_SKILLS = {
    name: tuple(re.compile(p if "\\" in p else re.escape(p), re.I) for p in patterns)
    for name, patterns in SKILL_VOCABULARY.items()
}

# "2+ years", "between 5 - 7 years", "0 to 1 year", "Typically 7+ years".
_YEARS = re.compile(
    r"(?:between\s+)?(\d{1,2})\s*(?:\+|\s*(?:-|to)\s*(\d{1,2})\s*\+?)?\s*year", re.I
)

# "$85,500.00 - $185,000.00", "$76,290 - $114,440 USD". TD posts bilingual pay
# lines ("45 700 $/$45,700 - 61 000 $/$61,000 CAD"), so the anchored $ form is
# matched rather than any run of digits.
_MONEY = re.compile(r"\$\s?(\d[\d,]{2,})(?:\.\d{2})?")
_CURRENCY = re.compile(r"\b(CAD|USD|EUR|GBP)\b")
_PAY_CONTEXT = re.compile(r"(salary|pay details|pay range|compensation|base pay|per annum)", re.I)

_DEADLINE_LABEL = re.compile(r"application deadline", re.I)
_DATE = re.compile(
    r"\b(\d{4})-(\d{2})-(\d{2})\b"
    r"|\b(\d{1,2})/(\d{1,2})/(\d{4})\b"
    r"|\b(january|february|march|april|may|june|july|august|september|october|november|"
    r"december)\s+(\d{1,2}),?\s+(\d{4})\b",
    re.I,
)
_MONTH_NAMES = [
    "january",
    "february",
    "march",
    "april",
    "may",
    "june",
    "july",
    "august",
    "september",
    "october",
    "november",
    "december",
]
_MONTHS = {name: number for number, name in enumerate(_MONTH_NAMES, start=1)}

# RBC's postings carry this verbatim under the labelled date, and it moves the
# real last day back by one. Getting this wrong means believing you have until
# the 21st when the form closes on the 20th, which is the single most expensive
# mistake this tool could make.
_DAY_PRIOR = re.compile(r"accepted until.{0,40}day prior to the application deadline", re.I | re.S)

_REMOTE = re.compile(r"\b(fully remote|remote[- ]first|work from home|100% remote)\b", re.I)
_HYBRID = re.compile(r"\b(hybrid)\b", re.I)
_ONSITE = re.compile(r"\b(on[- ]?site|in[- ]office|in the office)\b", re.I)

_SPONSOR_NO = re.compile(
    r"(not (?:able|in a position) to (?:provide|offer) (?:visa )?sponsor|"
    r"no (?:visa )?sponsorship|without (?:the need for )?sponsorship|"
    r"must be (?:legally )?(?:authorized|entitled|eligible) to work)",
    re.I,
)
_SPONSOR_YES = re.compile(
    r"(sponsorship (?:is )?available|will sponsor|visa sponsorship offered)", re.I
)


@dataclass(frozen=True)
class Requirements:
    """What a posting asks for, as far as rules can tell.

    Every field is optional. "Undisclosed" is the common case for compensation
    and the normal case for sponsorship language, and a null here means the
    posting did not say -- never that it said no.
    """

    required_skills: tuple[str, ...] = ()
    preferred_skills: tuple[str, ...] = ()
    required_bullets: tuple[str, ...] = ()
    preferred_bullets: tuple[str, ...] = ()
    min_years: int | None = None
    max_years: int | None = None
    compensation_min: int | None = None
    compensation_max: int | None = None
    currency: str | None = None
    work_arrangement: str | None = None
    sponsorship: str | None = None
    application_deadline: str | None = None
    ruleset_version: str = RULESET_VERSION

    def as_dict(self) -> dict[str, object]:
        return {
            "required_skills": list(self.required_skills),
            "preferred_skills": list(self.preferred_skills),
            "required_bullets": list(self.required_bullets),
            "preferred_bullets": list(self.preferred_bullets),
            "min_years": self.min_years,
            "max_years": self.max_years,
            "compensation_min": self.compensation_min,
            "compensation_max": self.compensation_max,
            "currency": self.currency,
            "work_arrangement": self.work_arrangement,
            "sponsorship": self.sponsorship,
            "application_deadline": self.application_deadline,
            "ruleset_version": self.ruleset_version,
        }

    @classmethod
    def from_dict(cls, payload: dict[str, object]) -> Requirements:
        """Rebuild from what `as_dict` stored, tolerating an older shape.

        Unknown keys are dropped and missing ones keep their defaults, so an
        extraction written by an earlier ruleset still loads rather than
        crashing the scorer. The alternative -- refusing to read it -- would
        make every rule change a migration.
        """

        def strings(key: str) -> tuple[str, ...]:
            value = payload.get(key) or ()
            if isinstance(value, (list, tuple)):
                return tuple(str(item) for item in value)
            return ()

        def number(key: str) -> int | None:
            value = payload.get(key)
            return int(value) if isinstance(value, (int, float)) else None

        def text(key: str) -> str | None:
            value = payload.get(key)
            return str(value) if isinstance(value, str) and value else None

        return cls(
            required_skills=strings("required_skills"),
            preferred_skills=strings("preferred_skills"),
            required_bullets=strings("required_bullets"),
            preferred_bullets=strings("preferred_bullets"),
            min_years=number("min_years"),
            max_years=number("max_years"),
            compensation_min=number("compensation_min"),
            compensation_max=number("compensation_max"),
            currency=text("currency"),
            work_arrangement=text("work_arrangement"),
            sponsorship=text("sponsorship"),
            application_deadline=text("application_deadline"),
            ruleset_version=text("ruleset_version") or RULESET_VERSION,
        )


@dataclass
class _Block:
    section: Section
    bullets: list[str] = field(default_factory=list)


def _classify(line: str) -> Section | None:
    """Whether this line is a heading, and what kind. None means 'not a heading'."""
    stripped = line.strip().rstrip(":?").strip()
    if not stripped or len(stripped) > 60 or stripped.startswith("-"):
        return None
    for pattern, section in _HEADINGS:
        if pattern.match(stripped):
            return section
    return None


def _blocks(text: str) -> list[_Block]:
    """Split the description into heading-led blocks of bullets.

    Anything before the first recognised heading, or under one we do not
    recognise, is IGNORED. That is deliberate: a posting is mostly prose about
    the company, and treating unlabelled bullets as requirements is how a
    benefits list becomes a skill requirement.
    """
    out: list[_Block] = []
    current = _Block(Section.IGNORED)
    orphan_marker = False
    for line in text.splitlines():
        section = _classify(line)
        if section is not None:
            out.append(current)
            current = _Block(section)
            orphan_marker = False
            continue
        stripped = line.strip()
        # Text already stored before `html_to_text` learned to rejoin these.
        if stripped == "-":
            orphan_marker = True
            continue
        if orphan_marker:
            current.bullets.append(stripped)
            orphan_marker = False
        elif stripped.startswith("- "):
            current.bullets.append(stripped[2:].strip())
    out.append(current)
    return out


def _unique(bullets: Iterable[str]) -> tuple[str, ...]:
    """Drop repeats, keeping order.

    TD publishes English and French in one description, so every section appears
    twice and a requirements list comes back at ninety-odd bullets. The repeats
    say nothing the first copy did not.
    """
    seen: set[str] = set()
    out: list[str] = []
    for bullet in bullets:
        key = bullet.strip().lower()
        if key and key not in seen:
            seen.add(key)
            out.append(bullet)
    return tuple(out)


def _skills_in(texts: tuple[str, ...]) -> tuple[str, ...]:
    haystack = "\n".join(texts).lower()
    found = [
        name
        for name, patterns in _COMPILED_SKILLS.items()
        if any(p.search(haystack) for p in patterns)
    ]
    return tuple(sorted(found))


def _years(texts: tuple[str, ...]) -> tuple[int | None, int | None]:
    """The smallest stated requirement wins.

    A posting listing "2+ years" and "5+ years" in different bullets is asking
    for the lower one as a floor; taking the maximum would filter out roles the
    candidate qualifies for.
    """
    lows: list[int] = []
    highs: list[int] = []
    for match in _YEARS.finditer("\n".join(texts)):
        low = int(match.group(1))
        lows.append(low)
        highs.append(int(match.group(2)) if match.group(2) else low)
    if not lows:
        return None, None
    return min(lows), max(highs)


def _compensation(text: str) -> tuple[int | None, int | None, str | None]:
    """A band, only when the line is actually about pay.

    Postings are full of dollar figures that are not salaries -- portfolio
    sizes, budgets, transaction values. Requiring pay context on the line or the
    one above it is what keeps "$2.5 billion portfolio" out of the band.
    """
    lines = text.splitlines()
    for index, line in enumerate(lines):
        context = line
        if index:
            context = lines[index - 1] + "\n" + line
        if not _PAY_CONTEXT.search(context):
            continue
        amounts = [int(m.group(1).replace(",", "")) for m in _MONEY.finditer(line)]
        # Below this, the figure is an hourly rate or a typo, not a band.
        amounts = [a for a in amounts if a >= 1000]
        if not amounts:
            continue
        currency_match = _CURRENCY.search(context)
        currency = currency_match.group(1) if currency_match else None
        return min(amounts), max(amounts), currency
    return None, None, None


def _iso(match: re.Match[str]) -> str | None:
    """Normalize the three date spellings these postings actually use."""
    if match.group(1):
        return f"{match.group(1)}-{match.group(2)}-{match.group(3)}"
    if match.group(4):
        month, day, year = int(match.group(4)), int(match.group(5)), match.group(6)
        return f"{year}-{month:02d}-{day:02d}"
    if match.group(7):
        month = _MONTHS[match.group(7).lower()]
        return f"{match.group(9)}-{month:02d}-{int(match.group(8)):02d}"
    return None


def _deadline(text: str) -> str | None:
    """The last day an application is actually accepted, normalized to ISO.

    Not simply the labelled date. RBC labels "Application Deadline: 2026-09-21"
    and then says applications are accepted "until 11:59 PM on the day prior to
    the application deadline date above" -- so the real last day is the 20th,
    which is also what the same posting says in prose further up. Reporting the
    label unadjusted would hand back a date one day later than the truth.

    BMO states the date under the same label with no such note, and means it.
    """
    lines = text.splitlines()
    for index, line in enumerate(lines):
        if not _DEADLINE_LABEL.search(line):
            continue

        # A date in the same sentence -- "the formal application deadline is
        # September 20, 2026" -- is prose written for the applicant, and it
        # already states the effective day. Nothing to adjust.
        inline = _DATE.search(line)
        if inline is not None:
            iso = _iso(inline)
            if iso is not None:
                return iso

        # A date on its own line under the label is a field, and a field is what
        # the day-prior note is talking about.
        for candidate in lines[index + 1 : index + 3]:
            match = _DATE.search(candidate)
            if match is None:
                continue
            iso = _iso(match)
            if iso is None:
                continue
            if _DAY_PRIOR.search(text):
                return (date.fromisoformat(iso) - timedelta(days=1)).isoformat()
            return iso
    return None


def _work_arrangement(text: str) -> str | None:
    if _REMOTE.search(text):
        return "remote"
    if _HYBRID.search(text):
        return "hybrid"
    if _ONSITE.search(text):
        return "onsite"
    return None


def _sponsorship(text: str) -> str | None:
    if _SPONSOR_NO.search(text):
        return "not_offered"
    if _SPONSOR_YES.search(text):
        return "offered"
    return None


def extract(description: str | None) -> Requirements:
    """Pull structured requirements out of a posting's text.

    Never raises on content. A posting that defeats every rule returns empty
    fields, because #30 requires that one bad posting does not abort a run --
    and an empty extraction is a true statement about what the rules found.
    """
    if not description or not description.strip():
        return Requirements()

    blocks = _blocks(description)
    required = _unique(
        b for block in blocks if block.section is Section.REQUIRED for b in block.bullets
    )
    preferred = _unique(
        b for block in blocks if block.section is Section.PREFERRED for b in block.bullets
    )

    low, high = _years(required or preferred)
    comp_min, comp_max, currency = _compensation(description)

    return Requirements(
        required_skills=_skills_in(required),
        preferred_skills=_skills_in(preferred),
        required_bullets=required,
        preferred_bullets=preferred,
        min_years=low,
        max_years=high,
        compensation_min=comp_min,
        compensation_max=comp_max,
        currency=currency,
        work_arrangement=_work_arrangement(description),
        sponsorship=_sponsorship(description),
        application_deadline=_deadline(description),
    )
