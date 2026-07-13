# SP4 — Status & Backlog Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** A read-only `status` skill that aggregates outstanding behavior/coverage/security work and regenerates a git-tracked `knowledge-base/BACKLOG.md`, backed by a `behavior-graph --gaps` query and a structured `findings.json` security index.

**Architecture:** A new `status` skill whose deterministic core (`collect_status.py`) assembles buckets from existing sources (specs via the frontmatter parser; `behavior-graph --gaps`; `verify_links.py`; `behavior.json`; `findings.json`), each degrading independently, and renders `BACKLOG.md`. `behavior-graph` gains a `--gaps` query (sharing a factored-out `_covered` with `surface`). `codebase-security-scan` emits `findings.json` alongside its prose report. Two one-at-a-time worklists (in the status skill) drain the proposed/confirmed tail.

**Tech Stack:** Python 3.12, stdlib only (`unittest`, `unittest.mock`, `subprocess`, `json`). Tests are `unittest` modules run with `python test_<name>.py` from the script's own directory. Skills auto-discover from `skills/<name>/SKILL.md` (no manifest edit needed).

## Global Constraints

- **Stdlib-only Python** — no new imports beyond the standard library (importing the sibling `frontmatter` module is fine; it's part of this plugin).
- **`status` is read-only and never blocks** — exit 0 always; it is a report. Its only write is `knowledge-base/BACKLOG.md` under `--write-backlog`.
- **Every source degrades independently** — a missing `behavior.json` / `findings.json` / graph / specs yields an empty bucket plus a `note`, never a crash or non-zero exit.
- **`BACKLOG.md` is generated at `knowledge-base/BACKLOG.md`**, never hand-edited (header says so), git-tracked.
- **`_covered` is shared** — `surface` and `gaps` must compute coverage with the same helper (`exercises` paths ∪ declared `entry` values) so they cannot drift.
- **`verify_links.py` exits non-zero when it finds errors** — `collect_status` must capture its stdout JSON WITHOUT `check=True` (else a normal "errors found" run is lost as a CalledProcessError).
- **Worklists reuse the SP1 state bumps** (`proposed → confirmed → accepted`) and never auto-author a test.
- **`findings.json`** lives at `knowledge-base/security/codebase-security/findings.json`; schema in §Task 2. It is the substrate SP5 enriches — do not add cross-reference logic here.
- **Production webapp `/Users/main/Documents/areas/viva-croatia/webapp/` is OFF-LIMITS.** The dogfood uses only the testbed `/Users/main/Documents/projects/viva-croatia-testbed`.

---

### Task 1: `behavior-graph --gaps` + shared `_covered`

Add a whole-repo uncovered-code query, factoring the coverage computation out of `surface` so the two share it.

**Files:**
- Modify: `skills/behavior-graph/scripts/behavior_graph.py` (extract `_covered`; add `gaps`; CLI)
- Test: `skills/behavior-graph/scripts/test_behavior_graph.py` (add to `SurfaceTest`)

**Interfaces:**
- Consumes (existing): `_graph_files(project_dir) -> set`, `load_behavior_json`, `run_behaviors.load_behaviors`.
- Produces:
  - `_covered(behaviors, specs_behaviors) -> set[str]` — `exercises` paths ∪ declared `entry` values.
  - `gaps(project_dir) -> dict` — `{version, gaps: [sorted uncovered paths], total, note?}`.
  - CLI: `--gaps` (mutually exclusive group).

- [ ] **Step 1: Write the failing tests**

Add these methods to the existing `SurfaceTest` class in `skills/behavior-graph/scripts/test_behavior_graph.py` (it already builds a fixture with `graph.json` files `lib/webauthn.ts`, `app/api/x/route.ts`, `app/api/posts/lock.ts`, `lib/util.ts`; `behavior.json` with accepted BEH-002 exercising `lib/webauthn.ts` and confirmed BEH-006 exercising `app/api/x/route.ts`; and specs declaring entries `app/api/x/route.ts` (BEH-006) and `app/api/posts/lock.ts` (BEH-004)):

```python
    def test_covered_union_of_exercises_and_entries(self):
        behaviors = {"X": {"exercises": [{"path": "a.ts"}]}}
        specs_behaviors = [{"entry": "b.ts"}, {"entry": None}, {}]
        self.assertEqual(behavior_graph._covered(behaviors, specs_behaviors), {"a.ts", "b.ts"})

    def test_gaps_lists_uncovered_source_files(self):
        # graph files: webauthn, x/route, posts/lock, util.
        # covered: webauthn (BEH-002 exercise), x/route (BEH-006 exercise+entry),
        #          posts/lock (BEH-004 entry). Only lib/util.ts is uncovered.
        r = behavior_graph.gaps(self.proj)
        self.assertEqual(r["gaps"], ["lib/util.ts"])
        self.assertEqual(r["total"], 1)

    def test_gaps_no_graph_degrades_to_note(self):
        import shutil
        shutil.rmtree(os.path.join(self.proj, "knowledge-base", ".graph"))
        r = behavior_graph.gaps(self.proj)
        self.assertIn("note", r)
        self.assertEqual(r["gaps"], [])
        self.assertEqual(r["total"], 0)
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `cd skills/behavior-graph/scripts && python test_behavior_graph.py -k SurfaceTest`
Expected: FAIL — `AttributeError: module 'behavior_graph' has no attribute '_covered'` / `'gaps'`.

- [ ] **Step 3: Extract `_covered` and use it in `surface`**

In `skills/behavior-graph/scripts/behavior_graph.py`, add this helper just before `def surface`:

```python
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
```

Then in `surface`, replace the inline covered block (the final block before `return result`):

```python
    covered = set()
    for rec in behaviors.values():
        for e in rec.get("exercises", []):
            covered.add(e["path"])
    for b in specs_behaviors:
        if b.get("entry"):
            covered.add(b["entry"])
    result["recall_gaps"] = sorted(f for f in changed if f in graph_files and f not in covered)
    return result
```

with:

```python
    covered = _covered(behaviors, specs_behaviors)
    result["recall_gaps"] = sorted(f for f in changed if f in graph_files and f not in covered)
    return result
```

- [ ] **Step 4: Add `gaps`**

In `skills/behavior-graph/scripts/behavior_graph.py`, add after `surface`:

```python
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
```

- [ ] **Step 5: Wire the CLI**

In `main`, add `--gaps` to the mutually exclusive group (alongside `--build`/`--affected`/`--implements`/`--check`/`--surface`):

```python
    group.add_argument("--gaps", action="store_true",
                       help="Whole-repo uncovered-code audit (source files no behavior covers).")
```

And handle it — add this block right before the existing `if args.surface:` block:

```python
    if args.gaps:
        print(json.dumps(gaps(args.project), indent=2))
        return 0
```

- [ ] **Step 6: Run the tests to verify they pass (and nothing regressed)**

Run: `cd skills/behavior-graph/scripts && python test_behavior_graph.py`
Expected: PASS — the new `_covered`/`gaps` tests, the existing `SurfaceTest` (now using the factored helper), and all other classes.

- [ ] **Step 7: Commit**

```bash
git add skills/behavior-graph/scripts/behavior_graph.py skills/behavior-graph/scripts/test_behavior_graph.py
git commit -m "feat(behavior-graph): --gaps whole-repo coverage audit (shared _covered with surface)"
```

---

### Task 2: `findings.json` security index

Make `codebase-security-scan` emit a machine-readable findings index alongside its prose report, with a documented schema.

**Files:**
- Create: `skills/codebase-security-scan/references/findings-schema.md`
- Modify: `skills/codebase-security-scan/SKILL.md` (report-generation steps)

**Interfaces:**
- Produces: `knowledge-base/security/codebase-security/findings.json` (schema below). Consumed by SP4's `collect_status.py` (Task 3, reads `status == "open"`).

- [ ] **Step 1: Write the schema reference**

Create `skills/codebase-security-scan/references/findings-schema.md`:

````markdown
# findings.json schema

A machine-readable index of the current security findings, written **alongside**
the prose report at `knowledge-base/security/codebase-security/findings.json`
whenever a report is generated or updated. It lets other skills (e.g.
`/freya-devkit:status`) read findings without parsing prose. Git-tracked.

```json
{
  "version": 1,
  "scanned_commit": "<git HEAD short hash at scan time>",
  "report": "knowledge-base/security/codebase-security/<YYYY-MM-DD>.md",
  "findings": [
    {
      "id": "SEC-001",
      "title": "Short finding title",
      "severity": "high | medium | low | info",
      "status": "open | resolved | intentional",
      "file": "src/path/to/file.ts",
      "line": 42,
      "spec_ref": "SPEC-001"
    }
  ]
}
```

Field rules:
- `id` — stable per finding across re-scans (matches the prose report's finding id).
- `severity` — one of `high`/`medium`/`low`/`info`.
- `status`:
  - `open` — a live finding needing attention.
  - `resolved` — fixed/no longer present (lifecycle RESOLVED).
  - `intentional` — explained by a declarative spec decision (the existing
    `check-specs` cross-reference); `spec_ref` names that spec.
- `file` / `line` — primary location (`line` optional).
- `spec_ref` — the spec marking it intentional, when known (optional).

Consumers treat any finding whose `status` is not `open` as not outstanding.
The list mirrors the prose report's findings exactly — same ids, same statuses.
````

- [ ] **Step 2: Add the emit step to the scan SKILL.md**

In `skills/codebase-security-scan/SKILL.md`, find the report-generation description (the step that says to save the report to `/knowledge-base/security/codebase-security/YYYY-MM-DD.md`, near the "Report Generation" step and the `update`/`audit` report-writing steps). After the report-save instruction, add this subsection (place it once, where report generation is described — if multiple modes describe report-writing, add a single shared subsection and reference it):

````markdown
#### Also emit `findings.json` (structured index)

Whenever you write or update the prose report, also write a machine-readable
index at `knowledge-base/security/codebase-security/findings.json` following
`references/findings-schema.md`. It mirrors the report's findings exactly —
one entry per finding with `id`, `title`, `severity`, `status`
(`open`/`resolved`/`intentional`), `file`, optional `line`, and `spec_ref`
when a spec marks the finding intentional. This lets `/freya-devkit:status`
and the backlog surface open findings without parsing prose. Overwrite it on
each report write (no dated suffixes — it always reflects the latest report).
````

- [ ] **Step 3: Verify placement + provide a validating example**

Run: `cd /Users/main/Documents/projects/freya-devkit && grep -n "findings.json" skills/codebase-security-scan/SKILL.md skills/codebase-security-scan/references/findings-schema.md`
Expected: the schema doc exists and the SKILL.md references `findings.json` in its report-generation section. Visually confirm the emit subsection sits with the report-writing step and the path matches the schema doc.

- [ ] **Step 4: Commit**

```bash
git add skills/codebase-security-scan/references/findings-schema.md skills/codebase-security-scan/SKILL.md
git commit -m "feat(codebase-security-scan): emit structured findings.json index + schema"
```

---

### Task 3: `collect_status.py` — the status aggregator

The deterministic core of the new `status` skill: assemble every bucket and render `BACKLOG.md`.

**Files:**
- Create: `skills/status/scripts/collect_status.py`
- Test: `skills/status/scripts/test_collect_status.py`

**Interfaces:**
- Consumes: `frontmatter.parse_frontmatter` + `frontmatter.BEHAVIOR_STATES` (spec-manager); `behavior-graph --gaps` and `verify_links.py` via subprocess; `behavior.json` and `findings.json` via file read.
- Produces:
  - `behavior_census(project_dir) -> (counts: dict, intent: list, test_owed: list)` — resolves `<project_dir>/knowledge-base/specs` if it exists, else treats the arg as the specs dir directly (so tests can pass a specs dir).
  - `gaps_bucket(project_dir) -> (dict{total, sample}, note|None)`; `verify_bucket`, `stale_bucket`, `security_bucket` → `(value, note|None)`.
  - `collect(project_dir) -> dict` with keys `version, project, behavior_counts, intent_worklist, test_owed_worklist, gaps, verify_failures, stale_fingerprints, open_security_findings, notes`.
  - `render_backlog(status) -> str`; `write_backlog(project_dir, status) -> path`.
  - CLI: `--project` (required), `--format json|text`, `--write-backlog`.

- [ ] **Step 1: Write the failing tests**

Create `skills/status/scripts/test_collect_status.py`:

```python
#!/usr/bin/env python3
"""Proof suite for collect_status.py — the status aggregator."""
import json
import os
import sys
import tempfile
import unittest
import unittest.mock as mock

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import collect_status  # noqa: E402

SPEC = """---
id: SPEC-001
title: Fixture
category: features
status: implemented
certainty: 60
behaviors:
  - behavior_id: BEH-001
    title: Proposed one
    state: proposed
  - behavior_id: BEH-002
    title: Confirmed one
    state: confirmed
    entry: app/x.ts
  - behavior_id: BEH-003
    title: Accepted one
    state: accepted
    adapter: vitest
    locator: x.test.ts::t
---
# body
"""


class CensusTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.specs = os.path.join(self.tmp.name, "auth")
        os.makedirs(self.specs)
        with open(os.path.join(self.specs, "s.md"), "w") as f:
            f.write(SPEC)

    def test_counts_by_state(self):
        counts, intent, owed = collect_status.behavior_census(self.tmp.name)
        self.assertEqual(counts["proposed"], 1)
        self.assertEqual(counts["confirmed"], 1)
        self.assertEqual(counts["accepted"], 1)

    def test_intent_worklist_is_proposed_with_certainty(self):
        _c, intent, _o = collect_status.behavior_census(self.tmp.name)
        self.assertEqual([r["behavior_id"] for r in intent], ["BEH-001"])
        self.assertEqual(intent[0]["certainty"], 60)  # inherited from parent spec

    def test_test_owed_worklist_is_confirmed(self):
        _c, _i, owed = collect_status.behavior_census(self.tmp.name)
        self.assertEqual([r["behavior_id"] for r in owed], ["BEH-002"])

    def test_missing_specs_dir_is_empty(self):
        counts, intent, owed = collect_status.behavior_census("/no/such/dir")
        self.assertEqual(sum(counts.values()), 0)
        self.assertEqual(intent, [])


class SecurityBucketTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.d = os.path.join(self.tmp.name, "knowledge-base", "security", "codebase-security")
        os.makedirs(self.d)

    def _write(self, obj):
        with open(os.path.join(self.d, "findings.json"), "w") as f:
            json.dump(obj, f)

    def test_open_findings_only(self):
        self._write({"version": 1, "findings": [
            {"id": "SEC-001", "title": "a", "severity": "high", "status": "open", "file": "x.ts"},
            {"id": "SEC-002", "title": "b", "severity": "low", "status": "resolved", "file": "y.ts"},
            {"id": "SEC-003", "title": "c", "severity": "medium", "status": "intentional", "file": "z.ts"},
        ]})
        out, note = collect_status.security_bucket(self.tmp.name)
        self.assertIsNone(note)
        self.assertEqual([f["id"] for f in out], ["SEC-001"])

    def test_missing_findings_is_note(self):
        out, note = collect_status.security_bucket(self.tmp.name)
        self.assertEqual(out, [])
        self.assertIsNotNone(note)


class StaleBucketTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.gdir = os.path.join(self.tmp.name, "knowledge-base", ".graph")
        os.makedirs(self.gdir)

    def _write(self, behaviors):
        with open(os.path.join(self.gdir, "behavior.json"), "w") as f:
            json.dump({"version": 1, "behaviors": behaviors}, f)

    def test_stale_when_freshness_differs_from_head(self):
        self._write({"BEH-002": {"exercises": [{"path": "a.ts", "freshness": "oldcommit"}]}})
        with mock.patch.object(collect_status, "_git_head", return_value="newcommit"):
            stale, note = collect_status.stale_bucket(self.tmp.name)
        self.assertEqual(stale, ["BEH-002"])

    def test_fresh_when_matches_head(self):
        self._write({"BEH-002": {"exercises": [{"path": "a.ts", "freshness": "head1"}]}})
        with mock.patch.object(collect_status, "_git_head", return_value="head1"):
            stale, note = collect_status.stale_bucket(self.tmp.name)
        self.assertEqual(stale, [])

    def test_missing_behavior_json_is_note(self):
        import shutil
        shutil.rmtree(self.gdir)
        stale, note = collect_status.stale_bucket(self.tmp.name)
        self.assertEqual(stale, [])
        self.assertIsNotNone(note)


class CollectAndRenderTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        os.makedirs(os.path.join(self.tmp.name, "knowledge-base", "specs", "auth"))
        with open(os.path.join(self.tmp.name, "knowledge-base", "specs", "auth", "s.md"), "w") as f:
            f.write(SPEC)

    def _collect(self):
        # mock the subprocess-backed buckets to keep this hermetic
        with mock.patch.object(collect_status, "gaps_bucket",
                               return_value=({"total": 2, "sample": ["a.ts", "b.ts"]}, None)), \
             mock.patch.object(collect_status, "verify_bucket", return_value=([], None)), \
             mock.patch.object(collect_status, "stale_bucket", return_value=([], None)), \
             mock.patch.object(collect_status, "security_bucket",
                               return_value=([{"id": "SEC-001", "title": "a", "severity": "high", "file": "x.ts"}], None)):
            return collect_status.collect(self.tmp.name)

    def test_collect_assembles_all_buckets(self):
        s = self._collect()
        self.assertEqual(s["behavior_counts"]["proposed"], 1)
        self.assertEqual(len(s["intent_worklist"]), 1)
        self.assertEqual(len(s["test_owed_worklist"]), 1)
        self.assertEqual(s["gaps"]["total"], 2)
        self.assertEqual(len(s["open_security_findings"]), 1)

    def test_render_backlog_has_sections_and_generated_header(self):
        md = collect_status.render_backlog(self._collect())
        self.assertIn("do not edit", md.lower())
        self.assertIn("Behaviors to confirm", md)
        self.assertIn("Tests owed", md)
        self.assertIn("Coverage gaps", md)
        self.assertIn("Open security findings", md)
        self.assertIn("BEH-001", md)   # the proposed behavior listed

    def test_write_backlog_writes_file(self):
        s = self._collect()
        path = collect_status.write_backlog(self.tmp.name, s)
        self.assertTrue(path.endswith(os.path.join("knowledge-base", "BACKLOG.md")))
        self.assertTrue(os.path.exists(path))


if __name__ == "__main__":
    unittest.main(verbosity=2)
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `cd skills/status/scripts && python test_collect_status.py`
Expected: FAIL — `ModuleNotFoundError: No module named 'collect_status'`.

- [ ] **Step 3: Write `collect_status.py`**

Create `skills/status/scripts/collect_status.py`:

```python
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
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `cd skills/status/scripts && python test_collect_status.py`
Expected: PASS — all classes (census, security, stale, collect/render/write), output pristine.

Note: the test mocks `gaps_bucket`/`verify_bucket`/`stale_bucket`/`security_bucket` in the collect test, and `behavior_census` accepts the specs-dir-or-project-root resolution, so no subprocess runs in the suite.

- [ ] **Step 5: Smoke-test against the testbed (read-only)**

Run:
```bash
cd /Users/main/Documents/projects/freya-devkit
python skills/status/scripts/collect_status.py --project /Users/main/Documents/projects/viva-croatia-testbed --format text
```
Expected: a status summary with non-zero accepted count (testbed has accepted BEH-002/003) and any notes (e.g. no findings.json yet). Read-only; do not commit testbed state.

- [ ] **Step 6: Commit**

```bash
git add skills/status/scripts/collect_status.py skills/status/scripts/test_collect_status.py
git commit -m "feat(status): collect_status.py — aggregate buckets + render BACKLOG.md"
```

---

### Task 4: `status` skill + wrap-up backlog refresh

Document the new `status` skill (command + worklists) and have `wrap-up` regenerate `BACKLOG.md` in its artifacts commit.

**Files:**
- Create: `skills/status/SKILL.md`
- Modify: `skills/wrap-up/SKILL.md` (Phase 5 artifacts — regenerate + stage `BACKLOG.md`)

**Interfaces:**
- Consumes: `collect_status.py` (Task 3) — `--format text|json`, `--write-backlog`.
- Produces: the documented `status` skill (no code interface).

- [ ] **Step 1: Create the `status` SKILL.md**

Create `skills/status/SKILL.md`:

````markdown
---
name: status
description: |
  Read-only project status: aggregate outstanding behavior/coverage/security work
  (behaviors to confirm, tests owed, coverage gaps, open security findings) and
  refresh the git-tracked knowledge-base/BACKLOG.md. The check-counterpart of wrap-up.

  TRIGGER when: asking "where do I stand", "what's outstanding", "what's left to do",
  refreshing the backlog, or working the intent/test-owed worklists.
---

# Status

The read-only **check** counterpart of `/freya-devkit:wrap-up` (which *does/syncs*).
`status` mutates nothing except, on request, the generated `knowledge-base/BACKLOG.md`.

## Commands

| Command | Description |
|---------|-------------|
| `status` | Print the status summary and refresh `BACKLOG.md` |
| `status --no-backlog` | Print the summary only (don't rewrite `BACKLOG.md`) |
| `gaps` | List whole-repo uncovered source files |
| `review intent` | Work the proposed → confirm worklist, one at a time |
| `review tests` | Work the confirmed → write-a-test worklist, one at a time |

### `status`

Run the aggregator and refresh the backlog:
```bash
python "${CLAUDE_PLUGIN_ROOT}/skills/status/scripts/collect_status.py" \
  --project . --format text --write-backlog
```
It reports a census (`proposed / confirmed / accepted / quarantined / deprecated`),
the two worklist sizes, coverage gaps, Tier-1 verify failures, stale fingerprints,
and open security findings — each source degrades to a `note` if unavailable, and
the command never blocks. It (re)writes `knowledge-base/BACKLOG.md`. For the
machine-readable form use `--format json`; to skip the backlog write, omit
`--write-backlog`.

### `gaps`

Whole-repo uncovered-code audit (source files no behavior exercises or declares as
an `entry`):
```bash
python "${CLAUDE_PLUGIN_ROOT}/skills/behavior-graph/scripts/behavior_graph.py" \
  --gaps --project .
```
Use it to find code with no captured intent — candidates to capture a behavior for.

### `review intent` (proposed → confirm)

Work the **intent worklist** one behavior at a time (certainty-sorted, lowest
first — read `intent_worklist` from `status --format json`). For each `proposed`
behavior: re-read its code, present it, then **confirm** (bump `state`
`proposed → confirmed` in the spec frontmatter), **edit then confirm**,
**quarantine/deprecate**, or **skip**. Stop whenever the engineer wants. This is
how the cold tail (behaviors never touched by work, so never surfaced by wrap-up's
validate-on-hit) gets drained on purpose.

### `review tests` (confirmed → accept)

Work the **test-owed worklist** one behavior at a time (read `test_owed_worklist`).
For each `confirmed` behavior: link or write its test, and once a real passing
linked test exists, bump `state` `confirmed → accepted` (the wrap-up regression
gate then governs it). Never auto-author a test — that is the engineer's work.

## BACKLOG.md

`status` regenerates **`knowledge-base/BACKLOG.md`** — a generated, git-tracked,
never-hand-edited view of what's outstanding (behaviors to confirm, tests owed,
coverage gaps, open security findings). It is to intent+security completeness what
a coverage report is to test coverage: it diffs in PRs so the team sees the
backlog without running anything. `wrap-up` also regenerates it in its artifacts
commit, so it stays current.

## When to use

- After pulling changes, or before planning, to see what intent/tests/findings are outstanding.
- To work the tail deliberately (the worklists) rather than waiting for validate-on-hit.
- `status` is read-only; use `/freya-devkit:wrap-up` to actually sync/commit.
````

- [ ] **Step 2: Add the backlog refresh to wrap-up's artifacts phase**

In `skills/wrap-up/SKILL.md`, in `### Phase 5: Artifacts Commit`, in the list of artifacts to stage (step 1, which lists "Updated docs / Updated specs / Security report / Updated dependency graph / Tracking files / proposed scaffolds"), add a step before staging to regenerate the backlog, and add `BACKLOG.md` to the staged set. Insert at the start of Phase 5 (before "Stage all artifact changes"):

````markdown
0. **Refresh the backlog.** Regenerate the generated, git-tracked backlog so it
   reflects the just-synced state:
   ```bash
   python "${CLAUDE_PLUGIN_ROOT}/skills/status/scripts/collect_status.py" \
     --project . --write-backlog >/dev/null
   ```
   Stage `knowledge-base/BACKLOG.md` with the other artifacts below.
````

And add `knowledge-base/BACKLOG.md` to the artifact list in step 1 of Phase 5 (the bulleted "Stage all artifact changes" list).

- [ ] **Step 3: Verify**

Run:
```bash
cd /Users/main/Documents/projects/freya-devkit
test -f skills/status/SKILL.md && head -5 skills/status/SKILL.md
grep -n "BACKLOG\|collect_status" skills/wrap-up/SKILL.md
```
Expected: the status SKILL.md exists with valid frontmatter (`name: status`); wrap-up Phase 5 references the backlog refresh + staging.

- [ ] **Step 4: Commit**

```bash
git add skills/status/SKILL.md skills/wrap-up/SKILL.md
git commit -m "feat(status): status skill (command + worklists); wrap-up refreshes BACKLOG.md"
```

---

## Dogfooding pass (manual — run after Task 4, not a TDD task)

Validate on the **testbed**, reusing the `dogfood/sp2-bootstrap` branch (proposed BEH-004–008 in `SPEC-002`, accepted BEH-002/003 in `SPEC-001`). Production webapp stays untouched.

- [ ] **D1 — status census + worklists.** `git checkout dogfood/sp2-bootstrap` in the testbed; run `collect_status.py --project <testbed> --format text`. Expect: proposed count ≥ 5 (the post-locking behaviors), accepted ≥ 2, an intent worklist listing BEH-004–008, and notes for any missing source (e.g. findings.json).
- [ ] **D2 — gaps.** Run `behavior-graph --gaps --project <testbed>`. Confirm it returns a plausible set of uncovered source files (the testbed is mostly unspecced) and does not list any file that is a declared `entry` or in an `exercises` edge.
- [ ] **D3 — BACKLOG.md.** Run `collect_status.py --project <testbed> --write-backlog` on a testbed branch; open `knowledge-base/BACKLOG.md` and confirm all sections render, the "do not edit" header is present, and the census line is accurate.
- [ ] **D4 — findings.json + security bucket.** Run `/freya-devkit:codebase-security-scan update` (or hand-write a small `findings.json` per the schema if a full scan is too heavy) on the testbed branch; re-run `status` and confirm `open` findings appear in the summary and `BACKLOG.md`.
- [ ] **D5 — worklist move.** Confirm one intent-worklist item (bump a proposed BEH to `confirmed` in its spec); re-run `status` and confirm the census moves (proposed −1, confirmed +1) and the intent worklist shrinks.
- [ ] **D6 — Log friction** in `docs/design/behavior-layer/dogfooding-notes.md` (new SP4 entry). Restore the testbed to `main`; retain the dogfood branch.

---

## Final whole-branch review

After Task 4 and the dogfood, dispatch the final whole-branch review (superpowers:requesting-code-review) over the SP4 commits (base = the SP4 plan commit), pointing it at any Minor findings recorded in the ledger. Continue on `feat/behavior-layer` — do **not** merge (SP5 remains).
