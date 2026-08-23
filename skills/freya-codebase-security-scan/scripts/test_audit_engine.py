#!/usr/bin/env python3
"""Unit tests for the audit engine. No agent is ever called."""

import os
import shutil
import tempfile
import unittest

import audit_engine


SEQUENTIAL = lambda thunks: [t() for t in thunks]


def finding(file="a.js", line=10, category="injection", **over):
    f = {
        "category": category, "severity": "high", "title": "t", "description": "d",
        "file": file, "line": line, "recommendation": "r",
    }
    f.update(over)
    return f


def verdicts(*pairs):
    return [{"lens": lens, "verdict": v, "reason": "r"} for lens, v in pairs]


def cited(reference="SPEC-007"):
    """A spec-intentional refutation that actually points at a spec."""
    return {"lens": "spec-intentional", "verdict": "refuted", "reason": "r",
            "specReference": reference}


class DedupKeyTest(unittest.TestCase):
    def test_same_file_window_and_category_collapse(self):
        self.assertEqual(audit_engine.dedup_key(finding(line=10)),
                         audit_engine.dedup_key(finding(line=14)))

    def test_next_window_is_distinct(self):
        self.assertNotEqual(audit_engine.dedup_key(finding(line=10)),
                            audit_engine.dedup_key(finding(line=15)))

    def test_different_category_is_distinct(self):
        self.assertNotEqual(audit_engine.dedup_key(finding(category="auth")),
                            audit_engine.dedup_key(finding(category="secrets")))

    def test_different_file_is_distinct(self):
        self.assertNotEqual(audit_engine.dedup_key(finding(file="a.js")),
                            audit_engine.dedup_key(finding(file="b.js")))

    def test_matches_the_retired_workflow_format(self):
        self.assertEqual(audit_engine.dedup_key(finding(file="src/x.js", line=42,
                                                        category="api")),
                         "src/x.js::8::api")


class DispositionTest(unittest.TestCase):
    def test_a_cited_spec_refute_outranks_a_majority_upheld(self):
        d, ref, _ = audit_engine.disposition(
            verdicts(("exploitability", "upheld"),
                     ("compensating-controls", "upheld")) + [cited()])
        self.assertEqual(d, "intentional-design")  # spec refute wins over majority
        self.assertEqual(ref, "SPEC-007")

    def test_an_uncited_spec_refute_does_not_claim_intentional_design(self):
        """`intentional-design` asserts a design decision. Without a spec to
        point at there is nothing to assert, and the finding was reported as
        specified behaviour with `specReference: null` beside it."""
        d, ref, _ = audit_engine.disposition(verdicts(
            ("exploitability", "upheld"), ("compensating-controls", "upheld"),
            ("spec-intentional", "refuted")))
        self.assertEqual((d, ref), ("confirmed", None))

    def test_a_blank_spec_reference_does_not_count_as_a_citation(self):
        d, _, _ = audit_engine.disposition(
            verdicts(("exploitability", "upheld")) + [cited("   ")])
        self.assertNotEqual(d, "intentional-design")

    def test_a_unanimous_refute_including_spec_is_dropped_not_intentional(self):
        """The whole documented `drop` path was unreachable whenever all three
        lenses answered: a unanimous refutation always contains a spec-lens
        refutation, which short-circuited to `intentional-design` — so a finding
        every skeptic rejected was reported as a design decision, uncited."""
        d, ref, _ = audit_engine.disposition(verdicts(
            ("exploitability", "refuted"), ("compensating-controls", "refuted"),
            ("spec-intentional", "refuted")))
        self.assertEqual((d, ref), ("drop", None))

    def test_a_cited_unanimous_refute_is_still_intentional_design(self):
        """The citation is the difference. Unanimity does not delete a spec."""
        d, ref, _ = audit_engine.disposition(
            verdicts(("exploitability", "refuted"),
                     ("compensating-controls", "refuted")) + [cited("SPEC-012")])
        self.assertEqual((d, ref), ("intentional-design", "SPEC-012"))

    def test_two_of_three_upheld_without_spec_refute_is_confirmed(self):
        d, _, v = audit_engine.disposition(verdicts(
            ("exploitability", "upheld"), ("compensating-controls", "upheld"),
            ("spec-intentional", "upheld")))
        self.assertEqual(d, "confirmed")
        self.assertEqual(v, {"upheld": 3, "total": 3, "lenses": audit_engine.SKEPTICS})

    def test_one_of_two_upheld_is_needs_review(self):
        """Pins `upheld * 2 > total`. With >= this would wrongly be confirmed."""
        d, _, _ = audit_engine.disposition(verdicts(
            ("exploitability", "upheld"), ("compensating-controls", "refuted")))
        self.assertEqual(d, "needs-review")

    def test_unanimous_refute_is_dropped(self):
        d, _, _ = audit_engine.disposition(verdicts(
            ("exploitability", "refuted"), ("compensating-controls", "refuted")))
        self.assertEqual(d, "drop")

    def test_majority_with_one_refute_is_confirmed(self):
        d, _, _ = audit_engine.disposition(verdicts(
            ("exploitability", "upheld"), ("compensating-controls", "refuted"),
            ("spec-intentional", "upheld")))
        self.assertEqual(d, "confirmed")  # 2 of 3 -> majority

    def test_one_of_three_upheld_is_needs_review(self):
        """spec-intentional must be UPHELD here: refuted *with a citation* and
        the spec branch would win instead."""
        d, _, _ = audit_engine.disposition(verdicts(
            ("exploitability", "refuted"), ("compensating-controls", "refuted"),
            ("spec-intentional", "upheld")))
        self.assertEqual(d, "needs-review")

    def test_spec_reference_is_carried_out(self):
        vs = verdicts(("exploitability", "upheld"))
        vs.append({"lens": "spec-intentional", "verdict": "refuted",
                   "reason": "r", "specReference": "SPEC-007"})
        d, ref, _ = audit_engine.disposition(vs)
        self.assertEqual((d, ref), ("intentional-design", "SPEC-007"))

    def test_lenses_names_only_the_lenses_that_answered(self):
        """`lenses` used to be the module constant, so a finding whose
        exploitability call timed out still reported all three — the report
        described a verification that did not happen."""
        _, _, v = audit_engine.disposition(verdicts(
            ("compensating-controls", "upheld"), ("spec-intentional", "upheld")))
        self.assertEqual(v["lenses"], ["compensating-controls", "spec-intentional"])
        self.assertEqual(v["total"], 2)

    def test_lenses_keeps_skeptic_order_not_arrival_order(self):
        _, _, v = audit_engine.disposition(verdicts(
            ("spec-intentional", "upheld"), ("exploitability", "upheld")))
        self.assertEqual(v["lenses"], ["exploitability", "spec-intentional"])

    def test_a_repeated_lens_is_named_once(self):
        _, _, v = audit_engine.disposition(verdicts(
            ("exploitability", "upheld"), ("exploitability", "refuted")))
        self.assertEqual(v["lenses"], ["exploitability"])

    def test_no_verdicts_names_no_lenses(self):
        _, _, v = audit_engine.disposition([])
        self.assertEqual(v["lenses"], [])

    def test_no_verdicts_is_needs_review_not_drop(self):
        """Deliberate divergence from the retired JS, which dropped the finding.

        Zero verdicts means every skeptic call failed — that is no information,
        not a unanimous refutation, and the skill's own rule forbids silently
        deleting a finding that was never actually refuted."""
        d, _, v = audit_engine.disposition([])
        self.assertEqual(d, "needs-review")
        self.assertEqual(v["total"], 0)
        self.assertEqual(v["upheld"], 0)


class DiscoverTest(unittest.TestCase):
    def test_stops_after_k_empty_dry_rounds(self):
        calls = []

        def ask(prompt, schema=None):
            calls.append(prompt)
            return {"findings": []}

        found = audit_engine.discover(ask, "ctx", run=SEQUENTIAL)
        self.assertEqual(found.findings, [])
        # Literals, not the constants under test: asserting against
        # audit_engine.K_EMPTY would adapt to a mutation of it and prove nothing.
        self.assertEqual(audit_engine.K_EMPTY, 2)
        self.assertEqual(len(audit_engine.CATEGORIES), 6)
        self.assertEqual(len(calls), 12)

    def test_dry_counter_resets_on_a_fresh_finding(self):
        rounds = {"n": 0}

        def ask(prompt, schema=None):
            if "Category: auth" not in prompt:
                return {"findings": []}
            rounds["n"] += 1
            if rounds["n"] == 2:
                return {"findings": [finding(file="new.js")]}
            return {"findings": []}

        found = audit_engine.discover(ask, "ctx", run=SEQUENTIAL)
        self.assertEqual(len(found.findings), 1)

    def test_a_fresh_finding_buys_another_k_empty_rounds(self):
        """Pins the `dry = 0` reset: without it the loop stops a round early."""
        auth_calls = {"n": 0}
        rounds = []

        def ask(prompt, schema=None):
            if "Category: auth" not in prompt:
                return {"findings": []}
            auth_calls["n"] += 1
            if auth_calls["n"] == 2:
                return {"findings": [finding(file="new.js")]}
            return {"findings": []}

        audit_engine.discover(ask, "ctx", run=SEQUENTIAL,
                              on_round=lambda r, fresh, total, dry: rounds.append(r))
        # dry / fresh / dry / dry -> 4 rounds. Without the reset: dry / fresh / dry -> 3.
        self.assertEqual(rounds, [1, 2, 3, 4])

    def test_stops_at_max_rounds(self):
        seq = {"n": 0}

        def ask(prompt, schema=None):
            seq["n"] += 1
            return {"findings": [finding(file=f"f{seq['n']}.js", line=seq["n"] * 10)]}

        found = audit_engine.discover(ask, "ctx", run=SEQUENTIAL)
        self.assertLessEqual(len(found.findings),
                             audit_engine.MAX_ROUNDS * len(audit_engine.CATEGORIES))
        self.assertGreater(len(found.findings), 0)

    def test_duplicates_across_rounds_are_dropped(self):
        """Round 2 repeats what round 1 already found."""
        seen_once = {"n": 0}

        def ask(prompt, schema=None):
            if "Category: auth" not in prompt:
                return {"findings": []}
            seen_once["n"] += 1
            return {"findings": [finding(file="same.js", line=10)]}

        found = audit_engine.discover(ask, "ctx", run=SEQUENTIAL)
        self.assertEqual(len(found.findings), 1)
        self.assertGreater(seen_once["n"], 1)  # it really was offered twice

    def test_duplicates_within_a_single_round_are_dropped(self):
        """Second divergence from the retired JS, which kept all six.

        The JS filtered a whole round against `seen` before adding anything, so
        six finders reporting one issue produced six entries. Keys are added as
        they are seen here, so the round collapses to one."""
        def ask(prompt, schema=None):
            return {"findings": [finding(file="same.js", line=10)]}

        found = audit_engine.discover(ask, "ctx", run=SEQUENTIAL)
        self.assertEqual(len(found.findings), 1)

    def test_failed_finder_calls_are_skipped_not_fatal(self):
        def ask(prompt, schema=None):
            if "Category: auth" in prompt:
                return None
            return {"findings": []}

        self.assertEqual(audit_engine.discover(ask, "ctx", run=SEQUENTIAL).findings, [])

    def test_max_findings_caps_discovery(self):
        seq = {"n": 0}

        def ask(prompt, schema=None):
            seq["n"] += 1
            return {"findings": [finding(file=f"f{seq['n']}.js", line=seq["n"] * 10)]}

        found = audit_engine.discover(ask, "ctx", run=SEQUENTIAL, max_findings=3)
        self.assertEqual(len(found.findings), 3)


class MaxRoundsTest(unittest.TestCase):
    """The `scan` preset is one round of discovery. Everything else — the three
    skeptic lenses above all — is identical to `audit`, because with one lens a
    single refutation is a unanimous one and `disposition` drops on unanimous."""

    def _counting_ask(self, per_round):
        """An `ask` that returns a brand-new finding for every finder call."""
        seq = {"n": 0}

        def ask(prompt, schema=None):
            seq["n"] += 1
            per_round.append(seq["n"])
            return {"findings": [finding(file=f"f{seq['n']}.js", line=seq["n"] * 10)]}

        return ask

    def test_one_round_stops_even_when_the_round_was_productive(self):
        rounds = []
        calls = []
        audit_engine.discover(self._counting_ask(calls), "ctx", SEQUENTIAL,
                              max_rounds=1,
                              on_round=lambda r, fresh, total, dry: rounds.append(r))
        self.assertEqual(rounds, [1])
        self.assertEqual(len(calls), 6)  # one finder per category, once

    def test_the_default_is_still_five_rounds(self):
        """Literal, not the constant: asserting against MAX_ROUNDS would adapt
        to a mutation of it and prove nothing."""
        rounds = []
        audit_engine.discover(self._counting_ask([]), "ctx", SEQUENTIAL,
                              on_round=lambda r, fresh, total, dry: rounds.append(r))
        self.assertEqual(rounds, [1, 2, 3, 4, 5])
        self.assertEqual(audit_engine.MAX_ROUNDS, 5)

    def test_one_round_still_dedups_within_the_round(self):
        def ask(prompt, schema=None):
            return {"findings": [finding(file="same.js", line=10)]}

        self.assertEqual(len(audit_engine.discover(ask, "ctx", SEQUENTIAL,
                                                   max_rounds=1).findings), 1)

    def test_audit_threads_max_rounds_to_discover(self):
        finder_calls = {"n": 0}

        def ask(prompt, schema=None):
            if prompt.startswith("Read"):
                return "context"
            if "Category:" in prompt:
                finder_calls["n"] += 1
                return {"findings": [finding(file=f"f{finder_calls['n']}.js")]} \
                    if "Category: auth." in prompt else {"findings": []}
            lens = next(l for l in audit_engine.SKEPTICS if f"Lens: {l}" in prompt)
            return {"lens": lens, "verdict": "upheld", "reason": "r"}

        out = audit_engine.audit(ask, SEQUENTIAL, max_rounds=1)
        self.assertEqual(finder_calls["n"], 6)
        self.assertEqual(len(out.findings), 1)

    def test_audit_still_defaults_to_the_full_loop(self):
        finder_calls = {"n": 0}

        def ask(prompt, schema=None):
            if prompt.startswith("Read"):
                return "context"
            if "Category:" in prompt:
                finder_calls["n"] += 1
                return {"findings": []}
            return {"lens": "exploitability", "verdict": "upheld", "reason": "r"}

        audit_engine.audit(ask, SEQUENTIAL)
        self.assertEqual(finder_calls["n"], 12)  # K_EMPTY=2 dry rounds x 6


class AuditTest(unittest.TestCase):
    def test_dropped_findings_never_leave_the_engine(self):
        def ask(prompt, schema=None):
            if prompt.startswith("Read"):
                return "context"
            if "Category:" in prompt:
                return {"findings": [finding()]} if "auth" in prompt else {"findings": []}
            return {"lens": "exploitability", "verdict": "refuted", "reason": "no path"}

        self.assertEqual(audit_engine.audit(ask, SEQUENTIAL).findings, [])

    def test_survivor_carries_disposition_and_verification(self):
        def ask(prompt, schema=None):
            if prompt.startswith("Read"):
                return "context"
            if "Category:" in prompt:
                return {"findings": [finding()]} if "auth" in prompt else {"findings": []}
            lens = next(l for l in audit_engine.SKEPTICS if f"Lens: {l}" in prompt)
            return {"lens": lens, "verdict": "upheld", "reason": "reachable"}

        out = audit_engine.audit(ask, SEQUENTIAL).findings
        self.assertEqual(len(out), 1)
        self.assertEqual(out[0]["disposition"], "confirmed")
        self.assertEqual(out[0]["verification"]["upheld"], 3)
        self.assertEqual(out[0]["file"], "a.js")


class ContextTest(unittest.TestCase):
    def test_a_failed_context_call_stops_the_audit(self):
        """Continuing would send `Context: None` to every finder, and a run of
        empty finders is indistinguishable from a clean codebase."""
        calls = []

        def ask(prompt, schema=None):
            calls.append(prompt)
            return None

        with self.assertRaises(audit_engine.ContextUnavailable):
            audit_engine.audit(ask, SEQUENTIAL)
        self.assertEqual(len(calls), 1)  # no finder ran

    def test_an_empty_context_string_also_stops_the_audit(self):
        with self.assertRaises(audit_engine.ContextUnavailable):
            audit_engine.audit(lambda p, schema=None: "", SEQUENTIAL)


class VerifyAllTest(unittest.TestCase):
    """The JS ran every finding's skeptics concurrently. Verifying three calls
    at a time wastes most of a pool, so findings are batched into flat waves."""

    def _ask(self, prompt, schema=None):
        return {"lens": "exploitability", "verdict": "upheld", "reason": "r"}

    def test_skeptics_are_submitted_as_one_flat_wave_per_batch(self):
        widths = []
        findings = [finding(file=f"f{i}.js") for i in range(audit_engine.VERIFY_BATCH + 3)]
        audit_engine.verify_all(findings, self._ask, "ctx",
                                lambda ts: widths.append(len(ts)) or [t() for t in ts])
        self.assertEqual(widths, [audit_engine.VERIFY_BATCH * 3, 3 * 3])

    def test_every_finding_gets_its_own_verdicts_not_a_neighbours(self):
        """Regrouping a flat wave by index is only safe if the slice lines up."""
        def ask(prompt, schema=None):
            upheld = "f1.js" in prompt
            return {"lens": "exploitability",
                    "verdict": "upheld" if upheld else "refuted", "reason": "r"}

        out = audit_engine.verify_all([finding(file="f0.js"), finding(file="f1.js")],
                                      ask, "ctx", SEQUENTIAL)
        self.assertEqual([o["file"] for o in out], ["f0.js", "f1.js"])
        self.assertEqual([o["disposition"] for o in out], ["drop", "confirmed"])

    def test_a_halt_preserves_the_batches_already_settled(self):
        calls = {"n": 0}

        def ask(prompt, schema=None):
            calls["n"] += 1
            if calls["n"] > audit_engine.VERIFY_BATCH * 3:
                raise audit_engine.Halted("no more calls")
            return {"lens": "exploitability", "verdict": "upheld", "reason": "r"}

        findings = [finding(file=f"f{i}.js") for i in range(audit_engine.VERIFY_BATCH + 2)]
        with self.assertRaises(audit_engine.Halted) as ctx:
            audit_engine.verify_all(findings, ask, "ctx", SEQUENTIAL)
        self.assertEqual(len(ctx.exception.settled), audit_engine.VERIFY_BATCH)


class HaltTest(unittest.TestCase):
    def test_a_halt_during_discovery_returns_nothing(self):
        """Nothing has been verified yet, so there is nothing worth keeping."""
        def ask(prompt, schema=None):
            if "Category:" in prompt:
                raise audit_engine.Halted("budget")
            return "ctx"

        self.assertEqual(audit_engine.audit(ask, SEQUENTIAL).findings, [])

    def test_a_halt_during_verification_returns_what_was_settled(self):
        """Used to discard the entire run — including findings already paid for."""
        lens_calls = {"n": 0}
        seq = {"n": 0}
        limit = audit_engine.VERIFY_BATCH * 3  # exactly one full batch

        def ask(prompt, schema=None):
            if "Lens:" in prompt:
                lens_calls["n"] += 1
                if lens_calls["n"] > limit:
                    raise audit_engine.Halted("budget")
                return {"lens": "exploitability", "verdict": "upheld", "reason": "r"}
            if "Category:" in prompt:
                seq["n"] += 1
                i = seq["n"]
                return {"findings": [finding(file=f"f{i}_{j}.js", line=10 * j)
                                     for j in range(2)]}
            return "ctx"

        out = audit_engine.audit(ask, SEQUENTIAL,
                                 max_findings=audit_engine.VERIFY_BATCH + 2).findings
        self.assertEqual(len(out), audit_engine.VERIFY_BATCH)
        self.assertTrue(all(o["disposition"] == "confirmed" for o in out))


class ColocationTest(unittest.TestCase):
    """Observed live on the phase 7 fixture: the `auth` finder and the
    `injection` finder both reported the SQL injection at src/auth.js:5, so one
    vulnerability became two findings and cost six verification calls. The same
    fixture at --concurrency 1 produced one. Non-reproducible double-counting."""

    def test_two_categories_at_one_location_point_at_each_other(self):
        out = audit_engine.annotate_colocated([
            finding(file="src/auth.js", line=5, category="auth"),
            finding(file="src/auth.js", line=5, category="injection"),
        ])
        self.assertEqual(out[0]["colocated"], ["injection"])
        self.assertEqual(out[1]["colocated"], ["auth"])

    def test_a_lone_finding_is_colocated_with_nothing(self):
        out = audit_engine.annotate_colocated([finding(file="src/a.js", line=5)])
        self.assertEqual(out[0]["colocated"], [])

    def test_a_different_window_is_not_colocated(self):
        out = audit_engine.annotate_colocated([
            finding(file="src/auth.js", line=2, category="secrets"),
            finding(file="src/auth.js", line=5, category="injection"),
        ])
        self.assertEqual([o["colocated"] for o in out], [[], []])

    def test_path_spelling_does_not_hide_a_colocation(self):
        out = audit_engine.annotate_colocated([
            finding(file="./src/auth.js", line=5, category="auth"),
            finding(file="src/auth.js", line=6, category="injection"),
        ])
        self.assertEqual(out[0]["colocated"], ["injection"])

    def test_nothing_is_merged_or_dropped(self):
        """The whole point. Two issues in one window stay two issues: between a
        visible duplicate and a silent deletion, a security tool takes the
        duplicate."""
        given = [finding(file="src/a.js", line=5, category="auth"),
                 finding(file="src/a.js", line=6, category="secrets")]
        out = audit_engine.annotate_colocated(given)
        self.assertEqual(len(out), 2)
        self.assertEqual([o["category"] for o in out], ["auth", "secrets"])

    def test_audit_annotates_survivors_only(self):
        """A survivor must not be told it shares a location with a finding the
        skeptics just deleted."""
        def ask(prompt, schema=None):
            if prompt.startswith("Read"):
                return "context"
            if "Category:" in prompt:
                if "Category: auth." in prompt:
                    return {"findings": [finding(file="a.js", line=5,
                                                 category="auth")]}
                if "Category: injection." in prompt:
                    return {"findings": [finding(file="a.js", line=5,
                                                 category="injection")]}
                return {"findings": []}
            lens = next(l for l in audit_engine.SKEPTICS if f"Lens: {l}" in prompt)
            if "'category': 'auth'" not in prompt:
                return {"lens": lens, "verdict": "upheld", "reason": "r"}
            # The auth copy is dropped: three refutations, none of them citing a
            # spec, so nothing short-circuits to intentional-design and
            # `upheld == 0` is reached. (This used to need the spec lens to go
            # unanswered, because an *uncited* refute short-circuited too.)
            return {"lens": lens, "verdict": "refuted", "reason": "r"}

        out = audit_engine.audit(ask, SEQUENTIAL, max_rounds=1).findings
        self.assertEqual([o["category"] for o in out], ["injection"])
        self.assertEqual(out[0]["colocated"], [])


class PathNormalizationTest(unittest.TestCase):
    """Observed live in phase 6: one Copilot run reported the same SQL injection
    twice, as `./src/auth.js` and `src/auth.js`. Both survived deduping and one
    of three verification slots was spent on the duplicate."""

    def test_a_dot_slash_prefix_is_the_same_file(self):
        self.assertEqual(audit_engine.dedup_key(finding(file="./src/auth.js")),
                         audit_engine.dedup_key(finding(file="src/auth.js")))

    def test_redundant_separators_are_the_same_file(self):
        self.assertEqual(audit_engine.dedup_key(finding(file="src//auth.js")),
                         audit_engine.dedup_key(finding(file="src/auth.js")))

    def test_genuinely_different_files_stay_distinct(self):
        self.assertNotEqual(audit_engine.dedup_key(finding(file="./src/a.js")),
                            audit_engine.dedup_key(finding(file="./src/b.js")))

    def test_discover_collapses_the_live_duplicate(self):
        rounds = iter([
            {"findings": [finding(file="./src/auth.js", line=5),
                          finding(file="src/auth.js", line=5)]},
            {"findings": []}, {"findings": []},
        ])

        def ask(prompt, schema=None):
            try:
                return next(rounds)
            except StopIteration:
                return {"findings": []}

        found = audit_engine.discover(ask, "ctx", SEQUENTIAL).findings
        self.assertEqual(len(found), 1, f"duplicate survived: {found}")

    def test_the_reported_path_is_normalized(self):
        def ask(prompt, schema=None):
            return {"findings": [finding(file="./src/auth.js")]}

        found = audit_engine.discover(ask, "ctx", SEQUENTIAL, max_findings=1).findings
        self.assertEqual(found[0]["file"], "src/auth.js")

    def test_a_windows_separator_is_the_same_file(self):
        """os.path.normpath is host-dependent: on Windows it rewrites every
        reported path to backslashes, so `src\\auth.js` and `src/auth.js` are
        two findings on POSIX and the *forward*-slash spelling is the odd one
        out on Windows — where it also breaks SKILL.md's cross-reference
        against a behavior graph keyed on forward slashes."""
        self.assertEqual(audit_engine.dedup_key(finding(file="src\\auth.js")),
                         audit_engine.dedup_key(finding(file="src/auth.js")))

    def test_the_reported_path_is_posix_on_every_host(self):
        self.assertEqual(audit_engine.normalize_file(".\\src\\auth.js"),
                         "src/auth.js")


class TruncationTest(unittest.TestCase):
    """Discovery that stops at `max_findings` has not finished looking.

    This replaces a bare `return found[:max_findings]` that told the caller
    nothing: the run discarded findings it had already discovered and paid for,
    skipped every remaining round, reported the survivors, and exited 0 — the
    code SKILL.md defines verbatim as clean.
    """

    def _one_per_finder(self):
        """Six finders, one brand-new finding each, every round."""
        seq = {"n": 0}

        def ask(prompt, schema=None):
            seq["n"] += 1
            return {"findings": [finding(file=f"f{seq['n']}.js", line=seq["n"] * 10)]}

        return ask

    def test_the_discarded_count_reaches_the_caller(self):
        out = audit_engine.discover(self._one_per_finder(), "ctx", SEQUENTIAL,
                                    max_findings=2)
        self.assertEqual(len(out.findings), 2)
        self.assertEqual(out.discarded, 4)  # round 1 discovered six
        self.assertTrue(out.capped)

    def test_a_cap_reached_with_nothing_to_discard_is_still_capped(self):
        """Zero discarded is not a complete sweep: rounds 2..5 never ran, so
        loop-until-dry never happened and the codebase was not exhausted."""
        out = audit_engine.discover(self._one_per_finder(), "ctx", SEQUENTIAL,
                                    max_findings=6)
        self.assertEqual((out.discarded, out.capped), (0, True))

    def test_a_run_that_goes_dry_is_not_capped(self):
        out = audit_engine.discover(lambda p, schema=None: {"findings": []},
                                    "ctx", SEQUENTIAL, max_findings=10)
        self.assertEqual((out.findings, out.discarded, out.capped), ([], 0, False))

    def test_audit_carries_the_truncation_out_past_verification(self):
        """The count has to survive the whole engine, not just `discover`:
        the driver reads it off `audit`'s result to pick its exit code."""
        seq = {"n": 0}

        def ask(prompt, schema=None):
            if prompt.startswith("Read"):
                return "context"
            if "Category:" in prompt:
                seq["n"] += 1
                return {"findings": [finding(file=f"f{seq['n']}.js",
                                             line=seq["n"] * 10)]}
            lens = next(l for l in audit_engine.SKEPTICS if f"Lens: {l}" in prompt)
            return {"lens": lens, "verdict": "upheld", "reason": "r"}

        out = audit_engine.audit(ask, SEQUENTIAL, max_findings=2, max_rounds=5)
        self.assertEqual(len(out.findings), 2)
        self.assertEqual((out.discarded, out.capped), (4, True))

    def test_a_budget_halt_is_not_reported_as_a_cap(self):
        """Two different incompletenesses. The driver names the ceiling itself,
        from its own Budget, and must not also blame --max-findings."""
        def ask(prompt, schema=None):
            if "Category:" in prompt:
                raise audit_engine.Halted("budget")
            return "ctx"

        out = audit_engine.audit(ask, SEQUENTIAL, max_findings=2)
        self.assertEqual((out.findings, out.discarded, out.capped), ([], 0, False))


class SpecCitationTest(unittest.TestCase):
    """A citation only outranks the vote if it points at something that exists.

    Found live, not by inspection: a `gpt-5-mini` skeptic run against a fixture
    containing exactly two .js files and no knowledge-base cited
    `/knowledge-base/specs/authentication.md#trusted-inputs-and-normalization`
    and downgraded a real SQL injection to `intentional-design`. A second run
    dispositioned a hardcoded production credential the same way, `upheld 0/3`,
    on a "citation" whose text was *"No /knowledge-base/specs ... found in repo"*.
    Requiring the field to be non-empty is no guard at all when the model writes
    the field. So the citation is now corroborated against the project, and an
    uncorroborated one falls through to the ordinary vote.
    """

    def setUp(self):
        self.project = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.project, ignore_errors=True)

    def _spec(self, relpath, body="SPEC-007: usernames are pre-normalized.\n"):
        path = os.path.join(self.project, relpath)
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w", encoding="utf-8") as handle:
            handle.write(body)
        return path

    def test_a_fabricated_path_does_not_buy_intentional_design(self):
        d, ref, _ = audit_engine.disposition(
            verdicts(("exploitability", "upheld"),
                     ("compensating-controls", "upheld"))
            + [cited("/knowledge-base/specs/authentication.md#trusted-inputs")],
            project=self.project)
        self.assertEqual((d, ref), ("confirmed", None))

    def test_a_self_negating_citation_is_not_a_citation(self):
        """The exact string that downgraded a hardcoded production credential."""
        d, ref, _ = audit_engine.disposition(
            verdicts(("exploitability", "refuted"),
                     ("compensating-controls", "refuted"))
            + [cited("No /knowledge-base/specs or /knowledge-base/reference "
                     "found in repo — no spec asserts this is intended")],
            project=self.project)
        self.assertEqual((d, ref), ("drop", None))

    def test_a_real_spec_file_still_buys_intentional_design(self):
        self._spec("knowledge-base/specs/authentication.md")
        d, ref, _ = audit_engine.disposition(
            verdicts(("exploitability", "upheld"),
                     ("compensating-controls", "upheld"))
            + [cited("/knowledge-base/specs/authentication.md#trusted-inputs")],
            project=self.project)
        self.assertEqual(d, "intentional-design")
        self.assertIn("authentication.md", ref)

    def test_a_relative_path_without_the_leading_slash_resolves(self):
        self._spec("specs/authentication.md")
        d, _, _ = audit_engine.disposition(
            verdicts(("exploitability", "upheld"))
            + [cited("specs/authentication.md#password-storage")],
            project=self.project)
        self.assertEqual(d, "intentional-design")

    def test_a_spec_id_is_corroborated_by_its_presence_in_the_project(self):
        """Citations here are as often an ID as a path — spec-manager issues
        SPEC-NNN / ADR-NNN / BEH-NNN — so an ID that really appears in the
        knowledge base is a citation too."""
        self._spec("knowledge-base/specs/auth.md", "# SPEC-007\nNormalized.\n")
        d, ref, _ = audit_engine.disposition(
            verdicts(("exploitability", "upheld")) + [cited("SPEC-007")],
            project=self.project)
        self.assertEqual((d, ref), ("intentional-design", "SPEC-007"))

    def test_an_invented_spec_id_does_not_resolve(self):
        self._spec("knowledge-base/specs/auth.md", "# SPEC-007\nNormalized.\n")
        d, ref, _ = audit_engine.disposition(
            verdicts(("exploitability", "upheld"),
                     ("compensating-controls", "upheld")) + [cited("SPEC-999")],
            project=self.project)
        self.assertEqual((d, ref), ("confirmed", None))

    def test_a_citation_may_not_escape_the_project(self):
        """A document outside the tree says nothing about *this* project's
        intent, and `os.path.join(root, '../x.md')` walks straight out to one.

        Pinned against a real neighbouring file rather than `../../etc/passwd`:
        that string carries neither a prose suffix nor a `SPEC-NNN`-shaped
        token, so it matched no citation pattern and the containment check was
        never consulted. Measured 2026-08-21 — with the `commonpath` guard
        replaced by `if False:`, all nine tests in this class still passed,
        and that guard is the only thing between a skeptic and downgrading a
        real finding on a spec belonging to somebody else's repository.
        """
        outside = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, outside, ignore_errors=True)
        with open(os.path.join(outside, "SPEC-001-elsewhere.md"), "w",
                  encoding="utf-8") as handle:
            handle.write("SPEC-001: another project's design decision.\n")
        escaping = "../%s/SPEC-001-elsewhere.md" % os.path.basename(outside)
        # The fixture is only a test if the escape lands on something real —
        # otherwise `isfile` refuses it and containment is never the reason.
        self.assertTrue(
            os.path.isfile(os.path.join(os.path.realpath(self.project), escaping)),
            "fixture must resolve to a file that exists outside the project")

        d, ref, _ = audit_engine.disposition(
            verdicts(("exploitability", "upheld"),
                     ("compensating-controls", "upheld"))
            + [cited(escaping)],
            project=self.project)
        self.assertEqual((d, ref), ("confirmed", None))

    def test_without_a_project_the_citation_is_trusted_as_before(self):
        """The resolver needs a tree to check against. With none, behaviour is
        unchanged rather than silently stricter — the driver always passes one."""
        d, ref, _ = audit_engine.disposition(
            verdicts(("exploitability", "upheld")) + [cited("SPEC-007")])
        self.assertEqual((d, ref), ("intentional-design", "SPEC-007"))

    def test_audit_threads_the_project_through_to_disposition(self):
        """The guard is worthless if the driver never hands the project down."""
        seen = []

        def ask(prompt, schema=None):
            if "findings" in str(schema):
                return {"findings": [finding()]}
            if schema is not None:
                lens = prompt.split("Lens: ", 1)[1].split(".", 1)[0]
                seen.append(lens)
                if lens == "spec-intentional":
                    # The shape observed live: a confident citation at a path
                    # that does not exist anywhere in the project.
                    return {"lens": lens, "verdict": "refuted", "reason": "r",
                            "specReference": "/knowledge-base/specs/nope.md"}
                return {"lens": lens, "verdict": "upheld", "reason": "r"}
            return "context"

        result = audit_engine.audit(ask, SEQUENTIAL, max_rounds=1,
                                    project=self.project)
        self.assertIn("spec-intentional", seen)
        self.assertEqual(result.findings[0]["disposition"], "confirmed")
        self.assertIsNone(result.findings[0]["specReference"])

    def test_an_id_outside_the_spec_namespace_is_not_a_citation(self):
        """`[A-Z]{2,6}-\\d+` also matched CWE-89, CVE-2021, RFC-7231, ISO-9001,
        AES-256 and this tool's own SEC-### ids, every one of which corroborated
        a citation against this repository. A finding's `cwe` field is
        interpolated verbatim into the skeptic prompt, so a worker reaches "per
        CWE-89 this is accepted" by paraphrasing its own input.

        The citation strings deliberately carry no `.md` token: with one, the
        path branch decides the case and the namespace is never consulted — the
        same trap `test_a_citation_may_not_escape_the_project` documents.
        """
        self._spec("docs/SECURITY.md",
                   "We defend against CWE-89 (SQL injection), follow RFC-7231,\n"
                   "hold ISO-9001, use AES-256, and SEC-004 is closed.\n")
        for token in ["CWE-89", "RFC-7231", "ISO-9001", "AES-256", "SEC-004"]:
            with self.subTest(token=token):
                d, ref, _ = audit_engine.disposition(
                    verdicts(("exploitability", "upheld"),
                             ("compensating-controls", "upheld"))
                    + [cited("Documented as an accepted risk, see the %s note"
                             % token)],
                    project=self.project)
                self.assertEqual((d, ref), ("confirmed", None))

    def test_the_adr_and_behavior_namespaces_still_corroborate(self):
        """The fence against narrowing one prefix too far. spec-manager issues
        all three and the coverage above only exercises SPEC-."""
        self._spec("knowledge-base/decisions/ADR-003-x.md", "# ADR-003\nDecided.\n")
        self._spec("knowledge-base/specs/b.md", "BEH-012 is accepted.\n")
        for token in ["ADR-003", "BEH-012"]:
            with self.subTest(token=token):
                d, ref, _ = audit_engine.disposition(
                    verdicts(("exploitability", "upheld")) + [cited(token)],
                    project=self.project)
                self.assertEqual((d, ref), ("intentional-design", token))

    def test_this_skills_own_reports_do_not_corroborate_a_citation(self):
        """The scanner is not its own witness — by id.

        A report names every id it discusses, including invented ones quoted out
        of a test, and it lands inside the walked roots — so last month's report
        corroborates this month's citation. Measured on this repository on
        2026-08-23 with the namespace already narrowed: `SPEC-999` still
        resolved, and its only occurrence in the whole tree is a report sentence
        saying it must not.

        Half the invariant. The path half is the test below, and it is the half
        that was missing while this docstring claimed the whole thing.
        """
        self._spec("knowledge-base/security/codebase-security/2026-08-21.md",
                   "SEC-005: the invented `SPEC-999` case must not resolve.\n")
        spoof = (verdicts(("exploitability", "upheld"),
                          ("compensating-controls", "upheld")) + [cited("SPEC-999")])
        d, ref, _ = audit_engine.disposition(spoof, project=self.project)
        self.assertEqual((d, ref), ("confirmed", None))

        # The control, so the assertion above is about *where* the mention was
        # and not about the id: an ordinary spec still corroborates it.
        self._spec("knowledge-base/specs/real.md", "SPEC-999 is accepted.\n")
        d, ref, _ = audit_engine.disposition(spoof, project=self.project)
        self.assertEqual((d, ref), ("intentional-design", "SPEC-999"))

    def test_a_report_cited_by_path_does_not_corroborate_a_citation(self):
        """The scanner is not its own witness — by path either.

        The more reachable of the two branches, and the one the id prune left
        open. A report file genuinely exists, so a skeptic that can list a
        directory can cite a real path and `os.path.isfile` says yes; the id
        branch needed the report to happen to name the id being cited. Measured
        against the tree of 2026-08-23 before the prune: the path branch
        returned the report and the disposition came back `intentional-design`
        on a finding two lenses upheld.
        """
        report = "knowledge-base/security/codebase-security/2026-08-21.md"
        self._spec(report, "SEC-005: accepted risk, see the note above.\n")
        spoof = (verdicts(("exploitability", "upheld"),
                          ("compensating-controls", "upheld"))
                 + [cited("%s#sec-005" % report)])
        d, ref, _ = audit_engine.disposition(spoof, project=self.project)
        self.assertEqual((d, ref), ("confirmed", None))

        # Two controls, because "no" is cheap to get for the wrong reason.
        # First: the prune is about the directory, not about the filename or
        # the `#fragment` — the same document one level up still corroborates.
        self._spec("knowledge-base/2026-08-21.md", "SEC-005: accepted.\n")
        d, _, _ = audit_engine.disposition(
            verdicts(("exploitability", "upheld"))
            + [cited("knowledge-base/2026-08-21.md#sec-005")],
            project=self.project)
        self.assertEqual(d, "intentional-design")

        # Second: a third party's own security prose is not this tool's output
        # and is exactly the corroboration the resolver exists to find.
        self._spec("docs/security/threat-model.md", "Accepted: SEC-005.\n")
        d, _, _ = audit_engine.disposition(
            verdicts(("exploitability", "upheld"))
            + [cited("docs/security/threat-model.md")],
            project=self.project)
        self.assertEqual(d, "intentional-design")


class SecretRedactionTest(unittest.TestCase):
    """A credential a finder copied out of the scanned repository must not leave
    this engine in any field it copied it into.

    It used to leave by three doors, and the engine owns all three: the skeptic
    prompt, which the driver passes as an argv element that any local user can
    read out of a process listing; the driver's stdout; and the git-tracked
    report the agent writes from that stdout. These tests pin the fix at the one
    *ingest*, so they stay green if the value is redacted earlier and go red the
    moment it is redacted later — which is the difference between one edit and
    three chances to miss one.

    "In any field it copied it into" is load-bearing and was not always true:
    the fixture below quotes the snippet in `title`, `description` and
    `recommendation` because a fixture loading only `description` left two
    fields uncovered while this docstring said the credential could not leave.
    What is still not claimed, here or in `redact_secret_evidence`: a credential
    a finder *paraphrases* rather than copies is not caught, because catching it
    needs pattern detection the redactor declines to do.

    AWS's own published example key, so the fixture is not itself a secret.
    """

    SECRET = "wJalrXUtnFEMI/K7MDENG/bPxRfiCYEXAMPLEKEY"
    SNIPPET = 'AWS_SECRET_ACCESS_KEY = "%s"' % SECRET

    def _ask(self, prompts, category="secrets"):
        def ask(prompt, schema=None):
            prompts.append(prompt)
            if schema is audit_engine.FINDER_SCHEMA:
                # Every prose field quotes the snippet, because a finder writes
                # the same evidence into whichever one it is filling. A fixture
                # that only loaded `description` is how a fix covering two of
                # the four fields read as though it covered all of them.
                return {"findings": [finding(
                    file="src/config.js", line=12, category=category,
                    title="hardcoded credential %s" % self.SNIPPET,
                    description="hardcoded credential: %s" % self.SNIPPET,
                    recommendation="remove %s and rotate it" % self.SNIPPET,
                    codeSnippet=self.SNIPPET)]}
            if schema is not None:
                lens = prompt.split("Lens: ", 1)[1].split(".", 1)[0]
                return {"lens": lens, "verdict": "upheld", "reason": "r"}
            return "context"
        return ask

    def test_a_credential_never_survives_discovery(self):
        found = audit_engine.discover(self._ask([]), "ctx", SEQUENTIAL,
                                      max_rounds=1)
        self.assertTrue(found.findings, "fixture must produce a finding")
        self.assertNotIn(self.SECRET, str(found.findings))

    def test_no_skeptic_prompt_ever_carries_the_credential(self):
        """`_skeptic` interpolates the whole finding dict, so this is the argv
        element the driver builds. Asserted on the count as well as the content:
        a stub that never reached a skeptic would pass an empty loop."""
        prompts = []
        result = audit_engine.audit(self._ask(prompts), SEQUENTIAL, max_rounds=1)
        skeptic = [p for p in prompts if "Lens: " in p]
        self.assertEqual(len(skeptic), len(audit_engine.SKEPTICS))
        self.assertTrue(result.findings)
        for prompt in skeptic:
            self.assertNotIn(self.SECRET, prompt)
            # What the skeptic keeps: where to look, and a stand-in stable
            # enough to recognise the same secret on the next run. The worker
            # can open the file itself; it does not need the bytes posted to it.
            self.assertIn("src/config.js", prompt)
            self.assertIn("redacted", prompt)

    def test_another_category_keeps_its_snippet_all_the_way_through(self):
        """The anti-over-reach half. Vulnerable code is most of what a report is
        worth for an injection finding, and redacting at ingest is exactly where
        an over-broad rule would quietly eat it."""
        prompts = []
        result = audit_engine.audit(self._ask(prompts, category="injection"),
                                    SEQUENTIAL, max_rounds=1)
        self.assertEqual(result.findings[0]["codeSnippet"], self.SNIPPET)
        self.assertIn(self.SNIPPET, [p for p in prompts if "Lens: " in p][0])


class LensBindingTest(unittest.TestCase):
    """A verdict is attributed to the lens whose question produced it.

    The wave submits one thunk per lens in SKEPTICS order and regroups by index,
    so slot j is SKEPTICS[j] — but `disposition` re-derived the lens from each
    answer's own `lens` key and nothing compared the two. Any of the three
    workers could therefore cast the single-lens spec veto that outranks a
    majority, and one mislabel made a report name a lens that never answered.

    A separate class rather than more methods on VerifyAllTest: inserting there
    would shift `test_audit_engine.py:725-727`, which the security report cites.
    """

    def _ask(self, replies):
        def ask(prompt, schema=None):
            return replies(prompt.split("Lens: ", 1)[1].split(".", 1)[0])
        return ask

    def _settle_one(self, replies):
        return audit_engine.verify_all([finding()], self._ask(replies), "ctx",
                                       SEQUENTIAL)[0]

    def test_a_verdict_is_bound_to_the_lens_it_was_asked_for(self):
        """No `project`, so the citation is trusted as written and the binding
        is the only thing between the spoof and `intentional-design`."""
        def replies(lens):
            if lens == "exploitability":
                return {"lens": "spec-intentional", "verdict": "refuted",
                        "reason": "r", "specReference": "SPEC-007"}
            return {"lens": lens, "verdict": "upheld", "reason": "r"}

        out = self._settle_one(replies)
        self.assertEqual(out["disposition"], "confirmed")
        self.assertIsNone(out["specReference"])
        self.assertEqual(out["verification"]["mislabeled"], 1)

    def test_a_failed_call_does_not_slide_the_lenses_left(self):
        """Binding runs on the raw slice. `disposition` opens by dropping the
        falsy entries, so binding the filtered list would move every later lens
        one place left — compensating-controls into slot 0, and spec-intentional
        out of the slot where the veto is decided."""
        def replies(lens):
            if lens == "exploitability":
                return None
            return {"lens": "exploitability", "verdict": "upheld", "reason": "r"}

        out = self._settle_one(replies)
        self.assertEqual(out["verification"]["lenses"],
                         ["compensating-controls", "spec-intentional"])
        self.assertEqual(out["verification"]["total"], 2)

    def test_a_mislabelled_verdict_is_counted_and_not_discarded(self):
        """Rewritten, never dropped. Discarding the one upheld answer here
        leaves an all-refuted remainder, and a finding every remaining skeptic
        refuted is deleted — on the strength of a labelling mistake."""
        def replies(lens):
            if lens == "spec-intentional":
                return {"lens": "exploitability", "verdict": "upheld", "reason": "r"}
            return {"lens": lens, "verdict": "refuted", "reason": "r"}

        out = self._settle_one(replies)
        self.assertEqual(out["verification"]["total"], 3)
        self.assertEqual(out["disposition"], "needs-review")

    def test_a_clean_wave_carries_no_mislabeled_key(self):
        """`mislabeled` is additive: absent whenever every worker answered the
        question it was asked, so the documented `{upheld, total, lenses}` shape
        is what every ordinary run still produces."""
        out = self._settle_one(
            lambda lens: {"lens": lens, "verdict": "upheld", "reason": "r"})
        self.assertEqual(out["verification"],
                         {"upheld": 3, "total": 3, "lenses": audit_engine.SKEPTICS})


# Last, not mid-file: this used to sit above PathNormalizationTest, so running
# the file directly (rather than through `-m unittest`) executed unittest.main()
# before those classes existed and silently skipped every one of them.
if __name__ == "__main__":
    unittest.main()
