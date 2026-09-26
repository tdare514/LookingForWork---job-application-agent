"""Exit codes for CLI commands, distinguishing user error from agent failure.

Aligns with the POSIX convention where 0 is success and non-zero is failure,
and adds semantic codes to let scripts and operators branch on the type of failure.
"""

from enum import IntEnum


class ExitCode(IntEnum):
    """CLI exit codes."""

    OK = 0
    """Successful execution."""

    USER_ERROR = 1
    """User-caused failure: bad input, unknown id or source, missing config, bad flag value."""

    USAGE = 2
    """POSIX usage error: Click's code for a bad flag or missing required argument."""

    AGENT_FAILURE = 3
    """Agent failure: a source declined, a truthfulness check failed, a companion error."""

    NOTHING_TO_DO = 4
    """Command was asked to act and found nothing to act on (reserved for future use)."""
