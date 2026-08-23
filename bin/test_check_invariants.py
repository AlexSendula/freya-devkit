#!/usr/bin/env python3
"""Unit tests for the two tree-wide invariants.

Both rules exist because the defect they name is invisible where it is
committed: an `import yaml` works on the machine that has yaml, and a bare
`subprocess.run(["git", ...])` works everywhere except a Windows box whose
working directory is a repository someone else wrote.

**`check_invariants.is_absolute` is deliberately not tested here.** It is one of
the two bootstrap copies ADR-030 permits, and the only thing worth asserting
about it is that it still agrees with the canonical
`skills/freya-code-graph/scripts/containment.py:is_anchored`. That is a parity
claim about two modules, so it lives with the other one:
`bin/test_freya_cli.py:ContainmentParityTest`. Running only this file after
editing `is_absolute` will report green — run that class too.
"""

import ast
import contextlib
import io
import os
import shutil
import tempfile
import unittest
from pathlib import Path

import check_invariants as ci


def build_root(tmp, *, bin_modules=None, skill_modules=None, launcher=None):
    """Materialize a fixture tree and return its root.

    `bin_modules` and `skill_modules` are {filename: source}. The skill layout is
    `skills/demo/scripts/<name>` because that is the path the checker scans —
    the shipped layout, and the only place a skill script can live. (`scripts/`
    is a directory name other tools in this repo prune; nothing in this checker
    has an exclusion list, so the name carries no meaning here beyond "where
    skill scripts are".)

    `launcher` writes an extensionless `bin/<name>` — the shape `bin/freya` has.
    """
    root = Path(tmp)
    (root / "bin").mkdir(parents=True)
    for name, source in (bin_modules or {}).items():
        (root / "bin" / name).write_text(source, encoding="utf-8")
    if skill_modules:
        scripts = root / "skills" / "demo" / "scripts"
        scripts.mkdir(parents=True)
        for name, source in skill_modules.items():
            (scripts / name).write_text(source, encoding="utf-8")
    for name, source in (launcher or {}).items():
        (root / "bin" / name).write_text(source, encoding="utf-8")
    return root


def rules_hit(root, **kwargs):
    """Rule ids reported for a fixture tree.

    `allow={}` unless the test says otherwise. The shipped allowlist names real
    repository paths; against a fixture tree every one of those entries is a
    stale entry, so the default would add eight unrelated violations to every
    assertion in this file.
    """
    kwargs.setdefault("allow", {})
    return [item[2] for item in ci.scan(Path(root), **kwargs)]


def excerpts(root, **kwargs):
    """The excerpt column for a fixture tree, in report order."""
    kwargs.setdefault("allow", {})
    return [item[3] for item in ci.scan(Path(root), **kwargs)]


def run_main(argv):
    """Call main() with its output captured, so the suite stays quiet.

    Returns (exit_code, stdout, stderr).
    """
    out, err = io.StringIO(), io.StringIO()
    with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
        code = ci.main(argv)
    return code, out.getvalue(), err.getvalue()


def site_packages_modules():
    """Top-level module names installed beside this interpreter's standard library."""
    directory = os.path.join(os.path.dirname(os.__file__), "site-packages")
    names = set()
    for entry in ci._listdir(directory):
        if entry.endswith(".py"):
            names.add(entry[:-3])
        elif os.path.isfile(os.path.join(directory, entry, "__init__.py")):
            names.add(entry)
    return {name for name in names if name.isidentifier()}


class StdlibNamesTest(unittest.TestCase):
    """`sys.stdlib_module_names` is 3.10+; the declared floor is 3.9 and CI runs it."""

    def test_the_standard_library_is_reported_for_the_running_interpreter(self):
        names = ci.stdlib_names()
        for name in ("json", "subprocess", "pathlib", "unittest", "__future__"):
            self.assertIn(name, names)

    def test_the_fallback_finds_the_standard_library_without_the_39_missing_attribute(self):
        """Called directly, not through `stdlib_names()`: on any interpreter new
        enough to run pytest today the attribute exists, so the 3.9 path would
        otherwise never be executed by this suite at all — the shape of a green
        test covering nothing."""
        names = ci._stdlib_names_by_listing()
        for name in ("json", "subprocess", "pathlib", "unittest", "concurrent", "sys"):
            self.assertIn(name, names)

    def test_the_fallback_admits_nothing_installed_into_site_packages(self):
        """The answer must come from the interpreter's layout, never from what
        has been installed into it. Resolving each name with
        `importlib.util.find_spec` would have been shorter and would have made
        `import yaml` legal on exactly the machine that has yaml — the failure
        INV-1 exists to make visible."""
        installed = site_packages_modules()
        if not installed:
            self.skipTest("nothing installed beside this interpreter's standard library")
        self.assertEqual(sorted(installed & ci._stdlib_names_by_listing()), [])

    def test_the_fallback_covers_the_other_platforms_standard_library(self):
        """`winreg` has no file in a POSIX interpreter's lib directory and
        `termios` has none in a Windows one, so a plain directory listing makes
        a legal stdlib import a violation on half the CI matrix."""
        names = ci._stdlib_names_by_listing()
        self.assertIn("winreg", names)
        self.assertIn("termios", names)


class ModuleDiscoveryTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.tmp, True)

    def test_an_extensionless_python_launcher_is_scanned(self):
        """`bin/freya` is a Python program with no `.py` on it — the launcher
        every install puts on a user's PATH. A scan of `bin/*.py` alone leaves a
        hole in the middle of the shipped set."""
        root = build_root(self.tmp, launcher={"freya": "#!/usr/bin/env python3\nimport yaml\n"})
        self.assertIn("INV1", rules_hit(root))

    def test_a_non_python_file_in_bin_is_not_scanned(self):
        """Both shapes that sit beside the launcher: `bin/commands.json`, which
        has a suffix, and an extensionless file that is not Python. The second
        is why the launcher is found by its shebang rather than by "no suffix" —
        with a suffix test alone this fixture is a `SyntaxError` inside the
        gate, reported as if the repository were broken."""
        root = build_root(self.tmp, launcher={
            "commands.json": '{"import": "yaml"}\n',
            "notes": "#!/bin/sh\nimport yaml is not python here\n",
        })
        self.assertEqual(rules_hit(root), [])

    def test_skill_scripts_are_scanned(self):
        root = build_root(self.tmp, skill_modules={"tool.py": "import yaml\n"})
        self.assertIn("INV1", rules_hit(root))


class ImportRuleTest(unittest.TestCase):
    """INV-1 — the standard library is the whole runtime."""

    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.tmp, True)

    def _root(self, source, name="tool.py"):
        return build_root(self.tmp, bin_modules={name: source})

    def test_a_standard_library_import_is_accepted(self):
        root = self._root("import json\nimport os\nfrom pathlib import Path\n")
        self.assertEqual(rules_hit(root), [])

    def test_a_third_party_import_is_flagged(self):
        root = self._root("import yaml\n")
        self.assertIn("INV1", rules_hit(root))

    def test_a_third_party_from_import_is_flagged(self):
        root = self._root("from yaml import safe_load\n")
        self.assertIn("INV1", rules_hit(root))

    def test_a_dotted_import_is_judged_on_its_top_level_package(self):
        """`os.path` is `os`, and `concurrent.futures` is `concurrent`: the
        top-level name is the distribution the import would have to come from."""
        root = self._root("import os.path\nfrom concurrent.futures import ThreadPoolExecutor\n")
        self.assertEqual(rules_hit(root), [])

    def test_a_dotted_third_party_import_is_still_flagged(self):
        root = self._root("import yaml.composer\n")
        self.assertIn("INV1", rules_hit(root))

    def test_a_sibling_module_is_accepted(self):
        root = build_root(self.tmp, bin_modules={
            "tool.py": "import helper\n",
            "helper.py": "VALUE = 1\n",
        })
        self.assertEqual(rules_hit(root), [])

    def test_a_module_from_another_directory_of_the_checkout_is_accepted(self):
        """`bin/backend_setup.py:73` puts `skills/freya-code-graph/scripts` on
        `sys.path` and imports `settings` out of it, on purpose and with a
        comment saying why. A strict same-directory rule reports that documented
        import as a missing dependency — a checker that has to be silenced on
        its first run."""
        root = build_root(
            self.tmp,
            bin_modules={"backend_setup.py": "def load():\n    import settings\n"},
            skill_modules={"settings.py": "VALUE = 1\n"},
        )
        self.assertEqual(rules_hit(root), [])

    def test_a_relative_import_is_not_judged(self):
        """`from . import x` names no top-level module, so the rule has nothing
        to compare against. `from .absent import x` is the form that matters:
        it *has* a module name, and reading it as a top-level one would report
        a relative import of a file in the same package as a missing
        dependency."""
        root = self._root("from . import helper\nfrom .absent import thing\n")
        self.assertEqual(rules_hit(root), [])

    def test_an_import_inside_a_function_is_flagged_too(self):
        """A dependency smuggled into a function body costs a user exactly what
        one at the top of the file does — and this tree really does import
        inside functions (`backend_setup.py`, `freya_cli.py`), so restricting
        the walk to `tree.body` would be a hole with traffic already on it."""
        root = self._root("def go():\n    import yaml\n    return yaml\n")
        self.assertIn("INV1", rules_hit(root))

    def test_an_import_inside_a_class_body_is_flagged_too(self):
        root = self._root("class Thing:\n    import yaml\n")
        self.assertIn("INV1", rules_hit(root))

    def test_a_third_party_import_guarded_by_except_importerror_is_still_flagged(self):
        """Decided exclusion, and the measurement it rested on has since moved
        without moving the decision. On 2026-08-21 the tree held exactly one
        guarded import; on 2026-08-23 it holds four, and all four still guard a
        module of *this checkout* rather than an optional dependency —
        `bin/freya_cli.py:195`, `bin/updater.py:77`,
        `skills/freya-codebase-security-scan/scripts/audit_adapter.py:55` and
        `skills/freya-behavior-runner/scripts/run_behaviors.py:271`.

        Which is the argument: the shape is not evidence of anything, so a
        carve-out keyed on it would exempt a future `try: import yaml` on the
        strength of a syntax four first-party bootstrap guards already use. A
        real optional dependency here is an ADR."""
        root = self._root("try:\n    import yaml\nexcept ImportError:\n    yaml = None\n")
        self.assertIn("INV1", rules_hit(root))

    def test_pytest_imported_by_a_test_module_is_flagged(self):
        """The suite is `unittest.TestCase` throughout and merely *runs* under
        pytest; CI installs exactly one package. A test file that imports it
        breaks `python3 -m unittest discover`, the documented no-install
        fallback."""
        root = self._root("import pytest\n", name="test_thing.py")
        self.assertIn("INV1", rules_hit(root))

    def test_the_excerpt_names_the_offending_import(self):
        root = self._root("from yaml import safe_load\n")
        self.assertEqual(excerpts(root), ["from yaml import safe_load"])


class BinaryRuleTest(unittest.TestCase):
    """INV-2 — a spawned program is named by a path, never by a bare name."""

    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.tmp, True)

    def _root(self, body, name="tool.py", preamble="import subprocess\n"):
        return build_root(self.tmp, bin_modules={name: preamble + body})

    def test_a_bare_binary_name_is_flagged(self):
        root = self._root('subprocess.run(["git", "status"])\n')
        self.assertIn("INV2", rules_hit(root))

    def test_the_excerpt_names_the_binary_and_the_shape(self):
        root = self._root('subprocess.run(["git", "status"])\n')
        self.assertEqual(excerpts(root), ["subprocess.run argv[0]='git' (bare name)"])

    def test_sys_executable_is_read_as_a_resolved_argv0(self):
        """Asserted on `is_resolved` rather than end to end, because end to end
        it proves nothing: an argv[0] the checker cannot read is skipped
        anyway, so a fixture spawning `[sys.executable, ...]` stays green with
        this branch deleted outright. That is the exact shape of the six
        green-and-vacuous tests this repository found in itself."""
        node = ast.parse("sys.executable").body[0].value
        self.assertIs(ci.is_resolved(node, {}), True)

    def test_an_attribute_that_is_not_sys_executable_is_not_read_as_resolved(self):
        """`self.binary` and `os.sep` are attributes too. Accepting the shape
        rather than the name would wave through every argv[0] held on an
        instance — including the resolver-shaped ones that never resolve."""
        for source in ("self.binary", "os.sep", "shutil.which"):
            with self.subTest(source=source):
                node = ast.parse(source).body[0].value
                self.assertIs(ci.is_resolved(node, {}), False)

    def test_an_absolute_posix_path_is_accepted(self):
        root = self._root('subprocess.run(["/usr/bin/git", "status"])\n')
        self.assertEqual(rules_hit(root), [])

    def test_an_absolute_windows_path_is_accepted(self):
        r"""`os.path.isabs` answers for the platform the *checker* runs on, and
        CI runs this on Linux and on Windows. `C:\tools\git.exe` reads as
        relative to posixpath, so one source file would be a violation on one
        leg of the matrix and clean on the other."""
        root = self._root('subprocess.run(["C:\\\\Git\\\\bin\\\\git.exe", "status"])\n')
        self.assertEqual(rules_hit(root), [])

    def test_a_module_level_constant_is_resolved_to_the_name_it_holds(self):
        """The SEC-002 shape: `BINARY = 'graphify'` forty lines above
        `subprocess.run([BINARY, ...], cwd=self.project_dir)`. A constant one
        screen up is not a resolver, and a checker that only reads literals at
        the call site says nothing about the one bare-name site in this
        repository that is already a filed HIGH finding."""
        root = self._root('BINARY = "graphify"\nsubprocess.run([BINARY, "update"])\n')
        self.assertEqual(excerpts(root), ["subprocess.run argv[0]='graphify' (bare name)"])

    def test_a_constant_holding_an_absolute_path_is_accepted(self):
        root = self._root('BINARY = "/usr/bin/git"\nsubprocess.run([BINARY, "status"])\n')
        self.assertEqual(rules_hit(root), [])

    def test_a_concatenated_argv_is_judged_on_its_head(self):
        """`["git"] + cmd` is the same spawn with the same argv[0]."""
        root = self._root('cmd = ["status"]\nsubprocess.run(["git"] + cmd)\n')
        self.assertIn("INV2", rules_hit(root))

    def test_a_starred_head_is_left_alone(self):
        """`[*prefix, "x"]` hides argv[0] behind a name; unreadable is not the
        same as safe, and the rule says nothing rather than guessing."""
        root = self._root('prefix = []\nsubprocess.run([*prefix, "status"])\n')
        self.assertEqual(rules_hit(root), [])

    def test_an_argv_built_by_a_helper_is_left_alone(self):
        """The known blind spot, stated so it is not mistaken for coverage:
        `subprocess.run(adapter.build_argv(contract), ...)` in `audit.py` is
        SEC-003's run site, and its bare `"claude"` is assembled inside
        `audit_adapter._claude_argv`. Nothing at this call site can see it."""
        root = self._root("def go(adapter, contract):\n"
                          "    subprocess.run(adapter.build_argv(contract))\n")
        self.assertEqual(rules_hit(root), [])

    def test_a_tuple_argv_is_checked_like_a_list(self):
        root = self._root('subprocess.run(("git", "status"))\n')
        self.assertIn("INV2", rules_hit(root))

    def test_a_string_command_is_flagged(self):
        """POSIX takes the whole string as the program; under `shell=True` the
        shell searches PATH for its first word. Either way a search picks it."""
        root = self._root('subprocess.run("git", shell=True)\n')
        self.assertIn("INV2", rules_hit(root))

    def test_a_relative_path_with_a_separator_is_flagged(self):
        root = self._root('subprocess.run(["./tools/git", "status"])\n')
        self.assertEqual(excerpts(root),
                         ["subprocess.run argv[0]='./tools/git' (relative path)"])

    def test_every_spawning_entry_point_is_checked(self):
        """`run` is the common one; `Popen`, `call`, `check_call` and
        `check_output` spawn exactly the same way."""
        for spawner in ("run", "Popen", "call", "check_call", "check_output"):
            with self.subTest(spawner=spawner):
                tmp = tempfile.mkdtemp()
                self.addCleanup(shutil.rmtree, tmp, True)
                root = build_root(tmp, bin_modules={
                    "tool.py": 'import subprocess\nsubprocess.%s(["git", "x"])\n' % spawner})
                self.assertIn("INV2", rules_hit(root))

    def test_an_aliased_subprocess_module_is_still_checked(self):
        """`import subprocess as sp` makes the spawn `sp.run`, which a checker
        matching the literal name `subprocess` never sees."""
        root = self._root('sp.run(["git", "status"])\n', preamble="import subprocess as sp\n")
        self.assertIn("INV2", rules_hit(root))

    def test_a_from_import_of_a_spawner_is_still_checked(self):
        root = self._root('run(["git", "status"])\n',
                          preamble="from subprocess import run\n")
        self.assertIn("INV2", rules_hit(root))

    def test_an_aliased_from_import_of_a_spawner_is_still_checked(self):
        root = self._root('spawn(["git", "status"])\n',
                          preamble="from subprocess import run as spawn\n")
        self.assertIn("INV2", rules_hit(root))

    def test_a_run_belonging_to_another_object_is_not_checked(self):
        """`runner.run([...])` is somebody else's method. The rule is about
        `subprocess`, and a name-only match would flag every `.run()` in the
        tree."""
        root = self._root("def go(runner):\n    runner.run(['git', 'status'])\n")
        self.assertEqual(rules_hit(root), [])

    def test_a_bare_run_without_the_subprocess_import_is_not_checked(self):
        root = build_root(self.tmp, bin_modules={
            "tool.py": "def run(argv):\n    pass\n\nrun(['git', 'status'])\n"})
        self.assertEqual(rules_hit(root), [])

    def test_a_test_module_is_not_checked_for_binaries(self):
        """Decided scope, and the reason is the threat rather than convenience:
        the defect is the toolkit spawning a program while its working directory
        is a repository it was merely pointed at. A test spawns `git` inside a
        `tempfile.mkdtemp()` tree it built two lines earlier."""
        root = self._root('subprocess.run(["git", "status"])\n', name="test_thing.py")
        self.assertEqual(rules_hit(root), [])

    def test_a_test_module_is_still_checked_for_imports(self):
        """The INV-2 exemption is not a general one: a test that imports a
        third-party package breaks the zero-install promise exactly as hard as
        a script that does."""
        root = self._root("import yaml\n", name="test_thing.py", preamble="")
        self.assertIn("INV1", rules_hit(root))

    def test_a_call_with_no_arguments_is_left_alone(self):
        root = self._root("subprocess.run()\n")
        self.assertEqual(rules_hit(root), [])


class AllowlistTest(unittest.TestCase):
    """The allowlist is a debt marker: exact in both directions, keyed by count."""

    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.tmp, True)

    def _root(self, body):
        return build_root(self.tmp, bin_modules={"tool.py": "import subprocess\n" + body})

    def test_an_allowlisted_site_is_not_reported(self):
        root = self._root('subprocess.run(["git", "status"])\n')
        self.assertEqual(rules_hit(root, allow={"bin/tool.py": {"git": 1}}), [])

    def test_a_site_beyond_the_files_budget_is_reported(self):
        """The whole point: green today, red the moment one more appears."""
        root = self._root('subprocess.run(["git", "status"])\nsubprocess.run(["git", "log"])\n')
        self.assertEqual(rules_hit(root, allow={"bin/tool.py": {"git": 1}}), ["INV2"])

    def test_the_budget_is_per_binary_name(self):
        """A budget for `git` must not silently absorb a new `graphify`."""
        root = self._root('subprocess.run(["git", "x"])\nsubprocess.run(["graphify", "y"])\n')
        hit = ci.scan(Path(root), allow={"bin/tool.py": {"git": 1}})
        self.assertEqual([item[3] for item in hit],
                         ["subprocess.run argv[0]='graphify' (bare name)"])

    def test_an_allowlist_entry_with_no_matching_site_is_reported(self):
        """Paying the debt down has to update the marker. Otherwise the list
        rots into a record of a defect that was fixed and a licence for one
        that has not been."""
        root = self._root("pass\n")
        found = ci.scan(Path(root), allow={"bin/tool.py": {"git": 1}})
        self.assertEqual(len(found), 1)
        self.assertIn("update KNOWN_BARE_BINARIES", found[0][3])

    def test_an_allowlist_entry_for_a_file_that_does_not_exist_is_reported(self):
        root = self._root("pass\n")
        found = ci.scan(Path(root), allow={"bin/deleted.py": {"git": 1}})
        self.assertEqual(len(found), 1)

    def test_the_allowlist_does_not_suppress_import_violations(self):
        """One rule's debt marker must never quiet the other rule."""
        root = build_root(self.tmp, bin_modules={
            "tool.py": 'import subprocess\nimport yaml\nsubprocess.run(["git", "x"])\n'})
        self.assertEqual(rules_hit(root, allow={"bin/tool.py": {"git": 1}}), ["INV1"])


class ShippedTreeTest(unittest.TestCase):
    """The guarantees the checker exists to make, asserted where pytest sees them.

    Every other test in this file builds a fixture tree. None of them looks at
    the tree that actually ships, which is how the stdlib-only rule survived as
    a hand-run census in a document for as long as it did.
    """

    ROOT = Path(__file__).resolve().parents[1]

    def test_the_shipped_tree_imports_only_the_standard_library_and_itself(self):
        violations = ci.scan(self.ROOT, rules={"INV1"})
        detail = "\n".join("%s:%d: %s" % (rel, line, excerpt)
                           for rel, line, _, excerpt in violations)
        self.assertEqual(violations, [], "non-stdlib imports:\n" + detail)

    def test_the_shipped_tree_has_no_unallowlisted_bare_binary_sites(self):
        violations = ci.scan(self.ROOT, rules={"INV2"})
        detail = "\n".join("%s:%d: %s" % (rel, line, excerpt)
                           for rel, line, _, excerpt in violations)
        self.assertEqual(violations, [], "unaccounted argv[0] sites:\n" + detail)

    def test_every_bare_binary_site_in_the_shipped_tree_names_git(self):
        """The census the allowlist records, re-measured after the G2 fix:
        2026-08-23, eight sites, all `git`, in seven files, none of them a filed
        finding. SEC-002's `graphify` and the two bare `git` sites that shared
        its files now go through `exec_path.resolve`, so `graphify` has left the
        census entirely.

        `assertEqual`, not `assertGreaterEqual`. The `>=` was written so the
        number would survive files moving, and it cannot survive a fix in the
        right direction — it would have called a census of eight green while the
        allowlist still claimed eleven. Both directions have to bite, which is
        the same property `apply_allowlist` gives per file.

        A ninth site, or one naming anything else — `claude`, `npm`, `node` — is
        a new class of exposure and should not slip in under a count."""
        sites = ci.scan(self.ROOT, rules={"INV2"}, allow={})
        names = sorted({item[3].split("argv[0]=")[1].split(" ")[0] for item in sites})
        detail = "\n".join("%s:%d: %s" % (rel, line, excerpt)
                           for rel, line, _, excerpt in sites)
        self.assertEqual(names, ["'git'"], detail)
        self.assertEqual(len(sites), 8, detail)
        self.assertEqual(len({rel for rel, _, _, _ in sites}), 7, detail)

    def test_the_shipped_tree_actually_has_modules_to_scan(self):
        """A guard against the whole suite above passing on an empty file list:
        `module_files` returning [] makes every assertion in this class true."""
        self.assertGreaterEqual(len(ci.module_files(self.ROOT)), 50)


class MainTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.tmp, True)

    def test_a_clean_tree_exits_zero(self):
        root = build_root(self.tmp, bin_modules={"tool.py": "import json\n"})
        code, out, _ = run_main(["--root", str(root), "--no-allowlist"])
        self.assertEqual(code, 0)
        self.assertIn("invariants hold", out)

    def test_a_violation_exits_one_and_names_the_file_and_rule(self):
        root = build_root(self.tmp, bin_modules={"tool.py": "import yaml\n"})
        code, out, err = run_main(["--root", str(root), "--no-allowlist"])
        self.assertEqual(code, 1)
        self.assertIn("bin/tool.py", out)
        self.assertIn("INV1", out)
        self.assertIn("1 violation(s).", err)

    def test_an_unparseable_module_exits_two(self):
        """Exit 2 is "the checker could not run", never "the tree is clean" —
        the same contract bin/check_skill_conformance.py uses for a missing
        manifest. A gate that reports success on input it failed to read is
        worse than no gate."""
        root = build_root(self.tmp, bin_modules={"broken.py": "def (:\n"})
        code, _, err = run_main(["--root", str(root), "--no-allowlist"])
        self.assertEqual(code, 2)
        self.assertIn("broken.py", err)

    def test_the_rule_filter_restricts_output(self):
        root = build_root(self.tmp, bin_modules={
            "tool.py": 'import subprocess\nimport yaml\nsubprocess.run(["git", "x"])\n'})
        self.assertEqual(rules_hit(root, rules={"INV1"}), ["INV1"])

    def test_the_default_run_uses_the_shipped_allowlist_and_passes(self):
        """No `--root`, no `--no-allowlist`: the command CI runs, on the tree it
        runs against."""
        code, out, _ = run_main([])
        self.assertEqual(code, 0, out)

    def test_no_allowlist_reports_the_debt_the_default_run_hides(self):
        """The census mode. The same tree the line above calls clean has eight
        real bare-name sites in it, and the allowlist is a marker for them, not
        an argument that they are fine.

        Exact, for the reason `ShippedTreeTest` gives: paying the debt down has
        to move this number, or the marker rots into a licence."""
        code, out, _ = run_main(["--no-allowlist", "--rule", "INV2"])
        self.assertEqual(code, 1)
        self.assertEqual(out.count("INV2"), 8, out)


if __name__ == "__main__":
    unittest.main()
