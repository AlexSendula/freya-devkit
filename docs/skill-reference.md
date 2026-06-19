# Skill Reference

Quick reference for all skills in the ecosystem.

> **Invocation & namespacing.** These skills ship as the `freya-devkit` plugin, so they are invoked with the plugin namespace: `/freya-devkit:<skill> [args]` (e.g. `/freya-devkit:code-graph build`). The bare `/code-graph` form only works for skills installed loose in `~/.claude/skills/`, not for plugin-installed skills.

## Core Skills

### code-graph

**Purpose**: Build and query code dependency graphs for impact analysis.

**Triggers**: "dependencies", "impact analysis", "blast radius", "what depends on", "affected files"

**Commands**:
| Command | Description |
|---------|-------------|
| `build` | Full scan, build graph from codebase |
| `update` | Incremental update via git diff |
| `query <file>` | Show dependencies + usages |
| `impact <file>` | Show blast radius |
| `dependents <file>` | Files that depend on this |
| `dependencies <file>` | Files this depends on |

**Output**: `docs/.code-graph/graph.json`

**Used by**: docs-manager, spec-manager, codebase-security-scan

---

### docs-manager

**Purpose**: Create and maintain standardized project documentation.

**Triggers**: "docs", "documentation", "create docs", "update docs", "architecture doc"

**Commands**:
| Command | Description |
|---------|-------------|
| `init` | Create initial docs structure |
| `update` | Update docs to reflect code changes |
| `update <doc>` | Update specific doc file |
| `review` | Check docs for consistency |
| `sync` | Full re-analysis |
| `resolve` | Fill in placeholders |
| `upgrade-diagrams` | Convert ASCII to mermaid |

**Output**: `docs/project/*.md`

**Uses**: code-graph (optional, for impact-aware updates)

---

### spec-manager

**Purpose**: Create and manage feature specifications with certainty scoring.

**Triggers**: "specs", "specifications", "design decisions", "why was this done", "that's intentional"

**Commands**:
| Command | Description |
|---------|-------------|
| `init` | Initialize specs structure |
| `create <name>` | Create new spec interactively |
| `scan` | Full codebase scan, generate specs |
| `update` | Git-aware incremental sync |
| `update <spec>` | Update specific spec |
| `verify` | Check specs match current code |
| `search <query>` | Full-text search |
| `review` | Review low-certainty specs |
| `get <id>` | Load spec by ID |

**Output**: `docs/specs/` with category subdirectories

**Uses**: code-graph (optional, for impact-aware updates)

---

### codebase-security-scan

**Purpose**: Comprehensive security audit using parallel subagents.

**Triggers**: "scan codebase for security", "security audit", "code security check"

**Commands**:
| Command | Description |
|---------|-------------|
| `scan` | Full codebase scan |
| `update` | Incremental scan (changed files only) |
| `impact <file>` | Security implications for a file |
| `check-specs` | Cross-reference findings against specs |

**Output**: `docs/security-reports/codebase-security/YYYY-MM-DD.md`

**Uses**: code-graph (impact analysis), spec-manager (intentional design)

---

### codebase-security-resolver

**Purpose**: Fix security issues found by codebase-security-scan.

**Triggers**: "fix security issues", "resolve security findings", "remediate vulnerabilities"

**Workflow**: Reads security report, proposes fixes, applies with user approval.

**Uses**: codebase-security-scan (reads reports)

---

### dependency-vulnerability-check

**Purpose**: Check for known vulnerabilities in project dependencies.

**Triggers**: "check dependencies", "vulnerability check", "supply chain security"

**Scope**: package.json, requirements.txt, go.mod dependencies

---

### wrap-up

**Purpose**: Complete post-implementation workflow in sequence.

**Triggers**: "wrap up", "complete feature", "finish up", "done implementing"

**Workflow**:
1. Commit code changes (if any)
2. `/freya-devkit:code-graph update`
3. `/freya-devkit:docs-manager update`
4. `/freya-devkit:spec-manager update`
5. `/freya-devkit:codebase-security-scan update`
6. Commit artifacts

**Uses**: All core skills (orchestrates them)

---

## Skill Relationships

```
                    wrap-up
                       │
       ┌───────────────┼───────────────┐
       │               │               │
       ▼               ▼               ▼
 code-graph    docs-manager    spec-manager
       │               │               │
       └───────────────┴───────────────┘
                       │
                       ▼
            codebase-security-scan
                       │
                       ▼
            codebase-security-resolver
```

## Quick Decision Guide

| I want to... | Use this skill |
|--------------|----------------|
| Understand code dependencies | `/freya-devkit:code-graph query <file>` |
| See what's affected by a change | `/freya-devkit:code-graph impact <file>` |
| Set up project docs | `/freya-devkit:docs-manager init` |
| Update docs after changes | `/freya-devkit:docs-manager update` |
| Create a feature spec | `/freya-devkit:spec-manager create <name>` |
| Generate specs from code | `/freya-devkit:spec-manager scan` |
| Check for security issues | `/freya-devkit:codebase-security-scan scan` |
| Fix security issues | `/freya-devkit:codebase-security-resolver` |
| Check dependencies for vulnerabilities | `/freya-devkit:dependency-vulnerability-check` |
| Finish implementing a feature | `/freya-devkit:wrap-up` |

## File Locations

| Type | Location |
|------|----------|
| Dependency graph | `docs/.code-graph/graph.json` |
| Project docs | `docs/project/*.md` |
| Feature specs | `docs/specs/<category>/SPEC-*.md` |
| Security reports | `docs/security-reports/codebase-security/YYYY-MM-DD.md` |
| Spec tracking | `docs/specs/.spec-last-update` |
| Security tracking | `docs/security-reports/.security-last-scan` |
