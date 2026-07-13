# SP3 — Validate-on-hit Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** At wrap-up, surface the proposed/confirmed behaviors a change actually touches (re-inferred, bounded, skippable) and flag touched code that no behavior covers — via a new deterministic `behavior-graph --surface` query consumed by wrap-up's Phase 3.5.

**Architecture:** A new read-only `behavior_graph.py --surface --base <commit>` subcommand emits three buckets (`affected_accepted`, `validate_candidates`, `recall_gaps`). Proposed behaviors are matched by `entry ∈ impact` — provably equivalent to the precise exercises-closure match (impact is closed under transitive dependents, and the entry depends on its whole closure), so no closure recomputation is needed and `behavior.json` stays unchanged. wrap-up Phase 3.5 runs the query after the existing gated `--check` and drives a non-gating, skippable confirm/capture loop.

**Tech Stack:** Python 3.12, stdlib only (`unittest`, `unittest.mock`). Tests are `unittest` modules run with `python test_<name>.py` from the script's own directory.

## Global Constraints

- **Stdlib-only Python** — no new imports beyond the standard library.
- **Advisory / non-gating** — nothing SP3 adds changes wrap-up's exit code. Only the existing accepted-`test-failed` gate (SP1, the `--check` path) blocks. `--surface` is read-only and never raises on missing graph/base.
- **`behavior.json` projected contents are unchanged** — proposed behaviors stay out of the projected graph (SP1/SP2 invariant). The surface query reads proposed from specs on-demand.
- **Precise match, computed cheaply** — a proposed/confirmed behavior is "affected" iff its `entry ∈ impact` (where `impact = _code_graph_impact(changed)` = changed ∪ transitive dependents). This is equivalent to `closure(entry) ∩ impact ≠ ∅`; it is NOT the rejected coarse match (`entry ∈ changed_files`), because `impact` includes transitive dependents, so a change to a dependency the entry imports still puts the entry in `impact`.
- **Entry-less proposed are not surfaced** on hit (worklist-only — SP4).
- **Re-inference is bounded + skippable** — only the affected subset is ever re-inferred, and the whole validate step is skippable, so a large change cannot trigger an unbounded agent fan-out.
- **Confirm bumps `proposed → confirmed`** (SP1 state) in the spec frontmatter; never auto-accept (tests stay owed). A newly-confirmed spec edit stages as an **artifact** (wrap-up commit 2).
- **Production webapp `/Users/main/Documents/areas/viva-croatia/webapp/` is OFF-LIMITS.** The dogfood uses only the testbed `/Users/main/Documents/projects/viva-croatia-testbed`.

---

### Task 1: `behavior-graph --surface --base` query

Add the read-only three-bucket surface query to `behavior_graph.py`, refactoring `direction_a` so the blast radius is computed once.

**Files:**
- Modify: `skills/behavior-graph/scripts/behavior_graph.py` (imports near top; `direction_a` ~line 164; add `_affected_from_impact`, `_graph_files`, `surface`; CLI `main` ~lines 216-247)
- Test: `skills/behavior-graph/scripts/test_behavior_graph.py` (add a `SurfaceTest` class)

**Interfaces:**
- Consumes (existing in this file): `_code_graph_impact(changed_files, project_dir) -> set`, `_changed_files(base, project_dir) -> list`, `load_behavior_json(project_dir) -> dict`. From the sibling runner: `run_behaviors.load_behaviors(specs_dir, states=(...)) -> list[dict]` (each record has `behavior_id`, `state`, `title`, `entry`, `spec_id`, `spec_path`).
- Produces:
  - `_affected_from_impact(behaviors, impact) -> list[str]` — sorted BEH ids whose `exercises ∩ impact ≠ ∅`.
  - `_graph_files(project_dir) -> set[str]` — project-relative source paths code-graph tracks (graph.json keys); `set()` if absent/unreadable.
  - `surface(project_dir, base) -> dict` — `{version, base, changed, affected_accepted, validate_candidates, recall_gaps, note?}`.
  - CLI: `--surface` (mutually exclusive group) with `--base <commit>`.

- [ ] **Step 1: Write the failing tests**

First ensure `skills/behavior-graph/scripts/test_behavior_graph.py` imports `json` at the top (add `import json` alongside the existing `import os` / `import tempfile` if it is not already there — the new fixture uses `json.dump`). Then add this class:

```python
class SurfaceTest(unittest.TestCase):
    SPEC = """---
id: SPEC-100
title: Surface fixture
category: features
status: implemented
behaviors:
  - behavior_id: BEH-002
    title: Accepted unit behavior
    state: accepted
    level: unit
    adapter: vitest
    locator: lib/webauthn.test.ts::x
  - behavior_id: BEH-006
    title: Confirmed integration behavior
    state: confirmed
    level: integration
    entry: app/api/x/route.ts
  - behavior_id: BEH-004
    title: Proposed lock behavior
    state: proposed
    level: integration
    entry: app/api/posts/lock.ts
  - behavior_id: BEH-005
    title: Proposed without entry (worklist-only)
    state: proposed
---
# body
"""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.proj = self.tmp.name
        specs = os.path.join(self.proj, "knowledge-base", "specs", "features")
        os.makedirs(specs)
        with open(os.path.join(specs, "SPEC-100.md"), "w") as f:
            f.write(self.SPEC)
        # code-graph file set (graph.json keys) — the recognised source files
        graph_dir = os.path.join(self.proj, "knowledge-base", ".graph")
        os.makedirs(graph_dir)
        with open(os.path.join(graph_dir, "graph.json"), "w") as f:
            json.dump({"version": 1, "files": {
                "lib/webauthn.ts": {}, "app/api/x/route.ts": {},
                "app/api/posts/lock.ts": {}, "lib/util.ts": {},
            }}, f)
        # projected graph: accepted BEH-002 + confirmed BEH-006 with exercises
        behavior_graph.write_behavior_json(self.proj, {
            "version": 1, "commit": "base",
            "behaviors": {
                "BEH-002": {"spec_id": "SPEC-100", "state": "accepted",
                            "coverage": "observed", "exercises": [{"path": "lib/webauthn.ts"}]},
                "BEH-006": {"spec_id": "SPEC-100", "state": "confirmed",
                            "coverage": "static", "exercises": [{"path": "app/api/x/route.ts"}]},
            },
        })

    def _surface(self, changed, impact):
        with mock.patch.object(behavior_graph, "_changed_files", return_value=changed), \
             mock.patch.object(behavior_graph, "_code_graph_impact", return_value=set(impact)):
            return behavior_graph.surface(self.proj, "base")

    def test_proposed_with_entry_in_impact_surfaces(self):
        r = self._surface(["app/api/posts/lock.ts"], ["app/api/posts/lock.ts"])
        ids = [c["behavior_id"] for c in r["validate_candidates"]]
        self.assertIn("BEH-004", ids)      # proposed, entry hit
        self.assertNotIn("BEH-005", ids)   # proposed, no entry -> not surfaced

    def test_dependency_level_hit_surfaces_proposed(self):
        # lib/util.ts changed; impact includes the entry as a transitive dependent.
        # This is the precise (not coarse) match: entry not in changed, but in impact.
        r = self._surface(["lib/util.ts"], ["lib/util.ts", "app/api/posts/lock.ts"])
        ids = [c["behavior_id"] for c in r["validate_candidates"]]
        self.assertIn("BEH-004", ids)

    def test_confirmed_surfaces_accepted_is_context_only(self):
        r = self._surface(
            ["lib/webauthn.ts", "app/api/x/route.ts"],
            ["lib/webauthn.ts", "app/api/x/route.ts"],
        )
        self.assertEqual(r["affected_accepted"], ["BEH-002"])
        ids = [c["behavior_id"] for c in r["validate_candidates"]]
        self.assertIn("BEH-006", ids)        # confirmed surfaced to validate
        self.assertNotIn("BEH-002", ids)     # accepted is NOT a validate candidate

    def test_recall_gap_flags_uncovered_changed_source(self):
        # lib/util.ts is a graph source file in no exercise and no declared entry.
        r = self._surface(["lib/util.ts"], ["lib/util.ts"])
        self.assertIn("lib/util.ts", r["recall_gaps"])

    def test_declared_entry_is_not_a_recall_gap(self):
        r = self._surface(["app/api/posts/lock.ts"], ["app/api/posts/lock.ts"])
        self.assertNotIn("app/api/posts/lock.ts", r["recall_gaps"])

    def test_non_source_changed_file_is_not_a_recall_gap(self):
        # README.md is not a code-graph file -> never a recall gap.
        r = self._surface(["README.md"], ["README.md"])
        self.assertEqual(r["recall_gaps"], [])

    def test_no_graph_degrades_to_note(self):
        import shutil
        shutil.rmtree(os.path.join(self.proj, "knowledge-base", ".graph"))
        r = self._surface(["lib/util.ts"], ["lib/util.ts"])
        self.assertIn("note", r)
        self.assertEqual(r["validate_candidates"], [])
        self.assertEqual(r["recall_gaps"], [])

    def test_no_changes_degrades_to_note(self):
        r = self._surface([], [])
        self.assertIn("note", r)
        self.assertEqual(r["validate_candidates"], [])
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `cd skills/behavior-graph/scripts && python test_behavior_graph.py -k SurfaceTest`
Expected: FAIL — `AttributeError: module 'behavior_graph' has no attribute 'surface'`.

- [ ] **Step 3: Add the runner import and refactor `direction_a`**

In `skills/behavior-graph/scripts/behavior_graph.py`, after the existing `import frontmatter` / `from frontmatter import FrontmatterError` block near the top, add the behavior-runner scripts dir to the path and import the loader:

```python
_RUNNER_SCRIPTS = Path(__file__).resolve().parents[2] / "behavior-runner" / "scripts"
sys.path.insert(0, str(_RUNNER_SCRIPTS))
import run_behaviors  # noqa: E402  (reused for load_behaviors — reads proposed from specs)
```

Then replace `direction_a` (currently around lines 164-172):

```python
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

with:

```python
def _affected_from_impact(behaviors, impact):
    """BEH ids in the projected graph whose exercised code intersects `impact`."""
    affected = []
    for bid, entry in behaviors.items():
        paths = {e["path"] for e in entry.get("exercises", [])}
        if paths & impact:
            affected.append(bid)
    return sorted(affected)


def direction_a(behaviors, changed_files, project_dir):
    """Direction A: projected behaviors whose exercised code intersects the blast radius."""
    return _affected_from_impact(behaviors, _code_graph_impact(changed_files, project_dir))
```

- [ ] **Step 4: Add `_graph_files` and `surface`**

In `skills/behavior-graph/scripts/behavior_graph.py`, add these functions after `direction_a`:

```python
def _graph_files(project_dir):
    """Project-relative source files code-graph tracks (graph.json keys); empty if absent."""
    path = os.path.join(project_dir, "knowledge-base", ".graph", "graph.json")
    if not os.path.exists(path):
        return set()
    try:
        with open(path, encoding="utf-8") as f:
            return set(json.load(f).get("files", {}).keys())
    except (json.JSONDecodeError, OSError):
        return set()


def surface(project_dir, base):
    """Validate-on-hit surface for base..HEAD (read-only, advisory).

    Returns three buckets:
      - affected_accepted: accepted behaviors the change touches (context; gated by --check).
      - validate_candidates: affected proposed + confirmed behaviors to confirm on hit.
      - recall_gaps: changed source files covered by no behavior.

    A proposed/confirmed behavior is "affected" iff its `entry` is in the change's
    impact set. impact = changed ∪ transitive dependents, and the entry depends on
    its whole closure, so `entry ∈ impact` is equivalent to closure(entry) ∩ impact
    ≠ ∅ — the precise match, without recomputing closures.
    """
    specs_dir = os.path.join(project_dir, "knowledge-base", "specs")
    changed = _changed_files(base, project_dir)
    result = {
        "version": 1, "base": base, "changed": changed,
        "affected_accepted": [], "validate_candidates": [], "recall_gaps": [],
    }
    graph_files = _graph_files(project_dir)
    if not graph_files:
        result["note"] = ("no code-graph at knowledge-base/.graph/graph.json — "
                          "run code-graph build; surfacing skipped")
        return result
    if not changed:
        result["note"] = "no changed files in base..HEAD"
        return result

    impact = _code_graph_impact(changed, project_dir)
    behaviors = load_behavior_json(project_dir).get("behaviors", {})

    affected = _affected_from_impact(behaviors, impact)
    result["affected_accepted"] = [b for b in affected
                                   if behaviors[b].get("state") == "accepted"]
    confirmed_hit = [b for b in affected if behaviors[b].get("state") == "confirmed"]

    # Proposed live in specs (not the projected graph); load all states once so we
    # can both surface proposed candidates and collect declared entries for recall.
    specs_behaviors = run_behaviors.load_behaviors(
        specs_dir, states=("proposed", "confirmed", "accepted"))
    by_id = {b.get("behavior_id"): b for b in specs_behaviors}

    candidates = []
    for bid in confirmed_hit:
        src = by_id.get(bid, {})
        candidates.append({
            "behavior_id": bid, "state": "confirmed",
            "spec_id": src.get("spec_id"), "title": src.get("title"),
            "entry": src.get("entry"), "spec_path": src.get("spec_path"),
        })
    for b in specs_behaviors:
        if b.get("state") != "proposed":
            continue
        entry = b.get("entry")
        if entry and entry in impact:
            candidates.append({
                "behavior_id": b.get("behavior_id"), "state": "proposed",
                "spec_id": b.get("spec_id"), "title": b.get("title"),
                "entry": entry, "spec_path": b.get("spec_path"),
            })
    result["validate_candidates"] = sorted(candidates, key=lambda c: c.get("behavior_id") or "")

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

- [ ] **Step 5: Wire the CLI**

In `main`, add `--surface` to the mutually exclusive group (alongside `--build`/`--affected`/`--implements`/`--check`):

```python
    group.add_argument("--surface", action="store_true",
                       help="Validate-on-hit surface (affected proposed/confirmed + recall gaps) for base..HEAD.")
```

And handle it — add this block right before the existing `if args.check:` block in `main`:

```python
    if args.surface:
        if not args.base:
            parser.error("--surface requires --base COMMIT")
        print(json.dumps(surface(args.project, args.base), indent=2))
        return 0
```

- [ ] **Step 6: Run the tests to verify they pass (and nothing regressed)**

Run: `cd skills/behavior-graph/scripts && python test_behavior_graph.py`
Expected: PASS — the new `SurfaceTest` and all existing classes (`DirectionATest`, `RegressionCheckTest`, `ConfirmedGraphTest`, etc.), output pristine.

- [ ] **Step 7: Smoke-test the CLI against the testbed (read-only)**

Run:
```bash
cd /Users/main/Documents/projects/freya-devkit
python skills/behavior-graph/scripts/behavior_graph.py --surface --base HEAD --project /Users/main/Documents/projects/viva-croatia-testbed
```
Expected: valid JSON with the three buckets (likely empty `validate_candidates`/`recall_gaps` with `base HEAD` since there is no diff, and a `note` about no changed files). Confirms the CLI wiring and that it never errors. Do not modify/commit testbed state.

- [ ] **Step 8: Commit**

```bash
git add skills/behavior-graph/scripts/behavior_graph.py skills/behavior-graph/scripts/test_behavior_graph.py
git commit -m "feat(behavior-graph): --surface validate-on-hit query (affected candidates + recall gaps)"
```

---

### Task 2: wrap-up Phase 3.5 surfacing step

Add the non-gating validate-on-hit step to wrap-up's Phase 3.5, after the gated `--check`.

**Files:**
- Modify: `skills/wrap-up/SKILL.md` (Phase 3.5 — add a step 3 after the `--check` step 2; update the closing scope blockquote)

**Interfaces:**
- Consumes: `behavior-graph --surface --base BASE` (Task 1) → JSON buckets; spec-manager for the `proposed → confirmed` state bump and for capturing a new behavior.
- Produces: documented procedure (no code interface for later tasks).

- [ ] **Step 1: Add the surfacing step to Phase 3.5**

In `skills/wrap-up/SKILL.md`, in `### Phase 3.5`, immediately after numbered item **2** (the `--build` then `--check` block, which ends with "...`behavior.json` is written under the git-ignored `knowledge-base/.graph/`.") and before the `> Phase 2 scope:` blockquote, insert:

````markdown
3. **Validate-on-hit (advisory — never blocks).** After the gated check, surface the
   proposed/confirmed behaviors this change actually touched, plus any touched code no
   behavior covers:
   ```bash
   python "${CLAUDE_PLUGIN_ROOT}/skills/behavior-graph/scripts/behavior_graph.py" \
     --surface --base "$BASE" --project .
   ```
   This is **read-only and never changes the exit code.** Using its JSON buckets:
   - **`validate_candidates`** (the affected proposed/confirmed behaviors — bounded to
     the touched subset): present them prominently, **but the whole step is skippable.**
     For each candidate the engineer chooses to review, **re-infer it against the
     current code** — read the behavior's `entry` file as it is now and produce a
     refreshed title/description — then offer: **confirm**, **edit then confirm**, or
     **skip**. On confirm, bump the behavior's `state` `proposed → confirmed` in its
     spec frontmatter (`spec_path`); a candidate already `confirmed` stays `confirmed`
     and is noted as still owing a test (its worklist home arrives in SP4). Never
     auto-accept — confirming intent does not author a test.
   - **`recall_gaps`** (changed source files no behavior covers): if any, prompt
     "these N touched file(s) have no covering behavior — capture one?" and, if the
     engineer wants, author a new `proposed`/`confirmed` behavior via spec-manager.
     Skippable.
   - **`affected_accepted`** is context only — those behaviors were already run by the
     gated check in step 2; do not re-validate them.
   Re-inference is bounded by the affected subset and the step is skippable, so a large
   change never triggers an unbounded re-inference fan-out. If `--surface` returns a
   `note` (no graph / no changes), print it and continue.
````

- [ ] **Step 2: Update the Phase 3.5 closing scope note**

In `skills/wrap-up/SKILL.md`, replace the Phase 3.5 closing blockquote:

```
> Phase 2 scope: this phase now runs the **affected** accepted behaviors via the
> behavior graph (Direction A) with deterministic-only blocking, and records
> coverage fingerprints. Model-based contradiction checks remain Phase 3.
```

with:

```
> Scope: this phase runs the **affected** accepted behaviors via the behavior graph
> (Direction A) with deterministic-only blocking and records coverage fingerprints
> (Phase 2), then **surfaces** the affected proposed/confirmed behaviors and
> uncovered touched code for confirmation — advisory, never blocking (SP3).
> Model-based contradiction checks remain a later track.
```

- [ ] **Step 3: Verify the edits**

Run: `cd /Users/main/Documents/projects/freya-devkit && grep -n "surface\|Validate-on-hit\|recall_gaps" skills/wrap-up/SKILL.md`
Expected: the new step 3 and its bucket references appear inside Phase 3.5; visually confirm step 3 sits between the `--check` step and the scope blockquote, and that the `$BASE` variable it uses is the same one defined in step 2.

- [ ] **Step 4: Commit**

```bash
git add skills/wrap-up/SKILL.md
git commit -m "feat(wrap-up): Phase 3.5 validate-on-hit surfacing (advisory, skippable)"
```

---

## Dogfooding pass (manual — run after Task 2, not a TDD task)

Validate on the **testbed**, reusing the `dogfood/sp2-bootstrap` branch (it has `SPEC-002`'s `proposed` post-locking behaviors anchored to the lock/claim routes). Production webapp stays untouched.

- [ ] **D1 — Surface query on a real change.** In the testbed, `git checkout dogfood/sp2-bootstrap`. Make a no-op edit to `app/api/posts/[id]/lock/route.ts`, commit it. Run `behavior_graph.py --surface --base HEAD~1 --project <testbed>`. Expect: BEH-004..007 (the lock-route proposed behaviors) in `validate_candidates`; BEH-008 (claim route, untouched) absent; the edited route NOT in `recall_gaps` (it is a declared entry).
- [ ] **D2 — Dependency-level hit.** Edit a lib the lock route imports (e.g. `lib/db-prisma.ts`), commit, re-run `--surface`. Confirm the lock behaviors still surface (their `entry` is in `impact` as a transitive dependent) — the precise, not coarse, match.
- [ ] **D3 — Recall gap.** Edit a testbed source file that no behavior covers (not any behavior's entry, not in any exercise), commit, re-run `--surface`. Confirm it appears in `recall_gaps`.
- [ ] **D4 — wrap-up interaction (light).** Walk the Phase 3.5 surfacing step manually for the D1 change: re-infer one surfaced proposed behavior against the current lock-route code, confirm it, and verify its `state` flips `proposed → confirmed` in `knowledge-base/specs/features/SPEC-002-post-locking.md`. Re-run `verify_links` → still clean.
- [ ] **D5 — Log friction** in `docs/design/behavior-layer/dogfooding-notes.md` (new SP3 entry): surface accuracy, re-inference quality, recall-gap noise. Restore the testbed to `main`; retain the dogfood branch.

---

## Final whole-branch review

After Task 2 and the dogfood, dispatch the final whole-branch review (superpowers:requesting-code-review) over the SP3 commits (base = the SP3 plan commit), pointing it at any Minor findings recorded in the ledger. Continue on `feat/behavior-layer` — do **not** merge (SP4–SP5 remain).
