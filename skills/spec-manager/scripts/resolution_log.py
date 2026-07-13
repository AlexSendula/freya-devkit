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
