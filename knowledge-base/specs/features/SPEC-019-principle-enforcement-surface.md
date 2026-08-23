---
id: SPEC-019
title: Principle enforcement surface (G2)
category: features
tags: [governance, principles, g2, tier-2, resolution-log, cli, spec-manager]
status: implemented
certainty: 80
created: 2026-08-21
updated: 2026-08-21
related_code:
  - skills/freya-spec-manager/scripts/principles.py
  - skills/freya-spec-manager/scripts/resolution_log.py
  - skills/freya-spec-manager/scripts/test_principles.py
  - bin/commands.json
  - skills/freya-spec-manager/SKILL.md
intentional_decisions:
  - "An absent principles.md is answered in prose that names the file, not with a blank line"
  - "Text output is the `## Principles` section alone; everything above it is dropped"
  - "A retired resolution is retired by a later `superseded` record, never by editing a line"
  - "A malformed log line is skipped with a warning instead of aborting the lookup"
  - "The script parses, appends and looks up; it never returns a verdict"
behaviors:
  - behavior_id: BEH-091
    title: "`principles list` on a project with no principles.md names the missing file instead of printing nothing"
    state: proposed
    level: unit
    adapter: unittest
    locator: skills/freya-spec-manager/scripts/test_principles.py#ListCase.test_absent_file_says_so_rather_than_printing_nothing
  - behavior_id: BEH-092
    title: A principles.md that exists but declares nothing is reported differently from an absent one
    state: proposed
    level: unit
    adapter: unittest
    locator: skills/freya-spec-manager/scripts/test_principles.py#ListCase.test_a_file_declaring_no_principles_is_distinguished_from_an_absent_one
  - behavior_id: BEH-093
    title: Listing prints the `## Principles` section only, not the prose above it
    state: proposed
    level: unit
    adapter: unittest
    locator: skills/freya-spec-manager/scripts/test_principles.py#ListCase.test_text_prints_section_when_present
  - behavior_id: BEH-094
    title: "`principles prior` returns the most recent resolution for a (principle, path), not the first"
    state: proposed
    level: unit
    adapter: unittest
    locator: skills/freya-spec-manager/scripts/test_principles.py#ResolutionsCase.test_latest_refutation_wins
  - behavior_id: BEH-095
    title: A later `superseded` record retires a (principle, path) while both lines stay on disk
    state: proposed
    level: unit
    adapter: unittest
    locator: skills/freya-spec-manager/scripts/test_principles.py#ResolutionsCase.test_superseded_record_retires_the_pair
---

# Principle enforcement surface (G2)

## What

`freya principles` is the read/write surface over the project's constitution
(`knowledge-base/principles.md`) and its resolution log. Three subcommands, no
judgment in any of them:

- **`list`** — the soft-injection payload. Prints the constitution so that
  `create`, `scan` and wrap-up run with the rules in view; `--format json` emits
  the parsed items (`n`, `title`, `text`), where a numbered `1. **Title.** body`
  item is one principle and its indented continuation lines fold into `text`. A
  file with no numbered items yields no items rather than an error. Both an
  absent file and a present-but-empty one produce a sentence saying which case it
  is (BEH-091, BEH-092).
- **`resolve`** — appends one JSON line to
  `knowledge-base/principle-resolutions.jsonl` recording a `refuted`, `amended`,
  `auto-cleared` or `superseded` outcome against a principle and the paths it
  touched. A **fix** is never logged; git already records it.
- **`prior`** — the recurrence query. Returns the active resolutions for the
  queried principle and paths: latest record per `(principle, path)`, pairs whose
  latest verdict is `superseded` dropped, a record covering several paths returned
  once (BEH-094, BEH-095).

What is deliberately absent: there is no check, no diff comparison and no exit
code that means "violation". The G2 checkpoint judgment lives in the wrap-up
skill as an agent procedure.

## Why

`principles.md` gets exactly two enforcement mechanisms — soft injection and a
resolve-to-proceed checkpoint at wrap-up — and this script is the machinery under
both. `list` exists so the rules are in the working context at design time, when
they are cheap to honour; `resolve`/`prior` exist because a refuted false positive
does not self-clear the way a fix does, so without a queryable record the
checkpoint re-nags on every overlapping change until people start rubber-stamping
it. Both the tier split and the log shape are settled decisions:
`knowledge-base/decisions/ADR-009-two-enforcement-tiers.md` and
`knowledge-base/decisions/ADR-010-append-only-resolution-logs.md`.

**Certainty (80).** High, because the intent here is written down in three
independent places that agree: `SKILL.md`'s "Principle Enforcement (governance
G2)" section, the module docstring ("this script only does the deterministic
parse / append / lookup"), and ADR-009/ADR-010. BEH-091 is stronger still — its
test carries a docstring explaining the discovery and citing ADR-005, so it is
recorded intent rather than inference. Held below that by the parser's tolerances:
that a free-form file yields no items, and that non-numbered content is silently
ignored, read as consequences of the regex rather than as decisions anyone made.

## Behavior

| Behavior | State | Verified by |
|----------|-------|-------------|
| BEH-091 `principles list` on a project with no principles.md names the missing file instead of printing nothing | proposed | `test_principles.py#ListCase.test_absent_file_says_so_rather_than_printing_nothing` (unittest) |
| BEH-092 A principles.md that exists but declares nothing is reported differently from an absent one | proposed | `test_principles.py#ListCase.test_a_file_declaring_no_principles_is_distinguished_from_an_absent_one` (unittest) |
| BEH-093 Listing prints the `## Principles` section only, not the prose above it | proposed | `test_principles.py#ListCase.test_text_prints_section_when_present` (unittest) |
| BEH-094 `principles prior` returns the most recent resolution for a (principle, path), not the first | proposed | `test_principles.py#ResolutionsCase.test_latest_refutation_wins` (unittest) |
| BEH-095 A later `superseded` record retires a (principle, path) while both lines stay on disk | proposed | `test_principles.py#ResolutionsCase.test_superseded_record_retires_the_pair` (unittest) |

Three further guarantees of the log are proven but not yet recorded as behaviors:
`prior` ignoring resolutions for unqueried paths and principles, a multi-path
record de-duplicating to one result, and a malformed line being skipped with a
warning (`test_principles.py#ResolutionsCase`, plus the shared-core suite
`test_resolution_log.py`).

## Intentional Design Decisions

### An absent principles.md is answered in prose, not with a blank line

**Decision**: `cmd_list` in text mode returns a sentence naming
`knowledge-base/principles.md` and stating that G2 passes vacuously. It used to
return the empty string, which printed one blank line and exited 0. JSON mode
returns `[]` and is unchanged, because an empty array is already unambiguous to a
machine.

**Rationale**: a blank line and exit 0 reads as "checked, all clear" when the
truth is "there was nothing here to check" — the same failure
`knowledge-base/decisions/ADR-005-repair-parsing-substrate-in-place.md` rules out
for the parsing substrate, applied to the CLI surface. It was found by running the
command on freya-devkit itself, which has no principles file.

**Security Scan Note**: exit 0 from `freya principles list` is not evidence that a
project has principles, and an empty JSON result is not evidence that a change was
checked against any. Read the text answer; it distinguishes "no file", "file with
no principles" and a real list.

### Text output is the `## Principles` section alone

**Decision**: `_principles_section` returns everything under a `## Principles`
heading and nothing above it, falling back to the whole file when that heading is
absent. Intro prose, rationale paragraphs and anything else placed before the
heading never reach the caller in text mode.

**Rationale**: the text payload is what gets injected into an agent's working
context, and the constitution is the numbered rules — surrounding narrative is
tokens that dilute them.

**Security Scan Note**: a rule written into the file's preamble instead of under
`## Principles` is silently invisible to soft injection. This is a file-layout
requirement, not a truncation bug.

### Retirement is a later `superseded` record, never an edited line

**Decision**: resolutions are appended one JSON object per line and never mutated
or deleted; a stale resolution is retired by appending a `superseded` record for
the same `(principle, path)`, and the active set is latest-wins with superseded
keys dropped. See
`knowledge-base/decisions/ADR-010-append-only-resolution-logs.md`.

**Security Scan Note**: a log holding several records for the same principle and
path, including ones that appear to contradict each other, is the intended shape
and not corruption or a replay. Read the last record per key. A tool that
"cleans up" the log by collapsing or deleting older lines destroys the audit trail
of how the team calibrated its own principles.

### A malformed log line is skipped with a warning, not fatal

**Decision**: `resolution_log.load` skips a line it cannot parse, records a
warning naming the line number and the file, and returns the rest; `prior` prints
those warnings to stderr and still answers.

**Rationale**: a corrupt line must not crash a wrap-up run, and must equally not
be able to make an auto-clear disappear unnoticed —
`ADR-010` fences auto-clear as the one place a real violation could hide.

**Security Scan Note**: a partially-unreadable resolution log degrades to fewer
priors, which biases the checkpoint toward escalating to a human. It never
authorises anything.

### The script never returns a verdict

**Decision**: nothing in `principles.py` decides whether a diff violates a
principle. There is no check subcommand and no failing exit code; the judgment and
the fix/refute/amend triage are agent steps in the wrap-up skill.

**Rationale**: model judgment is Tier 2 —
`knowledge-base/decisions/ADR-009-two-enforcement-tiers.md`.

**Security Scan Note**: the absence of enforcement logic in this module is not a
missing control. G2 is procedural by design: wrap-up does not complete while a
finding is unresolved, and "ignore and push" is not one of the three valid
resolutions.

## Related Specs

- [SPEC-020: Contradiction comparison sets (G3)](./SPEC-020-contradiction-comparison-set.md) —
  the same gather/append/lookup split, one authority tier down
- [SPEC-021: Declarative-drift scope and the gaps view (P4b)](./SPEC-021-declarative-drift-scope.md) —
  the third consumer of the shared resolution-log core
- [SPEC-018: Declared-intent gate](./SPEC-018-declared-intent-gate.md) — the Tier-1
  counterpart that does hard-block, and why it is allowed to

## Change History

| Date | Change | Reason |
|------|--------|--------|
| 2026-08-21 | Initial spec (inferred) | Brownfield scan of `skills/freya-spec-manager/scripts/principles.py` |
