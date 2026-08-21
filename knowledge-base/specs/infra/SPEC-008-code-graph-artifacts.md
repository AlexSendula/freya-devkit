---
id: SPEC-008
title: Code Graph Artifacts and What Is Committable
category: infra
tags: [substrate, code-graph, artifacts, gitignore, migration, backend-selection]
status: implemented
certainty: 80
created: 2026-08-21
updated: 2026-08-21
related_code:
  - skills/freya-code-graph/scripts/graph_ops.py
  - skills/freya-code-graph/scripts/substrate.py
  - skills/freya-code-graph/scripts/backend_graphify.py
  - skills/freya-behavior-graph/scripts/behavior_graph.py
intentional_decisions:
  - "Every build writes the graph twice — the active artifact and a per-backend copy"
  - "Nothing in the toolkit reads graph.<backend>.json; it exists as a baseline for a human diff"
  - "behavior.json is the one .graph/ artifact that is deliberately committed"
  - "A backend writes a .gitignore into a directory it does not own, and stops doing so once a human edits it"
behaviors:
  - behavior_id: BEH-038
    title: A build writes the active graph and a copy named for the backend that produced it
    state: proposed
    level: component
    adapter: unittest
    locator: skills/freya-code-graph/scripts/test_substrate.py#TestPerBackendArtifacts.test_a_build_writes_the_per_backend_artifact
  - behavior_id: BEH-039
    title: Every regenerable graph artifact a build writes is gitignored, and behavior.json deliberately is not
    state: proposed
    level: component
    adapter: unittest
    locator: skills/freya-code-graph/scripts/test_substrate.py#TestPerBackendArtifacts.test_the_per_backend_artifact_is_gitignored
  - behavior_id: BEH-040
    title: The graphify backend marks its own output directory uncommittable, and leaves a hand-edited marker alone
    state: proposed
    level: integration
    adapter: unittest
    entry: skills/freya-code-graph/scripts/backend_graphify.py
    locator: skills/freya-code-graph/scripts/test_backend_graphify.py#TestAgainstTheRealBinary.test_the_output_directory_is_marked_not_committable
---

# Code Graph Artifacts and What Is Committable

## What

Where a build's output lands, and which of those files a repository is expected to commit.

One serialisation is written to two paths: `knowledge-base/.graph/graph.json`, the active graph
every other skill reads, and `knowledge-base/.graph/graph.<backend>.json`, named for the backend
that produced it. Both are written by `persist_graph` (`graph_ops.py:2404`), which has exactly
one production caller — the contract's shared funnel — so no backend can opt out of either
file or name it differently.

Alongside them the build writes `knowledge-base/.graph/.gitignore`, listing `graph.json`,
`graph.*.json`, `classifications.json` and `docs.json` (`CACHE_IGNORED`, `graph_ops.py:245`).
`behavior.json` is not listed, and its absence is spelled out in the file's own header text.
`freya-behavior-graph` writes the same marker, and the two copies are held byte-identical
because whichever skill runs first wins.

`clear()` removes the active graph and every `graph.*.json` beside it, and deliberately keeps
`classifications.json` (`graph_ops.py:2351`).

A backend that produces its own scratch output is responsible for marking it: the graphify
backend writes `graphify-out/.gitignore` containing `*` after the tool has run
(`backend_graphify.py:386`), and stops rewriting it the moment its contents differ from the
text it wrote.

## Why

Two failures, one shape.

The first is the migration problem. Switching substrate replaces `graph.json`, which is the
baseline the switch was supposed to be measured against — so the diff that decides whether the
new backend is better is destroyed at the moment it is needed. The per-backend copy is what
survives the swap: same `timestamp`, `commit` and `substrate` block as the build that produced
it, sitting at its own path.

The second is that opting into a backend must not quietly make a cache committable. This has
gone wrong twice in this repository: `graph.<backend>.json` was added to `.graph/` with no
`.gitignore` entry and was staged by `git add -A`, and then `graphify-out/` appeared at the
*project root*, outside the only directory this toolkit's ignore rules reach, at roughly 9.3 KB
per file. Both were found by running `git add -A` on a fresh checkout, not by review.

`behavior.json` is the deliberate exception: its observed coverage comes from running the test
suite, so it cannot be rebuilt by re-reading source the way the graphs can, and committing it
is what gives a fresh clone a blast radius at all (ADR-017).

## Behavior

| Behavior | State | Verified by |
|----------|-------|-------------|
| BEH-038 A build writes the active graph and a copy named for the backend that produced it | proposed | `test_substrate.py#TestPerBackendArtifacts.test_a_build_writes_the_per_backend_artifact` (unittest) |
| BEH-039 Every regenerable graph artifact a build writes is gitignored, and behavior.json deliberately is not | proposed | `test_substrate.py#TestPerBackendArtifacts.test_the_per_backend_artifact_is_gitignored` (unittest) |
| BEH-040 The graphify backend marks its own output directory uncommittable, and leaves a hand-edited marker alone | proposed | `test_backend_graphify.py#TestAgainstTheRealBinary.test_the_output_directory_is_marked_not_committable` (unittest) |

BEH-039's second half — that `behavior.json` stays tracked — is pinned separately by
`test_substrate.py#TestPerBackendArtifacts.test_behavior_json_is_still_not_ignored` and by
`test_substrate.py#TestTheTwoCacheGitignoreWritersAgree.test_behavior_json_is_ignored_by_neither`.
BEH-040's hand-edit half is
`test_backend_graphify.py#TestAgainstTheRealBinary.test_a_hand_edited_marker_is_left_alone`.
Both of BEH-040's tests are skipped when the `graphify` binary is not installed, so on a
machine without it this behavior is unverified rather than green — worth knowing before
treating it as covered.

## Intentional Design Decisions

### Nothing in the toolkit reads the per-backend copy

**Decision**: `graph.<backend>.json` is written on every build and read by nothing.
`backend_graph_path` has one non-test caller and it is the write. There is no `--compare`
subcommand, and neither backend warm-starts from a copy it wrote earlier — both detect that
the *active* graph came from someone else and force a full rebuild instead
(`graph_ops.py:2092`–`:2100`, `backend_graphify.py:362`).

**Rationale**: ADR-028 records the decision and states this half of it plainly: what the
artifact buys is a preserved baseline on disk, not an automated comparison. The diff is run by
hand.

**Security Scan Note**: A write-only file, and a `backend_graph_path` helper with a single
caller, will read as dead code or an incomplete feature. It is neither. Removing the write
would silently remove the ability to evaluate a substrate migration, which is the guarantee
ADR-028 exists for.

### One `.graph/` artifact is committed on purpose

**Decision**: `behavior.json` is excluded from the cache `.gitignore` and is expected in
version control, while every other file in the same directory is ignored.

**Rationale**: ADR-017. It is the only artifact that cannot be reconstructed by re-reading
source, because its coverage fingerprints come from executing tests.

**Security Scan Note**: A committed generated file inside an otherwise-ignored cache directory
is intentional and is asserted against the literal ignore strings, not just the intent. Do not
"tidy" it by adding `behavior.json` or a blanket `*` to `knowledge-base/.graph/.gitignore` —
the blanket form is explicitly rejected by a test.

### A backend writes into a directory it does not own, once

**Decision**: `_mark_output_ignored` creates `graphify-out/.gitignore` with `*` in it, after
the external tool has created the directory. If the file already exists and its contents are
not the exact text this backend writes, it is left untouched. Every failure to write it is
swallowed (`backend_graphify.py:386`–`:406`).

**Rationale**: `graphify-out/` is the external tool's regenerable output at the project root,
where nothing else this toolkit writes can reach it. The wildcard rather than a filename list
is deliberate: the filenames belong to a tool nobody here controls, and enumerating them is
precisely how the previous instance of this bug happened. A project that has deliberately
edited the marker should not have that undone on every build, and a cache marker is not worth
failing a build over — the graph is the product.

**Security Scan Note**: "Tool writes a `.gitignore` containing `*` into the working tree" and
"exception handler that ignores all `OSError`" are both real patterns worth flagging in
general. Here they are the decision. The scope is one file in one generated directory, and it
is never rewritten over a human's version.

## Related Specs

- [SPEC-007: Substrate Backend Selection](./SPEC-007-substrate-backend-selection.md) — which
  backend's name ends up in the filename
- [SPEC-009: Unmapped Source Census](./SPEC-009-unmapped-source-census.md) — the block written
  into both artifacts before they are persisted

## Change History

| Date | Change | Reason |
|------|--------|--------|
| 2026-08-21 | Initial spec, inferred from code and tests | Brownfield scan (`freya-spec-manager bootstrap`) |

---

*Certainty 80. ADR-028 states the two-file rule, the gitignore placement and the
nothing-reads-it consequence directly, and the code carries regression comments naming the two
occasions a generated tree became committable — so the intent is well evidenced. Lower than
SPEC-007 because two of the three behaviors are only observable through a test that is skipped
without the external binary, and because `--clear` removing both artifacts is a fourth real
behavior of this spec that has a passing test
(`test_substrate.py#TestClearRemovesEveryArtifact.test_clear_removes_the_per_backend_copy_too`)
and no `BEH-` id allocated to it in this scan.*
