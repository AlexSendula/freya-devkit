# Behavior Layer — Ecosystem Integration

*Research brief for the **plugin-wide** freya-devkit explainer. Audience: an
engineer who has never seen this plugin. Scope: the behavior layer treated **as
one capability** — how it slots into the plugin alongside code-graph,
spec-manager, docs-manager, security, and wrap-up. The deep internal mechanics
(schemas, fingerprint merging, per-script CLI surface, governance walkthroughs)
live in the dedicated behavior-layer explainer at
`docs/explanations/behavior-layer-explainer/`; this brief stays at the ecosystem altitude and
points there for depth.*

**Primary sources (all read directly):**
- `docs/design/behavior-layer/00-vision.md` (whole-initiative vision)
- `docs/design/behavior-layer/03-adoption-and-intent-lifecycle.md` (adoption + lifecycle)
- `docs/explanations/behavior-layer-explainer/README.md` (the dedicated explainer's own map)
- `skills/behavior-graph/SKILL.md`, `skills/behavior-runner/SKILL.md`,
  `skills/status/SKILL.md`, `skills/wrap-up/SKILL.md`
- `docs/explanations/behavior-layer-explainer/_research/11-ecosystem-wiring.md` (the deep-dive
  ecosystem brief; this plugin-wide brief is its higher-altitude summary)

---

## 1. What it is (one paragraph)

The **behavior layer** is a single capability added to freya-devkit that makes
*intended behavior* a first-class, executable, blast-radius-aware artifact. Before
it, the plugin was "a strong *reverse-sync engine*" — after code changes it kept a
dependency graph, docs, specs, and security findings in sync — but it had no way
to capture **what the system is supposed to do** in an executable form (vision
§1). The behavior layer adds that: each observable behavior becomes a stable
record (`BEH-NNN`) with a lifecycle `state`, linked by an *adapter + locator* to a
real test, and projected into a **behavior graph** (`behavior.json`) that sits as
a sibling to the existing code graph. As one capability it is delivered by **three
new skills** (`behavior-graph`, `behavior-runner`, `status`), an **extension to
`spec-manager`** (the lifecycle, governance scripts, and intent taxonomy), and a
**new pipeline phase in `wrap-up`** (Phase 3.5). It does not replace anything — it
extends the existing reverse-sync toolkit with a forward-authoritative intent
layer.

> "Make **intended behavior** a first-class, executable, blast-radius-aware
> artifact in the freya-devkit ecosystem." (vision §1)

---

## 2. Why it exists (the four gaps it closes)

From vision §2, verbatim problem statement:

- **Tests don't track intent.** "Tests are usually written from the code, so they
  verify 'what the code does,' not 'what it should do.'"
- **Behavior drifts silently.** "A change can alter behavior unintentionally and
  still pass a green suite, because nothing pins the *intended* behavior."
- **Specs are inert.** spec-manager captured *why* well, but "the 'what' is an
  inert acceptance-criteria checklist that nothing executes and `verify` can only
  eyeball."
- **No behavioral impact analysis.** "code-graph answers 'what *code* does this
  change touch?' Nothing answers 'what *intended behavior* does this change
  touch?'"

The behavior layer's one-line ecosystem value: it turns specs from **inert prose
that nothing runs** into **executable, governed guarantees**, and extends
code-graph's blast radius from *code* to *intended behavior*.

---

## 3. The capability's moving parts (the cast, at ecosystem altitude)

| Piece | Kind | Role in the plugin |
|---|---|---|
| `code-graph` | pre-existing skill | Foundation/substrate. Builds `knowledge-base/.graph/graph.json` (import dependency graph); answers `impact <file>` = blast radius. The behavior layer builds *on top of* it, never modifies it. |
| `spec-manager` | **extended** skill | Owns the intent taxonomy: `principles.md`, `specs/`, `decisions/` (ADRs), `intents/`. Gains the behavior lifecycle, spec↔behavior links, and the deterministic + governance scripts. |
| `behavior-graph` | **new** skill | Owns `behavior.json` (the BEHAVIOR → TEST → CODE projection). Pure graph layer over code-graph + behavior-runner. Serves Direction A / Direction B. |
| `behavior-runner` | **new** skill | Runs a project's *accepted* behaviors via their adapter; captures TEST → CODE coverage fingerprints. Producer for the behavior graph. |
| `status` | **new** skill | Read-only counterpart of wrap-up. Aggregates outstanding intent/coverage/security work; refreshes git-tracked `knowledge-base/BACKLOG.md`. |
| `wrap-up` | **extended** skill | The orchestrator. Gains **Phase 3.5** (behavior integrity + accepted-behavior run + governance checkpoints) and the behavior-aware staging rule. |
| `codebase-security-scan` | **extended** skill | Now cross-references `accepted`, test-backed behaviors as the *strongest* "intentional" evidence, in addition to declarative specs. |
| brainstorming / planning (superpowers) | design-time consumers | Query the behavior graph and receive the soft-injected constitution at design time. |

Key architectural boundary: **behavior-graph is a pure graph layer.** It
*queries* `code-graph` (`--impact`) and `behavior-runner` (`--emit-fingerprints`);
"`code-graph` stays unaware of behaviors" (behavior-graph SKILL). Keeping
`behavior.json` a **sibling** of `graph.json` — not a schema bump — is deliberate
so the code-substrate choice stays decoupled (vision §6).

---

## 4. How it composes with the plugin's other skills

### 4a. It extends `spec-manager` (the intent side)

spec-manager already owned "*why*" (intentional design decisions). The behavior
layer adds the "*what*" as an executable, lifecycle-bearing record:

- **Intent taxonomy** (vision §4): *executable behavior* → a `Behavior` linked to a
  test; *declarative decision* → prose in the spec or an ADR; *principle* →
  project-wide rule in `principles.md`. Only the first becomes a test.
- **Lifecycle**: `proposed → confirmed → accepted → quarantined/deprecated`. Only
  **accepted, non-quarantined** behavior is authoritative. The `confirmed` state
  (adoption doc §3) is the key addition — it separates *confirming intent* from
  *writing the test*, so intent capture never forces mid-feature test authoring.
- **Governance scripts** live under spec-manager: `verify_links.py`,
  `verify_intent.py` (G1), `adr.py` (P4a), `principles.py` (G2),
  `contradictions.py` (G3), `drift.py` (P4b). wrap-up calls them; spec-manager owns
  them.
- **spec↔behavior link**: `@SPEC-NNN` + `@BEH-NNN` tags round-trip between the spec
  frontmatter and the test, so discovery needs no duplication into `specs/`.

### 4b. It extends `code-graph` (the impact side)

code-graph answers "what code does this change touch?" The behavior layer adds a
second graph that answers the two blast-radius directions (vision §7):

- **Direction A — code → behavior** (regression early-warning): `git diff` →
  code-graph blast radius → intersect with test fingerprints → "these behaviors
  exercise code you're touching."
- **Direction B — intent → behavior** (the planning question): spec/behavior edit →
  ID link → affected behaviors → fingerprint → implementing code.

Direction A rides on code-graph's `impact` traversal; behavior-graph never
re-implements dependency analysis.

### 4c. It extends `wrap-up` (the enforcement side)

wrap-up gains **Phase 3.5** between spec update (Phase 3) and security scan (Phase
4). See §6. It also gains the **behavior-aware staging rule** in Phase 0 (§7).

### 4d. It extends `codebase-security-scan` (the cross-reference side)

The scan already marked a finding `INTENTIONAL DESIGN` when a declarative spec
explained it. Now it also consults the behavior graph: an `accepted`, test-backed
behavior that explains a flagged finding is "the **strongest possible
'intentional' evidence** — a *verified guarantee*, not a prose claim" (adoption
§7). Findings not explained flow into the backlog.

### 4e. It adds `status` (the read-only counterpart of wrap-up)

Two unifying commands, deliberately not conflated (adoption §6):
- **`wrap-up`** = the do/sync command (mutates, commits).
- **`status`** = the read-only check: "where do I stand, what's outstanding?"
  Aggregates behavior state counts, the two worklists (intent, test-owed),
  coverage `gaps`, open security findings, and deterministic verify failures; and
  refreshes the generated, git-tracked `knowledge-base/BACKLOG.md`.

---

## 5. The adoption model (how intent gets into a real codebase)

This is the ecosystem-level answer to "how do I turn this on without drowning?"
(adoption doc). The core idea: **decouple inference from validation.**

- **Inference is cheap, done up front:** at adoption, bootstrap a full graph of
  *candidate* behaviors from the code — **all `proposed`, nothing trusted.**
- **Validation is the scarce resource, spent lazily:** the engineer only confirms
  intent for the small subset a change actually touches (Direction A), in the flow
  of work.
- **The cold tail** (behaviors never hit by work) is drained one at a time from a
  backlog via `status review intent` / `status review tests`.

The onboarding flow **detects project shape and degrades** (adoption §4):
- **Brownfield** (substantial code): `spec-manager init` → `code-graph build` →
  `scan` (infer candidates, all `proposed`) → `behavior-graph build`. "Nothing to
  review yet."
- **Greenfield / scaffold-only**: **skip inference**, set up structure + empty
  graphs, message clearly ("greenfield — author behaviors forward as you build").
  Detection uses `detect_project.py` + code-graph file counts.

> "a full bootstrap is fine *because you never have to review it all at once.*"
> (adoption §2)

`certainty` here is **the prioritizer of the proposed pile**, not a trust signal —
trust is the lifecycle `state` (adoption §4, §8).

---

## 6. The wrap-up Phase 3.5 pipeline (the enforcement seam)

Phase 3.5 ("Behavior Integrity & Accepted-Behavior Run") is where the capability
plugs into the plugin's existing post-implementation workflow. It runs **after**
graph/docs/specs updates and **before** the security scan. It is a **graded**
pipeline — the governing philosophy is that failures are gated by *what kind of
check produced them*, not by a model's confidence (vision §8):

| Step | Check | Skill/script | Gate |
|---|---|---|---|
| 1 | Link integrity + ADR integrity | `spec-manager` `verify_links.py`, `adr.py verify` | **HARD-BLOCK** (deterministic) |
| 2 | Declared-intent gate (G1) | `spec-manager` `verify_intent.py` | **HARD-BLOCK** (deterministic) |
| 3 | Build graph + run affected accepted behaviors (Direction A) | `behavior-graph --build` then `--check` | **HARD-BLOCK on regression** |
| 4 | Validate-on-hit (surface proposed/confirmed touched by change) | `behavior-graph --surface` | **ADVISORY — never blocks** |
| 5 | Principle checkpoint (G2) | `spec-manager` `principles.py` | resolve-to-proceed (model judgment) |
| 6 | Contradiction check (G3) | `spec-manager` `contradictions.py` | resolve-to-proceed (model judgment) |
| 7 | Declarative-drift check (P4b) | `spec-manager` `drift.py` | resolve-to-proceed (model judgment) |

Canonical ordering (verbatim, wrap-up scope note): "deterministic facts (G1 +
links + **adr verify** + accepted-behavior run) → G2 principle checkpoint (step 5)
→ G3 intent-coherence (step 6) → P4b declarative-drift (step 7)." Deterministic
facts block early and cheaply; expensive model judgment runs only after the facts
are clean.

**Two gate classes** (vision §8):
- **Deterministic failures HARD-BLOCK.** A link break, an accepted behavior's test
  failing, or an accepted-test change with no declared-intent record. "These are
  facts; wrap-up refuses to complete until they're resolved" — fix the code,
  declare intent (`INTENT-NNN`), or quarantine a test-infra failure.
- **Model findings (G2/G3/P4b) resolve-to-proceed but never hard-block on
  confidence alone.** They surface and must be *acknowledged/resolved*, but
  "'Ignore and push' is **not** a resolution." Model-confidence is promoted to a
  hard gate "only after its false-positive rate is measured on a real project and
  shown acceptable."

The Direction-A regression check (step 3) re-runs *only* the accepted behaviors
whose exercised code the change touched — **not the whole suite** — which is the
whole point of the behavior graph as an impact index.

*(Full per-step CLI and resolution-log mechanics: see the deep-dive brief
`docs/explanations/behavior-layer-explainer/_research/11-ecosystem-wiring.md` §5, and
`skills/wrap-up/SKILL.md` Phase 3.5.)*

---

## 7. The behavior-aware staging rule (a subtle two-commit refinement)

The plugin's signature **two-commit pattern** (code commit + artifacts commit) is
refined by the behavior layer. Normally files sort into the two commits by
*location* (code tree vs. `knowledge-base/`). The behavior layer overrides that
with lifecycle `state`:

> "A behavior scaffold's commit class follows its **lifecycle `state`, not its
> file location.**" (wrap-up SKILL)

A `.feature` scaffold lives under `features/` in the code tree, but until it is
`accepted` and authored it is *intent under review* → it rides the **artifacts**
commit. Once `accepted` with its `TODO(scaffold)` marker gone, it joins the
**code** commit. Rationale: intent can't be reliably inferred from code, so a
`proposed` scaffold is a draft proposal, not a verified guarantee — committing it
as "code" would blur the line the whole capability exists to keep sharp.

---

## 8. Design-time integration: soft-injected constitution + graph queries

The capability isn't only a wrap-up gate — it reaches back to **design time**
(vision §8 "Ecosystem touchpoints"):

- **`principles.md`** (the project constitution, borrowed from spec-kit's
  `constitution.md`) is **soft-injected** into the working context of
  brainstorming, planning, and wrap-up "so the agent designs with the constitution
  in view." The concrete call is `principles.py list --project .` at each
  design-time entry point.
- **brainstorming** queries the behavior graph: "this change touches behaviors X, Y
  — change or preserve?"
- **verify** is "**Upgraded from eyeballing prose to actually running the linked
  tests.**" (vision §8 table) — the single most quotable framing of the whole
  capability.

> "A passive file is not enforcement; these two mechanisms are." (vision §8, on
> `principles.md`: soft-injection + wrap-up/code-review checkpoint)

---

## 9. Inputs / outputs / artifacts (what it reads and writes)

| Artifact | Location | Owner | Git-tracked? |
|---|---|---|---|
| `graph.json` (code graph) | `knowledge-base/.graph/` | code-graph | no (cache) |
| `behavior.json` (behavior graph) | `knowledge-base/.graph/` | behavior-graph | **no** (git-ignored cache) |
| Behavior records (frontmatter + `@BEH-NNN`) | `knowledge-base/specs/` | spec-manager | yes |
| `.feature` files + step defs / native tests | code tree (`features/`, etc.) | code (once accepted) | yes |
| `principles.md` | `knowledge-base/` | spec-manager | yes |
| ADRs | `knowledge-base/decisions/` | spec-manager | yes |
| `INTENT-NNN.md` + `.intent-last-verified` | `knowledge-base/intents/` | spec-manager | yes |
| Resolution logs (`principle-`/`contradiction-`/`drift-resolutions.jsonl`) | `knowledge-base/` | spec-manager | yes |
| `BACKLOG.md` (generated, never hand-edited) | `knowledge-base/` | status / wrap-up | **yes** (diffs in PRs) |

Coverage fingerprint contract (behavior-runner output): each behavior maps to a
`coverage` of `observed | static | unknown`, with per-edge `source` / `confidence`
/ `freshness`. A behavior with no usable coverage is emitted `unknown` with an
empty `exercises` list — **never falsely attributed**.

---

## 10. Degradation behavior (how it fails safe)

The capability is designed to degrade rather than break — important for a plugin
that must work on any project shape:

- **No behaviors / greenfield:** onboarding skips inference and sets up empty
  graphs with a clear message. Not an error — it's the *easier* intent-first path.
- **No code-graph cache:** P4b drift's `impact_source` becomes `changed-only`
  (blast radius bounded to changed files, not their dependents) — "**never a silent
  empty set**"; the engineer is told the radius is narrower.
- **No `principles.md`:** the G2 principle checkpoint **skips** (nothing to
  enforce).
- **No changed specs/ADRs:** G3 contradiction check **skips**.
- **No `.intent-last-verified` baseline:** the G1 declared-intent gate **skips**.
- **`status` sources unavailable:** each source "degrades to a `note` if
  unavailable, and the command never blocks."
- **Never-synced project (F5 guard):** wrap-up's incremental `update` commands
  refuse to silently run a full-codebase generation on an unsynced project; it
  reports and defers to explicit `scan`/`build`.
- **Non-vitest / non-unit adapters:** emitted `coverage: "unknown"`, `reason:
  "level-deferred"` — the behavior is not run, never falsely marked passing.
- **Confirmed behaviors are advisory:** never executed, so never `test-failed`,
  so they **never gate** the regression check — "only `accepted` behaviors gate."

The overarching design rule is **"Coverage-unknown, never silent"** (vision §6):
governance leans on the graph, so it must *report when it cannot resolve an edge*
rather than return a falsely-small blast radius.

---

## 11. Honest limits — implemented vs. planned

The dedicated explainer is careful to distinguish shipped from stubbed; at
ecosystem altitude the load-bearing caveats are:

- **Adapter coverage is thin.** Only the **vitest unit path** is implemented in
  behavior-runner. jest and other adapters are "handled in later plans; behaviors
  using them are emitted with `coverage: 'unknown'` and `reason:
  'level-deferred'`" (behavior-runner SKILL). The vision's runner-agnostic promise
  is architectural, not yet fully realized.
- **Integration coverage is static, not observed.** Integration behaviors use the
  **static** code-graph closure of a declared `entry` (the observed per-framework
  V8+CDP adapter is deferred); e2e/browser is a later plan.
- **Model-judgment gates are advisory by design, not yet calibrated.** G2/G3/P4b
  resolve-to-proceed; promotion to hard gates awaits measured false-positive rates
  on a real project.
- **Substrate capability contract is a precondition, not a guarantee.** The vision
  names a capability contract the code substrate must satisfy before governance
  fully trusts it (resolve imports incl. TS path aliases, stable file identity,
  per-edge confidence, freshness, explicit "coverage unknown"). Whether to keep
  homegrown code-graph or adopt/borrow from `graphify` is a **deferred/open
  decision** (vision §10).
- **Frontmatter parser is hand-rolled** and "silently discards inline-array fields
  (e.g. `tags: [a, b]`)" — flagged in vision §10 to be replaced before the schema
  is extended.
- **Dogfooding numbers are illustrative, not benchmarks.** Per the explainer
  README, FP=0 was "measured on 2 behaviors / 3 changes — illustrative, not a
  benchmark." Quote with limits.
- **Phase 4 items delivered:** ADR support + ADR-aware conflict checks (**P4a**,
  2026-07-01) and declarative-drift checks (**P4b**, 2026-07-01) are marked
  delivered in the vision. Calibrated model enforcement is still "*if the evidence
  supports it*."

---

## 12. Verbatim quotable lines (with source)

- "Make **intended behavior** a first-class, executable, blast-radius-aware
  artifact in the freya-devkit ecosystem." — `00-vision.md` §1
- "Today the ecosystem is a strong *reverse-sync engine* … What it lacks is a way
  to capture **what the system is supposed to do**." — `00-vision.md` §1
- "**Accepted behavior is authoritative.**" — `00-vision.md` §3
- "Upgraded from eyeballing prose to actually running the linked tests." —
  `00-vision.md` §8 (the `verify` row)
- "Failures are gated by **what kind of check produced them**, not by a model's
  self-reported confidence." — `00-vision.md` §8
- "A passive file is not enforcement; these two mechanisms are." — `00-vision.md`
  §8 (on `principles.md`)
- "Inference is cheap and can be done up front; **validation is the scarce
  resource** and must be spent lazily, in the flow of work." — adoption doc §2
- "a full bootstrap is fine *because you never have to review it all at once.*" —
  adoption doc §2
- "an **`accepted`, test-backed behavior** … is the **strongest possible
  'intentional' evidence** — a *verified guarantee*, not a prose claim." —
  adoption doc §7
- "A behavior scaffold's commit class follows its **lifecycle `state`, not its
  file location.**" — `wrap-up/SKILL.md`
- "'Ignore and push' is **not** a resolution." — `wrap-up/SKILL.md` (G2/G3/P4b)
- "Confirmed behaviors are advisory … only `accepted` behaviors gate." —
  `behavior-graph/SKILL.md`

---

## 13. Where to go deeper

This brief is the *ecosystem-level* view. For the mechanics deliberately left out
here, the dedicated behavior-layer explainer and its research briefs are the
canonical source:
- `docs/explanations/behavior-layer-explainer/_research/11-ecosystem-wiring.md` — full Phase 3.5
  step-by-step, the complete staging table, merge-by-trust, soft-injection detail.
- `docs/explanations/behavior-layer-explainer/_research/06/07/08/09/10-*.md` — governance
  G1/G2/G3, P4a ADR, P4b drift, resolution-log refactor.
- `docs/explanations/behavior-layer-explainer/_research/02/03/04/05-*.md` — entity/adapters,
  graph/fingerprints, code-graph substrate, adoption SP1–SP5.
- `docs/design/behavior-layer/` — the source design docs (vision, phase designs,
  dogfooding notes, parking lot).

---

## 14. Notes / UNVERIFIED

- **Path inconsistency in wrap-up source (UNVERIFIED as intentional):** most
  Phase 3.5 commands use the portable `${CLAUDE_PLUGIN_ROOT}` prefix, but a few
  (`verify_intent.py` in steps 2 and Phase 5.0) use a hard-coded absolute path
  `/Users/main/.claude/plugins/cache/freya-devkit/freya-devkit/0.1.0/...`. This is
  a local-dev/dogfooding artifact and a known source inconsistency (also flagged in
  brief 11). Abstracted away here per sanitization; the portable form is the
  intended one.
- **Section/work-item labels** (`§8`, `G1–G3`, `P4a/P4b`, `SP1–SP5`, `F4/F5`,
  `Direction A/B`) are reproduced as-is from the source docs.
- All examples use the generic passkey-auth pattern (`SPEC-001`, `BEH-001/002/003`)
  used across the dedicated explainer; no proprietary/business content is
  reproduced.
