#!/usr/bin/env python3
"""Proof suite for collect_status.py — the status aggregator."""
import json
import os
import sys
import tempfile
import unittest
import unittest.mock as mock

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import collect_status  # noqa: E402

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


if __name__ == "__main__":
    unittest.main(verbosity=2)
