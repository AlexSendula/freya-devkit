---
id: ADR-024
title: Symbols refine a file anchor, never replace it, and stay off by default
status: accepted
created: 2026-08-21
updated: 2026-08-21
tags:
  - code-graph
  - substrate
  - artifacts
  - behavior-layer
---
# ADR-024: Symbols refine a file anchor, never replace it, and stay off by default

## Decision

Symbol-level detail is an optional refinement on a record whose anchor is always a
file path, in the two artifacts that have it.

In `graph.json`, an edge may carry `from_symbol`, `to_symbol` and `line` alongside
its `to`/`from`, `kind` and `provenance` (`skills/freya-code-graph/scripts/substrate.py:107`,
`:125`). In `behavior.json`, an `exercises` entry may carry `symbols` — a sorted list
of function names — alongside its `path`
(`skills/freya-behavior-runner/scripts/run_behaviors.py:178`). Neither field is ever
the anchor. An edge that omits its symbols is the file-level edge that shipped before
they existed, and an exercise entry that omits them is byte-identical to a pre-symbol
one.

Graph refinement is off unless a project asks for it: `substrate.symbols` in the
project's `knowledge-base/settings.json`, falling back to a machine-level default,
defaulting to `false` (`skills/freya-code-graph/scripts/settings.py:108`, `:435`).
Asking is a request, not a requirement — a backend that cannot see symbols is
unaffected, and the floor resolver declares only `imports` and `re_export`
(`skills/freya-code-graph/scripts/graph_ops.py:428`), so turning the flag on
for a homegrown project changes nothing.

A behaviour's symbols come from the istanbul coverage report — the named functions
whose execution count is non-zero — and never from the code graph
(`run_behaviors.py:106`). There is one `exercises` entry per file, with symbols as a
list on it, not one entry per symbol.

`docs.json` has none of this, although the design said it would. Its edges are
`{target, line, via, provenance}` (`skills/freya-docs-manager/scripts/docs_graph.py:366`)
and the file contains no occurrence of the string `symbol` at all. The polyglot spec
§5 states the refinement rule applies "in every artifact" and §6 says a docs edge's
target is "a file path, refined with an optional `symbol`"; that was never
implemented, and the docs graph (ADR-026) is file-level. This is recorded here as a
gap, not as behaviour.

## Rationale

graphify records `calls`, `inherits` and `mixes_in` between symbols, which is
strictly sharper than file-level imports: *this function changed, these three callers
care* beats *this file changed, these twelve importers care*. Discarding that detail
would have meant paying a full parse and keeping a regex-scraper's precision.

But symbol names are not durable identifiers, and this project had already learned
that once. Behaviors carry stable `BEH-NNN` ids precisely because file names and
scenario titles are not durable (ADR-001). Rename a function and a symbol-only anchor
breaks silently — and `behavior.json` is committed (ADR-017), so a broken anchor
becomes a diff someone has to resolve by hand, in the one artifact whose value is
that it was measured rather than typed.

Keeping the file anchor makes current behaviour the floor. Nothing can regress below
what shipped before symbols existed, which is what allowed this to be adopted
incrementally rather than as a cutover. That is verified rather than assumed: with
the same graphify output projected both ways, `--impact`, `--dependents` and
`--dependencies` on `substrate.py` return byte-identical JSON with refinement on and
off — 11 affected files, 10 dependents, in both modes.

The refinement is not free, which is why it is off. Re-derived on 2026-08-21 at
commit `2762d54`: on this repository the projection produces **122 file-level edges,
and 732 with `substrate.symbols` enabled — over the same 79 file pairs**, across the
73 files the projection anchors an edge on. Six times the edges for exactly zero
change in what any query answers. The cause is arithmetic rather than a defect: a
test module that calls one helper sixty times is sixty distinct symbol pairs and one
dependency. Two earlier figures for this cost were recorded during development,
73→417 and 120→698; both were true of earlier states of this repository and neither
reproduces now, so the ratio is the durable fact here and the counts are not.

Nothing narrows on those symbols. The only code that reads them is the printed edge
annotation on `--query --format summary`, which renders `[calls: caller → callee:42]`
(`graph_ops.py:2775`). Everything that gates or feeds another skill works in path
strings by design (ADR-021). So the size is currently paid for human display, and
default-off is the honest price for a consumer that does not exist yet.

For behaviours the source had to be the coverage report, because `source: observed`
means *the test ran this*. Graph symbols would contribute functions the test merely
loaded — inference wearing measurement's label, which is exactly the distinction the
trust model rests on (ADR-003, ADR-006). Two filters do the work, both derived from
reading a real report and both still reproducing today against the testbed's
`coverage-final.json`: **executed only**, and **named only**. That report carries 775
functions across its 123 entries; 405 of them are `(anonymous_N)`, where N is a
positional counter per file — `(anonymous_1)` occurs in 44 of them — so inserting one
function renumbers every later one and would churn a committed file's diff on an edit
that changed nothing about what ran (`run_behaviors.py:178`). The execution filter is
the sharper of the two on that report: exactly one of the 775, `verifyChallenge` in
`lib/webauthn.ts`, has a non-zero count, because a coverage report instruments what
the test loaded and not what it entered.

Symbols reach `behavior.json` only on the observed path. The static fingerprint used
for integration-level behaviours passes none (`run_behaviors.py:384`), which is
correct: a static dependency closure is inference and has no measured function to
name.

One precondition sits underneath all of this and belongs to ADR-023, but is worth
naming here: a symbol name has to identify a symbol, not merely describe one.
graphify labels a method with its bare name, so qualification by the owning class is
what makes the refinement usable. Re-derived on 2026-08-21, 108 of the 2,553 code
symbols indexed on this repository share a bare label with a sibling in the same
file; qualifying with the owner takes that to zero
(`skills/freya-code-graph/scripts/backend_graphify.py:608`).

## Rejected Alternatives

- **Move wholly to symbol anchors.** The sharpest possible graph, and the one
  graphify natively produces: a `calls` edge between two named functions, with no
  file-level noise and none of the dual-key bookkeeping the reverse index now carries
  to keep symbol-refined edges distinct (`substrate.py:363`). Rejected on durability
  and on reach. Names are not stable ids, so every rename becomes a breaking change
  to a committed artifact; and it is a one-way door — file-level is recoverable from
  symbol-level only if *every* backend supplies symbols, and the floor backend
  supplies none, so the floor could never be the fallback again.

- **Fold graphify's symbol edges down to file level and discard the symbol
  entirely.** Free in every sense: nothing downstream changes, the artifact stays
  small permanently, and there is no optional field to validate or to explain.
  Rejected because the backend has already computed the detail — throwing it away
  means paying graphify's parse cost to get a resolver's precision — and because an
  optional field costs a project that does not ask for it precisely nothing.

- **Turn refinement on by default.** Every project would get the sharper artifact
  without having to discover a setting, and a future symbol-aware consumer would find
  the data already sitting there rather than needing a rebuild first. Rejected on the
  6x measured above, paid on every build by every project for no change in any
  answer. `graph.json` is not committed (ADR-017), so the cost is build time and disk
  rather than diff — but it is still a cost imposed on everyone for a reader that
  does not exist. Off-by-default is also the reversible direction: a project turns it
  on with one setting and one rebuild.

- **Make symbols graph nodes.** The honest model of what graphify actually produces,
  and the only shape that could express intra-file calls — which the file projection
  has to drop outright, since an intra-file call has no file pair to refine
  (`backend_graphify.py:662`). Rejected because that is a different graph, not a
  refinement of this one: all three artifacts are joined on file path (ADR-025), and
  a second node type invalidates every consumer at once. The intra-file call graph is
  a real loss and is on the backlog rather than being quietly written off.

- **Take a behaviour's symbols from the code graph.** The obvious source, already
  built, and it would work for every backend and every language instead of only for
  istanbul-instrumented JavaScript. Rejected because it silently changes what
  `observed` means. The graph would contribute functions the test loaded but never
  entered; on the one real coverage report available that is the difference between
  one function and 775. A fingerprint that mixes the two is no longer evidence of
  anything.

- **One `exercises` entry per symbol.** A flat list is easier to filter, and it makes
  the symbol a first-class row rather than an attribute of a file. Rejected because
  `behavior-graph` reads `exercises[].path`, and Direction B returns those paths as a
  list (`skills/freya-behavior-graph/scripts/behavior_graph.py:240`), so a file with
  three exercised functions would be reported three times and every count derived
  from that list would shift. A refinement must not change cardinality.

- **Bump `behavior.json`'s `version`.** Exactly what a version field is for, and it
  would let a future reader distinguish a pre-symbol file from a post-symbol one.
  Rejected because there is no such reader: the field is written
  (`behavior_graph.py:230`, `run_behaviors.py:446`) and nothing anywhere inspects it,
  unlike `graph.json`'s version, which really does drive a staleness rebuild
  (`graph_ops.py:2140`). Bumping it would have been a compatibility gesture with no
  compatibility behind it. The guarantee that matters is structural and is asserted
  instead of announced: an entry with no symbols is byte-identical to one written
  before the field existed
  (`skills/freya-behavior-runner/scripts/test_run_behaviors.py:336`).

- **Narrow Direction A with symbols** — wake only the behaviours whose measured
  functions a change actually touched, rather than every behaviour that touches the
  file. The sharpest blast radius the data could support. Rejected because there is
  nothing to intersect against: `--impact` answers in path strings by design
  (ADR-021), so the impact side carries no symbol at all. Narrowing on one side only
  generates misses, and a miss in Direction A is precisely the failure the behavior
  layer exists to prevent.

## Revisit Conditions

- **A consumer appears that genuinely narrows on a symbol.** The default-off trade
  rests entirely on there being none; today the sole reader is a print statement
  (`graph_ops.py:2775`). When `behavior-graph`, `docs-manager` or wrap-up wants to
  answer *which function*, re-argue it — and start with whether the switch should be
  per relation kind (`calls` only, say) rather than one global boolean, since that is
  where most of the 6x comes from.

- **A backend exposes symbol *ranges*, not just start lines.** This is the concrete
  blocker on the `docs.json` gap recorded above: mapping a `path:line` citation onto
  the symbol containing that line requires knowing where a symbol ends, and
  graphify's node `source_location` gives a start only. When ranges arrive, either
  docs edges get symbol targets or spec §5's "in every artifact" gets struck — it
  must not stay stated as present fact in either place.

- **A coverage adapter lands for a non-istanbul runner.** `symbols` is captured from
  one hard-coded path, `coverage/coverage-final.json` (`run_behaviors.py:213`), so it
  is in practice a vitest/unit-level field. If coverage.py's report turns out not to
  name functions per file — the design assumed it does, and nothing has checked —
  then `symbols` is JavaScript-only, and that asymmetry belongs in the backend's
  declared `Coverage` rather than being discovered by a caller who finds an empty
  list.

- **Symbol identity becomes stable.** The file anchor is insurance against renames.
  A backend that emits an identifier surviving a rename removes the argument that
  made the dual anchor necessary, at which point it is redundant complexity rather
  than a floor.

- **The 6x ratio does not hold at scale.** It was measured on one 73-file repository
  — this one. A project with thousands of files and a heavier call graph could be far
  worse, in which case per-kind opt-in stops being a refinement of this
  decision and becomes a correction to it. Measure before assuming it carries.
