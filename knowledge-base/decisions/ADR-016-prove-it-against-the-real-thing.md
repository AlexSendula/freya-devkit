---
id: ADR-016
title: Prove it against the real thing: real dependencies, live dogfooding, committed evidence, dated-append corrections
status: accepted
created: 2026-08-19
updated: 2026-08-19
tags:
  - process
  - testing
  - evidence
  - design-records
---
# ADR-016: Prove it against the real thing: real dependencies, live dogfooding, committed evidence, dated-append corrections

## Decision

The project's evidence discipline has four clauses. Tests drive real dependencies wherever a real
one can be produced honestly — the updater's tests run real `git` in temporary directories, an
origin repo plus a clone — and injected runners are reserved for behaviour a real dependency cannot
produce honestly and for calls that cost money or are non-deterministic; guards that protect
against a measured external finding are mutation-tested, not merely unit-tested. Mechanisms are
validated by dogfooding in contact with a real project rather than by an isolated proof. Live
validation runs commit their load-bearing extracts under a versioned `evidence/` directory, cited
by path from the prose. A superseded statement in a design record keeps its original wording and
receives a dated `> **Correction …**` block underneath it; where a correction and the original
disagree, the authority order is shipped code first, then the correction, then the original.

## Rationale

**Real dependencies.** Phase 4b's finding is the case against mocks: they model a well-behaved
dependency and leave the failure paths unexamined — which is exactly where an update command lives,
since almost all of its interesting behaviour is a refusal. `git` is free and deterministic, so
there is no cost argument for repeating the mistake
(`docs/superpowers/archive/specs/2026-08-14-phase-5-update-init-design.md:186`). The shipped tests
cover fast-forward, dirty refusal, missing upstream, non-git store and a diverged branch, and skip
cleanly when `git` is absent (`bin/test_updater.py`). The injected-runner exception is drawn on the
same principle rather than against it: a hang cannot be produced honestly any other way, so the
notify check takes an injected runner and asserts that a fresh cache makes no network call
(`bin/test_updater.py:945`), that a stale one checks again (`bin/test_updater.py:956`), that an
unreachable remote stays silent while still stamping the clock (`bin/test_updater.py:979`), and
that a raising runner cannot change the command's exit code (`bin/test_updater.py:1019`). The audit
driver's `ask` is injected for the same reason: real calls cost money and are non-deterministic.

**Dogfooding over isolated proof.** Building horizontal infrastructure or governance ahead of
evidence risks building the wrong mechanism carefully. The staged Phase 0 vertical proof was
deliberately dropped and its validation folded into Phase 1's first real use on the testbed, with
phase order mechanism-first: traceability MVP, then impact indexing, then governance, then
expansion. This was recorded as a conscious risk trade — some Phase 1 schema, lifecycle and adapter
choices were provisional and expected to be corrected in contact with reality
(`docs/design/behavior-layer/00-vision.md:163`). That is exactly what happened: the four-state
lifecycle gained `confirmed` once real use demanded it.

**Dated-append corrections.** The reasoning that led somewhere else is the useful part of a design
record; silently rewriting it leaves the *why* unrecoverable and lets the same wrong path be taken
twice. The convention's value shows in what it caught across nine correction blocks
(`docs/design/portability/00-vision.md:5`): a struck "Part B has not been run" line that had
survived two commits appending Part B; a green checkmark for live loop-until-dry termination that
the run's own arithmetic refutes — with 6 categories, 3 skeptics and `K_EMPTY = 2`, Claude's 22
calls and 3 findings solve uniquely to two discovery rounds, which cannot contain the two
consecutive dry rounds `K_EMPTY` requires, so that run ended on `--max-findings 3`, not on dryness
(`docs/design/portability/phase-6-validation-log.md:193`); and a "still unproven" list that bundled
three answered questions with one genuinely open one, which made the open item read as noise
(`docs/design/portability/phase-6-validation-log.md:374`).

**Committed evidence.** This clause was adopted after a concrete loss. Everything in the phase-7
log is prose transcription with no raw artifact committed, including the 800 KB
`--log-level debug` log that is the sole source for the tool-invocation table and for the quoted
Copilot system-prompt clauses. It lived under `/tmp` and is gone
(`docs/design/portability/phase-7-validation-log.md:16`). Nothing in it is doubted; the cost is that
a maintainer asking "did Copilot's delegation policy change in CLI 1.1.x?" has no baseline to diff
against and must re-derive the finding from scratch, re-purchasing agent quota to do it. The
minimum committed set is therefore the tool-invocation counts, the quoted host prompt blocks, and
one full driver stderr transcript per adapter.

## Rejected Alternatives

- **Mocking the git runner throughout.** Mocks model a well-behaved dependency; the updater's
  interesting behaviour is refusal, which a well-behaved mock never produces.
- **Using real git for the notify check's timeout and hang cases.** A hang cannot be produced
  honestly with a real dependency, so an injected runner is the correct instrument there.
- **A staged Phase 0 vertical proof validating the loop in isolation.** Duplicated effort against a
  real dogfooding run that would exercise the same loop under real conditions.
- **Building the behavior graph or governance before the loop was validated.** Pushed to later
  phases; Phase 1 shipped with no `behavior.json` and no model-based checks precisely so the
  mechanism could be judged first.
- **Bundling the `knowledge-base/` IA migration into the behavior work.** It shipped as its own
  standalone PR, early and cheap, so a mechanical rename could not confound the validation
  (`docs/design/behavior-layer/00-vision.md:172`).
- **Editing a design in place and deleting the superseded text.** The standard move, rejected
  because it makes the reasoning unrecoverable and invites re-walking the same wrong path.
- **Deleting the design record once the work ships and relying on code plus git history.** Code
  records what was built, never what was considered and refused.
- **Treating prose transcription of a live run as sufficient evidence.** Phase 7 did exactly this
  and the underlying artifact is now unrecoverable.
- **Leaving the correction and the original with equal standing.** Without declaring shipped code
  the ground truth, a reader has no tiebreaker when the two disagree.

## Revisit Conditions

- The evidence clause is currently **unfulfilled**: no committed extract exists anywhere in the
  tree, and the `docs/design/portability/evidence/` drop zone — which never held more than a
  README and a `.gitkeep` — went with the design tree on 2026-08-19. The next live validation run
  must create `knowledge-base/evidence/` and produce the first committed extract (see
  [`../backlog.md`](../roadmap.md) § "Whatever runs live next"), or the clause should be withdrawn
  rather than left aspirational.
- If real-git tests become slow enough to hurt the suite, or CI environments without `git` stop
  being an edge case, the skip-when-absent posture is worth revisiting.
- If provisional choices start requiring expensive migrations rather than cheap corrections, the
  cost of skipping an isolated proof has exceeded its saving and the phasing rule should be
  reopened.
