---
id: SPEC-025
title: Read-Only Audit Workers and Agent Selection
category: infra
tags: [security, audit, sandboxing, read-only, adapter, portability, agent-cli]
status: implemented
certainty: 84
created: 2026-08-21
updated: 2026-08-21
related_code:
  - skills/freya-codebase-security-scan/scripts/audit_adapter.py
  - skills/freya-codebase-security-scan/scripts/audit.py
  - skills/freya-codebase-security-scan/SKILL.md
  - bin/commands.json
intentional_decisions:
  - "The allowlist is the load-bearing control and the deny flags are defence in depth only"
  - "A fixed tuple of forbidden flags checked per argv token, rather than a permission parser"
  - "Autodetection prefers claude because it is the CLI that reports per-call spend"
  - "--model is passed through without being checked against the selected --agent"
behaviors:
  - behavior_id: BEH-121
    title: Every audit worker is invoked under an explicit read-only allowlist that excludes the shell, and never under a blanket grant
    state: proposed
    level: unit
    adapter: unittest
    locator: skills/freya-codebase-security-scan/scripts/test_audit_adapter.py#ReadOnlyTest.test_no_adapter_ever_grants_blanket_access
  - behavior_id: BEH-122
    title: A blanket-permission flag arriving through the prompt is refused with UnsafeInvocation instead of reaching the worker
    state: proposed
    level: unit
    adapter: unittest
    locator: skills/freya-codebase-security-scan/scripts/test_audit_adapter.py#ReadOnlyTest.test_blanket_flag_in_a_prompt_is_rejected
  - behavior_id: BEH-123
    title: A whole `scan` run stays read-only — the cheap preset opens no write path on any of its calls
    state: proposed
    level: integration
    adapter: unittest
    entry: skills/freya-codebase-security-scan/scripts/audit.py
    locator: skills/freya-codebase-security-scan/scripts/test_audit.py#ScanModeTest.test_scan_workers_are_still_read_only
  - behavior_id: BEH-124
    title: With no --agent given the driver picks claude when it is installed and copilot otherwise
    state: proposed
    level: unit
    adapter: unittest
    locator: skills/freya-codebase-security-scan/scripts/test_audit_adapter.py#DetectTest.test_prefers_claude_when_both_present
  - behavior_id: BEH-125
    title: With neither agent CLI on PATH the run exits 1 and names the mode that was run and the in-loop fallback, not a binary to install
    state: proposed
    level: integration
    adapter: unittest
    entry: skills/freya-codebase-security-scan/scripts/audit.py
    locator: skills/freya-codebase-security-scan/scripts/test_audit.py#MainTest.test_no_agent_cli_degrades_with_guidance
---

# Read-Only Audit Workers and Agent Selection

## What

`freya security` (routed to `skills/freya-codebase-security-scan/scripts/audit.py` by
`bin/commands.json`) performs each of its discovery and verification tasks by running a
coding-agent CLI headlessly, one process per task. `audit_adapter.py` is the only
agent-specific code in the driver: it builds the argv, parses stdout, and reports per-call
spend where the CLI provides it.

Every argv is an allowlist the driver constructs in full — Claude
`--allowedTools "Read Grep Glob" --disallowedTools "Write Edit Bash"`, Copilot
`--allow-tool=read --deny-tool=write --deny-tool=shell` — granting reading and searching and
nothing else. Four blanket-permission flags (`--allow-all-tools`, `--allow-all`,
`--allow-all-paths`, `--allow-all-urls`) may never appear in any argv, and `_guard`
(`audit_adapter.py:83`) inspects every token before the argv leaves the module, raising
`UnsafeInvocation` when one of them is a token or its `=`-form. The prompt travels as a single
`-p` element of an argv list; nothing on this side is ever handed to a shell.

Which CLI runs is `--agent`, or autodetection in a fixed preference order (`claude`, then
`copilot`) when the flag is absent. An `--agent` naming an adapter that does not exist is a
message and exit 2 before anything is spent. When neither CLI is installed, `detect()` returns
`None` and the run exits 1 — the single meaning that exit code carries — with a message naming
the mode that was actually run and pointing at the skill's own in-loop scan, which is a skill
and not a command a user can type at a shell.

## Why

The driver exists because a fan-out expressed as a prose instruction is a suggestion; the
read-only boundary is the security half of the same decision, and it is a measurement rather
than a preference. ADR-015 records both, including the spike result that makes the shape of the
allowlist non-negotiable and the field evidence that it holds.

The workers are pointed at a repository whose contents nobody here controls, and every skeptic
call embeds text a previous worker wrote *after* reading that repository (`_skeptic` sends
`Finding: {finding}` verbatim, `audit_engine.py:398`). What bounds a worker that has been
talked into something is therefore the argv, not the prompt.

**[NEEDS CLARIFICATION]** — no comment or ADR states that prompt-embedding surface as a
considered case. That the allowlist covers it is true; that it was *chosen* to cover it is an
inference, and is one of the two things holding certainty below 90.

## Behavior

| Behavior | State | Verified by |
|----------|-------|-------------|
| BEH-121 Every audit worker is invoked under an explicit read-only allowlist that excludes the shell, and never under a blanket grant | proposed | `test_audit_adapter.py#ReadOnlyTest.test_no_adapter_ever_grants_blanket_access` (unittest) |
| BEH-122 A blanket-permission flag arriving through the prompt is refused with UnsafeInvocation instead of reaching the worker | proposed | `test_audit_adapter.py#ReadOnlyTest.test_blanket_flag_in_a_prompt_is_rejected` (unittest) |
| BEH-123 A whole `scan` run stays read-only — the cheap preset opens no write path on any of its calls | proposed | `test_audit.py#ScanModeTest.test_scan_workers_are_still_read_only` (unittest) |
| BEH-124 With no --agent given the driver picks claude when it is installed and copilot otherwise | proposed | `test_audit_adapter.py#DetectTest.test_prefers_claude_when_both_present` (unittest) |
| BEH-125 With neither agent CLI on PATH the run exits 1 and names the mode that was run and the in-loop fallback, not a binary to install | proposed | `test_audit.py#MainTest.test_no_agent_cli_degrades_with_guidance` (unittest) |

BEH-121's positive half — that the allowlist is actually *there*, not merely that a blanket flag
is absent — is `test_audit_adapter.py#ReadOnlyTest.test_claude_restricts_tools_to_read_only` and
`…test_copilot_denies_shell_not_just_write`. BEH-124's other two edges are
`…DetectTest.test_falls_back_to_copilot` and `…test_none_when_no_agent_cli_is_installed`.
BEH-123 is deliberately not a duplicate of BEH-121: it drives `main()` end to end and asserts
every argv that actually reached `subprocess.run`, which is the only form of the claim that
survives someone adding a call path the adapters do not build.

The unknown-`--agent` refusal (`test_audit.py#MainTest.test_unknown_agent_exits_two`) is real
and tested but is left off this list as ordinary input validation, not an intent worth a
standing record.

## Intentional Design Decisions

### The allowlist is the control; the deny flags are defence in depth

**Decision**: Both adapters pass deny flags *and* an allowlist, and the allowlist is what the
guarantee rests on. Removing Claude's `--disallowedTools` kills no test, and that is the
documented, expected result.

**Rationale**: ADR-015 — measured on Copilot CLI 1.0.75, `--allow-all-tools --deny-tool=write`
was bypassed by writing through the shell, while the allowlist held on both CLIs.

**Security Scan Note**: Two things here read as defects and are not. The redundant-looking deny
flags are deliberate belt-and-braces and must not be "simplified" away, and the fact that no
test dies when they are removed is documented mutation-testing output, not a coverage gap. The
line to protect is the allowlist itself.

### A fixed tuple of forbidden flags, checked per token

**Decision**: `BLANKET_FLAGS` is a four-element tuple and `_guard` matches a token exactly or
by its `flag=` prefix. It is not a permission parser and does not scan prose.

**Rationale**: The bypass it encodes is version-specific and easy to reintroduce by hand, so
ADR-015 chose a raise-on-sight guard that turns a reintroduction into a test failure. The
deeper protection is structural: the prompt is one element of an argv list, so prompt text can
never *become* a flag regardless of what it says.

**Security Scan Note**: This looks like a denylist where an allowlist belongs — the classic
finding. It is a second line. The first line is that the driver constructs every token of every
argv itself and never interpolates into a shell string (`subprocess.run` is always given a
list, never `shell=True`).

### Autodetection prefers claude because it reports spend

**Decision**: `PREFERENCE = ("claude", "copilot")`, and the first one on PATH wins.

**Rationale**: Only Claude's envelope carries `total_cost_usd`, which is the sole source for
the `$` figure the run prints and for `Budget.usd`. A copilot-first order would silently make
every run's spend unreportable.

**Security Scan Note**: A hardcoded vendor preference is intentional and is not a supply-chain
smell; `--agent` overrides it, and detection is `shutil.which` against a fixed two-name table,
not a PATH scan for anything executable.

### `--model` is passed through unchecked against `--agent`

**Decision**: `--model` is forwarded to whichever adapter was selected, with no validation that
the model name belongs to that CLI's vocabulary.

**Rationale**: Inferred, not stated. The vocabularies do not overlap and a hardcoded list of
valid model names would be stale within weeks; SKILL.md instead documents "pass both, or
neither" after a phase-7 run failed with `unrecognized_model` when a Copilot model name reached
an autodetected `claude` worker.

**Security Scan Note**: The missing cross-check is a known, documented seam rather than an
oversight — but note the failure it produces is a whole failed run, not a silent one, which is
why nothing guards it in code.

## Related Specs

- [SPEC-026: The Security Scan Spend Gate](./SPEC-026-security-scan-spend-gate.md) — the other
  half of `main()`'s pre-flight: what must be true before a single worker is launched
- [SPEC-027: A Security Run That Could Not Finish Says So](./SPEC-027-no-false-clean-bill-of-health.md) —
  what the same run promises about the answers it got back

## Change History

| Date | Change | Reason |
|------|--------|--------|
| 2026-08-21 | Initial spec, inferred from code and tests | Brownfield scan (`freya-spec-manager bootstrap`) |

---

*Certainty 84. ADR-015 states the allowlist decision, the measured bypass, the exit-1
single-meaning rule and the claude-first preference explicitly, and every behavior above has a
test whose docstring names the failure it prevents — this is about as well-evidenced as inferred
intent gets. Held below 90 for two reasons: the prompt-embedding surface described in **Why** is
an inference nobody wrote down, and the `--model` decision is reconstructed from a SKILL.md
sentence and a validation log rather than from anything in the code.*
