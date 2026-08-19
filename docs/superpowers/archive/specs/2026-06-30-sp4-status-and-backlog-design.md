# SP4 — Status & Backlog (design)

**Status:** Draft for review
**Date:** 2026-06-30
**Parent design:** `docs/design/behavior-layer/03-adoption-and-intent-lifecycle.md` (§6 status/backlog/worklists, §9 SP4, §11 BACKLOG location, §12 acceptance criteria).
**Depends on:** SP1 (lifecycle states), SP2 (the `proposed` corpus + `detect_project`), SP3 (`behavior-graph --surface` and its `covered`/`_graph_files` machinery). Reuses `run_behaviors.load_behaviors`, `verify_links.py`, `behavior.json`, and the `codebase-security-scan` report tree.

---

## 1. Goal

A read-only **`status`** command — the sibling of `wrap-up` (wrap-up = do/sync, status = check) — that answers "where do I stand, what's outstanding?" by aggregating across skills, and refreshes a generated, git-tracked **`BACKLOG.md`**. Plus a **`gaps`** command (whole-repo uncovered-code audit) and two **worklists** to work the cold tail one behavior at a time. Satisfies §12:

> `status` reports — and refreshes a git-tracked `BACKLOG.md` listing — behaviors-to-confirm, tests-owed, and open security findings; never silent. `gaps` lists uncovered code. The two `review` worklists let an engineer work the tail one-by-one.

## 2. Resolved decisions (from brainstorming)

- **`status` is a new top-level skill** — the read-only sibling of `wrap-up`. It aggregates across skills (behaviors, code-graph/gaps, verify, security) the way `wrap-up` orchestrates them, keeping `wrap-up`'s mutating semantics clean. Justified as genuinely cross-skill (unlike SP2's bootstrap, which extended one skill's `init`).
- **Structured security findings index first.** `codebase-security-scan` emits a machine-readable `findings.json` alongside its prose report; `status` reads that (no fragile prose parsing). This is the substrate **SP5** enriches (annotating a finding with the `accepted` behavior that explains it) — foundational, not throwaway.
- **`BACKLOG.md` at `knowledge-base/BACKLOG.md`**, generated and never hand-edited, git-tracked (groups with the other knowledge artifacts; still diffs in PRs).
- **Worklists live in the `status` skill**, following spec-manager `review`'s one-at-a-time interaction style (reuse the pattern, not the location).

## 3. Architecture

The deterministic core is one script in the new skill; the SKILL.md wraps it with the print/worklist procedures. One small query is added to `behavior-graph`, and one emit step to `codebase-security-scan`.

### 3.1 `status` skill — `scripts/collect_status.py` (deterministic core)

`skills/status/scripts/collect_status.py` aggregates every bucket and both renders `BACKLOG.md` and emits the same data as JSON.

- **Input:** `--project <dir>`; `--format json|text` (text = the printed summary); `--write-backlog` (regenerate `knowledge-base/BACKLOG.md`).
- **Buckets** (each from a deterministic source, each degrading independently):
  - `behavior_counts` — `{proposed, confirmed, accepted, quarantined, deprecated}` counts, via `run_behaviors.load_behaviors(specs_dir, states=ALL)`.
  - `intent_worklist` — the `proposed` behaviors (id, title, spec_id, spec_path, certainty if present), the confirm-me list.
  - `test_owed_worklist` — the `confirmed` behaviors, the write-a-test list.
  - `gaps` — whole-repo uncovered source files, via `behavior-graph --gaps` (§3.2). Stored as a count + a capped sample.
  - `verify_failures` — the list from `verify_links.py --format json` (deterministic Tier-1 errors).
  - `stale_fingerprints` — `behavior.json` behaviors whose any `exercises[*].freshness` ≠ current HEAD (cheap; advisory "re-run --build").
  - `open_security_findings` — from `findings.json` (§3.3): entries with `status == "open"` (count + list of `{id, title, severity, file}`).
- **`classify`-style return:** a single dict `{version, project, behavior_counts, intent_worklist, test_owed_worklist, gaps, verify_failures, stale_fingerprints, open_security_findings, notes: [...]}`. `notes` collects per-source degradation messages (e.g. "no behavior.json — run behavior-graph --build").
- **Read-only** except for `--write-backlog`, which writes only `knowledge-base/BACKLOG.md`. Stdlib-only.

### 3.2 `behavior-graph --gaps` (whole-repo uncovered audit)

Add `--gaps` to `behavior_graph.py`. It returns the project's source files (graph.json keys) that no behavior covers: `_graph_files(project_dir) − covered`, where `covered` is **factored out of `surface`** into a shared `_covered(project_dir, behaviors, specs_behaviors)` helper (exercises paths ∪ all declared `entry` values) so `surface` and `gaps` cannot drift. Emits `{version, gaps: [...], total: N}`. Read-only.

### 3.3 `codebase-security-scan` — `findings.json`

Extend the report-writing steps (`scan`/`update`/`audit` report generation) so that, alongside `knowledge-base/security/codebase-security/YYYY-MM-DD.md`, the skill also writes `knowledge-base/security/codebase-security/findings.json`:

```json
{
  "version": 1,
  "scanned_commit": "<hash>",
  "report": "knowledge-base/security/codebase-security/2026-06-30.md",
  "findings": [
    {"id": "SEC-001", "title": "...", "severity": "high|medium|low|info",
     "status": "open|resolved|intentional", "file": "src/x.ts", "line": 42,
     "spec_ref": "SPEC-001"}
  ]
}
```

- `status` is `open` unless the finding is marked RESOLVED (lifecycle) or `intentional` (cross-referenced to a declarative spec decision — the existing `check-specs` behavior). `spec_ref` is the spec that marks it intentional, when known.
- It is **git-tracked** (the prose reports already are) and lives beside the report it summarizes. The schema is documented in a new `references/findings-schema.md` in the security skill.
- This is an agent-emitted artifact (the scan procedure writes it as it writes the report) — no new deterministic extractor; the agent already has the structured findings in hand when it composes the report.

### 3.4 `BACKLOG.md` (generated)

`knowledge-base/BACKLOG.md`, regenerated by `status --write-backlog` and by `wrap-up` (in its artifacts commit). Header states it is generated — "do not edit; run `status` to refresh." Sections, each a short table or list:

- **Behaviors to confirm** (intent worklist) — id · title · spec.
- **Tests owed** (test-owed worklist) — id · title · spec.
- **Coverage gaps** — count + a capped sample of uncovered files.
- **Open security findings** — id · severity · title · file.
- A one-line census header ("12 proposed · 4 confirmed · 30 accepted · 3 tests owed · 5 open findings").

It is to intent+security completeness what a coverage report is to test coverage: visible, shared, diffable.

### 3.5 Worklists (the `status` skill procedure)

Two interactive, one-at-a-time loops, following spec-manager `review`'s style (present one item, act, next; stop anytime):

- **intent worklist** — walk `intent_worklist` (certainty-sorted, lowest first). For each `proposed` behavior: show it (and, like SP3, it may be re-read against current code), then confirm (`proposed → confirmed`), edit-then-confirm, quarantine/deprecate, or skip.
- **test-owed worklist** — walk `test_owed_worklist`. For each `confirmed` behavior: link/write its test and accept (`confirmed → accepted` once a real passing linked test exists — the SP1 accepted gate then governs), or skip. Never auto-author a test.

The worklists are how the cold tail (behaviors never hit by work, so never surfaced by SP3's validate-on-hit) gets drained on purpose.

## 4. Data flow

`status` → `collect_status.py` runs the sources (in-process `load_behaviors`; subprocess `behavior-graph --gaps`, `verify_links.py`; file reads of `behavior.json`, `findings.json`) → assembles the dict → prints the summary and/or writes `BACKLOG.md`. No mutation of specs, graph, or code. The worklists, when invoked, mutate spec frontmatter (state bumps) — those are artifacts (wrap-up commit 2), consistent with the behavior-aware staging rule.

## 5. Error & edge handling

- **Each source degrades independently.** Missing `behavior.json` → gaps/stale buckets empty + a `note`; missing `findings.json` → security bucket empty + a `note` ("no security scan yet — run codebase-security-scan"); no specs → zero census. `status` never crashes and never blocks (exit 0 always; it is a report).
- **Empty project / greenfield** → all-zero census, empty backlog with a "nothing outstanding / greenfield" line.
- **`--gaps` with no graph** → empty list + a note (run code-graph build), mirroring `surface`.
- **`findings.json` schema drift / unreadable** → security bucket degrades to a note, never throws.
- **Large gaps/worklists** → counts plus a capped sample in `BACKLOG.md`/text output (no wall of thousands of lines); the worklists are the place to actually grind them.

## 6. Testing

- **`collect_status.py` — unit tests** (stdlib `unittest`, tempdir fixtures): census counts by state; intent/test-owed worklist composition; each-source-degrades-independently (missing behavior.json / findings.json / graph each yields an empty bucket + note, never a raise); `--write-backlog` produces a `BACKLOG.md` with the expected sections and the "generated — do not edit" header; JSON shape stable.
- **`behavior-graph --gaps` — unit tests** (extend `test_behavior_graph.py`): `graph_files − covered`; a file in an exercise or declared as an entry is not a gap; no-graph degrades; and a shared-`_covered` test proving `surface` and `gaps` compute coverage identically.
- **`findings.json` — security skill:** the schema doc exists; a fixture/example validates against it. (The emit itself is an agent procedure, exercised by the dogfood.)
- **Dogfood on the testbed** (`dogfood/sp2-bootstrap` branch — proposed BEH-004–008; production webapp off-limits): run `status` and confirm the census (proposed count includes the post-locking behaviors), the worklists list them, `--gaps` returns a sane uncovered set, and `BACKLOG.md` renders with all sections; run a security `update` and confirm `findings.json` is emitted and its open findings appear in `status`. Walk one intent-worklist item (confirm a proposed → confirmed) and re-run `status` to see the counts move. Log friction.

## 7. Scope

**In scope:** the `status` skill + `collect_status.py` + `BACKLOG.md` rendering; `behavior-graph --gaps` (+ the `_covered` refactor shared with `surface`); the `findings.json` index emitted by `codebase-security-scan` + its schema doc; the two worklists.

**Out of scope:** the security↔behavior **cross-reference logic** (→ SP5 — SP4 only builds the `findings.json` substrate and reads `open` findings; it does not consult `accepted` behaviors to silence findings); model-based contradiction checks; any new behavior execution.

## 8. Acceptance criteria

- [ ] `status` (read-only) prints a census + the outstanding buckets and never blocks (exit 0) even when sources are missing (each degrades to a note).
- [ ] `collect_status.py` aggregates behavior counts, the intent (`proposed`) and test-owed (`confirmed`) worklists, gaps, verify failures, stale fingerprints, and open security findings.
- [ ] `status --write-backlog` (and `wrap-up`) regenerate `knowledge-base/BACKLOG.md` — generated header, all sections, git-tracked.
- [ ] `behavior-graph --gaps` lists whole-repo uncovered source files, sharing the exact `covered` computation with `surface`.
- [ ] `codebase-security-scan` emits `findings.json` (documented schema) whenever it writes a report; `status` reads `open` findings from it.
- [ ] The intent and test-owed worklists let an engineer work behaviors one at a time (confirm / accept via the SP1 state bumps), stopping anytime; never auto-authoring tests.
- [ ] Dogfooded on the testbed: census/worklists/gaps/backlog/security all populate correctly, and confirming a worklist item moves the counts.

## 9. Open questions

None blocking. `findings.json` is agent-emitted (the scan already reasons over structured findings), so its fidelity is validated by the dogfood, not a deterministic guarantee. If the census/worklists grow large at real scale, the capped-sample + counts approach keeps `status`/`BACKLOG.md` readable; the worklists remain the mechanism for working volume.
