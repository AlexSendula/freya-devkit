#!/usr/bin/env python3
"""Proof suite for intent.py — the INTENT-NNN authoring helper (G1)."""

import os
import shutil
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from intent import _next_id, new_record, render_record  # noqa: E402
from frontmatter import parse_frontmatter  # noqa: E402


class IntentHelperCase(unittest.TestCase):
    def _root(self):
        d = tempfile.mkdtemp()
        self.addCleanup(lambda: shutil.rmtree(d, ignore_errors=True))
        return Path(d)

    def test_next_id_empty_dir_is_001(self):
        self.assertEqual(_next_id(self._root() / "knowledge-base/intents"), "INTENT-001")

    def test_next_id_increments_past_max(self):
        d = self._root() / "knowledge-base/intents"
        d.mkdir(parents=True)
        (d / "INTENT-001.md").write_text("x")
        (d / "INTENT-002.md").write_text("x")
        self.assertEqual(_next_id(d), "INTENT-003")

    def test_new_record_writes_parseable_block_style(self):
        root = self._root()
        path = new_record(str(root), ["BEH-003"], "Alex", "Threat model changed.", "2026-07-01")
        self.assertTrue(path.endswith("knowledge-base/intents/INTENT-001.md"))
        fm, body = parse_frontmatter(Path(path).read_text(encoding="utf-8"))
        self.assertEqual(fm["id"], "INTENT-001")
        self.assertEqual(fm["behaviors"], ["BEH-003"])   # block-style list survives the parser
        self.assertEqual(fm["approver"], "Alex")
        self.assertEqual(fm["date"], "2026-07-01")
        self.assertIn("Threat model changed.", body)

    def test_new_record_creates_missing_dir(self):
        root = self._root()
        self.assertFalse((root / "knowledge-base/intents").exists())
        new_record(str(root), ["BEH-003"], "Alex", "why", "2026-07-01")
        self.assertTrue((root / "knowledge-base/intents").is_dir())

    def test_render_multiple_behaviors_block_style(self):
        text = render_record("INTENT-007", ["BEH-003", "BEH-004"], "Alex", "why", "2026-07-01")
        fm, _ = parse_frontmatter(text)
        self.assertEqual(fm["behaviors"], ["BEH-003", "BEH-004"])


if __name__ == "__main__":
    unittest.main(verbosity=2)
