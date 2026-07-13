# Research Brief: Adoption & Intent Lifecycle (SP1–SP5)

**Slice:** Adoption & intent lifecycle — how the Behavior Layer actually gets *onto* a real, existing codebase without either fabricating intent or drowning the engineer.
**Audience:** an engineer who knows nothing about this feature.
**Sources (all read in full):**
- `docs/design/behavior-layer/03-adoption-and-intent-lifecycle.md` (parent design — the "track A" umbrella)
- `docs/superpowers/plans/2026-06-30-sp1-confirmed-lifecycle.md` (SP1 implementation plan)
- `docs/superpowers/specs/2026-06-30-sp2-onboarding-bootstrap-design.md`
- `docs/superpowers/specs/2026-06-30-sp3-validate-on-hit-design.md`
- `docs/superpowers/specs/2026-06-30-sp4-status-and-backlog-design.md`
- `docs/superpowers/specs/2026-06-30-sp5-security-behavior-crossref-design.md`
- `skills/spec-manager/scripts/project_shape.py` (SP2 detector, shipped)
- `skills/status/SKILL.md` + `skills/status/scripts/collect_status.py` (SP4, shipped)
- `skills/behavior-graph/scripts/behavior_graph.py` (SP3/SP4/SP5 subcommands, shipped)
- `skills/wrap-up/SKILL.md` Phase 3.5 (SP3 integration, shipped)

> All subcommands referenced below (`--surface`, `--gaps`, `--covering`) and the `project_shape.py` / `collect_status.py` scripts were verified present in the source tree — this track is shipped, not just designed.

---

## 0. The one-paragraph story

The Behavior Layer only helps *once behaviors exist*. Phase 1–2 built the machinery (the BEHAVIOR → TEST → CODE graph, the runner, Direction A/B blast radius). This track (called **Phase 3 / track A — Adoption & Intent Lifecycle**) answers the unanswered question: **how does intent get captured on a real, existing codebase** without (a) the AI fabricating authoritative intent it can't actually know, or (b) drowning the engineer in a hundreds-of-specs review queue on day one? The dogfooding made this concrete: *"a full `scan` of the 224-file testbed would be a flood nobody validates."*

The core insight: **decouple inference from validation.** Inference is cheap and done up front (bootstrap infers a full graph of *candidate* behaviors, all untrusted). **Validation is the scarce resource** and is spent lazily, in the flow of work — the engineer only confirms intent for the small subset a change actually *touches*, in context, when the code is already in their head. The cold tail (behaviors never hit by work) is worked off a backlog, one at a time, at will. *"This dissolves the flood: a full bootstrap is fine because you never have to review it all at once."*

This track is the **prerequisite for governance** (model-based contradiction checks, principle enforcement — the next track): *"you cannot govern intent you have not captured."*

---

## 1. The decomposition (SP1–SP5)

The design breaks into five sub-projects, each shipping working, testable software with its own plan + dogfooding pass:

1. **SP1 — Lifecycle: add `confirmed`.** Insert a new state between `proposed` and `accepted`. **Foundational — do first** (everything leans on the lifecycle).
2. **SP2 — Onboarding/bootstrap.** Greenfield/brownfield detection + graceful degradation; all-`proposed` inference. A unified `bootstrap` command.
3. **SP3 — Validate-on-hit.** Direction-A surfacing at wrap-up: prominent, bounded, skippable; refresh-on-hit; uncovered-touched-code prompt.
4. **SP4 — Status & backlog.** A read-only `status` command + generated, git-tracked `BACKLOG.md` + `gaps` command + two `review` worklists.
5. **SP5 — Security ↔ behavior cross-reference.** Extend `codebase-security-scan` to consult `accepted` behaviors as verified intentional evidence. Independent of SP1–4.

Suggested order: **SP1 first**, then SP2 → SP3 → SP4; **SP5 in parallel**. The **testbed** (`/Users/main/Documents/projects/viva-croatia-testbed`) is the brownfield proving ground for SP2/SP3; the production webapp is off-limits for all dogfooding.

---

## 2. SP1 — the `confirmed` lifecycle state (the backbone)

### Why it exists
Confirming intent and writing a test are **two different steps**. Collapsing them forces test-writing mid-feature; leaving them untracked silently accumulates unguarded intent. So the design makes the middle state first-class — inserting **`confirmed`** between `proposed` and `accepted`. "Finishing" intent becomes the same confirm-loop applied twice: `proposed → confirmed` (confirm intent) and `confirmed → accepted` (write/link the test). Both are tracked; neither is silent.

### The full lifecycle table (from the parent design §3)

| State | Meaning | Test? | In blast radius? | Gates wrap-up? |
|---|---|---|---|---|
| `proposed` | drafted/inferred; intent **not** confirmed | no | no | no |
| **`confirmed`** *(new)* | a human confirmed the intent is correct; **test owed** | not yet | **yes, via static fingerprint** (if `entry` declared) — advisory | no (advisory) |
| `accepted` | confirmed **and** a real, passing linked test exists | yes | yes (observed/static) | **yes** (deterministic block on `test-failed`) |
| `quarantined` / `deprecated` | as today | — | — | — |

The full enum, copied verbatim, is:
```
proposed → confirmed → accepted → quarantined → deprecated
```
i.e. `BEHAVIOR_STATES = ("proposed", "confirmed", "accepted", "quarantined", "deprecated")`.

### The three defining properties of `confirmed`

1. **Advisory / non-gating.** A `confirmed` behavior "must never appear in a regression-check `failed` list and never cause a non-zero exit." Only `accepted` behaviors gate wrap-up (a deterministic block on `test-failed`). `accepted` semantics are **completely unchanged** by SP1.
2. **Static fingerprint via `entry`.** A `confirmed` behavior with an `entry` still gets a **static fingerprint** (the code-graph closure of that entry), so it participates in Direction A's blast radius *before its test exists*. "The static path is the placeholder coverage that bridges `confirmed → accepted`." A `confirmed` behavior is **never executed** — because it names no real test yet — so it can *never* be `test-failed`. That is what makes it structurally non-gating.
3. **Entry-less confirmed is allowed** (an SP1 decision). A `confirmed` behavior "needs neither adapter nor locator; an `entry` is optional." With an `entry` → static fingerprint; without one → `unknown` / `no-entry` (worklist-only, surfaced later in SP4). This resolved an open question the design flagged (`confirmed` without `entry`).

### What SP1 actually changed (four tasks, TDD, stdlib-only Python 3.12)

- **Task 1 — `frontmatter.py`:** add `confirmed` to `BEHAVIOR_STATES`; make adapter/locator requirements **state-aware**. Rule: adapter required *only* when `state == "accepted"`; locator required *only* when `state == "accepted" and adapter != "manual"`. Both are still type/enum-checked when *present* in any state (so a typo still fails loud). Signature unchanged: `validate_behaviors(behaviors, spec_id=None) -> list[str]`.
- **Task 2 — `verify_links.py`:** the Tier-1 link checker stops requiring a locator for pre-test states. `missing-locator` and `accepted-but-scaffold` fire only for `state == "accepted"`; `entry-unresolved`, `locator-unresolved`, `missing-reverse-tag`, `missing-spec-tag` fire for **any** state when the relevant field *is* present. Signature unchanged: `verify(specs_dir=None) -> list[dict]`.
- **Task 3 — `run_behaviors.py` (behavior-runner):** generalize the loader and add a per-behavior dispatch:
  - `load_behaviors(specs_dir, states=("accepted",), level=None) -> list[dict]` — new generalized loader.
  - `load_accepted_behaviors(specs_dir, level=None)` — now a thin backward-compatible wrapper over `load_behaviors(..., states=("accepted",), ...)`.
  - `fingerprint_behavior(behavior, project_dir, commit) -> dict` — routes one behavior: `confirmed` → `static_fingerprint` (**never executes**); else the existing accepted dispatch. **State wins over level/adapter** — a `confirmed` behavior naming a `vitest` test that doesn't exist yet must NOT be executed.
  - New CLI flag `--states STATE [STATE ...]` (default `["accepted"]`), so the wrap-up "run accepted behaviors" path stays accepted-only unless asked otherwise.
- **Task 4 — `behavior_graph.py` (behavior-graph):** **project** `confirmed` behaviors into `behavior.json` (so Direction A/B see them — `state not in ("accepted", "confirmed")` is the exclusion, so `proposed` is still excluded). `_run_behavior_runner` now invokes the runner with `--states accepted confirmed`. A defensive guard in `regression_check` enforces "only `accepted` behaviors can gate" locally, so future executable paths can't accidentally block on a non-accepted behavior.

### The key data-flow subtlety (recurs across SP2/SP3)
`behavior.json` projects only `accepted` + `confirmed` behaviors — **not** `proposed`. So the "full proposed behavior graph" that bootstrap produces lives as **`proposed` behavior records in `knowledge-base/specs/`** (the review queue), not in `behavior.json`. `behavior.json` stays ≈empty right after bootstrap, which is *correct*: bootstrap fills the candidate corpus; SP3/SP4 drain it as candidates get confirmed and accepted.

---

## 3. SP2 — onboarding & bootstrap (greenfield-aware)

### The problem it solves
Today, bringing the plugin up on a project means running each command by hand. SP2 is **one unified `bootstrap` flow** that detects the project shape and degrades gracefully.

### `project_shape.py` — the greenfield/brownfield detector (shipped, deterministic)
`skills/spec-manager/scripts/project_shape.py` classifies a project's shape from **objective signals**. Stdlib-only, **no mutation** (pure read + classify).

- **Inputs:** `--project <dir>` (required), `--format json|text` (default `json`).
- **Reads:**
  - code-graph's `knowledge-base/.graph/graph.json` — counts **internal source files** (nodes) and **internal import edges**.
  - `detect_project.py` (from docs-manager) — runtime, package manager, frameworks, test runners.
- **The load-bearing idea — internal edges, not file count.** An "internal edge" is an import code-graph resolved to a *project* file — i.e. NOT tagged `external:` or `unresolved:`. **Internal edges (real feature wiring) are the brownfield signal; raw file count is not** — "a bare scaffold can have many boilerplate files yet zero internal wiring." (This is exactly the *scaffold-noise guard*: a boilerplate-heavy fresh app looks greenfield despite its file count.)
- **The recommendation rule (verbatim from `classify`):**
  - `graph.json` absent/unreadable → `recommendation: "unknown"`, reason `"no code-graph at knowledge-base/.graph/graph.json — run code-graph build first"`.
  - `internal_edges == 0` → `"greenfield"`, reason `"{source_files} source file(s) but 0 internal import edges — no real feature wiring yet"`.
  - `internal_edges > 0` → `"brownfield"`, reason `"{source_files} source file(s) with {internal_edges} internal import edge(s) — existing codebase"`.
- **Output JSON shape:** `{recommendation, evidence, reason}` where `evidence = {source_files, internal_edges, stack, graph_present}`. The **evidence is always reported**, so the recommendation is explainable and the engineer can override on sight.

The threshold is deliberately simple (`> 0`) and explainable. The recommendation is **advisory + overridable** — bootstrap shows the evidence and lets the engineer **confirm or override**; "a wrong recommendation is never silently binding." On `unknown`, bootstrap asks outright (no recommendation).

### The unified `bootstrap` command (a spec-manager SKILL.md procedure)
Home is a `bootstrap` command **in spec-manager** (not a new top-level skill) — `init` and `scan` already live there, and it's the unified extension of `init`. It's an agent-orchestrated procedure (like `scan`/`update`), not a script. Sequence:

1. **`spec-manager init`** — knowledge-base structure + `principles.md`. Idempotent (never clobbers).
2. **`code-graph build`** — always run (cheap; the detector needs it).
3. **`project_shape`** — run the detector, **print the evidence + recommendation**, then ask the engineer to confirm the branch or override.
4. **Branch:**
   - **Brownfield →** run **`scan`** at the **per-observable-behavior grain** (all candidates `proposed`, written as behavior records in `knowledge-base/specs/`, **never** `.feature` scaffolds in the code tree — those appear only on acceptance). Then **`behavior-graph build`**. Warn up front that scan over a large repo can take a while (it spawns discovery agents).
   - **Greenfield →** **skip `scan`**; ensure an empty behavior graph exists; print: *"Greenfield project — no inference run. Author behaviors forward as you build (spec-manager create)."* This is the **easier** path (intent-first/BDD), not an error.
5. **Summary** — report what was created, and (brownfield) a count of proposed candidates by category, **with the reminder that nothing needs review now** — the queue is drained lazily (SP3 on-hit, SP4 worklists).

### Resolved decisions worth knowing
- **Inference grain — per *observable behavior*** (one `proposed` behavior per observable behavior/scenario, anchored to a route/entry where applicable). *Not* per-feature (too coarse to map or validate) and *not* per-route/function (reintroduces the "tests mirror code" smell). This grain is what makes SP3's validate-on-hit usable — each candidate surfaces precisely on the code it exercises.
- **Re-scan cadence — lazy.** SP2 builds only the **one-time** bootstrap. Newly-written code acquires intent later via SP3's "touched code with no covering behavior → capture one?" prompt. One inference path; no second eager mechanism.
- **Additive, never clobber.** On a partially-onboarded repo, bootstrap infers candidates only for the *unspecced* areas; it never overwrites existing specs.

### Where `certainty` lands
`certainty` is **not** the intent/trust signal (the lifecycle `state` is). `certainty` is the **prioritizer** of the proposed pile — "high = a glance, low = real attention." On a boilerplate-heavy app, inferred candidates come out **low-certainty and skippable** — they sit harmlessly as `proposed` until someone cares.

---

## 4. SP3 — validate-on-hit (the lazy loop)

### The idea
At **wrap-up** (and available on demand), *after* the existing gated regression check on accepted behaviors, do two **non-gating** things that drain the `proposed` corpus organically as the team works:

1. **Validate-on-hit** — surface the proposed/confirmed behaviors a change actually **touches**, re-inferred against current code, for confirmation. **Bounded to the touched subset; prominent but skippable.**
2. **Recall gap** — flag touched code that **no** behavior covers, and offer to capture one.

Prominence ≠ fatigue *because Direction A bounds it to the touched subset* — "typically 2–3, not the whole backlog."

### `behavior-graph --surface --base <commit>` (shipped, deterministic core)
`behavior_graph.py` has a `--surface --base <commit>` mode. Given `changed = git diff base..HEAD` and `impact = code_graph_impact(changed)`, it emits three JSON buckets:

- **`affected_accepted`** — accepted behaviors whose `exercises ∩ impact ≠ ∅`. **Context only** — already handled (gated) by `--check` in the prior step; **not re-validated**.
- **`validate_candidates`** — the affected **proposed + confirmed** behaviors to confirm on hit:
  - *confirmed* — from `behavior.json` via `direction_a` (already projected by SP1).
  - *proposed* — read from spec frontmatter, **prefiltered** to those whose `entry` (or spec `related_code`) intersects `impact` (cheap), then each prefiltered candidate's entry-closure is computed and intersected with `impact`. **A proposed behavior with no `entry` is NOT surfaced here** — it is worklist-only (SP4).
  - Each entry carries enough to act: `behavior_id`, `state`, `spec_id`, `spec_path`, `title`, `entry`.
- **`recall_gaps`** — changed **source** files not in `covered`, where `covered = {paths in any behavior.json exercises} ∪ {every behavior's declared entry across all specs}` (the shared `_covered` helper). It may **over-flag** a file only transitively covered by a proposed candidate — that over-prompts, which is **the safe direction** ("never silently accumulate unguarded intent").

The query is **read-only and never fails the build**: missing graph / missing base / git error → empty buckets with a `note` field explaining why.

**Hit matching** uses the same **precise exercises-closure** rule accepted behaviors already use: a behavior is "affected" iff its entry-closure (code-graph dependency set) intersects the change's blast radius — so editing a lib the entry imports surfaces the behavior (dependency-level hits, not coarse entry-only match).

### The wrap-up Phase 3.5 interaction (shipped in `skills/wrap-up/SKILL.md`)
Phase 3.5 keeps its order, then adds surfacing **after** the gated `--check` (so a real regression is dealt with first):
1. (unchanged) `verify_links` hard-block.
2. (unchanged) `--build` then `--check --base BASE` — **gated** regression on affected accepted behaviors. A non-zero exit means an affected accepted behavior is `test-failed` and blocks until classified.
3. **(new) Surface** — run `behavior-graph --surface --base "$BASE" --project .`. Then, **non-gating and skippable**:
   - **`validate_candidates`:** present prominently; for each the engineer reviews, **re-infer it against current code** (read the `entry` file as it is *now*, produce a refreshed title/description) — never a stale bootstrap guess. Offer **confirm** / **edit then confirm** / **skip**. On confirm, bump `state` `proposed → confirmed` in the spec frontmatter. A candidate already `confirmed` stays `confirmed` and is noted as still owing a test. **Never auto-accept** — confirming intent does not author a test.
   - **`recall_gaps`:** if any, prompt *"these N touched file(s) have no covering behavior — capture one?"* → optionally author a new `proposed`/`confirmed` behavior. Skippable.
   - **`affected_accepted`** is context only — do not re-validate.
4. Continue to Phase 4 (security) regardless — **surfacing never blocks / never changes the exit code.**

**Refresh-on-hit is bounded** by Direction A and the whole step is skippable — "a large or sprawling change cannot trigger an unbounded agent fan-out." A newly-`confirmed` spec edit is an **artifact** (wrap-up commit 2), consistent with the behavior-aware staging rule (intent records are artifacts; only `accepted` tests are code).

---

## 5. SP4 — status, backlog & worklists (never-silent)

### Two distinct unifying commands — don't conflate them
- **`wrap-up`** = the unifying **do/sync** command (already exists; runs code-graph + docs + specs + behavior-graph build/check + security + commits, and now the §5 surfacing).
- **`status`** *(new top-level skill)* = the unifying **read-only check**: "where do I stand, what's outstanding?" — **no mutation, no commit** (except, on request, the generated `BACKLOG.md`). It aggregates **across skills**. It is justified as a new top-level skill (not a spec-manager extension) because it's genuinely cross-skill.

### `status` skill commands (from `skills/status/SKILL.md`)

| Command | Description |
|---------|-------------|
| `status` | Print the status summary **and refresh `BACKLOG.md`** |
| `status` (summary only) | Print the summary without rewriting `BACKLOG.md` — run `collect_status.py` and omit `--write-backlog` |
| `gaps` | List whole-repo uncovered source files |
| `review intent` | Work the proposed → confirm worklist, one at a time |
| `review tests` | Work the confirmed → write-a-test worklist, one at a time |

The canonical `status` invocation:
```bash
python "${CLAUDE_PLUGIN_ROOT}/skills/status/scripts/collect_status.py" \
  --project . --format text --write-backlog
```

### `collect_status.py` — the deterministic core (shipped)
`skills/status/scripts/collect_status.py` aggregates every bucket, renders `BACKLOG.md`, and emits the same data as JSON. **Read-only except for `--write-backlog`. Stdlib-only. Never crashes and never blocks — each source degrades independently to a `note`.**

- **CLI:** `--project <dir>` (required), `--format json|text` (default `text`), `--write-backlog` (regenerate `knowledge-base/BACKLOG.md`).
- **The buckets (each from a deterministic source):**
  - `behavior_counts` — counts keyed by every state in `BEHAVIOR_STATES` (`proposed / confirmed / accepted / quarantined / deprecated`).
  - `intent_worklist` — the `proposed` behaviors (the confirm-me list), **certainty-sorted, lowest first** (`certainty` defaults to `100` when absent — a proposed behavior with no certainty sorts last).
  - `test_owed_worklist` — the `confirmed` behaviors (the write-a-test list), sorted by `behavior_id`.
  - `gaps` — whole-repo uncovered files via `behavior-graph --gaps`; stored as `{total, sample}` (capped sample, `GAPS_SAMPLE = 20`).
  - `verify_failures` — from `verify_links.py --format json`.
  - `stale_fingerprints` — `behavior.json` behaviors whose any `exercises[*].freshness` ≠ current HEAD (advisory "re-run --build").
  - `open_security_findings` — from `findings.json`: entries with `status == "open"` (as `{id, title, severity, file}`).
- **Return dict:** `{version, project, behavior_counts, intent_worklist, test_owed_worklist, gaps, verify_failures, stale_fingerprints, open_security_findings, notes}`. `notes` collects per-source degradation messages — e.g. `"no behavior.json — run behavior-graph --build"`, `"no findings.json — run codebase-security-scan"`, `"no code-graph at knowledge-base/.graph/graph.json — run code-graph build"`.
- **Subtlety in the source:** `gaps_bucket` uses `check=True` (behavior-graph `--gaps` always exits 0), but `verify_bucket` must **NOT** use `check=True` because `verify_links` exits non-zero when it finds errors — "or the JSON would be lost." A real, load-bearing distinction encoded in the code.

### `behavior-graph --gaps` (shipped)
Whole-repo uncovered audit: `graph_files(project_dir) − covered`, sharing the **exact same `_covered` helper** as `--surface` (factored out so surface and gaps "cannot drift"). `covered = {exercises paths} ∪ {all declared entry values}`. Emits `{version, gaps: [...], total: N}`; read-only; empty list + a `note` on no graph. Purpose: find code with no captured intent — candidates to capture a behavior for.

### `BACKLOG.md` — the generated, git-tracked artifact
`knowledge-base/BACKLOG.md`, regenerated by `status --write-backlog` and by `wrap-up` (in its artifacts commit). Properties:
- **Generated, never hand-edited.** The header literally says: `> Generated by \`/freya-devkit:status\` — **do not edit**; run \`status\` to refresh.` — "can't rot into a lie like a manual TODO."
- **Git-tracked** (unlike the `behavior.json` cache, which lives under git-ignored `.graph/`). So the backlog is visible and shared: it shows up in the repo, **diffs in PRs**, and the team sees the outstanding work without running anything. *"It is to intent+security completeness what a coverage report is to test coverage."*
- **Sections** rendered by `render_backlog`: a one-line **Census** header (e.g. `12 proposed · 4 confirmed · 30 accepted · 3 tests owed · 5 open findings · N coverage gaps`), then **Behaviors to confirm** (id · title · spec table), **Tests owed** (id · title · spec), **Coverage gaps** (count + capped sample), **Open security findings** (id · severity · title · file). Each empty section renders `_None._`.

### The two worklists (the cold-tail drain)
The worklists follow spec-manager `review`'s one-at-a-time interaction style (present one item, act, next; stop anytime). They are **how the cold tail** — behaviors never hit by work, so never surfaced by SP3's validate-on-hit — gets drained **on purpose**.
- **`review intent` (proposed → confirm):** walk `intent_worklist` (certainty-sorted, lowest first). For each `proposed` behavior: re-read its code, present it, then **confirm** (bump `state` `proposed → confirmed`), **edit then confirm**, **quarantine/deprecate**, or **skip**.
- **`review tests` (confirmed → accept):** walk `test_owed_worklist`. For each `confirmed` behavior: link or write its test; once a real passing linked test exists, bump `state` `confirmed → accepted` (the wrap-up regression gate then governs it). **Never auto-author a test** — that is the engineer's work.

### `findings.json` (the SP4 substrate SP5 enriches)
SP4 also has `codebase-security-scan` emit a machine-readable **`findings.json`** alongside its prose report at `knowledge-base/security/codebase-security/findings.json`, so `status` reads structured data (no fragile prose parsing). Schema `{version, scanned_commit, report, findings: [{id, title, severity, status, file, line, spec_ref}]}`. A finding's `status` is `open` unless RESOLVED (lifecycle) or `intentional` (cross-referenced to a declarative spec). This is **foundational, not throwaway** — it is exactly what SP5 enriches.

---

## 6. SP5 — security ↔ behavior cross-reference

### The idea
`codebase-security-scan` **already** cross-references findings against **declarative** intentional design decisions (it reads `knowledge-base/specs/` and marks a finding `INTENTIONAL DESIGN` when a spec says so — e.g. no-password-fallback). That stays. SP5 **extends it to also consult the behavior graph**: an **`accepted`, test-backed behavior** that explains a flagged finding is the **strongest possible "intentional" evidence — a *verified guarantee*, not a prose claim.**

### The canonical example (BEH-003)
A scan flagging *"endpoint doesn't verify the user exists"* should be silenced by: *"accepted behavior BEH-003, verified by a passing test, says the uniform response is the intended anti-enumeration guarantee."* The passing test **proves** the flagged pattern is the intended, working behavior.

### The one hard rule: **only `accepted` (verified) behaviors downgrade a finding**
- An **`accepted`** behavior (confirmed intent **and** a passing linked test) whose intent explains the finding downgrades it to **intentional (verified)**.
- A **`confirmed`** behavior (intent confirmed, test owed) at most adds an **advisory note** — the finding **stays open** until a test verifies it.
- `proposed`/unverified states **never** silence a finding.

### `behavior-graph --covering <file>` (shipped, deterministic prefilter)
Returns the **`accepted`** behaviors in `behavior.json` whose `exercises` include the given project-relative file:
```json
{"version": 1, "file": "app/api/.../route.ts",
 "covering": [{"behavior_id": "BEH-003", "spec_id": "SPEC-001", "coverage": "static"}]}
```
- Filters to `state == "accepted"` (the verified bar). `coverage` is reported (`observed` is stronger evidence the path actually ran than `static`) but does **not** change membership — `accepted` is the gate.
- Read-only; empty `covering` (with the file echoed) when there's no graph or no accepted behavior touches the file. Never raises.
- It **bounds** the scan's search to behaviors that actually touch the flagged code; the agent then reads those behaviors' specs for intent and judges relevance.

### The cross-reference procedure (a `codebase-security-scan` SKILL.md extension)
Mirrors the existing `check-specs` flow (deterministic candidate-gather → agent relevance judgment → annotate in place). For each finding, after the existing declarative-spec check:
1. Run `behavior-graph --covering <finding.file>` to get candidate accepted behaviors.
2. For each candidate, read its intent and judge: **does this behavior's verified intent explain this finding?**
3. On a match: mark the finding **intentional**, record `behavior_ref: BEH-NNN`, and add a note *"verified by passing test BEH-NNN (SPEC-MMM)."* **Keep the finding in the report (annotate, don't delete).**
4. **Evidence ranking:** an accepted-behavior match is the **strongest** evidence — it stands on its own even when no declarative spec covers the finding. When both apply, prefer the behavior reference (verified > claimed) and may record both.
5. A `confirmed` match adds only an advisory note (*"intended per BEH-NNN, but test owed — not yet verified"*); the finding **stays open**.

### `findings.json` schema extension
SP5 adds an optional **`behavior_ref`** field (the `BEH-NNN` of the accepted behavior that explains the finding). `status: intentional` as before. Because `status`/`collect_status.py` already treat any non-`open` finding as not-outstanding, a behavior-explained finding **drops from the open count automatically**; `behavior_ref` vs `spec_ref` records *which kind* of evidence (verified vs declarative) for auditability.

### Safety posture
"**Safe by construction:** downgrade = annotate + set `status: intentional`, never delete; a misjudgment is visible and reversible in the report, not a vanished finding." A finding on code no accepted behavior covers stays `open`. Open findings that a behavior does *not* explain flow into the SP4 backlog.

---

## 7. How the pieces fit (the end-to-end adoption arc)

1. **Day one (SP2 bootstrap):** infer a full corpus of `proposed` candidate behaviors (brownfield) — cheap, one-time, nothing trusted, **nothing to review yet**. Greenfield skips inference and says so.
2. **In the flow of work (SP3 validate-on-hit):** every wrap-up surfaces the 2–3 proposed/confirmed behaviors *this change touched*, re-inferred against current code, for a one-action confirm (`proposed → confirmed`). Touched code with no covering behavior gets a recall-gap prompt. Correct intent accumulates organically. All advisory — the only thing that blocks is an `accepted` behavior going `test-failed`.
3. **The cold tail (SP4 worklists + status):** `status` prints the census + refreshes the git-tracked `BACKLOG.md` so the whole team sees "18 behaviors owe tests / 3 open findings." `review intent` and `review tests` grind the never-hit tail one behavior at a time; `gaps` finds uncaptured code.
4. **Security payoff (SP5):** once a behavior reaches `accepted` (has a passing test), it becomes verified evidence that silences the security findings it explains — a verified guarantee, not a prose claim.

The whole design's promise (its final acceptance criterion): **"No fabricated authoritative intent: every inferred behavior is `proposed` until a human confirms; no scaffolds written into the code tree by inference."**

---

## 8. Sanitization note
No proprietary viva-croatia business/domain content, secrets, or customer data was reproduced. The `viva-croatia-testbed` is referenced by path only as the dogfooding proving ground (as the sources do); the production webapp is noted as off-limits (as the sources state). Route paths like `app/api/auth/passkey/authenticate/start/route.ts` and `app/api/posts/[id]/lock/route.ts` appear verbatim in the design docs as generic illustrative anchors and carry no proprietary content.
