# P4a — ADR support + ADR-aware conflict checks Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Give cross-cutting ADRs a real format + authoring/gather/integrity tooling, and make the G3 contradiction check ADR-aware (a changed spec vs all active ADRs; a changed ADR vs its principles).

**Architecture:** New `adr.py` mirrors `intent.py` (authoring) + adds a gather + deterministic integrity. `frontmatter.py` gains an `ADR_SCHEMA`. `contradictions.py` `build_context` gains `adrs` (always-global — all active ADRs, no category scoping) and a new `build_adr_context`. Resolution reuses the existing `contradiction-resolutions.jsonl` unchanged (`ADR-NNN` rides the free-form `(spec, against)` keying). SKILL wiring in spec-manager + wrap-up; design-doc updates.

**Tech Stack:** Python 3.12 stdlib only (`unittest`, `argparse`, `re`, `json`, `pathlib`). Markdown skill/reference docs.

## Global Constraints

- **Stdlib-only Python** — zero third-party imports (the plugin is zero-install).
- **Test framework:** stdlib `unittest`; each test file does `sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))` then imports siblings; ends with `unittest.main(verbosity=2)`; run via `python skills/spec-manager/scripts/test_<name>.py`.
- **Always-global comparison** — G3 compares against *all active ADRs*; **no category/tag/`applies_to` scoping** (design §2). Only lifecycle filters: `active` = `status == "accepted"`.
- **Authority order:** principle > ADR > spec. spec-vs-ADR → default *fix the spec*; ADR-vs-principle → default *fix the ADR*; peer → *reconcile* (design §5.3).
- **No JSONL schema change, no new resolution module** — reuse `contradictions.resolve`/`prior`; `ADR-NNN` is a valid `--spec`/`--against` value.
- **No silent drops** — a malformed ADR is a **surfaced warning**, never silently excluded from what the agent sees; deterministic `adr verify` hard-blocks on it.
- **Path prefix:** all scripts under `skills/spec-manager/scripts/`. Data under a project's `knowledge-base/decisions/`.
- **Branch:** work continues on `feat/behavior-layer` (do NOT merge). Dogfood on the testbed only; production webapp off-limits.
- **Commits** end with: `Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>`.

---

## File Structure

- **Create** `skills/spec-manager/scripts/adr.py` — authoring (`new`), gather (`load_adrs`/`active_adrs`), integrity (`verify_adrs`), index (`render_index`), CLI.
- **Create** `skills/spec-manager/scripts/test_adr.py` — proof suite.
- **Modify** `skills/spec-manager/scripts/frontmatter.py` — add `ADR_STATES`, `ADR_SCHEMA`, `validate_adr`.
- **Modify** `skills/spec-manager/scripts/test_frontmatter.py` — ADR schema tests.
- **Modify** `skills/spec-manager/scripts/contradictions.py` — `build_context` gains `adrs`/`adr_warnings`; add `build_adr_context` + `adr-context` CLI.
- **Modify** `skills/spec-manager/scripts/test_contradictions.py` — ADR context tests.
- **Create** `skills/spec-manager/references/adr-template.md` — ADR format doc.
- **Modify** `skills/spec-manager/references/decisions-readme.md` — remove "no tooling reads them yet".
- **Modify** `skills/spec-manager/SKILL.md` — `adr create`/`list`/`verify`; init scaffolding; G3 procedure ADR-aware.
- **Modify** `skills/wrap-up/SKILL.md` — `adr verify` in step 1; ADRs + changed `decisions/**` in step 6; staging.
- **Modify** `docs/design/behavior-layer/00-vision.md` + `docs/design/behavior-layer/parking-lot.md` — mark ADR-awareness delivered.

---

### Task 1: `ADR_SCHEMA` + `validate_adr` in frontmatter.py

**Files:**
- Modify: `skills/spec-manager/scripts/frontmatter.py` (add after `SPEC_SCHEMA`, ~line 58)
- Test: `skills/spec-manager/scripts/test_frontmatter.py`

**Interfaces:**
- Produces: `ADR_STATES: tuple`, `ADR_SCHEMA: dict`, `validate_adr(frontmatter: dict) -> list[str]` (empty == valid).

- [ ] **Step 1: Write the failing tests**

Add to `skills/spec-manager/scripts/test_frontmatter.py`. First ensure the import line pulls the new names (add `validate_adr, ADR_STATES` to the existing `from frontmatter import ...`):

```python
class ADRSchemaCase(unittest.TestCase):
    def test_accepts_well_formed_adr(self):
        fm = {"id": "ADR-001", "title": "Use Postgres", "status": "accepted",
              "tags": ["database"], "related_code": ["prisma/schema.prisma"]}
        self.assertEqual(validate_adr(fm), [])

    def test_rejects_bad_status(self):
        errs = validate_adr({"id": "ADR-001", "title": "X", "status": "bogus"})
        self.assertTrue(any("status" in e for e in errs))

    def test_requires_title(self):
        errs = validate_adr({"id": "ADR-001", "status": "accepted"})
        self.assertTrue(any("title" in e for e in errs))

    def test_optional_tags_must_be_list(self):
        errs = validate_adr({"id": "ADR-001", "title": "X", "status": "accepted",
                             "tags": "nope"})
        self.assertTrue(any("tags" in e for e in errs))

    def test_all_states_valid(self):
        for s in ADR_STATES:
            self.assertEqual(
                validate_adr({"id": "ADR-001", "title": "X", "status": s}), [])
```

- [ ] **Step 2: Run to verify it fails**

Run: `python skills/spec-manager/scripts/test_frontmatter.py -v`
Expected: FAIL / ERROR — `ImportError: cannot import name 'validate_adr'`.

- [ ] **Step 3: Implement**

In `frontmatter.py`, after the `SPEC_SCHEMA` block (before `class FrontmatterError`), add:

```python
# ADR frontmatter schema (P4a). ADRs are cross-cutting decision records; lifecycle
# mirrors behaviors — only `accepted` is authoritative. Unknown fields preserved.
ADR_STATES = ("proposed", "accepted", "superseded", "deprecated")

ADR_SCHEMA = {
    "required": {
        "id": str,
        "title": str,
        "status": str,
    },
    "optional": {
        "created": str,
        "updated": str,
        "tags": list,
        "supersedes": str,
        "superseded_by": str,
        "related_code": list,
    },
}
```

Then add this function at the end of the file (after `validate`):

```python
def validate_adr(frontmatter: dict) -> list:
    """Validate ADR frontmatter against ADR_SCHEMA + the closed status set.

    Returns a list of human-readable errors (empty == valid). Reuses `validate`
    for required/optional typing, then adds the ADR `status` enum check.
    """
    errors = validate(frontmatter, schema=ADR_SCHEMA)
    status = frontmatter.get("status")
    if status is not None and status not in ADR_STATES:
        errors.append(f"status '{status}' must be one of {', '.join(ADR_STATES)}")
    return errors
```

- [ ] **Step 4: Run to verify it passes**

Run: `python skills/spec-manager/scripts/test_frontmatter.py -v`
Expected: PASS (all existing + new ADR tests).

- [ ] **Step 5: Commit**

```bash
git add skills/spec-manager/scripts/frontmatter.py skills/spec-manager/scripts/test_frontmatter.py
git commit -m "feat(spec-manager): ADR_SCHEMA + validate_adr (P4a)

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

### Task 2: `adr.py` authoring — id allocation, render, `new`

**Files:**
- Create: `skills/spec-manager/scripts/adr.py`
- Test: `skills/spec-manager/scripts/test_adr.py`

**Interfaces:**
- Consumes: `frontmatter.parse_frontmatter`, `validate_adr`, `FrontmatterError`, `ADR_STATES` (Task 1).
- Produces: `DECISIONS_RELDIR`, `_decisions_dir(project)`, `_next_id(dir)->str`, `_slug(title)->str`, `render_record(adr_id,title,status,day,tags=None,supersedes=None)->str`, `new_record(project,title,status,day,tags=None,supersedes=None)->str` (path). CLI `adr new`.

- [ ] **Step 1: Write the failing tests**

Create `skills/spec-manager/scripts/test_adr.py`:

```python
#!/usr/bin/env python3
"""Proof suite for adr.py — the ADR authoring/gather/integrity helpers (P4a)."""

import os
import shutil
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from adr import _next_id, new_record, render_record  # noqa: E402
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
        self.assertTrue(path.endswith("knowledge-base/decisions/ADR-001-use-postgres.md"))
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


if __name__ == "__main__":
    unittest.main(verbosity=2)
```

- [ ] **Step 2: Run to verify it fails**

Run: `python skills/spec-manager/scripts/test_adr.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'adr'`.

- [ ] **Step 3: Implement**

Create `skills/spec-manager/scripts/adr.py`:

```python
#!/usr/bin/env python3
"""Authoring + gather + integrity helpers for ADRs (governance P4a).

- `adr new`  : allocate the next ADR-NNN and write a four-section scaffold.
- `load_adrs`/`active_adrs` : gather ADRs for the G3 contradiction check. A
   malformed ADR becomes a SURFACED WARNING, never a silent drop.
- `adr verify` : deterministic Tier-1 integrity (dup id, dangling supersede
   links, bad status/malformed) — hard-blocks at wrap-up.
- `adr list` : print/regenerate the decisions index.

Cross-cutting ADRs are compared ALWAYS-GLOBAL (no category scoping): see
docs/superpowers/specs/2026-07-01-p4a-adr-support-design.md §2. Only lifecycle
filters — `active_adrs` keeps `status == "accepted"`.
"""

import argparse
import json
import os
import re
import sys
from datetime import date as _date
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from frontmatter import (  # noqa: E402
    parse_frontmatter, validate_adr, FrontmatterError, ADR_STATES,
)

DECISIONS_RELDIR = "knowledge-base/decisions"
_ID_RE = re.compile(r"ADR-(\d+)")
_SECTIONS = ("Decision", "Rationale", "Rejected Alternatives", "Revisit Conditions")


def _decisions_dir(project):
    return Path(project) / DECISIONS_RELDIR


def _next_id(decisions_dir: Path) -> str:
    n = 0
    if decisions_dir.exists():
        for f in decisions_dir.glob("ADR-*.md"):
            m = _ID_RE.search(f.name)
            if m:
                n = max(n, int(m.group(1)))
    return f"ADR-{n + 1:03d}"


def _slug(title: str) -> str:
    s = re.sub(r"[^a-z0-9]+", "-", title.lower()).strip("-")
    return s or "decision"


def render_record(adr_id, title, status, day, tags=None, supersedes=None) -> str:
    fm = ["---", f"id: {adr_id}", f"title: {title}", f"status: {status}",
          f"created: {day}", f"updated: {day}"]
    if tags:
        fm.append("tags:")
        fm += [f"  - {t}" for t in tags]
    if supersedes:
        fm.append(f"supersedes: {supersedes}")
    fm.append("---")
    body = [f"# {adr_id}: {title}"]
    for sec in _SECTIONS:
        body.append(f"## {sec}")
        body.append(f"TODO: {sec.lower()}.")
    return "\n".join(fm) + "\n" + "\n".join(body) + "\n"


def new_record(project, title, status, day, tags=None, supersedes=None) -> str:
    ddir = _decisions_dir(project)
    ddir.mkdir(parents=True, exist_ok=True)
    adr_id = _next_id(ddir)
    path = ddir / f"{adr_id}-{_slug(title)}.md"
    path.write_text(render_record(adr_id, title, status, day, tags, supersedes),
                    encoding="utf-8")
    return str(path)


def _status(value):
    if value not in ADR_STATES:
        raise argparse.ArgumentTypeError(
            f"--status must be one of {', '.join(ADR_STATES)}, got {value!r}")
    return value


def main():
    parser = argparse.ArgumentParser(description="ADR helpers (P4a)")
    sub = parser.add_subparsers(dest="cmd", required=True)

    n = sub.add_parser("new", help="Create a new ADR-NNN scaffold")
    n.add_argument("--title", "-t", required=True)
    n.add_argument("--status", default="accepted", type=_status)
    n.add_argument("--tag", action="append", dest="tags")
    n.add_argument("--supersedes")
    n.add_argument("--date", dest="day", default=None)
    n.add_argument("--project", "-p", default=".")

    args = parser.parse_args()
    if args.cmd == "new":
        day = args.day or _date.today().isoformat()
        print(new_record(args.project, args.title, args.status, day,
                         args.tags, args.supersedes))


if __name__ == "__main__":
    main()
```

- [ ] **Step 4: Run to verify it passes**

Run: `python skills/spec-manager/scripts/test_adr.py -v`
Expected: PASS (5 tests).

- [ ] **Step 5: Commit**

```bash
git add skills/spec-manager/scripts/adr.py skills/spec-manager/scripts/test_adr.py
git commit -m "feat(spec-manager): adr.py authoring — id alloc + scaffold (P4a)

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

### Task 3: `adr.py` gather — `load_adrs` / `active_adrs`

**Files:**
- Modify: `skills/spec-manager/scripts/adr.py`
- Test: `skills/spec-manager/scripts/test_adr.py`

**Interfaces:**
- Produces: `load_adrs(project) -> (list[dict], list[str])` where each dict is `{id,title,status,tags,related_code,supersedes,superseded_by,body,path}`; `active_adrs(project) -> (list[dict], list[str])` (filters `status == "accepted"`). A malformed ADR → a warning string, excluded from the list but never silent.

- [ ] **Step 1: Write the failing tests**

Add to `test_adr.py`. First extend the import: `from adr import _next_id, new_record, render_record, load_adrs, active_adrs`. Then add a writer helper + case:

```python
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
```

- [ ] **Step 2: Run to verify it fails**

Run: `python skills/spec-manager/scripts/test_adr.py -v`
Expected: FAIL — `ImportError: cannot import name 'load_adrs'`.

- [ ] **Step 3: Implement**

In `adr.py`, add after `new_record` (before `_status`):

```python
def load_adrs(project):
    """Return (adrs, warnings). Each adr is a dict with id/title/status/tags/
    related_code/supersedes/superseded_by/body/path. A malformed ADR is a
    surfaced warning and excluded — never a SILENT drop (design §2, §7)."""
    ddir = _decisions_dir(project)
    adrs, warnings = [], []
    if not ddir.exists():
        return adrs, warnings
    for f in sorted(ddir.glob("ADR-*.md")):
        try:
            fm, body = parse_frontmatter(
                f.read_text(encoding="utf-8", errors="replace"))
        except FrontmatterError as e:
            warnings.append(f"unparseable ADR {f.name}: {e}")
            continue
        errs = validate_adr(fm)
        if errs:
            warnings.append(f"invalid ADR {f.name}: {'; '.join(errs)}")
            continue
        adrs.append({
            "id": fm.get("id"), "title": fm.get("title"), "status": fm.get("status"),
            "tags": fm.get("tags", []), "related_code": fm.get("related_code", []),
            "supersedes": fm.get("supersedes"), "superseded_by": fm.get("superseded_by"),
            "body": body.strip(), "path": str(f),
        })
    return adrs, warnings


def active_adrs(project):
    """(accepted ADRs, warnings) — the authoritative set G3 compares against."""
    adrs, warnings = load_adrs(project)
    return [a for a in adrs if a["status"] == "accepted"], warnings
```

- [ ] **Step 4: Run to verify it passes**

Run: `python skills/spec-manager/scripts/test_adr.py -v`
Expected: PASS (9 tests).

- [ ] **Step 5: Commit**

```bash
git add skills/spec-manager/scripts/adr.py skills/spec-manager/scripts/test_adr.py
git commit -m "feat(spec-manager): adr.py gather — load_adrs/active_adrs (P4a)

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

### Task 4: `adr.py` integrity + index — `verify` / `list`

**Files:**
- Modify: `skills/spec-manager/scripts/adr.py`
- Test: `skills/spec-manager/scripts/test_adr.py`

**Interfaces:**
- Produces: `verify_adrs(project) -> list[str]` (errors; empty == clean); `render_index(project) -> str`. CLI subcommands `adr verify` (exit 1 on any error) and `adr list [--format table|json]`.

- [ ] **Step 1: Write the failing tests**

Add to `test_adr.py`. Extend import: `from adr import ..., verify_adrs, render_index`. Reuse `_write_adr`:

```python
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

    def test_list_renders_table(self):
        root = self._root()
        _write_adr(root, "ADR-001", title="Use Postgres")
        out = render_index(str(root))
        self.assertIn("ADR-001", out)
        self.assertIn("Use Postgres", out)
```

- [ ] **Step 2: Run to verify it fails**

Run: `python skills/spec-manager/scripts/test_adr.py -v`
Expected: FAIL — `ImportError: cannot import name 'verify_adrs'`.

- [ ] **Step 3: Implement**

In `adr.py`, add after `active_adrs`:

```python
def verify_adrs(project):
    """Deterministic Tier-1 integrity — (errors); empty == clean. Flags:
    duplicate id, malformed/invalid frontmatter, and a supersedes/superseded_by
    that does not resolve to a known ADR id. Hard-blocks at wrap-up."""
    ddir = _decisions_dir(project)
    errors = []
    if not ddir.exists():
        return errors
    ids, raw = {}, []
    for f in sorted(ddir.glob("ADR-*.md")):
        try:
            fm, _ = parse_frontmatter(
                f.read_text(encoding="utf-8", errors="replace"))
        except FrontmatterError as e:
            errors.append(f"{f.name}: unparseable frontmatter: {e}")
            continue
        for e in validate_adr(fm):
            errors.append(f"{f.name}: {e}")
        aid = fm.get("id")
        if aid:
            if aid in ids:
                errors.append(f"{f.name}: duplicate id {aid} (also in {ids[aid]})")
            else:
                ids[aid] = f.name
        raw.append((f.name, fm))
    known = set(ids)
    for fname, fm in raw:
        for field in ("supersedes", "superseded_by"):
            ref = fm.get(field)
            if ref and ref not in known:
                errors.append(
                    f"{fname}: {field} '{ref}' does not resolve to a known ADR")
    return errors


def render_index(project):
    """Regenerate the decisions index as a markdown table."""
    adrs, _ = load_adrs(project)
    lines = ["# Architecture Decision Records", "",
             "| ID | Title | Status |", "|----|-------|--------|"]
    for a in sorted(adrs, key=lambda x: x["id"] or ""):
        lines.append(f"| {a['id']} | {a['title']} | {a['status']} |")
    return "\n".join(lines) + "\n"
```

Then extend `main()` — add these two subparsers before `args = parser.parse_args()`:

```python
    v = sub.add_parser("verify", help="Deterministic ADR integrity checks")
    v.add_argument("--project", "-p", default=".")

    ls = sub.add_parser("list", help="Print the ADR index")
    ls.add_argument("--project", "-p", default=".")
    ls.add_argument("--format", "-f", choices=["table", "json"], default="table")
```

and add these branches after the `if args.cmd == "new":` block:

```python
    elif args.cmd == "verify":
        errs = verify_adrs(args.project)
        for e in errs:
            print(e, file=sys.stderr)
        sys.exit(1 if errs else 0)
    elif args.cmd == "list":
        if args.format == "json":
            adrs, _ = load_adrs(args.project)
            print(json.dumps(adrs, indent=2))
        else:
            print(render_index(args.project))
```

- [ ] **Step 4: Run to verify it passes**

Run: `python skills/spec-manager/scripts/test_adr.py -v`
Expected: PASS (14 tests). Also confirm the CLI: `python skills/spec-manager/scripts/adr.py verify -p /tmp/nonexistent` exits 0 (no decisions dir → clean).

- [ ] **Step 5: Commit**

```bash
git add skills/spec-manager/scripts/adr.py skills/spec-manager/scripts/test_adr.py
git commit -m "feat(spec-manager): adr.py integrity + index — verify/list (P4a)

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

### Task 5: G3 `build_context` gains `adrs` (always-global)

**Files:**
- Modify: `skills/spec-manager/scripts/contradictions.py`
- Test: `skills/spec-manager/scripts/test_contradictions.py`

**Interfaces:**
- Consumes: `adr.active_adrs` (Task 3).
- Produces: `build_context` return dict gains `"adrs": [{id,title,body}…]` (active only) and `"adr_warnings": [...]`, in both the found and not-found branches.

- [ ] **Step 1: Write the failing tests**

Add to `test_contradictions.py`. Add an ADR writer helper near `_spec` and a case:

```python
def _adr(root, adr_id, status="accepted", title="T", body="We do X."):
    d = root / "knowledge-base/decisions"
    d.mkdir(parents=True, exist_ok=True)
    (d / f"{adr_id}-x.md").write_text(
        f"---\nid: {adr_id}\ntitle: {title}\nstatus: {status}\n---\n"
        f"# {adr_id}\n## Decision\n{body}\n", encoding="utf-8")


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
```

- [ ] **Step 2: Run to verify it fails**

Run: `python skills/spec-manager/scripts/test_contradictions.py -v`
Expected: FAIL — `KeyError: 'adrs'`.

- [ ] **Step 3: Implement**

In `contradictions.py`, add to the sibling import block (after the `principles` import). `active_adrs` is the only name imported from `adr` — `build_adr_context` is defined locally in Task 6, not imported:

```python
from adr import active_adrs  # noqa: E402
```

Replace `build_context` with:

```python
def build_context(project, spec_id):
    """Assemble {spec, category, principles, adrs, peers, adr_warnings} for a
    changed spec. `adrs` = ALL active ADRs (always-global, no scoping — design
    §2). `peers` = same-category specs (excluding self) with intentional_decisions.
    """
    specs = load_all_specs(find_specs_dir(project))
    principles = _load_principles(project)
    adrs, adr_warnings = active_adrs(project)
    adr_ctx = [{"id": a["id"], "title": a["title"], "body": a["body"]} for a in adrs]
    target = next((s for s in specs if s.id == spec_id), None)
    if target is None:
        return {"spec": spec_id, "category": None, "principles": principles,
                "adrs": adr_ctx, "peers": [], "adr_warnings": adr_warnings,
                "note": f"spec {spec_id} not found"}
    peers = [
        {"spec_id": s.id, "decisions": s.intentional_decisions}
        for s in specs
        if s.category == target.category and s.id != spec_id and s.intentional_decisions
    ]
    return {"spec": spec_id, "category": target.category,
            "principles": principles, "adrs": adr_ctx, "peers": peers,
            "adr_warnings": adr_warnings}
```

- [ ] **Step 4: Run to verify it passes**

Run: `python skills/spec-manager/scripts/test_contradictions.py -v`
Expected: PASS (existing context/resolution tests + 3 new ADR-context tests).

- [ ] **Step 5: Commit**

```bash
git add skills/spec-manager/scripts/contradictions.py skills/spec-manager/scripts/test_contradictions.py
git commit -m "feat(spec-manager): G3 build_context includes active ADRs (P4a)

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

### Task 6: `build_adr_context` (changed-ADR symmetry) + `adr-context` CLI

**Files:**
- Modify: `skills/spec-manager/scripts/contradictions.py`
- Test: `skills/spec-manager/scripts/test_contradictions.py`

**Interfaces:**
- Produces: `build_adr_context(project, adr_id) -> {adr, principles, peer_adrs, adr_warnings, [note]}` (`peer_adrs` = other active ADRs); CLI `contradictions.py adr-context --adr ADR-NNN`.

- [ ] **Step 1: Write the failing tests**

Add to `test_contradictions.py` (reuse `_adr` from Task 5). Extend the import: `from contradictions import (build_context, build_adr_context, append_resolution, active_prior, RESOLUTIONS_RELPATH,)`.

```python
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
```

- [ ] **Step 2: Run to verify it fails**

Run: `python skills/spec-manager/scripts/test_contradictions.py -v`
Expected: FAIL — `ImportError: cannot import name 'build_adr_context'`.

- [ ] **Step 3: Implement**

In `contradictions.py`, add after `build_context`:

```python
def build_adr_context(project, adr_id):
    """Assemble {adr, principles, peer_adrs, adr_warnings} for a CHANGED ADR.

    A changed ADR is judged against the principles above it (authority:
    principle > ADR) and its peer ADRs at the same tier (reconcile). `peer_adrs`
    excludes the changed ADR. Returns a `note` if the ADR isn't found/active.
    """
    adrs, adr_warnings = active_adrs(project)
    principles = _load_principles(project)
    target = next((a for a in adrs if a["id"] == adr_id), None)
    if target is None:
        return {"adr": adr_id, "principles": principles, "peer_adrs": [],
                "adr_warnings": adr_warnings,
                "note": f"ADR {adr_id} not found or not accepted"}
    peers = [{"id": a["id"], "title": a["title"], "body": a["body"]}
             for a in adrs if a["id"] != adr_id]
    return {"adr": {"id": target["id"], "title": target["title"],
                    "body": target["body"]},
            "principles": principles, "peer_adrs": peers,
            "adr_warnings": adr_warnings}
```

Then wire the CLI. Add a subparser in `main()` after the `context` parser:

```python
    ac = sub.add_parser("adr-context", help="Comparison set for a changed ADR")
    ac.add_argument("--project", "-p", default=".")
    ac.add_argument("--adr", required=True)
```

and a branch after the `if args.cmd == "context":` block:

```python
    elif args.cmd == "adr-context":
        print(json.dumps(build_adr_context(args.project, args.adr), indent=2))
```

- [ ] **Step 4: Run to verify it passes**

Run: `python skills/spec-manager/scripts/test_contradictions.py -v`
Expected: PASS (all prior + 2 new).

- [ ] **Step 5: Full-suite regression**

Run each suite; all must pass:
```bash
for t in frontmatter adr contradictions principles intent verify_intent verify_links; do
  python skills/spec-manager/scripts/test_$t.py >/dev/null 2>&1 && echo "$t OK" || echo "$t FAIL"
done
```
Expected: all `OK`.

- [ ] **Step 6: Commit**

```bash
git add skills/spec-manager/scripts/contradictions.py skills/spec-manager/scripts/test_contradictions.py
git commit -m "feat(spec-manager): build_adr_context — changed-ADR symmetry (P4a)

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

### Task 7: spec-manager SKILL.md + adr-template.md + decisions-readme.md

**Files:**
- Create: `skills/spec-manager/references/adr-template.md`
- Modify: `skills/spec-manager/references/decisions-readme.md`
- Modify: `skills/spec-manager/SKILL.md`

No unit test (documentation). Deliverable: the commands, the format doc, and the ADR-aware G3 procedure are documented and internally consistent with the scripts from Tasks 1–6.

- [ ] **Step 1: Create `adr-template.md`**

Create `skills/spec-manager/references/adr-template.md` mirroring `spec-template.md`: show the frontmatter (`id`, `title`, `status` [proposed|accepted|superseded|deprecated], `created`, `updated`, optional `tags`/`supersedes`/`superseded_by`/`related_code`) and the four body sections (Decision, Rationale, Rejected Alternatives, Revisit Conditions). Include a "Frontmatter Fields" table and a note: **only `accepted` ADRs are authoritative / compared by G3; ADRs are compared always-global (no category scoping); `tags`/`related_code` are human-navigation/P4b metadata, not G3 filters.**

- [ ] **Step 2: Rewrite the `decisions-readme.md` status note**

In `skills/spec-manager/references/decisions-readme.md`, replace the blockquote that begins "**Status:** this is an empty, git-tracked home…" with a note that ADR tooling now exists: `adr create`/`list`/`verify` (spec-manager), the `ADR-NNN` format (see `adr-template.md`), and that **accepted** ADRs are compared by the governance contradiction check (G3). Keep the "feature-local decisions belong in the spec, not here" paragraph.

- [ ] **Step 3: Update SKILL.md — Quick Reference + commands**

In `skills/spec-manager/SKILL.md`:
- Add to the Quick Reference table: `adr create <name>` (Create a cross-cutting ADR), `adr list` (Print the ADR index), `adr verify` (Deterministic ADR integrity).
- Add an **`init`** bullet: also scaffold `decisions/README.md` via `python .../adr.py list` and reference `adr-template.md` (replacing the old "ADR machinery arrives in a later phase" wording in the init section).
- Add a new command section **`### /freya-devkit:spec-manager adr create <name>`** describing the interactive flow (ask decision / rationale / rejected alternatives / revisit conditions / optional tags / supersedes → call `python .../adr.py new --title … --status accepted` → fill the body → regenerate the index with `adr list`). Document `adr list` and `adr verify` invocations with the full `python "…/adr.py"` command paths (mirror the existing `verify_links.py` invocation style).

- [ ] **Step 4: Update SKILL.md — the G3 contradiction procedure**

Find the existing "Contradiction Check (governance G3)" procedure section. Update it so the comparison set and semantics include ADRs:
- `contradictions.py context --spec <ID>` now also returns `adrs` (all active) and `adr_warnings` — the agent judges the changed spec against principles, **each active ADR**, and same-category peers. **Surface `adr_warnings`** (a malformed ADR must not silently vanish).
- Add the authority/resolution table (design §5.3): spec-vs-ADR → **fix the spec** (ADR outranks); spec-vs-peer → reconcile. `--against ADR-NNN` records the resolution (no schema change).
- Add the **changed-ADR** path: for an ADR created/changed this cycle, run `contradictions.py adr-context --adr <ADR-NNN>` and judge it against principles (→ **fix the ADR**) and peer ADRs (→ reconcile); record with `--spec ADR-NNN --against principle:N|ADR-MMM`.
- State the always-global rationale in one line (no category scoping; recall over precision; the LLM filters).

- [ ] **Step 5: Consistency check (no test framework — read for correctness)**

Verify every command path, flag, and field named in SKILL.md matches Tasks 1–6 exactly (`--title`, `--status`, `--tag`, `--supersedes`, `--project`; `context`/`adr-context`/`resolve`/`prior`; the `adrs`/`adr_warnings`/`peer_adrs` keys). Fix any drift.

- [ ] **Step 6: Commit**

```bash
git add skills/spec-manager/SKILL.md skills/spec-manager/references/adr-template.md skills/spec-manager/references/decisions-readme.md
git commit -m "docs(spec-manager): ADR commands + ADR-aware G3 procedure (P4a)

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

### Task 8: wrap-up SKILL.md — ADR integrity + ADR-aware step 6

**Files:**
- Modify: `skills/wrap-up/SKILL.md`

Deliverable: wrap-up Phase 3.5 runs `adr verify` as a deterministic hard-block, step 6 covers ADRs and changed `decisions/**`, and ADR files stage as artifacts.

- [ ] **Step 1: Add `adr verify` to the deterministic hard-block (Phase 3.5 step 1)**

In `skills/wrap-up/SKILL.md` Phase 3.5, step 1 (deterministic link integrity), add a sibling command after `verify_links.py`:
```bash
python "…/skills/spec-manager/scripts/adr.py" verify --project .
```
State a non-zero exit (duplicate `ADR-NNN`, dangling supersede link, bad status, malformed ADR) **hard-blocks** wrap-up, same tier as `verify_links`.

- [ ] **Step 2: Make step 6 (contradiction check) ADR-aware**

Update the Phase 3.5 **step 6** description:
- The comparison set from `contradictions.py context --spec <ID>` now includes **all active ADRs** — judge each changed spec against them (spec-vs-ADR → **fix the spec**). Surface `adr_warnings`.
- Also iterate the **changed `knowledge-base/decisions/**` ADRs** this cycle: for each, `contradictions.py adr-context --adr <ADR-NNN>` and judge against principles (→ **fix the ADR**) + peer ADRs (→ reconcile). Same resolve-to-proceed posture; `--against ADR-NNN` / `--spec ADR-NNN` record resolutions (no schema change).
- Keep the ordering line intact: deterministic facts (G1 + links + **adr verify** + accepted-behavior run) → G2 principle checkpoint (step 5) → G3 intent-coherence (step 6, now ADR-aware).

- [ ] **Step 3: Staging — ADRs are artifacts**

In the Phase 0 behavior-aware staging table and the Phase 5 artifacts list, add a row/line: **ADR files (`knowledge-base/decisions/ADR-*.md`) + `decisions/README.md` → artifacts (commit 2)** — same class as `SPEC-*.md` / `principles.md`.

- [ ] **Step 4: Consistency check**

Confirm the command paths and flags in wrap-up match Tasks 1–6 and Task 7 (especially `adr.py verify` and `contradictions.py adr-context --adr`). Fix any drift.

- [ ] **Step 5: Commit**

```bash
git add skills/wrap-up/SKILL.md
git commit -m "docs(wrap-up): ADR integrity hard-block + ADR-aware step 6 (P4a)

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

### Task 9: Design-doc updates — mark ADR-awareness delivered

**Files:**
- Modify: `docs/design/behavior-layer/00-vision.md`
- Modify: `docs/design/behavior-layer/parking-lot.md`

Deliverable: the vision and parking-lot reflect that P4a delivered ADR support + ADR-aware G3.

- [ ] **Step 1: Vision §8 + §10**

In `docs/design/behavior-layer/00-vision.md`:
- §8 Tier-2 bullet — after "**ADR-awareness is deferred** until the ADR phase ships a real `decisions/` format", append: *"— **delivered by P4a (2026-07-01):** the check now compares a changed spec against all active ADRs (always-global) and a changed ADR against its principles."*
- §10 "ADR capture machinery" bullet — append `(delivered — P4a)`.

- [ ] **Step 2: Parking-lot entry**

In `docs/design/behavior-layer/parking-lot.md`, update the "ADR capture machinery (Phase 4)" entry: prefix the heading with `~~…~~ DONE` (or a "Resolved" marker consistent with the file's existing resolved style) and add a one-line pointer to `docs/superpowers/specs/2026-07-01-p4a-adr-support-design.md` + the always-global scoping decision. Note the successor still open: **P4b declarative-drift** consumes ADR `related_code`.

- [ ] **Step 3: Commit**

```bash
git add docs/design/behavior-layer/00-vision.md docs/design/behavior-layer/parking-lot.md
git commit -m "docs(behavior-layer): mark ADR-awareness delivered by P4a

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

## Post-plan: dogfood + final review

After Task 9, before considering P4a done:
1. **Dogfood on the testbed** (`viva-croatia-testbed`, throwaway branch; restore `main` after): `adr new` an ADR; run `adr verify`/`adr list`; author a spec decision that contradicts it → confirm G3 `context` surfaces the ADR and the resolve-to-proceed flow logs `--against ADR-NNN`; author an ADR that contradicts a principle → confirm `adr-context` surfaces it (fix-the-ADR); re-run unchanged → auto-cleared; confirm a no-ADR project is unchanged.
2. **Final whole-branch review** — dispatch the code-reviewer on the full P4a range (`git merge-base` of the P4a work to HEAD) on the most capable model, per subagent-driven-development.
3. Record P4a completion in the SDD ledger + parking-lot; do **not** merge `feat/behavior-layer` (standing decision).
