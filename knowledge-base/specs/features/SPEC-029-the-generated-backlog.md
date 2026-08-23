---
id: SPEC-029
title: The Generated Backlog
category: features
tags: [status, backlog, artifacts, generated, coverage, overwrite]
status: implemented
certainty: 75
created: 2026-08-21
updated: 2026-08-21
related_code:
  - skills/freya-status/scripts/collect_status.py
  - skills/freya-status/SKILL.md
  - skills/freya-wrap-up/SKILL.md
intentional_decisions:
  - "BACKLOG.md is rewritten by full overwrite — the only path in this toolkit with that property in code"
  - "The backlog is git-tracked so it diffs in PRs, unlike the .graph caches"
  - "status writes the artifact and never stages or commits it — that is wrap-up's job"
  - "The gap total counts every graphed source file no behavior covers, including files no behavior could ever cover"
  - "The report's degradation notes are not rendered into the backlog"
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
---

# The Generated Backlog

## What

`knowledge-base/BACKLOG.md` is the census of SPEC-028 rendered as committed markdown. It is
written only when `--write-backlog` is passed (`collect_status.py:255`), and `wrap-up`
regenerates it inside its artifacts commit so it stays current with the code it describes.

The document is fixed in shape: a `# Backlog` heading, a do-not-edit banner, a one-line census
(`proposed · confirmed · accepted · tests owed · open findings · coverage gaps`), then four
sections — behaviors to confirm, tests owed, coverage gaps, open security findings. The two
worklists render as tables of behavior id, title and owning spec, or `_None._`. Coverage gaps
render as a total plus a sample of at most twenty paths (`GAPS_SAMPLE`, `collect_status.py:24`
and `:99`); the total is the whole repository's, uncapped.

The write is a full overwrite — `open(path, "w")` at `collect_status.py:226` — with no read of
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
rendered census (`collect_status.py:226` — note `freya-status/SKILL.md` and `roadmap.md` both
cite `:226`, which has since drifted by four lines). There is no merge, no backup, no
"this file was not generated by me" check, and no prompt.

**Rationale**: The document is a projection of state that is computed elsewhere; anything
hand-written in it would be un-regenerable and would silently disagree with the census on the
next refresh. The do-not-edit banner is the warning, and the generated-artifact contract is
what makes the file trustworthy in a diff.

The cost is real and was paid here: on a case-insensitive filesystem `BACKLOG.md` and
`backlog.md` are one path, so this project's hand-maintained backlog was renamed to
`roadmap.md` on 2026-08-21 specifically to keep the toolkit from destroying it
(`knowledge-base/roadmap.md:16`). Adopting projects need the same warning, which is why the
skill states it with a line reference rather than in passing.

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

### The report's notes do not reach the backlog

**Decision**: `render_backlog` reads counts, worklists, gaps and findings from the status dict
and never reads `status["notes"]`. The notes appear in the text and JSON forms only.

**Rationale**: The backlog is a worklist for a human reader, and the notes are diagnostics about
the run.

**Security Scan Note**: Note the consequence honestly rather than reading it as an oversight to
tidy: when a source degrades, its bucket renders in the committed file exactly as a genuinely
clean one. A run where the behavior graph could not be read writes "0 uncovered source file(s)"
under **Coverage gaps**, and "no findings.json — run codebase-security-scan" becomes `_None._`
under **Open security findings**. The distinction SPEC-028 works to preserve — never a silent
zero — is preserved in the report and lost in this rendering of it.

## Related Specs

- [SPEC-028: The Status Census](./SPEC-028-the-status-census.md) — the report this renders, and
  the degradation rule whose notes stop at the boundary
- [SPEC-030: Wrap-Up Orchestration](./SPEC-030-wrap-up-orchestration.md) — the other writer of
  this file, which regenerates it in the artifacts commit

## Change History

| Date | Change | Reason |
|------|--------|--------|
| 2026-08-21 | Initial spec, inferred from code and tests | Brownfield scan (`freya-spec-manager bootstrap`) |

---

*Certainty 75. The overwrite is deliberate beyond doubt — it is stated in the skill with a line
citation, restated in `roadmap.md`, and cost this project a file rename, which is about as much
corroboration as an inferred decision gets. The document's shape and the do-not-edit banner are
asserted by a real test. Held at 75 rather than higher because the two most consequential
properties (the destructive overwrite and the gap-sample cap) have no test at all, and because
the notes-stop-here boundary is a rendering hole rather than a stated choice — nothing in the
code or prose says it was considered, so calling it deliberate is the weakest inference in this
spec.*
