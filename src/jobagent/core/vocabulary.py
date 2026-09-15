"""Shared domain vocabulary.

Words that more than one package has to agree on. The seniority ladder is the
first: `matching` puts a posting on it, and the profile in `core` states which
rungs are wanted. Defining it in either of those would make the other import
sideways, and `core` is the layer everything else is allowed to depend on.

Nothing here does I/O or holds logic. If a definition starts wanting either, it
belongs in the package that uses it, not in this one.
"""

from __future__ import annotations

from enum import StrEnum


class Seniority(StrEnum):
    """One ladder, independent of the source's title inflation.

    A bank calling a new-graduate role "Associate" and a startup calling a
    ten-year role "Engineer II" have to land somewhere comparable, or seniority
    distance means nothing in the score.
    """

    INTERN = "intern"
    JUNIOR = "junior"
    MID = "mid"
    SENIOR = "senior"
    STAFF = "staff"
    LEAD = "lead"
    PRINCIPAL = "principal"
    MANAGER = "manager"
    DIRECTOR = "director"
    EXECUTIVE = "executive"
