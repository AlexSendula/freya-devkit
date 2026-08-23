#!/usr/bin/env python3
"""Proof suite for settings.py — the committed per-project settings file.

`settings.py` had no sibling test module; it was covered indirectly through
`test_substrate.py::TestSettings` (the backend layering) and through
`test_graph_ops.py` (a verdict reaching a build). Neither of those asks the
question this file exists for, and the gap had a hole in it: `normalise_dir_key`
refused the two bare strings `.` and `..` and let every *other* escaping key
through, so `{"directories": {"../shared": "source"}}` in a committed settings
file made the graph read a sibling tree and, walking back in through `..`, gave
every in-project file a second node — with nothing printed and `validate_graph`
returning clean. That last part is dated: measured at `abd1de3`. On the tree
this suite ships in, `validate_graph` does report those keys as not
project-relative (ADR-025) — and writes the graph anyway, after the sibling
file has been read, which is why the refusal below is still the thing that
closes it.

So the centre of gravity here is the directory key: the one value in this file
that a consumer joins onto the project root. The backend-precedence tests stay
where they are rather than being copied down here.

Run: python test_settings.py
"""

import ntpath
import os
import posixpath
import shutil
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import settings  # noqa: E402

#: Keys that must never survive, and the reason each one is here. Split by what
#: makes them wrong rather than lumped together, because the two halves failed
#: for different reasons and a single fix that only catches one of them would
#: still leave a live escape on the other leg of the CI matrix.
#:
#: The `..` half is what was measured escaping on 2026-08-23. The drive half is
#: its Windows sibling: the fold turns `D:\secrets` into `D:/secrets`, the drive
#: letter survives, and joining a bare drive onto a project discards the project.
_ESCAPING = (
    '..',
    '../shared',
    '../../etc/passwd',
    'docs/../../etc',
    'a/../../b',
    './../shared',
    '..\\shared',
    'D:\\secrets',
    'D:/secrets',
    'C:/Windows',
    'C:',
    'C:secrets',
)

#: Spellings a person actually types, and the single key each has to fold to.
#: These are the promise `normalise_dir_key` has always made, and they are here
#: so that tightening the rule cannot quietly break the fold — the obvious wrong
#: fix is to run the escape test *before* normalising, which turns `/docs/` and
#: `a/../b` red and nothing else.
_FOLDS = {
    'docs': 'docs',
    'docs/': 'docs',
    './docs': 'docs',
    '/docs/': 'docs',
    'docs//literate': 'docs/literate',
    'docs\\literate': 'docs/literate',
    '  docs/literate  ': 'docs/literate',
    'a/../b': 'b',
    'packages/legacy/': 'packages/legacy',
}

#: Values that name no directory at all.
_EMPTY = ('', '   ', None, '.', './', '/', '//', 0)

#: The cost of judging in both flavours, written down so it cannot drift either
#: way. A first component of one character then `:` is a Windows drive, so these
#: are refused even though every one of them is a legal POSIX directory name.
_DRIVE_SHAPED = ('a:b', 'a:b/c', 'x:', '1:x')

#: And the other side of that boundary: two characters before the colon is not a
#: drive, and neither is a colon in any component but the first. These have to
#: keep working, or the price of the rule is much larger than the docstring says.
_COLON_KEPT = {
    'my:dir': 'my:dir',
    'docs:v2': 'docs:v2',
    '2024:notes': '2024:notes',
    'docs/a:b': 'docs/a:b',
    'src/C:x': 'src/C:x',
}


class NormaliseDirKeyTest(unittest.TestCase):
    """The key space: POSIX, relative, and inside this project.

    Every consumer of a directory key either joins it onto the project root or
    matches it as the prefix of a project-relative path, so a key with no
    reading as a project-relative path is not a narrower answer — it is a
    different, silently wrong one.
    """

    def test_the_spellings_of_one_directory_fold_to_one_key(self):
        for spelling, expected in _FOLDS.items():
            with self.subTest(spelling=spelling):
                self.assertEqual(settings.normalise_dir_key(spelling), expected)

    def test_a_key_that_leaves_the_project_is_refused(self):
        """The hole. Each of these was accepted before 2026-08-23.

        `'../shared'` is the one that was measured: it graphed the sibling tree
        and read the contents of files under it. The rest are the same defect
        spelled differently, and `'docs/../../etc'` is the one a rule written
        against a leading `..` would miss.
        """
        for spelling in _ESCAPING:
            with self.subTest(spelling=spelling):
                self.assertEqual(settings.normalise_dir_key(spelling), '')

    def test_a_value_that_names_no_directory_is_refused(self):
        for spelling in _EMPTY:
            with self.subTest(spelling=spelling):
                self.assertEqual(settings.normalise_dir_key(spelling), '')

    def test_an_interior_dotdot_still_folds_instead_of_being_refused(self):
        """`a/../b` and `b` are one directory and must be one key (ADR-025).

        This is why the escape test runs on the folded text and not on the text
        as written, and it is the term that separates this rule from the check a
        spec locator gets — there, `..` is refused outright because no honest
        locator needs it.
        """
        self.assertEqual(settings.normalise_dir_key('a/../b'), 'b')
        self.assertEqual(settings.normalise_dir_key('docs/literate/../engine'),
                         'docs/engine')

    def test_a_leading_slash_still_rebases_onto_the_project(self):
        """SPEC-012 fixes `/docs/` as another spelling of `docs`.

        Refusing it would be the easy over-correction: an absolute-looking key
        is not an escape here, it is a documented spelling, and a project that
        wrote one would start being told its settings file was wrong.
        """
        self.assertEqual(settings.normalise_dir_key('/docs/'), 'docs')
        self.assertEqual(settings.normalise_dir_key('/packages/legacy'),
                         'packages/legacy')

    def test_the_drive_rule_costs_one_directory_name_and_no_more(self):
        """The one legitimate POSIX key this refuses, bounded from both sides.

        `containment.escapes` judges in both path flavours so that a committed
        key means the same thing on both legs of the CI matrix, and the price is
        that a folded key whose *first* component is one character then `:` is a
        drive to `ntpath` — so a project with a top-level directory named `a:b`
        is turned away. That is accepted rather than fixed: narrowing it would
        put a second, POSIX-only containment rule in `settings.py` against
        ADR-030's single body, and buy the difference by letting `C:x` be a
        directory on Linux and a drive on Windows.

        Both halves are load-bearing, and they fail to opposite mutations.
        Replacing the predicate with a POSIX-only one turns the first loop red;
        widening it to any colon at all turns the second red.
        """
        for spelling in _DRIVE_SHAPED:
            with self.subTest(refused=spelling):
                self.assertEqual(settings.normalise_dir_key(spelling), '')
        for spelling, expected in _COLON_KEPT.items():
            with self.subTest(kept=spelling):
                self.assertEqual(settings.normalise_dir_key(spelling), expected)

    def test_a_surviving_key_can_only_name_something_under_the_root(self):
        """The property the consumers actually depend on, stated as a join.

        `_scan_files` globs `project_dir / key.split('/')[0]`; the override
        lookups and `Exclusions._under` compare the key as a prefix. Both are
        joins, so the honest test is to perform one — in both path flavours,
        because the drive case cannot be reproduced on a POSIX host any other
        way and the CI matrix runs Windows.
        """
        flavours = (
            (posixpath, '/work/proj', '/'),
            (ntpath, 'C:\\work\\proj', '\\'),
        )
        survivors = _ESCAPING + tuple(_FOLDS) + _EMPTY + _DRIVE_SHAPED + tuple(_COLON_KEPT)
        for spelling in survivors:
            key = settings.normalise_dir_key(spelling)
            if not key:
                continue
            for module, root, sep in flavours:
                with self.subTest(spelling=spelling, flavour=module.__name__):
                    scan_root = module.normpath(module.join(root, key.split('/')[0]))
                    self.assertTrue(
                        scan_root == root or scan_root.startswith(root + sep),
                        '%r folded to %r, which globs %r — outside %r'
                        % (spelling, key, scan_root, root))


class DeclaredDirectoriesTest(unittest.TestCase):
    """What a refused key does to the rest of the file.

    Constructed directly rather than through `load()`, so nothing here can be
    answered by machine-level state outside the checkout.
    """

    def parse(self, directories):
        conf = settings.Settings({'directories': directories},
                                 '/proj/knowledge-base/settings.json', present=True)
        return conf.directories, conf.warnings

    def test_an_escaping_entry_is_skipped_and_the_rest_of_the_file_survives(self):
        """A skip, not a raise, and not a silent drop.

        A project that already committed `../shared` keeps building — that entry
        never widened scope correctly anyway, so refusing it loses nothing that
        worked — and the entries beside it still take effect. Raising would turn
        a settings typo into a project that cannot be graphed at all, which is
        the failure this module's opening paragraph rules out.
        """
        verdicts, warnings = self.parse({'../shared': 'source', 'docs': 'source'})
        self.assertEqual(verdicts, {'docs': 'source'})
        self.assertEqual(len(warnings), 1)

    def test_the_refusal_names_the_file_and_the_key_that_was_dropped(self):
        """Audibility is the whole point: the measured build printed nothing."""
        _, warnings = self.parse({'../shared': 'source'})
        self.assertIn('/proj/knowledge-base/settings.json', warnings[0])
        self.assertIn('../shared', warnings[0])
        self.assertIn('inside this project', warnings[0])

    def test_a_sibling_tree_never_reaches_the_verdict_map(self):
        """The security assertion, at the layer that decides it.

        `_declared_directories` turns whatever survives here into a `user`-tier
        classification, which is the strongest override tier there is and the
        thing `_scan_files` derives its glob roots from. Nothing that escapes
        may get that far.
        """
        for spelling in _ESCAPING:
            with self.subTest(spelling=spelling):
                verdicts, warnings = self.parse({spelling: 'source'})
                self.assertEqual(verdicts, {})
                self.assertTrue(warnings)


class CommittedFileTest(unittest.TestCase):
    """The same refusal, reached the way the attack reaches it: a file on disk.

    `load()` consults the machine-level home as well, which is real state
    outside the checkout, so this takes control of it rather than inheriting
    whoever's laptop is running the suite — the root `conftest.py` sandboxes the
    session but only when pytest's rootdir is the repository, and `pytest .`
    from inside `skills/` routes around it.
    """

    def setUp(self):
        home = tempfile.mkdtemp(prefix='freya-test-home-')
        self.addCleanup(shutil.rmtree, home, ignore_errors=True)
        previous = os.environ.get(settings.GLOBAL_ENV_VAR)
        os.environ[settings.GLOBAL_ENV_VAR] = home
        self.addCleanup(self._restore, previous)

    @staticmethod
    def _restore(previous):
        if previous is None:
            os.environ.pop(settings.GLOBAL_ENV_VAR, None)
        else:
            os.environ[settings.GLOBAL_ENV_VAR] = previous

    def project(self, contents):
        root = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, root, ignore_errors=True)
        kb = Path(root) / 'knowledge-base'
        kb.mkdir(parents=True, exist_ok=True)
        (kb / 'settings.json').write_text(contents, encoding='utf-8')
        return root

    def test_a_committed_sibling_declaration_is_refused_out_loud(self):
        conf = settings.load(self.project(
            '{"directories": {"../shared": "source", "docs": "source"}}'))
        self.assertEqual(conf.directories, {'docs': 'source'})
        self.assertTrue(any('../shared' in w for w in conf.warnings))

    def test_a_well_formed_file_still_produces_no_warnings(self):
        """The other half of the mutation: refusing everything would pass above."""
        conf = settings.load(self.project(
            '{"directories": {"docs": "source", "packages/legacy/": "exclude"}}'))
        self.assertEqual(conf.directories,
                         {'docs': 'source', 'packages/legacy': 'exclude'})
        self.assertEqual(conf.warnings, [])


if __name__ == '__main__':
    unittest.main()
