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

import hashlib
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


#: A secret's stand-in: how long it was, what it started with, and a truncated
#: digest of the whole of it. Enough for a reviewer to tell a live credential
#: from a test fixture without being handed either. The digest is what makes the
#: stand-in *stable* — the same value fingerprints identically on every run, so
#: last month's report can still be diffed against this one, and two 40-character
#: keys that both start `sk-a` stay distinguishable. A row of asterisks does
#: neither.
#:
#: This spelling is the canonical one, and it is canonical because two producers
#: write fingerprints into the same report — this function, and the agent
#: following the skill's own redaction rule — so a second spelling costs exactly
#: the property the digest is here for: a reader cannot match this month's
#: stand-in against last month's mechanically. The tie goes to the deterministic
#: producer, and to the form that survives an awkward value: `{prefix!r}` quotes
#: and escapes, so a suppressed prefix reads `prefix=''` rather than trailing
#: whitespace, and a prefix containing a space or a comma stays parseable. A
#: prose form ("44 chars, prefix sk-p") has neither property. Any document
#: stating the rule quotes this constant rather than paraphrasing it.
_REDACTED = "<redacted len={n} prefix={prefix!r} sha256={digest}>"

#: How much of the value the fingerprint may show. Four characters is enough to
#: recognise a provider prefix — `AKIA`, `ghp_`, `sk-p` — and short enough that
#: the remainder is not guessable from it. Arguable, like every default of this
#: kind; it is a constant so that an argument about it has somewhere to land.
KEEP_PREFIX = 4


def _fingerprint(value, keep=KEEP_PREFIX):
    # No prefix at all from a value short enough that four characters would be
    # most of it: `len=6 prefix='hunte'` is not a redaction, it is a hint. The
    # digest still identifies the value across runs, which is the part a
    # reviewer needs; the prefix is only ever a convenience.
    shown = value[:keep] if len(value) > keep * 2 else ""
    digest = hashlib.sha256(value.encode("utf-8")).hexdigest()[:8]
    return _REDACTED.format(n=len(value), prefix=shown, digest=digest)


def redact_literals(text, literals, *, keep=KEEP_PREFIX):
    """`text` with every string in `literals` replaced by a stable fingerprint.

    Literal substitution, never pattern detection, and that is the design rather
    than a first draft. A detector fails two ways and both are silent: a miss
    leaks the value this function exists to contain, and a false positive
    deletes evidence out of a report nobody will diff against the source. So the
    caller has to already know the bytes — which the one caller here does,
    because the finder handed them over as the finding's own evidence.

    Longest literal first, so one that is a prefix of another does not shred it
    and leave the tail in the clear.

    `_secret_literals` derives some of what the one caller passes, and that does
    not soften the rule above: every literal it derives is a substring of the
    evidence the finder handed over, so the pattern is applied to the value that
    is already known and never to the text being scrubbed. What a bad derivation
    can do is over-redact one `secrets` finding's own prose. What it cannot do is
    leak, or reach a finding of any other category.

    Here and not in the shared-primitive module, because ADR-030 places a
    primitive there once *more than one* skill needs it and only this one does.
    The moment a second caller appears it moves, by that rule and not by taste.
    """
    out = str(text)
    for literal in sorted({str(i) for i in literals if i}, key=len, reverse=True):
        out = out.replace(literal, _fingerprint(literal, keep))
    return out


#: The prose fields scrubbed of the snippet's literals. All three of the
#: model-written free-text fields FINDER_SCHEMA declares, and naming them here
#: is the point: `description` alone was two-thirds of a fix. `recommendation`
#: is a *required* field and "remove <the key> and rotate it" is the obvious
#: thing to write in it; a finder titles a secrets finding by quoting what it
#: found. Measured on 2026-08-23 with all three carrying the same AWS example
#: key: with only `description` in this tuple, 3 of 3 skeptic prompts carried
#: the credential and it reached the audit result.
#:
#: `cwe` is in the tuple too, and the reason it was nearly left out is worth
#: keeping. It was excluded as "an identifier" — a statement about what the
#: field is FOR, not about what a model puts in it. FINDER_SCHEMA declares it a
#: free string, and measured on 2026-08-23 a `cwe` of
#: `CWE-798 - the line is AWS_SECRET_ACCESS_KEY = "<key>"` came back out of
#: `audit()` with the credential intact through all three doors. Scrubbing it
#: costs nothing, because `redact_literals` substitutes literals and a genuine
#: `CWE-798` contains none of them. The general rule: a field earns exclusion by
#: what it COSTS to scrub, never by what it is nominally for.
#:
#: `file` is the one field excluded on cost — it is what a reader needs in order
#: to go and rotate the key, and `normalize_file` owns it. Widening the literal
#: set raised that cost rather than lowering it: a snippet reading
#: `key = "/home/ops/.aws/credentials"` now yields a path as a literal, so
#: scrubbing `file` could fingerprint the one field that says where to go.
#: `category` and `severity` are closed enums, so no prose reaches them.
#: `codeSnippet` is out because it is replaced whole rather than scrubbed.
_SCRUBBED_FIELDS = ("description", "title", "recommendation", "cwe")

#: How long a substring *derived* from the snippet has to be before it is
#: substituted. The floor is not about the secret, it is about the rest of the
#: sentence: a short piece of a line's value side — `1`, `r`, `dev`, `true` — is
#: far likelier to be an ordinary word somewhere in the prose than to be the
#: credential, and substituting `1` fingerprints every "line 12" in the report
#: while protecting nothing, because a stand-in publishing `len=1` has already
#: given a one-character value away. Eight is where value-side tokens stop
#: reading as English in practice. Arguable, like `KEEP_PREFIX`, and a constant
#: so that an argument about it has somewhere to land. The snippet itself and
#: its whole lines are substituted at any length: those are what the finder
#: declared to be the evidence, not something this module inferred from it.
MIN_DERIVED_LITERAL = 8

#: Punctuation a source line wraps a value in, trimmed off a derived literal so
#: the literal is the value and not the quoting around it. `=` is absent and the
#: absence is the decision: base64 padding ends a great many real keys, and
#: trimming it would substitute a prefix of the credential and leave the whole of
#: it standing wherever a finder wrote it out in full. `.` is absent for the same
#: reason — a JWT is three dot-separated segments and a trailing one is data.
_VALUE_WRAPPERS = "\"'`,;:()[]{}<> \t"

#: A quoted run, in the three quote characters source uses. Non-greedy and
#: applied per line, so an unterminated quote cannot swallow the rest of the
#: snippet, and the value is group 2.
_QUOTED = re.compile(r"""(['"`])(.*?)\1""")

#: Where a line's value side starts: the first `=` or `:`, whichever comes
#: first. `url = "https://x"` has both and the value starts at the `=`;
#: `Authorization: Bearer x` has both and it starts at the `:`. Everything in
#: front of the separator is the *name* — `AWS_SECRET_ACCESS_KEY`, `password`,
#: `Authorization` — and the name is the word a reader needs in order to know
#: which credential to rotate, so it never becomes a literal.
_VALUE_SIDE = re.compile(r"[=:]")


def _secret_literals(snippet):
    """Every substring of `snippet` this module is willing to substitute.

    The snippet itself and each of its lines, which is what a finder quotes when
    it copies the evidence — and then the value side of each line, because the
    leak this closes is the finder that quotes the credential *alone*. "remove
    <the key> and rotate it" is exactly what FINDER_SCHEMA's required
    `recommendation` asks for, and no whole-line literal ever matches it.
    Measured 2026-08-24 on a snippet of `AWS_SECRET_ACCESS_KEY = "<key>"`: with
    only the snippet and its lines in the set, the credential came back out of
    `audit()` intact in `title`, `description` and `recommendation`, in the same
    run whose `codeSnippet` was fingerprinted.

    Value side means three things, and they overlap on purpose because a snippet
    is a few lines and a redundant literal costs one dictionary slot: every
    quoted run on the line, which is what keeps a value carrying its own `:` and
    `/` in one piece; the tail after the line's first `=` or `:`, which is the
    unquoted `.env` and YAML shape; and that tail's whitespace-separated tokens,
    which is what reaches the credential in `Authorization: Bearer <token>`
    where the scheme is a public word and the token is not.

    Derived literals are held to `MIN_DERIVED_LITERAL`; the snippet and its whole
    lines are not.
    """
    literals = [snippet]
    for line in snippet.splitlines():
        line = line.strip()
        if not line:
            continue
        literals.append(line)
        derived = [match.group(2) for match in _QUOTED.finditer(line)]
        separator = _VALUE_SIDE.search(line)
        if separator:
            tail = line[separator.end():]
            derived.append(tail)
            derived.extend(tail.split())
        literals.extend(
            token for token in (item.strip(_VALUE_WRAPPERS) for item in derived)
            if len(token) >= MIN_DERIVED_LITERAL)
    return literals


def redact_secret_evidence(finding):
    """A `secrets`-category finding with its evidence fingerprinted.

    Here rather than in the engine because this module is where the shape of a
    finding is declared: `codeSnippet` exists in FINDER_SCHEMA and nowhere else
    in the tree, so the rule about what may be carried in it belongs beside it.

    `codeSnippet` is a verbatim copy of bytes read out of the scanned
    repository, and for this one category those bytes *are* the credential, so
    it is replaced whole. Each of the four fields in `_SCRUBBED_FIELDS` — the
    ones the model writes prose into — is then scrubbed of everything
    `_secret_literals` derives from that snippet: the snippet, each of its
    lines, and the value side of each of its lines. A finder that writes
    "hardcoded key AKIA... on line 12" has copied the snippet into its prose; a
    finder that writes "remove AKIA... and rotate it" has copied only the
    credential out of it, and does either in whichever field it is filling.

    Every other category comes back untouched. The vulnerable-code block is most
    of what a report is worth for an injection or an auth finding, and this is
    not a secret detector — it acts only where the finder already said
    "secrets". State what that leaves rather than papering over it. Substitution
    is byte for byte against substrings of the snippet, so three things survive:
    a credential a finder *retyped* rather than copied — paraphrased, re-cased,
    abbreviated with an ellipsis; one shorter than `MIN_DERIVED_LITERAL` that is
    neither the whole snippet nor a whole line of it; and one quoted from
    somewhere `codeSnippet` never went. Catching any of those needs the pattern
    detection `redact_literals` refuses, and refuses for reasons.

    Prevention, not retraction. It stops a value from being written; it cannot
    recall one already committed. ADR-010's open question about an escape hatch
    for spec-manager's append-only resolution logs is a different mechanism in a
    different skill, and this does not close it.
    """
    if finding.get("category") != "secrets":
        return finding
    snippet = str(finding.get("codeSnippet") or "")
    if not snippet:
        return finding
    out = dict(finding)
    out["codeSnippet"] = _fingerprint(snippet)
    literals = _secret_literals(snippet)
    for field in _SCRUBBED_FIELDS:
        if finding.get(field):
            out[field] = redact_literals(finding[field], literals)
    return out
