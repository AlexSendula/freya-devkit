# Shared resolution-log helper (refactor) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Extract the duplicated append-only resolution-log logic from `principles.py` (G2), `contradictions.py` (G3), and `drift.py` (P4b) into one `resolution_log.py`, and refactor all three to delegate — with **zero public-behavior change**.

**Architecture:** `resolution_log.py` exposes `append(path, record)`, `load(path, label=None) → (records, warnings)`, and `active(records, keys_of, want=None) → list` (the latest-wins / drop-`superseded` / dedupe-by-append-order core, parameterized by two callbacks). Each module keeps its constants, public signatures, record schema, and CLI; only the bodies delegate. G3's non-exploding `(spec, against)` key and G2/P4b's exploding `(field, path)` keys both express through `keys_of`.

**Tech Stack:** Python 3.12 stdlib only (`unittest`, `json`, `pathlib`).

## Global Constraints

- **Stdlib-only Python** — zero third-party imports.
- **The three existing test files are the regression net and MUST NOT be edited.** `test_principles.py`, `test_contradictions.py`, `test_drift.py` stay **byte-unchanged** and must pass. If a refactor makes one fail, fix the *refactor*, never the test.
- **Preserve every public surface:** each module keeps `RESOLUTIONS_RELPATH`, `VERDICTS`, the exact signatures of `append_resolution(project, record)` and `active_prior(...)`, `_load_records(project)`, record schemas, and CLIs. Only internal bodies change.
- **Behavior-preserving incl. the warning text:** `load(path, label)` uses `label` for the "skipped malformed line …" message, and each module passes its `RESOLUTIONS_RELPATH` so the string is identical to today.
- **Test framework:** stdlib `unittest`; new test file does `sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))` then imports `resolution_log`; run via `python skills/spec-manager/scripts/test_<name>.py`.
- **Branch:** continue on `feat/behavior-layer` (do NOT merge).
- **Commits** end with: `Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>`.

---

## File Structure

- **Create** `skills/spec-manager/scripts/resolution_log.py` — `append` / `load` / `active`.
- **Create** `skills/spec-manager/scripts/test_resolution_log.py` — helper proof suite.
- **Modify** `skills/spec-manager/scripts/principles.py` — delegate (bodies only).
- **Modify** `skills/spec-manager/scripts/contradictions.py` — delegate (bodies only).
- **Modify** `skills/spec-manager/scripts/drift.py` — delegate (bodies only).
- **Do NOT touch** `test_principles.py` / `test_contradictions.py` / `test_drift.py`.

---

### Task 1: `resolution_log.py` + tests

**Files:**
- Create: `skills/spec-manager/scripts/resolution_log.py`
- Test: `skills/spec-manager/scripts/test_resolution_log.py`

**Interfaces:**
- Produces: `append(path, record) -> str`; `load(path, label=None) -> (records: list, warnings: list)`; `active(records, keys_of, want=None) -> list`.

- [ ] **Step 1: Write the failing tests**

Create `skills/spec-manager/scripts/test_resolution_log.py`:

```python
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
```

- [ ] **Step 2: Run to verify it fails**

Run: `python skills/spec-manager/scripts/test_resolution_log.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'resolution_log'`.

- [ ] **Step 3: Implement**

Create `skills/spec-manager/scripts/resolution_log.py`:

```python
#!/usr/bin/env python3
"""Append-only resolution-log core, shared by the governance resolution logs
(G2 `principles.py`, G3 `contradictions.py`, P4b `drift.py`).

Each caller keeps its own RELPATH, VERDICTS, record schema, and public
signatures; only the mechanics live here:
- append(path, record): write one JSONL line (sorted keys), creating parents.
- load(path, label=None) -> (records, warnings): parse in append order, skip a
  malformed line with a warning naming `label` (default: the file name); a
  missing file -> ([], []).
- active(records, keys_of, want=None) -> list: latest-active records — keep the
  LAST record per key (keys_of explodes a record into the keys it covers), drop
  keys whose latest verdict is `superseded`, apply the `want` filter, and return
  the survivors de-duped in append order.
"""

import json
from pathlib import Path


def append(path, record):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as f:
        f.write(json.dumps(record, sort_keys=True) + "\n")
    return str(path)


def load(path, label=None):
    path = Path(path)
    label = label or path.name
    records, warnings = [], []
    if not path.exists():
        return records, warnings
    for i, line in enumerate(
            path.read_text(encoding="utf-8", errors="replace").splitlines(), 1):
        line = line.strip()
        if not line:
            continue
        try:
            records.append(json.loads(line))
        except json.JSONDecodeError:
            warnings.append(f"skipped malformed line {i} in {label}")
    return records, warnings


def active(records, keys_of, want=None):
    latest = {}  # key -> (append_idx, record)
    for idx, rec in enumerate(records):
        for k in keys_of(rec):
            latest[k] = (idx, rec)
    picked = {}  # append_idx -> record (de-dupe multi-key records)
    for k, (idx, rec) in latest.items():
        if rec.get("verdict") == "superseded":
            continue
        if want is not None and not want(k):
            continue
        picked[idx] = rec
    return [picked[i] for i in sorted(picked)]
```

- [ ] **Step 4: Run to verify it passes**

Run: `python skills/spec-manager/scripts/test_resolution_log.py -v`
Expected: PASS (11 tests).

- [ ] **Step 5: Commit**

```bash
git add skills/spec-manager/scripts/resolution_log.py skills/spec-manager/scripts/test_resolution_log.py
git commit -m "feat(spec-manager): resolution_log.py — shared append-only log core

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

### Task 2: Refactor `principles.py` (G2) onto the helper

**Files:**
- Modify: `skills/spec-manager/scripts/principles.py`
- Regression net (DO NOT EDIT): `skills/spec-manager/scripts/test_principles.py`

**Interfaces:**
- Consumes: `resolution_log.append/load/active`.
- Unchanged public surface: `RESOLUTIONS_RELPATH`, `VERDICTS`, `append_resolution(project, record)`, `_load_records(project)`, `active_prior(project, paths=None, principle=None) -> (list, warnings)`.

- [ ] **Step 1: Add the import**

`principles.py` currently imports `argparse, json, re, sys, date, Path` and does NOT manipulate `sys.path`. Add `import os` to the imports, and after the import block add:
```python
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import resolution_log  # noqa: E402
```

- [ ] **Step 2: Delegate the three bodies**

Replace `append_resolution`, `_load_records`, and `active_prior` with these delegating versions (keep the signatures and the surrounding module exactly as-is):

```python
def append_resolution(project, record):
    return resolution_log.append(_resolutions_path(project), record)


def _load_records(project):
    return resolution_log.load(_resolutions_path(project), RESOLUTIONS_RELPATH)


def active_prior(project, paths=None, principle=None):
    """Latest-active resolution per (principle, path)."""
    records, warnings = _load_records(project)
    want_paths = set(paths) if paths else None
    keys_of = lambda r: [(r.get("principle"), p) for p in (r.get("paths") or [])]
    want = lambda k: (want_paths is None or k[1] in want_paths) and \
                     (principle is None or k[0] == principle)
    return resolution_log.active(records, keys_of, want), warnings
```

Delete the now-unused local loop bodies these replace. Leave `_resolutions_path`, `_principles_path`, `parse_principles`, `cmd_list`, `_cmd_resolve`, `main`, and all constants untouched.

- [ ] **Step 3: Confirm the regression net is untouched and green**

The test file must be byte-unchanged:
```bash
git diff --stat skills/spec-manager/scripts/test_principles.py    # expect: no output (unchanged)
python skills/spec-manager/scripts/test_principles.py -v
```
Expected: `test_principles.py` shows NO diff; all 11 tests PASS.

- [ ] **Step 4: Commit**

```bash
git add skills/spec-manager/scripts/principles.py
git commit -m "refactor(spec-manager): principles.py delegates to resolution_log (G2)

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

### Task 3: Refactor `contradictions.py` (G3) onto the helper

**Files:**
- Modify: `skills/spec-manager/scripts/contradictions.py`
- Regression net (DO NOT EDIT): `skills/spec-manager/scripts/test_contradictions.py`

**Interfaces:**
- Unchanged public surface: `RESOLUTIONS_RELPATH`, `VERDICTS`, `append_resolution(project, record)`, `_load_records(project)`, `active_prior(project, spec, against=None) -> (list, warnings)`, plus `build_context`/`build_adr_context` (untouched).

- [ ] **Step 1: Add the import**

`contradictions.py` already has `sys.path.insert(...)` and sibling imports (`search_specs`, `principles`, `adr`). Add to that block:
```python
import resolution_log  # noqa: E402
```

- [ ] **Step 2: Delegate the three bodies**

Replace `append_resolution`, `_load_records`, and `active_prior` with (note the **single-key** `keys_of` — G3 does not explode over paths):

```python
def append_resolution(project, record):
    return resolution_log.append(_resolutions_path(project), record)


def _load_records(project):
    return resolution_log.load(_resolutions_path(project), RESOLUTIONS_RELPATH)


def active_prior(project, spec, against=None):
    """Latest-active resolution per (spec, against) for the given spec."""
    records, warnings = _load_records(project)
    keys_of = lambda r: [(r.get("spec"), r.get("against"))]
    want = lambda k: k[0] == spec and (against is None or k[1] == against)
    return resolution_log.active(records, keys_of, want), warnings
```

Leave `build_context`, `build_adr_context`, `_load_principles`, `_resolutions_path`, `_cmd_resolve`, `main`, and constants untouched.

- [ ] **Step 3: Confirm the regression net is untouched and green**

```bash
git diff --stat skills/spec-manager/scripts/test_contradictions.py   # expect: no output
python skills/spec-manager/scripts/test_contradictions.py -v
```
Expected: NO diff to the test file; all 16 tests PASS.

- [ ] **Step 4: Commit**

```bash
git add skills/spec-manager/scripts/contradictions.py
git commit -m "refactor(spec-manager): contradictions.py delegates to resolution_log (G3)

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

### Task 4: Refactor `drift.py` (P4b) onto the helper

**Files:**
- Modify: `skills/spec-manager/scripts/drift.py`
- Regression net (DO NOT EDIT): `skills/spec-manager/scripts/test_drift.py`

**Interfaces:**
- Unchanged public surface: `RESOLUTIONS_RELPATH`, `VERDICTS`, `append_resolution(project, record)`, `_load_records(project)`, `active_prior(project, item, paths=None) -> (list, warnings)`, plus `build_drift_context`/`compute_impact`/`drift_gaps` (untouched).

- [ ] **Step 1: Add the import**

`drift.py` already has `sys.path.insert(...)` and sibling imports (`search_specs`, `adr`). Add to that block:
```python
import resolution_log  # noqa: E402
```

- [ ] **Step 2: Delegate the three bodies**

Replace `append_resolution`, `_load_records`, and `active_prior` with (P4b explodes over `paths`, keyed `(item, path)`):

```python
def append_resolution(project, record):
    return resolution_log.append(_resolutions_path(project), record)


def _load_records(project):
    return resolution_log.load(_resolutions_path(project), RESOLUTIONS_RELPATH)


def active_prior(project, item, paths=None):
    """Latest-active resolution per (item, path) for the given item."""
    records, warnings = _load_records(project)
    want_paths = set(paths) if paths else None
    keys_of = lambda r: [(r.get("item"), p) for p in (r.get("paths") or [])]
    want = lambda k: k[0] == item and (want_paths is None or k[1] in want_paths)
    return resolution_log.active(records, keys_of, want), warnings
```

Leave the gather (`changed_files`/`compute_impact`/`_spec_targets`/`_adr_targets`/`build_drift_context`), `drift_gaps`, `_cmd_resolve`, `main`, and constants untouched.

- [ ] **Step 3: Confirm the regression net is untouched and green**

```bash
git diff --stat skills/spec-manager/scripts/test_drift.py   # expect: no output
python skills/spec-manager/scripts/test_drift.py -v
```
Expected: NO diff to the test file; all 19 tests PASS.

- [ ] **Step 4: Full governance sweep**

All suites must pass, and the three refactored modules must no longer contain their own latest-wins loop:
```bash
for t in resolution_log principles contradictions drift frontmatter adr intent verify_intent verify_links; do
  python skills/spec-manager/scripts/test_$t.py >/dev/null 2>&1 && echo "$t OK" || echo "$t FAIL"
done
# duplication gone: each should print 0 (no local latest-wins loop remains)
for m in principles contradictions drift; do
  echo -n "$m latest-loop lines: "; grep -c 'latest\[' skills/spec-manager/scripts/$m.py
done
```
Expected: all suites `OK`; each module prints `0` for `latest[` occurrences.

- [ ] **Step 5: Commit**

```bash
git add skills/spec-manager/scripts/drift.py
git commit -m "refactor(spec-manager): drift.py delegates to resolution_log (P4b)

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

## Post-plan: final review + parking-lot

After Task 4:
1. **Final whole-branch review** — dispatch the code-reviewer on the full refactor range (base = the spec commit, HEAD) on the most capable model, focused on: behavior preservation (existing suites byte-unchanged + green), the two `keys_of` shapes correctly reproduce G2/P4b (exploding) and G3 (single-key) semantics, no schema/RELPATH/CLI drift, and that the duplication is genuinely removed.
2. Update the parking-lot "Shared resolution-log helper (refactor)" entry → **delivered**, with a pointer to this spec.
3. Record completion in the SDD ledger; do **not** merge `feat/behavior-layer` (standing decision).
