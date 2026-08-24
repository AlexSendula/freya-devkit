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

- **Its own baseline marker.** `verify_intent` keeps `knowledge-base/intents/.intent-last-verified` (`skills/freya-spec-manager/scripts/verify_intent.py:56`), advanced only after the gate passes. Reusing `.spec-last-update` would silently disable G1 entirely: wrap-up advances that marker in Phase 3 (spec-manager update) **before** the Phase 3.5 check runs, so at check time `baseline == HEAD`, the diff is empty, and every edit passes. The ordering hazard is documented in the module docstring and guarded by a dedicated test pinning "baseline == HEAD → no false pass/fail".
- **Diffs the working tree, not HEAD.** In the two-commit flow the test edit lands in commit 1 while the record is staged for commit 2, and the check runs between them — reading only HEAD would miss the record.
- **Discovers in-change records by scanning the filesystem** and testing existence at the baseline (`git cat-file -e <baseline>:<path>`). Finding records via `git diff` would miss an untracked new record and block an engineer who had already written one.
- **Emits complete JSON on a non-zero exit,** so callers must read the JSON rather than using `check=True` — the wrap-up step says so explicitly (`skills/freya-wrap-up/SKILL.md:166`).
- **Skips rather than blocks when no baseline exists,** so a fresh repo or a full-scan run can still wrap up.

It ships as a sibling script to `verify_links` rather than folded into it.

> **Correction, 2026-08-24 (SEC-001, SEC-011).** Two clauses above are now narrower than they read, and the reason is that the marker is a file the *scanned repository* commits. This record treated it as toolkit bookkeeping; it is untrusted input in a git revision slot, and five marker *shapes* got a Tier-1 gate to state it had run over a change-set it had not read — **but not all with the same signature, and the difference is what a test for them has to assert.** Shapes 1–4 each produced `skipped: false` with exit 0, the fingerprint of a gate that read a real change-set and found nothing wrong. Shape 5 is three marker values that produced the opposite half of the same lie: a bare `None` baseline, so **`skipped: true`** with an empty `warnings` list and the fresh-repo note — byte-identical to a repository that has never been gated, which is why `--advance` then moved the baseline and erased the finding, and why the fix for it lives in `_read_baseline` rather than in the argv handling that closed 1–4. Each shape passed the fix written for the one before it, so the list is the record and not the history:
>
> 1. `--output=<file>` — an OPTION, not a revision. git truncates the named file, writes the diff into it and returns rc=0 with empty stdout. Stopped by shape-validating the marker (`_COMMIT_RE`, `verify_intent.py:81`) and, independently, by `--end-of-options`.
> 2. Forty zeros — valid hex, so the regex passes it; git fails rc=128 and the empty result was indistinguishable from "nothing changed". Stopped by returning `ok=False` and labelling the run `skipped` (`_changed_status`, `verify_intent.py:144`).
> 3. A committed file named `deadbeef` — pure hex, so the regex passes it, and git resolves it as a PATHSPEC at rc=0. Stopped by `--`.
> 4. A hex TREE hash from `git rev-parse HEAD:knowledge-base` — walks past the regex, `--end-of-options` and `--` alike, because git will diff a tree against the working tree. Everything outside the chosen subtree then reports as `A`, which `_is_change` calls free. Stopped only by peeling `^{commit}`, which also subsumes shape 3.
> 5. A marker holding `commit:` with no value, a marker with no `commit:` line, and a zero-byte marker — each returned a bare `None`, which is the exact fingerprint of a fresh repository, so `--advance` exited 0 and erased the finding. Stopped by making every branch that returns `None` for a marker that *exists* return a warning with it (`_read_baseline`, `verify_intent.py:94`).
>
> The shipped argv is `diff --name-status -M --end-of-options <baseline>^{commit} --` (`verify_intent.py:219`–`:220`). Only two of those three added tokens are refusals; `--` is now redundant as one and is kept for the opposite reason, because a repository that commits a file named `<its own marker sha>^{commit}` makes the argument ambiguous without it, which is rc=128 on every run — denial rather than a false clean, and just as quiet. The measured table is in `_changed_status`'s docstring.
>
> **What rc=0 buys, and the residue this record owns.** It means git resolved the marker to a commit *in this repository* and diffed it. It does not mean the commit is one this toolkit chose, so a repository willing to write `commit: <its own HEAD>` gets an honest diff of nothing and a truthful exit 0. That is this ADR's trust model for the marker rather than a bypass — the marker is the repository's own bookkeeping and always was — but nothing said it out loud until now (`verify_intent.py:207`–`:211`).
>
> **The fifth mechanics clause is two states now, not one.** "No baseline exists" splits into *no marker at all*, which is BEH-090 and still skips and still advances, and *a marker that exists and is unusable*, which skips and must not advance. `--advance` is a separate exit code for that: `advance_if_clear` refuses when the gate is blocking **or** when it did not run (`verify_intent.py:547`), and the CLI exits **2** for either, with different wording so the operator is not sent looking for a `BEH-NNN` the gate never produced (`verify_intent.py:647`, `:657`). The discriminator is structural rather than a list of attack shapes — `baseline is None and no warnings` is reachable from the absent marker and from nowhere else (`_skipped_without_checking`, `verify_intent.py:509`). `--force` remains the escape hatch for both refusals. Before this, `--advance` gated on `unauthorized`/`errors` alone, so one corrupt file in `knowledge-base/intents/` moved the baseline to HEAD with an empty stderr and bought a permanent clean sheet.
>
> **Consumers must read `skipped` before trusting exit 0.** Exit 0 has always covered both "nothing to authorize" and "the gate did not run"; what changed is that the second now always says so in the JSON and on stderr. The module docstring states it (`verify_intent.py:23`); this record now does too.

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
