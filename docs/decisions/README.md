# Decisions

Architecture Decision Records — **what was decided, why, and what was rejected.**

The rejected alternatives are the point. Anyone can read the code to learn what the system
does; only these records say what it could have been and why it isn't. When a question comes
back around, start here so it doesn't get re-litigated from scratch.

These sixteen records were distilled from the design documents, specs and implementation plans
accumulated between 2026-06 and 2026-08 — roughly fifty files that mixed decisions with tasks,
status and superseded reasoning. The originals are in git history; what mattered is here.

## Format

Each record follows freya's own ADR format, defined by
[`frontmatter.py`](../../skills/freya-spec-manager/scripts/frontmatter.py) (`ADR_SCHEMA`) and
[`adr.py`](../../skills/freya-spec-manager/scripts/adr.py):

```
---
id: ADR-001
title: <title>
status: accepted | proposed | superseded | deprecated
created / updated: YYYY-MM-DD
tags: [...]
---
## Decision   ## Rationale   ## Rejected Alternatives   ## Revisit Conditions
```

**The tooling does not see this directory.** `adr.py` reads `knowledge-base/decisions/`
(`DECISIONS_RELDIR`, `adr.py:29`) — the layout it writes into an *adopting* project. This repo
deliberately keeps its root free of `knowledge-base/`, so `freya adr verify --project .` here
checks zero files and exits 0, and `freya adr list` prints an empty table. These sixteen
records do satisfy `ADR_SCHEMA`; nothing checks that automatically. The format is shared, the
tooling is not — write new records by hand.

**Authority order: shipped code beats an ADR beats a spec.** An ADR records the decision, not
the implementation. Where they disagree, the code is right and the ADR needs a correction —
add one rather than rewriting history.

> **On the citations.** Records here cite their sources by `path:line`. Citations into
> `skills/`, `bin/` and the rest of `docs/` resolve against the working tree. Citations into
> `docs/design/…` or `docs/superpowers/…` do **not** — those are the documents these ADRs were
> distilled from, deleted on 2026-08-19. They resolve against git history: `git log --all --
> <path>`, or `git show 04a9b8b:<path>`. The line numbers are exact as of that commit and are
> kept deliberately, because a citation without a line is not provenance.

## The records

### Foundations — what the system fundamentally is

| ADR | Decision |
|---|---|
| [ADR-001](ADR-001-behavior-as-executable-artifact.md) | Intended behavior is a first-class executable artifact |
| [ADR-002](ADR-002-authority-order-single-ownership.md) | Authority runs principle > ADR > spec > reference, and every fact is owned once |
| [ADR-003](ADR-003-lifecycle-state-is-trust-signal.md) | Lifecycle state, not a certainty score, is the trust signal |
| [ADR-004](ADR-004-behavior-adapters-and-execution-split.md) | Bind behaviors to tests through adapters, and split execution from the graph |

### Substrate — the graph everything else stands on

| ADR | Decision |
|---|---|
| [ADR-005](ADR-005-repair-parsing-substrate-in-place.md) | Repair the parsing substrate in place, stdlib-only, and never return a confidently-empty result |
| [ADR-006](ADR-006-real-interface-execution-and-coverage.md) | Behavior tests drive the app over its real interface; coverage is observed at unit, static closure at integration |

### Adoption and governance

| ADR | Decision |
|---|---|
| [ADR-007](ADR-007-bootstrap-proposed-drain-lazily.md) | Bootstrap everything as proposed, drain the corpus lazily on hit, and publish the tail |
| [ADR-008](ADR-008-declared-intent-record-required.md) | Changing an accepted guarantee requires a declared-intent record |
| [ADR-009](ADR-009-two-enforcement-tiers.md) | Two enforcement tiers: deterministic checks block, model judgment is resolve-to-proceed and fails open |
| [ADR-010](ADR-010-append-only-resolution-logs.md) | Non-fix resolutions live in append-only JSONL logs, re-judged on recurrence, behind one shared implementation |
| [ADR-011](ADR-011-governance-check-scoping.md) | Scope each governance check by which failure is recoverable |
| [ADR-012](ADR-012-accepted-behavior-downgrades-findings.md) | Only an accepted, test-backed behavior may downgrade a security finding, and a downgrade never deletes |

### Portability — running on any coding agent

| ADR | Decision |
|---|---|
| [ADR-013](ADR-013-single-freya-launcher.md) | One self-locating `freya` launcher is the sole command surface |
| [ADR-014](ADR-014-canonical-store-install-contract.md) | Install the whole suite from a canonical store by symlink, prefix in the repo, and touch only what we created |
| [ADR-015](ADR-015-driver-owned-fan-out.md) | Own the fan-out in our own driver, and run its workers under a read-only allowlist that excludes the shell |

### Process

| ADR | Decision |
|---|---|
| [ADR-016](ADR-016-prove-it-against-the-real-thing.md) | Prove it against the real thing: real dependencies, live dogfooding, committed evidence, dated-append corrections |

## Adding one

Write it when you make a decision a future maintainer could reasonably reverse without knowing
why it was made. Take the next free id, fill all four sections, and never write "none" under
Rejected Alternatives — if nothing was considered, the obvious default was rejected, so name it.

Outstanding work belongs in [`../backlog.md`](../backlog.md), not here. An ADR is a decision,
not a task.
