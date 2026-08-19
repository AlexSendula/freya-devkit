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


class TestHomegrownIsAConformingBackend(unittest.TestCase):
    """Phase 1's actual deliverable: the shipped resolver, behind the contract.

    An interface with one implementation is fiction, so the point of these is not that they
    pass — it is that they are the same assertions graphify will have to pass in Phase 2.
    """

    def mk(self, files):
        d = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, d, ignore_errors=True)
        for rel, content in files.items():
            p = Path(d) / rel
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_text(content, encoding='utf-8')
        return d

    def graph_of(self, files):
        from graph_ops import CodeGraph
        g = CodeGraph(self.mk(files))
        g.build(non_interactive=True)
        return g

    def test_it_satisfies_the_contract(self):
        from graph_ops import CodeGraph
        self.assertEqual(conformance_errors(CodeGraph(self.mk({}))), [])

    def test_it_is_always_available(self):
        """The floor exists for the machine that cannot install anything."""
        from graph_ops import CodeGraph
        self.assertTrue(CodeGraph(self.mk({})).available())

    def test_its_coverage_names_the_languages_it_parses(self):
        from graph_ops import CodeGraph
        cov = CodeGraph(self.mk({})).coverage()
        self.assertEqual(set(cov.languages),
                         {'typescript', 'javascript', 'python', 'go'})
        self.assertIn('.tsx', cov.extensions)
        self.assertIn('imports', cov.relations)

    def test_it_declares_only_the_relations_it_actually_emits(self):
        """It resolves imports. It does not do symbols, so it must not claim calls."""
        from graph_ops import CodeGraph
        cov = CodeGraph(self.mk({})).coverage()
        self.assertNotIn('calls', cov.relations)
        self.assertNotIn('inherits', cov.relations)

    def test_a_built_graph_validates_against_the_contract(self):
        g = self.graph_of({
            'src/a.ts': "import { b } from './b'\n",
            'src/b.ts': 'export const b = 1\n',
        })
        self.assertEqual(validate_graph(g.graph), [])

    def test_a_built_graph_carries_its_substrate_block(self):
        g = self.graph_of({'src/a.ts': 'export const a = 1\n'})
        substrate = g.graph['substrate']
        self.assertEqual(substrate['backend'], 'homegrown')
        self.assertIsNotNone(Coverage.from_dict(substrate['coverage']))

    def test_the_substrate_block_survives_a_write_and_reload(self):
        from graph_ops import CodeGraph
        d = self.mk({'src/a.ts': 'export const a = 1\n'})
        CodeGraph(d).build(non_interactive=True)
        reloaded = CodeGraph(d).load()
        self.assertEqual(reloaded['substrate']['backend'], 'homegrown')

    def test_blind_spots_distinguish_an_empty_repo_from_a_blind_backend(self):
        """The question freya could not answer, and why a Java repo read as greenfield."""
        g = self.graph_of({
            'src/a.ts': 'export const a = 1\n',
            'Main.java': 'class Main {}\n',
            'Other.java': 'class Other {}\n',
        })
        summary = summarise_coverage(g.graph, ['src/a.ts', 'Main.java', 'Other.java'])
        self.assertEqual(summary['blind_spots'], {'.java': 2})
        self.assertEqual(summary['backend'], 'homegrown')

    def test_exclusions_are_an_input_the_caller_can_supply(self):
        """Obligation 6: `vendor/ is not mine` is a project fact, not a backend opinion."""
        from graph_ops import CodeGraph
        d = self.mk({
            'src/a.ts': 'export const a = 1\n',
            'thirdparty/b.ts': 'export const b = 1\n',
        })
        g = CodeGraph(d)
        g.build(non_interactive=True, exclusions=Exclusions(directories=['thirdparty']))
        self.assertEqual(set(g.graph['files']), {'src/a.ts'})

    def test_the_exclusions_it_used_are_recorded_in_the_graph(self):
        from graph_ops import CodeGraph
        d = self.mk({'src/a.ts': 'export const a = 1\n'})
        g = CodeGraph(d)
        g.build(non_interactive=True, exclusions=Exclusions(directories=['vendor']))
        self.assertIn('vendor', g.graph['substrate']['exclusions']['directories'])


class TestPerBackendArtifacts(unittest.TestCase):
    """CD-17. A substrate swap has to be diffable, so the previous graph must survive it."""

    def mk(self, files):
        d = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, d, ignore_errors=True)
        for rel, content in files.items():
            p = Path(d) / rel
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_text(content, encoding='utf-8')
        return d

    def test_a_build_writes_the_per_backend_artifact(self):
        from graph_ops import CodeGraph
        d = self.mk({'src/a.ts': 'export const a = 1\n'})
        CodeGraph(d).build(non_interactive=True)
        self.assertTrue((Path(d) / 'knowledge-base' / '.graph' / 'graph.homegrown.json').exists())

    def test_graph_json_remains_the_active_graph(self):
        """Three other skills read graph.json directly; Phase 1 changes nothing for them."""
        from graph_ops import CodeGraph
        d = self.mk({'src/a.ts': 'export const a = 1\n'})
        CodeGraph(d).build(non_interactive=True)
        gdir = Path(d) / 'knowledge-base' / '.graph'
        active = json.loads((gdir / 'graph.json').read_text(encoding='utf-8'))
        per_backend = json.loads((gdir / 'graph.homegrown.json').read_text(encoding='utf-8'))
        self.assertEqual(active['files'], per_backend['files'])

    def test_the_per_backend_artifact_is_gitignored(self):
        from graph_ops import CodeGraph
        d = self.mk({'src/a.ts': 'export const a = 1\n'})
        CodeGraph(d).build(non_interactive=True)
        gi = (Path(d) / 'knowledge-base' / '.graph' / '.gitignore').read_text(encoding='utf-8')
        self.assertIn('graph.*.json', gi)

    def test_behavior_json_is_still_not_ignored(self):
        """ADR-017: it is the one artifact that cannot be rebuilt from source."""
        from graph_ops import CodeGraph
        d = self.mk({'src/a.ts': 'export const a = 1\n'})
        CodeGraph(d).build(non_interactive=True)
        gi = (Path(d) / 'knowledge-base' / '.graph' / '.gitignore').read_text(encoding='utf-8')
        self.assertNotIn('behavior.json\n', gi.replace('# behavior.json', ''))


class TestIncrementalUpdateHonoursTheContract(unittest.TestCase):
    """`--update` is the steady-state command, so the contract has to hold on it too.

    It re-parsed whatever `git diff` named and wrote it straight into the graph, consulting
    neither the exclusion rules nor the classifications — so a single commit touching an
    ignored tree quietly re-admitted files `--build` had excluded, and the substrate block
    disappeared on the first incremental run after a build.
    """

    def repo(self, files):
        import subprocess
        d = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, d, ignore_errors=True)
        for rel, content in files.items():
            p = Path(d) / rel
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_text(content, encoding='utf-8')
        env = dict(os.environ, GIT_AUTHOR_NAME='t', GIT_AUTHOR_EMAIL='t@t',
                   GIT_COMMITTER_NAME='t', GIT_COMMITTER_EMAIL='t@t')
        for cmd in (['init', '-q'], ['add', '-A'], ['commit', '-qm', 'one']):
            subprocess.run(['git'] + cmd, cwd=d, env=env, check=True,
                           capture_output=True)
        return d, env

    def commit(self, d, env, rel, content):
        import subprocess
        p = Path(d) / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(content, encoding='utf-8')
        subprocess.run(['git', 'add', '-A'], cwd=d, env=env, check=True, capture_output=True)
        subprocess.run(['git', 'commit', '-qm', 'two'], cwd=d, env=env, check=True,
                       capture_output=True)

    def test_update_keeps_the_substrate_block(self):
        from graph_ops import CodeGraph
        d, env = self.repo({'src/a.ts': 'export const a = 1\n'})
        CodeGraph(d).build(non_interactive=True)
        self.commit(d, env, 'src/b.ts', 'export const b = 1\n')
        g = CodeGraph(d)
        g.update(non_interactive=True)
        self.assertEqual(g.graph['substrate']['backend'], 'homegrown')
        self.assertEqual(validate_graph(g.graph), [])

    def test_update_does_not_re_admit_an_excluded_file(self):
        from graph_ops import CodeGraph
        d, env = self.repo({
            '.gitignore': 'ignored/\n',
            'src/a.ts': 'export const a = 1\n',
        })
        CodeGraph(d).build(non_interactive=True)
        # -f because the tree is gitignored; the point is that a commit touching it must
        # still not put it in the graph.
        import subprocess
        p = Path(d) / 'ignored' / 'x.ts'
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text('export const x = 1\n', encoding='utf-8')
        subprocess.run(['git', 'add', '-f', '-A'], cwd=d, env=env, check=True,
                       capture_output=True)
        subprocess.run(['git', 'commit', '-qm', 'two'], cwd=d, env=env, check=True,
                       capture_output=True)
        g = CodeGraph(d)
        g.update(non_interactive=True)
        self.assertNotIn('ignored/x.ts', g.graph['files'])

    def test_update_refreshes_the_per_backend_artifact(self):
        from graph_ops import CodeGraph
        d, env = self.repo({'src/a.ts': 'export const a = 1\n'})
        CodeGraph(d).build(non_interactive=True)
        self.commit(d, env, 'src/b.ts', 'export const b = 1\n')
        CodeGraph(d).update(non_interactive=True)
        per_backend = json.loads(
            (Path(d) / 'knowledge-base' / '.graph' / 'graph.homegrown.json')
            .read_text(encoding='utf-8'))
        self.assertIn('src/b.ts', per_backend['files'])


class _FakeBackend:
    """A stand-in second backend.

    An interface with one implementation is fiction (spec §2.2), and Phase 2's graphify does
    not exist yet — so selection is proved against something that is not the incumbent.
    """

    def __init__(self, name='graphify', available=True, extensions=('.java', '.kt', '.ts')):
        self.name = name
        self._available = available
        self._extensions = extensions

    def coverage(self):
        return Coverage(['java', 'kotlin', 'typescript'], self._extensions, ['imports'], True)

    def available(self):
        return self._available

    def build(self, exclusions=None, non_interactive=False):
        return {}

    def update(self, exclusions=None, non_interactive=False):
        return {}


class TestBackendSelection(unittest.TestCase):
    """CD-15, and spec §2.2's rule that selection is never silent."""

    def mk(self, settings_json=None):
        d = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, d, ignore_errors=True)
        if settings_json is not None:
            kb = Path(d) / 'knowledge-base'
            kb.mkdir(parents=True, exist_ok=True)
            (kb / 'settings.json').write_text(settings_json, encoding='utf-8')
        return d

    def registry(self, **extra):
        import graph_ops
        reg = {'homegrown': lambda p: graph_ops.CodeGraph(p)}
        reg.update(extra)
        return reg

    def test_default_is_the_floor_when_nothing_else_is_registered(self):
        import backends
        sel = backends.select(self.mk(), registry=self.registry())
        self.assertEqual(sel.backend.name, 'homegrown')
        self.assertFalse(sel.degraded)

    def test_a_named_backend_is_honoured(self):
        import backends
        d = self.mk('{"substrate": {"backend": "graphify"}}')
        sel = backends.select(d, registry=self.registry(graphify=lambda p: _FakeBackend()))
        self.assertEqual(sel.backend.name, 'graphify')
        self.assertFalse(sel.degraded)

    def test_an_unavailable_backend_degrades_to_the_floor_and_says_so(self):
        import backends
        d = self.mk('{"substrate": {"backend": "graphify"}}')
        sel = backends.select(
            d, registry=self.registry(graphify=lambda p: _FakeBackend(available=False)))
        self.assertEqual(sel.backend.name, 'homegrown')
        self.assertTrue(sel.degraded)
        self.assertEqual(sel.degraded_from, 'graphify')
        self.assertIn('graphify', sel.describe())

    def test_an_unknown_backend_degrades_rather_than_failing_the_run(self):
        import backends
        d = self.mk('{"substrate": {"backend": "nonesuch"}}')
        sel = backends.select(d, registry=self.registry())
        self.assertEqual(sel.backend.name, 'homegrown')
        self.assertEqual(sel.degraded_from, 'nonesuch')

    def test_degradation_reaches_the_graph_metadata(self):
        """A thin graph must never be mistaken for a thin repo."""
        import backends
        d = self.mk('{"substrate": {"backend": "graphify"}}')
        sel = backends.select(
            d, registry=self.registry(graphify=lambda p: _FakeBackend(available=False)))
        meta = sel.metadata()
        self.assertEqual(meta['degraded_from'], 'graphify')
        self.assertTrue(meta['degraded_reason'])

    def test_auto_prefers_whichever_backend_reads_more_of_this_repo(self):
        import backends
        d = self.mk()  # no settings file at all -> auto
        sel = backends.select(
            d, present_extensions={'.java': 40, '.ts': 2},
            registry=self.registry(graphify=lambda p: _FakeBackend()))
        self.assertEqual(sel.backend.name, 'graphify')

    def test_auto_keeps_the_floor_when_it_reads_just_as_much(self):
        """Predictability: a tie must not depend on registration order."""
        import backends
        d = self.mk()
        sel = backends.select(
            d, present_extensions={'.ts': 10},
            registry=self.registry(graphify=lambda p: _FakeBackend(extensions=('.ts',))))
        self.assertEqual(sel.backend.name, 'homegrown')

    def test_a_backend_that_explodes_on_construction_is_simply_unavailable(self):
        import backends

        def boom(_):
            raise RuntimeError('bad install')

        sel = backends.select(self.mk('{"substrate": {"backend": "graphify"}}'),
                              registry=self.registry(graphify=boom))
        self.assertEqual(sel.backend.name, 'homegrown')
        self.assertTrue(sel.degraded)

    def test_settings_warnings_are_carried_to_the_caller(self):
        import backends
        sel = backends.select(self.mk('{not json'), registry=self.registry())
        self.assertTrue(sel.warnings)

    def test_the_extension_census_skips_dependency_trees(self):
        import backends
        d = self.mk()
        for rel in ('src/a.ts', 'src/b.ts', 'node_modules/pkg/c.ts', 'Main.java'):
            p = Path(d) / rel
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_text('x', encoding='utf-8')
        census = backends.extension_census(d)
        self.assertEqual(census.get('.ts'), 2)
        self.assertEqual(census.get('.java'), 1)


class TestTheTwoCacheGitignoreWritersAgree(unittest.TestCase):
    """`code-graph` and `behavior-graph` both write `.graph/.gitignore`.

    Whichever runs first wins, so if their content differs the file depends on run order —
    and one of them would keep rewriting the other's. The comment in each says they are kept
    identical; nothing checked it, and they had already drifted by the time this was written.
    """

    def _other(self):
        here = os.path.dirname(os.path.abspath(__file__))
        path = os.path.normpath(os.path.join(
            here, '..', '..', 'freya-behavior-graph', 'scripts', 'behavior_graph.py'))
        sys.path.insert(0, os.path.dirname(path))
        import behavior_graph  # noqa: E402
        return behavior_graph

    def test_the_produced_file_content_is_identical(self):
        import graph_ops
        self.assertEqual(graph_ops.CACHE_GITIGNORE, self._other().CACHE_GITIGNORE)

    def test_the_ignored_names_are_identical(self):
        import graph_ops
        self.assertEqual(graph_ops.CACHE_IGNORED, self._other().CACHE_IGNORED)

    def test_behavior_json_is_ignored_by_neither(self):
        """ADR-017, asserted against the actual string rather than the intent."""
        import graph_ops
        for name in graph_ops.CACHE_IGNORED:
            self.assertNotEqual(name, 'behavior.json')
        body = [ln for ln in graph_ops.CACHE_GITIGNORE.splitlines()
                if ln.strip() and not ln.startswith('#')]
        self.assertNotIn('behavior.json', body)
        self.assertNotIn('*', body)


if __name__ == '__main__':
    unittest.main(verbosity=2)
