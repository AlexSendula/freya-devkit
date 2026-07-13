# P4a — ADR support + ADR-aware conflict checks (design)

**Status:** Draft for review
**Date:** 2026-07-01
**Parent design:** `docs/design/behavior-layer/00-vision.md` (§4 intent taxonomy — cross-cutting ADRs; §5 authority hierarchy + "reference links to decisions, never restates"; §8 Tier-2 conflict checking / the deferred ADR-awareness; §9 Phase 4 — Expansion).
**Track:** Phase 4 — Expansion, sub-project **P4a** (of P4a ADR support / P4b declarative-drift / P4c more adapters / P4d calibrated enforcement). The first Phase-4 leaf; unblocks P4b's cross-cutting scoping and turns G3 from ADR-*ready* into ADR-*aware*.
**Depends on:** the frontmatter parser (`frontmatter.parse_frontmatter`, `validate`); the G3 machinery (`contradictions.py` `build_context` / `resolve` / `prior`, and its append-only `contradiction-resolutions.jsonl`); the `INTENT-NNN` authoring helper (`intent.py`) as the pattern for `adr.py`. Independent of P4b/P4c.

---

## 1. Goal

Give cross-cutting **Architecture Decision Records** a real home and make the governance layer *see* them. Two halves:

1. **Capture** — an `ADR-NNN` format (decision · rationale · rejected alternatives · revisit conditions), an `adr create` flow mirroring `spec create`, a gather (`load_adrs`), a `decisions/README.md` index, and deterministic integrity checks. Replaces today's empty `knowledge-base/decisions/` scaffold ("no tooling reads them yet").
2. **Enforce** — extend G3's contradiction check so a changed spec is compared against the ADRs, and a changed ADR is compared against the principles above it. Resolves vision §8's deferred ADR-awareness: *"ADR-awareness is deferred until the ADR phase ships a real `decisions/` format."* It now has.

## 2. The scoping decision — always-global, not category-scoped

**How does the check decide which ADRs are relevant to a changed spec? It doesn't scope — it shows the LLM *all active ADRs*.** This reverses an earlier `applies_to`-by-category sketch, on the strength of a three-lens research pass (prior art / our data / adversarial critique):

- **Scoping only decides what reaches the LLM; the LLM makes the contradiction judgment.** Over-scoping (a filter that excludes a relevant ADR) is a **silent miss** — the exact failure this governance layer exists to prevent — and is unrecoverable. Under-scoping (an irrelevant ADR reaches the LLM) is just **noise** it dismisses in one line. A false negative here is far worse than a false positive.
- **ADRs are cross-cutting *by definition*.** Forcing them into single-domain categories is a category error: an author cannot enumerate at write-time every future spec-category an ADR will matter for — if they could, the LLM check would be unnecessary.
- **Volume is tiny** (single digits now; <20 realistically). The entire ADR corpus is a few thousand tokens; scoping saves nothing and costs silent-miss risk.
- **Prior art agrees:** Nygard/adr-tools/MADR keep ADRs a flat, status-only list with scope in prose; categorical/tag scoping is documented as prone to *tag rot* and the *"cross-cutting decision has no home"* failure.

**Consequences of always-global:**
- No `applies_to` field. The only "filter" is **lifecycle/authority status**: G3 compares against `accepted`, non-`superseded`/`deprecated` ADRs only.
- The category-vocabulary problem (categories are not an enforced enum in code) is **moot for ADRs** — we do not scope by category, so no `CATEGORIES` enum, no ADR-side category validation, no change to peer-*spec* matching.
- `tags` and `related_code` may appear on ADRs as **optional human-navigation / future-P4b metadata only** — never a G3 filter.
- If ADR volume ever crosses ~30 and noise becomes a real complaint, the *only* safe narrowing lever is an **opt-out** (`skip_for`), never opt-in — keeping the failure mode "noise," never "silence." **YAGNI now**; recorded for later.

## 3. ADR format & storage

`knowledge-base/decisions/ADR-NNN-kebab-name.md`. ID = the next sequential `ADR-NNN` across existing files (allocated at authoring, like `INTENT-NNN`; deterministic duplicate detection in `adr verify`).

```yaml
---
id: ADR-001
title: Use PostgreSQL for primary storage
status: accepted            # proposed | accepted | superseded | deprecated
created: 2026-07-01
updated: 2026-07-01
tags: [database]            # optional — human navigation only, NOT a G3 filter
supersedes: ADR-000         # optional ADR cross-link
superseded_by: ADR-014      # optional — set when this ADR is retired
related_code:               # optional — future P4b (declarative-drift) hook, NOT a G3 filter
  - prisma/schema.prisma
---
# ADR-001: Use PostgreSQL for primary storage
## Decision
## Rationale
## Rejected Alternatives
## Revisit Conditions
```

**Lifecycle mirrors behaviors — only `accepted` is authoritative.** `proposed` records intent under review (not yet constraining); `accepted` constrains specs and is compared by G3; `superseded`/`deprecated` are excluded from the comparison set (an author retires an ADR by setting `status: superseded` + `superseded_by`, and/or adding the successor's `supersedes`). Human-authored via `adr create` ⇒ starts `accepted` (as a user-created spec is certainty 100).

**Body = the four sections** (decision · rationale · rejected alternatives · revisit conditions). *Revisit Conditions* is what turns a later Postgres→Mongo swap into a **reviewable event** (vision §5), not a silent regeneration.

## 4. Validation & authoring

### 4.1 `ADR_SCHEMA` (in `frontmatter.py`, beside `SPEC_SCHEMA`)
- **required:** `id: str`, `title: str`, `status: str`
- **optional:** `created: str`, `updated: str`, `tags: list`, `supersedes: str`, `superseded_by: str`, `related_code: list`
- `status` validated against the closed set `{proposed, accepted, superseded, deprecated}`.
- Unknown fields preserved, never an error (same round-trip rule as specs). **Fails loud** (`FrontmatterError` / validation errors) on a malformed ADR rather than silently dropping fields.

### 4.2 `adr.py` (new script, mirrors `intent.py`)
- **`adr new --title T [--status accepted] [--supersedes ADR-NNN] [--tag t]… [--project .]`** — allocate the next `ADR-NNN`, write the scaffold with the four `## ` headings as `TODO:` stubs, print the path. Rejects an out-of-set `--status` (like `intent.py` rejects a non-`BEH-NNN`).
- **`load_adrs(project) → (adrs, warnings)`** — parse every `decisions/ADR-*.md`; each entry `{id, title, status, tags, related_code, supersedes, superseded_by, body}` (body = the section text the LLM judges against). A malformed ADR is a **surfaced warning**, never a silent drop — G3's no-silent-miss guarantee. `active_adrs(project)` filters to `accepted`.
- **`adr list [--format table|json] [--project .]`** — feeds/regenerates the `decisions/README.md` index.
- **`adr verify [--project .]`** — deterministic Tier-1 integrity, non-zero on failure: duplicate `ADR-NNN`; `supersedes` / `superseded_by` that don't resolve to a real ADR; `status` outside the set; malformed frontmatter. Cheap and certain — runs beside `verify_links` in spec-manager `verify` and (hard-block) at wrap-up.

### 4.3 `spec-manager adr create <name>` (interactive, mirrors `spec create`)
One question at a time: decision / rationale / rejected alternatives / revisit conditions / (optional) tags / supersedes. Calls `adr.py new`, fills the body, updates `decisions/README.md`. Starts `accepted`.

## 5. The G3 extension (the payoff)

### 5.1 Spec changed → compare against ADRs
`contradictions.build_context(project, spec_id)` gains **`adrs`** (all active ADRs) and **`adr_warnings`**:
```json
{"spec":"SPEC-005","category":"auth","principles":[…],
 "adrs":[{"id":"ADR-001","title":"…","body":"…"}],
 "peers":[…],"adr_warnings":[]}
```
The agent judges the changed spec against each principle, **each active ADR**, and each same-category peer.

### 5.2 ADR changed → compare against principles (symmetry)
An ADR now outranks specs, so an ADR that itself contradicts a **principle** must be caught — else ADRs are the one authoritative artifact nothing governs. New **`build_adr_context(project, adr_id) → {adr, principles, peer_adrs}`** (`peer_adrs` = the *other* active ADRs): a changed ADR is judged against the principles above it and its peer ADRs (same tier). Entry points: interactively at `adr create`, and — since an ADR is a markdown file a human may edit directly — for any changed `decisions/**` in batch at wrap-up (no separate `adr update` command; a direct edit is caught by the batched check).

### 5.3 Authority & resolution semantics
Authority order (refines vision §5's specs+decisions tier): **principle > ADR > spec**.

| Changed item | Contradicts | Resolution (default) |
|---|---|---|
| spec | a principle | fix the spec (or consciously amend the principle) |
| spec | an **ADR** | **fix the spec** (ADR outranks) — or consciously amend the ADR |
| spec | a peer spec (same category) | **reconcile** — fix either side, or refute |
| **ADR** | a principle | **fix the ADR** (or amend the principle) |
| **ADR** | a peer ADR | **reconcile** |

### 5.4 Resolution machinery — reuse, no schema change
`resolve` / `prior` are unchanged: `--against` is free-form, so **`ADR-007`** slots into the existing `(spec, against)` keying beside `principle:2` / `SPEC-003`. A changed-ADR finding is keyed `(ADR-001, against)` where `against` is `principle:N` or a peer `ADR-NNN` — the same `contradiction-resolutions.jsonl`, same latest-wins/`superseded` retirement, same LLM-first triage on recurrence. `ADR-NNN` is documented as a valid `--spec` and `--against` value. **No new JSONL field, no new module.**

## 6. Triggers & gate posture

Identical to G3 (vision §8), extended to ADRs:
- **Interactive** — at spec-manager `create`/`update` (spec vs ADRs) **and** `adr create` (ADR vs principles/peer-ADRs). Cheapest place to catch a conflict.
- **Batched — wrap-up Phase 3.5 step 6** — over changed `specs/**` *and* changed `decisions/**` this cycle, as the same **resolve-to-proceed** step. Order unchanged: deterministic facts (G1 + links + `adr verify` + accepted-behavior run) → principle judgment (G2) → intent-coherence judgment (G3, now ADR-aware).

**Posture:** the contradiction judgment is model work → **advisory / procedural** (agent-honored, never a script hard-block, never auto-fail on model confidence). Each finding **resolved to proceed** — fix / refute / reconcile / amend. `adr verify` (deterministic) **does** hard-block. Fail-open on no principles / no ADRs / tooling error.

## 7. Error & edge handling

- **No ADRs** (empty `decisions/`) → `active_adrs` empty → `adrs: []` → the ADR comparison **no-ops**; G3 behaves exactly as today. Zero-regression for projects without ADRs.
- **Malformed ADR** → surfaced in `adr_warnings` (never silently excluded) and hard-flagged by `adr verify`.
- **Only `proposed` ADRs** → not authoritative → excluded from the set (like a `proposed` behavior isn't run).
- **`superseded`/`deprecated` ADR** → excluded from the comparison set; still parseable/listable for history.
- **`supersedes`/`superseded_by` dangling** → `adr verify` failure (deterministic), not a silent skip.
- **`adr new` on a fresh project** → creates `decisions/` if absent (like `intent.py` creates `intents/`).

## 8. Scope

**In scope:** the `ADR-NNN` format + lifecycle; `ADR_SCHEMA`; `adr.py` (`new` / `list` / `verify` / `load_adrs` / `active_adrs`); `spec-manager adr create`/`list`/`verify` wiring + `adr-template.md`; `init` scaffolding of `decisions/README.md` and the rewritten `decisions-readme.md`; the G3 extension (`build_context` gains `adrs`; new `build_adr_context`) with the authority table §5.3; wrap-up step-6 inclusion of ADRs and changed `decisions/**`; always-global comparison; deterministic ADR integrity.

**Out of scope:** **P4b** declarative-drift / code-vs-declared-intent (the other Phase-4 item; `related_code` on ADRs is only the hook); **P4c** more language/runner adapters; **P4d** calibrated model-confidence hard-gating (evidence-gated); category-vocabulary enforcement (moot under always-global); `applies_to`/`skip_for` scoping (YAGNI — opt-out only if volume ever demands); a bidirectional spec↔ADR reference index (prose links suffice, per prior art).

## 9. Testing

- **`adr.py` unit tests** (stdlib `unittest`, parallel to `test_intent.py` / `test_contradictions.py`): `new` allocates the next id and renders the four-section scaffold; `load_adrs` parses a well-formed ADR, filters `active_adrs` to `accepted`, and turns a malformed ADR into a **warning not a drop**; `verify` catches a duplicate id, a dangling `supersedes`/`superseded_by`, and a bad `status`; `_next_id` on an empty dir returns `ADR-001`.
- **`frontmatter.py` unit tests:** `ADR_SCHEMA` validation accepts a well-formed ADR and rejects a bad `status` / missing `title`; block-style `related_code`/`tags` round-trip.
- **`contradictions.py` unit tests:** `build_context` includes `adrs` (active only) and excludes `superseded`; `build_adr_context` returns principles + peer ADRs for a changed ADR; both no-op cleanly with no ADRs.
- **Agent judgment (the contradiction + triage) is validated by the testbed dogfood, not a unit test:** a spec decision contradicting an ADR → surfaces + resolve-to-proceed with default *fix-the-spec*; `--against ADR-NNN` logged; re-run unchanged → auto-cleared; rewrite → retired; an ADR contradicting a principle → surfaces as *fix-the-ADR*; no-ADR project → no change. Production webapp off-limits; testbed branch, restored after.

## 10. Acceptance criteria

- [ ] `adr new` allocates the next `ADR-NNN` and writes a valid scaffold (four sections, `status: proposed` or `accepted`); `ADR_SCHEMA` fails loud on a malformed ADR.
- [ ] `load_adrs` returns active ADRs and surfaces a malformed ADR as a **warning, never a silent drop**; `active_adrs` filters to `accepted`.
- [ ] `adr verify` exits non-zero on a duplicate id, a dangling `supersedes`/`superseded_by`, or a bad `status`; it runs in spec-manager `verify` and hard-blocks at wrap-up.
- [ ] `build_context` includes **all active ADRs** (no category scoping), excludes `superseded`/`deprecated`, and no-ops with no ADRs; `build_adr_context` returns principles + peer ADRs for a changed ADR.
- [ ] The contradiction check compares a changed spec against ADRs and a changed ADR against principles/peer-ADRs, at `create`/`update` and wrap-up step 6; it is procedural/advisory and does not complete wrap-up while a finding is unresolved.
- [ ] Resolution respects §5.3: spec-vs-ADR → fix the spec; ADR-vs-principle → fix the ADR; peer → reconcile. `ADR-NNN` works as `--spec`/`--against` with **no JSONL schema change**.
- [ ] `spec-manager init` scaffolds `decisions/README.md`; `decisions-readme.md` no longer says "no tooling reads them yet"; a new `adr-template.md` documents the format.
- [ ] ADR files stage as **artifacts** (commit 2) at wrap-up.
- [ ] Dogfooded on the testbed: spec-vs-ADR contradiction surfaces/resolves; ADR-vs-principle surfaces; refute→logged; re-run→auto-cleared; rewrite→retired; no-ADR project unchanged.

## 11. Open questions

None blocking. The comparison is always-global by design (§2): recall is total, the LLM filters relevance, and the only tuning lever (opt-out) is deferred until volume proves it necessary. The contradiction judgment and auto-clear triage are model work — the same kind G2/G3 already make — bounded by resolve-to-proceed with the human as calibration, and validated by the dogfood. The **P4b declarative-drift** check is the explicit successor that consumes ADR `related_code`.
