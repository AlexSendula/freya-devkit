---
id: ADR-009
title: "Two enforcement tiers: deterministic checks block, model judgment is resolve-to-proceed and fails open"
status: accepted
created: 2026-08-19
updated: 2026-08-19
tags:
  - governance
  - enforcement
  - wrap-up
  - fail-open
---
# ADR-009: Two enforcement tiers: deterministic checks block, model judgment is resolve-to-proceed and fails open

## Decision

Failures are gated by the kind of check that produced them, never by a model's self-reported confidence. Tier 1 is deterministic and hard-blocks — link integrity and lifecycle consistency, `adr verify`, the G1 declared-intent gate, and the accepted-behavior regression check, where wrap-up's Phase 3.5 blocks on exactly one behavior condition: an affected, accepted, non-quarantined behavior whose re-run came back `test-failed` (`skills/freya-wrap-up/SKILL.md:186`). Tier 2 is everything driven by model judgment — contradiction checking, principle enforcement, declarative drift, and anything derived from a fingerprint rather than an executed test result — and runs *after* the hard blocks as a resolve-to-proceed agent procedure, not a script exit code. Every check fails open on infrastructure failure: no principles file, no git, no diff or no baseline means the check no-ops, never a false clean and never a block.

## Rationale

A model's "high certainty" is not a calibrated probability, so a gate that fails on model confidence fails randomly. Blocking on it trains people to rubber-stamp "declare intent" to escape the noise, which corrupts the declared-intent record the whole governance model rests on — after which real violations get waved through too (`docs/design/behavior-layer/00-vision.md:157`).

Warn-only is equally wrong, because it lets a real violation slide with no adjudication. A "violation" hides two separable questions: is there really one (fallible model judgment), and given a real one, what must happen (it must be adhered to). "Don't hard-block on model confidence" answers only the first and is not a licence to let violations slide (`docs/superpowers/archive/specs/2026-07-01-g2-principle-enforcement-design.md:22`). The human running wrap-up is the calibration point: the model surfaces, the person adjudicates. Wrap-up does not complete while a finding is unresolved, "ignore and push" is not a resolution, and the three valid resolutions are **fix** (git is the record), **refute** (false positive, logged) and **amend** (the higher-authority item consciously changed, logged). Findings are resolved in the cycle that raised them — there is no standing "open principle findings" bucket in `status` or `BACKLOG.md` (`docs/superpowers/archive/plans/2026-07-01-g2-principle-enforcement.md:15`). The deterministic half of this is a script that only parses, appends and looks up; the judgment stays agent work in wrap-up (`skills/freya-spec-manager/scripts/principles.py:10`).

This stays high-signal because principles are deliberately few and sharp, so a flag is rare, and the worst case of a misjudgment is bounded: a surfaced false positive (friction) or a logged, auditable auto-clear — never a silently-pushed violation with no record. Ordering matters too: putting the advisory phase after the deterministic blocks means a run that is going to fail fails on facts first (`skills/freya-wrap-up/SKILL.md:440`).

Blocking on a `test-failed` is safe regardless of coverage quality, because it is a real test failure and not an inference. Blocking on an inference is only safe once the false-positive rate is known, and it is not. The measured FP rate is 0: editing `lib/webauthn.ts` flagged exactly the two behaviors depending on it, editing an unrelated lib (`lib/audit.ts`) flagged none, and editing the route flagged only BEH-003. But that is 3 representative changes across 2 behaviors, recorded explicitly as illustrative and not statistically significant (`docs/design/behavior-layer/02-phase-2.md:174`, `docs/design/behavior-layer/dogfooding-notes.md:129`). It validates the mechanism and says nothing about trustworthiness at scale; promoting a fingerprint check to a hard block on that evidence would block builds on a guess.

Fail-open is intentional and is stated twice over, with an explicit instruction not to "harden" it into a block, because a check that blocks on a corrupt baseline or a missing git would make wrap-up unusable exactly when it is most needed. G1 is the deliberate counterexample — it can hard-block precisely because it is a git-and-files computation with no model in it, and it still fails open on git error (`skills/freya-spec-manager/scripts/verify_intent.py:20`). Scoping Tier 2 by category and blast radius rather than re-deriving the whole repo keeps it incremental and quiet enough to be trusted (`docs/design/behavior-layer/00-vision.md:146`). `principles.md` gets exactly two enforcement mechanisms and no more: soft injection into the working context of brainstorming, planning and wrap-up, and a checkpoint diff at wrap-up and code-review. Promotion of a declarative decision into a guard scenario is recommended where cheap and never required — a decision that genuinely cannot be tested staying declarative is the honest ceiling of what tests can do, not a failure (`docs/design/behavior-layer/00-vision.md:41`).

## Rejected Alternatives

- **Hard-block on model confidence, or auto-fail via a script exit code.** Uncalibrated confidence produces random failures and reflexive overrides. Deferred as P4d until a false-positive rate is measured on a real project.
- **Pure warn-only advisory output.** A warning nobody has to answer is a violation with no adjudication. Resolve-to-proceed makes a refute a deliberate, recorded act rather than a shrug.
- **Whole-repo contradiction re-derivation on every change.** Noisy and slow, so it gets ignored or switched off — which is worse than not running it.
- **Treating `principles.md` as enforcement simply by existing.** A passive file is not a mechanism; injection and the checkpoint diff are.
- **Requiring every declarative decision to become a guard scenario.** Some decisions are genuinely untestable, and pretending otherwise produces ceremonial tests.
- **Making Tier 2 ADR-aware before an ADR format existed.** Checking specs against ADRs would have referenced machinery that did not yet exist; it landed with P4a once `decisions/` was real.
- **Hard-blocking on fingerprint-derived checks now.** The supporting evidence is 2 behaviors and 3 changes. Blocking on that is blocking on a guess.
- **Keeping everything advisory, including real test failures.** That leaves wrap-up unable to stop a regression, which defeats the point of running behaviors at all.
- **Running every accepted behavior regardless of lifecycle state, including quarantined ones.** Quarantine exists to keep known-flaky infrastructure out of the blocking path; only `accepted` is authoritative (`skills/freya-spec-manager/references/spec-template.md:119`).
- **Failing closed on git errors, a missing baseline, or a corrupt marker.** Wrap-up would break hardest exactly when the repo is already in trouble.
- **A standing backlog bucket for open principle findings.** A bucket is where findings go to be ignored; they are resolved in the cycle that raised them.

## Revisit Conditions

The sole trigger for moving anything up a tier is evidence: measure the Tier-2 false-positive rate on a real project, and fingerprint precision on a suite large enough to be meaningful. With that evidence, the deferred calibrated hard gate (P4d) becomes supportable. Also revisit if refutes start being rubber-stamped — that would mean the human calibration this design depends on has stopped working.
