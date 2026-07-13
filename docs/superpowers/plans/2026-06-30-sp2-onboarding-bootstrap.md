# SP2 — Onboarding & Bootstrap Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a unified `spec-manager bootstrap` onboarding flow — detect project shape, then bootstrap a corpus of `proposed` candidate behaviors on brownfield or degrade gracefully on greenfield — backed by one deterministic shape-detector script.

**Architecture:** One new stdlib-only script (`project_shape.py`) classifies a project as `brownfield`/`greenfield`/`unknown` from code-graph's internal import-edge count plus `detect_project.py`'s stack summary, always emitting its evidence. The `bootstrap` command itself is an agent-orchestrated SKILL.md procedure (like `scan`/`update`) that sequences `init` → `code-graph build` → detect/recommend/confirm → the greenfield/brownfield branch.

**Tech Stack:** Python 3.12, stdlib only (`unittest`, `unittest.mock`, `subprocess`, `json`). No third-party deps. Tests are `unittest` modules run with `python test_<name>.py` from the script's own directory.

## Global Constraints

- **Stdlib-only Python** — no new imports beyond the standard library.
- **Inference grain is per observable behavior** — one `proposed` behavior per observable behavior/scenario (anchored to a route/entry where applicable); not per-feature, not per-route/function.
- **SP2 is the one-time bootstrap only** — no `scan --update` / re-scan command; new code acquires intent later via SP3's on-hit prompt.
- **Detect + recommend + confirm** — the detector's classification is a *recommendation*; bootstrap shows the evidence and the engineer confirms or overrides. Never silently auto-branch. `unknown` → ask outright.
- **Additive, never clobber** — on a partially-onboarded repo, bootstrap infers only for unspecced areas and never overwrites or re-infers existing specs.
- **No `.feature` scaffolds written by bootstrap** — inference produces only `proposed` behavior records in `knowledge-base/specs/`; scaffolds in the code tree appear only on acceptance.
- **`bootstrap` lives in spec-manager** (a new command), not a new top-level skill.
- **An internal edge = a resolved import** — an entry in a file's `imports` list NOT prefixed `external:` or `unresolved:`. Internal-edge count (real wiring), not raw file count, is the brownfield signal.
- **Production webapp `/Users/main/Documents/areas/viva-croatia/webapp/` is OFF-LIMITS.** The dogfooding pass uses only the testbed `/Users/main/Documents/projects/viva-croatia-testbed`.

---

### Task 1: `project_shape.py` — deterministic shape detector

A standalone script that classifies project shape from objective signals and always reports the evidence behind the call.

**Files:**
- Create: `skills/spec-manager/scripts/project_shape.py`
- Test: `skills/spec-manager/scripts/test_project_shape.py`

**Interfaces:**
- Consumes: code-graph's `graph.json` schema (`{"files": {"<rel>": {"imports": [...], ...}}}`, where an import is internal iff it does NOT start with `external:`/`unresolved:`); `detect_project.py` at `../../docs-manager/scripts/detect_project.py`, invoked as `python detect_project.py <project_dir>` → prints a JSON dict.
- Produces:
  - `count_graph(project_dir) -> tuple[int, int, bool]` — `(source_files, internal_edges, graph_present)`.
  - `run_detect_project(project_dir) -> dict` — detect_project's stack dict, `{}` on any failure.
  - `classify(project_dir) -> dict` — `{"recommendation": "brownfield"|"greenfield"|"unknown", "evidence": {"source_files": int, "internal_edges": int, "stack": dict, "graph_present": bool}, "reason": str}`.
  - CLI: `--project <dir>` (required), `--format json|text` (default `json`).

- [ ] **Step 1: Write the failing tests**

Create `skills/spec-manager/scripts/test_project_shape.py`:

```python
#!/usr/bin/env python3
"""Proof suite for project_shape.py — the bootstrap shape detector."""

import json
import os
import sys
import tempfile
import unittest
import unittest.mock as mock

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import project_shape  # noqa: E402


def _write_graph(project_dir, files):
    d = os.path.join(project_dir, "knowledge-base", ".graph")
    os.makedirs(d, exist_ok=True)
    with open(os.path.join(d, "graph.json"), "w", encoding="utf-8") as f:
        json.dump({"version": 1, "files": files}, f)


class CountGraphTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.proj = self.tmp.name

    def test_missing_graph_returns_not_present(self):
        self.assertEqual(project_shape.count_graph(self.proj), (0, 0, False))

    def test_counts_only_internal_edges(self):
        # external: and unresolved: imports are NOT internal wiring.
        _write_graph(self.proj, {
            "lib/a.ts": {"imports": ["lib/b.ts", "external:react", "unresolved:./missing"]},
            "lib/b.ts": {"imports": []},
        })
        self.assertEqual(project_shape.count_graph(self.proj), (2, 1, True))

    def test_malformed_graph_returns_not_present(self):
        d = os.path.join(self.proj, "knowledge-base", ".graph")
        os.makedirs(d)
        with open(os.path.join(d, "graph.json"), "w", encoding="utf-8") as f:
            f.write("{not json")
        self.assertEqual(project_shape.count_graph(self.proj), (0, 0, False))


class ClassifyTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.proj = self.tmp.name

    def test_brownfield_when_internal_edges_present(self):
        _write_graph(self.proj, {"a.ts": {"imports": ["b.ts"]}, "b.ts": {"imports": []}})
        with mock.patch.object(project_shape, "run_detect_project", return_value={"runtime": "nodejs"}):
            r = project_shape.classify(self.proj)
        self.assertEqual(r["recommendation"], "brownfield")
        self.assertEqual(r["evidence"]["internal_edges"], 1)
        self.assertEqual(r["evidence"]["stack"], {"runtime": "nodejs"})

    def test_greenfield_when_zero_internal_edges(self):
        _write_graph(self.proj, {"a.ts": {"imports": ["external:react"]}})
        with mock.patch.object(project_shape, "run_detect_project", return_value={}):
            r = project_shape.classify(self.proj)
        self.assertEqual(r["recommendation"], "greenfield")
        self.assertEqual(r["evidence"]["internal_edges"], 0)

    def test_unknown_when_no_graph(self):
        with mock.patch.object(project_shape, "run_detect_project", return_value={}):
            r = project_shape.classify(self.proj)
        self.assertEqual(r["recommendation"], "unknown")
        self.assertFalse(r["evidence"]["graph_present"])

    def test_evidence_keys_always_present(self):
        with mock.patch.object(project_shape, "run_detect_project", return_value={}):
            r = project_shape.classify(self.proj)
        for k in ("source_files", "internal_edges", "stack", "graph_present"):
            self.assertIn(k, r["evidence"])


class RunDetectProjectTest(unittest.TestCase):
    def test_empty_dict_on_subprocess_failure(self):
        with mock.patch.object(project_shape.subprocess, "run", side_effect=FileNotFoundError()):
            self.assertEqual(project_shape.run_detect_project("/nope"), {})


if __name__ == "__main__":
    unittest.main(verbosity=2)
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `cd skills/spec-manager/scripts && python test_project_shape.py`
Expected: FAIL — `ModuleNotFoundError: No module named 'project_shape'` (the script does not exist yet).

- [ ] **Step 3: Write the detector**

Create `skills/spec-manager/scripts/project_shape.py`:

```python
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
        lines.append(f"  stack: runtime={stack.get('runtime')} framework={stack.get('framework')}")
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
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `cd skills/spec-manager/scripts && python test_project_shape.py`
Expected: PASS — all tests (6 + the detect-project failure test), output pristine.

- [ ] **Step 5: Smoke-test the CLI against the testbed (real graph)**

Run: `cd skills/spec-manager/scripts && python project_shape.py --project /Users/main/Documents/projects/viva-croatia-testbed --format text`
Expected: `Recommendation: brownfield` with a non-zero `internal edges` count and a `stack` line showing `runtime=nodejs framework=...` (the testbed is a real Next.js app with a built code-graph). This is a read-only smoke check — no commit of testbed state.

- [ ] **Step 6: Commit**

```bash
git add skills/spec-manager/scripts/project_shape.py skills/spec-manager/scripts/test_project_shape.py
git commit -m "feat(spec-manager): project_shape.py — bootstrap greenfield/brownfield detector"
```

---

### Task 2: `bootstrap` command (spec-manager SKILL.md procedure)

Document the unified onboarding flow as a new `bootstrap` command and add it to the Quick Reference. Agent-orchestrated procedure — no script beyond Task 1; validated by review + the dogfooding pass.

**Files:**
- Modify: `skills/spec-manager/SKILL.md` (Quick Reference table near the top; add a new command section after the `init` command section)

**Interfaces:**
- Consumes: `project_shape.py` from Task 1 (`--project . --format text`); the existing `init`, `scan` procedures; `/freya-devkit:code-graph build`; `/freya-devkit:behavior-graph --build`.
- Produces: documented `bootstrap` command (no code interface for later tasks).

- [ ] **Step 1: Add the Quick Reference row**

In `skills/spec-manager/SKILL.md`, in the Quick Reference table, add this row immediately after the `init` row:

```
| `bootstrap` | Unified onboarding: detect shape → init + code-graph + (brownfield) scan + behavior-graph |
```

- [ ] **Step 2: Add the `bootstrap` command section**

In `skills/spec-manager/SKILL.md`, immediately after the `### /freya-devkit:spec-manager init` command section (before the `### /freya-devkit:spec-manager create` section), insert:

````markdown
### `/freya-devkit:spec-manager bootstrap`

The unified "bring the plugin up on this project" flow — it replaces running
`init` / `code-graph build` / `scan` by hand. It is **one-time**: for day-to-day
syncing use `update`, and after the first run newly-written code acquires intent
lazily via wrap-up's "touched code with no covering behavior" prompt.

**Flow:**

1. **Init structure.** Run the `init` flow (knowledge-base layout + `principles.md`). Idempotent — never clobbers existing files.
2. **Build the code graph.** Run `/freya-devkit:code-graph build` — the shape detector needs it, and it is cheap and useful regardless of shape.
3. **Detect shape and recommend.** Run:
   ```bash
   python "${CLAUDE_PLUGIN_ROOT}/skills/spec-manager/scripts/project_shape.py" --project . --format text
   ```
   Show the engineer the recommendation **and its evidence** (source-file count, internal-edge count, detected stack), then ask them to **confirm the branch or override**. On `unknown` (no graph / unreadable), ask outright with no recommendation. The detector never forces a branch — a one-time onboarding decision benefits from a human glance, so an unusually-structured repo can be overridden on sight rather than silently misclassified.
4. **Branch:**
   - **Brownfield →** run the `scan` flow to infer candidate behaviors at the **per-observable-behavior grain** (one `proposed` behavior per observable behavior/scenario, anchored to a route/entry where applicable — *not* per feature, *not* per route/function). All candidates are `proposed` records written into `knowledge-base/specs/`; **never** `.feature` scaffolds in the code tree (those appear only on acceptance). On a partially-onboarded repo this is **additive** — infer only for areas that have no existing spec; never overwrite or re-infer existing specs. Then run `/freya-devkit:behavior-graph --build --project .`. **Warn first** that scan over a large repo spawns discovery agents and can take a while.
   - **Greenfield →** skip `scan`. Build an (essentially empty) behavior graph so the machinery is initialized: `/freya-devkit:behavior-graph --build --project .` (with no `accepted`/`confirmed` behaviors this yields an empty `behavior.json`, which is correct). Print: *"Greenfield project — no inference run. Author behaviors forward as you build with `spec-manager create`."*
5. **Summary.** Report the knowledge-base layout created, the graph built, and (brownfield) a count of `proposed` candidates by category — with the reminder that **nothing needs review now**: the proposed queue is drained lazily (validate-on-hit at wrap-up, and the worklists once SP4 lands). The "full proposed behavior graph" is this corpus of `proposed` records in `knowledge-base/specs/`, *not* `behavior.json` (which projects only `accepted`/`confirmed`, so it stays ≈empty at first run — expected).
````

- [ ] **Step 3: Verify the edits render and the cross-references are valid**

Run: `cd /Users/main/Documents/projects/freya-devkit && grep -n "bootstrap" skills/spec-manager/SKILL.md`
Expected: the new Quick Reference row and the new command heading both appear. Visually confirm the `bootstrap` section sits between `init` and `create`, and that the `project_shape.py` path matches Task 1's file location.

- [ ] **Step 4: Commit**

```bash
git add skills/spec-manager/SKILL.md
git commit -m "feat(spec-manager): bootstrap command — unified greenfield-aware onboarding"
```

---

## Dogfooding pass (manual — run after Task 2, not a TDD task)

Validate on the **testbed** (`/Users/main/Documents/projects/viva-croatia-testbed`). The production webapp stays untouched. This is the long-flagged real test of the brownfield `scan` import path.

- [ ] **D1 — Detector on a real brownfield repo.** `python skills/spec-manager/scripts/project_shape.py --project /Users/main/Documents/projects/viva-croatia-testbed --format text`. Expect `brownfield`, non-zero internal edges, `runtime=nodejs`. (Read-only.)
- [ ] **D2 — Greenfield + unknown branches.** In a throwaway temp dir: (a) with no `knowledge-base/.graph/graph.json` → expect `unknown`; (b) write a minimal `graph.json` whose only imports are `external:` → expect `greenfield`. Confirms graceful degradation without touching any real repo.
- [ ] **D3 — Additive brownfield scan (bounded).** On a testbed branch (`git checkout -b dogfood/sp2-bootstrap` in the testbed; keep `main` clean), run the brownfield branch of `bootstrap` scoped to **one currently-unspecced feature area** (not the whole 224-file repo — the mechanism is identical, the cost is not). Verify: (a) it produces `proposed` behavior records at the per-observable-behavior grain that read as a *manageable* queue; (b) it writes **no** `.feature` files into the code tree; (c) the existing `SPEC-001` passkey spec is **untouched** (additive/no-clobber). Judge queue manageability — this is the parking-lot question ("flood vs manageable").
- [ ] **D4 — Log friction.** Record findings in `docs/design/behavior-layer/dogfooding-notes.md` (new SP2 entry): detector accuracy, queue manageability at the chosen grain, any additive/no-clobber issues. Restore the testbed to `main`; retain the dogfood branch for reference.

---

## Final whole-branch review

After Task 2 and the dogfooding pass, dispatch the final whole-branch review (superpowers:requesting-code-review) over the SP2 commits (base = the SP2 plan commit), pointing it at any Minor findings recorded in the ledger. Then continue on `feat/behavior-layer` — do **not** merge (SP3–SP5 remain).
