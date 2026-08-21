#!/usr/bin/env python3
"""Proof suite for adr.py — the ADR authoring/gather/integrity helpers (P4a)."""

import os
import shutil
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from adr import _next_id, new_record, render_record, load_adrs, active_adrs, verify_adrs, render_index  # noqa: E402
from frontmatter import parse_frontmatter  # noqa: E402


class AuthoringCase(unittest.TestCase):
    def _root(self):
        d = tempfile.mkdtemp()
        self.addCleanup(lambda: shutil.rmtree(d, ignore_errors=True))
        return Path(d)

    def test_next_id_empty_dir_is_001(self):
        self.assertEqual(_next_id(self._root() / "knowledge-base/decisions"), "ADR-001")

    def test_next_id_increments_past_max(self):
        d = self._root() / "knowledge-base/decisions"
        d.mkdir(parents=True)
        (d / "ADR-001-a.md").write_text("x")
        (d / "ADR-004-b.md").write_text("x")
        self.assertEqual(_next_id(d), "ADR-005")

    def test_new_record_writes_four_section_scaffold(self):
        root = self._root()
        path = new_record(str(root), "Use Postgres", "accepted", "2026-07-01")
        # Path equality, not a '/'-suffix match: new_record returns a NATIVE path
        # (correctly — it is printed for a human to open), and the first Windows
        # CI run failed this on separators alone. The claim under test is the
        # location, which Path compares in the host's own spelling.
        self.assertEqual(Path(path),
                         root / "knowledge-base" / "decisions" / "ADR-001-use-postgres.md")
        text = Path(path).read_text(encoding="utf-8")
        fm, body = parse_frontmatter(text)
        self.assertEqual(fm["id"], "ADR-001")
        self.assertEqual(fm["title"], "Use Postgres")
        self.assertEqual(fm["status"], "accepted")
        for section in ("## Decision", "## Rationale",
                        "## Rejected Alternatives", "## Revisit Conditions"):
            self.assertIn(section, body)

    def test_new_record_creates_missing_dir(self):
        root = self._root()
        self.assertFalse((root / "knowledge-base/decisions").exists())
        new_record(str(root), "X", "proposed", "2026-07-01")
        self.assertTrue((root / "knowledge-base/decisions").is_dir())

    def test_render_includes_tags_and_supersedes(self):
        text = render_record("ADR-007", "Y", "accepted", "2026-07-01",
                             tags=["database"], supersedes="ADR-006")
        fm, _ = parse_frontmatter(text)
        self.assertEqual(fm["tags"], ["database"])
        self.assertEqual(fm["supersedes"], "ADR-006")


def _write_adr(root, adr_id, status="accepted", title="T", extra=""):
    d = root / "knowledge-base/decisions"
    d.mkdir(parents=True, exist_ok=True)
    (d / f"{adr_id}-x.md").write_text(
        "---\n"
        f"id: {adr_id}\n"
        f"title: {title}\n"
        f"status: {status}\n"
        f"{extra}"
        "---\n"
        f"# {adr_id}: {title}\n## Decision\nWe do X.\n",
        encoding="utf-8")


class GatherCase(unittest.TestCase):
    def _root(self):
        d = tempfile.mkdtemp()
        self.addCleanup(lambda: shutil.rmtree(d, ignore_errors=True))
        return Path(d)

    def test_load_parses_wellformed(self):
        root = self._root()
        _write_adr(root, "ADR-001", title="Use Postgres")
        adrs, warns = load_adrs(str(root))
        self.assertEqual(warns, [])
        self.assertEqual(adrs[0]["id"], "ADR-001")
        self.assertEqual(adrs[0]["title"], "Use Postgres")
        self.assertIn("We do X.", adrs[0]["body"])

    def test_malformed_is_warning_not_silent_drop(self):
        root = self._root()
        _write_adr(root, "ADR-001")
        _write_adr(root, "ADR-002", status="bogus")   # invalid status
        adrs, warns = load_adrs(str(root))
        self.assertEqual([a["id"] for a in adrs], ["ADR-001"])   # bad one excluded
        self.assertTrue(any("ADR-002" in w for w in warns))       # but LOUDLY warned

    def test_active_filters_to_accepted(self):
        root = self._root()
        _write_adr(root, "ADR-001", status="accepted")
        _write_adr(root, "ADR-002", status="proposed")
        _write_adr(root, "ADR-003", status="superseded")
        active, _ = active_adrs(str(root))
        self.assertEqual([a["id"] for a in active], ["ADR-001"])

    def test_empty_dir_returns_empty(self):
        self.assertEqual(load_adrs(str(self._root())), ([], []))


class IntegrityCase(unittest.TestCase):
    def _root(self):
        d = tempfile.mkdtemp()
        self.addCleanup(lambda: shutil.rmtree(d, ignore_errors=True))
        return Path(d)

    def test_clean_when_valid(self):
        root = self._root()
        _write_adr(root, "ADR-001")
        self.assertEqual(verify_adrs(str(root)), [])

    def test_flags_duplicate_id(self):
        root = self._root()
        d = root / "knowledge-base/decisions"
        d.mkdir(parents=True)
        for name in ("ADR-001-a.md", "ADR-002-b.md"):
            (d / name).write_text(
                "---\nid: ADR-001\ntitle: T\nstatus: accepted\n---\n# x\n",
                encoding="utf-8")
        errs = verify_adrs(str(root))
        self.assertTrue(any("duplicate id" in e for e in errs))

    def test_flags_dangling_supersedes(self):
        root = self._root()
        _write_adr(root, "ADR-001", extra="superseded_by: ADR-099\n")
        errs = verify_adrs(str(root))
        self.assertTrue(any("ADR-099" in e for e in errs))

    def test_flags_bad_status(self):
        root = self._root()
        _write_adr(root, "ADR-001", status="bogus")
        errs = verify_adrs(str(root))
        self.assertTrue(any("status" in e for e in errs))

    def test_flags_unparseable_frontmatter(self):
        """BEH-079 — the one integrity branch nothing reached. The four tests
        above all feed `verify_adrs` well-formed YAML carrying a bad *value*,
        so the `except FrontmatterError` arm was never entered and the module
        could have raised out of a Tier-1 gate instead of reporting. SPEC-016
        named the hole and docked its certainty for it; the sibling gate has
        had the equivalent test since
        `test_verify_intent.py#VerifyIntentCase.test_unparseable_record_is_error_not_traceback`.
        Three malformations, because one arm of the parser is not the parser.
        """
        root = self._root()
        _write_adr(root, "ADR-001")          # a healthy neighbour, must stay clean
        d = root / "knowledge-base/decisions"
        broken = {
            "ADR-002-no-fence.md":
                "---\nid: ADR-002\ntitle: T\nstatus: accepted\n",
            "ADR-003-open-array.md":
                "---\nid: ADR-003\ntitle: T\nstatus: accepted\n"
                "tags: [governance, adr\n---\n# x\n",
            "ADR-004-tab-indent.md":
                "---\nid: ADR-004\ntitle: T\nstatus: accepted\n"
                "related_code:\n\t- adr.py\n---\n# x\n",
        }
        for name, text in broken.items():
            (d / name).write_text(text, encoding="utf-8")

        errs = verify_adrs(str(root))        # must RETURN — a raise fails here
        for name in broken:
            with self.subTest(record=name):
                self.assertTrue(
                    any(name in e and "unparseable" in e for e in errs), errs)
        # And the walk is not abandoned at the first bad file: the valid
        # neighbour is still reached, and still reported clean.
        self.assertFalse(any("ADR-001" in e for e in errs), errs)

    def test_list_renders_table(self):
        root = self._root()
        _write_adr(root, "ADR-001", title="Use Postgres")
        out = render_index(str(root))
        self.assertIn("ADR-001", out)
        self.assertIn("Use Postgres", out)


if __name__ == "__main__":
    unittest.main(verbosity=2)
