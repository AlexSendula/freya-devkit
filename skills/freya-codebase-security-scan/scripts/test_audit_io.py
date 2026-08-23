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


#: The triage order every consumer reads off SEVERITIES' *position*: what the
#: report leads with, what `freya status` counts as open first, where the
#: `--max-calls` budget goes. Declared as literals on purpose — deriving these
#: from audit_io.SEVERITIES would adapt to a reordering of it and prove
#: nothing, the "literals, not the constants under test" rule this suite states
#: at test_audit_engine.py:180. A severity added to the registry with no entry
#: here is a severity nobody has decided how to triage, and the table below
#: says so by name.
TRIAGE_RANK = {"critical": 0, "high": 1, "medium": 2, "low": 3, "info": 4}

#: Severities agent CLIs actually emit that this vocabulary does not contain —
#: wrong case, a neighbouring taxonomy, a ticket priority, an empty field. Each
#: must be rejected *loudly*. An unrecognised severity that silently sorts to
#: the middle, or silently counts as zero, is the collect_status.py:150 /
#: ADR-005 failure: a real finding that the report never leads with and that
#: nothing tells the operator was dropped.
OUT_OF_VOCABULARY = ["apocalyptic", "CRITICAL", "High", "Critical", "sev1",
                     "moderate", "severe", "warning", "none", "P0", "unknown", ""]


def _report_order(findings):
    """Rank findings the way a consumer of the vocabulary has to: by the
    registry's *position*. Report lead, `freya status` and the scan budget all
    read severity this way, which is what makes the order of SEVERITIES
    behaviour rather than decoration."""
    return sorted(findings, key=lambda f: audit_io.SEVERITIES.index(f["severity"]))


class SeverityVocabularyTest(unittest.TestCase):
    """Driven off audit_io.SEVERITIES, so a severity added tomorrow is
    exercised the moment it is added rather than covered by nothing."""

    def test_every_severity_has_a_declared_triage_rank(self):
        """The gate that makes the rest of this class self-extending: a new
        member of the registry cannot land without someone deciding where it
        triages, and the failure names the member."""
        for severity in audit_io.SEVERITIES:
            with self.subTest(severity=severity):
                self.assertIn(severity, TRIAGE_RANK,
                              f"{severity!r} is declared but has no triage rank")

    def test_every_triaged_severity_is_still_declared(self):
        """The other direction, and the reason it is here: every table in this
        class iterates the registry, so an emptied or shrunken SEVERITIES makes
        all of them vacuously green — measured, by emptying it. This row is
        driven off the literals instead, so a severity dropped from the
        vocabulary goes red by name rather than quietly ceasing to be tested."""
        for severity in TRIAGE_RANK:
            with self.subTest(severity=severity):
                self.assertIn(severity, audit_io.SEVERITIES)

    def test_each_severity_outranks_the_next(self):
        """The ordering itself, pair by pair, against literals. Membership
        cannot see an ordering bug: swapping two members leaves the set
        identical while the report starts leading with the wrong finding."""
        for higher, lower in zip(audit_io.SEVERITIES, audit_io.SEVERITIES[1:]):
            with self.subTest(above=higher, below=lower):
                self.assertLess(TRIAGE_RANK[higher], TRIAGE_RANK[lower],
                                f"{higher} must triage above {lower}")

    def test_no_severity_is_declared_twice(self):
        """Position is the rank, so a duplicate gives one severity two ranks
        and `.index` silently returns the first."""
        self.assertEqual(len(set(audit_io.SEVERITIES)), len(audit_io.SEVERITIES))

    def test_a_mixed_report_leads_with_the_worst(self):
        """The consequence of the order, end to end. The input is built from
        the registry (reversed, so the sort has real work) and the expected
        result is a literal — a reordered registry produces a differently
        ordered report and this goes red. Alphabetical ranking, the likeliest
        wrong key, would put info second."""
        scrambled = [finding(severity=s, title=s)
                     for s in reversed(audit_io.SEVERITIES)]
        self.assertEqual([f["title"] for f in _report_order(scrambled)],
                         ["critical", "high", "medium", "low", "info"])

    def test_every_severity_validates_through_the_finder_schema(self):
        """Each declared severity is one a worker may actually return. A
        severity in the registry that the schema rejects is a finding the
        driver throws away as malformed."""
        for severity in audit_io.SEVERITIES:
            with self.subTest(severity=severity):
                audit_io.validate({"findings": [finding(severity=severity)]},
                                  audit_io.FINDER_SCHEMA)

    def test_a_finding_at_any_severity_outranks_an_empty_example(self):
        """The TwoObjectsTest shape, per severity: selection is schema-driven,
        so a severity the schema does not accept loses to the worker's own
        `{"findings": []}` example and the finding vanishes into a clean
        report — silently, because the example is itself valid."""
        for severity in audit_io.SEVERITIES:
            with self.subTest(severity=severity):
                answer = {"findings": [finding(severity=severity)]}
                text = ('If I had found nothing I would return '
                        '{"findings": []}. Here is what I found:\n'
                        + json.dumps(answer))
                self.assertEqual(
                    audit_io.extract_json(text, audit_io.FINDER_SCHEMA), answer)


class OutOfVocabularySeverityTest(unittest.TestCase):
    """What happens to a severity the registry does not declare. Silence is
    the failure mode: the schema is the only thing standing between an
    unrecognised severity and a ranker that would place it by guesswork."""

    def test_the_fixture_stays_out_of_vocabulary(self):
        """Guards the table below against the registry growing into it."""
        for severity in OUT_OF_VOCABULARY:
            with self.subTest(severity=severity):
                self.assertNotIn(severity, audit_io.SEVERITIES)

    def test_an_unknown_severity_is_rejected_not_absorbed(self):
        for severity in OUT_OF_VOCABULARY:
            with self.subTest(severity=severity):
                with self.assertRaises(audit_io.SchemaError):
                    audit_io.validate({"findings": [finding(severity=severity)]},
                                      audit_io.FINDER_SCHEMA)

    def test_the_rejection_names_the_field_the_value_and_the_vocabulary(self):
        """`ask` reports this string to the operator. "invalid payload" is the
        note that never gets acted on; the path, the offending value and the
        accepted set are what makes a dropped finding visible."""
        for severity in OUT_OF_VOCABULARY:
            with self.subTest(severity=severity):
                with self.assertRaises(audit_io.SchemaError) as ctx:
                    audit_io.validate({"findings": [finding(severity=severity)]},
                                      audit_io.FINDER_SCHEMA)
                self.assertEqual(ctx.exception.path, "findings[0].severity")
                message = str(ctx.exception)
                self.assertIn(repr(severity), message)
                self.assertIn("critical", message)

    def test_an_unknown_severity_never_wins_selection(self):
        """The extraction-level consequence, and the reason rejection has to be
        loud at all: if an out-of-vocabulary finding validated, it would be the
        last valid candidate and would be handed back as the answer."""
        for severity in OUT_OF_VOCABULARY:
            with self.subTest(severity=severity):
                text = (json.dumps({"findings": []})
                        + "\n\nOn reflection:\n"
                        + json.dumps({"findings": [finding(severity=severity)]}))
                self.assertEqual(
                    audit_io.extract_json(text, audit_io.FINDER_SCHEMA),
                    {"findings": []})

    def test_a_numeric_severity_is_not_a_severity(self):
        """Ordinal severities (1..5) are a real neighbouring convention; the
        type check has to catch them before the enum check would."""
        with self.assertRaises(audit_io.SchemaError) as ctx:
            audit_io.validate({"findings": [finding(severity=1)]},
                              audit_io.FINDER_SCHEMA)
        self.assertEqual(ctx.exception.path, "findings[0].severity")


class CategoryVocabularyTest(unittest.TestCase):
    """ConstantsTest pins the membership of CATEGORIES and SKEPTICS against the
    retired workflow. These pin what each member *does*, so a seventh category
    is exercised rather than merely listed."""

    def test_every_category_validates_through_the_finder_schema(self):
        for category in audit_io.CATEGORIES:
            with self.subTest(category=category):
                audit_io.validate({"findings": [finding(category=category)]},
                                  audit_io.FINDER_SCHEMA)

    def test_a_finding_in_any_category_outranks_an_empty_example(self):
        for category in audit_io.CATEGORIES:
            with self.subTest(category=category):
                answer = {"findings": [finding(category=category)]}
                text = ('Output format: {"findings": []}\nMy answer:\n'
                        + json.dumps(answer))
                self.assertEqual(
                    audit_io.extract_json(text, audit_io.FINDER_SCHEMA), answer)

    def test_every_skeptic_lens_validates_through_the_verdict_schema(self):
        """A lens the verdict schema rejects is a skeptic whose verdict is
        discarded — which the aggregator counts as an unresolved claim."""
        for lens in audit_io.SKEPTICS:
            with self.subTest(lens=lens):
                audit_io.validate({"lens": lens, "verdict": "upheld", "reason": "r"},
                                  audit_io.VERDICT_SCHEMA)

    def test_every_skeptic_lens_can_both_uphold_and_refute(self):
        for lens in audit_io.SKEPTICS:
            for verdict in ["upheld", "refuted"]:
                with self.subTest(lens=lens, verdict=verdict):
                    answer = {"lens": lens, "verdict": verdict, "reason": "r"}
                    text = ('An example verdict is {"lens": "exploitability", '
                            '"verdict": "upheld", "reason": "example"}. Mine:\n'
                            + json.dumps(answer))
                    self.assertEqual(
                        audit_io.extract_json(text, audit_io.VERDICT_SCHEMA), answer)


if __name__ == "__main__":
    unittest.main()
