---
id: SPEC-028
title: The Status Census
category: features
tags: [status, worklists, behaviors, coverage, security, degradation, read-only]
status: implemented
certainty: 80
created: 2026-08-21
updated: 2026-08-21
related_code:
  - skills/freya-status/scripts/collect_status.py
  - skills/freya-status/SKILL.md
  - bin/commands.json
intentional_decisions:
  - "Every source degrades to an empty bucket plus a named note — one unavailable input never takes out the report"
  - "The report never blocks and always exits 0, whatever it finds"
  - "verify_links' non-zero exit is a findings signal, not a failure — its JSON is read, never discarded by check=True"
  - "behavior_census accepts a project root or a specs directory, so a path that does not exist reports zero rather than raising"
  - "A spec that cannot be parsed or decoded is skipped, not fatal — one stray byte used to end the whole walk"
behaviors:
  - behavior_id: BEH-136
    title: The census counts every behavior in the specs tree by lifecycle state
    state: proposed
    level: unit
    adapter: unittest
    locator: skills/freya-status/scripts/test_collect_status.py#CensusTest.test_counts_by_state
  - behavior_id: BEH-137
    title: A proposed behavior reaches the intent worklist carrying its parent spec's certainty, so review can start with the least-trusted intent
    state: proposed
    level: unit
    adapter: unittest
    locator: skills/freya-status/scripts/test_collect_status.py#CensusTest.test_intent_worklist_is_proposed_with_certainty
  - behavior_id: BEH-138
    title: A confirmed behavior reaches the test-owed worklist, and is the only state that does
    state: proposed
    level: unit
    adapter: unittest
    locator: skills/freya-status/scripts/test_collect_status.py#CensusTest.test_test_owed_worklist_is_confirmed
  - behavior_id: BEH-139
    title: A project with no specs directory reports an empty census instead of failing
    state: proposed
    level: unit
    adapter: unittest
    locator: skills/freya-status/scripts/test_collect_status.py#CensusTest.test_missing_specs_dir_is_empty
  - behavior_id: BEH-140
    title: A spec file that cannot be parsed or decoded is skipped and the walk continues over the rest
    state: proposed
    level: unit
    adapter: manual
    locator: skills/freya-status/scripts/test_collect_status.py#CensusTest.test_an_unreadable_spec_does_not_stop_the_walk
  - behavior_id: BEH-141
    title: Only findings still open reach the report — resolved and intentional ones are left out
    state: proposed
    level: unit
    adapter: unittest
    locator: skills/freya-status/scripts/test_collect_status.py#SecurityBucketTest.test_open_findings_only
  - behavior_id: BEH-142
    title: A behavior whose captured coverage was fingerprinted at some commit other than HEAD is reported stale
    state: proposed
    level: unit
    adapter: unittest
    locator: skills/freya-status/scripts/test_collect_status.py#StaleBucketTest.test_stale_when_freshness_differs_from_head
  - behavior_id: BEH-143
    title: Link-integrity errors survive the checker's non-zero exit instead of being read as a clean run
    state: proposed
    level: unit
    adapter: unittest
    locator: skills/freya-status/scripts/test_collect_status.py#VerifyBucketTest.test_returns_errors_even_when_subprocess_exits_nonzero
  - behavior_id: BEH-144
    title: Each unavailable source degrades to an empty bucket plus a note naming what was missing, never a crash
    state: proposed
    level: unit
    adapter: unittest
    locator: skills/freya-status/scripts/test_collect_status.py#SecurityBucketTest.test_missing_findings_is_note
  - behavior_id: BEH-145
    title: The command exits 0 whatever it finds — it reports outstanding work, it never blocks
    state: proposed
    level: integration
    adapter: manual
    entry: skills/freya-status/scripts/collect_status.py
    locator: skills/freya-status/scripts/test_collect_status.py#MainTest.test_status_exits_zero_with_work_outstanding
---

# The Status Census

## What

`freya status` answers "where do I stand" from five independent sources and mutates nothing
(`collect_status.collect`, `collect_status.py:154`). The answer is one document: a census of
every behavior in `knowledge-base/specs/**` by lifecycle state, the two worklists that drain
that census (`proposed` → confirm, `confirmed` → write a test), whole-repo coverage gaps,
Tier-1 link-integrity failures, behaviors whose captured coverage fingerprint predates HEAD,
and open security findings. `--format json` emits it whole for an agent; the text form prints
one line per bucket plus every note.

The census walks the specs tree itself rather than reading a projection, because `proposed`
behaviors deliberately never reach `behavior.json` (ADR-007). Each `proposed` record inherits
its parent spec's `certainty` (`collect_status.py:78`) and the worklist is sorted
lowest-certainty first (`:82`), which is the order `status review intent` documents working in.

Four of the five sources are external: the behavior graph for gaps, `verify_links` for link
integrity, `behavior.json` for fingerprint freshness, and `findings.json` for security. Every
one of them can be missing on a partially-onboarded project, and each failure is contained to
its own bucket — an empty result plus a note saying which input was absent.

## Why

`status` exists because "where do I stand" and "do and sync everything" are different
questions, and a toolkit that only answers the second cannot be asked the first without
changing state. ADR-007 records that split and why the read-only half was kept out of
`wrap-up` rather than added as a mode of it.

The degradation rule is the load-bearing part. This report is the first thing run on a project
part-way through adoption — that is its whole purpose — so the normal case is that two or three
of its five inputs do not exist yet. A single unhandled `FileNotFoundError` would make the
command useless exactly when it is most needed, and a bucket that silently returned zero would
be worse: an empty "open security findings" list reads as *clean*, not as *never scanned*. The
note is what separates the two, and it is why each source returns `(value, note)` rather than
just a value.

The certainty inheritance exists so review can be spent in a useful order. A bootstrap corpus
is a pile of guesses of varying quality; working the least-confident first is how the pile
turns into signal rather than a uniform slog.

## Behavior

| Behavior | State | Verified by |
|----------|-------|-------------|
| BEH-136 The census counts every behavior in the specs tree by lifecycle state | proposed | `test_collect_status.py#CensusTest.test_counts_by_state` (unittest) |
| BEH-137 A proposed behavior reaches the intent worklist carrying its parent spec's certainty | proposed | `test_collect_status.py#CensusTest.test_intent_worklist_is_proposed_with_certainty` (unittest) |
| BEH-138 A confirmed behavior reaches the test-owed worklist, and is the only state that does | proposed | `test_collect_status.py#CensusTest.test_test_owed_worklist_is_confirmed` (unittest) |
| BEH-139 A project with no specs directory reports an empty census instead of failing | proposed | `test_collect_status.py#CensusTest.test_missing_specs_dir_is_empty` (unittest) |
| BEH-140 A spec file that cannot be parsed or decoded is skipped and the walk continues | proposed | **no test** — `test_collect_status.py#CensusTest.test_an_unreadable_spec_does_not_stop_the_walk` is where one belongs (manual) |
| BEH-141 Only findings still open reach the report | proposed | `test_collect_status.py#SecurityBucketTest.test_open_findings_only` (unittest) |
| BEH-142 A behavior fingerprinted at some commit other than HEAD is reported stale | proposed | `test_collect_status.py#StaleBucketTest.test_stale_when_freshness_differs_from_head` (unittest) |
| BEH-143 Link-integrity errors survive the checker's non-zero exit | proposed | `test_collect_status.py#VerifyBucketTest.test_returns_errors_even_when_subprocess_exits_nonzero` (unittest) |
| BEH-144 Each unavailable source degrades to an empty bucket plus a note | proposed | `test_collect_status.py#SecurityBucketTest.test_missing_findings_is_note` (unittest) |
| BEH-145 The command exits 0 whatever it finds | proposed | **no test** — `test_collect_status.py#MainTest.test_status_exits_zero_with_work_outstanding` is where one belongs (manual) |

BEH-142's other edge is `StaleBucketTest.test_fresh_when_matches_head`; BEH-144 holds three
tests across three sources — `SecurityBucketTest.test_missing_findings_is_note`,
`StaleBucketTest.test_missing_behavior_json_is_note` and
`VerifyBucketTest.test_bad_json_degrades_to_note` — because a degradation rule stated once for
all sources is only worth having if it holds at each of them. `VerifyBucketTest.test_empty_stdout_is_clean`
holds the opposite edge for BEH-143: a genuinely clean run must not manufacture a note.

Two gaps. **BEH-140** guards a regression that already happened once: the `except` at
`collect_status.py:59` carries the comment that a `UnicodeDecodeError` is not an `OSError` and
that strict decoding of one spec with a stray byte "raise[d] out of the whole status walk".
The fix is in the code and nothing asserts it, so the same class of failure can return
silently. **BEH-145** is the never-blocks guarantee — `main` returns 0 unconditionally
(`collect_status.py:262`) — which is stated in ADR-007, in the skill and in the module
docstring, and is checked by nothing: no test invokes `main` at all.

## Intentional Design Decisions

### Every source degrades independently, and says so

**Decision**: A missing graph, missing `findings.json`, missing `behavior.json`, unreadable
JSON or an unavailable subprocess yields that bucket's empty value plus a `note`, and the other
four buckets are unaffected. Nothing raises out of `collect`.

**Rationale**: ADR-007 — a partially-onboarded project is the expected input, not the error
case. The note is the part that matters: it distinguishes "zero open findings" from "no scan
has ever run", which are the same number and opposite facts.

**Security Scan Note**: The broad `except` clauses around every file read and subprocess call
are deliberate containment, not swallowed errors. Narrowing them, or letting one propagate so
the caller "knows something went wrong", breaks the guarantee this command exists to provide.
The failure is reported through the `notes` list, not through an exception.

### `check=True` is used on exactly one subprocess call, and deliberately not on the other

**Decision**: `gaps_bucket` uses `check=True`; `verify_bucket` does not, and says why in place
(`collect_status.py:102`–`:104`).

**Rationale**: `behavior-graph --gaps` always exits 0 — a missing graph comes back as a JSON
`note` — so a non-zero exit there really is a failure. `verify_links` exits non-zero *because
it found link errors*, and those errors are its stdout. Adding `check=True` there would raise
on precisely the runs that have something to report, and the report would say zero failures.

**Security Scan Note**: The inconsistency between two adjacent `subprocess.run` calls is
intentional and is pinned by `VerifyBucketTest.test_returns_errors_even_when_subprocess_exits_nonzero`,
whose docstring names the false-green it prevents. "Add `check=True` for consistency" is a
regression, not a cleanup.

### The census accepts a project root or a specs directory

**Decision**: `behavior_census` resolves `<project>/knowledge-base/specs` if that exists and
otherwise treats the argument itself as a specs directory (`collect_status.py:46`–`:48`). A
path that exists as neither reports an all-zero census rather than raising.

**Rationale**: The tests pass a specs directory directly, and the docstring says so. It also
falls out of the degradation rule — a project with no specs tree yet is the ordinary state of a
project about to be onboarded.

**Security Scan Note**: A user-supplied path that does not exist producing a successful,
all-zero result looks like a swallowed error. It is the documented contract (BEH-139). Note the
consequence honestly: a typo'd `--project` reports a clean, empty project rather than
complaining, and nothing currently distinguishes the two.

### Only `open` findings count as outstanding

**Decision**: `security_bucket` keeps findings whose `status` is exactly `open`, so `resolved`
and `intentional` are both excluded (`collect_status.py:150`).

**Rationale**: `intentional` is the disposition a spec's declared decision produces; carrying
it in the outstanding-work list would mean the backlog never empties and would re-litigate a
decision already recorded. See ADR-012 for the accepted-behavior side of the same idea.

**Security Scan Note**: Findings disappearing from the status report is not suppression — the
prose report and `findings.json` keep every finding with its disposition. This bucket answers
"what is still owed", not "what was ever found".

## Related Specs

- [SPEC-029: The Generated Backlog](./SPEC-029-the-generated-backlog.md) — the git-tracked
  rendering of this census, and the full-overwrite rule that governs it
- [SPEC-030: Wrap-Up Orchestration](./SPEC-030-wrap-up-orchestration.md) — the mutating
  counterpart, which regenerates the backlog inside its artifacts commit

## Change History

| Date | Change | Reason |
|------|--------|--------|
| 2026-08-21 | Initial spec, inferred from code and tests | Brownfield scan (`freya-spec-manager bootstrap`) |

---

*Certainty 80. The bucket semantics are unambiguous in code and each has a test whose docstring
names the failure it prevents; the degradation rule is stated in the module docstring and again
in ADR-007, and the `check=True` asymmetry carries an in-line comment explaining itself, which
is what deliberate looks like. Held at 80 rather than higher because the two guarantees the
project talks about most — never crash on a bad spec, never block — are the two with no test at
all, and because the worklist ordering that `review intent` depends on is asserted nowhere (the
fixture has a single proposed behavior, so the sort at `:82` is unexercised).*
