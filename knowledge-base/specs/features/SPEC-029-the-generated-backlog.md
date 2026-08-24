---
id: SPEC-029
title: The Generated Backlog
category: features
tags: [status, backlog, artifacts, generated, coverage, overwrite]
status: implemented
certainty: 75
created: 2026-08-21
updated: 2026-08-24
related_code:
  - skills/freya-status/scripts/collect_status.py
  - skills/freya-status/SKILL.md
  - skills/freya-wrap-up/SKILL.md
intentional_decisions:
  - "BACKLOG.md is rewritten by full overwrite — the only path in this toolkit with that property in code"
  - "The backlog is git-tracked so it diffs in PRs, unlike the .graph caches"
  - "status writes the artifact and never stages or commits it — that is wrap-up's job"
  - "The gap total counts every graphed source file no behavior covers, including files no behavior could ever cover"
  - "The report's degradation notes ARE rendered into the backlog, above the sections they qualify"
behaviors:
  - behavior_id: BEH-146
    title: A refresh writes the census to knowledge-base/BACKLOG.md, creating the directory if it is absent
    state: proposed
    level: unit
    adapter: unittest
    locator: skills/freya-status/scripts/test_collect_status.py#CollectAndRenderTest.test_write_backlog_writes_file
  - behavior_id: BEH-147
    title: The generated backlog names each outstanding behavior under a do-not-edit banner and its four fixed sections
    state: proposed
    level: unit
    adapter: unittest
    locator: skills/freya-status/scripts/test_collect_status.py#CollectAndRenderTest.test_render_backlog_has_sections_and_generated_header
  - behavior_id: BEH-148
    title: A refresh replaces the file whole — anything hand-written at that path is gone, with no merge and no warning
    state: proposed
    level: unit
    adapter: manual
    locator: skills/freya-status/scripts/test_collect_status.py#CollectAndRenderTest.test_a_refresh_replaces_hand_written_content
  - behavior_id: BEH-149
    title: The coverage-gap section reports the whole repository's total but lists at most twenty of them
    state: proposed
    level: unit
    adapter: manual
    locator: skills/freya-status/scripts/test_collect_status.py#CollectAndRenderTest.test_the_gap_sample_is_capped_while_the_total_is_whole
  - behavior_id: BEH-160
    title: The generated backlog carries the census notes, above the sections they qualify, and manufactures none when every source was read
    state: proposed
    level: unit
    adapter: unittest
    locator: skills/freya-status/scripts/test_collect_status.py#CollectAndRenderTest.test_the_backlog_carries_the_census_notes
---

# The Generated Backlog

## What

`knowledge-base/BACKLOG.md` is the census of SPEC-028 rendered as committed markdown. It is
written only when `--write-backlog` is passed (`collect_status.py:378`), and `wrap-up`
regenerates it inside its artifacts commit so it stays current with the code it describes.

The document is fixed in shape: a `# Backlog` heading, a do-not-edit banner, a one-line census
(`proposed · confirmed · accepted · tests owed · open findings · coverage gaps`), then four
sections — behaviors to confirm, tests owed, coverage gaps, open security findings. The two
worklists render as tables of behavior id, title and owning spec, or `_None._`. Coverage gaps
render as a total plus a sample of at most twenty paths (`GAPS_SAMPLE`, `collect_status.py:24`
and `:99`); the total is the whole repository's, uncapped.

The write is a full overwrite — `open(path, "w")` at `collect_status.py:349` — with no read of
the existing file, no merge and no diff.

## Why

A backlog nobody regenerates rots into a lie, and a backlog that lives only in a tool nobody
runs is invisible. This one is generated so it cannot drift from the census, and git-tracked so
it diffs in a pull request: the reviewer sees "18 behaviors owe tests / 3 open findings" without
running anything. ADR-007 records that reasoning and the deliberate contrast with the `.graph`
parse caches, which are regenerable and ignored.

The sample cap exists because the two audiences want different things from the same number. The
count is the metric — it belongs in the census line and in a PR diff, whole. The list is a
starting point for whoever is about to work it, and pasting several hundred paths into a
tracked file would make every refresh a large diff that hides the number that actually moved.

## Behavior

| Behavior | State | Verified by |
|----------|-------|-------------|
| BEH-146 A refresh writes the census to `knowledge-base/BACKLOG.md`, creating the directory if absent | proposed | `test_collect_status.py#CollectAndRenderTest.test_write_backlog_writes_file` (unittest) |
| BEH-147 The generated backlog names each outstanding behavior under a do-not-edit banner and its four fixed sections | proposed | `test_collect_status.py#CollectAndRenderTest.test_render_backlog_has_sections_and_generated_header` (unittest) |
| BEH-148 A refresh replaces the file whole — hand-written content at that path is gone | proposed | **no test** — `test_collect_status.py#CollectAndRenderTest.test_a_refresh_replaces_hand_written_content` is where one belongs (manual) |
| BEH-149 The gap section reports the whole total but lists at most twenty paths | proposed | **no test** — `test_collect_status.py#CollectAndRenderTest.test_the_gap_sample_is_capped_while_the_total_is_whole` is where one belongs (manual) |
| BEH-160 The backlog carries the census notes above the sections they qualify, and manufactures none when every source was read | proposed | `test_collect_status.py#CollectAndRenderTest.test_the_backlog_carries_the_census_notes` (unittest) |

BEH-148 is the highest-consequence untested behavior in this area. `test_write_backlog_writes_file`
asserts the file exists afterwards and nothing asserts what happened to what was there before,
so the destructive half of the contract — the half the skill warns about in prose and the half
that forced this project to rename its own hand-written backlog to `roadmap.md` — is verified
nowhere.

BEH-149's cap is observable today: this repository's backlog reports 65 gaps and lists 20.
Neither the cap nor the "total stays whole" half is asserted, because `gaps_bucket` is mocked
in every test that reaches the renderer.

## Intentional Design Decisions

### The file is rewritten whole, and anything hand-authored at that path is destroyed

**Decision**: `write_backlog` opens `knowledge-base/BACKLOG.md` with mode `w` and writes the
rendered census (`collect_status.py:349`). There is no merge, no backup, no
"this file was not generated by me" check, and no prompt.

**Rationale**: The document is a projection of state that is computed elsewhere; anything
hand-written in it would be un-regenerable and would silently disagree with the census on the
next refresh. The do-not-edit banner is the warning, and the generated-artifact contract is
what makes the file trustworthy in a diff.

The cost is real and was paid here: on a case-insensitive filesystem `BACKLOG.md` and
`backlog.md` are one path, so this project's hand-maintained backlog was renamed to
`roadmap.md` on 2026-08-21 specifically to keep the toolkit from destroying it
(`knowledge-base/roadmap.md`, the callout headed "Why `roadmap.md` and not `backlog.md`" — cited
by heading because `decisions/README.md:83` forbids citing that file by line, which is edited
continuously). Adopting projects need the same warning, which is why the skill states it
outright rather than in passing.

**Security Scan Note**: "Writes a user file with mode `w` without checking whether it exists"
is the design, not missing error handling. Do not add a merge, a backup or an existence guard —
each would reintroduce the drift the generated contract exists to prevent. The correct advice
to an adopter is to keep a hand-maintained backlog under a different name.

### The artifact is written, never staged and never committed

**Decision**: `status` writes `BACKLOG.md` and stops. It runs no `git add` and no `git commit`.

**Rationale**: The two-commit pattern keeps code and generated artifacts in separate commits,
and the engineer decides when the second one happens; `wrap-up` owns that. The skill records
that Phase 6 validation observed an agent with broad tool permissions infer a `git commit`
nobody had asked for, in a repository it had only been asked to read — so the boundary is
stated explicitly rather than left implied.

**Security Scan Note**: A tool that writes a tracked file and leaves the working tree dirty is
intentional here. The dirty tree is the signal to the engineer; auto-staging it would hide a
change they never approved.

### The gap total includes files no behavior could ever cover

**Decision**: The headline coverage-gap number is every source file in the code graph that no
behavior covers, with no notion of *coverable*. Test files and shell scripts are therefore
permanent entries: a behavior's `exercises` names production code, so `test_*.py` can never
leave the list.

**Rationale**: Measured on this repository, 65 reported against 32 actually behavior-coverable —
30 test files and 3 shell scripts (`bin/freya`, `install.sh`, `install.ps1`) are the other 51%
(`knowledge-base/roadmap.md`, open defect 15). It is recorded as open rather than fixed because
excluding by filename convention is exactly the kind of built-in judgement ADR-022 says must be
a project-overridable default rather than a hardcoded name list, and no such predicate exists
yet.

**Security Scan Note**: The number in the census line is not a defect count and not a coverage
percentage. Roughly half of it, on a repository with a normal test suite, is unactionable by
construction. Do not treat a large or unchanging gap total as evidence of anything until the
`coverable` predicate exists.

### The report's notes reach the backlog, above the sections they qualify

**Decision**: `render_backlog` reads `status["notes"]` (`collect_status.py:303`) and, when the
list is non-empty, emits a block headed **"This census could not read every source"** — a
section below may be empty because its input was missing, not because it is clean — followed by
one bullet per note, placed above the four sections rather than under them
(`collect_status.py:305`–`:308`). A run that read every source emits no such block.

**Rationale**: this is a reversal, and the earlier version of this section recorded the hole as
the weakest inference in the spec. It was a hole: SPEC-028 makes the note the thing that
separates "0 open findings" from "no scan has ever run" — the same number and opposite facts —
and this renderer read the value and dropped the note in the one rendering that is committed
and read in a PR diff. A project with no `findings.json` wrote "0 open findings" and `_None._`
under **Open security findings**, with nothing anywhere in the file saying the source was
missing. That is ADR-005's confidently-empty answer inside a tracked artifact, so the boundary
was moved rather than defended.

**Security Scan Note**: the caveat block appearing in a committed file is the point, not noise
to suppress. Two properties are load-bearing and are pinned together by BEH-160: it sits
*above* the sections it qualifies rather than stranded beneath them, and a clean run
manufactures no caveat — a banner that always fires is one a reader learns to skip, which is
the same argument ADR-029 makes for the census. The note that names unreadable findings is
sample-capped for this reason (`UNRECOGNISED_SAMPLE`, `collect_status.py:149`): three hundred
bad rows would put three hundred ids on one line of a tracked file.

## Related Specs

- [SPEC-028: The Status Census](./SPEC-028-the-status-census.md) — the report this renders, and
  the degradation rule whose notes stop at the boundary
- [SPEC-030: Wrap-Up Orchestration](./SPEC-030-wrap-up-orchestration.md) — the other writer of
  this file, which regenerates it in the artifacts commit

## Change History

| Date | Change | Reason |
|------|--------|--------|
| 2026-08-21 | Initial spec, inferred from code and tests | Brownfield scan (`freya-spec-manager bootstrap`) |
| 2026-08-24 | Reversed the "notes do not reach the backlog" decision — `render_backlog` reads `status["notes"]` and renders them as a caveat block above the sections. Added BEH-160. Dropped the claim that the `:349` overwrite citation had drifted. | The rendering hole this spec called the weakest inference in it was closed on 2026-08-23: the `(value, note)` pair now reaches the committed artifact, which was the one place the ADR-005 caveat was being lost. The `:349` citation was re-measured and is correct. |
| 2026-08-24 | Repointed the `roadmap.md` provenance from a line number to the section heading it names. | `decisions/README.md:83` forbids citing `roadmap.md` by line, because it is edited continuously and the citation gate cannot see the drift — `:16` happens to land on the right callout today, which is exactly the kind of luck the rule exists to stop relying on. |

---

*Certainty 75. The overwrite is deliberate beyond doubt — it is stated in the skill with a line
citation, restated in `roadmap.md`, and cost this project a file rename, which is about as much
corroboration as an inferred decision gets. The document's shape and the do-not-edit banner are
asserted by a real test. Held at 75 rather than higher because the two most consequential
properties (the destructive overwrite and the gap-sample cap) have no test at all. The
notes-stop-here boundary was the weakest inference in this spec and is no longer an inference
at all: it was a hole, it was closed on 2026-08-23, and the choice now argued in code and
pinned by BEH-160 is the opposite one.*
