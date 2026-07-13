# Phase 2 — Plan 3: `behavior-runner` integration level (static via code-graph) — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Give the `behavior-runner` an **integration-level** fingerprint path: an accepted integration behavior declares an `entry` point, and the runner emits a **`source: static`** fingerprint built from code-graph's transitive import closure of that entry — proving it on the testbed with BEH-003.

**Architecture:** Observed coverage is not capturable at the integration level on Next.js without a framework-specific V8+CDP adapter (dogfooding **F11**; deferred — see `parking-lot.md`). So integration uses the **framework-agnostic static fallback**: `entry` file → `code-graph --dependencies` (transitive closure) → `exercises` edges tagged `source: static`, `coverage: "static"`. Static over-approximates, which is the **safe** direction for blast radius (a false "might be affected" only runs an extra test; a false "not affected" misses a regression). Unit-level observed coverage (Plan 2) is unchanged and remains the precise source.

**Tech Stack:** Python 3 (stdlib only); reuses `code-graph/scripts/graph_ops.py --dependencies` (already fixed for alias/closure resolution). Proven on the **testbed** (`/Users/main/Documents/projects/viva-croatia-testbed`).

## Global Constraints

- Plugin scripts are **stdlib-only**; the runner shells out to `graph_ops.py` by path.
- Plugin code → **freya-devkit** repo, branch `feat/behavior-layer` (normal `git`, user `Alex`).
- Testbed changes → **testbed** repo with `git -c user.name="Alex" -c user.email="claude.stifle198@simplelogin.com"`. Never touch `/Users/main/Documents/areas/viva-croatia/webapp`.
- Producer only: emit fingerprints to stdout; never write `behavior.json`.
- Coverage-unknown, never silent: an integration behavior with no `entry`, a missing `entry` file, or no graph edges yields `coverage: "unknown"` with a `reason` — never a fabricated edge.
- The `coverage` field gains a third value: **`observed | static | unknown`**. Each `exercises` edge keeps its own `source` (`observed | static`). Static confidence is lower than observed.

## File Structure

**freya-devkit (plugin):**
- `skills/behavior-runner/scripts/run_behaviors.py` — generalize `shape_fingerprint`; add `static_exercises`, `_code_graph_deps`, `static_fingerprint`; dispatch `integration` in `main` (modify).
- `skills/behavior-runner/scripts/test_run_behaviors.py` — add static tests (modify).
- `skills/behavior-runner/SKILL.md` — document the integration/static path + coverage enum (modify).
- `docs/design/behavior-layer/02-phase-2.md` — §3 coverage enum note (modify).

**viva-croatia-testbed:**
- `knowledge-base/specs/auth/SPEC-001-passkey-login.md` — add `entry` to BEH-003 (modify).

---

### Task 1: Generalize `shape_fingerprint` for `source`; add `static_exercises`

**Repo:** freya-devkit (plugin).

**Files:**
- Modify: `skills/behavior-runner/scripts/run_behaviors.py`
- Modify: `skills/behavior-runner/scripts/test_run_behaviors.py`

**Interfaces:**
- Produces: `shape_fingerprint(exercised_keys, commit, source="observed", confidence=None, reason=None)` — `coverage` equals `source` when keys present (default per-source confidence: observed `0.8`, static `0.5`), else `coverage: "unknown"` (+ `reason` when given). Observed behavior is unchanged for existing callers.
- Produces: `static_exercises(entry, deps) -> list[str]` — `sorted(set([entry] + deps))`.

- [ ] **Step 1: Write the failing tests**

Append to `skills/behavior-runner/scripts/test_run_behaviors.py`:
```python
class ShapeFingerprintStaticTest(unittest.TestCase):
    def test_static_source_sets_coverage_and_edge_source(self):
        fp = run_behaviors.shape_fingerprint(
            ["app/api/x/route.ts", "lib/webauthn.ts"], "c1", source="static"
        )
        self.assertEqual(fp["coverage"], "static")
        self.assertEqual(
            fp["exercises"],
            [
                {"path": "app/api/x/route.ts", "source": "static", "confidence": 0.5, "freshness": "c1"},
                {"path": "lib/webauthn.ts", "source": "static", "confidence": 0.5, "freshness": "c1"},
            ],
        )

    def test_observed_default_unchanged(self):
        fp = run_behaviors.shape_fingerprint(["lib/webauthn.ts"], "c1")
        self.assertEqual(fp["coverage"], "observed")
        self.assertEqual(fp["exercises"][0]["source"], "observed")
        self.assertEqual(fp["exercises"][0]["confidence"], 0.8)


class StaticExercisesTest(unittest.TestCase):
    def test_includes_entry_dedups_and_sorts(self):
        keys = run_behaviors.static_exercises(
            "app/api/x/route.ts", ["lib/webauthn.ts", "app/api/x/route.ts", "lib/prisma.ts"]
        )
        self.assertEqual(keys, ["app/api/x/route.ts", "lib/prisma.ts", "lib/webauthn.ts"])
```

- [ ] **Step 2: Run to verify they fail**

Run: `cd skills/behavior-runner/scripts && python -m unittest test_run_behaviors -v`
Expected: FAIL — `AttributeError: ... 'static_exercises'`, and the static `shape_fingerprint` test fails on the unexpected `source`/`coverage` shape.

- [ ] **Step 3: Implement**

In `run_behaviors.py`, add the static-confidence constant next to `OBSERVED_CONFIDENCE`:
```python
STATIC_CONFIDENCE = 0.5
```
Replace the existing `shape_fingerprint` with the generalized version:
```python
def shape_fingerprint(exercised_keys, commit, source="observed", confidence=None, reason=None):
    """Build a per-behavior fingerprint. `source` ("observed"|"static") sets the
    coverage value and each edge's source; unknown when there are no keys."""
    if not exercised_keys:
        result = {"coverage": "unknown", "exercises": []}
        if reason is not None:
            result["reason"] = reason
        return result
    if confidence is None:
        confidence = STATIC_CONFIDENCE if source == "static" else OBSERVED_CONFIDENCE
    return {
        "coverage": source,
        "exercises": [
            {"path": k, "source": source, "confidence": confidence, "freshness": commit}
            for k in exercised_keys
        ],
    }


def static_exercises(entry, deps):
    """The static fingerprint key set: the entry file plus its dependency closure."""
    return sorted({entry, *deps})
```

- [ ] **Step 4: Run to verify pass**

Run: `cd skills/behavior-runner/scripts && python -m unittest test_run_behaviors -v`
Expected: PASS (all prior tests + the 3 new ones). Confirm the existing observed/unknown tests still pass (the signature change is backward-compatible — no caller passed `confidence` positionally).

- [ ] **Step 5: Commit**

```bash
git add skills/behavior-runner/scripts/
git commit -m "feat(behavior-runner): generalize shape_fingerprint for static source + static_exercises"
```

---

### Task 2: Add `static_fingerprint` (code-graph closure) + dispatch integration

**Repo:** freya-devkit (plugin).

**Files:**
- Modify: `skills/behavior-runner/scripts/run_behaviors.py`
- Modify: `skills/behavior-runner/scripts/test_run_behaviors.py`
- Modify: `skills/behavior-runner/SKILL.md`
- Modify: `docs/design/behavior-layer/02-phase-2.md`

**Interfaces:**
- Consumes: `code-graph/scripts/graph_ops.py --dependencies <entry> --dir <project> --format json` → a JSON array of project-relative dependency keys (verified: returns `["lib/prisma.ts","lib/webauthn.ts"]` for the BEH-003 route).
- Consumes: `shape_fingerprint`, `static_exercises`, `_git_head` (Tasks 1 / Plan 2).
- Produces: `static_fingerprint(behavior, project_dir) -> dict` and an `integration`-level branch in `main`'s `--emit-fingerprints`.

- [ ] **Step 1: Write the failing tests**

Append to `test_run_behaviors.py`:
```python
import unittest.mock as mock


class StaticFingerprintTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.proj = self.tmp.name
        os.makedirs(os.path.join(self.proj, "app", "api", "x"))
        open(os.path.join(self.proj, "app", "api", "x", "route.ts"), "w").close()

    def tearDown(self):
        self.tmp.cleanup()

    def test_no_entry_is_unknown_with_reason(self):
        fp = run_behaviors.static_fingerprint({"behavior_id": "BEH-X"}, self.proj)
        self.assertEqual(fp["coverage"], "unknown")
        self.assertEqual(fp["reason"], "no-entry")

    def test_missing_entry_file_is_unknown_with_reason(self):
        beh = {"behavior_id": "BEH-X", "entry": "app/api/x/missing.ts"}
        fp = run_behaviors.static_fingerprint(beh, self.proj)
        self.assertEqual(fp["coverage"], "unknown")
        self.assertEqual(fp["reason"], "entry-missing")

    def test_entry_plus_closure_is_static(self):
        beh = {"behavior_id": "BEH-X", "entry": "app/api/x/route.ts"}
        with mock.patch.object(run_behaviors, "_code_graph_deps", return_value=["lib/webauthn.ts", "lib/prisma.ts"]):
            fp = run_behaviors.static_fingerprint(beh, self.proj)
        self.assertEqual(fp["coverage"], "static")
        self.assertEqual(
            [e["path"] for e in fp["exercises"]],
            ["app/api/x/route.ts", "lib/prisma.ts", "lib/webauthn.ts"],
        )
        self.assertTrue(all(e["source"] == "static" for e in fp["exercises"]))
```

- [ ] **Step 2: Run to verify they fail**

Run: `cd skills/behavior-runner/scripts && python -m unittest test_run_behaviors -v`
Expected: FAIL — `AttributeError: ... 'static_fingerprint'` / `'_code_graph_deps'`.

- [ ] **Step 3: Implement**

In `run_behaviors.py`, add the code-graph path constant near the spec-scripts insert:
```python
_CODE_GRAPH = Path(__file__).resolve().parents[2] / "code-graph" / "scripts" / "graph_ops.py"
```
Add the two functions (above `main`):
```python
def _code_graph_deps(entry, project_dir):
    """Transitive import-closure of `entry` from code-graph (project-relative keys)."""
    try:
        out = subprocess.run(
            [sys.executable, str(_CODE_GRAPH), "--dependencies", entry,
             "--dir", project_dir, "--format", "json"],
            capture_output=True, text=True, check=True,
        )
        data = json.loads(out.stdout)
        return data if isinstance(data, list) else []
    except (subprocess.CalledProcessError, json.JSONDecodeError, FileNotFoundError):
        return []


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
    deps = _code_graph_deps(entry, project_dir)
    return shape_fingerprint(
        static_exercises(entry, deps), commit, source="static", confidence=STATIC_CONFIDENCE
    )
```
In `main`'s `--emit-fingerprints` loop, add the integration branch between the unit branch and the `else`:
```python
        for b in behaviors:
            if b.get("level") == "unit" and b.get("adapter") == "vitest":
                fingerprints[b["behavior_id"]] = run_unit_behavior(b, args.project)
            elif b.get("level") == "integration":
                fingerprints[b["behavior_id"]] = static_fingerprint(b, args.project)
            else:
                fingerprints[b["behavior_id"]] = shape_fingerprint(
                    [], commit, reason="level-deferred"
                )
```
(`commit` is the single `_git_head(args.project)` already computed before the loop in Plan 2.)

- [ ] **Step 4: Run to verify pass**

Run: `cd skills/behavior-runner/scripts && python -m unittest test_run_behaviors -v`
Expected: PASS (all prior + 3 new).

- [ ] **Step 5: Update docs**

In `skills/behavior-runner/SKILL.md`: in the per-level table, change the `integration` row mechanism to `running app over HTTP; observed coverage is a deferred per-framework V8+CDP adapter, so the **static** code-graph closure of a declared **entry** is used (source: static)`. In the Output contract, note `coverage` is `observed | static | unknown`, that integration behaviors require an `entry` field, and the unknown `reason` set now includes `no-entry` / `entry-missing` (alongside `level-deferred` / `test-failed` / `no-coverage`).

In `docs/design/behavior-layer/02-phase-2.md` §3, update the coverage bullet so the enum reads `observed | static | unknown` and note integration behaviors declare an `entry` whose code-graph closure becomes `source: static` edges.

- [ ] **Step 6: Commit**

```bash
git add skills/behavior-runner/ docs/design/behavior-layer/02-phase-2.md
git commit -m "feat(behavior-runner): static integration fingerprint via code-graph closure"
```

---

### Task 3: Declare BEH-003 `entry` on the testbed and prove the static fingerprint

**Repo:** viva-croatia-testbed (proving ground); the runner is invoked from the plugin by path.

**Files:**
- Modify: `knowledge-base/specs/auth/SPEC-001-passkey-login.md` (add `entry` to BEH-003)

**Interfaces:**
- Consumes: the integration dispatch + `static_fingerprint` (Task 2); a current code-graph `graph.json` for the testbed.
- Produces: an emitted `BEH-003` fingerprint with `coverage: "static"` and `exercises` covering the route + its closure.

- [ ] **Step 1: Add the `entry` field to BEH-003**

In `knowledge-base/specs/auth/SPEC-001-passkey-login.md`, in the BEH-003 behavior record, add an `entry` line (the route the integration test drives):
```yaml
  - behavior_id: BEH-003
    title: Unknown email does not reveal whether a user exists
    state: accepted
    level: integration
    adapter: cucumber
    locator: features/auth/passkey-login.feature#unknown-email-does-not-reveal-whether-a-user-exists
    entry: app/api/auth/passkey/authenticate/start/route.ts
```

- [ ] **Step 2: Refresh the code-graph so the closure is current**

Run (non-interactive; the graph cache is git-ignored):
```bash
python "/Users/main/.claude/plugins/cache/freya-devkit/freya-devkit/0.1.0/skills/code-graph/scripts/graph_ops.py" \
  --update --dir /Users/main/Documents/projects/viva-croatia-testbed --non-interactive
```
Expected: graph updates without prompting. (Sanity check the entry resolves:
`… --dependencies app/api/auth/passkey/authenticate/start/route.ts --dir <testbed> --format json` → `["lib/prisma.ts","lib/webauthn.ts"]`.)

- [ ] **Step 3: Emit fingerprints and verify BEH-003 is static**

Run:
```bash
python /Users/main/Documents/projects/freya-devkit/skills/behavior-runner/scripts/run_behaviors.py \
  --project /Users/main/Documents/projects/viva-croatia-testbed --emit-fingerprints
```
Expected JSON: `fingerprints.BEH-003.coverage == "static"`, with `exercises` paths exactly `["app/api/auth/passkey/authenticate/start/route.ts", "lib/prisma.ts", "lib/webauthn.ts"]`, each `source: "static"`, `confidence: 0.5`. (BEH-002 stays `observed`; BEH-001 stays `unknown`/`level-deferred`.)

- [ ] **Step 4: Confirm deterministic verify is still green**

Run:
```bash
python "/Users/main/.claude/plugins/cache/freya-devkit/freya-devkit/0.1.0/skills/spec-manager/scripts/verify_links.py" \
  --dir /Users/main/Documents/projects/viva-croatia-testbed/knowledge-base/specs --format text
```
Expected: `OK …` (exit 0). The added `entry` field is preserved/ignored by the parser (unknown fields are non-fatal); locator integrity is unchanged.

- [ ] **Step 5: Commit (testbed)**

```bash
cd /Users/main/Documents/projects/viva-croatia-testbed
git add knowledge-base/specs/auth/SPEC-001-passkey-login.md
git -c user.name="Alex" -c user.email="claude.stifle198@simplelogin.com" \
  commit -m "spec(SPEC-001): declare BEH-003 entry point for static integration fingerprint"
```

---

## Self-Review

**Spec coverage (against `02-phase-2.md` + F11 decision):** Delivers the integration-level fingerprint path as the **static fallback** (§4 / F11), framework-agnostic via code-graph (the user's "use code-graph" call), with observed-via-CDP correctly deferred (`parking-lot.md`). `coverage` gains `static`; edges carry `source: static` at lower confidence (§2 "static edges, lower trust"). Coverage-unknown-never-silent holds: `no-entry` / `entry-missing` reasons. Out of scope (correct): `behavior.json` ownership + Direction A/B merge (Plan 4 = behavior-graph), observed integration capture (deferred adapter), measurement aggregation (after Plan 4).

**Placeholder scan:** No TBD/TODO. Every code step shows the code; every command states expected output (the BEH-003 closure is the empirically-verified `["lib/prisma.ts","lib/webauthn.ts"]`).

**Type/name consistency:** `shape_fingerprint(..., source=, confidence=, reason=)`, `static_exercises(entry, deps)`, `_code_graph_deps(entry, project_dir)`, `static_fingerprint(behavior, project_dir)` are defined once and used consistently. The fingerprint shape (`{coverage, exercises:[{path,source,confidence,freshness}], reason?}`) matches Plan 2 plus the `static` coverage value. The entry `app/api/auth/passkey/authenticate/start/route.ts` is identical in the spec edit (Task 3) and the expected output (Task 3 Step 3). The signature generalization is backward-compatible (verified: no Plan-2 caller passes `confidence` positionally).

**Known iteration point (honest):** Task 3 Step 3's expected `exercises` set assumes the testbed graph resolves the route's closure to exactly prisma + webauthn (confirmed today via `--dependencies`). If `code-graph --update` picks up unrelated drift, the set could differ; the assertion is on BEH-003's three known keys, and any divergence is a code-graph result to inspect, not a runner bug. `entry`-field validation in `verify_links` (does the entry resolve?) is a deliberate future enhancement, noted in `parking-lot.md`-adjacent carried items, not built here.

## Next plan

**Plan 4 — `behavior-graph`:** own `behavior.json`; project spec frontmatter (incl. `level`/`entry`); ingest + merge the runner's fingerprints by trust (`observed` > `static`), consuming the `reason` discriminator (preserve a prior `observed` edge on `level-deferred`, invalidate on `test-failed`); serve Direction A (intersect a code change's blast radius with fingerprints) and Direction B; fold in F5 (never-synced guard) and F3 (`init` `.gitkeep`), and begin the §6 measurement (static-vs-observed breadth/FP/runtime).
