---
id: ADR-021
title: An edge is an object carrying kind and provenance, behind a versioned schema
status: accepted
created: 2026-08-21
updated: 2026-08-21
tags:
  - code-graph
  - substrate
  - artifacts
  - trust
---
# ADR-021: An edge is an object carrying kind and provenance, behind a versioned schema

## Decision

An edge in `graph.json` is an object. Forward it is `{"to": …, "kind": …, "provenance": …}`;
in the reverse index it is the same object keyed `from`. `kind` is one of the five values in
`RELATION_KINDS` — `imports`, `re_exports`, `calls`, `inherits`, `references`
(`skills/freya-code-graph/scripts/substrate.py:47`). `provenance` is one of the **two** values
in `PROVENANCE` — `extracted` or `inferred` (`substrate.py:59`). `make_edge` raises on anything
outside either vocabulary (`substrate.py:128`), and `validate_graph` reports an out-of-vocabulary
kind or provenance on the forward edge (`substrate.py:741`, `:744`) and on its mirror in the
reverse index (`:793`, `:796`) — a reverse edge is an edge, held to the same vocabulary. An edge
may also carry the optional symbol refinement, which ADR-024 governs; the file anchor is never
replaced by it.

The change bumped the artifact's schema from 1 to 2 (`substrate.py:75`). Readers accept both
shapes: every consumer goes through accessors that take a bare string or an object
(`substrate.py:144`, `:156`, `:162`), and `upgrade_edges` rewrites string edges in memory on load
(`substrate.py:211`). An upgraded edge claims `imports` / `extracted`, which is exactly what the
string era could express and the only honest reading of it. `upgrade_edges` deliberately does not
stamp `version` (`substrate.py:231`): that field records what is on disk, and reading is how
staleness is discovered. A version-1 artifact therefore forces a full rebuild inside
`CodeGraph.update`, ahead of the "nothing changed" short-circuit that the steady-state workflow
otherwise takes (`graph_ops.py:2129`).

The node queries stay in paths. `--impact`, `--dependents` and `--dependencies` answer with path
strings, projected off the edge objects by `edge_ends` (`graph_ops.py:2271`, `:2335`). Only
`--query` returns edges, because it is the one query whose question is "tell me about this file"
(`graph_ops.py:2196`).

**Provenance is recorded and read by nothing.** Every edge carries `extracted` or `inferred`
faithfully: the homegrown resolver stamps `extracted` throughout, because it reads import
statements out of source text and does nothing else (`graph_ops.py:1997`, `:2010`), and the
graphify backend maps that backend's own `EXTRACTED`/`INFERRED` tag, defaulting an unrecognised
confidence to `inferred` (`backend_graphify.py:144`, `:670`, `:699`). Past that, no production
code consults the field. `edge_provenance` has exactly one caller, and it is the reverse-index
builder copying the value onto the mirrored edge (`substrate.py:362`). The design — stated in the
spec, in the working decision record and on the explainer pages — was that only `extracted` edges
may gate `wrap-up` and `inferred` ones are advisory. No code implements that filter, so an
inferred edge reaches blast radius indistinguishable from an extracted one. **The tier is
designed and unenforced**, and the skill documentation says so out loud
(`skills/freya-code-graph/SKILL.md:635`). Writing the filter, or striking the promise, is
open defect 13 in `knowledge-base/roadmap.md` (§ *Per-edge provenance is recorded and
enforced by nothing*).

`unresolved` is not a provenance value and never was. "Could not be resolved" is a fact about
where an edge points, not about how it was read, so it is a prefix on the target —
`unresolved:<raw specifier>`, alongside `external:` (`substrate.py:71`). The edge is kept and
visible rather than dropped, which is ADR-005's rule applied at edge granularity.

## Rationale

A string can carry exactly one fact: where the edge points. `import { x } from './y'` and
`export * from './y'` were the same value, so a barrel that only forwards a module was
indistinguishable from a module that uses it, and a symbol-level relation could not be written
down at all. Measured during the Phase 0 substrate spike on a 292-file TypeScript testbed
(2026-08-19): graphify produced 5,027 links, of which the contract's five relation kinds matched
2,102 by name — 1,137 `imports`, 822 `calls`, 133 `references`, 10 `extends` — leaving 58% with
no expressible form. Those were not extra detail about edges we already had; they were edges with
nowhere to go. (The projection that eventually shipped maps more of graphify's relation names
than that naive count did — ADR-023 — but the structural relations it drops still cannot become
file-to-file edges under any mapping.)

The migration was done at the cheapest moment it would ever be available. When the question was
put there was one producer and one consumer; every phase after it adds readers, and deferring
would have meant a Phase 2 that promised per-edge provenance and could not deliver it, because
validation required each specifier to be a string.

Provenance was adopted rather than invented. freya already had the enforcement shape in ADR-009 —
deterministic checks block, model judgment is resolve-to-proceed — and graphify already tagged
its links `EXTRACTED` or `INFERRED`, so the mapping looked free. Two measurements have since made
the tier narrower than the original reasoning assumed, and both must travel with this record.
First, the axis is not deterministic-versus-model-judged: Phase 0 ran every build with no API key
and still produced `INFERRED` links, which are type resolution — a call whose receiver type had
to be inferred from a declaration. Second, at Phase 0 the split bought nothing at the granularity
the contract uses: zero file-level edges anywhere rested solely on an `INFERRED` link, on all
three test repositories. That became non-zero only once symbol-level relations were projected
onto file pairs; re-derived on 2026-08-21 against this repository's own graphify graph, 12 of 120
file-level edges are `inferred` and one file pair exists only because of them. The figure moves
with the source — it was two pairs when the tier was written — so it is worth re-deriving rather
than citing.

Sharper still: the one genuine cross-language mis-wiring this feature actually found would not
have been caught by the filter. graphify emits one node per external module, and that node's
`source_file` is whichever importer it parsed first, so Swift files that each `import Foundation`
produced edges between *each other* — edges that exist nowhere in the source, in the direction
that inflates blast radius (`backend_graphify.py:157`). Those links carry `EXTRACTED` confidence —
checked directly in the recorded extraction the regression test replays,
`skills/freya-code-graph/scripts/testdata/gate91.json`. They were fixed structurally, by treating an aggregate
anchor as an `external:` signal, not by any trust tier. So recording provenance is worth doing —
it is cheap, lossless, and it is the only place the distinction could ever be reconstructed from —
but treating it as a live safety mechanism is not warranted by anything measured so far. That is
why this record states the field's real status instead of its intended one.

Two boundaries were drawn at the same time and are load-bearing. Node queries answer in paths
because their callers do set arithmetic on the answer: `set(data["all_affected"]) | set(changed)`
in spec-manager's drift check (`drift.py:95`) and `paths & impact` in the behavior graph
(`behavior_graph.py:267`). An edge object there raises `TypeError: unhashable type: 'dict'` in a
skill that gains nothing from the extra fields; the third consumer, behavior-runner, instead
rejects any `--dependencies` answer that is not a list of strings and degrades that behaviour to
coverage-unknown (`run_behaviors.py:353`). All three needed no change at all. The readers that
open `graph.json` directly did, and `project_shape.py:56` now reads both shapes because
misreading a version-1 artifact would report a wired codebase as greenfield.

And readers stay tolerant of the old shape permanently, until the version says otherwise.
`graph.json` is gitignored, so there is no committed copy to correct in a commit — an older
artifact sits on a machine until something rewrites it, and refusing to read it is
indistinguishable from a project with no dependencies, which is precisely the confidently-empty
answer ADR-005 exists to prevent. The version bump is what makes that tolerance removable later
rather than load-bearing forever.

## Rejected Alternatives

- **Stay file-level, honestly: keep bare strings, drop the three symbol kinds, and strike
  provenance.** The cheapest option, and it has a real argument behind it — the design's
  deliberate floor is file-level, and every consumer today asks a file-level question. It buys
  zero migration and zero new failure modes. Rejected because it discards most of what a
  symbol-aware backend already computed, for free, and only defers a migration whose cost rises
  with every reader added. It also cannot express `re_exports`, so a barrel file and a consumer
  of a module stay the same edge.

- **Defer the edge change until symbols land.** This is what the plan of record said, and it has
  the merit of doing one schema change instead of two. Rejected because the intervening phase had
  already promised per-edge provenance and could not deliver it against a shape whose specifiers
  had to be strings — the contract would have reopened anyway, later, with more readers attached.

- **Keep strings and add a parallel `edges` key alongside them.** Zero downstream risk: every
  existing reader keeps working untouched, and new readers get the rich shape. Rejected because
  it stores one fact twice and the two copies drift. This repository has been bitten by exactly
  that failure before, with a byte-identical constant maintained in two skills.

- **Return edge objects from `--impact`, `--dependents` and `--dependencies` too.** Consistency,
  and it would let a caller filter blast radius by kind — "which files depend on this, ignoring
  barrels" — without a second query. Rejected because those three queries answer "which files",
  their callers hash or type-check the answer the moment they get it, and none of them has yet
  wanted a kind. The richer answer is available from `--query` for anyone who does, and a
  kind-filtered blast radius should arrive as a new flag rather than as a change to what the
  existing three return.

- **Refuse to read a version-1 artifact, or stamp it current on read.** Refusing is the clean
  contract position: a reader that cannot honour the schema should say so rather than guess.
  Stamping is the tidy one: upgrade in memory, mark it done, never look again. Both were rejected
  for the same reason. Refusing turns a stale local cache into a silent "this project has no
  dependencies". Stamping is worse: a graph old enough to be version 1 may predate the
  `substrate` metadata block entirely, and that block cannot be reconstructed from the artifact —
  only a real build knows which backend ran and what it can see. Stamping the version would have
  frozen the graph permanently claiming no backend and no coverage. A rebuild, not a rewrite,
  is what ships (`graph_ops.py:2129`), and the persistence path refuses to rewrite a stale
  artifact a backend wrongly reported as up to date, saying so on stderr instead
  (`graph_ops.py:2467`).

- **Discard inferred edges entirely and run the second backend in its most conservative mode.**
  This was the first recommendation when the trust question was raised, and it would have removed
  the whole problem: nothing to filter, because nothing uncertain is in the graph. Rejected
  because the objection was that inferred edges should not *block*, which argues for labelling
  them, not for throwing them away. Worth being exact about the price, since it is smaller than
  the original argument implied: at Phase 0 discarding would have cost nothing at file
  granularity, because no file-level edge on any of the three test repositories rested solely on
  an inferred link. It costs something now — one file pair on this repository, and 12 of its 120
  file-level edges — all of them calls and references whose receiver the resolver had to work out
  from a declared type rather than read, which is exactly the speculative-but-plausible relation
  the label exists to mark.

- **Record no provenance at all and let every edge gate equally.** Simpler artifact, simpler
  validator, and the honest observation that over-approximating a blast radius is the safe
  direction anyway. Rejected because the field is the only place the distinction could ever be
  recovered from — a backend's confidence tag is not recomputable from the artifact once
  dropped — and because a gate people learn to ignore provides no protection at all. Note,
  though, that this alternative and what actually ships are behaviourally identical today; the
  difference is that the shipped artifact keeps the evidence needed to decide between them.

## Revisit Conditions

- **The provenance filter gets written, or the promise gets struck.** This is the open item, not
  a hypothetical: open defect 13 in `knowledge-base/roadmap.md`. Deciding it needs a measured
  mis-wiring rate on a real
  polyglot repository, not an argument. The concrete trigger is the first project where an
  inferred edge widens a blast radius enough that `wrap-up`'s affected-behaviour re-run
  (`skills/freya-wrap-up/SKILL.md:168`) blocks on a behaviour the change did not touch. If the
  filter is written, it belongs where blast radius is *consumed* — `behavior_graph.py:243`,
  `drift.py:76` — not in the graph, which must go on recording every edge it can see.

- **A backend arrives whose relations do not fit the five kinds.** `RELATION_KINDS` is fixed
  deliberately so a caller can ask "does this backend give me calls?" portably, and unmappable
  relations are currently counted and reported rather than guessed at (ADR-023). If the reported
  unmapped set on a real repository is dominated by one recurring relation with genuine
  file-to-file meaning, the vocabulary should grow — and that is a schema 3 change, not a quiet
  addition.

- **Schema 3, whenever it comes.** That is the moment to decide whether the version-1 tolerance
  can be dropped. It is retained today only because an un-rebuilt artifact may still be on a
  disk somewhere; once every reachable installation has been through at least one version-2
  build, `upgrade_edges` and the string branches in the accessors are removable. The version
  field exists precisely so that this can be decided on evidence rather than guessed.

- **`graph.json` stops being gitignored.** The permanent read-side tolerance rests on the
  artifact being local and uncommittable-to-correct (ADR-017 draws the same line for
  `behavior.json`). If the graph ever becomes a committed artifact, an old shape can be fixed in
  a commit and the tolerance argument collapses.
