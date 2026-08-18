# Design Notes

Cross-cutting ideas and deferred investigations that don't belong to a single feature's design folder. Each entry says *what*, *why deferred*, and *when to pick it up*.

## Audit all subagent flows + the generated-docs set (deferred: after portability)

**What:** Several skills orchestrate sub-agents (coordinator + parallel workers) — e.g. `docs-manager` spawns workers to generate documentation, `codebase-security-scan` spawns discovery/analysis workers, and `spec-manager scan` spawns discovery agents. As a later upgrade we should audit **all** of these flows. Specifically for `docs-manager`, review **what documents we actually generate** (ARCHITECTURE / API / DATABASE / …): are they the right set? Do we need more, fewer, or different docs — e.g. varying by project type / stack?

**Why deferred:** it's an upgrade, and it sits downstream of the multi-agent **portability** feature (Track A). Portability is already reshaping *how* these subagent flows are expressed (decoupling the unit-of-work from the scheduler), so it's cheaper to revisit the *content* of the flows afterward. It also ties into the framework-agnostic goal in the polyglot parking-lot (docs-manager's templates are Next/Prisma-flavored today).

**When to pick it up:** after portability ships. Start by enumerating every coordinator/worker flow; then revisit the docs-manager generated-doc set against arbitrary stacks.
