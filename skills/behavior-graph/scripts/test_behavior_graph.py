import json
import os
import tempfile
import unittest
import unittest.mock as mock

import behavior_graph


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
    entry: app/api/auth/passkey/authenticate/start/route.ts
  - behavior_id: BEH-004
    title: Authentication start rejects a malformed body (test owed)
    state: confirmed
    level: integration
    entry: app/api/auth/passkey/authenticate/start/route.ts
  - behavior_id: BEH-001
    title: Successful passkey login
    state: proposed
    level: e2e
    adapter: cucumber
    locator: features/auth/passkey-login.feature#successful-passkey-login
---
# body
"""


class ProjectBehaviorsTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        d = os.path.join(self.tmp.name, "auth")
        os.makedirs(d)
        with open(os.path.join(d, "SPEC-001-passkey-login.md"), "w") as f:
            f.write(SPEC)
        self.specs = self.tmp.name

    def tearDown(self):
        self.tmp.cleanup()

    def test_projects_accepted_and_confirmed_behaviors(self):
        got = behavior_graph.project_behaviors(self.specs)
        # BEH-001 proposed -> excluded; BEH-004 confirmed -> included.
        self.assertEqual(sorted(got), ["BEH-002", "BEH-003", "BEH-004"])
        self.assertEqual(got["BEH-004"]["state"], "confirmed")
        self.assertEqual(
            got["BEH-003"],
            {
                "spec_id": "SPEC-001",
                "state": "accepted",
                "level": "integration",
                "adapter": "cucumber",
                "locator": "features/auth/passkey-login.feature#unknown-email-does-not-reveal-whether-a-user-exists",
            },
        )


class MergeFingerprintTest(unittest.TestCase):
    def test_observed_incoming_wins(self):
        out = behavior_graph.merge_fingerprint(
            {"coverage": "static", "exercises": [{"path": "a"}]},
            {"coverage": "observed", "exercises": [{"path": "b"}]},
        )
        self.assertEqual(out, {"coverage": "observed", "exercises": [{"path": "b"}]})

    def test_static_does_not_downgrade_observed(self):
        out = behavior_graph.merge_fingerprint(
            {"coverage": "observed", "exercises": [{"path": "obs"}]},
            {"coverage": "static", "exercises": [{"path": "stat"}]},
        )
        self.assertEqual(out, {"coverage": "observed", "exercises": [{"path": "obs"}]})

    def test_static_with_no_prior_is_static(self):
        out = behavior_graph.merge_fingerprint(
            None, {"coverage": "static", "exercises": [{"path": "stat"}]}
        )
        self.assertEqual(out, {"coverage": "static", "exercises": [{"path": "stat"}]})

    def test_test_failed_invalidates_even_observed_prior(self):
        out = behavior_graph.merge_fingerprint(
            {"coverage": "observed", "exercises": [{"path": "obs"}]},
            {"coverage": "unknown", "exercises": [], "reason": "test-failed"},
        )
        self.assertEqual(out, {"coverage": "unknown", "exercises": [], "reason": "test-failed"})

    def test_other_unknown_preserves_prior(self):
        out = behavior_graph.merge_fingerprint(
            {"coverage": "observed", "exercises": [{"path": "obs"}]},
            {"coverage": "unknown", "exercises": [], "reason": "level-deferred"},
        )
        self.assertEqual(out, {"coverage": "observed", "exercises": [{"path": "obs"}]})

    def test_unknown_with_no_prior_keeps_reason(self):
        out = behavior_graph.merge_fingerprint(
            None, {"coverage": "unknown", "exercises": [], "reason": "no-entry"}
        )
        self.assertEqual(out, {"coverage": "unknown", "exercises": [], "reason": "no-entry"})


class BuildTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.proj = self.tmp.name
        specs = os.path.join(self.proj, "knowledge-base", "specs", "auth")
        os.makedirs(specs)
        with open(os.path.join(specs, "SPEC-001-passkey-login.md"), "w") as f:
            f.write(SPEC)

    def tearDown(self):
        self.tmp.cleanup()

    def test_build_merges_runner_fingerprints_and_writes(self):
        runner_out = {
            "version": 1,
            "commit": "deadbeef",
            "fingerprints": {
                "BEH-002": {"coverage": "observed", "exercises": [{"path": "lib/webauthn.ts", "source": "observed", "confidence": 0.8, "freshness": "deadbeef"}]},
                "BEH-003": {"coverage": "static", "exercises": [{"path": "app/api/auth/passkey/authenticate/start/route.ts", "source": "static", "confidence": 0.5, "freshness": "deadbeef"}]},
            },
        }
        with mock.patch.object(behavior_graph, "_run_behavior_runner", return_value=runner_out):
            data = behavior_graph.build(self.proj)
        self.assertEqual(data["commit"], "deadbeef")
        self.assertEqual(data["behaviors"]["BEH-002"]["coverage"], "observed")
        self.assertEqual(data["behaviors"]["BEH-002"]["level"], "unit")  # projected field present
        self.assertEqual(data["behaviors"]["BEH-003"]["coverage"], "static")
        # behavior.json was written under the git-ignored .graph dir
        path = os.path.join(self.proj, "knowledge-base", ".graph", "behavior.json")
        self.assertTrue(os.path.exists(path))

    def test_build_preserves_prior_observed_on_unknown(self):
        # Seed a prior behavior.json with an observed BEH-003 edge.
        behavior_graph.write_behavior_json(self.proj, {
            "version": 1, "commit": "old",
            "behaviors": {"BEH-003": {"spec_id": "SPEC-001", "state": "accepted",
                                      "level": "integration", "adapter": "cucumber",
                                      "locator": "x", "coverage": "observed",
                                      "exercises": [{"path": "lib/prior.ts"}]}},
        })
        runner_out = {"version": 1, "commit": "new", "fingerprints": {
            "BEH-002": {"coverage": "observed", "exercises": [{"path": "lib/webauthn.ts"}]},
            "BEH-003": {"coverage": "unknown", "exercises": [], "reason": "level-deferred"},
        }}
        with mock.patch.object(behavior_graph, "_run_behavior_runner", return_value=runner_out):
            data = behavior_graph.build(self.proj)
        # prior observed edge preserved despite the unknown run
        self.assertEqual(data["behaviors"]["BEH-003"]["coverage"], "observed")
        self.assertEqual(data["behaviors"]["BEH-003"]["exercises"], [{"path": "lib/prior.ts"}])


class WriteBehaviorJsonGitignoreTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.proj = self.tmp.name

    def tearDown(self):
        self.tmp.cleanup()

    def test_creates_gitignore_on_fresh_graph_dir(self):
        behavior_graph.write_behavior_json(self.proj, {"version": 1, "behaviors": {}})
        gitignore = os.path.join(self.proj, "knowledge-base", ".graph", ".gitignore")
        self.assertTrue(os.path.exists(gitignore))
        with open(gitignore, encoding="utf-8") as f:
            contents = f.read()
        self.assertEqual(contents.strip(), "*")

    def test_does_not_overwrite_existing_gitignore(self):
        graph_dir = os.path.join(self.proj, "knowledge-base", ".graph")
        os.makedirs(graph_dir)
        gitignore = os.path.join(graph_dir, ".gitignore")
        with open(gitignore, "w", encoding="utf-8") as f:
            f.write("existing\n")
        behavior_graph.write_behavior_json(self.proj, {"version": 1, "behaviors": {}})
        with open(gitignore, encoding="utf-8") as f:
            contents = f.read()
        self.assertEqual(contents, "existing\n")


class DirectionBTest(unittest.TestCase):
    def test_returns_exercised_paths(self):
        behaviors = {"BEH-003": {"exercises": [{"path": "lib/webauthn.ts"}, {"path": "lib/prisma.ts"}]}}
        self.assertEqual(behavior_graph.direction_b(behaviors, "BEH-003"),
                         ["lib/prisma.ts", "lib/webauthn.ts"])

    def test_unknown_behavior_returns_empty(self):
        self.assertEqual(behavior_graph.direction_b({}, "BEH-999"), [])


class DirectionATest(unittest.TestCase):
    def test_affected_when_exercises_intersect_impact(self):
        behaviors = {
            "BEH-002": {"exercises": [{"path": "lib/webauthn.ts"}]},
            "BEH-003": {"exercises": [{"path": "app/api/x/route.ts"}, {"path": "lib/webauthn.ts"}]},
            "BEH-009": {"exercises": [{"path": "lib/unrelated.ts"}]},
        }
        impact = {"lib/webauthn.ts", "app/api/x/route.ts"}
        with mock.patch.object(behavior_graph, "_code_graph_impact", return_value=impact):
            got = behavior_graph.direction_a(behaviors, ["lib/webauthn.ts"], "/proj")
        self.assertEqual(got, ["BEH-002", "BEH-003"])  # BEH-009 not affected, sorted

    def test_none_affected_returns_empty(self):
        behaviors = {"BEH-002": {"exercises": [{"path": "lib/webauthn.ts"}]}}
        with mock.patch.object(behavior_graph, "_code_graph_impact", return_value={"lib/other.ts"}):
            self.assertEqual(behavior_graph.direction_a(behaviors, ["lib/other.ts"], "/proj"), [])


class RegressionCheckTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.proj = self.tmp.name
        behavior_graph.write_behavior_json(self.proj, {
            "version": 1, "commit": "base",
            "behaviors": {
                "BEH-002": {"spec_id": "SPEC-001", "state": "accepted", "level": "unit",
                            "adapter": "vitest", "locator": "x", "coverage": "observed",
                            "exercises": [{"path": "lib/webauthn.ts"}]},
                "BEH-003": {"spec_id": "SPEC-001", "state": "accepted", "level": "integration",
                            "adapter": "cucumber", "locator": "y", "coverage": "static",
                            "exercises": [{"path": "lib/other.ts"}]},
            },
        })

    def tearDown(self):
        self.tmp.cleanup()

    def test_no_affected_exits_zero(self):
        with mock.patch.object(behavior_graph, "_changed_files", return_value=["README.md"]), \
             mock.patch.object(behavior_graph, "_code_graph_impact", return_value={"README.md"}):
            report, code = behavior_graph.regression_check(self.proj, "base")
        self.assertEqual(code, 0)
        self.assertEqual(report["affected"], [])

    def test_affected_passing_exits_zero(self):
        runner_out = {"version": 1, "commit": "new", "fingerprints": {
            "BEH-002": {"coverage": "observed", "exercises": [{"path": "lib/webauthn.ts"}]}}}
        with mock.patch.object(behavior_graph, "_changed_files", return_value=["lib/webauthn.ts"]), \
             mock.patch.object(behavior_graph, "_code_graph_impact", return_value={"lib/webauthn.ts"}), \
             mock.patch.object(behavior_graph, "_run_behavior_runner", return_value=runner_out) as run:
            report, code = behavior_graph.regression_check(self.proj, "base")
        run.assert_called_once_with(self.proj, only=["BEH-002"])  # only the affected re-run
        self.assertEqual(code, 0)
        self.assertEqual(report["affected"], ["BEH-002"])
        self.assertEqual(report["failed"], [])

    def test_affected_failing_blocks(self):
        runner_out = {"version": 1, "commit": "new", "fingerprints": {
            "BEH-002": {"coverage": "unknown", "exercises": [], "reason": "test-failed"}}}
        with mock.patch.object(behavior_graph, "_changed_files", return_value=["lib/webauthn.ts"]), \
             mock.patch.object(behavior_graph, "_code_graph_impact", return_value={"lib/webauthn.ts"}), \
             mock.patch.object(behavior_graph, "_run_behavior_runner", return_value=runner_out):
            report, code = behavior_graph.regression_check(self.proj, "base")
        self.assertEqual(code, 1)
        self.assertEqual(report["failed"], ["BEH-002"])


class ConfirmedGraphTest(unittest.TestCase):
    def test_run_behavior_runner_requests_accepted_and_confirmed(self):
        captured = {}

        def fake_run(argv, capture_output, text, check):
            captured["argv"] = argv
            r = mock.MagicMock()
            r.stdout = '{"version": 1, "commit": "x", "fingerprints": {}}'
            return r

        with mock.patch.object(behavior_graph.subprocess, "run", side_effect=fake_run):
            behavior_graph._run_behavior_runner("/proj")
        argv = captured["argv"]
        self.assertIn("--states", argv)
        i = argv.index("--states")
        self.assertEqual(argv[i + 1:i + 3], ["accepted", "confirmed"])

    def test_confirmed_affected_but_never_blocks(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        proj = tmp.name
        behavior_graph.write_behavior_json(proj, {
            "version": 1, "commit": "base",
            "behaviors": {
                "BEH-004": {"spec_id": "SPEC-001", "state": "confirmed", "level": "integration",
                            "coverage": "static",
                            "exercises": [{"path": "app/api/x/route.ts"}]},
            },
        })
        # The confirmed behavior is affected; the runner returns a static
        # fingerprint (never test-failed), so the check must not block.
        runner_out = {"version": 1, "commit": "new", "fingerprints": {
            "BEH-004": {"coverage": "static",
                        "exercises": [{"path": "app/api/x/route.ts", "source": "static",
                                       "confidence": 0.5, "freshness": "new"}]}}}
        with mock.patch.object(behavior_graph, "_changed_files", return_value=["app/api/x/route.ts"]), \
             mock.patch.object(behavior_graph, "_code_graph_impact", return_value={"app/api/x/route.ts"}), \
             mock.patch.object(behavior_graph, "_run_behavior_runner", return_value=runner_out):
            report, code = behavior_graph.regression_check(proj, "base")
        self.assertEqual(code, 0)
        self.assertEqual(report["failed"], [])
        self.assertEqual(report["affected"], ["BEH-004"])


class ConfirmedDoesNotBlockOnTestFailedTest(unittest.TestCase):
    """Guard: a confirmed behavior with test-failed incoming must NOT add to failed.

    This test proves the defense-in-depth invariant: only `accepted` behaviors
    can ever block regression_check. The runner contract is the first line of
    defense (it never executes confirmed), but the gate itself must enforce this
    locally so SP2/SP3 executable paths cannot accidentally gate on non-accepted.
    """

    def test_confirmed_with_test_failed_does_not_block(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        proj = tmp.name
        behavior_graph.write_behavior_json(proj, {
            "version": 1, "commit": "base",
            "behaviors": {
                "BEH-004": {"spec_id": "SPEC-001", "state": "confirmed", "level": "integration",
                            "coverage": "static",
                            "exercises": [{"path": "app/api/x/route.ts"}]},
            },
        })
        # Simulate a future bug: runner somehow returns test-failed for a confirmed behavior.
        runner_out = {"version": 1, "commit": "new", "fingerprints": {
            "BEH-004": {"coverage": "unknown", "exercises": [], "reason": "test-failed"}}}
        with mock.patch.object(behavior_graph, "_changed_files", return_value=["app/api/x/route.ts"]), \
             mock.patch.object(behavior_graph, "_code_graph_impact", return_value={"app/api/x/route.ts"}), \
             mock.patch.object(behavior_graph, "_run_behavior_runner", return_value=runner_out):
            report, code = behavior_graph.regression_check(proj, "base")
        # Must not block: confirmed is advisory only, never gates regardless of incoming reason.
        self.assertEqual(code, 0, "confirmed behavior with test-failed must not exit 1")
        self.assertEqual(report["failed"], [], "confirmed behavior must not appear in failed")
        self.assertEqual(report["affected"], ["BEH-004"])


class SurfaceTest(unittest.TestCase):
    SPEC = """---
id: SPEC-100
title: Surface fixture
category: features
status: implemented
behaviors:
  - behavior_id: BEH-002
    title: Accepted unit behavior
    state: accepted
    level: unit
    adapter: vitest
    locator: lib/webauthn.test.ts::x
  - behavior_id: BEH-006
    title: Confirmed integration behavior
    state: confirmed
    level: integration
    entry: app/api/x/route.ts
  - behavior_id: BEH-004
    title: Proposed lock behavior
    state: proposed
    level: integration
    entry: app/api/posts/lock.ts
  - behavior_id: BEH-005
    title: Proposed without entry (worklist-only)
    state: proposed
---
# body
"""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.proj = self.tmp.name
        specs = os.path.join(self.proj, "knowledge-base", "specs", "features")
        os.makedirs(specs)
        with open(os.path.join(specs, "SPEC-100.md"), "w") as f:
            f.write(self.SPEC)
        # code-graph file set (graph.json keys) — the recognised source files
        graph_dir = os.path.join(self.proj, "knowledge-base", ".graph")
        os.makedirs(graph_dir)
        with open(os.path.join(graph_dir, "graph.json"), "w") as f:
            json.dump({"version": 1, "files": {
                "lib/webauthn.ts": {}, "app/api/x/route.ts": {},
                "app/api/posts/lock.ts": {}, "lib/util.ts": {},
            }}, f)
        # projected graph: accepted BEH-002 + confirmed BEH-006 with exercises
        behavior_graph.write_behavior_json(self.proj, {
            "version": 1, "commit": "base",
            "behaviors": {
                "BEH-002": {"spec_id": "SPEC-100", "state": "accepted",
                            "coverage": "observed", "exercises": [{"path": "lib/webauthn.ts"}]},
                "BEH-006": {"spec_id": "SPEC-100", "state": "confirmed",
                            "coverage": "static", "exercises": [{"path": "app/api/x/route.ts"}]},
            },
        })

    def _surface(self, changed, impact):
        with mock.patch.object(behavior_graph, "_changed_files", return_value=changed), \
             mock.patch.object(behavior_graph, "_code_graph_impact", return_value=set(impact)):
            return behavior_graph.surface(self.proj, "base")

    def test_proposed_with_entry_in_impact_surfaces(self):
        r = self._surface(["app/api/posts/lock.ts"], ["app/api/posts/lock.ts"])
        ids = [c["behavior_id"] for c in r["validate_candidates"]]
        self.assertIn("BEH-004", ids)      # proposed, entry hit
        self.assertNotIn("BEH-005", ids)   # proposed, no entry -> not surfaced

    def test_dependency_level_hit_surfaces_proposed(self):
        # lib/util.ts changed; impact includes the entry as a transitive dependent.
        # This is the precise (not coarse) match: entry not in changed, but in impact.
        r = self._surface(["lib/util.ts"], ["lib/util.ts", "app/api/posts/lock.ts"])
        ids = [c["behavior_id"] for c in r["validate_candidates"]]
        self.assertIn("BEH-004", ids)

    def test_confirmed_surfaces_accepted_is_context_only(self):
        r = self._surface(
            ["lib/webauthn.ts", "app/api/x/route.ts"],
            ["lib/webauthn.ts", "app/api/x/route.ts"],
        )
        self.assertEqual(r["affected_accepted"], ["BEH-002"])
        ids = [c["behavior_id"] for c in r["validate_candidates"]]
        self.assertIn("BEH-006", ids)        # confirmed surfaced to validate
        self.assertNotIn("BEH-002", ids)     # accepted is NOT a validate candidate

    def test_recall_gap_flags_uncovered_changed_source(self):
        # lib/util.ts is a graph source file in no exercise and no declared entry.
        r = self._surface(["lib/util.ts"], ["lib/util.ts"])
        self.assertIn("lib/util.ts", r["recall_gaps"])

    def test_declared_entry_is_not_a_recall_gap(self):
        r = self._surface(["app/api/posts/lock.ts"], ["app/api/posts/lock.ts"])
        self.assertNotIn("app/api/posts/lock.ts", r["recall_gaps"])

    def test_non_source_changed_file_is_not_a_recall_gap(self):
        # README.md is not a code-graph file -> never a recall gap.
        r = self._surface(["README.md"], ["README.md"])
        self.assertEqual(r["recall_gaps"], [])

    def test_no_graph_degrades_to_note(self):
        import shutil
        shutil.rmtree(os.path.join(self.proj, "knowledge-base", ".graph"))
        r = self._surface(["lib/util.ts"], ["lib/util.ts"])
        self.assertIn("note", r)
        self.assertEqual(r["validate_candidates"], [])
        self.assertEqual(r["recall_gaps"], [])

    def test_no_changes_degrades_to_note(self):
        r = self._surface([], [])
        self.assertIn("note", r)
        self.assertEqual(r["validate_candidates"], [])
        self.assertEqual(r["recall_gaps"], [])
        self.assertEqual(r["affected_accepted"], [])

    def test_covered_union_of_exercises_and_entries(self):
        behaviors = {"X": {"exercises": [{"path": "a.ts"}]}}
        specs_behaviors = [{"entry": "b.ts"}, {"entry": None}, {}]
        self.assertEqual(behavior_graph._covered(behaviors, specs_behaviors), {"a.ts", "b.ts"})

    def test_gaps_lists_uncovered_source_files(self):
        # graph files: webauthn, x/route, posts/lock, util.
        # covered: webauthn (BEH-002 exercise), x/route (BEH-006 exercise+entry),
        #          posts/lock (BEH-004 entry). Only lib/util.ts is uncovered.
        r = behavior_graph.gaps(self.proj)
        self.assertEqual(r["gaps"], ["lib/util.ts"])
        self.assertEqual(r["total"], 1)

    def test_gaps_no_graph_degrades_to_note(self):
        import shutil
        shutil.rmtree(os.path.join(self.proj, "knowledge-base", ".graph"))
        r = behavior_graph.gaps(self.proj)
        self.assertIn("note", r)
        self.assertEqual(r["gaps"], [])
        self.assertEqual(r["total"], 0)

    def test_covering_returns_accepted_behavior_for_file(self):
        r = behavior_graph.covering(self.proj, "lib/webauthn.ts")
        self.assertEqual(r["file"], "lib/webauthn.ts")
        self.assertEqual([c["behavior_id"] for c in r["covering"]], ["BEH-002"])
        self.assertEqual(r["covering"][0]["spec_id"], "SPEC-100")

    def test_covering_excludes_confirmed_behavior(self):
        # BEH-006 (confirmed) exercises app/api/x/route.ts but is NOT accepted,
        # so it must not be returned — only verified behaviors downgrade findings.
        r = behavior_graph.covering(self.proj, "app/api/x/route.ts")
        self.assertEqual(r["covering"], [])

    def test_covering_excludes_noncovering_file(self):
        r = behavior_graph.covering(self.proj, "lib/util.ts")
        self.assertEqual(r["covering"], [])

    def test_covering_no_graph_returns_empty_with_file(self):
        import shutil
        shutil.rmtree(os.path.join(self.proj, "knowledge-base", ".graph"))
        r = behavior_graph.covering(self.proj, "lib/webauthn.ts")
        self.assertEqual(r["file"], "lib/webauthn.ts")
        self.assertEqual(r["covering"], [])


if __name__ == "__main__":
    unittest.main()
