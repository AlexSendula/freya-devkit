#!/usr/bin/env python3
"""Proof suite for verify_links.py — Tier-1 deterministic integrity checks.

Builds throwaway fixture projects on disk and asserts which errors fire.

Run:  python test_verify_links.py
"""

import os
import shutil
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from verify_links import verify  # noqa: E402


def _write(path: Path, content: str):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def _spec(spec_id, category, behaviors_block):
    """Render a spec file. `behaviors_block` is already-correctly-indented YAML
    (2-space dash, 4-space continuation), or "" for a declarative spec."""
    return (
        "---\n"
        f"id: {spec_id}\n"
        f"title: {spec_id} Title\n"
        f"category: {category}\n"
        "status: implemented\n"
        "certainty: 90\n"
        "created: 2026-06-24\n"
        "updated: 2026-06-24\n"
        "related_code:\n"
        "  - src/x.ts\n"
        "behaviors:\n"
        f"{behaviors_block}"
        "---\n\n"
        f"# {spec_id}\n"
    )


def _beh_block(behavior_id, title, state, adapter, locator=None, level=None, entry=None):
    block = (
        f"  - behavior_id: {behavior_id}\n"
        f"    title: {title}\n"
        f"    state: {state}\n"
        f"    adapter: {adapter}\n"
    )
    if locator is not None:
        block += f"    locator: {locator}\n"
    if level is not None:
        block += f"    level: {level}\n"
    if entry is not None:
        block += f"    entry: {entry}\n"
    return block


# Feature files — explicit, column-0 indentation (no dedent).
FEATURE_CLEAN = (
    "@SPEC-001\n"
    "Feature: Login\n"
    "\n"
    "  @BEH-001\n"
    "  Scenario: Successful login\n"
    "    Given a registered user\n"
    "    When they authenticate\n"
    "    Then they are logged in\n"
)
FEATURE_SCAFFOLD = (
    "@SPEC-001\n"
    "Feature: Login\n"
    "\n"
    "  @BEH-001\n"
    "  Scenario: Successful login\n"
    "    # TODO(scaffold): replace with real steps. Step definitions are not generated.\n"
    "    Given <initial state>\n"
    "    When <action>\n"
    "    Then <expected outcome>\n"
)
FEATURE_NO_BEH_TAG = (
    "@SPEC-001\n"
    "Feature: Login\n"
    "\n"
    "  Scenario: Successful login\n"
    "    Given a registered user\n"
    "    When they authenticate\n"
    "    Then they are logged in\n"
)
FEATURE_ORPHAN_TAG = FEATURE_CLEAN + (
    "\n"
    "  @BEH-999\n"
    "  Scenario: Ghost scenario\n"
    "    Given nothing\n"
    "    When nothing\n"
    "    Then nothing\n"
)


def _kinds(errors):
    return {e["kind"] for e in errors}


class VerifyLinksCase(unittest.TestCase):
    def _root(self):
        d = tempfile.mkdtemp()
        self.addCleanup(lambda: shutil.rmtree(d, ignore_errors=True))
        return Path(d)

    def _specs_dir(self, root):
        return str(root / "knowledge-base" / "specs")

    def _login_spec(self, root, state="accepted", adapter="cucumber",
                    locator="features/auth/login.feature#successful-login"):
        _write(root / "knowledge-base/specs/auth/SPEC-001-login.md",
               _spec("SPEC-001", "auth",
                     _beh_block("BEH-001", "Successful login", state, adapter, locator)))

    # --- sanity: fixtures actually parse (guards against vacuous passes) ---
    def test_fixture_actually_parses(self):
        from search_specs import load_all_specs
        root = self._root()
        self._login_spec(root)
        specs = load_all_specs(self._specs_dir(root))
        self.assertEqual(len(specs), 1)
        self.assertEqual(len(specs[0].behaviors), 1)
        self.assertEqual(specs[0].behaviors[0]["behavior_id"], "BEH-001")

    def test_clean_set_passes(self):
        root = self._root()
        self._login_spec(root)
        _write(root / "features/auth/login.feature", FEATURE_CLEAN)
        errors = verify(self._specs_dir(root))
        self.assertEqual(errors, [], f"expected clean, got {errors}")

    def test_broken_locator_reported(self):
        root = self._root()
        self._login_spec(root, locator="features/auth/missing.feature#successful-login")
        errors = verify(self._specs_dir(root))
        self.assertIn("locator-unresolved", _kinds(errors))

    def test_entry_unresolved_reported(self):
        root = self._root()
        _write(root / "knowledge-base/specs/auth/SPEC-001-login.md",
               _spec("SPEC-001", "auth",
                     _beh_block("BEH-001", "Successful login", "accepted", "cucumber",
                                locator="features/auth/login.feature#successful-login",
                                level="integration", entry="app/api/missing/route.ts")))
        _write(root / "features/auth/login.feature", FEATURE_CLEAN)
        errors = verify(self._specs_dir(root))
        self.assertIn("entry-unresolved", _kinds(errors))

    def test_entry_resolved_is_clean(self):
        root = self._root()
        _write(root / "knowledge-base/specs/auth/SPEC-001-login.md",
               _spec("SPEC-001", "auth",
                     _beh_block("BEH-001", "Successful login", "accepted", "cucumber",
                                locator="features/auth/login.feature#successful-login",
                                level="integration", entry="app/api/real/route.ts")))
        _write(root / "features/auth/login.feature", FEATURE_CLEAN)
        _write(root / "app/api/real/route.ts", "export function POST(){}\n")
        errors = verify(self._specs_dir(root))
        self.assertNotIn("entry-unresolved", _kinds(errors))

    def test_accepted_but_scaffold_reported(self):
        root = self._root()
        self._login_spec(root, state="accepted")
        _write(root / "features/auth/login.feature", FEATURE_SCAFFOLD)
        errors = verify(self._specs_dir(root))
        self.assertIn("accepted-but-scaffold", _kinds(errors))

    def test_proposed_with_scaffold_is_fine(self):
        root = self._root()
        self._login_spec(root, state="proposed")
        _write(root / "features/auth/login.feature", FEATURE_SCAFFOLD)
        errors = verify(self._specs_dir(root))
        self.assertNotIn("accepted-but-scaffold", _kinds(errors))

    def test_missing_reverse_tag_reported(self):
        root = self._root()
        self._login_spec(root)
        _write(root / "features/auth/login.feature", FEATURE_NO_BEH_TAG)
        errors = verify(self._specs_dir(root))
        self.assertIn("missing-reverse-tag", _kinds(errors))

    def test_orphan_tag_reported(self):
        root = self._root()
        self._login_spec(root)
        _write(root / "features/auth/login.feature", FEATURE_ORPHAN_TAG)
        errors = verify(self._specs_dir(root))
        self.assertIn("orphan-behavior-tag", _kinds(errors))

    def test_mixed_file_accepted_authored_passes_beside_proposed_scaffold(self):
        # Regression: an accepted+authored scenario must NOT be flagged just
        # because a sibling proposed scaffold in the same file still has TODO.
        root = self._root()
        _write(root / "knowledge-base/specs/auth/SPEC-012-passkey.md",
               _spec("SPEC-012", "auth",
                     _beh_block("BEH-007", "Successful passkey login", "accepted",
                                "cucumber",
                                "features/auth/passkey-login.feature#successful-passkey-login")
                     + _beh_block("BEH-008", "Rejected on bad credential", "proposed",
                                  "cucumber",
                                  "features/auth/passkey-login.feature#rejected-on-bad-credential")))
        _write(root / "features/auth/passkey-login.feature",
               "@SPEC-012\nFeature: Passkey Login\n\n"
               "  @BEH-007\n  Scenario: Successful passkey login\n"
               "    Given a registered passkey\n    When the user authenticates\n"
               "    Then they are logged in\n\n"
               "  @BEH-008\n  Scenario: Rejected on bad credential\n"
               "    # TODO(scaffold): replace with real steps. Step definitions are not generated.\n"
               "    Given <initial state>\n    When <action>\n    Then <expected outcome>\n")
        errors = verify(self._specs_dir(root))
        self.assertEqual(errors, [], f"expected clean mixed file, got {errors}")

    def test_duplicate_behavior_id_reported(self):
        root = self._root()
        _write(root / "knowledge-base/specs/auth/SPEC-001-login.md",
               _spec("SPEC-001", "auth",
                     _beh_block("BEH-001", "Successful login", "accepted", "manual")))
        _write(root / "knowledge-base/specs/api/SPEC-002-other.md",
               _spec("SPEC-002", "api",
                     _beh_block("BEH-001", "Reused id", "accepted", "manual")))
        errors = verify(self._specs_dir(root))
        self.assertIn("duplicate-id", _kinds(errors))

    def test_native_adapter_resolves_existing_test(self):
        root = self._root()
        self._login_spec(root, adapter="jest",
                         locator="tests/auth/login.test.ts#successful login")
        _write(root / "tests/auth/login.test.ts", "test('successful login', () => {});\n")
        errors = verify(self._specs_dir(root))
        self.assertEqual(errors, [], f"expected clean native link, got {errors}")

    def test_manual_adapter_needs_no_locator(self):
        root = self._root()
        _write(root / "knowledge-base/specs/auth/SPEC-001-login.md",
               _spec("SPEC-001", "auth",
                     _beh_block("BEH-001", "Admin reviews audit log", "accepted", "manual")))
        errors = verify(self._specs_dir(root))
        self.assertEqual(errors, [], f"expected clean manual behavior, got {errors}")

    def test_confirmed_without_locator_is_clean(self):
        root = self._root()
        _write(root / "knowledge-base/specs/auth/SPEC-001-login.md",
               _spec("SPEC-001", "auth",
                     _beh_block("BEH-001", "Owes a test", "confirmed", "cucumber")))
        errors = verify(self._specs_dir(root))
        self.assertEqual(errors, [], f"expected clean confirmed-no-test, got {errors}")

    def test_confirmed_entry_unresolved_still_reported(self):
        root = self._root()
        _write(root / "knowledge-base/specs/auth/SPEC-001-login.md",
               _spec("SPEC-001", "auth",
                     _beh_block("BEH-001", "Owes a test", "confirmed", "cucumber",
                                level="integration", entry="app/api/missing/route.ts")))
        errors = verify(self._specs_dir(root))
        self.assertIn("entry-unresolved", _kinds(errors))

    def test_confirmed_entry_resolved_is_clean(self):
        root = self._root()
        _write(root / "knowledge-base/specs/auth/SPEC-001-login.md",
               _spec("SPEC-001", "auth",
                     _beh_block("BEH-001", "Owes a test", "confirmed", "cucumber",
                                level="integration", entry="app/api/real/route.ts")))
        _write(root / "app/api/real/route.ts", "export function POST(){}\n")
        errors = verify(self._specs_dir(root))
        self.assertEqual(errors, [], f"expected clean, got {errors}")

    def test_accepted_missing_locator_still_reported(self):
        root = self._root()
        _write(root / "knowledge-base/specs/auth/SPEC-001-login.md",
               _spec("SPEC-001", "auth",
                     _beh_block("BEH-001", "Successful login", "accepted", "cucumber")))
        errors = verify(self._specs_dir(root))
        self.assertIn("missing-locator", _kinds(errors))


if __name__ == "__main__":
    unittest.main(verbosity=2)
