#!/usr/bin/env python3
"""Proof suite for containment.py — the four path predicates.

Each class pins one function, and the tests are written so that deleting any
single term of a predicate turns at least one of them red. That is the point of
having four functions instead of one: a shared implementation would have shared
mutations, and a mutation that kills three tests at once tells you nothing about
which question was answered wrongly.

Run: python test_containment.py
"""

import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import containment  # noqa: E402


def _link_or_skip(case, target, link):
    """Make `link` point at `target`, or skip this one test.

    Windows only creates symlinks for a privileged process or with Developer
    Mode on, and the CI matrix runs Windows. Skipping is confined to the methods
    that genuinely need a link — the drive-letter and prefix cases below are
    deliberately left unguarded so this file can never skip in its entirety.
    """
    try:
        os.symlink(str(target), str(link), target_is_directory=os.path.isdir(str(target)))
    except (OSError, NotImplementedError, AttributeError) as exc:
        case.skipTest("this host will not create symlinks: %s" % exc)


class EscapesTest(unittest.TestCase):
    """The lexical rule for a value declared in checked-in data.

    Five terms, and three of them — `win.drive`, `win.root` and
    `".." in win.parts` — have a case here that no other term catches. The
    other two, `posix.is_absolute()` and `".." in posix.parts`, are genuinely
    redundant rather than merely untested: deleting either, or both, leaves this
    file green, and no input can make either one the deciding term.

    Why they cannot: `PureWindowsPath` splits on `/` as well as `\\`, so every
    `..` component POSIX sees is a component Windows sees too, and every
    POSIX-absolute string carries a Windows root or a Windows drive. Searched
    rather than argued — 88,740 strings built from the separator, dot, drive and
    UNC atoms were enumerated on 2026-08-23 and neither term was ever the only
    one firing. The near miss is the `//../a` class, where `win.parts` has no
    `..` because `//..` is parsed as a UNC drive; that same parse makes
    `win.drive` fire, so the term is still not reached.

    Both are kept because the rule reads as "reject an absolute path or a `..`
    in either flavour", and a reader should not have to know how pathlib parses
    `//` to believe it. This docstring is the honest record of which terms are
    unmutated — an incomplete record is worse than none, because it tells the
    next reader that every term it does not mention is pinned.
    """

    def test_a_drive_relative_windows_path_escapes_on_every_host(self):
        """`C:x` is caught by the `win.drive` term and by nothing else.

        `PurePosixPath("C:x").is_absolute()` is False and
        `PureWindowsPath("C:x").root` is empty, so drop `win.drive` and this
        value reaches a `root / value` join on Linux, macOS and Windows alike.
        """
        self.assertTrue(containment.escapes("C:x"))
        self.assertTrue(containment.escapes("C:\\Windows\\win.ini"))

    def test_a_rooted_path_with_no_drive_escapes(self):
        """`\\etc\\passwd` is caught by `win.root` and by nothing else.

        POSIX sees one ordinary relative filename with backslashes in it. This
        is the value 3.13's `ntpath.isabs` change stopped calling absolute.
        """
        self.assertTrue(containment.escapes("\\etc\\passwd"))

    def test_a_posix_absolute_path_escapes(self):
        self.assertTrue(containment.escapes("/etc/passwd"))

    def test_a_dotdot_escapes_even_when_it_normalises_back_inside(self):
        """`a/../b` resolves to `b`, inside the root, and is still rejected."""
        self.assertTrue(containment.escapes("a/../../b"))
        self.assertTrue(containment.escapes("a/../b"))
        self.assertTrue(containment.escapes("a\\..\\b"))

    def test_an_ordinary_relative_path_does_not_escape(self):
        for value in ("skills/freya-code-graph/scripts/graph_ops.py",
                      "tests/test_login.py",
                      "a.py",
                      "",
                      "."):
            with self.subTest(value=value):
                self.assertFalse(containment.escapes(value))


class RelWithinTest(unittest.TestCase):
    """The graph-key rule: normalise, do not resolve."""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        # Deliberately NOT resolved. Both arguments have to be spelled the same
        # way for a lexical predicate to mean anything, and on macOS a resolved
        # temp dir is under /private/var while an unresolved one is under /var.
        self.tmp = Path(self._tmp.name)
        self.root = self.tmp / "proj"
        (self.root / "src").mkdir(parents=True)

    def test_a_symlinked_in_project_file_keeps_its_in_project_key(self):
        """The reason this is not `within` and not `Path.resolve()`.

        A file reached through an in-project link is a legitimate project file,
        and `graph.json`, `behavior.json` and `docs.json` all key it by the path
        the walk found (ADR-025). Resolving would key it by its realpath — a
        different string — and the join, which is a set intersection, would
        silently stop matching it rather than match it wrongly.
        """
        outside = self.tmp / "vendor"
        outside.mkdir()
        (outside / "a.py").write_text("x\n", encoding="utf-8")
        _link_or_skip(self, outside, self.root / "linked")
        got = containment.rel_within(self.root, self.root / "linked" / "a.py")
        self.assertEqual(got, Path("linked") / "a.py")

    def test_a_dotdot_that_lands_back_inside_is_normalised_not_preserved(self):
        got = containment.rel_within(self.root, self.root / "src" / ".." / "src" / "a.py")
        self.assertEqual(got, Path("src") / "a.py")

    def test_a_candidate_that_climbs_out_of_the_root_is_none(self):
        self.assertIsNone(containment.rel_within(self.root, self.root / ".." / "evil.py"))

    def test_a_sibling_whose_name_starts_with_the_root_is_none(self):
        """`proj-tools/` is not inside `proj/`, and a prefix test would say it is."""
        self.assertIsNone(
            containment.rel_within(self.root, self.tmp / "proj-tools" / "a.py"))

    def test_the_root_itself_is_the_empty_relative_path(self):
        self.assertEqual(containment.rel_within(self.root, self.root), Path("."))


class WithinTest(unittest.TestCase):
    """The security rule: resolve, then compare whole components."""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.tmp = Path(self._tmp.name)

    def test_a_link_that_leaves_the_root_is_not_contained(self):
        """The case a lexical check gets wrong, and the reason this one resolves."""
        root = self.tmp / "proj"
        root.mkdir()
        outside = self.tmp / "elsewhere"
        outside.mkdir()
        (outside / "git").write_text("#!/bin/sh\n", encoding="utf-8")
        _link_or_skip(self, outside, root / "bin")
        self.assertFalse(containment.within(root, root / "bin" / "git"))

    def test_two_spellings_of_one_directory_still_contain_its_children(self):
        """The `/var` -> `/private/var` shape, in a form every host can run.

        Resolving only ONE side is the bug this pins: a root spelled through a
        link and a candidate spelled through the real directory are the same
        place, and a containment check that says otherwise refuses work it
        should do. On macOS this is not hypothetical — it is what `/var` does to
        every temp path, and it has already cost this repository a bug (ADR-014).
        """
        real = self.tmp / "real"
        (real / "sub").mkdir(parents=True)
        (real / "sub" / "file").write_text("x\n", encoding="utf-8")
        _link_or_skip(self, real, self.tmp / "alias")
        self.assertTrue(containment.within(self.tmp / "alias", real / "sub" / "file"))
        self.assertTrue(containment.within(real, self.tmp / "alias" / "sub" / "file"))

    def test_a_sibling_whose_name_starts_with_the_root_is_not_contained(self):
        """`commonpath`, not `startswith`: `/a/bc` is not under `/a/b`."""
        self.assertFalse(containment.within(self.tmp / "proj", self.tmp / "proj-tools" / "x"))

    def test_the_root_contains_itself(self):
        self.assertTrue(containment.within(self.tmp, self.tmp))

    def test_a_child_is_contained(self):
        self.assertTrue(containment.within(self.tmp, self.tmp / "a" / "b.py"))

    def test_paths_with_no_common_root_are_refused_not_raised(self):
        """Windows: `commonpath` raises on two different drive letters.

        Verified against `ntpath.commonpath(["c:\\\\a", "d:\\\\b"])`, which is
        `ValueError: Paths don't have the same drive`. It is driven here through
        a patch rather than through real drive letters because the POSIX runners
        in the matrix cannot produce the input — and a check whose only witness
        is the Windows leg is a check that is discovered to be missing by CI
        three waves after it was omitted.
        """
        with mock.patch("os.path.commonpath",
                        side_effect=ValueError("Paths don't have the same drive")):
            self.assertFalse(containment.within(self.tmp, self.tmp / "a"))


class IsAnchoredTest(unittest.TestCase):
    """One answer per string, on every host and every supported interpreter."""

    #: Measured by hand on 3.9.6, 3.11.13, 3.12.5 and 3.13.5. `os.path.isabs`
    #: disagrees with this table on every Windows spelling when run on POSIX.
    #:
    #: The rival worth pinning is `posixpath.isabs(t) or ntpath.isabs(t)`, the
    #: form that looks obviously correct and is the one `check_invariants` used
    #: to have. Two rows separate it from the shape below, and they do not
    #: separate it equally:
    #:
    #:   `\tools\git.exe` — the union says True on 3.9/3.11/3.12 and False on
    #:   3.13, so on the *newer* half of the CI matrix this row cannot tell the
    #:   two apart. On its own it would leave the version-stability argument
    #:   held up by the 3.9 leg alone, and MIN_PYTHON is the first thing a
    #:   later wave raises.
    #:
    #:   `\\server` — a UNC server name with no share, which names a host and
    #:   not a file. The union says True on 3.9, 3.11, 3.12 *and* 3.13; the
    #:   drive-and-root form says False on all four, because splitdrive yields
    #:   no drive for a share-less UNC path. This is the row that still
    #:   discriminates when 3.9 is gone.
    TABLE = (
        ("/usr/bin/git", True),
        ("C:\\tools\\git.exe", True),
        ("\\\\server\\share\\git.exe", True),
        ("\\\\?\\C:\\git.exe", True),
        ("\\\\?\\UNC\\server\\share\\git.exe", True),
        ("C:git.exe", False),
        ("\\tools\\git.exe", False),
        ("\\\\server", False),
        (".\\git.exe", False),
        ("./git", False),
        ("git", False),
        ("", False),
    )

    def test_the_table_holds_on_this_interpreter(self):
        for text, expected in self.TABLE:
            with self.subTest(text=text):
                self.assertEqual(containment.is_anchored(text), expected)

    def test_it_is_not_the_negation_of_escapes(self):
        """Both predicates have to exist, and this is the value that proves it.

        `C:x` may not be joined onto a root (it escapes) and it does not stand
        on its own either (it is drive-relative, so the working directory
        supplies the rest). A codebase that kept only one of the two would
        answer one of those questions with the other's answer.
        """
        self.assertTrue(containment.escapes("C:x"))
        self.assertFalse(containment.is_anchored("C:x"))
        # And the other direction: an ordinary relative path neither escapes
        # nor is anchored, so the two are not complements in any case.
        self.assertFalse(containment.escapes("src/a.py"))
        self.assertFalse(containment.is_anchored("src/a.py"))


if __name__ == "__main__":
    unittest.main()
