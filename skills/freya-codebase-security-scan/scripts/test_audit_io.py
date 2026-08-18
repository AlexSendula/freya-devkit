#!/usr/bin/env python3
"""Unit tests for audit JSON extraction and schema validation."""

import json
import unittest

import audit_io


def finding(**over):
    f = {
        "category": "injection", "severity": "high", "title": "SQLi",
        "description": "concatenated query", "file": "src/db.js", "line": 42,
        "recommendation": "parameterize",
    }
    f.update(over)
    return f


class ExtractTest(unittest.TestCase):
    def test_bare_json(self):
        self.assertEqual(audit_io.extract_json('{"findings": []}'), {"findings": []})

    def test_fenced_json(self):
        self.assertEqual(
            audit_io.extract_json('```json\n{"findings": []}\n```'), {"findings": []})

    def test_fenced_without_language(self):
        self.assertEqual(audit_io.extract_json('```\n{"findings": []}\n```'), {"findings": []})

    def test_narration_before_json_is_salvaged(self):
        """Copilot prefixes prose; the spike proved this needs salvage-extraction."""
        text = 'I scanned the files and found one issue.\n\n{"findings": [1]}'
        self.assertEqual(audit_io.extract_json(text), {"findings": [1]})

    def test_narration_after_json_is_ignored(self):
        self.assertEqual(
            audit_io.extract_json('{"findings": []}\n\nLet me know if you want more.'),
            {"findings": []})

    def test_nested_braces_are_balanced_correctly(self):
        text = 'Result:\n{"findings": [{"file": "a.js", "meta": {"x": 1}}]}\ndone'
        self.assertEqual(audit_io.extract_json(text)["findings"][0]["meta"], {"x": 1})

    def test_brace_inside_a_string_does_not_end_the_object(self):
        text = 'x {"findings": [], "note": "a } brace"} y'
        self.assertEqual(audit_io.extract_json(text)["note"], "a } brace")

    def test_unparseable_returns_none(self):
        self.assertIsNone(audit_io.extract_json("I could not complete the scan."))

    def test_empty_returns_none(self):
        self.assertIsNone(audit_io.extract_json(""))


class TwoObjectsTest(unittest.TestCase):
    """The silent-wrong-result shape. Extraction returned the FIRST object that
    parsed, so a worker that showed the output format before answering had its
    own example handed back as its answer — and `{"findings": []}` is itself
    FINDER_SCHEMA-valid, so validation passed, the task counted as answered, no
    retry fired, and a critical finding vanished into an exit-0 clean report."""

    ANSWER = {"findings": [finding()]}

    def test_a_format_example_before_the_answer_is_not_the_answer(self):
        text = ('I scanned the repository. If nothing new had been found I would '
                'return {"findings": []}. Here is what I found:\n\n'
                + json.dumps(self.ANSWER))
        self.assertEqual(audit_io.extract_json(text, audit_io.FINDER_SCHEMA),
                         self.ANSWER)

    def test_the_same_shape_across_two_fences(self):
        text = ('Output format:\n```json\n{"findings": []}\n```\n'
                'My answer:\n```json\n' + json.dumps(self.ANSWER) + '\n```')
        self.assertEqual(audit_io.extract_json(text, audit_io.FINDER_SCHEMA),
                         self.ANSWER)

    def test_an_echoed_schema_does_not_burn_both_attempts(self):
        """`ask` appends the schema to every prompt, so a worker echoing it back
        above its answer is the likeliest two-object response of all. It parses
        but does not validate, so it used to fail the attempt outright."""
        text = ('```json\n' + json.dumps(audit_io.FINDER_SCHEMA) + '\n```\n'
                '```json\n' + json.dumps(self.ANSWER) + '\n```')
        self.assertEqual(audit_io.extract_json(text, audit_io.FINDER_SCHEMA),
                         self.ANSWER)

    def test_trailing_chatter_cannot_outrank_a_fenced_answer(self):
        """The mirror image must stay shut: plain last-wins would let an
        afterthought replace the answer the worker actually marked as one."""
        text = ('```json\n' + json.dumps(self.ANSWER) + '\n```\n'
                'For reference, an empty result looks like {"findings": []}.')
        self.assertEqual(audit_io.extract_json(text, audit_io.FINDER_SCHEMA),
                         self.ANSWER)

    def test_without_a_schema_the_first_object_still_wins(self):
        """The schema-less callers must be unchanged: with nothing to validate
        against there is no way to tell an example from an answer."""
        text = '{"findings": []}\n\nand also ' + json.dumps(self.ANSWER)
        self.assertEqual(audit_io.extract_json(text), {"findings": []})

    def test_nothing_valid_still_yields_an_object_to_complain_about(self):
        """`ask` needs a SchemaError naming the failing path, not the useless
        'no JSON object in the response'."""
        got = audit_io.extract_json('{"findings": [{"category": "telepathy"}]}',
                                    audit_io.FINDER_SCHEMA)
        self.assertEqual(got, {"findings": [{"category": "telepathy"}]})

    def test_a_verdict_is_picked_by_its_own_schema(self):
        answer = {"lens": "spec-intentional", "verdict": "refuted",
                  "reason": "specified", "specReference": "SPEC-007"}
        text = ('A verdict looks like {"lens": "exploitability", "verdict": '
                '"upheld", "reason": "example"}. Mine:\n' + json.dumps(answer))
        self.assertEqual(audit_io.extract_json(text, audit_io.VERDICT_SCHEMA),
                         answer)

    def test_the_salvage_scanner_gives_up_on_a_pathological_response(self):
        """A `{` that never balances makes its scan run to the end of the text,
        and restarting at every following `{` is quadratic — measured at 6.9s
        for a 433KB response, burned on a pool thread `--timeout` does not
        cover. Past the bound the response is unusable, which `ask` retries."""
        noise = "{ " * (audit_io._MAX_SCAN_STARTS + 5)
        self.assertIsNone(audit_io.extract_json(noise + '{"findings": []}'))


class ValidateTest(unittest.TestCase):
    def test_valid_finder_payload(self):
        audit_io.validate({"findings": [finding()]}, audit_io.FINDER_SCHEMA)

    def test_empty_findings_is_valid(self):
        audit_io.validate({"findings": []}, audit_io.FINDER_SCHEMA)

    def test_missing_required_key_raises(self):
        with self.assertRaises(audit_io.SchemaError):
            audit_io.validate({}, audit_io.FINDER_SCHEMA)

    def test_missing_required_field_in_item_raises(self):
        bad = finding()
        del bad["file"]
        with self.assertRaises(audit_io.SchemaError):
            audit_io.validate({"findings": [bad]}, audit_io.FINDER_SCHEMA)

    def test_unknown_category_raises(self):
        with self.assertRaises(audit_io.SchemaError):
            audit_io.validate({"findings": [finding(category="telepathy")]},
                              audit_io.FINDER_SCHEMA)

    def test_unknown_severity_raises(self):
        with self.assertRaises(audit_io.SchemaError):
            audit_io.validate({"findings": [finding(severity="apocalyptic")]},
                              audit_io.FINDER_SCHEMA)

    def test_additional_property_raises(self):
        with self.assertRaises(audit_io.SchemaError):
            audit_io.validate({"findings": [finding(sneaky="x")]}, audit_io.FINDER_SCHEMA)

    def test_wrong_type_raises(self):
        with self.assertRaises(audit_io.SchemaError):
            audit_io.validate({"findings": finding()}, audit_io.FINDER_SCHEMA)

    def test_line_must_be_integer(self):
        with self.assertRaises(audit_io.SchemaError):
            audit_io.validate({"findings": [finding(line="42")]}, audit_io.FINDER_SCHEMA)

    def test_negative_line_raises(self):
        with self.assertRaises(audit_io.SchemaError):
            audit_io.validate({"findings": [finding(line=-1)]}, audit_io.FINDER_SCHEMA)

    def test_bool_is_not_a_valid_line(self):
        """bool is a subclass of int in Python; the schema never wants one."""
        with self.assertRaises(audit_io.SchemaError):
            audit_io.validate({"findings": [finding(line=True)]}, audit_io.FINDER_SCHEMA)

    def test_optional_fields_are_allowed(self):
        audit_io.validate({"findings": [finding(cwe="CWE-89", codeSnippet="q + s")]},
                          audit_io.FINDER_SCHEMA)

    def test_valid_verdict(self):
        audit_io.validate({"lens": "exploitability", "verdict": "upheld", "reason": "r"},
                          audit_io.VERDICT_SCHEMA)

    def test_unknown_lens_raises(self):
        with self.assertRaises(audit_io.SchemaError):
            audit_io.validate({"lens": "vibes", "verdict": "upheld", "reason": "r"},
                              audit_io.VERDICT_SCHEMA)

    def test_unknown_verdict_raises(self):
        with self.assertRaises(audit_io.SchemaError):
            audit_io.validate({"lens": "exploitability", "verdict": "maybe", "reason": "r"},
                              audit_io.VERDICT_SCHEMA)

    def test_error_names_the_failing_path(self):
        bad = finding()
        del bad["file"]
        with self.assertRaises(audit_io.SchemaError) as ctx:
            audit_io.validate({"findings": [bad]}, audit_io.FINDER_SCHEMA)
        self.assertIn("findings[0]", str(ctx.exception))


class ConstantsTest(unittest.TestCase):
    def test_categories_match_the_retired_workflow(self):
        self.assertEqual(audit_io.CATEGORIES,
                         ["auth", "injection", "secrets", "api", "config", "file"])

    def test_skeptics_match_the_retired_workflow(self):
        self.assertEqual(audit_io.SKEPTICS,
                         ["exploitability", "compensating-controls", "spec-intentional"])


if __name__ == "__main__":
    unittest.main()
