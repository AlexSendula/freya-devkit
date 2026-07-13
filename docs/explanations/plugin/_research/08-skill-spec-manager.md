# Skill: spec-manager — research brief

> Backing research for the plugin-wide explainer. Sourced from
> `skills/spec-manager/SKILL.md`, its `references/`, and its `scripts/`.
> All paths are repo-relative unless noted. Examples are generic (auth/WebAuthn,
> `src/…`); no proprietary content is reproduced.

---

## 1. What it is

`spec-manager` is the freya-devkit skill that **creates and manages feature
specifications capturing WHAT a feature does and WHY it was designed that way** —
with a special emphasis on *intentional design decisions that might look like
bugs or security issues*. It owns three things inside the shared
`knowledge-base/` root:

- `knowledge-base/specs/` — per-feature intent + decisions (the specs themselves)
- `knowledge-base/principles.md` — the project "constitution" (highest-authority intent)
- `knowledge-base/decisions/` — cross-cutting Architecture Decision Records (ADRs)

> "spec-manager owns `principles.md`, `specs/`, and `decisions/`. `principles.md`
> is the highest-authority intent record; `specs/` and `decisions/` sit below
> it." (`SKILL.md`)

It is invoked namespaced as `/freya-devkit:spec-manager <command>`.

Beyond plain specs, spec-manager is the **home of the plugin's "behavior layer"**
— first-class `Behavior` records (BEH-NNN) with a lifecycle, linked to executable
tests via adapters, plus a set of governance gates (G1/G2/G3/P4a/P4b). Those are
noted here but kept at the ecosystem level; the deep behavior-layer material lives
in its own briefs.

## 2. Why it exists

Two core problems:

1. **Preserve design intent that code alone can't express.** New developers, AI
   agents, and security scanners routinely "fix" deliberate choices (no password
   fallback, permissive CORS on a public API, no rate limit on a health endpoint).
   Specs record the decision + rationale + explicit guidance to tools.

2. **Act as the security false-positive filter.** The *Intentional Design
   Decisions* section is the key feature — it lets a security scan distinguish a
   real vulnerability from a documented, on-purpose choice. From the template:

   > "This is the key section for preventing false positives in security scans
   > and code reviews." (`references/spec-template.md`)

   Example structure (generic):

   ```markdown
   ## Intentional Design Decisions
   ### No Password Fallback
   **Decision**: We do not offer password authentication as a fallback.
   **Rationale**: Offering password fallback would create a phishing vector.
   **Security Scan Note**: Any security tool flagging "missing password
   authentication" should be ignored - this is intentional.
   ```

   > "This helps: Security scans distinguish real issues from design decisions;
   > New developers understand why code is the way it is; AI agents avoid
   > 'fixing' intentional choices." (`SKILL.md`)

## 3. The knowledge-base layout it participates in

```
knowledge-base/
├── principles.md      # constitution (spec-manager init)          [spec-manager]
├── specs/             # per-feature intent + decisions            [spec-manager]
├── decisions/         # cross-cutting ADRs                        [spec-manager]
├── reference/         # descriptive architecture/API/schema docs  [docs-manager]
├── security/          # security findings                         [security-scan]
└── .graph/            # generated dependency + behavior graph      [code-graph]
```

Specs are organized by category under `specs/`:
`auth/`, `api/`, `data/`, `features/`, `infra/`, `integration/`, `ui/` — each with
a `README.md` index at the top.

## 4. Commands (Quick Reference, verbatim from `SKILL.md`)

| Command | Description |
|---------|-------------|
| `init` | Initialize `/knowledge-base/specs/` structure |
| `bootstrap` | Unified onboarding: detect shape → init + code-graph + (brownfield) scan + behavior-graph |
| `create <name>` | Create new spec interactively |
| `scan` | Full codebase scan, generate specs with certainty scores |
| `update` | Git-aware incremental sync (no args = smart sync) |
| `update <spec>` | Re-analyze and update specific spec |
| `verify` | Check if all specs match current code |
| `intent new <BEH...>` | Create an INTENT-NNN record authorizing a change to an accepted behavior's test |
| `adr create <name>` | Create a cross-cutting ADR interactively |
| `adr list` | Print / regenerate the ADR index |
| `adr verify` | Deterministic ADR integrity (dup IDs, dangling links, bad status) |
| `search <query>` | Full-text search across specs |
| `by-tag <tag>` | Filter specs by tag |
| `get <id...>` | Load full spec(s) by ID |
| `review` | Interactive review of low-certainty specs |
| `principles` | Print the project's principles (constitution) |
| `drift gaps` | On-demand: declared items with no `related_code` (drift-blind) |
| `index` | Rebuild search index |
| `help` | Display help and usage information |

## 5. Onboarding: greenfield vs brownfield (`bootstrap`)

`bootstrap` is the **one-time** "bring the plugin up on this project" flow. It
replaces running `init` / `code-graph build` / `scan` by hand. Day-to-day syncing
is `update`.

Flow (`SKILL.md`):
1. **Init structure** (idempotent — never clobbers existing files).
2. **Build the code graph** via `/freya-devkit:code-graph build` (the shape
   detector needs it).
3. **Detect shape and recommend** — run:
   ```bash
   python "${CLAUDE_PLUGIN_ROOT}/skills/spec-manager/scripts/project_shape.py" --project . --format text
   ```
   Show the engineer the recommendation **and its evidence** (source-file count,
   internal-edge count, detected stack), then ask them to **confirm or override**.
   The detector never forces a branch.
4. **Branch:**
   - **Brownfield →** run `scan` to infer candidate behaviors at the
     **per-observable-behavior grain** (one `proposed` behavior per scenario,
     anchored to a route/entry where applicable — *not* per feature/route). All
     candidates are `proposed` records written into `knowledge-base/specs/`;
     **never** `.feature` scaffolds in the code tree. Additive on a
     partially-onboarded repo (infer only for areas with no existing spec). Then
     `/freya-devkit:behavior-graph --build --project .`. Warn first that scan over
     a large repo spawns discovery agents and can take a while.
   - **Greenfield →** skip `scan`. Build an (essentially empty) behavior graph so
     the machinery is initialized. Print: *"Greenfield project — no inference run.
     Author behaviors forward as you build with `spec-manager create`."*
5. **Summary** — knowledge-base layout, graph built, and (brownfield) a count of
   `proposed` candidates by category, with the reminder that **nothing needs
   review now** (the proposed queue is drained lazily).

### How shape is detected (`scripts/project_shape.py`)

The classification is **objective and transparent**, based on the code-graph's
**internal import-edge count** (real feature wiring), not raw file count:

- Reads `knowledge-base/.graph/graph.json`. Counts `files` and "internal edges"
  (imports NOT tagged `external:` or `unresolved:`).
- Also shells out to `docs-manager/scripts/detect_project.py` for a stack summary
  (runtime, package manager, frontend/backend framework, db/orm, test runners).
- Decision:
  - no graph present → `unknown` ("run code-graph build first")
  - graph present, `internal_edges == 0` → `greenfield` ("N source file(s) but 0
    internal import edges — no real feature wiring yet")
  - graph present, `internal_edges > 0` → `brownfield`

> Rationale in code: "Internal edges (real wiring) are the brownfield signal; raw
> file count is not (a bare scaffold can have many boilerplate files yet zero
> internal wiring)." (`project_shape.py`)

CLI: `--project <dir>` (required), `--format json|text` (default `json`).

## 6. `init` — what it creates

1. `/knowledge-base/specs/` (if missing).
2. Category subdirs (`auth/ api/ data/ features/ infra/ integration/ ui/`), each
   with an empty `.gitkeep` (Git doesn't track empty dirs).
3. `specs/README.md` index.
4. `/knowledge-base/principles.md` from `references/principles-template.md`.
5. `/knowledge-base/decisions/` from `references/decisions-readme.md`; scaffold its
   `README.md` via `adr.py list --project .` (header-only table on an empty dir).
6. Report what was created.
7. `/knowledge-base/intents/` (home for INTENT-NNN records; starts with a `.gitkeep`).

## 7. `scan` — the big one (brownfield inference)

Generates specs with certainty scores using a **coordinator + parallel workers**
pattern.

- **Phase 1 — Coordinator discovery.** Load the constitution first (soft
  injection: `principles.py list`). Spawn ONE coordinator that scans structure,
  identifies feature areas (auth/api/ui/data/infra), and spawns parallel
  discovery agents per area.
- **Phase 2 — Parallel discovery agents.** Each area agent scans code, identifies
  features, generates specs with inferred What/Why + certainty, flags intentional
  decisions, notes `[NEEDS CLARIFICATION]`.
- **Phase 2.5 — Intent classification → a review queue (not staged scaffolds).**
  Each piece of intent is classified: observable behavior expressible as a test →
  propose a `Behavior` (state `proposed`); non-testable → declarative (inline
  *Intentional Design Decisions*, or note for `decisions/` if cross-cutting).
- **Phase 3 — Certainty evaluation.** Cross-reference `knowledge-base/reference/`,
  check comments, validate "what" matches code, adjust score.
- **Phase 4 — Interactive clarification.** Group by certainty; ask about
  low-certainty specs (<70%).
- **Phase 5 — Generate index.** Update `specs/README.md`.

**Hard rules for `scan`** (verbatim, important):

> "`scan` produces a **review queue of `proposed` candidates** — never `accepted`,
> and **never files written into the code tree.** Intent cannot be reliably
> inferred from code; auto-generating authoritative-looking scaffolds from the
> implementation would reintroduce the 'tests mirror code' problem the behavior
> layer exists to fix." (`SKILL.md`)

A candidate becomes `accepted` — and only then does its scaffold/link enter the
code tree — **when a human accepts it.**

## 8. `update` — git-aware incremental sync (day-to-day)

> "Use `update` (no args) for day-to-day syncing after code changes. Use `scan`
> only for initial setup or complete refresh." (`SKILL.md`)

- **Phase 1 — Change detection.** Read `.spec-last-update` for the last commit
  hash; if missing / no git → fall back to full scan. `git diff <last>..HEAD
  --name-only`. No changes → "specs are up to date" and exit.
- **Phase 2 — Impact analysis (code-graph enhanced).** Map changed files to specs
  via `related_code`. **If code-graph available**, call
  `/freya-devkit:code-graph impact <changed-files>` to get blast radius and
  include dependent files, not just directly-changed ones. **Fallback:** git diff
  only.
- **Phase 3 — Update existing specs** (re-read `related_code`, update content, add
  Change History entry, adjust certainty; mark removed code `deprecated`).
- **Phase 4 — Generate new specs** for new code without specs (discovery agents for
  changed areas only). Flag <70% for review.
- **Phase 5 — Review & fix** (cross-reference reference docs, auto-fix typos/stale
  refs, produce summary report).
- **Phase 6 — Update tracking.** Write `knowledge-base/specs/.spec-last-update`:
  ```
  # Spec Manager Last Update
  commit: <hash>
  timestamp: <ISO-8601>
  specs_updated: <count>
  specs_created: <count>
  ```

`update <spec>` is single-spec mode: reload by ID, re-read `related_code`, prompt
on significant change, update + Change History + certainty, then run the G3
contradiction check.

Update-workflow guidance table:

| Scenario | Recommended Command |
|----------|---------------------|
| After implementing a feature | `update` |
| Single spec needs update | `update <spec>` |
| First time setup | `init` then `update` (or `scan`) |
| Check all specs accurate | `verify` or `update` |
| Complete codebase refresh | `scan` |

## 9. Certainty scoring

A `certainty` score (0-100) in frontmatter indicates how confident the AI is
about an *inferred, not-yet-human-confirmed* spec.

| Score | Meaning | Action |
|-------|---------|--------|
| 90-100 | High confidence | Auto-accept |
| 70-89 | Good confidence | Brief review |
| 50-69 | Medium confidence | Ask user to confirm |
| 0-49 | Low confidence | Detailed review needed |

- **Increases:** code comments, matching `reference/` docs, clear patterns, tests.
- **Decreases:** no comments, ambiguous code, multiple interpretations, missing tests.
- **User-created specs are set to certainty 100.**

**Post-behavior-layer nuance (important):** `certainty` now measures confidence in
an *inferred, unconfirmed* spec — it gates review of `scan` output and backs the
**declarative** intent (the *Intentional Design Decisions* the security scan
cross-references, which have no test to verify them). It is **not** the signal for
*executable behavior* intent — that is carried by the behavior lifecycle `state`:

> "`confirmed` = a human confirmed the intent (test owed)" and "`accepted` =
> confirmed intent that a real linked test verifies." A human-authored or
> human-confirmed spec is trusted regardless of the number. (`SKILL.md`)

## 10. Spec file format

Frontmatter (`references/spec-template.md`):

```yaml
---
id: SPEC-001
title: Feature Name
category: auth | api | data | features | infra | integration | ui
tags: [tag1, tag2]
status: draft | in-progress | implemented | deprecated
certainty: 0-100
created: YYYY-MM-DD
updated: YYYY-MM-DD
related_code:
  - path/to/file.ts
intentional_decisions:
  - "Brief description of intentional decision"
behaviors:
  - behavior_id: BEH-007
    title: Successful passkey login
    state: accepted           # proposed | confirmed | accepted | quarantined | deprecated
    adapter: cucumber         # cucumber | behave | pytest-bdd | jest | playwright | ... | manual
    locator: features/auth/passkey-login.feature#successful-passkey-login
---
```

Key sections: **What** (purpose/scope — *not* step-by-step behavior), **Why**
(problem/rationale), **Behavior** (a table linking each BEH-NNN to its verifying
test — no copied scenario text), **Intentional Design Decisions** (declarative
choices + rationale + Security Scan Note), **Related Specs**, **Change History**.

`related_code` is **expected even on purely declarative specs** — it is the key
the declarative-drift check uses to decide whether a change's blast radius can
affect the decision. A declarative spec with no `related_code` is invisible to
that check.

### IDs
- Specs: `SPEC-NNN`, next sequential number across existing specs.
- Behaviors: `BEH-NNN`, next sequential across all behaviors, **stable across
  renames** (never renumber).
- ADRs: `ADR-NNN`, next sequential across `decisions/ADR-*.md`.
- Intents: `INTENT-NNN`.
Allocation is a convention at authoring; deterministic duplicate-ID detection is
enforced by `verify` / `adr verify`.

## 11. Behavior records, lifecycle, and adapters (behavior layer — ecosystem note)

Each `behaviors:` entry is a first-class, intent-bearing record linked to an
executable test. Lifecycle `state` (closed set, from `frontmatter.py`):
`proposed → confirmed → accepted` (+ `quarantined` / `deprecated`). Only
**`accepted`** is authoritative and blocks on failure; `confirmed` = intent
confirmed, test owed.

Behavior-record fields (`references/spec-template.md`): `behavior_id` (req),
`title` (req), `state` (req), `level` (`unit|component|integration|e2e` — runner
dispatch key), `adapter` (required for `accepted`, optional for pre-test states),
`locator` (required for `accepted` except `manual`), `entry` (required for
`level: integration` — the route/handler the integration test drives), `spec_id`
(optional; must match parent if present).

**Adapters** (`scripts/adapters.py`) link a behavior to its test two ways:
- **Gherkin** (`cucumber` / `behave` / `pytest-bdd`) — default for *new* behavior.
  spec-manager writes a **skeleton `.feature`** with required `@SPEC-NNN` /
  `@BEH-NNN` tags and a `TODO(scaffold)` marker, **no real steps, no step
  definitions** (authoring real steps is human forward-design work). Emitted via:
  ```bash
  python "${CLAUDE_PLUGIN_ROOT}/skills/spec-manager/scripts/adapters.py" gherkin-scaffold \
    --spec-id SPEC-012 --title "Passkey Login" \
    --spec-path knowledge-base/specs/auth/SPEC-012-passkey-login.md \
    --behavior "BEH-007:Successful passkey login"
  ```
  Feature file lands in the **code tree** at `features/<category>/<name>.feature`;
  locator = `features/<category>/<name>.feature#<scenario-slug>`.
- **Native** (`jest`, `playwright`, `pytest`, …) — link an **existing** test by
  `locator` (`path/to/test#case`, or `path::node` for pytest). No file written,
  nothing rewritten — keeps adoption cheap for projects that already have tests.

Known adapters (`frontmatter.KNOWN_ADAPTERS`): `cucumber, behave, pytest-bdd,
jest, vitest, mocha, jasmine, playwright, cypress, pytest, unittest, manual`.

## 12. `verify` — deterministic (Tier-1) integrity checks

`verify` runs the cheap, certain, LLM-free checks that are allowed to
**hard-block at wrap-up**. Three deterministic scripts:

1. **`verify_links.py`** — behavior link-integrity:
   ```bash
   python "${CLAUDE_PLUGIN_ROOT}/skills/spec-manager/scripts/verify_links.py" --format json
   ```
   Flags (exits non-zero on any): a `locator` that doesn't resolve to a real file;
   a Gherkin behavior missing its `@SPEC-NNN`/`@BEH-NNN` tag; an **accepted**
   behavior whose feature still carries `TODO(scaffold)`; a `BEH-NNN` reused across
   specs; a declared `entry` that doesn't resolve; an orphan `@SPEC`/`@BEH` tag in
   a `.feature` matching no spec/behavior. (A `proposed`/`confirmed` behavior may
   omit locator/test — not an error; a declared locator must still resolve.)
2. **`verify_intent.py`** — declared-intent gate (governance G1, see below):
   ```bash
   python ".../scripts/verify_intent.py" --project . --format json
   ```
   Non-zero when an `accepted` behavior's linked test was modified/deleted since
   the `.intent-last-verified` baseline without a **new** `INTENT-NNN` record.
   > "Consume its JSON on the non-zero exit — do not run it with `check=True`."
3. **`adr.py verify`** — ADR integrity (dup `ADR-NNN`, malformed frontmatter,
   `status` outside the closed set, dangling `supersedes`/`superseded_by`).

Also: `frontmatter.validate_behaviors` rejects an unknown `level` and a non-string
`entry`, so a runner-dispatch typo fails loud.

> "Model-based contradiction checking … is **Tier-2 / Phase 3** — not part of
> this command yet. Phase 1 `verify` ships only the deterministic checks above."
> (`SKILL.md`)

## 13. Governance gates (behavior-layer additions — ecosystem-level)

spec-manager hosts the deterministic halves of several governance gates. The
model *judgment* for the advisory ones runs in the wrap-up skill; spec-manager's
scripts do the deterministic gather / append / lookup. All three advisory logs
share one append-only core (`scripts/resolution_log.py`: `append`, `load`,
`active` with latest-wins-per-key and `superseded` retirement).

- **G1 — Declared-Intent records (hard-block).** An `accepted` behavior's test is
  its machine-checkable guarantee; editing it requires an in-change-set
  `INTENT-NNN` record. `scripts/intent.py new --behavior BEH-NNN --approver "…"
  --rationale "…"` authors the record; `scripts/verify_intent.py` is the gate.
  Records live in `knowledge-base/intents/`. Only `accepted` behaviors are
  governed; the record must be **new in the change-set** (temporal self-scoping —
  a past record can't bless a future edit); the gate verifies a record *exists*,
  not that its rationale is honest.

- **G2 — Principle enforcement.** `knowledge-base/principles.md` is the
  constitution. Enforced by (a) **soft injection** (`principles.py list` surfaces
  it at `create`, `scan`, wrap-up) and (b) a **resolve-to-proceed checkpoint** at
  wrap-up (model judgment; each finding fixed/refuted/amended before wrap-up
  completes — never a script hard-block). Log:
  `knowledge-base/principle-resolutions.jsonl`.

- **G3 — Contradiction check (advisory / resolve-to-proceed).** When a spec or ADR
  is created/changed, check it doesn't contradict a higher-authority intent
  (authority order **principle > ADR > spec**). `scripts/contradictions.py context
  --spec <ID>` (or `adr-context --adr <ID>`) assembles the comparison set;
  `resolve` / `prior` back the recurrence triage. **ADRs are compared
  always-global** (all `accepted` ADRs, no category scoping — over-scoping is a
  silent miss). Malformed ADRs surface as `adr_warnings`, never silently dropped.
  Log: `knowledge-base/contradiction-resolutions.jsonl`.

- **P4a — ADR support.** `scripts/adr.py`: `new` / `list` / `verify` +
  `load_adrs`/`active_adrs` gather for G3. Only `accepted` ADRs are authoritative.

- **P4b — Declarative-drift check (advisory / resolve-to-proceed, wrap-up step 7).**
  Does changed code contradict *declared* intent (a spec's
  `intentional_decisions`/prose, or an accepted ADR's body)?
  `scripts/drift.py context --base <SHA>` gathers targets **scoped by
  blast-radius** (`related_code ∩ code-graph impact`) — deliberately NOT
  always-global like G3. Degrades to `changed-only` (never a silent empty set)
  when the code-graph is absent. `drift gaps` is the on-demand honesty view listing
  declared items with no `related_code` (invisible to drift). Log:
  `knowledge-base/drift-resolutions.jsonl`.

  > "P4b is *code-anchored* — it scopes by blast-radius … deliberately NOT
  > always-global like G3 (where every accepted ADR is compared regardless)."
  > (`SKILL.md`)

## 14. How specs act as the security false-positive filter

The through-line for the ecosystem: the **Intentional Design Decisions** section
(and the `intentional_decisions:` frontmatter list it summarizes) is what a
security scan cross-references to avoid flagging deliberate choices. `certainty`
backs the *declarative* intent (these decisions have no test to verify them); the
`--intentional` search flag (`search_specs.py`) surfaces exactly these specs. The
security-scan/resolver skills consume this to separate real issues from documented
design. This is the primary composition point between spec-manager and the
security skills.

## 15. Composition with other skills

- **code-graph** — used for impact-aware `update`/`scan` (blast radius →
  dependent files, not just changed files) and by `project_shape.py` (internal
  edge count) and `drift.py` (P4b scoping). Fallback to plain git diff /
  `changed-only` when absent.
- **docs-manager** — owns `knowledge-base/reference/`; `project_shape.py` shells
  out to `docs-manager/scripts/detect_project.py` for the stack summary.
- **behavior-graph / behavior-runner** — `bootstrap` builds the behavior graph
  after scan; behaviors authored here are what those skills project/run.
- **wrap-up** — orchestrates the governance gates: runs G1/verify (hard-block),
  G2 principle checkpoint (Phase 3.5 step 5), G3 contradiction (step 6), P4b drift
  (step 7). spec-manager provides the deterministic scripts; wrap-up provides the
  model judgment.
- **security-scan / security-resolver** — consume Intentional Design Decisions as
  the false-positive filter.

## 16. Search / supporting scripts

- `scripts/search_specs.py` — fast local search. Flags: `--query/-q`, `--tag/-t`,
  `--category/-c`, `--status/-s`, `--id`, `--min-certainty`, `--max-certainty`,
  `--below` (shorthand for max-certainty), `--intentional`, `--sort-certainty`
  (lowest first), `--format table|json|paths` (default `table`), `--dir/-d`.
  `find_specs_dir` prefers `knowledge-base/specs`, with a **legacy fallback** to
  `docs/specs` for not-yet-migrated projects.
- `scripts/frontmatter.py` — strict, stdlib-only, **fail-loud** frontmatter parser
  (a deliberate subset of YAML, not a full engine). Raises `FrontmatterError` on
  anything outside the grammar rather than silently dropping fields. Defines the
  spec + ADR schemas, `BEHAVIOR_STATES`, `KNOWN_ADAPTERS`, `KNOWN_LEVELS`, and
  `validate_behaviors` / `validate_adr`.
- `scripts/*` also ship `test_*.py` unit tests for most modules (adapters,
  adr, contradictions, drift, frontmatter, intent, principles, project_shape,
  resolution_log, verify_intent, verify_links).

## 17. Degradation behavior

- **No git repo / missing `.spec-last-update`** → `update` falls back to a full
  scan.
- **code-graph unavailable** → `update`/`scan` use plain git-diff analysis;
  `drift.py` reports `impact_source: changed-only` (direct files only) and the
  skill is instructed to note the narrower scope to the engineer (never a silent
  empty set); `project_shape.py` returns `unknown` if there's no graph.
- **No `.intent-last-verified` baseline** → G1 gate **skips** (fresh repo / full
  scan). `verify_intent` is also fail-open on git error.
- **Empty `decisions/`** → `adr verify` / `adr list` are no-ops (zero-regression
  for projects without ADRs).
- **Malformed ADR** → surfaced as a warning (`adr_warnings`), excluded from the
  comparison set, never silently dropped.
- **No constitution yet** → `principles.py list` prints empty output; soft
  injection just no-ops.
- **Legacy `docs/specs/` layout** → still readable via `find_specs_dir` fallback.

## 18. Honest limits

- **Model-based contradiction checking is NOT in `verify`** — that's Tier-2/Phase
  3. `verify` ships only deterministic checks. G3/P4b/G2 *judgment* runs in
  wrap-up, not as part of `verify`.
- **`scan` cannot reliably infer intent from code** — it only ever produces
  `proposed` candidates for human review; it never writes `accepted` records or
  code-tree scaffolds. Acceptance is a human act.
- **G1 verifies a record *exists*, not that its rationale is honest** — honesty is
  the (separate) Tier-2 governance track.
- **`certainty` is a heuristic**, not a guarantee; and post-behavior-layer it is
  explicitly *not* the signal for executable-behavior trust (that's the lifecycle
  `state`).
- **Gherkin scaffolds have no step definitions and no real steps** — a human must
  author them; an accepted behavior still carrying `TODO(scaffold)` is a
  verify-time error.
- **`bootstrap` is one-time**; ongoing intent acquisition is lazy (wrap-up's
  "touched code with no covering behavior" prompt).

## 19. Gotchas / UNVERIFIED

- **Path form for scripts varies in `SKILL.md`.** Some commands use the portable
  `${CLAUDE_PLUGIN_ROOT}/skills/spec-manager/scripts/…` form; others hard-code an
  absolute cached install path (`/Users/main/.claude/plugins/cache/freya-devkit/
  freya-devkit/0.1.0/skills/spec-manager/scripts/…`). The `${CLAUDE_PLUGIN_ROOT}`
  form is the portable one; the absolute path is machine-specific and should not
  be treated as canonical. (Recent commits mention a "Phase 5 work-laptop
  enablement (portability)" parking-lot item, consistent with this being in
  flux.)
- **`init` help/eval text still references the legacy `/docs/specs/` layout**
  (`evals/evals.json` expected_output says `/docs/specs/`), whereas current
  `SKILL.md` uses `/knowledge-base/specs/`. The `evals.json` appears stale
  relative to the knowledge-base migration. UNVERIFIED whether evals have been
  re-baselined.
- **`drift.py`/`contradictions.py`/`principles.py` were recently refactored** to
  delegate to the shared `resolution_log.py` (see git log G2/G3/P4b commits) — the
  behavior described here reflects the post-refactor code that was read directly.
- The `principles` and `drift gaps` top-level skill commands map onto
  `principles.py list` and `drift.py gaps` respectively; the SKILL Quick Reference
  lists them but the detailed prose treats them as sub-invocations.

## 20. Verbatim quotable lines

- "Manage feature specifications that capture WHAT features do and WHY they were
  designed that way." (`SKILL.md`)
- "The key feature: specs capture intentional decisions that might look like bugs
  or security issues." (`SKILL.md`)
- "`scan` produces a **review queue of `proposed` candidates** — never `accepted`,
  and **never files written into the code tree.**" (`SKILL.md`)
- "A candidate becomes `accepted` … when a **human accepts it**." (`SKILL.md`)
- "`principles.md` is the highest-authority intent record; `specs/` and
  `decisions/` sit below it." (`SKILL.md`)
- "This is the key section for preventing false positives in security scans and
  code reviews." (`references/spec-template.md`)
- "Internal edges (real wiring) are the brownfield signal; raw file count is not."
  (`scripts/project_shape.py`)
- "the model *depends on* [structured metadata], so the substrate must be reliable
  … **fails loud** — raising `FrontmatterError` on anything outside the grammar
  rather than silently dropping it." (`scripts/frontmatter.py`)
- "P4b is *code-anchored* … deliberately NOT always-global like G3." (`SKILL.md`)
