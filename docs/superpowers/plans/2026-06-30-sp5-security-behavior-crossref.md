# SP5 — Security ↔ Behavior Cross-Reference Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Let `codebase-security-scan` treat an `accepted`, test-backed behavior whose intent explains a flagged finding as the strongest "intentional" evidence — downgrading the finding (with a `behavior_ref`) while keeping it visible — via a new `behavior-graph --covering` query.

**Architecture:** A new read-only `behavior_graph.py --covering <file>` returns the `accepted` behaviors whose `exercises` include a file. The `codebase-security-scan` cross-reference step (which already matches findings to declarative specs) gains a parallel behavior pass: prefilter with `--covering`, judge relevance, and on an accepted match mark the finding intentional with `behavior_ref`. The `findings.json` schema gains a `behavior_ref` field.

**Tech Stack:** Python 3.12, stdlib only (`unittest`, `unittest.mock`). Tests run with `python test_behavior_graph.py` from the script's dir. The scan cross-reference is an agent-driven SKILL.md procedure (validated by the dogfood).

## Global Constraints

- **Stdlib-only Python** — no new imports.
- **Only `accepted` (verified) behaviors downgrade a finding.** `--covering` returns only `accepted` behaviors; the SKILL.md rule restricts downgrade to accepted matches. A `confirmed`/`proposed` behavior never silences a finding — at most an advisory note; the finding stays `open`.
- **Downgrade = annotate, never delete.** A behavior-explained finding is marked `status: intentional` with a `behavior_ref` and a "verified by passing test" note, and stays visible in the prose report (safe, auditable, reversible).
- **Evidence ranking:** an accepted-behavior match is the strongest evidence — it stands even when no declarative spec covers the finding (verified > declarative).
- **`--covering` is read-only** and returns an empty `covering` list (with the file echoed) when there is no graph / no accepted behavior covers the file; never raises.
- **No discovery change** — SP5 only changes how findings are *cross-referenced*, not how they are found.
- **Production webapp `/Users/main/Documents/areas/viva-croatia/webapp/` is OFF-LIMITS.** The dogfood uses only the testbed `/Users/main/Documents/projects/viva-croatia-testbed`.

---

### Task 1: `behavior-graph --covering <file>`

Add a read-only query returning the accepted behaviors that exercise a given file.

**Files:**
- Modify: `skills/behavior-graph/scripts/behavior_graph.py` (add `covering`; CLI)
- Test: `skills/behavior-graph/scripts/test_behavior_graph.py` (add to `SurfaceTest`)

**Interfaces:**
- Consumes (existing): `load_behavior_json(project_dir)` — `behavior.json` records carry `state`, `spec_id`, `coverage`, `exercises`.
- Produces:
  - `covering(project_dir, file) -> dict` — `{version, file, covering: [{behavior_id, spec_id, coverage}]}`, `accepted`-only, sorted by `behavior_id`.
  - CLI: `--covering FILE` (mutually exclusive group).

- [ ] **Step 1: Write the failing tests**

Add these methods to the existing `SurfaceTest` class in `skills/behavior-graph/scripts/test_behavior_graph.py` (its fixture's `behavior.json` has accepted `BEH-002` exercising `lib/webauthn.ts` and confirmed `BEH-006` exercising `app/api/x/route.ts`):

```python
    def test_covering_returns_accepted_behavior_for_file(self):
        r = behavior_graph.covering(self.proj, "lib/webauthn.ts")
        self.assertEqual(r["file"], "lib/webauthn.ts")
        self.assertEqual([c["behavior_id"] for c in r["covering"]], ["BEH-002"])
        self.assertEqual(r["covering"][0]["spec_id"], "SPEC-100")

    def test_covering_excludes_confirmed_behavior(self):
        # BEH-006 (confirmed) exercises app/api/x/route.ts but is NOT accepted,
        # so it must not be returned — only verified behaviors downgrade findings.
        r = behavior_graph.covering(self.proj, "app/api/x/route.ts")
        self.assertEqual(r["covering"], [])

    def test_covering_excludes_noncovering_file(self):
        r = behavior_graph.covering(self.proj, "lib/util.ts")
        self.assertEqual(r["covering"], [])

    def test_covering_no_graph_returns_empty_with_file(self):
        import shutil
        shutil.rmtree(os.path.join(self.proj, "knowledge-base", ".graph"))
        r = behavior_graph.covering(self.proj, "lib/webauthn.ts")
        self.assertEqual(r["file"], "lib/webauthn.ts")
        self.assertEqual(r["covering"], [])
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `cd skills/behavior-graph/scripts && python test_behavior_graph.py -k SurfaceTest`
Expected: FAIL — `AttributeError: module 'behavior_graph' has no attribute 'covering'`.

- [ ] **Step 3: Add `covering`**

In `skills/behavior-graph/scripts/behavior_graph.py`, add after `gaps`:

```python
def covering(project_dir, file):
    """Accepted behaviors whose `exercises` include `file` (read-only).

    Only `accepted` (test-verified) behaviors are returned — they are the
    strongest "intentional" evidence for the security cross-reference (SP5).
    Empty `covering` (file echoed) when there is no graph or none cover it.
    """
    behaviors = load_behavior_json(project_dir).get("behaviors", {})
    out = []
    for bid, rec in behaviors.items():
        if rec.get("state") != "accepted":
            continue
        paths = {e["path"] for e in rec.get("exercises", [])}
        if file in paths:
            out.append({"behavior_id": bid, "spec_id": rec.get("spec_id"),
                        "coverage": rec.get("coverage")})
    out.sort(key=lambda c: c["behavior_id"])
    return {"version": 1, "file": file, "covering": out}
```

- [ ] **Step 4: Wire the CLI**

In `main`, add `--covering` to the mutually exclusive group (alongside `--build`/`--affected`/`--implements`/`--check`/`--surface`/`--gaps`):

```python
    group.add_argument("--covering", metavar="FILE",
                       help="Accepted behaviors whose exercised code includes FILE (security cross-ref).")
```

And handle it — add this block right before the existing `if args.gaps:` block:

```python
    if args.covering:
        print(json.dumps(covering(args.project, args.covering), indent=2))
        return 0
```

- [ ] **Step 5: Run the tests to verify they pass (and nothing regressed)**

Run: `cd skills/behavior-graph/scripts && python test_behavior_graph.py`
Expected: PASS — the new `covering` tests and all existing classes.

- [ ] **Step 6: Commit**

```bash
git add skills/behavior-graph/scripts/behavior_graph.py skills/behavior-graph/scripts/test_behavior_graph.py
git commit -m "feat(behavior-graph): --covering query (accepted behaviors exercising a file)"
```

---

### Task 2: Scan cross-reference extension + `behavior_ref` schema

Teach `codebase-security-scan` to consult accepted behaviors as verified intentional evidence, and add `behavior_ref` to the findings schema.

**Files:**
- Modify: `skills/codebase-security-scan/references/findings-schema.md` (add `behavior_ref`)
- Modify: `skills/codebase-security-scan/SKILL.md` (check-specs Phase 3 behavior pass; the `findings.json` emit step)

**Interfaces:**
- Consumes: `behavior-graph --covering <file>` (Task 1).
- Produces: documented cross-reference behavior (no code interface).

- [ ] **Step 1: Add `behavior_ref` to the findings schema**

In `skills/codebase-security-scan/references/findings-schema.md`:

In the JSON example, replace the `spec_ref` line:
```
      "spec_ref": "SPEC-001"
```
with:
```
      "spec_ref": "SPEC-001",
      "behavior_ref": "BEH-003"
```

Replace the `intentional` status rule:
```
  - `intentional` — explained by a declarative spec decision (the existing
    `check-specs` cross-reference); `spec_ref` names that spec.
```
with:
```
  - `intentional` — explained by intent, so not outstanding. Either a declarative
    spec decision (`spec_ref` names the spec — a prose claim) **or** an `accepted`,
    test-backed behavior whose intent explains it (`behavior_ref` names the behavior
    — a *verified guarantee*, the stronger evidence). A finding may carry both.
```

Replace the `spec_ref` field rule:
```
- `spec_ref` — the spec marking it intentional, when known (optional).
```
with:
```
- `spec_ref` — the declarative spec marking it intentional, when known (optional).
- `behavior_ref` — the `accepted` behavior (`BEH-NNN`) whose verified intent explains
  the finding, when known (optional). A behavior-explained finding is the strongest
  "intentional" evidence (test-backed, not a prose claim).
```

- [ ] **Step 2: Add the behavior pass to check-specs Phase 3**

In `skills/codebase-security-scan/SKILL.md`, replace the `**Phase 3: Cross-Reference Each Finding**` block:

```
**Phase 3: Cross-Reference Each Finding**
For each finding:
1. Identify the feature/component involved
2. Search specs for matching feature/component
3. Check if spec explicitly allows the "vulnerable" behavior
4. If match found:
   - Update status to **INTENTIONAL DESIGN**
   - Add spec reference
   - Include rationale from spec
```

with:

```
**Phase 3: Cross-Reference Each Finding**
For each finding, check two evidence sources — declarative specs and verified behaviors:

*Declarative specs (existing):*
1. Identify the feature/component involved
2. Search specs for matching feature/component
3. Check if a spec explicitly allows the "vulnerable" behavior
4. If a spec match is found:
   - Update status to **INTENTIONAL DESIGN**
   - Add the spec reference (`spec_ref`) and include the rationale from the spec

*Accepted behaviors (verified guarantee — the stronger evidence):*
5. Run the behavior graph to find the `accepted` behaviors that exercise the
   finding's file:
   ```bash
   python "${CLAUDE_PLUGIN_ROOT}/skills/behavior-graph/scripts/behavior_graph.py" \
     --covering <finding-file> --project .
   ```
6. For each returned behavior, read its intent (its spec's Behavior entry /
   rationale) and judge: **does this behavior's verified intent explain this
   finding?** (the same relevance judgment as for specs)
7. If an accepted behavior explains the finding:
   - Update status to **INTENTIONAL DESIGN** and record `behavior_ref: BEH-NNN`
   - Note *"verified by passing test BEH-NNN (SPEC-MMM)"* — this is the **strongest**
     evidence and stands even when no declarative spec covers the finding (verified >
     a prose claim). A finding may carry both `spec_ref` and `behavior_ref`.
8. **Only `accepted` behaviors downgrade a finding.** `--covering` returns only
   accepted behaviors; if a `proposed`/`confirmed` behavior is known to be relevant,
   add only an advisory note ("intended per BEH-NNN, but test owed — not yet
   verified") and **leave the finding open**.
```

- [ ] **Step 3: Note `behavior_ref` in the findings.json emit step**

In `skills/codebase-security-scan/SKILL.md`, in the `#### Also emit \`findings.json\`` subsection (added in SP4), find the sentence listing the per-finding fields ("...with `id`, `title`, `severity`, `status` ... `file`, optional `line`, and `spec_ref` when a spec marks the finding intentional.") and extend it to also mention `behavior_ref`:

Replace:
```
`file`, optional `line`, and `spec_ref`
when a spec marks the finding intentional.
```
with:
```
`file`, optional `line`, `spec_ref`
when a declarative spec marks the finding intentional, and `behavior_ref` when an
`accepted` behavior verifiably explains it (the stronger evidence).
```

(If the exact wrapping differs, match on the `spec_ref when a spec marks the finding intentional` phrase and add the `behavior_ref` clause.)

- [ ] **Step 4: Verify the edits**

Run:
```bash
cd /Users/main/Documents/projects/freya-devkit
grep -n "behavior_ref\|--covering" skills/codebase-security-scan/SKILL.md skills/codebase-security-scan/references/findings-schema.md
```
Expected: `behavior_ref` appears in both files; the `--covering` invocation appears in the SKILL.md Phase 3 behavior pass. Visually confirm the behavior pass sits inside check-specs Phase 3 and the schema example/rules are consistent.

- [ ] **Step 5: Commit**

```bash
git add skills/codebase-security-scan/SKILL.md skills/codebase-security-scan/references/findings-schema.md
git commit -m "feat(codebase-security-scan): cross-reference accepted behaviors as verified intentional evidence"
```

---

## Dogfooding pass (manual — run after Task 2, not a TDD task)

Validate the BEH-003 exemplar on the **testbed** (`main` has accepted BEH-002/003). Production webapp untouched.

- [ ] **D1 — covering query.** On the testbed (with a built `behavior.json` — run `behavior-graph --build --project <testbed>` if needed), run:
  ```bash
  python skills/behavior-graph/scripts/behavior_graph.py --covering app/api/auth/passkey/authenticate/start/route.ts --project <testbed>
  ```
  Expect `BEH-003` (accepted, exercises the auth-start route) in `covering`; confirm a `confirmed`/`proposed` behavior on the same file (if any) is absent.
- [ ] **D2 — verified downgrade.** On a testbed branch, hand-write a `findings.json` (per the schema) with an `open` finding like `{"id":"SEC-001","title":"auth-start endpoint does not verify the user exists","severity":"medium","status":"open","file":"app/api/auth/passkey/authenticate/start/route.ts"}`. Walk the check-specs Phase 3 behavior pass: `--covering` surfaces BEH-003; judge that its anti-enumeration intent explains the finding; update the finding to `status: intentional`, `behavior_ref: BEH-003`. Re-run `status` and confirm the finding **drops from the open count** (and a `proposed`/`confirmed`-only case would have stayed open).
- [ ] **D3 — uncovered finding stays open.** Add a second `open` finding on a file no accepted behavior exercises (e.g. `lib/date-formatter.ts`); confirm `--covering` returns empty and the finding stays `open`.
- [ ] **D4 — Log friction** in `docs/design/behavior-layer/dogfooding-notes.md` (new SP5 entry). Restore the testbed to `main`; retain/clean the dogfood branch.

---

## Final whole-branch review

After Task 2 and the dogfood, dispatch the final whole-branch review (superpowers:requesting-code-review) over the SP5 commits (base = the SP5 plan commit), pointing it at any Minor findings recorded in the ledger. SP5 is the last sub-project of the Adoption & Intent Lifecycle track; the branch `feat/behavior-layer` remains unmerged pending the user's decision to land the whole track.
