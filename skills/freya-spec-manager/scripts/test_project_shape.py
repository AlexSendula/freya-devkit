#!/usr/bin/env python3
"""Proof suite for project_shape.py — the bootstrap shape detector."""

import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
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
            with self.subTest(key=k):
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


# Read off the constants themselves, so a member added tomorrow is exercised on the next
# run without anyone remembering to name it. Bound here, at import, rather than inside each
# test on purpose: it lets a mutation run empty `project_shape._NOT_SOURCE` (or drop a single
# member from it) and watch the affected rows go red by name, instead of the table quietly
# iterating an empty registry and reporting green — which is how a table over an exclusion
# list becomes worse than the one test it replaced.
_NOT_SOURCE_MEMBERS = tuple(sorted(project_shape._NOT_SOURCE))
_CENSUS_SKIP_MEMBERS = tuple(sorted(project_shape._CENSUS_SKIP))

# Not in `_NOT_SOURCE`, and a language the graph in these fixtures cannot read — so it is
# what a blind spot looks like when nothing suppresses it.
_SOURCE_EXT = ".java"


class _ShapeFixture(unittest.TestCase):
    """A project whose graph reads `.ts` and nothing else, so any other extension on
    disk is unread — and the only question left is whether it *counts*."""

    def setUp(self):
        patcher = mock.patch.object(project_shape, "run_detect_project", return_value={})
        patcher.start()
        self.addCleanup(patcher.stop)
        self._fresh_project()

    def _fresh_project(self):
        """A brand-new empty project. Each table row gets one, so a row that fails
        cannot leave its fixture behind and take the rows after it down with it."""
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.proj = tmp.name
        return self.proj

    def _write(self, rel):
        p = os.path.join(self.proj, rel)
        os.makedirs(os.path.dirname(p) or self.proj, exist_ok=True)
        with open(p, "w", encoding="utf-8") as f:
            f.write("x\n")

    def _graph(self):
        """A substrate-aware graph with no census block, so `_blind_spots` falls through
        to the disk walk — the path `_NOT_SOURCE` and `_CENSUS_SKIP` actually gate."""
        d = os.path.join(self.proj, "knowledge-base", ".graph")
        os.makedirs(d, exist_ok=True)
        with open(os.path.join(d, "graph.json"), "w", encoding="utf-8") as f:
            json.dump({
                "version": 1,
                "substrate": {
                    "backend": "homegrown",
                    "coverage": {"languages": ["typescript"], "extensions": [".ts"],
                                 "relations": ["imports"], "incremental": True},
                },
                "files": {},
            }, f)

    def _classify(self, *rels):
        for rel in rels:
            self._write(rel)
        self._graph()
        return project_shape.classify(self.proj)


class NotSourceRegistryTest(_ShapeFixture):
    """Table over `_NOT_SOURCE` — 35 declared, 1 of them ever named until now.

    This list decides what does *not* count as source when the graph is empty, which is
    the difference between `greenfield` (bootstrap treats the repo as new) and `unknown`
    (bootstrap stops and asks). Every member is a claim that a repo carrying only that
    file type has shown no evidence of being an existing codebase, and every member is one
    edit away from being the thing that hides a real one — `.sh` already was, and ADR-029
    records the correction.

    Each row plants exactly one file of one extension and asserts the *verdict*, not the
    membership: `assertIn(ext, _NOT_SOURCE)` would re-state the constant and would pass
    with the filter deleted. `test_the_fixtures_really_reach_the_exclusion_list` below is
    the standing proof that these fixtures are gated here and not thrown away earlier by
    the dotfile or skip-directory rules, which would make every row green for free.
    """

    def test_the_registry_is_not_empty(self):
        """Non-vacuity guard: an emptied `_NOT_SOURCE` must fail here rather than leave
        the table below looping over nothing."""
        self.assertTrue(project_shape._NOT_SOURCE,
                        "_NOT_SOURCE is empty — the table below asserts nothing")

    def test_no_member_of_not_source_makes_a_repo_look_like_an_existing_codebase(self):
        for ext in _NOT_SOURCE_MEMBERS:
            with self.subTest(extension=ext):
                self._fresh_project()
                r = self._classify(f"src/sample{ext}")
                self.assertEqual(r["recommendation"], "greenfield")
                self.assertNotIn("blind_spots", r["evidence"])

    def test_an_extension_off_the_list_is_a_blind_spot(self):
        """The control that keeps the rows above honest: same fixture, same single file,
        an extension the list does not carry — and the verdict flips."""
        self.assertNotIn(_SOURCE_EXT, project_shape._NOT_SOURCE)
        r = self._classify(f"src/Sample{_SOURCE_EXT}")
        self.assertEqual(r["recommendation"], "unknown")
        self.assertEqual(r["evidence"]["blind_spots"], {_SOURCE_EXT: 1})

    def test_the_fixtures_really_reach_the_exclusion_list(self):
        """The vacuity canary. `unreadable_files` drops dotfiles and prunes directories
        before `_NOT_SOURCE` is ever consulted, so a fixture planted under the wrong name
        would be filtered upstream and pass for the wrong reason. Empty the list and the
        same fixture must flip — which proves the rows above are gated *here*."""
        self._write("src/sample.md")
        self._graph()
        with mock.patch.object(project_shape, "_NOT_SOURCE", set()):
            r = project_shape.classify(self.proj)
        self.assertEqual(r["recommendation"], "unknown")
        self.assertEqual(r["evidence"]["blind_spots"], {".md": 1})


class CensusSkipRegistryTest(_ShapeFixture):
    """Table over `_CENSUS_SKIP` — 14 declared, 2 of them named until now.

    These are the directories the disk walk refuses to descend into. A member that stopped
    pruning would report a vendored dependency tree as this project's unread source, and
    `graphify-out` is in the list precisely because a backend counting its own output as
    files it failed to read gave every project a blind spot in its own graph directory.

    Each row plants a real blind-spot extension *inside* the directory and asserts the
    verdict stays clean. Note that `.git`, `.next` and `.venv` are also caught by the
    walk's separate dot-directory rule, so those three rows are belt-and-braces: measured
    by emptying `_CENSUS_SKIP`, eleven rows go red and those three stay green. They pin the
    directory names, not the pruning — the pruning is proven by the other eleven.
    """

    def test_the_registry_is_not_empty(self):
        self.assertTrue(project_shape._CENSUS_SKIP,
                        "_CENSUS_SKIP is empty — the table below asserts nothing")

    def test_no_skipped_directory_contributes_a_blind_spot(self):
        for name in _CENSUS_SKIP_MEMBERS:
            with self.subTest(directory=name):
                self._fresh_project()
                r = self._classify(f"{name}/pkg/Sample{_SOURCE_EXT}")
                self.assertEqual(r["recommendation"], "greenfield")
                self.assertNotIn("blind_spots", r["evidence"])

    def test_the_same_file_outside_a_skipped_directory_is_a_blind_spot(self):
        """The control: it is the directory doing the work, not the file being invisible."""
        r = self._classify(f"src/pkg/Sample{_SOURCE_EXT}")
        self.assertEqual(r["recommendation"], "unknown")
        self.assertEqual(r["evidence"]["blind_spots"], {_SOURCE_EXT: 1})

    def test_the_fixtures_really_reach_the_skip_list(self):
        """The vacuity canary, for a member with no dot prefix to hide behind."""
        self.assertIn("node_modules", project_shape._CENSUS_SKIP)
        self._write(f"node_modules/pkg/Sample{_SOURCE_EXT}")
        self._graph()
        with mock.patch.object(project_shape, "_CENSUS_SKIP", set()):
            r = project_shape.classify(self.proj)
        self.assertEqual(r["recommendation"], "unknown")
        self.assertEqual(r["evidence"]["blind_spots"], {_SOURCE_EXT: 1})


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

    def test_empty_dict_on_timeout(self):
        """SEC-008's caller half. `TimeoutExpired` derives from `SubprocessError`, not from
        `OSError`, so it is not covered by anything else in the tuple: adding the timeout
        without adding the class would have swapped a hang for an uncaught exception out of
        `classify()`, which is a worse answer than the hang for a caller whose whole contract
        is "empty dict on any failure".
        """
        boom = subprocess.TimeoutExpired(cmd="detect_project.py", timeout=1)
        with mock.patch.object(project_shape.subprocess, "run", side_effect=boom):
            self.assertEqual(project_shape.run_detect_project("/nope"), {})


#: A stand-in for detect_project.py that never answers. It appends one byte to a heartbeat
#: file every 10 ms, unbuffered, inside the directory it was handed, so "was this process
#: still alive after the call returned?" is answered by reading one file size twice — which
#: behaves the same on all three platforms. `os.kill(pid, 0)` is the obvious probe and is not
#: usable here: on Windows `os.kill` is `TerminateProcess`, so the probe would kill the thing
#: it claims to measure. The twenty-second deadline is a leash rather than part of the test —
#: twenty times the bound the rows below inject — so that a failure cannot leave a process
#: running on the machine, and so that a mutation which removes the bound goes red in twenty
#: seconds instead of never.
_WEDGED_CHILD = """\
import os, sys, time
deadline = time.time() + 20
with open(os.path.join(sys.argv[1], "heartbeat"), "ab", buffering=0) as fh:
    while time.time() < deadline:
        fh.write(b".")
        time.sleep(0.01)
"""

#: The control: the same shape, answering the way detect_project.py answers.
_ANSWERING_CHILD = """\
import sys
sys.stdout.write('{"runtime": "python"}')
"""


class OverrunningChildTest(unittest.TestCase):
    """SEC-008's caller half, exercised against a real child instead of inspected on a mock.

    What stood here asserted `run.call_args[1]["timeout"] == project_shape._DETECT_TIMEOUT`:
    the value the caller passed, compared against the constant the caller read it from. It
    could not fail while the module compiled, and its docstring claimed it was the row that
    made the pair mean "the child is bounded". Measured 2026-08-23, with `_DETECT_TIMEOUT`
    set to `None` — which is `subprocess.run(..., timeout=None)`, the unbounded wait the
    finding is about — this module stayed at 38 passed.

    So the bound is spent rather than read. `_WEDGED_CHILD` overruns it and the control
    answers inside it; without the control, `{}` out of the overrun row would prove only that
    this harness produces `{}`, which every other failure path in `run_detect_project` also
    does. This class injects a one-second bound so it costs about a second, which makes it
    deliberately blind to what the shipped number is — `ShippedBoundTest` below is that half.
    """

    #: Long enough that a cold interpreter on the slowest runner in the CI matrix has started
    #: and written its first byte before the kill, short enough that the row costs a second.
    BOUND = 1.0

    #: Thirty heartbeats' worth. A child that survived the call grows the file during this
    #: window; the assertion is that it does not grow by one byte.
    SETTLE = 0.3

    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.tmp, True)
        self.project = os.path.join(self.tmp, "project")
        os.makedirs(self.project)

    def _stand_in(self, source):
        path = os.path.join(self.tmp, "child.py")
        with open(path, "w", encoding="utf-8") as f:
            f.write(source)
        return path

    def _beats(self):
        path = os.path.join(self.project, "heartbeat")
        return os.path.getsize(path) if os.path.exists(path) else 0

    def test_a_child_that_answers_inside_the_bound_is_left_alone(self):
        with mock.patch.object(project_shape, "_DETECT_PROJECT",
                               self._stand_in(_ANSWERING_CHILD)), \
                mock.patch.object(project_shape, "_DETECT_TIMEOUT", self.BOUND):
            self.assertEqual(project_shape.run_detect_project(self.project),
                             {"runtime": "python"})

    def test_an_overrunning_child_is_killed_and_the_caller_answers_empty(self):
        with mock.patch.object(project_shape, "_DETECT_PROJECT",
                               self._stand_in(_WEDGED_CHILD)), \
                mock.patch.object(project_shape, "_DETECT_TIMEOUT", self.BOUND):
            started = time.monotonic()
            result = project_shape.run_detect_project(self.project)
            elapsed = time.monotonic() - started

        self.assertEqual(result, {})
        # Half the stand-in's own leash: the row must not be able to pass by outlasting the
        # child, which is what "no timeout at all" looks like from out here.
        self.assertLess(elapsed, 10, "the caller waited for the child rather than bounding it")
        beats = self._beats()
        self.assertGreater(beats, 0, "the stand-in never ran; this row would prove nothing")
        time.sleep(self.SETTLE)
        self.assertEqual(self._beats(), beats,
                         "the child outlived the call that gave up waiting for it")


class ShippedBoundTest(unittest.TestCase):
    """The number that actually ships, which the class above deliberately does not use.

    `OverrunningChildTest` injects a one-second bound so it can run in a second, and is
    therefore green with `_DETECT_TIMEOUT = None`. These two rows are the other half: what
    the shipped value has to be, and that it is the value the child is given.
    """

    def test_the_shipped_bound_is_a_finite_number_of_seconds(self):
        """Both ends, with a failure behind each. Too small and the bound fires on healthy
        repositories — a cold interpreter plus a walk of up to
        `detect_project._WALK_FILE_LIMIT` files is not instant — and `run_detect_project`
        answers `{}`, which bootstrap reads as "no stack detected" rather than as an error.
        Too large and it is a bound to a type checker and a hang to the engineer waiting on
        `freya spec bootstrap`; ten minutes is an order of magnitude past the shipped sixty.
        """
        bound = project_shape._DETECT_TIMEOUT
        self.assertIsInstance(bound, (int, float))
        self.assertGreaterEqual(bound, 5)
        self.assertLessEqual(bound, 600)

    def test_that_bound_and_no_other_is_what_reaches_the_child(self):
        """The wiring, and only the wiring: this says the kwarg is there and carries the
        module's own constant. It is the row above that says the constant is a bound, and
        keeping the two apart is what stopped the pair being circular."""
        fake_result = mock.MagicMock()
        fake_result.stdout = "{}"
        fake_result.returncode = 0
        with mock.patch.object(project_shape.subprocess, "run",
                               return_value=fake_result) as run:
            project_shape.run_detect_project("/nope")
        self.assertEqual(run.call_args[1]["timeout"], project_shape._DETECT_TIMEOUT)


if __name__ == "__main__":
    unittest.main(verbosity=2)
