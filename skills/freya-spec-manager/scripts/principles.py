#!/usr/bin/env python3
"""
Principle enforcement helpers (governance G2).

- `list`   : print the project's principles (soft injection + checkpoint input).
- `resolve`: append a resolution record to principle-resolutions.jsonl.
- `prior`  : return the active prior resolutions touching given files (recurrence
             handling — the wrap-up agent re-validates these against the current diff).

The checkpoint JUDGMENT (does the diff violate a principle?) and the triage
(auto-clear / retire / escalate) are agent work in wrap-up's SKILL.md; this script
only does the deterministic parse / append / lookup.

Paths (under --project, default "."):
  knowledge-base/principles.md
  knowledge-base/principle-resolutions.jsonl   (append-only)

Retirement is expressed as a LATER `superseded` record (latest-wins per
(principle, path)), never by mutating a field — that keeps the log append-only.
"""

import argparse
import json
import os
import re
import sys
from datetime import date as _date
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import resolution_log  # noqa: E402

PRINCIPLES_RELPATH = "knowledge-base/principles.md"
RESOLUTIONS_RELPATH = "knowledge-base/principle-resolutions.jsonl"
VERDICTS = ("refuted", "amended", "auto-cleared", "superseded")

_ITEM_RE = re.compile(r"^\s*(\d+)\.\s+(.*)$")
_BOLD_RE = re.compile(r"\*\*(.+?)\*\*")


def _principles_path(project):
    return Path(project) / PRINCIPLES_RELPATH


def _resolutions_path(project):
    return Path(project) / RESOLUTIONS_RELPATH


def parse_principles(text):
    """Parse the numbered principles → [{"n":int,"title":str,"text":str}].

    A principle is a top-level numbered item (`1. **Title.** body`); indented
    continuation lines (e.g. `_Why: …_`) fold into `text`. Non-numbered content is
    ignored, so a free-form file yields fewer/no structured items.
    """
    items, cur = [], None
    for line in text.splitlines():
        m = _ITEM_RE.match(line)
        if m:
            if cur:
                items.append(cur)
            body = m.group(2).strip()
            bold = _BOLD_RE.search(body)
            title = bold.group(1).strip().rstrip(".") if bold else body
            cur = {"n": int(m.group(1)), "title": title, "text": body}
        elif cur is not None and line.strip():
            cur["text"] += " " + line.strip()
    if cur:
        items.append(cur)
    return items


def _principles_section(text):
    """Raw text under a `## Principles` heading, or the whole file if absent."""
    lines = text.splitlines()
    for i, ln in enumerate(lines):
        if ln.strip().lower().startswith("## principles"):
            return "\n".join(lines[i + 1:]).strip()
    return text.strip()


def cmd_list(project, fmt):
    path = _principles_path(project)
    if not path.exists():
        return "" if fmt == "text" else "[]"
    text = path.read_text(encoding="utf-8", errors="replace")
    if fmt == "json":
        return json.dumps(parse_principles(text), indent=2)
    return _principles_section(text)


def append_resolution(project, record):
    return resolution_log.append(_resolutions_path(project), record)


def _load_records(project):
    """(records, warnings) — parsed JSONL lines in append order; skips bad lines."""
    return resolution_log.load(_resolutions_path(project), RESOLUTIONS_RELPATH)


def active_prior(project, paths=None, principle=None):
    """Latest-active resolution per (principle, path)."""
    records, warnings = _load_records(project)
    want_paths = set(paths) if paths else None
    keys_of = lambda r: [(r.get("principle"), p) for p in (r.get("paths") or [])]
    want = lambda k: (want_paths is None or k[1] in want_paths) and \
                     (principle is None or k[0] == principle)
    return resolution_log.active(records, keys_of, want), warnings


def _cmd_resolve(args):
    record = {"date": args.day or _date.today().isoformat(),
              "principle": args.principle, "verdict": args.verdict,
              "paths": args.paths, "reason": args.reason}
    if args.ref:
        record["ref"] = args.ref
    if args.commit:
        record["commit"] = args.commit
    print(append_resolution(args.project, record))


def main():
    parser = argparse.ArgumentParser(description="Principle enforcement helpers (G2)")
    sub = parser.add_subparsers(dest="cmd", required=True)

    pl = sub.add_parser("list", help="Print the project's principles")
    pl.add_argument("--project", "-p", default=".")
    pl.add_argument("--format", "-f", choices=["text", "json"], default="text")

    pr = sub.add_parser("resolve", help="Append a resolution record")
    pr.add_argument("--project", "-p", default=".")
    pr.add_argument("--principle", type=int, required=True)
    pr.add_argument("--verdict", choices=VERDICTS, required=True)
    pr.add_argument("--reason", required=True)
    pr.add_argument("--paths", nargs="+", required=True)
    pr.add_argument("--ref")
    pr.add_argument("--commit")
    pr.add_argument("--date", dest="day")

    pp = sub.add_parser("prior", help="Active prior resolutions touching given files")
    pp.add_argument("--project", "-p", default=".")
    pp.add_argument("--paths", nargs="+", required=True)
    pp.add_argument("--principle", type=int)
    pp.add_argument("--format", "-f", choices=["json"], default="json")

    args = parser.parse_args()
    if args.cmd == "list":
        print(cmd_list(args.project, args.format))
    elif args.cmd == "resolve":
        _cmd_resolve(args)
    elif args.cmd == "prior":
        recs, warns = active_prior(args.project, paths=args.paths, principle=args.principle)
        for w in warns:
            print(w, file=sys.stderr)
        print(json.dumps(recs, indent=2))


if __name__ == "__main__":
    main()
