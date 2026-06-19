# Architecture

How skills connect, share data, and work together.

## Skill Dependency Graph

```
                    ┌─────────────────────────────────────┐
                    │            wrap-up                  │
                    │   (orchestrates post-implementation) │
                    └─────────────────────────────────────┘
                                    │
            ┌───────────────────────┼───────────────────────┐
            │                       │                       │
            ▼                       ▼                       ▼
    ┌───────────────┐     ┌───────────────┐     ┌───────────────────┐
    │  code-graph   │     │ docs-manager  │     │codebase-security- │
    │               │     │               │     │      scan         │
    └───────────────┘     └───────────────┘     └───────────────────┘
            │                       │                       │
            │                       │                       │
            └───────────────────────┼───────────────────────┘
                                    │
                                    ▼
                          ┌───────────────┐
                          │ spec-manager  │
                          └───────────────┘
                                    │
                                    ▼
                          ┌───────────────┐
                          │ code-graph    │
                          │ (foundation)  │
                          └───────────────┘
```

## Skill Tiers

### Tier 1: Foundation

| Skill | Purpose | Used By |
|-------|---------|---------|
| `code-graph` | Dependency graph, impact analysis | All other skills |

This is the foundation. It knows what files depend on what, enabling impact-aware operations.

### Tier 2: Consumers

| Skill | Purpose | Dependencies |
|-------|---------|--------------|
| `docs-manager` | Project documentation | code-graph (optional) |
| `spec-manager` | Feature specifications | code-graph (optional) |

These skills maintain structured information about the codebase. They use `code-graph` when available for smarter updates.

### Tier 3: Analysis

| Skill | Purpose | Dependencies |
|-------|---------|--------------|
| `codebase-security-scan` | Security auditing | code-graph, spec-manager |
| `dependency-vulnerability-check` | Supply chain security | None |

Security analysis benefits from both impact awareness (code-graph) and understanding intentional design (spec-manager).

### Tier 4: Orchestration

| Skill | Purpose | Dependencies |
|-------|---------|--------------|
| `wrap-up` | Post-implementation workflow | All above |

The orchestrator that runs everything in sequence after implementation.

### Tier 5: Resolution

| Skill | Purpose | Dependencies |
|-------|---------|--------------|
| `codebase-security-resolver` | Fix security issues | security-scan |

Handles the output of security scanning.

## Data Flow

### Input Sources

```
Codebase Files
      │
      ├── src/**/*.ts ─────────────────────────────────────┐
      ├── src/**/*.py                                       │
      └── ...                                               │
                                                            ▼
                                          ┌─────────────────────────────┐
                                          │        code-graph           │
                                          │   builds dependency graph   │
                                          └─────────────────────────────┘
                                                        │
                                                        ▼
                                          docs/.code-graph/graph.json
```

### Output Artifacts

```
┌─────────────────────────────────────────────────────────────┐
│                        docs/                                 │
├─────────────────────────────────────────────────────────────┤
│ ├── project/              ← docs-manager                     │
│ │   ├── ARCHITECTURE.md                                     │
│ │   ├── API.md                                              │
│ │   └── ...                                                 │
│ ├── specs/                ← spec-manager                     │
│ │   ├── features/                                           │
│ │   ├── auth/                                               │
│ │   └── .spec-last-update                                   │
│ ├── security-reports/     ← security-scan                    │
│ │   ├── codebase-security/                                  │
│ │   │   └── 2024-01-15.md                                   │
│ │   └── .security-last-scan                                 │
│ └── .code-graph/          ← code-graph                       │
│     ├── graph.json                                          │
│     └── classifications.json                                │
└─────────────────────────────────────────────────────────────┘
```

### Integration Data Flow

```
1. Code changes committed
         │
         ▼
2. code-graph update
   - Reads git diff
   - Updates graph.json
   - Provides impact analysis
         │
         ▼
3. docs-manager update
   - Asks code-graph for blast radius
   - Updates affected docs
         │
         ▼
4. spec-manager update
   - Asks code-graph for blast radius
   - Updates affected specs
   - Adjusts certainty scores
         │
         ▼
5. security-scan update
   - Asks code-graph for blast radius
   - Asks spec-manager for intentional design
   - Generates findings with context
```

## Tracking Files

Skills use tracking files to enable incremental updates:

| File | Owner | Purpose |
|------|-------|---------|
| `.spec-last-update` | spec-manager | Last commit scanned for specs |
| `.security-last-scan` | security-scan | Last commit scanned for security |
| `graph.json` → `commit` field | code-graph | Commit graph was built from |

These enable "only process what changed" behavior.

## Fallback Behavior

Skills gracefully degrade when dependencies are missing:

```yaml
# Example from docs-manager
if code-graph available:
    blast_radius = /freya-devkit:code-graph impact <changed-files>
    update docs for affected files
else:
    # Fallback to simple git diff
    update docs for directly changed files
```

This means skills work standalone but work better together.

## Directory Structure

```
.claude/
├── skills/
│   ├── code-graph/
│   │   ├── SKILL.md
│   │   ├── scripts/
│   │   │   └── graph_ops.py
│   │   └── references/
│   │       └── graph-schema.md
│   ├── docs-manager/
│   │   ├── SKILL.md
│   │   ├── scripts/
│   │   │   └── detect_project.py
│   │   └── references/
│   │       └── templates.md
│   ├── spec-manager/
│   │   ├── SKILL.md
│   │   ├── scripts/
│   │   │   └── search_specs.py
│   │   ├── references/
│   │   │   ├── spec-template.md
│   │   │   └── categories.md
│   │   └── evals/
│   │       └── evals.json
│   ├── codebase-security-scan/
│   │   └── SKILL.md
│   ├── codebase-security-resolver/
│   │   └── SKILL.md
│   ├── wrap-up/
│   │   └── SKILL.md
│   └── dependency-vulnerability-check/
│       └── SKILL.md
```

Each skill follows a similar structure but adapts to its needs.
