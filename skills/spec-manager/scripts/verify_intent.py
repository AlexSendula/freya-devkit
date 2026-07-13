#!/usr/bin/env python3
"""
Tier-1 deterministic declared-intent gate (governance G1).

Editing an `accepted` behavior's linked test is treated as an attempt to change
the intended behavior, and must be authorized by an in-change-set INTENT-NNN
record (knowledge-base/intents/). This check is git-aware and transition-based
(unlike verify_links.py, a stateless snapshot check), so it is a SIBLING script
that shares the same Tier-1 hard-block tier and exit-code convention.

Detection: files changed since the baseline commit ∩ accepted-behavior locators.
A record authorizes only when it is NEW in the change-set (absent at baseline),
which makes it self-scoping — a past record cannot bless a future edit.

Baseline: knowledge-base/intents/.intent-last-verified (G1's OWN marker — it must
NOT reuse .spec-last-update, which wrap-up advances in Phase 3 before this Phase
3.5 check runs). Absent marker => the check skips (fresh repo / full scan).

Exit code is non-zero when an accepted test changed without an authorizing record
(or a record is malformed), so wrap-up can gate on it. Fail-open on git error.

Usage:
    python verify_intent.py --project .
    python verify_intent.py --project . --format json
    python verify_intent.py --project . --advance   # write marker = current HEAD
"""

import argparse
import json
import os
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from search_specs import load_all_specs, find_specs_dir  # noqa: E402
from frontmatter import parse_frontmatter, FrontmatterError  # noqa: E402
from adapters import parse_locator  # noqa: E402

MARKER_RELPATH = "knowledge-base/intents/.intent-last-verified"
INTENTS_RELDIR = "knowledge-base/intents"


def _git(project_dir, *args):
    """Run git in project_dir; return (returncode, stdout). Never raises."""
    try:
        out = subprocess.run(["git", "-C", project_dir, *args],
                             capture_output=True, text=True)
        return out.returncode, out.stdout
    except (FileNotFoundError, OSError):
        return 1, ""


def _read_baseline(project_dir):
    """Commit hash from the marker, or None if absent/unreadable."""
    marker = Path(project_dir) / MARKER_RELPATH
    if not marker.exists():
        return None
    for line in marker.read_text(encoding="utf-8", errors="replace").splitlines():
        line = line.strip()
        if line.startswith("commit:"):
            return line.split(":", 1)[1].strip() or None
    return None


def _changed_status(project_dir, baseline):
    """Map {project-relative path: status} for baseline..working-tree.

    `git diff --name-status -M <baseline>` (one ref) compares the baseline to the
    working tree, so committed changes since baseline AND tracked working-tree
    edits both count. Rename entries record the NEW path with a ('R', similarity)
    tuple; others map to 'M'/'A'/'D'.
    """
    rc, out = _git(project_dir, "diff", "--name-status", "-M", baseline)
    status = {}
    if rc != 0:
        return status
    for line in out.splitlines():
        parts = line.split("\t")
        if len(parts) < 2:
            continue
        code = parts[0]
        if code.startswith("R"):
            sim = int(code[1:] or "0")
            status[parts[-1]] = ("R", sim)
        else:
            status[parts[-1]] = code[0]
    return status


def _is_change(status):
    """Modified or deleted => a change. Added or pure-rename(100%) => not."""
    if status is None:
        return False
    if isinstance(status, tuple):        # rename: changed only if content moved too
        return status[1] < 100
    return status in ("M", "D")


def _record_is_new(project_dir, baseline, relpath):
    """True if `relpath` did not exist at the baseline commit (=> in-change)."""
    rc, _ = _git(project_dir, "cat-file", "-e", f"{baseline}:{relpath}")
    return rc != 0


def _load_records(project_dir, baseline):
    """New-since-baseline INTENT records on disk.

    Filesystem scan (not git diff) so untracked, staged, and committed records
    all count uniformly. Returns (records, errors) where a record is
    {"id","behaviors":[...],"path"}; a malformed record yields an error string.
    """
    records, errors = [], []
    intents_dir = Path(project_dir) / INTENTS_RELDIR
    if not intents_dir.exists():
        return records, errors
    for f in sorted(intents_dir.glob("INTENT-*.md")):
        relpath = os.path.relpath(str(f), project_dir)
        if not _record_is_new(project_dir, baseline, relpath):
            continue  # pre-existing => does not authorize (self-scoping)
        try:
            fm, _body = parse_frontmatter(f.read_text(encoding="utf-8", errors="replace"))
        except FrontmatterError as exc:
            errors.append(f"{f.name}: unparseable frontmatter — {exc}")
            continue
        except Exception as exc:  # noqa: BLE001 — defensive: never crash on a bad record
            errors.append(f"{f.name}: could not read record — {exc}")
            continue
        behaviors = fm.get("behaviors")
        if not isinstance(behaviors, list) or not behaviors:
            errors.append(f"{f.name}: malformed record — missing or empty 'behaviors:' list")
            continue
        records.append({"id": fm.get("id", f.stem), "behaviors": list(behaviors),
                        "path": relpath})
    return records, errors


def verify_intent(project_dir="."):
    project_dir = os.path.abspath(project_dir)
    specs_dir = find_specs_dir(project_dir)
    result = {"version": 1, "baseline": None, "skipped": False,
              "edited_accepted": [], "records_in_change": [],
              "authorized": [], "unauthorized": [], "errors": [], "warnings": []}

    baseline = _read_baseline(project_dir)
    result["baseline"] = baseline
    if not baseline:
        result["skipped"] = True
        result["note"] = "no baseline marker — intent gate skipped (governs transitions only)"
        return result

    status = _changed_status(project_dir, baseline)
    specs = load_all_specs(specs_dir)

    edited = []
    for s in specs:
        for b in s.behaviors:
            if b.get("state") != "accepted":
                continue
            locator = b.get("locator")
            if not locator:
                continue
            rel_path, _frag = parse_locator(locator)
            st = status.get(rel_path)
            if _is_change(st):
                edited.append({"behavior_id": b.get("behavior_id"), "spec_id": s.id,
                               "locator": locator, "path": rel_path,
                               "status": ("R" if isinstance(st, tuple) else st)})
    result["edited_accepted"] = edited

    records, errors = _load_records(project_dir, baseline)
    result["records_in_change"] = records
    result["errors"] = errors

    all_bids = {b.get("behavior_id") for s in specs for b in s.behaviors}
    covered = set()
    for rec in records:
        for bid in rec["behaviors"]:
            covered.add(bid)
            if bid not in all_bids:
                result["warnings"].append(
                    f"{rec['id']} names {bid}, which is not a known behavior")

    for e in edited:
        if e["behavior_id"] in covered:
            result["authorized"].append(e["behavior_id"])
        else:
            result["unauthorized"].append(
                {"behavior_id": e["behavior_id"], "spec_id": e["spec_id"], "path": e["path"]})

    return result


def advance_marker(project_dir):
    """Write the baseline marker = current HEAD. Returns the commit, or None."""
    rc, out = _git(project_dir, "rev-parse", "HEAD")
    if rc != 0 or not out.strip():
        return None
    commit = out.strip()
    marker = Path(project_dir) / MARKER_RELPATH
    marker.parent.mkdir(parents=True, exist_ok=True)
    marker.write_text(f"# Intent gate last-verified\ncommit: {commit}\n", encoding="utf-8")
    return commit


def _blocking(result):
    return bool(result["unauthorized"]) or bool(result["errors"])


def _print_text(result):
    if result["skipped"]:
        print("intent gate: skipped (no baseline marker)")
        return
    if not _blocking(result):
        print("OK — no accepted test changed without an authorizing intent record.")
    else:
        if result["unauthorized"]:
            print(f"{len(result['unauthorized'])} accepted test change(s) without an intent record:\n")
            for u in result["unauthorized"]:
                print(f"  [{u['behavior_id']}] {u['spec_id']}: {u['path']} changed — "
                      f"file knowledge-base/intents/INTENT-NNN.md naming {u['behavior_id']} "
                      f"(intent.py new --behavior {u['behavior_id']}), or revert the test edit.")
        for e in result["errors"]:
            print(f"  [error] {e}")
    for w in result["warnings"]:
        print(f"  [warn] {w}")


def main():
    parser = argparse.ArgumentParser(description="Tier-1 declared-intent gate (G1)")
    parser.add_argument("--project", "-p", default=".", help="Project root (default: .)")
    parser.add_argument("--format", "-f", choices=["text", "json"], default="text")
    parser.add_argument("--advance", action="store_true",
                        help="Write the baseline marker = current HEAD (after a passing wrap-up).")
    args = parser.parse_args()

    if args.advance:
        commit = advance_marker(args.project)
        if commit:
            print(f"intent baseline advanced to {commit[:10]}")
            sys.exit(0)
        print("could not advance marker (git error)", file=sys.stderr)
        sys.exit(1)

    result = verify_intent(args.project)
    if args.format == "json":
        print(json.dumps(result, indent=2))
    else:
        _print_text(result)
    sys.exit(1 if _blocking(result) else 0)


if __name__ == "__main__":
    main()
