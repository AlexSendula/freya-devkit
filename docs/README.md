# Skills System Documentation

This directory documents the skills ecosystem for AI-assisted app development and maintenance.

## Purpose

Help AI agents understand the philosophy, architecture, and patterns behind the skills system so they can:
- Work effectively with existing skills
- Create new skills that integrate naturally
- Maintain consistency with established conventions

## Documentation

| Document | Purpose |
|----------|---------|
| [philosophy.md](philosophy.md) | Why skills exist, core concepts, mental model |
| [architecture.md](architecture.md) | How skills connect, dependency graph, data flow |
| [patterns.md](patterns.md) | Reusable patterns (coordinator+workers, two-commit, etc.) |
| [conventions.md](conventions.md) | Integration conventions, not strict rules |
| [skill-reference.md](skill-reference.md) | Quick reference table of all skills |

## Quick Orientation

### The Core Idea

Skills are specialized workflows that work together to maintain a codebase. Instead of one monolithic prompt, we have focused skills that:

1. **Integrate with each other** - skills can use other skills
2. **Share context** - through docs, specs, and graphs
3. **Follow consistent patterns** - but aren't strictly forced to

### The Foundation

```
code-graph (foundation)
    ↓
docs-manager, spec-manager, behavior-graph, behavior-runner  (the behavior layer) — use code-graph
    ↓
codebase-security-scan, dependency-vulnerability-check  (analysis)
    ↓
wrap-up (orchestrates everything, incl. behavior integrity Phase 3.5)  ·  status (read-only check)
```

### Key Patterns

- **Coordinator + Workers**: One agent plans, parallel workers execute
- **Two-Commit Pattern**: Code changes separate from generated artifacts
- **Incremental Updates**: Git-aware, only process what changed
- **Certainty Scoring**: Confidence levels for AI-generated specs

### Integration Philosophy

Skills don't have to follow these patterns, but understanding them helps create skills that fit naturally into the ecosystem. The goal is coherence, not enforcement.

## Getting Started

1. Read [philosophy.md](philosophy.md) to understand the "why"
2. Skim [skill-reference.md](skill-reference.md) to see what exists
3. Reference [patterns.md](patterns.md) when building new skills
4. Check [conventions.md](conventions.md) for integration guidelines
