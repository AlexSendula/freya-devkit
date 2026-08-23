#!/usr/bin/env python3
"""Unit tests for the skill-layer conformance checker."""

import contextlib
import io
import json
import tempfile
import unittest
from pathlib import Path

import check_skill_conformance as csc


def build_root(tmp, *, skill_md=None, reference_md=None, commands=None, script_py=None,
               skill_dir="demo"):
    """Materialize a minimal suite tree and return its root.

    `script_py`, when given, is written to `skills/demo/scripts/tool.py` —
    a fixture for the Python-file coverage the checker also scans.

    `skill_dir` names the skill directory (default `demo`, which every existing
    fixture's `name: demo` frontmatter is written against). R12 needs a
    directory whose name is outside the spec's grammar, and R8 compares against
    whatever this is.
    """
    root = Path(tmp)
    (root / "bin").mkdir(parents=True)
    (root / "bin" / "commands.json").write_text(
        json.dumps(commands if commands is not None else {"code-graph": "code-graph/scripts/graph_ops.py"}),
        encoding="utf-8",
    )
    skill_dir = root / "skills" / skill_dir
    skill_dir.mkdir(parents=True)
    (skill_dir / "SKILL.md").write_text(
        skill_md if skill_md is not None else "---\nname: demo\ndescription: d\n---\n\nBody.\n",
        encoding="utf-8",
    )
    if reference_md is not None:
        (skill_dir / "references").mkdir()
        (skill_dir / "references" / "notes.md").write_text(reference_md, encoding="utf-8")
    if script_py is not None:
        (skill_dir / "scripts").mkdir(exist_ok=True)
        (skill_dir / "scripts" / "tool.py").write_text(script_py, encoding="utf-8")
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
            root = build_root(
                tmp,
                skill_md=(
                    "---\nname: demo\ndescription: d\n---\n\n"
                    "See the `freya-code-graph` skill for details.\n"
                ),
            )
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
            root = build_root(
                tmp, skill_md="---\nname: demo\ndescription: d\n---\n\nRun `freya code-graph --build`.\n"
            )
            self.assertEqual(rules_hit(root), [])

    def test_builtin_command_is_accepted(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = build_root(
                tmp, skill_md="---\nname: demo\ndescription: d\n---\n\nRun `freya doctor` to verify.\n"
            )
            self.assertEqual(rules_hit(root), [])

    def test_prose_freya_word_is_not_a_command(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = build_root(
                tmp,
                skill_md=(
                    "---\nname: demo\ndescription: d\n---\n\n"
                    "The freya launcher resolves the suite root.\n"
                ),
            )
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

    def test_workflow_tool_is_flagged_now_that_audit_is_ported(self):
        """Phase 4b retired the Workflow engine; the exemption went with it."""
        with tempfile.TemporaryDirectory() as tmp:
            root = build_root(tmp, skill_md="Run the Workflow tool with scriptPath.\n")
            self.assertIn("R4", rules_hit(root))

    def test_hyphenated_workflow_references_are_flagged_too(self):
        """The ` tool` alternation missed these, and three shipped past it:
        two SKILL.md files and skill-reference.md all still described `audit`
        as "Workflow-powered" after the engine had been deleted."""
        for phrase in ("a heavier Workflow-powered mode",
                       "the Workflow engine owns the loop",
                       "see the Workflow script for details"):
            with tempfile.TemporaryDirectory() as tmp:
                root = build_root(tmp, skill_md=phrase + "\n")
                self.assertIn("R4", rules_hit(root), phrase)

    def test_lowercase_workflow_prose_is_still_allowed(self):
        """`wrap-up workflow` is ordinary English, not a Claude-only construct."""
        with tempfile.TemporaryDirectory() as tmp:
            root = build_root(tmp, skill_md=(
                "Run this after the wrap-up workflow completes. The workflow "
                "engine in your CI is unrelated.\n"))
            self.assertNotIn("R4", rules_hit(root))

    def test_plugin_root_has_no_exemption_left(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = build_root(
                tmp,
                skill_md='`scriptPath: "${CLAUDE_PLUGIN_ROOT}/workflows/codebase-security-audit.js"`\n',
            )
            self.assertIn("R1", rules_hit(root))

    def test_ordinary_prose_tool_is_not_flagged(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = build_root(tmp, skill_md="npm audit is a security tool worth running.\n")
            self.assertNotIn("R4", rules_hit(root))

    # -- Widened R4 coverage: the ` tool` suffix was one literal space wide ---

    def test_backticked_tool_name_is_flagged(self):
        """Backticking the name is the *default* markdown spelling, and the
        old `\\b(?:Read|...) tool\\b` needed the name bare and the space literal."""
        for phrase in ("Use the `Read` tool to open it.",
                       "Use the **Task** tool to delegate.",
                       "Use the *Write* tool to create files."):
            with tempfile.TemporaryDirectory() as tmp:
                root = build_root(tmp, skill_md=phrase + "\n")
                self.assertIn("R4", rules_hit(root), phrase)

    def test_plural_tools_is_flagged(self):
        """`\\btool\\b` rejected the plural, so a coordination shipped clean."""
        with tempfile.TemporaryDirectory() as tmp:
            root = build_root(tmp, skill_md="Use the Read and Write tools for this.\n")
            self.assertIn("R4", rules_hit(root))

    def test_claude_only_compound_tokens_are_flagged(self):
        """Half of Claude's tool surface was simply absent from the pattern.
        These compounds have no plain-English reading, so a bare token is enough."""
        for token in ("MultiEdit", "NotebookEdit", "WebFetch", "SlashCommand",
                      "BashOutput", "KillShell", "subagent_type"):
            with tempfile.TemporaryDirectory() as tmp:
                root = build_root(tmp, skill_md=f"Apply the change with {token}.\n")
                self.assertIn("R4", rules_hit(root), token)

    def test_instruction_verb_before_a_tool_name_is_flagged(self):
        """The shipped spelling that had no ` tool` suffix at all — both lines
        came from skills/freya-codebase-security-scan/SKILL.md."""
        for phrase in ("Use Grep with appropriate patterns to find vulnerabilities",
                       "Use Read to examine suspicious code in context",
                       "Delegate this using Task per area"):
            with tempfile.TemporaryDirectory() as tmp:
                root = build_root(tmp, skill_md=phrase + "\n")
                self.assertIn("R4", rules_hit(root), phrase)

    def test_bare_capitalised_glob_in_prose_is_flagged(self):
        """`Glob for key patterns` (freya-spec-manager) names the tool with no
        verb and no suffix. Capitalised, Glob and Grep are only ever Claude's
        tools — the shell utilities are lowercase."""
        with tempfile.TemporaryDirectory() as tmp:
            root = build_root(tmp, skill_md="Scans codebase structure (Glob for key patterns)\n")
            self.assertIn("R4", rules_hit(root))

    def test_lowercase_shell_utilities_are_not_flagged(self):
        """`grep`/`glob` lowercase are portable shell vocabulary, not tools."""
        with tempfile.TemporaryDirectory() as tmp:
            root = build_root(tmp, skill_md="Use grep -rn to search; a glob matches many files.\n")
            self.assertNotIn("R4", rules_hit(root))

    def test_ordinary_imperative_english_is_not_flagged(self):
        """The widened rule must stay off ordinary sentences: the tool names are
        also the commonest verbs in English."""
        with tempfile.TemporaryDirectory() as tmp:
            root = build_root(tmp, skill_md=(
                "Read the file, then edit the doc and write the report.\n"
                "Agent Skills is the spec this suite conforms to.\n"
                "Run bash commands through your agent's shell.\n"))
            self.assertNotIn("R4", rules_hit(root))

    def test_claude_only_paths_are_flagged(self):
        """R13. No rule looked at *paths* at all, so the reviewer's evasion
        fixture could end "Reports land in ~/.claude/skills/." and scan clean.
        R1 owns ${CLAUDE_PLUGIN_ROOT}; this is everything else."""
        for phrase in ("Reports land in ~/.claude/skills/.",
                       "Read the manifest from .claude-plugin/plugin.json",
                       "Load `.claude/settings.json` first",
                       "Resolve paths against $CLAUDE_PROJECT_DIR"):
            with tempfile.TemporaryDirectory() as tmp:
                root = build_root(tmp, skill_md=phrase + "\n")
                self.assertIn("R13", rules_hit(root), phrase)

    def test_a_projects_own_claude_md_is_not_flagged(self):
        """Decided exclusion: CLAUDE.md is a file the *user's project* may have,
        alongside README.md and AGENTS.md, not a construct the skill layer
        depends on. Both shipped mentions (docs-manager's root-doc detection and
        its DEVELOPER worker context list) read whatever is there; flagging them
        would make the suite worse on the projects it already handles."""
        with tempfile.TemporaryDirectory() as tmp:
            root = build_root(tmp, skill_md=(
                "Setup instructions (README, AGENTS.md, CLAUDE.md)\n"))
            self.assertNotIn("R13", rules_hit(root))

    def test_claude_only_paths_are_flagged_in_py_too(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = build_root(tmp, script_py='STORE = Path.home() / ".claude" / "skills"\n')
            self.assertIn("R13", rules_hit(root))

    def test_plugin_root_stays_r1_only(self):
        """`${CLAUDE_PLUGIN_ROOT}` contains a CLAUDE_ token; R13 must not
        double-report what R1 already owns."""
        with tempfile.TemporaryDirectory() as tmp:
            root = build_root(tmp, skill_md='python "${CLAUDE_PLUGIN_ROOT}/x.py"\n')
            hits = rules_hit(root)
            self.assertIn("R1", hits)
            self.assertNotIn("R13", hits)

    def test_ordinary_dotfile_prose_is_not_flagged(self):
        """The rule is about Claude's locations, not about dotted paths."""
        with tempfile.TemporaryDirectory() as tmp:
            root = build_root(tmp, skill_md=(
                "Artifacts live in `.freya/`, and AGENTS.md lists every skill.\n"
                "The word claude is not a path.\n"))
            self.assertNotIn("R13", rules_hit(root))

    def test_adapter_argv_in_a_py_file_is_not_flagged(self):
        """Deliberate carve-out: the bare-name prose forms are markdown-only.
        A per-agent adapter has to name that agent's own tools in an argv —
        `--allowedTools "Read Grep Glob"` is data handed to the `claude` binary,
        not an instruction to a model — and that is the one place a Claude tool
        name is correct by construction."""
        with tempfile.TemporaryDirectory() as tmp:
            root = build_root(tmp, script_py='ARGV = ["--allowedTools", "Read Grep Glob"]\n')
            self.assertNotIn("R4", rules_hit(root))

    def test_extra_frontmatter_key_is_flagged(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = build_root(
                tmp, skill_md="---\nname: demo\ndescription: d\nextra-field: yes\n---\n"
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

    def test_bare_plugin_root_is_flagged(self):
        """R1 must catch the bare form ($CLAUDE_PLUGIN_ROOT, no braces), not just braced."""
        with tempfile.TemporaryDirectory() as tmp:
            root = build_root(tmp, skill_md='python "$CLAUDE_PLUGIN_ROOT/skills/x/scripts/y.py" --go\n')
            self.assertIn("R1", rules_hit(root))

    def test_bare_plugin_root_has_no_exemption_left(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = build_root(
                tmp,
                skill_md='Run `scriptPath: "$CLAUDE_PLUGIN_ROOT/workflows/codebase-security-audit.js"`.\n',
            )
            self.assertIn("R1", rules_hit(root))

    def test_bare_and_braced_plugin_root_both_count(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = build_root(tmp, skill_md="${CLAUDE_PLUGIN_ROOT} and $CLAUDE_PLUGIN_ROOT\n")
            self.assertEqual(rules_hit(root).count("R1"), 2)

    def test_loop_slash_command_is_flagged(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = build_root(tmp, skill_md="Set up /loop 10m to poll for updates.\n")
            self.assertIn("R6", rules_hit(root))

    def test_loop_inside_path_is_not_flagged(self):
        """R6 must not fire on a path segment like `workflows/loop.js`."""
        with tempfile.TemporaryDirectory() as tmp:
            root = build_root(tmp, skill_md="The engine lives at scripts/loop/runner.py.\n")
            self.assertNotIn("R6", rules_hit(root))

    def test_loop_prefix_of_longer_word_is_not_flagged(self):
        """R6 must not fire on `/loopback` — a different, longer token."""
        with tempfile.TemporaryDirectory() as tmp:
            root = build_root(tmp, skill_md="Some code paths use /loopback interfaces.\n")
            self.assertNotIn("R6", rules_hit(root))

    def test_plan_mode_prose_is_flagged(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = build_root(tmp, skill_md="Never rely on plan mode for this step.\n")
            self.assertIn("R7", rules_hit(root))

    def test_plan_mode_prose_is_case_insensitive(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = build_root(tmp, skill_md="Avoid Plan Mode; present a plan for approval instead.\n")
            self.assertIn("R7", rules_hit(root))

    def test_planning_mode_is_not_flagged(self):
        """R7 matches the exact phrase 'plan mode', not 'planning mode'."""
        with tempfile.TemporaryDirectory() as tmp:
            root = build_root(tmp, skill_md="Use the planning mode of your editor.\n")
            self.assertNotIn("R7", rules_hit(root))

    def test_enterplanmode_token_triggers_r4_not_r7(self):
        """EnterPlanMode (no space) is the R4 token form; R7 is the prose form only."""
        with tempfile.TemporaryDirectory() as tmp:
            root = build_root(tmp, skill_md="Use EnterPlanMode tool to create a plan.\n")
            hits = rules_hit(root)
            self.assertIn("R4", hits)
            self.assertNotIn("R7", hits)

    def test_standard_optional_frontmatter_is_allowed(self):
        """license, metadata, compatibility and allowed-tools are in the spec."""
        with tempfile.TemporaryDirectory() as tmp:
            root = build_root(
                tmp,
                skill_md=(
                    "---\nname: demo\ndescription: d\nlicense: MIT\n"
                    "compatibility: Requires git\nallowed-tools: Read\nmetadata:\n  author: x\n---\n"
                ),
            )
            self.assertNotIn("R5", rules_hit(root))

    def test_unknown_frontmatter_key_is_still_flagged(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = build_root(tmp, skill_md="---\nname: demo\ndescription: d\ninvented: x\n---\n")
            self.assertIn("R5", rules_hit(root))


class NameMatchesDirectoryTest(unittest.TestCase):
    """The Agent Skills spec requires `name` to equal the parent directory name."""

    def test_matching_name_is_accepted(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = build_root(tmp, skill_md="---\nname: demo\ndescription: d\n---\n")
            self.assertNotIn("R8", rules_hit(root))

    def test_mismatched_name_is_flagged(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = build_root(tmp, skill_md="---\nname: not-demo\ndescription: d\n---\n")
            self.assertIn("R8", rules_hit(root))

    def test_quoted_name_matches_the_directory(self):
        """YAML permits `name: "demo"`; the quotes must not read as a mismatch."""
        with tempfile.TemporaryDirectory() as tmp:
            root = build_root(tmp, skill_md='---\nname: "demo"\ndescription: d\n---\n')
            self.assertNotIn("R8", rules_hit(root))

    def test_single_quoted_name_matches_the_directory(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = build_root(tmp, skill_md="---\nname: 'demo'\ndescription: d\n---\n")
            self.assertNotIn("R8", rules_hit(root))

    def test_missing_name_is_flagged(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = build_root(tmp, skill_md="---\ndescription: d\n---\n")
            self.assertIn("R8", rules_hit(root))

    def test_reference_file_is_not_checked_for_name(self):
        """Only SKILL.md carries the name contract; references/*.md must not trip R8."""
        with tempfile.TemporaryDirectory() as tmp:
            root = build_root(tmp, reference_md="Some notes.\n")
            self.assertNotIn("R8", rules_hit(root))

    def test_block_scalar_name_matching_directory_is_accepted(self):
        """A `name: |` block scalar whose content equals the directory name is a
        well-formed name, not a mismatch — the marker itself is not the value."""
        with tempfile.TemporaryDirectory() as tmp:
            root = build_root(tmp, skill_md="---\nname: |\n  demo\ndescription: d\n---\n")
            self.assertNotIn("R8", rules_hit(root))

    def test_block_scalar_name_mismatching_directory_is_flagged(self):
        """The same block-scalar form still flags a genuine mismatch."""
        with tempfile.TemporaryDirectory() as tmp:
            root = build_root(tmp, skill_md="---\nname: |\n  not-demo\ndescription: d\n---\n")
            self.assertIn("R8", rules_hit(root))


class RequiredFrontmatterTest(unittest.TestCase):
    """R11/R12 — the two halves of the spec's frontmatter contract nothing checked.

    R5 policed which keys were *allowed*; nothing asked whether the two required
    ones were there, or whether `name` was spelled the way the spec permits.
    """

    def test_missing_description_is_flagged(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = build_root(tmp, skill_md="---\nname: demo\n---\n\nBody.\n")
            self.assertIn("R11", rules_hit(root))

    def test_empty_description_is_flagged(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = build_root(tmp, skill_md="---\nname: demo\ndescription:\n---\n\nBody.\n")
            self.assertIn("R11", rules_hit(root))

    def test_a_present_description_is_accepted(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = build_root(tmp, skill_md="---\nname: demo\ndescription: d\n---\n")
            self.assertNotIn("R11", rules_hit(root))

    def test_a_name_outside_the_spec_grammar_is_flagged(self):
        """The spec's `name` is lowercase letters, digits and single hyphens."""
        for bad in ("Freya_Demo--X", "Demo", "demo_skill", "demo--skill", "-demo", "demo-"):
            with tempfile.TemporaryDirectory() as tmp:
                root = build_root(
                    tmp, skill_dir=bad, skill_md=f"---\nname: {bad}\ndescription: d\n---\n"
                )
                self.assertIn("R12", rules_hit(root), bad)

    def test_a_conforming_name_is_accepted(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = build_root(
                tmp, skill_dir="freya-code-graph",
                skill_md="---\nname: freya-code-graph\ndescription: d\n---\n",
            )
            self.assertEqual(rules_hit(root), [])

    def test_the_evasion_fixture_is_no_longer_conformant(self):
        """Reported verbatim: a directory named Freya_Demo--X with an empty
        description printed "skill layer is conformant." and exited 0."""
        with tempfile.TemporaryDirectory() as tmp:
            root = build_root(
                tmp, skill_dir="Freya_Demo--X",
                skill_md="---\nname: Freya_Demo--X\ndescription:\n---\n\nBody.\n",
            )
            code, _, err = run_main(["--root", str(root)])
            self.assertEqual(code, 1)
            self.assertIn("R11", err)
            self.assertIn("R12", err)

    def test_reference_file_carries_no_frontmatter_contract(self):
        """Only SKILL.md must declare name/description; references/*.md must not."""
        with tempfile.TemporaryDirectory() as tmp:
            root = build_root(tmp, reference_md="Some notes.\n")
            hits = rules_hit(root)
            self.assertNotIn("R11", hits)
            self.assertNotIn("R12", hits)


class PythonFileScanTest(unittest.TestCase):
    """skills/**/*.py is now scanned too (R1/R2 substring checks; R4/R6/R7 prose
    checks ride along since they're plain per-line checks; R3/R5 stay markdown-only)."""

    def test_plugin_root_in_py_is_flagged(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = build_root(tmp, script_py='ROOT = "${CLAUDE_PLUGIN_ROOT}/skills/x"\n')
            self.assertIn("R1", rules_hit(root))

    def test_slash_ref_in_py_is_flagged(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = build_root(tmp, script_py='MSG = "/freya-devkit:status"\n')
            self.assertIn("R2", rules_hit(root))

    def test_loop_in_py_is_flagged(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = build_root(tmp, script_py="# schedule this with /loop 10m\n")
            self.assertIn("R6", rules_hit(root))

    def test_plan_mode_in_py_is_flagged(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = build_root(tmp, script_py="# do not rely on plan mode here\n")
            self.assertIn("R7", rules_hit(root))

    def test_tool_name_in_py_is_flagged(self):
        """R4 is a plain per-line prose check, so it rides along onto .py files too."""
        with tempfile.TemporaryDirectory() as tmp:
            root = build_root(tmp, script_py="# Use the Write tool to create files\n")
            self.assertIn("R4", rules_hit(root))

    def test_freya_command_in_py_does_not_trigger_r3(self):
        """R3 is markdown-only (code-span based) — a bad `freya` mention in a .py
        comment must not be flagged, unlike the same text in a SKILL.md."""
        with tempfile.TemporaryDirectory() as tmp:
            root = build_root(tmp, script_py="# Run `freya bogus-command --now`\n")
            self.assertNotIn("R3", rules_hit(root))

    def test_frontmatter_like_block_in_py_does_not_trigger_r5(self):
        """R5 is markdown-only (YAML frontmatter, anchored at line 1 == '---') — a
        .py file whose content happens to satisfy that same shape must not be
        flagged, since frontmatter is not a concept that applies to a .py file."""
        with tempfile.TemporaryDirectory() as tmp:
            root = build_root(
                tmp, script_py="---\nname: demo\ncompatibility: Requires Agent\n---\n"
            )
            self.assertNotIn("R5", rules_hit(root))

    def test_clean_py_file_is_not_flagged(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = build_root(tmp, script_py='def main():\n    print("hello")\n')
            self.assertEqual(rules_hit(root), [])

    def test_python_violation_surfaces_through_main(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = build_root(tmp, script_py='MSG = "/freya-devkit:status"\n')
            code, out, err = run_main(["--root", str(root)])
            self.assertEqual(code, 1)
            self.assertIn("R2", out)
            self.assertIn("tool.py", out)
            self.assertIn("1 violation(s).", err)


class FanoutTest(unittest.TestCase):
    """R9: a skill that fans out must say what to do without subagents."""

    SENTINEL = (
        "Run them in parallel if your agent supports subagents; otherwise "
        "run them one at a time.\n"
    )

    def _skill(self, body):
        return "---\nname: demo\ndescription: d\n---\n\n" + body

    def test_unconditional_parallel_imperative_is_flagged(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = build_root(tmp, skill_md=self._skill(
                "The coordinator spawns worker agents IN PARALLEL for each doc type.\n"))
            self.assertIn("R9", rules_hit(root))

    def test_sentinel_satisfies_the_whole_file(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = build_root(tmp, skill_md=self._skill(
                "Spawn discovery agents for each area.\n"
                "Launch the following specialized agents in parallel.\n" + self.SENTINEL))
            self.assertNotIn("R9", rules_hit(root))

    def test_flagged_once_per_file_not_per_mention(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = build_root(tmp, skill_md=self._skill(
                "Spawn worker agents.\nLaunch parallel agents.\nRun them in parallel.\n"))
            self.assertEqual(rules_hit(root).count("R9"), 1)

    def test_descriptive_parallel_mention_is_flagged(self):
        """`description:` advertising parallel subagents is a portability claim too."""
        with tempfile.TemporaryDirectory() as tmp:
            root = build_root(
                tmp,
                skill_md="---\nname: demo\ndescription: Audits a codebase using parallel subagents.\n---\n",
            )
            self.assertIn("R9", rules_hit(root))

    def test_unrelated_fanout_word_is_not_flagged(self):
        """wrap-up says 're-inference fan-out'; spec-manager says 'dispatch key'."""
        with tempfile.TemporaryDirectory() as tmp:
            root = build_root(tmp, skill_md=self._skill(
                "A change never triggers an unbounded re-inference fan-out.\n"
                "A typo in the runner's dispatch key fails loud.\n"))
            self.assertNotIn("R9", rules_hit(root))

    def test_spawn_followed_by_a_paren_is_not_an_instruction(self):
        """`spawn\\(` doesn't match FANOUT because `spawn` has no whitespace before
        the next character — not because R9 skips fenced code blocks (it doesn't;
        unlike R3 it never calls code_spans())."""
        with tempfile.TemporaryDirectory() as tmp:
            root = build_root(tmp, skill_md=self._skill(
                "Detection pattern:\n```\nspawn\\([^)]*\\+\n```\n"))
            self.assertNotIn("R9", rules_hit(root))

    def test_reference_file_is_not_checked(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = build_root(tmp, reference_md="Spawn worker agents in parallel.\n")
            self.assertNotIn("R9", rules_hit(root))

    # -- Widened FANOUT coverage (final review, Phase 4) --------------------

    def test_article_between_verb_and_noun_is_flagged(self):
        """One indefinite article away from what this phase removed."""
        with tempfile.TemporaryDirectory() as tmp:
            root = build_root(tmp, skill_md=self._skill(
                "Spawn a worker for each doc type.\n"))
            self.assertIn("R9", rules_hit(root))

    def test_launch_with_per_article_is_flagged(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = build_root(tmp, skill_md=self._skill(
                "Launch a subagent per category.\n"))
            self.assertIn("R9", rules_hit(root))

    def test_concurrently_is_flagged(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = build_root(tmp, skill_md=self._skill(
                "Run the 12 workers concurrently.\n"))
            self.assertIn("R9", rules_hit(root))

    def test_simultaneously_is_flagged(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = build_root(tmp, skill_md=self._skill(
                "Run all six scans simultaneously.\n"))
            self.assertIn("R9", rules_hit(root))

    def test_delegate_to_a_subagent_is_flagged(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = build_root(tmp, skill_md=self._skill(
                "Delegate each area to a subagent.\n"))
            self.assertIn("R9", rules_hit(root))

    def test_create_n_subagents_is_flagged(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = build_root(tmp, skill_md=self._skill(
                "Create 12 subagents, one per doc type.\n"))
            self.assertIn("R9", rules_hit(root))

    def test_dispatch_one_task_per_area_is_flagged(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = build_root(tmp, skill_md=self._skill(
                "Dispatch one task per area.\n"))
            self.assertIn("R9", rules_hit(root))

    def test_parallelized_is_flagged(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = build_root(tmp, skill_md=self._skill(
                "Cheap by design: a fixed 2-3 passes per finding, parallelized "
                "across findings.\n"))
            self.assertIn("R9", rules_hit(root))

    def test_parallelised_british_spelling_is_flagged(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = build_root(tmp, skill_md=self._skill(
                "Findings are parallelised across the run.\n"))
            self.assertIn("R9", rules_hit(root))

    def test_parallel_processing_is_flagged(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = build_root(tmp, skill_md=self._skill(
                "Group affected areas by category for parallel processing.\n"))
            self.assertIn("R9", rules_hit(root))

    def test_parallel_validation_is_flagged(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = build_root(tmp, skill_md=self._skill(
                "Parallel validation - validate multiple findings when possible.\n"))
            self.assertIn("R9", rules_hit(root))

    def test_parallel_pass_is_flagged(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = build_root(tmp, skill_md=self._skill(
                "`scan` does one parallel pass of the 6 finders.\n"))
            self.assertIn("R9", rules_hit(root))

    def test_sentinel_without_a_sequential_fallback_is_flagged(self):
        """The sentinel says *when* to fan out and never says what to do instead.
        Phase 7's update-mode fan-outs shipped with no scheduling guidance at all
        because one sentinel anywhere in the file satisfied the whole rule."""
        with tempfile.TemporaryDirectory() as tmp:
            root = build_root(tmp, skill_md=self._skill(
                "Spawn worker agents for each area.\n"
                "Run them in parallel if your agent supports subagents.\n"))
            self.assertIn("R9", rules_hit(root))

    def test_sequentially_counts_as_the_fallback(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = build_root(tmp, skill_md=self._skill(
                "Spawn worker agents for each area.\n"
                "Run them in parallel if your agent supports subagents; "
                "otherwise run them sequentially.\n"))
            self.assertNotIn("R9", rules_hit(root))

    def test_a_fallback_without_the_sentinel_is_still_flagged(self):
        """Both halves are required — a bare "one at a time" never says the
        parallel path is conditional on the agent having subagents."""
        with tempfile.TemporaryDirectory() as tmp:
            root = build_root(tmp, skill_md=self._skill(
                "Spawn worker agents for each area, or run them one at a time.\n"))
            self.assertIn("R9", rules_hit(root))

    def test_capitalized_sentinel_is_recognized(self):
        """A sentence-initial capital ('If your agent supports subagents…') is
        perfectly compliant; the check must compare against text.lower(), not the
        literal (lowercase) SUBAGENT_SENTINEL against un-lowered text."""
        with tempfile.TemporaryDirectory() as tmp:
            root = build_root(tmp, skill_md=self._skill(
                "Spawn worker agents for each area.\n"
                "If your agent supports subagents, run them in parallel; "
                "otherwise run them one at a time.\n"))
            self.assertNotIn("R9", rules_hit(root))


class MainTest(unittest.TestCase):
    def test_clean_tree_exits_zero(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = build_root(tmp)
            code, out, _ = run_main(["--root", str(root)])
            self.assertEqual(code, 0)
            self.assertIn("conformant", out)

    def test_violation_exits_one(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = build_root(
                tmp, skill_md="---\nname: demo\ndescription: d\n---\n\nSee /freya-devkit:code-graph.\n"
            )
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


class FrontmatterValueTest(unittest.TestCase):
    def test_reads_an_inline_value(self):
        lines = ["---", "name: freya-status", "description: short", "---"]
        self.assertEqual(csc.frontmatter_value(lines, "description"),
                         "short")

    def test_reads_a_block_scalar(self):
        lines = ["---", "name: freya-status", "description: |",
                 "  First line.", "  Second line.", "---", "body"]
        self.assertEqual(csc.frontmatter_value(lines, "description"),
                         "First line.\nSecond line.")

    def test_a_block_scalar_stops_at_the_next_key(self):
        lines = ["---", "description: |", "  Only this.", "license: MIT", "---"]
        self.assertEqual(csc.frontmatter_value(lines, "description"),
                         "Only this.")

    def test_strips_one_layer_of_quoting(self):
        lines = ["---", 'name: "freya-status"', "---"]
        self.assertEqual(csc.frontmatter_value(lines, "name"),
                         "freya-status")

    def test_an_absent_key_is_none(self):
        lines = ["---", "name: freya-status", "---"]
        self.assertIsNone(csc.frontmatter_value(lines, "description"))

    def test_a_block_scalar_name_reads_as_the_name_not_the_marker(self):
        """Decided behaviour: `name: |` followed by indented content resolves to
        that content, the way a real YAML parser reads it — not to the literal
        "|" marker the old inline-only reader returned."""
        lines = ["---", "name: |", "  freya-status", "---"]
        self.assertEqual(csc.frontmatter_name(lines), "freya-status")

    def test_folds_a_plain_multi_line_scalar(self):
        """An unquoted value continues onto every following indented line — YAML
        folds them into one scalar. Reading only the first line is what let a
        1774-character description measure 53 and walk past R10."""
        lines = ["---", "description: First line", "  second line", "  third line", "---"]
        self.assertEqual(csc.frontmatter_value(lines, "description"),
                         "First line second line third line")

    def test_a_plain_multi_line_scalar_stops_at_the_next_key(self):
        lines = ["---", "description: First", "  more", "license: MIT", "---"]
        self.assertEqual(csc.frontmatter_value(lines, "description"), "First more")

    def test_a_single_line_plain_scalar_is_unchanged_by_folding(self):
        lines = ["---", "name: demo", "description: short", "---"]
        self.assertEqual(csc.frontmatter_value(lines, "name"), "demo")

    def test_the_real_skills_all_have_a_readable_description(self):
        root = Path(__file__).resolve().parents[1]
        for skill in sorted((root / "skills").iterdir()):
            md = skill / "SKILL.md"
            if not md.is_file():
                continue
            lines = md.read_text(encoding="utf-8").splitlines()
            value = csc.frontmatter_value(lines, "description")
            self.assertTrue(value and value not in ("|", ">"), f"{skill.name}: {value!r}")


class FrontmatterLengthTest(unittest.TestCase):
    """R10 — the rule phase 6 validation had to discover the hard way.

    GitHub Copilot silently omitted a skill whose description ran to 1251
    characters; Claude Code loaded the same skill without complaint. It was
    installed, linked, and invisible, with no error on either side.
    """

    def _skill(self, description):
        return f"---\nname: demo\ndescription: |\n  {description}\n---\n\nBody.\n"

    def test_a_description_over_the_limit_is_caught(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = build_root(tmp, skill_md=self._skill("x" * 1200))
            self.assertIn("R10", rules_hit(root))

    def test_a_description_at_the_limit_passes(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = build_root(tmp, skill_md=self._skill("x" * 1024))
            self.assertNotIn("R10", rules_hit(root))

    def test_the_violation_names_the_key_and_both_numbers(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = build_root(tmp, skill_md=self._skill("x" * 1200))
            excerpt = [v[3] for v in csc.scan(Path(root)) if v[2] == "R10"][0]
            self.assertIn("description", excerpt)
            self.assertIn("1200", excerpt)
            self.assertIn("1024", excerpt)

    def test_an_over_long_compatibility_value_is_caught_too(self):
        with tempfile.TemporaryDirectory() as tmp:
            md = f"---\nname: demo\ndescription: d\ncompatibility: {'y' * 600}\n---\n\nBody.\n"
            root = build_root(tmp, skill_md=md)
            self.assertIn("R10", rules_hit(root))

    def test_every_real_skill_is_within_the_limits(self):
        root = Path(__file__).resolve().parents[1]
        offenders = [(v[0], v[3]) for v in csc.scan(root) if v[2] == "R10"]
        self.assertEqual(offenders, [], f"R10 violations in the shipped suite: {offenders}")

    def test_a_plain_multi_line_description_is_measured_whole(self):
        """The spelling R10 was blind to: no `|` marker at all, just an unquoted
        value continued over indented lines — which is what a description reads
        like after an editor rewraps it. Measured before this was fixed: 1774
        real characters, 53 seen, "skill layer is conformant.", exit 0."""
        chunk = "x" * 100
        body = "\n".join("  " + chunk for _ in range(17))
        md = f"---\nname: demo\ndescription: {chunk}\n{body}\n---\n\nBody.\n"
        with tempfile.TemporaryDirectory() as tmp:
            root = build_root(tmp, skill_md=md)
            self.assertIn("R10", rules_hit(root))

    def test_a_plain_multi_line_description_under_the_limit_still_passes(self):
        """Folding must not manufacture violations: three short lines are three
        short lines, not a limit breach."""
        md = "---\nname: demo\ndescription: First line\n  second line\n---\n\nBody.\n"
        with tempfile.TemporaryDirectory() as tmp:
            root = build_root(tmp, skill_md=md)
            self.assertEqual(rules_hit(root), [])


class ShippedTreeTest(unittest.TestCase):
    """The guarantee the checker exists to make, asserted where pytest sees it.

    Every other test builds a fixture tree; none of them looked at the suite
    that actually ships, so the whole "runs on any agent" invariant rested on
    someone remembering to run `python3 bin/check_skill_conformance.py` by hand
    (CONTRIBUTING.md asks for it; no CI enforces it).
    """

    def test_the_shipped_skill_layer_is_conformant(self):
        root = Path(__file__).resolve().parents[1]
        violations = csc.scan(root)
        detail = "\n".join(f"{rel}:{line}: {rule}: {excerpt}"
                           for rel, line, rule, excerpt in violations)
        self.assertEqual(violations, [], f"skills/ is not conformant:\n{detail}")


# Appended after ShippedTreeTest rather than filed with the other rule classes:
# four places cite this file by line (CONTRIBUTING.md:142, DEVELOPER.md:65,
# TESTING.md:156 and :390), and adding at the end is the only edit that leaves
# what they point at where it is. Move it up once those are repointed.
class RedactionTest(unittest.TestCase):
    """R14: a skill that reads secret material must say what may be written down.

    SEC-009 and SEC-017. The security report's evidence block and the
    docs-manager ENVIRONMENT worker both take a real secret as input and produce
    a file `freya-wrap-up` commits, and neither said not to copy the value
    across. Neither can call a redaction helper — they are prose handed to an
    agent — so the rule *is* the sentence, and this is the gate on the sentence
    being there.
    """

    CLAUSE = (
        "Never write a real secret value into the doc; the placeholder is "
        "`[REDACTED]`.\n"
    )

    def _skill(self, body):
        return "---\nname: demo\ndescription: d\n---\n\n" + body

    def test_reading_dot_env_without_the_clause_is_flagged(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = build_root(tmp, skill_md=self._skill(
                "**Context to gather:**\n- .env.example files\n"))
            self.assertIn("R14", rules_hit(root))

    def test_secrets_management_without_the_clause_is_flagged(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = build_root(tmp, skill_md=self._skill(
                "- Secrets management approach\n"))
            self.assertIn("R14", rules_hit(root))

    def test_hardcoded_credentials_without_the_clause_is_flagged(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = build_root(tmp, skill_md=self._skill(
                "Scan for hardcoded credentials, API keys and private keys.\n"))
            self.assertIn("R14", rules_hit(root))

    def test_the_clause_satisfies_the_whole_file(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = build_root(tmp, skill_md=self._skill(
                "- .env.example files\n- Secrets management approach\n" + self.CLAUSE))
            self.assertNotIn("R14", rules_hit(root))

    def test_sentinel_without_a_placeholder_is_flagged(self):
        """Half the rule. "Never write a real secret value" leaves the writer to
        invent the alternative, and an evidence block left empty loses the
        finding it was evidence for."""
        with tempfile.TemporaryDirectory() as tmp:
            root = build_root(tmp, skill_md=self._skill(
                "- .env.example files\nNever write a real secret value here.\n"))
            self.assertIn("R14", rules_hit(root))

    def test_placeholder_without_the_sentinel_is_flagged(self):
        """The other half. Showing `[REDACTED]` in a table never says the value
        is forbidden — it reads as one formatting option among several."""
        with tempfile.TemporaryDirectory() as tmp:
            root = build_root(tmp, skill_md=self._skill(
                "- .env.example files\nExample column: `[REDACTED]`.\n"))
            self.assertIn("R14", rules_hit(root))

    def test_prose_saying_a_value_is_redacted_is_not_the_placeholder(self):
        """A delimiter is required: what has to appear is the token the writer
        types, not a sentence about redaction in the abstract."""
        with tempfile.TemporaryDirectory() as tmp:
            root = build_root(tmp, skill_md=self._skill(
                "- .env.example files\n"
                "Never write a real secret value; make sure it is redacted.\n"))
            self.assertIn("R14", rules_hit(root))

    def test_angle_bracket_fingerprint_counts_as_the_placeholder(self):
        """The security report writes a fingerprint, not a fixed token; both
        writers must be able to satisfy the same rule in their own shape."""
        with tempfile.TemporaryDirectory() as tmp:
            root = build_root(tmp, skill_md=self._skill(
                "Scan for exposed secrets.\n"
                "Never write a real secret value — emit "
                "`<redacted len=44 prefix='sk-p' sha256=9f2c1ab4>`.\n"))
            self.assertNotIn("R14", rules_hit(root))

    def test_capitalized_sentinel_is_recognized(self):
        """Same trap R9 had: the sentinel is lowercase and real prose starts a
        sentence with it, so the comparison must be against text.lower()."""
        with tempfile.TemporaryDirectory() as tmp:
            root = build_root(tmp, skill_md=self._skill(
                "- .env.example files\n"
                "NEVER WRITE A REAL SECRET VALUE. Write `{REDACTED}` instead.\n"))
            self.assertNotIn("R14", rules_hit(root))

    def test_flagged_once_per_file_not_per_mention(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = build_root(tmp, skill_md=self._skill(
                "- .env.example files\n- Secrets management approach\n"
                "- Exposed secrets in code\n- API keys\n"))
            self.assertEqual(rules_hit(root).count("R14"), 1)

    #: Files that mention secret material and are still out of scope, with the
    #: real thing each one stands for. One test over both members rather than
    #: two: the `.py` member has no single-point mutant that kills it — a `.py`
    #: file is guarded twice, by the markdown-only return *and* by the
    #: `SKILL.md` name gate, so hoisting the R14 block above the return leaves
    #: it green (measured 2026-08-23: 139 pass). A redundancy guard, and filing it
    #: as a member of the property it belongs to says so instead of letting it
    #: pose as an independently verified test.
    OUT_OF_SCOPE = (
        ("reference_md", "| Variable | Example |\n|---|---|\n"
                         "| `DATABASE_URL` | read it from `.env.example` |\n"),
        ("script_py", 'EXTENSIONS = (".sh", ".env", ".gitignore")\n'
                      'FIXTURE = ".env.local"\n'),
    )

    def test_only_skill_md_is_checked(self):
        """R14 reads `SKILL.md` and nothing else under a skill directory.

        `references/templates.md` trips the rule on 18 lines — 15 of them a
        `.env` mention, 17 mentions in all — and every one of the 18 is
        scaffolding inside a fenced template, instructing nobody. The `.py`
        corpus is the same story in fewer places: measured at `f61cfbd`, three
        hits under `skills/**/*.py`, all of them names (a `.env` entry in an
        extension list, a `.env.local` graph fixture and the comment about it).
        SKILL.md is the file the Agent Skills spec guarantees a host loads; it
        is also the only one worth policing.
        """
        for kind, body in self.OUT_OF_SCOPE:
            with self.subTest(kind=kind), tempfile.TemporaryDirectory() as tmp:
                root = build_root(tmp, **{kind: body})
                self.assertNotIn("R14", rules_hit(root))

    def test_ordinary_token_and_password_prose_is_not_flagged(self):
        """The three sentences that made a bare `token`/`password` keyword
        unusable: two skills price a fan-out in LLM tokens, the resolver
        describes token validation, and spec-manager documents a password
        decision. None of them reads a secret."""
        with tempfile.TemporaryDirectory() as tmp:
            root = build_root(tmp, skill_md=self._skill(
                "Costs roughly 7x the tokens of a sequential pass.\n"
                "SEC-003: auth bypass in token validation.\n"
                "### No Password Fallback\n"
                "We do not offer password authentication as a fallback.\n"))
            self.assertNotIn("R14", rules_hit(root))

    # --- the rule has to be in the slot, not only in the file ---------------
    #
    # SEC-009 in one line: the report template's evidence block took a bare
    # `{code snippet}`, and for a Secrets finding the vulnerable code *is* the
    # credential. A `### Redaction` section further down the same file is not a
    # fix for that, it is the excuse — so this clause does not consult the
    # file-level `stated` check at all.

    SECTION = (
        "Scan for exposed secrets in code.\n\n"
        "Never write a real secret value; write `[REDACTED]` instead.\n\n"
    )

    def test_a_bare_copied_source_slot_is_flagged(self):
        """The regression itself: the file states the rule in full and the slot
        the writer types into still says nothing."""
        with tempfile.TemporaryDirectory() as tmp:
            root = build_root(tmp, skill_md=self._skill(
                self.SECTION + "**Vulnerable Code:**\n{code snippet}\n"))
            self.assertIn("R14", rules_hit(root))

    def test_a_slot_carrying_the_placeholder_is_accepted(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = build_root(tmp, skill_md=self._skill(
                self.SECTION + "**Vulnerable Code:**\n"
                "{code snippet — swap the literal for "
                "<redacted len=44 prefix='sk-p' sha256=9f2c1ab4>}\n"))
            self.assertNotIn("R14", rules_hit(root))

    def test_a_slot_carrying_the_sentinel_is_accepted(self):
        """Either half is enough *in the slot*: a writer who is told not to
        write the value has been told the thing that matters, and the file-level
        check is what makes sure the placeholder is defined somewhere."""
        with tempfile.TemporaryDirectory() as tmp:
            root = build_root(tmp, skill_md=self._skill(
                self.SECTION + "**Vulnerable Code:**\n"
                "{code snippet; never write a real secret value}\n"))
            self.assertNotIn("R14", rules_hit(root))

    def test_a_slot_with_nested_braces_is_still_a_slot(self):
        """The remediation for the real one spells the fingerprint out as
        `<redacted len={n} ...>`, nesting braces one deep. A pattern that stops
        at the first inner brace would stop checking the slot the moment
        somebody fixed it — a gate that only ever guards the past."""
        with tempfile.TemporaryDirectory() as tmp:
            root = build_root(tmp, skill_md=self._skill(
                self.SECTION + "{code snippet, {language}-tagged}\n"))
            self.assertIn("R14", rules_hit(root))

    def test_a_slot_in_a_skill_that_reads_no_secrets_is_not_flagged(self):
        """`freya-code-graph` has bare `{...}` lines too, and no worker of its
        ever looks at a credential. The trigger is the same for both halves of
        R14 or the rule stops being about secrets."""
        with tempfile.TemporaryDirectory() as tmp:
            root = build_root(tmp, skill_md=self._skill(
                "**Vulnerable Code:**\n{code snippet}\n"))
            self.assertNotIn("R14", rules_hit(root))

    def test_a_describe_it_slot_is_not_a_copied_source_slot(self):
        """32 of the 33 bare slots in the shipped corpus take no verbatim source
        — a description, a command, a template branch, JSON in an example. There
        is nothing to redact in any of them; demanding a notice is noise."""
        with tempfile.TemporaryDirectory() as tmp:
            root = build_root(tmp, skill_md=self._skill(
                self.SECTION + "{What the vulnerability is and why it matters}\n"
                "{For each finding that matches a spec:}\n"))
            self.assertNotIn("R14", rules_hit(root))

    def test_every_unguarded_slot_is_reported_not_just_the_first(self):
        """Unlike the file-level clause, one sentence does not fix these: each
        slot is its own edit, so each one has to be named."""
        with tempfile.TemporaryDirectory() as tmp:
            root = build_root(tmp, skill_md=self._skill(
                self.SECTION + "{code snippet}\n\n{the secret literal}\n"))
            self.assertEqual(rules_hit(root).count("R14"), 2)


# Last, not mid-file: this used to sit above FrontmatterLengthTest, so running
# the file directly (rather than through `-m unittest` or pytest) executed
# unittest.main() before that class existed and silently skipped all five of
# its tests — every one of R10, including the regression guard for the phase-6
# defect the rule was written for. 86 tests reported, 91 collected.
if __name__ == "__main__":
    unittest.main()
