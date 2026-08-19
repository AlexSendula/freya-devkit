# Phase 3 (track A) — Adoption & Intent Lifecycle

**Status:** Draft for review
**Date:** 2026-06-30
**Depends on:** `00-vision.md`, `01-phase-1.md`, `02-phase-2.md` (the behavior graph + Direction A/B + runner + merge-by-trust), and the Phase-2 closeout (`02f`).
**Relationship to governance:** The vision earmarked "Phase 3" for *governance* (model-based contradiction checks, principle enforcement). This track is its **prerequisite**: you cannot govern intent you have not captured. So this — getting intent *into* the system on a real (brownfield) project without overwhelming anyone — comes first; governance is the next track after.

---

## 1. The problem

The behavior layer works once behaviors exist (Phase 1–2). The unanswered question is **adoption**: how does intent get captured on a real, existing codebase without either (a) the AI fabricating authoritative intent it can't actually know, or (b) drowning the engineer in a hundreds-of-specs review queue on day one? The dogfooding made this concrete — a full `scan` of the 224-file testbed would be a flood nobody validates.

## 2. The core idea — decouple inference from validation

Inference is cheap and can be done up front; **validation is the scarce resource** and must be spent lazily, in the flow of work.

- **Inference (bootstrap, all `proposed`):** at adoption, infer a full graph of *candidate* behaviors from the code. Cheap, one-time, and **nothing is trusted** — every candidate is `proposed`.
- **Validation (lazy, work-driven):** the engineer only confirms intent for the small subset a change actually **touches** (Direction A), in context, when the code is already in their head. Correct intent accumulates organically as the team works across the codebase.
- **The tail (cold code):** behaviors never hit by work are worked off a **backlog**, one at a time, at will.

This dissolves the flood: a full bootstrap is fine *because you never have to review it all at once.*

## 3. The intent lifecycle (the backbone)

Confirming intent and writing a test are **two different steps**. Collapsing them forces test-writing mid-feature; leaving them untracked silently accumulates unguarded intent. So we make the middle state first-class — insert **`confirmed`** between `proposed` and `accepted`:

| State | Meaning | Test? | In blast radius? | Gates wrap-up? |
|---|---|---|---|---|
| `proposed` | drafted/inferred; intent **not** confirmed | no | no | no |
| **`confirmed`** *(new)* | a human confirmed the intent is correct; **test owed** | not yet | **yes, via static fingerprint** (if `entry` declared) — advisory | no (advisory) |
| `accepted` | confirmed **and** a real, passing linked test exists | yes | yes (observed/static) | **yes** (deterministic block on `test-failed`) |
| `quarantined` / `deprecated` | as today | — | — | — |

Key consequences:
- **`accepted` keeps today's meaning** (intent + test, regression-gating) — `verify_links`' accepted-but-scaffold gate is unchanged.
- A `confirmed` behavior with an `entry` **still gets a static fingerprint** (Phase-2 Plan 3) — so it participates in Direction A's blast radius *before its test exists*. The static path is the placeholder coverage that bridges `confirmed → accepted`.
- "Finishing" intent = the same loop as confirming behaviors, applied twice: `proposed → confirmed` (confirm intent) and `confirmed → accepted` (write/link the test). Both are tracked; neither is silent (§6).

## 4. Onboarding / bootstrap (greenfield-aware)

A unified "bring the plugin up on a project" flow, replacing today's run-each-command-by-hand setup. It **detects the project shape** and degrades gracefully:

- **Brownfield** (substantial existing code): `spec-manager init` → `code-graph build` → **`scan` (infer candidates, all `proposed`)** → `behavior-graph build`. Produces a full proposed graph; setup takes longer; **nothing to review yet**.
- **Greenfield / scaffold-only** (little or no code): **skip inference** — set up structure + empty graphs and message clearly ("greenfield — author behaviors forward as you build"). This is the *easier* path (intent-first/BDD), not an error. Detection uses `detect_project.py` + code-graph file counts.
- **Scaffold-noise guard:** on a boilerplate-heavy fresh app, inferred candidates come out low-certainty and skippable — they sit harmlessly as `proposed` until someone cares.

`certainty` here is the **prioritizer** of the proposed pile (high = a glance, low = real attention), not a trust signal — trust is the lifecycle `state`.

## 5. Validate-on-hit (the lazy loop)

At `wrap-up` (and available on demand), after computing the change's blast radius via Direction A:
- **Surface the affected `proposed` / `confirmed` behaviors prominently** — default to reviewing them, because intent capture is a first-class goal — **but skippable**. This stays low-friction *because Direction A bounds it to the touched subset* (typically 2–3, not the whole backlog), so prominence ≠ fatigue.
- **Refresh on hit:** re-infer/refresh a surfaced `proposed`/`confirmed` behavior against *current* code before showing it — never present a stale bootstrap guess.
- **Recall gap — touched code with no covering behavior:** when a change touches files in **no** behavior's `exercises`, prompt to capture one. This catches intent the bootstrap never inferred (otherwise invisible forever, since Direction A only hits behaviors that exist).

The cold tail (everything not hit by work) is **opt-in**, via the worklists (§6).

## 6. Status, backlog & worklists (never-silent)

Two distinct unifying commands — don't conflate them:
- **`wrap-up`** = the unifying **do/sync** command (already exists; runs code-graph + docs + specs + behavior-graph build/check + security + commits). No change to its role here beyond §5's surfacing.
- **`status`** *(new)* = the unifying **read-only check**: "where do I stand, what's outstanding?" — **no mutation, no commit.** It aggregates **across skills**:
  - behavior state counts (`proposed / confirmed / accepted / quarantined / deprecated`),
  - the two **worklists**: *intent* (proposed → confirm) and *test-owed* (confirmed → test),
  - `gaps` (code in no behavior's `exercises` — the uncovered-code audit),
  - open **security findings** (from codebase-security-scan),
  - deterministic `verify` failures + stale fingerprints.

`status` both **prints** a summary **and** refreshes a single **generated, git-tracked `knowledge-base/BACKLOG.md`** (named generically — it holds **behaviors to confirm + tests owed + open security findings**, not only intent). Properties:
- **Generated, never hand-edited** (header says so; run `status` to refresh) — can't rot into a lie like a manual TODO.
- **Git-tracked** (unlike the `behavior.json` cache) — *so the backlog is visible and shared*: it shows up in the repo, diffs in PRs, and the team sees "18 behaviors owe tests / 3 open security findings" without running anything. It is to intent+security completeness what a coverage report is to test coverage. `wrap-up` regenerates it in the artifacts commit so it stays current.

**Worklists** extend the existing `spec-manager review` one-at-a-time pattern from specs to behaviors: a certainty-sorted *intent* worklist (`proposed`) and a *test-owed* worklist (`confirmed`), worked until done or the engineer stops.

## 7. Security ↔ behavior cross-reference

`codebase-security-scan` already cross-references findings against **declarative** intentional design decisions (it reads `knowledge-base/specs/` and marks a finding `INTENTIONAL DESIGN` when a spec says so — e.g. no-password-fallback). That stays. **Extend it to also consult the behavior graph:** an **`accepted`, test-backed behavior** that explains a flagged finding is the **strongest possible "intentional" evidence** — a *verified guarantee*, not a prose claim. BEH-003 is the exemplar: a scan flagging "endpoint doesn't verify the user exists" should be silenced by "accepted behavior BEH-003, verified by a passing test, says the uniform response is the intended anti-enumeration guarantee." Open findings that this does *not* explain flow into the §6 backlog.

## 8. Where `certainty` lands (closing F4)

Confirmed during brainstorming and already documented in spec-manager: `certainty` is **not** the executable-behavior intent signal (lifecycle `state` is — `accepted`/`confirmed` = human-confirmed). `certainty` survives as (a) the **prioritizer** of the proposed worklist, (b) the confidence on **declarative** intentional-decisions the security scan consults, and (c) backward-compat. No provenance redesign.

## 9. Decomposition into sub-projects (each → its own plan)

1. **SP1 — Lifecycle: add `confirmed`.** `frontmatter.BEHAVIOR_STATES` + `validate_behaviors`; `verify_links` (confirmed may lack a test; accepted unchanged); `behavior-graph` (confirmed + `entry` → static fingerprint, advisory; not gating); runner dispatch. **Foundational — do first.**
2. **SP2 — Onboarding/bootstrap** (greenfield/brownfield detection + graceful degradation; all-`proposed` inference).
3. **SP3 — Validate-on-hit** (Direction A surfacing at wrap-up: prominent/bounded/skippable; refresh-on-hit; uncovered-touched-code prompt).
4. **SP4 — Status & backlog** (`status` command + generated git-tracked `BACKLOG.md` + `gaps` command + the two `review` worklists).
5. **SP5 — Security ↔ behavior cross-reference** (extend codebase-security-scan to consult `accepted` behaviors; independent of SP1–4).

Suggested order: **SP1 first** (everything leans on the lifecycle), then SP2 → SP3 → SP4; SP5 in parallel. Each ships working, testable software and gets its own plan + dogfooding pass on the testbed (which is the brownfield proving ground for SP2/SP3).

## 10. Scope

**In scope:** the lifecycle change, bootstrap, validate-on-hit, status/backlog/worklists/gaps, security cross-reference, greenfield handling.

**Out of scope (later):** model-based **contradiction checks / principle enforcement** (the governance track — this capability is its prerequisite); the observed-CDP coverage adapter and other `parking-lot.md` items; freshness *caching* as a perf optimization (distinct from §5's *correctness* refresh-on-hit); fully automated test *generation* for `confirmed → accepted` (we link/aid tests; we don't write them — boundary §5c of `02-phase-2.md`).

## 11. Open questions (resolve during sub-project planning)

- **`BACKLOG.md` location/name** — `knowledge-base/BACKLOG.md` proposed; confirm it shouldn't live elsewhere (e.g. repo root) for visibility.
- **Bootstrap inference depth** — does `scan` propose behaviors per route/function, or per feature area? (Affects proposed-pile size.) Decide in SP2, measure on the testbed.
- **`confirmed` without `entry`** — a confirmed behavior with no declared entry has *no* fingerprint, so Direction A can't surface it on hit. Require an `entry` (or a locator) at `confirm` time, or allow entry-less confirmed (worklist-only)? Decide in SP1.
- **Re-scan cadence** — bootstrap is one-time; how/when is inference re-run to catch new code (a `scan --update`, or the §5 uncovered-touched-code prompt as the primary mechanism)? Decide in SP2/SP3.

## 12. Acceptance criteria (capability-level)

> **Correction (2026-08-19) — SP1 through SP5 all shipped and were dogfooded.** The unchecked
> boxes below are stale bookkeeping. `confirmed` is in `frontmatter.py`; `freya-status` ships
> `collect_status.py` with both worklists and refreshes `knowledge-base/BACKLOG.md`;
> `behavior_graph.py` exposes `--surface`, `--gaps` and `--covering`; and the security scan
> consults accepted behaviors via `behavior_ref`. Dated dogfood passes for each are in
> `dogfooding-notes.md`. §11's open questions were all answered during those passes.
> Note that shipped code cites this document by name — `run_behaviors.py` refers to
> "design 03 §3" — so its number and section structure are load-bearing.

- [ ] `confirmed` is a first-class lifecycle state: validated, allowed without a test, gets a static fingerprint via `entry`, advisory (non-gating), promotable to `accepted` when a real test lands.
- [ ] A unified onboarding bootstraps a full **`proposed`** behavior graph on a brownfield project, and degrades gracefully (no pointless inference, clear message) on greenfield.
- [ ] At wrap-up, a change surfaces its **affected** proposed/confirmed behaviors (bounded, skippable) and flags touched code with **no** covering behavior.
- [ ] `status` reports — and refreshes a git-tracked `BACKLOG.md` listing — behaviors-to-confirm, tests-owed, and open security findings; never silent.
- [ ] `gaps` lists uncovered code (scoped, candidate list).
- [ ] The two `review` worklists (intent, test-owed) let an engineer work the tail one-by-one.
- [ ] `codebase-security-scan` cross-references `accepted` behaviors (not only declarative decisions) as intentional evidence.
- [ ] No fabricated authoritative intent: every inferred behavior is `proposed` until a human confirms; no scaffolds written into the code tree by inference.
