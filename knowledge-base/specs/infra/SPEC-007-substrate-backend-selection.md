---
id: SPEC-007
title: Substrate Backend Selection
category: infra
tags: [substrate, code-graph, backend-selection, configuration, portability, degradation]
status: implemented
certainty: 85
created: 2026-08-21
updated: 2026-08-21
related_code:
  - skills/freya-code-graph/scripts/backends.py
  - skills/freya-code-graph/scripts/settings.py
  - skills/freya-code-graph/scripts/substrate.py
  - skills/freya-code-graph/scripts/graph_ops.py
  - skills/freya-code-graph/scripts/backend_graphify.py
intentional_decisions:
  - "`auto` runs the floor and never shops for a wider installed backend"
  - "A backend that is named but unusable degrades to the floor at exit 0 instead of failing the build"
  - "The first build carries the machine-level default into the project's committed settings.json"
  - "There is no permission list — naming a backend in settings.json is the whole opt-in"
behaviors:
  - behavior_id: BEH-031
    title: An unconfigured project builds on the stdlib floor even when a wider backend is installed
    state: proposed
    level: component
    adapter: unittest
    locator: skills/freya-code-graph/scripts/test_substrate.py#TestBackendSelection.test_auto_is_the_floor_even_when_another_backend_would_read_more
  - behavior_id: BEH-032
    title: A project that names a backend gets that backend
    state: proposed
    level: component
    adapter: unittest
    locator: skills/freya-code-graph/scripts/test_substrate.py#TestBackendSelection.test_a_named_backend_is_honoured
  - behavior_id: BEH-033
    title: A named backend whose binary is absent degrades to the floor and the build still succeeds, naming what it lost
    state: proposed
    level: component
    adapter: unittest
    locator: skills/freya-code-graph/scripts/test_substrate.py#TestBackendSelection.test_an_unavailable_backend_degrades_to_the_floor_and_says_so
  - behavior_id: BEH-034
    title: A degraded build records the backend it lost in the graph artifact, not only on stderr
    state: proposed
    level: component
    adapter: unittest
    locator: skills/freya-code-graph/scripts/test_substrate.py#TestDegradationReachesTheArtifact.test_a_degraded_build_records_it_in_the_graph
  - behavior_id: BEH-035
    title: An installed backend that fails the contract check is refused before it runs, and the refusal is recorded as a degradation
    state: proposed
    level: component
    adapter: unittest
    locator: skills/freya-code-graph/scripts/test_substrate.py#TestDegradationReachesTheArtifact.test_a_backend_that_fails_conformance_is_recorded_as_a_degradation
  - behavior_id: BEH-036
    title: Under auto, an installed wider backend is named with the files it would add and the runnable commands to switch — and nothing is said when there is nothing to offer
    state: proposed
    level: component
    adapter: unittest
    locator: skills/freya-code-graph/scripts/test_substrate.py#TestBackendSelection.test_auto_says_what_it_is_leaving_on_the_table
  - behavior_id: BEH-037
    title: A project's own answer outranks the machine-level default, which outranks the floor
    state: proposed
    level: unit
    adapter: unittest
    locator: skills/freya-code-graph/scripts/test_substrate.py#TestTheMachineLevelDefault.test_a_project_that_has_decided_wins
---

# Substrate Backend Selection

## What

Which parser produces this project's code graph, and how a caller finds out.

`freya-code-graph` resolves exactly one backend per build. Two are registered:
`homegrown`, the stdlib-only resolver that ships with the toolkit and is therefore always
installable, and `graphify`, an external tree-sitter tool. Resolution reads
`knowledge-base/settings.json` (the project's answer), then `~/.freya/settings.json` (the
machine's), and falls back to the floor when neither has decided. A name that resolves to a
backend which is not on the machine, cannot be constructed, or does not satisfy the substrate
contract is replaced by the floor — the build continues and produces a graph.

The scope of this spec is *selection and its visibility*: which backend runs, whether the run
was what the project asked for, and where a reader can see the answer afterwards. What a
backend must provide is ADR-018; who writes the resulting graph to disk is ADR-020 and
SPEC-008; what the chosen backend could not read is SPEC-009.

The visible surface is three things: the backend's own graph artifact
(`knowledge-base/.graph/graph.<backend>.json`), the `substrate` block inside every graph
(`backend`, `coverage`, and `degraded_from` / `degraded_reason` when a fallback happened), and
one stderr line per run whenever the backend that ran was not the plain floor.

## Why

A code graph that is thin because the repository is small and a code graph that is thin
because the parser could not read the language are the same JSON. Every downstream answer —
blast radius, docs impact, behaviour fingerprints, the security scan's incremental scope — is
computed from that file, so a silent substitution silently narrows all of them at once.
Selection therefore has to be recorded rather than inferred, and it has to be recorded *in
the artifact*, because the stderr of the run that produced it is gone by the time anyone reads
the graph.

The second pressure is the one that produced the floor: the driving case for polyglot support
is a locked-down machine, which is exactly where a dependency cannot be installed. So the
toolkit must work with nothing installed and nothing configured, and every fallback path has
to land somewhere rather than raising.

## Behavior

| Behavior | State | Verified by |
|----------|-------|-------------|
| BEH-031 An unconfigured project builds on the stdlib floor even when a wider backend is installed | proposed | `test_substrate.py#TestBackendSelection.test_auto_is_the_floor_even_when_another_backend_would_read_more` (unittest) |
| BEH-032 A project that names a backend gets that backend | proposed | `test_substrate.py#TestBackendSelection.test_a_named_backend_is_honoured` (unittest) |
| BEH-033 A named backend whose binary is absent degrades to the floor and the build still succeeds, naming what it lost | proposed | `test_substrate.py#TestBackendSelection.test_an_unavailable_backend_degrades_to_the_floor_and_says_so` (unittest) |
| BEH-034 A degraded build records the backend it lost in the graph artifact, not only on stderr | proposed | `test_substrate.py#TestDegradationReachesTheArtifact.test_a_degraded_build_records_it_in_the_graph` (unittest) |
| BEH-035 An installed backend that fails the contract check is refused before it runs, and the refusal is recorded as a degradation | proposed | `test_substrate.py#TestDegradationReachesTheArtifact.test_a_backend_that_fails_conformance_is_recorded_as_a_degradation` (unittest) |
| BEH-036 Under auto, an installed wider backend is named with the files it would add and the runnable commands to switch — and nothing is said when there is nothing to offer | proposed | `test_substrate.py#TestBackendSelection.test_auto_says_what_it_is_leaving_on_the_table` (unittest) |
| BEH-037 A project's own answer outranks the machine-level default, which outranks the floor | proposed | `test_substrate.py#TestTheMachineLevelDefault.test_a_project_that_has_decided_wins` (unittest) |

BEH-036's silent half is separately pinned by
`test_substrate.py#TestBackendSelection.test_auto_stays_quiet_when_there_is_nothing_to_offer`;
one behavior, two tests, because the caveat is only worth having if both edges hold.

## Intentional Design Decisions

### `auto` deliberately does not pick the best available backend

**Decision**: With nothing configured, selection resolves to `homegrown` and stops. It does
not rank the installed backends against the repository and does not switch to a wider one it
finds on PATH, even when that backend demonstrably reads more of this project
(`backends.py:152`–`:183`). The scoring function that used to do this was deleted rather than
left unused, and its removal is recorded in a comment at `backends.py:106`.

**Rationale**: ADR-019. A substrate change is a migration, not a side effect of installing
something — and per ADR-028 it has to be diffable against the previous baseline before it is
trusted.

**Security Scan Note**: A scanner or reviewer noticing that a more capable parser is installed
and unused, or that `select()` has a comparison it never acts on, is looking at the decision,
not a bug. Do not "fix" `auto` to choose the widest backend.

### A backend that cannot run is a degradation, not a failure

**Decision**: Every path where the requested backend cannot be used — not on PATH, not a
registered name at all, raises on construction, fails `conformance_errors`, or throws
mid-build — falls back to the floor, finishes the build, and exits 0
(`backends.py:138`–`:150`, `graph_ops.py:3514`–`:3532`, `graph_ops.py:2759`). The only
non-recoverable case is the floor itself failing, which is re-raised.

**Rationale**: ADR-019. The floor is what the run would have used had nobody configured
anything, so a traceback is never the best available answer. The honesty requirement is
discharged by recording the fallback rather than by refusing to answer.

**Security Scan Note**: The broad `except Exception` handlers in `available_backends`,
`choose_backend` and `_run_or_degrade` are deliberate fail-open paths, not swallowed errors.
Each one writes `degraded_from` and a reason into the artifact. Flag them only if a path is
found that degrades *without* recording it — that is the actual defect class here, and it has
occurred once (`graph_ops.py:3520`).

### The first build writes the machine's answer into the project's committed settings

**Decision**: When a machine-level default exists and the project has not answered, the next
`--build` or `--update` writes that backend name into the project's
`knowledge-base/settings.json` and says so on stderr (`settings.seed_project_backend`,
`graph_ops._seed_from_machine_default`). A project with nothing configured and no machine
default has nothing written to it.

**Rationale**: ADR-019. Integration behaviours' static fingerprints are derived from the
code-graph closure and committed in `behavior.json`, so a backend left implicit means the same
commit produces a different committed artifact on two laptops, arriving as a diff that reads
like behaviour drift.

**Security Scan Note**: A tool writing a file into the repository during a read-shaped
operation is normally worth flagging. This one is intentional, is confined to
`knowledge-base/settings.json`, never overwrites an answer the project already gave (including
an explicit `auto`), validates the name against the registry before copying it, and is
non-fatal if the checkout is read-only.

### Naming a backend is the entire opt-in

**Decision**: There is no allow-list, capability flag or second confirmation. A name in a
settings file is sufficient authority to run that backend's binary as a subprocess
(`backends.py:113`–`:121`; `backend_graphify.py:434`).

**Rationale**: ADR-019 — a project that has written the name down has decided, and a second
permission list would only be a place for the two to disagree.

**Security Scan Note**: "Executes a binary named in a config file" is accurate and intended.
The mitigations that exist are that the name is validated against a closed registry at
`--use` time, that an unknown name degrades rather than being executed, and that
`conformance_errors` binds the actual call signature before the backend is invoked.

## Related Specs

- [SPEC-008: Code Graph Artifacts](./SPEC-008-code-graph-artifacts.md) — where the chosen
  backend's output is written, and what is committable
- [SPEC-009: Unmapped Source Census](./SPEC-009-unmapped-source-census.md) — what the chosen
  backend could not read

## Change History

| Date | Change | Reason |
|------|--------|--------|
| 2026-08-21 | Initial spec, inferred from code and tests | Brownfield scan (`freya-spec-manager bootstrap`) |

---

*Certainty 85. High because the behaviour is not merely implemented but argued: ADR-019 states
selection, precedence and the fallback rules explicitly and cites the same line numbers this
spec reads; `backends.py` carries a deleted-on-purpose comment where the rejected alternative
used to be; and every branch above has a test whose docstring names the decision. Held below
90 because these behaviors were inferred from the implementation rather than authored ahead of
it, and because the exact stderr wording is asserted only by substring — the facts are pinned,
the presentation is not.*
