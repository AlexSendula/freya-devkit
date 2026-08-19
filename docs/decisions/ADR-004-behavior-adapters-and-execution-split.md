---
id: ADR-004
title: Bind behaviors to tests through adapters, and split execution from the graph
status: accepted
created: 2026-08-19
updated: 2026-08-19
tags:
  - behavior-layer
  - adapters
  - architecture
  - srp
---
# ADR-004: Bind behaviors to tests through adapters, and split execution from the graph

## Decision

Behavior is modelled independently of any runner: an adapter plus a locator links a behavior to whatever verifies it — a Gherkin scenario (`cucumber`, `behave`, `pytest-bdd`), a native test (`jest`, `vitest`, `pytest`, `playwright`, `go-test`), or `manual` — and test tooling is detected at runtime, statelessly, on demand. The layer ships as two skills split on the execution seam: `freya-behavior-runner` executes accepted behaviors and emits fingerprints as JSON on stdout, and `freya-behavior-graph` owns `behavior.json`, projects spec frontmatter, merges fingerprints and serves both blast-radius directions. `behavior.json` lives in the git-ignored `knowledge-base/.graph/` as a sibling of `graph.json` (`skills/freya-behavior-graph/scripts/behavior_graph.py:92`); `code-graph` neither owns nor reads it and is only queried via `--impact`/`--dependencies`.

## Rationale

Forcing a project to re-author an existing suite into Gherkin is the adoption cost that would have killed the layer before it earned anything. Gherkin is therefore the recommended default for *new* user-visible behavior, not a requirement: a native adapter links an existing test by locator with no rewrite, no `.feature` and no step definitions (`skills/freya-spec-manager/scripts/adapters.py:12`). Gherkin scaffolds are the only shape that carries a written `TODO(scaffold)` marker, which is what lets integrity checks tell an unwritten scaffold from a real linked test (`skills/freya-spec-manager/scripts/adapters.py:26`).

Runtime detection mirrors what `docs-manager` already does for project type, so no stack is hardcoded (`docs/design/behavior-layer/00-vision.md:30`). It is stateless because a persisted tracking file would have had no consumer — the guidance was explicit, "do not invent a persisted tracking file with no consumer" — so Phase 2 re-runs detection when it needs it.

The skill split follows the one real seam in the system: `code-graph`'s build is static parsing — cheap, pure, no subprocess — whereas running behaviors boots app servers, drives third-party runners, manages processes and ports and captures runtime coverage. Bundling that into the graph layer would pollute a deterministically-testable data layer with the single messy, flaky operation (`docs/design/behavior-layer/02-phase-2.md:132`). The two halves also change for different reasons: the runner changes when you add an adapter, a level or a coverage mechanism; the graph changes when the projection schema, the trust rules or the query semantics change.

The suites prove the seam holds. `behavior_graph.py`'s unit tests never execute a real test runner: every build and check path is exercised with `_run_behavior_runner` patched (`skills/freya-behavior-graph/scripts/test_behavior_graph.py:137`), which is only possible because the graph layer reaches the runner through exactly one subprocess boundary (`skills/freya-behavior-graph/scripts/behavior_graph.py:118`). Cross-skill access is a subprocess call against the suite root, not a Python import, because no cross-skill import path exists — skills shell out. Keeping `behavior.json` in its own file also lets the code-substrate question stay open without holding up the behavior layer.

## Rejected Alternatives

- **Gherkin-only, with cucumber as the single supported form.** Every project without a Gherkin suite would have had to re-author its tests before getting any value. That is the adoption cliff the adapter model exists to remove.
- **A hardcoded stack or a fixed list of supported runners.** `docs-manager` had already shown that runtime project-type detection is feasible, so hardcoding would have been a self-inflicted portability limit.
- **A persisted runner-tracking file.** Nothing consumed it. A stored fact with no reader is a file that goes stale silently; detection is cheap enough to redo on demand.
- **Importing detection helpers across skills in Python.** There is no cross-skill import path in the plugin layout, so this would have required inventing one. Skills shell out instead.
- **A single combined behavior skill.** `behavior-graph` would no longer be queryable or unit-testable without a live runner, and the pure graph layer would inherit the runner's flakiness.
- **`behavior.json` owned by `code-graph`, or merged into `graph.json`.** The first draft specified exactly this and it was explicitly reversed. It makes `code-graph` behavior-aware and welds the behavior projection to whatever code substrate is eventually chosen; `behavior.json` is a sibling file, never a schema bump to `graph.json`.
- **Ship one skill now and split later once the seam hurts.** Migrating ownership and reshuffling command surfaces after the fact is worse than starting clean. The accepted cost of splitting up front is one extra orchestration hop and a `behavior-graph` thinner than the runner.

## Revisit Conditions

Reconsider if adapter maintenance across many runners outgrows its value; if a runner needs behavior identity that the adapter/locator pair cannot express; if `behavior-graph` never grows past a thin wrapper around the runner, which would mean the split bought nothing; or if the code substrate is replaced such that behavior edges could live natively in the same store, which would remove the reason for a separate `behavior.json`.
