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
| See what's here and what each skill does | [reference/SKILL_REFERENCE.md](reference/SKILL_REFERENCE.md) |
| Understand how the pieces fit together | [reference/ARCHITECTURE.md](reference/ARCHITECTURE.md) |
| Build or extend a skill | [patterns.md](patterns.md), then [reference/DEVELOPER.md](reference/DEVELOPER.md) |
| Know why something was built this way | [decisions/](decisions/) |
| Know what's still outstanding | [roadmap.md](roadmap.md) |

## What's in here

| Path | What it is | Owner |
|---|---|---|
| [README.md](README.md) | This index | `docs-manager` |
| [reference/](reference/) | Descriptive documentation, reverse-synced from the code | `docs-manager` |
| [reference/ARCHITECTURE.md](reference/ARCHITECTURE.md) | How the skills connect, `bin/` and `skills/`, the dependency graph, data flow | `docs-manager` |
| [reference/DEVELOPER.md](reference/DEVELOPER.md) | Integration conventions for writing a skill that fits | `docs-manager` |
| [reference/SKILL_REFERENCE.md](reference/SKILL_REFERENCE.md) | Every skill, its commands, and what it reads and writes | `docs-manager` |
| [philosophy.md](philosophy.md) | Why skills exist, core concepts, the mental model | hand-written |
| [patterns.md](patterns.md) | Reusable patterns — coordinator + workers, the two-commit rule, incremental updates | hand-written |
| [decisions/](decisions/) | **Architecture Decision Records.** What was decided, why, and what was rejected. Twenty-nine records covering the behavior layer, the graph substrate and its backends, governance and portability. | hand-written |
| [roadmap.md](roadmap.md) | **The single live backlog.** Next initiative, deferred capabilities, verified open defects. Nothing outstanding lives anywhere else. | hand-written |
| [migrations/](migrations/) | Runnable recipes for projects adopting a new version. **Run these**, don't just read them. | hand-written |
| [explanations/](explanations/) | Source of the published explainer site. Uploaded verbatim as the GitHub Pages site root, so anything added here is published; the seven page filenames — `index`, `using`, `how-it-works`, `extending`, `reference`, `decisions`, `evolution` — are pinned URLs. | hand-written |
| `.graph/` | Generated graph cache. Self-ignoring except `behavior.json`, which is committed (ADR-017). | `code-graph`, `behavior-graph` |
| `settings.json` | Project settings — the graph backend, directory verdicts. Committed. | `code-graph` |

`BACKLOG.md` is **not** in this tree and must not be created by hand: `freya status` writes it
by full overwrite. The hand-maintained backlog is [`roadmap.md`](roadmap.md), which is why it
carries that name.

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

**Generated and hand-written content share this directory, and the table above says which is
which.** freya-devkit runs against itself, so this tree is the same `knowledge-base/` layout
the toolkit creates in any adopting project. Three paths are written by full overwrite and
nothing hand-authored may live at them: `README.md`, `reference/`, and `BACKLOG.md`. Everything
else here the toolkit reads or ignores. Until 2026-08-21 this repo kept a hand-written `docs/`
instead and had no `knowledge-base/` at all, on the reasoning that the two should never mix;
running the toolkit on itself is what made that reasoning cost more than it saved.

**Only `freya-wrap-up` commits.** Every other skill writes its artifacts and stops. See
[patterns.md](patterns.md) and [reference/DEVELOPER.md](reference/DEVELOPER.md).
