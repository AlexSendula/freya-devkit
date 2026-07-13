#!/usr/bin/env python3
"""
collect_status.py — the deterministic core of the `status` skill.

Aggregates the project's outstanding behavior / coverage / security work into
one read-only report, and (optionally) regenerates knowledge-base/BACKLOG.md.
Every source degrades independently: a missing graph / findings / specs yields
an empty bucket plus a note, never a crash. Stdlib-only.
"""
import argparse
import json
import os
import subprocess
import sys
from pathlib import Path

_SPEC_SCRIPTS = Path(__file__).resolve().parents[2] / "spec-manager" / "scripts"
_BEHAVIOR_GRAPH = Path(__file__).resolve().parents[2] / "behavior-graph" / "scripts" / "behavior_graph.py"
_VERIFY_LINKS = _SPEC_SCRIPTS / "verify_links.py"
sys.path.insert(0, str(_SPEC_SCRIPTS))
import frontmatter  # noqa: E402
from frontmatter import FrontmatterError, BEHAVIOR_STATES  # noqa: E402

GAPS_SAMPLE = 20


def _specs_dir(project_dir):
    return os.path.join(project_dir, "knowledge-base", "specs")


def _git_head(project_dir):
    try:
        out = subprocess.run(["git", "-C", project_dir, "rev-parse", "HEAD"],
                             capture_output=True, text=True, check=True)
        return out.stdout.strip()
    except (subprocess.CalledProcessError, FileNotFoundError, OSError):
        return None


def behavior_census(project_dir):
    """Counts by state + the intent (proposed) and test-owed (confirmed) worklists.

    `project_dir` may be a project root OR a specs dir directly (tests pass the
    latter); we resolve to a specs dir if one exists under it, else use it as-is.
    """
    specs_dir = _specs_dir(project_dir)
    if not os.path.isdir(specs_dir):
        specs_dir = project_dir
    counts = {s: 0 for s in BEHAVIOR_STATES}
    intent, test_owed = [], []
    if os.path.isdir(specs_dir):
        for root, _dirs, files in os.walk(specs_dir):
            for name in files:
                if not name.endswith(".md"):
                    continue
                try:
                    with open(os.path.join(root, name), encoding="utf-8") as f:
                        fm, _body = frontmatter.parse_frontmatter(f.read())
                except (FrontmatterError, OSError):
                    continue
                behaviors = fm.get("behaviors")
                if not isinstance(behaviors, list):
                    continue
                spec_id = fm.get("id")
                certainty = fm.get("certainty")
                spec_path = os.path.join(root, name)
                for b in behaviors:
                    if not isinstance(b, dict) or not b.get("behavior_id"):
                        continue
                    state = b.get("state")
                    if state in counts:
                        counts[state] += 1
                    rec = {"behavior_id": b.get("behavior_id"), "title": b.get("title"),
                           "spec_id": spec_id, "spec_path": spec_path}
                    if state == "proposed":
                        rec["certainty"] = certainty if isinstance(certainty, int) else 100
                        intent.append(rec)
                    elif state == "confirmed":
                        test_owed.append(rec)
    intent.sort(key=lambda r: (r.get("certainty", 100), r.get("behavior_id") or ""))
    test_owed.sort(key=lambda r: r.get("behavior_id") or "")
    return counts, intent, test_owed


def gaps_bucket(project_dir):
    """Whole-repo coverage gaps via behavior-graph --gaps (count + capped sample)."""
    try:
        # check=True is safe here: behavior-graph --gaps always exits 0 (it returns a
        # JSON "note" on a missing graph rather than failing), unlike verify_links which
        # exits non-zero on findings (so verify_bucket must NOT use check=True).
        out = subprocess.run(
            [sys.executable, str(_BEHAVIOR_GRAPH), "--gaps", "--project", project_dir],
            capture_output=True, text=True, check=True)
        data = json.loads(out.stdout)
    except (subprocess.CalledProcessError, json.JSONDecodeError, FileNotFoundError, OSError):
        return {"total": 0, "sample": []}, "could not compute gaps (behavior-graph --gaps)"
    return {"total": data.get("total", 0), "sample": data.get("gaps", [])[:GAPS_SAMPLE]}, data.get("note")


def verify_bucket(project_dir):
    """Tier-1 link-integrity errors from verify_links (which exits non-zero when it
    finds errors — so we must NOT use check=True, or the JSON would be lost)."""
    try:
        out = subprocess.run(
            [sys.executable, str(_VERIFY_LINKS), "--dir", _specs_dir(project_dir), "--format", "json"],
            capture_output=True, text=True)
        errors = json.loads(out.stdout) if out.stdout.strip() else []
        return errors, None
    except (json.JSONDecodeError, FileNotFoundError, OSError):
        return [], "could not run verify_links"


def stale_bucket(project_dir):
    """Behaviors in behavior.json whose fingerprint freshness != current HEAD."""
    path = os.path.join(project_dir, "knowledge-base", ".graph", "behavior.json")
    if not os.path.exists(path):
        return [], "no behavior.json — run behavior-graph --build"
    try:
        with open(path, encoding="utf-8") as f:
            behaviors = json.load(f).get("behaviors", {})
    except (json.JSONDecodeError, OSError):
        return [], "behavior.json unreadable"
    head = _git_head(project_dir)
    if not head:
        return [], None
    stale = []
    for bid, rec in behaviors.items():
        fresh = {e.get("freshness") for e in rec.get("exercises", []) if e.get("freshness")}
        if fresh and head not in fresh:
            stale.append(bid)
    return sorted(stale), None


def security_bucket(project_dir):
    """Open findings from the structured findings.json index."""
    path = os.path.join(project_dir, "knowledge-base", "security",
                        "codebase-security", "findings.json")
    if not os.path.exists(path):
        return [], "no findings.json — run codebase-security-scan"
    try:
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
    except (json.JSONDecodeError, OSError):
        return [], "findings.json unreadable"
    findings = data.get("findings", []) if isinstance(data, dict) else []
    out = [{"id": x.get("id"), "title": x.get("title"),
            "severity": x.get("severity"), "file": x.get("file")}
           for x in findings if isinstance(x, dict) and x.get("status") == "open"]
    return out, None


def collect(project_dir):
    """Assemble the full status report dict (read-only)."""
    counts, intent, test_owed = behavior_census(project_dir)
    notes = []
    gaps, n = gaps_bucket(project_dir); notes += [n] if n else []
    verify_failures, n = verify_bucket(project_dir); notes += [n] if n else []
    stale, n = stale_bucket(project_dir); notes += [n] if n else []
    security, n = security_bucket(project_dir); notes += [n] if n else []
    return {
        "version": 1,
        "project": os.path.abspath(project_dir),
        "behavior_counts": counts,
        "intent_worklist": intent,
        "test_owed_worklist": test_owed,
        "gaps": gaps,
        "verify_failures": verify_failures,
        "stale_fingerprints": stale,
        "open_security_findings": security,
        "notes": notes,
    }


def render_backlog(status):
    """Render BACKLOG.md markdown from a status dict."""
    c = status["behavior_counts"]
    intent = status["intent_worklist"]
    owed = status["test_owed_worklist"]
    gaps = status["gaps"]
    sec = status["open_security_findings"]
    L = ["# Backlog", "",
         "> Generated by `/freya-devkit:status` — **do not edit**; run `status` to refresh.",
         "",
         (f"**Census:** {c['proposed']} proposed · {c['confirmed']} confirmed · "
          f"{c['accepted']} accepted · {len(owed)} tests owed · {len(sec)} open findings · "
          f"{gaps['total']} coverage gaps"),
         ""]

    L += ["## Behaviors to confirm", ""]
    if intent:
        L += ["| Behavior | Title | Spec |", "|---|---|---|"]
        L += [f"| {r['behavior_id']} | {r.get('title') or ''} | {r.get('spec_id') or ''} |" for r in intent]
    else:
        L.append("_None._")
    L.append("")

    L += ["## Tests owed", ""]
    if owed:
        L += ["| Behavior | Title | Spec |", "|---|---|---|"]
        L += [f"| {r['behavior_id']} | {r.get('title') or ''} | {r.get('spec_id') or ''} |" for r in owed]
    else:
        L.append("_None._")
    L.append("")

    L += ["## Coverage gaps", ""]
    L.append(f"{gaps['total']} uncovered source file(s)." + (" Sample:" if gaps["sample"] else ""))
    L += [f"- `{f}`" for f in gaps["sample"]]
    L.append("")

    L += ["## Open security findings", ""]
    if sec:
        L += ["| ID | Severity | Title | File |", "|---|---|---|---|"]
        L += [f"| {f.get('id') or ''} | {f.get('severity') or ''} | {f.get('title') or ''} | {f.get('file') or ''} |"
              for f in sec]
    else:
        L.append("_None._")
    L.append("")
    return "\n".join(L) + "\n"


def write_backlog(project_dir, status):
    path = os.path.join(project_dir, "knowledge-base", "BACKLOG.md")
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        f.write(render_backlog(status))
    return path


def _format_text(status):
    c = status["behavior_counts"]
    L = [f"Status for {status['project']}",
         (f"  behaviors: {c['proposed']} proposed, {c['confirmed']} confirmed, "
          f"{c['accepted']} accepted, {c['quarantined']} quarantined, {c['deprecated']} deprecated"),
         f"  intent worklist (to confirm): {len(status['intent_worklist'])}",
         f"  test-owed worklist:           {len(status['test_owed_worklist'])}",
         f"  coverage gaps:                {status['gaps']['total']}",
         f"  verify failures:              {len(status['verify_failures'])}",
         f"  stale fingerprints:           {len(status['stale_fingerprints'])}",
         f"  open security findings:       {len(status['open_security_findings'])}"]
    for n in status["notes"]:
        L.append(f"  note: {n}")
    return "\n".join(L)


def main():
    parser = argparse.ArgumentParser(description="Aggregate project behavior/coverage/security status.")
    parser.add_argument("--project", required=True, help="Project root directory.")
    parser.add_argument("--format", choices=["json", "text"], default="text")
    parser.add_argument("--write-backlog", action="store_true",
                        help="Regenerate knowledge-base/BACKLOG.md from the status.")
    args = parser.parse_args()
    status = collect(args.project)
    if args.write_backlog:
        path = write_backlog(args.project, status)
        print(f"wrote {path}")
    if args.format == "json":
        print(json.dumps(status, indent=2))
    else:
        print(_format_text(status))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
