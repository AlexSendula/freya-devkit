---
id: ADR-001
title: Intended behavior is a first-class executable artifact
status: accepted
created: 2026-08-19
updated: 2026-08-19
tags:
  - behavior-layer
  - intent
  - scope
---
# ADR-001: Intended behavior is a first-class executable artifact

## Decision

Intent that is observable behavior becomes a Behavior record: a stable `BEH-NNN` id with a
lifecycle, bound by an adapter to a test that actually runs. The toolkit is no longer purely a
reverse-sync engine (graph, docs, specs and security kept in sync after the fact); it has a
forward-authoritative layer that code must conform to. The layer's scope is traceability, not
testing methodology — test level is a field on the behavior and the runner's dispatch key, never
a prescribed pyramid and never a separate skill, and the layer links to whatever test already
verifies a behavior rather than writing tests, running TDD or replacing a runner. Mocking policy
is guidance carried on the behavior, not an enforced check.

## Rationale

Three concrete gaps drove the layer.

1. **Tests are written from the code, so they verify what the code does rather than what it
   should do.** Coverage reads healthy while intent is unguarded, and a change can silently alter
   behavior on a fully green suite.
2. **spec-manager's acceptance criteria were an inert checkbox list.** Nothing executed them, and
   `verify` could only eyeball them.
3. **code-graph structurally cannot answer the behavioral question.** It answers "what *code* does
   this change touch?" Nothing answered "what *intended behavior* does this change touch?"
   (`docs/design/behavior-layer/00-vision.md:22`).

The scope limit is what makes the layer composable rather than competitive. The differentiated
value is only three things — the stable Behavior entity, the intent→test→code graph, and
governance — so the layer sits next to existing tooling instead of duplicating it: superpowers TDD
writes the test and the layer links to it; gsd generates tests per phase and the layer adds the
cross-cutting traceability gsd lacks. Owning test creation would duplicate both and drag the layer
into a methodology it has no claim to.

Level-agnosticism was proven rather than asserted: Phase 2 shipped two levels at once — BEH-003 at
integration via cucumber and BEH-002 at unit via vitest, two adapters and two coverage mechanisms,
"exactly the contrast the measurement gate needs"
(`docs/design/behavior-layer/02-phase-2.md:199`). The prohibition on a prescribed pyramid is
explicit in the same document: `level` is a field plus the runner's dispatch key, not a separate
skill (`docs/design/behavior-layer/02-phase-2.md:86`).

The mocking guidance is mechanical, not stylistic, which is also why it stays guidance. Heavy
mocking shrinks the `exercises` fingerprint to near-nothing and thereby weakens Direction A, and it
tests the mock rather than the guarantee — mocking the database to return "no user" for BEH-003
would test the mock, not the no-enumeration property. But whether a given mock crosses that line is
per-behavior judgement the tool cannot verify, so it is advice on the record, not a gate.

**Build-vs-borrow.** Two ideas were taken from `github/spec-kit` (verified 2026-06) and spec-kit
itself was refused (`docs/design/behavior-layer/00-vision.md:185`): a project-wide constitution,
adopted as `knowledge-base/principles.md` sitting above all specs and decisions; and Given/When/Then
acceptance criteria, made executable via a Gherkin `.feature` or a linked native test and absorbed
into the behavior layer rather than kept as a separate artifact.

## Rejected Alternatives

- **Inert Given/When/Then prose checkboxes, as spec-kit ships them.** Nothing executes them, so
  drift stays silent — this is the exact gap being closed, not a solution to it.
- **Test coverage as the proxy for intent.** Coverage measures which code ran; it never measures
  which intent is pinned. A change can hold coverage constant and alter the guarantee.
- **Extending code-graph alone.** code-graph has no notion of intent and no place to put a stable
  behavioral id; the missing edge (`TEST → CODE`, anchored to a behavior) does not exist in it.
- **Adopting spec-kit wholesale as the forward engine.** freya-devkit already has a forward flow
  through superpowers brainstorming → writing-plans → executing-plans, and its differentiator is
  reverse-sync plus intentional decisions plus the security tie-in. Adopting spec-kit discards that
  and couples the roadmap to an external template engine.
- **Prescribing a test pyramid.** The team decides how much of each level to write; the layer's job
  is traceability to whatever verifies a behavior, at whatever level.
- **A skill per test level.** Levels differ in mechanics, not in traceability semantics; one field
  and one dispatch key cover it.
- **Owning test creation.** Duplicates gsd's generator and superpowers TDD, and claims a
  methodology the layer has no basis to claim.
- **Enforcing "mock minimally" as a check.** The judgement is per-behavior and the tool cannot
  verify it; a false failure here would train people to ignore the layer.

## Revisit Conditions

- If maintaining behavior records on a real project costs more than the regressions they catch,
  the layer's existence is back on the table.
- If a runner-level mechanism appears that pins intent without a separate record, the Behavior
  entity stops being the differentiator.
- If locators drift faster than they can be repaired, owning some test authoring must be
  reconsidered despite the scope limit.
- If spec-kit or a successor grows reverse-sync and decision capture, the build-vs-borrow
  calculation changes and should be rerun.
- Foreign-tooling ingest — migrating a project off spec-kit — was deliberately left as a separate
  later concern and is not settled by this record.
