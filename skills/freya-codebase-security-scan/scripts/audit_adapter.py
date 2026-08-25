#!/usr/bin/env python3
"""Drive a coding-agent CLI headlessly as a read-only audit worker.

This is the only agent-specific code in the audit driver. Everything else is
plain Python that calls an `ask` callable.

SECURITY — the read-only boundary. The spike behind design 6.1.1 established
that GitHub's "deny beats allow" applies to the *write tool*, not to writes
performed *through* the shell: `--allow-all-tools --deny-tool=write` let a
worker create a file with a shell redirect. Only an explicit allowlist that
excludes the shell held. So:

  * every argv here is an allowlist, never a blanket grant, and
  * build_argv refuses to emit a blanket permission flag even if one is
    smuggled in through the prompt.

Those two constrain what a worker may *do*. They say nothing about *which file*
gets started, which is a separate question with its own answer below: argv[0] is
an absolute path resolved outside the audited project, or no worker starts at
all (SEC-003).
"""

from __future__ import annotations

import json
import sys
from collections import namedtuple
from pathlib import Path

#: The shared program resolver, reached by the sibling-skill pattern this suite
#: already uses (ADR-030): `bin/` is not copied into an agent's skills directory
#: under a `--copy` install, so a helper there would be unreachable from an
#: installed skill, while the `freya-*` directories always travel together.
#:
#: Guarded, the same width and for the same reason as `bin/updater.py`'s import
#: of this module — the two must not silently disagree about what a damaged
#: skill tree does. A `--copy` install whose `freya-code-graph` target was
#: occupied or foreign is *skipped* by the installer, so a security driver can
#: genuinely find itself in a tree with no resolver. Unguarded, that was a raw
#: `ModuleNotFoundError` traceback out of `freya security`, and it degraded
#: acceptably only by coincidence: Python's uncaught-exception exit code happens
#: to equal `audit.EXIT_NOTHING_TO_DO`, which nothing in the tree recorded and
#: any renumbering of the exit codes would have broken in silence.
#:
#: Failing closed is still the rule and the guard does not soften it: with the
#: resolver gone `program_for` refuses with a stated reason, `detect` finds
#: nothing, and `_guard` refuses every argv. There is no fallback to a bare
#: name here either (ADR-030).
_SCRIPTS = Path(__file__).resolve().parents[2] / "freya-code-graph" / "scripts"
if _SCRIPTS.is_dir() and str(_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS))
try:
    import containment  # noqa: E402
    import exec_path  # noqa: E402
except Exception:  # noqa: BLE001 — a damaged skill tree must refuse, not traceback
    containment = exec_path = None

#: Said when the skill tree cannot answer where an agent CLI is. Begins with the
#: program's name, the convention `exec_path.Resolution` documents, so `main()`
#: can print it unedited alongside the resolver's own reasons.
NO_RESOLVER = (
    "%s cannot be resolved: the skill tree is incomplete — "
    "skills/freya-code-graph/scripts/exec_path.py could not be loaded, and it is "
    "what decides which agent CLI is safe to run"
)

#: Structurally `exec_path.Resolution`, and reached only when `exec_path` itself
#: could not be loaded — the one case in which the canonical type is unavailable
#: to name. Deliberately not a second *rule*: it carries a refusal outward and
#: decides nothing.
_Unresolvable = namedtuple("Resolution", "path reason")

#: Flags that would hand a worker general-purpose tool access. Never emitted.
BLANKET_FLAGS = ("--allow-all-tools", "--allow-all", "--allow-all-paths", "--allow-all-urls")

Adapter = namedtuple("Adapter", "name binary build_argv parse_stdout cost")


class UnsafeInvocation(Exception):
    """An argv would have granted a worker more than read access."""


def _guard(argv):
    # argv[0] first, and it is here rather than in a static rule because a
    # static rule cannot see it. INV-2 (`bin/check_invariants.py`) reads argv[0]
    # at the *call site*; this argv is assembled in a helper and reaches
    # `subprocess.run` as an expression, which the checker's own docstring
    # records as a known blind spot. So the property is a runtime refusal in
    # the one function every adapter's argv already passes through.
    #
    # A bare name asks the operating system to search, and on Windows
    # `CreateProcess` searches the parent's working directory before PATH —
    # under documented usage, the repository being audited (SEC-003).
    #
    # `isinstance` before the predicate, and it is load-bearing rather than
    # defensive: a forgotten `program=` puts None at argv[0], and
    # `containment.is_anchored` is a string predicate that would raise TypeError
    # out of a security check instead of refusing. The forgotten program is the
    # single likeliest way this fix gets half-applied, so it must arrive as an
    # `UnsafeInvocation` that names it.
    #
    # No anchoring rule means no worker, rather than a worker judged by a rule
    # that is not there. `main()` refuses long before this on a damaged tree;
    # this is the backstop for a caller that builds an argv directly.
    if containment is None:
        raise UnsafeInvocation(NO_RESOLVER % "an audit worker")
    if not argv or not isinstance(argv[0], str) or not containment.is_anchored(argv[0]):
        raise UnsafeInvocation(
            f"refusing to run an audit worker as {argv[0] if argv else None!r}: "
            "argv[0] must be an absolute path, or the search path chooses which "
            "binary a worker is"
        )
    for token in argv:
        for flag in BLANKET_FLAGS:
            if token == flag or token.startswith(flag + "="):
                raise UnsafeInvocation(
                    f"refusing to run an audit worker with {flag}: writes through the "
                    "shell are not blocked by --deny-tool"
                )
    return argv


def _claude_argv(prompt, model=None, program=None):
    # `program`, deliberately not `program or "claude"`. A fallback would make
    # the fix opt-in per call site, and the one site that forgot would search
    # PATH in silence; with none, `_guard` turns a forgotten program into an
    # immediate refusal.
    argv = [
        program, "-p", prompt,
        "--output-format", "json",
        "--allowedTools", "Read Grep Glob",
        "--disallowedTools", "Write Edit Bash",
    ]
    if model:
        argv += ["--model", model]
    return _guard(argv)


def _copilot_argv(prompt, model=None, program=None):
    argv = [
        program, "-p", prompt,
        "-s", "--no-ask-user",
        "--allow-tool=read",
        "--deny-tool=write", "--deny-tool=shell",
    ]
    if model:
        argv += ["--model", model]
    return _guard(argv)


def _claude_result_event(text):
    """Return the `result` session event, or None if text is not an envelope."""
    try:
        payload = json.loads(text)
    except ValueError:
        return None
    events = payload if isinstance(payload, list) else [payload]
    for event in reversed(events):
        if isinstance(event, dict) and event.get("type") == "result":
            return event
    return None


def _claude_parse(text):
    event = _claude_result_event(text)
    if event is None:
        return text
    return event.get("result", "")


def _claude_cost(text):
    event = _claude_result_event(text)
    return None if event is None else event.get("total_cost_usd")


def _passthrough(text):
    return text


def _no_cost(_text):
    return None


ADAPTERS = {
    "claude": Adapter("claude", "claude", _claude_argv, _claude_parse, _claude_cost),
    "copilot": Adapter("copilot", "copilot", _copilot_argv, _passthrough, _no_cost),
}

#: Claude first — it reports per-call spend, which the budget guard can use.
PREFERENCE = ("claude", "copilot")


def program_for(name, project_dir=None):
    """Where adapter `name`'s binary is, as an `exec_path.Resolution`.

    The one place an agent CLI's location is decided. `path` is absolute or the
    worker does not start, and `reason` is a printable sentence saying which
    refusal applied — which is why this is split out of `detect` rather than
    folded into it: `--agent claude` skips detection entirely and still has to
    be told where claude is, and a caller that got None deserves better than a
    None.

    A tree with no resolver is a refusal like any other, carried out through the
    same return shape so `main()` needs no separate branch for it: the operator
    is told the store is incomplete instead of being shown a traceback.
    """
    binary = ADAPTERS[name].binary
    if exec_path is None:
        return _Unresolvable(None, NO_RESOLVER % binary)
    return exec_path.resolve(binary, project_dir)


def detect(project_dir=None):
    """Name of the first supported agent CLI usable here, or None.

    "Usable" is stricter than "on PATH": a CLI that resolves inside the project
    being audited is not one the operator installed (SEC-003), and it is that
    project's contents the worker is about to read. Ask `program_for` for the
    reason.
    """
    for name in PREFERENCE:
        if program_for(name, project_dir).path:
            return name
    return None
