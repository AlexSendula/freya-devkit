---
id: SPEC-016
title: ADR record integrity and index
category: features
tags: [adr, governance, integrity, tier-1, spec-manager]
status: implemented
certainty: 85
created: 2026-08-21
updated: 2026-08-21
related_code:
  - skills/freya-spec-manager/scripts/adr.py
  - skills/freya-spec-manager/scripts/frontmatter.py
  - skills/freya-spec-manager/scripts/test_adr.py
  - knowledge-base/decisions/README.md
  - bin/commands.json
intentional_decisions:
  - "A malformed ADR is excluded from the comparison set but always surfaced as a warning"
  - "verify_adrs collects every error instead of stopping at the first bad file"
  - "Only lifecycle filters the authoritative set — category never does"
  - "The gate sees knowledge-base/decisions/ADR-*.md and nothing else"
  - "ADR ids are allocated from the filenames on disk, with no persistent counter"
behaviors:
  - behavior_id: BEH-076
    title: Two ADRs sharing an id fail `adr verify`, naming both files
    state: proposed
    level: unit
    adapter: unittest
    locator: skills/freya-spec-manager/scripts/test_adr.py#IntegrityCase.test_flags_duplicate_id
  - behavior_id: BEH-077
    title: A supersedes/superseded_by that resolves to no known ADR fails `adr verify`
    state: proposed
    level: unit
    adapter: unittest
    locator: skills/freya-spec-manager/scripts/test_adr.py#IntegrityCase.test_flags_dangling_supersedes
  - behavior_id: BEH-078
    title: An ADR status outside proposed/accepted/superseded/deprecated fails `adr verify`
    state: proposed
    level: unit
    adapter: unittest
    locator: skills/freya-spec-manager/scripts/test_adr.py#IntegrityCase.test_flags_bad_status
  - behavior_id: BEH-079
    title: An ADR whose frontmatter cannot be parsed is reported as unparseable, not a traceback
    state: proposed
    level: unit
    adapter: manual
    locator: skills/freya-spec-manager/scripts/test_adr.py#IntegrityCase.test_flags_unparseable_frontmatter
  - behavior_id: BEH-080
    title: A malformed ADR is left out of the gathered set and returned as a warning
    state: proposed
    level: unit
    adapter: unittest
    locator: skills/freya-spec-manager/scripts/test_adr.py#GatherCase.test_malformed_is_warning_not_silent_drop
  - behavior_id: BEH-081
    title: "`adr list` prints every ADR as an id/title/status index table"
    state: proposed
    level: unit
    adapter: unittest
    locator: skills/freya-spec-manager/scripts/test_adr.py#IntegrityCase.test_list_renders_table
---

# ADR record integrity and index

## What

`freya adr` is the deterministic half of ADR handling: it does not author the
reasoning, it guarantees that the records in `knowledge-base/decisions/` are
addressable and internally consistent.

`adr verify` walks `knowledge-base/decisions/ADR-*.md` and reports four classes of
integrity failure — a duplicate `ADR-NNN` id, a `supersedes`/`superseded_by` that
resolves to no record in the directory, a `status` outside the closed set, and
frontmatter that is missing a required field or cannot be parsed at all. Errors go
to stderr and the process exits non-zero, which is what makes it usable as a
hard-block. An absent decisions directory is clean, not an error.

`adr list` renders the same set as a markdown index (`ID | Title | Status`), or as
JSON. `load_adrs`/`active_adrs` are the gather side used by the contradiction
check: `active_adrs` narrows to `status: accepted`, and both return a warnings
channel alongside the records.

Scope bound: this covers reading, checking and indexing existing records. Authoring
(`adr new`, which allocates the next id and writes a four-section skeleton) is in
the same module but the content of an ADR is a human's job — the tooling never
writes the reasoning.

## Why

An ADR is only load-bearing if it can be found and trusted. A duplicate id means
two different decisions answer to the same citation; a dangling supersede link
means the chain of "what replaced this" has a hole; a bad status means the
authoritative set is ambiguous. None of these are judgment calls, so they are
checked by a script and blocked on, rather than left to review.

This repository is its own evidence: until 2026-08-21 these twenty-nine records
sat in a hand-written directory the tooling could not reach, and schema
conformance was something you had to remember to check by hand
(`knowledge-base/decisions/README.md`). Moving them under
`knowledge-base/decisions/` is what put them inside this guarantee.

**Certainty (85).** High, but not authored-by-a-human high. Each failure class is
named in the module docstring, in `skills/freya-spec-manager/SKILL.md` and again in
the reference template, and each has a dedicated test — the intent is documented
three times over, so it is deliberate rather than emergent. The deductions are for
the two edges no test pins: the CLI's own exit-code/stderr contract, and the
unparseable-frontmatter branch (BEH-079).

## Behavior

| Behavior | State | Verified by |
|----------|-------|-------------|
| BEH-076 Two ADRs sharing an id fail `adr verify`, naming both files | proposed | `skills/freya-spec-manager/scripts/test_adr.py#IntegrityCase.test_flags_duplicate_id` (unittest) |
| BEH-077 A supersedes/superseded_by that resolves to no known ADR fails `adr verify` | proposed | `skills/freya-spec-manager/scripts/test_adr.py#IntegrityCase.test_flags_dangling_supersedes` (unittest) |
| BEH-078 An ADR status outside the closed set fails `adr verify` | proposed | `skills/freya-spec-manager/scripts/test_adr.py#IntegrityCase.test_flags_bad_status` (unittest) |
| BEH-079 An unparseable ADR is reported as unparseable, not a traceback | proposed | *no test* — owed at `test_adr.py#IntegrityCase.test_flags_unparseable_frontmatter` (manual) |
| BEH-080 A malformed ADR is left out of the gathered set and returned as a warning | proposed | `skills/freya-spec-manager/scripts/test_adr.py#GatherCase.test_malformed_is_warning_not_silent_drop` (unittest) |
| BEH-081 `adr list` prints every ADR as an id/title/status index table | proposed | `skills/freya-spec-manager/scripts/test_adr.py#IntegrityCase.test_list_renders_table` (unittest) |

Two gaps worth naming, neither currently a behavior record:

- **The CLI contract is untested.** `verify_adrs` is exercised directly by four
  tests; nothing runs `adr.py verify` as a process and asserts exit 1 with errors
  on stderr, even though that exit code is what wrap-up gates on.
- **BEH-079 has no test.** `verify_adrs` catches `FrontmatterError` and emits
  `"<file>: unparseable frontmatter: …"`, but every integrity test feeds it
  well-formed YAML with a bad *value*. The sibling gate has exactly this test
  (`test_verify_intent.py#VerifyIntentCase.test_unparseable_record_is_error_not_traceback`);
  this one does not.

## Intentional Design Decisions

### A malformed ADR is excluded from the comparison set, but never silently

**Decision**: `load_adrs`/`active_adrs` drop any record that fails
`validate_adr` from the returned list and append a human-readable string to a
second return value, the warnings channel. The record is not repaired, not
guessed at, and not passed through in a degraded form.

**Rationale**: an invalid record cannot be compared safely — its status may be the
thing that is wrong — but an exclusion nobody sees turns a governance check into a
false clean, which is the failure mode this project treats as unrecoverable (see
`knowledge-base/decisions/ADR-005-repair-parsing-substrate-in-place.md`, the
never-confidently-empty rule).

**Security Scan Note**: a tool observing that `adr list` output is shorter than the
file count in `knowledge-base/decisions/` has not found a silent drop — check the
warnings channel, which the caller is expected to surface. Exclusion plus a warning
is the designed pair.

### `verify_adrs` collects every error rather than stopping at the first

**Decision**: a parse failure `continue`s to the next file and validation errors
accumulate; the function returns a list, and the CLI prints all of them before
exiting 1. An empty list means clean.

**Rationale**: a Tier-1 gate is run by someone who wants to fix everything in one
pass. Failing fast would hide the second broken record behind the first and turn
one repair into several round-trips.

**Security Scan Note**: the swallowed exception around `parse_frontmatter` is
deliberate error aggregation, not a suppressed failure — the condition is
re-emitted as an error string and still exits non-zero.

### Only lifecycle filters the authoritative set — category never does

**Decision**: `active_adrs` filters on `status == "accepted"` and nothing else.
There is no category, tag or path scoping anywhere in the gather path.

**Rationale**: recorded in
`knowledge-base/decisions/ADR-011-governance-check-scoping.md` (always-global
comparison) and `knowledge-base/decisions/ADR-003-lifecycle-state-is-trust-signal.md`
(state, not a score, is what makes a record authoritative). Not restated here.

**Security Scan Note**: a `proposed` or `superseded` ADR being ignored by the
contradiction check is the lifecycle working, not a missed record.

### The gate sees `knowledge-base/decisions/ADR-*.md` and nothing else

**Decision**: `DECISIONS_RELDIR` is fixed and the glob is `ADR-*.md`. A decision
record kept anywhere else, or named anything else, is invisible to `adr verify`,
`adr list` and the contradiction check — it is not an error, it simply does not
exist as far as the tooling is concerned.

**Rationale**: a single, predictable location is what lets every consumer agree on
what the ADR set *is* without configuration. The cost is real and this repository
paid it: its own records were unverifiable until they were moved into that
directory on 2026-08-21.

**Security Scan Note**: "no ADR covers this" from the tooling means "no ADR in
`knowledge-base/decisions/`". A decision documented in a README or a design note is
outside the checked set by construction.

### ADR ids are allocated from the filenames on disk, with no persistent counter

**Decision**: `_next_id` takes the highest `ADR-(\d+)` found in the directory's
filenames and returns that plus one. No counter file, no consultation of the `id`
field inside the records.

**Rationale**: statelessness — the directory listing is the allocator, so a
checkout, a merge or a manual `mv` cannot desynchronise it from a stored number.
The backstop is the duplicate-id check (BEH-076), which is where a collision is
supposed to surface; `skills/freya-spec-manager/SKILL.md` states this pairing
explicitly.

**Security Scan Note**: gaps in the ADR numbering are expected (a deleted record
leaves its number unused) and are not evidence of a missing file.

**[NEEDS CLARIFICATION]** deleting the *highest*-numbered record makes its id
available again, so a future `adr new` would reissue it and any citation to the
deleted record would silently resolve to a different decision. Is id reuse
acceptable, or should allocation be monotonic across git history?

## Related Specs

- [SPEC-017: Spec search and discovery](./SPEC-017-spec-search-and-discovery.md) — the other
  reader of `frontmatter.py`, with the opposite fail policy for a bad file
- [SPEC-018: Declared-intent gate](./SPEC-018-declared-intent-gate.md) — the sibling Tier-1
  gate, and the one that does have a CLI-contract test

## Change History

| Date | Change | Reason |
|------|--------|--------|
| 2026-08-21 | Initial spec (inferred) | Brownfield scan of `skills/freya-spec-manager/scripts/adr.py` |
