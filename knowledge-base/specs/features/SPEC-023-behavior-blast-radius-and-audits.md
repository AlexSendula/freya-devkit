---
id: SPEC-023
title: Blast radius in both directions, and the uncovered-code audit
category: features
tags: [behavior-layer, behavior-graph, blast-radius, coverage-gaps, security-cross-reference, adr-001, adr-004]
status: implemented
certainty: 80
created: 2026-08-21
updated: 2026-08-24
related_code:
  - skills/freya-behavior-graph/scripts/behavior_graph.py
  - skills/freya-behavior-runner/scripts/run_behaviors.py
intentional_decisions:
  - "Direction A over-approximates on purpose: a false 'might be affected' costs one test run, a false 'not affected' costs a regression"
  - "The security cross-reference answers with accepted behaviors only, never confirmed ones"
  - "A file the code graph indexed is not automatically code a behavior could cover"
  - "Direction B answers with an empty list for a behavior id it has never seen"
behaviors:
  - behavior_id: BEH-111
    title: A changed file returns the behaviors whose exercised code its blast radius reaches
    state: proposed
    level: component
    adapter: unittest
    locator: skills/freya-behavior-graph/scripts/test_behavior_graph.py#DirectionATest.test_affected_when_exercises_intersect_impact
  - behavior_id: BEH-112
    title: A behavior id returns the project files that behavior exercises, in sorted order
    state: proposed
    level: unit
    adapter: unittest
    locator: skills/freya-behavior-graph/scripts/test_behavior_graph.py#DirectionBTest.test_returns_exercised_paths
  - behavior_id: BEH-113
    title: The security cross-reference for a file answers with accepted behaviors only
    state: proposed
    level: component
    adapter: unittest
    locator: skills/freya-behavior-graph/scripts/test_behavior_graph.py#SurfaceTest.test_covering_excludes_confirmed_behavior
  - behavior_id: BEH-114
    title: The whole-repo audit lists indexed source files no behavior covers, counting a declared entry as covered
    state: proposed
    level: component
    adapter: unittest
    locator: skills/freya-behavior-graph/scripts/test_behavior_graph.py#SurfaceTest.test_gaps_lists_uncovered_source_files
  - behavior_id: BEH-115
    title: The audit run on a project with no code graph says so instead of reporting zero gaps
    state: proposed
    level: component
    adapter: unittest
    locator: skills/freya-behavior-graph/scripts/test_behavior_graph.py#SurfaceTest.test_gaps_no_graph_degrades_to_note
---

# Blast radius in both directions, and the uncovered-code audit

## What

Four read-only questions answered from the committed `behavior.json`, each a single mode of
`freya behavior-graph` and each printing JSON on stdout:

- **`--affected <files>` (Direction A)** — which behaviors a code change touches. The changed
  files are expanded through `code-graph --impact` into the change's blast radius (the inputs
  plus their direct and transitive dependents), and every behavior whose `exercises` paths
  intersect that set is returned, sorted.
- **`--implements <BEH-NNN>` (Direction B)** — which project files a behavior exercises.
- **`--covering <file>` (`--verify` optional)** — which *accepted* behaviors exercise a given
  file. This is the cross-reference a security finding is checked against: a finding in a file
  that a verified behavior deliberately exercises is a different thing from a finding in
  unguarded code. A returned behavior must **declare a locator** that stays inside the project
  and names a file that exists; a behavior declaring none is refused rather than returned.
  With `--verify`, each returned behavior's linked test is handed to `freya-behavior-runner`
  and re-run, and the row carries the verdict.
- **`--gaps`** — the whole-repo recall audit: every source file the code graph indexed that no
  behavior covers. "Covers" is the union of two things, exercised paths from the graph and
  `entry:` values declared on specs — and the second half is read from specs in **every** state,
  so a `proposed` candidate that names an entry already discharges that file from the report
  before anyone has reviewed it.

Direction A is the one with a second data source: it is the only mode here that shells out to
`code-graph`. The others read `behavior.json` alone, which is why their answers reflect the
last `--build` and not the working tree.

## Why

ADR-001 names the gap this closes: `code-graph` answers "what code does this change touch?"
and structurally cannot answer "what *intended behavior* does this change touch?" — it has no
notion of intent and no place to put a behavioral id. Direction A is that missing question, and
Direction B is its inverse, which is what makes a behavior record navigable rather than
decorative: given `BEH-NNN`, go to the code.

`--gaps` and `--covering` are the two consumers built on top of those edges rather than new
edges of their own. `--gaps` feeds the tail of ADR-007's adoption model — the corpus drains on
contact during wrap-up, and everything never contacted is worked from a generated backlog, which
needs a whole-repo view of what nothing covers. `--covering` is the security tie-in: an
`accepted` behavior is the strongest available evidence that code a scanner flagged is doing
what someone intended it to do.

The degradation rules matter as much as the answers. Every one of these surfaces has a state in
which it can return nothing, and "nothing" here reads as reassurance — no behaviors affected, no
gaps, no coverage. A project that has simply never built a graph must not be able to produce that
reassurance by accident.

## Behavior

| Behavior | State | Verified by |
|----------|-------|-------------|
| BEH-111 A changed file returns the behaviors whose exercised code its blast radius reaches | proposed | `test_behavior_graph.py#DirectionATest.test_affected_when_exercises_intersect_impact` (unittest) |
| BEH-112 A behavior id returns the project files that behavior exercises, in sorted order | proposed | `test_behavior_graph.py#DirectionBTest.test_returns_exercised_paths` (unittest) |
| BEH-113 The security cross-reference for a file answers with accepted behaviors only | proposed | `test_behavior_graph.py#SurfaceTest.test_covering_excludes_confirmed_behavior` (unittest) |
| BEH-114 The whole-repo audit lists indexed source files no behavior covers, counting a declared entry as covered | proposed | `test_behavior_graph.py#SurfaceTest.test_gaps_lists_uncovered_source_files` (unittest) |
| BEH-115 The audit run on a project with no code graph says so instead of reporting zero gaps | proposed | `test_behavior_graph.py#SurfaceTest.test_gaps_no_graph_degrades_to_note` (unittest) |

BEH-111's test supplies the impact set directly rather than running `code-graph`, which is the
seam ADR-004 built on purpose: the graph layer reaches both neighbours through exactly one
subprocess boundary each, so its own behavior is testable without either of them. What that
test does *not* pin is the expansion itself — that a dependent two hops from the change is in
the impact set at all is `code-graph`'s guarantee, not this one.

`--surface` (validate-on-hit) is deliberately absent from this table. It reads the same three
inputs and shares `_covered` with `--gaps`, but it exists to serve the wrap-up drain loop and
belongs with that workflow rather than with the query surface.

## Intentional Design Decisions

### Over-approximating is the safe direction, and it is the chosen one

**Decision**: Direction A intersects against `changed ∪ direct dependents ∪ transitive
dependents`, and a behavior is "affected" if *any* file it exercises is anywhere in that set.
An integration behavior's `static` fingerprint is its entry's whole import closure, so it is
affected by a change to anything it transitively imports.

**Rationale**: recorded in ADR-006 — a false "might be affected" costs one extra test run, a
false "not affected" misses a regression — together with the measurement that made it
acceptable (a static closure of three files against an observed one of one, false-positive rate
zero on the representative changes). Not restated. The consequence at this surface is that
`--affected` on a widely-imported utility can legitimately return most of the corpus.

**Security Scan Note**: a query that returns a large set is working as designed. Narrowing the
intersection — for example matching only files the diff literally touched — converts every
missed transitive edge into a regression that the gate reports as green.

### Only accepted behaviors are offered as evidence

**Decision**: `--covering` skips any behavior whose state is not `accepted`, even when that
behavior demonstrably exercises the file. A `confirmed` behavior covering the file yields an
empty answer.

**Rationale**: ADR-003 sets the rule that only `accepted, non-quarantined` is authoritative;
ADR-012 covers the downgrade of a finding by an accepted behavior. What is specific here is the
asymmetry with `--gaps`, which counts that same confirmed behavior — and a merely `proposed`
one — as covering the file. The two surfaces answer different questions on purpose: recall
("is anyone intending to guard this?") admits unreviewed intent, while evidence ("is this
verified?") admits nothing below `accepted`.

**Security Scan Note**: an empty `covering` list is not a claim that the file is unguarded — it
is a claim that no *verified* behavior guards it. Do not use it as a coverage metric, and do not
"fix" the asymmetry with `--gaps` by aligning the two filters; that would either let unverified
intent downgrade a finding or make every confirmed behavior's file report as a recall gap.

### A declared locator is required, not merely checked when present

**Decision**: `--covering` refuses a behavior that declares no `locator` at all, alongside the
ones whose locator escapes the project or names no file.

**Rationale**: added 2026-08-24. The check previously read only what was declared, so a
behavior declaring *nothing* skipped the predicate entirely — an `accepted` behavior with
`adapter: vitest` and no locator, and the query returned it. Tier 1 refused exactly that shape
(`missing-locator`), so a repository the gate would have blocked could still license an
ADR-012 downgrade here. It is the hole that needed no forgery, only an omission, which is why
it is worth a decision entry of its own rather than a line in the table above.

The residual, stated because it runs the other way: a `.py` fragment naming no symbol is
refused by Tier 1 and **returned** here — this check stops at the file, so "the locator
resolves" means the file is there, not that the named test is. Running the gate is therefore
worth strictly more than running this query.

**Security Scan Note**: a refusal here is the safe direction — the finding stays open. Do not
relax it to "resolve the locator if one is declared"; that is the pre-2026-08-24 behaviour.

### `--verify` re-runs the test, and `test-failed` still means two things

**Decision**: without `--verify`, `source: observed` is a **label on evidence, not a
verification of it** — a test passed once, on somebody's machine, at the commit `freshness`
names, and both inputs come from the repository being scanned. `--verify` re-runs each
returned behavior's linked test through `freya-behavior-runner`. A row whose test did not pass
is `passed: false`, and so is every inability to run: "could not determine" must never read as
"verified".

**Rationale**: added 2026-08-24, when ADR-012 retracted the argument this surface used to
carry. `covering()`'s docstring had held that running a scanned repository's suite was "worse
than the problem it would solve" — an argument against a capability this toolkit ships as a
feature, in a sibling skill this module imports. It imported a hostile-clone threat model that
does not describe what freya is: a developer runs it on a repository they already trust.

**What `--verify` does not establish** is the part to carry into a report.
`freya-behavior-runner` spells **any** non-zero exit from the test command `test-failed`, so a
red test, an uninstalled vitest and a project with no package manifest arrive as one token,
and nothing in this module separates them. Measured 2026-08-24 on a checkout with no JS
toolchain: every row came back `test-failed` while the evidence string said the tests had been
re-run and none passed. `test-failed` therefore carries a `note` naming the second meaning, and
only that reason does — a caveat printed on every row is one nobody reads on the row that
needed it. The runner's stderr is forwarded rather than swallowed, because it is the only place
the difference is visible.

**Security Scan Note**: do not report "this repository asserts an accepted behavior whose test
does not pass" from a `test-failed` row alone. Read `verified.reason` and the runner's stderr
first; on a machine where nothing was installed, that sentence is false.

### A file the graph indexed is not necessarily code a behavior could cover

**Decision**: `--gaps` excludes graph nodes whose recorded language is `json`, `xml` or
`msbuild`, keyed on the language the backend itself recorded rather than on the file extension.

**Rationale**: under the original homegrown backend "graph node" and "source file" were the
same set, so the distinction did not exist. A polyglot backend indexes manifests and project
files — `package.json`, `pom.xml`, `app.csproj` — and each of them then appeared as source with
no behavior, from there into a tracked `BACKLOG.md` and into wrap-up asking someone to write a
behavior for `package.json`. Noise in a gap report is how the report stops being read. Keyed on
the recorded language because the backend already decided what each file is, and re-deciding it
here is how two copies of one idea drift apart. Pinned by
`test_behavior_graph.py#SurfaceTest.test_a_manifest_node_is_not_a_gap`.

**Security Scan Note**: the exclusion list is about report noise, not about trust. A manifest
being absent from the gap report says nothing about whether it is reviewed; dependency review is
a different tool's job.

### Direction B cannot tell an unknown behavior from one that exercises nothing

**Decision**: `--implements BEH-999` for an id that is not in the graph returns an empty list
and exit 0 — the same answer as a behavior that is present and exercises nothing. Pinned by
`test_behavior_graph.py#DirectionBTest.test_unknown_behavior_returns_empty`.

**Rationale**: this is recorded because it *looks* like the ADR-005 violation the code-graph
side goes to some length to avoid (`get_dependents` returns `None` for an unknown node and the
CLI exits non-zero). Whether it is a deliberate simplification — a `proposed` behavior is
legitimately absent from the graph, so "not there" is a routine state rather than an error —
or an oversight is a judgement a human still owes, and it is the main reason this spec's
certainty is not higher.

**Security Scan Note**: not a resolved decision. Treat an empty `implements` as "no answer",
not as "this behavior touches no code", until someone rules on it.

## Certainty

75. Each behavior has a test asserting the observable outcome, and the two directions are named
as the layer's purpose in ADR-001 and ADR-004. Lower than SPEC-022 because more of this surface
is recent and its intent is inferred from code comments rather than from a decision record:
`--gaps` and `--covering` post-date the ADRs that describe the layer, the confirmed/accepted
asymmetry between them is stated nowhere but in two docstrings, and the Direction B empty-answer
case above is an open question rather than a documented choice.

## Related Specs

- [SPEC-022: behavior.json is a committed projection](../infra/SPEC-022-behavior-json-committed-projection.md) — the file every query here reads
- [SPEC-024: What the behavior runner will execute, and what it refuses to guess](./SPEC-024-behavior-execution-dispatch.md) — where the `exercises` edges come from
- [SPEC-005: Never a confidently empty answer](./SPEC-005-code-graph-answers-and-empty-results.md) — the same empty-versus-unknown distinction, on the code graph's own surfaces

## Change History

| Date | Change | Reason |
|------|--------|--------|
| 2026-08-21 | Initial spec, inferred from code and tests | Brownfield scan of the behavior layer |
| 2026-08-24 | `--covering` documented as requiring a declared locator; `--verify` added to the query surface with two new decision entries — the locator requirement and what re-running does and does not establish | Sync against `fix/security-findings-0-3-1`. Both are SEC remediations: the locator hole let an omission license an ADR-012 downgrade, and `--verify` exists because ADR-012 retracted the hostile-clone argument this spec's surface used to rest on |
