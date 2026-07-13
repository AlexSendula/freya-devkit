# G3 — Tier-2 Contradiction Checks (design)

**Status:** Draft for review
**Date:** 2026-07-01
**Parent design:** `docs/design/behavior-layer/00-vision.md` (§5 authority hierarchy; §8 Consistency & conflict checking / Tier-2 + Block-vs-warn; §9 Phase 3 — Governance).
**Track:** Phase 3 — Governance, sub-project **G3** (of G1 intent records / G2 principle enforcement / G3 contradiction checks) — the final governance leaf.
**Depends on:** the spec index (`search_specs.load_all_specs`, the `Spec` dataclass's `category` + `intentional_decisions`); `principles.py list` (reused from G2); the wrap-up advisory phase (Phase 3.5) where G1 + G2 + validate-on-hit already live. Independent of G1's gate; structurally parallel to G2.

---

## 1. Goal

When a spec's intent is **created or changed**, judge whether it **contradicts a higher-authority intent**, and resolve the conflict by the authority order (vision §5). Satisfies vision §8:

> Contradictions between intents are caught by a two-tier, scoped check … Tier 2 — contradiction (LLM, advisory): on spec create-or-update and in batch at wrap-up, the *changed item only* is compared against same-domain, higher-authority items — initially **principles + feature-local decisions only**.

G3 is **intent × intent**, distinguishing it from its siblings: G1 (does an accepted test change have a record?) and G2 (does the *code diff* violate a principle?). G3 asks: does this *changed intent* conflict with *another recorded intent*?

## 2. Scope — what's in, and the ADR boundary

**Authority order** (vision §5): `principles.md` > `specs/` + `decisions/` > `reference/`.

**Comparison set** for a changed spec: `principles.md` (strictly higher authority) **+** the intentional decisions of *other* specs in the **same category** (same authority level — a consistency check). The changed spec itself is excluded.

**ADR-blind (deliberate, dependency-driven).** Cross-cutting **ADRs** live in `knowledge-base/decisions/`, which today is an **empty scaffold** — there is no ADR format, no create flow, no index. G3 therefore does **not** compare against ADRs: checking against a structurally-empty set would fake coverage. G3 is built **ADR-ready** — the same check extends to ADRs once the **ADR-capture sub-project (vision Phase 4)** ships. This is order, not deprioritization; ADR support was always Phase 4.

**Declarative-drift is *not* G3.** "Code drifted from a declared spec" (e.g. spec says Postgres, code uses Mongo) is a *code-vs-intent* check the vision files under **Phase 4 Expansion** — out of scope here.

## 3. The check

**Inputs, assembled by `contradictions.py context --spec <SPEC-ID> --project .`:**
- **Principles** — via `principles.py list` (reused from G2).
- **Same-category peer decisions** — the `intentional_decisions` of other specs sharing the changed spec's `category`, gathered from the spec index; the changed spec is excluded.

`context` returns `{"spec": "SPEC-005", "category": "auth", "principles": [{"n","title","text"}…], "peers": [{"spec_id","decisions":[…]}…]}` — deterministic and testable (correct category, self excluded, principles included).

**Process (agent judgment).** The agent reads the changed spec's intent (purpose, scope, decisions) and, for each item in the comparison set, asks *does this changed intent contradict it?* — producing findings that name the **conflicting item** (`principle:2` or `SPEC-003`) and **why**. Two resolution semantics by what's contradicted:
- **vs a principle** (higher authority): the principle wins by the authority order → default resolution is **fix the spec** (or consciously **amend the principle**).
- **vs a peer spec's decision** (same authority): no automatic winner → a **consistency conflict** to reconcile — fix one side, or refute if they don't truly conflict.

**Scope:** category only; **ADR-blind** (§2); a spec with no decisions is still checked (its purpose/scope prose can contradict a principle).

## 4. Triggers & gate posture

Two entry points to the *same* check (vision §8: "on spec create-or-update and in batch at wrap-up"):

- **Interactive — spec-manager `create` / `update`.** Right after a spec is authored or changed, run the check on *that* spec and resolve any contradiction then — the cheapest place to catch a conflict, before it's even committed.
- **Batched — wrap-up.** Over the specs changed this cycle (the `knowledge-base/specs/**` files in the change-set), run the check as a **resolve-to-proceed** step in Phase 3.5 — **step 6, immediately after G2's principle checkpoint (step 5)** — so the order is: deterministic facts (G1 + links + accepted-behavior run) → principle judgment (G2) → intent-coherence judgment (G3). This is the safety net for specs changed outside the interactive flow.

**Posture — identical to G2:** model judgment, so it is **advisory / procedural** (agent-honored, never a script hard-block, never auto-fail on model confidence). Each finding is **resolved to proceed** — **fix** (edit the spec, or amend the principle/peer), **refute** (false positive), or **reconcile** (peer conflict). "Ignore and push" is not a resolution; contradictions are resolved in the cycle that raised them (**no standing backlog**). Fail-open on no principles / no peers / tooling error.

## 5. Resolution machinery

Its own append-only `knowledge-base/contradiction-resolutions.jsonl`, records keyed by `(spec, against)` where `against` is the conflicting item (`principle:2` or `SPEC-003`):

```json
{"date":"2026-07-01","spec":"SPEC-005","against":"principle:2","verdict":"refuted","reason":"the spec stores a hashed token reference, not a raw secret in source","commit":"abc1234"}
```

`contradictions.py` mirrors G2's proven mechanics — **its own module, keyed on `(spec, against)`** (we deliberately did *not* extract a shared module, to avoid churning G2's shipped code):
- `resolve --spec SPEC-005 --against principle:2 --verdict {refuted|amended|auto-cleared|superseded} --reason "…" [--commit SHA] [--date YYYY-MM-DD]` — append one JSONL line.
- `prior --spec SPEC-005 [--against X] [--format json]` — latest-active per `(spec, against)`, drops `superseded`, de-dupes, skips a malformed line with a warning.
- **Verdicts match G2.** A **fix** (editing the spec, or editing a peer to reconcile) needs no entry — git is the record. **Amend** = the *higher-authority* item (a principle) was consciously changed.
- **Retirement is append-only:** a stale resolution is retired by a later `superseded` record (latest-wins per `(spec, against)`), never a mutated field — the same realization used in G2.
- **Same LLM-first triage on recurrence:** re-validate a prior resolution against the *current spec text* — still-valid → **auto-clear** (logged); the spec was rewritten so the prior no longer maps → **retire** (`superseded`); now a real contradiction → **escalate**. Same guardrails: re-judge the current intent against the *specific* prior reason (not the spec id); bias-to-escalate on ambiguity; always logged (`verdict: auto-cleared`); a finding with no prior always reaches the human.

**Staging:** `contradiction-resolutions.jsonl` + any `principles.md`/spec amendment → **artifacts** (commit 2).

## 6. Error & edge handling

- **Empty comparison set** (a spec alone in its category, no principles) → `context` returns empty → check **no-ops**.
- **Spec with no decisions** → still checked (purpose/scope prose can contradict a principle).
- **`contradiction-resolutions.jsonl` malformed / partially corrupt** → `prior`/`resolve` skip unparseable lines with a warning; never crash, never silently authorize an auto-clear.
- **Spec not found / no git** → `context` returns a graceful empty result; **fail-open** — never a false "clean," never a block.
- **Ambiguous triage** → escalate to human (bias-to-surface), never auto-clear.

## 7. Testing

- **`contradictions.py` unit tests** (stdlib `unittest`, parallel to `principles.py`): `context` returns principles + same-category peer decisions, **excludes the changed spec itself**, empty when alone / no principles; `resolve` appends a well-formed line **without rewriting prior lines**; `prior` is **latest-wins per `(spec, against)`**, excludes `superseded`, de-dupes a multi-`against` record, skips a malformed line with a warning.
- **The judgment + LLM triage is an agent procedure** → validated by the **testbed dogfood**, not a unit test: a spec decision that contradicts a principle → surfaces + resolve-to-proceed; refute → logged; re-run unchanged → **auto-cleared** (no re-nag); rewrite the spec → **retired**; a *new* contradiction → **escalates**; two same-category specs with conflicting decisions → surfaces as a **peer reconcile**. Production webapp off-limits.

## 8. Scope

**In scope:** `contradictions.py` (`context` / `resolve` / `prior`); the contradiction check as an agent procedure at spec-manager `create`/`update` **and** wrap-up Phase 3.5 **step 6**; the append-only `contradiction-resolutions.jsonl`; category scoping; principle + same-category-peer comparison with authority-order / reconcile semantics.

**Out of scope:** **ADR-awareness** — cross-cutting ADRs, pending the Phase-4 ADR-capture sub-project (G3 is ADR-ready, not ADR-aware); **declarative-drift** / code-vs-declared-intent (Phase 4 Expansion); the *auto-fail hard gate* on model confidence (vision defers until the false-positive rate is measured); extracting a shared resolution module (we chose separate/same-pattern to avoid churning G2); wiring the third-party superpowers skills.

## 9. Acceptance criteria

- [ ] `contradictions.py context --spec <id>` returns `principles` + same-category `peers`' decisions, **excludes the changed spec**, and is empty (no-op) when the spec is alone / there are no principles.
- [ ] `contradictions.py resolve` appends a well-formed JSONL record to `contradiction-resolutions.jsonl` without rewriting existing lines; `prior --spec <id>` returns only **active** (non-`superseded`) latest records per `(spec, against)`, de-dupes, and skips malformed lines with a warning.
- [ ] The contradiction check runs interactively at spec-manager `create`/`update` and as wrap-up Phase 3.5 **step 6** (after G2), is procedural/advisory (never a script hard-block, never auto-fail on model confidence), and does not complete wrap-up while a finding is unresolved.
- [ ] Resolution respects the authority order: a contradiction **vs a principle** resolves by fixing the spec (or amending the principle); **vs a peer** resolves by reconcile/refute. Findings name the conflicting item (`principle:N` / `SPEC-NNN`).
- [ ] Auto-clear only fires when the current spec intent still *is* what the prior reason described; a *new* contradiction escalates; every auto-clear is logged as `verdict: auto-cleared`.
- [ ] `contradiction-resolutions.jsonl` + any amendment stage with the artifacts commit; the check is **ADR-blind** (no comparison against `decisions/`) and does not attempt declarative-drift.
- [ ] Dogfooded on the testbed: spec-vs-principle contradiction surfaces/resolves; refute → logged; re-run unchanged → auto-cleared; spec rewrite → retired; new contradiction → escalated; peer conflict → surfaced as reconcile.

## 10. Open questions

None blocking. The contradiction judgment (and the auto-clear triage) is inherently model judgment — the same kind G2 and the security cross-reference already make — validated by the dogfood, not a deterministic guarantee. The safety posture (resolve-to-proceed with the human as calibration; auto-clear fenced by current-intent-vs-specific-reason + bias-to-escalate + always-logged; new contradictions always reach the human) bounds a misjudgment to a surfaced false positive (friction) or a logged, auditable auto-clear — never a silently-shipped contradiction. **ADR-awareness** is the explicit successor: when the Phase-4 ADR machinery ships, `context` gains an ADR gather and the same check covers cross-cutting decisions.
