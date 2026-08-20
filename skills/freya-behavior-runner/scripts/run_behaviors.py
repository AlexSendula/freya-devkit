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

# Reuse the freya-spec-manager frontmatter parser (stdlib-only, zero-install).
_SPEC_SCRIPTS = Path(__file__).resolve().parents[2] / "freya-spec-manager" / "scripts"
_CODE_GRAPH = Path(__file__).resolve().parents[2] / "freya-code-graph" / "scripts" / "graph_ops.py"
sys.path.insert(0, str(_SPEC_SCRIPTS))
import frontmatter  # noqa: E402
from frontmatter import FrontmatterError  # noqa: E402
# adapters.py lives alongside frontmatter.py in freya-spec-manager/scripts (already on sys.path).
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
            except (FrontmatterError, UnicodeDecodeError, OSError) as e:
                # `UnicodeDecodeError` and `OSError` alongside the parse error: strict UTF-8
                # decoding is a *read* failure, not a frontmatter one, so a single spec with
                # a stray byte — or one that cannot be opened at all — took down the whole
                # behaviour layer with an unhandled traceback rather than skipping the one
                # file it could not read. One bad file must cost one file.
                sys.stderr.write(f"[behavior-runner] skipping unreadable spec {path}: {e}\n")
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


def coverage_symbols(coverage_final, project_dir, exclude=None):
    """Map an istanbul coverage-final.json to the *named functions that actually ran*.

    Phase 3's symbol refinement, and it comes from the coverage report rather than from the
    code graph on purpose. An `observed` exercise means "the test ran this"; taking its
    symbols from a graph would mix in something nobody executed. `fnMap[i]` names each
    function and `f[i]` counts its executions, so this is measurement, not inference.

    Two rules, both from looking at real coverage output (775 functions across 123 files):

    - **`f[i] > 0` only.** A function that was loaded but never entered is not exercised.
    - **Named functions only.** 405 of those 775 are `(anonymous_N)`, and N is a *positional*
      counter per file — `(anonymous_1)` occurs in 44 files, and inserting one function
      renumbers every later one. Committing those into `behavior.json` (which is tracked,
      ADR-017) would churn the diff on edits that changed nothing about what ran.
    """
    exclude = exclude or set()
    project = Path(project_dir).resolve()
    symbols = {}
    for abs_path, entry in (coverage_final or {}).items():
        fn_map = (entry or {}).get("fnMap") or {}
        counts = (entry or {}).get("f") or {}
        if not fn_map:
            continue
        try:
            rel = Path(abs_path).resolve().relative_to(project).as_posix()
        except ValueError:
            continue
        if rel in exclude or rel.startswith("node_modules/") or "/node_modules/" in rel:
            continue
        names = set()
        for index, fn in fn_map.items():
            if not counts.get(index):
                continue
            name = (fn or {}).get("name")
            if isinstance(name, str) and name and not name.startswith("(anonymous"):
                names.add(name)
        if names:
            # Union, not assignment. Two absolute keys can resolve to one project-relative
            # path — a workspace package reached through a symlink, or any non-canonical
            # duplicate — and assigning would let whichever came last in the JSON silently
            # erase the other file's executed functions. `coverage_files_to_keys` is immune
            # because it builds a set of paths; this builds a mapping, so it has to say so.
            symbols.setdefault(rel, set()).update(names)
    return {rel: sorted(names) for rel, names in symbols.items()}


def shape_fingerprint(exercised_keys, commit, source="observed", confidence=None, reason=None,
                      symbols=None):
    """Build a per-behavior fingerprint. `source` ("observed"|"static") sets the
    coverage value and each edge's source; unknown when there are no keys.

    `symbols` optionally refines an entry with the named functions that ran in that file. It
    is a *list on the existing per-file entry*, not an entry per symbol: the file key is what
    `behavior-graph` intersects against the impact set, and splitting the entry would change
    that set's cardinality and every count derived from it. Refinement never replaces the file
    anchor (spec §5) — an entry with no symbols is byte-identical to one from before this
    existed, which is what makes the addition safe on a committed artifact.
    """
    if not exercised_keys:
        result = {"coverage": "unknown", "exercises": []}
        if reason is not None:
            result["reason"] = reason
        return result
    if confidence is None:
        confidence = STATIC_CONFIDENCE if source == "static" else OBSERVED_CONFIDENCE
    symbols = symbols or {}
    exercises = []
    for k in exercised_keys:
        edge = {"path": k, "source": source, "confidence": confidence, "freshness": commit}
        named = symbols.get(k)
        if named:
            edge["symbols"] = sorted(named)
        exercises.append(edge)
    return {"coverage": source, "exercises": exercises}


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
    if not keys:
        # A coverage report that maps onto nothing inside `--project`. Every other failure
        # path here carries a `reason`; this one returned a bare `unknown`, which is the
        # single value the merge treats as "no news" — so the previous `observed`
        # fingerprint was preserved indefinitely and nothing ever said the measurement had
        # stopped landing. Real causes: a monorepo where the test exercises a sibling
        # package outside the project root, or a reporter emitting paths this cannot
        # resolve.
        sys.stderr.write(
            f"[behavior-runner] {behavior['behavior_id']}: the test passed and produced"
            f" coverage, but none of it maps inside {project_dir} — the fingerprint is"
            f" unknown rather than empty\n")
        return shape_fingerprint([], commit, reason="coverage-outside-project")
    return shape_fingerprint(
        keys, commit,
        symbols=coverage_symbols(coverage_final, project_dir, exclude={test_file}))


def _graph_degraded_from(graph_path):
    """The backend a graph *should* have been built with, if it fell back. None otherwise.

    Read from the artifact rather than from settings, because the artifact is the thing that
    records what actually happened — `degraded_from` is written by the run that degraded, and
    a graph carried between machines still carries it.
    """
    try:
        with open(graph_path, encoding="utf-8") as fh:
            substrate = (json.load(fh) or {}).get("substrate")
    except (OSError, ValueError):
        return None
    if not isinstance(substrate, dict):
        return None
    wanted = substrate.get("degraded_from")
    if not isinstance(wanted, str) or not wanted:
        return None
    got = substrate.get("backend")
    return "%s unavailable, built with %s" % (wanted, got if isinstance(got, str) else "?")


def _portable(detail, project_dir):
    """One line of another tool's stderr, made safe to commit.

    `reason` is written into behavior.json, which is tracked (ADR-017). Splicing raw stderr
    in put whatever that line contained into git: a traceback tail carries the absolute path
    of the machine that produced it, so the same failure produced a different committed
    string on every developer's laptop and leaked a home directory into the repository.

    The project root becomes `.`; anything still absolute is dropped to its basename. The
    diagnostic survives, the machine does not.
    """
    text = " ".join(str(detail or "").split())[:200]
    root = str(project_dir or "").rstrip(os.sep)
    if root:
        text = text.replace(root + os.sep, "").replace(root, ".")
    return " ".join(
        os.path.basename(word) if os.path.isabs(word) else word for word in text.split())


def _code_graph_deps(entry, project_dir):
    """-> (keys, reason). The transitive import-closure of `entry` from code-graph.

    `keys` is None when the closure could not be determined, and `reason` says why —
    `"no-graph"` or `"graph-query-failed"`. Never `[]` on failure.

    It used to return `[]` on any subprocess or parse error, and the only caller branched
    on `deps is None`. So a failed query produced `static_exercises(entry, [])` — a
    one-file closure — tagged `coverage: static` at full confidence, with no warning.
    behavior.json is committed (ADR-017) and its `exercises[].path` values decide which
    behaviors a change is deemed to affect, so the wrong answer persisted into the repo and
    then quietly narrowed every later blast radius. A green wrap-up that ran fewer
    behaviors than it should is precisely the silent-empty failure ADR-005 exists to stop.

    An empty closure is a real answer — a file that imports nothing. A failed query is not,
    and the two must not share a representation.
    """
    graph_path = os.path.join(project_dir, "knowledge-base", ".graph", "graph.json")
    if not os.path.exists(graph_path):
        return None, "no-graph"

    degraded = _graph_degraded_from(graph_path)
    if degraded:
        # The project asked for a backend and did not get one, so this graph is thinner than
        # the project declared. Answering anyway would write that thinner closure into
        # behavior.json — which is committed, and whose `exercises[].path` values decide
        # which behaviours a change is deemed to affect. Every later blast radius would then
        # be computed against a closure narrowed by whichever laptop happened to run last.
        #
        # `unknown` with a reason is exactly the "no news" signal `merge_fingerprint` already
        # honours: the prior fingerprint is preserved rather than replaced. Refusing to
        # answer is the honest move; a narrower answer that looks authoritative is not.
        return None, "graph-degraded: %s" % degraded
    # `substrate.unmapped_source` (CD-27) is deliberately NOT read here, and extending the
    # refusal above to cover it is the first "fix" a future reader will reach for.
    #
    # `degraded_from` means the project asked for a backend and did not get one — abnormal,
    # and the artifact is thinner than the project itself declared. Blind spots mean the
    # backend the project *chose* cannot read everything, which is the ordinary operating
    # condition of the floor on any polyglot repository. Refusing on it would return
    # `coverage: unknown` for every confirmed and every integration behaviour on every such
    # repo, freezing behavior.json where there is history and writing empty `exercises` where
    # there is not — and wrap-up's gate would then run zero behaviours and exit 0. A caveat
    # must never change whether there is an answer, only what the answer says about itself.
    # Pinned by test_a_repo_with_unmapped_files_still_fingerprints_static.
    try:
        out = subprocess.run(
            [sys.executable, str(_CODE_GRAPH), "--dependencies", entry,
             "--dir", project_dir, "--format", "json"],
            capture_output=True, text=True, check=True,
        )
        data = json.loads(out.stdout)
    except subprocess.CalledProcessError as exc:
        # A non-zero exit includes "this entry is not a node in the graph", which code-graph
        # reports rather than answering `[]` — the entry may sit under a directory the graph
        # excludes, which is a coverage gap and not an absence of dependencies. Its message
        # goes through verbatim so the operator sees which of the two it was.
        detail = (exc.stderr or "").strip().splitlines()
        return None, "graph-query-failed: %s" % _portable(detail[-1] if detail else
                                                          "no detail", project_dir)
    except (json.JSONDecodeError, FileNotFoundError, OSError):
        return None, "graph-query-failed"
    if not isinstance(data, list) or not all(isinstance(k, str) for k in data):
        # `--dependencies` answers in path strings. Anything else means the artifact's
        # shape moved underneath us, and guessing at it is how a wrong closure gets
        # committed — see the docstring.
        return None, "graph-query-failed"
    return data, None


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
    deps, reason = _code_graph_deps(entry, project_dir)
    if deps is None:
        detail = (f"no code-graph at {project_dir} (run code-graph build)"
                  if reason == "no-graph"
                  else f"code-graph could not answer --dependencies for {entry}"
                       f" ({reason.split(': ', 1)[-1]})")
        sys.stderr.write(
            f"[behavior-runner] {behavior.get('behavior_id')}: {detail}"
            f" — cannot derive static fingerprint\n"
        )
        return shape_fingerprint([], commit, reason=reason)
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
