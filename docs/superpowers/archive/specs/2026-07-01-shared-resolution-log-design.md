# Shared resolution-log helper (refactor) — design

**Status:** Draft for review
**Date:** 2026-07-01
**Type:** Behavior-preserving refactor (no new capability, no public-API change).
**Motivation:** Governance sub-projects G2 (`principles.py`), G3 (`contradictions.py`), and P4b (`drift.py`) each carry a near-verbatim copy of the append-only resolution-log logic (`append_resolution` / `_load_records` / `active_prior`). This was a deliberate, spec-approved decision at 2 copies (G3: "we deliberately did not extract a shared module, to avoid churning G2's shipped code"). At 3 copies the DRY case wins; parking-lot logged it as its own refactor sub-project. This is that sub-project.
**Depends on:** the three shipped modules and their test suites (the regression net). No functional dependency.

---

## 1. Goal

Extract the duplicated resolution-log logic into one `resolution_log.py`, and refactor all three governance modules to delegate to it — **without changing any public API, CLI, record schema, RELPATH, or observable behavior.** Success = the three existing suites pass **unchanged**, plus a new focused suite for the helper.

## 2. The duplication, precisely (two variants, not one)

- **`append_resolution(project, record)`** and **`_load_records(project)`** are **verbatim** across all three — only the module's `RESOLUTIONS_RELPATH` differs.
- **`active_prior`** has two shapes:
  - **G2 `principles.py`** (`active_prior(project, paths=None, principle=None)`) and **P4b `drift.py`** (`active_prior(project, item, paths=None)`): **explode** a record over its `paths`, key `(field, path)` where `field` is `principle` / `item`.
  - **G3 `contradictions.py`** (`active_prior(project, spec, against=None)`): **single** `against` per record (no explosion), key `(spec, against)`.

All three share the same core algorithm: *keep the latest (append-order) record per key, drop keys whose latest verdict is `superseded`, filter to the caller's query, de-dupe a multi-key record to one entry by append index, and thread `(records, warnings)`.*

## 3. Design — `resolution_log.py`

A small stdlib module with three functions (no class — matches the codebase style):

```python
def append(path, record):
    """Append one JSONL line (sorted keys) to `path`, creating parents. Returns str(path)."""

def load(path):
    """(records, warnings) — parsed JSONL lines in append order; a malformed line
    is skipped with a warning naming the line number. Missing file → ([], [])."""

def active(records, keys_of, want=None):
    """Latest-active records, given:
      keys_of(record) -> iterable of hashable keys the record covers
                         (exploded over paths, or a single (a, b) tuple);
      want(key) -> bool, the caller's query filter (default: keep all).
    Keeps the LAST record per key, drops keys whose latest verdict is `superseded`,
    applies `want`, and returns the surviving records de-duped in append order."""
```

`active` is the exact current algorithm, parameterized:
```python
def active(records, keys_of, want=None):
    latest = {}
    for idx, rec in enumerate(records):
        for k in keys_of(rec):
            latest[k] = (idx, rec)
    picked = {}
    for k, (idx, rec) in latest.items():
        if rec.get("verdict") == "superseded":
            continue
        if want is not None and not want(k):
            continue
        picked[idx] = rec
    return [picked[i] for i in sorted(picked)]
```

## 4. Delegation — preserve every public surface

Each module keeps its module-level constants (`RESOLUTIONS_RELPATH`, `VERDICTS`), its path helper, and the **exact signatures** of `append_resolution` / `active_prior` (and `_cmd_resolve`, the CLI, and record schemas). Only the bodies change:

- **`append_resolution(project, record)`** → `return resolution_log.append(_resolutions_path(project), record)`.
- **`_load_records(project)`** → `return resolution_log.load(_resolutions_path(project))` (or inline the call at the two `active_prior` sites and drop `_load_records` if it has no other caller — decided per module, keeping whatever is externally referenced).
- **`active_prior(...)`** → build the module's `keys_of` + `want` closures and delegate:

  **G2** (`active_prior(project, paths=None, principle=None)`):
  ```python
  records, warnings = resolution_log.load(_resolutions_path(project))
  keys_of = lambda r: [(r.get("principle"), p) for p in (r.get("paths") or [])]
  want = lambda k: (paths is None or k[1] in set(paths)) and (principle is None or k[0] == principle)
  return resolution_log.active(records, keys_of, want), warnings
  ```
  **P4b** (`active_prior(project, item, paths=None)`): same, with `item` in place of `principle` and `k[0] == item` always required.

  **G3** (`active_prior(project, spec, against=None)`):
  ```python
  records, warnings = resolution_log.load(_resolutions_path(project))
  keys_of = lambda r: [(r.get("spec"), r.get("against"))]
  want = lambda k: k[0] == spec and (against is None or k[1] == against)
  return resolution_log.active(records, keys_of, want), warnings
  ```

Import style matches the siblings: `sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))` then `import resolution_log` (or `from resolution_log import append, load, active`).

## 5. Safety & testing

- **The three existing suites are the regression net** — they must pass **unchanged** (no edits to `test_principles.py` / `test_contradictions.py` / `test_drift.py`). Any needed edit there is a signal the refactor changed behavior — stop and fix the refactor, not the test.
- **New `test_resolution_log.py`** covers the core directly: `append` is append-only; `load` skips a malformed line with a warning and returns `([],[])` on a missing file; `active` with a path-exploding `keys_of` does latest-wins per `(field,path)`, drops `superseded`, de-dupes a multi-path record, and honors `want`; `active` with a single-key `keys_of` (the G3 shape) does latest-wins per `(a,b)` and honors `want`.
- **Full sweep** after each module refactor: all governance suites green.

## 6. Scope

**In scope:** `resolution_log.py` (`append`/`load`/`active`); refactor `principles.py`, `contradictions.py`, `drift.py` to delegate while preserving their public APIs, CLIs, record schemas, RELPATHs, and `VERDICTS`; `test_resolution_log.py`.

**Out of scope:** any change to record schemas, keys, verdicts, CLI flags, or SKILL docs (nothing about the resolution logs changes from a user's view); unifying the three `active_prior` *signatures* (they stay module-specific — callers depend on them); touching the resolution *judgment/triage* prose in the SKILLs; the security findings log (a different shape, not part of this pattern).

## 7. Acceptance criteria

- [ ] `resolution_log.py` exposes `append(path, record)`, `load(path)->(records,warnings)`, `active(records, keys_of, want=None)->list` with the exact algorithm of §3.
- [ ] `principles.py`, `contradictions.py`, `drift.py` delegate to it; their `append_resolution`/`active_prior` public signatures, `RESOLUTIONS_RELPATH`, `VERDICTS`, record schemas, and CLIs are unchanged.
- [ ] `test_principles.py` (11), `test_contradictions.py` (16), `test_drift.py` (19) all pass **with no edits**.
- [ ] `test_resolution_log.py` covers both `keys_of` shapes (path-exploding and single-key), append-only, malformed-skip, missing-file, and `want` filtering.
- [ ] Full governance sweep green (resolution_log + the three + frontmatter/adr/intent/verify_intent/verify_links).
- [ ] The three modules no longer contain their own copy of the latest-wins/superseded/dedupe loop (the duplication is gone).

## 8. Open questions

None. The refactor is bounded by "existing suites pass unchanged," which mechanically guarantees behavior preservation; the only new surface is the helper and its own tests.
