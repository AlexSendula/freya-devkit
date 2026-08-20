---
id: ADR-028
title: Each backend writes its own graph beside the active one
status: accepted
created: 2026-08-21
updated: 2026-08-21
tags:
  - substrate
  - code-graph
  - artifacts
---
# ADR-028: Each backend writes its own graph beside the active one

## Decision

Every build is written twice. `persist_graph` serialises the graph once and writes that same
payload to `knowledge-base/.graph/graph.json` — the active artifact every consumer reads — and
to `knowledge-base/.graph/graph.<backend>.json`, named for the backend that produced it
(`skills/freya-code-graph/scripts/graph_ops.py:2398`, `:2411`;
`skills/freya-code-graph/scripts/substrate.py:255`, `:260`). The two files are byte-identical
at the moment of writing. It has one production caller, in the contract's shared funnel
(`graph_ops.py:2490`), so no backend can opt out and none can name the file differently.

Switching backends therefore replaces the active graph and leaves the previous backend's copy
untouched, at its own path, with the `timestamp`, `commit` and `substrate` block of the build
that produced it still inside it. Both files are in the cache `.gitignore` the build writes
(`graph_ops.py:243`), so the copy is a working artifact, not a committed one — see ADR-017 for
why that line is drawn where it is. `clear()` removes the active graph *and* every
`graph.*.json` beside it (`graph_ops.py:2345`, `:2356`), pinned by a test
(`skills/freya-code-graph/scripts/test_substrate.py:1469`).

**Nothing in the toolkit reads `graph.<backend>.json.`** `backend_graph_path` has exactly one
caller outside tests and it is the write above; there is no `--compare` subcommand, and the
incremental path does not use the copy either — both backends detect that the *active* graph
was produced by someone else and force a full rebuild rather than warm-starting from a copy
they wrote earlier (`graph_ops.py:2087`–`:2098`; `backend_graphify.py:363`). So what this
decision buys is a preserved baseline on disk, not an automated comparison: the diff is run by
hand, by a person or an agent, over two files. That is the designed-and-unenforced half of it,
and it is worth stating plainly, because the guarantee is only as good as the operator who
remembers to look.

## Rationale

A substrate swap changes every blast radius in the project at once, silently and with no diff.
ADR-016's discipline says such a thing is proved against the real repository rather than argued,
and ADR-019 makes passing that comparison the gate on any backend becoming a default. Comparing
requires two artifacts to exist at the same time. Under the contract both backends write to the
same path (`substrate.py:255`), so with one file the baseline is destroyed at exactly the moment
it is needed, and the only way to recover it is to reinstate the old backend and pay a full
rebuild — a real full rebuild, since the foreign-artifact check above refuses the incremental
route.

Phase 0 escaped this only by accident of layout. graphify was measured as a raw tool, and it
writes to `graphify-out/` at the project root; `knowledge-base/.graph/` was never touched, so
the two graphs coexisted without anyone arranging for it. The moment graphify became a backend
under the contract, that accident ended, and the property Phase 0 relied on had to be paid for
deliberately.

The cost is one duplicate of the active artifact, and the active artifact is small. Measured on
this repository on 2026-08-21: homegrown produces 81,838 bytes across 62 indexed files, graphify
51,720 bytes across 73 — so the graphify projection is *smaller per file* than the floor's, and
the copy is free at this scale. The "artifact size at scale" worry that has followed this
decision around is attached to the wrong file: the ~9.3 KB-per-file figure from the Phase 0
spike describes graphify's own `graphify-out/graph.json`, which on this repository is 5.4 MB, not
the projected contract graph that gets duplicated here. `graphify-out/` is a genuine size
problem and it has its own ignore rule (`backend_graphify.py:278`); it is not this one.

Two properties follow from the second file existing, and both had to be built rather than
assumed. Adding an artifact to `.graph/` means the cache `.gitignore` has to be upgradable in
place, or an already-onboarded project keeps the list it was given and every later artifact
arrives committable — which is why `_EVER_IGNORED` records every list we have ever written
(`graph_ops.py:268`). And a cache clear that knows about only one of the two files is worse than
no clear at all: it leaves a complete, correctly-shaped, current-looking graph that nothing will
ever report as stale, whereas a missing `graph.json` at least announces its own absence.
`classifications.json` is deliberately spared by the same clear (`graph_ops.py:2352`) — it holds
human and model judgements about which directories are source, which a cache clear has no
business discarding.

**This closes ADR-017's first revisit condition, which is not met.** ADR-017 asks whether Track B
has introduced a substrate that owns and clears `.graph/` wholesale, in which case `behavior.json`
would have to move out of that directory. Checked on 2026-08-21 by running a build and then a
clear in a temporary project with `behavior.json` present: `clear()` unlinks `graph.json` and
`graph.*.json`, then attempts `rmdir()` inside a bare `try`/`except` that fails harmlessly while
anything else remains (`graph_ops.py:2356`–`:2366`). `behavior.json`, `classifications.json` and
the directory itself all survived. No shipped backend wipes `.graph/`; graphify confines itself
to `graphify-out/`. `behavior.json` does not need to move.

## Rejected Alternatives

- **One `graph.json`, overwritten by whichever backend ran last.** The status quo before this
  decision, the simplest thing, and the shape every consumer already assumes — it costs nothing
  to keep and nothing to explain. Rejected because it makes the swap unmeasurable in the one
  direction that matters. The failure mode a substrate change introduces is a *narrower* graph:
  edges the old backend found and the new one does not, which shrink a behaviour's static closure
  and let a regression through the wrap-up gate unflagged. That is invisible without the old
  numbers, and recovering them after the fact means reinstating the previous backend and
  rebuilding the whole repository — the exact cost the comparison was supposed to be cheap
  enough to always pay.

- **A single `graph.previous.json` stash.** Cheapest possible one-hop comparison, and the
  filename never proliferates however many backends ship. Rejected on two counts: it carries no
  parentage, so after a second swap it is a graph of unknown origin that a reader has to open
  and inspect to identify, and it structurally cannot hold two backends' *current* output at
  once. Validating a fallback — building with graphify, building with the floor, and asking
  whether the reduced coverage the floor declares matches what it actually lost — needs both
  sides fresh against the same source, and a one-slot stash can only ever hold the older one.

- **Copy the graph aside by hand before switching.** Effectively what Phase 0 did, and it buys
  the entire benefit for zero lines of code. Rejected because it only works when someone
  remembers, and the failure is silent and late: you discover the baseline was never taken at
  the moment you sit down to diff, by which point the source has moved too and even a rebuild
  no longer reproduces it. A guarantee that depends on remembering is not one.

- **Commit the per-backend copies so a swap shows up in a pull request.** This is the version
  that would put the substrate change in front of a reviewer, where changes are actually
  examined, rather than leaving it to whoever happens to run the diff. Rejected on ADR-017's
  measured argument: the graph is content-stable but not byte-stable, because its `imports`
  arrays are assembled from a set, so a committed copy diffs on every build with zero code
  change. Committing a *second* copy doubles that noise, and noise on every commit is what
  guarantees nobody reads the one diff that mattered.

- **Drop `graph.json` entirely and have consumers resolve the active backend's filename.** The
  only option that removes the duplication outright: one file per backend, and readers ask the
  substrate which one is live. Rejected on blast radius. Four skills read
  `knowledge-base/.graph/graph.json` as a hard-coded string —
  `skills/freya-behavior-graph/scripts/behavior_graph.py:293`,
  `skills/freya-behavior-runner/scripts/run_behaviors.py:301`,
  `skills/freya-docs-manager/scripts/docs_graph.py:327`,
  `skills/freya-spec-manager/scripts/project_shape.py:25` — and none of them imports the
  substrate module or knows the backend-selection rules. Making four skills learn how a backend
  is chosen just to locate a file inverts the point of ADR-020, where the contract owns
  persistence precisely so consumers do not have to know which backend ran. One stable path is
  the interface; the per-backend name is a working artifact behind it.

## Revisit Conditions

- **Something starts reading `graph.<backend>.json`.** Today nothing does, so a stale copy is
  inert. The moment a `compare` command or a fallback-validation check consumes it, the copy
  needs a freshness rule it does not have: it carries its own `timestamp` and `commit` and
  nothing checks either, so a comparison would happily diff today's graph against one produced
  months ago and report the difference as a substrate effect. Write that check with the first
  consumer, not after it.

- **A third backend ships, or switching becomes routine.** The copies accumulate one per backend
  name ever used and nothing prunes them; only `--clear` removes them, and it removes all of
  them. Two is free. A renamed backend also orphans its old file under the old name, which
  nothing will ever clean or report. At three or more, or on the first rename, retention should
  become an explicit setting rather than an accident of which names have been used.

- **The active artifact stops being small — measured on the projected graph, not on
  `graphify-out/`.** At 51.7 KB (graphify) and 81.8 KB (homegrown) on this repository, the copy
  costs nothing worth discussing. A repository whose `graph.json` runs to tens of megabytes
  changes the arithmetic, and the honest response is a retention policy the project can see and
  set, not silently keeping one file instead of two.

- **A backend arrives that owns `.graph/` and clears it wholesale.** That would break two things
  this record checked and found safe on 2026-08-21: `clear()`'s deliberate sparing of
  `classifications.json`, and ADR-017's placement of `behavior.json` in the same directory. Both
  need re-deciding together at that point, not one at a time.
