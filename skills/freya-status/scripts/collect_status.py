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

_SPEC_SCRIPTS = Path(__file__).resolve().parents[2] / "freya-spec-manager" / "scripts"
_BEHAVIOR_GRAPH = Path(__file__).resolve().parents[2] / "freya-behavior-graph" / "scripts" / "behavior_graph.py"
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
                except (FrontmatterError, UnicodeDecodeError, OSError):
                    # UnicodeDecodeError is not an OSError. Strict decoding made one spec
                    # with a stray byte raise out of the whole status walk.
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
    """Tier-1 link-integrity errors from verify_links.

    `check=True` would be wrong — verify_links exits non-zero exactly when it has
    errors, and that is the run whose JSON this bucket wants. But then the exit
    code says nothing either way, because a traceback exits 1 too. Only the JSON
    tells them apart, so the JSON is what is tested: `--format json` always
    prints at least `[]`, so stdout that will not parse is a run that did not
    finish. This read empty stdout as `[]` with `note=None` — "verify failures:
    0" for a check that died, and that zero is committed to BACKLOG.md. A
    *directory* named `login.feature` is enough to get there, because
    verify_links globs `*.feature` and `read_text` raises on one. SEC-007 closed
    this shape in `security_bucket`; this is the sibling it did not reach
    (SPEC-028 — the note is what separates "clean" from "never ran").
    """
    try:
        out = subprocess.run(
            [sys.executable, str(_VERIFY_LINKS), "--dir", _specs_dir(project_dir), "--format", "json"],
            capture_output=True, text=True)
        errors = json.loads(out.stdout)
    except (OSError, ValueError):
        # ValueError, not json.JSONDecodeError: it covers that one (a subclass), the empty
        # stdout of a gate that died before printing, and the UnicodeDecodeError `text=True`
        # raises on an undecodable byte — the trap the two buckets below name.
        return [], "verify_links returned no result — link integrity was not checked"
    if not isinstance(errors, list):
        return [], "verify_links returned no list of errors — link integrity was not checked"
    return errors, None


def stale_bucket(project_dir):
    """Behaviors in behavior.json whose fingerprint freshness != current HEAD."""
    path = os.path.join(project_dir, "knowledge-base", ".graph", "behavior.json")
    if not os.path.exists(path):
        return [], "no behavior.json — run behavior-graph --build"
    try:
        with open(path, encoding="utf-8") as f:
            behaviors = json.load(f).get("behaviors", {})
    except (OSError, ValueError):
        # ValueError, not json.JSONDecodeError: that is already a ValueError, and the wider
        # clause also catches the UnicodeDecodeError one non-UTF-8 byte raises out of the read.
        # SEC-008 was the same mistake in the other direction — `except OSError` over a decode
        # — and it turned a swallowed error into an uncaught traceback.
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


#: The settled half of findings-schema.md's `status` vocabulary. `open` is
#: outstanding; these two are dispositions somebody actually recorded. A fourth
#: value is not a fourth disposition — it is a value this consumer was never
#: told how to read, and the schema's "consumers treat any finding whose status
#: is not `open` as not outstanding" is a rule about the three values it fixes,
#: not a licence to accept a fourth in silence.
_SETTLED_STATUSES = frozenset({"resolved", "intentional"})

#: How many unreadable findings the note names before it stops listing them.
#: The count stays whole and only the list is capped, for the reason
#: GAPS_SAMPLE exists (SPEC-029): this note now reaches the git-tracked
#: BACKLOG.md, and an index with three hundred bad rows would put three hundred
#: ids on one line of it and bury the number that matters.
UNRECOGNISED_SAMPLE = 10


def security_bucket(project_dir):
    """Open findings from findings.json — partitioned by status, never filtered by it.

    `resolved` and `intentional` are settled and left out; `open` is
    outstanding; anything else — a capitalisation, a synonym, a missing key, an
    entry that is not an object at all — is counted as OPEN and named in the
    note. This was an exact-match filter, and the drop was silent: a
    findings.json holding three high-severity findings with statuses `Open`,
    `unresolved` and none at all returned `([], None)`, which is zero findings
    and nothing to say about them. Both ends of this file are written by hand —
    an agent composing JSON against a prose schema at one end, an adopting
    project committing it at the other — so a vocabulary miss is the expected
    failure, not the exotic one.

    A silently-zero security bucket reads as CLEAN, not as NEVER SCANNED, and
    those are the same number and opposite facts. The direction to fail in is
    the alarm (ADR-005, SPEC-027).
    """
    path = os.path.join(project_dir, "knowledge-base", "security",
                        "codebase-security", "findings.json")
    if not os.path.exists(path):
        return [], "no findings.json — run codebase-security-scan"
    try:
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
    except (OSError, ValueError):
        # See the note in the behavior bucket: ValueError covers both the JSON parse failure
        # and a non-UTF-8 byte, and this bucket's whole contract is that it never answers zero
        # without saying why.
        return [], "findings.json unreadable"
    findings = data.get("findings") if isinstance(data, dict) else None
    if not isinstance(findings, list):
        # A bare top-level array, or a `findings` key holding something else.
        # The old form defaulted both to `[]`, which is indistinguishable from
        # a scan that ran and found nothing.
        return [], "findings.json carries no findings list — nothing was counted"
    out, unrecognised = [], []
    for i, x in enumerate(findings):
        if not isinstance(x, dict):
            unrecognised.append(f"entry {i}: not an object")
            continue
        status = x.get("status")
        # The isinstance test is not tidiness. `status` is project-supplied
        # JSON, so it can be a list or a dict, and an unhashable value tested
        # against a frozenset raises TypeError out of the whole census — the one
        # thing every bucket in this module promises never to do (SPEC-028).
        if isinstance(status, str) and status in _SETTLED_STATUSES:
            continue
        if status != "open":
            label = x.get("id") or f"entry {i}"
            unrecognised.append(f"{label}: " + ("missing" if status is None else repr(status)))
        out.append({"id": x.get("id"), "title": x.get("title"),
                    "severity": x.get("severity"), "file": x.get("file")})
    if unrecognised:
        named = "; ".join(unrecognised[:UNRECOGNISED_SAMPLE])
        if len(unrecognised) > UNRECOGNISED_SAMPLE:
            named += f"; and {len(unrecognised) - UNRECOGNISED_SAMPLE} more"
        return out, (f"{len(unrecognised)} finding(s) carry a status this report does not "
                     f"recognise ({named}) — counted as open")
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


def _line(value):
    r"""A project-supplied string rendered on one markdown line, outside a table.

    Only the newline is collapsed, because only the newline ends something out
    here. A `|` is ordinary text in a list item, and a backtick inside a code
    span costs one ugly line — which is cheaper than a lossy transform on a path
    the reader is meant to be able to select and copy.
    """
    text = "" if value is None else str(value)
    return text.replace("\r", " ").replace("\n", " ")


def _cell(value):
    r"""One markdown table cell from a project-supplied string.

    Two characters end something in a table. `|` ends the cell: a title holding
    one renders a five-cell row under a three-cell header and pushes the last
    column off the end, so a behavior loses its spec attribution. A newline ends
    the whole *table*, and that is the half that matters. Spec frontmatter
    cannot carry one — that parser is line-oriented (frontmatter.py
    `_logical_lines`) — but finding titles come from findings.json, which is
    JSON and git-tracked, and a JSON string holds whatever it likes. Reproduced
    2026-08-23: a finding titled "RCE |\n\n_None._\n\n## Notes\n\nNothing
    outstanding." ended the open-findings table after one truncated row, printed
    `_None._` beneath it and forged a `## Notes` heading — a security section
    that reads as clean, in a tracked artifact whose own banner tells the reader
    not to edit it and therefore to trust it.

    **The backslash goes first, and the order is the whole fix.** Escaping only
    the pipe is a bypass, not a defence: GFM's row scanner consumes a backslash
    together with the character after it (GFM spec §4.10, tables), and
    CommonMark §2.4 makes `\\` a literal backslash rather than a shield — so a
    `|` is a delimiter exactly when an EVEN number of backslashes precedes it.
    A title already holding `\|` therefore came out of the pipe-only escaper as
    `\\|`, which is a literal backslash followed by a live delimiter, and the
    attacker got back the extra column the fix was written to take away.
    Reproduced 2026-08-23 against the pipe-only version: a finding titled
    `benign \| EXTRA-CELL` rendered as `benign \` / `EXTRA-CELL`, and `x.py`
    was pushed past the four-column header and discarded. Escaping the
    backslash first makes that title `\\\|` — literal backslash, escaped pipe —
    and the File column survives. The two `replace` calls do not commute, and
    the test that guards them splits rows by GFM's rule rather than by this
    function's (`test_collect_status.py:gfm_cells`), because an oracle that
    reuses the escaper's own rule is how the pipe-only version passed.
    """
    return _line(value).replace("\\", "\\\\").replace("|", "\\|")


def render_backlog(status):
    """Render BACKLOG.md markdown from a status dict."""
    c = status["behavior_counts"]
    intent = status["intent_worklist"]
    owed = status["test_owed_worklist"]
    gaps = status["gaps"]
    sec = status["open_security_findings"]
    L = ["# Backlog", "",
         "> Generated by the `freya-status` skill — **do not edit**; re-run it to refresh.",
         "",
         (f"**Census:** {c['proposed']} proposed · {c['confirmed']} confirmed · "
          f"{c['accepted']} accepted · {len(owed)} tests owed · {len(sec)} open findings · "
          f"{gaps['total']} coverage gaps"),
         ""]

    # The census line is a row of numbers, and a number is only worth what its
    # source was worth. `collect` already returns a note for every source it
    # could not read — SPEC-028 calls that note the thing that separates "0 open
    # findings" from "no scan has ever run" — and this renderer dropped that
    # half, in the one rendering that is committed and read in a PR diff. A
    # project with no findings.json wrote "0 open findings" and `_None._` under
    # Open security findings and said nothing about never having scanned.
    notes = status.get("notes") or []
    if notes:
        L += ["> **This census could not read every source** — a section below may be",
              "> empty because its input was missing, not because it is clean.",
              ">"]
        L += [f"> - {_line(n)}" for n in notes]
        L.append("")

    L += ["## Behaviors to confirm", ""]
    if intent:
        L += ["| Behavior | Title | Spec |", "|---|---|---|"]
        L += [f"| {_cell(r['behavior_id'])} | {_cell(r.get('title'))} | "
              f"{_cell(r.get('spec_id'))} |" for r in intent]
    else:
        L.append("_None._")
    L.append("")

    L += ["## Tests owed", ""]
    if owed:
        L += ["| Behavior | Title | Spec |", "|---|---|---|"]
        L += [f"| {_cell(r['behavior_id'])} | {_cell(r.get('title'))} | "
              f"{_cell(r.get('spec_id'))} |" for r in owed]
    else:
        L.append("_None._")
    L.append("")

    L += ["## Coverage gaps", ""]
    L.append(f"{gaps['total']} uncovered source file(s)." + (" Sample:" if gaps["sample"] else ""))
    L += [f"- `{_line(f)}`" for f in gaps["sample"]]
    L.append("")

    L += ["## Open security findings", ""]
    if sec:
        L += ["| ID | Severity | Title | File |", "|---|---|---|---|"]
        L += [f"| {_cell(f.get('id'))} | {_cell(f.get('severity'))} | "
              f"{_cell(f.get('title'))} | {_cell(f.get('file'))} |"
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
