#!/usr/bin/env python3
"""Proof suite for exec_path.py — the binary resolver.

The module has one load-bearing rule and it is easy to write backwards, so most
of this file is about the difference between refusing a relative resolution and
tidying it up into an absolute one. The second shape looks like a fix, passes a
reading of the security report, and hands the attacker's binary to the operating
system with a fully-qualified name.

Run: python test_exec_path.py
"""

import os
import shutil
import stat
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import exec_path  # noqa: E402


def _plant(directory, name):
    """Write an executable `name` into `directory` and return its path.

    On Windows a bare command is resolved through PATHEXT, so the `.exe`
    spelling is written too — otherwise the planted file is not what
    `shutil.which` would find and the test would be measuring PATHEXT rather
    than containment.
    """
    directory.mkdir(parents=True, exist_ok=True)
    primary = directory / name
    written = [primary]
    if os.name == "nt":
        written.append(directory / (name + ".exe"))
    for path in written:
        path.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
        path.chmod(path.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)
    return primary


class RefusalTest(unittest.TestCase):
    """A resolution that is not already absolute is refused, never absolutised."""

    def test_a_relative_resolution_is_refused_not_made_absolute(self):
        """The Windows working-directory hit, and any relative PATH component.

        Each of these is what `shutil.which` hands back when the search found
        something the working directory chose. Running `abspath` over any of
        them produces a convincing absolute path to exactly the wrong file.
        """
        for found in (".\\graphify.exe", "./graphify", "graphify",
                      "C:graphify.exe", "\\tools\\graphify.exe"):
            with self.subTest(found=found):
                with mock.patch("shutil.which", return_value=found):
                    got = exec_path.resolve("graphify")
                self.assertIsNone(got.path)
                self.assertIn("not an absolute path", got.reason)
                # The refused spelling is quoted back, which is what shows it
                # was rejected rather than rewritten.
                self.assertIn(repr(found), got.reason)

    def test_an_absolute_resolution_is_returned_unchanged(self):
        for found in ("/usr/bin/git", "C:\\Program Files\\Git\\git.exe"):
            with self.subTest(found=found):
                with mock.patch("shutil.which", return_value=found):
                    got = exec_path.resolve("git")
                self.assertEqual(got.path, found)
                self.assertIsNone(got.reason)

    def test_a_missing_program_is_reported_by_name(self):
        """The exact wording `bin/updater.py:preconditions` already prints."""
        with mock.patch("shutil.which", return_value=None):
            got = exec_path.resolve("git")
        self.assertIsNone(got.path)
        self.assertEqual(got.reason, "git is not on PATH")

    def test_which_is_called_with_exactly_one_argument(self):
        """`path=` buys nothing and would cost two passing tests.

        It does not suppress the Windows curdir insert — the insert happens
        after the default is applied, to whatever list is in hand — and
        `test_audit_adapter.py:114` and `:118` patch `shutil.which` with a
        one-parameter lambda, so a second argument turns those two into
        TypeErrors. (`:123` uses `return_value=None`, a MagicMock that accepts
        any arity, and would stay green.) Those two are hypothetical until
        `audit_adapter.detect` actually calls this resolver; this test is not,
        and it is the one that fails first if someone adds the argument back.
        """
        with mock.patch("shutil.which", side_effect=lambda b: "/usr/bin/%s" % b) as which:
            got = exec_path.resolve("git")
        self.assertEqual(got.path, "/usr/bin/git")
        self.assertEqual(which.call_args, mock.call("git"))


class ProjectContainmentTest(unittest.TestCase):
    """A scanned repository does not get to choose which binary we run."""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.tmp = Path(self._tmp.name)
        self.project = self.tmp / "scanned-project"
        self.project.mkdir()

    def test_a_program_found_inside_the_scanned_project_is_refused(self):
        """The whole defect, driven through the real `shutil.which`.

        The binary is planted at the project root and PATH is set to it, which
        is what a repository shipping its own `graphify` plus a direnv or a
        `node_modules/.bin` entry produces. Both halves matter: with
        `project_dir` the resolution is refused, and without it the same call
        succeeds — so the test is about containment and not about the file being
        unfindable.

        The `allowed` half is asserted by *directory*, never by filename. A bare
        command on Windows is resolved through PATHEXT, so `which` returns
        `graphify.EXE` and never the extensionless spelling `_plant` returns:
        measured against the real stdlib win32 branch on 3.9.6, 3.11.13, 3.12.5
        and 3.13.5, all four hand back the `.EXE`. An `assertEqual(...name,
        planted.name)` here is a PATHEXT assertion wearing a containment
        assertion's clothes, and it fails on both Windows legs of the matrix
        while passing everywhere the author can run it.
        """
        planted = _plant(self.project, "graphify")
        with mock.patch.dict(os.environ, {"PATH": str(self.project)}):
            if shutil.which("graphify") is None:
                self.skipTest("this host's shutil.which will not find the planted file")
            refused = exec_path.resolve("graphify", project_dir=self.project)
            allowed = exec_path.resolve("graphify")
        self.assertIsNone(refused.path)
        self.assertIn("inside the project being scanned", refused.reason)
        self.assertIn(str(self.project), refused.reason)
        self.assertIsNotNone(allowed.path)
        self.assertEqual(Path(allowed.path).parent, self.project)
        self.assertEqual(Path(allowed.path).stem, planted.name)

    def test_the_refusal_does_not_need_a_real_file(self):
        """The same branch, with no dependency on PATHEXT or an exec bit.

        `test_a_program_found_inside_the_scanned_project_is_refused` can skip on
        a host whose `shutil.which` will not match an extensionless file. This
        one cannot, so the branch is never unproven.
        """
        inside = self.project / "bin" / "graphify"
        with mock.patch("shutil.which", return_value=str(inside)):
            got = exec_path.resolve("graphify", project_dir=self.project)
        self.assertIsNone(got.path)
        self.assertIn("inside the project being scanned", got.reason)

    def test_a_program_outside_the_scanned_project_is_allowed(self):
        outside = self.tmp / "tools" / "graphify"
        with mock.patch("shutil.which", return_value=str(outside)):
            got = exec_path.resolve("graphify", project_dir=self.project)
        self.assertEqual(got.path, str(outside))
        self.assertIsNone(got.reason)

    def test_no_project_dir_means_no_containment_question(self):
        inside = self.project / "graphify"
        with mock.patch("shutil.which", return_value=str(inside)):
            got = exec_path.resolve("graphify")
        self.assertEqual(got.path, str(inside))


class CurdirOptOutTest(unittest.TestCase):
    """The 3.12+ belt to the absoluteness rule's braces."""

    def setUp(self):
        # patch.dict snapshots the whole environment and restores it, including
        # the putenv side effects, so nothing here leaks into a later test.
        patcher = mock.patch.dict(os.environ)
        patcher.start()
        self.addCleanup(patcher.stop)
        os.environ.pop(exec_path.CURDIR_OPT_OUT, None)

    def test_it_is_set_on_windows(self):
        with mock.patch.object(exec_path, "_WINDOWS", True):
            exec_path._suppress_curdir_search()
        self.assertEqual(os.environ.get(exec_path.CURDIR_OPT_OUT), "1")

    def test_it_is_never_set_off_windows(self):
        """Nothing reads it elsewhere, and an unexplained variable in a POSIX
        environment is inherited by every child process this suite spawns."""
        with mock.patch.object(exec_path, "_WINDOWS", False):
            exec_path._suppress_curdir_search()
        self.assertNotIn(exec_path.CURDIR_OPT_OUT, os.environ)

    def test_an_operators_own_value_wins(self):
        """`setdefault`, not assignment: only the name's presence is read by the
        API, so overwriting an operator's value changes nothing except whose
        decision the environment records."""
        os.environ[exec_path.CURDIR_OPT_OUT] = "set-by-the-operator"
        with mock.patch.object(exec_path, "_WINDOWS", True):
            exec_path._suppress_curdir_search()
        self.assertEqual(os.environ[exec_path.CURDIR_OPT_OUT], "set-by-the-operator")

    def test_resolve_asks_for_the_opt_out_before_searching(self):
        """The order is the point: asking after the search has already happened
        would leave the working-directory entry in the list that was used."""
        calls = []
        with mock.patch.object(exec_path, "_suppress_curdir_search",
                               side_effect=lambda: calls.append("suppress")):
            with mock.patch("shutil.which",
                            side_effect=lambda b: calls.append("which") or "/usr/bin/git"):
                exec_path.resolve("git")
        self.assertEqual(calls, ["suppress", "which"])


if __name__ == "__main__":
    unittest.main()
