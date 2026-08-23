#!/usr/bin/env python3
"""
project_shape.py — classify a project as greenfield / brownfield / unknown for
the spec-manager `bootstrap` onboarding flow.

The classification is a *recommendation*: bootstrap shows the evidence and lets
the engineer confirm or override (SP2 design §2). The signal is objective and
transparent — code-graph's internal import-edge count (real feature wiring, not
mere file count) plus detect_project's stack summary.

Stdlib-only.
"""
import argparse
import json
import os
import subprocess
import sys
from pathlib import Path

_DETECT_PROJECT = (Path(__file__).resolve().parents[2]
                   / "freya-docs-manager" / "scripts" / "detect_project.py")


def _graph_path(project_dir):
    return os.path.join(project_dir, "knowledge-base", ".graph", "graph.json")


def count_graph(project_dir):
    """Return (source_files, internal_edges, graph_present).

    An internal edge is an import code-graph resolved to a project file — i.e.
    NOT tagged `external:` or `unresolved:`. Internal edges (real wiring) are the
    brownfield signal; raw file count is not (a bare scaffold can have many
    boilerplate files yet zero internal wiring).

    An edge is `{"to": ..., "kind": ..., "provenance": ...}` since 2026-08-20, and was a
    bare string before that. Both are read, because a graph.json written by an older build
    is still on disk until something rebuilds it — and misreading it would report a wired
    codebase as `greenfield`, which is the exact wrong answer this function exists to avoid.
    The projection is duplicated here rather than imported: `substrate.edge_other` is the
    definition, and reaching into another skill's scripts for one expression would couple
    them harder than the shared artifact already does.
    """
    path = _graph_path(project_dir)
    if not os.path.exists(path):
        return 0, 0, False
    try:
        with open(path, encoding="utf-8") as f:
            graph = json.load(f)
    except (json.JSONDecodeError, OSError):
        return 0, 0, False
    files = graph.get("files", {})
    internal_edges = 0
    for info in files.values():
        for imp in info.get("imports", []):
            target = imp.get("to", "") if isinstance(imp, dict) else imp
            if isinstance(target, str) and target and not target.startswith(
                    ("external:", "unresolved:")):
                internal_edges += 1
    return len(files), internal_edges, True


#: How long a stack detection may run before this caller stops waiting. A detection is a
#: bounded walk of one repository, so sixty seconds is orders of magnitude of headroom and
#: still short enough that a wedged child is noticed rather than waited on. There was no
#: timeout at all until SEC-008: whatever `detect_project` did — including, through a
#: committed `vendor -> /` symlink, walking the operator's whole filesystem — this call
#: waited for it, with `capture_output=True` so nothing reached the operator meanwhile.
#: The child bounds its own walk now (`detect_project._WALK_FILE_LIMIT`), so this is defence
#: in depth — and it has to be, for the next unbounded scan somebody adds over there.
_DETECT_TIMEOUT = 60


def run_detect_project(project_dir):
    """Return detect_project.py's stack dict (empty dict on any failure).

    `subprocess.TimeoutExpired` is in the except tuple and is not redundant with the `OSError`
    beside it: it derives from `SubprocessError`, so adding the timeout without adding the
    class would have swapped a hang for an uncaught exception out of `classify()` — worse than
    the hang, for a caller whose entire contract is "empty dict on any failure".
    """
    try:
        out = subprocess.run(
            [sys.executable, str(_DETECT_PROJECT), project_dir],
            capture_output=True, text=True, check=True, timeout=_DETECT_TIMEOUT,
        )
        data = json.loads(out.stdout)
        return data if isinstance(data, dict) else {}
    except (subprocess.CalledProcessError, subprocess.TimeoutExpired,
            json.JSONDecodeError, FileNotFoundError, OSError):
        return {}


_CENSUS_SKIP = {
    "node_modules", ".git", "dist", "build", "out", ".next", "__pycache__",
    "venv", ".venv", "vendor", "target", "coverage", "knowledge-base",
    # Backend output. Counting a substrate's own artifacts as files it failed to read would
    # have every project report a blind spot in its own graph directory.
    "graphify-out",
}


def unreadable_files(project_dir, limit=20000):
    """Count files on disk, by extension, that the graph's backend does not read.

    Returns `{}` when the graph predates the substrate block, so a graph built before
    Track B Phase 1 keeps its old classification instead of suddenly reading as unknown.
    """
    path = _graph_path(project_dir)
    try:
        with open(path, encoding="utf-8") as f:
            graph = json.load(f)
    except (json.JSONDecodeError, OSError):
        return {}
    if not isinstance(graph, dict):
        return {}
    coverage = ((graph.get("substrate") or {}).get("coverage") or {})
    extensions = coverage.get("extensions")
    if not isinstance(extensions, list) or not extensions:
        return {}

    known = {str(e).lower() for e in extensions}
    census = {}
    seen = 0
    for root, dirs, filenames in os.walk(project_dir):
        dirs[:] = [d for d in dirs if d not in _CENSUS_SKIP and not d.startswith(".")]
        for filename in filenames:
            if filename.startswith("."):
                continue  # dotfiles are configuration, not unread source
            ext = os.path.splitext(filename)[1].lower()
            if not ext or ext in known:
                continue
            census[ext] = census.get(ext, 0) + 1
            seen += 1
            if seen >= limit:
                return census
    return census


# Extensions that are never source, so their presence says nothing about whether a repo is
# empty. Without this every project looks "unreadable" because of its README and lockfile.
_NOT_SOURCE = {
    ".md", ".txt", ".json", ".yaml", ".yml", ".toml", ".lock", ".xml", ".ini", ".cfg",
    ".png", ".jpg", ".jpeg", ".gif", ".svg", ".webp", ".ico", ".pdf",
    ".css", ".scss", ".sass", ".less", ".html", ".sh", ".env", ".gitignore",
    ".sql", ".csv", ".log", ".map", ".woff", ".woff2", ".ttf", ".otf", ".eot",
}


def unmapped_from_graph(project_dir):
    """(extensions, censused) from the graph's own `substrate.unmapped_source` block.

    `censused` is False when the key is absent — the graph predates the census (ADR-029) — and
    also when the census *ran and failed*, which records `{"files": null, "error": ...}`. Both
    mean "I do not know what this backend could not read", and both must fall back to the walk.
    Treating the error block as a clean answer turned an explicit I-don't-know back into a
    silent zero, which is the exact substitution the block was added to prevent.

    `{"files": 0}` is a real answer and returns `({}, True)`.
    """
    try:
        with open(_graph_path(project_dir), encoding="utf-8") as f:
            graph = json.load(f)
    except (json.JSONDecodeError, OSError):
        return {}, False
    if not isinstance(graph, dict):
        return {}, False
    substrate_block = graph.get("substrate")
    if not isinstance(substrate_block, dict):
        return {}, False
    block = substrate_block.get("unmapped_source")
    if not isinstance(block, dict) or block.get("files") is None:
        return {}, False
    return dict(block.get("extensions") or {}), True


def _censused(project_dir):
    """Did a ADR-029 census actually run for this graph, and succeed?"""
    return unmapped_from_graph(project_dir)[1]


def _has_files(project_dir, limit=200):
    """Does this directory hold anything at all, ignoring tooling and version control?

    Cheap and short-circuiting: the caller only needs "more than zero", so it stops at the
    first hit. `limit` bounds a pathological tree rather than the answer.
    """
    seen = 0
    for root, dirs, filenames in os.walk(project_dir):
        dirs[:] = [d for d in dirs
                   if d not in _CENSUS_SKIP and not d.startswith(".")]
        for filename in filenames:
            if not filename.startswith("."):
                return True
            seen += 1
            if seen >= limit:
                return False
    return False


def _blind_spots(project_dir, source_files=0):
    """What the graph's backend could not read, preferring the census over a fresh walk.

    The census is more accurate when it fires: it applies the build's own scope rule, where
    `unreadable_files` consults a hardcoded skip list that knows nothing about `.gitignore` or
    this project's directory classifications. Measured on freya-devkit, the walk reports 96
    files of which 68 are deliberately out of scope.

    But its **silence is not authoritative**, and treating it as such caused a real regression.
    The census is closed-world — it reports only extensions on a curated source list — and it
    reports only files that are *in scope*. A repository whose entire codebase is fifteen shell
    scripts under `scripts/` is therefore censused clean, because `scripts/` is a built-in
    top-level exclusion. Measured on a real 40-file deployment repo: `unknown` before this
    feature, `greenfield` after it. That is ADR-005's confidently-empty answer, reintroduced by
    the mechanism written to remove it — and it is the same `scripts/` exclusion that made
    freya unable to graph itself, one layer up.

    So: trust the census when it finds something, or when the graph has content to be
    authoritative about. When the graph is empty, fall back to the open-world walk, because an
    empty graph is precisely where a confident "nothing" is most dangerous and least earned.
    """
    census, censused = unmapped_from_graph(project_dir)
    if census:
        # No `_NOT_SOURCE` filter: the census already filtered, against a curated source list
        # and a materiality rule rather than a list of things that are not source.
        return census
    if censused and source_files:
        return {}
    return {ext: n for ext, n in unreadable_files(project_dir).items()
            if ext not in _NOT_SOURCE}


def classify(project_dir):
    """Classify project shape. Returns {recommendation, evidence, reason}."""
    source_files, internal_edges, graph_present = count_graph(project_dir)
    evidence = {
        "source_files": source_files,
        "internal_edges": internal_edges,
        "stack": run_detect_project(project_dir),
        "graph_present": graph_present,
    }
    if not graph_present:
        return {
            "recommendation": "unknown",
            "evidence": evidence,
            "reason": "no code-graph at knowledge-base/.graph/graph.json — run code-graph build first",
        }
    # Computed once, before the branches, and reported on all of them. It used to live inside
    # the zero-edge branch, so a repository with *any* internal edges was told nothing: two
    # TypeScript imports were enough to buy silence about 400 unread Java files, and the
    # evidence block would report `runtime: jvm` and `source_files: 3` side by side without
    # ever noticing the two were in tension.
    blind = _blind_spots(project_dir, source_files)
    if blind:
        evidence["blind_spots"] = blind
    if internal_edges == 0:
        # Zero edges means one of two very different things: no wiring yet, or a backend that
        # cannot read this language. Reporting *greenfield* for the second is how a large Java
        # codebase — and freya-devkit itself, until its resolver was repaired — was mistaken
        # for an empty scaffold, and it is the answer that then drives bootstrap.
        if not blind and source_files == 0 and _censused(project_dir) \
                and _has_files(project_dir):
            # A censused graph that is empty over a non-empty directory has said, positively,
            # "there is nothing here I cannot read" — which leaves only one explanation: the
            # scope rule excluded everything. Measured on a real 40-file deployment repo whose
            # whole codebase is shell scripts under `scripts/`, a built-in top-level exclusion:
            # `unknown` before this feature, `greenfield` after it. That is ADR-005's
            # confidently-empty answer reintroduced by the mechanism written to remove it.
            #
            # Gated on `_censused` so a graph written before the census keeps its old answer —
            # that one genuinely does not know, and flipping it would be a different kind of
            # guess.
            return {
                "recommendation": "unknown",
                "evidence": evidence,
                "reason": ("the graph is empty but the directory is not, and the backend "
                           "reports nothing it could not read — so every file here is outside "
                           "the graph's scope. Check the exclusions before bootstrapping; "
                           "this is not a greenfield project."),
            }
        if blind:
            listed = ", ".join(f"{n} {ext}" for ext, n in
                               sorted(blind.items(), key=lambda kv: (-kv[1], kv[0]))[:3])
            return {
                "recommendation": "unknown",
                "evidence": evidence,
                "reason": (f"0 internal import edges, but the code-graph backend does not read "
                           f"{listed} — this may be an existing codebase the graph cannot see, "
                           f"not a greenfield one. Check the substrate coverage before "
                           f"bootstrapping."),
            }
        return {
            "recommendation": "greenfield",
            "evidence": evidence,
            "reason": f"{source_files} source file(s) but 0 internal import edges — no real feature wiring yet",
        }
    return {
        "recommendation": "brownfield",
        "evidence": evidence,
        "reason": f"{source_files} source file(s) with {internal_edges} internal import edge(s) — existing codebase",
    }


def _format_text(result):
    e = result["evidence"]
    lines = [
        f"Recommendation: {result['recommendation']}",
        f"  reason: {result['reason']}",
        f"  source files:   {e['source_files']}",
        f"  internal edges: {e['internal_edges']}",
        f"  graph present:  {e['graph_present']}",
    ]
    # `--format text` is what spec-manager's bootstrap actually invokes, and it had no
    # blind-spot branch at all — so even the one path that did compute blind spots was
    # invisible on the only surface that reads it, except where it leaked into `reason`.
    blind = e.get("blind_spots") or {}
    if blind:
        listed = ", ".join(f"{n} {ext}" for ext, n in
                           sorted(blind.items(), key=lambda kv: (-kv[1], kv[0]))[:3])
        lines.append(f"  not graphed:    {listed} (the backend cannot read these)")
    stack = e.get("stack") or {}
    if stack:
        runtime_info = stack.get("runtime") or {}
        framework_info = stack.get("framework") or {}
        database_info = stack.get("database") or {}
        test_info = stack.get("test_runners") or {}

        parts = []
        runtime_val = runtime_info.get("runtime") if isinstance(runtime_info, dict) else None
        pkg_mgr = runtime_info.get("package_manager") if isinstance(runtime_info, dict) else None
        if runtime_val:
            parts.append(f"runtime={runtime_val}")
        if pkg_mgr:
            parts.append(f"pkg={pkg_mgr}")
        frontend = framework_info.get("frontend") if isinstance(framework_info, dict) else None
        backend = framework_info.get("backend") if isinstance(framework_info, dict) else None
        if frontend:
            parts.append(f"frontend={frontend}")
        if backend:
            parts.append(f"backend={backend}")
        db_type = database_info.get("type") if isinstance(database_info, dict) else None
        db_orm = database_info.get("orm") if isinstance(database_info, dict) else None
        if db_type:
            parts.append(f"db={db_type}")
        if db_orm:
            parts.append(f"orm={db_orm}")
        runners = test_info.get("runners") if isinstance(test_info, dict) else None
        if runners:
            parts.append(f"test={','.join(runners)}")
        if parts:
            lines.append(f"  stack: {' '.join(parts)}")
    return "\n".join(lines)


def main():
    parser = argparse.ArgumentParser(description="Classify project shape for bootstrap.")
    parser.add_argument("--project", required=True, help="Project root directory.")
    parser.add_argument("--format", choices=["json", "text"], default="json")
    args = parser.parse_args()
    result = classify(args.project)
    if args.format == "json":
        print(json.dumps(result, indent=2))
    else:
        print(_format_text(result))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
