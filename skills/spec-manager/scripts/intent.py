#!/usr/bin/env python3
"""Authoring helper for declared-intent (INTENT-NNN) records (governance G1).

`intent new` allocates the next INTENT id and writes a block-style record naming
the behaviors whose accepted test is being changed. The gate (verify_intent.py)
then recognizes the new record as authorizing the change. Block-style lists only
— the hand-rolled frontmatter parser discards inline arrays.
"""

import argparse
import re
import sys
from datetime import date as _date
from pathlib import Path

INTENTS_RELDIR = "knowledge-base/intents"
_BEH_RE = re.compile(r"^BEH-\d+$")
_ID_RE = re.compile(r"INTENT-(\d+)\.md$")


def _next_id(intents_dir: Path) -> str:
    n = 0
    if intents_dir.exists():
        for f in intents_dir.glob("INTENT-*.md"):
            m = _ID_RE.search(f.name)
            if m:
                n = max(n, int(m.group(1)))
    return f"INTENT-{n + 1:03d}"


def render_record(intent_id, behaviors, approver, rationale, day) -> str:
    beh_lines = "".join(f"  - {b}\n" for b in behaviors)
    return (
        "---\n"
        f"id: {intent_id}\n"
        "behaviors:\n"
        f"{beh_lines}"
        f"approver: {approver}\n"
        f"date: {day}\n"
        "---\n"
        "## Rationale\n"
        f"{rationale}\n"
    )


def new_record(project_dir, behaviors, approver, rationale, day) -> str:
    intents_dir = Path(project_dir) / INTENTS_RELDIR
    intents_dir.mkdir(parents=True, exist_ok=True)
    intent_id = _next_id(intents_dir)
    path = intents_dir / f"{intent_id}.md"
    path.write_text(render_record(intent_id, behaviors, approver, rationale, day),
                    encoding="utf-8")
    return str(path)


def _beh(value):
    if not _BEH_RE.match(value):
        raise argparse.ArgumentTypeError(f"--behavior must be BEH-NNN, got {value!r}")
    return value


def main():
    parser = argparse.ArgumentParser(description="Declared-intent record helper (G1)")
    sub = parser.add_subparsers(dest="cmd", required=True)
    n = sub.add_parser("new", help="Create a new INTENT-NNN record")
    n.add_argument("--behavior", "-b", required=True, action="append", type=_beh,
                   help="BEH-NNN this record authorizes changing (repeatable)")
    n.add_argument("--approver", required=True)
    n.add_argument("--rationale", default="TODO: why this accepted behavior is changing.")
    n.add_argument("--date", dest="day", default=None, help="YYYY-MM-DD (default: today)")
    n.add_argument("--project", "-p", default=".")
    args = parser.parse_args()

    if args.cmd == "new":
        day = args.day or _date.today().isoformat()
        print(new_record(args.project, args.behavior, args.approver, args.rationale, day))


if __name__ == "__main__":
    main()
