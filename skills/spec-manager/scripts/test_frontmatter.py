#!/usr/bin/env python3
"""
Proof suite for the scoped frontmatter parser (frontmatter.py).

This is the evidence that the substrate is reliable: it pins the exact grammar
the Behavior Layer depends on, and pins that anything outside the grammar
*fails loud* rather than silently dropping data — the bug class the old
hand-rolled parser had.

Run:  python test_frontmatter.py
"""

import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from frontmatter import (  # noqa: E402
    parse_frontmatter,
    validate,
    validate_behaviors,
    validate_adr,
    ADR_STATES,
    FrontmatterError,
    SCHEMA_VERSION,
)


class TestScalars(unittest.TestCase):
    def test_basic_scalars_and_body(self):
        fm, body = parse_frontmatter(
            "---\nid: SPEC-012\ntitle: Passkey Login\n---\n# Heading\n\nBody text.\n"
        )
        self.assertEqual(fm["id"], "SPEC-012")
        self.assertEqual(fm["title"], "Passkey Login")
        self.assertEqual(body, "# Heading\n\nBody text.\n")

    def test_bare_integer_coerced(self):
        fm, _ = parse_frontmatter("---\ncertainty: 90\n---\n")
        self.assertEqual(fm["certainty"], 90)
        self.assertIsInstance(fm["certainty"], int)

    def test_date_stays_string(self):
        fm, _ = parse_frontmatter("---\ncreated: 2026-06-24\n---\n")
        self.assertEqual(fm["created"], "2026-06-24")

    def test_quoted_strings(self):
        fm, _ = parse_frontmatter(
            "---\na: \"hello world\"\nb: 'single quoted'\n---\n"
        )
        self.assertEqual(fm["a"], "hello world")
        self.assertEqual(fm["b"], "single quoted")


class TestInlineArrays(unittest.TestCase):
    def test_inline_array_round_trips(self):
        # The exact bug the old parser had: this used to become a string, then dropped.
        fm, _ = parse_frontmatter(
            "---\ntags: [authentication, security, webauthn]\n---\n"
        )
        self.assertEqual(fm["tags"], ["authentication", "security", "webauthn"])

    def test_empty_inline_array(self):
        fm, _ = parse_frontmatter("---\ntags: []\n---\n")
        self.assertEqual(fm["tags"], [])

    def test_inline_array_with_quoted_comma(self):
        fm, _ = parse_frontmatter('---\ntags: ["a, b", c]\n---\n')
        self.assertEqual(fm["tags"], ["a, b", "c"])

    def test_unterminated_inline_array_raises(self):
        with self.assertRaises(FrontmatterError):
            parse_frontmatter("---\ntags: [a, b\n---\n")


class TestBlockSequences(unittest.TestCase):
    def test_indented_block_list(self):
        fm, _ = parse_frontmatter(
            "---\nrelated_code:\n  - src/lib/auth/passkeys.ts\n  - src/api/routes/auth.ts\n---\n"
        )
        self.assertEqual(
            fm["related_code"],
            ["src/lib/auth/passkeys.ts", "src/api/routes/auth.ts"],
        )

    def test_unindented_block_list(self):
        # YAML allows the dash at the parent's indent; we accept it too.
        fm, _ = parse_frontmatter(
            "---\nrelated_code:\n- src/a.ts\n- src/b.ts\n---\n"
        )
        self.assertEqual(fm["related_code"], ["src/a.ts", "src/b.ts"])

    def test_quoted_list_items(self):
        fm, _ = parse_frontmatter(
            '---\nintentional_decisions:\n  - "No password fallback (phishing vector)"\n---\n'
        )
        self.assertEqual(
            fm["intentional_decisions"],
            ["No password fallback (phishing vector)"],
        )


class TestListOfMappings(unittest.TestCase):
    SPEC = (
        "---\n"
        "id: SPEC-012\n"
        "behaviors:\n"
        "  - behavior_id: BEH-007\n"
        "    title: Successful passkey login\n"
        "    state: accepted\n"
        "    adapter: cucumber\n"
        "    locator: features/auth/passkey-login.feature#successful-passkey-login\n"
        "  - behavior_id: BEH-008\n"
        "    title: Rejected on bad credential\n"
        "    state: proposed\n"
        "---\n"
    )

    def test_behaviors_parse_into_list_of_dicts(self):
        fm, _ = parse_frontmatter(self.SPEC)
        self.assertEqual(len(fm["behaviors"]), 2)
        first = fm["behaviors"][0]
        self.assertEqual(first["behavior_id"], "BEH-007")
        self.assertEqual(first["title"], "Successful passkey login")
        self.assertEqual(first["state"], "accepted")
        self.assertEqual(first["adapter"], "cucumber")

    def test_locator_hash_is_preserved(self):
        # A '#' not preceded by whitespace is part of the value, not a comment.
        fm, _ = parse_frontmatter(self.SPEC)
        self.assertEqual(
            fm["behaviors"][0]["locator"],
            "features/auth/passkey-login.feature#successful-passkey-login",
        )

    def test_second_behavior_has_subset_of_fields(self):
        fm, _ = parse_frontmatter(self.SPEC)
        self.assertEqual(fm["behaviors"][1]["behavior_id"], "BEH-008")
        self.assertEqual(fm["behaviors"][1]["state"], "proposed")


class TestComments(unittest.TestCase):
    def test_full_line_comment_skipped(self):
        fm, _ = parse_frontmatter("---\n# a comment\nid: SPEC-001\n---\n")
        self.assertEqual(fm, {"id": "SPEC-001"})

    def test_inline_comment_stripped(self):
        fm, _ = parse_frontmatter("---\nbehavior_id: BEH-007   # stable across renames\n---\n")
        self.assertEqual(fm["behavior_id"], "BEH-007")

    def test_hash_without_leading_space_kept(self):
        fm, _ = parse_frontmatter("---\ncolor: #fff\n---\n")
        self.assertEqual(fm["color"], "#fff")


class TestMalformed(unittest.TestCase):
    def test_missing_closing_fence_raises(self):
        with self.assertRaises(FrontmatterError):
            parse_frontmatter("---\nid: SPEC-001\nno closing fence\n")

    def test_no_frontmatter_returns_empty(self):
        fm, body = parse_frontmatter("# Just a markdown file\n\nNo frontmatter here.\n")
        self.assertEqual(fm, {})
        self.assertEqual(body, "# Just a markdown file\n\nNo frontmatter here.\n")

    def test_empty_frontmatter_block(self):
        fm, body = parse_frontmatter("---\n---\nbody\n")
        self.assertEqual(fm, {})
        self.assertEqual(body, "body\n")

    def test_tab_indentation_raises(self):
        with self.assertRaises(FrontmatterError):
            parse_frontmatter("---\nrelated_code:\n\t- src/a.ts\n---\n")

    def test_orphan_sequence_item_raises(self):
        with self.assertRaises(FrontmatterError):
            parse_frontmatter("---\n- orphan\n---\n")

    def test_line_without_colon_raises(self):
        with self.assertRaises(FrontmatterError):
            parse_frontmatter("---\nthis is not a key value line\n---\n")


class TestUnknownFieldsPreserved(unittest.TestCase):
    def test_unknown_field_round_trips(self):
        fm, _ = parse_frontmatter("---\nid: SPEC-001\nfuture_field: keep me\n---\n")
        self.assertEqual(fm["future_field"], "keep me")


class TestValidate(unittest.TestCase):
    def test_valid_minimal_spec(self):
        fm = {"id": "SPEC-1", "title": "T", "category": "auth", "status": "draft"}
        self.assertEqual(validate(fm), [])

    def test_missing_required_reported(self):
        errors = validate({"id": "SPEC-1"})
        joined = " ".join(errors)
        self.assertIn("title", joined)
        self.assertIn("category", joined)
        self.assertIn("status", joined)

    def test_wrong_type_reported(self):
        fm = {"id": "SPEC-1", "title": "T", "category": "auth",
              "status": "draft", "tags": "not-a-list"}
        errors = validate(fm)
        self.assertTrue(any("tags" in e for e in errors))

    def test_unknown_field_not_an_error(self):
        fm = {"id": "SPEC-1", "title": "T", "category": "auth",
              "status": "draft", "future_field": "x"}
        self.assertEqual(validate(fm), [])

    def test_unsupported_schema_version(self):
        errors = validate({}, schema_version=SCHEMA_VERSION + 1)
        self.assertTrue(errors)
        self.assertIn("schema_version", errors[0])


def _beh(**overrides):
    """A valid behavior record, with field overrides for negative tests."""
    rec = {
        "behavior_id": "BEH-007",
        "title": "Successful passkey login",
        "state": "accepted",
        "adapter": "cucumber",
        "locator": "features/auth/passkey-login.feature#successful-passkey-login",
    }
    rec.update(overrides)
    return rec


class TestBehaviorValidation(unittest.TestCase):
    def test_valid_record(self):
        self.assertEqual(validate_behaviors([_beh()]), [])

    def test_valid_level_accepted(self):
        self.assertEqual(validate_behaviors([_beh(level="unit")]), [])

    def test_bad_level_rejected(self):
        errors = validate_behaviors([_beh(level="untit")])
        self.assertTrue(any("level" in e for e in errors))

    def test_no_level_or_entry_still_valid(self):
        # level/entry are optional — a record without them must stay valid.
        self.assertEqual(validate_behaviors([_beh()]), [])

    def test_valid_entry_accepted(self):
        self.assertEqual(
            validate_behaviors([_beh(level="integration", entry="app/api/x/route.ts")]), [])

    def test_non_string_entry_rejected(self):
        errors = validate_behaviors([_beh(entry=123)])
        self.assertTrue(any("entry" in e for e in errors))

    def test_full_spec_with_behaviors_validates(self):
        fm = {
            "id": "SPEC-012", "title": "Passkey Login", "category": "auth",
            "status": "implemented", "behaviors": [_beh()],
        }
        self.assertEqual(validate(fm), [])

    def test_bad_state_rejected(self):
        errors = validate_behaviors([_beh(state="authored")])
        self.assertTrue(any("state" in e for e in errors))

    def test_missing_state_rejected(self):
        rec = _beh()
        del rec["state"]
        errors = validate_behaviors([rec])
        self.assertTrue(any("state" in e for e in errors))

    def test_reused_id_flagged(self):
        errors = validate_behaviors([_beh(), _beh(title="Another")])
        self.assertTrue(any("duplicate behavior_id" in e for e in errors))

    def test_bad_id_format_rejected(self):
        errors = validate_behaviors([_beh(behavior_id="BEH-7")])
        self.assertTrue(any("BEH-NNN" in e for e in errors))

    def test_unknown_adapter_rejected(self):
        errors = validate_behaviors([_beh(adapter="rspec")])
        self.assertTrue(any("adapter" in e for e in errors))

    def test_missing_locator_for_non_manual_rejected(self):
        rec = _beh()
        del rec["locator"]
        errors = validate_behaviors([rec])
        self.assertTrue(any("locator" in e for e in errors))

    def test_manual_adapter_allows_missing_locator(self):
        rec = {"behavior_id": "BEH-009", "title": "Admin reviews audit log",
               "state": "accepted", "adapter": "manual"}
        self.assertEqual(validate_behaviors([rec]), [])

    def test_spec_id_mismatch_rejected(self):
        errors = validate_behaviors([_beh(spec_id="SPEC-999")], spec_id="SPEC-012")
        self.assertTrue(any("does not match parent" in e for e in errors))

    def test_spec_id_match_ok(self):
        self.assertEqual(
            validate_behaviors([_beh(spec_id="SPEC-012")], spec_id="SPEC-012"), []
        )

    def test_confirmed_state_is_valid(self):
        # A confirmed behavior that still carries adapter+locator is valid.
        self.assertEqual(validate_behaviors([_beh(state="confirmed")]), [])

    def test_confirmed_without_test_is_valid(self):
        # confirmed = intent confirmed, test owed: no adapter/locator required.
        rec = {"behavior_id": "BEH-010", "title": "Owes a test", "state": "confirmed"}
        self.assertEqual(validate_behaviors([rec]), [])

    def test_confirmed_with_entry_only_is_valid(self):
        rec = {"behavior_id": "BEH-010", "title": "Owes a test", "state": "confirmed",
               "level": "integration", "entry": "app/api/x/route.ts"}
        self.assertEqual(validate_behaviors([rec]), [])

    def test_proposed_without_test_is_valid(self):
        # A scan-inferred proposed candidate has no test yet either.
        rec = {"behavior_id": "BEH-011", "title": "Inferred candidate", "state": "proposed"}
        self.assertEqual(validate_behaviors([rec]), [])

    def test_confirmed_bad_adapter_when_present_rejected(self):
        rec = {"behavior_id": "BEH-010", "title": "x", "state": "confirmed", "adapter": "rspec"}
        self.assertTrue(any("adapter" in e for e in validate_behaviors([rec])))

    def test_confirmed_non_string_locator_when_present_rejected(self):
        rec = {"behavior_id": "BEH-010", "title": "x", "state": "confirmed", "locator": 123}
        self.assertTrue(any("locator" in e for e in validate_behaviors([rec])))

    def test_accepted_still_requires_adapter(self):
        rec = {"behavior_id": "BEH-012", "title": "x", "state": "accepted"}
        self.assertTrue(any("adapter" in e for e in validate_behaviors([rec])))

    def test_parsed_spec_round_trips_through_validate(self):
        # End-to-end: a hand-written spec parses into structured records that validate.
        fm, _ = parse_frontmatter(TestListOfMappings.SPEC + "")
        # TestListOfMappings.SPEC has no required spec fields beyond id; validate
        # the behaviors list directly.
        self.assertIsInstance(fm["behaviors"], list)
        errors = validate_behaviors(fm["behaviors"], fm.get("id"))
        # BEH-008 in that fixture is 'proposed' with adapter/locator absent. A
        # pre-test state needs neither, so it now validates cleanly; assert the
        # parse produced the right shape and the first (accepted) record is clean.
        self.assertEqual(fm["behaviors"][0]["behavior_id"], "BEH-007")
        self.assertFalse(any("behaviors[0]" in e for e in errors))


class ADRSchemaCase(unittest.TestCase):
    def test_stray_behaviors_key_not_behavior_validated(self):
        # An ADR is not a spec: a stray malformed `behaviors` value must NOT
        # trigger behavior validation via validate_adr (ADR_SCHEMA has no such field).
        fm = {"id": "ADR-001", "title": "X", "status": "accepted",
              "behaviors": [{"nonsense": True}]}
        errs = validate_adr(fm)
        self.assertFalse(any("behavior" in e.lower() for e in errs))

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


if __name__ == "__main__":
    unittest.main(verbosity=2)
