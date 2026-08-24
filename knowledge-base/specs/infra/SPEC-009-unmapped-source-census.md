---
id: SPEC-009
title: The Unmapped-Source Census
category: infra
tags: [substrate, code-graph, coverage, honesty, polyglot, agent-surface]
status: implemented
certainty: 82
created: 2026-08-21
updated: 2026-08-21
related_code:
  - skills/freya-code-graph/scripts/substrate.py
  - skills/freya-code-graph/scripts/graph_ops.py
  - skills/freya-code-graph/scripts/backends.py
  - skills/freya-spec-manager/scripts/project_shape.py
intentional_decisions:
  - "The census is a caveat, never a refusal — it changes no exit code and takes no gate red"
  - "The extension list is closed-world, so a language nobody listed is reported nowhere"
  - "Script extensions are suppressed unless they outnumber the graph (two-tier materiality)"
  - "The key is absent, not empty, on a repository the backend reads completely"
  - "The census re-derives the build's own scope rule instead of reading the artifact's recorded exclusions"
behaviors:
  - behavior_id: BEH-041
    title: A build's answer names what the backend could not read — how many files, which extensions, and which directories to search instead
    state: proposed
    level: integration
    adapter: unittest
    entry: skills/freya-code-graph/scripts/graph_ops.py
    locator: skills/freya-code-graph/scripts/test_graph_ops.py#TestUnmappedSourceCLI.test_a_build_names_what_it_could_not_read
  - behavior_id: BEH-042
    title: A repository the backend reads completely pays nothing — the caveat key is absent from the answer, while the artifact still records that the census ran and found nothing
    state: proposed
    level: integration
    adapter: unittest
    entry: skills/freya-code-graph/scripts/graph_ops.py
    locator: skills/freya-code-graph/scripts/test_graph_ops.py#TestUnmappedSourceCLI.test_a_clean_repo_pays_nothing_at_all
  - behavior_id: BEH-043
    title: Unread program source is reported however little of it there is, while a script extension is reported only when it outnumbers the graph
    state: proposed
    level: unit
    adapter: unittest
    locator: skills/freya-code-graph/scripts/test_substrate.py#TestUnmappedCensus.test_tier_one_is_reported_however_small
  - behavior_id: BEH-044
    title: A census that could not run says so, and is never reported as a zero
    state: proposed
    level: unit
    adapter: unittest
    locator: skills/freya-code-graph/scripts/test_substrate.py#TestUnmappedCensus.test_a_census_that_could_not_run_says_so
  - behavior_id: BEH-045
    title: A build that has already fallen back to the floor does not recommend the backend it just failed to use
    state: proposed
    level: integration
    adapter: manual
    entry: skills/freya-code-graph/scripts/graph_ops.py
    locator: skills/freya-code-graph/scripts/test_graph_ops.py#TestUnmappedSourceCLI.test_a_degraded_build_does_not_recommend_the_backend_it_lost
---

# The Unmapped-Source Census

## What

Every answer the code graph gives says what it could not read.

Each build or update that writes a graph performs one pruned tree walk over the project and
records the result at `graph["substrate"]["unmapped_source"]` (`graph_ops._census`,
`graph_ops.py:2823`): how many in-scope source files the running backend does not read, which
extensions they are, and which directories to grep instead. `--build` and `--update` carry the
whole block in their JSON answer, including a prose `advice` sentence and — on a run that did
not degrade — a `readable_by` recommendation naming a backend that would read them. `--query`
and `--impact` carry a structured digest of `files`, `extensions`, `directories` plus
truncation markers. `--dependents` and `--dependencies` keep their bare arrays and say the same
thing on stderr.

What counts as unread source is a two-tier model (`substrate.py:867` and `:894`). Tier one is
program source a backend could reasonably be expected to graph, and any of it is material.
Tier two is script and schema extensions — shell, PowerShell, SQL, batch — which are material
only when they outnumber both the graphed file count and a floor of two
(`SCRIPT_MATERIALITY_FLOOR`, `substrate.py:902`). Anything on neither list is never reported.

Three states are expressible and distinguishable: a populated block, `{"files": 0}` meaning
the census ran and found nothing, and `{"files": null, "error": …}` meaning it could not run.
Only the first reaches an answer — `unmapped_digest` returns `None` for the second
(`substrate.py:1054`), so the key is absent rather than empty.

## Why

ADR-005 established that the graph must never answer "nothing" when it means "I don't know",
and that was implemented at the repository level: a Java repo will not classify itself
greenfield. It was never implemented at the *answer* level, and the two are different claims.
"3 dependents" and "3 dependents, and I could not read a fifth of this repo" are not the same
sentence, and the tool said the first when it meant the second.

The consumer is the agent driving the toolkit, not a person. Builds run with no keyboard
attached almost every time — `--non-interactive` auto-enables whenever stdin is not a TTY,
which is every agent-driven run and every wrap-up — so a printed warning lands nowhere. The
signal has to ride in the machine-readable answer.

The materiality rule is the whole design rather than a refinement of it. A caveat that fires on
every repository with a README is one an agent learns to skip inside a single context window,
after which it costs tokens forever and changes no decision; a caveat that stays silent on a
Java service is the confidently-empty answer this exists to stop. Both edges are load-bearing,
and both have been measured wrong at least once: a census consulting only gitignore-style
patterns reported 96 unread files on this repository of which 68 were deliberately out of
scope, a 71% phantom.

## Behavior

| Behavior | State | Verified by |
|----------|-------|-------------|
| BEH-041 A build's answer names what the backend could not read — how many files, which extensions, and which directories to search instead | proposed | `test_graph_ops.py#TestUnmappedSourceCLI.test_a_build_names_what_it_could_not_read` (unittest) |
| BEH-042 A repository the backend reads completely pays nothing — the caveat key is absent from the answer, while the artifact still records that the census ran and found nothing | proposed | `test_graph_ops.py#TestUnmappedSourceCLI.test_a_clean_repo_pays_nothing_at_all` (unittest) |
| BEH-043 Unread program source is reported however little of it there is, while a script extension is reported only when it outnumbers the graph | proposed | `test_substrate.py#TestUnmappedCensus.test_tier_one_is_reported_however_small` (unittest) |
| BEH-044 A census that could not run says so, and is never reported as a zero | proposed | `test_substrate.py#TestUnmappedCensus.test_a_census_that_could_not_run_says_so` (unittest) |
| BEH-045 A build that has already fallen back to the floor does not recommend the backend it just failed to use | proposed | **no test** — `test_graph_ops.py#TestUnmappedSourceCLI.test_a_degraded_build_does_not_recommend_the_backend_it_lost` is where one belongs (manual) |

BEH-042's artifact half is `test_graph_ops.py#TestUnmappedSourceCLI.test_the_clean_sentinel_reaches_the_artifact`;
BEH-043's suppression half is `test_substrate.py#TestUnmappedCensus.test_tier_two_below_the_floor_is_dropped`
and `…test_tier_two_the_graph_dominates_is_dropped`, with `…test_tier_two_that_dominates_is_kept`
holding the other edge. One behavior each, several tests, because a materiality rule is only
worth having if both directions hold.

BEH-045 is the gap. `backends.readable_by` is deliberately availability-blind — it answers "is
there a remedy at all?", which matters most on a machine that has never installed one — and
`_census` suppresses it on a degraded run (`graph_ops.py:2846`–`:2853`) so the answer does not
recommend `--use graphify` in the same breath as "graphify is unavailable". Nothing asserts
that suppression: no test in this repository constructs a degraded build and inspects the
census block. A regression would produce advice that contradicts the stderr line directly above
it, at exit 0, on the surface an agent acts from.

## Intentional Design Decisions

### The census is a caveat, never a refusal

**Decision**: Nothing declines to answer, changes an exit code, or takes a gate red because of
the census. A build over a repository the backend can read a fifth of exits 0 and writes the
graph.

**Rationale**: ADR-029. The rule is written into `freya-behavior-runner/scripts/run_behaviors.py`
as a comment beside the `degraded_from` refusal it must specifically *not* join, and pinned by
`test_a_repo_with_unmapped_files_still_fingerprints_static`.

**Security Scan Note**: "The tool detects it cannot read 20% of the repository and proceeds
anyway" is the design, not missing error handling. The obligation discharged here is
disclosure, not refusal — the failure mode being prevented is the opposite one, a tool that
goes quiet or hard-fails and takes the whole workflow with it.

### The extension list is closed-world, and a language nobody listed goes unreported

**Decision**: `SOURCE_EXTENSIONS` and `SCRIPT_EXTENSIONS` are fixed frozensets. An extension on
neither list produces silence, however many files carry it
(`test_substrate.py#TestUnmappedCensus.test_unlisted_extensions_are_never_reported`).

**Rationale**: ADR-029 accepts this explicitly as a real, narrower instance of the hole the
census closes. Silence is the right default for a signal whose only value is being believed,
and an open-world rule made `.md`, `.json` and `.png` 71% of the old disk walk.

**Security Scan Note**: A hardcoded allow-list of file extensions with no fallback branch is
intentional and is not an oversight to be "completed". The correct fix for a missing language
is a new entry in the frozenset, not a default case.

### The census re-derives the build's scope rule instead of reading the recorded exclusions

**Decision**: `_unmapped_source_paths` (`graph_ops.py:2807`) filters using
`CodeGraph._should_exclude` plus the caller's `Exclusions` — the two layers `build()` itself
applies — rather than the `substrate.exclusions` block recorded in the artifact.

**Rationale**: The recorded set is a strict subset. It carries no `always_exclude_files`, no
`top_level_exclude_dirs` and no `always_exclude_dirs` below depth two, and on a fresh project
it is computed before directory classification has run — so it is nearly empty on exactly the
bootstrap build this feature exists to serve.

**Security Scan Note**: This looks like duplicated exclusion logic that has drifted from the
recorded metadata, and a reviewer may propose consolidating on the artifact's block. That
change re-introduces the 71% false-positive rate measured before it. The seam is guarded by
`test_graph_ops.py#TestUnmappedSourceCLI.test_the_caller_s_exclusions_reach_the_census_through_the_runner`.

### Absent, not empty, when there is nothing to say

**Decision**: `unmapped_digest` returns `None` for a clean census, and `_answer_caveats`
returns `{}`, so `--query` and `--impact` on a monoglot repository emit exactly the key set
they emitted before this feature existed. The `{"files": 0}` sentinel is written to the
artifact only.

**Rationale**: ADR-019's discipline, enforced in one place rather than at each of the four
surfaces. The sentinel is what lets `project_shape` tell "censused and clean" from "this graph
predates the census" without a schema bump that would force a rebuild everywhere and churn
every committed behaviour fingerprint.

**Security Scan Note**: The asymmetry — a field present in the persisted artifact and absent
from the API response computed from it — is deliberate. `test_a_clean_repo_pays_nothing_at_all`
asserts the answer's key set exactly rather than asserting an absence, so adding a
harmless-looking empty `unmapped_source: {}` to the clean path is a test failure by design.

## Related Specs

- [SPEC-007: Substrate Backend Selection](./SPEC-007-substrate-backend-selection.md) — which
  backend's blind spots are being censused, and the degradation that suppresses the remedy
- [SPEC-008: Code Graph Artifacts](./SPEC-008-code-graph-artifacts.md) — the artifacts the
  census block is written into

## Change History

| Date | Change | Reason |
|------|--------|--------|
| 2026-08-21 | Initial spec, inferred from code and tests | Brownfield scan (`freya-spec-manager bootstrap`) |

---

*Certainty 82. ADR-029 states the mechanism, the two-tier rule, the absent-not-empty
discipline and the never-a-refusal rule directly, and the code carries measured numbers for
every threshold rather than round ones — the materiality floor of 2 and the extension cap of 8
are both documented as tuned against specific real repositories. Every reported behavior above
has a test whose docstring names the failure it prevents. Held at 82 rather than higher because
BEH-045 is a real branch with no coverage at all, which means at least one of this feature's
stated guarantees is currently declared and unenforced.*
