#!/usr/bin/env python3
"""Proof suite for detect_project.py — the stack detector docs-manager runs on.

Written during the Track B agnosticism sweep, which is also when it emerged that this module
had no tests at all. Half of these are a regression guard for behaviour that already worked;
the rest cover stacks it could not see, which is the point of the sweep.

Run: python test_detect_project.py
"""

import json
import os
import shutil
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import detect_project  # noqa: E402


class Base(unittest.TestCase):
    def mk(self, files):
        d = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, d, ignore_errors=True)
        for rel, content in files.items():
            p = Path(d) / rel
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_text(content, encoding="utf-8")
        return d

    def pkg(self, **deps):
        return json.dumps({"name": "x", "dependencies": deps})


class RuntimeDetectionTest(Base):
    """Regression guard: the runtimes that already worked must keep working."""

    def test_node(self):
        d = self.mk({"package.json": self.pkg(), "pnpm-lock.yaml": ""})
        r = detect_project.detect_package_manager(d)
        self.assertEqual(r["runtime"], "nodejs")
        self.assertEqual(r["package_manager"], "pnpm")

    def test_python(self):
        d = self.mk({"pyproject.toml": "[project]\nname='x'\n"})
        self.assertEqual(detect_project.detect_package_manager(d)["runtime"], "python")

    def test_go(self):
        d = self.mk({"go.mod": "module x\n"})
        self.assertEqual(detect_project.detect_package_manager(d)["runtime"], "go")

    def test_rust(self):
        d = self.mk({"Cargo.toml": "[package]\nname='x'\n"})
        self.assertEqual(detect_project.detect_package_manager(d)["runtime"], "rust")

    def test_an_unrecognised_project_reports_nothing_rather_than_guessing(self):
        self.assertEqual(detect_project.detect_package_manager(self.mk({"README.md": "hi"})), {})


class ManifestlessProjectTest(Base):
    """Not every real project declares a manifest.

    freya-devkit is 50-odd Python files with no pyproject.toml, and reported no runtime at
    all — so docs-manager had nothing to key on when run against the very repo it ships from.
    Plenty of scripts, tools and plugin repos look the same.
    """

    def test_a_python_repo_without_a_manifest_is_still_python(self):
        d = self.mk({
            "bin/cli.py": "x = 1\n",
            "lib/core.py": "y = 2\n",
            "lib/util.py": "z = 3\n",
        })
        r = detect_project.detect_package_manager(d)
        self.assertEqual(r["runtime"], "python")
        self.assertEqual(r.get("runtime_source"), "file-extensions")

    def test_the_dominant_language_wins(self):
        d = self.mk({
            "a.go": "package main\n", "b.go": "package main\n", "c.go": "package main\n",
            "script.py": "x = 1\n",
        })
        self.assertEqual(detect_project.detect_package_manager(d)["runtime"], "go")

    def test_a_manifest_always_beats_the_file_census(self):
        """A Node repo with a build script in Python is still a Node repo."""
        d = self.mk({
            "package.json": self.pkg(),
            "a.py": "1\n", "b.py": "2\n", "c.py": "3\n", "d.py": "4\n",
        })
        r = detect_project.detect_package_manager(d)
        self.assertEqual(r["runtime"], "nodejs")
        self.assertNotIn("runtime_source", r)

    def test_a_repo_with_no_source_at_all_still_reports_nothing(self):
        d = self.mk({"README.md": "hi", "notes.txt": "x"})
        self.assertEqual(detect_project.detect_package_manager(d), {})

    def test_dependency_trees_do_not_decide_the_runtime(self):
        d = self.mk({
            "src/a.ts": "1\n",
            "node_modules/pkg/x.py": "1\n", "node_modules/pkg/y.py": "2\n",
            "node_modules/pkg/z.py": "3\n", "node_modules/pkg/w.py": "4\n",
        })
        self.assertEqual(detect_project.detect_package_manager(d)["runtime"], "nodejs")


class JvmDetectionTest(Base):
    """Java was the language that started Track B, and the detector could not see it.

    A Maven or Gradle project reported no runtime at all, so every downstream question —
    which doc templates, which test runner, which build command — had nothing to go on.
    """

    def test_maven(self):
        d = self.mk({"pom.xml": "<project><artifactId>x</artifactId></project>"})
        r = detect_project.detect_package_manager(d)
        self.assertEqual(r["runtime"], "jvm")
        self.assertEqual(r["package_manager"], "maven")

    def test_gradle(self):
        d = self.mk({"build.gradle": "plugins { id 'java' }"})
        r = detect_project.detect_package_manager(d)
        self.assertEqual(r["runtime"], "jvm")
        self.assertEqual(r["package_manager"], "gradle")

    def test_gradle_kotlin_dsl(self):
        d = self.mk({"build.gradle.kts": "plugins { java }"})
        self.assertEqual(detect_project.detect_package_manager(d)["package_manager"], "gradle")

    def test_spring_boot_is_a_backend(self):
        d = self.mk({"pom.xml": "<project><dependency>"
                                "<artifactId>spring-boot-starter-web</artifactId>"
                                "</dependency></project>"})
        self.assertEqual(detect_project.detect_framework(d, "jvm")["backend"], "spring")

    def test_a_plain_jvm_project_claims_no_framework(self):
        d = self.mk({"pom.xml": "<project><artifactId>x</artifactId></project>"})
        self.assertIsNone(detect_project.detect_framework(d, "jvm")["backend"])


class MobileDetectionTest(Base):
    """Expo/React Native reads as plain `react` without this, which picks web templates."""

    def test_expo(self):
        d = self.mk({"package.json": self.pkg(expo="~52.0.0", react="18.3.1"),
                     "app.json": '{"expo": {"name": "x"}}'})
        self.assertEqual(detect_project.detect_framework(d, "nodejs")["frontend"], "expo")

    def test_bare_react_native(self):
        d = self.mk({"package.json": self.pkg(**{"react-native": "0.76.0", "react": "18.3.1"})})
        self.assertEqual(detect_project.detect_framework(d, "nodejs")["frontend"],
                         "react-native")

    def test_expo_wins_over_react_native_and_react(self):
        """All three are present in every Expo app; the most specific one is the answer."""
        d = self.mk({"package.json": self.pkg(
            expo="~52.0.0", **{"react-native": "0.76.0", "react": "18.3.1"})})
        self.assertEqual(detect_project.detect_framework(d, "nodejs")["frontend"], "expo")

    def test_a_web_react_app_is_still_react(self):
        d = self.mk({"package.json": self.pkg(react="18.3.1")})
        self.assertEqual(detect_project.detect_framework(d, "nodejs")["frontend"], "react")

    def test_nextjs_still_wins_for_a_next_app(self):
        d = self.mk({"package.json": self.pkg(next="15.0.0", react="18.3.1")})
        self.assertEqual(detect_project.detect_framework(d, "nodejs")["frontend"], "nextjs")


class MonorepoDetectionTest(Base):
    """The shape acme-travel is moving to, and the shape the graph now resolves."""

    def test_npm_workspaces(self):
        d = self.mk({
            "package.json": json.dumps({"name": "root", "workspaces": ["packages/*"]}),
            "packages/domain/package.json": '{"name":"@x/domain"}',
        })
        r = detect_project.detect_package_manager(d)
        self.assertTrue(r["monorepo"])
        self.assertEqual(r["workspace_tool"], "npm")

    def test_pnpm_workspaces(self):
        d = self.mk({
            "package.json": '{"name":"root"}',
            "pnpm-workspace.yaml": "packages:\n  - 'packages/*'\n",
        })
        r = detect_project.detect_package_manager(d)
        self.assertTrue(r["monorepo"])
        self.assertEqual(r["workspace_tool"], "pnpm")

    def test_a_pnpm_file_without_packages_is_not_a_monorepo(self):
        """The testbed's file declares only build settings."""
        d = self.mk({
            "package.json": '{"name":"solo"}',
            "pnpm-workspace.yaml": "onlyBuiltDependencies:\n  - better-sqlite3\n",
        })
        self.assertFalse(detect_project.detect_package_manager(d).get("monorepo"))

    def test_a_single_package_repo_is_not_a_monorepo(self):
        d = self.mk({"package.json": '{"name":"solo"}'})
        self.assertFalse(detect_project.detect_package_manager(d).get("monorepo"))


class OrmDetectionTest(Base):
    def test_prisma_still_detected(self):
        d = self.mk({"prisma/schema.prisma": 'datasource db { provider = "postgresql" }'})
        self.assertEqual(detect_project.detect_database(d)["orm"], "prisma")

    def test_a_project_without_an_orm_says_so(self):
        self.assertIsNone(detect_project.detect_database(self.mk({}))["orm"])


class ExistingDocsTest(Base):
    """Found by running docs-manager on freya-devkit itself.

    The detector looked only at `docs/`, so a project that had already adopted the
    toolkit's own `knowledge-base/` layout reported no docs directory and no existing
    files — and every run planned a from-scratch create instead of a reverse-sync.
    """

    def test_the_toolkits_own_layout_is_found(self):
        d = self.mk({"knowledge-base/reference/ARCHITECTURE.md": "# A\n"})
        found = detect_project.detect_existing_docs(d)
        self.assertEqual(found["layout"], "knowledge-base")
        self.assertTrue(found["docs_dir"].endswith(os.path.join("knowledge-base", "reference")))
        self.assertIn("ARCHITECTURE.md", found["files"])

    def test_reference_wins_over_the_knowledge_base_root(self):
        d = self.mk({"knowledge-base/README.md": "# Index\n",
                     "knowledge-base/reference/ARCHITECTURE.md": "# A\n"})
        found = detect_project.detect_existing_docs(d)
        self.assertTrue(found["docs_dir"].endswith(os.path.join("knowledge-base", "reference")))
        self.assertEqual(found["files"], ["ARCHITECTURE.md"])

    def test_a_knowledge_base_holding_only_settings_is_not_a_docs_dir(self):
        """`knowledge-base/` exists the moment code-graph writes settings.json.

        Reporting that as "documentation is present" would suppress the create the
        project actually needs, which is worse than the bug this test came from.
        """
        d = self.mk({"knowledge-base/settings.json": "{}\n"})
        found = detect_project.detect_existing_docs(d)
        self.assertIsNone(found["docs_dir"])
        self.assertIsNone(found["layout"])

    def test_the_legacy_docs_layout_still_works(self):
        d = self.mk({"docs/architecture.md": "# A\n"})
        found = detect_project.detect_existing_docs(d)
        self.assertEqual(found["layout"], "docs")
        self.assertIn("architecture.md", found["files"])

    def test_knowledge_base_wins_when_both_exist(self):
        d = self.mk({"docs/architecture.md": "# old\n",
                     "knowledge-base/reference/ARCHITECTURE.md": "# new\n"})
        found = detect_project.detect_existing_docs(d)
        self.assertEqual(found["layout"], "knowledge-base")
        self.assertNotIn("architecture.md", found["files"])

    def test_root_documents_are_reported_with_no_docs_dir_at_all(self):
        d = self.mk({"README.md": "# r\n", "AGENTS.md": "# a\n"})
        found = detect_project.detect_existing_docs(d)
        self.assertIsNone(found["docs_dir"])
        self.assertEqual(found["files"], ["README.md", "AGENTS.md"])


if __name__ == "__main__":
    unittest.main(verbosity=2)
