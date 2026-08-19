# Skill Reference

Quick reference for all ten skills, grouped by the five tiers of the ecosystem.

> **Invocation & namespacing.** Skill names are `freya-<skill>` (e.g. `freya-code-graph`). Installed portably via `install.sh` (any agent), a skill is named `freya-<skill>` and how you invoke it is the host's business — name it in the request ("run the freya-code-graph skill and build the graph"), or use whatever invocation syntax your agent offers. There is no cross-agent slash form. Installed via the Claude marketplace plugin, Claude namespaces it: `/freya-devkit:freya-<skill> [args]` (e.g. `/freya-devkit:freya-code-graph build`). See the [README](../README.md#installation) for both install paths.

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

**Purpose**: Comprehensive security audit, scanning each category as an independent task (run in parallel where the agent supports it).

**Triggers**: "scan codebase for security", "security audit", "code security check"

**Commands**:
| Command | Description |
|---------|-------------|
| `scan` | Full codebase scan, run by the `freya security scan` driver (one discovery round, three verification lenses). **Paid** — drives a real agent CLI. |
| `update` | Incremental scan (changed files only); stays in the main loop, since the driver cannot express a git-diff scope. Free, and what `wrap-up` runs. Its first run on a repo with no tracker does a full **in-loop** pass rather than falling into the paid driver. |
| `impact <file>` | Security implications for a file |
| `check-specs` | Cross-reference findings against specs |
| `audit` | Same driver, exhaustive discovery (`freya security audit`); on-demand / pre-release, **not** part of wrap-up |

`scan` and `audit` are two presets of one driver — it owns the fan-out over the six
categories rather than asking the agent to schedule it. `--agent` picks the worker CLI
and `--model` names a model **of that CLI**; pass both or neither. `--max-calls` is the
cost ceiling, `--concurrency` the pool width, `--dry-run` prints the cost plan and spends
nothing, and `--yes` answers the spend confirmation up front — without it a run with no
tty declines rather than blocking.

Its exit code is the first thing to read, and only one value means "fall back":

| Exit | Meaning |
|---|---|
| `0` | Complete — the JSON array on stdout is the whole result |
| `1` | **No agent CLI on PATH, and nothing else** — the only case where the skill runs the scan in its own loop instead |
| `2` | Failed — bad project path, no usable answers, or a ceiling too low to verify one finding |
| `3` | Incomplete — the ceiling stopped it early, tasks went unanswered, or discovery was truncated. Report the findings, never call the run clean |
| `4` | Declined — confirmation refused, or non-interactive without `--yes`. Nothing ran, nothing was spent; re-run with `--yes` |

An empty array with exit `0` means clean. An empty array with any other code means the
scan did not run.

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
2. `freya-code-graph update`
3. `freya-docs-manager update`
4. `freya-spec-manager update`
5. Behavior integrity & accepted-behavior run (Phase 3.5) — deterministic link/ADR/declared-intent gates + `behavior-graph --check`, then the G2/G3/P4b resolve-to-proceed checkpoints
6. `freya-codebase-security-scan update`
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
| Understand code dependencies | `freya-code-graph query <file>` |
| See what's affected by a change | `freya-code-graph impact <file>` |
| Set up project docs | `freya-docs-manager init` |
| Update docs after changes | `freya-docs-manager update` |
| Create a feature spec | `freya-spec-manager create <name>` |
| Generate specs from code | `freya-spec-manager scan` |
| Check for security issues | `freya-codebase-security-scan scan` |
| Fix security issues | `freya-codebase-security-resolver` |
| Check dependencies for vulnerabilities | `freya-dependency-vulnerability-check` |
| See which behaviors a change affects | `freya-behavior-graph --affected <file>` |
| Finish implementing a feature | `freya-wrap-up` |
| Check what intent / tests / findings are outstanding | `freya-status` |
| Refresh the toolkit itself | `freya update` |
| Preview an update without applying it | `freya update --dry-run` |
| Pick the update up in a session already open | Claude Code `/reload-skills`, Copilot `/skills` |
| Introduce the toolkit in a project's AGENTS.md | `freya init` |
| Check the installation is healthy | `freya doctor` |

## File Locations

Everything under `knowledge-base/` is committed except `.graph/`, which ignores itself.

| Type | Location | In git? |
|------|----------|---------|
| Dependency graph | `knowledge-base/.graph/graph.json` | ignored |
| Graph classifications | `knowledge-base/.graph/classifications.json` | ignored |
| Behavior graph | `knowledge-base/.graph/behavior.json` | ignored ⚠ |
| Project docs | `knowledge-base/reference/*.md` | tracked |
| Feature specs | `knowledge-base/specs/<category>/SPEC-*.md` | tracked |
| ADRs (decisions) | `knowledge-base/decisions/ADR-*.md` | tracked |
| Declared intents | `knowledge-base/intents/INTENT-*.md` | tracked |
| Principles (constitution) | `knowledge-base/principles.md` | tracked |
| Backlog (generated) | `knowledge-base/BACKLOG.md` | tracked |
| Security reports | `knowledge-base/security/codebase-security/YYYY-MM-DD.md` | tracked |
| Resolution logs | `knowledge-base/*-resolutions.jsonl` | tracked |
| Spec tracking | `knowledge-base/specs/.spec-last-update` | tracked |
| Security tracking | `knowledge-base/security/.security-last-scan` | tracked |
| Update-check throttle | `~/.freya/update-check.json` | outside the repo |
| Project agent primer | `AGENTS.md` (managed block only) | tracked |

⚠ `behavior.json` holds observed coverage captured by running the tests, so it cannot be
rebuilt by re-reading source like its `.graph/` neighbours can. See
[architecture.md](architecture.md#output-artifacts) and [backlog.md](backlog.md).
