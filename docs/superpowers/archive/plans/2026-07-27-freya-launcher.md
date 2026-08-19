# freya Launcher Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build `freya`, a self-locating launcher that gives every coding agent one portable command surface (`freya code-graph impact src/auth.ts`), replacing Claude's `${CLAUDE_PLUGIN_ROOT}` invocation.

**Architecture:** A thin executable shim (`bin/freya`) delegates to an importable, testable module (`bin/freya_cli.py`). The module locates the suite from its own path via `Path(__file__).resolve()` (symlink-following, so agent-linked copies still resolve to the canonical store), maps a friendly command name to a script through a JSON manifest (`bin/commands.json`), and dispatches with `sys.executable` — never bare `python`. Adds a `doctor` health check.

**Tech Stack:** Python 3 standard library only (`json`, `pathlib`, `subprocess`, `shutil`, `sys`, `os`); `unittest` for tests.

**Phase 1 of** `docs/design/portability/01-design.md` §11. Later phases (SKILL.md rewrite, installer, orchestration, `update`/`init`) are out of scope here.

## Global Constraints

- **Stdlib-only Python 3.** No third-party dependencies — the suite's standing rule.
- **Shebang:** every executable script starts `#!/usr/bin/env python3`.
- **Tests:** `unittest`, colocated as `test_<module>.py` beside the module, importing via `sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))`. Run with `python3 -m unittest test_<module> -v` from the module's directory.
- **Never invoke bare `python`.** Dispatch uses `sys.executable`.
- **Never use `${CLAUDE_PLUGIN_ROOT}`.** Self-locate from `__file__`.
- **Symlink correctness:** the shim must use `os.path.realpath(__file__)` (not `abspath`) — under `-P` / `PYTHONSAFEPATH` / isolated mode CPython does not auto-insert a resolved `sys.path[0]`, so abspath would point at the symlink's directory and the import would fail.
- **Do not modify existing skill scripts** in this phase. Only `bin/` is created.
- **Commit locally after each task. Do NOT `git push`** (standing user rule).
- Manifest paths are relative to the repo's `skills/` directory.

---

### Task 1: Command manifest and self-location

**Files:**
- Create: `bin/commands.json`
- Create: `bin/freya_cli.py`
- Test: `bin/test_freya_cli.py`

**Interfaces:**
- Consumes: nothing (first task).
- Produces: `suite_root() -> Path`, `load_manifest(root: Path|str|None = None) -> dict[str, str]`, `resolve_command(name: str, manifest: dict|None = None, root: Path|str|None = None) -> Path|None`. Later tasks call all three.

- [ ] **Step 1: Write the failing test**

Create `bin/test_freya_cli.py`:

```python
#!/usr/bin/env python3
"""Proof suite for freya_cli.py — the portable launcher."""
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import freya_cli  # noqa: E402


class SuiteRootTest(unittest.TestCase):
    def test_points_at_checkout_containing_skills_and_bin(self):
        root = freya_cli.suite_root()
        self.assertTrue((root / "skills").is_dir(), f"no skills/ under {root}")
        self.assertTrue((root / "bin").is_dir(), f"no bin/ under {root}")

    def test_is_absolute_and_resolved(self):
        root = freya_cli.suite_root()
        self.assertTrue(root.is_absolute())
        self.assertEqual(root, root.resolve())


class ManifestTest(unittest.TestCase):
    def test_loads_and_contains_core_commands(self):
        manifest = freya_cli.load_manifest()
        for name in ("code-graph", "behavior-graph", "status", "spec"):
            self.assertIn(name, manifest)

    def test_every_manifest_target_exists(self):
        """Guards against manifest drift when scripts move or are renamed."""
        root = freya_cli.suite_root()
        missing = [
            f"{name} -> {rel}"
            for name, rel in freya_cli.load_manifest().items()
            if not (root / "skills" / rel).is_file()
        ]
        self.assertEqual(missing, [], f"manifest points at missing scripts: {missing}")


class ResolveCommandTest(unittest.TestCase):
    def test_known_command_resolves_to_existing_script(self):
        script = freya_cli.resolve_command("code-graph")
        self.assertIsNotNone(script)
        self.assertTrue(script.is_file())
        self.assertEqual(script.name, "graph_ops.py")

    def test_unknown_command_returns_none(self):
        self.assertIsNone(freya_cli.resolve_command("no-such-command"))

    def test_honors_explicit_root_and_manifest(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "skills" / "demo" / "scripts").mkdir(parents=True)
            target = root / "skills" / "demo" / "scripts" / "run.py"
            target.write_text("")
            got = freya_cli.resolve_command(
                "demo", manifest={"demo": "demo/scripts/run.py"}, root=root
            )
            self.assertEqual(got, target)


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd bin && python3 -m unittest test_freya_cli -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'freya_cli'`

- [ ] **Step 3: Write the manifest**

Create `bin/commands.json` (paths relative to `skills/`; every target verified to have a CLI entrypoint):

```json
{
  "code-graph": "code-graph/scripts/graph_ops.py",
  "behavior-graph": "behavior-graph/scripts/behavior_graph.py",
  "behavior-runner": "behavior-runner/scripts/run_behaviors.py",
  "status": "status/scripts/collect_status.py",
  "detect-project": "docs-manager/scripts/detect_project.py",
  "spec": "spec-manager/scripts/search_specs.py",
  "adapters": "spec-manager/scripts/adapters.py",
  "adr": "spec-manager/scripts/adr.py",
  "contradictions": "spec-manager/scripts/contradictions.py",
  "drift": "spec-manager/scripts/drift.py",
  "intent": "spec-manager/scripts/intent.py",
  "principles": "spec-manager/scripts/principles.py",
  "project-shape": "spec-manager/scripts/project_shape.py",
  "verify-intent": "spec-manager/scripts/verify_intent.py",
  "verify-links": "spec-manager/scripts/verify_links.py"
}
```

- [ ] **Step 4: Write minimal implementation**

Create `bin/freya_cli.py`:

```python
#!/usr/bin/env python3
"""freya — the portable launcher for the freya-devkit skill suite.

Gives every coding agent one command surface (`freya <command> [args...]`)
instead of Claude-specific `${CLAUDE_PLUGIN_ROOT}` script paths. Logic lives
here (importable, testable); `bin/freya` is the executable shim.
"""
import json
from pathlib import Path

MANIFEST_NAME = "commands.json"


def suite_root():
    """Absolute path of the freya-devkit checkout (the canonical store).

    `.resolve()` follows symlinks, so a skill directory linked into an agent's
    skills folder still resolves back to the real tree where sibling scripts live.
    """
    return Path(__file__).resolve().parents[1]


def load_manifest(root=None):
    """Load the command -> script-path map."""
    root = Path(root) if root is not None else suite_root()
    with open(root / "bin" / MANIFEST_NAME, encoding="utf-8") as fh:
        return json.load(fh)


def resolve_command(name, manifest=None, root=None):
    """Absolute Path of the script for `name`, or None if unknown."""
    root = Path(root) if root is not None else suite_root()
    if manifest is None:
        manifest = load_manifest(root)
    rel = manifest.get(name)
    if rel is None:
        return None
    return root / "skills" / rel
```

- [ ] **Step 5: Run test to verify it passes**

Run: `cd bin && python3 -m unittest test_freya_cli -v`
Expected: PASS — 7 tests OK

- [ ] **Step 6: Commit**

```bash
git add bin/commands.json bin/freya_cli.py bin/test_freya_cli.py
git commit -m "feat(freya): command manifest and self-location"
```

---

### Task 2: Dispatch with the current interpreter

**Files:**
- Modify: `bin/freya_cli.py`
- Test: `bin/test_freya_cli.py`

**Interfaces:**
- Consumes: `resolve_command()` from Task 1.
- Produces: `build_argv(script: Path, args: list[str]) -> list[str]`, `run_command(name: str, args: list[str], root=None) -> int|None` (returns the child's exit code, or `None` when the command is unknown). Task 3's `main()` calls `run_command`.

- [ ] **Step 1: Write the failing test**

Append to `bin/test_freya_cli.py` (before the `if __name__` block):

```python
class BuildArgvTest(unittest.TestCase):
    def test_uses_current_interpreter_not_bare_python(self):
        argv = freya_cli.build_argv(Path("/tmp/x.py"), ["--flag", "v"])
        self.assertEqual(argv[0], sys.executable)
        self.assertEqual(argv[1], "/tmp/x.py")
        self.assertEqual(argv[2:], ["--flag", "v"])

    def test_all_elements_are_strings(self):
        argv = freya_cli.build_argv(Path("/tmp/x.py"), [])
        self.assertTrue(all(isinstance(a, str) for a in argv))


class RunCommandTest(unittest.TestCase):
    def _fixture(self, tmp, body):
        root = Path(tmp)
        (root / "bin").mkdir(parents=True)
        (root / "skills" / "demo" / "scripts").mkdir(parents=True)
        (root / "skills" / "demo" / "scripts" / "run.py").write_text(body)
        (root / "bin" / "commands.json").write_text(
            json.dumps({"demo": "demo/scripts/run.py"})
        )
        return root

    def test_propagates_child_exit_code(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = self._fixture(tmp, "import sys\nsys.exit(7)\n")
            self.assertEqual(freya_cli.run_command("demo", [], root=root), 7)

    def test_returns_zero_on_success(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = self._fixture(tmp, "print('hi')\n")
            self.assertEqual(freya_cli.run_command("demo", [], root=root), 0)

    def test_passes_arguments_through(self):
        with tempfile.TemporaryDirectory() as tmp:
            body = "import sys\nsys.exit(len(sys.argv) - 1)\n"
            root = self._fixture(tmp, body)
            self.assertEqual(freya_cli.run_command("demo", ["a", "b", "c"], root=root), 3)

    def test_unknown_command_returns_none(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = self._fixture(tmp, "print('hi')\n")
            self.assertIsNone(freya_cli.run_command("nope", [], root=root))
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd bin && python3 -m unittest test_freya_cli -v`
Expected: FAIL — `AttributeError: module 'freya_cli' has no attribute 'build_argv'`

- [ ] **Step 3: Write minimal implementation**

In `bin/freya_cli.py`, add `import subprocess` and `import sys` to the imports, then append:

```python
def build_argv(script, args):
    """Command line for running a suite script with the *current* interpreter.

    Uses sys.executable so the launcher never depends on a bare `python` being
    on PATH — it frequently is not on modern systems.
    """
    return [sys.executable, str(script), *[str(a) for a in args]]


def run_command(name, args, root=None):
    """Run a suite command; return its exit code, or None if the name is unknown."""
    script = resolve_command(name, root=root)
    if script is None:
        return None
    return subprocess.call(build_argv(script, args))
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd bin && python3 -m unittest test_freya_cli -v`
Expected: PASS — 13 tests OK

- [ ] **Step 5: Commit**

```bash
git add bin/freya_cli.py bin/test_freya_cli.py
git commit -m "feat(freya): dispatch via sys.executable with exit-code propagation"
```

---

### Task 3: `main()`, help, and unknown-command handling

**Files:**
- Modify: `bin/freya_cli.py`
- Test: `bin/test_freya_cli.py`

**Interfaces:**
- Consumes: `load_manifest()`, `run_command()`.
- Produces: `format_help(manifest=None) -> str`, `main(argv: list[str]|None = None) -> int`. `bin/freya` (Task 5) calls `main`. Exit codes: `0` success/help, `2` unknown command, otherwise the child's code.

- [ ] **Step 1: Write the failing test**

Append to `bin/test_freya_cli.py`:

```python
import contextlib
import io


class FormatHelpTest(unittest.TestCase):
    def test_lists_every_manifest_command_and_builtins(self):
        text = freya_cli.format_help({"zebra": "z/scripts/z.py", "alpha": "a/scripts/a.py"})
        self.assertIn("alpha", text)
        self.assertIn("zebra", text)
        self.assertIn("doctor", text)
        self.assertIn("help", text)
        self.assertLess(text.index("alpha"), text.index("zebra"), "commands should be sorted")


class MainTest(unittest.TestCase):
    def _run(self, argv):
        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            code = freya_cli.main(argv)
        return code, out.getvalue(), err.getvalue()

    def test_no_args_prints_help_and_succeeds(self):
        code, out, _ = self._run([])
        self.assertEqual(code, 0)
        self.assertIn("Usage: freya", out)

    def test_help_command_prints_help(self):
        for flag in ("help", "-h", "--help"):
            code, out, _ = self._run([flag])
            self.assertEqual(code, 0, flag)
            self.assertIn("Usage: freya", out)

    def test_unknown_command_exits_2_with_stderr_hint(self):
        code, _, err = self._run(["definitely-not-a-command"])
        self.assertEqual(code, 2)
        self.assertIn("unknown command", err)
        self.assertIn("freya help", err)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd bin && python3 -m unittest test_freya_cli -v`
Expected: FAIL — `AttributeError: module 'freya_cli' has no attribute 'format_help'`

- [ ] **Step 3: Write minimal implementation**

Append to `bin/freya_cli.py`:

```python
def format_help(manifest=None):
    """Human-readable command listing."""
    if manifest is None:
        manifest = load_manifest()
    lines = [
        "freya — freya-devkit launcher",
        "",
        "Usage: freya <command> [args...]",
        "",
        "Commands:",
    ]
    lines += [f"  {name}" for name in sorted(manifest)]
    lines += [
        "",
        "Built-ins:",
        "  doctor    Check that the installation is healthy",
        "  help      Show this message",
        "",
        "All arguments after <command> are passed through unchanged.",
    ]
    return "\n".join(lines)


def main(argv=None):
    argv = list(sys.argv[1:] if argv is None else argv)
    if not argv or argv[0] in ("help", "-h", "--help"):
        print(format_help())
        return 0
    name, rest = argv[0], argv[1:]
    code = run_command(name, rest)
    if code is None:
        sys.stderr.write(
            f"freya: unknown command '{name}'\n\nRun 'freya help' for the command list.\n"
        )
        return 2
    return code
```

Note: the `doctor` built-in is wired into `main` in Task 4, which is where `doctor()` is defined — so this task introduces no forward reference.

- [ ] **Step 4: Run test to verify it passes**

Run: `cd bin && python3 -m unittest test_freya_cli -v`
Expected: PASS — 17 tests OK

- [ ] **Step 5: Commit**

```bash
git add bin/freya_cli.py bin/test_freya_cli.py
git commit -m "feat(freya): main dispatch, help, and unknown-command handling"
```

---

### Task 4: `freya doctor` health check

**Files:**
- Modify: `bin/freya_cli.py`
- Test: `bin/test_freya_cli.py`

**Interfaces:**
- Consumes: `suite_root()`, `load_manifest()`, and `main()` from Task 3 (this task wires the `doctor` built-in into it).
- Produces: `doctor_checks(root=None) -> list[tuple[str, str, str]]` where each tuple is `(name, status, detail)` and `status` is one of `"ok"` / `"warn"` / `"fail"`; `doctor(root=None) -> int` (0 unless a check is `"fail"` — `"warn"` does not fail the run, because `freya` is not on `PATH` until the Phase 3 installer runs).

- [ ] **Step 1: Write the failing test**

Append to `bin/test_freya_cli.py`:

```python
class DoctorTest(unittest.TestCase):
    def _status(self, checks, name):
        return next(s for n, s, _ in checks if n == name)

    def test_healthy_checkout_reports_ok(self):
        checks = freya_cli.doctor_checks()
        self.assertEqual(self._status(checks, "suite root"), "ok")
        self.assertEqual(self._status(checks, "manifest"), "ok")
        self.assertEqual(self._status(checks, "scripts"), "ok")
        self.assertEqual(self._status(checks, "python"), "ok")

    def test_path_check_is_warn_not_fail_when_absent(self):
        statuses = {s for n, s, _ in freya_cli.doctor_checks() if n == "freya on PATH"}
        self.assertTrue(statuses <= {"ok", "warn"}, f"PATH must never hard-fail, got {statuses}")

    def test_missing_script_is_reported_as_fail(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "bin").mkdir(parents=True)
            (root / "skills").mkdir(parents=True)
            (root / "bin" / "commands.json").write_text(
                json.dumps({"ghost": "ghost/scripts/ghost.py"})
            )
            checks = freya_cli.doctor_checks(root=root)
            self.assertEqual(self._status(checks, "scripts"), "fail")
            self.assertIn("ghost", dict((n, d) for n, _, d in checks)["scripts"])

    def test_doctor_returns_1_when_a_check_fails(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "bin").mkdir(parents=True)
            (root / "skills").mkdir(parents=True)
            (root / "bin" / "commands.json").write_text(
                json.dumps({"ghost": "ghost/scripts/ghost.py"})
            )
            out = io.StringIO()
            with contextlib.redirect_stdout(out):
                code = freya_cli.doctor(root=root)
            self.assertEqual(code, 1)
            self.assertIn("FAIL", out.getvalue())

    def test_doctor_returns_0_on_healthy_checkout(self):
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            code = freya_cli.doctor()
        self.assertEqual(code, 0)

    def test_main_dispatches_the_doctor_builtin(self):
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            code = freya_cli.main(["doctor"])
        self.assertEqual(code, 0)
        self.assertIn("suite root", out.getvalue())

    def _broken_manifest_root(self, tmp, content):
        root = Path(tmp)
        (root / "bin").mkdir(parents=True, exist_ok=True)
        (root / "skills").mkdir(parents=True, exist_ok=True)
        (root / "bin" / "commands.json").write_text(content)
        return root

    def test_malformed_manifest_is_reported_not_raised(self):
        """doctor exists to diagnose broken installs — it must never traceback.

        Every input must ALSO leave the scripts check unable to claim success.
        `"{ not json"` is the case that reaches the `except (OSError, ValueError)`
        branch — the literal site of the original defect, where falling back to an
        empty manifest made scripts report ("ok", "all present") having verified
        nothing. Asserting on scripts here is what keeps that fix from silently
        regressing.
        """
        for content in ("[]", "null", '"a string"', "{ not json"):
            with self.subTest(content=content), tempfile.TemporaryDirectory() as tmp:
                root = self._broken_manifest_root(tmp, content)
                checks = freya_cli.doctor_checks(root=root)   # must not raise
                self.assertEqual(self._status(checks, "manifest"), "fail")
                detail = dict((n, d) for n, _, d in checks)["scripts"]
                self.assertNotEqual(self._status(checks, "scripts"), "ok")
                self.assertNotIn("all present", detail)

    def test_absent_manifest_file_is_reported_not_raised(self):
        """The OSError sub-path: no commands.json at all."""
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "bin").mkdir(parents=True)
            (root / "skills").mkdir(parents=True)
            checks = freya_cli.doctor_checks(root=root)   # must not raise
            self.assertEqual(self._status(checks, "manifest"), "fail")
            detail = dict((n, d) for n, _, d in checks)["scripts"]
            self.assertNotEqual(self._status(checks, "scripts"), "ok")
            self.assertNotIn("all present", detail)

    def test_non_string_manifest_value_is_reported(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = self._broken_manifest_root(tmp, json.dumps({"demo": 5}))
            checks = freya_cli.doctor_checks(root=root)
            self.assertEqual(self._status(checks, "manifest"), "fail")

    def test_scripts_not_claimed_present_when_manifest_unusable(self):
        """The bug this guards: falling back to {} made scripts report 'all present'."""
        with tempfile.TemporaryDirectory() as tmp:
            root = self._broken_manifest_root(tmp, "[]")
            checks = freya_cli.doctor_checks(root=root)
            detail = dict((n, d) for n, _, d in checks)["scripts"]
            self.assertNotEqual(self._status(checks, "scripts"), "ok")
            self.assertNotIn("all present", detail)

    def test_doctor_reports_failure_cleanly_on_malformed_manifest(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = self._broken_manifest_root(tmp, "null")
            out = io.StringIO()
            with contextlib.redirect_stdout(out):
                code = freya_cli.doctor(root=root)   # must not raise
            self.assertEqual(code, 1)
            self.assertIn("FAIL", out.getvalue())
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd bin && python3 -m unittest test_freya_cli -v`
Expected: FAIL — `AttributeError: module 'freya_cli' has no attribute 'doctor_checks'`

- [ ] **Step 3: Write minimal implementation**

In `bin/freya_cli.py` add `import shutil` to the imports, then append:

```python
MIN_PYTHON = (3, 8)


def doctor_checks(root=None):
    """Health checks as (name, status, detail); status is 'ok' | 'warn' | 'fail'."""
    root = Path(root) if root is not None else suite_root()
    checks = []

    skills_ok = (root / "skills").is_dir()
    checks.append(("suite root", "ok" if skills_ok else "fail", str(root)))

    # `manifest` stays None unless we loaded something we can actually trust.
    # doctor exists to diagnose broken installs, so a malformed manifest must be
    # reported, never crash — and the scripts check must not claim "all present"
    # when it never had a manifest to check against.
    manifest = None
    try:
        loaded = load_manifest(root)
    except (OSError, ValueError) as exc:
        checks.append(("manifest", "fail", str(exc)))
    else:
        if not isinstance(loaded, dict):
            checks.append((
                "manifest", "fail",
                f"expected a JSON object, got {type(loaded).__name__}",
            ))
        elif not all(isinstance(rel, str) for rel in loaded.values()):
            checks.append((
                "manifest", "fail",
                "every entry must map a command name to a string path",
            ))
        else:
            manifest = loaded
            checks.append(("manifest", "ok", f"{len(loaded)} commands"))

    if manifest is None:
        checks.append(("scripts", "warn", "not evaluated — manifest unavailable"))
    else:
        missing = sorted(
            name for name, rel in manifest.items() if not (root / "skills" / rel).is_file()
        )
        checks.append((
            "scripts",
            "fail" if missing else "ok",
            f"missing: {', '.join(missing)}" if missing else "all present",
        ))

    py_ok = sys.version_info >= MIN_PYTHON
    checks.append(("python", "ok" if py_ok else "fail", sys.version.split()[0]))

    found = shutil.which("freya")
    checks.append((
        "freya on PATH",
        "ok" if found else "warn",
        found or "not found — run the installer or add bin/ to PATH",
    ))
    return checks


def doctor(root=None):
    """Print health checks; return 1 if any check failed, else 0."""
    label = {"ok": "ok", "warn": "warn", "fail": "FAIL"}
    checks = doctor_checks(root)
    for name, status, detail in checks:
        print(f"[{label[status]}] {name}: {detail}")
    return 1 if any(status == "fail" for _, status, _ in checks) else 0
```

- [ ] **Step 4: Wire the `doctor` built-in into `main`**

In `main()`, insert the `doctor` branch immediately after the `name, rest = argv[0], argv[1:]` line:

```python
    name, rest = argv[0], argv[1:]
    if name == "doctor":
        return doctor()
    code = run_command(name, rest)
```

- [ ] **Step 5: Run test to verify it passes**

Run: `cd bin && python3 -m unittest test_freya_cli -v`
Expected: PASS — 29 tests OK

- [ ] **Step 6: Commit**

```bash
git add bin/freya_cli.py bin/test_freya_cli.py
git commit -m "feat(freya): doctor health check and main wiring"
```

---

### Task 5: Executable shim and end-to-end verification

**Files:**
- Create: `bin/freya`
- Test: manual end-to-end commands (below)

**Interfaces:**
- Consumes: `freya_cli.main()`.
- Produces: the `freya` executable — the entry point the installer (Phase 3) links onto `PATH` and that all rewritten SKILL.md files (Phase 2) invoke.

- [ ] **Step 1: Write the shim**

Create `bin/freya`:

```python
#!/usr/bin/env python3
"""Executable entry point for the freya-devkit launcher.

Deliberately thin: all logic lives in freya_cli.py so it stays importable and
unit-testable. Uses realpath (not abspath) because this file is symlinked onto
PATH by the installer — abspath would resolve to the symlink's directory and the
freya_cli import would fail.
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.realpath(__file__)))

from freya_cli import main  # noqa: E402

if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
```

- [ ] **Step 2: Make it executable and verify help works**

```bash
chmod +x bin/freya
./bin/freya help
```
Expected: the command list, including `code-graph`, `status`, `doctor`; exit code 0.

- [ ] **Step 3: Verify doctor and unknown-command exit codes**

```bash
./bin/freya doctor; echo "doctor exit=$?"
./bin/freya definitely-not-a-command; echo "unknown exit=$?"
```
Expected: doctor prints `[ok]` lines (a `[warn]` for `freya on PATH` is expected before the installer exists) and `doctor exit=0`; the unknown command prints `freya: unknown command …` to stderr with `unknown exit=2`.

- [ ] **Step 4: Verify real dispatch reaches a suite script**

```bash
./bin/freya code-graph --help
```
Expected: `graph_ops.py`'s own argparse help (proving the manifest → `sys.executable` → script path works end to end).

- [ ] **Step 5: Verify the symlink path (the realpath requirement)**

```bash
mkdir -p /tmp/freya-path-test
ln -sf "$PWD/bin/freya" /tmp/freya-path-test/freya
/tmp/freya-path-test/freya help > /dev/null && echo "symlinked invocation OK"
PATH="/tmp/freya-path-test:$PATH" freya doctor | grep "freya on PATH"
rm -rf /tmp/freya-path-test
```
Expected: `symlinked invocation OK`, and the PATH check now reports `[ok]` with the symlink location — proving the launcher works when linked onto `PATH`, which is exactly how the installer will deploy it.

- [ ] **Step 6: Run the full suite once more**

Run: `cd bin && python3 -m unittest test_freya_cli -v`
Expected: PASS — 29 tests OK

- [ ] **Step 7: Commit**

```bash
git add bin/freya
git commit -m "feat(freya): executable shim with symlink-safe self-location"
```

---

## Out of scope (later phases)

- **Phase 2** — rewriting the 83 `${CLAUDE_PLUGIN_ROOT}` invocations and 172 `/freya-devkit:` slash references in SKILL.md to `freya <command>`.
- **Phase 3** — `install.sh` / `install.ps1`: canonical store, PATH linking, per-agent skill dirs with `freya-*` prefixing.
- **Phase 4** — portable orchestration for the three fan-out flows; the audit driver + headless agent adapter.
- **Phase 5** — `freya update` (+ notify-only check) and `freya init`. `main()` will gain those subcommands alongside `doctor`.
