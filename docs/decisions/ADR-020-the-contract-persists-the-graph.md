---
id: ADR-020
title: The contract persists the graph; a backend only produces it
status: accepted
created: 2026-08-21
updated: 2026-08-21
tags:
  - substrate
  - code-graph
  - artifacts
---
# ADR-020: The contract persists the graph; a backend only produces it

## Decision

A backend's `build()` and `update()` return a `substrate.Result` — the graph it produced, and
what it did to produce it (`skills/freya-code-graph/scripts/substrate.py:269`). Everything after
that belongs to the contract. `run_build` and `run_update` (`graph_ops.py:2562`, `:2567`) pass
the result to one shared funnel, `_finalise` (`graph_ops.py:2417`), which derives the
`dependents` reverse index (`:2452`), refuses to overwrite a populated graph with an empty one
(`:2454`), validates what the backend emitted and records any errors in the artifact
(`:2460`–`:2477`), takes the census of in-scope files the backend cannot read (`:2485`), and
writes both `graph.json` and `graph.<backend>.json` (`:2490`, and ADR-028 for why there are two).
`persist_graph` has exactly one production caller, and it is that line.

A backend that returns anything other than a `Result` is rejected by name rather than
mishandled (`graph_ops.py:2420`). `project_dir` is a required backend attribute for this reason
alone — the contract does the writing, so it has to be told where (`substrate.py:572`, `:625`).

`Result` is a type rather than a bare dict because a dict cannot say "nothing changed", which
`update` has to be able to say without a sentinel every caller then has to recognise
(`substrate.py:270`–`280`, `:299`).

What the backend keeps is the decision to *rebuild*. Only it knows which tool ran and what that
tool can see, so when a backend reports its artifact current the contract writes nothing, even
if that artifact is schema-old: it says on stderr that the backend should have rebuilt it and
leaves it alone (`graph_ops.py:2425`–`:2443`).

## Rationale

Phase 1 moved the homegrown resolver behind an interface and the review's verdict was that the
interface was homegrown's own shape wearing a costume: the vocabulary and the metadata block
were real, but the executable part of the contract stopped exactly where the incumbent's private
methods began. Linking `dependents`, validating, and writing the file all lived inside
`CodeGraph`. `dependents` — the reverse index every consumer actually reads for blast radius —
was not mentioned in the contract at all.

That was demonstrated rather than argued. A second backend written strictly to the documented
obligations exited 0, printed a file count, and wrote no graph. It satisfied every published
requirement and produced nothing, reporting success — which is ADR-005's confidently-empty
answer one level up, arriving through the socket that was supposed to prevent it.

Central derivation is not merely convenient here, it is more correct. `dependents` is a pure
function of `imports`, so computing it once in the contract is strictly better than asking every
backend to emit it right; and it is rebuilt from scratch on every write rather than appended to,
because an incremental pass that only adds entries leaves an edge behind when the import that
justified it is deleted (`substrate.py:307`–`:313`). The reverse edge carries the forward edge's
kind and provenance (ADR-021) and its symbols (ADR-024), which is a second thing no backend now
has to remember.

The wiring also gave the contract's own validator its first caller. `substrate.validate_graph`
existed, was well written, and had zero production callers, so nothing checked that a produced
graph was well-formed — including ours. It now runs on every write. **It does not block.** A
graph that fails validation is written anyway, with the errors recorded under
`substrate.validation` in the artifact and the first one printed to stderr. And nothing reads
that field: outside the schema reference and the tests, no code branches on it. It is a
diagnostic for whoever opens the graph a week later, not a gate — recorded and unenforced, and
it should be read that way rather than as a guarantee that a graph on disk is sound.

Exactly one check does block, and it is the one validation cannot make: an empty `files` dict is
*valid* — there is no edge to be wrong about — so a backend that silently stops working would
overwrite a good graph and report `status: built`. `_refuse_to_erase` raises instead
(`graph_ops.py:2508`), which lets the caller degrade to the floor and keeps the previous artifact
until something can replace it honestly (ADR-019).

The split holds up now that a second backend is real: `GraphifyBackend.build()` extracts,
projects onto the contract's shape and returns a `Result` — it opens no artifact and writes no
graph (`backend_graphify.py:329`–`:338`). The funnel has also proved to be the right shape for
work decided later; the unread-file census of ADR-029 was added to `_finalise` rather than to any
backend, and it is correct for both because it sits at the single point every backend passes
through.

## Rejected Alternatives

- **Leave persistence in each backend and document what it must do.** Cheapest by far: the
  incumbent keeps working untouched, and a future backend can write whatever layout suits it
  best — a database, a stream, an incrementally-patched file. It is also precisely the thing
  Phase 1's review found. A contract enforced by prose was already in place when the second
  backend satisfied every documented obligation and still wrote no file. The failure was not
  that the document was unclear; it was that nothing executed it.

- **Have `build()` return the finished graph dict and let the caller persist it.** No new type,
  no vocabulary to learn, and the smallest possible diff to the incumbent's signature. It cannot
  express the two things the update path needs to report: "nothing changed" (which then needs a
  sentinel — `None`, or an empty dict — that every caller must know how to read, and which
  collides with the genuinely-empty graph `_refuse_to_erase` exists to catch) and how many files
  moved, which is the only number the update summary has. `Result` carries the status and the
  count beside the graph and costs one class with three slots.

- **Keep `dependents` a backend obligation and add it as a seventh requirement.** It would have
  bought a real saving on the second backend: graphify already knows both directions of every
  link, so emitting the reverse index during projection is close to free, whereas the contract
  now recomputes it in a second pass. Rejected because derived data emitted independently by N
  backends is wrong in N ways — and the one incremental optimisation any of them would reach for,
  appending to the existing index instead of rebuilding it, is the specific bug that leaves a
  dependent listed after the import is deleted.

- **Put the shared half in `backends.py`, next to the registry.** Attractive on size alone:
  `graph_ops.py` is over three thousand lines and already holds both the floor and the CLI, so
  the contract's shared code sitting in it looks like the incumbent owning the socket again.
  Selection and finalisation are different concerns, though, and the test that matters is that a
  backend which is never selected must still be finalisable by its own suite — the graphify
  tests call `graph_ops.run_build` and `_run_or_degrade` directly, with no registry involved
  (`test_backend_graphify.py:817`–`:819`, `:842`). `substrate.py` was not an option either: it is
  the contract and deliberately knows nothing about implementations (`backends.py:4`), while
  finalisation must reach into the floor — `_finalise`'s census constructs a `CodeGraph` to
  borrow its scope rule (`graph_ops.py:2651`).

- **Refuse to write a graph that fails validation.** The strict reading, and the one that makes
  the validator a guarantee rather than a note: no consumer could ever act on an edge the
  contract already knew was broken. It loses more than it saves. Validation errors are per-edge —
  a dangling target, an unknown kind — and refusing the write over one of them throws away a
  graph that is right about everything else, leaving consumers with a staler artifact or none at
  all. That is a worse answer than a flagged one. The errors ride in the file instead, because
  the stderr of the run that produced them is gone by the time anyone reads the graph.

## Revisit Conditions

- **A backend appears whose graph should not be materialised whole.** The contract takes the
  entire graph as a value and writes it in one `json.dumps`. A daemon- or database-backed
  substrate, or any backend on a repository large enough that the artifact stops fitting
  comfortably in memory, breaks that shape; the socket would then need a write *interface*
  (chunked or incremental persistence) rather than a return value. Watch for it when a project
  an order of magnitude larger than the ones this was built on is graphed.

- **Something acts on an edge that `substrate.validation` already flagged.** Today the field is
  written and read by nothing. The first time a wrong blast radius is traced back to an error
  already recorded in the artifact, the choice above stops being defensible — either validation
  gates the write, or consumers learn to read the field. What must not happen is that it stays a
  decoration nobody checks; if no reader has appeared by the time the field is inconvenient,
  delete it rather than keep it as evidence of a promise.

- **`_refuse_to_erase` starts firing on legitimate builds.** It compares against the active
  artifact whoever wrote it (`graph_ops.py:2527`), so switching a repository from a polyglot
  backend to the floor — a Java project going from a full graph to zero readable files — trips
  the refusal, and when the floor *is* the running backend the CLI exits 1 and tells the user to
  `--clear` first. That is right for a backend that broke and wrong for a backend swap that
  worked as designed. If the swap case shows up in practice, the guard needs to compare against
  the same backend's own copy rather than the active one.

- **Rebuilding the reverse index stops being free.** Measured on this repository on 2026-08-21:
  0.0008s for 62 files and 465 import edges, on both the homegrown and graphify artifacts — noise
  against everything else a build pays. It is a full pass over every edge on every write,
  including an `--update` that changed one file, so a repository two or three orders of magnitude
  larger, or symbol-refined edges multiplying the edge count, could make it matter. Measure
  before assuming it still holds; if it does not, the answer is an incremental relink that is
  correct about deletions, not a return to per-backend `dependents`.
