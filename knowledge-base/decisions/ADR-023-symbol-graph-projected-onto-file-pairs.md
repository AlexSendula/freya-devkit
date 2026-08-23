---
id: ADR-023
title: graphify's symbol graph is projected onto file pairs, and nothing intra-file becomes an edge
status: accepted
created: 2026-08-21
updated: 2026-08-21
tags:
  - code-graph
  - substrate
  - artifacts
---
# ADR-023: graphify's symbol graph is projected onto file pairs, and nothing intra-file becomes an edge

## Decision

graphify's nodes are *symbols* and its links run symbol → symbol. The substrate contract's
nodes are *files* (ADR-018), and every other artifact in the toolkit joins on a file path
(ADR-025). So the graphify backend projects each link onto the file pair its endpoints live in,
and keeps the result only when two things hold: the link's relation is one the mapping table
names as a dependency, and the two endpoints are in different files.

The mapping table is `RELATIONS` in
[`backend_graphify.py:93`](../../skills/freya-code-graph/scripts/backend_graphify.py). It has
32 rows. Twenty-three name one of the contract's five kinds — which is all five, so graphify
declares `imports`, `re_exports`, `calls`, `inherits` and `references` where the homegrown floor
declares only the first two. Nine name `None`. Those nine are listed rather than omitted,
because being *in* the table is what stops them being reported as unknown on every build.

There is no default row. A relation the table does not name produces no edge, is counted into
`substrate.unmapped_relations` in the written artifact, and is announced on stderr
(`backend_graphify.py:510`, `:536`) — the same "say what you could not read" obligation
ADR-029 states for the answer as a whole. On this repository the report is empty, and it is
meant to be: it is a tripwire for a capability arriving upstream, not a running tally of loss.

The intra-file rule is the second filter, and it applies to links whose relation survived the
first. A link whose two endpoints share a file is dropped in the projection
(`backend_graphify.py:676`). The contract then refuses the same thing twice more, independently:
`link_dependents` skips a self-target rather than writing it into the reverse index
(`substrate.py:350`), and `validate_graph` reports it as a contract error
(`substrate.py:781`). None of the three rejects the artifact — validation records its errors
under `substrate.validation` and the graph is written anyway (`graph_ops.py:2578`) — so the
guarantee is that a self-edge cannot reach a *caller*, not that it cannot be produced.

Three shapes need naming because they are not what they look like:

A node typed `module` or `namespace` is an aggregate anchor, not a file. graphify emits one node
per external module and one per C# namespace, shared across every file that mentions it, and
that node still carries a `source_file` — whichever file was parsed first. `ANCHOR_NODE_TYPES`
(`backend_graphify.py:178`) turns both into `external:<label>` at index time
(`:600`), which is what the contract already had for "a real dependency that is not a file of
ours". A `package` node deliberately stays a file: its `source_file` is the manifest it was
parsed from, which is a real path.

`method` links are dropped as edges and kept as a lookup. `_method_owners`
(`backend_graphify.py:622`) walks them to qualify a bare method label into `Class.method()`,
which is what makes ADR-024's symbol refinement name a symbol rather than merely describe one.

Exclusions are honoured as a post-filter on graphify's output (`backend_graphify.py:615`),
because `graphify update` accepts only `--force` and `--no-cluster` — there is no exclusion
flag to pass. That is a property of the tool, verified against its own `--help` at 0.9.47, not
a preference.

## Rationale

The table is derived from counting what each relation actually connects, not from reading its
name, and the counts are what decided the nine `None` rows.

Measured on this repository at commit `0f86434` with graphify 0.9.47, under the project's own
exclusions: graphify emits **7,497 links**. **4,193 of them — 56% — carry a relation the table
drops**, and on this repository those are three relations: `contains` (1,528), `method` (1,713)
and `rationale_for` (952). Every one of the 4,193 is intra-file, and that is the argument by
itself — a relation that never crosses a file boundary cannot produce a file → file edge under
any mapping, only a self-edge. The three are structural or indexical rather than dependencies:
`contains` is the node hierarchy, and 774 of its links are not even code-to-code but markdown
section nesting; `method` is class-has-method, all 1,713 in `.py` files; `rationale_for` runs
from a `rationale` node to a `code` node 952 times out of 952, all intra-file, all `.py`, with
the source node's label being the first line of a docstring. That the three account for the
whole drop is a fact about *this* repository's language mix, not about the table — the other
six `None` rows are for relations a Python and TypeScript corpus never produces.

graphify agrees, independently. Its own `DEFAULT_AFFECTED_RELATIONS` (`affected.py:12` in the
installed package) is the vocabulary its blast-radius traversal walks; all fourteen entries are
mapped to a kind here, and the same tuple omits `contains` and `method`.

The remaining **3,304 links carry a mapped relation**. 271 of those have an endpoint that is not
an in-scope code node — a `document` or `rationale` node, or a file the project excluded — and
of the **3,033 that remain, 2,314 (76%) are intra-file**. They go for the reason the contract
now checks for twice: blast radius walks `dependents`, so one self-edge puts a file in its own
blast radius and `--impact` reports it as directly affected by itself. The **719 cross-file
links** that survive project onto **78 distinct file pairs**, written as **120 file-level edges
over 65 files**.

That 78 is the number the adoption gate turns on. Spec §9.1 blocks the second substrate if it
loses an edge the floor finds, because a lost edge silently narrows a behaviour's blast radius
and a regression walks through wrap-up unflagged. At the same commit the homegrown resolver
finds **72** internal pairs, and exactly one of them is missing from graphify's 78:
`bin/installer.py → bin/freya_cli.py`. That one is homegrown's own false positive — the text
`"from freya_cli import main\n"` at [`bin/installer.py:566`](../../bin/installer.py) is a
string literal that installer.py writes into a generated shim. Homegrown's regexes read string
bodies (backlog item 10); graphify parses. The gate is pinned against a recorded extraction in
`skills/freya-code-graph/scripts/testdata/gate91.json` so it runs on a machine with no binary,
and pinned on `(from, to, kind)` rather than on pairs alone, because a pair-only assertion
caught one of six deliberate mapping mutations.

The vocabulary cannot be enumerated, which is why there is a report instead of a default.
Grepping graphify's source for `relation = "…"` and `"relation": "…"` yields 26 names — all 26
are in the table. It misses four that `DEFAULT_AFFECTED_RELATIONS` names outright
(`dynamic_import`, `embeds`, `extends`, `requires`), and it misses two more that the table
carries because they were observed rather than found: `reads_from`, which this repository's
graph contains and which upstream emits through a helper call
(`_add_edge(obj_nid, tbl_nid, "reads_from", line)`), and `semantically_similar_to`, which
exists only inside a JSON schema in a prompt string. A static scan of somebody else's registry
finds what the scan's shape allows it to find.

The anchor rule was not a hypothesis. Read as files, module nodes fabricate edges: in the
recorded gate fixture two Swift files each `import Foundation`, the shared `Foundation` node
carries `source_file: src/s2.swift`, and dropping `ANCHOR_NODE_TYPES` turns that into
`src/s1.swift → src/s2.swift` — an edge in neither source file, in the direction that inflates
blast radius. The namespace case is the same shape one language over and was missed the first
time, because the fix enumerated the case it had seen instead of the class it belonged to.
graphify's own resolver treats the two identically for the same reason: `resolution.py:671`
skips both when disambiguating, under a docstring saying they are one module rather than
distinct same-named symbols. Both cases are pinned
([`test_backend_graphify.py:625`](../../skills/freya-code-graph/scripts/test_backend_graphify.py)
and `:635`), as is `package` staying a file (`:662`).

One consequence should be stated plainly rather than celebrated. Phase 0 recorded the two-tier
`extracted`/`inferred` provenance design as unexercised, because no file-level edge rested
solely on an inferred link. That is no longer true — at this commit exactly one of the 78 pairs
does — and that one edge is **wrong**: graphify guesses that `audit_engine.audit()` calling
`Result(...)` reaches `substrate.Result`, when `Result` is a local `namedtuple` at
[`audit_engine.py:36`](../../skills/freya-codebase-security-scan/scripts/audit_engine.py) and
the file never imports `substrate`. The tier is doing exactly what it exists to mark. It is
also read by nothing: provenance is written on every edge and surfaced by `query`, but no
production code branches on it, so this inferred edge reaches blast radius indistinguishable
from an extracted one. That gap belongs to ADR-021 and is tracked as backlog item 13; it is
noted here because this projection is where the inferred edges come from.

## Rejected Alternatives

- **Adopt `rationale_for` as graphify's documentation graph.** It would have bought a docs
  graph for free on every Python repository — doc-to-code links with no extraction pipeline of
  our own — and that is how it was read at first. It is not one. All 952 links run from a
  `rationale` node whose label is the first line of a docstring to a `code` node in the same
  file; the source is not a file and the link never crosses one, so it cannot express a
  relationship between two files no matter how it is projected. The docs graph is built from
  citations we control instead, anchored at section (ADR-026).

- **Default an unlisted relation to `references`.** It would have bought forward compatibility
  for free: a capability added upstream would arrive as edges on the next build with no table
  edit, and `references` is the weakest kind, so the guess would be conservative. It loses
  because it is a silent fallthrough, which is the failure mode Phase 0 recorded against config
  coverage — "nothing, and no warning". An upstream relation that meant something structural
  would arrive as a graph that merely looks thin, and thin-graph-versus-thin-repo is precisely
  the distinction the substrate block exists to preserve.

- **Drop an unlisted relation silently.** The literal default of `RELATIONS.get(relation)`, and
  what the code would do if nobody had thought about it. It would have bought one less field in
  the artifact and one less line on stderr. It loses for the same reason as the previous
  option, minus even the edges: the loss would be invisible at exactly the moment it is
  interesting, which is the build after graphify learns something new.

- **Map only the fourteen relations in graphify's `DEFAULT_AFFECTED_RELATIONS`.** It would have
  bought a single upstream-owned source of truth and no judgment calls of ours: graphify already
  decides which relations are dependencies, so mirror that tuple and stop. It loses because
  that tuple says nothing about the relations that are *not* dependencies. `contains`, `method`
  and `rationale_for` would fall through to the unmapped report on every single build — 4,193
  links of noise here — and a report that always fires is not a signal. The nine explicit
  `None` rows are what keep the report meaningful.

- **Keep intra-file links as self-edges.** It would have bought the intra-file call graph for
  free, inside the artifact the toolkit already has: 2,314 links on this repository, which is
  76% of everything with a mapped relation and two in-scope endpoints, describing which
  functions in a file call which. Verified against what it costs: one self-edge makes
  `--impact` report a file as its own direct dependent, and every traversal walks that. The
  information is discarded rather than dismissed — recording it needs a node type below the
  file, which the contract does not have.

- **Read a `module` or `namespace` node as the file its `source_file` names.** It would have
  bought one code path with no special cases: every node in graphify's graph carries a
  `source_file`, so treat them all alike. It fabricates edges instead, silently and in the
  worst direction — N files importing one module become N−1 edges into whichever file was
  parsed first, inflating that file's blast radius with files that have never heard of it.

- **Treat `package` nodes as anchors too, for symmetry.** It would have bought one rule for
  every aggregate node type instead of an enumerated pair, which is the shape of the mistake
  that made `namespace` a second fix rather than part of the first. It loses on the facts: a
  package node's `source_file` is the manifest it was parsed from, a real path, and graphify
  prunes dependency edges whose target manifest is outside the corpus — so
  `packages/a/package.json → packages/b/package.json` is a true statement about two files that
  exist, and turning it into `external:@x/b` would throw a real edge away.

- **Change the contract's node type to a symbol instead of projecting.** It would have bought
  graphify's graph at full resolution, with no projection code and nothing discarded. It is
  rejected in ADR-024 and ADR-025 rather than here: symbols refine a file anchor and never
  replace it, because every other artifact in the toolkit — docs, behaviours, security findings
  — joins on a file path, and a symbol-keyed graph would break all three joins at once.

## Revisit Conditions

- **`substrate.unmapped_relations` appears in a built artifact.** It is absent on every
  repository the gate runs against today. The first time it fires, the new row must be judged
  the way the existing ones were — by counting what the relation actually connects and how
  often it crosses a file boundary — and not by what its name suggests. A relation whose links
  turn out to be 100% intra-file gets a `None` row, not a kind.

- **`contains`, `method` or `rationale_for` is measured crossing a file boundary anywhere.**
  The drop rests entirely on those three being intra-file in every sample taken, and the sample
  is Python-heavy: `method` and `rationale_for` are `.py`-only here. A language whose extractor
  emits `method` across files — or an upstream change that links a docstring node to code
  elsewhere — makes the drop lossy for that repository, and the census has to be re-run per
  language rather than assumed from this one.

- **The contract gains a node type below the file.** Then the intra-file call graph stops being
  unrepresentable, the self-edge rule stops being the end of the story, and this projection
  should record what it currently discards. That capability is not in `knowledge-base/roadmap.md`; it
  lives only in this record, which is the reason it is stated here.

- **graphify stops canonicalising module and namespace nodes.** If a future version emits one
  node per importing file rather than one shared node, `ANCHOR_NODE_TYPES` inverts from a
  correction into a loss: real file → file edges would be flattened into `external:` signals.
  The check is cheap — count distinct node ids per module label in `graphify-out/graph.json`.

- **`graphify update` grows an exclusion flag.** Applying exclusions on the way in rather than
  as a post-filter would cut extraction cost on a repository with a large vendored tree, which
  is currently parsed in full and then discarded. Verified absent at 0.9.47; re-check on a
  major version bump.
