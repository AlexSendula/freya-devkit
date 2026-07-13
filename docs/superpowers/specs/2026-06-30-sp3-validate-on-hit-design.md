# SP3 — Validate-on-hit (design)

**Status:** Draft for review
**Date:** 2026-06-30
**Parent design:** `docs/design/behavior-layer/03-adoption-and-intent-lifecycle.md` (§5 validate-on-hit, §9 SP3, §12 acceptance criteria).
**Depends on:** SP1 (the `confirmed` state + the accepted-only regression gate) and SP2 (bootstrap produces the `proposed` corpus, anchored per-observable-behavior to an `entry`). Builds on the existing wrap-up Phase 3.5 (verify_links → behavior-graph `--build` → `--check`) and `behavior-graph`'s `direction_a` / `code_graph_impact`.

---

## 1. Goal

At wrap-up, after the existing **gated** regression check on accepted behaviors, do two **non-gating** things that drain the `proposed` corpus organically as the team works:

1. **Validate-on-hit** — surface the proposed/confirmed behaviors a change actually touches, re-inferred against current code, for confirmation. Bounded to the touched subset; prominent but skippable.
2. **Recall gap** — flag touched code that **no** behavior covers, and offer to capture one.

This satisfies §12:

> At wrap-up, a change surfaces its **affected** proposed/confirmed behaviors (bounded, skippable) and flags touched code with **no** covering behavior.

## 2. Resolved decisions (from brainstorming)

- **Hit matching — precise exercises-closure.** A proposed/confirmed behavior is "affected" by the same rule accepted behaviors already use: its entry-closure (code-graph dependency set) intersects the change's blast radius (`code_graph_impact`). This catches dependency-level hits (editing a lib the entry imports surfaces the behavior), consistent with accepted/confirmed surfacing — not a coarse entry-only match.
- **`behavior.json` unchanged.** Proposed behaviors stay **out** of the projected graph (SP1/SP2 invariant). Their footprints are computed **on-demand** in the surface query, prefiltered to candidates near the change, reusing behavior-runner's static-closure code. Confirmed are already in the graph (SP1) and matched via `direction_a`.
- **Refresh-on-hit — full agent re-inference.** Each surfaced candidate the engineer chooses to review is re-inferred against the entry's *current* code (fresh title/description), never shown as a stale bootstrap guess. **Bounded** by Direction A (only the affected subset) and **skippable**, so it never fans out over the whole backlog.
- **Advisory / non-gating.** Nothing in this phase changes wrap-up's exit code. Only the existing accepted-`test-failed` gate (SP1) blocks. Surfacing is prominent (default-on) but skippable.
- **Home — a `behavior-graph --surface --base <commit>` subcommand** (deterministic, testable), consumed by wrap-up's Phase 3.5 procedure (which drives the interactive prompts). Keeps wrap-up thin.

## 3. The `--surface --base <commit>` query (deterministic core)

`behavior_graph.py` gains a `--surface --base <commit>` mode. Given `changed = git diff base..HEAD` (project-relative) and `impact = _code_graph_impact(changed, project_dir)`, it emits JSON:

```json
{
  "version": 1,
  "base": "<commit>",
  "changed": ["..."],
  "affected_accepted": ["BEH-002"],
  "validate_candidates": [
    {"behavior_id": "BEH-004", "state": "proposed", "spec_id": "SPEC-002",
     "title": "...", "entry": "app/api/posts/[id]/lock/route.ts", "spec_path": "knowledge-base/specs/features/SPEC-002-post-locking.md"}
  ],
  "recall_gaps": ["app/api/posts/[id]/discard-draft/route.ts"]
}
```

- **`affected_accepted`** — accepted behaviors (from `behavior.json`) whose `exercises ∩ impact ≠ ∅`. Context only; already handled (gated) by `--check`. Not re-validated.
- **`validate_candidates`** — the affected **proposed + confirmed** behaviors:
  - *confirmed* — from `behavior.json` via `direction_a` (already projected), filtered to `state == "confirmed"`.
  - *proposed* — read from specs (frontmatter); **prefiltered** to those whose `entry` (or spec `related_code`) intersects `impact` (cheap), then each prefiltered candidate's entry-closure is computed (reuse behavior-runner's `static_exercises` + `_code_graph_deps`) and intersected with `impact`. A proposed behavior with no `entry` is **not** surfaced here (it is worklist-only — SP4).
  - Each entry carries enough to act: `behavior_id`, `state`, `spec_id`, `spec_path`, `title`, `entry`.
- **`recall_gaps`** — changed **source** files (code-graph-recognised languages) not in `covered`, where `covered = {paths in any behavior.json exercises} ∪ {every behavior's declared entry across all specs}`. Cheap set math; no per-proposed closure. May over-flag a file only transitively covered by a proposed candidate (not its entry) — that over-prompts, the safe direction (design §5: never silently accumulate unguarded intent).

The query is **read-only** and never fails the build: missing graph / missing base / git error → empty buckets with a `note` field explaining why (advisory).

## 4. wrap-up Phase 3.5 interaction (procedure)

Phase 3.5 keeps its current order, then adds a surfacing step **after** the gated `--check` (so a real regression is dealt with first):

1. (unchanged) verify_links hard-block.
2. (unchanged) `--build` then `--check --base BASE` — gated regression on affected accepted behaviors.
3. **(new) Surface.** Run `behavior-graph --surface --base BASE`. Then, **non-gating and skippable**:
   - **Validate-candidates** (bounded to the affected subset): announce the count; for each candidate the engineer reviews, **re-infer** it — re-read the `entry`'s current code and produce a refreshed title/description/rationale — and present it. The engineer **confirms** (`proposed → confirmed`: bump the behavior's `state` in its spec frontmatter via spec-manager; a candidate already `confirmed` is reminded its test is owed), **edits** then confirms, or **skips**. The whole step is skippable in one action.
   - **Recall-gaps:** if any, prompt "these N touched files have no covering behavior — capture one?" → optionally author a new `proposed`/`confirmed` behavior record (spec-manager `create`/classify), or skip.
4. Continue to Phase 4 (security) regardless — surfacing never blocks.

Staging note: a newly-`confirmed` behavior's spec edit is an **artifact** (commit 2), consistent with wrap-up's behavior-aware staging rule (intent records are artifacts; only `accepted` tests are code).

## 5. Error & edge handling

- **No graph / no base / not a git repo:** `--surface` returns empty buckets + a `note`; wrap-up prints it and moves on. Never blocks.
- **Re-inference cost:** bounded by Direction A (affected subset only) and the whole validate step is skippable — a large or sprawling change cannot trigger an unbounded agent fan-out. If the affected-candidate count is large, wrap-up reports the count and lets the engineer review a few or skip the rest (worklists in SP4 are the place to grind the tail).
- **Proposed candidate whose `entry` no longer resolves:** excluded from `validate_candidates` (no closure) and its stale `entry` is already caught by `verify_links` (`entry-unresolved`) in step 1.
- **A confirmed candidate confirmed-on-hit but still test-owed:** stays `confirmed` (no auto-accept — we confirm intent, never author tests); the test-owed reminder routes to SP4's worklist.

## 6. Testing

- **`--surface` — unit tests** (`test_behavior_graph.py`, stdlib `unittest`, tempdir fixtures + synthetic `behavior.json`/specs, mocking `_code_graph_impact` and the static-closure helper as the existing tests do):
  - affected proposed surfaced via on-demand entry-closure ∩ impact; entry-less proposed NOT surfaced.
  - affected confirmed surfaced from the graph; accepted go to `affected_accepted`, not `validate_candidates`.
  - prefilter correctness (a proposed behavior whose entry is far from impact is not closure-computed/surfaced).
  - `recall_gaps` set math: a changed source file in no exercise and no declared entry is flagged; one that is a declared entry or in an exercise is not.
  - empty-graph / no-base degradation → empty buckets + `note`, exit 0.
- **Interactive loop — testbed dogfood.** Reuse the `dogfood/sp2-bootstrap` branch (it has `SPEC-002`'s proposed post-locking behaviors anchored to the lock/claim routes). Edit the lock route, run the wrap-up surfacing step, and verify: the affected proposed behaviors surface, re-inference presents a current-code description, confirming one bumps it `proposed → confirmed` in the spec, and a touched file with no covering behavior appears as a recall gap. Log friction in `dogfooding-notes.md`. Production webapp stays off-limits.

## 7. Scope

**In scope:** the `behavior-graph --surface --base` query (three buckets, on-demand proposed closure, recall-gap set math); the wrap-up Phase 3.5 surfacing/re-inference/confirm/capture procedure; the `proposed → confirmed` bump on confirm.

**Out of scope:** worklists / `status` / `BACKLOG.md` (→ SP4 — the place to work the cold tail); the security ↔ behavior cross-reference (→ SP5); authoring tests for confirmed behaviors (boundary unchanged — intent is confirmed, tests are owed); any change to `behavior.json`'s projected contents (proposed stay out).

## 8. Acceptance criteria

- [ ] `behavior-graph --surface --base <commit>` emits `affected_accepted`, `validate_candidates` (affected proposed via on-demand entry-closure + affected confirmed), and `recall_gaps`, read-only, degrading to empty buckets + a note on missing graph/base.
- [ ] A proposed behavior is surfaced iff its entry-closure intersects the change's blast radius; entry-less proposed are not surfaced (worklist-only).
- [ ] `recall_gaps` lists changed source files in no behavior's exercises and not any declared entry.
- [ ] wrap-up Phase 3.5 surfaces validate-candidates (bounded, skippable), re-infers each reviewed candidate against current code, and bumps `proposed → confirmed` on confirm — without changing the wrap-up exit code.
- [ ] wrap-up flags recall-gaps and offers to capture a behavior (skippable).
- [ ] `behavior.json`'s projected contents are unchanged (proposed remain unprojected); the SP1 accepted-only gate still governs blocking.
- [ ] Dogfooded on the testbed: editing a route surfaces its affected proposed behaviors, re-inference shows current-code intent, confirm bumps the state, and an uncovered touched file is flagged.

## 9. Open questions

None blocking. Re-inference quality (how good the refreshed description is) is inherently agent-judgment and validated by the dogfood, not a deterministic guarantee. The recall-gap over-flagging (transitively-covered files) is accepted as the safe direction; if the dogfood shows it is noisy, SP4's `status`/worklist view can dedupe or the definition can tighten to include proposed closures.
