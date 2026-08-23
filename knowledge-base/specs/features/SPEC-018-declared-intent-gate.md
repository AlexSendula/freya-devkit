---
id: SPEC-018
title: Declared-intent gate over accepted behaviors
category: features
tags: [governance, intent-records, gate, tier-1, git, spec-manager]
status: implemented
certainty: 85
created: 2026-08-21
updated: 2026-08-21
related_code:
  - skills/freya-spec-manager/scripts/verify_intent.py
  - skills/freya-spec-manager/scripts/adapters.py
  - skills/freya-spec-manager/scripts/search_specs.py
  - skills/freya-spec-manager/scripts/test_verify_intent.py
  - bin/commands.json
intentional_decisions:
  - "The gate fails open on a missing baseline or an unusable git diff"
  - "Only accepted behaviors are governed; the rest change freely"
  - "An untracked record file on disk authorizes — the commit trailer never does"
  - "Locator and record paths are handed to git in git's own spelling"
  - "A record naming an unknown behavior is a warning, not an error"
behaviors:
  - behavior_id: BEH-087
    title: Editing an accepted behavior's test with no in-change record is reported unauthorized
    state: proposed
    level: unit
    adapter: unittest
    locator: skills/freya-spec-manager/scripts/test_verify_intent.py#VerifyIntentCase.test_edited_accepted_test_without_record_blocks
  - behavior_id: BEH-088
    title: A new INTENT record naming the behavior authorizes the edit
    state: proposed
    level: unit
    adapter: unittest
    locator: skills/freya-spec-manager/scripts/test_verify_intent.py#VerifyIntentCase.test_edited_accepted_test_with_record_passes
  - behavior_id: BEH-089
    title: A record that already existed at the baseline does not authorize a later edit
    state: proposed
    level: unit
    adapter: unittest
    locator: skills/freya-spec-manager/scripts/test_verify_intent.py#VerifyIntentCase.test_preexisting_record_does_not_authorize
  - behavior_id: BEH-090
    title: With no baseline marker the gate reports itself skipped and exits 0
    state: proposed
    level: unit
    adapter: unittest
    locator: skills/freya-spec-manager/scripts/test_verify_intent.py#VerifyIntentCase.test_no_baseline_skips
---

# Declared-intent gate over accepted behaviors

## What

`freya verify-intent` answers one question about a change-set: did an accepted
behavior's linked test change, and if so does a declared-intent record in the same
change-set name that behavior?

It loads the spec corpus, keeps the `accepted` behaviors that carry a locator,
resolves each locator to a file path, and intersects those paths with what changed
between its own baseline marker and the working tree. A modified or deleted test is
a change that needs authorization; an added file or a pure rename is not. Records
are read from `knowledge-base/intents/INTENT-*.md`, and only those that did not
exist at the baseline count. The result is a JSON-serialisable report —
`edited_accepted`, `records_in_change`, `authorized`, `unauthorized`, `errors`,
`warnings` — and a non-zero exit whenever `unauthorized` or `errors` is non-empty.
`--advance` writes the marker to the current HEAD, which is how a passing run sets
the next baseline.

The gate keeps its *own* baseline file rather than sharing the spec-update marker,
and it diffs the working tree rather than HEAD; both are mechanics of
`knowledge-base/decisions/ADR-008-declared-intent-record-required.md` and are not
restated here.

## Why

A red accepted test is the strongest signal this system has. The blind spot is
changing the code and the test together: the suite stays green, every fact-layer
check agrees, and the guarantee has been silently redefined. This gate exists to
turn that one blind spot back into a fact — "was an accepted test edited, and does
a record name it?" — which is answerable deterministically from artifacts that
already exist. The reasoning, and the rejected alternatives, are in ADR-008.

What this spec adds on top of the ADR is the observable surface: which conditions
produce a block, which produce a pass, and the four places where the gate's own
implementation could quietly stop protecting anything.

**Certainty (85).** As deliberate as anything in this repository: the decision has
an ADR, the module docstring states each rule and the reason for it, and there are
seventeen tests including a CLI exit-code-plus-JSON contract test and a path-spelling
test written after a real Windows CI fail-open. The deduction is only that this spec
is inferred from that material rather than authored alongside it, and that the
fail-open surface (below) is wider than any single document states in one place.

## Behavior

| Behavior | State | Verified by |
|----------|-------|-------------|
| BEH-087 Editing an accepted behavior's test with no in-change record is reported unauthorized | proposed | `skills/freya-spec-manager/scripts/test_verify_intent.py#VerifyIntentCase.test_edited_accepted_test_without_record_blocks` (unittest) |
| BEH-088 A new INTENT record naming the behavior authorizes the edit | proposed | `skills/freya-spec-manager/scripts/test_verify_intent.py#VerifyIntentCase.test_edited_accepted_test_with_record_passes` (unittest) |
| BEH-089 A record that already existed at the baseline does not authorize a later edit | proposed | `skills/freya-spec-manager/scripts/test_verify_intent.py#VerifyIntentCase.test_preexisting_record_does_not_authorize` (unittest) |
| BEH-090 With no baseline marker the gate reports itself skipped and exits 0 | proposed | `skills/freya-spec-manager/scripts/test_verify_intent.py#VerifyIntentCase.test_no_baseline_skips` (unittest) |

Four behaviors, not the whole tested surface. Deleting an accepted test
(`test_deleted_accepted_test_without_record_blocks`), an unparseable record
producing an error that covers nothing
(`test_unparseable_record_is_error_not_traceback`), the untracked-record path
(`test_untracked_record_counts`) and the CLI's exit-1-with-JSON contract
(`test_cli_exit_code_and_json_contract`) are all verified today and are candidates
for the corpus if a reviewer wants them recorded individually; they are described
here as scope and as decisions rather than duplicated as behavior records.

## Intentional Design Decisions

### The gate fails open on a missing baseline or an unusable git diff

**Decision**: with no `.intent-last-verified` marker the run is `skipped: true` and
exits 0 (BEH-090). If the `git diff` itself fails, `_changed_status` returns an
empty map, nothing intersects, and the run also passes. No infrastructure problem
is ever reported as a block.

**Rationale**: the project-wide rule that every check fails open on infrastructure
failure — never a false clean *and* never a false block — is
`knowledge-base/decisions/ADR-009-two-enforcement-tiers.md`. For this gate the
concrete case is a fresh repository or a full scan, where there is no transition to
govern yet.

**Security Scan Note**: a passing `verify-intent` on a repository with no marker is
not a statement that accepted tests are unchanged. Read `skipped` in the JSON
before treating exit 0 as a guarantee. This is the intended semantics, not a
bypass.

### Only `accepted` behaviors are governed; the rest change freely

**Decision**: `proposed`, `confirmed`, `quarantined` and `deprecated` behaviors are
skipped entirely, as are accepted behaviors with no locator; newly added tests and
100%-similarity renames need no record. Reclassifying a behavior to `deprecated` in
the same change-set as the edit is therefore a legitimate path through the gate.

**Rationale**: recorded in
`knowledge-base/decisions/ADR-008-declared-intent-record-required.md` (what needs a
record and what does not) and
`knowledge-base/decisions/ADR-003-lifecycle-state-is-trust-signal.md` (why only the
accepted state is authoritative).

**Security Scan Note**: the gate deliberately protects a small set. "Most tests can
be edited without a record" is the design, not a hole — the set it protects is
exactly the set that carries a guarantee.

### An untracked record file on disk authorizes — the commit trailer never does

**Decision**: records are found by scanning the filesystem, so untracked, staged
and committed `INTENT-*.md` files all count equally; a file is "in the change-set"
when `git cat-file` cannot find it at the baseline commit. The `Intent: INTENT-NNN`
commit trailer is traceability only and is never read by the gate.

**Rationale**: ADR-008 — the two-commit flow puts the test edit in commit 1 and the
record in commit 2, and the check runs between them, so a gate reading only
committed state would reject the intended workflow.

**Security Scan Note**: reading an unversioned, unreviewed file as authorization is
intentional. The gate's own docstring is explicit that it verifies a record
*exists*, not that its rationale is honest — judging the rationale is the Tier-2
governance track, and human review of the resulting commit is where that happens.

### Locator and record paths are handed to git in git's own spelling

**Decision**: `_git_relpath` converts a filesystem path to a forward-slash,
project-relative path via `PurePath.as_posix()` before it reaches
`git cat-file -e <commit>:<path>`, rather than passing `os.path.relpath` output
through.

**Rationale**: git matches a `<commit>:<path>` rev-spec against its own
'/'-separated tree paths verbatim, and `cat-file` cannot distinguish "path I failed
to resolve" from "path genuinely absent" — both land on *new*, the permissive side.
The first Windows CI run caught exactly this: backslash paths made every
pre-existing record look new, so a record filed for some past change authorized
today's edit. Pinned by
`test_verify_intent.py#VerifyIntentCase.test_record_path_reaches_git_slash_separated`.

**Security Scan Note**: the `as_posix()` call is load-bearing and platform-agnostic
by design. A cleanup that "simplifies" it to native path handling reopens a
silent fail-open on Windows; a scanner flagging the normalization as redundant is
wrong.

### A record naming an unknown behavior is a warning, not an error

**Decision**: an `INTENT` record listing a `BEH-NNN` that no spec declares produces
a `warnings` entry and does not affect the exit code. A record that is malformed —
missing or empty `behaviors:`, or unparseable frontmatter — is an `error` and does
block, and authorizes nothing.

**Rationale**: the two failures are different. A stale or mistyped id in a record
is a bookkeeping problem that should be visible without stopping work, while a
record the gate cannot read is a record it cannot honour — treating that as an
authorization would let a broken file wave any edit through.

**Security Scan Note**: an unknown-behavior warning is not a suppressed failure;
the blocking cases are `unauthorized` and `errors`, and both are in the JSON.

## Related Specs

- [SPEC-016: ADR record integrity and index](./SPEC-016-adr-record-integrity.md) — the sibling
  Tier-1 deterministic gate
- [SPEC-017: Spec search and corpus discovery](./SPEC-017-spec-search-and-discovery.md) —
  supplies the behavior corpus this gate reads

## Change History

| Date | Change | Reason |
|------|--------|--------|
| 2026-08-21 | Initial spec (inferred) | Brownfield scan of `skills/freya-spec-manager/scripts/verify_intent.py` |
