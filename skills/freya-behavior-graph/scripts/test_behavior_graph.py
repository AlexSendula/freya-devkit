import io
import json
import os
import shutil
import subprocess
import tempfile
import unittest
import unittest.mock as mock

import behavior_graph
# Import order is load-bearing, not alphabetical: verify_links lives under
# freya-spec-manager, and importing behavior_graph is what puts that scripts/
# directory on sys.path (behavior_graph.py:20). It is imported rather than
# shelled out to because LocatorCheckDivergesFromTier1Test asserts what Tier 1
# says about the same fixture, and a described comparison is one that rots.
import verify_links  # noqa: E402


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


class LoadBehaviorJsonTest(unittest.TestCase):
    def setUp(self):
        self.proj = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.proj, True)
        os.makedirs(os.path.join(self.proj, "knowledge-base", ".graph"))

    def _path(self):
        return os.path.join(self.proj, "knowledge-base", ".graph", "behavior.json")

    def _write(self, text):
        with open(self._path(), "w", encoding="utf-8") as f:
            f.write(text)

    def test_an_unreadable_file_is_not_silently_an_empty_graph(self):
        """BEH-110 is FALSE. This pins what the code actually does, not what the spec claims.

        SPEC-022 states BEH-110 as "A behavior.json that cannot be read says so instead of
        answering as an empty graph", records it `proposed` with `adapter: manual`, and names
        this exact method as where its test should live. The code does the opposite:
        `load_behavior_json` catches `json.JSONDecodeError` and `OSError` and returns `{}` —
        byte for byte the answer a project that has never built a graph gets. SPEC-022's own
        certainty note (80) leaves open "whether BEH-110's silent `{}` is a deliberate
        degradation or the gap it looks like". Measured here: it is the gap, on both the
        corrupt-content path and the cannot-open path.

        The consequence is why it matters and is asserted below. With a half-written
        behavior.json `regression_check` computes no affected behaviors, never starts the
        runner, and exits 0 — so an interrupted build or a badly resolved merge conflict turns
        the Direction-A gate green rather than red, which is the confidently-empty answer
        ADR-005 exists to forbid.

        When the degradation is fixed this test goes red on the assertions below. That is the
        signal to rewrite it as the claim BEH-110 makes and promote the behavior — not to
        delete it, and not to loosen it.
        """
        a_fix_landed = "the silent-{} degradation changed; BEH-110 may now hold — read the docstring"

        self._write('{"version": 1, "behavi')                      # truncated write
        self.assertEqual(behavior_graph.load_behavior_json(self.proj), {}, a_fix_landed)

        os.remove(self._path())
        os.makedirs(self._path())                                  # open() raises OSError
        self.assertEqual(behavior_graph.load_behavior_json(self.proj), {}, a_fix_landed)

        os.rmdir(self._path())
        self._write('{"version": 1, "behavi')
        with mock.patch.object(behavior_graph, "_changed_files", return_value=(["lib/webauthn.ts"], True)), \
             mock.patch.object(behavior_graph, "_code_graph_impact", return_value={"lib/webauthn.ts"}), \
             mock.patch.object(behavior_graph, "_run_behavior_runner",
                               return_value={"version": 1, "commit": "new",
                                             "fingerprints": {}}) as run:
            report, code = behavior_graph.regression_check(self.proj, "base")
        self.assertEqual(code, 0, a_fix_landed)
        self.assertEqual(report["affected"], [], a_fix_landed)
        run.assert_not_called()


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

    def _gitignore(self):
        return os.path.join(self.proj, "knowledge-base", ".graph", ".gitignore")

    def _write_gitignore(self, text):
        graph_dir = os.path.join(self.proj, "knowledge-base", ".graph")
        os.makedirs(graph_dir, exist_ok=True)
        with open(self._gitignore(), "w", encoding="utf-8") as f:
            f.write(text)

    def test_creates_gitignore_on_fresh_graph_dir(self):
        """The cache ignores the two regenerable files by name, never behavior.json.

        A blanket `*` would sweep up behavior.json, whose observed coverage comes
        from running the test suite and cannot be rebuilt by re-reading source.
        """
        behavior_graph.write_behavior_json(self.proj, {"version": 1, "behaviors": {}})
        self.assertTrue(os.path.exists(self._gitignore()))
        with open(self._gitignore(), encoding="utf-8") as f:
            lines = [ln.strip() for ln in f if ln.strip() and not ln.startswith("#")]
        self.assertEqual(lines, ["graph.json", "graph.*.json", "classifications.json", "docs.json"])
        self.assertNotIn("*", lines)

    def test_replaces_a_legacy_blanket_ignore(self):
        """Existing projects carry the old `*`; the writer must upgrade it in place.

        Both writers only wrote when the file was absent, so without this an
        already-onboarded project would keep ignoring behavior.json forever.
        """
        self._write_gitignore("*\n")
        behavior_graph.write_behavior_json(self.proj, {"version": 1, "behaviors": {}})
        with open(self._gitignore(), encoding="utf-8") as f:
            lines = [ln.strip() for ln in f if ln.strip() and not ln.startswith("#")]
        self.assertEqual(lines, ["graph.json", "graph.*.json", "classifications.json", "docs.json"])

    def test_replaces_the_legacy_commented_blanket_ignore(self):
        """code-graph's variant of the same legacy file, comment and all."""
        self._write_gitignore("# Generated code-graph cache — do not commit\n*\n")
        behavior_graph.write_behavior_json(self.proj, {"version": 1, "behaviors": {}})
        with open(self._gitignore(), encoding="utf-8") as f:
            lines = [ln.strip() for ln in f if ln.strip() and not ln.startswith("#")]
        self.assertEqual(lines, ["graph.json", "graph.*.json", "classifications.json", "docs.json"])

    def test_does_not_overwrite_a_customised_gitignore(self):
        """Anything that is not a recognised legacy blanket is the user's file."""
        self._write_gitignore("existing\n")
        behavior_graph.write_behavior_json(self.proj, {"version": 1, "behaviors": {}})
        with open(self._gitignore(), encoding="utf-8") as f:
            contents = f.read()
        self.assertEqual(contents, "existing\n")

    def test_exercises_are_sorted_by_path(self):
        """behavior.json is committed, so it must be byte-stable across rebuilds.

        code-graph's import closure comes out of a set, so its order varies run to
        run (proven: two builds of identical input differ only in ordering). Left
        unsorted, every rebuild would produce a spurious diff.
        """
        data = {"version": 1, "behaviors": {"BEH-001": {"coverage": "static", "exercises": [
            {"path": "lib/z.ts", "source": "static"},
            {"path": "lib/a.ts", "source": "static"},
            {"path": "lib/m.ts", "source": "static"},
        ]}}}
        behavior_graph.write_behavior_json(self.proj, data)
        with open(behavior_graph._behavior_json_path(self.proj), encoding="utf-8") as f:
            written = json.load(f)
        paths = [e["path"] for e in written["behaviors"]["BEH-001"]["exercises"]]
        self.assertEqual(paths, ["lib/a.ts", "lib/m.ts", "lib/z.ts"])

    def test_the_behaviors_mapping_is_sorted_by_id(self):
        """The exercises were sorted and the keys they sit under were not.

        `project_behaviors` fills this mapping in `os.walk` dirent order — directory order
        on APFS, hash order on ext4 — so identical specs produced a different key order on
        a colleague's machine or in CI. On a tracked artifact whose diffs are read as
        behaviour drift, that is a whole-file false alarm.
        """
        data = {"version": 1, "behaviors": {
            "BEH-003": {"coverage": "unknown", "exercises": []},
            "BEH-001": {"coverage": "unknown", "exercises": []},
            "BEH-002": {"coverage": "unknown", "exercises": []},
        }}
        behavior_graph.write_behavior_json(self.proj, data)
        with open(behavior_graph._behavior_json_path(self.proj), encoding="utf-8") as f:
            written = json.load(f)
        self.assertEqual(list(written["behaviors"]), ["BEH-001", "BEH-002", "BEH-003"])

    def test_key_order_does_not_change_the_file(self):
        first = None
        for order in (["BEH-002", "BEH-001"], ["BEH-001", "BEH-002"]):
            behavior_graph.write_behavior_json(self.proj, {
                "version": 1,
                "behaviors": {bid: {"coverage": "unknown", "exercises": []}
                              for bid in order},
            })
            with open(behavior_graph._behavior_json_path(self.proj), encoding="utf-8") as f:
                text = f.read()
            if first is None:
                first = text
            self.assertEqual(text, first, "key order leaked into the committed file")

    def test_two_writes_of_the_same_content_are_byte_identical(self):
        """The property that matters: rebuild with no change produces no diff."""
        import random
        exercises = [{"path": p, "source": "static"} for p in
                     ["lib/a.ts", "lib/b.ts", "lib/c.ts", "lib/d.ts"]]
        first = None
        for _ in range(4):
            shuffled = exercises[:]
            random.shuffle(shuffled)
            behavior_graph.write_behavior_json(
                self.proj,
                {"version": 1, "behaviors": {"BEH-001": {"coverage": "static",
                                                         "exercises": shuffled}}})
            with open(behavior_graph._behavior_json_path(self.proj), encoding="utf-8") as f:
                text = f.read()
            if first is None:
                first = text
            self.assertEqual(text, first, "same content produced a different file")


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
        with mock.patch.object(behavior_graph, "_changed_files", return_value=(["README.md"], True)), \
             mock.patch.object(behavior_graph, "_code_graph_impact", return_value={"README.md"}):
            report, code = behavior_graph.regression_check(self.proj, "base")
        self.assertEqual(code, 0)
        self.assertEqual(report["affected"], [])

    def test_affected_passing_exits_zero(self):
        runner_out = {"version": 1, "commit": "new", "fingerprints": {
            "BEH-002": {"coverage": "observed", "exercises": [{"path": "lib/webauthn.ts"}]}}}
        with mock.patch.object(behavior_graph, "_changed_files", return_value=(["lib/webauthn.ts"], True)), \
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
        with mock.patch.object(behavior_graph, "_changed_files", return_value=(["lib/webauthn.ts"], True)), \
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
            # `stderr` is spelled because the wrapper forwards it now; a MagicMock
            # attribute here is truthy and would be written to the real stderr.
            return mock.MagicMock(
                returncode=0, stderr="",
                stdout='{"version": 1, "commit": "x", "fingerprints": {}}')

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
        with mock.patch.object(behavior_graph, "_changed_files", return_value=(["app/api/x/route.ts"], True)), \
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
        with mock.patch.object(behavior_graph, "_changed_files", return_value=(["app/api/x/route.ts"], True)), \
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
        # BEH-002's locator has to name a real file: `covering()` runs its own
        # locator check, because the repository it answers about is one whose
        # gates nobody here ran. It is not verify_links' Tier-1 check re-run —
        # the two diverge, and `LocatorCheckDivergesFromTier1Test` is where.
        os.makedirs(os.path.join(self.proj, "lib"), exist_ok=True)
        with open(os.path.join(self.proj, "lib", "webauthn.test.ts"), "w") as f:
            f.write("")
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
                            "coverage": "observed",
                            "exercises": [{"path": "lib/webauthn.ts",
                                           "source": "observed"}]},
                "BEH-006": {"spec_id": "SPEC-100", "state": "confirmed",
                            "coverage": "static", "exercises": [{"path": "app/api/x/route.ts"}]},
            },
        })

    def _surface(self, changed, impact, ok=True):
        with mock.patch.object(behavior_graph, "_changed_files", return_value=(changed, ok)), \
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
        # An honest empty diff is not a skip. `AGateThatCouldNotDiffSaysSoTest` owns the
        # other half; this end of it is asserted here so the two cannot collapse into one
        # note again without a test going red.
        self.assertIs(r["skipped"], False)

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

    def test_a_manifest_node_is_not_a_gap(self):
        """"Graph node" and "source file" were the same set under the homegrown backend,
        which only ever indexed source. A polyglot backend indexes manifests too, and every
        `package.json` and `pom.xml` then arrived in the gap report as source with no
        behaviour — into a tracked BACKLOG.md, and into wrap-up asking someone to write a
        behaviour for `package.json`."""
        path = os.path.join(self.proj, "knowledge-base", ".graph", "graph.json")
        with open(path, encoding="utf-8") as f:
            graph = json.load(f)
        graph["files"]["package.json"] = {"imports": [], "dependents": [],
                                          "exports": [], "language": "json"}
        graph["files"]["pom.xml"] = {"imports": [], "dependents": [],
                                     "exports": [], "language": "xml"}
        with open(path, "w", encoding="utf-8") as f:
            json.dump(graph, f)
        r = behavior_graph.gaps(self.proj)
        self.assertEqual(r["gaps"], ["lib/util.ts"])

    def test_covering_returns_accepted_behavior_for_file(self):
        r = behavior_graph.covering(self.proj, "lib/webauthn.ts")
        self.assertEqual(r["file"], "lib/webauthn.ts")
        self.assertEqual([c["behavior_id"] for c in r["covering"]], ["BEH-002"])
        self.assertEqual(r["covering"][0]["spec_id"], "SPEC-100")

    def test_covering_excludes_confirmed_behavior(self):
        # BEH-006 (confirmed) exercises app/api/x/route.ts but is NOT accepted,
        # so it must not be returned. This comment used to read "only verified
        # behaviors downgrade findings", which is the SEC-006 overclaim in
        # miniature: `accepted` is a state the scanned project *declares*, and
        # nothing here ran a test. Only behaviors declared accepted downgrade
        # findings — that is a narrower sentence and it is the true one.
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


class CoveringEvidenceTest(unittest.TestCase):
    """What `--covering` may claim, and what it may only label (SEC-006).

    The 2026-08-21 scan reproduced the mechanism: a hand-written behavior.json
    declaring `BEH-777` accepted made `--covering src/vulnerable.ts` return it —
    and that return value is what licenses ADR-012's downgrade, the only
    sanctioned way this toolkit stops counting a real security finding.

    **The earlier version of this class argued the finding could not be closed,
    on a premise that was wrong.** It held that the only non-project-supplied
    evidence would be running the linked test, and that executing a scanned
    repository's suite is worse than the problem. That is an argument against a
    capability this toolkit ships as a feature: `freya-behavior-runner` exists to
    run the project's tests, and `regression_check` in the module under test
    already re-runs accepted behaviors. freya is a tool a developer points at a
    repository they are working in, and by then they have installed its
    dependencies and run its suite.

    So the class now pins four things instead of two:

    * `state` is owned by the spec (ADR-002/ADR-003), so behavior.json alone
      asserts nothing.
    * a locator is **required** and must name a real file. It used to be checked
      only when declared, which let an omission through — the widest of the
      holes, because it needed no forgery.
    * only `source: "observed"` counts. An exercises entry is either a real run
      with coverage or `static` — **inferred from the import graph, with no test
      involved at all** — and this query read neither, so an inference silenced
      findings exactly as a passing test did.
    * `--verify` re-runs the linked test rather than trusting the committed
      record of a past run.

    What is left is a genuine residual and is pinned out loud rather than
    described: without `--verify`, `observed` means *a test passed once on
    somebody's machine*, which is a label on evidence and not a verification.
    The locator property here is *related to* verify_links' Tier-1 one and is not
    the same property; `LocatorCheckDivergesFromTier1Test` measures the gap.
    """

    SPEC = """---
id: SPEC-777
title: Covering fixture
category: features
status: implemented
behaviors:
  - behavior_id: BEH-777
    title: A behavior somebody declared
    state: {state}
    level: unit
    adapter: {adapter}
{locator_line}---
# body
"""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.proj = self.tmp.name
        os.makedirs(os.path.join(self.proj, "lib"))
        with open(os.path.join(self.proj, "lib", "webauthn.test.ts"), "w") as f:
            f.write("")
        self._write_graph()

    def _write_graph(self, source="observed", symbols=None):
        """The attacker's artifact: accepted state and an exercise on the flagged file,
        asserted by the graph and by nothing else.

        `source` is spelled out because a hand-written artifact would spell it — an
        attacker writing this file writes `observed`, and a fixture that omits the field
        tests a shape the runner never produces. The default is therefore the *hard* case,
        not the easy one."""
        edge = {"path": "src/vulnerable.ts", "source": source,
                "confidence": 0.8, "freshness": "fixture"}
        if symbols:
            edge["symbols"] = symbols
        behavior_graph.write_behavior_json(self.proj, {
            "version": 1, "commit": "fixture",
            "behaviors": {
                "BEH-777": {"spec_id": "SPEC-777", "state": "accepted",
                            "coverage": "observed", "exercises": [edge]},
            },
        })

    def _write_spec(self, state="accepted", locator="lib/webauthn.test.ts::x",
                    adapter="vitest"):
        specs = os.path.join(self.proj, "knowledge-base", "specs", "features")
        os.makedirs(specs, exist_ok=True)
        locator_line = "" if locator is None else "    locator: {}\n".format(locator)
        with open(os.path.join(specs, "SPEC-777.md"), "w") as f:
            f.write(self.SPEC.format(state=state, adapter=adapter,
                                     locator_line=locator_line))

    def _covering(self):
        return behavior_graph.covering(self.proj, "src/vulnerable.ts")["covering"]

    def test_a_spec_backed_accepted_behavior_covers(self):
        """The control. Without it the other five pass on a query that is simply
        always empty, which would be a worse bug wearing this fix's clothes."""
        self._write_spec()
        self.assertEqual(self._covering(), [{
            "behavior_id": "BEH-777", "spec_id": "SPEC-777", "coverage": "observed",
            "locator": "lib/webauthn.test.ts::x", "source": "observed",
        }])

    def test_an_accepted_state_only_in_behavior_json_does_not_cover(self):
        """SEC-006's reproduction: behavior.json says accepted and no spec says
        anything. The graph is a projection of the specs, so an entry with no spec
        behind it is not evidence of intent — it is an unsourced assertion."""
        self.assertEqual(self._covering(), [])

    def test_a_behavior_demoted_in_the_specs_stops_covering(self):
        """The likelier case, and it needs no attacker: somebody demoted the
        behavior and nobody re-ran `--build`, so a stale graph still says accepted.
        State is read from the spec, so the demotion takes effect at this query
        rather than whenever the graph is next rebuilt."""
        self._write_spec(state="proposed")
        self.assertEqual(self._covering(), [])

    def test_a_locator_naming_no_file_does_not_cover(self):
        """verify_links refuses this at Tier 1 — but that gate ran on a repository
        somebody chose to run it on, and this query answers about one nobody did."""
        self._write_spec(locator="lib/gone.test.ts::x")
        self.assertEqual(self._covering(), [])

    def test_a_locator_escaping_the_project_does_not_cover(self):
        """A locator is project-supplied text that gets joined onto the project
        path, so it is the same shape as SEC-013 in a different file. The escape
        target is a real file in the temp directory's parent rather than
        `/etc/hosts`, which does not exist on the Windows runners and would make
        this assertion pass there for the wrong reason."""
        outside = os.path.join(os.path.dirname(self.proj), "beh777-probe.test.ts")
        with open(outside, "w") as f:
            f.write("")
        self.addCleanup(os.remove, outside)
        self._write_spec(locator="../beh777-probe.test.ts::x")
        self.assertEqual(self._covering(), [])

    def test_a_locator_with_no_path_does_not_cover(self):
        """`#scenario` on its own names no file. Joined onto the project it is the
        project directory, which exists — so the existence check would answer a
        question it was never asked."""
        self._write_spec(locator="'#does-not-reveal'")
        self.assertEqual(self._covering(), [])

    def test_a_locator_naming_a_directory_does_not_cover(self):
        """A locator addresses a test, and eleven of the twelve adapters in
        `frontmatter.KNOWN_ADAPTERS` address one by file (`manual` addresses
        nothing, which is why it carries no locator) — so a directory has
        not resolved, it has failed to under an `os.path.exists` that says yes to
        anything on disk. The forgery this closes is cheaper than the rest of the
        class: `.` is the project root, it exists in every project, and it takes
        no knowledge of the scanned tree at all."""
        os.makedirs(os.path.join(self.proj, "tests"), exist_ok=True)
        for locator in ("tests::x", "tests", "'.::x'"):
            with self.subTest(locator=locator):
                self._write_spec(locator=locator)
                self.assertEqual(self._covering(), [])

    def test_an_accepted_behavior_with_no_locator_no_longer_covers(self):
        """The residual this class used to pin out loud, now closed.

        It read: `manual` is the one adapter Tier 1 permits to declare no locator, but the
        exemption here was wider, because `covering()` never reads the adapter — ANY spec
        declaring no locator got the pass. The old note said closing it "would mean refusing
        an accepted behavior for declaring nothing, which is a decision about every adapter
        rather than a fix for SEC-006".

        That decision has been taken, and this is the right query to take it in: the whole
        question `covering()` answers is "did a test exercise this file", and a behavior with
        no locator names no test. A `manual` behavior is intent without an executable — real
        and worth recording, and not evidence that anything ran. It still appears everywhere
        else in the graph; it just stops silencing security findings.
        """
        self._write_spec(locator=None, adapter="manual")
        self.assertEqual(self._covering(), [])

    def test_a_statically_inferred_exercise_does_not_cover(self):
        """The widest hole SEC-006 had, and the one the finding did not name.

        An exercises entry carries `source: "observed"` (a real run, with coverage) or
        `static` — inferred from the import graph by `run_behaviors.static_exercises`, with no
        test involved at all. This query read neither field, so a dependency-graph inference
        silenced a security finding exactly as a passing test did.

        No forgery is needed to reach this state: a project whose accepted behavior has no
        runnable adapter gets `static` edges from an ordinary `--build`.
        """
        self._write_graph(source="static")
        self._write_spec()
        self.assertEqual(self._covering(), [])

    def test_an_exercise_with_no_source_field_does_not_cover(self):
        """Fail closed on a shape the runner does not produce.

        Every edge `run_behaviors` writes carries `source`. One without it is hand-written or
        from a format older than this check, and neither is evidence a test ran. Absent must
        not read as `observed` — that is the direction that silences findings.
        """
        behavior_graph.write_behavior_json(self.proj, {
            "version": 1, "commit": "fixture",
            "behaviors": {
                "BEH-777": {"spec_id": "SPEC-777", "state": "accepted",
                            "coverage": "observed",
                            "exercises": [{"path": "src/vulnerable.ts"}]},
            },
        })
        self._write_spec()
        self.assertEqual(self._covering(), [])

    def test_the_symbols_that_ran_are_carried_to_the_caller(self):
        """The file anchor alone is weak in a way worth handing to the agent: a test touching
        anywhere in a 500-line module downgraded a finding on a line it never executed. The
        runner records which named functions ran, and this query used to drop that.

        It does not make the judgement — the agent still does — but it stops asking the agent
        to make it blind. File-plus-symbols, never lines: `coverage_symbols` records names,
        and claiming line granularity would be an overclaim the data cannot support.
        """
        self._write_graph(symbols=["handleLogin", "verifyChallenge"])
        self._write_spec()
        self.assertEqual(self._covering()[0]["symbols"],
                         ["handleLogin", "verifyChallenge"])

    def test_the_answer_says_what_it_trusted(self):
        """The actual remediation. Nothing here was verified — both inputs are
        files the scanned project committed — so the query states that instead of
        implying otherwise by staying silent. It pins the label's presence, not
        that any consumer reads it; carrying it into the report is SKILL.md's job.
        """
        self._write_spec()
        r = behavior_graph.covering(self.proj, "src/vulnerable.ts")
        self.assertIn("behavior.json", r["evidence"])
        self.assertIn("no test was run by this query", r["evidence"])
        self.assertIs(r["verified"], False)
        # The distinction the label has to carry, and the reason a generic sentence is the
        # failure mode: `observed` means a test passed once on somebody's machine. Only
        # --verify means one passed now.
        self.assertIn("source: observed", r["evidence"])

    def test_verify_reruns_the_test_and_says_so(self):
        """`--verify` is the half that was argued away rather than built.

        The runner is stubbed because this asserts the wiring and the label, not that pytest
        works: what must hold is that a green run reaches the row as `verified.passed` and
        that the evidence stops saying no test ran.
        """
        self._write_spec()
        with mock.patch.object(behavior_graph, "_run_behavior_runner",
                               return_value={"fingerprints": {
                                   "BEH-777": {"coverage": "observed", "exercises": []}}}):
            r = behavior_graph.covering(self.proj, "src/vulnerable.ts", verify=True)
        self.assertIs(r["verified"], True)
        self.assertEqual(r["covering"][0]["verified"],
                         {"passed": True, "reason": "test passed under this query"})
        self.assertIn("RE-RUN", r["evidence"])
        self.assertNotIn("no test was run by this query", r["evidence"])

    def test_a_red_test_is_evidence_against_the_behavior(self):
        """A failing test must not read as a verified one. It still appears in `covering` —
        the caller needs to see that the claim was tested and failed, which is strictly more
        information than the row being absent — with `passed` false and the runner's reason.

        What `test-failed` does and does not establish is
        `AVerificationSaysWhatItCouldNotTellApartTest`'s subject; asserted here only as the
        `note` travelling with the token, so the two cannot be separated by an edit to one.
        """
        self._write_spec()
        with mock.patch.object(behavior_graph, "_run_behavior_runner",
                               return_value={"fingerprints": {
                                   "BEH-777": {"coverage": "unknown", "exercises": [],
                                               "reason": "test-failed"}}}):
            r = behavior_graph.covering(self.proj, "src/vulnerable.ts", verify=True)
        verdict = r["covering"][0]["verified"]
        self.assertEqual((verdict["passed"], verdict["reason"]), (False, "test-failed"))
        self.assertIn("could not start", verdict["note"])
        self.assertIn("0 of 1 passed", r["evidence"])

    def test_a_runner_that_cannot_start_does_not_verify_anything(self):
        """"Could not determine" must never read as "verified" in the one query that can
        silence a security finding. A missing runner, a timeout and a malformed stdout all
        land here, and all of them are False with the reason naming the class."""
        self._write_spec()
        with mock.patch.object(behavior_graph, "_run_behavior_runner",
                               side_effect=OSError("no runner")):
            r = behavior_graph.covering(self.proj, "src/vulnerable.ts", verify=True)
        verdict = r["covering"][0]["verified"]
        self.assertFalse(verdict["passed"])
        self.assertIn("could not run", verdict["reason"])


class LocatorCheckDivergesFromTier1Test(unittest.TestCase):
    """`covering()`'s locator check against verify_links' Tier-1 one, same fixture.

    `covering()`'s docstring used to say it "re-establishes" the Tier-1 property.
    It does not: neither check implies the other, and the consequence is a
    repository that passes every gate and still has `--covering` refuse a
    behavior. A maintainer who has read "re-establishes" reads that refusal as a
    bug in this file and goes looking for the wrong thing.

    So the divergence is asserted rather than described. Each row runs one
    fixture through both, and the class is red the moment either side moves —
    including the day somebody fixes the Tier-1 hole in row 3, which is the
    outcome this class most wants and would otherwise silently outlive.
    """

    SPEC = """---
id: SPEC-778
title: Divergence fixture
category: features
status: implemented
behaviors:
  - behavior_id: BEH-778
    title: A behavior somebody declared
    state: accepted
    level: unit
    adapter: {adapter}
{locator_line}---
# body
"""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.proj = self.tmp.name
        os.makedirs(os.path.join(self.proj, "lib"))
        with open(os.path.join(self.proj, "lib", "a.test.ts"), "w") as f:
            f.write("")
        with open(os.path.join(self.proj, "lib", "test_a.py"), "w") as f:
            f.write("def test_real():\n    pass\n")
        behavior_graph.write_behavior_json(self.proj, {
            "version": 1, "commit": "fixture",
            "behaviors": {
                # `source: observed` spelled out — the runner always writes it, and a
                # fixture without it exercises a shape that only a hand-edited file has.
                "BEH-778": {"spec_id": "SPEC-778", "state": "accepted",
                            "coverage": "observed",
                            "exercises": [{"path": "src/vulnerable.ts",
                                           "source": "observed"}]},
            },
        })

    def _both(self, locator, adapter="vitest"):
        """(does Tier 1 pass it, does `--covering` return it) for one locator."""
        specs = os.path.join(self.proj, "knowledge-base", "specs")
        os.makedirs(os.path.join(specs, "features"), exist_ok=True)
        locator_line = "" if locator is None else "    locator: {}\n".format(locator)
        with open(os.path.join(specs, "features", "SPEC-778.md"), "w") as f:
            f.write(self.SPEC.format(adapter=adapter, locator_line=locator_line))
        tier1 = not verify_links.verify(specs)
        covers = bool(behavior_graph.covering(self.proj, "src/vulnerable.ts")["covering"])
        return tier1, covers

    def test_the_two_agree_on_a_real_file(self):
        """The control. Without it every row below passes on a fixture that is
        simply broken for both, which would read as a divergence and is not."""
        self.assertEqual(self._both("lib/a.test.ts::x"), (True, True))

    def test_the_two_agree_on_a_file_that_does_not_exist(self):
        """The case the Tier-1 comparison is actually about — and the one where
        the two checks do line up. It is here so the rows that follow are read as
        exceptions to a rule rather than as the rule."""
        self.assertEqual(self._both("lib/gone.test.ts::x"), (False, False))

    def test_an_empty_path_part_is_now_refused_by_both(self):
        """This row used to read `(True, False)` — Tier 1 passed a locator that
        names nothing, because `escapes("")` is false and `root / ""` is the
        project root, which exists. The divergence was the evidence, and on
        2026-08-23 it was spent: `verify_links` now refuses an empty path part
        and the two agree.

        Kept, and kept as an assertion rather than a deleted row, because the
        agreement is the thing worth pinning. If either side loosens, this goes
        red from whichever side moved."""
        self.assertEqual(self._both("'#scenario-only'"), (False, False))

    def test_a_directory_is_now_refused_by_both(self):
        """The same fix, one rung less obvious: Tier 1 asked `Path.exists`, which
        a directory satisfies, while this query asks `os.path.isfile`. Tier 1 now
        asks `is_file` too. A locator names a test file, and a directory sitting
        at that path is not one."""
        self.assertEqual(self._both("lib::x"), (False, False))

    def test_a_missing_locator_is_now_refused_by_both(self):
        """The divergence that mattered most for SEC-006, and it is spent.

        This row read `(False, True)`: Tier 1 knew that `accepted` plus a non-`manual`
        adapter must carry a locator, while this query read only what was declared — so a
        spec declaring nothing had nothing refused, and the exposure was exactly the
        repositories nobody ran the gate on. `covering()` now requires a locator, so both
        refuse.

        Kept as an assertion of agreement rather than deleted, for the reason this class
        exists: if either side loosens, this goes red from whichever side moved."""
        self.assertEqual(self._both(None), (False, False))

    def test_an_unresolvable_python_fragment_is_refused_by_tier_1_and_returned_here(self):
        """Tier 1 parses a `.py` locator's fragment and resolves the symbol. This
        check stops at the file, so `::nope` is returned. Recorded because it is
        the honest limit of "the locator resolves": it means the file is there,
        not that the named test is."""
        self.assertEqual(self._both("lib/test_a.py::nope", adapter="pytest"),
                         (False, True))


class GapsCoverablePredicateTest(unittest.TestCase):
    """The census counts only files a behavior could ever name in its exercised code.

    Measured on freya-devkit itself on 2026-08-21, before this predicate existed: `--gaps`
    reported 57 files and the git-tracked `knowledge-base/BACKLOG.md` carried that 57 to the
    reader. 29 of them were `test_*.py`, one was `conftest.py`, and three were not Python at
    all (`bin/freya`, `install.sh`, `install.ps1`) — 33 of 57, so the headline was 2.4x the 24
    files anyone could act on, and the generated worklist was asking people to write behaviors
    covering their own test files. The same command reports 24 with the predicate in place.
    """

    # One row per kind that was inflating the census. The third column is the language the
    # code graph recorded for the node, which is what the language rule keys on; None is a
    # node the backend indexed without identifying (`bin/freya` is one on this repo).
    NOT_COVERABLE = (
        ("a pytest-style test module", "src/test_login.py", "python"),
        ("a suffix-style test module", "src/login_test.py", "python"),
        ("a Go-style test module", "src/login_test.go", "go"),
        ("the pytest conftest", "src/conftest.py", "python"),
        ("a colocated JS/TS test", "lib/webauthn.test.ts", "typescript"),
        ("a colocated JS/TS spec", "lib/webauthn.spec.tsx", "typescript"),
        ("an extensionless executable", "cli/freya", None),
        ("a shell script", "install.sh", "shell"),
        ("a PowerShell script", "install.ps1", "powershell"),
    )

    COVERABLE = (
        ("a Python module", "src/login.py", "python"),
        ("a TypeScript module", "lib/webauthn.ts", "typescript"),
        ("a module the backend gave no language", "lib/util.ts", None),
        ("a name that merely contains 'test'", "src/contest.py", "python"),
    )

    def setUp(self):
        self.proj = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.proj, True)
        os.makedirs(os.path.join(self.proj, "knowledge-base", "specs"))
        os.makedirs(os.path.join(self.proj, "knowledge-base", ".graph"))

    def _write_graph(self, rows):
        files = {}
        for _label, rel, language in rows:
            info = {"imports": [], "dependents": [], "exports": []}
            if language is not None:
                info["language"] = language
            files[rel] = info
        path = os.path.join(self.proj, "knowledge-base", ".graph", "graph.json")
        with open(path, "w", encoding="utf-8") as f:
            json.dump({"version": 1, "files": files}, f)

    def test_the_census_omits_every_file_kind_no_behavior_could_name(self):
        """A behavior's exercised code is the production code its test reached, so none of
        these can ever appear there however much of the repo they make up."""
        self._write_graph(self.NOT_COVERABLE + (("real source", "src/login.py", "python"),))
        r = behavior_graph.gaps(self.proj)
        self.assertEqual(r["gaps"], ["src/login.py"])
        self.assertEqual(r["total"], 1)
        for label, rel, _language in self.NOT_COVERABLE:
            with self.subTest(label):
                self.assertNotIn(rel, r["gaps"])

    def test_real_source_is_still_counted_whatever_language_it_is_written_in(self):
        """The tempting predicate — "a `.py` file that is not a test" — reads correctly on
        this repository and reports zero gaps on every TS, Go or C# project the polyglot
        backend exists to serve. Trading 33 noisy entries for a confidently-empty census is
        the trade ADR-005 forbids, so each row here is a language the fix must not silence."""
        self._write_graph(self.COVERABLE)
        r = behavior_graph.gaps(self.proj)
        self.assertEqual(r["gaps"], ["lib/util.ts", "lib/webauthn.ts",
                                     "src/contest.py", "src/login.py"])
        self.assertEqual(r["total"], 4)
        for label, rel, _language in self.COVERABLE:
            with self.subTest(label):
                self.assertIn(rel, r["gaps"])

    def test_a_filename_that_merely_contains_test_is_still_a_gap(self):
        """The test-name match is anchored, not a substring.

        The unanchored version of this same idea already shipped once in the graph's
        exclusion rules, where a `.next` entry excluded every path containing `next`
        (`graph_ops.py:214`). Here it would drop `contest.py` and `latest.ts` from the
        census — real uncovered source hidden, which is strictly worse than the noise the
        exclusions were added to remove.
        """
        self._write_graph((("contains test", "src/contest.py", "python"),
                           ("contains test", "lib/latest.ts", "typescript")))
        r = behavior_graph.gaps(self.proj)
        self.assertEqual(r["gaps"], ["lib/latest.ts", "src/contest.py"])

    def test_a_covered_file_is_still_discharged_from_the_census(self):
        """The new predicate narrows the candidate set; it must not replace the coverage
        subtraction that was already there."""
        self._write_graph((("covered", "src/login.py", "python"),
                           ("uncovered", "src/signup.py", "python")))
        behavior_graph.write_behavior_json(self.proj, {
            "version": 1, "commit": "base",
            "behaviors": {"BEH-002": {"spec_id": "SPEC-100", "state": "accepted",
                                      "coverage": "observed",
                                      "exercises": [{"path": "src/login.py"}]}},
        })
        r = behavior_graph.gaps(self.proj)
        self.assertEqual(r["gaps"], ["src/signup.py"])


def _git(cwd, *argv):
    """Run git in `cwd` with a fixed identity, raising on failure."""
    env = dict(os.environ, GIT_AUTHOR_NAME="t", GIT_AUTHOR_EMAIL="t@e",
               GIT_COMMITTER_NAME="t", GIT_COMMITTER_EMAIL="t@e")
    return subprocess.run(["git", *argv], cwd=cwd, env=env, capture_output=True,
                          text=True, check=True)


class AGateThatCouldNotDiffSaysSoTest(unittest.TestCase):
    """`--check` and `--surface` over a `--base` git cannot resolve.

    Measured 2026-08-24 on the version this class was written against: a two-commit
    repository, one accepted behavior exercising the file that changed between them.
    `--base <real base>` reported `affected: [BEH-001]`. `--base origin/main` — a
    repository with no remote, which is a CI checkout, a shallow clone, or any fork
    whose default branch is not `main` — reported `{"affected": [], "failed": [],
    "changed": []}` and exit 0, byte for byte what a genuinely unaffected change
    produces. `git diff --name-only origin/main..HEAD` exits 128 there.

    That is the Direction-A hard block wrap-up runs at phase 3 reporting a clean run
    over a diff it never computed, and it is the shape `verify_intent._changed_status`
    was rewritten to close with an `ok=False` labelled skip — left open in the sibling
    gate. The fix is the same one: fail open per ADR-009 (a broken baseline must not
    become a false block, which is the alternative that record rejects by name), and
    say so, because a no-op indistinguishable from a pass is the false clean the same
    record forbids.

    Real git, not a mocked `_changed_files`, because what is under test is what git
    does with an argument — a stub would assert the fixture's own opinion of that.
    """

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = self.tmp.name
        os.makedirs(os.path.join(self.root, "src"))
        self._write("src/a.py", "print(1)\n")
        behavior_graph.write_behavior_json(self.root, {
            "version": 1, "commit": "fixture",
            "behaviors": {
                "BEH-001": {"spec_id": "SPEC-001", "state": "accepted", "level": "unit",
                            "adapter": "pytest", "locator": "tests/test_a.py::test_a",
                            "coverage": "observed",
                            "exercises": [{"path": "src/a.py", "source": "observed"}]},
            },
        })
        self._write_graph_json()
        _git(self.root, "init", "-q")
        _git(self.root, "add", "-A")
        _git(self.root, "commit", "-qm", "one")
        self.base = _git(self.root, "rev-parse", "HEAD").stdout.strip()
        self._write("src/a.py", "print(1)\nprint(2)\n")
        _git(self.root, "add", "-A")
        _git(self.root, "commit", "-qm", "two")

    def _write(self, rel, text):
        path = os.path.join(self.root, *rel.split("/"))
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w", encoding="utf-8") as f:
            f.write(text)

    def _write_graph_json(self, project=None):
        path = os.path.join(project or self.root, "knowledge-base", ".graph", "graph.json")
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w", encoding="utf-8") as f:
            json.dump({"files": {"src/a.py": {"language": "python"}}}, f)

    # -- the control, first: without it every assertion below passes on a fixture
    # that is simply broken for both answers, which would read as the defect and is not.
    def test_a_base_git_can_resolve_finds_the_affected_behavior(self):
        with mock.patch.object(behavior_graph, "_run_behavior_runner",
                               return_value={"commit": "new", "fingerprints": {
                                   "BEH-001": {"coverage": "observed",
                                               "exercises": [{"path": "src/a.py"}]}}}):
            report, code = behavior_graph.regression_check(self.root, self.base)
        self.assertEqual((report["affected"], report["changed"], code),
                         (["BEH-001"], ["src/a.py"], 0))
        self.assertIs(report["skipped"], False)

    def test_an_unresolvable_base_is_a_labelled_skip_and_not_a_clean_run(self):
        with mock.patch.object(behavior_graph, "_run_behavior_runner") as run:
            report, code = behavior_graph.regression_check(self.root, "origin/main")
        run.assert_not_called()
        self.assertEqual(code, 0, "ADR-009 fails open on a git error; it does not block")
        self.assertIs(report["skipped"], True)
        self.assertIn("origin/main", report["note"])
        self.assertIn("git", report["note"])

    def test_a_real_base_with_nothing_changed_is_not_a_skip(self):
        """The other half of the distinction. An honest empty diff must keep reading as
        an honest empty diff, or the label is just noise on every clean run."""
        head = _git(self.root, "rev-parse", "HEAD").stdout.strip()
        report, code = behavior_graph.regression_check(self.root, head)
        self.assertEqual((report["affected"], report["changed"], code), ([], [], 0))
        self.assertIs(report["skipped"], False)
        self.assertNotIn("note", report)

    def test_surface_stops_calling_a_failed_diff_an_empty_one(self):
        """`surface` already emitted a note here, which is why it was the sibling worth
        checking rather than the one to leave alone: the note it emitted was `no changed
        files in base..HEAD`, a sentence that is false when git refused to answer. Both
        spellings of empty produced it, byte for byte."""
        broken = behavior_graph.surface(self.root, "origin/main")
        honest = behavior_graph.surface(
            self.root, _git(self.root, "rev-parse", "HEAD").stdout.strip())
        self.assertIs(broken["skipped"], True)
        self.assertIn("origin/main", broken["note"])
        self.assertIs(honest["skipped"], False)
        self.assertEqual(honest["note"], "no changed files in base..HEAD")

    def test_changed_files_reports_whether_git_answered(self):
        self.assertEqual(behavior_graph._changed_files(self.base, self.root),
                         (["src/a.py"], True))
        self.assertEqual(behavior_graph._changed_files("origin/main", self.root),
                         ([], False))

    def test_the_revision_slot_cannot_smuggle_an_option(self):
        """`--end-of-options`, and the same argument `graph_ops._get_changed_files` was
        given: `--output=<file>` in the revision slot makes git truncate that file, write
        the diff into it, and exit 0 with an empty stdout — a clean-looking run that also
        clobbers a path outside the project. Measured on git 2.50.1, 2026-08-24, with the
        token absent: rc=0 and the target overwritten. `--base` is operator-supplied here
        rather than repository-supplied, so this is a footgun rather than the forgery
        route it is in `verify_intent`; the sibling that asks the same question already
        refuses it, and two of three spellings of one idea is how they drift."""
        target = os.path.join(self.tmp.name, "sentinel")
        with open(target, "w", encoding="utf-8") as f:
            f.write("untouched")
        self.assertEqual(behavior_graph._changed_files("--output=" + target, self.root),
                         ([], False))
        with open(target, encoding="utf-8") as f:
            self.assertEqual(f.read(), "untouched")

    def test_paths_are_project_relative_when_the_project_is_a_subdirectory(self):
        """`--relative`. `git diff --name-only` prints paths from the *repository* root,
        while every path this module joins against — `behavior.json`'s `exercises[].path`,
        `graph.json`'s keys — is project-relative. In a monorepo package, or any `--project`
        below the repo root, every returned path carried an extra prefix, so no exercised
        path ever matched and the gate reported `0 affected` over a real change. That is
        the same false clean this class is about, reached without any git error at all —
        and it is the defect `graph_ops._get_changed_files` already fixed for its own
        caller (`graph_ops.py:590`)."""
        proj = os.path.join(self.root, "pkg")
        os.makedirs(os.path.join(proj, "src"))
        self._write("pkg/src/b.py", "print(1)\n")
        _git(self.root, "add", "-A")
        _git(self.root, "commit", "-qm", "three")
        base = _git(self.root, "rev-parse", "HEAD").stdout.strip()
        self._write("pkg/src/b.py", "print(2)\n")
        self._write("src/a.py", "print(3)\n")
        _git(self.root, "add", "-A")
        _git(self.root, "commit", "-qm", "four")
        self.assertEqual(behavior_graph._changed_files(base, proj), (["src/b.py"], True))

    def test_a_rename_names_the_path_it_moved_from(self):
        """`--no-renames`. This asks which paths moved, not what the author meant: with
        rename detection on — git's default — a moved file is reported once, as its
        destination, and the path it vanished from is never named. An accepted behavior
        whose `exercises` still record the old path is then not affected by the commit
        that moved its code out from under it, which is exactly the run that most needs
        to happen."""
        _git(self.root, "mv", "src/a.py", "src/moved.py")
        _git(self.root, "commit", "-qm", "rename")
        base = _git(self.root, "rev-parse", "HEAD~1").stdout.strip()
        changed, ok = behavior_graph._changed_files(base, self.root)
        self.assertIs(ok, True)
        self.assertEqual(sorted(changed), ["src/a.py", "src/moved.py"])


class AVerificationSaysWhatItCouldNotTellApartTest(unittest.TestCase):
    """`--verify`'s verdict over a toolchain that never started.

    `_verify_behaviors` promised that "the reason is carried so a refusal can be told
    from a failure", and the runner's vocabulary does not reach that far: `test-failed`
    is `run_behaviors`' word for ANY non-zero exit from the test command
    (`run_behaviors.py:408`, `:463`). Measured 2026-08-24 on a fixture with a resolving
    locator, an `observed` edge and no JS toolchain installed at all — `pnpm vitest`
    exiting `ERR_PNPM_NO_IMPORTER_MANIFEST_FOUND` — the row came back
    `{"passed": false, "reason": "test-failed"}` and the evidence string read "each
    behavior's linked test was RE-RUN by this query. 0 of 1 passed."

    Nothing ran. The consumer is told a false row "is a finding in its own right"
    (`skills/freya-codebase-security-scan/SKILL.md:440`), so that answer files a report
    accusing a repository of asserting behaviors whose tests fail, on a machine where
    the tests were never executed. The token cannot be split here — it is the runner's,
    and this module only reads it — so what is fixed is the claim built on top of it.
    """

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.proj = self.tmp.name
        os.makedirs(os.path.join(self.proj, "lib"))
        with open(os.path.join(self.proj, "lib", "webauthn.test.ts"), "w") as f:
            f.write("")
        specs = os.path.join(self.proj, "knowledge-base", "specs", "features")
        os.makedirs(specs)
        with open(os.path.join(specs, "SPEC-777.md"), "w") as f:
            f.write(CoveringEvidenceTest.SPEC.format(
                state="accepted", adapter="vitest",
                locator_line="    locator: lib/webauthn.test.ts::x\n"))
        behavior_graph.write_behavior_json(self.proj, {
            "version": 1, "commit": "fixture",
            "behaviors": {"BEH-777": {"spec_id": "SPEC-777", "state": "accepted",
                                      "coverage": "observed",
                                      "exercises": [{"path": "src/vulnerable.ts",
                                                     "source": "observed",
                                                     "freshness": "fixture"}]}},
        })

    def _verify(self, fingerprint):
        with mock.patch.object(behavior_graph, "_run_behavior_runner",
                               return_value={"fingerprints": {"BEH-777": fingerprint}}):
            return behavior_graph.covering(self.proj, "src/vulnerable.ts", verify=True)

    def test_test_failed_carries_the_two_things_it_cannot_tell_apart(self):
        verdict = self._verify({"coverage": "unknown", "exercises": [],
                                "reason": "test-failed"})["covering"][0]["verified"]
        self.assertEqual((verdict["passed"], verdict["reason"]), (False, "test-failed"))
        self.assertIn("could not start", verdict["note"])

    def test_a_reason_that_is_already_unambiguous_carries_no_note(self):
        """The note is attached to the one token that hides a second meaning. On every
        other reason it would be noise, and a caveat printed everywhere is a caveat
        nobody reads on the row where it matters."""
        verdict = self._verify({"coverage": "unknown", "exercises": [],
                                "reason": "no-coverage-tool"})["covering"][0]["verified"]
        self.assertEqual((verdict["passed"], verdict["reason"]),
                         (False, "no-coverage-tool"))
        self.assertNotIn("note", verdict)

    def test_the_evidence_string_stops_calling_an_unrun_test_a_failing_one(self):
        """The evidence string is what `freya-codebase-security-scan` step 7 orders copied
        into the human-read report verbatim, so a qualifier that lives anywhere else does
        not travel. It goes in the same sentence as the claim it qualifies."""
        evidence = self._verify({"coverage": "unknown", "exercises": [],
                                 "reason": "test-failed"})["evidence"]
        self.assertIn("0 of 1 passed", evidence)
        self.assertIn("only where its test actually ran", evidence)
        self.assertIn("non-zero exit", evidence)


class TheRunnersOwnDiagnosisReachesTheOperatorTest(unittest.TestCase):
    """`_run_behavior_runner` captured the child's stderr and dropped it.

    `run_behaviors` writes every diagnosis it has to stderr and exits 0 anyway — the
    failing test's own output (`run_behaviors.py:407`), "test passed but coverage was
    not measured", "the locator is stale". `capture_output=True` here swallowed all of
    it, so the only thing that reached the operator was the token in the JSON. Measured
    2026-08-24: `--covering --verify` against a project with no JS toolchain printed
    `reason: test-failed` and an empty stderr, leaving nothing anywhere on the machine
    that says which of the two meanings applied.

    Forwarding is not a nicety here. It is the only place the ambiguity the verdict's
    `note` names can actually be resolved.
    """

    STDOUT = '{"version": 1, "commit": "x", "fingerprints": {}}'

    def _run(self, returncode, stderr):
        """(what the call produced, what reached sys.stderr) for one child outcome."""
        if returncode:
            outcome = {"side_effect": subprocess.CalledProcessError(
                returncode, ["runner"], self.STDOUT, stderr)}
        else:
            outcome = {"return_value": mock.MagicMock(
                returncode=0, stdout=self.STDOUT, stderr=stderr)}
        err = io.StringIO()
        with mock.patch.object(behavior_graph.subprocess, "run", **outcome), \
             mock.patch.object(behavior_graph.sys, "stderr", err):
            try:
                return behavior_graph._run_behavior_runner("/proj"), err.getvalue()
            except subprocess.CalledProcessError as exc:
                return exc, err.getvalue()

    def test_the_child_stderr_is_forwarded_when_the_runner_exits_zero(self):
        """The path that matters most, and the counter-intuitive one: the runner exits 0
        with a red behavior in its fingerprints, so the failing test's output is on the
        *success* path."""
        out, captured = self._run(0, "[behavior-runner] BEH-777: FAIL expected 1\n")
        self.assertEqual(out["commit"], "x")
        self.assertEqual(captured, "[behavior-runner] BEH-777: FAIL expected 1\n")

    def test_the_child_stderr_is_forwarded_when_the_runner_exits_non_zero(self):
        out, captured = self._run(2, "Traceback: FileNotFoundError: pnpm\n")
        self.assertIsInstance(out, subprocess.CalledProcessError)
        self.assertEqual(captured, "Traceback: FileNotFoundError: pnpm\n")


if __name__ == "__main__":
    unittest.main()
