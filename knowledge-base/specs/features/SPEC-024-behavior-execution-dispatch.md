---
id: SPEC-024
title: What the behavior layer runs, and what it refuses to invent
category: features
tags: [behavior-layer, behavior-runner, lifecycle, adapters, coverage-unknown, gherkin-scaffold, adr-003, adr-004, adr-006]
status: implemented
certainty: 80
created: 2026-08-21
updated: 2026-08-21
related_code:
  - skills/freya-behavior-runner/scripts/run_behaviors.py
  - skills/freya-behavior-graph/scripts/behavior_graph.py
  - skills/freya-spec-manager/scripts/adapters.py
intentional_decisions:
  - "Dispatch reads the lifecycle state before it reads the level or the adapter, so a confirmed behavior is unreachable rather than merely forbidden"
  - "The same non-gating rule is enforced twice, in two skills, on purpose"
  - "An adapter or level with no implemented path produces an explicit unknown rather than an empty pass"
  - "The generated Gherkin scaffold contains no real steps and no step definitions, by design and permanently"
behaviors:
  - behavior_id: BEH-116
    title: A confirmed behavior naming a unit test is still never executed
    state: proposed
    level: unit
    adapter: unittest
    locator: skills/freya-behavior-runner/scripts/test_run_behaviors.py#FingerprintBehaviorTest.test_confirmed_with_unit_adapter_is_still_not_executed
  - behavior_id: BEH-117
    title: A confirmed behavior cannot fail the regression gate even when handed a failed result
    state: proposed
    level: component
    adapter: unittest
    locator: skills/freya-behavior-graph/scripts/test_behavior_graph.py#ConfirmedDoesNotBlockOnTestFailedTest.test_confirmed_with_test_failed_does_not_block
  - behavior_id: BEH-118
    title: An accepted behavior at a level with no implemented path reports unknown and names the reason
    state: proposed
    level: unit
    adapter: unittest
    locator: skills/freya-behavior-runner/scripts/test_run_behaviors.py#FingerprintBehaviorTest.test_accepted_other_level_is_level_deferred
  - behavior_id: BEH-119
    title: A failed dependency-closure query produces unknown with a reason, not a one-file closure
    state: proposed
    level: unit
    adapter: unittest
    locator: skills/freya-behavior-runner/scripts/test_run_behaviors.py#StaticFingerprintTest.test_a_failed_graph_query_is_unknown_not_a_one_file_closure
  - behavior_id: BEH-120
    title: A generated Gherkin scaffold carries its tags and a scaffold marker, and placeholder steps only
    state: proposed
    level: unit
    adapter: unittest
    locator: skills/freya-spec-manager/scripts/test_adapters.py#TestGherkinScaffold.test_no_real_steps_only_placeholders
---

# What the behavior layer runs, and what it refuses to invent

## What

Two refusals, and the dispatch that implements the first.

**Which behaviors are executed.** `fingerprint_behavior` routes on `state` first: a `confirmed`
behavior never runs a test, whatever level or adapter it declares, and gets an advisory static
fingerprint from its `entry` instead. Only then does level dispatch happen — and here the
implemented surface is narrower than the declared one:

| Declared | Actually implemented |
|---|---|
| `unit` / `component` — runner-native V8 coverage (vitest/jest) | `level: unit` **and** `adapter: vitest` only, invoked as `pnpm vitest run <file> [-t <name>] --coverage` |
| `integration` — static closure of a declared `entry` | implemented, adapter-agnostic; the `entry` field drives it |
| `e2e` — browser | not implemented |

Everything outside those two rows — a `component` behavior, a `unit` behavior on jest or
pytest, any `e2e` behavior — is emitted as `coverage: unknown` with `reason: level-deferred`.
That is the honest state of the runner today, against a SKILL.md table and an adapter list
(ADR-004 names cucumber, behave, pytest-bdd, jest, vitest, mocha, jasmine, playwright, cypress,
pytest, unittest, manual) that describe the model rather than what executes.

**What an unmeasurable run says.** Every failure path returns `unknown` with a `reason`, never
an empty pass and never a guess: `test-failed`, `no-coverage`, `coverage-outside-project`,
`no-entry`, `entry-missing`, `no-graph`, `graph-degraded: …`, `graph-query-failed: …`,
`level-deferred`, `not-run`. The reason is what the merge in SPEC-022 dispatches on, and it is
written into a committed file, which is why the detail spliced into `graph-query-failed` is
stripped of machine-specific paths first.

**What a scaffold contains.** When a behavior needs a new Gherkin test, `freya adapters
gherkin-scaffold` emits a skeleton: the `@SPEC-NNN` tag on the Feature, an `@BEH-NNN` tag on
each Scenario, a `TODO(scaffold)` marker, and three placeholder steps. No real steps, and no
step definitions — then or later. Authoring them is a human's job.

## Why

The lifecycle rule is ADR-003's: only `accepted, non-quarantined` is authoritative, and
`confirmed` means the intent is agreed while the test is still owed. The reason dispatch reads
state *before* level is that a confirmed record may perfectly well name a vitest locator for a
test nobody has written yet; ordering the checks the other way would run it. Making the gate
unreachable rather than merely forbidden is the point — a rule enforced by ordering cannot be
violated by a later adapter that forgets it.

The refusal to invent coverage is ADR-006's never-falsely-empty rule, and it carries the
highest cost of any rule in the layer: an empty `exercises` list reads to Direction A as
"nothing to re-run", which is the single output that silently disables the regression gate. The
failed-closure case is the same failure through a narrower door — a query error that came back
as `[]` produced a confident one-file fingerprint at full confidence, written into a committed
artifact, quietly narrowing every later blast radius.

The scaffold's emptiness is the same principle applied to intent instead of coverage. Intent
cannot be reliably inferred from code; generating plausible-looking scenarios from the
implementation would produce tests that mirror what the code does, which is the exact failure
the behavior layer exists to fix (ADR-001, ADR-003).

## Behavior

| Behavior | State | Verified by |
|----------|-------|-------------|
| BEH-116 A confirmed behavior naming a unit test is still never executed | proposed | `test_run_behaviors.py#FingerprintBehaviorTest.test_confirmed_with_unit_adapter_is_still_not_executed` (unittest) |
| BEH-117 A confirmed behavior cannot fail the regression gate even when handed a failed result | proposed | `test_behavior_graph.py#ConfirmedDoesNotBlockOnTestFailedTest.test_confirmed_with_test_failed_does_not_block` (unittest) |
| BEH-118 An accepted behavior at a level with no implemented path reports unknown and names the reason | proposed | `test_run_behaviors.py#FingerprintBehaviorTest.test_accepted_other_level_is_level_deferred` (unittest) |
| BEH-119 A failed dependency-closure query produces unknown with a reason, not a one-file closure | proposed | `test_run_behaviors.py#StaticFingerprintTest.test_a_failed_graph_query_is_unknown_not_a_one_file_closure` (unittest) |
| BEH-120 A generated Gherkin scaffold carries its tags and a scaffold marker, and placeholder steps only | proposed | `test_adapters.py#TestGherkinScaffold.test_no_real_steps_only_placeholders` (unittest) |

BEH-116 and BEH-117 are the same guarantee at two layers and are recorded separately because
each is separately breakable: the first is the runner declining to execute, the second is the
graph's gate declining to count a failure it should never have been handed. BEH-117's test
fabricates exactly that impossible input.

BEH-120 is one row for a scaffold with four asserted properties — the two tag families, the
marker, and the placeholder steps — each with its own test in `TestGherkinScaffold`. Recorded
as one behavior because what an operator observes is a single emitted file that is
unmistakably not a test. Two neighbouring guarantees are deliberately not given ids here and
belong with `verify`: that an accepted behavior still carrying the marker is an error, and that
the marker is scoped per scenario so an authored scenario sitting beside a scaffold in the same
file is not flagged by it (`test_adapters.py#TestScenarioScoping.test_authored_block_has_no_marker`).

No behavior is recorded for "an accepted unit vitest behavior is executed"
(`test_accepted_unit_vitest_is_executed`) or for the pnpm invocation
(`VitestArgvTest.test_builds_filtered_vitest_argv`). They are pinned, but they describe the one
implemented adapter rather than a guarantee the layer makes, and recording them would freeze an
implementation detail that ADR-004 explicitly expects to grow.

## Intentional Design Decisions

### State is read before level and adapter

**Decision**: `fingerprint_behavior` checks `state == "confirmed"` before it looks at `level` or
`adapter`, so a confirmed behavior that declares `level: unit, adapter: vitest` and a locator is
routed to the static path and never executed.

**Rationale**: ADR-003 records the decision and rejects the alternative ordering by name,
including the test that pins it. Not restated.

**Security Scan Note**: the unreachable branch is the design. A reviewer who notices that
`level` and `adapter` are validated but unused for confirmed records, and "simplifies" the
dispatch by checking level first, turns a documented safety property into a race with whatever
locator happens to be in the frontmatter.

### The non-gating rule is enforced twice, in two skills

**Decision**: `regression_check` re-checks `state == "accepted"` before adding a behavior to
`failed`, even though the runner contract guarantees a confirmed behavior can never come back
`test-failed`.

**Rationale**: defense in depth across a subprocess boundary. The two skills are separately
versioned and separately installed (ADR-004's execution split), so the graph cannot assume the
runner beside it is the one it was written against; and future executable paths for the
remaining levels would otherwise inherit the ability to gate on unconfirmed intent.

**Security Scan Note**: this is a duplicated check, not dead code. Removing it as redundant
removes the only enforcement that survives a runner from a different version.

### An unimplemented path is loud rather than absent

**Decision**: a level or adapter with no implementation returns `coverage: unknown` with
`reason: level-deferred` rather than an empty successful fingerprint — and the merge then
preserves whatever was previously known, rather than overwriting it with the nothing that was
just measured.

**Rationale**: ADR-006 gives the argument and the two opposite silent failures the `reason`
discriminator exists to separate. Specific to this surface: `level-deferred` is how the layer
reports its own incompleteness, so the count of behaviors carrying it is the honest measure of
how much of the declared adapter matrix is real.

**Security Scan Note**: a fingerprint that is `unknown` is not a failure and does not block. It
means unmeasured. A tool treating `unknown` as `covered: false`, or as an error, will both be
wrong; the distinction between "no coverage" and "coverage not attempted" is carried entirely
by the `reason` string.

### The scaffold will never contain real steps

**Decision**: `render_feature_scaffold` emits `Given <initial state>` / `When <action>` /
`Then <expected outcome>` under a `TODO(scaffold)` marker, and writes no step definitions. This
is permanent, not a first iteration.

**Rationale**: ADR-001 and ADR-003 both bear on it — the layer links to tests rather than
authoring them, and inferred intent must never enter the code tree wearing an authoritative
costume. Not restated. What is specific to the scaffold: the marker is the only mechanical way
`verify` can tell an unfilled scaffold from a real linked test, so it is load-bearing rather
than a comment.

**Security Scan Note**: a `.feature` file full of placeholder steps and a `TODO` is not an
abandoned or broken test. It is a scaffold awaiting a human, and it cannot make a suite pass
falsely — the accepted state that would make it authoritative is exactly the state `verify`
refuses while the marker is present.

## Certainty

80. ADR-003 names the state-before-level ordering, the pinning test and the rejected
alternative outright; ADR-006 names the never-falsely-empty rule; the scaffold's shape is
stated in three places and asserted in four tests. Held below that on two counts. First,
`level-deferred` is a placeholder by the runner's own SKILL.md ("later plans"), so recording it
as intended behavior is a reading — what is certainly intended is *that an unimplemented path
says so*, not that the current set of unimplemented paths is final. Second, whether the
hardcoded `pnpm` in the vitest invocation is a decision or an artifact of the testbed is
unanswered anywhere, and a project on npm or yarn would find out at run time.

## Related Specs

- [SPEC-022: behavior.json is a committed projection](../infra/SPEC-022-behavior-json-committed-projection.md) — where these fingerprints are merged and what each `reason` does there
- [SPEC-023: Blast radius in both directions, and the uncovered-code audit](./SPEC-023-behavior-blast-radius-and-audits.md) — the queries the resulting edges serve
- [SPEC-005: Never a confidently empty answer](./SPEC-005-code-graph-answers-and-empty-results.md) — the code-graph side of BEH-119's failed query

## Change History

| Date | Change | Reason |
|------|--------|--------|
| 2026-08-21 | Initial spec, inferred from code and tests | Brownfield scan of the behavior layer |
