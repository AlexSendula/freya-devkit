#!/usr/bin/env python3
"""
behavior-graph — owns behavior.json (the generated BEHAVIOR → TEST → CODE
projection). Builds it by projecting spec frontmatter, orchestrating
behavior-runner for fingerprints, and merging by trust; serves Direction A
(code change → affected behaviors) and Direction B (behavior → code).

Pure graph layer: it queries code-graph and behavior-runner (sibling skills);
code-graph stays unaware of behaviors (vision §5b).
"""
import argparse
import json
import os
import subprocess
import sys
from pathlib import Path

# Reuse the spec-manager frontmatter parser (stdlib-only).
_SPEC_SCRIPTS = Path(__file__).resolve().parents[2] / "spec-manager" / "scripts"
sys.path.insert(0, str(_SPEC_SCRIPTS))
import frontmatter  # noqa: E402
from frontmatter import FrontmatterError  # noqa: E402

_RUNNER = Path(__file__).resolve().parents[2] / "behavior-runner" / "scripts" / "run_behaviors.py"
_CODE_GRAPH = Path(__file__).resolve().parents[2] / "code-graph" / "scripts" / "graph_ops.py"

_RUNNER_SCRIPTS = Path(__file__).resolve().parents[2] / "behavior-runner" / "scripts"
sys.path.insert(0, str(_RUNNER_SCRIPTS))
import run_behaviors  # noqa: E402  (reused for load_behaviors — reads proposed from specs)

_PROJECTED_FIELDS = ("state", "level", "adapter", "locator")


def merge_fingerprint(prior, incoming):
    """Merge a prior coverage-part with an incoming runner fingerprint by trust.

    observed > static; a test-failed run invalidates; any other unknown reason
    preserves the prior fingerprint. Coverage-parts are {coverage, exercises, reason?}.
    """
    cov = incoming.get("coverage")
    if cov == "observed":
        return {"coverage": "observed", "exercises": list(incoming.get("exercises", []))}
    if cov == "static":
        if prior and prior.get("coverage") == "observed":
            return {"coverage": "observed", "exercises": list(prior.get("exercises", []))}
        return {"coverage": "static", "exercises": list(incoming.get("exercises", []))}
    # unknown
    if incoming.get("reason") == "test-failed":
        return {"coverage": "unknown", "exercises": [], "reason": "test-failed"}
    if prior:
        part = {"coverage": prior.get("coverage", "unknown"), "exercises": list(prior.get("exercises", []))}
        if "reason" in prior:
            part["reason"] = prior["reason"]
        return part
    out = {"coverage": "unknown", "exercises": []}
    if incoming.get("reason") is not None:
        out["reason"] = incoming["reason"]
    return out


def project_behaviors(specs_dir):
    """Map BEH-NNN -> projected frontmatter fields for every accepted or
    confirmed behavior (proposed is excluded)."""
    out = {}
    for root, _dirs, files in os.walk(specs_dir):
        for name in files:
            if not name.endswith(".md"):
                continue
            try:
                with open(os.path.join(root, name), encoding="utf-8") as f:
                    fm, _body = frontmatter.parse_frontmatter(f.read())
            except FrontmatterError:
                continue
            for b in fm.get("behaviors") or []:
                # accepted (authoritative) + confirmed (advisory, test owed) both
                # belong in the graph so Direction A/B can see them; proposed does
                # not (it is not confirmed intent). confirmed never gates because
                # the runner never executes it (design 03 §3).
                if not isinstance(b, dict) or b.get("state") not in ("accepted", "confirmed"):
                    continue
                bid = b.get("behavior_id")
                if not bid:
                    continue
                rec = {"spec_id": fm.get("id")}
                for key in _PROJECTED_FIELDS:
                    rec[key] = b.get(key)
                out[bid] = rec
    return out


def _behavior_json_path(project_dir):
    return os.path.join(project_dir, "knowledge-base", ".graph", "behavior.json")


def load_behavior_json(project_dir):
    path = _behavior_json_path(project_dir)
    if not os.path.exists(path):
        return {}
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except (json.JSONDecodeError, OSError):
        return {}


def write_behavior_json(project_dir, data):
    path = _behavior_json_path(project_dir)
    graph_dir = os.path.dirname(path)
    os.makedirs(graph_dir, exist_ok=True)
    gitignore = os.path.join(graph_dir, ".gitignore")
    if not os.path.exists(gitignore):
        with open(gitignore, "w", encoding="utf-8") as f:
            f.write("*\n")
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2)


def _run_behavior_runner(project_dir, only=None):
    argv = [sys.executable, str(_RUNNER), "--project", project_dir,
            "--states", "accepted", "confirmed", "--emit-fingerprints"]
    if only:
        argv += ["--only", *only]
    out = subprocess.run(argv, capture_output=True, text=True, check=True)
    return json.loads(out.stdout)


def build(project_dir):
    """Project specs + run behaviors + merge by trust → write & return behavior.json."""
    specs_dir = os.path.join(project_dir, "knowledge-base", "specs")
    projected = project_behaviors(specs_dir)
    runner = _run_behavior_runner(project_dir)
    fingerprints = runner.get("fingerprints", {})
    prior = load_behavior_json(project_dir).get("behaviors", {})

    behaviors = {}
    for bid, fields in projected.items():
        incoming = fingerprints.get(bid, {"coverage": "unknown", "exercises": [], "reason": "not-run"})
        prior_part = prior.get(bid)
        merged = merge_fingerprint(prior_part, incoming)
        behaviors[bid] = {**fields, **merged}

    data = {"version": 1, "commit": runner.get("commit", "unknown"), "behaviors": behaviors}
    write_behavior_json(project_dir, data)
    return data


def direction_b(behaviors, beh_id):
    """Direction B: the code a behavior exercises (implementing files)."""
    entry = behaviors.get(beh_id)
    if not entry:
        return []
    return sorted(e["path"] for e in entry.get("exercises", []))


def _code_graph_impact(changed_files, project_dir):
    """Blast-radius set for changed files: the inputs plus direct+transitive dependents."""
    impact = set(changed_files)
    if not changed_files:
        return impact
    try:
        out = subprocess.run(
            [sys.executable, str(_CODE_GRAPH), "--impact", *changed_files,
             "--dir", project_dir, "--format", "json"],
            capture_output=True, text=True, check=True,
        )
        data = json.loads(out.stdout)
        for key in ("input_files", "direct_dependents", "transitive_dependents"):
            impact.update(data.get(key, []))
    except (subprocess.CalledProcessError, json.JSONDecodeError, FileNotFoundError, OSError):
        pass
    return impact


def _affected_from_impact(behaviors, impact):
    """BEH ids in the projected graph whose exercised code intersects `impact`."""
    affected = []
    for bid, entry in behaviors.items():
        paths = {e["path"] for e in entry.get("exercises", [])}
        if paths & impact:
            affected.append(bid)
    return sorted(affected)


def direction_a(behaviors, changed_files, project_dir):
    """Direction A: projected behaviors whose exercised code intersects the blast radius."""
    return _affected_from_impact(behaviors, _code_graph_impact(changed_files, project_dir))


def _graph_files(project_dir):
    """Project-relative source files code-graph tracks (graph.json keys); empty if absent."""
    path = os.path.join(project_dir, "knowledge-base", ".graph", "graph.json")
    if not os.path.exists(path):
        return set()
    try:
        with open(path, encoding="utf-8") as f:
            return set(json.load(f).get("files", {}).keys())
    except (json.JSONDecodeError, OSError):
        return set()


def _covered(behaviors, specs_behaviors):
    """Project-relative files any behavior covers: graph `exercises` paths ∪ declared
    `entry` values. Shared by surface (recall gaps) and gaps (whole-repo audit)."""
    covered = set()
    for rec in behaviors.values():
        for e in rec.get("exercises", []):
            covered.add(e["path"])
    for b in specs_behaviors:
        if b.get("entry"):
            covered.add(b["entry"])
    return covered


def surface(project_dir, base):
    """Validate-on-hit surface for base..HEAD (read-only, advisory).

    Returns three buckets:
      - affected_accepted: accepted behaviors the change touches (context only; the
        accepted-behavior gate lives in the separate --check step, not here).
      - validate_candidates: affected proposed + confirmed behaviors to confirm on hit.
      - recall_gaps: changed source files covered by no behavior.

    A proposed/confirmed behavior is "affected" iff its `entry` is in the change's
    impact set. impact = changed ∪ transitive dependents, and the entry depends on
    its whole closure, so `entry ∈ impact` is equivalent to closure(entry) ∩ impact
    ≠ ∅ — the precise match, without recomputing closures.
    """
    specs_dir = os.path.join(project_dir, "knowledge-base", "specs")
    changed = _changed_files(base, project_dir)
    result = {
        "version": 1, "base": base, "changed": changed,
        "affected_accepted": [], "validate_candidates": [], "recall_gaps": [],
    }
    graph_files = _graph_files(project_dir)
    if not graph_files:
        result["note"] = ("no code-graph at knowledge-base/.graph/graph.json — "
                          "run code-graph build; surfacing skipped")
        return result
    if not changed:
        result["note"] = "no changed files in base..HEAD"
        return result

    impact = _code_graph_impact(changed, project_dir)
    behaviors = load_behavior_json(project_dir).get("behaviors", {})

    affected = _affected_from_impact(behaviors, impact)
    result["affected_accepted"] = [b for b in affected
                                   if behaviors[b].get("state") == "accepted"]
    confirmed_hit = [b for b in affected if behaviors[b].get("state") == "confirmed"]

    # Proposed live in specs (not the projected graph); load all states once so we
    # can both surface proposed candidates and collect declared entries for recall.
    specs_behaviors = run_behaviors.load_behaviors(
        specs_dir, states=("proposed", "confirmed", "accepted"))
    by_id = {b.get("behavior_id"): b for b in specs_behaviors}

    candidates = []
    for bid in confirmed_hit:
        src = by_id.get(bid, {})
        candidates.append({
            "behavior_id": bid, "state": "confirmed",
            "spec_id": src.get("spec_id"), "title": src.get("title"),
            "entry": src.get("entry"), "spec_path": src.get("spec_path"),
        })
    for b in specs_behaviors:
        if b.get("state") != "proposed":
            continue
        entry = b.get("entry")
        if entry and entry in impact:
            candidates.append({
                "behavior_id": b.get("behavior_id"), "state": "proposed",
                "spec_id": b.get("spec_id"), "title": b.get("title"),
                "entry": entry, "spec_path": b.get("spec_path"),
            })
    result["validate_candidates"] = sorted(candidates, key=lambda c: c.get("behavior_id") or "")

    covered = _covered(behaviors, specs_behaviors)
    result["recall_gaps"] = sorted(f for f in changed if f in graph_files and f not in covered)
    return result


def gaps(project_dir):
    """Whole-repo uncovered audit: graph source files no behavior covers (read-only)."""
    specs_dir = os.path.join(project_dir, "knowledge-base", "specs")
    result = {"version": 1, "gaps": [], "total": 0}
    graph_files = _graph_files(project_dir)
    if not graph_files:
        result["note"] = ("no code-graph at knowledge-base/.graph/graph.json — "
                          "run code-graph build")
        return result
    behaviors = load_behavior_json(project_dir).get("behaviors", {})
    specs_behaviors = run_behaviors.load_behaviors(
        specs_dir, states=("proposed", "confirmed", "accepted"))
    covered = _covered(behaviors, specs_behaviors)
    uncovered = sorted(f for f in graph_files if f not in covered)
    result["gaps"] = uncovered
    result["total"] = len(uncovered)
    return result


def covering(project_dir, file):
    """Accepted behaviors whose `exercises` include `file` (read-only).

    Only `accepted` (test-verified) behaviors are returned — they are the
    strongest "intentional" evidence for the security cross-reference (SP5).
    Empty `covering` (file echoed) when there is no graph or none cover it.
    """
    behaviors = load_behavior_json(project_dir).get("behaviors", {})
    out = []
    for bid, rec in behaviors.items():
        if rec.get("state") != "accepted":
            continue
        paths = {e["path"] for e in rec.get("exercises", [])}
        if file in paths:
            out.append({"behavior_id": bid, "spec_id": rec.get("spec_id"),
                        "coverage": rec.get("coverage")})
    out.sort(key=lambda c: c["behavior_id"])
    return {"version": 1, "file": file, "covering": out}


def _changed_files(base, project_dir):
    """Project-relative files changed in base..HEAD (empty on git error)."""
    try:
        out = subprocess.run(
            ["git", "-C", project_dir, "diff", "--name-only", f"{base}..HEAD"],
            capture_output=True, text=True, check=True,
        )
        return [ln.strip() for ln in out.stdout.splitlines() if ln.strip()]
    except (subprocess.CalledProcessError, FileNotFoundError, OSError):
        return []


def regression_check(project_dir, base):
    """Direction-A regression check: re-run only the accepted behaviors a change
    touches; block (exit 1) if any is test-failed. Returns (report, exit_code)."""
    data = load_behavior_json(project_dir)
    behaviors = data.get("behaviors", {})
    changed = _changed_files(base, project_dir)
    affected = direction_a(behaviors, changed, project_dir)
    if not affected:
        return {"affected": [], "failed": [], "changed": changed}, 0

    runner = _run_behavior_runner(project_dir, only=affected)
    fingerprints = runner.get("fingerprints", {})
    failed = []
    for bid in affected:
        incoming = fingerprints.get(bid, {"coverage": "unknown", "exercises": [], "reason": "not-run"})
        prior_part = behaviors.get(bid)
        merged = merge_fingerprint(prior_part, incoming)
        fields = {k: v for k, v in behaviors[bid].items()
                  if k not in ("coverage", "exercises", "reason")}
        behaviors[bid] = {**fields, **merged}
        # Guard: only `accepted` behaviors can gate the regression check.
        # Non-accepted states (confirmed, proposed) are advisory by construction.
        # The runner contract is the first line of defense (it never emits test-failed
        # for confirmed), but this check enforces the invariant locally so that future
        # SP2/SP3 executable paths cannot accidentally gate on a non-accepted behavior.
        if (behaviors[bid].get("state") == "accepted"
                and incoming.get("coverage") == "unknown"
                and incoming.get("reason") == "test-failed"):
            failed.append(bid)

    data["behaviors"] = behaviors
    data["commit"] = runner.get("commit", data.get("commit", "unknown"))
    write_behavior_json(project_dir, data)
    return {"affected": affected, "failed": failed, "changed": changed}, (1 if failed else 0)


def main():
    parser = argparse.ArgumentParser(description="Build and query the behavior graph.")
    parser.add_argument("--project", required=True, help="Project root directory.")
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--build", action="store_true", help="Build/refresh behavior.json.")
    group.add_argument("--affected", nargs="+", metavar="FILE",
                       help="Direction A: behaviors affected by these changed files.")
    group.add_argument("--implements", metavar="BEH",
                       help="Direction B: code a behavior exercises.")
    group.add_argument("--check", action="store_true",
                       help="Direction-A regression check (re-run affected accepted behaviors).")
    group.add_argument("--surface", action="store_true",
                       help="Validate-on-hit surface (affected proposed/confirmed + recall gaps) for base..HEAD.")
    group.add_argument("--gaps", action="store_true",
                       help="Whole-repo uncovered-code audit (source files no behavior covers).")
    group.add_argument("--covering", metavar="FILE",
                       help="Accepted behaviors whose exercised code includes FILE (security cross-ref).")
    parser.add_argument("--base", help="Base commit for --check (diff base..HEAD).")
    args = parser.parse_args()

    if args.covering:
        print(json.dumps(covering(args.project, args.covering), indent=2))
        return 0

    if args.gaps:
        print(json.dumps(gaps(args.project), indent=2))
        return 0

    if args.surface:
        if not args.base:
            parser.error("--surface requires --base COMMIT")
        print(json.dumps(surface(args.project, args.base), indent=2))
        return 0

    if args.check:
        if not args.base:
            parser.error("--check requires --base COMMIT")
        report, code = regression_check(args.project, args.base)
        print(json.dumps(report, indent=2))
        return code

    if args.build:
        data = build(args.project)
        print(json.dumps(data, indent=2))
        return 0

    behaviors = load_behavior_json(args.project).get("behaviors", {})
    if args.affected:
        print(json.dumps({"affected": direction_a(behaviors, args.affected, args.project)}, indent=2))
    else:
        print(json.dumps({"implements": direction_b(behaviors, args.implements)}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
