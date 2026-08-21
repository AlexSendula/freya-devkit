#!/usr/bin/env python3
"""Proof suite for collect_status.py — the status aggregator."""
import json
import os
import subprocess
import sys
import tempfile
import unittest
import unittest.mock as mock

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import collect_status  # noqa: E402

SCRIPT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "collect_status.py")

SPEC = """---
id: SPEC-001
title: Fixture
category: features
status: implemented
certainty: 60
behaviors:
  - behavior_id: BEH-001
    title: Proposed one
    state: proposed
  - behavior_id: BEH-002
    title: Confirmed one
    state: confirmed
    entry: app/x.ts
  - behavior_id: BEH-003
    title: Accepted one
    state: accepted
    adapter: vitest
    locator: x.test.ts::t
---
# body
"""


class CensusTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.specs = os.path.join(self.tmp.name, "auth")
        os.makedirs(self.specs)
        with open(os.path.join(self.specs, "s.md"), "w") as f:
            f.write(SPEC)

    def test_counts_by_state(self):
        counts, intent, owed = collect_status.behavior_census(self.tmp.name)
        self.assertEqual(counts["proposed"], 1)
        self.assertEqual(counts["confirmed"], 1)
        self.assertEqual(counts["accepted"], 1)

    def test_intent_worklist_is_proposed_with_certainty(self):
        _c, intent, _o = collect_status.behavior_census(self.tmp.name)
        self.assertEqual([r["behavior_id"] for r in intent], ["BEH-001"])
        self.assertEqual(intent[0]["certainty"], 60)  # inherited from parent spec

    def test_test_owed_worklist_is_confirmed(self):
        _c, _i, owed = collect_status.behavior_census(self.tmp.name)
        self.assertEqual([r["behavior_id"] for r in owed], ["BEH-002"])

    def test_missing_specs_dir_is_empty(self):
        counts, intent, owed = collect_status.behavior_census("/no/such/dir")
        self.assertEqual(sum(counts.values()), 0)
        self.assertEqual(intent, [])

    def test_an_unreadable_spec_does_not_stop_the_walk(self):
        """One spec carrying a stray byte once raised UnicodeDecodeError out of the
        whole census: it is not an OSError, so the handler meant to skip the file did
        not catch it (collect_status.py:59) and the report came back empty. Both
        flavours of unreadable are planted here beside a good spec, so narrowing that
        handler back down to either one goes red rather than merely quiet."""
        with open(os.path.join(self.specs, "aa-malformed.md"), "w") as f:
            f.write("---\nid: SPEC-002\n\ttitle: tab indented\n---\n# body\n")
        with open(os.path.join(self.specs, "ab-undecodable.md"), "wb") as f:
            f.write(b"---\nid: SPEC-003\ntitle: stray \xff byte\nbehaviors:\n"
                    b"  - behavior_id: BEH-999\n    state: proposed\n---\n# body\n")
        counts, intent, owed = collect_status.behavior_census(self.tmp.name)
        self.assertEqual([r["behavior_id"] for r in intent], ["BEH-001"])
        self.assertEqual([r["behavior_id"] for r in owed], ["BEH-002"])
        self.assertEqual(counts["proposed"], 1)   # BEH-999 was never readable
        self.assertEqual(counts["accepted"], 1)


class SecurityBucketTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.d = os.path.join(self.tmp.name, "knowledge-base", "security", "codebase-security")
        os.makedirs(self.d)

    def _write(self, obj):
        with open(os.path.join(self.d, "findings.json"), "w") as f:
            json.dump(obj, f)

    def test_open_findings_only(self):
        self._write({"version": 1, "findings": [
            {"id": "SEC-001", "title": "a", "severity": "high", "status": "open", "file": "x.ts"},
            {"id": "SEC-002", "title": "b", "severity": "low", "status": "resolved", "file": "y.ts"},
            {"id": "SEC-003", "title": "c", "severity": "medium", "status": "intentional", "file": "z.ts"},
        ]})
        out, note = collect_status.security_bucket(self.tmp.name)
        self.assertIsNone(note)
        self.assertEqual([f["id"] for f in out], ["SEC-001"])

    def test_missing_findings_is_note(self):
        out, note = collect_status.security_bucket(self.tmp.name)
        self.assertEqual(out, [])
        self.assertIsNotNone(note)


class StaleBucketTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.gdir = os.path.join(self.tmp.name, "knowledge-base", ".graph")
        os.makedirs(self.gdir)

    def _write(self, behaviors):
        with open(os.path.join(self.gdir, "behavior.json"), "w") as f:
            json.dump({"version": 1, "behaviors": behaviors}, f)

    def test_stale_when_freshness_differs_from_head(self):
        self._write({"BEH-002": {"exercises": [{"path": "a.ts", "freshness": "oldcommit"}]}})
        with mock.patch.object(collect_status, "_git_head", return_value="newcommit"):
            stale, note = collect_status.stale_bucket(self.tmp.name)
        self.assertEqual(stale, ["BEH-002"])

    def test_fresh_when_matches_head(self):
        self._write({"BEH-002": {"exercises": [{"path": "a.ts", "freshness": "head1"}]}})
        with mock.patch.object(collect_status, "_git_head", return_value="head1"):
            stale, note = collect_status.stale_bucket(self.tmp.name)
        self.assertEqual(stale, [])

    def test_missing_behavior_json_is_note(self):
        import shutil
        shutil.rmtree(self.gdir)
        stale, note = collect_status.stale_bucket(self.tmp.name)
        self.assertEqual(stale, [])
        self.assertIsNotNone(note)


class CollectAndRenderTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        os.makedirs(os.path.join(self.tmp.name, "knowledge-base", "specs", "auth"))
        with open(os.path.join(self.tmp.name, "knowledge-base", "specs", "auth", "s.md"), "w") as f:
            f.write(SPEC)

    def _collect(self):
        # mock the subprocess-backed buckets to keep this hermetic
        with mock.patch.object(collect_status, "gaps_bucket",
                               return_value=({"total": 2, "sample": ["a.ts", "b.ts"]}, None)), \
             mock.patch.object(collect_status, "verify_bucket", return_value=([], None)), \
             mock.patch.object(collect_status, "stale_bucket", return_value=([], None)), \
             mock.patch.object(collect_status, "security_bucket",
                               return_value=([{"id": "SEC-001", "title": "a", "severity": "high", "file": "x.ts"}], None)):
            return collect_status.collect(self.tmp.name)

    def test_collect_assembles_all_buckets(self):
        s = self._collect()
        self.assertEqual(s["behavior_counts"]["proposed"], 1)
        self.assertEqual(len(s["intent_worklist"]), 1)
        self.assertEqual(len(s["test_owed_worklist"]), 1)
        self.assertEqual(s["gaps"]["total"], 2)
        self.assertEqual(len(s["open_security_findings"]), 1)

    def test_render_backlog_has_sections_and_generated_header(self):
        md = collect_status.render_backlog(self._collect())
        self.assertIn("do not edit", md.lower())
        self.assertIn("Behaviors to confirm", md)
        self.assertIn("Tests owed", md)
        self.assertIn("Coverage gaps", md)
        self.assertIn("Open security findings", md)
        self.assertIn("BEH-001", md)   # the proposed behavior listed

    def test_write_backlog_writes_file(self):
        s = self._collect()
        path = collect_status.write_backlog(self.tmp.name, s)
        self.assertTrue(path.endswith(os.path.join("knowledge-base", "BACKLOG.md")))
        self.assertTrue(os.path.exists(path))

    def test_a_refresh_replaces_hand_written_content(self):
        """`write_backlog` opens the path "w" (collect_status.py:226) — the only
        full-overwrite path in the tree, and it came within a rename of destroying
        ~600 lines of hand-written backlog on this repo. Nothing is merged, nothing
        is set aside and nothing is said about it. That destruction is the specified
        behaviour, and this pins it so nobody softens it into a silent merge later."""
        path = os.path.join(self.tmp.name, "knowledge-base", "BACKLOG.md")
        with open(path, "w") as f:
            f.write("# Backlog\n\n- MINE-1: an item a human typed and no generator knows\n")
        status = self._collect()
        returned = collect_status.write_backlog(self.tmp.name, status)
        self.assertEqual(returned, path)
        with open(path) as f:
            after = f.read()
        self.assertNotIn("MINE-1", after)
        self.assertEqual(after, collect_status.render_backlog(status))
        # …and nothing was preserved on the side first: no .bak, no .orig, no copy.
        self.assertEqual(sorted(os.listdir(os.path.dirname(path))), ["BACKLOG.md", "specs"])

    def test_the_gap_sample_is_capped_while_the_total_is_whole(self):
        """The gap section is a signal, not a worklist: it must not paste a thousand
        paths into a tracked file, and it must not shrink the repo-wide total down to
        whatever it happened to print. 137 gaps in, 137 reported, 20 listed."""
        gaps = [f"src/mod{i}/file.ts" for i in range(137)]
        fake_result = mock.MagicMock()
        fake_result.stdout = json.dumps({"version": 1, "total": 137, "gaps": gaps})
        with mock.patch.object(collect_status.subprocess, "run", return_value=fake_result), \
             mock.patch.object(collect_status, "verify_bucket", return_value=([], None)), \
             mock.patch.object(collect_status, "stale_bucket", return_value=([], None)), \
             mock.patch.object(collect_status, "security_bucket", return_value=([], None)):
            status = collect_status.collect(self.tmp.name)
        self.assertEqual(status["gaps"]["total"], 137)
        self.assertEqual(len(status["gaps"]["sample"]), 20)
        md = collect_status.render_backlog(status)
        self.assertIn("137 uncovered source file(s)", md)
        self.assertIn("137 coverage gaps", md)          # the census line, likewise whole
        self.assertIn("`src/mod19/file.ts`", md)        # the twentieth, listed
        self.assertNotIn("src/mod20/file.ts", md)       # the twenty-first, not


class VerifyBucketTest(unittest.TestCase):
    """Prove that verify_bucket preserves the errors list even on non-zero exit."""

    def test_returns_errors_even_when_subprocess_exits_nonzero(self):
        """Critical: verify_links exits non-zero on findings; errors must not be lost."""
        stdout = '[{"kind": "missing-locator", "spec_id": "SPEC-001", "behavior_id": "BEH-001", "message": "x"}]'
        fake_result = mock.MagicMock()
        fake_result.returncode = 1
        fake_result.stdout = stdout
        with mock.patch.object(collect_status.subprocess, "run", return_value=fake_result):
            errors, note = collect_status.verify_bucket("/any/project/dir")
        self.assertIsNone(note)
        self.assertEqual(len(errors), 1)
        self.assertEqual(errors[0]["kind"], "missing-locator")

    def test_empty_stdout_is_clean(self):
        """Zero exit + empty stdout returns ([], None) — no spurious note."""
        fake_result = mock.MagicMock()
        fake_result.returncode = 0
        fake_result.stdout = ""
        with mock.patch.object(collect_status.subprocess, "run", return_value=fake_result):
            errors, note = collect_status.verify_bucket("/any/project/dir")
        self.assertEqual(errors, [])
        self.assertIsNone(note)

    def test_bad_json_degrades_to_note(self):
        """Malformed stdout should not crash — degrade to ([], <note>)."""
        fake_result = mock.MagicMock()
        fake_result.stdout = "not json"
        with mock.patch.object(collect_status.subprocess, "run", return_value=fake_result):
            errors, note = collect_status.verify_bucket("/any/project/dir")
        self.assertEqual(errors, [])
        self.assertIsNotNone(note)


class MainTest(unittest.TestCase):
    """Drives the script as a process, which is the only way to see its real exit code."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        specs = os.path.join(self.tmp.name, "knowledge-base", "specs", "auth")
        os.makedirs(specs)
        with open(os.path.join(specs, "s.md"), "w") as f:
            f.write(SPEC)
        sec = os.path.join(self.tmp.name, "knowledge-base", "security", "codebase-security")
        os.makedirs(sec)
        with open(os.path.join(sec, "findings.json"), "w") as f:
            json.dump({"version": 1, "findings": [
                {"id": "SEC-001", "title": "a", "severity": "high",
                 "status": "open", "file": "x.ts"}]}, f)

    def test_status_exits_zero_with_work_outstanding(self):
        """status is the read-only check-counterpart of wrap-up: it reports, it never
        blocks, so its exit code carries no verdict about what it found. A non-zero
        exit here would make every caller that chains on `&&` — and CI — treat an
        ordinary backlog as a failure. The fixture carries outstanding work in three
        worklists at once, so a zero exit over an empty report cannot pass for this."""
        proc = subprocess.run(
            [sys.executable, SCRIPT, "--project", self.tmp.name, "--format", "json"],
            capture_output=True, text=True)
        report = json.loads(proc.stdout)
        self.assertEqual([r["behavior_id"] for r in report["intent_worklist"]], ["BEH-001"])
        self.assertEqual([r["behavior_id"] for r in report["test_owed_worklist"]], ["BEH-002"])
        self.assertEqual([f["id"] for f in report["open_security_findings"]], ["SEC-001"])
        self.assertEqual(proc.returncode, 0, proc.stderr)


if __name__ == "__main__":
    unittest.main(verbosity=2)
