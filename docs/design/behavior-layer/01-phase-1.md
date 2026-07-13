# Phase 1 — Traceability MVP

**Status:** Draft for review
**Date:** 2026-06-24
**Depends on:** `00-vision.md`. The separate Phase 0 proof was deliberately dropped (vision §9): this schema is validated with unit tests and throwaway fixtures, and by dogfooding on a real project, as it is built — the feature is project-agnostic. Some choices are provisional and expected to change in contact with real use.
**Unlocks:** Phase 2 (impact indexing) and Phase 3 (governance). No behavior graph and no model-based checks in this phase.

---

## 1. Goal

After Phase 1, a feature spec can **declare its intended behavior as first-class `Behavior` records**, each with a **stable id**, a **lifecycle state**, and an **adapter** linking it to an executable test — authored as Gherkin *or* linked to an existing native test. Links are checked deterministically, and *accepted* behaviors are run at wrap-up, where **only deterministic failures block**. Phase 1 runs against the `knowledge-base/` layout established by the separate, already-shipped migration (vision §9).

This phase builds the behavior loop as a reusable capability across two adapters, validated by dogfooding on the testbed. It is about **identity, lifecycle, links, and integrity** — not the graph (Phase 2) and not enforcement intelligence (Phase 3).

## 2. Scope

**In scope**
- The `Behavior` entity: stable `BEH-NNN` id + the `proposed/accepted/quarantined/deprecated` lifecycle.
- Extended spec format (frontmatter + sections) carrying behaviors and their links.
- **Two adapters:** Gherkin (`.feature` + steps) and **one** native test framework (whichever the target project uses, as detected at runtime).
- Spec ↔ behavior ↔ test linking (`@SPEC-NNN` + `@BEH-NNN` tags; adapter + locator).
- Intent-classification workflow in spec-manager (`create`, `scan`, `update`) producing **proposed** candidates for review — never authoritative artifacts.
- Deterministic integrity checks (Tier 1 from vision §8).
- Run *accepted* behaviors at wrap-up; **block only deterministic failures**.
- Two-commit classification update.
- **Substrate prerequisites** (§7) — strict, schema-validated frontmatter parsing must land before the schema is extended.

**Out of scope (later phases / decoupled)**
- `knowledge-base/` directory migration — **decoupled, standalone PR** (vision §9), shipped separately ahead of this phase (not part of it).
- The behavior graph / `behavior.json` / blast-radius and coverage fingerprints (Phase 2).
- Model-based Tier-2 contradiction checks, principle enforcement, declarative-drift (Phase 3+).
- ADR capture machinery and ADR-aware checks (Phase 4). The shipped migration created `decisions/` with a README so the empty dir survives Git; the ADR machinery itself stays absent until Phase 4.
- Foreign-tooling ingest (e.g. migrating off spec-kit) — its own later concern.

## 3. The `Behavior` entity & lifecycle

A behavior is the first-class unit, independent of any test format.

```yaml
behavior_id: BEH-007          # stable across renames
spec_id: SPEC-012
title: Successful passkey login
state: accepted               # proposed | accepted | quarantined | deprecated
adapter: cucumber             # cucumber | jest | playwright | ... | manual
locator: features/auth/passkey-login.feature#successful-passkey-login
```

Lifecycle states (vision §3.1):

| State | Meaning | Authoritative? |
|---|---|---|
| `proposed` | A candidate (e.g. from `scan` inference). Intent not yet approved by a human. | No |
| `accepted` | Approved as intended behavior; its test is the safety net. | **Yes** |
| `quarantined` | Test failing for infra reasons (flaky / fixture / env), temporarily out of the authoritative set. | No |
| `deprecated` | Behavior intentionally retired. | No |

`state` replaces the earlier `behavior_status` (`none/scaffolded/authored`), which conflated "text exists" with "approved as intent." **Only `accepted` behaviors block on failure.**

## 4. Spec format

### 4.1 Frontmatter (additions in **bold**)

```yaml
---
id: SPEC-012
title: Passkey Login
category: auth            # auth | api | data | features | infra | integration | ui
tags: [authentication, security, webauthn]
status: implemented      # draft | in-progress | implemented | deprecated
certainty: 90
created: 2026-06-24
updated: 2026-06-24
related_code:
  - src/lib/auth/passkeys.ts
intentional_decisions:
  - "No password fallback (phishing vector)"
behaviors:                                      # NEW — first-class behavior records
  - behavior_id: BEH-007
    title: Successful passkey login
    state: accepted
    adapter: cucumber
    locator: features/auth/passkey-login.feature#successful-passkey-login
---
```

- `behaviors` — the list of `Behavior` records this spec owns. Empty/absent ⇒ the spec is purely declarative (allowed).
- `related_code` — **required on declarative specs too**, not just behavioral ones: it is the key the later declarative-drift check (Phase 3+) uses to decide whether a diff's blast radius can affect this decision. A declarative spec with no `related_code` is invisible to that check.
- The old `feature_files` / `behavior_status` fields are replaced by the `behaviors` list.

### 4.2 Body sections

Keep the existing sections (What / Why / Intentional Design Decisions / Related Specs / Change History), honoring the **ownership split** (vision §5): the spec's "What" states *purpose, scope, and bounds* — it does **not** restate the step-by-step behavior the test owns. **Change the acceptance section:**

- Remove the inert acceptance-criteria checkbox list.
- Replace with a short **Behavior** section that *links* to each behavior's test (no copied scenario text — single source of truth):

```markdown
## Behavior

| Behavior | State | Verified by |
|---|---|---|
| BEH-007 Successful passkey login | accepted | `features/auth/passkey-login.feature` (cucumber) |

Declarative decisions that are not executable are recorded under **Intentional Design Decisions** below.
```

### 4.3 Adapters

Two adapters in Phase 1:

- **Gherkin (`cucumber` / `behave` / `pytest-bdd`):** the recommended default for *new, user-visible* behavior. When a behavior is created this way, spec-manager writes a **skeleton `.feature`** (it does **not** write real scenarios — that is human/forward-design work):

  ```gherkin
  @SPEC-012 @BEH-007
  Scenario: Successful passkey login
    # Intent and rationale live in knowledge-base/specs/auth/SPEC-012-passkey-login.md
    # TODO(scaffold): replace with real steps.
    Given <initial state>
    When <action>
    Then <expected outcome>
  ```

  The `@SPEC-NNN` and `@BEH-NNN` tags are **required** — they are the reverse links. Step definitions are **not** created in Phase 1.

- **One native adapter (the Phase-0-validated one, e.g. `jest`):** links an **existing** test by locator — no rewrite, no `.feature`, no steps. This is what keeps adoption cheap for projects that already have tests.

## 5. Intent classification → a review queue (not staged scaffolds)

When spec-manager creates or scans, each candidate piece of intent is classified:

```
For each intended behavior / decision:
  Is it observable behavior expressible as a test?
    ├─ Yes → propose a Behavior (state: proposed)
    │         ├─ new user-visible → recommend a Gherkin scaffold
    │         └─ already covered by a native test → recommend linking it
    └─ No  → declarative
              ├─ cheaply guarded by a (often negative) scenario? → recommend promotion
              └─ Feature-local → Intentional Design Decisions (inline)
                 Cross-cutting → note for decisions/ (ADR, deferred)
```

- **`scan` produces a review queue of `proposed` candidates, not files committed into the code tree.** Intent cannot be reliably inferred from code — code reveals *candidate* behavior at best, and auto-generating authoritative-looking scaffolds from the implementation reintroduces the very "tests mirror code" problem the layer exists to fix.
- A candidate becomes `accepted` (and only then does its scaffold/link enter the code tree) when a **human accepts it**.
- Classification is **interactive for low certainty** (reuse spec-manager's certainty thresholds and one-question-at-a-time `review` style). Promotion to a guard scenario is **recommended, not forced.**

## 6. Linking & integrity (deterministic only)

Tier-1 checks from vision §8 (no LLM, no execution-based contradiction analysis in Phase 1):

- **Forward link:** spec `behaviors[].locator` → an existing test location.
- **Reverse link:** `@SPEC-NNN` + `@BEH-NNN` tags on the Gherkin `Feature`/`Scenario` (for native adapters, the locator is the link).
- **Integrity checks:**
  - every `locator` resolves to a real test;
  - every `@SPEC`/`@BEH` tag points at an existing spec/behavior, and ids round-trip;
  - `state` is consistent (e.g. `accepted` but the scaffold still contains the `TODO(scaffold)` marker ⇒ **error**; behavior id reused ⇒ error).

> Model-based contradiction checking (comparing an intent against higher-authority principles, vision §8 Tier 2) is **Phase 3** — it rides on the wrap-up integration and must stay ADR-blind until the ADR phase. Phase 1 ships only the deterministic checks above and captures the data later checks need.

## 7. Substrate prerequisites (must land before the schema extends)

The new schema is more structured metadata, and the model will *depend* on these fields — so the deterministic substrate has to be reliable first:

- **Replace the hand-rolled frontmatter parser with a strict, schema-validated frontmatter parser that fails loud** — a *scoped* parser for our exact (versioned, model-authored) grammar, not a full YAML engine, since the plugin is stdlib-only / zero-install. The current parser silently discards inline-array fields (e.g. `tags: [a, b]` is parsed as a string then dropped) — which would silently break `tags` and any inline list in the new schema. The replacement raises a clear error on anything outside the grammar instead of dropping it.
- Add schema validation, version the schema, and make unknown fields round-trip safely (test malformed/partial frontmatter).
- **Runner awareness:** detect the project's test tooling **on demand, statelessly** (extend `detect_project.py`); do not invent a persisted tracking file with no consumer. Phase 2 re-runs detection when it needs it.

## 8. Two-commit classification

| Artifact | Commit |
|---|---|
| `proposed` behaviors / unaccepted scaffolds | **Artifacts** (commit 2) — they are intent under review, not yet code |
| `accepted` behaviors' tests (`.feature` + steps, or the native test) | **Code** (commit 1) — executable, real |
| `SPEC-*.md`, `principles.md` | **Artifacts** (commit 2) |

A scaffold's commit class follows its **lifecycle state**, not its location: a `proposed`/`TODO` scaffold is an artifact even though it sits in the code tree; it joins the code commit only once `accepted` and executable. `wrap-up` is updated to stage by this rule (full wrap-up/run integration is later; Phase 1 only needs the staging classification correct).

## 9. Acceptance criteria for Phase 1

- [ ] Schema exercised on a real project (dogfooding); provisional choices noted for later correction.
- [ ] `Behavior` entity exists with stable `BEH-NNN` ids and the `proposed/accepted/quarantined/deprecated` lifecycle.
- [ ] Spec frontmatter carries the `behaviors` list; the spec template and `references/` are updated; declarative specs capture `related_code`.
- [ ] **Strict, schema-validated frontmatter parsing** (scoped, fail-loud) is in place; inline-array fields round-trip correctly.
- [ ] Two adapters work: a Gherkin scaffold **and** linking one existing native test.
- [ ] `spec-manager create` can classify intent and produce a declarative-only spec **or** a spec with proposed/accepted behaviors.
- [ ] `spec-manager scan` infers intent into a **review queue of `proposed` candidates**, with certainty scores, and never marks them `accepted`.
- [ ] `spec-manager verify` performs the deterministic link-integrity checks in §6.
- [ ] Project test tooling is detected **on demand** (no orphan tracking file).
- [ ] At wrap-up, *accepted* behaviors run and **only deterministic failures block**; two-commit staging follows lifecycle state.
- [ ] No `behavior.json`, no coverage fingerprints, no model-based checks (those are Phases 2–3).

## 10. Resolved decisions

1. **Migration ergonomics:** the `knowledge-base/` migration was a **decoupled, standalone, idempotent** change — shipped ahead of this phase, **not** part of it (vision §9).
2. **`principles.md` starter content:** a minimal template ships with the migration (`spec-manager/references/principles-template.md`, written by `spec-manager init`); generation from a scan deferred.
3. **`scan` output:** a **review queue of `proposed` candidates**, never staged scaffolds.
4. **Lifecycle vs. status:** `state` (lifecycle) replaces `behavior_status`; only `accepted` blocks.
5. **Category set** (spec-manager vs code-graph categories): reconcile in Phase 2, when impact indexing joins them.
