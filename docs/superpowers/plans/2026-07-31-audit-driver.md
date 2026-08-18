# Audit Driver Implementation Plan (Phase 4b)

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Move the `audit` engine off Claude's Workflow tool into a Python driver that owns all control flow and calls whichever agent CLI is installed as a headless, read-only worker — so `audit` runs on Copilot and Claude alike, and the JS workflow can be deleted.

**Architecture:** Invert the dependency. Today a Claude-only runtime owns the loop and calls our logic; after this, our logic owns the loop and calls the agent. The engine (loop-until-dry, dedup, majority voting, dispositions) becomes ordinary Python with a single injected `ask` callable, so it is unit-testable without spending a cent. The only per-agent surface is a ~20-line adapter that builds an argv and parses stdout.

**Tech Stack:** Python 3 stdlib only — `argparse`, `json`, `re`, `subprocess`, `concurrent.futures`, `shutil.which`, `unittest`, `unittest.mock`. No `jsonschema`; the driver ships a minimal validator for the two schemas it uses.

## Context

This is **Phase 4b of the portability track** ([`docs/design/portability/01-design.md`](../../design/portability/01-design.md) §6.1, §6.1.1). Branch `feat/polyglot-portability` stays open. Phase 4 made the three prose fan-out flows portable; `audit` was carved out because it is not prose — it runs on `workflows/codebase-security-audit.js` via the Workflow tool.

### Why a driver rather than prose

Copilot has multi-agent orchestration, but decomposition is **model-driven** and there is no schema-validated structured return. `audit`'s rigor lives precisely in the deterministic parts — loop-until-dry, cross-round dedup, N-skeptic majority voting. Expressed as prose those guarantees become suggestions. Reading the existing workflow confirms the port is mostly relocation: of its 143 lines, only the `agent(...)` call is Claude-provided.

### What must be preserved exactly

The engine's constants and logic are the contract. Any deviation changes audit results:

| Thing | Value |
|---|---|
| Categories | `auth`, `injection`, `secrets`, `api`, `config`, `file` |
| `K_EMPTY` | 2 consecutive dry rounds stop discovery |
| `MAX_ROUNDS` | 5 |
| Skeptic lenses | `exploitability`, `compensating-controls`, `spec-intentional` |
| Dedup key | `f"{file}::{line // 5}::{category}"` |
| Majority | `upheld * 2 > total` → `confirmed` |
| Spec refute | any lens `spec-intentional` with verdict `refuted` → `intentional-design` (wins over majority) |
| Unanimous refute | `upheld == 0` → `drop` (never returned) |
| Otherwise | `needs-review` |

**The output contract is unchanged.** The driver returns a JSON array of survivors, each carrying `disposition`, optional `specReference`, and `verification` = `{upheld, total, lenses}`. It does **not** write the report, assign `SEC-###` IDs, or re-evaluate previous findings — the skill's main loop still does all of that, so the report format stays identical and `freya-codebase-security-resolver` and `check-specs` keep parsing it unchanged.

### One deliberate behaviour change

In the JS, when **every** skeptic call fails, `vs` is empty, so `upheld == 0` and the finding is dropped as a false positive. That is a silent delete on error, and it contradicts the skill's own stated rule: *"only a **unanimous** refutation drops a finding. Any disagreement (split verdict) keeps it as NEEDS REVIEW — never silently delete an upheld or contested finding."* Zero verdicts is not a unanimous refutation; it is no information.

**The driver returns `needs-review` when no verdict was obtained**, and records `verification.total = 0` so the report shows the verification did not run. This is the only intentional divergence from the JS and must be tested explicitly.

### Read-only enforcement — the load-bearing security detail

From the spike (design §6.1.1, re-confirmed 2026-07-31: Copilot CLI is still **1.0.75**, the version tested, and Claude Code is 2.1.220 — every flag below is present in `--help` on both):

| Config | Result |
|---|---|
| Claude `--allowedTools "Read Grep Glob" --disallowedTools "Write Edit"` | **Held.** Attempted `Bash` 3×, all denied. |
| Copilot `--allow-tool='read' --deny-tool=write` | **Held.** Write tool *and* an explicit shell redirect both failed. |
| Copilot `--allow-all-tools --deny-tool=write` | **❌ BYPASSED — file created via a shell command.** |

"Deny beats allow" applies to the *write tool*, **not** to writes performed *through* the shell. The adapter must therefore use an **explicit allowlist that excludes shell**, with `--deny-tool` only as defence in depth. `--allow-all-tools` must never appear in an audit invocation — Task 2 makes that a hard, tested guard rather than a convention.

## Global Constraints

- **Python 3 stdlib only.** No `jsonschema`, no `requests`. Shebang `#!/usr/bin/env python3`. **Never invoke bare `python`.**
- **Tests must never call a real agent.** Every test injects a fake `ask` or mocks `subprocess.run`. A test that shells out to `claude` or `copilot` is a defect — it costs money and is non-deterministic.
- **Never `--allow-all-tools`, `--allow-all`, or `--allow-all-paths`** in any adapter argv. Task 2 asserts this.
- **The engine must not import the adapter.** It takes an `ask` callable. That is what makes it testable and what keeps the per-agent surface at ~20 lines.
- **Preserve the constants and disposition ladder exactly** as tabulated above, with the single documented exception for zero verdicts.
- **Cost is a real risk.** The spike measured **$0.396 for one finder worker on a trivial fixture**. Worst case here is 1 context + 5 rounds × 6 finders + 3 × findings — plausibly 100+ calls. The driver must refuse to start an unbounded run: caps are on by default and the user confirms before any spend.
- **Do not modify** `docs/design/`, `docs/explanations/`, `docs/migrations/`, `docs/superpowers/plans/`, or `.claude-plugin/`.
- **Commit locally after each task. Do NOT push.**
- Commit messages end with:
  `Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>`

## File Structure

| File | Responsibility |
|---|---|
| `skills/freya-codebase-security-scan/scripts/audit_io.py` | **Create.** JSON extraction from agent stdout + a minimal schema validator. |
| `skills/freya-codebase-security-scan/scripts/test_audit_io.py` | **Create.** |
| `skills/freya-codebase-security-scan/scripts/audit_adapter.py` | **Create.** Per-agent argv + stdout parsing + detection. The only agent-specific code. |
| `skills/freya-codebase-security-scan/scripts/test_audit_adapter.py` | **Create.** |
| `skills/freya-codebase-security-scan/scripts/audit_engine.py` | **Create.** Loop-until-dry, dedup, voting, dispositions. Pure; takes an `ask` callable. |
| `skills/freya-codebase-security-scan/scripts/test_audit_engine.py` | **Create.** |
| `skills/freya-codebase-security-scan/scripts/audit.py` | **Create.** CLI, worker pool, budget guard, degradation. |
| `skills/freya-codebase-security-scan/scripts/test_audit.py` | **Create.** |
| `bin/commands.json` | **Modify.** Register `security`. |
| `skills/freya-codebase-security-scan/SKILL.md` | **Modify.** Rewrite the `audit` section. |
| `bin/check_skill_conformance.py`, `bin/test_check_skill_conformance.py` | **Modify.** Retire the audit exemptions. |
| `CONTRIBUTING.md` | **Modify.** Drop the Workflow bullet. |
| `workflows/codebase-security-audit.js` | **Delete.** |

---

### Task 1: JSON extraction and schema validation

The spike's key output-shape finding: Copilot prefixes narration before the JSON, Claude wraps it in a session envelope. Both need salvage-extraction, and neither CLI enforces a *content* schema — so validation moves to us.

**Files:**
- Create: `skills/freya-codebase-security-scan/scripts/audit_io.py`
- Test: `skills/freya-codebase-security-scan/scripts/test_audit_io.py`

**Interfaces produced:**
- `extract_json(text: str) -> dict | None` — strip fences → direct parse → brace-balanced scan for the first complete object; `None` if nothing parses
- `SchemaError(Exception)` with a `.path` describing where validation failed
- `validate(obj, schema) -> None` — raises `SchemaError`; supports the JSON-Schema subset the two audit schemas use: `type` (object/array/string/integer), `required`, `properties`, `additionalProperties: false`, `enum`, `items`, `minimum`
- `FINDER_SCHEMA`, `VERDICT_SCHEMA`, `CATEGORIES`, `SEVERITIES`, `SKEPTICS` — ported verbatim from the JS

- [ ] **Step 1: Write the failing tests**

Create `skills/freya-codebase-security-scan/scripts/test_audit_io.py`:

```python
#!/usr/bin/env python3
"""Unit tests for audit JSON extraction and schema validation."""

import unittest

import audit_io


def finding(**over):
    f = {
        "category": "injection", "severity": "high", "title": "SQLi",
        "description": "concatenated query", "file": "src/db.js", "line": 42,
        "recommendation": "parameterize",
    }
    f.update(over)
    return f


class ExtractTest(unittest.TestCase):
    def test_bare_json(self):
        self.assertEqual(audit_io.extract_json('{"findings": []}'), {"findings": []})

    def test_fenced_json(self):
        self.assertEqual(
            audit_io.extract_json('```json\n{"findings": []}\n```'), {"findings": []})

    def test_fenced_without_language(self):
        self.assertEqual(audit_io.extract_json('```\n{"findings": []}\n```'), {"findings": []})

    def test_narration_before_json_is_salvaged(self):
        """Copilot prefixes prose; the spike proved this needs salvage-extraction."""
        text = 'I scanned the files and found one issue.\n\n{"findings": [1]}'
        self.assertEqual(audit_io.extract_json(text), {"findings": [1]})

    def test_narration_after_json_is_ignored(self):
        self.assertEqual(
            audit_io.extract_json('{"findings": []}\n\nLet me know if you want more.'),
            {"findings": []})

    def test_nested_braces_are_balanced_correctly(self):
        text = 'Result:\n{"findings": [{"file": "a.js", "meta": {"x": 1}}]}\ndone'
        self.assertEqual(audit_io.extract_json(text)["findings"][0]["meta"], {"x": 1})

    def test_brace_inside_a_string_does_not_end_the_object(self):
        text = 'x {"findings": [], "note": "a } brace"} y'
        self.assertEqual(audit_io.extract_json(text)["note"], "a } brace")

    def test_unparseable_returns_none(self):
        self.assertIsNone(audit_io.extract_json("I could not complete the scan."))

    def test_empty_returns_none(self):
        self.assertIsNone(audit_io.extract_json(""))


class ValidateTest(unittest.TestCase):
    def test_valid_finder_payload(self):
        audit_io.validate({"findings": [finding()]}, audit_io.FINDER_SCHEMA)

    def test_empty_findings_is_valid(self):
        audit_io.validate({"findings": []}, audit_io.FINDER_SCHEMA)

    def test_missing_required_key_raises(self):
        with self.assertRaises(audit_io.SchemaError):
            audit_io.validate({}, audit_io.FINDER_SCHEMA)

    def test_missing_required_field_in_item_raises(self):
        bad = finding()
        del bad["file"]
        with self.assertRaises(audit_io.SchemaError):
            audit_io.validate({"findings": [bad]}, audit_io.FINDER_SCHEMA)

    def test_unknown_category_raises(self):
        with self.assertRaises(audit_io.SchemaError):
            audit_io.validate({"findings": [finding(category="telepathy")]},
                              audit_io.FINDER_SCHEMA)

    def test_unknown_severity_raises(self):
        with self.assertRaises(audit_io.SchemaError):
            audit_io.validate({"findings": [finding(severity="apocalyptic")]},
                              audit_io.FINDER_SCHEMA)

    def test_additional_property_raises(self):
        with self.assertRaises(audit_io.SchemaError):
            audit_io.validate({"findings": [finding(sneaky="x")]}, audit_io.FINDER_SCHEMA)

    def test_wrong_type_raises(self):
        with self.assertRaises(audit_io.SchemaError):
            audit_io.validate({"findings": finding()}, audit_io.FINDER_SCHEMA)

    def test_line_must_be_integer(self):
        with self.assertRaises(audit_io.SchemaError):
            audit_io.validate({"findings": [finding(line="42")]}, audit_io.FINDER_SCHEMA)

    def test_negative_line_raises(self):
        with self.assertRaises(audit_io.SchemaError):
            audit_io.validate({"findings": [finding(line=-1)]}, audit_io.FINDER_SCHEMA)

    def test_optional_fields_are_allowed(self):
        audit_io.validate({"findings": [finding(cwe="CWE-89", codeSnippet="q + s")]},
                          audit_io.FINDER_SCHEMA)

    def test_valid_verdict(self):
        audit_io.validate({"lens": "exploitability", "verdict": "upheld", "reason": "r"},
                          audit_io.VERDICT_SCHEMA)

    def test_unknown_lens_raises(self):
        with self.assertRaises(audit_io.SchemaError):
            audit_io.validate({"lens": "vibes", "verdict": "upheld", "reason": "r"},
                              audit_io.VERDICT_SCHEMA)

    def test_unknown_verdict_raises(self):
        with self.assertRaises(audit_io.SchemaError):
            audit_io.validate({"lens": "exploitability", "verdict": "maybe", "reason": "r"},
                              audit_io.VERDICT_SCHEMA)

    def test_error_names_the_failing_path(self):
        bad = finding()
        del bad["file"]
        with self.assertRaises(audit_io.SchemaError) as ctx:
            audit_io.validate({"findings": [bad]}, audit_io.FINDER_SCHEMA)
        self.assertIn("findings[0]", str(ctx.exception))


class ConstantsTest(unittest.TestCase):
    def test_categories_match_the_retired_workflow(self):
        self.assertEqual(audit_io.CATEGORIES,
                         ["auth", "injection", "secrets", "api", "config", "file"])

    def test_skeptics_match_the_retired_workflow(self):
        self.assertEqual(audit_io.SKEPTICS,
                         ["exploitability", "compensating-controls", "spec-intentional"])


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run to verify they fail**

Run: `cd skills/freya-codebase-security-scan/scripts && python3 -m unittest test_audit_io -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'audit_io'`

- [ ] **Step 3: Implement**

Create `skills/freya-codebase-security-scan/scripts/audit_io.py`:

```python
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


class SchemaError(Exception):
    """A payload did not match its schema. `path` locates the failure."""

    def __init__(self, path, message):
        super().__init__(f"{path}: {message}")
        self.path = path


def _first_json_object(text):
    """Return the first complete brace-balanced JSON object in text, or None.

    Tracks string state so a brace inside a string value does not end the
    object — agent prose regularly contains them.
    """
    start = text.find("{")
    while start != -1:
        depth = 0
        in_string = False
        escaped = False
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
                    try:
                        return json.loads(text[start:i + 1])
                    except ValueError:
                        break
        start = text.find("{", start + 1)
    return None


def extract_json(text):
    """Pull a JSON object out of an agent's stdout. None if there isn't one."""
    if not text:
        return None
    for fenced in _FENCE.findall(text):
        try:
            return json.loads(fenced.strip())
        except ValueError:
            continue
    try:
        return json.loads(text.strip())
    except ValueError:
        pass
    return _first_json_object(text)


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
```

- [ ] **Step 4: Run to verify they pass**

Run: `cd skills/freya-codebase-security-scan/scripts && python3 -m unittest test_audit_io -v`
Expected: PASS — 26 tests, `OK`

- [ ] **Step 5: Mutation-check the two guards that matter**

1. In `_first_json_object`, delete the `in_string` tracking (treat `"` as an ordinary character).
   Expected: FAIL on `test_brace_inside_a_string_does_not_end_the_object`. **Restore.**
2. In `validate`, drop the `additionalProperties` block.
   Expected: FAIL on `test_additional_property_raises`. **Restore.**
3. In `_check_type`, change the `integer` check to `isinstance(v, int)` (allowing bool).
   Expected: no test fails — bool is not exercised. **Add** a test asserting `line=True` raises, then re-apply the mutation and confirm it now fails. **Restore.**

Re-run: PASS, 27 tests.

- [ ] **Step 6: Commit**

```bash
git add skills/freya-codebase-security-scan/scripts/audit_io.py \
        skills/freya-codebase-security-scan/scripts/test_audit_io.py
git commit -F - <<'EOF'
feat(audit): JSON extraction and schema validation for agent output

Neither agent CLI enforces a content schema on a headless response, and the
spike showed Copilot narrates before its JSON, so extraction and validation
have to be ours. Ports FINDER_SCHEMA and VERDICT_SCHEMA verbatim from the JS
workflow and adds a stdlib validator for the subset they use.

The brace scanner tracks string state, because agent prose routinely contains
braces inside string values.

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>
EOF
```

---

### Task 2: The agent adapter

The only per-agent code in the whole phase, and the only place the read-only boundary is enforced.

**Files:**
- Create: `skills/freya-codebase-security-scan/scripts/audit_adapter.py`
- Test: `skills/freya-codebase-security-scan/scripts/test_audit_adapter.py`

**Interfaces produced:**
- `ADAPTERS: dict[str, Adapter]` for `"claude"` and `"copilot"`
- `Adapter` — a namedtuple `(name, binary, build_argv, parse_stdout, reports_cost)`
- `build_argv(prompt, model=None) -> list[str]`
- `parse_stdout(text) -> str` — the payload, envelope removed
- `detect() -> str | None` — first adapter whose binary is on PATH, Claude preferred (it reports cost)
- `UnsafeInvocation(Exception)` — raised if an argv would grant blanket tool access

| | Claude | Copilot |
|---|---|---|
| Prompt | `-p <prompt>` | `-p <prompt>` |
| Clean output | `--output-format json` | `-s` |
| Read-only | `--allowedTools "Read Grep Glob"` + `--disallowedTools "Write Edit Bash"` | `--allow-tool=read` + `--deny-tool=write` + `--deny-tool=shell` |
| Suppress questions | implicit with `-p` | `--no-ask-user` |
| Model | `--model <m>` | `--model <m>` |
| Envelope | array of session events; payload at the `type=="result"` element's `.result` | none — plain text |
| Cost telemetry | `total_cost_usd` | none |

- [ ] **Step 1: Write the failing tests**

Create `skills/freya-codebase-security-scan/scripts/test_audit_adapter.py`:

```python
#!/usr/bin/env python3
"""Unit tests for the per-agent headless adapter.

Nothing here executes an agent: argv construction and stdout parsing are pure,
and detection is tested with shutil.which patched.
"""

import json
import unittest
from unittest import mock

import audit_adapter


class ArgvTest(unittest.TestCase):
    def test_claude_argv_shape(self):
        argv = audit_adapter.ADAPTERS["claude"].build_argv("find bugs")
        self.assertEqual(argv[0], "claude")
        self.assertIn("-p", argv)
        self.assertIn("find bugs", argv)
        self.assertIn("--output-format", argv)
        self.assertIn("json", argv)

    def test_copilot_argv_shape(self):
        argv = audit_adapter.ADAPTERS["copilot"].build_argv("find bugs")
        self.assertEqual(argv[0], "copilot")
        self.assertIn("-p", argv)
        self.assertIn("find bugs", argv)
        self.assertIn("-s", argv)
        self.assertIn("--no-ask-user", argv)

    def test_model_is_passed_through_when_given(self):
        for name in audit_adapter.ADAPTERS:
            argv = audit_adapter.ADAPTERS[name].build_argv("x", model="cheap-1")
            self.assertIn("--model", argv, name)
            self.assertIn("cheap-1", argv, name)

    def test_model_is_absent_when_not_given(self):
        for name in audit_adapter.ADAPTERS:
            self.assertNotIn("--model", audit_adapter.ADAPTERS[name].build_argv("x"), name)


class ReadOnlyTest(unittest.TestCase):
    """The no-writes boundary. The spike proved --allow-all-tools is bypassable
    via the shell even with --deny-tool=write, so an allowlist excluding shell
    is the only configuration that holds."""

    BLANKET = ("--allow-all-tools", "--allow-all", "--allow-all-paths", "--allow-all-urls")

    def test_no_adapter_ever_grants_blanket_access(self):
        for name, adapter in audit_adapter.ADAPTERS.items():
            argv = adapter.build_argv("x", model="m")
            for flag in self.BLANKET:
                self.assertNotIn(flag, argv, f"{name} must never pass {flag}")

    def test_claude_restricts_tools_to_read_only(self):
        argv = audit_adapter.ADAPTERS["claude"].build_argv("x")
        joined = " ".join(argv)
        self.assertIn("--allowedTools", joined)
        self.assertIn("Read", joined)
        self.assertNotIn("Write", " ".join(
            argv[argv.index("--allowedTools") + 1:argv.index("--allowedTools") + 2]))

    def test_copilot_denies_shell_not_just_write(self):
        """deny beats allow for the write *tool*, not for writes through the shell."""
        joined = " ".join(audit_adapter.ADAPTERS["copilot"].build_argv("x"))
        self.assertIn("--allow-tool=read", joined)
        self.assertIn("--deny-tool=shell", joined)

    def test_blanket_flag_in_a_prompt_is_rejected(self):
        """A prompt must never be able to smuggle a permission flag into argv."""
        with self.assertRaises(audit_adapter.UnsafeInvocation):
            audit_adapter.ADAPTERS["copilot"].build_argv("--allow-all-tools")


class ParseTest(unittest.TestCase):
    def test_claude_payload_comes_from_the_result_event(self):
        envelope = json.dumps([
            {"type": "system", "subtype": "init"},
            {"type": "assistant", "message": "thinking"},
            {"type": "result", "result": '{"findings": []}', "total_cost_usd": 0.4},
        ])
        self.assertEqual(
            audit_adapter.ADAPTERS["claude"].parse_stdout(envelope), '{"findings": []}')

    def test_claude_accepts_a_bare_object_envelope(self):
        envelope = json.dumps({"type": "result", "result": "payload"})
        self.assertEqual(audit_adapter.ADAPTERS["claude"].parse_stdout(envelope), "payload")

    def test_claude_falls_back_to_raw_text_when_not_an_envelope(self):
        self.assertEqual(
            audit_adapter.ADAPTERS["claude"].parse_stdout('{"findings": []}'),
            '{"findings": []}')

    def test_copilot_returns_stdout_unchanged(self):
        text = 'I looked around.\n{"findings": []}'
        self.assertEqual(audit_adapter.ADAPTERS["copilot"].parse_stdout(text), text)


class CostTest(unittest.TestCase):
    def test_claude_reports_cost(self):
        envelope = json.dumps([{"type": "result", "result": "x", "total_cost_usd": 0.396}])
        self.assertAlmostEqual(audit_adapter.ADAPTERS["claude"].cost(envelope), 0.396)

    def test_copilot_reports_no_cost(self):
        self.assertIsNone(audit_adapter.ADAPTERS["copilot"].cost("anything"))

    def test_missing_cost_field_is_none(self):
        self.assertIsNone(audit_adapter.ADAPTERS["claude"].cost('[{"type":"result","result":"x"}]'))


class DetectTest(unittest.TestCase):
    def test_prefers_claude_when_both_present(self):
        with mock.patch("shutil.which", side_effect=lambda b: f"/usr/bin/{b}"):
            self.assertEqual(audit_adapter.detect(), "claude")

    def test_falls_back_to_copilot(self):
        with mock.patch("shutil.which", side_effect=lambda b: "/usr/bin/copilot"
                        if b == "copilot" else None):
            self.assertEqual(audit_adapter.detect(), "copilot")

    def test_none_when_no_agent_cli_is_installed(self):
        with mock.patch("shutil.which", return_value=None):
            self.assertIsNone(audit_adapter.detect())


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run to verify they fail**

Run: `cd skills/freya-codebase-security-scan/scripts && python3 -m unittest test_audit_adapter -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'audit_adapter'`

- [ ] **Step 3: Implement**

Create `skills/freya-codebase-security-scan/scripts/audit_adapter.py`:

```python
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
```

- [ ] **Step 4: Run to verify they pass**

Run: `cd skills/freya-codebase-security-scan/scripts && python3 -m unittest test_audit_adapter -v`
Expected: PASS — 18 tests, `OK`

- [ ] **Step 5: Mutation-check the security boundary**

1. In `_copilot_argv`, replace the allowlist with `--allow-all-tools` plus `--deny-tool=write` (the configuration the spike proved bypassable).
   Expected: FAIL on `test_no_adapter_ever_grants_blanket_access` **and** `test_copilot_denies_shell_not_just_write`. **Restore.**
2. Make `_guard` a no-op returning `argv`.
   Expected: FAIL on `test_blanket_flag_in_a_prompt_is_rejected`. **Restore.**
3. In `_claude_argv`, drop `--disallowedTools`.
   Expected: no test fails — the allowlist is what holds, and the deny list is defence in depth. **This is expected**; do not add a test to force it. Note it in your report. **Restore.**

Re-run after restoring: PASS, 18 tests.

- [ ] **Step 6: Commit**

```bash
git add skills/freya-codebase-security-scan/scripts/audit_adapter.py \
        skills/freya-codebase-security-scan/scripts/test_audit_adapter.py
git commit -F - <<'EOF'
feat(audit): headless read-only adapter for Claude and Copilot

The only agent-specific code in the driver: argv construction, envelope
parsing, cost telemetry, and CLI detection.

The read-only boundary is the load-bearing part. The spike established that
"deny beats allow" covers the write *tool* but not writes through the shell —
`--allow-all-tools --deny-tool=write` let a worker create a file via a shell
redirect. Every argv here is an allowlist, and build_argv refuses to emit a
blanket permission flag even if one is smuggled in through the prompt.

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>
EOF
```

---

### Task 3: The engine

The relocated logic. Pure: it takes an `ask` callable, so every test runs offline and free.

**Files:**
- Create: `skills/freya-codebase-security-scan/scripts/audit_engine.py`
- Test: `skills/freya-codebase-security-scan/scripts/test_audit_engine.py`

**Interfaces produced:**
- `K_EMPTY = 2`, `MAX_ROUNDS = 5`
- `dedup_key(finding) -> str`
- `disposition(verdicts) -> tuple[str, str | None, dict]` → `(disposition, spec_reference, verification)`
- `discover(ask, context, *, max_findings=None, on_round=None) -> list[dict]`
- `verify(finding, ask, context, run) -> dict` — the finding plus `disposition`, `specReference`, `verification`
- `audit(ask, run, *, max_findings=None, on_round=None) -> list[dict]` — survivors only

`ask(prompt, schema=None) -> dict | str | None` is injected. `run(thunks) -> list` is injected too, so the engine does not care whether work is parallel or sequential — Task 4 supplies a pooled implementation, tests supply `lambda ts: [t() for t in ts]`.

- [ ] **Step 1: Write the failing tests**

Create `skills/freya-codebase-security-scan/scripts/test_audit_engine.py`:

```python
#!/usr/bin/env python3
"""Unit tests for the audit engine. No agent is ever called."""

import unittest

import audit_engine


SEQUENTIAL = lambda thunks: [t() for t in thunks]


def finding(file="a.js", line=10, category="injection", **over):
    f = {
        "category": category, "severity": "high", "title": "t", "description": "d",
        "file": file, "line": line, "recommendation": "r",
    }
    f.update(over)
    return f


def verdicts(*pairs):
    return [{"lens": lens, "verdict": v, "reason": "r"} for lens, v in pairs]


class DedupKeyTest(unittest.TestCase):
    def test_same_file_window_and_category_collapse(self):
        self.assertEqual(audit_engine.dedup_key(finding(line=10)),
                         audit_engine.dedup_key(finding(line=14)))

    def test_next_window_is_distinct(self):
        self.assertNotEqual(audit_engine.dedup_key(finding(line=10)),
                            audit_engine.dedup_key(finding(line=15)))

    def test_different_category_is_distinct(self):
        self.assertNotEqual(audit_engine.dedup_key(finding(category="auth")),
                            audit_engine.dedup_key(finding(category="secrets")))

    def test_different_file_is_distinct(self):
        self.assertNotEqual(audit_engine.dedup_key(finding(file="a.js")),
                            audit_engine.dedup_key(finding(file="b.js")))

    def test_matches_the_retired_workflow_format(self):
        self.assertEqual(audit_engine.dedup_key(finding(file="src/x.js", line=42,
                                                        category="api")),
                         "src/x.js::8::api")


class DispositionTest(unittest.TestCase):
    def test_spec_refute_outranks_a_majority_upheld(self):
        d, _, v = audit_engine.disposition(verdicts(
            ("exploitability", "upheld"), ("compensating-controls", "upheld"),
            ("spec-intentional", "refuted")))
        self.assertEqual(d, "intentional-design")  # spec refute wins over majority

    def test_two_of_three_upheld_without_spec_refute_is_confirmed(self):
        d, _, v = audit_engine.disposition(verdicts(
            ("exploitability", "upheld"), ("compensating-controls", "upheld"),
            ("spec-intentional", "upheld")))
        self.assertEqual(d, "confirmed")
        self.assertEqual(v, {"upheld": 3, "total": 3, "lenses": audit_engine.SKEPTICS})

    def test_one_of_two_upheld_is_needs_review(self):
        """Pins `upheld * 2 > total`. With >= this would wrongly be confirmed."""
        d, _, _ = audit_engine.disposition(verdicts(
            ("exploitability", "upheld"), ("compensating-controls", "refuted")))
        self.assertEqual(d, "needs-review")

    def test_unanimous_refute_is_dropped(self):
        d, _, _ = audit_engine.disposition(verdicts(
            ("exploitability", "refuted"), ("compensating-controls", "refuted")))
        self.assertEqual(d, "drop")

    def test_majority_with_one_refute_is_confirmed(self):
        d, _, _ = audit_engine.disposition(verdicts(
            ("exploitability", "upheld"), ("compensating-controls", "refuted"),
            ("spec-intentional", "upheld")))
        self.assertEqual(d, "confirmed")  # 2 of 3 -> majority

    def test_one_of_three_upheld_is_needs_review(self):
        """spec-intentional must be UPHELD here, or the spec branch would win."""
        d, _, _ = audit_engine.disposition(verdicts(
            ("exploitability", "refuted"), ("compensating-controls", "refuted"),
            ("spec-intentional", "upheld")))
        self.assertEqual(d, "needs-review")

    def test_spec_reference_is_carried_out(self):
        vs = verdicts(("exploitability", "upheld"))
        vs.append({"lens": "spec-intentional", "verdict": "refuted",
                   "reason": "r", "specReference": "SPEC-007"})
        d, ref, _ = audit_engine.disposition(vs)
        self.assertEqual((d, ref), ("intentional-design", "SPEC-007"))

    def test_no_verdicts_is_needs_review_not_drop(self):
        """Deliberate divergence from the retired JS, which dropped the finding.

        Zero verdicts means every skeptic call failed — that is no information,
        not a unanimous refutation, and the skill's own rule forbids silently
        deleting a finding that was never actually refuted."""
        d, _, v = audit_engine.disposition([])
        self.assertEqual(d, "needs-review")
        self.assertEqual(v["total"], 0)
        self.assertEqual(v["upheld"], 0)


class DiscoverTest(unittest.TestCase):
    def test_stops_after_k_empty_dry_rounds(self):
        calls = []

        def ask(prompt, schema=None):
            calls.append(prompt)
            return {"findings": []}

        found = audit_engine.discover(ask, "ctx", run=SEQUENTIAL)
        self.assertEqual(found, [])
        # Literals, not the constants under test: asserting against
        # audit_engine.K_EMPTY would adapt to a mutation of it and prove nothing.
        self.assertEqual(audit_engine.K_EMPTY, 2)
        self.assertEqual(len(audit_engine.CATEGORIES), 6)
        self.assertEqual(len(calls), 12)

    def test_dry_counter_resets_on_a_fresh_finding(self):
        rounds = {"n": 0}

        def ask(prompt, schema=None):
            if "Category: auth" not in prompt:
                return {"findings": []}
            rounds["n"] += 1
            if rounds["n"] == 2:
                return {"findings": [finding(file="new.js")]}
            return {"findings": []}

        found = audit_engine.discover(ask, "ctx", run=SEQUENTIAL)
        self.assertEqual(len(found), 1)

    def test_a_fresh_finding_buys_another_k_empty_rounds(self):
        """Pins the `dry = 0` reset: without it the loop stops a round early."""
        auth_calls = {"n": 0}
        rounds = []

        def ask(prompt, schema=None):
            if "Category: auth" not in prompt:
                return {"findings": []}
            auth_calls["n"] += 1
            if auth_calls["n"] == 2:
                return {"findings": [finding(file="new.js")]}
            return {"findings": []}

        audit_engine.discover(ask, "ctx", run=SEQUENTIAL,
                              on_round=lambda r, fresh, total, dry: rounds.append(r))
        # dry / fresh / dry / dry -> 4 rounds. Without the reset: dry / fresh / dry -> 3.
        self.assertEqual(rounds, [1, 2, 3, 4])

    def test_stops_at_max_rounds(self):
        seq = {"n": 0}

        def ask(prompt, schema=None):
            seq["n"] += 1
            return {"findings": [finding(file=f"f{seq['n']}.js", line=seq["n"] * 10)]}

        found = audit_engine.discover(ask, "ctx", run=SEQUENTIAL)
        self.assertLessEqual(len(found), audit_engine.MAX_ROUNDS * len(audit_engine.CATEGORIES))
        self.assertGreater(len(found), 0)

    def test_duplicates_across_rounds_are_dropped(self):
        def ask(prompt, schema=None):
            return {"findings": [finding(file="same.js", line=10)]}

        found = audit_engine.discover(ask, "ctx", run=SEQUENTIAL)
        self.assertEqual(len(found), 1)

    def test_failed_finder_calls_are_skipped_not_fatal(self):
        def ask(prompt, schema=None):
            if "Category: auth" in prompt:
                return None
            return {"findings": []}

        self.assertEqual(audit_engine.discover(ask, "ctx", run=SEQUENTIAL), [])

    def test_max_findings_caps_discovery(self):
        seq = {"n": 0}

        def ask(prompt, schema=None):
            seq["n"] += 1
            return {"findings": [finding(file=f"f{seq['n']}.js", line=seq["n"] * 10)]}

        found = audit_engine.discover(ask, "ctx", run=SEQUENTIAL, max_findings=3)
        self.assertLessEqual(len(found), 3)


class AuditTest(unittest.TestCase):
    def test_dropped_findings_never_leave_the_engine(self):
        def ask(prompt, schema=None):
            if prompt.startswith("Read"):
                return "context"
            if "Category:" in prompt:
                return {"findings": [finding()]} if "auth" in prompt else {"findings": []}
            return {"lens": "exploitability", "verdict": "refuted", "reason": "no path"}

        self.assertEqual(audit_engine.audit(ask, SEQUENTIAL), [])

    def test_survivor_carries_disposition_and_verification(self):
        def ask(prompt, schema=None):
            if prompt.startswith("Read"):
                return "context"
            if "Category:" in prompt:
                return {"findings": [finding()]} if "auth" in prompt else {"findings": []}
            lens = next(l for l in audit_engine.SKEPTICS if f"Lens: {l}" in prompt)
            return {"lens": lens, "verdict": "upheld", "reason": "reachable"}

        out = audit_engine.audit(ask, SEQUENTIAL)
        self.assertEqual(len(out), 1)
        self.assertEqual(out[0]["disposition"], "confirmed")
        self.assertEqual(out[0]["verification"]["upheld"], 3)
        self.assertEqual(out[0]["file"], "a.js")


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run to verify they fail**

Run: `cd skills/freya-codebase-security-scan/scripts && python3 -m unittest test_audit_engine -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'audit_engine'`

- [ ] **Step 3: Implement**

Create `skills/freya-codebase-security-scan/scripts/audit_engine.py`:

```python
#!/usr/bin/env python3
"""The audit engine: exhaustive discovery, then adversarial verification.

Ported from workflows/codebase-security-audit.js, which ran on Claude's
Workflow tool. All control flow is here; the only injected pieces are `ask`
(one LLM call) and `run` (how to execute a list of thunks). That is what makes
the engine testable offline and agent-agnostic.

Contract, unchanged from the JS: this returns deduped, verified findings. It
does NOT write the report, assign SEC-### IDs, or re-evaluate previous
findings — the skill's main loop does all of that.
"""

from __future__ import annotations

from audit_io import CATEGORIES, FINDER_SCHEMA, SKEPTICS, VERDICT_SCHEMA

K_EMPTY = 2      # consecutive dry rounds that stop discovery
MAX_ROUNDS = 5   # budget guard

CONTEXT_PROMPT = (
    "Read /knowledge-base/reference and /knowledge-base/specs (if present). Summarize: "
    "architecture, auth model, trust boundaries, untrusted entry points, and an explicit "
    "list of SPEC'D-INTENTIONAL behaviors that must NOT be reported as vulnerabilities. "
    "Return prose."
)


def dedup_key(finding):
    """Same file + same five-line window + same category collapse to one finding."""
    return f"{finding['file']}::{int(finding['line']) // 5}::{finding['category']}"


def disposition(verdicts):
    """Return (disposition, spec_reference, verification) for one finding.

    A spec-intentional refutation outranks the majority: if the behaviour is
    specified, it is a design decision rather than a vulnerability.

    Divergence from the retired JS: with zero verdicts (every skeptic call
    failed) the JS reached `upheld == 0` and dropped the finding. That is a
    silent delete on error. The skill's rule is that only a *unanimous
    refutation* drops a finding, so no-information now yields needs-review.
    """
    verdicts = [v for v in verdicts if v]
    upheld = sum(1 for v in verdicts if v.get("verdict") == "upheld")
    total = len(verdicts)
    verification = {"upheld": upheld, "total": total, "lenses": SKEPTICS}

    spec_refute = next(
        (v for v in verdicts
         if v.get("lens") == "spec-intentional" and v.get("verdict") == "refuted"),
        None,
    )
    if spec_refute:
        return "intentional-design", spec_refute.get("specReference"), verification
    if total == 0:
        return "needs-review", None, verification
    if upheld * 2 > total:
        return "confirmed", None, verification
    if upheld == 0:
        return "drop", None, verification
    return "needs-review", None, verification


def discover(ask, context, run, *, max_findings=None, on_round=None):
    """Loop the six category finders until K_EMPTY dry rounds or MAX_ROUNDS."""
    seen = set()
    found = []
    dry = 0
    rounds = 0

    while dry < K_EMPTY and rounds < MAX_ROUNDS:
        rounds += 1
        known = sorted(seen)

        def finder(category):
            def thunk():
                return ask(
                    f"Category: {category}. Context: {context}. "
                    f"Already found (skip these dedup keys): {known}. "
                    f"Exhaustively scan the codebase for NEW {category} vulnerabilities "
                    f"on uncovered surface. Return {{ findings: [...] }} matching the "
                    f"schema; empty array if nothing new.",
                    schema=FINDER_SCHEMA,
                )
            return thunk

        results = run([finder(c) for c in CATEGORIES])

        fresh = []
        for result in results:
            if not result:
                continue
            for item in result.get("findings", []):
                if dedup_key(item) not in seen:
                    seen.add(dedup_key(item))
                    fresh.append(item)

        if not fresh:
            dry += 1
            if on_round:
                on_round(rounds, 0, len(found), dry)
            continue

        dry = 0
        found.extend(fresh)
        if on_round:
            on_round(rounds, len(fresh), len(found), dry)
        if max_findings is not None and len(found) >= max_findings:
            return found[:max_findings]

    return found


def verify(finding, ask, context, run):
    """Run every skeptic lens against one finding and settle its disposition."""
    def skeptic(lens):
        def thunk():
            return ask(
                f"Finding: {finding}. Spec-intentional context: {context}. Lens: {lens}. "
                f"Your job is to REFUTE this finding, not confirm it. Return verdict "
                f'"refuted" or "upheld" with a reason (and specReference if '
                f"spec-intentional).",
                schema=VERDICT_SCHEMA,
            )
        return thunk

    verdicts = run([skeptic(lens) for lens in SKEPTICS])
    disp, spec_reference, verification = disposition(verdicts)
    return {**finding, "disposition": disp, "specReference": spec_reference,
            "verification": verification}


def audit(ask, run, *, max_findings=None, on_round=None):
    """Full audit. Returns survivors only — dropped findings never leave here."""
    context = ask(CONTEXT_PROMPT)
    findings = discover(ask, context, run, max_findings=max_findings, on_round=on_round)
    verified = [verify(f, ask, context, run) for f in findings]
    return [v for v in verified if v["disposition"] != "drop"]
```

- [ ] **Step 4: Run to verify they pass**

Run: `cd skills/freya-codebase-security-scan/scripts && python3 -m unittest test_audit_engine -v`
Expected: PASS — 22 tests, `OK`

- [ ] **Step 5: Mutation-check the ported logic**

Each of these is a value the port must not get wrong. All six were verified on
2026-07-31 to kill their named test.

> **Delete `__pycache__` between mutations, or run `python3 -B`.** These edits land
> within the same mtime tick, so Python reuses stale bytecode and you see the
> *previous* mutation's result. This caught out the plan's own validation run twice —
> two mutations looked killed when they had never been loaded.

1. `dedup_key`: change `// 5` to `// 10`.
   Expected: FAIL on `test_next_window_is_distinct` and `test_matches_the_retired_workflow_format`. **Restore.**
2. `disposition`: change `upheld * 2 > total` to `upheld * 2 >= total`.
   Expected: FAIL on `test_one_of_two_upheld_is_needs_review`. **Restore.**
   (Only a 1-of-2 split separates `>` from `>=` — a 1-of-3 case does not, which is
   exactly why that test exists.)
3. `disposition`: delete the `total == 0` guard.
   Expected: FAIL on `test_no_verdicts_is_needs_review_not_drop`. **Restore.**
4. `disposition`: move the `spec_refute` check *after* the majority check.
   Expected: FAIL on `test_spec_refute_outranks_a_majority_upheld`. **Restore.**
   (Only that one. `test_spec_reference_is_carried_out` uses a 1-of-2 split where
   the majority condition is false either way, so reordering does not reach it.
   Deleting the branch outright would fail both — a different mutation.)
5. `discover`: delete the `dry = 0` reset.
   Expected: FAIL on `test_a_fresh_finding_buys_another_k_empty_rounds`. **Restore.**
   (Not a findings-count test — both paths yield one finding; only the round count
   distinguishes them.)
6. `K_EMPTY = 3`.
   Expected: FAIL on `test_stops_after_k_empty_dry_rounds` and
   `test_a_fresh_finding_buys_another_k_empty_rounds`. **Restore.**

Re-run after restoring all six: PASS, 22 tests.

- [ ] **Step 6: Commit**

```bash
git add skills/freya-codebase-security-scan/scripts/audit_engine.py \
        skills/freya-codebase-security-scan/scripts/test_audit_engine.py
git commit -F - <<'EOF'
feat(audit): port the audit engine from the Workflow script to Python

Loop-until-dry discovery, cross-round dedup, diverse-lens skeptics and the
disposition ladder, relocated from workflows/codebase-security-audit.js. The
constants, dedup key and vote arithmetic are preserved exactly; six mutation
checks pin them.

`ask` and `run` are injected, so the engine is agent-agnostic and every test
runs offline for free — something the Workflow version could never do.

One deliberate divergence: when every skeptic call fails, the JS reached
`upheld == 0` and dropped the finding as a false positive. Zero verdicts is no
information, not a unanimous refutation, and the skill's own rule forbids
silently deleting a finding that was never refuted. That case is now
needs-review with verification.total = 0.

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>
EOF
```

---

### Task 4: The driver — CLI, worker pool, budget guard, degradation

**Files:**
- Create: `skills/freya-codebase-security-scan/scripts/audit.py`
- Test: `skills/freya-codebase-security-scan/scripts/test_audit.py`
- Modify: `bin/commands.json`

**Interfaces produced:**
- `Budget` — counts calls, sums cost where the adapter reports it, raises `BudgetExhausted` past `max_calls`
- `make_ask(adapter_name, budget, *, model=None, retries=1, timeout=600)` → an `ask` for the engine
- `make_run(concurrency)` → a `run` backed by `concurrent.futures.ThreadPoolExecutor`
- `estimate(max_findings)` → worst-case call count
- `main(argv=None) -> int` — `0` ok, `1` no agent CLI / nothing to do, `2` failure

CLI: `freya security audit [--project PATH] [--agent claude|copilot] [--model M] [--max-calls N] [--max-findings N] [--concurrency N] [--dry-run] [--yes] [--format json|summary]`

- [ ] **Step 1: Write the failing tests**

Create `skills/freya-codebase-security-scan/scripts/test_audit.py`:

```python
#!/usr/bin/env python3
"""Unit tests for the audit driver. No agent is ever invoked."""

import contextlib
import io
import json
import unittest
from unittest import mock

import audit


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


class EstimateTest(unittest.TestCase):
    def test_worst_case_counts_context_finders_and_skeptics(self):
        # 1 context + MAX_ROUNDS*6 finders + 3 skeptics per finding
        self.assertEqual(audit.estimate(max_findings=10), 1 + 5 * 6 + 3 * 10)


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


class MainTest(unittest.TestCase):
    def test_no_agent_cli_degrades_with_guidance(self):
        with mock.patch("audit_adapter.detect", return_value=None):
            code, _, err = run_main(["--yes"])
        self.assertEqual(code, 1)
        self.assertIn("scan", err)

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

    def test_confirmation_is_required_without_yes(self):
        with mock.patch("audit_adapter.detect", return_value="copilot"), \
             mock.patch("builtins.input", return_value="n"), \
             mock.patch("subprocess.run") as run:
            code, _, _ = run_main([])
        self.assertEqual(code, 1)
        run.assert_not_called()

    def test_findings_are_emitted_as_json(self):
        survivor = {"file": "a.js", "disposition": "confirmed"}
        with mock.patch("audit_adapter.detect", return_value="copilot"), \
             mock.patch("audit_engine.audit", return_value=[survivor]):
            code, out, _ = run_main(["--yes", "--format", "json"])
        self.assertEqual(code, 0)
        self.assertEqual(json.loads(out), [survivor])


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run to verify they fail**

Run: `cd skills/freya-codebase-security-scan/scripts && python3 -m unittest test_audit -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'audit'`

- [ ] **Step 3: Implement**

Create `skills/freya-codebase-security-scan/scripts/audit.py` (mode 644):

```python
#!/usr/bin/env python3
"""`freya security audit` — exhaustive, adversarially-verified security audit.

Owns the control flow the Claude Workflow tool used to own, and calls whatever
agent CLI is installed as a headless read-only worker.

COST. The spike measured $0.396 for one finder worker on a trivial fixture,
and the worst case here is 1 + MAX_ROUNDS*6 + 3*findings calls. So the caps are
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

import audit_adapter
import audit_engine
import audit_io

DEFAULT_MAX_CALLS = 80
DEFAULT_MAX_FINDINGS = 40
DEFAULT_CONCURRENCY = 4
DEFAULT_TIMEOUT = 600


class BudgetExhausted(Exception):
    """The run hit its call ceiling."""


class Budget:
    """Counts agent calls, and spend where the adapter reports it."""

    def __init__(self, max_calls):
        self.max_calls = max_calls
        self.calls = 0
        self.usd = None

    def spend(self, cost):
        if self.calls >= self.max_calls:
            raise BudgetExhausted(f"call budget exhausted ({self.max_calls})")
        self.calls += 1
        if cost is not None:
            self.usd = (self.usd or 0.0) + cost


def estimate(max_findings):
    """Worst-case agent calls: context + every finder round + skeptics per finding."""
    finders = audit_engine.MAX_ROUNDS * len(audit_io.CATEGORIES)
    return 1 + finders + len(audit_io.SKEPTICS) * max_findings


def make_ask(adapter_name, budget, *, model=None, retries=1, timeout=DEFAULT_TIMEOUT,
             cwd=None):
    """Build the `ask` callable the engine uses for one LLM task."""
    adapter = audit_adapter.ADAPTERS[adapter_name]

    def ask(prompt, schema=None):
        contract = prompt
        if schema is not None:
            contract += ("\n\nReturn ONLY a single JSON object matching this schema, "
                         "with no commentary:\n" + json.dumps(schema))
        for attempt in range(retries + 1):
            budget.spend(None)  # reserve the slot before the call
            try:
                completed = subprocess.run(
                    adapter.build_argv(contract, model=model),
                    capture_output=True, text=True, timeout=timeout, cwd=cwd,
                )
            except (OSError, subprocess.TimeoutExpired):
                continue
            if completed.returncode != 0:
                continue
            payload = adapter.parse_stdout(completed.stdout)
            cost = adapter.cost(completed.stdout)
            if cost is not None:
                budget.usd = (budget.usd or 0.0) + cost
            if schema is None:
                return payload
            obj = audit_io.extract_json(payload)
            if obj is None:
                continue
            try:
                audit_io.validate(obj, schema)
            except audit_io.SchemaError:
                continue
            return obj
        return None

    return ask


def make_run(concurrency):
    """Build the `run` callable: a bounded pool over the engine's thunks."""
    def run(thunks):
        if concurrency <= 1:
            return [t() for t in thunks]
        with concurrent.futures.ThreadPoolExecutor(max_workers=concurrency) as pool:
            return list(pool.map(lambda t: t(), thunks))
    return run


def main(argv=None):
    parser = argparse.ArgumentParser(
        prog="freya security audit",
        description="Exhaustive security discovery plus adversarial verification.",
    )
    parser.add_argument("mode", nargs="?", default="audit", choices=["audit"])
    parser.add_argument("--project", default=".", help="project directory to audit")
    # No argparse `choices` here: we want a clean message and return code 2
    # rather than argparse's SystemExit, so main() always returns.
    parser.add_argument("--agent", help="agent CLI to drive (default: autodetect)")
    parser.add_argument("--model", help="model for workers; a cheaper one cuts cost a lot")
    parser.add_argument("--max-calls", type=int, default=DEFAULT_MAX_CALLS)
    parser.add_argument("--max-findings", type=int, default=DEFAULT_MAX_FINDINGS)
    parser.add_argument("--concurrency", type=int, default=DEFAULT_CONCURRENCY)
    parser.add_argument("--timeout", type=int, default=DEFAULT_TIMEOUT)
    parser.add_argument("--dry-run", action="store_true",
                        help="print the plan and cost ceiling, call nothing")
    parser.add_argument("--yes", action="store_true", help="skip the confirmation prompt")
    parser.add_argument("--format", choices=["json", "summary"], default="json")
    args = parser.parse_args(argv)

    if args.agent and args.agent not in audit_adapter.ADAPTERS:
        print(f"unknown agent: {args.agent}", file=sys.stderr)
        return 2

    agent_name = args.agent or audit_adapter.detect()
    if agent_name is None:
        print(
            "audit needs an agent CLI on PATH (claude or copilot) and none was found.\n"
            "Use `freya-codebase-security-scan scan` or `update` instead — both are "
            "fully portable and are what wrap-up runs.",
            file=sys.stderr,
        )
        return 1

    # Everything human-facing goes to stderr: stdout carries only the JSON
    # payload, because the skill's main loop parses it.
    worst = estimate(args.max_findings)
    capped = min(worst, args.max_calls)
    say = lambda line: print(line, file=sys.stderr)
    say(f"agent:        {agent_name}")
    say(f"project:      {os.path.abspath(args.project)}")
    say(f"worst case:   {worst} agent calls "
        f"(1 context + {audit_engine.MAX_ROUNDS}x{len(audit_io.CATEGORIES)} finders "
        f"+ {len(audit_io.SKEPTICS)} skeptics x {args.max_findings} findings)")
    say(f"call ceiling: {capped} — the run stops here even if unfinished")
    say("This spends real money. One worker measured ~$0.40 on a trivial fixture.")

    if args.dry_run:
        return 0

    if not args.yes:
        try:
            if input("Proceed? [y/N] ").strip().lower() not in ("y", "yes"):
                print("aborted.", file=sys.stderr)
                return 1
        except EOFError:
            print("aborted (no tty; pass --yes to run unattended).", file=sys.stderr)
            return 1

    budget = Budget(args.max_calls)
    ask = make_ask(agent_name, budget, model=args.model, timeout=args.timeout,
                   cwd=args.project)

    def on_round(rounds, fresh, total, dry):
        note = f"dry ({dry}/{audit_engine.K_EMPTY})" if not fresh else f"+{fresh} new"
        print(f"round {rounds}: {note} — {total} findings, {budget.calls} calls",
              file=sys.stderr)

    try:
        survivors = audit_engine.audit(
            ask, make_run(args.concurrency),
            max_findings=args.max_findings, on_round=on_round,
        )
    except BudgetExhausted as exc:
        print(f"\n{exc} — returning nothing rather than a partial audit you might "
              f"mistake for a complete one.", file=sys.stderr)
        return 2

    spend = "" if budget.usd is None else f", ${budget.usd:.2f}"
    print(f"done: {len(survivors)} findings after verification "
          f"({budget.calls} calls{spend})", file=sys.stderr)

    if args.format == "json":
        print(json.dumps(survivors, indent=2))
    else:
        for item in survivors:
            print(f"[{item['disposition']}] {item.get('severity','?')} "
                  f"{item.get('file','?')}:{item.get('line','?')} — {item.get('title','')}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
```

- [ ] **Step 4: Run to verify they pass**

Run: `cd skills/freya-codebase-security-scan/scripts && python3 -m unittest test_audit -v`
Expected: PASS — 17 tests, `OK`

- [ ] **Step 5: Register the command**

Add to `bin/commands.json`, keeping keys sorted as the file already is:

```json
  "security": "freya-codebase-security-scan/scripts/audit.py",
```

Verify:
```bash
cd bin && python3 -m unittest test_freya_cli -q
cd .. && ./bin/freya security --help
```
Expected: the launcher suite passes (its `test_every_cli_script_is_registered` covers the new script), and `--help` prints the audit usage.

- [ ] **Step 6: Prove it degrades and never spends by accident**

```bash
./bin/freya security audit --dry-run
```
Expected: prints agent, project, worst case, call ceiling, and the cost warning; exits 0; makes no agent call.

```bash
PATH=/usr/bin:/bin ./bin/freya security audit --yes 2>&1 | tail -3; echo "exit=$?"
```
Expected: the no-agent-CLI message pointing at `scan`/`update`, exit 1.

- [ ] **Step 7: Mutation-check the budget guard**

1. In `Budget.spend`, drop the `if self.calls >= self.max_calls` raise.
   Expected: FAIL on `test_raises_past_the_cap`. **Restore.**
2. In `make_ask`, move `budget.spend(None)` to *after* the `subprocess.run` call.
   Expected: FAIL on `test_every_call_is_counted` (a failed call would go uncounted, so the ceiling could be overrun by retries). **Restore.**

Re-run: PASS, 17 tests.

- [ ] **Step 8: Commit**

```bash
git add skills/freya-codebase-security-scan/scripts/audit.py \
        skills/freya-codebase-security-scan/scripts/test_audit.py bin/commands.json
git commit -F - <<'EOF'
feat(audit): the driver — CLI, worker pool, budget guard, degradation

Wires the engine to an agent: a bounded thread pool supplies `run`, and `ask`
does prompt-contract -> extract -> validate -> bounded retry, which is what the
Workflow tool's `schema:` used to provide.

Cost is the real risk, so the guard is not advisory. Caps are on by default,
the worst-case call count and the money warning print before anything is spent,
a confirmation is required without --yes, and every attempt is counted *before*
the subprocess runs so retries cannot overrun the ceiling. Exhausting the
budget returns nothing rather than a partial audit that could be mistaken for a
complete one.

With no agent CLI installed it exits 1 pointing at scan/update, which are fully
portable and are what wrap-up runs.

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>
EOF
```

---

### Task 5: Retire the Workflow tool

Everything Phase 2 and Phase 4 deferred comes out together. That simultaneity is the completeness proof: if any piece is left, the checker fails.

**Files:**
- Delete: `workflows/codebase-security-audit.js`
- Modify: `skills/freya-codebase-security-scan/SKILL.md`, `bin/check_skill_conformance.py`, `bin/test_check_skill_conformance.py`, `CONTRIBUTING.md`

- [ ] **Step 1: Rewrite the `audit` section of the skill**

Replace the **Engine** paragraph and **Phase 1** of `### freya-codebase-security-scan audit (Deep Audit)`:

```markdown
**Engine:** `freya security audit` — a Python driver bundled with this skill. It owns
the control flow (loop-until-dry, dedup, majority voting) and calls whichever agent CLI
is installed (`claude` or `copilot`) as a headless, read-only worker.

**Critical division of labor — the driver returns DATA, the skill writes the REPORT:**
The driver does NOT write the report, assign `SEC-###` IDs, or re-evaluate previous
findings. Its workers run with an explicit read-only tool allowlist and return a JSON
array of deduped, adversarially-verified findings. The skill's **main loop** then does
everything that keeps the report format stable.

**Workflow:**

**Phase 1: Run the audit driver**

```bash
freya security audit --project .
```

It prints the worst-case call count and a cost warning, then asks for confirmation
(`--yes` to skip, `--dry-run` to see the plan and spend nothing). It executes: context →
exhaustive discovery (loop-until-dry over the 6 categories) → dedup by
`file + line-window + category` → per-finding adversarial verification → unanimous-refute
drop, and prints a JSON array of survivors on stdout. Each carries `disposition`
(`confirmed` / `mitigated` / `intentional-design` / `needs-review`), optional
`specReference`, and `verification` (`{upheld, total, lenses}`). No IDs, no file writes.

**Cost.** One worker measured ~$0.40 on a trivial fixture, and a full audit is dozens of
calls. `--max-calls` (default 80) and `--max-findings` (default 40) bound it; `--model`
points workers at a cheaper model. If the call ceiling is reached the driver returns
nothing rather than a partial audit you might mistake for a complete one.

**If no agent CLI is installed** the driver exits 1 and points you at `scan` / `update`,
which are fully portable. Nothing in the core workflow depends on `audit`.
```

Leave Phases 2–4 (re-evaluate, IDs and format, tracking) exactly as they are — they are the main-loop half of the contract and they are unchanged.

Then update the mode table entry at the top of the file:

```
-| `audit` | Exhaustive discovery + adversarial verification (Workflow-powered). On-demand / pre-release. |
+| `audit` | Exhaustive discovery + adversarial verification (`freya security audit`). On-demand / pre-release. |
```

And the remaining "Workflow tool" mentions:

```
-Exhaustive discovery plus a stronger adversarial verification pass, powered by the **Workflow tool**. On-demand / periodic...
+Exhaustive discovery plus a stronger adversarial verification pass, run by the `freya security audit` driver. On-demand / periodic...

-**Runs on every `scan` and `update`, in the main loop. This is NOT the Workflow tool** — keep it synchronous...
+**Runs on every `scan` and `update`, in the main loop. This is NOT the `audit` driver** — keep it synchronous...
```

Read each in place; there are four "Workflow tool" mentions and two `${CLAUDE_PLUGIN_ROOT}` lines, and **all six must be gone** when you finish.

- [ ] **Step 2: Delete the workflow**

```bash
git rm workflows/codebase-security-audit.js
```

If `workflows/` is now empty, remove it too.

- [ ] **Step 3: Retire the checker's exemptions**

In `bin/check_skill_conformance.py`:

- Delete `AUDIT_WORKFLOW_MARKER` and the `if AUDIT_WORKFLOW_MARKER not in line:` guard in `check_file`, so R1 applies everywhere with no exception.
- Add `Workflow` to the tool-name alternation in `AGENT_TOOL_NAMES`, so `Workflow tool` is flagged like every other Claude-only tool name.

In `bin/test_check_skill_conformance.py`:

- Delete `test_audit_workflow_line_is_exempt` and `test_workflow_tool_is_exempt_until_phase_4b` — both assert an exemption that no longer exists.
- Add a replacement that pins the new behaviour:

```python
    def test_workflow_tool_is_flagged_now_that_audit_is_ported(self):
        """Phase 4b retired the Workflow engine; the exemption went with it."""
        with tempfile.TemporaryDirectory() as tmp:
            root = build_root(tmp, skill_md="Run the Workflow tool with scriptPath.\n")
            self.assertIn("R4", rules_hit(root))

    def test_plugin_root_has_no_exemption_left(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = build_root(
                tmp,
                skill_md='`scriptPath: "${CLAUDE_PLUGIN_ROOT}/workflows/codebase-security-audit.js"`\n',
            )
            self.assertIn("R1", rules_hit(root))
```

- [ ] **Step 4: Drop the CONTRIBUTING bullet**

Delete the bullet beginning "**The audit Workflow** is invoked via the Workflow tool's `scriptPath`…" — it documents a file that no longer exists. Leave the other conventions untouched.

- [ ] **Step 5: Verify the retirement is complete**

```bash
python3 bin/check_skill_conformance.py; echo "exit=$?"
```
Expected: `skill layer is conformant.`, `exit=0`. **This is the proof**: R1 and R4 now have no exemptions, so a single leftover reference anywhere would fail.

```bash
grep -rn 'Workflow tool\|codebase-security-audit\|CLAUDE_PLUGIN_ROOT' skills/ CONTRIBUTING.md README.md docs/*.md
ls workflows/ 2>&1
```
Expected: no output from the grep; `workflows/` gone.

```bash
for t in bin/test_*.py skills/*/scripts/test_*.py; do
  d=$(dirname "$t"); m=$(basename "$t" .py)
  ( cd "$d" && python3 -m unittest "$m" -q ) >/dev/null 2>&1 && echo "ok    $t" || echo "FAIL  $t"
done
```
Expected: `ok` for all 22 suites (18 previous + the four new audit suites).

```bash
./bin/freya doctor; echo "exit=$?"
```
Expected: exit 0, manifest now reporting 16 commands.

- [ ] **Step 6: Commit**

```bash
git add -A
git commit -F - <<'EOF'
refactor(audit): retire the Workflow engine

Deletes workflows/codebase-security-audit.js and rewires the skill to
`freya security audit`. Everything the earlier phases deferred comes out at
once: the four Workflow-tool references, the two ${CLAUDE_PLUGIN_ROOT} lines,
the checker's AUDIT_WORKFLOW_MARKER exemption and its AGENT_TOOL_NAMES
omission, and the CONTRIBUTING bullet.

That simultaneity is the completeness proof — R1 and R4 now have no exemptions
at all, so a single leftover reference anywhere would fail the gate. The two
tests that asserted the exemptions are replaced by two that assert their
absence.

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>
EOF
```

---

## Definition of done

- `python3 bin/check_skill_conformance.py` exits 0 with **no** rule exemptions remaining.
- `grep -rn 'Workflow tool\|codebase-security-audit'` over `skills/`, `CONTRIBUTING.md`, `README.md` and top-level `docs/*.md` returns nothing.
- The only `${CLAUDE_PLUGIN_ROOT}` left anywhere is `CONTRIBUTING.md`'s launcher bullet, which cites it as the anti-pattern *not* to write. That one stays.
- `workflows/` is gone.
- All 22 test suites pass; **no test invokes a real agent CLI**.
- `./bin/freya security audit --dry-run` prints a plan and spends nothing.
- With no agent CLI on PATH, the driver exits 1 pointing at `scan`/`update`.
- The engine's constants, dedup key and vote arithmetic match the retired JS, pinned by six mutation checks — with the single documented divergence for zero verdicts.
- `.claude-plugin/` unchanged from `main`.
- **Nothing pushed.**

## Carried forward

- **Phase 5:** `freya update` + notify-only check + `freya init`. Store relocation orphans install links, which `doctor` can see but does not report.
- **Phase 6:** the whole track's end-to-end validation, now including:
  - **A real `audit` run on both agents** — this phase's tests are all offline by design, so nothing here proves an actual worker returns schema-valid findings. Budget for it: one small fixture repo, `--max-findings 3`, both adapters.
  - **Re-confirming the read-only boundary live.** The spike proved it on Copilot 1.0.75 and this phase encodes that finding as a hard guard, but the guard is only as good as the last time someone checked the CLI's behaviour. Re-run the bypass probe against whatever version ships then.
  - Windows (`install.ps1` has never run), and the unmeasured `~7×` figure.
- **`mitigated` is unreachable.** The skill's disposition table maps `mitigated`→MITIGATED, but neither the JS nor this port ever emits it — `disposition()` only returns `confirmed`, `intentional-design`, `needs-review` or `drop`. Pre-existing, faithfully preserved, and worth resolving on its own: either have a lens emit it or drop it from the table.
