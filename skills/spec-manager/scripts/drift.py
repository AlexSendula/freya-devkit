#!/usr/bin/env python3
"""Declarative-drift checks (governance P4b) — LLM-advisory, resolve-to-proceed.

Does the changed code contradict DECLARATIVE intent (a spec's intentional_decisions
/ purely-declarative prose, or an accepted ADR's decision)? Scoped by
related_code ∩ blast-radius — code-anchored, deliberately NOT always-global
(design 2026-07-01-p4b-declarative-drift-design.md §2). An item with no
related_code is out of drift scope (surfaced only by `gaps`).

- context : the per-change, blast-radius-scoped drift set (git diff → code-graph
            impact → intersect related_code). Deterministic gather; the drift
            JUDGMENT + triage are agent work in wrap-up SKILL.md.
- resolve : append a resolution to drift-resolutions.jsonl.
- prior   : active prior resolutions for an item (recurrence triage).
- gaps    : on-demand — declared items with NO related_code (drift can't see them).

Retirement is append-only: a later `superseded` record (latest-wins per
(item, path)), never a mutated field.

Paths (under --project, default "."):
  knowledge-base/drift-resolutions.jsonl   (append-only)
"""

import argparse
import json
import os
import subprocess
import sys
from datetime import date as _date
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from search_specs import load_all_specs, find_specs_dir  # noqa: E402
from adr import active_adrs  # noqa: E402
import resolution_log  # noqa: E402

_GRAPH_OPS = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                          "..", "..", "code-graph", "scripts", "graph_ops.py")

RESOLUTIONS_RELPATH = "knowledge-base/drift-resolutions.jsonl"
VERDICTS = ("refuted", "amended", "auto-cleared", "superseded")


def _resolutions_path(project):
    return Path(project) / RESOLUTIONS_RELPATH


def append_resolution(project, record):
    return resolution_log.append(_resolutions_path(project), record)


def _load_records(project):
    return resolution_log.load(_resolutions_path(project), RESOLUTIONS_RELPATH)


def active_prior(project, item, paths=None):
    """Latest-active resolution per (item, path) for the given item."""
    records, warnings = _load_records(project)
    want_paths = set(paths) if paths else None
    keys_of = lambda r: [(r.get("item"), p) for p in (r.get("paths") or [])]
    want = lambda k: k[0] == item and (want_paths is None or k[1] in want_paths)
    return resolution_log.active(records, keys_of, want), warnings


def changed_files(project, base):
    """Project-relative files changed in base..HEAD (empty on any git error)."""
    try:
        out = subprocess.run(
            ["git", "-C", project, "diff", f"{base}..HEAD", "--name-only"],
            capture_output=True, text=True, check=True).stdout
    except (subprocess.CalledProcessError, FileNotFoundError):
        return []
    return [ln.strip() for ln in out.splitlines() if ln.strip()]


def compute_impact(project, base):
    """(impact_set, source). Union of changed files + their code-graph dependents;
    degrades to `changed-only` (never a silent empty set) if the graph/tool is
    unavailable or produced no graph result. `empty` when nothing changed.

    `code-graph` means the graph actually ran (the `all_affected` key is present,
    even if it lists no dependents). A missing graph — where graph_ops emits `{}`
    with no `all_affected` key — degrades to `changed-only` so the operator sees
    the blast radius is narrower (direct files only), not falsely complete."""
    changed = changed_files(project, base)
    if not changed:
        return set(), "empty"
    try:
        out = subprocess.run(
            [sys.executable, _GRAPH_OPS, "--impact", *changed,
             "--dir", project, "--format", "json"],
            capture_output=True, text=True, check=True).stdout
        data = json.loads(out)
        if "all_affected" in data:
            return set(data["all_affected"]) | set(changed), "code-graph"
    except (subprocess.CalledProcessError, FileNotFoundError, json.JSONDecodeError):
        pass
    return set(changed), "changed-only"


def _spec_targets(project, impact):
    targets = []
    for s in load_all_specs(find_specs_dir(project)):
        if s.status == "deprecated" or not s.intentional_decisions:
            continue
        hits = [p for p in s.related_code if p in impact]
        if hits:
            targets.append({"item": s.id, "kind": "spec", "related_code": s.related_code,
                            "hit_paths": hits, "decisions": s.intentional_decisions,
                            "file_path": s.file_path})
    return targets


def _adr_targets(project, impact):
    adrs, warnings = active_adrs(project)
    targets = []
    for a in adrs:
        rc = a.get("related_code") or []
        hits = [p for p in rc if p in impact]
        if hits:
            targets.append({"item": a["id"], "kind": "adr", "related_code": rc,
                            "hit_paths": hits, "title": a["title"], "body": a["body"]})
    return targets, warnings


def build_drift_context(project, base, impact=None, source=None):
    """Blast-radius-scoped drift targets: specs' intentional_decisions + accepted
    ADRs whose related_code intersects the change impact. `impact` is injectable
    for testing; when None it is computed from base via compute_impact."""
    if impact is None:
        impact, source = compute_impact(project, base)
    impact = set(impact)
    spec_t = _spec_targets(project, impact)
    adr_t, warnings = _adr_targets(project, impact)
    return {"base": base, "impact_source": source, "impact_count": len(impact),
            "targets": spec_t + adr_t, "warnings": warnings}


def drift_gaps(project):
    """Declared items carrying intent but NO related_code — invisible to the drift
    check (the honesty view; on-demand, not part of wrap-up)."""
    specs = [{"item": s.id, "kind": "spec", "decisions": s.intentional_decisions}
             for s in load_all_specs(find_specs_dir(project))
             if s.status != "deprecated" and s.intentional_decisions and not s.related_code]
    adrs, warnings = active_adrs(project)
    adr_gaps = [{"item": a["id"], "kind": "adr", "title": a["title"]}
                for a in adrs if not (a.get("related_code") or [])]
    return {"specs": specs, "adrs": adr_gaps, "warnings": warnings}


def _cmd_resolve(args):
    record = {"date": args.day or _date.today().isoformat(),
              "item": args.item, "verdict": args.verdict,
              "paths": args.paths, "reason": args.reason}
    if args.commit:
        record["commit"] = args.commit
    print(append_resolution(args.project, record))


def main():
    parser = argparse.ArgumentParser(description="Declarative-drift helpers (P4b)")
    sub = parser.add_subparsers(dest="cmd", required=True)

    c = sub.add_parser("context", help="Blast-radius-scoped drift targets")
    c.add_argument("--project", "-p", default=".")
    c.add_argument("--base", required=True, help="diff base (e.g. $BASE); base..HEAD")
    c.add_argument("--format", "-f", choices=["json"], default="json")

    g = sub.add_parser("gaps", help="Declared items with no related_code (drift-blind)")
    g.add_argument("--project", "-p", default=".")
    g.add_argument("--format", "-f", choices=["json"], default="json")

    r = sub.add_parser("resolve", help="Append a drift resolution record")
    r.add_argument("--project", "-p", default=".")
    r.add_argument("--item", required=True, help="drifted intent: SPEC-NNN or ADR-NNN")
    r.add_argument("--verdict", choices=VERDICTS, required=True)
    r.add_argument("--reason", required=True)
    r.add_argument("--paths", nargs="+", required=True)
    r.add_argument("--commit")
    r.add_argument("--date", dest="day")

    pr = sub.add_parser("prior", help="Active prior resolutions for an item")
    pr.add_argument("--project", "-p", default=".")
    pr.add_argument("--item", required=True)
    pr.add_argument("--paths", nargs="+")
    pr.add_argument("--format", "-f", choices=["json"], default="json")

    args = parser.parse_args()
    if args.cmd == "context":
        print(json.dumps(build_drift_context(args.project, args.base), indent=2))
    elif args.cmd == "gaps":
        print(json.dumps(drift_gaps(args.project), indent=2))
    elif args.cmd == "resolve":
        _cmd_resolve(args)
    elif args.cmd == "prior":
        recs, warns = active_prior(args.project, args.item, paths=args.paths)
        for w in warns:
            print(w, file=sys.stderr)
        print(json.dumps(recs, indent=2))


if __name__ == "__main__":
    main()
