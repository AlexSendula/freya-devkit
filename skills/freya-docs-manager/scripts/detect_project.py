#!/usr/bin/env python3
"""
Project detection script for docs-manager skill.
Analyzes the codebase to detect project type, tech stack, and relevant documentation needs.
"""

import json
import os
import sys
from pathlib import Path


def detect_package_manager(project_dir: str) -> dict:
    """Detect package manager and runtime."""
    results = {}

    # Check for Node.js
    if os.path.exists(os.path.join(project_dir, "package.json")):
        results["runtime"] = "nodejs"
        if os.path.exists(os.path.join(project_dir, "pnpm-lock.yaml")):
            results["package_manager"] = "pnpm"
        elif os.path.exists(os.path.join(project_dir, "yarn.lock")):
            results["package_manager"] = "yarn"
        elif os.path.exists(os.path.join(project_dir, "bun.lockb")):
            results["package_manager"] = "bun"
        else:
            results["package_manager"] = "npm"

    # Check for Python
    elif os.path.exists(os.path.join(project_dir, "pyproject.toml")):
        results["runtime"] = "python"
        if os.path.exists(os.path.join(project_dir, "poetry.lock")):
            results["package_manager"] = "poetry"
        else:
            results["package_manager"] = "pip"
    elif os.path.exists(os.path.join(project_dir, "requirements.txt")):
        results["runtime"] = "python"
        results["package_manager"] = "pip"

    # Check for Go
    elif os.path.exists(os.path.join(project_dir, "go.mod")):
        results["runtime"] = "go"
        results["package_manager"] = "go_modules"

    # Check for Rust
    elif os.path.exists(os.path.join(project_dir, "Cargo.toml")):
        results["runtime"] = "rust"
        results["package_manager"] = "cargo"

    # Check for PHP
    elif os.path.exists(os.path.join(project_dir, "composer.json")):
        results["runtime"] = "php"
        results["package_manager"] = "composer"

    # Check for JVM. Java is the language that prompted the polyglot work, and it was the
    # one stack this detector could not see at all — a Maven or Gradle repo reported no
    # runtime, so every downstream question had nothing to answer from.
    elif os.path.exists(os.path.join(project_dir, "pom.xml")):
        results["runtime"] = "jvm"
        results["package_manager"] = "maven"
    elif any(os.path.exists(os.path.join(project_dir, f))
             for f in ("build.gradle", "build.gradle.kts", "settings.gradle",
                       "settings.gradle.kts")):
        results["runtime"] = "jvm"
        results["package_manager"] = "gradle"

    # No manifest anywhere. Fall back to counting source files, because "this project does
    # not declare a manifest" is not the same as "this project has no language" — freya-devkit
    # itself is fifty Python files with no pyproject.toml, and plenty of tool and plugin repos
    # look the same. Flagged as `runtime_source` so a caller can tell an inference from a
    # declaration.
    if not results.get("runtime"):
        inferred = infer_runtime_from_sources(project_dir)
        if inferred:
            results["runtime"] = inferred
            results["runtime_source"] = "file-extensions"

    workspace_tool = detect_workspace_tool(project_dir)
    if workspace_tool:
        results["monorepo"] = True
        results["workspace_tool"] = workspace_tool

    return results


_RUNTIME_BY_EXT = {
    ".py": "python", ".ts": "nodejs", ".tsx": "nodejs", ".js": "nodejs", ".jsx": "nodejs",
    ".go": "go", ".rs": "rust", ".java": "jvm", ".kt": "jvm", ".scala": "jvm",
    ".rb": "ruby", ".php": "php", ".cs": "dotnet", ".swift": "swift",
}

_CENSUS_SKIP = {
    "node_modules", ".git", "dist", "build", "out", ".next", "__pycache__", "venv", ".venv",
    "vendor", "target", "coverage", "knowledge-base", "graphify-out",
}


def infer_runtime_from_sources(project_dir: str, limit: int = 5000):
    """The runtime implied by the files actually present, or None."""
    counts = {}
    seen = 0
    for root, dirs, filenames in os.walk(project_dir):
        dirs[:] = [d for d in dirs if d not in _CENSUS_SKIP and not d.startswith(".")]
        for filename in filenames:
            runtime = _RUNTIME_BY_EXT.get(os.path.splitext(filename)[1].lower())
            if not runtime:
                continue
            counts[runtime] = counts.get(runtime, 0) + 1
            seen += 1
            if seen >= limit:
                break
        if seen >= limit:
            break
    if not counts:
        return None
    # Sorted by name on a tie so the answer does not depend on walk order.
    return max(sorted(counts), key=lambda r: counts[r])


def detect_workspace_tool(project_dir: str):
    """Which tool declares this repo's workspaces, or None if it is a single package.

    Worth knowing on its own — docs for a monorepo describe a different thing — and it is the
    same question code-graph answers to resolve cross-package imports.
    """
    package_json = os.path.join(project_dir, "package.json")
    if os.path.exists(package_json):
        try:
            with open(package_json, 'r') as f:
                declared = json.load(f).get("workspaces")
        except (json.JSONDecodeError, OSError):
            declared = None
        if isinstance(declared, list) and declared:
            return "npm"
        if isinstance(declared, dict) and declared.get("packages"):
            return "npm"

    pnpm = os.path.join(project_dir, "pnpm-workspace.yaml")
    if os.path.exists(pnpm):
        try:
            lines = open(pnpm, 'r', encoding="utf-8").read().splitlines()
        except OSError:
            lines = []
        in_packages = False
        for line in lines:
            stripped = line.strip()
            if not stripped or stripped.startswith("#"):
                continue
            if not line[:1].isspace():
                # A pnpm-workspace.yaml declaring only build settings — which the testbed
                # has — is not a workspace root.
                in_packages = stripped.startswith("packages:")
                continue
            if in_packages and stripped.startswith("- "):
                return "pnpm"

    return None


def detect_framework(project_dir: str, runtime: str) -> dict:
    """Detect framework based on runtime and dependencies."""
    results = {"frontend": None, "backend": None}

    if runtime == "nodejs":
        package_json_path = os.path.join(project_dir, "package.json")
        if os.path.exists(package_json_path):
            try:
                with open(package_json_path, 'r') as f:
                    pkg = json.load(f)
                    deps = {**pkg.get("dependencies", {}), **pkg.get("devDependencies", {})}

                    # Frontend frameworks. Most specific first: an Expo app has expo,
                    # react-native AND react in its dependencies, so checking react first
                    # would call a mobile app a web app and pick web doc templates for it.
                    if "expo" in deps:
                        results["frontend"] = "expo"
                    elif "react-native" in deps:
                        results["frontend"] = "react-native"
                    elif "next" in deps:
                        results["frontend"] = "nextjs"
                    elif "nuxt" in deps:
                        results["frontend"] = "nuxt"
                    elif "react" in deps:
                        results["frontend"] = "react"
                    elif "vue" in deps:
                        results["frontend"] = "vue"
                    elif "svelte" in deps:
                        results["frontend"] = "svelte"
                    elif "angular" in deps or "@angular/core" in deps:
                        results["frontend"] = "angular"

                    # Backend frameworks
                    if "express" in deps:
                        results["backend"] = "express"
                    elif "fastify" in deps:
                        results["backend"] = "fastify"
                    elif "nestjs" in deps or "@nestjs/core" in deps:
                        results["backend"] = "nestjs"
                    elif "hono" in deps:
                        results["backend"] = "hono"

                    # Full-stack detection
                    if "next" in deps and not results["backend"]:
                        # Next.js can be full-stack with API routes
                        results["backend"] = "nextjs_api_routes"
            except (json.JSONDecodeError, FileNotFoundError):
                pass

    elif runtime == "python":
        # Check for common Python frameworks
        requirements_path = os.path.join(project_dir, "requirements.txt")
        pyproject_path = os.path.join(project_dir, "pyproject.toml")

        deps_text = ""
        if os.path.exists(requirements_path):
            with open(requirements_path, 'r') as f:
                deps_text = f.read().lower()
        if os.path.exists(pyproject_path):
            with open(pyproject_path, 'r') as f:
                deps_text += f.read().lower()

        if "django" in deps_text:
            results["backend"] = "django"
        elif "fastapi" in deps_text:
            results["backend"] = "fastapi"
        elif "flask" in deps_text:
            results["backend"] = "flask"

    elif runtime == "jvm":
        # Read the build file as text rather than parsing XML or Groovy: the question is only
        # which framework is on the classpath, and the same substring works for Maven, Gradle
        # Groovy and Gradle Kotlin without three parsers.
        deps_text = ""
        for name in ("pom.xml", "build.gradle", "build.gradle.kts"):
            path = os.path.join(project_dir, name)
            if os.path.exists(path):
                try:
                    with open(path, 'r', encoding="utf-8", errors="replace") as f:
                        deps_text += f.read().lower()
                except OSError:
                    pass

        if "spring-boot" in deps_text or "springframework" in deps_text:
            results["backend"] = "spring"
        elif "quarkus" in deps_text:
            results["backend"] = "quarkus"
        elif "micronaut" in deps_text:
            results["backend"] = "micronaut"
        elif "io.ktor" in deps_text:
            results["backend"] = "ktor"

    return results


def detect_database(project_dir: str) -> dict:
    """Detect database type from configuration files."""
    results = {"type": None, "orm": None}

    # Check for Prisma
    if os.path.exists(os.path.join(project_dir, "prisma", "schema.prisma")):
        results["orm"] = "prisma"
        # Parse schema to detect database type
        try:
            with open(os.path.join(project_dir, "prisma", "schema.prisma"), 'r') as f:
                content = f.read()
                if 'postgresql' in content or 'postgres' in content:
                    results["type"] = "postgresql"
                elif 'mysql' in content:
                    results["type"] = "mysql"
                elif 'sqlite' in content:
                    results["type"] = "sqlite"
        except FileNotFoundError:
            pass

    # Check for Drizzle
    elif any(os.path.exists(os.path.join(project_dir, f)) for f in ["drizzle.config.ts", "drizzle.config.js"]):
        results["orm"] = "drizzle"

    # Check for Django models
    if glob_search(project_dir, "**/models.py"):
        if results["orm"] is None:
            results["orm"] = "django_orm"

    # Check for SQLAlchemy
    if glob_search(project_dir, "**/*models*.py"):
        results["orm"] = results["orm"] or "sqlalchemy"

    # Check for mongoose (MongoDB)
    package_json = os.path.join(project_dir, "package.json")
    if os.path.exists(package_json):
        try:
            with open(package_json, 'r') as f:
                pkg = json.load(f)
                deps = {**pkg.get("dependencies", {}), **pkg.get("devDependencies", {})}
                if "mongoose" in deps:
                    results["type"] = "mongodb"
                    results["orm"] = "mongoose"
        except (json.JSONDecodeError, FileNotFoundError):
            pass

    return results


def glob_search(directory: str, pattern: str) -> list:
    """Simple glob search helper."""
    import glob as g
    return g.glob(os.path.join(directory, pattern), recursive=True)


def detect_infrastructure(project_dir: str) -> dict:
    """Detect infrastructure and deployment setup."""
    results = {"containerization": [], "hosting": [], "ci_cd": None}

    # Containerization
    if os.path.exists(os.path.join(project_dir, "Dockerfile")):
        results["containerization"].append("docker")
    if os.path.exists(os.path.join(project_dir, "docker-compose.yml")) or \
       os.path.exists(os.path.join(project_dir, "docker-compose.yaml")):
        results["containerization"].append("docker-compose")

    # Kubernetes
    if os.path.exists(os.path.join(project_dir, "k8s")) or \
       glob_search(project_dir, "**/*.yaml"):
        for f in glob_search(project_dir, "**/*.yaml"):
            try:
                with open(f, 'r') as file:
                    if "apiVersion" in file.read():
                        results["containerization"].append("kubernetes")
                        break
            except:
                pass

    # CI/CD
    if os.path.exists(os.path.join(project_dir, ".github", "workflows")):
        results["ci_cd"] = "github_actions"
    elif os.path.exists(os.path.join(project_dir, ".gitlab-ci.yml")):
        results["ci_cd"] = "gitlab_ci"
    elif os.path.exists(os.path.join(project_dir, ".circleci")):
        results["ci_cd"] = "circleci"

    # Hosting indicators
    if os.path.exists(os.path.join(project_dir, "vercel.json")):
        results["hosting"].append("vercel")
    if os.path.exists(os.path.join(project_dir, "netlify.toml")):
        results["hosting"].append("netlify")
    if os.path.exists(os.path.join(project_dir, "railway.json")) or \
       os.path.exists(os.path.join(project_dir, "railway.toml")):
        results["hosting"].append("railway")

    return results


def detect_test_runners(project_dir: str) -> dict:
    """Detect available test runners/frameworks — stateless, on demand.

    Returns {"runners": [...], "evidence": [...]}. An **empty** runners list is
    a valid, explicit answer (the project has no detectable test tooling) — the
    Behavior Layer treats "none" as a loud result, not a missing one. No state
    is persisted; callers re-run detection whenever they need it.
    """
    runners = set()
    evidence = []

    # --- Node / JS: package.json dependencies ---
    pkg_path = os.path.join(project_dir, "package.json")
    if os.path.exists(pkg_path):
        try:
            with open(pkg_path, "r") as f:
                pkg = json.load(f)
            deps = {**pkg.get("dependencies", {}), **pkg.get("devDependencies", {})}
            dep_map = {
                "jest": "jest",
                "vitest": "vitest",
                "mocha": "mocha",
                "jasmine": "jasmine",
                "cypress": "cypress",
                "@playwright/test": "playwright",
                "playwright": "playwright",
                "@cucumber/cucumber": "cucumber",
                "cucumber": "cucumber",
                "jest-cucumber": "cucumber",
            }
            for dep, runner in dep_map.items():
                if dep in deps:
                    runners.add(runner)
                    evidence.append(f"package.json:{dep}")
        except (json.JSONDecodeError, OSError):
            pass

    # --- JS config files (a runner configured without an explicit dep entry) ---
    config_globs = {
        "jest": ["jest.config.*"],
        "vitest": ["vitest.config.*"],
        "playwright": ["playwright.config.*"],
        "cypress": ["cypress.config.*", "cypress.json"],
        "mocha": [".mocharc*"],
    }
    for runner, patterns in config_globs.items():
        for pat in patterns:
            if glob_search(project_dir, pat):
                runners.add(runner)
                evidence.append(f"config:{pat}")
                break

    # --- Python ---
    py_text = ""
    for fname in ("requirements.txt", "pyproject.toml", "setup.cfg", "tox.ini"):
        fpath = os.path.join(project_dir, fname)
        if os.path.exists(fpath):
            try:
                with open(fpath, "r") as f:
                    py_text += f.read().lower()
            except OSError:
                pass
    if "pytest-bdd" in py_text:
        runners.add("pytest-bdd")
        evidence.append("python:pytest-bdd")
    if "pytest" in py_text or os.path.exists(os.path.join(project_dir, "pytest.ini")):
        runners.add("pytest")
        evidence.append("python:pytest")
    if "behave" in py_text:
        runners.add("behave")
        evidence.append("python:behave")
    # unittest is stdlib (no dependency entry); infer from test-file naming only
    # when no richer Python runner was found, to avoid noise.
    if "pytest" not in runners and "pytest-bdd" not in runners:
        if glob_search(project_dir, "**/test_*.py") or glob_search(project_dir, "**/*_test.py"):
            runners.add("unittest")
            evidence.append("glob:test_*.py")

    # --- Gherkin feature files (adapter-agnostic BDD signal) ---
    if glob_search(project_dir, "**/*.feature"):
        runners.add("gherkin")
        evidence.append("glob:*.feature")

    return {"runners": sorted(runners), "evidence": sorted(set(evidence))}


#: Where documentation may already live, most-specific first. `knowledge-base/reference/`
#: is the layout docs-manager itself writes; `docs/` is the pre-adoption convention. Looking
#: only at `docs/` meant that on any project that had already adopted the toolkit — including
#: this repo, once it moved its own tree — the coordinator was told there was no docs
#: directory and no existing files, so every run planned a from-scratch create and the
#: reverse-sync it is supposed to do never had a starting point.
DOC_DIR_CANDIDATES = (
    ("knowledge-base", os.path.join("knowledge-base", "reference")),
    ("knowledge-base", "knowledge-base"),
    ("docs", "docs"),
)


def detect_existing_docs(project_dir: str) -> dict:
    """Detect existing documentation.

    `docs_dir` is the first candidate that exists and holds markdown, `layout` names the
    convention it belongs to, and `files` lists its markdown plus the root-level documents.
    An empty directory is not a hit: `knowledge-base/` exists as soon as code-graph writes
    `settings.json` into it, and treating that as "docs are present" would be worse than
    the bug this replaced.
    """
    results = {"docs_dir": None, "layout": None, "files": []}

    for layout, relative in DOC_DIR_CANDIDATES:
        docs_path = os.path.join(project_dir, relative)
        if not os.path.isdir(docs_path):
            continue
        markdown = sorted(f for f in os.listdir(docs_path) if f.endswith('.md'))
        if not markdown:
            continue
        results["docs_dir"] = docs_path
        results["layout"] = layout
        results["files"].extend(markdown)
        break

    # Check for root-level docs
    root_docs = ["README.md", "CLAUDE.md", "AGENTS.md", "CONTRIBUTING.md", "CHANGELOG.md"]
    for doc in root_docs:
        if os.path.exists(os.path.join(project_dir, doc)):
            results["files"].append(doc)

    return results


def get_needed_docs(project_info: dict) -> list:
    """Determine which documentation files are needed based on project analysis."""
    needed = ["README.md", "ARCHITECTURE.md", "DEVELOPER.md", "STYLE_GUIDE.md"]

    # Add database docs if database detected
    if project_info.get("database", {}).get("type") or project_info.get("database", {}).get("orm"):
        needed.append("DATABASE.md")

    # Add API docs if backend detected
    if project_info.get("framework", {}).get("backend"):
        needed.append("API.md")

    # Add infrastructure docs if containerization detected
    infra = project_info.get("infrastructure", {})
    if infra.get("containerization") or infra.get("hosting") or infra.get("ci_cd"):
        needed.append("DEPLOYMENT.md")
        needed.append("INFRASTRUCTURE.md")

    # Always add security docs for production projects
    needed.append("SECURITY.md")

    return needed


def analyze_project(project_dir: str = ".") -> dict:
    """Main function to analyze a project and return comprehensive information."""
    project_dir = os.path.abspath(project_dir)

    results = {
        "project_dir": project_dir,
        "runtime": {},
        "framework": {},
        "database": {},
        "infrastructure": {},
        "existing_docs": {},
        "needed_docs": [],
        "test_runners": {}
    }

    # Run detections
    results["runtime"] = detect_package_manager(project_dir)
    results["framework"] = detect_framework(project_dir, results["runtime"].get("runtime", ""))
    results["database"] = detect_database(project_dir)
    results["infrastructure"] = detect_infrastructure(project_dir)
    results["existing_docs"] = detect_existing_docs(project_dir)
    results["needed_docs"] = get_needed_docs(results)
    results["test_runners"] = detect_test_runners(project_dir)

    return results


def main():
    """CLI entry point."""
    project_dir = sys.argv[1] if len(sys.argv) > 1 else "."
    results = analyze_project(project_dir)
    print(json.dumps(results, indent=2))


if __name__ == "__main__":
    main()
