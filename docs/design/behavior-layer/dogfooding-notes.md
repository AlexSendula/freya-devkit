# Phase 1 — Dogfooding Notes & Friction Log

**Started:** 2026-06-28
**Testbed:** `/Users/main/Documents/projects/viva-croatia-testbed/` (isolated snapshot of the Viva Croatia production webapp — production at `/Users/main/Documents/areas/viva-croatia/webapp/` is **off-limits**, never touch it).
**Purpose:** Validate Phase 1 (Traceability MVP) against a real project, per vision §9 ("mechanism-first, validated by dogfooding"). Capture provisional-choice corrections and friction as we go.

---

## Testbed facts (Viva Croatia)

- **Stack:** Next.js 16 (App Router) + React 19 + TypeScript, Prisma 7 (SQLite `dev.db`/`cms.db`), NextAuth 4 (`auth.ts`), pnpm, Tailwind + shadcn/ui, next-intl (`messages/`). CMS-style web app.
- **Tests: NONE.** No test files, no runner in `devDependencies`, no test script. → exercises the "runner detection reports **none**" case, and the greenfield-adoption path.
- **Notable for dogfooding:**
  - Uses `@simplewebauthn` (passkeys) — matches the vision's running example; the natural **first spec is passkey auth**.
  - TS path alias `@/* → ./*`, used pervasively (`@/lib/...`, `@/components/...`). This is a **direct stress test of the code-graph substrate debt** (vision §10): `graph_ops.py:198/857` treats non-relative imports as `external` and drops them. Relevant when Phase 2 blast radius lands — expect under-counted dependencies here.
- **Git baseline:** fresh repo, initial commit `b4fb973` ("import viva-croatia webapp snapshot…"). 307 tracked files. node_modules/.next/.git/.env/.env.local excluded from the snapshot.

## Local-dev install setup (so branch code runs via `/freya-devkit:*`)

The installed plugin was published GitHub `AlexSendula/freya-devkit` @ `ba8470b` (v0.1.0) — **pre-Phase-1**. All Phase 1 work is local-only on branch `feat/behavior-layer` (not pushed, not published). To dogfood the real invocation path:

- Backed up `~/.claude/plugins/cache/freya-devkit/freya-devkit/0.1.0` → `0.1.0.pre-phase1-backup`.
- Symlinked `…/0.1.0` → `/Users/main/Documents/projects/freya-devkit` (the repo root = plugin root).
- Added `.in_use/` to the repo `.gitignore` (plugin runtime marker would otherwise pollute the working tree via the symlink).
- **Reverse it with:** `rm` the symlink, `mv 0.1.0.pre-phase1-backup 0.1.0` (or reinstall from GitHub).

---

## Friction log (findings → provisional-choice corrections)

### F1 — No dev→install loop
Branch work cannot be exercised through `/freya-devkit:*` at all: the Skill tool loads the published cache, which tracks GitHub, which is at the pre-Phase-1 commit. There is no documented "run the local working tree as the plugin" path. **Action:** symlink local-dev install (done above); should be documented in CONTRIBUTING and ideally scripted.

### F2 — Plugin cache does not hot-reload in a running session
After symlinking the cache to the branch on disk, the **current** session still served the stale SKILL.md (verified: `/freya-devkit:spec-manager help` returned `/docs/specs/`-era content). The session caches the plugin at startup. **A session restart is required** to pick up local-dev changes. **Action:** note in CONTRIBUTING; factor into any dogfooding workflow (edit → restart → test).

### F3 — `init` leaves spec category dirs that won't survive Git
`init` creates 7 empty spec category dirs (`specs/{auth,api,data,features,infra,integration,ui}/`). Git doesn't track empty dirs, so on commit they vanish — only `specs/README.md` and `decisions/README.md` (and `principles.md`) survive. The design deliberately gave `decisions/` a README *so its empty home survives Git* (see `decisions-readme.md`), but the spec category subdirs got no equivalent `.gitkeep`/README. **Action:** either drop a `.gitkeep` in each category dir during `init`, or create category dirs lazily when the first spec lands there. Decide which is the intended model.

### N1 — (not a bug) project + runner detection is solid
`detect_project.py` on the testbed correctly returned `runtime: nodejs/pnpm`, `framework: nextjs`, `database: sqlite/prisma`, docker infra, and `test_runners: {runners: [], evidence: []}` — i.e. the "no runner" case is reported cleanly and loudly, as Phase 1 intends. There is no `project_type` key (an earlier worry); detection is richer than that.

### Process note — `init` is fully model-driven (no script, no README template)
`init` has no script and no canonical `specs/README.md` template file; the agent hand-authors both the directory creation and the index README, so two runs can diverge in format. The `index` command regenerates the README but has nothing to anchor its structure to. **Action (minor):** consider a `references/specs-readme-template.md` so the index format is stable across runs/agents.

### F4 — `create` vs `scan` blur: certainty model doesn't fit "agent-drafted, human-confirmed"
SKILL.md `create` says "Set certainty to 100 (user-created)." In real use the agent **drafted** SPEC-001 from the code and the human **confirmed** the intent/decisions — a hybrid of `create` and `scan`. Neither "100 = user wrote it" nor a low scan score fits. We set `certainty: 90`. **Action:** define how certainty is assigned when intent is agent-drafted but human-confirmed (and whether that path is `create`, `scan`, or a third mode).

### N2 — (validated) the full Phase 1 loop works on a real project
End-to-end on the testbed (SPEC-001 Passkey Login, 3 behaviors):
- **Parser:** `search_specs.py --id SPEC-001` round-tripped the inline `tags: [...]` array (the original silent-drop bug class), the 6-path `related_code` block sequence, and all 3 list-of-maps `behaviors` — substrate proven on real content.
- **Adapter:** `adapters.py gherkin-scaffold` emitted a correct `features/auth/passkey-login.feature` (`@SPEC-001` on Feature, `@BEH-NNN` per scenario, TODO markers); slugs matched the spec locators.
- **verify (clean):** `verify_links.py` → OK / exit 0 with all behaviors `proposed`.
- **verify (gate fires):** flipping BEH-001 → `accepted` (still a TODO scaffold) produced exactly one `accepted-but-scaffold` error / exit 1, **scoped to BEH-001** — BEH-002/003 (proposed scaffolds in the same file) were correctly not flagged (per-scenario scoping, commit 54d6eb3). Reverted to `proposed` → OK again.

## Progress

Resume-checklist steps **1–4 done**: branch code loads ✓; `init` (knowledge-base layout, runner detection = none) ✓; `create` SPEC-001 with proposed behaviors + intentional decisions ✓; Gherkin adapter scaffold ✓; deterministic `verify` (pass + gate) ✓.

**Not yet done — step 5 (close the loop):** no behavior is `accepted` yet, because that requires a real test. Options for the testbed (no test tooling installed): (a) stand up cucumber-js + step definitions for a Gherkin behavior, or (b) **native adapter** — write one real test (e.g. a Playwright E2E for "successful passkey login", or a unit test on a `lib/webauthn.ts` function), link it by `locator`, mark the behavior `accepted`, and run wrap-up so execution + deterministic-only blocking fire. Native adapter (b) is the cheaper, more representative path and also exercises the **second adapter** (Phase 1 acceptance criterion).

### F5 — wrap-up on a freshly-`init`'d project triggers full-codebase generation
wrap-up Phases 2–4 call `docs-manager update` / `spec-manager update` / `codebase-security-scan update`. With no prior tracking files, each falls back to a **full** scan/generation across the whole codebase — heavy, and unrelated to the change just made. wrap-up implicitly assumes you've been using the tools incrementally. **Action:** wrap-up (or the `update` commands) should detect "never-synced" and either no-op with a clear message or require an explicit first `scan`, rather than silently doing a full generation. *(This session we scoped wrap-up to the behavior-relevant phases — 1, 3.5, 5 — and deferred 2–4.)*

### F6 — code-graph `--build` is interactive; cannot run unattended
`graph_ops.py --build` prompts on stdin to classify ambiguous directories ("Uncertain classification for 'app/[lang]/' … Your choice (1 or 2):") and prints "AI classification not available in CLI mode." On a real Next.js project this fires for many `app/` subdirs and **hangs** — which means wrap-up's Phase 1 (`code-graph update`) cannot complete unattended. It also prompted to classify its **own** generated `knowledge-base/.graph/` output dir. **Action:** non-interactive/CI mode with a safe default (and auto-exclude `.graph/`, `node_modules`, etc.); when invoked by an agent the agent can answer, but as a pipeline subprocess it deadlocks.

### F7 — **(critical)** path aliases ⇒ 100% external, internally-empty graph, reported silently
After completing the build (auto-answering "source"), the graph for the testbed had **229 files, 1052 import edges — and 0 internal edges; all 1052 tagged `external:`.** Cause: every internal import uses the `@/` alias (Next.js standard; `tsconfig` `paths: {"@/*": ["./*"]}`), and the resolver (`graph_ops.py:198/857`) treats non-relative imports as external and drops them. `--dependencies app/api/auth/passkey/authenticate/route.ts` → `[]` despite three `@/lib/*` imports.
- This is exactly the vision §10 capability-contract gap, now confirmed on real code.
- It is **worse than incomplete**: it returns an empty blast radius *as if complete*, violating the "coverage-unknown, never silent" principle (§6). No "unknown" signal is emitted.
- **Impact:** for any alias-using TS project (the majority), code-graph impact analysis is uniformly empty → spec/docs impact updates and **all of Phase 2's blast radius ride on nothing**. This is a hard prerequisite to fix (resolve `tsconfig`/`jsconfig` `paths`, or adopt graphify) before Phase 2 governance can be trusted. Promote §10 from "deferred/open" to "blocking for Phase 2."

### F8 — generated `knowledge-base/.graph/` is not git-ignored
The renamed generated cache `knowledge-base/.graph/` (was `.code-graph/`, which *was* ignored) has no gitignore coverage in adopting projects, so it would be committed as an artifact. It's a regenerable cache (and currently a broken one, per F7). **Action:** `init` should add `knowledge-base/.graph/` to the project `.gitignore` (or wrap-up should refuse to commit it).

## Progress (cont.)

Resume-checklist **step 5 partially exercised** via a scoped wrap-up:
- **Phase 0 staging (validated):** all changes classify as **artifacts** — the `proposed`/TODO `features/auth/passkey-login.feature` scaffold → artifacts (not code), `knowledge-base/` → artifacts; **no code commit**. The behavior-aware staging rule holds on real content.
- **Phase 1 code-graph (ran, broken):** see F6/F7 — built but internally empty.
- **Phase 3.5 verify (green):** `verify_links.py` OK / exit 0; **0 accepted behaviors → nothing to execute** (the deferred execution path, consciously skipped).
- **Phases 2–4 (deferred):** see F5.
- **Phase 5 commit:** held pending a decision on the broken `.graph` artifact (F8) — do not commit junk as if valid.

### F9 — code-graph relative-import resolution is cwd-sensitive (silently drops)
While verifying F7: `_resolve_import_path` resolves relative imports via `(from_dir / import_path).resolve()` (relative to the **process cwd**) then `relative_to(project_dir)`. When the tool is invoked with `--dir X` from a different cwd — exactly how wrap-up and the testbed build run it — every relative import fails `relative_to` and is **dropped entirely** (not even tagged external). Proven with a 3-file fixture: built from a foreign cwd, `a.ts`'s `./b` → `[]`; rebuilt with cwd==projectdir → `['src/b.ts']`. Compounds F7 (the testbed's 0/1052 internal was *both* bugs). **Action:** resolve relative imports against `project_dir` + the file's own path, independent of cwd.

### Verified verdict on F7/F9 — the engine is ORIGINAL, not introduced by this work
`git diff ba8470b..HEAD -- skills/code-graph/scripts/graph_ops.py` = 2 lines, both the `docs/.code-graph → knowledge-base/.graph` path rename. `_resolve_import_path` is unchanged since published v0.1.0. There is **no separate "new" graph engine** — the blast-radius/impact feature *is* the original code-graph (the Phase 2 behavior graph is not built yet). Conclusion: the impact feature has been broken for path-alias projects since v0.1.0; dogfooding merely exposed it on the first real alias-using project. **§10 (substrate capability contract) is promoted from "deferred/open" to BLOCKING for Phase 2.**

#### Fix scope to unblock Phase 2 (code-graph substrate)
1. **tsconfig/jsconfig `paths` + `baseUrl` resolution** (fixes F7) — resolve `@/*`-style aliases before the external fallback.
2. **cwd-independent resolution** (fixes F9) — resolve against `project_dir`, not process cwd.
3. **non-interactive build mode + auto-exclude generated dirs** (fixes F6).
4. **emit an explicit `unresolved`/`coverage-unknown` signal** instead of silently dropping (vision §6) — so "no deps" is distinguishable from "couldn't resolve."
5. (ops) **`init` should git-ignore `knowledge-base/.graph/`** (fixes F8).
Open decision: patch the homegrown resolver (above) vs. adopt graphify (§10).

### RESOLVED — F6/F7/F8/F9 fixed in code-graph (TDD)
Implemented per `code-graph-substrate-fix.md` with `skills/code-graph/scripts/test_graph_ops.py` (8 cases, written first). Changes in `graph_ops.py`:
- **F7** tsconfig/jsconfig `paths`+`baseUrl` alias resolution (string-aware JSONC parser — a naive regex stripper mis-read `/*` in `@/*` and `*/` in `**/*.ts`; caught by a TDD regression test before shipping).
- **F9** relative imports anchored to `project_dir` (cwd-independent).
- **§6** imports tagged `external:` vs `unresolved:` (no silent drop).
- **F6** `--non-interactive` (auto when no TTY) defaults uncertain dirs to source; no stdin prompts.
- **F8** build writes a self-ignoring `knowledge-base/.graph/.gitignore` (`*`).

**Verified on the testbed:** rebuild went from **0 internal / 1052 external** to **607 internal / 488 external / 0 unresolved**; the authenticate route now resolves `lib/webauthn.ts`, `lib/rate-limit.ts`, `lib/audit.ts`, `lib/prisma.ts`. SKILL.md updated. **§10 capability-contract (alias resolution + coverage-unknown signal) now met for TS/JS — Phase 2 unblocked.** `extends` chains and per-edge confidence remain out of scope (graphify fallback if needed).

### F10 — **(critical, design-shaping)** in-process route-handler import is not viable; behavior tests must drive the app over its real interface
Closing the loop (Plan 1) first tried the planned strategy: import the Next.js route handler **in-process** (cucumber + tsx) and call its `POST` export directly. This **cannot work on an ordinary project** and the cause is not a dev-time artifact:
- The testbed (like the production app, like the `create-next-app` default) is **CommonJS-default** (`package.json` has no `"type": "module"`). Under that, tsx loads the app's `.ts` files through Node's CommonJS hook, so the route `require()`s its ESM deps (`next/server`, `@simplewebauthn`, `lib/webauthn`). Node 24's `require(esm)` rules **forbid it across `next/server`'s module cycle**, and even outside a cycle can't read named ESM exports synchronously. Neither `.mts` step files nor tsx's `tsImport` fixes it — the *app's* `.ts` files are the ones being CJS-loaded.
- Flipping the testbed to `"type": "module"` *did* make it pass — which is exactly the trap: it would give a **false green**. You cannot demand every adopter convert their production app to ESM to run behavior tests; that's a project-wide change and a serious adoption barrier. The testbed would then no longer represent the real project.

**Resolution (the right way, and framework-agnostic):** a behavior test drives the app over its **real interface** (HTTP, for a web app) against a **running instance** — never by importing the app's internals. The app's own runtime handles all module/bundling concerns; the test just issues real requests and asserts on real responses. This is identical in shape for Next, Express, Django, Rails, FastAPI — only the *launch command* differs. Implemented as a cucumber `BeforeAll`/`AfterAll` **app-under-test harness** (`features/steps/support/server.mts`) that boots `next dev` once on a fixed port, polls readiness, exposes a base URL, and kills the process group on teardown; step defs `fetch()` the live endpoint. BEH-003 passes (~4s incl. boot), clean teardown, `verify` green.

**Implications:**
- The **execution contract** for the behavior layer is now explicit: *the project tells the harness how to start the app and what base URL to hit; step definitions talk to that boundary.* This belongs in the adapter/runner config model, not hard-coded. (The launch command is the only project-specific bit.)
- **Phase 2 ripple (important):** observed-coverage capture must instrument the **app/server process** (e.g. c8/V8 coverage over the `next dev` child, or the framework's own coverage), **not** the in-process test runner. The earlier "c8 over the cucumber process" assumption in `02-phase-2.md` §-coverage is invalid for the HTTP model and must be revised before Plan 2.
- Plan 1's Task 2/3 as written (in-process import) were superseded by this server-based approach during execution; the committed testbed code reflects the corrected design.

### F11 — **(design-shaping)** observed coverage at the integration level is NOT capturable on Next.js with the naive approach; it needs a per-framework V8+CDP adapter
Spiked the Phase-2 §4 assumption (boot the app under `NODE_V8_COVERAGE`, read source-mapped coverage). On the testbed: booted `next dev` with `NODE_V8_COVERAGE`, fired the real BEH-003 requests (HTTP 200, behavior demonstrably ran), exited cleanly — and the coverage contained **only Next's own framework internals (`next/dist/...`)**, zero app code, zero `.next` chunks, even with a clean (non-SIGKILL) flush. Cause: Next App Router runs route handlers in a **separate render worker** (the `proxy.ts`/`render` split) that doesn't inherit the env-var capture, and app code is **bundled**.
- **Research (2026) confirms the real state of the art:** (1) the Istanbul/`babel-plugin-istanbul` path is a **dead end on App Router** — forcing Babel breaks Server Actions (SWC-only transform). (2) V8 coverage *does* work, but **only via the debugger**: launch the server under `--inspect` and collect V8 over **CDP** (the actual worker is at inspector **port + 1**), then **remap `.next` bundles to source via source maps**. The tool `nextcov` (stevez/nextcov) does exactly this (dev + prod, emits istanbul-format, merges with vitest). See research links in the Plan-3 discussion.
- **So observed integration coverage is *solved* but framework-specific** (CDP port dance + source-map remap; `nextcov` is Next-only; Next 16 + Turbopack support unverified). That collides with the F10 framework-agnostic principle — *for this piece only*.
- **Decision:** baseline = **static via code-graph** (an integration behavior declares its `entry` point; code-graph expands the transitive import closure into `source: static` edges; observed stays `unknown` with a reason). Static over-approximates, which is the **safe** direction for blast radius (a false "might be affected" just runs an extra test; a false "not affected" misses a regression). Observed-via-CDP becomes a **deferred per-framework coverage adapter** (see `parking-lot.md`), not a Plan-3 blocker. Unit-level observed coverage (vitest) already works and stays the precise-fingerprint source.

### Measurement (Phase 2 evidence gate, 2026-06-29)
The §6 evidence gate, measured on the testbed (full results in `02-phase-2.md` §6a). Headline: the behavior graph is **selective and fast** — editing `lib/webauthn.ts` flags exactly the two behaviors that depend on it; editing an unrelated lib (`audit.ts`) flags **none**; editing the route flags only BEH-003. **FP rate 0** on the representative set. Incremental `--check` on a change touching no exercised code is **0.07 s** (zero re-runs) vs. a full `--build` at ~1.4–2.4 s (vitest-dominated). Observed (unit, BEH-002 → 1 file) is precise; static (integration, BEH-003 → 3 files) is conservatively broader — the safe direction. **Caveat:** only 2 behaviors / 3 changes — validates the mechanism, not trustworthiness-at-scale. Gate verdict: deterministic blocking (on an affected behavior's real `test-failed`) is safe and shipped in wrap-up Phase 3.5; *fingerprint-driven* governance stays advisory until measured on a larger suite (the bar Phase 3 must clear).

*(append further findings below as we hit them)*

---

## Progress (cont.) — loop CLOSED

Resume-checklist **step 5 (close the loop) DONE.** On the testbed, BEH-003 ("unknown email does not reveal whether a user exists") is now a **real, passing, `accepted`** cucumber behavior driven over real HTTP against a running `next dev` instance. Testbed commits: `8244b8b` (cucumber-js + tsx + c8 tooling), `2fe9ca7` (real BEH-003 over HTTP + app-under-test harness), `4d4e60d` (SPEC-001 accept BEH-003). Deterministic `verify_links.py` → OK/exit 0 with one accepted behavior + two still-`proposed` scaffolds (BEH-001/002). The full Phase-1 traceability loop (spec → proposed behavior → real test → accepted → deterministic integrity) is proven end-to-end on a real project. Key correction surfaced: **F10** (HTTP-over-running-app, not in-process import) — which also reshapes Phase 2's coverage-capture design.

---

## SP1 — `confirmed` lifecycle state (2026-06-30, dogfood pass)

Dogfooded the new `confirmed` state on the testbed (branch `dogfood/sp1-confirmed`; `main` untouched). Added BEH-004 ("Authentication start rejects a malformed request body") as `confirmed`, `level: integration`, `entry` = the start route, **no adapter / no locator** (entry-less confirmed — intent confirmed, test owed). Results, first try, no friction:

- **verify_links** → `[]` / exit 0: a confirmed behavior with no locator is correctly *not* a `missing-locator` error; its declared `entry` still resolved.
- **behavior-graph `--build`** → BEH-004 projected with `state: confirmed`, `coverage: static`, and the entry's code-graph closure as `source: static` edges (route + `lib/prisma.ts` + `lib/webauthn.ts`). `adapter`/`locator` are `null` and round-trip fine.
- **`--check --base main`** (no-op touch to the entry route) → `affected: [BEH-003, BEH-004]`, **`failed: []`, exit 0**. The headline: a `confirmed` behavior is surfaced by Direction A (so it *will* be available for validate-on-hit in SP3) yet **never gates** — it can only ever carry `static`/`unknown`, never `test-failed`, because the runner never executes it.

Net: `confirmed` behaves exactly as designed — first-class, blast-radius-visible, advisory. The entry-less-confirmed decision (allowed; worklist-only when no `entry`) held up. No new friction surfaced.

---

## SP2 — onboarding & bootstrap (2026-06-30, dogfood pass)

Dogfooded `project_shape.py` + the `bootstrap` flow on the testbed (branch `dogfood/sp2-bootstrap`; `main` untouched). This is the brownfield-import path the parking-lot flagged as never-exercised.

- **Detector (D1) on the real testbed** → `brownfield`, **232 source files / 609 internal import edges**, readable stack line (`runtime=nodejs pkg=pnpm frontend=nextjs backend=nextjs_api_routes db=sqlite orm=prisma test=cucumber,gherkin,vitest`). The internal-edge signal (not raw file count) cleanly separates real wiring from boilerplate.
- **Greenfield / unknown (D2)** → a dir with no `graph.json` → `unknown` (falls back to ask); a `graph.json` whose imports are all `external:` → `greenfield`. Graceful degradation confirmed without touching any real repo.
- **Bounded brownfield scan (D3)** — inferred the **post-locking** feature (`app/api/posts/[id]/lock|claim`, `lib/post-lock-types.ts`) at the per-observable-behavior grain → **5 `proposed` behaviors** (acquire / locked-by-other 423 / release-not-holder 409 / refresh-not-holder 409 / claim-clears-is-new), written as `SPEC-002` with `entry` anchors. Verified: verify_links **clean (exit 0)**; **zero `.feature` scaffolds** written to the code tree (proposed → record only); **SPEC-001 untouched** (additive); the 5 proposed behaviors are **not** projected into `behavior.json` (only accepted BEH-002/003 are) — confirming "the proposed corpus lives in specs; `behavior.json` stays ≈empty until acceptance."

**Verdict on the parking-lot question ("flood vs manageable"):** at the per-observable-behavior grain, one real feature → ~5 crisp, test-shaped candidates. Manageable. The grain choice holds. **Caveat:** one feature area, hand-run as the controller (the full coordinator/parallel-agent `scan` over all 224 files was not run — same mechanism, larger volume; the lazy-review model means the pile size is not the ergonomic bottleneck, the per-hit surfacing is). No friction surfaced; one fix during build (text-format stack rendered raw dict repr → flattened, since `bootstrap` shows `--format text` to the engineer).

---

## SP3 — validate-on-hit (2026-06-30, dogfood pass)

Dogfooded `behavior-graph --surface` + the wrap-up Phase 3.5 surfacing step on the testbed, reusing the `dogfood/sp2-bootstrap` branch (its `SPEC-002` has 5 `proposed` post-locking behaviors anchored to the lock/claim routes). `main` untouched.

- **D1 — direct hit:** a no-op edit to `app/api/posts/[id]/lock/route.ts` → `validate_candidates = [BEH-004,005,006,007]` (the 4 lock-route behaviors), BEH-008 (claim route, untouched) correctly absent, the edited route **not** a recall gap (it is a declared entry).
- **D2 — dependency-level hit (the headline):** a no-op edit to `lib/db-prisma.ts` — which the routes import, the routes themselves **unchanged** (`lock route in changed? False`) — surfaced **all** post behaviors (BEH-004..008) because both entries are in `impact` as transitive dependents. This is exactly the precise `entry ∈ impact` match; the rejected coarse `entry ∈ changed` would have surfaced nothing. The closure-equivalence reasoning holds on real data.
- **D3 — recall gap:** editing `lib/date-formatter.ts` (no behavior's entry, in no exercise) → `recall_gaps = [lib/date-formatter.ts]`, no validate candidates. Uncovered touched code is caught.
- **D4 — confirm-bump loop:** simulating the wrap-up confirm action by flipping BEH-004 `proposed → confirmed` → `verify_links` clean (confirmed + entry, no locator is valid) → `behavior-graph --build` now projects BEH-004 as `confirmed`/`static`. The end-to-end loop (surface → confirm → advisory static fingerprint, then test-owed) works.

**Verdict:** validate-on-hit is selective and precise on real data — Direction A bounds the surfaced set to exactly the touched behaviors, the dependency-level match works (the property that makes it more than a coarse entry check), and the recall gap catches genuinely-uncovered edits. **Caveat:** re-inference quality (the agent re-reading the entry to refresh a candidate's description) is inherently judgment and was exercised lightly here (the confirm was a direct state bump); it will get real exercise once a human drives wrap-up interactively on a substantive change.

---

## SP4 — status & backlog (2026-06-30, dogfood pass)

Dogfooded the `status` skill + `collect_status.py` + `behavior-graph --gaps` + `findings.json` on the testbed (`dogfood/sp2-bootstrap`; `main` untouched).

- **D1 — status census/worklists:** `6 proposed · 0 confirmed · 2 accepted`, intent worklist 6, test-owed 0, 222 coverage gaps, verify 0, stale 0, security `note: no findings.json`. Each source reported or noted; never blocked.
- **D2 — gaps:** whole-repo audit → 222 uncovered source files (the testbed is mostly unspecced beyond passkey auth + the SP2 post-locking candidates), sample real files; **no declared entry leaked into the gaps** (the shared `_covered` correctly excludes entries/exercises).
- **D3 — BACKLOG.md:** rendered with the generated "do not edit" header, an accurate census line, and all four sections (Behaviors to confirm / Tests owed / Coverage gaps / Open security findings).
- **D4 — findings.json:** hand-wrote a 2-finding index (1 open, 1 resolved) per the schema → `status` reported **1 open finding** (resolved correctly excluded). The structured index works as the SP5 substrate.
- **D5 — worklist move:** confirming BEH-004 (`proposed → confirmed`) moved the census to `5 proposed · 1 confirmed`, intent worklist 5, **test-owed 1** — the lifecycle bump flows straight into the worklists.

**Verdict:** `status` is a faithful read-only aggregator — census, both worklists, gaps, verify, stale, and (structured) security all populate, degrade independently, and move correctly as state changes. The backlog is a real shared artifact. **Caveat:** `findings.json` was hand-written (a full `codebase-security-scan` run is heavy); the agent-emit path is exercised for real once a scan runs on a project. 222 gaps is a lot — expected on a mostly-unspecced repo; the capped sample keeps the backlog readable, and the worklists/`gaps` are the mechanism to work it down.

---

## SP5 — security ↔ behavior cross-reference (2026-06-30, dogfood pass)

Dogfooded `behavior-graph --covering` + the security cross-reference on the testbed (`dogfood/sp5-crossref`; `main` untouched). The BEH-003 exemplar, end-to-end:

- **D1 — covering query:** `--covering app/api/auth/passkey/authenticate/start/route.ts` → `[(BEH-003, SPEC-001, static)]` — the accepted, test-backed behavior that exercises the auth-start route is surfaced.
- **D2 — verified downgrade:** seeded two `open` findings; the prefilter mapped `route → [BEH-003]` and `lib/date-formatter.ts → []`. Judging BEH-003's anti-enumeration intent to explain SEC-001 ("endpoint does not verify the user exists"), downgraded it to `status: intentional`, `behavior_ref: BEH-003`, "verified by passing test". `status` then reported the finding **dropped from the open count**.
- **D3 — uncovered stays open:** SEC-002 on `lib/date-formatter.ts` (no accepted behavior covers it) → `--covering` empty → stays `open`. `status` open ids = `[SEC-002]` (1 open). No false silencing.

**Verdict:** the strongest-evidence rule works as designed — a verified (`accepted` + passing test) behavior silences a flagged finding (drops it from outstanding) while it stays visible with the `behavior_ref`; an uncovered finding stays open; only accepted behaviors qualify (the prefilter returns accepted-only). This completes the Adoption & Intent Lifecycle track. **Caveat:** the relevance judgment (does BEH-003 explain SEC-001) was applied by hand here, as it will be by the scan agent — same kind of judgment `check-specs` already makes for declarative specs; the deterministic part (`--covering` prefilter + the `behavior_ref`/status plumbing) is the tested, load-bearing piece.

---

## Full-repo brownfield scan — at-scale measurement (2026-06-30)

Ran the full brownfield `scan` (coordinator + 7 parallel discovery agents) over the whole testbed (~224 files, auth excluded — already specced), to answer the parking-lot's open at-scale question. Read-only (no spec files written — this was a *measurement* of the candidate inventory, not a bootstrap commit).

**Result — the queue at the per-observable-behavior grain:**

| Area | exec behaviors | declarative | files |
|---|---|---|---|
| posts | ~49 | 6 | 9 |
| events | ~41 | 5 | 3 |
| emails | ~63 | 10 | 8 |
| admin-users | ~57 | 7 | 9 |
| admin-account-lifecycle | ~54 | 6 | 12 |
| media-upload | ~37 | 7 | 5 |
| settings/i18n/translate | ~35 | 6 | 4 |
| **total** | **~336** | **~47** | **~50** |

**~383 proposed candidates** total (~88% executable behaviors, ~12% declarative decisions).

**Findings:**
- **Flood confirmed in aggregate — manageable only because review is lazy.** Every area was individually manageable (35–63 candidates, and each agent self-reported "manageable at this grain"), but the **whole-repo total (~383)** is decisively a pile no human reviews up front. This is the direct answer to the parking-lot's "manageable queue vs flood on a few-hundred-file repo": **a flood if reviewed eagerly; fine because nothing is.** It confirms the core architecture thesis and makes **SP3 (validate-on-hit) + SP4 (worklists/status) load-bearing, not optional** — they are the only thing that makes a ~380-candidate corpus tractable.
- **Classification quality: good.** The ~88/12 executable-vs-declarative split is sensible. Declarative decisions captured genuinely non-testable design choices (advisory time-boxed locks, masked API keys, dual-passkey super-admin transfer, public-vs-auth endpoint policy, email-client inline-style constraint, 60s settings cache). Agents flagged borderline cases honestly (audit-log side-effects → kept as executable since integration-verifiable).
- **Grain mostly held; a real padding risk surfaced.** Most agents stopped at natural behavioral seams. But validation-heavy routes (events/emails/translate) produced per-input-branch candidates (e.g. one behavior per field-length check) — defensible (each is a distinct assertion) but the largest contributor to volume. If the pile ever needs trimming, collapsing per-field-validation behaviors into one "validates the payload (rejects: …)" behavior per route is the lever.
- **Cost: acceptable for one-time onboarding.** 7 parallel discovery agents, ~260k subagent tokens, ~65s wall.

**Verdict:** the brownfield import scales — not by keeping the queue small, but by never requiring it to be reviewed at once. The grain is right for precision (each candidate maps to one route+assertion); volume is the expected consequence, drained lazily. The parking-lot's at-scale risk is now measured and closed.

---

## Resume checklist (after session restart)

1. Confirm branch code now loads: `/freya-devkit:spec-manager help` should mention **behaviors / knowledge-base / adapters** (not `/docs/specs/`).
2. `/freya-devkit:spec-manager init` against the **testbed** → expect `knowledge-base/` layout (NOT `/docs/specs/`) + `principles.md` template; watch runner detection report **none**.
3. `/freya-devkit:spec-manager create` a first spec for **passkey auth** → classify intent → a declarative decision or two + 1–2 **proposed** behaviors with Gherkin scaffolds.
4. `/freya-devkit:spec-manager verify` → deterministic link-integrity checks on real content.
5. (Loop-closer, optional) write one real test for the most important behavior in a fitting runner (e.g. Playwright E2E or a `lib/` unit test), mark it `accepted`, run wrap-up so execution + deterministic-only blocking fire.
6. Log every friction point here as a provisional-choice correction (vision §9).
