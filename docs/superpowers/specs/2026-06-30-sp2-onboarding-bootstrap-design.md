# SP2 — Onboarding & Bootstrap (design)

**Status:** Draft for review
**Date:** 2026-06-30
**Parent design:** `docs/design/behavior-layer/03-adoption-and-intent-lifecycle.md` (§4 onboarding, §9 SP2, §11 open questions, §12 acceptance criteria).
**Depends on:** SP1 (the `confirmed` lifecycle state) is shipped; `spec-manager init` + `scan`, `code-graph build`, `behavior-graph build`, and `docs-manager`'s `detect_project.py` all exist.

---

## 1. Goal

One "bring the plugin up on this project" flow that replaces today's run-each-command-by-hand setup. On a **brownfield** repo it ends with a full corpus of `proposed` candidate behaviors (the review queue); on a **greenfield** repo it degrades gracefully — sets up structure and empty graphs, skips inference, and says so. This satisfies §12's criterion:

> A unified onboarding bootstraps a full **`proposed`** behavior graph on a brownfield project, and degrades gracefully (no pointless inference, clear message) on greenfield.

## 2. Resolved decisions (from brainstorming)

- **Inference grain — per observable behavior.** Bootstrap infers one `proposed` behavior per observable behavior/scenario (anchored to a route/entry where applicable), matching `scan`'s existing "expressible as a test?" classifier — not per-feature (too coarse to map or validate) and not per-route/function (reintroduces the "tests mirror code" smell). Each candidate therefore surfaces precisely on the code it exercises, which is what makes SP3's validate-on-hit usable.
- **Re-scan cadence — lazy.** SP2 builds only the **one-time** bootstrap. Newly-written code acquires intent later through SP3's "touched code with no covering behavior → capture one?" prompt. One inference path; no second eager mechanism to keep in sync.
- **Greenfield/brownfield detection — detect + recommend + user confirms.** Compute a transparent signal and *recommend* a branch with its evidence; the engineer confirms or overrides. No brittle magic threshold; a one-time interactive step keeps a human in the loop.
- **Home — a `bootstrap` command in spec-manager** (not a new top-level skill). `init` and `scan` already live there; bootstrap is the unified extension of `init`, and spec-manager already orchestrates a sibling skill (`update` calls `code-graph impact`), so the pattern is established.
- **Additive, never clobber.** On a partially-onboarded repo, bootstrap infers candidates only for the *unspecced* areas; it never overwrites existing specs.

## 3. Architecture

The deterministic, unit-tested core is one small **detector** script; the orchestration is a SKILL.md procedure that sequences existing commands.

### 3.1 `project_shape.py` (new, deterministic)

`skills/spec-manager/scripts/project_shape.py` — classify a project's shape from objective signals.

- **Inputs:** `--project <dir>` (and `--format json|text`).
- **Reads:**
  - code-graph's `knowledge-base/.graph/graph.json` if present — counts **internal source files** (nodes) and **internal import edges** (edges between project files, excluding `node_modules`/externals).
  - `detect_project.py` (docs-manager) — runtime, package manager, frameworks, test runners.
- **Emits JSON:**
  ```json
  {
    "recommendation": "brownfield" | "greenfield" | "unknown",
    "evidence": {
      "source_files": <int>,
      "internal_edges": <int>,
      "stack": { ...detect_project output... },
      "graph_present": <bool>
    },
    "reason": "<one-line human explanation>"
  }
  ```
- **Recommendation rule (transparent, since the human confirms):**
  - `graph.json` absent or unreadable → `unknown` (orchestration falls back to "always ask").
  - `internal_edges == 0` (no real wiring — bare scaffold, even if many boilerplate files exist) → `greenfield`.
  - `internal_edges > 0` → `brownfield`.
  - The exact counts are always reported as `evidence` so the recommendation is explainable and the user can override on sight.
- **No mutation.** Pure read + classify. Stdlib-only.

### 3.2 `bootstrap` command (spec-manager SKILL.md procedure)

A new command documented in `skills/spec-manager/SKILL.md`, added to the Quick Reference table. It is an agent-orchestrated procedure (like `scan`/`update`), not a script. Sequence:

1. **`spec-manager init`** — knowledge-base structure + `principles.md`. Idempotent (never clobbers existing files).
2. **`code-graph build`** — always run; cheap, and the detector needs it. (If the project has a stale/partial graph, this refreshes it.)
3. **`project_shape`** — run the detector; **print the evidence and the recommendation**, then ask the engineer to confirm the branch or override. On `unknown`, ask outright (no recommendation).
4. **Branch:**
   - **Brownfield →** run **`scan`** at the per-observable-behavior grain (all candidates `proposed`, written as behavior records in `knowledge-base/specs/`, **never** `.feature` scaffolds in the code tree — those appear only on acceptance). On a partially-onboarded repo, scan is **additive**: it covers unspecced areas and does not overwrite existing specs. Then **`behavior-graph build`**. Warn up front that scan over a large repo can take a while (it spawns discovery agents).
   - **Greenfield →** skip `scan`; ensure an empty behavior graph exists; print a clear message: *"Greenfield project — no inference run. Author behaviors forward as you build (spec-manager create)."* Done.
5. **Summary** — report what was created: knowledge-base layout, graph built, and (brownfield) a count of proposed candidates by category, with the reminder that **nothing needs review now** — the queue is drained lazily (SP3 on-hit, SP4 worklists).

## 4. Data flow & a subtlety

The "full proposed behavior graph" produced by bootstrap is the corpus of **`proposed` behavior records in `knowledge-base/specs/`** — the review queue — **not** `behavior.json`. `behavior.json` projects only `accepted`/`confirmed` behaviors (SP1), so it stays ≈empty at first run, which is correct: bootstrap fills the candidate corpus; SP3/SP4 drain it as candidates get confirmed and accepted. Bootstrap builds `behavior.json` anyway so the graph machinery is initialized and ready.

## 5. Error & edge handling

- **Already-onboarded / partial repo:** detect existing `knowledge-base/specs/` content. Bootstrap proceeds **additively** (scan infers only unspecced areas; existing specs are untouched) and says so in the summary — it does not refuse, and it does not re-infer over already-specced areas.
- **code-graph build fails / unparseable repo:** `project_shape` returns `unknown`; the procedure falls back to asking the engineer directly rather than guessing a branch.
- **Greenfield but the user overrides to brownfield (or vice versa):** the confirm/override step is authoritative — the recommendation never forces a branch.
- **Scan cost on large repos:** surfaced as an explicit up-front warning in the brownfield branch (one-time cost; the design accepts longer setup).

## 6. Testing

- **`project_shape.py` — unit tests** (`test_project_shape.py`, stdlib `unittest`, on-disk tempdir fixtures + synthetic `graph.json`):
  - brownfield: a `graph.json` with internal edges > 0 → `recommendation: brownfield`, evidence counts correct.
  - greenfield: a `graph.json` with 0 internal edges (scaffold) → `greenfield`.
  - missing graph: no `graph.json` → `unknown`, `graph_present: false`, falls back signal present.
  - evidence shape: `source_files`/`internal_edges`/`stack`/`graph_present` keys always present; output is valid JSON.
- **Orchestration — dogfood on the testbed** (the brownfield proving ground; production webapp off-limits). This is the test the parking-lot flagged as missing ("`scan` brownfield import is undogfooded"): run `bootstrap` on the testbed (mostly unspecced beyond passkey auth), confirm the brownfield branch, and **judge whether the proposed queue is manageable** at the per-observable-behavior grain — and that existing passkey specs are untouched (additive). Log friction in `dogfooding-notes.md`. Also exercise the greenfield branch on a throwaway empty/scaffold dir to confirm graceful skip + message.

## 7. Scope

**In scope:** `project_shape.py` + tests; the `bootstrap` command procedure (init → code-graph build → detect/recommend/confirm → GF/BF branch → scan/behavior-graph build); greenfield degradation; additive behavior on partial repos; the testbed dogfood.

**Out of scope:** re-scan of newly-written code (→ SP3's on-hit prompt); worklists, `status`, and `BACKLOG.md` (→ SP4); any change to `scan`'s internal discovery mechanics beyond invoking it at the agreed grain; observed-coverage adapters (parking-lot).

## 8. Acceptance criteria

- [ ] `project_shape.py` classifies a project as `brownfield` / `greenfield` / `unknown` from code-graph counts + `detect_project`, always emitting the evidence, and is unit-tested.
- [ ] `spec-manager bootstrap` runs init → code-graph build → detect/recommend/confirm, then branches: brownfield runs `scan` (per-observable-behavior, all `proposed`, additive) + `behavior-graph build`; greenfield skips inference with a clear message.
- [ ] On a partially-onboarded repo, bootstrap does not clobber or re-infer existing specs.
- [ ] No `.feature` scaffolds are written into the code tree by bootstrap (inference produces only `proposed` behavior records in `knowledge-base/specs/`).
- [ ] Dogfooded on the testbed: the brownfield queue is manageable at the chosen grain and existing specs are untouched; the greenfield branch degrades gracefully; friction logged.

## 9. Open questions

None blocking. The §11 items this sub-project owned are resolved in §2. The exact internal-edge threshold is intentionally simple (`> 0`) and explainable; if the testbed dogfood shows it misclassifies real repos, refine the rule (it is advisory + overridable, so a wrong recommendation is never silently binding).
