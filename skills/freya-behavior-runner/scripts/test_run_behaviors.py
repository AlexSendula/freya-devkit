import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
import unittest.mock as mock
from unittest.mock import patch, MagicMock

import run_behaviors


SPEC = """---
id: SPEC-001
title: Passkey Login
category: auth
status: implemented
behaviors:
  - behavior_id: BEH-002
    title: Login with an expired challenge is rejected
    state: accepted
    level: unit
    adapter: vitest
    locator: lib/webauthn.test.ts::rejects an expired challenge
  - behavior_id: BEH-003
    title: Unknown email does not reveal whether a user exists
    state: accepted
    level: integration
    adapter: cucumber
    locator: features/auth/passkey-login.feature#unknown-email-does-not-reveal-whether-a-user-exists
  - behavior_id: BEH-001
    title: Successful passkey login
    state: proposed
    level: e2e
    adapter: cucumber
    locator: features/auth/passkey-login.feature#successful-passkey-login
  - behavior_id: BEH-004
    title: Authentication start rejects a malformed body (test owed)
    state: confirmed
    level: integration
    entry: app/api/auth/passkey/authenticate/start/route.ts
---
# body
"""


class LoadAcceptedBehaviorsTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        specs = os.path.join(self.tmp.name, "auth")
        os.makedirs(specs)
        with open(os.path.join(specs, "SPEC-001-passkey-login.md"), "w") as f:
            f.write(SPEC)
        self.specs_dir = self.tmp.name

    def tearDown(self):
        self.tmp.cleanup()

    def test_filters_to_accepted_unit(self):
        got = run_behaviors.load_accepted_behaviors(self.specs_dir, level="unit")
        self.assertEqual(len(got), 1)
        self.assertEqual(got[0]["behavior_id"], "BEH-002")
        self.assertEqual(got[0]["spec_id"], "SPEC-001")
        self.assertTrue(got[0]["spec_path"].endswith("SPEC-001-passkey-login.md"))

    def test_accepted_without_level_filter_excludes_proposed(self):
        got = run_behaviors.load_accepted_behaviors(self.specs_dir)
        ids = sorted(b["behavior_id"] for b in got)
        self.assertEqual(ids, ["BEH-002", "BEH-003"])  # BEH-001 is proposed


class CoverageMappingTest(unittest.TestCase):
    def setUp(self):
        self.project = "/proj"
        self.cov = {
            "/proj/lib/webauthn.ts": {"s": {"0": 3, "1": 1, "2": 0}},
            "/proj/lib/webauthn.test.ts": {"s": {"0": 1}},
            "/proj/lib/unused.ts": {"s": {"0": 0, "1": 0}},
            "/proj/node_modules/pkg/index.js": {"s": {"0": 5}},
            "/elsewhere/other.ts": {"s": {"0": 2}},
        }

    def test_keeps_executed_project_source_drops_the_rest(self):
        keys = run_behaviors.coverage_files_to_keys(
            self.cov, self.project, exclude={"lib/webauthn.test.ts"}
        )
        self.assertEqual(keys, ["lib/webauthn.ts"])

    def test_unused_file_is_dropped(self):
        keys = run_behaviors.coverage_files_to_keys(self.cov, self.project)
        self.assertNotIn("lib/unused.ts", keys)


class ShapeFingerprintTest(unittest.TestCase):
    def test_observed_when_keys_present(self):
        fp = run_behaviors.shape_fingerprint(["lib/webauthn.ts"], "abc123")
        self.assertEqual(fp["coverage"], "observed")
        self.assertEqual(fp["exercises"], [
            {"path": "lib/webauthn.ts", "source": "observed", "confidence": 0.8, "freshness": "abc123"}
        ])
        # Fix 2: observed result must NOT carry a reason key
        self.assertNotIn("reason", fp)

    def test_unknown_when_no_keys(self):
        fp = run_behaviors.shape_fingerprint([], "abc123")
        self.assertEqual(fp["coverage"], "unknown")
        self.assertEqual(fp["exercises"], [])
        # Fix 2: unknown without reason omits the key entirely
        self.assertNotIn("reason", fp)

    def test_unknown_with_reason_includes_reason(self):
        # Fix 2: unknown WITH reason includes "reason"
        fp = run_behaviors.shape_fingerprint([], "abc123", reason="test-failed")
        self.assertEqual(fp["coverage"], "unknown")
        self.assertEqual(fp["exercises"], [])
        self.assertEqual(fp["reason"], "test-failed")

    def test_unknown_with_none_reason_omits_reason(self):
        # Fix 2: reason=None must not add the key
        fp = run_behaviors.shape_fingerprint([], "abc123", reason=None)
        self.assertNotIn("reason", fp)


class VitestArgvTest(unittest.TestCase):
    def test_builds_filtered_vitest_argv(self):
        beh = {
            "behavior_id": "BEH-002",
            "adapter": "vitest",
            "locator": "lib/webauthn.test.ts::rejects an expired challenge",
        }
        argv, test_file = run_behaviors.vitest_argv(beh)
        self.assertEqual(test_file, "lib/webauthn.test.ts")
        self.assertEqual(
            argv,
            ["pnpm", "vitest", "run", "lib/webauthn.test.ts",
             "-t", "rejects an expired challenge", "--coverage"],
        )


class PytestArgvTest(unittest.TestCase):
    """The Python argv builder, and the defect class it must not repeat.

    ADR-013 measured what naming an interpreter by hope costs on this project: all 80 script
    invocations called a bare `python`, which does not exist on many modern systems. A bare
    `pytest` is the same bet on a console script being installed *and* first on PATH, and it
    is worse here — the flags below come from pytest-cov, so a pytest resolved off PATH may
    be one this interpreter never probed.
    """

    def build(self, locator, coverage=True):
        with patch.object(run_behaviors, "coverage_json_available", return_value=coverage):
            return run_behaviors.pytest_argv(
                {"behavior_id": "BEH-900", "adapter": "pytest", "locator": locator})

    def test_it_runs_pytest_as_a_module_of_the_running_interpreter(self):
        argv, _ = self.build("lib/test_webauthn.py#TestChallenge.test_expired")
        self.assertEqual(argv[:3], [sys.executable, "-m", "pytest"])

    def test_the_hash_spelling_of_a_locator_becomes_a_pytest_node_id(self):
        """`path#Class.method` is the spelling `feature_locator` emits and the one every
        behavior in this repo is authored with; pytest addresses a test only as
        `path::Class::method`. An untranslated locator is not a filter that matches nothing,
        it is a usage error — measured exit 4 on pytest 9.0.1."""
        argv, test_file = self.build("lib/test_webauthn.py#TestChallenge.test_expired")
        self.assertEqual(test_file, "lib/test_webauthn.py")
        self.assertEqual(argv[3], "lib/test_webauthn.py::TestChallenge::test_expired")

    def test_the_double_colon_spelling_of_a_locator_is_carried_through_unchanged(self):
        argv, test_file = self.build("lib/test_webauthn.py::TestChallenge::test_expired")
        self.assertEqual(test_file, "lib/test_webauthn.py")
        self.assertEqual(argv[3], "lib/test_webauthn.py::TestChallenge::test_expired")

    def test_a_module_level_test_function_needs_no_class_segment(self):
        argv, _ = self.build("lib/test_webauthn.py#test_expired_is_rejected")
        self.assertEqual(argv[3], "lib/test_webauthn.py::test_expired_is_rejected")

    def test_a_locator_with_no_fragment_addresses_the_whole_file(self):
        argv, _ = self.build("lib/test_webauthn.py")
        self.assertEqual(argv[3], "lib/test_webauthn.py")

    def test_a_parametrize_id_keeps_the_dot_inside_its_brackets(self):
        """`test_backoff[1.5]` is one pytest node segment. Splitting the fragment on every
        `.` yields `test_backoff[1::5]`, which addresses nothing — and by the time that
        reaches an exit code it is indistinguishable from a stale locator.

        A `subTest` row has no addressable id at all (see `pytest_node_id`), so this is the
        only bracketed form the translator ever legitimately sees.
        """
        argv, _ = self.build("lib/test_rate.py#TestWindow.test_backoff[1.5]")
        self.assertEqual(argv[3], "lib/test_rate.py::TestWindow::test_backoff[1.5]")

    def test_the_coverage_flags_appear_only_when_the_reporter_is_importable(self):
        """coverage.py and pytest-cov are not stdlib and the plugin is zero-install
        (ADR-005), so the flags are conditional on a probe. Emitting them regardless makes
        pytest exit 4 on a machine without pytest-cov — which this runner reads as a locator
        that selected nothing, so a missing optional package would masquerade as a broken
        spec and the coverage degradation would never be reported as such."""
        with_cov, _ = self.build("lib/test_a.py#T.test_b", coverage=True)
        without, _ = self.build("lib/test_a.py#T.test_b", coverage=False)
        self.assertEqual(with_cov[4:],
                         ["--cov=.", "--cov-report=json:coverage/coverage-python.json"])
        self.assertEqual(without,
                         [sys.executable, "-m", "pytest", "lib/test_a.py::T::test_b"])


class PytestCoverageMappingTest(unittest.TestCase):
    """coverage.py's JSON report mapped to fingerprint keys.

    The fixture is the shape measured from coverage 7.12.0 (`meta.format: 3`), not an
    invented one: `files[path]` carrying `executed_lines`, a `summary`, and a per-region
    `functions` map. It shares no key with istanbul's `s`/`fnMap`/`f`, which is why there are
    two parsers rather than one with a branch.
    """

    REPORT = {
        "meta": {"format": 3, "version": "7.12.0"},
        "files": {
            "pkg/lib.py": {
                "executed_lines": [1, 2, 4],
                "summary": {"covered_lines": 3, "num_statements": 4},
                "functions": {
                    "used": {"executed_lines": [2], "summary": {"covered_lines": 1}},
                    "unused": {"executed_lines": [], "summary": {"covered_lines": 0}},
                    "": {"executed_lines": [1, 4], "summary": {"covered_lines": 2}},
                },
            },
            "pkg/never_imported.py": {
                "executed_lines": [],
                "summary": {"covered_lines": 0, "num_statements": 6},
                "functions": {},
            },
            "lib/test_webauthn.py": {
                "executed_lines": [1, 2, 4, 5, 6],
                "summary": {"covered_lines": 5, "num_statements": 6},
                "functions": {"TestChallenge.test_expired": {"executed_lines": [6]}},
            },
            ".venv/lib/python3.12/site-packages/thirdparty/mod.py": {
                "executed_lines": [1, 2],
                "summary": {"covered_lines": 2, "num_statements": 2},
                "functions": {"helper": {"executed_lines": [2]}},
            },
            "/elsewhere/other.py": {
                "executed_lines": [1],
                "summary": {"covered_lines": 1, "num_statements": 1},
            },
        },
    }

    def test_it_keeps_the_project_files_the_test_actually_reached(self):
        keys = run_behaviors.coverage_json_to_keys(
            self.REPORT, "/proj", exclude={"lib/test_webauthn.py"})
        self.assertEqual(keys, ["pkg/lib.py"])

    def test_a_module_nothing_imported_is_dropped(self):
        """`--cov=.` reports every file under the tree, not only the ones that ran, so an
        untouched module arrives with `covered_lines: 0` and an empty `executed_lines`.
        Keeping it would attribute the whole repository to every behavior, which is the
        over-broad fingerprint ADR-006's confidence split exists to avoid."""
        self.assertNotIn("pkg/never_imported.py",
                         run_behaviors.coverage_json_to_keys(self.REPORT, "/proj"))

    def test_an_installed_package_inside_the_project_is_not_project_code(self):
        """A virtualenv under the project root is measured like anything else once `--cov=.`
        is in play. This is the Python counterpart of the istanbul path's `node_modules`
        guard, and pruning is the thing under test here."""
        self.assertNotIn(".venv/lib/python3.12/site-packages/thirdparty/mod.py",
                         run_behaviors.coverage_json_to_keys(self.REPORT, "/proj"))

    def test_a_file_outside_the_project_is_dropped(self):
        keys = run_behaviors.coverage_json_to_keys(self.REPORT, "/proj")
        self.assertFalse([k for k in keys if "other.py" in k], keys)

    def test_an_absolute_report_path_maps_the_same_as_a_relative_one(self):
        """coverage.py writes paths relative to the directory the run started in, but a
        `[run] relative_files = false` config — the default in some projects — makes them
        absolute. Both spellings name the same file and must produce the same key."""
        report = {"files": {"/proj/pkg/lib.py": {
            "executed_lines": [1], "summary": {"covered_lines": 1}}}}
        self.assertEqual(run_behaviors.coverage_json_to_keys(report, "/proj"),
                         ["pkg/lib.py"])


class PytestCoverageSymbolsTest(unittest.TestCase):
    """Symbol refinement on the Python side — measured from the report, never inferred."""

    def test_only_functions_the_test_entered_are_recorded(self):
        syms = run_behaviors.coverage_json_symbols(
            PytestCoverageMappingTest.REPORT, "/proj", exclude={"lib/test_webauthn.py"})
        self.assertEqual(syms["pkg/lib.py"], ["used"])

    def test_module_level_statements_are_not_a_function_name(self):
        """coverage.py files a module's top-level lines under the **empty** name `""` — the
        same thing istanbul spells `(anonymous_N)`. behavior.json is committed (ADR-017), so
        a key naming no function only churns the tracked diff."""
        syms = run_behaviors.coverage_json_symbols(
            PytestCoverageMappingTest.REPORT, "/proj")
        self.assertEqual(syms["pkg/lib.py"], ["used"])
        self.assertNotIn("", syms["pkg/lib.py"])

    def test_a_report_from_an_older_coverage_yields_an_unrefined_entry_not_an_error(self):
        """The per-region `functions` block landed in coverage.py 7.6.2; an older report has
        no such key at all. ADR-024's compatibility clause applies — an entry with no symbols
        must be byte-identical to one written before symbols existed, so the absence has to
        produce no key rather than an empty list."""
        report = {"files": {"pkg/lib.py": {"executed_lines": [1, 2],
                                           "summary": {"covered_lines": 2}}}}
        self.assertEqual(run_behaviors.coverage_json_symbols(report, "/proj"), {})
        fp = run_behaviors.shape_fingerprint(
            ["pkg/lib.py"], "c1",
            symbols=run_behaviors.coverage_json_symbols(report, "/proj"))
        self.assertNotIn("symbols", fp["exercises"][0])


class RunPytestBehaviorTest(unittest.TestCase):
    """Every branch of the Python executor that cannot measure, and what it says instead.

    ADR-006's never-falsely-empty rule carries the highest cost in the layer: an empty
    `exercises` list reads to the blast-radius query as "nothing to re-run", the single
    output that silently disables the regression gate. So each branch is pinned on its
    `reason`, not merely on being `unknown` — the reason string is what SPEC-022's merge
    dispatches on.

    The subprocess is mocked throughout: shelling out to a real pytest from a unit test
    would make this file's result depend on the tree it happens to be run from.
    """

    BEHAVIOR = {
        "behavior_id": "BEH-900", "state": "accepted", "level": "unit",
        "adapter": "pytest",
        "locator": "lib/test_webauthn.py#TestChallenge.test_expired_is_rejected",
    }
    REPORT = {
        "meta": {"format": 3, "version": "7.12.0"},
        "files": {
            "pkg/webauthn.py": {
                "executed_lines": [1, 2], "summary": {"covered_lines": 2},
                "functions": {"verify_challenge": {"executed_lines": [2]}},
            },
            "lib/test_webauthn.py": {
                "executed_lines": [1, 5], "summary": {"covered_lines": 2},
                "functions": {"TestChallenge.test_expired_is_rejected":
                              {"executed_lines": [5]}},
            },
        },
    }

    def setUp(self):
        self.project = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.project, ignore_errors=True)
        self.report_path = os.path.join(self.project, "coverage", "coverage-python.json")

    def write_report(self, report):
        os.makedirs(os.path.dirname(self.report_path), exist_ok=True)
        with open(self.report_path, "w", encoding="utf-8") as f:
            json.dump(report, f)

    def run_it(self, returncode, coverage_tool=True, report=None):
        """Drive the executor with a fake pytest that writes `report` when it runs.

        Written from the side effect rather than up front on purpose: the executor deletes a
        stale report *before* it launches pytest, so a fixture placed in advance would be
        removed and the test would silently exercise the no-report branch instead.
        """
        def fake_run(argv, **kwargs):
            self.calls.append((argv, kwargs))
            if report is not None:
                self.write_report(report)
            return MagicMock(returncode=returncode, stdout="", stderr="")

        self.calls = []
        with patch.object(run_behaviors.subprocess, "run", side_effect=fake_run), \
             patch.object(run_behaviors, "coverage_json_available",
                          return_value=coverage_tool), \
             patch.object(run_behaviors, "_git_head", return_value="abc123"):
            return run_behaviors.run_pytest_behavior(self.BEHAVIOR, self.project)

    def test_a_passing_run_becomes_an_observed_fingerprint_without_the_test_file(self):
        fp = self.run_it(0, report=self.REPORT)
        self.assertEqual(fp["coverage"], "observed")
        self.assertEqual([e["path"] for e in fp["exercises"]], ["pkg/webauthn.py"])
        self.assertEqual(fp["exercises"][0]["symbols"], ["verify_challenge"])

    def test_pytest_is_launched_with_the_project_as_its_working_directory(self):
        """`--cov=.` and the relative `--cov-report=json:coverage/…` path are both resolved
        against the child's cwd. Launching from anywhere else measures the wrong tree and
        writes the report where the executor will not look for it."""
        self.run_it(0, report=self.REPORT)
        self.assertEqual(self.calls[0][1]["cwd"], self.project)

    def test_a_red_test_is_test_failed_and_no_coverage_is_invented(self):
        fp = self.run_it(1)
        self.assertEqual(fp["coverage"], "unknown")
        self.assertEqual(fp["exercises"], [])
        self.assertEqual(fp["reason"], "test-failed")

    def test_a_locator_that_selects_no_test_is_not_reported_as_a_test_failure(self):
        """Measured on pytest 9.0.1: a node id naming a method that does not exist prints
        `(no match in any of [...])` and exits **4** — a usage error, not a red test.

        The distinction is load-bearing in both directions. `test-failed` invalidates the
        committed edges (SPEC-022's merge) *and* hard-blocks wrap-up Phase 3.5 (ADR-009),
        which is only defensible because it is a real test result rather than an inference —
        and a renamed test method is not a test result at all. Resolving locators belongs to
        `verify_links`, which checks every state, not to the runner.
        """
        fp = self.run_it(4)
        self.assertEqual(fp["coverage"], "unknown")
        self.assertEqual(fp["reason"], "locator-selected-nothing")

    def test_exit_five_no_tests_collected_is_the_same_non_failure(self):
        self.assertEqual(self.run_it(5)["reason"], "locator-selected-nothing")

    def test_a_pass_with_no_coverage_tooling_says_so_rather_than_claiming_a_measurement(self):
        """coverage.py and pytest-cov are optional (ADR-005: zero-install), so this is the
        ordinary state of a fresh machine, not an error. The exit code is still honoured —
        the test really did pass — but the coverage half degrades to `unknown` with a reason,
        which SPEC-022 merges as "no news" and therefore preserves whatever was measured
        last time instead of overwriting it with nothing."""
        fp = self.run_it(0, coverage_tool=False)
        self.assertEqual(fp["coverage"], "unknown")
        self.assertEqual(fp["exercises"], [])
        self.assertEqual(fp["reason"], "no-coverage-tool")
        self.assertFalse([a for a in self.calls[0][0] if a.startswith("--cov")],
                         "no coverage flags may be sent to a pytest that cannot parse them")

    def test_a_red_test_is_still_test_failed_when_coverage_is_unavailable(self):
        """The order of the two checks is the contract. Reading coverage availability first
        would report a genuinely failing Python behavior as an unmeasured one on any machine
        without pytest-cov — turning the regression gate off exactly where it is needed."""
        self.assertEqual(self.run_it(1, coverage_tool=False)["reason"], "test-failed")

    def test_a_pass_that_wrote_no_report_is_no_coverage(self):
        fp = self.run_it(0, report=None)
        self.assertEqual(fp["coverage"], "unknown")
        self.assertEqual(fp["reason"], "no-coverage")

    def test_a_stale_report_from_a_previous_run_is_never_read_as_this_run_s_coverage(self):
        """The report path is fixed, so yesterday's file is sitting there when today's run
        starts. Without the up-front delete, a run that produced no coverage at all would be
        fingerprinted `observed` from the previous run's edges and stamped with the current
        commit — a measurement that never happened, written into a committed artifact."""
        self.write_report(self.REPORT)
        fp = self.run_it(0, report=None)
        self.assertEqual(fp["reason"], "no-coverage")
        self.assertEqual(fp["exercises"], [])

    def test_coverage_that_maps_nowhere_inside_the_project_is_unknown_not_empty(self):
        fp = self.run_it(0, report={"files": {"/elsewhere/pkg/other.py": {
            "executed_lines": [1], "summary": {"covered_lines": 1}}}})
        self.assertEqual(fp["coverage"], "unknown")
        self.assertEqual(fp["reason"], "coverage-outside-project")


class PythonBehaviorDispatchTest(unittest.TestCase):
    """`fingerprint_behavior` hardcoded `adapter == "vitest"`, so a Python behavior could be
    authored and validated (`KNOWN_ADAPTERS` allow-lists both `pytest` and `unittest`) and
    then never run.

    Measured on this repository's own 149 behaviors: 132 declare `adapter: unittest`, of
    which 26 are `integration` and got a static fingerprint while the other **106 fell to
    `level-deferred`** — not one executed a test. 83 of those are `unit`-level and reach the
    executor once this dispatch exists; the remaining 23 are `component`-level and still do
    not, which is why the level check below is pinned too.

    Both Python spellings must reach the executor, and `state` must still be read before
    either of them.
    """

    def test_an_accepted_unit_pytest_behavior_is_executed(self):
        beh = {"behavior_id": "BEH-900", "state": "accepted", "level": "unit",
               "adapter": "pytest", "locator": "lib/test_x.py#T.test_y"}
        with mock.patch.object(run_behaviors, "run_pytest_behavior",
                               return_value={"coverage": "observed", "exercises": []}) as run:
            fp = run_behaviors.fingerprint_behavior(beh, "/proj", "c1")
        run.assert_called_once()
        self.assertEqual(fp["coverage"], "observed")

    def test_an_accepted_unit_unittest_behavior_reaches_the_same_executor(self):
        """`unittest` and `pytest` are two adapter names for one executor: a
        `unittest.TestCase` is collected and addressed by pytest identically. Routing only
        the `pytest` spelling would leave this repository's behaviors unrunnable, since all
        29 of its test files are `unittest.TestCase`."""
        beh = {"behavior_id": "BEH-901", "state": "accepted", "level": "unit",
               "adapter": "unittest", "locator": "lib/test_x.py#T.test_y"}
        with mock.patch.object(run_behaviors, "run_pytest_behavior",
                               return_value={"coverage": "observed", "exercises": []}) as run:
            run_behaviors.fingerprint_behavior(beh, "/proj", "c1")
        run.assert_called_once()

    def test_a_confirmed_python_behavior_is_still_never_executed(self):
        """ADR-003's ordering: state is read before level and adapter, so the gate on a
        confirmed behavior is unreachable rather than merely forbidden. Adding a second
        executor is precisely the change that could re-open it — a confirmed record may name
        a Python test nobody has written yet."""
        beh = {"behavior_id": "BEH-902", "state": "confirmed", "level": "unit",
               "adapter": "pytest", "locator": "lib/test_x.py#T.test_y"}
        with mock.patch.object(run_behaviors, "run_pytest_behavior") as run, \
             mock.patch.object(run_behaviors, "static_fingerprint",
                               return_value={"coverage": "unknown", "exercises": [],
                                             "reason": "no-entry"}) as sf:
            run_behaviors.fingerprint_behavior(beh, "/proj", "c1")
        run.assert_not_called()
        sf.assert_called_once()

    def test_a_python_behavior_at_an_unimplemented_level_is_still_level_deferred(self):
        """The executor is unit-level only, exactly as the vitest one is. An `e2e` Python
        behavior has no path and must say so, rather than be quietly run at a level whose
        coverage semantics it does not have."""
        beh = {"behavior_id": "BEH-903", "state": "accepted", "level": "e2e",
               "adapter": "pytest", "locator": "lib/test_x.py#T.test_y"}
        with mock.patch.object(run_behaviors, "run_pytest_behavior") as run:
            fp = run_behaviors.fingerprint_behavior(beh, "/proj", "c1")
        run.assert_not_called()
        self.assertEqual(fp["reason"], "level-deferred")


class LoadAcceptedBehaviorsMalformedTest(unittest.TestCase):
    """Fix 1: a malformed spec must not abort the whole batch."""

    VALID_SPEC = """---
id: SPEC-GOOD
title: Good Spec
category: auth
status: implemented
behaviors:
  - behavior_id: BEH-GOOD
    title: A valid behavior
    state: accepted
    level: unit
    adapter: vitest
    locator: lib/auth.test.ts::works
---
# body
"""

    MALFORMED_SPEC = """---
id: SPEC-BAD
title: Unterminated fence
# no closing ---
"""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        specs = os.path.join(self.tmp.name, "auth")
        os.makedirs(specs)
        with open(os.path.join(specs, "good.md"), "w") as f:
            f.write(self.VALID_SPEC)
        with open(os.path.join(specs, "bad.md"), "w") as f:
            f.write(self.MALFORMED_SPEC)
        self.specs_dir = self.tmp.name

    def tearDown(self):
        self.tmp.cleanup()

    def test_malformed_spec_does_not_abort_batch(self):
        # Must not raise, and must still return the valid behavior
        got = run_behaviors.load_accepted_behaviors(self.specs_dir)
        self.assertEqual(len(got), 1)
        self.assertEqual(got[0]["behavior_id"], "BEH-GOOD")

    def test_a_spec_that_is_not_utf8_costs_one_file_not_the_batch(self):
        """Only `FrontmatterError` was caught, and strict decoding raises
        `UnicodeDecodeError` — which is not one. A single spec with a stray byte took the
        entire behaviour layer down with an unhandled traceback."""
        with open(os.path.join(self.specs_dir, "auth", "bytes.md"), "wb") as f:
            f.write(b"---\nid: SPEC-BYTES\ntitle: caf\xe9\n---\n")
        got = run_behaviors.load_accepted_behaviors(self.specs_dir)
        self.assertEqual([b["behavior_id"] for b in got], ["BEH-GOOD"])


class DegradedGraphDoesNotNarrowACommittedFingerprintTest(unittest.TestCase):
    """A graph built by the floor after the project's backend was unavailable is thinner than
    the project declared. Answering from it writes that thinner closure into behavior.json,
    which is committed — and `exercises[].path` decides which behaviours a change is deemed to
    affect, so every later blast radius is narrowed by whichever laptop ran last.

    `unknown` with a reason is the signal `merge_fingerprint` already honours by preserving
    the prior. Refusing to answer is honest; a narrower answer that looks authoritative is not.
    """

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.proj = self.tmp.name
        self.addCleanup(self.tmp.cleanup)
        graph_dir = os.path.join(self.proj, "knowledge-base", ".graph")
        os.makedirs(graph_dir)
        self.graph = os.path.join(graph_dir, "graph.json")

    def write_graph(self, substrate):
        with open(self.graph, "w", encoding="utf-8") as fh:
            json.dump({"version": 2, "substrate": substrate, "files": {}}, fh)

    def test_a_degraded_graph_is_declined_with_a_reason(self):
        self.write_graph({"backend": "homegrown", "degraded_from": "graphify",
                          "coverage": {}})
        deps, reason = run_behaviors._code_graph_deps("app/x.ts", self.proj)
        self.assertIsNone(deps)
        self.assertTrue(reason.startswith("graph-degraded"), reason)
        self.assertIn("graphify", reason)

    def test_an_undegraded_graph_is_answered_normally(self):
        self.write_graph({"backend": "homegrown", "coverage": {}})
        deps, reason = run_behaviors._code_graph_deps("app/x.ts", self.proj)
        # Reaches the real query rather than being declined up front; whatever it answers,
        # it must not be the degraded refusal.
        self.assertFalse((reason or "").startswith("graph-degraded"))

    def test_a_graph_with_no_substrate_block_is_not_treated_as_degraded(self):
        with open(self.graph, "w", encoding="utf-8") as fh:
            json.dump({"version": 1, "files": {}}, fh)
        _, reason = run_behaviors._code_graph_deps("app/x.ts", self.proj)
        self.assertFalse((reason or "").startswith("graph-degraded"))


class ReasonStringsAreCommittableTest(unittest.TestCase):
    """`reason` is written into behavior.json, which is tracked (ADR-017).

    Raw stderr was spliced in verbatim, so a traceback tail put the absolute path of
    whichever machine produced it into git — a different committed string per developer,
    and a home directory leaked into the repository.
    """

    def test_the_project_root_becomes_a_dot(self):
        got = run_behaviors._portable(
            "OSError: [Errno 13] /home/alex/proj/knowledge-base/.graph/graph.json",
            "/home/alex/proj")
        self.assertNotIn("/home/alex", got)
        self.assertIn("knowledge-base/.graph/graph.json", got)

    def test_an_unrelated_absolute_path_is_reduced_to_its_basename(self):
        got = run_behaviors._portable("could not read /Users/someone/other/graph.json",
                                      "/home/alex/proj")
        self.assertNotIn("/Users/someone", got)
        self.assertIn("graph.json", got)

    def test_a_windows_absolute_path_is_reduced_on_every_host(self):
        """The Windows spelling, judged on whatever host runs the suite.

        `os.path.isabs` answers for the platform it is on, and this string came from another
        tool — so a Linux run must still recognise `C:\\Users\\...` as absolute or the
        reduction is only as good as the machine that happened to run it.
        """
        got = run_behaviors._portable(r"could not read C:\Users\someone\other\graph.json",
                                      "/home/alex/proj")
        self.assertNotIn("someone", got)
        self.assertIn("graph.json", got)

    def test_a_posix_absolute_path_is_reduced_on_every_host(self):
        """The mirror, and the one CI actually caught.

        On Windows under Python 3.13 `ntpath.isabs('/Users/someone/x')` is False — 3.13
        stopped treating a rooted path with no drive as absolute — so this leaked a home
        directory into the committed behavior.json on that interpreter and no other. It
        passed on Linux, on Windows 3.9, and on every developer machine.
        """
        got = run_behaviors._portable("could not read /Users/someone/other/graph.json",
                                      r"C:\projects\thing")
        self.assertNotIn("someone", got)
        self.assertIn("graph.json", got)

    def test_a_bare_word_is_not_mistaken_for_a_path(self):
        """The rule widened; it must not have widened onto ordinary prose."""
        got = run_behaviors._portable("could not read the file: permission denied", "/p")
        self.assertIn("permission denied", got)
        self.assertIn("could not read the file:", got)

    def test_it_is_bounded_and_single_line(self):
        got = run_behaviors._portable("a\nb\n" + "x" * 500, "/p")
        self.assertNotIn("\n", got)
        self.assertLessEqual(len(got), 200)


class RunUnitBehaviorFailureTest(unittest.TestCase):
    """Fix 3: run_unit_behavior failure branch uses reason='test-failed'."""

    BEHAVIOR = {
        "behavior_id": "BEH-002",
        "level": "unit",
        "adapter": "vitest",
        "locator": "lib/webauthn.test.ts::rejects an expired challenge",
    }

    def test_failed_subprocess_returns_test_failed_reason(self):
        mock_result = MagicMock()
        mock_result.returncode = 1
        mock_result.stdout = ""
        mock_result.stderr = ""
        with patch("run_behaviors.subprocess.run", return_value=mock_result):
            with patch("run_behaviors._git_head", return_value="abc123"):
                with patch("run_behaviors.os.path.exists", return_value=False):
                    with patch("run_behaviors.os.remove"):
                        fp = run_behaviors.run_unit_behavior(self.BEHAVIOR, "/fake/project")
        self.assertEqual(fp["coverage"], "unknown")
        self.assertEqual(fp["exercises"], [])
        self.assertEqual(fp["reason"], "test-failed")


class CoverageSymbolsTest(unittest.TestCase):
    """Phase 3 — an exercise entry may name the functions that actually ran.

    Sourced from the coverage report, not the code graph: `observed` means "the test ran
    this", and taking symbols from a graph would mix in things nobody executed.
    """

    COV = {
        "/proj/lib/webauthn.ts": {
            "s": {"0": 3},
            "fnMap": {"0": {"name": "verifyChallenge"}, "1": {"name": "unusedHelper"},
                      "2": {"name": "(anonymous_1)"}},
            "f": {"0": 5, "1": 0, "2": 9},
        },
        "/proj/lib/plain.ts": {"s": {"0": 1}, "fnMap": {}, "f": {}},
        "/proj/node_modules/pkg/i.js": {"s": {"0": 1},
                                        "fnMap": {"0": {"name": "vendored"}}, "f": {"0": 1}},
    }

    def test_only_functions_that_ran_are_recorded(self):
        syms = run_behaviors.coverage_symbols(self.COV, "/proj")
        self.assertEqual(syms["lib/webauthn.ts"], ["verifyChallenge"])

    def test_anonymous_functions_are_never_recorded(self):
        """`(anonymous_N)` is a positional counter per file — inserting one function
        renumbers every later one. behavior.json is committed (ADR-017), so those names
        would churn the tracked diff on edits that changed nothing about what ran."""
        syms = run_behaviors.coverage_symbols(self.COV, "/proj")
        self.assertNotIn("(anonymous_1)", syms["lib/webauthn.ts"])

    def test_a_file_with_no_named_functions_is_simply_absent(self):
        self.assertNotIn("lib/plain.ts", run_behaviors.coverage_symbols(self.COV, "/proj"))

    def test_vendored_code_is_excluded_as_it_is_for_paths(self):
        syms = run_behaviors.coverage_symbols(self.COV, "/proj")
        self.assertEqual(list(syms), ["lib/webauthn.ts"])

    def test_symbols_refine_an_entry_without_replacing_its_path(self):
        fp = run_behaviors.shape_fingerprint(
            ["lib/webauthn.ts", "lib/plain.ts"], "c1",
            symbols={"lib/webauthn.ts": ["verifyChallenge"]})
        by_path = {e["path"]: e for e in fp["exercises"]}
        self.assertEqual(by_path["lib/webauthn.ts"]["symbols"], ["verifyChallenge"])
        self.assertEqual(sorted(by_path), ["lib/plain.ts", "lib/webauthn.ts"])

    def test_an_unrefined_entry_is_byte_identical_to_before_symbols_existed(self):
        """The compatibility guarantee for a *committed* artifact: a project whose coverage
        yields no named functions must produce exactly the file it produced yesterday.

        Pinned against a literal rather than against the implementation compared with itself,
        and serialised the way `write_behavior_json` does it — `json.dump(..., indent=2)` with
        no `sort_keys`, so on-disk bytes follow insertion order. An earlier version of this
        test used `sort_keys=True`, which normalises away key order — the one thing that can
        actually break, and the one thing a tracked diff would show.
        """
        got = run_behaviors.shape_fingerprint(["a.ts", "b.ts"], "c1", symbols={})
        self.assertEqual(json.dumps(got, indent=2), json.dumps({
            "coverage": "observed",
            "exercises": [
                {"path": "a.ts", "source": "observed", "confidence": 0.8,
                 "freshness": "c1"},
                {"path": "b.ts", "source": "observed", "confidence": 0.8,
                 "freshness": "c1"},
            ],
        }, indent=2))

    def test_symbols_are_appended_last_so_existing_keys_keep_their_order(self):
        """behavior.json is written with `indent=2` and no `sort_keys`, so key order is the
        file's byte order. A refined entry must be the old one plus a key, not a reshuffle."""
        got = run_behaviors.shape_fingerprint(["a.ts"], "c1", symbols={"a.ts": ["f"]})
        self.assertEqual(list(got["exercises"][0]),
                         ["path", "source", "confidence", "freshness", "symbols"])

    def test_one_entry_per_file_not_one_per_symbol(self):
        """`behavior-graph` intersects `exercises[].path` against the impact set. Splitting
        the entry would change that set's cardinality and every count derived from it."""
        fp = run_behaviors.shape_fingerprint(
            ["lib/a.ts"], "c1", symbols={"lib/a.ts": ["one", "two", "three"]})
        self.assertEqual(len(fp["exercises"]), 1)
        self.assertEqual(fp["exercises"][0]["symbols"], ["one", "three", "two"])


class ShapeFingerprintStaticTest(unittest.TestCase):
    def test_static_source_sets_coverage_and_edge_source(self):
        fp = run_behaviors.shape_fingerprint(
            ["app/api/x/route.ts", "lib/webauthn.ts"], "c1", source="static"
        )
        self.assertEqual(fp["coverage"], "static")
        self.assertEqual(
            fp["exercises"],
            [
                {"path": "app/api/x/route.ts", "source": "static", "confidence": 0.5, "freshness": "c1"},
                {"path": "lib/webauthn.ts", "source": "static", "confidence": 0.5, "freshness": "c1"},
            ],
        )

    def test_observed_default_unchanged(self):
        fp = run_behaviors.shape_fingerprint(["lib/webauthn.ts"], "c1")
        self.assertEqual(fp["coverage"], "observed")
        self.assertEqual(fp["exercises"][0]["source"], "observed")
        self.assertEqual(fp["exercises"][0]["confidence"], 0.8)


class StaticExercisesTest(unittest.TestCase):
    def test_includes_entry_dedups_and_sorts(self):
        keys = run_behaviors.static_exercises(
            "app/api/x/route.ts", ["lib/webauthn.ts", "app/api/x/route.ts", "lib/prisma.ts"]
        )
        self.assertEqual(keys, ["app/api/x/route.ts", "lib/prisma.ts", "lib/webauthn.ts"])


class StaticFingerprintTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.proj = self.tmp.name
        os.makedirs(os.path.join(self.proj, "app", "api", "x"))
        open(os.path.join(self.proj, "app", "api", "x", "route.ts"), "w").close()
        # These shell out to code-graph, which reads the machine-level backend default from
        # `~/.freya/settings.json` — real state outside the checkout. Left alone, whether this
        # class passes depends on whether the person running it ever answered the install
        # question, which is not a property of the code under test.
        self.home = tempfile.TemporaryDirectory()
        self.previous_home = os.environ.get("FREYA_HOME")
        os.environ["FREYA_HOME"] = self.home.name

    def tearDown(self):
        self.tmp.cleanup()
        if self.previous_home is None:
            os.environ.pop("FREYA_HOME", None)
        else:
            os.environ["FREYA_HOME"] = self.previous_home
        self.home.cleanup()

    def test_no_entry_is_unknown_with_reason(self):
        fp = run_behaviors.static_fingerprint({"behavior_id": "BEH-X"}, self.proj)
        self.assertEqual(fp["coverage"], "unknown")
        self.assertEqual(fp["reason"], "no-entry")

    def test_missing_entry_file_is_unknown_with_reason(self):
        beh = {"behavior_id": "BEH-X", "entry": "app/api/x/missing.ts"}
        fp = run_behaviors.static_fingerprint(beh, self.proj)
        self.assertEqual(fp["coverage"], "unknown")
        self.assertEqual(fp["reason"], "entry-missing")

    def test_entry_plus_closure_is_static(self):
        beh = {"behavior_id": "BEH-X", "entry": "app/api/x/route.ts"}
        with mock.patch.object(run_behaviors, "_code_graph_deps", return_value=(["lib/webauthn.ts", "lib/prisma.ts"], None)):
            fp = run_behaviors.static_fingerprint(beh, self.proj)
        self.assertEqual(fp["coverage"], "static")
        self.assertEqual(
            [e["path"] for e in fp["exercises"]],
            ["app/api/x/route.ts", "lib/prisma.ts", "lib/webauthn.ts"],
        )
        self.assertTrue(all(e["source"] == "static" for e in fp["exercises"]))

    def test_no_graph_is_unknown_with_reason(self):
        beh = {"behavior_id": "BEH-X", "entry": "app/api/x/route.ts"}
        with mock.patch.object(run_behaviors, "_code_graph_deps",
                               return_value=(None, "no-graph")):
            fp = run_behaviors.static_fingerprint(beh, self.proj)
        self.assertEqual(fp["coverage"], "unknown")
        self.assertEqual(fp["reason"], "no-graph")
        self.assertEqual(fp["exercises"], [])

    def test_a_failed_graph_query_is_unknown_not_a_one_file_closure(self):
        """The bug this shape exists to prevent.

        A failed query used to come back as `[]`, and the caller branched only on `None`,
        so it produced a closure of exactly the entry file — tagged `static` at full
        confidence, no warning — and behavior.json is committed. Every later blast radius
        was then computed against a fingerprint that had quietly lost its dependencies.
        """
        beh = {"behavior_id": "BEH-X", "entry": "app/api/x/route.ts"}
        with mock.patch.object(run_behaviors, "_code_graph_deps",
                               return_value=(None, "graph-query-failed")):
            fp = run_behaviors.static_fingerprint(beh, self.proj)
        self.assertEqual(fp["coverage"], "unknown")
        self.assertEqual(fp["reason"], "graph-query-failed")
        self.assertEqual(fp["exercises"], [])

    def test_an_entry_outside_the_graph_is_unknown_not_an_empty_closure(self):
        """The same silent narrowing, through a different door.

        `--dependencies` used to answer `[]` both for "imports nothing" and for "not a node
        in the graph", so a behaviour whose entry sits under an excluded directory produced a
        confident one-file fingerprint. Moving `scripts` back to a root-level exclusion made
        that newly reachable. Exercised end to end against a real graph rather than a mock,
        because the defect lived in the seam between the two processes.
        """
        proj = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, proj, ignore_errors=True)
        os.makedirs(os.path.join(proj, "src"))
        os.makedirs(os.path.join(proj, "scripts"))
        with open(os.path.join(proj, "src", "a.ts"), "w") as f:
            f.write("export const a = 1\n")
        with open(os.path.join(proj, "scripts", "tool.ts"), "w") as f:
            f.write("export const t = 1\n")

        subprocess.run([sys.executable, str(run_behaviors._CODE_GRAPH), "--build",
                        "--dir", proj, "--non-interactive"],
                       capture_output=True, text=True, check=True)

        beh = {"behavior_id": "BEH-X", "entry": "scripts/tool.ts"}
        fp = run_behaviors.static_fingerprint(beh, proj)
        self.assertEqual(fp["coverage"], "unknown")
        self.assertEqual(fp["exercises"], [])
        self.assertTrue(fp["reason"].startswith("graph-query-failed"), fp["reason"])

        # ...and a node that really is in the graph still answers.
        fp2 = run_behaviors.static_fingerprint(
            {"behavior_id": "BEH-Y", "entry": "src/a.ts"}, proj)
        self.assertEqual(fp2["coverage"], "static")
        self.assertEqual([e["path"] for e in fp2["exercises"]], ["src/a.ts"])

    def test_a_repo_with_unmapped_files_still_fingerprints_static(self):
        """THE ANTI-REFUSAL PIN (ADR-029).

        Blind spots are the normal operating condition of the floor on any polyglot repo, and
        must never become a refusal the way `degraded_from` is. Extending that refusal here is
        the first "fix" a future reader will reach for, and it would return `coverage: unknown`
        for every confirmed and every integration behaviour on every such repository —
        freezing the committed behavior.json where there is history, writing empty `exercises`
        where there is not, and taking wrap-up's gate green over zero behaviours.

        A caveat may change what an answer says about itself. It may never change whether
        there is an answer.
        """
        proj = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, proj, ignore_errors=True)
        os.makedirs(os.path.join(proj, "src"))
        os.makedirs(os.path.join(proj, "svc"))
        with open(os.path.join(proj, "src", "a.ts"), "w") as f:
            f.write("export const a = 1\n")
        with open(os.path.join(proj, "src", "b.ts"), "w") as f:
            f.write('import { a } from "./a"\nexport const b = a\n')
        for i in range(12):
            with open(os.path.join(proj, "svc", "C%d.java" % i), "w") as f:
                f.write("class C%d {}\n" % i)

        subprocess.run([sys.executable, str(run_behaviors._CODE_GRAPH), "--build",
                        "--dir", proj, "--non-interactive"],
                       capture_output=True, text=True, check=True)

        with open(os.path.join(proj, "knowledge-base", ".graph", "graph.json")) as f:
            block = json.load(f)["substrate"]["unmapped_source"]
        self.assertEqual(block["files"], 12, "fixture must actually have blind spots")

        fp = run_behaviors.static_fingerprint(
            {"behavior_id": "BEH-Z", "entry": "src/b.ts"}, proj)
        self.assertEqual(fp["coverage"], "static")
        self.assertTrue(fp["exercises"], "a blind spot must not empty the closure")

    def test_a_genuinely_empty_closure_is_still_a_real_answer(self):
        """A file that imports nothing is not a failure, and must not be reported as one."""
        beh = {"behavior_id": "BEH-X", "entry": "app/api/x/route.ts"}
        with mock.patch.object(run_behaviors, "_code_graph_deps", return_value=([], None)):
            fp = run_behaviors.static_fingerprint(beh, self.proj)
        self.assertEqual(fp["coverage"], "static")
        self.assertEqual([e["path"] for e in fp["exercises"]], ["app/api/x/route.ts"])


class FilterOnlyTest(unittest.TestCase):
    def test_keeps_only_named_behaviors(self):
        behaviors = [
            {"behavior_id": "BEH-001"},
            {"behavior_id": "BEH-002"},
            {"behavior_id": "BEH-003"},
        ]
        got = run_behaviors.filter_only(behaviors, ["BEH-003", "BEH-001"])
        self.assertEqual([b["behavior_id"] for b in got], ["BEH-001", "BEH-003"])

    def test_none_filter_returns_all(self):
        behaviors = [{"behavior_id": "BEH-001"}, {"behavior_id": "BEH-002"}]
        self.assertEqual(run_behaviors.filter_only(behaviors, None), behaviors)


class LoadBehaviorsStatesTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        specs = os.path.join(self.tmp.name, "auth")
        os.makedirs(specs)
        with open(os.path.join(specs, "SPEC-001-passkey-login.md"), "w") as f:
            f.write(SPEC)
        self.specs_dir = self.tmp.name

    def tearDown(self):
        self.tmp.cleanup()

    def test_accepted_loader_still_excludes_confirmed(self):
        got = run_behaviors.load_accepted_behaviors(self.specs_dir)
        ids = sorted(b["behavior_id"] for b in got)
        self.assertEqual(ids, ["BEH-002", "BEH-003"])  # BEH-004 confirmed excluded

    def test_load_behaviors_includes_confirmed_when_requested(self):
        got = run_behaviors.load_behaviors(self.specs_dir, states=("accepted", "confirmed"))
        ids = sorted(b["behavior_id"] for b in got)
        self.assertEqual(ids, ["BEH-002", "BEH-003", "BEH-004"])


class FingerprintBehaviorTest(unittest.TestCase):
    def test_confirmed_uses_static_never_runs_a_test(self):
        beh = {"behavior_id": "BEH-004", "state": "confirmed",
               "level": "integration", "entry": "app/api/x/route.ts"}
        with mock.patch.object(run_behaviors, "static_fingerprint",
                               return_value={"coverage": "static", "exercises": []}) as sf, \
             mock.patch.object(run_behaviors, "run_unit_behavior") as run:
            fp = run_behaviors.fingerprint_behavior(beh, "/proj", "c1")
        sf.assert_called_once()
        run.assert_not_called()
        self.assertEqual(fp["coverage"], "static")

    def test_confirmed_with_unit_adapter_is_still_not_executed(self):
        # State wins over level/adapter: a confirmed behavior naming a vitest
        # test that does not exist yet must NOT be executed.
        beh = {"behavior_id": "BEH-005", "state": "confirmed",
               "level": "unit", "adapter": "vitest", "locator": "x.test.ts::t"}
        with mock.patch.object(run_behaviors, "run_unit_behavior") as run, \
             mock.patch.object(run_behaviors, "static_fingerprint",
                               return_value={"coverage": "unknown", "exercises": [], "reason": "no-entry"}) as sf:
            run_behaviors.fingerprint_behavior(beh, "/proj", "c1")
        run.assert_not_called()
        sf.assert_called_once()

    def test_accepted_unit_vitest_is_executed(self):
        beh = {"behavior_id": "BEH-002", "state": "accepted",
               "level": "unit", "adapter": "vitest", "locator": "x.test.ts::t"}
        with mock.patch.object(run_behaviors, "run_unit_behavior",
                               return_value={"coverage": "observed", "exercises": []}) as run:
            fp = run_behaviors.fingerprint_behavior(beh, "/proj", "c1")
        run.assert_called_once()
        self.assertEqual(fp["coverage"], "observed")

    def test_accepted_integration_uses_static(self):
        beh = {"behavior_id": "BEH-003", "state": "accepted", "level": "integration",
               "entry": "app/api/x/route.ts"}
        with mock.patch.object(run_behaviors, "static_fingerprint",
                               return_value={"coverage": "static", "exercises": []}) as sf:
            fp = run_behaviors.fingerprint_behavior(beh, "/proj", "c1")
        sf.assert_called_once()
        self.assertEqual(fp["coverage"], "static")

    def test_accepted_other_level_is_level_deferred(self):
        beh = {"behavior_id": "BEH-001", "state": "accepted", "level": "e2e", "adapter": "cucumber"}
        fp = run_behaviors.fingerprint_behavior(beh, "/proj", "c1")
        self.assertEqual(fp["coverage"], "unknown")
        self.assertEqual(fp["reason"], "level-deferred")


class DeclaredAddressesAreContainedBeforeTheyAreActedOnTest(unittest.TestCase):
    """SEC-013's residual: the runner reached the filesystem with a spec-supplied path.

    `verify_links` has refused an escaping `locator` or `entry` at Tier-1 for some
    time, and the temptation is to read that as coverage. It is not: it is a
    different command in a different process, and `behavior_graph` shells straight
    into `run_behaviors.py` with nothing in front of it. So the runner took a
    string out of checked-in spec frontmatter and put it into
    `os.path.join(project_dir, entry)` — which discards `project_dir` outright for
    an absolute value — and into a `pnpm vitest` / `pytest` argv run with the
    project as `cwd`.

    There are three kinds of test below and they are not interchangeable. An
    earlier version of this docstring claimed all of them asserted a sink was not
    reached; four did, and a reader who takes the whole class for guard-regression
    coverage trusts it further than it goes. Named, so the claim can be checked:

    **Sink tests** — `..._never_becomes_an_argv`,
    `..._never_reaches_the_pytest_executor_either`, `..._is_never_stat_ed`,
    `..._does_not_reach_the_real_filesystem`, `..._refusal_is_not_a_test_failure`,
    `..._costs_one_behavior_not_the_run`. Each asserts a sink was NOT reached,
    because a refusal that still stats the file or spawns the process is not a
    refusal. Revert the guard in `fingerprint_behavior` (`uncontained =
    _uncontained_address(behavior)` -> `uncontained = None`) and every one of the
    six goes red. Measured on that revert: 26 `assert_not_called` failures across
    the six (`run_unit_behavior` 6, `run_pytest_behavior` 5, `static_fingerprint`
    10, `subprocess.run` 5), plus three rows of `..._costs_one_behavior_not_the_run`
    that never reach their assertion because the malformed scalar raises the
    uncaught `TypeError` first — which is that test's own subject, so it is the
    right red for those rows and not a weaker one.

    **A shape test** — `..._names_the_field_and_the_value_on_stderr`. It pins what
    the refusal *says*, not what it declines to do, and the stderr line is the only
    part of a refusal an operator ever sees. It goes red under the revert as well,
    though not on the message: it is the one test here with no sink mocked at all,
    so the revert lets it try to spawn `pnpm` in a `/proj` that does not exist and
    it dies on the `FileNotFoundError`. Red for a true reason, but not the reason
    it is named for — do not read it as guard coverage.

    **False-positive tests** — `..._judged_by_its_path_half_only`,
    `..._ordinary_relative_address_is_untouched`,
    `..._no_address_at_all_still_routes_normally`,
    `..._empty_declared_address_is_not_called_an_escape`. These assert the sink IS
    reached, and they stay GREEN under that revert by design. They are the half of
    the gate that cannot be measured by breaking it: a guard that refused
    everything would pass all six sink tests and fail only these.

    `..._canonical_body_not_a_local_copy` is none of the three — it is ADR-030's
    import identity check, and it also stays green under the revert.
    """

    # (label, locator) — the escaping shapes, judged in both path flavours on every
    # host. The two Windows rows are not decoration: `ntpath.isabs` changed in 3.13
    # so a rooted path with no drive stopped being absolute there, which is exactly
    # the drift `containment.escapes` exists to absorb, and a host-flavour test
    # would pass on Linux CI while the rule leaked on Windows.
    ESCAPING = (
        ("posix absolute", "/etc/passwd"),
        ("parent traversal", "../../../etc/passwd"),
        ("traversal mid-path", "tests/../../outside/x.test.ts"),
        ("windows drive", "C:\\Windows\\System32\\x.test.ts"),
        ("windows rooted, no drive", "\\Windows\\System32\\x.test.ts"),
    )

    def test_an_escaping_locator_never_becomes_an_argv(self):
        for label, locator in self.ESCAPING:
            with self.subTest(label):
                beh = {"behavior_id": "BEH-666", "state": "accepted", "level": "unit",
                       "adapter": "vitest", "locator": locator}
                with mock.patch.object(run_behaviors, "run_unit_behavior") as run, \
                     mock.patch.object(run_behaviors, "subprocess") as sp:
                    fp = run_behaviors.fingerprint_behavior(beh, "/proj", "c1")
                run.assert_not_called()
                sp.run.assert_not_called()
                self.assertEqual(fp["coverage"], "unknown")
                self.assertEqual(fp["reason"], "locator-escapes-project")

    def test_an_escaping_locator_never_reaches_the_pytest_executor_either(self):
        # The Python half of the same sink. `pytest_argv` builds a node id from the
        # locator and hands it to `sys.executable -m pytest` with cwd=project.
        for label, locator in self.ESCAPING:
            with self.subTest(label):
                beh = {"behavior_id": "BEH-667", "state": "accepted", "level": "unit",
                       "adapter": "pytest", "locator": locator + "::test_x"}
                with mock.patch.object(run_behaviors, "run_pytest_behavior") as run:
                    fp = run_behaviors.fingerprint_behavior(beh, "/proj", "c1")
                run.assert_not_called()
                self.assertEqual(fp["reason"], "locator-escapes-project")

    def test_an_escaping_entry_is_never_stat_ed(self):
        # `static_fingerprint` owns the `os.path.exists(os.path.join(project_dir,
        # entry))` probe, so proving it is not called is proving the stat did not
        # happen. Both states that route there are covered: `confirmed` (state wins
        # over level) and accepted `integration`.
        for state, level in (("confirmed", "integration"), ("accepted", "integration")):
            for label, entry in self.ESCAPING:
                with self.subTest(f"{state}/{label}"):
                    beh = {"behavior_id": "BEH-668", "state": state, "level": level,
                           "entry": entry}
                    with mock.patch.object(run_behaviors, "static_fingerprint") as sf:
                        fp = run_behaviors.fingerprint_behavior(beh, "/proj", "c1")
                    sf.assert_not_called()
                    self.assertEqual(fp["coverage"], "unknown")
                    self.assertEqual(fp["reason"], "entry-escapes-project")

    def test_an_escaping_entry_does_not_reach_the_real_filesystem(self):
        # The same claim without a mock standing in for the sink: a real project
        # root, a real absolute entry, and nothing spawned. If the guard is
        # reverted this reaches `_git_head` and then code-graph.
        with tempfile.TemporaryDirectory() as proj:
            beh = {"behavior_id": "BEH-669", "state": "confirmed", "level": "integration",
                   "entry": os.path.join(os.path.abspath(os.sep), "etc", "passwd")}
            with mock.patch.object(run_behaviors.subprocess, "run") as spawn:
                fp = run_behaviors.fingerprint_behavior(beh, proj, "c1")
            spawn.assert_not_called()
            self.assertEqual(fp["reason"], "entry-escapes-project")

    def test_a_refusal_is_not_a_test_failure(self):
        # `merge_fingerprint` treats `test-failed` alone as invalidating: it wipes
        # committed edges and blocks a commit (ADR-009). A spec typo must not do
        # that, and an escaping locator must not read as a red test either.
        beh = {"behavior_id": "BEH-670", "state": "accepted", "level": "unit",
               "adapter": "vitest", "locator": "/etc/passwd"}
        with mock.patch.object(run_behaviors, "run_unit_behavior") as run:
            fp = run_behaviors.fingerprint_behavior(beh, "/proj", "c1")
        # The sink first: a fingerprint that merely *says* it is not a test failure,
        # produced after the test was run anyway, would satisfy the two assertions
        # below and mean nothing.
        run.assert_not_called()
        self.assertNotEqual(fp["reason"], "test-failed")
        self.assertEqual(fp["exercises"], [])

    def test_the_locator_is_judged_by_its_path_half_only(self):
        # A fragment is a runner selector, not a path: `-t` takes a test title and a
        # pytest `[...]` id takes a parametrize value. Judging the whole locator
        # reads as containment and is not — it refuses the behavior that *tests*
        # traversal, whose title or parametrize id says `../../etc/passwd` because
        # that is the input under test. `verify_links` draws the line in the same
        # place (it checks `rel_path`, not `locator`), and these locators escape as
        # whole strings while their path halves do not.
        for label, beh, sink in (
            ("vitest title",
             {"behavior_id": "BEH-671", "state": "accepted", "level": "unit",
              "adapter": "vitest", "locator": "lib/paths.test.ts::rejects ../../etc/passwd"},
             "run_unit_behavior"),
            ("pytest parametrize id",
             {"behavior_id": "BEH-672", "state": "accepted", "level": "unit",
              "adapter": "pytest",
              "locator": "tests/test_paths.py::test_rejects[../../etc/passwd]"},
             "run_pytest_behavior"),
            ("gherkin slug",
             {"behavior_id": "BEH-673", "state": "accepted", "level": "integration",
              "adapter": "cucumber", "locator": "features/a.feature#unknown/../email"},
             "static_fingerprint"),
        ):
            with self.subTest(label):
                self.assertTrue(run_behaviors.escapes(beh["locator"]),
                                "the whole locator must escape, or this proves nothing")
                with mock.patch.object(run_behaviors, sink,
                                       return_value={"coverage": "observed",
                                                     "exercises": []}) as run:
                    fp = run_behaviors.fingerprint_behavior(beh, "/proj", "c1")
                run.assert_called_once()
                self.assertEqual(fp["coverage"], "observed")

    def test_an_ordinary_relative_address_is_untouched(self):
        for label, beh, sink in (
            ("unit vitest",
             {"behavior_id": "BEH-002", "state": "accepted", "level": "unit",
              "adapter": "vitest", "locator": "lib/webauthn.test.ts::rejects it"},
             "run_unit_behavior"),
            ("unit pytest",
             {"behavior_id": "BEH-003", "state": "accepted", "level": "unit",
              "adapter": "pytest", "locator": "tests/test_a.py::TestX::test_y"},
             "run_pytest_behavior"),
            ("confirmed with entry",
             {"behavior_id": "BEH-004", "state": "confirmed", "level": "integration",
              "entry": "app/api/x/route.ts"},
             "static_fingerprint"),
            ("dotted but not dot-dot",
             {"behavior_id": "BEH-005", "state": "confirmed", "level": "integration",
              "entry": "app/.well-known/x.ts"},
             "static_fingerprint"),
        ):
            with self.subTest(label):
                with mock.patch.object(run_behaviors, sink,
                                       return_value={"coverage": "static",
                                                     "exercises": []}) as called:
                    run_behaviors.fingerprint_behavior(beh, "/proj", "c1")
                called.assert_called_once()

    def test_a_behavior_with_no_address_at_all_still_routes_normally(self):
        # `proposed`/`confirmed` are pre-test, so an absent locator is ordinary and
        # the guard must not turn "nothing declared" into "declared something bad".
        beh = {"behavior_id": "BEH-006", "state": "accepted", "level": "e2e",
               "adapter": "cucumber"}
        fp = run_behaviors.fingerprint_behavior(beh, "/proj", "c1")
        self.assertEqual(fp["reason"], "level-deferred")

    def test_a_non_string_address_costs_one_behavior_not_the_run(self):
        # Frontmatter scalars are not all strings: `locator: 123` parses to an int
        # and a flow sequence to a list. Both used to reach `"#" in locator` or
        # `os.path.join` and raise an uncaught TypeError out of the whole
        # `--emit-fingerprints` pass, losing every other behavior's fingerprint.
        #
        # The falsy rows are the ones the first spelling of the gate let through,
        # because it asked `if locator:` and that question cannot tell "declared as
        # 0" from "not declared at all". Measured on a two-behavior fixture spec
        # before the fix: `locator: 0` exited 1 with `TypeError: argument of type
        # 'int' is not iterable` and printed no JSON at all, so the honest
        # behavior's fingerprint went with it, and `locator: []` — a list is
        # iterable, so `"#" in []` is merely False rather than a TypeError —
        # travelled intact into `subprocess.run(["pnpm", "vitest", "run", []])`.
        #
        # Only `subprocess.run` is mocked and both executors are left real, because
        # a mocked `run_unit_behavior` swallows the very TypeError this test is
        # about. One sink is enough to name: `static_fingerprint` spawns `_git_head`
        # before it stats anything, so an unspawned process proves the stat did not
        # happen either.
        #
        # The stub returns a real `CompletedProcess` rather than a bare MagicMock so
        # that a regression fails on `assert_not_called` and says so. A MagicMock
        # return makes `result.returncode != 0` truthy, and the row then dies in
        # `sys.stderr.write(result.stdout + result.stderr)` with a TypeError about
        # MagicMock — red either way, but red about the wrong thing.
        green = subprocess.CompletedProcess([], 0, "", "")
        for label, beh, reason in (
            ("int locator",
             {"behavior_id": "BEH-007", "state": "accepted", "level": "unit",
              "adapter": "vitest", "locator": 123}, "locator-escapes-project"),
            ("zero locator",
             {"behavior_id": "BEH-008", "state": "accepted", "level": "unit",
              "adapter": "vitest", "locator": 0}, "locator-escapes-project"),
            ("list locator",
             {"behavior_id": "BEH-009", "state": "accepted", "level": "unit",
              "adapter": "vitest", "locator": ["lib/a.test.ts"]}, "locator-escapes-project"),
            ("empty list locator",
             {"behavior_id": "BEH-010", "state": "accepted", "level": "unit",
              "adapter": "vitest", "locator": []}, "locator-escapes-project"),
            ("int entry",
             {"behavior_id": "BEH-011", "state": "confirmed", "level": "integration",
              "entry": 7}, "entry-escapes-project"),
            ("zero entry",
             {"behavior_id": "BEH-012", "state": "confirmed", "level": "integration",
              "entry": 0}, "entry-escapes-project"),
            ("empty list entry",
             {"behavior_id": "BEH-013", "state": "confirmed", "level": "integration",
              "entry": []}, "entry-escapes-project"),
        ):
            with self.subTest(label):
                with mock.patch.object(run_behaviors.subprocess, "run",
                                       return_value=green) as spawn:
                    fp = run_behaviors.fingerprint_behavior(beh, "/proj", "c1")
                spawn.assert_not_called()
                self.assertEqual(fp["reason"], reason)

    def test_an_empty_declared_address_is_not_called_an_escape(self):
        # The one present-but-falsy value the gate deliberately does NOT refuse.
        # `escapes("")` is False, so `locator-escapes-project` would be a false
        # statement about it, and the fix for the falsy-scalar hole above must not
        # be spelled `if locator is not None: refuse unless truthy` — that reads as
        # containment and is not. An empty address keeps its existing fall-through
        # and the adapter decides what it means.
        self.assertFalse(run_behaviors.escapes(""))
        for label, beh, sink in (
            ("empty locator",
             {"behavior_id": "BEH-014", "state": "accepted", "level": "unit",
              "adapter": "vitest", "locator": ""}, "run_unit_behavior"),
            ("empty entry",
             {"behavior_id": "BEH-015", "state": "confirmed", "level": "integration",
              "entry": ""}, "static_fingerprint"),
        ):
            with self.subTest(label):
                with mock.patch.object(run_behaviors, sink,
                                       return_value={"coverage": "unknown",
                                                     "exercises": []}) as called:
                    fp = run_behaviors.fingerprint_behavior(beh, "/proj", "c1")
                called.assert_called_once()
                # Not `assertNotIn("reason", fp)`: the sink's stub return has no
                # `reason` key, so that would pass whether or not it was consulted.
                self.assertEqual(fp, {"coverage": "unknown", "exercises": []})

    def test_the_rule_is_the_canonical_body_not_a_local_copy(self):
        # ADR-030: the containment rule is imported, not re-typed. A hand-written
        # twin here would pass every test above while drifting from the Tier-1
        # gate at the margin, and the margin is where a locator gets through.
        from containment import escapes as canonical
        self.assertIs(run_behaviors.escapes, canonical)

    def test_the_refusal_names_the_field_and_the_value_on_stderr(self):
        beh = {"behavior_id": "BEH-010", "state": "accepted", "level": "unit",
               "adapter": "vitest", "locator": "/etc/passwd"}
        with mock.patch.object(run_behaviors.sys, "stderr") as err:
            run_behaviors.fingerprint_behavior(beh, "/proj", "c1")
        message = "".join(call.args[0] for call in err.write.call_args_list)
        self.assertIn("BEH-010", message)
        self.assertIn("locator", message)
        self.assertIn("/etc/passwd", message)


if __name__ == "__main__":
    unittest.main()
