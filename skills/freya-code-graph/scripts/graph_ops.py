#!/usr/bin/env python3
"""
Code Graph Operations

Build and query dependency graphs for code impact analysis.

Usage:
    python graph_ops.py --build [--dir /path/to/project]
    python graph_ops.py --update [--commit HEAD~1]
    python graph_ops.py --query src/lib/auth.ts
    python graph_ops.py --impact src/lib/auth.ts
    python graph_ops.py --dependents src/lib/auth.ts
    python graph_ops.py --dependencies src/lib/auth.ts
    python graph_ops.py --clear
"""

import argparse
import json
import os
import posixpath
import re
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path, PurePosixPath
from typing import Any, Dict, List, Optional, Sequence, Set

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import substrate  # noqa: E402  — the contract this module's CodeGraph implements


# File patterns by language
FILE_PATTERNS = {
    'typescript': ['**/*.ts', '**/*.tsx'],
    'javascript': ['**/*.js', '**/*.jsx'],
    'python': ['**/*.py'],
    'go': ['**/*.go'],
}

# `CATEGORY_PATTERNS` and `_categorize_file` lived here until 2026-08-19. Every file entry
# carried a path-guessed `category` that no caller ever read — three unrelated things in
# this repo are called "category", and the live two are security findings and spec
# contexts. Removed under CD-12; existing caches keep the key harmlessly.

# Import patterns by language
IMPORT_PATTERNS = {
    # `(?:type\s+)?` appears on the three statement forms that accept it. A type-only
    # import is a real dependency — the importer does not compile without it — and
    # omitting it hid 16 edges on the testbed alone. It is optional, so the plain
    # forms keep matching exactly as before.
    'typescript': [
        # import { x } from './y'   /   import type { X } from './y'
        r'import\s+(?:type\s+)?\{[^}]*\}\s+from\s+[\'"]([^\'"]+)[\'"]',
        # import x from './y'       /   import type X from './y'
        r'import\s+(?:type\s+)?\w+\s+from\s+[\'"]([^\'"]+)[\'"]',
        # import * as x from './y'
        r'import\s+(?:type\s+)?\*\s+as\s+\w+\s+from\s+[\'"]([^\'"]+)[\'"]',
        # export * from './y'       /   export type { D } from './y'
        r'export\s+(?:type\s+)?(?:\*|\{[^}]*\})\s+from\s+[\'"]([^\'"]+)[\'"]',
        # require('./y')
        r'require\s*\(\s*[\'"]([^\'"]+)[\'"]\s*\)',
        # import('./y')
        r'import\s*\(\s*[\'"]([^\'"]+)[\'"]\s*\)',
    ],
    'javascript': [
        # Same as TypeScript (JS is subset). `type` cannot appear in plain JS, but
        # keeping the two lists identical is what stops them drifting apart.
        r'import\s+(?:type\s+)?\{[^}]*\}\s+from\s+[\'"]([^\'"]+)[\'"]',
        r'import\s+(?:type\s+)?\w+\s+from\s+[\'"]([^\'"]+)[\'"]',
        r'import\s+(?:type\s+)?\*\s+as\s+\w+\s+from\s+[\'"]([^\'"]+)[\'"]',
        r'export\s+(?:type\s+)?(?:\*|\{[^}]*\})\s+from\s+[\'"]([^\'"]+)[\'"]',
        r'require\s*\(\s*[\'"]([^\'"]+)[\'"]\s*\)',
        r'import\s*\(\s*[\'"]([^\'"]+)[\'"]\s*\)',
    ],
    'python': [
        # from x import y   (also covers `from .x import y` and `from ..x import y`)
        r'from\s+([\w.]+)\s+import',
        # import x
        r'^import\s+([\w.]+)',
        # A third pattern for `from . import x` used to sit here. Its capture group
        # started *after* the dots, so it returned the rest of the statement rather
        # than a module: `from . import leaf` yielded the specifier 'import', which
        # was then reported as a third-party package literally named `import`. It
        # produced 66 junk entries across the measured repos and not one real edge.
        # `from . import x` is still missed — the module name lives in the import
        # clause, which needs clause capture to read — but it is now missed silently
        # rather than answered wrongly. Tracked in docs/backlog.md.
    ],
    'go': [
        # import "module/path"
        r'import\s+[\'"]([^\'"]+)[\'"]',
        # import alias "module/path"
        r'import\s+\w+\s+[\'"]([^\'"]+)[\'"]',
        # multi-line import ( ... )
        r'[\'"]([^\'"]+)[\'"]',
    ],
}

# Export patterns by language
EXPORT_PATTERNS = {
    'typescript': [
        r'export\s+(?:async\s+)?function\s+(\w+)',
        r'export\s+const\s+(\w+)',
        r'export\s+class\s+(\w+)',
        r'export\s+interface\s+(\w+)',
        r'export\s+type\s+(\w+)',
        r'export\s+enum\s+(\w+)',
        r'export\s+\{([^}]+)\}',
    ],
    'javascript': [
        r'export\s+(?:async\s+)?function\s+(\w+)',
        r'export\s+const\s+(\w+)',
        r'export\s+class\s+(\w+)',
        r'export\s+\{([^}]+)\}',
        r'module\.exports\s*=\s*\{([^}]+)\}',
        r'exports\.(\w+)\s*=',
    ],
    'python': [
        # Python doesn't have explicit exports, but we can track __all__
        r'__all__\s*=\s*\[([^\]]+)\]',
    ],
    'go': [
        # Go exports are capitalised functions/types
        r'func\s+([A-Z]\w+)',
        r'type\s+([A-Z]\w+)',
        r'var\s+([A-Z]\w+)',
        r'const\s+([A-Z]\w+)',
    ],
}


# Import edges that name a *specifier*, not a file in this project. Their tail is
# whatever the source file wrote, so it is reported verbatim and never re-keyed.
IMPORT_SIGNALS = ('external:', 'unresolved:')

# Bump whenever the directory rules below change meaning. Cached `rule`/`gitignore`
# verdicts in classifications.json are discarded on a mismatch, so a rule fix reaches
# projects that were already graphed instead of only fresh clones. Any string works;
# a date is readable in the file.
RULES_VERSION = '2026-08-19'


def _gitignore_pattern_matches(rel_path: str, parts: Sequence[str], pattern: str) -> bool:
    """Does one already-de-negated gitignore pattern match `rel_path`?

    Anchoring is the part that matters and the part that was missing. In git, a pattern
    containing a slash anywhere but the end is relative to the `.gitignore` — `/lib` and
    `lib/auth` mean the root's — while a bare name floats and matches at any depth. The
    parser used to strip the leading slash before anything could tell the difference, so
    `/lib` silently deleted `src/lib/` too.
    """
    from fnmatch import fnmatch

    body = pattern.strip('/')
    if not body:
        return False

    # A slash anywhere except a lone trailing one anchors the pattern to the root.
    anchored = pattern.startswith('/') or '/' in pattern.rstrip('/')

    if body.startswith('**/'):
        # Explicitly floating, whatever else it contains.
        tail = body[3:]
        return any(fnmatch('/'.join(parts[i:]), tail)
                   or fnmatch('/'.join(parts[i:]), tail + '/*')
                   for i in range(len(parts)))

    if anchored:
        # The pattern itself, or anything beneath it when it names a directory.
        return fnmatch(rel_path, body) or fnmatch(rel_path, body + '/*')

    # Floating: any single path component.
    return any(fnmatch(part, body) for part in parts)


def gitignore_excludes(rel_path: str, patterns: List[str]) -> bool:
    """Does `.gitignore` exclude the project-relative `rel_path`?

    One implementation, because there used to be two. `_should_exclude` filtered files and
    `_classify_with_rules` filtered whole directories, each with its own matching rules, and
    they disagreed — so a path could be classified one way and filtered the other. Both also
    fell back to an unanchored substring test, which is what made a `.next` entry exclude
    `app/api/auth/[...nextauth]/route.ts`.

    **Last match wins**, as in git, which is what makes `!` work: `config/*` followed by
    `!config/default.ts` keeps `default.ts`. Discarding negations meant excluding files git
    tracks — and then emitting dangling edges to them from files that import them.

    An approximation, not an implementation. `fnmatch`'s `*` crosses `/` where git's does not,
    so a wildcard pattern can match deeper than git would. That errs toward excluding, which is
    the direction to be careful about, so patterns are kept narrow above: only an explicit
    `**/` prefix floats a slash-bearing pattern.
    """
    parts = PurePosixPath(rel_path).parts
    excluded = False
    for raw in patterns:
        pat = (raw or '').strip()
        if not pat or pat.startswith('#'):
            continue
        negated = pat.startswith('!')
        if negated:
            pat = pat[1:].strip()
            if not pat:
                continue
        if _gitignore_pattern_matches(rel_path, parts, pat):
            excluded = not negated
    return excluded


# The regenerable files in knowledge-base/.graph/, ignored by name. Kept byte
# identical to behavior_graph.py's copy: whichever skill runs first writes it,
# and a drift between the two would make the file depend on run order.
CACHE_IGNORED = ('graph.json', 'graph.*.json', 'classifications.json')

CACHE_GITIGNORE = (
    '# Generated code-graph cache — do not commit.\n'
    '#\n'
    '# behavior.json is deliberately NOT listed. Its observed coverage is captured\n'
    '# by running the test suite, so it cannot be rebuilt by re-reading source the\n'
    '# way these can — committing it is what gives a fresh clone a blast radius.\n'
    '#\n'
    '# graph.*.json is the per-backend artifact (CD-17): each substrate writes its own,\n'
    '# so a swap can be diffed instead of destroying the baseline it should be measured\n'
    '# against. graph.json stays the active graph that other skills read.\n'
    + '\n'.join(CACHE_IGNORED) + '\n'
)


def _is_legacy_blanket_ignore(text: str) -> bool:
    """True for the pre-0.2.1 `*` file, whichever skill wrote it.

    Both writers used to write only when the file was absent, so an
    already-onboarded project would otherwise keep ignoring behavior.json
    forever. Matching on content — rather than just overwriting — leaves a
    hand-edited file alone.
    """
    lines = [ln.strip() for ln in text.splitlines()
             if ln.strip() and not ln.lstrip().startswith('#')]
    return lines == ['*']


def _write_cache_gitignore(path: Any) -> None:
    """Write the cache .gitignore, upgrading a legacy blanket but never a custom one."""
    try:
        if path.exists() and not _is_legacy_blanket_ignore(
                path.read_text(encoding='utf-8', errors='replace')):
            return
    except OSError:
        return
    path.write_text(CACHE_GITIGNORE, encoding='utf-8')


def normalize_key(path: Any) -> str:
    """A project-relative path, as a stable graph key.

    posixpath, not os.path, and backslashes folded in by hand — the same rule and
    for the same reason as `normalize_file()` in the security scanner's
    audit_engine.py. `Path.relative_to()` returns a native path, so on Windows
    `str(rel)` is `src\\b.ts`. The first Windows CI run caught what that costs:
    the graph keyed `weirddir\\x.ts`, every forward-slash lookup missed, and
    `--query`/`--dependencies` reported nothing for files the build had just
    indexed. The damage does not stop at this skill — behavior-graph intersects
    these keys with behavior records' `exercises[].path`, and behavior-runner
    reads `graph.json` keys directly, both keyed on forward slashes; a Windows
    graph silently fails to intersect and blast radius comes back empty.

    `os.path.normpath` is the trap, not the fix: on Windows it rewrites a
    perfectly good `src/b.ts` *into* `src\\b.ts`, so the bug survives on the one
    host that has it. The fold is unconditional because a key can arrive from a
    Windows-written cache while running on Linux (and vice versa) — the host
    that reads must not decide what a key looks like.

    The cost of "unconditional", stated plainly: on POSIX a backslash is a
    legal filename character, so a file genuinely named `weird\name.ts` now
    shares a key with `weird/name.ts` and one silently overwrites the other.
    Accepted for the same reason audit_engine accepts it: a key that means
    different things on different hosts is not an interchange key, and a
    backslash in a POSIX source filename is vanishingly rare next to the
    certainty of breaking every lookup on Windows.
    """
    text = str(path).replace('\\', '/')
    return posixpath.normpath(text) if text else text


def normalize_import(value: str) -> str:
    """Normalize a resolved import edge; `external:`/`unresolved:` pass through."""
    return value if value.startswith(IMPORT_SIGNALS) else normalize_key(value)


def migrate_separators(graph: Dict[str, Any]) -> Dict[str, Any]:
    """Fold a cache written with native Windows separators back to POSIX keys.

    A graph.json built by an earlier release on Windows keys files as `src\\b.ts`
    and its `imports`/`dependents` reference that same form. Normalizing only the
    write path would leave those caches permanently unreadable — every lookup a
    fixed build makes would miss — which is the worst outcome available, since it
    looks exactly like a project with no dependencies. So the read path migrates
    too, and the next `--build`/`--update` writes the corrected form back.

    Cheaper than invalidating the cache and cheaper than a schema-version bump:
    the guard means a graph built on any POSIX host, or by this version anywhere,
    pays one scan of the key list and returns untouched.
    """
    files = graph.get('files')
    if not isinstance(files, dict) or not any('\\' in key for key in files):
        return graph

    migrated: Dict[str, Any] = {}
    for key, info in files.items():
        if isinstance(info, dict):
            info = {
                **info,
                'imports': [normalize_import(i) for i in info.get('imports', [])],
                'dependents': [normalize_key(d) for d in info.get('dependents', [])],
            }
        migrated[normalize_key(key)] = info
    graph['files'] = migrated
    return graph


class CodeGraph:
    """Manages the dependency graph for a codebase."""

    def __init__(self, project_dir: Optional[str] = None):
        self.project_dir = Path(project_dir or os.getcwd()).resolve()
        self.graph_dir = self.project_dir / 'knowledge-base' / '.graph'
        self.graph_path = self.graph_dir / 'graph.json'
        self.classifications_path = self.graph_dir / 'classifications.json'
        self.graph: Dict[str, Any] = {}
        self.classifications: Dict[str, Any] = {}
        self._alias_cache: Optional[List] = None
        self._alias_base: Path = self.project_dir
        # parent dir -> its exact on-disk names, for the case check in _is_real_file.
        # Per-instance rather than global: a long-lived process graphing two projects must
        # not serve one's listing to the other, and a build is short enough that staleness
        # within a single run is not a concern.
        self._dir_listing_cache: Dict[Path, Any] = {}
        # workspace package name -> directory; None until the manifests are read once
        self._workspace_cache: Optional[Dict[str, Path]] = None

    # -------------------------------------------------------------------------
    # The substrate contract (see substrate.py). This class is freya's first
    # backend — the stdlib-only floor that is always installed.
    # -------------------------------------------------------------------------

    name = 'homegrown'

    def coverage(self) -> substrate.Coverage:
        """What this backend actually handles — contract obligation 4.

        `relations` claims only `imports`, because that is genuinely all it emits. It resolves
        module references between files; it has no notion of a symbol, so it must not claim
        `calls` or `inherits` merely because the vocabulary contains them. Overclaiming here is
        how a caller ends up trusting a query the backend cannot answer.
        """
        extensions = sorted({
            os.path.splitext(pattern)[1]
            for patterns in FILE_PATTERNS.values()
            for pattern in patterns
        })
        return substrate.Coverage(
            languages=FILE_PATTERNS.keys(),
            extensions=extensions,
            relations=('imports',),
            # Deletions are handled correctly: `update` removes the entry and rebuilds every
            # dependent. This is the bar spec §9.2 holds other backends to.
            incremental=True,
        )

    def available(self) -> bool:
        """Always. The floor exists for the machine that cannot install anything."""
        return True

    def project_exclusions(self) -> substrate.Exclusions:
        """The exclusions this project declares, as a contract input.

        Obligation 6 says a backend is *given* its exclusions rather than deciding them, on the
        grounds that "vendor/ is not mine" is true whichever parser runs. This assembles that
        input from the two places the project states it: directory classifications, and
        `.gitignore`.
        """
        classified = (self._load_classifications().get('directories') or {})
        return substrate.Exclusions(
            directories=[name for name, verdict in classified.items()
                         if isinstance(verdict, dict) and verdict.get('type') == 'exclude'],
            patterns=self._parse_gitignore(),
            matcher=gitignore_excludes,
        )

    def _ensure_graph_dir(self) -> None:
        """Create the graph cache dir and write its `.gitignore` (F8).

        The two files this skill generates are a parse cache — rebuildable from
        source in seconds, and large enough that committing them would put an
        unreadable, conflict-prone diff in a large share of commits. They are
        ignored by name so adopting projects never touch their root `.gitignore`.

        **Not a blanket `*`.** F8 predates `behavior.json`, which later landed in
        this same directory and inherited an ignore rule written before it
        existed. It is not a parse cache: its observed coverage is captured by
        running the test suite, so it cannot be rebuilt by re-reading source. A
        `*` here silently costs a fresh clone every observed fingerprint it has.
        """
        self.graph_dir.mkdir(parents=True, exist_ok=True)
        _write_cache_gitignore(self.graph_dir / '.gitignore')

    def _get_git_commit(self) -> Optional[str]:
        """Get current git commit hash."""
        try:
            result = subprocess.run(
                ['git', 'rev-parse', 'HEAD'],
                cwd=self.project_dir,
                capture_output=True,
                text=True,
            )
            if result.returncode == 0:
                return result.stdout.strip()[:12]
        except Exception:
            pass
        return None

    def _get_changed_files(self, since_commit: str) -> List[str]:
        """Get list of files changed since a commit."""
        try:
            result = subprocess.run(
                ['git', 'diff', f'{since_commit}..HEAD', '--name-only'],
                cwd=self.project_dir,
                capture_output=True,
                text=True,
            )
            if result.returncode == 0:
                return [f.strip() for f in result.stdout.strip().split('\n') if f.strip()]
        except Exception:
            pass
        return []

    def _detect_language(self, file_path: Path) -> Optional[str]:
        """Detect language from file extension."""
        ext = file_path.suffix.lower()
        mapping = {
            '.ts': 'typescript',
            '.tsx': 'typescript',
            '.js': 'javascript',
            '.jsx': 'javascript',
            '.py': 'python',
            '.go': 'go',
        }
        return mapping.get(ext)

    # -------------------------------------------------------------------------
    # Import resolution: relative (cwd-independent) + tsconfig/jsconfig aliases
    # -------------------------------------------------------------------------

    @staticmethod
    def _strip_jsonc(text: str) -> str:
        """JSONC -> JSON: drop `//` and `/* */` comments and trailing commas.

        String-aware: comment markers inside string literals are preserved, so values
        like the `@/*` alias or a `**/*.ts` glob (which contain `/*` and `*/`) are not
        mistaken for comments. Stdlib-only, scoped to tsconfig/jsconfig.
        """
        out = []
        i, n = 0, len(text)
        in_str = False
        quote = ''
        while i < n:
            c = text[i]
            if in_str:
                out.append(c)
                if c == '\\' and i + 1 < n:        # keep escaped char verbatim
                    out.append(text[i + 1])
                    i += 2
                    continue
                if c == quote:
                    in_str = False
                i += 1
                continue
            if c in ('"', "'"):
                in_str = True
                quote = c
                out.append(c)
                i += 1
                continue
            if c == '/' and i + 1 < n and text[i + 1] == '/':
                i += 2
                while i < n and text[i] != '\n':
                    i += 1
                continue
            if c == '/' and i + 1 < n and text[i + 1] == '*':
                i += 2
                while i + 1 < n and not (text[i] == '*' and text[i + 1] == '/'):
                    i += 1
                i += 2
                continue
            out.append(c)
            i += 1
        # Trailing commas: safe now that comments are gone (strings preserved above).
        return re.sub(r',(\s*[}\]])', r'\1', ''.join(out))

    def _load_path_aliases(self) -> List:
        """Load `(pattern, [targets])` path aliases from tsconfig/jsconfig (cached).

        Sets `self._alias_base` to the resolved `baseUrl`. One config only; `extends`
        is intentionally not followed (out of scope — see substrate-fix plan).
        """
        if self._alias_cache is not None:
            return self._alias_cache
        aliases: List = []
        base_url = '.'
        for name in ('tsconfig.json', 'jsconfig.json'):
            cfg = self.project_dir / name
            if not cfg.exists():
                continue
            try:
                data = json.loads(self._strip_jsonc(cfg.read_text(encoding='utf-8')))
            except Exception:
                data = None
            if isinstance(data, dict):
                co = data.get('compilerOptions', {}) or {}
                base_url = co.get('baseUrl', '.') or '.'
                for pattern, targets in (co.get('paths', {}) or {}).items():
                    if isinstance(targets, list):
                        aliases.append((pattern, targets))
            break
        self._alias_base = (self.project_dir / base_url).resolve()
        self._alias_cache = aliases
        return aliases

    def _matches_alias(self, import_path: str) -> bool:
        for pattern, _ in self._load_path_aliases():
            if '*' in pattern:
                if import_path.startswith(pattern.split('*', 1)[0]):
                    return True
            elif import_path == pattern:
                return True
        return False

    def _resolve_fs(self, resolved: Path) -> Optional[str]:
        """Resolve a base path to a real project-relative source file (suffixes/index)."""
        candidates = [
            resolved,
            resolved.with_suffix('.ts'),
            resolved.with_suffix('.tsx'),
            resolved.with_suffix('.js'),
            resolved.with_suffix('.jsx'),
            resolved.with_suffix('.py'),
            resolved / 'index.ts',
            resolved / 'index.tsx',
            resolved / 'index.js',
            resolved / 'index.jsx',
            resolved / '__init__.py',
        ]
        for candidate in candidates:
            try:
                rel = candidate.relative_to(self.project_dir)
            except ValueError:
                continue
            # A file, and spelled the way it is spelled on disk. Two separate traps:
            # the bare path is the first candidate and a *directory* satisfies exists(),
            # so `from './accessibility'` used to resolve to the folder and never reach
            # its index; and on a case-insensitive filesystem `./Utils` matches utils.ts,
            # producing an edge that names no node in the graph.
            if self._is_real_file(candidate):
                return normalize_key(rel)
        return None

    def _load_workspace_packages(self) -> Dict[str, Path]:
        """Map each workspace package name to its directory. Empty if not a monorepo.

        In a monorepo the cross-package import *is* the architecture — `apps/mobile` depending
        on `packages/domain` is the relationship anyone asking for blast radius cares about.
        Without this it resolves to `external:@scope/name`, indistinguishable from a dependency
        on something off npm, and the graph quietly reports the repo as a set of unrelated
        islands (CD-18).

        npm and yarn declare membership in `package.json#workspaces`, as a list or under a
        `packages` key. pnpm uses `pnpm-workspace.yaml`, read here with a deliberately narrow
        line parser rather than a YAML dependency: only a top-level `packages:` block of
        `- pattern` entries. Anything more elaborate is treated as "not a workspace root",
        which costs edges rather than inventing them.
        """
        if self._workspace_cache is not None:
            return self._workspace_cache

        packages = {}  # type: Dict[str, Path]
        globs = self._workspace_globs()
        for pattern in globs:
            pattern = pattern.strip().strip('"\'').rstrip('/')
            if not pattern or pattern.startswith('!'):
                continue
            try:
                candidates = sorted(self.project_dir.glob(pattern))
            except (ValueError, OSError):
                continue
            for directory in candidates:
                if not directory.is_dir():
                    continue
                manifest = directory / 'package.json'
                if not manifest.is_file():
                    continue
                try:
                    with open(manifest, encoding='utf-8') as handle:
                        name = json.load(handle).get('name')
                except (OSError, ValueError):
                    continue
                if isinstance(name, str) and name:
                    packages.setdefault(name, directory)

        self._workspace_cache = packages
        return packages

    def _workspace_globs(self) -> List[str]:
        """The workspace patterns this repo declares, from whichever tool declares them."""
        globs = []  # type: List[str]

        manifest = self.project_dir / 'package.json'
        if manifest.is_file():
            try:
                with open(manifest, encoding='utf-8') as handle:
                    declared = json.load(handle).get('workspaces')
            except (OSError, ValueError):
                declared = None
            if isinstance(declared, list):
                globs.extend(str(p) for p in declared if isinstance(p, str))
            elif isinstance(declared, dict):
                # yarn's object form
                entries = declared.get('packages')
                if isinstance(entries, list):
                    globs.extend(str(p) for p in entries if isinstance(p, str))

        pnpm = self.project_dir / 'pnpm-workspace.yaml'
        if pnpm.is_file():
            try:
                lines = pnpm.read_text(encoding='utf-8').splitlines()
            except OSError:
                lines = []
            in_packages = False
            for line in lines:
                stripped = line.strip()
                if not stripped or stripped.startswith('#'):
                    continue
                if not line[:1].isspace():
                    # A new top-level key ends the block. The testbed's file declares only
                    # `onlyBuiltDependencies`, so this is what stops it being read as a
                    # workspace root.
                    in_packages = stripped.startswith('packages:')
                    continue
                if in_packages and stripped.startswith('- '):
                    globs.append(stripped[2:].strip())

        return globs

    def _resolve_workspace_import(self, import_path: str) -> Optional[str]:
        """Resolve `@scope/pkg` or `@scope/pkg/sub/path` to a file, or None."""
        packages = self._load_workspace_packages()
        if not packages:
            return None

        # Longest name first: `@acme/domain-utils` must not be matched by `@acme/domain`.
        for name in sorted(packages, key=len, reverse=True):
            if import_path != name and not import_path.startswith(name + '/'):
                continue
            root = packages[name]
            subpath = import_path[len(name):].lstrip('/')
            if subpath:
                return self._resolve_fs(root / subpath)
            # A bare package name: honour `main`, then fall back to index resolution.
            manifest = root / 'package.json'
            try:
                with open(manifest, encoding='utf-8') as handle:
                    main = json.load(handle).get('main')
            except (OSError, ValueError):
                main = None
            if isinstance(main, str) and main:
                hit = self._resolve_fs(root / main)
                if hit:
                    return hit
            return self._resolve_fs(root)
        return None

    def _names_a_workspace_package(self, import_path: str) -> bool:
        """Does this specifier name a package this repo owns?

        Separates a genuine gap from a third-party dependency: a failed `@acme/domain/...`
        could only ever have meant something in this repo, so it is `unresolved:`, not
        `external:`.
        """
        return any(import_path == name or import_path.startswith(name + '/')
                   for name in self._load_workspace_packages())

    def _resolve_alias(self, import_path: str) -> Optional[str]:
        """Resolve a bare specifier via tsconfig/jsconfig `paths`, or None."""
        for pattern, targets in self._load_path_aliases():
            if '*' in pattern:
                prefix = pattern.split('*', 1)[0]
                if not import_path.startswith(prefix):
                    continue
                tail = import_path[len(prefix):]
                for tgt in targets:
                    hit = self._resolve_fs(self._alias_base / tgt.replace('*', tail))
                    if hit:
                        return hit
            elif import_path == pattern:
                for tgt in targets:
                    hit = self._resolve_fs(self._alias_base / tgt)
                    if hit:
                        return hit
        return None

    def _is_real_file(self, candidate: Path) -> bool:
        """Is `candidate` a file whose on-disk name matches exactly, case included?

        macOS and Windows filesystems are case-insensitive, so `Path('Utils.py').is_file()` is
        true when the file on disk is `utils.py`. Trusting that resolves the import to a key
        spelled the way the *import statement* spelled it — naming a node the graph does not
        contain, and making the graph differ between a macOS dev host and Linux CI.

        The directory listing is cached because this runs once per candidate per import, and
        an uncached `listdir` would turn resolution into a per-import directory scan.
        """
        try:
            if not candidate.is_file():
                return False
        except OSError:
            return False
        parent = candidate.parent
        names = self._dir_listing_cache.get(parent)
        if names is None:
            try:
                names = frozenset(os.listdir(parent))
            except OSError:
                names = frozenset()
            self._dir_listing_cache[parent] = names
        return candidate.name in names

    def _resolve_python_module(self, base: Path, parts: List[str]) -> Optional[str]:
        """Resolve dotted module `parts` beneath `base` to a real file, or None."""
        if not parts:
            return None
        target = base
        for part in parts:
            target = target / part
        for candidate in (target.with_suffix('.py'), target / '__init__.py'):
            try:
                rel = candidate.relative_to(self.project_dir)
            except ValueError:
                continue  # escaped the project; not ours to resolve
            if self._is_real_file(candidate):
                return normalize_key(rel)
        return None

    def _python_search_bases(self, from_dir: Path) -> List[Path]:
        """Directories standing in for `sys.path`, best candidate first.

        There is no single right answer without running the interpreter, so this
        approximates the two layouts that actually occur, in the order Python would
        prefer them:

          - a **loose script or test** (its directory has no `__init__.py`) gets its
            own directory as `sys.path[0]`, so a sibling module wins
          - a **package member** does not. Python 3 removed implicit relative imports,
            so a bare `import utils` inside a package is absolute and must resolve
            against whatever the package hangs off — which is the parent of its
            outermost `__init__.py`, not the file's own directory

        That parent is also what makes the PyPA src-layout work: for
        `src/myapp/service.py` it comes out as `src/`, which is exactly the entry
        `pip install -e .` puts on the path.
        """
        package_root = from_dir
        while ((package_root / '__init__.py').exists()
               and package_root != self.project_dir
               and package_root.parent != package_root):
            package_root = package_root.parent

        in_package = package_root != from_dir
        # A package member deliberately does NOT get its own directory. Python 3 removed
        # implicit relative imports, so a bare `import logging` inside a package is absolute
        # and must not bind the sibling `logging.py`. Keeping from_dir as a last-resort base
        # reinstated Python 2 semantics: measured on a 2,098-file stock-library corpus, 91 of
        # 91 edges it produced were wrong, 24 of them files importing themselves.
        ordered = ([package_root, self.project_dir] if in_package
                   else [from_dir, package_root, self.project_dir])

        # `src/` is a source root only when Python packaging says so. Appending it on the
        # strength of the directory existing fabricates edges in every JS, TS or Rust repo
        # that happens to have one.
        src = self.project_dir / 'src'
        if src.is_dir() and any((self.project_dir / manifest).exists()
                                for manifest in ('pyproject.toml', 'setup.cfg', 'setup.py')):
            ordered.append(src)

        seen, bases = set(), []
        for base in ordered:
            if base not in seen:
                seen.add(base)
                bases.append(base)
        return bases

    def _resolve_python_import(self, import_path: str, from_file: str) -> Optional[str]:
        """Resolve a Python import the way Python does, or None.

        Python's dotted module syntax is not a filesystem path, which is what the
        generic resolver treated it as: `from .adapters import x` became a lookup for
        a file literally named `.adapters`, and `import behavior_graph` — a module
        sitting in the same directory — was written off as a third-party package.
        Between them these produced zero internal edges for every Python project.

        Explicit relative imports (`.mod`, `..pkg.mod`) are anchored to the importing
        file's package: one leading dot is the current package, each extra dot climbs
        a level. Absolute imports are tried against `_python_search_bases`.

        Resolution only succeeds when a real file is there, so genuine third-party
        packages still fall through to `external:`.
        """
        from_dir = (self.project_dir / from_file).parent

        if import_path.startswith('.'):
            stripped = import_path.lstrip('.')
            if not stripped:
                # `from . import leaf` — the module name is in the import clause, which the
                # patterns do not capture, so all that reached here is punctuation. The edge
                # is genuinely missed (backlog item 10), but reporting `unresolved:.` would
                # be worse than missing it: `unresolved:` means "meant something in this
                # project and could not be found", and it feeds the coverage-unknown signal.
                # A parser artifact must not masquerade as a coverage gap.
                return None
            climb = len(import_path) - len(stripped)
            base = from_dir
            for _ in range(climb - 1):
                base = base.parent
            return self._resolve_python_module(base, stripped.split('.'))

        parts = import_path.split('.')
        for base in self._python_search_bases(from_dir):
            hit = self._resolve_python_module(base, parts)
            if hit:
                return hit
        return None

    def _resolve_import_path(self, import_path: str, from_file: str,
                             language: Optional[str] = None) -> Optional[str]:
        """Resolve an import to a project-relative file path, or None.

        Relative/absolute imports are anchored to `project_dir` (cwd-independent, F9);
        bare specifiers are matched against tsconfig/jsconfig path aliases (F7) before
        falling through to external. Python uses module semantics instead of path
        semantics throughout.
        """
        if language == 'python':
            return self._resolve_python_import(import_path, from_file)
        if import_path.startswith('.') or import_path.startswith('/'):
            from_dir = (self.project_dir / from_file).parent
            return self._resolve_fs((from_dir / import_path).resolve())
        # A workspace sibling looks exactly like a third-party package until you read the
        # root manifest. Tried before aliases because a tsconfig `paths` entry that happens
        # to collide should not shadow a real package in the same repo.
        hit = self._resolve_workspace_import(import_path)
        if hit:
            return hit
        return self._resolve_alias(import_path)

    def _classify_import(self, import_path: str, from_file: str,
                         language: Optional[str] = None) -> str:
        """Tag an import: internal rel-path, `external:<pkg>`, or `unresolved:<imp>`.

        `unresolved:` makes a failed relative/alias resolution visible instead of
        silently dropping it (vision §6, "coverage-unknown, never silent").
        """
        resolved = self._resolve_import_path(import_path, from_file, language)
        if resolved == from_file:
            # A file is never its own dependency. This happens honestly: `rich/abc.py` does
            # `from abc import ABC`, meaning the stdlib, and with the package at the project
            # root the local `abc.py` is the nearest match — itself. Shadowing a stdlib name
            # with a *sibling* is real and stays resolved; a self-edge is not a dependency,
            # and blast radius walks edges, so one would make a file its own dependent.
            resolved = None
        if resolved:
            return resolved
        # A Python import that names no file on disk is a package. Only an explicitly
        # relative one is a broken reference worth surfacing, since it can only ever
        # have meant something inside this project.
        if language == 'python':
            return (f'unresolved:{import_path}' if import_path.startswith('.')
                    else f'external:{import_path}')
        if (import_path.startswith('.') or import_path.startswith('/')
                or self._matches_alias(import_path)
                or self._names_a_workspace_package(import_path)):
            return f'unresolved:{import_path}'
        return f'external:{import_path}'

    def _parse_imports(self, content: str, language: str) -> List[str]:
        """Extract import paths from file content."""
        imports = []
        patterns = IMPORT_PATTERNS.get(language, [])

        for pattern in patterns:
            matches = re.findall(pattern, content, re.MULTILINE)
            for match in matches:
                if isinstance(match, tuple):
                    match = match[0] if match[0] else match[1] if len(match) > 1 else ''
                match = (match or '').strip()
                # `from . import leaf` leaves only the dots here: the module name lives in the
                # import clause, which these patterns do not capture. Punctuation is not a
                # module reference, and emitting it would later surface as `unresolved:.` — a
                # parser artifact wearing the costume of a coverage gap. The edge is missed
                # either way (backlog item 10); this keeps it from also being misreported.
                if match and match.strip('.'):
                    imports.append(match)

        return sorted(set(imports))

    def _parse_exports(self, content: str, language: str) -> List[str]:
        """Extract export names from file content."""
        exports = []
        patterns = EXPORT_PATTERNS.get(language, [])

        for pattern in patterns:
            matches = re.findall(pattern, content, re.MULTILINE)
            for match in matches:
                if isinstance(match, tuple):
                    match = match[0] if match[0] else match[1] if len(match) > 1 else ''
                if match:
                    # Handle export { a, b, c } syntax
                    for name in match.split(','):
                        name = name.strip().split(' as ')[-1].strip()
                        if name and name not in exports:
                            exports.append(name)
                elif isinstance(match, str) and match:
                    if match not in exports:
                        exports.append(match)

        return sorted(set(exports))

    def _parse_gitignore(self) -> List[str]:
        """Read `.gitignore` into a list of patterns, **verbatim**.

        Deliberately no normalisation. This used to strip both slashes and collapse `**`
        before returning, which destroyed the two things a matcher needs:

        - `line.strip('/')` turned the root-anchored `/lib` into the floating `lib`, so it
          excluded `src/lib/` as well — git-tracked source, silently absent from the graph.
        - `!` lines were dropped entirely, so `config/*` + `!config/default.ts` excluded a file
          git tracks, and any import of it then dangled.

        Interpretation belongs in `gitignore_excludes`, which can see the whole ordered list
        and apply last-match-wins. A parser that pre-digests its input cannot.
        """
        gitignore_path = self.project_dir / '.gitignore'
        if not gitignore_path.exists():
            return []
        try:
            content = gitignore_path.read_text(encoding='utf-8')
        except OSError:
            return []

        patterns = []
        for line in content.splitlines():
            line = line.strip()
            if not line or line.startswith('#'):
                continue
            patterns.append(line)
        return patterns

    def _get_exclusion_rules(self) -> Dict[str, Any]:
        """Get comprehensive exclusion rules for the project."""
        return {
            # Directories that are ALWAYS excluded (build artifacts, dependencies, etc.)
            'always_exclude_dirs': {
                # Dependencies
                'node_modules', 'vendor', '__pycache__', 'venv', '.venv', 'env',
                # Version control
                '.git', '.svn', '.hg',
                # Build outputs
                'dist', 'build', 'out', '.output', 'target',
                # Framework build caches
                '.next', '.nuxt', '.astro', '.svelte-kit', '.remix', '.vuepress',
                '.docusaurus', '.cache', '.parcel-cache', '.vite', '.turbo',
                # Test coverage
                'coverage', '.nyc_output', 'htmlcov',
                # IDE/Editor
                '.idea', '.vscode', '.sublime-project',
                # OS files
                '__MACOSX',
                # Documentation builds
                '_site', '.docusaurus',
                # CI definitions
                '.github', '.gitlab',
                # Our own generated output. Graphing it would be self-reference.
                'knowledge-base',
            },
            # Excluded only as a TOP-LEVEL directory, not wherever the name appears.
            #
            # The distinction is the fix for a real defect: the set above is tested
            # against *every* path component, which is right for an artifact tree —
            # a nested `node_modules/` is still `node_modules`. It is wrong for a
            # name that merely follows a convention. `scripts` used to sit above, so
            # `skills/<skill>/scripts/` was excluded too, hiding 40 of this repo's
            # Python files while the build reported success. `generated` did the same
            # to the Next.js route `app/api/media/generated/route.ts`.
            #
            # At the repo root these names do mean what the convention says, and
            # indexing them is measurably noise: a top-level `docs/` here holds the
            # published site's bundled JS and this spike's planted fixtures, none of
            # which belong in a blast radius. Below the root, the name carries no such
            # promise, so the judgement passes to classifications.json — per-project
            # and overridable, which a hardcoded name list is not.
            #
            # 'scripts' is on neither list: it holds real source often enough, at the
            # root as well as below it, that excluding it by name is the guess that
            # started this.
            'top_level_exclude_dirs': {
                'docs', 'examples',
                'generated', '.generated', 'autogen',
            },
            # File patterns that are ALWAYS excluded
            'always_exclude_files': {
                '*.d.ts',        # TypeScript declaration files
                '*.min.js',      # Minified JS
                '*.min.css',     # Minified CSS
                '*.bundle.js',   # Bundled JS
                '*.chunk.js',    # Webpack chunks
                '*.map',         # Source maps
                '*.lock',        # Lock files
                '*.log',         # Log files
            },
            # Directories that are LIKELY source code (whitelist approach)
            'likely_source_dirs': {
                # JavaScript/TypeScript
                'src', 'lib', 'app', 'apps', 'packages', 'components', 'pages',
                'hooks', 'utils', 'helpers', 'services', 'contexts', 'stores',
                'types', 'interfaces', 'models', 'schemas',
                # Python
                'app', 'apps', 'backend', 'api', 'core', 'modules',
                # Go
                'cmd', 'pkg', 'internal', 'api', 'handler', 'handlers',
                # General
                'server', 'client', 'shared', 'common', 'config',
            },
        }

    def _detect_source_structure(self) -> List[str]:
        """Detect which source directories exist in the project."""
        rules = self._get_exclusion_rules()
        found_source_dirs = []

        for dir_name in rules['likely_source_dirs']:
            dir_path = self.project_dir / dir_name
            if dir_path.exists() and dir_path.is_dir():
                found_source_dirs.append(dir_name)

        return found_source_dirs

    def _should_exclude(self, rel_path: str, gitignore_patterns: List[str]) -> bool:
        """Check if a path should be excluded based on multiple rules."""
        from fnmatch import fnmatch

        rules = self._get_exclusion_rules()
        path_parts = Path(rel_path).parts
        filename = Path(rel_path).name

        # 1. Check always-exclude directories (anywhere in path)
        for exc_dir in rules['always_exclude_dirs']:
            if exc_dir in path_parts:
                return True

        # 1b. Convention directories, at the repo root only. See the set's comment.
        if len(path_parts) > 1 and path_parts[0] in rules['top_level_exclude_dirs']:
            return True

        # 2. Check always-exclude file patterns
        for pattern in rules['always_exclude_files']:
            if fnmatch(filename, pattern):
                return True

        # 3. Check gitignore patterns — shared with _classify_with_rules
        return gitignore_excludes(rel_path, gitignore_patterns)

    # =========================================================================
    # Hybrid Classification System (Rules + AI)
    # =========================================================================

    def _get_project_context(self) -> Dict[str, Any]:
        """Detect project type, framework, and language for context."""
        context = {
            'framework': None,
            'language': None,
            'package_manager': None,
            'config_files': [],
        }

        # Check for config files
        config_files = {
            'package.json': 'node',
            'tsconfig.json': 'typescript',
            'pyproject.toml': 'python',
            'setup.py': 'python',
            'requirements.txt': 'python',
            'go.mod': 'go',
            'Cargo.toml': 'rust',
        }

        for config_file, hint in config_files.items():
            if (self.project_dir / config_file).exists():
                context['config_files'].append(config_file)
                if hint in ['node', 'typescript']:
                    context['language'] = context['language'] or 'typescript'
                    context['package_manager'] = 'npm/yarn/pnpm'
                elif hint == 'python':
                    context['language'] = context['language'] or 'python'
                    context['package_manager'] = 'pip'
                elif hint == 'go':
                    context['language'] = 'go'
                    context['package_manager'] = 'go modules'

        # Detect framework from package.json
        package_json_path = self.project_dir / 'package.json'
        if package_json_path.exists():
            try:
                content = package_json_path.read_text(encoding='utf-8')
                package_data = json.loads(content)
                deps = {**package_data.get('dependencies', {}), **package_data.get('devDependencies', {})}

                if 'next' in deps:
                    context['framework'] = 'Next.js'
                elif 'nuxt' in deps:
                    context['framework'] = 'Nuxt.js'
                elif 'react' in deps:
                    context['framework'] = 'React'
                elif 'vue' in deps:
                    context['framework'] = 'Vue'
                elif 'svelte' in deps:
                    context['framework'] = 'Svelte'
                elif 'express' in deps:
                    context['framework'] = 'Express'
                elif 'fastapi' in deps or any('fastapi' in d for d in deps):
                    context['framework'] = 'FastAPI'
            except Exception:
                pass

        # Check for framework-specific config files
        if (self.project_dir / 'next.config.js').exists() or (self.project_dir / 'next.config.mjs').exists():
            context['framework'] = 'Next.js'
        if (self.project_dir / 'nuxt.config.js').exists() or (self.project_dir / 'nuxt.config.ts').exists():
            context['framework'] = 'Nuxt.js'

        return context

    def _get_all_directories(self, max_depth: int = 2) -> List[str]:
        """Get all directories in the project up to max_depth."""
        directories = []

        for item in self.project_dir.iterdir():
            if item.is_dir() and not item.name.startswith('.'):
                directories.append(item.name)
                # Get subdirectories if within max_depth
                if max_depth > 1:
                    try:
                        for subitem in item.iterdir():
                            if subitem.is_dir():
                                directories.append(f"{item.name}/{subitem.name}")
                    except PermissionError:
                        pass

        return sorted(set(directories))

    def _load_classifications(self) -> Dict[str, Any]:
        """Load cached classifications, discarding verdicts the rules have outgrown.

        The builder skips any directory already present here, so without this a rule
        change only ever reached a fresh clone: every project graphed before the
        change kept the old answer indefinitely, and `--clear` does not remove this
        file. That is how a fix for a directory being wrongly excluded would have
        shipped to nobody.

        Only `rule` and `gitignore` verdicts are dropped — they are re-derivable, so
        the rules are their single source of truth. A `user` or `ai` verdict is a
        judgement about this project that no rule change invalidates, and it stays.
        """
        if not self.classifications_path.exists():
            return {'version': 1, 'rules_version': RULES_VERSION, 'directories': {}}
        try:
            with open(self.classifications_path) as f:
                data = json.load(f)
        except Exception:
            return {'version': 1, 'rules_version': RULES_VERSION, 'directories': {}}

        if data.get('rules_version') != RULES_VERSION:
            data['directories'] = {
                name: verdict
                for name, verdict in (data.get('directories') or {}).items()
                if (verdict or {}).get('source') not in ('rule', 'gitignore')
            }
            data['rules_version'] = RULES_VERSION
        return data

    def _save_classifications(self, classifications: Dict[str, Any]) -> None:
        """Save classifications to file."""
        self._ensure_graph_dir()
        classifications['version'] = 1
        classifications['rules_version'] = RULES_VERSION
        classifications['classified_at'] = datetime.now(timezone.utc).isoformat()
        with open(self.classifications_path, 'w') as f:
            json.dump(classifications, f, indent=2)

    def _classify_with_rules(self, dir_name: str) -> Optional[Dict[str, Any]]:
        """Classify a directory using known rules. Returns None if unknown.

        `dir_name` is project-relative and may be nested ('skills/thing'), so the
        checks here mirror `_should_exclude` rather than inventing their own rules.
        Two verdicts for the same directory would be worse than either one.
        """
        rules = self._get_exclusion_rules()
        parts = PurePosixPath(dir_name).parts

        # Artifact trees, wherever the name appears
        if any(part in rules['always_exclude_dirs'] for part in parts):
            return {'type': 'exclude', 'confidence': 1.0, 'source': 'rule'}

        # Convention directories, at the repo root only
        if parts and parts[0] in rules['top_level_exclude_dirs']:
            return {'type': 'exclude', 'confidence': 1.0, 'source': 'rule'}

        # Check if it's a known source directory
        if dir_name in rules['likely_source_dirs']:
            return {'type': 'source', 'confidence': 1.0, 'source': 'rule'}

        # Check gitignore patterns.
        #
        # This used to be `pattern == dir_name or pattern in dir_name` — the same
        # unanchored substring test that was removed from `_should_exclude`, and it
        # survived here because the two functions had drifted apart. It is the more
        # damaging of the two: `_classify_with_rules` runs first and excludes whole
        # directories, so a `.next` entry took out any top-level directory whose name
        # merely contained `.next`.
        if gitignore_excludes(dir_name, self._parse_gitignore()):
            return {'type': 'exclude', 'confidence': 0.9, 'source': 'gitignore'}

        return None

    def _build_classification_prompt(self, unknown_dirs: List[str], context: Dict[str, Any]) -> str:
        """Build the AI prompt for classifying unknown directories."""
        context_str = f"""Project context:
- Framework: {context.get('framework') or 'Unknown'}
- Language: {context.get('language') or 'Unknown'}
- Package manager: {context.get('package_manager') or 'Unknown'}
- Config files: {', '.join(context.get('config_files', []))}"""

        dirs_str = '\n'.join(f"- {d}/" for d in unknown_dirs)

        return f"""You are classifying directories in a codebase for dependency graph analysis.

{context_str}

Classify these directories as 'source' (contains code to track for dependencies) or 'exclude' (generated/build/vendor/should not track):

{dirs_str}

Respond with ONLY a JSON object, no markdown formatting:
{{"directory_name": {{"type": "source|exclude", "confidence": 0.0-1.0, "reasoning": "brief explanation"}}, ...}}"""

    def _parse_ai_classification_response(self, response: str, unknown_dirs: List[str]) -> Dict[str, Dict[str, Any]]:
        """Parse AI response into classification dict."""
        try:
            # Try to extract JSON from response
            response = response.strip()
            # Remove markdown code blocks if present
            if response.startswith('```'):
                response = response.split('\n', 1)[1]
            if response.endswith('```'):
                response = response.rsplit('\n', 1)[0]

            result = json.loads(response)
            classifications = {}

            for dir_name in unknown_dirs:
                if dir_name in result:
                    data = result[dir_name]
                    classifications[dir_name] = {
                        'type': data.get('type', 'exclude'),
                        'confidence': float(data.get('confidence', 0.5)),
                        'source': 'ai',
                        'reasoning': data.get('reasoning', ''),
                    }
                else:
                    # Default to exclude if AI didn't classify
                    classifications[dir_name] = {
                        'type': 'exclude',
                        'confidence': 0.5,
                        'source': 'default',
                        'reasoning': 'Not classified by AI',
                    }

            return classifications
        except json.JSONDecodeError:
            # If parsing fails, default all to exclude
            return {
                dir_name: {
                    'type': 'exclude',
                    'confidence': 0.3,
                    'source': 'error',
                    'reasoning': 'Failed to parse AI response',
                }
                for dir_name in unknown_dirs
            }

    def _classify_with_ai(self, unknown_dirs: List[str], context: Dict[str, Any]) -> Dict[str, Dict[str, Any]]:
        """Send unknown directories to AI for classification.

        NOTE: This method is designed to be called by the skill (which has AI access).
        When run standalone via CLI, it will return default classifications.
        """
        # When run via CLI without AI, return default exclude classifications
        # The skill will intercept this and call AI properly
        return {
            dir_name: {
                'type': 'exclude',
                'confidence': 0.5,
                'source': 'no_ai',
                'reasoning': 'AI classification not available in CLI mode',
            }
            for dir_name in unknown_dirs
        }

    def _ask_user_classification(self, dir_name: str, classification: Dict[str, Any]) -> str:
        """Ask user to confirm classification for low-confidence results."""
        print(f"\nUncertain classification for '{dir_name}/'")
        print(f"  AI suggests: {classification['type']} ({int(classification['confidence'] * 100)}% confidence)")
        print(f"  Reasoning: {classification.get('reasoning', 'No reasoning provided')}")
        print()
        print("  [1] Source - include in dependency graph")
        print("  [2] Exclude - skip this directory")

        while True:
            try:
                choice = input("  Your choice (1 or 2): ").strip()
                if choice == '1':
                    return 'source'
                elif choice == '2':
                    return 'exclude'
                else:
                    print("  Please enter 1 or 2")
            except EOFError:
                # Non-interactive mode, default to exclude
                return 'exclude'

    def _classify_directories(self, use_ai: bool = True, ai_response: Optional[str] = None,
                              non_interactive: bool = False) -> Dict[str, Any]:
        """Main classification flow: rules → AI → user confirmation.

        Args:
            use_ai: Whether to use AI for unknown directories
            ai_response: Pre-fetched AI response (from skill invocation)
            non_interactive: Never prompt on stdin; default uncertain dirs to source
                (err toward completeness — never silently drop real source). F6.

        Returns:
            Classifications dict with all directories classified
        """
        classifications = self._load_classifications()
        context = self._get_project_context()
        all_dirs = self._get_all_directories()

        # Find directories that need classification
        known_classifications = classifications.get('directories', {})
        dirs_to_classify = []

        for dir_name in all_dirs:
            # Check if already classified
            if dir_name in known_classifications:
                continue

            # Try rules first
            rule_result = self._classify_with_rules(dir_name)
            if rule_result:
                known_classifications[dir_name] = rule_result
            else:
                dirs_to_classify.append(dir_name)

        # If no unknown directories, we're done
        if not dirs_to_classify:
            classifications['directories'] = known_classifications
            classifications['project_context'] = context
            self._save_classifications(classifications)
            return classifications

        # Classify unknowns with AI
        if use_ai:
            if ai_response:
                # Use pre-fetched AI response
                ai_classifications = self._parse_ai_classification_response(ai_response, dirs_to_classify)
            else:
                # Get AI classification (will return defaults in CLI mode)
                ai_classifications = self._classify_with_ai(dirs_to_classify, context)

            # Process AI results
            for dir_name, classification in ai_classifications.items():
                confidence = classification.get('confidence', 0)

                if confidence >= 0.8:
                    # Auto-accept high confidence
                    known_classifications[dir_name] = classification
                elif non_interactive:
                    # No stdin: default uncertain dirs to source so real code is never
                    # silently dropped (F6). Recorded so the choice is auditable.
                    known_classifications[dir_name] = {
                        'type': 'source',
                        'confidence': 1.0,
                        'source': 'auto-source-default',
                        'reasoning': f"Non-interactive default after AI suggestion ({classification['type']})",
                    }
                else:
                    # Ask user for low confidence
                    final_type = self._ask_user_classification(dir_name, classification)
                    known_classifications[dir_name] = {
                        'type': final_type,
                        'confidence': 1.0,
                        'source': 'user',
                        'reasoning': f"User confirmed after AI suggestion ({classification['type']})",
                    }
        else:
            # No AI, default unknown to exclude
            for dir_name in dirs_to_classify:
                known_classifications[dir_name] = {
                    'type': 'exclude',
                    'confidence': 0.5,
                    'source': 'default',
                    'reasoning': 'No AI available, defaulted to exclude',
                }

        # Save and return
        classifications['directories'] = known_classifications
        classifications['project_context'] = context
        self._save_classifications(classifications)
        return classifications

    # =========================================================================
    # Public methods for skill integration (AI-assisted classification)
    # =========================================================================

    def needs_classification(self) -> bool:
        """Check if there are directories that need AI classification."""
        classifications = self._load_classifications()
        all_dirs = self._get_all_directories()
        known_classifications = classifications.get('directories', {})

        for dir_name in all_dirs:
            if dir_name not in known_classifications:
                rule_result = self._classify_with_rules(dir_name)
                if not rule_result:
                    return True
        return False

    def get_unclassified_directories(self) -> List[str]:
        """Get list of directories that need AI classification."""
        classifications = self._load_classifications()
        all_dirs = self._get_all_directories()
        known_classifications = classifications.get('directories', {})

        unclassified = []
        for dir_name in all_dirs:
            if dir_name not in known_classifications:
                rule_result = self._classify_with_rules(dir_name)
                if not rule_result:
                    unclassified.append(dir_name)

        return unclassified

    def get_classification_prompt(self) -> str:
        """Get the prompt to send to AI for classification."""
        unknown_dirs = self.get_unclassified_directories()
        if not unknown_dirs:
            return ""
        context = self._get_project_context()
        return self._build_classification_prompt(unknown_dirs, context)

    def classify_with_ai_response(self, ai_response: str) -> Dict[str, Any]:
        """Process AI response and complete classification.

        This is called by the skill after it gets AI response.
        Returns classifications with any low-confidence items needing user input.
        """
        return self._classify_directories(use_ai=True, ai_response=ai_response)

    def get_low_confidence_classifications(self) -> Dict[str, Dict[str, Any]]:
        """Get classifications that need user confirmation."""
        classifications = self._load_classifications()
        low_confidence = {}

        for dir_name, info in classifications.get('directories', {}).items():
            if info.get('source') == 'ai' and info.get('confidence', 0) < 0.8:
                low_confidence[dir_name] = info

        return low_confidence

    def set_classification(self, dir_name: str, classification_type: str, reasoning: str = "") -> None:
        """Set classification for a directory (used after user confirmation)."""
        classifications = self._load_classifications()
        classifications.setdefault('directories', {})[dir_name] = {
            'type': classification_type,
            'confidence': 1.0,
            'source': 'user',
            'reasoning': reasoning,
        }
        self._save_classifications(classifications)

    def _scan_files(self, classifications: Optional[Dict[str, Any]] = None) -> List[Path]:
        """Find all source files in the project using classifications."""
        files = []
        gitignore_patterns = self._parse_gitignore()

        # Use classifications if provided, otherwise load from file
        if classifications is None:
            classifications = self._load_classifications()

        classified_dirs = classifications.get('directories', {})

        # Get source directories from classifications
        source_dirs = [
            d for d, info in classified_dirs.items()
            if info.get('type') == 'source' and '/' not in d  # Only top-level dirs
        ]

        if source_dirs:
            # Scan only classified source directories
            for src_dir in source_dirs:
                dir_path = self.project_dir / src_dir
                for language, patterns in FILE_PATTERNS.items():
                    for pattern in patterns:
                        files.extend(dir_path.glob(pattern))

            # Also scan root-level source files (e.g., index.ts, app.ts)
            for language, patterns in FILE_PATTERNS.items():
                for pattern in patterns:
                    for f in self.project_dir.glob(pattern):
                        # Only include if it's directly in root (no subdirectory)
                        if len(Path(f.relative_to(self.project_dir)).parts) == 1:
                            files.append(f)
        else:
            # Fallback: scan entire project but apply filters
            for language, patterns in FILE_PATTERNS.items():
                for pattern in patterns:
                    files.extend(self.project_dir.glob(pattern))

        # Apply exclusion rules and check against classifications
        filtered = []
        for f in files:
            try:
                # POSIX form before any '/'-splitting or glob matching below: with a
                # native `src\b.ts` the top-level split finds nothing, so on Windows
                # every classified `exclude` directory was silently ignored here.
                rel_path = normalize_key(f.relative_to(self.project_dir))

                # Walk every ancestor of this file, deepest first, and take the first
                # classification found.
                #
                # This used to read only `rel_path.split('/')[0]`, so a verdict on anything
                # nested was written to classifications.json and then never consulted. That
                # made the delegation `top_level_exclude_dirs` relies on a fiction: the
                # comment says judgement below the root "passes to classifications.json —
                # per-project and overridable", and it did not. Deepest-first also lets a
                # specific verdict override a broader one, so `packages/` can be source while
                # `packages/legacy/` is not.
                verdict = None
                ancestors = rel_path.split('/')[:-1]
                for depth in range(len(ancestors), 0, -1):
                    prefix = '/'.join(ancestors[:depth])
                    if prefix in classified_dirs:
                        verdict = classified_dirs[prefix].get('type')
                        break
                if verdict == 'exclude':
                    continue

                # Also check standard exclusion rules
                if not self._should_exclude(rel_path, gitignore_patterns):
                    filtered.append(f)
            except ValueError:
                continue

        # Remove duplicates
        # sorted, not list(set(...)): set iteration order varies per process, which
        # made graph.json key order — and every dependents list built from it —
        # differ between two builds of identical input.
        return sorted(set(filtered))

    def _build_file_info(self, file_path: Path) -> Dict[str, Any]:
        """Build file info dict for a single file."""
        try:
            content = file_path.read_text(encoding='utf-8', errors='ignore')
        except Exception:
            return {'imports': [], 'dependents': [], 'exports': []}

        language = self._detect_language(file_path)
        rel_path = normalize_key(file_path.relative_to(self.project_dir))

        imports = self._parse_imports(content, language) if language else []
        exports = self._parse_exports(content, language) if language else []

        # Resolve + classify import paths (internal / external: / unresolved:)
        resolved_imports = [self._classify_import(imp, rel_path, language) for imp in imports]

        return {
            'exports': exports,
            'imports': resolved_imports,
            'dependents': [],
            'language': language,
        }

    def _write_graph(self, graph: Dict[str, Any]) -> None:
        """Persist the graph as both the active artifact and this backend's own.

        `graph.json` stays the active graph because three other skills read that path
        directly, and Phase 1's rule is that nothing downstream changes. `graph.<backend>.json`
        is the addition (CD-17): without it, switching substrates destroys the baseline at
        exactly the moment CD-13 requires a diff against it.
        """
        self._ensure_graph_dir()
        payload = json.dumps(graph, indent=2)
        for path in (self.graph_path, self.graph_dir / ('graph.%s.json' % self.name)):
            with open(path, 'w', encoding='utf-8') as handle:
                handle.write(payload)

    def build(self, ai_response: Optional[str] = None, non_interactive: bool = False,
              exclusions: Optional[substrate.Exclusions] = None) -> Dict[str, Any]:
        """Build the dependency graph from scratch.

        Args:
            ai_response: Pre-fetched AI response for directory classification
                         (used when skill invokes this with AI access)
            non_interactive: Never prompt for directory classification (F6)
            exclusions: Contract obligation 6 — what the project has declared out of
                        scope. Omitted, the backend derives them from the project itself,
                        which is what every current caller relies on.
        """
        print(f'Scanning {self.project_dir}...')

        # Step 1: Classify directories (rules → AI → user)
        print('Classifying directories...')
        classifications = self._classify_directories(use_ai=True, ai_response=ai_response,
                                                      non_interactive=non_interactive)
        source_count = sum(1 for d in classifications.get('directories', {}).values() if d.get('type') == 'source')
        exclude_count = sum(1 for d in classifications.get('directories', {}).values() if d.get('type') == 'exclude')
        print(f'Classified: {source_count} source dirs, {exclude_count} excluded dirs')

        # Step 2: Scan files using classifications
        files = self._scan_files(classifications)

        # A caller-supplied exclusion set is applied on top of the project's own, never
        # instead of it: the caller is adding scope knowledge, not overriding the repo's
        # .gitignore.
        if exclusions is not None:
            files = [f for f in files
                     if not exclusions.excludes(normalize_key(f.relative_to(self.project_dir)))]
        print(f'Found {len(files)} source files')

        # Build file info
        graph = {
            'version': 1,
            'commit': self._get_git_commit(),
            'timestamp': datetime.now(timezone.utc).isoformat(),
            'project_root': str(self.project_dir),
            'substrate': substrate.graph_metadata(
                self.name, self.coverage(),
                exclusions if exclusions is not None else self.project_exclusions()),
            'files': {},
        }

        for file_path in files:
            rel_path = normalize_key(file_path.relative_to(self.project_dir))
            graph['files'][rel_path] = self._build_file_info(file_path)

        # Build dependents (reverse mapping)
        for file_path, info in graph['files'].items():
            for imp in info.get('imports', []):
                if not imp.startswith('external:') and imp in graph['files']:
                    graph['files'][imp]['dependents'].append(file_path)

        self._write_graph(graph)
        self.graph = graph

        # Summary
        total_imports = sum(len(f.get('imports', [])) for f in graph['files'].values())
        total_exports = sum(len(f.get('exports', [])) for f in graph['files'].values())

        return {
            'files_scanned': len(graph['files']),
            'total_imports': total_imports,
            'total_exports': total_exports,
            'commit': graph['commit'],
            'cached_to': str(self.graph_path),
        }

    def load(self) -> Optional[Dict[str, Any]]:
        """Load graph from cache, migrating pre-POSIX-key caches on the way in."""
        if self.graph_path.exists():
            with open(self.graph_path, encoding='utf-8') as f:
                self.graph = migrate_separators(json.load(f))
            return self.graph
        return None

    def update(self, non_interactive: bool = False,
               exclusions: Optional[substrate.Exclusions] = None) -> Dict[str, Any]:
        """Incrementally update the graph."""
        graph = self.load()
        if not graph:
            print('No cached graph found. Running full build...')
            return self.build(non_interactive=non_interactive, exclusions=exclusions)

        last_commit = graph.get('commit')
        if not last_commit:
            print('No commit info in cached graph. Running full build...')
            return self.build(non_interactive=non_interactive, exclusions=exclusions)

        changed_files = self._get_changed_files(last_commit)
        if not changed_files:
            return {'status': 'up_to_date', 'files_changed': 0}

        print(f'Updating graph for {len(changed_files)} changed files...')

        # Re-parse changed files. `git diff --name-only` already emits POSIX paths on
        # every host, but normalizing keeps the key that indexes the graph and the key
        # `_build_file_info` derives from the same string — one source of truth.
        # The same exclusions `build` applies. Without this, `--update` re-parsed whatever
        # `git diff` named and wrote it straight in, so one commit touching an ignored tree
        # silently re-admitted files the build had excluded — and `--update` is the command
        # the steady-state workflow actually runs.
        gitignore_patterns = self._parse_gitignore()
        classified = (self._load_classifications().get('directories') or {})

        def out_of_scope(rel_path: str) -> bool:
            if self._should_exclude(rel_path, gitignore_patterns):
                return True
            if exclusions is not None and exclusions.excludes(rel_path):
                return True
            ancestors = rel_path.split('/')[:-1]
            for depth in range(len(ancestors), 0, -1):
                verdict = classified.get('/'.join(ancestors[:depth]))
                if isinstance(verdict, dict):
                    return verdict.get('type') == 'exclude'
            return False

        for file_path in map(normalize_key, changed_files):
            full_path = self.project_dir / file_path
            if full_path.exists() and not out_of_scope(file_path):
                # Check if it's a source file
                if self._detect_language(full_path):
                    graph['files'][file_path] = self._build_file_info(full_path)
            elif file_path in graph['files']:
                # Deleted, or newly out of scope. Either way it leaves the graph, and the
                # dependents rebuild below drops every edge that pointed at it.
                del graph['files'][file_path]

        # Rebuild dependents for affected files
        for file_path in graph['files']:
            graph['files'][file_path]['dependents'] = []

        for file_path, info in graph['files'].items():
            for imp in info.get('imports', []):
                if not imp.startswith('external:') and imp in graph['files']:
                    graph['files'][imp]['dependents'].append(file_path)

        # Update metadata. The substrate block is refreshed rather than carried over, so a
        # graph never claims coverage the currently-installed backend does not have.
        graph['commit'] = self._get_git_commit()
        graph['timestamp'] = datetime.now(timezone.utc).isoformat()
        graph['substrate'] = substrate.graph_metadata(
            self.name, self.coverage(),
            exclusions if exclusions is not None else self.project_exclusions())

        self._write_graph(graph)
        self.graph = graph

        return {
            'status': 'updated',
            'files_changed': len(changed_files),
            'commit': graph['commit'],
        }

    def query(self, file_path: str) -> Optional[Dict[str, Any]]:
        """Query dependency info for a file."""
        graph = self.load()
        if not graph:
            print('No cached graph found. Run /code-graph build first.')
            return None

        # Normalize path. A caller on Windows naturally passes the path its shell,
        # git status or tab-completion produced (`src\lib\auth.ts`); the key is POSIX
        # on every host, so the lookup is folded rather than the key.
        file_path = normalize_key(file_path)

        info = graph['files'].get(file_path)
        if not info:
            print(f'File not found in graph: {file_path}')
            return None

        return {
            'file': file_path,
            'exports': info.get('exports', []),
            'imports': info.get('imports', []),
            'dependents': info.get('dependents', []),
            'category': info.get('category', 'unknown'),
            'language': info.get('language'),
        }

    def get_dependents(self, file_path: str, transitive: bool = True) -> Set[str]:
        """Get all files that depend on this file."""
        graph = self.load()
        if not graph:
            return set()

        file_path = normalize_key(file_path)

        result = set()

        def traverse(path: str):
            info = graph['files'].get(path, {})
            for dep in info.get('dependents', []):
                if dep not in result:
                    result.add(dep)
                    if transitive:
                        traverse(dep)

        traverse(file_path)
        return result

    def get_dependencies(self, file_path: str, transitive: bool = True) -> Set[str]:
        """Get all files this file depends on."""
        graph = self.load()
        if not graph:
            return set()

        file_path = normalize_key(file_path)

        result = set()

        def traverse(path: str):
            info = graph['files'].get(path, {})
            for imp in info.get('imports', []):
                if not imp.startswith(IMPORT_SIGNALS) and imp not in result:
                    result.add(imp)
                    if transitive:
                        traverse(imp)

        traverse(file_path)
        return result

    def get_impact(self, file_paths: List[str]) -> Dict[str, Set[str]]:
        """Get blast radius for multiple files."""
        graph = self.load()
        if not graph:
            return {}

        # Normalized once, up front: the set arithmetic below subtracts `file_paths`
        # from the dependent sets, so an un-normalized input (`./src/a.ts`, or a
        # Windows `src\a.ts`) would fail to cancel and report a file as its own
        # transitive dependent.
        file_paths = [normalize_key(p) for p in file_paths]

        all_dependents = set()
        direct = set()

        for file_path in file_paths:
            info = graph['files'].get(file_path)
            if info:
                direct.update(info.get('dependents', []))
                all_dependents.add(file_path)
                all_dependents.update(self.get_dependents(file_path, transitive=True))

        return {
            'input_files': set(file_paths),
            'direct_dependents': direct,
            'transitive_dependents': all_dependents - set(file_paths) - direct,
            'all_affected': all_dependents,
        }

    def clear(self) -> bool:
        """Clear the cached graph."""
        if self.graph_path.exists():
            self.graph_path.unlink()
            # Try to remove empty directory
            try:
                self.graph_dir.rmdir()
            except Exception:
                pass
            return True
        return False


def format_summary(data: Any, operation: str) -> str:
    """Format output as human-readable summary."""
    if operation == 'build':
        return f"""Built dependency graph:
  - {data['files_scanned']} files scanned
  - {data['total_imports']} import relationships
  - {data['total_exports']} export declarations
  - Cached to {data['cached_to']}"""

    elif operation == 'update':
        if data.get('status') == 'up_to_date':
            return "Graph is up to date. No changes detected."
        return f"""Updated dependency graph:
  - {data['files_changed']} files changed since last build
  - Graph updated at commit {data.get('commit', 'unknown')}"""

    elif operation == 'query':
        if not data:
            return "File not found in graph."

        lines = [f"File: {data['file']}", ""]

        if data.get('exports'):
            lines.append("Exports:")
            for exp in data['exports']:
                lines.append(f"  - {exp}")
            lines.append("")

        if data.get('imports'):
            lines.append("Dependencies (imports from):")
            for imp in data['imports']:
                prefix = "" if imp.startswith('external:') else "→ "
                lines.append(f"  - {imp} {prefix}")
            lines.append("")

        if data.get('dependents'):
            lines.append("Dependents (imported by):")
            for dep in data['dependents']:
                lines.append(f"  - {dep}")
            lines.append("")

        lines.append(f"Category: {data.get('category', 'unknown')}")
        return '\n'.join(lines)

    elif operation == 'impact':
        lines = [f"Impact analysis for: {', '.join(data['input_files'])}", ""]

        if data['direct_dependents']:
            lines.append(f"Direct impact ({len(data['direct_dependents'])} files):")
            for dep in sorted(data['direct_dependents']):
                lines.append(f"  - {dep}")
            lines.append("")

        if data['transitive_dependents']:
            lines.append(f"Transitive impact ({len(data['transitive_dependents'])} files):")
            for dep in sorted(data['transitive_dependents']):
                lines.append(f"  - {dep}")
            lines.append("")

        lines.append(f"Total blast radius: {len(data['all_affected'])} files affected")
        return '\n'.join(lines)

    elif operation == 'dependents':
        if not data:
            return "No cached graph found or file not in graph."

        lines = ["Dependents:"]
        for dep in sorted(data):
            lines.append(f"  - {dep}")
        return '\n'.join(lines)

    elif operation == 'dependencies':
        if not data:
            return "No cached graph found or file not in graph."

        lines = ["Dependencies:"]
        for dep in sorted(data):
            lines.append(f"  - {dep}")
        return '\n'.join(lines)

    elif operation == 'clear':
        return "Cleared dependency graph cache for this project."

    return str(data)


def main():
    parser = argparse.ArgumentParser(
        description='Code dependency graph operations',
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )

    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument('--build', action='store_true', help='Build graph from scratch')
    group.add_argument('--update', action='store_true', help='Update graph incrementally')
    group.add_argument('--query', metavar='FILE', help='Query file info')
    group.add_argument('--impact', nargs='+', metavar='FILE', help='Impact analysis')
    group.add_argument('--dependents', metavar='FILE', help='Get dependents')
    group.add_argument('--dependencies', metavar='FILE', help='Get dependencies')
    group.add_argument('--clear', action='store_true', help='Clear cache')

    parser.add_argument('--dir', metavar='PATH', help='Project directory')
    parser.add_argument('--format', choices=['json', 'summary'], default='json',
                       help='Output format (default: json)')
    parser.add_argument('--non-interactive', action='store_true',
                        help='Never prompt for directory classification; default uncertain dirs '
                             'to source (also auto-enabled when stdin is not a TTY)')

    args = parser.parse_args()

    # Auto-detect non-interactive when there is no TTY (e.g. invoked by wrap-up). F6.
    non_interactive = args.non_interactive or not sys.stdin.isatty()

    graph = CodeGraph(args.dir)

    # Backend selection, on the operations that produce a graph. Announced on stderr rather
    # than stdout so it never contaminates `--format json`, and announced at all because
    # spec §2.2 requires the choice to be visible: a caller must be able to tell a thin graph
    # from a thin repo. Today there is one backend and this is plumbing; Phase 2 is what it
    # is plumbing for.
    if args.build or args.update:
        try:
            import backends
            selection = backends.select(
                str(graph.project_dir),
                present_extensions=backends.extension_census(
                    str(graph.project_dir), graph.project_exclusions()))
            for warning in selection.warnings:
                print(warning, file=sys.stderr)
            if selection.degraded or selection.backend.name != CodeGraph.name:
                print(selection.describe(), file=sys.stderr)
            graph = selection.backend if hasattr(selection.backend, 'build') else graph
        except Exception as exc:
            # Selection is an optimisation over "run the floor". It must never be the reason
            # a build fails, because the floor is what the build would have used anyway.
            print('code-graph: backend selection failed (%s); using %r'
                  % (exc.__class__.__name__, CodeGraph.name), file=sys.stderr)
    output = None
    operation = None

    if args.build:
        output = graph.build(non_interactive=non_interactive)
        operation = 'build'

    elif args.update:
        output = graph.update(non_interactive=non_interactive)
        operation = 'update'

    elif args.query:
        output = graph.query(args.query)
        operation = 'query'

    elif args.impact:
        output = graph.get_impact(args.impact)
        operation = 'impact'

    elif args.dependents:
        output = graph.get_dependents(args.dependents)
        operation = 'dependents'

    elif args.dependencies:
        output = graph.get_dependencies(args.dependencies)
        operation = 'dependencies'

    elif args.clear:
        output = graph.clear()
        operation = 'clear'

    if output is not None:
        if args.format == 'json':
            # Convert sets to lists for JSON serialization
            if isinstance(output, set):
                output = sorted(list(output))
            elif isinstance(output, dict):
                output = {k: sorted(list(v)) if isinstance(v, set) else v
                         for k, v in output.items()}
            print(json.dumps(output, indent=2))
        else:
            print(format_summary(output, operation))
    else:
        sys.exit(1)


if __name__ == '__main__':
    main()
