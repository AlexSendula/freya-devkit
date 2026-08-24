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

import json
import ntpath
import os
import posixpath
import shutil
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import containment  # noqa: E402
import settings  # noqa: E402

#: Declared values that must never become a root, and what makes each one wrong.
#:
#: Judged in both path flavours on every host, so the answer does not depend on which leg of
#: the CI matrix is running. Two of these are the whole reason for that: on POSIX `C:\shared`
#: reads as a legal directory name, and on Windows under 3.13 `/opt/sdk` is not absolute
#: (`ntpath.isabs` changed), so a rule built on `os.path.isabs` lets one through on each leg.
_NOT_RELATIVE = (
    '/opt/sdk',
    '//server/share',
    '\\shared',
    'C:\\shared',
    'C:/shared',
    'C:shared',
    'D:\\secrets',
)

#: Refused by name rather than by shape. A committed file cannot carry a path that means a
#: different directory for each person who reads it, and this is the one such path that would
#: fail silently everywhere instead of loudly somewhere.
_TILDE = ('~', '~/secrets', '~alex/shared')

#: Aliases that would make `outside:<alias>/<rel>` ambiguous, unsplittable, or invisible in a
#: diff. The alias is the name a crossing is reported under, so it has to be a word.
_BAD_ALIASES = ('a/b', 'a:b', '', '   ', 'ui pkg', 'ui/', '../ui')

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

    def test_the_refusal_says_where_the_declaration_belongs(self):
        """A refusal that does not name the alternative moves the silence one step.

        The two keys both talk about directories, and the one a person reaches for first is
        the wrong one for a path outside the root — measurably so, since `../shared` in
        `directories` is what this file's whole first half exists to refuse.
        """
        conf = settings.load(self.project('{"directories": {"../shared": "source"}}'))
        self.assertIn('"outside"', conf.warnings[0])


class OutsideRootsTest(unittest.TestCase):
    """A directory outside the project root, reached only because the project said so.

    Inside the root, discovery is automatic and nothing here is involved. Crossing the root is
    never implicit: no symlink, no `..` and no absolute path gets there, and the only way is a
    declaration in this committed file (ADR-031).

    The fixture is a project that is a *subdirectory* of the temp dir, so `packages/` is a real
    sibling of the project root and nothing is written above the tree this cleans up.
    """

    def setUp(self):
        home = tempfile.mkdtemp(prefix='freya-test-home-')
        self.addCleanup(shutil.rmtree, home, ignore_errors=True)
        previous = os.environ.get(settings.GLOBAL_ENV_VAR)
        os.environ[settings.GLOBAL_ENV_VAR] = home
        self.addCleanup(self._restore, previous)
        self.root = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, str(self.root), ignore_errors=True)
        self.proj = self.root / 'proj'
        (self.proj / 'src').mkdir(parents=True)
        (self.proj / 'src' / 'a.ts').write_text('export const a = 1\n', encoding='utf-8')
        (self.proj / 'knowledge-base').mkdir()
        self.ui = self.root / 'packages' / 'ui'
        (self.ui / 'src').mkdir(parents=True)
        (self.ui / 'src' / 'Button.tsx').write_text('export const B = 1\n', encoding='utf-8')

    @staticmethod
    def _restore(previous):
        if previous is None:
            os.environ.pop(settings.GLOBAL_ENV_VAR, None)
        else:
            os.environ[settings.GLOBAL_ENV_VAR] = previous

    def declare(self, outside):
        (self.proj / 'knowledge-base' / 'settings.json').write_text(
            json.dumps({'outside': outside}), encoding='utf-8')
        return settings.load(str(self.proj))

    def test_a_relative_declaration_resolves_and_a_crossing_is_named_by_alias(self):
        """The happy path, and the two things the token must be.

        The **alias** and not the path, so the token is the same string in every clone and no
        absolute path reaches a committed artifact. And POSIX separators on every host, for the
        same reason `normalize_key` folds them: a token that reads differently on Windows is
        not an interchange token.

        Mutations, each of which turns exactly this red: return
        `os.path.relpath(candidate, project_root)` instead of the aliased token and the
        assertion sees `../packages/ui/src/Button.tsx`; drop the `.replace(os.sep, '/')` and it
        goes red on Windows CI.
        """
        conf = self.declare({'ui': '../packages/ui'})
        self.assertEqual(conf.warnings, [])
        self.assertEqual(conf.outside.key_for(self.ui / 'src' / 'Button.tsx'),
                         'outside:ui/src/Button.tsx')
        self.assertEqual(conf.outside.to_dict(),
                         {'declared': [{'alias': 'ui', 'path': '../packages/ui'}]})

    def test_a_path_outside_the_declared_root_is_still_not_reachable(self):
        """The anti-vacuity control: declaring one root does not open the parent.

        Without it, an implementation that returned a token for everything would pass every
        refusal in this class.
        """
        conf = self.declare({'ui': '../packages/ui'})
        for candidate in (self.root / 'packages' / 'other.ts',
                          self.root / 'elsewhere' / 'x.ts',
                          self.proj / 'src' / 'a.ts'):
            with self.subTest(candidate=str(candidate)):
                self.assertIsNone(conf.outside.key_for(candidate))

    def test_an_absolute_declaration_is_refused_for_being_absolute_on_every_host(self):
        """The reason, not merely the refusal — and that is the whole point of this row.

        Every value here would be turned away regardless, by the clause that requires a
        declaration to leave the root, so a test that asserted only `roots == ()` would be
        green against a rule that judges absoluteness with the host's own `os.path.isabs`.
        What breaks under that swap is the *sentence*: on POSIX `os.path.isabs('C:/shared')`
        is False, so four of the seven values below are reported as naming something inside
        the project, and on Windows from 3.13 `ntpath.isabs('/opt/sdk')` is False and that one
        gets the same wrong answer. One mislabelled spelling per leg of the CI matrix, which
        is what judging in both flavours exists to prevent.
        """
        for value in _NOT_RELATIVE:
            with self.subTest(value=value):
                conf = self.declare({'x': value})
                self.assertEqual(conf.outside.roots, ())
                self.assertEqual(len(conf.warnings), 1)
                self.assertIn(repr(value), conf.warnings[0])
                self.assertIn('is not a relative path', conf.warnings[0])
                self.assertEqual(conf.outside.to_dict()['refused'][0]['alias'], 'x')

    def test_a_tilde_declaration_is_refused_by_name(self):
        """Also a row about the reason, and also load-bearing only there.

        `~/shared` cannot be accepted by any version of this rule — it has no `../`, so the
        clause that requires a declaration to leave the root refuses it. Delete the `~` branch
        and what the person is told is that their home directory is inside their project, which
        is the one answer that sends them looking in the wrong place. This is the failure that
        is silent on every machine at once, so it is worth a sentence of its own.
        """
        for value in _TILDE:
            with self.subTest(value=value):
                conf = self.declare({'x': value})
                self.assertEqual(conf.outside.roots, ())
                self.assertIn('~', conf.warnings[0])
                self.assertIn('different directory for every user', conf.warnings[0])

    def test_a_root_inside_this_project_is_refused_and_sent_to_directories(self):
        """One file must never have two spellings.

        A root that resolves back inside the project would give `src/a.ts` a second identity as
        `outside:x/a.ts`, which breaks ADR-025's one-key-space rule from the direction the
        graph-key check cannot see.

        Four lexical spellings only. The symlink case is the next method rather than a tail on
        this one, because a tail that skips takes the whole method's report to `skipped` on
        every host that will not make a link — these four rows then read as unrun on half the
        CI matrix when they in fact passed.
        """
        for value in ('./src', 'src', '../proj/src', '.'):
            with self.subTest(value=value):
                conf = self.declare({'x': value})
                self.assertEqual(conf.outside.roots, ())
                self.assertTrue(conf.warnings)

    def test_a_root_that_symlinks_back_into_the_project_is_refused(self):
        """The same rule where only `realpath` can see it, with a real link on disk.

        Mutate `parse_outside`'s containment comparison to a lexical one and the root is
        accepted, and `key_for` starts answering `outside:x/a.ts` for a file that is already a
        node. Skipping is confined to this method for the reason `test_containment.py`'s
        `_link_or_skip` gives, and the host-independent half of the same decision is pinned by
        `test_the_containment_question_is_resolved_on_every_host` below.
        """
        link = self.root / 'link'
        try:
            os.symlink(str(self.proj / 'src'), str(link), target_is_directory=True)
        except (OSError, NotImplementedError, AttributeError) as exc:
            self.skipTest('this host will not create symlinks: %s' % exc)
        conf = self.declare({'x': '../link'})
        self.assertEqual(conf.outside.roots, ())
        self.assertIsNone(conf.outside.key_for(self.proj / 'src' / 'a.ts'))
        self.assertTrue(conf.warnings)

    def test_the_containment_question_is_resolved_on_every_host(self):
        """Both containment decisions in this file, pinned without asking the host for a link.

        The two rows that prove `containment.within` is the predicate — the symlinked root
        above, and a symlink under a declared root — both need `os.symlink`, and Windows only
        grants that to a privileged process or with Developer Mode on. So the most
        security-relevant choice in this module was asserted on one leg of the CI matrix and
        nowhere else: replacing `within` with a lexical prefix compare at both sites left
        `test_settings.py` green at 26 rows with symlinks unavailable. That is the same gap
        `test_graph_ops.py::test_the_gate_hands_its_candidate_over_as_spelled_on_every_host`
        was written to close for `_contain`, and this is its counterpart here.

        A divergence between how a path is spelled and what it resolves to cannot be built on a
        real filesystem without a link, so it is supplied instead: `os.path.realpath` is
        replaced by one that delegates for everything except two paths, which is exactly the
        question a resolving predicate asks and a lexical one never does.

        Two directions, because the two sites resolve different sides:

        * `key_for` resolves the **candidate**, so a path spelled under the declared root that
          leads out of it is refused. A lexical rule returns a token for it.
        * `parse_outside` resolves the **project**, so a root that lands in the project's real
          location is refused even when the project was named by a spelling that differs. A
          lexical rule accepts it, and one file gets two spellings.
        """
        real = os.path.realpath
        # Both spellings are built from paths that are *already* resolved, so that a lexical
        # implementation genuinely reaches its comparison instead of failing it on the
        # `/var` -> `/private/var` indirection macOS puts under every temp directory. Without
        # that, the mutation this row exists to catch would pass it for the wrong reason.
        outside_the_root = os.path.join(real(str(self.root)), 'elsewhere', 'x.ts')
        spelled_under_root = os.path.join(real(str(self.ui)), 'link', 'x.ts')
        project_spelling = str(self.root / 'proj-by-another-name')
        project_real = real(str(self.proj))

        def fake(path, *args, **kwargs):
            text = os.path.normpath(os.fspath(path))
            if text == spelled_under_root:
                return outside_the_root
            if text == project_spelling or text.startswith(project_spelling + os.sep):
                text = project_real + text[len(project_spelling):]
            return real(text, *args, **kwargs)

        conf = self.declare({'ui': '../packages/ui'})
        self.assertEqual(conf.outside.key_for(self.ui / 'src' / 'Button.tsx'),
                         'outside:ui/src/Button.tsx')
        with mock.patch('os.path.realpath', fake):
            # The candidate side. Spelled inside the declared root, resolves out of it.
            self.assertIsNone(conf.outside.key_for(spelled_under_root))
            # The project side. `../packages/ui` is a genuine sibling of the real project, so
            # the control below has to be part of this row: without it a rule that refused
            # everything would pass the assertion above it.
            roots, warnings = settings.parse_outside(
                {'ui': '../packages/ui'}, project_spelling, 'settings.json')
            self.assertEqual([alias for alias, _, _ in roots.roots], ['ui'])
            self.assertEqual(warnings, [])
            roots, warnings = settings.parse_outside(
                {'x': '../proj-by-another-name/src'}, project_spelling, 'settings.json')
            self.assertEqual(roots.roots, ())
            self.assertIn('resolves inside this project', warnings[0])

    def test_two_roots_that_nest_name_a_file_the_same_way_in_either_order(self):
        """A crossing token is a function of the declarations, never of their key order.

        Declaring both a package and the directory holding it is an ordinary thing to write,
        and `key_for` returns on the first root that contains the candidate — so before
        `OutsideRoots` sorted them, the same tree with the same files produced
        `outside:ui/src/Button.tsx` under one key order and `outside:pkgs/ui/src/Button.tsx`
        under the other.

        That is not a hypothesis about hand-edited files: `write()` re-serialises this map with
        `sort_keys=True` and `seed_project_backend` calls it on the first build of any project
        carrying a machine default, so freya alphabetised the aliases itself and changed every
        token in the next graph with no code change at all. Mutation: `self.roots =
        tuple(roots)` in `OutsideRoots.__init__` and the second order returns the outer alias.

        The most specific root wins, which is also what makes `crossings: 0` on the outer root
        mean "the inner one covers it" rather than a wrong answer.
        """
        for order in (('ui', 'pkgs'), ('pkgs', 'ui')):
            with self.subTest(order=order):
                paths = {'ui': '../packages/ui', 'pkgs': '../packages'}
                conf = self.declare({alias: paths[alias] for alias in order})
                self.assertEqual(conf.warnings, [])
                self.assertEqual(conf.outside.key_for(self.ui / 'src' / 'Button.tsx'),
                                 'outside:ui/src/Button.tsx')
                self.assertEqual([alias for alias, _, _ in conf.outside.roots],
                                 ['ui', 'pkgs'])

    def test_two_spellings_of_one_alias_cannot_both_be_in_force(self):
        """An alias is the name a crossing is reported under, so two roots cannot share one.

        JSON cannot spell a literal duplicate key, so this only fires on two spellings that
        `strip()` folds together — which is exactly the typo `_ALIAS_CHARS` refuses whitespace
        to keep out of a diff. Left unchecked it was not cosmetic: both entries reached
        `declared`, and `_outside_report` counts crossings by alias and stamps the count on
        every row carrying it, so the artifact reported two crossings against a total of one.

        Mutation: drop the `taken` guard and `roots` comes back with `ui` twice and no warning.
        """
        conf = self.declare({'ui': '../packages/ui', ' ui ': '../packages'})
        self.assertEqual([alias for alias, _, _ in conf.outside.roots], ['ui'])
        self.assertEqual(conf.outside.to_dict()['declared'],
                         [{'alias': 'ui', 'path': '../packages/ui'}])
        self.assertEqual(conf.outside.to_dict()['refused'][0]['alias'], 'ui')
        self.assertIn('repeats an alias', conf.warnings[0])

    def test_a_root_reached_through_a_symlink_is_honoured_and_said_out_loud(self):
        """Honoured, because the path was declared — and named, because it is not legible.

        A symlink *under* a declared root is refused (that is SEC-008, and the rows above pin
        it). A declared root that is *itself* a symlink is a different question: nothing was
        crossed implicitly, so refusing it would turn away an ordinary `../packages -> ...`
        layout. But this record's argument for refusing absolute paths is that a relative one
        is legible in review, and `../packages` is only a sentence anyone can check while every
        component of it is what it looks like.

        So the run says where the declaration actually landed. Mutation: drop the warning and
        neither the committed file nor `graph.json` ever names the real destination — `to_dict`
        deliberately carries only the declared spelling.

        Measured against the project's *realpath*, so this fires on divergence the declaration
        contributed and not on every macOS checkout under `/tmp`.
        """
        hidden = self.root / 'elsewhere' / 'hidden'
        hidden.mkdir(parents=True)
        try:
            os.symlink(str(hidden), str(self.root / 'linked'), target_is_directory=True)
        except (OSError, NotImplementedError, AttributeError) as exc:
            self.skipTest('this host will not create symlinks: %s' % exc)
        conf = self.declare({'ui': '../linked'})
        self.assertEqual([alias for alias, _, _ in conf.outside.roots], ['ui'])
        self.assertEqual(len(conf.warnings), 1)
        self.assertIn('through a symlink', conf.warnings[0])
        self.assertIn('../elsewhere/hidden', conf.warnings[0])

    def test_the_direct_caller_guards_answer_with_their_own_sentence(self):
        """`parse_outside`'s first two branches, reached the only way anything reaches them.

        They are unreachable through `load()` — `DEFAULTS` carries `'outside': {}`, so a
        non-object section is caught by the generic type check with its own different sentence
        ("using defaults for it") and `Settings` is handed the default. The row above,
        `test_a_section_of_the_wrong_type_warns_like_every_other_one`, asserts on that generic
        sentence and would pass with these branches deleted — which is how a dead guard in a
        security-adjacent parser comes to read as covered.

        So they are pinned here, through a direct call, and the assertion is on the sentence
        this function produces rather than on the substring the two share. Mutation: delete the
        `isinstance` branch and this raises `AttributeError` instead of answering.
        """
        roots, warnings = settings.parse_outside(['../packages/ui'], str(self.proj), 'file.json')
        self.assertEqual(roots.roots, ())
        self.assertEqual(warnings, ['file.json: "outside" must be an object; ignoring it'])
        # And `None` is an absent section rather than a malformed one, so it says nothing.
        roots, warnings = settings.parse_outside(None, str(self.proj), 'file.json')
        self.assertEqual((roots.roots, warnings), ((), []))

    def test_a_root_that_contains_this_project_is_refused(self):
        """An ancestor is not a scope. Declaring one re-admits the whole tree the checkout
        sits in, which is not "linking a sibling package" — it is pointing freya somewhere
        else, and the warning says so."""
        for value in ('..', '../..', '../../..'):
            with self.subTest(value=value):
                conf = self.declare({'x': value})
                self.assertEqual(conf.outside.roots, ())
                self.assertIn('contains this project', conf.warnings[0])

    def test_a_declaration_that_names_nothing_is_reported_not_silently_inert(self):
        """A stale or typo'd root is the failure this file has already paid for twice.

        It is refused *and* carried into `to_dict`, because the warning goes to stderr and
        stderr is dead skill-to-skill (ADR-029). Mutation: drop the `refused` list from
        `to_dict` and the second assertion fails while the first still passes.
        """
        conf = self.declare({'gone': '../packages/nope'})
        self.assertEqual(conf.outside.roots, ())
        self.assertEqual(conf.outside.to_dict()['refused'][0]['alias'], 'gone')
        self.assertIn('does not name a directory that exists', conf.warnings[0])

    def test_an_alias_that_would_not_split_is_refused(self):
        """`outside:<alias>/<rel>` splits on the first `/`, so an alias may not contain one.

        The rest of the set is about the alias being a *name*: it appears in an answer, and one
        that differs from another by a space is a typo nobody sees in a diff.
        """
        for alias in _BAD_ALIASES:
            with self.subTest(alias=alias):
                conf = self.declare({alias: '../packages/ui'})
                self.assertEqual(conf.outside.roots, ())
                self.assertTrue(conf.warnings)

    def test_declaring_nothing_says_nothing(self):
        """The zero-config path, which is the thing that must not be traded away.

        No section, an empty section, and no settings file at all are all the same answer, and
        none of them produces a block for an artifact to carry.
        """
        for label, contents in (('absent', '{}'),
                                ('empty', '{"outside": {}}'),
                                ('directories only', '{"directories": {"docs": "source"}}')):
            with self.subTest(case=label):
                (self.proj / 'knowledge-base' / 'settings.json').write_text(
                    contents, encoding='utf-8')
                conf = settings.load(str(self.proj))
                self.assertEqual(conf.outside.roots, ())
                self.assertIsNone(conf.outside.to_dict())
                self.assertFalse(conf.outside)

    def test_a_section_of_the_wrong_type_warns_like_every_other_one(self):
        """The existing malformed-input pattern, not a second one invented for this key."""
        (self.proj / 'knowledge-base' / 'settings.json').write_text(
            '{"outside": ["../packages/ui"]}', encoding='utf-8')
        conf = settings.load(str(self.proj))
        self.assertEqual(conf.outside.roots, ())
        self.assertTrue(any('must be an object' in w for w in conf.warnings))

    def test_a_refused_declaration_does_not_take_the_others_down_with_it(self):
        """A skip and not a raise, the same as every other malformation in this file.

        A project whose committed file carries one stale root keeps building. Refusing that
        entry loses nothing that worked, because a declaration that cannot resolve never
        reached anything; raising would take the graph away as well.
        """
        conf = self.declare({'ui': '../packages/ui', 'gone': '/opt/sdk'})
        self.assertEqual([alias for alias, _, _ in conf.outside.roots], ['ui'])
        self.assertEqual(len(conf.warnings), 1)

    def test_a_value_the_filesystem_cannot_address_is_refused_and_not_raised(self):
        """The row above with a value that did not merely fail to resolve — it raised.

        `os.path.realpath` was the one line in this parser that answered a malformed value
        with an exception. A NUL is spellable in JSON (`"\\u0000"`) and is not spellable in a
        path, so `lstat` raised `ValueError` straight out of `parse_outside`; a lone surrogate
        raises `UnicodeEncodeError`, which is one too. `Settings.__init__` parses this section
        unconditionally, so both took down `--build`, `--update` and every read-only query on
        a project whose committed file carried one — a build failing because configuration is
        wrong, which is the thing this function's docstring promises never happens.

        The good root beside it is the anti-vacuity half: a guard that skipped the whole
        section rather than the entry would pass an assertion about the bad one alone.
        Mutation: remove the `try`/`except ValueError` and both subTests error out here rather
        than failing, which is the crash itself.
        """
        for label, bad in (('NUL', '../sh\x00ared'), ('lone surrogate', '../sh\ud800ared')):
            with self.subTest(case=label):
                conf = self.declare({'ui': '../packages/ui', 'bad': bad})
                self.assertEqual([alias for alias, _, _ in conf.outside.roots], ['ui'])
                self.assertEqual(len(conf.warnings), 1)
                self.assertIn('is not a path this system can address', conf.warnings[0])
                self.assertEqual(conf.outside.to_dict()['refused'][0]['alias'], 'bad')


class AnUntaughtConsumerRefusesACrossingTest(unittest.TestCase):
    """Fail-closed, as a property of the token rather than a rule anyone has to remember.

    Adoption is per consumer and the default is refusal: in this branch only code-graph's
    containment sites honour a declaration. Every other consumer — `verify_links`,
    `detect_project`, the security scan's spec resolver, `behavior_graph` — is untaught, and
    what they all do with a target is join it onto the project root and look. So the token has
    to be a string that join cannot turn into a file outside the project.

    The mutation this class exists for is the obvious alternative design: emit the real
    `../packages/ui/src/Button.tsx`. Every assertion below goes red on it, and every consumer
    in the tree would happily have opened it.
    """

    def setUp(self):
        home = tempfile.mkdtemp(prefix='freya-test-home-')
        self.addCleanup(shutil.rmtree, home, ignore_errors=True)
        previous = os.environ.get(settings.GLOBAL_ENV_VAR)
        os.environ[settings.GLOBAL_ENV_VAR] = home
        # Restored, not left set. The session sandbox in the root `conftest.py` is only
        # collected when pytest's rootdir is the repository, so a test that walks off with the
        # variable hands the next one a home this one is about to delete.
        self.addCleanup(OutsideRootsTest._restore, previous)
        self.root = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, str(self.root), ignore_errors=True)
        proj = self.root / 'proj'
        (proj / 'knowledge-base').mkdir(parents=True)
        ui = self.root / 'packages' / 'ui' / 'src'
        ui.mkdir(parents=True)
        (ui / 'Button.tsx').write_text('export const B = 1\n', encoding='utf-8')
        (proj / 'knowledge-base' / 'settings.json').write_text(
            '{"outside": {"ui": "../packages/ui"}}', encoding='utf-8')
        self.proj = proj
        self.token = settings.load(str(proj)).outside.key_for(ui / 'Button.tsx')

    def test_the_token_carries_nothing_a_join_could_escape_with(self):
        """No `..`, no drive, no root — in either path flavour, on every host."""
        self.assertEqual(self.token, 'outside:ui/src/Button.tsx')
        self.assertFalse(containment.escapes(self.token))
        self.assertFalse(containment.is_anchored(self.token))
        for flavour, base in ((posixpath, '/work/proj'), (ntpath, 'C:\\work\\proj')):
            with self.subTest(flavour=flavour.__name__):
                self.assertFalse(flavour.isabs(self.token))
                root = flavour.normpath(base)
                joined = flavour.normpath(flavour.join(root, self.token))
                self.assertTrue(joined.startswith(root + flavour.sep), joined)

    def test_joining_the_token_onto_any_root_names_nothing_that_exists(self):
        """The refusal itself. An untaught consumer resolves it to nothing and says so —
        `locator-unresolved`, `File not found in graph`, an empty language map. It refuses; it
        does not read."""
        for label, base in (('the project', self.proj),
                            ('the declared root', self.root / 'packages' / 'ui'),
                            ('the parent', self.root)):
            with self.subTest(base=label):
                self.assertFalse((Path(base) / self.token).exists())
                self.assertFalse(
                    os.path.exists(os.path.realpath(os.path.join(str(base), self.token))))


if __name__ == '__main__':
    unittest.main()
