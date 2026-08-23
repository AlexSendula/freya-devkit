---
id: ADR-026
title: The docs graph anchors at section, and markdown splits only at headings
status: accepted
created: 2026-08-21
updated: 2026-08-21
tags:
  - artifacts
  - code-graph
  - knowledge-base
  - parsing
---
# ADR-026: The docs graph anchors at section, and markdown splits only at headings

## Decision

A third artifact, `knowledge-base/.graph/docs.json`, records which documentation
**section** cites which code **file**. The source anchor is a heading slug —
`knowledge-base/reference/ARCHITECTURE.md#output-artifacts` (`docs_graph.py:411`) — not a line. The
target is a plain repository-relative file path. The cited line rides *inside*
the edge as evidence and comes back out as `lines_cited` on a query
(`docs_graph.py:414`), but it is never the anchor.

Edges come from three deterministic readers of text that is already written:
`path:line` tokens in prose, relative markdown links whose target has a code
extension, and the `related_code:` frontmatter every spec and ADR already
carries. `related_code` describes the document rather than one section of it, so
it attaches to the first real section instead of being copied across all of them
(`docs_graph.py:369-375`). Only a path naming a file the code graph actually
knows becomes an edge (`docs_graph.py:229`); with no code graph present every
citation is discarded and `code_graph_present: false` says so, on stderr as well
(`docs_graph.py:392`, `:454-456`). The reverse query — *"I changed
`graph_ops.py`, which docs now lie?"* — is `freya docs-graph --impact <file>`,
implemented at `docs_graph.py:402` and wired into the launcher at
`bin/commands.json:7`. `docs-manager`'s update workflow calls it instead of
judging correspondence (`skills/freya-docs-manager/SKILL.md:441`); the caller is
an agent following that instruction, not code.

Sectioning splits **only** at heading boundaries, and a heading is recognised
only outside a fenced block. Fences are matched by character *and* length, so
` ```` ` can contain ` ``` ` verbatim (`docs_graph.py:110-121`). An unterminated
fence produces a `warnings` entry saying the document may be under-sectioned
rather than silently swallowing every later heading (`docs_graph.py:137-142`).
The output is a partition: concatenating every section's `raw` reproduces the
body byte for byte (`docs_graph.py:97`, pinned at `test_docs_graph.py:107`).

`docs.json` is git-ignored, which is the opposite of the call ADR-017 made for
`behavior.json`, and for the reason stated in the ignore file itself: it is
parsed from markdown that is already committed, so it is regenerable in the same
sense the code graph is (`graph_ops.py:247`, `:258-259`).

Two things the approved design promised that the shipped code does not do are
recorded here rather than left to be rediscovered. **No docs edge carries a
symbol.** The design said the target would be refined with a symbol wherever a
citation carried a line; every edge in fact has exactly `target`, `line`, `via`
and `provenance` (`docs_graph.py:366-368`, `:374-375`), and neither persisted
graph holds a symbol range for a line to be mapped onto — ADR-023 projects
graphify's symbol graph down onto file pairs and keeps nothing per-symbol. Docs
edges are therefore file-level under *both* backends, not only on the floor as
the spec claimed. This is ADR-024's rule at its floor: the file anchor is all
there is, and it is still a usable answer. **The semantic markdown pass is not
wired in.** It was to contribute `inferred` edges when enabled; `provenance` is
the string literal `'extracted'` at both places an edge is constructed, so
nothing in this artifact is model-judged and no `inferred` edge can reach it.

## Rationale

The doc-to-code edge already existed conceptually and was being re-derived by
model judgment on every run. `docs-manager` decided staleness by taking a git
diff, asking code-graph for the impact, and then having the agent decide which
documents corresponded to the affected files. Nothing recorded that
`architecture.md` documents those files, so the answer was inconsistent between
runs and unverifiable after them.

The reverse question had no answer at all, and that is not hypothetical. Changing
how `knowledge-base/.graph/.gitignore` is written falsified prose in both
`knowledge-base/reference/ARCHITECTURE.md` and `knowledge-base/reference/SKILL_REFERENCE.md`; both cited one exact line
of `skills/freya-code-graph/scripts/graph_ops.py` — a line number that has since
moved — in prose no tool read, and both were found by grep. Today the same
question is a lookup: `freya docs-graph --impact` on that file returns
`knowledge-base/reference/ARCHITECTURE.md#output-artifacts` — the exact section that change
invalidated — alongside every other section that cites it.

Anchoring at the section rather than the line follows from what breaks and what
gets asked. A line number shifts the moment anyone inserts a paragraph above it,
so a line-anchored graph invalidates itself on edits that changed nothing
relevant; a heading survives. And the question anyone actually asks is *which
section is now wrong*, because a section is the unit a person rewrites. The
precision is not thrown away — it is demoted from anchor to evidence.

One measurement changed the design: prose cites bare filenames far more often
than paths. Re-derived on this repository on 2026-08-21 at commit `2762d54`, 242
of 324 resolved citation occurrences — 75% — are bare names like `graph_ops.py`
rather than `skills/freya-code-graph/scripts/graph_ops.py`. Refusing them would
have discarded three-quarters of the graph. So a bare name is resolved, but only
when it is unambiguous: the citing document's own directory is tried first, then
the basename index, and a name matching two files goes into
`ambiguous_citations` rather than being guessed (`docs_graph.py:251-264`,
`:395-398`). Zero were ambiguous here. The same restraint governs the whole
parser — a wrong edge sends someone to rewrite a document that was fine, which
is worse than no edge.

The chunking rule exists because splitting inside a fenced block produces
content that is not merely truncated but actively wrong: half a mermaid diagram,
half an ASCII tree. `knowledge-base/reference/ARCHITECTURE.md` carries directory trees inside fences
and the explainer site carries mermaid, so any size-based splitter would have
been hit on the first run. A `# comment` inside a ` ```bash ` block is
indistinguishable from an H1 by pattern alone. The precedent is exact rather
than analogous: `_strip_jsonc` (`graph_ops.py:604`) had to be made string-aware
because a naive regex read the `/*` inside the alias string `"@/*"` as a comment
opener and broke tsconfig alias resolution (`test_graph_ops.py:76`).
Structure-unaware text processing is one bug class, and it was caught by a
regression test before shipping rather than in the field. Six of the chunker's
tests are about fences alone.

The atomicity guarantee is narrower than the design stated it, and the narrow
version is the true one. The only block the chunker tracks is the fence. Tables
and HTML blocks survive because the sole split point is a heading line and
neither normally contains one — a consequence, not a mechanism. It can be
defeated: a table row followed immediately by `---` is read as a setext H2 and
splits the table, and an HTML block containing a line beginning with `#` splits
at that line. Neither occurred in any of this repository's markdown when this was
checked on 2026-08-21, and no test covers either. Read the guarantee as *never
split a fence*, and the rest as a property that holds in practice.

For scale, measured on the working tree of 2026-08-21 at commit `2762d54`: 40
documents, 469 sections, 306 edges, of which 203 carry a cited line. Treat that
as a snapshot, not a property — the count tracks how much documentation exists
and moves whenever a document is added. An earlier figure of "35 documents, 171
edges" was repeated in several places and does not reproduce; the shape of the
result is the durable part, never the total.

## Rejected Alternatives

- **Keep re-deriving staleness on every run.** The status quo and the default if
  nobody looked: zero implementation, no new artifact, and immunity from a docs
  graph itself going stale. It also has the agent's full reading comprehension
  available, where the parser has only citations. Rejected because the judgment
  is unverifiable after the fact, inconsistent between runs, and — the deciding
  point — structurally incapable of answering the reverse query, since it starts
  from a document and asks about code, never the other way.

- **Anchor the source side at `path:line`.** Sharpest possible blame: not "this
  section may be wrong" but "the claim on this exact line is wrong", diffable
  against the citation it came from. Rejected because it is brittle to any edit
  above the citation, so inserting a paragraph invalidates edges that are still
  perfectly correct, and because it answers a question nobody asks — nobody
  rewrites a line. The precision is retained inside the edge, so nothing was
  actually lost.

- **Anchor at the document instead of the section.** Cheaper than either, and
  immune to heading renames, which section anchors are not. Rejected on
  granularity: on this repository 306 edges spread across 469 sections, and
  `knowledge-base/reference/ARCHITECTURE.md` alone carries 27 of them. A document-level answer says
  "something in architecture.md may be wrong", which is what grep already said,
  and grep is what this artifact exists to replace.

- **Make graphify's semantic markdown pass the primary edge source.** It would
  have found the relationships nobody wrote down — the documents that describe
  code without ever citing it, which the deterministic readers are blind to by
  construction. Rejected as primary because it is `inferred`, needs a model, and
  costs a run of it per build, while our own citations are deterministic and
  already sitting in the files. It was kept in the design as an opt-in
  supplement; as of this record it was never built, so every edge is `extracted`.

- **Resolve every path-shaped token, not only those the code graph knows.**
  Would have bought edges into files the graph excludes — configuration,
  generated output, files in another repository — and a larger graph on day one.
  Rejected because prose is full of path-shaped strings that are not references
  to this repository, and checking a candidate against the graph's file set is
  the only thing keeping the parser honest. The narrow regex and the URL and
  timestamp rejections (`docs_graph.py:196-199`, `:246-248`) exist for the same
  reason.

- **Chunk by line count or token budget.** The standard move in a RAG pipeline,
  trivial to implement, and it produces uniform chunks, which is exactly what an
  embedding index wants. Rejected because it is guaranteed to cut a diagram in
  half on this repository's own documents, and because chunk size is not a unit
  anyone queries — there is no useful sentence beginning "lines 400 to 600 of
  architecture.md are now wrong".

- **Chunk by paragraph.** Finer granularity, so an edge would point nearer the
  claim it supports. Rejected because a paragraph has no stable name to anchor
  on — a heading has a slug, a paragraph has only an ordinal that changes with
  every edit — and because it multiplies edges without changing the answer
  anyone acts on, which is still "reread this section".

- **Commit `docs.json` the way ADR-017 commits `behavior.json`.** Would let a
  reviewer see doc coverage change inside a pull request, and give a fresh clone
  the reverse query without a build. Rejected because the two files are not the
  same kind of artifact: observed coverage can only be recaptured by running a
  green suite, whereas every docs edge is recoverable by re-reading committed
  markdown against the code graph. That makes it a cache in exactly ADR-017's
  sense, and a cache that changes on every documentation commit — which is most
  of them.

## Revisit Conditions

- **An adopting project's documentation cites no code at all.** Then all three
  deterministic readers yield nothing and `docs.json` is a list of documents with
  zero edges, at which point the unbuilt semantic pass is the only way to have a
  docs graph — its design, and why it is not a record, is in
  [`../roadmap.md`](../roadmap.md) under *Deferred capabilities*. This repository is unusually citation-heavy because its own
  conventions demand `path:line` provenance; that is not evidence about anyone
  else. Check it on the first adopter whose docs were not written under that
  habit.

- **A persisted graph starts carrying symbol ranges.** The docs edge is
  file-level because no artifact holds a line-to-symbol map for it to consult,
  not because file-level was preferred. Every edge already stores the cited
  `line`, so the day such a map lands in `graph.json`, refining the target under
  ADR-024 becomes a small change and the design's original promise becomes
  buildable. Until then, do not describe docs edges as symbol-capable.

- **A real document is split mid-table or mid-HTML-block.** The atomicity
  guarantee is enforced for fences only. The first time a table followed
  immediately by `---`, or an HTML block containing a `#` line, produces a
  nonsense section title, add explicit block tracking — and a test, because none
  covers it today.

- **`ambiguous_citations` stops being empty.** Zero bare names were ambiguous
  here. A project with `index.ts` in twenty directories inverts that: most
  citations become unresolvable and the graph is mostly gaps. The obvious
  fallback is already in place — the citing document's own directory is tried
  before the basename index (`docs_graph.py:251-253`) — so a fix would need a
  real tie-break, such as nearest-in-graph, or a convention that writers qualify
  the path.

- **A single section grows large enough that one anchor is a useless answer.**
  The largest section in this repository on 2026-08-21 is 89 lines, so the
  question is not live. A 2,000-line section with one anchor would make
  sub-section splitting on top-level block boundaries worth adding — but measure
  before assuming, and split only between blocks, never inside one.
