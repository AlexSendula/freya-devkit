# Decisions

Architecture Decision Records — **what was decided, why, and what was rejected.**

The rejected alternatives are the point. Anyone can read the code to learn what the system
does; only these records say what it could have been and why it isn't. When a question comes
back around, start here so it doesn't get re-litigated from scratch.

These twenty-nine records were distilled from the design documents, specs and implementation
plans accumulated between 2026-06 and 2026-08 — roughly fifty files that mixed decisions with
tasks, status and superseded reasoning — and, for ADR-018 onward, from Track B's own working
record. The originals are in git history; what mattered is here.

**Distillation is not transcription.** Every record was re-verified against the code as it was
written, and several claims did not survive: behaviour asserted in the present tense that no
code implements, and measured figures that no longer reproduce. Where a promise turned out to
be unimplemented it is recorded as unimplemented — see ADR-021 on per-edge provenance, which
had been stated as an enforced gate in four separate documents. A record that overstates the
system is worse than no record, because it is believed.

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

**The tooling sees this directory.** `adr.py` reads `knowledge-base/decisions/`
(`DECISIONS_RELDIR`, `adr.py:29`), which is where these records now live, so
`freya adr verify --project .` checks all twenty-nine and `freya adr list` prints them.
Until 2026-08-21 they sat in a hand-written `docs/decisions/` the tooling could not reach,
and schema conformance was something you had to remember to check by hand. New records are
still written by hand — `adr.py` verifies and lists, it does not author.

**Authority order: shipped code beats an ADR beats a spec.** An ADR records the decision, not
the implementation. Where they disagree, the code is right and the ADR needs a correction —
add one rather than rewriting history.

> **On the citations.** Records here cite their sources by `path:line`. Citations into
> `skills/`, `bin/` and the rest of `knowledge-base/` resolve against the working tree.
> Citations into `docs/design/…`, `docs/superpowers/…` or `docs/polyglot/…` do **not** — those
> are the documents these ADRs were distilled from — the first two deleted on 2026-08-19,
> `docs/polyglot/` on 2026-08-21. They resolve against git history: `git log --all -- <path>`,
> or `git show 04a9b8b:<path>` for the first two and `git show 2762d54:<path>` for
> `docs/polyglot/`. The line numbers are exact as of that commit and are kept deliberately,
> because a citation without a line is not provenance.
>
> A working-tree citation written before 2026-08-21 may name `docs/…`: on that date this
> repo's whole documentation tree moved to `knowledge-base/` and `architecture.md`,
> `conventions.md` and `skill-reference.md` were renamed to
> `reference/ARCHITECTURE.md`, `reference/DEVELOPER.md` and `reference/SKILL_REFERENCE.md`,
> with `backlog.md` becoming `roadmap.md`. The line numbers survived the move; the paths
> did not.

## The records

### Foundations — what the system fundamentally is

| ADR | Decision |
|---|---|
| [ADR-001](ADR-001-behavior-as-executable-artifact.md) | Intended behavior is a first-class executable artifact |
| [ADR-002](ADR-002-authority-order-single-ownership.md) | Authority runs principle > ADR > spec > reference, and every fact is owned once |
| [ADR-003](ADR-003-lifecycle-state-is-trust-signal.md) | Lifecycle state, not a certainty score, is the trust signal |
| [ADR-004](ADR-004-behavior-adapters-and-execution-split.md) | Bind behaviors to tests through adapters, and split execution from the graph |
| [ADR-017](ADR-017-behavior-json-is-committed.md) | Commit `behavior.json`; ignore only the regenerable parse cache |

### Substrate — the graph everything else stands on

| ADR | Decision |
|---|---|
| [ADR-005](ADR-005-repair-parsing-substrate-in-place.md) | Repair the parsing substrate in place, stdlib-only, and never return a confidently-empty result |
| [ADR-006](ADR-006-real-interface-execution-and-coverage.md) | Behavior tests drive the app over its real interface; coverage is observed at unit, static closure at integration |
| [ADR-018](ADR-018-substrate-contract-for-the-code-graph.md) | The code graph is produced through a contract, not by one resolver |
| [ADR-019](ADR-019-the-floor-and-choosing-a-backend.md) | The floor always ships, and any other backend runs because a person named it |
| [ADR-020](ADR-020-the-contract-persists-the-graph.md) | The contract persists the graph; a backend only produces it |
| [ADR-021](ADR-021-an-edge-is-an-object-with-kind-and-provenance.md) | An edge is an object carrying kind and provenance, behind a versioned schema |
| [ADR-022](ADR-022-every-exclusion-default-is-arguable.md) | Every built-in exclusion is a default a project can overrule, in two tiers |
| [ADR-023](ADR-023-symbol-graph-projected-onto-file-pairs.md) | A symbol graph is projected onto file pairs, and nothing intra-file becomes an edge |
| [ADR-024](ADR-024-symbols-refine-an-anchor-never-replace-it.md) | Symbols refine a file anchor, never replace it, and stay off by default |
| [ADR-025](ADR-025-three-artifacts-joined-on-file-path.md) | Three artifacts, one owner each, joined on file path |
| [ADR-026](ADR-026-the-docs-graph-anchored-at-section.md) | The docs graph anchors at section, and markdown splits only at headings |
| [ADR-027](ADR-027-what-is-not-graph-material.md) | Config-as-code and migrations are not graph material |
| [ADR-028](ADR-028-graphs-are-stored-per-backend.md) | Each backend writes its own graph beside the active one |
| [ADR-029](ADR-029-an-answer-says-what-it-could-not-read.md) | Every answer says what the backend could not read, and it is never a refusal |

ADR-018 through ADR-029 are the polyglot substrate (Track B), distilled from a working record
of twenty-seven candidate decisions. Twelve records rather than twenty-seven because several
entries answered one question in parts, and five recorded the order of the feature's own phases
rather than anything that outlives it. Read ADR-018 first; ADR-019 and ADR-029 are the two a
reader is most likely to need.

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

Outstanding work belongs in [`../backlog.md`](../roadmap.md), not here. An ADR is a decision,
not a task.
