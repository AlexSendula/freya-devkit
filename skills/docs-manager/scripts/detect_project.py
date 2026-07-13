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

    return results


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

                    # Frontend frameworks
                    if "next" in deps:
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


def detect_existing_docs(project_dir: str) -> dict:
    """Detect existing documentation."""
    results = {"docs_dir": None, "files": []}

    # Check for docs directory
    docs_path = os.path.join(project_dir, "docs")
    if os.path.isdir(docs_path):
        results["docs_dir"] = docs_path
        for f in os.listdir(docs_path):
            if f.endswith('.md'):
                results["files"].append(f)

    # Check for root-level docs
    root_docs = ["README.md", "CLAUDE.md", "CONTRIBUTING.md", "CHANGELOG.md"]
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
