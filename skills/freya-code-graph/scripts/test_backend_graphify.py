#!/usr/bin/env python3
"""Tests for the graphify backend (Track B Phase 2).

Split deliberately in two. The **projection** is a pure function from graphify's payload to the
contract's shape, so it is tested against fixtures and runs everywhere — including CI, which
has no graphify. The handful of tests that need the real binary are skipped when it is absent,
and say so rather than passing quietly.

That split is the point rather than a convenience: the projection is where every decision
lives — which relations become edges, what happens to intra-file links, how exclusions are
applied — and none of it should require an external tool to verify.

Run: python test_backend_graphify.py
"""

import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import backend_graphify  # noqa: E402
import graph_ops  # noqa: E402
import substrate  # noqa: E402
from backend_graphify import GraphifyBackend, GraphifyUnavailable  # noqa: E402

HAVE_GRAPHIFY = shutil.which(backend_graphify.BINARY) is not None
needs_graphify = unittest.skipUnless(
    HAVE_GRAPHIFY, 'the graphify binary is not installed on this machine')


def node(node_id, source_file, label='sym', line='L1', file_type='code'):
    return {'id': node_id, 'label': label, 'source_file': source_file,
            'source_location': line, 'file_type': file_type, '_origin': 'ast'}


def link(source, target, relation='calls', confidence='EXTRACTED', location='L10'):
    return {'source': source, 'target': target, 'relation': relation,
            'confidence': confidence, 'source_location': location, '_origin': 'ast'}


class Base(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)
        self.backend = GraphifyBackend(self.tmp)

    def translate(self, nodes, links, **kw):
        return self.backend.translate({'nodes': nodes, 'links': links}, **kw)

    def edges(self, graph, path):
        return graph['files'][path]['imports']


class TestTheProjection(Base):
    """graphify's nodes are symbols; ours are files. Every link is projected onto the file
    pair its endpoints live in."""

    def test_a_symbol_link_becomes_a_file_edge(self):
        g = self.translate(
            [node('a', 'src/a.py', 'main'), node('b', 'src/b.py', 'helper')],
            [link('a', 'b', 'calls')])
        self.assertEqual(self.edges(g, 'src/a.py'), [
            {'to': 'src/b.py', 'kind': 'calls', 'provenance': 'extracted'}])

    def test_every_file_with_a_symbol_becomes_a_node_even_with_no_edges(self):
        """A file graphify saw but found no dependency in is still a file it saw. Dropping it
        would report a smaller repo than exists."""
        g = self.translate([node('a', 'src/lonely.py')], [])
        self.assertIn('src/lonely.py', g['files'])
        self.assertEqual(self.edges(g, 'src/lonely.py'), [])

    def test_confidence_becomes_provenance(self):
        g = self.translate(
            [node('a', 'src/a.py'), node('b', 'src/b.py')],
            [link('a', 'b', 'calls', confidence='INFERRED')])
        self.assertEqual(self.edges(g, 'src/a.py')[0]['provenance'], 'inferred')

    def test_an_unrecognised_confidence_is_inferred_not_extracted(self):
        """The cautious direction. `extracted` means "stated in the source"; claiming it for a
        value we do not recognise would assert something nobody checked."""
        g = self.translate(
            [node('a', 'src/a.py'), node('b', 'src/b.py')],
            [link('a', 'b', 'calls', confidence='SOMETHING_NEW')])
        self.assertEqual(self.edges(g, 'src/a.py')[0]['provenance'], 'inferred')

    def test_language_comes_from_the_extension(self):
        g = self.translate([node('a', 'Main.java'), node('b', 'lib.rs')], [])
        self.assertEqual(g['files']['Main.java']['language'], 'java')
        self.assertEqual(g['files']['lib.rs']['language'], 'rust')

    def test_an_unknown_extension_has_no_language_rather_than_a_guess(self):
        g = self.translate([node('a', 'thing.wat')], [])
        self.assertIsNone(g['files']['thing.wat']['language'])


class TestRelationMapping(Base):
    """graphify emits eleven relations; the contract's vocabulary has five."""

    def two(self, relation):
        return self.translate(
            [node('a', 'src/a.py'), node('b', 'src/b.py')],
            [link('a', 'b', relation)])

    def test_the_import_family_collapses_to_imports(self):
        for relation in ('imports', 'imports_from'):
            g = self.two(relation)
            self.assertEqual(self.edges(g, 'src/a.py')[0]['kind'], 'imports', relation)

    def test_the_call_family_collapses_to_calls(self):
        for relation in ('calls', 'indirect_call'):
            g = self.two(relation)
            self.assertEqual(self.edges(g, 'src/a.py')[0]['kind'], 'calls', relation)

    def test_the_loose_family_collapses_to_references(self):
        for relation in ('references', 'uses', 'reads_from'):
            g = self.two(relation)
            self.assertEqual(self.edges(g, 'src/a.py')[0]['kind'], 'references', relation)

    def test_inherits_survives_as_itself(self):
        self.assertEqual(self.edges(self.two('inherits'), 'src/a.py')[0]['kind'], 'inherits')

    def test_structural_relations_are_not_dependencies(self):
        """`contains` (file has symbol) and `method` (class has method) are the node
        hierarchy. Measured at 2,318 links on this repository — emitting them would put the
        shape of the code into a query that means "what breaks if I change this file"."""
        for relation in ('contains', 'method'):
            g = self.two(relation)
            self.assertEqual(self.edges(g, 'src/a.py'), [], relation)

    def test_graphifys_own_docs_graph_is_not_adopted(self):
        """`rationale_for` is 543 links between `rationale`/`document` nodes. We already have
        a docs graph built from citations we control (CD-7); a second one would give two
        answers to "which docs describe this file"."""
        g = self.translate(
            [node('a', 'docs/why.md', file_type='rationale'), node('b', 'src/b.py')],
            [link('a', 'b', 'rationale_for')])
        self.assertNotIn('docs/why.md', g['files'])
        self.assertEqual(self.edges(g, 'src/b.py'), [])

    def test_an_unknown_future_relation_is_dropped_rather_than_guessed(self):
        g = self.two('teleports_to')
        self.assertEqual(self.edges(g, 'src/a.py'), [])


class TestWhatIsDeliberatelyNotAnEdge(Base):
    def test_a_non_code_node_is_not_a_file(self):
        g = self.translate([node('d', 'README.md', file_type='document')], [])
        self.assertEqual(g['files'], {})

    def test_an_intra_file_link_is_not_a_self_edge(self):
        """1,475 of graphify's `calls` links on this repository are intra-file. Every one
        would make a file its own dependent, and blast radius walks these edges — so a file
        would always appear in its own blast radius."""
        g = self.translate(
            [node('a', 'src/a.py', 'outer'), node('b', 'src/a.py', 'inner')],
            [link('a', 'b', 'calls')])
        self.assertIn('src/a.py', g['files'])
        self.assertEqual(self.edges(g, 'src/a.py'), [])

    def test_a_link_to_a_node_that_does_not_exist_is_dropped(self):
        g = self.translate([node('a', 'src/a.py')], [link('a', 'ghost')])
        self.assertEqual(self.edges(g, 'src/a.py'), [])

    def test_a_node_with_no_source_file_cannot_anchor_an_edge(self):
        payload = {'nodes': [node('a', 'src/a.py'), node('b', None)],
                   'links': [link('a', 'b')]}
        g = self.backend.translate(payload)
        self.assertEqual(self.edges(g, 'src/a.py'), [])

    def test_malformed_links_are_skipped_not_fatal(self):
        g = self.translate([node('a', 'src/a.py'), node('b', 'src/b.py')],
                           ['not a dict', None, 42, {}, link('a', 'b')])
        self.assertEqual(len(self.edges(g, 'src/a.py')), 1)

    def test_duplicate_links_between_the_same_pair_collapse_to_one_edge(self):
        """Without symbols an edge is (from, to, kind), so the 417 symbol-level links on this
        repository become 73 file pairs. Keeping all of them would count one dependency many
        times in every dependents list."""
        g = self.translate(
            [node('a', 'src/a.py', 'f1'), node('a2', 'src/a.py', 'f2'),
             node('b', 'src/b.py', 'g')],
            [link('a', 'b', 'calls'), link('a2', 'b', 'calls')])
        self.assertEqual(len(self.edges(g, 'src/a.py')), 1)

    def test_two_kinds_between_one_pair_stay_two_edges(self):
        """They are different facts. Collapsing them would lose the distinction the object
        edge shape was introduced to carry."""
        g = self.translate(
            [node('a', 'src/a.py'), node('b', 'src/b.py')],
            [link('a', 'b', 'imports'), link('a', 'b', 'calls')])
        self.assertEqual({e['kind'] for e in self.edges(g, 'src/a.py')},
                         {'imports', 'calls'})


class TestExclusionsArePostFiltered(Base):
    """`graphify update` takes no exclusion flag, so obligation 6 is honoured on the way out.
    That settles spec open question 3, which had left the mechanism undecided."""

    def test_an_excluded_file_is_neither_a_node_nor_an_edge_end(self):
        g = self.translate(
            [node('a', 'src/a.py'), node('v', 'vendor/lib.py')],
            [link('a', 'v', 'imports')],
            exclusions=substrate.Exclusions(directories=['vendor']))
        self.assertNotIn('vendor/lib.py', g['files'])
        self.assertEqual(self.edges(g, 'src/a.py'), [])

    def test_an_edge_out_of_an_excluded_file_goes_too(self):
        g = self.translate(
            [node('a', 'src/a.py'), node('v', 'vendor/lib.py')],
            [link('v', 'a', 'imports')],
            exclusions=substrate.Exclusions(directories=['vendor']))
        self.assertEqual(list(g['files']), ['src/a.py'])

    def test_an_override_keeps_a_file_the_defaults_would_drop(self):
        g = self.translate(
            [node('a', 'src/a.py'), node('d', 'docs/lit.py')],
            [link('a', 'd', 'imports')],
            exclusions=substrate.Exclusions(directories=['docs'], overrides=['docs']))
        self.assertIn('docs/lit.py', g['files'])


class TestTheContractIsSatisfied(Base):
    def test_it_conforms(self):
        self.assertEqual(substrate.conformance_errors(self.backend), [])

    def test_it_declares_only_relations_it_can_emit(self):
        """`re_exports` is absent because graphify has no relation meaning it. Claiming a kind
        a backend cannot emit is how a caller trusts a query that always returns nothing."""
        relations = self.backend.coverage().relations
        self.assertNotIn('re_exports', relations)
        self.assertEqual(set(relations), set(backend_graphify.RELATIONS.values()) - {None})

    def test_a_translated_graph_validates(self):
        g = self.translate([node('a', 'src/a.py'), node('b', 'src/b.py')],
                           [link('a', 'b', 'imports')])
        substrate.link_dependents(g)
        self.assertEqual(substrate.validate_graph(g, self.backend.coverage()), [])

    def test_the_graph_says_which_backend_made_it(self):
        g = self.translate([node('a', 'src/a.py')], [])
        self.assertEqual(g['substrate']['backend'], 'graphify')
        self.assertEqual(g['version'], substrate.GRAPH_SCHEMA_VERSION)

    def test_edges_are_ordered_so_two_runs_agree(self):
        nodes = [node('a', 'src/a.py'), node('b', 'src/b.py'), node('c', 'src/c.py')]
        links = [link('a', 'c', 'imports'), link('a', 'b', 'imports')]
        first = self.translate(nodes, links)
        second = self.translate(nodes, list(reversed(links)))
        self.assertEqual(first['files']['src/a.py']['imports'],
                         second['files']['src/a.py']['imports'])


class TestFailureIsReportedNotSwallowed(Base):
    """A backend that cannot produce a graph must say so. Returning an empty one is the
    confident-empty failure the whole contract exists to remove."""

    def test_a_missing_binary_raises_rather_than_returning_nothing(self):
        self.backend.available = lambda: False
        with self.assertRaises(GraphifyUnavailable):
            self.backend.build()

    def test_success_with_no_output_file_is_a_failure(self):
        self.backend.available = lambda: True
        self.backend._run = lambda: None
        original = subprocess.run

        def fake(*a, **kw):
            return original([sys.executable, '-c', ''], capture_output=True, text=True)

        backend_graphify.subprocess.run = fake
        self.addCleanup(setattr, backend_graphify.subprocess, 'run', original)
        with self.assertRaises(GraphifyUnavailable) as ctx:
            self.backend.build()
        self.assertIn('wrote no', str(ctx.exception))

    def test_a_build_failure_degrades_to_the_floor_rather_than_crashing(self):
        """Selection degrades when a backend is unavailable. This is the other half: one that
        passed selection and then threw used to take the whole build down with it."""
        os.makedirs(os.path.join(self.tmp, 'src'))
        with open(os.path.join(self.tmp, 'src', 'a.py'), 'w') as handle:
            handle.write('x = 1\n')

        class Exploding(GraphifyBackend):
            def build(self, **kw):
                raise GraphifyUnavailable('boom')

        out = graph_ops._run_or_degrade(
            graph_ops.run_build, Exploding(self.tmp), graph_ops.CodeGraph(self.tmp),
            True, None, None)
        self.assertEqual(out['files_scanned'], 1)
        written = json.load(open(out['cached_to'], encoding='utf-8'))
        self.assertEqual(written['substrate']['backend'], 'homegrown')
        self.assertEqual(written['substrate']['degraded_from'], 'graphify')

    def test_the_floor_failing_is_not_silently_swallowed(self):
        """There is nothing left to fall back to, so it must surface."""
        class BrokenFloor(graph_ops.CodeGraph):
            def build(self, **kw):
                raise RuntimeError('the floor itself is broken')

        floor = BrokenFloor(self.tmp)
        with self.assertRaises(RuntimeError):
            graph_ops._run_or_degrade(graph_ops.run_build, floor, floor, True, None, None)


@needs_graphify
class TestAgainstTheRealBinary(Base):
    """The claims about graphify that fixtures cannot check."""

    def project(self, files):
        for rel, body in files.items():
            path = os.path.join(self.tmp, rel)
            os.makedirs(os.path.dirname(path), exist_ok=True)
            with open(path, 'w', encoding='utf-8') as handle:
                handle.write(body)
        return self.tmp

    def test_it_extracts_a_language_the_floor_cannot_read(self):
        """The entire argument for this backend. A Java repo is graphed as empty by the
        homegrown resolver and reported as a success."""
        self.project({
            'src/Main.java': ('public class Main {\n'
                              '  public int run() { return new Helper().help(); }\n}\n'),
            'src/Helper.java': 'public class Helper {\n  public int help() { return 1; }\n}\n',
        })
        graph = GraphifyBackend(self.tmp).build().graph
        self.assertIn('src/Main.java', graph['files'])
        self.assertIn('src/Helper.java', graph['files'])

        floor = graph_ops.CodeGraph(self.tmp).build(non_interactive=True).graph
        self.assertEqual(floor['files'], {}, 'the floor should see no Java at all')

    def test_a_deleted_file_leaves_the_graph(self):
        """This is what `coverage.incremental=True` claims, so it is measured, not assumed."""
        self.project({'src/a.py': 'from b import h\ndef m(): return h()\n',
                      'src/b.py': 'def h(): return 1\n'})
        self.assertIn('src/b.py', GraphifyBackend(self.tmp).build().graph['files'])
        os.remove(os.path.join(self.tmp, 'src', 'b.py'))
        self.assertNotIn('src/b.py', GraphifyBackend(self.tmp).update().graph['files'])

    def test_two_runs_of_unchanged_source_agree(self):
        self.project({'src/a.py': 'def m(): return 1\n'})
        first = GraphifyBackend(self.tmp).build().graph['files']
        second = GraphifyBackend(self.tmp).build().graph['files']
        self.assertEqual(first, second)

    def test_an_empty_project_still_gets_a_graph(self):
        """graphify exits 1 on a project with nothing to extract — its message,
        "Nothing to update or rebuild failed", conflates the two cases and cannot be told
        apart without matching on a string that will change between versions.

        So the backend reports it as a failure, which is honest, and the contract degrades to
        the floor, which produces the correct empty graph. Asserted through `_run_or_degrade`
        because the guarantee that matters is the one a user gets, not the one the backend
        returns.
        """
        out = graph_ops._run_or_degrade(
            graph_ops.run_build, GraphifyBackend(self.tmp),
            graph_ops.CodeGraph(self.tmp), True, None, None)
        written = json.load(open(out['cached_to'], encoding='utf-8'))
        self.assertEqual(written['files'], {})
        self.assertEqual(written['substrate']['backend'], 'homegrown')
        self.assertEqual(written['substrate']['degraded_from'], 'graphify')

    def test_a_second_run_over_unchanged_source_is_not_mistaken_for_a_failure(self):
        """The cached no-op path. If it exited non-zero like the empty case, every steady
        state `--update` would degrade to the floor and the opt-in would quietly stop
        applying."""
        self.project({'src/a.py': 'def m(): return 1\n'})
        GraphifyBackend(self.tmp).build()
        again = GraphifyBackend(self.tmp).update()
        self.assertEqual(again.status, substrate.Result.UPDATED)
        self.assertIn('src/a.py', again.graph['files'])


if __name__ == '__main__':
    unittest.main()
