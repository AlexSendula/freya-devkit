# Skills System Documentation

This directory documents the skills ecosystem for AI-assisted app development and maintenance.

The skills are **agent-neutral**: they run on Claude Code, GitHub Copilot, and anything
else that reads the Agent Skills standard. Every bundled script is invoked through one
launcher, `freya <command>`, and nothing under `skills/` may name a host-specific
construct — `bin/check_skill_conformance.py` enforces that and CI runs it on every push.

## Purpose

Help AI agents understand the philosophy, architecture, and patterns behind the skills system so they can:
- Work effectively with existing skills
- Create new skills that integrate naturally
- Maintain consistency with established conventions

## Documentation

| Document | Purpose |
|----------|---------|
| [philosophy.md](philosophy.md) | Why skills exist, core concepts, mental model |
| [architecture.md](architecture.md) | How skills connect, `bin/` and `skills/`, dependency graph, data flow |
| [patterns.md](patterns.md) | Reusable patterns (coordinator+workers, two-commit, etc.) |
| [conventions.md](conventions.md) | Integration conventions, not strict rules |
| [skill-reference.md](skill-reference.md) | Quick reference table of all skills |
| [migrations/](migrations/) | One-time moves between versions — run these, don't just read them |

Two more directories sit alongside, and are read differently:

| Directory | How to read it |
|-----------|----------------|
| [design/](design/) | **Dated design records.** What was decided, when, and why — including reasoning that turned out wrong, kept with a dated correction beneath it rather than rewritten. Not a specification; shipped code wins. |
| [explanations/](explanations/) | The source of the published visual explainers (GitHub Pages). |

## Quick Orientation

### The Core Idea

Skills are specialized workflows that work together to maintain a codebase. Instead of one monolithic prompt, we have focused skills that:

1. **Integrate with each other** - skills can use other skills
2. **Share context** - through docs, specs, and graphs
3. **Follow consistent patterns** - but aren't strictly forced to

### The Foundation

```
freya-code-graph (foundation)
    ↓
freya-docs-manager, freya-spec-manager, freya-behavior-graph, freya-behavior-runner
        (the behavior layer) — use code-graph
    ↓
freya-codebase-security-scan, freya-dependency-vulnerability-check  (analysis)
    ↓
freya-wrap-up (orchestrates everything, incl. behavior integrity Phase 3.5)
freya-status  (read-only check)
```

### Key Patterns

- **Coordinator + Independent Tasks**: One agent plans, then independent tasks run in parallel if the agent supports subagents, else one at a time — except where the guarantee is load-bearing, where a driver schedules its own worker processes instead
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
