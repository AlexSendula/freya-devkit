#!/usr/bin/env python3
"""Two whole-tree invariants that no per-file unit test can express.

Both are properties of the *set* of modules, not of any one of them, and both
fail invisibly on the machine that commits the violation — which is why they are
a gate rather than a review note.

INV-1 — the standard library is the whole runtime.
    knowledge-base/reference/STYLE_GUIDE.md records the rule and, until this
    file existed, recorded that nothing checked it: the census in that document
    was run by hand. The failure mode is the reason it matters. Someone writes
    `import yaml`, it works on their machine because they happen to have PyYAML
    installed, every test passes, and the zero-install promise is gone for
    everyone else. A new dependency is an ADR (ADR-005, ADR-019); an import that
    is neither standard library nor a module from this checkout is a defect.

INV-2 — a spawned program is named by a path, never by a bare name.
    `subprocess.run(["git", ...], cwd=<a repository we were pointed at>)` asks
    the operating system to search for `git`. On Windows `CreateProcess`
    searches the working directory first, so the scanned repository chooses the
    binary. Two HIGH findings on this repository are that defect: SEC-002
    (`backend_graphify.py`, where the scanned project's own settings.json arms
    the backend whose bare name is then resolved from its directory) and SEC-003
    (`audit_adapter.py` / `audit.py`, the agent-CLI workers).

    Known blind spot: this rule reads argv[0] at the call site. An argv built by
    a helper — `subprocess.run(adapter.build_argv(contract), ...)` in
    `audit.py` — is not statically decidable here, so SEC-003's bare `"claude"`
    (`audit_adapter.py:_claude_argv`) is invisible to it. The rule catches the
    shape at the boundary it can see and does not pretend to more.

Usage:
    python bin/check_invariants.py [--root DIR] [--rule INV1] [--rule INV2]

Exit codes match bin/check_skill_conformance.py: 0 clean, 1 violations,
2 the checker could not run (an unparseable module, a missing tree).
"""

from __future__ import annotations

import argparse
import ast
import ntpath
import os
import posixpath
import sys
from pathlib import Path

RULES = {
    "INV1": "import is neither standard library nor a module in this checkout — "
            "a dependency is an ADR, and its absence is invisible on the machine "
            "that commits it",
    "INV2": "subprocess argv[0] is not a path — the OS search path chooses the "
            "binary, and on Windows CreateProcess searches the working directory "
            "first",
}

#: The subprocess entry points that spawn a program. `subprocess.getoutput` and
#: friends are deliberately absent: they are shell wrappers with no argv to read.
SPAWNERS = frozenset({"run", "Popen", "call", "check_call", "check_output"})

#: Standard-library modules that ship on one platform only, so a listing of the
#: running interpreter's stdlib directory does not find the other platform's.
#: Consulted by the 3.9 fallback below and by nothing else.
PLATFORM_ONLY_STDLIB = frozenset({
    "fcntl", "grp", "msilib", "msvcrt", "nt", "ossaudiodev", "posix", "pwd",
    "readline", "resource", "spwd", "termios", "tty", "winreg", "winsound",
    "_winapi",
})

#: Bare-name argv[0] sites that exist today, as {path: {name: how many}}.
#:
#: **This is a debt marker, not an approval.** Every entry below is a real
#: instance of the defect INV-2 describes; none of them is safe because it is
#: listed here. The list exists so the rule is green on today's tree and goes
#: red the moment an eleventh site appears — which is the only way a gate can be
#: added to a tree that already violates it without either disabling the gate or
#: rewriting ten files belonging to other people.
#:
#: Of these ten, exactly one is a filed finding: `backend_graphify.py`'s
#: `graphify` is SEC-002 (High, CONFIRMED). SEC-003 — the other filed instance —
#: is *not* here, because its bare `"claude"` is assembled inside
#: `audit_adapter._claude_argv` and never appears at a call site.
#:
#: The nine `git` sites are unfiled. `git` is a weaker target than `claude` or
#: `graphify` (an attacker planting `git.exe` in a repository is attacking every
#: tool that runs there, not this one), but it is the same defect: seven of the
#: nine run with `cwd=` or `-C` pointing at a repository the operator merely
#: named.
#:
#: Counts rather than line numbers on purpose: these files are under active
#: edit, and a line number churns for reasons that have nothing to do with this
#: rule — `run_behaviors.py`'s site moved from :193 to :226 while this checker
#: was being written. A file's budget is exact in both directions; see
#: `apply_allowlist`.
#:
#: `bin/check_doc_citations.py` is the eleventh, and it is not legacy: it was
#: written the same day as this file and reproduced the defect from scratch.
#: That is the argument for the gate in one line — the shape is copied forward
#: because nothing has ever said no to it. Drop the entry the moment it is
#: fixed; the stale-entry check will insist.
KNOWN_BARE_BINARIES = {
    "bin/check_doc_citations.py": {"git": 1},
    "bin/updater.py": {"git": 1},
    "skills/freya-behavior-graph/scripts/behavior_graph.py": {"git": 1},
    "skills/freya-behavior-runner/scripts/run_behaviors.py": {"git": 1},
    "skills/freya-code-graph/scripts/backend_graphify.py": {"git": 1, "graphify": 1},
    "skills/freya-code-graph/scripts/graph_ops.py": {"git": 2},
    "skills/freya-spec-manager/scripts/drift.py": {"git": 1},
    "skills/freya-spec-manager/scripts/verify_intent.py": {"git": 1},
    "skills/freya-status/scripts/collect_status.py": {"git": 1},
}


def _listdir(path):
    """os.listdir, or [] for anything unreadable — a missing directory is not news."""
    try:
        return os.listdir(path)
    except OSError:
        return []


def _stdlib_names_by_listing():
    """Standard-library module names read out of the interpreter's own layout.

    The 3.9 fallback. `sys.stdlib_module_names` is 3.10+ and this repository's
    floor is 3.9 (STYLE_GUIDE, "Target CPython 3.9"), which CI runs — so a bare
    attribute access would make this checker the thing that breaks on the oldest
    interpreter it is supposed to defend.

    Resolving each name with `importlib.util.find_spec` would have been shorter
    and would have defeated the entire rule: `import yaml` resolves on the
    machine that has yaml installed, which is precisely the invisible failure
    INV-1 exists to make visible. So the answer comes from the interpreter's
    layout and never from what has been installed into it, and `site-packages`
    is skipped by name.
    """
    found = set(sys.builtin_module_names) | set(PLATFORM_ONLY_STDLIB)
    stdlib_dir = os.path.dirname(os.__file__)
    for entry in _listdir(stdlib_dir):
        if entry == "site-packages":
            continue
        if entry.endswith(".py"):
            found.add(entry[:-3])
        elif os.path.isfile(os.path.join(stdlib_dir, entry, "__init__.py")):
            found.add(entry)
    # Extension modules: `_socket.cpython-39-darwin.so` -> `_socket`.
    for entry in _listdir(os.path.join(stdlib_dir, "lib-dynload")):
        found.add(entry.split(".", 1)[0])
    return frozenset(name for name in found if name.isidentifier())


def stdlib_names():
    """Every standard-library module name for the running interpreter."""
    names = getattr(sys, "stdlib_module_names", None)
    if names is not None:
        return frozenset(names)
    return _stdlib_names_by_listing()


def _has_python_shebang(path):
    """Does this extensionless file start with a python shebang?"""
    try:
        with open(path, "rb") as handle:
            first = handle.readline(256)
    except OSError:
        return False
    return first.startswith(b"#!") and b"python" in first


def module_files(root):
    """Every Python module this repository ships, sorted.

    `bin/*.py` and `skills/*/scripts/*.py` are the two directories STYLE_GUIDE's
    census names. `bin/freya` joins them because it is a Python program that
    carries no `.py` — the launcher every install puts on a user's PATH — and a
    hole in the middle of the scanned set is worth less than the two lines that
    close it. It is found by its shebang rather than by name so a second
    launcher would be covered too.
    """
    files = []
    bin_dir = root / "bin"
    if bin_dir.is_dir():
        files.extend(bin_dir.glob("*.py"))
        files.extend(path for path in bin_dir.iterdir()
                     if path.is_file() and not path.suffix and _has_python_shebang(path))
    skills_dir = root / "skills"
    if skills_dir.is_dir():
        files.extend(skills_dir.glob("*/scripts/*.py"))
    return sorted(set(files))


def first_party_modules(paths):
    """Module names importable from inside this checkout.

    Any scanned module, not only a same-directory sibling: `bin/backend_setup.py`
    inserts `skills/freya-code-graph/scripts` onto `sys.path` and imports
    `settings` and `backends` out of it, deliberately and with a comment saying
    why. A strict same-directory rule would report that documented import as a
    missing dependency, which is a checker that has to be silenced on its first
    run.
    """
    return frozenset(path.stem for path in paths if path.suffix == ".py")


def imported_names(tree):
    """Yield (lineno, top-level module name, excerpt) for every import in a module.

    Every import, not only the ones at module level: `bin/backend_setup.py` and
    `bin/freya_cli.py` both import inside a function on purpose, and a
    dependency smuggled in there costs a user exactly what one at the top does.

    Only the first dotted component is yielded — `os.path` is `os`, and
    `concurrent.futures` is `concurrent` — because that is the distribution the
    import would have to come from.

    Relative imports yield nothing: `from . import x` names no top-level module,
    so the rule has nothing to judge.
    """
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                yield node.lineno, alias.name.split(".")[0], "import %s" % alias.name
        elif isinstance(node, ast.ImportFrom):
            if node.level or not node.module:
                continue
            names = ", ".join(alias.name for alias in node.names)
            yield (node.lineno, node.module.split(".")[0],
                   "from %s import %s" % (node.module, names))


def check_imports(rel, tree, stdlib, first_party):
    """INV-1 violations in one module.

    There is deliberately no carve-out for the optional-dependency shape
    (`try: import X / except ImportError:`). Measured on 2026-08-21: the tree
    contains no such import — the single `except ImportError` in the suite,
    `bin/freya_cli.py:184`, guards `import installer`, a module of this
    checkout. Exempting a shape nothing uses would only create the hole a future
    `try: import yaml` walks through, and this repository's answer to a genuine
    optional dependency is an ADR, not a bare `except`.
    """
    return [(rel, lineno, "INV1", excerpt)
            for lineno, name, excerpt in imported_names(tree)
            if name not in stdlib and name not in first_party]


def subprocess_aliases(tree):
    """(module names, function names) this module can spawn a program through.

    Both binding forms, because either one hides the call from a checker that
    only knows the other: `import subprocess as sp` makes the spawn `sp.run`,
    and `from subprocess import check_output` makes it a bare `check_output`.
    """
    modules, functions = set(), set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                if alias.name == "subprocess":
                    modules.add(alias.asname or "subprocess")
        elif isinstance(node, ast.ImportFrom):
            if node.level or node.module != "subprocess":
                continue
            for alias in node.names:
                if alias.name in SPAWNERS:
                    functions.add(alias.asname or alias.name)
    return modules, functions


def spawn_calls(tree):
    """Yield (Call node, display name) for every subprocess spawn in a module."""
    modules, functions = subprocess_aliases(tree)
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        func = node.func
        if (isinstance(func, ast.Attribute) and func.attr in SPAWNERS
                and isinstance(func.value, ast.Name) and func.value.id in modules):
            yield node, "%s.%s" % (func.value.id, func.attr)
        elif isinstance(func, ast.Name) and func.id in functions:
            yield node, func.id


def module_constants(tree):
    """Module-level `NAME = "literal"` bindings.

    Without these the check reads `subprocess.run([BINARY, ...])` as
    unresolvable and says nothing — and `BINARY` is `'graphify'`
    (`backend_graphify.py:46`), the one bare-name site that is already a filed
    HIGH finding. A constant declared forty lines up is not a resolver.
    """
    constants = {}
    for node in tree.body:
        if not isinstance(node, ast.Assign):
            continue
        value = node.value
        if not (isinstance(value, ast.Constant) and isinstance(value.value, str)):
            continue
        for target in node.targets:
            if isinstance(target, ast.Name):
                constants[target.id] = value.value
    return constants


def argv0_node(call):
    """The AST node holding argv[0], or None when the call's shape hides it.

    None means "not decidable here", never "fine": a `Starred` head
    (`[*prefix, "x"]`), a name bound to a parameter, and a helper's return value
    are all unreadable at the call site and all left alone.
    """
    if not call.args:
        return None
    first = call.args[0]
    # `["git"] + cmd` — the head of the concatenation is still the program.
    while isinstance(first, ast.BinOp) and isinstance(first.op, ast.Add):
        first = first.left
    if isinstance(first, (ast.List, ast.Tuple)):
        if not first.elts or isinstance(first.elts[0], ast.Starred):
            return None
        return first.elts[0]
    if isinstance(first, ast.Constant) and isinstance(first.value, str):
        # A string argv: POSIX takes the whole string as the program, and under
        # shell=True the shell searches PATH for its first word. Either way the
        # name is resolved by a search this rule is about.
        return first
    return None


def resolve_binary(node, constants):
    """The literal argv[0] this node names, or None when it is not statically known."""
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return node.value
    if isinstance(node, ast.Name):
        return constants.get(node.id)
    return None


def is_absolute(text):
    """Absolute under either platform's rules — and under either interpreter's.

    `os.path.isabs` answers for the platform the *checker* runs on, and CI runs
    this on Linux and on Windows. `C:\\tools\\git.exe` reads as relative to
    posixpath, so one source file would be a violation on one leg of the matrix
    and clean on the other, for a reason nothing in the output would explain.

    `posixpath.isabs(text) or ntpath.isabs(text)` was the fix for that, and it
    only got half of it: CI also runs 3.9 and 3.13, and `ntpath.isabs` changed
    in 3.13 so a rooted path with no drive stopped being absolute. Measured over
    an eleven-case table on 3.9.6, 3.12.5 and 3.13.5, the union answers True for
    `\\tools\\git.exe` on the first two and False on the third — the same file,
    clean on one interpreter and a violation on the next, which is the property
    this docstring already claimed the function did not have.

    So the two unambiguous shapes are judged directly instead: a POSIX absolute
    path, or a Windows path carrying both a drive (or a UNC share) and a root.
    That form gave identical answers on all three interpreters for all eleven
    cases. It is the same predicate as
    `skills/freya-code-graph/scripts/containment.py:is_anchored`, written out
    again rather than imported for the reason `bin/freya_cli.py:_escapes` gives:
    this checker has to run against a skill tree it may be about to condemn.
    """
    if posixpath.isabs(text):
        return True
    drive, rest = ntpath.splitdrive(text)
    return bool(drive) and rest[:1] in ("\\", "/")


def is_resolved(node, constants):
    """True when argv[0] is the running interpreter or an absolute path."""
    if (isinstance(node, ast.Attribute) and node.attr == "executable"
            and isinstance(node.value, ast.Name) and node.value.id == "sys"):
        return True
    literal = resolve_binary(node, constants)
    return literal is not None and is_absolute(literal)


def bare_binaries(rel, tree):
    """Yield (rel, lineno, name, excerpt) for each unresolved argv[0] in a module."""
    constants = module_constants(tree)
    for call, display in spawn_calls(tree):
        node = argv0_node(call)
        if node is None or is_resolved(node, constants):
            continue
        literal = resolve_binary(node, constants)
        if literal is None:
            continue
        kind = "relative path" if ("/" in literal or "\\" in literal) else "bare name"
        yield rel, call.lineno, literal, "%s argv[0]=%r (%s)" % (display, literal, kind)


def apply_allowlist(sites, allow):
    """Turn raw INV-2 sites into violations, minus the ones already accounted for.

    A file's budget is exact in both directions. An eleventh bare `git` in a
    file allowed two is reported, which is the point. So is an allowlist entry
    with no site left to match — paying the debt down has to update the marker,
    or the marker rots into a record of a defect that was fixed years ago and a
    licence for one that has not been.
    """
    budget = {path: dict(names) for path, names in allow.items()}
    violations = []
    for rel, lineno, name, excerpt in sites:
        remaining = budget.get(rel, {}).get(name, 0)
        if remaining > 0:
            budget[rel][name] = remaining - 1
            continue
        violations.append((rel, lineno, "INV2", excerpt))
    for rel in sorted(budget):
        for name in sorted(budget[rel]):
            left = budget[rel][name]
            if left > 0:
                violations.append((
                    rel, 0, "INV2",
                    "allowlist expects %d more %r site(s) than exist — "
                    "fixed? update KNOWN_BARE_BINARIES" % (left, name),
                ))
    return violations


def is_test_module(path):
    """Is this a test module?

    INV-2 skips them, and the reason is the threat, not convenience. The defect
    is the toolkit spawning a program while its working directory is a
    repository it was merely pointed at — `audit.py`'s `cwd=args.project`,
    `backend_graphify`'s `cwd=self.project_dir`. A test spawns `git` inside a
    `tempfile.mkdtemp()` tree it built itself two lines earlier. Scanning them
    would add two dozen entries to the allowlist and bury the ten that matter.
    INV-1 has no such exemption: a test that imports pytest breaks the
    zero-install promise exactly as hard as a script that does.
    """
    return path.name.startswith("test_")


def scan(root, rules=None, allow=None):
    """Scan the shipped Python tree. Returns sorted (rel, lineno, rule, excerpt)."""
    if allow is None:
        allow = KNOWN_BARE_BINARIES
    root = Path(root)
    paths = module_files(root)
    stdlib = stdlib_names()
    first_party = first_party_modules(paths)

    violations = []
    sites = []
    for path in paths:
        rel = path.relative_to(root).as_posix()
        source = path.read_text(encoding="utf-8")
        try:
            tree = ast.parse(source, filename=str(path))
        except SyntaxError as exc:
            raise ValueError("%s: %s" % (rel, exc)) from exc
        violations.extend(check_imports(rel, tree, stdlib, first_party))
        if not is_test_module(path):
            sites.extend(bare_binaries(rel, tree))

    violations.extend(apply_allowlist(sites, allow))
    if rules is not None:
        violations = [item for item in violations if item[2] in rules]
    return sorted(violations)


def main(argv=None):
    parser = argparse.ArgumentParser(
        description="Check the tree-wide invariants no unit test can express."
    )
    parser.add_argument("--root", type=Path, default=None,
                        help="Suite root (default: this checkout)")
    parser.add_argument("--rule", action="append", choices=sorted(RULES),
                        help="Only report these rules (repeatable)")
    parser.add_argument(
        "--no-allowlist", action="store_true",
        help="Ignore KNOWN_BARE_BINARIES and report every INV2 site — the debt census",
    )
    args = parser.parse_args(argv)

    root = args.root if args.root is not None else Path(__file__).resolve().parents[1]

    try:
        violations = scan(root,
                          rules=set(args.rule) if args.rule else None,
                          allow={} if args.no_allowlist else None)
    except (OSError, ValueError) as exc:
        print("check-invariants: %s" % exc, file=sys.stderr)
        return 2

    for rel, lineno, rule, excerpt in violations:
        print("%s:%d: %s: %s" % (rel, lineno, rule, excerpt))

    if violations:
        counts = {}
        for _, _, rule, _ in violations:
            counts[rule] = counts.get(rule, 0) + 1
        print(file=sys.stderr)
        for rule in sorted(counts):
            print("  %s (%d): %s" % (rule, counts[rule], RULES[rule]), file=sys.stderr)
        print("\n%d violation(s)." % len(violations), file=sys.stderr)
        return 1

    print("tree invariants hold.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
