#!/usr/bin/env python3
"""Proof suite for the behavior adapters (adapters.py).

Run:  python test_adapters.py
"""

import os
import shutil
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from adapters import (  # noqa: E402
    slugify,
    feature_locator,
    render_scenario_scaffold,
    render_feature_scaffold,
    extract_spec_tags,
    extract_behavior_tags,
    has_scaffold_marker,
    scenario_blocks,
    scenario_block_for,
    parse_locator,
    GHERKIN_ADAPTERS,
    SCAFFOLD_MARKER,
)
from frontmatter import KNOWN_ADAPTERS, validate_behaviors  # noqa: E402
from verify_links import verify  # noqa: E402


class TestSlugAndLocator(unittest.TestCase):
    def test_slugify(self):
        self.assertEqual(slugify("Successful passkey login"), "successful-passkey-login")
        self.assertEqual(slugify("  Trim & punctuate!! "), "trim-punctuate")

    def test_feature_locator(self):
        self.assertEqual(
            feature_locator("auth", "passkey-login", "Successful passkey login"),
            "features/auth/passkey-login.feature#successful-passkey-login",
        )

    def test_parse_locator_gherkin(self):
        path, frag = parse_locator("features/auth/passkey-login.feature#successful-passkey-login")
        self.assertEqual(path, "features/auth/passkey-login.feature")
        self.assertEqual(frag, "successful-passkey-login")

    def test_parse_locator_pytest(self):
        path, frag = parse_locator("tests/test_auth.py::test_passkey_login")
        self.assertEqual(path, "tests/test_auth.py")
        self.assertEqual(frag, "test_passkey_login")

    def test_parse_locator_no_fragment(self):
        path, frag = parse_locator("tests/auth.test.ts")
        self.assertEqual(path, "tests/auth.test.ts")
        self.assertIsNone(frag)


class TestGherkinScaffold(unittest.TestCase):
    def setUp(self):
        self.text = render_feature_scaffold(
            "SPEC-012",
            "Passkey Login",
            "knowledge-base/specs/auth/SPEC-012-passkey-login.md",
            [("BEH-007", "Successful passkey login"),
             ("BEH-008", "Rejected on bad credential")],
        )

    def test_has_required_spec_tag(self):
        self.assertEqual(extract_spec_tags(self.text), {"SPEC-012"})

    def test_has_required_behavior_tags(self):
        self.assertEqual(extract_behavior_tags(self.text), {"BEH-007", "BEH-008"})

    def test_has_scaffold_marker(self):
        self.assertTrue(has_scaffold_marker(self.text))

    def test_points_at_spec_for_intent(self):
        self.assertIn("knowledge-base/specs/auth/SPEC-012-passkey-login.md", self.text)

    def test_no_real_steps_only_placeholders(self):
        # Scaffolds carry placeholder steps, never concrete ones.
        self.assertIn("<initial state>", self.text)
        self.assertIn("<action>", self.text)
        self.assertIn("<expected outcome>", self.text)

    def test_valid_gherkin_shape(self):
        self.assertIn("Feature: Passkey Login", self.text)
        self.assertEqual(self.text.count("Scenario:"), 2)

    def test_single_scenario_scaffold(self):
        s = render_scenario_scaffold("BEH-007", "Successful passkey login")
        self.assertIn("@BEH-007", s)
        self.assertIn("Scenario: Successful passkey login", s)
        self.assertIn(SCAFFOLD_MARKER, s)


class TestRealFeatureHasNoMarker(unittest.TestCase):
    def test_filled_feature_reports_no_marker(self):
        real = (
            "@SPEC-012\nFeature: Passkey Login\n\n"
            "  @BEH-007\n  Scenario: Successful passkey login\n"
            "    Given a registered passkey\n    When the user authenticates\n"
            "    Then they are logged in\n"
        )
        self.assertFalse(has_scaffold_marker(real))
        self.assertEqual(extract_behavior_tags(real), {"BEH-007"})


class TestScenarioScoping(unittest.TestCase):
    # One file, one authored (BEH-007, no marker) and one scaffold (BEH-008, marker).
    MIXED = (
        "@SPEC-012\nFeature: Passkey Login\n\n"
        "  @BEH-007\n  Scenario: Successful passkey login\n"
        "    Given a registered passkey\n    When the user authenticates\n"
        "    Then they are logged in\n\n"
        "  @BEH-008\n  Scenario: Rejected on bad credential\n"
        "    # TODO(scaffold): replace with real steps. Step definitions are not generated.\n"
        "    Given <initial state>\n    When <action>\n    Then <expected outcome>\n"
    )

    def test_splits_into_two_blocks(self):
        blocks = scenario_blocks(self.MIXED)
        self.assertEqual(len(blocks), 2)
        self.assertEqual(blocks[0][0], {"BEH-007"})
        self.assertEqual(blocks[1][0], {"BEH-008"})

    def test_authored_block_has_no_marker(self):
        block = scenario_block_for(self.MIXED, "BEH-007")
        self.assertIsNotNone(block)
        self.assertFalse(has_scaffold_marker(block))

    def test_scaffold_block_has_marker(self):
        block = scenario_block_for(self.MIXED, "BEH-008")
        self.assertTrue(has_scaffold_marker(block))

    def test_whole_file_still_has_marker(self):
        # The file-level helper sees BEH-008's marker — which is why the check
        # must be scenario-scoped, not file-scoped.
        self.assertTrue(has_scaffold_marker(self.MIXED))

    def test_unknown_behavior_returns_none(self):
        self.assertIsNone(scenario_block_for(self.MIXED, "BEH-999"))


LOCATOR = "features/auth/login.feature#successful-login"

# No tags at all. For a Gherkin adapter both reverse links are missing; for a
# native adapter the same file is just an opaque test artifact.
FEATURE_UNTAGGED = (
    "Feature: Login\n"
    "\n"
    "  Scenario: Successful login\n"
    "    Given a registered user\n"
    "    When they authenticate\n"
    "    Then they are logged in\n"
)
# Fully tagged, so the only thing left to object to is the unfilled marker.
FEATURE_SCAFFOLD = (
    "@SPEC-001\n"
    "Feature: Login\n"
    "\n"
    "  @BEH-001\n"
    "  Scenario: Successful login\n"
    f"    # {SCAFFOLD_MARKER}: replace with real steps. Step definitions are not generated.\n"
    "    Given <initial state>\n"
    "    When <action>\n"
    "    Then <expected outcome>\n"
)


def _spec_text(adapter, state, locator=LOCATOR):
    return (
        "---\n"
        "id: SPEC-001\n"
        "title: Login\n"
        "category: auth\n"
        "status: implemented\n"
        "certainty: 90\n"
        "created: 2026-06-24\n"
        "updated: 2026-06-24\n"
        "related_code:\n"
        "  - src/x.ts\n"
        "behaviors:\n"
        "  - behavior_id: BEH-001\n"
        "    title: Successful login\n"
        f"    state: {state}\n"
        f"    adapter: {adapter}\n"
        f"    locator: {locator}\n"
        "---\n\n"
        "# SPEC-001\n"
    )


class GherkinAdapterRegistryTest(unittest.TestCase):
    """Table over `GHERKIN_ADAPTERS` — 3 declared, 0 of them named until now.

    Membership is not decoration: it is what makes `verify_links` demand the
    `@SPEC-NNN` / `@BEH-NNN` reverse tags and refuse an `accepted` behavior that
    is still sitting on a `TODO(scaffold)` marker. A fourth adapter added to the
    tuple tomorrow is exercised by these rows the moment it lands.

    Every row uses the *same* fixture and varies only the adapter name, so a
    green row is membership doing the work and nothing else — the native control
    below runs the identical bytes and comes back clean.

    `GHERKIN_ADAPTERS` is imported by value above on purpose. That leaves the
    rows driven by the real tuple while a mutation run can empty the copy the
    consumer reads (`verify_links.GHERKIN_ADAPTERS`) and watch every row go red
    by name, instead of silently iterating an empty registry.
    """

    NATIVE_ADAPTER = "vitest"  # known, deliberately not a Gherkin adapter

    def _project(self, adapter, feature_text, state="accepted"):
        """Build a one-spec, one-feature project and return verify()'s errors."""
        root = Path(tempfile.mkdtemp())
        self.addCleanup(lambda: shutil.rmtree(root, ignore_errors=True))
        spec = root / "knowledge-base/specs/auth/SPEC-001-login.md"
        spec.parent.mkdir(parents=True, exist_ok=True)
        spec.write_text(_spec_text(adapter, state), encoding="utf-8")
        feature = root / "features/auth/login.feature"
        feature.parent.mkdir(parents=True, exist_ok=True)
        feature.write_text(feature_text, encoding="utf-8")
        return verify(str(root / "knowledge-base" / "specs"))

    @staticmethod
    def _kinds(errors):
        return {e["kind"] for e in errors}

    def test_the_registry_is_not_empty(self):
        """Non-vacuity guard. Emptying the tuple would leave every table below
        looping over nothing and passing, which is the failure mode these tables
        exist to remove."""
        self.assertTrue(GHERKIN_ADAPTERS,
                        "GHERKIN_ADAPTERS is empty — the tables below assert nothing")

    def test_every_member_gets_reverse_tag_checking(self):
        for adapter in GHERKIN_ADAPTERS:
            with self.subTest(adapter=adapter):
                kinds = self._kinds(self._project(adapter, FEATURE_UNTAGGED))
                self.assertIn("missing-reverse-tag", kinds)
                self.assertIn("missing-spec-tag", kinds)

    def test_every_member_blocks_an_accepted_behavior_still_on_a_scaffold(self):
        for adapter in GHERKIN_ADAPTERS:
            with self.subTest(adapter=adapter):
                self.assertIn(
                    "accepted-but-scaffold",
                    self._kinds(self._project(adapter, FEATURE_SCAFFOLD, state="accepted")),
                )

    def test_every_member_leaves_a_proposed_scaffold_alone(self):
        """The other half of the rule: a scaffold is what `proposed` is supposed
        to look like, so the marker is only an error once the behavior claims to
        be authoritative."""
        for adapter in GHERKIN_ADAPTERS:
            with self.subTest(adapter=adapter):
                errors = self._project(adapter, FEATURE_SCAFFOLD, state="proposed")
                self.assertEqual(errors, [], f"expected clean, got {errors}")

    def test_every_member_is_an_adapter_frontmatter_will_accept(self):
        """A Gherkin adapter that `frontmatter` does not know is a spec that
        cannot validate and a behavior that still gets the Gherkin treatment —
        two registries disagreeing about the same word."""
        for adapter in GHERKIN_ADAPTERS:
            with self.subTest(adapter=adapter):
                errors = validate_behaviors([{
                    "behavior_id": "BEH-001",
                    "title": "Successful login",
                    "state": "accepted",
                    "adapter": adapter,
                    "locator": LOCATOR,
                }])
                self.assertEqual(errors, [], f"expected clean, got {errors}")

    def test_a_native_adapter_gets_none_of_the_gherkin_treatment(self):
        """The control that makes the rows above mean something: byte-identical
        fixture, non-member adapter, no complaint. A native adapter links a test
        in place — it never promised the file was tagged."""
        self.assertNotIn(self.NATIVE_ADAPTER, GHERKIN_ADAPTERS)
        self.assertIn(self.NATIVE_ADAPTER, KNOWN_ADAPTERS)
        errors = self._project(self.NATIVE_ADAPTER, FEATURE_UNTAGGED)
        self.assertEqual(errors, [], f"expected clean, got {errors}")

    def test_a_native_adapter_is_not_blocked_by_a_scaffold_marker(self):
        errors = self._project(self.NATIVE_ADAPTER, FEATURE_SCAFFOLD, state="accepted")
        self.assertNotIn("accepted-but-scaffold", self._kinds(errors))


if __name__ == "__main__":
    unittest.main(verbosity=2)
