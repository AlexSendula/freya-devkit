# Skill Reference

Quick reference for all ten skills, grouped by the five tiers of the ecosystem.

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

**Output**: `knowledge-base/.graph/graph.json`

**Used by**: docs-manager, spec-manager, behavior-graph, behavior-runner, codebase-security-scan

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

**Output**: `knowledge-base/reference/*.md`

**Uses**: code-graph (optional, for impact-aware updates)

---

### spec-manager

**Purpose**: Create and manage feature specifications with certainty scoring.

**Triggers**: "specs", "specifications", "design decisions", "why was this done", "that's intentional"

**Commands**:
| Command | Description |
|---------|-------------|
| `init` | Initialize specs structure |
| `bootstrap` | Unified onboarding: detect shape → init + code-graph + (brownfield) scan + behavior-graph |
| `create <name>` | Create new spec interactively |
| `scan` | Full codebase scan, generate specs |
| `update` | Git-aware incremental sync |
| `update <spec>` | Update specific spec |
| `verify` | Check specs match current code |
| `intent new <BEH...>` | Create an INTENT-NNN record authorizing a change to an accepted behavior's test |
| `adr create/list/verify` | Cross-cutting Architecture Decision Records |
| `principles` | Print the project's principles (constitution; the G2 checkpoint) |
| `drift gaps` | Declared items with no `related_code` (on-demand drift audit) |
| `search <query>` | Full-text search |
| `by-tag <tag>` | Filter specs by tag |
| `review` | Review low-certainty specs |
| `get <id>` | Load spec by ID |
| `index` | Rebuild search index |

**Output**: `knowledge-base/specs/` with category subdirectories

**Uses**: code-graph (optional, for impact-aware updates)

---

### behavior-graph

**Purpose**: Own the behavior graph (`behavior.json`, sibling of `graph.json`) — intended behavior as first-class BEHAVIOR → TEST → CODE records — and answer blast radius in both directions.

**Triggers**: "behaviors", "affected behaviors", "what implements this", "behavior coverage"

**Commands** (exactly one mode per run):
| Command | Description |
|---------|-------------|
| `--build` | Build/refresh `behavior.json` |
| `--affected <files>` | Direction A: accepted/confirmed behaviors a code change touches |
| `--implements <BEH>` | Direction B: code a behavior exercises |
| `--check --base <commit>` | Regression gate: re-run affected accepted behaviors (wrap-up Phase 3.5) |
| `--surface --base <commit>` | Validate-on-hit: surface touched proposed/confirmed behaviors (advisory) |
| `--gaps` | Whole-repo uncovered-code audit |
| `--covering <file>` | Accepted behaviors whose exercised code includes a file |

**Output**: `knowledge-base/.graph/behavior.json`

**Uses**: code-graph (impact), behavior-runner (coverage fingerprints)

---

### behavior-runner

**Purpose**: Run a project's accepted behaviors via their test adapter and capture observed TEST → CODE coverage fingerprints. A producer — it prints fingerprints, never writes `behavior.json`.

**Triggers**: "run behaviors", "behavior coverage", "refresh fingerprints"

**Commands**:
| Command | Description |
|---------|-------------|
| `run` (default) | Emit fingerprints for accepted behaviors (`--level unit --emit-fingerprints`) |
| `--list` | List matching accepted behaviors without running them |

**Note**: Only the `vitest` unit path is implemented; other adapters emit `coverage: "unknown"` (`reason: level-deferred`).

**Uses**: code-graph (static closure for an integration `entry`)

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
| `audit` | Exhaustive discovery + adversarial verification (Workflow-powered); on-demand / pre-release, not part of wrap-up |

**Output**: `knowledge-base/security/codebase-security/YYYY-MM-DD.md`

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
5. Behavior integrity & accepted-behavior run (Phase 3.5) — deterministic link/ADR/declared-intent gates + `behavior-graph --check`, then the G2/G3/P4b resolve-to-proceed checkpoints
6. `/freya-devkit:codebase-security-scan update`
7. Commit artifacts

**Uses**: All core skills (orchestrates them)

---

### status

**Purpose**: Read-only counterpart of wrap-up — a census of outstanding intent, tests owed, coverage gaps, and open findings. Mutates nothing except (on request) the generated `BACKLOG.md`.

**Triggers**: "status", "what's outstanding", "backlog", "coverage gaps"

**Commands**:
| Command | Description |
|---------|-------------|
| `status` | Print the status summary and refresh `BACKLOG.md` |
| `gaps` | List whole-repo uncovered source files |
| `review intent` | Work the proposed → confirm worklist, one at a time |
| `review tests` | Work the confirmed → write-a-test worklist, one at a time |

**Output**: `knowledge-base/BACKLOG.md`

**Uses**: behavior-graph, spec-manager, security-scan (all read-only)

---

## Skill Relationships

```
Tier 1  code-graph  (foundation: graph.json, blast radius)
             │
Tier 2  docs-manager · spec-manager · behavior-graph → behavior-runner
             │   (behavior-graph owns behavior.json, a sibling of graph.json)
             ▼
Tier 3  codebase-security-scan · dependency-vulnerability-check
             │
             ▼
Tier 4  wrap-up  (orchestrates T1 → T2 → behavior integrity 3.5 → T3, two commits)  ·  status (read-only)
             │
             ▼
Tier 5  codebase-security-resolver
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
| See which behaviors a change affects | `/freya-devkit:behavior-graph --affected <file>` |
| Finish implementing a feature | `/freya-devkit:wrap-up` |
| Check what intent / tests / findings are outstanding | `/freya-devkit:status` |

## File Locations

| Type | Location |
|------|----------|
| Dependency graph | `knowledge-base/.graph/graph.json` |
| Behavior graph | `knowledge-base/.graph/behavior.json` |
| Project docs | `knowledge-base/reference/*.md` |
| Feature specs | `knowledge-base/specs/<category>/SPEC-*.md` |
| ADRs (decisions) | `knowledge-base/decisions/ADR-*.md` |
| Declared intents | `knowledge-base/intents/INTENT-*.md` |
| Principles (constitution) | `knowledge-base/principles.md` |
| Backlog (generated) | `knowledge-base/BACKLOG.md` |
| Security reports | `knowledge-base/security/codebase-security/YYYY-MM-DD.md` |
| Spec tracking | `knowledge-base/specs/.spec-last-update` |
| Security tracking | `knowledge-base/security/.security-last-scan` |
