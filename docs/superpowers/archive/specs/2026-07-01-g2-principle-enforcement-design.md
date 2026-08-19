# G2 — Principle Enforcement (design)

**Status:** Draft for review
**Date:** 2026-07-01
**Parent design:** `docs/design/behavior-layer/00-vision.md` (§8 Principle enforcement + Block-vs-warn; §9 Phase 3 — Governance).
**Track:** Phase 3 — Governance, sub-project **G2** (of G1 intent records / G2 principle enforcement / G3 contradiction checks).
**Depends on:** `knowledge-base/principles.md` (scaffolded by spec-manager `init`); the wrap-up advisory phase (Phase 3.5) where G1 and validate-on-hit already live; the incremental change-set base wrap-up already uses. Independent of G1's gate and of G3.

---

## 1. Goal

Make `principles.md` — the project's constitution — actually enforced, not a passive file. Today its own template *claims* two enforcement mechanisms (soft injection + a checkpoint) but **nothing implements either**. G2 delivers both (vision §8):

- **Soft (context injection):** surface `principles.md` into the working context of the design-time and wrap-up flows we own, so work happens "with the constitution in view."
- **Checkpoint:** at wrap-up, diff the change against the principles and raise a finding on violation — a **model judgment**, so per block-vs-warn it is **acknowledged/resolved, never a hard-block on model confidence**.

G2 is distinct from **G3**: G2 compares the *code change vs. principles*; G3 compares *intent vs. same-domain higher-authority intent*.

## 2. The core stance — resolve-to-proceed, human is the calibration

A "violation" hides two separable things: **(1) is there really a violation?** (the model's judgment — fallible) and **(2) given a real one, what should happen?** (it must be adhered to). The vision's "don't hard-block on model confidence" addresses **(1)** only: an uncalibrated model that can hard-fail wrap-up forces an override on every false positive, which trains reflexive bypass — and then real violations get waved through too. It is *not* a license to let violations slide.

So G2's checkpoint is a **resolve-to-proceed gate**: wrap-up does not complete while a principle finding is unresolved, and "ignore and push" is **not** a resolution. The three resolutions are:

| Resolution | When | Recorded as |
|---|---|---|
| **Fix** | the principle really was violated | the code diff + commit (git is the record — no log entry) |
| **Refute** | the model flagged a false positive | an entry in the resolution index (§4) |
| **Amend** | the principle itself should change | the amendment in `principles.md` (+ dated change-history line) **and** a log entry |

**The human running wrap-up is the calibration** — the model *surfaces*, the person *adjudicates*. Refuting a false positive is a first-class, legitimate resolution, so there is no reflexive-bypass pressure. It stays high-signal because principles are deliberately **few and sharp** (a handful of rules), so a flag is rare and meaningful.

**Enforcement kind.** G1's Phase-3.5 gates are *script exit codes* (deterministic facts). G2's checkpoint is *model judgment*, so its gate is **procedure-enforced by the wrap-up agent** (the SKILL.md instructs it not to complete while a finding is unresolved), not a script exit. This is the honest shape for a judgment check, and it matches the vision's "requires an explicit acknowledgement" (as opposed to the *auto-fail hard gate*, which the vision defers until the false-positive rate is measured).

**No standing backlog.** Every finding is resolved within the wrap-up that raised it; principle violations are never carried forward as open debt (unlike security findings). `status`/`BACKLOG.md` gain **no** "open principle findings" bucket.

## 3. The checkpoint check

**Inputs:** `knowledge-base/principles.md` (the short numbered rule list) and the change-set diff being wrapped (`git diff <BASE>` — **the same `BASE` the Phase 3.5 validate-on-hit surfacing already computes** in wrap-up, so there is one unambiguous change-set for the whole advisory phase; the code changing *this* cycle, not the whole repo).

**Process (agent procedure).** The agent reads the principles and the diff and, for each principle, asks *"does anything in this diff violate this rule?"*, emitting candidate findings — each naming the **principle**, the **file/hunk**, and **why** — or reporting clean. Because principles are project-wide by definition, *all* principles apply to any change: the whole (short) list is checked against the diff, no blast-radius scoping needed (that is G3's concern, not G2's).

**Deterministic helper** (`principles.py list`, in spec-manager): parse and print the numbered principles from `principles.md`. It does **not** judge — judgment is inherently the model's job. On a missing/empty `principles.md` it prints nothing and exits 0, so the checkpoint **no-ops** (a project with no constitution has nothing to enforce).

## 4. The resolution index & LLM-first triage

Non-fix resolutions must be durable *and* queryable — a prose-only log is write-once-read-never, and the checkpoint needs to consult past resolutions so it does not re-nag about the same false positive every time a file changes.

### 4.1 The index

`knowledge-base/principle-resolutions.jsonl` — append-only, one JSON record per line:

```json
{"date":"2026-07-01","principle":1,"verdict":"refuted","paths":["app/api/health/route.ts"],"reason":"intentional public health check","ref":"SPEC-007","commit":"abc1234","status":"active"}
```

- `verdict`: `refuted` (human false-positive call) · `amended` (principle changed) · `auto-cleared` (LLM re-applied a prior refutation — see 4.2) · `superseded` (retires a now-stale record).
- `status`: `active` | `superseded`. **Append-only** — retiring a resolution appends a `superseded` record (or a superseding entry references the retired one); records are never erased, so the audit trail survives.
- Keyed conceptually by **(principle, path)** — the natural link, since a finding is always "principle N, about file F."

**Two more `principles.py` subcommands:**
- `resolve --principle N --verdict refuted|amended|auto-cleared|superseded --reason "…" --paths <files> [--ref SPEC-NNN] [--commit SHA]` — append a well-formed record (deterministic, testable).
- `prior --paths <changed files> [--principle N]` — return the **active** resolutions touching those files (excludes `superseded`); empty when none; skips a malformed line with a warning rather than crashing.

### 4.2 LLM-first triage (the recurrence handler)

When a finding has a prior resolution (from `prior`), the LLM **re-validates the prior against the current diff** — a fresh judgment, not a stale key match — landing in one of three:

1. **Still clearly valid** — the flagged code is *the same intentional thing the prior reason described*, materially unchanged → **LLM auto-clears** the finding and appends an `auto-cleared` record. No human needed.
2. **Stale** — the code changed enough that the prior no longer maps → **retire** it (append `superseded`) and evaluate the finding fresh; if fresh-clean, done; if a violation, escalate.
3. **Now a real violation** — the prior reason no longer excuses what is there → **escalate to the human**.

Findings with **no prior resolution always go to the human** — the LLM cannot auto-clear what was never adjudicated.

**Auto-clear guardrails** (auto-clear is the one place a real violation could be hidden, so it is fenced):
- **Re-judge the current hunk against the *specific* prior reason — not the file.** If `health/route.ts` was refuted as "intentional public health check" and a later diff adds a *new* unauthenticated endpoint returning user data to that same file, the prior reason does not cover the new code → **escalate**, do not auto-clear.
- **Bias to escalate on any ambiguity** — auto-clear only the clean, unchanged-intent case.
- **Auto-clearances are logged, never silent** (`verdict: auto-cleared`), so a reviewer sees what the machine waved through vs. what a person did.
- **New violations (no prior) always reach the human** — the safety floor.

## 5. Integration & data flow

**Wrap-up checkpoint phase.** In wrap-up's advisory phase (Phase 3.5), **after** the deterministic hard-blocks (link integrity, the G1 intent gate, the accepted-behavior run) — facts settled first, then judgment — the agent:
1. `principles.py list` → load the constitution (this *is* soft injection at wrap-up).
2. Judge the change diff (against the Phase 3.5 `BASE`, §3) × principles → candidate findings.
3. For each finding, `principles.py prior --paths <changed files>` → triage per §4.2 (auto-clear / retire+refresh / escalate).
4. Resolve each escalated finding with the human: **fix** (change code, re-run), **refute** (`resolve --verdict refuted`), or **amend** (`resolve --verdict amended`, edit `principles.md`).
5. Wrap-up completes only when no finding remains unresolved.

**Soft injection** — surface the constitution where design happens, in the flows we own:
- **wrap-up:** step 1 above.
- **spec-manager `create` / `scan`:** load and show `principles.md` (via `principles.py list`) at the top of intent authoring, so new specs/behaviors are drafted against the constitution.
- **Out of our reach (noted, not built):** the third-party superpowers `brainstorming` / `writing-plans` skills — the template's "brainstorming/planning" claim is honored for *our* design-time surface (spec-manager); wiring the superpowers skills is a separate user-level convention.

**Code-review touchpoint.** The vision names "wrap-up *and* code-review." We own the enforced wrap-up checkpoint; for code review the buildable piece is a one-line pointer in the requesting-code-review rubric — "check the diff against `knowledge-base/principles.md`" — the same judgment, applied by the reviewer. No separate enforcement engine.

**Staging.** `principle-resolutions.jsonl` and any `principles.md` amendment are `knowledge-base/` **artifacts** → commit 2. A code *fix* prompted by a finding rides the normal code commit (commit 1).

## 6. Error & edge handling

- **No `principles.md`** → checkpoint no-ops (nothing to enforce); `list` prints nothing, exits 0.
- **No changes / no git / detached HEAD** → diff can't be gathered → no-op; never silently claims "clean" — it reports it could not run. **Fail-open** (advisory phase never blocks on infra failure).
- **Model can't run the judgment** → agent notes it and proceeds; the checkpoint is advisory by nature, not a deterministic gate.
- **`principle-resolutions.jsonl` malformed / partially corrupt** → `prior`/`resolve` skip unparseable lines with a warning; a broken line never crashes the run and never silently authorizes an auto-clear.
- **Ambiguous triage** → escalate to human (bias-to-surface), never auto-clear.

## 7. Testing

- **`principles.py` unit tests** (stdlib `unittest`): `list` parses the numbered rules from a sample `principles.md`; empty/absent → empty output, exit 0. `resolve` appends a well-formed JSONL record **without rewriting prior lines** (append-only). `prior --paths` returns **active** matches for the given files/principle, **excludes `superseded`**, empty when none, and **skips a malformed line** robustly. A `superseded` record removes an entry from `prior` while leaving it in the file.
- **The checkpoint judgment + LLM triage is an agent procedure** → validated by the **testbed dogfood**, not a unit test: introduce a sharp principle; make a change that violates it → surfaces + resolve-to-proceed; refute a false positive → logged; re-run unchanged → **auto-cleared** (no re-nag); change the code so the prior no longer maps → **retired + re-evaluated**; add a *new* violation to a previously-refuted file → **escalates, not auto-cleared** (the key guardrail). Production webapp off-limits.

## 8. Scope

**In scope:** `principles.py` (`list` / `resolve` / `prior`, incl. supersede); the wrap-up checkpoint phase (agent procedure: judge → LLM-triage against `prior` → auto-clear/retire/escalate → resolve-to-proceed); the append-only `principle-resolutions.jsonl` index; soft injection into wrap-up + spec-manager `create`/`scan`; a one-line principles pointer in the requesting-code-review rubric.

**Out of scope:** G3 (intent-vs-intent contradiction checks); promoting a principle to a guard scenario (optional, deferred — vision §4/§8); the *auto-fail hard gate* on model confidence (vision defers it until the false-positive rate is measured on a real project); wiring the third-party superpowers `brainstorming`/`writing-plans`; ADR-awareness.

## 9. Acceptance criteria

- [ ] `principles.py list` prints the numbered principles from `principles.md`; empty/absent → empty output, exit 0 (checkpoint no-ops).
- [ ] `principles.py resolve` appends a well-formed JSONL record to `principle-resolutions.jsonl` without rewriting existing lines; `prior --paths` returns only **active** matching records (excludes `superseded`), is empty when none, and skips malformed lines with a warning.
- [ ] The wrap-up checkpoint phase runs **after** the deterministic hard-blocks, loads principles, judges the change diff, triages each finding against `prior` (auto-clear / retire+refresh / escalate), and does not complete wrap-up while a finding is unresolved.
- [ ] Auto-clear only fires when the flagged current code still *is* the intentional thing the prior reason described; a new/different violation in a previously-refuted file escalates; every auto-clear is logged as `verdict: auto-cleared`.
- [ ] `principles.md` is surfaced (soft injection) in spec-manager `create`/`scan` and at the wrap-up checkpoint; the requesting-code-review rubric carries the principles pointer.
- [ ] `principle-resolutions.jsonl` + any `principles.md` amendment stage with the artifacts commit; a code fix rides the code commit.
- [ ] Dogfooded on the testbed: violate → surface/resolve; refute → logged; re-run unchanged → auto-cleared; code drift → retired+refreshed; new violation in a refuted file → escalated.

## 10. Open questions

None blocking. The checkpoint's judgment (and the auto-clear triage) is inherently model judgment — the same kind `scan` and the security cross-reference already make — validated by the dogfood, not a deterministic guarantee. The safety posture (resolve-to-proceed with the human as calibration; auto-clear fenced by current-hunk-vs-specific-reason + bias-to-escalate + always-logged; new violations always reach the human) bounds the blast radius of a misjudgment to, at worst, a surfaced false positive (friction) or a logged, auditable auto-clear — never a silently-pushed violation with no record.
