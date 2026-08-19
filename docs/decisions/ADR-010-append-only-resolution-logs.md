---
id: ADR-010
title: Non-fix resolutions live in append-only JSONL logs, re-judged on recurrence, behind one shared implementation
status: accepted
created: 2026-08-19
updated: 2026-08-19
tags:
  - governance
  - resolution-log
  - append-only
  - rule-of-three
---
# ADR-010: Non-fix resolutions live in append-only JSONL logs, re-judged on recurrence, behind one shared implementation

## Decision

Refute, amend, auto-clear and supersede outcomes are recorded as one JSON object per line in append-only logs (`principle-resolutions.jsonl`, `contradiction-resolutions.jsonl`, `drift-resolutions.jsonl`); records are never erased or mutated, a stale resolution is retired by appending a later record with `verdict: superseded`, and the active set is latest-wins per key with superseded keys dropped. On recurrence the LLM does not match the key — it re-validates the *specific prior reason* against the current hunk or intent text, landing in auto-clear, retire-and-re-evaluate, or escalate; a finding with no prior resolution always reaches the human. The mechanics live in one `resolution_log.py` exposing `append(path, record)`, `load(path)` and `active(records, keys_of, want)`, which `principles.py`, `contradictions.py` and `drift.py` delegate to while keeping their own relpaths, verdict sets, record schemas, CLIs and divergent `active_prior` signatures.

## Rationale

A prose-only log is write-once-read-never, and the wrap-up checkpoint must consult past resolutions or it re-nags about the same false positive on every overlapping change — the rubber-stamp erosion the enforcement model warns about (`docs/superpowers/archive/specs/2026-07-01-g2-principle-enforcement-design.md:48`). Fix and amend outcomes self-clear via git, which is why fix outcomes are deliberately not logged: git is already the record. Refute does not self-clear, and that asymmetry is the whole reason the log exists.

Append-only was chosen over the governance spec's own illustrated `status: active|superseded` mutable field. Flipping that field means rewriting a line, so the field and the append-only property are incompatible — and the property is worth more: an append-only log is tamper-evident, and its history is the record of how the team calibrated its own principles. The later-record form reproduces the spec's semantics exactly, so this is a faithful realization rather than a scope cut, guarded by `test_superseded_record_retires_the_pair` and `test_append_is_append_only` in each module.

Auto-clear is the one place a real violation could hide, so it is fenced with guardrails drawn from a worked example (`...g2-principle-enforcement-design.md:76`): if `health/route.ts` was refuted as "intentional public health check" and a later diff adds a *new* unauthenticated endpoint returning user data to that same file, the prior reason does not cover the new code, so it escalates. The rules are: bias to escalate on ambiguity; log every auto-clear as `verdict: auto-cleared` so a reviewer can see what the machine waved through versus what a person did; skip a malformed line with a warning naming the line number, so a corrupt log never crashes the run and never silently authorises an auto-clear.

The shared module is a worked rule of three. G3 stated the case for duplication plainly — "we deliberately did not extract a shared module, to avoid churning G2's shipped code" — and at two copies that trade was correct: churn risk to shipped, tested governance code outweighed the DRY win. When P4b's `drift.py` made a third copy of `append_resolution`/`_load_records`/`active_prior`, the balance flipped and the extraction was booked as its own refactor sub-project (`docs/superpowers/archive/specs/2026-07-01-shared-resolution-log-design.md:13`).

The duplication was measured before it was removed. `append_resolution` and `_load_records` were verbatim across all three modules with only the relpath differing, while `active_prior` had exactly two shapes over one algorithm — latest-wins per key, drop keys whose latest verdict is superseded, filter by the caller's query, de-dupe by append index. G2 and P4b explode a record over its `paths` and key on `(field, path)`; G3 keys once on `(spec, against)`. Both are expressible through a single `keys_of` callback, which is how `active` is parameterised (`skills/freya-spec-manager/scripts/resolution_log.py:47`).

Safety came from a hard rule rather than from review: the three existing suites (11 + 16 + 19 tests) had to pass **with no edits**, and any needed test edit was treated as a signal the refactor had changed behavior — fix the refactor, not the test. Completion was verified mechanically by grepping each module for a remaining local `latest[` loop and requiring zero hits. All three modules now import the helper (`skills/freya-spec-manager/scripts/contradictions.py:38`, `principles.py:31`, `drift.py:35`).

## Rejected Alternatives

- **A prose changelog or narrative resolution notes.** Unqueryable by the checkpoint, which is the only consumer that matters; it would leave the recurrence loop unfixed.
- **Mutating a `status` field, or deleting a record, to retire a resolution.** Both require rewriting a line, which forfeits tamper-evidence. The spec illustrated the mutable field; the later-superseded-record form gives identical semantics without the rewrite.
- **Deleting or editing stale lines in a periodic cleanup pass.** Erases the calibration history the log exists to hold.
- **Auto-clearing by stale key match on `(principle, path)` or spec id.** Triage is a fresh judgment against the specific prior *reason*, not against the file or the id — the health-check example is exactly the case a key match gets wrong.
- **Logging fix outcomes too.** Git already records them; a second record adds noise and can disagree with the tree.
- **Keeping three copies.** Correct at two, wrong at three: a fourth divergence would have made the three implementations quietly different.
- **Extracting at the second copy.** Rejected deliberately at the time — churning G2's shipped, tested code to satisfy DRY, before a third consumer proved the shape was stable.
- **Unifying the three `active_prior` signatures.** Callers depend on them. The two shapes are reconciled by closures *inside* the delegation, not by changing the public surface.
- **Adjusting the existing tests to fit the refactor.** Forbidden, because the unchanged suites are the only proof behavior was preserved.
- **Folding the security findings log into the same helper.** Different record shape and different lifecycle; sharing would have forced a lowest-common-denominator schema.

## Revisit Conditions

- If auto-clear is ever observed suppressing a real finding during dogfooding, the guardrails and the auto-clear verdict itself are back on the table.
- If the logs grow large enough that latest-wins scanning is measurably slow, add an index or compaction — but compaction must preserve the audit trail, not replace it.
- If a resolution ever needs redacting (a secret pasted into a `reason` field), append-only needs an escape hatch designed on purpose rather than improvised under pressure.
- A fourth consumer with a genuinely different key shape would pressure the `keys_of`/`want` parameterisation and justify revisiting the helper's surface.
