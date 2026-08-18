#!/usr/bin/env python3
"""
Tests for the code-graph substrate fixes (dogfooding findings F6-F9 + vision §6).

Covers:
  - tsconfig/jsconfig `paths` alias resolution        (F7)
  - cwd-independent relative resolution               (F9)
  - explicit `unresolved:` signal (no silent drop)    (§6)
  - genuine external packages still tagged `external:` (regression guard)
  - non-interactive build (no stdin) for ambiguous dirs (F6)
  - self-ignoring generated graph cache               (F8)
  - POSIX graph keys on every host (first Windows CI run)

Run: python test_graph_ops.py
"""

import json
import os
import shutil
import sys
import tempfile
import unittest
from pathlib import Path, PurePosixPath, PureWindowsPath

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from graph_ops import CodeGraph, normalize_import, normalize_key  # noqa: E402


class Base(unittest.TestCase):
    def mk(self, files: dict) -> str:
        d = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, d, ignore_errors=True)
        for rel, content in files.items():
            p = Path(d) / rel
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_text(content, encoding="utf-8")
        return d


class TestAliasResolution(Base):
    def test_tsconfig_alias_resolves_internal(self):
        """`@/src/b` resolves to an internal file, not external:, given tsconfig paths."""
        proj = self.mk({
            "tsconfig.json": '{"compilerOptions":{"baseUrl":".","paths":{"@/*":["./*"]}}}',
            "src/b.ts": "export const b = 1\n",
            "src/c.ts": "import { b } from '@/src/b'\nexport const c = 2\n",
        })
        g = CodeGraph(proj)
        g.build()
        self.assertIn("src/b.ts", g.query("src/c.ts")["imports"])
        self.assertIn("src/b.ts", g.get_dependencies("src/c.ts"))

    def test_alias_resolves_with_glob_include(self):
        """A real-world tsconfig (alias + `**/*.ts` include) must not break parsing.

        Regression: `/*` in the `@/*` alias and `*/` in `**/*.ts` must not be treated
        as a block comment by the JSONC stripper.
        """
        proj = self.mk({
            "tsconfig.json": (
                '{\n'
                '  "compilerOptions": {\n'
                '    "baseUrl": ".",\n'
                '    "paths": { "@/*": ["./*"] }\n'
                '  },\n'
                '  "include": ["**/*.ts", "**/*.tsx"],\n'
                '  "exclude": ["node_modules"]\n'
                '}\n'
            ),
            "lib/webauthn.ts": "export const verify = 1\n",
            "app/route.ts": "import { verify } from '@/lib/webauthn'\nexport const r = 1\n",
        })
        g = CodeGraph(proj)
        g.build(non_interactive=True)
        self.assertIn("lib/webauthn.ts", g.query("app/route.ts")["imports"])
        self.assertIn("lib/webauthn.ts", g.get_dependencies("app/route.ts"))

    def test_jsconfig_jsonc_alias_resolves_internal(self):
        """jsconfig with comments + trailing comma (JSONC) still yields alias resolution."""
        proj = self.mk({
            "jsconfig.json": (
                "{\n"
                "  // path aliases\n"
                '  "compilerOptions": {\n'
                '    "baseUrl": ".",\n'
                '    "paths": { "@/*": ["./*"] },\n'  # trailing comma below
                "  },\n"
                "}\n"
            ),
            "src/b.js": "export const b = 1\n",
            "src/g.js": "import { b } from '@/src/b'\n",
        })
        g = CodeGraph(proj)
        g.build()
        self.assertIn("src/b.js", g.get_dependencies("src/g.js"))


class TestCwdIndependence(Base):
    def test_relative_import_resolves_from_foreign_cwd(self):
        """Relative imports must resolve when build runs with cwd != project dir (F9)."""
        proj = self.mk({
            "src/a.ts": "import { b } from './b'\nexport const a = 1\n",
            "src/b.ts": "export const b = 1\n",
        })
        other = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, other, ignore_errors=True)
        cwd = os.getcwd()
        try:
            os.chdir(other)
            CodeGraph(proj).build()
        finally:
            os.chdir(cwd)
        self.assertIn("src/b.ts", CodeGraph(proj).get_dependencies("src/a.ts"))


class TestUnresolvedSignal(Base):
    def test_unresolved_relative_is_marked_not_dropped(self):
        """A relative import to a missing file is recorded as unresolved:, not dropped (§6)."""
        proj = self.mk({"src/d.ts": "import x from './missing'\nexport const d = 1\n"})
        g = CodeGraph(proj)
        g.build()
        self.assertIn("unresolved:./missing", g.query("src/d.ts")["imports"])

    def test_external_package_still_external(self):
        """Genuine bare packages stay external: (regression guard for Fix 4)."""
        proj = self.mk({"src/e.ts": "import React from 'react'\nexport const e = 1\n"})
        g = CodeGraph(proj)
        g.build()
        self.assertIn("external:react", g.query("src/e.ts")["imports"])


class TestNonInteractiveBuild(Base):
    def test_ambiguous_dir_included_without_stdin(self):
        """Non-interactive build must not block on stdin and should not drop real source (F6)."""
        proj = self.mk({"weirddir/x.ts": "export const x = 1\n"})
        CodeGraph(proj).build(non_interactive=True)
        self.assertIn("weirddir/x.ts", CodeGraph(proj).load()["files"])


class TestGraphCacheIgnored(Base):
    def test_graph_dir_self_ignored(self):
        """The generated cache writes its own .gitignore so it is never committed (F8)."""
        proj = self.mk({"src/b.ts": "export const b = 1\n"})
        CodeGraph(proj).build()
        gi = Path(proj) / "knowledge-base" / ".graph" / ".gitignore"
        self.assertTrue(gi.exists(), ".graph/.gitignore not written")
        self.assertIn("*", gi.read_text(encoding="utf-8"))


class TestPathKeySeparators(Base):
    """Graph keys are POSIX whatever host built them (first Windows CI run).

    Windows CI keyed a file as `weirddir\\x.ts`, so every forward-slash lookup
    missed: four cases here got `None` from `query()` and two more got an empty
    dependency set. The separator cannot be the host's choice — behavior-graph
    intersects these keys with behavior records' `exercises[].path` and
    behavior-runner reads `graph.json` keys directly, both forward-slash.
    """

    def test_a_native_windows_relative_path_becomes_a_posix_key(self):
        """The write path, exercised from any host.

        `Path.relative_to()` returns a *native* path, so on Windows the key was
        `str(WindowsPath('weirddir/x.ts'))` == `weirddir\\x.ts`. PureWindowsPath
        stands in for that here, which is what makes the Windows-only regression
        reproducible (and this test meaningful) on Linux and macOS.
        """
        self.assertEqual(normalize_key(PureWindowsPath("weirddir") / "x.ts"), "weirddir/x.ts")
        self.assertEqual(normalize_key(PureWindowsPath("src/lib") / "auth.ts"), "src/lib/auth.ts")

    def test_posix_input_is_unchanged_and_leading_dot_slash_is_dropped(self):
        """The fold must not disturb the POSIX hosts that are already green."""
        self.assertEqual(normalize_key("src/b.ts"), "src/b.ts")
        self.assertEqual(normalize_key(PurePosixPath("src/b.ts")), "src/b.ts")
        self.assertEqual(normalize_key("./src/b.ts"), "src/b.ts")  # replaces the old prefix strip
        self.assertEqual(normalize_key("src//b.ts"), "src/b.ts")

    def test_import_signals_keep_the_specifier_verbatim(self):
        """`external:`/`unresolved:` tails are what the source wrote, not our paths."""
        self.assertEqual(normalize_import("unresolved:./missing"), "unresolved:./missing")
        self.assertEqual(normalize_import("external:react"), "external:react")
        self.assertEqual(normalize_import("src\\b.ts"), "src/b.ts")

    def test_build_writes_no_native_separator_into_a_key(self):
        proj = self.mk({
            "src/lib/auth.ts": "export const auth = 1\n",
            "src/c.ts": "import { auth } from './lib/auth'\nexport const c = 2\n",
        })
        CodeGraph(proj).build(non_interactive=True)
        files = CodeGraph(proj).load()["files"]
        self.assertIn("src/lib/auth.ts", files)
        self.assertEqual([k for k in files if "\\" in k], [])
        self.assertIn("src/lib/auth.ts", files["src/c.ts"]["imports"])

    def test_lookups_accept_a_native_windows_argument(self):
        """A Windows user pastes what their shell/git produced; the key stays POSIX."""
        proj = self.mk({
            "src/a.ts": "import { b } from './b'\nexport const a = 1\n",
            "src/b.ts": "export const b = 1\n",
        })
        g = CodeGraph(proj)
        g.build(non_interactive=True)
        self.assertEqual(g.query("src\\a.ts")["file"], "src/a.ts")
        self.assertIn("src/b.ts", g.get_dependencies("src\\a.ts"))
        self.assertIn("src/a.ts", g.get_dependents("src\\b.ts"))

    def test_impact_cancels_its_inputs_however_they_were_spelled(self):
        proj = self.mk({
            "src/a.ts": "import { b } from './b'\nexport const a = 1\n",
            "src/b.ts": "export const b = 1\n",
        })
        g = CodeGraph(proj)
        g.build(non_interactive=True)
        impact = g.get_impact(["./src/b.ts"])
        self.assertEqual(impact["input_files"], {"src/b.ts"})
        self.assertIn("src/a.ts", impact["direct_dependents"])
        # The input must not come back as a dependent of itself.
        self.assertNotIn("src/b.ts", impact["transitive_dependents"])

    def test_a_cache_written_with_backslash_keys_is_migrated_on_read(self):
        """Fixing only the write path would leave old Windows caches unreadable.

        A graph.json from an earlier release on Windows keys files (and their
        `imports`/`dependents`) natively. Migrating on read means a fixed build
        answers correctly before anyone re-runs `--build`.
        """
        stale = {
            "version": 1,
            "commit": None,
            "timestamp": "2026-01-01T00:00:00+00:00",
            "project_root": "C:\\proj",
            "files": {
                "src\\a.ts": {
                    "exports": ["a"],
                    "imports": ["src\\b.ts", "external:react", "unresolved:./missing"],
                    "dependents": [],
                    "category": "unknown",
                    "language": "typescript",
                },
                "src\\b.ts": {
                    "exports": ["b"],
                    "imports": [],
                    "dependents": ["src\\a.ts"],
                    "category": "unknown",
                    "language": "typescript",
                },
            },
        }
        proj = self.mk({"knowledge-base/.graph/graph.json": json.dumps(stale)})
        g = CodeGraph(proj)

        self.assertEqual(sorted(g.load()["files"]), ["src/a.ts", "src/b.ts"])
        info = g.query("src/a.ts")
        self.assertIn("src/b.ts", info["imports"])
        self.assertIn("unresolved:./missing", info["imports"])  # signal survives migration
        self.assertIn("external:react", info["imports"])
        self.assertEqual(g.get_dependencies("src/a.ts"), {"src/b.ts"})
        self.assertEqual(g.get_dependents("src/b.ts"), {"src/a.ts"})

    def test_migration_leaves_a_posix_cache_untouched(self):
        clean = {
            "version": 1,
            "files": {
                "src/a.ts": {"exports": [], "imports": ["src/b.ts"], "dependents": []},
                "src/b.ts": {"exports": [], "imports": [], "dependents": ["src/a.ts"]},
            },
        }
        proj = self.mk({"knowledge-base/.graph/graph.json": json.dumps(clean)})
        self.assertEqual(CodeGraph(proj).load(), clean)


if __name__ == "__main__":
    unittest.main(verbosity=2)
