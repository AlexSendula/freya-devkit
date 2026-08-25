#!/usr/bin/env python3
"""Proof suite for drift.py — the P4b declarative-drift helpers."""

import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import drift  # noqa: E402  — `_GRAPH_OPS`, for the tests that run the real child CLI
from drift import append_resolution, active_prior, build_drift_context, compute_impact, drift_gaps, RESOLUTIONS_RELPATH  # noqa: E402


class ResolutionsCase(unittest.TestCase):
    def _root(self):
        d = tempfile.mkdtemp()
        self.addCleanup(lambda: shutil.rmtree(d, ignore_errors=True))
        return Path(d)

    def _rec(self, verdict, item="SPEC-001", paths=None, reason="r"):
        return {"date": "2026-07-01", "item": item,
                "paths": paths or ["lib/webauthn.ts"], "verdict": verdict, "reason": reason}

    def test_append_is_append_only(self):
        root = self._root()
        append_resolution(str(root), self._rec("refuted"))
        append_resolution(str(root), self._rec("refuted", item="ADR-001", paths=["prisma/schema.prisma"]))
        lines = (root / RESOLUTIONS_RELPATH).read_text().splitlines()
        self.assertEqual(len(lines), 2)
        self.assertEqual(json.loads(lines[0])["item"], "SPEC-001")

    def test_prior_returns_active_for_item(self):
        root = self._root()
        append_resolution(str(root), self._rec("refuted", reason="model misread"))
        recs, warns = active_prior(str(root), "SPEC-001")
        self.assertEqual(len(recs), 1)
        self.assertEqual(recs[0]["reason"], "model misread")
        self.assertEqual(warns, [])

    def test_prior_filters_by_item_and_paths(self):
        root = self._root()
        append_resolution(str(root), self._rec("refuted", paths=["lib/webauthn.ts"]))
        self.assertEqual(active_prior(str(root), "SPEC-999")[0], [])                  # other item
        self.assertEqual(active_prior(str(root), "SPEC-001", paths=["other.ts"])[0], [])  # other path

    def test_superseded_retires_the_pair(self):
        root = self._root()
        append_resolution(str(root), self._rec("refuted"))
        append_resolution(str(root), self._rec("superseded", reason="code moved"))
        recs, _ = active_prior(str(root), "SPEC-001")
        self.assertEqual(recs, [])
        self.assertEqual(len((root / RESOLUTIONS_RELPATH).read_text().splitlines()), 2)  # append-only

    def test_latest_wins(self):
        root = self._root()
        append_resolution(str(root), self._rec("refuted", reason="first"))
        append_resolution(str(root), self._rec("refuted", reason="second"))
        recs, _ = active_prior(str(root), "SPEC-001")
        self.assertEqual([r["reason"] for r in recs], ["second"])

    def test_multi_path_record_dedupes(self):
        root = self._root()
        append_resolution(str(root), self._rec("refuted", paths=["a.ts", "b.ts"]))
        recs, _ = active_prior(str(root), "SPEC-001")
        self.assertEqual(len(recs), 1)  # one record, not one per path

    def test_malformed_line_skipped_with_warning(self):
        root = self._root()
        append_resolution(str(root), self._rec("refuted"))
        with (root / RESOLUTIONS_RELPATH).open("a", encoding="utf-8") as f:
            f.write("{bad json\n")
        recs, warns = active_prior(str(root), "SPEC-001")
        self.assertEqual(len(recs), 1)
        self.assertTrue(warns)


def _write(path, content):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def _spec(spec_id, category, decisions, related_code, status="implemented"):
    dblock = "intentional_decisions:\n" + "".join(f"  - {d}\n" for d in decisions) if decisions else ""
    rblock = "related_code:\n" + "".join(f"  - {p}\n" for p in related_code) if related_code else ""
    return (f"---\nid: {spec_id}\ntitle: {spec_id}\ncategory: {category}\n"
            f"status: {status}\ncertainty: 90\ncreated: 2026-07-01\nupdated: 2026-07-01\n"
            f"{rblock}{dblock}---\n\n# {spec_id}\n")


def _adr(root, adr_id, related_code, status="accepted", title="T"):
    d = root / "knowledge-base/decisions"
    d.mkdir(parents=True, exist_ok=True)
    rblock = "related_code:\n" + "".join(f"  - {p}\n" for p in related_code) if related_code else ""
    (d / f"{adr_id}-x.md").write_text(
        f"---\nid: {adr_id}\ntitle: {title}\nstatus: {status}\n{rblock}---\n"
        f"# {adr_id}\n## Decision\nWe do X.\n", encoding="utf-8")


class ComputeImpactCase(unittest.TestCase):
    def test_success_with_no_dependents_is_code_graph(self):
        fake = mock.Mock(stdout='{"all_affected": []}')
        with mock.patch("drift.changed_files", return_value=["x.ts"]), \
             mock.patch("drift.subprocess.run", return_value=fake):
            impact, source = compute_impact(".", "BASE")
        self.assertEqual(source, "code-graph")   # tool ran fine, just no dependents
        self.assertEqual(impact, {"x.ts"})

    def test_graph_tool_missing_degrades_to_changed_only(self):
        with mock.patch("drift.changed_files", return_value=["x.ts"]), \
             mock.patch("drift.subprocess.run", side_effect=FileNotFoundError()):
            impact, source = compute_impact(".", "BASE")
        self.assertEqual(source, "changed-only")
        self.assertEqual(impact, {"x.ts"})

    def test_no_graph_result_degrades_to_changed_only(self):
        # graph_ops exits 0 but emits {} (no cached graph) → no all_affected key
        # → changed-only, so the operator sees a narrower (not falsely complete) radius.
        fake = mock.Mock(stdout='{}')
        with mock.patch("drift.changed_files", return_value=["x.ts"]), \
             mock.patch("drift.subprocess.run", return_value=fake):
            impact, source = compute_impact(".", "BASE")
        self.assertEqual(source, "changed-only")
        self.assertEqual(impact, {"x.ts"})

    def test_no_changes_is_empty(self):
        with mock.patch("drift.changed_files", return_value=[]):
            impact, source = compute_impact(".", "BASE")
        self.assertEqual(source, "empty")
        self.assertEqual(impact, set())


class ImpactArgvCase(unittest.TestCase):
    """A name git reports is a filename, and the child CLI has to read it as one.

    `git diff --name-only` will happily print `--build`. It is a legal filename on every
    platform this runs on, and `git add -- --build` is all it takes to get one into a
    repository. Those names went into the code-graph child's argv as bare positional
    values, where argparse read them as flags — and `--build` sits in the same mutually
    exclusive group as `--impact`, so the child exited rc=2, the `CalledProcessError` was
    swallowed one frame up, and `compute_impact` returned `changed-only`. Every dependent
    dropped out of the blast radius, and the run reported success. One filename turns the
    declarative-drift gate into a check of the changed files and nothing else.

    Two changes went in, and only one of them is load-bearing. Said plainly, because a
    docstring that credits both would leave the next reader unable to tell which:

      - each path is spelled `./<path>`. argparse cannot mistake that for a flag, and
        `normalize_key` (posixpath.normpath) strips it again on the way in, so the graph is
        keyed exactly as before. This is the fix. Drop it, with or without the reorder, and
        the second test below goes red.
      - `--impact` moved last, so its `nargs='+'` has no `--dir` or `--format` behind it
        left to swallow. Defence in depth, and labelled as such: with the `./` in place no
        input reaches the greedy case, so reverting this alone leaves both tests green. The
        security report claims both halves are required; measured, they are not.

    Neither is asserted through argv shape. An `assertLess(argv.index(...), ...)` passes
    with either half missing, which is exactly how this defect survived review the first
    time.

    These run the real child process against a real graph on purpose. Mocking
    `subprocess.run` here would assert the argv this file already believes in, which is the
    thing in question.
    """

    def _project(self):
        """Two Python files, b importing a, with a real graph built on disk."""
        d = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, d, ignore_errors=True)
        _write(Path(d) / "a.py", "A = 1\n")
        _write(Path(d) / "b.py", "from a import A\nB = A\n")
        built = subprocess.run(
            [sys.executable, drift._GRAPH_OPS, "--build", "--dir", d,
             "--format", "json", "--non-interactive"], capture_output=True, text=True)
        self.assertEqual(built.returncode, 0, built.stderr)
        return d

    def test_an_ordinary_change_still_gets_its_dependents(self):
        """The `./` prefix must not cost anything: `normalize_key` strips it, so the keys
        the child answers with are the keys the graph holds."""
        proj = self._project()
        with mock.patch("drift.changed_files", return_value=["a.py"]):
            impact, source = compute_impact(proj, "BASE")
        self.assertEqual(source, "code-graph")
        self.assertEqual(impact, {"a.py", "b.py"})

    def test_a_leading_dash_filename_does_not_collapse_the_blast_radius(self):
        proj = self._project()
        with mock.patch("drift.changed_files", return_value=["a.py", "--build"]):
            impact, source = compute_impact(proj, "BASE")
        self.assertEqual(source, "code-graph")
        self.assertIn("b.py", impact)


class ContextCase(unittest.TestCase):
    def _root(self):
        d = tempfile.mkdtemp()
        self.addCleanup(lambda: shutil.rmtree(d, ignore_errors=True))
        return Path(d)

    def test_target_when_related_code_intersects_impact(self):
        root = self._root()
        _write(root / "knowledge-base/specs/auth/SPEC-001.md",
               _spec("SPEC-001", "auth", ["userVerification preferred"], ["lib/webauthn.ts"]))
        ctx = build_drift_context(str(root), "BASE", impact={"lib/webauthn.ts"}, source="test")
        ids = [t["item"] for t in ctx["targets"]]
        self.assertEqual(ids, ["SPEC-001"])
        self.assertEqual(ctx["targets"][0]["hit_paths"], ["lib/webauthn.ts"])
        self.assertEqual(ctx["targets"][0]["decisions"], ["userVerification preferred"])

    def test_a_declared_path_spelled_differently_from_gits_still_hits(self):
        """`impact` holds git's spelling; `related_code` holds whatever the author typed.

        Compared verbatim, an ordinary `./lib/webauthn.ts` never matched
        `lib/webauthn.ts`, so the spec dropped out of the P4b drift checkpoint's
        target set — silently, from a resolve-to-proceed gate. That is a
        confidently short answer, which is worse than a wrong one because
        nothing about the output says it is short.

        The same defect as the G1 locator comparison, one file over. That one
        was found and this one was not, because the sibling survey asked who
        resolves a LOCATOR rather than who compares a DECLARED PATH to git — so
        the ADR row below is here to make the pair testable together.
        """
        for declared in ("./lib/webauthn.ts", "lib//webauthn.ts", "lib/x/../webauthn.ts"):
            with self.subTest(declared=declared):
                root = self._root()
                _write(root / "knowledge-base/specs/auth/SPEC-001.md",
                       _spec("SPEC-001", "auth", ["userVerification preferred"], [declared]))
                _adr(root, "ADR-001", [declared])
                ctx = build_drift_context(str(root), "BASE",
                                          impact={"lib/webauthn.ts"}, source="test")
                self.assertEqual(sorted(t["item"] for t in ctx["targets"]),
                                 ["ADR-001", "SPEC-001"])

    def test_no_target_when_no_intersection(self):
        root = self._root()
        _write(root / "knowledge-base/specs/auth/SPEC-001.md",
               _spec("SPEC-001", "auth", ["d"], ["lib/webauthn.ts"]))
        ctx = build_drift_context(str(root), "BASE", impact={"lib/other.ts"}, source="test")
        self.assertEqual(ctx["targets"], [])

    def test_excludes_deprecated_spec_and_specs_without_decisions(self):
        root = self._root()
        _write(root / "knowledge-base/specs/auth/SPEC-001.md",
               _spec("SPEC-001", "auth", ["d"], ["a.ts"], status="deprecated"))
        _write(root / "knowledge-base/specs/auth/SPEC-002.md",
               _spec("SPEC-002", "auth", [], ["a.ts"]))  # no decisions
        ctx = build_drift_context(str(root), "BASE", impact={"a.ts"}, source="test")
        self.assertEqual(ctx["targets"], [])

    def test_accepted_adr_is_target_proposed_excluded(self):
        root = self._root()
        _adr(root, "ADR-001", ["prisma/schema.prisma"], status="accepted")
        _adr(root, "ADR-002", ["prisma/schema.prisma"], status="proposed")
        ctx = build_drift_context(str(root), "BASE", impact={"prisma/schema.prisma"}, source="test")
        self.assertEqual([t["item"] for t in ctx["targets"]], ["ADR-001"])
        self.assertEqual(ctx["targets"][0]["kind"], "adr")

    def test_empty_impact_is_noop(self):
        root = self._root()
        _write(root / "knowledge-base/specs/auth/SPEC-001.md",
               _spec("SPEC-001", "auth", ["d"], ["a.ts"]))
        ctx = build_drift_context(str(root), "BASE", impact=set(), source="empty")
        self.assertEqual(ctx["targets"], [])
        self.assertEqual(ctx["impact_source"], "empty")


class GapsCase(unittest.TestCase):
    def _root(self):
        d = tempfile.mkdtemp()
        self.addCleanup(lambda: shutil.rmtree(d, ignore_errors=True))
        return Path(d)

    def test_lists_decisions_without_related_code(self):
        root = self._root()
        _write(root / "knowledge-base/specs/auth/SPEC-001.md",
               _spec("SPEC-001", "auth", ["no related_code decision"], []))    # gap
        _write(root / "knowledge-base/specs/auth/SPEC-002.md",
               _spec("SPEC-002", "auth", ["scoped"], ["lib/x.ts"]))            # not a gap
        gaps = drift_gaps(str(root))
        self.assertEqual([g["item"] for g in gaps["specs"]], ["SPEC-001"])

    def test_lists_adrs_without_related_code(self):
        root = self._root()
        _adr(root, "ADR-001", [])                      # gap (no related_code)
        _adr(root, "ADR-002", ["prisma/schema.prisma"])  # not a gap
        gaps = drift_gaps(str(root))
        self.assertEqual([g["item"] for g in gaps["adrs"]], ["ADR-001"])

    def test_empty_project_no_gaps(self):
        gaps = drift_gaps(str(self._root()))
        self.assertEqual(gaps["specs"], [])
        self.assertEqual(gaps["adrs"], [])


if __name__ == "__main__":
    unittest.main(verbosity=2)
