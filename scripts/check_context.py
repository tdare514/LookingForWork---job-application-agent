#!/usr/bin/env python3
"""Deterministic context check.

Docs rot silently. This catches the mechanical half of that -- a missing file, a
broken link, an ADR absent from its index, a STATUS.md nobody has touched in a
fortnight -- so review attention can go to the half that needs judgement.

Run locally (``python3 scripts/check_context.py``) and in CI. No dependencies.
Exit 0 clean, 1 on any error. Warnings never fail the run.
"""

from __future__ import annotations

import datetime as dt
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

ERRORS: list[str] = []
WARNINGS: list[str] = []

# Files that must exist, because AGENTS.md's ownership table points at them.
REQUIRED = [
    "README.md",
    "AGENTS.md",
    "CLAUDE.md",
    "STATUS.md",
    "CONTRIBUTING.md",
    "ROADMAP.md",
    "docs/architecture.md",
    "docs/security-privacy.md",
    "docs/adr/README.md",
]

# Agent instruction files get read into every session; keep them cheap.
SIZE_LIMITS = {"AGENTS.md": 200, "CLAUDE.md": 30, "STATUS.md": 60}

STATUS_STALE_DAYS = 14

SECRET_FILENAMES = re.compile(r"(^|/)(\.env(\..+)?|.*\.pem|.*\.key|.*\.p12)$")
DATA_ARTEFACTS = re.compile(r"\.(db|sqlite3?|pdf|docx)$")

# Credential shapes. Deliberately narrow: a noisy check gets disabled.
SECRET_CONTENT = re.compile(
    r"(sk-[A-Za-z0-9]{16,}|ghp_[A-Za-z0-9]{20,}|AKIA[0-9A-Z]{16}"
    r"|-----BEGIN [A-Z ]*PRIVATE KEY-----)"
)


def fail(msg: str) -> None:
    ERRORS.append(msg)


def warn(msg: str) -> None:
    WARNINGS.append(msg)


def tracked_files() -> list[str]:
    out = subprocess.run(
        ["git", "ls-files"], cwd=ROOT, capture_output=True, text=True, check=True
    )
    return [line for line in out.stdout.splitlines() if line]


def check_required_files() -> None:
    for rel in REQUIRED:
        if not (ROOT / rel).is_file():
            fail(f"required file missing: {rel}")


def check_claude_imports_agents() -> None:
    """CLAUDE.md must import the shared briefing, or the two drift apart."""
    path = ROOT / "CLAUDE.md"
    if not path.is_file():
        return
    head = path.read_text().splitlines()[:5]
    if not any(line.strip() == "@AGENTS.md" for line in head):
        fail("CLAUDE.md must start with '@AGENTS.md' so the shared briefing loads")


def check_sizes() -> None:
    for rel, limit in SIZE_LIMITS.items():
        path = ROOT / rel
        if not path.is_file():
            continue
        lines = len(path.read_text().splitlines())
        if lines > limit:
            fail(f"{rel} is {lines} lines, limit {limit} -- move detail into a linked doc")


def check_status_freshness() -> None:
    path = ROOT / "STATUS.md"
    if not path.is_file():
        return
    match = re.search(r"Last updated:\s*(\d{4}-\d{2}-\d{2})", path.read_text())
    if match is None:
        fail("STATUS.md has no 'Last updated: YYYY-MM-DD' line")
        return
    updated = dt.date.fromisoformat(match.group(1))
    age = (dt.date.today() - updated).days
    if age > STATUS_STALE_DAYS:
        warn(f"STATUS.md was last updated {age} days ago -- is it still true?")
    if age < 0:
        fail(f"STATUS.md is dated {updated}, in the future")


def check_markdown_links(md_files: list[str]) -> None:
    """Relative links must resolve. Catches renames that silently break docs."""
    link = re.compile(r"\[[^\]]*\]\(([^)]+)\)")
    for rel in md_files:
        path = ROOT / rel
        for target in link.findall(path.read_text()):
            target = target.split("#", 1)[0].strip()
            if not target or target.startswith(("http://", "https://", "mailto:", "<")):
                continue
            if (path.parent / target).exists() or (ROOT / target.lstrip("/")).exists():
                continue
            fail(f"{rel}: broken relative link -> {target}")


def check_adrs() -> None:
    """Every ADR appears in the index, and every indexed ADR exists."""
    adr_dir = ROOT / "docs" / "adr"
    index = adr_dir / "README.md"
    if not index.is_file():
        return
    index_text = index.read_text()
    on_disk = {p.name for p in adr_dir.glob("[0-9][0-9][0-9][0-9]-*.md")}
    for name in sorted(on_disk):
        if name not in index_text:
            fail(f"ADR not listed in docs/adr/README.md: {name}")
    for linked in re.findall(r"\(([0-9]{4}-[^)]+\.md)\)", index_text):
        if linked not in on_disk:
            fail(f"docs/adr/README.md links a missing ADR: {linked}")
    for name in sorted(on_disk):
        head = (adr_dir / name).read_text().splitlines()[:8]
        if not any(re.search(r"\*\*Status:\*\*", line) for line in head):
            fail(f"{name} has no '**Status:**' line in its first 8 lines")


def check_no_secrets(files: list[str]) -> None:
    """The repository is public. Nothing personal or credential-shaped is tracked."""
    for rel in files:
        if SECRET_FILENAMES.search(rel) and not rel.endswith(".example"):
            fail(f"secret-shaped file is tracked: {rel}")
        if DATA_ARTEFACTS.search(rel):
            fail(f"generated data artefact is tracked: {rel}")
        if rel.startswith("data/"):
            fail(f"data directory content is tracked: {rel}")

    for rel in files:
        path = ROOT / rel
        if not path.is_file() or path.stat().st_size > 512_000:
            continue
        try:
            text = path.read_text()
        except (UnicodeDecodeError, OSError):
            continue
        if rel == "scripts/check_context.py":
            continue  # the patterns themselves live here
        if SECRET_CONTENT.search(text):
            fail(f"credential-shaped string in {rel}")


def check_pii_registry_is_code() -> None:
    """The PII inventory is code, not prose -- it is what makes purge verifiable."""
    registry = ROOT / "src" / "jobagent" / "core" / "pii.py"
    if not registry.is_file():
        fail("src/jobagent/core/pii.py is missing -- the PII registry is a hard requirement")


def main() -> int:
    files = tracked_files()
    md_files = [f for f in files if f.endswith(".md")]

    check_required_files()
    check_claude_imports_agents()
    check_sizes()
    check_status_freshness()
    check_markdown_links(md_files)
    check_adrs()
    check_no_secrets(files)
    check_pii_registry_is_code()

    for msg in WARNINGS:
        print(f"warning: {msg}")
    for msg in ERRORS:
        print(f"error: {msg}")

    if ERRORS:
        print(f"\ncontext check FAILED ({len(ERRORS)} error(s))")
        return 1
    print(f"context check passed ({len(files)} tracked files, {len(WARNINGS)} warning(s))")
    return 0


if __name__ == "__main__":
    sys.exit(main())
