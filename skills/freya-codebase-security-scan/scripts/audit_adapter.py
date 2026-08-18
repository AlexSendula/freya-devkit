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
"""

from __future__ import annotations

import json
import shutil
from collections import namedtuple

#: Flags that would hand a worker general-purpose tool access. Never emitted.
BLANKET_FLAGS = ("--allow-all-tools", "--allow-all", "--allow-all-paths", "--allow-all-urls")

Adapter = namedtuple("Adapter", "name binary build_argv parse_stdout cost")


class UnsafeInvocation(Exception):
    """An argv would have granted a worker more than read access."""


def _guard(argv):
    for token in argv:
        for flag in BLANKET_FLAGS:
            if token == flag or token.startswith(flag + "="):
                raise UnsafeInvocation(
                    f"refusing to run an audit worker with {flag}: writes through the "
                    "shell are not blocked by --deny-tool"
                )
    return argv


def _claude_argv(prompt, model=None):
    argv = [
        "claude", "-p", prompt,
        "--output-format", "json",
        "--allowedTools", "Read Grep Glob",
        "--disallowedTools", "Write Edit Bash",
    ]
    if model:
        argv += ["--model", model]
    return _guard(argv)


def _copilot_argv(prompt, model=None):
    argv = [
        "copilot", "-p", prompt,
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


def detect():
    """Name of the first supported agent CLI on PATH, or None."""
    for name in PREFERENCE:
        if shutil.which(ADAPTERS[name].binary):
            return name
    return None
