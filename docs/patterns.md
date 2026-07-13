# Patterns

Reusable patterns that appear across multiple skills. These are conventions, not requirements - use them when they fit.

## Pattern: Coordinator + Parallel Workers

**Problem**: Processing a large codebase is slow if done sequentially.

**Solution**: One coordinator plans, multiple workers execute in parallel.

```
┌─────────────┐
│ Coordinator │  ← Analyzes structure, plans work
└─────────────┘
       │
       │ spawns
       ▼
┌──────────────────────────────────────────────┐
│              Parallel Workers                 │
├──────────┬──────────┬──────────┬─────────────┤
│ Worker 1 │ Worker 2 │ Worker 3 │ Worker N    │
│ (auth)   │ (api)    │ (data)   │ (features)  │
└──────────┴──────────┴──────────┴─────────────┘
       │
       │ results
       ▼
┌─────────────┐
│ Aggregation │  ← Combine results
└─────────────┘
```

**Used by**: docs-manager, spec-manager (scan mode), codebase-security-scan

**When to use**: When work can be partitioned by area/category and combined at the end.

**Example from docs-manager**:
```
Coordinator: Detect project type, ask user about business context
    ↓
Worker 1: Generate ARCHITECTURE.md
Worker 2: Generate API.md
Worker 3: Generate DATABASE.md
... (parallel)
    ↓
Combine: Create README.md index
```

## Pattern: Two-Commit Separation

**Problem**: Generated artifacts reference code commits. If artifacts are in the same commit, the reference is unstable.

**Solution**: Separate commits for code and artifacts.

```
Commit 1 (code):
  - src/lib/auth.ts
  - src/api/routes.ts
  - tests/auth.test.ts

Commit 2 (artifacts):
  - knowledge-base/reference/API.md
  - knowledge-base/specs/auth/SPEC-001.md
  - knowledge-base/security/.../2024-03-27.md
  - knowledge-base/.graph/graph.json
```

**Benefits**:
- Security scan has stable commit to reference
- Git history is cleaner (code vs generated)
- No tracking file hacks needed

**Used by**: wrap-up

**Behavior-aware refinement**: a behavior's commit class follows its **lifecycle `state`, not its file location**. A `.feature` scaffold lives under the code tree, but until it is `accepted` and authored (its `TODO(scaffold)` marker gone) it is *intent under review* → it rides the **artifacts** commit (commit 2). Once `accepted`, its test joins the **code** commit (commit 1). `wrap-up` stages accordingly — a `proposed` scaffold is a draft proposal, not a verified guarantee.

**When to use**: When generating artifacts that reference or describe code changes.

## Pattern: Incremental Updates

**Problem**: Full scans are expensive. Most changes affect only a small area.

**Solution**: Track last processed state, only process changes since then.

```
1. Read tracking file → get last_commit: abc123
2. Run git diff abc123..HEAD → changed_files
3. If code-graph available:
     blast_radius = /freya-devkit:code-graph impact changed_files
   else:
     blast_radius = changed_files
4. Process only blast_radius files
5. Update tracking file with current commit
```

**Used by**: code-graph update, docs-manager update, spec-manager update, security-scan update

**When to use**: When processing is expensive and changes are typically localized.

**Tracking files**:
```
knowledge-base/specs/.spec-last-update
knowledge-base/security/.security-last-scan
knowledge-base/.graph/graph.json (has commit field)
```

## Pattern: Certainty Scoring

**Problem**: AI-generated content isn't always correct. Users need to know confidence levels.

**Solution**: Assign a certainty score (0-100) to AI-generated specs.

| Score | Meaning | Action |
|-------|---------|--------|
| 90-100 | High confidence | Accept automatically |
| 70-89 | Good confidence | Brief review |
| 50-69 | Medium confidence | Ask user to confirm |
| 0-49 | Low confidence | Needs detailed review |

**Factors that increase certainty**:
- Code comments explain intent
- Matching documentation exists
- Clear patterns in code
- Tests present

**Factors that decrease certainty**:
- No comments
- Ambiguous code
- Multiple interpretations possible
- No tests

**Used by**: spec-manager

**When to use**: When generating content that may need human verification.

## Pattern: Intentional Design Tracking

**Problem**: Security scans flag things that are actually intentional design decisions.

**Solution**: Specs include an "intentional design decisions" section that security tools respect.

```yaml
# In a spec
intentional_decisions:
  - decision: "No password authentication fallback"
    rationale: "Would create phishing vector"
    security_note: "Ignore security tools flagging missing password auth"
```

**Flow**:
```
1. Security scan finds potential issue
2. Check specs for intentional design matching this issue
3. If found → mark as INTENTIONAL DESIGN, not vulnerability
4. Include spec reference in report
```

**Used by**: spec-manager (stores), codebase-security-scan (reads)

**When to use**: When documenting features that might look like bugs/security issues.

## Pattern: Fallback Without Dependencies

**Problem**: Skills might be used in isolation without their optional dependencies.

**Solution**: Check if dependency exists, fall back gracefully if not.

```yaml
# In SKILL.md
if /freya-devkit:code-graph skill available:
    impact = /freya-devkit:code-graph impact <files>
    process impact files
else:
    # Fallback: simple git diff
    process only directly changed files
    warn user about reduced coverage
```

**Used by**: All skills that have optional dependencies

**When to use**: Whenever a skill can benefit from another skill but doesn't strictly require it.

## Pattern: Phase-Based Execution

**Problem**: Complex workflows have multiple steps that should be clear to users.

**Solution**: Break execution into named phases, report progress.

```
[Phase 1: Change Detection]
  - Found 5 changed files
[Phase 2: Impact Analysis]
  - Blast radius: 12 files
[Phase 3: Update Specs]
  - Updated 3 specs
[Phase 4: Review]
  - 2 specs need attention
```

**Used by**: Most skills with multi-step workflows

**When to use**: When workflow has distinct stages and user benefit from visibility.

## Pattern: Git-Aware State

**Problem**: Knowing "what changed" requires remembering "last state".

**Solution**: Store last-processed git commit in a tracking file.

```yaml
# .spec-last-update
commit: abc123def456
timestamp: 2024-03-27T10:30:00Z
specs_updated: 5
specs_created: 2
```

Next run:
```bash
git diff abc123def456..HEAD --name-only
# → files changed since last update
```

**Used by**: spec-manager, security-scan

**When to use**: When you need to know what changed since last run.

## Pattern: Validation Against Specs

**Problem**: Security findings might be false positives if they're actually intentional design.

**Solution**: Cross-reference findings against specs before finalizing report.

```
For each security finding:
  1. Identify affected feature/component
  2. Search specs for matching feature
  3. Check if spec explicitly allows the "vulnerable" behavior
  4. If yes → mark as INTENTIONAL DESIGN
  5. If no → keep as potential vulnerability
```

**Used by**: codebase-security-scan check-specs command

**When to use**: When generating findings that might conflict with intentional design.

## Pattern: Worker Agent Specialization

**Problem**: Generic agents are less effective than specialized ones.

**Solution**: Spawn specialized agents for specific task types.

```
# docs-manager workers:
Worker 1: PROJECT_OVERVIEW (business context)
Worker 2: ARCHITECTURE (system design)
Worker 3: DATABASE (schema, models)
Worker 4: API (endpoints, formats)
...

# security-scan workers:
Worker 1: Authentication & Authorization
Worker 2: Input Validation & Injection
Worker 3: Secrets & Sensitive Data
Worker 4: API & Network Security
...
```

**Used by**: docs-manager, codebase-security-scan

**When to use**: When work can be partitioned by domain expertise.

## Pattern: Resolution Logs (resolve-to-proceed governance)

**Problem**: Some governance checks are model *judgment*, not deterministic *facts*. They shouldn't hard-block on confidence alone, but "ignore and push" must not be a silent escape hatch — and the same finding shouldn't re-prompt every run once a human has resolved it.

**Solution**: Append-only JSONL **resolution logs**. Each governance gate triages a finding against prior resolutions and records a verdict, so a resolved finding stays resolved until its inputs change.

```
knowledge-base/principle-resolutions.jsonl      ← G2 (principles.py)
knowledge-base/contradiction-resolutions.jsonl  ← G3 (contradictions.py)
knowledge-base/drift-resolutions.jsonl          ← P4b (drift.py)
```

One shared core (`resolution_log.py`) provides `append` / `load` / `active`, keyed by a caller-supplied tuple; verdicts include *refuted*, *amended*, *superseded*. A straight code fix is **not** logged — git already records it.

**Used by**: spec-manager governance gates (G2/G3/P4b), driven from wrap-up Phase 3.5

**When to use**: For checks that need human judgment to clear, where you want an auditable, non-repeating record instead of a hard block.
