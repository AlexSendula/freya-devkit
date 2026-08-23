---
id: SPEC-004
title: Building and refreshing the dependency graph
category: features
tags: [code-graph, build, incremental, git, cache]
status: implemented
certainty: 82
created: 2026-08-21
updated: 2026-08-21
related_code:
  - skills/freya-code-graph/scripts/graph_ops.py
  - skills/freya-code-graph/scripts/substrate.py
intentional_decisions:
  - "Any cached graph that cannot be trusted is rebuilt whole, never patched forward"
  - "Rename detection is switched off and diff paths are project-relative, so a moved file leaves no ghost node"
  - "A build whose result would empty a populated graph refuses, keeps the previous artifact and exits non-zero"
  - "git runs as a fixed-argv subprocess and every git failure degrades to cannot-tell rather than raising"
behaviors:
  - behavior_id: BEH-016
    title: A build from scratch says what it scanned and where it cached the graph
    state: proposed
    level: integration
    adapter: unittest
    entry: skills/freya-code-graph/scripts/graph_ops.py
    locator: skills/freya-code-graph/scripts/test_graph_ops.py#TestSummaryFormatIsWhatIsDocumented.test_build_says_cached_to
  - behavior_id: BEH-017
    title: An update applies a change when the project sits below the git root
    state: proposed
    level: component
    adapter: unittest
    locator: skills/freya-code-graph/scripts/test_graph_ops.py#TestScaleAndScopeDefects.test_update_works_when_the_project_is_below_the_git_root
  - behavior_id: BEH-018
    title: An update with nothing changed reports up to date and leaves the artifact untouched
    state: proposed
    level: integration
    adapter: unittest
    entry: skills/freya-code-graph/scripts/graph_ops.py
    locator: skills/freya-code-graph/scripts/test_graph_ops.py#TestUnmappedSourceCLI.test_an_up_to_date_update_carries_the_census_without_re_walking
  - behavior_id: BEH-019
    title: An update whose cached commit git cannot resolve rebuilds instead of reporting no changes
    state: proposed
    level: component
    adapter: unittest
    locator: skills/freya-code-graph/scripts/test_graph_ops.py#TestOlderGraphsWithStringEdges.test_a_commit_git_cannot_resolve_rebuilds_rather_than_reporting_no_changes
  - behavior_id: BEH-020
    title: An update after a rename drops the vanished path from the graph
    state: proposed
    level: component
    adapter: unittest
    locator: skills/freya-code-graph/scripts/test_graph_ops.py#TestRenamesLeaveNoGhostNode.test_the_old_path_leaves_the_graph
  - behavior_id: BEH-021
    title: An update over a schema-stale artifact rebuilds it rather than stamping the version forward
    state: proposed
    level: component
    adapter: unittest
    locator: skills/freya-code-graph/scripts/test_graph_ops.py#TestOlderGraphsWithStringEdges.test_a_stale_artifact_triggers_a_full_rebuild_not_a_rewrite
  - behavior_id: BEH-022
    title: An update with no cached graph falls back to a full build and says so
    state: proposed
    level: component
    adapter: manual
    locator: skills/freya-code-graph/scripts/test_graph_ops.py#TestUpdateWithoutACache.test_a_first_update_falls_back_to_a_full_build
  - behavior_id: BEH-023
    title: A build that would leave the graph empty refuses and keeps the previous graph
    state: proposed
    level: integration
    adapter: unittest
    entry: skills/freya-code-graph/scripts/graph_ops.py
    locator: skills/freya-code-graph/scripts/test_graph_ops.py#TestRefusingToEraseIsARefusalNotACrash.test_it_reports_and_exits_rather_than_raising
---

# Building and refreshing the dependency graph

## What

`freya code-graph --build` produces the project's import graph from scratch and caches it
under `knowledge-base/.graph/`; `freya code-graph --update` refreshes that cache from the
files git says changed since the commit the cache records. Both are the entry points every
other skill's impact analysis stands on, and both answer on stdout in either JSON or
`--format summary`.

The scope of this spec is the **lifecycle** of that artifact — when a refresh is
incremental, when it silently becomes a full rebuild, and when a build declines to write at
all. It does not cover how an individual import is resolved, nor what an answer says about
the files the backend could not read (SPEC-005).

`--update` degrades to a full build on five distinct conditions: no cached graph, a cache
with no commit recorded, a cache written by a different backend, a cache at an older schema
version, and a cached commit git cannot resolve against HEAD. Each of these was, at some
point, a silent "up to date" that froze the graph while it went on answering confidently.

Two smaller scope facts belong here because they are load-bearing rather than incidental:
the changed-file list is asked for with `--no-renames --relative`, and changed files are
re-filtered through the same exclusion rules `build()` applies, so an update never re-admits
a file the build excluded.

## Why

A dependency graph that is quietly stale is worse than no graph at all: docs-manager,
spec-manager and the security scan all narrow their work to a blast radius this artifact
computes, so a frozen cache silently narrows all three. Every fallback-to-full-build branch
in `update()` exists because a specific version of "reported success, changed nothing" was
observed in the field — the module carries the post-mortem for each one inline.

The refusal in `--build` is the same argument from the other end. Excluding the last source
directory, or deleting the last source file, is an ordinary thing to commit; overwriting a
populated graph with an empty one in response would hand every downstream consumer a
confidently-empty answer.

## Behavior

| Behavior | State | Verified by |
|----------|-------|-------------|
| BEH-016 A build from scratch says what it scanned and where it cached the graph | proposed | `test_graph_ops.py#TestSummaryFormatIsWhatIsDocumented.test_build_says_cached_to` (unittest) |
| BEH-017 An update applies a change when the project sits below the git root | proposed | `test_graph_ops.py#TestScaleAndScopeDefects.test_update_works_when_the_project_is_below_the_git_root` (unittest) |
| BEH-018 An update with nothing changed reports up to date and leaves the artifact untouched | proposed | `test_graph_ops.py#TestUnmappedSourceCLI.test_an_up_to_date_update_carries_the_census_without_re_walking` (unittest) |
| BEH-019 An update whose cached commit git cannot resolve rebuilds instead of reporting no changes | proposed | `test_graph_ops.py#TestOlderGraphsWithStringEdges.test_a_commit_git_cannot_resolve_rebuilds_rather_than_reporting_no_changes` (unittest) |
| BEH-020 An update after a rename drops the vanished path from the graph | proposed | `test_graph_ops.py#TestRenamesLeaveNoGhostNode.test_the_old_path_leaves_the_graph` (unittest) |
| BEH-021 An update over a schema-stale artifact rebuilds it rather than stamping the version forward | proposed | `test_graph_ops.py#TestOlderGraphsWithStringEdges.test_a_stale_artifact_triggers_a_full_rebuild_not_a_rewrite` (unittest) |
| BEH-022 An update with no cached graph falls back to a full build and says so | proposed | *no test* — proposed home `test_graph_ops.py#TestUpdateWithoutACache` (manual) |
| BEH-023 A build that would leave the graph empty refuses and keeps the previous graph | proposed | `test_graph_ops.py#TestRefusingToEraseIsARefusalNotACrash.test_it_reports_and_exits_rather_than_raising` (unittest) |

BEH-022 is the everyday first-run path — `--update` on a project that has never been built —
and it is the one branch of the five with no direct test. The neighbouring fallbacks
(BEH-019, BEH-021) are each pinned; this one is only exercised incidentally by fixtures that
happen to start with no cache.

## Intentional Design Decisions

### An untrustworthy cache is rebuilt whole, never patched forward

**Decision**: `CodeGraph.update` returns `self.build(...)` outright on five separate
conditions rather than repairing the artifact in place — including the case where the only
thing wrong is the recorded schema version, where stamping the version forward would be a
one-line fix.

**Rationale**: the `substrate` block records which backend ran and what that backend can
read, and it cannot be reconstructed from an artifact that predates it — only a real build
knows. Stamping the version was tried and was worse than doing nothing: the graph stopped
being stale, so nothing looked at it again, and it was left permanently claiming no backend
and no coverage. The governing rule is ADR-005 — an answer must never be confidently empty —
applied to the artifact's own metadata. The cross-backend case is ADR-028 territory: patching
one resolver's edges into another's graph produces a graph no reader can characterise.

**Security Scan Note**: the five near-identical `return self.build(...)` branches are not
copy-paste duplication to be collapsed, and re-parsing an entire project because of a version
integer is not a performance defect. Each branch is a distinct diagnosis with its own stderr
line; merging them loses the message that tells an operator *which* condition fired.

### Rename detection off, diff paths project-relative

**Decision**: the changed-file list is obtained with
`git diff <commit>..HEAD --name-only --no-renames --relative`.

**Rationale**: two different failures, one call. With git's default rename detection a moved
file is reported once, as its destination, and the path it vanished from is never named — so
`update()` never deletes the old node, and `--dependents` on it goes on answering with files
that no longer import it. `--relative` is required because `--name-only` emits
repository-relative paths while every graph key is project-relative; without it, a project
below the git root (a monorepo package, or `--dir pkg`) matched nothing, found no work, and
reported success (BEH-017).

**Security Scan Note**: disabling rename detection is deliberate and is not a
performance-tuning oversight. This code asks *which paths moved*, not *what the author meant*.

### git failure means "cannot tell", never an exception

**Decision**: `_get_git_commit` and `_get_changed_files` run git through `subprocess.run`
with a fixed argument list, `capture_output=True` and no shell, swallow every exception, and
return `None` on any non-zero exit. `None` and `[]` are then treated as different answers by
the caller.

**Rationale**: a repository with no git, a rebased-away commit, or a graph carried between
checkouts must not crash a build; but neither may it be reported as "nothing changed", which
is what a single empty-list return produced for years (BEH-019).

**Security Scan Note**: the broad `except Exception` around the subprocess calls is
intentional error containment, not swallowed-error sloppiness — the failure is converted into
an explicit `None` that the caller acts on. There is no shell interpolation: `since_commit`
is passed as its own argv element to a fixed command.

### Refusing to write is a message, not a traceback

**Decision**: when a build would replace a populated graph with an empty one, it raises
`EmptiedTheGraph`, which `main()` catches and turns into a one-paragraph stderr message plus
exit 1. The previous graph is left exactly as it was, and the message names `--clear` as the
way to proceed deliberately.

**Rationale**: excluding the last source directory is an ordinary commit, and the refusal is
right — but it reached users as an unhandled traceback with the composed explanation buried
inside it.

**Security Scan Note**: exit 1 with the old artifact still on disk is the intended outcome,
not a failed cleanup or a partially written file. Nothing here is a resource leak.

## Certainty

82. Inferred from code and tests rather than authored, so not 100. High within that band
because each fallback branch carries an inline post-mortem naming the failure it prevents,
seven of the eight behaviors have a test that asserts exactly the observable outcome, and the
decisions above are corroborated by ADR-005 and ADR-028. Held below 85 because the exact
wording of the build summary (BEH-016) and the untested first-update fallback (BEH-022) are
inferences about intent, not statements the code makes about itself.

## Related Specs

- [SPEC-005: Never a confidently empty answer](./SPEC-005-code-graph-answers-and-empty-results.md)
- [SPEC-006: Transitive traversal and clearing the graph cache](./SPEC-006-code-graph-traversal-and-cache-clear.md)

## Change History

| Date | Change | Reason |
|------|--------|--------|
| 2026-08-21 | Initial spec, inferred from code and tests | Brownfield scan of the code-graph build/update surface |
