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


class CensusedGraphTest(unittest.TestCase):
    """ADR-029 — the census in the artifact, preferred over a fresh disk walk.

    The walk consults a hardcoded skip list that knows nothing about `.gitignore` or this
    project's directory classifications; measured on freya-devkit it reports 96 unread files
    of which 68 are deliberately out of scope. The census applies the build's own scope rule,
    so it is both cheaper and right. The walk stays only for graphs written before it existed.
    """

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.proj = self.tmp.name
        patcher = mock.patch.object(project_shape, "run_detect_project", return_value={})
        patcher.start()
        self.addCleanup(patcher.stop)

    def _files(self, *rels):
        for rel in rels:
            p = os.path.join(self.proj, rel)
            os.makedirs(os.path.dirname(p) or self.proj, exist_ok=True)
            with open(p, "w", encoding="utf-8") as f:
                f.write("x\n")

    def _graph(self, files, unmapped):
        d = os.path.join(self.proj, "knowledge-base", ".graph")
        os.makedirs(d, exist_ok=True)
        substrate = {"backend": "homegrown",
                     "coverage": {"languages": ["typescript"], "extensions": [".ts"],
                                  "relations": ["imports"], "incremental": True}}
        if unmapped is not None:
            substrate["unmapped_source"] = unmapped
        with open(os.path.join(d, "graph.json"), "w", encoding="utf-8") as f:
            json.dump({"version": 1, "substrate": substrate, "files": files}, f)

    def test_the_artifact_is_preferred_over_the_disk_walk(self):
        """The graph claims 12 .java; the disk holds none. A walk would return {}."""
        self._graph({}, {"files": 12, "extensions": {".java": 12}})
        r = project_shape.classify(self.proj)
        self.assertEqual(r["evidence"]["blind_spots"], {".java": 12})

    def test_blind_spots_are_reported_on_the_brownfield_branch(self):
        """The exact hole. Two TypeScript imports used to buy silence about 400 unread Java
        files, and the evidence block would report `runtime: jvm` and `source_files: 3` side
        by side without ever noticing the two were in tension."""
        self._graph({"a.ts": {"imports": ["b.ts"]}, "b.ts": {"imports": []}},
                    {"files": 12, "extensions": {".java": 12}})
        r = project_shape.classify(self.proj)
        self.assertEqual(r["recommendation"], "brownfield")
        self.assertEqual(r["evidence"]["blind_spots"], {".java": 12})
        self.assertIn("existing codebase", r["reason"])

    def test_format_text_says_what_is_not_graphed(self):
        """`--format text` is what spec-manager's bootstrap invokes, and it had no
        blind-spot branch at all — so even the path that did compute them was invisible."""
        self._graph({"a.ts": {"imports": ["b.ts"]}, "b.ts": {"imports": []}},
                    {"files": 12, "extensions": {".java": 12}})
        text = project_shape._format_text(project_shape.classify(self.proj))
        self.assertIn("not graphed:", text)
        self.assertIn("12 .java", text)

    def test_format_text_omits_the_line_when_there_is_nothing_to_say(self):
        self._graph({"a.ts": {"imports": ["b.ts"]}, "b.ts": {"imports": []}}, {"files": 0})
        text = project_shape._format_text(project_shape.classify(self.proj))
        self.assertNotIn("not graphed:", text)

    def test_a_censused_clean_graph_is_authoritative(self):
        """The census says the backend read everything in scope; the walk must not
        second-guess it with files the build deliberately excluded."""
        self._files("vendor/Main.java", "vendor/Other.java")
        self._graph({}, {"files": 0})
        self.assertEqual(project_shape.classify(self.proj)["recommendation"], "greenfield")

    def test_a_pre_census_graph_still_walks_the_disk(self):
        """The compatibility guarantee: deleting the walk would regress every graph written
        before ADR-029 to "no blind spots at all" — the confidently-empty answer it guards."""
        self._files("src/Main.java", "src/Other.java", "src/Third.java")
        self._graph({}, None)
        r = project_shape.classify(self.proj)
        self.assertEqual(r["recommendation"], "unknown")
        self.assertEqual(r["evidence"]["blind_spots"], {".java": 3})

    def test_verdict_pin_a_a_powershell_repo_stays_unknown(self):
        """MUST NOT CHANGE. `.ps1` is absent from `_NOT_SOURCE`, so this is `unknown` today;
        an allowlist that dropped it would have flipped a real codebase to `greenfield`."""
        self._graph({}, {"files": 12, "extensions": {".ps1": 12}})
        self.assertEqual(project_shape.classify(self.proj)["recommendation"], "unknown")

    def test_verdict_pin_b_a_shell_repo_becomes_unknown(self):
        """A DELIBERATE CHANGE. Today this is `greenfield`, because `.sh` is in `_NOT_SOURCE`
        — a repository made of shell scripts told its own tooling it was an empty scaffold.
        Recorded in ADR-029 so the new value is a decision rather than a surprise."""
        self._graph({}, {"files": 40, "extensions": {".sh": 40}})
        self.assertEqual(project_shape.classify(self.proj)["recommendation"], "unknown")

    def test_a_repo_the_scope_rule_excluded_entirely_is_not_greenfield(self):
        """THE REGRESSION PIN. Measured on a real 40-file deployment repository whose whole
        codebase is shell scripts under `scripts/` — a built-in top-level exclusion. The census
        correctly reports nothing unread (they are out of scope, not unreadable), and this path
        then called it `greenfield`: ADR-005's confidently-empty answer, reintroduced by the
        mechanism written to remove it, and via the same `scripts/` rule that once stopped
        freya graphing itself."""
        self._files("scripts/deploy.sh", "scripts/setup.sh", "README.md")
        self._graph({}, {"files": 0})
        r = project_shape.classify(self.proj)
        self.assertEqual(r["recommendation"], "unknown")
        self.assertIn("outside the graph's scope", r["reason"])

    def test_a_census_error_falls_back_to_the_walk_rather_than_reading_as_clean(self):
        """`{"files": null, "error": ...}` is written precisely so a census that could not run
        is never confused with a clean one. Reading it as censused-and-clean turned that
        explicit I-don't-know back into a silent zero AND suppressed the fallback walk."""
        self._files("src/Main.java", "src/Other.java")
        self._graph({}, {"files": None, "error": "PermissionError"})
        r = project_shape.classify(self.proj)
        self.assertEqual(r["recommendation"], "unknown")
        self.assertEqual(r["evidence"]["blind_spots"], {".java": 2})

    def test_an_empty_censused_graph_still_walks_for_languages_off_the_tier_lists(self):
        """The census is closed-world; the walk is open-world. Preferring the census
        unconditionally made every language in neither tier list — .ipynb, .graphql, .nix,
        .hx — silent, which is the original defect for those languages exactly."""
        self._files("nb/analysis.ipynb", "nb/model.ipynb")
        self._graph({}, {"files": 0})
        r = project_shape.classify(self.proj)
        self.assertEqual(r["recommendation"], "unknown")
        self.assertEqual(r["evidence"]["blind_spots"], {".ipynb": 2})

    def test_verdict_pin_c_a_scaffold_with_an_installer_becomes_greenfield(self):
        """A DELIBERATE CHANGE, the other way. Today one `.ps1` installer beside three real
        source files yields `unknown`; the materiality rule removes that false alarm."""
        self._graph({"a.ts": {"imports": []}, "b.ts": {"imports": []},
                     "c.ts": {"imports": []}}, {"files": 0})
        self.assertEqual(project_shape.classify(self.proj)["recommendation"], "greenfield")


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
