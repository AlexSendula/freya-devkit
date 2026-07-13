import os
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
        with mock.patch.object(run_behaviors, "_code_graph_deps", return_value=["lib/webauthn.ts", "lib/prisma.ts"]):
            fp = run_behaviors.static_fingerprint(beh, self.proj)
        self.assertEqual(fp["coverage"], "static")
        self.assertEqual(
            [e["path"] for e in fp["exercises"]],
            ["app/api/x/route.ts", "lib/prisma.ts", "lib/webauthn.ts"],
        )
        self.assertTrue(all(e["source"] == "static" for e in fp["exercises"]))

    def test_no_graph_is_unknown_with_reason(self):
        beh = {"behavior_id": "BEH-X", "entry": "app/api/x/route.ts"}
        with mock.patch.object(run_behaviors, "_code_graph_deps", return_value=None):
            fp = run_behaviors.static_fingerprint(beh, self.proj)
        self.assertEqual(fp["coverage"], "unknown")
        self.assertEqual(fp["reason"], "no-graph")
        self.assertEqual(fp["exercises"], [])


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
