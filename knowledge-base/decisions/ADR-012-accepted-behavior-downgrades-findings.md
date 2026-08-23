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

The canonical case is a scan flagging "endpoint does not verify the user exists" against BEH-003's uniform anti-enumeration response. The finding is real as a pattern and wrong as a verdict, and the behavior's passing test is what settles it.

**The bar is enforced by the query, not only by procedure.** `behavior-graph --covering <file>` filters to `state == "accepted"` before the agent ever judges relevance (`skills/freya-behavior-graph/scripts/behavior_graph.py:320`), so a `proposed` or `confirmed` behavior is never even a candidate for silencing. That places the trust boundary in deterministic code rather than in an instruction the agent could drift from.

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
