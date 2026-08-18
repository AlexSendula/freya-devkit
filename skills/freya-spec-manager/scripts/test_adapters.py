#!/usr/bin/env python3
"""Proof suite for the behavior adapters (adapters.py).

Run:  python test_adapters.py
"""

import os
import sys
import unittest

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
    SCAFFOLD_MARKER,
)


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


if __name__ == "__main__":
    unittest.main(verbosity=2)
