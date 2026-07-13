#!/usr/bin/env python3
"""Proof suite for contradictions.py — the G3 contradiction-check helpers."""

import json
import os
import shutil
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from contradictions import (  # noqa: E402
    build_context, build_adr_context, append_resolution, active_prior, RESOLUTIONS_RELPATH,
)

PRINCIPLES = "## Principles\n\n1. **Authenticated by default.** Endpoints need auth.\n"


def _write(path: Path, content: str):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def _spec(spec_id, category, decisions):
    block = ""
    if decisions:
        block = "intentional_decisions:\n" + "".join(f"  - {d}\n" for d in decisions)
    return (
        "---\n"
        f"id: {spec_id}\n"
        f"title: {spec_id} Title\n"
        f"category: {category}\n"
        "status: implemented\n"
        "certainty: 90\n"
        "created: 2026-07-01\n"
        "updated: 2026-07-01\n"
        f"{block}"
        "---\n\n"
        f"# {spec_id}\n"
    )


def _adr(root, adr_id, status="accepted", title="T", body="We do X."):
    d = root / "knowledge-base/decisions"
    d.mkdir(parents=True, exist_ok=True)
    (d / f"{adr_id}-x.md").write_text(
        f"---\nid: {adr_id}\ntitle: {title}\nstatus: {status}\n---\n"
        f"# {adr_id}\n## Decision\n{body}\n", encoding="utf-8")


class ContextCase(unittest.TestCase):
    def _root(self):
        d = tempfile.mkdtemp()
        self.addCleanup(lambda: shutil.rmtree(d, ignore_errors=True))
        return Path(d)

    def _project(self, root):
        _write(root / "knowledge-base/principles.md", PRINCIPLES)
        _write(root / "knowledge-base/specs/auth/SPEC-001.md",
               _spec("SPEC-001", "auth", ["No password fallback"]))
        _write(root / "knowledge-base/specs/auth/SPEC-002.md",
               _spec("SPEC-002", "auth", ["Uniform 404 to prevent enumeration"]))
        _write(root / "knowledge-base/specs/api/SPEC-003.md",
               _spec("SPEC-003", "api", ["Rate limit at the edge"]))

    def test_context_has_principles_and_same_category_peers(self):
        root = self._root(); self._project(root)
        ctx = build_context(str(root), "SPEC-001")
        self.assertEqual(ctx["category"], "auth")
        self.assertEqual(len(ctx["principles"]), 1)
        self.assertEqual([p["spec_id"] for p in ctx["peers"]], ["SPEC-002"])  # same cat, not self

    def test_context_excludes_self_and_other_categories(self):
        root = self._root(); self._project(root)
        peers = [p["spec_id"] for p in build_context(str(root), "SPEC-001")["peers"]]
        self.assertNotIn("SPEC-001", peers)   # self excluded
        self.assertNotIn("SPEC-003", peers)   # different category excluded

    def test_context_excludes_peers_without_decisions(self):
        root = self._root()
        _write(root / "knowledge-base/principles.md", PRINCIPLES)
        _write(root / "knowledge-base/specs/auth/SPEC-001.md", _spec("SPEC-001", "auth", ["d"]))
        _write(root / "knowledge-base/specs/auth/SPEC-002.md", _spec("SPEC-002", "auth", []))
        self.assertEqual(build_context(str(root), "SPEC-001")["peers"], [])

    def test_context_spec_not_found_is_safe(self):
        root = self._root(); self._project(root)
        ctx = build_context(str(root), "SPEC-999")
        self.assertEqual(ctx["peers"], [])
        self.assertIn("note", ctx)

    def test_context_no_principles(self):
        root = self._root()
        _write(root / "knowledge-base/specs/auth/SPEC-001.md", _spec("SPEC-001", "auth", ["d"]))
        self.assertEqual(build_context(str(root), "SPEC-001")["principles"], [])


class ResolutionsCase(unittest.TestCase):
    def _root(self):
        d = tempfile.mkdtemp()
        self.addCleanup(lambda: shutil.rmtree(d, ignore_errors=True))
        return Path(d)

    def _rec(self, verdict, against, spec="SPEC-001", reason="r"):
        return {"date": "2026-07-01", "spec": spec, "against": against,
                "verdict": verdict, "reason": reason}

    def test_append_is_append_only(self):
        root = self._root()
        append_resolution(str(root), self._rec("refuted", "principle:1"))
        append_resolution(str(root), self._rec("refuted", "SPEC-002"))
        lines = (root / RESOLUTIONS_RELPATH).read_text().splitlines()
        self.assertEqual(len(lines), 2)
        self.assertEqual(json.loads(lines[0])["against"], "principle:1")

    def test_prior_returns_active_for_spec(self):
        root = self._root()
        append_resolution(str(root), self._rec("refuted", "principle:1", reason="intentional public"))
        recs, warns = active_prior(str(root), "SPEC-001")
        self.assertEqual(len(recs), 1)
        self.assertEqual(recs[0]["reason"], "intentional public")
        self.assertEqual(warns, [])

    def test_prior_filters_by_spec_and_against(self):
        root = self._root()
        append_resolution(str(root), self._rec("refuted", "principle:1", spec="SPEC-001"))
        self.assertEqual(active_prior(str(root), "SPEC-002")[0], [])           # other spec
        self.assertEqual(active_prior(str(root), "SPEC-001", against="SPEC-009")[0], [])  # other against

    def test_superseded_retires_the_pair(self):
        root = self._root()
        append_resolution(str(root), self._rec("refuted", "principle:1"))
        append_resolution(str(root), self._rec("superseded", "principle:1", reason="spec rewritten"))
        recs, _ = active_prior(str(root), "SPEC-001")
        self.assertEqual(recs, [])
        self.assertEqual(len((root / RESOLUTIONS_RELPATH).read_text().splitlines()), 2)  # append-only

    def test_latest_wins(self):
        root = self._root()
        append_resolution(str(root), self._rec("refuted", "principle:1", reason="first"))
        append_resolution(str(root), self._rec("refuted", "principle:1", reason="second"))
        recs, _ = active_prior(str(root), "SPEC-001")
        self.assertEqual([r["reason"] for r in recs], ["second"])

    def test_malformed_line_skipped_with_warning(self):
        root = self._root()
        append_resolution(str(root), self._rec("refuted", "principle:1"))
        with (root / RESOLUTIONS_RELPATH).open("a", encoding="utf-8") as f:
            f.write("{bad json\n")
        recs, warns = active_prior(str(root), "SPEC-001")
        self.assertEqual(len(recs), 1)
        self.assertTrue(warns)


class ADRContextCase(unittest.TestCase):
    def _root(self):
        d = tempfile.mkdtemp()
        self.addCleanup(lambda: shutil.rmtree(d, ignore_errors=True))
        return Path(d)

    def test_context_includes_active_adrs(self):
        root = self._root()
        _write(root / "knowledge-base/specs/auth/SPEC-001.md",
               _spec("SPEC-001", "auth", ["d"]))
        _adr(root, "ADR-001", title="Use Postgres")
        ctx = build_context(str(root), "SPEC-001")
        self.assertEqual([a["id"] for a in ctx["adrs"]], ["ADR-001"])
        self.assertEqual(ctx["adr_warnings"], [])

    def test_context_excludes_superseded_adr(self):
        root = self._root()
        _write(root / "knowledge-base/specs/auth/SPEC-001.md",
               _spec("SPEC-001", "auth", ["d"]))
        _adr(root, "ADR-001", status="accepted")
        _adr(root, "ADR-002", status="superseded")
        ctx = build_context(str(root), "SPEC-001")
        self.assertEqual([a["id"] for a in ctx["adrs"]], ["ADR-001"])

    def test_context_no_adrs_is_empty(self):
        root = self._root()
        _write(root / "knowledge-base/specs/auth/SPEC-001.md",
               _spec("SPEC-001", "auth", ["d"]))
        self.assertEqual(build_context(str(root), "SPEC-001")["adrs"], [])


class ADRSelfContextCase(unittest.TestCase):
    def _root(self):
        d = tempfile.mkdtemp()
        self.addCleanup(lambda: shutil.rmtree(d, ignore_errors=True))
        return Path(d)

    def test_has_principles_and_peer_adrs(self):
        root = self._root()
        _write(root / "knowledge-base/principles.md", PRINCIPLES)
        _adr(root, "ADR-001", title="A")
        _adr(root, "ADR-002", title="B")
        ctx = build_adr_context(str(root), "ADR-001")
        self.assertEqual(ctx["adr"]["id"], "ADR-001")
        self.assertEqual(len(ctx["principles"]), 1)
        self.assertEqual([a["id"] for a in ctx["peer_adrs"]], ["ADR-002"])  # self excluded

    def test_unknown_adr_is_safe(self):
        root = self._root()
        _adr(root, "ADR-001")
        ctx = build_adr_context(str(root), "ADR-999")
        self.assertEqual(ctx["peer_adrs"], [])
        self.assertIn("note", ctx)


if __name__ == "__main__":
    unittest.main(verbosity=2)
