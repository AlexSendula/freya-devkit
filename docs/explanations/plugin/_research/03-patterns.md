# Research Brief: Cross-Skill Patterns

**Topic:** The reusable patterns that recur across freya-devkit skills
**Primary source:** `docs/patterns.md`
**Verification sources:** `skills/code-graph/SKILL.md`, `skills/spec-manager/SKILL.md`, `skills/codebase-security-scan/SKILL.md`, `skills/wrap-up/SKILL.md`

---

## What this is

`docs/patterns.md` is a catalog of **11 reusable patterns** that appear across multiple skills in the freya-devkit plugin. It is explicitly framed as conventions rather than mandates. The opening line:

> "Reusable patterns that appear across multiple skills. These are conventions, not requirements - use them when they fit." (`docs/patterns.md:3`)

These patterns are the connective tissue of the plugin: they explain *how* the individual skills (code-graph, docs-manager, spec-manager, codebase-security-scan, wrap-up, etc.) cooperate, stay fast on large codebases, and remain usable in isolation. An engineer reading this brief should come away understanding the recurring design vocabulary the whole toolkit is built from.

## Why it exists

The plugin processes large codebases and generates artifacts (docs, specs, security reports, dependency graphs) that must stay in sync with code. Each pattern solves a recurring tension:

- Sequential processing is slow → **Coordinator + Parallel Workers**
- Artifacts referencing code need stable references → **Two-Commit Separation**
- Full re-scans are expensive → **Incremental Updates** / **Git-Aware State**
- AI output isn't always right → **Certainty Scoring**
- Security tools flag deliberate choices → **Intentional Design Tracking** / **Validation Against Specs**
- Skills may run without their optional dependencies → **Fallback Without Dependencies**

## The 11 patterns

Each entry in the source follows a consistent template: **Problem → Solution → (diagram/example) → Used by → When to use.**

### 1. Coordinator + Parallel Workers
- **Problem:** "Processing a large codebase is slow if done sequentially." (`patterns.md:7`)
- **Solution:** "One coordinator plans, multiple workers execute in parallel." (`patterns.md:9`)
- **Pipeline:** Coordinator analyzes structure & plans work → spawns N parallel workers partitioned by area (auth, api, data, features) → Aggregation combines results.
- **Used by:** docs-manager, spec-manager (scan mode), codebase-security-scan (`patterns.md:32`)
- **When to use:** "When work can be partitioned by area/category and combined at the end." (`patterns.md:34`)

### 2. Two-Commit Separation
- **Problem:** "Generated artifacts reference code commits. If artifacts are in the same commit, the reference is unstable." (`patterns.md:50`)
- **Solution:** Separate commits — Commit 1 = code (`src/...`, `tests/...`); Commit 2 = artifacts (`knowledge-base/reference/API.md`, `knowledge-base/specs/...`, `knowledge-base/security/...`, `knowledge-base/.graph/graph.json`).
- **Benefits (verbatim):** "Security scan has stable commit to reference / Git history is cleaner (code vs generated) / No tracking file hacks needed" (`patterns.md:68-70`)
- **Used by:** wrap-up (`patterns.md:72`)
- **When to use:** "When generating artifacts that reference or describe code changes." (`patterns.md:74`)

### 3. Incremental Updates
- **Problem:** "Full scans are expensive. Most changes affect only a small area." (`patterns.md:78`)
- **Solution:** "Track last processed state, only process changes since then." (`patterns.md:80`)
- **Pipeline (verbatim from `patterns.md:82-91`):**
  1. Read tracking file → get `last_commit: abc123`
  2. Run `git diff abc123..HEAD` → changed_files
  3. If code-graph available: `blast_radius = /freya-devkit:code-graph impact changed_files`; else `blast_radius = changed_files`
  4. Process only blast_radius files
  5. Update tracking file with current commit
- **Used by:** code-graph update, docs-manager update, spec-manager update, security-scan update (`patterns.md:93`)
- **Tracking files listed (`patterns.md:97-102`):**
  - `knowledge-base/specs/.spec-last-update`
  - `knowledge-base/security/.security-last-scan`
  - `knowledge-base/.graph/graph.json` (has commit field)

### 4. Certainty Scoring
- **Problem:** "AI-generated content isn't always correct. Users need to know confidence levels." (`patterns.md:106`)
- **Solution:** "Assign a certainty score (0-100) to AI-generated specs." (`patterns.md:108`)
- **Score bands (verbatim table, `patterns.md:110-115`):**
  | Score | Meaning | Action |
  |-------|---------|--------|
  | 90-100 | High confidence | Accept automatically |
  | 70-89 | Good confidence | Brief review |
  | 50-69 | Medium confidence | Ask user to confirm |
  | 0-49 | Low confidence | Needs detailed review |
- **Increases certainty:** code comments explain intent, matching docs exist, clear patterns in code, tests present (`patterns.md:117-121`)
- **Decreases certainty:** no comments, ambiguous code, multiple interpretations possible, no tests (`patterns.md:123-127`)
- **Used by:** spec-manager (`patterns.md:129`)

### 5. Intentional Design Tracking
- **Problem:** "Security scans flag things that are actually intentional design decisions." (`patterns.md:135`)
- **Solution:** "Specs include an 'intentional design decisions' section that security tools respect." (`patterns.md:137`)
- **Example spec YAML (`patterns.md:139-145`):**
  ```yaml
  intentional_decisions:
    - decision: "No password authentication fallback"
      rationale: "Would create phishing vector"
      security_note: "Ignore security tools flagging missing password auth"
  ```
- **Flow:** security scan finds issue → check specs for matching intentional design → if found, mark as INTENTIONAL DESIGN (not vulnerability) → include spec reference in report.
- **Used by:** spec-manager (stores), codebase-security-scan (reads) (`patterns.md:155`)

### 6. Fallback Without Dependencies
- **Problem:** "Skills might be used in isolation without their optional dependencies." (`patterns.md:161`)
- **Solution:** "Check if dependency exists, fall back gracefully if not." (`patterns.md:163`)
- **Pattern (verbatim `patterns.md:166-174`):** if `/freya-devkit:code-graph` available → `impact = /freya-devkit:code-graph impact <files>`, process impact files; else fallback to simple git diff, process only directly changed files, **warn user about reduced coverage**.
- **Used by:** "All skills that have optional dependencies." (`patterns.md:176`)

### 7. Phase-Based Execution
- **Problem:** "Complex workflows have multiple steps that should be clear to users." (`patterns.md:181`)
- **Solution:** "Break execution into named phases, report progress." (`patterns.md:183`)
- **Example output:** `[Phase 1: Change Detection]` → `[Phase 2: Impact Analysis]` → `[Phase 3: Update Specs]` → `[Phase 4: Review]` (`patterns.md:186-195`)
- **Used by:** "Most skills with multi-step workflows." (`patterns.md:197`)

### 8. Git-Aware State
- **Problem:** "Knowing 'what changed' requires remembering 'last state'." (`patterns.md:202`)
- **Solution:** "Store last-processed git commit in a tracking file." (`patterns.md:204`)
- **Example `.spec-last-update` (`patterns.md:207-213`):**
  ```yaml
  commit: abc123def456
  timestamp: 2024-03-27T10:30:00Z
  specs_updated: 5
  specs_created: 2
  ```
- **Next run:** `git diff abc123def456..HEAD --name-only` (`patterns.md:217`)
- **Used by:** spec-manager, security-scan (`patterns.md:221`)

### 9. Validation Against Specs
- **Problem:** "Security findings might be false positives if they're actually intentional design." (`patterns.md:226`)
- **Solution:** "Cross-reference findings against specs before finalizing report." (`patterns.md:228`)
- **Flow (`patterns.md:231-238`):** for each finding → identify affected feature → search specs for match → check if spec explicitly allows the "vulnerable" behavior → if yes mark INTENTIONAL DESIGN, else keep as potential vulnerability.
- **Used by:** codebase-security-scan `check-specs` command (`patterns.md:240`)

### 10. Worker Agent Specialization
- **Problem:** "Generic agents are less effective than specialized ones." (`patterns.md:245`)
- **Solution:** "Spawn specialized agents for specific task types." (`patterns.md:247`)
- **docs-manager workers:** PROJECT_OVERVIEW, ARCHITECTURE, DATABASE, API. **security-scan workers:** Authentication & Authorization, Input Validation & Injection, Secrets & Sensitive Data, API & Network Security (`patterns.md:250-263`)
- **Used by:** docs-manager, codebase-security-scan (`patterns.md:266`)

> Note: Patterns 1 (Coordinator + Parallel Workers) and 10 (Worker Agent Specialization) are closely related — #1 is the orchestration shape, #10 is the domain-specialization of the workers spawned.

## Verification against actual skills

I cross-checked the load-bearing claims against the real skill files (not just the pattern doc):

- **`/freya-devkit:code-graph impact <file>` CLI** — confirmed real. `skills/code-graph/SKILL.md:239` documents `### /freya-devkit:code-graph impact <file>`, and `:30` lists `impact <file>` = "Show blast radius if this file changes". The impact formula is `impact(file) = file + direct_dependents(file) + transitive_dependents(file)` (`code-graph/SKILL.md:107`).
- **Tracking file paths** — confirmed real:
  - `.spec-last-update` in `knowledge-base/specs/` (`spec-manager/SKILL.md:89,292,352`).
  - `.security-last-scan` in `knowledge-base/security/` (`codebase-security-scan/SKILL.md:175,226,1077,1079`).
  - Graph stored to `knowledge-base/.graph/graph.json` (`codebase-security-scan/SKILL.md:185`; graph file `graph.json` per `code-graph/SKILL.md:43`).
- **audit mode extends the pattern:** security-scan's `audit` writes `.security-last-scan` with `scan_type: audit`, "same shape as `update`" (`codebase-security-scan/SKILL.md:464`) — consistent with the Git-Aware State / Incremental Updates patterns.

## How it composes with other skills

The patterns document is the "why they fit together" layer beneath the tier stack described in the plugin README/CLAUDE.md:

```
code-graph (foundation)
    ↓ Fallback Without Dependencies + Incremental Updates use its `impact`
docs-manager, spec-manager (Coordinator+Workers, Certainty Scoring, Git-Aware State)
    ↓ Intentional Design Tracking (spec-manager stores → security reads)
codebase-security-scan (Validation Against Specs, Worker Specialization)
    ↓ Two-Commit Separation
wrap-up (orchestrates; owns the two-commit boundary)
```

- **code-graph** is the shared dependency other skills optionally call for blast radius; the Fallback pattern is what lets them run without it.
- **spec-manager ↔ codebase-security-scan** are coupled through Intentional Design Tracking / Validation Against Specs (producer/consumer of the `intentional_decisions` block).
- **wrap-up** is the single owner of Two-Commit Separation, committing code separately from generated artifacts.

## Inputs / Outputs / Artifacts referenced

- **Tracking files (state):** `knowledge-base/specs/.spec-last-update`, `knowledge-base/security/.security-last-scan`, `knowledge-base/.graph/graph.json`.
- **Generated artifacts (Two-Commit's Commit 2):** `knowledge-base/reference/*.md`, `knowledge-base/specs/**/SPEC-*.md`, `knowledge-base/security/**/*.md`, `knowledge-base/.graph/graph.json`.
- **CLI referenced:** `/freya-devkit:code-graph impact <files>`, `git diff <last_commit>..HEAD [--name-only]`.

## Degradation behavior

The Fallback Without Dependencies pattern *is* the degradation contract: when code-graph is unavailable, skills process only directly-changed files (git diff) instead of the full blast radius, and **warn the user about reduced coverage** (`patterns.md:173`). This trades completeness for the ability to run in isolation.

## Honest limits / gotchas

- **Conventions, not enforcement.** The doc itself states these are "conventions, not requirements" (`patterns.md:3`). There is no linter or runtime that enforces a skill uses any pattern; adherence is by author discipline.
- **Example commit hashes / timestamps are illustrative.** Values like `abc123`, `abc123def456`, and `2024-03-27T10:30:00Z` are placeholders in the doc, not real data.
- **The example paths in Two-Commit use `src/lib/auth.ts` / `src/api/routes.ts`** — generic illustration, not a required project layout.
- **UNVERIFIED — exact certainty-score computation:** patterns.md lists qualitative factors that raise/lower certainty but does not specify a numeric algorithm; whether spec-manager computes the 0-100 score deterministically or via LLM judgment is not stated here (would need to read spec-manager scripts to confirm).
- **UNVERIFIED — "Used by" completeness:** the "Used by" lines are the doc's own claims. I confirmed code-graph `impact`, the two tracking files, and the graph path against source, but did not exhaustively verify every skill listed under every pattern (e.g., that docs-manager literally uses Certainty Scoring nowhere is not asserted, only that spec-manager does).
- **`check-specs` command name:** patterns.md refers to a codebase-security-scan "check-specs command" (`patterns.md:240`); I did not verify the exact command spelling against the security-scan SKILL.md in this pass — treat the command token as UNVERIFIED.

## Quotable lines (verbatim, from `docs/patterns.md`)

- "Reusable patterns that appear across multiple skills. These are conventions, not requirements - use them when they fit." (`:3`)
- "One coordinator plans, multiple workers execute in parallel." (`:9`)
- "Generated artifacts reference code commits. If artifacts are in the same commit, the reference is unstable." (`:50`)
- "No tracking file hacks needed" (`:70`)
- "Full scans are expensive. Most changes affect only a small area." (`:78`)
- "Assign a certainty score (0-100) to AI-generated specs." (`:108`)
- "Specs include an 'intentional design decisions' section that security tools respect." (`:137`)
- "Check if dependency exists, fall back gracefully if not." (`:163`)
- "Generic agents are less effective than specialized ones." (`:245`)
