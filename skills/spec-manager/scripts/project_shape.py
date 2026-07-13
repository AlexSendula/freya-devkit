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
                   / "docs-manager" / "scripts" / "detect_project.py")


def _graph_path(project_dir):
    return os.path.join(project_dir, "knowledge-base", ".graph", "graph.json")


def count_graph(project_dir):
    """Return (source_files, internal_edges, graph_present).

    An internal edge is an import code-graph resolved to a project file — i.e.
    NOT tagged `external:` or `unresolved:`. Internal edges (real wiring) are the
    brownfield signal; raw file count is not (a bare scaffold can have many
    boilerplate files yet zero internal wiring).
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
            if not imp.startswith(("external:", "unresolved:")):
                internal_edges += 1
    return len(files), internal_edges, True


def run_detect_project(project_dir):
    """Return detect_project.py's stack dict (empty dict on any failure)."""
    try:
        out = subprocess.run(
            [sys.executable, str(_DETECT_PROJECT), project_dir],
            capture_output=True, text=True, check=True,
        )
        data = json.loads(out.stdout)
        return data if isinstance(data, dict) else {}
    except (subprocess.CalledProcessError, json.JSONDecodeError, FileNotFoundError, OSError):
        return {}


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
    if internal_edges == 0:
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
