#!/usr/bin/env python3
"""
behavior-runner — run accepted behaviors via their adapter and emit observed
coverage fingerprints (TEST -> CODE edges). Producer only: it never writes
behavior.json (that is behavior-graph's job).

Two unit executors exist: **vitest** (in-process, runner-native V8 coverage) and **pytest**
(`sys.executable -m pytest`, coverage.py's JSON report when it is installed), the latter
serving both the `pytest` and `unittest` adapters. Every other level and adapter is still
`level-deferred`. The `(state, level, adapter)` if-ladder in `fingerprint_behavior` is now
carrying two executors and is the thing to replace with a runner-adapter registry when a
third arrives.
"""
import argparse
import importlib.util
import json
import os
import re
import subprocess
import sys
from pathlib import Path, PurePosixPath, PureWindowsPath

# Reuse the freya-spec-manager frontmatter parser (stdlib-only, zero-install).
_SPEC_SCRIPTS = Path(__file__).resolve().parents[2] / "freya-spec-manager" / "scripts"
_CODE_GRAPH = Path(__file__).resolve().parents[2] / "freya-code-graph" / "scripts" / "graph_ops.py"
sys.path.insert(0, str(_SPEC_SCRIPTS))
import frontmatter  # noqa: E402
from frontmatter import FrontmatterError  # noqa: E402
# adapters.py lives alongside frontmatter.py in freya-spec-manager/scripts (already on sys.path).
from adapters import parse_locator  # noqa: E402
# The containment rule is owned by freya-code-graph and imported, never re-typed (ADR-030):
# a runner whose idea of "outside the project" drifts from the Tier-1 gate's is a gate with a
# seam in it. `_CODE_GRAPH.parent` rather than a second spelling of that directory — the
# subprocess argv in `_code_graph_deps` already proves the path, and one constant cannot
# drift from itself.
sys.path.insert(0, str(_CODE_GRAPH.parent))
from containment import escapes  # noqa: E402

OBSERVED_CONFIDENCE = 0.8
STATIC_CONFIDENCE = 0.5

# Adapters routed to the pytest executor. `unittest` is here because a stdlib
# `unittest.TestCase` is collected and addressed by pytest exactly like a pytest test —
# the adapter names how the test is *written*, the executor is how it is *run*.
PYTEST_ADAPTERS = ("pytest", "unittest")
# Project-relative, so the argv carries no machine path and the run is reproducible from
# the logged command. Deliberately NOT `coverage/coverage-final.json`: that name belongs to
# istanbul, the two schemas share nothing, and one directory holding both under one name is
# how a parser gets handed the other language's report.
PYTEST_COVERAGE_JSON = "coverage/coverage-python.json"
# pytest exit codes that mean "the node id addressed no test", as distinct from "a test ran
# and failed". Measured on pytest 9.0.1: a node id naming a method that does not exist
# prints `(no match in any of [...])` and exits **4** (usage error); 5 is
# `EXIT_NOTESTSCOLLECTED`. Kept apart from `test-failed` because that reason both
# invalidates committed edges and hard-blocks wrap-up (ADR-009), and a stale locator is not
# a test result — resolving locators is `verify_links`' job, not the runner's.
_PYTEST_NOTHING_SELECTED = (4, 5)
# The two importable pieces a JSON coverage report needs. Neither is stdlib and neither may
# become a hard dependency (ADR-005's zero-install constraint), so their absence degrades
# rather than fails. Both are named because `--cov-report=json` is *pytest-cov's* flag, not
# coverage.py's: probing only `coverage` would emit flags pytest rejects with a usage error,
# which would then read as a broken locator.
_COVERAGE_MODULES = ("coverage", "pytest_cov")
# Path components that are somebody else's code. The Python counterpart of the istanbul
# path's `node_modules` guard — with `--cov=.` a virtualenv inside the project root is
# measured like anything else.
_PY_VENDOR_PARTS = frozenset({"site-packages", "dist-packages", ".venv", "venv",
                              "node_modules"})
# Split a locator fragment on `::` or `.`, but never on a `.` inside `[...]`. See
# `pytest_node_id`.
_LOCATOR_SEP_RE = re.compile(r"(?:::|\.)(?![^\[\]]*\])")


def load_behaviors(specs_dir, states=("accepted",), level=None):
    """Return behavior records under specs_dir whose state is in `states`,
    optionally filtered by level.

    Each record is the spec's behavior mapping plus `spec_id` and `spec_path`.
    """
    states = tuple(states)
    out = []
    for root, _dirs, files in os.walk(specs_dir):
        for name in files:
            if not name.endswith(".md"):
                continue
            path = os.path.join(root, name)
            try:
                with open(path, encoding="utf-8") as f:
                    fm, _body = frontmatter.parse_frontmatter(f.read())
            except (FrontmatterError, UnicodeDecodeError, OSError) as e:
                # `UnicodeDecodeError` and `OSError` alongside the parse error: strict UTF-8
                # decoding is a *read* failure, not a frontmatter one, so a single spec with
                # a stray byte — or one that cannot be opened at all — took down the whole
                # behaviour layer with an unhandled traceback rather than skipping the one
                # file it could not read. One bad file must cost one file.
                sys.stderr.write(f"[behavior-runner] skipping unreadable spec {path}: {e}\n")
                continue
            behaviors = fm.get("behaviors")
            if not isinstance(behaviors, list):
                continue
            for b in behaviors:
                if not isinstance(b, dict):
                    continue
                if b.get("state") not in states:
                    continue
                if level is not None and b.get("level") != level:
                    continue
                rec = dict(b)
                rec["spec_id"] = fm.get("id")
                rec["spec_path"] = path
                out.append(rec)
    return out


def load_accepted_behaviors(specs_dir, level=None):
    """Backward-compatible wrapper: accepted behaviors only (used by the
    wrap-up 'run accepted behaviors' path, which must not run confirmed)."""
    return load_behaviors(specs_dir, states=("accepted",), level=level)


def coverage_files_to_keys(coverage_final, project_dir, exclude=None):
    """Map an istanbul coverage-final.json to executed project-relative paths."""
    exclude = exclude or set()
    project = Path(project_dir).resolve()
    keys = set()
    for abs_path, entry in coverage_final.items():
        statements = (entry or {}).get("s", {})
        if not any(count > 0 for count in statements.values()):
            continue  # file loaded but no statement executed
        p = Path(abs_path).resolve()
        try:
            rel = p.relative_to(project).as_posix()
        except ValueError:
            continue  # outside the project
        if rel.startswith("node_modules/") or "/node_modules/" in rel:
            continue
        if rel in exclude:
            continue
        keys.add(rel)
    return sorted(keys)


def coverage_symbols(coverage_final, project_dir, exclude=None):
    """Map an istanbul coverage-final.json to the *named functions that actually ran*.

    Phase 3's symbol refinement, and it comes from the coverage report rather than from the
    code graph on purpose. An `observed` exercise means "the test ran this"; taking its
    symbols from a graph would mix in something nobody executed. `fnMap[i]` names each
    function and `f[i]` counts its executions, so this is measurement, not inference.

    Two rules, both from looking at real coverage output (775 functions across 123 files):

    - **`f[i] > 0` only.** A function that was loaded but never entered is not exercised.
    - **Named functions only.** 405 of those 775 are `(anonymous_N)`, and N is a *positional*
      counter per file — `(anonymous_1)` occurs in 44 files, and inserting one function
      renumbers every later one. Committing those into `behavior.json` (which is tracked,
      ADR-017) would churn the diff on edits that changed nothing about what ran.
    """
    exclude = exclude or set()
    project = Path(project_dir).resolve()
    symbols = {}
    for abs_path, entry in (coverage_final or {}).items():
        fn_map = (entry or {}).get("fnMap") or {}
        counts = (entry or {}).get("f") or {}
        if not fn_map:
            continue
        try:
            rel = Path(abs_path).resolve().relative_to(project).as_posix()
        except ValueError:
            continue
        if rel in exclude or rel.startswith("node_modules/") or "/node_modules/" in rel:
            continue
        names = set()
        for index, fn in fn_map.items():
            if not counts.get(index):
                continue
            name = (fn or {}).get("name")
            if isinstance(name, str) and name and not name.startswith("(anonymous"):
                names.add(name)
        if names:
            # Union, not assignment. Two absolute keys can resolve to one project-relative
            # path — a workspace package reached through a symlink, or any non-canonical
            # duplicate — and assigning would let whichever came last in the JSON silently
            # erase the other file's executed functions. `coverage_files_to_keys` is immune
            # because it builds a set of paths; this builds a mapping, so it has to say so.
            symbols.setdefault(rel, set()).update(names)
    return {rel: sorted(names) for rel, names in symbols.items()}


def shape_fingerprint(exercised_keys, commit, source="observed", confidence=None, reason=None,
                      symbols=None):
    """Build a per-behavior fingerprint. `source` ("observed"|"static") sets the
    coverage value and each edge's source; unknown when there are no keys.

    `symbols` optionally refines an entry with the named functions that ran in that file. It
    is a *list on the existing per-file entry*, not an entry per symbol: the file key is what
    `behavior-graph` intersects against the impact set, and splitting the entry would change
    that set's cardinality and every count derived from it. Refinement never replaces the file
    anchor (spec §5) — an entry with no symbols is byte-identical to one from before this
    existed, which is what makes the addition safe on a committed artifact.
    """
    if not exercised_keys:
        result = {"coverage": "unknown", "exercises": []}
        if reason is not None:
            result["reason"] = reason
        return result
    if confidence is None:
        confidence = STATIC_CONFIDENCE if source == "static" else OBSERVED_CONFIDENCE
    symbols = symbols or {}
    exercises = []
    for k in exercised_keys:
        edge = {"path": k, "source": source, "confidence": confidence, "freshness": commit}
        named = symbols.get(k)
        if named:
            edge["symbols"] = sorted(named)
        exercises.append(edge)
    return {"coverage": source, "exercises": exercises}


def static_exercises(entry, deps):
    """The static fingerprint key set: the entry file plus its dependency closure."""
    return sorted({entry, *deps})


def vitest_argv(behavior):
    """Return (argv, test_file) to run a single vitest test for this behavior."""
    test_file, fragment = parse_locator(behavior["locator"])
    argv = ["pnpm", "vitest", "run", test_file]
    if fragment:
        argv += ["-t", fragment]
    argv += ["--coverage"]
    return argv, test_file


def pytest_node_id(test_file, fragment):
    """Translate a locator's (path, fragment) into a pytest node id.

    The two grammars do not match. A behavior locator is written `path#Class.method` (the
    spelling spec-manager emits) or `path::Class::method` (pytest's own, which `parse_locator`
    also accepts); pytest addresses a test only as `path::Class::method`. So every separator
    in the fragment is normalised to `::`. No fragment means the whole file, which is a
    legitimate node id on its own.

    **A `subTest` row is not addressable by any runner, and no row selector is built here.**
    Measured on pytest 9.0.1: `pytest 'f.py::Cls::meth[row]'` against a `unittest` table
    method prints `(no match in any of [<UnitTestCase Cls>])` and exits 4 — a usage error,
    not a filter that matched nothing — for every row spelling tried, including pytest's own
    `[name='a']` subtest label. A table method is therefore the finest granularity a behavior
    can bind to: give one `BEH-NNN` to the method, never one per row. Do not re-derive this.

    A pytest `@parametrize` id *is* addressable (`meth[1-2]`), which is why the split leaves a
    `.` inside brackets alone — `meth[1.5]` is one segment, not two.
    """
    if not fragment:
        return test_file
    parts = [p for p in _LOCATOR_SEP_RE.split(fragment) if p]
    return "::".join([test_file, *parts])


def coverage_json_available():
    """Whether this interpreter can produce a pytest JSON coverage report.

    A probe whose answer is allowed to be no: coverage.py and pytest-cov are not stdlib, and
    the plugin is zero-install (ADR-005), so neither may become a hard dependency of running
    a Python behavior. When it answers no the test is still executed — pass or fail is real
    information — and only the coverage half degrades, to `unknown` with a reason rather than
    to a confidently empty `exercises` list.
    """
    try:
        return all(importlib.util.find_spec(m) is not None for m in _COVERAGE_MODULES)
    except (ImportError, ValueError):
        # `find_spec` raises rather than answering for a broken or shadowed installation.
        return False


def _module_available(name):
    """Is `name` importable by the interpreter that would run the test?

    Split from `coverage_json_available` because the two answers carry very different
    weight. A missing coverage module degrades the *measurement* and the test still runs;
    a missing pytest means no test runs at all, and the difference decides whether an
    `unknown` fingerprint preserves the committed edges or replaces them.
    """
    try:
        return importlib.util.find_spec(name) is not None
    except (ImportError, ValueError):
        return False


def pytest_argv(behavior):
    """Return (argv, test_file) to run a single pytest test for this behavior.

    `sys.executable -m pytest`, never a bare `pytest`. ADR-013 measured the cost of the
    other choice on this project: all 80 script invocations named a bare `python`, which does
    not exist on many modern systems, and a bare `pytest` is the same bet on a console script
    being both installed and first on `PATH`. `-m` also pins the runner to the interpreter
    whose `coverage`/`pytest_cov` `coverage_json_available` just probed, so the flags below
    cannot be handed to a pytest that has never heard of them.

    `--cov=.` measures the tree under `cwd` (the project) rather than a guessed package name,
    so a project laid out as `src/`, as a flat module, or as neither is measured the same way.
    """
    test_file, fragment = parse_locator(behavior["locator"])
    argv = [sys.executable, "-m", "pytest", pytest_node_id(test_file, fragment)]
    if coverage_json_available():
        argv += ["--cov=.", "--cov-report=json:" + PYTEST_COVERAGE_JSON]
    return argv, test_file


def coverage_json_to_keys(coverage_report, project_dir, exclude=None):
    """Map a coverage.py `--cov-report=json` report to executed project-relative paths.

    The coverage.py twin of `coverage_files_to_keys`; the two schemas share nothing, which is
    why this is a second function rather than a branch. Measured against coverage 7.12.0
    (`meta.format: 3`): `{"files": {path: {"executed_lines": [...], "summary": {...}}}}`,
    with paths relative to the directory the run started in — `--project`, since that is the
    subprocess `cwd`.

    `--cov=.` reports *every* file under the tree, so a module nothing imported is present
    with `covered_lines: 0` and has to be dropped. That is the same "loaded but nothing
    executed" rule the istanbul path applies to `s`, and the reason a fingerprint is the set
    of files the test reached rather than the set of files that exist.
    """
    exclude = exclude or set()
    project = Path(project_dir).resolve()
    keys = set()
    for path, entry in ((coverage_report or {}).get("files") or {}).items():
        entry = entry or {}
        if not ((entry.get("summary") or {}).get("covered_lines")
                or entry.get("executed_lines")):
            continue
        p = Path(path)
        if not p.is_absolute():
            p = project / p
        try:
            rel = p.resolve().relative_to(project).as_posix()
        except ValueError:
            continue  # outside the project
        if rel in exclude or _PY_VENDOR_PARTS.intersection(rel.split("/")):
            continue
        keys.add(rel)
    return sorted(keys)


def coverage_json_symbols(coverage_report, project_dir, exclude=None):
    """The named functions a pytest run actually entered, per project-relative file.

    The coverage.py twin of `coverage_symbols`, and it reads the same way: measured from what
    ran, never inferred from a graph. Each file entry carries a `functions` map from a
    qualified name (`"used"`, `"TestLib.test_used"`) to its own line data, and a function
    that was never entered has `executed_lines: []`.

    Module-level statements are collected under the **empty** name `""`. That is the exact
    analogue of istanbul's `(anonymous_N)` and is dropped for the same reason: it names no
    function, and behavior.json is committed (ADR-017), so writing it would add a key to the
    tracked diff that says nothing about what ran.

    The `functions` block is coverage.py 7.6.2 and newer. An older report simply has no such
    key, and this returns nothing for that file — which is the byte-identical unrefined entry
    ADR-024 requires, not an error.
    """
    exclude = exclude or set()
    project = Path(project_dir).resolve()
    symbols = {}
    for path, entry in ((coverage_report or {}).get("files") or {}).items():
        functions = (entry or {}).get("functions") or {}
        if not functions:
            continue
        p = Path(path)
        if not p.is_absolute():
            p = project / p
        try:
            rel = p.resolve().relative_to(project).as_posix()
        except ValueError:
            continue
        if rel in exclude or _PY_VENDOR_PARTS.intersection(rel.split("/")):
            continue
        names = set()
        for name, data in functions.items():
            if not isinstance(name, str) or not name:
                continue
            if (data or {}).get("executed_lines"):
                names.add(name)
        if names:
            # Union for the same reason `coverage_symbols` unions: two report keys can
            # resolve to one project-relative path, and assigning would let the last one
            # erase the other's executed functions.
            symbols.setdefault(rel, set()).update(names)
    return {rel: sorted(names) for rel, names in symbols.items()}


def run_pytest_behavior(behavior, project_dir):
    """Run one unit behavior via pytest with coverage; return its fingerprint.

    The order of the checks below is the contract, not a style choice. The exit code is read
    **before** coverage availability, because whether the test passed is real information
    that does not depend on anything being installed — degrading coverage must never turn a
    red test green. And every branch that cannot measure returns `unknown` *with a reason*
    (ADR-005, ADR-006): a confidently empty `exercises` list reads to the blast-radius query
    as "nothing to re-run", which is the one output that silently disables the gate.
    """
    argv, test_file = pytest_argv(behavior)
    commit = _git_head(project_dir)
    cov_path = os.path.join(project_dir, *PYTEST_COVERAGE_JSON.split("/"))
    if os.path.exists(cov_path):
        os.remove(cov_path)

    # Asked before spawning, for the same reason `_PYTEST_NOTHING_SELECTED` exists below:
    # a machine with no pytest installed makes `python -m pytest` exit non-zero, which
    # this function used to call `test-failed` — and that reason both wipes the committed
    # edges in behavior.json and hard-blocks wrap-up (ADR-009). So a fresh clone with
    # nothing installed failed the commit AND destroyed the blast-radius artifact, after
    # which `--covering` on those files answered empty for good and a legitimate
    # ADR-012 downgrade stopped working. "I could not run the test" is not "the test
    # failed", and only one of the two is evidence about the code.
    if not _module_available("pytest"):
        sys.stderr.write(
            f"[behavior-runner] {behavior.get('behavior_id')}: pytest is not installed in"
            f" {sys.executable} — no test was run, so nothing is claimed about it\n"
        )
        return shape_fingerprint([], commit, reason="toolchain-missing: pytest")

    result = subprocess.run(argv, cwd=project_dir, capture_output=True, text=True)
    if result.returncode in _PYTEST_NOTHING_SELECTED:
        # The locator addressed nothing. Not a failure: no test ran, so there is no result
        # to report, and calling it `test-failed` would wipe committed edges and block a
        # commit over a rename.
        sys.stderr.write(
            f"[behavior-runner] {behavior.get('behavior_id')}: pytest selected no test for"
            f" {behavior.get('locator')} (exit {result.returncode}) — the locator is stale"
            f" or the node id does not resolve\n"
        )
        return shape_fingerprint([], commit, reason="locator-selected-nothing")
    if result.returncode != 0:
        # Test failed -> coverage-unknown, never faked.
        sys.stderr.write(result.stdout + result.stderr)
        return shape_fingerprint([], commit, reason="test-failed")
    if not coverage_json_available():
        # The test passed and nothing measured it. Saying so is the whole point: an
        # `unknown` here preserves whatever was previously known, where an empty `observed`
        # would overwrite it with a measurement that never happened.
        sys.stderr.write(
            f"[behavior-runner] {behavior.get('behavior_id')}: test passed but coverage was"
            f" not measured — install coverage.py + pytest-cov to fingerprint Python"
            f" behaviors (neither is required, and neither is bundled)\n"
        )
        return shape_fingerprint([], commit, reason="no-coverage-tool")
    if not os.path.exists(cov_path):
        sys.stderr.write(
            f"[behavior-runner] {behavior.get('behavior_id')}: test passed but no coverage at"
            f" {cov_path} — is the json report reaching that path?\n"
        )
        return shape_fingerprint([], commit, reason="no-coverage")

    with open(cov_path, encoding="utf-8") as f:
        coverage_report = json.load(f)
    keys = coverage_json_to_keys(coverage_report, project_dir, exclude={test_file})
    if not keys:
        sys.stderr.write(
            f"[behavior-runner] {behavior.get('behavior_id')}: the test passed and produced"
            f" coverage, but none of it maps inside {project_dir} — the fingerprint is"
            f" unknown rather than empty\n")
        return shape_fingerprint([], commit, reason="coverage-outside-project")
    return shape_fingerprint(
        keys, commit,
        symbols=coverage_json_symbols(coverage_report, project_dir, exclude={test_file}))


def _git_head(project_dir):
    try:
        out = subprocess.run(
            ["git", "-C", project_dir, "rev-parse", "HEAD"],
            capture_output=True, text=True, check=True,
        )
        return out.stdout.strip()
    except (subprocess.CalledProcessError, FileNotFoundError):
        return "unknown"


def run_unit_behavior(behavior, project_dir):
    """Run one unit behavior via vitest with coverage; return its fingerprint."""
    argv, test_file = vitest_argv(behavior)
    commit = _git_head(project_dir)
    cov_path = os.path.join(project_dir, "coverage", "coverage-final.json")
    if os.path.exists(cov_path):
        os.remove(cov_path)

    try:
        result = subprocess.run(argv, cwd=project_dir, capture_output=True, text=True)
    except OSError as exc:
        # The JS half of the same defect, and it arrives by a different route: `pnpm` is
        # spawned by name, so a machine without it raises here instead of exiting non-zero.
        # Uncaught, that took the whole run down; called `test-failed`, it would wipe the
        # committed edges and block the commit. It is neither — no test ran.
        sys.stderr.write(
            f"[behavior-runner] {behavior.get('behavior_id')}: cannot start {argv[0]!r}"
            f" ({exc.__class__.__name__}) — no test was run, so nothing is claimed\n"
        )
        return shape_fingerprint([], commit,
                                 reason="toolchain-missing: %s" % argv[0])
    if result.returncode != 0:
        # Test failed -> coverage-unknown, never faked.
        sys.stderr.write(result.stdout + result.stderr)
        return shape_fingerprint([], commit, reason="test-failed")
    if not os.path.exists(cov_path):
        # Test passed but produced no coverage file -> misconfigured reporter.
        sys.stderr.write(
            f"[behavior-runner] {behavior['behavior_id']}: test passed but no coverage at"
            f" {cov_path} — is @vitest/coverage-v8 + the json reporter configured?\n"
        )
        return shape_fingerprint([], commit, reason="no-coverage")

    with open(cov_path, encoding="utf-8") as f:
        coverage_final = json.load(f)
    keys = coverage_files_to_keys(coverage_final, project_dir, exclude={test_file})
    if not keys:
        # A coverage report that maps onto nothing inside `--project`. Every other failure
        # path here carries a `reason`; this one returned a bare `unknown`, which is the
        # single value the merge treats as "no news" — so the previous `observed`
        # fingerprint was preserved indefinitely and nothing ever said the measurement had
        # stopped landing. Real causes: a monorepo where the test exercises a sibling
        # package outside the project root, or a reporter emitting paths this cannot
        # resolve.
        sys.stderr.write(
            f"[behavior-runner] {behavior['behavior_id']}: the test passed and produced"
            f" coverage, but none of it maps inside {project_dir} — the fingerprint is"
            f" unknown rather than empty\n")
        return shape_fingerprint([], commit, reason="coverage-outside-project")
    return shape_fingerprint(
        keys, commit,
        symbols=coverage_symbols(coverage_final, project_dir, exclude={test_file}))


def _graph_degraded_from(graph_path):
    """The backend a graph *should* have been built with, if it fell back. None otherwise.

    Read from the artifact rather than from settings, because the artifact is the thing that
    records what actually happened — `degraded_from` is written by the run that degraded, and
    a graph carried between machines still carries it.
    """
    try:
        with open(graph_path, encoding="utf-8") as fh:
            substrate = (json.load(fh) or {}).get("substrate")
    except (OSError, ValueError):
        return None
    if not isinstance(substrate, dict):
        return None
    wanted = substrate.get("degraded_from")
    if not isinstance(wanted, str) or not wanted:
        return None
    got = substrate.get("backend")
    return "%s unavailable, built with %s" % (wanted, got if isinstance(got, str) else "?")


def _reduce_if_absolute(word):
    """`word` reduced to its basename if it is an absolute path, else unchanged.

    Both halves are flavour-agnostic, and the second half is the one that is easy to get
    wrong: detecting a Windows path with `PureWindowsPath` and then taking its basename with
    `PurePosixPath` returns the whole string, because a backslash is not a separator under
    POSIX rules. The path has to be *read back* in the flavour it was recognised in.

    Neither half may use `os.path`: this is applied to another tool's stderr, so the spelling
    is not ours to assume, and the host's answer changes with the platform and — for
    `ntpath.isabs` on a rooted path with no drive — with the interpreter version.
    """
    win, posix = PureWindowsPath(word), PurePosixPath(word)
    if posix.is_absolute():
        return posix.name
    if win.drive or win.root:
        return win.name
    return word


def _portable(detail, project_dir):
    """One line of another tool's stderr, made safe to commit.

    `reason` is written into behavior.json, which is tracked (ADR-017). Splicing raw stderr
    in put whatever that line contained into git: a traceback tail carries the absolute path
    of the machine that produced it, so the same failure produced a different committed
    string on every developer's laptop and leaked a home directory into the repository.

    The project root becomes `.`; anything still absolute is dropped to its basename. The
    diagnostic survives, the machine does not.

    Absoluteness is judged in BOTH path flavours on every host, never by `os.path.isabs`
    alone. The stderr being reduced came from some other tool and may name a path in either
    spelling whatever platform we are on, and the host's own answer is the wrong one twice
    over: on Windows, Python 3.13 changed `ntpath.isabs` so a rooted path with no drive is no
    longer absolute, so `/Users/someone/x.json` sailed through unreduced and its home
    directory reached the committed `behavior.json`. Caught by the first CI run on Windows,
    on 3.13 only, exactly as `bin/freya_cli.py:_escapes` predicts.
    """
    text = " ".join(str(detail or "").split())[:200]
    root = str(project_dir or "").rstrip(os.sep)
    if root:
        text = text.replace(root + os.sep, "").replace(root, ".")
    return " ".join(_reduce_if_absolute(word) for word in text.split())


def _code_graph_deps(entry, project_dir):
    """-> (keys, reason). The transitive import-closure of `entry` from code-graph.

    `keys` is None when the closure could not be determined, and `reason` says why —
    `"no-graph"` or `"graph-query-failed"`. Never `[]` on failure.

    It used to return `[]` on any subprocess or parse error, and the only caller branched
    on `deps is None`. So a failed query produced `static_exercises(entry, [])` — a
    one-file closure — tagged `coverage: static` at full confidence, with no warning.
    behavior.json is committed (ADR-017) and its `exercises[].path` values decide which
    behaviors a change is deemed to affect, so the wrong answer persisted into the repo and
    then quietly narrowed every later blast radius. A green wrap-up that ran fewer
    behaviors than it should is precisely the silent-empty failure ADR-005 exists to stop.

    An empty closure is a real answer — a file that imports nothing. A failed query is not,
    and the two must not share a representation.
    """
    graph_path = os.path.join(project_dir, "knowledge-base", ".graph", "graph.json")
    if not os.path.exists(graph_path):
        return None, "no-graph"

    degraded = _graph_degraded_from(graph_path)
    if degraded:
        # The project asked for a backend and did not get one, so this graph is thinner than
        # the project declared. Answering anyway would write that thinner closure into
        # behavior.json — which is committed, and whose `exercises[].path` values decide
        # which behaviours a change is deemed to affect. Every later blast radius would then
        # be computed against a closure narrowed by whichever laptop happened to run last.
        #
        # `unknown` with a reason is exactly the "no news" signal `merge_fingerprint` already
        # honours: the prior fingerprint is preserved rather than replaced. Refusing to
        # answer is the honest move; a narrower answer that looks authoritative is not.
        return None, "graph-degraded: %s" % degraded
    # `substrate.unmapped_source` (ADR-029) is deliberately NOT read here, and extending the
    # refusal above to cover it is the first "fix" a future reader will reach for.
    #
    # `degraded_from` means the project asked for a backend and did not get one — abnormal,
    # and the artifact is thinner than the project itself declared. Blind spots mean the
    # backend the project *chose* cannot read everything, which is the ordinary operating
    # condition of the floor on any polyglot repository. Refusing on it would return
    # `coverage: unknown` for every confirmed and every integration behaviour on every such
    # repo, freezing behavior.json where there is history and writing empty `exercises` where
    # there is not — and wrap-up's gate would then run zero behaviours and exit 0. A caveat
    # must never change whether there is an answer, only what the answer says about itself.
    # Pinned by test_a_repo_with_unmapped_files_still_fingerprints_static.
    try:
        out = subprocess.run(
            [sys.executable, str(_CODE_GRAPH), "--dependencies", entry,
             "--dir", project_dir, "--format", "json"],
            capture_output=True, text=True, check=True,
        )
        data = json.loads(out.stdout)
    except subprocess.CalledProcessError as exc:
        # A non-zero exit includes "this entry is not a node in the graph", which code-graph
        # reports rather than answering `[]` — the entry may sit under a directory the graph
        # excludes, which is a coverage gap and not an absence of dependencies. Its message
        # goes through verbatim so the operator sees which of the two it was.
        detail = (exc.stderr or "").strip().splitlines()
        return None, "graph-query-failed: %s" % _portable(detail[-1] if detail else
                                                          "no detail", project_dir)
    except (json.JSONDecodeError, FileNotFoundError, OSError):
        return None, "graph-query-failed"
    if not isinstance(data, list) or not all(isinstance(k, str) for k in data):
        # `--dependencies` answers in path strings. Anything else means the artifact's
        # shape moved underneath us, and guessing at it is how a wrong closure gets
        # committed — see the docstring.
        return None, "graph-query-failed"
    return data, None


def static_fingerprint(behavior, project_dir):
    """Integration-level fingerprint: the declared entry + its code-graph closure,
    tagged source: static. No entry / missing file / no edges -> coverage unknown."""
    commit = _git_head(project_dir)
    entry = behavior.get("entry")
    if not entry:
        return shape_fingerprint([], commit, reason="no-entry")
    if not os.path.exists(os.path.join(project_dir, entry)):
        sys.stderr.write(
            f"[behavior-runner] {behavior.get('behavior_id')}: entry not found: {entry}\n"
        )
        return shape_fingerprint([], commit, reason="entry-missing")
    deps, reason = _code_graph_deps(entry, project_dir)
    if deps is None:
        detail = (f"no code-graph at {project_dir} (run code-graph build)"
                  if reason == "no-graph"
                  else f"code-graph could not answer --dependencies for {entry}"
                       f" ({reason.split(': ', 1)[-1]})")
        sys.stderr.write(
            f"[behavior-runner] {behavior.get('behavior_id')}: {detail}"
            f" — cannot derive static fingerprint\n"
        )
        return shape_fingerprint([], commit, reason=reason)
    return shape_fingerprint(
        static_exercises(entry, deps), commit, source="static", confidence=STATIC_CONFIDENCE
    )


def _uncontained_address(behavior):
    """The declared address this behavior may not be acted on with, or None.

    Returns `(field, value)` — `field` is `"locator"` or `"entry"`, the two spec
    fields that name a file and the two this runner turns into a stat or an argv.

    **`escapes` and not `within`**, and the difference between them is why
    `containment` has four functions rather than one. A locator is a value
    *declared* in checked-in spec frontmatter, judged before anything is touched.
    At the moment of the check the file it names need not exist — a locator whose
    test is still being written is ordinary — and on the two argv paths nothing
    here will ever stat it at all: the string is handed to `pnpm vitest` or to
    `pytest` with `cwd=project_dir` and *they* resolve it. There is no file to
    `realpath`, so the existence-and-symlink question `within` answers cannot be
    put, and putting it anyway would refuse every honest locator that points at a
    test not yet committed. The answerable question is the lexical one `escapes`
    asks: may this declared string be joined onto a root at all. It is also the
    exact rule `verify_links` applies to these same two fields, which is the
    point — one imported body, so the two gates cannot disagree at the margin.

    What that turns away is `/etc/passwd` and `../../.ssh/id_rsa`, and the reason
    both matter is that neither reaches its sink as a path *under* the project:
    `os.path.join(project_dir, "/etc/passwd")` discards `project_dir` entirely,
    and `pnpm vitest run ../../x` is resolved by vitest against a `cwd` it is free
    to climb out of.

    A value that is not a string is refused by the same gate. Frontmatter scalars
    are not all strings — `locator: 123` parses to an int and a flow sequence to a
    list — and both used to travel to `"#" in locator` or
    `os.path.join(project_dir, entry)` and die there with an uncaught
    `TypeError`, so one malformed spec cost the fingerprints of every other
    behavior in the run. That is the same "one bad file must cost one file" rule
    `load_behaviors` already enforces on specs it cannot read.

    **Presence is `is not None`, never truthiness**, and the first spelling of
    this gate got that wrong. `if locator:` asks whether the value is *useful*,
    which is not the question — the question is whether the spec *declared* one,
    because a declared value is checked-in data and YAML hands us any scalar it
    likes. `if locator:` answers no for `locator: 0` and `locator: []` exactly as
    it does for a behavior with no locator at all, so both walked straight past
    the gate: measured, `0` still died in `parse_locator`, and `[]` — iterable, so
    `"#" in []` is merely False — got all the way into
    `subprocess.run(["pnpm", "vitest", "run", []])` before raising. The same
    mistake on `entry` costs a lie rather than a traceback, because
    `static_fingerprint`'s own `if not entry` catches it and reports `no-entry`
    about a behavior that declared one.

    The empty string is the one present value deliberately left alone: `escapes("")`
    is False, so a reason of `-escapes-project` would be a false statement about
    it, and it keeps its existing fall-through to the adapter.
    """
    locator = behavior.get("locator")
    if locator is not None:
        # `parse_locator` splits on `#`/`::` and would itself raise on a non-string,
        # so the type question is settled before the fragment is stripped.
        path = parse_locator(locator)[0] if isinstance(locator, str) else locator
        if not isinstance(path, str) or escapes(path):
            return "locator", locator
    entry = behavior.get("entry")
    if entry is not None and (not isinstance(entry, str) or escapes(entry)):
        return "entry", entry
    return None


def fingerprint_behavior(behavior, project_dir, commit):
    """Produce one behavior's fingerprint by state then level.

    `confirmed` = intent confirmed, test owed (design 03 §3): it has no
    executable test yet, so it is NEVER run — it gets an advisory STATIC
    fingerprint from its `entry` (or `unknown`/`no-entry` with none). Because it
    is never executed it can never be `test-failed`, so it never gates wrap-up.

    Containment is refused here, once, ahead of the whole ladder, because every
    sink that turns a spec-declared address into a filesystem or argv operation is
    downstream of this one function and has no other production caller:
    `vitest_argv` and `pytest_argv` (both reached only through their `run_*`
    wrappers, which are reached only from here) and `static_fingerprint`'s
    `os.path.exists(os.path.join(project_dir, entry))`. It is also the only place
    the refusal *can* live: the two argv builders return a tuple, not a
    fingerprint, so refusing inside one of them means raising, and an exception
    from a single bad spec loses the fingerprints of every other behavior in the
    run. A new caller of `static_fingerprint` or either `run_*` therefore inherits
    no guard and must come through here instead.

    `verify_links` refuses the same two fields at Tier-1 with the same imported
    rule, and that is not this module's containment: it is a different command in
    a different process, and `behavior_graph._run_behavior_runner` shells straight
    into this runner with nothing in front of it (SEC-013).

    The refusal is `unknown` with a reason, never an exception and never
    `test-failed`. No test ran, so there is no result to report, and
    `merge_fingerprint` treats `test-failed` alone as invalidating — spelling a
    refusal that way would wipe committed edges and block a commit over a spec
    typo. Every other reason preserves the prior fingerprint, which is the honest
    "no news" (ADR-005).
    """
    uncontained = _uncontained_address(behavior)
    if uncontained:
        field, value = uncontained
        sys.stderr.write(
            f"[behavior-runner] {behavior.get('behavior_id')}: {field} names a path outside"
            f" the project ({value}) — refusing to act on it\n"
        )
        return shape_fingerprint([], commit, reason=f"{field}-escapes-project")
    if behavior.get("state") == "confirmed":
        return static_fingerprint(behavior, project_dir)
    if behavior.get("level") == "unit" and behavior.get("adapter") == "vitest":
        return run_unit_behavior(behavior, project_dir)
    if behavior.get("level") == "unit" and behavior.get("adapter") in PYTEST_ADAPTERS:
        # Reached only after the `confirmed` check above, so the state-before-level ordering
        # ADR-003 relies on is unchanged: a confirmed behavior naming a Python test is still
        # unreachable here rather than merely forbidden.
        return run_pytest_behavior(behavior, project_dir)
    # Static integration path is adapter-agnostic (cucumber, native, etc.) — the
    # entry field drives the closure.
    if behavior.get("level") == "integration":
        return static_fingerprint(behavior, project_dir)
    # Non-unit/non-vitest accepted levels are produced by later plans.
    return shape_fingerprint([], commit, reason="level-deferred")


def filter_only(behaviors, only):
    """Restrict a behavior list to the given BEH ids (order: by the behavior list)."""
    if not only:
        return behaviors
    wanted = set(only)
    return [b for b in behaviors if b.get("behavior_id") in wanted]


def main():
    parser = argparse.ArgumentParser(description="Run accepted behaviors and emit fingerprints.")
    parser.add_argument("--project", required=True, help="Project root directory.")
    parser.add_argument("--specs-dir", help="Specs dir (default: <project>/knowledge-base/specs).")
    parser.add_argument("--level", help="Only run behaviors at this level (e.g. unit).")
    parser.add_argument("--states", nargs="+", default=["accepted"],
                        help="Behavior states to load (default: accepted only).")
    parser.add_argument("--only", nargs="+", metavar="BEH",
                        help="Restrict to these accepted behavior ids.")
    parser.add_argument("--list", action="store_true", help="List matching accepted behaviors and exit.")
    parser.add_argument("--emit-fingerprints", action="store_true",
                        help="Run each matching behavior and emit fingerprints JSON.")
    args = parser.parse_args()

    specs_dir = args.specs_dir or os.path.join(args.project, "knowledge-base", "specs")
    behaviors = load_behaviors(specs_dir, states=args.states, level=args.level)
    behaviors = filter_only(behaviors, args.only)

    if args.list:
        for b in behaviors:
            print(f"{b['behavior_id']}\t{b.get('level')}\t{b.get('adapter')}\t{b.get('locator')}")
        return 0

    if args.emit_fingerprints:
        commit = _git_head(args.project)
        fingerprints = {}
        for b in behaviors:
            fingerprints[b["behavior_id"]] = fingerprint_behavior(b, args.project, commit)
        print(json.dumps({
            "version": 1,
            "commit": commit,
            "fingerprints": fingerprints,
        }, indent=2))
        return 0

    print(json.dumps({"behaviors": [b["behavior_id"] for b in behaviors]}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
