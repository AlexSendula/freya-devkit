#!/usr/bin/env python3
"""Proof suite for drift.py — the P4b declarative-drift helpers."""

import json
import os
import shutil
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
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
