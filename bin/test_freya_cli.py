#!/usr/bin/env python3
"""Proof suite for freya_cli.py — the portable launcher."""
import contextlib
import io
import json
import os
import re
import subprocess
import sys
import tempfile
import unittest
import unittest.mock
from pathlib import Path
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import freya_cli  # noqa: E402
import installer  # noqa: E402


class SuiteRootTest(unittest.TestCase):
    def test_points_at_checkout_containing_skills_and_bin(self):
        root = freya_cli.suite_root()
        self.assertTrue((root / "skills").is_dir(), f"no skills/ under {root}")
        self.assertTrue((root / "bin").is_dir(), f"no bin/ under {root}")

    def test_is_absolute_and_resolved(self):
        root = freya_cli.suite_root()
        self.assertTrue(root.is_absolute())
        self.assertEqual(root, root.resolve())


class ManifestTest(unittest.TestCase):
    def test_loads_and_contains_core_commands(self):
        manifest = freya_cli.load_manifest()
        for name in ("code-graph", "behavior-graph", "status", "spec"):
            self.assertIn(name, manifest)

    def test_every_manifest_target_exists(self):
        """Guards against manifest drift when scripts move or are renamed."""
        root = freya_cli.suite_root()
        missing = [
            f"{name} -> {rel}"
            for name, rel in freya_cli.load_manifest().items()
            if not (root / "skills" / rel).is_file()
        ]
        self.assertEqual(missing, [], f"manifest points at missing scripts: {missing}")

    def test_every_cli_script_is_registered(self):
        """Reverse of test_every_manifest_target_exists: a new CLI script must be
        added to commands.json or it is unreachable through freya."""
        root = freya_cli.suite_root()
        registered = {
            (root / "skills" / rel).resolve() for rel in freya_cli.load_manifest().values()
        }
        unregistered = []
        for script in sorted((root / "skills").glob("*/scripts/*.py")):
            if script.name.startswith("test_"):
                continue
            text = script.read_text(encoding="utf-8")
            if '__name__ == "__main__"' in text or "__name__ == '__main__'" in text:
                if script.resolve() not in registered:
                    unregistered.append(str(script.relative_to(root)))
        self.assertEqual(unregistered, [], f"CLI scripts missing from commands.json: {unregistered}")


class ResolveCommandTest(unittest.TestCase):
    def test_known_command_resolves_to_existing_script(self):
        script = freya_cli.resolve_command("code-graph")
        self.assertIsNotNone(script)
        self.assertTrue(script.is_file())
        self.assertEqual(script.name, "graph_ops.py")

    def test_unknown_command_returns_none(self):
        self.assertIsNone(freya_cli.resolve_command("no-such-command"))

    def test_honors_explicit_root_and_manifest(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "skills" / "demo" / "scripts").mkdir(parents=True)
            target = root / "skills" / "demo" / "scripts" / "run.py"
            target.write_text("")
            got = freya_cli.resolve_command(
                "demo", manifest={"demo": "demo/scripts/run.py"}, root=root
            )
            self.assertEqual(got, target)


class BuildArgvTest(unittest.TestCase):
    def test_uses_current_interpreter_not_bare_python(self):
        # `str(Path("/tmp/x.py"))` is "\tmp\x.py" on Windows — the separator
        # is the platform's, and asserting the POSIX literal was asserting the
        # platform, not the behaviour. The contract is that the script comes
        # through as `str(script)` in argv[1]; only argv[0] is the subject.
        # (First Windows CI run.)
        script = Path("/tmp/x.py")
        argv = freya_cli.build_argv(script, ["--flag", "v"])
        self.assertEqual(argv[0], sys.executable)
        self.assertEqual(argv[1], str(script))
        self.assertEqual(argv[2:], ["--flag", "v"])

    def test_all_elements_are_strings(self):
        argv = freya_cli.build_argv(Path("/tmp/x.py"), [])
        self.assertTrue(all(isinstance(a, str) for a in argv))


class RunCommandTest(unittest.TestCase):
    def _fixture(self, tmp, body):
        root = Path(tmp)
        (root / "bin").mkdir(parents=True)
        (root / "skills" / "demo" / "scripts").mkdir(parents=True)
        (root / "skills" / "demo" / "scripts" / "run.py").write_text(body)
        (root / "bin" / "commands.json").write_text(
            json.dumps({"demo": "demo/scripts/run.py"})
        )
        return root

    def test_propagates_child_exit_code(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = self._fixture(tmp, "import sys\nsys.exit(7)\n")
            self.assertEqual(freya_cli.run_command("demo", [], root=root), 7)

    def test_returns_zero_on_success(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = self._fixture(tmp, "print('hi')\n")
            self.assertEqual(freya_cli.run_command("demo", [], root=root), 0)

    def test_passes_arguments_through(self):
        with tempfile.TemporaryDirectory() as tmp:
            body = "import sys\nsys.exit(len(sys.argv) - 1)\n"
            root = self._fixture(tmp, body)
            self.assertEqual(freya_cli.run_command("demo", ["a", "b", "c"], root=root), 3)

    def test_unknown_command_returns_none(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = self._fixture(tmp, "print('hi')\n")
            self.assertIsNone(freya_cli.run_command("nope", [], root=root))


class FormatHelpTest(unittest.TestCase):
    def test_lists_every_manifest_command_and_builtins(self):
        text = freya_cli.format_help({"zebra": "z/scripts/z.py", "alpha": "a/scripts/a.py"})
        self.assertIn("alpha", text)
        self.assertIn("zebra", text)
        self.assertIn("doctor", text)
        self.assertIn("help", text)
        self.assertLess(text.index("alpha"), text.index("zebra"), "commands should be sorted")


class MainTest(unittest.TestCase):
    def _run(self, argv):
        # main() calls updater.notify() for any command outside NO_NOTIFY,
        # which — unpatched — writes ~/.freya/update-check.json for real and
        # runs a real `git ls-remote`. Every test that drives main() through
        # this helper gets a no-op notify instead, so the suite never touches
        # the real home directory or the network just to exercise dispatch.
        out, err = io.StringIO(), io.StringIO()
        with unittest.mock.patch("updater.notify", lambda *a, **k: None):
            with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
                code = freya_cli.main(argv)
        return code, out.getvalue(), err.getvalue()

    def test_no_args_prints_help_and_succeeds(self):
        code, out, _ = self._run([])
        self.assertEqual(code, 0)
        self.assertIn("Usage: freya", out)

    def test_help_command_prints_help(self):
        for flag in ("help", "-h", "--help"):
            code, out, _ = self._run([flag])
            self.assertEqual(code, 0, flag)
            self.assertIn("Usage: freya", out)

    def test_unknown_command_exits_2_with_stderr_hint(self):
        code, _, err = self._run(["definitely-not-a-command"])
        self.assertEqual(code, 2)
        self.assertIn("unknown command", err)
        self.assertIn("freya help", err)

    def test_returns_child_exit_code_for_known_command(self):
        # "code-graph" is outside NO_NOTIFY, so this must go through _run's
        # patched notify() rather than calling main() directly — unpatched,
        # this test used to write ~/.freya/update-check.json and run a real
        # `git ls-remote` on every suite run.
        with unittest.mock.patch.object(freya_cli, "run_command", return_value=5) as ran:
            code, _, _ = self._run(["code-graph", "--impact", "x.ts"])
        self.assertEqual(code, 5)
        ran.assert_called_once_with("code-graph", ["--impact", "x.ts"])

    def test_install_is_routed_to_the_installer(self):
        with mock.patch("installer.main", return_value=0) as installer_main:
            code = freya_cli.main(["install", "--agent", "claude"])
        self.assertEqual(code, 0)
        installer_main.assert_called_once_with(["--agent", "claude"])

    def test_uninstall_is_routed_to_the_installer(self):
        with mock.patch("installer.main", return_value=0) as installer_main:
            freya_cli.main(["uninstall"])
        installer_main.assert_called_once_with(["--uninstall"])


#: A `run=` stand-in that fails every git call instantly. doctor_checks()'s
#: "updates" check is unthrottled by design (a diagnostic that reports a
#: cached answer is not diagnosing anything), so any test that calls
#: doctor_checks()/doctor() against the real suite root — as the tests below
#: do, to exercise the other checks against this actual checkout — must
#: inject this or it makes a real `git ls-remote` to the real origin.
def _offline_git(*_args, **_kwargs):
    return 1, ""


class DoctorTest(unittest.TestCase):
    def _status(self, checks, name):
        return next(s for n, s, _ in checks if n == name)

    def test_healthy_checkout_reports_ok(self):
        checks = freya_cli.doctor_checks(run=_offline_git)
        self.assertEqual(self._status(checks, "suite root"), "ok")
        self.assertEqual(self._status(checks, "manifest"), "ok")
        self.assertEqual(self._status(checks, "scripts"), "ok")
        self.assertEqual(self._status(checks, "python"), "ok")

    def test_path_check_is_warn_not_fail_when_absent(self):
        """No `freya` on PATH is the shape a half-finished install leaves, and
        it is the shape doctor is most often run from — so the row warns. A
        FAIL there would make `freya doctor` exit 1 while diagnosing exactly
        the state it was invoked to explain, which is the same discipline
        `_under` follows for an unreadable path.

        This test was green and vacuous until 2026-08-21, both halves
        measured. It never mocked `which` — unlike the two tests below it —
        so it ran against the ambient PATH, where `which("freya")` finds the
        installed copy and the absent branch is simply never entered: turning
        that branch into a hard "fail" left this green. And its
        `statuses <= {"ok", "warn"}` could not have caught it even then —
        turning the branch into "ok", a PATH row that silently approves of a
        missing launcher, left it green too.
        """
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "checkout"
            (root / "bin").mkdir(parents=True)
            (root / "skills").mkdir(parents=True)
            (root / "bin" / "commands.json").write_text("{}")
            # targets={} for the same reason the neighbours below pass a tmp
            # root: only the PATH row is under test, and the agent checks
            # would otherwise answer against the real ~/.claude.
            with mock.patch.object(freya_cli.shutil, "which", return_value=None):
                status, detail = self._path_row(
                    freya_cli.doctor_checks(root=root, targets={}, run=_offline_git))
        self.assertEqual(status, "warn")
        self.assertIn("not found", detail)

    def _path_row(self, checks):
        return next((s, d) for n, s, d in checks if n == "freya on PATH")

    def test_a_freya_on_path_from_another_install_is_a_warning(self):
        """Found by running `./bin/freya doctor` from a checkout.

        A released copy was on PATH, doctor inspected the checkout, and the row
        said `ok` — so every other row described a tree the shell would not run.
        """
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "checkout"
            (root / "bin").mkdir(parents=True)
            (root / "skills").mkdir(parents=True)
            (root / "bin" / "commands.json").write_text("{}")
            elsewhere = Path(tmp) / "elsewhere" / "bin"
            elsewhere.mkdir(parents=True)
            (elsewhere / "freya").write_text("#!/bin/sh\n")
            (elsewhere / "freya").chmod(0o755)
            with mock.patch.object(freya_cli.shutil, "which",
                                   return_value=str(elsewhere / "freya")):
                status, detail = self._path_row(
                    freya_cli.doctor_checks(root=root, run=_offline_git))
        self.assertEqual(status, "warn")
        self.assertIn("a different copy", detail)

    def test_a_symlink_into_the_store_is_still_ok(self):
        """The healthy install is a symlink, so the check must follow it."""
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "store"
            (root / "bin").mkdir(parents=True)
            (root / "skills").mkdir(parents=True)
            (root / "bin" / "commands.json").write_text("{}")
            (root / "bin" / "freya").write_text("#!/bin/sh\n")
            link_dir = Path(tmp) / "linkdir"
            link_dir.mkdir()
            link = link_dir / "freya"
            link.symlink_to(root / "bin" / "freya")
            with mock.patch.object(freya_cli.shutil, "which", return_value=str(link)):
                status, detail = self._path_row(
                    freya_cli.doctor_checks(root=root, run=_offline_git))
        self.assertEqual(status, "ok")
        self.assertNotIn("different copy", detail)

    def test_missing_script_is_reported_as_fail(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "bin").mkdir(parents=True)
            (root / "skills").mkdir(parents=True)
            (root / "bin" / "commands.json").write_text(
                json.dumps({"ghost": "ghost/scripts/ghost.py"})
            )
            checks = freya_cli.doctor_checks(root=root, run=_offline_git)
            self.assertEqual(self._status(checks, "scripts"), "fail")
            self.assertIn("ghost", dict((n, d) for n, _, d in checks)["scripts"])

    def test_doctor_returns_1_when_a_check_fails(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "bin").mkdir(parents=True)
            (root / "skills").mkdir(parents=True)
            (root / "bin" / "commands.json").write_text(
                json.dumps({"ghost": "ghost/scripts/ghost.py"})
            )
            out = io.StringIO()
            with contextlib.redirect_stdout(out):
                code = freya_cli.doctor(root=root)
            self.assertEqual(code, 1)
            self.assertIn("FAIL", out.getvalue())

    def test_doctor_returns_0_on_healthy_checkout(self):
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            code = freya_cli.doctor(run=_offline_git)
        self.assertEqual(code, 0)

    def test_main_dispatches_the_doctor_builtin(self):
        # "doctor" is in NO_NOTIFY, so main() itself makes no notify() call
        # here — but doctor() has no CLI-level seam for injecting `run=`, and
        # its own "updates" check is deliberately unthrottled, so without
        # patching updater.git this still reaches the real network on every
        # suite run.
        out = io.StringIO()
        with unittest.mock.patch("updater.notify", lambda *a, **k: None):
            with unittest.mock.patch("updater.git", _offline_git):
                with contextlib.redirect_stdout(out):
                    code = freya_cli.main(["doctor"])
        self.assertEqual(code, 0)
        self.assertIn("suite root", out.getvalue())

    def _broken_manifest_root(self, tmp, content):
        root = Path(tmp)
        (root / "bin").mkdir(parents=True, exist_ok=True)
        (root / "skills").mkdir(parents=True, exist_ok=True)
        (root / "bin" / "commands.json").write_text(content)
        return root

    def test_malformed_manifest_is_reported_not_raised(self):
        """doctor exists to diagnose broken installs — it must never traceback.

        Every input must ALSO leave the scripts check unable to claim success.
        `"{ not json"` is the case that reaches the `except (OSError, ValueError)`
        branch — the literal site of the original defect, where falling back to an
        empty manifest made scripts report ("ok", "all present") having verified
        nothing. Asserting on scripts here is what keeps that fix from silently
        regressing.
        """
        for content in ("[]", "null", '"a string"', "{ not json"):
            with self.subTest(content=content), tempfile.TemporaryDirectory() as tmp:
                root = self._broken_manifest_root(tmp, content)
                checks = freya_cli.doctor_checks(root=root, run=_offline_git)   # must not raise
                self.assertEqual(self._status(checks, "manifest"), "fail")
                detail = dict((n, d) for n, _, d in checks)["scripts"]
                self.assertNotEqual(self._status(checks, "scripts"), "ok")
                self.assertNotIn("all present", detail)

    def test_non_string_manifest_value_is_reported(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = self._broken_manifest_root(tmp, json.dumps({"demo": 5}))
            checks = freya_cli.doctor_checks(root=root, run=_offline_git)
            self.assertEqual(self._status(checks, "manifest"), "fail")

    def test_scripts_not_claimed_present_when_manifest_unusable(self):
        """The bug this guards: falling back to {} made scripts report 'all present'."""
        with tempfile.TemporaryDirectory() as tmp:
            root = self._broken_manifest_root(tmp, "[]")
            checks = freya_cli.doctor_checks(root=root, run=_offline_git)
            detail = dict((n, d) for n, _, d in checks)["scripts"]
            self.assertNotEqual(self._status(checks, "scripts"), "ok")
            self.assertNotIn("all present", detail)

    def test_absent_manifest_file_is_reported_not_raised(self):
        """The OSError sub-path: no commands.json at all."""
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "bin").mkdir(parents=True)
            (root / "skills").mkdir(parents=True)
            checks = freya_cli.doctor_checks(root=root, run=_offline_git)   # must not raise
            self.assertEqual(self._status(checks, "manifest"), "fail")
            detail = dict((n, d) for n, _, d in checks)["scripts"]
            self.assertNotEqual(self._status(checks, "scripts"), "ok")
            self.assertNotIn("all present", detail)

    def test_doctor_reports_failure_cleanly_on_malformed_manifest(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = self._broken_manifest_root(tmp, "null")
            out = io.StringIO()
            with contextlib.redirect_stdout(out):
                code = freya_cli.doctor(root=root)   # must not raise
            self.assertEqual(code, 1)
            self.assertIn("FAIL", out.getvalue())

    def test_main_propagates_doctor_failure_exit_code(self):
        # "doctor" is in NO_NOTIFY so main() should not call notify() at all
        # here; patching it to a no-op is the belt-and-suspenders half of
        # that guarantee, matching the other main(["doctor"]) test above.
        with unittest.mock.patch("updater.notify", lambda *a, **k: None):
            with unittest.mock.patch.object(freya_cli, "doctor", return_value=1) as ran:
                self.assertEqual(freya_cli.main(["doctor"]), 1)
        ran.assert_called_once_with()

    def test_doctor_reports_agent_link_status(self):
        labels = [label for label, _, _ in freya_cli.doctor_checks(run=_offline_git)]
        self.assertIn("agents", labels)

    def test_doctor_warns_when_the_claude_plugin_is_also_installed(self):
        """Plugin + personal install means every skill is registered twice."""
        labels = [label for label, _, _ in freya_cli.doctor_checks(run=_offline_git)]
        self.assertIn("duplicate install", labels)


class ShimTest(unittest.TestCase):
    def test_symlinked_shim_runs_under_safe_path(self):
        """bin/freya must use realpath: under PYTHONSAFEPATH CPython does not
        auto-insert a resolved sys.path[0], so abspath would point at the
        symlink's directory and the freya_cli import would fail."""
        shim = freya_cli.suite_root() / "bin" / "freya"
        with tempfile.TemporaryDirectory() as tmp:
            link = Path(tmp) / "freya"
            link.symlink_to(shim)
            env = {**os.environ, "PYTHONSAFEPATH": "1"}
            # Executed through its shebang on POSIX, which is how it is
            # actually invoked; Windows cannot run an extensionless file at
            # all (that is what the .cmd shim exists for), so there the
            # interpreter is named explicitly.
            argv = ([sys.executable, str(link), "help"] if os.name == "nt"
                    else [str(link), "help"])
            r = subprocess.run(argv, capture_output=True, text=True, env=env)
            self.assertEqual(r.returncode, 0, r.stderr)
            self.assertIn("Usage: freya", r.stdout)

    def test_every_dispatched_command_imports_under_safe_path(self):
        """The test above only ran `help`, which returns before `run_command`
        ever spawns a child — so it proved nothing about the commands, and
        `freya security` was dead under PYTHONSAFEPATH (its bare `import
        audit_adapter` relies on the sys.path[0] the flag removes) while this
        class stayed green. The environment is inherited by the child, so the
        launcher is where the script's own directory has to be restored.
        """
        shim = freya_cli.suite_root() / "bin" / "freya"
        env = {**os.environ, "PYTHONSAFEPATH": "1"}
        for name in sorted(freya_cli.load_manifest()):
            with self.subTest(command=name):
                # The import happens at module scope, before argparse, so
                # --help is a valid probe that runs no real work.
                r = subprocess.run([sys.executable, str(shim), name, "--help"],
                                   capture_output=True, text=True, env=env)
                self.assertNotIn("ModuleNotFoundError", r.stderr)

    def test_running_the_module_directly_is_not_a_silent_success(self):
        """`python3 bin/freya_cli.py doctor` — the way a user whose launcher is
        not on PATH reaches the diagnostic — printed nothing and exited 0,
        which reads exactly like a passing health check."""
        module = freya_cli.suite_root() / "bin" / "freya_cli.py"
        r = subprocess.run([sys.executable, str(module), "definitely-not-a-command"],
                           capture_output=True, text=True)
        self.assertEqual(r.returncode, 2)
        self.assertIn("unknown command", r.stderr)


class PythonFloorTest(unittest.TestCase):
    """MIN_PYTHON was declared and never enforced: every entry point that
    would have reported it needed a newer Python than the floor it checked,
    so a 3.6/3.7 host got a SyntaxError from installer.py instead — including
    from `freya doctor`, whose whole job here is to say the Python is too old.
    Three files carry the floor and none can import the others, so this is the
    only thing keeping them in step.
    """

    def _floor_in(self, path, pattern):
        text = (freya_cli.suite_root() / path).read_text(encoding="utf-8")
        found = re.findall(pattern, text)
        self.assertTrue(found, f"no version floor found in {path}")
        return {(int(major), int(minor)) for major, minor in found}

    def test_the_launcher_guards_the_declared_floor(self):
        self.assertEqual(
            self._floor_in("bin/freya", r"sys\.version_info < \((\d+), (\d+)\)"),
            {freya_cli.MIN_PYTHON},
        )

    def test_both_bootstrap_scripts_gate_on_the_declared_floor(self):
        for path in ("install.sh", "install.ps1"):
            with self.subTest(path=path):
                self.assertEqual(
                    self._floor_in(path, r"sys\.version_info [<>]=? \((\d+), (\d+)\)"),
                    {freya_cli.MIN_PYTHON},
                )

    #: A stand-in for a CPython older than the floor, dropped on one
    #: subprocess's PYTHONPATH so `site` imports it before the shim runs.
    #: Faking `sys.version_info` alone would only prove the comparison works;
    #: the import hook is what makes the simulation honest, because on a real
    #: 3.8 the suite modules are not merely wrong-versioned, they cannot be
    #: parsed — and that SyntaxError, raised from a file the user never named,
    #: is precisely the traceback the guard exists to pre-empt.
    _OLD_INTERPRETER = (
        "import collections, sys\n"
        "sys.version_info = collections.namedtuple(\n"
        "    'version_info', 'major minor micro releaselevel serial')(3, 8, 0, 'final', 0)\n"
        "\n"
        "class _Unparsable:\n"
        "    def find_spec(self, fullname, path=None, target=None):\n"
        "        if fullname in ('freya_cli', 'installer', 'updater', 'agents_md'):\n"
        "            raise SyntaxError('invalid syntax')\n"
        "        return None\n"
        "\n"
        "sys.meta_path.insert(0, _Unparsable())\n"
    )

    def test_an_old_interpreter_is_refused_by_message_not_syntaxerror(self):
        """BEH-005: the too-old interpreter is *named*, not tracebacked.

        The tests above only prove the four declarations agree on a number.
        None of them runs the guard, so none would notice it being moved below
        `from freya_cli import main` — where it would still read (3, 9) and
        still be, for a 3.8 user, unreachable: the import dies first and the
        error names installer.py, a file they never typed. `freya doctor` is
        covered here alongside `help` because it is the one command whose job
        is to say the Python is too old, and it is also the command that pulls
        in the most unparsable modules on the way to saying it.
        """
        shim = freya_cli.suite_root() / "bin" / "freya"
        with tempfile.TemporaryDirectory() as tmp:
            (Path(tmp) / "sitecustomize.py").write_text(
                self._OLD_INTERPRETER, encoding="utf-8")
            # OPT_OUT so that a guard which fails to fire cannot reach the
            # real network on its way to failing this test.
            env = {**os.environ, "PYTHONPATH": tmp, "FREYA_NO_UPDATE_CHECK": "1"}
            for command in ("help", "doctor"):
                with self.subTest(command=command):
                    r = subprocess.run([sys.executable, str(shim), command],
                                       capture_output=True, text=True, env=env)
                    self.assertNotIn("Traceback", r.stderr)
                    self.assertNotIn("SyntaxError", r.stderr)
                    self.assertIn("Python 3.9 or newer", r.stderr)
                    # "found 3.8", not "3.8": sys.executable is in the same
                    # sentence, and a version number can hide in its path.
                    self.assertIn("found 3.8", r.stderr)
                    self.assertEqual(r.returncode, 2, r.stderr)
                    self.assertEqual(r.stdout, "")

    def test_the_bootstrap_probe_actually_accepts_this_interpreter(self):
        """The gate is a one-liner run by a shell; a typo in it rejects every
        Python on the machine and the installer is simply unreachable."""
        text = (freya_cli.suite_root() / "install.sh").read_text(encoding="utf-8")
        probe = re.search(r'"\$py" -c \'([^\']+)\'', text).group(1)
        self.assertEqual(
            subprocess.run([sys.executable, "-c", probe]).returncode, 0)


class ManifestValidationTest(unittest.TestCase):
    """A structurally valid but wrong-shaped manifest crashed every dispatch
    with a raw traceback, while doctor handled the identical input cleanly and
    had four subtests proving it."""

    def _root(self, tmp, content):
        root = Path(tmp)
        (root / "bin").mkdir(parents=True, exist_ok=True)
        (root / "skills").mkdir(parents=True, exist_ok=True)
        (root / "bin" / "commands.json").write_text(content, encoding="utf-8")
        return root

    def test_a_wrong_shaped_manifest_raises_value_error(self):
        for content in ("null", "[]", '"a string"', '{"demo": 5}'):
            with self.subTest(content=content), tempfile.TemporaryDirectory() as tmp:
                with self.assertRaises(ValueError):
                    freya_cli.load_manifest(self._root(tmp, content))

    def test_an_entry_that_escapes_the_skills_directory_is_rejected(self):
        """resolve_command joins the value onto the store and main runs it, so
        the manifest is an implicit trust boundary with nothing on it."""
        # Both path flavours on every host: the manifest is checked-in data
        # read on all of them. `/etc/passwd` is the one that regressed —
        # Python 3.13 changed ntpath.isabs so a rooted path with no drive is no
        # longer absolute on Windows, and the old `os.path.isabs` check let it
        # through on 3.13 while rejecting it on 3.9.
        for rel in ("/etc/passwd", "../../x.py", "/Windows/System32/x.py",
                    r"C:\Windows\System32\calc.exe", "C:x.py",
                    r"\\server\share\x.py", r"..\..\x.py",
                    "skills/../../../etc/passwd"):
            with self.subTest(rel=rel), tempfile.TemporaryDirectory() as tmp:
                root = self._root(tmp, json.dumps({"demo": rel}))
                with self.assertRaises(ValueError):
                    freya_cli.load_manifest(root)

    def test_doctor_fails_a_manifest_name_that_can_never_run(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = self._root(tmp, json.dumps({"doctor": "demo/scripts/doc.py"}))
            checks = freya_cli.doctor_checks(root=root, targets={}, run=_offline_git)
            manifest = next(c for c in checks if c[0] == "manifest")
            self.assertEqual(manifest[1], "fail")
            self.assertIn("doctor", manifest[2])

    def test_resolve_command_does_not_traceback_on_one(self):
        for content in ("null", "[]", '{"demo": 5}'):
            with self.subTest(content=content), tempfile.TemporaryDirectory() as tmp:
                root = self._root(tmp, content)
                with self.assertRaises(ValueError):
                    freya_cli.resolve_command("demo", root=root)

    def test_main_prints_the_intended_message_for_every_shape(self):
        for content in ("null", "[]", '"a string"', '{"code-graph": 5}', "{ not json"):
            for argv in (["help"], ["code-graph", "--build"]):
                with self.subTest(content=content, argv=argv), \
                        tempfile.TemporaryDirectory() as tmp:
                    root = self._root(tmp, content)
                    out, err = io.StringIO(), io.StringIO()
                    with unittest.mock.patch.object(freya_cli, "suite_root",
                                                    lambda root=root: root):
                        with unittest.mock.patch("updater.notify", lambda *a, **k: None):
                            with contextlib.redirect_stdout(out), \
                                    contextlib.redirect_stderr(err):
                                code = freya_cli.main(argv)   # must not raise
                    self.assertEqual(code, 2)
                    self.assertIn("cannot read the command manifest", err.getvalue())
                    self.assertIn("freya doctor", err.getvalue())

    def test_no_manifest_command_is_shadowed_by_a_builtin(self):
        """main dispatches the built-ins before ever calling run_command, so a
        manifest entry that collides with one is unreachable — while `freya
        help` still advertises it under Commands."""
        self.assertEqual(
            set(freya_cli.load_manifest()) & set(freya_cli.BUILTIN_COMMANDS), set())

    def test_every_freya_command_the_docs_prescribe_actually_exists(self):
        """The seam nothing crossed: the SKILL.md layer is the only caller of
        most of these commands, and no test ever checked that what it tells an
        agent to run resolves to anything. A renamed script or a manifest key
        that drifts leaves the instruction pointing at `unknown command`.
        """
        root = freya_cli.suite_root()
        known = set(freya_cli.load_manifest()) | set(freya_cli.BUILTIN_COMMANDS)
        # Anchored on a backtick, a line start or a shell prompt so prose
        # ("the freya launcher") is not mistaken for an invocation.
        pattern = re.compile(r"(?:^|`|\$ )freya ([a-z][a-z0-9-]*)", re.M)
        unknown = []
        for doc in sorted(root.glob("skills/*/SKILL.md")) + [root / "README.md"]:
            for name in sorted(set(pattern.findall(doc.read_text(encoding="utf-8")))):
                if name not in known:
                    unknown.append(f"{doc.relative_to(root)}: freya {name}")
        self.assertEqual(unknown, [], f"documented commands that do not exist: {unknown}")


class MissingScriptTest(unittest.TestCase):
    def test_a_registered_but_missing_script_is_a_freya_error(self):
        """CPython's own "can't open file" error never mentions freya and
        exits 2 — the same code as an unknown command."""
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "bin").mkdir(parents=True)
            (root / "skills").mkdir(parents=True)
            (root / "bin" / "commands.json").write_text(
                json.dumps({"ghost": "ghost/scripts/ghost.py"}), encoding="utf-8")
            err = io.StringIO()
            with contextlib.redirect_stderr(err):
                code = freya_cli.run_command("ghost", [], root=root)
            self.assertEqual(code, 2)
            self.assertIn("freya:", err.getvalue())
            self.assertIn("freya doctor", err.getvalue())

    @unittest.skipIf(os.name == "nt", "POSIX signal semantics")
    def test_a_signal_killed_child_uses_the_shell_convention(self):
        """subprocess.call reports -N; passing that to SystemExit masks it to
        256-N (241 for SIGTERM), which no shell convention explains. bin/freya
        already exits 130 for Ctrl-C, so 128+N is the intent."""
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "bin").mkdir(parents=True)
            (root / "skills" / "demo" / "scripts").mkdir(parents=True)
            (root / "skills" / "demo" / "scripts" / "run.py").write_text(
                "import os, signal\nos.kill(os.getpid(), signal.SIGTERM)\n",
                encoding="utf-8")
            (root / "bin" / "commands.json").write_text(
                json.dumps({"demo": "demo/scripts/run.py"}), encoding="utf-8")
            self.assertEqual(freya_cli.run_command("demo", [], root=root), 143)


class UnknownCommandHintTest(unittest.TestCase):
    def test_a_skill_name_is_named_as_a_skill(self):
        """`freya wrap-up` is the most natural thing a new user types, and the
        CLI/skill distinction only ever appeared in a project's AGENTS.md."""
        out, err = io.StringIO(), io.StringIO()
        with unittest.mock.patch("updater.notify", lambda *a, **k: None):
            with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
                code = freya_cli.main(["wrap-up"])
        self.assertEqual(code, 2)
        self.assertIn("is a skill, not a CLI command", err.getvalue())
        self.assertIn("freya-wrap-up", err.getvalue())

    def test_a_name_that_is_neither_gets_only_the_plain_message(self):
        out, err = io.StringIO(), io.StringIO()
        with unittest.mock.patch("updater.notify", lambda *a, **k: None):
            with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
                freya_cli.main(["definitely-not-a-command"])
        self.assertNotIn("is a skill", err.getvalue())
        self.assertIn("freya help", err.getvalue())


class PluginInstalledTest(unittest.TestCase):
    """doctor's duplicate-install probe tested `plugins/marketplaces/freya-devkit`,
    which means "marketplace added", not "plugin installed"."""

    def _home(self, tmp, *, marketplace=False, installed=False, cache_exists=True):
        home = Path(tmp)
        plugins = home / ".claude" / "plugins"
        plugins.mkdir(parents=True)
        if marketplace:
            (plugins / "marketplaces" / "freya-devkit").mkdir(parents=True)
        if installed:
            cache = plugins / "cache" / "freya-devkit" / "freya-devkit" / "0.1.0"
            if cache_exists:
                cache.mkdir(parents=True)
            (plugins / "installed_plugins.json").write_text(json.dumps({
                "version": 2,
                "plugins": {"freya-devkit@freya-devkit": [
                    {"scope": "user", "installPath": str(cache), "version": "0.1.0"}
                ]},
            }), encoding="utf-8")
        return home

    def test_a_marketplace_alone_is_not_an_install(self):
        with tempfile.TemporaryDirectory() as tmp:
            self.assertFalse(freya_cli.plugin_installed(self._home(tmp, marketplace=True)))

    def test_an_installed_plugin_is_found_without_a_marketplace_checkout(self):
        """A `directory`-source marketplace has no checkout under
        plugins/marketplaces at all, yet its plugins are genuinely installed."""
        with tempfile.TemporaryDirectory() as tmp:
            self.assertTrue(freya_cli.plugin_installed(self._home(tmp, installed=True)))

    def test_a_recorded_install_whose_files_are_gone_is_not_an_install(self):
        with tempfile.TemporaryDirectory() as tmp:
            home = self._home(tmp, installed=True, cache_exists=False)
            self.assertFalse(freya_cli.plugin_installed(home))

    def test_a_missing_or_corrupt_record_is_not_an_install(self):
        with tempfile.TemporaryDirectory() as tmp:
            home = Path(tmp)
            (home / ".claude" / "plugins").mkdir(parents=True)
            self.assertFalse(freya_cli.plugin_installed(home))
            (home / ".claude" / "plugins" / "installed_plugins.json").write_text(
                "{ not json", encoding="utf-8")
            self.assertFalse(freya_cli.plugin_installed(home))


class DoctorSurvivesBrokenReadsTest(unittest.TestCase):
    """doctor exists to diagnose the broken installations whose reads fail."""

    @contextlib.contextmanager
    def _unreadable_skills(self):
        real_is_file, real_iterdir = Path.is_file, Path.iterdir

        def is_file(self, *a, **k):
            if "skills" in self.parts:
                raise PermissionError(13, "Permission denied")
            return real_is_file(self, *a, **k)

        def iterdir(self, *a, **k):
            if self.name == "skills":
                raise PermissionError(13, "Permission denied")
            return real_iterdir(self, *a, **k)

        with unittest.mock.patch.object(Path, "is_file", is_file):
            with unittest.mock.patch.object(Path, "iterdir", iterdir):
                yield

    def test_an_unreadable_skills_directory_is_a_row_not_a_traceback(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "bin").mkdir(parents=True)
            (root / "skills").mkdir(parents=True)
            (root / "bin" / "commands.json").write_text(
                json.dumps({"demo": "demo/scripts/run.py"}), encoding="utf-8")
            with self._unreadable_skills():
                checks = freya_cli.doctor_checks(root=root, targets={}, run=_offline_git)
            statuses = dict((n, s) for n, s, _ in checks)
            # The manifest read fine — blaming it, and telling the user to run
            # the command that just died, was the actual defect.
            self.assertEqual(statuses["manifest"], "ok")
            self.assertEqual(statuses["scripts"], "fail")

    def test_main_does_not_report_it_as_a_manifest_failure(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "bin").mkdir(parents=True)
            (root / "skills").mkdir(parents=True)
            (root / "bin" / "commands.json").write_text(
                json.dumps({"demo": "demo/scripts/run.py"}), encoding="utf-8")
            out, err = io.StringIO(), io.StringIO()
            with unittest.mock.patch.object(freya_cli, "suite_root", lambda root=root: root):
                with unittest.mock.patch("updater.git", _offline_git):
                    with unittest.mock.patch("updater.notify", lambda *a, **k: None):
                        with self._unreadable_skills():
                            with contextlib.redirect_stdout(out), \
                                    contextlib.redirect_stderr(err):
                                code = freya_cli.main(["doctor"])   # must not raise
            self.assertEqual(code, 1)
            self.assertNotIn("cannot read the command manifest", err.getvalue())
            self.assertIn("FAIL", out.getvalue())


class DoctorAheadOfUpstreamTest(unittest.TestCase):
    def _runner(self, *, local, remote, ancestor):
        def run(args, cwd, timeout=None):
            if args[0] == "rev-parse" and args[1] == "--show-toplevel":
                return 0, str(cwd)
            if args[0] == "rev-parse" and "@{u}" in args:
                return 0, "origin/main"
            if args[0] == "rev-parse":
                return 0, local
            if args[0] == "ls-remote":
                return 0, f"{remote}\trefs/heads/main"
            if args[0] == "merge-base":
                return (0, "") if ancestor else (1, "")
            return 1, ""
        return run

    def test_a_store_that_is_merely_ahead_is_not_told_to_update(self):
        """`freya update` refuses a diverged store with exit 2, so warning
        "has moved — run `freya update`" over a local commit sent every
        contributor to a command that cannot succeed."""
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp).resolve()
            checks = freya_cli.doctor_checks(
                root=root, targets={},
                run=self._runner(local="aaaa", remote="bbbb", ancestor=True))
            status = next(c for c in checks if c[0] == "updates")
            self.assertEqual(status[1], "ok")
            self.assertIn("ahead", status[2])

    def test_a_genuinely_moved_upstream_still_warns(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp).resolve()
            checks = freya_cli.doctor_checks(
                root=root, targets={},
                run=self._runner(local="aaaa", remote="bbbb", ancestor=False))
            status = next(c for c in checks if c[0] == "updates")
            self.assertEqual(status[1], "warn")
            self.assertIn("has moved", status[2])


class DoctorAgentsTest(unittest.TestCase):
    def _store_and_agent(self, tmp):
        root = Path(tmp).resolve()
        store = root / "store"
        (store / "bin").mkdir(parents=True)
        for name in ("freya-status",):
            d = store / "skills" / name
            d.mkdir(parents=True)
            (d / "SKILL.md").write_text(f"---\nname: {name}\ndescription: d\n---\n",
                                        encoding="utf-8")
        agent = root / "agent"
        agent.mkdir()
        return store, agent

    def _check(self, checks, label):
        return next((c for c in checks if c[0] == label), None)

    def test_reports_the_install_mode(self):
        with tempfile.TemporaryDirectory() as tmp:
            store, agent = self._store_and_agent(tmp)
            (agent / "freya-status").symlink_to(store / "skills" / "freya-status")
            checks = freya_cli.doctor_checks(store, targets={"claude": agent})
            self.assertEqual(self._check(checks, "agents")[1], "ok")
            self.assertIn("claude (1, symlink)", self._check(checks, "agents")[2])

    def test_warns_about_a_link_into_a_moved_store(self):
        with tempfile.TemporaryDirectory() as tmp:
            store, agent = self._store_and_agent(tmp)
            stale_target = Path(tmp).resolve() / "old" / "skills" / "freya-status"
            (agent / "freya-status").symlink_to(stale_target)
            checks = freya_cli.doctor_checks(store, targets={"claude": agent})
            orphaned = self._check(checks, "orphaned entries")
            self.assertEqual(orphaned[1], "warn")
            self.assertIn(str(stale_target), orphaned[2])
            self.assertIn("freya install --force", orphaned[2])

    def test_warns_about_a_skill_deleted_from_this_store(self):
        with tempfile.TemporaryDirectory() as tmp:
            store, agent = self._store_and_agent(tmp)
            (agent / "freya-ghost").symlink_to(store / "skills" / "freya-ghost")
            checks = freya_cli.doctor_checks(store, targets={"claude": agent})
            orphaned = self._check(checks, "orphaned entries")
            self.assertEqual(orphaned[1], "warn")
            self.assertIn("freya update", orphaned[2])
            self.assertNotIn("checkout moved", orphaned[2])
            self.assertNotIn("different store", orphaned[2])

    def test_warns_about_both_kinds_at_once(self):
        with tempfile.TemporaryDirectory() as tmp:
            store, agent = self._store_and_agent(tmp)
            stale_target = Path(tmp).resolve() / "old" / "skills" / "freya-status"
            (agent / "freya-status").symlink_to(stale_target)
            (agent / "freya-ghost").symlink_to(store / "skills" / "freya-ghost")
            checks = freya_cli.doctor_checks(store, targets={"claude": agent})
            orphaned = self._check(checks, "orphaned entries")
            self.assertEqual(orphaned[1], "warn")
            self.assertIn("checkout moved", orphaned[2])
            self.assertIn("freya update", orphaned[2])

    def test_orphan_skill_clause_names_the_path(self):
        """DoD: doctor names an orphaned entry with the path it points at —
        the stale-store clause always did; orphan-skill printed only the
        entry name."""
        with tempfile.TemporaryDirectory() as tmp:
            store, agent = self._store_and_agent(tmp)
            ghost_target = store / "skills" / "freya-ghost"
            (agent / "freya-ghost").symlink_to(ghost_target)
            checks = freya_cli.doctor_checks(store, targets={"claude": agent})
            orphaned = self._check(checks, "orphaned entries")
            self.assertIn(str(ghost_target), orphaned[2])

    def test_reports_an_unauditable_agent_instead_of_the_wrong_remedy(self):
        """doctor used to swallow an unauditable agent directory (`except
        (OSError, ValueError): continue`) and then say "the suite is not
        installed for any agent — run freya install", which is the wrong
        remedy for a directory that turned unreadable. It must name the
        agent and the error instead."""
        with tempfile.TemporaryDirectory() as tmp:
            store, agent = self._store_and_agent(tmp)
            (agent / "freya-status").symlink_to(store / "skills" / "freya-status")

            def explode(*_a, **_k):
                raise OSError("permission denied")

            with unittest.mock.patch.object(installer, "audit_agent", explode):
                checks = freya_cli.doctor_checks(store, targets={"claude": agent})
            agent_check = self._check(checks, "agent: claude")
            self.assertIsNotNone(agent_check)
            self.assertEqual(agent_check[1], "warn")
            self.assertIn("permission denied", agent_check[2])

    def test_warns_about_an_occupied_entry_shadowing_a_current_skill(self):
        """A `foreign`/`occupied` entry whose name IS a skill this store
        still has means that skill is not installed for this agent — today
        relink prints "left alone" and doctor's orphan clause never
        mentioned it at all, so the install looked complete when it was not."""
        with tempfile.TemporaryDirectory() as tmp:
            store, agent = self._store_and_agent(tmp)
            (agent / "freya-status").mkdir()  # occupied: a bare dir, not ours
            checks = freya_cli.doctor_checks(store, targets={"claude": agent})
            orphaned = self._check(checks, "orphaned entries")
            self.assertEqual(orphaned[1], "warn")
            self.assertIn("freya-status", orphaned[2])
            self.assertIn("not installed", orphaned[2])
            self.assertIn("move it aside", orphaned[2])

    def test_warns_about_a_foreign_symlink_shadowing_a_current_skill(self):
        with tempfile.TemporaryDirectory() as tmp:
            store, agent = self._store_and_agent(tmp)
            (agent / "freya-status").symlink_to(Path(tmp).resolve() / "elsewhere")
            checks = freya_cli.doctor_checks(store, targets={"claude": agent})
            orphaned = self._check(checks, "orphaned entries")
            self.assertEqual(orphaned[1], "warn")
            self.assertIn("freya-status", orphaned[2])
            self.assertIn("not installed", orphaned[2])
            self.assertIn("freya install --force", orphaned[2])

    def test_a_foreign_entry_naming_no_current_skill_is_not_called_shadowed(self):
        """A stray freya-* entry that names nothing in the store isn't
        shadowing anything — it must not get the "not installed" wording,
        which would misleadingly imply a skill of that name exists."""
        with tempfile.TemporaryDirectory() as tmp:
            store, agent = self._store_and_agent(tmp)
            (agent / "freya-other").symlink_to(Path(tmp).resolve() / "elsewhere")
            checks = freya_cli.doctor_checks(store, targets={"claude": agent})
            orphaned = self._check(checks, "orphaned entries")
            self.assertEqual(orphaned[1], "ok")

    def test_reports_a_copy_install_as_installed(self):
        with tempfile.TemporaryDirectory() as tmp:
            store, agent = self._store_and_agent(tmp)
            installer.apply_plan(
                installer.plan_agent(store, "claude", target_dir=agent), copy=True)
            checks = freya_cli.doctor_checks(store, targets={"claude": agent})
            self.assertEqual(self._check(checks, "agents")[1], "ok")
            self.assertIn("claude (1, copy)", self._check(checks, "agents")[2])

    def test_says_nothing_is_installed_when_the_directory_is_empty(self):
        with tempfile.TemporaryDirectory() as tmp:
            store, agent = self._store_and_agent(tmp)
            checks = freya_cli.doctor_checks(store, targets={"claude": agent})
            self.assertEqual(self._check(checks, "agents")[1], "warn")
            self.assertEqual(self._check(checks, "orphaned entries")[1], "ok")

    def test_duplicate_install_check_honors_targets_not_the_real_home(self):
        """The `duplicate install` check used to call `installer.plan_agent(root,
        "claude")` with no `target_dir`, so it consulted the real ~/.claude no
        matter what `targets` said. It must now be given the same tmp directory
        every other check in this class already uses."""
        with tempfile.TemporaryDirectory() as tmp:
            store, agent = self._store_and_agent(tmp)
            real_plan_agent = installer.plan_agent
            calls = []

            def spy(store_arg, agent_name, target_dir=None):
                calls.append(target_dir)
                return real_plan_agent(store_arg, agent_name, target_dir=target_dir)

            with unittest.mock.patch.object(installer, "plan_agent", spy):
                freya_cli.doctor_checks(store, targets={"claude": agent})
            self.assertEqual(calls, [agent])

    def test_duplicate_install_check_is_skipped_when_claude_is_not_a_target(self):
        with tempfile.TemporaryDirectory() as tmp:
            store, _agent = self._store_and_agent(tmp)
            checks = freya_cli.doctor_checks(store, targets={})
            labels = [label for label, _, _ in checks]
            self.assertNotIn("duplicate install", labels)


class DoctorUpdatesCheckTest(unittest.TestCase):
    """The `updates` check, exercised through an injected `run=` — never the
    real network. Covers every branch of doctor_checks()'s update ladder."""

    def _check(self, checks, label):
        return next(c for c in checks if c[0] == label)

    def _runner(self, *, is_checkout=True, has_upstream=True, local="aaaa", remote="aaaa"):
        def run(args, cwd, timeout=None):
            if args[0] == "rev-parse" and args[1] == "--show-toplevel":
                return (0, str(cwd)) if is_checkout else (1, "")
            if args[0] == "rev-parse" and "@{u}" in args:
                return (0, "origin/main") if has_upstream else (1, "")
            if args[0] == "rev-parse":
                return 0, local
            if args[0] == "ls-remote":
                return (0, f"{remote}\trefs/heads/main") if remote is not None else (1, "")
            return 1, ""
        return run

    def _checks(self, root, **runner_kwargs):
        # targets={} keeps this from ever touching the real ~/.claude or
        # ~/.agents — only the `updates` check is under test here.
        return freya_cli.doctor_checks(root=root, targets={}, run=self._runner(**runner_kwargs))

    def test_up_to_date(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp).resolve()
            checks = self._checks(root, local="aaaa", remote="aaaa")
            self.assertEqual(self._check(checks, "updates"),
                             ("updates", "ok", "up to date with origin/main"))

    def test_remote_moved(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp).resolve()
            checks = self._checks(root, local="aaaa", remote="bbbb")
            status = self._check(checks, "updates")
            self.assertEqual(status[1], "warn")
            self.assertIn("has moved", status[2])

    def test_no_upstream(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp).resolve()
            checks = self._checks(root, has_upstream=False)
            self.assertEqual(self._check(checks, "updates"),
                             ("updates", "warn", "this branch has no upstream"))

    def test_unreachable_remote(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp).resolve()
            checks = self._checks(root, remote=None)
            status = self._check(checks, "updates")
            self.assertEqual(status[1], "warn")
            self.assertIn("could not reach", status[2])

    def test_not_a_git_checkout(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp).resolve()
            checks = self._checks(root, is_checkout=False)
            status = self._check(checks, "updates")
            self.assertEqual(status[1], "warn")
            self.assertIn("not a git checkout", status[2])

    def test_opt_out_is_still_honored_and_makes_no_git_call(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp).resolve()
            calls = []

            def counting_run(args, cwd, timeout=None):
                calls.append(args)
                return 1, ""

            with unittest.mock.patch.dict(os.environ, {"FREYA_NO_UPDATE_CHECK": "1"}):
                checks = freya_cli.doctor_checks(root=root, targets={}, run=counting_run)
            self.assertEqual(calls, [])
            status = self._check(checks, "updates")
            self.assertEqual(status[1], "ok")


class NotifyWiringTest(unittest.TestCase):
    def test_the_notice_precedes_an_ordinary_command(self):
        # The only positive test of this wiring: every other test in this class
        # asserts the notice is NOT printed for update/install/doctor, or checks
        # only an exit code. Deleting the `if name not in NO_NOTIFY:` block in
        # freya_cli.main entirely used to leave the whole suite green — this is
        # the one test that actually fails when the block is gone.
        seen = []
        with unittest.mock.patch("updater.notify", lambda *a, **k: seen.append(a)):
            with unittest.mock.patch.object(freya_cli, "run_command", return_value=0):
                freya_cli.main(["code-graph"])
        self.assertEqual(seen, [(freya_cli.suite_root(),)])

    def test_an_exploding_notify_does_not_change_the_exit_code(self):
        def boom(*_a, **_k):
            raise RuntimeError("boom")

        with unittest.mock.patch("updater.notify", boom):
            out, err = io.StringIO(), io.StringIO()
            with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
                code = freya_cli.main(["definitely-not-a-command"])
        self.assertEqual(code, 2)

    def test_the_notice_is_not_printed_for_update_itself(self):
        seen = []
        with unittest.mock.patch("updater.notify", lambda *a, **k: seen.append(a)):
            with unittest.mock.patch("updater.update", return_value=0):
                out, err = io.StringIO(), io.StringIO()
                with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
                    freya_cli.main(["update"])
        self.assertEqual(seen, [])

    def test_the_notice_is_not_printed_for_doctor_either(self):
        # doctor asks the update question itself, unthrottled — notifying
        # first would pay for two remote calls on one diagnostic.
        seen = []
        with unittest.mock.patch("updater.notify", lambda *a, **k: seen.append(a)):
            with unittest.mock.patch("updater.git", _offline_git):
                out = io.StringIO()
                with contextlib.redirect_stdout(out):
                    freya_cli.main(["doctor"])
        self.assertEqual(seen, [])


class UpdateDispatchTest(unittest.TestCase):
    """`freya update`'s own argument validation — separate from what
    updater.update() does once it is called, which UpdateTest in
    test_updater.py covers."""

    def _run(self, argv):
        out, err = io.StringIO(), io.StringIO()
        with unittest.mock.patch("updater.notify", lambda *a, **k: None):
            with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
                code = freya_cli.main(argv)
        return code, out.getvalue(), err.getvalue()

    def test_dry_run_with_a_value_is_rejected_not_silently_run_for_real(self):
        # "--dry-run" in rest used to also match "--dry-run=1", so this used
        # to perform a real update instead of a preview.
        with unittest.mock.patch("updater.update") as ran:
            code, _, err = self._run(["update", "--dry-run=1"])
        ran.assert_not_called()
        self.assertEqual(code, 2)
        self.assertIn("usage: freya update", err)

    def test_an_unknown_flag_is_rejected(self):
        with unittest.mock.patch("updater.update") as ran:
            code, _, err = self._run(["update", "--force"])
        ran.assert_not_called()
        self.assertEqual(code, 2)
        self.assertIn("usage: freya update", err)

    def test_plain_dry_run_still_works(self):
        with unittest.mock.patch("updater.update", return_value=0) as ran:
            code, _, _ = self._run(["update", "--dry-run"])
        self.assertEqual(code, 0)
        ran.assert_called_once_with(freya_cli.suite_root(), dry_run=True)

    def test_no_arguments_still_works(self):
        with unittest.mock.patch("updater.update", return_value=0) as ran:
            code, _, _ = self._run(["update"])
        self.assertEqual(code, 0)
        ran.assert_called_once_with(freya_cli.suite_root(), dry_run=False)


class InitDispatchTest(unittest.TestCase):
    """`freya init`'s own argument validation — mirrors UpdateDispatchTest.

    `"--dry-run" in rest` used to also match `--dry-run=1` and any other
    stray argument, so a malformed flag was silently dropped rather than
    rejected, performing a real write when a preview was intended.
    """

    def _run(self, argv):
        out, err = io.StringIO(), io.StringIO()
        with unittest.mock.patch("updater.notify", lambda *a, **k: None):
            with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
                code = freya_cli.main(argv)
        return code, out.getvalue(), err.getvalue()

    def test_dry_run_with_a_value_is_rejected_not_silently_run_for_real(self):
        with unittest.mock.patch("agents_md.init") as ran:
            code, _, err = self._run(["init", "--dry-run=1"])
        ran.assert_not_called()
        self.assertEqual(code, 2)
        self.assertIn("usage: freya init", err)

    def test_an_unknown_flag_is_rejected(self):
        with unittest.mock.patch("agents_md.init") as ran:
            code, _, err = self._run(["init", "--unknown-flag"])
        ran.assert_not_called()
        self.assertEqual(code, 2)
        self.assertIn("usage: freya init", err)

    def test_two_positionals_are_rejected(self):
        with unittest.mock.patch("agents_md.init") as ran:
            code, _, err = self._run(["init", "a", "b"])
        ran.assert_not_called()
        self.assertEqual(code, 2)
        self.assertIn("usage: freya init", err)

    def test_dispatches_to_agents_md_init(self):
        with unittest.mock.patch("agents_md.init", return_value=0) as ran:
            code, _, _ = self._run(["init", "/tmp/some-project"])
        self.assertEqual(code, 0)
        ran.assert_called_once_with(freya_cli.suite_root(), "/tmp/some-project",
                                     dry_run=False)

    def test_plain_dry_run_still_works(self):
        with unittest.mock.patch("agents_md.init", return_value=0) as ran:
            code, _, _ = self._run(["init", "--dry-run"])
        self.assertEqual(code, 0)
        ran.assert_called_once_with(freya_cli.suite_root(), ".", dry_run=True)

    def test_init_is_listed_in_the_builtins(self):
        # A bare `assertIn("init", ...)` would also pass on the word
        # "install" alone, never actually checking that `init` has its own
        # built-in line.
        self.assertIn(
            "  init      Write a freya-devkit section into a project's AGENTS.md",
            freya_cli.format_help(),
        )


if __name__ == "__main__":
    unittest.main()
