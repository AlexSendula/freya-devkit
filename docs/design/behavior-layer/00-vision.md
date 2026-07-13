# Behavior Layer — Vision

**Status:** Draft for review
**Date:** 2026-06-24
**Scope:** Whole-initiative vision. Implementation detail for the first build phase lives in `01-phase-1.md`. Each later phase gets its own numbered design doc, written just-in-time before that phase is executed.

---

## 1. Summary

Make **intended behavior** a first-class, executable, blast-radius-aware artifact in the freya-devkit ecosystem.

Today the ecosystem is a strong *reverse-sync engine* — after code changes it keeps a dependency graph, docs, specs, and security findings in sync. What it lacks is a way to capture **what the system is supposed to do** in a form that is (a) executable, so unintended behavior changes are caught; (b) intent-driven, so tests track behavior rather than whatever the code happens to do; and (c) visible at design time, so behavior changes are decided on purpose rather than discovered after the fact.

This initiative adds that layer by making **behavior** a first-class entity — a stable, intent-bearing record linked to an executable test. The test is authored as **Gherkin** where Given/When/Then adds intent-clarity, or linked to an existing **native test** (jest, pytest, playwright, …) where one already covers the behavior; Gherkin is the recommended default, not a requirement. It extends the existing code-graph into a **behavior graph** so changes can be traced to the behaviors they affect.

## 2. Problem

- **Tests don't track intent.** Tests are usually written from the code, so they verify "what the code does," not "what it should do." Coverage looks fine while the actual intended behavior goes unguarded.
- **Behavior drifts silently.** A change can alter behavior unintentionally and still pass a green suite, because nothing pins the *intended* behavior.
- **Specs are inert.** spec-manager specs capture *why* well (the Intentional Design Decisions layer is genuinely differentiated), but the "what" is an inert acceptance-criteria checklist that nothing executes and `verify` can only eyeball.
- **No behavioral impact analysis.** code-graph answers "what *code* does this change touch?" Nothing answers "what *intended behavior* does this change touch?"

## 3. Core principles (non-negotiables)

1. **Accepted behavior is authoritative.** An **accepted, non-quarantined** behavior's failure blocks completion until it is *classified* — as a **regression** (code is wrong), an **intended change** (recorded via a declared-intent artifact, §7), or a **test-infrastructure failure** (flaky / fixture / env → quarantine). The rule deliberately does *not* claim every red test means broken code — only that an accepted behavior may not fail *silently or unclassified*. This classification gate is what ties regression-safety, coverage, and design-time awareness into one mechanism.
2. **Intent has two kinds.** *Executable behavior* → an executable test (Gherkin scenario or a linked native test). *Declarative decisions* → prose. Only the first becomes a test; the second is governed by human review + certainty + (for security) scan-suppression notes.
3. **Truth flows in two directions.** Specs + behavior are **forward / authoritative** (code conforms to them). Reference docs are **reverse / descriptive** (they mirror the code). The two must never be conflated.
4. **Single source of truth, never a duplicate.** A *generated projection* (one source, a derived view) is allowed; a *hand-maintained duplicate* (two editable copies that drift) is forbidden.
5. **Adapter-based, runner-agnostic.** Behavior is modelled independently of any runner. An **adapter** links a behavior to whatever verifies it — a Gherkin scenario (cucumber-js, behave, pytest-bdd), a native test (jest, pytest, playwright, go-test), or `manual`. Like docs-manager detects project type, the layer detects available tooling. No hardcoded stack, and no forced re-authoring of tests that already exist.

## 4. The intent taxonomy

| Kind of intent | Example | Home | Verified by |
|---|---|---|---|
| **Executable behavior** | "a new user can register a passkey and is logged in" | a `Behavior` (stable id + lifecycle) linked to a test — Gherkin `.feature` *or* native, in the code tree | the runner, via the adapter — automated regression |
| **Declarative decision (feature-local)** | "this feature offers no password fallback" | Intentional Design Decisions section of the feature spec | human review + certainty (promote to a guard scenario where cheap) |
| **Declarative decision (cross-cutting)** | "we use Postgres, not Mongo"; "hexagonal architecture" | `knowledge-base/decisions/` (ADRs) | human review + certainty |
| **Principle (project-wide)** | "every endpoint must be authenticated by default" | `knowledge-base/principles.md` | applies to all of the above |

**Promotion rule:** prefer turning a declarative decision into a *guard scenario* (often a negative test) when it is cheap to do so — e.g., "no password fallback" → `When credentials are POSTed to /login, Then it is rejected`. When a decision genuinely cannot be tested, it stays declarative. That is the honest ceiling of what tests can do, not a failure.

## 5. Authority hierarchy & layout

Intent has an authority order, top to bottom, reflected in the layout:

```
knowledge-base/                  ← the project's source-of-truth, read by agents + humans
  principles.md                  ← constitution: project-wide rules            [borrowed from spec-kit]
  reference/                     ← architecture, API, schema (how it IS — descriptive, reverse-synced)
  specs/<category>/              ← per-feature intent + decisions + link to behavior (what it SHOULD be)
  decisions/                     ← cross-cutting ADRs (declarative intent, not feature-bound)
  security/                      ← security findings
  .graph/                        ← graph.json (code) + behavior.json (behavior) — generated

features/<category>/             ← Gherkin .feature (one adapter) = an executable test  (CODE tree)
  steps/                         ← step definitions = glue code (imports the app)
<native tests>                   ← jest / pytest / playwright tests, linked in place by adapter (CODE tree)
```

> The directory names above are the **live layout**, established by the standalone `knowledge-base/` migration (§9), which has **shipped**. The behavior work never depended on that migration; the phases simply now run against the `knowledge-base/` layout.

Key boundaries:
- **A behavior's test lives in the code tree** — a `.feature` next to its step definitions, or an existing native test in place. It *is* test code. Discovery from the knowledge base is handled by the spec's link + the behavior graph (see §6), **not** by duplicating the behavior into `specs/`.
- **`specs/` stays purely declarative**: intent + decisions + a link to the executable behavior.
- **`reference/` is reverse-synced** (mirrors code); **`specs/` is forward-authoritative** (drives code).
- **`reference/` links to decisions, never restates them.** A cross-cutting fact like "uses Postgres" is owned once — by its ADR, which holds the rationale, the rejected alternatives, and the conditions to revisit — and `reference/` points to it (`Postgres (see ADR-007)`). The reference doc records *what is*; the ADR records *what was decided and why*. This keeps `reference/` a generated projection, not a hand-maintained duplicate (the single-source-of-truth rule, §3.4), and it is what turns a later Postgres→Mongo swap into a reviewable event instead of a silent doc regeneration.

### Who owns what

To stop the spec's prose and the executable test from drifting into two copies of the same thing, ownership is explicit:

| Artifact | Owns |
|---|---|
| **spec** (`specs/`) | purpose, scope, rationale, constraints, non-executable (declarative) decisions |
| **behavior + its test** | the observable acceptance behavior (the *what-happens*) |
| **reference** (`reference/`) | description of how the code currently works |
| **principles / ADRs** | rules that constrain all of the above |

The spec describes *why and within what bounds*; it never restates the step-by-step behavior the test already owns.

### Naming conventions

| Thing | Convention | Example |
|---|---|---|
| Knowledge-base root | `knowledge-base/` (kebab-case, matches `security-reports`/`code-graph`) | — |
| Spec file | `SPEC-NNN-kebab-name.md` | `SPEC-012-passkey-login.md` |
| Behavior id | `BEH-NNN`, **stable across renames** | `@BEH-007` |
| Spec ↔ behavior link | `@SPEC-NNN` (feature/suite) + `@BEH-NNN` (per behavior) tags | `@SPEC-012 @BEH-007` |
| Behavior ↔ test link | `adapter` + `locator` in the behavior record | `adapter: jest` |
| Gherkin feature file | `kebab-name.feature` | `passkey-login.feature` |
| Step definitions | runner-conventional dir in the code tree | `features/steps/auth_steps.*` |
| Declared-intent record | `INTENT-NNN` | `INTENT-023` |
| Behavior graph data | `behavior.json` in `knowledge-base/.graph/` | — |

## 6. The behavior graph

Extend code-graph (`graph.json`) with a **sibling** file `behavior.json`. Keeping it separate — not a schema bump to `graph.json` — is deliberate: it lets the code-substrate decision (see §10) stay decoupled.

```
SPEC ──covers──▶ BEHAVIOR ──verified by──▶ TEST ──exercises──▶ CODE ──imports──▶ CODE
(intent)        (BEH-NNN,                 (adapter +          (files/fns)       (existing
                 lifecycle)                locator)                              code-graph)
```

- **`SPEC → BEHAVIOR`**: the ID link (`SPEC-012` ⇄ `@SPEC-012`) plus a per-behavior `@BEH-NNN`. Reliable, no inference. **Stable behavior ids are required** because file names and scenario titles are not durable identifiers — a renamed scenario must keep its identity, and a Scenario Outline's generated examples must resolve to one behavior.
- **`BEHAVIOR → TEST`**: the adapter + locator (Gherkin scenario, native test, …). One behavior maps to exactly one verifying test; a spec may own several behaviors.
- **`TEST → CODE`**: the only genuinely new edge, and it is *never asserted as certain*. Every edge carries **provenance**:
  - `source`: `explicit` (hand-declared) **>** `observed` (per-test runtime coverage) **>** `static` (parsed from step/test symbols) — in that trust order;
  - `confidence` + `freshness` (the commit it was observed at).

  Dynamic coverage is *broad*, not "precise" — it sweeps in setup, middleware, logging, shared frameworks — while static parsing is *narrow* — it sees glue, not runtime. Neither is collapsed into a confident `exercises` edge.
- **`CODE → CODE`**: existing code-graph.

**Coverage-unknown, never silent.** Governance leans on this graph, so it must *report when it cannot resolve* an edge (e.g. a path-aliased or dynamic import it can't follow) rather than return a small blast radius that looks complete. A **capability contract** for the substrate (§10) is a precondition for trusting any block decision built on it.

## 7. Behavioral blast-radius — the two directions

- **Direction A — code → behavior** (regression early-warning, and the design-time check): `git diff` → code-graph blast radius → intersect with test fingerprints → *"these behaviors exercise code you're touching."*
- **Direction B — intent → behavior** (the planning question): spec/behavior edit → ID link → affected behaviors → fingerprint → implementing code. Tells you both *which behaviors to revisit* and *which code will follow*.

**The governance rule that makes them trustworthy:** an accepted behavior's test may only be changed through a **declared-intent record** — a durable, machine-checkable artifact (`INTENT-NNN`: the behaviors it touches, a rationale, and an approver), surfaced in the spec's change-history and/or a commit trailer. Chat history does not count. A bare code change that breaks an accepted test is **always** a regression (or a test-infra failure → quarantine), never a license to edit the test. Without a concrete record, "declared intent" is unenforceable and every red test degrades into "just update it" until the safety net rots.

## 8. Ecosystem touchpoints & enforcement

| Skill | Change |
|---|---|
| **spec-manager** | Extended spec format; classify intent (testable → propose a behavior + scaffold/link a test; declarative → decision record); maintain the spec↔behavior link and lifecycle. |
| **code-graph** | Gains behavior/test nodes + provenance-bearing fingerprint ingestion (`behavior.json`). |
| **new "behavior" capability** | Manage the behavior lifecycle; via adapters, run the verifying tests with per-test coverage; record fingerprints. |
| **brainstorming** | At design time, query the behavior graph → *"this change touches behaviors X, Y — change or preserve?"* `principles.md` is auto-injected here so design happens with the constitution in view. |
| **wrap-up** | Run *accepted* behaviors, refresh fingerprints, flag *undeclared* regressions, keep spec↔behavior in sync, and run principle + consistency checks (block per the rules below). |
| **verify** | Upgraded from eyeballing prose to actually running the linked tests. |

### Principle enforcement

`principles.md` is enforced two ways, and no more: **soft** — auto-injected into the working context of brainstorming, planning, and wrap-up, so the agent designs with the constitution in view; and **checkpoint** — wrap-up and code-review diff the change against it and raise a finding on violation. A principle that is cheaply testable *may* additionally be promoted to a guard scenario (§4 promotion rule), but promotion is never required. A passive file is not enforcement; these two mechanisms are.

### Consistency & conflict checking

Contradictions between intents are caught by a **two-tier, scoped** check:

- **Tier 1 — link integrity (deterministic):** behavior links resolve (`@SPEC`/`@BEH` tags round-trip, adapter locators point at real tests), and lifecycle state is consistent (e.g. `accepted` but the scaffold still contains its `TODO` marker ⇒ error). Cheap and certain.
- **Tier 2 — contradiction (LLM, advisory):** on spec create-or-update and in batch at wrap-up, the *changed item only* is compared against **same-domain, higher-authority** items — initially **principles + feature-local decisions only** (which exist from Phase 1). **ADR-awareness is deferred** until the ADR phase ships a real `decisions/` format; checking specs against ADRs before then would reference machinery that doesn't exist — **delivered by P4a (2026-07-01):** the check now compares a changed spec against all active ADRs (always-global) and a changed ADR against its principles. Resolution follows the authority order in §5 (principles > specs/decisions > reference).

Scoping by category / blast-radius — never a whole-repo re-derivation — is deliberate: it keeps the check incremental and quiet enough to be trusted.

### Declarative-drift check

Declarative intent has no test to fail, so it is guarded at wrap-up by the same Tier-2 check — run **only for the declarative specs whose `related_code` intersects the change's blast radius** (cross-cutting ADRs are scoped by domain instead). This relies on the *existing* code-level blast radius from code-graph, not the behavior graph. The preferred long-term path remains promoting testable decisions into guard scenarios; this check is the honest fallback for the genuinely untestable. It lands in the **Governance/Expansion** phases, once the substrate's blast radius is trustworthy (§10). — delivered by P4b (2026-07-01): a wrap-up step-7 check, blast-radius-scoped over `related_code` (code-anchored, not always-global), resolve-to-proceed; see docs/superpowers/specs/2026-07-01-p4b-declarative-drift-design.md.

### Block vs. warn

Failures are gated by **what kind of check produced them**, not by a model's self-reported confidence:

- **Deterministic failures hard-block.** A Tier-1 link break, an *accepted* behavior's test failing, or a behavior-test change with **no** declared-intent record. These are facts; wrap-up refuses to complete until they're resolved — **fix** the code, or **declare intent** (file an `INTENT-NNN`, updating/superseding the spec or principle). A test-infra failure is resolved by **quarantine**, which removes it from the authoritative set until repaired.
- **Model findings (Tier-2 contradictions) must be *acknowledged*, but never hard-block on certainty alone.** A model's "high certainty" is not a calibrated probability, and blocking on it would train people to rubber-stamp "declare intent" to escape noise. So a model finding surfaces and requires an explicit acknowledgement — but model-confidence is promoted to a hard gate **only after** its false-positive rate is measured on a real project and shown acceptable.

The system never infers intent from a diff. It refuses to let a *deterministic* violation pass silently, and makes a *probabilistic* one impossible to ignore without being seen.

## 9. Phase decomposition

Each phase gets its own spec → plan → implementation cycle. The ordering is **mechanism-first**: the central behavior loop is validated by **dogfooding Phase 1 on a real project** as it is built, rather than building horizontal infrastructure or governance ahead of evidence.

> A separate, staged **Phase 0 vertical proof** was considered and deliberately dropped. Instead of proving the loop in isolation first, we fold that validation into Phase 1's first real use on the testbed. This is a conscious risk trade: some Phase 1 schema, lifecycle, and adapter choices are made provisionally and corrected in contact with reality.

1. **Phase 1 — Traceability MVP**: formalize spec↔behavior identity and the `proposed/accepted/quarantined/deprecated` lifecycle; support Gherkin **plus one native adapter**; deterministic integrity checks; run *accepted* behaviors at wrap-up and **block only deterministic failures**. Directory layout left intact. Detailed in `01-phase-1.md`.
2. **Phase 2 — Impact indexing**: explicit code links first; add *observed* per-test coverage as an optional enhancer with provenance + freshness; detect stale fingerprints; **measure false-positives and runtime**; introduce `behavior.json` only once the edge model is understood. → unlocks **Direction A**, then **B**.
3. **Phase 3 — Governance**: durable declared-intent records, behavior-change review tied to specs, principles enforcement (soft form may arrive earlier, being cheap), model contradiction checks as *advisory*, an acknowledgement audit trail.
4. **Phase 4 — Expansion**: more language/runner adapters; ADR support + ADR-aware conflict checks (delivered — P4a); declarative-drift checks (delivered — P4b); calibrated model enforcement *if the evidence supports it*.

**Decoupled, standalone work (shipped):** the `knowledge-base/` IA migration (`docs/ → knowledge-base/`, `project/ → reference/`, `security-reports/ → security/`, `.code-graph/ → .graph/`, add `principles.md` + empty `decisions/`) shipped as its **own** PR with no behavior changes — done **early** (cheapest while the repo is small) and never entangled with validating the behavior loop.

## 10. Deferred / open decisions

- **Code substrate & its capability contract.** Whether to keep homegrown code-graph, adopt [graphify](https://github.com/safishamsi/graphify) (symbol-level, multi-language, tree-sitter, confidence-scored — philosophically aligned), or borrow its ideas. **Independent of that choice, the substrate must satisfy a capability contract before governance depends on it:** resolve imports (incl. TypeScript path aliases — the current regex resolver treats non-relative imports as external and silently drops them), stable file identity, language coverage, per-edge confidence, freshness, changed-file impact, and an explicit **"coverage unknown"** signal instead of a falsely-small blast radius.
- **Frontmatter substrate.** The current spec frontmatter parser is hand-rolled and silently discards inline-array fields (e.g. `tags: [a, b]`). Replace it with a real YAML parser + schema validation **before** the schema is extended, since the model will depend on these fields.
- **ADR capture machinery.** Its own phase (§9, Phase 4); Tier-2 conflict checks stay ADR-blind until it ships. (delivered — P4a, see docs/superpowers/specs/2026-07-01-p4a-adr-support-design.md)

## 11. What we borrowed from spec-kit (and what we did not)

Verified against `github/spec-kit` (2026-06).

- **Borrowed — a constitution / principles file.** spec-kit's `constitution.md`; here `knowledge-base/principles.md`. Project-wide rules above all specs and decisions.
- **Borrowed — executable acceptance criteria.** spec-kit writes acceptance scenarios in Given/When/Then, but they stay inert prose. We make the same grammar *executable* — via a Gherkin `.feature` or a linked native test. This idea is fully absorbed into the behavior layer; it is not a separate artifact.
- **Not adopted — spec-kit wholesale.** spec-kit is a forward *build engine* (specify → plan → tasks → implement). freya-devkit already has a forward flow via superpowers (brainstorming → writing-plans → executing-plans) and its differentiator is the reverse-sync + intentional-decisions/security tie-in. Adopting spec-kit wholesale would discard that and couple the roadmap to an external template engine.

## 12. Glossary

- **Behavior** — an intended, observable fact about the system: a stable record (`BEH-NNN`) with a lifecycle, linked via an adapter to the test that verifies it. Not tied to any one test format.
- **Adapter / locator** — how a behavior points at its verification (Gherkin scenario, native test, or `manual`) and where that test lives.
- **Lifecycle** — `proposed` → `accepted` → `quarantined` → `deprecated`. Only *accepted, non-quarantined* behavior is authoritative.
- **Coverage fingerprint** — the set of files/lines a single test executes; the provenance-bearing `TEST → CODE` edge (never asserted as precise).
- **Generated projection** — a derived, read-only view of a single source of truth (allowed). Distinct from a duplicate.
- **Declared-intent record** — a durable, machine-checkable artifact (`INTENT-NNN`: behaviors touched, rationale, approver) — the only legitimate reason to change an accepted behavior's test.
- **Behavioral blast-radius** — the set of intended behaviors affected by a change.
