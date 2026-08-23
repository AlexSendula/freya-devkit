---
id: ADR-017
title: behavior.json is committed; only the parse cache is ignored
status: accepted
created: 2026-08-19
updated: 2026-08-19
tags:
  - behavior-layer
  - code-graph
  - artifacts
---
# ADR-017: behavior.json is committed; only the parse cache is ignored

## Decision

`knowledge-base/.graph/.gitignore` names the regenerable files individually
instead of using a blanket `*`. `behavior.json` is tracked. Its `exercises` lists are sorted by path at write
time so the committed file is byte-stable across rebuilds.

> **Correction, 2026-08-21.** This originally named the list — "the two regenerable files,
> `graph.json` and `classifications.json`" — and the list grew: it is now `graph.json`,
> `graph.*.json`, `classifications.json` and `docs.json` (ADR-025, ADR-028). Naming a mutable
> list inside a decision is what made this record wrong within a fortnight; the decision was
> always *name them individually rather than use `*`*, and that is what it says now.
>
> The first revisit condition below — "Track B introduces a substrate that owns and clears
> `.graph/` wholesale" — was checked on 2026-08-21 and is **not met**. `CodeGraph.clear()`
> unlinks `graph*.json` and calls `rmdir()`, which fails harmlessly while `behavior.json` is
> present. `behavior.json` stays where it is.
>
> One caveat this record did not anticipate: in *freya-devkit's own repository* a root
> `.gitignore` rule (`**/.graph/`) shadows the directory, so git refuses to add
> `behavior.json` here even though an adopting project commits it. The decision is about
> adopting projects and holds there; this repo is the exception, not the rule.

> **Correction, 2026-08-21 (second).** The caveat above is no longer true, and the exception it
> describes is gone. `**/.graph/` was removed from this repo's root `.gitignore` when
> freya-devkit adopted `knowledge-base/` and began running the toolkit on itself;
> `git check-ignore knowledge-base/.graph/behavior.json` now exits 1. The rule was the reason
> this repository could not honour its own decision, which is exactly the kind of thing
> dogfooding surfaces and nothing else does — note that the mechanism was never specific to
> this repo either: *any* adopting project that adds `**/.graph/` by hand hits it, because git
> does not descend into an ignored directory to read the `.gitignore` the toolkit writes
> inside it.

## Rationale

The three files in `.graph/` are not the same kind of artifact.

`graph.json` and `classifications.json` are a **parse cache**. They are
rebuildable from source in seconds, and large — 124 KB for a ~230-file project.
Committing them would put an unreadable, conflict-prone diff in a large share of
commits, and a generated-JSON merge conflict has no meaningful hand resolution.
Measured: two builds of byte-identical input produce byte-different `graph.json`,
because the `imports` arrays are assembled from a set. Ten of ten differing
entries were pure reordering, so the content is deterministic and the file is
not. Committed, it would show a diff on every build with zero code change.

`behavior.json` is not a parse cache. Most of it *is* derivable — `spec_id`,
`state`, `level`, `adapter` and `locator` are copied from the spec, which is
committed, and `source: static` edges recompute from the graph. But the
`source: observed` edges are captured by **running the test suite** under
coverage. They cannot be recovered by re-reading source, only by re-running a
green suite with a working runner. That is the precise part of the file, and the
part the behavior layer's blast radius rests on. Ignored, a fresh clone starts
with no observed coverage and silently degrades to `static`/`unknown` — the
"coverage-unknown, never silent" failure mode ADR-005 exists to prevent.

Nobody had weighed this. The blanket `*` came from dogfooding finding F8, which
was filed as a bug — the `docs/.code-graph/` → `knowledge-base/.graph/` rename
had lost an ignore rule that already existed — for a directory that at the time
held only the parse cache. `behavior.json` shipped in Phase 2 and landed in that
directory afterwards, inheriting a rule written before it existed. Both writers
then wrote the file only when absent, so no already-onboarded project would ever
have picked up a correction.

Sorting is a precondition, not a nicety: the static edges come from the same
unordered closure as `graph.json`, so an unsorted `behavior.json` would produce
the spurious per-build diff that makes committing `graph.json` a bad idea.

## Rejected Alternatives

- **Keep the blanket `*` and accept the cold start.** The status quo, and the
  default if nobody looks. It costs every fresh clone its observed fingerprints
  and does so silently — the loss is invisible until someone reads a blast radius
  that is quietly narrower than it should be.

- **Move `behavior.json` out of `.graph/` to `knowledge-base/behavior.json`.**
  Initially recommended here, on the reasoning that `.graph/` is the substrate's
  directory and a substrate swap (Track B) could clear it, taking the one
  unrebuildable artifact with it. Checking the code refuted that: nothing does
  `rmtree` on `.graph/`, and the only cleanup path, `GraphOps.clear()`, unlinks
  `graph.json` then calls `rmdir()`, which fails harmlessly while other files are
  present. The move would have superseded ADR-004's placement, touched seven path
  references and required an adopter migration, to buy a risk that does not
  exist. If Track B ever introduces a real substrate-wipe, revisit.

- **Commit `graph.json` too.** Would let CI skip a rebuild and let a reviewer see
  blast radius change in a PR. Rejected on the measured churn: unstable ordering
  means a diff on every build even when nothing changed, and at 124 KB it drowns
  the reviewable content it was supposed to expose.

- **Sort only when writing, and leave the producers unordered.** This is what
  shipped, and it is deliberate: `write_behavior_json` is the single choke point
  every producer passes through, so one sort there fixes determinism for the
  runner, the static closure and any future coverage adapter at once. Sorting in
  each producer instead would need repeating for every adapter Track B adds.

## Revisit Conditions

- **Track B introduces a substrate that owns and clears `.graph/` wholesale.**
  Then the second alternative above becomes real and `behavior.json` should move
  out. This is the likely trigger — check it when the substrate fork is decided.
- **`behavior.json` stops being small.** The churn argument is currently waived
  because the file is ~1.4 KB on a real project. A project with thousands of
  accepted behaviors and observed coverage on each could change that; measure
  before assuming it holds.
- **Merge conflicts on it become routine** rather than rare. The intended
  resolution is to re-run the suite, not to hand-merge; if that proves painful
  in practice, reconsider whether the observed edges belong in a separate file
  from the derivable ones.
