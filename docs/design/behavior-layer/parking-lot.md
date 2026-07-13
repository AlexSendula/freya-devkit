# Behavior Layer — Parking Lot (deferred work & reminders)

Things we deliberately deferred so they get done **properly**, not on the go. Each entry says *what*, *why deferred*, and *how to pick it up*. Keep this current as items land or new ones surface. (Chronological friction findings live in `dogfooding-notes.md`; in-flight Phase-2 scope lives in `02-phase-2.md`. This file is the durable backlog.)

---

## Operational / cleanup (do before any release)

### Revert the local-dev plugin symlink
- **What:** the published plugin cache `~/.claude/plugins/cache/freya-devkit/freya-devkit/0.1.0` is currently a **symlink to the dev repo root** so `/freya-devkit:*` runs branch code (backup at `…/0.1.0.pre-phase1-backup`). This is a dogfooding hack, not a real install.
- **Why deferred:** needed for the whole Phase 1/2 dogfooding loop.
- **How to revert:** remove the symlink and `mv 0.1.0.pre-phase1-backup 0.1.0` (or reinstall from GitHub). Then **publish the real release** off `feat/behavior-layer` once it merges, and reinstall the normal way. Mirrors dogfooding-notes **F1/F2**. (Also recorded in persistent memory `project_phase1-dogfooding`.)

### Publish the real freya-devkit release
- **What:** GitHub `AlexSendula/freya-devkit` is still at the pre-Phase-1 commit; all behavior-layer work is local on `feat/behavior-layer`.
- **How:** after the branch merges, cut a new version (new skills `behavior-runner`/`behavior-graph`, updated `code-graph`/`spec-manager`/`wrap-up`), update the marketplace entry, then revert the symlink (above).

### Testbed: gitignore `coverage/`
- **What:** vitest (and the integration coverage path) writes `coverage/` in the testbed; it isn't gitignored. Minor, but add it so generated coverage isn't committed.

---

## Deferred capabilities (do properly, as their own effort)

### Per-framework observed-coverage adapter (V8 + CDP)  ← the big one
- **What:** real *observed* `TEST → CODE` coverage at the **integration/e2e** level, captured by launching the app under `--inspect` and collecting V8 coverage over the **Chrome DevTools Protocol** (the actual worker is at inspector **port + 1**), then remapping bundled `.next` output to source via source maps. Reference implementation: **`nextcov`** (stevez/nextcov) — dev + prod, emits istanbul-format, merges with vitest. `next-test-api-route-handler` (NTARH) is a related route-handler test tool.
- **Why deferred:** it's framework-specific (CDP port dance + source-map remap; `nextcov` is Next-only; **Next 16 + Turbopack support unverified**) and a meaningful chunk of engineering + a Node dependency. Too big to bolt on mid-BDD-implementation, and it deserves doing right. See **F11**.
- **Baseline in the meantime (Plan 3):** static via code-graph (`source: static`, conservatively-broad — the safe direction for blast radius). The observed adapter *upgrades* integration behaviors from `static` to `observed` where a project opts in.
- **How to pick it up:** model it as a **coverage adapter** (parallel to runner adapters) keyed by framework/level. First confirm Turbopack + Next 16 source-map fidelity (a focused spike). Istanbul/`babel-plugin-istanbul` is a **dead end on App Router** (breaks Server Actions) — do not pursue it.
- **Research:** [Why Istanbul fails on App Router](https://dev.to/stevez/why-istanbul-coverage-doesnt-work-with-nextjs-app-router-9ip) · [nextcov](https://github.com/stevez/nextcov) · [next.js Discussion #28606](https://github.com/vercel/next.js/discussions/28606) · [Playwright coverage example](https://dev.to/anishkny/code-coverage-for-a-nextjs-app-using-playwright-tests-18n7)

### Tracing adapter (consume the app's existing observability)
- **What:** for apps that **already** emit structured logs or OpenTelemetry traces, derive observed `exercises` edges by reading the trace for a test request (which components handled it) — *zero* instrumentation added by us.
- **Why deferred:** app-specific (depends on the app's tracing/log format; span→file mapping is coarse); discuss after the BDD implementation lands. Salvaged core of the "just add logging" idea — note that *generic* logging-as-coverage is really build instrumentation in disguise and hits the same bundling/worker wall, so only the "consume existing traces" form is worth it.
- **How to pick it up:** another **coverage adapter** variant, opt-in for instrumented apps.

### Graphify (code-graph substrate fallback)
- **What:** the homegrown `code-graph` resolver was fixed (alias/`tsconfig paths` resolution, cwd-independence, `unresolved` signal — see dogfooding **RESOLVED F6–F9**). Graphify is the heavier off-the-shelf option held in reserve (vision §10).
- **Why deferred:** the homegrown resolver is sufficient post-fix (0→607 internal edges on the testbed). Don't adopt a dependency we don't need yet.
- **Trigger to revisit:** if homegrown keeps accruing edge cases it can't handle cleanly — known gaps today are **`extends` chains** in tsconfig, **per-edge confidence**, and **monorepos**. If those pile up (especially once the static integration fingerprint leans hard on the import closure), evaluate graphify.

### Full E2E for the happy-path login (BEH-001)
- **What:** BEH-001 "successful passkey login" needs a WebAuthn assertion signed by an authenticator — only verifiable at the browser/E2E layer (Playwright + virtual authenticator). It stays `proposed` until then.
- **Why deferred:** much heavier than the guard/unit behaviors; not needed to prove the mechanism.

### ~~ADR capture machinery (Phase 4) — unlocks G3's ADR-awareness~~ — DELIVERED (P4a, 2026-07-01)
- **Resolved — P4a shipped.** Spec: `docs/superpowers/specs/2026-07-01-p4a-adr-support-design.md`. Delivered: the `ADR-NNN` format + lifecycle, `adr.py` (`new`/`list`/`verify`/`load_adrs`), `frontmatter.ADR_SCHEMA`, the G3 `build_context` ADR gather + the `build_adr_context` changed-ADR symmetry, and wrap-up wiring (`adr verify` hard-block + ADR-aware step 6). **Scoping decision reversed to always-global:** G3 compares a changed spec against *all accepted* ADRs — **no category scoping** (a research-backed reversal of an `applies_to`-by-category sketch, to avoid the silent-miss failure mode); authority **principle > ADR > spec**. **~~Successor still open~~** → **delivered — P4b (2026-07-01):** declarative-drift check (code-vs-declared-intent) — wrap-up step-7, blast-radius-scoped over `related_code` (code-anchored, not always-global), resolve-to-proceed. Spec: `docs/superpowers/specs/2026-07-01-p4b-declarative-drift-design.md`. Remaining Phase-4 leaves: **P4c** (more language/runner adapters), **P4d** (calibrated model enforcement — evidence-gated).
- **What (delivered):** a real format + capture flow for cross-cutting **Architecture Decision Records** in `knowledge-base/decisions/` — an `ADR-NNN.md` format (decision, rationale, rejected alternatives, revisit conditions), an `adr create` flow (ID allocation, index) mirroring `spec create`, and a gather so consumers can load ADRs.
- **Why deferred:** the governance track (G1–G3) is complete, but G3 is deliberately **ADR-blind** — `decisions/` is an empty scaffold today, so there's nothing to check against. G3 was built **ADR-ready**: once this machinery ships, `contradictions.py context` gains an ADR gather and the *same* G3 check extends to cross-cutting decisions. Rationale is documented at length in `docs/explanations/governance-explainer/index.html`.
- **How to pick it up:** brainstorm → spec → plan as its own sub-project. Then extend `build_context` to include ADRs in the comparison set, and add an authority-order rule for ADR vs spec. Also unblocks the **declarative-drift** check (code-vs-declared-intent), the other Phase-4 Expansion item, which can reference ADRs.

---

## Carried findings — status

**Resolved during Phase 2 (Plans 4–5)** — kept here only as a pointer to where they landed:
- ~~**F3**~~ — `spec-manager init` now drops `.gitkeep` in each spec category dir (Plan 5, `d65d5b5`).
- ~~**F5**~~ — `wrap-up` now carries a never-synced guard so `update` won't silently full-generate (Plan 5, `759105a`).
- ~~**`reason` discriminator**~~ — `behavior-graph`'s `merge_fingerprint` consumes it (invalidate on `test-failed`, preserve the prior edge on any other `unknown`) (Plan 4).
- ~~**Measurement (§6)**~~ — recorded in `02-phase-2.md` §6a and `dogfooding-notes.md` (Plan 5, `2a5a0ec`): selective (FP 0 on the testbed set), fast (incremental `--check` 0.07 s when nothing affected).

**Also resolved:**
- ~~**`level` / `entry` schema validation**~~ — `frontmatter.validate_behaviors` now rejects an unknown `level` (enum `unit`/`component`/`integration`/`e2e`) or non-string `entry`, and `verify_links` flags a declared `entry` that doesn't resolve (`bcaa8c9`). Fail-loud gap closed.
- ~~**F4 — certainty for agent-drafted-but-human-confirmed intent**~~ — **dissolved, not redesigned.** For *executable behaviors*, intent confidence is carried by lifecycle `state` (`accepted` = human-confirmed), which is what `certainty` was approximating — so the "hybrid score" problem disappears. `certainty` keeps a narrowed role (confidence in `scan`-inferred *unconfirmed* specs + *declarative* intentional-decisions + backward-compat), documented in spec-manager SKILL.md. No provenance fields added.

**Still open:**
- **`vite-tsconfig-paths` deprecation (testbed, minor).** The testbed's vitest config uses `vite-tsconfig-paths`; Vite now supports `resolve.tsconfigPaths` natively. Testbed-only polish — swap when convenient.

**Resolved — brownfield `scan` dogfooded, mechanism + scale both measured:**
- ~~**`scan` (brownfield import) is undogfooded.**~~ **CLOSED.** The "import this skill into an existing codebase" path is now exercised at two scales:
  - **Mechanism (SP2 dogfood):** a bounded single-area scan (post-locking) produced 5 `proposed` behaviors at the per-observable-behavior grain — additive/no-clobber, **no `.feature` scaffolds** in the code tree, correct executable-vs-declarative classification.
  - **Full repo (2026-06-30, `dogfooding-notes.md` "Full-repo brownfield scan" entry):** coordinator + 7 parallel discovery agents over the whole ~224-file testbed → **~383 candidates (~336 executable behaviors + ~47 declarative decisions, ~88% executable)** across 7 feature areas. Findings: each area is individually manageable (35–63), but the **aggregate is a flood reviewed eagerly** — which is exactly why the architecture never reviews it eagerly. This **confirms SP3 (validate-on-hit) + SP4 (worklists/status) are load-bearing**, classification quality is good, and the one-time cost (~260k tokens / ~65s parallel) is acceptable.
  - **Residual watch-item (minor):** validation-heavy routes emit per-input-branch candidates (one behavior per field-length check) — the main volume driver. If trimming is ever wanted, collapse per-field-validation behaviors into one "validates the payload" behavior per route. Not blocking; logged for if/when the pile is dogfooded for *review ergonomics* (distinct from this *inventory* measurement).

---

## Deferred capabilities (do properly, as their own effort) — continued

### Brownfield over a vendor substrate: ownership-boundary scoping  ← the strongest unaddressed adoption case
- **What:** support the **third brownfield shape** — an existing project where you own only a thin custom layer (e.g. custom auth trees / nodes / scripts) sitting on a large vendor codebase you must **not touch and did not write** (canonical: **Ping / ForgeRock on-prem**). Distinct from the two brownfield shapes already exercised: (greenfield, you own all of it) and (brownfield, you own all of it — the ~383-candidate full-repo scan above). The new requirement is a first-class **ownership boundary**.
- **Why it matters / why deferred:** the current `scan` walks *feature areas* and has no notion of "mine vs the platform." Point a naive full-repo scan at a ForgeRock checkout and the ~383 candidates become **tens of thousands of vendor-code candidates** — pure noise burying the ~dozens that matter. So the vendor-substrate case isn't merely *suboptimal* without scoping — it's unusable. Deferred because it's its own track (config surface + code-graph boundary semantics + a config-as-code question), and the adoption/intent-lifecycle track (SP1–SP5) was the right stopping point.
- **Design sketch (for pickup):**
  1. **Owned-paths config (load-bearing).** A small include/exclude glob config that **both `scan` and `code-graph` respect**: only owned paths get behaviors inferred, scaffolds written, or wrap-up gating. Everything else is frozen. This is the single piece that makes the case usable.
  2. **Vendor code = boundary, not invisible.** `code-graph` still resolves edges *into* the platform (a custom node calls a Ping API) for impact analysis, but does **not** descend into or infer ownership of vendor files. They act as leaf/boundary nodes: referenced by `exercises`, never specced, never scaffolded, never blocking.
  3. **The seam is where the layer earns its keep.** Custom trees encode intent vendor docs never capture ("given the platform authenticates, our node enforces X") and that breaks **silently** on a platform upgrade. Pinned as `accepted` behaviors, a Ping version bump becomes a regression signal — Direction-A surfacing generalizes from "code change → affected behaviors" to "**dependency/platform bump → affected seam behaviors light up**." Likely the strongest single adoption story for the whole layer.
  4. **Stretch — config-as-code.** ForgeRock trees are often JSON/config, not source. A behavior may need to `exercise` a tree-config file rather than a `.ts`; the locator/exercises model currently assumes source files. Probably its own scoped sub-question, flagged not solved.
- **Relationship to the closed brownfield item:** different axis. That item measured review **ergonomics / scale** (you own everything); this is about **scope / ownership** (you own a boundary layer over frozen vendor code). Additive to the current design, not a gap it fails — but required before the vendor-substrate case is tractable.

### ~~Shared resolution-log helper (refactor)~~ — DELIVERED (2026-07-01)
- **Resolved.** Spec: `docs/superpowers/specs/2026-07-01-shared-resolution-log-design.md`. Shipped `resolution_log.py` (`append` / `load(path, label)` / `active(records, keys_of, want)`); `principles.py` (G2), `contradictions.py` (G3), and `drift.py` (P4b) all delegate to it — the three `active_prior` public signatures, RELPATHs, `VERDICTS`, record schemas, and CLIs unchanged. Behavior preservation proven by the three suites passing **byte-unchanged** (11 + 16 + 19); the duplicated latest-wins loop is gone from all three (one copy in `resolution_log.py`). Final opus review: zero findings.
- **What (delivered):** G2 (`principles.py`), G3 (`contradictions.py`), and P4b (`drift.py`) each carried a near-verbatim copy of the resolution-log logic (`append_resolution` / `_load_records` / `active_prior`), differing only in the record key tuple (`(principle, path)` / `(spec, against)` / `(item, path)`). Extracted a shared `resolution_log.py` helper — generic append/load/active keyed by a caller-supplied `keys_of` callback — and refactored all three modules onto it.
- **Why deferred:** the parallelism was a deliberate, spec-approved decision while shipping fast: avoid churning already-shipped and reviewed G2/G3 code while P4b was in flight. Now that there are **three** copies, the DRY debt is real enough to justify a cleanup pass — but the refactor re-touches two already-final-reviewed modules and deserves its own spec → plan → review cycle, not a mid-stream edit.
- **How to pick it up:** brainstorm → spec → plan as its own small sub-project (its own SDD). Keep the three record schemas and key tuples intact (only the storage/query logic is shared); re-run all three suites after the refactor (`principles` 11 tests, `contradictions` 16 tests, `drift` 18 tests) to confirm no regressions.

---

## Phase 5 candidates — real-world / work-laptop enablement (bigger than a Phase-4 leaf)

> Strategic take from the 2026-07-01 discussion. The behavior layer is **functionally complete for the greenfield/TypeScript case** (viva-croatia: Next/TS, vitest observed-unit + static integration + cucumber + full governance G1–G3/P4a/P4b). The next real frontier is **using this at $DAYJOB** (VS Code + GitHub Copilot, polyglot enterprise stack). These are initiative-level, not leaves — each wants its own vision.

### P4c (more language/runner adapters) — DEPRIORITIZED
- **Status:** does **not** serve viva-croatia (uses vitest, not jest; TS, not Python) → not worth building for it. Phase 4 is "done enough" for the TS case.
- **Substrate (mapped 2026-07-01):** only the **vitest** unit runner is actually implemented (V8 → `coverage-final.json` → observed fingerprint). `jest`/`mocha`/`jasmine`/`pytest`/`unittest`/`playwright`/`cypress` are **allow-listed in `KNOWN_ADAPTERS` but stubbed** — `run_behaviors.fingerprint_behavior()` returns `level-deferred` (unknown coverage, never run). Integration = static via code-graph (adapter-agnostic); authoring already handles all (Gherkin scaffold + native link).
- **If ever wanted:** `jest` is **near-free** (emits the same Istanbul `coverage-final.json` vitest's parser already reads — only a new argv builder); `pytest` adds **Python** as a second language (coverage.py `--cov-report=json` → small new parser). Both unit-level, stdlib-parseable. **Observed e2e (playwright/cypress) is NOT P4c** — it needs the deferred **V8+CDP coverage-adapter** ("the big one" above).
- **Design note when picked up:** replace the hardcoded `(state, level, adapter)` if-ladder in `fingerprint_behavior()` with a small **runner-adapter registry** (per adapter: argv builder + coverage parser + observed-confidence), porting vitest onto it behavior-preservingly. But note: the **runner side is not the polyglot blocker — code-graph is** (see Track B).

### Track A — Multi-agent portability (VS Code / GitHub Copilot; skills.sh-style install)
- **What:** freya-devkit is a **Claude Code plugin**, but the work laptop is **VS Code + GitHub Copilot**, where it does not cleanly install. Want a `skills.sh`-style installer that sets it up for **multiple coding agents**.
- **Why it's tractable:** the deterministic **scripts are already portable stdlib-Python CLIs** (no Claude dependency). Only the **orchestration layer** is Claude-specific: `SKILL.md` prose references the Skill tool / `/freya-devkit:*` / `${CLAUDE_PLUGIN_ROOT}` + hardcoded plugin-cache paths; install = the Claude marketplace.
- **Approach sketch:** keep the scripts; make them **self-locating** (drop hardcoded cache paths); provide **per-agent instruction files** + an **installer** that maps the workflow into each agent's convention. Consolidation points: **`AGENTS.md`** (a growing cross-agent standard) and/or **MCP** (Copilot, Cursor, Claude all speak it — a clean home for the deterministic tools). `skills.sh` ≈ that installer + convention-mapping.
- **Effort/risk:** self-contained, **medium**, no core rearchitecting. **Verify first (don't guess):** the *current* state of Copilot extensibility (custom instructions vs MCP vs agent skills — moving fast) and exactly what skills.sh does.

### Track B — Polyglot code-graph substrate (Java + config-as-code) ← the actual wall hit
- **What:** `code-graph` is a **homegrown TS/JS import resolver**. Work projects are **Java + Docker images + Helm charts + Python config + YAML/TOML + `.crt`/`.key` + `bin/`**. code-graph is **blind to all of it** — the user hit this wall immediately on a first VS Code conversion attempt. Two distinct gaps:
  1. **Real languages** (Java, …) need an actual parser (not regex import-scraping).
  2. **Config-as-code / a "resource graph"** — Helm → rendered manifests → images, Dockerfile `COPY`, YAML/TOML wiring, certs/keys/bins — these are **reference/deployment edges, not import edges**. Arguably a **second graph** alongside the code graph, not just more languages in the same one.
- **PIVOTAL FORK (decide first — it gates the whole design):** the plugin's north star is **"stdlib-only Python, zero-install."** Java / tree-sitter / graphify **break that.** Fork = **keep zero-install** (homegrown per-language resolvers — limited, brittle) **vs adopt a dependency** (graphify / tree-sitter — real multi-language, gives up zero-install). Ties to **vision §10** (graphify held in reserve — *Java is exactly the named trigger*) and the **vendor-substrate** entry above (work is *also* brownfield-over-a-platform + polyglot; config-as-code was flagged there as a stretch). **2026-07-12 lean (not final): adopt a dependency — graphify as the *standard* substrate, motivated by unifying the code + behavior graphs; to be brainstormed/researched first (see *Direction updates* at the end of this file).**
- **Why it's the blocker:** everything — behaviors, drift, blast radius — stands on the graph. **Portability without polyglot = installable but blind on Java.** So this is foundational and the **largest** effort.
- **How to pick it up:** its own vision/brainstorm, **opening with the substrate decision** (2026-07-12 lean: graphify-as-standard — see *Direction updates* below), then likely (a) a language-parser abstraction in code-graph, (b) a resource-graph for config/deploy edges, and (c) **framework/stack-agnosticism across the whole plugin** — generalize docs-manager templates, the greenfield/brownfield shape detector, and security heuristics beyond Next/Prisma (see *Direction updates* #3).

### Recommended sequencing (captured for later)
- **Stop Phase-4 leaf-grinding** (P4c deprioritized). Treat **work-laptop enablement** as the next real initiative = **two independent tracks** (A portability, B polyglot). **B (polyglot) is the true blocker**; **A (portability) is more self-contained** and yields *something* runnable sooner.
- **Open questions — updated 2026-07-12 (see *Direction updates* below):** (1) *Resolved* — sequencing is **portability (Track A) before merge, polyglot (Track B) after merge**. (2) The **zero-install fork** now has a recorded **lean toward graphify-as-standard** (a dependency is acceptable), but it is **not yet decided** — it needs its own brainstorm/research first.

---

## Direction updates (2026-07-12 — from user)

Captured from the pre-merge strategy discussion. These refine the Phase-5 tracks and the open questions above. They are **notes for later, not work to do now** — the substrate decision and all polyglot work are explicitly **post-merge**.

1. **Substrate lean: graphify as the *standard* (default) — not a tiered/opt-in backend.** A tiered "homegrown-default + graphify-opt-in" model was proposed; the user **disagrees** and leans toward **making graphify the standard substrate**. Rationale: one real substrate would **tighten the behavior↔code connection** and open the door to **unifying the code graph and the behavior graph into a single graph** (rather than `behavior.json` sitting as a sibling of `graph.json`). This **supersedes** any "zero-install as a hard line" framing — a dependency is acceptable if it makes the graph better. **Not decided:** must be **brainstormed/researched first** (its own vision → spec), because merging the two graphs is a real architectural change (schema, ownership, degradation), and it appears to tension with the deliberate **vision §6** decision to keep `behavior.json` a *sibling* so the code-substrate choice stays decoupled — the research must resolve whether unifying conflicts with that, or subsumes it.

2. **Sequencing confirmed: polyglot (Track B) is *after* the merge.** Pre-merge, merge-gating work = doc-code drift fix + a scoped cleanup + portability (Track A, skills.sh-style). Polyglot / substrate work does **not** gate the merge — it's the next initiative once the cleaned-up, portable release ships. (Resolves open question 1.)

3. **Polyglot scope expands: make the whole plugin framework/stack-agnostic.** The polyglot initiative is not only about `code-graph` parsing more languages — it should make the **entire plugin work for any application repo**, not just Next/Prisma webapps. Concretely: audit and generalize every place the toolkit bakes in Next/Prisma/TS assumptions — **docs-manager's templates** (currently Next/Prisma-flavored), the greenfield/brownfield **shape detector**, **security-scan** heuristics, and any framework-specific coverage/adapter assumptions — so that pointing freya-devkit at an arbitrary stack (Java service, Python API, Go CLI, config-as-code repo) still yields something useful from every skill. This is the same north star as Track B's polyglot substrate, one altitude up: substrate-agnostic *and* framework-agnostic.
