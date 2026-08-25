#!/usr/bin/env python3
"""`freya security audit` / `freya security scan` — driver-owned security runs.

Owns the control flow the retired Claude-only saved-script engine used to own,
and calls whatever agent CLI is installed as a headless read-only worker.

TWO MODES, ONE DRIVER. `scan` is a *preset*: one round of discovery instead of
MAX_ROUNDS, and otherwise byte-for-byte the same run. It exists because phase 6
watched Copilot answer "run the six category scans in parallel" with a sequence
of greps it performed itself, and then report them as parallel — the agent's own
account of its work cannot tell you whether the fan-out happened. Scheduling the
work here is the only version of that guarantee that is not a suggestion.

The preset cuts rounds and NOT skeptics. With one lens a single refutation is a
unanimous one, `audit_engine.disposition` reaches `upheld == 0`, and a real
vulnerability is deleted with no trace in the report. Cheaper, and wrong.

COST. The spike measured $0.396 for one finder worker on a trivial fixture,
and the worst case here is 1 + rounds*6 + 3*findings calls. So the caps are
on by default, the plan is printed before anything is spent, and the run stops
the moment the call budget is exhausted rather than silently continuing.
"""

from __future__ import annotations

import argparse
import concurrent.futures
import json
import os
import subprocess
import sys
import threading
from collections import namedtuple

import audit_adapter
import audit_engine
import audit_io

DEFAULT_MAX_CALLS = 200
DEFAULT_CONCURRENCY = 4
DEFAULT_TIMEOUT = 600
DEFAULT_RETRIES = 1

Mode = namedtuple("Mode", "name rounds blurb")

#: The only thing a mode may vary is how many discovery rounds it buys. Lenses,
#: dedup, the read-only allowlist and every guard are shared deliberately: two
#: modes with two definitions of "a finding" would drift, and the cheaper one
#: would be the one that drifted toward missing things.
MODES = {
    "audit": Mode("audit", audit_engine.MAX_ROUNDS,
                  "exhaustive loop-until-dry discovery"),
    "scan": Mode("scan", 1, "one round of discovery"),
}

#: Exit codes. 3 is distinct so the skill can tell a truncated audit from a
#: complete one without parsing stderr.
#:
#: 4 exists because 1 used to carry two meanings. SKILL.md defines exit 1 as
#: "no agent CLI on PATH — fall back to the in-loop scan", and the confirmation
#: gate returned it too: an unattended run of the documented command aborted at
#: EOF, the agent read exit 1 in that table, concluded the CLI was missing, and
#: silently reverted to the prose fan-out phase 7 exists to eliminate — on a
#: machine where the CLI was in fact installed. 1 now means only the one thing.
EXIT_OK = 0
EXIT_NOTHING_TO_DO = 1
EXIT_FAILED = 2
EXIT_INCOMPLETE = 3
EXIT_DECLINED = 4


class BudgetExhausted(audit_engine.Halted):
    """The run hit its call ceiling. A Halted, so the engine keeps its work."""


class Budget:
    """Counts agent calls, and spend where the adapter reports it.

    One lock, because `run` executes thunks on a pool: without it the
    check-then-increment in `spend` could let concurrent workers past a full
    ceiling, and `usd` could lose updates. The contention is negligible —
    every holder is about to block in `subprocess.run` for seconds.
    """

    def __init__(self, max_calls):
        self.max_calls = max_calls
        self.calls = 0
        self.usd = None
        self.exhausted = False
        self._lock = threading.Lock()

    def spend(self, cost):
        with self._lock:
            if self.calls >= self.max_calls:
                self.exhausted = True
                raise BudgetExhausted(f"call budget exhausted ({self.max_calls})")
            self.calls += 1
            if cost is not None:
                self.usd = (self.usd or 0.0) + cost

    def add_cost(self, cost):
        """Record spend reported after the fact, without consuming a slot."""
        with self._lock:
            self.usd = (self.usd or 0.0) + cost


class Health:
    """What actually happened on the wire.

    Without this, every failure path in `ask` is a silent `None`: an expired
    login, a bad --model or a missing --project produce a run of empty finders
    that is indistinguishable from a clean codebase. A security tool must not
    report "no findings" when what it means is "no answers".

    Tracked at two levels. Attempts drive the diagnostics; *tasks* drive the
    trust decision, because one context call succeeding while all six finders
    fail must not count as "something worked".

    Locked for the same reason Budget is, and with more at stake: `+= 1` is a
    read-modify-write, these are incremented from every pool thread, and these
    counters — not Budget's — decide whether main() reports a run as clean, as
    INCOMPLETE, or as failed. A single lost `unanswered` increment on a run
    with exactly one unanswered task turns EXIT_INCOMPLETE into EXIT_OK.
    """

    def __init__(self):
        self.attempts = 0
        self.failures = 0
        self.answered = 0
        self.unanswered = 0
        self.last_error = None
        self._lock = threading.Lock()

    def attempted(self):
        with self._lock:
            self.attempts += 1

    def failed(self, reason):
        with self._lock:
            self.failures += 1
            self.last_error = (str(reason).strip().splitlines()[-1][:200]
                               if reason else "?")

    def task_answered(self):
        with self._lock:
            self.answered += 1

    def task_unanswered(self):
        with self._lock:
            self.unanswered += 1


def logical_calls(max_findings, rounds=audit_engine.MAX_ROUNDS):
    """Agent tasks a full run needs: context + every finder round + skeptics.

    `rounds` is the mode's only degree of freedom. The skeptic term is a
    constant in both modes on purpose — see the module docstring.
    """
    finders = rounds * len(audit_io.CATEGORIES)
    return 1 + finders + len(audit_io.SKEPTICS) * max_findings


def estimate(max_findings, retries=DEFAULT_RETRIES, rounds=audit_engine.MAX_ROUNDS):
    """Worst-case *attempts*, which is what the budget counts.

    Every logical task may be retried, so attempts are what the ceiling has to
    be compared against. Reporting tasks against a ceiling counted in attempts
    understated the true cost by a factor of (retries + 1).
    """
    return logical_calls(max_findings, rounds) * (retries + 1)


def affordable_findings(max_calls, retries=DEFAULT_RETRIES,
                        rounds=audit_engine.MAX_ROUNDS):
    """How many findings `max_calls` can discover *and* verify.

    Derived rather than defaulted: an independently chosen --max-findings is
    how a run ends up promising more work than its ceiling can pay for. Mode
    aware, because the same ceiling buys a `scan` 24 more discovery tasks'
    worth of verification than it buys an `audit`.
    """
    tasks = max_calls // (retries + 1)
    discovery = 1 + rounds * len(audit_io.CATEGORIES)
    return max(0, (tasks - discovery) // len(audit_io.SKEPTICS))


def failure_reason(adapter, completed):
    """The most informative thing a failed CLI call told us.

    Claude reports errors *inside* its JSON envelope on stdout, not on stderr:
    an expired OAuth session arrives as returncode 1, empty stderr, and
    `result: "Failed to authenticate: OAuth session expired and could not be
    refreshed"`. Reading stderr alone reduced that to `last error: exit 1` and
    left the user to reproduce the call by hand to find out why — which is
    exactly what phase 7 validation had to do.
    """
    payload = ""
    try:
        payload = adapter.parse_stdout(completed.stdout) or ""
    except Exception:  # a parser must never turn a failed call into a crash
        payload = completed.stdout or ""
    for candidate in (completed.stderr, payload):
        if candidate and candidate.strip():
            return candidate
    return f"exit {completed.returncode}"


def make_ask(adapter_name, budget, *, model=None, retries=DEFAULT_RETRIES,
             timeout=DEFAULT_TIMEOUT, cwd=None, health=None, program=None):
    """Build the `ask` callable the engine uses for one LLM task.

    `program` is the absolute path `main()` resolved for this adapter. It only
    looks optional: `audit_adapter._guard` refuses an argv[0] that is not an
    absolute path, so omitting it raises rather than falling back to a search.
    It is threaded in at construction rather than looked up per call so that 73
    workers share one decision and the answer cannot change mid-run.
    """
    adapter = audit_adapter.ADAPTERS[adapter_name]
    health = health if health is not None else Health()

    def ask(prompt, schema=None):
        base = prompt
        if schema is not None:
            base += ("\n\nReturn ONLY a single JSON object matching this schema, "
                     "with no commentary:\n" + json.dumps(schema))
        rejected = None
        for _attempt in range(retries + 1):
            # Tell the worker what was wrong with its last answer. Re-sending
            # the identical prompt can only recover a transient failure, never
            # the schema failure the retry was designed for: a worker that
            # answered `category: "crypto"` answers it again, and the task ends
            # unanswered having spent two slots for one question.
            contract = base if rejected is None else (
                f"{base}\n\nYour previous reply was rejected: {rejected}\n"
                "Return only the JSON object, nothing else."
            )
            budget.spend(None)  # reserve the slot before the call
            health.attempted()
            try:
                completed = subprocess.run(
                    adapter.build_argv(contract, model=model, program=program),
                    capture_output=True, text=True,
                    # Explicit, and lenient. `text=True` alone decodes with the
                    # locale's codec and errors="strict": on Windows that is the
                    # ANSI code page, so a finding naming a non-Latin identifier
                    # raised UnicodeDecodeError — which is a ValueError, caught
                    # by nothing on this path — and unwound the whole audit,
                    # discarding every batch already settled and paid for. The
                    # workers are Node programs that emit UTF-8; a stray
                    # undecodable byte is noise the extractor can step over.
                    encoding="utf-8", errors="replace",
                    timeout=timeout, cwd=cwd,
                )
            except (OSError, subprocess.TimeoutExpired) as exc:
                health.failed(exc)
                rejected = None  # nothing came back to critique
                continue
            if completed.returncode != 0:
                health.failed(failure_reason(adapter, completed))
                rejected = None
                continue
            payload = adapter.parse_stdout(completed.stdout)
            cost = adapter.cost(completed.stdout)
            if cost is not None:
                budget.add_cost(cost)
            if schema is None:
                health.task_answered()
                return payload
            # The schema goes *into* extraction: with several JSON objects in
            # one response, which one is the answer is a schema question.
            obj = audit_io.extract_json(payload, schema)
            if obj is None:
                rejected = "no JSON object in the response"
                health.failed(rejected)
                continue
            try:
                audit_io.validate(obj, schema)
            except audit_io.SchemaError as exc:
                rejected = str(exc)
                health.failed(exc)
                continue
            health.task_answered()
            return obj
        health.task_unanswered()
        return None

    return ask


def make_run(concurrency):
    """Build the `run` callable: a bounded pool over the engine's thunks.

    CONTRACT: results come back in *submission* order, which is why this is
    `pool.map` and not `as_completed`. `audit_engine.verify_all` regroups a
    flat wave by index, so completion order would hand each finding its
    neighbour's verdicts — and a real vulnerability whose neighbours were
    refuted then reaches `upheld == 0` and is dropped inside the engine,
    without a word anywhere. ConcurrencyTest pins it.
    """
    def run(thunks):
        if concurrency <= 1:
            return [t() for t in thunks]
        with concurrent.futures.ThreadPoolExecutor(max_workers=concurrency) as pool:
            return list(pool.map(lambda t: t(), thunks))
    return run


def verified_clause(survivors):
    """How much of `survivors` actually completed verification, in words.

    The INCOMPLETE banners used to open with "The N findings below are verified
    and real" unconditionally — including in the phase-6 run they were written
    for, where every skeptic call failed and all three survivors reached
    `disposition` with zero verdicts. The JSON beside the banner said
    `needs-review` and `Upheld 0/0`; the banner said verified and real. A guard
    that exists to stop a run overstating itself must not overstate itself.
    """
    total = len(survivors)
    done = sum(1 for item in survivors
               if item.get("verification", {}).get("total"))
    if not total:
        return "No findings survived"
    if not done:
        return (f"NONE of the {total} findings below could be verified — every "
                f"skeptic call failed, so they are unranked candidates")
    if done == total:
        return f"The {total} findings below completed verification"
    return f"{done} of the {total} findings below completed verification"


def main(argv=None):
    parser = argparse.ArgumentParser(
        prog="freya security",
        description="Driver-owned security discovery plus adversarial verification.",
    )
    parser.add_argument("mode", nargs="?", default="audit", choices=sorted(MODES),
                        help="audit: exhaustive. scan: one discovery round, "
                             "same verification.")
    parser.add_argument("--project", default=".", help="project directory to audit")
    # No argparse `choices` here: we want a clean message and return code 2
    # rather than argparse's SystemExit, so main() always returns.
    parser.add_argument("--agent", help="agent CLI to drive (default: autodetect)")
    parser.add_argument("--model", help="model for workers; a cheaper one cuts cost a lot")
    parser.add_argument("--max-calls", type=int, default=DEFAULT_MAX_CALLS,
                        help="hard ceiling on agent calls — the one cost knob")
    parser.add_argument("--max-findings", type=int, default=None,
                        help="default: as many as --max-calls can also verify")
    parser.add_argument("--concurrency", type=int, default=DEFAULT_CONCURRENCY)
    parser.add_argument("--timeout", type=int, default=DEFAULT_TIMEOUT)
    parser.add_argument("--dry-run", action="store_true",
                        help="print the plan and cost ceiling, call nothing")
    parser.add_argument("--yes", action="store_true", help="skip the confirmation prompt")
    parser.add_argument("--format", choices=["json", "summary"], default="json")
    args = parser.parse_args(argv)

    say = lambda line: print(line, file=sys.stderr)
    mode = MODES[args.mode]

    if args.agent and args.agent not in audit_adapter.ADAPTERS:
        say(f"unknown agent: {args.agent}")
        return EXIT_FAILED

    # Every bad-input path returns a clean message and a code; none of them may
    # reach `Budget.spend`, which raises BudgetExhausted on call #1 when the
    # ceiling is 0 and escapes main() as a traceback (the context call is the
    # one `ask` the engine does not wrap in `except Halted`).
    if args.max_calls < 1:
        say(f"--max-calls must be at least 1, got {args.max_calls}.")
        return EXIT_FAILED

    # Checked before anything is spent: subprocess.run(cwd=<missing>) raises an
    # OSError that `ask` treats as one more failed call, so a typo here would
    # otherwise buy a full round of failures and an empty, clean-looking result.
    if not os.path.isdir(args.project):
        say(f"not a directory: {args.project}")
        return EXIT_FAILED

    agent_name = args.agent or audit_adapter.detect(args.project)
    if agent_name is None:
        # `mode.name`, not a hardcoded "audit": `scan` reached this line too and
        # was told that *audit* needed a CLI. And the remedy names no binary,
        # because `freya-codebase-security-scan` is a skill, not a command — a
        # user who typed the old text at a shell got `command not found`.
        #
        # The per-CLI reasons are printed because "none was found" is no longer
        # the only way to get here: a CLI that resolves inside the repository
        # being audited is refused, and an operator who can see `claude` on PATH
        # has to be told that rather than told it is missing.
        reasons = "\n".join(f"  {audit_adapter.program_for(n, args.project).reason}"
                            for n in audit_adapter.PREFERENCE)
        say(f"{mode.name} needs an agent CLI on PATH (claude or copilot) and none "
            f"was usable.\n{reasons}\nThere is no other binary to run: the portable "
            "fallback is the freya-codebase-security-scan skill's own in-loop scan, "
            "which the agent performs itself and which is what wrap-up uses.")
        return EXIT_NOTHING_TO_DO

    # Resolved once, here, before the cost plan prints — so a refusal costs
    # nothing and arrives explained. This also covers `--agent claude`, which
    # skipped `detect` entirely: without it that path reaches `make_ask` with no
    # program and dies on `UnsafeInvocation` once per worker. EXIT_NOTHING_TO_DO
    # is what SKILL.md maps to "fall back to the in-loop scan", so a refusal
    # degrades exactly like a missing CLI.
    program = audit_adapter.program_for(agent_name, args.project)
    if program.path is None:
        say(f"{program.reason}.")
        return EXIT_NOTHING_TO_DO

    # --max-calls is the only cost knob; --max-findings is derived from it so the
    # two cannot disagree. An explicit --max-findings that the ceiling cannot pay
    # for is honoured but called out, because it will truncate.
    affordable = affordable_findings(args.max_calls, rounds=mode.rounds)
    max_findings = args.max_findings if args.max_findings is not None else affordable
    worst = estimate(max_findings, rounds=mode.rounds)

    # Refused, not warned. A ceiling too small to verify anything derives
    # --max-findings 0, and `discover` then returns `found[:0]` on the first
    # productive round: every vulnerability discovered is discarded, stdout is
    # `[]`, and the exit code is 0 — which SKILL.md defines verbatim as clean.
    # A configuration whose only possible output is a false clean bill of health
    # must not be allowed to spend a cent.
    if max_findings < 1:
        say(f"--max-findings is {max_findings}, so this run could only ever report "
            f"`[]` no matter what it found — refusing to start.\n"
            f"{mode.name} needs at least --max-calls {estimate(1, rounds=mode.rounds)} "
            f"to discover and verify a single finding.")
        return EXIT_FAILED

    # Everything human-facing goes to stderr: stdout carries only the JSON
    # payload, because the skill's main loop parses it.
    say(f"mode:         {mode.name} — {mode.blurb}")
    say(f"agent:        {agent_name}")
    say(f"project:      {os.path.abspath(args.project)}")
    say(f"call ceiling: {args.max_calls} attempts "
        f"(each of {logical_calls(max_findings, mode.rounds)} tasks may retry once)")
    say(f"worst case:   {worst} attempts "
        f"(1 context + {mode.rounds}x{len(audit_io.CATEGORIES)} finders "
        f"+ {len(audit_io.SKEPTICS)} skeptics x {max_findings} findings)")
    say(f"buys you:     up to {max_findings} findings discovered and verified")
    if max_findings > affordable:
        say(f"WARNING:      --max-findings {max_findings} needs {worst} attempts but the "
            f"ceiling is {args.max_calls}; expect a truncated audit past ~{affordable} "
            f"findings. Raise --max-calls to fit.")
    say("This spends real money. One worker measured ~$0.40 on a trivial fixture.")

    if args.dry_run:
        return EXIT_OK

    if not args.yes:
        # Never block on input() with no tty. The sibling graph_ops.py auto-
        # detects this the same way; here the answer is a refusal rather than a
        # default, because the thing being confirmed is spending money.
        if not sys.stdin.isatty():
            say("refusing to spend money unattended — pass --yes "
                "(run --dry-run first to see the cost plan)")
            return EXIT_DECLINED
        # The prompt goes to stderr. `input(prompt)` writes it to *stdout*,
        # which this module promises carries only the JSON payload: a human
        # answering `y` while redirecting stdout to a file got
        # `Proceed? [y/N] [...]` — invalid JSON — in it.
        say("Proceed? [y/N] ")
        try:
            answer = input()
        except EOFError:  # stdin claimed a tty and then closed anyway
            answer = ""
        if answer.strip().lower() not in ("y", "yes"):
            say("aborted.")
            return EXIT_DECLINED

    budget = Budget(args.max_calls)
    health = Health()
    ask = make_ask(agent_name, budget, model=args.model, timeout=args.timeout,
                   cwd=args.project, health=health, program=program.path)

    def on_round(round_no, fresh, total, dry):
        # The dry counter is meaningless at one round — nothing follows it —
        # so a single-round mode reports what happened, not a countdown.
        if fresh:
            note = f"+{fresh} new"
        elif mode.rounds == 1:
            note = "nothing found"
        else:
            note = f"dry ({dry}/{audit_engine.K_EMPTY})"
        say(f"round {round_no}/{mode.rounds}: {note} — "
            f"{total} findings, {budget.calls} calls")

    def on_settled(done, total):
        say(f"verified {done}/{total} findings — {budget.calls} calls")

    try:
        result = audit_engine.audit(
            ask, make_run(args.concurrency), max_findings=max_findings,
            max_rounds=mode.rounds, on_round=on_round, on_settled=on_settled,
            # Without the project the engine cannot tell a real citation from an
            # invented one, and a fabricated `specReference` downgrades a live
            # finding to `intentional-design`. Observed on both agents.
            project=args.project,
        )
    except audit_engine.ContextUnavailable as exc:
        say(f"\n{exc}.\nlast error: {health.last_error}")
        return EXIT_FAILED
    survivors = result.findings

    spend = "" if budget.usd is None else f", ${budget.usd:.2f}"
    say(f"done: {len(survivors)} findings after verification "
        f"({budget.calls} calls, {health.failures} failed{spend})")

    # A run that got no answers found no vulnerabilities the way an unplugged
    # smoke detector finds no fire. Never report either as success.
    if health.attempts and not health.answered:
        say(f"every agent call failed — this is NOT a clean result.\n"
            f"last error: {health.last_error}")
        return EXIT_FAILED
    if health.unanswered and not survivors:
        say(f"{health.unanswered} of {health.answered + health.unanswered} tasks got no "
            f"usable answer and nothing was found — an empty result here cannot be "
            f"told apart from a broken run, so it is not being reported as clean.\n"
            f"last error: {health.last_error}")
        return EXIT_FAILED

    # Some tasks getting no answer means discovery did not cover the codebase,
    # whether or not anything survived. The two guards above only catch the
    # all-or-nothing shapes: every call failing, or nothing surviving. Phase 6
    # validation hit the shape between them — 22 of 27 calls failed on a real
    # repository, three findings survived, and the run reported them the way a
    # complete audit reports its results, with no mention of the failures and no
    # sight of last_error. A mostly-failed audit is an incomplete audit.
    degraded = health.unanswered > 0
    if degraded:
        say(f"INCOMPLETE: {health.unanswered} of {health.answered + health.unanswered} "
            f"tasks got no usable answer ({health.failures} of {health.attempts} attempts "
            f"failed). {verified_clause(survivors)}, but the codebase was not fully "
            f"covered — do not read this as a clean bill of health.\n"
            f"last error: {health.last_error}")

    if budget.exhausted:
        say(f"INCOMPLETE: the {args.max_calls}-attempt ceiling stopped the run early. "
            f"{verified_clause(survivors)}, but discovery did not finish — do not read "
            f"this as a clean bill of health. Raise --max-calls to complete it.")

    # Truncation is incompleteness. `discover` used to end in a bare
    # `return found[:max_findings]`: the cap silently deleted findings the run
    # had already discovered and paid for, cut discovery short of loop-until-dry,
    # and left every guard above it looking at a perfectly healthy run — so the
    # driver exited 0 "Complete" on a codebase it had stopped reading.
    if result.capped:
        say(f"INCOMPLETE: discovery stopped at the --max-findings {max_findings} cap "
            f"with {result.discarded} discovered finding(s) discarded unverified, and "
            f"the remaining rounds never ran. {verified_clause(survivors)}, but the "
            f"codebase was not swept — do not read this as a clean bill of health. "
            f"Raise --max-calls to complete it.")

    if args.format == "json":
        print(json.dumps(survivors, indent=2))
    else:
        for item in survivors:
            print(f"[{item['disposition']}] {item.get('severity','?')} "
                  f"{item.get('file','?')}:{item.get('line','?')} — {item.get('title','')}")
    return (EXIT_INCOMPLETE if (budget.exhausted or degraded or result.capped)
            else EXIT_OK)


if __name__ == "__main__":
    raise SystemExit(main())
