---
id: SPEC-005
title: Never a confidently empty answer
category: features
tags: [code-graph, query, impact, empty-answer, adr-005]
status: implemented
certainty: 85
created: 2026-08-21
updated: 2026-08-21
related_code:
  - skills/freya-code-graph/scripts/graph_ops.py
  - skills/freya-code-graph/scripts/substrate.py
intentional_decisions:
  - "An unknown file and an empty result are different answers, and only the first is a refusal"
  - "The four query surfaces deliberately answer in three different shapes, and one of them qualifies itself on stderr"
  - "Impact analysis over a missing graph returns exactly an empty object, with no caveat keys added"
behaviors:
  - behavior_id: BEH-024
    title: An empty but real dependents or dependencies answer is worded as an answer
    state: proposed
    level: integration
    adapter: unittest
    entry: skills/freya-code-graph/scripts/graph_ops.py
    locator: skills/freya-code-graph/scripts/test_graph_ops.py#TestSummaryFormatIsWhatIsDocumented.test_an_empty_answer_is_not_reported_as_a_missing_graph
  - behavior_id: BEH-025
    title: A query about a file the graph has never indexed exits non-zero and names it
    state: proposed
    level: integration
    adapter: unittest
    entry: skills/freya-code-graph/scripts/graph_ops.py
    locator: skills/freya-code-graph/scripts/test_graph_ops.py#TestSummaryFormatIsWhatIsDocumented.test_an_empty_answer_is_not_reported_as_a_missing_graph
  - behavior_id: BEH-026
    title: Impact analysis names the input files it has never indexed instead of dropping them
    state: proposed
    level: component
    adapter: unittest
    locator: skills/freya-code-graph/scripts/test_graph_ops.py#TestImpactSaysWhenItHasNeverSeenAFile.test_an_unindexed_input_is_reported
  - behavior_id: BEH-027
    title: Impact analysis with no graph at all answers with exactly an empty object
    state: proposed
    level: integration
    adapter: unittest
    entry: skills/freya-code-graph/scripts/graph_ops.py
    locator: skills/freya-code-graph/scripts/test_graph_ops.py#TestUnmappedSourceCLI.test_impact_with_no_graph_is_still_exactly_empty
  - behavior_id: BEH-028
    title: Dependents and dependencies stay bare arrays and put their coverage caveat on stderr
    state: proposed
    level: integration
    adapter: unittest
    entry: skills/freya-code-graph/scripts/graph_ops.py
    locator: skills/freya-code-graph/scripts/test_graph_ops.py#TestUnmappedSourceCLI.test_dependents_stays_a_bare_array_and_says_so_on_stderr
---

# Never a confidently empty answer

## What

`--query`, `--impact`, `--dependents` and `--dependencies` are the four surfaces the graph
answers on. This spec covers what each of them says when the answer is small, empty, or
unavailable — which is the case that carries the risk, because every one of those looks
identical to "I have never seen this file" unless the surface takes care to distinguish them.

Three distinctions are held apart on purpose:

- **empty vs unknown.** A file that genuinely has no dependents gets a stated answer and exit
  0. A file the graph has never indexed is a refusal — the API returns `None`, the CLI writes
  `File not found in graph` to stderr and exits non-zero.
- **partial vs complete.** `--impact` accepts several inputs at once and reports the ones it
  has never indexed in `not_in_graph`, in the payload as well as on stderr, so a
  zero-blast-radius answer cannot be read as "nothing depends on this".
- **answered vs never ran.** `--impact` against a project with no graph answers with exactly
  `{}` and nothing else.

The wording is part of the behavior, not decoration. `Nothing depends on this file.` and
`This file imports nothing in the project.` are the two sentences an agent pattern-matches
on, and both replaced a message that claimed no cached graph existed.

## Why

ADR-005 is the origin: a resolver that could not resolve anything returned `[]` and every
consumer rode on nothing for months, because an empty blast radius looks exactly like a
complete one. The rule that came out of it — under-report certainty, never under-report scope —
is only meaningful if it survives all the way to the surface a caller reads. It had been
implemented at the repository level and, at each of these four surfaces, was reintroduced
one layer up at least three separate times: in `--impact`, which silently dropped unknown
inputs; in `--dependents`, which conflated a missing node with an empty set; and in
`format_summary`, which reported a real empty answer as a missing graph.

The consumers here are mostly other skills, not people. `wrap-up` calls `--impact`;
`drift.py` and `run_behaviors.py` call `--impact` and `--dependencies` with `capture_output`
and read only stdout. That is why the distinctions have to live in the payload and the exit
code, and why the one caveat that cannot fit in the payload is deliberately routed to stderr
instead of being wedged in.

## Behavior

| Behavior | State | Verified by |
|----------|-------|-------------|
| BEH-024 An empty but real dependents or dependencies answer is worded as an answer | proposed | `test_graph_ops.py#TestSummaryFormatIsWhatIsDocumented.test_an_empty_answer_is_not_reported_as_a_missing_graph` (unittest) |
| BEH-025 A query about a file the graph has never indexed exits non-zero and names it | proposed | `test_graph_ops.py#TestSummaryFormatIsWhatIsDocumented.test_an_empty_answer_is_not_reported_as_a_missing_graph` (unittest) |
| BEH-026 Impact analysis names the input files it has never indexed instead of dropping them | proposed | `test_graph_ops.py#TestImpactSaysWhenItHasNeverSeenAFile.test_an_unindexed_input_is_reported` (unittest) |
| BEH-027 Impact analysis with no graph at all answers with exactly an empty object | proposed | `test_graph_ops.py#TestUnmappedSourceCLI.test_impact_with_no_graph_is_still_exactly_empty` (unittest) |
| BEH-028 Dependents and dependencies stay bare arrays and put their coverage caveat on stderr | proposed | `test_graph_ops.py#TestUnmappedSourceCLI.test_dependents_stays_a_bare_array_and_says_so_on_stderr` (unittest) |

BEH-024 and BEH-025 are two scenarios of one existing test — the empty-but-real answer and
the unknown-file refusal are asserted side by side there, because the test's point is that
they differ. They are recorded separately because they are separately observable and a future
change could break either alone.

`--query` has no row of its own here. Its shape (edge objects, not paths) is pinned by
`test_graph_ops.py#TestEdgesAreObjects.test_node_queries_still_answer_in_paths` and
`test_graph_ops.py#TestUnmappedSourceCLI.test_query_keeps_its_edge_objects`, and the guarantee
belongs to ADR-021 rather than to this spec.

## Intentional Design Decisions

### `None` is not the empty set

**Decision**: `get_dependents` and `get_dependencies` return `None` when the graph cannot
answer — no cached graph, or a path that is not a node — and an empty `set()` when the answer
is genuinely empty. `main()` maps `None` onto `sys.exit(1)`, so an unknown path is a non-zero
exit with a stderr line rather than an empty array on stdout. `--impact` keeps exit 0 and
reports the same fact structurally, in `not_in_graph`, because it takes many inputs and some
of them may be known.

**Rationale**: the general rule is ADR-005's, and it is not restated here. What is specific
to this surface is who pays for a violation: `run_behaviors` treats an empty closure as a real
answer and writes a one-file fingerprint into the *committed* `behavior.json`, which then
narrows every later blast radius in the repository.

**Security Scan Note**: the non-zero exit on an unknown path is the designed outcome of a
successful run, not an error path — do not "fix" it to return `[]` for symmetry with the
empty answer. Equally, a caller that reads `[]` from `--dependents` as "unknown file" is
reading it wrong; `[]` means the graph knows this file and nothing imports it.

### Three shapes across four surfaces, on purpose

**Decision**: `--query` answers with edge objects carrying kind and provenance; `--impact`
answers with an object of path sets; `--dependents` and `--dependencies` answer with bare JSON
arrays of paths and put their coverage caveat on stderr rather than in the payload.

**Rationale**: recorded in ADR-021 (edges vs paths) and ADR-029 (why the two bare-array
surfaces qualify themselves on stderr and are not wrapped in an envelope). Both records also
state the measured consequence of unifying the shapes, so it is not repeated here.

**Security Scan Note**: the asymmetry is deliberate and load-bearing. `run_behaviors`
validates `--dependencies` with `isinstance(data, list)` and routes everything to
`coverage: unknown` otherwise, which takes a repository-wide gate green over zero behaviors —
so wrapping these two surfaces in an object to make the API "consistent" fails *closed*, not
loudly. Diagnostics written to stderr while stdout stays machine-readable is intended
separation of channels, not stray debug output.

### An impact answer over a missing graph is exactly `{}`

**Decision**: when there is no cached graph, `get_impact` returns an empty dict and the caveat
keys that every populated answer carries are deliberately *not* added to it.

**Rationale**: `drift.py` uses the presence of `all_affected` as its signal that the graph
actually ran. An extra key in this branch flips every drift run to `changed-only` at exit 0
with nothing going red — the failure is silent and repository-wide.

**Security Scan Note**: the branch that returns `{}` while its sibling returns a fully
annotated object is not an inconsistency to normalise. It is a sentinel with a named consumer.

## Certainty

85. The distinctions above are stated explicitly in ADR-005 and ADR-029, restated in the
docstrings of every function that implements them, and each behavior has a test that asserts
the observable outcome — including the exact sentences. Not higher, because these records are
inferred from the implementation rather than authored: in particular the two sentences in
BEH-024 are pinned by a test but were never specified anywhere as product wording, so whether
their exact text is intent or an artifact of the fix is a judgement a human still owes.

## Related Specs

- [SPEC-004: Building and refreshing the dependency graph](./SPEC-004-code-graph-build-and-update.md)
- [SPEC-006: Transitive traversal and clearing the graph cache](./SPEC-006-code-graph-traversal-and-cache-clear.md)

## Change History

| Date | Change | Reason |
|------|--------|--------|
| 2026-08-21 | Initial spec, inferred from code and tests | Brownfield scan of the code-graph query surface |
