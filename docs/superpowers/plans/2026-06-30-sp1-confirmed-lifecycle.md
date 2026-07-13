# SP1 — `confirmed` Lifecycle State Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make `confirmed` a first-class behavior lifecycle state — intent confirmed, test owed — that validates without a test, gets an advisory static fingerprint via its `entry`, and never gates wrap-up.

**Architecture:** `confirmed` sits between `proposed` and `accepted`. The locator/adapter requirement becomes state-aware (only `accepted` asserts a real linked test). The runner produces an advisory **static** fingerprint for confirmed behaviors (never executing a test, so they can never be `test-failed`), and the graph projects them so Direction A/B see them — but because they are never executed they can never block the regression check.

**Tech Stack:** Python 3.12, stdlib only (`unittest`, `unittest.mock`). No third-party deps. Tests are `unittest` modules run with `python test_<name>.py` from the script's own directory.

## Global Constraints

- **Stdlib-only Python** — no new imports beyond the standard library; the plugin is zero-install.
- **Lifecycle order is `proposed → confirmed → accepted → quarantined → deprecated`** — `confirmed` is inserted after `proposed`, before `accepted`. Copy the enum verbatim where it appears.
- **`accepted` semantics are unchanged** — it still requires an adapter and (non-`manual`) a locator, still hard-blocks on `test-failed`, still triggers the accepted-but-scaffold check. Do not relax any `accepted` guarantee.
- **`confirmed` is advisory / non-gating** — it must never appear in a regression-check `failed` list and never cause a non-zero exit.
- **`confirmed` allows an entry-less record** (decided for SP1): a confirmed behavior needs neither adapter nor locator; an `entry` is optional. With an `entry` it gets a static fingerprint; without one it is `unknown`/`no-entry` (worklist-only, surfaced later in SP4).
- **Tests run per-file:** `cd` into the script directory and run `python test_<name>.py`. Each test module already puts its own dir on `sys.path`.
- **Production webapp `/Users/main/Documents/areas/viva-croatia/webapp/` is OFF-LIMITS.** The dogfooding pass uses only the testbed at `/Users/main/Documents/projects/viva-croatia-testbed`.

---

### Task 1: Lifecycle vocabulary + state-aware validation (`frontmatter.py`)

Add `confirmed` to the closed lifecycle and make adapter/locator requirements state-aware so a pre-test behavior (`proposed`/`confirmed`) validates without a test, while `accepted` is unchanged.

**Files:**
- Modify: `skills/spec-manager/scripts/frontmatter.py` (`BEHAVIOR_STATES` ~line 69; `validate_behaviors` adapter/locator block ~lines 329-337)
- Test: `skills/spec-manager/scripts/test_frontmatter.py` (add to `class TestBehaviorValidation`)
- Docs: `skills/spec-manager/SKILL.md`, `skills/spec-manager/references/spec-template.md`

**Interfaces:**
- Consumes: nothing from earlier tasks.
- Produces:
  - `BEHAVIOR_STATES == ("proposed", "confirmed", "accepted", "quarantined", "deprecated")`
  - `validate_behaviors(behaviors, spec_id=None) -> list[str]` — unchanged signature; new rule: adapter required only when `state == "accepted"`; locator required only when `state == "accepted" and adapter != "manual"`; both still type/enum-checked when present in any state.

- [ ] **Step 1: Write the failing tests**

Add these methods to `class TestBehaviorValidation` in `skills/spec-manager/scripts/test_frontmatter.py`:

```python
    def test_confirmed_state_is_valid(self):
        # A confirmed behavior that still carries adapter+locator is valid.
        self.assertEqual(validate_behaviors([_beh(state="confirmed")]), [])

    def test_confirmed_without_test_is_valid(self):
        # confirmed = intent confirmed, test owed: no adapter/locator required.
        rec = {"behavior_id": "BEH-010", "title": "Owes a test", "state": "confirmed"}
        self.assertEqual(validate_behaviors([rec]), [])

    def test_confirmed_with_entry_only_is_valid(self):
        rec = {"behavior_id": "BEH-010", "title": "Owes a test", "state": "confirmed",
               "level": "integration", "entry": "app/api/x/route.ts"}
        self.assertEqual(validate_behaviors([rec]), [])

    def test_proposed_without_test_is_valid(self):
        # A scan-inferred proposed candidate has no test yet either.
        rec = {"behavior_id": "BEH-011", "title": "Inferred candidate", "state": "proposed"}
        self.assertEqual(validate_behaviors([rec]), [])

    def test_confirmed_bad_adapter_when_present_rejected(self):
        rec = {"behavior_id": "BEH-010", "title": "x", "state": "confirmed", "adapter": "rspec"}
        self.assertTrue(any("adapter" in e for e in validate_behaviors([rec])))

    def test_confirmed_non_string_locator_when_present_rejected(self):
        rec = {"behavior_id": "BEH-010", "title": "x", "state": "confirmed", "locator": 123}
        self.assertTrue(any("locator" in e for e in validate_behaviors([rec])))

    def test_accepted_still_requires_adapter(self):
        rec = {"behavior_id": "BEH-012", "title": "x", "state": "accepted"}
        self.assertTrue(any("adapter" in e for e in validate_behaviors([rec])))
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `cd skills/spec-manager/scripts && python test_frontmatter.py -k TestBehaviorValidation`
Expected: FAIL — `test_confirmed_state_is_valid` / `test_confirmed_without_test_is_valid` fail because `state 'confirmed' must be one of ...` (confirmed not in enum) and the entry-less/proposed cases fail because adapter/locator are still unconditionally required.

- [ ] **Step 3: Add `confirmed` to the lifecycle enum**

In `skills/spec-manager/scripts/frontmatter.py`, replace the `BEHAVIOR_STATES` definition and its comment (around lines 65-69):

```python
# Behavior-record vocabulary. The lifecycle is closed; the adapter set is
# intentionally a generous-but-checked allow-list (vision lists `... | manual`
# as extensible — new adapters are added here as phases ship, so an unknown
# adapter still fails loud rather than pointing at a runner with no implementation).
# Lifecycle: proposed -> confirmed -> accepted (+ quarantined / deprecated).
# `confirmed` = a human confirmed the intent but the test is still owed (design
# 03 §3): it carries intent (and may declare an `entry`) but asserts no test, so
# adapter/locator are not required for it (see validate_behaviors below).
BEHAVIOR_STATES = ("proposed", "confirmed", "accepted", "quarantined", "deprecated")
```

- [ ] **Step 4: Make adapter/locator requirements state-aware**

In `validate_behaviors`, replace the adapter + locator block (currently lines ~329-337):

```python
        adapter = b.get("adapter")
        if adapter not in KNOWN_ADAPTERS:
            errors.append(
                f"{where}: adapter '{adapter}' must be one of {', '.join(KNOWN_ADAPTERS)}"
            )

        locator = b.get("locator")
        if adapter != "manual" and (not locator or not isinstance(locator, str)):
            errors.append(f"{where}: missing locator (required for adapter '{adapter}')")
```

with:

```python
        # Only `accepted` asserts a real, linked, passing test, so adapter and
        # locator are *required* only for accepted. Pre-test states (`proposed`,
        # `confirmed`) may omit them — intent confirmed, test owed (design 03 §3).
        # When either is present in any state it is still validated, so a typo
        # fails loud rather than silently routing to the wrong runner.
        adapter = b.get("adapter")
        if state == "accepted":
            if adapter not in KNOWN_ADAPTERS:
                errors.append(
                    f"{where}: adapter '{adapter}' must be one of {', '.join(KNOWN_ADAPTERS)}"
                )
        elif adapter is not None and adapter not in KNOWN_ADAPTERS:
            errors.append(
                f"{where}: adapter '{adapter}' must be one of {', '.join(KNOWN_ADAPTERS)}"
            )

        locator = b.get("locator")
        if state == "accepted" and adapter != "manual":
            if not locator or not isinstance(locator, str):
                errors.append(f"{where}: missing locator (required for accepted adapter '{adapter}')")
        elif locator is not None and not isinstance(locator, str):
            errors.append(f"{where}: locator must be a string")
```

- [ ] **Step 5: Run the tests to verify they pass (and nothing regressed)**

Run: `cd skills/spec-manager/scripts && python test_frontmatter.py`
Expected: PASS — all tests, including the existing `test_missing_locator_for_non_manual_rejected`, `test_manual_adapter_allows_missing_locator`, and `test_bad_state_rejected`.

- [ ] **Step 6: Fix the now-stale comment in the round-trip test**

In `skills/spec-manager/scripts/test_frontmatter.py`, the `test_parsed_spec_round_trips_through_validate` comment claims BEH-008 (proposed, no adapter) "is expected to report a missing adapter" — no longer true. Replace that comment:

```python
        # BEH-008 in that fixture is 'proposed' with adapter/locator absent. A
        # pre-test state needs neither, so it now validates cleanly; assert the
        # parse produced the right shape and the first (accepted) record is clean.
```

Run: `cd skills/spec-manager/scripts && python test_frontmatter.py -k test_parsed_spec_round_trips_through_validate`
Expected: PASS.

- [ ] **Step 7: Update the lifecycle docs (spec-manager)**

In `skills/spec-manager/SKILL.md`:

Replace the behaviors-block state comment (line ~573):
```
    state: accepted            # proposed | accepted | quarantined | deprecated
```
with:
```
    state: accepted            # proposed | confirmed | accepted | quarantined | deprecated
```

Replace the authoritative-state sentence (line ~581):
```
lifecycle `state` (only **accepted** is authoritative), an `adapter`, and a
```
with:
```
lifecycle `state` (`accepted` is authoritative — verified by a linked test;
`confirmed` = intent confirmed, test owed), an `adapter`, and a
```

In the `certainty` blockquote, replace this three-line block (lines ~110-113):
```
> carried by the behavior **lifecycle `state`** (`proposed → accepted`), where
> **`accepted` = a human confirmed the intent** (and usually a real linked test
> verifies it). So:
```
with:
```
> carried by the behavior **lifecycle `state`** (`proposed → confirmed → accepted`),
> where **`confirmed` = a human confirmed the intent (test owed)** and **`accepted`
> = confirmed intent that a real linked test verifies**. So:
```

In `skills/spec-manager/references/spec-template.md`, replace line 24:
```
    state: proposed            # proposed | accepted | quarantined | deprecated
```
with:
```
    state: proposed            # proposed | confirmed | accepted | quarantined | deprecated
```
and replace line 119:
```
| `state` | Yes | `proposed` \| `accepted` \| `quarantined` \| `deprecated`. Only **accepted** is authoritative and blocks on failure |
```
with:
```
| `state` | Yes | `proposed` \| `confirmed` \| `accepted` \| `quarantined` \| `deprecated`. `confirmed` = intent confirmed, test owed (advisory); only **accepted** is authoritative and blocks on failure |
```

- [ ] **Step 8: Commit**

```bash
git add skills/spec-manager/scripts/frontmatter.py skills/spec-manager/scripts/test_frontmatter.py skills/spec-manager/SKILL.md skills/spec-manager/references/spec-template.md
git commit -m "feat(spec-manager): add confirmed lifecycle state + state-aware validation"
```

---

### Task 2: `verify_links` — confirmed may lack a test

Make the Tier-1 link checker stop requiring a locator for pre-test states, while keeping every `accepted` check intact and still resolving any locator/entry that *is* present.

**Files:**
- Modify: `skills/spec-manager/scripts/verify_links.py` (forward loop, lines ~91-136)
- Test: `skills/spec-manager/scripts/test_verify_links.py`
- Docs: `skills/spec-manager/SKILL.md` (the `verify` section, line ~337)

**Interfaces:**
- Consumes: `BEHAVIOR_STATES` includes `confirmed` (Task 1).
- Produces: `verify(specs_dir=None) -> list[dict]` — unchanged signature. New behavior: `missing-locator` and `accepted-but-scaffold` fire only for `state == "accepted"`; `entry-unresolved`, `locator-unresolved`, `missing-reverse-tag`, `missing-spec-tag` fire for any state when the relevant field is present.

- [ ] **Step 1: Write the failing tests**

Add these methods to `class VerifyLinksCase` in `skills/spec-manager/scripts/test_verify_links.py`:

```python
    def test_confirmed_without_locator_is_clean(self):
        root = self._root()
        _write(root / "knowledge-base/specs/auth/SPEC-001-login.md",
               _spec("SPEC-001", "auth",
                     _beh_block("BEH-001", "Owes a test", "confirmed", "cucumber")))
        errors = verify(self._specs_dir(root))
        self.assertEqual(errors, [], f"expected clean confirmed-no-test, got {errors}")

    def test_confirmed_entry_unresolved_still_reported(self):
        root = self._root()
        _write(root / "knowledge-base/specs/auth/SPEC-001-login.md",
               _spec("SPEC-001", "auth",
                     _beh_block("BEH-001", "Owes a test", "confirmed", "cucumber",
                                level="integration", entry="app/api/missing/route.ts")))
        errors = verify(self._specs_dir(root))
        self.assertIn("entry-unresolved", _kinds(errors))

    def test_confirmed_entry_resolved_is_clean(self):
        root = self._root()
        _write(root / "knowledge-base/specs/auth/SPEC-001-login.md",
               _spec("SPEC-001", "auth",
                     _beh_block("BEH-001", "Owes a test", "confirmed", "cucumber",
                                level="integration", entry="app/api/real/route.ts")))
        _write(root / "app/api/real/route.ts", "export function POST(){}\n")
        errors = verify(self._specs_dir(root))
        self.assertEqual(errors, [], f"expected clean, got {errors}")

    def test_accepted_missing_locator_still_reported(self):
        root = self._root()
        _write(root / "knowledge-base/specs/auth/SPEC-001-login.md",
               _spec("SPEC-001", "auth",
                     _beh_block("BEH-001", "Successful login", "accepted", "cucumber")))
        errors = verify(self._specs_dir(root))
        self.assertIn("missing-locator", _kinds(errors))
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `cd skills/spec-manager/scripts && python test_verify_links.py`
Expected: FAIL — `test_confirmed_without_locator_is_clean` reports a `missing-locator` error (today's code requires a locator for any non-`manual` adapter regardless of state).

- [ ] **Step 3: Make the forward loop state-aware**

In `skills/spec-manager/scripts/verify_links.py`, replace the body of the forward loop (the block starting at `if adapter == "manual":` through the `accepted-but-scaffold` check, lines ~108-136) with:

```python
            if adapter == "manual":
                continue

            # Only `accepted` asserts a real linked test, so only accepted
            # *requires* a locator. `proposed`/`confirmed` are pre-test (intent
            # confirmed, test owed — design 03 §3): a missing locator is fine. A
            # locator that IS present is resolved whatever the state, so a typo
            # fails loud.
            if not locator:
                if state == "accepted":
                    errors.append(_err(s.id, bid, "missing-locator",
                                       f"{bid} has adapter '{adapter}' but no locator"))
                continue

            rel_path, _frag = parse_locator(locator)
            abs_path = root / rel_path
            if not abs_path.exists():
                errors.append(_err(s.id, bid, "locator-unresolved",
                                   f"locator path does not exist: {rel_path}"))
                continue

            if adapter in GHERKIN_ADAPTERS:
                text = abs_path.read_text(encoding="utf-8", errors="replace")
                if bid not in extract_behavior_tags(text):
                    errors.append(_err(s.id, bid, "missing-reverse-tag",
                                       f"@{bid} tag not found in {rel_path}"))
                if s.id and s.id not in extract_spec_tags(text):
                    errors.append(_err(s.id, bid, "missing-spec-tag",
                                       f"@{s.id} tag not found in {rel_path}"))
                # Scope the scaffold-marker check to THIS behavior's own scenario
                # so a sibling proposed scaffold in the same file doesn't taint it.
                if state == "accepted":
                    block = scenario_block_for(text, bid)
                    if block is not None and has_scaffold_marker(block):
                        errors.append(_err(s.id, bid, "accepted-but-scaffold",
                                           f"accepted behavior still has {SCAFFOLD_MARKER} in {rel_path}"))
```

(The `entry` resolution check above this block, and the `manual` skip, are unchanged in position — `entry` is still checked for every state because it sits before the `manual` continue.)

- [ ] **Step 4: Run the tests to verify they pass (and nothing regressed)**

Run: `cd skills/spec-manager/scripts && python test_verify_links.py`
Expected: PASS — including the existing `test_clean_set_passes`, `test_broken_locator_reported`, `test_accepted_but_scaffold_reported`, `test_proposed_with_scaffold_is_fine`, and `test_mixed_file_accepted_authored_passes_beside_proposed_scaffold`.

- [ ] **Step 5: Update the `verify` docs**

In `skills/spec-manager/SKILL.md`, in the `verify` command's check list, after the line (line ~337):
```
   - an **accepted** behavior whose feature still carries its `TODO(scaffold)` marker;
```
add:
```
   - (a `proposed`/`confirmed` behavior may omit a locator/test — that is **not** an error;
     a locator or `entry` that *is* declared must still resolve);
```

- [ ] **Step 6: Commit**

```bash
git add skills/spec-manager/scripts/verify_links.py skills/spec-manager/scripts/test_verify_links.py skills/spec-manager/SKILL.md
git commit -m "feat(spec-manager): verify_links allows confirmed/proposed without a test"
```

---

### Task 3: Runner — select states + confirmed → advisory static fingerprint

Generalize the loader to select behaviors by state, and add a per-behavior dispatch that gives `confirmed` behaviors an advisory **static** fingerprint without ever executing a test.

**Files:**
- Modify: `skills/behavior-runner/scripts/run_behaviors.py` (`load_accepted_behaviors` ~lines 30-61; `main` arg parsing + emit loop ~lines 212-254)
- Test: `skills/behavior-runner/scripts/test_run_behaviors.py`
- Docs: `skills/behavior-runner/SKILL.md`

**Interfaces:**
- Consumes: `confirmed` is a valid state (Task 1); `static_fingerprint(behavior, project_dir)`, `run_unit_behavior(behavior, project_dir)`, `shape_fingerprint(...)` (existing).
- Produces:
  - `load_behaviors(specs_dir, states=("accepted",), level=None) -> list[dict]` — new generalized loader.
  - `load_accepted_behaviors(specs_dir, level=None) -> list[dict]` — now a thin wrapper over `load_behaviors(..., states=("accepted",), ...)`; unchanged behavior.
  - `fingerprint_behavior(behavior, project_dir, commit) -> dict` — new; routes one behavior to its fingerprint. `confirmed` → `static_fingerprint` (never executes); else the existing accepted dispatch.
  - CLI: `--states STATE [STATE ...]` (default `["accepted"]`).

- [ ] **Step 1: Write the failing tests**

In `skills/behavior-runner/scripts/test_run_behaviors.py`, first extend the module-level `SPEC` fixture by adding a confirmed behavior (append before the closing `---`, after the BEH-001 block):

```python
  - behavior_id: BEH-004
    title: Authentication start rejects a malformed body (test owed)
    state: confirmed
    level: integration
    entry: app/api/auth/passkey/authenticate/start/route.ts
```

Then add these test classes:

```python
class LoadBehaviorsStatesTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        specs = os.path.join(self.tmp.name, "auth")
        os.makedirs(specs)
        with open(os.path.join(specs, "SPEC-001-passkey-login.md"), "w") as f:
            f.write(SPEC)
        self.specs_dir = self.tmp.name

    def tearDown(self):
        self.tmp.cleanup()

    def test_accepted_loader_still_excludes_confirmed(self):
        got = run_behaviors.load_accepted_behaviors(self.specs_dir)
        ids = sorted(b["behavior_id"] for b in got)
        self.assertEqual(ids, ["BEH-002", "BEH-003"])  # BEH-004 confirmed excluded

    def test_load_behaviors_includes_confirmed_when_requested(self):
        got = run_behaviors.load_behaviors(self.specs_dir, states=("accepted", "confirmed"))
        ids = sorted(b["behavior_id"] for b in got)
        self.assertEqual(ids, ["BEH-002", "BEH-003", "BEH-004"])


class FingerprintBehaviorTest(unittest.TestCase):
    def test_confirmed_uses_static_never_runs_a_test(self):
        beh = {"behavior_id": "BEH-004", "state": "confirmed",
               "level": "integration", "entry": "app/api/x/route.ts"}
        with mock.patch.object(run_behaviors, "static_fingerprint",
                               return_value={"coverage": "static", "exercises": []}) as sf, \
             mock.patch.object(run_behaviors, "run_unit_behavior") as run:
            fp = run_behaviors.fingerprint_behavior(beh, "/proj", "c1")
        sf.assert_called_once()
        run.assert_not_called()
        self.assertEqual(fp["coverage"], "static")

    def test_confirmed_with_unit_adapter_is_still_not_executed(self):
        # State wins over level/adapter: a confirmed behavior naming a vitest
        # test that does not exist yet must NOT be executed.
        beh = {"behavior_id": "BEH-005", "state": "confirmed",
               "level": "unit", "adapter": "vitest", "locator": "x.test.ts::t"}
        with mock.patch.object(run_behaviors, "run_unit_behavior") as run, \
             mock.patch.object(run_behaviors, "static_fingerprint",
                               return_value={"coverage": "unknown", "exercises": [], "reason": "no-entry"}) as sf:
            run_behaviors.fingerprint_behavior(beh, "/proj", "c1")
        run.assert_not_called()
        sf.assert_called_once()

    def test_accepted_unit_vitest_is_executed(self):
        beh = {"behavior_id": "BEH-002", "state": "accepted",
               "level": "unit", "adapter": "vitest", "locator": "x.test.ts::t"}
        with mock.patch.object(run_behaviors, "run_unit_behavior",
                               return_value={"coverage": "observed", "exercises": []}) as run:
            fp = run_behaviors.fingerprint_behavior(beh, "/proj", "c1")
        run.assert_called_once()
        self.assertEqual(fp["coverage"], "observed")

    def test_accepted_integration_uses_static(self):
        beh = {"behavior_id": "BEH-003", "state": "accepted", "level": "integration",
               "entry": "app/api/x/route.ts"}
        with mock.patch.object(run_behaviors, "static_fingerprint",
                               return_value={"coverage": "static", "exercises": []}) as sf:
            fp = run_behaviors.fingerprint_behavior(beh, "/proj", "c1")
        sf.assert_called_once()
        self.assertEqual(fp["coverage"], "static")

    def test_accepted_other_level_is_level_deferred(self):
        beh = {"behavior_id": "BEH-001", "state": "accepted", "level": "e2e", "adapter": "cucumber"}
        fp = run_behaviors.fingerprint_behavior(beh, "/proj", "c1")
        self.assertEqual(fp["coverage"], "unknown")
        self.assertEqual(fp["reason"], "level-deferred")
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `cd skills/behavior-runner/scripts && python test_run_behaviors.py`
Expected: FAIL — `AttributeError: module 'run_behaviors' has no attribute 'load_behaviors'` and `... 'fingerprint_behavior'`.

- [ ] **Step 3: Generalize the loader**

In `skills/behavior-runner/scripts/run_behaviors.py`, replace the whole `load_accepted_behaviors` function (lines ~30-61) with:

```python
def load_behaviors(specs_dir, states=("accepted",), level=None):
    """Return behavior records under specs_dir whose state is in `states`,
    optionally filtered by level.

    Each record is the spec's behavior mapping plus `spec_id` and `spec_path`.
    """
    states = tuple(states)
    out = []
    for root, _dirs, files in os.walk(specs_dir):
        for name in files:
            if not name.endswith(".md"):
                continue
            path = os.path.join(root, name)
            try:
                with open(path, encoding="utf-8") as f:
                    fm, _body = frontmatter.parse_frontmatter(f.read())
            except FrontmatterError as e:
                sys.stderr.write(f"[behavior-runner] skipping unparseable spec {path}: {e}\n")
                continue
            behaviors = fm.get("behaviors")
            if not isinstance(behaviors, list):
                continue
            for b in behaviors:
                if not isinstance(b, dict):
                    continue
                if b.get("state") not in states:
                    continue
                if level is not None and b.get("level") != level:
                    continue
                rec = dict(b)
                rec["spec_id"] = fm.get("id")
                rec["spec_path"] = path
                out.append(rec)
    return out


def load_accepted_behaviors(specs_dir, level=None):
    """Backward-compatible wrapper: accepted behaviors only (used by the
    wrap-up 'run accepted behaviors' path, which must not run confirmed)."""
    return load_behaviors(specs_dir, states=("accepted",), level=level)
```

- [ ] **Step 4: Extract the per-behavior dispatch**

In `skills/behavior-runner/scripts/run_behaviors.py`, add this function just above `def filter_only` (line ~204):

```python
def fingerprint_behavior(behavior, project_dir, commit):
    """Produce one behavior's fingerprint by state then level.

    `confirmed` = intent confirmed, test owed (design 03 §3): it has no
    executable test yet, so it is NEVER run — it gets an advisory STATIC
    fingerprint from its `entry` (or `unknown`/`no-entry` with none). Because it
    is never executed it can never be `test-failed`, so it never gates wrap-up.
    """
    if behavior.get("state") == "confirmed":
        return static_fingerprint(behavior, project_dir)
    if behavior.get("level") == "unit" and behavior.get("adapter") == "vitest":
        return run_unit_behavior(behavior, project_dir)
    # Static integration path is adapter-agnostic (cucumber, native, etc.) — the
    # entry field drives the closure.
    if behavior.get("level") == "integration":
        return static_fingerprint(behavior, project_dir)
    # Non-unit/non-vitest accepted levels are produced by later plans.
    return shape_fingerprint([], commit, reason="level-deferred")
```

- [ ] **Step 5: Wire the CLI flag and emit loop to use them**

In `main`, add the `--states` argument after the `--level` argument (line ~216):

```python
    parser.add_argument("--states", nargs="+", default=["accepted"],
                        help="Behavior states to load (default: accepted only).")
```

Replace the loader call (line ~225):
```python
    behaviors = load_accepted_behaviors(specs_dir, level=args.level)
```
with:
```python
    behaviors = load_behaviors(specs_dir, states=args.states, level=args.level)
```

Replace the emit-fingerprints loop body (lines ~234-245) with:
```python
    if args.emit_fingerprints:
        commit = _git_head(args.project)
        fingerprints = {}
        for b in behaviors:
            fingerprints[b["behavior_id"]] = fingerprint_behavior(b, args.project, commit)
        print(json.dumps({
            "version": 1,
            "commit": commit,
            "fingerprints": fingerprints,
        }, indent=2))
        return 0
```

- [ ] **Step 6: Run the tests to verify they pass (and nothing regressed)**

Run: `cd skills/behavior-runner/scripts && python test_run_behaviors.py`
Expected: PASS — including the existing `LoadAcceptedBehaviorsTest`, `RunUnitBehaviorFailureTest`, and `StaticFingerprintTest` classes.

- [ ] **Step 7: Update the runner docs**

In `skills/behavior-runner/SKILL.md`, after the per-level coverage table (after line 24), add:

```markdown
### Confirmed behaviors (advisory)

A `confirmed` behavior (intent confirmed, test owed — see the lifecycle in
spec-manager) has **no executable test yet**, so the runner never executes it.
When it declares an `entry` it gets an advisory **static** fingerprint (the
code-graph closure of that entry); with no `entry` it is `unknown` / `no-entry`.
Because it is never executed it can never be `test-failed`, so it never gates
wrap-up. Select confirmed behaviors with `--states accepted confirmed`; the
default is `accepted` only, so the wrap-up "run accepted behaviors" path stays
accepted-only.
```

- [ ] **Step 8: Commit**

```bash
git add skills/behavior-runner/scripts/run_behaviors.py skills/behavior-runner/scripts/test_run_behaviors.py skills/behavior-runner/SKILL.md
git commit -m "feat(behavior-runner): state selection + confirmed advisory static fingerprint"
```

---

### Task 4: Graph — project confirmed + advisory (non-gating) guarantee

Project `confirmed` behaviors into `behavior.json` (so Direction A/B see them), request them from the runner, and prove they never block the regression check.

**Files:**
- Modify: `skills/behavior-graph/scripts/behavior_graph.py` (`project_behaviors` ~lines 57-79; `_run_behavior_runner` ~lines 109-114)
- Test: `skills/behavior-graph/scripts/test_behavior_graph.py`
- Docs: `skills/behavior-graph/SKILL.md`

**Interfaces:**
- Consumes: the runner's `--states accepted confirmed` flag (Task 3); records carry `state`.
- Produces:
  - `project_behaviors(specs_dir) -> dict` — now includes records whose `state` is `accepted` **or** `confirmed`.
  - `_run_behavior_runner(project_dir, only=None)` — now invokes the runner with `--states accepted confirmed`.
  - Unchanged: `build`, `direction_a`, `direction_b`, `regression_check` signatures and the merge-by-trust contract.

- [ ] **Step 1: Write the failing tests**

In `skills/behavior-graph/scripts/test_behavior_graph.py`, first extend the module-level `SPEC` fixture by adding a confirmed behavior (after the BEH-001 block, before the closing `---`):

```python
  - behavior_id: BEH-004
    title: Authentication start rejects a malformed body (test owed)
    state: confirmed
    level: integration
    entry: app/api/auth/passkey/authenticate/start/route.ts
```

Update the existing `test_projects_accepted_behaviors_only` assertion to include the confirmed behavior, and rename it:

```python
    def test_projects_accepted_and_confirmed_behaviors(self):
        got = behavior_graph.project_behaviors(self.specs)
        # BEH-001 proposed -> excluded; BEH-004 confirmed -> included.
        self.assertEqual(sorted(got), ["BEH-002", "BEH-003", "BEH-004"])
        self.assertEqual(got["BEH-004"]["state"], "confirmed")
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
```

Add a new test class for the runner-arg and advisory guarantees:

```python
class ConfirmedGraphTest(unittest.TestCase):
    def test_run_behavior_runner_requests_accepted_and_confirmed(self):
        captured = {}

        def fake_run(argv, capture_output, text, check):
            captured["argv"] = argv
            r = mock.MagicMock()
            r.stdout = '{"version": 1, "commit": "x", "fingerprints": {}}'
            return r

        with mock.patch.object(behavior_graph.subprocess, "run", side_effect=fake_run):
            behavior_graph._run_behavior_runner("/proj")
        argv = captured["argv"]
        self.assertIn("--states", argv)
        i = argv.index("--states")
        self.assertEqual(argv[i + 1:i + 3], ["accepted", "confirmed"])

    def test_confirmed_affected_but_never_blocks(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        proj = tmp.name
        behavior_graph.write_behavior_json(proj, {
            "version": 1, "commit": "base",
            "behaviors": {
                "BEH-004": {"spec_id": "SPEC-001", "state": "confirmed", "level": "integration",
                            "coverage": "static",
                            "exercises": [{"path": "app/api/x/route.ts"}]},
            },
        })
        # The confirmed behavior is affected; the runner returns a static
        # fingerprint (never test-failed), so the check must not block.
        runner_out = {"version": 1, "commit": "new", "fingerprints": {
            "BEH-004": {"coverage": "static",
                        "exercises": [{"path": "app/api/x/route.ts", "source": "static",
                                       "confidence": 0.5, "freshness": "new"}]}}}
        with mock.patch.object(behavior_graph, "_changed_files", return_value=["app/api/x/route.ts"]), \
             mock.patch.object(behavior_graph, "_code_graph_impact", return_value={"app/api/x/route.ts"}), \
             mock.patch.object(behavior_graph, "_run_behavior_runner", return_value=runner_out):
            report, code = behavior_graph.regression_check(proj, "base")
        self.assertEqual(code, 0)
        self.assertEqual(report["failed"], [])
        self.assertEqual(report["affected"], ["BEH-004"])
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `cd skills/behavior-graph/scripts && python test_behavior_graph.py`
Expected: FAIL — `test_projects_accepted_and_confirmed_behaviors` fails because `project_behaviors` excludes the confirmed BEH-004, and `test_run_behavior_runner_requests_accepted_and_confirmed` fails because `--states` is not in the argv.

- [ ] **Step 3: Project confirmed behaviors**

In `skills/behavior-graph/scripts/behavior_graph.py`, in `project_behaviors`, replace the filter line (line ~70):

```python
                if not isinstance(b, dict) or b.get("state") != "accepted":
                    continue
```
with:
```python
                # accepted (authoritative) + confirmed (advisory, test owed) both
                # belong in the graph so Direction A/B can see them; proposed does
                # not (it is not confirmed intent). confirmed never gates because
                # the runner never executes it (design 03 §3).
                if not isinstance(b, dict) or b.get("state") not in ("accepted", "confirmed"):
                    continue
```

Also update the docstring of `project_behaviors` (line ~58):
```python
    """Map BEH-NNN -> projected frontmatter fields for every accepted behavior."""
```
to:
```python
    """Map BEH-NNN -> projected frontmatter fields for every accepted or
    confirmed behavior (proposed is excluded)."""
```

- [ ] **Step 4: Request confirmed fingerprints from the runner**

In `_run_behavior_runner` (line ~110), replace:
```python
    argv = [sys.executable, str(_RUNNER), "--project", project_dir, "--emit-fingerprints"]
```
with:
```python
    argv = [sys.executable, str(_RUNNER), "--project", project_dir,
            "--states", "accepted", "confirmed", "--emit-fingerprints"]
```

- [ ] **Step 5: Run the tests to verify they pass (and nothing regressed)**

Run: `cd skills/behavior-graph/scripts && python test_behavior_graph.py`
Expected: PASS — including the existing `BuildTest`, `MergeFingerprintTest`, and `RegressionCheckTest` classes.

- [ ] **Step 6: Update the graph docs**

In `skills/behavior-graph/SKILL.md`, replace the Direction A bullet (line 19):
```
- **Direction A** — `affected <changed-files>`: which accepted behaviors a code change touches.
```
with:
```
- **Direction A** — `affected <changed-files>`: which accepted or confirmed behaviors a code change touches.
```

After the "Merge by trust" table (after line 34), add:
```markdown
> **Confirmed behaviors are advisory.** `confirmed` behaviors (intent confirmed,
> test owed) are projected into `behavior.json` and surface in Direction A/B, but
> the runner never executes them, so they only ever carry a `static` or `unknown`
> fingerprint — never `test-failed`. The regression `--check` therefore never
> blocks on a confirmed behavior; only `accepted` behaviors gate.
```

- [ ] **Step 7: Commit**

```bash
git add skills/behavior-graph/scripts/behavior_graph.py skills/behavior-graph/scripts/test_behavior_graph.py skills/behavior-graph/SKILL.md
git commit -m "feat(behavior-graph): project confirmed behaviors (advisory, non-gating)"
```

---

## Dogfooding pass (manual — run after Task 4, not a TDD task)

Prove the mechanism end-to-end on the **testbed** (`/Users/main/Documents/projects/viva-croatia-testbed`). The production webapp stays untouched.

- [ ] **D1:** In the testbed spec `knowledge-base/specs/auth/SPEC-001-passkey-login.md`, add a `confirmed` behavior with a real, currently-untested intent and an `entry` pointing at an existing route, e.g.:
  ```yaml
    - behavior_id: BEH-004
      title: Authentication start rejects a malformed request body
      state: confirmed
      level: integration
      entry: app/api/auth/passkey/authenticate/start/route.ts
  ```
- [ ] **D2:** Verify links pass (confirmed needs no test):
  ```bash
  python skills/spec-manager/scripts/verify_links.py --dir /Users/main/Documents/projects/viva-croatia-testbed/knowledge-base/specs --format json
  ```
  Expected: exit 0, `[]` (no `missing-locator` for BEH-004; if the `entry` path is wrong you get `entry-unresolved`).
- [ ] **D3:** Build the behavior graph and confirm BEH-004 appears with an advisory static fingerprint:
  ```bash
  python skills/behavior-graph/scripts/behavior_graph.py --build --project /Users/main/Documents/projects/viva-croatia-testbed
  ```
  Expected: `behaviors["BEH-004"]` present with `"state": "confirmed"` and `"coverage": "static"` (assuming the testbed has a built code-graph; otherwise `"coverage": "unknown"`, `"reason": "no-graph"` — run `code-graph build` first).
- [ ] **D4:** Make a no-op edit to the `entry` route in the testbed, commit it, then run the regression check and confirm it does **not** block on the confirmed behavior:
  ```bash
  python skills/behavior-graph/scripts/behavior_graph.py --check --base HEAD~1 --project /Users/main/Documents/projects/viva-croatia-testbed
  ```
  Expected: BEH-004 in `affected`, empty `failed`, exit 0 (advisory, non-gating).
- [ ] **D5:** Log any friction in `docs/design/behavior-layer/dogfooding-notes.md` (new F-entry), and revert the testbed no-op edit if it was only for D4.

---

## Final whole-branch review

After Task 4 (and the dogfooding pass), dispatch the final whole-branch review (superpowers:requesting-code-review) over the SP1 commits, then proceed to `superpowers:finishing-a-development-branch`.
