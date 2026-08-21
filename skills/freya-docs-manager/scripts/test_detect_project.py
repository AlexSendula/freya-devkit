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


class ExtensionCensusTest(Base):
    """The extension table is the whole of the manifestless fallback, and none of it was named.

    `ManifestlessProjectTest` above exercises the census through `.py`, `.go` and `.ts` only —
    three of the fourteen extensions it knows. The other eleven decide the answer for every
    repo without a manifest, and three of the runtimes they produce — `ruby`, `dotnet` and
    `swift` — have no manifest branch anywhere in `detect_package_manager`, which checks for
    eight files and none of them is a Gemfile, a `.csproj` or a `Package.swift`. For those
    three stacks this table is the only thing that can ever name the runtime.
    """

    EXTENSIONS = [
        (".py", "python"), (".ts", "nodejs"), (".tsx", "nodejs"), (".js", "nodejs"),
        (".jsx", "nodejs"), (".go", "go"), (".rs", "rust"), (".java", "jvm"),
        (".kt", "jvm"), (".scala", "jvm"), (".rb", "ruby"), (".php", "php"),
        (".cs", "dotnet"), (".swift", "swift"),
    ]

    def test_every_extension_the_census_knows_names_its_runtime(self):
        for ext, runtime in self.EXTENSIONS:
            with self.subTest(ext=ext):
                d = self.mk({"src/a" + ext: "x\n"})
                self.assertEqual(detect_project.infer_runtime_from_sources(d), runtime)
        # A literal, not the table under test: a fifteenth extension added without a case
        # above would otherwise ship with nothing exercising it, which is how this table got
        # to fourteen members and three tests.
        self.assertEqual(len(detect_project._RUNTIME_BY_EXT), 14)

    def test_the_extension_match_is_case_insensitive(self):
        """The table is keyed in lower case, so the lookup's `.lower()` is load-bearing rather
        than decorative: without it every upper-cased extension falls through to `None` and
        the repo reports no runtime at all, which is the same silence a manifestless repo used
        to produce — the bug the census exists to fix."""
        d = self.mk({"src/Main.JAVA": "class Main {}\n"})
        self.assertEqual(detect_project.infer_runtime_from_sources(d), "jvm")


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


class TestRunnerDetectionTest(Base):
    """`detect_test_runners` is what tells the Behavior Layer how to run anything.

    It had no test of any kind, while carrying three separate registries — ten package.json
    dependencies, six config-file patterns and four Python signals. Each is a claim about a
    stack this project does not otherwise touch, so an entry that never worked would look
    exactly like a project that happens not to use that runner.
    """

    NO_TOOLING = {
        "package.json": json.dumps({"name": "x", "dependencies": {"express": "4.19.2"}}),
        "requirements.txt": "requests==2.32.3\n",
        "src/app.js": "module.exports = 1;\n",
        "src/app.py": "x = 1\n",
        "README.md": "# x\n",
    }

    def test_a_project_with_no_test_tooling_reports_an_empty_runner_list(self):
        """An empty list is the answer, not the absence of one.

        The caller cannot distinguish "detection found nothing" from "detection fell over"
        unless the shape is the same either way, so both keys must be present and both must
        be lists — a `None`, a missing key or a raise would each turn a project with no tests
        into a broken run. The fixture is a real project with dependencies, Python and
        JavaScript sources and a README, none of which is test tooling; the control below
        proves the detector is looking at this tree rather than failing to see it.
        """
        found = detect_project.detect_test_runners(self.mk(self.NO_TOOLING))
        self.assertEqual(found, {"runners": [], "evidence": []})

        # Control: one file added to the same tree and the same call answers.
        with_tooling = dict(self.NO_TOOLING, **{"pytest.ini": "[pytest]\n"})
        self.assertEqual(detect_project.detect_test_runners(self.mk(with_tooling))["runners"],
                         ["pytest"])

    def test_every_runner_dependency_in_package_json_is_recognised(self):
        """All ten entries of the dependency table, and the devDependencies half of the merge.

        Test runners are dev dependencies in practice, and nothing else in this file reads
        `devDependencies` at all — `detect_framework`'s tests all go through `dependencies`.
        """
        for dep, runner in [
            ("jest", "jest"),
            ("vitest", "vitest"),
            ("mocha", "mocha"),
            ("jasmine", "jasmine"),
            ("cypress", "cypress"),
            ("@playwright/test", "playwright"),
            ("playwright", "playwright"),
            ("@cucumber/cucumber", "cucumber"),
            ("cucumber", "cucumber"),
            ("jest-cucumber", "cucumber"),
        ]:
            with self.subTest(dep=dep):
                d = self.mk({"package.json": json.dumps(
                    {"name": "x", "devDependencies": {dep: "1.0.0"}})})
                found = detect_project.detect_test_runners(d)
                self.assertEqual(found["runners"], [runner])
                self.assertEqual(found["evidence"], ["package.json:" + dep])

    def test_a_config_file_is_enough_when_the_dependency_is_absent(self):
        """A runner installed globally, or hoisted by a workspace root, leaves a config file
        and no entry in this package's manifest. The manifest here declares no dependencies
        at all, so the config pattern is the only thing that can produce the answer."""
        for filename, runner, pattern in [
            ("jest.config.js", "jest", "config:jest.config.*"),
            ("vitest.config.ts", "vitest", "config:vitest.config.*"),
            ("playwright.config.ts", "playwright", "config:playwright.config.*"),
            ("cypress.config.ts", "cypress", "config:cypress.config.*"),
            ("cypress.json", "cypress", "config:cypress.json"),
            (".mocharc.json", "mocha", "config:.mocharc*"),
        ]:
            with self.subTest(filename=filename):
                d = self.mk({"package.json": '{"name":"x"}', filename: "{}\n"})
                found = detect_project.detect_test_runners(d)
                self.assertEqual(found["runners"], [runner])
                self.assertEqual(found["evidence"], [pattern])

    def test_unittest_is_inferred_from_file_names_only_when_pytest_is_not_present(self):
        """`unittest` is stdlib, so it has no dependency entry and can only be inferred from
        naming — and `test_*.py` is exactly what a pytest project looks like too. Reporting
        both would send the Behavior Layer at a runner the project does not drive; this repo
        is the case in point, since its 29 files are `unittest.TestCase` classes that CI runs
        under pytest, and `pytest` is the right answer for it.
        """
        bare = self.mk({"tests/test_thing.py": "x = 1\n"})
        self.assertEqual(detect_project.detect_test_runners(bare)["runners"], ["unittest"])

        with_pytest = self.mk({"tests/test_thing.py": "x = 1\n",
                               "requirements.txt": "pytest==8.3.2\n"})
        self.assertEqual(detect_project.detect_test_runners(with_pytest)["runners"],
                         ["pytest"])

    def test_feature_files_are_reported_next_to_the_runner_that_executes_them(self):
        """Gherkin is a signal about the *suite*, not about the runner: the same `.feature`
        tree is driven by jest-cucumber, behave or cucumber-js. Both facts have to survive
        into the answer, because neither one alone says how to run the thing.
        """
        d = self.mk({
            "package.json": json.dumps({"name": "x", "devDependencies": {
                "jest-cucumber": "3.0.0"}}),
            "features/login.feature": "Feature: login\n",
        })
        found = detect_project.detect_test_runners(d)
        self.assertEqual(found["runners"], ["cucumber", "gherkin"])
        self.assertEqual(found["evidence"],
                         ["glob:*.feature", "package.json:jest-cucumber"])


if __name__ == "__main__":
    unittest.main(verbosity=2)
