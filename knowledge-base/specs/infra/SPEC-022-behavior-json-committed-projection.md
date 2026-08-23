---
id: SPEC-022
title: behavior.json is a committed projection, and a rebuild only changes it when something changed
category: infra
tags: [behavior-layer, behavior-graph, artifacts, byte-stability, merge-by-trust, adr-017, adr-006]
status: implemented
certainty: 80
created: 2026-08-21
updated: 2026-08-21
related_code:
  - skills/freya-behavior-graph/scripts/behavior_graph.py
  - skills/freya-behavior-runner/scripts/run_behaviors.py
intentional_decisions:
  - "One generated JSON file inside a cache directory is deliberately tracked while its neighbours are ignored"
  - "A rebuild that measured nothing rewrites the file with the previous run's data rather than with what it just saw"
  - "Sorting happens only at the write, not in any of the producers that feed it"
  - "A proposed behavior is deliberately invisible to the graph, however many of them a scan produced"
behaviors:
  - behavior_id: BEH-106
    title: A rebuild that changes nothing produces a byte-identical behavior.json
    state: proposed
    level: component
    adapter: unittest
    locator: skills/freya-behavior-graph/scripts/test_behavior_graph.py#WriteBehaviorJsonGitignoreTest.test_two_writes_of_the_same_content_are_byte_identical
  - behavior_id: BEH-107
    title: A rebuild after a red test drops that behavior's stored exercised-code edges
    state: proposed
    level: unit
    adapter: unittest
    locator: skills/freya-behavior-graph/scripts/test_behavior_graph.py#MergeFingerprintTest.test_test_failed_invalidates_even_observed_prior
  - behavior_id: BEH-108
    title: A rebuild whose run could not measure anything keeps the fingerprint already committed
    state: proposed
    level: component
    adapter: unittest
    locator: skills/freya-behavior-graph/scripts/test_behavior_graph.py#BuildTest.test_build_preserves_prior_observed_on_unknown
  - behavior_id: BEH-109
    title: Proposed behaviors are never projected into behavior.json; accepted and confirmed are
    state: proposed
    level: component
    adapter: unittest
    locator: skills/freya-behavior-graph/scripts/test_behavior_graph.py#ProjectBehaviorsTest.test_projects_accepted_and_confirmed_behaviors
  - behavior_id: BEH-110
    title: A behavior.json that cannot be read says so instead of answering as an empty graph
    state: proposed
    level: component
    adapter: manual
    locator: skills/freya-behavior-graph/scripts/test_behavior_graph.py#LoadBehaviorJsonTest.test_an_unreadable_file_is_not_silently_an_empty_graph
---

# behavior.json is a committed projection, and a rebuild only changes it when something changed

## What

`knowledge-base/.graph/behavior.json` is the `BEHAVIOR → TEST → CODE` projection that
`freya behavior-graph --build` writes. It is generated — never hand-edited — from three inputs:
the `behaviors:` frontmatter of every spec, the fingerprints `behavior-runner` returns for
this run, and whatever the file already contained.

Two properties are the reason this spec exists.

**It is tracked by git, unlike every other file beside it.** `graph.json`, `graph.*.json`,
`classifications.json` and `docs.json` are a parse cache and are ignored by name;
`behavior.json` is not, because its `source: observed` edges come from running a suite under
coverage and cannot be recovered by re-reading source.

**A rebuild is therefore expected to produce no diff unless something actually changed.** That
is a property of the writer, not of the producers: `write_behavior_json` sorts every
`exercises` list by path and the whole `behaviors` mapping by id before serialising, so neither
the code graph's set-derived import closure nor `os.walk`'s dirent order can leak into a
tracked file. What *does* change the file is a change in measurement, and the merge decides
which measurement wins: `observed` beats `static`, a red test invalidates what is stored, and
any other unmeasurable outcome leaves the previous fingerprint in place.

The projection is also selective. Only `accepted` and `confirmed` behaviors are projected —
a `proposed` behavior is invisible here no matter how many of them a brownfield scan wrote.

## Why

The blast-radius question the behavior layer exists to answer is only as good as the edges it
is asked over, and the precise half of those edges is not derivable. A fresh clone with no
`behavior.json` does not fail; it silently degrades to `static`/`unknown` and every later
"which behaviors does this change touch" answer comes back narrower than the truth, with
nothing on screen to say so. Committing the file is what stops that, and ADR-017 records the
decision and the alternatives.

Committing it, however, is only tolerable if it behaves like a source file in review. A
generated JSON that reorders itself on every build is the reason `graph.json` is *not*
committed — measured there at ten of ten differing entries being pure reordering. Since
`behavior.json` is read as a record of behavioural drift, a whole-file reordering diff is not
noise but a false alarm about the one thing the file is supposed to report.

The merge rules exist because the two ways of getting this wrong are both silent and exactly
opposite: always preserving means a red test keeps its green edges and the regression gate
never fires; always invalidating means one unsupported level wipes a good fingerprint. ADR-006
carries that reasoning and the `reason` discriminator that implements it.

## Behavior

| Behavior | State | Verified by |
|----------|-------|-------------|
| BEH-106 A rebuild that changes nothing produces a byte-identical behavior.json | proposed | `test_behavior_graph.py#WriteBehaviorJsonGitignoreTest.test_two_writes_of_the_same_content_are_byte_identical` (unittest) |
| BEH-107 A rebuild after a red test drops that behavior's stored exercised-code edges | proposed | `test_behavior_graph.py#MergeFingerprintTest.test_test_failed_invalidates_even_observed_prior` (unittest) |
| BEH-108 A rebuild whose run could not measure anything keeps the fingerprint already committed | proposed | `test_behavior_graph.py#BuildTest.test_build_preserves_prior_observed_on_unknown` (unittest) |
| BEH-109 Proposed behaviors are never projected into behavior.json; accepted and confirmed are | proposed | `test_behavior_graph.py#ProjectBehaviorsTest.test_projects_accepted_and_confirmed_behaviors` (unittest) |
| BEH-110 A behavior.json that cannot be read says so instead of answering as an empty graph | proposed | none — `adapter: manual`, gap |

BEH-106 is one guarantee with three tests behind it, because there are three producers that
could break it independently: `test_exercises_are_sorted_by_path` (the closure's order),
`test_the_behaviors_mapping_is_sorted_by_id` and `test_key_order_does_not_change_the_file` (the
spec walk's order), and the locator above, which asserts the end property against shuffled
input. Recorded as one behavior because "a no-op rebuild produces no diff" is what an operator
observes; the three tests are how it is held.

BEH-110 has **no test**, and it is the highest-value row here for that reason.
`load_behavior_json` catches `json.JSONDecodeError` and `OSError` and returns `{}`. Every
read path — Direction A, Direction B, `--covering`, `--surface`, and `regression_check` —
then behaves exactly as it would for a project that has never built a graph: `--check`
computes no affected behaviors, runs nothing, and exits 0. A truncated file from an
interrupted write, or a badly resolved merge conflict, therefore turns the gate green rather
than red. The locator names where the test should live.

## Intentional Design Decisions

### One tracked file inside a directory of ignored ones

**Decision**: `knowledge-base/.graph/.gitignore` lists the regenerable artifacts by name and
deliberately omits `behavior.json`, which the repository is expected to commit.

**Rationale**: recorded in ADR-017, including why the blanket `*` it replaced was there and
why moving the file out of `.graph/` was rejected. Not restated. Note for readers arriving
from ADR-004, which describes `behavior.json` as living "in the git-ignored
`knowledge-base/.graph/`": ADR-017 supersedes that clause; the directory is no longer
ignored wholesale.

**Security Scan Note**: a generated JSON artifact tracked in git, inside a directory whose
`.gitignore` sits next to it, is the intended arrangement and not a leaked build output. The
file contains project-relative paths, function names and a commit sha; it is not expected to
contain secrets, and a scanner that finds one there has found a real problem in a producer.

### A rebuild that rewrites the file with the *previous* run's data

**Decision**: when a run returns `coverage: unknown` for any reason other than `test-failed`,
the merge writes the prior fingerprint back out. The freshly-measured "nothing" is discarded.

**Rationale**: ADR-006 §"the `reason` discriminator was added mid-flight, and it is
load-bearing" gives the full argument, including the two opposite silent failures. What is
worth adding at this file's level: the preserved value is written with the *new* commit in
`data["commit"]`, so a preserved edge's own `freshness` field is older than the file's commit.
That skew is deliberate — the edge records when it was measured, not when it was written.

**Security Scan Note**: this looks like a cache that fails to invalidate, and it is not one.
The one incoming result that *does* invalidate is a failed test. Do not "fix" the preserve
branch to clear stale data; that removes the regression gate's memory of what a behavior
exercises, which is what selects the behaviors to re-run.

### Sorting lives at the write, not in the producers

**Decision**: `_stable` is applied inside `write_behavior_json`, the single choke point every
producer passes through, rather than each producer emitting sorted output.

**Rationale**: ADR-017 records this as a deliberate choice over sorting in the producers —
one sort fixes determinism for the vitest path, the static closure and any future coverage
adapter at once. The cost is that a caller who serialises the return value of `build()` by
hand, instead of reading the file, gets unsorted data; nothing in the toolkit does.

**Security Scan Note**: not a defensive-copy or normalisation omission in the producers. The
invariant is asserted at the boundary that has consequences (the tracked file), not at every
internal one.

### Proposed behaviors are not in the graph at all

**Decision**: `project_behaviors` admits only `accepted` and `confirmed`. A brownfield scan
that writes a hundred `proposed` candidates changes `behavior.json` by exactly nothing.

**Rationale**: ADR-003 (state is the trust signal) and ADR-007 (bootstrap as proposed, drain
lazily) both bear on this and are not restated. The consequence specific to this file: the
size of the proposed corpus has no effect on build time, on the committed artifact, or on any
blast-radius answer, which is what makes an aggressive brownfield scan safe to run.

**Security Scan Note**: an empty `behaviors` object in a project that visibly has specs is not
a broken build. It means nothing has been accepted or confirmed yet.

## Certainty

80. ADR-017 states the committed-ness and the byte-stability precondition explicitly, ADR-006
states the merge order, and each of BEH-106 through BEH-109 has a test asserting the observable
outcome with a docstring naming the failure it prevents. Held below that because these records
are inferred from the implementation rather than authored, and two specifics are judgement a
human still owes: whether the `freshness`/`commit` skew described above is intended or merely
tolerated, and whether BEH-110's silent `{}` is a deliberate degradation or the gap it looks
like.

## Related Specs

- [SPEC-008: Code Graph Artifacts and What Is Committable](../infra/SPEC-008-code-graph-artifacts.md) — owns the `.graph/.gitignore` marker itself, which both `code-graph` and `behavior-graph` write and which is held byte-identical between them
- [SPEC-023: Blast radius in both directions, and the uncovered-code audit](../features/SPEC-023-behavior-blast-radius-and-audits.md) — the queries served from this file
- [SPEC-024: What the behavior runner will execute, and what it refuses to guess](../features/SPEC-024-behavior-execution-dispatch.md) — the producer of the fingerprints merged here

## Change History

| Date | Change | Reason |
|------|--------|--------|
| 2026-08-21 | Initial spec, inferred from code and tests | Brownfield scan of the behavior layer |
