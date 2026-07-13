# Phase 2 — Plan 5: Closeout (activate in wrap-up + F5/F3 + measurement) — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make the behavior graph **active in the everyday workflow** — wrap-up's Phase 3.5 uses Direction A to re-run only the *affected* accepted behaviors and blocks on a deterministic regression — and close out Phase 2's carried fixes (**F5**, **F3**) and the §6 **measurement**.

**Architecture:** Encapsulate the Phase-3.5 regression logic in a testable `behavior-graph --check --base <commit>` command: it diffs `base..HEAD`, runs **Direction A** to find affected accepted behaviors, re-runs *only those* via a new `behavior-runner --only` filter, merges the results back into `behavior.json` (incremental update), and exits non-zero if any affected behavior is `test-failed`. wrap-up's Phase 3.5 then just calls this command and blocks on its exit code (keeping the SKILL.md prose thin). F5 (never-synced guard) and F3 (`init` `.gitkeep`) are SKILL.md changes; measurement is an empirical write-up.

**Tech Stack:** Python 3 (stdlib only). Builds on `behavior-runner` and `behavior-graph` (Plans 2–4). Proven on the **testbed** (`/Users/main/Documents/projects/viva-croatia-testbed`).

## Global Constraints

- Plugin scripts are **stdlib-only**; shell out to sibling skills by path.
- Plugin code → **freya-devkit** repo, branch `feat/behavior-layer` (normal `git`, user `Alex`).
- `behavior-graph` owns `behavior.json`; `code-graph` stays pure (only queried).
- **Only deterministic failures block** (vision §8): a `test-failed` result for an *affected, accepted* behavior blocks; everything else is advisory.
- `--check` re-runs **only the affected** accepted behaviors (incremental, Direction A) — never the whole suite.
- Merge by trust is unchanged (`observed > static`; `test-failed` invalidates; other `unknown` preserves).

## File Structure

**freya-devkit (plugin):**
- `skills/behavior-runner/scripts/run_behaviors.py` + its test — add `--only` filter (modify).
- `skills/behavior-graph/scripts/behavior_graph.py` + its test — add `--check`/`regression_check` (modify).
- `skills/wrap-up/SKILL.md` — Phase 3.5 rewrite + F5 never-synced guard (modify).
- `skills/spec-manager/SKILL.md` — F3 `init` `.gitkeep` (modify).
- `docs/design/behavior-layer/02-phase-2.md` §6 + `docs/design/behavior-layer/dogfooding-notes.md` — measurement results (modify).

---

### Task 1: `behavior-runner --only` filter

**Repo:** freya-devkit (plugin).

**Files:**
- Modify: `skills/behavior-runner/scripts/run_behaviors.py`
- Modify: `skills/behavior-runner/scripts/test_run_behaviors.py`

**Interfaces:**
- Produces: a `--only BEH-NNN [BEH-NNN ...]` CLI flag that restricts `--list`/`--emit-fingerprints` to the named accepted behaviors. Implemented via `filter_only(behaviors, only) -> list` (pure).

- [ ] **Step 1: Write the failing test**

Append to `skills/behavior-runner/scripts/test_run_behaviors.py`:
```python
class FilterOnlyTest(unittest.TestCase):
    def test_keeps_only_named_behaviors(self):
        behaviors = [
            {"behavior_id": "BEH-001"},
            {"behavior_id": "BEH-002"},
            {"behavior_id": "BEH-003"},
        ]
        got = run_behaviors.filter_only(behaviors, ["BEH-003", "BEH-001"])
        self.assertEqual([b["behavior_id"] for b in got], ["BEH-001", "BEH-003"])

    def test_none_filter_returns_all(self):
        behaviors = [{"behavior_id": "BEH-001"}, {"behavior_id": "BEH-002"}]
        self.assertEqual(run_behaviors.filter_only(behaviors, None), behaviors)
```

- [ ] **Step 2: Run to verify it fails**

Run: `cd skills/behavior-runner/scripts && python -m unittest test_run_behaviors -v`
Expected: FAIL — `AttributeError: ... 'filter_only'`.

- [ ] **Step 3: Implement**

Add to `run_behaviors.py` (above `main`):
```python
def filter_only(behaviors, only):
    """Restrict a behavior list to the given BEH ids (order: by the behavior list)."""
    if not only:
        return behaviors
    wanted = set(only)
    return [b for b in behaviors if b.get("behavior_id") in wanted]
```
In `main`, add the flag (next to `--level`):
```python
    parser.add_argument("--only", nargs="+", metavar="BEH",
                        help="Restrict to these accepted behavior ids.")
```
Then apply it immediately after `behaviors = load_accepted_behaviors(...)` (which is computed once near the top of `main`, before the `--list`/`--emit-fingerprints` branches):
```python
    behaviors = filter_only(behaviors, args.only)
```

- [ ] **Step 4: Run to verify it passes**

Run: `cd skills/behavior-runner/scripts && python -m unittest test_run_behaviors -v`
Expected: PASS (all prior + 2 new). Spot-check the wiring against the testbed:
```bash
python skills/behavior-runner/scripts/run_behaviors.py \
  --project /Users/main/Documents/projects/viva-croatia-testbed --emit-fingerprints --only BEH-002
```
Expected: `fingerprints` contains only `BEH-002` (observed), not BEH-003.

- [ ] **Step 5: Commit**

```bash
git add skills/behavior-runner/scripts/
git commit -m "feat(behavior-runner): --only filter to run a subset of behaviors"
```

---

### Task 2: `behavior-graph --check` (incremental Direction-A regression check)

**Repo:** freya-devkit (plugin).

**Files:**
- Modify: `skills/behavior-graph/scripts/behavior_graph.py`
- Modify: `skills/behavior-graph/scripts/test_behavior_graph.py`

**Interfaces:**
- Consumes: `direction_a`, `merge_fingerprint`, `load_behavior_json`/`write_behavior_json` (Plan 4); `behavior-runner --only` (Task 1).
- Produces: `_changed_files(base, project_dir) -> list[str]` (git diff), `_run_behavior_runner(project_dir, only=None)` (extended), `regression_check(project_dir, base) -> tuple[dict, int]` (report + exit code), and a `--check --base COMMIT` CLI branch.

- [ ] **Step 1: Write the failing tests**

Append to `skills/behavior-graph/scripts/test_behavior_graph.py`:
```python
class RegressionCheckTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.proj = self.tmp.name
        behavior_graph.write_behavior_json(self.proj, {
            "version": 1, "commit": "base",
            "behaviors": {
                "BEH-002": {"spec_id": "SPEC-001", "state": "accepted", "level": "unit",
                            "adapter": "vitest", "locator": "x", "coverage": "observed",
                            "exercises": [{"path": "lib/webauthn.ts"}]},
                "BEH-003": {"spec_id": "SPEC-001", "state": "accepted", "level": "integration",
                            "adapter": "cucumber", "locator": "y", "coverage": "static",
                            "exercises": [{"path": "lib/other.ts"}]},
            },
        })

    def tearDown(self):
        self.tmp.cleanup()

    def test_no_affected_exits_zero(self):
        with mock.patch.object(behavior_graph, "_changed_files", return_value=["README.md"]), \
             mock.patch.object(behavior_graph, "_code_graph_impact", return_value={"README.md"}):
            report, code = behavior_graph.regression_check(self.proj, "base")
        self.assertEqual(code, 0)
        self.assertEqual(report["affected"], [])

    def test_affected_passing_exits_zero(self):
        runner_out = {"version": 1, "commit": "new", "fingerprints": {
            "BEH-002": {"coverage": "observed", "exercises": [{"path": "lib/webauthn.ts"}]}}}
        with mock.patch.object(behavior_graph, "_changed_files", return_value=["lib/webauthn.ts"]), \
             mock.patch.object(behavior_graph, "_code_graph_impact", return_value={"lib/webauthn.ts"}), \
             mock.patch.object(behavior_graph, "_run_behavior_runner", return_value=runner_out) as run:
            report, code = behavior_graph.regression_check(self.proj, "base")
        run.assert_called_once_with(self.proj, only=["BEH-002"])  # only the affected re-run
        self.assertEqual(code, 0)
        self.assertEqual(report["affected"], ["BEH-002"])
        self.assertEqual(report["failed"], [])

    def test_affected_failing_blocks(self):
        runner_out = {"version": 1, "commit": "new", "fingerprints": {
            "BEH-002": {"coverage": "unknown", "exercises": [], "reason": "test-failed"}}}
        with mock.patch.object(behavior_graph, "_changed_files", return_value=["lib/webauthn.ts"]), \
             mock.patch.object(behavior_graph, "_code_graph_impact", return_value={"lib/webauthn.ts"}), \
             mock.patch.object(behavior_graph, "_run_behavior_runner", return_value=runner_out):
            report, code = behavior_graph.regression_check(self.proj, "base")
        self.assertEqual(code, 1)
        self.assertEqual(report["failed"], ["BEH-002"])
```

- [ ] **Step 2: Run to verify they fail**

Run: `cd skills/behavior-graph/scripts && python -m unittest test_behavior_graph -v`
Expected: FAIL — `AttributeError: ... 'regression_check'` / `'_changed_files'`.

- [ ] **Step 3: Implement**

In `behavior_graph.py`, extend `_run_behavior_runner` to accept `only`:
```python
def _run_behavior_runner(project_dir, only=None):
    argv = [sys.executable, str(_RUNNER), "--project", project_dir, "--emit-fingerprints"]
    if only:
        argv += ["--only", *only]
    out = subprocess.run(argv, capture_output=True, text=True, check=True)
    return json.loads(out.stdout)
```
Add `_changed_files` and `regression_check` (above `main`):
```python
def _changed_files(base, project_dir):
    """Project-relative files changed in base..HEAD (empty on git error)."""
    try:
        out = subprocess.run(
            ["git", "-C", project_dir, "diff", "--name-only", f"{base}..HEAD"],
            capture_output=True, text=True, check=True,
        )
        return [ln.strip() for ln in out.stdout.splitlines() if ln.strip()]
    except (subprocess.CalledProcessError, FileNotFoundError, OSError):
        return []


def regression_check(project_dir, base):
    """Direction-A regression check: re-run only the accepted behaviors a change
    touches; block (exit 1) if any is test-failed. Returns (report, exit_code)."""
    data = load_behavior_json(project_dir)
    behaviors = data.get("behaviors", {})
    changed = _changed_files(base, project_dir)
    affected = direction_a(behaviors, changed, project_dir)
    if not affected:
        return {"affected": [], "failed": [], "changed": changed}, 0

    runner = _run_behavior_runner(project_dir, only=affected)
    fingerprints = runner.get("fingerprints", {})
    failed = []
    for bid in affected:
        incoming = fingerprints.get(bid, {"coverage": "unknown", "exercises": [], "reason": "not-run"})
        prior_part = behaviors.get(bid)
        merged = merge_fingerprint(prior_part, incoming)
        fields = {k: v for k, v in behaviors[bid].items()
                  if k not in ("coverage", "exercises", "reason")}
        behaviors[bid] = {**fields, **merged}
        if incoming.get("coverage") == "unknown" and incoming.get("reason") == "test-failed":
            failed.append(bid)

    data["behaviors"] = behaviors
    data["commit"] = runner.get("commit", data.get("commit", "unknown"))
    write_behavior_json(project_dir, data)
    return {"affected": affected, "failed": failed, "changed": changed}, (1 if failed else 0)
```
Add the CLI branch in `main` (extend the mutually-exclusive group + handle it):
```python
    group.add_argument("--check", action="store_true",
                       help="Direction-A regression check (re-run affected accepted behaviors).")
    parser.add_argument("--base", help="Base commit for --check (diff base..HEAD).")
```
And in `main`'s dispatch, before the `--affected`/`--implements` reads:
```python
    if args.check:
        if not args.base:
            parser.error("--check requires --base COMMIT")
        report, code = regression_check(args.project, args.base)
        print(json.dumps(report, indent=2))
        return code
```

- [ ] **Step 4: Run unit tests, then prove on the testbed**

Run the pure tests: `cd skills/behavior-graph/scripts && python -m unittest test_behavior_graph -v`
Expected: PASS (15 prior + 3 new = 18).

Then prove the pass-path end-to-end on the testbed (build the graph first, then check a change that touches `lib/webauthn.ts`):
```bash
cd /Users/main/Documents/projects/viva-croatia-testbed
PRIOR=$(git rev-parse HEAD~1)   # a commit before the most recent change
python /Users/main/Documents/projects/freya-devkit/skills/behavior-graph/scripts/behavior_graph.py \
  --build --project /Users/main/Documents/projects/viva-croatia-testbed >/dev/null
python /Users/main/Documents/projects/freya-devkit/skills/behavior-graph/scripts/behavior_graph.py \
  --check --base "$PRIOR" --project /Users/main/Documents/projects/viva-croatia-testbed
echo "exit: $?"
```
Expected: a JSON report listing `affected` (the accepted behaviors whose exercised code intersects the diff) with `failed: []` and **exit 0** (the behaviors re-run green). The blocking path (`exit 1` on a `test-failed` affected behavior) is covered by the unit test `test_affected_failing_blocks`.

- [ ] **Step 5: Commit**

```bash
git add skills/behavior-graph/scripts/
git commit -m "feat(behavior-graph): --check (incremental Direction-A regression gate)"
```

---

### Task 3: Wire wrap-up Phase 3.5 + add the F5 never-synced guard

**Repo:** freya-devkit (plugin).

**Files:**
- Modify: `skills/wrap-up/SKILL.md`

**Interfaces:**
- Consumes: `behavior-graph --check --base <pre-code-commit>` (Task 2). wrap-up Phase 0 already captures the new code-commit hash; its parent is the base.

- [ ] **Step 1: Rewrite Phase 3.5 step 2 to use the behavior graph**

In `skills/wrap-up/SKILL.md`, replace **Phase 3.5 step 2** ("Run accepted behaviors…") with:
````markdown
2. **Build/refresh the behavior graph, then run the affected accepted behaviors
   (hard-block on a regression).** After the code commit, refresh the graph and
   run the Direction-A regression check (re-runs *only* the accepted behaviors
   whose exercised code the change touched — not the whole suite):
   ```bash
   BASE=$(git rev-parse HEAD~1)   # the commit before this wrap-up's code commit
   python "${CLAUDE_PLUGIN_ROOT}/skills/behavior-graph/scripts/behavior_graph.py" \
     --build --project . >/dev/null
   python "${CLAUDE_PLUGIN_ROOT}/skills/behavior-graph/scripts/behavior_graph.py" \
     --check --base "$BASE" --project .
   ```
   A non-zero exit means an affected accepted behavior is **`test-failed`** — a
   **deterministic failure** that blocks until classified: fix the code
   (regression), record an intended change, or `quarantine` a test-infra failure.
   `proposed`/`quarantined`/`deprecated` behaviors are never run. `behavior.json`
   is written under the git-ignored `knowledge-base/.graph/`.
````
Update the note under Phase 3.5 to read:
````markdown
> Phase 2 scope: this phase now runs the **affected** accepted behaviors via the
> behavior graph (Direction A) with deterministic-only blocking, and records
> coverage fingerprints. Model-based contradiction checks remain Phase 3.
````

- [ ] **Step 2: Add the F5 never-synced guard**

In `skills/wrap-up/SKILL.md`, add a guard sentence to **each** of Phases 1–4's update calls (code-graph / docs-manager / spec-manager / security). Add this once as a shared note right before Phase 1 (the "Phase 1: Update Dependency Graph" heading):
````markdown
> **Never-synced guard (F5).** The `update` commands below are incremental and
> assume a prior sync. If a project has **never been synced** (no tracking file —
> e.g. no `knowledge-base/specs/.spec-last-update`, no `.graph/`, no
> `.security-last-scan`), do **not** let `update` silently run a full-codebase
> generation. Instead, report that the project is unsynced and run the explicit
> first-time command (`scan` / `build`) deliberately, or skip that phase with a
> clear message. wrap-up must not trigger a surprise full generation.
````

- [ ] **Step 3: Verify the referenced command exists and the prose is consistent**

Run (confirms the command wrap-up now calls is real and accepts the flags):
```bash
python "/Users/main/.claude/plugins/cache/freya-devkit/freya-devkit/0.1.0/skills/behavior-graph/scripts/behavior_graph.py" --help
```
Expected: usage shows `--build`, `--check`, `--base`, `--affected`, `--implements`. Re-read Phase 3.5 to confirm step 1 (verify_links) is unchanged and step 2 now references `behavior-graph --check`.

- [ ] **Step 4: Commit**

```bash
git add skills/wrap-up/SKILL.md
git commit -m "feat(wrap-up): Phase 3.5 runs affected behaviors via behavior-graph; F5 never-synced guard"
```

---

### Task 4: F3 — `spec-manager init` keeps empty category dirs

**Repo:** freya-devkit (plugin).

**Files:**
- Modify: `skills/spec-manager/SKILL.md`

- [ ] **Step 1: Update the `init` steps**

In `skills/spec-manager/SKILL.md`, under `### /freya-devkit:spec-manager init`, change step 2 to drop a `.gitkeep` in each category dir so the structure survives Git:
````markdown
2. Create category subdirectories: `auth/`, `api/`, `data/`, `features/`, `infra/`, `integration/`, `ui/` — each with an empty `.gitkeep` file so the empty directory survives Git (Git does not track empty directories; this mirrors the `decisions/` README rationale).
````

- [ ] **Step 2: Verify consistency**

Re-read the `init` section and the [Knowledge-Base Layout] section to confirm the `.gitkeep` rationale matches the existing `decisions/`-README note (which exists for the same "survive Git" reason). No other step references the category dirs as empty-and-unprotected.

- [ ] **Step 3: Commit**

```bash
git add skills/spec-manager/SKILL.md
git commit -m "fix(spec-manager): init drops .gitkeep in spec category dirs (F3)"
```

---

### Task 5: §6 Measurement (the evidence gate)

**Repo:** freya-devkit (plugin) — docs only.

**Files:**
- Modify: `docs/design/behavior-layer/02-phase-2.md` (§6 results)
- Modify: `docs/design/behavior-layer/dogfooding-notes.md` (a measurement entry)

**Interfaces:**
- Consumes: the testbed's built `behavior.json` (BEH-002 observed, BEH-003 static) and `behavior-graph --check`.

- [ ] **Step 1: Gather the numbers on the testbed**

Run and record the raw outputs:
```bash
cd /Users/main/Documents/projects/viva-croatia-testbed
# Fingerprint breadth (files per behavior):
python /Users/main/Documents/projects/freya-devkit/skills/behavior-graph/scripts/behavior_graph.py --build --project . \
  | python3 -c "import sys,json; d=json.load(sys.stdin); [print(b, len(v.get('exercises',[])), v.get('coverage')) for b,v in d['behaviors'].items()]"
# Runtime of an incremental check (time it):
time python /Users/main/Documents/projects/freya-devkit/skills/behavior-graph/scripts/behavior_graph.py --check --base "$(git rev-parse HEAD~1)" --project .
```

- [ ] **Step 2: Record the measurement**

Add a `## §6 Measurement (results)` subsection to `02-phase-2.md` capturing, from Step 1:
- **Fingerprint breadth:** files-per-fingerprint for BEH-002 (observed) and BEH-003 (static) — the actual counts.
- **False-positive rate:** hand-judged on the testbed set — of the behaviors `--check` flags as affected by a representative change (e.g. editing `lib/webauthn.ts`), how many are *genuinely* relevant vs. swept in. State the change used and the judgment.
- **Runtime:** the measured `--check` wall-clock (incremental) and a note that it re-runs only affected behaviors, not the suite.
- **Static-vs-observed:** note BEH-003's static fingerprint breadth vs BEH-002's observed, and that static is conservatively-broader (the safe direction).
- The **four gated decisions** (§6): is `observed` trustworthy; is per-behavior fast enough; is integration source-map remap reliable (answer: deferred — static used instead, F11); can governance hard-block (Phase 3 — record the measured FP basis).

Add a one-paragraph `### Measurement (Phase 2)` entry to `dogfooding-notes.md` summarizing the same, as the evidence-gate record (vision §9).

- [ ] **Step 3: Commit**

```bash
git add docs/design/behavior-layer/02-phase-2.md docs/design/behavior-layer/dogfooding-notes.md
git commit -m "docs(behavior-layer): Phase 2 §6 measurement results"
```

---

## Self-Review

**Spec coverage (against `02-phase-2.md` §4a/§5/§8/§9 + §6):** Delivers incremental execution (Direction-A selection re-runs only affected — Task 2), wrap-up Phase 3.5 wiring with deterministic-only blocking (§9 — Task 3), the carried **F5** (never-synced guard — Task 3) and **F3** (`init` `.gitkeep` — Task 4), and the §6 **measurement** evidence gate (Task 5). The `--only` filter (Task 1) is the mechanism enabling incremental re-runs. Deferred (correctly, beyond Phase 2): full **freshness caching** (skip re-running an affected behavior whose files are unchanged since its `freshness` commit) — noted in Next; brainstorming Direction B wiring (advisory, Phase 3-adjacent); the observed-CDP coverage adapter (`parking-lot.md`).

**Placeholder scan:** No TBD/TODO in code. Task 5 is an empirical task with concrete commands; its "record the numbers" step is a deliverable (the numbers come from Step 1's real output), not a placeholder. Prose tasks (3, 4) give exact SKILL.md replacement text.

**Type/name consistency:** `filter_only` (Task 1) feeds `--only`, which `behavior-graph._run_behavior_runner(project_dir, only=...)` (Task 2) passes through; `regression_check` reuses `direction_a`/`merge_fingerprint`/`write_behavior_json` (Plan 4) with the same `{coverage, exercises, reason?}` coverage-part shape. The wrap-up command (Task 3) calls exactly the `--check --base --project` interface Task 2 defines. Exit-code contract (0 pass / 1 blocked) is consistent between `regression_check`, `main`, and the wrap-up prose.

**Known iteration point (honest):** Task 2 Step 4's testbed pass-path assumes a recent commit (`HEAD~1`) whose diff touches code an accepted behavior exercises; if `HEAD~1..HEAD` happens to touch no exercised file, `affected` is empty (exit 0, `affected: []`) — still a valid result, just not a demonstration. Pick a base whose diff includes `lib/webauthn.ts` (e.g. the BEH-002 test commit's parent) to exercise the affected path. The blocking path is unit-tested regardless. `_changed_files` uses `base..HEAD`; if `base` is invalid it returns `[]` (no affected, exit 0) rather than crashing — acceptable for a gate, and wrap-up always passes a real parent commit.

## Next plan

Phase 2 is **complete** after this plan. Optional follow-ups (not Phase 2): **freshness caching** (skip unchanged affected behaviors via the per-edge `freshness` commit), **brainstorming Direction B** wiring (design-time "this change touches behaviors X, Y"), and the deferred **observed-CDP coverage adapter** (`parking-lot.md`). Then **Phase 3** (governance: model-based contradiction checks, principle enforcement) — gated on this plan's §6 measurement showing the fingerprints are trustworthy.
