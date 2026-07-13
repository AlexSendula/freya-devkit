#!/usr/bin/env python3
"""
behavior-runner — run accepted behaviors via their adapter and emit observed
coverage fingerprints (TEST -> CODE edges). Producer only: it never writes
behavior.json (that is behavior-graph's job).

Phase 2 Plan 2 implements the **unit** level (adapter: vitest, in-process,
runner-native V8 coverage). Other levels are added in later plans.
"""
import argparse
import json
import os
import subprocess
import sys
from pathlib import Path

# Reuse the spec-manager frontmatter parser (stdlib-only, zero-install).
_SPEC_SCRIPTS = Path(__file__).resolve().parents[2] / "spec-manager" / "scripts"
_CODE_GRAPH = Path(__file__).resolve().parents[2] / "code-graph" / "scripts" / "graph_ops.py"
sys.path.insert(0, str(_SPEC_SCRIPTS))
import frontmatter  # noqa: E402
from frontmatter import FrontmatterError  # noqa: E402
# adapters.py lives alongside frontmatter.py in spec-manager/scripts (already on sys.path).
from adapters import parse_locator  # noqa: E402

OBSERVED_CONFIDENCE = 0.8
STATIC_CONFIDENCE = 0.5


def load_behaviors(specs_dir, states=("accepted",), level=None):
    """Return behavior records under specs_dir whose state is in `states`,
    optionally filtered by level.

    Each record is the spec's behavior mapping plus `spec_id` and `spec_path`.
    """
    states = tuple(states)
    out = []
    for root, _dirs, files in os.walk(specs_dir):
        for name in files:
            if not name.endswith(".md"):
                continue
            path = os.path.join(root, name)
            try:
                with open(path, encoding="utf-8") as f:
                    fm, _body = frontmatter.parse_frontmatter(f.read())
            except FrontmatterError as e:
                sys.stderr.write(f"[behavior-runner] skipping unparseable spec {path}: {e}\n")
                continue
            behaviors = fm.get("behaviors")
            if not isinstance(behaviors, list):
                continue
            for b in behaviors:
                if not isinstance(b, dict):
                    continue
                if b.get("state") not in states:
                    continue
                if level is not None and b.get("level") != level:
                    continue
                rec = dict(b)
                rec["spec_id"] = fm.get("id")
                rec["spec_path"] = path
                out.append(rec)
    return out


def load_accepted_behaviors(specs_dir, level=None):
    """Backward-compatible wrapper: accepted behaviors only (used by the
    wrap-up 'run accepted behaviors' path, which must not run confirmed)."""
    return load_behaviors(specs_dir, states=("accepted",), level=level)


def coverage_files_to_keys(coverage_final, project_dir, exclude=None):
    """Map an istanbul coverage-final.json to executed project-relative paths."""
    exclude = exclude or set()
    project = Path(project_dir).resolve()
    keys = set()
    for abs_path, entry in coverage_final.items():
        statements = (entry or {}).get("s", {})
        if not any(count > 0 for count in statements.values()):
            continue  # file loaded but no statement executed
        p = Path(abs_path).resolve()
        try:
            rel = p.relative_to(project).as_posix()
        except ValueError:
            continue  # outside the project
        if rel.startswith("node_modules/") or "/node_modules/" in rel:
            continue
        if rel in exclude:
            continue
        keys.add(rel)
    return sorted(keys)


def shape_fingerprint(exercised_keys, commit, source="observed", confidence=None, reason=None):
    """Build a per-behavior fingerprint. `source` ("observed"|"static") sets the
    coverage value and each edge's source; unknown when there are no keys."""
    if not exercised_keys:
        result = {"coverage": "unknown", "exercises": []}
        if reason is not None:
            result["reason"] = reason
        return result
    if confidence is None:
        confidence = STATIC_CONFIDENCE if source == "static" else OBSERVED_CONFIDENCE
    return {
        "coverage": source,
        "exercises": [
            {"path": k, "source": source, "confidence": confidence, "freshness": commit}
            for k in exercised_keys
        ],
    }


def static_exercises(entry, deps):
    """The static fingerprint key set: the entry file plus its dependency closure."""
    return sorted({entry, *deps})


def vitest_argv(behavior):
    """Return (argv, test_file) to run a single vitest test for this behavior."""
    test_file, fragment = parse_locator(behavior["locator"])
    argv = ["pnpm", "vitest", "run", test_file]
    if fragment:
        argv += ["-t", fragment]
    argv += ["--coverage"]
    return argv, test_file


def _git_head(project_dir):
    try:
        out = subprocess.run(
            ["git", "-C", project_dir, "rev-parse", "HEAD"],
            capture_output=True, text=True, check=True,
        )
        return out.stdout.strip()
    except (subprocess.CalledProcessError, FileNotFoundError):
        return "unknown"


def run_unit_behavior(behavior, project_dir):
    """Run one unit behavior via vitest with coverage; return its fingerprint."""
    argv, test_file = vitest_argv(behavior)
    commit = _git_head(project_dir)
    cov_path = os.path.join(project_dir, "coverage", "coverage-final.json")
    if os.path.exists(cov_path):
        os.remove(cov_path)

    result = subprocess.run(argv, cwd=project_dir, capture_output=True, text=True)
    if result.returncode != 0:
        # Test failed -> coverage-unknown, never faked.
        sys.stderr.write(result.stdout + result.stderr)
        return shape_fingerprint([], commit, reason="test-failed")
    if not os.path.exists(cov_path):
        # Test passed but produced no coverage file -> misconfigured reporter.
        sys.stderr.write(
            f"[behavior-runner] {behavior['behavior_id']}: test passed but no coverage at"
            f" {cov_path} — is @vitest/coverage-v8 + the json reporter configured?\n"
        )
        return shape_fingerprint([], commit, reason="no-coverage")

    with open(cov_path, encoding="utf-8") as f:
        coverage_final = json.load(f)
    keys = coverage_files_to_keys(coverage_final, project_dir, exclude={test_file})
    return shape_fingerprint(keys, commit)


def _code_graph_deps(entry, project_dir):
    """Transitive import-closure of `entry` from code-graph (project-relative keys).

    Returns None if no built graph cache exists (caller should treat as no-graph,
    not as an empty closure), a list of keys on success, or [] on subprocess/parse
    errors when the graph cache is present.
    """
    graph_path = os.path.join(project_dir, "knowledge-base", ".graph", "graph.json")
    if not os.path.exists(graph_path):
        return None
    try:
        out = subprocess.run(
            [sys.executable, str(_CODE_GRAPH), "--dependencies", entry,
             "--dir", project_dir, "--format", "json"],
            capture_output=True, text=True, check=True,
        )
        data = json.loads(out.stdout)
        return data if isinstance(data, list) else []
    except (subprocess.CalledProcessError, json.JSONDecodeError, FileNotFoundError, OSError):
        return []


def static_fingerprint(behavior, project_dir):
    """Integration-level fingerprint: the declared entry + its code-graph closure,
    tagged source: static. No entry / missing file / no edges -> coverage unknown."""
    commit = _git_head(project_dir)
    entry = behavior.get("entry")
    if not entry:
        return shape_fingerprint([], commit, reason="no-entry")
    if not os.path.exists(os.path.join(project_dir, entry)):
        sys.stderr.write(
            f"[behavior-runner] {behavior.get('behavior_id')}: entry not found: {entry}\n"
        )
        return shape_fingerprint([], commit, reason="entry-missing")
    deps = _code_graph_deps(entry, project_dir)
    if deps is None:
        sys.stderr.write(
            f"[behavior-runner] {behavior.get('behavior_id')}: no code-graph at {project_dir}"
            f" (run code-graph build) — cannot derive static fingerprint\n"
        )
        return shape_fingerprint([], commit, reason="no-graph")
    return shape_fingerprint(
        static_exercises(entry, deps), commit, source="static", confidence=STATIC_CONFIDENCE
    )


def fingerprint_behavior(behavior, project_dir, commit):
    """Produce one behavior's fingerprint by state then level.

    `confirmed` = intent confirmed, test owed (design 03 §3): it has no
    executable test yet, so it is NEVER run — it gets an advisory STATIC
    fingerprint from its `entry` (or `unknown`/`no-entry` with none). Because it
    is never executed it can never be `test-failed`, so it never gates wrap-up.
    """
    if behavior.get("state") == "confirmed":
        return static_fingerprint(behavior, project_dir)
    if behavior.get("level") == "unit" and behavior.get("adapter") == "vitest":
        return run_unit_behavior(behavior, project_dir)
    # Static integration path is adapter-agnostic (cucumber, native, etc.) — the
    # entry field drives the closure.
    if behavior.get("level") == "integration":
        return static_fingerprint(behavior, project_dir)
    # Non-unit/non-vitest accepted levels are produced by later plans.
    return shape_fingerprint([], commit, reason="level-deferred")


def filter_only(behaviors, only):
    """Restrict a behavior list to the given BEH ids (order: by the behavior list)."""
    if not only:
        return behaviors
    wanted = set(only)
    return [b for b in behaviors if b.get("behavior_id") in wanted]


def main():
    parser = argparse.ArgumentParser(description="Run accepted behaviors and emit fingerprints.")
    parser.add_argument("--project", required=True, help="Project root directory.")
    parser.add_argument("--specs-dir", help="Specs dir (default: <project>/knowledge-base/specs).")
    parser.add_argument("--level", help="Only run behaviors at this level (e.g. unit).")
    parser.add_argument("--states", nargs="+", default=["accepted"],
                        help="Behavior states to load (default: accepted only).")
    parser.add_argument("--only", nargs="+", metavar="BEH",
                        help="Restrict to these accepted behavior ids.")
    parser.add_argument("--list", action="store_true", help="List matching accepted behaviors and exit.")
    parser.add_argument("--emit-fingerprints", action="store_true",
                        help="Run each matching behavior and emit fingerprints JSON.")
    args = parser.parse_args()

    specs_dir = args.specs_dir or os.path.join(args.project, "knowledge-base", "specs")
    behaviors = load_behaviors(specs_dir, states=args.states, level=args.level)
    behaviors = filter_only(behaviors, args.only)

    if args.list:
        for b in behaviors:
            print(f"{b['behavior_id']}\t{b.get('level')}\t{b.get('adapter')}\t{b.get('locator')}")
        return 0

    if args.emit_fingerprints:
        commit = _git_head(args.project)
        fingerprints = {}
        for b in behaviors:
            fingerprints[b["behavior_id"]] = fingerprint_behavior(b, args.project, commit)
        print(json.dumps({
            "version": 1,
            "commit": commit,
            "fingerprints": fingerprints,
        }, indent=2))
        return 0

    print(json.dumps({"behaviors": [b["behavior_id"] for b in behaviors]}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
