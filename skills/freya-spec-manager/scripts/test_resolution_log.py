#!/usr/bin/env python3
"""Proof suite for resolution_log.py — the shared append-only log core."""

import json
import os
import shutil
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import resolution_log as rl  # noqa: E402


def _rec(verdict, key, paths=None, reason="r"):
    # A generic record: `key` stands in for principle/item/spec; paths for the
    # exploding modules. `against` for the single-key (G3) shape.
    return {"date": "2026-07-01", "key": key, "paths": paths or ["a.ts"],
            "against": "X", "verdict": verdict, "reason": reason}


class AppendLoadCase(unittest.TestCase):
    def _root(self):
        d = tempfile.mkdtemp()
        self.addCleanup(lambda: shutil.rmtree(d, ignore_errors=True))
        return Path(d)

    def test_append_is_append_only(self):
        p = self._root() / "log.jsonl"
        rl.append(p, _rec("refuted", "K1"))
        rl.append(p, _rec("refuted", "K2"))
        self.assertEqual(len(p.read_text().splitlines()), 2)
        self.assertEqual(json.loads(p.read_text().splitlines()[0])["key"], "K1")

    def test_append_creates_parents_and_returns_path(self):
        p = self._root() / "nested/dir/log.jsonl"
        out = rl.append(p, _rec("refuted", "K1"))
        self.assertTrue(p.exists())
        self.assertEqual(out, str(p))

    def test_load_missing_file_is_empty(self):
        self.assertEqual(rl.load(self._root() / "nope.jsonl"), ([], []))

    def test_load_skips_malformed_with_labelled_warning(self):
        p = self._root() / "log.jsonl"
        rl.append(p, _rec("refuted", "K1"))
        with p.open("a", encoding="utf-8") as f:
            f.write("{bad json\n")
        records, warnings = rl.load(p, label="my/rel/path.jsonl")
        self.assertEqual(len(records), 1)
        self.assertEqual(len(warnings), 1)
        self.assertIn("my/rel/path.jsonl", warnings[0])   # label used, not path.name

    def test_load_blank_lines_ignored(self):
        p = self._root() / "log.jsonl"
        p.write_text('\n' + json.dumps(_rec("refuted", "K1")) + '\n\n', encoding="utf-8")
        records, warnings = rl.load(p)
        self.assertEqual(len(records), 1)
        self.assertEqual(warnings, [])


class ActiveExplodingCase(unittest.TestCase):
    """The G2/P4b shape: key = (field, path), exploded over `paths`."""
    def _keys(self, r):
        return [(r.get("key"), p) for p in (r.get("paths") or [])]

    def test_latest_wins_per_key_path(self):
        recs = [_rec("refuted", "K1", reason="first"), _rec("refuted", "K1", reason="second")]
        out = rl.active(recs, self._keys)
        self.assertEqual([r["reason"] for r in out], ["second"])

    def test_superseded_drops_the_pair(self):
        recs = [_rec("refuted", "K1"), _rec("superseded", "K1")]
        self.assertEqual(rl.active(recs, self._keys), [])

    def test_multi_path_record_dedupes(self):
        recs = [_rec("refuted", "K1", paths=["a.ts", "b.ts"])]
        self.assertEqual(len(rl.active(recs, self._keys)), 1)

    def test_want_filters_by_key_and_path(self):
        recs = [_rec("refuted", "K1", paths=["a.ts"]),
                _rec("refuted", "K2", paths=["b.ts"])]
        out = rl.active(recs, self._keys, lambda k: k[0] == "K1")
        self.assertEqual([r["key"] for r in out], ["K1"])
        out2 = rl.active(recs, self._keys, lambda k: k[1] == "b.ts")
        self.assertEqual([r["key"] for r in out2], ["K2"])


class ActiveSingleKeyCase(unittest.TestCase):
    """The G3 shape: key = (spec, against), one key per record, no explosion."""
    def _keys(self, r):
        return [(r.get("key"), r.get("against"))]

    def test_latest_wins_per_pair(self):
        recs = [_rec("refuted", "S1", reason="first"), _rec("refuted", "S1", reason="second")]
        out = rl.active(recs, self._keys)
        self.assertEqual([r["reason"] for r in out], ["second"])

    def test_superseded_and_want(self):
        recs = [_rec("refuted", "S1"), _rec("refuted", "S2"), _rec("superseded", "S2")]
        out = rl.active(recs, self._keys, lambda k: k[0] in ("S1", "S2"))
        self.assertEqual([r["key"] for r in out], ["S1"])   # S2 retired


if __name__ == "__main__":
    unittest.main(verbosity=2)
