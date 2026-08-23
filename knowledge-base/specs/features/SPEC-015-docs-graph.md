---
id: SPEC-015
title: The Docs Graph — Which Documentation Section Cites Which Code
category: features
tags: [docs-manager, docs-graph, artifacts, impact-analysis, parsing]
status: implemented
certainty: 82
created: 2026-08-21
updated: 2026-08-21
related_code:
  - skills/freya-docs-manager/scripts/docs_graph.py
  - skills/freya-docs-manager/scripts/test_docs_graph.py
  - skills/freya-code-graph/scripts/graph_ops.py
intentional_decisions:
  - "Every edge is parsed from committed text; provenance is always 'extracted' and nothing is model-inferred"
  - "With no code graph present, every citation is discarded and the artifact records code_graph_present: false rather than resolving paths it cannot check"
  - "Edges anchor at a heading slug, never at a line; the cited line is kept inside the edge as evidence (ADR-026)"
  - "A bare filename is resolved only when it is unambiguous; an ambiguous one is reported, not guessed"
  - "docs.json is git-ignored because it is re-derivable from committed markdown (ADR-026)"
behaviors:
  - behavior_id: BEH-069
    title: A heading-shaped line inside a fenced block does not start a new section
    state: proposed
    level: unit
    adapter: unittest
    locator: skills/freya-docs-manager/scripts/test_docs_graph.py#ChunkingTest.test_a_hash_inside_a_fence_is_not_a_heading
  - behavior_id: BEH-070
    title: Sectioning a document loses nothing — rejoining every section reproduces the input byte for byte
    state: proposed
    level: unit
    adapter: unittest
    locator: skills/freya-docs-manager/scripts/test_docs_graph.py#ChunkingTest.test_no_content_is_lost
  - behavior_id: BEH-071
    title: A path naming a file the code graph does not know never becomes an edge
    state: proposed
    level: unit
    adapter: unittest
    locator: skills/freya-docs-manager/scripts/test_docs_graph.py#CitationTest.test_a_file_not_in_the_graph_is_not_an_edge
  - behavior_id: BEH-072
    title: A bare filename matching two files is reported as ambiguous rather than resolved to one of them
    state: proposed
    level: unit
    adapter: unittest
    locator: skills/freya-docs-manager/scripts/test_docs_graph.py#BareFilenameTest.test_ambiguity_is_reported_rather_than_silently_dropped
  - behavior_id: BEH-073
    title: A document's related_code frontmatter becomes edges alongside the citations in its prose
    state: proposed
    level: unit
    adapter: unittest
    locator: skills/freya-docs-manager/scripts/test_docs_graph.py#RelatedCodeTest.test_related_code_frontmatter_becomes_edges
  - behavior_id: BEH-074
    title: Asking which docs cite a changed file returns section anchors, with the cited lines as evidence
    state: proposed
    level: unit
    adapter: unittest
    locator: skills/freya-docs-manager/scripts/test_docs_graph.py#BuildTest.test_impact_answers_which_sections_a_file_appears_in
  - behavior_id: BEH-075
    title: With no code graph present the build produces zero edges and says so, instead of resolving paths it cannot check
    state: proposed
    level: unit
    adapter: manual
    locator: skills/freya-docs-manager/scripts/test_docs_graph.py#CodeGraphAbsentTest.test_no_code_graph_discards_every_citation_and_says_so
---

# The Docs Graph — Which Documentation Section Cites Which Code

## What

`freya docs-graph --build` parses every markdown file under `docs/` and `knowledge-base/` into
`knowledge-base/.graph/docs.json`: for each document, its heading-delimited sections, and for
each section the code files it cites. Three readers produce edges — `path:line` tokens in
prose, relative markdown links whose target has a code extension, and the `related_code:`
frontmatter every spec and ADR already carries. A citation only becomes an edge if it names a
file the code graph knows about.

`freya docs-graph --impact <file>` answers the reverse question — *"I changed this file, which
documentation now lies?"* — from the stored artifact, returning `document.md#section-slug`
anchors with the lines each section cited. Run before a build, it says there is no artifact and
exits non-zero rather than returning an empty answer.

Two invariants govern the parse. The document is split **only** at headings, and a heading is
only recognised outside a fenced block, so a `#` comment in a shell example and a mermaid
diagram survive whole; and sectioning is a partition — concatenating every section's raw text
reproduces the document exactly. Malformed input (an unterminated fence) produces a warning on
the document rather than silently swallowing every heading after it.

The artifact is one of the three the toolkit maintains, each with a single owner, joined on the
repository-relative file path — see
[ADR-025](../../decisions/ADR-025-three-artifacts-joined-on-file-path.md). Nothing in the
toolkit reads `docs.json` programmatically today; its consumer is `docs-manager`'s update
workflow, where an agent chains `--impact` after a code-graph blast radius
(`skills/freya-docs-manager/SKILL.md:441`).

## Why

Documentation staleness used to be decided by an agent judging which documents corresponded to
a set of changed files. Nothing recorded that a given document describes a given file, so that
judgement was re-made on every run, differed between runs, and could not be checked afterwards.
The reverse question had no answer at all — and on this repository that was not hypothetical:
changing how one cache file is written falsified prose in two reference documents, both of
which cited an exact source line in text no tool read, and both were found by grep.

Recording the edges instead of re-deriving them turns that into a lookup. The design
constraint throughout is that a wrong edge is worse than a missing one, because it sends
someone to rewrite a document that was fine — which is why every reader is a parser over text
that is already committed, and why anything the parser cannot place is dropped or named rather
than guessed. The rationale for anchoring at the section, and for each rejected alternative, is
in [ADR-026](../../decisions/ADR-026-the-docs-graph-anchored-at-section.md).

## Behavior

| Behavior | State | Verified by |
|----------|-------|-------------|
| BEH-069 A `#` inside a fence is not a heading | proposed | `test_docs_graph.py#ChunkingTest.test_a_hash_inside_a_fence_is_not_a_heading` (unittest) |
| BEH-070 Sectioning is a partition, not a filter | proposed | `test_docs_graph.py#ChunkingTest.test_no_content_is_lost` (unittest) |
| BEH-071 Only a file the code graph knows becomes an edge | proposed | `test_docs_graph.py#CitationTest.test_a_file_not_in_the_graph_is_not_an_edge` (unittest) |
| BEH-072 An ambiguous bare filename is reported, not guessed | proposed | `test_docs_graph.py#BareFilenameTest.test_ambiguity_is_reported_rather_than_silently_dropped` (unittest) |
| BEH-073 `related_code:` frontmatter becomes edges | proposed | `test_docs_graph.py#RelatedCodeTest.test_related_code_frontmatter_becomes_edges` (unittest) |
| BEH-074 `--impact` returns section anchors with cited lines | proposed | `test_docs_graph.py#BuildTest.test_impact_answers_which_sections_a_file_appears_in` (unittest) |
| BEH-075 No code graph → zero edges, and the artifact says so | proposed | **no test** — every existing test injects `code_files` directly (manual) |

Neighbouring scenarios folded into the behaviors above rather than listed separately: tilde and
nested fences (`ChunkingTest.test_tilde_fences_are_handled`,
`.test_a_longer_fence_is_not_closed_by_a_shorter_one`), the unterminated-fence warning
(`.test_an_unclosed_fence_does_not_swallow_the_rest_silently`,
`BuildTest.test_a_document_that_cannot_be_parsed_is_reported_not_skipped`), GitHub-style unique
slugs (`.test_slugs_are_github_style_and_unique`), URLs and clock times not being citations
(`CitationTest.test_a_url_with_a_port_is_not_a_citation`, `.test_a_time_is_not_a_citation`),
unambiguous bare-name resolution (`BareFilenameTest.test_an_unambiguous_bare_filename_resolves`),
the section-not-line anchor (`BuildTest.test_the_anchor_is_the_section_not_the_line`), an
uncited file returning an empty answer rather than an error
(`.test_impact_on_an_uncited_file_is_empty_not_an_error`), and determinism
(`.test_output_is_deterministic`).

Two surfaces have **no** coverage and are the honest gaps in this area: the CLI in `main()` —
including the "no docs graph, run `--build` first" exit-1 path and the stderr warning when no
code graph was found — and `load_code_files`, which is the only thing that decides whether
BEH-075 fires in real use.

## Intentional Design Decisions

### No code graph means every citation is discarded

**Decision**: `load_code_files` returns an empty set when `knowledge-base/.graph/graph.json` is
missing or unparseable, and an empty file set discards every citation. The build still
succeeds, still records every document and section, and sets `code_graph_present: false` (with
a note on stderr under `--format summary`).

**Rationale**: With no graph there is nothing to check a candidate path against, and a resolver
that guesses invents edges into files that may not exist. Recorded, with the measured effect on
this repository — 273 edges with the graph present, 0 without — in
[ADR-025](../../decisions/ADR-025-three-artifacts-joined-on-file-path.md).

**Security Scan Note**: A zero-edge `docs.json` is a degraded result, not a corrupted one, and
it is self-describing: `code_graph_present` distinguishes "no graph to check against" from "a
repository nobody documented". This is the ADR-029 rule — an answer says what it could not
read — and not a swallowed failure. Do not "fix" it by resolving paths against the filesystem;
that is the rejected alternative.

### Every edge is parsed, none is inferred

**Decision**: `provenance` is the literal string `'extracted'` at both places an edge is
constructed. No model pass contributes edges, and no edge carries a symbol — every edge has
exactly `target`, `line`, `via` and `provenance`.

**Rationale**: The two gaps against the original design (the semantic markdown pass that was
never wired in, and symbol-level targets that no persisted graph can currently support) are
recorded in [ADR-026](../../decisions/ADR-026-the-docs-graph-anchored-at-section.md) so they
are not rediscovered as bugs.

**Security Scan Note**: The constant `provenance` field is deliberate, not a stub awaiting a
value. A scanner that flags it as dead metadata should read it as an assertion: nothing in this
artifact is model-judged.

### A bare filename is resolved when it is unambiguous

**Decision**: `graph_ops.py` with no directory resolves to the one file with that basename;
the citing document's own directory is tried first. A name matching two files resolves to
neither and is added to `ambiguous_citations`.

**Rationale**: Three quarters of the citations in this repository's prose are bare names, so
refusing them would discard most of the graph — measured, with the tie-break rules, in
[ADR-026](../../decisions/ADR-026-the-docs-graph-anchored-at-section.md).

**Security Scan Note**: The narrow path regex plus the URL and timestamp rejections
(`docs_graph.py:196-199`, `:246-248`) exist so that path-shaped strings in prose cannot become
edges. The regex is anchored on a dot-extension and never touches the filesystem — no path is
opened as a result of parsing prose, so this is not a path-traversal surface.

### `related_code` attaches to one section, not all of them

**Decision**: Frontmatter `related_code:` describes the document rather than any one section of
it, so its edges are attached to the first real section (skipping an untitled preamble) instead
of being copied onto every section.

**Rationale**: Duplicating them would make `--impact` report every section of a spec as
affected by any file that spec relates to, which is the document-level answer ADR-026 rejects
on granularity.

**Security Scan Note**: Not security-relevant. Note that this attachment rule is **not**
covered by a test — `RelatedCodeTest` pins the frontmatter parsing only.

## Related Specs

- [SPEC-013: Project Stack Detection](./SPEC-013-project-stack-detection.md)
- [SPEC-014: Existing Documentation Detection](./SPEC-014-existing-docs-detection.md) — where
  the markdown this parses is found

## Notes on Certainty

82. The decisions here are unusually well evidenced — two accepted ADRs record them, the module
docstring states the "parsed, never inferred" rule outright, and the test suite's own docstring
names the two failure modes it exists to prevent — so deliberateness is not in doubt for
BEH-069 through BEH-074. Held below 85 because the whole CLI surface and `load_code_files` are
untested, which makes BEH-075 an inference from a code comment rather than from a pinned
behavior, and because the artifact's consumer is prose in a skill file rather than code, so
nothing pins the output shape that `--impact` callers depend on.

## Change History

| Date | Change | Reason |
|------|--------|--------|
| 2026-08-21 | Initial spec, inferred by brownfield scan | Behaviors recorded as `proposed`; no human has confirmed this intent yet |
