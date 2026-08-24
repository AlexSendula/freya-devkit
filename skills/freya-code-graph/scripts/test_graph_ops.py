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

import contextlib
import io
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path, PurePosixPath, PureWindowsPath

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import containment  # noqa: E402
import graph_ops  # noqa: E402
import settings  # noqa: E402
import substrate  # noqa: E402
from graph_ops import CodeGraph, normalize_import, normalize_key  # noqa: E402
from substrate import edge_ends as ends  # noqa: E402


def _git_repo(path):
    """Make `path` a git repository with one commit, and return its short HEAD."""
    env = dict(os.environ, GIT_AUTHOR_NAME="t", GIT_AUTHOR_EMAIL="t@e",
               GIT_COMMITTER_NAME="t", GIT_COMMITTER_EMAIL="t@e")
    for argv in (["git", "init", "-q"], ["git", "add", "-A"],
                 ["git", "commit", "-qm", "init"]):
        subprocess.run(argv, cwd=path, env=env, capture_output=True, check=True)
    out = subprocess.run(["git", "rev-parse", "HEAD"], cwd=path, env=env,
                         capture_output=True, text=True, check=True)
    return out.stdout.strip()[:12]


def _commit(path, message="next"):
    """Commit everything in `path`, and return the new short HEAD.

    Separate from `_git_repo` because the incremental path only exists between two commits:
    `--update` asks git what moved since the commit the cached graph recorded, so a second
    commit is the whole fixture for it.
    """
    env = dict(os.environ, GIT_AUTHOR_NAME="t", GIT_AUTHOR_EMAIL="t@e",
               GIT_COMMITTER_NAME="t", GIT_COMMITTER_EMAIL="t@e")
    for argv in (["git", "add", "-A"], ["git", "commit", "-qm", message]):
        subprocess.run(argv, cwd=path, env=env, capture_output=True, check=True)
    out = subprocess.run(["git", "rev-parse", "HEAD"], cwd=path, env=env,
                         capture_output=True, text=True, check=True)
    return out.stdout.strip()[:12]


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
        graph_ops.run_build(g)
        self.assertIn("src/b.ts", ends(g.query("src/c.ts")["imports"]))
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
        graph_ops.run_build(g, non_interactive=True)
        self.assertIn("lib/webauthn.ts", ends(g.query("app/route.ts")["imports"]))
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
        graph_ops.run_build(g)
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
            graph_ops.run_build(CodeGraph(proj))
        finally:
            os.chdir(cwd)
        self.assertIn("src/b.ts", CodeGraph(proj).get_dependencies("src/a.ts"))


class TestUnresolvedSignal(Base):
    def test_unresolved_relative_is_marked_not_dropped(self):
        """A relative import to a missing file is recorded as unresolved:, not dropped (§6)."""
        proj = self.mk({"src/d.ts": "import x from './missing'\nexport const d = 1\n"})
        g = CodeGraph(proj)
        graph_ops.run_build(g)
        self.assertIn("unresolved:./missing", ends(g.query("src/d.ts")["imports"]))

    def test_external_package_still_external(self):
        """Genuine bare packages stay external: (regression guard for Fix 4)."""
        proj = self.mk({"src/e.ts": "import React from 'react'\nexport const e = 1\n"})
        g = CodeGraph(proj)
        graph_ops.run_build(g)
        self.assertIn("external:react", ends(g.query("src/e.ts")["imports"]))


class TestNonInteractiveBuild(Base):
    def test_ambiguous_dir_included_without_stdin(self):
        """Non-interactive build must not block on stdin and should not drop real source (F6)."""
        proj = self.mk({"weirddir/x.ts": "export const x = 1\n"})
        graph_ops.run_build(CodeGraph(proj), non_interactive=True)
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

        `graph.*.json` covers the per-backend artifacts (ADR-028), which are as
        regenerable as graph.json and must not turn the cache back into a `*`.
        """
        proj = self.mk({"src/b.ts": "export const b = 1\n"})
        graph_ops.run_build(CodeGraph(proj))
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
        graph_ops.run_build(CodeGraph(proj), non_interactive=True)
        self.assertEqual(self._lines(gdir / ".gitignore"),
                         ["graph.json", "graph.*.json", "classifications.json", "docs.json"])

    def test_leaves_a_customised_gitignore_alone(self):
        proj = self.mk({"src/b.ts": "export const b = 1\n"})
        gdir = Path(proj) / "knowledge-base" / ".graph"
        gdir.mkdir(parents=True, exist_ok=True)
        (gdir / ".gitignore").write_text("mine.json\n", encoding="utf-8")
        graph_ops.run_build(CodeGraph(proj), non_interactive=True)
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
        graph_ops.run_build(CodeGraph(proj), non_interactive=True)
        files = CodeGraph(proj).load()["files"]
        self.assertIn("src/lib/auth.ts", files)
        self.assertEqual([k for k in files if "\\" in k], [])
        self.assertIn("src/lib/auth.ts", ends(files["src/c.ts"]["imports"]))

    def test_lookups_accept_a_native_windows_argument(self):
        """A Windows user pastes what their shell/git produced; the key stays POSIX."""
        proj = self.mk({
            "src/a.ts": "import { b } from './b'\nexport const a = 1\n",
            "src/b.ts": "export const b = 1\n",
        })
        g = CodeGraph(proj)
        graph_ops.run_build(g, non_interactive=True)
        self.assertEqual(g.query("src\\a.ts")["file"], "src/a.ts")
        self.assertIn("src/b.ts", g.get_dependencies("src\\a.ts"))
        self.assertIn("src/a.ts", g.get_dependents("src\\b.ts"))

    def test_impact_cancels_its_inputs_however_they_were_spelled(self):
        proj = self.mk({
            "src/a.ts": "import { b } from './b'\nexport const a = 1\n",
            "src/b.ts": "export const b = 1\n",
        })
        g = CodeGraph(proj)
        graph_ops.run_build(g, non_interactive=True)
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
        self.assertIn("src/b.ts", ends(info["imports"]))
        self.assertIn("unresolved:./missing", ends(info["imports"]))  # signal survives migration
        self.assertIn("external:react", ends(info["imports"]))
        self.assertEqual(g.get_dependencies("src/a.ts"), {"src/b.ts"})
        self.assertEqual(g.get_dependents("src/b.ts"), {"src/a.ts"})

    def test_migration_leaves_a_current_cache_untouched(self):
        """POSIX keys and object edges: nothing for either migration to do."""
        clean = {
            "version": 2,
            "files": {
                "src/a.ts": {
                    "exports": [], "dependents": [],
                    "imports": [{"to": "src/b.ts", "kind": "imports",
                                 "provenance": "extracted"}],
                },
                "src/b.ts": {
                    "exports": [], "imports": [],
                    "dependents": [{"from": "src/a.ts", "kind": "imports",
                                    "provenance": "extracted"}],
                },
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

    Matching the name at *any* depth is what hid 40 of this repo's 51 Python files.
    The fix is depth, not deletion: at the root the convention holds, below it the
    name promises nothing. Generated and vendored trees stay excluded at every depth.
    """

    def test_code_under_a_nested_scripts_dir_is_graphed(self):
        proj = self.mk({
            "skills/thing/scripts/mod_a.py": "import mod_b\n",
            "skills/thing/scripts/mod_b.py": "x = 1\n",
        })
        g = CodeGraph(proj)
        graph_ops.run_build(g, non_interactive=True)
        self.assertIn("skills/thing/scripts/mod_a.py", g.graph["files"])
        self.assertIn("skills/thing/scripts/mod_b.py", g.graph["files"])

    def test_a_top_level_scripts_dir_is_excluded(self):
        """Restored deliberately, after dropping the name outright went too far.

        A root `scripts/` had been excluded in every project this toolkit had ever run
        on. Un-excluding it everywhere to fix one repo's *nested* `skills/*/scripts/`
        changed the answer for projects that had not asked for anything.
        """
        proj = self.mk({
            "src/a.ts": "export const a = 1\n",
            "scripts/tool.ts": "export const z = 1\n",
        })
        g = CodeGraph(proj)
        graph_ops.run_build(g, non_interactive=True)
        self.assertEqual(set(g.graph["files"]), {"src/a.ts"})

    def test_a_top_level_convention_dir_is_still_excluded(self):
        """At the root, `docs/` and `examples/` do mean what the convention says.

        Measured: indexing this repo's own `docs/` pulled in the published site's
        bundled JS and a spike's planted fixtures — noise in every blast radius.
        That tree is now `knowledge-base/`, excluded by a different rule; the fixture
        below is synthetic and tests the root-convention rule on its own terms.
        """
        proj = self.mk({
            "src/a.ts": "export const a = 1\n",
            "docs/site/bundle.js": "var b = 1\n",
            "examples/demo.ts": "export const d = 1\n",
        })
        g = CodeGraph(proj)
        graph_ops.run_build(g, non_interactive=True)
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
        graph_ops.run_build(g, non_interactive=True)
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
        graph_ops.run_build(g, non_interactive=True)
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
        graph_ops.run_build(g, non_interactive=True)
        self.assertEqual(set(g.graph["files"]), {"src/a.ts"})


class TestEdgesAreObjects(Base):
    """An edge carries more than a destination.

    A string can state exactly one fact — where the edge points — so `a imports b` and
    `a re-exports b` were the same string, and `a calls b` could not be written down at
    all. Phase 0 measured the cost against graphify on the testbed: of 5,027 links, our
    shape could express 2,102. The missing 58% are not detail about the same edges, they
    are edges with a kind and symbol ends that a string has nowhere to put.
    """

    def edges(self, g, path, key="imports"):
        return g.query(path)[key]

    def test_an_import_edge_carries_kind_and_provenance(self):
        proj = self.mk({
            "src/a.ts": "import { b } from './b'\n",
            "src/b.ts": "export const b = 1\n",
        })
        g = CodeGraph(proj)
        graph_ops.run_build(g, non_interactive=True)
        self.assertEqual(self.edges(g, "src/a.ts"), [
            {"to": "src/b.ts", "kind": "imports", "provenance": "extracted"},
        ])

    def test_a_barrel_re_export_is_a_different_kind(self):
        """`export * from './y'` and `import {x} from './y'` were the same edge."""
        proj = self.mk({
            "src/index.ts": "export * from './widget'\n",
            "src/widget.ts": "export const w = 1\n",
        })
        g = CodeGraph(proj)
        graph_ops.run_build(g, non_interactive=True)
        self.assertEqual(self.edges(g, "src/index.ts"), [
            {"to": "src/widget.ts", "kind": "re_exports", "provenance": "extracted"},
        ])

    def test_importing_and_re_exporting_the_same_module_is_one_import_edge(self):
        """Two edges to one target would double it in every dependents list."""
        proj = self.mk({
            "src/index.ts": "import { w } from './widget'\nexport * from './widget'\n",
            "src/widget.ts": "export const w = 1\n",
        })
        g = CodeGraph(proj)
        graph_ops.run_build(g, non_interactive=True)
        self.assertEqual(self.edges(g, "src/index.ts"), [
            {"to": "src/widget.ts", "kind": "imports", "provenance": "extracted"},
        ])

    def test_two_specifiers_naming_one_file_are_one_edge(self):
        """Deduping by specifier is not enough — `./sub` and `./sub/index` are two
        specifiers and one file. Left as two edges they contradict each other on `kind` and
        double the target in every dependents list, which is exactly what the dedupe exists
        to prevent."""
        proj = self.mk({
            "src/index.ts": ("import { q } from './sub'\n"
                             "export * from './sub/index'\n"),
            "src/sub/index.ts": "export const q = 1\n",
        })
        g = CodeGraph(proj)
        graph_ops.run_build(g, non_interactive=True)
        self.assertEqual(self.edges(g, "src/index.ts"), [
            {"to": "src/sub/index.ts", "kind": "imports", "provenance": "extracted"},
        ])
        self.assertEqual(len(self.edges(g, "src/sub/index.ts", "dependents")), 1)

    def test_a_pure_barrel_reached_by_two_specifiers_stays_a_re_export(self):
        proj = self.mk({
            "src/index.ts": ("export * from './sub'\n"
                             "export * from './sub/index'\n"),
            "src/sub/index.ts": "export const q = 1\n",
        })
        g = CodeGraph(proj)
        graph_ops.run_build(g, non_interactive=True)
        self.assertEqual(self.edges(g, "src/index.ts"), [
            {"to": "src/sub/index.ts", "kind": "re_exports", "provenance": "extracted"},
        ])

    def test_the_reverse_edge_keeps_the_forward_edge_s_kind(self):
        proj = self.mk({
            "src/index.ts": "export * from './widget'\n",
            "src/widget.ts": "export const w = 1\n",
        })
        g = CodeGraph(proj)
        graph_ops.run_build(g, non_interactive=True)
        self.assertEqual(self.edges(g, "src/widget.ts", "dependents"), [
            {"from": "src/index.ts", "kind": "re_exports", "provenance": "extracted"},
        ])

    def test_signals_are_edges_too(self):
        proj = self.mk({"src/a.ts": "import r from 'react'\nimport x from './gone'\n"})
        g = CodeGraph(proj)
        graph_ops.run_build(g, non_interactive=True)
        self.assertEqual(
            sorted((e["to"], e["kind"]) for e in self.edges(g, "src/a.ts")),
            [("external:react", "imports"), ("unresolved:./gone", "imports")])

    def test_the_backend_now_claims_the_relation_it_emits(self):
        """Claiming only `imports` while emitting re-exports would be the overclaim
        problem inverted — a caller cannot ask for what the coverage denies."""
        relations = CodeGraph(self.mk({})).coverage().relations
        self.assertEqual(relations, ("imports", "re_exports"))

    def test_node_queries_still_answer_in_paths(self):
        """`--impact`, `--dependents` and `--dependencies` answer "which files".

        Three other skills feed those straight into set arithmetic; an edge object there
        would raise `unhashable type: 'dict'` inside a set literal, in a different skill,
        for no gain — the caller asked which files, not how.
        """
        proj = self.mk({
            "src/a.ts": "import { b } from './b'\n",
            "src/b.ts": "export const b = 1\n",
        })
        g = CodeGraph(proj)
        graph_ops.run_build(g, non_interactive=True)
        self.assertEqual(g.get_dependencies("src/a.ts"), {"src/b.ts"})
        self.assertEqual(g.get_dependents("src/b.ts"), {"src/a.ts"})
        self.assertEqual(g.get_impact(["src/b.ts"])["direct_dependents"], {"src/a.ts"})


class TestOlderGraphsWithStringEdges(Base):
    """A graph.json already on disk has string edges, and must still be readable.

    The artifact is gitignored, so there is no committed copy to fix in a commit —
    whatever is on a given machine is whatever the last build there wrote. Refusing to
    read it would look exactly like a project with no dependencies, which is the failure
    this whole initiative exists to remove.
    """

    def stale(self, proj):
        return self.mk({"knowledge-base/.graph/graph.json": json.dumps({
            "version": 1,
            # A commit, so `update()` reaches its "nothing changed" path rather than
            # falling back to a full build. There is no git repo in the fixture, so
            # `git diff` fails and the changed-file list is empty — which is the state
            # a real steady-state `--update` is in almost every time it runs.
            "commit": "abc123def456",
            "files": {
                "src/a.ts": {"exports": [], "dependents": [],
                             "imports": ["src/b.ts", "external:react"]},
                "src/b.ts": {"exports": [], "imports": [], "dependents": ["src/a.ts"]},
            },
        })})

    def test_string_edges_are_upgraded_on_read(self):
        g = CodeGraph(self.stale(None))
        info = g.load()["files"]["src/a.ts"]
        self.assertEqual(info["imports"], [
            {"to": "src/b.ts", "kind": "imports", "provenance": "extracted"},
            {"to": "external:react", "kind": "imports", "provenance": "extracted"},
        ])

    def test_the_upgrade_does_not_claim_a_kind_the_old_resolver_never_determined(self):
        """`imports`/`extracted` is exactly what the string era could express."""
        g = CodeGraph(self.stale(None))
        kinds = {e["kind"] for i in g.load()["files"].values() for e in i["imports"]}
        self.assertEqual(kinds, {"imports"})

    def test_queries_answer_correctly_against_an_un_rebuilt_cache(self):
        g = CodeGraph(self.stale(None))
        self.assertEqual(g.get_dependencies("src/a.ts"), {"src/b.ts"})
        self.assertEqual(g.get_dependents("src/b.ts"), {"src/a.ts"})

    def test_reading_does_not_pretend_the_file_on_disk_was_upgraded(self):
        """`version` records what is on disk. Stamping it on read would make every graph
        report itself current the instant it was read — which is when we find out it is
        not, so nothing would ever rewrite it."""
        g = CodeGraph(self.stale(None))
        self.assertTrue(substrate.is_stale(g.load()))

    def test_a_stale_artifact_triggers_a_full_rebuild_not_a_rewrite(self):
        """A rewrite was the first attempt, and it was worse than doing nothing.

        A graph old enough to be stale may predate the `substrate` metadata block, and that
        block cannot be reconstructed from the artifact — only a real build knows which
        backend ran and what it can see. Stamping the version without it left the graph
        claiming no backend and no coverage, *and* stopped it being stale, so nothing would
        ever have looked at it again.
        """
        proj = self.mk({
            "src/a.ts": "import { b } from './b'\n",
            "src/b.ts": "export const b = 1\n",
            "knowledge-base/.graph/graph.json": json.dumps({
                "version": 1,
                "commit": "abc123def456",
                "files": {"src/a.ts": {"exports": [], "imports": ["src/b.ts"],
                                       "dependents": []}},
            }),
        })
        out = graph_ops.run_update(CodeGraph(proj), non_interactive=True)

        self.assertEqual(out["status"], substrate.Result.BUILT)
        on_disk = json.loads(
            (Path(proj) / "knowledge-base" / ".graph" / "graph.json").read_text())
        self.assertFalse(substrate.is_stale(on_disk))
        self.assertEqual(on_disk["files"]["src/a.ts"]["imports"][0]["to"], "src/b.ts")

    def test_the_rebuilt_artifact_carries_real_substrate_metadata(self):
        """The whole reason it is a rebuild. `backend` and `coverage` are what let a caller
        tell an empty repo from a blind backend, and they cannot be invented."""
        proj = self.mk({
            "src/a.ts": "export const a = 1\n",
            "knowledge-base/.graph/graph.json": json.dumps({
                "version": 1, "commit": "abc123def456",
                "files": {"src/a.ts": {"exports": [], "imports": [], "dependents": []}},
            }),
        })
        graph_ops.run_update(CodeGraph(proj), non_interactive=True)
        block = json.loads((Path(proj) / "knowledge-base" / ".graph"
                            / "graph.json").read_text())["substrate"]
        self.assertEqual(block["backend"], "homegrown")
        self.assertTrue(block["coverage"]["languages"])
        self.assertNotIn("validation", block)

    def test_a_current_artifact_is_not_rebuilt_for_nothing(self):
        """Needs a real repository: the cached commit has to be one git can resolve, or the
        answer is "cannot tell" rather than "nothing changed"."""
        proj = self.mk({"src/a.ts": "export const a = 1\n"})
        head = _git_repo(proj)
        gdir = Path(proj) / "knowledge-base" / ".graph"
        gdir.mkdir(parents=True, exist_ok=True)
        (gdir / "graph.json").write_text(json.dumps({
            "version": substrate.GRAPH_SCHEMA_VERSION, "commit": head, "files": {},
        }), encoding="utf-8")
        out = graph_ops.run_update(CodeGraph(proj), non_interactive=True)
        self.assertEqual(out["status"], substrate.Result.UP_TO_DATE)

    def test_a_commit_git_cannot_resolve_rebuilds_rather_than_reporting_no_changes(self):
        """`[]` from git used to mean both "nothing changed" and "git could not say", so a
        commit that had been rebased or squashed away — or a graph carried between checkouts —
        reported "up to date" forever and the graph never refreshed."""
        proj = self.mk({"src/a.ts": "export const a = 1\n"})
        _git_repo(proj)
        gdir = Path(proj) / "knowledge-base" / ".graph"
        gdir.mkdir(parents=True, exist_ok=True)
        (gdir / "graph.json").write_text(json.dumps({
            "version": substrate.GRAPH_SCHEMA_VERSION,
            "commit": "0" * 12, "files": {},
        }), encoding="utf-8")
        out = graph_ops.run_update(CodeGraph(proj), non_interactive=True)
        self.assertEqual(out["status"], substrate.Result.BUILT)
        self.assertIn("src/a.ts", json.loads(
            (gdir / "graph.json").read_text())["files"])


class TestAnOverrideSurvivesAClone(Base):
    """An override recorded only in the cache is an override only one machine has.

    The first version of this feature put it in `knowledge-base/.graph/classifications.json`,
    which `CACHE_GITIGNORE` declares regenerable and not to be committed. It worked for
    whoever typed it and vanished on clone: CI and every colleague graphed a smaller codebase
    and were told the build succeeded. ADR-019 had already rejected that file as a home for a
    decision, on exactly this ground, before the override was put in it.
    """

    def settings(self, proj, directories):
        kb = Path(proj) / "knowledge-base"
        kb.mkdir(parents=True, exist_ok=True)
        (kb / "settings.json").write_text(
            json.dumps({"directories": directories}), encoding="utf-8")

    def test_a_committed_verdict_overrides_a_convention_name(self):
        proj = self.mk({"docs/literate/engine.ts": "export const e = 1\n"})
        self.settings(proj, {"docs": "source"})
        g = CodeGraph(proj)
        graph_ops.run_build(g, non_interactive=True, exclusions=g.project_exclusions())
        self.assertIn("docs/literate/engine.ts", g.graph["files"])

    def test_it_still_works_with_the_gitignored_cache_deleted(self):
        """The clone. `knowledge-base/.graph/` never travels; `settings.json` does."""
        proj = self.mk({"docs/literate/engine.ts": "export const e = 1\n"})
        self.settings(proj, {"docs": "source"})
        g = CodeGraph(proj)
        graph_ops.run_build(g, non_interactive=True, exclusions=g.project_exclusions())
        shutil.rmtree(Path(proj) / "knowledge-base" / ".graph")

        fresh = CodeGraph(proj)
        graph_ops.run_build(fresh, non_interactive=True,
                            exclusions=fresh.project_exclusions())
        self.assertIn("docs/literate/engine.ts", fresh.graph["files"])

    def test_a_committed_verdict_beats_a_stale_cached_rule_verdict(self):
        proj = self.mk({"docs/literate/engine.ts": "export const e = 1\n"})
        g = CodeGraph(proj)
        graph_ops.run_build(g, non_interactive=True)
        self.assertEqual(set(g.graph["files"]), set())      # docs excluded, cached as `rule`

        self.settings(proj, {"docs": "source"})
        g2 = CodeGraph(proj)
        graph_ops.run_build(g2, non_interactive=True, exclusions=g2.project_exclusions())
        self.assertIn("docs/literate/engine.ts", g2.graph["files"])

    def test_a_committed_exclude_narrows_scope_too(self):
        proj = self.mk({
            "src/a.ts": "export const a = 1\n",
            "src/legacy/old.ts": "export const o = 1\n",
        })
        self.settings(proj, {"src/legacy": "exclude"})
        g = CodeGraph(proj)
        graph_ops.run_build(g, non_interactive=True, exclusions=g.project_exclusions())
        self.assertEqual(set(g.graph["files"]), {"src/a.ts"})

    def test_the_spellings_people_actually_type_all_resolve(self):
        """The docs write directories with a trailing slash throughout, Windows users type
        backslashes, and hand-edited files pick up `./`. Only one spelling used to match —
        the rest were dead keys with no error, no warning, and no effect."""
        for spelling in ("docs/", "./docs", "docs", "/docs/"):
            with self.subTest(spelling=spelling):
                proj = self.mk({"docs/literate/engine.ts": "export const e = 1\n"})
                self.settings(proj, {spelling: "source"})
                g = CodeGraph(proj)
                graph_ops.run_build(g, non_interactive=True,
                                    exclusions=g.project_exclusions())
                self.assertIn("docs/literate/engine.ts", g.graph["files"], spelling)

    def test_a_bad_verdict_warns_and_is_skipped_rather_than_crashing(self):
        proj = self.mk({"docs/literate/engine.ts": "export const e = 1\n"})
        self.settings(proj, {"docs": "yes please"})
        g = CodeGraph(proj)
        graph_ops.run_build(g, non_interactive=True, exclusions=g.project_exclusions())
        self.assertEqual(set(g.graph["files"]), set())

    def test_a_hand_edited_shorthand_in_the_cache_does_not_abort_the_build(self):
        """`"docs": "source"` in classifications.json is the obvious mistake — the docs talk
        about a `source` field. It used to abort the build with a raw AttributeError."""
        proj = self.mk({"src/a.ts": "export const a = 1\n"})
        gdir = Path(proj) / "knowledge-base" / ".graph"
        gdir.mkdir(parents=True, exist_ok=True)
        (gdir / "classifications.json").write_text(json.dumps({
            "version": 1, "rules_version": graph_ops.RULES_VERSION,
            "directories": {"docs": "source", "src": None},
        }), encoding="utf-8")
        g = CodeGraph(proj)
        graph_ops.run_build(g, non_interactive=True)
        self.assertIn("src/a.ts", g.graph["files"])


class TestAProjectCanOverrideTheDefaults(Base):
    """The name lists above are defaults, and a project must be able to disagree.

    Until 2026-08-20 it could not. `set_classification('docs', 'source')` was accepted,
    written to classifications.json, and then silently overruled by `_should_exclude`,
    which never consulted classifications at all — so a `source` verdict was inert and a
    wrong default was unfixable. That is the real defect behind the depth argument: the
    lists here cannot know what some other repository keeps where, and the only honest
    answer is to let that repository say.
    """

    def _seed(self, proj, entries):
        gdir = Path(proj) / "knowledge-base" / ".graph"
        gdir.mkdir(parents=True, exist_ok=True)
        (gdir / "classifications.json").write_text(
            json.dumps({"version": 1, "rules_version": graph_ops.RULES_VERSION,
                        "directories": entries}), encoding="utf-8")
        return gdir

    def test_a_user_source_verdict_beats_a_top_level_convention_name(self):
        proj = self.mk({"docs/literate/engine.ts": "export const e = 1\n"})
        self._seed(proj, {
            "docs": {"type": "source", "confidence": 1.0, "source": "user"},
        })
        g = CodeGraph(proj)
        graph_ops.run_build(g, non_interactive=True)
        self.assertIn("docs/literate/engine.ts", g.graph["files"])

    def test_a_nested_user_source_verdict_is_reachable(self):
        """A verdict nobody ever globs for is not an override.

        Scan roots are top-level, so a verdict on `docs/literate` also has to widen the
        root to `docs` — otherwise the file it was about is never a candidate, and the
        override records an opinion that changes nothing.
        """
        proj = self.mk({
            "docs/literate/engine.ts": "export const e = 1\n",
            "docs/site/bundle.js": "var b = 1\n",
        })
        self._seed(proj, {
            "docs/literate": {"type": "source", "confidence": 1.0, "source": "user"},
        })
        g = CodeGraph(proj)
        graph_ops.run_build(g, non_interactive=True)
        self.assertEqual(set(g.graph["files"]), {"docs/literate/engine.ts"})

    def test_a_user_source_verdict_beats_an_artifact_tree_name(self):
        """The strong tier. `target/` is Maven's build dir and somebody's source dir."""
        proj = self.mk({"target/app.py": "x = 1\n"})
        self._seed(proj, {
            "target": {"type": "source", "confidence": 1.0, "source": "user"},
        })
        g = CodeGraph(proj)
        graph_ops.run_build(g, non_interactive=True)
        self.assertIn("target/app.py", g.graph["files"])

    def test_a_model_source_verdict_does_not_beat_an_artifact_tree_name(self):
        """The weak tier. A model guessing `node_modules` is source is a real failure
        mode; a person typing it is not. So `ai` overrides conventions, not artifacts."""
        proj = self.mk({
            "src/a.ts": "export const a = 1\n",
            "node_modules/pkg/index.js": "module.exports = {}\n",
        })
        self._seed(proj, {
            "src": {"type": "source", "confidence": 1.0, "source": "rule"},
            "node_modules": {"type": "source", "confidence": 0.9, "source": "ai"},
        })
        g = CodeGraph(proj)
        graph_ops.run_build(g, non_interactive=True)
        self.assertEqual(set(g.graph["files"]), {"src/a.ts"})

    def test_a_model_source_verdict_does_beat_a_convention_name(self):
        proj = self.mk({"examples/widget.ts": "export const w = 1\n"})
        self._seed(proj, {
            "examples": {"type": "source", "confidence": 0.9, "source": "ai"},
        })
        g = CodeGraph(proj)
        graph_ops.run_build(g, non_interactive=True)
        self.assertIn("examples/widget.ts", g.graph["files"])

    def test_an_override_beats_gitignore(self):
        """git's opinion about what to commit is not the question being asked.

        Two layers had to agree for this to work: `_should_exclude`, and the `Exclusions`
        the CLI passes back into `build()` — which is assembled from the same .gitignore
        and would otherwise have filtered the file out again one step later.
        """
        proj = self.mk({
            "generated/api/client.ts": "export const c = 1\n",
            ".gitignore": "generated/\n",
        })
        self._seed(proj, {
            "generated": {"type": "source", "confidence": 1.0, "source": "user"},
        })
        g = CodeGraph(proj)
        graph_ops.run_build(g, non_interactive=True, exclusions=g.project_exclusions())
        self.assertIn("generated/api/client.ts", g.graph["files"])

    def test_a_rule_verdict_cannot_override_the_rules_that_produced_it(self):
        """Otherwise the escape hatch is circular: the lists would be overriding
        themselves via the cache they just wrote."""
        proj = self.mk({"docs/site/bundle.js": "var b = 1\n"})
        self._seed(proj, {
            "docs": {"type": "source", "confidence": 1.0, "source": "rule"},
        })
        g = CodeGraph(proj)
        graph_ops.run_build(g, non_interactive=True)
        self.assertEqual(set(g.graph["files"]), set())

    def test_a_deeper_exclude_still_wins_inside_an_override(self):
        proj = self.mk({
            "docs/literate/engine.ts": "export const e = 1\n",
            "docs/literate/legacy/old.ts": "export const o = 1\n",
        })
        self._seed(proj, {
            "docs/literate": {"type": "source", "confidence": 1.0, "source": "user"},
            "docs/literate/legacy": {"type": "exclude", "confidence": 1.0,
                                     "source": "user"},
        })
        g = CodeGraph(proj)
        graph_ops.run_build(g, non_interactive=True, exclusions=g.project_exclusions())
        self.assertEqual(set(g.graph["files"]), {"docs/literate/engine.ts"})

    def test_file_kind_patterns_are_not_overridable(self):
        """`*.d.ts` is a claim about what a file is, not about which dirs are in scope."""
        proj = self.mk({
            "docs/literate/engine.ts": "export const e = 1\n",
            "docs/literate/types.d.ts": "declare const t: number;\n",
        })
        self._seed(proj, {
            "docs": {"type": "source", "confidence": 1.0, "source": "user"},
        })
        g = CodeGraph(proj)
        graph_ops.run_build(g, non_interactive=True)
        self.assertEqual(set(g.graph["files"]), {"docs/literate/engine.ts"})

    def test_set_classification_is_no_longer_inert(self):
        """The end-to-end path a user actually takes, which used to do nothing."""
        proj = self.mk({"docs/literate/engine.ts": "export const e = 1\n"})
        g = CodeGraph(proj)
        graph_ops.run_build(g, non_interactive=True)
        self.assertEqual(set(g.graph["files"]), set())

        g.set_classification("docs", "source", "it really is source here")
        g2 = CodeGraph(proj)
        graph_ops.run_build(g2, non_interactive=True, exclusions=g2.project_exclusions())
        self.assertIn("docs/literate/engine.ts", g2.graph["files"])


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
        proj = self.mk({"src/tool.py": "x = 1\n"})
        self._seed(proj, {
            "src": {"type": "exclude", "confidence": 1.0, "source": "rule"},
        }, version="something-old")
        g = CodeGraph(proj)
        graph_ops.run_build(g, non_interactive=True)
        self.assertIn("src/tool.py", g.graph["files"])

    def test_a_user_verdict_survives_a_rules_change(self):
        proj = self.mk({"vendor_ish/tool.py": "x = 1\n"})
        self._seed(proj, {
            "vendor_ish": {"type": "exclude", "confidence": 1.0, "source": "user"},
        }, version="something-old")
        g = CodeGraph(proj)
        graph_ops.run_build(g, non_interactive=True)
        self.assertNotIn("vendor_ish/tool.py", g.graph["files"])
        self.assertEqual(
            self._classifications(proj)["directories"]["vendor_ish"]["source"], "user")

    def test_an_ai_verdict_survives_a_rules_change(self):
        proj = self.mk({"odd/tool.py": "x = 1\n"})
        self._seed(proj, {
            "odd": {"type": "exclude", "confidence": 0.8, "source": "ai"},
        }, version="something-old")
        g = CodeGraph(proj)
        graph_ops.run_build(g, non_interactive=True)
        self.assertNotIn("odd/tool.py", g.graph["files"])

    def test_the_current_rules_version_is_recorded_so_the_next_change_propagates(self):
        proj = self.mk({"src/a.py": "x = 1\n"})
        graph_ops.run_build(CodeGraph(proj), non_interactive=True)
        self.assertIn("rules_version", self._classifications(proj))


class TestDeadCategoryFieldIsGone(Base):
    """ADR-021. `category` was written on every file and read by nothing.

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
        graph_ops.run_build(g, non_interactive=True)
        self.assertTrue(g.graph["files"], "fixture graphed nothing; the loop below is vacuous")
        for path, info in g.graph["files"].items():
            with self.subTest(path=path):
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
    repo as an npm dependency. ADR-019.
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
        graph_ops.run_build(g, non_interactive=True)
        self.assertIn("packages/domain/src/index.ts",
                      ends(g.query("apps/mobile/src/App.tsx")["imports"]))

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
        graph_ops.run_build(g, non_interactive=True)
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
        graph_ops.run_build(g, non_interactive=True)
        self.assertIn("packages/domain/src/dates.ts",
                      ends(g.query("apps/mobile/src/App.tsx")["imports"]))

    def test_a_package_without_main_falls_back_to_an_index(self):
        proj = self.mk({
            "package.json": self.WS_ROOT,
            "packages/ui/package.json": '{"name":"@acme/ui"}',
            "packages/ui/index.ts": "export const Button = 1\n",
            "apps/mobile/package.json": '{"name":"@acme/mobile"}',
            "apps/mobile/src/App.tsx": "import { Button } from '@acme/ui'\n",
        })
        g = CodeGraph(proj)
        graph_ops.run_build(g, non_interactive=True)
        self.assertIn("packages/ui/index.ts", ends(g.query("apps/mobile/src/App.tsx")["imports"]))

    def test_the_yarn_object_form_is_read(self):
        proj = self.mk({
            "package.json": '{"name":"root","workspaces":{"packages":["libs/*"]}}',
            "libs/core/package.json": '{"name":"@x/core","main":"index.js"}',
            "libs/core/index.js": "module.exports = 1\n",
            "libs/app/package.json": '{"name":"@x/app"}',
            "libs/app/main.js": "const c = require('@x/core')\n",
        })
        g = CodeGraph(proj)
        graph_ops.run_build(g, non_interactive=True)
        self.assertIn("libs/core/index.js", ends(g.query("libs/app/main.js")["imports"]))

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
        graph_ops.run_build(g, non_interactive=True)
        self.assertIn("packages/domain/src/index.ts", ends(g.query("packages/app/main.ts")["imports"]))

    def test_a_pnpm_file_without_a_packages_key_is_not_a_workspace_root(self):
        """The testbed has exactly this: pnpm-workspace.yaml holding only build settings."""
        proj = self.mk({
            "package.json": '{"name":"solo"}',
            "pnpm-workspace.yaml": "onlyBuiltDependencies:\n  - better-sqlite3\n",
            "src/a.ts": "import React from 'react'\n",
        })
        g = CodeGraph(proj)
        graph_ops.run_build(g, non_interactive=True)
        self.assertIn("external:react", ends(g.query("src/a.ts")["imports"]))

    def test_a_real_npm_package_is_still_external(self):
        proj = self.mk({
            "package.json": self.WS_ROOT,
            "packages/domain/package.json": '{"name":"@acme/domain","main":"src/index.ts"}',
            "packages/domain/src/index.ts": "import React from 'react'\n",
        })
        g = CodeGraph(proj)
        graph_ops.run_build(g, non_interactive=True)
        self.assertIn("external:react", ends(g.query("packages/domain/src/index.ts")["imports"]))

    def test_a_package_vendored_under_node_modules_is_not_a_workspace_member(self):
        """`packages/**` matches node_modules too, and the damage is not just noise.

        A vendored copy of `react` got adopted as a workspace package, so `import React from
        'react'` — a genuine third-party dependency — resolved as internal and came back
        `unresolved:react`. The graph then asserts a real dependency is a missing local file.
        """
        proj = self.mk({
            "package.json": '{"name":"root","workspaces":["packages/**"]}',
            "packages/a/package.json": '{"name":"@x/a","main":"i.ts"}',
            "packages/a/i.ts": "export const i = 1\n",
            "packages/a/node_modules/react/package.json": '{"name":"react","main":"i.js"}',
            "packages/a/node_modules/react/i.js": "module.exports = 1\n",
            "src/app.ts": "import React from 'react'\n",
        })
        g = CodeGraph(proj)
        graph_ops.run_build(g, non_interactive=True)
        self.assertIn("external:react", ends(g.query("src/app.ts")["imports"]))

    def test_no_name_in_the_never_a_workspace_list_can_yield_a_member(self):
        """Driven off `_NEVER_A_WORKSPACE` itself, so a name added to it is covered here
        the day it is added — the test above pins `node_modules` and nothing else did.

        The list is the only gate in `_load_workspace_packages`: eight names, two of which
        were ever named by a test. Each fixture plants a manifest one level under the
        member name and a *real* sibling package beside it, then asserts the observable
        consequence — the vendored name resolves `external:`, i.e. it was never adopted.

        The sibling is the anti-vacuity half. Without it a glob that reached nothing at all
        would produce the same `external:` answer and the table would pass with
        `_load_workspace_packages` deleted outright.
        """
        names = sorted(graph_ops._NEVER_A_WORKSPACE)
        # Non-emptiness only, not the membership: `assertEqual(names, [...])` would
        # re-state the constant and pass with the gate that reads it deleted. An empty
        # registry, though, makes the loop below pass by iterating nothing.
        self.assertTrue(names, "_NEVER_A_WORKSPACE is empty; the table proves nothing")
        for name in names:
            with self.subTest(directory=name):
                proj = self.mk({
                    "package.json": '{"name":"root","private":true,'
                                    '"workspaces":["packages/**"]}',
                    "packages/real/package.json": '{"name":"@x/real","main":"i.ts"}',
                    "packages/real/i.ts": "export const i = 1\n",
                    "packages/real/%s/vendored/package.json" % name:
                        '{"name":"@x/vendored","main":"v.js"}',
                    "packages/real/%s/vendored/v.js" % name: "module.exports = 1\n",
                    "src/app.ts": "import { i } from '@x/real'\n"
                                  "import { v } from '@x/vendored'\n",
                })
                g = CodeGraph(proj)
                graph_ops.run_build(g, non_interactive=True)
                imports = ends(g.query("src/app.ts")["imports"])
                self.assertIn("packages/real/i.ts", imports,
                              "%s: the glob never reached the sibling, so the "
                              "external: answer below proves nothing" % name)
                self.assertIn("external:@x/vendored", imports,
                              "%s adopted a package as a workspace member" % name)
                self.assertNotIn("@x/vendored", g._load_workspace_packages())

    def test_an_absolute_workspace_pattern_does_not_break_the_build(self):
        """Path.glob rejects an absolute pattern on the 3.9 floor CI runs."""
        proj = self.mk({
            "package.json": '{"name":"root","workspaces":["/abs/elsewhere/*","packages/*"]}',
            "packages/a/package.json": '{"name":"@x/a","main":"i.ts"}',
            "packages/a/i.ts": "export const i = 1\n",
            "src/app.ts": "import { i } from '@x/a'\n",
        })
        g = CodeGraph(proj)
        graph_ops.run_build(g, non_interactive=True)
        self.assertIn("packages/a/i.ts", ends(g.query("src/app.ts")["imports"]))

    def test_a_pattern_escaping_the_project_is_ignored(self):
        proj = self.mk({
            "package.json": '{"name":"root","workspaces":["../outside/*","packages/*"]}',
            "packages/a/package.json": '{"name":"@x/a","main":"i.ts"}',
            "packages/a/i.ts": "export const i = 1\n",
        })
        g = CodeGraph(proj)
        graph_ops.run_build(g, non_interactive=True)
        self.assertIn("packages/a/i.ts", g.graph["files"])

    def test_a_non_workspace_repo_is_unaffected(self):
        proj = self.mk({
            "package.json": '{"name":"solo"}',
            "src/a.ts": "import { b } from '@scope/thing'\n",
        })
        g = CodeGraph(proj)
        graph_ops.run_build(g, non_interactive=True)
        self.assertIn("external:@scope/thing", ends(g.query("src/a.ts")["imports"]))

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
        graph_ops.run_build(g, non_interactive=True)
        imports = ends(g.query("apps/mobile/src/App.tsx")["imports"])
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
        graph_ops.run_build(g, non_interactive=True)
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
        graph_ops.run_build(g, non_interactive=True)
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
        graph_ops.run_build(g, non_interactive=True)
        self.assertIn("pkg/mod_b.py", ends(g.query("pkg/mod_a.py")["imports"]))

    def test_sibling_from_import_is_internal(self):
        proj = self.mk({
            "pkg/mod_a.py": "from mod_c import thing\n",
            "pkg/mod_c.py": "thing = 1\n",
        })
        g = CodeGraph(proj)
        graph_ops.run_build(g, non_interactive=True)
        self.assertIn("pkg/mod_c.py", ends(g.query("pkg/mod_a.py")["imports"]))

    def test_explicit_relative_import_is_internal(self):
        proj = self.mk({
            "pkg/__init__.py": "",
            "pkg/mod_a.py": "from .mod_d import other\n",
            "pkg/mod_d.py": "other = 1\n",
        })
        g = CodeGraph(proj)
        graph_ops.run_build(g, non_interactive=True)
        self.assertIn("pkg/mod_d.py", ends(g.query("pkg/mod_a.py")["imports"]))

    def test_dotted_package_import_is_internal(self):
        proj = self.mk({
            "app/main.py": "from lib.helpers import fn\n",
            "app/lib/__init__.py": "",
            "app/lib/helpers.py": "def fn():\n    return 1\n",
        })
        g = CodeGraph(proj)
        graph_ops.run_build(g, non_interactive=True)
        self.assertIn("app/lib/helpers.py", ends(g.query("app/main.py")["imports"]))

    def test_stdlib_and_third_party_stay_external(self):
        """The regression guard: resolving siblings must not swallow real packages."""
        proj = self.mk({"pkg/mod_a.py": "import json\nimport requests\n"})
        g = CodeGraph(proj)
        graph_ops.run_build(g, non_interactive=True)
        imports = ends(g.query("pkg/mod_a.py")["imports"])
        self.assertIn("external:json", imports)
        self.assertIn("external:requests", imports)

    def test_a_local_module_shadowing_a_stdlib_name_resolves_locally(self):
        """If `json.py` sits next door, Python imports that. So must the graph."""
        proj = self.mk({
            "pkg/mod_a.py": "import json\n",
            "pkg/json.py": "loads = None\n",
        })
        g = CodeGraph(proj)
        graph_ops.run_build(g, non_interactive=True)
        self.assertIn("pkg/json.py", ends(g.query("pkg/mod_a.py")["imports"]))


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
        graph_ops.run_build(g, non_interactive=True)
        self.assertIn("src/myapp/core/db.py",
                      ends(g.query("src/myapp/service.py")["imports"]))

    def test_src_layout_gives_the_dependency_a_dependent(self):
        """The blast-radius consequence, which is the reason this matters."""
        proj = self.mk({
            "src/myapp/__init__.py": "",
            "src/myapp/core/__init__.py": "",
            "src/myapp/core/db.py": "WHO = 'db'\n",
            "src/myapp/service.py": "from myapp.core.db import WHO\n",
        })
        g = CodeGraph(proj)
        graph_ops.run_build(g, non_interactive=True)
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
        graph_ops.run_build(g, non_interactive=True)
        self.assertIn("utils.py", ends(g.query("pkg/mod.py")["imports"]))
        self.assertNotIn("pkg/utils.py", ends(g.query("pkg/mod.py")["imports"]))

    def test_a_loose_script_still_prefers_its_own_directory(self):
        """Outside a package, sys.path[0] is the script's directory, so the sibling wins."""
        proj = self.mk({
            "helpers.py": "ROOT = True\n",
            "tools/helpers.py": "SIBLING = True\n",
            "tools/run.py": "import helpers\n",
        })
        g = CodeGraph(proj)
        graph_ops.run_build(g, non_interactive=True)
        self.assertIn("tools/helpers.py", ends(g.query("tools/run.py")["imports"]))


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
        graph_ops.run_build(g, non_interactive=True)
        imports = ends(g.query("app/magics/auto.py")["imports"])
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
        graph_ops.run_build(g, non_interactive=True)
        self.assertNotIn("app/hooks/wx.py", ends(g.query("app/hooks/wx.py")["imports"]))

    def test_no_self_edges_anywhere_in_a_built_graph(self):
        proj = self.mk({
            "pkg/__init__.py": "",
            "pkg/json.py": "loads = None\n",
            "pkg/io.py": "import json\nimport io\n",
        })
        g = CodeGraph(proj)
        graph_ops.run_build(g, non_interactive=True)
        self_edges = [(f, i) for f, info in g.graph["files"].items()
                      for i in ends(info["imports"]) if i == f]
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
        graph_ops.run_build(g, non_interactive=True)
        self.assertNotIn("abc.py", ends(g.query("abc.py")["imports"]))
        self.assertNotIn("json.py", ends(g.query("json.py")["imports"]))

    def test_no_file_is_its_own_dependent(self):
        proj = self.mk({
            "__init__.py": "",
            "logging.py": "import logging\n",
        })
        g = CodeGraph(proj)
        graph_ops.run_build(g, non_interactive=True)
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
        graph_ops.run_build(g, non_interactive=True)
        self.assertIn("pkg/util.py", ends(g.query("pkg/deep/mod.py")["imports"]))


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
        graph_ops.run_build(g, non_interactive=True)
        imports = ends(g.query("pkg/main.py")["imports"])
        self.assertNotIn("pkg/Utils.py", imports)
        self.assertIn("external:Utils", imports)

    def test_a_ts_import_with_the_wrong_case_does_not_become_an_edge(self):
        proj = self.mk({
            "src/utils.ts": "export const v = 1\n",
            "src/main.ts": "import { v } from './Utils'\n",
        })
        g = CodeGraph(proj)
        graph_ops.run_build(g, non_interactive=True)
        self.assertNotIn("src/Utils.ts", ends(g.query("src/main.ts")["imports"]))

    def test_correct_case_still_resolves(self):
        proj = self.mk({
            "pkg/utils.py": "V = 1\n",
            "pkg/main.py": "import utils\n",
            "src/utils.ts": "export const v = 1\n",
            "src/main.ts": "import { v } from './utils'\n",
        })
        g = CodeGraph(proj)
        graph_ops.run_build(g, non_interactive=True)
        self.assertIn("pkg/utils.py", ends(g.query("pkg/main.py")["imports"]))
        self.assertIn("src/utils.ts", ends(g.query("src/main.ts")["imports"]))


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
        graph_ops.run_build(g, non_interactive=True)
        imports = ends(g.query("tools/gen.py")["imports"])
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
        graph_ops.run_build(g, non_interactive=True)
        self.assertIn("src/myapp/service.py", ends(g.query("tests/test_service.py")["imports"]))


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
        graph_ops.run_build(g, non_interactive=True)
        imports = ends(g.query("pkg/deep.py")["imports"])
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
        graph_ops.run_build(g, non_interactive=True)
        imports = ends(g.query("pkg/mod.py")["imports"])
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
        graph_ops.run_build(g, non_interactive=True)
        bad = [(f, i) for f, info in g.graph["files"].items()
               for i in ends(info["imports"]) if i.rstrip().endswith(" import")
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
        graph_ops.run_build(g, non_interactive=True)
        self.assertIn("a.ts", ends(g.query("t.ts")["imports"]))

    def test_default_type_import_is_an_edge(self):
        proj = self.mk({
            "b.ts": "type B = number\nexport default B\n",
            "t.ts": "import type B from './b'\n",
        })
        g = CodeGraph(proj)
        graph_ops.run_build(g, non_interactive=True)
        self.assertIn("b.ts", ends(g.query("t.ts")["imports"]))

    def test_type_only_re_export_is_an_edge(self):
        proj = self.mk({
            "d.ts": "export type D = boolean\n",
            "t.ts": "export type { D } from './d'\n",
        })
        g = CodeGraph(proj)
        graph_ops.run_build(g, non_interactive=True)
        self.assertIn("d.ts", ends(g.query("t.ts")["imports"]))

    def test_inline_type_specifier_still_resolves(self):
        proj = self.mk({
            "e.ts": "export type E = string\nexport const e = 1\n",
            "t.ts": "import { type E, e } from './e'\n",
        })
        g = CodeGraph(proj)
        graph_ops.run_build(g, non_interactive=True)
        self.assertIn("e.ts", ends(g.query("t.ts")["imports"]))


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
        graph_ops.run_build(g, non_interactive=True)
        self.assertIn("components/accessibility/index.tsx",
                      ends(g.query("components/providers.tsx")["imports"]))

    def test_a_python_package_dir_resolves_to_its_init(self):
        proj = self.mk({
            "pkg/sub/__init__.py": "value = 1\n",
            "pkg/main.py": "from sub import value\n",
        })
        g = CodeGraph(proj)
        graph_ops.run_build(g, non_interactive=True)
        self.assertIn("pkg/sub/__init__.py", ends(g.query("pkg/main.py")["imports"]))

    def test_no_edge_points_at_a_directory(self):
        """The invariant behind both: every internal edge names a file in the graph."""
        proj = self.mk({
            "components/accessibility/index.tsx": "export const A = 1\n",
            "components/accessibility/ctx.tsx": "export const C = 1\n",
            "components/providers.tsx": "import { A } from './accessibility'\n",
        })
        g = CodeGraph(proj)
        graph_ops.run_build(g, non_interactive=True)
        files = set(g.graph["files"])
        dangling = [(s, i) for s, info in g.graph["files"].items()
                    for i in ends(info["imports"])
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
        graph_ops.run_build(g, non_interactive=True)
        self.assertIn("app/api/auth/[...nextauth]/route.ts", g.graph["files"])

    def test_the_actually_ignored_directory_is_still_excluded(self):
        proj = self.mk({
            ".gitignore": ".next\n",
            "src/a.ts": "export const a = 1\n",
            ".next/static/chunk.js": "var c = 1\n",
        })
        g = CodeGraph(proj)
        graph_ops.run_build(g, non_interactive=True)
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
        graph_ops.run_build(g, non_interactive=True)
        files = set(g.graph["files"])
        self.assertNotIn("lib/vendored.ts", files)
        self.assertIn("src/lib/auth.ts", files)
        self.assertIn("src/lib/auth.ts", ends(g.query("src/app.ts")["imports"]))

    def test_an_unanchored_pattern_still_matches_at_any_depth(self):
        proj = self.mk({
            ".gitignore": "vendor\n",
            "src/a.ts": "export const a = 1\n",
            "vendor/x.ts": "export const x = 1\n",
            "packages/ui/vendor/y.ts": "export const y = 1\n",
        })
        g = CodeGraph(proj)
        graph_ops.run_build(g, non_interactive=True)
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
        graph_ops.run_build(g, non_interactive=True)
        files = set(g.graph["files"])
        self.assertIn("config/default.ts", files)
        self.assertNotIn("config/secret.ts", files)
        self.assertIn("config/default.ts", ends(g.query("src/a.ts")["imports"]))

    def test_a_gitignored_source_dir_is_still_excluded(self):
        proj = self.mk({
            ".gitignore": "secret/\n",
            "src/a.ts": "export const a = 1\n",
            "secret/leak.ts": "export const s = 1\n",
        })
        g = CodeGraph(proj)
        graph_ops.run_build(g, non_interactive=True)
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
        graph_ops.run_build(g, non_interactive=True)

        internal = {
            (src, imp)
            for src, info in g.graph["files"].items()
            for imp in ends(info["imports"])
            if not imp.startswith(("external:", "unresolved:"))
        }
        self.assertEqual(len(g.graph["files"]), 5)
        self.assertGreaterEqual(len(internal), 3, f"expected real wiring, got {internal}")
        self.assertIn(
            ("skills/thing/scripts/test_behavior_graph.py",
             "skills/thing/scripts/behavior_graph.py"), internal)


class TestRenamesLeaveNoGhostNode(Base):
    """`--update` asks git which paths changed, and git answers with rename *semantics*.

    With detection on — the default — a moved file is reported once, as its destination,
    and the path it vanished from is never named. `update()` only removes an entry when git
    names it, so the old path stayed in the graph forever: `--dependents` on it answered
    confidently with files that no longer import it, and only a full `--build` cleared it.
    """

    def _commit(self, proj, message):
        env = dict(os.environ, GIT_AUTHOR_NAME="t", GIT_AUTHOR_EMAIL="t@e",
                   GIT_COMMITTER_NAME="t", GIT_COMMITTER_EMAIL="t@e")
        subprocess.run(["git", "add", "-A"], cwd=proj, env=env, capture_output=True)
        subprocess.run(["git", "commit", "-qm", message], cwd=proj, env=env,
                       capture_output=True, check=True)

    def test_the_old_path_leaves_the_graph(self):
        proj = self.mk({
            "src/a.ts": "export const a = 1\n",
            "src/b.ts": "import { a } from './a'\nexport const b = a\n",
        })
        _git_repo(proj)
        g = CodeGraph(proj)
        graph_ops.run_build(g)
        self.assertIn("src/a.ts", g.load()["files"])

        env = dict(os.environ, GIT_AUTHOR_NAME="t", GIT_AUTHOR_EMAIL="t@e",
                   GIT_COMMITTER_NAME="t", GIT_COMMITTER_EMAIL="t@e")
        subprocess.run(["git", "mv", "src/a.ts", "src/renamed.ts"], cwd=proj, env=env,
                       capture_output=True, check=True)
        (Path(proj) / "src" / "b.ts").write_text(
            "import { a } from './renamed'\nexport const b = a\n", encoding="utf-8")
        self._commit(proj, "rename")

        graph_ops.run_update(CodeGraph(proj))
        files = CodeGraph(proj).load()["files"]
        self.assertIn("src/renamed.ts", files)
        self.assertNotIn("src/a.ts", files, "the vanished path is still a graph node")


class TestASettingsVerdictCanBeWithdrawn(Base):
    """A committed verdict was folded into the gitignored cache and persisted there.

    It then outlived the file that declared it: deleting the entry from settings.json
    changed nothing, because the cached copy still outranked every rule, survived the
    RULES_VERSION discard (only `rule`/`gitignore` are dropped) and survived `--clear`.
    The only way back was to hand-edit a cache the toolkit says is regenerable — which
    inverts ADR-019 exactly.
    """

    def test_removing_the_entry_takes_effect_on_the_next_build(self):
        proj = self.mk({
            "src/a.ts": "export const a = 1\n",
            "docs/d.ts": "export const d = 1\n",
            "knowledge-base/settings.json": '{"directories": {"docs": "source"}}\n',
        })
        graph_ops.run_build(CodeGraph(proj), non_interactive=True)
        self.assertIn("docs/d.ts", CodeGraph(proj).load()["files"])

        (Path(proj) / "knowledge-base" / "settings.json").write_text("{}\n",
                                                                     encoding="utf-8")
        graph_ops.run_build(CodeGraph(proj), non_interactive=True)
        self.assertNotIn("docs/d.ts", CodeGraph(proj).load()["files"])

    def test_the_verdict_is_never_written_into_the_cache(self):
        proj = self.mk({
            "src/a.ts": "export const a = 1\n",
            "docs/d.ts": "export const d = 1\n",
            "knowledge-base/settings.json": '{"directories": {"docs": "source"}}\n',
        })
        graph_ops.run_build(CodeGraph(proj), non_interactive=True)
        cached = json.loads(
            (Path(proj) / "knowledge-base" / ".graph" / "classifications.json")
            .read_text(encoding="utf-8"))
        self.assertNotIn("docs", cached["directories"])


class TestRefusingToEraseIsARefusalNotACrash(Base):
    """Excluding the last source directory is an ordinary thing to commit.

    The refusal is right — an empty graph over a populated one is the confident-empty
    failure — but it reached the user as an unhandled `EmptiedTheGraph` traceback and exit
    1, with the composed explanation buried inside it.
    """

    def test_it_reports_and_exits_rather_than_raising(self):
        proj = self.mk({
            "src/a.ts": "export const a = 1\n",
            "knowledge-base/settings.json": "{}\n",
        })
        graph_ops.run_build(CodeGraph(proj), non_interactive=True)
        (Path(proj) / "knowledge-base" / "settings.json").write_text(
            '{"directories": {"src": "exclude"}}\n', encoding="utf-8")

        out = subprocess.run(
            [sys.executable, str(Path(graph_ops.__file__)), "--build", "--dir", proj,
             "--non-interactive"],
            capture_output=True, text=True)
        self.assertEqual(out.returncode, 1)
        self.assertIn("refusing to overwrite", out.stderr)
        self.assertNotIn("Traceback", out.stderr)
        # And the previous graph is still there.
        self.assertIn("src/a.ts", CodeGraph(proj).load()["files"])


class TestImpactSaysWhenItHasNeverSeenAFile(Base):
    """`--dependents` on an unknown file has always said so; `--impact` did not.

    It returned `all_affected: []` with exit 0 and nothing on stderr, which reads as
    "nothing depends on this" and means "I have never seen this file" — and `--impact` is
    the one wrap-up calls.
    """

    def test_an_unindexed_input_is_reported(self):
        proj = self.mk({"src/a.ts": "export const a = 1\n"})
        g = CodeGraph(proj)
        graph_ops.run_build(g)
        result = CodeGraph(proj).get_impact(["src/a.ts", "Main.java"])
        self.assertEqual(result["not_in_graph"], {"Main.java"})
        self.assertNotIn("Main.java", result["all_affected"])

    def test_a_fully_known_input_reports_nothing_extra(self):
        proj = self.mk({"src/a.ts": "export const a = 1\n"})
        graph_ops.run_build(CodeGraph(proj))
        self.assertEqual(CodeGraph(proj).get_impact(["src/a.ts"])["not_in_graph"], set())


class TestRecordingTheBackendChoice(Base):
    """`--use` is the whole reason `settings.write` finally has a caller.

    Before it, the only way to opt into a backend was hand-authoring JSON — a writer existed,
    with no way to invoke it, and the sole discovery path was a stderr hint that fired only
    once you had already installed the thing it was recommending.
    """

    def setUp(self):
        self.home = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.home, ignore_errors=True)
        self.previous = os.environ.get("FREYA_HOME")
        os.environ["FREYA_HOME"] = self.home
        self.addCleanup(self._restore)

    def _restore(self):
        if self.previous is None:
            os.environ.pop("FREYA_HOME", None)
        else:
            os.environ["FREYA_HOME"] = self.previous

    def run_cli(self, *args, cwd=None):
        env = dict(os.environ, FREYA_HOME=self.home)
        return subprocess.run(
            [sys.executable, graph_ops.__file__, *args],
            capture_output=True, text=True, env=env, cwd=cwd)

    def project(self):
        return self.mk({"src/a.ts": "export const a = 1\n"})

    def test_an_unknown_name_is_refused_with_a_non_zero_exit(self):
        """A name that reaches settings.json unchecked resolves to nothing, degrades to the
        floor, and the project spends a week believing it opted into something."""
        proj = self.project()
        out = self.run_cli("--use", "grapheefy", "--dir", proj)
        self.assertEqual(out.returncode, 2)
        self.assertIn("not a backend", out.stderr)
        self.assertFalse(os.path.exists(settings.settings_path(proj)))

    def test_a_known_name_is_written_to_the_project(self):
        proj = self.project()
        out = self.run_cli("--use", "graphify", "--dir", proj)
        self.assertEqual(out.returncode, 0, out.stderr)
        self.assertEqual(settings.load(proj).backend, "graphify")
        self.assertIn("Commit", out.stdout)

    def test_global_scope_writes_the_machine_default(self):
        proj = self.project()
        out = self.run_cli("--use", "graphify", "--global", "--dir", proj)
        self.assertEqual(out.returncode, 0, out.stderr)
        self.assertFalse(os.path.exists(settings.settings_path(proj)),
                         "--global must not also write into whatever project happens to be "
                         "the working directory")
        data, _ = settings.load_global()
        self.assertEqual(data["substrate"]["backend"], "graphify")

    def test_a_build_carries_the_machine_default_into_the_project(self):
        proj = self.project()
        self.run_cli("--use", "graphify", "--global", "--dir", proj)
        out = self.run_cli("--build", "--dir", proj, "--non-interactive")
        self.assertEqual(out.returncode, 0, out.stderr)
        self.assertEqual(settings.load(proj).backend, "graphify")
        self.assertIn("Commit it", out.stderr)

    def test_a_build_with_nothing_configured_writes_nothing(self):
        """The floor recorded as though somebody chose it is a decision nobody made."""
        proj = self.project()
        out = self.run_cli("--build", "--dir", proj, "--non-interactive")
        self.assertEqual(out.returncode, 0, out.stderr)
        self.assertFalse(os.path.exists(settings.settings_path(proj)))

    def test_a_project_that_opted_out_is_not_re_seeded(self):
        proj = self.project()
        self.run_cli("--use", "homegrown", "--dir", proj)
        self.run_cli("--use", "graphify", "--global", "--dir", proj)
        self.run_cli("--build", "--dir", proj, "--non-interactive")
        self.assertEqual(settings.load(proj).backend, "homegrown")


class TestUnmappedSourceWalk(Base):
    """ADR-029 — the census walk, and the scope rule it has to honour.

    The scope rule is the whole difference between a signal and noise. Measured on this
    repository, a census that consults only gitignore-style patterns reports 96 unread files of
    which 68 are deliberately out of scope — a 71% phantom. These pin the four rules that
    remove it.
    """

    def walk(self, files, exclusions=None):
        d = self.mk(files)
        g = CodeGraph(d)
        return graph_ops._unmapped_source_paths(
            g, ['.ts', '.tsx', '.js', '.jsx', '.py', '.go'], exclusions)

    def test_it_finds_the_unread_source(self):
        paths, truncated = self.walk({
            "web/src/a.ts": "export const a = 1\n",
            "src/main/java/com/acme/A.java": "class A {}\n",
            "src/main/java/com/acme/B.java": "class B {}\n",
        })
        self.assertEqual(sorted(paths), ["src/main/java/com/acme/A.java",
                                         "src/main/java/com/acme/B.java"])
        self.assertFalse(truncated)

    def test_it_honours_the_build_s_own_exclusions(self):
        """Not `substrate.exclusions` from the artifact — that is a strict subset of the real
        rule, and on a first build it is computed before classification has even run.

        Every excluded path here is one only `_should_exclude` rejects. An earlier version of
        this test used `node_modules/` and `dist/`, which `CENSUS_PRUNE` removes *before*
        `_should_exclude` is ever called — so the line it existed to pin could be deleted with
        the whole suite green. `scripts/` and `docs/` are `top_level_exclude_dirs`, `x.min.js`
        is an `always_exclude_files` pattern, and `deep/vendor/` is an always-excluded name
        below depth one.
        """
        paths, _ = self.walk({
            "src/a.ts": "export const a = 1\n",
            "scripts/tool.java": "class T {}\n",
            "docs/sample.java": "class D {}\n",
            "deep/vendor/V.java": "class V {}\n",
            "real/Z.java": "class Z {}\n",
        })
        self.assertEqual(paths, ["real/Z.java"])

    def test_the_prune_list_and_the_scope_rule_both_apply(self):
        """CENSUS_PRUNE is an optimisation, not the scope rule. Both must hold."""
        paths, _ = self.walk({
            "src/a.ts": "export const a = 1\n",
            "node_modules/pkg/X.java": "class X {}\n",
            "a/b/dist/Y.java": "class Y {}\n",
            "real/Z.java": "class Z {}\n",
        })
        self.assertEqual(paths, ["real/Z.java"])

    def test_it_honours_a_caller_supplied_exclusions_on_top(self):
        """Obligation 6: the two layers `build()` applies, both applied here."""
        files = {"src/a.ts": "export const a = 1\n", "thirdparty/B.java": "class B {}\n"}
        self.assertEqual(self.walk(files)[0], ["thirdparty/B.java"])
        excl = substrate.Exclusions(directories=["thirdparty"])
        self.assertEqual(self.walk(files, excl)[0], [])

    def test_dotfiles_and_extensionless_files_are_skipped(self):
        """`Coverage.blind_spots` has no dotfile guard and yields `.local` for `.env.local`.
        The two implementations disagree; this asserts which one the census follows."""
        paths, _ = self.walk({
            "src/a.ts": "export const a = 1\n",
            # Dotfiles whose extensions ARE candidates, so the guard is what rejects them
            # rather than the extension check. The earlier fixture used `.env.local` and
            # `.eslintrc.json`, whose extensions are in neither tier list — so every file was
            # dropped before the dotfile guard ran, and the guard could be deleted with the
            # suite green.
            ".prettierrc.cjs": "module.exports={}\n",
            "a/.eslintrc.mjs": "export default {}\n",
            "bin/freya": "#!/bin/sh\n",
            "Makefile": "all:\n",
        })
        self.assertEqual(paths, [])

    def test_the_limit_bounds_the_walk_and_says_so(self):
        files = {"src/a.ts": "export const a = 1\n"}
        files.update({"j/C%d.java" % i: "class C%d {}\n" % i for i in range(10)})
        d = self.mk(files)
        paths, truncated = graph_ops._unmapped_source_paths(
            CodeGraph(d), ['.ts'], None, limit=4)
        self.assertEqual(len(paths), 4)
        self.assertTrue(truncated)

    def test_a_census_that_raises_never_takes_the_build_down(self):
        """A census failure must not fail a build, and must not look like a clean census."""
        d = self.mk({"src/a.ts": "export const a = 1\n"})
        g = CodeGraph(d)
        original = graph_ops._unmapped_source_paths
        graph_ops._unmapped_source_paths = lambda *a, **k: (_ for _ in ()).throw(OSError("no"))
        try:
            block = graph_ops._census(g, {"files": {}})
        finally:
            graph_ops._unmapped_source_paths = original
        self.assertIsNone(block["files"])
        self.assertEqual(block["error"], "OSError")


class TestScaleAndScopeDefects(Base):
    """Four defects the final review found, each reproduced before it was fixed."""

    def test_a_long_import_chain_does_not_blow_the_stack(self):
        """A recursive DFS is bounded by the size of the reachable component, not by depth.
        A 2,000-file chain — an ordinary monorepo — raised RecursionError and exited non-zero,
        which `run_behaviors` (check=True) turns into `graph-query-failed`, then
        `coverage: unknown` for every integration behaviour, then a frozen committed
        behavior.json. A stack overflow here narrows every blast radius elsewhere."""
        n = 1500
        files = {}
        for i in range(n):
            imp = 'import { x%d } from "./f%d";\n' % (i + 1, i + 1) if i + 1 < n else ''
            files['src/f%d.ts' % i] = imp + 'export const x%d = 1;\n' % i
        g = CodeGraph(self.mk(files))
        graph_ops.run_build(g, non_interactive=True)
        self.assertEqual(len(g.get_dependents('src/f%d.ts' % (n - 1))), n - 1)
        self.assertEqual(len(g.get_dependencies('src/f0.ts')), n - 1)

    def test_update_works_when_the_project_is_below_the_git_root(self):
        """`git diff --name-only` emits repository-relative paths; everything downstream is
        project-relative. In a monorepo package every path carried an extra prefix, so nothing
        matched, `update()` found no work and reported success — and the graph froze at the
        last full build while continuing to answer confidently."""
        root = self.mk({"pkg/src/a.ts": "export const a = 1\n",
                        "pkg/src/b.ts": 'import { a } from "./a"\nexport const b = a\n'})
        proj = os.path.join(root, "pkg")
        for cmd in (["init", "-q"], ["add", "-A"],
                    ["-c", "user.email=t@t", "-c", "user.name=t", "commit", "-qm", "one"]):
            subprocess.run(["git", *cmd], cwd=root, capture_output=True)
        graph_ops.run_build(CodeGraph(proj), non_interactive=True)

        with open(os.path.join(proj, "src", "b.ts"), "w") as f:
            f.write('import { a } from "./a"\nexport const b = a\nexport const NEW = 2\n')
        for cmd in (["add", "-A"],
                    ["-c", "user.email=t@t", "-c", "user.name=t", "commit", "-qm", "two"]):
            subprocess.run(["git", *cmd], cwd=root, capture_output=True)
        graph_ops.run_update(CodeGraph(proj), non_interactive=True)

        with open(os.path.join(proj, "knowledge-base", ".graph", "graph.json")) as f:
            graph = json.load(f)
        self.assertIn("NEW", graph["files"]["src/b.ts"]["exports"])

    def test_the_built_in_exclusions_reach_every_backend(self):
        """OBLIGATION 6. The built-in name lists were applied only inside the floor's own
        `_should_exclude`, so a project running graphify graphed `vendor/`, `target/` and the
        toolkit's own `knowledge-base/` while the floor on the same repository did not. Two
        backends disagreeing about scope is exactly what ADR-018 exists to prevent."""
        proj = self.mk({"src/a.ts": "export const a = 1\n",
                        "vendor/v.ts": "export const v = 1\n",
                        "deep/nested/node_modules/pkg/m.ts": "export const m = 1\n",
                        "docs/site.ts": "export const d = 1\n"})
        excl = CodeGraph(proj).project_exclusions()
        self.assertFalse(excl.excludes("src/a.ts"))
        for out in ("vendor/v.ts", "deep/nested/node_modules/pkg/m.ts", "docs/site.ts"):
            with self.subTest(path=out):
                self.assertTrue(excl.excludes(out), out)

    def test_an_override_does_not_admit_the_vendored_tree_beneath_it(self):
        """`Exclusions._excluded_under_override` documents a measured 50,000-file blowup and
        the fix was applied to the contract's copy of the rule only. The floor's own
        `_should_exclude` still skipped the artifact check outright under a `user` override,
        at any depth. Asserts the two implementations agree, which is the property that was
        missing rather than either answer alone."""
        proj = self.mk({
            ".gitignore": "/node_modules\n",
            "packages/app/src/p.ts": "export const p = 1\n",
            "packages/app/node_modules/lodash/m.ts": "export const m = 1\n",
            "knowledge-base/.graph/classifications.json":
                '{"directories":{"packages":{"type":"source","source":"user"}}}',
        })
        g = CodeGraph(proj)
        gi = g._parse_gitignore()
        cl = g._load_classifications().get("directories") or {}
        excl = g.project_exclusions()
        for path, expected in (("packages/app/src/p.ts", False),
                               ("packages/app/node_modules/lodash/m.ts", True)):
            with self.subTest(path=path, excluded=expected):
                self.assertEqual(g._should_exclude(path, gi, cl), expected, path)
                self.assertEqual(excl.excludes(path), expected, path)

    def test_the_two_layers_agree_for_an_ai_verdict_too(self):
        """`project_exclusions` passes both `user` and `ai` verdicts as `overrides`, while the
        floor distinguishes them — `ai` overrules conventions only, `user` overrules
        everything. The tiers are therefore collapsed at the contract layer. It has no
        observable effect because artifact trees travel as patterns and
        `_excluded_under_override` re-matches patterns against the path below the override
        root, but the two implementations agreeing is the property, not the mechanism."""
        proj = self.mk({
            "pkgs/app/src/p.ts": "export const p = 1\n",
            "pkgs/app/node_modules/x/m.ts": "export const m = 1\n",
            "knowledge-base/.graph/classifications.json":
                '{"directories":{"pkgs":{"type":"source","source":"ai","confidence":0.9}}}',
        })
        g = CodeGraph(proj)
        gi = g._parse_gitignore()
        cl = g._load_classifications().get("directories") or {}
        excl = g.project_exclusions()
        for path, expected in (("pkgs/app/src/p.ts", False),
                               ("pkgs/app/node_modules/x/m.ts", True)):
            with self.subTest(path=path, excluded=expected):
                self.assertEqual(g._should_exclude(path, gi, cl), expected, path)
                self.assertEqual(excl.excludes(path), expected, path)


class TestSummaryFormatIsWhatIsDocumented(Base):
    """`--format summary` is what SKILL.md shows an agent, and it had drifted badly.

    The documented `update` block had three of four lines the code never emits; `dependents`
    and `dependencies` were documented with a filename header and a direct/transitive split
    that do not exist; every transitive entry carried a `(via …)` annotation nothing produces,
    because nothing records the traversal path; `build` said "Stored to" where the code says
    "Cached to". An agent pattern-matching on any of that finds nothing.
    """

    def cli(self, proj, *args):
        return subprocess.run([sys.executable, graph_ops.__file__, *args, "--dir", proj,
                               "--format", "summary"], capture_output=True, text=True).stdout

    def chain(self):
        return self.mk({
            "src/a.ts": "export const a = 1\n",
            "src/b.ts": 'import { a } from "./a"\nexport const b = a\n',
            "src/c.ts": 'import { b } from "./b"\nexport const c = b\n',
        })

    def test_no_surface_invents_a_via_annotation(self):
        """Nothing in the graph records how a transitive edge was reached."""
        proj = self.chain()
        self.cli(proj, "--build", "--non-interactive")
        for args in (("--impact", "src/a.ts"), ("--dependents", "src/a.ts"),
                     ("--dependencies", "src/c.ts")):
            with self.subTest(surface=args[0]):
                self.assertNotIn("(via", self.cli(proj, *args))

    def test_build_says_cached_to(self):
        out = self.cli(self.chain(), "--build", "--non-interactive")
        self.assertIn("- Cached to ", out)
        self.assertNotIn("Stored to", out)

    def test_the_bare_list_surfaces_are_flat_and_unheaded(self):
        proj = self.chain()
        self.cli(proj, "--build", "--non-interactive")
        out = self.cli(proj, "--dependents", "src/a.ts")
        self.assertTrue(out.startswith("Dependents:"), out)
        self.assertNotIn("Direct", out)
        self.assertNotIn("Transitive", out)

    def test_an_empty_answer_is_not_reported_as_a_missing_graph(self):
        """The empty-vs-unknown conflation the API layer was fixed to remove, still live in
        the one place a person reads it. A file that imports nothing is a real answer; a file
        the graph has never seen exits non-zero instead."""
        proj = self.chain()
        self.cli(proj, "--build", "--non-interactive")
        self.assertEqual(self.cli(proj, "--dependencies", "src/a.ts").strip(),
                         "This file imports nothing in the project.")
        self.assertEqual(self.cli(proj, "--dependents", "src/c.ts").strip(),
                         "Nothing depends on this file.")
        unknown = subprocess.run(
            [sys.executable, graph_ops.__file__, "--dependents", "nope.ts", "--dir", proj,
             "--format", "summary"], capture_output=True, text=True)
        self.assertNotEqual(unknown.returncode, 0)
        self.assertIn("File not found in graph", unknown.stderr)


class TestIncrementalObligation(Base):
    """Obligation 5, which was declared everywhere and enforced nowhere.

    `coverage().incremental` was written into every graph and read by no code. Both shipped
    backends declare `True`, so nothing had ever been in a position to notice — while the
    module docstring, the schema reference, the spec and the decision record all stated the
    enforcement as present fact.
    """

    class _Declines:
        """A conforming backend that cannot drop deleted nodes."""

        name = 'declines'

        def __init__(self, inner):
            self._inner = inner
            self.project_dir = inner.project_dir
            self.update_calls = 0
            self.build_calls = 0

        def coverage(self):
            c = self._inner.coverage()
            return substrate.Coverage(list(c.languages), list(c.extensions),
                                      list(c.relations), False)

        def build(self, **kw):
            self.build_calls += 1
            return self._inner.build(**kw)

        def update(self, **kw):
            self.update_calls += 1
            return self._inner.update(**kw)

    def test_a_backend_that_declines_incremental_gets_a_full_build(self):
        proj = self.mk({"src/a.ts": "export const a = 1\n",
                        "src/b.ts": 'import { a } from "./a"\nexport const b = a\n'})
        backend = self._Declines(CodeGraph(proj))
        graph_ops.run_build(backend, non_interactive=True)
        graph_ops.run_update(backend, non_interactive=True)
        self.assertEqual(backend.update_calls, 0, "update() must not be trusted")
        self.assertEqual(backend.build_calls, 2, "the contract rebuilds instead")

    def test_a_backend_that_supports_incremental_is_left_alone(self):
        proj = self.mk({"src/a.ts": "export const a = 1\n"})
        g = CodeGraph(proj)
        self.assertTrue(g.coverage().incremental)
        graph_ops.run_build(g, non_interactive=True)
        out = graph_ops.run_update(g, non_interactive=True)
        self.assertIn('status', out)


class TestUpdateWithoutACache(Base):
    """BEH-022 — the everyday first run: `--update` on a project that has never been built.

    `CodeGraph.update` returns `self.build(...)` outright on five conditions, and four of them
    are pinned by name (no commit, an unresolvable commit, a foreign backend, a stale schema).
    This one — no artifact at all — was reached only incidentally, by fixtures that happen to
    start with no cache and assert something else entirely.

    It is the one that runs most often. `--update` is the steady-state command wrap-up issues,
    so the first invocation on every new checkout takes this branch, and the fallback is
    invisible unless it is declared: `format_summary`'s update branch decides which block to
    print from `status`, so a fallback that reported `updated` would print "0 files changed"
    over a graph it had just built from nothing.
    """

    def setUp(self):
        # Sandboxed for the reason TestUnmappedSourceCLI spells out: `choose_backend` reads the
        # real ~/.freya/settings.json, and on a machine that answered the install question with
        # `graphify` this shells into a different backend's `update()` — whose no-cache branch
        # says something else, or nothing. Green here, red on any colleague's laptop.
        self.home = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.home, ignore_errors=True)

    def run_cli(self, *args):
        return subprocess.run([sys.executable, graph_ops.__file__, *args],
                              capture_output=True, text=True,
                              env=dict(os.environ, FREYA_HOME=self.home))

    def pair(self):
        return self.mk({"src/a.ts": "export const a = 1\n",
                        "src/b.ts": 'import { a } from "./a";\nexport const b = a;\n'})

    def test_a_first_update_falls_back_to_a_full_build(self):
        proj = self.pair()
        out = self.run_cli("--update", "--dir", proj, "--non-interactive", "--format", "json")
        self.assertEqual(out.returncode, 0, out.stderr)
        self.assertIn("No cached graph found. Running full build...", out.stderr)

        # The answer is a build summary, not an update one — no `files_changed` to read as
        # "nothing happened", and a `status` downstream can tell the two apart by.
        data = json.loads(out.stdout)
        self.assertEqual(data["status"], "built")
        self.assertEqual(data["files_scanned"], 2)
        self.assertNotIn("files_changed", data)

        # And a real build happened, rather than a message about one: both files are in the
        # artifact with the edge between them resolved.
        with open(os.path.join(proj, "knowledge-base", ".graph", "graph.json")) as f:
            graph = json.load(f)
        self.assertEqual(sorted(graph["files"]), ["src/a.ts", "src/b.ts"])
        self.assertEqual(ends(graph["files"]["src/b.ts"]["imports"]), ["src/a.ts"])

        # A second, fresh project for the human-readable half: after the run above this one
        # has a cache, and the branch under test only exists when there is none.
        summary = self.run_cli("--update", "--dir", self.pair(), "--non-interactive",
                               "--format", "summary").stdout
        self.assertTrue(summary.startswith("Built dependency graph:"), summary)
        self.assertNotIn("Updated dependency graph", summary)


class TestReadableBy(Base):
    """The remedy has to be nameable on a machine that has never installed the remedy.

    `select`'s existing hint is gated on `len(available_backends()) > 1`, so it recommends
    graphify only where graphify is already present — a discovery path that requires you to
    own the thing before being told you might want it. This works because a backend declares
    its coverage from a module-level constant rather than by asking the binary.
    """

    def test_it_fires_without_the_backend_on_path(self):
        import backends
        import shutil as sh
        original = sh.which
        sh.which = lambda *a, **k: None
        try:
            self.assertEqual(
                backends.readable_by({'.java': 12},
                                     ['.ts', '.tsx', '.js', '.jsx', '.py', '.go']),
                {'graphify': 12})
        finally:
            sh.which = original

    def test_it_drops_over_claimed_extensions(self):
        """graphify's `.json` selection is name-based — `package.json` produces nodes, an
        arbitrary `x.json` does not. Counting it would fire the recommendation on every
        repository in existence."""
        import backends
        self.assertEqual(
            backends.readable_by({'.json': 40},
                                 ['.ts', '.tsx', '.js', '.jsx', '.py', '.go']),
            {})


class TestUnmappedSourceCLI(Base):
    """The first tests of `main()` and `format_summary` in this repository.

    Verified by grep before writing them: `format_summary` appeared only at its definition,
    one recursive call, one call site and one comment, and no test invoked `main()` at all.
    The entire CLI presentation layer — the surface every agent actually reads — was unguarded
    in a suite of well over a thousand tests.
    """

    def setUp(self):
        # Sandbox the machine-level backend default. Without this, `_seed_from_machine_default`
        # and `choose_backend` read the real ~/.freya/settings.json: a machine that answered
        # the install question with `graphify` builds every fixture with a backend that reads
        # .java, the census correctly reports nothing, and six assertions about 12 unmapped
        # files fail. Green here, red on any colleague's laptop — the same defect this suite
        # shipped once before, which is why conftest.py's docstring calls itself "a safety net,
        # not the mechanism".
        self.home = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.home, ignore_errors=True)

    def run_cli(self, *args):
        return subprocess.run([sys.executable, graph_ops.__file__, *args],
                              capture_output=True, text=True,
                              env=dict(os.environ, FREYA_HOME=self.home))

    def mixed(self):
        files = {"web/src/a.ts": "export const a = 1\n",
                 "web/src/b.ts": 'import { a } from "./a";\nexport const b = a;\n'}
        files.update({"src/main/java/com/acme/C%d.java" % i: "class C%d {}\n" % i
                      for i in range(12)})
        return self.mk(files)

    def clean(self):
        return self.mk({"src/a.ts": "export const a = 1\n",
                        "src/b.ts": 'import { a } from "./a";\nexport const b = a;\n',
                        "README.md": "# x\n", "package.json": '{"name":"x"}\n'})

    def test_a_build_names_what_it_could_not_read(self):
        """The headline case: `files_scanned: 3` stops reading as a denominator the moment
        `unmapped_source.files: 12` sits in the same object."""
        out = self.run_cli("--build", "--dir", self.mixed(), "--non-interactive")
        self.assertEqual(out.returncode, 0, out.stderr)
        block = json.loads(out.stdout)["unmapped_source"]
        self.assertEqual(block["files"], 12)
        self.assertEqual(block["extensions"], {".java": 12})
        self.assertEqual(block["directories"], {"src/main/java/com/acme": 12})

    def test_a_clean_repo_pays_nothing_at_all(self):
        """THE ADR-019 GUARANTEE. Asserted as an exact key set, not as an absence: a field that
        fires on every repository with a README is one an agent learns to skip, after which it
        costs tokens forever and changes no decision."""
        out = self.run_cli("--build", "--dir", self.clean(), "--non-interactive")
        self.assertEqual(out.returncode, 0, out.stderr)
        self.assertEqual(set(json.loads(out.stdout)),
                         {"files_scanned", "total_imports", "total_exports",
                          "commit", "cached_to", "status"})

    def test_the_clean_sentinel_reaches_the_artifact(self):
        """`files: 0` in the gitignored artifact is what lets project_shape tell "censused and
        clean" from "this graph predates the census" — with no schema bump."""
        proj = self.clean()
        self.run_cli("--build", "--dir", proj, "--non-interactive")
        with open(os.path.join(proj, "knowledge-base", ".graph", "graph.json")) as f:
            block = json.load(f)["substrate"]["unmapped_source"]
        self.assertEqual(block["files"], 0)

    def test_impact_with_no_graph_is_still_exactly_empty(self):
        """DRIFT'S LOAD-BEARING CONTRACT. `drift.py` uses the *presence* of `all_affected` as
        its "the graph actually ran" signal, so an extra key in this branch would flip every
        drift run to `changed-only` at exit 0 with nothing going red. Previously unguarded."""
        out = self.run_cli("--impact", "foo.ts", "--dir", self.mk({}), "--format", "json")
        self.assertEqual(out.returncode, 0, out.stderr)
        self.assertEqual(json.loads(out.stdout), {})

    def test_impact_carries_the_digest_and_keeps_every_original_key(self):
        proj = self.mixed()
        self.run_cli("--build", "--dir", proj, "--non-interactive")
        out = self.run_cli("--impact", "web/src/a.ts", "--dir", proj, "--format", "json")
        data = json.loads(out.stdout)
        self.assertEqual(set(data), {"input_files", "direct_dependents",
                                     "transitive_dependents", "all_affected",
                                     "not_in_graph", "unmapped_source"})
        self.assertEqual(set(data["unmapped_source"]), {"files", "extensions", "directories"})

    def test_query_keeps_its_edge_objects(self):
        """ADR-021's edges-vs-paths distinction is untouched by the caveat."""
        proj = self.mixed()
        self.run_cli("--build", "--dir", proj, "--non-interactive")
        data = json.loads(self.run_cli("--query", "web/src/a.ts", "--dir", proj,
                                       "--format", "json").stdout)
        self.assertEqual(set(data) - {"unmapped_source"},
                         {"file", "exports", "imports", "dependents", "language"})
        self.assertTrue(all(isinstance(e, dict) for e in data["dependents"]))

    def test_dependencies_stays_a_bare_array_and_says_so_on_stderr(self):
        """THE SHAPE PIN. `run_behaviors` validates this with `isinstance(data, list)` and
        falls to `graph-query-failed` otherwise — which routes every confirmed and every
        integration behaviour to `coverage: unknown`, freezing the committed behavior.json and
        taking wrap-up's gate green over zero behaviours. Breaking closed here is a repo-wide
        silent pass. Both halves in one test, because the strategy needs both to be true."""
        proj = self.mixed()
        self.run_cli("--build", "--dir", proj, "--non-interactive")
        out = self.run_cli("--dependencies", "web/src/b.ts", "--dir", proj, "--format", "json")
        self.assertEqual(out.returncode, 0, out.stderr)
        data = json.loads(out.stdout)
        self.assertIsInstance(data, list)
        self.assertTrue(all(isinstance(x, str) for x in data))
        self.assertIn("excludes 12 source file(s)", out.stderr)

    def test_dependents_stays_a_bare_array_and_says_so_on_stderr(self):
        proj = self.mixed()
        self.run_cli("--build", "--dir", proj, "--non-interactive")
        out = self.run_cli("--dependents", "web/src/a.ts", "--dir", proj, "--format", "json")
        self.assertEqual(out.returncode, 0, out.stderr)
        self.assertIsInstance(json.loads(out.stdout), list)
        self.assertIn("excludes 12 source file(s)", out.stderr)

    def test_an_up_to_date_update_carries_the_census_without_re_walking(self):
        proj = self.mixed()
        # A real commit, because `update()` falls back to a full build without one — and a
        # full build would re-walk, which is exactly what this test claims does not happen.
        for cmd in (["init", "-q"], ["add", "-A"],
                    ["-c", "user.email=t@t", "-c", "user.name=t", "commit", "-qm", "x"]):
            subprocess.run(["git", *cmd], cwd=proj, capture_output=True)
        self.run_cli("--build", "--dir", proj, "--non-interactive")
        artifact = os.path.join(proj, "knowledge-base", ".graph", "graph.json")
        before = os.path.getmtime(artifact)
        out = self.run_cli("--update", "--dir", proj, "--non-interactive", "--format", "json")
        data = json.loads(out.stdout)
        self.assertEqual(data["status"], "up_to_date")
        self.assertEqual(data["unmapped_source"]["files"], 12)
        self.assertEqual(os.path.getmtime(artifact), before)

    def test_the_caller_s_exclusions_reach_the_census_through_the_runner(self):
        """THE SEAM. `_finalise` gained an `exclusions` parameter and run_build/run_update pass
        `kwargs.get('exclusions')`. Replacing either with None — the shape a typo like
        `kwargs.get('exclusion')` produces — left all 1,409 tests green while the production
        answer changed. Obligation 6 was asserted at the unit and not at the wiring."""
        files = {"src/a.ts": "export const a = 1\n", "thirdparty/B.java": "class B {}\n"}
        proj = self.mk(files)
        g = CodeGraph(proj)
        out = graph_ops.run_build(
            g, exclusions=substrate.Exclusions(directories=["thirdparty"]),
            non_interactive=True)
        self.assertNotIn("unmapped_source", out)

        out2 = graph_ops.run_build(CodeGraph(self.mk(files)), non_interactive=True)
        self.assertEqual(out2["unmapped_source"]["extensions"], {".java": 1})

    def test_the_count_is_not_truncated_by_the_extension_cap(self):
        """`files` was summed from the CAPPED dict, so 22 unread files across 11 extensions
        were reported as 16 and three languages were named nowhere — the caveat itself giving
        a plausible-looking wrong number, in prose, flatly."""
        files = {"app/a.ts": "export const a = 1\n"}
        for e in ("java", "kt", "rb", "php", "rs", "swift", "dart", "hs", "ml", "elm", "sol"):
            files["lang_%s/f1.%s" % (e, e)] = "x\n"
            files["lang_%s/f2.%s" % (e, e)] = "x\n"
        out = self.run_cli("--build", "--dir", self.mk(files), "--non-interactive")
        block = json.loads(out.stdout)["unmapped_source"]
        self.assertEqual(block["files"], 22)
        self.assertEqual(len(block["extensions"]), 8)
        self.assertEqual(block["extensions_omitted"], 3)
        self.assertIn("22 source file(s)", block["advice"])

    def test_the_digest_carries_its_own_truncation_markers(self):
        """Dropping them presented a partial search target as a complete one, on the surfaces
        an agent acts from: "grep these five directories" when there were nine."""
        files = {"app/a.ts": "export const a = 1\n"}
        for i in range(8):
            files["root%d/C.java" % i] = "class C {}\n"
        proj = self.mk(files)
        self.run_cli("--build", "--dir", proj, "--non-interactive")
        data = json.loads(self.run_cli("--impact", "app/a.ts", "--dir", proj,
                                       "--format", "json").stdout)
        self.assertEqual(data["unmapped_source"]["directories_omitted"], 3)

    def test_a_corrupt_substrate_block_does_not_take_the_answer_down(self):
        """`or {}` rescues only a falsy value, so a truthy non-dict reached `.get` and raised —
        turning four working answers into exit 1. `_finalise` guards the write path against
        exactly this shape, twice, and the new read paths did not."""
        proj = self.mixed()
        self.run_cli("--build", "--dir", proj, "--non-interactive")
        path = os.path.join(proj, "knowledge-base", ".graph", "graph.json")
        with open(path) as f:
            graph = json.load(f)
        graph["substrate"] = "whatever"
        with open(path, "w") as f:
            json.dump(graph, f)
        out = self.run_cli("--dependencies", "web/src/b.ts", "--dir", proj, "--format", "json")
        self.assertEqual(out.returncode, 0, out.stderr)
        self.assertIsInstance(json.loads(out.stdout), list)

    def test_impact_does_not_emit_the_bare_array_caveat(self):
        """`get_impact` calls `get_dependents` internally. The stderr line names
        `--dependents/--dependencies`, so an `--impact` run pointed the reader at commands they
        had not run — and contradicted a payload that was already qualified correctly."""
        proj = self.mixed()
        self.run_cli("--build", "--dir", proj, "--non-interactive")
        out = self.run_cli("--impact", "web/src/a.ts", "--dir", proj, "--format", "json")
        self.assertIn("unmapped_source", json.loads(out.stdout))
        self.assertNotIn("--dependents/--dependencies", out.stderr)

    class _Explodes:
        """A backend that passes selection and then throws at build time.

        The scenario `_run_or_degrade` exists for — the wrapped tool was upgraded, timed out,
        or exited 0 having written nothing — and the only way to reach the degraded census
        without installing a backend and then breaking it.
        """

        name = 'graphify'

        def __init__(self, project_dir):
            self.project_dir = project_dir

        def build(self, **kwargs):
            raise RuntimeError('binary vanished mid-build')

        def update(self, **kwargs):
            raise RuntimeError('binary vanished mid-build')

    def test_a_degraded_build_does_not_recommend_the_backend_it_lost(self):
        """BEH-045. `backends.readable_by` is deliberately availability-blind — it answers "is
        there a remedy at all?", which is exactly right on a machine that never installed one —
        so nothing in it notices that this run has just *proved* graphify unusable. The
        suppression lives in `_census` alone, and no test constructed a degraded build. A
        regression prints "--use graphify" directly beneath "'graphify' failed during the
        build", at exit 0, on the surface an agent acts from.

        Both directions, because the fixture is what makes the assertion mean anything: on the
        same twelve unread .java files an ordinary floor build *does* name the remedy.
        """
        control = graph_ops.run_build(CodeGraph(self.mixed()), non_interactive=True)
        self.assertEqual(control["unmapped_source"]["readable_by"], {"graphify": 12})
        self.assertIn("--use graphify", control["unmapped_source"]["advice"])

        proj = self.mixed()
        degraded = graph_ops._run_or_degrade(
            graph_ops.run_build, self._Explodes(proj), CodeGraph(proj),
            True, None, None)

        # The census still reports the gap — the caveat is not what gets suppressed.
        block = degraded["unmapped_source"]
        self.assertEqual(block["files"], 12)
        self.assertEqual(block["directories"], {"src/main/java/com/acme": 12})
        # Only the remedy is, in both the structured field and the prose that quotes it.
        self.assertNotIn("readable_by", block)
        self.assertNotIn("graphify", block["advice"])

        # And this really was the degraded path, not a build that quietly succeeded on the
        # floor: without this the suppression could be asserted over a run that never fell back.
        with open(os.path.join(proj, "knowledge-base", ".graph", "graph.json")) as f:
            self.assertEqual(json.load(f)["substrate"]["degraded_from"], "graphify")

    def test_the_summary_format_gains_a_line_only_when_there_is_one(self):
        """FIRST TEST OF format_summary. Both directions: the new line appears, and a clean
        repo's four lines are byte-identical to what they were before the census existed."""
        dirty = self.run_cli("--build", "--dir", self.mixed(), "--non-interactive",
                             "--format", "summary").stdout
        self.assertIn("NOT GRAPHED: 12 source file(s)", dirty)
        self.assertIn("src/main/java/com/acme", dirty)
        clean = self.run_cli("--build", "--dir", self.clean(), "--non-interactive",
                             "--format", "summary").stdout
        self.assertNotIn("NOT GRAPHED", clean)
        body = clean.strip().splitlines()
        self.assertEqual(body[0], "Built dependency graph:")
        self.assertEqual([ln.strip().split(" ")[0] for ln in body[1:]], ["-"] * 4)
        self.assertTrue(body[-1].strip().startswith("- Cached to"))


class TestTheResolverCannotEscapeTheProject(Base):
    """A `..` in an alias target or a workspace subpath resolved out of the tree (SEC-014).

    `Path.relative_to` compares *parts*, so `/proj/../outside/secret.ts` relative to `/proj`
    succeeded and handed back `../outside/secret.ts` — which `normalize_key` cannot collapse
    and which then entered the graph as an internal edge target, indistinguishable from a
    file the project owns. `CodeGraph._contain` is the one gate now.

    Every escape row below is paired with an honest row, because a resolver that resolves
    nothing passes every escape assertion in this class.
    """

    def alias_project(self):
        """A project whose tsconfig maps one alias out of the tree and one inside it.

        The project is a *subdirectory* of the temp dir so that `outside/` is a real sibling
        of the project root and nothing is written above the directory this test cleans up.
        """
        root = self.mk({
            "proj/tsconfig.json": ('{"compilerOptions":{"baseUrl":".","paths":'
                                   '{"@evil/*":["../outside/*"],"@ok/*":["./lib/*"]}}}'),
            "proj/src/a.ts": "import { s } from '@evil/secret'\nexport const a = 1\n",
            "proj/lib/util.ts": "export const u = 1\n",
            "outside/secret.ts": "export const s = 1\n",
        })
        return os.path.join(root, "proj")

    def workspace_project(self):
        """A monorepo whose package name is used as a launchpad for `../../../`."""
        root = self.mk({
            "proj/package.json": '{"name":"root","workspaces":["packages/*"]}',
            "proj/packages/domain/package.json": ('{"name":"@acme/domain",'
                                                  '"main":"src/index.ts"}'),
            "proj/packages/domain/src/index.ts": "export const d = 1\n",
            "proj/app/a.ts": "import { c } from '@acme/domain/../../../outside/creds'\n",
            "outside/creds.ts": "export const c = 1\n",
        })
        return os.path.join(root, "proj")

    def test_a_tsconfig_paths_target_with_dotdot_does_not_resolve(self):
        """Measured before the fix: this returned `../outside/secret.ts`."""
        proj = self.alias_project()
        g = CodeGraph(proj)
        self.assertEqual(g._classify_import("@evil/secret", "src/a.ts"),
                         "unresolved:@evil/secret")
        graph_ops.run_build(g)
        for target in ends(g.query("src/a.ts")["imports"]):
            self.assertFalse(target.startswith("..") or "/../" in target, target)

    def test_a_workspace_subpath_that_walks_out_does_not_resolve(self):
        """A different construction from the alias site — `root / subpath` rather than a
        configured target — and it went out of the tree the same way."""
        proj = self.workspace_project()
        g = CodeGraph(proj)
        self.assertEqual(
            g._classify_import("@acme/domain/../../../outside/creds", "app/a.ts"),
            "unresolved:@acme/domain/../../../outside/creds")

    def test_honest_imports_still_resolve(self):
        """The anti-vacuity control. With `_contain` returning None unconditionally these
        three go red while both escape rows above stay green."""
        alias = CodeGraph(self.alias_project())
        workspace = CodeGraph(self.workspace_project())
        for label, graph, spec, from_file, expected in (
                ("relative", alias, "../lib/util", "src/a.ts", "lib/util.ts"),
                ("alias", alias, "@ok/util", "src/a.ts", "lib/util.ts"),
                ("workspace", workspace, "@acme/domain", "app/a.ts",
                 "packages/domain/src/index.ts")):
            with self.subTest(kind=label):
                self.assertEqual(graph._classify_import(spec, from_file), expected)

    def test_a_symlinked_in_project_directory_keeps_its_spelled_key(self):
        """Why the gate normalises and deliberately does not resolve.

        `graph.json`, `behavior.json` and the docs graph are joined on this key by set
        intersection (ADR-025). Resolving `proj/alias/util.ts` to `proj/real/util.ts` would
        not key the file *wrongly* — it would key it under a string the other two artifacts
        never carry, so it would stop joining at all and a blast radius would come back
        quietly short with nothing to read. Measured: with `_contain` switched to
        `candidate.resolve()` the key below becomes `real/util.ts`, and no other test in the
        suite notices.

        Through an *alias*, not a relative import, and the difference is a finding in itself:
        `_resolve_import_path` already calls `.resolve()` on a relative candidate before this
        gate ever sees it (`graph_ops.py:1031`), so a relative import through a symlink is
        re-keyed upstream today and this gate cannot be what fixes that. The alias, workspace
        and Python sites hand the candidate over unresolved, so they are where the choice is
        observable.
        """
        proj = self.mk({
            "tsconfig.json": '{"compilerOptions":{"baseUrl":".","paths":{"@s/*":["./alias/*"]}}}',
            "real/util.ts": "export const u = 1\n",
            "src/a.ts": "import { u } from '@s/util'\n",
        })
        try:
            os.symlink(os.path.join(proj, "real"), os.path.join(proj, "alias"),
                       target_is_directory=True)
        except (OSError, NotImplementedError, AttributeError) as exc:
            # Windows makes symlinks only for a privileged process or with Developer Mode on.
            self.skipTest("this host will not create symlinks: %s" % exc)
        self.assertEqual(CodeGraph(proj)._classify_import("@s/util", "src/a.ts"),
                         "alias/util.ts")

    def test_the_gate_hands_its_candidate_over_as_spelled_on_every_host(self):
        """The same choice as the row above, pinned without asking the host for a symlink.

        That row is the only test in the suite that notices `_contain` switching to
        `containment.rel_within(self.project_dir, candidate.resolve())`, and its body is
        wrapped in a `skipTest` for hosts that will not create a symlink — Windows without
        Developer Mode, which is half the CI matrix. So the most subtle decision in this gate
        was asserted on one leg of the matrix and nowhere else, and a `.resolve()` added back
        by someone tidying up would go green on the other leg.

        A divergence between how a path is spelled and what it resolves to cannot be built
        on a real filesystem without a symlink, so it is supplied rather than created: a
        candidate that spells one in-project file and resolves to another. `os.fspath` is the
        only thing this gate is entitled to ask a candidate — `rel_within` calls
        `os.path.abspath`, which is exactly that — so a double that answers both questions
        differently separates the two implementations on any host.

        This does not replace the row above and is not offered as an equivalent: the symlink
        row proves a real symlinked directory behaves this way, and this row proves the gate
        keeps making the choice where no symlink can be made to prove it.
        """
        proj = self.mk({"real/util.ts": "export const u = 1\n"})

        class SpelledCandidate:
            """A stand-in for the symlink. Deliberately not a `Path` subclass: subclassing
            `pathlib.Path` needs private `_flavour` plumbing below 3.12, and the point is to
            expose exactly the two questions the gate may ask."""

            def __init__(self, spelled, resolved):
                self._spelled, self._resolved = spelled, resolved

            def __fspath__(self):
                return self._spelled

            def resolve(self, strict=False):
                return Path(self._resolved)

        # Off `g.project_dir` and not off `proj`: the constructor resolves the root, and on
        # macOS a temp dir is reached through the `/var` -> `/private/var` symlink, so a
        # candidate spelled from `proj` is under a different string and the gate answers None
        # for a reason that has nothing to do with what this row is asking.
        g = CodeGraph(proj)
        candidate = SpelledCandidate(str(g.project_dir / "alias" / "util.ts"),
                                     str(g.project_dir / "real" / "util.ts"))
        self.assertEqual(normalize_key(g._contain(candidate)), "alias/util.ts")

    def test_the_python_resolver_asks_the_same_gate(self):
        """Defence in depth, and labelled as such rather than sold as a fix.

        No `..` reaches this site through the public API today: `_python_search_bases` builds
        every base with `Path.parent`, which truncates rather than appends, and a dotted
        import cannot contain a `..` segment. The site is here so that the two cannot drift —
        which is the whole reason `_contain` is a method and not two inlined calls.
        """
        root = self.mk({"proj/pkg/__init__.py": "", "outside/creds.py": "X = 1\n"})
        g = CodeGraph(os.path.join(root, "proj"))
        # `g.project_dir` rather than the string this test built: `CodeGraph.__init__`
        # resolves the root, and on macOS a temp dir arrives through a symlinked `/var`, so a
        # hand-built candidate would be outside the root for a reason that has nothing to do
        # with what is being measured.
        self.assertIsNone(g._resolve_python_module(g.project_dir / ".." / "outside",
                                                   ["creds"]))
        self.assertEqual(g._resolve_python_module(g.project_dir, ["pkg"]), "pkg/__init__.py")


class TestTheCachedCommitIsNotAGitArgument(Base):
    """`graph.json` is input, not fact, and its `commit` was pasted into a git revision.

    The cache is gitignored *here*, so the reflex is "nobody can reach it". Nothing stops
    another repository committing one, and `--update` is the first thing wrap-up runs after
    a checkout. A `commit` of `--output=<path>` turned the revision slot into a git option:
    `git diff --output=<path>..HEAD --name-only ...` wrote git's own output over that path
    and printed nothing, so `_get_changed_files` returned `[]`, `update()` read `[]` as
    "nothing changed", and the graph reported itself up to date for as long as the poisoned
    cache survived. A truncated file and a frozen graph, and the run exited 0.

    Two controls, tested apart because together they hide each other:

      - the hash check in `update()`, which means the string never reaches argv. This is the
        one that does not depend on the git version.
      - `--end-of-options` in the argv, which holds if the check is ever loosened. Its
        position is the whole trick: git refuses `--name-only` *after* a non-option
        argument, so the separator goes last, after the options and before the revision.
        Put it first — the obvious reading — and every `--update` on every machine returns
        rc=128, `_get_changed_files` answers None forever, and the incremental path silently
        becomes a full rebuild. That failure is invisible; it just costs minutes.
    """

    def _poisoned(self, commit):
        """A real repository whose cached graph carries `commit`, and nothing else."""
        proj = self.mk({"src/a.ts": "export const a = 1\n"})
        _git_repo(proj)
        gdir = Path(proj) / "knowledge-base" / ".graph"
        gdir.mkdir(parents=True, exist_ok=True)
        (gdir / "graph.json").write_text(json.dumps({
            "version": substrate.GRAPH_SCHEMA_VERSION, "commit": commit, "files": {},
        }), encoding="utf-8")
        return proj, gdir

    def test_a_cached_commit_that_is_not_a_hash_rebuilds_instead_of_freezing(self):
        """End to end, with the payload the finding names: no write outside the graph, and
        the answer is a real rebuild rather than "up to date"."""
        # Its own empty directory, and asserted empty rather than globbed for a name. Aimed
        # at the shared temp root instead, this passes or fails on debris another test left
        # behind — which it did, once, and read as a fix.
        target = Path(self.mk({}))
        proj, gdir = self._poisoned("--output=" + str(target / "pwn"))

        out = graph_ops.run_update(CodeGraph(proj), non_interactive=True)

        self.assertEqual(out["status"], substrate.Result.BUILT)
        self.assertIn("src/a.ts", json.loads((gdir / "graph.json").read_text())["files"])
        self.assertEqual(sorted(p.name for p in target.iterdir()), [],
                         "git wrote outside the project on the strength of a cached string")

    def test_a_cached_commit_that_is_not_a_hash_is_never_handed_to_git(self):
        """The half the separator would otherwise cover for. Both controls turn a poisoned
        cache into a rebuild, so "it rebuilt" cannot tell them apart — this asks the narrower
        question the hash check exists to answer: git is never asked at all."""
        asked = []

        class Recording(CodeGraph):
            def _get_changed_files(self, since_commit):
                asked.append(since_commit)
                return super()._get_changed_files(since_commit)

        proj, _ = self._poisoned("--output=" + str(Path(self.mk({})) / "pwn"))
        self.assertEqual(graph_ops.run_update(Recording(proj), non_interactive=True)["status"],
                         substrate.Result.BUILT)
        self.assertEqual(asked, [])

        proj, _ = self._poisoned("0" * 40)   # hex, so this one is allowed through to git
        graph_ops.run_update(Recording(proj), non_interactive=True)
        self.assertEqual(asked, ["0" * 40])

    def test_the_diff_argv_puts_its_options_before_the_revision(self):
        """`_get_changed_files` directly, with the hash check out of the picture.

        The second assertion is the reason this test exists. Ordering the argv the obvious
        way — separator first — passes the first assertion and fails this one, because git
        answers `option '--name-only' must come before non-option arguments`, rc=128, for
        every ordinary revision as well as the hostile one.
        """
        root = self.mk({"pkg/src/a.ts": "export const a = 1\n",
                        "pkg/src/b.ts": 'import { a } from "./a"\nexport const b = a\n'})
        proj = os.path.join(root, "pkg")
        env = dict(os.environ, GIT_AUTHOR_NAME="t", GIT_AUTHOR_EMAIL="t@e",
                   GIT_COMMITTER_NAME="t", GIT_COMMITTER_EMAIL="t@e")
        for argv in (["git", "init", "-q"], ["git", "add", "-A"],
                     ["git", "commit", "-qm", "one"]):
            subprocess.run(argv, cwd=root, env=env, capture_output=True, check=True)
        base = subprocess.run(["git", "rev-parse", "HEAD"], cwd=root, env=env,
                              capture_output=True, text=True, check=True).stdout.strip()
        with open(os.path.join(proj, "src", "b.ts"), "w", encoding="utf-8") as f:
            f.write('import { a } from "./a"\nexport const b = a\nexport const NEW = 2\n')
        for argv in (["git", "add", "-A"], ["git", "commit", "-qm", "two"]):
            subprocess.run(argv, cwd=root, env=env, capture_output=True, check=True)

        g = CodeGraph(proj)
        target = Path(self.mk({}))
        self.assertIsNone(g._get_changed_files("--output=" + str(target / "pwn")))
        self.assertEqual(sorted(p.name for p in target.iterdir()), [])
        # Project-relative, from a project one directory below the repository root: the
        # separator must not cost `--relative` its effect.
        self.assertEqual(g._get_changed_files(base), ["src/b.ts"])


class TestCrossingTheRootIsADeclaredAct(Base):
    """Nothing outside the project root is reached unless the project declared it (ADR-031).

    Two halves, and both have to hold or the feature is either useless or SEC-008 with a
    declaration written on it. Inside the root discovery stays automatic. Crossing the root is
    never implicit — and when it does happen, the answer says so.

    The fixture is the motivating shape: a checkout beside the package it imports, which is
    what an Expo app in one repository importing a design system from another looks like.
    `proj/` is a subdirectory of the temp dir so `packages/` is a genuine sibling and nothing
    is written above the tree this class cleans up.
    """

    SECRET = "SECRET_FROM_OUTSIDE"

    def sibling_project(self, declaration=None):
        root = self.mk({
            "proj/src/a.ts": "import { B } from '../../packages/ui/src/Button'\n"
                             "export const a = 1\n",
            "proj/src/b.ts": "import { a } from './a'\nexport const b = 1\n",
            "packages/ui/src/Button.tsx": "export const B = 1\n"
                                          "export const %s = 'leaked'\n" % self.SECRET,
            # Never referenced by anything in the project. A declaration must not make this
            # reachable: the grant is resolution of a reference in-project code wrote, never a
            # licence to walk the tree the reference landed in.
            "packages/ui/unreferenced/keys.ts": "export const %s = 'walked'\n" % self.SECRET,
        })
        proj = os.path.join(root, "proj")
        os.makedirs(os.path.join(proj, "knowledge-base"), exist_ok=True)
        if declaration is not None:
            with open(os.path.join(proj, "knowledge-base", "settings.json"), "w",
                      encoding="utf-8") as handle:
                json.dump({"outside": declaration}, handle)
        return root, proj

    def built(self, declaration=None):
        root, proj = self.sibling_project(declaration)
        g = CodeGraph(proj)
        graph_ops.run_build(g, non_interactive=True, exclusions=g.project_exclusions())
        return root, proj, g

    # -- the default is refusal ------------------------------------------------------------

    def test_an_undeclared_sibling_stays_unresolved(self):
        """Zero-config behaviour is unchanged, and declaration is the whole opt-in.

        This is the row that says the feature is not on by default. Without it, an
        implementation that resolved every sibling would pass everything below.
        """
        _, _, g = self.built()
        self.assertEqual(ends(g.graph["files"]["src/a.ts"]["imports"]),
                         ["unresolved:../../packages/ui/src/Button"])
        self.assertNotIn("outside_roots", g.graph["substrate"])

    def test_an_undeclared_project_enumerates_nothing_outside_its_own_root(self):
        """Containment runs before the `is_file()` and before the `listdir`, and this proves it.

        *Enumerates*, and the name says so rather than saying "touches", because the stronger
        claim is false and was asserted here for a while: `_resolve_import_path` builds a
        relative candidate with `(from_dir / import_path).resolve()`, which `lstat`s every
        component of a `../..` specifier before `_contain` is consulted at all, declared or
        not. That realpath is pre-existing, it is the one ADR-031's Rationale prices, and this
        row cannot see it — `_dir_listing_cache` is populated only by `_is_real_file`, so it is
        the record of every directory this build *enumerated*, which is the bound that is
        actually held.

        Move the `_contain` call after `self._is_real_file(candidate)` in `_resolve_fs` and the
        edge classification does not change at all — it is still `unresolved:` — but the
        sibling directory appears in this cache. That is the mutation this row exists for:
        without it, a version of the fix that looks correct still leaves an existence oracle
        over paths outside the project.
        """
        _, proj, g = self.built()
        for parent in g._dir_listing_cache:
            with self.subTest(listed=str(parent)):
                self.assertIsNotNone(containment.rel_within(g.project_dir, parent),
                                     "%s is outside %s" % (parent, g.project_dir))

    # -- a declaration buys resolution, and only resolution --------------------------------

    def test_a_declared_root_resolves_to_a_signal_and_never_to_a_node(self):
        """The crossing is an edge target, not a file.

        Two independent mutations, each of which must turn this red on its own. Remove
        `'outside:'` from `substrate.IMPORT_SIGNALS` and `is_internal` becomes true for the
        target, so `validate_graph` reports an edge naming no file in the graph. Have
        `OutsideRoots.key_for` return the raw relative path and the first assertion sees
        `../packages/ui/src/Button.tsx`.
        """
        _, _, g = self.built({"ui": "../packages/ui"})
        self.assertEqual(ends(g.graph["files"]["src/a.ts"]["imports"]),
                         ["outside:ui/src/Button.tsx"])
        self.assertNotIn("outside:ui/src/Button.tsx", g.graph["files"])
        self.assertEqual(sorted(g.graph["files"]), ["src/a.ts", "src/b.ts"])
        self.assertEqual(substrate.validate_graph(g.graph, g.coverage()), [])
        for path, info in g.graph["files"].items():
            with self.subTest(node=path):
                self.assertNotIn("outside:ui/src/Button.tsx",
                                 ends(info.get("dependents") or []))

    def test_the_declared_root_is_resolved_into_and_never_walked(self):
        """The line between this feature and SEC-008 with a declaration written on it.

        `unreferenced/keys.ts` sits under the declared root and nothing in the project references
        it. If any part of this globbed, walked or scanned the declared tree it would be in
        the artifact. And `Button.tsx` — which *is* referenced — contributes an edge target and
        nothing else: its exports are not read, because reading them means opening a file
        outside the project, which no declaration buys.

        The secret string is planted in both files and asserted absent from the whole artifact,
        because that is the blunt version of the claim and it does not depend on knowing which
        key content would have arrived under.
        """
        _, proj, g = self.built({"ui": "../packages/ui"})
        artifact = json.dumps(g.graph)
        self.assertNotIn(self.SECRET, artifact)
        self.assertNotIn("unreferenced", artifact)
        listed = {os.path.basename(str(p)) for p in g._dir_listing_cache}
        self.assertNotIn("unreferenced", listed)
        self.assertNotIn("ui", listed)

    def test_an_untaught_consumer_cannot_open_any_edge_target(self):
        """Fail-closed, asserted over the artifact rather than over one token.

        Every consumer that has not been taught about declarations does the same thing with a
        target: joins it onto the project root and looks. So the property is not "the token is
        tidy", it is that no edge target in a built graph can be turned into a file outside the
        project by that join. Emitting `../packages/ui/src/Button.tsx` instead — the obvious
        alternative design — turns this red, and would have handed every untaught consumer in
        the tree a working path out of the repository.
        """
        _, proj, g = self.built({"ui": "../packages/ui"})
        crossings = 0
        for info in g.graph["files"].values():
            for target in ends(info["imports"]):
                with self.subTest(target=target):
                    landed = os.path.realpath(os.path.join(str(g.project_dir), target))
                    self.assertTrue(
                        containment.within(str(g.project_dir), landed)
                        or not os.path.exists(landed),
                        "%r joined onto the project root opens %s" % (target, landed))
                    if not target.startswith(substrate.OUTSIDE_PREFIX):
                        continue
                    crossings += 1
                    # Stronger than "names nothing", and only claimed of a crossing: the
                    # token carries no `..`, no drive and no root in either flavour, so the
                    # join above cannot leave the root whatever the filesystem looks like.
                    # An `unresolved:` tail is whatever the source wrote and may well hold
                    # `..`, which is why this half is not asserted of every target.
                    self.assertFalse(containment.escapes(target))
        self.assertEqual(crossings, 1, "the fixture stopped crossing; this row proves nothing")

    def test_the_python_resolver_crosses_by_the_same_gate(self):
        """One gate, two languages. `_contain` is a method for exactly this reason: inlined at
        both sites, the TypeScript and Python resolvers would eventually disagree about what
        this project is allowed to reach."""
        root = self.mk({
            "proj/knowledge-base/settings.json": '{"outside": {"sdk": "../sdk"}}',
            "proj/app.py": "import client\n",
            "sdk/client.py": "X = 1\n",
        })
        g = CodeGraph(os.path.join(root, "proj"))
        self.assertEqual(g._resolve_python_module(g.project_dir / ".." / "sdk", ["client"]),
                         "outside:sdk/client.py")
        self.assertIsNone(g._resolve_python_module(g.project_dir / ".." / "elsewhere",
                                                   ["client"]))

    # -- the answer says it left the project ------------------------------------------------

    def test_a_project_that_declares_nothing_produces_byte_identical_output(self):
        """ADR-029's absent-not-empty rule, which this inherits rather than reinvents.

        Mutation: write `graph['substrate']['outside_roots'] = crossed or {}` in `_finalise`
        and this fails immediately — every repository in the world would start carrying an
        empty key, and every `--query` answer would grow a field that always reads the same.
        """
        for label, declaration in (("no settings file", None), ("empty section", {})):
            with self.subTest(case=label):
                _, proj, g = self.built(declaration)
                self.assertNotIn("outside_roots", g.graph["substrate"])
                self.assertEqual(graph_ops._answer_caveats(g.graph), {})
                self.assertNotIn("outside_roots", g.query("src/a.ts"))

    def test_the_artifact_and_the_query_both_say_what_was_crossed(self):
        """The payload half of ADR-029's split, on the two surfaces that can carry structure.

        `--query` is where an agent reads programmatically, and an impact answer computed over
        a graph with edges leaving the repository is not the same sentence as one that is
        entirely in-tree.
        """
        _, proj, g = self.built({"ui": "../packages/ui"})
        expected = {"declared": [{"alias": "ui", "path": "../packages/ui", "crossings": 1}],
                    "crossings": 1}
        self.assertEqual(g.graph["substrate"]["outside_roots"], expected)
        self.assertEqual(g.query("src/a.ts")["outside_roots"], expected)
        self.assertEqual(graph_ops._answer_caveats(g.graph)["outside_roots"], expected)

    def test_a_declared_root_nothing_imports_is_reported_with_zero_crossings(self):
        """A declaration that buys nothing is a typo or a leftover, and omitting it is the
        silent-no-effect configuration this repository keeps paying for.

        Mutation: return early from `_outside_report` when the total is zero, or filter
        `declared` down to the aliases that were crossed. Either turns this red while the row
        above stays green.
        """
        _, _, g = self.built({"ui": "../packages/ui", "unused": "../packages"})
        block = g.graph["substrate"]["outside_roots"]
        self.assertEqual({e["alias"]: e["crossings"] for e in block["declared"]},
                         {"ui": 1, "unused": 0})
        self.assertEqual(block["crossings"], 1)

    def test_a_refused_declaration_reaches_the_artifact_and_not_only_stderr(self):
        """The reason the refusals are carried at all: the warning goes to stderr, and ADR-029
        measured that stderr is dead skill-to-skill. A declaration thrown away in a run nobody
        watched is exactly what a reader of the artifact needs told."""
        _, _, g = self.built({"ui": "../packages/ui", "gone": "../packages/nope"})
        self.assertEqual(g.graph["substrate"]["outside_roots"]["refused"],
                         [{"alias": "gone", "path": "../packages/nope",
                           "reason": "does not name a directory that exists"}])

    def test_the_bare_array_surfaces_say_it_on_stderr_and_keep_their_shape(self):
        """ADR-029's channel split, unchanged and for the reason it measured.

        `run_behaviors._code_graph_deps` validates `--dependencies` with
        `isinstance(data, list)` and routes anything else to `graph-query-failed`, which takes
        every behaviour to `coverage: unknown` and wrap-up's gate green over zero behaviours.
        So the caveat goes to stderr and the array stays an array.

        It is worth saying on these two in particular: `substrate.internal_ends` filters an
        `outside:` target out of both — correctly, since it names no node to walk to — so this
        is the one surface where a crossing is otherwise structurally invisible.
        """
        _, proj, g = self.built({"ui": "../packages/ui"})
        # `_ANNOUNCED` dedupes for the life of the process, and the build above already said
        # this once. Saved and put back rather than just cleared: leaving it empty lets every
        # later test in the same process re-announce lines an earlier one had already spent.
        previously = set(graph_ops._ANNOUNCED)
        self.addCleanup(graph_ops._ANNOUNCED.update, previously)
        graph_ops._ANNOUNCED.clear()
        err = io.StringIO()
        with contextlib.redirect_stderr(err):
            deps = g.get_dependencies("src/a.ts")
        self.assertIsInstance(deps, set)
        self.assertEqual(deps, set())
        self.assertIn("leaves the project root", err.getvalue())
        self.assertIn("'ui'", err.getvalue())

    def test_a_declaration_changed_after_a_build_reaches_every_edge(self):
        """`--update` is the command the steady-state workflow runs, and a declaration is not
        a per-file change.

        Every other row in this class goes through `run_build`, and that is where this feature
        was wrong in both directions. `_get_changed_files` names what git says moved, so every
        *unchanged* file keeps the edges it was given under the old `outside` section, while
        `_outside_report` reads the settings file as it is *now* and stamps a `crossings` count
        over edges nobody re-resolved.

        Both directions were reachable by touching one unrelated file, and both lie:

        * remove a declaration and the artifact keeps `outside:` targets with no declaration in
          force at all — which is the shape ADR-031 defers to "a second backend starts emitting
          `outside:` tokens", reachable today with one producer;
        * add one and the report says `crossings: 0` over a file that does cross, and
          `_outside_report`'s own docstring defines a zero as a typo or a leftover. The report
          tells the reader to delete a declaration that is live.

        Mutation: drop the `declared_then != declared_now` comparison in `CodeGraph.update` and
        both halves go red — `status` comes back `updated`, and the edge and the report
        disagree.
        """
        for label, before, after, edge, report in (
                ("removed", {"ui": "../packages/ui"}, {},
                 "unresolved:../../packages/ui/src/Button", None),
                ("added", {}, {"ui": "../packages/ui"},
                 "outside:ui/src/Button.tsx",
                 {"declared": [{"alias": "ui", "path": "../packages/ui", "crossings": 1}],
                  "crossings": 1})):
            with self.subTest(declaration=label):
                root, proj = self.sibling_project(before)
                _git_repo(root)
                g = CodeGraph(proj)
                graph_ops.run_build(g, non_interactive=True, exclusions=g.project_exclusions())
                with open(os.path.join(proj, "knowledge-base", "settings.json"), "w",
                          encoding="utf-8") as handle:
                    json.dump({"outside": after}, handle)
                # One file, unrelated to the crossing. The point is that the crossing is
                # re-resolved even though git has nothing to say about the file that carries it.
                with open(os.path.join(proj, "src", "unrelated.ts"), "w",
                          encoding="utf-8") as handle:
                    handle.write("export const unrelated = 1\n")
                _commit(root)
                fresh = CodeGraph(proj)
                summary = graph_ops.run_update(fresh, non_interactive=True,
                                               exclusions=fresh.project_exclusions())
                self.assertEqual(summary["status"], substrate.Result.BUILT)
                self.assertEqual(ends(fresh.graph["files"]["src/a.ts"]["imports"]), [edge])
                self.assertEqual(fresh.graph["substrate"].get("outside_roots"), report)

    def test_a_declared_root_nothing_crossed_is_not_announced_as_a_crossing(self):
        """"This graph leaves the project root" is a claim about the edges, not about the file.

        Gated on a declaration merely being in force, it was false in the commonest state of a
        new declaration — one nobody has imported through yet — and printed on `--build` and
        again on every `--dependents`. On graphify it is worse: that backend never consults
        declarations, so the zero is not even a measurement and the sentence asserted a
        crossing over a backend that never looked.

        Mutation: restore the unconditional wording in `_outside_sentence` and both halves go
        red. The companion row `test_a_declared_root_nothing_imports_is_reported_with_zero_
        crossings` asserts the payload and never looks at a sentence, which is how this
        survived.
        """
        root = self.mk({
            "proj/knowledge-base/settings.json": '{"outside": {"ui": "../packages/ui"}}',
            "proj/src/a.ts": "export const a = 1\n",
            "proj/src/b.ts": "import { a } from './a'\nexport const b = 1\n",
            "packages/ui/src/Button.tsx": "export const B = 1\n",
        })
        proj = os.path.join(root, "proj")
        g = CodeGraph(proj)
        previously = set(graph_ops._ANNOUNCED)
        self.addCleanup(graph_ops._ANNOUNCED.update, previously)
        graph_ops._ANNOUNCED.clear()
        err = io.StringIO()
        with contextlib.redirect_stderr(err):
            summary = graph_ops.run_build(g, non_interactive=True,
                                          exclusions=g.project_exclusions())
        self.assertEqual(g.graph["substrate"]["outside_roots"]["crossings"], 0)
        self.assertIn("does not leave the project root", err.getvalue())
        self.assertNotIn("this graph leaves the project root", err.getvalue())
        self.assertIn("does not leave the project root",
                      graph_ops.format_summary(summary, "build"))
        graph_ops._ANNOUNCED.clear()
        err = io.StringIO()
        with contextlib.redirect_stderr(err):
            g.get_dependents("src/a.ts")
        self.assertIn("does not leave the project root", err.getvalue())
        # The second line qualifies *this answer*, and there is nothing to qualify: printed
        # unconditionally it warned that "a file under a declared root is resolved to" for an
        # answer in which no file was.
        self.assertNotIn("resolved to, never graphed", err.getvalue())

    def test_the_summary_surfaces_carry_the_caveat_the_payload_carries(self):
        """ADR-029 splits the caveat by audience, and `--format summary` fell through the split.

        `--query --format summary` printed an `outside:` target with no qualification at all,
        and `--impact --format summary` printed a blast radius with nothing on either stream,
        while both carried the block in `--format json`. That inverts the ADR: the machine was
        told and the person was not. `--dependents`/`--dependencies` are the exception and stay
        one — they answer with a bare array that cannot carry a field, so they use stderr.

        Mutation: drop `_outside_line` from any one of the four `format_summary` branches and
        the row for it goes red. TROUBLESHOOTING.md presents `--format summary` as "the graph,
        and what it could not read", so this is the documented human entry point.
        """
        _, _, g = self.built({"ui": "../packages/ui"})
        cached = graph_ops.persist_graph(g.project_dir, g.name, g.graph)
        self.assertTrue(cached)
        for operation, data in (
                ("build", dict(substrate.build_summary(g.graph, cached),
                               **graph_ops._answer_caveats(g.graph, full=True))),
                ("update", dict({"status": "updated", "files_changed": 1, "commit": "abc"},
                                **graph_ops._answer_caveats(g.graph, full=True))),
                ("update", dict({"status": "up_to_date", "files_changed": 0, "commit": "abc"},
                                **graph_ops._answer_caveats(g.graph, full=True))),
                ("query", g.query("src/a.ts")),
                ("impact", g.get_impact(["src/a.ts"]))):
            with self.subTest(surface="%s/%s" % (operation, data.get("status", "-"))):
                rendered = graph_ops.format_summary(data, operation)
                self.assertIn("leaves the project root", rendered)
                self.assertIn("'ui' (../packages/ui)", rendered)
        # And the control: a project that declares nothing renders exactly what it always did.
        _, _, plain = self.built()
        self.assertNotIn("project root",
                         graph_ops.format_summary(plain.query("src/a.ts"), "query"))

    def test_a_persisted_block_of_the_wrong_shape_breaks_closed(self):
        """The two bare-array surfaces must degrade, not raise, on any artifact shape.

        `_outside_block` guarded the outer dict and stopped there, so a persisted
        `{"declared": ["ui"]}` — or `"ui"`, which is truthy and iterates into characters —
        reached `.get` one level down and raised `AttributeError` out of `--dependents` and
        `--dependencies`. That is the same defect `_census_block`'s docstring records, one
        level deeper in the same block, and ADR-031 requires these two to break closed.

        Mutation: replace `_declared_entries`' body with `block.get('declared') or []` and
        every shape below raises.
        """
        _, _, g = self.built({"ui": "../packages/ui"})
        for shape in ({"declared": ["ui"]}, {"declared": "ui"}, {"declared": [None]},
                      {"declared": {"alias": "ui"}}, {"crossings": 1}, {}):
            with self.subTest(shape=repr(shape)):
                g.graph["substrate"]["outside_roots"] = shape
                graph_ops.persist_graph(g.project_dir, g.name, g.graph)
                fresh = CodeGraph(str(g.project_dir))
                with contextlib.redirect_stderr(io.StringIO()):
                    self.assertEqual(fresh.get_dependencies("src/a.ts"), set())
                    self.assertEqual(fresh.get_dependents("src/b.ts"), set())
                self.assertEqual(graph_ops._outside_sentence(shape), "")

    def test_a_symlink_out_of_the_project_is_still_not_a_declaration(self):
        """A symlink is an *implicit* crossing, and a declaration never re-authorises one.

        The declared root here is `../packages/ui`, and `proj/vendor` is a symlink to
        `../packages` — one level above it. Resolution through the symlink lands outside the
        declared root, so it is refused: a declaration authorises the directory it names, not
        the neighbourhood it sits in (SEC-008).
        """
        root, proj = self.sibling_project({"ui": "../packages/ui"})
        try:
            os.symlink(os.path.join(root, "packages"), os.path.join(proj, "vendor"),
                       target_is_directory=True)
        except (OSError, NotImplementedError, AttributeError) as exc:
            self.skipTest("this host will not create symlinks: %s" % exc)
        with open(os.path.join(proj, "src", "c.ts"), "w", encoding="utf-8") as handle:
            handle.write("import { X } from '../vendor/other/x'\n")
        g = CodeGraph(proj)
        self.assertEqual(g._classify_import("../vendor/other/x", "src/c.ts"),
                         "unresolved:../vendor/other/x")


class TestASymlinkDoesNotCrossTheRootOnItsOwn(Base):
    """SEC-023. ADR-031 said crossing the root is a declared act; it was true of imports.

    An `..` import, a tsconfig `paths` escape and an absolute import all came back
    `unresolved:`. A symlink committed *inside* the project pointing outside it was globbed
    by discovery, opened, parsed, and its declarations published as a node's `exports` — no
    declaration, nothing on stderr. SEC-008's defect on the other traversal.

    The fixture detail that matters: without a committed `settings.json` the classification
    path differs and the symlink is not picked up at all, so a first attempt at this
    reproduction wrongly came back clean. A negative result here is worth nothing without it.
    """

    LEAKED = "LEAKED_FROM_OUTSIDE_ROOT"

    def linked_project(self, *, target_outside=True, declaration=None):
        root = self.mk({
            "proj/src/app.ts": "import './linkfile'\n",
            "proj/src/real.ts": "export const INSIDE = 1\n",
            "outside/leaked.ts": "export const %s = 1\n" % self.LEAKED,
        })
        proj = os.path.join(root, "proj")
        os.makedirs(os.path.join(proj, "knowledge-base"), exist_ok=True)
        cfg = {"substrate": {"backend": "homegrown"}}
        if declaration is not None:
            cfg["outside"] = declaration
        with open(os.path.join(proj, "knowledge-base", "settings.json"), "w",
                  encoding="utf-8") as handle:
            json.dump(cfg, handle)
        target = (os.path.join(root, "outside", "leaked.ts") if target_outside
                  else os.path.join(proj, "src", "real.ts"))
        try:
            os.symlink(target, os.path.join(proj, "src", "linkfile.ts"))
        except (OSError, NotImplementedError, AttributeError) as exc:
            self.skipTest("this host will not create symlinks: %s" % exc)
        g = CodeGraph(proj)
        graph_ops.run_build(g, non_interactive=True, exclusions=g.project_exclusions())
        return proj, g

    def test_a_symlink_out_of_the_project_is_refused_and_said_out_loud(self):
        """The finding. Refused, and the refusal is in the artifact rather than only on
        stderr, because stderr is dead skill-to-skill and a silently shorter file set is a
        blast radius that is quietly too small (ADR-029)."""
        _, g = self.linked_project()
        self.assertNotIn("src/linkfile.ts", g.graph["files"])
        block = g.graph["substrate"]["escaping_links"]
        self.assertEqual((block["refused"], block["crossed"]), (1, 0))
        self.assertEqual(block["sample"]["refused"], ["src/linkfile.ts"])

    def test_nothing_outside_the_root_is_read_through_the_link(self):
        """The reason the finding was Medium rather than cosmetic: the name published as an
        export existed only in the file outside the root."""
        _, g = self.linked_project()
        self.assertNotIn(self.LEAKED, json.dumps(g.graph))

    def test_a_symlink_that_stays_inside_the_project_still_becomes_a_node(self):
        """The row that stops this being 'refuse every symlink'.

        A monorepo links a package into place, and `containment.within` is the predicate
        precisely because it asks whether the *file* is inside rather than whether the entry
        is a link. Simplify this to `os.path.islink` and this test goes red.
        """
        _, g = self.linked_project(target_outside=False)
        self.assertIn("src/linkfile.ts", g.graph["files"])
        self.assertNotIn("escaping_links", g.graph["substrate"])

    def test_a_declared_target_makes_it_a_crossing_and_still_not_a_node(self):
        """Declared, so legitimate — and it lands on the same side of the line as an import
        into a declared root. ADR-031's grant is resolution only: an outside file never
        becomes a `files` key, whichever route reached it. Were a symlink to produce a node
        here, the declaration would buy strictly more through a link than through an import.
        """
        _, g = self.linked_project(declaration={"out": "../outside"})
        self.assertNotIn("src/linkfile.ts", g.graph["files"])
        block = g.graph["substrate"]["escaping_links"]
        self.assertEqual((block["refused"], block["crossed"]), (0, 1))
        self.assertEqual(block["sample"]["crossed"]["src/linkfile.ts"],
                         "outside:out/leaked.ts")
        self.assertNotIn(self.LEAKED, json.dumps(g.graph))

    def test_a_project_with_no_symlinks_says_nothing(self):
        """Absent, not empty (ADR-029) — so every repository that has never had a symlink
        produces byte-identical output to one built before this existed. No symlink is
        created, so this row asserts on every host and the class is never wholly skipped.
        """
        root = self.mk({"proj/src/app.ts": "export const a = 1\n"})
        proj = os.path.join(root, "proj")
        os.makedirs(os.path.join(proj, "knowledge-base"), exist_ok=True)
        with open(os.path.join(proj, "knowledge-base", "settings.json"), "w",
                  encoding="utf-8") as handle:
            json.dump({"substrate": {"backend": "homegrown"}}, handle)
        g = CodeGraph(proj)
        graph_ops.run_build(g, non_interactive=True, exclusions=g.project_exclusions())
        self.assertNotIn("escaping_links", g.graph["substrate"])

    def test_the_sample_cap_is_the_number_validation_errors_uses(self):
        """A parity claim a comment makes is a claim nothing checks. This is the check."""
        self.assertEqual(graph_ops._MAX_RECORDED_ESCAPING_LINKS,
                         graph_ops._MAX_RECORDED_VALIDATION_ERRORS)
        self.assertEqual(graph_ops._MAX_RECORDED_ESCAPING_LINKS, 20)


if __name__ == "__main__":
    unittest.main(verbosity=2)
