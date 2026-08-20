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
import pathlib
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


def graphify_module_source(dotted):
    """Read a module out of graphify's own interpreter, or None if it cannot be reached.

    graphify installs as a `uv tool` in its own virtualenv, so it is on PATH but not on this
    process's import path. The binary's shebang names the interpreter that *can* import it.
    """
    binary = shutil.which(backend_graphify.BINARY)
    if not binary:
        return None
    try:
        shebang = pathlib.Path(binary).read_text(errors='replace').splitlines()[0]
    except (OSError, IndexError):
        return None
    if not shebang.startswith('#!'):
        return None
    interpreter = shebang[2:].strip()
    try:
        out = subprocess.run(
            [interpreter, '-c',
             'import %s as m; print(m.__file__)' % dotted],
            capture_output=True, text=True, timeout=60)
    except (OSError, subprocess.TimeoutExpired):
        return None
    if out.returncode != 0:
        return None
    try:
        return pathlib.Path(out.stdout.strip()).read_text(encoding='utf-8')
    except OSError:
        return None


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


class TestSymbolRefinement(Base):
    """Phase 3. Symbols refine a file anchor; they never replace it (spec §5, CD-6)."""

    def test_off_by_default(self):
        """Measured on this repository, symbols turn 73 file-level edges into 417 — a test
        module calling one helper sixty times is sixty symbol pairs and one dependency.
        Nothing downstream reads them yet, so the cost is not imposed by default."""
        g = self.translate([node('a', 'src/a.py', 'main'), node('b', 'src/b.py', 'helper')],
                           [link('a', 'b', 'calls')])
        self.assertEqual(self.edges(g, 'src/a.py')[0],
                         {'to': 'src/b.py', 'kind': 'calls', 'provenance': 'extracted'})

    def test_on_request_an_edge_names_both_ends(self):
        g = self.translate([node('a', 'src/a.py', 'main'), node('b', 'src/b.py', 'helper')],
                           [link('a', 'b', 'calls', location='L42')], symbols=True)
        self.assertEqual(self.edges(g, 'src/a.py')[0], {
            'to': 'src/b.py', 'kind': 'calls', 'provenance': 'extracted',
            'from_symbol': 'main', 'to_symbol': 'helper', 'line': 42})

    def test_the_file_anchor_survives_refinement(self):
        """The floor. A consumer that ignores symbols must behave exactly as before."""
        plain = self.translate([node('a', 'src/a.py', 'm'), node('b', 'src/b.py', 'h')],
                               [link('a', 'b', 'imports')])
        refined = self.translate([node('a', 'src/a.py', 'm'), node('b', 'src/b.py', 'h')],
                                 [link('a', 'b', 'imports')], symbols=True)
        self.assertEqual(substrate.edge_ends(self.edges(plain, 'src/a.py')),
                         substrate.edge_ends(self.edges(refined, 'src/a.py')))

    def test_symbols_split_edges_the_file_view_would_merge(self):
        """Two calls into one file are one dependency and two facts. Without symbols they
        collapse; with them, both survive — which is the whole point of the refinement."""
        nodes = [node('a1', 'src/a.py', 'first'), node('a2', 'src/a.py', 'second'),
                 node('b', 'src/b.py', 'helper')]
        links = [link('a1', 'b', 'calls'), link('a2', 'b', 'calls')]
        self.assertEqual(len(self.edges(self.translate(nodes, links), 'src/a.py')), 1)
        self.assertEqual(
            len(self.edges(self.translate(nodes, links, symbols=True), 'src/a.py')), 2)

    def test_a_method_symbol_is_qualified_by_its_owning_class(self):
        """graphify labels a method with its own name only — `.setUp()`. Measured on this
        repository, 64 of 1,731 code symbols share a bare label with a sibling in the same
        file (three different `._run()` in one test module). Unqualified, a symbol name
        describes a symbol without identifying one."""
        g = self.translate(
            [node('cls', 'src/a.py', 'InitTest'), node('m', 'src/a.py', '.run()'),
             node('t', 'src/b.py', 'helper')],
            [link('cls', 'm', 'method'), link('m', 't', 'calls')], symbols=True)
        self.assertEqual(self.edges(g, 'src/a.py')[0]['from_symbol'], 'InitTest.run()')

    def test_qualification_disambiguates_siblings_that_share_a_bare_label(self):
        g = self.translate(
            [node('c1', 'src/a.py', 'FirstTest'), node('c2', 'src/a.py', 'SecondTest'),
             node('m1', 'src/a.py', '._run()'), node('m2', 'src/a.py', '._run()'),
             node('t', 'src/b.py', 'helper')],
            [link('c1', 'm1', 'method'), link('c2', 'm2', 'method'),
             link('m1', 't', 'calls'), link('m2', 't', 'calls')], symbols=True)
        self.assertEqual(
            sorted(e['from_symbol'] for e in self.edges(g, 'src/a.py')),
            ['FirstTest._run()', 'SecondTest._run()'])

    def test_a_module_level_function_is_left_unqualified(self):
        """There is nothing to qualify it with, and inventing a prefix would be worse."""
        g = self.translate([node('a', 'src/a.py', 'main()'), node('b', 'src/b.py', 'h')],
                           [link('a', 'b', 'calls')], symbols=True)
        self.assertEqual(self.edges(g, 'src/a.py')[0]['from_symbol'], 'main()')

    def test_method_is_still_not_an_edge(self):
        """Kept as a lookup, dropped as a dependency — it never crosses a file boundary."""
        g = self.translate(
            [node('cls', 'src/a.py', 'C'), node('m', 'src/a.py', '.run()')],
            [link('cls', 'm', 'method')], symbols=True)
        self.assertEqual(self.edges(g, 'src/a.py'), [])

    def test_a_missing_line_is_omitted_rather_than_guessed(self):
        bad = link('a', 'b', 'calls')
        bad['source_location'] = 'not-a-line'
        g = self.translate([node('a', 'src/a.py', 'm'), node('b', 'src/b.py', 'h')],
                           [bad], symbols=True)
        self.assertNotIn('line', self.edges(g, 'src/a.py')[0])

    def test_an_unnamed_symbol_is_omitted_rather_than_recorded_empty(self):
        g = self.translate([node('a', 'src/a.py', ''), node('b', 'src/b.py', 'h')],
                           [link('a', 'b', 'calls')], symbols=True)
        edge = self.edges(g, 'src/a.py')[0]
        self.assertNotIn('from_symbol', edge)
        self.assertEqual(edge['to_symbol'], 'h')

    def test_a_refined_graph_still_validates(self):
        g = self.translate([node('a', 'src/a.py', 'm'), node('b', 'src/b.py', 'h')],
                           [link('a', 'b', 'imports')], symbols=True)
        substrate.link_dependents(g)
        self.assertEqual(substrate.validate_graph(g, self.backend.coverage()), [])


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

    def test_the_declaration_is_derived_from_the_mapping_table(self):
        """Written down twice, the two drift. A row added to the table must not leave the
        coverage declaration claiming less — or more — than the projection can emit."""
        self.assertEqual(set(self.backend.coverage().relations),
                         set(backend_graphify.RELATIONS.values()) - {None})

    def test_an_unmapped_relation_is_reported_rather_than_defaulted(self):
        """The vocabulary cannot be enumerated: grepping graphify's source finds 26 relation
        names, and `reads_from` — which this repository's own graph contains — is not one of
        them. So a name this table has never seen is a capability arriving upstream, and it
        has to surface as "dropped N links" rather than as a repository that looks thin."""
        g = self.translate(
            [node('a', 'src/a.py'), node('b', 'src/b.py')],
            [link('a', 'b', 'teleports_to'), link('a', 'b', 'teleports_to'),
             link('a', 'b', 'imports')])
        self.assertEqual(g['substrate']['unmapped_relations'], {'teleports_to': 2})
        self.assertEqual(len(self.edges(g, 'src/a.py')), 1)

    def test_a_relation_known_not_to_be_a_dependency_is_not_reported(self):
        """`contains` is listed with an explicit None. Being on the table is what stops it
        appearing in the unmapped report on every single build."""
        g = self.translate([node('a', 'src/a.py'), node('b', 'src/a.py')],
                           [link('a', 'b', 'contains')])
        self.assertNotIn('unmapped_relations', g['substrate'])

    def test_direction_disagreeing_with_the_link_s_own_source_file_is_counted(self):
        """graphify writes `directed: false`, so field order is the only carrier of
        direction — and Phase 0 measured that losing it takes mean blast radius from 5 files
        to 188. Each link repeats its own source_file, which is a free cross-check."""
        bad = link('a', 'b', 'imports')
        bad['source_file'] = 'somewhere/else.py'
        g = self.translate([node('a', 'src/a.py'), node('b', 'src/b.py')], [bad])
        self.assertEqual(g['substrate']['direction_warnings'], 1)

    def test_a_consistent_graph_carries_no_direction_warning(self):
        good = link('a', 'b', 'imports')
        good['source_file'] = 'src/a.py'
        g = self.translate([node('a', 'src/a.py'), node('b', 'src/b.py')], [good])
        self.assertNotIn('direction_warnings', g['substrate'])

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


class TestTheUnderReportingGate(unittest.TestCase):
    """Spec §9.1, the test that blocks adoption: **does graphify lose an edge the homegrown
    resolver finds?** A lost edge narrows a behaviour's blast radius, the behaviour is not
    flagged, and a regression walks through the wrap-up gate.

    Run against a committed fixture and a *recorded* graphify extraction, so it gates the half
    that can regress here — our projection — on any machine, with no binary. graphify's own
    extraction is gated separately by the live tests below, which skip when it is absent.
    """

    FIXTURE = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                           'testdata', 'gate91.json')

    @classmethod
    def setUpClass(cls):
        with open(cls.FIXTURE, encoding='utf-8') as handle:
            cls.data = json.load(handle)

    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)
        for rel, body in self.data['files'].items():
            path = os.path.join(self.tmp, rel)
            os.makedirs(os.path.dirname(path), exist_ok=True)
            with open(path, 'w', encoding='utf-8') as handle:
                handle.write(body)

    def pairs(self, graph):
        return {(src, substrate.edge_other(e))
                for src, info in graph['files'].items()
                for e in info['imports']
                if substrate.is_internal(substrate.edge_other(e))}

    def both(self):
        homegrown = graph_ops.CodeGraph(self.tmp).build(non_interactive=True).graph
        translated = GraphifyBackend(self.tmp).translate(self.data['graphify'])
        return self.pairs(homegrown), self.pairs(translated)

    def test_graphify_loses_no_edge_the_floor_finds(self):
        floor, graphify = self.both()
        missed = floor - graphify
        # The one known exception, and it is homegrown's defect rather than graphify's:
        # `shim.py` contains `from util import compute` inside a *string literal*, and the
        # homegrown regexes read string bodies (backlog item 10). graphify parses.
        self.assertEqual(missed, {('src/shim.py', 'src/util.py')},
                         'graphify lost edges beyond the known homegrown false positive: %s'
                         % sorted(missed - {('src/shim.py', 'src/util.py')}))

    def test_the_known_miss_really_is_a_string_literal(self):
        """Pinned so the exemption above cannot quietly start excusing something else."""
        body = self.data['files']['src/shim.py']
        self.assertIn('"from util import compute', body)

    def test_graphify_sees_a_language_the_floor_is_blind_to(self):
        """The polyglot half. Without this the gate would pass for a backend that merely
        matched the floor, which is not why the second substrate exists."""
        floor, graphify = self.both()
        java = {p for p in graphify if p[0].endswith('.java')}
        self.assertTrue(java, 'no Java edge in the recorded extraction')
        self.assertFalse({p for p in floor if p[0].endswith('.java')})

    def test_direction_is_preserved_and_not_symmetrised(self):
        """graphify writes `directed: false`. Phase 0 measured that reading it as undirected
        takes mean blast radius from 5 files to 188, so direction is the single
        highest-consequence silent regression available here."""
        _, graphify = self.both()
        self.assertIn(('src/app.ts', 'src/helper.ts'), graphify)
        self.assertNotIn(('src/helper.ts', 'src/app.ts'), graphify)

    def test_the_projected_edge_set_is_pinned_exactly(self):
        """Pairs alone are a weak gate on this fixture: three relations carry each pair, so
        dropping one changes nothing observable. Pinning (from, to, kind) catches a mapping
        change that *does* alter the graph — most importantly losing `calls`, which is the
        only relation carrying the Java edge and therefore the whole polyglot claim.
        """
        translated = GraphifyBackend(self.tmp).translate(self.data['graphify'])
        got = {(src, substrate.edge_other(e), substrate.edge_kind(e))
               for src, info in translated['files'].items() for e in info['imports']}
        self.assertEqual(got, {
            ('src/app.ts', 'src/helper.ts', 'imports'),
            ('src/app.ts', 'src/helper.ts', 'calls'),
            ('src/main.py', 'src/util.py', 'imports'),
            ('src/main.py', 'src/util.py', 'calls'),
            ('java/Service.java', 'java/Repo.java', 'calls'),
        })

    def test_the_translated_graph_satisfies_the_contract(self):
        translated = GraphifyBackend(self.tmp).translate(self.data['graphify'])
        substrate.link_dependents(translated)
        errors = substrate.validate_graph(translated,
                                          GraphifyBackend(self.tmp).coverage())
        self.assertEqual(errors, [])

    @needs_graphify
    def test_the_recording_still_matches_what_graphify_produces(self):
        """The fixture is a snapshot, and a snapshot rots. This is the canary: when graphify
        changes what it emits for this tree, the gate above is still passing against a graph
        nobody produces any more."""
        live = GraphifyBackend(self.tmp).build().graph
        self.assertEqual(self.pairs(live),
                         self.pairs(GraphifyBackend(self.tmp).translate(
                             self.data['graphify'])),
                         'recorded fixture has drifted from graphify %s — re-record it'
                         % self.data.get('graphify_version'))


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

    def test_the_mapping_covers_graphifys_own_dependency_vocabulary(self):
        """The authority for "is this relation a dependency?" is graphify, not us.

        `DEFAULT_AFFECTED_RELATIONS` is the vocabulary its own blast-radius traversal walks.
        Every name in it must map to one of our kinds — a name missing from our table is a
        dependency graphify would follow and we would silently drop.

        This exists because a hand-maintained table drifted within an hour of being written:
        four relations were removed from it on the strength of a grep that only matched
        `relation = "..."` assignments and could not see a tuple constant.
        """
        import ast

        text = graphify_module_source('graphify.affected')
        if text is None:
            self.skipTest('graphify.affected could not be read from its own interpreter')
        source = ast.parse(text)
        theirs = None
        for statement in ast.walk(source):
            if (isinstance(statement, ast.Assign)
                    and any(getattr(t, 'id', None) == 'DEFAULT_AFFECTED_RELATIONS'
                            for t in statement.targets)):
                theirs = {e.value for e in statement.value.elts
                          if isinstance(e, ast.Constant) and isinstance(e.value, str)}
        self.assertTrue(theirs, 'could not read DEFAULT_AFFECTED_RELATIONS')

        unmapped = sorted(r for r in theirs if backend_graphify.RELATIONS.get(r) is None)
        self.assertEqual(unmapped, [],
                         'graphify walks these as dependencies and we drop them: %s'
                         % unmapped)

    def test_graphify_agrees_the_structural_relations_are_not_dependencies(self):
        """Independent confirmation of the three we drop: graphify's own traversal excludes
        them too, at affected.py's `not in ("method", "contains")` guard."""
        source = graphify_module_source('graphify.affected')
        if source is None:
            self.skipTest('graphify.affected could not be read from its own interpreter')
        self.assertIn('"method", "contains"', source)
        for structural in ('contains', 'method', 'rationale_for'):
            self.assertIsNone(backend_graphify.RELATIONS[structural])

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
