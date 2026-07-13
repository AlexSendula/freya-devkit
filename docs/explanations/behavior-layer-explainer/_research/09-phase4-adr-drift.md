# Phase 4 — ADR support (P4a) & Declarative-drift (P4b)

> Research brief for the Behavior-Layer explainer webapp. Audience: an engineer who has never seen this feature.
> Everything below is copied verbatim from source files or paraphrased with the exact identifiers preserved. Source files:
> - `docs/superpowers/specs/2026-07-01-p4a-adr-support-design.md`
> - `docs/superpowers/specs/2026-07-01-p4b-declarative-drift-design.md`
> - `docs/superpowers/plans/2026-07-01-p4a-adr-support.md`
> - `docs/superpowers/plans/2026-07-01-p4b-declarative-drift.md`
> - `skills/spec-manager/scripts/adr.py`
> - `skills/spec-manager/scripts/drift.py`
> - `skills/spec-manager/scripts/contradictions.py`
> - (cross-refs) `skills/spec-manager/scripts/resolution_log.py`

---

## 0. Where Phase 4 sits

Phase 4 is the **Expansion** track of the behavior layer. It has four leaves:

- **P4a** — ADR support (this brief)
- **P4b** — declarative-drift (this brief)
- **P4c** — more adapters (out of scope here)
- **P4d** — calibrated enforcement (out of scope here)

P4a is described as *"The first Phase-4 leaf; unblocks P4b's cross-cutting scoping and turns G3 from ADR-*ready* into ADR-*aware*."* P4b is the *"Successor to P4a — consumes the ADR `related_code` hook it added."*

Both checks share one **posture**: model judgment → **advisory / procedural** (agent-honored, never a script hard-block, never auto-fail on model confidence). Each finding is **resolved to proceed** — fix / refute / reconcile / amend. Both **fail-open** on tooling error / no inputs.

---

# PART A — P4a: ADR support + ADR-aware conflict checks

## A1. The problem it solves

Before P4a, `knowledge-base/decisions/` was an **empty, git-tracked scaffold** — the design says the old note read *"no tooling reads them yet."* Architecture Decision Records (ADRs) had no format and the governance layer could not *see* them. The vision had explicitly **deferred** ADR-awareness: *"ADR-awareness is deferred until the ADR phase ships a real `decisions/` format."* P4a ships that format.

P4a has two halves:
1. **Capture** — an `ADR-NNN` format (decision · rationale · rejected alternatives · revisit conditions), an `adr create` flow mirroring `spec create`, a gather (`load_adrs`), a `decisions/README.md` index, and deterministic integrity checks.
2. **Enforce** — extend the G3 contradiction check so a changed spec is compared against the ADRs, and a changed ADR is compared against the principles above it.

## A2. The ADR format & storage

**Location:** `knowledge-base/decisions/ADR-NNN-kebab-name.md`. ID = the next sequential `ADR-NNN` across existing files (allocated at authoring, like `INTENT-NNN`; deterministic duplicate detection in `adr verify`).

Frontmatter (from the design, sanitized to a neutral example):

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

**Body = the four sections:** Decision · Rationale · Rejected Alternatives · Revisit Conditions. *Revisit Conditions* is what turns a later swap (e.g. Postgres→Mongo) into a **reviewable event**, not a silent regeneration.

**Lifecycle mirrors behaviors — only `accepted` is authoritative:**
- `proposed` — records intent under review; **not yet constraining**.
- `accepted` — constrains specs and is compared by G3.
- `superseded` / `deprecated` — **excluded** from the comparison set; still parseable/listable for history.

Human-authored via `adr create` ⇒ starts `accepted` (as a user-created spec is certainty 100). An author retires an ADR by setting `status: superseded` + `superseded_by`, and/or adding the successor's `supersedes`.

## A3. `ADR_SCHEMA` and validation (in `frontmatter.py`)

Two new names live beside `SPEC_SCHEMA`:

```python
ADR_STATES = ("proposed", "accepted", "superseded", "deprecated")

ADR_SCHEMA = {
    "required": {"id": str, "title": str, "status": str},
    "optional": {"created": str, "updated": str, "tags": list,
                 "supersedes": str, "superseded_by": str, "related_code": list},
}
```

- **required:** `id: str`, `title: str`, `status: str`
- **optional:** `created`, `updated`, `tags` (list), `supersedes`, `superseded_by`, `related_code` (list)
- `status` validated against the closed set `{proposed, accepted, superseded, deprecated}`.
- Unknown fields preserved, never an error (same round-trip rule as specs). **Fails loud** (`FrontmatterError` / validation errors) on a malformed ADR rather than silently dropping fields.
- `validate_adr(frontmatter: dict) -> list` (empty == valid) reuses `validate` for required/optional typing, then adds the ADR `status` enum check.

## A4. `adr.py` — the authoring/gather/integrity script

Header (verbatim from `adr.py`): *"Cross-cutting ADRs are compared ALWAYS-GLOBAL (no category scoping) ... Only lifecycle filters — `active_adrs` keeps `status == "accepted"`."*

Key module constants:
- `DECISIONS_RELDIR = "knowledge-base/decisions"`
- `_ID_RE = re.compile(r"ADR-(\d+)")`
- `_SECTIONS = ("Decision", "Rationale", "Rejected Alternatives", "Revisit Conditions")`

**Functions / signatures (verbatim):**
- `_decisions_dir(project)` → `Path(project) / DECISIONS_RELDIR`
- `_next_id(decisions_dir: Path) -> str` — scans `ADR-*.md`, returns `f"ADR-{n + 1:03d}"`; on an empty dir returns `ADR-001`.
- `_slug(title: str) -> str`
- `render_record(adr_id, title, status, day, tags=None, supersedes=None) -> str` — renders frontmatter + the four `## ` headings, each body section a `TODO: {sec.lower()}.` stub.
- `new_record(project, title, status, day, tags=None, supersedes=None) -> str` — creates `decisions/` if absent, allocates the next id, writes `{adr_id}-{_slug(title)}.md`, returns the path string.
- `load_adrs(project)` → `(adrs, warnings)`. Each adr dict: `{id, title, status, tags, related_code, supersedes, superseded_by, body, path}` (body = section text stripped). A malformed ADR is a **surfaced warning and excluded — never a SILENT drop**.
- `active_adrs(project)` → `([a for a in adrs if a["status"] == "accepted"], warnings)` — the authoritative set G3 compares against.
- `verify_adrs(project) -> list` (errors; empty == clean) — deterministic Tier-1 integrity.
- `render_index(project) -> str` — regenerates the decisions index as a markdown table (`# Architecture Decision Records`, `| ID | Title | Status |`).

**CLI commands:**
- `adr new --title T [--status accepted] [--supersedes ADR-NNN] [--tag t]… [--date …] [--project .]`
  - flags: `--title`/`-t` (required), `--status` (default `accepted`, rejects out-of-set via `_status` → `argparse.ArgumentTypeError`), `--tag` (append → `tags`), `--supersedes`, `--date` (→ `day`), `--project`/`-p` (default `.`).
- `adr verify [--project .]` — prints each error to stderr, `sys.exit(1 if errs else 0)`. Hard-blocks at wrap-up.
- `adr list [--format table|json] [--project .]` — feeds/regenerates `decisions/README.md`.

**`adr verify` catches (deterministic, non-zero on failure):**
- duplicate `ADR-NNN` (`"{f.name}: duplicate id {aid} (also in {ids[aid]})"`)
- `supersedes` / `superseded_by` that **do not resolve** to a known ADR id (`"{fname}: {field} '{ref}' does not resolve to a known ADR"`)
- `status` outside the set / malformed frontmatter (`"{f.name}: unparseable frontmatter: {e}"`)

**Interactive flow:** `spec-manager adr create <name>` asks one question at a time — decision / rationale / rejected alternatives / revisit conditions / (optional) tags / supersedes → calls `adr.py new` → fills the body → updates `decisions/README.md`. Starts `accepted`.

## A5. The G3 extension (the payoff)

Authority order (refines the vision's specs+decisions tier): **principle > ADR > spec**.

### A5.1 Spec changed → compare against ADRs (`build_context`)

`contradictions.build_context(project, spec_id)` gained **`adrs`** (all active ADRs) and **`adr_warnings`**. Example return shape:

```json
{"spec":"SPEC-005","category":"auth","principles":[…],
 "adrs":[{"id":"ADR-001","title":"…","body":"…"}],
 "peers":[…],"adr_warnings":[]}
```

The agent judges the changed spec against each principle, **each active ADR**, and each same-category peer. `adrs` is built as `[{"id": a["id"], "title": a["title"], "body": a["body"]} for a in adrs]` from `active_adrs(project)`. The key is present in **both** the found and not-found branches.

### A5.2 ADR changed → compare against principles (symmetry) (`build_adr_context`)

Because an ADR now outranks specs, an ADR that itself contradicts a **principle** must be caught — *"else ADRs are the one authoritative artifact nothing governs."* New:

`build_adr_context(project, adr_id) -> {adr, principles, peer_adrs, adr_warnings, [note]}` where `peer_adrs` = the *other* active ADRs (self excluded). If the ADR isn't found/active it returns a `note: "ADR {adr_id} not found or not accepted"`.

Entry points: interactively at `adr create`, and — since an ADR is a markdown file a human may edit directly — for any changed `decisions/**` in batch at wrap-up (**no separate `adr update` command**; a direct edit is caught by the batched check). CLI: `contradictions.py adr-context --adr ADR-NNN`.

### A5.3 Resolution machinery — reuse, no schema change

`resolve` / `prior` are **unchanged**: `--against` is free-form, so **`ADR-007`** slots into the existing `(spec, against)` keying beside `principle:2` / `SPEC-003`. Same `contradiction-resolutions.jsonl`, same latest-wins/`superseded` retirement. `ADR-NNN` is a valid `--spec` and `--against` value. **No new JSONL field, no new module.**

The `resolve` CLI help strings make this explicit:
- `--spec required=True, help="changed item: SPEC-NNN or ADR-NNN"`
- `--against required=True, help="conflicting item: principle:N, SPEC-NNN, or ADR-NNN"`

Authority / resolution table (design §5.3):

| Changed item | Contradicts | Resolution (default) |
|---|---|---|
| spec | a principle | fix the spec (or consciously amend the principle) |
| spec | an **ADR** | **fix the spec** (ADR outranks) — or consciously amend the ADR |
| spec | a peer spec (same category) | **reconcile** — fix either side, or refute |
| **ADR** | a principle | **fix the ADR** (or amend the principle) |
| **ADR** | a peer ADR | **reconcile** |

## A6. THE big design decision — always-global, not category-scoped

**How does the check decide which ADRs are relevant to a changed spec? It doesn't scope — it shows the LLM *all active ADRs*.** This reversed an earlier `applies_to`-by-category sketch. The four reasons (this is the heart of the "why"):

1. **Scoping only decides what reaches the LLM; the LLM makes the contradiction judgment.** Over-scoping (a filter that excludes a relevant ADR) is a **silent miss** — *"the exact failure this governance layer exists to prevent"* — and is **unrecoverable**. Under-scoping (an irrelevant ADR reaches the LLM) is just **noise** it dismisses in one line. *A false negative here is far worse than a false positive.* (This is the cardinal sin for a governance tool.)
2. **ADRs are cross-cutting *by definition*.** Forcing them into single-domain categories is a category error: *"an author cannot enumerate at write-time every future spec-category an ADR will matter for — if they could, the LLM check would be unnecessary."*
3. **Volume is tiny** (single digits now; <20 realistically). *"The entire ADR corpus is a few thousand tokens; scoping saves nothing and costs silent-miss risk."*
4. **Prior art agrees:** Nygard/adr-tools/MADR keep ADRs a flat, status-only list with scope in prose; categorical/tag scoping is documented as prone to *tag rot* and the *"cross-cutting decision has no home"* failure.

**Consequences:**
- **No `applies_to` field.** The only "filter" is lifecycle/authority status: G3 compares against `accepted`, non-`superseded`/`deprecated` ADRs only.
- `tags` and `related_code` may appear on ADRs as **optional human-navigation / future-P4b metadata only** — never a G3 filter.
- If ADR volume ever crosses ~30 and noise becomes a real complaint, the *only* safe narrowing lever is an **opt-out** (`skip_for`), never opt-in — keeping the failure mode "noise," never "silence." **YAGNI now**; recorded for later.

## A7. Triggers, gate posture, edges

- **Interactive** — spec-manager `create`/`update` (spec vs ADRs) **and** `adr create` (ADR vs principles/peer-ADRs). Cheapest place to catch a conflict.
- **Batched** — wrap-up **Phase 3.5 step 6**, over changed `specs/**` *and* changed `decisions/**`, as the same resolve-to-proceed step. Order: deterministic facts (G1 + links + **`adr verify`** + accepted-behavior run) → principle judgment (G2) → intent-coherence judgment (G3, now ADR-aware).
- **Posture:** the contradiction judgment is model work → **advisory / procedural** (never a script hard-block). `adr verify` (deterministic) **does** hard-block. Fail-open on no principles / no ADRs / tooling error.

**Edges (zero-regression guarantees):**
- **No ADRs** (empty `decisions/`) → `active_adrs` empty → `adrs: []` → the ADR comparison **no-ops**; G3 behaves exactly as today.
- **Malformed ADR** → surfaced in `adr_warnings` (never silently excluded) and hard-flagged by `adr verify`.
- **Only `proposed` ADRs** → not authoritative → excluded (like a `proposed` behavior isn't run).
- **`superseded`/`deprecated`** → excluded from comparison; still parseable/listable.
- **dangling `supersedes`/`superseded_by`** → `adr verify` failure, not a silent skip.
- **`adr new` on a fresh project** → creates `decisions/` if absent.

---

# PART B — P4b: Declarative-drift check

## B1. The problem it solves

P4b guards **declarative intent — the intent that has no test to fail** — against the code drifting away from it. Behaviors are guarded by their tests (Direction A, shipped); a spec's `intentional_decisions`, a purely-declarative spec's prose, and an ADR's decision are **not**. P4b is *"the honest fallback for the genuinely untestable."*

The question it asks at wrap-up: **does the changed code contradict a declared intent that governs it?** Each finding surfaces as **resolve-to-proceed** (fix / amend / refute), same posture as G2/G3.

## B2. THE big design decision — blast-radius-scoped, DELIBERATELY not always-global

**The comparison is scoped by `related_code ∩ blast-radius`, NOT always-global.** This is a **conscious asymmetry with P4a's G3**, and the design argues it is correct:

- **G3 is intent-vs-intent** with no code anchor and a tiny item count → always-global won (recall over precision; the LLM filters).
- **P4b is code-vs-intent, triggered by a code change.** Its natural scope is *the declared intent governing the code that changed* = `related_code ∩ blast-radius`. Always-global here would re-judge **every** declared decision against **every** change — *"the whole-repo re-derivation the vision explicitly rejects as too noisy to trust"* (keeps the check incremental and quiet enough to be trusted).

**Honest recall gap (accepted).** Because scope follows `related_code`:
- A declared decision or ADR with **no `related_code` is invisible** to this check (the spec-template already warns: *"A declarative spec with no `related_code` is invisible to that check"*).
- Drift introduced in code **not in, and not a dependent of,** a decision's `related_code` is not caught — the same recall gap Direction A has.
- Mitigations: keep `related_code` current; the **preferred** long-term path stays *promoting a testable decision into a guard scenario*; and `drift gaps` makes the un-scopable set **visible** rather than silent.

## B3. Drift targets — all decisions + accepted ADRs

For a changed set, a **drift target** is any of the following whose `related_code` intersects the blast radius:
- **A spec's `intentional_decisions`** — for *every* non-`deprecated` spec, not only purely-declarative ones. A behavioral spec's decisions are equally untested and driftable.
- **A purely-declarative spec** (no accepted behaviors) — its purpose/scope prose plus decisions.
- **An accepted ADR** — via its `related_code` (the P4a hook). `proposed`/`superseded`/`deprecated` ADRs are excluded (mirrors `active_adrs`).

A target with **empty `related_code` is NOT checked here** — it surfaces in `drift gaps` instead.

## B4. The blast radius — reuse Direction A exactly

Identical mechanism to behavior-graph's Direction A, with `related_code` substituted for behaviors' `exercises`:

1. `changed = git diff $BASE..HEAD --name-only` (project-relative).
2. `impact = code-graph --impact <changed>` — the union of changed files + their direct + transitive **dependents**. A related_code file is "hit" if it *is* changed or *depends on* something changed — the correct direction (the decision's implementation was affected by the change).
3. `targets = { item : item.related_code ∩ impact ≠ ∅ }`, carrying the intersecting `hit_paths`.

**Degrade, never falsely-clean.** If code-graph is unavailable / the graph is missing, fall back to `impact = changed` (direct file intersection only) and **say so** — `impact_source: "changed-only"` — a narrower blast radius, never a silent empty one.

There are **three impact sources** (from the code): `code-graph`, `changed-only`, `empty`. A subtle point clarified in the `compute_impact` docstring: *"`code-graph` means the graph actually ran (the `all_affected` key is present, even if it lists no dependents). A missing graph — where graph_ops emits `{}` with no `all_affected` key — degrades to `changed-only`."*

## B5. `drift.py` — the deterministic helpers

Module header: *"Scoped by related_code ∩ blast-radius — code-anchored, deliberately NOT always-global ... An item with no related_code is out of drift scope (surfaced only by `gaps`)."*

Constants:
- `RESOLUTIONS_RELPATH = "knowledge-base/drift-resolutions.jsonl"`
- `VERDICTS = ("refuted", "amended", "auto-cleared", "superseded")`
- `_GRAPH_OPS = os.path.join(..., "..", "..", "code-graph", "scripts", "graph_ops.py")`

**Functions / signatures (verbatim):**
- `changed_files(project, base)` — `git -C project diff {base}..HEAD --name-only`; empty on any git error.
- `compute_impact(project, base)` → `(impact_set, source)`. Calls `graph_ops.py --impact <changed> --dir project --format json`; returns `set(data["all_affected"]) | set(changed), "code-graph"` when the graph ran, else `set(changed), "changed-only"`; `set(), "empty"` when nothing changed.
- `_spec_targets(project, impact)` — skips `s.status == "deprecated" or not s.intentional_decisions`; a spec is a target if any `related_code` path is in `impact`. Target dict: `{item, kind:"spec", related_code, hit_paths, decisions, file_path}`.
- `_adr_targets(project, impact)` → `(targets, warnings)` from `active_adrs`. Target dict: `{item, kind:"adr", related_code, hit_paths, title, body}`.
- `build_drift_context(project, base, impact=None, source=None)` — returns `{base, impact_source, impact_count, targets, warnings}`. `impact` is injectable for testing; when `None` it is computed via `compute_impact`.
- `drift_gaps(project)` → `{specs, adrs, warnings}` — declared items carrying intent but **no** `related_code`.
- `append_resolution(project, record)` / `active_prior(project, item, paths=None)` — delegate to shared `resolution_log`; latest-wins per `(item, path)`.

**CLI commands (full flags):**
- `context --base $BASE [--project .] [--format json]` → the per-change, blast-radius-scoped drift set. `--base` is **required**. Example output (sanitized):
  ```json
  {"base":"<sha>","impact_source":"code-graph","impact_count":12,
   "targets":[
     {"item":"SPEC-001","kind":"spec","related_code":[…],"hit_paths":["lib/webauthn.ts"],
      "decisions":["userVerification is 'preferred', not 'required'"],"file_path":"…/SPEC-001…md"},
     {"item":"ADR-001","kind":"adr","related_code":[…],"hit_paths":["prisma/schema.prisma"],
      "title":"Use PostgreSQL","body":"## Decision …"}],
   "warnings":[…]}
  ```
- `resolve --item SPEC-NNN|ADR-NNN --verdict {refuted|amended|auto-cleared|superseded} --reason R --paths <files…> [--commit SHA] [--date YYYY-MM-DD]` — append one line to `drift-resolutions.jsonl`. `--item`, `--verdict`, `--reason`, `--paths` are required.
- `prior --item X [--paths <files…>] [--format json]` — active latest-wins per `(item, path)`, drops `superseded`, skips a malformed line with a warning.
- `gaps [--project .] [--format json]` — **on-demand, NOT part of wrap-up**: the static list of declared decisions/ADRs that carry intent but **no `related_code`**. A coverage signal, not a gate.

## B6. The resolution log — `drift-resolutions.jsonl`, keyed `(item, path)`

New append-only log at `knowledge-base/drift-resolutions.jsonl`, keyed **`(item, path)`** (like G2's `(principle, path)`). Example record (sanitized):

```json
{"date":"2026-07-01","item":"SPEC-001","verdict":"refuted",
 "paths":["lib/webauthn.ts"],"reason":"code sets userVerification 'preferred' exactly as declared; model misread the mount option","commit":"abc1234"}
```

- **Retirement is append-only** — a later `superseded` record (latest-wins per `(item, path)`), never a mutated field.
- **Verdicts match G2/G3.** `refuted` = false positive. `amended` = the declared intent was *consciously changed* to match new code (the spec decision / ADR was edited — a reviewable event). A plain **fix the code** needs no entry (git records it); an **amend** self-clears next run too, but is logged for the acknowledgment audit trail.

**Why the log exists (the resolve-to-proceed memory):** the check fires **every time a decision's `related_code` lands in a blast radius**, so a finding recurs. The log's load-bearing job is to stop re-nagging an already-adjudicated **`refuted`** false positive on every overlapping change (the "rubber-stamp" erosion), plus the acknowledgment audit trail, plus the priors the recurrence triage validates against. `fix`/`amend` self-clear via git; `refuted` does not — hence the log.

## B7. The judgment (agent) & triggers

**Trigger — wrap-up only.** P4b is code-triggered; there is **no interactive entry** (nothing in code changed at spec/ADR authoring time). It runs in **wrap-up Phase 3.5 step 7**, after G3's step 6, reusing the same `$BASE` computed in step 3.

**Full ordering:** deterministic facts (G1 + links + `adr verify` + accepted-behavior run) → **G2 principle checkpoint (step 5)** → **G3 contradiction check (step 6)** → **P4b declarative-drift (step 7)**.

**Process (agent judgment).** Run `drift.py context --base $BASE`. For each target, read the declared intent (spec's decisions/prose, or the ADR body) + the **diff of its `hit_paths`** (`git diff $BASE..HEAD -- <hit_paths>`), and judge: *does the current code contradict this declared intent?* Each finding is resolved to proceed:
- **fix the code** — no log; git records;
- **amend the intent** — edit the spec decision / ADR and log `amended` (the reviewable event);
- **refute** — false positive; log `refuted`.

*"Ignore and push" is not a resolution; drift is resolved in the cycle that raised it (no standing backlog).*

**LLM-first triage on recurrence** (identical to G2/G3): `drift.py prior --item <id> --paths <hit_paths>` → re-validate a prior against the *current* code in the hit paths — still-valid → **auto-clear** (`auto-cleared`, logged); the code moved so the prior no longer maps → **retire** (`superseded`); now a real drift → **escalate**. Guardrails: re-judge the current hunk against the *specific* prior reason (not the item id); bias-to-escalate on ambiguity; always logged; a finding with no prior always reaches the human.

**Posture:** advisory / procedural — never a script hard-block, never auto-fail on model confidence. Fail-open on no code-graph / no targets / tooling error.

## B8. Edges

- **No changed files / empty blast radius** → `targets: []` → step 7 no-ops.
- **No code-graph / missing graph** → `impact_source: "changed-only"` (direct intersection), never a silent empty blast radius.
- **Target with empty `related_code`** → excluded from `context`; visible in `gaps`.
- **`drift-resolutions.jsonl` malformed** → `prior`/`resolve` skip the bad line with a warning; never crash, never silently authorize an auto-clear.
- **No git** → `context` returns a graceful empty result; fail-open.
- **Ambiguous triage** → escalate (bias-to-surface).

---

## C. Staging (both) & the two-commit pattern

At wrap-up, both features' artifacts stage in **commit 2 (artifacts)**, same class as `SPEC-*.md` / `principles.md`:
- **P4a:** ADR files (`knowledge-base/decisions/ADR-*.md`) + `decisions/README.md`.
- **P4b:** `knowledge-base/drift-resolutions.jsonl` (same class as the principle-/contradiction-resolutions logs).

---

## D. The two scoping decisions, side by side (the takeaway)

| | **P4a G3 (spec ↔ ADR)** | **P4b drift (code ↔ declared intent)** |
|---|---|---|
| Nature | intent-vs-intent, no code anchor | code-vs-intent, triggered by a code change |
| Scope | **always-global** — ALL active ADRs | **blast-radius-scoped** — `related_code ∩ impact` |
| Why | over-scoping = unrecoverable silent miss; ADRs cross-cutting by definition; corpus tiny | code-anchored; an item with no `related_code` is honestly out of scope; global here = rejected whole-repo re-derivation |
| Failure it refuses | a **silent miss** (false negative) | **noise** / whole-repo re-nagging |
| Honesty view | (n/a) | `drift gaps` — declared items with no `related_code` |

The one-line mental model: **P4a errs toward recall because a missed ADR is unrecoverable; P4b errs toward quiet because a code-triggered check must stay incremental — and it makes its blind spot visible via `gaps`.**

---

## E. Testing note

Both are validated the same way: deterministic helpers by stdlib `unittest` suites (`test_adr.py`, `test_contradictions.py`, `test_drift.py`, `test_frontmatter.py`) with the code-graph call stubbed/injected; the **agent judgment + triage** (the actual contradiction/drift call and auto-clear triage) validated by the **testbed dogfood, not a unit test**. Production webapp off-limits; testbed branch, restored after.
