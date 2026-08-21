# Spec Corpus Index

**30 specs · 149 behaviors · all behaviors `proposed`**

This corpus was **inferred by a brownfield scan on 2026-08-21**, not authored by
hand. Ten parallel workers read the code and its tests and wrote down what the
suite already guarantees; nothing here changed a line of implementation.

Read it with four things in mind:

1. **Every behavior is `proposed` by design.** Bootstrap never asserts that a
   machine-written record carries human intent, so the whole corpus starts in
   the lowest-trust lifecycle state — see
   [ADR-007](../decisions/ADR-007-bootstrap-proposed-drain-lazily.md). `proposed`
   is advisory: it blocks nothing, and only `accepted` is authoritative.
2. **Nothing needs review now.** The 149-record queue is not a task list to sit
   down and grind through. It drains **lazily, on hit**: when wrap-up touches
   code a behavior covers, that behavior — and only that one — comes up for
   confirmation. The undrained tail is published in
   [BACKLOG.md](../BACKLOG.md) rather than hidden.
3. **Certainty below 100 means inferred, not authored.** A score is the scan's
   own confidence that it read the intent correctly out of code, tests, comments
   and ADRs. 100 is reserved for a spec a human wrote or confirmed. Every score
   below is a standing invitation to correct it. The range here is 70–85.
4. **A `manual` adapter means the test is owed, not that the check is manual.**
   17 of the 149 behaviors are real, observable guarantees with no test
   anywhere. Their `locator:` names the address where the test *should* live, so
   it deliberately points at a file, class or method that does not exist yet.
   `verify-links` skips `manual` records for exactly this reason.

## features (20 specs, 89 behaviors)

| Spec | Title | Status | Certainty | Behaviors | No test |
|------|-------|--------|-----------|-----------|---------|
| [SPEC-004](./features/SPEC-004-code-graph-build-and-update.md) | Building and refreshing the dependency graph | implemented | 82 | 8 | 1 |
| [SPEC-005](./features/SPEC-005-code-graph-answers-and-empty-results.md) | Never a confidently empty answer | implemented | 85 | 5 | — |
| [SPEC-006](./features/SPEC-006-code-graph-traversal-and-cache-clear.md) | Transitive traversal and clearing the graph cache | implemented | 72 | 2 | — |
| [SPEC-010](./features/SPEC-010-default-graph-scope.md) | Default Graph Scope — What a Build Reads Before Anyone Configures Anything | implemented | 85 | 5 | — |
| [SPEC-011](./features/SPEC-011-two-tier-exclusion-override.md) | A Project Can Overrule Any Exclusion Default, in Two Tiers | implemented | 80 | 5 | — |
| [SPEC-012](./features/SPEC-012-directory-verdicts-and-the-classification-cache.md) | Where a Directory Verdict Lives, and What Invalidates the Cache | implemented | 80 | 5 | — |
| [SPEC-013](./features/SPEC-013-project-stack-detection.md) | Project Stack Detection | implemented | 80 | 6 | 1 |
| [SPEC-014](./features/SPEC-014-existing-docs-detection.md) | Existing Documentation Detection | implemented | 85 | 2 | — |
| [SPEC-015](./features/SPEC-015-docs-graph.md) | The Docs Graph — Which Documentation Section Cites Which Code | implemented | 82 | 7 | 1 |
| [SPEC-016](./features/SPEC-016-adr-record-integrity.md) | ADR record integrity and index | implemented | 85 | 6 | 1 |
| [SPEC-017](./features/SPEC-017-spec-search-and-discovery.md) | Spec search and corpus discovery | implemented | 70 | 5 | 5 |
| [SPEC-018](./features/SPEC-018-declared-intent-gate.md) | Declared-intent gate over accepted behaviors | implemented | 85 | 4 | — |
| [SPEC-019](./features/SPEC-019-principle-enforcement-surface.md) | Principle enforcement surface (G2) | implemented | 80 | 5 | — |
| [SPEC-020](./features/SPEC-020-contradiction-comparison-set.md) | Contradiction comparison sets (G3) | implemented | 85 | 5 | — |
| [SPEC-021](./features/SPEC-021-declarative-drift-scope.md) | Declarative-drift scope and the gaps view (P4b) | implemented | 80 | 5 | — |
| [SPEC-023](./features/SPEC-023-behavior-blast-radius-and-audits.md) | Blast radius in both directions, and the uncovered-code audit | implemented | 75 | 5 | — |
| [SPEC-024](./features/SPEC-024-behavior-execution-dispatch.md) | What the behavior layer runs, and what it refuses to invent | implemented | 80 | 5 | — |
| [SPEC-028](./features/SPEC-028-the-status-census.md) | The Status Census | implemented | 80 | 10 | 2 |
| [SPEC-029](./features/SPEC-029-the-generated-backlog.md) | The Generated Backlog | implemented | 75 | 4 | 2 |
| [SPEC-030](./features/SPEC-030-wrap-up-orchestration.md) | Wrap-Up Orchestration | implemented | 70 | 0 | — |

`SPEC-030` is **declarative**: wrap-up is `SKILL.md` alone, with no engine, no
tests and no manifest entry, so it has intent to record but no behavior it could
honestly claim to pin.

## infra (10 specs, 60 behaviors)

| Spec | Title | Status | Certainty | Behaviors | No test |
|------|-------|--------|-----------|-----------|---------|
| [SPEC-001](./infra/SPEC-001-freya-launcher-command-surface.md) | The `freya` launcher command surface | implemented | 85 | 5 | 1 |
| [SPEC-002](./infra/SPEC-002-canonical-store-install-contract.md) | Canonical-store install contract — install, update, uninstall | implemented | 85 | 7 | — |
| [SPEC-003](./infra/SPEC-003-agents-md-managed-block.md) | The managed AGENTS.md block written by `freya init` | implemented | 80 | 3 | — |
| [SPEC-007](./infra/SPEC-007-substrate-backend-selection.md) | Substrate Backend Selection | implemented | 85 | 7 | — |
| [SPEC-008](./infra/SPEC-008-code-graph-artifacts.md) | Code Graph Artifacts and What Is Committable | implemented | 80 | 3 | — |
| [SPEC-009](./infra/SPEC-009-unmapped-source-census.md) | The Unmapped-Source Census | implemented | 82 | 5 | 1 |
| [SPEC-022](./infra/SPEC-022-behavior-json-committed-projection.md) | behavior.json is a committed projection, and a rebuild only changes it when something changed | implemented | 80 | 5 | 1 |
| [SPEC-025](./infra/SPEC-025-read-only-audit-workers.md) | Read-Only Audit Workers and Agent Selection | implemented | 84 | 5 | — |
| [SPEC-026](./infra/SPEC-026-security-scan-spend-gate.md) | The Security Scan Spend Gate | implemented | 82 | 5 | — |
| [SPEC-027](./infra/SPEC-027-no-false-clean-bill-of-health.md) | A Security Run That Could Not Finish Says So | implemented | 78 | 5 | 1 |

## Id allocation

`SPEC-001` … `SPEC-030` and `BEH-001` … `BEH-149` are all in use, with no gaps
and no duplicates. `BEH-150` was reserved for the scan and never spent, so it is
the next free behavior id; `SPEC-031` is the next free spec id.

## Where the coverage gaps are

The 17 `manual` behaviors are the scan's honest ledger of intent that nothing
executes. Two areas carry most of it:

- **`SPEC-017` (all 5).** `search_specs.py` is the only script in
  `skills/freya-spec-manager/scripts/` with no `test_*.py` sibling — and it is
  the module every other spec-manager script imports.
- **`SPEC-027` (BEH-135).** The `findings.json` "reclassify, never delete"
  guarantee lives entirely in prose; no code writes the file and no test asserts
  its shape.

The rest are single uncovered branches, each named in its own spec's Behavior
section. `knowledge-base/BACKLOG.md` is the generated, always-current view;
this file is the map.
