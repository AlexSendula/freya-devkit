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
import graph_ops  # noqa: E402
import settings as settings_mod  # noqa: E402
import substrate  # noqa: E402
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


class TestExclusionOverrides(unittest.TestCase):
    """A project must be able to declare something back *in* scope.

    Exclusions are assembled from defaults and from `.gitignore`, neither of which can
    know that this repository keeps real source where the convention says it should not.
    Without overrides the resolver's escape hatch would be undone one layer up: the CLI
    passes these exclusions back into `build()`, so a directory the project had just
    declared source would be filtered out again a step later.
    """

    def test_an_override_beats_a_pattern(self):
        def matcher(rel, patterns):
            return rel.startswith('generated/')

        ex = Exclusions(patterns=['generated/'], matcher=matcher,
                        overrides=['generated'])
        self.assertFalse(ex.excludes('generated/api/client.ts'))

    def test_an_override_beats_a_directory(self):
        ex = Exclusions(directories=['docs'], overrides=['docs'])
        self.assertFalse(ex.excludes('docs/literate/engine.ts'))

    def test_a_deeper_exclusion_still_wins_inside_an_override(self):
        ex = Exclusions(directories=['docs/literate/legacy'],
                        overrides=['docs/literate'])
        self.assertFalse(ex.excludes('docs/literate/engine.ts'))
        self.assertTrue(ex.excludes('docs/literate/legacy/old.ts'))

    def test_an_override_does_not_leak_past_a_path_boundary(self):
        ex = Exclusions(directories=['docsite'], overrides=['docs'])
        self.assertTrue(ex.excludes('docsite/bundle.js'))

    def test_the_deepest_override_governs(self):
        """`packages/` declared source must not resurrect an excluded member that a
        narrower override says nothing about."""
        ex = Exclusions(directories=['packages/legacy'],
                        overrides=['packages', 'packages/ui'])
        self.assertFalse(ex.excludes('packages/ui/card.tsx'))
        self.assertTrue(ex.excludes('packages/legacy/old.tsx'))

    def test_overrides_are_absent_from_metadata_when_unused(self):
        """A graph from a project that overrode nothing stays byte-identical to one
        written before overrides existed."""
        self.assertNotIn('overrides', Exclusions(directories=['vendor']).to_dict())
        self.assertEqual(Exclusions(overrides=['docs']).to_dict()['overrides'], ['docs'])


class _Backend:
    """A minimal conforming backend, used to check the checker."""

    name = 'stub'
    # The contract persists the graph, so it has to know where to put it.
    project_dir = '/tmp/stub-project'

    def coverage(self):
        return Coverage(['python'], ['.py'], ['imports'], True)

    def available(self):
        return True

    def build(self, exclusions=None, non_interactive=False, selection_metadata=None):
        return {}

    def update(self, exclusions=None, non_interactive=False, selection_metadata=None):
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

    def test_a_backend_that_cannot_say_where_it_lives_is_rejected(self):
        """The contract writes the artifacts, so it has to know where.

        Every backend is already constructed with a project directory — the registry
        passes one to the factory — so this only requires it to keep it.
        """
        b = _Backend()
        b.project_dir = ''
        self.assertTrue(any('project_dir' in e for e in conformance_errors(b)))

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

    def test_a_backend_the_caller_cannot_actually_call_is_rejected(self):
        """"Callable" is not a contract.

        This exact stub passed conformance and then crashed the CLI with an unexpected
        keyword. A check that green-lights something the only caller cannot invoke is
        checking the wrong thing.
        """
        b = _Backend()
        b.build = lambda exclusions=None: {}
        errors = conformance_errors(b)
        self.assertTrue(any('cannot be called as the contract calls it' in e
                            for e in errors), errors)

    def test_a_backend_taking_kwargs_is_accepted(self):
        b = _Backend()
        b.build = lambda **kw: {}
        b.update = lambda **kw: {}
        self.assertEqual(conformance_errors(b), [])

    def test_the_shipped_backend_satisfies_its_own_contract(self):
        """The floor has to pass the check every other backend is held to."""
        import tempfile as _tf
        from graph_ops import CodeGraph
        d = _tf.mkdtemp()
        self.addCleanup(shutil.rmtree, d, ignore_errors=True)
        self.assertEqual(conformance_errors(CodeGraph(d)), [])


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
        graph_ops.run_build(g, non_interactive=True)
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
        graph_ops.run_build(CodeGraph(d), non_interactive=True)
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
        graph_ops.run_build(g, non_interactive=True, exclusions=Exclusions(directories=['thirdparty']))
        self.assertEqual(set(g.graph['files']), {'src/a.ts'})

    def test_the_exclusions_it_used_are_recorded_in_the_graph(self):
        from graph_ops import CodeGraph
        d = self.mk({'src/a.ts': 'export const a = 1\n'})
        g = CodeGraph(d)
        graph_ops.run_build(g, non_interactive=True, exclusions=Exclusions(directories=['vendor']))
        self.assertIn('vendor', g.graph['substrate']['exclusions']['directories'])


class TestTheRunnerSurvivesAHostileBackend(unittest.TestCase):
    """The contract exists because the *second* backend will not be this repo's.

    Phase 1's review proved the point by building one: it satisfied every documented
    obligation, then crashed twice and exited 0 having written nothing. So the runner is
    tested against outputs the shipped backend would never produce.
    """

    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)

    def backend(self, result):
        class B(_Backend):
            project_dir = self.tmp

            def build(self, exclusions=None, non_interactive=False,
                      selection_metadata=None):
                return result
        return B()

    def test_up_to_date_with_no_graph_writes_nothing_rather_than_crashing(self):
        """`Result` permits it, so eventually something will do it. Testing staleness before
        checking for a graph would try to stamp a version onto None."""
        out = graph_ops.run_build(
            self.backend(substrate.Result(None, substrate.Result.UP_TO_DATE, 0)))
        self.assertEqual(out["status"], "up_to_date")
        self.assertFalse(os.path.exists(
            os.path.join(self.tmp, "knowledge-base", ".graph", "graph.json")))

    def test_a_non_dict_substrate_block_does_not_turn_a_diagnostic_into_a_crash(self):
        """This graph is already broken — that is what the branch is reporting. Indexing
        whatever the backend put in `substrate` would replace the report with a traceback."""
        out = graph_ops.run_build(self.backend(substrate.Result({
            "version": substrate.GRAPH_SCHEMA_VERSION,
            "substrate": "not a dict",
            "files": {"a.py": {"imports": [{"to": "gone.py", "kind": "imports",
                                            "provenance": "extracted"}],
                               "dependents": []}},
        })))
        self.assertEqual(out["files_scanned"], 1)
        written = json.load(open(os.path.join(
            self.tmp, "knowledge-base", ".graph", "graph.json"), encoding="utf-8"))
        self.assertGreaterEqual(written["substrate"]["validation"]["error_count"], 1)

    def test_a_backend_returning_a_bare_dict_is_rejected_by_name(self):
        """The old return type. It must fail loudly, not be half-understood."""
        with self.assertRaises(TypeError) as ctx:
            graph_ops.run_build(self.backend({"files": {}}))
        self.assertIn("substrate.Result", str(ctx.exception))

    def test_a_dangling_edge_is_recorded_in_the_artifact_not_only_on_stderr(self):
        out = graph_ops.run_build(self.backend(substrate.Result({
            "version": substrate.GRAPH_SCHEMA_VERSION,
            "substrate": graph_metadata("stub", Coverage(["python"], [".py"],
                                                         ["imports"], True)),
            "files": {"a.py": {"imports": [{"to": "gone.py", "kind": "imports",
                                            "provenance": "extracted"}],
                               "dependents": []}},
        })))
        written = json.load(open(out["cached_to"], encoding="utf-8"))
        self.assertIn("names no file in the graph",
                      written["substrate"]["validation"]["errors"][0])


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
        graph_ops.run_build(CodeGraph(d), non_interactive=True)
        self.assertTrue((Path(d) / 'knowledge-base' / '.graph' / 'graph.homegrown.json').exists())

    def test_graph_json_remains_the_active_graph(self):
        """Three other skills read graph.json directly; Phase 1 changes nothing for them."""
        from graph_ops import CodeGraph
        d = self.mk({'src/a.ts': 'export const a = 1\n'})
        graph_ops.run_build(CodeGraph(d), non_interactive=True)
        gdir = Path(d) / 'knowledge-base' / '.graph'
        active = json.loads((gdir / 'graph.json').read_text(encoding='utf-8'))
        per_backend = json.loads((gdir / 'graph.homegrown.json').read_text(encoding='utf-8'))
        self.assertEqual(active['files'], per_backend['files'])

    def test_the_per_backend_artifact_is_gitignored(self):
        from graph_ops import CodeGraph
        d = self.mk({'src/a.ts': 'export const a = 1\n'})
        graph_ops.run_build(CodeGraph(d), non_interactive=True)
        gi = (Path(d) / 'knowledge-base' / '.graph' / '.gitignore').read_text(encoding='utf-8')
        self.assertIn('graph.*.json', gi)

    def test_behavior_json_is_still_not_ignored(self):
        """ADR-017: it is the one artifact that cannot be rebuilt from source."""
        from graph_ops import CodeGraph
        d = self.mk({'src/a.ts': 'export const a = 1\n'})
        graph_ops.run_build(CodeGraph(d), non_interactive=True)
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
        graph_ops.run_build(CodeGraph(d), non_interactive=True)
        self.commit(d, env, 'src/b.ts', 'export const b = 1\n')
        g = CodeGraph(d)
        graph_ops.run_update(g, non_interactive=True)
        self.assertEqual(g.graph['substrate']['backend'], 'homegrown')
        self.assertEqual(validate_graph(g.graph), [])

    def test_update_does_not_re_admit_an_excluded_file(self):
        from graph_ops import CodeGraph
        d, env = self.repo({
            '.gitignore': 'ignored/\n',
            'src/a.ts': 'export const a = 1\n',
        })
        graph_ops.run_build(CodeGraph(d), non_interactive=True)
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
        graph_ops.run_update(g, non_interactive=True)
        self.assertNotIn('ignored/x.ts', g.graph['files'])

    def test_update_refreshes_the_per_backend_artifact(self):
        from graph_ops import CodeGraph
        d, env = self.repo({'src/a.ts': 'export const a = 1\n'})
        graph_ops.run_build(CodeGraph(d), non_interactive=True)
        self.commit(d, env, 'src/b.ts', 'export const b = 1\n')
        graph_ops.run_update(CodeGraph(d), non_interactive=True)
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

    def build(self, exclusions=None, non_interactive=False, selection_metadata=None):
        return {}

    def update(self, exclusions=None, non_interactive=False, selection_metadata=None):
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

    def test_auto_is_the_floor_even_when_another_backend_would_read_more(self):
        """A substrate swap is a decision, not a side effect of installing something.

        This used to score the installed backends and pick the widest, which would have meant
        that putting a binary anywhere on PATH silently changed the substrate — and therefore
        every blast radius — for every project on the machine at once, with no diff. Spec §11
        mitigates the zero-install risk with *graphify is opt-in*, and CD-13 requires a
        substrate change to be a measured migration.

        Not hypothetical: measured on this repository, graphify scored 63 to homegrown's 58
        and would have taken over on the next build.
        """
        import backends
        d = self.mk()  # no settings file at all -> auto
        sel = backends.select(
            d, present_extensions={'.java': 40, '.ts': 2},
            registry=self.registry(graphify=lambda p: _FakeBackend()))
        self.assertEqual(sel.backend.name, 'homegrown')
        self.assertFalse(sel.degraded)

    def test_auto_says_what_it_is_leaving_on_the_table(self):
        """Opt-in must not mean undiscoverable. The one thing a project cannot work out for
        itself is which of its files another backend would have read."""
        import backends
        d = self.mk()
        sel = backends.select(
            d, present_extensions={'.java': 40, '.ts': 2},
            registry=self.registry(graphify=lambda p: _FakeBackend()))
        hint = ' '.join(sel.warnings)
        self.assertIn('graphify', hint)
        self.assertIn('.java', hint)
        self.assertIn('40', hint)
        self.assertIn('substrate.backend', hint)
        self.assertNotIn('.ts', hint)   # the floor already reads those

    def test_auto_stays_quiet_when_there_is_nothing_to_offer(self):
        import backends
        d = self.mk()
        sel = backends.select(
            d, present_extensions={'.ts': 10},
            registry=self.registry(graphify=lambda p: _FakeBackend(extensions=('.ts',))))
        self.assertEqual(sel.backend.name, 'homegrown')
        self.assertEqual(sel.warnings, [])

    def test_naming_a_backend_is_the_opt_in(self):
        import backends
        d = self.mk('{"substrate": {"backend": "graphify"}}')
        sel = backends.select(
            d, present_extensions={'.java': 40},
            registry=self.registry(graphify=lambda p: _FakeBackend()))
        self.assertEqual(sel.backend.name, 'graphify')
        self.assertFalse(sel.degraded)

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


class TestUpgradePathForAlreadyOnboardedProjects(unittest.TestCase):
    """A new artifact has to become ignored on projects that already have a .gitignore.

    `_write_cache_gitignore` only rewrote the legacy blanket `*`, so every project that had
    ever run a build kept its old list — and CD-17's `graph.<backend>.json`, added on top, was
    left committable. Measured before the fix: `git add -A` staged graph.homegrown.json.
    """

    def mk(self, existing_gitignore=None):
        d = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, d, ignore_errors=True)
        (Path(d) / 'src').mkdir(parents=True, exist_ok=True)
        (Path(d) / 'src' / 'a.ts').write_text('export const a = 1\n', encoding='utf-8')
        if existing_gitignore is not None:
            gdir = Path(d) / 'knowledge-base' / '.graph'
            gdir.mkdir(parents=True, exist_ok=True)
            (gdir / '.gitignore').write_text(existing_gitignore, encoding='utf-8')
        return d

    def _lines(self, d):
        text = (Path(d) / 'knowledge-base' / '.graph' / '.gitignore').read_text(encoding='utf-8')
        return [ln.strip() for ln in text.splitlines()
                if ln.strip() and not ln.startswith('#')]

    def test_a_previous_version_of_our_own_file_is_upgraded(self):
        from graph_ops import CodeGraph, CACHE_IGNORED
        d = self.mk('# Generated code-graph cache — do not commit.\n'
                    'graph.json\nclassifications.json\n')
        graph_ops.run_build(CodeGraph(d), non_interactive=True)
        self.assertEqual(self._lines(d), list(CACHE_IGNORED))

    def test_the_intermediate_version_is_also_upgraded(self):
        from graph_ops import CodeGraph, CACHE_IGNORED
        d = self.mk('graph.json\ngraph.*.json\nclassifications.json\n')
        graph_ops.run_build(CodeGraph(d), non_interactive=True)
        self.assertEqual(self._lines(d), list(CACHE_IGNORED))

    def test_the_legacy_blanket_is_still_upgraded(self):
        from graph_ops import CodeGraph, CACHE_IGNORED
        d = self.mk('# Generated code-graph cache — do not commit\n*\n')
        graph_ops.run_build(CodeGraph(d), non_interactive=True)
        self.assertEqual(self._lines(d), list(CACHE_IGNORED))

    def test_a_hand_edited_file_is_still_left_alone(self):
        """The property the early-return existed to protect, which must survive."""
        from graph_ops import CodeGraph
        d = self.mk('graph.json\nclassifications.json\nmy-own-thing.json\n')
        graph_ops.run_build(CodeGraph(d), non_interactive=True)
        self.assertIn('my-own-thing.json', self._lines(d))

    def test_every_artifact_the_build_writes_is_ignored(self):
        """The invariant behind all of the above, asserted against real git."""
        import subprocess
        from graph_ops import CodeGraph
        d = self.mk('graph.json\nclassifications.json\n')
        graph_ops.run_build(CodeGraph(d), non_interactive=True)
        env = dict(os.environ, GIT_AUTHOR_NAME='t', GIT_AUTHOR_EMAIL='t@t',
                   GIT_COMMITTER_NAME='t', GIT_COMMITTER_EMAIL='t@t')
        subprocess.run(['git', 'init', '-q'], cwd=d, env=env, check=True, capture_output=True)
        subprocess.run(['git', 'add', '-A'], cwd=d, env=env, check=True, capture_output=True)
        staged = subprocess.run(['git', 'diff', '--cached', '--name-only'], cwd=d, env=env,
                                capture_output=True, text=True).stdout.split()
        leaked = [p for p in staged if p.startswith('knowledge-base/.graph/')
                  and not p.endswith('.gitignore')]
        self.assertEqual(leaked, [])


class TestDegradationReachesTheArtifact(unittest.TestCase):
    """Spec §2.2: selection is never silent. stderr is not the artifact.

    A graph read a week later has to say it came from a fallback, or a thin graph is
    indistinguishable from a thin repo — the exact confusion this initiative exists to remove.
    """

    def mk(self, settings_json):
        d = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, d, ignore_errors=True)
        (Path(d) / 'src').mkdir(parents=True, exist_ok=True)
        (Path(d) / 'src' / 'a.ts').write_text('export const a = 1\n', encoding='utf-8')
        kb = Path(d) / 'knowledge-base'
        kb.mkdir(parents=True, exist_ok=True)
        (kb / 'settings.json').write_text(settings_json, encoding='utf-8')
        return d

    def test_a_degraded_build_records_it_in_the_graph(self):
        from graph_ops import CodeGraph
        d = self.mk('{"substrate": {"backend": "graphify"}}')
        g = CodeGraph(d)
        graph_ops.run_build(g, non_interactive=True,
                selection_metadata={'degraded_from': 'graphify', 'degraded_reason': 'x'})
        self.assertEqual(g.graph['substrate']['degraded_from'], 'graphify')

    def test_an_undegraded_build_says_nothing(self):
        from graph_ops import CodeGraph
        d = self.mk('{"substrate": {"backend": "homegrown"}}')
        g = CodeGraph(d)
        graph_ops.run_build(g, non_interactive=True)
        self.assertNotIn('degraded_from', g.graph['substrate'])


class TestClearRemovesEveryArtifact(unittest.TestCase):
    """CD-17 added a second file; --clear was not told about it.

    A leftover graph.<backend>.json is worse than a stale graph.json, because nothing reports
    it and it looks current.
    """

    def test_clear_removes_the_per_backend_copy_too(self):
        from graph_ops import CodeGraph
        d = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, d, ignore_errors=True)
        (Path(d) / 'src').mkdir(parents=True, exist_ok=True)
        (Path(d) / 'src' / 'a.ts').write_text('export const a = 1\n', encoding='utf-8')
        graph_ops.run_build(CodeGraph(d), non_interactive=True)
        gdir = Path(d) / 'knowledge-base' / '.graph'
        self.assertTrue((gdir / 'graph.homegrown.json').exists())
        CodeGraph(d).clear()
        self.assertFalse((gdir / 'graph.json').exists())
        self.assertFalse((gdir / 'graph.homegrown.json').exists())


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
