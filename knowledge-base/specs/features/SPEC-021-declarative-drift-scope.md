---
id: SPEC-021
title: Declarative-drift scope and the gaps view (P4b)
category: features
tags: [governance, drift, p4b, blast-radius, code-graph, tier-2, spec-manager]
status: implemented
certainty: 80
created: 2026-08-21
updated: 2026-08-21
related_code:
  - skills/freya-spec-manager/scripts/drift.py
  - skills/freya-spec-manager/scripts/adr.py
  - skills/freya-spec-manager/scripts/search_specs.py
  - skills/freya-spec-manager/scripts/test_drift.py
  - bin/commands.json
  - skills/freya-spec-manager/SKILL.md
intentional_decisions:
  - "Drift is scoped by related_code intersecting the blast radius, not run globally"
  - "A missing code graph degrades to changed-only and labels itself, never to an empty radius"
  - "An item with no related_code is out of scope, and the gap is published rather than closed"
  - "A deprecated spec, and a spec declaring no decisions, constrain nothing"
  - "Only accepted ADRs constrain code; a proposed one does not"
behaviors:
  - behavior_id: BEH-101
    title: A declared item becomes a drift target only where its related_code intersects the change's blast radius
    state: proposed
    level: unit
    adapter: unittest
    locator: skills/freya-spec-manager/scripts/test_drift.py#ContextCase.test_target_when_related_code_intersects_impact
  - behavior_id: BEH-102
    title: A deprecated spec, and a spec declaring no decisions, are never drift targets
    state: proposed
    level: unit
    adapter: unittest
    locator: skills/freya-spec-manager/scripts/test_drift.py#ContextCase.test_excludes_deprecated_spec_and_specs_without_decisions
  - behavior_id: BEH-103
    title: An accepted ADR whose related_code is touched is a target; a proposed ADR is not
    state: proposed
    level: unit
    adapter: unittest
    locator: skills/freya-spec-manager/scripts/test_drift.py#ContextCase.test_accepted_adr_is_target_proposed_excluded
  - behavior_id: BEH-104
    title: A change with no usable code graph reports impact_source changed-only rather than an empty blast radius
    state: proposed
    level: unit
    adapter: unittest
    locator: skills/freya-spec-manager/scripts/test_drift.py#ComputeImpactCase.test_no_graph_result_degrades_to_changed_only
  - behavior_id: BEH-105
    title: "`drift gaps` lists the declared items whose intent has no related_code anchor"
    state: proposed
    level: unit
    adapter: unittest
    locator: skills/freya-spec-manager/scripts/test_drift.py#GapsCase.test_lists_decisions_without_related_code
---

# Declarative-drift scope and the gaps view (P4b)

## What

`freya drift` asks the code-versus-intent question: did the code that changed in
this cycle drift away from intent that was *declared* rather than tested — a
spec's `intentional_decisions` or an accepted ADR's body?

**`context`** answers "what is in scope for this change". It resolves the change
into an impact set (changed files, plus their transitive dependents from the code
graph), then keeps only declared items whose `related_code` intersects it,
reporting for each target the full declared footprint and the subset actually hit
(BEH-101). Deprecated specs, specs with no declared decisions, and non-accepted
ADRs are not targets (BEH-102, BEH-103). The payload always names how the radius
was computed: `code-graph` when the graph answered, `changed-only` when it could
not, `empty` when nothing changed (BEH-104).

**`gaps`** answers the honest complement — which declared specs and ADRs carry
intent but no `related_code`, and are therefore invisible to `context` no matter
what changes (BEH-105). It is on-demand and deliberately not part of every
wrap-up.

**`resolve`** and **`prior`** are the append-only resolution-log pair described in
[SPEC-019](./SPEC-019-principle-enforcement-surface.md), keyed on `(item, path)`.

## Why

Direction-A checking — run the tests — cannot see a decision that was never
expressible as a test. P4b covers that half, and it takes the *opposite* scoping
to the contradiction check: code-anchored, blast-radius-scoped, because
re-judging every declared decision against every change is the whole-repo
re-derivation that is too noisy to be trusted and therefore gets switched off. The
reasoning for choosing scope per check by which failure is recoverable is recorded
in `knowledge-base/decisions/ADR-011-governance-check-scoping.md`.

That scope buys quiet at the cost of recall, and the design refuses to hide the
cost: the un-scopable set is inspectable through `gaps`, and a degraded blast
radius says so in the payload instead of returning a smaller answer that looks
complete. The recommended long-term fix for a gap is not a wider scope — it is
keeping `related_code` current, or promoting the decision into a guard scenario
where that is cheap.

**Certainty (80).** The scoping decision, the degradation contract and the purpose
of `gaps` are all documented — ADR-011 cites `drift.py` by line, the module
docstring names the design document, and `SKILL.md` declares itself the single
source for the P4b procedure. Held at 80 by the target filters: excluding
deprecated specs and specs with no `intentional_decisions` (BEH-102) is a
consequential scope choice that no ADR argues for, and the `related_code`
intersection is a plain string match on project-relative paths, so a path spelled
differently in a spec than in `git diff` output silently drops a target — behavior
that looks decided but may only be incidental.

## Behavior

| Behavior | State | Verified by |
|----------|-------|-------------|
| BEH-101 A declared item becomes a drift target only where its related_code intersects the change's blast radius | proposed | `test_drift.py#ContextCase.test_target_when_related_code_intersects_impact` (unittest) |
| BEH-102 A deprecated spec, and a spec declaring no decisions, are never drift targets | proposed | `test_drift.py#ContextCase.test_excludes_deprecated_spec_and_specs_without_decisions` (unittest) |
| BEH-103 An accepted ADR whose related_code is touched is a target; a proposed ADR is not | proposed | `test_drift.py#ContextCase.test_accepted_adr_is_target_proposed_excluded` (unittest) |
| BEH-104 A change with no usable code graph reports impact_source changed-only rather than an empty blast radius | proposed | `test_drift.py#ComputeImpactCase.test_no_graph_result_degrades_to_changed_only` (unittest) |
| BEH-105 `drift gaps` lists the declared items whose intent has no related_code anchor | proposed | `test_drift.py#GapsCase.test_lists_decisions_without_related_code` (unittest) |

BEH-104's sibling cases are proven alongside it and unrecorded: a graph that runs
and finds no dependents still reports `code-graph`
(`ComputeImpactCase.test_success_with_no_dependents_is_code_graph`), a missing
graph tool degrades the same way as a missing graph
(`test_graph_tool_missing_degrades_to_changed_only`), and no changed files is
`empty` (`test_no_changes_is_empty`). BEH-105 covers specs; the ADR half of the
same command is proven by `GapsCase.test_lists_adrs_without_related_code`.

## Intentional Design Decisions

### Drift is blast-radius-scoped, and the resulting recall gap is published

**Decision**: only declared items whose `related_code` intersects the change's
impact set are judged. Drift introduced in code that is neither in nor a dependent
of `related_code` is not caught, and an item with no `related_code` at all is out
of scope entirely. The gap is surfaced by `gaps` rather than closed by widening
the scope. See
`knowledge-base/decisions/ADR-011-governance-check-scoping.md`.

**Security Scan Note**: a clean `drift context` means "no declared intent anchored
to the code you touched was contradicted". It is not evidence that the change
honours every decision in the project. Any conclusion of the form "the tool found
no drift, therefore the decision still holds" is over-reading it — check `gaps`
and `related_code` before drawing it.

### A missing code graph degrades to `changed-only` and labels itself

**Decision**: when the graph tool is absent, fails, or returns a result with no
`all_affected` key, `compute_impact` falls back to the directly changed files and
reports `impact_source: "changed-only"`. It never returns an empty impact set to
stand in for "could not compute", and the skill requires the narrower radius to be
called out to the engineer.

**Rationale**: a silently empty blast radius produces a clean run that means
nothing — the confidently-empty result the toolkit rules out. A labelled narrow
radius is a usable answer with a stated limit.

**Security Scan Note**: this is not a swallowed exception. `impact_source:
changed-only` in a report is the signal that dependent files were out of scope for
that run; the correct response is to re-run with a graph, not to treat the result
as complete.

### A deprecated spec, and a spec with no declared decisions, constrain nothing

**Decision**: `_spec_targets` skips any spec whose `status` is `deprecated` and
any spec with an empty `intentional_decisions` list, however well its
`related_code` matches the change.

**Rationale**: a deprecated record is withdrawn intent, and a spec whose intent is
entirely behavioral has nothing declarative to drift from — its guarantees are
enforced by running its behaviors instead.

**Security Scan Note**: a decision that still reads as binding in a `deprecated`
spec is enforced by nothing. Deprecating a spec silently retires every declarative
decision in it; that is intended, and it is the reason a decision worth keeping
belongs in an ADR or a live spec.

### Only accepted ADRs constrain code

**Decision**: the ADR target set is filtered by lifecycle status alone — accepted
in; proposed, superseded and deprecated out — matching the contradiction check's
filter.

**Rationale**: an ADR under discussion is not yet a project commitment, and
blocking or nagging on a proposal would make drafting one expensive
(`knowledge-base/decisions/ADR-011-governance-check-scoping.md`).

**Security Scan Note**: intent recorded in a `proposed` ADR is not enforced by any
check. If a decision needs to bind now, it needs to be accepted now.

### `gaps` is on-demand, not part of wrap-up

**Decision**: the honesty view runs when someone asks for it. Wrap-up's P4b step
runs `context` only.

**Rationale**: the gap list changes slowly and is a corpus-maintenance task, while
wrap-up is per-change; putting it in every run would attach a standing warning to
work that has nothing to do with it, and standing warnings get ignored.

**Security Scan Note**: the drift-blind set is not reported during normal
operation. An audit that wants to know what governance cannot see has to run
`freya drift gaps` explicitly.

## Related Specs

- [SPEC-020: Contradiction comparison sets (G3)](./SPEC-020-contradiction-comparison-set.md) —
  the always-global counterpart; the two scopings are one decision seen from
  opposite directions
- [SPEC-019: Principle enforcement surface (G2)](./SPEC-019-principle-enforcement-surface.md) —
  the shared append-only resolution-log semantics
- [SPEC-016: ADR record integrity and index](./SPEC-016-adr-record-integrity.md) — the
  lifecycle filter that decides which ADRs reach this check

## Change History

| Date | Change | Reason |
|------|--------|--------|
| 2026-08-21 | Initial spec (inferred) | Brownfield scan of `skills/freya-spec-manager/scripts/drift.py` |
