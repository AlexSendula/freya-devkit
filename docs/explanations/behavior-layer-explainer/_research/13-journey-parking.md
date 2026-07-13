# The Journey & What Is Deliberately Parked

*Research brief for the Behavior Layer explainer webapp. Slice: the phase timeline, the mechanism-first sequencing, and the honest status of what is delivered vs. parked.*

Sources read in full:
- `docs/design/behavior-layer/00-vision.md` (§9 Phase decomposition, §10 Deferred/open decisions)
- `docs/design/behavior-layer/parking-lot.md` (the durable backlog)
- `docs/design/behavior-layer/03-adoption-and-intent-lifecycle.md` (SP-track framing, first 60 lines)
- `git log --oneline main..HEAD` → **135 commits**

---

## 1. One-paragraph orientation for a newcomer

The Behavior Layer makes **intended behavior** a first-class, executable, blast-radius-aware artifact. Before this branch, freya-devkit was a strong *reverse-sync engine* (after code changes it keeps a dependency graph, docs, specs, and security findings in sync) but had no way to capture *what the system is supposed to do* in an executable, intent-driven, design-time-visible form. The whole initiative was built on one guiding rule — **mechanism-first, dogfood-as-you-go** — and it landed as a sequence of phases (1 → 2 → 3/adoption → 4 → a shared refactor), each dogfooded on a real testbed project as it was built rather than building horizontal infrastructure or governance ahead of evidence. This brief covers that journey and, critically, the **parking lot**: the work deliberately deferred so it gets done *properly, not on the go*.

---

## 2. The phase timeline (vision §9)

The ordering is **mechanism-first**: the central behavior loop is validated by **dogfooding Phase 1 on a real project** as it is built, rather than building horizontal infrastructure or governance ahead of evidence. Each phase gets its own **spec → plan → implementation** cycle.

### Phase 1 — Traceability MVP
Verbatim scope (§9.1): "formalize spec↔behavior identity and the `proposed/accepted/quarantined/deprecated` lifecycle; support Gherkin **plus one native adapter**; deterministic integrity checks; run *accepted* behaviors at wrap-up and **block only deterministic failures**. Directory layout left intact. Detailed in `01-phase-1.md`."

Commit anchors (bottom of the arc):
- `ae0bc11 feat(spec-manager): extended spec format with behaviors`
- `aed2046 feat(spec-manager): Behavior entity + lifecycle validation`
- `406071c feat(spec-manager): two behavior adapters (Gherkin scaffold + native link)`
- `e6a02f8 feat(spec-manager): Tier-1 deterministic link-integrity checks (verify)`
- `68a5c03 feat: intent classification review queue + lifecycle-aware wrap-up staging`

### Phase 2 — Impact indexing
Verbatim scope (§9.2): "explicit code links first; add *observed* per-test coverage as an optional enhancer with provenance + freshness; detect stale fingerprints; **measure false-positives and runtime**; introduce `behavior.json` only once the edge model is understood. → unlocks **Direction A**, then **B**."

This is where the two new skills are born and where `behavior.json` (the sibling to `graph.json`) appears. Commit anchors:
- `e340712 feat(behavior-runner): run unit behavior via vitest + emit observed fingerprint`
- `900b324 feat(behavior-runner): static integration fingerprint via code-graph closure`
- `8692127 feat(behavior-graph): Direction A (blast-radius intersect) + CLI`
- `bb92dac feat(behavior-graph): build (project+run+merge) + Direction B`
- `9736425 feat(behavior-graph): --check (incremental Direction-A regression gate)`
- `759105a feat(wrap-up): Phase 3.5 runs affected behaviors via behavior-graph; F5 never-synced guard`

**Measured result** (parking-lot "Measurement (§6)", Plan 5, `2a5a0ec`): "selective (FP 0 on the testbed set), fast (incremental `--check` 0.07 s when nothing affected)."

### Phase 3 (track A) — Adoption & Intent Lifecycle + the SP1–SP5 track
The vision earmarked "Phase 3" for *governance*. But adoption came first — verbatim from `03-adoption-and-intent-lifecycle.md` §Relationship-to-governance: **"you cannot govern intent you have not captured."** The core idea (§2): **"decouple inference from validation"** — *"Inference is cheap and can be done up front; validation is the scarce resource and must be spent lazily, in the flow of work."*

The lifecycle gets a **new middle state** — `confirmed` inserted between `proposed` and `accepted` (§3): "Confirming intent and writing a test are **two different steps**." The state table (verbatim column facts):
- `proposed` — drafted/inferred; intent **not** confirmed; no test; not in blast radius; does not gate wrap-up.
- **`confirmed`** *(new)* — a human confirmed the intent is correct; **test owed**; not yet a test; **yes, via static fingerprint** (if `entry` declared) — advisory; gates wrap-up: no (advisory).
- `accepted` — confirmed **and** a real, passing linked test exists; in blast radius (observed/static); **gates wrap-up: yes** (deterministic block on `test-failed`).
- `quarantined` / `deprecated` — as today.

This track shipped as **SP1 through SP5** (each an SDD: design → plan → implementation → dogfooding note), commit anchors:
- **SP1** confirmed lifecycle state: `ea2fe0f`, `af51f63`, `3521978`, `87af3c9` (dogfooding note), `c53f548` (review).
- **SP2** onboarding & bootstrap (greenfield/brownfield detector, `bootstrap` command): `99d1a6d feat(spec-manager): project_shape.py`, `ce91273 feat(spec-manager): bootstrap command — unified greenfield-aware onboarding`, `619ae7c` (dogfooding note).
- **SP3** validate-on-hit: `596af12 feat(behavior-graph): --surface validate-on-hit query`, `76be813 feat(wrap-up): Phase 3.5 validate-on-hit surfacing (advisory, skippable)`, `38ce58a` (dogfooding note).
- **SP4** status & backlog: `d67eb23 feat(status): collect_status.py — aggregate buckets + render BACKLOG.md`, `631e779 feat(status): status skill (command + worklists); wrap-up refreshes BACKLOG.md`, `f28fcbc feat(codebase-security-scan): emit structured findings.json index + schema`.
- **SP5** security ↔ behavior cross-reference: `8021209 feat(codebase-security-scan): cross-reference accepted behaviors as verified intentional evidence`, `cbd4f33 feat(behavior-graph): --covering query`, `93ca30f` (dogfooding note).

### Phase 4 — Expansion (ADR + drift)
Verbatim scope (§9.4): "more language/runner adapters; ADR support + ADR-aware conflict checks (delivered — P4a); declarative-drift checks (delivered — P4b); calibrated model enforcement *if the evidence supports it*."

Before P4a/P4b, the **governance track G1–G3** landed (the *actual* Phase 3 scope, done after adoption):
- **G1** declared-intent records (`INTENT-NNN`): `545179b feat(spec-manager): verify_intent — deterministic declared-intent gate (G1)`, `17f9441 feat(spec-manager): intent.py — INTENT-NNN authoring helper (G1)`, `d7c2dec` (wire into verify + wrap-up).
- **G2** principle enforcement: `f6bb2e7 feat(spec-manager): principles.py — list/resolve/prior helpers (G2)`.
- **G3** contradiction checks (advisory, Tier-2): `6601532 feat(spec-manager): contradictions.py — context/resolve/prior helpers (G3)`.

Then Phase 4:
- **P4a** ADR support + ADR-aware conflict checks: `ca4ef16`, `6a7ede6` (design), `70f4353 feat(spec-manager): adr.py authoring`, `fff1170 feat(spec-manager): G3 build_context includes active ADRs (P4a)`, `d2ebd54 build_adr_context — changed-ADR symmetry`. **Scoping decision reversed to always-global** — G3 compares a changed spec against *all accepted* ADRs, **no category scoping** ("a research-backed reversal of an `applies_to`-by-category sketch, to avoid the silent-miss failure mode"); authority order **principle > ADR > spec**.
- **P4b** declarative-drift check: `e953711` (design), `25f8275 feat(spec-manager): drift.py gaps`, `f47edbf drift.py gather — blast-radius context`, `aaf0a13 docs(wrap-up): declarative-drift check as Phase 3.5 step 7 (P4b)`. It is "a wrap-up step-7 check, blast-radius-scoped over `related_code` (code-anchored, not always-global), resolve-to-proceed."

### The shared refactor (top of the arc, 2026-07-01)
G2 (`principles.py`), G3 (`contradictions.py`), and P4b (`drift.py`) each carried a near-verbatim copy of the resolution-log logic. Once there were **three** copies, the DRY debt justified a cleanup pass — but "the refactor re-touches two already-final-reviewed modules and deserves its own spec → plan → review cycle, not a mid-stream edit." Delivered:
- `15afce1 docs(refactor): shared resolution-log helper design`
- `10fe43a feat(spec-manager): resolution_log.py — shared append-only log core`
- `c4222e5 refactor(spec-manager): principles.py delegates to resolution_log (G2)`
- `83517bd refactor(spec-manager): contradictions.py delegates to resolution_log (G3)`
- `1c55f33 refactor(spec-manager): drift.py delegates to resolution_log (P4b)`
- `298462b docs(behavior-layer): mark shared resolution-log refactor delivered`

Shipped `resolution_log.py` with the public surface `append` / `load(path, label)` / `active(records, keys_of, want)` — "generic append/load/active keyed by a caller-supplied `keys_of` callback." Behavior preservation proven by the three suites passing **byte-unchanged (11 + 16 + 19)**; "Final opus review: zero findings." (Note: one line says the drift suite is 19, another pickup note says re-run `drift` 18 tests — see `unverified`.)

The very top commit is `2095b48 docs(behavior-layer): parking-lot — Phase 5 work-laptop enablement (portability + polyglot) + P4c deprioritized`.

---

## 3. Why Phase 0 vertical proof was deliberately dropped (vision §9)

Verbatim: **"A separate, staged Phase 0 vertical proof was considered and deliberately dropped. Instead of proving the loop in isolation first, we fold that validation into Phase 1's first real use on the testbed. This is a conscious risk trade: some Phase 1 schema, lifecycle, and adapter choices are made provisionally and corrected in contact with reality."**

The rationale is the whole mechanism-first thesis: rather than build a throwaway isolated proof, the team validated the central behavior loop *by dogfooding Phase 1 on a real project as it was built* — accepting that some early schema/lifecycle/adapter choices would be provisional and corrected against reality (the "F"-numbered friction findings in `dogfooding-notes.md` are that correction record).

---

## 4. The decoupled, standalone work (shipped early)

Verbatim (§9): "the `knowledge-base/` IA migration (`docs/ → knowledge-base/`, `project/ → reference/`, `security-reports/ → security/`, `.code-graph/ → .graph/`, add `principles.md` + empty `decisions/`) shipped as its **own** PR with no behavior changes — done **early** (cheapest while the repo is small) and never entangled with validating the behavior loop." Per §5, "The behavior work never depended on that migration; the phases simply now run against the `knowledge-base/` layout."

---

## 5. Vision §10 — deferred / open decisions

Three items, verbatim in essence:

1. **Code substrate & its capability contract.** Whether to keep homegrown code-graph, adopt [graphify](https://github.com/safishamsi/graphify) ("symbol-level, multi-language, tree-sitter, confidence-scored — philosophically aligned"), or borrow its ideas. Independent of that choice, the substrate must satisfy a **capability contract** before governance depends on it: "resolve imports (incl. TypeScript path aliases — the current regex resolver treats non-relative imports as external and silently drops them), stable file identity, language coverage, per-edge confidence, freshness, changed-file impact, and an explicit **'coverage unknown'** signal instead of a falsely-small blast radius." *(Largely addressed in-branch by the code-graph substrate fix — see `d423299 fix(code-graph): resolve tsconfig path aliases + cwd-independent imports` — but graphify stays in reserve.)*

2. **Frontmatter substrate.** "The current spec frontmatter parser is hand-rolled and silently discards inline-array fields (e.g. `tags: [a, b]`). Replace it with a real YAML parser + schema validation **before** the schema is extended."

3. **ADR capture machinery.** "Its own phase (§9, Phase 4); Tier-2 conflict checks stay ADR-blind until it ships. **(delivered — P4a, see docs/superpowers/specs/2026-07-01-p4a-adr-support-design.md)**"

---

## 6. Parking lot — DELIVERED vs. PARKED

### Delivered (struck through in the source)
- **ADR capture machinery (Phase 4) → DELIVERED (P4a, 2026-07-01).** Delivered: "the `ADR-NNN` format + lifecycle, `adr.py` (`new`/`list`/`verify`/`load_adrs`), `frontmatter.ADR_SCHEMA`, the G3 `build_context` ADR gather + the `build_adr_context` changed-ADR symmetry, and wrap-up wiring (`adr verify` hard-block + ADR-aware step 6)."
- **Shared resolution-log helper (refactor) → DELIVERED (2026-07-01).** Shipped `resolution_log.py` (`append` / `load(path, label)` / `active(records, keys_of, want)`).
- **`scan` (brownfield import) → CLOSED.** Exercised at two scales; see §8 numbers.
- Several carried findings resolved: **F3** (`init` drops `.gitkeep`, `d65d5b5`), **F5** (never-synced guard, `759105a`), the **`reason` discriminator**, the **§6 measurement**, **`level`/`entry` schema validation** (`bcaa8c9`), and **F4** — "certainty for agent-drafted-but-human-confirmed intent — **dissolved, not redesigned**" (intent confidence is now carried by lifecycle `state`; `accepted` = human-confirmed).

### Parked — operational (do before any release)
- **Revert the local-dev plugin symlink.** The published plugin cache `~/.claude/plugins/cache/freya-devkit/freya-devkit/0.1.0` is currently a **symlink to the dev repo root** (backup at `…/0.1.0.pre-phase1-backup`) so `/freya-devkit:*` runs branch code. "This is a dogfooding hack, not a real install." Revert = remove the symlink and `mv 0.1.0.pre-phase1-backup 0.1.0`. Mirrors dogfooding **F1/F2**; recorded in persistent memory `project_phase1-dogfooding`.
- **Publish the real freya-devkit release.** GitHub `AlexSendula/freya-devkit` "is still at the pre-Phase-1 commit; all behavior-layer work is local on `feat/behavior-layer`." Cut a new version (new skills `behavior-runner`/`behavior-graph`, updated `code-graph`/`spec-manager`/`wrap-up`) after merge.
- **Testbed: gitignore `coverage/`.** Vitest writes `coverage/` in the testbed; not gitignored. Minor.

### Parked — deferred capabilities (do properly, as their own effort)
- **Per-framework observed-coverage adapter (V8 + CDP)** — "the big one." Real *observed* `TEST → CODE` coverage at the integration/e2e level, captured by launching the app under `--inspect` and collecting V8 coverage over the **Chrome DevTools Protocol** ("the actual worker is at inspector **port + 1**"), then remapping bundled `.next` output to source via source maps. Reference impl: **`nextcov`** (stevez/nextcov). Deferred because "framework-specific (CDP port dance + source-map remap; `nextcov` is Next-only; **Next 16 + Turbopack support unverified**)." Baseline meanwhile: static via code-graph (`source: static`). **Istanbul/`babel-plugin-istanbul` is a dead end on App Router (breaks Server Actions) — do not pursue it.** See **F11**.
- **Tracing adapter** — for apps that already emit structured logs or OpenTelemetry traces, derive observed `exercises` edges from the trace, "*zero* instrumentation added by us." Deferred (app-specific).
- **Graphify (code-graph substrate fallback)** — homegrown resolver was fixed ("0→607 internal edges on the testbed"). "Don't adopt a dependency we don't need yet." Trigger to revisit: if homegrown keeps accruing edge cases — known gaps are **`extends` chains** in tsconfig, **per-edge confidence**, and **monorepos**.
- **Full E2E for the happy-path login (BEH-001)** — "successful passkey login" needs a WebAuthn assertion signed by an authenticator (Playwright + virtual authenticator). "It stays `proposed` until then."
- **Brownfield over a vendor substrate: ownership-boundary scoping** — "the strongest unaddressed adoption case." Support the **third brownfield shape**: you own only a thin custom layer over a large vendor codebase you must not touch (canonical: **Ping / ForgeRock on-prem**). Needs a first-class **ownership boundary** (owned-paths include/exclude glob config respected by both `scan` and `code-graph`; vendor code = boundary leaf node, resolved-into but never specced/scaffolded/blocking). "Point a naive full-repo scan at a ForgeRock checkout and the ~383 candidates become **tens of thousands of vendor-code candidates**." Direction-A generalizes: "**dependency/platform bump → affected seam behaviors light up**" — "Likely the strongest single adoption story for the whole layer." Stretch: config-as-code (ForgeRock trees are JSON/config, not source).

### Parked — Phase 5 candidates: real-world / work-laptop enablement
Strategic take from the **2026-07-01 discussion**. The behavior layer is **"functionally complete for the greenfield/TypeScript case"** (viva-croatia: Next/TS, vitest observed-unit + static integration + cucumber + full governance G1–G3/P4a/P4b). The next frontier is **using this at $DAYJOB** (VS Code + GitHub Copilot, polyglot enterprise stack).

- **P4c (more language/runner adapters) — DEPRIORITIZED.** "Does **not** serve viva-croatia (uses vitest, not jest; TS, not Python) → not worth building for it. Phase 4 is 'done enough' for the TS case." Substrate reality (mapped 2026-07-01): **only the vitest unit runner is actually implemented** (V8 → `coverage-final.json` → observed fingerprint). "`jest`/`mocha`/`jasmine`/`pytest`/`unittest`/`playwright`/`cypress` are **allow-listed in `KNOWN_ADAPTERS` but stubbed**" — `run_behaviors.fingerprint_behavior()` returns `level-deferred`. If ever wanted: `jest` is **near-free** (same Istanbul `coverage-final.json`, only a new argv builder); `pytest` adds Python (coverage.py `--cov-report=json`). **Observed e2e (playwright/cypress) is NOT P4c — it needs the deferred V8+CDP coverage-adapter.** Design note: replace the hardcoded `(state, level, adapter)` if-ladder in `fingerprint_behavior()` with a small **runner-adapter registry**. "But note: the **runner side is not the polyglot blocker — code-graph is** (see Track B)."

- **Track A — Multi-agent portability (VS Code / GitHub Copilot; skills.sh-style install).** freya-devkit is a **Claude Code plugin**, but the work laptop is **VS Code + GitHub Copilot**, where it does not cleanly install. Why tractable: "the deterministic **scripts are already portable stdlib-Python CLIs** (no Claude dependency). Only the **orchestration layer** is Claude-specific" (`SKILL.md` prose references the Skill tool / `/freya-devkit:*` / `${CLAUDE_PLUGIN_ROOT}` + hardcoded plugin-cache paths). Approach: make scripts **self-locating**; provide **per-agent instruction files** + an **installer**. Consolidation points: **`AGENTS.md`** (a growing cross-agent standard) and/or **MCP**. Effort/risk: "self-contained, **medium**, no core rearchitecting." Verify-first: the current state of Copilot extensibility and exactly what skills.sh does.

- **Track B — Polyglot code-graph substrate (Java + config-as-code) — "the actual wall hit."** `code-graph` is a **homegrown TS/JS import resolver**. Work projects are "Java + Docker images + Helm charts + Python config + YAML/TOML + `.crt`/`.key` + `bin/`" — code-graph is **blind to all of it** ("the user hit this wall immediately on a first VS Code conversion attempt"). Two gaps: (1) real languages need an actual parser (not regex import-scraping); (2) **config-as-code / a "resource graph"** — "reference/deployment edges, not import edges… Arguably a **second graph** alongside the code graph."

- **PIVOTAL FORK (decide first — it gates the whole design):** "the plugin's north star is **'stdlib-only Python, zero-install.'** Java / tree-sitter / graphify **break that.** Fork = **keep zero-install** (homegrown per-language resolvers — limited, brittle) **vs adopt a dependency** (graphify / tree-sitter — real multi-language, gives up zero-install)." Ties to vision §10 (graphify held in reserve — "*Java is exactly the named trigger*"). "Portability without polyglot = installable but blind on Java." So Track B is foundational and the **largest** effort.

- **Recommended sequencing:** "Stop Phase-4 leaf-grinding (P4c deprioritized). Treat work-laptop enablement as the next real initiative = two independent tracks (A portability, B polyglot). **B (polyglot) is the true blocker; A (portability) is more self-contained** and yields *something* runnable sooner." Open questions pending user decision: (1) which track first; (2) **the zero-install fork** — "open to a dependency (tree-sitter/graphify) for real Java support, or is zero-install a hard line to design around?"

---

## 7. P4d — calibrated model enforcement (evidence-gated)

Listed as a remaining Phase-4 leaf (parking-lot): **"P4d (calibrated model enforcement — evidence-gated)."** Rooted in vision §8 "Block vs. warn": model findings (Tier-2 contradictions) "must be *acknowledged*, but never hard-block on certainty alone… model-confidence is promoted to a hard gate **only after** its false-positive rate is measured on a real project and shown acceptable." A model's "high certainty" is not a calibrated probability; blocking on it "would train people to rubber-stamp 'declare intent' to escape noise." So P4d is deliberately gated on measured evidence that does not exist yet.

---

## 8. The measured numbers (verbatim — do not approximate)

- Commit arc: **135 commits** on `main..HEAD`.
- Phase 2 measurement: **FP 0** on the testbed set; incremental `--check` **0.07 s** when nothing affected.
- Code-graph substrate fix: **0→607 internal edges** on the testbed.
- Full-repo brownfield scan (2026-06-30): coordinator + **7 parallel discovery agents** over the **~224-file** testbed → **~383 candidates (~336 executable behaviors + ~47 declarative decisions, ~88% executable)** across **7 feature areas**; each area individually manageable (**35–63**); one-time cost **~260k tokens / ~65s parallel**.
- SP2 dogfood bounded single-area scan: **5 `proposed` behaviors**, "additive/no-clobber, **no `.feature` scaffolds** in the code tree."
- Resolution-log refactor suites: **11 + 16 + 19** passing byte-unchanged (`principles` 11, `contradictions` 16; drift stated as both 19 and 18 — see unverified).
- Vendor-substrate warning: a naive ForgeRock scan turns ~383 candidates into "**tens of thousands** of vendor-code candidates."

---

## 9. The honest status (the punchline)

Two grounded facts to close on:
1. **The original `00-vision` is essentially delivered.** §9 Phase 1–4 are all shipped (Traceability, Impact indexing, the adoption SP-track, Governance G1–G3, P4a ADR, P4b declarative-drift), plus the shared refactor. §10's ADR machinery is delivered; the substrate capability contract is largely satisfied by the code-graph fix (graphify still in reserve). What remains are *deliberately parked leaves* (P4c deprioritized, P4d evidence-gated) and the *new frontier* (Phase 5 work-laptop enablement).
2. **`feat/behavior-layer` is unmerged by standing decision.** Per parking-lot: "all behavior-layer work is local on `feat/behavior-layer`"; the operational parking items (revert the dev symlink, publish the real release) are explicitly "do before any release" and gated on the branch merging. The behavior layer is functionally complete for the greenfield/TypeScript case but has not been cut into a release.

---

## 10. Newcomer framing tips

- Lead with the **mechanism-first / dogfood-as-you-go** thesis — it explains *every* sequencing choice (why Phase 0 was dropped, why adoption preempted governance, why P4d waits for evidence, why graphify stays parked).
- The recurring pattern in the parking lot is **"do it properly, as its own effort"** — deferral here is a quality decision, not neglect. Each parked item states *what / why deferred / how to pick it up*.
- The single sharpest forward tension for the explainer: the **zero-install fork** (stdlib-only Python vs. adopting tree-sitter/graphify for real Java). It is the one open decision that gates the largest remaining effort.
