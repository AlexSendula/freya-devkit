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
| `init` | Initialize `/docs/specs/` structure |
| `create <name>` | Create new spec interactively |
| `scan` | Full codebase scan, generate specs with certainty scores |
| `update` | Git-aware incremental sync (no args = smart sync) |
| `update <spec>` | Re-analyze and update specific spec |
| `verify` | Check if all specs match current code |
| `search <query>` | Full-text search across specs |
| `by-tag <tag>` | Filter specs by tag |
| `get <id...>` | Load full spec(s) by ID |
| `review` | Interactive review of low-certainty specs |
| `index` | Rebuild search index |
| `help` | Display help and usage information |

## How It Works

### Spec Structure

Specs live in `/docs/specs/` organized by category:

```
docs/specs/
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

### Incremental Update Tracking

The `.spec-last-update` file in `docs/specs/` tracks the last sync state:

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

**Increases certainty:** code comments, matching docs in `/docs/project/`, clear patterns, tests
**Decreases certainty:** no comments, ambiguous code, multiple interpretations, missing tests

---

## Commands

### `/freya-devkit:spec-manager init`

Initialize the specs directory structure:

1. Create `/docs/specs/` if it doesn't exist
2. Create category subdirectories: `auth/`, `api/`, `data/`, `features/`, `infra/`, `integration/`, `ui/`
3. Create `README.md` with index template and search instructions
4. Report what was created

### `/freya-devkit:spec-manager create <name>`

Interactively create a new spec:

1. Ask clarifying questions:
   - What feature is this for?
   - What should it do?
   - Why is this needed?
   - Any intentional design decisions?
   - Category and tags?

2. Generate spec ID (next sequential number)
3. Create spec file using template from `references/spec-template.md`
4. Set certainty to 100 (user-created)
5. Update README index

### `/freya-devkit:spec-manager scan`

**The big one** - scan codebase to generate specs with certainty metrics.

**Phase 1: Coordinator Discovery**

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

**Phase 3: Certainty Evaluation**

For each generated spec:
1. Cross-reference with `/docs/project/` documentation
2. Check code comments for intent
3. Validate "what" matches code behavior
4. Adjust certainty score

**Phase 4: Interactive Clarification**

Present user with:
1. Summary of all generated specs
2. Specs grouped by certainty level
3. For low-certainty specs (<70%), ask clarifying questions

**Phase 5: Generate Index**

Update `docs/specs/README.md` with all specs.

### `/freya-devkit:spec-manager update` (no arguments)

**The smart sync command** - git-aware incremental spec updates.

> 💡 **Best Practice**: Use `update` (no args) for day-to-day syncing after code changes. Use `scan` only for initial setup or complete refresh.

**Phase 1: Change Detection**

1. Read `.spec-last-update` file from `docs/specs/` for last commit hash
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

1. Cross-reference updated specs with `/docs/project/` docs for consistency
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
2. Write to `docs/specs/.spec-last-update`:
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

### `/freya-devkit:spec-manager verify`

Check if all specs are still accurate:

1. Load each spec
2. Read its `related_code` paths
3. Analyze if code matches spec
4. Report discrepancies with recommendations
5. Flag specs with stale certainty (haven't been verified recently)

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
      - Check comments, tests, and `/docs/project/` for evidence
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

1. Scan all specs in `/docs/specs/`
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
| init    | Initialize /docs/specs/ structure |
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
---
```

Key sections:
- **What**: What the feature does (specific, measurable)
- **Why**: Why it's needed, what problem it solves
- **Acceptance Criteria**: Checklist of requirements
- **Intentional Design Decisions**: Design choices with rationale
- **Related Specs**: Links to related specifications
- **Change History**: Log of changes and reasons

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
