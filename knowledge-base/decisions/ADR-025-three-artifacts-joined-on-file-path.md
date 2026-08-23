---
id: ADR-025
title: three artifacts, one owner each, joined on file path
status: accepted
created: 2026-08-21
updated: 2026-08-21
tags:
  - artifacts
  - code-graph
  - behavior-layer
---
# ADR-025: three artifacts, one owner each, joined on file path

## Decision

The graph layer is three artifacts under `knowledge-base/.graph/`, and each one is written by
exactly one piece of code.

`graph.json` holds code → code and is written by `persist_graph`
(`skills/freya-code-graph/scripts/graph_ops.py:2516`), whichever backend produced the content —
the contract persists, a backend only produces (ADR-020) — with a per-backend copy alongside it
(ADR-028). `behavior.json` holds behaviour → test → code and is written by
`write_behavior_json` (`skills/freya-behavior-graph/scripts/behavior_graph.py:206`);
behavior-runner produces the observed fingerprints and never writes the file, which its module
docstring states as its first fact (`skills/freya-behavior-runner/scripts/run_behaviors.py:5`).
`docs.json` holds doc section → code and is written by
`skills/freya-docs-manager/scripts/docs_graph.py:29`. Three artifacts, three owners, three
commands on the launcher — `code-graph`, `behavior-graph`, `docs-graph`
(`bin/commands.json:2`, `:3`, `:7`).

They share one key space: the project-relative POSIX file path. Joining them is a set operation
on that key and needs no translation table. `_affected_from_impact` is the join in full —
`{e["path"] for e in entry["exercises"]} & impact`, one line
(`skills/freya-behavior-graph/scripts/behavior_graph.py:271`). The runner works to stay in that
key space: istanbul reports absolute paths, and it converts each one with
`Path(abs_path).resolve().relative_to(project).as_posix()` before it becomes an exercise
(`run_behaviors.py:131`). `docs.json` edge targets are the same strings. A symbol may refine
one of those anchors but never replaces it (ADR-024), so the key survives.

There is no combined store and no fourth linking artifact. The fourth file in that directory,
`classifications.json`, is not one either: it is code-graph's own per-project classification
cache, written by the same owner as `graph.json` (`graph_ops.py:398`).

What is *not* built is the query layer the design named — a reader that loads whichever
artifacts are present and answers across them. Two pairwise joins ship instead, each hardcoded
in the consumer: `docs_graph.load_code_files` reads `graph.json` to get the file set it
validates citations against (`docs_graph.py:321`), and `run_behaviors._code_graph_deps` shells
out to `code-graph --dependencies` to build a static fingerprint (`run_behaviors.py:291`). The
third pair has no consumer at all: nothing in the toolkit reads `docs.json`, and `freya
docs-graph` has no programmatic caller — its only mentions outside its own source are the
launcher registration and an instruction to the agent to chain it after a blast radius
(`skills/freya-docs-manager/SKILL.md:441`). The cross-artifact join is a property of the data
and a step in a skill's prose; it is not a component.

## Rationale

The three artifacts have different owners because they have different preconditions, and a
precondition that fails should cost one artifact rather than all three. `graph.json` needs a
backend that can read the languages present, which on a locked-down machine may be only the
floor (ADR-019). `behavior.json`'s observed half needs a green suite under a working runner,
and that half is the part no re-read of source can reconstruct (ADR-017). `docs.json` needs the
markdown, which is committed.

The working record went one step further than that and was wrong. It said the markdown parser
"needs nothing" and that a broken code substrate "costs you nothing in docs edges". It costs
you all of them. `load_code_files` returns an empty set when `graph.json` is missing or
unparseable (`docs_graph.py:332`), and an empty set discards every citation — deliberately,
because with no graph there is nothing to check a path against and a resolver that guesses
invents edges into files that may not exist. Measured on this repository on 2026-08-21:
`build()` with the code graph present produced 39 documents and 273 edges; the same call with
an empty file set produced 39 documents and 0 edges. At build time the docs graph is a
*dependent* of the code graph rather than a peer of it; once built, `--impact` answers from
`docs.json` alone.

What separation actually buys is that the failure is confined to one artifact and named inside
it. `docs.json` carries `code_graph_present` in every build (`docs_graph.py:392`), so a
zero-edge artifact is distinguishable from a repository nobody documented. `_code_graph_deps`
returns `None` with a reason — `no-graph`, or `graph-degraded: <backend>` — rather than the
empty closure it used to return, and the merge then preserves the prior fingerprint instead of
overwriting it with a narrower one (`run_behaviors.py:291`). That is ADR-029's rule applied at
the artifact level: an answer says what it could not read. One combined file could carry the
same flags in principle, but it would carry them for a document nobody can partially refresh —
whichever producer ran last would decide the whole file's freshness, and a caller reading it
could not tell which half was current.

Separate files are also what lets the git decision be made per artifact.
`knowledge-base/.graph/.gitignore` names `graph.json`, `graph.*.json`, `classifications.json`
and `docs.json` individually and deliberately omits `behavior.json` (`graph_ops.py:245`, with a
byte-identical copy in `behavior_graph.py:122` that `test_substrate.py:1574` pins). ADR-017
argued that split; it is only expressible because the artifacts are three files.

In this repository that nested file decides nothing, and the reason is worth stating precisely
because a reader will otherwise take the shipped documentation at face value. The root
`.gitignore:18` excludes `**/.graph/` wholesale, so git never descends into the directory:
`git check-ignore -v knowledge-base/.graph/behavior.json` answers `.gitignore:18:**/.graph/`,
and `git add` on it refuses with "The following paths are ignored". Reproduced 2026-08-21 in a
scratch repository carrying both ignore files: with the root line present the add is refused;
with that one line removed, `git add -A` stages `behavior.json` and only `behavior.json`,
exactly as the nested file intends. An adopting project has no root `**/.graph/` rule, so the
nested file governs there and ADR-017's guarantee holds. Here it does not, and nothing under
`knowledge-base/` has ever been tracked in this repo, so nothing is lost today — but this
repository is not a witness for ADR-017, and `references/graph-schema.md:16` states as flat
fact that "the one file in that directory which *is* tracked is `behavior.json`", which is true
of an adopting project and false where it is written.

The artifacts also grow on unrelated axes, which is a practical argument against one store. On
this repository on 2026-08-21 `graph.json` was 62 files and ~80 KB while a fresh `docs.json`
was ~155 KB — the code graph scales with source files, the docs graph with prose, and neither
number predicts the other.

A linking graph would be an empty table. Every edge in all three artifacts already lands on a
repo-relative path, so there is no identifier to translate; the join is `&`.

## Rejected Alternatives

- **One merged graph store.** Simplest to query: one file to open, one schema, one version
  number, and a cross-artifact question answered by a lookup instead of by chaining two
  commands. It would have made the unbuilt query layer unnecessary by construction. Rejected on
  ownership — three producers with different preconditions writing one document means every
  write is a partial write, and a caller reading it cannot tell which part is fresh. One
  argument in its favour should *not* be reused: that merging is mechanically impossible
  because `behavior.json` is committed while `graph.json` is ignored. That was overstated.
  `behavior.json` is reproducible by re-running the suite, so the difference is cost and
  precondition, not possibility.

- **Three artifacts plus a fourth linking graph.** Considered explicitly. It would have bought
  an indirection point: if any artifact later moved to an identifier that is not a file path,
  only the linking layer would learn the new key and no consumer would change. Rejected because
  it is an empty table today — every producer already speaks paths, and the runner does real
  work to keep it that way (`run_behaviors.py:131`). A fourth artifact means a fourth producer,
  a fourth staleness question and a fourth failure mode bought for a translation that is the
  identity function.

- **Unify the code graph and the behaviour graph.** The recorded lean before the substrate
  contract existed, on the grounds that one real substrate would tighten the behaviour↔code
  connection and give symbol-level exercises out of the same pass. Dropped: the contract
  (ADR-018) delivers that tightening without coupling the behaviour layer to the substrate
  choice, and the coupling is the expensive half. `behavior.json` is the one artifact that must
  survive a substrate swap intact; `graph.json` is the one that now legitimately exists several
  times over, once per backend (ADR-028). Merging them would have made the artifact that must
  not be duplicated the one that is.

- **Let the substrate own doc edges too, and ship two artifacts instead of three.** graphify
  emits a `cites` relation, so the doc→code question could have arrived free with the code
  graph and needed no markdown parser at all. Rejected, and the rejection is enforced in code:
  the graphify backend maps `'cites': None` with the note that `docs.json` owns that question
  (`skills/freya-code-graph/scripts/backend_graphify.py:128`), listed explicitly rather than
  omitted so it does not resurface in the unmapped report on every build. Owning it in the
  substrate would have made doc edges disappear the moment a project ran on the floor backend,
  and would have anchored them wherever the backend chose rather than at the section, which is
  the anchor the question actually needs (ADR-026).

- **Resolve doc citations without a code graph to check them against.** The alternative that
  would have made the design's "requires nothing" true, and given a docs graph that works on a
  repository where no backend has ever run. Rejected in the code comment at `docs_graph.py:324`
  — without a graph there is nothing to check a path against, and guessing invents edges. A
  second tree walk would also answer the scope question differently from the graph's own
  exclusion rules (ADR-022), so `--impact` would return doc sections pointing at files no blast
  radius knows about. Discarding every citation and saying so was preferred to resolving some
  of them and not knowing which.

## Revisit Conditions

- **An artifact needs a key that is not a file path.** A substrate that exposes stable symbol
  ids but not the file they live in, a test id that no longer maps to a file, or doc anchors
  that outlive their document. Today symbols are an optional refinement on a path anchor
  (ADR-024), which is what keeps `&` sufficient. The first producer that cannot supply a path
  makes the fourth-artifact alternative real.

- **The third pair gets a consumer.** Nothing joins `docs.json` to `behavior.json` today, and
  no code reads `docs.json` at all. The first question that crosses both — "which doc sections
  describe the code this behaviour exercises?" — is the point at which the agent-chained join
  stops being adequate and the query layer has to be built and given a home. Decide then
  whether it lives in code-graph or in its own module; do not assume the answer now.

- **`docs.json` stops being derivable from committed markdown.** The current ignore rule rests
  on that: it is regenerable in the same sense the graph is. Any edge in it that comes from
  running something — a model pass, a link checker, anything not a parse of tracked text —
  moves it into `behavior.json`'s category, and ADR-017's argument then applies to it too.

- **This repository needs to dogfood a committed `behavior.json`.** It cannot today: the root
  `.gitignore:18` `**/.graph/` shadows the nested rule and makes git refuse the add. Narrowing
  that one line to the four regenerable filenames is the fix; do it before relying on this repo
  to demonstrate ADR-017 rather than only to describe it.
