# Phase 2 — Plan 4: `behavior-graph` skill (core) — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Stand up the **`behavior-graph`** skill — own `behavior.json`, build it by projecting spec frontmatter + orchestrating `behavior-runner` + **merging fingerprints by trust**, and serve the two blast-radius queries: **Direction A** (changed files → affected behaviors) and **Direction B** (behavior → implementing code).

**Architecture:** A new stdlib-only Python skill `skills/behavior-graph/`. It is the pure, deterministic graph layer that sits *above* `code-graph` (queried for blast radius) and `behavior-runner` (shelled out to for fingerprints), per the two-skill split in `02-phase-2.md` §5b. `behavior.json` lives at `<project>/knowledge-base/.graph/behavior.json` (sibling to `graph.json`, in the git-ignored `.graph/` dir). Merge-by-trust: `observed > static`; a `test-failed` run **invalidates** a behavior's edges; any other `unknown` (`level-deferred`/`no-entry`/`no-graph`/`no-coverage`/`entry-missing`/`not-run`) **preserves** the prior fingerprint. Incremental re-run selection, freshness staleness, wrap-up wiring, F5/F3, and measurement are **Plan 5** (out of scope here).

**Tech Stack:** Python 3 (stdlib only). Consumes `behavior-runner/scripts/run_behaviors.py --emit-fingerprints` and `code-graph/scripts/graph_ops.py --impact`. Proven on the **testbed** (`/Users/main/Documents/projects/viva-croatia-testbed`).

## Global Constraints

- Plugin scripts are **stdlib-only**; reuse `spec-manager/scripts/frontmatter.py`; shell out to sibling skills by path.
- Plugin code → **freya-devkit** repo, branch `feat/behavior-layer` (normal `git`, user `Alex`).
- `behavior-graph` **owns `behavior.json`**; `code-graph` stays pure (only *queried* via `--impact`). Dependency arrows point up only: `behavior-graph → behavior-runner + code-graph + spec-manager`.
- `behavior.json` is a **generated projection** — never hand-edited; written to `<project>/knowledge-base/.graph/behavior.json` (git-ignored).
- Only **accepted** behaviors appear in `behavior.json` (matches the runner, which only emits accepted behaviors).
- Merge is by **trust**: `observed > static`; `test-failed` invalidates; other `unknown` reasons preserve the prior edge.

## File Structure

**freya-devkit (plugin):**
- `skills/behavior-graph/scripts/behavior_graph.py` — projection, merge, build, Direction A/B, CLI (new).
- `skills/behavior-graph/scripts/test_behavior_graph.py` — stdlib `unittest` tests (new).
- `skills/behavior-graph/SKILL.md` — skill definition + commands (new).

**viva-croatia-testbed:** no source changes — used as the proving ground (build `behavior.json`, query both directions). `behavior.json` is written under the git-ignored `.graph/`.

---

### Task 1: Scaffold the skill + `project_behaviors`

**Repo:** freya-devkit (plugin).

**Files:**
- Create: `skills/behavior-graph/scripts/behavior_graph.py`
- Create: `skills/behavior-graph/scripts/test_behavior_graph.py`
- Create: `skills/behavior-graph/SKILL.md`

**Interfaces:**
- Produces: `project_behaviors(specs_dir) -> dict[str, dict]` — `BEH-NNN → {spec_id, state, level, adapter, locator}` for every **accepted** behavior under `specs_dir`. Unparseable spec files are skipped (not fatal).

- [ ] **Step 1: Write the failing test**

Create `skills/behavior-graph/scripts/test_behavior_graph.py`:
```python
import os
import tempfile
import unittest
import unittest.mock as mock

import behavior_graph


SPEC = """---
id: SPEC-001
title: Passkey Login
category: auth
status: implemented
behaviors:
  - behavior_id: BEH-002
    title: Login with an expired challenge is rejected
    state: accepted
    level: unit
    adapter: vitest
    locator: lib/webauthn.test.ts::rejects an expired challenge
  - behavior_id: BEH-003
    title: Unknown email does not reveal whether a user exists
    state: accepted
    level: integration
    adapter: cucumber
    locator: features/auth/passkey-login.feature#unknown-email-does-not-reveal-whether-a-user-exists
    entry: app/api/auth/passkey/authenticate/start/route.ts
  - behavior_id: BEH-001
    title: Successful passkey login
    state: proposed
    level: e2e
    adapter: cucumber
    locator: features/auth/passkey-login.feature#successful-passkey-login
---
# body
"""


class ProjectBehaviorsTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        d = os.path.join(self.tmp.name, "auth")
        os.makedirs(d)
        with open(os.path.join(d, "SPEC-001-passkey-login.md"), "w") as f:
            f.write(SPEC)
        self.specs = self.tmp.name

    def tearDown(self):
        self.tmp.cleanup()

    def test_projects_accepted_behaviors_only(self):
        got = behavior_graph.project_behaviors(self.specs)
        self.assertEqual(sorted(got), ["BEH-002", "BEH-003"])  # BEH-001 proposed → excluded
        self.assertEqual(
            got["BEH-003"],
            {
                "spec_id": "SPEC-001",
                "state": "accepted",
                "level": "integration",
                "adapter": "cucumber",
                "locator": "features/auth/passkey-login.feature#unknown-email-does-not-reveal-whether-a-user-exists",
            },
        )


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run to verify it fails**

Run: `cd skills/behavior-graph/scripts && python -m unittest test_behavior_graph -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'behavior_graph'`.

- [ ] **Step 3: Implement**

Create `skills/behavior-graph/scripts/behavior_graph.py`:
```python
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

_PROJECTED_FIELDS = ("state", "level", "adapter", "locator")


def project_behaviors(specs_dir):
    """Map BEH-NNN -> projected frontmatter fields for every accepted behavior."""
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
                if not isinstance(b, dict) or b.get("state") != "accepted":
                    continue
                bid = b.get("behavior_id")
                if not bid:
                    continue
                rec = {"spec_id": fm.get("id")}
                for key in _PROJECTED_FIELDS:
                    rec[key] = b.get(key)
                out[bid] = rec
    return out


def main():
    parser = argparse.ArgumentParser(description="Build and query the behavior graph.")
    parser.add_argument("--project", required=True, help="Project root directory.")
    args = parser.parse_args()
    print(json.dumps({"behaviors": sorted(project_behaviors(
        os.path.join(args.project, "knowledge-base", "specs")))}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
```

- [ ] **Step 4: Run to verify it passes**

Run: `cd skills/behavior-graph/scripts && python -m unittest test_behavior_graph -v`
Expected: PASS (1 test).

- [ ] **Step 5: Write SKILL.md**

Create `skills/behavior-graph/SKILL.md`:
```markdown
---
name: behavior-graph
description: |
  Own behavior.json (the BEHAVIOR -> TEST -> CODE projection) and answer the two
  blast-radius directions: code change -> affected behaviors, and behavior ->
  implementing code. Pure graph layer over code-graph + behavior-runner.

  TRIGGER when: building/refreshing the behavior graph, asking which behaviors a
  code change affects, or which code implements a behavior. Used by wrap-up and
  brainstorming.
---

# Behavior Graph

Owns `behavior.json` (a **generated** projection at `knowledge-base/.graph/behavior.json`,
sibling to `graph.json`). It projects spec frontmatter, orchestrates `behavior-runner`
for coverage fingerprints, **merges by trust** (`observed > static`), and serves:

- **Direction A** — `affected <changed-files>`: which accepted behaviors a code change touches.
- **Direction B** — `implements <BEH-NNN>`: which code a behavior exercises.

It is the pure graph layer (vision §5b): it *queries* `code-graph` (`--impact`) and
`behavior-runner` (`--emit-fingerprints`); `code-graph` stays unaware of behaviors.

## Merge by trust

| Incoming run | Result |
|---|---|
| `observed` | take it (highest trust) |
| `static` | take it, unless the prior edge was `observed` (don't downgrade) |
| `unknown` + `reason: test-failed` | **invalidate** (the test is red) |
| `unknown` + any other reason | **preserve** the prior fingerprint |

## Commands

```bash
# Build/refresh behavior.json (projects specs, runs behaviors, merges):
python "${CLAUDE_PLUGIN_ROOT}/skills/behavior-graph/scripts/behavior_graph.py" --build --project /path/to/project

# Direction A — which behaviors does a code change touch:
python "${CLAUDE_PLUGIN_ROOT}/skills/behavior-graph/scripts/behavior_graph.py" --affected lib/webauthn.ts --project /path/to/project

# Direction B — which code does a behavior exercise:
python "${CLAUDE_PLUGIN_ROOT}/skills/behavior-graph/scripts/behavior_graph.py" --implements BEH-003 --project /path/to/project
```
```

- [ ] **Step 6: Commit**

```bash
git add skills/behavior-graph/
git commit -m "feat(behavior-graph): scaffold skill + project_behaviors"
```

---

### Task 2: `merge_fingerprint` (merge by trust)

**Repo:** freya-devkit (plugin).

**Files:**
- Modify: `skills/behavior-graph/scripts/behavior_graph.py`
- Modify: `skills/behavior-graph/scripts/test_behavior_graph.py`

**Interfaces:**
- Produces: `merge_fingerprint(prior, incoming) -> dict` — `prior`/`incoming` are coverage-parts `{coverage, exercises, reason?}` (`prior` may be `None`). Returns the merged coverage-part per the trust table.

- [ ] **Step 1: Write the failing tests**

Append to `test_behavior_graph.py`:
```python
class MergeFingerprintTest(unittest.TestCase):
    def test_observed_incoming_wins(self):
        out = behavior_graph.merge_fingerprint(
            {"coverage": "static", "exercises": [{"path": "a"}]},
            {"coverage": "observed", "exercises": [{"path": "b"}]},
        )
        self.assertEqual(out, {"coverage": "observed", "exercises": [{"path": "b"}]})

    def test_static_does_not_downgrade_observed(self):
        out = behavior_graph.merge_fingerprint(
            {"coverage": "observed", "exercises": [{"path": "obs"}]},
            {"coverage": "static", "exercises": [{"path": "stat"}]},
        )
        self.assertEqual(out, {"coverage": "observed", "exercises": [{"path": "obs"}]})

    def test_static_with_no_prior_is_static(self):
        out = behavior_graph.merge_fingerprint(
            None, {"coverage": "static", "exercises": [{"path": "stat"}]}
        )
        self.assertEqual(out, {"coverage": "static", "exercises": [{"path": "stat"}]})

    def test_test_failed_invalidates_even_observed_prior(self):
        out = behavior_graph.merge_fingerprint(
            {"coverage": "observed", "exercises": [{"path": "obs"}]},
            {"coverage": "unknown", "exercises": [], "reason": "test-failed"},
        )
        self.assertEqual(out, {"coverage": "unknown", "exercises": [], "reason": "test-failed"})

    def test_other_unknown_preserves_prior(self):
        out = behavior_graph.merge_fingerprint(
            {"coverage": "observed", "exercises": [{"path": "obs"}]},
            {"coverage": "unknown", "exercises": [], "reason": "level-deferred"},
        )
        self.assertEqual(out, {"coverage": "observed", "exercises": [{"path": "obs"}]})

    def test_unknown_with_no_prior_keeps_reason(self):
        out = behavior_graph.merge_fingerprint(
            None, {"coverage": "unknown", "exercises": [], "reason": "no-entry"}
        )
        self.assertEqual(out, {"coverage": "unknown", "exercises": [], "reason": "no-entry"})
```

- [ ] **Step 2: Run to verify they fail**

Run: `cd skills/behavior-graph/scripts && python -m unittest test_behavior_graph -v`
Expected: FAIL — `AttributeError: ... 'merge_fingerprint'`.

- [ ] **Step 3: Implement**

Add to `behavior_graph.py` (above `main`):
```python
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
```

- [ ] **Step 4: Run to verify they pass**

Run: `cd skills/behavior-graph/scripts && python -m unittest test_behavior_graph -v`
Expected: PASS (1 + 6 = 7 tests).

- [ ] **Step 5: Commit**

```bash
git add skills/behavior-graph/scripts/
git commit -m "feat(behavior-graph): merge_fingerprint (merge by trust)"
```

---

### Task 3: `build` (orchestrate runner + merge + write) and Direction B

**Repo:** freya-devkit (plugin).

**Files:**
- Modify: `skills/behavior-graph/scripts/behavior_graph.py`
- Modify: `skills/behavior-graph/scripts/test_behavior_graph.py`

**Interfaces:**
- Consumes: `behavior-runner/scripts/run_behaviors.py --project <p> --emit-fingerprints` → `{version, commit, fingerprints: {BEH: {coverage, exercises, reason?}}}` (verified contract).
- Consumes: `project_behaviors`, `merge_fingerprint`.
- Produces: `load_behavior_json(project_dir) -> dict`, `write_behavior_json(project_dir, data)`, `build(project_dir) -> dict` (writes `behavior.json` and returns it), `direction_b(behaviors, beh_id) -> list[str]`.

- [ ] **Step 1: Write the failing tests**

Append to `test_behavior_graph.py`:
```python
class BuildTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.proj = self.tmp.name
        specs = os.path.join(self.proj, "knowledge-base", "specs", "auth")
        os.makedirs(specs)
        with open(os.path.join(specs, "SPEC-001-passkey-login.md"), "w") as f:
            f.write(SPEC)

    def tearDown(self):
        self.tmp.cleanup()

    def test_build_merges_runner_fingerprints_and_writes(self):
        runner_out = {
            "version": 1,
            "commit": "deadbeef",
            "fingerprints": {
                "BEH-002": {"coverage": "observed", "exercises": [{"path": "lib/webauthn.ts", "source": "observed", "confidence": 0.8, "freshness": "deadbeef"}]},
                "BEH-003": {"coverage": "static", "exercises": [{"path": "app/api/auth/passkey/authenticate/start/route.ts", "source": "static", "confidence": 0.5, "freshness": "deadbeef"}]},
            },
        }
        with mock.patch.object(behavior_graph, "_run_behavior_runner", return_value=runner_out):
            data = behavior_graph.build(self.proj)
        self.assertEqual(data["commit"], "deadbeef")
        self.assertEqual(data["behaviors"]["BEH-002"]["coverage"], "observed")
        self.assertEqual(data["behaviors"]["BEH-002"]["level"], "unit")  # projected field present
        self.assertEqual(data["behaviors"]["BEH-003"]["coverage"], "static")
        # behavior.json was written under the git-ignored .graph dir
        path = os.path.join(self.proj, "knowledge-base", ".graph", "behavior.json")
        self.assertTrue(os.path.exists(path))

    def test_build_preserves_prior_observed_on_unknown(self):
        # Seed a prior behavior.json with an observed BEH-003 edge.
        behavior_graph.write_behavior_json(self.proj, {
            "version": 1, "commit": "old",
            "behaviors": {"BEH-003": {"spec_id": "SPEC-001", "state": "accepted",
                                      "level": "integration", "adapter": "cucumber",
                                      "locator": "x", "coverage": "observed",
                                      "exercises": [{"path": "lib/prior.ts"}]}},
        })
        runner_out = {"version": 1, "commit": "new", "fingerprints": {
            "BEH-002": {"coverage": "observed", "exercises": [{"path": "lib/webauthn.ts"}]},
            "BEH-003": {"coverage": "unknown", "exercises": [], "reason": "level-deferred"},
        }}
        with mock.patch.object(behavior_graph, "_run_behavior_runner", return_value=runner_out):
            data = behavior_graph.build(self.proj)
        # prior observed edge preserved despite the unknown run
        self.assertEqual(data["behaviors"]["BEH-003"]["coverage"], "observed")
        self.assertEqual(data["behaviors"]["BEH-003"]["exercises"], [{"path": "lib/prior.ts"}])


class DirectionBTest(unittest.TestCase):
    def test_returns_exercised_paths(self):
        behaviors = {"BEH-003": {"exercises": [{"path": "lib/webauthn.ts"}, {"path": "lib/prisma.ts"}]}}
        self.assertEqual(behavior_graph.direction_b(behaviors, "BEH-003"),
                         ["lib/webauthn.ts", "lib/prisma.ts"])

    def test_unknown_behavior_returns_empty(self):
        self.assertEqual(behavior_graph.direction_b({}, "BEH-999"), [])
```

- [ ] **Step 2: Run to verify they fail**

Run: `cd skills/behavior-graph/scripts && python -m unittest test_behavior_graph -v`
Expected: FAIL — `AttributeError: ... 'build'` / `'write_behavior_json'` / `'direction_b'`.

- [ ] **Step 3: Implement**

Add to `behavior_graph.py` (above `main`):
```python
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
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2)


def _run_behavior_runner(project_dir):
    out = subprocess.run(
        [sys.executable, str(_RUNNER), "--project", project_dir, "--emit-fingerprints"],
        capture_output=True, text=True, check=True,
    )
    return json.loads(out.stdout)


_COVERAGE_KEYS = ("coverage", "exercises", "reason")


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
    return [e["path"] for e in entry.get("exercises", [])]
```

- [ ] **Step 4: Run to verify they pass**

Run: `cd skills/behavior-graph/scripts && python -m unittest test_behavior_graph -v`
Expected: PASS (7 + 4 = 11 tests).

- [ ] **Step 5: Commit**

```bash
git add skills/behavior-graph/scripts/
git commit -m "feat(behavior-graph): build (project+run+merge) + Direction B"
```

---

### Task 4: Direction A + CLI wiring, proven on the testbed

**Repo:** freya-devkit (plugin); proven against the testbed.

**Files:**
- Modify: `skills/behavior-graph/scripts/behavior_graph.py`
- Modify: `skills/behavior-graph/scripts/test_behavior_graph.py`

**Interfaces:**
- Consumes: `code-graph/scripts/graph_ops.py --impact <files> --dir <p> --format json` → `{input_files, direct_dependents, transitive_dependents}` (verified shape).
- Produces: `_code_graph_impact(changed_files, project_dir) -> set[str]`, `direction_a(behaviors, changed_files, project_dir) -> list[str]`, and a `main` with mutually-exclusive `--build` / `--affected FILE...` / `--implements BEH`.

- [ ] **Step 1: Write the failing tests**

Append to `test_behavior_graph.py`:
```python
class DirectionATest(unittest.TestCase):
    def test_affected_when_exercises_intersect_impact(self):
        behaviors = {
            "BEH-002": {"exercises": [{"path": "lib/webauthn.ts"}]},
            "BEH-003": {"exercises": [{"path": "app/api/x/route.ts"}, {"path": "lib/webauthn.ts"}]},
            "BEH-009": {"exercises": [{"path": "lib/unrelated.ts"}]},
        }
        impact = {"lib/webauthn.ts", "app/api/x/route.ts"}
        with mock.patch.object(behavior_graph, "_code_graph_impact", return_value=impact):
            got = behavior_graph.direction_a(behaviors, ["lib/webauthn.ts"], "/proj")
        self.assertEqual(got, ["BEH-002", "BEH-003"])  # BEH-009 not affected, sorted

    def test_none_affected_returns_empty(self):
        behaviors = {"BEH-002": {"exercises": [{"path": "lib/webauthn.ts"}]}}
        with mock.patch.object(behavior_graph, "_code_graph_impact", return_value={"lib/other.ts"}):
            self.assertEqual(behavior_graph.direction_a(behaviors, ["lib/other.ts"], "/proj"), [])
```

- [ ] **Step 2: Run to verify they fail**

Run: `cd skills/behavior-graph/scripts && python -m unittest test_behavior_graph -v`
Expected: FAIL — `AttributeError: ... 'direction_a'` / `'_code_graph_impact'`.

- [ ] **Step 3: Implement**

Add to `behavior_graph.py` (above `main`):
```python
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


def direction_a(behaviors, changed_files, project_dir):
    """Direction A: accepted behaviors whose exercised code intersects the blast radius."""
    impact = _code_graph_impact(changed_files, project_dir)
    affected = []
    for bid, entry in behaviors.items():
        paths = {e["path"] for e in entry.get("exercises", [])}
        if paths & impact:
            affected.append(bid)
    return sorted(affected)
```
Replace `main` with the full CLI:
```python
def main():
    parser = argparse.ArgumentParser(description="Build and query the behavior graph.")
    parser.add_argument("--project", required=True, help="Project root directory.")
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--build", action="store_true", help="Build/refresh behavior.json.")
    group.add_argument("--affected", nargs="+", metavar="FILE",
                       help="Direction A: behaviors affected by these changed files.")
    group.add_argument("--implements", metavar="BEH",
                       help="Direction B: code a behavior exercises.")
    args = parser.parse_args()

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
```

- [ ] **Step 4: Run unit tests, then prove end-to-end on the testbed**

Run the pure tests: `cd skills/behavior-graph/scripts && python -m unittest test_behavior_graph -v`
Expected: PASS (11 + 2 = 13 tests).

Then the real end-to-end (the testbed has accepted BEH-002 unit + BEH-003 integration, and a built code-graph):
```bash
# Build the behavior graph for the testbed:
python /Users/main/Documents/projects/freya-devkit/skills/behavior-graph/scripts/behavior_graph.py \
  --build --project /Users/main/Documents/projects/viva-croatia-testbed
```
Expected: JSON with `behaviors.BEH-002.coverage == "observed"` (exercises `lib/webauthn.ts`) and `behaviors.BEH-003.coverage == "static"` (exercises the route + `lib/prisma.ts` + `lib/webauthn.ts`).
```bash
# Direction A — change lib/webauthn.ts → both behaviors are affected:
python …/behavior_graph.py --affected lib/webauthn.ts --project /Users/main/Documents/projects/viva-croatia-testbed
# Expected: {"affected": ["BEH-002", "BEH-003"]}

# Direction B — BEH-003 → its implementing code:
python …/behavior_graph.py --implements BEH-003 --project /Users/main/Documents/projects/viva-croatia-testbed
# Expected: {"implements": ["app/api/auth/passkey/authenticate/start/route.ts", "lib/prisma.ts", "lib/webauthn.ts"]}
```
(If the runner emits BEH-003 as `unknown` because the testbed code-graph is stale, refresh it: `graph_ops.py --update --dir <testbed> --non-interactive`, then rebuild.)

- [ ] **Step 5: Commit**

```bash
git add skills/behavior-graph/scripts/
git commit -m "feat(behavior-graph): Direction A (blast-radius intersect) + CLI"
```

---

## Self-Review

**Spec coverage (against `02-phase-2.md` §3/§5/§5b/§9):** Delivers the `behavior-graph` skill owning `behavior.json` (§5b — code-graph stays pure, only queried via `--impact`); projects spec frontmatter (§3); merges fingerprints by trust with the `reason` discriminator consumed (§3 — observed > static, test-failed invalidates, other unknown preserves); serves Direction A (§5 — blast radius ∩ fingerprints) and Direction B (§5). Out of scope here (correctly → Plan 5): incremental re-run selection + freshness staleness (§4a), wrap-up Phase 3.5 wiring (§9), F5/F3 (§8), measurement (§6).

**Placeholder scan:** No TBD/TODO. Every code step shows full code; every command states expected output, using the empirically-verified testbed values (BEH-002 observed → `lib/webauthn.ts`; BEH-003 static → route + prisma + webauthn; Direction A on `lib/webauthn.ts` → both).

**Type/name consistency:** `project_behaviors`, `merge_fingerprint`, `load_behavior_json`/`write_behavior_json`, `_run_behavior_runner`, `build`, `direction_b`, `_code_graph_impact`, `direction_a` are defined once and consumed consistently. The coverage-part shape `{coverage, exercises, reason?}` from `merge_fingerprint` (Task 2) is what `build` (Task 3) spreads onto projected fields, and what `direction_a`/`direction_b` (Tasks 3/4) read via `exercises[].path`. The runner contract (`{version, commit, fingerprints}`) and code-graph `--impact` contract (`{input_files, direct_dependents, transitive_dependents}`) match the verified outputs. `behavior.json` fields (`spec_id/state/level/adapter/locator/coverage/exercises`) match `02-phase-2.md` §3.

**Known iteration point (honest):** Task 4 Step 4's end-to-end assumes the testbed code-graph is current (it is, from Plan 3) and the runner emits BEH-003 as `static` (proven in Plan 3) — the fallback note covers a stale graph. `_run_behavior_runner` uses `check=True`; if the runner subprocess errors, `build` raises rather than writing a partial graph — acceptable (fail loud on a broken producer) and revisited with measurement in Plan 5.

## Next plan

**Plan 5 — wiring, perf, fixes:** incremental re-run selection (Direction A picks which behaviors to re-run) + freshness staleness (compare each edge's `freshness` commit to the last commit touching the file); wrap-up Phase 3.5 integration (run affected accepted behaviors, block on deterministic failures); the carried **F5** (never-synced guard) and **F3** (`init` `.gitkeep`); and the §6 measurement (fingerprint breadth, FP rate, runtime, static-vs-observed).
