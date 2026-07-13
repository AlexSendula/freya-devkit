# Phase 1 — Implementation Plan

**Status:** Draft for review
**Date:** 2026-06-24
**Plans:** `01-phase-1.md` (the *spec* — the "what"). This doc is the *plan* — the "in what order, touching which files, verified how."
**Branch:** `feat/behavior-layer` (the whole initiative lands here; kept local for now).

---

## Context

`01-phase-1.md` fully specifies the Traceability MVP — the `Behavior` entity, its lifecycle, the extended spec format, two adapters, deterministic integrity checks, and wrap-up staging. What it deliberately leaves open is the **execution sequence**: which files change, in what order, and how each step is proven. This plan fills that, **foundation-first**, because the substrate prerequisite is load-bearing: the current frontmatter parser (`search_specs.py: parse_frontmatter`) is a regex hand-roll that **silently drops inline-array fields** (`tags: [a, b]` → string → discarded). Extending the schema on top of it would silently corrupt the new `behaviors` data, so the parser is replaced and proven *before* the schema grows.

The `knowledge-base/` migration has shipped (see `00-vision.md §9`), so all paths below target the new layout. Each step is validated **inside the devkit** with unit tests and throwaway fixture projects — the feature is project-agnostic and must work on any project. Some schema/lifecycle/adapter choices are provisional and expected to change in contact with real use (vision §9).

**Decision already taken (parser):** instead of a full YAML engine (the plugin is stdlib-only, zero-install), Phase 1 ships a **scoped, schema-validated frontmatter parser** for our exact (versioned, model-authored) grammar that **fails loud** on anything outside it. This kills the silent-drop bug class without an install step. Step 0 aligns the spec's wording to this.

## Workflow note

These are **ordered, landable steps** on the single `feat/behavior-layer` branch — sequential commits, not separate branches/PRs. Each step is independently committable and verifiable. The plan is step-sequencing, not a frozen contract: reality (the testbed) can move it.

---

## Step 0 — Align the spec to the parser decision
- `docs/design/behavior-layer/01-phase-1.md §7`: soften "Replace the hand-rolled frontmatter parser with a **real YAML parser**" → "a **strict, schema-validated frontmatter parser that fails loud**", so the spec matches the chosen approach. Small, do first.

## Step 1 — Substrate: scoped parser + schema validation + runner detection
The foundation. Nothing else lands until this is proven.
- **New** `skills/spec-manager/scripts/frontmatter.py`:
  - `parse_frontmatter(text) -> (dict, body)` — pure-stdlib parser for our grammar: scalars, ints, dates-as-strings, quoted strings, block sequences (`- item`), **inline flow arrays (`[a, b]`)**, and one level of list-of-mappings (for `behaviors:`). **Raises a clear error** on anything outside the grammar — never silently drops.
  - `validate(frontmatter, schema_version) -> list[error]` — required-field + type checks against a **versioned schema**. Unknown fields are **preserved** (round-trip safe), not dropped.
  - A schema-version constant so future migrations are explicit.
- **Rewire** `skills/spec-manager/scripts/search_specs.py`: delete the old `parse_frontmatter` (lines ~50–102), import from `frontmatter.py`. The `Spec` dataclass and search/format logic stay (the `behaviors` field is added in Step 3).
- **New** `skills/spec-manager/scripts/test_frontmatter.py` (stdlib `unittest`): inline arrays round-trip; block lists; list-of-maps; missing closing `---`; partial/empty frontmatter; unknown field preserved; malformed grammar raises. This suite is the proof the substrate is reliable.
- **Extend** `skills/docs-manager/scripts/detect_project.py`: add a stateless `detect_test_runners()` (jest/vitest/mocha, pytest/unittest, playwright/cypress, cucumber/behave) via `package.json` deps + config globs, returned inside the existing `analyze_project()` dict — no tracking file. Consumers (spec-manager, wrap-up) reach it **as a subprocess** — `python "${CLAUDE_PLUGIN_ROOT}/skills/docs-manager/scripts/detect_project.py" <dir>` and read `["test_runners"]` from the JSON — **not** a Python import (the plugin has no cross-skill import path; skills only shell out to each other's scripts via the plugin root).

**Verify:** `python test_frontmatter.py` passes; `search_specs.py --id <id> --format json` on a fixture spec with `tags: [a, b]` now shows the tags (previously empty); `detect_project.py` on throwaway fixtures (one with a jest/pytest config, one with none) reports the runner set — and reports **none** as a valid, loud answer when no test tooling is present.

## Step 2 — `Behavior` entity + lifecycle
- Add the behavior record to `frontmatter.py`'s validator: `behavior_id` (`BEH-NNN`), `spec_id`, `title`, `state` (`proposed|accepted|quarantined|deprecated`), `adapter` (`cucumber|jest|playwright|...|manual`), `locator`.
- Sequential `BEH-NNN` id allocation mirroring spec ids. Allocation is a **model-driven SKILL.md convention** (there is no spec-id *allocator* in code either — `search_specs.py` only reads ids; `SKILL.md` instructs "next sequential number"). We mirror that convention rather than building an allocator script no other id type has. **Deterministic collision *detection*** (reused `BEH-NNN`) lives in `verify_links.py` (Step 5); ids are stable across renames.
- Extend `test_frontmatter.py`: valid record; bad state rejected; reused id flagged at validate time.

**Verify:** unit tests cover the behavior record; a hand-written spec carrying a `behaviors:` list parses into a structured `list[dict]` with all fields intact.

## Step 3 — Extended spec format
- `skills/spec-manager/references/spec-template.md`: add the `behaviors:` frontmatter list; replace the inert `## Acceptance Criteria` checkbox section with a `## Behavior` table (links to each behavior's test, **no copied scenario text**); note `related_code` is now expected on declarative specs too (the key the Phase 3 drift check uses).
- `skills/spec-manager/references/categories.md`: minor — behavior/test tag notes (low priority).
- `skills/spec-manager/SKILL.md`: update the "Spec File Format" section + `create`/`update`/`verify` descriptions to describe behaviors; drop any `feature_files`/`behavior_status` framing (doc-only alignment — neither exists in code).
- `Spec` dataclass in `search_specs.py`: add a `behaviors` field so search/get surface them.

**Verify:** a spec authored from the updated template parses cleanly; `search_specs.py --id <id> --format json` includes the `behaviors` list.

## Step 4 — Two adapters
- **Gherkin adapter:** spec-manager writes a **skeleton `.feature`** with required `@SPEC-NNN`/`@BEH-NNN` tags and `TODO(scaffold)` markers (no real steps, no step definitions). Mostly a SKILL.md workflow addition + a small helper to emit/validate the scaffold shape. Scaffolds reference intent at `knowledge-base/specs/<cat>/SPEC-*.md`.
- **Native adapter:** link an **existing** test by `locator` — no file written, no rewrite. Keeps adoption cheap for projects that already have tests.

**Verify:** generating a Gherkin scaffold yields a tagged `.feature` with TODO markers; linking a native test records a resolvable `locator` with no file churn.

## Step 5 — Deterministic integrity checks (`verify`)
- **New** `skills/spec-manager/scripts/verify_links.py` (Tier-1, no LLM, no execution): every `locator` resolves to a real test location; every `@SPEC`/`@BEH` tag points at an existing spec/behavior and ids round-trip; state consistency (`accepted` but scaffold still has `TODO(scaffold)` → **error**; reused `BEH` id → error).
- Wire into `spec-manager verify` (SKILL.md).

**Verify:** `verify_links.py` against a spec set with a deliberately broken locator and a stale TODO-on-accepted behavior → both reported as errors; a clean set passes.

## Step 6 — Intent classification → review queue + wrap-up staging
- `skills/spec-manager/SKILL.md` (`create`/`scan`): classify intent — testable → propose a `Behavior` (`state: proposed`); not testable → declarative (Intentional Design Decisions, or note for `knowledge-base/decisions/`). **`scan` produces a review queue of `proposed` candidates, never `accepted`**, never files committed into the code tree. Reuse the existing one-question-at-a-time `review` flow + certainty thresholds for low-certainty candidates.
- `skills/wrap-up/SKILL.md`: add lifecycle-aware staging to the two-commit rules — a scaffold's commit class follows its **state**, not its location: `proposed`/TODO scaffolds → artifacts commit; `accepted` behaviors' tests → code commit. At wrap-up, *accepted* behaviors run via the detected runner and **only deterministic failures block**.

**Verify:** a `scan` run yields proposed candidates with certainty scores and writes nothing authoritative into the code tree; a wrap-up dry-run stages a proposed scaffold as an artifact and an accepted test as code.

---

## Critical files

| File | Step | Change |
|---|---|---|
| `docs/design/behavior-layer/01-phase-1.md` | 0 | Soften §7 parser wording |
| `skills/spec-manager/scripts/frontmatter.py` (new) | 1,2 | Scoped parser + versioned schema validator |
| `skills/spec-manager/scripts/test_frontmatter.py` (new) | 1,2 | Stdlib unittest proof suite |
| `skills/spec-manager/scripts/search_specs.py` | 1,3 | Use new parser; add `behaviors` to `Spec` |
| `skills/docs-manager/scripts/detect_project.py` | 1 | Stateless `detect_test_runners()` |
| `skills/spec-manager/references/spec-template.md` | 3 | `behaviors:` list; `## Behavior` replaces Acceptance Criteria |
| `skills/spec-manager/references/categories.md` | 3 | Minor behavior/test tag notes |
| `skills/spec-manager/SKILL.md` | 3,4,6 | Format section + create/scan/verify behavior workflow |
| `skills/spec-manager/scripts/verify_links.py` (new) | 5 | Tier-1 deterministic integrity checks |
| `skills/wrap-up/SKILL.md` | 6 | Lifecycle-aware two-commit staging; run accepted behaviors |

## Reused utilities (do not reinvent)
- `analyze_project()` + detection helpers in `detect_project.py` — extend, don't replace.
- `Spec` dataclass + `load_all_specs`/`search_specs` in `search_specs.py` — keep the search machinery; swap the parser and add a field.
- spec-manager's existing **certainty thresholds** and **one-question-at-a-time `review`** flow (SKILL.md) — reuse for behavior classification.
- spec id allocation convention — mirror it for `BEH-NNN`.

## Out of scope (later phases / decoupled)
`behavior.json` / blast-radius / coverage fingerprints (Phase 2); model-based Tier-2 contradiction checks, principle enforcement, declarative-drift (Phase 3); ADR machinery (Phase 4 — `decisions/` already exists empty); generating real `principles.md` content from a scan; foreign-tooling ingest.

## End-to-end verification
On a throwaway fixture project, after all steps: author a spec with a `behaviors:` list via the updated template → `search_specs.py` surfaces it and `tags`/inline arrays survive → `verify_links.py` passes on good links and errors on a broken one → a `scan` produces only `proposed` candidates → wrap-up stages proposed scaffolds as artifacts and accepted tests as code, running accepted behaviors with deterministic-only blocking. Note any schema/lifecycle friction that surfaces as provisional-choice corrections (vision §9).
