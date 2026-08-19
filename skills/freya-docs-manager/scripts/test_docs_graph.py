#!/usr/bin/env python3
"""Proof suite for docs_graph.py — the doc-section to code edge producer (Track B Phase 4).

Two things are being pinned. The chunker must never corrupt a document, which is the bug class
the F7 JSONC stripper already demonstrated once. And the citation parser must not invent edges,
because a docs graph nobody trusts is worse than no docs graph.

Run: python test_docs_graph.py
"""

import json
import os
import shutil
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import docs_graph  # noqa: E402


class Base(unittest.TestCase):
    def mk(self, files):
        d = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, d, ignore_errors=True)
        for rel, content in files.items():
            p = Path(d) / rel
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_text(content, encoding="utf-8")
        return d


class ChunkingTest(Base):
    """Rule 1: split only at heading boundaries. Rules 2 and 3: blocks are atomic."""

    def sections(self, text):
        return docs_graph.split_sections(text)

    def test_splits_at_headings(self):
        secs = self.sections("# One\nalpha\n\n## Two\nbeta\n")
        self.assertEqual([s.title for s in secs], ["One", "Two"])
        self.assertIn("alpha", secs[0].body)
        self.assertIn("beta", secs[1].body)

    def test_a_hash_inside_a_fence_is_not_a_heading(self):
        """The whole point. A bash comment looks exactly like an H1."""
        text = (
            "# Real\n"
            "```bash\n"
            "# not a heading\n"
            "## also not a heading\n"
            "```\n"
            "after\n"
        )
        secs = self.sections(text)
        self.assertEqual([s.title for s in secs], ["Real"])
        self.assertIn("## also not a heading", secs[0].body)

    def test_a_fence_is_never_split(self):
        text = "# A\n```\nline1\nline2\n```\n"
        secs = self.sections(text)
        body = secs[0].body
        self.assertEqual(body.count("```"), 2)

    def test_a_mermaid_diagram_survives_intact(self):
        """architecture.md has these, and a line-count splitter would halve one."""
        text = (
            "# Diagram\n"
            "```mermaid\n"
            "graph TD\n"
            "  A --> B\n"
            "  B --> C\n"
            "```\n"
        )
        secs = self.sections(text)
        self.assertEqual(len(secs), 1)
        self.assertIn("A --> B", secs[0].body)
        self.assertIn("B --> C", secs[0].body)

    def test_tilde_fences_are_handled(self):
        text = "# A\n~~~\n# not a heading\n~~~\n"
        self.assertEqual([s.title for s in self.sections(text)], ["A"])

    def test_a_longer_fence_is_not_closed_by_a_shorter_one(self):
        """Nested fences: ```` can contain ``` verbatim."""
        text = "# A\n````\n```\n# inner\n```\n````\n## B\nx\n"
        self.assertEqual([s.title for s in self.sections(text)], ["A", "B"])

    def test_an_unclosed_fence_does_not_swallow_the_rest_silently(self):
        """Malformed input must not make every later heading vanish without a word."""
        text = "# A\n```\nunclosed\n\n## B\nbeta\n"
        secs = self.sections(text)
        self.assertEqual([s.title for s in secs], ["A"])
        self.assertTrue(any(s.warnings for s in secs))

    def test_content_before_the_first_heading_is_kept(self):
        secs = self.sections("preamble text\n\n# First\nbody\n")
        self.assertEqual(len(secs), 2)
        self.assertIsNone(secs[0].title)
        self.assertIn("preamble", secs[0].body)

    def test_frontmatter_is_not_a_section(self):
        secs = self.sections("---\nid: SPEC-001\n---\n\n# Title\nbody\n")
        self.assertEqual([s.title for s in secs], ["Title"])

    def test_no_content_is_lost(self):
        """The invariant that matters: chunking is a partition, not a filter."""
        text = (
            "intro\n# A\nalpha\n```\n# fake\n```\n## B\nbeta\n\n| a | b |\n| - | - |\n"
        )
        secs = self.sections(text)
        rejoined = "".join(s.raw for s in secs)
        self.assertEqual(rejoined, text)

    def test_slugs_are_github_style_and_unique(self):
        secs = self.sections("# Output Artifacts\nx\n## Output Artifacts\ny\n")
        self.assertEqual(secs[0].slug, "output-artifacts")
        self.assertEqual(secs[1].slug, "output-artifacts-1")

    def test_setext_headings_are_recognised(self):
        secs = self.sections("Title\n=====\nbody\n\nOther\n-----\nmore\n")
        self.assertEqual([s.title for s in secs], ["Title", "Other"])


class CitationTest(Base):
    """Rule: parse what is written. Never infer, and never invent."""

    def cites(self, text, doc="docs/a.md", files=("src/graph_ops.py",)):
        return docs_graph.find_citations(text, doc, set(files))

    def test_a_path_line_citation_is_found(self):
        found = self.cites("See `src/graph_ops.py:212` for detail.")
        self.assertEqual(len(found), 1)
        self.assertEqual(found[0].target, "src/graph_ops.py")
        self.assertEqual(found[0].line, 212)

    def test_a_bare_file_reference_is_found_without_a_line(self):
        found = self.cites("Defined in `src/graph_ops.py`.")
        self.assertEqual(found[0].target, "src/graph_ops.py")
        self.assertIsNone(found[0].line)

    def test_a_url_with_a_port_is_not_a_citation(self):
        self.assertEqual(self.cites("Visit http://example.com:8080/src/graph_ops.py"), [])

    def test_a_time_is_not_a_citation(self):
        self.assertEqual(self.cites("Runs at 12:30 every day."), [])

    def test_a_file_not_in_the_graph_is_not_an_edge(self):
        """The parser reads text; only a real file becomes an edge."""
        self.assertEqual(self.cites("See `src/imaginary.py:9`."), [])

    def test_a_relative_markdown_link_is_a_citation(self):
        found = docs_graph.find_citations(
            "See [the resolver](../src/graph_ops.py).", "docs/a.md", {"src/graph_ops.py"})
        self.assertEqual(found[0].target, "src/graph_ops.py")

    def test_a_link_to_another_doc_is_not_a_code_edge(self):
        self.assertEqual(
            docs_graph.find_citations("See [other](./other.md).", "docs/a.md",
                                      {"src/graph_ops.py"}), [])

    def test_duplicate_citations_collapse_but_keep_every_line(self):
        found = self.cites("`src/graph_ops.py:212` and again `src/graph_ops.py:212` "
                           "and `src/graph_ops.py:300`")
        self.assertEqual(len(found), 2)
        self.assertEqual(sorted(c.line for c in found), [212, 300])


class BareFilenameTest(Base):
    """Prose cites `graph_ops.py:212`, not the full path.

    Measured on this repo: 103 citations are bare filenames against 67 full paths, so
    requiring a path would discard the majority of the graph. Resolution is allowed only when
    the name is unambiguous — guessing between two same-named files would point someone at the
    wrong document, which is worse than pointing them at none.
    """

    def test_an_unambiguous_bare_filename_resolves(self):
        found = docs_graph.find_citations(
            "See `graph_ops.py:212`.", "docs/a.md", {"skills/cg/scripts/graph_ops.py"})
        self.assertEqual(found[0].target, "skills/cg/scripts/graph_ops.py")
        self.assertEqual(found[0].line, 212)

    def test_an_ambiguous_bare_filename_is_not_guessed(self):
        found = docs_graph.find_citations(
            "See `utils.py`.", "docs/a.md", {"a/utils.py", "b/utils.py"})
        self.assertEqual(found, [])

    def test_a_full_path_still_wins_over_a_bare_match(self):
        found = docs_graph.find_citations(
            "See `b/utils.py`.", "docs/a.md", {"a/utils.py", "b/utils.py"})
        self.assertEqual([c.target for c in found], ["b/utils.py"])

    def test_a_bare_name_not_in_the_graph_is_not_an_edge(self):
        self.assertEqual(
            docs_graph.find_citations("See `nowhere.py`.", "docs/a.md", {"a/utils.py"}), [])

    def test_ambiguity_is_reported_rather_than_silently_dropped(self):
        d = self.mk({"docs/a.md": "# A\nSee `utils.py`.\n"})
        graph = docs_graph.build(d, code_files={"a/utils.py", "b/utils.py"})
        self.assertTrue(graph.get("ambiguous_citations"))
        self.assertIn("utils.py", json.dumps(graph["ambiguous_citations"]))


class RelatedCodeTest(Base):
    def test_related_code_frontmatter_becomes_edges(self):
        text = (
            "---\n"
            "id: SPEC-001\n"
            "related_code:\n"
            "  - src/graph_ops.py\n"
            "  - src/other.py\n"
            "---\n"
            "# Spec\n"
        )
        found = docs_graph.find_related_code(text, {"src/graph_ops.py", "src/other.py"})
        self.assertEqual(sorted(found), ["src/graph_ops.py", "src/other.py"])

    def test_an_inline_list_is_read(self):
        text = "---\nrelated_code: [src/graph_ops.py]\n---\n# x\n"
        self.assertEqual(docs_graph.find_related_code(text, {"src/graph_ops.py"}),
                         ["src/graph_ops.py"])

    def test_absent_frontmatter_yields_nothing(self):
        self.assertEqual(docs_graph.find_related_code("# no frontmatter\n", {"a.py"}), [])


class BuildTest(Base):
    """The artifact, and the query built on it."""

    def build(self, files, code_files):
        d = self.mk(files)
        return d, docs_graph.build(d, code_files=set(code_files))

    def test_the_artifact_has_the_expected_shape(self):
        d, graph = self.build(
            {"docs/arch.md": "# Output Artifacts\nSee `src/g.py:12`.\n"},
            ["src/g.py"])
        self.assertIn("docs", graph)
        entry = graph["docs"]["docs/arch.md"]
        section = entry["sections"][0]
        self.assertEqual(section["slug"], "output-artifacts")
        self.assertEqual(section["edges"][0]["target"], "src/g.py")
        self.assertEqual(section["edges"][0]["provenance"], "extracted")

    def test_the_anchor_is_the_section_not_the_line(self):
        """Line numbers shift when anyone inserts a paragraph; the heading does not."""
        d, graph = self.build(
            {"docs/a.md": "# Intro\nx\n\n## Deep Dive\nSee `src/g.py:99`.\n"},
            ["src/g.py"])
        secs = graph["docs"]["docs/a.md"]["sections"]
        cited = [s for s in secs if s["edges"]]
        self.assertEqual(len(cited), 1)
        self.assertEqual(cited[0]["slug"], "deep-dive")
        # the line is retained as evidence inside the edge, not as the anchor
        self.assertEqual(cited[0]["edges"][0]["line"], 99)

    def test_impact_answers_which_sections_a_file_appears_in(self):
        d, graph = self.build({
            "docs/a.md": "# A\n`src/g.py:1`\n",
            "docs/b.md": "# B\nunrelated\n\n## B2\n`src/g.py`\n",
        }, ["src/g.py"])
        hits = docs_graph.impact(graph, "src/g.py")
        self.assertEqual(sorted(h["anchor"] for h in hits),
                         ["docs/a.md#a", "docs/b.md#b2"])

    def test_impact_on_an_uncited_file_is_empty_not_an_error(self):
        d, graph = self.build({"docs/a.md": "# A\nnothing here\n"}, ["src/g.py"])
        self.assertEqual(docs_graph.impact(graph, "src/g.py"), [])

    def test_a_doc_with_no_citations_is_still_recorded(self):
        """Absence of edges is a fact; a missing doc is a gap. They must be distinguishable."""
        d, graph = self.build({"docs/a.md": "# A\nprose only\n"}, ["src/g.py"])
        self.assertIn("docs/a.md", graph["docs"])
        self.assertEqual(graph["docs"]["docs/a.md"]["sections"][0]["edges"], [])

    def test_the_artifact_records_how_it_was_produced(self):
        d, graph = self.build({"docs/a.md": "# A\n`src/g.py`\n"}, ["src/g.py"])
        self.assertEqual(graph["producer"], "docs-graph")
        self.assertIn("docs_scanned", graph)

    def test_a_document_that_cannot_be_parsed_is_reported_not_skipped(self):
        d, graph = self.build({"docs/a.md": "# A\n```\nunclosed\n"}, ["src/g.py"])
        self.assertTrue(graph["docs"]["docs/a.md"].get("warnings"))

    def test_output_is_deterministic(self):
        files = {"docs/a.md": "# A\n`src/g.py:2` `src/h.py:1`\n"}
        d1, g1 = self.build(files, ["src/g.py", "src/h.py"])
        d2, g2 = self.build(files, ["src/g.py", "src/h.py"])
        self.assertEqual(json.dumps(g1["docs"], sort_keys=True),
                         json.dumps(g2["docs"], sort_keys=True))


if __name__ == "__main__":
    unittest.main(verbosity=2)
