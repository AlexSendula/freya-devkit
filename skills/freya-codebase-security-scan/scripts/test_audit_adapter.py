#!/usr/bin/env python3
"""Unit tests for the per-agent headless adapter.

Nothing here executes an agent: argv construction and stdout parsing are pure,
and detection is tested with shutil.which patched.
"""

import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import audit_adapter

#: The absolute path `main()` resolves the agent CLI to before any worker is
#: built. Every `build_argv` below has to be given one: argv[0] is what the
#: operating system is asked to start, and `_guard` refuses anything that is
#: not already absolute, so a test passing the bare name would be exercising
#: the refusal rather than the argv shape it is named for.
PROGRAM = "/opt/agents/cli"


class ArgvTest(unittest.TestCase):
    def test_claude_argv_shape(self):
        argv = audit_adapter.ADAPTERS["claude"].build_argv("find bugs", program=PROGRAM)
        self.assertEqual(argv[0], PROGRAM)
        self.assertIn("-p", argv)
        self.assertIn("find bugs", argv)
        self.assertIn("--output-format", argv)
        self.assertIn("json", argv)

    def test_copilot_argv_shape(self):
        argv = audit_adapter.ADAPTERS["copilot"].build_argv("find bugs", program=PROGRAM)
        self.assertEqual(argv[0], PROGRAM)
        self.assertIn("-p", argv)
        self.assertIn("find bugs", argv)
        self.assertIn("-s", argv)
        self.assertIn("--no-ask-user", argv)

    def test_model_is_passed_through_when_given(self):
        for name in audit_adapter.ADAPTERS:
            argv = audit_adapter.ADAPTERS[name].build_argv(
                "x", model="cheap-1", program=PROGRAM)
            self.assertIn("--model", argv, name)
            self.assertIn("cheap-1", argv, name)

    def test_model_is_absent_when_not_given(self):
        for name in audit_adapter.ADAPTERS:
            argv = audit_adapter.ADAPTERS[name].build_argv("x", program=PROGRAM)
            self.assertNotIn("--model", argv, name)


class ReadOnlyTest(unittest.TestCase):
    """The no-writes boundary. The spike proved --allow-all-tools is bypassable
    via the shell even with --deny-tool=write, so an allowlist excluding shell
    is the only configuration that holds."""

    BLANKET = ("--allow-all-tools", "--allow-all", "--allow-all-paths", "--allow-all-urls")

    def test_no_adapter_ever_grants_blanket_access(self):
        for name, adapter in audit_adapter.ADAPTERS.items():
            argv = adapter.build_argv("x", model="m", program=PROGRAM)
            for flag in self.BLANKET:
                self.assertNotIn(flag, argv, f"{name} must never pass {flag}")

    def test_claude_restricts_tools_to_read_only(self):
        argv = audit_adapter.ADAPTERS["claude"].build_argv("x", program=PROGRAM)
        joined = " ".join(argv)
        self.assertIn("--allowedTools", joined)
        self.assertIn("Read", joined)
        self.assertNotIn("Write", " ".join(
            argv[argv.index("--allowedTools") + 1:argv.index("--allowedTools") + 2]))

    def test_copilot_denies_shell_not_just_write(self):
        """deny beats allow for the write *tool*, not for writes through the shell."""
        joined = " ".join(audit_adapter.ADAPTERS["copilot"].build_argv("x", program=PROGRAM))
        self.assertIn("--allow-tool=read", joined)
        self.assertIn("--deny-tool=shell", joined)

    def test_blanket_flag_in_a_prompt_is_rejected(self):
        """A prompt must never be able to smuggle a permission flag into argv."""
        with self.assertRaises(audit_adapter.UnsafeInvocation):
            audit_adapter.ADAPTERS["copilot"].build_argv("--allow-all-tools", program=PROGRAM)


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


class Argv0Test(unittest.TestCase):
    """SEC-003, and the runtime substitute for a static rule that cannot see it.

    INV-2 (`bin/check_invariants.py`) reads argv[0] at the call site; this argv is assembled in
    a helper and handed to `subprocess.run` as an expression, so the checker's own docstring
    records it as a known blind spot. `_guard` is where the property is enforced instead — the
    one function every adapter's argv already passes through, and the same function the
    blanket-flag refusal lives in.
    """

    def test_a_bare_argv0_is_refused(self):
        """A bare name is a request to search, and on Windows `CreateProcess` searches the
        working directory — under documented usage, the repository being audited."""
        with self.assertRaises(audit_adapter.UnsafeInvocation) as ctx:
            audit_adapter._guard(["claude", "-p", "x"])
        self.assertIn("absolute path", str(ctx.exception))

    def test_a_relative_argv0_is_refused(self):
        for argv0 in ("./claude", ".\\claude.exe", "bin/claude", "C:claude.exe"):
            with self.subTest(argv0=argv0):
                with self.assertRaises(audit_adapter.UnsafeInvocation):
                    audit_adapter._guard([argv0, "-p", "x"])

    def test_an_empty_argv_is_refused_rather_than_indexed(self):
        """`argv[0]` on an empty list is an IndexError, which is not a refusal — it is a
        traceback out of a security check."""
        with self.assertRaises(audit_adapter.UnsafeInvocation):
            audit_adapter._guard([])

    def test_build_argv_without_a_program_raises(self):
        """Deliberately no `program or "claude"` fallback. A default would make the whole fix
        opt-in per call site, and the one site that forgot would search PATH in silence."""
        for name in audit_adapter.ADAPTERS:
            with self.subTest(name=name):
                with self.assertRaises(audit_adapter.UnsafeInvocation):
                    audit_adapter.ADAPTERS[name].build_argv("x")

    def test_a_forgotten_program_is_named_as_missing_not_as_the_bare_binary(self):
        """The refusal has to name what would actually have been run.

        Restoring a `program or "claude"` fallback is invisible to every other
        test in this file: argv[0] becomes `"claude"`, which is not anchored, so
        `_guard` raises exactly as it does for None and the suite stays green.
        The two worlds differ only in the message — `None` versus `'claude'` —
        and the difference is the whole diagnosis. `None` says "a call site
        forgot to thread `program=` through"; `'claude'` says "the claude you
        have is not absolute", which is a different bug and sends the reader off
        to inspect a PATH that was never consulted.

        So this is the test that holds the comment above `_claude_argv` to
        something, rather than leaving it as a statement of intent no run can
        contradict.
        """
        for name, binary in (("claude", "claude"), ("copilot", "copilot")):
            with self.subTest(name=name):
                with self.assertRaises(audit_adapter.UnsafeInvocation) as caught:
                    audit_adapter.ADAPTERS[name].build_argv("x")
                message = str(caught.exception)
                self.assertIn("None", message)
                self.assertNotIn(repr(binary), message)

    def test_the_resolved_program_becomes_argv0(self):
        for name in audit_adapter.ADAPTERS:
            with self.subTest(name=name):
                argv = audit_adapter.ADAPTERS[name].build_argv("x", program=PROGRAM)
                self.assertEqual(argv[0], PROGRAM)

    def test_the_blanket_flag_refusal_is_not_displaced(self):
        """Two independent refusals in one function; adding the first must not consume the
        second. An absolute argv[0] carrying a smuggled permission flag still raises."""
        with self.assertRaises(audit_adapter.UnsafeInvocation) as ctx:
            audit_adapter._guard([PROGRAM, "-p", "--allow-all-tools"])
        self.assertIn("--allow-all-tools", str(ctx.exception))


class ProgramForTest(unittest.TestCase):
    """Where an agent CLI is decided, once, with a printable reason for a refusal."""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.project = Path(self._tmp.name) / "audited-project"
        self.project.mkdir()

    def _plant(self, name):
        written = [self.project / name]
        if os.name == "nt":
            written.append(self.project / (name + ".exe"))
        for path in written:
            path.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
            path.chmod(0o755)

    def test_an_agent_cli_inside_the_audited_project_is_not_detected(self):
        """A `claude` the repository being audited shipped is not one the operator installed.

        Both halves are asserted: with the project named, detection comes back empty; without
        it, the same PATH finds the same file. The difference is the containment rule and not
        the file being unfindable.
        """
        self._plant("claude")
        with mock.patch.dict(os.environ, {"PATH": str(self.project)}):
            if shutil.which("claude") is None:
                self.skipTest("this host's shutil.which will not find the planted file")
            self.assertIsNone(audit_adapter.detect(self.project))
            self.assertEqual(audit_adapter.detect(), "claude")
            refused = audit_adapter.program_for("claude", self.project)
        self.assertIsNone(refused.path)
        self.assertIn(str(self.project), refused.reason)

    def test_a_missing_cli_is_reported_by_name(self):
        with mock.patch("shutil.which", return_value=None):
            self.assertEqual(audit_adapter.program_for("copilot").reason,
                             "copilot is not on PATH")


class NoResolverTest(unittest.TestCase):
    """A skill tree with no `exec_path` refuses, and says so.

    The reachable cause is narrow but real: `--copy` skips a skill whose target
    was occupied or foreign, so `freya-code-graph` can be absent from a tree
    that still has this one. Unguarded, that was a `ModuleNotFoundError`
    traceback out of `freya security`, exiting 1 only because Python's
    uncaught-exception code happens to equal `audit.EXIT_NOTHING_TO_DO` — a
    coincidence, not a degrade. `bin/updater.py` guards the identical import and
    the two must not disagree about what a damaged tree does.
    """

    def test_program_for_refuses_with_a_reason_instead_of_raising(self):
        with mock.patch.object(audit_adapter, "exec_path", None):
            got = audit_adapter.program_for("claude", "/some/project")
        self.assertIsNone(got.path)
        self.assertTrue(got.reason.startswith("claude cannot be resolved"), got.reason)
        self.assertIn("exec_path.py", got.reason)

    def test_detection_finds_nothing_rather_than_falling_back_to_a_bare_name(self):
        """The temptation this closes: a damaged tree is exactly when "just
        search PATH" reads as graceful degradation. `shutil.which` is made to
        succeed with a plausible absolute path, so the only thing that can
        produce None is the refusal itself."""
        with mock.patch.object(audit_adapter, "exec_path", None), \
                mock.patch("shutil.which", side_effect=lambda b: f"/usr/bin/{b}"):
            self.assertIsNone(audit_adapter.detect("/some/project"))

    def test_guard_refuses_every_argv_when_the_anchoring_rule_is_missing(self):
        """No rule means no worker, rather than a worker judged by a rule that
        is not there. An absolute argv[0] — the shape that normally passes — is
        used so this cannot be read as the ordinary refusal."""
        with mock.patch.object(audit_adapter, "containment", None):
            with self.assertRaises(audit_adapter.UnsafeInvocation) as caught:
                audit_adapter._guard([PROGRAM, "-p", "x"])
        self.assertIn("exec_path.py", str(caught.exception))

    def test_the_driver_degrades_with_a_stated_reason_and_no_traceback(self):
        """End to end, in a real damaged tree and a fresh interpreter, because
        the defect was at module import and this process's `sys.modules` is
        already warm. Asserts the exit code *and* the absence of a traceback:
        the code alone was right before this fix, by coincidence."""
        scripts = Path(audit_adapter.__file__).resolve().parent
        with tempfile.TemporaryDirectory() as tmp:
            tree = Path(tmp) / "skills"
            broken = tree / "freya-codebase-security-scan" / "scripts"
            broken.parent.mkdir(parents=True)
            shutil.copytree(scripts, broken,
                            ignore=shutil.ignore_patterns("__pycache__"))
            # Present but empty: the shape a `--copy` install leaves behind when
            # freya-code-graph's target was occupied, not a missing directory.
            (tree / "freya-code-graph" / "scripts").mkdir(parents=True)
            project = Path(tmp) / "project"
            project.mkdir()
            proc = subprocess.run(
                [sys.executable, str(broken / "audit.py"), "scan",
                 "--project", str(project), "--dry-run"],
                capture_output=True, text=True)
        self.assertNotIn("Traceback", proc.stderr)
        self.assertIn("exec_path.py", proc.stderr)
        self.assertEqual(proc.returncode, 1)  # audit.EXIT_NOTHING_TO_DO


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
