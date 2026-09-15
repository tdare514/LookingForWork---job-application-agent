"""Canonical normalization for job rows.

De-duplication is only as good as the strings it compares. "Acme, Inc.", "Acme
Inc" and "ACME" are one employer; "TORONTO, Ontario, Canada" and "Toronto, ON"
are one city; and Workday bakes campus-posting noise straight into the title, so
"2027 Winter - GRM, Counterparty Credit Risk Intern (4 Months)" and the same
role reposted next term are the same job wearing a different label.

Everything here is a pure function over strings -- no I/O, no database, stdlib
only. That is deliberate: these are the rules most likely to need tuning against
real postings, and a pure function is the cheapest thing to test.
"""

from __future__ import annotations

import re
import unicodedata
from difflib import SequenceMatcher

# The ladder itself lives in core: the profile states which rungs it wants, and
# core is the layer both packages may depend on. This module owns how a title is
# placed ON the ladder, which is a different job.
from jobagent.core.vocabulary import Seniority

# Employers whose legal name and trading name share no words. A general
# suffix-stripper cannot get these, and they are precisely the companies this
# tool exists to chase, so they are listed rather than inferred.
COMPANY_ALIASES: dict[str, str] = {
    "bank of montreal": "bmo",
    "bmo financial group": "bmo",
    "bmo capital markets": "bmo",
    "royal bank of canada": "rbc",
    "rbc royal bank": "rbc",
    "rbc capital markets": "rbc",
    "toronto dominion": "td",
    "toronto dominion bank": "td",
    "td bank": "td",
    "td bank group": "td",
    "td securities": "td",
    "bank of nova scotia": "scotiabank",
    "scotia bank": "scotiabank",
    "canadian imperial bank of commerce": "cibc",
}

# Legal-form noise. Note what is absent: "bank". Stripping it turned
# "Bank of Montreal" into "of montreal", which matched nothing and was the
# reason the alias table above exists rather than a longer suffix list.
_LEGAL_SUFFIXES = re.compile(
    r"\b(inc|incorporated|ltd|limited|llc|llp|lp|plc|corp|corporation|co|"
    r"company|group|holdings|sa|nv|ag|gmbh)\b"
)

# Workday campus postings carry the term, the length and an encoding artefact in
# the title itself. None of it identifies the role.
_TITLE_NOISE = (
    re.compile(r"\bxmlname\b"),
    re.compile(r"\b(19|20)\d{2}\b"),  # "2027 Winter"
    re.compile(r"\b(winter|summer|spring|fall|autumn)\b"),
    re.compile(r"\(\s*\d+\s*months?\s*\)"),  # "(4 Months)"
    re.compile(r"\b\d+\s*months?\b"),
    re.compile(r"\b(co[- ]?op|internship|placement)\b"),
    re.compile(r"\b(req(uisition)?|job)\s*(id|#)?\s*[:#]?\s*[a-z]?[-_]?\d{3,}\b"),
)

# Province and state tails. A posting's city is the part that decides whether it
# is commutable; the rest is the same city said at more length.
_LOCATION_TAIL = re.compile(
    r",\s*(ontario|on|quebec|qc|british columbia|bc|alberta|ab|manitoba|mb|"
    r"saskatchewan|sk|nova scotia|ns|new brunswick|nb|newfoundland( and labrador)?|nl|"
    r"prince edward island|pe|pei|yukon|yt|northwest territories|nt|nunavut|nu|"
    r"canada|united states|usa|us)\b.*$"
)


# A campus posting says so in its title, and that beats every other signal in
# the list. Banks name divisions after the C-suite -- RBC posts "2027 CFO,
# Winter Financial Analyst", which is a student role in the CFO group, not a
# chief financial officer. Checked first for exactly that reason.
_CAMPUS = re.compile(
    r"\b(intern|internship|co[- ]?op|student|new grad|graduate|campus)\b"
    r"|\b(19|20)\d{2}\b.*\b(winter|summer|spring|fall|autumn)\b"
    r"|\b(winter|summer|spring|fall|autumn)\b.*\b(19|20)\d{2}\b"
)

# Ordered most-specific first: "senior manager" must not read as "senior".
_SENIORITY_PATTERNS: tuple[tuple[re.Pattern[str], Seniority], ...] = (
    (_CAMPUS, Seniority.INTERN),
    (re.compile(r"\b(vp|vice president|chief|c[teifo]o|head of)\b"), Seniority.EXECUTIVE),
    (re.compile(r"\b(director|managing director|md)\b"), Seniority.DIRECTOR),
    (re.compile(r"\b(manager|mgr)\b"), Seniority.MANAGER),
    (re.compile(r"\bprincipal\b"), Seniority.PRINCIPAL),
    (re.compile(r"\b(staff|distinguished)\b"), Seniority.STAFF),
    (re.compile(r"\b(lead|leader)\b"), Seniority.LEAD),
    (re.compile(r"\b(senior|snr|sr|iii|iv)\b"), Seniority.SENIOR),
    (re.compile(r"\b(junior|jr|entry[- ]level|associate|analyst|i{1,2})\b"), Seniority.JUNIOR),
)

# Distance on the ladder, for "no more than one rung outside the target" (#31).
_RUNG: dict[Seniority, int] = {
    Seniority.INTERN: 0,
    Seniority.JUNIOR: 1,
    Seniority.MID: 2,
    Seniority.SENIOR: 3,
    Seniority.STAFF: 4,
    Seniority.LEAD: 4,
    Seniority.PRINCIPAL: 5,
    Seniority.MANAGER: 5,
    Seniority.DIRECTOR: 6,
    Seniority.EXECUTIVE: 7,
}


def _fold(value: str) -> str:
    """Lowercase, strip accents, reduce punctuation to spaces, collapse runs."""
    decomposed = unicodedata.normalize("NFKD", value)
    ascii_only = "".join(c for c in decomposed if not unicodedata.combining(c))
    lowered = ascii_only.lower()
    spaced = re.sub(r"[^a-z0-9]+", " ", lowered)
    return " ".join(spaced.split())


def normalize_company(name: str) -> str:
    """Collapse an employer's names and legal forms onto one key.

    Aliases are applied before suffix stripping, because the suffix stripper
    would otherwise mangle the very names the alias table exists to catch.
    """
    folded = _fold(name)
    # "The Toronto-Dominion Bank" is the legal name on every posting TD writes.
    if folded.startswith("the "):
        folded = folded[4:]
    if not folded:
        return ""
    if folded in COMPANY_ALIASES:
        return COMPANY_ALIASES[folded]
    stripped = " ".join(_LEGAL_SUFFIXES.sub(" ", folded).split())
    # Check again: "BMO Financial Group Inc" only matches once the suffix is off.
    if stripped in COMPANY_ALIASES:
        return COMPANY_ALIASES[stripped]
    # Stripping everything means the name *was* the legal form. Keep the original.
    return stripped or folded


def normalize_title(title: str) -> str:
    """Reduce a title to the part that identifies the role.

    Seniority is deliberately left in. Two postings differing only by "Senior"
    are different jobs, and `same_role` relies on that surviving.
    """
    folded = _fold(title)
    for pattern in _TITLE_NOISE:
        folded = pattern.sub(" ", folded)
    return " ".join(folded.split())


def normalize_location(location: str | None) -> str:
    """City-level only, so two spellings of one city agree.

    Deliberately lossy. "Toronto, ON" and "TORONTO, Ontario, Canada" are the
    same commute; keeping the tail would make them different jobs.
    """
    if not location:
        return ""
    lowered = location.lower().strip()
    # Workday sometimes gives a street address first: "200 BAY ST:TORONTO".
    if ":" in lowered:
        lowered = lowered.rsplit(":", 1)[-1]
    trimmed = _LOCATION_TAIL.sub("", lowered)
    # The city is the LAST segment left, not the first. Workday routinely leads
    # with a building: "7250 Mile End, Montreal, Quebec" is Montreal.
    segments = [seg for seg in trimmed.split(",") if seg.strip()]
    city = segments[-1] if segments else trimmed
    folded = _fold(city)
    # A bare street address normalizes to nothing useful; fall back to the whole
    # string rather than claiming the location is unknown.
    return folded or _fold(location)


def seniority_of(title: str, description: str | None = None) -> tuple[Seniority, bool]:
    """Place a title on the ladder, and say whether the posting actually said so.

    The boolean is the part that matters to the hard filters (#31). MID is the
    fallback for an unmarked title, not a reading of one, and roughly half of
    bank postings are unmarked -- "Analyst, Risk Management" says nothing about
    level. Cutting those for being two rungs from an intern target would empty
    the board on a guess, and a filter that empties the board silently looks
    exactly like a filter that works.

    So the caller gets both: the level to score against, and whether it was read
    or assumed. Scoring may use an assumed level; cutting may not.

    The description is consulted only when the title is silent, which is the
    common case for the bank postings this was tuned against.
    """
    haystack = _fold(title)
    for pattern, level in _SENIORITY_PATTERNS:
        if pattern.search(haystack):
            return level, True
    if description:
        head = _fold(description)[:400]
        for pattern, level in _SENIORITY_PATTERNS:
            if pattern.search(head):
                return level, True
    return Seniority.MID, False


def normalize_seniority(title: str, description: str | None = None) -> Seniority:
    """The level alone, for callers that only need somewhere to put the row.

    `seniority_of` is the one to reach for when the difference between a level
    that was read and one that was assumed changes what you do next.
    """
    level, _matched = seniority_of(title, description)
    return level


def seniority_distance(a: Seniority, b: Seniority) -> int:
    """Rungs apart on the ladder. Used by the hard filters in #31."""
    return abs(_RUNG[a] - _RUNG[b])


def dedupe_key(company: str, title: str, location: str | None) -> str:
    """The coarse identity of a role: normalized company, title and city.

    Deliberately *not* the `jobs.fingerprint` column. That one is UNIQUE and was
    computed from raw strings, so re-deriving it would either collide on rows
    already in the board or force a silent merge of the user's own rows during a
    migration. This key is indexed but not unique, and it is consulted before an
    insert -- so a duplicate is never created, and an existing one is never
    destroyed.
    """
    return f"{normalize_company(company)}|{normalize_title(title)}|{normalize_location(location)}"


# Two titles this similar at the same company and city are one role. Tuned
# against real bank postings: RBC prefixes the department ("GRM, Counterparty
# Credit Risk Intern" vs "Counterparty Credit Risk Intern") which must collapse,
# while "Analyst, Risk" and "Analyst, Credit" must not.
TITLE_SIMILARITY = 0.75
TITLE_SEQUENCE_SIMILARITY = 0.90


def title_similarity(a: str, b: str) -> float:
    """Jaccard overlap of the normalized title's words."""
    tokens_a = set(normalize_title(a).split())
    tokens_b = set(normalize_title(b).split())
    if not tokens_a or not tokens_b:
        return 0.0
    return len(tokens_a & tokens_b) / len(tokens_a | tokens_b)


# Digits and roman numerals in a title are almost always a level, not noise.
# "Analyst I" and "Analyst II" are one character apart and are different jobs.
_LEVEL_TOKENS = frozenset({"i", "ii", "iii", "iv", "v", "vi"})


def _level_markers(title: str) -> set[str]:
    return {
        token
        for token in normalize_title(title).split()
        if token.isdigit() or token in _LEVEL_TOKENS
    }


def same_role(title_a: str, title_b: str) -> bool:
    """Whether two titles at one company and city describe the same job.

    Two independent tests, because they fail on different things. Word overlap
    catches an inserted department prefix; character similarity catches a plural
    or a typo. Either is enough.

    Both are gated on two things string distance cannot see. Seniority must
    match: "Data Scientist" and "Senior Data Scientist" are 0.67 similar by
    words and closer still by characters, and merging them is the mistake #28
    names specifically. Level markers must match too: "Analyst I" and
    "Analyst II" differ by one character and are different jobs.

    Nothing about string distance can tell you either of those. The ladder can.
    """
    if normalize_seniority(title_a) is not normalize_seniority(title_b):
        return False
    if _level_markers(title_a) != _level_markers(title_b):
        return False
    if title_similarity(title_a, title_b) >= TITLE_SIMILARITY:
        return True
    ratio = SequenceMatcher(None, normalize_title(title_a), normalize_title(title_b)).ratio()
    return ratio >= TITLE_SEQUENCE_SIMILARITY
