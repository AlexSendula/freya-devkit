---
id: ADR-008
title: Changing an accepted guarantee requires a declared-intent record
status: accepted
created: 2026-08-19
updated: 2026-08-19
tags:
  - governance
  - intent-records
  - gate
  - determinism
---
# ADR-008: Changing an accepted guarantee requires a declared-intent record

## Decision

An accepted, non-quarantined behavior that fails blocks completion until it is classified as exactly one of three things: a regression (the code is wrong), an intended change (recorded as a durable `INTENT-NNN` artifact naming the behaviors touched, a rationale and an approver), or a test-infrastructure failure (flaky, fixture or environment — resolved by quarantine, which removes the behavior from the authoritative set until repaired). A bare code change that breaks an accepted test is always a regression or an infra failure, never a license to edit the test. This ships as gate G1: modifying or deleting the locator of a behavior that is `accepted` at HEAD hard-blocks wrap-up unless an `INTENT-NNN` record filed in the same change-set names that behavior.

## Rationale

The classification gate is what ties regression-safety, coverage and design-time awareness into one mechanism, and it is deliberately narrower than "every red test means broken code" — it only forbids an accepted behavior failing silently or unclassified (`docs/design/behavior-layer/00-vision.md:26`). The `INTENT-NNN` artifact has to be durable and machine-checkable because without a record "declared intent" is unenforceable and every red test degrades into "just update it" until the safety net rots (`docs/design/behavior-layer/00-vision.md:122`).

G1 plugs the one blind spot in the fact layer. Code-versus-test disagreement is checkable by running the test, and a red accepted test hard-blocks — the strongest guarantee in the system. But changing the code **and** the test together leaves the suite green, so the fact layer sees nothing even though the guarantee has been silently redefined. That is the only way to slip a changed guarantee past the strongest check. "Was an accepted test edited, and does a record name it?" is itself a fact, so closing the hole stays fully deterministic and needs no new machinery: intersect the change-set's changed files with accepted behaviors' locators, both of which already exist. Scoping is temporal — a record counts only if it is new since the baseline — so a past record cannot bless a future edit. Before G1, the blocking rules already told engineers to "file an `INTENT-NNN`" while the artifact did not exist, leaving an intentional change to an accepted guarantee with no legitimate path through the gate.

Newly-added locators, pure renames, and edits to non-accepted behaviors require nothing. The record file — not the commit trailer — is the source of truth, and the gate checks only that such a record exists.

Every mechanics clause names a way the gate would otherwise fail open:

- **Its own baseline marker.** `verify_intent` keeps `knowledge-base/intents/.intent-last-verified` (`skills/freya-spec-manager/scripts/verify_intent.py:45`), advanced only after the gate passes. Reusing `.spec-last-update` would silently disable G1 entirely: wrap-up advances that marker in Phase 3 (spec-manager update) **before** the Phase 3.5 check runs, so at check time `baseline == HEAD`, the diff is empty, and every edit passes. The ordering hazard is documented in the module docstring and guarded by a dedicated test pinning "baseline == HEAD → no false pass/fail".
- **Diffs the working tree, not HEAD.** In the two-commit flow the test edit lands in commit 1 while the record is staged for commit 2, and the check runs between them — reading only HEAD would miss the record.
- **Discovers in-change records by scanning the filesystem** and testing existence at the baseline (`git cat-file -e <baseline>:<path>`). Finding records via `git diff` would miss an untracked new record and block an engineer who had already written one.
- **Emits complete JSON on a non-zero exit,** so callers must read the JSON rather than using `check=True` — the wrap-up step says so explicitly (`skills/freya-wrap-up/SKILL.md:166`).
- **Skips rather than blocks when no baseline exists,** so a fresh repo or a full-scan run can still wrap up.

It ships as a sibling script to `verify_links` rather than folded into it.

## Rejected Alternatives

- **The "just update the test" reflex.** The default this ADR exists to forbid: it converts a broken guarantee into a green suite with no record that anything changed.
- **Chat history or an unstructured commit message as the record.** Nothing can check either one later.
- **The stricter rule that any failing test means broken code.** Dishonest about flakes, fixtures and environments — which is exactly why quarantine is a first-class resolution.
- **Relying on the red-test gate alone.** It cannot see a code-plus-test change, the one path that redefines a guarantee while staying green.
- **Content-hash fingerprinting of accepted tests.** Temporal scoping gives the same self-scoping property with no extra state to maintain.
- **Exempting cosmetic edits.** Any edit triggers the requirement "regardless of what", because judging an edit cosmetic is precisely the judgment a deterministic gate refuses to make.
- **Making the `Intent:` commit trailer gate-enforcing.** Rebase and amend mangle commit messages, so the trailer stays strongly-recommended traceability.
- **Verifying that the rationale is honest, or that the description still matches the changed test.** Judgment, deferred to the advisory tier; G1 checks presence only.
- **Authenticating the approver.** Identity cannot be verified deterministically, so the approver is captured, not authenticated; sign-off is left to PR review, and the record's value is the durable conscious confirmation.
- **Replacing the frontmatter parser as a precondition.** The record format is block-style lists only, which sidesteps the inline-array drop without a rewrite.
- **Reusing `.spec-last-update`, diffing only committed state, and finding records with `git diff`.** Each fails open, as detailed above.
- **Folding the transition check into `verify_links`.** That script is a stateless single-snapshot check, which a baseline diff would muddy.
- **Blocking when no baseline exists.** A fresh repo or a full-scan run could never wrap up.
- **Treating every referential problem alike.** A record naming a non-existent BEH is a warning; a malformed record missing `behaviors:` fails loud, because a broken record must never silently "cover" anything.

## Revisit Conditions

- Known gap: assertions living in a helper file that is not the declared locator escape the path-based check (a content-hash approach shares this limitation). Widening detection to the test's import closure would close it.
- If quarantine becomes the routine escape hatch — a rising share of accepted behaviors quarantined — the gate is being gamed and needs a time limit or a review step.
- If wrap-up's phase ordering changes, re-verify that the baseline marker is advanced only after the gate passes.
- If presence-only checking proves too weak and the judgment layer never lands, reopen.
