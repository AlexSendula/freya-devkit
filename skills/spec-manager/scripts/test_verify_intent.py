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

    def test_unparseable_record_is_error_not_traceback(self):
        """A genuinely malformed frontmatter fence must produce an error, not raise."""
        root = self._root()
        self._accepted_project(root)
        _write(root / "features/auth/login.feature", FEATURE + "    And an extra step\n")
        # Unterminated --- fence: parse_frontmatter raises FrontmatterError on this.
        _write(root / "knowledge-base/intents/INTENT-001.md",
               "---\nid: INTENT-001\nbehaviors:\n  - BEH-001\n# missing closing fence\n")
        res = verify_intent(str(root))  # must not raise
        self.assertTrue(res["errors"], "unparseable INTENT record must produce an error entry")
        self.assertEqual([u["behavior_id"] for u in res["unauthorized"]], ["BEH-001"],
                         "unparseable record must not cover any behavior")

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
