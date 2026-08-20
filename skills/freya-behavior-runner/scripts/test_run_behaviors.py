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

    def tearDown(self):
        self.tmp.cleanup()

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


if __name__ == "__main__":
    unittest.main()
