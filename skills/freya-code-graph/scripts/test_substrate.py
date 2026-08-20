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

    def test_an_override_does_not_re_admit_a_nested_artifact_tree(self):
        """The override overrules rules aimed *at it*, not rules about what is inside it.

        This returned False for every path under an override, so
        `{"directories": {"packages": "source"}}` on a workspaces tree pulled every
        `packages/*/node_modules/**` into the graph — the 50,000-file blast radius CD-21's
        two-tier design exists to prevent, reached through an ordinary ancestor verdict.
        Nothing could switch it back off either: the classifier does not descend into a
        directory whose ancestor carries a stated verdict, so no nested `exclude` is ever
        derived to catch it.
        """
        ex = Exclusions(directories=['node_modules', 'dist'],
                        patterns=['node_modules/', 'dist/', '*.min.js'],
                        matcher=graph_ops.gitignore_excludes,
                        overrides=['packages'])
        self.assertFalse(ex.excludes('packages/app/src/index.ts'))
        self.assertTrue(ex.excludes('packages/app/node_modules/lodash/index.js'))
        self.assertTrue(ex.excludes('packages/node_modules/lodash/index.js'))
        self.assertTrue(ex.excludes('packages/app/dist/bundle.js'))
        self.assertTrue(ex.excludes('packages/app/vendor.min.js'))

    def test_the_rule_the_override_exists_to_beat_still_loses(self):
        """A pattern naming the overridden directory itself must not survive as a tail.

        `docs/` in `.gitignore` is exactly what the override is for; matching it against
        the path below the override root is what makes it stop applying, rather than a
        special case that has to enumerate which patterns to skip.
        """
        ex = Exclusions(patterns=['docs/'], matcher=graph_ops.gitignore_excludes,
                        overrides=['docs'])
        self.assertFalse(ex.excludes('docs/literate/engine.ts'))


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

    def test_a_reverse_edge_that_lost_its_kind_is_reported(self):
        """The reverse-index check named this case and did not cover it.

        Both `dependents` checks could be deleted with the whole suite still green, which
        is the same "a guard nobody wired up" shape the contract's own validator was in
        before it acquired a caller.
        """
        g = self.graph({
            'a.ts': {'imports': [], 'dependents': [{'from': 'b.ts', 'provenance': 'extracted'}]},
            'b.ts': {'imports': [], 'dependents': []},
        })
        self.assertTrue(any('has kind' in e for e in validate_graph(g)), validate_graph(g))

    def test_a_reverse_edge_with_a_bad_provenance_is_reported(self):
        g = self.graph({
            'a.ts': {'imports': [],
                     'dependents': [{'from': 'b.ts', 'kind': 'imports', 'provenance': 'vibes'}]},
            'b.ts': {'imports': [], 'dependents': []},
        })
        self.assertTrue(any('has provenance' in e for e in validate_graph(g)))

    def test_a_reverse_edge_with_an_empty_symbol_is_reported(self):
        g = self.graph({
            'a.ts': {'imports': [],
                     'dependents': [{'from': 'b.ts', 'kind': 'calls',
                                     'provenance': 'extracted', 'to_symbol': '  '}]},
            'b.ts': {'imports': [], 'dependents': []},
        })
        self.assertTrue(any('not a symbol name' in e for e in validate_graph(g)))

    def test_a_legacy_string_dependent_is_still_accepted(self):
        """A v1 artifact keyed its dependents as bare strings. Refusing to read one is
        indistinguishable from a project with no dependencies."""
        g = self.graph({
            'a.ts': {'imports': [], 'dependents': ['b.ts']},
            'b.ts': {'imports': [], 'dependents': []},
        })
        self.assertEqual(validate_graph(g), [])


class TestTheReverseIndexIsDerived(unittest.TestCase):
    """`dependents` is a pure function of `imports`, rebuilt on every write.

    Both properties below were unguarded: `link_dependents`' reset could be weakened to
    `setdefault` and its symbol-copy loop deleted outright, with the whole suite still
    green — while the first leaves a dependent behind when the import justifying it is
    deleted, and the second collapses every symbol-refined edge between one file pair into
    byte-identical duplicates (measured: 322 of 417 entries on this repository).
    """

    def test_a_stale_dependent_does_not_survive_the_rebuild(self):
        graph = {'files': {
            'a.ts': {'imports': [substrate.make_edge('b.ts')], 'dependents': []},
            'b.ts': {'imports': [], 'dependents': [substrate.make_edge('gone.ts',
                                                                      reverse=True)]},
        }}
        substrate.link_dependents(graph)
        self.assertEqual([substrate.edge_other(e)
                          for e in graph['files']['b.ts']['dependents']], ['a.ts'])

    def test_the_reverse_edge_carries_the_forward_edges_symbols(self):
        forward = substrate.make_edge('b.ts', kind='calls', from_symbol='run',
                                      to_symbol='helper', line=12)
        graph = {'files': {'a.ts': {'imports': [forward]}, 'b.ts': {'imports': []}}}
        substrate.link_dependents(graph)
        reverse = graph['files']['b.ts']['dependents'][0]
        self.assertEqual(reverse['from'], 'a.ts')
        self.assertEqual(reverse['kind'], 'calls')
        self.assertEqual(substrate.edge_symbols(reverse), ('run', 'helper'))
        self.assertEqual(reverse['line'], 12)

    def test_two_symbol_edges_between_one_pair_stay_distinct_backwards(self):
        graph = {'files': {
            'a.ts': {'imports': [
                substrate.make_edge('b.ts', kind='calls', from_symbol='one', to_symbol='h'),
                substrate.make_edge('b.ts', kind='calls', from_symbol='two', to_symbol='h'),
            ]},
            'b.ts': {'imports': []},
        }}
        substrate.link_dependents(graph)
        dependents = graph['files']['b.ts']['dependents']
        self.assertEqual(len(dependents), 2)
        self.assertEqual(len({json.dumps(d, sort_keys=True) for d in dependents}), 2)

    def test_an_out_of_vocabulary_kind_is_validated_rather_than_raised(self):
        """Linking runs one line before validation, so raising here made the validator's
        own message — which names the file and the offending kind — unreachable."""
        graph = {
            'substrate': graph_metadata('x', Coverage(['typescript'], ['.ts'],
                                                      ['imports'], True)),
            'files': {'a.ts': {'imports': [{'to': 'b.ts', 'kind': 'mixes_in',
                                            'provenance': 'extracted'}]},
                      'b.ts': {'imports': []}},
        }
        substrate.link_dependents(graph)  # must not raise
        self.assertTrue(any('mixes_in' in e for e in validate_graph(graph)))


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


class MachineHome(unittest.TestCase):
    """Give this test its own empty machine-level home, and say so.

    `settings.load()` consults `~/.freya/settings.json`, which is real state outside the
    checkout. Any test asserting what happens "with nothing configured" is therefore asserting
    something about the machine it runs on unless it takes control — and the failure is the
    worst kind: green on a laptop that never answered the install question, red on one that
    did, for a reason nothing in the repository records.

    The root `conftest.py` sandboxes the whole session as a safety net, but it only applies
    when pytest's rootdir is the repository — running `pytest .` from inside `skills/` bypasses
    it, and did: ten tests failed against a real machine default. So the isolation lives with
    the tests that depend on it, where it is visible and cannot be routed around.
    """

    def setUp(self):
        self.home = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.home, ignore_errors=True)
        previous = os.environ.get(settings_mod.GLOBAL_ENV_VAR)
        os.environ[settings_mod.GLOBAL_ENV_VAR] = self.home
        self.addCleanup(self._restore_home, previous)

    @staticmethod
    def _restore_home(previous):
        if previous is None:
            os.environ.pop(settings_mod.GLOBAL_ENV_VAR, None)
        else:
            os.environ[settings_mod.GLOBAL_ENV_VAR] = previous


class TestSettings(MachineHome):
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


class TestTheMachineLevelDefault(MachineHome):
    """One answer, given once at install time, used by every project that has not decided.

    The alternative was asking mid-workflow, which cannot work: code-graph goes
    non-interactive whenever stdin is not a TTY, and that is every agent-driven run and every
    wrap-up run. So the question is asked where a human demonstrably is — `freya install` —
    and this is the layer that carries the answer to every project afterwards.
    """

    def project(self, contents=None):
        d = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, d, ignore_errors=True)
        if contents is not None:
            kb = Path(d) / 'knowledge-base'
            kb.mkdir(parents=True, exist_ok=True)
            (kb / 'settings.json').write_text(contents, encoding='utf-8')
        return d

    def set_global(self, text):
        Path(settings_mod.global_settings_path()).write_text(text, encoding='utf-8')

    # -- precedence --------------------------------------------------------

    def test_nothing_anywhere_is_the_floor(self):
        s = settings_mod.load(self.project())
        self.assertEqual(s.backend, 'auto')
        self.assertEqual(s.backend_source, settings_mod.SOURCE_DEFAULT)

    def test_the_machine_default_answers_a_project_that_has_not_decided(self):
        self.set_global('{"substrate": {"backend": "graphify"}}')
        s = settings_mod.load(self.project())
        self.assertEqual(s.backend, 'graphify')
        self.assertEqual(s.backend_source, settings_mod.SOURCE_GLOBAL)

    def test_a_project_that_has_decided_wins(self):
        self.set_global('{"substrate": {"backend": "graphify"}}')
        s = settings_mod.load(self.project('{"substrate": {"backend": "homegrown"}}'))
        self.assertEqual(s.backend, 'homegrown')
        self.assertEqual(s.backend_source, settings_mod.SOURCE_PROJECT)

    def test_an_explicit_auto_defers_to_the_machine(self):
        """`auto` is an answer — "keep following whatever the machine says" — and it is the
        one form of opting *in* that survives the machine changing its mind."""
        self.set_global('{"substrate": {"backend": "graphify"}}')
        s = settings_mod.load(self.project('{"substrate": {"backend": "auto"}}'))
        self.assertEqual(s.backend, 'graphify')
        self.assertTrue(s.decided)

    def test_absent_and_explicit_auto_are_different_answers(self):
        """Only the first is something to seed into. Collapsing them would rewrite a
        project's deliberate `auto` into a frozen name the next time anything built."""
        self.assertFalse(settings_mod.load(self.project('{}')).decided)
        self.assertTrue(
            settings_mod.load(self.project('{"substrate": {"backend": "auto"}}')).decided)

    def test_symbols_follow_the_same_layering(self):
        self.set_global('{"substrate": {"symbols": true}}')
        self.assertTrue(settings_mod.load(self.project()).symbols)
        self.assertFalse(
            settings_mod.load(self.project('{"substrate": {"symbols": false}}')).symbols)

    # -- what may live at machine level ------------------------------------

    def test_scope_is_never_a_machine_level_setting(self):
        """A global `directories` would apply to repositories nobody has looked at — and a
        global `node_modules: source` is a 50,000-file graph on every project on the machine.
        Scope is a fact about one project; a parser preference is a fact about the person."""
        self.set_global('{"directories": {"node_modules": "source"}}')
        s = settings_mod.load(self.project())
        self.assertEqual(s.directories, {})
        self.assertTrue(any('not a machine-level setting' in w for w in s.warnings))

    def test_an_unknown_substrate_key_is_reported_not_honoured(self):
        self.set_global('{"substrate": {"backend": "graphify", "excludes": ["x"]}}')
        s = settings_mod.load(self.project())
        self.assertEqual(s.backend, 'graphify')
        self.assertTrue(any('substrate.excludes' in w for w in s.warnings))

    def test_a_broken_machine_file_never_stops_a_project_building(self):
        self.set_global('{not json')
        s = settings_mod.load(self.project())
        self.assertEqual(s.backend, 'auto')
        self.assertTrue(s.warnings)

    # -- writing -----------------------------------------------------------

    def test_setting_a_backend_keeps_everything_else_in_the_file(self):
        d = self.project('{"directories": {"docs": "source"}}')
        settings_mod.set_backend('graphify', project_dir=d)
        s = settings_mod.load(d)
        self.assertEqual(s.backend, 'graphify')
        self.assertEqual(s.directories, {'docs': 'source'})

    def test_setting_the_machine_default_keeps_everything_else(self):
        self.set_global('{"substrate": {"symbols": true}}')
        settings_mod.set_backend('graphify', scope=settings_mod.SOURCE_GLOBAL)
        s = settings_mod.load(self.project())
        self.assertEqual(s.backend, 'graphify')
        self.assertTrue(s.symbols)

    def test_an_unparseable_project_file_is_not_silently_overwritten(self):
        d = self.project('{not json')
        with self.assertRaises(ValueError):
            settings_mod.set_backend('graphify', project_dir=d)

    # -- seeding -----------------------------------------------------------

    def test_seeding_writes_the_machine_answer_into_the_project(self):
        """This is what makes a machine default safe. Left implicit, the same commit graphs
        differently on a machine that has one and a machine that does not — and integration
        fingerprints come from the graph closure into behavior.json, which is committed."""
        self.set_global('{"substrate": {"backend": "graphify"}}')
        d = self.project()
        path = settings_mod.seed_project_backend(d)
        self.assertIsNotNone(path)
        self.assertEqual(json.loads(Path(path).read_text())['substrate']['backend'],
                         'graphify')

    def test_seeding_leaves_a_project_that_already_decided_alone(self):
        self.set_global('{"substrate": {"backend": "graphify"}}')
        d = self.project('{"substrate": {"backend": "homegrown"}}')
        self.assertIsNone(settings_mod.seed_project_backend(d))
        self.assertEqual(settings_mod.load(d).backend, 'homegrown')

    def test_seeding_does_not_freeze_a_deliberate_auto(self):
        self.set_global('{"substrate": {"backend": "graphify"}}')
        d = self.project('{"substrate": {"backend": "auto"}}')
        self.assertIsNone(settings_mod.seed_project_backend(d))

    def test_no_machine_answer_writes_nothing_at_all(self):
        """A headless run with nothing configured must not record the floor as though
        somebody chose it. A committed file naming a decision nobody made is the
        confidently-wrong failure this whole substrate exists to refuse."""
        d = self.project()
        self.assertIsNone(settings_mod.seed_project_backend(d))
        self.assertFalse(os.path.exists(settings_mod.settings_path(d)))

    def test_the_machine_home_is_overridable(self):
        """Without this the suite's own result would depend on whose laptop it ran on."""
        self.assertTrue(settings_mod.global_settings_path().startswith(self.home))


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


class TestBackendSelection(MachineHome):
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
        self.assertNotIn('.ts', hint)   # the floor already reads those
        # The runnable command, not a description of a file to hand-edit. This text is the
        # whole discovery path — there is deliberately nothing in the skill layer about
        # choosing a backend, because that would be read on every invocation to say nothing
        # on almost all of them.
        self.assertIn('--use graphify', hint)
        self.assertIn('--global', hint)

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

    def test_a_backend_that_fails_conformance_is_recorded_as_a_degradation(self):
        """The CLI printed the non-conformance to stderr and then built on the floor with
        no metadata at all, so the artifact was indistinguishable from an ordinary floor
        build. It is a degradation like any other: the project asked for a backend and did
        not get it, and the graph is the only place still saying so a week later.
        """
        import backends
        from graph_ops import CodeGraph
        d = self.mk('{"substrate": {"backend": "brokenbackend"}}')

        class Broken:
            """Registered, available, and not conforming — `coverage()` raises."""
            name = 'brokenbackend'

            def __init__(self, project_dir):
                self.project_dir = project_dir

            def coverage(self):
                raise RuntimeError('cannot describe itself')

            def available(self):
                return True

            def build(self, **kw):
                raise AssertionError('a non-conforming backend must never be built with')

            def update(self, **kw):
                raise AssertionError('a non-conforming backend must never be built with')

        original = backends._registry
        backends._registry = lambda: dict(original(), brokenbackend=Broken)
        self.addCleanup(setattr, backends, '_registry', original)

        floor = CodeGraph(d)
        chosen, metadata = graph_ops.choose_backend(floor, floor.project_exclusions())
        self.assertIs(chosen, floor)
        self.assertEqual(metadata['degraded_from'], 'brokenbackend')

        graph_ops.run_build(floor, non_interactive=True, exclusions=None,
                            selection_metadata=metadata)
        written = json.loads(
            (Path(d) / 'knowledge-base' / '.graph' / 'graph.json').read_text('utf-8'))
        self.assertEqual(written['substrate']['degraded_from'], 'brokenbackend')
        self.assertIn('does not satisfy the substrate contract',
                      written['substrate']['degraded_reason'])


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
