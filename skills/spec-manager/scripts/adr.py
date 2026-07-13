#!/usr/bin/env python3
"""Authoring + gather + integrity helpers for ADRs (governance P4a).

- `adr new`  : allocate the next ADR-NNN and write a four-section scaffold.
- `load_adrs`/`active_adrs` : gather ADRs for the G3 contradiction check. A
   malformed ADR becomes a SURFACED WARNING, never a silent drop.
- `adr verify` : deterministic Tier-1 integrity (dup id, dangling supersede
   links, bad status/malformed) — hard-blocks at wrap-up.
- `adr list` : print/regenerate the decisions index.

Cross-cutting ADRs are compared ALWAYS-GLOBAL (no category scoping): see
docs/superpowers/specs/2026-07-01-p4a-adr-support-design.md §2. Only lifecycle
filters — `active_adrs` keeps `status == "accepted"`.
"""

import argparse
import json
import os
import re
import sys
from datetime import date as _date
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from frontmatter import (  # noqa: E402
    parse_frontmatter, validate_adr, FrontmatterError, ADR_STATES,
)

DECISIONS_RELDIR = "knowledge-base/decisions"
_ID_RE = re.compile(r"ADR-(\d+)")
_SECTIONS = ("Decision", "Rationale", "Rejected Alternatives", "Revisit Conditions")


def _decisions_dir(project):
    return Path(project) / DECISIONS_RELDIR


def _next_id(decisions_dir: Path) -> str:
    n = 0
    if decisions_dir.exists():
        for f in decisions_dir.glob("ADR-*.md"):
            m = _ID_RE.search(f.name)
            if m:
                n = max(n, int(m.group(1)))
    return f"ADR-{n + 1:03d}"


def _slug(title: str) -> str:
    s = re.sub(r"[^a-z0-9]+", "-", title.lower()).strip("-")
    return s or "decision"


def render_record(adr_id, title, status, day, tags=None, supersedes=None) -> str:
    fm = ["---", f"id: {adr_id}", f"title: {title}", f"status: {status}",
          f"created: {day}", f"updated: {day}"]
    if tags:
        fm.append("tags:")
        fm += [f"  - {t}" for t in tags]
    if supersedes:
        fm.append(f"supersedes: {supersedes}")
    fm.append("---")
    body = [f"# {adr_id}: {title}"]
    for sec in _SECTIONS:
        body.append(f"## {sec}")
        body.append(f"TODO: {sec.lower()}.")
    return "\n".join(fm) + "\n" + "\n".join(body) + "\n"


def new_record(project, title, status, day, tags=None, supersedes=None) -> str:
    ddir = _decisions_dir(project)
    ddir.mkdir(parents=True, exist_ok=True)
    adr_id = _next_id(ddir)
    path = ddir / f"{adr_id}-{_slug(title)}.md"
    path.write_text(render_record(adr_id, title, status, day, tags, supersedes),
                    encoding="utf-8")
    return str(path)


def load_adrs(project):
    """Return (adrs, warnings). Each adr is a dict with id/title/status/tags/
    related_code/supersedes/superseded_by/body/path. A malformed ADR is a
    surfaced warning and excluded — never a SILENT drop (design §2, §7)."""
    ddir = _decisions_dir(project)
    adrs, warnings = [], []
    if not ddir.exists():
        return adrs, warnings
    for f in sorted(ddir.glob("ADR-*.md")):
        try:
            fm, body = parse_frontmatter(
                f.read_text(encoding="utf-8", errors="replace"))
        except FrontmatterError as e:
            warnings.append(f"unparseable ADR {f.name}: {e}")
            continue
        errs = validate_adr(fm)
        if errs:
            warnings.append(f"invalid ADR {f.name}: {'; '.join(errs)}")
            continue
        adrs.append({
            "id": fm.get("id"), "title": fm.get("title"), "status": fm.get("status"),
            "tags": fm.get("tags", []), "related_code": fm.get("related_code", []),
            "supersedes": fm.get("supersedes"), "superseded_by": fm.get("superseded_by"),
            "body": body.strip(), "path": str(f),
        })
    return adrs, warnings


def active_adrs(project):
    """(accepted ADRs, warnings) — the authoritative set G3 compares against."""
    adrs, warnings = load_adrs(project)
    return [a for a in adrs if a["status"] == "accepted"], warnings


def verify_adrs(project):
    """Deterministic Tier-1 integrity — (errors); empty == clean. Flags:
    duplicate id, malformed/invalid frontmatter, and a supersedes/superseded_by
    that does not resolve to a known ADR id. Hard-blocks at wrap-up."""
    ddir = _decisions_dir(project)
    errors = []
    if not ddir.exists():
        return errors
    ids, raw = {}, []
    for f in sorted(ddir.glob("ADR-*.md")):
        try:
            fm, _ = parse_frontmatter(
                f.read_text(encoding="utf-8", errors="replace"))
        except FrontmatterError as e:
            errors.append(f"{f.name}: unparseable frontmatter: {e}")
            continue
        for e in validate_adr(fm):
            errors.append(f"{f.name}: {e}")
        aid = fm.get("id")
        if aid:
            if aid in ids:
                errors.append(f"{f.name}: duplicate id {aid} (also in {ids[aid]})")
            else:
                ids[aid] = f.name
        raw.append((f.name, fm))
    known = set(ids)
    for fname, fm in raw:
        for field in ("supersedes", "superseded_by"):
            ref = fm.get(field)
            if ref and ref not in known:
                errors.append(
                    f"{fname}: {field} '{ref}' does not resolve to a known ADR")
    return errors


def render_index(project):
    """Regenerate the decisions index as a markdown table."""
    adrs, _ = load_adrs(project)
    lines = ["# Architecture Decision Records", "",
             "| ID | Title | Status |", "|----|-------|--------|"]
    for a in sorted(adrs, key=lambda x: x["id"] or ""):
        lines.append(f"| {a['id']} | {a['title']} | {a['status']} |")
    return "\n".join(lines) + "\n"


def _status(value):
    if value not in ADR_STATES:
        raise argparse.ArgumentTypeError(
            f"--status must be one of {', '.join(ADR_STATES)}, got {value!r}")
    return value


def main():
    parser = argparse.ArgumentParser(description="ADR helpers (P4a)")
    sub = parser.add_subparsers(dest="cmd", required=True)

    n = sub.add_parser("new", help="Create a new ADR-NNN scaffold")
    n.add_argument("--title", "-t", required=True)
    n.add_argument("--status", default="accepted", type=_status)
    n.add_argument("--tag", action="append", dest="tags")
    n.add_argument("--supersedes")
    n.add_argument("--date", dest="day", default=None)
    n.add_argument("--project", "-p", default=".")

    v = sub.add_parser("verify", help="Deterministic ADR integrity checks")
    v.add_argument("--project", "-p", default=".")

    ls = sub.add_parser("list", help="Print the ADR index")
    ls.add_argument("--project", "-p", default=".")
    ls.add_argument("--format", "-f", choices=["table", "json"], default="table")

    args = parser.parse_args()
    if args.cmd == "new":
        day = args.day or _date.today().isoformat()
        print(new_record(args.project, args.title, args.status, day,
                         args.tags, args.supersedes))
    elif args.cmd == "verify":
        errs = verify_adrs(args.project)
        for e in errs:
            print(e, file=sys.stderr)
        sys.exit(1 if errs else 0)
    elif args.cmd == "list":
        if args.format == "json":
            adrs, _ = load_adrs(args.project)
            print(json.dumps(adrs, indent=2))
        else:
            print(render_index(args.project))


if __name__ == "__main__":
    main()
