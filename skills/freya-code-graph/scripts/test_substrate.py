#!/usr/bin/env python3
"""Tests for the substrate contract and project settings (Track B Phase 1).

The contract's whole job is to make a backend's limits *visible*, so these tests are mostly
about what happens when something is missing, malformed or out of scope — the paths where the
old resolver returned a confident nothing.

Run: python test_substrate.py
"""

import json
import os
import shutil
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import settings as settings_mod  # noqa: E402
from substrate import (  # noqa: E402
    Coverage,
    Exclusions,
    RELATION_KINDS,
    conformance_errors,
    graph_metadata,
    is_internal,
    summarise_coverage,
    validate_graph,
)


class TestCoverage(unittest.TestCase):
    def cov(self, **kw):
        base = dict(languages=['python'], extensions=['.py'],
                    relations=['imports'], incremental=True)
        base.update(kw)
        return Coverage(**base)

    def test_extensions_are_normalised(self):
        c = self.cov(extensions=['py', '.TS', '.py'])
        self.assertEqual(c.extensions, ('.py', '.ts'))

    def test_relations_must_come_from_the_vocabulary(self):
        with self.assertRaises(ValueError) as ctx:
            self.cov(relations=['imports', 'teleports'])
        self.assertIn('teleports', str(ctx.exception))

    def test_relations_keep_vocabulary_order_not_input_order(self):
        """Two backends declaring the same set must serialise identically."""
        a = self.cov(relations=['calls', 'imports'])
        b = self.cov(relations=['imports', 'calls'])
        self.assertEqual(a.relations, b.relations)
        self.assertEqual(a.to_dict(), b.to_dict())

    def test_handles_is_extension_based_and_case_insensitive(self):
        c = self.cov(extensions=['.ts'])
        self.assertTrue(c.handles('src/App.TS'))
        self.assertFalse(c.handles('src/Main.java'))

    def test_blind_spots_counts_what_the_backend_cannot_read(self):
        """The measurement that distinguishes an empty repo from a blind backend."""
        c = self.cov(extensions=['.py'])
        spots = c.blind_spots([
            'a.py', 'b.py', 'Main.java', 'Other.java', 'Third.java', 'x.kt',
        ])
        self.assertEqual(spots, {'.java': 3, '.kt': 1})

    def test_blind_spots_is_empty_when_everything_is_covered(self):
        self.assertEqual(self.cov(extensions=['.py']).blind_spots(['a.py', 'b.py']), {})

    def test_extensionless_files_are_not_blind_spots(self):
        self.assertEqual(self.cov().blind_spots(['Makefile', 'LICENSE']), {})

    def test_round_trips_through_a_dict(self):
        c = self.cov(relations=['imports', 'calls'], incremental=False)
        self.assertEqual(Coverage.from_dict(c.to_dict()), c)

    def test_from_dict_rejects_junk_rather_than_raising(self):
        for junk in (None, [], 'nope', {'relations': ['teleports']}):
            self.assertIsNone(Coverage.from_dict(junk), junk)


class TestExclusions(unittest.TestCase):
    def test_a_directory_excludes_everything_beneath_it(self):
        ex = Exclusions(directories=['vendor', 'packages/legacy'])
        self.assertTrue(ex.excludes('vendor/lib.ts'))
        self.assertTrue(ex.excludes('packages/legacy/deep/mod.ts'))
        self.assertFalse(ex.excludes('packages/current/mod.ts'))

    def test_a_prefix_that_is_not_a_path_boundary_does_not_match(self):
        """`vendor` must not exclude `vendored-utils/`."""
        ex = Exclusions(directories=['vendor'])
        self.assertFalse(ex.excludes('vendored-utils/mod.ts'))

    def test_patterns_are_delegated_to_the_callers_matcher(self):
        """The contract does not own a second gitignore implementation.

        There were two once, with different semantics, and they disagreed.
        """
        seen = []

        def matcher(rel, patterns):
            seen.append((rel, tuple(patterns)))
            return rel.endswith('.log')

        ex = Exclusions(patterns=['*.log'], matcher=matcher)
        self.assertTrue(ex.excludes('build/out.log'))
        self.assertFalse(ex.excludes('src/a.ts'))
        self.assertEqual(seen[0], ('build/out.log', ('*.log',)))

    def test_no_matcher_means_patterns_are_inert_rather_than_guessed(self):
        ex = Exclusions(patterns=['*.log'])
        self.assertFalse(ex.excludes('build/out.log'))

    def test_separators_and_leading_slashes_are_normalised(self):
        ex = Exclusions(directories=['/vendor/'])
        self.assertTrue(ex.excludes('/vendor/lib.ts'))


class _Backend:
    """A minimal conforming backend, used to check the checker."""

    name = 'stub'

    def coverage(self):
        return Coverage(['python'], ['.py'], ['imports'], True)

    def available(self):
        return True

    def build(self, exclusions=None, non_interactive=False):
        return {}

    def update(self, exclusions=None, non_interactive=False):
        return {}


class TestConformance(unittest.TestCase):
    def test_a_conforming_backend_reports_no_errors(self):
        self.assertEqual(conformance_errors(_Backend()), [])

    def test_a_missing_method_is_reported(self):
        b = _Backend()
        del b.__class__.update
        try:
            self.assertTrue(any('update' in e for e in conformance_errors(b)))
        finally:
            _Backend.update = lambda self, exclusions=None, non_interactive=False: {}

    def test_a_name_that_is_not_filename_safe_is_rejected(self):
        """The name becomes graph.<name>.json (CD-17)."""
        b = _Backend()
        b.name = 'my backend/v2'
        self.assertTrue(any('filename-safe' in e for e in conformance_errors(b)))

    def test_a_backend_declaring_nothing_is_rejected(self):
        b = _Backend()
        b.coverage = lambda: Coverage([], [], [], False)
        self.assertTrue(any('never be selected' in e for e in conformance_errors(b)))

    def test_a_coverage_that_raises_is_reported_not_propagated(self):
        b = _Backend()

        def boom():
            raise RuntimeError('no')

        b.coverage = boom
        self.assertTrue(any('raised RuntimeError' in e for e in conformance_errors(b)))


class TestGraphValidation(unittest.TestCase):
    def graph(self, files, **meta):
        base = graph_metadata('homegrown', Coverage(['typescript'], ['.ts'], ['imports'], True))
        base.update(meta)
        return {'substrate': base, 'files': files}

    def test_a_well_formed_graph_validates(self):
        g = self.graph({
            'a.ts': {'imports': ['b.ts']},
            'b.ts': {'imports': []},
        })
        self.assertEqual(validate_graph(g), [])

    def test_an_edge_naming_no_file_is_a_contract_violation(self):
        """Obligation 2 inverted: unresolvable targets must carry the unresolved: prefix."""
        g = self.graph({'a.ts': {'imports': ['components/accessibility']}})
        errors = validate_graph(g)
        self.assertTrue(any('names no file' in e for e in errors), errors)

    def test_signal_prefixed_specifiers_are_not_edges(self):
        g = self.graph({'a.ts': {'imports': ['external:react', 'unresolved:./missing']}})
        self.assertEqual(validate_graph(g), [])

    def test_missing_substrate_metadata_is_reported(self):
        g = {'files': {'a.ts': {'imports': []}}}
        self.assertTrue(any('substrate' in e for e in validate_graph(g)))

    def test_a_file_outside_declared_coverage_is_reported(self):
        cov = Coverage(['typescript'], ['.ts'], ['imports'], True)
        g = self.graph({'Main.java': {'imports': []}})
        self.assertTrue(any('outside the declared coverage' in e
                            for e in validate_graph(g, cov)))

    def test_junk_shapes_are_reported_not_raised(self):
        for junk in ([], 'nope', {'files': 'nope'}, {'files': {'a.ts': 'nope'}}):
            self.assertTrue(validate_graph(junk), junk)


class TestMetadata(unittest.TestCase):
    def test_degradation_is_recorded_rather_than_inferred(self):
        """A thin graph must never be mistaken for a thin repo."""
        meta = graph_metadata(
            'homegrown', Coverage(['python'], ['.py'], ['imports'], True),
            degraded_from='graphify', degraded_reason='not installed')
        self.assertEqual(meta['degraded_from'], 'graphify')
        self.assertEqual(meta['degraded_reason'], 'not installed')

    def test_no_degradation_keys_when_the_chosen_backend_ran(self):
        meta = graph_metadata('homegrown', Coverage(['python'], ['.py'], ['imports'], True))
        self.assertNotIn('degraded_from', meta)

    def test_summarise_reports_blind_spots_against_files_on_disk(self):
        g = {
            'substrate': graph_metadata(
                'homegrown', Coverage(['python'], ['.py'], ['imports'], True)),
            'files': {'a.py': {'imports': ['b.py', 'external:os', 'unresolved:.x']},
                      'b.py': {'imports': []}},
        }
        summary = summarise_coverage(g, ['a.py', 'b.py', 'Main.java', 'App.kt'])
        self.assertEqual(summary['internal_edges'], 1)
        self.assertEqual(summary['unresolved_imports'], 1)
        self.assertEqual(summary['blind_spots'], {'.java': 1, '.kt': 1})


class TestIsInternal(unittest.TestCase):
    def test_signals_are_not_internal(self):
        self.assertFalse(is_internal('external:react'))
        self.assertFalse(is_internal('unresolved:./x'))
        self.assertFalse(is_internal(''))
        self.assertTrue(is_internal('src/a.ts'))


class TestSettings(unittest.TestCase):
    def mk(self, contents=None):
        d = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, d, ignore_errors=True)
        if contents is not None:
            kb = Path(d) / 'knowledge-base'
            kb.mkdir(parents=True, exist_ok=True)
            (kb / 'settings.json').write_text(contents, encoding='utf-8')
        return d

    def test_absent_file_yields_defaults_without_warning(self):
        s = settings_mod.load(self.mk())
        self.assertEqual(s.backend, 'auto')
        self.assertFalse(s.present)
        self.assertEqual(s.warnings, [])

    def test_a_configured_backend_is_read(self):
        s = settings_mod.load(self.mk('{"substrate": {"backend": "graphify"}}'))
        self.assertEqual(s.backend, 'graphify')
        self.assertTrue(s.present)

    def test_malformed_json_degrades_to_defaults_with_a_warning(self):
        """A build must not fail because configuration is broken — but it must say so."""
        s = settings_mod.load(self.mk('{not json'))
        self.assertEqual(s.backend, 'auto')
        self.assertTrue(s.warnings)

    def test_a_wrong_shaped_section_warns_rather_than_crashing(self):
        s = settings_mod.load(self.mk('{"substrate": "graphify"}'))
        self.assertEqual(s.backend, 'auto')
        self.assertTrue(any('must be an object' in w for w in s.warnings))

    def test_an_unknown_section_is_preserved_not_discarded(self):
        """Forward compatibility: an older freya must not eat a newer one's settings."""
        s = settings_mod.load(self.mk('{"docs": {"chunking": "structural"}}'))
        self.assertEqual(s.data['docs'], {'chunking': 'structural'})
        self.assertEqual(s.backend, 'auto')

    def test_an_empty_backend_string_falls_back_to_auto(self):
        s = settings_mod.load(self.mk('{"substrate": {"backend": "   "}}'))
        self.assertEqual(s.backend, 'auto')

    def test_write_then_load_round_trips(self):
        d = self.mk()
        path = settings_mod.write(d, {'substrate': {'backend': 'homegrown'}})
        self.assertTrue(os.path.exists(path))
        self.assertEqual(settings_mod.load(d).backend, 'homegrown')

    def test_settings_live_beside_specs_not_inside_the_gitignored_cache(self):
        """CD-15: committed and travelling with the repo, not in .graph/."""
        path = settings_mod.settings_path('/proj')
        self.assertEqual(Path(path).parent.name, 'knowledge-base')
        self.assertNotIn('.graph', path)


if __name__ == '__main__':
    unittest.main(verbosity=2)
