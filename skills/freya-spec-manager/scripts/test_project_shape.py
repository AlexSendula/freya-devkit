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


class BlindBackendIsNotGreenfieldTest(unittest.TestCase):
    """Zero internal edges means one of two very different things.

    Either the project genuinely has no wiring yet, or the backend that built the graph cannot
    read the language it is written in. Calling both *greenfield* is what made a Java repo —
    and, until the resolver was repaired, freya-devkit itself — look like an empty scaffold to
    its own tooling. The `substrate` block added in Track B Phase 1 is what makes the two
    distinguishable.
    """

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.proj = self.tmp.name

    def _files(self, *rels):
        for rel in rels:
            p = os.path.join(self.proj, rel)
            os.makedirs(os.path.dirname(p), exist_ok=True)
            with open(p, "w", encoding="utf-8") as f:
                f.write("x\n")

    def _graph(self, files, extensions=(".ts", ".tsx")):
        d = os.path.join(self.proj, "knowledge-base", ".graph")
        os.makedirs(d, exist_ok=True)
        with open(os.path.join(d, "graph.json"), "w", encoding="utf-8") as f:
            json.dump({
                "version": 1,
                "substrate": {
                    "backend": "homegrown",
                    "coverage": {"languages": ["typescript"], "extensions": list(extensions),
                                 "relations": ["imports"], "incremental": True},
                },
                "files": files,
            }, f)

    def test_a_java_repo_the_backend_cannot_read_is_not_greenfield(self):
        self._files("src/Main.java", "src/Service.java", "src/Repo.java")
        self._graph({})
        result = project_shape.classify(self.proj)
        self.assertEqual(result["recommendation"], "unknown")
        self.assertIn(".java", result["reason"])
        self.assertEqual(result["evidence"]["blind_spots"], {".java": 3})

    def test_a_genuinely_empty_scaffold_is_still_greenfield(self):
        """The capability that must survive: no wiring, and nothing unread."""
        self._files("src/index.ts")
        self._graph({"src/index.ts": {"imports": []}})
        result = project_shape.classify(self.proj)
        self.assertEqual(result["recommendation"], "greenfield")

    def test_wiring_beats_blind_spots(self):
        """Real edges mean brownfield even if some files went unread."""
        self._files("src/a.ts", "src/b.ts", "Main.java")
        self._graph({"src/a.ts": {"imports": ["src/b.ts"]}, "src/b.ts": {"imports": []}})
        self.assertEqual(project_shape.classify(self.proj)["recommendation"], "brownfield")

    def test_a_graph_without_a_substrate_block_keeps_the_old_answer(self):
        """Graphs built before Phase 1 must not start reporting unknown."""
        self._files("src/Main.java")
        d = os.path.join(self.proj, "knowledge-base", ".graph")
        os.makedirs(d, exist_ok=True)
        with open(os.path.join(d, "graph.json"), "w", encoding="utf-8") as f:
            json.dump({"version": 1, "files": {}}, f)
        self.assertEqual(project_shape.classify(self.proj)["recommendation"], "greenfield")

    def test_dependency_trees_do_not_count_as_blind_spots(self):
        self._files("node_modules/pkg/Main.java", "src/index.ts")
        self._graph({"src/index.ts": {"imports": []}})
        self.assertEqual(project_shape.classify(self.proj)["recommendation"], "greenfield")


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

    def test_counts_object_shaped_edges(self):
        """The shape code-graph writes since 2026-08-20."""
        _write_graph(self.proj, {
            "lib/a.ts": {"imports": [
                {"to": "lib/b.ts", "kind": "imports", "provenance": "extracted"},
                {"to": "external:react", "kind": "imports", "provenance": "extracted"},
            ]},
            "lib/b.ts": {"imports": []},
        })
        self.assertEqual(project_shape.count_graph(self.proj), (2, 1, True))

    def test_object_edges_still_reach_the_brownfield_verdict(self):
        """The consequence, not just the count. Misreading the new shape would report a
        wired codebase as greenfield — the exact wrong answer this module exists to
        prevent, and the one that drives bootstrap over a real codebase."""
        _write_graph(self.proj, {
            "lib/a.ts": {"imports": [
                {"to": "lib/b.ts", "kind": "imports", "provenance": "extracted"}]},
            "lib/b.ts": {"imports": []},
        })
        with mock.patch.object(project_shape, "run_detect_project", return_value={}):
            self.assertEqual(
                project_shape.classify(self.proj)["recommendation"], "brownfield")

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
