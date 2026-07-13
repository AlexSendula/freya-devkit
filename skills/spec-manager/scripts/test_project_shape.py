#!/usr/bin/env python3
"""Proof suite for project_shape.py — the bootstrap shape detector."""

import json
import os
import sys
import tempfile
import unittest
import unittest.mock as mock

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import project_shape  # noqa: E402


def _write_graph(project_dir, files):
    d = os.path.join(project_dir, "knowledge-base", ".graph")
    os.makedirs(d, exist_ok=True)
    with open(os.path.join(d, "graph.json"), "w", encoding="utf-8") as f:
        json.dump({"version": 1, "files": files}, f)


class CountGraphTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.proj = self.tmp.name

    def test_missing_graph_returns_not_present(self):
        self.assertEqual(project_shape.count_graph(self.proj), (0, 0, False))

    def test_counts_only_internal_edges(self):
        # external: and unresolved: imports are NOT internal wiring.
        _write_graph(self.proj, {
            "lib/a.ts": {"imports": ["lib/b.ts", "external:react", "unresolved:./missing"]},
            "lib/b.ts": {"imports": []},
        })
        self.assertEqual(project_shape.count_graph(self.proj), (2, 1, True))

    def test_malformed_graph_returns_not_present(self):
        d = os.path.join(self.proj, "knowledge-base", ".graph")
        os.makedirs(d)
        with open(os.path.join(d, "graph.json"), "w", encoding="utf-8") as f:
            f.write("{not json")
        self.assertEqual(project_shape.count_graph(self.proj), (0, 0, False))


class ClassifyTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.proj = self.tmp.name

    def test_brownfield_when_internal_edges_present(self):
        _write_graph(self.proj, {"a.ts": {"imports": ["b.ts"]}, "b.ts": {"imports": []}})
        with mock.patch.object(project_shape, "run_detect_project", return_value={"runtime": "nodejs"}):
            r = project_shape.classify(self.proj)
        self.assertEqual(r["recommendation"], "brownfield")
        self.assertEqual(r["evidence"]["internal_edges"], 1)
        self.assertEqual(r["evidence"]["stack"], {"runtime": "nodejs"})

    def test_greenfield_when_zero_internal_edges(self):
        _write_graph(self.proj, {"a.ts": {"imports": ["external:react"]}})
        with mock.patch.object(project_shape, "run_detect_project", return_value={}):
            r = project_shape.classify(self.proj)
        self.assertEqual(r["recommendation"], "greenfield")
        self.assertEqual(r["evidence"]["internal_edges"], 0)

    def test_unknown_when_no_graph(self):
        with mock.patch.object(project_shape, "run_detect_project", return_value={}):
            r = project_shape.classify(self.proj)
        self.assertEqual(r["recommendation"], "unknown")
        self.assertFalse(r["evidence"]["graph_present"])

    def test_evidence_keys_always_present(self):
        with mock.patch.object(project_shape, "run_detect_project", return_value={}):
            r = project_shape.classify(self.proj)
        for k in ("source_files", "internal_edges", "stack", "graph_present"):
            self.assertIn(k, r["evidence"])


class RunDetectProjectTest(unittest.TestCase):
    def test_empty_dict_on_subprocess_failure(self):
        with mock.patch.object(project_shape.subprocess, "run", side_effect=FileNotFoundError()):
            self.assertEqual(project_shape.run_detect_project("/nope"), {})

    def test_empty_dict_on_json_decode_failure(self):
        fake_result = mock.MagicMock()
        fake_result.stdout = "not json"
        fake_result.returncode = 0
        with mock.patch.object(project_shape.subprocess, "run", return_value=fake_result):
            self.assertEqual(project_shape.run_detect_project("/nope"), {})


if __name__ == "__main__":
    unittest.main(verbosity=2)
