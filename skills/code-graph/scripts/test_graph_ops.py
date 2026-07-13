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

Run: python test_graph_ops.py
"""

import os
import shutil
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from graph_ops import CodeGraph  # noqa: E402


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


if __name__ == "__main__":
    unittest.main(verbosity=2)
