# SKILL.md De-Claude-ify Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Remove every Claude-only construct from the shipped skill layer (`skills/**/*.md`) so the same SKILL.md set works on Claude Code and GitHub Copilot, and add a permanent regression gate that keeps them out.

**Architecture:** Phase 1 already shipped the `freya` launcher (`bin/freya`, `bin/freya_cli.py`, `bin/commands.json`) — every script a SKILL.md invokes is already registered as a `freya` command. This phase is therefore a *substitution* job over markdown, not a redesign. It is driven test-first by a new conformance checker (`bin/check_skill_conformance.py`) that starts red against the real tree and is driven to green by the rewrite tasks. Scripts under `skills/*/scripts/` are not touched.

**Tech Stack:** Python 3 stdlib only (`argparse`, `re`, `json`, `pathlib`, `unittest`). No new dependencies.

## Context

This is **Phase 2 of 6** in the portability track ([`docs/design/portability/01-design.md`](../../../design/portability/01-design.md) §11). Branch `feat/polyglot-portability` stays open through all six phases.

Verified counts against the tree on 2026-07-28:

| Surface | Sites | This phase? |
|---|---|---|
| `python "${CLAUDE_PLUGIN_ROOT}/…"` script invocations in SKILL.md | **80** | **yes** — Task 2 |
| `${CLAUDE_PLUGIN_ROOT}` in the audit Workflow refs (`codebase-security-scan` L442, L450) | 3 | **no** — Phase 4b |
| `/freya-devkit:<skill>` in SKILL.md | **172** | **yes** — Task 3 |
| `/freya-devkit:<skill>` in `skills/*/references/*.md` | **5** | **yes** — Task 3 |
| `/loop` (Claude Code slash command) | **7** | **yes** — Task 4 |
| "plan mode" phrasing | **5** | **yes** — Task 4 |
| Claude tool names — `askUserQuestion` 1, `EnterPlanMode` 1, `WebSearch` 4, `Write tool` 1 | **7** | **yes** — Task 4 (2 of them die with `compatibility:`) |
| `compatibility:` frontmatter | **2** skills | **yes** — Task 4 |
| "Workflow tool" phrasing | 4 | **no** — Phase 4b |
| LLM fan-out orchestration prose (3 flows) | 3 | **no** — Phase 4 |
| `/freya-devkit:` in user-facing docs (README, `docs/skill-reference.md`, …) | 47 | **no** — Phase 3 |
| `/freya-devkit:` + `${CLAUDE_PLUGIN_ROOT}` in `docs/design`, `docs/superpowers/plans`, `docs/explanations`, `docs/migrations` | 254 + 135 | **never** — historical record |

`80 + 3 = 83` and `172 + 5 = 177`, reconciling with design §1.

**Design decision applied (user-confirmed 2026-07-28, amending §1 of this plan's parent spec):** a skill cross-reference becomes the **prefixed name** `freya-<skill>`, per Decision 3. Known consequence, carried to Phase 6 validation: under the Claude *marketplace-plugin* install the skill is registered as `freya-devkit:code-graph`, so `freya-code-graph` is a name the agent maps rather than matches. This is a soft resolution from the available-skills list, not a hard failure. Phase 3's installer path makes the name exact.

## Global Constraints

- **Python 3 stdlib only.** No third-party imports in any new script.
- **Shebang `#!/usr/bin/env python3`** on any new executable script. **Never invoke bare `python`** anywhere — in code, in docs, or in a command you run.
- **Tests are colocated and use `unittest`**, matching `bin/test_freya_cli.py` and every `skills/*/scripts/test_*.py`. Run with `python3 -m unittest`.
- **Never write `${CLAUDE_PLUGIN_ROOT}`** into any file under `skills/`. The only two sanctioned lines are the audit-Workflow references in `skills/codebase-security-scan/SKILL.md` (L442, L450), which Phase 4b retires.
- **Two names, one character apart — never mix them:**
  - `freya <command>` (**space**) is the CLI launcher. Only valid for commands in `bin/commands.json` plus the builtins `install`, `update`, `doctor`, `init`, `help`.
  - `freya-<skill>` (**hyphen**) is a skill name, never a shell command.
  - **Amended after the final review (project owner's call):** a `freya-<skill>` line *may* appear inside a fenced block when the block lists skill invocations — `freya-wrap-up --no-security` means "invoke this skill with these arguments", exactly as `/freya-devkit:wrap-up --no-security` did before the port. ~50 such sites are deliberate. What remains forbidden is the genuine mix-up: a **hyphen** name carrying flags that belong to the **CLI** (the final review found exactly one, `spec-manager/SKILL.md:166-167`, since fixed).
- **Do not modify anything under `skills/*/scripts/`.** This phase is markdown-only, apart from the new `bin/` checker and its test — plus one named exception found during Task 3: `skills/status/scripts/collect_status.py:182` writes `/freya-devkit:status` into every project's generated `knowledge-base/BACKLOG.md`. That is shipped user-facing output, not a comment, so leaving it would contradict the phase's own completion claim. It is fixed here; its covering test (`test_collect_status.py:153`) asserts on `"do not edit"` and is unaffected. No other script under `skills/*/scripts/` may be touched.
- **Implementers do not modify anything under `docs/`.** User-facing docs are Phase 3; `docs/design` and `docs/explanations` are a historical record and are never rewritten. (`CONTRIBUTING.md` is the single exception, in Task 5.) This constraint scopes the *rewrite* — it does not freeze **this plan file**, which the controller amends whenever execution proves a step wrong. Four such amendments happened during Phase 2 and each is its own commit; a plan that still described work that did not happen would be worse than one that was edited.
- **Do not rewrite the three LLM fan-out flows** (`codebase-security-scan`, `docs-manager`, `spec-manager scan`) — that is Phase 4. Leave phrasing like "using parallel subagents" alone.
- **Preserve command flags verbatim.** The rewrite replaces only the `python "${CLAUDE_PLUGIN_ROOT}/skills/<skill>/scripts/<script>.py"` prefix. Everything after the closing quote is unchanged.
- **Commit locally after each task. Do NOT push.** The user requires explicit permission for every push.
- Commit messages end with:
  `Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>`

## File Structure

| File | Responsibility |
|---|---|
| `bin/check_skill_conformance.py` | **Create.** Scans `skills/**/*.md` for agent-specific constructs; the regression gate. |
| `bin/test_check_skill_conformance.py` | **Create.** Unit tests for the checker, on temp fixtures. |
| `skills/{spec-manager,wrap-up,code-graph,behavior-graph,codebase-security-scan,behavior-runner,status}/SKILL.md` | **Modify.** Task 2 — 80 invocations. |
| `skills/*/SKILL.md` (8 files) + `skills/{codebase-security-scan,spec-manager}/references/*.md` (3 files) | **Modify.** Task 3 — 177 slash refs. |
| `skills/{codebase-security-scan,dependency-vulnerability-check,codebase-security-resolver}/SKILL.md` | **Modify.** Task 4 — frontmatter and Claude-only affordances. |
| `CONTRIBUTING.md` | **Modify.** Task 5 — the conventions that currently *mandate* what this phase removes. |

---

### Task 1: Conformance checker

The regression gate. Written first so Tasks 2–4 have an objective finish line. Its unit tests pass immediately (they run on temp fixtures); running it against the real repo exits **1** until Task 4 lands. That is expected and is the point.

**Files:**
- Create: `bin/check_skill_conformance.py`
- Test: `bin/test_check_skill_conformance.py`

**Interfaces:**
- Consumes: `bin/commands.json` (the command manifest written in Phase 1). Read it directly with `json.loads`; do **not** import `freya_cli` — the checker must work on an arbitrary `--root`.
- Produces, for later tasks and for CI:
  - `check_file(path: Path, rel: str, allowed: set[str]) -> list[tuple[str, int, str, str]]` returning `(rel, lineno, rule_id, excerpt)`
  - `scan(root: Path, rules: set[str] | None = None) -> list[tuple[str, int, str, str]]`
  - `main(argv: list[str] | None = None) -> int` — `0` clean, `1` violations found
  - Rule ids: `R1` plugin root, `R2` slash ref, `R3` unknown freya command, `R4` agent-specific tool name, `R5` non-standard frontmatter key

- [ ] **Step 1: Write the failing tests**

Create `bin/test_check_skill_conformance.py`:

```python
#!/usr/bin/env python3
"""Unit tests for the skill-layer conformance checker."""

import contextlib
import io
import json
import tempfile
import unittest
from pathlib import Path

import check_skill_conformance as csc


def build_root(tmp, *, skill_md=None, reference_md=None, commands=None):
    """Materialize a minimal suite tree and return its root."""
    root = Path(tmp)
    (root / "bin").mkdir(parents=True)
    (root / "bin" / "commands.json").write_text(
        json.dumps(commands if commands is not None else {"code-graph": "code-graph/scripts/graph_ops.py"}),
        encoding="utf-8",
    )
    skill_dir = root / "skills" / "demo"
    skill_dir.mkdir(parents=True)
    (skill_dir / "SKILL.md").write_text(
        skill_md if skill_md is not None else "---\nname: demo\ndescription: d\n---\n\nBody.\n",
        encoding="utf-8",
    )
    if reference_md is not None:
        (skill_dir / "references").mkdir()
        (skill_dir / "references" / "notes.md").write_text(reference_md, encoding="utf-8")
    return root


def rules_hit(root, **kwargs):
    return [v[2] for v in csc.scan(Path(root), **kwargs)]


def run_main(argv):
    """Call main() with its output captured, so the suite stays quiet.

    Returns (exit_code, stdout, stderr) — the captured streams let the tests
    assert on what the tool actually reports, not just how it exits.
    """
    out, err = io.StringIO(), io.StringIO()
    with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
        code = csc.main(argv)
    return code, out.getvalue(), err.getvalue()


class CodeSpanTest(unittest.TestCase):
    def test_fenced_lines_are_code(self):
        lines = ["prose", "```bash", "freya status --json", "```", "more prose"]
        self.assertEqual(list(csc.code_spans(lines)), [(3, "freya status --json")])

    def test_inline_backticks_are_code(self):
        lines = ["Run `freya drift --project .` now."]
        self.assertEqual(list(csc.code_spans(lines)), [(1, "freya drift --project .")])

    def test_prose_outside_backticks_is_not_code(self):
        lines = ["The freya launcher resolves the suite root."]
        self.assertEqual(list(csc.code_spans(lines)), [])


class FrontmatterTest(unittest.TestCase):
    def test_top_level_keys_are_returned(self):
        lines = ["---", "name: demo", "description: d", "---", "body: not frontmatter"]
        self.assertEqual(list(csc.frontmatter_keys(lines)), [(2, "name"), (3, "description")])

    def test_indented_description_body_is_not_a_key(self):
        lines = ["---", "description: |", "  TRIGGER when: something happens", "---"]
        self.assertEqual(list(csc.frontmatter_keys(lines)), [(2, "description")])

    def test_missing_frontmatter_yields_nothing(self):
        self.assertEqual(list(csc.frontmatter_keys(["# Title", "body"])), [])


class RuleTest(unittest.TestCase):
    def test_plugin_root_is_flagged(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = build_root(tmp, skill_md='python "${CLAUDE_PLUGIN_ROOT}/skills/x/scripts/y.py" --go\n')
            self.assertIn("R1", rules_hit(root))

    def test_audit_workflow_line_is_exempt(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = build_root(
                tmp,
                skill_md='Run `scriptPath: "${CLAUDE_PLUGIN_ROOT}/workflows/codebase-security-audit.js"`.\n',
            )
            self.assertNotIn("R1", rules_hit(root))

    def test_two_plugin_roots_on_one_line_count_twice(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = build_root(tmp, skill_md="${CLAUDE_PLUGIN_ROOT} and ${CLAUDE_PLUGIN_ROOT}\n")
            self.assertEqual(rules_hit(root).count("R1"), 2)

    def test_slash_ref_is_flagged(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = build_root(tmp, skill_md="See /freya-devkit:code-graph for details.\n")
            self.assertIn("R2", rules_hit(root))

    def test_prefixed_skill_name_is_accepted(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = build_root(tmp, skill_md="See the `freya-code-graph` skill for details.\n")
            self.assertEqual(rules_hit(root), [])

    def test_hyphenated_skill_name_is_not_a_command(self):
        """freya-code-graph is a skill name, not `freya <command>` — R3 must ignore it."""
        with tempfile.TemporaryDirectory() as tmp:
            root = build_root(tmp, skill_md="Invoke `freya-docs-manager update` when done.\n")
            self.assertNotIn("R3", rules_hit(root))

    def test_unknown_freya_command_is_flagged(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = build_root(tmp, skill_md="Run `freya bogus-command --now`.\n")
            self.assertIn("R3", rules_hit(root))

    def test_registered_command_is_accepted(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = build_root(tmp, skill_md="Run `freya code-graph --build`.\n")
            self.assertEqual(rules_hit(root), [])

    def test_builtin_command_is_accepted(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = build_root(tmp, skill_md="Run `freya doctor` to verify.\n")
            self.assertEqual(rules_hit(root), [])

    def test_prose_freya_word_is_not_a_command(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = build_root(tmp, skill_md="The freya launcher resolves the suite root.\n")
            self.assertEqual(rules_hit(root), [])

    def test_ask_tool_name_is_flagged(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = build_root(tmp, skill_md="Use askUserQuestion with an open prompt.\n")
            self.assertIn("R4", rules_hit(root))

    def test_plan_mode_tool_name_is_flagged(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = build_root(tmp, skill_md="Use EnterPlanMode tool to create a plan.\n")
            self.assertIn("R4", rules_hit(root))

    def test_bare_tool_word_is_flagged(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = build_root(tmp, skill_md="Create files using the Write tool:\n")
            self.assertIn("R4", rules_hit(root))

    def test_workflow_tool_is_exempt_until_phase_4b(self):
        """audit mode still runs on the Workflow tool; Phase 4b removes both."""
        with tempfile.TemporaryDirectory() as tmp:
            root = build_root(tmp, skill_md="Run the Workflow tool with scriptPath.\n")
            self.assertNotIn("R4", rules_hit(root))

    def test_ordinary_prose_tool_is_not_flagged(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = build_root(tmp, skill_md="npm audit is a security tool worth running.\n")
            self.assertNotIn("R4", rules_hit(root))

    def test_extra_frontmatter_key_is_flagged(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = build_root(
                tmp, skill_md="---\nname: demo\ndescription: d\ncompatibility: Requires Agent\n---\n"
            )
            self.assertIn("R5", rules_hit(root))

    def test_name_and_description_are_allowed(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = build_root(tmp, skill_md="---\nname: demo\ndescription: d\n---\n")
            self.assertEqual(rules_hit(root), [])

    def test_reference_markdown_is_scanned(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = build_root(tmp, reference_md="See /freya-devkit:spec-manager.\n")
            self.assertIn("R2", rules_hit(root))

    def test_rule_filter_restricts_output(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = build_root(
                tmp, skill_md='python "${CLAUDE_PLUGIN_ROOT}/a.py"\nSee /freya-devkit:code-graph.\n'
            )
            self.assertEqual(rules_hit(root, rules={"R2"}), ["R2"])


class MainTest(unittest.TestCase):
    def test_clean_tree_exits_zero(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = build_root(tmp)
            code, out, _ = run_main(["--root", str(root)])
            self.assertEqual(code, 0)
            self.assertIn("conformant", out)

    def test_violation_exits_one(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = build_root(tmp, skill_md="See /freya-devkit:code-graph.\n")
            code, out, err = run_main(["--root", str(root)])
            self.assertEqual(code, 1)
            self.assertIn("R2", out)
            self.assertIn("1 violation(s).", err)

    def test_missing_manifest_exits_two(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = build_root(tmp)
            (root / "bin" / "commands.json").unlink()
            code, _, err = run_main(["--root", str(root)])
            self.assertEqual(code, 2)
            self.assertIn("commands.json", err)


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `cd bin && python3 -m unittest test_check_skill_conformance -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'check_skill_conformance'`

- [ ] **Step 3: Write the checker**

Create `bin/check_skill_conformance.py`:

```python
#!/usr/bin/env python3
"""Guard the shipped skill layer against agent-specific constructs.

Phase 2 of the portability track removed ${CLAUDE_PLUGIN_ROOT} invocations and
/freya-devkit: slash references from skills/**/*.md. This checker is what keeps
them out: it is a regression gate, not a one-off migration script.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

#: Launcher subcommands that are not in the command manifest.
BUILTIN_COMMANDS = frozenset({"install", "update", "doctor", "init", "help"})

#: The Agent Skills standard defines exactly these frontmatter keys.
ALLOWED_FRONTMATTER = frozenset({"name", "description"})

#: Phase 4b retires workflows/codebase-security-audit.js and its Workflow-tool
#: invocation. Until then those lines are the one sanctioned ${CLAUDE_PLUGIN_ROOT}
#: use, and the exemption disappears on its own when the file does.
AUDIT_WORKFLOW_MARKER = "codebase-security-audit"

RULES = {
    "R1": "${CLAUDE_PLUGIN_ROOT} is Claude-only — use a `freya <command>` invocation",
    "R2": "/freya-devkit: is Claude-only — use the prefixed skill name freya-<skill>",
    "R3": "unknown freya command — add it to bin/commands.json or fix the name",
    "R4": "agent-specific tool name — use agent-neutral phrasing",
    "R5": "non-standard frontmatter key — Agent Skills defines name and description",
}

PLUGIN_ROOT = "${CLAUDE_PLUGIN_ROOT}"
SLASH_REF = "/freya-devkit:"
FRONTMATTER_KEY = re.compile(r"([A-Za-z_][A-Za-z0-9_-]*):")

#: Tool names that exist under one agent only. "Workflow tool" is deliberately
#: absent: `audit` mode still runs on it, and Phase 4b removes the engine and this
#: exemption together. Adding it now would make the gate unreachable.
AGENT_TOOL_NAMES = re.compile(
    r"\b(?:askUserQuestion|AskUserQuestion|EnterPlanMode|ExitPlanMode|TodoWrite|WebSearch)\b"
    r"|\b(?:Read|Write|Edit|Glob|Grep|Bash|Task|Agent|Skill) tool\b"
)

#: A CLI invocation is `freya` + whitespace + a command word. The whitespace is
#: load-bearing: `freya-code-graph` is a skill name, not a command, and must not match.
FREYA_COMMAND = re.compile(r"\bfreya[ \t]+([a-z][a-z0-9-]*)")

INLINE_CODE = re.compile(r"`([^`]+)`")


def code_spans(lines):
    """Yield (lineno, text) for text an agent reads as a command.

    That is every line inside a fenced block, plus every inline `code` span
    outside one. Prose is excluded so ordinary sentences mentioning freya do
    not register as command invocations.
    """
    in_fence = False
    for lineno, line in enumerate(lines, 1):
        if line.lstrip().startswith("```"):
            in_fence = not in_fence
            continue
        if in_fence:
            yield lineno, line
        else:
            for span in INLINE_CODE.findall(line):
                yield lineno, span


def frontmatter_keys(lines):
    """Yield (lineno, key) for each top-level YAML frontmatter key.

    Indented lines are block-scalar content (e.g. the body of `description: |`),
    not keys, so the pattern is deliberately anchored at column zero.
    """
    if not lines or lines[0].strip() != "---":
        return
    for lineno, line in enumerate(lines[1:], 2):
        if line.strip() == "---":
            return
        match = FRONTMATTER_KEY.match(line)
        if match:
            yield lineno, match.group(1)


def check_file(path, rel, allowed):
    """Return a list of (rel, lineno, rule_id, excerpt) violations for one file."""
    lines = path.read_text(encoding="utf-8").splitlines()
    violations = []

    for lineno, line in enumerate(lines, 1):
        if AUDIT_WORKFLOW_MARKER not in line:
            for _ in range(line.count(PLUGIN_ROOT)):
                violations.append((rel, lineno, "R1", line.strip()))
        for _ in range(line.count(SLASH_REF)):
            violations.append((rel, lineno, "R2", line.strip()))
        for match in AGENT_TOOL_NAMES.finditer(line):
            violations.append((rel, lineno, "R4", match.group(0)))

    for lineno, span in code_spans(lines):
        for command in FREYA_COMMAND.findall(span):
            if command not in allowed:
                violations.append((rel, lineno, "R3", f"freya {command}"))

    for lineno, key in frontmatter_keys(lines):
        if key not in ALLOWED_FRONTMATTER:
            violations.append((rel, lineno, "R5", f"{key}:"))

    return violations


def load_allowed_commands(root):
    """Return every valid `freya <command>` word: manifest entries plus builtins."""
    manifest = json.loads((root / "bin" / "commands.json").read_text(encoding="utf-8"))
    if not isinstance(manifest, dict):
        raise ValueError("bin/commands.json must contain a JSON object")
    return set(manifest) | set(BUILTIN_COMMANDS)


def scan(root, rules=None):
    """Scan every markdown file under root/skills. Returns sorted violations."""
    allowed = load_allowed_commands(root)
    violations = []
    for path in sorted((root / "skills").rglob("*.md")):
        violations.extend(check_file(path, str(path.relative_to(root)), allowed))
    if rules is not None:
        violations = [v for v in violations if v[2] in rules]
    return sorted(violations)


def main(argv=None):
    parser = argparse.ArgumentParser(
        description="Check the shipped skill layer for agent-specific constructs."
    )
    parser.add_argument("--root", type=Path, default=None, help="Suite root (default: this checkout)")
    parser.add_argument(
        "--rule", action="append", choices=sorted(RULES), help="Only report these rules (repeatable)"
    )
    args = parser.parse_args(argv)

    root = args.root if args.root is not None else Path(__file__).resolve().parents[1]

    try:
        violations = scan(root, rules=set(args.rule) if args.rule else None)
    except (OSError, ValueError) as exc:
        print(f"check-skill-conformance: {exc}", file=sys.stderr)
        return 2

    for rel, lineno, rule, excerpt in violations:
        print(f"{rel}:{lineno}: {rule}: {excerpt}")

    if violations:
        counts = {}
        for _, _, rule, _ in violations:
            counts[rule] = counts.get(rule, 0) + 1
        print(file=sys.stderr)
        for rule in sorted(counts):
            print(f"  {rule} ({counts[rule]}): {RULES[rule]}", file=sys.stderr)
        print(f"\n{len(violations)} violation(s).", file=sys.stderr)
        return 1

    print("skill layer is conformant.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `cd bin && python3 -m unittest test_check_skill_conformance -v`
Expected: PASS — 28 tests, `OK`

- [ ] **Step 5: Verify the guards are real (mutation check)**

Three guards carry the most weight. Break each, confirm the *named* test fails, restore.

1. In `FREYA_COMMAND`, change `r"\bfreya[ \t]+([a-z][a-z0-9-]*)"` to `r"\bfreya[- \t]+([a-z][a-z0-9-]*)"`.
   Expected: FAIL on `test_hyphenated_skill_name_is_not_a_command`. **Restore the line.**
2. In `check_file`, change `if AUDIT_WORKFLOW_MARKER not in line:` to `if True:`.
   Expected: FAIL on `test_audit_workflow_line_is_exempt`. **Restore the line.**
3. In `AGENT_TOOL_NAMES`, append `|\bWorkflow tool\b` to the pattern.
   Expected: FAIL on `test_workflow_tool_is_exempt_until_phase_4b`. **Restore the line.**

Run `cd bin && python3 -m unittest test_check_skill_conformance -v` after each mutation
and again after restoring all three; the final run must be PASS, 28 tests.

- [ ] **Step 6: Confirm the starting violation count**

Run: `python3 bin/check_skill_conformance.py; echo "exit=$?"`

Expected — `exit=1` and exactly this summary (measured 2026-07-28; if your numbers differ, the checker is wrong, not the tree):

```
  R1 (80): ${CLAUDE_PLUGIN_ROOT} is Claude-only — use a `freya <command>` invocation
  R2 (177): /freya-devkit: is Claude-only — use the prefixed skill name freya-<skill>
  R4 (7): agent-specific tool name — use agent-neutral phrasing
  R5 (2): non-standard frontmatter key — Agent Skills defines name and description

266 violation(s).
```

R3 is absent because no `freya <command>` exists in the skill layer yet — Task 2 introduces the first ones. Task 2 clears R1, Task 3 clears R2, Task 4 clears R4 and R5.

- [ ] **Step 7: Commit**

```bash
git add bin/check_skill_conformance.py bin/test_check_skill_conformance.py
git commit -F - <<'EOF'
test(portability): add skill-layer conformance checker

Phase 2 gate. Flags ${CLAUDE_PLUGIN_ROOT} (R1), /freya-devkit: slash refs
(R2), unregistered freya commands (R3), agent-specific tool names (R4), and
non-standard frontmatter keys (R5) across skills/**/*.md.

Exits 1 against the tree today; Tasks 2-4 drive it to green. The audit
Workflow references are exempt until Phase 4b retires that file.

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>
EOF
```

---

### Task 2: Rewrite the 80 script invocations

**Files:**
- Modify: `skills/spec-manager/SKILL.md` (34), `skills/wrap-up/SKILL.md` (25), `skills/code-graph/SKILL.md` (9), `skills/behavior-graph/SKILL.md` (7), `skills/codebase-security-scan/SKILL.md` (1 of its 3; the other 2 are the exempt audit refs), `skills/behavior-runner/SKILL.md` (2), `skills/status/SKILL.md` (2)

**Interfaces:**
- Consumes: `bin/commands.json` from Phase 1, and `bin/check_skill_conformance.py` from Task 1.
- Produces: a skill layer where R1 is clean; Task 5's green gate depends on it.

**The complete mapping.** Every invoked script is already registered — there are no gaps and nothing to add to the manifest.

| `${CLAUDE_PLUGIN_ROOT}` script path | Replacement | Sites |
|---|---|---|
| `skills/spec-manager/scripts/drift.py` | `freya drift` | 12 |
| `skills/behavior-graph/scripts/behavior_graph.py` | `freya behavior-graph` | 12 |
| `skills/spec-manager/scripts/search_specs.py` | `freya spec` | 10 |
| `skills/spec-manager/scripts/contradictions.py` | `freya contradictions` | 10 |
| `skills/code-graph/scripts/graph_ops.py` | `freya code-graph` | 9 |
| `skills/spec-manager/scripts/principles.py` | `freya principles` | 8 |
| `skills/spec-manager/scripts/adr.py` | `freya adr` | 7 |
| `skills/spec-manager/scripts/verify_intent.py` | `freya verify-intent` | 3 |
| `skills/status/scripts/collect_status.py` | `freya status` | 2 |
| `skills/spec-manager/scripts/verify_links.py` | `freya verify-links` | 2 |
| `skills/behavior-runner/scripts/run_behaviors.py` | `freya behavior-runner` | 2 |
| `skills/spec-manager/scripts/project_shape.py` | `freya project-shape` | 1 |
| `skills/spec-manager/scripts/intent.py` | `freya intent` | 1 |
| `skills/spec-manager/scripts/adapters.py` | `freya adapters` | 1 |
| | **total** | **80** |

**The rule.** Replace the whole token sequence

```
python "${CLAUDE_PLUGIN_ROOT}/<script path from the table>"
```

with the replacement from the table. **Everything after the closing double-quote is preserved byte-for-byte** — flags, arguments, trailing `\` line continuations, and trailing comments. Backslash continuations stay; only the first line of a multi-line invocation changes.

Worked examples covering every form present in the tree:

```
# bare, fenced (75 sites)
-python "${CLAUDE_PLUGIN_ROOT}/skills/spec-manager/scripts/principles.py" list --project .
+freya principles list --project .

# multi-line continuation (43 of the 75)
-python "${CLAUDE_PLUGIN_ROOT}/skills/behavior-graph/scripts/behavior_graph.py" \
+freya behavior-graph \
     --check --project .

# shell-chained (skills/wrap-up/SKILL.md:181)
-   && python "${CLAUDE_PLUGIN_ROOT}/skills/behavior-graph/scripts/behavior_graph.py" \
+   && freya behavior-graph \

# inline, in a numbered step (skills/spec-manager/SKILL.md:516, 525, 546)
-1. Run `python "${CLAUDE_PLUGIN_ROOT}/skills/spec-manager/scripts/search_specs.py" --query "<query>"`
+1. Run `freya spec --query "<query>"`
```

- [ ] **Step 1: Hand-edit the prose sites**

Four sentences and headings describe the target as a *script you invoke*; after the rewrite it is a *command*. None of them contain the `python "${CLAUDE_PLUGIN_ROOT}/…"` string, so the mechanical substitution in Step 2 cannot reach them — do them first, by hand.

```
skills/spec-manager/SKILL.md:966
-## Search Script
+## Search Command

skills/spec-manager/SKILL.md:968
-The `python "${CLAUDE_PLUGIN_ROOT}/skills/spec-manager/scripts/search_specs.py"` script provides fast local searching.
+The `freya spec` command provides fast local searching.

skills/spec-manager/SKILL.md:985  (delete the line — the usage above already covers it)
-The script is in the skill's `scripts/` directory. Call it with `python` using the full path.

skills/code-graph/SKILL.md:364-366
-## Script Usage
-
-The underlying `graph_ops.py` script can be called directly:
+## Command Usage
+
+The `freya code-graph` command wraps the underlying `graph_ops.py` script:
```

Afterwards, `grep -rn -i '\bpython\b' skills/*/SKILL.md` must return only two hits, both naming Python as a *language* (`code-graph/SKILL.md:101` and `:405`).

- [ ] **Step 2: Apply the remaining 79 substitutions**

Work file by file, in descending count order: `spec-manager`, `wrap-up`, `code-graph`, `behavior-graph`, `behavior-runner`, `status`, `codebase-security-scan`. Apply the table mechanically.

Do **not** touch `skills/codebase-security-scan/SKILL.md` lines 442 and 450 — those are the audit Workflow references reserved for Phase 4b.

- [ ] **Step 3: Verify no invocation survives, and none was invented**

```bash
# Only the two exempt audit lines may remain in the markdown.
grep -rn 'CLAUDE_PLUGIN_ROOT' skills/ --include='*.md'
```
Expected: exactly two lines, both `skills/codebase-security-scan/SKILL.md` (442, 450).

Note the `--include='*.md'`. Without it you also get `skills/spec-manager/scripts/search_specs.py:34`, a stale mention in a code comment. That one is real but out of scope here — this phase does not touch `skills/*/scripts/`, and it is already assigned to Phase 3 under *Carried forward*.

```bash
python3 bin/check_skill_conformance.py --rule R1 --rule R3; echo "exit=$?"
```
Expected: `exit=0` — R1 clean, and every `freya <command>` introduced is a registered command.

- [ ] **Step 4: Verify the flags were preserved, not just the command names**

R3 proves the command *names* are real. This proves the *flags* still are. Confirm each of the 14 commands is live end-to-end through the launcher:

```bash
for c in drift behavior-graph spec contradictions code-graph principles adr \
         verify-intent status verify-links behavior-runner project-shape intent adapters; do
  printf '%-16s ' "$c"
  ./bin/freya "$c" --help >/dev/null 2>&1 && echo ok || echo FAILED
done
```
Expected: `ok` for all 14.

Then diff-review that nothing but the prefix changed:

```bash
git diff -U0 -- skills/ | grep '^[-+]' | grep -v '^[-+][-+]' | grep -c ''
```
Expected: 160 changed lines (80 removals + 80 additions). A higher number means an edit went beyond the prefix — inspect `git diff` before continuing.

- [ ] **Step 5: Commit**

```bash
git add skills/
git commit -F - <<'EOF'
refactor(skills): invoke scripts via the freya launcher

Replaces all 80 `python "${CLAUDE_PLUGIN_ROOT}/..."` invocations across seven
SKILL.md files with the equivalent `freya <command>` form. Flags and arguments
are preserved verbatim; only the invocation prefix changes.

Also fixes the latent bare-`python` hazard for free: the launcher runs targets
with sys.executable, so the skills no longer depend on a `python` on PATH.

The two audit Workflow references remain until Phase 4b retires that engine.

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>
EOF
```

---

### Task 3: Rewrite the 177 slash references

**Files:**
- Modify: `skills/spec-manager/SKILL.md` (40), `skills/wrap-up/SKILL.md` (27), `skills/docs-manager/SKILL.md` (29), `skills/codebase-security-scan/SKILL.md` (26), `skills/codebase-security-resolver/SKILL.md` (26), `skills/code-graph/SKILL.md` (18), `skills/dependency-vulnerability-check/SKILL.md` (3), `skills/status/SKILL.md` (2)
- Modify: `skills/spec-manager/references/adr-template.md` (3), `skills/codebase-security-scan/references/findings-schema.md` (1), `skills/spec-manager/references/decisions-readme.md` (1)

**Interfaces:**
- Consumes: nothing from earlier tasks beyond the Task 1 checker.
- Produces: R2 clean.

**The rule — a single substitution, applied everywhere including inside YAML frontmatter:**

```
/freya-devkit:<skill>   →   freya-<skill>
```

The leading slash is dropped and the `freya-` prefix is added. Nothing else on the line changes. This is deliberately mechanical: the current form already reads as "skill name, optionally followed by a mode", and that reading is preserved exactly.

```
-1. **If `/freya-devkit:code-graph` skill is available:**
+1. **If `freya-code-graph` skill is available:**

-### `/freya-devkit:code-graph build`
+### `freya-code-graph build`

-Run `/freya-devkit:docs-manager update` to sync project documentation.
+Run `freya-docs-manager update` to sync project documentation.

-- `/freya-devkit:code-graph` - Dependency graph
+- `freya-code-graph` - Dependency graph
```

**Frontmatter is included.** Four skills reference others from inside `description:`, which is what drives discovery, so these matter most:

```
-  INTEGRATION: Uses /freya-devkit:code-graph skill (when available) for impact-aware documentation
+  INTEGRATION: Uses freya-code-graph skill (when available) for impact-aware documentation
```

**Include** the `compatibility:` line in `skills/codebase-security-scan/SKILL.md:23` — 2 of the 177 sit there (`/freya-devkit:code-graph`, `/freya-devkit:spec-manager`). Task 4 deletes that whole line, so rewriting it now is throwaway work, but it keeps this task's gate exact: R2 must reach **zero** here, not two.

**Do not** touch the `/loop` invocations in this task. There are 7 `/loop` lines, 6 of which also carry a `/freya-devkit:` ref (the 7th, `dependency-vulnerability-check/SKILL.md:24`, mentions `/loop` alone). Apply only the slash-ref substitution here and let Task 4 handle `/loop`. An intermediate state like `/loop 1d freya-dependency-vulnerability-check` is expected and correct at the end of this task.

**The one-character hazard.** After this task both forms appear in the same files:

- `freya spec --query "x"` — **space** — the CLI launcher, from Task 2
- `freya-spec-manager` — **hyphen** — a skill name, from this task

Never convert between them. If a site currently reads `/freya-devkit:spec-manager`, it is a *skill* reference and becomes `freya-spec-manager`, even where a superficially similar `freya spec` CLI command exists. `code-graph`, `status`, and `spec`/`spec-manager` are the three places this is easy to get wrong.

- [ ] **Step 1: Apply the substitution across all 11 files**

Work file by file. Confirm each file's post-edit count matches the table above.

- [ ] **Step 2: Verify completeness and correctness**

```bash
grep -rn '/freya-devkit:' skills/ ; echo "remaining=$?"
```
Expected: no output, `remaining=1` (grep found nothing).

```bash
python3 bin/check_skill_conformance.py --rule R2 --rule R3; echo "exit=$?"
```
Expected: `exit=0`. R3 clean here is the real safety net — it proves no skill reference was accidentally turned into a `freya <command>` that does not exist.

```bash
grep -rc 'freya-' skills/*/SKILL.md skills/*/references/*.md | grep -v ':0$'
```
Expected: counts matching the Files list above (spec-manager 40, wrap-up 27, docs-manager 29, …).

- [ ] **Step 3: Spot-check the three collision-prone names**

```bash
grep -rn 'freya[- ]code-graph\|freya[- ]status\|freya[- ]spec' skills/ | grep -v '^Binary'
```
Read every hit. Each must be either a fenced/inline **command** with a space (`freya code-graph --build`, `freya status --json`, `freya spec --query`) or a **skill name** with a hyphen (`freya-code-graph`, `freya-status`, `freya-spec-manager`). Anything else is a defect introduced by this task.

- [ ] **Step 4: Commit**

```bash
git add skills/
git commit -F - <<'EOF'
refactor(skills): use prefixed skill names instead of Claude slash refs

Replaces all 177 `/freya-devkit:<skill>` references across eight SKILL.md
files and three references/*.md files with the prefixed name `freya-<skill>`
(design Decision 3), including inside the `description:` frontmatter that
drives skill discovery.

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>
EOF
```

---

### Task 4: Remove the remaining Claude-only affordances

Small, unrelated edits that share one property: each names a Claude Code feature that does not exist under that name on other agents.

**Files:**
- Modify: `skills/codebase-security-scan/SKILL.md` — drop `compatibility:` (1); `/loop` (3); `WebSearch` (1)
- Modify: `skills/dependency-vulnerability-check/SKILL.md` — drop `compatibility:` (1); `/loop` (4); `WebSearch` (1)
- Modify: `skills/codebase-security-resolver/SKILL.md` — `askUserQuestion` (1); `EnterPlanMode` (1); plan-mode phrasing (4)
- Modify: `skills/docs-manager/SKILL.md` — `Write tool` (1)

**Interfaces:**
- Consumes: the Task 1 checker.
- Produces: R4 and R5 clean — the last two rules still red.

**Deliberately out of scope:** the four "Workflow tool" references in `skills/codebase-security-scan/SKILL.md` (L436, L442, L450, L564). `audit` mode genuinely still runs on that engine; Phase 4b removes the engine and these references together. `AGENT_TOOL_NAMES` omits the phrase for exactly this reason, so leaving them does not block the green gate.

- [ ] **Step 1: Delete the two `compatibility:` frontmatter lines**

`compatibility:` is not part of the Agent Skills standard. Neither line carries a requirement worth keeping in prose: the tool list restates what the skill body already does, and the optional-skill note is already stated in the `description:` INTEGRATION block directly above it.

In `skills/codebase-security-scan/SKILL.md`, delete this line entirely:

```
compatibility: Requires Agent, Read, Glob, Grep, Write, WebSearch tools. Optional: /freya-devkit:code-graph skill, /freya-devkit:spec-manager skill
```

In `skills/dependency-vulnerability-check/SKILL.md`, delete this line entirely:

```
compatibility: Requires Bash, Read, Write, Glob, Grep, WebSearch tools
```

- [ ] **Step 2: Genericize the 7 `/loop` sites**

`/loop` is a Claude Code slash command. Replace it with a statement of intent the user's own scheduler can satisfy.

`skills/dependency-vulnerability-check/SKILL.md:24`:
```
-- Setting up periodic security scanning (works well with `/loop` for daily/weekly checks)
+- Setting up periodic security scanning (pair it with your agent's scheduler, or cron, for daily/weekly checks)
```

`skills/dependency-vulnerability-check/SKILL.md:205`:
```
-- Consider scheduling regular security audits (use `/loop 1d freya-dependency-vulnerability-check`)
+- Consider scheduling regular security audits (run `freya-dependency-vulnerability-check` daily via your agent's scheduler or cron)
```

`skills/codebase-security-scan/SKILL.md:886`:
```
-4. Schedule regular security audits (use `/loop 1w freya-codebase-security-scan`)
+4. Schedule regular security audits (run `freya-codebase-security-scan` weekly via your agent's scheduler or cron)
```

The remaining four sit inside fenced blocks that exist only to show `/loop` syntax. A fenced block implies "type this", and there is no cross-agent equivalent to type — so replace each block with prose rather than inventing a fake command.

`skills/dependency-vulnerability-check/SKILL.md:235-246` — replace the whole section:

````markdown
## Example usage with scheduling

To run this check daily:
```
/loop 1d freya-dependency-vulnerability-check
```

To run weekly:
```
/loop 1w freya-dependency-vulnerability-check
```
````

with:

````markdown
## Example usage with scheduling

Run the `freya-dependency-vulnerability-check` skill on a recurring schedule using
whatever your agent provides — a built-in loop/scheduler command, a CI job, or a
system cron entry.

- **Daily** — recommended while a project is under active development.
- **Weekly** — recommended for projects in maintenance mode.
````

`skills/codebase-security-scan/SKILL.md:968-980` — replace the whole section:

````markdown
## Scheduling

To run weekly security scans:
```
/loop 1w freya-codebase-security-scan
```

For incremental updates after code changes:
```
/loop 1d freya-codebase-security-scan update
```
````

with:

````markdown
## Scheduling

Run the `freya-codebase-security-scan` skill on a recurring schedule using whatever
your agent provides — a built-in loop/scheduler command, a CI job, or a system cron
entry.

- **Weekly, full `scan`** — a complete security assessment.
- **Daily, `update` mode** — incremental analysis of what changed.

`audit` mode is deliberately absent here: it is on-demand and expensive. Run it
before a release, not on a timer.
````

(Lines 205, 886, and the fenced blocks already read `freya-…` rather than `/freya-devkit:…` because Task 3 rewrote them. Line numbers shift as you delete lines — work bottom-up within each file, or re-grep between edits.)

- [ ] **Step 3: Genericize `askUserQuestion`**

`skills/codebase-security-resolver/SKILL.md:250`:
```
-Use askUserQuestion with an open prompt:
+Ask the user, with an open prompt:
```

- [ ] **Step 4: Genericize the plan-mode phrasing**

Claude Code's "plan mode" is a named mode; other agents have no such command. Describe the behavior instead of naming the feature. Four of the five sites are headings or list items; keep them terse.

`skills/codebase-security-resolver/SKILL.md:16` (inside `description:`):
```
-  WORKFLOW: Lists findings → user selects -> validate findings → summarize with validation notes -> confirm -> enter plan mode →
+  WORKFLOW: Lists findings → user selects -> validate findings → summarize with validation notes -> confirm -> present a fix plan for approval →
```

`skills/codebase-security-resolver/SKILL.md:340` and `:342` — the heading and the sentence under it. Line 342 also carries the `EnterPlanMode` tool name, so both go together:
```
-**Phase 9: Enter Plan Mode**
-
-Use EnterPlanMode tool to create an implementation plan for the selected findings.
+**Phase 9: Present the Fix Plan for Approval**
+
+Produce an implementation plan for the selected findings and present it to the user
+for approval before making any edits.
```

`skills/codebase-security-resolver/SKILL.md:346`:
```
-When entering plan mode, include:
+In the plan, include:
```

`skills/codebase-security-resolver/SKILL.md:626`:
```
-6. Enter plan mode
+6. Present the fix plan for approval
```

Do not change what Phase 9 does — only how it is named. The plan contents, the example plan header, and every later phase stay as they are.

- [ ] **Step 5: Genericize the two remaining tool names**

`skills/dependency-vulnerability-check/SKILL.md:71`:
```
-   - Use WebSearch to look up: `CVE-XXXX-XXXXX vulnerability details exploit`
+   - Search the web for: `CVE-XXXX-XXXXX vulnerability details exploit`
```

`skills/codebase-security-scan/SKILL.md:477`:
```
-For each potential finding, use WebSearch to validate:
+For each potential finding, search the web to validate:
```

`skills/docs-manager/SKILL.md:501`:
```
-2. Create/update files using the Write tool:
+2. Create or update the files:
```

(The other two `WebSearch` mentions were on the `compatibility:` lines deleted in Step 1.)

- [ ] **Step 6: Verify**

```bash
grep -rn '/loop\|askUserQuestion\|EnterPlanMode\|WebSearch\|Write tool\|compatibility:' skills/
grep -rni 'plan mode' skills/
```
Expected: no output from either.

```bash
python3 bin/check_skill_conformance.py; echo "exit=$?"
```
Expected: `exit=0` — **all five rules clean**. This is the phase's finish line.

- [ ] **Step 7: Commit**

```bash
git add skills/
git commit -F - <<'EOF'
refactor(skills): drop Claude-only affordances from the skill layer

- Remove the two non-standard `compatibility:` frontmatter keys; Agent Skills
  defines only `name` and `description`.
- Replace the 7 `/loop` scheduling references (a Claude Code slash command) with
  scheduler-neutral guidance; the two fenced `/loop` blocks become prose, since
  there is no cross-agent command to put in a code block.
- Replace the Claude tool names `askUserQuestion`, `EnterPlanMode`, `WebSearch`
  and `Write tool` with plain descriptions of the action.
- Rename "enter plan mode" to "present the fix plan for approval" in
  codebase-security-resolver; the behaviour is unchanged, only the phrasing
  stops naming a Claude-specific mode.

The four "Workflow tool" references stay: `audit` still runs on that engine,
and Phase 4b retires both together.

check_skill_conformance now exits 0.

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>
EOF
```

---

### Task 5: Update the contributor conventions and prove the tree is green

`CONTRIBUTING.md` currently *mandates* the two constructs this phase removed. Left alone, the next contributor follows it and the checker rejects their work with no guidance. This is the one file outside `skills/` that Phase 2 touches; the rest of the user-facing docs are Phase 3.

**Files:**
- Modify: `CONTRIBUTING.md:22-28` ("Conventions to preserve")

**Interfaces:**
- Consumes: the finished skill layer from Tasks 2–4.
- Produces: the phase's exit state — a fully green tree.

- [ ] **Step 1: Rewrite the two stale conventions and add the missing one**

Replace lines 24–26:

```markdown
- **Namespaced cross-references.** Skills call each other as `/freya-devkit:<skill>`, never the bare `/<skill>` form (bare names only resolve for loose `~/.claude/skills/` installs, not plugin installs).
- **Bundled script paths.** Reference bundled scripts via `${CLAUDE_PLUGIN_ROOT}`, e.g.
  `python "${CLAUDE_PLUGIN_ROOT}/skills/code-graph/scripts/graph_ops.py" ...`. Always quote (handles spaces in the install path).
```

with:

```markdown
- **Agent-neutral skill layer.** Nothing under `skills/` may name a Claude-only
  construct. `python3 bin/check_skill_conformance.py` enforces this and must exit 0;
  run it before you commit.
- **Cross-references use the prefixed skill name.** Skills refer to each other as
  `freya-<skill>` (e.g. `freya-code-graph`), never `/freya-devkit:<skill>` and never
  the bare `<skill>` form. The installer creates the skill directories under these
  prefixed names.
- **Script invocations go through the launcher.** Call bundled scripts as
  `freya <command> ...` (e.g. `freya code-graph --build`), never
  `python "${CLAUDE_PLUGIN_ROOT}/..."`. The launcher self-locates and runs the target
  with `sys.executable`, so no `python` needs to be on PATH.
- **Register new CLI scripts in `bin/commands.json`.** Any script under
  `skills/*/scripts/` with a `__main__` block must have a manifest entry, or it is
  unreachable through `freya`. `bin/test_freya_cli.py` fails if you forget.
- **Mind the one-character distinction.** `freya <command>` (space) is the CLI;
  `freya-<skill>` (hyphen) is a skill name. They are never interchangeable.
```

Leave the existing bullet about the audit Workflow (line 27) and the one about additive report fields (line 28) unchanged. The Workflow bullet stops being true in Phase 4b and is that phase's job to remove.

- [ ] **Step 2: Run the conformance checker**

Run: `python3 bin/check_skill_conformance.py; echo "exit=$?"`
Expected: `skill layer is conformant.` and `exit=0`

- [ ] **Step 3: Run every test suite in the repo**

```bash
fail=0
for t in bin/test_*.py skills/*/scripts/test_*.py; do
  d=$(dirname "$t"); m=$(basename "$t" .py)
  ( cd "$d" && python3 -m unittest "$m" -q ) >/dev/null 2>&1 \
    && echo "ok    $t" || { echo "FAIL  $t"; fail=1; }
done
exit $fail
```
Expected: `ok` for all 17 suites (`bin/test_freya_cli.py`, the new `bin/test_check_skill_conformance.py`, and the 15 pre-existing skill suites). Nothing in this phase touches `skills/*/scripts/`, so any failure there is a real regression — investigate, do not rerun-and-hope.

- [ ] **Step 4: Confirm Claude still works**

Design §11 requires Phase 2 to "keep Claude working." The plugin manifest and every script are untouched, so verify the launcher path the skills now depend on:

```bash
./bin/freya doctor; echo "exit=$?"
```
Expected: `exit=0`, with the manifest and scripts checks reporting `ok`.

Then confirm the plugin distribution is byte-for-byte unchanged:

```bash
git diff --stat main -- .claude-plugin/ skills/*/scripts/ workflows/
```
Expected: **exactly one line** — `skills/status/scripts/collect_status.py | 2 +-`, the sanctioned exception from Task 3 (it stamped a Claude-only command into every generated `BACKLOG.md`; see Global Constraints). `.claude-plugin/` and `workflows/` must not appear at all. Anything else in the output is a regression.

- [ ] **Step 5: Commit**

```bash
git add CONTRIBUTING.md
git commit -F - <<'EOF'
docs(contributing): update conventions for the agent-neutral skill layer

The "conventions to preserve" section still mandated `/freya-devkit:` refs and
`${CLAUDE_PLUGIN_ROOT}` paths, which Phase 2 removed — following it would have
reintroduced exactly what check_skill_conformance now rejects.

Also documents the bin/commands.json registration requirement, which was
missing since the launcher landed in Phase 1.

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>
EOF
```

---

## Definition of done

- `python3 bin/check_skill_conformance.py` exits 0.
- `grep -rn 'CLAUDE_PLUGIN_ROOT' skills/ --include='*.md'` returns only the two audit-Workflow lines.
- `grep -rn '/freya-devkit:' skills/` returns nothing — including under `scripts/`.
- All 17 test suites pass.
- `./bin/freya doctor` exits 0. Its one `[warn]` (`freya on PATH: not found`) is expected until Phase 3 installs the launcher.
- `.claude-plugin/` and `workflows/` are unchanged from `main`; `skills/*/scripts/` differs by exactly the one sanctioned `collect_status.py` line.
- **Nothing pushed.**

## Carried forward

- **Phase 3:** the 47 `/freya-devkit:` refs in README, `docs/skill-reference.md`, `docs/conventions.md`, `docs/patterns.md`, `docs/architecture.md`, `docs/philosophy.md`, `CONTRIBUTING.md` — rewritten alongside the real installer, with per-agent invocation syntax. Also `docs/architecture.md`'s one `${CLAUDE_PLUGIN_ROOT}` mention.
  - **The installer must rewrite the `name:` frontmatter field, not just the directory name.** All 173 cross-references are `freya-<skill>`; if only directories are prefixed, those references stay unresolvable on any runtime that keys off `name:`. `CONTRIBUTING.md` now states this contract.
  - `drift.py` still reaches `graph_ops.py` via `abspath` + a textual `../..`. Phase 2 materially de-risked it — every documented invocation now goes through the launcher, whose `suite_root()` uses `.resolve()`, so `drift.py` always runs at its canonical path where the sibling is still `code-graph`. Replace the textual reach with a `suite_root()`-derived path when building the installer.
  - `bin/check_skill_conformance.py`'s `BUILTIN_COMMANDS` allows `install`, `update`, `init` — forward-dated to the installer this phase builds. `./bin/freya` exits 2 on all three today.
- **Phase 4:** the three LLM fan-out flows, including the "using parallel subagents" phrasing left in `codebase-security-scan`'s `description:`.
- **Phase 4b:** the audit Workflow, which must be removed as one unit — the two `${CLAUDE_PLUGIN_ROOT}` references (`skills/codebase-security-scan/SKILL.md` L442, L450), the four "Workflow tool" phrasings (L436, L442, L450, L564), the `AUDIT_WORKFLOW_MARKER` exemption and the `AGENT_TOOL_NAMES` omission in `bin/check_skill_conformance.py`, and the Workflow bullet in `CONTRIBUTING.md`. Add `\bWorkflow tool\b` to `AGENT_TOOL_NAMES` and delete `test_workflow_tool_is_exempt_until_phase_4b` as the last step, so the gate proves the removal was complete.
- **Phase 6:** validate that Claude resolves `freya-<skill>` references correctly under the marketplace-plugin install, where the registered name is `freya-devkit:<skill>`. The final review found the concrete failure path — nine sites branch on skill availability *by name* and instruct the agent to warn-and-skip when it does not match; worst case `wrap-up` skips every phase. Those nine now name the capability and both registered forms, but the end-to-end behaviour is unverified until this phase.
