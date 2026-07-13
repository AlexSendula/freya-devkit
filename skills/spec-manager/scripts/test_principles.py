#!/usr/bin/env python3
"""Proof suite for principles.py — the G2 principle-enforcement helpers."""

import json
import os
import shutil
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from principles import (  # noqa: E402
    parse_principles, cmd_list, append_resolution, active_prior,
    RESOLUTIONS_RELPATH,
)

PRINCIPLES_MD = """# Principles

> intro prose ignored by the parser.

## Principles

1. **Authenticated by default.** Every endpoint requires auth unless a spec documents an exception.
   _Why: a forgotten check should fail closed._

2. **No secret in source.** Secrets come from the environment, never the repo.
"""


def _write(path: Path, content: str):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


class ParseCase(unittest.TestCase):
    def test_parses_numbered_principles_with_titles(self):
        items = parse_principles(PRINCIPLES_MD)
        self.assertEqual([i["n"] for i in items], [1, 2])
        self.assertEqual(items[0]["title"], "Authenticated by default")
        self.assertIn("fail closed", items[0]["text"])  # continuation line folded in

    def test_freeform_file_yields_no_items(self):
        self.assertEqual(parse_principles("just some prose, no numbered rules"), [])


class ListCase(unittest.TestCase):
    def _root(self):
        d = tempfile.mkdtemp()
        self.addCleanup(lambda: shutil.rmtree(d, ignore_errors=True))
        return Path(d)

    def test_text_prints_section_when_present(self):
        root = self._root()
        _write(root / "knowledge-base/principles.md", PRINCIPLES_MD)
        out = cmd_list(str(root), "text")
        self.assertIn("Authenticated by default", out)
        self.assertNotIn("intro prose", out)  # only the ## Principles section

    def test_absent_file_is_empty_and_safe(self):
        root = self._root()
        self.assertEqual(cmd_list(str(root), "text"), "")
        self.assertEqual(cmd_list(str(root), "json"), "[]")


class ResolutionsCase(unittest.TestCase):
    def _root(self):
        d = tempfile.mkdtemp()
        self.addCleanup(lambda: shutil.rmtree(d, ignore_errors=True))
        return Path(d)

    def _rec(self, verdict, paths, reason="r", principle=1):
        return {"date": "2026-07-01", "principle": principle, "verdict": verdict,
                "paths": paths, "reason": reason}

    def test_append_is_append_only(self):
        root = self._root()
        append_resolution(str(root), self._rec("refuted", ["a.ts"]))
        append_resolution(str(root), self._rec("refuted", ["b.ts"]))
        lines = (root / RESOLUTIONS_RELPATH).read_text().splitlines()
        self.assertEqual(len(lines), 2)
        self.assertEqual(json.loads(lines[0])["paths"], ["a.ts"])  # first line untouched

    def test_prior_returns_matching_active_record(self):
        root = self._root()
        append_resolution(str(root), self._rec("refuted", ["a.ts"], reason="intentional"))
        recs, warns = active_prior(str(root), paths=["a.ts"])
        self.assertEqual(len(recs), 1)
        self.assertEqual(recs[0]["reason"], "intentional")
        self.assertEqual(warns, [])

    def test_prior_excludes_unqueried_paths_and_principles(self):
        root = self._root()
        append_resolution(str(root), self._rec("refuted", ["a.ts"], principle=1))
        self.assertEqual(active_prior(str(root), paths=["b.ts"])[0], [])
        self.assertEqual(active_prior(str(root), paths=["a.ts"], principle=2)[0], [])

    def test_superseded_record_retires_the_pair(self):
        root = self._root()
        append_resolution(str(root), self._rec("refuted", ["a.ts"]))
        append_resolution(str(root), self._rec("superseded", ["a.ts"], reason="stale"))
        recs, _ = active_prior(str(root), paths=["a.ts"])
        self.assertEqual(recs, [])  # retired
        # append-only: both lines still on disk
        self.assertEqual(len((root / RESOLUTIONS_RELPATH).read_text().splitlines()), 2)

    def test_latest_refutation_wins(self):
        root = self._root()
        append_resolution(str(root), self._rec("refuted", ["a.ts"], reason="first"))
        append_resolution(str(root), self._rec("refuted", ["a.ts"], reason="second"))
        recs, _ = active_prior(str(root), paths=["a.ts"])
        self.assertEqual([r["reason"] for r in recs], ["second"])

    def test_malformed_line_is_skipped_with_warning(self):
        root = self._root()
        append_resolution(str(root), self._rec("refuted", ["a.ts"]))
        with (root / RESOLUTIONS_RELPATH).open("a", encoding="utf-8") as f:
            f.write("{not valid json\n")
        recs, warns = active_prior(str(root), paths=["a.ts"])
        self.assertEqual(len(recs), 1)
        self.assertTrue(warns)

    def test_multipath_record_dedupes(self):
        root = self._root()
        append_resolution(str(root), self._rec("refuted", ["a.ts", "b.ts"]))
        recs, _ = active_prior(str(root), paths=["a.ts", "b.ts"])
        self.assertEqual(len(recs), 1)  # one record, not one per path


if __name__ == "__main__":
    unittest.main(verbosity=2)
