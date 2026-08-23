---
id: SPEC-001
title: The `freya` launcher command surface
category: infra
tags: [launcher, cli, dispatch, portability, agent-neutral, manifest]
status: implemented
certainty: 85
created: 2026-08-21
updated: 2026-08-21
related_code:
  - bin/freya
  - bin/freya_cli.py
  - bin/commands.json
  - install.sh
  - install.ps1
intentional_decisions:
  - "The command manifest is treated as a trust boundary and validated with both path flavours on every host"
  - "Dispatched scripts get the script's own directory prepended to PYTHONPATH"
  - "The minimum Python version is duplicated across four entry points that cannot import each other"
  - "A refusal and an unknown command share exit code 2; a signal-killed child reports 128+N"
behaviors:
  - behavior_id: BEH-001
    title: An unknown command is refused with exit 2 and points at `freya help`
    state: proposed
    level: integration
    adapter: unittest
    entry: bin/freya_cli.py
    locator: bin/test_freya_cli.py#MainTest.test_unknown_command_exits_2_with_stderr_hint
  - behavior_id: BEH-002
    title: A manifest entry naming anything but a path under `skills/` is refused before dispatch
    state: proposed
    level: unit
    adapter: unittest
    locator: bin/test_freya_cli.py#ManifestValidationTest.test_an_entry_that_escapes_the_skills_directory_is_rejected
  - behavior_id: BEH-003
    title: A registered command whose script is missing is a freya error naming the script and `freya doctor`
    state: proposed
    level: unit
    adapter: unittest
    locator: bin/test_freya_cli.py#MissingScriptTest.test_a_registered_but_missing_script_is_a_freya_error
  - behavior_id: BEH-004
    title: "`freya doctor` reports a broken installation as rows and exits 1 instead of raising"
    state: proposed
    level: integration
    adapter: unittest
    entry: bin/freya_cli.py
    locator: bin/test_freya_cli.py#DoctorTest.test_doctor_reports_failure_cleanly_on_malformed_manifest
  - behavior_id: BEH-005
    title: An interpreter older than the declared floor is named as the problem instead of raising SyntaxError
    state: proposed
    level: e2e
    adapter: manual
    locator: bin/test_freya_cli.py#PythonFloorTest.test_an_old_interpreter_is_refused_by_message_not_syntaxerror
---

# The `freya` launcher command surface

## What

`freya <command> [args...]` is the only command surface the suite exposes. The
launcher locates its own store from `Path(__file__).resolve()`, looks the command
up in `bin/commands.json`, and runs the target script with `sys.executable`, so
no caller ever needs a per-agent path variable or a bare `python`.

Scope of this spec:

- **Dispatch and its refusals.** A name in the manifest runs its script and the
  child's exit code is returned unchanged; a name that is not is refused. A name
  that is a *skill* rather than a command (`freya wrap-up`) is additionally told
  so, since the CLI/skill distinction otherwise appears only in a project's
  `AGENTS.md`.
- **The manifest as an input.** Shape and path validation happen once, in
  `load_manifest`, so the path that *runs* a command rejects exactly what
  `doctor` reports.
- **Self-diagnosis.** `freya doctor` reports one row per check
  (`suite root`, `manifest`, `scripts`, `python`, `freya on PATH`, `agents`,
  `orphaned entries`, `updates`, `duplicate install`) and exits 1 only when a
  row is `FAIL`. Every read it makes is guarded, because every one of them can
  fail on precisely the broken install it was run to explain.
- **The interpreter floor.** Four entry points refuse an interpreter older than
  `freya_cli.MIN_PYTHON` before any suite module is imported.

Out of scope: what an individual dispatched script does, and everything about
placing the launcher on `PATH` (see SPEC-002).

## Why

The problem was measured, not assumed: 83 `${CLAUDE_PLUGIN_ROOT}` sites across
SKILL.md files, and 80 script invocations that called a bare `python` which does
not exist on many modern systems. One self-locating launcher removes both at
once for every agent, which is the decision recorded in
[ADR-013](../../decisions/ADR-013-single-freya-launcher.md).

The refusals exist because the launcher sits between a user (or an agent) and a
subprocess. Every failure shape here was one that previously surfaced as
somebody else's error message: CPython's "can't open file" for a pruned install,
a raw `TypeError` for a half-restored manifest, a `SyntaxError` from a file the
user never named for an old interpreter. Each of those points the reader at the
wrong thing, and `doctor` — the one command whose job is to explain the
installation — was the loudest example, so it is the one most heavily guarded.

**Certainty (85).** High but not authored: `bin/freya_cli.py` documents the
intent of each guard inline, ADR-013 records the decision, and every behavior
below except BEH-005 has a test named for the intent rather than the mechanism.
It is not 100 because these were read out of code and tests rather than stated
by the author, and because BEH-005's floor is asserted only by source
inspection, so its runtime behavior is inferred.

## Behavior

| Behavior | State | Verified by |
|----------|-------|-------------|
| BEH-001 An unknown command is refused with exit 2 and points at `freya help` | proposed | `bin/test_freya_cli.py#MainTest.test_unknown_command_exits_2_with_stderr_hint` (unittest) |
| BEH-002 A manifest entry naming anything but a path under `skills/` is refused before dispatch | proposed | `bin/test_freya_cli.py#ManifestValidationTest.test_an_entry_that_escapes_the_skills_directory_is_rejected` (unittest) |
| BEH-003 A registered command whose script is missing is a freya error naming the script and `freya doctor` | proposed | `bin/test_freya_cli.py#MissingScriptTest.test_a_registered_but_missing_script_is_a_freya_error` (unittest) |
| BEH-004 `freya doctor` reports a broken installation as rows and exits 1 instead of raising | proposed | `bin/test_freya_cli.py#DoctorTest.test_doctor_reports_failure_cleanly_on_malformed_manifest` (unittest) |
| BEH-005 An interpreter older than the declared floor is named as the problem instead of raising SyntaxError | proposed | **no test** — `manual`; belongs in `bin/test_freya_cli.py#PythonFloorTest` |

BEH-005 is the gap in this area. `PythonFloorTest` asserts that `bin/freya`,
`install.sh` and `install.ps1` all spell the same floor as `freya_cli.MIN_PYTHON`,
and that `install.sh`'s probe accepts the running interpreter — but nothing runs
either entry point under an older interpreter, so the message and the exit code
a 3.8 user actually sees are unverified.

## Intentional Design Decisions

### The command manifest is a trust boundary, validated with both path flavours on every host

**Decision**: `load_manifest` rejects any entry whose value is POSIX-absolute,
carries a Windows drive or root, or contains `..` in either spelling — on every
platform, not just the one it is running on — and raises `ValueError` rather
than filtering the offending entries out. `bin/commands.json` is repo-owned data
today, so this guards an input that is not currently attacker-controlled.

**Rationale**: `resolve_command` joins the manifest value onto the store and
`run_command` executes the result, so "a path under `skills/`" is the only thing
an entry is ever allowed to mean. Letting the host decide what a value means is
what broke it before: Python 3.13 changed `ntpath.isabs` so a rooted path with
no drive (`/etc/passwd`) is no longer absolute on Windows, and the same
checked-in value was rejected on 3.9 and accepted on 3.13, where joining it
discards the store's own path.

**Security Scan Note**: a `subprocess` call whose script path comes from a JSON
file is intentional and is the launcher's whole purpose — see ADR-013. The path
is validated before the join, on both path flavours, and the manifest is
repository-owned. Flag a change that removes `_escapes`, not the dispatch
itself.

### Dispatched scripts get their own directory prepended to `PYTHONPATH`

**Decision**: `child_env` puts the resolved directory of the script being run at
the front of the child's `PYTHONPATH`.

**Rationale**: suite scripts import siblings by bare name, which normally works
because CPython puts the script's directory on `sys.path`. Under
`PYTHONSAFEPATH` / `-P` / isolated mode it does not, and `freya security` died
with `ModuleNotFoundError` while the one test that sets `PYTHONSAFEPATH` stayed
green because it only ran `freya help`, which spawns no child. Restoring the
entry once beats sixteen hand-rolled `sys.path` inserts.

**Security Scan Note**: this is `PYTHONPATH` manipulation with a value derived
from the launcher's own resolved location, never from user input or the
environment, and it prepends exactly the entry the interpreter normally provides.

### The interpreter floor is duplicated in four files on purpose

**Decision**: `bin/freya`, `bin/freya_cli.py` (`MIN_PYTHON`), `install.sh` and
`install.ps1` each spell out the same minimum version instead of sharing one
definition.

**Rationale**: none of them can import the others at the moment they need the
answer. `installer.py` and `updater.py` open with `from __future__ import
annotations`, so an older interpreter dies with a `SyntaxError` from a file the
user never named — including on `freya doctor`, the one command whose job is to
say the Python is too old. `bin/freya` therefore checks before importing any
suite module and writes its message without an f-string.

**Security Scan Note**: not copy-paste drift. `bin/test_freya_cli.py#PythonFloorTest`
is what keeps the four in step; a linter proposing to deduplicate them is
proposing to reintroduce the failure.

### Exit codes: 2 for every refusal, 128+N for a signal-killed child

**Decision**: an unknown command, a bad manifest, a missing script and a
rejected flag all exit 2, and `run_command` converts a child terminated by
signal N (reported by `subprocess.call` as `-N`) into `128 - (-N)`.

**Rationale**: the refusals are all "freya will not run this", which is one
condition from a caller's point of view; the distinction is carried by the
message on stderr. Passing `-N` to `SystemExit` masks it to `256-N` (241 for
SIGTERM), which no shell convention explains, while `bin/freya`'s own
`SystemExit(130)` for Ctrl-C shows 128+N is the intent.

**Security Scan Note**: an exit code that does not distinguish "unknown command"
from "manifest rejected" is deliberate, not a swallowed error — stderr always
names the cause.

## Related Specs

- [SPEC-002: Canonical-store install contract](./SPEC-002-canonical-store-install-contract.md) — how the launcher gets onto `PATH`, and what `doctor`'s install rows report on
- [SPEC-003: The managed AGENTS.md block](./SPEC-003-agents-md-managed-block.md) — `freya init`, the built-in that writes outside the store

## Change History

| Date | Change | Reason |
|------|--------|--------|
| 2026-08-21 | Initial spec, inferred from code and tests by the brownfield scan | `freya-spec-manager bootstrap` — all behaviors `proposed`, none reviewed by a human yet |
