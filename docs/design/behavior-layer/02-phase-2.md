# Phase 2 — Impact Indexing (Behavioral Blast Radius)

**Status:** Draft for review
**Date:** 2026-06-29 · **Revised:** 2026-06-29 (post-Plan-1, folding in **F10** and the brainstorming that followed: test-level-agnosticism, per-level coverage, the two-skill split, the "we link, never create tests" boundary).
**Depends on:** `00-vision.md` (§6 behavior graph, §7 the two directions), `01-phase-1.md` (the `Behavior` entity, lifecycle, adapters, deterministic `verify`), and the **code-graph substrate fix** (`code-graph-substrate-fix.md`) — Phase 2's blast radius is meaningless until code-graph resolves real internal edges, which it now does.
**Unlocks:** Phase 3 (governance) — but only if the measurement gate (§6) shows the fingerprints are trustworthy.

---

## 1. Goal

After Phase 2, a change to code can answer **"which intended behaviors does this touch?"** and a change to intent can answer **"which code implements this behavior?"** — both riding on a `behavior.json` graph built on top of the (now-working) code-graph.

The new, never-certain edge is **`TEST → CODE`** (`exercises`). Phase 2 captures it from **observed per-test coverage**, records it with **provenance + freshness**, and wires the two blast-radius directions into `wrap-up` and `brainstorming`. It also closes the Phase-1 loop: accepted behaviors with real, runnable, instrumented tests.

This phase is **evidence-gated**: it must *measure* false-positive rate, runtime, and coverage-attribution reliability before anything downstream (Phase 3 governance) is allowed to trust the fingerprints.

## 2. Scope

**In scope**
- `behavior.json` — a **generated projection** (vision §3.4) holding `BEHAVIOR → TEST → CODE` edges, **owned by the new `behavior-graph` skill** (see §5b), sibling to `graph.json`.
- A **`level` field on behaviors** (unit / component / integration / e2e). The behavior layer is **test-level-agnostic** — see §3a.
- **Observed `exercises` edges** — captured by running an *accepted* behavior's verifying test with coverage; tagged `source: observed`, with `confidence` + `freshness` (the commit observed at).
- **Per-level coverage capture** (§4) — the mechanism differs by level: in-process runner-native coverage for unit/component; separate-process instrumentation of the running app for integration; e2e deferred.
- **Static `exercises` edges** — best-effort fallback parsed from step/test symbols; `source: static`, lower trust.
- Two new skills (§5b): **`behavior-runner`** (execute accepted behaviors via their adapter+level, capture coverage, emit fingerprints) and **`behavior-graph`** (own `behavior.json`, project frontmatter, merge by trust, serve Direction A/B).
- **Incremental execution + freshness caching** — only re-run behaviors whose code changed (Direction A) and whose fingerprint is stale; reuse cached fingerprints otherwise.
- **Staleness detection** — a fingerprint whose `freshness` commit predates a change to its files is flagged stale.
- **Direction A** (code → behavior) and **Direction B** (intent → behavior), surfaced in `wrap-up` and `brainstorming`.
- **Measurement** — fingerprint breadth, false-positive rate, runtime, **and coverage-attribution reliability** (incl. the bundler source-map remap risk, §4), recorded as a gating deliverable.
- **Close the loop on two levels** — BEH-003 as an **integration** exemplar (cucumber-js, HTTP layer — *already landed in Plan 1*) and BEH-002 as a **unit** exemplar (vitest, in-process, mocked clock). Proving two levels is what validates the level-agnostic claim and exercises the **second adapter** (a Phase-1 criterion not yet closed).
- **Folded-in dogfooding fixes:** **F5** (wrap-up never-synced guard), **F3** (`init` keeps empty spec category dirs).

**Out of scope (later / deferred)**
- **Hand-authored explicit edges** (`exercises:` in spec frontmatter). Deliberately dropped: users will not maintain edges by hand — automation is the point. Reintroduced *only* as an evidence-gated lever if measurement shows observed coverage is too noisy (§6).
- **Test creation / TDD / test generation.** The behavior layer **links to whatever tests exist** (§5c); it never writes tests or owns a testing methodology.
- Model-based contradiction checks, principle enforcement, model-confidence hard-blocking (Phase 3).
- ADR machinery (Phase 4).
- The **single-boot + inspector-delta** coverage optimization for integration level (§4, Approach B) — deferred until runtime measurement proves boot-per-behavior too slow.
- **E2E / component-level coverage capture** — the model accommodates them (§3a), but Phase 2 implements only unit + integration. Full-browser E2E for the happy-path BEH-001 (Playwright + WebAuthn virtual authenticator) is much later.
- **F4** (certainty model for agent-drafted-but-human-confirmed intent) — does not naturally arise in Phase 2; remains an open finding, not wedged in here.
- Graphify adoption — the §10 fallback if the homegrown substrate keeps accruing edge cases.

## 3. `behavior.json` — schema & the `exercises` edge

A **generated projection** (derived from specs + coverage runs + static parse — never hand-edited), **owned by `behavior-graph`** (§5b), sibling to `graph.json` (kept separate so the code-substrate decision stays decoupled, vision §6).

```json
{
  "version": 1,
  "commit": "<commit the graph was built at>",
  "behaviors": {
    "BEH-003": {
      "spec_id": "SPEC-001",
      "state": "accepted",
      "level": "integration",
      "adapter": "cucumber",
      "locator": "features/auth/passkey-login.feature#unknown-email-does-not-reveal-whether-a-user-exists",
      "coverage": "observed",
      "exercises": [
        { "path": "app/api/auth/passkey/authenticate/start/route.ts", "source": "observed", "confidence": 0.8, "freshness": "8223fa5" },
        { "path": "lib/webauthn.ts", "source": "observed", "confidence": 0.8, "freshness": "8223fa5" }
      ]
    }
  }
}
```

- **Keyed by stable `BEH-NNN`.** `spec_id` / `state` / `level` / `adapter` / `locator` are **projected** from spec frontmatter (single source of truth — not re-authored here).
- **`exercises` = the `TEST → CODE` edges.** Each carries `source` (`observed | static`), `confidence`, and `freshness` (the commit it was captured at). On merge, **higher trust wins** (`observed > static`; `explicit` reserved for the future lever).
- **Paths are `graph.json` file keys** — `behavior.json` sits *on top of* the code-graph so Direction A can intersect a code blast radius with these fingerprints. This is a **contract** with code-graph (same key format + the blast-radius query), not shared ownership (§5b).
- **Coverage enum: `observed | static | unknown`.** `observed` — runtime V8 coverage (unit/component). `static` — code-graph closure of a declared `entry` file (integration); the behavior must carry an `entry` field (project-relative route/handler path) whose transitive import closure becomes `source: static` edges. `unknown` — no usable coverage. Never a falsely-empty or falsely-attributed `exercises` list. An `unknown` result carries a **`reason`** discriminator (`level-deferred` | `test-failed` | `no-coverage` | `no-entry` | `entry-missing` | `no-graph`) so the consumer (`behavior-graph`) can distinguish "pending a future runner" from "test is red" from "ran but emitted nothing" from "integration entry not declared/found" from "no code-graph built yet" — and decide whether to preserve a prior `observed` edge on merge. (Added during Plan 2; the producer emits it today.)
- Only **accepted, non-quarantined** behaviors get fingerprints (others aren't run).

### 3a. Test-level-agnosticism (a property of the model, not a skill)

The behavior layer is already **runner-agnostic** (cucumber / jest / vitest / playwright / pytest via adapters). It is also **test-level-agnostic**: a behavior is verified by *whatever level best proves it*, recorded in its `level` field:

| Level | Fits behaviors that are… | Typical adapter/runner |
|---|---|---|
| `unit` | logic in one function/module | native (vitest/jest), in-process |
| `component` | a UI piece in isolation | native (vitest + testing-library) |
| `integration` | a guarantee at a service/API boundary | cucumber (Gherkin) or native, over HTTP |
| `e2e` | a full-system user flow | playwright (browser) |

The layer does **not** prescribe a test pyramid — the team decides how much of each to write. The layer's job is only to make the *intended behaviors* first-class and traceable to whatever verifies them, at whatever level. `level` is just a field + the runner's dispatch key; it is **not** a separate skill.

> **F10 nuance.** "Drive the app over its real interface, never import its internals" is the rule for **integration/e2e of endpoints** (importing a framework route handler drags the whole framework module graph into a CommonJS-default test process — Node `require(esm)` then forbids it). It is **not** a blanket ban on in-process: a **unit** test that imports a plain `lib/` function and calls it in-process is correct and expected. Different levels, different mechanics.

## 4. Observed coverage capture (per level)

The **`behavior-runner`** skill (§5b) is invoked at `wrap-up` Phase 3.5 and on demand. It:

1. **Detects the runner / resolves the adapter** — reuse `detect_test_runners()` (cucumber-js, vitest, jest, playwright, pytest-bdd are the same idea per adapter).
2. **Runs each (selected, accepted) behavior's test with coverage — by a mechanism chosen by `level`:**
   - **`unit` / `component` (in-process, vitest/jest):** the code under test runs *in the test process*, so coverage is the **runner's native** V8/c8/istanbul output. Attribution is trivial and precise.
   - **`integration` (HTTP, cucumber + the app-under-test harness):** the app runs in a **separate process**, so we instrument *that* process. **Approach A — boot-per-behavior** (Phase 2 default): launch the app under V8 coverage (`NODE_V8_COVERAGE`/c8), run only that behavior's scenario(s) over HTTP, shut it down, read the coverage → that is the behavior's fingerprint. Clean attribution (the process handled only this behavior), zero app modification, framework-agnostic. Cost is one app boot per behavior — bounded by incremental execution (§4a). **Approach B — single boot + inspector deltas** (`Profiler.takePreciseCoverage` before/after each scenario) is the documented optimization, **deferred until measurement (§6) shows A is too slow.**
   - **`e2e` (browser):** deferred (§2).
3. **Maps executed files → `graph.json` keys**, drops externals/`node_modules` → that set is the `observed` fingerprint.
4. **Emits fingerprints** (`source: observed`, a `confidence`, `freshness: <current commit>`) for `behavior-graph` to merge.

**Attribution is per-behavior** (each scenario/test = one `BEH-NNN`). Fingerprints are honestly **broad, not precise** (a test sweeps middleware/logging/framework, vision §6) — recorded as `observed`, never as a certain edge.

> **Source-map remap risk (spike + measured, §6).** For bundler-based frameworks (Next.js/Turbopack, webpack), V8 coverage of the running app may land on **compiled chunks**, not source files. c8 remaps via source maps, but reliability varies by framework/dev-vs-build. The runner must **remap to original source keys**; if it cannot do so reliably for a behavior, that behavior is `coverage: unknown` — never falsely attributed to a compiled-chunk path. This risk does **not** affect in-process unit coverage (no bundler in the path). It is the single biggest technical unknown in Phase 2 and gets an explicit spike before the integration fingerprint is trusted.

### 4a. Scaling (why per-behavior is fine)

Per-behavior *isolation* is about attribution granularity, not run volume. Volume is bounded by:

- **Incremental execution — Direction A doing double duty.** At wrap-up: `git diff` → code-graph blast radius → intersect with `behavior.json` fingerprints → **only re-run the affected behaviors.** Steady-state that's a handful regardless of total behavior count. A full sweep happens only on first index or explicit `--rebuild`.
- **Freshness caching.** A behavior whose files are unchanged since its `freshness` commit reuses its cached fingerprint — no re-run.

So even the heavier integration path (boot-per-behavior) runs only for the few behaviors a change actually touches.

### 4b. Mocking guidance (for behavior tests specifically)

Mocking is orthogonal to level but correlates (unit mocks heavily; integration selectively; e2e barely). For **behavior** tests the guidance is sharp: **mock as little as possible — only genuinely external/nondeterministic boundaries** (clock, randomness, paid third-party APIs). Two reasons:
1. **Fidelity.** Over-mocking tests "the mock did what I told it," not the behavior. For BEH-003, mocking the DB to return "no user" would test the mock, not the no-enumeration guarantee.
2. **Fingerprint breadth.** Heavy mocking shrinks the `exercises` fingerprint to near-nothing, weakening Direction A.

This is *guidance recorded with the behavior*, not an enforced rule.

## 5. The two directions & where they surface

- **Direction A — code → behavior** (regression early-warning *and* the test-selection lever): `git diff` → code-graph blast radius → intersect with fingerprints → "these accepted behaviors exercise code you changed." At **wrap-up** this (a) selects which behaviors to re-run, and (b) flags any whose test now fails as a deterministic regression (vision §8 block rules).
- **Direction B — intent → behavior** (the planning question): a spec/behavior → its fingerprint → implementing code. Available to **brainstorming** at design time: "this change touches behaviors X, Y — change or preserve?"

Both are **served by `behavior-graph`**, which owns `behavior.json` and calls code-graph's blast-radius query for the Direction-A intersection.

### 5b. Architecture — where each piece lives, and why two new skills

The behavior layer keeps the plugin's modular, tiered-skills philosophy. The decisive design point: **execution is a fundamentally different kind of operation than graph maintenance.** code-graph's "build" is static parsing — cheap, pure, no subprocess. Running behaviors boots app servers, drives third-party runners, manages processes/ports, captures runtime coverage — heavy, environment-coupled, and the flaky part of the system. Bundling that into the graph layer would pollute a pure, deterministically-testable data layer with the one messy operation. So they split on that seam:

| Concern | Skill | Character |
|---|---|---|
| code↔code dependency graph + blast-radius query | **code-graph** (exists) | pure, foundation. **Knows nothing about behaviors** — `behavior.json` is *not* owned here. |
| Behavior entity, lifecycle, adapter, locator, **`level`**, `verify_links`, `init` | **spec-manager** (exists) | intent authoring + deterministic integrity |
| Detect runner, dispatch by adapter+level, boot the app-under-test harness, capture per-level coverage, map files→keys → **emit fingerprints** | **`behavior-runner`** (new) | heavy, flaky, tooling-coupled (subprocess) |
| Own `behavior.json`: project spec frontmatter, ingest fingerprints, merge by trust, compute affected/stale set, serve **Direction A/B** | **`behavior-graph`** (new) | pure, deterministic, queryable (parallels code-graph in character) |
| Orchestrate + enforce deterministic blocking | **wrap-up** (exists) | orchestrator |

**Why two new skills, not one:** they have different reasons to change (SRP). `behavior-runner` changes when you add a runner/adapter/level or a coverage mechanism; `behavior-graph` changes when the projection schema, trust/merge rules, or Direction A/B query semantics change. The interface between them is a crisp data contract — the runner emits `{BEH-NNN: {exercises:[{path,source,confidence,freshness}], coverage}}`, the graph ingests and merges. `behavior-graph` can be queried (and unit-tested) without ever running a test; `behavior-runner` can be invoked to produce fingerprints without caring about the graph.

**Dependency direction (all arrows up):** `behavior-runner → code-graph + spec-manager`; `behavior-graph → behavior-runner + code-graph + spec-manager`; `wrap-up → behavior-graph`. `behavior-graph`'s build/update orchestrates the runner (project frontmatter → ask the runner for fingerprints of the selected set → merge) — the direct analogue of `code-graph build = scan`, except the heavy "scan" (execution) is delegated to a dedicated skill because it's heavy.

> **Cost, honestly:** two skills = more surface and one orchestration hop, and `behavior-graph` starts thinner than the runner. But the seam is visible *now*, and splitting later would mean migrating `behavior.json` ownership and reshuffling command surfaces — more painful than starting clean.

### 5c. Boundary with test-creation tools (gsd, superpowers TDD)

The behavior layer **does not write tests, run TDD, or replace a test runner.** Its differentiated value is narrow: the **Behavior entity** (stable `BEH-NNN`, lifecycle, intent classification), the **behavior graph** (intent ↔ test ↔ code blast radius), and **governance** (deterministic verify now; contradiction checks later). It therefore **composes** rather than competes:

- **superpowers TDD** writes the test (red-green-refactor); the behavior layer then links a behavior to it.
- **gsd** runs its own phase/requirement flow and even generates tests + checks coverage (`gsd-nyquist-auditor`); the behavior layer links behaviors to those tests by `locator` and adds the cross-cutting traceability gsd's per-phase model doesn't give.

The rule: **whoever creates the test (human, TDD, gsd, anything), the behavior layer links the intended behavior to it and captures the code it exercises.** We never own test *creation* or *methodology* — only the traceability and governance on top.

## 6. Measurement (the evidence gate)

A first-class deliverable, not a vibe — recorded in `dogfooding-notes.md` and a results subsection here:

- **Fingerprint breadth** — files-per-fingerprint distribution (how broad the coverage sweep is), per level.
- **False-positive rate** — for representative changes, of the behaviors Direction A flags, how many are *genuinely* relevant vs. swept in incidentally (hand-judged on the small testbed set).
- **Runtime** — time to capture a fingerprint (in-process unit vs. boot-per-behavior integration) and to do an incremental re-run for a typical change.
- **Coverage-attribution reliability** — does integration coverage remap from compiled chunks back to source keys correctly (the §4 bundler source-map risk)? Measured before any integration fingerprint is trusted.

These numbers **gate four decisions**:
1. Is `observed` coverage trustworthy, or must we **reintroduce explicit anchors** (the dropped `exercises:`)?
2. Is boot-per-behavior fast enough, or do we need the **single-boot + inspector-delta** optimization (§4 Approach B)?
3. Is integration source-map remap reliable, or must some integration behaviors stay `coverage: unknown` (and lean on the unit level instead)?
4. Can governance ever **hard-block** on this (Phase 3), or must it stay advisory? (Vision §8 ties block-vs-warn to exactly this measured FP rate.)

### 6a. Measurement results (Plan 5, on the testbed — 2026-06-29)

Measured on the testbed (2 accepted behaviors: BEH-002 unit/observed, BEH-003 integration/static). **These numbers validate the mechanism is selective and fast; they are illustrative, not statistically significant — the set is tiny (2 behaviors, 3 representative changes). Re-measure as the suite grows.**

- **Fingerprint breadth:** BEH-002 (observed/unit) = **1 file** (`lib/webauthn.ts`) — precise. BEH-003 (static/integration) = **3 files** (`…/authenticate/start/route.ts`, `lib/prisma.ts`, `lib/webauthn.ts`) — broader. Observed is tighter than static, as expected.
- **False-positive rate (hand-judged):**
  - edit `lib/webauthn.ts` → flags **[BEH-002, BEH-003]**; both genuinely depend on it (BEH-002 tests `verifyChallenge` in that file; BEH-003's route imports it). FP = 0/2.
  - edit `lib/audit.ts` → flags **[]** (neither behavior exercises audit) — correct selectivity, no false positives.
  - edit `…/authenticate/start/route.ts` → flags **[BEH-003]** only (BEH-002 is a unit test of `verifyChallenge`, doesn't touch the route). FP = 0/1; correct discrimination.
  - → **FP rate 0** on this small representative set; the gate is selective, not flag-everything.
- **Runtime:** full `--build` (runs all accepted: BEH-002 vitest + BEH-003 static) = **~1.4–2.4 s** (vitest-startup-dominated). Incremental `--check` on a change touching **no** exercised code = **0.07 s** (zero re-runs — the scaling win). Read-only `--affected`/`--implements` queries = **0.03–0.06 s**. The incremental model re-runs only affected behaviors, so cost scales with the *change's* blast radius, not the suite size.
- **Static-vs-observed:** BEH-003 static (3 files) over-approximates vs. BEH-002 observed (1 file) — the **safe** direction for blast radius. Observed is precise where capturable (unit); static is the framework-agnostic integration fallback (F11).

**The four gated decisions, answered (provisionally, pending scale):**
1. **Observed trustworthy?** Yes at the **unit** level — BEH-002's observed fingerprint is exactly `lib/webauthn.ts`, precise. No need to reintroduce hand-authored anchors.
2. **Per-behavior fast enough?** Yes — incremental `--check` skips unaffected behaviors (0.07 s when none affected); the inspector-delta optimization (§4 Approach B) is **not** needed at this scale.
3. **Integration source-map remap reliable?** **Deferred (F11)** — observed integration coverage is not captured on Next; **static** (code-graph closure) is used instead, which the breadth numbers confirm is usable and conservatively-broad. The observed-CDP adapter remains a future option (`parking-lot.md`).
4. **Can governance hard-block?** **Deterministic blocking is already safe** and shipped (wrap-up Phase 3.5 blocks on a `test-failed` of an *affected, executed* behavior — that's a real test failure, not a fingerprint inference). **Fingerprint-driven** governance (e.g. "you changed exercised code without touching intent") should stay **advisory** until the FP rate is measured on a larger suite. This is the gate Phase 3 must clear before promoting any fingerprint-based check to a hard block.

## 7. Closing the loop on the testbed (two levels)

Observed coverage requires accepted, passing, instrumentable tests. Phase 2 proves **two levels**:

- **`integration` — BEH-003** ("unknown email → generic options; no user enumeration"): a plain `POST /api/auth/passkey/authenticate/start` asserting a generic response — no crypto. Verified by cucumber-js over **real HTTP** against a running app (the app-under-test harness). **This already landed in Plan 1** (loop closed; BEH-003 `accepted`, `verify` green). Phase 2 adds its **observed fingerprint** via the integration coverage path (§4).
- **`unit` — BEH-002** ("login with an expired challenge is rejected"): the expiry decision is logic, best proven by a **vitest** test on the challenge-validation function, in-process, with a **mocked clock** (the one legitimate nondeterministic boundary). This validates the **unit** level, the **native adapter** (Phase-1's second-adapter criterion), and the in-process coverage path.
- **BEH-001 "successful passkey login" stays `proposed`** — a valid login needs a WebAuthn assertion signed by an authenticator, unforgeable below the browser/E2E layer (deferred).

Two behaviors, two levels, two adapters, two coverage mechanisms → exactly the contrast the measurement gate (§6) needs.

## 8. Folded-in dogfooding fixes

- **F5 — wrap-up never-synced ⇒ full generation.** While editing wrap-up (Phase 3.5 + Direction A), add a guard: if a project has never been synced (no tracking files), `docs`/`specs`/`security` `update` either no-ops with a clear message or requires an explicit first `scan`, instead of silently running a full-codebase generation.
- **F3 — empty spec category dirs vanish on commit.** Small `spec-manager init` change: drop a `.gitkeep` in each category dir (or create lazily) so the structure survives Git, consistent with the `decisions/` README rationale.
- **F4 — carried forward** (certainty for agent-drafted/human-confirmed intent). Does not naturally arise in Phase 2; remains an open finding.

## 9. Ecosystem touchpoints

| Skill | Change |
|---|---|
| **code-graph** | Unchanged in ownership: stays a pure code↔code graph and **exposes** the blast-radius query Direction A consumes. `behavior.json` is **not** owned here (revised — was incorrectly assigned to code-graph in the first draft). |
| **behavior-runner** (new) | Detects runner, dispatches accepted behaviors by adapter+level, boots the app-under-test harness (integration), captures per-level coverage, maps files→keys, emits fingerprints + freshness. |
| **behavior-graph** (new) | Owns/generates `behavior.json`; projects spec frontmatter; ingests + merges fingerprints by trust; computes the affected/stale selection set; serves Direction A (via code-graph) and Direction B. |
| **wrap-up** | Phase 3.5 asks `behavior-graph` for the affected accepted behaviors (incremental, Direction A), which orchestrates `behavior-runner`; flags undeclared regressions; F5 guard added. |
| **brainstorming** | Direction B query at design time ("this change touches behaviors X, Y"). |
| **spec-manager** | Adds the `level` field to the Behavior schema; `init` F3 fix; `behavior.json` projects its frontmatter (no new authored fields beyond `level`). |

## 10. Acceptance criteria

- [ ] `behavior.json` exists as a generated projection **owned by `behavior-graph`** (sibling to `graph.json`), keyed by `BEH-NNN`, with `level` and `exercises` edges carrying `source`/`confidence`/`freshness`.
- [ ] **code-graph remains pure** — it does not own or import `behavior.json`; it only exposes the blast-radius query.
- [ ] `behavior-runner` runs an accepted **integration** behavior (BEH-003) over real HTTP against a running app with V8 coverage, **remaps to source keys**, and records an `observed` fingerprint.
- [ ] `behavior-runner` runs an accepted **unit** behavior (BEH-002) in-process (vitest) with runner-native coverage and records an `observed` fingerprint.
- [ ] A behavior with no usable / non-remappable coverage is marked `coverage: unknown`, never falsely empty or attributed to compiled chunks.
- [ ] Direction A: a code change selects + flags the affected accepted behaviors (not the whole suite).
- [ ] Direction B: a behavior resolves to its implementing code.
- [ ] Incremental execution + freshness caching: an unaffected behavior is **not** re-run.
- [ ] Measurement recorded: fingerprint breadth, FP rate, runtime, **source-map remap reliability** — with the four gated decisions noted.
- [ ] Loop proven on the testbed at **two levels**: BEH-003 (integration, already accepted) produces a fingerprint; BEH-002 (unit, vitest) has a real test, is `accepted`, and produces a fingerprint.
- [ ] F5 guard and F3 `.gitkeep` landed; F4 explicitly carried forward.
- [ ] No model-based checks, no hand-authored edges, no test-creation, no inspector-delta optimization, no e2e/component capture (later/deferred).

## 11. Decisions resolved during brainstorming

1. **Scope B** — explicit *and* observed, but explicit-by-hand was then dropped (see #3); observed coverage is the mechanism.
2. **Runner-agnostic adapter model** (cucumber-js / vitest / jest / playwright / pytest-bdd); reuse the existing SPEC-001 scaffolds.
3. **Dropped hand-authored `exercises:`** — `behavior.json` is fully generated; explicit anchors are an evidence-gated future lever.
4. **F10 — drive the app over its real interface (HTTP) against a running instance for integration/e2e**, never by importing internals (in-process import is non-viable on CommonJS-default projects). In-process is still correct for unit tests of plain modules.
5. **Test-level-agnostic model** — a `level` field (unit/component/integration/e2e); the layer doesn't prescribe a test pyramid (§3a).
6. **Per-level coverage capture** — runner-native (in-process) for unit/component; separate-process instrumentation (boot-per-behavior; inspector-delta deferred) for integration; e2e deferred (§4).
7. **Mock minimally** for behavior tests — only external/nondeterministic boundaries (§4b).
8. **Two new skills** — `behavior-runner` (execution) and `behavior-graph` (the graph), split on the execution-vs-graph-maintenance seam; **`behavior.json` owned by `behavior-graph`, code-graph kept pure** (corrects the first draft) (§5b).
9. **Boundary: link, never create tests** — composes with gsd / superpowers TDD (§5c).
10. **Per-behavior attribution**, with **incremental execution + freshness caching** as the scaling story.
11. **Two-level loop closure** — BEH-003 (integration, landed) + BEH-002 (unit, vitest); BEH-001 stays proposed.
