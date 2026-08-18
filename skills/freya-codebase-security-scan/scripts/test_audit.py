#!/usr/bin/env python3
"""Unit tests for the audit driver. No agent is ever invoked."""

import contextlib
import io
import json
import subprocess
import sys
import threading
import time
import unittest
from unittest import mock

import audit
import audit_adapter
import audit_engine


class _SlowBudget(audit.Budget):
    """A Budget whose `calls` reads slowly, widening the check->increment race."""

    @property
    def calls(self):
        time.sleep(0.002)
        return self._calls

    @calls.setter
    def calls(self, value):
        self._calls = value


def _slow_counter(name):
    """A counter attribute whose read is slow *after* fetching the value.

    Note where the delay sits, because it is the whole trick and it differs
    from _SlowBudget's. _SlowBudget widens a check-then-act, so sleeping before
    the read is enough. Health's hazard is a plain `+= 1`, whose window is
    between the load and the store — sleeping first only delays every thread
    equally, and the counter then comes out right even with the lock removed.
    """
    store = "_" + name

    def get(self):
        value = getattr(self, store)
        time.sleep(0.002)
        return value

    def put(self, value):
        setattr(self, store, value)

    return property(get, put)


class _SlowHealth(audit.Health):
    """The Health analogue of _SlowBudget."""

    attempts = _slow_counter("attempts")
    failures = _slow_counter("failures")
    answered = _slow_counter("answered")
    unanswered = _slow_counter("unanswered")


class _FakeStdin(io.StringIO):
    """A stdin that can claim to be a terminal.

    Deliberately not a mock of `builtins.input`: the leak under test is that
    `input(prompt)` writes its prompt to *sys.stdout* when stdin is not a real
    file, and mocking `input` away hides exactly that.
    """

    def __init__(self, text="", tty=True):
        super().__init__(text)
        self._tty = tty

    def isatty(self):
        return self._tty


def run_main(argv):
    out, err = io.StringIO(), io.StringIO()
    with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
        code = audit.main(argv)
    return code, out.getvalue(), err.getvalue()


class BudgetTest(unittest.TestCase):
    def test_counts_calls(self):
        b = audit.Budget(max_calls=3)
        for _ in range(3):
            b.spend(None)
        self.assertEqual(b.calls, 3)

    def test_raises_past_the_cap(self):
        b = audit.Budget(max_calls=1)
        b.spend(None)
        with self.assertRaises(audit.BudgetExhausted):
            b.spend(None)

    def test_sums_cost_when_reported(self):
        b = audit.Budget(max_calls=10)
        b.spend(0.4)
        b.spend(0.2)
        self.assertAlmostEqual(b.usd, 0.6)

    def test_cost_stays_none_when_not_reported(self):
        b = audit.Budget(max_calls=10)
        b.spend(None)
        self.assertIsNone(b.usd)

    def test_exhaustion_is_recorded_not_just_raised(self):
        """main() reads this flag to decide between exit 0 and exit 3."""
        b = audit.Budget(max_calls=1)
        b.spend(None)
        self.assertFalse(b.exhausted)
        with self.assertRaises(audit.BudgetExhausted):
            b.spend(None)
        self.assertTrue(b.exhausted)

    def test_exhaustion_is_a_halt_so_the_engine_keeps_its_work(self):
        self.assertTrue(issubclass(audit.BudgetExhausted, audit_engine.Halted))

    def test_the_ceiling_holds_under_concurrent_workers(self):
        """`run` spends from a pool, so check-then-increment needs the lock.

        A plain hammer loop cannot prove this: the window between the check and
        the increment is a few bytecodes wide, so it never loses the race and
        the test passes with the lock removed. `_SlowBudget` widens that window
        without touching the logic under test, which makes the interleaving
        deterministic — remove the lock and this fails every time.
        """
        b = _SlowBudget(max_calls=4)

        def hammer():
            for _ in range(3):
                try:
                    b.spend(0.01)
                except audit.BudgetExhausted:
                    return

        threads = [threading.Thread(target=hammer) for _ in range(8)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        self.assertEqual(b.calls, 4)
        self.assertAlmostEqual(b.usd, 0.04)


class HealthLockTest(unittest.TestCase):
    """Health went unlocked while Budget, ten lines above it, did not — and it
    is Health's counters, not Budget's, that decide whether main() reports a run
    as clean, INCOMPLETE or failed."""

    # One counter per test on purpose: hammering all four together lets the
    # three locked mutators serialize the threads, and an unlocked fourth then
    # comes out right anyway. Each lock has to be provable on its own.
    def _hammer(self, bump):
        health = _SlowHealth()

        def hammer():
            for _ in range(3):
                bump(health)

        threads = [threading.Thread(target=hammer) for _ in range(8)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        return health

    def test_the_unanswered_counter_survives_concurrent_workers(self):
        """A single lost increment on a run with exactly one unanswered task
        flips `degraded` to False: no INCOMPLETE banner, exit 0, a partially
        covered scan reported as a complete one."""
        self.assertEqual(self._hammer(lambda h: h.task_unanswered()).unanswered, 24)

    def test_the_answered_counter_survives_concurrent_workers(self):
        """`health.attempts and not health.answered` is the "every call failed"
        guard; a phantom `answered` would let a dead run report as a live one."""
        self.assertEqual(self._hammer(lambda h: h.task_answered()).answered, 24)

    def test_the_attempt_counter_survives_concurrent_workers(self):
        self.assertEqual(self._hammer(lambda h: h.attempted()).attempts, 24)

    def test_the_failure_counter_survives_concurrent_workers(self):
        """Diagnostic, not a gate — but it is the number the INCOMPLETE banner
        asks the user to judge residual risk by."""
        self.assertEqual(self._hammer(lambda h: h.failed("boom")).failures, 24)


class EstimateTest(unittest.TestCase):
    def test_worst_case_is_counted_in_attempts_not_tasks(self):
        """The budget counts attempts, so the estimate must too — a task that
        retries costs two. Reporting tasks against an attempt ceiling understated
        the real cost by (retries + 1)."""
        tasks = 1 + 5 * 6 + 3 * 10
        self.assertEqual(audit.logical_calls(10), tasks)
        self.assertEqual(audit.estimate(10, retries=1), tasks * 2)
        self.assertEqual(audit.estimate(10, retries=0), tasks)

    def test_affordable_findings_leaves_room_for_discovery(self):
        # 200 attempts / 2 = 100 tasks; 31 go to context+finders; 69/3 = 23 findings
        self.assertEqual(audit.affordable_findings(200, retries=1), 23)

    def test_a_budget_too_small_to_verify_anything_affords_zero(self):
        self.assertEqual(audit.affordable_findings(10, retries=1), 0)

    def test_the_shipped_defaults_can_actually_finish_a_run(self):
        """The regression guard. --max-calls 80 with --max-findings 40 promised
        151 tasks against an 80-attempt ceiling: the default configuration could
        not complete, and exhaustion discarded everything already paid for."""
        affordable = audit.affordable_findings(audit.DEFAULT_MAX_CALLS)
        self.assertGreater(affordable, 0)
        self.assertLessEqual(audit.estimate(affordable), audit.DEFAULT_MAX_CALLS)


class ModeTest(unittest.TestCase):
    """`scan` is a preset of this driver, not a second driver."""

    def test_scan_is_one_round_of_discovery(self):
        self.assertEqual(audit.MODES["scan"].rounds, 1)
        self.assertEqual(audit.MODES["audit"].rounds, 5)

    def test_the_preset_never_cuts_skeptics(self):
        """The load-bearing constraint. With one lens a single refutation is a
        unanimous one, `disposition` reaches `upheld == 0`, and a real
        vulnerability is deleted without a word. Verification is identical in
        both modes; only discovery is cheaper."""
        for mode in audit.MODES.values():
            self.assertEqual(
                audit.logical_calls(4, rounds=mode.rounds),
                1 + mode.rounds * 6 + 3 * 4,
                f"{mode.name} does not verify with all three lenses",
            )

    def test_the_worst_cases_at_three_findings(self):
        self.assertEqual(audit.logical_calls(3, rounds=1), 16)
        self.assertEqual(audit.logical_calls(3, rounds=5), 40)

    def test_affordable_findings_is_mode_aware(self):
        # 200 attempts / 2 = 100 tasks; 7 go to context+finders; 93/3 = 31
        self.assertEqual(audit.affordable_findings(200, rounds=1), 31)
        self.assertGreater(audit.affordable_findings(200, rounds=1),
                           audit.affordable_findings(200, rounds=5))

    def test_the_default_rounds_are_still_audits(self):
        """Every existing caller passes no `rounds` and must be unaffected."""
        self.assertEqual(audit.logical_calls(10), audit.logical_calls(10, rounds=5))
        self.assertEqual(audit.affordable_findings(200),
                         audit.affordable_findings(200, rounds=5))


class ConcurrencyTest(unittest.TestCase):
    """The property the whole feature exists for. Phase 6 watched Copilot run
    six 'parallel' category scans as a sequence of greps and report them as
    parallel — a guarantee that lives in a sentence is a suggestion. The pool
    is the guarantee, so it gets a test rather than a one-off measurement."""

    DELAY = 0.05
    N = 6

    def _elapsed(self, concurrency):
        thunks = [lambda: time.sleep(self.DELAY) for _ in range(self.N)]
        start = time.monotonic()
        audit.make_run(concurrency)(thunks)
        return time.monotonic() - start

    def test_the_pool_beats_the_sequential_floor(self):
        elapsed = self._elapsed(self.N)
        self.assertLess(elapsed, self.DELAY * self.N / 2,
                        "make_run did not parallelize")

    def test_concurrency_one_is_sequential(self):
        """Pins the other side: --concurrency 1 must really serialize, or the
        live wall-clock comparison it exists for would measure nothing."""
        self.assertGreater(self._elapsed(1), self.DELAY * self.N * 0.8)

    def test_the_pool_returns_results_in_submission_order(self):
        """The pool's other contract, and the one with teeth.
        `audit_engine.verify_all` regroups a flat wave by index, so a `run` that
        returned completion order (`as_completed`) would hand every finding its
        neighbour's verdicts — and a real vulnerability whose neighbours were
        refuted then reaches `upheld == 0` and is dropped inside the engine with
        no message anywhere. The sleeps are reversed, so completion order is
        provably not submission order.
        """
        def thunk(i):
            def run_one():
                time.sleep((self.N - i) * 0.01)
                return i
            return run_one

        thunks = [thunk(i) for i in range(self.N)]
        self.assertEqual(audit.make_run(self.N)(thunks), list(range(self.N)))
        self.assertEqual(audit.make_run(1)(thunks), list(range(self.N)))


class AskTest(unittest.TestCase):
    def _completed(self, stdout):
        return mock.Mock(returncode=0, stdout=stdout, stderr="")

    def test_valid_payload_is_returned(self):
        budget = audit.Budget(max_calls=5)
        ask = audit.make_ask("copilot", budget)
        with mock.patch("subprocess.run", return_value=self._completed('{"findings": []}')):
            self.assertEqual(ask("p", schema=audit.audit_io.FINDER_SCHEMA), {"findings": []})

    def test_invalid_payload_is_retried_then_gives_up(self):
        budget = audit.Budget(max_calls=5)
        ask = audit.make_ask("copilot", budget, retries=1)
        with mock.patch("subprocess.run",
                        return_value=self._completed("no json here")) as run:
            self.assertIsNone(ask("p", schema=audit.audit_io.FINDER_SCHEMA))
        self.assertEqual(run.call_count, 2)  # first attempt + one retry

    def test_schema_violation_is_retried(self):
        budget = audit.Budget(max_calls=5)
        ask = audit.make_ask("copilot", budget, retries=1)
        bad = json.dumps({"findings": [{"category": "nope"}]})
        with mock.patch("subprocess.run", return_value=self._completed(bad)) as run:
            self.assertIsNone(ask("p", schema=audit.audit_io.FINDER_SCHEMA))
        self.assertEqual(run.call_count, 2)

    def test_nonzero_exit_yields_none(self):
        budget = audit.Budget(max_calls=5)
        ask = audit.make_ask("copilot", budget, retries=0)
        with mock.patch("subprocess.run",
                        return_value=mock.Mock(returncode=1, stdout="", stderr="boom")):
            self.assertIsNone(ask("p", schema=audit.audit_io.FINDER_SCHEMA))

    def test_schemaless_call_returns_text(self):
        budget = audit.Budget(max_calls=5)
        ask = audit.make_ask("copilot", budget)
        with mock.patch("subprocess.run", return_value=self._completed("just prose")):
            self.assertEqual(ask("p"), "just prose")

    def test_every_call_is_counted(self):
        budget = audit.Budget(max_calls=5)
        ask = audit.make_ask("copilot", budget, retries=1)
        with mock.patch("subprocess.run", return_value=self._completed("nope")):
            ask("p", schema=audit.audit_io.FINDER_SCHEMA)
        self.assertEqual(budget.calls, 2)

    def test_worker_argv_is_read_only(self):
        budget = audit.Budget(max_calls=5)
        ask = audit.make_ask("copilot", budget)
        with mock.patch("subprocess.run", return_value=self._completed("x")) as run:
            ask("p")
        argv = run.call_args[0][0]
        self.assertNotIn("--allow-all-tools", argv)
        self.assertIn("--deny-tool=shell", argv)

    def test_a_subprocess_that_never_starts_still_charges_the_budget(self):
        """--max-calls is the one cost knob, so the slot is reserved *before*
        the call. No test used to make subprocess.run raise at all, so the
        whole OSError/TimeoutExpired branch was dead to the suite and the
        documented mutation check for this ordering passed against it."""
        budget = audit.Budget(max_calls=9)
        health = audit.Health()
        ask = audit.make_ask("copilot", budget, retries=1, health=health)
        with mock.patch("subprocess.run", side_effect=OSError("no such binary")):
            self.assertIsNone(ask("p", schema=audit.audit_io.FINDER_SCHEMA))
        self.assertEqual(budget.calls, 2)  # the attempt and its retry
        self.assertEqual((health.attempts, health.failures), (2, 2))
        self.assertIn("no such binary", health.last_error)

    def test_a_timed_out_worker_is_charged_and_named(self):
        budget = audit.Budget(max_calls=9)
        health = audit.Health()
        ask = audit.make_ask("copilot", budget, retries=1, health=health)
        timeout = subprocess.TimeoutExpired(cmd=["copilot"], timeout=600)
        with mock.patch("subprocess.run", side_effect=timeout):
            self.assertIsNone(ask("p", schema=audit.audit_io.FINDER_SCHEMA))
        self.assertEqual((budget.calls, health.failures), (2, 2))
        self.assertIn("timed out", health.last_error)

    def test_a_retry_tells_the_worker_what_was_wrong(self):
        """Re-sending the identical prompt can only recover a transient
        failure, never the schema failure the retry exists for: a worker that
        answered `category: "crypto"` answers it again, and the task ends
        unanswered having spent two slots on one question."""
        budget = audit.Budget(max_calls=5)
        ask = audit.make_ask("copilot", budget, retries=1)
        bad = json.dumps({"findings": [{"category": "crypto"}]})
        with mock.patch("subprocess.run", side_effect=[
            self._completed(bad), self._completed('{"findings": []}'),
        ]) as run:
            self.assertEqual(ask("p", schema=audit.audit_io.FINDER_SCHEMA),
                             {"findings": []})
        first, second = (call[0][0][2] for call in run.call_args_list)
        self.assertNotIn("rejected", first)
        self.assertIn("previous reply was rejected", second)
        self.assertIn("findings[0]", second)  # the SchemaError's own path

    def test_the_schema_reaches_extraction_not_just_validation(self):
        """Which of several JSON objects is the answer is a schema question, so
        `ask` has to hand the schema to `extract_json` and not merely validate
        whatever came back first. A worker showing the output format before
        answering used to have its own example returned, validated, and
        counted as a successful task."""
        answer = {"findings": [{"category": "injection", "severity": "critical",
                                "title": "SQLi", "description": "d",
                                "file": "src/a.js", "line": 5,
                                "recommendation": "r"}]}
        narrated = ('If nothing were found I would return {"findings": []}. '
                    'Here is what I found:\n' + json.dumps(answer))
        budget = audit.Budget(max_calls=5)
        health = audit.Health()
        ask = audit.make_ask("copilot", budget, retries=0, health=health)
        with mock.patch("subprocess.run", return_value=self._completed(narrated)):
            self.assertEqual(ask("p", schema=audit.audit_io.FINDER_SCHEMA), answer)
        self.assertEqual(health.answered, 1)

    def test_a_wire_failure_does_not_critique_an_answer_that_never_came(self):
        budget = audit.Budget(max_calls=5)
        ask = audit.make_ask("copilot", budget, retries=1)
        with mock.patch("subprocess.run", side_effect=[
            mock.Mock(returncode=1, stdout="", stderr="429"),
            self._completed('{"findings": []}'),
        ]) as run:
            ask("p", schema=audit.audit_io.FINDER_SCHEMA)
        self.assertNotIn("rejected", run.call_args_list[1][0][0][2])


class DecodingTest(unittest.TestCase):
    """Decoding happens inside `subprocess.run`, so a Mock cannot reach it.
    These drive a real child process."""

    def _adapter(self, script):
        return audit_adapter.Adapter(
            "raw", sys.executable,
            lambda prompt, model=None: [sys.executable, "-c", script],
            lambda text: text, lambda _text: None)

    def _ask(self, script, **kw):
        with mock.patch.dict(audit_adapter.ADAPTERS,
                             {"raw": self._adapter(script)}):
            ask = audit.make_ask("raw", audit.Budget(max_calls=3), retries=0, **kw)
            return ask("p", schema=audit.audit_io.FINDER_SCHEMA)

    def test_undecodable_bytes_do_not_unwind_the_whole_run(self):
        """`text=True` alone decodes strict with the locale's codec, and
        UnicodeDecodeError is a ValueError — caught by nothing between here and
        `main`. One worker's stray byte therefore took down the audit and
        discarded every batch `verify_all` had already settled and paid for.
        Noise the extractor can step over must cost one call at most."""
        script = (r"import sys; sys.stdout.buffer.write("
                  r"b'scanning \xff\xfe done\n{\"findings\": []}')")
        self.assertEqual(self._ask(script), {"findings": []})

    def test_a_worker_reporting_a_non_ascii_identifier_is_read_verbatim(self):
        """The other half, and the one that bites on Windows: `text=True`
        decodes with the ANSI code page there, so valid UTF-8 in a finding's
        text was mojibake at best and a hard failure at worst. The codec is
        pinned to what the workers actually emit."""
        payload = {"findings": [{"category": "secrets", "severity": "high",
                                 "title": "ключ в исходнике", "description": "d",
                                 "file": "src/конфиг.js", "line": 3,
                                 "recommendation": "r"}]}
        script = ("import sys; sys.stdout.buffer.write("
                  + repr(json.dumps(payload).encode("utf-8")) + ")")
        got = self._ask(script)
        self.assertEqual(got["findings"][0]["title"], "ключ в исходнике")
        self.assertEqual(got["findings"][0]["file"], "src/конфиг.js")


class HealthTest(unittest.TestCase):
    """Failures used to be silent `continue`s, which is how a broken run came
    back looking like a clean codebase."""

    def _ask(self, completed, **kw):
        health = audit.Health()
        ask = audit.make_ask("copilot", audit.Budget(max_calls=9), health=health, **kw)
        with mock.patch("subprocess.run", return_value=completed):
            ask("p", schema=audit.audit_io.FINDER_SCHEMA)
        return health

    def test_an_error_inside_the_envelope_is_reported(self):
        """Live in phase 7: `claude -p` answered returncode 1, EMPTY stderr, and
        `result: "Failed to authenticate: OAuth session expired..."` inside its
        JSON envelope. The driver said `last error: exit 1` and the reason had
        to be found by reproducing the call by hand."""
        envelope = json.dumps([{"type": "result", "is_error": True,
                                "result": "Failed to authenticate: OAuth session "
                                          "expired and could not be refreshed"}])
        budget = audit.Budget(max_calls=5)
        health = audit.Health()
        ask = audit.make_ask("claude", budget, retries=0, health=health)
        with mock.patch("subprocess.run", return_value=mock.Mock(
                returncode=1, stdout=envelope, stderr="")):
            self.assertIsNone(ask("hi"))
        self.assertIn("OAuth session expired", health.last_error)

    def test_stderr_still_wins_when_there_is_some(self):
        budget = audit.Budget(max_calls=5)
        health = audit.Health()
        ask = audit.make_ask("copilot", budget, retries=0, health=health)
        with mock.patch("subprocess.run", return_value=mock.Mock(
                returncode=1, stdout="noise", stderr="429 rate limited")):
            ask("hi")
        self.assertIn("429 rate limited", health.last_error)

    def test_a_silent_failure_still_names_the_exit_code(self):
        budget = audit.Budget(max_calls=5)
        health = audit.Health()
        ask = audit.make_ask("copilot", budget, retries=0, health=health)
        with mock.patch("subprocess.run", return_value=mock.Mock(
                returncode=7, stdout="", stderr="")):
            ask("hi")
        self.assertEqual(health.last_error, "exit 7")

    def test_a_parser_that_raises_does_not_crash_the_run(self):
        boom = audit_adapter.Adapter("boom", "boom", lambda p, model=None: ["boom"],
                                     mock.Mock(side_effect=ValueError("bad")),
                                     lambda _t: None)
        completed = mock.Mock(returncode=1, stdout="raw output", stderr="")
        self.assertEqual(audit.failure_reason(boom, completed), "raw output")

    def test_a_nonzero_exit_records_the_stderr(self):
        health = self._ask(mock.Mock(returncode=1, stdout="", stderr="not authenticated"))
        self.assertEqual((health.answered, health.unanswered), (0, 1))
        self.assertEqual(health.failures, 2)  # attempt + retry
        self.assertIn("not authenticated", health.last_error)

    def test_unparseable_output_is_recorded_as_a_failure(self):
        health = self._ask(mock.Mock(returncode=0, stdout="I cannot do that", stderr=""))
        self.assertEqual(health.answered, 0)
        self.assertIn("no JSON", health.last_error)

    def test_a_schema_violation_is_recorded_with_its_path(self):
        bad = json.dumps({"findings": [{"category": "telepathy"}]})
        health = self._ask(mock.Mock(returncode=0, stdout=bad, stderr=""))
        self.assertEqual(health.answered, 0)
        self.assertIn("findings[0]", health.last_error)

    def test_a_good_call_counts_as_answered(self):
        health = self._ask(mock.Mock(returncode=0, stdout='{"findings": []}', stderr=""))
        self.assertEqual((health.answered, health.unanswered, health.failures), (1, 0, 0))

    def test_a_retry_that_succeeds_is_one_answered_task_and_one_failure(self):
        """A flake must not poison the trust decision: the task was answered."""
        health = audit.Health()
        ask = audit.make_ask("copilot", audit.Budget(max_calls=9), health=health)
        with mock.patch("subprocess.run", side_effect=[
            mock.Mock(returncode=1, stdout="", stderr="flake"),
            mock.Mock(returncode=0, stdout='{"findings": []}', stderr=""),
        ]):
            self.assertEqual(ask("p", schema=audit.audit_io.FINDER_SCHEMA),
                             {"findings": []})
        self.assertEqual((health.answered, health.unanswered), (1, 0))
        self.assertEqual((health.attempts, health.failures), (2, 1))


class MainTest(unittest.TestCase):
    def test_no_agent_cli_degrades_with_guidance(self):
        with mock.patch("audit_adapter.detect", return_value=None):
            code, _, err = run_main(["scan", "--yes"])
        self.assertEqual(code, audit.EXIT_NOTHING_TO_DO)
        # The mode that actually ran. `scan` used to be told that *audit*
        # needed a CLI, and pointed at `freya-codebase-security-scan scan` —
        # a skill name, not a binary, and the command just run.
        self.assertIn("scan needs an agent CLI", err)
        self.assertIn("in-loop", err)

    def test_dry_run_reports_the_plan_and_calls_nothing(self):
        with mock.patch("audit_adapter.detect", return_value="copilot"), \
             mock.patch("subprocess.run") as run:
            code, out, err = run_main(["--dry-run"])
        self.assertEqual(code, 0)
        self.assertIn("worst case", err.lower())
        self.assertEqual(out, "")  # stdout stays a pure data channel
        run.assert_not_called()

    def test_unknown_agent_exits_two(self):
        code, _, err = run_main(["--agent", "nope", "--yes"])
        self.assertEqual(code, 2)
        self.assertIn("unknown agent", err)

    def test_findings_are_emitted_as_json(self):
        survivor = {"file": "a.js", "disposition": "confirmed"}
        with mock.patch("audit_adapter.detect", return_value="copilot"), \
             mock.patch("audit_engine.audit",
                        return_value=audit_engine.Result([survivor], 0, False)):
            code, out, _ = run_main(["--yes", "--format", "json"])
        self.assertEqual(code, 0)
        self.assertEqual(json.loads(out), [survivor])

    def test_a_missing_project_is_rejected_before_anything_is_spent(self):
        """cwd=<missing> raises an OSError that `ask` counts as one more failed
        call, so a typo used to buy a full round of failures and an empty
        result that read as clean."""
        with mock.patch("audit_adapter.detect", return_value="copilot"), \
             mock.patch("subprocess.run") as run:
            code, out, err = run_main(["--yes", "--project", "/no/such/dir"])
        self.assertEqual(code, audit.EXIT_FAILED)
        self.assertIn("not a directory", err)
        self.assertEqual(out, "")
        run.assert_not_called()

    def test_a_failed_context_call_stops_before_the_finders_run(self):
        """The context call is call #1. If it fails every finder will too, and
        a run of empty finders is indistinguishable from a clean codebase."""
        dead = mock.Mock(returncode=1, stdout="", stderr="401 unauthorized")
        with mock.patch("audit_adapter.detect", return_value="copilot"), \
             mock.patch("subprocess.run", return_value=dead) as run:
            code, out, err = run_main(["--yes"])
        self.assertEqual(code, audit.EXIT_FAILED)
        self.assertEqual(out, "")
        self.assertIn("401 unauthorized", err)
        self.assertLessEqual(run.call_count, 2)  # context + its one retry, no finders

    def test_a_run_where_every_finder_failed_is_never_reported_as_clean(self):
        """The headline defect: 26 failed calls used to exit 0 with `[]`, and the
        skill's main loop then wrote a report saying the codebase was clean.

        The context call succeeds here, so a naive "did anything work?" check
        would pass. What matters is that no *finder* got an answer."""
        def reply(argv, **kw):
            prompt = argv[argv.index("-p") + 1]
            if "Category:" in prompt:
                return mock.Mock(returncode=1, stdout="", stderr="rate limited")
            return mock.Mock(returncode=0, stdout="context prose", stderr="")

        with mock.patch("audit_adapter.detect", return_value="copilot"), \
             mock.patch("subprocess.run", side_effect=reply):
            code, out, err = run_main(["--yes", "--concurrency", "1"])
        self.assertEqual(code, audit.EXIT_FAILED)
        self.assertIn("cannot be told apart from a broken run", err)
        self.assertIn("rate limited", err)

    def test_exhausting_the_budget_keeps_the_findings_already_verified(self):
        """Used to return nothing and exit 2 — the entire spend, discarded.

        12 findings verify in batches of VERIFY_BATCH(8) + 4. The ceiling is set
        to die inside the second batch, so the first batch must survive."""
        seq = {"n": 0}

        def reply(argv, **kw):
            prompt = argv[argv.index("-p") + 1]
            if "Lens:" in prompt:
                return mock.Mock(returncode=0, stderr="", stdout=json.dumps(
                    {"lens": "exploitability", "verdict": "upheld", "reason": "r"}))
            if "Category:" in prompt:
                seq["n"] += 1
                i = seq["n"]
                return mock.Mock(returncode=0, stderr="", stdout=json.dumps(
                    {"findings": [{"category": "injection", "severity": "high",
                                   "title": "t", "description": "d",
                                   "file": f"f{i}_{j}.js", "line": i * 10 + j,
                                   "recommendation": "r"} for j in range(2)]}))
            return mock.Mock(returncode=0, stdout="context prose", stderr="")

        with mock.patch("audit_adapter.detect", return_value="copilot"), \
             mock.patch("subprocess.run", side_effect=reply):
            code, out, err = run_main(["--yes", "--concurrency", "1",
                                       "--max-calls", "35", "--max-findings", "12"])
        self.assertEqual(code, audit.EXIT_INCOMPLETE)
        self.assertEqual(len(json.loads(out)), audit_engine.VERIFY_BATCH)
        self.assertIn("INCOMPLETE", err)
        self.assertIn("clean bill of health", err)  # truncation is stated, not implied

    def test_max_findings_is_derived_from_the_call_ceiling(self):
        with mock.patch("audit_adapter.detect", return_value="copilot"):
            _, _, err = run_main(["--dry-run", "--max-calls", "200"])
        self.assertIn("up to 23 findings", err)
        self.assertNotIn("WARNING", err)

    def test_an_unaffordable_max_findings_is_called_out(self):
        """The old defaults in numbers: 40 findings against an 80 ceiling."""
        with mock.patch("audit_adapter.detect", return_value="copilot"):
            _, _, err = run_main(["--dry-run", "--max-calls", "80",
                                  "--max-findings", "40"])
        self.assertIn("WARNING", err)
        self.assertIn("truncated", err)


class ConfirmationTest(unittest.TestCase):
    """Exit 1 used to carry two meanings. SKILL.md defines it as "no agent CLI
    on PATH — fall back to the in-loop scan", and the confirmation gate returned
    it too, so an unattended run of the documented command was read as a missing
    CLI and the agent silently reverted to the prose fan-out the driver exists
    to replace — on a machine where the CLI was installed."""

    def test_a_declined_run_and_a_missing_cli_are_told_apart(self):
        with mock.patch("audit_adapter.detect", return_value=None):
            missing, _, _ = run_main(["--yes"])
        with mock.patch("audit_adapter.detect", return_value="copilot"), \
             mock.patch("sys.stdin", _FakeStdin(tty=False)):
            declined, _, _ = run_main([])
        self.assertEqual(missing, audit.EXIT_NOTHING_TO_DO)
        self.assertEqual(declined, audit.EXIT_DECLINED)
        self.assertNotEqual(missing, declined)

    def test_no_tty_refuses_instead_of_blocking_on_input(self):
        with mock.patch("audit_adapter.detect", return_value="copilot"), \
             mock.patch("sys.stdin", _FakeStdin(tty=False)), \
             mock.patch("subprocess.run") as run:
            code, out, err = run_main([])
        self.assertEqual(code, audit.EXIT_DECLINED)
        self.assertIn("--yes", err)       # the remedy, spelled out
        self.assertIn("--dry-run", err)
        self.assertEqual(out, "")
        run.assert_not_called()

    def test_the_prompt_never_reaches_stdout(self):
        """stdout is the channel the skill parses as a JSON array, and
        `input(prompt)` writes to it: a human answering `y` while redirecting
        stdout to a file got `Proceed? [y/N] [...]` — invalid JSON — in it."""
        with mock.patch("audit_adapter.detect", return_value="copilot"), \
             mock.patch("sys.stdin", _FakeStdin("n\n")), \
             mock.patch("subprocess.run") as run:
            code, out, err = run_main([])
        self.assertEqual(code, audit.EXIT_DECLINED)
        self.assertEqual(out, "")
        self.assertIn("Proceed?", err)
        run.assert_not_called()

    def test_a_yes_at_a_terminal_still_runs(self):
        """The gate must still be a gate, not a blanket refusal."""
        with mock.patch("audit_adapter.detect", return_value="copilot"), \
             mock.patch("sys.stdin", _FakeStdin("y\n")), \
             mock.patch("audit_engine.audit",
                        return_value=audit_engine.Result([], 0, False)):
            code, out, _ = run_main([])
        self.assertEqual(code, audit.EXIT_OK)
        self.assertEqual(json.loads(out), [])


class CeilingRefusalTest(unittest.TestCase):
    """A configuration whose only possible output is a false clean bill of
    health must not be allowed to spend a cent."""

    def test_a_ceiling_too_small_to_verify_anything_refuses_to_start(self):
        """The headline defect. `--max-calls 60` derived --max-findings 0,
        `discover` returned `found[:0]` on the first productive round, stdout
        was `[]` and the exit code 0 — which SKILL.md defines verbatim as
        clean, for a codebase whose vulnerabilities the run had just found."""
        with mock.patch("audit_adapter.detect", return_value="copilot"), \
             mock.patch("subprocess.run") as run:
            code, out, err = run_main(["--yes", "--max-calls", "60"])
        self.assertEqual(code, audit.EXIT_FAILED)
        self.assertEqual(out, "")  # never `[]`, which reads as clean
        self.assertIn("refusing to start", err)
        self.assertIn("audit needs at least --max-calls 68", err)
        run.assert_not_called()

    def test_the_minimum_is_mode_aware(self):
        with mock.patch("audit_adapter.detect", return_value="copilot"), \
             mock.patch("subprocess.run") as run:
            code, _, err = run_main(["scan", "--yes", "--max-calls", "19"])
        self.assertEqual(code, audit.EXIT_FAILED)
        self.assertIn("scan needs at least --max-calls 20", err)
        run.assert_not_called()

    def test_an_explicit_zero_max_findings_is_refused_too(self):
        with mock.patch("audit_adapter.detect", return_value="copilot"), \
             mock.patch("subprocess.run") as run:
            code, _, err = run_main(["--yes", "--max-findings", "0"])
        self.assertEqual(code, audit.EXIT_FAILED)
        self.assertIn("refusing to start", err)
        run.assert_not_called()

    def test_a_zero_call_ceiling_is_a_message_not_a_traceback(self):
        """`Budget.spend` raises on call #1 when the ceiling is 0, and the
        context call is the one `ask` the engine does not wrap in
        `except Halted` — so it escaped `main()` as a raw traceback."""
        with mock.patch("audit_adapter.detect", return_value="copilot"), \
             mock.patch("subprocess.run") as run:
            code, out, err = run_main(["--yes", "--max-calls", "0"])
        self.assertEqual(code, audit.EXIT_FAILED)
        self.assertIn("--max-calls must be at least 1", err)
        self.assertEqual(out, "")
        run.assert_not_called()

    def test_the_shipped_default_is_not_refused(self):
        """The guard must not fire on the configuration everybody runs."""
        with mock.patch("audit_adapter.detect", return_value="copilot"):
            code, _, err = run_main(["--dry-run"])
        self.assertEqual(code, audit.EXIT_OK)
        self.assertNotIn("refusing to start", err)


class ScanModeTest(unittest.TestCase):
    """`freya security scan` — the same driver, one round of discovery."""

    FINDING = {"file": "a.js", "line": 1, "category": "injection",
               "severity": "high", "title": "SQLi",
               "description": "concatenated query", "recommendation": "parameterize"}

    def _reply(self, prompts):
        def reply(argv, **kw):
            prompt = argv[argv.index("-p") + 1]
            prompts.append(prompt)
            if "Category:" in prompt:
                return mock.Mock(returncode=0, stderr="", stdout=json.dumps(
                    {"findings": [self.FINDING]
                     if "Category: injection." in prompt else []}))
            if "REFUTE" in prompt:
                lens = next(l for l in audit_engine.SKEPTICS if f"Lens: {l}" in prompt)
                return mock.Mock(returncode=0, stderr="", stdout=json.dumps(
                    {"lens": lens, "verdict": "upheld", "reason": "real"}))
            return mock.Mock(returncode=0, stdout="context prose", stderr="")
        return reply

    def test_scan_runs_exactly_one_round_of_finders(self):
        """Audit would run this fixture for four more rounds: the finding is
        fresh in round 1, so `dry` resets and K_EMPTY buys two more rounds."""
        prompts = []
        with mock.patch("audit_adapter.detect", return_value="copilot"), \
             mock.patch("subprocess.run", side_effect=self._reply(prompts)):
            code, out, err = run_main(["scan", "--yes", "--concurrency", "1"])
        self.assertEqual(code, audit.EXIT_OK)
        self.assertEqual(sum(1 for p in prompts if "Category:" in p), 6)
        self.assertEqual(len(json.loads(out)), 1)

    def test_audit_on_the_same_fixture_runs_more(self):
        """The control. Same replies, no preset — discovery keeps going."""
        prompts = []
        with mock.patch("audit_adapter.detect", return_value="copilot"), \
             mock.patch("subprocess.run", side_effect=self._reply(prompts)):
            run_main(["audit", "--yes", "--concurrency", "1"])
        self.assertGreater(sum(1 for p in prompts if "Category:" in p), 6)

    def test_scan_verifies_with_all_three_lenses(self):
        prompts = []
        with mock.patch("audit_adapter.detect", return_value="copilot"), \
             mock.patch("subprocess.run", side_effect=self._reply(prompts)):
            _, out, _ = run_main(["scan", "--yes", "--concurrency", "1"])
        self.assertEqual(json.loads(out)[0]["verification"]["lenses"],
                         audit_engine.SKEPTICS)

    def test_scan_dry_run_prints_the_one_round_plan(self):
        with mock.patch("audit_adapter.detect", return_value="copilot"), \
             mock.patch("subprocess.run") as run:
            code, out, err = run_main(["scan", "--dry-run", "--max-calls", "200"])
        self.assertEqual(code, audit.EXIT_OK)
        self.assertIn("1x6 finders", err)
        self.assertIn("up to 31 findings", err)
        self.assertEqual(out, "")
        run.assert_not_called()

    def test_audit_dry_run_still_prints_five_rounds(self):
        with mock.patch("audit_adapter.detect", return_value="copilot"):
            _, _, err = run_main(["audit", "--dry-run", "--max-calls", "200"])
        self.assertIn("5x6 finders", err)
        self.assertIn("up to 23 findings", err)

    def test_the_mode_is_named_in_the_plan(self):
        with mock.patch("audit_adapter.detect", return_value="copilot"):
            _, _, err = run_main(["scan", "--dry-run"])
        self.assertIn("mode:         scan", err)

    def test_an_unknown_mode_is_rejected(self):
        with self.assertRaises(SystemExit):
            run_main(["sweep", "--dry-run"])

    def test_a_degraded_scan_is_incomplete_too(self):
        """One round has fewer chances to recover from a failure than five, so
        the guard matters more here, not less."""
        def reply(argv, **kw):
            prompt = argv[argv.index("-p") + 1]
            if "Category:" in prompt:
                if "Category: injection." in prompt:
                    return mock.Mock(returncode=0, stderr="", stdout=json.dumps(
                        {"findings": [self.FINDING]}))
                return mock.Mock(returncode=1, stdout="", stderr="rate limited")
            if "REFUTE" in prompt:
                return mock.Mock(returncode=0, stderr="", stdout=json.dumps(
                    {"lens": "exploitability", "verdict": "upheld", "reason": "real"}))
            return mock.Mock(returncode=0, stdout="context prose", stderr="")

        with mock.patch("audit_adapter.detect", return_value="copilot"), \
             mock.patch("subprocess.run", side_effect=reply):
            code, out, err = run_main(["scan", "--yes", "--concurrency", "1"])
        self.assertEqual(code, audit.EXIT_INCOMPLETE)
        self.assertIn("INCOMPLETE", err)
        self.assertIn("rate limited", err)
        self.assertIn("SQLi", out)

    def test_scan_workers_are_still_read_only(self):
        """A preset must not open a write path."""
        argvs = []

        def reply(argv, **kw):
            argvs.append(argv)
            return mock.Mock(returncode=0, stdout="context prose", stderr="")

        with mock.patch("audit_adapter.detect", return_value="copilot"), \
             mock.patch("subprocess.run", side_effect=reply):
            run_main(["scan", "--yes", "--concurrency", "1"])
        self.assertTrue(argvs)
        for argv in argvs:
            self.assertIn("--deny-tool=write", argv)
            self.assertIn("--deny-tool=shell", argv)
            self.assertNotIn("--allow-all-tools", argv)


class DegradedRunTest(unittest.TestCase):
    """Phase 6 validation, on a real 299-file repository: 22 of 27 calls failed,
    three findings survived, and the run reported them exactly as a complete
    audit reports its results — no mention of the failures, no `last error`,
    exit 0. The existing guards only catch the all-or-nothing shapes (every call
    failing, or nothing surviving); this is the shape between them."""

    def test_a_mostly_failed_run_is_reported_as_incomplete(self):
        finding = {"file": "a.js", "line": 1, "category": "injection",
                   "severity": "high", "title": "SQLi",
                   "description": "concatenated query", "recommendation": "parameterize"}

        def reply(argv, **kw):
            prompt = argv[argv.index("-p") + 1]
            if "Category:" in prompt:
                # One category answers; the rest fail. Discovery is degraded but
                # not dead, which is precisely the case that used to slip through.
                if "Category: injection." in prompt:
                    return mock.Mock(returncode=0, stdout=json.dumps(
                        {"findings": [finding]}), stderr="")
                return mock.Mock(returncode=1, stdout="", stderr="rate limited")
            if "REFUTE" in prompt:
                return mock.Mock(returncode=0, stdout=json.dumps(
                    {"lens": "exploitability", "verdict": "upheld",
                     "reason": "real"}), stderr="")
            return mock.Mock(returncode=0, stdout="context prose", stderr="")

        with mock.patch("audit_adapter.detect", return_value="copilot"), \
             mock.patch("subprocess.run", side_effect=reply):
            code, out, err = run_main(["--yes", "--concurrency", "1"])

        self.assertEqual(code, audit.EXIT_INCOMPLETE)
        self.assertIn("INCOMPLETE", err)
        self.assertIn("got no usable answer", err)
        self.assertIn("rate limited", err)          # last_error must be visible
        self.assertIn("SQLi", out)                  # survivors are still reported

    def test_a_fully_answered_run_is_not_flagged_incomplete(self):
        finding = {"file": "a.js", "line": 1, "category": "injection",
                   "severity": "high", "title": "SQLi",
                   "description": "concatenated query", "recommendation": "parameterize"}

        def reply(argv, **kw):
            prompt = argv[argv.index("-p") + 1]
            if "Category:" in prompt:
                return mock.Mock(returncode=0, stdout=json.dumps(
                    {"findings": [finding] if "Category: injection." in prompt else []}), stderr="")
            if "REFUTE" in prompt:
                return mock.Mock(returncode=0, stdout=json.dumps(
                    {"lens": "exploitability", "verdict": "upheld",
                     "reason": "real"}), stderr="")
            return mock.Mock(returncode=0, stdout="context prose", stderr="")

        with mock.patch("audit_adapter.detect", return_value="copilot"), \
             mock.patch("subprocess.run", side_effect=reply):
            code, out, err = run_main(["--yes", "--concurrency", "1"])

        self.assertEqual(code, audit.EXIT_OK)
        self.assertNotIn("INCOMPLETE", err)


def _finding(i):
    return {"category": "injection", "severity": "critical", "title": f"SQLi {i}",
            "description": "concatenated query", "file": f"src/f{i}.js",
            "line": 5, "recommendation": "parameterize"}


class TruncatedDiscoveryTest(unittest.TestCase):
    """Truncation is incompleteness.

    `discover` used to end in a bare `return found[:max_findings]`: findings the
    run had already discovered and paid for were deleted, the remaining rounds
    never ran, and every health guard still saw a perfectly healthy run — so the
    driver exited 0 on a codebase it had stopped reading, and SKILL.md's exit
    table calls 0 "Complete. The JSON array is the whole result."
    """

    def _reply(self):
        seq = {"n": 0}

        def reply(argv, **kw):
            prompt = argv[argv.index("-p") + 1]
            if "Lens:" in prompt:
                lens = next(l for l in audit_engine.SKEPTICS if f"Lens: {l}" in prompt)
                return mock.Mock(returncode=0, stderr="", stdout=json.dumps(
                    {"lens": lens, "verdict": "upheld", "reason": "reachable"}))
            if "Category:" in prompt:
                seq["n"] += 1
                return mock.Mock(returncode=0, stderr="", stdout=json.dumps(
                    {"findings": [_finding(seq["n"])]}))
            return mock.Mock(returncode=0, stdout="context prose", stderr="")

        return reply

    def test_a_cap_that_discarded_findings_is_never_reported_as_complete(self):
        with mock.patch("audit_adapter.detect", return_value="copilot"), \
             mock.patch("subprocess.run", side_effect=self._reply()):
            code, out, err = run_main(["--yes", "--concurrency", "1",
                                       "--max-calls", "200", "--max-findings", "2"])
        self.assertEqual(code, audit.EXIT_INCOMPLETE)
        self.assertEqual(len(json.loads(out)), 2)   # survivors are still reported
        self.assertIn("INCOMPLETE", err)
        self.assertIn("4 discovered finding(s) discarded", err)  # round 1 found six
        self.assertIn("clean bill of health", err)

    def test_a_cap_that_discarded_nothing_is_still_not_a_complete_sweep(self):
        """Zero discarded is not exhaustive: rounds 2..5 never ran, so
        loop-until-dry — the entire point of `audit` — never happened."""
        with mock.patch("audit_adapter.detect", return_value="copilot"), \
             mock.patch("subprocess.run", side_effect=self._reply()):
            code, out, err = run_main(["--yes", "--concurrency", "1",
                                       "--max-calls", "200", "--max-findings", "6"])
        self.assertEqual(code, audit.EXIT_INCOMPLETE)
        self.assertIn("0 discovered finding(s) discarded", err)
        self.assertIn("remaining rounds never ran", err)

    def test_a_run_that_went_dry_under_the_cap_is_complete(self):
        """The control. Without it the fix could just be `always INCOMPLETE`."""
        def reply(argv, **kw):
            prompt = argv[argv.index("-p") + 1]
            if "Category:" in prompt:
                return mock.Mock(returncode=0, stderr="", stdout='{"findings": []}')
            return mock.Mock(returncode=0, stdout="context prose", stderr="")

        with mock.patch("audit_adapter.detect", return_value="copilot"), \
             mock.patch("subprocess.run", side_effect=reply):
            code, out, err = run_main(["--yes", "--concurrency", "1"])
        self.assertEqual(code, audit.EXIT_OK)
        self.assertEqual(json.loads(out), [])
        self.assertNotIn("INCOMPLETE", err)


class BannerHonestyTest(unittest.TestCase):
    """The INCOMPLETE banners opened with "The N findings below are verified and
    real" — unconditionally, including in the phase-6 run they were written for,
    where every skeptic call failed and all three survivors reached
    `disposition` with zero verdicts. The JSON beside the banner said
    `needs-review` and `Upheld 0/0`. A guard against a run overstating itself
    must not overstate itself."""

    def _run_with_dead_skeptics(self):
        def reply(argv, **kw):
            prompt = argv[argv.index("-p") + 1]
            if "Lens:" in prompt:
                return mock.Mock(returncode=1, stdout="", stderr="quota exhausted")
            if "Category:" in prompt:
                return mock.Mock(returncode=0, stderr="", stdout=json.dumps(
                    {"findings": [_finding(1)]
                     if "Category: injection." in prompt else []}))
            return mock.Mock(returncode=0, stdout="context prose", stderr="")

        with mock.patch("audit_adapter.detect", return_value="copilot"), \
             mock.patch("subprocess.run", side_effect=reply):
            return run_main(["--yes", "--concurrency", "1"])

    def test_a_banner_never_claims_a_verification_that_did_not_happen(self):
        code, out, err = self._run_with_dead_skeptics()
        self.assertEqual(code, audit.EXIT_INCOMPLETE)
        self.assertNotIn("verified and real", err)
        self.assertIn("NONE of the 1 findings below could be verified", err)
        # ...and the banner agrees with the JSON the skill actually consumes.
        settled = json.loads(out)[0]
        self.assertEqual(settled["disposition"], "needs-review")
        self.assertEqual(settled["verification"]["total"], 0)

    def test_a_fully_verified_degraded_run_says_so(self):
        clause = audit.verified_clause(
            [{"verification": {"total": 3}}, {"verification": {"total": 3}}])
        self.assertEqual(clause, "The 2 findings below completed verification")

    def test_a_partly_verified_run_counts_both_sides(self):
        clause = audit.verified_clause(
            [{"verification": {"total": 3}}, {"verification": {"total": 0}}])
        self.assertEqual(clause, "1 of the 2 findings below completed verification")


class DefaultConcurrencyTest(unittest.TestCase):
    """DEFAULT_CONCURRENCY (4) is what `freya security scan` actually runs, and
    every other end-to-end test pinned `--concurrency 1` — so Budget's lock,
    Health's counters and `verify_all`'s index regrouping had zero coverage on
    the shipped path.

    The verdicts differ per finding and the replies are staggered, so a pool
    that lost submission order usually mis-pairs them here. Usually, not
    always: real thread scheduling is the point of this class, which makes it
    coverage rather than a proof. ConcurrencyTest owns the deterministic
    ordering proof.
    """

    KEEP = ("src/keep1.js", "src/keep2.js")

    def _reply(self):
        def reply(argv, **kw):
            prompt = argv[argv.index("-p") + 1]
            if "Lens:" in prompt:
                lens = next(l for l in audit_engine.SKEPTICS if f"Lens: {l}" in prompt)
                # Stagger so completion order is not submission order.
                time.sleep(0.02 if "keep1.js" in prompt else 0.001)
                refuted = "drop.js" in prompt
                return mock.Mock(returncode=0, stderr="", stdout=json.dumps(
                    {"lens": lens, "verdict": "refuted" if refuted else "upheld",
                     "reason": "r"}))
            if "Category:" in prompt:
                for name, category in (("src/keep1.js", "auth"),
                                       ("src/drop.js", "injection"),
                                       ("src/keep2.js", "secrets")):
                    if f"Category: {category}." in prompt:
                        return mock.Mock(returncode=0, stderr="", stdout=json.dumps(
                            {"findings": [dict(_finding(1), file=name,
                                               category=category)]}))
                return mock.Mock(returncode=0, stderr="", stdout='{"findings": []}')
            return mock.Mock(returncode=0, stdout="context prose", stderr="")

        return reply

    def test_the_shipped_defaults_run_end_to_end_and_keep_verdicts_paired(self):
        with mock.patch("audit_adapter.detect", return_value="copilot"), \
             mock.patch("subprocess.run", side_effect=self._reply()):
            code, out, err = run_main(["scan", "--yes"])
        self.assertEqual(code, audit.EXIT_OK, err)
        survivors = json.loads(out)
        self.assertEqual(sorted(s["file"] for s in survivors), list(self.KEEP))
        # The unanimously refuted finding is gone, and only that one.
        self.assertTrue(all(s["disposition"] == "confirmed" for s in survivors))

    def test_the_default_concurrency_is_the_one_being_exercised(self):
        """Pins the premise: if DEFAULT_CONCURRENCY became 1 this class would
        quietly stop testing the pool at all."""
        self.assertEqual(audit.DEFAULT_CONCURRENCY, 4)


# Last, not mid-file: this used to sit above DegradedRunTest, so running the
# file directly (rather than through `-m unittest`) executed unittest.main()
# before that class existed and silently skipped both of its tests.
if __name__ == "__main__":
    unittest.main()
