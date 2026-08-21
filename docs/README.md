# Documentation

freya-devkit is a suite of ten skills that help an AI agent maintain a codebase: dependency
graphs, documentation, specifications, behavior traceability, and security scanning, tied
together by one post-implementation workflow.

The skills are **agent-neutral** — they run on Claude Code, GitHub Copilot, and anything else
that reads the Agent Skills standard. Every bundled script is invoked through one launcher,
`freya <command>`, and nothing under `skills/` may name a host-specific construct;
`bin/check_skill_conformance.py` enforces that and CI runs it on every push.

## Where to start

| If you want to | Read |
|---|---|
| Understand why any of this exists | [philosophy.md](philosophy.md) |
| See what's here and what each skill does | [skill-reference.md](skill-reference.md) |
| Understand how the pieces fit together | [architecture.md](architecture.md) |
| Build or extend a skill | [patterns.md](patterns.md), then [conventions.md](conventions.md) |
| Know why something was built this way | [decisions/](decisions/) |
| Know what's still outstanding | [backlog.md](backlog.md) |

## What's in here

| Path | What it is |
|---|---|
| [philosophy.md](philosophy.md) | Why skills exist, core concepts, the mental model |
| [architecture.md](architecture.md) | How the skills connect, `bin/` and `skills/`, the dependency graph, data flow |
| [patterns.md](patterns.md) | Reusable patterns — coordinator + workers, the two-commit rule, incremental updates |
| [conventions.md](conventions.md) | Integration conventions for writing a skill that fits |
| [skill-reference.md](skill-reference.md) | Every skill, its commands, and what it reads and writes |
| [decisions/](decisions/) | **Architecture Decision Records.** What was decided, why, and what was rejected. Twenty-nine records covering the behavior layer, the graph substrate and its backends, governance and portability. |
| [backlog.md](backlog.md) | **The single live backlog.** Next initiative, deferred capabilities, verified open defects. Nothing outstanding lives anywhere else. |
| [migrations/](migrations/) | Runnable recipes for projects adopting a new version. **Run these**, don't just read them. |
| [explanations/](explanations/) | Source of the published explainer site. Uploaded verbatim as the GitHub Pages site root, so anything added here is published; the seven page filenames — `index`, `using`, `how-it-works`, `extending`, `reference`, `decisions`, `evolution` — are pinned URLs. |

## The shape of it

```
freya-code-graph                                            (foundation)
    ↓
freya-docs-manager  freya-spec-manager
freya-behavior-graph  freya-behavior-runner                 (knowledge + behavior)
    ↓
freya-codebase-security-scan  freya-dependency-vulnerability-check
                                                            (analysis)
    ↓
freya-wrap-up    orchestrates everything, incl. behavior integrity
freya-status     read-only counterpart — what's outstanding
    ↓
freya-codebase-security-resolver                            (resolution)
```

Skills compose through **on-disk artifacts**, not through calling each other: one writes a
graph, the next reads it. That is why they degrade gracefully — a missing upstream artifact
costs precision, not function.

## Two conventions worth knowing before you edit anything

**Generated artifacts live in `knowledge-base/`, hand-written documentation lives in `docs/`.**
This directory is entirely hand-written. When the toolkit runs against a project it creates
`knowledge-base/` for its own output — specs, reference docs, security reports, the graph
cache. freya-devkit deliberately has no `knowledge-base/` of its own yet; keeping the root
unclaimed means generated and hand-written content never share a directory.

**Only `freya-wrap-up` commits.** Every other skill writes its artifacts and stops. See
[patterns.md](patterns.md) and [conventions.md](conventions.md).
