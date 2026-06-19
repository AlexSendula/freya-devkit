# Philosophy

The core beliefs and mental model behind this skills ecosystem.

## Why Skills Over Monolithic Prompts

Traditional AI assistance uses one big prompt with all instructions. This approach has problems:

- **Context bloat**: Everything loaded even when not needed
- **Hard to maintain**: One change affects everything
- **No modularity**: Can't mix and match capabilities

Skills solve this by being:

- **Focused**: Each skill does one thing well
- **Composable**: Skills can use other skills
- **Progressive**: Load what you need, when you need it

## The Mental Model

Think of skills as **specialized team members** working on a codebase:

```
┌─────────────────────────────────────────────────────────┐
│                     Your Codebase                        │
└─────────────────────────────────────────────────────────┘
                           │
       ┌───────────────────┼───────────────────┐
       │                   │                   │
       ▼                   ▼                   ▼
┌─────────────┐    ┌─────────────┐    ┌─────────────┐
│ code-graph  │    │ docs-manager│    │spec-manager │
│  "Analyst"  │    │ "Writer"    │    │ "Architect" │
└─────────────┘    └─────────────┘    └─────────────┘
       │                   │                   │
       └───────────────────┼───────────────────┘
                           │
                           ▼
                  ┌─────────────┐
                  │   wrap-up   │
                  │ "Integrator"│
                  └─────────────┘
```

Each skill has a role, knows its job, and can collaborate with others.

## Core Concepts

### 1. Intentional Design

Code isn't just "correct" or "incorrect" - some things are **intentional**.

```yaml
# A security scan might flag this as a vulnerability:
"Missing role check on DELETE - any user can delete"

# But the spec says:
decision: "Any authenticated user can CRUD posts"
rationale: "Collaborative tool with equal access"
```

Skills should understand that some "issues" are design decisions. The `spec-manager` captures these so `codebase-security-scan` doesn't flag them.

### 2. Certainty Scoring

When AI generates documentation or specs, it doesn't always know it's right.

| Score | Meaning | Action |
|-------|---------|--------|
| 90-100 | High confidence | Trust it |
| 70-89 | Good confidence | Quick review |
| 50-69 | Medium confidence | Ask user |
| 0-49 | Low confidence | Detailed review |

This acknowledges AI uncertainty rather than hiding it.

### 3. Impact Awareness

When code changes, what else is affected?

```
code-graph tracks:
  file A imports file B
  file B is imported by files C, D, E

If A changes → check B → check C, D, E
```

Skills use `code-graph` to understand blast radius. A documentation update isn't just about changed files - it's about affected files.

### 4. Incremental Over Full

Don't re-scan everything every time.

- **Full scan**: Initial setup, complete refresh
- **Incremental**: After code changes, only process what's different
- **Tracking files**: `.spec-last-update`, `.security-last-scan` remember state

This makes skills fast enough to run frequently.

### 5. Separation of Concerns

Code changes are different from generated artifacts.

```
Commit 1: Code changes
  - src/lib/auth.ts
  - src/api/routes.ts

Commit 2: Generated artifacts
  - docs/project/API.md
  - docs/specs/auth/SPEC-001.md
  - docs/security-reports/...
```

The two-commit pattern keeps git history clean and lets tools reference stable commits.

## What This Enables

### For Development

1. Implement a feature
2. Run `/freya-devkit:wrap-up`
3. Get: updated docs, specs, security scan, all committed

### For Understanding

1. New AI session starts
2. Reads `docs/project/` for context
3. Reads `docs/specs/` for intentional design decisions
4. Has full understanding without being told everything

### For Maintenance

1. Security scan finds potential issues
2. Cross-references specs for intentional design
3. Reports only real vulnerabilities
4. Tracks finding lifecycle across scans

## What This Doesn't Mean

- **Not prescriptive**: Skills don't have to follow every pattern
- **Not complete**: The ecosystem grows over time
- **Not perfect**: Certainty scores acknowledge uncertainty
- **Not enforced**: Conventions guide, they don't restrict

The goal is coherence and collaboration, not rigid compliance.
