# P4b — Declarative-drift check Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a code-vs-declared-intent drift check at wrap-up: for a change's blast radius, judge whether the changed code contradicts a declared intent (a spec's `intentional_decisions`, or an accepted ADR) whose `related_code` it touches — resolve-to-proceed, advisory.

**Architecture:** New `drift.py` mirrors `principles.py`/`contradictions.py`. It reuses the Direction-A blast-radius chain (`git diff $BASE..HEAD` → code-graph `--impact` → intersect) but intersects `related_code` instead of behaviors' `exercises`. Deterministic gather (`context`) + resolution log (`resolve`/`prior`, append-only `drift-resolutions.jsonl` keyed `(item, path)`) + on-demand honesty view (`gaps`). The drift JUDGMENT is agent work in wrap-up SKILL.md (step 7).

**Tech Stack:** Python 3.12 stdlib only (`unittest`, `argparse`, `json`, `subprocess`, `pathlib`). Markdown skill docs.

## Global Constraints

- **Stdlib-only Python** — zero third-party imports.
- **Test framework:** stdlib `unittest`; each test file does `sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))` then imports siblings; ends with `unittest.main(verbosity=2)`; run via `python skills/spec-manager/scripts/test_<name>.py`.
- **Blast-radius scoped, NOT always-global** — targets are filtered by `related_code ∩ blast-radius`; an item with no `related_code` is out of drift scope (surfaced only by `gaps`).
- **Degrade, never falsely-clean** — if code-graph is unavailable, `impact_source` is `changed-only` (direct intersection), never a silent empty blast radius.
- **Verdicts** (match G2/G3): `refuted | amended | auto-cleared | superseded`. Record keyed `(item, path)`; retirement is a later `superseded` record (append-only), never a mutated field.
- **Advisory** — the check never hard-blocks on model confidence; it is resolve-to-proceed. `drift.py` itself is deterministic gather/append/lookup only.
- **Reuse, don't reinvent:** import `search_specs.load_all_specs`/`find_specs_dir`, `adr.active_adrs`, and call code-graph `graph_ops.py --impact` exactly as behavior-graph does.
- **Branch:** continue on `feat/behavior-layer` (do NOT merge). Dogfood on the testbed only; production webapp off-limits.
- **Commits** end with: `Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>`.

---

## File Structure

- **Create** `skills/spec-manager/scripts/drift.py` — `context`/`resolve`/`prior`/`gaps` + gather + resolution log.
- **Create** `skills/spec-manager/scripts/test_drift.py` — proof suite.
- **Modify** `skills/wrap-up/SKILL.md` — Phase 3.5 step 7 + staging.
- **Modify** `skills/spec-manager/SKILL.md` — "Declarative-Drift Check" procedure section (single source) + `drift` command docs.
- **Modify** `docs/design/behavior-layer/00-vision.md` + `docs/design/behavior-layer/parking-lot.md` — mark declarative-drift delivered by P4b.

---

### Task 1: `drift.py` resolution log — `resolve` / `prior`

**Files:**
- Create: `skills/spec-manager/scripts/drift.py`
- Test: `skills/spec-manager/scripts/test_drift.py`

**Interfaces:**
- Produces: `RESOLUTIONS_RELPATH`, `VERDICTS`, `append_resolution(project, record)->str`, `active_prior(project, item, paths=None)->(list, warnings)` (latest-wins per `(item, path)`, drops `superseded`, skips malformed with warning). CLI `resolve` / `prior`.

- [ ] **Step 1: Write the failing tests**

Create `skills/spec-manager/scripts/test_drift.py`:

```python
#!/usr/bin/env python3
"""Proof suite for drift.py — the P4b declarative-drift helpers."""

import json
import os
import shutil
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from drift import append_resolution, active_prior, RESOLUTIONS_RELPATH  # noqa: E402


class ResolutionsCase(unittest.TestCase):
    def _root(self):
        d = tempfile.mkdtemp()
        self.addCleanup(lambda: shutil.rmtree(d, ignore_errors=True))
        return Path(d)

    def _rec(self, verdict, item="SPEC-001", paths=None, reason="r"):
        return {"date": "2026-07-01", "item": item,
                "paths": paths or ["lib/webauthn.ts"], "verdict": verdict, "reason": reason}

    def test_append_is_append_only(self):
        root = self._root()
        append_resolution(str(root), self._rec("refuted"))
        append_resolution(str(root), self._rec("refuted", item="ADR-001", paths=["prisma/schema.prisma"]))
        lines = (root / RESOLUTIONS_RELPATH).read_text().splitlines()
        self.assertEqual(len(lines), 2)
        self.assertEqual(json.loads(lines[0])["item"], "SPEC-001")

    def test_prior_returns_active_for_item(self):
        root = self._root()
        append_resolution(str(root), self._rec("refuted", reason="model misread"))
        recs, warns = active_prior(str(root), "SPEC-001")
        self.assertEqual(len(recs), 1)
        self.assertEqual(recs[0]["reason"], "model misread")
        self.assertEqual(warns, [])

    def test_prior_filters_by_item_and_paths(self):
        root = self._root()
        append_resolution(str(root), self._rec("refuted", paths=["lib/webauthn.ts"]))
        self.assertEqual(active_prior(str(root), "SPEC-999")[0], [])                  # other item
        self.assertEqual(active_prior(str(root), "SPEC-001", paths=["other.ts"])[0], [])  # other path

    def test_superseded_retires_the_pair(self):
        root = self._root()
        append_resolution(str(root), self._rec("refuted"))
        append_resolution(str(root), self._rec("superseded", reason="code moved"))
        recs, _ = active_prior(str(root), "SPEC-001")
        self.assertEqual(recs, [])
        self.assertEqual(len((root / RESOLUTIONS_RELPATH).read_text().splitlines()), 2)  # append-only

    def test_latest_wins(self):
        root = self._root()
        append_resolution(str(root), self._rec("refuted", reason="first"))
        append_resolution(str(root), self._rec("refuted", reason="second"))
        recs, _ = active_prior(str(root), "SPEC-001")
        self.assertEqual([r["reason"] for r in recs], ["second"])

    def test_multi_path_record_dedupes(self):
        root = self._root()
        append_resolution(str(root), self._rec("refuted", paths=["a.ts", "b.ts"]))
        recs, _ = active_prior(str(root), "SPEC-001")
        self.assertEqual(len(recs), 1)  # one record, not one per path

    def test_malformed_line_skipped_with_warning(self):
        root = self._root()
        append_resolution(str(root), self._rec("refuted"))
        with (root / RESOLUTIONS_RELPATH).open("a", encoding="utf-8") as f:
            f.write("{bad json\n")
        recs, warns = active_prior(str(root), "SPEC-001")
        self.assertEqual(len(recs), 1)
        self.assertTrue(warns)


if __name__ == "__main__":
    unittest.main(verbosity=2)
```

- [ ] **Step 2: Run to verify it fails**

Run: `python skills/spec-manager/scripts/test_drift.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'drift'`.

- [ ] **Step 3: Implement**

Create `skills/spec-manager/scripts/drift.py`:

```python
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
import sys
from datetime import date as _date
from pathlib import Path

RESOLUTIONS_RELPATH = "knowledge-base/drift-resolutions.jsonl"
VERDICTS = ("refuted", "amended", "auto-cleared", "superseded")


def _resolutions_path(project):
    return Path(project) / RESOLUTIONS_RELPATH


def append_resolution(project, record):
    path = _resolutions_path(project)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as f:
        f.write(json.dumps(record, sort_keys=True) + "\n")
    return str(path)


def _load_records(project):
    """(records, warnings) — parsed JSONL lines in append order; skips bad lines."""
    path = _resolutions_path(project)
    records, warnings = [], []
    if not path.exists():
        return records, warnings
    for i, line in enumerate(
            path.read_text(encoding="utf-8", errors="replace").splitlines(), 1):
        line = line.strip()
        if not line:
            continue
        try:
            records.append(json.loads(line))
        except json.JSONDecodeError:
            warnings.append(f"skipped malformed line {i} in {RESOLUTIONS_RELPATH}")
    return records, warnings


def active_prior(project, item, paths=None):
    """Latest-active resolution per (item, path) for the given item.

    Explodes each record over its `paths`, keeps the LAST (append-order) record
    per (item, path), drops pairs whose latest verdict is `superseded`, then
    filters to the queried item/paths. De-duped so a multi-path record appears once.
    """
    records, warnings = _load_records(project)
    latest = {}  # (item, path) -> (append_idx, record)
    for idx, rec in enumerate(records):
        it = rec.get("item")
        for pth in rec.get("paths") or []:
            latest[(it, pth)] = (idx, rec)
    want = set(paths) if paths else None
    picked = {}  # append_idx -> record (de-dupe multi-path records)
    for (it, pth), (idx, rec) in latest.items():
        if rec.get("verdict") == "superseded":
            continue
        if it != item:
            continue
        if want is not None and pth not in want:
            continue
        picked[idx] = rec
    return [picked[i] for i in sorted(picked)], warnings


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
    if args.cmd == "resolve":
        _cmd_resolve(args)
    elif args.cmd == "prior":
        recs, warns = active_prior(args.project, args.item, paths=args.paths)
        for w in warns:
            print(w, file=sys.stderr)
        print(json.dumps(recs, indent=2))


if __name__ == "__main__":
    main()
```

- [ ] **Step 4: Run to verify it passes**

Run: `python skills/spec-manager/scripts/test_drift.py -v`
Expected: PASS (7 tests).

- [ ] **Step 5: Commit**

```bash
git add skills/spec-manager/scripts/drift.py skills/spec-manager/scripts/test_drift.py
git commit -m "feat(spec-manager): drift.py resolution log — resolve/prior (P4b)

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

### Task 2: `drift.py` gather — blast radius + `context`

**Files:**
- Modify: `skills/spec-manager/scripts/drift.py`
- Test: `skills/spec-manager/scripts/test_drift.py`

**Interfaces:**
- Consumes: `search_specs.load_all_specs`/`find_specs_dir`, `adr.active_adrs`, code-graph `graph_ops.py --impact`.
- Produces: `changed_files(project, base)->list`, `compute_impact(project, base)->(set, source)`, `build_drift_context(project, base, impact=None, source=None)->dict` (targets whose `related_code ∩ impact ≠ ∅`; `impact` injectable for tests). CLI `context`.

- [ ] **Step 1: Write the failing tests**

Add to `test_drift.py`. Extend the import: `from drift import append_resolution, active_prior, build_drift_context, RESOLUTIONS_RELPATH`. Add helpers + case:

```python
def _write(path, content):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def _spec(spec_id, category, decisions, related_code, status="implemented"):
    dblock = "intentional_decisions:\n" + "".join(f"  - {d}\n" for d in decisions) if decisions else ""
    rblock = "related_code:\n" + "".join(f"  - {p}\n" for p in related_code) if related_code else ""
    return (f"---\nid: {spec_id}\ntitle: {spec_id}\ncategory: {category}\n"
            f"status: {status}\ncertainty: 90\ncreated: 2026-07-01\nupdated: 2026-07-01\n"
            f"{rblock}{dblock}---\n\n# {spec_id}\n")


def _adr(root, adr_id, related_code, status="accepted", title="T"):
    d = root / "knowledge-base/decisions"
    d.mkdir(parents=True, exist_ok=True)
    rblock = "related_code:\n" + "".join(f"  - {p}\n" for p in related_code) if related_code else ""
    (d / f"{adr_id}-x.md").write_text(
        f"---\nid: {adr_id}\ntitle: {title}\nstatus: {status}\n{rblock}---\n"
        f"# {adr_id}\n## Decision\nWe do X.\n", encoding="utf-8")


class ContextCase(unittest.TestCase):
    def _root(self):
        d = tempfile.mkdtemp()
        self.addCleanup(lambda: shutil.rmtree(d, ignore_errors=True))
        return Path(d)

    def test_target_when_related_code_intersects_impact(self):
        root = self._root()
        _write(root / "knowledge-base/specs/auth/SPEC-001.md",
               _spec("SPEC-001", "auth", ["userVerification preferred"], ["lib/webauthn.ts"]))
        ctx = build_drift_context(str(root), "BASE", impact={"lib/webauthn.ts"}, source="test")
        ids = [t["item"] for t in ctx["targets"]]
        self.assertEqual(ids, ["SPEC-001"])
        self.assertEqual(ctx["targets"][0]["hit_paths"], ["lib/webauthn.ts"])
        self.assertEqual(ctx["targets"][0]["decisions"], ["userVerification preferred"])

    def test_no_target_when_no_intersection(self):
        root = self._root()
        _write(root / "knowledge-base/specs/auth/SPEC-001.md",
               _spec("SPEC-001", "auth", ["d"], ["lib/webauthn.ts"]))
        ctx = build_drift_context(str(root), "BASE", impact={"lib/other.ts"}, source="test")
        self.assertEqual(ctx["targets"], [])

    def test_excludes_deprecated_spec_and_specs_without_decisions(self):
        root = self._root()
        _write(root / "knowledge-base/specs/auth/SPEC-001.md",
               _spec("SPEC-001", "auth", ["d"], ["a.ts"], status="deprecated"))
        _write(root / "knowledge-base/specs/auth/SPEC-002.md",
               _spec("SPEC-002", "auth", [], ["a.ts"]))  # no decisions
        ctx = build_drift_context(str(root), "BASE", impact={"a.ts"}, source="test")
        self.assertEqual(ctx["targets"], [])

    def test_accepted_adr_is_target_proposed_excluded(self):
        root = self._root()
        _adr(root, "ADR-001", ["prisma/schema.prisma"], status="accepted")
        _adr(root, "ADR-002", ["prisma/schema.prisma"], status="proposed")
        ctx = build_drift_context(str(root), "BASE", impact={"prisma/schema.prisma"}, source="test")
        self.assertEqual([t["item"] for t in ctx["targets"]], ["ADR-001"])
        self.assertEqual(ctx["targets"][0]["kind"], "adr")

    def test_empty_impact_is_noop(self):
        root = self._root()
        _write(root / "knowledge-base/specs/auth/SPEC-001.md",
               _spec("SPEC-001", "auth", ["d"], ["a.ts"]))
        ctx = build_drift_context(str(root), "BASE", impact=set(), source="empty")
        self.assertEqual(ctx["targets"], [])
        self.assertEqual(ctx["impact_source"], "empty")
```

- [ ] **Step 2: Run to verify it fails**

Run: `python skills/spec-manager/scripts/test_drift.py -v`
Expected: FAIL — `ImportError: cannot import name 'build_drift_context'`.

- [ ] **Step 3: Implement**

In `drift.py`, extend the imports (add after `from pathlib import Path`):

```python
import subprocess

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from search_specs import load_all_specs, find_specs_dir  # noqa: E402
from adr import active_adrs  # noqa: E402

_GRAPH_OPS = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                          "..", "..", "code-graph", "scripts", "graph_ops.py")
```

Add these functions (after `active_prior`, before `_cmd_resolve`):

```python
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
    unavailable. `empty` when nothing changed."""
    changed = changed_files(project, base)
    if not changed:
        return set(), "empty"
    try:
        out = subprocess.run(
            [sys.executable, _GRAPH_OPS, "--impact", *changed,
             "--dir", project, "--format", "json"],
            capture_output=True, text=True, check=True).stdout
        impact = set(json.loads(out).get("all_affected") or [])
        if impact:
            return impact | set(changed), "code-graph"
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
```

Add the `context` subparser in `main()` (before `args = parser.parse_args()`):

```python
    c = sub.add_parser("context", help="Blast-radius-scoped drift targets")
    c.add_argument("--project", "-p", default=".")
    c.add_argument("--base", required=True, help="diff base (e.g. $BASE); base..HEAD")
    c.add_argument("--format", "-f", choices=["json"], default="json")
```

and its branch (before `elif args.cmd == "resolve":`):

```python
    if args.cmd == "context":
        print(json.dumps(build_drift_context(args.project, args.base), indent=2))
    elif args.cmd == "resolve":
```

(Change the existing `if args.cmd == "resolve":` to `elif args.cmd == "resolve":`.)

- [ ] **Step 4: Run to verify it passes**

Run: `python skills/spec-manager/scripts/test_drift.py -v`
Expected: PASS (12 tests).

- [ ] **Step 5: Commit**

```bash
git add skills/spec-manager/scripts/drift.py skills/spec-manager/scripts/test_drift.py
git commit -m "feat(spec-manager): drift.py gather — blast-radius context (P4b)

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

### Task 3: `drift.py` `gaps` — the honesty view

**Files:**
- Modify: `skills/spec-manager/scripts/drift.py`
- Test: `skills/spec-manager/scripts/test_drift.py`

**Interfaces:**
- Produces: `drift_gaps(project)->dict` (`{specs, adrs, warnings}` — declared items with **no** `related_code`). CLI `gaps`.

- [ ] **Step 1: Write the failing tests**

Add to `test_drift.py` (extend import: `from drift import ..., drift_gaps`). Reuse `_write`/`_spec`/`_adr`:

```python
class GapsCase(unittest.TestCase):
    def _root(self):
        d = tempfile.mkdtemp()
        self.addCleanup(lambda: shutil.rmtree(d, ignore_errors=True))
        return Path(d)

    def test_lists_decisions_without_related_code(self):
        root = self._root()
        _write(root / "knowledge-base/specs/auth/SPEC-001.md",
               _spec("SPEC-001", "auth", ["no related_code decision"], []))    # gap
        _write(root / "knowledge-base/specs/auth/SPEC-002.md",
               _spec("SPEC-002", "auth", ["scoped"], ["lib/x.ts"]))            # not a gap
        gaps = drift_gaps(str(root))
        self.assertEqual([g["item"] for g in gaps["specs"]], ["SPEC-001"])

    def test_lists_adrs_without_related_code(self):
        root = self._root()
        _adr(root, "ADR-001", [])                      # gap (no related_code)
        _adr(root, "ADR-002", ["prisma/schema.prisma"])  # not a gap
        gaps = drift_gaps(str(root))
        self.assertEqual([g["item"] for g in gaps["adrs"]], ["ADR-001"])

    def test_empty_project_no_gaps(self):
        gaps = drift_gaps(str(self._root()))
        self.assertEqual(gaps["specs"], [])
        self.assertEqual(gaps["adrs"], [])
```

- [ ] **Step 2: Run to verify it fails**

Run: `python skills/spec-manager/scripts/test_drift.py -v`
Expected: FAIL — `ImportError: cannot import name 'drift_gaps'`.

- [ ] **Step 3: Implement**

In `drift.py`, add after `build_drift_context`:

```python
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
```

Add the `gaps` subparser in `main()` (after the `context` subparser):

```python
    g = sub.add_parser("gaps", help="Declared items with no related_code (drift-blind)")
    g.add_argument("--project", "-p", default=".")
    g.add_argument("--format", "-f", choices=["json"], default="json")
```

and its branch (after the `context` branch):

```python
    elif args.cmd == "gaps":
        print(json.dumps(drift_gaps(args.project), indent=2))
```

- [ ] **Step 4: Run to verify it passes**

Run: `python skills/spec-manager/scripts/test_drift.py -v`
Expected: PASS (15 tests).

- [ ] **Step 5: Full-suite regression**

```bash
for t in drift frontmatter adr contradictions principles intent verify_intent verify_links; do
  python skills/spec-manager/scripts/test_$t.py >/dev/null 2>&1 && echo "$t OK" || echo "$t FAIL"
done
```
Expected: all `OK`.

- [ ] **Step 6: Commit**

```bash
git add skills/spec-manager/scripts/drift.py skills/spec-manager/scripts/test_drift.py
git commit -m "feat(spec-manager): drift.py gaps — un-scopable intent honesty view (P4b)

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

### Task 4: wrap-up SKILL.md — Phase 3.5 step 7

**Files:**
- Modify: `skills/wrap-up/SKILL.md`

Deliverable: wrap-up runs the declarative-drift check as an advisory, resolve-to-proceed step 7 after G3, reusing `$BASE`, staging resolutions as artifacts.

- [ ] **Step 1: Add step 7 (declarative-drift check)**

In `skills/wrap-up/SKILL.md` Phase 3.5, after the G3 contradiction check (step 6), add **step 7 — Declarative-drift check**, matching the style of steps 5/6. It must:
- Run `python "${CLAUDE_PLUGIN_ROOT}/skills/spec-manager/scripts/drift.py" context --base "$BASE" --project .` (reuse the `$BASE` from step 3).
- For each target: read the declared intent (the spec's `decisions` + its `file_path` prose, or the ADR `body`) and the **diff of the target's `hit_paths`** (`git diff $BASE..HEAD -- <hit_paths>`); judge whether the current code contradicts the declared intent.
- Resolve-to-proceed per finding: **fix the code** (no log), **amend the intent** (edit the spec decision / ADR, then `drift.py resolve --item <id> --verdict amended --reason … --paths …`), or **refute** (`--verdict refuted`). Surface `warnings` (e.g. malformed ADR).
- LLM-first triage of priors: `drift.py prior --item <id> --paths <hit_paths>` → re-validate against the current hunk; still-valid → `auto-cleared` (logged); code moved → `superseded`; new drift → escalate. Same guardrails as G2/G3 (re-judge current hunk vs the specific prior reason; bias-to-escalate; always logged; no-prior → human).
- State the posture: advisory / procedural, **never a hard-block on model confidence**; do not complete wrap-up while a finding is unresolved; fail-open on no code-graph / no targets (note `impact_source: changed-only` degrade).
- Update the ordering line to: deterministic facts (G1 + links + `adr verify` + accepted-behavior run) → G2 (step 5) → G3 (step 6) → **P4b declarative-drift (step 7)**.

- [ ] **Step 2: Staging**

In the Phase 0 behavior-aware staging table AND the Phase 5 artifacts list, add: `knowledge-base/drift-resolutions.jsonl` → **artifacts (commit 2)**, same class as the principle-/contradiction-resolutions logs.

- [ ] **Step 3: Consistency check**

Confirm every command/flag matches Task 1–3 (`drift.py context --base`, `resolve --item --verdict {refuted|amended|auto-cleared|superseded} --reason --paths`, `prior --item --paths`). Fix any drift. Note `drift.py gaps` is **on-demand and NOT part of wrap-up**.

- [ ] **Step 4: Commit**

```bash
git add skills/wrap-up/SKILL.md
git commit -m "docs(wrap-up): declarative-drift check as Phase 3.5 step 7 (P4b)

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

### Task 5: spec-manager SKILL.md — Declarative-Drift Check section

**Files:**
- Modify: `skills/spec-manager/SKILL.md`

Deliverable: a single-source "Declarative-Drift Check (governance P4b)" section (referenced by wrap-up step 7, mirroring how the G3 section is the single source), plus the `drift` command docs including the on-demand `gaps`.

- [ ] **Step 1: Add the procedure section + command docs**

In `skills/spec-manager/SKILL.md`, mirroring the existing "Contradiction Check (governance G3)" section:
- Add a **"Declarative-Drift Check (governance P4b)"** section: what it is (code-vs-declared-intent, blast-radius-scoped, advisory), the `drift.py context --base` gather, the judgment loop, resolve-to-proceed verdicts, the LLM-first prior triage, and the authority-neutral resolution (fix code / amend intent / refute). State the always-global asymmetry with G3 in one line (P4b is code-anchored → blast-radius, not global).
- Document the `drift.py` commands with full `python "${CLAUDE_PLUGIN_ROOT}/…/drift.py"` paths (match the style used for `contradictions.py`): `context --base`, `resolve`, `prior`, and **`gaps`** (on-demand: the un-scopable-intent coverage view — recommend running it periodically, not at every wrap-up).
- Add Quick Reference rows if the file has a command table: `drift gaps` (and note drift's main path is wrap-up-driven).

- [ ] **Step 2: Consistency check**

Verify commands/flags/verdicts and the `(item, path)` resolution model match Tasks 1–3. Fix any drift.

- [ ] **Step 3: Commit**

```bash
git add skills/spec-manager/SKILL.md
git commit -m "docs(spec-manager): Declarative-Drift Check (P4b) procedure + drift commands

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

### Task 6: Design-doc updates — mark declarative-drift delivered

**Files:**
- Modify: `docs/design/behavior-layer/00-vision.md`
- Modify: `docs/design/behavior-layer/parking-lot.md`

- [ ] **Step 1: Vision §8 + §9**

In `docs/design/behavior-layer/00-vision.md`:
- §8 "Declarative-drift check" paragraph — append a clause: *"— delivered by P4b (2026-07-01): a wrap-up step-7 check, blast-radius-scoped over `related_code`, resolve-to-proceed; see docs/superpowers/specs/2026-07-01-p4b-declarative-drift-design.md."*
- §9 Phase 4 line — annotate `declarative-drift checks` with `(delivered — P4b)`.

- [ ] **Step 2: Parking-lot**

In `docs/design/behavior-layer/parking-lot.md`, if a declarative-drift / Phase-4 successor note exists, mark it delivered (matching the file's resolved-item convention) with a pointer to the P4b spec. Note the remaining Phase-4 leaves: **P4c** (more adapters), **P4d** (calibrated enforcement — evidence-gated).

- [ ] **Step 3: Commit**

```bash
git add docs/design/behavior-layer/00-vision.md docs/design/behavior-layer/parking-lot.md
git commit -m "docs(behavior-layer): mark declarative-drift delivered by P4b

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

## Post-plan: dogfood + final review

After Task 6, before considering P4b done:
1. **Dogfood on the testbed** (`viva-croatia-testbed`, throwaway branch; restore `main` after): give a spec decision a `related_code` file, change that file to contradict the decision, run `drift.py context --base <BASE>` → confirm the target surfaces with correct `hit_paths`; walk resolve-to-proceed (`refute` → logged → re-run auto-clear via `prior`; `amend` → self-clears); confirm an ADR-governed file drift surfaces; confirm a change touching no declared `related_code` → no targets; confirm `drift.py gaps` lists a decision with no `related_code`; confirm `impact_source` is `code-graph` on the real graph (and degrades to `changed-only` if the graph is absent).
2. **Final whole-branch review** — dispatch the code-reviewer on the full P4b range on the most capable model.
3. Record P4b completion in the SDD ledger + parking-lot; do **not** merge `feat/behavior-layer` (standing decision).
