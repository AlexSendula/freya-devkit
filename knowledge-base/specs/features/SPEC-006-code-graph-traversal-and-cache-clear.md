---
id: SPEC-006
title: Transitive traversal and clearing the graph cache
category: features
tags: [code-graph, traversal, scale, cache, clear]
status: implemented
certainty: 72
created: 2026-08-21
updated: 2026-08-21
related_code:
  - skills/freya-code-graph/scripts/graph_ops.py
  - skills/freya-code-graph/scripts/substrate.py
intentional_decisions:
  - "Traversal is iterative with an explicit worklist, never recursive, and the visited set is what terminates it"
  - "Clearing the cache deletes every backend's graph file but deliberately keeps the directory classifications"
  - "Clearing the cache never touches behavior.json, which is committed and cannot be rebuilt from source"
behaviors:
  - behavior_id: BEH-029
    title: Transitive dependents and dependencies answer over a very long import chain
    state: proposed
    level: component
    adapter: unittest
    locator: skills/freya-code-graph/scripts/test_graph_ops.py#TestScaleAndScopeDefects.test_a_long_import_chain_does_not_blow_the_stack
  - behavior_id: BEH-030
    title: Clearing the cache removes every backend's graph file
    state: proposed
    level: component
    adapter: unittest
    locator: skills/freya-code-graph/scripts/test_substrate.py#TestClearRemovesEveryArtifact.test_clear_removes_the_per_backend_copy_too
---

# Transitive traversal and clearing the graph cache

## What

Two things the graph does after it has been built and asked a question.

**Traversal.** `--dependents` and `--dependencies` walk the graph transitively by default, so
the answer is the full reachable set rather than one hop, and `--impact` reports the direct
and transitive parts separately over several inputs at once. The walk is bounded by the size
of the reachable component, not by any depth limit, and it must hold up on the shapes real
repositories actually have — a 1,500-file import chain is an ordinary monorepo, not a
pathological fixture.

**Clearing.** `freya code-graph --clear` deletes the regenerable graph artifacts for the
project: `graph.json` plus every per-backend `graph.<backend>.json`. It removes the `.graph`
directory if that leaves it empty, and returns whether anything was removed.

Two things it deliberately does not delete: `classifications.json`, which holds user and
model judgements about which directories are source, and `behavior.json`, which is committed
and cannot be rebuilt by re-reading source.

Two observations that are *not* asserted as intent here, because the code does not say either
way:

- `[NEEDS CLARIFICATION]` `--clear` on a project with no cache still prints
  `Cleared dependency graph cache for this project.` and exits 0, while the JSON form of the
  same run prints `false`. Verified by hand, 2026-08-21. Whether the summary should say
  "nothing to clear" is a product decision nobody has made.
- `[NEEDS CLARIFICATION]` `docs.json` sits in the same directory and is listed alongside the
  graph files as regenerable cache, but `clear()` does not remove it. Deliberate scoping or an
  omission is not determinable from the code.

## Why

Both halves exist to stop a *silent* wrong answer rather than a loud one.

A recursive walk over this graph does not fail gracefully. `run_behaviors` invokes
`--dependencies` with `check=True`, so a `RecursionError` becomes `graph-query-failed`, then
`coverage: unknown` for every integration behavior, then a frozen committed `behavior.json`.
A stack overflow in one query narrows every blast radius in the repository afterwards.

A leftover per-backend graph is the same class of problem at rest. `graph.json` at least
announces its absence when it is gone; a stale `graph.<backend>.json` left behind by a clear
looks current and is reported by nothing.

## Behavior

| Behavior | State | Verified by |
|----------|-------|-------------|
| BEH-029 Transitive dependents and dependencies answer over a very long import chain | proposed | `test_graph_ops.py#TestScaleAndScopeDefects.test_a_long_import_chain_does_not_blow_the_stack` (unittest) |
| BEH-030 Clearing the cache removes every backend's graph file | proposed | `test_substrate.py#TestClearRemovesEveryArtifact.test_clear_removes_the_per_backend_copy_too` (unittest) |

The other half of BEH-030 — that `classifications.json` survives a clear — has **no test**.
It is stated three times in comments (in `clear`, in `_load_classifications`, and in
`settings.py`) and one test docstring relies on it while asserting something else, but nothing
asserts it. A future change to `clear` that swept the whole directory would be caught by
nothing and would silently discard decisions a person made.

## Intentional Design Decisions

### Traversal is iterative by construction

**Decision**: `get_dependents` and `get_dependencies` use an explicit `pending` list and a
`result` set instead of recursion, and a node is added to `result` *before* it is queued, so a
cyclic import graph terminates.

**Rationale**: a recursive DFS here is bounded by the size of the reachable component rather
than by depth. A 1,500-file chain — reproduced on a fixture, and an ordinary monorepo shape —
raised `RecursionError` and exited non-zero, and the consequence of that exit is described
under Why.

**Security Scan Note**: the hand-rolled worklist is deliberate; it is not an un-refactored
loop to be "simplified" into recursion, and raising the recursion limit is not an acceptable
substitute. The `while pending` loop is not unbounded: every path is added to `result` at most
once and only then queued, so the loop is bounded by the node count even on a cyclic graph.

### A cache clear keeps what a person decided

**Decision**: `clear()` deletes `graph.json` and every `graph.<backend>.json`, and
deliberately leaves `classifications.json` in place, along with `behavior.json`.

**Rationale**: the two graph files are a parse cache, rebuildable from source in seconds.
`classifications.json` is not — it records which directories a user or a model judged to be
source, and a cache clear has no business discarding a judgement. `behavior.json` is the
committed observed-coverage artifact and is out of scope for the same reason in stronger form;
that split is ADR-017's, and the per-backend file it must also sweep is ADR-028's.

**Security Scan Note**: files remaining in `.graph/` after a documented "clear cache"
operation are intentional retention, not incomplete cleanup, and not a stale-state bug.
Nothing sensitive is retained: `classifications.json` holds directory names and verdicts.

## Certainty

72. Lower than the sibling specs for two reasons. The traversal decision is unambiguous —
inline post-mortem, a fixture at scale, a named downstream consequence — but the clear
surface is only half pinned: the retention half of BEH-030 has no test, and the two
`[NEEDS CLARIFICATION]` items above are places where the observed behavior may be intent or
may be an oversight, with nothing in the code to settle it. Recorded rather than guessed.

## Related Specs

- [SPEC-004: Building and refreshing the dependency graph](./SPEC-004-code-graph-build-and-update.md)
- [SPEC-005: Never a confidently empty answer](./SPEC-005-code-graph-answers-and-empty-results.md)

## Change History

| Date | Change | Reason |
|------|--------|--------|
| 2026-08-21 | Initial spec, inferred from code and tests | Brownfield scan of the code-graph traversal and cache surface |
