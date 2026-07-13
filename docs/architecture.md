# Architecture

How skills connect, share data, and work together.

## Skill Dependency Graph

The toolkit is **ten skills across five tiers**. Each tier builds on the ones above it:

```
Tier 1 — Foundation
    code-graph ............ builds knowledge-base/.graph/graph.json (impact / blast radius)
        │
        ▼
Tier 2 — Knowledge / Consumers
    docs-manager .......... impact-aware documentation
    spec-manager .......... specs, ADRs, principles, and the behavior lifecycle
    behavior-graph ........ behavior.json (sibling of graph.json); BEHAVIOR → TEST → CODE
        └─ behavior-runner  runs accepted behaviors, captures TEST → CODE coverage
        │
        ▼
Tier 3 — Analysis
    codebase-security-scan .......... blast-radius- and intent-aware findings
    dependency-vulnerability-check .. supply-chain / CVE audit
        │
        ▼
Tier 4 — Orchestration
    wrap-up ... runs code-graph → docs → specs → behavior integrity & run (Phase 3.5) → security, then two commits
    status .... read-only counterpart: outstanding intent / tests / coverage / findings; refreshes BACKLOG.md
        │
        ▼
Tier 5 — Resolution
    codebase-security-resolver ...... fixes findings, documents intentional ones
```

## Skill Tiers

### Tier 1: Foundation

| Skill | Purpose | Used By |
|-------|---------|---------|
| `code-graph` | Dependency graph, impact analysis | All other skills |

This is the foundation. It knows what files depend on what, enabling impact-aware operations.

### Tier 2: Knowledge / Consumers

| Skill | Purpose | Dependencies |
|-------|---------|--------------|
| `docs-manager` | Project documentation | code-graph (optional) |
| `spec-manager` | Feature specs, ADRs, principles, behavior lifecycle | code-graph (optional) |
| `behavior-graph` | Behavior graph (`behavior.json`); blast radius both directions | code-graph, behavior-runner |
| `behavior-runner` | Run accepted behaviors, capture coverage fingerprints | code-graph |

These skills maintain structured knowledge about the codebase. `behavior-graph` and `behavior-runner` form the **behavior layer**: intended behavior as first-class, executable records projected into `behavior.json` (a sibling of `graph.json`). They use `code-graph` when available for smarter updates and blast radius.

### Tier 3: Analysis

| Skill | Purpose | Dependencies |
|-------|---------|--------------|
| `codebase-security-scan` | Security auditing | code-graph, spec-manager, behavior-graph |
| `dependency-vulnerability-check` | Supply chain security | None |

Security analysis benefits from impact awareness (code-graph) and from understanding intentional design — both declarative specs and **accepted, test-backed behaviors** (the strongest "intentional" evidence).

### Tier 4: Orchestration

| Skill | Purpose | Dependencies |
|-------|---------|--------------|
| `wrap-up` | Post-implementation workflow (mutates + commits) | All above |
| `status` | Read-only outstanding-work aggregation; refreshes `BACKLOG.md` | All above (read-only) |

`wrap-up` is the do/sync command; `status` is its read-only check-counterpart — "where do I stand, what's outstanding?"

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
                                          knowledge-base/.graph/graph.json
```

### Output Artifacts

```
┌─────────────────────────────────────────────────────────────┐
│                     knowledge-base/                          │
├─────────────────────────────────────────────────────────────┤
│ ├── README.md             ← docs-manager (index)             │
│ ├── principles.md         ← spec-manager (constitution)      │
│ ├── BACKLOG.md            ← status (generated, git-tracked)  │
│ ├── reference/            ← docs-manager                     │
│ │   ├── ARCHITECTURE.md                                      │
│ │   ├── API.md                                               │
│ │   └── ...                                                  │
│ ├── specs/                ← spec-manager                     │
│ │   ├── features/                                            │
│ │   ├── auth/                                                │
│ │   └── .spec-last-update                                    │
│ ├── decisions/            ← spec-manager (cross-cutting ADRs)│
│ ├── intents/              ← spec-manager (INTENT-NNN records)│
│ ├── security/             ← security-scan                    │
│ │   ├── codebase-security/                                   │
│ │   │   └── 2024-01-15.md                                    │
│ │   └── .security-last-scan                                  │
│ └── .graph/                                                  │
│     ├── graph.json            ← code-graph                   │
│     ├── classifications.json  ← code-graph                   │
│     └── behavior.json         ← behavior-graph (sibling)     │
└─────────────────────────────────────────────────────────────┘
```

The governance resolution logs (`principle-`, `contradiction-`, `drift-resolutions.jsonl`) also live under `knowledge-base/`; see [patterns.md](patterns.md).

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
   - Updates affected specs, adjusts certainty scores
         │
         ▼
5. behavior integrity & run  (wrap-up Phase 3.5)
   - behavior-graph builds/refreshes behavior.json (projects spec frontmatter,
     runs affected accepted behaviors via behavior-runner, merges by trust)
   - Deterministic link/ADR/declared-intent checks hard-block; a regression on an
     accepted behavior hard-blocks; principle/contradiction/drift checkpoints
     resolve-to-proceed
         │
         ▼
6. security-scan update
   - Asks code-graph for blast radius
   - Asks spec-manager + behavior-graph for intentional design
   - Generates findings with context
```

## Tracking Files

Skills use tracking files to enable incremental updates:

| File | Owner | Purpose |
|------|-------|---------|
| `.spec-last-update` | spec-manager | Last commit scanned for specs |
| `.security-last-scan` | security-scan | Last commit scanned for security |
| `.intent-last-verified` | spec-manager | Baseline for the declared-intent gate (G1) |
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

This means skills work standalone but work better together. The behavior layer degrades the same way: with no `code-graph` cache the declarative-drift check bounds its blast radius to changed files (never a silent empty set), and non-vitest / non-unit behaviors are emitted `coverage: "unknown"` rather than falsely marked passing.

## Directory Structure

Skills live at the plugin repo's `skills/` directory (scripts are referenced at runtime via `${CLAUDE_PLUGIN_ROOT}/skills/<skill>/scripts/…`):

```
skills/
├── code-graph/
│   ├── SKILL.md
│   └── scripts/
│       └── graph_ops.py
├── docs-manager/
│   ├── SKILL.md
│   └── scripts/
│       └── detect_project.py
├── spec-manager/
│   ├── SKILL.md
│   ├── scripts/
│   │   ├── search_specs.py       # spec CRUD / search
│   │   ├── frontmatter.py        # schema + validation
│   │   ├── adr.py                # ADRs (P4a)
│   │   ├── principles.py         # G2 principle checkpoint
│   │   ├── contradictions.py     # G3 contradiction check
│   │   ├── drift.py              # P4b declarative-drift check
│   │   ├── verify_intent.py      # G1 declared-intent gate
│   │   ├── verify_links.py       # link integrity
│   │   └── resolution_log.py     # shared append-only resolution log
│   └── references/
│       ├── spec-template.md
│       └── categories.md
├── behavior-graph/
│   ├── SKILL.md
│   └── scripts/
│       └── behavior_graph.py
├── behavior-runner/
│   ├── SKILL.md
│   └── scripts/
│       └── run_behaviors.py
├── codebase-security-scan/
│   └── SKILL.md
├── codebase-security-resolver/
│   └── SKILL.md
├── dependency-vulnerability-check/
│   └── SKILL.md
├── status/
│   ├── SKILL.md
│   └── scripts/
│       └── collect_status.py
└── wrap-up/
    └── SKILL.md
```

Each skill follows a similar structure but adapts to its needs.
