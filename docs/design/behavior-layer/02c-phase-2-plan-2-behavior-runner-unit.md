# Phase 2 — Plan 2: `behavior-runner` skill (unit level) — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Stand up the new **`behavior-runner`** skill and prove it end-to-end at the **unit level** — running an accepted unit behavior (BEH-002, "expired challenge rejected") via vitest with coverage and emitting an `observed` fingerprint (`TEST → CODE` edges) for `behavior-graph` to consume later.

**Architecture:** A new plugin skill `skills/behavior-runner/` with a stdlib-only Python entry `run_behaviors.py`. It reads accepted behaviors from a project's specs (reusing spec-manager's `frontmatter.py`), and for a `level: unit` / `adapter: vitest` behavior it shells out to the project's vitest runner with V8 coverage, parses the coverage report, maps executed files to project-relative graph keys, and emits a per-behavior fingerprint as JSON. The runner is a **producer**: it emits fingerprints; it does **not** own `behavior.json` (that is `behavior-graph`, a later plan). The unit level is built first because in-process vitest coverage is source-mapped reliably — no bundler remap unknown (that risk is isolated to the integration plan).

**Tech Stack:** Python 3 (stdlib only) for the skill; the **testbed** (`/Users/main/Documents/projects/viva-croatia-testbed`) provides the proving ground with vitest + `@vitest/coverage-v8` + `vite-tsconfig-paths`.

## Global Constraints

- Plugin scripts are **stdlib-only** (zero-install) — no PyYAML, no pip deps. Reuse `skills/spec-manager/scripts/frontmatter.py` for parsing.
- Plugin code (the `behavior-runner` skill) is committed to the **freya-devkit** repo on branch `feat/behavior-layer` (normal `git`, user already `Alex`).
- Testbed changes are committed to the **testbed** repo with `git -c user.name="Alex" -c user.email="claude.stifle198@simplelogin.com"`. Never touch `/Users/main/Documents/areas/viva-croatia/webapp` (production).
- The runner is a **producer only**: it emits fingerprints (`{BEH-NNN: {coverage, exercises}}`); it never writes `behavior.json`.
- Only **accepted, non-quarantined** behaviors matching the requested `level` are run.
- A behavior with no usable coverage is emitted as `coverage: "unknown"` with `exercises: []` — never falsely empty-as-observed.
- The plugin is invoked by absolute path under `${CLAUDE_PLUGIN_ROOT}` (the symlinked local-dev install = the repo).

---

## File Structure

**freya-devkit (plugin):**
- `skills/behavior-runner/SKILL.md` — skill definition + commands (new).
- `skills/behavior-runner/scripts/run_behaviors.py` — the runner (new).
- `skills/behavior-runner/scripts/test_run_behaviors.py` — stdlib `unittest` tests for the pure logic (new).

**viva-croatia-testbed (proving ground):**
- `package.json`, `pnpm-lock.yaml` — add vitest tooling + `test:unit` script (modify).
- `vitest.config.ts` — vitest + coverage config (new).
- `lib/webauthn.test.ts` — BEH-002 unit test (new).
- `knowledge-base/specs/auth/SPEC-001-passkey-login.md` — BEH-002 → vitest/native + `level`s (modify).
- `features/auth/passkey-login.feature` — remove the now-native BEH-002 scenario (modify).

---

### Task 1: Scaffold the skill + accepted-behavior reader

**Repo:** freya-devkit (plugin).

**Files:**
- Create: `skills/behavior-runner/scripts/run_behaviors.py`
- Create: `skills/behavior-runner/scripts/test_run_behaviors.py`
- Create: `skills/behavior-runner/SKILL.md`

**Interfaces:**
- Produces: `load_accepted_behaviors(specs_dir, level=None) -> list[dict]` — each dict is a behavior record (`behavior_id`, `title`, `state`, `adapter`, `locator`, and `level` if present) augmented with `spec_id` and `spec_path`. Returns only `state == "accepted"` behaviors, optionally filtered to `level`.

- [ ] **Step 1: Write the failing test**

Create `skills/behavior-runner/scripts/test_run_behaviors.py`:
```python
import os
import tempfile
import unittest

import run_behaviors


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
  - behavior_id: BEH-001
    title: Successful passkey login
    state: proposed
    level: e2e
    adapter: cucumber
    locator: features/auth/passkey-login.feature#successful-passkey-login
---
# body
"""


class LoadAcceptedBehaviorsTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        specs = os.path.join(self.tmp.name, "auth")
        os.makedirs(specs)
        with open(os.path.join(specs, "SPEC-001-passkey-login.md"), "w") as f:
            f.write(SPEC)
        self.specs_dir = self.tmp.name

    def tearDown(self):
        self.tmp.cleanup()

    def test_filters_to_accepted_unit(self):
        got = run_behaviors.load_accepted_behaviors(self.specs_dir, level="unit")
        self.assertEqual(len(got), 1)
        self.assertEqual(got[0]["behavior_id"], "BEH-002")
        self.assertEqual(got[0]["spec_id"], "SPEC-001")
        self.assertTrue(got[0]["spec_path"].endswith("SPEC-001-passkey-login.md"))

    def test_accepted_without_level_filter_excludes_proposed(self):
        got = run_behaviors.load_accepted_behaviors(self.specs_dir)
        ids = sorted(b["behavior_id"] for b in got)
        self.assertEqual(ids, ["BEH-002", "BEH-003"])  # BEH-001 is proposed


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `cd skills/behavior-runner/scripts && python -m unittest test_run_behaviors -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'run_behaviors'` (or `AttributeError: ... load_accepted_behaviors`).

- [ ] **Step 3: Write the minimal implementation**

Create `skills/behavior-runner/scripts/run_behaviors.py`:
```python
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
sys.path.insert(0, str(_SPEC_SCRIPTS))
import frontmatter  # noqa: E402

OBSERVED_CONFIDENCE = 0.8


def load_accepted_behaviors(specs_dir, level=None):
    """Return accepted behavior records under specs_dir, optionally by level.

    Each record is the spec's behavior mapping plus `spec_id` and `spec_path`.
    """
    out = []
    for root, _dirs, files in os.walk(specs_dir):
        for name in files:
            if not name.endswith(".md"):
                continue
            path = os.path.join(root, name)
            with open(path, encoding="utf-8") as f:
                fm, _body = frontmatter.parse_frontmatter(f.read())
            behaviors = fm.get("behaviors")
            if not isinstance(behaviors, list):
                continue
            for b in behaviors:
                if not isinstance(b, dict):
                    continue
                if b.get("state") != "accepted":
                    continue
                if level is not None and b.get("level") != level:
                    continue
                rec = dict(b)
                rec["spec_id"] = fm.get("id")
                rec["spec_path"] = path
                out.append(rec)
    return out


def main():
    parser = argparse.ArgumentParser(description="Run accepted behaviors and emit fingerprints.")
    parser.add_argument("--project", required=True, help="Project root directory.")
    parser.add_argument("--specs-dir", help="Specs dir (default: <project>/knowledge-base/specs).")
    parser.add_argument("--level", help="Only run behaviors at this level (e.g. unit).")
    parser.add_argument("--list", action="store_true", help="List matching accepted behaviors and exit.")
    args = parser.parse_args()

    specs_dir = args.specs_dir or os.path.join(args.project, "knowledge-base", "specs")
    behaviors = load_accepted_behaviors(specs_dir, level=args.level)

    if args.list:
        for b in behaviors:
            print(f"{b['behavior_id']}\t{b.get('level')}\t{b.get('adapter')}\t{b.get('locator')}")
        return 0

    print(json.dumps({"behaviors": [b["behavior_id"] for b in behaviors]}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
```

- [ ] **Step 4: Run the test to verify it passes**

Run: `cd skills/behavior-runner/scripts && python -m unittest test_run_behaviors -v`
Expected: PASS (2 tests).

- [ ] **Step 5: Write the SKILL.md**

Create `skills/behavior-runner/SKILL.md`:
```markdown
---
name: behavior-runner
description: |
  Run a project's accepted behaviors via their adapter and capture observed
  coverage as TEST -> CODE fingerprints. Producer for the behavior graph.

  TRIGGER when: running accepted behaviors, capturing behavior coverage, or
  refreshing behavior fingerprints. Used by behavior-graph and wrap-up.
---

# Behavior Runner

Runs **accepted, non-quarantined** behaviors through their adapter and emits
`observed` coverage fingerprints (the `TEST -> CODE` `exercises` edges). It is a
**producer**: it prints fingerprints as JSON; it never writes `behavior.json`
(that is `behavior-graph`).

Coverage capture is **per level** (vision: test-level-agnostic):

| Level | Mechanism |
|-------|-----------|
| `unit` / `component` | in-process, runner-native V8 coverage (vitest/jest) |
| `integration` | running app instrumented over real HTTP (later plan) |
| `e2e` | browser (later plan) |

## Commands

### `run` (default)
Emit fingerprints for accepted behaviors:
```bash
python "${CLAUDE_PLUGIN_ROOT}/skills/behavior-runner/scripts/run_behaviors.py" \
  --project /path/to/project --level unit --emit-fingerprints
```

### `--list`
List matching accepted behaviors without running them:
```bash
python "${CLAUDE_PLUGIN_ROOT}/skills/behavior-runner/scripts/run_behaviors.py" \
  --project /path/to/project --level unit --list
```

## Output (fingerprint contract)

```json
{
  "version": 1,
  "commit": "<project HEAD>",
  "fingerprints": {
    "BEH-002": {
      "coverage": "observed",
      "exercises": [
        { "path": "lib/webauthn.ts", "source": "observed", "confidence": 0.8, "freshness": "<commit>" }
      ]
    }
  }
}
```

A behavior with no usable coverage is emitted with `coverage: "unknown"` and an
empty `exercises` list — never falsely attributed.
```

- [ ] **Step 6: Commit**

```bash
git add skills/behavior-runner/
git commit -m "feat(behavior-runner): scaffold skill + accepted-behavior reader"
```

---

### Task 2: Coverage parsing + fingerprint shaping (pure logic)

**Repo:** freya-devkit (plugin).

**Files:**
- Modify: `skills/behavior-runner/scripts/run_behaviors.py`
- Modify: `skills/behavior-runner/scripts/test_run_behaviors.py`

**Interfaces:**
- Produces: `coverage_files_to_keys(coverage_final, project_dir, exclude=None) -> list[str]` — given an istanbul `coverage-final.json` dict (keyed by absolute path; each value has a statement-hit map `s`), return sorted project-relative paths of files with at least one executed statement, dropping `node_modules`, files outside `project_dir`, and any path in `exclude`.
- Produces: `shape_fingerprint(exercised_keys, commit, confidence=OBSERVED_CONFIDENCE) -> dict` — `{"coverage": "observed"|"unknown", "exercises": [...]}`.

- [ ] **Step 1: Write the failing tests**

Append to `skills/behavior-runner/scripts/test_run_behaviors.py`:
```python
class CoverageMappingTest(unittest.TestCase):
    def setUp(self):
        self.project = "/proj"
        self.cov = {
            "/proj/lib/webauthn.ts": {"s": {"0": 3, "1": 1, "2": 0}},
            "/proj/lib/webauthn.test.ts": {"s": {"0": 1}},
            "/proj/lib/unused.ts": {"s": {"0": 0, "1": 0}},
            "/proj/node_modules/pkg/index.js": {"s": {"0": 5}},
            "/elsewhere/other.ts": {"s": {"0": 2}},
        }

    def test_keeps_executed_project_source_drops_the_rest(self):
        keys = run_behaviors.coverage_files_to_keys(
            self.cov, self.project, exclude={"lib/webauthn.test.ts"}
        )
        self.assertEqual(keys, ["lib/webauthn.ts"])

    def test_unused_file_is_dropped(self):
        keys = run_behaviors.coverage_files_to_keys(self.cov, self.project)
        self.assertNotIn("lib/unused.ts", keys)


class ShapeFingerprintTest(unittest.TestCase):
    def test_observed_when_keys_present(self):
        fp = run_behaviors.shape_fingerprint(["lib/webauthn.ts"], "abc123")
        self.assertEqual(fp["coverage"], "observed")
        self.assertEqual(fp["exercises"], [
            {"path": "lib/webauthn.ts", "source": "observed", "confidence": 0.8, "freshness": "abc123"}
        ])

    def test_unknown_when_no_keys(self):
        fp = run_behaviors.shape_fingerprint([], "abc123")
        self.assertEqual(fp["coverage"], "unknown")
        self.assertEqual(fp["exercises"], [])
```

- [ ] **Step 2: Run to verify they fail**

Run: `cd skills/behavior-runner/scripts && python -m unittest test_run_behaviors -v`
Expected: FAIL — `AttributeError: module 'run_behaviors' has no attribute 'coverage_files_to_keys'`.

- [ ] **Step 3: Implement**

Add to `run_behaviors.py` (above `main`):
```python
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


def shape_fingerprint(exercised_keys, commit, confidence=OBSERVED_CONFIDENCE):
    """Build a per-behavior fingerprint record (coverage + exercises edges)."""
    if not exercised_keys:
        return {"coverage": "unknown", "exercises": []}
    return {
        "coverage": "observed",
        "exercises": [
            {"path": k, "source": "observed", "confidence": confidence, "freshness": commit}
            for k in exercised_keys
        ],
    }
```

- [ ] **Step 4: Run to verify they pass**

Run: `cd skills/behavior-runner/scripts && python -m unittest test_run_behaviors -v`
Expected: PASS (6 tests total).

- [ ] **Step 5: Commit**

```bash
git add skills/behavior-runner/scripts/
git commit -m "feat(behavior-runner): coverage->keys mapping + fingerprint shaping"
```

---

### Task 3: Testbed — make BEH-002 a real unit behavior (vitest)

**Repo:** viva-croatia-testbed.

**Files:**
- Modify: `package.json` (devDeps + `test:unit` script)
- Create: `vitest.config.ts`
- Create: `lib/webauthn.test.ts`
- Modify: `knowledge-base/specs/auth/SPEC-001-passkey-login.md`
- Modify: `features/auth/passkey-login.feature`

**Interfaces:**
- Consumes: `verifyChallenge(challenge: string)` from `lib/webauthn.ts` — returns `{ valid: boolean; userId?; type? }`; on an expired stored challenge it deletes the row and returns `{ valid: false }` (verified by reading lib/webauthn.ts:150-168).
- Produces: an accepted `level: unit` / `adapter: vitest` behavior BEH-002 located at `lib/webauthn.test.ts::rejects an expired challenge`.

- [ ] **Step 1: Install vitest tooling**

Run:
```bash
cd /Users/main/Documents/projects/viva-croatia-testbed
pnpm add -D vitest @vitest/coverage-v8 vite-tsconfig-paths
```
Expected: install completes; `node_modules/.bin/vitest` exists.

- [ ] **Step 2: Add the vitest config**

Create `vitest.config.ts`:
```ts
import { defineConfig } from 'vitest/config'
import tsconfigPaths from 'vite-tsconfig-paths'

export default defineConfig({
  plugins: [tsconfigPaths()],
  test: {
    environment: 'node',
    include: ['**/*.test.ts'],
    coverage: {
      provider: 'v8',
      reporter: ['json'],
      reportsDirectory: './coverage',
      // Cover app/lib source; the report is read by behavior-runner.
      include: ['app/**', 'lib/**'],
    },
  },
})
```

- [ ] **Step 3: Add the `test:unit` script**

In `package.json` `scripts`, add:
```json
"test:unit": "vitest run"
```

- [ ] **Step 4: Write the failing unit test**

Create `lib/webauthn.test.ts`:
```ts
import { describe, it, expect, vi, beforeEach } from 'vitest'

// Mock the DB boundary — the only external/nondeterministic dependency.
// Everything else (the expiry decision) runs as the real implementation.
vi.mock('./prisma', () => ({
  prisma: {
    webAuthnChallenge: {
      findUnique: vi.fn(),
      delete: vi.fn(),
    },
  },
}))

import { verifyChallenge } from './webauthn'
import { prisma } from './prisma'

describe('verifyChallenge', () => {
  beforeEach(() => {
    vi.clearAllMocks()
  })

  it('rejects an expired challenge', async () => {
    // expiresAt one minute in the past → expired
    ;(prisma.webAuthnChallenge.findUnique as any).mockResolvedValue({
      challenge: 'abc',
      userId: null,
      type: 'authentication',
      expiresAt: new Date(Date.now() - 60_000),
    })

    const result = await verifyChallenge('abc')

    expect(result.valid).toBe(false)
    // An expired challenge is deleted (single-use / cleanup).
    expect(prisma.webAuthnChallenge.delete).toHaveBeenCalledWith({
      where: { challenge: 'abc' },
    })
  })
})
```

- [ ] **Step 5: Run to verify it passes (real behavior already works)**

Run: `cd /Users/main/Documents/projects/viva-croatia-testbed && pnpm test:unit`
Expected: 1 test passes (`verifyChallenge > rejects an expired challenge`). The behavior already exists in the code, so this is GREEN immediately — the test documents and locks it. (If it errors on module resolution, confirm `vite-tsconfig-paths` is installed; the only imports in play are `./webauthn`, the mocked `./prisma`, and `@simplewebauthn/server`.)

- [ ] **Step 6: Re-point BEH-002 in the spec to the vitest test**

In `knowledge-base/specs/auth/SPEC-001-passkey-login.md` frontmatter, replace the **BEH-002** record and add `level` to all three behaviors:
```yaml
  - behavior_id: BEH-001
    title: Successful passkey login
    state: proposed
    level: e2e
    adapter: cucumber
    locator: features/auth/passkey-login.feature#successful-passkey-login
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
```
In the `## Behavior` table, update the BEH-002 row's `Verified by` to `lib/webauthn.test.ts (vitest)` and its State to `accepted`.

- [ ] **Step 7: Remove the now-native BEH-002 scenario from the feature file**

In `features/auth/passkey-login.feature`, delete the `@BEH-002` scenario block (its title is `Login with an expired challenge is rejected`). BEH-002 is now verified by vitest, so leaving a `@BEH-002` Gherkin tag would be an orphan tag. Leave `@BEH-001` and `@BEH-003` intact.

- [ ] **Step 8: Run deterministic verify (expect OK)**

Run:
```bash
python "/Users/main/.claude/plugins/cache/freya-devkit/freya-devkit/0.1.0/skills/spec-manager/scripts/verify_links.py" \
  --dir /Users/main/Documents/projects/viva-croatia-testbed/knowledge-base/specs --format text
```
Expected: `OK — all behavior links pass Tier-1 integrity checks.` (exit 0). BEH-002's locator resolves to a real file (`lib/webauthn.test.ts`), it has no `TODO(scaffold)` marker, and the feature file no longer carries an orphan `@BEH-002`.

- [ ] **Step 9: Commit (testbed)**

```bash
cd /Users/main/Documents/projects/viva-croatia-testbed
git add package.json pnpm-lock.yaml vitest.config.ts lib/webauthn.test.ts \
  knowledge-base/specs/auth/SPEC-001-passkey-login.md features/auth/passkey-login.feature
git -c user.name="Alex" -c user.email="claude.stifle198@simplelogin.com" \
  commit -m "test(unit): BEH-002 expired-challenge as vitest behavior (native adapter)"
```

---

### Task 4: Wire the runner to execute a unit behavior and emit a fingerprint

**Repo:** freya-devkit (plugin); verified against the testbed.

**Files:**
- Modify: `skills/behavior-runner/scripts/run_behaviors.py`
- Modify: `skills/behavior-runner/scripts/test_run_behaviors.py`

**Interfaces:**
- Consumes: `parse_locator(locator)` from spec-manager's `adapters.py` (splits `path::fragment` or `path#fragment` into `(path, fragment)`).
- Consumes: `load_accepted_behaviors`, `coverage_files_to_keys`, `shape_fingerprint` (Tasks 1-2).
- Produces: `run_unit_behavior(behavior, project_dir) -> dict` (a fingerprint) and a `--emit-fingerprints` mode printing `{version, commit, fingerprints}`.

- [ ] **Step 1: Write the failing test (locator → vitest argv)**

The subprocess run itself is verified against the testbed in Step 4; here we unit-test the pure piece: turning a behavior locator into the vitest command argv. Append to `test_run_behaviors.py`:
```python
class VitestArgvTest(unittest.TestCase):
    def test_builds_filtered_vitest_argv(self):
        beh = {
            "behavior_id": "BEH-002",
            "adapter": "vitest",
            "locator": "lib/webauthn.test.ts::rejects an expired challenge",
        }
        argv, test_file = run_behaviors.vitest_argv(beh)
        self.assertEqual(test_file, "lib/webauthn.test.ts")
        self.assertEqual(
            argv,
            ["pnpm", "vitest", "run", "lib/webauthn.test.ts",
             "-t", "rejects an expired challenge", "--coverage"],
        )
```

- [ ] **Step 2: Run to verify it fails**

Run: `cd skills/behavior-runner/scripts && python -m unittest test_run_behaviors -v`
Expected: FAIL — `AttributeError: ... 'vitest_argv'`.

- [ ] **Step 3: Implement execution + emit**

Add to `run_behaviors.py` (and extend `main`). Reuse `parse_locator` from adapters.py:
```python
# adapters.py lives alongside frontmatter.py in spec-manager/scripts (already on sys.path).
from adapters import parse_locator  # noqa: E402


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
    if result.returncode != 0 or not os.path.exists(cov_path):
        # Test failed or produced no coverage -> coverage-unknown, never faked.
        sys.stderr.write(result.stdout + result.stderr)
        return shape_fingerprint([], commit)

    with open(cov_path, encoding="utf-8") as f:
        coverage_final = json.load(f)
    keys = coverage_files_to_keys(coverage_final, project_dir, exclude={test_file})
    return shape_fingerprint(keys, commit)
```
Then extend `main`: add the `--emit-fingerprints` flag and branch (insert before the final `print(json.dumps(...))`):
```python
    parser.add_argument("--emit-fingerprints", action="store_true",
                        help="Run each matching behavior and emit fingerprints JSON.")
    # ... (args = parser.parse_args() already above) ...

    if args.emit_fingerprints:
        fingerprints = {}
        for b in behaviors:
            if b.get("level") == "unit" and b.get("adapter") == "vitest":
                fingerprints[b["behavior_id"]] = run_unit_behavior(b, args.project)
            else:
                # Non-unit levels are produced by later plans; mark unknown for now.
                fingerprints[b["behavior_id"]] = {"coverage": "unknown", "exercises": []}
        print(json.dumps({
            "version": 1,
            "commit": _git_head(args.project),
            "fingerprints": fingerprints,
        }, indent=2))
        return 0
```
(Place this branch after `--list` and before the default summary print.)

- [ ] **Step 4: Run the unit test to verify pass, then prove end-to-end on the testbed**

Run the pure test: `cd skills/behavior-runner/scripts && python -m unittest test_run_behaviors -v`
Expected: PASS (7 tests).

Then the real end-to-end emit:
```bash
python skills/behavior-runner/scripts/run_behaviors.py \
  --project /Users/main/Documents/projects/viva-croatia-testbed --level unit --emit-fingerprints
```
Expected JSON: `fingerprints.BEH-002.coverage == "observed"` and `exercises` contains `{"path": "lib/webauthn.ts", "source": "observed", "confidence": 0.8, "freshness": "<commit>"}`. (`lib/webauthn.test.ts` itself is excluded; `node_modules` dropped.)

- [ ] **Step 5: Commit**

```bash
git add skills/behavior-runner/scripts/
git commit -m "feat(behavior-runner): run unit behavior via vitest + emit observed fingerprint"
```

---

## Self-Review

**Spec coverage (against `02-phase-2.md`):** This plan delivers the `behavior-runner` skill (§5b/§9), the **unit-level** coverage path (§4 "in-process runner-native"), the **producer-only** boundary (it emits fingerprints, never `behavior.json` — §3/§5b), the **coverage-unknown-never-silent** rule (§3, Task 2/4), and the **unit half of the two-level loop** (BEH-002, §7). Out of this plan's scope (correctly): integration coverage + the source-map spike (Plan 3), `behavior.json` ownership + Direction A/B (Plan 4 = behavior-graph), F5/F3 (later), measurement aggregation (after both levels capture). The `level` field is introduced as spec data here; documenting it in spec-manager's schema/SKILL.md is a small follow-up folded into Plan 4.

**Placeholder scan:** No TBD/TODO in code. The only `TODO(scaffold)` reference is the literal marker string discussed in Task 3 Step 7 (a real artifact). All steps that change code show the code; all commands have expected output.

**Type/name consistency:** `load_accepted_behaviors`, `coverage_files_to_keys`, `shape_fingerprint`, `vitest_argv`, `run_unit_behavior` are defined once and referenced consistently. The fingerprint shape (`{coverage, exercises:[{path,source,confidence,freshness}]}`) is identical in Task 2's `shape_fingerprint`, the SKILL.md contract, and Task 4's emit. The locator `lib/webauthn.test.ts::rejects an expired challenge` is identical in the test fixture (Task 1), the spec edit (Task 3 Step 6), and the vitest argv (Task 4). `parse_locator` is reused from adapters.py, not redefined.

**Known iteration point (honest):** Task 3 Step 5 — vitest importing `lib/webauthn.ts` pulls in `@simplewebauthn/server` (ESM). vitest handles ESM natively (unlike the cucumber+tsx CJS path that triggered F10), so this should load cleanly; if a stray ESM-interop issue appears, it is isolated to the test harness (mock surface), not the behavior. Task 4 Step 4's coverage key set depends on vitest's v8 provider emitting `coverage-final.json` under `./coverage`; the `include: ['app/**','lib/**']` config keeps the report scoped to source.

## Next plan

**Plan 3 — `behavior-runner` integration level:** the source-map remap **spike** (does V8 coverage of the running `next dev` app remap to source keys?) + the boot-per-behavior capture for BEH-003, producing its `observed` fingerprint (or an honest `coverage: unknown` if remap proves unreliable). **Plan 4 — `behavior-graph`:** own `behavior.json`, project spec frontmatter (incl. `level`), ingest+merge the runner's fingerprints by trust, serve Direction A (via code-graph) and Direction B; fold in F5/F3 and the measurement aggregation.
