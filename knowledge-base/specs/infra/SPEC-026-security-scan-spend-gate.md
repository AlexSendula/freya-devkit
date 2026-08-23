---
id: SPEC-026
title: The Security Scan Spend Gate
category: infra
tags: [security, audit, cost, budget, confirmation, cli-contract, driver]
status: implemented
certainty: 82
created: 2026-08-21
updated: 2026-08-21
related_code:
  - skills/freya-codebase-security-scan/scripts/audit.py
  - skills/freya-codebase-security-scan/scripts/audit_io.py
  - skills/freya-codebase-security-scan/scripts/audit_engine.py
  - skills/freya-codebase-security-scan/SKILL.md
intentional_decisions:
  - "With no tty the gate refuses rather than defaulting, because what it guards is spending money"
  - "--yes exists so the human confirmation can move up into the conversation, where the user can see it"
  - "--max-calls is the only cost knob and --max-findings is derived from it, so the two cannot disagree"
  - "A ceiling that cannot pay to verify one finding is refused, not warned about"
  - "stdout carries the JSON payload and nothing else; every human-facing line goes to stderr"
  - "The budget counts attempts, not tasks, and charges the slot before the call is made"
behaviors:
  - behavior_id: BEH-126
    title: --dry-run prints the mode, the ceiling, the worst-case attempt count and what it buys, and makes no agent call at all
    state: proposed
    level: integration
    adapter: unittest
    entry: skills/freya-codebase-security-scan/scripts/audit.py
    locator: skills/freya-codebase-security-scan/scripts/test_audit.py#MainTest.test_dry_run_reports_the_plan_and_calls_nothing
  - behavior_id: BEH-127
    title: A run that cannot ask for confirmation declines and exits 4 having spent nothing — a different code from the 1 that means no agent CLI
    state: proposed
    level: integration
    adapter: unittest
    entry: skills/freya-codebase-security-scan/scripts/audit.py
    locator: skills/freya-codebase-security-scan/scripts/test_audit.py#ConfirmationTest.test_no_tty_refuses_instead_of_blocking_on_input
  - behavior_id: BEH-128
    title: The confirmation prompt and every other human-facing line stay off stdout, which carries only the JSON payload
    state: proposed
    level: integration
    adapter: unittest
    entry: skills/freya-codebase-security-scan/scripts/audit.py
    locator: skills/freya-codebase-security-scan/scripts/test_audit.py#ConfirmationTest.test_the_prompt_never_reaches_stdout
  - behavior_id: BEH-129
    title: A call ceiling too small to discover and verify a single finding refuses to start, naming the minimum for that mode, and never prints an empty array
    state: proposed
    level: integration
    adapter: unittest
    entry: skills/freya-codebase-security-scan/scripts/audit.py
    locator: skills/freya-codebase-security-scan/scripts/test_audit.py#CeilingRefusalTest.test_a_ceiling_too_small_to_verify_anything_refuses_to_start
  - behavior_id: BEH-130
    title: How many findings a run may report is derived from the call ceiling, and an explicit --max-findings the ceiling cannot pay for is run anyway but called out as truncating
    state: proposed
    level: integration
    adapter: unittest
    entry: skills/freya-codebase-security-scan/scripts/audit.py
    locator: skills/freya-codebase-security-scan/scripts/test_audit.py#MainTest.test_max_findings_is_derived_from_the_call_ceiling
---

# The Security Scan Spend Gate

## What

`freya security` spends real money — one measured worker call cost $0.396 on a trivial
fixture, and a full `audit` is up to `1 + 5x6 + 3xfindings` tasks, each of which may retry
once. Everything between the command line and the first worker call is therefore a gate, and
`main()` is mostly that gate rather than the audit.

Three things happen before anything is spent. The plan is printed — mode, agent, project, the
attempt ceiling, the worst case in attempts, and how many findings that buys — and with
`--dry-run` the run stops right there at exit 0. Bad configurations are refused: an unknown
`--agent`, a `--project` that is not a directory, a `--max-calls` below 1, and a ceiling too
small to discover *and* verify a single finding (68 attempts for `audit`, 20 for `scan`) all
return an exit code and a sentence, having called nothing. Then the confirmation: without
`--yes` the driver asks, and at a shell with no tty it declines and exits 4 rather than
blocking or assuming consent.

`--max-calls` (default 200 attempts) is the only cost knob. `--max-findings` is *derived* from
it — with the shipped default, 23 findings for `audit` and 31 for `scan` — and an explicitly
passed value the ceiling cannot pay for is honoured but flagged as one that will truncate. The
ceiling counts attempts rather than logical tasks, because every task may retry, and a slot is
consumed at the moment a call is attempted rather than when it succeeds.

Human-facing output is on stderr throughout. stdout carries the JSON array of findings and
nothing else, because the skill's main loop parses it.

## Why

A cost guard that can be reached by accident is not a guard. Two of these refusals exist
because the alternative was silently worse: an agent shell has no tty, so a gate that blocked
on `input()` would hang a wrap-up forever, and a gate that defaulted to yes would spend tens of
dollars nobody approved. Refusing, with the remedy (`--yes`, and `--dry-run` first) named in
the message, is the only third option.

The ceiling refusal exists because of a real failure shape rather than tidiness: `--max-calls 60`
derives `--max-findings 0`, `discover` then returns `found[:0]` on its first productive round,
stdout is `[]` and the exit code is 0 — which SKILL.md defines verbatim as a clean codebase.
A configuration whose only possible output is a false clean bill of health must not be allowed
to spend a cent, and warning about it is not enough when the output it produces is
indistinguishable from success.

Deriving `--max-findings` rather than defaulting it comes from the same place: two
independently chosen numbers are how a run ends up promising more work than its ceiling can pay
for, and the mode changes the arithmetic — the same 200 attempts buy a `scan` 24 more findings'
worth of verification than they buy an `audit`, because `scan` spends 6 discovery calls where
`audit` spends 30.

## Behavior

| Behavior | State | Verified by |
|----------|-------|-------------|
| BEH-126 --dry-run prints the mode, the ceiling, the worst-case attempt count and what it buys, and makes no agent call at all | proposed | `test_audit.py#MainTest.test_dry_run_reports_the_plan_and_calls_nothing` (unittest) |
| BEH-127 A run that cannot ask for confirmation declines and exits 4 having spent nothing — a different code from the 1 that means no agent CLI | proposed | `test_audit.py#ConfirmationTest.test_no_tty_refuses_instead_of_blocking_on_input` (unittest) |
| BEH-128 The confirmation prompt and every other human-facing line stay off stdout, which carries only the JSON payload | proposed | `test_audit.py#ConfirmationTest.test_the_prompt_never_reaches_stdout` (unittest) |
| BEH-129 A call ceiling too small to discover and verify a single finding refuses to start, naming the minimum for that mode, and never prints an empty array | proposed | `test_audit.py#CeilingRefusalTest.test_a_ceiling_too_small_to_verify_anything_refuses_to_start` (unittest) |
| BEH-130 How many findings a run may report is derived from the call ceiling, and an explicit --max-findings the ceiling cannot pay for is run anyway but called out as truncating | proposed | `test_audit.py#MainTest.test_max_findings_is_derived_from_the_call_ceiling` (unittest) |

Several of these are one behavior with more than one edge, and both edges matter:

- BEH-127's other half is `…ConfirmationTest.test_a_declined_run_and_a_missing_cli_are_told_apart`,
  which asserts the two codes differ rather than each in isolation — the defect it guards is
  exactly that they once did not. `…test_a_yes_at_a_terminal_still_runs` keeps the gate a gate
  and not a blanket refusal.
- BEH-129's mode-awareness is `…CeilingRefusalTest.test_the_minimum_is_mode_aware`, the
  explicit-zero path is `…test_an_explicit_zero_max_findings_is_refused_too`, the
  ceiling-of-zero path is `…test_a_zero_call_ceiling_is_a_message_not_a_traceback`, and
  `…test_the_shipped_default_is_not_refused` is the control that stops the guard from firing on
  the configuration everybody runs.
- BEH-130's warning half is `…MainTest.test_an_unaffordable_max_findings_is_called_out`, and the
  arithmetic underneath both is pinned by `…EstimateTest` — in particular
  `test_worst_case_is_counted_in_attempts_not_tasks` and
  `test_the_shipped_defaults_can_actually_finish_a_run`.

Two further pre-flight refusals are tested and deliberately left off the list as ordinary input
validation: `…MainTest.test_a_missing_project_is_rejected_before_anything_is_spent` (a `cwd`
typo would otherwise buy a full round of failed calls and an empty result that reads as clean)
and `…MainTest.test_unknown_agent_exits_two`.

## Intentional Design Decisions

### With no tty the gate refuses; it does not default

**Decision**: `main()` checks `sys.stdin.isatty()` and, when there is no terminal and `--yes`
was not passed, returns `EXIT_DECLINED` (4) without calling anything.

**Rationale**: The sibling `graph_ops.py` detects the same condition and picks a sensible
default; here the thing being confirmed is spending money, so the safe default is to do
nothing. The message names both remedies rather than merely reporting the refusal.

**Security Scan Note**: A tty check that changes control flow is intentional and is neither an
interactivity bug nor a denial-of-service on automation. Automation is expected to pass
`--yes`; the exit code is distinct precisely so the caller can tell "declined" from "broken".

### `--yes` moves the human gate up into the conversation

**Decision**: The skill's documented invocation is `freya security scan --project . --yes`,
i.e. the driver's own confirmation is skipped on the normal path.

**Rationale**: When an agent runs the driver, the prompt the driver would print is one the user
never sees. SKILL.md therefore requires the agent to state the cost, run `--dry-run` if asked,
get a spoken go-ahead, and only then pass `--yes`. The gate is not removed; it is relocated to
where a human is actually looking.

**Security Scan Note**: "A tool that ships a flag to skip its own confirmation prompt, and
documentation telling you to always use it" is the design. The compensating control is
procedural and lives in SKILL.md, not in this file.

### One cost knob, and the other number is derived from it

**Decision**: `--max-findings` defaults to `affordable_findings(--max-calls, rounds)` rather
than to a constant, and the printed plan states what the ceiling buys.

**Rationale**: See **Why**. The derivation is mode-aware because discovery cost is what the
mode changes.

**Security Scan Note**: The integer arithmetic in `affordable_findings` / `estimate` is not
dead or arbitrary — it is the contract between the two flags, and `EstimateTest` fails if it
drifts. Do not "simplify" `estimate` to count tasks: attempts is what the ceiling compares
against, and counting tasks understated true cost by a factor of `retries + 1`.

### A ceiling that can only report `[]` is refused, not warned about

**Decision**: `max_findings < 1` returns `EXIT_FAILED` with nothing on stdout.

**Rationale**: See **Why** — the output of the un-refused version is byte-identical to a clean
scan.

**Security Scan Note**: An early `return` before the main work, on a numeric edge case, is the
whole point here rather than an unreachable branch to be tidied away.

### stdout is a pure data channel

**Decision**: Every diagnostic, banner, warning and prompt is written to stderr via the local
`say`. The confirmation prompt is printed with `say` and read with a bare `input()`, rather
than `input(prompt)`.

**Rationale**: `input(prompt)` writes its prompt to *stdout*, and a human answering `y` while
redirecting stdout to a file got `Proceed? [y/N]` in what was supposed to be JSON.

**Security Scan Note**: The split is a machine-interface contract, not a logging inconsistency.
Moving any of these to stdout — or "helpfully" echoing the plan there — corrupts the payload
the skill parses.

### The budget charges the slot before the call

**Decision**: `Budget.spend(None)` is called *before* `subprocess.run`, so a subprocess that
never starts, or that times out, still consumes a slot; and both `Budget` and `Health` take a
lock around their counters.

**Rationale**: `--max-calls` is a spend guard, not an accounting ledger — a failure mode that
did not consume budget would let a broken agent loop for free. The locks are there because the
pool increments these from several threads, and Health's counters in particular decide whether
`main()` reports a run as clean, incomplete, or failed.

**Security Scan Note**: "Resource counter incremented before the operation succeeds" is
deliberate. So is the lock on a counter that looks single-threaded: `run` executes the thunks
on a `ThreadPoolExecutor`, and the race is pinned by `BudgetTest.test_the_ceiling_holds_under_concurrent_workers`
and `HealthLockTest`.

## Related Specs

- [SPEC-025: Read-Only Audit Workers and Agent Selection](./SPEC-025-read-only-audit-workers.md) —
  what a worker is allowed to do once the gate lets the run start
- [SPEC-027: A Security Run That Could Not Finish Says So](./SPEC-027-no-false-clean-bill-of-health.md) —
  the other end of the ceiling: what happens when the budget runs out mid-run

## Change History

| Date | Change | Reason |
|------|--------|--------|
| 2026-08-21 | Initial spec, inferred from code and tests | Brownfield scan (`freya-spec-manager bootstrap`) |

---

*Certainty 82. Every refusal above carries a comment naming the incident that produced it, with
concrete numbers (`--max-calls 60`, `$0.396`, exit 1 read as a missing CLI), and each has a test
whose docstring repeats the failure — so these are decisions rather than accidents. Held below
90 because the split between "worth a standing behavior record" and "ordinary input validation"
is my judgment, not the code's: the project-directory and unknown-agent refusals are equally
tested and could reasonably be behaviors too, and ADR-015 covers the cost reasoning without ever
mentioning the confirmation gate, which is documented only in SKILL.md and in this module.*
