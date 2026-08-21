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
| [reference/PROJECT_OVERVIEW.md](reference/PROJECT_OVERVIEW.md) | What this is, who it is for, and what it deliberately is not | `docs-manager` |
| [reference/ARCHITECTURE.md](reference/ARCHITECTURE.md) | How the skills connect, `bin/` and `skills/`, the graph substrate, data flow | `docs-manager` |
| [reference/DEVELOPER.md](reference/DEVELOPER.md) | Working on the toolkit: tests, the conformance gate, the conventions a new skill must fit | `docs-manager` |
| [reference/SKILL_REFERENCE.md](reference/SKILL_REFERENCE.md) | Every skill, its commands, and what it reads and writes | `docs-manager` |
| [reference/TESTING.md](reference/TESTING.md) | The suite, what CI runs, and the two conventions this repo learned the hard way | `docs-manager` |
| [reference/DEPLOYMENT.md](reference/DEPLOYMENT.md) | How it ships — install paths, the plugin, `freya update`, GitHub Pages | `docs-manager` |
| [reference/ENVIRONMENT.md](reference/ENVIRONMENT.md) | Every environment variable and external binary, and what changes when it is set | `docs-manager` |
| [reference/SECURITY.md](reference/SECURITY.md) | The toolkit's own posture: the read-only allowlist, the cost gate, the sandbox's limits | `docs-manager` |
| [reference/STYLE_GUIDE.md](reference/STYLE_GUIDE.md) | The conventions actually in force, each with an example you can open | `docs-manager` |
| [reference/TROUBLESHOOTING.md](reference/TROUBLESHOOTING.md) | Real failure modes, how to confirm each one, and the fix | `docs-manager` |
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
the toolkit creates in any adopting project. Three paths are the toolkit's to write and
nothing hand-authored may live at them: `README.md`, `reference/`, and `BACKLOG.md`. Only one
of those is enforced in code — `freya status` opens `BACKLOG.md` with mode `w`
(`collect_status.py:222`), so anything there is destroyed on the next run without warning. The
other two are written by an agent following `docs-manager`'s SKILL.md, which means they are a
convention an agent can be talked out of, not a guarantee. Everything else here the toolkit
reads or ignores. Until 2026-08-21 this repo kept a hand-written `docs/`
instead and had no `knowledge-base/` at all, on the reasoning that the two should never mix;
running the toolkit on itself is what made that reasoning cost more than it saved.

**Only `freya-wrap-up` commits generated artifacts.** Every other artifact-writing skill
writes its output and stops. Two caveats worth knowing before you rely on it:
`freya-codebase-security-resolver` does commit — the *code fix* it made, so the scan has a
hash to diff against (`skills/freya-codebase-security-resolver/SKILL.md:534`) — and no code
enforces any of this. It is a paragraph in four SKILL.md bodies and nothing else; a skill
that omitted it would break the two-commit invariant silently. See
[patterns.md](patterns.md) and [reference/DEVELOPER.md](reference/DEVELOPER.md).
