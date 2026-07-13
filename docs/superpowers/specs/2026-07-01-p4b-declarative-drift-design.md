# P4b — Declarative-drift check (design)

**Status:** Draft for review
**Date:** 2026-07-01
**Parent design:** `docs/design/behavior-layer/00-vision.md` (§7 Direction A — code→behavior blast radius; §8 "Declarative-drift check"; §9 Phase 4 — Expansion).
**Track:** Phase 4 — Expansion, sub-project **P4b** (of P4a ADR support / P4b declarative-drift / P4c more adapters / P4d calibrated enforcement). Successor to P4a — consumes the ADR `related_code` hook it added.
**Depends on:** the code-graph blast-radius (`code-graph … --impact`, reused exactly as behavior-graph's Direction A does); the spec index (`search_specs.load_all_specs`, the `Spec.related_code`/`intentional_decisions` fields); the ADR gather (`adr.active_adrs`, `related_code`); the G2/G3 resolution machinery as the pattern for `drift.py`. Independent of P4c/P4d.

---

## 1. Goal

Guard **declarative intent** — the intent that has no test to fail — against the code drifting away from it. Behaviors are guarded by their tests (Direction A, shipped); a spec's `intentional_decisions`, a purely-declarative spec's prose, and an ADR's decision are **not**. P4b is the honest fallback the vision names:

> Declarative intent has no test to fail, so it is guarded at wrap-up by the same Tier-2 check — run **only for the declarative specs whose `related_code` intersects the change's blast radius** … This relies on the *existing* code-level blast radius from code-graph, not the behavior graph. … this check is the honest fallback for the genuinely untestable.

At wrap-up, for the code that changed, ask: **does the changed code contradict a declared intent that governs it?** Surface each finding as **resolve-to-proceed** (fix / amend / refute), same posture as G2/G3.

## 2. Scope — blast-radius-scoped, deliberately not always-global

**The comparison is scoped by `related_code ∩ blast-radius`, NOT always-global.** This is a conscious asymmetry with P4a's G3, and it is correct:

- **G3 is intent-vs-intent** with no code anchor and a tiny item count → always-global won (recall over precision; the LLM filters).
- **P4b is code-vs-intent, triggered by a code change.** Its natural scope is *the declared intent governing the code that changed* = `related_code ∩ blast-radius`. Always-global here would re-judge **every** declared decision against **every** change — the whole-repo re-derivation the vision explicitly rejects as too noisy to trust (§8: "Scoping by category / blast-radius — never a whole-repo re-derivation … keeps the check incremental and quiet enough to be trusted").

**Honest recall gap (accepted).** Because scope follows `related_code`:
- A declared decision or ADR with **no `related_code` is invisible** to this check (spec-template already warns: "A declarative spec with no `related_code` is invisible to that check").
- Drift introduced in code **not in, and not a dependent of,** a decision's `related_code` is not caught — the same recall gap Direction A has.
- Mitigations: keep `related_code` current; the **preferred** long-term path stays *promoting a testable decision into a guard scenario* (§4 promotion rule); and `drift gaps` (§5) makes the un-scopable set **visible** rather than silent.

## 3. Drift targets — all decisions + ADRs

For a changed set, a **drift target** is any of the following whose `related_code` intersects the blast radius:

- **A spec's `intentional_decisions`** — for *every* non-`deprecated` spec, not only purely-declarative ones. A behavioral spec's *declarative decisions* are equally untested and driftable; its behaviors are covered by the test run, its decisions are the gap P4b fills.
- **A purely-declarative spec** (no accepted behaviors) — its purpose/scope prose plus decisions.
- **An accepted ADR** — via its `related_code` (the P4a hook). `proposed`/`superseded`/`deprecated` ADRs are not authoritative and are excluded (mirrors `active_adrs`).

A target with empty `related_code` is **not** checked here — it surfaces in `drift gaps` (§5) instead.

## 4. The blast radius — reuse Direction A exactly

Identical mechanism to behavior-graph's Direction A (`behavior_graph.py` `_changed_files` → `_code_graph_impact` → intersect), with `related_code` substituted for behaviors' `exercises`:

1. `changed = git diff $BASE..HEAD --name-only` (project-relative).
2. `impact = code-graph --impact <changed>` — the union of changed files + their direct + transitive **dependents** (`graph_ops.get_impact`). A related_code file is "hit" if it *is* changed or *depends on* something changed — the correct direction (the decision's implementation was affected by the change).
3. `targets = { item : item.related_code ∩ impact ≠ ∅ }`, carrying the intersecting `hit_paths`.

**Degrade, never falsely-clean.** If code-graph is unavailable / the graph is missing, fall back to `impact = changed` (direct file intersection only) and **say so** in the output (`impact_source: "changed-only"`), exactly as behavior-graph degrades — a narrower blast radius, never a silent empty one.

## 5. `drift.py` — deterministic helpers (mirrors `principles.py`/`contradictions.py`)

- **`context --base $BASE [--project .] [--format json]`** → the per-change, blast-radius-scoped drift set:
  ```json
  {"base":"<sha>","impact_source":"code-graph","impact_count":12,
   "targets":[
     {"item":"SPEC-001","kind":"spec","related_code":[…],"hit_paths":["lib/webauthn.ts"],
      "decisions":["userVerification is 'preferred', not 'required'"],"file_path":"…/SPEC-001…md"},
     {"item":"ADR-001","kind":"adr","related_code":[…],"hit_paths":["prisma/schema.prisma"],
      "title":"Use PostgreSQL","body":"## Decision …"}],
   "warnings":[…]}
  ```
  Deterministic and testable (correct intersection, self-consistent, no-op when empty). The agent then reads each target's full text + the diff of its `hit_paths` and judges drift.
- **`resolve --item SPEC-NNN|ADR-NNN --verdict {refuted|amended|auto-cleared|superseded} --reason R --paths <files…> [--commit SHA] [--date YYYY-MM-DD]`** → append one line to `knowledge-base/drift-resolutions.jsonl`.
- **`prior --item X [--paths <files…>] [--format json]`** → active latest-wins per `(item, path)`, drops `superseded`, skips a malformed line with a warning. Same shape as G2's `active_prior` (explode over `paths`).
- **`gaps [--project .] [--format json]`** → **on-demand, NOT part of wrap-up**: the static list of declared decisions/ADRs that carry declared intent but **no `related_code`** — the honesty view of what drift can never see. Mirrors SP4's `--gaps`: a coverage signal, not a gate.

### Resolution record & retirement
`knowledge-base/drift-resolutions.jsonl`, keyed `(item, path)` (like G2's `(principle, path)`):
```json
{"date":"2026-07-01","item":"SPEC-001","verdict":"refuted",
 "paths":["lib/webauthn.ts"],"reason":"code sets userVerification 'preferred' exactly as declared; model misread the mount option","commit":"abc1234"}
```
- **Retirement is append-only** — a later `superseded` record (latest-wins per `(item, path)`), never a mutated field.
- **Verdicts match G2/G3.** `refuted` = false positive. `amended` = the declared intent was *consciously changed* to match new code (the spec decision / ADR was edited — a reviewable event, §5 of the vision). A plain **fix the code** needs no entry (git records it); an **amend** self-clears next run too, but is logged for the acknowledgment audit trail.

### Why the log exists (the resolve-to-proceed memory)
The check fires **every time a decision's `related_code` lands in a blast radius**, so a finding recurs across wrap-ups. The log's load-bearing job is to stop re-nagging an already-adjudicated **`refuted`** false positive on every overlapping change (the "rubber-stamp" erosion the vision warns about, §8 block-vs-warn), plus the acknowledgment audit trail, plus the priors the recurrence triage validates against. `fix`/`amend` self-clear via git; `refuted` does not — hence the log.

## 6. The judgment (agent) & triggers

**Trigger — wrap-up only.** P4b is code-triggered; there is no interactive entry (nothing in code changed at spec/ADR authoring time). It runs in **wrap-up Phase 3.5 step 7**, after G3's step 6, reusing the same `$BASE` computed in step 3. Ordering: deterministic facts (G1 + links + `adr verify` + accepted-behavior run) → G2 principle checkpoint (step 5) → G3 contradiction check (step 6) → **P4b declarative-drift (step 7)**.

**Process (agent judgment).** Run `drift.py context --base $BASE`. For each target, read the declared intent (the spec's decisions/prose, or the ADR body) + the **diff of its `hit_paths`**, and judge: *does the current code contradict this declared intent?* Each finding is **resolved to proceed**:
- **fix the code** — make the code honor the intent (no log; git records);
- **amend the intent** — the decision genuinely moved; edit the spec decision / ADR and log `amended` (the reviewable event);
- **refute** — false positive; log `refuted`.
"Ignore and push" is not a resolution; drift is resolved in the cycle that raised it (no standing backlog).

**LLM-first triage on recurrence** (identical to G2/G3): re-validate a prior resolution against the *current* code in the hit paths — still-valid → **auto-clear** (logged); the code moved so the prior no longer maps → **retire** (`superseded`); now a real drift → **escalate**. Guardrails: re-judge the current hunk against the *specific* prior reason (not the item id); bias-to-escalate on ambiguity; always logged; a finding with no prior always reaches the human.

**Posture:** model judgment → **advisory / procedural** (agent-honored, never a script hard-block, never auto-fail on model confidence). Fail-open on no code-graph / no targets / tooling error.

## 7. Error & edge handling

- **No changed files / empty blast radius** → `targets: []` → step 7 no-ops.
- **No code-graph / missing graph** → `impact_source: "changed-only"` (direct intersection), never a silent empty blast radius (§4).
- **Target with empty `related_code`** → excluded from `context`; visible in `gaps`.
- **`drift-resolutions.jsonl` malformed** → `prior`/`resolve` skip the bad line with a warning; never crash, never silently authorize an auto-clear.
- **No git** → `context` returns a graceful empty result; fail-open.
- **Ambiguous triage** → escalate (bias-to-surface).

## 8. Testing

- **`drift.py` unit tests** (stdlib `unittest`, parallel to `test_principles.py`): `context` returns exactly the targets whose `related_code` intersects a stubbed impact set, excludes non-intersecting and `deprecated`/`proposed` items, carries correct `hit_paths`, and no-ops on empty; `impact_source` flips to `changed-only` when the graph is absent; `resolve` appends a well-formed line **without rewriting priors**; `prior` is latest-wins per `(item, path)`, excludes `superseded`, skips a malformed line with a warning; `gaps` lists declared items with empty `related_code` and excludes those with `related_code`. The code-graph call is stubbed/injected so the intersection logic is tested deterministically without a real graph.
- **The drift JUDGMENT + triage is an agent procedure** → validated by the **testbed dogfood**, not a unit test: a code change that contradicts a spec decision → surfaces + resolve-to-proceed; refute → logged + not re-nagged on re-run (auto-clear); amend the decision → self-clears; an ADR-governed file drift → surfaces; a change touching no declared `related_code` → no-op; `gaps` lists the un-scopable decisions. Production webapp off-limits; testbed branch, restored after.

## 9. Scope

**In scope:** `drift.py` (`context` / `resolve` / `prior` / `gaps`); the blast-radius reuse (Direction-A chain over `related_code`); the append-only `drift-resolutions.jsonl` keyed `(item, path)`; wrap-up Phase 3.5 **step 7** (advisory, resolve-to-proceed, reuse `$BASE`, stage resolutions as artifacts); targets = all non-deprecated specs' `intentional_decisions` + purely-declarative prose + accepted ADRs, filtered by `related_code ∩ blast-radius`; the `gaps` honesty view.

**Out of scope:** **P4c** more language/runner adapters; **P4d** calibrated model-confidence hard-gating (evidence-gated); **promoting** a decision into a guard scenario (the preferred long-term path, but a human authoring act, not this check); any **always-global** drift mode (rejected — P4b is code-anchored); an interactive (non-wrap-up) trigger; behavioral drift (already covered by the accepted-behavior run / Direction A).

## 10. Acceptance criteria

- [ ] `drift.py context --base <sha>` returns exactly the specs' `intentional_decisions` + accepted ADRs whose `related_code` intersects the change's blast radius, with correct `hit_paths`, excludes `deprecated`/`proposed`/non-intersecting items, and no-ops when the blast radius is empty.
- [ ] Blast radius reuses the code-graph impact (changed + transitive dependents); with no graph, `impact_source` is `changed-only` and the result is never a silent empty set.
- [ ] `drift.py resolve` appends a well-formed JSONL line to `drift-resolutions.jsonl` without rewriting priors; `prior --item <id>` returns only **active** (non-`superseded`) latest records per `(item, path)`, and skips malformed lines with a warning.
- [ ] `drift.py gaps` lists declared decisions/ADRs with **no** `related_code` and excludes those that have it.
- [ ] The drift check runs as wrap-up Phase 3.5 **step 7** (after G3), is procedural/advisory (never a script hard-block, never auto-fail on model confidence), reuses `$BASE`, and does not complete wrap-up while a finding is unresolved.
- [ ] Resolution semantics: fix-the-code needs no log; `amend` edits the decision/ADR and logs; `refute` logs; a `refuted` finding is not re-nagged on a later overlapping change while code/intent are unchanged (auto-clear), and a genuine new drift escalates.
- [ ] `drift-resolutions.jsonl` stages with the artifacts commit.
- [ ] Dogfooded on the testbed: code-vs-decision drift surfaces/resolves; refute → logged + auto-cleared on re-run; amend → self-clears; ADR-governed drift surfaces; change touching no declared `related_code` → no-op; `gaps` lists the un-scopable set.

## 11. Open questions

None blocking. The blast-radius scoping is intrinsic to a code-anchored check (§2) and its recall gap is the vision's accepted honest limit, made visible by `gaps`. The drift judgment and auto-clear triage are model work — the same kind G2/G3 make — bounded by resolve-to-proceed with the human as calibration, and validated by the dogfood. The preferred escape from the recall gap remains **promoting a testable decision into a guard scenario**; P4b is the fallback for the genuinely untestable, not a replacement for it.
