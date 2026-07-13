# Behavior Layer — The Problem & The Vision (Research Brief)

> Audience: an engineer who knows **nothing** about this feature and is coming from the original `main`.
> Source of truth for this brief:
> - `/Users/main/Documents/projects/freya-devkit/docs/design/behavior-layer/00-vision.md` (the vision doc, "Status: Draft for review", "Date: 2026-06-24")
> - `/Users/main/Documents/projects/freya-devkit/docs/migrations/knowledge-base.md` (the `docs/ → knowledge-base/` IA migration)
>
> Everything below is grounded in those two files. Verbatim quotes are marked. Anything I could not confirm is in the **Unverified** section at the end.

---

## 0. One-sentence framing

> "Make **intended behavior** a first-class, executable, blast-radius-aware artifact in the freya-devkit ecosystem." (verbatim, §1)

Freya-devkit today is described as a strong **reverse-sync engine**: after code changes, it keeps a dependency graph, docs, specs, and security findings in sync. The Behavior Layer adds the missing *forward* capability — capturing **what the system is supposed to do** in an executable form.

---

## 1. The Problem — four failure modes

The vision (§2 "Problem") names exactly four failure modes. Copy them accurately; each is the "before" that the whole initiative exists to fix.

1. **Tests don't track intent.** (tests mirror code, not intent)
   > "Tests are usually written from the code, so they verify 'what the code does,' not 'what it should do.' Coverage looks fine while the actual intended behavior goes unguarded." (verbatim)
   - *Why it matters:* a green, high-coverage suite can be entirely consistent with the system doing the wrong thing, because the tests were derived from the code rather than from intent.

2. **Behavior drifts silently.**
   > "A change can alter behavior unintentionally and still pass a green suite, because nothing pins the *intended* behavior." (verbatim)
   - *Why it matters:* nothing "pins" intended behavior, so an unintended behavior change is invisible — it doesn't turn the suite red.

3. **Specs are inert.**
   > "spec-manager specs capture *why* well (the Intentional Design Decisions layer is genuinely differentiated), but the 'what' is an inert acceptance-criteria checklist that nothing executes and `verify` can only eyeball." (verbatim)
   - *Why it matters:* the existing spec-manager is good at recording *why* a decision was made, but the *what* (acceptance criteria) is prose nothing runs. `verify` could only "eyeball" it.

4. **No behavioral impact analysis.**
   > "code-graph answers 'what *code* does this change touch?' Nothing answers 'what *intended behavior* does this change touch?'" (verbatim)
   - *Why it matters:* the existing `code-graph` computes a *code* blast radius but there was no way to compute a *behavioral* blast radius.

---

## 2. The Solution — one-line summary

> "This initiative adds that layer by making **behavior** a first-class entity — a stable, intent-bearing record linked to an executable test." (verbatim, §1)

Two concrete design commitments back that one-liner:
- The verifying test is authored as **Gherkin** (Given/When/Then) "where Given/When/Then adds intent-clarity", **or** linked to an existing **native test** (jest, pytest, playwright, …) "where one already covers the behavior; **Gherkin is the recommended default, not a requirement.**" (verbatim)
- It "extends the existing code-graph into a **behavior graph** so changes can be traced to the behaviors they affect." (verbatim)

The three properties the vision wants behavior capture to have (§1): **(a) executable** (so unintended behavior changes are caught), **(b) intent-driven** (so tests track behavior rather than whatever the code happens to do), and **(c) visible at design time** (so behavior changes are decided on purpose rather than discovered after the fact).

---

## 3. The five core principles (non-negotiables, §3)

These are the load-bearing constraints. Get these right and the newcomer understands the whole design's spine.

### Principle 1 — Accepted behavior is authoritative (the classification gate)
> "An **accepted, non-quarantined** behavior's failure blocks completion until it is *classified* — as a **regression** (code is wrong), an **intended change** (recorded via a declared-intent artifact, §7), or a **test-infrastructure failure** (flaky / fixture / env → quarantine)." (verbatim)

Crucial nuance the vision insists on:
> "The rule deliberately does *not* claim every red test means broken code — only that an accepted behavior may not fail *silently or unclassified*. This classification gate is what ties regression-safety, coverage, and design-time awareness into one mechanism." (verbatim)

**The three verdicts a failure must be classified into:**
| Verdict | Meaning | Resolution |
|---|---|---|
| **regression** | code is wrong | fix the code |
| **intended change** | behavior changed on purpose | record via a declared-intent artifact (`INTENT-NNN`, §7) |
| **test-infrastructure failure** | flaky / fixture / env | quarantine |

*Why it matters:* this single gate is what unifies regression-safety, coverage, and design-time awareness. It is intentionally humble — it does not assert "red test == broken code," only "an accepted behavior may not fail silently or unclassified."

### Principle 2 — Intent has two kinds
> "*Executable behavior* → an executable test (Gherkin scenario or a linked native test). *Declarative decisions* → prose. Only the first becomes a test; the second is governed by human review + certainty + (for security) scan-suppression notes." (verbatim)

### Principle 3 — Truth flows in two directions (forward/authoritative vs reverse/descriptive)
> "Specs + behavior are **forward / authoritative** (code conforms to them). Reference docs are **reverse / descriptive** (they mirror the code). The two must never be conflated." (verbatim)

*Why it matters:* this is the conceptual axis of the whole system. `specs/` + behavior **drive** the code; `reference/` **mirrors** the code. Conflating them is the classic doc-rot trap.

### Principle 4 — Single source of truth, never a duplicate
> "A *generated projection* (one source, a derived view) is allowed; a *hand-maintained duplicate* (two editable copies that drift) is forbidden." (verbatim)

*Why it matters:* the distinction is precise — a read-only derived view (projection) is fine; two independently-editable copies of the same fact (duplicate) are forbidden because they drift.

### Principle 5 — Adapter-based, runner-agnostic
> "Behavior is modelled independently of any runner. An **adapter** links a behavior to whatever verifies it — a Gherkin scenario (cucumber-js, behave, pytest-bdd), a native test (jest, pytest, playwright, go-test), or `manual`. Like docs-manager detects project type, the layer detects available tooling. No hardcoded stack, and no forced re-authoring of tests that already exist." (verbatim)

*Why it matters:* no lock-in to a test runner, and — critically — **no forced re-authoring** of tests a project already has.

---

## 4. The intent taxonomy (§4)

The core insight: not all "intent" is the same thing, and each kind has a **home** and a way it is **verified**. Four kinds:

| Kind of intent | Example (verbatim) | Home | Verified by |
|---|---|---|---|
| **Executable behavior** | "a new user can register a passkey and is logged in" | a `Behavior` (stable id + lifecycle) linked to a test — Gherkin `.feature` *or* native, in the code tree | the runner, via the adapter — automated regression |
| **Declarative decision (feature-local)** | "this feature offers no password fallback" | Intentional Design Decisions section of the feature spec | human review + certainty (promote to a guard scenario where cheap) |
| **Declarative decision (cross-cutting)** | "we use Postgres, not Mongo"; "hexagonal architecture" | `knowledge-base/decisions/` (ADRs) | human review + certainty |
| **Principle (project-wide)** | "every endpoint must be authenticated by default" | `knowledge-base/principles.md` | applies to all of the above |

### The promotion rule
> "prefer turning a declarative decision into a *guard scenario* (often a negative test) when it is cheap to do so — e.g., 'no password fallback' → `When credentials are POSTed to /login, Then it is rejected`. When a decision genuinely cannot be tested, it stays declarative. That is the honest ceiling of what tests can do, not a failure." (verbatim)

*Why it matters:* the system prefers to make a declarative decision *executable* (a negative/guard test) when cheap — but it is honest that some decisions are genuinely untestable, and staying declarative is "not a failure."

---

## 5. Authority hierarchy & the `knowledge-base/` layout (§5)

> "Intent has an authority order, top to bottom, reflected in the layout." (verbatim)

**The directory layout (verbatim, §5):**
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

Note (verbatim): "The directory names above are the **live layout**, established by the standalone `knowledge-base/` migration (§9), which has **shipped**. The behavior work never depended on that migration; the phases simply now run against the `knowledge-base/` layout."

**Authority order (top to bottom), used for conflict resolution (§5, restated in §8):** `principles > specs/decisions > reference`.

**Key boundaries (verbatim, §5):**
- "A behavior's test lives in the code tree — a `.feature` next to its step definitions, or an existing native test in place. It *is* test code. Discovery from the knowledge base is handled by the spec's link + the behavior graph (see §6), **not** by duplicating the behavior into `specs/`."
- "`specs/` stays purely declarative: intent + decisions + a link to the executable behavior."
- "`reference/` is reverse-synced (mirrors code); `specs/` is forward-authoritative (drives code)."
- "`reference/` links to decisions, never restates them." — e.g. "uses Postgres" is owned once by its ADR, and reference points to it (`Postgres (see ADR-007)`). "The reference doc records *what is*; the ADR records *what was decided and why*." This keeps `reference/` a generated projection (single-source-of-truth rule §3.4) and turns a later Postgres→Mongo swap "into a reviewable event instead of a silent doc regeneration."

### Who owns what (ownership table, §5, verbatim)
| Artifact | Owns |
|---|---|
| **spec** (`specs/`) | purpose, scope, rationale, constraints, non-executable (declarative) decisions |
| **behavior + its test** | the observable acceptance behavior (the *what-happens*) |
| **reference** (`reference/`) | description of how the code currently works |
| **principles / ADRs** | rules that constrain all of the above |

> "The spec describes *why and within what bounds*; it never restates the step-by-step behavior the test already owns." (verbatim)

*Why the ownership table exists:* "To stop the spec's prose and the executable test from drifting into two copies of the same thing, ownership is explicit." (verbatim)

---

## 6. Naming conventions (§5, verbatim table)

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

**Why stable ids matter (§6):** "Stable behavior ids are required because file names and scenario titles are not durable identifiers — a renamed scenario must keep its identity, and a Scenario Outline's generated examples must resolve to one behavior." (verbatim)

---

## 7. The behavior graph & the two blast-radius directions (§6–§7)

The behavior graph is `behavior.json`, a **sibling** to `graph.json` (not a schema bump). "Keeping it separate — not a schema bump to `graph.json` — is deliberate: it lets the code-substrate decision (see §10) stay decoupled." (verbatim)

**The edge chain (verbatim, §6):**
```
SPEC ──covers──▶ BEHAVIOR ──verified by──▶ TEST ──exercises──▶ CODE ──imports──▶ CODE
```

- `TEST → CODE` is "the only genuinely new edge, and it is *never asserted as certain*." Every edge carries **provenance**: `source: explicit (hand-declared) > observed (per-test runtime coverage) > static (parsed from step/test symbols)` in that trust order, plus `confidence` + `freshness` (the commit it was observed at). (verbatim)
- **"Coverage-unknown, never silent."** The graph "must *report when it cannot resolve* an edge … rather than return a small blast radius that looks complete." (verbatim)

**The two directions (§7):**
- **Direction A — code → behavior** (regression early-warning + design-time check): "`git diff` → code-graph blast radius → intersect with test fingerprints → *'these behaviors exercise code you're touching.'*" (verbatim)
- **Direction B — intent → behavior** (the planning question): "spec/behavior edit → ID link → affected behaviors → fingerprint → implementing code." (verbatim)

**Governance rule (§7):** an accepted behavior's test "may only be changed through a **declared-intent record** — a durable, machine-checkable artifact (`INTENT-NNN`: the behaviors it touches, a rationale, and an approver)… Chat history does not count. A bare code change that breaks an accepted test is **always** a regression (or a test-infra failure → quarantine), never a license to edit the test." (verbatim)

---

## 8. What was borrowed from spec-kit (and what was NOT) (§11)

> "Verified against `github/spec-kit` (2026-06)." (verbatim)

- **Borrowed — a constitution / principles file.** "spec-kit's `constitution.md`; here `knowledge-base/principles.md`. Project-wide rules above all specs and decisions." (verbatim)
- **Borrowed — executable acceptance criteria.** "spec-kit writes acceptance scenarios in Given/When/Then, but they stay inert prose. We make the same grammar *executable* — via a Gherkin `.feature` or a linked native test. This idea is fully absorbed into the behavior layer; it is not a separate artifact." (verbatim)
- **NOT adopted — spec-kit wholesale.** "spec-kit is a forward *build engine* (specify → plan → tasks → implement). freya-devkit already has a forward flow via superpowers (brainstorming → writing-plans → executing-plans) and its differentiator is the reverse-sync + intentional-decisions/security tie-in. Adopting spec-kit wholesale would discard that and couple the roadmap to an external template engine." (verbatim)

---

## 9. Glossary (§12, verbatim)

- **Behavior** — "an intended, observable fact about the system: a stable record (`BEH-NNN`) with a lifecycle, linked via an adapter to the test that verifies it. Not tied to any one test format."
- **Adapter / locator** — "how a behavior points at its verification (Gherkin scenario, native test, or `manual`) and where that test lives."
- **Lifecycle** — "`proposed` → `accepted` → `quarantined` → `deprecated`. Only *accepted, non-quarantined* behavior is authoritative."
- **Coverage fingerprint** — "the set of files/lines a single test executes; the provenance-bearing `TEST → CODE` edge (never asserted as precise)."
- **Generated projection** — "a derived, read-only view of a single source of truth (allowed). Distinct from a duplicate."
- **Declared-intent record** — "a durable, machine-checkable artifact (`INTENT-NNN`: behaviors touched, rationale, approver) — the only legitimate reason to change an accepted behavior's test."
- **Behavioral blast-radius** — "the set of intended behaviors affected by a change."

---

## 10. The `knowledge-base/` migration (from `docs/migrations/knowledge-base.md`)

Context a newcomer needs: the layout in §5 is real because of a **standalone, already-shipped** IA migration that moved generated artifacts out of `docs/` into one `knowledge-base/` root. "This changes **where** skills read/write, never **what** they do." (verbatim)

**Path moves (verbatim table):**
| Old location | New location |
|---|---|
| `docs/specs/` | `knowledge-base/specs/` |
| `docs/project/` | `knowledge-base/reference/` |
| `docs/security-reports/` | `knowledge-base/security/` |
| `docs/.code-graph/` | `knowledge-base/.graph/` |
| `docs/README.md` (generated index) | `knowledge-base/README.md` |
| — (new) | `knowledge-base/principles.md` |
| — (new) | `knowledge-base/decisions/` |

**Migration recipe (verbatim, "idempotent … safe to re-run"):**
```bash
# From the project root. Each line is safe to skip if the source dir doesn't exist.
[ -d docs/specs ]            && git mv docs/specs knowledge-base/specs
[ -d docs/project ]          && git mv docs/project knowledge-base/reference
[ -d docs/security-reports ] && git mv docs/security-reports knowledge-base/security
[ -d docs/README.md ]        || true   # if you keep a generated index, move it to knowledge-base/README.md

# The dependency graph is a regenerable cache — delete the old one and rebuild:
rm -rf docs/.code-graph
/freya-devkit:code-graph build
```
Then seed the two new homes "(or just run `/freya-devkit:spec-manager init`, which creates them if absent)":
- `knowledge-base/principles.md` — the project constitution (template: `skills/spec-manager/references/principles-template.md`).
- `knowledge-base/decisions/` — home for cross-cutting ADRs (README: `skills/spec-manager/references/decisions-readme.md`).

**Notes (verbatim):**
- "No behavior change. Skills resolve the new paths by default. `spec-manager`'s spec search keeps a legacy `docs/specs` fallback so a not-yet-migrated project stays readable, but all writes go to `knowledge-base/`."
- "The code graph need not be migrated — it is a cache keyed to a commit; rebuilding is cheaper and safer than moving it."

---

## 11. Newcomer takeaway (how to explain it in one breath)

Before: freya-devkit only synced *backwards* from code (graph, docs, specs, security) after the fact. Tests were written from the code, so they guarded "what the code does," not "what it should do" — and behavior could drift silently through a green suite. The Behavior Layer flips one axis forward: **intended behavior** becomes a stable, id'd record (`BEH-NNN`) with a lifecycle, linked through a runner-agnostic **adapter** to an actual executable test, and wired into a **behavior graph** so any change can be traced to the behaviors it touches. The enforcement core is one humble gate: an accepted behavior may not fail *silently or unclassified* — every failure is triaged into **regression**, **intended change** (which requires a durable `INTENT-NNN` record), or **test-infra failure** (quarantine).

---

## Related design docs (for cross-linking, exist in-repo — not the primary sources)
- `docs/design/behavior-layer/01-phase-1.md` (Traceability MVP detail)
- `docs/design/behavior-layer/02-phase-2.md` (Impact indexing / behavior.json / behavior-runner)
- `docs/design/behavior-layer/03-adoption-and-intent-lifecycle.md`
- `docs/design/behavior-layer/code-graph-substrate-fix.md`
- `docs/design/behavior-layer/dogfooding-notes.md`
- `docs/superpowers/specs/2026-07-01-p4a-adr-support-design.md` (referenced in §8/§10 of vision — P4a ADR support)
- `docs/superpowers/specs/2026-07-01-p4b-declarative-drift-design.md` (referenced in §8 of vision — P4b declarative-drift)
