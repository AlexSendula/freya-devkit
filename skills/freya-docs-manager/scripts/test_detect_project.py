#!/usr/bin/env python3
"""Proof suite for detect_project.py — the stack detector docs-manager runs on.

Written during the Track B agnosticism sweep, which is also when it emerged that this module
had no tests at all. Half of these are a regression guard for behaviour that already worked;
the rest cover stacks it could not see, which is the point of the sweep.

Run: python test_detect_project.py
"""

import contextlib
import io
import json
import os
import shutil
import sys
import tempfile
import unittest
import unittest.mock as mock
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
# `_WALK_FILE_LIMIT` claims to be `substrate.CENSUS_LIMIT`; the claim is asserted rather than
# restated, so the constant is imported by the ADR-030 sibling pattern (`verify_links.py:40`)
# instead of copied here as a literal that would agree forever whatever the original became.
sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "freya-code-graph" / "scripts"))
import detect_project  # noqa: E402
import substrate  # noqa: E402


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


class PackageManagerTableTest(Base):
    """The manifest chain: eight manifests and four lockfiles, named four times above.

    The package manager is what every generated `DEVELOPER.md` puts in its install and test
    commands, so a row that stopped matching does not produce an error — it produces a
    document telling the reader to run the wrong tool. `yarn`, `bun`, `poetry`, `composer`
    and three of the four Gradle files had nothing exercising them at all.

    Literal rows: the chain is inline `if`/`elif` inside the function, with no table to drive
    off. Each row asserts the pair the detector reports, plus the absence of `runtime_source`
    — these are declarations, and the census flag must not appear on any of them, which is
    the one thing that distinguishes this path from `ManifestlessProjectTest` below.
    """

    MANIFESTS = [
        ({"package.json": '{"name":"x"}'}, "nodejs", "npm"),
        ({"package.json": '{"name":"x"}', "pnpm-lock.yaml": ""}, "nodejs", "pnpm"),
        ({"package.json": '{"name":"x"}', "yarn.lock": ""}, "nodejs", "yarn"),
        ({"package.json": '{"name":"x"}', "bun.lockb": ""}, "nodejs", "bun"),
        ({"pyproject.toml": "[project]\nname='x'\n"}, "python", "pip"),
        ({"pyproject.toml": "[project]\nname='x'\n", "poetry.lock": ""}, "python", "poetry"),
        ({"requirements.txt": "requests\n"}, "python", "pip"),
        ({"go.mod": "module x\n"}, "go", "go_modules"),
        ({"Cargo.toml": "[package]\nname='x'\n"}, "rust", "cargo"),
        ({"composer.json": '{"name":"x/y"}'}, "php", "composer"),
        ({"pom.xml": "<project/>"}, "jvm", "maven"),
        ({"build.gradle": "plugins {}"}, "jvm", "gradle"),
        ({"build.gradle.kts": "plugins {}"}, "jvm", "gradle"),
        ({"settings.gradle": "rootProject.name = 'x'"}, "jvm", "gradle"),
        ({"settings.gradle.kts": "rootProject.name = \"x\""}, "jvm", "gradle"),
    ]

    def test_every_manifest_names_its_runtime_and_package_manager(self):
        for files, runtime, manager in self.MANIFESTS:
            with self.subTest(files=sorted(files)):
                found = detect_project.detect_package_manager(self.mk(files))
                self.assertEqual(found["runtime"], runtime)
                self.assertEqual(found["package_manager"], manager)
                self.assertNotIn("runtime_source", found)

    def test_the_most_specific_lockfile_present_decides_the_node_package_manager(self):
        """A repo that has switched managers keeps the old lockfile around more often than
        not, so which one wins is a decision and not an accident."""
        d = self.mk({"package.json": '{"name":"x"}', "pnpm-lock.yaml": "",
                     "yarn.lock": "", "bun.lockb": ""})
        self.assertEqual(detect_project.detect_package_manager(d)["package_manager"], "pnpm")


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

    The rows are taken from `_RUNTIME_BY_EXT` itself rather than copied out of it, so a
    fifteenth extension is exercised the moment it is added and cannot ship unnamed. What
    each row asserts is not the mapping — restating it would pass with the census deleted —
    but the observable end of it: a repo whose only source file carries that extension is
    reported as that runtime, through the same public entry point docs-manager calls, and
    flagged `runtime_source: file-extensions` so a caller can tell the inference from a
    declaration.

    What a row driven off the table cannot see is a *wrong* value in it — remap `.rb` to
    `"rubby"` and both sides of the assertion move together. `RUNTIME_VOCABULARY` below is
    the literal that closes that: a runtime name nothing downstream keys on is inert, and
    inert is exactly how a typo would present.
    """

    #: The runtime names the rest of the toolkit branches on — `detect_framework`'s three
    #: chains, plus the ones only this census can ever produce. A literal, deliberately:
    #: it is the vocabulary the table's values have to belong to, not a copy of the table.
    RUNTIME_VOCABULARY = {"python", "nodejs", "go", "rust", "jvm", "ruby", "php",
                          "dotnet", "swift"}

    def test_no_extension_maps_to_a_runtime_nothing_downstream_understands(self):
        for ext, runtime in sorted(detect_project._RUNTIME_BY_EXT.items()):
            with self.subTest(ext=ext):
                self.assertIn(runtime, self.RUNTIME_VOCABULARY)

    def test_every_extension_the_census_knows_names_its_runtime(self):
        # A table driven off a registry says nothing when the registry is empty, so the
        # loop is guarded rather than trusted.
        self.assertTrue(detect_project._RUNTIME_BY_EXT,
                        "the extension table is empty — every row below would be vacuous")
        for ext, runtime in sorted(detect_project._RUNTIME_BY_EXT.items()):
            with self.subTest(ext=ext):
                d = self.mk({"src/a" + ext: "x\n"})
                found = detect_project.detect_package_manager(d)
                self.assertEqual(found.get("runtime"), runtime)
                self.assertEqual(found.get("runtime_source"), "file-extensions")

    def test_an_extension_the_census_does_not_know_is_not_a_runtime(self):
        """The control for the table above: the fixture shape it uses produces an answer
        because of the extension, not because a directory with one file in it is enough.
        Without this, a census that returned `"python"` for anything at all would keep the
        `.py` row green and be caught by nothing else here.
        """
        for ext in (".txt", ".md", ".json", ".yaml"):
            with self.subTest(ext=ext):
                self.assertNotIn(ext, detect_project._RUNTIME_BY_EXT)
                d = self.mk({"src/a" + ext: "x\n"})
                self.assertEqual(detect_project.detect_package_manager(d), {})

    def test_the_extension_match_is_case_insensitive(self):
        """The table is keyed in lower case, so the lookup's `.lower()` is load-bearing rather
        than decorative: without it every upper-cased extension falls through to `None` and
        the repo reports no runtime at all, which is the same silence a manifestless repo used
        to produce — the bug the census exists to fix."""
        d = self.mk({"src/Main.JAVA": "class Main {}\n"})
        self.assertEqual(detect_project.infer_runtime_from_sources(d), "jvm")

    def test_the_census_stops_counting_at_its_limit(self):
        """The cap is the only thing standing between this walk and a monorepo with a
        hundred thousand files, and it changes the answer — it is a sample, not a total.
        Ten Python files sit at the root where the walk starts; a hundred Go files sit below
        it and are never reached, so the sample says python and the whole tree says go.
        """
        files = {"m%d.py" % i: "x = 1\n" for i in range(10)}
        files.update({"deep/g%d.go" % i: "package main\n" for i in range(100)})
        d = self.mk(files)
        self.assertEqual(detect_project.infer_runtime_from_sources(d, limit=5), "python")
        self.assertEqual(detect_project.infer_runtime_from_sources(d), "go")


class CensusPruningTest(Base):
    """`_CENSUS_SKIP` — fourteen directory names, one of which was ever named in a test.

    Every entry is a claim that the sources under it are somebody else's: a `node_modules`
    full of vendored Python, a `vendor/` full of Go, a `target/` full of decompiled classes.
    Miss one and the census reports the dependency tree's language instead of the project's,
    which is the failure `test_dependency_trees_do_not_decide_the_runtime` catches for exactly
    one of the fourteen.

    The rows come from `_CENSUS_SKIP` itself, so a fifteenth pruned name is covered when it is
    added. Each row asserts the consequence — three Python files buried under the name do not
    outvote the one TypeScript file that is really the project — never that the set contains
    the name, which is what the set is.

    Two things this table cannot prove on its own, both handled below:

    * the fixture has to be capable of going the other way, or every row is green because the
      files were never counted at all. `test_the_same_tree_is_python_under_a_name_nobody_prunes`
      is that control, and it is the specific mistake this repo has made three times —
      a fixture planted under a pruned name never reaches the line under test.
    * `.git`, `.next` and `.venv` are *also* pruned by the `d.startswith(".")` clause next to
      the membership check, so their rows stay green with `_CENSUS_SKIP` emptied out. They
      are covered here, but what covers them is the dot rule, pinned separately by
      `test_a_dot_directory_is_pruned_even_when_the_skip_list_never_names_it`.
    """

    def tree(self, directory):
        """One TypeScript file that is the project, three Python files that are not."""
        return {
            "src/app.ts": "export const x = 1;\n",
            directory + "/a.py": "a = 1\n",
            directory + "/b.py": "b = 2\n",
            directory + "/c.py": "c = 3\n",
        }

    def test_the_same_tree_is_python_under_a_name_nobody_prunes(self):
        """Control for the table below: the buried files really are countable."""
        self.assertNotIn("lib", detect_project._CENSUS_SKIP)
        self.assertEqual(detect_project.infer_runtime_from_sources(self.mk(self.tree("lib"))),
                         "python")

    def test_no_pruned_directory_contributes_to_the_census(self):
        self.assertTrue(detect_project._CENSUS_SKIP,
                        "the skip list is empty — every row below would be vacuous")
        for directory in sorted(detect_project._CENSUS_SKIP):
            with self.subTest(directory=directory):
                d = self.mk(self.tree(directory))
                self.assertEqual(detect_project.infer_runtime_from_sources(d), "nodejs")

    def test_pruning_applies_at_every_depth_not_just_the_repo_root(self):
        """A workspace member's `node_modules` is nested two levels down, and that is the
        shape the monorepo work put in front of this walk."""
        d = self.mk({
            "src/app.ts": "export const x = 1;\n",
            "packages/api/node_modules/dep/a.py": "a = 1\n",
            "packages/api/node_modules/dep/b.py": "b = 2\n",
            "packages/api/node_modules/dep/c.py": "c = 3\n",
        })
        self.assertEqual(detect_project.infer_runtime_from_sources(d), "nodejs")

    def test_a_dot_directory_is_pruned_even_when_the_skip_list_never_names_it(self):
        """The second half of the prune, and the reason three `_CENSUS_SKIP` rows above are
        double-covered. `.cache` is in no list anywhere; it is skipped because it starts with
        a dot. Naming it here keeps that rule attached to a test of its own rather than
        borrowing credit from the membership table.
        """
        self.assertNotIn(".cache", detect_project._CENSUS_SKIP)
        self.assertEqual(detect_project.infer_runtime_from_sources(self.mk(self.tree(".cache"))),
                         "nodejs")


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


class FrameworkTableTest(Base):
    """`detect_framework` is three ordered elif chains and twenty-two package names.

    `MobileDetectionTest` above reaches five of them. The rest pick the doc templates for
    every stack this repo does not itself use, so an entry that never matched would look
    exactly like a project that does not use that framework — silent either way.

    These are literal rows, not a registry loop, because the chains are inline `elif`s inside
    the function rather than a module-level table: there is nothing to drive off. Each row
    still asserts the answer rather than the branch, and the negative rows below pin the
    ordering, which is the part a table of single-dependency fixtures cannot see.
    """

    NODE_FRONTEND = [
        ("expo", "expo"),
        ("react-native", "react-native"),
        ("next", "nextjs"),
        ("nuxt", "nuxt"),
        ("react", "react"),
        ("vue", "vue"),
        ("svelte", "svelte"),
        ("angular", "angular"),
        ("@angular/core", "angular"),
    ]

    NODE_BACKEND = [
        ("express", "express"),
        ("fastify", "fastify"),
        ("nestjs", "nestjs"),
        ("@nestjs/core", "nestjs"),
        ("hono", "hono"),
    ]

    def test_every_frontend_dependency_names_its_framework(self):
        for dep, framework in self.NODE_FRONTEND:
            with self.subTest(dep=dep):
                d = self.mk({"package.json": self.pkg(**{dep: "1.0.0"})})
                self.assertEqual(detect_project.detect_framework(d, "nodejs")["frontend"],
                                 framework)

    def test_every_backend_dependency_names_its_framework(self):
        for dep, framework in self.NODE_BACKEND:
            with self.subTest(dep=dep):
                d = self.mk({"package.json": self.pkg(**{dep: "1.0.0"})})
                self.assertEqual(detect_project.detect_framework(d, "nodejs")["backend"],
                                 framework)

    def test_a_next_app_with_no_server_framework_is_credited_with_api_routes(self):
        d = self.mk({"package.json": self.pkg(next="15.0.0")})
        self.assertEqual(detect_project.detect_framework(d, "nodejs")["backend"],
                         "nextjs_api_routes")

    def test_a_real_server_framework_outranks_the_api_routes_guess(self):
        """Next.js can serve its own API, but if the app also ships Express that is what
        the deployment and API docs have to describe."""
        d = self.mk({"package.json": self.pkg(next="15.0.0", express="4.19.2")})
        self.assertEqual(detect_project.detect_framework(d, "nodejs")["backend"], "express")

    def test_a_runtime_the_detector_has_no_chain_for_claims_nothing(self):
        """The control on all of the above: `detect_framework` answers `None`/`None` rather
        than falling through to a default, so a green row means the chain ran."""
        d = self.mk({"package.json": self.pkg(react="18.3.1", express="4.19.2")})
        self.assertEqual(detect_project.detect_framework(d, "go"),
                         {"frontend": None, "backend": None})

    def test_a_malformed_package_json_is_not_a_crash(self):
        """A half-written manifest is a normal state for a repo mid-edit, and detection is
        run on whatever is on disk."""
        d = self.mk({"package.json": "{ not json at all"})
        self.assertEqual(detect_project.detect_framework(d, "nodejs"),
                         {"frontend": None, "backend": None})

    def test_a_node_runtime_inferred_without_a_manifest_claims_no_framework(self):
        """The census can call a repo `nodejs` from `.ts` files alone, with no package.json
        anywhere — so `detect_framework` is reached with the Node chain selected and nothing
        to read. It has to answer rather than raise."""
        d = self.mk({"src/app.ts": "export const x = 1;\n"})
        self.assertEqual(detect_project.detect_package_manager(d)["runtime"], "nodejs")
        self.assertEqual(detect_project.detect_framework(d, "nodejs"),
                         {"frontend": None, "backend": None})

    PYTHON_BACKENDS = [("django", "django"), ("fastapi", "fastapi"), ("flask", "flask")]

    def test_every_python_backend_is_found_in_either_dependency_file(self):
        """Both files are read and concatenated, so each framework has to be found from
        either one — a Poetry project declares in `pyproject.toml` and has no
        `requirements.txt` at all."""
        for token, framework in self.PYTHON_BACKENDS:
            for filename, body in (("requirements.txt", token + "==1.0\n"),
                                   ("pyproject.toml",
                                    "[project]\ndependencies = ['%s']\n" % token)):
                with self.subTest(framework=framework, declared_in=filename):
                    d = self.mk({filename: body})
                    self.assertEqual(detect_project.detect_framework(d, "python")["backend"],
                                     framework)

    def test_a_python_project_with_no_web_framework_claims_none(self):
        d = self.mk({"requirements.txt": "requests==2.32.3\n"})
        self.assertIsNone(detect_project.detect_framework(d, "python")["backend"])

    JVM_BACKENDS = [
        ("spring-boot-starter-web", "spring"),
        ("org.springframework.boot", "spring"),
        ("io.quarkus", "quarkus"),
        ("io.micronaut", "micronaut"),
        ("io.ktor", "ktor"),
    ]

    def test_every_jvm_backend_is_found_in_every_build_file_flavour(self):
        """One substring search over three build files is the whole design — Maven XML,
        Gradle Groovy and Gradle Kotlin without three parsers — so each token has to be
        found in whichever of the three the project actually ships."""
        for token, framework in self.JVM_BACKENDS:
            for filename in ("pom.xml", "build.gradle", "build.gradle.kts"):
                with self.subTest(framework=framework, build_file=filename):
                    d = self.mk({filename: "dependencies { %s }" % token})
                    self.assertEqual(detect_project.detect_framework(d, "jvm")["backend"],
                                     framework)


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

    def test_the_object_form_of_the_workspaces_field_counts_too(self):
        """Yarn's `{"packages": [...]}` spelling is as common as the array, and reading only
        the array form calls a workspace root a single package — after which code-graph has
        no cross-package imports to resolve and the docs describe one of the members."""
        d = self.mk({
            "package.json": json.dumps({"name": "root",
                                        "workspaces": {"packages": ["packages/*"]}}),
            "packages/domain/package.json": '{"name":"@x/domain"}',
        })
        self.assertEqual(detect_project.detect_package_manager(d)["workspace_tool"], "npm")

    def test_an_empty_workspaces_declaration_is_not_a_workspace_root(self):
        for declared in ([], {}, {"packages": []}, "packages/*"):
            with self.subTest(workspaces=declared):
                d = self.mk({"package.json": json.dumps({"name": "root",
                                                         "workspaces": declared})})
                self.assertFalse(detect_project.detect_package_manager(d).get("monorepo"))

    def test_comments_and_blank_lines_do_not_hide_the_packages_block(self):
        """Real `pnpm-workspace.yaml` files are commented, and the scanner reads them line by
        line rather than parsing YAML."""
        d = self.mk({
            "package.json": '{"name":"root"}',
            "pnpm-workspace.yaml": "# managed by the release tooling\n\n"
                                   "onlyBuiltDependencies:\n  - better-sqlite3\n\n"
                                   "packages:\n  # the apps\n  - 'apps/*'\n",
        })
        self.assertEqual(detect_project.detect_package_manager(d)["workspace_tool"], "pnpm")

    def test_a_malformed_package_json_is_not_a_monorepo_and_not_a_crash(self):
        """Detection runs on whatever is on disk, including a manifest mid-edit."""
        d = self.mk({"package.json": "{ name: not json"})
        self.assertFalse(detect_project.detect_package_manager(d).get("monorepo"))


class OrmDetectionTest(Base):
    def test_prisma_still_detected(self):
        d = self.mk({"prisma/schema.prisma": 'datasource db { provider = "postgresql" }'})
        self.assertEqual(detect_project.detect_database(d)["orm"], "prisma")

    def test_a_project_without_an_orm_says_so(self):
        self.assertIsNone(detect_project.detect_database(self.mk({}))["orm"])

    PRISMA_PROVIDERS = [("postgresql", "postgresql"), ("postgres", "postgresql"),
                        ("mysql", "mysql"), ("sqlite", "sqlite")]

    def test_the_prisma_provider_decides_the_database_type(self):
        """`DATABASE.md` is written from `type`, and only the schema says which engine it is."""
        for provider, expected in self.PRISMA_PROVIDERS:
            with self.subTest(provider=provider):
                d = self.mk({"prisma/schema.prisma":
                             'datasource db { provider = "%s" }' % provider})
                self.assertEqual(detect_project.detect_database(d),
                                 {"type": expected, "orm": "prisma"})

    def test_a_prisma_schema_naming_no_known_engine_reports_the_orm_and_no_type(self):
        """The control for the table above: `type` comes from the schema's text, not from
        the presence of the file."""
        d = self.mk({"prisma/schema.prisma": 'datasource db { provider = "cockroach" }'})
        self.assertEqual(detect_project.detect_database(d), {"type": None, "orm": "prisma"})

    ORM_FIXTURES = [
        ("drizzle.config.ts", "drizzle"),
        ("drizzle.config.js", "drizzle"),
        ("app/models.py", "django_orm"),
        ("app/db_models.py", "sqlalchemy"),
    ]

    def test_each_orm_signature_names_its_orm(self):
        for path, orm in self.ORM_FIXTURES:
            with self.subTest(path=path):
                d = self.mk({path: "x = 1\n"})
                self.assertEqual(detect_project.detect_database(d)["orm"], orm)

    def test_mongoose_reports_both_the_orm_and_the_engine(self):
        """The one dependency that names the database as well as the layer over it."""
        d = self.mk({"package.json": self.pkg(mongoose="8.5.0")})
        self.assertEqual(detect_project.detect_database(d),
                         {"type": "mongodb", "orm": "mongoose"})

    def test_a_malformed_package_json_does_not_abort_database_detection(self):
        d = self.mk({"package.json": "{ not json", "app/models.py": "x = 1\n"})
        self.assertEqual(detect_project.detect_database(d)["orm"], "django_orm")

    def test_an_explicit_schema_outranks_a_file_named_like_a_model(self):
        """A Prisma project with any `*models*.py` anywhere — a script, a fixture — must
        still report Prisma; the Python probes are a fallback, not an override."""
        d = self.mk({"prisma/schema.prisma": 'datasource db { provider = "sqlite" }',
                     "tools/models.py": "x = 1\n"})
        self.assertEqual(detect_project.detect_database(d),
                         {"type": "sqlite", "orm": "prisma"})


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

    def test_every_candidate_layout_is_found_when_it_is_the_one_present(self):
        """Rows off `DOC_DIR_CANDIDATES` itself, so a fourth convention added to the tuple
        is exercised the moment it is added rather than the next time someone remembers.

        The tests above name all three of today's entries by hand and would keep passing with
        a fourth added and never reached — which, for a reverse-sync that only starts from a
        directory it found, is the same silent from-scratch create that
        `test_the_toolkits_own_layout_is_found` exists to prevent.
        """
        self.assertTrue(detect_project.DOC_DIR_CANDIDATES,
                        "the candidate list is empty — every row below would be vacuous")
        for layout, relative in detect_project.DOC_DIR_CANDIDATES:
            with self.subTest(relative=relative):
                d = self.mk({os.path.join(relative, "GUIDE.md"): "# g\n"})
                found = detect_project.detect_existing_docs(d)
                self.assertEqual(found["layout"], layout)
                self.assertEqual(found["docs_dir"], os.path.join(d, relative))
                self.assertEqual(found["files"], ["GUIDE.md"])

    def test_a_directory_matching_no_candidate_is_not_documentation(self):
        """Control for the table above: the markdown is found because of where it sits, not
        because any directory holding a `.md` counts."""
        d = self.mk({"notes/GUIDE.md": "# g\n"})
        found = detect_project.detect_existing_docs(d)
        self.assertIsNone(found["docs_dir"])
        self.assertEqual(found["files"], [])

    ROOT_DOCUMENTS = ["README.md", "CLAUDE.md", "AGENTS.md", "CONTRIBUTING.md", "CHANGELOG.md"]

    def test_every_root_document_the_detector_looks_for_is_reported(self):
        """Five names, of which the tests above reach two. Each one is a file the docs run
        must not overwrite blind, so a name that stopped being found would hand the
        coordinator an empty slot where a hand-written document already lives.
        """
        for name in self.ROOT_DOCUMENTS:
            with self.subTest(document=name):
                d = self.mk({name: "# doc\n", "IGNORED.md": "# not a root document\n"})
                found = detect_project.detect_existing_docs(d)
                self.assertEqual(found["files"], [name])


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

    PYTHON_SIGNALS = [
        ("requirements.txt", "pytest-bdd==7.3.0\n", "pytest-bdd", "python:pytest-bdd"),
        ("requirements.txt", "pytest==8.3.2\n", "pytest", "python:pytest"),
        ("requirements.txt", "behave==1.2.6\n", "behave", "python:behave"),
        ("pyproject.toml", "[project]\ndependencies=['pytest']\n", "pytest", "python:pytest"),
        ("setup.cfg", "[options]\ntests_require = behave\n", "behave", "python:behave"),
        ("tox.ini", "[testenv]\ndeps = pytest\n", "pytest", "python:pytest"),
    ]

    def test_every_python_signal_is_read_from_every_declaration_file(self):
        """The Python half is four substring probes across four files, and the tests above
        reach one probe through one file. Each of the four files is where a real project
        declares its test dependencies — `tox.ini` and `setup.cfg` for anything predating
        `pyproject.toml` — and none of them was named.
        """
        for filename, body, runner, evidence in self.PYTHON_SIGNALS:
            with self.subTest(declared_in=filename, runner=runner):
                found = detect_project.detect_test_runners(self.mk({filename: body}))
                self.assertIn(runner, found["runners"])
                self.assertIn(evidence, found["evidence"])

    def test_a_malformed_package_json_still_lets_the_other_probes_answer(self):
        """The Node probe is first, and a manifest it cannot parse must not cost the caller
        the Python and Gherkin answers that follow it."""
        d = self.mk({"package.json": "{ not json", "requirements.txt": "pytest==8.3.2\n"})
        self.assertEqual(detect_project.detect_test_runners(d)["runners"], ["pytest"])

    def test_pytest_bdd_is_reported_alongside_pytest_rather_than_instead_of_it(self):
        """`pytest-bdd` contains the substring `pytest`, so both probes fire — and both
        answers are true: the suite is driven by pytest and its scenarios are Gherkin.
        Reporting only the BDD layer would lose the command that runs it."""
        found = detect_project.detect_test_runners(
            self.mk({"requirements.txt": "pytest-bdd==7.3.0\n"}))
        self.assertEqual(found["runners"], ["pytest", "pytest-bdd"])

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


class InfrastructureDetectionTest(Base):
    """`detect_infrastructure` had no test of any kind and never executed under the suite.

    It carries three registries — two containerisation signals, three CI providers and four
    hosting files — and every one of them decides whether `DEPLOYMENT.md` and
    `INFRASTRUCTURE.md` get written at all. A signal that stopped matching would read as
    "this project is not deployed anywhere", which is a plausible answer and therefore a
    silent one.
    """

    CONTAINERIZATION = [
        ("Dockerfile", "docker"),
        ("docker-compose.yml", "docker-compose"),
        ("docker-compose.yaml", "docker-compose"),
    ]

    CI_PROVIDERS = [
        (".github/workflows/ci.yml", "github_actions"),
        (".gitlab-ci.yml", "gitlab_ci"),
        (".circleci/config.yml", "circleci"),
    ]

    HOSTING = [
        ("vercel.json", "vercel"),
        ("netlify.toml", "netlify"),
        ("railway.json", "railway"),
        ("railway.toml", "railway"),
    ]

    def test_an_empty_project_claims_no_infrastructure(self):
        """The control for every table below: absence is reported as empty lists and a
        `None`, so a green row means the signal was found rather than assumed."""
        self.assertEqual(detect_project.detect_infrastructure(self.mk({})),
                         {"containerization": [], "hosting": [], "ci_cd": None})

    def test_each_containerization_signal_is_recognised(self):
        for filename, signal in self.CONTAINERIZATION:
            with self.subTest(filename=filename):
                d = self.mk({filename: "FROM scratch\n"})
                self.assertEqual(detect_project.detect_infrastructure(d)["containerization"],
                                 [signal])

    def test_each_ci_provider_is_recognised(self):
        for path, provider in self.CI_PROVIDERS:
            with self.subTest(path=path):
                d = self.mk({path: "steps: []\n"})
                self.assertEqual(detect_project.detect_infrastructure(d)["ci_cd"], provider)

    def test_each_hosting_signal_is_recognised(self):
        for filename, host in self.HOSTING:
            with self.subTest(filename=filename):
                d = self.mk({filename: "{}\n"})
                self.assertEqual(detect_project.detect_infrastructure(d)["hosting"], [host])

    def test_hosting_signals_accumulate_rather_than_shadowing_each_other(self):
        """A repo really can ship a `vercel.json` and a `railway.toml` — a preview
        deployment and a production one — and the deployment doc has to describe both."""
        d = self.mk({"vercel.json": "{}\n", "netlify.toml": "", "railway.json": "{}\n"})
        self.assertEqual(detect_project.detect_infrastructure(d)["hosting"],
                         ["vercel", "netlify", "railway"])

    def test_the_first_ci_provider_in_the_chain_wins(self):
        """`ci_cd` is a single value, so a repo mid-migration with two config files gets one
        answer, and which one is not arbitrary — the chain is ordered."""
        d = self.mk({".github/workflows/ci.yml": "steps: []\n",
                     ".gitlab-ci.yml": "stages: []\n",
                     ".circleci/config.yml": "jobs: {}\n"})
        self.assertEqual(detect_project.detect_infrastructure(d)["ci_cd"], "github_actions")

    def test_kubernetes_is_claimed_from_a_manifest_not_from_a_directory_name(self):
        d = self.mk({"k8s/deployment.yaml": "apiVersion: apps/v1\nkind: Deployment\n"})
        self.assertIn("kubernetes", detect_project.detect_infrastructure(d)["containerization"])

    def test_an_ordinary_yaml_file_is_not_kubernetes(self):
        """Every repo has YAML. Treating any of it as a cluster manifest would put a
        Kubernetes section into the infrastructure doc of a project that has never seen one.
        """
        d = self.mk({"config/settings.yaml": "log_level: debug\n"})
        self.assertEqual(detect_project.detect_infrastructure(d)["containerization"], [])

    def test_an_unreadable_yaml_file_does_not_abort_the_scan(self):
        """Detection runs over whatever is on disk, including a file it cannot decode, and
        the answer for the rest of the tree still has to arrive."""
        d = self.mk({"Dockerfile": "FROM scratch\n"})
        (Path(d) / "broken.yaml").write_bytes(b"\xfe\xff\x00binary")
        self.assertEqual(detect_project.detect_infrastructure(d)["containerization"],
                         ["docker"])


class NeededDocsTest(Base):
    """`get_needed_docs` is the list the whole docs run works from, and it never executed.

    Four documents are unconditional and four are earned by something the detectors found.
    A trigger that stopped firing does not fail — it produces a shorter list, and the
    coordinator writes the shorter set without noticing the API or database doc is missing.
    """

    ALWAYS = ["README.md", "ARCHITECTURE.md", "DEVELOPER.md", "STYLE_GUIDE.md", "SECURITY.md"]

    CONDITIONAL = [
        ({"database": {"type": "postgresql", "orm": None}}, ["DATABASE.md"]),
        ({"database": {"type": None, "orm": "prisma"}}, ["DATABASE.md"]),
        ({"framework": {"backend": "express"}}, ["API.md"]),
        ({"infrastructure": {"containerization": ["docker"]}},
         ["DEPLOYMENT.md", "INFRASTRUCTURE.md"]),
        ({"infrastructure": {"hosting": ["vercel"]}}, ["DEPLOYMENT.md", "INFRASTRUCTURE.md"]),
        ({"infrastructure": {"ci_cd": "github_actions"}},
         ["DEPLOYMENT.md", "INFRASTRUCTURE.md"]),
    ]

    def test_the_unconditional_documents_are_needed_by_a_project_with_nothing_detected(self):
        self.assertEqual(detect_project.get_needed_docs({}), self.ALWAYS)

    def test_each_trigger_earns_exactly_the_documents_it_is_responsible_for(self):
        """Rows assert the difference from the baseline above, so a row cannot pass on the
        strength of the four documents every project gets."""
        baseline = set(detect_project.get_needed_docs({}))
        for project_info, earned in self.CONDITIONAL:
            with self.subTest(trigger=sorted(project_info.items())[0][0],
                              detail=json.dumps(project_info, sort_keys=True)):
                needed = detect_project.get_needed_docs(project_info)
                self.assertEqual(sorted(set(needed) - baseline), sorted(earned))

    def test_a_fully_detected_project_earns_every_document(self):
        needed = detect_project.get_needed_docs({
            "database": {"type": "postgresql", "orm": "prisma"},
            "framework": {"backend": "nextjs_api_routes"},
            "infrastructure": {"containerization": ["docker"], "hosting": ["vercel"],
                               "ci_cd": "github_actions"},
        })
        self.assertEqual(sorted(needed), sorted(self.ALWAYS + [
            "DATABASE.md", "API.md", "DEPLOYMENT.md", "INFRASTRUCTURE.md"]))
        # No document is asked for twice: the docs run writes one file per entry, and a
        # duplicate would have it write, then overwrite, the same path.
        self.assertEqual(len(needed), len(set(needed)))

    def test_a_missing_section_is_not_a_crash(self):
        """`analyze_project` always supplies every key, but this is also called on the
        partial dictionaries a resumed or incremental run carries."""
        self.assertEqual(detect_project.get_needed_docs({"framework": {}, "database": {}}),
                         self.ALWAYS)


class AnalyzeProjectTest(Base):
    """`analyze_project` is the only function anything outside this module calls, and it had
    never run under the suite. It is a wiring seam: seven keys, each filled by one detector.

    The rows below are that wiring, and each asserts the observable thing — the value under
    the key equals what the detector for that key answers about the same directory. A key
    pointed at the wrong detector, or dropped from the result, fails a named row. Asserting
    the literal answers instead would restate the detector tests above and would still pass
    with two keys swapped.
    """

    PROJECT = {
        "package.json": json.dumps({
            "name": "app",
            "dependencies": {"next": "15.0.0", "react": "18.3.1"},
            "devDependencies": {"jest": "29.7.0"},
        }),
        "pnpm-lock.yaml": "lockfileVersion: '9.0'\n",
        "prisma/schema.prisma": 'datasource db { provider = "postgresql" }',
        "Dockerfile": "FROM node:22\n",
        ".github/workflows/ci.yml": "on: push\n",
        "knowledge-base/reference/ARCHITECTURE.md": "# Architecture\n",
        "README.md": "# app\n",
    }

    #: key -> the detector that owns it, called on the same directory.
    OWNERS = [
        ("runtime", lambda d: detect_project.detect_package_manager(d)),
        ("database", lambda d: detect_project.detect_database(d)),
        ("infrastructure", lambda d: detect_project.detect_infrastructure(d)),
        ("existing_docs", lambda d: detect_project.detect_existing_docs(d)),
        ("test_runners", lambda d: detect_project.detect_test_runners(d)),
    ]

    def test_every_key_carries_what_its_own_detector_answers(self):
        d = self.mk(self.PROJECT)
        results = detect_project.analyze_project(d)
        for key, detector in self.OWNERS:
            with self.subTest(key=key):
                self.assertEqual(results[key], detector(d))

    def test_the_framework_key_is_resolved_against_the_detected_runtime(self):
        """`detect_framework` needs the runtime as an argument, and passing the wrong one is
        silent — every chain in it is keyed on that string, so a mistake yields
        `{"frontend": None, "backend": None}`, which is what a plain project looks like.
        """
        d = self.mk(self.PROJECT)
        results = detect_project.analyze_project(d)
        self.assertEqual(results["framework"], detect_project.detect_framework(d, "nodejs"))
        self.assertEqual(results["framework"]["frontend"], "nextjs")

    def test_the_document_list_is_computed_from_the_detections_not_from_the_directory(self):
        """`get_needed_docs` reads the assembled result, so it sees the database and the
        CI provider the detectors just found. If it were handed the raw directory instead,
        every conditional document would drop out and nothing else here would notice.
        """
        d = self.mk(self.PROJECT)
        results = detect_project.analyze_project(d)
        self.assertEqual(results["needed_docs"], detect_project.get_needed_docs(results))
        for earned in ("DATABASE.md", "API.md", "DEPLOYMENT.md", "INFRASTRUCTURE.md"):
            with self.subTest(document=earned):
                self.assertIn(earned, results["needed_docs"])

    def test_a_bare_directory_still_returns_every_key(self):
        """The shape is the contract: a caller reading `results["database"]["orm"]` must not
        have to know whether anything was found."""
        results = detect_project.analyze_project(self.mk({}))
        for key in ("project_dir", "runtime", "framework", "database", "infrastructure",
                    "existing_docs", "needed_docs", "test_runners"):
            with self.subTest(key=key):
                self.assertIn(key, results)
        self.assertEqual(results["runtime"], {})
        self.assertEqual(results["needed_docs"], NeededDocsTest.ALWAYS)

    def test_a_relative_directory_is_reported_as_an_absolute_path(self):
        """Everything downstream joins paths onto `project_dir`, and the default argument is
        `"."` — so the one call that takes the default must not hand back a relative path.
        """
        d = self.mk(self.PROJECT)
        origin = os.getcwd()
        self.addCleanup(os.chdir, origin)
        os.chdir(d)
        results = detect_project.analyze_project()
        self.assertTrue(os.path.isabs(results["project_dir"]))
        self.assertEqual(results["project_dir"], os.getcwd())


class CliEntryPointTest(Base):
    """`main()` is how every skill actually reaches this module — the coordinator shells out
    and parses stdout. It had never executed, so "the detector works" and "the command works"
    were separate claims and only the first one was being made.
    """

    def run_main(self, argv):
        original = sys.argv
        sys.argv = argv
        buffer = io.StringIO()
        try:
            with contextlib.redirect_stdout(buffer):
                detect_project.main()
        finally:
            sys.argv = original
        return buffer.getvalue()

    def test_the_command_prints_the_analysis_as_parseable_json(self):
        """Stdout is the interface. Anything that makes it unparseable — a stray print, a
        value json cannot serialise — breaks every caller, and a detector test cannot see it.
        """
        d = self.mk(AnalyzeProjectTest.PROJECT)
        printed = self.run_main(["detect_project.py", d])
        self.assertEqual(json.loads(printed), detect_project.analyze_project(d))

    def test_the_command_defaults_to_the_working_directory(self):
        """Invoked with no argument — which is how the skill runs it from the project root."""
        d = self.mk(AnalyzeProjectTest.PROJECT)
        origin = os.getcwd()
        self.addCleanup(os.chdir, origin)
        os.chdir(d)
        printed = self.run_main(["detect_project.py"])
        self.assertEqual(json.loads(printed)["project_dir"], os.getcwd())


def _symlinks_are_creatable():
    """Can this process make a directory symlink at all?

    Windows needs `SeCreateSymbolicLinkPrivilege` for one, and a CI runner may not have it.
    Probed once rather than guessed from `os.name`, because Developer Mode grants it.
    """
    d = tempfile.mkdtemp()
    try:
        os.mkdir(os.path.join(d, "target"))
        os.symlink(os.path.join(d, "target"), os.path.join(d, "link"),
                   target_is_directory=True)
        return os.path.islink(os.path.join(d, "link"))
    except (OSError, NotImplementedError, AttributeError):
        return False
    finally:
        shutil.rmtree(d, ignore_errors=True)


SYMLINKS_CREATABLE = _symlinks_are_creatable()


def _islink_claiming(*names):
    """An `os.path.islink` that says True for these basenames and defers for everything else.

    This is what keeps the containment rows below from being a class that skips itself out of
    existence on a host with no symlink privilege. It also isolates the one clause under test:
    the entry is an ordinary directory, so `os.walk`'s own `followlinks=False` cannot be what
    refuses to descend it — only `_refuses_descent` can.
    """
    real = os.path.islink

    def fake(path):
        return os.path.basename(os.path.normpath(path)) in names or real(path)

    return fake


class WalkContainmentTest(Base):
    """SEC-008: the stack detector stays inside the tree it was pointed at.

    `glob.glob(..., recursive=True)` descends directory symlinks — measured identical on 3.9,
    3.12 and 3.13 — so a repository committing `vendor -> /` made this module read the
    operator's filesystem and take as long as that took. No cycle was needed; one link to a
    big tree was the whole vector.

    The accepted price, agreed before the change: a manifest reachable only through a
    symlinked directory is no longer detected. Every row is paired with a control that puts
    the same manifest somewhere ordinary, because a containment test whose fixture was never
    readable in the first place is green for the wrong reason.
    """

    MANIFEST = "apiVersion: apps/v1\nkind: Deployment\n"

    def containerization(self, directory):
        return detect_project.detect_infrastructure(directory)["containerization"]

    def outside_and_project(self):
        """A project directory with a sibling — not a child — holding a real manifest."""
        parent = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, parent, ignore_errors=True)
        outside = Path(parent) / "outside" / "sub"
        outside.mkdir(parents=True)
        (outside / "app.yaml").write_text(self.MANIFEST, encoding="utf-8")
        project = Path(parent) / "proj"
        project.mkdir()
        return outside, project

    def test_the_control_a_manifest_inside_the_project_is_detected(self):
        """Without this row every refusal below is satisfied by "nothing is ever detected"."""
        d = self.mk({"deploy/app.yaml": self.MANIFEST})
        self.assertIn("kubernetes", self.containerization(d))

    def test_a_directory_the_walk_reads_as_a_symlink_is_never_descended(self):
        """The portable half, and the one that carries the proof on Windows."""
        d = self.mk({"linkdir/app.yaml": self.MANIFEST})
        self.assertIn("kubernetes", self.containerization(d))
        with mock.patch("os.path.islink", _islink_claiming("linkdir")):
            self.assertEqual(self.containerization(d), [])

    def test_the_modules_own_refusal_is_what_prunes_a_symlinked_directory(self):
        """The row above cannot tell which of two redundant guards did the work.

        `os.walk` refuses a symlinked directory by itself, because `followlinks` defaults to
        False, and it re-reads `os.path.islink` while it recurses — so with the default in
        place the explicit `_refuses_descent` prune can be deleted and every other row here
        stays green. A redundant guard nobody can falsify is a guard that gets deleted by the
        next reader. This row forces `followlinks=True` so that `walk_project`'s own refusal
        is the only thing left that can prune, and pairs it with the same walk unpatched.
        """
        d = self.mk({"linkdir/app.yaml": self.MANIFEST})
        real_walk = os.walk

        def always_descend(top, **kwargs):
            kwargs["followlinks"] = True
            return real_walk(top, **kwargs)

        with mock.patch("os.walk", always_descend):
            self.assertIn("kubernetes", self.containerization(d))
            with mock.patch("os.path.islink", _islink_claiming("linkdir")):
                self.assertEqual(self.containerization(d), [])

    def test_a_file_the_walk_reads_as_a_symlink_is_never_opened(self):
        """The file half of the same trick, portably. A `*.yaml` that is itself a link is the
        way out of the tree that pruning directories does not close — and in text mode
        `link.yaml -> /dev/zero` is an endless source, which is the MemoryError the bare
        `except:` used to swallow.
        """
        d = self.mk({"deploy/app.yaml": self.MANIFEST})
        self.assertIn("kubernetes", self.containerization(d))
        with mock.patch("os.path.islink", _islink_claiming("app.yaml")):
            self.assertEqual(self.containerization(d), [])

    @unittest.skipUnless(SYMLINKS_CREATABLE, "this host cannot create a symlink")
    def test_a_manifest_reached_only_through_a_symlinked_directory_is_not_detected(self):
        """The accepted behavior change, against a real link rather than a claimed one.

        Two clauses have to be removed together to turn this red — the `_refuses_descent`
        prune and `followlinks=False` — because they are deliberately redundant. The row
        above is what proves the prune alone is load-bearing.
        """
        outside, project = self.outside_and_project()
        os.symlink(str(outside.parent), str(project / "linkdir"), target_is_directory=True)
        self.assertEqual(self.containerization(str(project)), [])

        (project / "deploy").mkdir()
        (project / "deploy" / "app.yaml").write_text(self.MANIFEST, encoding="utf-8")
        self.assertIn("kubernetes", self.containerization(str(project)))

    @unittest.skipUnless(SYMLINKS_CREATABLE, "this host cannot create a symlink")
    def test_a_yaml_that_is_itself_a_symlink_out_of_the_tree_is_not_read(self):
        """Deliberately a link to an ordinary manifest and not to `/dev/zero`: the claim is
        containment, and an out-of-memory test would prove it by dying."""
        outside, project = self.outside_and_project()
        os.symlink(str(outside / "app.yaml"), str(project / "app.yaml"))
        self.assertEqual(self.containerization(str(project)), [])


class InfrastructureReadTest(Base):
    """What `detect_infrastructure` opens, how much of it, and what it does when a read fails.

    The handler replaced here was the last literal bare `except:` in the tree, and it hid
    everything from a permission error to MemoryError.
    """

    def test_a_yaml_that_is_not_valid_utf8_is_skipped_rather_than_fatal(self):
        """The correction to SEC-008's own remediation, which said to swap the bare `except:`
        for `except OSError` over the same text read. `open(path, 'r')` decodes with the
        platform encoding, so one undecodable byte raises UnicodeDecodeError — a ValueError,
        not an OSError — and that repair would have turned a swallowed error into an uncaught
        traceback out of `analyze_project` with no JSON on stdout. Reading bytes is what makes
        `except OSError` sufficient.

        Sorted walk order reaches `a-bad.yaml` first, so this also proves the scan carried on
        past the file it could not read rather than stopping there.
        """
        d = self.mk({"b-good.yaml": "apiVersion: v1\nkind: Pod\n"})
        (Path(d) / "a-bad.yaml").write_bytes(b"\xff\xfe not text\n")
        self.assertIn("kubernetes",
                      detect_project.detect_infrastructure(d)["containerization"])

    def test_only_the_first_64k_of_a_yaml_is_examined(self):
        """The per-file cap, in both directions.

        The miss in the first row is deliberate and is documented on `_YAML_PREFIX`: a
        manifest that puts 64 KiB in front of a required top-level key is not worth an
        unbounded read of every YAML file in a repository. The second row is what stops the
        first being satisfied by "nothing is ever detected".
        """
        rows = [
            ("past the prefix", detect_project._YAML_PREFIX + 4096, False),
            ("inside the prefix", detect_project._YAML_PREFIX - 100, True),
        ]
        for name, offset, expected in rows:
            with self.subTest(name):
                d = self.mk({})
                padding = b"# " + b"p" * (offset - 3) + b"\n"
                (Path(d) / "big.yaml").write_bytes(padding + b"apiVersion: v1\n")
                found = detect_project.detect_infrastructure(d)["containerization"]
                self.assertEqual("kubernetes" in found, expected)

    def test_the_tree_is_walked_once_not_twice(self):
        """The guard this replaced re-ran the identical whole-tree glob whenever the repo held
        YAML and had no `k8s/` directory, and decided nothing with it — the loop it guarded is
        already empty when the traversal is.
        """
        d = self.mk({"config/settings.yaml": "log_level: debug\n"})
        self.assertFalse(os.path.exists(os.path.join(d, "k8s")))
        with mock.patch.object(detect_project, "walk_project",
                               wraps=detect_project.walk_project) as walk:
            detect_project.detect_infrastructure(d)
        self.assertEqual(walk.call_count, 1)

    def test_the_extension_test_no_longer_depends_on_the_platform(self):
        """`glob` matched through `os.path.normcase`, so `APP.YAML` was examined on Windows
        and skipped on POSIX. One answer everywhere is worth more than either of them."""
        d = self.mk({"deploy/APP.YAML": "apiVersion: v1\n"})
        self.assertIn("kubernetes",
                      detect_project.detect_infrastructure(d)["containerization"])


class WalkPruningTest(Base):
    """What the bounded walk refuses to look at, and what each refusal is worth.

    Two separate rules do the pruning and they need separate rows, or one covers for the
    other: membership in `_CENSUS_SKIP`, and the leading dot. The dot rule is the one the
    switch from `glob` to `os.walk` had to *keep* to stay a refactor — `glob` never returned
    anything under `.git`, and `os.walk` walks straight in, so leaving it out would have made
    the repair widen the very read surface the finding is about.
    """

    MANIFEST = "apiVersion: apps/v1\nkind: Deployment\n"

    def test_the_control_the_same_manifest_under_an_ordinary_name_is_found(self):
        self.assertNotIn("lib", detect_project._CENSUS_SKIP)
        d = self.mk({"lib/chart/app.yaml": self.MANIFEST})
        self.assertIn("kubernetes",
                      detect_project.detect_infrastructure(d)["containerization"])

    def test_no_pruned_directory_can_claim_the_project_runs_on_kubernetes(self):
        self.assertTrue(detect_project._CENSUS_SKIP,
                        "the skip list is empty — every row below would be vacuous")
        for directory in sorted(detect_project._CENSUS_SKIP):
            with self.subTest(directory=directory):
                d = self.mk({directory + "/chart/app.yaml": self.MANIFEST})
                self.assertEqual(
                    detect_project.detect_infrastructure(d)["containerization"], [])

    def test_a_dot_directory_is_never_walked_into(self):
        """`.cache` is named in no list anywhere; it is skipped for its leading dot alone."""
        self.assertNotIn(".cache", detect_project._CENSUS_SKIP)
        d = self.mk({".cache/app.yaml": self.MANIFEST})
        self.assertEqual(detect_project.detect_infrastructure(d)["containerization"], [])


class WalkBoundsTest(Base):
    """The caps are load-bearing, not decorative. Each row is paired with the same tree under
    a cap that admits it, because a bound proves nothing without the case it lets through.
    """

    def test_the_walk_stops_at_its_file_limit(self):
        d = self.mk({"f%02d.txt" % i: "" for i in range(10)})
        self.assertEqual(len(list(detect_project.walk_project(d, limit=3))), 3)
        self.assertEqual(len(list(detect_project.walk_project(d))), 10)

    def test_the_yaml_scan_stops_at_its_file_cap(self):
        """Five YAML files where only the last in sorted order carries the key, so the cap is
        what decides the answer rather than the contents."""
        files = {"a%d.yaml" % i: "log: %d\n" % i for i in range(4)}
        files["z.yaml"] = "apiVersion: v1\n"
        d = self.mk(files)
        with mock.patch.object(detect_project, "_YAML_FILE_CAP", 2):
            self.assertEqual(detect_project.detect_infrastructure(d)["containerization"], [])
        with mock.patch.object(detect_project, "_YAML_FILE_CAP", 10):
            self.assertIn("kubernetes",
                          detect_project.detect_infrastructure(d)["containerization"])

    def test_the_yaml_scan_stops_at_its_whole_scan_byte_budget(self):
        """The file cap alone still allows 500 x 64 KiB. The budget is the second ceiling, and
        it is spent on bytes actually read rather than on files counted."""
        d = self.mk({"a.yaml": "log: one\n", "z.yaml": "apiVersion: v1\n"})
        with mock.patch.object(detect_project, "_YAML_BYTE_BUDGET", 5):
            self.assertEqual(detect_project.detect_infrastructure(d)["containerization"], [])
        self.assertIn("kubernetes",
                      detect_project.detect_infrastructure(d)["containerization"])

    def test_the_shipped_ceilings_are_the_ones_the_rows_above_only_simulate(self):
        """Every row above injects its own cap, so all three prove the mechanism and none of
        them pins the number that ships. Measured 2026-08-23: setting `_WALK_FILE_LIMIT`,
        `_YAML_FILE_CAP` and `_YAML_BYTE_BUDGET` to `10 ** 15` left this module at 115 passed,
        i.e. the unbounded traversal SEC-008 is about was one token away with the suite green.
        Setting them to 1 was green too, which is the same hole from the other end.

        The assertions are relationships, not the literals, so retuning a ceiling stays a
        one-line change and removing one does not.
        """
        walk = detect_project._WALK_FILE_LIMIT
        files = detect_project._YAML_FILE_CAP
        budget = detect_project._YAML_BYTE_BUDGET
        for name, value in (("_WALK_FILE_LIMIT", walk), ("_YAML_FILE_CAP", files),
                            ("_YAML_BYTE_BUDGET", budget)):
            with self.subTest(name):
                self.assertIsInstance(value, int)

        # The claim `_WALK_FILE_LIMIT`'s own comment makes, as an assertion.
        self.assertEqual(walk, substrate.CENSUS_LIMIT)

        # A cap larger than the walk that feeds it is not a cap; below about fifty files a
        # rendered Helm chart or a kustomize overlay tree stops being examined to the end,
        # and `apiVersion` can be in the last file in sorted order.
        self.assertLessEqual(files, walk)
        self.assertGreaterEqual(files, 50)

        # The budget is the *second* ceiling and only means something strictly under what the
        # file cap alone already permits — the row above says so in prose. At the other end it
        # has to pay for the cap at a kilobyte a manifest, or the file cap is dead code.
        self.assertLess(budget, files * detect_project._YAML_PREFIX)
        self.assertGreaterEqual(budget, files * 1024)


class VendoredTreeContainmentTest(Base):
    """The four `**` globs SEC-008 did not name.

    The finding described `**/*.yaml`. `**/models.py`, `**/*models*.py`, `**/test_*.py` /
    `**/*_test.py` and `**/*.feature` were the identical defect under a different pattern
    string — a committed `vendor -> /` made every one of them walk the operator's filesystem
    — so all five were routed through the same bounded walk.

    That changes their answers on real repositories, and this class is that change written
    down: a vendored Django is not this project's ORM, and a dependency's test files are not
    this project's test runner. It is the judgement `infer_runtime_from_sources` has always
    made about the same directories, applied to the other four traversals.
    """

    def test_a_vendored_models_py_no_longer_names_the_orm(self):
        self.assertEqual(
            detect_project.detect_database(self.mk({"app/models.py": "x = 1\n"}))["orm"],
            "django_orm")
        d = self.mk({"node_modules/dj/models.py": "x = 1\n"})
        self.assertIsNone(detect_project.detect_database(d)["orm"])

    def test_a_vendored_sqlalchemy_model_no_longer_names_the_orm(self):
        self.assertEqual(
            detect_project.detect_database(self.mk({"app/user_models.py": "x = 1\n"}))["orm"],
            "sqlalchemy")
        d = self.mk({"vendor/pkg/user_models.py": "x = 1\n"})
        self.assertIsNone(detect_project.detect_database(d)["orm"])

    def test_a_vendored_test_file_no_longer_names_the_runner(self):
        self.assertIn("unittest", detect_project.detect_test_runners(
            self.mk({"tests/test_app.py": "x = 1\n"}))["runners"])
        d = self.mk({"node_modules/pkg/test_app.py": "x = 1\n"})
        self.assertEqual(detect_project.detect_test_runners(d)["runners"], [])

    def test_both_unittest_file_spellings_are_still_recognised(self):
        """Two globs became one predicate, and that is exactly where a spelling gets lost."""
        for name in ("tests/test_app.py", "tests/app_test.py"):
            with self.subTest(name):
                d = self.mk({name: "x = 1\n"})
                self.assertIn("unittest", detect_project.detect_test_runners(d)["runners"])

    def test_a_vendored_feature_file_no_longer_names_gherkin(self):
        self.assertIn("gherkin", detect_project.detect_test_runners(
            self.mk({"features/login.feature": "Feature: login\n"}))["runners"])
        d = self.mk({"node_modules/pkg/x.feature": "Feature: x\n"})
        self.assertEqual(detect_project.detect_test_runners(d)["runners"], [])


class CaseFoldedMatchTest(Base):
    """The narrowing the switch away from `glob` did not mean to make, and the choice about it.

    `glob` matches through `os.path.normcase`. On Windows that made all four of these
    patterns case-insensitive, and `**/models.py` is a literal — resolved by `_glob0`/
    `_lexists` rather than by `fnmatch` — so it was case-insensitive on default macOS APFS as
    well. The predicates that replaced them were case-sensitive on every host, which is a
    silent behaviour change on two platforms of three in the direction that loses answers.

    Measured 2026-08-23 on this APFS host, fixture `app/Models.py`:
    `glob.glob(d + "/**/models.py", recursive=True)` returned `['.../app/models.py']` while
    `detect_database(d)["orm"]` returned `None` where it had returned `"django_orm"`. The
    three wildcard patterns were already case-sensitive on POSIX, so on macOS the loss was
    that one; on Windows it was all four.

    The decision recorded here is to fold everywhere, matching the call
    `test_the_extension_test_no_longer_depends_on_the_platform` records for `**/*.yaml` a
    class above. The accepted cost is the other direction on POSIX: these four now match
    names `glob` did not, so `Models.py` alone names the Django ORM where it previously named
    nothing. Detection is a heuristic whose false positive costs one wrong section in a
    generated document; an answer that depends on the host costs more than that.
    """

    def test_the_predicate_is_handed_a_folded_name(self):
        """The fold is in `any_project_file` and nowhere else, which is what lets the four
        predicates stay written against lower-case literals — and what makes a fifth predicate
        written against an upper-case one silently dead. This row is where that is said."""
        seen = []
        detect_project.any_project_file(
            self.mk({"pkg/README.MD": ""}), lambda n: seen.append(n) or False)
        self.assertEqual(seen, ["readme.md"])

    def test_an_upper_cased_name_is_read_the_same_way_on_every_host(self):
        def orm(d):
            return detect_project.detect_database(d)["orm"]

        def runners(d):
            return detect_project.detect_test_runners(d)["runners"]

        rows = [
            ("app/Models.py", orm, "django_orm"),
            ("app/User_Models.PY", orm, "sqlalchemy"),
            ("tests/Test_App.PY", runners, ["unittest"]),
            ("tests/App_Test.PY", runners, ["unittest"]),
            ("features/Login.FEATURE", runners, ["gherkin"]),
        ]
        for name, call, expected in rows:
            with self.subTest(name):
                self.assertEqual(call(self.mk({name: "x = 1\n"})), expected)


if __name__ == "__main__":
    unittest.main(verbosity=2)
