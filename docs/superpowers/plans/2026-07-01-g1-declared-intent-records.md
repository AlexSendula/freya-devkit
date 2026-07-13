# G1 — Declared-Intent Records Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make editing an `accepted` behavior's test a deterministic hard-block at wrap-up unless an in-change-set `INTENT-NNN` record authorizes it.

**Architecture:** One new git-aware check script (`verify_intent.py`) that intersects the change-set diff with accepted-behavior locators and requires a *new-since-baseline* intent record naming each edited behavior; one authoring helper (`intent.py new`); and SKILL.md wiring into `spec-manager verify` and `wrap-up` Phase 3.5/5. The check is a **sibling** to `verify_links.py` (same Tier-1 hard-block tier and exit-code convention) but git-aware/transition-based, so it stays a separate script. Fully deterministic — git + file reads, no model.

**Tech Stack:** Python 3.12 stdlib only (`unittest`, `subprocess`, `pathlib`, `argparse`, `json`, `re`, `datetime`); git CLI; the existing spec-manager helpers `search_specs.load_all_specs/find_specs_dir`, `frontmatter.parse_frontmatter`, `adapters.parse_locator`.

## Global Constraints

- **Stdlib-only Python** — zero pip installs; the plugin must run on a bare interpreter.
- **Block-style YAML lists only** in `INTENT-NNN.md` records (`behaviors:` as a `-` list) — the hand-rolled frontmatter parser silently discards *inline* arrays (`[BEH-003]`).
- **Baseline marker is G1's own** `knowledge-base/intents/.intent-last-verified`; **never reuse `.spec-last-update`** (wrap-up advances that in Phase 3, before the Phase 3.5 check). Advance the marker **only after the gate passes** (Phase 5).
- **Only `accepted` behaviors are governed.** Locator status **M or D** (modified/deleted) requires a record; **A** (added) and a **pure rename (R100)** do not; a rename with edits (R<100) counts as modified.
- **A record authorizes only when it is new in the change-set** (absent at the baseline commit) — this is what makes it self-scoping.
- **Exit non-zero when blocking; consumers must NOT use `check=True`** — they read the JSON on a non-zero exit (the discipline `verify_links` established).
- **Two-commit staging:** `INTENT-NNN.md` and the `.intent-last-verified` marker are **artifacts** (commit 2); the test edit + `Intent:` trailer are **code** (commit 1).
- **No-baseline / git-error behavior is fail-open** (skip, never falsely block) — a fresh repo or a corrupt baseline yields no block; the next successful wrap-up re-advances the marker.
- **Never touch the production webapp** (`/Users/main/Documents/areas/viva-croatia/webapp/`); dogfood on the testbed only.
- Commit messages end with: `Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>`.

---

### Task 1: `verify_intent.py` — the deterministic intent gate

**Files:**
- Create: `skills/spec-manager/scripts/verify_intent.py`
- Test: `skills/spec-manager/scripts/test_verify_intent.py`

**Interfaces:**
- Consumes: `search_specs.load_all_specs(specs_dir) -> list[Spec]`, `search_specs.find_specs_dir(start_path) -> str` (Spec has `.id` and `.behaviors: list[dict]` with keys `behavior_id`/`state`/`locator`); `frontmatter.parse_frontmatter(text) -> (dict, body)`; `adapters.parse_locator(locator) -> (path, fragment)`.
- Produces:
  - `verify_intent(project_dir: str = ".") -> dict` — result schema `{"version":1, "baseline":str|None, "skipped":bool, "edited_accepted":[{"behavior_id","spec_id","locator","path","status"}], "records_in_change":[{"id","behaviors":[str],"path"}], "authorized":[str], "unauthorized":[{"behavior_id","spec_id","path"}], "errors":[str], "warnings":[str], "note"?:str}`.
  - `advance_marker(project_dir: str) -> str|None` — writes the marker = current HEAD, returns the commit (or None on git error).
  - `MARKER_RELPATH = "knowledge-base/intents/.intent-last-verified"`, `INTENTS_RELDIR = "knowledge-base/intents"`.
  - CLI: `--project/-p`, `--format/-f {text,json}`, `--advance`. Exit `1` when `unauthorized` or `errors` is non-empty (else `0`); `--advance` exits `0` on success, `1` on git error.

- [ ] **Step 1: Write the failing test file**

Create `skills/spec-manager/scripts/test_verify_intent.py`:

```python
#!/usr/bin/env python3
"""Proof suite for verify_intent.py — the G1 declared-intent gate.

Builds throwaway git repos on disk and asserts which behaviors are unauthorized.

Run:  python test_verify_intent.py
"""

import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from verify_intent import verify_intent, advance_marker  # noqa: E402


def _write(path: Path, content: str):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def _git(root: Path, *args, check=True):
    r = subprocess.run(["git", "-C", str(root), *args],
                       capture_output=True, text=True)
    if check and r.returncode != 0:
        raise RuntimeError(f"git {args} failed: {r.stderr}")
    return r.stdout.strip()


def _init_repo(root: Path):
    _git(root, "init", "-q")
    _git(root, "config", "user.email", "t@t.t")
    _git(root, "config", "user.name", "T")


def _commit_all(root: Path, msg: str) -> str:
    _git(root, "add", "-A")
    _git(root, "commit", "-q", "-m", msg)
    return _git(root, "rev-parse", "HEAD")


def _set_marker(root: Path, commit: str):
    m = root / "knowledge-base/intents/.intent-last-verified"
    m.parent.mkdir(parents=True, exist_ok=True)
    m.write_text(f"# Intent gate last-verified\ncommit: {commit}\n", encoding="utf-8")


def _spec(spec_id, behaviors_block):
    return (
        "---\n"
        f"id: {spec_id}\n"
        f"title: {spec_id} Title\n"
        "category: auth\n"
        "status: implemented\n"
        "certainty: 90\n"
        "created: 2026-07-01\n"
        "updated: 2026-07-01\n"
        "behaviors:\n"
        f"{behaviors_block}"
        "---\n\n"
        f"# {spec_id}\n"
    )


def _beh_block(behavior_id, title, state, locator):
    return (
        f"  - behavior_id: {behavior_id}\n"
        f"    title: {title}\n"
        f"    state: {state}\n"
        f"    adapter: cucumber\n"
        f"    locator: {locator}\n"
    )


FEATURE = (
    "@SPEC-001\nFeature: Login\n\n"
    "  @BEH-001\n  Scenario: Successful login\n"
    "    Given a registered user\n    When they authenticate\n"
    "    Then they are logged in\n"
)


def _intent(intent_id, behaviors):
    beh = "".join(f"  - {b}\n" for b in behaviors)
    return (
        "---\n"
        f"id: {intent_id}\n"
        "behaviors:\n"
        f"{beh}"
        "approver: Alex\n"
        "date: 2026-07-01\n"
        "---\n"
        "## Rationale\nBecause.\n"
    )


class VerifyIntentCase(unittest.TestCase):
    def _root(self):
        d = tempfile.mkdtemp()
        self.addCleanup(lambda: shutil.rmtree(d, ignore_errors=True))
        return Path(d)

    def _accepted_project(self, root, state="accepted"):
        """Committed baseline: one accepted BEH-001 linked to a feature file."""
        _init_repo(root)
        _write(root / "knowledge-base/specs/auth/SPEC-001-login.md",
               _spec("SPEC-001",
                     _beh_block("BEH-001", "Successful login", state,
                                "features/auth/login.feature#successful-login")))
        _write(root / "features/auth/login.feature", FEATURE)
        base = _commit_all(root, "baseline")
        _set_marker(root, base)
        return base

    # --- the core cases ---
    def test_edited_accepted_test_without_record_blocks(self):
        root = self._root()
        self._accepted_project(root)
        _write(root / "features/auth/login.feature", FEATURE + "    And an extra step\n")
        res = verify_intent(str(root))
        self.assertEqual([u["behavior_id"] for u in res["unauthorized"]], ["BEH-001"])

    def test_edited_accepted_test_with_record_passes(self):
        root = self._root()
        self._accepted_project(root)
        _write(root / "features/auth/login.feature", FEATURE + "    And an extra step\n")
        _write(root / "knowledge-base/intents/INTENT-001.md", _intent("INTENT-001", ["BEH-001"]))
        res = verify_intent(str(root))
        self.assertEqual(res["unauthorized"], [])
        self.assertIn("BEH-001", res["authorized"])

    def test_added_accepted_test_needs_no_record(self):
        root = self._root()
        base = self._accepted_project(root)
        # A brand-new accepted behavior + committed new test file (status A).
        _write(root / "knowledge-base/specs/auth/SPEC-002-signup.md",
               _spec("SPEC-002",
                     _beh_block("BEH-002", "Signup", "accepted",
                                "features/auth/signup.feature#signup")))
        _write(root / "features/auth/signup.feature",
               "@SPEC-002\nFeature: Signup\n\n  @BEH-002\n  Scenario: Signup\n"
               "    Given a visitor\n    When they sign up\n    Then an account exists\n")
        _commit_all(root, "add signup")
        res = verify_intent(str(root))
        self.assertEqual(res["unauthorized"], [])

    def test_deleted_accepted_test_without_record_blocks(self):
        root = self._root()
        self._accepted_project(root)
        (root / "features/auth/login.feature").unlink()
        res = verify_intent(str(root))
        self.assertEqual([u["behavior_id"] for u in res["unauthorized"]], ["BEH-001"])

    def test_preexisting_record_does_not_authorize(self):
        root = self._root()
        _init_repo(root)
        _write(root / "knowledge-base/specs/auth/SPEC-001-login.md",
               _spec("SPEC-001",
                     _beh_block("BEH-001", "Successful login", "accepted",
                                "features/auth/login.feature#successful-login")))
        _write(root / "features/auth/login.feature", FEATURE)
        # Record committed as part of the BASELINE => not new in the change-set.
        _write(root / "knowledge-base/intents/INTENT-001.md", _intent("INTENT-001", ["BEH-001"]))
        base = _commit_all(root, "baseline with record")
        _set_marker(root, base)
        _write(root / "features/auth/login.feature", FEATURE + "    And a later edit\n")
        res = verify_intent(str(root))
        self.assertEqual([u["behavior_id"] for u in res["unauthorized"]], ["BEH-001"])

    def test_edited_proposed_test_is_free(self):
        root = self._root()
        self._accepted_project(root, state="proposed")
        _write(root / "features/auth/login.feature", FEATURE + "    And an extra step\n")
        res = verify_intent(str(root))
        self.assertEqual(res["unauthorized"], [])

    def test_deprecated_in_same_change_is_free(self):
        root = self._root()
        self._accepted_project(root)  # committed as accepted
        # Reclassify to deprecated on disk AND edit its test in the same change.
        _write(root / "knowledge-base/specs/auth/SPEC-001-login.md",
               _spec("SPEC-001",
                     _beh_block("BEH-001", "Successful login", "deprecated",
                                "features/auth/login.feature#successful-login")))
        _write(root / "features/auth/login.feature", FEATURE + "    And an extra step\n")
        res = verify_intent(str(root))
        self.assertEqual(res["unauthorized"], [])

    def test_pure_rename_needs_no_record(self):
        root = self._root()
        self._accepted_project(root)
        # git mv the test file (staged rename, 100% similarity) and repoint locator.
        _git(root, "mv", "features/auth/login.feature", "features/auth/renamed.feature")
        _write(root / "knowledge-base/specs/auth/SPEC-001-login.md",
               _spec("SPEC-001",
                     _beh_block("BEH-001", "Successful login", "accepted",
                                "features/auth/renamed.feature#successful-login")))
        res = verify_intent(str(root))
        self.assertEqual(res["unauthorized"], [])

    def test_no_baseline_skips(self):
        root = self._root()
        _init_repo(root)
        _write(root / "knowledge-base/specs/auth/SPEC-001-login.md",
               _spec("SPEC-001",
                     _beh_block("BEH-001", "Successful login", "accepted",
                                "features/auth/login.feature#successful-login")))
        _write(root / "features/auth/login.feature", FEATURE)
        _commit_all(root, "baseline")
        # No marker written.
        res = verify_intent(str(root))
        self.assertTrue(res["skipped"])
        self.assertEqual(res["unauthorized"], [])

    def test_baseline_equals_head_no_false_block(self):
        root = self._root()
        base = self._accepted_project(root)  # marker == HEAD, no working-tree edits
        res = verify_intent(str(root))
        self.assertFalse(res["skipped"])
        self.assertEqual(res["unauthorized"], [])

    def test_untracked_record_counts(self):
        root = self._root()
        self._accepted_project(root)
        _write(root / "features/auth/login.feature", FEATURE + "    And an extra step\n")
        # Record left untracked (never git-added) — must still authorize.
        _write(root / "knowledge-base/intents/INTENT-001.md", _intent("INTENT-001", ["BEH-001"]))
        res = verify_intent(str(root))
        self.assertEqual(res["unauthorized"], [])

    def test_malformed_record_is_error(self):
        root = self._root()
        self._accepted_project(root)
        _write(root / "features/auth/login.feature", FEATURE + "    And an extra step\n")
        _write(root / "knowledge-base/intents/INTENT-001.md",
               "---\nid: INTENT-001\napprover: Alex\ndate: 2026-07-01\n---\n## Rationale\nx\n")
        res = verify_intent(str(root))
        self.assertTrue(res["errors"], "malformed record must produce an error")

    def test_record_names_unknown_behavior_warns(self):
        root = self._root()
        base = self._accepted_project(root)
        # No edited accepted test; a new record names a non-existent behavior.
        _write(root / "knowledge-base/intents/INTENT-001.md", _intent("INTENT-001", ["BEH-999"]))
        res = verify_intent(str(root))
        self.assertEqual(res["unauthorized"], [])
        self.assertTrue(any("BEH-999" in w for w in res["warnings"]))

    def test_advance_marker_writes_head(self):
        root = self._root()
        base = self._accepted_project(root)
        (root / "knowledge-base/intents/.intent-last-verified").unlink()
        got = advance_marker(str(root))
        self.assertEqual(got, base)
        self.assertIn(base, (root / "knowledge-base/intents/.intent-last-verified").read_text())

    def test_cli_exit_code_and_json_contract(self):
        root = self._root()
        self._accepted_project(root)
        _write(root / "features/auth/login.feature", FEATURE + "    And an extra step\n")
        script = os.path.join(os.path.dirname(os.path.abspath(__file__)), "verify_intent.py")
        r = subprocess.run([sys.executable, script, "--project", str(root), "--format", "json"],
                           capture_output=True, text=True)
        self.assertEqual(r.returncode, 1)  # blocking
        data = json.loads(r.stdout)         # JSON still emitted on non-zero exit
        self.assertEqual([u["behavior_id"] for u in data["unauthorized"]], ["BEH-001"])


if __name__ == "__main__":
    unittest.main(verbosity=2)
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `cd skills/spec-manager/scripts && python test_verify_intent.py`
Expected: FAIL — `ImportError: cannot import name 'verify_intent' from 'verify_intent'` (module doesn't exist yet).

- [ ] **Step 3: Write `verify_intent.py`**

Create `skills/spec-manager/scripts/verify_intent.py`:

```python
#!/usr/bin/env python3
"""
Tier-1 deterministic declared-intent gate (governance G1).

Editing an `accepted` behavior's linked test is treated as an attempt to change
the intended behavior, and must be authorized by an in-change-set INTENT-NNN
record (knowledge-base/intents/). This check is git-aware and transition-based
(unlike verify_links.py, a stateless snapshot check), so it is a SIBLING script
that shares the same Tier-1 hard-block tier and exit-code convention.

Detection: files changed since the baseline commit ∩ accepted-behavior locators.
A record authorizes only when it is NEW in the change-set (absent at baseline),
which makes it self-scoping — a past record cannot bless a future edit.

Baseline: knowledge-base/intents/.intent-last-verified (G1's OWN marker — it must
NOT reuse .spec-last-update, which wrap-up advances in Phase 3 before this Phase
3.5 check runs). Absent marker => the check skips (fresh repo / full scan).

Exit code is non-zero when an accepted test changed without an authorizing record
(or a record is malformed), so wrap-up can gate on it. Fail-open on git error.

Usage:
    python verify_intent.py --project .
    python verify_intent.py --project . --format json
    python verify_intent.py --project . --advance   # write marker = current HEAD
"""

import argparse
import json
import os
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from search_specs import load_all_specs, find_specs_dir  # noqa: E402
from frontmatter import parse_frontmatter  # noqa: E402
from adapters import parse_locator  # noqa: E402

MARKER_RELPATH = "knowledge-base/intents/.intent-last-verified"
INTENTS_RELDIR = "knowledge-base/intents"


def _git(project_dir, *args):
    """Run git in project_dir; return (returncode, stdout). Never raises."""
    try:
        out = subprocess.run(["git", "-C", project_dir, *args],
                             capture_output=True, text=True)
        return out.returncode, out.stdout
    except (FileNotFoundError, OSError):
        return 1, ""


def _read_baseline(project_dir):
    """Commit hash from the marker, or None if absent/unreadable."""
    marker = Path(project_dir) / MARKER_RELPATH
    if not marker.exists():
        return None
    for line in marker.read_text(encoding="utf-8", errors="replace").splitlines():
        line = line.strip()
        if line.startswith("commit:"):
            return line.split(":", 1)[1].strip() or None
    return None


def _changed_status(project_dir, baseline):
    """Map {project-relative path: status} for baseline..working-tree.

    `git diff --name-status -M <baseline>` (one ref) compares the baseline to the
    working tree, so committed changes since baseline AND tracked working-tree
    edits both count. Rename entries record the NEW path with a ('R', similarity)
    tuple; others map to 'M'/'A'/'D'.
    """
    rc, out = _git(project_dir, "diff", "--name-status", "-M", baseline)
    status = {}
    if rc != 0:
        return status
    for line in out.splitlines():
        parts = line.split("\t")
        if len(parts) < 2:
            continue
        code = parts[0]
        if code.startswith("R"):
            sim = int(code[1:] or "0")
            status[parts[-1]] = ("R", sim)
        else:
            status[parts[-1]] = code[0]
    return status


def _is_change(status):
    """Modified or deleted => a change. Added or pure-rename(100%) => not."""
    if status is None:
        return False
    if isinstance(status, tuple):        # rename: changed only if content moved too
        return status[1] < 100
    return status in ("M", "D")


def _record_is_new(project_dir, baseline, relpath):
    """True if `relpath` did not exist at the baseline commit (=> in-change)."""
    rc, _ = _git(project_dir, "cat-file", "-e", f"{baseline}:{relpath}")
    return rc != 0


def _load_records(project_dir, baseline):
    """New-since-baseline INTENT records on disk.

    Filesystem scan (not git diff) so untracked, staged, and committed records
    all count uniformly. Returns (records, errors) where a record is
    {"id","behaviors":[...],"path"}; a malformed record yields an error string.
    """
    records, errors = [], []
    intents_dir = Path(project_dir) / INTENTS_RELDIR
    if not intents_dir.exists():
        return records, errors
    for f in sorted(intents_dir.glob("INTENT-*.md")):
        relpath = os.path.relpath(str(f), project_dir)
        if not _record_is_new(project_dir, baseline, relpath):
            continue  # pre-existing => does not authorize (self-scoping)
        fm, _body = parse_frontmatter(f.read_text(encoding="utf-8", errors="replace"))
        behaviors = fm.get("behaviors")
        if not isinstance(behaviors, list) or not behaviors:
            errors.append(f"{f.name}: malformed record — missing or empty 'behaviors:' list")
            continue
        records.append({"id": fm.get("id", f.stem), "behaviors": list(behaviors),
                        "path": relpath})
    return records, errors


def verify_intent(project_dir="."):
    project_dir = os.path.abspath(project_dir)
    specs_dir = find_specs_dir(project_dir)
    result = {"version": 1, "baseline": None, "skipped": False,
              "edited_accepted": [], "records_in_change": [],
              "authorized": [], "unauthorized": [], "errors": [], "warnings": []}

    baseline = _read_baseline(project_dir)
    result["baseline"] = baseline
    if not baseline:
        result["skipped"] = True
        result["note"] = "no baseline marker — intent gate skipped (governs transitions only)"
        return result

    status = _changed_status(project_dir, baseline)
    specs = load_all_specs(specs_dir)

    edited = []
    for s in specs:
        for b in s.behaviors:
            if b.get("state") != "accepted":
                continue
            locator = b.get("locator")
            if not locator:
                continue
            rel_path, _frag = parse_locator(locator)
            st = status.get(rel_path)
            if _is_change(st):
                edited.append({"behavior_id": b.get("behavior_id"), "spec_id": s.id,
                               "locator": locator, "path": rel_path,
                               "status": ("R" if isinstance(st, tuple) else st)})
    result["edited_accepted"] = edited

    records, errors = _load_records(project_dir, baseline)
    result["records_in_change"] = records
    result["errors"] = errors

    all_bids = {b.get("behavior_id") for s in specs for b in s.behaviors}
    covered = set()
    for rec in records:
        for bid in rec["behaviors"]:
            covered.add(bid)
            if bid not in all_bids:
                result["warnings"].append(
                    f"{rec['id']} names {bid}, which is not a known behavior")

    for e in edited:
        if e["behavior_id"] in covered:
            result["authorized"].append(e["behavior_id"])
        else:
            result["unauthorized"].append(
                {"behavior_id": e["behavior_id"], "spec_id": e["spec_id"], "path": e["path"]})

    return result


def advance_marker(project_dir):
    """Write the baseline marker = current HEAD. Returns the commit, or None."""
    rc, out = _git(project_dir, "rev-parse", "HEAD")
    if rc != 0 or not out.strip():
        return None
    commit = out.strip()
    marker = Path(project_dir) / MARKER_RELPATH
    marker.parent.mkdir(parents=True, exist_ok=True)
    marker.write_text(f"# Intent gate last-verified\ncommit: {commit}\n", encoding="utf-8")
    return commit


def _blocking(result):
    return bool(result["unauthorized"]) or bool(result["errors"])


def _print_text(result):
    if result["skipped"]:
        print("intent gate: skipped (no baseline marker)")
        return
    if not _blocking(result):
        print("OK — no accepted test changed without an authorizing intent record.")
    else:
        if result["unauthorized"]:
            print(f"{len(result['unauthorized'])} accepted test change(s) without an intent record:\n")
            for u in result["unauthorized"]:
                print(f"  [{u['behavior_id']}] {u['spec_id']}: {u['path']} changed — "
                      f"file knowledge-base/intents/INTENT-NNN.md naming {u['behavior_id']} "
                      f"(intent.py new --behavior {u['behavior_id']}), or revert the test edit.")
        for e in result["errors"]:
            print(f"  [error] {e}")
    for w in result["warnings"]:
        print(f"  [warn] {w}")


def main():
    parser = argparse.ArgumentParser(description="Tier-1 declared-intent gate (G1)")
    parser.add_argument("--project", "-p", default=".", help="Project root (default: .)")
    parser.add_argument("--format", "-f", choices=["text", "json"], default="text")
    parser.add_argument("--advance", action="store_true",
                        help="Write the baseline marker = current HEAD (after a passing wrap-up).")
    args = parser.parse_args()

    if args.advance:
        commit = advance_marker(args.project)
        if commit:
            print(f"intent baseline advanced to {commit[:10]}")
            sys.exit(0)
        print("could not advance marker (git error)", file=sys.stderr)
        sys.exit(1)

    result = verify_intent(args.project)
    if args.format == "json":
        print(json.dumps(result, indent=2))
    else:
        _print_text(result)
    sys.exit(1 if _blocking(result) else 0)


if __name__ == "__main__":
    main()
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `cd skills/spec-manager/scripts && python test_verify_intent.py`
Expected: PASS — `Ran 15 tests ... OK`.

- [ ] **Step 5: Run the sibling suites to confirm no regressions**

Run: `cd skills/spec-manager/scripts && python test_verify_links.py && python test_frontmatter.py && python test_adapters.py`
Expected: all three suites `OK`.

- [ ] **Step 6: Commit**

```bash
git add skills/spec-manager/scripts/verify_intent.py skills/spec-manager/scripts/test_verify_intent.py
git commit -m "feat(spec-manager): verify_intent — deterministic declared-intent gate (G1)

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

### Task 2: `intent.py new` — the authoring helper

**Files:**
- Create: `skills/spec-manager/scripts/intent.py`
- Test: `skills/spec-manager/scripts/test_intent.py`

**Interfaces:**
- Consumes: `frontmatter.parse_frontmatter` (in the test, to prove the written record round-trips).
- Produces:
  - `render_record(intent_id: str, behaviors: list[str], approver: str, rationale: str, day: str) -> str` — block-style frontmatter + `## Rationale`.
  - `_next_id(intents_dir: Path) -> str` — next `INTENT-NNN` (zero-padded 3), `INTENT-001` on an empty/absent dir.
  - `new_record(project_dir, behaviors, approver, rationale, day) -> str` — creates `knowledge-base/intents/` if absent, writes the record, returns its path.
  - CLI: `intent.py new --behavior/-b BEH-NNN (repeatable) --approver X [--rationale R] [--date YYYY-MM-DD] [--project .]`, prints the created path.

- [ ] **Step 1: Write the failing test**

Create `skills/spec-manager/scripts/test_intent.py`:

```python
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
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `cd skills/spec-manager/scripts && python test_intent.py`
Expected: FAIL — `ModuleNotFoundError: No module named 'intent'`.

- [ ] **Step 3: Write `intent.py`**

Create `skills/spec-manager/scripts/intent.py`:

```python
#!/usr/bin/env python3
"""Authoring helper for declared-intent (INTENT-NNN) records (governance G1).

`intent new` allocates the next INTENT id and writes a block-style record naming
the behaviors whose accepted test is being changed. The gate (verify_intent.py)
then recognizes the new record as authorizing the change. Block-style lists only
— the hand-rolled frontmatter parser discards inline arrays.
"""

import argparse
import re
import sys
from datetime import date as _date
from pathlib import Path

INTENTS_RELDIR = "knowledge-base/intents"
_BEH_RE = re.compile(r"^BEH-\d+$")
_ID_RE = re.compile(r"INTENT-(\d+)\.md$")


def _next_id(intents_dir: Path) -> str:
    n = 0
    if intents_dir.exists():
        for f in intents_dir.glob("INTENT-*.md"):
            m = _ID_RE.search(f.name)
            if m:
                n = max(n, int(m.group(1)))
    return f"INTENT-{n + 1:03d}"


def render_record(intent_id, behaviors, approver, rationale, day) -> str:
    beh_lines = "".join(f"  - {b}\n" for b in behaviors)
    return (
        "---\n"
        f"id: {intent_id}\n"
        "behaviors:\n"
        f"{beh_lines}"
        f"approver: {approver}\n"
        f"date: {day}\n"
        "---\n"
        "## Rationale\n"
        f"{rationale}\n"
    )


def new_record(project_dir, behaviors, approver, rationale, day) -> str:
    intents_dir = Path(project_dir) / INTENTS_RELDIR
    intents_dir.mkdir(parents=True, exist_ok=True)
    intent_id = _next_id(intents_dir)
    path = intents_dir / f"{intent_id}.md"
    path.write_text(render_record(intent_id, behaviors, approver, rationale, day),
                    encoding="utf-8")
    return str(path)


def _beh(value):
    if not _BEH_RE.match(value):
        raise argparse.ArgumentTypeError(f"--behavior must be BEH-NNN, got {value!r}")
    return value


def main():
    parser = argparse.ArgumentParser(description="Declared-intent record helper (G1)")
    sub = parser.add_subparsers(dest="cmd", required=True)
    n = sub.add_parser("new", help="Create a new INTENT-NNN record")
    n.add_argument("--behavior", "-b", required=True, action="append", type=_beh,
                   help="BEH-NNN this record authorizes changing (repeatable)")
    n.add_argument("--approver", required=True)
    n.add_argument("--rationale", default="TODO: why this accepted behavior is changing.")
    n.add_argument("--date", dest="day", default=None, help="YYYY-MM-DD (default: today)")
    n.add_argument("--project", "-p", default=".")
    args = parser.parse_args()

    if args.cmd == "new":
        day = args.day or _date.today().isoformat()
        print(new_record(args.project, args.behavior, args.approver, args.rationale, day))


if __name__ == "__main__":
    main()
```

- [ ] **Step 4: Run the test to verify it passes**

Run: `cd skills/spec-manager/scripts && python test_intent.py`
Expected: PASS — `Ran 5 tests ... OK`.

- [ ] **Step 5: Verify the CLI end-to-end**

Run: `cd /tmp && rm -rf itest && mkdir itest && python "$OLDPWD/skills/spec-manager/scripts/intent.py" new -b BEH-003 --approver Alex --rationale "x" --date 2026-07-01 --project itest && cat itest/knowledge-base/intents/INTENT-001.md`
Expected: prints `itest/knowledge-base/intents/INTENT-001.md`, then the record with a block-style `behaviors:` list.

- [ ] **Step 6: Commit**

```bash
git add skills/spec-manager/scripts/intent.py skills/spec-manager/scripts/test_intent.py
git commit -m "feat(spec-manager): intent.py — INTENT-NNN authoring helper (G1)

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

### Task 3: Wire the gate into `spec-manager` and `wrap-up` (SKILL.md)

**Files:**
- Modify: `skills/spec-manager/SKILL.md` (the `verify` command section; the Quick Reference table; the `init` step list; a new Declared-Intent Records subsection)
- Modify: `skills/wrap-up/SKILL.md` (Phase 3.5; Phase 5; the behavior-aware staging table)

**Interfaces:**
- Consumes: `verify_intent.py` (`--project/--format/--advance`) and `intent.py new` from Tasks 1–2, invoked via the plugin's absolute cache path `"/Users/main/.claude/plugins/cache/freya-devkit/freya-devkit/0.1.0/skills/spec-manager/scripts/…"` (the convention every other SKILL.md script call already uses).
- Produces: no code; documentation wiring so the deterministic gate actually runs at `spec-manager verify` and `wrap-up`.

- [ ] **Step 1: Add the Quick Reference row and `init` step in `spec-manager/SKILL.md`**

In the Quick Reference table (after the `verify` row), add:

```markdown
| `intent new <BEH...>` | Create an INTENT-NNN record authorizing a change to an accepted behavior's test |
```

In the `init` command's numbered steps, add a step after the `decisions/` step:

```markdown
7. Create `/knowledge-base/intents/` (home for `INTENT-NNN` declared-intent records; starts empty with a `.gitkeep`)
```

- [ ] **Step 2: Extend the `verify` command section in `spec-manager/SKILL.md`**

Immediately after the existing `verify_links.py` invocation block (the one ending "These are **deterministic failures** — at wrap-up they hard-block (vision §8)."), add:

````markdown
1b. Run the deterministic **declared-intent gate** (governance G1) — also a deterministic
    hard-block:
    ```bash
    python "/Users/main/.claude/plugins/cache/freya-devkit/freya-devkit/0.1.0/skills/spec-manager/scripts/verify_intent.py" --project . --format json
    ```
    This exits non-zero when an `accepted` behavior's linked test was **modified or
    deleted** in the current change-set (since the `.intent-last-verified` baseline)
    without a **new** `INTENT-NNN` record naming that behavior. Remedy: `spec-manager
    intent new <BEH-NNN>` (declare the change) or revert the test edit. With no
    baseline marker the gate skips. **Consume its JSON on the non-zero exit — do not
    run it with `check=True`.**
````

- [ ] **Step 3: Add the Declared-Intent Records subsection to `spec-manager/SKILL.md`**

After the "Intentional Design Decisions" section, add:

````markdown
## Declared-Intent Records (governance G1)

An `accepted` behavior's test is its machine-checkable guarantee. Editing that test
is treated as an attempt to change the intended behavior, and is a **deterministic
hard-block** at wrap-up unless an `INTENT-NNN` record in the same change-set declares
it (vision §7). This is the *only* sanctioned way to change an accepted guarantee;
otherwise a red (or silently-edited-green) accepted test is always a regression.

**Record** — `knowledge-base/intents/INTENT-NNN.md`, block-style frontmatter:

```markdown
---
id: INTENT-001
behaviors:
  - BEH-003
approver: Alex
date: 2026-07-01
---
## Rationale
Anti-enumeration response changed from a 404 to a uniform 200 per the revised
threat model.
```

**Create one** (when the gate blocks you, or proactively before editing an accepted test):

```bash
python "/Users/main/.claude/plugins/cache/freya-devkit/freya-devkit/0.1.0/skills/spec-manager/scripts/intent.py" \
  new --behavior BEH-003 --approver "<you>" --rationale "<why the guarantee is changing>"
```

**Scope & rules:**
- Only `accepted` behaviors are governed. `proposed`/`confirmed`/`quarantined`/`deprecated` tests change freely.
- A record authorizes **only when it is new in the change-set** — a past record cannot bless a future edit (temporal self-scoping).
- Newly *added* accepted tests and pure renames need no record; *modified* or *deleted* ones do.
- The file is the gate's source of truth; add an `Intent: INTENT-NNN` commit trailer for traceability.
- The gate verifies a record *exists* — not that its rationale is honest (that judgment is the Tier-2 governance track, not G1).
````

- [ ] **Step 4: Wire Phase 3.5 in `wrap-up/SKILL.md`**

In "### Phase 3.5: Behavior Integrity & Accepted-Behavior Run", after step 1 (the `verify_links.py` hard-block), insert a new step (renumbering the accepted-run step to 3):

````markdown
2. **Declared-intent gate (hard-block).** Run:
   ```bash
   python "/Users/main/.claude/plugins/cache/freya-devkit/freya-devkit/0.1.0/skills/spec-manager/scripts/verify_intent.py" --project . --format json
   ```
   A non-zero exit means an `accepted` behavior's test was modified/deleted in this
   change-set without a **new** `INTENT-NNN` record naming it (governance G1). This
   **blocks** wrap-up: either `spec-manager intent new <BEH-NNN>` to declare the
   intended change, or revert the test edit (a bare accepted-test change is a
   regression). With no `.intent-last-verified` baseline the gate skips. **Read the
   JSON on the non-zero exit — never `check=True`.**
````

- [ ] **Step 5: Wire Phase 5 (marker advance) and the staging table in `wrap-up/SKILL.md`**

In "#### Behavior-aware staging rule", add two rows to the table:

```markdown
| `INTENT-NNN.md` records + `.intent-last-verified` marker | **Artifacts** (commit 2) |
| an accepted test's edit + its `Intent: INTENT-NNN` commit trailer | **Code** (commit 1) |
```

In "### Phase 5: Artifacts Commit", add a numbered step before staging (so the marker advances only after the Phase 3.5 gate passed):

````markdown
0. Advance the declared-intent baseline to the commit being wrapped (only reached
   because the Phase 3.5 gate passed):
   ```bash
   python "/Users/main/.claude/plugins/cache/freya-devkit/freya-devkit/0.1.0/skills/spec-manager/scripts/verify_intent.py" --project . --advance
   ```
   Stage `knowledge-base/intents/` (any new `INTENT-NNN.md` and the updated
   `.intent-last-verified`) with the other artifacts.
````

- [ ] **Step 6: Verify the wiring text is present and paths are correct**

Run:
```bash
grep -c "verify_intent.py" skills/spec-manager/SKILL.md skills/wrap-up/SKILL.md
grep -c "intent new\|intent.py" skills/spec-manager/SKILL.md
grep -n "INTENT-NNN.md" skills/wrap-up/SKILL.md
```
Expected: `verify_intent.py` appears ≥1× in each file; the `intent` helper referenced in spec-manager; the staging row present in wrap-up.

- [ ] **Step 7: Run the full spec-manager suite once more (no code changed, but confirm green)**

Run: `cd skills/spec-manager/scripts && python test_verify_intent.py && python test_intent.py && python test_verify_links.py && python test_frontmatter.py`
Expected: all `OK`.

- [ ] **Step 8: Commit**

```bash
git add skills/spec-manager/SKILL.md skills/wrap-up/SKILL.md
git commit -m "docs(spec-manager,wrap-up): wire the G1 declared-intent gate into verify + wrap-up

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

## Dogfood (after all tasks, on the testbed — not part of the plan's commits)

On the testbed (`/Users/main/Documents/projects/viva-croatia-testbed`), on a throwaway branch, with an `accepted` behavior present (BEH-002/BEH-003 in `SPEC-001-passkey-login.md`): write the `.intent-last-verified` marker at HEAD, edit an accepted behavior's linked test so it *stays green*, run `verify_intent.py` → confirm it blocks naming that behavior; run `intent.py new --behavior <BEH>` → confirm it passes; edit a `proposed` behavior's test → confirm it never blocks. Restore the testbed to `main` and delete the branch afterward. Production webapp off-limits.

---

## Scope note — deferred from the spec

The spec lists an **optional** "mechanical change-history pointer stamp" (accepting a
record appends a one-line pointer into the behavior's spec Change History) as
in-scope. This plan **defers it** (YAGNI): the `INTENT-NNN` record already names its
behaviors, and the `Intent:` commit trailer already ties the change to the record, so
the traceability the stamp would add is redundant — and stamping would mean parsing/
editing a Change History section that many specs don't yet have. If wanted later, it's
a self-contained follow-up (a `spec-manager` helper that appends to the owning spec).
This is the one conscious deviation from the spec's in-scope list; everything else in
§10 is covered by Tasks 1–3.

## Notes for the executor

- **DRY:** `verify_intent.py` reuses `load_all_specs`/`find_specs_dir`/`parse_frontmatter`/`parse_locator` — do not re-parse specs or locators by hand.
- **Fail-open on git errors** is intentional (Global Constraints): `_git` never raises and a missing/corrupt baseline skips rather than blocks. Do not "harden" this into a block.
- **Marker timing is load-bearing:** advance the marker only in Phase 5 (after the gate). Reusing `.spec-last-update` or advancing earlier silently disables the gate — the `test_baseline_equals_head_no_false_block` test guards the symptom.
- Every script is invoked in production via the absolute plugin cache path; keep the `sys.path.insert(0, dirname(__file__))` shim so sibling imports work regardless of cwd.
