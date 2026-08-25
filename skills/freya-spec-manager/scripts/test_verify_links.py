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
# `SKIP_DIRS` is bound here at import, deliberately: the table below drives off this
# binding while the code under test reads `verify_links.SKIP_DIRS`. That is what makes
# "empty the registry and watch every row go red" a check rather than a tautology — an
# emptied registry would otherwise empty the table too and pass with nothing run.
from verify_links import SKIP_DIRS, verify  # noqa: E402


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
# Nothing in this file resolves: SPEC-404 is not a spec and BEH-999 is not a behavior. Put
# anywhere the reverse scan reaches, it is worth exactly two findings.
FEATURE_ALL_ORPHAN = (
    "@SPEC-404\n"
    "Feature: Ghost\n"
    "\n"
    "  @BEH-999\n"
    "  Scenario: Ghost scenario\n"
    "    Given nothing\n"
    "    When nothing\n"
    "    Then nothing\n"
)
ORPHAN_KINDS = {"orphan-spec-tag", "orphan-behavior-tag"}


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

    # `test_native_adapter_resolves_existing_test` was deleted here 2026-08-21.
    # It cited `login.test.ts#successful login` against a body spelled
    # `test('successful login', ...)`, which reads as a fragment check and was
    # never one — nothing resolves a non-Python fragment. Measured: teaching
    # verify_links to match those fragments by substring left it green while
    # `PythonLocatorSymbolCase.test_a_non_python_locator_keeps_its_fragment_
    # unchecked` went red. The rest of it — an accepted native adapter whose
    # locator resolves — is `test_clean_set_passes` and the mixed-file case,
    # both of which go red when the `missing-locator` guard is mis-scoped.

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


# A real module for a locator to point into. Column-0, no dedent.
PY_MODULE = (
    "import unittest\n"
    "\n"
    "\n"
    "class LoginCase(unittest.TestCase):\n"
    "    def test_a_registered_user_can_authenticate(self):\n"
    "        self.assertTrue(True)\n"
    "\n"
    "\n"
    "def test_a_bare_module_level_function(self):\n"
    "    assert True\n"
)


class _PyLocatorFixture(unittest.TestCase):
    """Shared fixture for the Python-locator cases."""

    def _root(self):
        d = tempfile.mkdtemp()
        self.addCleanup(lambda: shutil.rmtree(d, ignore_errors=True))
        return Path(d)

    def _specs_dir(self, root):
        return str(root / "knowledge-base" / "specs")

    def _project(self, locator, adapter="unittest", state="proposed",
                 module=PY_MODULE, path="tests/test_login.py", entry=None):
        root = self._root()
        if module is not None:
            _write(root / path, module)
        _write(root / "knowledge-base/specs/auth/SPEC-001-login.md",
               _spec("SPEC-001", "auth",
                     _beh_block("BEH-001", "Successful login", state, adapter,
                                locator, entry=entry)))
        return verify(self._specs_dir(root))


class PythonLocatorSymbolCase(_PyLocatorFixture):
    """`path#Class.method` has to name a symbol that is really there.

    Until 2026-08-21 `parse_locator`'s fragment was discarded for every
    non-Gherkin adapter, so the whole forward check was `abs_path.exists()`.
    Renaming a test method broke the link and nothing said so — measured by
    renaming every locator target in this repo out of existence: `verify-links`
    still exited 0 with all 1,435 tests passing.
    """

    def test_a_method_that_exists_resolves(self):
        self.assertEqual(self._project(
            "tests/test_login.py#LoginCase.test_a_registered_user_can_authenticate"), [])

    def test_a_method_that_does_not_exist_is_an_error(self):
        errors = self._project("tests/test_login.py#LoginCase.test_a_method_nobody_wrote")
        self.assertIn("locator-symbol-unresolved", _kinds(errors))

    def test_a_class_that_does_not_exist_is_an_error(self):
        errors = self._project(
            "tests/test_login.py#GhostCase.test_a_registered_user_can_authenticate")
        self.assertIn("locator-symbol-unresolved", _kinds(errors))

    def test_a_bare_module_level_function_resolves(self):
        self.assertEqual(
            self._project("tests/test_login.py#test_a_bare_module_level_function"), [])

    def test_a_class_named_alone_resolves(self):
        """`path#Class` with no method is a legitimate whole-class anchor."""
        self.assertEqual(self._project("tests/test_login.py#LoginCase"), [])

    def test_the_pytest_double_colon_form_is_resolved_too(self):
        errors = self._project("tests/test_login.py::LoginCase.test_a_method_nobody_wrote")
        self.assertIn("locator-symbol-unresolved", _kinds(errors))

    def test_the_pytest_double_colon_separator_between_class_and_method_resolves(self):
        """pytest's own node-id form is `file::Class::method`, not `Class.method`."""
        self.assertEqual(self._project(
            "tests/test_login.py::LoginCase::test_a_registered_user_can_authenticate"), [])

    def test_a_non_python_locator_keeps_its_fragment_unchecked(self):
        """Only Python can be resolved by AST. A `.ts` fragment is a runner
        selector we have no parser for, and inventing one would fail loud on
        links that are fine."""
        root = self._root()
        _write(root / "tests/login.test.ts", "test('successful login', () => {});\n")
        _write(root / "knowledge-base/specs/auth/SPEC-001-login.md",
               _spec("SPEC-001", "auth",
                     _beh_block("BEH-001", "Successful login", "proposed", "vitest",
                                "tests/login.test.ts#no such scenario")))
        self.assertEqual(verify(self._specs_dir(root)), [])

    def test_an_unparseable_python_file_does_not_claim_the_symbol_is_missing(self):
        """A file we cannot parse tells us nothing about the symbol. Reporting
        `locator-symbol-unresolved` there would be a confidently-wrong result
        (ADR-005) — the syntax error is the finding, not the link."""
        errors = self._project(
            "tests/test_login.py#LoginCase.test_a_registered_user_can_authenticate",
            module="class Broken(:\n")
        self.assertNotIn("locator-symbol-unresolved", _kinds(errors))
        self.assertIn("locator-unparseable", _kinds(errors))

    def test_a_locator_with_no_fragment_is_still_only_a_file_check(self):
        """`path` alone names the whole file. There is no symbol to resolve."""
        self.assertEqual(self._project("tests/test_login.py"), [])


class ManualLocatorCase(_PyLocatorFixture):
    """`adapter: manual` skipped the locator entirely — not just the fragment,
    the whole check, before the file even had to exist.

    Measured on this repo the day it was found: 17 manual behaviors carried a
    locator, 11 named a method that was not there and 6 named a file that had
    never existed, and `verify-links` reported OK. Manual means no runner drives
    it; it does not mean the address is exempt from being real.
    """

    def test_a_manual_locator_naming_a_missing_file_is_an_error(self):
        errors = self._project("tests/test_nobody_wrote.py#Case.test_thing",
                               adapter="manual", module=None)
        self.assertIn("locator-unresolved", _kinds(errors))

    def test_a_manual_locator_naming_a_missing_method_is_an_error(self):
        errors = self._project("tests/test_login.py#LoginCase.test_a_method_nobody_wrote",
                               adapter="manual")
        self.assertIn("locator-symbol-unresolved", _kinds(errors))

    def test_a_manual_locator_that_resolves_is_clean(self):
        self.assertEqual(self._project(
            "tests/test_login.py#LoginCase.test_a_registered_user_can_authenticate",
            adapter="manual"), [])

    def test_manual_with_no_locator_at_all_is_still_fine(self):
        """The exemption that was real: a manual behavior owes no address."""
        root = self._root()
        _write(root / "knowledge-base/specs/auth/SPEC-001-login.md",
               _spec("SPEC-001", "auth",
                     _beh_block("BEH-001", "Successful login", "proposed", "manual")))
        self.assertEqual(verify(self._specs_dir(root)), [])

    def test_manual_never_gets_the_gherkin_reverse_tag_checks(self):
        """Resolving a manual locator must not drag it into the Gherkin branch —
        a manual behavior owes no `@BEH-NNN` tag in its target."""
        root = self._root()
        _write(root / "features/auth/login.feature", FEATURE_NO_BEH_TAG)
        _write(root / "knowledge-base/specs/auth/SPEC-001-login.md",
               _spec("SPEC-001", "auth",
                     _beh_block("BEH-001", "Successful login", "proposed", "manual",
                                "features/auth/login.feature#successful-login")))
        self.assertEqual(verify(self._specs_dir(root)), [])


class LocatorEscapesProjectCase(_PyLocatorFixture):
    """SEC-013: `abs_path = root / rel_path` discards `root` when `rel_path` is
    absolute — `Path('/a/b') / '/etc/passwd'` is `/etc/passwd`. Before the symbol
    check that leaked an existence bit about the host; with it, it would parse an
    out-of-project file.
    """

    def test_a_posix_absolute_locator_is_rejected(self):
        self.assertIn("locator-escapes-project", _kinds(self._project("/etc/passwd")))

    def test_a_dotdot_locator_is_rejected(self):
        errors = self._project("../../../../../../etc/passwd")
        self.assertIn("locator-escapes-project", _kinds(errors))

    def test_a_windows_drive_locator_is_rejected(self):
        errors = self._project("C:\\Windows\\System32\\drivers\\etc\\hosts")
        self.assertIn("locator-escapes-project", _kinds(errors))

    def test_a_windows_root_locator_is_rejected(self):
        self.assertIn("locator-escapes-project", _kinds(self._project("\\Windows\\win.ini")))

    def test_an_escaping_entry_is_rejected_too(self):
        """`entry` is resolved by the same `root / value` idiom two lines up."""
        root = self._root()
        _write(root / "knowledge-base/specs/auth/SPEC-001-login.md",
               _spec("SPEC-001", "auth",
                     _beh_block("BEH-001", "Successful login", "proposed", "manual",
                                locator=None, entry="/etc/passwd")))
        self.assertIn("entry-escapes-project", _kinds(verify(self._specs_dir(root))))

    def test_an_escaping_locator_is_not_also_reported_as_unresolved(self):
        """One finding per defect: the escape is the error, not a stat result."""
        kinds = _kinds(self._project("/etc/passwd"))
        self.assertNotIn("locator-unresolved", kinds)

    def test_an_ordinary_relative_locator_is_not_flagged(self):
        self.assertEqual(self._project("tests/test_login.py#LoginCase"), [])

    def test_a_dotdot_is_rejected_even_when_it_normalises_back_inside(self):
        """`a/../b` does resolve to `b`, inside the project — and is still
        rejected, matching `freya_cli._escapes`. One containment rule for the
        whole repo beats two that disagree at the margin, and no honest locator
        needs `..`; ADR-002, single ownership of the predicate.
        """
        errors = self._project("tests/nested/../test_login.py#LoginCase")
        self.assertIn("locator-escapes-project", _kinds(errors))


class LocatorNamesNoFileCase(_PyLocatorFixture):
    """The two shapes that walked through the gate by being *almost* nothing.

    Found on 2026-08-23 not by this gate's own tests but by
    `behavior_graph.covering()`, which asks the stricter question and had been
    quietly diverging from Tier 1 as a result. Both shapes made
    `verify_links` print "OK — all behavior links pass" over a locator that
    resolved to no test whatsoever.
    """

    def test_a_locator_with_no_path_part_is_rejected(self):
        """`#scenario-only` parses to an empty path. `escapes("")` is false and
        `root / ""` is the project root, which exists — so both guards passed."""
        self.assertIn("locator-names-no-file", _kinds(self._project("#scenario-only")))

    def test_a_locator_naming_a_directory_is_rejected(self):
        """`Path.exists` is true for a directory. A locator names a test file."""
        root = self._root()
        (root / "tests" / "nested").mkdir(parents=True, exist_ok=True)
        _write(root / "knowledge-base/specs/auth/SPEC-001-login.md",
               _spec("SPEC-001", "auth",
                     _beh_block("BEH-001", "Successful login", "accepted", "pytest",
                                locator="tests/nested")))
        self.assertIn("locator-unresolved", _kinds(verify(self._specs_dir(root))))

    def test_an_empty_path_is_not_reported_as_escaping(self):
        """Its own kind, not a neighbour's. An empty path escapes nothing, and
        "path does not exist" would send the author to correct a path rather
        than to write one — a different authoring mistake with a different fix.
        """
        kinds = _kinds(self._project("#scenario-only"))
        self.assertNotIn("locator-escapes-project", kinds)
        self.assertNotIn("locator-unresolved", kinds)


class ReverseScanSkipDirsCase(unittest.TestCase):
    """Every directory the reverse `.feature` scan walks past, one row per declared member.

    The table drives off `SKIP_DIRS` itself, so a ninth name added to the constant is
    exercised the moment it is added — eight were declared and one was named by hand when
    this was written.

    Each row asserts the *consequence*: an all-orphan feature file sitting in that directory
    yields no orphan finding. It never asserts that the set contains what the set contains —
    `assertEqual(sorted(SKIP_DIRS), [...])` would pass with `_iter_feature_files`' guard
    deleted, which is the whole failure mode.

    `test_the_control_fixture_really_does_fire` is the guard against the vacuous pass this
    repo has now hit three times: the identical file under an ordinary `features/` must
    report both orphan kinds. Without it, every row below would stay green if the fixture
    quietly stopped parsing, and the table would prove nothing at all.

    Mutation-checked 2026-08-21. With `verify_links.SKIP_DIRS = frozenset()` all eight rows
    go red — `orphan-spec-tag` and `orphan-behavior-tag` for each — and the control stays
    green. No second list eats these fixtures before the guard sees them.
    """

    def _root(self):
        d = tempfile.mkdtemp()
        self.addCleanup(lambda: shutil.rmtree(d, ignore_errors=True))
        return Path(d)

    def _orphan_feature_under(self, directory):
        """A project whose only `.feature` file is an orphan, parked in `directory`."""
        root = self._root()
        _write(root / "knowledge-base/specs/auth/SPEC-001-login.md",
               _spec("SPEC-001", "auth",
                     _beh_block("BEH-001", "Admin reviews audit log", "proposed", "manual")))
        _write(root / directory / "ghost.feature", FEATURE_ALL_ORPHAN)
        return verify(str(root / "knowledge-base" / "specs"))

    def test_the_control_fixture_really_does_fire(self):
        """The fixture is live: parked anywhere ordinary, it is worth both findings."""
        kinds = _kinds(self._orphan_feature_under("features/auth"))
        self.assertEqual(kinds & ORPHAN_KINDS, ORPHAN_KINDS)

    def test_no_feature_file_under_a_skipped_directory_is_scanned(self):
        self.assertTrue(SKIP_DIRS, "an empty registry would make this table vacuous")
        for directory in sorted(SKIP_DIRS):
            with self.subTest(directory=directory):
                errors = self._orphan_feature_under(directory)
                self.assertEqual(
                    _kinds(errors) & ORPHAN_KINDS, set(),
                    "the reverse scan descended into %s/: %s" % (directory, errors))


if __name__ == "__main__":
    unittest.main(verbosity=2)
