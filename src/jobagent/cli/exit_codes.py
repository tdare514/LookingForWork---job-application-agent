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
    """The input is wrong: unknown id or source, bad file, no profile, half a config."""

    USAGE = 2
    """A bad flag or missing argument (Click), or a flag value a command refuses."""

    AGENT_FAILURE = 3
    """The tool tried and could not finish: companion refused, purge left data."""

    NOTHING_TO_DO = 4
    """Command was asked to act and found nothing to act on (reserved for future use)."""
