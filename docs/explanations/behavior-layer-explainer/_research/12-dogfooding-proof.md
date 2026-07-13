# What the Behavior Layer Demonstrably Solved — The Dogfooding Evidence

> Research brief for the explainer webapp. Source: `docs/design/behavior-layer/dogfooding-notes.md`
> ("Phase 1 — Dogfooding Notes & Friction Log"). Every number, verdict, filename, and CLI
> flag below is copied verbatim from that file. Nothing here is invented.
> Proprietary testbed domain content has been genericized (see **Sanitization / unverified** at end).

---

## 1. The setup: why dogfooding, and against what

The Behavior Layer was built **mechanism-first, validated by dogfooding** (vision §9). Rather than
trust a design on paper, the team ran the branch code against **a real, production-shaped
Next.js / TypeScript web app** used as an isolated testbed snapshot. The point was to find the
provisional design choices that break on contact with real code and log every one as a correction.

The testbed's shape (this is *why* it was a good stress test):

- **Stack:** Next.js 16 (App Router) + React 19 + TypeScript, Prisma 7 (SQLite), NextAuth 4, pnpm,
  Tailwind + shadcn/ui, next-intl. A CMS-style web app.
- **Tests: NONE.** No test files, no runner in `devDependencies`, no test script. This deliberately
  exercised the "runner detection reports **none**" case and the greenfield-adoption path.
- **Uses `@simplewebauthn` (passkeys)** — matched the vision's running example, so the natural
  **first spec is passkey auth**.
- **TS path alias `@/* → ./*`, used pervasively** (`@/lib/...`, `@/components/...`). This was a
  **direct stress test of the code-graph substrate** — and it exposed a critical latent bug (§4 below).
- **Git baseline:** fresh repo, **307 tracked files**.

### The dev→install friction (F1–F3) — before any feature could even run
The branch code couldn't be exercised through `/freya-devkit:*` at first: the Skill tool loads the
**published plugin cache** (which tracked a **pre-Phase-1** GitHub commit), not the local working tree.

- **F1 — No dev→install loop.** Fixed by symlinking a local-dev install; flagged for CONTRIBUTING.
- **F2 — Plugin cache does not hot-reload in a running session.** After symlinking, the current
  session **still served the stale SKILL.md** (verified: `/freya-devkit:spec-manager help` returned
  old `/docs/specs/`-era content). **A session restart is required** to pick up local-dev changes.
  Working loop becomes: **edit → restart → test.**
- **F3 — `init` leaves spec category dirs that won't survive Git.** `init` creates 7 empty spec
  category dirs; Git doesn't track empty dirs, so on commit they vanish. Needs `.gitkeep`/README or
  lazy creation.

---

## 2. What the full Phase-1 loop demonstrably did (N2, "loop CLOSED")

**N2 — validated: the full Phase 1 loop works on a real project.** End-to-end on the testbed with
**SPEC-001 (Passkey Login), 3 behaviors**:

- **Parser:** `search_specs.py --id SPEC-001` round-tripped the inline `tags: [...]` array (**the
  original silent-drop bug class**), the 6-path `related_code` block, and all 3 list-of-maps
  `behaviors` — the substrate was proven on real content.
- **Adapter:** `adapters.py gherkin-scaffold` emitted a correct `features/auth/passkey-login.feature`
  (`@SPEC-001` on Feature, `@BEH-NNN` per scenario, TODO markers).
- **verify (clean):** `verify_links.py` → **OK / exit 0** with all behaviors `proposed`.
- **verify (gate fires) — the load-bearing moment:** flipping BEH-001 → `accepted` while it was
  **still a TODO scaffold** produced **exactly one `accepted-but-scaffold` error / exit 1, scoped to
  BEH-001** — BEH-002/003 (proposed scaffolds in the same file) were correctly **not** flagged
  (per-scenario scoping, commit `54d6eb3`). Reverted to `proposed` → OK again.

**Loop CLOSED:** BEH-003 ("unknown email does not reveal whether a user exists") became a **real,
passing, `accepted`** cucumber behavior driven over **real HTTP against a running `next dev`
instance**. The full traceability loop — **spec → proposed behavior → real test → accepted →
deterministic integrity** — is proven end-to-end on a real project.

> **Newcomer takeaway:** the deterministic gate can catch a lie that a green test suite never would —
> a behavior marked `accepted` whose "test" is still a TODO scaffold. The suite is green (nothing
> runs); the layer says exit 1.

---

## 3. The headline measurement: selective and fast, FP rate 0 (Phase 2 evidence gate)

Measured on the testbed (2026-06-29). **The behavior graph is selective and fast:**

- Editing `lib/webauthn.ts` flags **exactly the two behaviors that depend on it**.
- Editing an unrelated lib (`audit.ts`) flags **none**.
- Editing the route flags **only BEH-003**.
- **FP rate 0** on the representative set.
- Incremental `--check` on a change touching no exercised code is **0.07 s** (zero re-runs) vs. a
  full `--build` at **~1.4–2.4 s** (vitest-dominated).
- Observed coverage (unit, BEH-002 → 1 file) is **precise**; static (integration, BEH-003 → 3 files)
  is **conservatively broader — the safe direction**.

**Honest caveat (recorded):** only **2 behaviors / 3 changes** — this validates the *mechanism*, not
*trustworthiness-at-scale*. **Gate verdict:** deterministic blocking (on an affected behavior's real
`test-failed`) is **safe and shipped in wrap-up Phase 3.5**; *fingerprint-driven* governance stays
**advisory** until measured on a larger suite.

---

## 4. The critical thing dogfooding caught that a green suite would have missed (F6–F9)

This is the most important "before/after" moment. The impact/blast-radius engine was **silently and
completely broken for path-alias projects** — and had been **since v0.1.0**. A green test suite would
never surface it, because the tool returned an answer; the answer was just empty.

- **F7 (critical):** After building, the testbed graph had **229 files, 1052 import edges — and
  0 internal edges; all 1052 tagged `external:`.** Cause: every internal import uses the `@/` alias
  and the resolver treated non-relative imports as external and dropped them.
  `--dependencies app/api/auth/passkey/authenticate/route.ts` → **`[]`** despite three `@/lib/*`
  imports. **Worse than incomplete: it returned an empty blast radius *as if complete***, violating
  the "coverage-unknown, never silent" principle (§6). No "unknown" signal was emitted.
- **F9:** relative-import resolution was **cwd-sensitive** and silently dropped imports when run via
  `--dir X` from a different cwd (exactly how wrap-up runs it). Proven with a 3-file fixture. The
  testbed's 0/1052 was **both bugs** compounded.
- **F6:** `graph_ops.py --build` was **interactive** (prompted on stdin to classify ambiguous dirs,
  even its own generated `.graph/` output) and **hangs** unattended → wrap-up's Phase 1 couldn't
  complete as a pipeline subprocess.
- **F8:** generated `knowledge-base/.graph/` was **not git-ignored** → would be committed as a
  (broken) artifact.

**Verified verdict — the engine is ORIGINAL, not introduced by this work.**
`git diff ba8470b..HEAD -- skills/code-graph/scripts/graph_ops.py` = **2 lines**, both a path rename.
`_resolve_import_path` was **unchanged since published v0.1.0**. Conclusion: the impact feature had
been **broken for path-alias projects since v0.1.0**; dogfooding merely exposed it on the first real
alias-using project. §10 was **promoted from "deferred/open" to BLOCKING for Phase 2**.

### The fix + the before/after number
Fixed with TDD (`test_graph_ops.py`, **8 cases, written first**). Notably, a naive regex JSONC stripper
mis-read `/*` in `@/*` and `*/` in `**/*.ts` — **caught by a TDD regression test before shipping**.

**Verified on the testbed:** rebuild went from **0 internal / 1052 external** to
**607 internal / 488 external / 0 unresolved**. The authenticate route now resolves
`lib/webauthn.ts`, `lib/rate-limit.ts`, `lib/audit.ts`, `lib/prisma.ts`. **§10 capability-contract now
met for TS/JS — Phase 2 unblocked.**

The five fixes: (1) tsconfig/jsconfig `paths`+`baseUrl` alias resolution; (2) cwd-independent
resolution anchored to `project_dir` (F9); (3) tag imports `external:` vs `unresolved:` — **no silent
drop** (§6); (4) `--non-interactive` (auto when no TTY) (F6); (5) build writes a self-ignoring
`knowledge-base/.graph/.gitignore` (`*`) (F8).

---

## 5. The other design-shaping discoveries (F10, F11)

These are cases where dogfooding didn't just find a bug — it **reshaped the design**.

- **F10 (critical, design-shaping): in-process route-handler import is not viable.** The planned
  strategy — import the Next.js route handler **in-process** and call its `POST` export directly —
  **cannot work on an ordinary project.** The testbed (like the `create-next-app` default) is
  **CommonJS-default**; Node 24's `require(esm)` rules forbid loading the route's ESM deps across
  the module cycle. Flipping the testbed to `"type": "module"` *did* make it pass — **exactly the
  trap: a false green**, and an unacceptable adoption barrier (you can't demand every adopter convert
  their app to ESM).
  **Resolution (framework-agnostic):** a behavior test drives the app over its **real interface
  (HTTP)** against a **running instance** — never by importing internals. Implemented as a cucumber
  `BeforeAll`/`AfterAll` app-under-test harness (`features/steps/support/server.mts`) that boots
  `next dev` once, polls readiness, and kills the process group on teardown. **BEH-003 passes (~4s
  incl. boot), clean teardown, `verify` green.** The **execution contract** is now explicit: the
  project tells the harness how to start the app and what base URL to hit.
- **F11 (design-shaping): observed integration coverage on Next.js needs a per-framework V8+CDP
  adapter.** Booting `next dev` under `NODE_V8_COVERAGE` captured **only Next's own framework
  internals, zero app code** (App Router runs handlers in a separate render worker; app code is
  bundled). The real state of the art (2026 research): Istanbul is a dead end on App Router; V8
  works but **only via the debugger** (`--inspect`, collect over CDP at inspector **port + 1**, remap
  `.next` bundles to source). **Decision:** baseline = **static via code-graph** (an integration
  behavior declares its `entry`; code-graph expands the transitive import closure into
  `source: static` edges; observed stays `unknown` with a reason). **Static over-approximates, which
  is the safe direction** — a false "might be affected" just runs an extra test; a false "not
  affected" misses a regression. Observed-via-CDP became a deferred per-framework adapter.

---

## 6. Per-sub-project dogfooding confirmations (SP1–SP5)

Each ran on its own branch with `main` untouched. All passed.

- **SP1 — `confirmed` lifecycle state.** Added BEH-004 as `confirmed`, `level: integration`, `entry`
  = the start route, **no adapter / no locator** (entry-less confirmed — *intent confirmed, test
  owed*). First try, no friction. `verify_links` → `[]` / exit 0 (a confirmed behavior with no
  locator is correctly *not* a `missing-locator` error). `--check --base main` → `affected:
  [BEH-003, BEH-004]`, **`failed: []`, exit 0`. Headline: a `confirmed` behavior is **blast-radius
  visible yet never gates** — it can only carry `static`/`unknown`, never `test-failed`, because the
  runner never executes it. First-class, advisory.
- **SP2 — onboarding & bootstrap (brownfield-import path).** The detector on the real testbed →
  **`brownfield`, 232 source files / 609 internal import edges**. (Note the number differs from the
  pre-fix 229 — this is post-code-graph-fix.) Greenfield/unknown degradation confirmed. Bounded
  brownfield scan of one real feature (a resource-locking feature — genericized) → **5 `proposed`
  behaviors** written as SPEC-002 with `entry` anchors: verify_links **clean (exit 0)**; **zero
  `.feature` scaffolds written to the code tree** (proposed → record only); **SPEC-001 untouched**;
  the 5 proposed behaviors are **not** projected into `behavior.json` (only accepted BEH-002/003
  are). **Verdict:** at the per-observable-behavior grain, one real feature → **~5 crisp,
  test-shaped candidates. Manageable.** Caveat: one feature area, hand-run as controller.
- **SP3 — validate-on-hit.** D1 direct hit (edit lock route) → `validate_candidates =
  [BEH-004,005,006,007]`, untouched claim-route BEH-008 correctly absent. **D2 dependency-level hit
  (the headline):** a no-op edit to a shared db lib the routes import (**routes themselves
  unchanged**) surfaced **all** post behaviors (BEH-004..008) via `entry ∈ impact` (the coarse
  `entry ∈ changed` would have surfaced nothing). D3 recall gap: editing an uncovered util →
  `recall_gaps = [...]`, no candidates. D4 confirm-bump loop works end-to-end. **Selective and
  precise on real data.**
- **SP4 — status & backlog.** Census `6 proposed · 0 confirmed · 2 accepted`, intent worklist 6,
  test-owed 0, **222 coverage gaps**, verify 0, stale 0, security `note: no findings.json`. Gaps
  audit → **222 uncovered source files**, no declared entry leaked into gaps. `BACKLOG.md` rendered
  with generated header + all four sections. `findings.json` 2-finding index (1 open, 1 resolved) →
  `status` reported **1 open finding** (resolved excluded). D5: confirming BEH-004 moved census to
  `5 proposed · 1 confirmed`, intent worklist 5, **test-owed 1** — lifecycle bumps flow into
  worklists. **A faithful read-only aggregator that degrades independently.**
- **SP5 — security ↔ behavior cross-reference.** `--covering <auth-start route>` →
  `[(BEH-003, SPEC-001, static)]`. **Verified downgrade:** BEH-003's anti-enumeration intent explains
  SEC-001 ("endpoint does not verify the user exists") → downgraded to `status: intentional`,
  `behavior_ref: BEH-003`, "verified by passing test" → `status` **dropped it from the open count**
  (still visible with the ref). **Uncovered stays open:** SEC-002 (no accepted behavior covers it) →
  `--covering` empty → stays `open`, open ids `[SEC-002]`. **Only accepted behaviors qualify.**
  The strongest-evidence rule works: **a verified behavior silences a flagged finding; an uncovered
  finding stays open; no false silencing.**

---

## 7. The at-scale measurement: the "flood" question, answered

Ran the **full brownfield `scan` (coordinator + 7 parallel discovery agents)** over the whole testbed
(**~224 files, auth excluded**). Read-only measurement (no spec files written).

**The candidate queue at the per-observable-behavior grain — ~383 proposed candidates total**
(~88% executable behaviors, ~12% declarative decisions):

| Area (genericized) | exec behaviors | declarative | files |
|---|---|---|---|
| resource A | ~49 | 6 | 9 |
| resource B | ~41 | 5 | 3 |
| notifications | ~63 | 10 | 8 |
| admin-users | ~57 | 7 | 9 |
| admin-account-lifecycle | ~54 | 6 | 12 |
| media-upload | ~37 | 7 | 5 |
| settings/i18n | ~35 | 6 | 4 |
| **total** | **~336** | **~47** | **~50** |

**Findings:**
- **Flood confirmed in aggregate — manageable only because review is lazy.** Every area was
  individually manageable (35–63 candidates), but the whole-repo total (**~383**) is "**a flood if
  reviewed eagerly; fine because nothing is.**" This makes **SP3 (validate-on-hit) + SP4
  (worklists/status) load-bearing, not optional** — they're the only thing that makes a ~380-candidate
  corpus tractable.
- **Classification quality: good.** ~88/12 executable-vs-declarative split is sensible. Declarative
  decisions captured genuinely non-testable design choices (e.g. advisory time-boxed locks, masked
  API keys, cache TTLs). Agents flagged borderline cases honestly.
- **Grain mostly held; a real padding risk surfaced.** Validation-heavy routes produced
  per-input-branch candidates (one behavior per field-length check) — the largest volume contributor.
  Trim lever if ever needed: collapse per-field-validation into one "validates the payload" behavior
  per route.
- **Cost: acceptable for one-time onboarding.** 7 parallel agents, **~260k subagent tokens, ~65s
  wall**.

**Verdict:** the brownfield import **scales — not by keeping the queue small, but by never requiring
it to be reviewed at once.** The at-scale risk is measured and closed.

---

## 8. Honest limitations recorded (for a balanced explainer)

- Phase 2 evidence gate measured on **only 2 behaviors / 3 changes** — validates mechanism, not
  trustworthiness-at-scale. Fingerprint-driven governance stays **advisory** until a larger suite.
- **Observed integration coverage is framework-specific** (Next-only CDP/source-map dance; Next 16 +
  Turbopack support unverified) — deferred as a per-framework adapter; static-via-code-graph is the
  shipped baseline.
- SP2/SP3/SP5's **relevance/re-inference judgments were applied by hand** (as the agent will in real
  use); the fully-automated agent-emit paths get real exercise once a human drives wrap-up
  interactively / a real security scan runs.
- SP4's **`findings.json` was hand-written** (a full security scan is heavy).
- **222 coverage gaps** on the testbed — expected on a mostly-unspecced repo; the capped sample keeps
  the backlog readable.
- `extends` chains and per-edge confidence in code-graph **remain out of scope** (graphify fallback
  if needed).

---

## Sanitization / unverified

- The testbed is a real proprietary web app. Its identity, business/domain feature names, and any
  customer data are **not** reproduced here. Feature areas from the at-scale scan table
  ("resource A/B", "notifications") and the SP2 "resource-locking feature" are **genericized
  placeholders** — the *numbers, files, and mechanics are verbatim* from the source; only the
  business labels were neutralized.
- The stack, passkey/WebAuthn example, and route paths (e.g. `app/api/auth/passkey/authenticate/...`)
  are quoted as they appear in the notes; they describe generic auth mechanics, not proprietary logic.
- Commit SHAs, file paths, and `lib/*` names are copied verbatim from the notes.
