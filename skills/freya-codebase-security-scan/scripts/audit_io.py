#!/usr/bin/env python3
"""Parse and validate what an agent CLI returns for an audit task.

Neither Claude Code nor Copilot enforces a *content* schema on a headless
response — Claude's `--output-format json` is a session envelope whose payload
is still free text, and Copilot's `-s` only suppresses session metadata. The
spike (design 6.1.1) confirmed Copilot narrates before its JSON. So extraction
and validation are ours, and this module is the whole of it.

Stdlib only: no jsonschema. The validator supports exactly the JSON-Schema
subset the two audit schemas use.
"""

from __future__ import annotations

import json
import re

CATEGORIES = ["auth", "injection", "secrets", "api", "config", "file"]
SEVERITIES = ["critical", "high", "medium", "low", "info"]
SKEPTICS = ["exploitability", "compensating-controls", "spec-intentional"]

FINDER_SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "required": ["findings"],
    "properties": {
        "findings": {
            "type": "array",
            "items": {
                "type": "object",
                "additionalProperties": False,
                "required": ["category", "severity", "title", "description",
                             "file", "line", "recommendation"],
                "properties": {
                    "category": {"type": "string", "enum": CATEGORIES},
                    "severity": {"type": "string", "enum": SEVERITIES},
                    "title": {"type": "string"},
                    "description": {"type": "string"},
                    "file": {"type": "string"},
                    "line": {"type": "integer", "minimum": 0},
                    "cwe": {"type": "string"},
                    "codeSnippet": {"type": "string"},
                    "recommendation": {"type": "string"},
                },
            },
        },
    },
}

VERDICT_SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "required": ["lens", "verdict", "reason"],
    "properties": {
        "lens": {"type": "string", "enum": SKEPTICS},
        "verdict": {"type": "string", "enum": ["refuted", "upheld"]},
        "reason": {"type": "string"},
        "specReference": {"type": "string"},
    },
}

_FENCE = re.compile(r"```(?:[a-zA-Z0-9_-]+)?\s*\n(.*?)```", re.S)

#: Sentinel for "this text is not JSON". `None` cannot serve: `null` parses.
_UNPARSED = object()

#: How many `{` positions the salvage scanner will try before giving up. A `{`
#: that never balances makes its scan run to the end of the response, and
#: restarting at every following `{` is quadratic — measured at 6.9s for a
#: 433KB response with a thousand stray braces, burned on a pool thread that
#: `--timeout` does not cover. A response needing more starts than this is not
#: one the driver can use anyway.
_MAX_SCAN_STARTS = 500


class SchemaError(Exception):
    """A payload did not match its schema. `path` locates the failure."""

    def __init__(self, path, message):
        super().__init__(f"{path}: {message}")
        self.path = path


def _parse(text):
    """`text` as JSON, or `_UNPARSED`. json.loads already ignores surrounding
    whitespace, so a fenced block needs no stripping of its own."""
    try:
        return json.loads(text)
    except ValueError:
        return _UNPARSED


def _balanced_objects(text):
    """Every complete brace-balanced JSON object in text, in document order.

    Tracks string state so a brace inside a string value does not end the
    object — agent prose regularly contains them. On a successful parse the
    scan resumes *past* the object, so its nested braces are not re-offered as
    candidates of their own.
    """
    objects = []
    start = text.find("{")
    starts = 0
    while start != -1 and starts < _MAX_SCAN_STARTS:
        starts += 1
        depth = 0
        in_string = False
        escaped = False
        end = -1
        for i in range(start, len(text)):
            ch = text[i]
            if in_string:
                if escaped:
                    escaped = False
                elif ch == "\\":
                    escaped = True
                elif ch == '"':
                    in_string = False
                continue
            if ch == '"':
                in_string = True
            elif ch == "{":
                depth += 1
            elif ch == "}":
                depth -= 1
                if depth == 0:
                    end = i
                    break
        if end != -1:
            obj = _parse(text[start:end + 1])
            if obj is not _UNPARSED:
                objects.append(obj)
                start = text.find("{", end + 1)
                continue
        start = text.find("{", start + 1)
    return objects


def extract_json(text, schema=None):
    """Pull the agent's JSON answer out of its stdout. None if there isn't one.

    LAST valid candidate, not first. This used to return the first object that
    parsed, so a worker that showed the output format before answering — "if I
    found nothing I would return {"findings": []}; here is what I found: {…}" —
    had its own example handed back as its answer. The example is itself
    FINDER_SCHEMA-valid, so validation passed, the task was recorded as
    answered, no retry fired, and a real finding vanished into an exit-0 clean
    report. Schema-awareness alone does not fix that shape; the selection rule
    has to, which is why the schema is a parameter rather than a filter.

    Candidates are grouped by how deliberate they are — a fenced block is an
    answer the worker marked as one, an object salvaged from mid-prose is a
    guess — and the groups are searched in that order so that trailing prose
    cannot outrank a fenced answer. With no schema, or when nothing validates,
    the first parseable object is returned: that keeps the schema-less callers
    unchanged and leaves `ask` a concrete object to report a SchemaError
    against rather than the useless "no JSON object in the response".
    """
    if not text:
        return None
    groups = [
        [obj for obj in (_parse(block) for block in _FENCE.findall(text))
         if obj is not _UNPARSED],
        [obj for obj in [_parse(text)] if obj is not _UNPARSED],
        _balanced_objects(text),
    ]
    if schema is not None:
        for group in groups:
            for obj in reversed(group):
                try:
                    validate(obj, schema)
                except SchemaError:
                    continue
                return obj
    for group in groups:
        if group:
            return group[0]
    return None


def _check_type(value, expected, path):
    ok = {
        "object": lambda v: isinstance(v, dict),
        "array": lambda v: isinstance(v, list),
        "string": lambda v: isinstance(v, str),
        # bool is an int in Python; the schemas never want one
        "integer": lambda v: isinstance(v, int) and not isinstance(v, bool),
    }[expected]
    if not ok(value):
        raise SchemaError(path, f"expected {expected}, got {type(value).__name__}")


def validate(obj, schema, path="$"):
    """Raise SchemaError unless obj matches schema."""
    _check_type(obj, schema["type"], path)

    if "enum" in schema and obj not in schema["enum"]:
        raise SchemaError(path, f"{obj!r} not one of {schema['enum']}")

    if "minimum" in schema and obj < schema["minimum"]:
        raise SchemaError(path, f"{obj} below minimum {schema['minimum']}")

    if schema["type"] == "object":
        for name in schema.get("required", []):
            if name not in obj:
                raise SchemaError(path, f"missing required key {name!r}")
        properties = schema.get("properties", {})
        if schema.get("additionalProperties") is False:
            for name in obj:
                if name not in properties:
                    raise SchemaError(path, f"unexpected key {name!r}")
        for name, sub in properties.items():
            if name in obj:
                validate(obj[name], sub, f"{path}.{name}" if path != "$" else name)

    elif schema["type"] == "array" and "items" in schema:
        for index, item in enumerate(obj):
            validate(item, schema["items"], f"{path}[{index}]")
