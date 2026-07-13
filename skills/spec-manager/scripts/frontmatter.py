#!/usr/bin/env python3
"""
Scoped, schema-validated frontmatter parser for spec files.

This replaces the previous hand-rolled regex parser, which silently discarded
inline-array fields (e.g. `tags: [a, b]` was parsed as a string then dropped).
The Behavior Layer extends the spec schema with structured metadata that the
model *depends on*, so the substrate must be reliable: this parser handles our
exact, versioned, model-authored grammar and **fails loud** — raising
`FrontmatterError` on anything outside the grammar rather than silently dropping
it. It is deliberately NOT a full YAML engine (the plugin is stdlib-only /
zero-install); it is a strict subset that covers what spec frontmatter uses.

Supported grammar
-----------------
- `key: value` scalars (strings; bare integers coerced to int; dates stay strings)
- single- or double-quoted scalar strings
- inline flow arrays: `tags: [authentication, security, webauthn]`
- block sequences:
      related_code:
        - src/lib/auth/passkeys.ts
        - src/api/routes/auth.ts
- one level of list-of-mappings (for `behaviors:`):
      behaviors:
        - behavior_id: BEH-007
          title: Successful passkey login
          state: accepted
- `#` line comments and trailing inline comments (a `#` is a comment only when
  preceded by whitespace — so a locator like `foo.feature#scenario` is preserved)

Anything else (tab indentation, an orphan sequence item, a missing closing
fence, a malformed line) raises `FrontmatterError`.
"""

import re

SCHEMA_VERSION = 1

# Spec frontmatter schema (v1). Behavior-record sub-validation is added in a
# later step; unknown fields are always preserved (round-trip safe), never an
# error — only known fields are type-checked.
SPEC_SCHEMA = {
    "required": {
        "id": str,
        "title": str,
        "category": str,
        "status": str,
    },
    "optional": {
        "tags": list,
        "certainty": int,
        "created": str,
        "updated": str,
        "related_code": list,
        "intentional_decisions": list,
        "behaviors": list,
    },
}

# ADR frontmatter schema (P4a). ADRs are cross-cutting decision records; lifecycle
# mirrors behaviors — only `accepted` is authoritative. Unknown fields preserved.
ADR_STATES = ("proposed", "accepted", "superseded", "deprecated")

ADR_SCHEMA = {
    "required": {
        "id": str,
        "title": str,
        "status": str,
    },
    "optional": {
        "created": str,
        "updated": str,
        "tags": list,
        "supersedes": str,
        "superseded_by": str,
        "related_code": list,
    },
}


class FrontmatterError(ValueError):
    """Raised when frontmatter is outside the supported grammar."""


# Behavior-record vocabulary. The lifecycle is closed; the adapter set is
# intentionally a generous-but-checked allow-list (vision lists `... | manual`
# as extensible — new adapters are added here as phases ship, so an unknown
# adapter still fails loud rather than pointing at a runner with no implementation).
# Lifecycle: proposed -> confirmed -> accepted (+ quarantined / deprecated).
# `confirmed` = a human confirmed the intent but the test is still owed (design
# 03 §3): it carries intent (and may declare an `entry`) but asserts no test, so
# adapter/locator are not required for it (see validate_behaviors below).
BEHAVIOR_STATES = ("proposed", "confirmed", "accepted", "quarantined", "deprecated")
KNOWN_ADAPTERS = (
    "cucumber", "behave", "pytest-bdd",          # Gherkin family
    "jest", "vitest", "mocha", "jasmine",         # JS unit
    "playwright", "cypress",                      # JS e2e
    "pytest", "unittest",                         # Python
    "manual",                                     # human-verified, no runner
)
# Test levels (vision: the layer is test-level-agnostic). Optional on a behavior,
# but when present it must be one of these — it's the runner's dispatch key, so a
# typo would silently route a behavior to the wrong (or no) coverage path.
KNOWN_LEVELS = ("unit", "component", "integration", "e2e")
_BEH_ID_RE = re.compile(r"BEH-\d{3,}")


# --------------------------------------------------------------------------- #
# Scalar / value parsing
# --------------------------------------------------------------------------- #

def _strip_inline_comment(s: str) -> str:
    """Remove a trailing ` # comment`, respecting quotes.

    A `#` only starts a comment when it is preceded by whitespace (YAML rule),
    so `foo.feature#scenario` and `#fff` keep their `#`.
    """
    in_single = in_double = False
    for idx, ch in enumerate(s):
        if ch == "'" and not in_double:
            in_single = not in_single
        elif ch == '"' and not in_single:
            in_double = not in_double
        elif ch == "#" and not in_single and not in_double:
            if idx > 0 and s[idx - 1] in (" ", "\t"):
                return s[:idx].rstrip()
    return s


def _split_flow(inner: str) -> list:
    """Split the inside of a flow array on commas, respecting quotes."""
    items, buf = [], []
    in_single = in_double = False
    for ch in inner:
        if ch == "'" and not in_double:
            in_single = not in_single
            buf.append(ch)
        elif ch == '"' and not in_single:
            in_double = not in_double
            buf.append(ch)
        elif ch == "," and not in_single and not in_double:
            items.append("".join(buf).strip())
            buf = []
        else:
            buf.append(ch)
    if in_single or in_double:
        raise FrontmatterError(f"unterminated quote in flow array: {inner!r}")
    tail = "".join(buf).strip()
    if tail:
        items.append(tail)
    return items


def _parse_flow_seq(s: str) -> list:
    if not s.endswith("]"):
        raise FrontmatterError(f"unterminated flow sequence: {s!r}")
    inner = s[1:-1].strip()
    if not inner:
        return []
    return [_parse_scalar(x) for x in _split_flow(inner)]


def _parse_scalar(s: str):
    s = s.strip()
    if len(s) >= 2 and s[0] == s[-1] and s[0] in ("'", '"'):
        return s[1:-1]
    if re.fullmatch(r"-?\d+", s):
        return int(s)
    return s


def _parse_value(s: str):
    if s.startswith("["):
        return _parse_flow_seq(s)
    return _parse_scalar(s)


# --------------------------------------------------------------------------- #
# Block (line-oriented) parsing
# --------------------------------------------------------------------------- #

# A list item is a mapping entry when it looks like `ident: ...` (colon followed
# by whitespace or end-of-line) — this excludes scalars like `src/x.ts` and URLs
# like `https://...` (whose colon is followed by `/`, not whitespace).
_MAP_ITEM_RE = re.compile(r"[A-Za-z0-9_]+:(\s|$)")


def _logical_lines(raw_lines):
    """Return [(indent, content)] for non-blank, non-comment lines."""
    out = []
    for ln in raw_lines:
        full = ln.rstrip()
        content = full.strip()
        if not content or content.startswith("#"):
            continue
        indent = len(full) - len(full.lstrip(" "))
        if "\t" in full[:indent + 1]:
            raise FrontmatterError("tab indentation is not allowed")
        out.append((indent, content))
    return out


def _parse_sequence(lines, i, indent):
    items = []
    while i < len(lines):
        cur_indent, content = lines[i]
        if cur_indent < indent:
            break
        if cur_indent > indent:
            raise FrontmatterError(f"unexpected indentation in sequence: {content!r}")
        if not content.startswith("- "):
            break  # a non-dash line at this indent ends the sequence
        item_body = content[2:].strip()

        if _MAP_ITEM_RE.match(item_body):
            # list-of-mappings: first key sits on the dash line, the rest are
            # indented deeper. One level only.
            mapping = {}
            key, _, rest = item_body.partition(":")
            mapping[key.strip()] = _parse_value(_strip_inline_comment(rest.strip()))
            i += 1
            while i < len(lines):
                ci, cc = lines[i]
                if ci <= indent or cc.startswith("- "):
                    break
                if ":" not in cc:
                    raise FrontmatterError(f"expected 'key: value' in list item: {cc!r}")
                k2, _, r2 = cc.partition(":")
                mapping[k2.strip()] = _parse_value(_strip_inline_comment(r2.strip()))
                i += 1
            items.append(mapping)
        else:
            items.append(_parse_value(_strip_inline_comment(item_body)))
            i += 1
    return items, i


def _parse_mapping(lines, i, indent):
    result = {}
    while i < len(lines):
        cur_indent, content = lines[i]
        if cur_indent < indent:
            break
        if cur_indent > indent:
            raise FrontmatterError(f"unexpected indentation: {content!r}")
        if content.startswith("- "):
            raise FrontmatterError(f"unexpected sequence item in mapping: {content!r}")
        if ":" not in content:
            raise FrontmatterError(f"expected 'key: value': {content!r}")

        key, _, rest = content.partition(":")
        key = key.strip()
        rest = _strip_inline_comment(rest.strip())

        if rest == "":
            # block value: a sequence or nested mapping on following lines
            child = i + 1
            if child < len(lines):
                ci, cc = lines[child]
                if cc.startswith("- ") and ci >= indent:
                    result[key], i = _parse_sequence(lines, child, ci)
                    continue
                if ci > indent:
                    result[key], i = _parse_mapping(lines, child, ci)
                    continue
            result[key] = None
            i += 1
        else:
            result[key] = _parse_value(rest)
            i += 1
    return result, i


# --------------------------------------------------------------------------- #
# Public API
# --------------------------------------------------------------------------- #

def parse_frontmatter(text: str):
    """Parse leading `---` frontmatter. Returns (dict, body).

    No frontmatter (text does not open with a `---` fence) returns ({}, text).
    An opened-but-unterminated fence, or a malformed line, raises FrontmatterError.
    """
    lines = text.split("\n")
    if not lines or lines[0].strip() != "---":
        return {}, text

    closing = None
    for idx in range(1, len(lines)):
        if lines[idx].strip() == "---":
            closing = idx
            break
    if closing is None:
        raise FrontmatterError("unterminated frontmatter: missing closing '---'")

    fm_lines = _logical_lines(lines[1:closing])
    body = "\n".join(lines[closing + 1:])
    data, consumed = _parse_mapping(fm_lines, 0, 0)
    if consumed != len(fm_lines):
        # _parse_mapping stopped early — something is structurally wrong.
        leftover = fm_lines[consumed][1]
        raise FrontmatterError(f"could not parse frontmatter near: {leftover!r}")
    return data, body


def _type_ok(value, expected) -> bool:
    if expected is int:
        return isinstance(value, int) and not isinstance(value, bool)
    return isinstance(value, expected)


def validate_behaviors(behaviors, spec_id: str = None) -> list:
    """Validate a spec's `behaviors:` list of records.

    Each record is the first-class `Behavior` entity (vision §3): a stable
    `BEH-NNN` id, a closed lifecycle `state`, an `adapter`, and (for everything
    but `manual`) a `locator`. `spec_id` inside a record is optional — it is
    inherited from the parent spec — but if present it must match. Duplicate
    `behavior_id`s **within this spec** are flagged here; cross-spec reuse is a
    `verify_links` concern (Step 5).
    """
    errors = []
    if not isinstance(behaviors, list):
        return ["'behaviors' must be a list"]

    seen = {}
    for idx, b in enumerate(behaviors):
        where = f"behaviors[{idx}]"
        if not isinstance(b, dict):
            errors.append(f"{where}: must be a mapping")
            continue

        bid = b.get("behavior_id")
        if not bid:
            errors.append(f"{where}: missing required field: behavior_id")
        elif not isinstance(bid, str) or not _BEH_ID_RE.fullmatch(bid):
            errors.append(f"{where}: behavior_id '{bid}' must match BEH-NNN")
        elif bid in seen:
            errors.append(f"{where}: duplicate behavior_id '{bid}' (already at {seen[bid]})")
        else:
            seen[bid] = where

        title = b.get("title")
        if not title or not isinstance(title, str):
            errors.append(f"{where}: missing or non-string title")

        state = b.get("state")
        if state not in BEHAVIOR_STATES:
            errors.append(
                f"{where}: state '{state}' must be one of {', '.join(BEHAVIOR_STATES)}"
            )

        # Only `accepted` asserts a real, linked, passing test, so adapter and
        # locator are *required* only for accepted. Pre-test states (`proposed`,
        # `confirmed`) may omit them — intent confirmed, test owed (design 03 §3).
        # When either is present in any state it is still validated, so a typo
        # fails loud rather than silently routing to the wrong runner.
        adapter = b.get("adapter")
        if state == "accepted":
            if adapter not in KNOWN_ADAPTERS:
                errors.append(
                    f"{where}: adapter '{adapter}' must be one of {', '.join(KNOWN_ADAPTERS)}"
                )
        elif adapter is not None and adapter not in KNOWN_ADAPTERS:
            errors.append(
                f"{where}: adapter '{adapter}' must be one of {', '.join(KNOWN_ADAPTERS)}"
            )

        locator = b.get("locator")
        if state == "accepted" and adapter != "manual":
            if not locator or not isinstance(locator, str):
                errors.append(f"{where}: missing locator (required for accepted adapter '{adapter}')")
        elif locator is not None and not isinstance(locator, str):
            errors.append(f"{where}: locator must be a string")

        # `level` and `entry` are optional, but validated when present (catch typos
        # in the runner's dispatch key, and a non-string entry path).
        level = b.get("level")
        if level is not None and level not in KNOWN_LEVELS:
            errors.append(
                f"{where}: level '{level}' must be one of {', '.join(KNOWN_LEVELS)}"
            )

        entry = b.get("entry")
        if entry is not None and not isinstance(entry, str):
            errors.append(f"{where}: entry must be a string (a project-relative path)")

        sid = b.get("spec_id")
        if sid is not None:
            if not isinstance(sid, str):
                errors.append(f"{where}: spec_id must be a string")
            elif spec_id is not None and sid != spec_id:
                errors.append(
                    f"{where}: spec_id '{sid}' does not match parent spec '{spec_id}'"
                )

    return errors


def validate(frontmatter: dict, schema_version: int = SCHEMA_VERSION, schema: dict = None) -> list:
    """Validate parsed frontmatter against a versioned schema.

    Returns a list of human-readable error strings (empty == valid). Required
    fields must be present and correctly typed; known optional fields are
    type-checked when present; **unknown fields are preserved and never an
    error** (forward/backward compatibility).
    """
    if schema_version != SCHEMA_VERSION:
        return [f"unsupported schema_version: {schema_version} (expected {SCHEMA_VERSION})"]
    schema = schema or SPEC_SCHEMA
    errors = []
    for key, typ in schema["required"].items():
        if key not in frontmatter or frontmatter[key] is None:
            errors.append(f"missing required field: {key}")
        elif not _type_ok(frontmatter[key], typ):
            errors.append(f"field '{key}' must be {typ.__name__}, got {type(frontmatter[key]).__name__}")
    for key, typ in schema["optional"].items():
        if key in frontmatter and frontmatter[key] is not None and not _type_ok(frontmatter[key], typ):
            errors.append(f"field '{key}' must be {typ.__name__}, got {type(frontmatter[key]).__name__}")
    schema_fields = {**schema.get("required", {}), **schema.get("optional", {})}
    if "behaviors" in schema_fields:
        behaviors = frontmatter.get("behaviors")
        if isinstance(behaviors, list):
            errors.extend(validate_behaviors(behaviors, frontmatter.get("id")))
    return errors


def validate_adr(frontmatter: dict) -> list:
    """Validate ADR frontmatter against ADR_SCHEMA + the closed status set.

    Returns a list of human-readable errors (empty == valid). Reuses `validate`
    for required/optional typing, then adds the ADR `status` enum check.
    """
    errors = validate(frontmatter, schema=ADR_SCHEMA)
    status = frontmatter.get("status")
    if status is not None and status not in ADR_STATES:
        errors.append(f"status '{status}' must be one of {', '.join(ADR_STATES)}")
    return errors
