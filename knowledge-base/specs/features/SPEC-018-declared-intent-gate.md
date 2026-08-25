---
id: SPEC-018
title: Declared-intent gate over accepted behaviors
category: features
tags: [governance, intent-records, gate, tier-1, git, spec-manager]
status: implemented
certainty: 85
created: 2026-08-21
updated: 2026-08-24
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
forty-seven tests — seventeen when this spec was written, and those seventeen already
included a CLI exit-code-plus-JSON contract test and a path-spelling test written
after a real Windows CI fail-open
(`skills/freya-spec-manager/scripts/test_verify_intent.py:761` and `:193`, both
present at `c00b2f4`). The eighteen added on 2026-08-23 are adversarial and are a
different set: eleven for the marker shapes that got the gate to report itself clean,
seven for `--advance` — what it refuses, what `--force` overrides, and the one skip it
still advances over. The twelve added on 2026-08-24 are a third set: five for the
corpus the gate reads (an unreadable spec blocks both Tier-1 gates, a non-record in
the specs tree does not) and seven for how a locator is spelled, one of which only
runs on a case-sensitive filesystem and skips elsewhere. The deduction is only that this spec
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

**Decision**: the run fails open on both — it exits 0 and never reports an
infrastructure problem as a block — but each one is *labelled*, and the label is
part of the decision rather than a courtesy. With no `.intent-last-verified`
marker the run is `skipped: true` with the fresh-repo note (BEH-090). When the
`git diff` itself fails, `_changed_status` returns `ok=False`
(`skills/freya-spec-manager/scripts/verify_intent.py:144`) and the run is
`skipped: true` with `intent gate skipped — git could not diff <baseline>..worktree;
nothing was checked` (`verify_intent.py:441`). A marker that exists and is unusable
— unreadable, holding an empty `commit:` value, holding no `commit:` line, or
holding something that is not hash-shaped — is a third labelled skip, and it also
appends a `warnings` entry naming the file (`_read_baseline`, `verify_intent.py:94`).

`--advance` reads those labels and refuses on them. `advance_if_clear`
(`verify_intent.py:547`) writes the baseline only over a gate that ran and did not
block; over either refusal the CLI exits **2** with the reason on stderr
(`verify_intent.py:646`, `:656`), and `--force` is the sole override. One carve-out
survives and it is narrow: an *absent* marker still advances, because writing the
first marker is how a fresh repository leaves that state. An empty, malformed or
unresolvable marker does not qualify — the discriminator is structural rather than a
list of shapes (`_skipped_without_checking`, `verify_intent.py:509`).

**Rationale**: the project-wide rule that every check fails open on infrastructure
failure — never a false clean *and* never a false block — is
`knowledge-base/decisions/ADR-009-two-enforcement-tiers.md`. For this gate the
concrete case is a fresh repository or a full scan, where there is no transition to
govern yet. What the earlier version of this section got wrong is the *silent* half:
an empty change-set because git refused and an empty one because nothing changed are
two different answers, and reporting both as `skipped: false` with exit 0 is a
Tier-1 gate stating it ran while having read nothing. That is a false clean, which
the fail-open rule was never meant to license. And a fail-open is only harmless
while nothing durable happens: advancing the baseline over a gate that read nothing
clears whatever it did not look at on every future run, which is why the write path
refuses where the check does not.

**Security Scan Note**: a passing `verify-intent` is not a statement that accepted
tests are unchanged. **Read `skipped` before treating exit 0 as a guarantee** — that
is the contract, not a caveat, and it is stated in the module docstring
(`verify_intent.py:23`). Exit 2 from `--advance` means the baseline was *not*
moved; it is not the gate's exit 1 and a consumer that conflates the two will report
an unauthorized edit where the gate produced none.

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

**Decision**: two halves, and until 2026-08-24 this section described only one of
them while its title claimed both.

*Record paths* — `_git_relpath` converts a filesystem path to a forward-slash,
project-relative path via `PurePath.as_posix()` before it reaches
`git cat-file -e <commit>:<path>`, rather than passing `os.path.relpath` output
through.

*Locator paths* — the path a spec declares is reduced with
`graph_ops.normalize_key`, the same rule that keys the code graph (ADR-030: the
primitive is imported, not copied), and so is git's side of the comparison. Where
that leaves two spellings still unequal, `os.path.samefile` decides whether they
name one file, and only then.

**Rationale**: git matches a `<commit>:<path>` rev-spec against its own
'/'-separated tree paths verbatim, and `cat-file` cannot distinguish "path I failed
to resolve" from "path genuinely absent" — both land on *new*, the permissive side.
The first Windows CI run caught exactly this: backslash paths made every
pre-existing record look new, so a record filed for some past change authorized
today's edit. Pinned by
`test_verify_intent.py#VerifyIntentCase.test_record_path_reaches_git_slash_separated`.

The locator half lands on the same permissive side for a different reason. A
locator written `./tests/test_a.py::test_a` is not an error anywhere else in the
toolkit — `verify_links` resolves it and so does `behavior_graph` — so the spelling
passes Tier-1 on the way in, and matching git's map verbatim then skipped the
behavior and reported `skipped: false, unauthorized: [], exit 0`. Case is the part
that cannot be settled by a rule: `Tests/x.py` and `tests/x.py` are one file on
macOS and Windows and two on Linux, so `casefold()` alone would produce a false
block on the host a governance gate most often runs on. `samefile` puts that to the
filesystem instead. Its residue is stated where it is decided: a *deleted* accepted
test whose locator differs in case has no file left to ask about, and it is
`verify_links` reporting `locator-unresolved` in the same wrap-up phase that
catches it.

**Security Scan Note**: the `as_posix()` call is load-bearing and platform-agnostic
by design. A cleanup that "simplifies" it to native path handling reopens a
silent fail-open on Windows; a scanner flagging the normalization as redundant is
wrong. The same goes for `samefile`: replacing it with a case-folded string
comparison looks like a simplification and is a platform-dependent wrong answer.

### A record naming an unknown behavior is a warning, not an error

**Decision**: an `INTENT` record listing a `BEH-NNN` that no spec declares produces
a `warnings` entry and does not affect the exit code. A record that is malformed —
missing or empty `behaviors:`, or unparseable frontmatter — is an `error` and does
block, and authorizes nothing.

A **spec** the gate cannot read is an `error` on the same terms, added
2026-08-24. It used to drop out of `load_all_specs`, so its `accepted` behaviors
did not exist as far as this gate was concerned and the run reported
`skipped: false` with an empty `unauthorized` — the shape of a gate that ran.

**Rationale**: the two failures are different. A stale or mistyped id in a record
is a bookkeeping problem that should be visible without stopping work, while a
record the gate cannot read is a record it cannot honour — treating that as an
authorization would let a broken file wave any edit through. An unreadable spec is
the same argument one layer out and with a worse consequence, because nothing about
the run looks unusual: `--advance` then moves the baseline, which does not defer
the unauthorized edit, it clears it on every future run.

**Security Scan Note**: an unknown-behavior warning is not a suppressed failure;
the blocking cases are `unauthorized` and `errors`, and both are in the JSON. An
`errors` entry naming a file under `knowledge-base/specs/` means the corpus was
short and this gate says so rather than checking what was left.

## Related Specs

- [SPEC-016: ADR record integrity and index](./SPEC-016-adr-record-integrity.md) — the sibling
  Tier-1 deterministic gate
- [SPEC-017: Spec search and corpus discovery](./SPEC-017-spec-search-and-discovery.md) —
  supplies the behavior corpus this gate reads

## Change History

| Date | Change | Reason |
|------|--------|--------|
| 2026-08-21 | Initial spec (inferred) | Brownfield scan of `skills/freya-spec-manager/scripts/verify_intent.py` |
| 2026-08-24 | Amended the fail-open decision: a failed `git diff` is a labelled `skipped: true`, not an empty change-set; an unusable marker is a third labelled skip; `--advance` refuses over a block or a skip and exits 2, with the absent-marker carve-out named. Test count 17 → 35. | SEC-001 and SEC-011. The section asserted an invariant the code contradicted: it said an unusable diff passes silently, and the code has reported `skipped: true` with a note since 2026-08-23. A spec blessing a fail-open the code removed is worse than no spec, because it reads as the intended semantics. |
| 2026-08-24 | Fixed the Certainty paragraph the same day: the CLI-contract and path-spelling tests it named belong to the original seventeen, not to the eighteen added on 2026-08-23. | Set-differencing the two files gives 18 added and 0 removed; both named tests are present at `c00b2f4`. The 11/7 split of the eighteen was correct and is unchanged — only the trailing clause had drifted onto the wrong referent. |
| 2026-08-24 | Gave the path-spelling decision its second half. The title said "locator and record paths" and the body only ever described `_git_relpath`, which is applied to record paths and was never applied to locators; a locator now goes through `normalize_key`, and `samefile` settles case. Added the unreadable-spec error to the warning-vs-error decision. Test count 35 → 47. | A locator spelled `./tests/x.py` passed every other checker in the suite and never matched git's map, so the gate skipped the behavior and reported `skipped: false, unauthorized: [], exit 0` — the permissive direction, reachable by writing two characters into a spec. The section's own title had been asserting the fix for three days. |
