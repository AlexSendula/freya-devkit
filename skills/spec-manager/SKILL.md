---
name: spec-manager
description: |
  Create and manage feature specifications that capture intentional design decisions.

  Use this skill when the user wants to:
  - Initialize a specs structure in their project
  - Create specifications for features (before or after implementation)
  - Scan existing codebase to generate specs with certainty scores
  - Document intentional design decisions that might look like bugs/security issues
  - Search, review, or update existing specs
  - Verify specs are still accurate after code changes

  Also trigger proactively when the user mentions "specs", "specifications", "design decisions",
  "why was this done this way", "that's intentional", or when security scans flag things that
  might be intentional design choices.

  INTEGRATION: Uses /freya-devkit:code-graph skill (when available) for impact-aware spec updates.
  Analyzes blast radius of code changes to include dependent files in analysis, not just
  directly changed files.
---

# Spec Manager

Manage feature specifications that capture WHAT features do and WHY they were designed that way.

## Quick Reference

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
| `principles` | Print the project's principles (constitution) — used for soft injection & the G2 checkpoint |
| `drift gaps` | On-demand: declared items with no `related_code` (drift-blind); NOT part of every wrap-up — main P4b path is wrap-up step 7 (`drift context`) |
| `index` | Rebuild search index |
| `help` | Display help and usage information |

## How It Works

### Spec Structure

Specs live in `/knowledge-base/specs/` organized by category:

```
knowledge-base/specs/
├── README.md                    # Index with search/filter
├── auth/
│   ├── SPEC-001-passkeys.md
│   └── SPEC-002-sessions.md
├── api/
│   └── SPEC-003-rate-limiting.md
└── features/
    └── SPEC-004-team-photos.md
```

Each spec has structured frontmatter with a **certainty score** (0-100) indicating how confident the AI is about the spec's accuracy.

### Knowledge-Base Layout

`specs/` is one part of the project's `knowledge-base/` root, which is shared across skills:

```
knowledge-base/
├── principles.md      # Project constitution: project-wide rules (spec-manager init)
├── specs/             # Per-feature intent + decisions (spec-manager)
├── decisions/         # Cross-cutting ADRs (spec-manager init scaffolds; `adr create`/`list`/`verify`)
├── reference/         # Descriptive architecture/API/schema docs (docs-manager)
├── security/          # Security findings (codebase-security-scan)
└── .graph/            # Generated dependency + behavior graph data (code-graph)
```

spec-manager owns `principles.md`, `specs/`, and `decisions/`. `principles.md` is the highest-authority intent record; `specs/` and `decisions/` sit below it.

### Incremental Update Tracking

The `.spec-last-update` file in `knowledge-base/specs/` tracks the last sync state:

```
# Spec Manager Last Update
commit: abc123def456
timestamp: 2024-01-15T10:30:00Z
specs_updated: 5
specs_created: 2
```

This enables git-aware incremental updates via `/freya-devkit:spec-manager update` (without arguments).

### Certainty Scoring

| Score | Meaning | Action |
|-------|---------|--------|
| 90-100 | High confidence | Auto-accept |
| 70-89 | Good confidence | Brief review |
| 50-69 | Medium confidence | Ask user to confirm |
| 0-49 | Low confidence | Detailed review needed |

**Increases certainty:** code comments, matching docs in `/knowledge-base/reference/`, clear patterns, tests
**Decreases certainty:** no comments, ambiguous code, multiple interpretations, missing tests

> **What `certainty` is for now (post behavior-layer).** `certainty` measures
> confidence in an **inferred, not-yet-human-confirmed** spec — its job is to gate
> review of `scan` output and to back the **declarative** intent (the *Intentional
> Design Decisions* the security scan cross-references, which have no test to
> verify them). It is **not** the signal for *executable behavior* intent: that is
> carried by the behavior **lifecycle `state`** (`proposed → confirmed → accepted`),
> where **`confirmed` = a human confirmed the intent (test owed)** and **`accepted`
> = confirmed intent that a real linked test verifies**. So:
> - A **human-authored or human-confirmed** spec is trusted regardless of the
>   number — the old "agent drafted it, so score it lower" instinct is wrong once
>   a human has confirmed (an agent-drafted, human-confirmed spec is simply
>   confirmed; its behaviors are `accepted`).
> - `certainty` stays meaningful for `scan`-inferred, unconfirmed specs and for
>   declarative decisions, and for backward compatibility with existing specs.

---

## Commands

### `/freya-devkit:spec-manager init`

Initialize the specs structure and the intent/governance homes:

1. Create `/knowledge-base/specs/` if it doesn't exist
2. Create category subdirectories: `auth/`, `api/`, `data/`, `features/`, `infra/`, `integration/`, `ui/` — each with an empty `.gitkeep` file so the empty directory survives Git (Git does not track empty directories; this mirrors the `decisions/` README rationale).
3. Create `README.md` with index template and search instructions
4. Create `/knowledge-base/principles.md` from `references/principles-template.md` if it doesn't exist (the project's constitution — see [Knowledge-Base Layout](#knowledge-base-layout))
5. Create `/knowledge-base/decisions/` from `references/decisions-readme.md` if it doesn't exist (home for cross-cutting ADRs — see `references/adr-template.md` for the format). Scaffold its `README.md` index with:
   ```bash
   python "${CLAUDE_PLUGIN_ROOT}/skills/spec-manager/scripts/adr.py" \
     list --project .
   ```
   (On an empty `decisions/` directory this produces the header-only index table, which is the correct starting state.)
6. Report what was created
7. Create `/knowledge-base/intents/` (home for `INTENT-NNN` declared-intent records; starts empty with a `.gitkeep`)

### `/freya-devkit:spec-manager bootstrap`

The unified "bring the plugin up on this project" flow — it replaces running
`init` / `code-graph build` / `scan` by hand. It is **one-time**: for day-to-day
syncing use `update`, and after the first run newly-written code acquires intent
lazily via wrap-up's "touched code with no covering behavior" prompt.

**Flow:**

1. **Init structure.** Run the `init` flow (knowledge-base layout + `principles.md`). Idempotent — never clobbers existing files.
2. **Build the code graph.** Run `/freya-devkit:code-graph build` — the shape detector needs it, and it is cheap and useful regardless of shape.
3. **Detect shape and recommend.** Run:
   ```bash
   python "${CLAUDE_PLUGIN_ROOT}/skills/spec-manager/scripts/project_shape.py" --project . --format text
   ```
   Show the engineer the recommendation **and its evidence** (source-file count, internal-edge count, detected stack), then ask them to **confirm the branch or override**. On `unknown` (no graph / unreadable), ask outright with no recommendation. The detector never forces a branch — a one-time onboarding decision benefits from a human glance, so an unusually-structured repo can be overridden on sight rather than silently misclassified.
4. **Branch:**
   - **Brownfield →** run the `scan` flow to infer candidate behaviors at the **per-observable-behavior grain** (one `proposed` behavior per observable behavior/scenario, anchored to a route/entry where applicable — *not* per feature, *not* per route/function). All candidates are `proposed` records written into `knowledge-base/specs/`; **never** `.feature` scaffolds in the code tree (those appear only on acceptance). On a partially-onboarded repo this is **additive** — infer only for areas that have no existing spec; never overwrite or re-infer existing specs. Then run `/freya-devkit:behavior-graph --build --project .`. **Warn first** that scan over a large repo spawns discovery agents and can take a while.
   - **Greenfield →** skip `scan`. Build an (essentially empty) behavior graph so the machinery is initialized: `/freya-devkit:behavior-graph --build --project .` (with no `accepted`/`confirmed` behaviors this yields an empty `behavior.json`, which is correct). Print: *"Greenfield project — no inference run. Author behaviors forward as you build with `spec-manager create`."*
5. **Summary.** Report the knowledge-base layout created, the graph built, and (brownfield) a count of `proposed` candidates by category — with the reminder that **nothing needs review now**: the proposed queue is drained lazily (validate-on-hit at wrap-up, and the worklists once SP4 lands). The "full proposed behavior graph" is this corpus of `proposed` records in `knowledge-base/specs/`, *not* `behavior.json` (which projects only `accepted`/`confirmed`, so it stays ≈empty at first run — expected).

### `/freya-devkit:spec-manager create <name>`

Interactively create a new spec:

1. **Surface the constitution first** (soft injection — draft against the project's rules):
   ```bash
   python "${CLAUDE_PLUGIN_ROOT}/skills/spec-manager/scripts/principles.py" list --project .
   ```
   Keep these principles in view while authoring the spec/behaviors; a new spec should
   not propose intent that violates a principle. (Empty output ⇒ no constitution yet.)

2. Ask clarifying questions:
   - What feature is this for?
   - What should it do?
   - Why is this needed?
   - Any intentional design decisions?
   - Category and tags?

3. Generate spec ID (next sequential number)
4. Create spec file using template from `references/spec-template.md`. If the feature has observable behavior, add `behaviors:` records (see **Spec File Format**); leave the list empty for a purely declarative spec. New behaviors normally start as `proposed`
5. Set certainty to 100 (user-created)
6. Update README index
7. **Contradiction check (governance G3).** Run the G3 contradiction check on the new
   spec (see "Contradiction Check (governance G3)"): a freshly authored spec must not
   contradict a principle or a same-category peer's decision. Resolve any finding before
   finishing.

> **ID allocation (specs and behaviors).** Spec IDs are `SPEC-NNN`, allocated as
> the next sequential number across existing specs. Behavior records (the
> `behaviors:` list, see **Spec File Format**) use `BEH-NNN`, allocated the same
> way — the next sequential number across all behaviors in the project — and are
> **stable across renames** (never renumber a behavior; a renamed scenario keeps
> its `BEH-NNN`). Allocation is a convention applied when authoring; deterministic
> duplicate-ID detection is enforced by `verify`.

### `/freya-devkit:spec-manager scan`

**The big one** - scan codebase to generate specs with certainty metrics.

**Phase 1: Coordinator Discovery**

- **Load the constitution first** (soft injection), so intent classification happens
  against the project's rules:
  ```bash
  python "${CLAUDE_PLUGIN_ROOT}/skills/spec-manager/scripts/principles.py" list --project .
  ```

Spawn ONE coordinator agent that:
1. Scans codebase structure (Glob for key patterns)
2. Identifies feature areas: auth, api, ui, data, infra
3. Spawns parallel discovery agents for each area

**Phase 2: Parallel Discovery Agents**

Each area agent:
- Scans relevant code paths
- Identifies features/mechanisms
- Generates specs with inferred What, Why, and certainty scores
- Flags potential intentional decisions
- Notes areas needing clarification as `[NEEDS CLARIFICATION]`

**Discovery areas:**
- **Auth**: `src/lib/auth/`, middleware, auth routes, session handling
- **API**: `src/app/api/`, route handlers, rate limiting, caching
- **Data**: schema files, models, migrations, relationships
- **Features**: `src/components/`, pages, user-facing features
- **Infra**: config files, environment setup, infrastructure

**Phase 2.5: Intent Classification → a review queue (not staged scaffolds)**

For each piece of intent discovered, classify it:

```
Is it observable behavior expressible as a test?
  ├─ Yes → propose a Behavior (state: proposed)
  │         ├─ new user-visible        → recommend a Gherkin scaffold
  │         └─ already covered by a test → recommend linking the native test
  └─ No  → declarative
            ├─ cheaply guarded by a (often negative) scenario? → recommend promotion
            └─ Feature-local → Intentional Design Decisions (inline)
               Cross-cutting → note for knowledge-base/decisions/ (ADR, deferred)
```

**Hard rules for `scan`:**
- `scan` produces a **review queue of `proposed` candidates** — never `accepted`,
  and **never files written into the code tree.** Intent cannot be reliably
  inferred from code; auto-generating authoritative-looking scaffolds from the
  implementation would reintroduce the "tests mirror code" problem the behavior
  layer exists to fix.
- A candidate becomes `accepted` — and only then does its scaffold/link enter the
  code tree (via the adapter, see **Adapters**) — when a **human accepts it**.
- Classification is **interactive for low certainty**: reuse the one-question-at-
  a-time `review` flow and the existing certainty thresholds (below). Promotion of
  a declarative decision to a guard scenario is **recommended, not forced**.

**Phase 3: Certainty Evaluation**

For each generated spec:
1. Cross-reference with `/knowledge-base/reference/` documentation
2. Check code comments for intent
3. Validate "what" matches code behavior
4. Adjust certainty score

**Phase 4: Interactive Clarification**

Present user with:
1. Summary of all generated specs
2. Specs grouped by certainty level
3. For low-certainty specs (<70%), ask clarifying questions

**Phase 5: Generate Index**

Update `knowledge-base/specs/README.md` with all specs.

### `/freya-devkit:spec-manager update` (no arguments)

**The smart sync command** - git-aware incremental spec updates.

> 💡 **Best Practice**: Use `update` (no args) for day-to-day syncing after code changes. Use `scan` only for initial setup or complete refresh.

**Phase 1: Change Detection**

1. Read `.spec-last-update` file from `knowledge-base/specs/` for last commit hash
2. If missing or no git repo, fall back to full scan (like `scan` command)
3. Run `git diff <last-commit>..HEAD --name-only` to get changed files
4. If no changes detected, report "specs are up to date" and exit

**Phase 2: Impact Analysis (Code-Graph Enhanced)**

1. Map changed files to existing specs via `related_code` frontmatter
2. **If `/freya-devkit:code-graph` skill is available:**
   - Call `/freya-devkit:code-graph impact <changed-files>` to get blast radius
   - Include dependent files in analysis, not just directly changed files
   - Map blast radius to existing specs via `related_code`
3. **If code-graph is not available (fallback):**
   - Use only directly changed files from git diff
4. Identify specs whose `related_code` paths have been modified
5. Identify new code areas that don't have corresponding specs
6. Group affected areas by category for parallel processing

**Phase 3: Update Existing Specs**

For each spec with changed related code:

1. Re-read the spec's `related_code` paths
2. Analyze if code still matches spec content
3. If behavior changed:
   - Update spec content to reflect changes
   - Add entry to Change History section
   - Adjust certainty score
4. If code removed:
   - Mark spec as `deprecated` or flag for review
5. Log all updates for summary report

**Phase 4: Generate New Specs**

For new code without specs:

1. Spawn discovery agents for changed areas only (not full codebase)
2. Analyze new features/mechanisms
3. Generate specs with appropriate certainty scores
4. Flag specs with certainty < 70% for user review
5. Use standard categories and naming conventions

**Phase 5: Review & Fix**

1. Cross-reference updated specs with `/knowledge-base/reference/` docs for consistency
2. Check for conflicts between related specs
3. Auto-fix obvious issues:
   - Typos, formatting
   - Stale references to removed code
   - Outdated status values
4. Generate summary report:
   ```
   ✅ Updated: 3 specs (SPEC-001, SPEC-003, SPEC-007)
   📝 Created: 1 new spec (SPEC-012)
   ⚠️ Needs Review: 1 spec (SPEC-005 - low certainty)
   ```

**Phase 6: Update Tracking**

1. Get current commit hash: `git rev-parse HEAD`
2. Write to `knowledge-base/specs/.spec-last-update`:
   ```yaml
   # Spec Manager Last Update
   commit: <current-hash>
   timestamp: <ISO-8601>
   specs_updated: <count>
   specs_created: <count>
   ```
3. Update README index with any new specs

### `/freya-devkit:spec-manager update <spec>`

Re-analyze code and update a specific spec (single spec mode):

1. Load the spec by ID (e.g., `SPEC-001`)
2. Re-read its `related_code` paths
3. Analyze if code still matches spec
4. If changes detected:
   - Prompt user for confirmation on significant changes
   - Update spec content
   - Add entry to Change History
5. Update certainty score based on current code state
6. Run quick review for consistency with related specs
7. **Contradiction check (governance G3).** After updating the spec, run the G3
   contradiction check on it (see "Contradiction Check (governance G3)") — a changed
   decision must not contradict a principle or a same-category peer. Resolve any finding.

### `/freya-devkit:spec-manager verify`

Check if all specs are still accurate, **and** run the deterministic behavior
link-integrity checks (Tier-1):

1. Run the deterministic link checks first — these are cheap and certain:
   ```bash
   python "${CLAUDE_PLUGIN_ROOT}/skills/spec-manager/scripts/verify_links.py" --format json
   ```
   This reports (and exits non-zero on) any of:
   - a behavior `locator` that does not resolve to a real file;
   - a Gherkin behavior whose feature file is missing its `@SPEC-NNN` / `@BEH-NNN` tag;
   - an **accepted** behavior whose feature still carries its `TODO(scaffold)` marker;
   - (a `proposed`/`confirmed` behavior may omit a locator/test — that is **not** an error;
     a locator or `entry` that *is* declared must still resolve);
   - a `BEH-NNN` reused across specs;
   - a declared `entry` (integration behaviors) that does not resolve to a real file;
   - an orphan `@SPEC`/`@BEH` tag in a `.feature` that matches no spec/behavior.
   These are **deterministic failures** — at wrap-up they hard-block (vision §8).
1b. Run the deterministic **declared-intent gate** (governance G1) — also a deterministic
    hard-block:
    ```bash
    python "${CLAUDE_PLUGIN_ROOT}/skills/spec-manager/scripts/verify_intent.py" --project . --format json
    ```
    This exits non-zero when an `accepted` behavior's linked test was **modified or
    deleted** in the current change-set (since the `.intent-last-verified` baseline)
    without a **new** `INTENT-NNN` record naming that behavior. Remedy: `spec-manager
    intent new <BEH-NNN>` (declare the change) or revert the test edit. With no
    baseline marker the gate skips. **Consume its JSON on the non-zero exit — do not
    run it with `check=True`.**
   (Separately, `frontmatter.validate_behaviors` rejects an unknown `level`
   — it must be one of `unit`/`component`/`integration`/`e2e` — and a non-string
   `entry`, so a typo in the runner's dispatch key fails loud rather than silently
   routing a behavior to no coverage path.)
1c. Run the deterministic **ADR integrity check** — also a deterministic hard-block:
    ```bash
    python "${CLAUDE_PLUGIN_ROOT}/skills/spec-manager/scripts/adr.py" \
      verify --project .
    ```
    Exits non-zero on a duplicate `ADR-NNN`, malformed/invalid ADR frontmatter,
    `status` outside the closed set, or a `supersedes`/`superseded_by` that does
    not resolve to a real ADR id. On an empty `decisions/` directory this is a
    no-op (zero-regression for projects without ADRs).
2. Load each spec and read its `related_code` paths
3. Analyze if code matches spec
4. Report discrepancies with recommendations
5. Flag specs with stale certainty (haven't been verified recently)

> Model-based contradiction checking (comparing intent against higher-authority
> principles/decisions) is **Tier-2 / Phase 3** — not part of this command yet.
> Phase 1 `verify` ships only the deterministic checks above.

### `/freya-devkit:spec-manager adr create <name>`

Interactively author a new cross-cutting Architecture Decision Record (ADR).

Ask questions **one at a time**:

1. What is the decision? (the concrete choice being made)
2. What is the rationale? (why this choice; alternatives briefly)
3. What alternatives were rejected, and why?
4. Under what conditions should this decision be revisited?
5. Optional: any tags? (human navigation only — not G3 filters)
6. Optional: does this supersede an existing ADR? (`ADR-NNN`)

Then:

```bash
python "${CLAUDE_PLUGIN_ROOT}/skills/spec-manager/scripts/adr.py" \
  new --title "<title>" --status accepted \
  [--tag <tag>]... [--supersedes ADR-NNN] [--project .]
```

This allocates the next sequential `ADR-NNN`, writes a four-section scaffold
(`Decision`, `Rationale`, `Rejected Alternatives`, `Revisit Conditions`) to
`knowledge-base/decisions/ADR-NNN-<slug>.md`, and prints the path. Fill each
section with the answers collected above.

After filling the body, regenerate the index:

```bash
python "${CLAUDE_PLUGIN_ROOT}/skills/spec-manager/scripts/adr.py" \
  list --project .
```

Immediately run the **changed-ADR** path of the G3 contradiction check (see
"Contradiction Check (governance G3)") — a new ADR must not contradict a
principle or a peer ADR. Resolve any finding before finishing.

> **ID allocation.** ADR IDs are `ADR-NNN`, allocated as the next sequential
> number across existing `knowledge-base/decisions/ADR-*.md` files. Duplicate-ID
> detection is enforced by `adr verify`.
>
> **Lifecycle.** A human-authored ADR starts `accepted` (the same way a
> human-authored spec starts at certainty 100). Use `--status proposed` only
> when the decision is still under team review. Only `accepted` ADRs constrain
> specs and are compared by G3.

### `/freya-devkit:spec-manager adr list`

Print / regenerate the ADR index (a markdown table of all ADRs in
`knowledge-base/decisions/`):

```bash
python "${CLAUDE_PLUGIN_ROOT}/skills/spec-manager/scripts/adr.py" \
  list [--format table|json] [--project .]
```

`--format table` (default) emits a `# Architecture Decision Records` markdown
table (`ID | Title | Status`). `--format json` emits the full parsed ADR list.
Use this to regenerate `decisions/README.md` after authoring or editing ADRs.

### `/freya-devkit:spec-manager adr verify`

Run deterministic Tier-1 integrity checks on all ADRs (hard-blocks at wrap-up):

```bash
python "${CLAUDE_PLUGIN_ROOT}/skills/spec-manager/scripts/adr.py" \
  verify [--project .]
```

Exits non-zero (prints errors to stderr) on any of:
- duplicate `ADR-NNN` id across files
- malformed or invalid frontmatter (missing required `id`/`title`/`status`)
- `status` outside the closed set `proposed|accepted|superseded|deprecated`
- `supersedes` or `superseded_by` that does not resolve to a real ADR id

A malformed ADR that `adr verify` would catch is also surfaced as an
`adr_warnings` entry in `build_context` / `build_adr_context` output — it is
never silently dropped from the comparison set (the no-silent-miss guarantee).

---

### `/freya-devkit:spec-manager search <query>`

Full-text search across specs:

1. Run `python "${CLAUDE_PLUGIN_ROOT}/skills/spec-manager/scripts/search_specs.py" --query "<query>"`
2. Interpret results for relevance
3. Present top matches with summaries
4. Offer to load full specs for relevant matches

### `/freya-devkit:spec-manager by-tag <tag>`

Filter specs by tag:

1. Run `python "${CLAUDE_PLUGIN_ROOT}/skills/spec-manager/scripts/search_specs.py" --tag <tag>`
2. Present results in table format
3. Offer to load full specs

### `/freya-devkit:spec-manager get <id...>`

Load full spec(s) for one or more IDs:

1. Parse the provided spec IDs
2. Read each spec file
3. Return complete content including all sections

Examples:
- `/freya-devkit:spec-manager get SPEC-001` - Get single spec
- `/freya-devkit:spec-manager get SPEC-001 SPEC-003 SPEC-007` - Get multiple specs

### `/freya-devkit:spec-manager review`

Interactive review of low-certainty specs with intelligent uncertainty handling.

**Phase 1: Discovery**
1. Run `python "${CLAUDE_PLUGIN_ROOT}/skills/spec-manager/scripts/search_specs.py" --sort-certainty --below 100`
2. Present list sorted by certainty (lowest first)
3. Ask user which to review (e.g., "lowest three", "SPEC-005", "all below 80%")

**Phase 2: Iterative Review**

Process specs **one at a time** and ask questions **one at a time**:

> ⚠️ **Critical**: Never batch multiple questions together. Present one discrepancy or question, wait for the answer, then move to the next. This creates a natural back-and-forth conversation rather than an overwhelming questionnaire.

For each selected spec:

1. **Present ONE discrepancy or question at a time:**
   - "I found that the spec says X but the code shows Y. Which is correct?"
   - "I inferred X from the code - is this correct?"
   - "Why was this designed this way?"
   - "Any intentional decisions to add?"

2. **Analyze response for uncertainty:**
   - **Hedging**: "I think", "maybe", "probably", "I guess", "not sure", "might be"
   - **Qualifiers**: "kind of", "sort of", "somewhat", "mostly"
   - **Direct uncertainty**: "I don't know", "unclear", "not certain"
   - **Incompleteness**: Partial answer, skipped parts

3. **If response is uncertain or incomplete:**
   a. **Self-verify by examining code:**
      - Re-read `related_code` paths
      - Check comments, tests, and `/knowledge-base/reference/` for evidence
      - Look at commit history or related patterns

   b. **Present findings to user:**
      - "Based on the code at [file:line], I see X which suggests Y"
      - "I found evidence in [docs/tests] that indicates Z"
      - "Does this interpretation sound accurate?"

   c. **Offer options if still ambiguous:**
      - "I see two possibilities: A) ... or B) ..."
      - "Based on [evidence], I lean toward X - agree?"

   d. **Loop until confirmed:**
      - Don't update spec until user confirms understanding
      - Mark any remaining uncertainty in the spec itself

4. **Update spec** only when confident understanding is reached
5. **Document remaining uncertainty** if any exists:
   - Set appropriate certainty score
   - Add `[NEEDS CLARIFICATION: ...]` notes if needed

**Phase 3: Summary**
Report what was clarified, what remains uncertain, and updated certainty scores.

### `/freya-devkit:spec-manager index`

Rebuild the search index:

1. Scan all specs in `/knowledge-base/specs/`
2. Parse frontmatter
3. Update `README.md` index

### `/freya-devkit:spec-manager help`

Display help information about the spec-manager skill, including:
- What the skill does
- All available commands
- Usage examples

When called with `help` or `--help` or `-h`:
1. Show the Quick Reference table
2. Display brief description from the skill intro
3. Show example usage patterns

**Example usage:**
```
/freya-devkit:spec-manager help
/freya-devkit:spec-manager --help
/freya-devkit:spec-manager -h
```

**Example output:**
```
# Spec Manager Help

Manage feature specifications that capture WHAT features do and WHY they were designed that way.

## Commands

| Command | Description |
|---------|-------------|
| init    | Initialize /knowledge-base/specs/ structure |
| create  | Create new spec interactively |
| scan    | Full codebase scan, generate specs with certainty scores |
| update  | Git-aware incremental sync (recommended for day-to-day) |
| update <spec> | Re-analyze and update a specific spec |
| verify  | Check if all specs match current code |
| search  | Full-text search across specs |
| by-tag  | Filter specs by tag |
| get     | Load full spec(s) by ID |
| review  | Interactive review of low-certainty specs |
| index   | Rebuild search index |
| help    | Display this help message |

## Usage Examples

/freya-devkit:spec-manager init                    # Initialize specs directory
/freya-devkit:spec-manager create user-auth        # Create a new spec interactively
/freya-devkit:spec-manager scan                    # Full codebase scan (first time or complete refresh)
/freya-devkit:spec-manager update                  # Smart sync after code changes (recommended)
/freya-devkit:spec-manager update SPEC-001         # Update a specific spec
/freya-devkit:spec-manager search authentication   # Search specs for "authentication"
/freya-devkit:spec-manager get SPEC-001            # Read a specific spec
/freya-devkit:spec-manager verify                  # Check all specs are still accurate
```

---

## Intentional Design Decisions

The key feature: specs capture intentional decisions that might look like bugs or security issues.

**Example from a spec:**

```markdown
## Intentional Design Decisions

### No Password Fallback
**Decision**: We do not offer password authentication as a fallback.

**Rationale**: Offering password fallback would create a phishing vector.

**Security Scan Note**: Any security tool flagging "missing password authentication"
should be ignored - this is intentional.
```

This helps:
- Security scans distinguish real issues from design decisions
- New developers understand why code is the way it is
- AI agents avoid "fixing" intentional choices

---

## Declared-Intent Records (governance G1)

An `accepted` behavior's test is its machine-checkable guarantee. Editing that test
is treated as an attempt to change the intended behavior, and is a **deterministic
hard-block** at wrap-up unless an `INTENT-NNN` record in the same change-set declares
it (vision §7). This is the *only* sanctioned way to change an accepted guarantee;
otherwise a red (or silently-edited-green) accepted test is always a regression.

**Record** — `knowledge-base/intents/INTENT-NNN.md`, block-style frontmatter:

```markdown
---
id: INTENT-001
behaviors:
  - BEH-003
approver: Alex
date: 2026-07-01
---
## Rationale
Anti-enumeration response changed from a 404 to a uniform 200 per the revised
threat model.
```

**Create one** (when the gate blocks you, or proactively before editing an accepted test):

```bash
python "${CLAUDE_PLUGIN_ROOT}/skills/spec-manager/scripts/intent.py" \
  new --behavior BEH-003 --approver "<you>" --rationale "<why the guarantee is changing>"
```

**Scope & rules:**
- Only `accepted` behaviors are governed. `proposed`/`confirmed`/`quarantined`/`deprecated` tests change freely.
- A record authorizes **only when it is new in the change-set** — a past record cannot bless a future edit (temporal self-scoping).
- Newly *added* accepted tests and pure renames need no record; *modified* or *deleted* ones do.
- The file is the gate's source of truth; add an `Intent: INTENT-NNN` commit trailer for traceability.
- The gate verifies a record *exists* — not that its rationale is honest (that judgment is the Tier-2 governance track, not G1).

---

## Principle Enforcement (governance G2)

`knowledge-base/principles.md` is the project's constitution. It is enforced two ways
(vision §8), both of which G2 makes real:

- **Soft injection:** `principles.py list` surfaces it at design time (`create`, `scan`)
  and at wrap-up, so work happens with the rules in view.
- **Checkpoint (resolve-to-proceed):** at wrap-up, the change diff is judged against the
  principles; each finding is **fixed / refuted / amended** before wrap-up completes —
  "ignore and push" is not an option. This is model judgment (a *procedural* gate, never
  a script hard-block), with an LLM-first triage of prior resolutions (auto-clear /
  retire / escalate) recorded in the append-only `knowledge-base/principle-resolutions.jsonl`.
  See the wrap-up skill's Phase 3.5, step 5.

The `principles.py resolve` / `prior` subcommands back the checkpoint; `list` backs
soft injection.

---

## Contradiction Check (governance G3)

When a spec or ADR is **created or changed**, check it doesn't **contradict a
higher-authority intent** (authority order: **principle > ADR > spec**). Runs
interactively here (`create`, `update <spec>`, `adr create`) and batched at
wrap-up (Phase 3.5 step 6, over changed `specs/**` *and* `decisions/**`). Model
judgment → **advisory / resolve-to-proceed**, never a hard-block on model confidence.

### Changed-spec path (for a changed `<SPEC-ID>`)

1. **Assemble the comparison set:**
   ```bash
   python "${CLAUDE_PLUGIN_ROOT}/skills/spec-manager/scripts/contradictions.py" \
     context --project . --spec <SPEC-ID>
   ```
   Returns `principles` (higher authority), **`adrs`** (all active ADRs —
   always-global, no category scoping; the LLM filters relevance), same-category
   `peers`' decisions, and **`adr_warnings`** (malformed ADRs that could not be
   parsed — surface these; a malformed ADR must not silently vanish from the
   comparison set). The spec itself is excluded. Empty set ⇒ **no-op**.

   > **Always-global ADR comparison:** ADRs are cross-cutting by definition.
   > The check shows the LLM *all* `accepted` ADRs — no category or tag
   > scoping. An excluded ADR is a silent miss (unrecoverable); an irrelevant
   > ADR is noise the LLM dismisses in one line. `tags` and `related_code` on
   > ADRs are human-navigation / P4b metadata, never G3 filters.

2. **Judge** the changed spec's intent against **each principle**, **each active ADR**,
   and each same-category peer: *does this changed intent contradict it?* Name each
   finding by the conflicting item (`principle:2`, `ADR-003`, or `SPEC-003`) and why.
   Surface any `adr_warnings` — the LLM must not judge without knowing which ADRs
   were excluded due to malformation.

3. **Triage against prior resolutions:**
   ```bash
   python "${CLAUDE_PLUGIN_ROOT}/skills/spec-manager/scripts/contradictions.py" \
     prior --project . --spec <SPEC-ID>
   ```
   Re-validate any prior against the *current* spec text: **still valid** → auto-clear
   (`resolve --verdict auto-cleared`); **stale** (spec rewritten) → retire
   (`resolve --verdict superseded`); **now a real contradiction** → escalate. Guardrails:
   re-judge the current intent vs the *specific* prior reason (not the spec id); bias to
   escalate on ambiguity; always log auto-clears; a finding with no prior always reaches
   the human.

4. **Resolve each finding** (authority table):

   | Contradicts | Resolution |
   |---|---|
   | a principle | **Fix the spec** (ADR outranks spec; principle outranks both) — or consciously amend the principle |
   | an **ADR** | **Fix the spec** (ADR outranks) — or consciously amend the ADR |
   | a peer spec (same category) | **Reconcile** (fix either side, or refute) |

   ```bash
   python "${CLAUDE_PLUGIN_ROOT}/skills/spec-manager/scripts/contradictions.py" \
     resolve --project . --spec <SPEC-ID> \
     --against <principle:N|ADR-NNN|SPEC-NNN> \
     --verdict <refuted|amended|auto-cleared|superseded> --reason "…"
   ```
   `ADR-NNN` is a valid `--against` value with no schema change.
   A **fix** (editing the spec / peer) needs no record — git is the record. Records +
   any amendment stage with the **artifacts** commit.

### Changed-ADR path (for an ADR created or changed this cycle)

For each ADR file added or modified in the current change-set, run:

```bash
python "${CLAUDE_PLUGIN_ROOT}/skills/spec-manager/scripts/contradictions.py" \
  adr-context --project . --adr <ADR-NNN>
```

Returns `adr` (the changed record), `principles`, `peer_adrs` (all other active
ADRs, excluding the changed one), and `adr_warnings`. Note: if the ADR is newly
created with `status: proposed` it will not appear in `active_adrs` and the
response will include a `note` field — this is expected; re-run after setting it
to `accepted`.

Judge the changed ADR against each principle and each peer ADR:

| Contradicts | Resolution |
|---|---|
| a principle | **Fix the ADR** (principle outranks) — or consciously amend the principle |
| a peer ADR | **Reconcile** (fix either side, or refute) |

Record each resolution with `--spec ADR-NNN --against principle:N|ADR-MMM`:

```bash
python "${CLAUDE_PLUGIN_ROOT}/skills/spec-manager/scripts/contradictions.py" \
  resolve --project . --spec <ADR-NNN> \
  --against <principle:N|ADR-MMM> \
  --verdict <refuted|amended|auto-cleared|superseded> --reason "…"
```

`ADR-NNN` is a valid `--spec` value; this reuses the same
`contradiction-resolutions.jsonl` and latest-wins/`superseded` retirement — no
new JSONL field, no new module.

**Declarative-drift** (code-vs-declared-intent) is a separate P4b track.

---

## Declarative-Drift Check (governance P4b)

When code changes in this cycle, check whether those changes contradict any
*declared* intent — a spec's `intentional_decisions` or a spec's prose, or an
accepted ADR's body. Checked at wrap-up (step 7), after the G3 contradiction
check. Model judgment → **advisory / resolve-to-proceed**, never a hard-block
on model confidence; wrap-up must not complete while a finding is unresolved.

> **Asymmetry with G3 in one line:** P4b is *code-anchored* — it scopes by
> blast-radius (only declared items whose `related_code` intersects the
> change) — deliberately NOT always-global like G3 (where every accepted ADR
> is compared regardless). An item with no `related_code` is invisible to the
> drift check; `gaps` (on-demand) is the honesty view for those.

This section is the single source for the P4b procedure. Wrap-up step 7
references it rather than duplicating it.

### The gather

Run `context` with the same `$BASE` used in step 3 of wrap-up:

```bash
python "${CLAUDE_PLUGIN_ROOT}/skills/spec-manager/scripts/drift.py" \
  context --base "$BASE" [--project .]
```

Returns `{base, impact_source, impact_count, targets, warnings}`. Each target
has `item` (`SPEC-NNN` or `ADR-NNN`), `kind` (`spec` | `adr`), `related_code`
(the full declared footprint), `hit_paths` (the subset inside the blast
radius), and either `decisions` + `file_path` (spec targets) or `title` +
`body` (ADR targets).

`impact_source` degrades to `changed-only` when the code-graph is absent —
the blast radius then covers only the directly changed files, not their
dependents. This is **never a silent empty set**: when `changed-only` is
reported, note it to the engineer (some related items may be out of scope).
No targets ⇒ skip the judgment step (nothing in scope for this change).

### The judgment loop + resolve-to-proceed

**Judge each target.** Read the declared intent (`decisions` list + spec prose
or ADR `body`) and `git diff "$BASE"..HEAD -- <hit_paths>`. For each target,
determine whether the diff contradicts the declared intent.

**Triage each finding against prior resolutions:**

```bash
python "${CLAUDE_PLUGIN_ROOT}/skills/spec-manager/scripts/drift.py" \
  prior --item <SPEC-NNN|ADR-NNN> [--paths <hit_paths>] [--project .]
```

Re-validate any prior against the *current* hunk (not just the file):
- **Still valid** — flagged code is the same intentional thing the prior
  described, materially unchanged → **auto-clear** and log:
  `resolve --verdict auto-cleared`
- **Stale** — code changed; the prior no longer maps → **retire** and
  re-evaluate: `resolve --verdict superseded`
- **Now a real conflict** → **escalate.**

Guardrails (same as G2/G3): re-judge the current hunk against the *specific*
prior reason; **bias to escalate** on ambiguity; a finding with **no prior
always goes to the human.**

**Resolve every escalated finding — do not complete wrap-up until each is
resolved** (authority-neutral: neither the code nor the declared intent has
automatic priority):

| Resolution | Action | Record? |
|---|---|---|
| **Fix the code** | Change code to align with declared intent, re-judge | No — git records the fix |
| **Amend the intent** | Edit the spec decision or ADR body, then log: `resolve --verdict amended` | Yes — log the amendment |
| **Refute** | False positive; the conflict isn't real: `resolve --verdict refuted` | Yes — log the refutation |

"Ignore and push" is **not** a resolution. Drift findings are resolved in the
wrap-up that raised them (no backlog debt).

### Commands

**`context` — gather the blast-radius-scoped drift targets:**

```bash
python "${CLAUDE_PLUGIN_ROOT}/skills/spec-manager/scripts/drift.py" \
  context --base <SHA> [--project .]
```

**`resolve` — append a resolution record** (keyed `(item, path)`; retirement
is a later `superseded` record — append-only, never a mutated field):

```bash
python "${CLAUDE_PLUGIN_ROOT}/skills/spec-manager/scripts/drift.py" \
  resolve --item <SPEC-NNN|ADR-NNN> \
  --verdict <refuted|amended|auto-cleared|superseded> \
  --reason "<why>" \
  --paths <file1> [<file2> ...] \
  [--commit <sha>] [--date <YYYY-MM-DD>] [--project .]
```

**`prior` — active prior resolutions for an item** (recurrence triage):

```bash
python "${CLAUDE_PLUGIN_ROOT}/skills/spec-manager/scripts/drift.py" \
  prior --item <SPEC-NNN|ADR-NNN> [--paths <file1> ...] [--project .]
```

**`gaps` — on-demand coverage view** (declared items with no `related_code`,
invisible to the drift check):

```bash
python "${CLAUDE_PLUGIN_ROOT}/skills/spec-manager/scripts/drift.py" \
  gaps [--project .] [--format json]
```

> `gaps` is **on-demand** — run it periodically to find specs and ADRs whose
> declared intent has no `related_code` anchor (and is therefore drift-blind).
> Recommended action: add `related_code` entries to those items so future
> drift checks can scope them. `gaps` is **NOT** part of every wrap-up run.
> Drift's main path is wrap-up-driven (step 7 → `context`).

---

## Search Script

The `python "${CLAUDE_PLUGIN_ROOT}/skills/spec-manager/scripts/search_specs.py"` script provides fast local searching.

**Usage:**
```bash
python "${CLAUDE_PLUGIN_ROOT}/skills/spec-manager/scripts/search_specs.py" --query "authentication"
python "${CLAUDE_PLUGIN_ROOT}/skills/spec-manager/scripts/search_specs.py" --tag security --min-certainty 70
python "${CLAUDE_PLUGIN_ROOT}/skills/spec-manager/scripts/search_specs.py" --category auth
python "${CLAUDE_PLUGIN_ROOT}/skills/spec-manager/scripts/search_specs.py" --id SPEC-001
python "${CLAUDE_PLUGIN_ROOT}/skills/spec-manager/scripts/search_specs.py" --sort-certainty    # Lowest first
python "${CLAUDE_PLUGIN_ROOT}/skills/spec-manager/scripts/search_specs.py" --below 100         # All below 100% certainty
```

**Output formats:**
- `--format table` (default): Human-readable table
- `--format json`: Machine-readable JSON
- `--format paths`: Just file paths

The script is in the skill's `scripts/` directory. Call it with `python` using the full path.

---

## Spec File Format

See `references/spec-template.md` for the full template. Key frontmatter fields:

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
    state: accepted            # proposed | confirmed | accepted | quarantined | deprecated
    adapter: cucumber          # cucumber | behave | pytest-bdd | jest | playwright | ... | manual
    locator: features/auth/passkey-login.feature#successful-passkey-login
---
```

`behaviors` is the list of first-class `Behavior` records this spec owns (empty/
absent ⇒ a purely declarative spec). Each record carries a stable `BEH-NNN` id, a
lifecycle `state` (`accepted` is authoritative — verified by a linked test;
`confirmed` = intent confirmed, test owed), an `adapter`, and a
`locator` to its executable test. `related_code` is expected on declarative specs
too. See `references/spec-template.md` for the full record schema.

Key sections:
- **What**: The feature's purpose, scope, and bounds — *not* the step-by-step behavior the test owns
- **Why**: Why it's needed, what problem it solves
- **Behavior**: A table linking each `BEH-NNN` to the test that verifies it (no copied scenario text — single source of truth). Replaces the old inert acceptance-criteria checklist
- **Intentional Design Decisions**: Non-executable (declarative) design choices with rationale
- **Related Specs**: Links to related specifications
- **Change History**: Log of changes and reasons

---

## Adapters

A behavior is linked to the test that verifies it by an **adapter** + **locator**.
Two adapters in Phase 1:

### Gherkin (`cucumber` / `behave` / `pytest-bdd`) — default for new behavior

When an `accepted` behavior needs a new test, spec-manager writes a **skeleton
`.feature`** — never real scenarios (authoring real steps is forward-design work
for a human). Emit it with:

```bash
python "${CLAUDE_PLUGIN_ROOT}/skills/spec-manager/scripts/adapters.py" gherkin-scaffold \
  --spec-id SPEC-012 --title "Passkey Login" \
  --spec-path knowledge-base/specs/auth/SPEC-012-passkey-login.md \
  --behavior "BEH-007:Successful passkey login"
```

This produces a feature file in the **code tree** at `features/<category>/<name>.feature`:

```gherkin
@SPEC-012
Feature: Passkey Login
  # Intent and rationale live in knowledge-base/specs/auth/SPEC-012-passkey-login.md

  @BEH-007
  Scenario: Successful passkey login
    # TODO(scaffold): replace with real steps. Step definitions are not generated.
    Given <initial state>
    When <action>
    Then <expected outcome>
```

- The `@SPEC-NNN` (on `Feature`) and `@BEH-NNN` (on each `Scenario`) tags are
  **required** — they are the reverse links. Step definitions are **not** created.
- The behavior's `locator` is `features/<category>/<name>.feature#<scenario-slug>`.
- A scaffold keeps its `TODO(scaffold)` marker until a human fills in real steps;
  `verify` treats an **accepted** behavior that still carries the marker as an error.

### Native (`jest`, `playwright`, `pytest`, …) — link an existing test

When a behavior is already covered by a real test, **link it by `locator`** — no
`.feature` is written, nothing is rewritten. Set `adapter` to the runner and
`locator` to `path/to/test#case` (or `path::node` for pytest). This keeps adoption
cheap for projects that already have tests.

---

## Update Workflow Comparison

| Scenario | Recommended Command |
|----------|---------------------|
| After implementing a feature | `update` (incremental, git-aware) |
| Single spec needs update | `update <spec>` |
| First time setup | `init` then `update` (or `scan`) |
| Check all specs are accurate | `verify` or `update` |
| Complete codebase refresh | `scan` |

---

## References

- `references/spec-template.md` - Template for creating new specs
- `references/categories.md` - Standard categories and tag guidelines

Read these when you need to create new specs or understand category conventions.

## Code-Graph Integration

When the `/freya-devkit:code-graph` skill is available, spec-manager uses it for enhanced analysis:

**Enhanced Phase 2 (Impact Analysis):**
1. Get changed files from git diff
2. Call `/freya-devkit:code-graph impact <changed-files>` to get blast radius
3. Combine results to get full blast radius
4. Map blast radius to existing specs via `related_code`

**Enhanced scan mode:**
- Use `/freya-devkit:code-graph dependents <file>` to suggest `related_code` entries for new specs
- Analyze dependency relationships to identify feature boundaries

**Fallback behavior:**
If `/freya-devkit:code-graph` is not available, use simple git diff analysis (current behavior).
