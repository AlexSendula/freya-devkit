---
id: ADR-012
title: Only an accepted, test-backed behavior may downgrade a security finding, and a downgrade never deletes
status: accepted
created: 2026-08-19
updated: 2026-08-19
tags:
  - security
  - behavior-layer
  - intentional-design
---
# ADR-012: Only an accepted, test-backed behavior may downgrade a security finding, and a downgrade never deletes

## Decision

The security scan consults the behavior graph in addition to declarative specs. An `accepted`, test-backed behavior that explains a flagged finding is the strongest available intentional-design evidence: it downgrades the finding to `status: intentional` with a `behavior_ref`, dropping it from the outstanding count while the finding stays fully visible in the report. A matching `confirmed` behavior adds an advisory note only and the finding stays open; where both a behavior and a declarative spec explain a finding, the behavior reference is preferred; findings nothing explains flow into the backlog.

## Rationale

A passing linked test proves the flagged pattern is the intended, working behavior — **verified evidence rather than a prose claim**. The scan already honored the weaker evidence (a declarative spec asserting "this is intentional"), so the stronger evidence must count too, and an accepted behavior stands on its own even where no declarative spec covers the finding (`docs/design/behavior-layer/03-adoption-and-intent-lifecycle.md:78`).

> **Correction, 2026-08-24 (SEC-006 in *this* repository's scan — not the testbed `SEC-001`/`SEC-002` quoted further down, which are a different index).** The sentence above is the false premise this record was built on, and it is the sentence the rest of the toolkit inherited. **No test is run.** `--covering` reads two project-supplied artifacts — behavior state and locator out of `knowledge-base/specs/`, exercised paths and coverage out of the committed `knowledge-base/.graph/behavior.json` — and both are hand-editable by the repository being scanned. What licenses a downgrade is therefore a *claim* that a test exists and passes, checked for shape, never for truth. Read every "test-backed", "verified evidence" and "verified intent" in this record, including its own title, as "accepted-and-locator-resolving", which is what the code actually establishes.
>
> **The gap is not closed, and this correction is not a fix.** SEC-006 was mitigated rather than resolved, and the reason is worth recording because it is the reason a future attempt will fail the same way. Re-deriving the behavior's state from the specs instead of from `behavior.json` — which is what `covering()` now does (`behavior_graph.py:584`) — moves the forgery from one committed file to two; it does not remove it, because both files ship inside the repository under audit. The only evidence that would not be project-supplied is running the linked test, and running a scanned repository's suite is arbitrary code execution performed by a security tool on hostile input, which is worse than the finding. So the query stops claiming and starts labelling: it returns an `evidence` string saying exactly what was trusted (`behavior_graph.py:598`–`:603`), and the skill that consumes it copies that string into the report verbatim and is told in as many words never to write *"verified by passing test"* (`skills/freya-codebase-security-scan/SKILL.md:429`). A label the reader sees is the whole of the mitigation; without the skill-side half it would have been inert.
>
> **The residual, stated so the next reader does not have to find it.** `covering()` skips the locator check entirely when a behavior declares no locator — `if locator and not _locator_resolves(...)` (`behavior_graph.py:591`) — and it never reads the adapter, which *is* projected (`_PROJECTED_FIELDS`, `behavior_graph.py:40`) and simply not consulted. So an `accepted` behavior with no locator still downgrades, whether or not its adapter is `manual`. For `manual` that is legal and Tier 1 agrees; for any other adapter Tier 1 refuses the same record as `missing-locator` while this query returns it. Both shapes reach a downgrade, and the second one is a forged spec's cheapest route. It is pinned, not closed (`behavior_graph.py:561`–`:565`).
>
> **This query's locator check and `verify_links`' Tier-1 check are not the same check and neither implies the other — but as of 2026-08-23 every divergence the fixture measures runs the same direction: Tier 1 refuses and `--covering` returns anyway.** The two that ran the other way were closed inside this branch by `8179f62`, which gave `verify_links` a `locator-names-no-file` error for a locator with no path part (`skills/freya-spec-manager/scripts/verify_links.py:194`) and moved its existence test from `Path.exists` to `is_file`, so a directory no longer satisfies it (`:204`); the same commit rewrote both rows of `LocatorCheckDivergesFromTier1Test` (`skills/freya-behavior-graph/scripts/test_behavior_graph.py:861`) to assert *agreement* at `(False, False)` (`:931`, `:943`). The two that survive fail **open** here rather than closed — an `accepted` behavior with a non-`manual` adapter and no locator at all, and a `.py` locator whose fragment names no symbol — Tier 1 refuses each and this query returns it (`:950`, `:960`, both `(False, True)`). **So the reassurance that used to sit here is spent, and the asymmetry now points the other way: no row in that class is `(True, False)`, so nothing measured here makes a gate-green repository meet a `--covering` refusal, while two measured shapes make a gate-red repository get a downgrade this query was happy to license.** Running the gate is worth strictly more than running this. Two caveats on the sources: `covering()`'s own docstring still calls the first two rows Tier-1 **passes** (`skills/freya-behavior-graph/scripts/behavior_graph.py:556`–`:560`) and is stale on that point until it is corrected, and its fourth bullet's Gherkin-reverse-tag case (`:566`–`:568`) is described there with no executable row behind it — of the shapes that block names, that is the one nothing in this repository measures.

The canonical case is a scan flagging "endpoint does not verify the user exists" against BEH-003's uniform anti-enumeration response. The finding is real as a pattern and wrong as a verdict, and the behavior's passing test is what settles it.

**The bar is enforced by the query, not only by procedure.** `behavior-graph --covering <file>` filters to `state == "accepted"` before the agent ever judges relevance (`skills/freya-behavior-graph/scripts/behavior_graph.py:588`), so a `proposed` or `confirmed` behavior is never even a candidate for silencing. That places the trust boundary in deterministic code rather than in an instruction the agent could drift from.

**Safety comes from the shape of the downgrade: annotate and reclassify, never delete.** Every silencing stays in the report, auditable against a named behavior and its test, so a misjudgment is a visible, reversible annotation rather than a vanished finding. The `behavior_ref` field is part of the documented findings index schema (`skills/freya-codebase-security-scan/references/findings-schema.md`).

SP5 proved the path end to end on the testbed (`docs/design/behavior-layer/dogfooding-notes.md:196`–`:198`):

- `--covering app/api/auth/passkey/authenticate/start/route.ts` returned `[(BEH-003, SPEC-001, static)]`.
- SEC-001 was downgraded to `status: intentional` with `behavior_ref: BEH-003` and dropped from the open count in `status`.
- SEC-002 on `lib/date-formatter.ts`, which no accepted behavior covers, returned an empty `--covering` and stayed `open`. No false silencing.

## Rejected Alternatives

- **Declarative specs as the only intentional-design evidence.** A prose claim nothing executes is strictly weaker than a passing test; keeping the weaker evidence while ignoring the stronger one inverts the trust order the behavior layer exists to establish.
- **Let `proposed` or `confirmed` behaviors explain findings.** Intent without a test is exactly the unverified claim a declarative spec already makes. Unverified states may annotate, never silence — otherwise a bootstrap guess could clear a real vulnerability.
- **Delete or hide a downgraded finding.** That destroys the audit trail which makes the downgrade checkable, and a wrong judgment becomes undiscoverable instead of reversible.
- **Require `coverage: observed` for membership in `--covering`.** `observed` is reported as the stronger signal that the path really executes, but `accepted` alone is the gate — a static fingerprint on an accepted, test-backed behavior is still verified intent, and requiring `observed` would exclude legitimate cases for no gain in trust.
- **Require a declarative spec alongside the behavior match.** Redundant paperwork: the behavior plus its passing test is already the stronger evidence, so demanding the weaker artifact as a co-signature only suppresses valid downgrades.
- **Replace the existing declarative `check-specs` cross-reference.** It is unchanged and still the path for non-executable decisions, which by definition no test can carry.

## Revisit Conditions

The relevance judgment — does this behavior's intent actually explain this finding — is agent judgment, the same kind `check-specs` already makes, validated by dogfooding rather than deterministically. If false downgrades appear at volume, the deterministic `--covering` prefilter is the tested piece to build a stricter rule or a second confirmation step on.
