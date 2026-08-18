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
