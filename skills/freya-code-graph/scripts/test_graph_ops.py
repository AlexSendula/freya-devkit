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
    def _lines(self, gi):
        return [ln.strip() for ln in gi.read_text(encoding="utf-8").splitlines()
                if ln.strip() and not ln.startswith("#")]

    def test_graph_dir_ignores_the_regenerable_files_by_name(self):
        """The cache writes its own .gitignore so it is never committed (F8) — but
        it names the regenerable files rather than using a blanket `*`.

        F8 predates behavior.json. A `*` written for a directory holding only a
        parse cache later swept up behavior.json, whose observed coverage comes
        from running the test suite and cannot be rebuilt from source.

        `graph.*.json` covers the per-backend artifacts (CD-17), which are as
        regenerable as graph.json and must not turn the cache back into a `*`.
        """
        proj = self.mk({"src/b.ts": "export const b = 1\n"})
        CodeGraph(proj).build()
        gi = Path(proj) / "knowledge-base" / ".graph" / ".gitignore"
        self.assertTrue(gi.exists(), ".graph/.gitignore not written")
        self.assertEqual(self._lines(gi),
                         ["graph.json", "graph.*.json", "classifications.json", "docs.json"])

    def test_upgrades_a_legacy_blanket_ignore(self):
        """An already-onboarded project carries `*`; the build must upgrade it."""
        proj = self.mk({"src/b.ts": "export const b = 1\n"})
        gdir = Path(proj) / "knowledge-base" / ".graph"
        gdir.mkdir(parents=True, exist_ok=True)
        (gdir / ".gitignore").write_text(
            "# Generated code-graph cache — do not commit\n*\n", encoding="utf-8")
        # non_interactive: the pre-existing .graph/ dir is an uncertain classification,
        # and build() would otherwise prompt on stdin (F6).
        CodeGraph(proj).build(non_interactive=True)
        self.assertEqual(self._lines(gdir / ".gitignore"),
                         ["graph.json", "graph.*.json", "classifications.json", "docs.json"])

    def test_leaves_a_customised_gitignore_alone(self):
        proj = self.mk({"src/b.ts": "export const b = 1\n"})
        gdir = Path(proj) / "knowledge-base" / ".graph"
        gdir.mkdir(parents=True, exist_ok=True)
        (gdir / ".gitignore").write_text("mine.json\n", encoding="utf-8")
        CodeGraph(proj).build(non_interactive=True)
        self.assertEqual((gdir / ".gitignore").read_text(encoding="utf-8"), "mine.json\n")


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


# =============================================================================
# Resolver repairs — Track B Phase 0 findings (backlog item 9).
#
# The spike measured this resolver against its own repo and got 10 of 50 Python
# files and 0 internal edges, reported as success. Each class below pins one of
# the causes. They are written against a real project tree rather than a unit
# seam deliberately: every one of these defects was invisible to the existing
# suite precisely because nothing ran the resolver end to end.
# =============================================================================


class TestSourceBearingDirsAreNotExcludedByName(Base):
    """`scripts/` holds build shell scripts in a web app and application code here.

    Excluding it by name, at any depth, is what hid 40 of this repo's 51 Python
    files. Generated and vendored trees must stay excluded.
    """

    def test_code_under_a_nested_scripts_dir_is_graphed(self):
        proj = self.mk({
            "skills/thing/scripts/mod_a.py": "import mod_b\n",
            "skills/thing/scripts/mod_b.py": "x = 1\n",
        })
        g = CodeGraph(proj)
        g.build(non_interactive=True)
        self.assertIn("skills/thing/scripts/mod_a.py", g.graph["files"])
        self.assertIn("skills/thing/scripts/mod_b.py", g.graph["files"])

    def test_code_under_a_top_level_scripts_dir_is_graphed(self):
        proj = self.mk({"scripts/tool.ts": "export const z = 1\n"})
        g = CodeGraph(proj)
        g.build(non_interactive=True)
        self.assertIn("scripts/tool.ts", g.graph["files"])

    def test_a_top_level_convention_dir_is_still_excluded(self):
        """At the root, `docs/` and `examples/` do mean what the convention says.

        Measured: indexing this repo's own `docs/` pulled in the published site's
        bundled JS and a spike's planted fixtures — noise in every blast radius.
        """
        proj = self.mk({
            "src/a.ts": "export const a = 1\n",
            "docs/site/bundle.js": "var b = 1\n",
            "examples/demo.ts": "export const d = 1\n",
        })
        g = CodeGraph(proj)
        g.build(non_interactive=True)
        self.assertEqual(set(g.graph["files"]), {"src/a.ts"})

    def test_the_same_name_below_the_root_is_kept(self):
        """Below the root the name promises nothing, so it is not evidence.

        `app/api/media/generated/route.ts` in the testbed is a git-tracked Next.js
        route that a depth-blind `generated` rule silently dropped.
        """
        proj = self.mk({
            "app/api/media/generated/route.ts": "export const DELETE = 1\n",
            "skills/thing/docs/build.py": "x = 1\n",
            "packages/ui/examples/card.tsx": "export const C = 1\n",
        })
        g = CodeGraph(proj)
        g.build(non_interactive=True)
        self.assertEqual(set(g.graph["files"]), {
            "app/api/media/generated/route.ts",
            "skills/thing/docs/build.py",
            "packages/ui/examples/card.tsx",
        })

    def test_our_own_generated_output_is_still_excluded(self):
        """`knowledge-base/` is freya's output. Graphing it would be self-reference."""
        proj = self.mk({
            "src/a.ts": "export const a = 1\n",
            "knowledge-base/generated.ts": "export const g = 1\n",
        })
        g = CodeGraph(proj)
        g.build(non_interactive=True)
        self.assertIn("src/a.ts", g.graph["files"])
        self.assertNotIn("knowledge-base/generated.ts", g.graph["files"])

    def test_build_and_dependency_trees_are_still_excluded(self):
        proj = self.mk({
            "src/a.ts": "export const a = 1\n",
            "dist/bundle.js": "var x = 1\n",
            "node_modules/pkg/index.js": "module.exports = {}\n",
            "build/out.js": "var y = 1\n",
        })
        g = CodeGraph(proj)
        g.build(non_interactive=True)
        self.assertEqual(set(g.graph["files"]), {"src/a.ts"})


class TestStaleRuleClassificationsAreRefreshed(Base):
    """A rule change has to reach projects that were already graphed.

    `classifications.json` caches a verdict per directory and the builder skips any
    directory already in it, so changing the rules only ever helped a fresh clone —
    every existing user kept the old answer, and `--clear` does not delete the file.
    Rule-derived verdicts are re-derivable and must follow the rules; a verdict the
    user or the model made is a judgement and must survive.
    """

    def _classifications(self, proj):
        p = Path(proj) / "knowledge-base" / ".graph" / "classifications.json"
        return json.loads(p.read_text(encoding="utf-8"))

    def _seed(self, proj, entries, version=None):
        gdir = Path(proj) / "knowledge-base" / ".graph"
        gdir.mkdir(parents=True, exist_ok=True)
        payload = {"version": 1, "directories": entries}
        if version is not None:
            payload["rules_version"] = version
        (gdir / "classifications.json").write_text(json.dumps(payload), encoding="utf-8")

    def test_a_stale_rule_verdict_is_rediscarded_and_the_dir_is_graphed(self):
        proj = self.mk({"scripts/tool.py": "x = 1\n"})
        self._seed(proj, {
            "scripts": {"type": "exclude", "confidence": 1.0, "source": "rule"},
        }, version="something-old")
        g = CodeGraph(proj)
        g.build(non_interactive=True)
        self.assertIn("scripts/tool.py", g.graph["files"])

    def test_a_user_verdict_survives_a_rules_change(self):
        proj = self.mk({"vendor_ish/tool.py": "x = 1\n"})
        self._seed(proj, {
            "vendor_ish": {"type": "exclude", "confidence": 1.0, "source": "user"},
        }, version="something-old")
        g = CodeGraph(proj)
        g.build(non_interactive=True)
        self.assertNotIn("vendor_ish/tool.py", g.graph["files"])
        self.assertEqual(
            self._classifications(proj)["directories"]["vendor_ish"]["source"], "user")

    def test_an_ai_verdict_survives_a_rules_change(self):
        proj = self.mk({"odd/tool.py": "x = 1\n"})
        self._seed(proj, {
            "odd": {"type": "exclude", "confidence": 0.8, "source": "ai"},
        }, version="something-old")
        g = CodeGraph(proj)
        g.build(non_interactive=True)
        self.assertNotIn("odd/tool.py", g.graph["files"])

    def test_the_current_rules_version_is_recorded_so_the_next_change_propagates(self):
        proj = self.mk({"src/a.py": "x = 1\n"})
        CodeGraph(proj).build(non_interactive=True)
        self.assertIn("rules_version", self._classifications(proj))


class TestDeadCategoryFieldIsGone(Base):
    """CD-12. `category` was written on every file and read by nothing.

    Three unrelated things in this repo are called "category"; the other two — security
    findings and spec contexts — are live and untouched. This one guessed a label from the
    file path, stored it in every entry, and no caller ever looked.
    """

    def test_no_file_entry_carries_a_category(self):
        proj = self.mk({
            "src/auth/login.ts": "export const l = 1\n",
            "src/api/route.ts": "export const r = 1\n",
        })
        g = CodeGraph(proj)
        g.build(non_interactive=True)
        for path, info in g.graph["files"].items():
            self.assertNotIn("category", info, path)

    def test_a_cache_written_with_category_still_loads(self):
        """Existing graphs carry it; reading one must not break."""
        legacy = {
            "version": 1,
            "files": {"src/a.ts": {"exports": [], "imports": [], "dependents": [],
                                   "category": "auth", "language": "typescript"}},
        }
        proj = self.mk({"knowledge-base/.graph/graph.json": json.dumps(legacy)})
        loaded = CodeGraph(proj).load()
        self.assertIn("src/a.ts", loaded["files"])


class TestWorkspaceResolution(Base):
    """A monorepo's cross-package import is the architectural edge, not a third-party one.

    Measured before this landed: `apps/mobile` importing `@acme/domain` resolved to
    `external:@acme/domain` — the toolkit reporting the most important relationship in the
    repo as an npm dependency. CD-18.
    """

    WS_ROOT = '{"name":"root","private":true,"workspaces":["packages/*","apps/*"]}'

    def test_a_cross_package_import_is_internal(self):
        proj = self.mk({
            "package.json": self.WS_ROOT,
            "packages/domain/package.json": '{"name":"@acme/domain","main":"src/index.ts"}',
            "packages/domain/src/index.ts": "export const extract = () => 1\n",
            "apps/mobile/package.json": '{"name":"@acme/mobile"}',
            "apps/mobile/src/App.tsx": "import { extract } from '@acme/domain'\n",
        })
        g = CodeGraph(proj)
        g.build(non_interactive=True)
        self.assertIn("packages/domain/src/index.ts",
                      g.query("apps/mobile/src/App.tsx")["imports"])

    def test_the_dependency_gains_a_dependent(self):
        """The blast-radius consequence, which is the reason this matters."""
        proj = self.mk({
            "package.json": self.WS_ROOT,
            "packages/domain/package.json": '{"name":"@acme/domain","main":"src/index.ts"}',
            "packages/domain/src/index.ts": "export const extract = () => 1\n",
            "apps/mobile/package.json": '{"name":"@acme/mobile"}',
            "apps/mobile/src/App.tsx": "import { extract } from '@acme/domain'\n",
        })
        g = CodeGraph(proj)
        g.build(non_interactive=True)
        self.assertIn("apps/mobile/src/App.tsx",
                      g.get_dependents("packages/domain/src/index.ts"))

    def test_a_subpath_import_resolves_inside_the_package(self):
        proj = self.mk({
            "package.json": self.WS_ROOT,
            "packages/domain/package.json": '{"name":"@acme/domain"}',
            "packages/domain/src/dates.ts": "export const fmt = () => 1\n",
            "apps/mobile/package.json": '{"name":"@acme/mobile"}',
            "apps/mobile/src/App.tsx": "import { fmt } from '@acme/domain/src/dates'\n",
        })
        g = CodeGraph(proj)
        g.build(non_interactive=True)
        self.assertIn("packages/domain/src/dates.ts",
                      g.query("apps/mobile/src/App.tsx")["imports"])

    def test_a_package_without_main_falls_back_to_an_index(self):
        proj = self.mk({
            "package.json": self.WS_ROOT,
            "packages/ui/package.json": '{"name":"@acme/ui"}',
            "packages/ui/index.ts": "export const Button = 1\n",
            "apps/mobile/package.json": '{"name":"@acme/mobile"}',
            "apps/mobile/src/App.tsx": "import { Button } from '@acme/ui'\n",
        })
        g = CodeGraph(proj)
        g.build(non_interactive=True)
        self.assertIn("packages/ui/index.ts", g.query("apps/mobile/src/App.tsx")["imports"])

    def test_the_yarn_object_form_is_read(self):
        proj = self.mk({
            "package.json": '{"name":"root","workspaces":{"packages":["libs/*"]}}',
            "libs/core/package.json": '{"name":"@x/core","main":"index.js"}',
            "libs/core/index.js": "module.exports = 1\n",
            "libs/app/package.json": '{"name":"@x/app"}',
            "libs/app/main.js": "const c = require('@x/core')\n",
        })
        g = CodeGraph(proj)
        g.build(non_interactive=True)
        self.assertIn("libs/core/index.js", g.query("libs/app/main.js")["imports"])

    def test_a_pnpm_workspace_file_is_read(self):
        proj = self.mk({
            "package.json": '{"name":"root"}',
            "pnpm-workspace.yaml": "packages:\n  - 'packages/*'\n",
            "packages/domain/package.json": '{"name":"@acme/domain","main":"src/index.ts"}',
            "packages/domain/src/index.ts": "export const e = 1\n",
            "packages/app/package.json": '{"name":"@acme/app"}',
            "packages/app/main.ts": "import { e } from '@acme/domain'\n",
        })
        g = CodeGraph(proj)
        g.build(non_interactive=True)
        self.assertIn("packages/domain/src/index.ts", g.query("packages/app/main.ts")["imports"])

    def test_a_pnpm_file_without_a_packages_key_is_not_a_workspace_root(self):
        """The testbed has exactly this: pnpm-workspace.yaml holding only build settings."""
        proj = self.mk({
            "package.json": '{"name":"solo"}',
            "pnpm-workspace.yaml": "onlyBuiltDependencies:\n  - better-sqlite3\n",
            "src/a.ts": "import React from 'react'\n",
        })
        g = CodeGraph(proj)
        g.build(non_interactive=True)
        self.assertIn("external:react", g.query("src/a.ts")["imports"])

    def test_a_real_npm_package_is_still_external(self):
        proj = self.mk({
            "package.json": self.WS_ROOT,
            "packages/domain/package.json": '{"name":"@acme/domain","main":"src/index.ts"}',
            "packages/domain/src/index.ts": "import React from 'react'\n",
        })
        g = CodeGraph(proj)
        g.build(non_interactive=True)
        self.assertIn("external:react", g.query("packages/domain/src/index.ts")["imports"])

    def test_a_non_workspace_repo_is_unaffected(self):
        proj = self.mk({
            "package.json": '{"name":"solo"}',
            "src/a.ts": "import { b } from '@scope/thing'\n",
        })
        g = CodeGraph(proj)
        g.build(non_interactive=True)
        self.assertIn("external:@scope/thing", g.query("src/a.ts")["imports"])

    def test_a_missing_workspace_target_is_unresolved_not_external(self):
        """It names a package this repo owns, so a failure is a gap, not a third party."""
        proj = self.mk({
            "package.json": self.WS_ROOT,
            "packages/domain/package.json": '{"name":"@acme/domain","main":"src/index.ts"}',
            "packages/domain/src/index.ts": "export const e = 1\n",
            "apps/mobile/package.json": '{"name":"@acme/mobile"}',
            "apps/mobile/src/App.tsx": "import { x } from '@acme/domain/src/missing'\n",
        })
        g = CodeGraph(proj)
        g.build(non_interactive=True)
        imports = g.query("apps/mobile/src/App.tsx")["imports"]
        self.assertIn("unresolved:@acme/domain/src/missing", imports)


class TestNestedClassificationVerdicts(Base):
    """A per-project verdict must be honoured wherever it sits.

    `top_level_exclude_dirs` delegates judgement below the root to classifications.json, on the
    grounds that it is per-project and overridable. That delegation only means something if a
    nested verdict is actually read — and `_scan_files` was keying on the first path component
    alone, so every nested `exclude` was recorded and then ignored.
    """

    def _seed(self, proj, entries):
        gdir = Path(proj) / "knowledge-base" / ".graph"
        gdir.mkdir(parents=True, exist_ok=True)
        (gdir / "classifications.json").write_text(
            json.dumps({"version": 1, "rules_version": "x", "directories": entries}),
            encoding="utf-8")

    def test_a_nested_exclude_verdict_is_honoured(self):
        proj = self.mk({
            "packages/app/src.ts": "export const a = 1\n",
            "packages/legacy/old.ts": "export const o = 1\n",
        })
        self._seed(proj, {
            "packages": {"type": "source", "confidence": 1.0, "source": "user"},
            "packages/legacy": {"type": "exclude", "confidence": 1.0, "source": "user"},
        })
        g = CodeGraph(proj)
        g.build(non_interactive=True)
        files = set(g.graph["files"])
        self.assertIn("packages/app/src.ts", files)
        self.assertNotIn("packages/legacy/old.ts", files)

    def test_a_deeper_verdict_wins_over_its_ancestor(self):
        proj = self.mk({
            "a/b/c/keep.ts": "export const k = 1\n",
            "a/b/drop.ts": "export const d = 1\n",
        })
        self._seed(proj, {
            "a": {"type": "source", "confidence": 1.0, "source": "user"},
            "a/b": {"type": "exclude", "confidence": 1.0, "source": "user"},
            "a/b/c": {"type": "source", "confidence": 1.0, "source": "user"},
        })
        g = CodeGraph(proj)
        g.build(non_interactive=True)
        files = set(g.graph["files"])
        self.assertIn("a/b/c/keep.ts", files)
        self.assertNotIn("a/b/drop.ts", files)


class TestPythonImportResolution(Base):
    """Python's own resolution rules, which the resolver did not implement.

    A sibling module is the ordinary way freya's skills import each other, and it
    was being reported as a third-party package — so the graph had no internal
    edges at all even once the files were in it.
    """

    def test_sibling_module_import_is_internal(self):
        proj = self.mk({
            "pkg/mod_a.py": "import mod_b\n",
            "pkg/mod_b.py": "x = 1\n",
        })
        g = CodeGraph(proj)
        g.build(non_interactive=True)
        self.assertIn("pkg/mod_b.py", g.query("pkg/mod_a.py")["imports"])

    def test_sibling_from_import_is_internal(self):
        proj = self.mk({
            "pkg/mod_a.py": "from mod_c import thing\n",
            "pkg/mod_c.py": "thing = 1\n",
        })
        g = CodeGraph(proj)
        g.build(non_interactive=True)
        self.assertIn("pkg/mod_c.py", g.query("pkg/mod_a.py")["imports"])

    def test_explicit_relative_import_is_internal(self):
        proj = self.mk({
            "pkg/__init__.py": "",
            "pkg/mod_a.py": "from .mod_d import other\n",
            "pkg/mod_d.py": "other = 1\n",
        })
        g = CodeGraph(proj)
        g.build(non_interactive=True)
        self.assertIn("pkg/mod_d.py", g.query("pkg/mod_a.py")["imports"])

    def test_dotted_package_import_is_internal(self):
        proj = self.mk({
            "app/main.py": "from lib.helpers import fn\n",
            "app/lib/__init__.py": "",
            "app/lib/helpers.py": "def fn():\n    return 1\n",
        })
        g = CodeGraph(proj)
        g.build(non_interactive=True)
        self.assertIn("app/lib/helpers.py", g.query("app/main.py")["imports"])

    def test_stdlib_and_third_party_stay_external(self):
        """The regression guard: resolving siblings must not swallow real packages."""
        proj = self.mk({"pkg/mod_a.py": "import json\nimport requests\n"})
        g = CodeGraph(proj)
        g.build(non_interactive=True)
        imports = g.query("pkg/mod_a.py")["imports"]
        self.assertIn("external:json", imports)
        self.assertIn("external:requests", imports)

    def test_a_local_module_shadowing_a_stdlib_name_resolves_locally(self):
        """If `json.py` sits next door, Python imports that. So must the graph."""
        proj = self.mk({
            "pkg/mod_a.py": "import json\n",
            "pkg/json.py": "loads = None\n",
        })
        g = CodeGraph(proj)
        g.build(non_interactive=True)
        self.assertIn("pkg/json.py", g.query("pkg/mod_a.py")["imports"])


class TestPythonSourceRoots(Base):
    """Which directories stand in for `sys.path`.

    Modelling it as exactly (importing file's dir, project root) misses the layout
    the PyPA recommends, and the miss is silent: `from myapp.core.db import X`
    becomes `external:myapp.core.db`, which reads identically to `external:requests`.
    """

    def test_src_layout_resolves(self):
        proj = self.mk({
            "pyproject.toml": '[project]\nname = "myapp"\n',
            "src/myapp/__init__.py": "",
            "src/myapp/core/__init__.py": "",
            "src/myapp/core/db.py": "WHO = 'db'\n",
            "src/myapp/service.py": "from myapp.core.db import WHO\n",
        })
        g = CodeGraph(proj)
        g.build(non_interactive=True)
        self.assertIn("src/myapp/core/db.py",
                      g.query("src/myapp/service.py")["imports"])

    def test_src_layout_gives_the_dependency_a_dependent(self):
        """The blast-radius consequence, which is the reason this matters."""
        proj = self.mk({
            "src/myapp/__init__.py": "",
            "src/myapp/core/__init__.py": "",
            "src/myapp/core/db.py": "WHO = 'db'\n",
            "src/myapp/service.py": "from myapp.core.db import WHO\n",
        })
        g = CodeGraph(proj)
        g.build(non_interactive=True)
        self.assertEqual(g.get_dependents("src/myapp/core/db.py"),
                         {"src/myapp/service.py"})

    def test_a_package_member_does_not_take_a_sibling_over_the_root(self):
        """Python 3 removed implicit relative imports.

        Inside a package, a bare `import utils` is absolute — it must not silently
        bind the sibling `pkg/utils.py`.
        """
        proj = self.mk({
            "utils.py": "ROOT = True\n",
            "pkg/__init__.py": "",
            "pkg/utils.py": "SIBLING = True\n",
            "pkg/mod.py": "import utils\n",
        })
        g = CodeGraph(proj)
        g.build(non_interactive=True)
        self.assertIn("utils.py", g.query("pkg/mod.py")["imports"])
        self.assertNotIn("pkg/utils.py", g.query("pkg/mod.py")["imports"])

    def test_a_loose_script_still_prefers_its_own_directory(self):
        """Outside a package, sys.path[0] is the script's directory, so the sibling wins."""
        proj = self.mk({
            "helpers.py": "ROOT = True\n",
            "tools/helpers.py": "SIBLING = True\n",
            "tools/run.py": "import helpers\n",
        })
        g = CodeGraph(proj)
        g.build(non_interactive=True)
        self.assertIn("tools/helpers.py", g.query("tools/run.py")["imports"])


class TestPackageMembersDoNotSearchTheirOwnDirectory(Base):
    """Python 3 removed implicit relative imports; the resolver must not reinstate them.

    Keeping the importing file's own directory as a last-resort base inside a package makes
    `import logging` bind the sibling `logging.py`. Measured on a 2,098-file stock-library
    corpus: 91 of 91 such edges were wrong, 24 of them self-edges — a file importing itself.
    """

    def test_a_stdlib_name_is_not_captured_by_a_sibling_module(self):
        proj = self.mk({
            "app/__init__.py": "",
            "app/logging.py": "handlers = None\n",
            "app/magics/__init__.py": "",
            "app/magics/auto.py": "import logging\n",
        })
        g = CodeGraph(proj)
        g.build(non_interactive=True)
        imports = g.query("app/magics/auto.py")["imports"]
        self.assertIn("external:logging", imports)
        self.assertNotIn("app/magics/logging.py", imports)
        self.assertNotIn("app/logging.py", imports)

    def test_a_module_never_imports_itself(self):
        proj = self.mk({
            "app/__init__.py": "",
            "app/hooks/__init__.py": "",
            "app/hooks/wx.py": "import wx\n",
        })
        g = CodeGraph(proj)
        g.build(non_interactive=True)
        self.assertNotIn("app/hooks/wx.py", g.query("app/hooks/wx.py")["imports"])

    def test_no_self_edges_anywhere_in_a_built_graph(self):
        proj = self.mk({
            "pkg/__init__.py": "",
            "pkg/json.py": "loads = None\n",
            "pkg/io.py": "import json\nimport io\n",
        })
        g = CodeGraph(proj)
        g.build(non_interactive=True)
        self_edges = [(f, i) for f, info in g.graph["files"].items()
                      for i in info["imports"] if i == f]
        self.assertEqual(self_edges, [])

    def test_a_root_module_shadowing_a_stdlib_name_does_not_import_itself(self):
        """`rich/abc.py` does `from abc import ABC`, meaning the stdlib.

        With the package at the project root the local `abc.py` is the first thing on the
        search path, so resolution finds the importing file itself. Shadowing a stdlib name
        with a *sibling* is real and stays supported; a file depending on itself is not a
        dependency, and it breaks blast radius, which walks edges.
        """
        proj = self.mk({
            "__init__.py": "",
            "abc.py": "from abc import ABC\n",
            "json.py": "from json import loads\n",
            "text.py": "T = 1\n",
        })
        g = CodeGraph(proj)
        g.build(non_interactive=True)
        self.assertNotIn("abc.py", g.query("abc.py")["imports"])
        self.assertNotIn("json.py", g.query("json.py")["imports"])

    def test_no_file_is_its_own_dependent(self):
        proj = self.mk({
            "__init__.py": "",
            "logging.py": "import logging\n",
        })
        g = CodeGraph(proj)
        g.build(non_interactive=True)
        self.assertNotIn("logging.py", g.get_dependents("logging.py"))

    def test_an_absolute_import_inside_a_package_still_reaches_the_package_root(self):
        """The capability that must survive the fix."""
        proj = self.mk({
            "pkg/__init__.py": "",
            "pkg/util.py": "V = 1\n",
            "pkg/deep/__init__.py": "",
            "pkg/deep/mod.py": "from pkg.util import V\n",
        })
        g = CodeGraph(proj)
        g.build(non_interactive=True)
        self.assertIn("pkg/util.py", g.query("pkg/deep/mod.py")["imports"])


class TestCaseSensitivityOfResolvedEdges(Base):
    """An edge must name a file that is actually in the graph.

    macOS and Windows filesystems are case-insensitive, so `Utils.py`.exists() is true when the
    file is `utils.py`. Keying the edge from the import's spelling then produces a target no
    node matches — and makes the graph differ between a macOS dev host and Linux CI.
    """

    def test_a_python_import_with_the_wrong_case_does_not_become_an_edge(self):
        proj = self.mk({
            "pkg/utils.py": "V = 1\n",
            "pkg/main.py": "import Utils\n",
        })
        g = CodeGraph(proj)
        g.build(non_interactive=True)
        imports = g.query("pkg/main.py")["imports"]
        self.assertNotIn("pkg/Utils.py", imports)
        self.assertIn("external:Utils", imports)

    def test_a_ts_import_with_the_wrong_case_does_not_become_an_edge(self):
        proj = self.mk({
            "src/utils.ts": "export const v = 1\n",
            "src/main.ts": "import { v } from './Utils'\n",
        })
        g = CodeGraph(proj)
        g.build(non_interactive=True)
        self.assertNotIn("src/Utils.ts", g.query("src/main.ts")["imports"])

    def test_correct_case_still_resolves(self):
        proj = self.mk({
            "pkg/utils.py": "V = 1\n",
            "pkg/main.py": "import utils\n",
            "src/utils.ts": "export const v = 1\n",
            "src/main.ts": "import { v } from './utils'\n",
        })
        g = CodeGraph(proj)
        g.build(non_interactive=True)
        self.assertIn("pkg/utils.py", g.query("pkg/main.py")["imports"])
        self.assertIn("src/utils.ts", g.query("src/main.ts")["imports"])


class TestSrcBaseIsGatedOnPythonPackaging(Base):
    """`src/` is only a Python source root when Python packaging says so.

    Appending it unconditionally fabricates edges in any repo that merely has a `src/` —
    which is most JS, TS and Rust projects.
    """

    def test_a_js_repo_with_src_does_not_gain_python_edges(self):
        proj = self.mk({
            "package.json": '{"name":"web"}',
            "src/utils.py": "V = 1\n",
            "tools/gen.py": "import utils\n",
        })
        g = CodeGraph(proj)
        g.build(non_interactive=True)
        imports = g.query("tools/gen.py")["imports"]
        self.assertNotIn("src/utils.py", imports)
        self.assertIn("external:utils", imports)

    def test_a_python_src_layout_still_resolves_from_outside_the_package(self):
        proj = self.mk({
            "pyproject.toml": '[project]\nname = "myapp"\n',
            "src/myapp/__init__.py": "",
            "src/myapp/service.py": "V = 1\n",
            "tests/test_service.py": "from myapp.service import V\n",
        })
        g = CodeGraph(proj)
        g.build(non_interactive=True)
        self.assertIn("src/myapp/service.py", g.query("tests/test_service.py")["imports"])


class TestNoPhantomPackagesFromImportSyntax(Base):
    """A regex that captures part of the statement's grammar invents dependencies.

    `from . import leaf` was yielding a package literally named `import`. The edge
    itself is still missed — the module name lives in the import clause, which
    nothing captures — but a wrong answer must not be dressed up as a real one.
    """

    def test_from_dot_import_does_not_invent_a_package_named_import(self):
        proj = self.mk({
            "pkg/__init__.py": "",
            "pkg/leaf.py": "V = 1\n",
            "pkg/deep.py": "from . import leaf\n",
        })
        g = CodeGraph(proj)
        g.build(non_interactive=True)
        imports = g.query("pkg/deep.py")["imports"]
        self.assertNotIn("external:import", imports)
        self.assertFalse([i for i in imports if i.rstrip().endswith(" import")],
                         f"specifier captured part of the statement grammar: {imports}")

    def test_from_dot_import_does_not_emit_a_bare_unresolved_dot(self):
        """`unresolved:` means "meant something in this project and could not be found".

        A bare `unresolved:.` is not that — it is the parser capturing punctuation. Feeding it
        into the coverage-unknown signal makes a healthy project look like it has gaps.
        """
        proj = self.mk({
            "pkg/__init__.py": "",
            "pkg/leaf.py": "V = 1\n",
            "pkg/mod.py": "from . import leaf\n",
        })
        g = CodeGraph(proj)
        g.build(non_interactive=True)
        imports = g.query("pkg/mod.py")["imports"]
        self.assertNotIn("unresolved:.", imports)
        self.assertNotIn("unresolved:..", imports)

    def test_no_specifier_anywhere_ends_in_the_import_keyword(self):
        proj = self.mk({
            "pkg/__init__.py": "",
            "pkg/sub/__init__.py": "",
            "pkg/sub/leaf.py": "V = 1\n",
            "pkg/sibling.py": "V = 2\n",
            "pkg/sub/deep.py": "from . import leaf\nfrom .. import sibling\n",
        })
        g = CodeGraph(proj)
        g.build(non_interactive=True)
        bad = [(f, i) for f, info in g.graph["files"].items()
               for i in info["imports"] if i.rstrip().endswith(" import")
               or i in ("external:import", "unresolved:import")]
        self.assertEqual(bad, [])


class TestTypeOnlyImports(Base):
    """`import type` is a real dependency: the file does not compile without it.

    16 of the 18 edges graphify found and this resolver missed were this form.
    """

    def test_named_type_import_is_an_edge(self):
        proj = self.mk({
            "a.ts": "export type A = string\n",
            "t.ts": "import type { A } from './a'\nexport const t: A = 'x'\n",
        })
        g = CodeGraph(proj)
        g.build(non_interactive=True)
        self.assertIn("a.ts", g.query("t.ts")["imports"])

    def test_default_type_import_is_an_edge(self):
        proj = self.mk({
            "b.ts": "type B = number\nexport default B\n",
            "t.ts": "import type B from './b'\n",
        })
        g = CodeGraph(proj)
        g.build(non_interactive=True)
        self.assertIn("b.ts", g.query("t.ts")["imports"])

    def test_type_only_re_export_is_an_edge(self):
        proj = self.mk({
            "d.ts": "export type D = boolean\n",
            "t.ts": "export type { D } from './d'\n",
        })
        g = CodeGraph(proj)
        g.build(non_interactive=True)
        self.assertIn("d.ts", g.query("t.ts")["imports"])

    def test_inline_type_specifier_still_resolves(self):
        proj = self.mk({
            "e.ts": "export type E = string\nexport const e = 1\n",
            "t.ts": "import { type E, e } from './e'\n",
        })
        g = CodeGraph(proj)
        g.build(non_interactive=True)
        self.assertIn("e.ts", g.query("t.ts")["imports"])


class TestBarrelImports(Base):
    """`import { X } from './dir'` must land on the directory's index file.

    The candidate list tried the bare path first, and a directory satisfies
    `exists()`, so resolution returned the directory and never reached `index.ts`.
    The result was an edge pointing at something that is not a file in the graph —
    the sole dangling edge on the testbed.
    """

    def test_directory_import_resolves_to_its_index(self):
        proj = self.mk({
            "components/accessibility/index.tsx": "export const A = 1\n",
            "components/providers.tsx": "import { A } from './accessibility'\n",
        })
        g = CodeGraph(proj)
        g.build(non_interactive=True)
        self.assertIn("components/accessibility/index.tsx",
                      g.query("components/providers.tsx")["imports"])

    def test_a_python_package_dir_resolves_to_its_init(self):
        proj = self.mk({
            "pkg/sub/__init__.py": "value = 1\n",
            "pkg/main.py": "from sub import value\n",
        })
        g = CodeGraph(proj)
        g.build(non_interactive=True)
        self.assertIn("pkg/sub/__init__.py", g.query("pkg/main.py")["imports"])

    def test_no_edge_points_at_a_directory(self):
        """The invariant behind both: every internal edge names a file in the graph."""
        proj = self.mk({
            "components/accessibility/index.tsx": "export const A = 1\n",
            "components/accessibility/ctx.tsx": "export const C = 1\n",
            "components/providers.tsx": "import { A } from './accessibility'\n",
        })
        g = CodeGraph(proj)
        g.build(non_interactive=True)
        files = set(g.graph["files"])
        dangling = [(s, i) for s, info in g.graph["files"].items()
                    for i in info["imports"]
                    if not i.startswith(("external:", "unresolved:")) and i not in files]
        self.assertEqual(dangling, [])


class TestGitignoreMatchingIsNotSubstring(Base):
    """A gitignore entry matched a path that merely *contained* it.

    `.next` excluded `app/api/auth/[...nextauth]/route.ts`, because the string
    `...nextauth` contains `.next`. A sibling `[...path]` route survived, so the
    hole was invisible until two catch-all routes were compared.
    """

    def test_a_route_whose_name_contains_an_ignored_pattern_is_kept(self):
        proj = self.mk({
            ".gitignore": ".next\nnode_modules\n",
            "app/api/auth/[...nextauth]/route.ts": "export const GET = 1\n",
        })
        g = CodeGraph(proj)
        g.build(non_interactive=True)
        self.assertIn("app/api/auth/[...nextauth]/route.ts", g.graph["files"])

    def test_the_actually_ignored_directory_is_still_excluded(self):
        proj = self.mk({
            ".gitignore": ".next\n",
            "src/a.ts": "export const a = 1\n",
            ".next/static/chunk.js": "var c = 1\n",
        })
        g = CodeGraph(proj)
        g.build(non_interactive=True)
        self.assertIn("src/a.ts", g.graph["files"])
        self.assertNotIn(".next/static/chunk.js", g.graph["files"])

    def test_a_root_anchored_pattern_does_not_match_at_depth(self):
        """`/lib` in .gitignore means the root `lib/`, not every `lib/` in the tree.

        The parser stripped the leading slash before the matcher could honour it, so a
        root-anchored entry silently deleted `src/lib/` — git-tracked source — from the graph.
        """
        proj = self.mk({
            ".gitignore": "/lib\n/generated\n",
            "lib/vendored.ts": "export const v = 1\n",
            "src/lib/auth.ts": "export const a = 1\n",
            "src/app.ts": "import { a } from './lib/auth'\n",
        })
        g = CodeGraph(proj)
        g.build(non_interactive=True)
        files = set(g.graph["files"])
        self.assertNotIn("lib/vendored.ts", files)
        self.assertIn("src/lib/auth.ts", files)
        self.assertIn("src/lib/auth.ts", g.query("src/app.ts")["imports"])

    def test_an_unanchored_pattern_still_matches_at_any_depth(self):
        proj = self.mk({
            ".gitignore": "vendor\n",
            "src/a.ts": "export const a = 1\n",
            "vendor/x.ts": "export const x = 1\n",
            "packages/ui/vendor/y.ts": "export const y = 1\n",
        })
        g = CodeGraph(proj)
        g.build(non_interactive=True)
        self.assertEqual(set(g.graph["files"]), {"src/a.ts"})

    def test_a_negation_re_includes_a_tracked_file(self):
        """`config/*` plus `!config/default.ts` keeps default.ts, as git does.

        Dropping `!` lines meant the resolver excluded a file git tracks — and then emitted a
        dangling edge to it from a file that imports it.
        """
        proj = self.mk({
            ".gitignore": "config/*\n!config/default.ts\n",
            "config/default.ts": "export const d = 1\n",
            "config/secret.ts": "export const s = 1\n",
            "src/a.ts": "import { d } from '../config/default'\n",
        })
        g = CodeGraph(proj)
        g.build(non_interactive=True)
        files = set(g.graph["files"])
        self.assertIn("config/default.ts", files)
        self.assertNotIn("config/secret.ts", files)
        self.assertIn("config/default.ts", g.query("src/a.ts")["imports"])

    def test_a_gitignored_source_dir_is_still_excluded(self):
        proj = self.mk({
            ".gitignore": "secret/\n",
            "src/a.ts": "export const a = 1\n",
            "secret/leak.ts": "export const s = 1\n",
        })
        g = CodeGraph(proj)
        g.build(non_interactive=True)
        self.assertIn("src/a.ts", g.graph["files"])
        self.assertNotIn("secret/leak.ts", g.graph["files"])


class TestThisRepoGraphsItself(Base):
    """The end-to-end assertion the old suite could not make.

    Every defect above was individually invisible to a synthetic fixture. What
    made them visible was pointing the resolver at a real repo, so that check is
    now part of the suite rather than a thing someone remembers to do.
    """

    def test_a_skill_shaped_python_tree_yields_internal_edges(self):
        proj = self.mk({
            "bin/cli.py": "import installer\n",
            "bin/installer.py": "import json\n",
            "skills/thing/scripts/behavior_graph.py": "from frontmatter import parse\n",
            "skills/thing/scripts/frontmatter.py": "def parse():\n    return {}\n",
            "skills/thing/scripts/test_behavior_graph.py": "import behavior_graph\n",
        })
        g = CodeGraph(proj)
        g.build(non_interactive=True)

        internal = {
            (src, imp)
            for src, info in g.graph["files"].items()
            for imp in info["imports"]
            if not imp.startswith(("external:", "unresolved:"))
        }
        self.assertEqual(len(g.graph["files"]), 5)
        self.assertGreaterEqual(len(internal), 3, f"expected real wiring, got {internal}")
        self.assertIn(
            ("skills/thing/scripts/test_behavior_graph.py",
             "skills/thing/scripts/behavior_graph.py"), internal)


if __name__ == "__main__":
    unittest.main(verbosity=2)
