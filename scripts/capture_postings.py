#!/usr/bin/env python3
"""Print board rows as eval-corpus fixtures. Writes nothing.

The ranking corpus (#76) and the extraction corpus (#65) both need real
postings, and real postings need network access to the tenants. A build
container does not have it -- its proxy refuses `rbc.wd3.myworkdayjobs.com`
and every other job board at the CONNECT stage, before a request is ever
made. So the corpus cannot grow from inside one, and no amount of code
changes that.

This is the way round it. On a machine that *does* have network:

    export JOBAGENT_DATA_DIR=/tmp/corpus-capture   # not your real board
    jobagent init
    jobagent fetch workday:rbc --details --limit 50
    python3 scripts/capture_postings.py --new-only

It prints fixture-shaped JSON to stdout. Nothing is written, nothing is
uploaded, and the file it is destined for is only touched when you paste it
there -- which is also when you write the labels, and those have to be read
off the posting text rather than copied from the extractor's output.

**What it will not print.** Only the fields in `BoardRepo.FIXTURE_FIELDS`,
which are employer-published text. Never your notes, the state of a row, why
you skipped it, or when you looked at it. That list lives in the repository
layer next to the query rather than here, because a script can be bypassed and
a data-access method is where the rows actually come from; `tests/test_capture.py`
asserts it cannot widen without someone noticing. These fixtures go into a
public repository, so the narrow path is the point.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from jobagent.core.storage import Storage
from jobagent.tracking.repo import BoardRepo

FIXTURES = Path(__file__).resolve().parents[1] / "tests" / "fixtures" / "postings.json"


def existing_source_ids(path: Path) -> set[str]:
    if not path.is_file():
        return set()
    try:
        return {str(p.get("source_id")) for p in json.loads(path.read_text())}
    except (ValueError, AttributeError):
        return set()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument(
        "--new-only",
        action="store_true",
        help="Skip postings whose source_id is already in tests/fixtures/postings.json.",
    )
    parser.add_argument("--limit", type=int, default=0, help="At most this many postings.")
    args = parser.parse_args(argv)

    with Storage() as store:
        rows = BoardRepo(store).fixture_rows()
    captured = len(rows)

    if args.new_only:
        known = existing_source_ids(FIXTURES)
        rows = [r for r in rows if str(r["source_id"]) not in known]
    if args.limit > 0:
        rows = rows[: args.limit]

    if not rows:
        # Two different problems with two different fixes, so say which. On
        # stderr, because a caller redirecting stdout to a file still needs to
        # see it rather than quietly ending up with an empty capture.
        if captured and args.new_only:
            print(
                f"All {captured} posting(s) on this board are already in "
                f"{FIXTURES.name}. Fetch more, or drop --new-only to print them anyway.",
                file=sys.stderr,
            )
        else:
            print(
                "No postings with descriptions to capture. Run `jobagent fetch "
                "<source> --details` first -- a posting with no text cannot be "
                "labelled, so it is no use to either corpus.",
                file=sys.stderr,
            )
        return 1

    print(json.dumps(rows, indent=2, ensure_ascii=False))
    print(
        f"\n{len(rows)} posting(s) above. Paste into tests/fixtures/postings.json, then "
        f"label each one in ranking_labels.json and labels.json by reading the posting "
        f"text -- not the extractor's output. `test_every_posting_carries_a_label` "
        f"fails until you do, which is the intended nag.",
        file=sys.stderr,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
