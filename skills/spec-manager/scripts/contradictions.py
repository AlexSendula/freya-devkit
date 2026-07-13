#!/usr/bin/env python3
"""
Contradiction checks (governance G3) — deterministic helpers.

- `context`: assemble the higher-authority comparison set for a changed spec
             (principles + same-category peer decisions; the spec itself excluded).
- `resolve`: append a resolution record to contradiction-resolutions.jsonl.
- `prior`  : active prior resolutions for a spec (recurrence handling — the agent
             re-validates these against the current spec text).

The contradiction JUDGMENT (does the changed intent contradict a higher-authority
intent?) and the triage (auto-clear / retire / escalate) are agent work in the
spec-manager / wrap-up SKILL.md; this script only does the deterministic gather /
append / lookup.

ADR-aware (P4a): a changed spec is compared against ALL active ADRs (always-global,
no category scoping — build_context), and a changed ADR against its principles +
peer ADRs (build_adr_context). Retirement is append-only: a later `superseded`
record (latest-wins per (spec, against)), never a mutated field.

Paths (under --project, default "."):
  knowledge-base/principles.md                     (via principles.py)
  knowledge-base/specs/                             (via search_specs)
  knowledge-base/contradiction-resolutions.jsonl    (append-only)
"""

import argparse
import json
import os
import sys
from datetime import date as _date
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from search_specs import load_all_specs, find_specs_dir  # noqa: E402
from principles import parse_principles, PRINCIPLES_RELPATH  # noqa: E402
from adr import active_adrs  # noqa: E402
import resolution_log  # noqa: E402

RESOLUTIONS_RELPATH = "knowledge-base/contradiction-resolutions.jsonl"
VERDICTS = ("refuted", "amended", "auto-cleared", "superseded")


def _resolutions_path(project):
    return Path(project) / RESOLUTIONS_RELPATH


def _load_principles(project):
    path = Path(project) / PRINCIPLES_RELPATH
    if not path.exists():
        return []
    return parse_principles(path.read_text(encoding="utf-8", errors="replace"))


def build_context(project, spec_id):
    """Assemble {spec, category, principles, adrs, peers, adr_warnings} for a
    changed spec. `adrs` = ALL active ADRs (always-global, no scoping — design
    §2). `peers` = same-category specs (excluding self) with intentional_decisions.
    """
    specs = load_all_specs(find_specs_dir(project))
    principles = _load_principles(project)
    adrs, adr_warnings = active_adrs(project)
    adr_ctx = [{"id": a["id"], "title": a["title"], "body": a["body"]} for a in adrs]
    target = next((s for s in specs if s.id == spec_id), None)
    if target is None:
        return {"spec": spec_id, "category": None, "principles": principles,
                "adrs": adr_ctx, "peers": [], "adr_warnings": adr_warnings,
                "note": f"spec {spec_id} not found"}
    peers = [
        {"spec_id": s.id, "decisions": s.intentional_decisions}
        for s in specs
        if s.category == target.category and s.id != spec_id and s.intentional_decisions
    ]
    return {"spec": spec_id, "category": target.category,
            "principles": principles, "adrs": adr_ctx, "peers": peers,
            "adr_warnings": adr_warnings}


def build_adr_context(project, adr_id):
    """Assemble {adr, principles, peer_adrs, adr_warnings, [note]} for a CHANGED ADR.

    A changed ADR is judged against the principles above it (authority:
    principle > ADR) and its peer ADRs at the same tier (reconcile). `peer_adrs`
    excludes the changed ADR. Returns a `note` if the ADR isn't found/active.
    """
    adrs, adr_warnings = active_adrs(project)
    principles = _load_principles(project)
    target = next((a for a in adrs if a["id"] == adr_id), None)
    if target is None:
        return {"adr": adr_id, "principles": principles, "peer_adrs": [],
                "adr_warnings": adr_warnings,
                "note": f"ADR {adr_id} not found or not accepted"}
    peers = [{"id": a["id"], "title": a["title"], "body": a["body"]}
             for a in adrs if a["id"] != adr_id]
    return {"adr": {"id": target["id"], "title": target["title"],
                    "body": target["body"]},
            "principles": principles, "peer_adrs": peers,
            "adr_warnings": adr_warnings}


def append_resolution(project, record):
    return resolution_log.append(_resolutions_path(project), record)


def _load_records(project):
    return resolution_log.load(_resolutions_path(project), RESOLUTIONS_RELPATH)


def active_prior(project, spec, against=None):
    """Latest-active resolution per (spec, against) for the given spec."""
    records, warnings = _load_records(project)
    keys_of = lambda r: [(r.get("spec"), r.get("against"))]
    want = lambda k: k[0] == spec and (against is None or k[1] == against)
    return resolution_log.active(records, keys_of, want), warnings


def _cmd_resolve(args):
    record = {"date": args.day or _date.today().isoformat(),
              "spec": args.spec, "against": args.against,
              "verdict": args.verdict, "reason": args.reason}
    if args.commit:
        record["commit"] = args.commit
    print(append_resolution(args.project, record))


def main():
    parser = argparse.ArgumentParser(description="Contradiction-check helpers (G3)")
    sub = parser.add_subparsers(dest="cmd", required=True)

    c = sub.add_parser("context", help="Assemble the comparison set for a spec")
    c.add_argument("--project", "-p", default=".")
    c.add_argument("--spec", required=True)

    ac = sub.add_parser("adr-context", help="Comparison set for a changed ADR")
    ac.add_argument("--project", "-p", default=".")
    ac.add_argument("--adr", required=True)

    r = sub.add_parser("resolve", help="Append a resolution record")
    r.add_argument("--project", "-p", default=".")
    r.add_argument("--spec", required=True, help="changed item: SPEC-NNN or ADR-NNN")
    r.add_argument("--against", required=True,
                   help="conflicting item: principle:N, SPEC-NNN, or ADR-NNN")
    r.add_argument("--verdict", choices=VERDICTS, required=True)
    r.add_argument("--reason", required=True)
    r.add_argument("--commit")
    r.add_argument("--date", dest="day")

    pr = sub.add_parser("prior", help="Active prior resolutions for a spec")
    pr.add_argument("--project", "-p", default=".")
    pr.add_argument("--spec", required=True)
    pr.add_argument("--against")
    pr.add_argument("--format", "-f", choices=["json"], default="json")

    args = parser.parse_args()
    if args.cmd == "context":
        print(json.dumps(build_context(args.project, args.spec), indent=2))
    elif args.cmd == "adr-context":
        print(json.dumps(build_adr_context(args.project, args.adr), indent=2))
    elif args.cmd == "resolve":
        _cmd_resolve(args)
    elif args.cmd == "prior":
        recs, warns = active_prior(args.project, args.spec, against=args.against)
        for w in warns:
            print(w, file=sys.stderr)
        print(json.dumps(recs, indent=2))


if __name__ == "__main__":
    main()
