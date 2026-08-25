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
from typing import Any, Dict, List, Optional, Sequence, Set, Tuple

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import containment  # noqa: E402  — the one body of the path-containment rules (ADR-030)
import settings  # noqa: E402  — knowledge-base/settings.json, the committed half
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
# contexts. Removed 2026-08-20 (`git log -S _categorize_file`); it was computed on every
# build and read by nothing. Existing caches keep the key harmlessly. Not an ADR: there was no
# fork — the alternative was keeping a field nobody reads.

# Import patterns by language, each tagged with the relation it expresses.
#
# The tag is what the object-shaped edge buys immediately. `export * from './y'` and
# `import {x} from './y'` were the same edge when an edge was a string, because a string can
# only say *where*. A barrel file that re-exports twelve modules and a module that imports
# twelve modules are different things to anyone reading a blast radius, and now they can be
# told apart.
_RE_EXPORT = 're_exports'
_IMPORTS = 'imports'

IMPORT_PATTERNS = {
    # `(?:type\s+)?` appears on the three statement forms that accept it. A type-only
    # import is a real dependency — the importer does not compile without it — and
    # omitting it hid 16 edges on the testbed alone. It is optional, so the plain
    # forms keep matching exactly as before.
    'typescript': [
        # import { x } from './y'   /   import type { X } from './y'
        (r'import\s+(?:type\s+)?\{[^}]*\}\s+from\s+[\'"]([^\'"]+)[\'"]', _IMPORTS),
        # import x from './y'       /   import type X from './y'
        (r'import\s+(?:type\s+)?\w+\s+from\s+[\'"]([^\'"]+)[\'"]', _IMPORTS),
        # import * as x from './y'
        (r'import\s+(?:type\s+)?\*\s+as\s+\w+\s+from\s+[\'"]([^\'"]+)[\'"]', _IMPORTS),
        # export * from './y'       /   export type { D } from './y'
        (r'export\s+(?:type\s+)?(?:\*|\{[^}]*\})\s+from\s+[\'"]([^\'"]+)[\'"]', _RE_EXPORT),
        # require('./y')
        (r'require\s*\(\s*[\'"]([^\'"]+)[\'"]\s*\)', _IMPORTS),
        # import('./y')
        (r'import\s*\(\s*[\'"]([^\'"]+)[\'"]\s*\)', _IMPORTS),
    ],
    'javascript': [
        # Same as TypeScript (JS is subset). `type` cannot appear in plain JS, but
        # keeping the two lists identical is what stops them drifting apart.
        (r'import\s+(?:type\s+)?\{[^}]*\}\s+from\s+[\'"]([^\'"]+)[\'"]', _IMPORTS),
        (r'import\s+(?:type\s+)?\w+\s+from\s+[\'"]([^\'"]+)[\'"]', _IMPORTS),
        (r'import\s+(?:type\s+)?\*\s+as\s+\w+\s+from\s+[\'"]([^\'"]+)[\'"]', _IMPORTS),
        (r'export\s+(?:type\s+)?(?:\*|\{[^}]*\})\s+from\s+[\'"]([^\'"]+)[\'"]', _RE_EXPORT),
        (r'require\s*\(\s*[\'"]([^\'"]+)[\'"]\s*\)', _IMPORTS),
        (r'import\s*\(\s*[\'"]([^\'"]+)[\'"]\s*\)', _IMPORTS),
    ],
    'python': [
        # from x import y   (also covers `from .x import y` and `from ..x import y`)
        (r'from\s+([\w.]+)\s+import', _IMPORTS),
        # import x
        (r'^import\s+([\w.]+)', _IMPORTS),
        # A third pattern for `from . import x` used to sit here. Its capture group
        # started *after* the dots, so it returned the rest of the statement rather
        # than a module: `from . import leaf` yielded the specifier 'import', which
        # was then reported as a third-party package literally named `import`. It
        # produced 66 junk entries across the measured repos and not one real edge.
        # `from . import x` is still missed — the module name lives in the import
        # clause, which needs clause capture to read — but it is now missed silently
        # rather than answered wrongly. Tracked in knowledge-base/roadmap.md.
    ],
    'go': [
        # import "module/path"
        (r'import\s+[\'"]([^\'"]+)[\'"]', _IMPORTS),
        # import alias "module/path"
        (r'import\s+\w+\s+[\'"]([^\'"]+)[\'"]', _IMPORTS),
        # multi-line import ( ... )
        (r'[\'"]([^\'"]+)[\'"]', _IMPORTS),
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


# Import edges that name a *specifier*, not a file in this project, are `substrate`'s
# vocabulary and are read from there. This module used to carry its own copy of the tuple,
# which is how `normalize_import` and `is_internal` come to disagree about what a signal is —
# and they would have, the moment `outside:` was added to one of them (ADR-031).

# Bump whenever the directory rules below change meaning. Cached `rule`/`gitignore`
# verdicts in classifications.json are discarded on a mismatch, so a rule fix reaches
# projects that were already graphed instead of only fresh clones. Any string works;
# a date is readable in the file.
RULES_VERSION = '2026-08-20b'

# The marker a settings-declared verdict carries. It is the one thing that distinguishes a
# decision the project committed from a verdict this module derived, and `_save_classifications`
# uses it to keep the former out of the cache — a copy in there outlives the file that declared
# it, and then nothing can withdraw it.
_DECLARED_IN_SETTINGS = 'declared in knowledge-base/settings.json'

# Classification sources that outrank the built-in name lists in `_get_exclusion_rules`.
#
# A `rule` or `gitignore` verdict is those lists' own output, so letting one override them
# would be circular. `user` and `ai` are judgements *about this project*, which is the only
# thing that can know a default is wrong here.
#
# The two tiers differ deliberately. A name list written in this file cannot know that some
# repository really does keep source in a directory called `target`, so a person who says so
# outranks everything — without that, a wrong default is unfixable, which is the actual defect
# this exists to close. A model gets the weaker tier: "node_modules is source" is a plausible
# thing for one to guess and an implausible thing for a person to type.
_OVERRIDES_EVERYTHING = frozenset({'user'})
_OVERRIDES_CONVENTIONS = frozenset({'user', 'ai'})


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
CACHE_IGNORED = ('graph.json', 'graph.*.json', 'classifications.json', 'docs.json')

CACHE_GITIGNORE = (
    '# Generated code-graph cache — do not commit.\n'
    '#\n'
    '# behavior.json is deliberately NOT listed. Its observed coverage is captured\n'
    '# by running the test suite, so it cannot be rebuilt by re-reading source the\n'
    '# way these can — committing it is what gives a fresh clone a blast radius.\n'
    '#\n'
    '# graph.*.json is the per-backend artifact (ADR-028): each substrate writes its own,\n'
    '# so a swap can be diffed instead of destroying the baseline it should be measured\n'
    '# against. graph.json stays the active graph that other skills read.\n'
    '#\n'
    '# docs.json is the doc-section -> code edge set. Parsed from the markdown that is\n'
    '# already committed, so it is regenerable in the same sense the graph is.\n'
    + '\n'.join(CACHE_IGNORED) + '\n'
)


# Every entry this file has ever contained. A file listing only these was written by us and
# can be upgraded in place; one containing anything else was edited by hand and is left alone.
#
# Without this history the upgrade only fired on the legacy `*`, so a project that had run a
# single build kept its list forever — and every artifact added afterwards arrived un-ignored
# and committable. ADR-028's graph.<backend>.json did exactly that: `git add -A` staged it.
_EVER_IGNORED = frozenset({'*', 'graph.json', 'graph.*.json',
                          'classifications.json', 'docs.json'})

# Directory names that can never contain a workspace member, however permissive the glob.
_NEVER_A_WORKSPACE = frozenset({'node_modules', '.git', 'dist', 'build', '.next',
                                'vendor', 'target', '__pycache__'})


def _is_ours(text: str) -> bool:
    """Did we write this file? True for any version of it we have ever produced."""
    lines = [ln.strip() for ln in text.splitlines()
             if ln.strip() and not ln.lstrip().startswith('#')]
    return bool(lines) and all(line in _EVER_IGNORED for line in lines)


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
        if path.exists() and not _is_ours(
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
    """Normalize a resolved import edge; a signal target passes through untouched.

    `substrate.IMPORT_SIGNALS` and not a local copy: the tail of a signal is whatever the
    source file wrote, or an alias the project chose, and re-keying either would be wrong —
    but the *list* of what counts as a signal has to be the same one `substrate.is_internal`
    reads, or this function normalises a target that function then treats as a node.
    """
    return value if value.startswith(substrate.IMPORT_SIGNALS) else normalize_key(value)


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

    def fold(edge: Any, normalise: Any, end: str) -> Any:
        """Fold one edge's far end, whether the edge is an object or a bare string."""
        if isinstance(edge, dict):
            return {**edge, end: normalise(edge.get(end, ''))}
        return normalise(edge)

    migrated: Dict[str, Any] = {}
    for key, info in files.items():
        if isinstance(info, dict):
            info = {
                **info,
                'imports': [fold(i, normalize_import, 'to')
                            for i in info.get('imports', [])],
                'dependents': [fold(d, normalize_key, 'from')
                               for d in info.get('dependents', [])],
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
        # The declared out-of-tree roots (ADR-031); None until settings.json is read once.
        # Empty is both the default and the common case, and an empty one answers every
        # containment question without a single filesystem call.
        self._outside_cache: Optional[settings.OutsideRoots] = None
        # Discovery candidates whose realpath left the project (SEC-023), as
        # {rel_path: crossing-token-or-None}. Populated by `_scan_files` and drained into
        # the artifact by `_escaping_links_report`, because a silently shrinking file set
        # produces a blast radius that is quietly too small — the failure ADR-029 exists
        # against — and because stderr is dead skill-to-skill.
        self._escaping_links: Dict[str, Optional[str]] = {}

    def _record_escaping_link(self, rel_path: str, crossing: Optional[str]) -> None:
        """Note a discovery candidate that resolved out of the project, once.

        `crossing` is `outside:<alias>/<tail>` when a declared root covers the target and
        None when nothing did. Both are recorded: the declared one is legitimate and is
        reported as a crossing, the undeclared one is refused — and a reader needs to be able
        to tell which happened without re-running the build.
        """
        self._escaping_links.setdefault(rel_path, crossing)

    # -------------------------------------------------------------------------
    # The substrate contract (see substrate.py). This class is freya's first
    # backend — the stdlib-only floor that is always installed.
    # -------------------------------------------------------------------------

    name = 'homegrown'

    def coverage(self) -> substrate.Coverage:
        """What this backend actually handles — contract obligation 4.

        `relations` claims `imports` and `re_exports` — the two it genuinely emits, now that
        an edge can carry a kind. It resolves module references between files and has no
        notion of a symbol, so it must not claim `calls`, `inherits` or `references` merely
        because the vocabulary contains them. Overclaiming here is how a caller ends up
        trusting a query the backend cannot answer.
        """
        extensions = sorted({
            os.path.splitext(pattern)[1]
            for patterns in FILE_PATTERNS.values()
            for pattern in patterns
        })
        return substrate.Coverage(
            languages=FILE_PATTERNS.keys(),
            extensions=extensions,
            relations=(_IMPORTS, _RE_EXPORT),
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
        input from the three places the project states it: the built-in name lists, directory
        classifications, and `.gitignore`.

        The built-in lists used to be missing here, and were applied only inside
        `CodeGraph._should_exclude` — i.e. only by the backend that happens to own them. So a
        project running graphify graphed `vendor/`, `target/` and the toolkit's own
        `knowledge-base/`, while the floor on the same repository did not. Measured on a
        fixture: three files graphed, two of which the floor excludes. Two backends disagreeing
        about scope on the same repository is exactly the outcome ADR-018 exists to prevent, and
        the obligation that says so was being honoured by one implementation only.

        The three tiers map onto the contract's two:
          - `always_exclude_dirs` match at any depth, which is gitignore semantics -> patterns.
          - `top_level_exclude_dirs` match only from the root, which is what `Exclusions`
            `directories` already means -> directories.
          - `always_exclude_files` are globs -> patterns.

        Classifications are read in both directions. `exclude` narrows scope; `source` from a
        person or a model widens it back over `.gitignore`, and travels as `overrides` so that
        every backend honours it and not only this one. Carrying the built-ins as patterns is
        also what makes an override safe: `Exclusions._excluded_under_override` re-matches
        patterns against the path *below* the override root, so declaring `packages/` source
        still does not admit `packages/*/node_modules/**`.
        """
        rules = self._get_exclusion_rules()
        classified = (self._load_classifications().get('directories') or {})
        verdicts = [(name, verdict) for name, verdict in classified.items()
                    if isinstance(verdict, dict)]
        overrides = [name for name, verdict in verdicts
                     if verdict.get('type') == 'source'
                     and verdict.get('source') in _OVERRIDES_CONVENTIONS]

        def shadowed(name: str) -> bool:
            """Does `name` sit inside a directory this project declared source?"""
            parts = name.split('/')
            return any(name != o and parts[:len(o.split('/'))] == o.split('/')
                       for o in overrides)

        return substrate.Exclusions(
            # A *derived* exclusion inside an override is dropped, because it is the name
            # lists asserting themselves one level down from where they were overruled —
            # and a cached one from an earlier build would otherwise beat the override by
            # having got there first. A *stated* one is kept: that is a carve-out the
            # project asked for, and `Exclusions.excludes` honours it as the deeper rule.
            directories=[name for name, verdict in verdicts
                         if verdict.get('type') == 'exclude'
                         and not (shadowed(name) and verdict.get('source')
                                  not in _OVERRIDES_CONVENTIONS)]
            # Top-level-only, and an override still beats them: `overrides` is consulted
            # first, and a depth-0 name cannot re-exclude the override it names.
            + [name for name in sorted(rules['top_level_exclude_dirs'])
               if name not in overrides],
            patterns=sorted(rules['always_exclude_files'])
            + ['%s/' % name for name in sorted(rules['always_exclude_dirs'])]
            + self._parse_gitignore(),
            matcher=gitignore_excludes,
            overrides=overrides,
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

    def _get_changed_files(self, since_commit: str) -> Optional[List[str]]:
        """Files changed since `since_commit`, or None if git could not say.

        None and `[]` are different answers, and they used to be the same one. `[]` means
        "nothing changed" and short-circuits `update()` — so a commit git cannot resolve
        (rebased away, squashed, a graph carried between checkouts, git not installed)
        produced "Graph is up to date. No changes detected." forever. The graph never
        refreshed and never said why.

        `--no-renames` because this asks *which paths moved*, not *what the author meant*.
        With rename detection on — git's default — a moved file is reported once, as its
        destination, and the path it vanished from is never named. `update()` only removes
        an entry when git names it, so the old path stayed in the graph as a ghost node:
        `--dependents` on it answered confidently with files that no longer import it, and
        every blast radius through it was computed against a file that does not exist.
        Only a full `--build` cleared it.
        """
        try:
            result = subprocess.run(
                # `--relative` because `--name-only` emits paths from the *repository* root
                # while everything downstream — `graph['files']` keys, `project_dir / path` —
                # is project-relative. Whenever the project is a subdirectory of the repo
                # (`--dir pkg`, or a monorepo package, or this toolkit run against a
                # sub-project) every returned path carried an extra prefix, so no file ever
                # matched, `update()` found nothing to do and reported success. The graph then
                # froze at the last full build while continuing to answer confidently.
                # A no-op at the repository root, so it cannot regress the common case.
                ['git', 'diff', '--name-only', '--no-renames', '--relative',
                 '--end-of-options', f'{since_commit}..HEAD'],
                cwd=self.project_dir,
                capture_output=True,
                text=True,
            )
        except Exception:
            return None
        if result.returncode != 0:
            return None
        return [f.strip() for f in result.stdout.strip().split('\n') if f.strip()]

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

    def _outside_roots(self) -> settings.OutsideRoots:
        """The out-of-tree roots this project declared, read once (ADR-031).

        Cached on the instance for the reason `_alias_cache` is: `_contain` runs once per
        candidate per import, and this reads a file. Read here rather than off the back of
        `_declared_directories`, which is the other reader of this file, because that runs only
        on the classification path — a `--update` or a `--query` resolves imports without going
        near it, and a declaration that applied on `--build` and not on `--update` would be the
        worst possible version of this feature.

        The warnings are announced here as well as there. `_announce_once` makes the overlap
        free, and a refused declaration that printed on one entry point and not the other is
        the silence this whole section is written against.
        """
        if self._outside_cache is None:
            conf = settings.load(str(self.project_dir))
            for warning in conf.warnings:
                _announce_once('code-graph: %s' % warning)
            self._outside_cache = conf.outside
        return self._outside_cache

    def _contain(self, candidate: Path) -> Optional[str]:
        """The graph key for `candidate`, or None when it is not this project's to resolve.

        Two questions, asked in this order, and deliberately not the same question twice.
        First: is it inside the project? That is **lexical** — `containment.rel_within`, which
        normalises and does not resolve. Only if the answer is no is the second question asked:
        is it under a root this project *declared* outside itself? That one is **resolved** on
        both sides, because it is a security decision rather than a key derivation.

        A method rather than a bare call at each site, and this is the change it was written
        for: the out-of-tree branch lands in one place instead of being copied into
        `_resolve_fs` and `_resolve_python_module`, where the two would eventually disagree
        about what the project is.

        What the caller gets back is a **key or a signal**, not a path. An out-of-tree file has
        no project-relative spelling — that is the whole reason `../shared` corrupted the graph
        when it was allowed as a directory key — so it comes back as `outside:<alias>/<rel>`,
        which is a signal (`substrate.IMPORT_SIGNALS`) and never a node.

        The caller's next question is `_is_real_file`, and it is still asked in that order.
        State the guarantee that buys with its condition attached, because the unqualified
        version is false: containment runs before any `is_file()` and before any `listdir`, so
        nothing that is neither in the project nor declared is ever **opened or enumerated** —
        but the candidate has already been realpathed by the time it arrives here, declared or
        not. `_resolve_import_path` builds it with `(from_dir / import_path).resolve()`, which
        `lstat`s every component of a `../..` specifier whether or not this project has ever
        declared anything. That is pre-existing, it is the one `realpath` ADR-031's Rationale
        prices, and it is why the test that pins this measures `_dir_listing_cache` — the
        record of every `listdir` — rather than claiming no syscall leaves the root.

        `containment.rel_within`, deliberately, and not either of its neighbours:

          - not `escapes`, which judges a value **declared** in checked-in data. What
            arrives here is a `Path` this resolver just built out of a tsconfig target, a
            workspace root or a Python search base. The join has already happened, and the
            escape this exists to catch is only visible once it has.
          - not `within`, which realpaths both sides. The return value becomes a graph key,
            and `graph.json`, `behavior.json` and `docs.json` are joined on that key by set
            intersection (ADR-025), so resolving would re-key a legitimately symlinked
            in-project file to its realpath — the file would not join wrongly, it would stop
            joining at all and a blast radius would come back quietly short. The candidate
            also need not exist yet; `_is_real_file` is the next question, not this one.

        What it fixes: `relative_to` compares *parts*, so `/proj/../outside/secret.ts`
        relative to `/proj` succeeded and handed back `../outside/secret.ts` — a path
        `normalize_key` cannot collapse, recorded as an internal edge target (SEC-014).
        Measured on a project whose tsconfig maps `@evil/*` to `../outside/*`: the edge was
        `../outside/secret.ts` and is now `unresolved:@evil/secret`. `rel_within` normalises
        before it compares, which is what makes the question answerable at all.

        And `containment.within` for the second question, for the opposite reason: the answer
        there decides whether a path outside the project is reached at all, so a symlink under
        a declared root that points somewhere else must not be followed into. A symlink is an
        implicit crossing and a declaration never re-authorises one (SEC-008).
        """
        rel = containment.rel_within(self.project_dir, candidate)
        if rel is not None:
            return normalize_key(rel)
        return self._outside_roots().key_for(candidate)

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
            key = self._contain(candidate)
            if key is None:
                continue
            # A file, and spelled the way it is spelled on disk. Two separate traps:
            # the bare path is the first candidate and a *directory* satisfies exists(),
            # so `from './accessibility'` used to resolve to the folder and never reach
            # its index; and on a case-insensitive filesystem `./Utils` matches utils.ts,
            # producing an edge that names no node in the graph.
            if self._is_real_file(candidate):
                return key
        return None

    def _load_workspace_packages(self) -> Dict[str, Path]:
        """Map each workspace package name to its directory. Empty if not a monorepo.

        In a monorepo the cross-package import *is* the architecture — `apps/mobile` depending
        on `packages/domain` is the relationship anyone asking for blast radius cares about.
        Without this it resolves to `external:@scope/name`, indistinguishable from a dependency
        on something off npm, and the graph quietly reports the repo as a set of unrelated
        islands (ADR-019).

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
            if pattern.startswith('/') or pattern.startswith('..'):
                # An absolute or escaping pattern cannot name a package in this repo.
                # Skipping costs edges; letting it through costs the build, because
                # Path.glob rejects an absolute pattern outright on the 3.9 floor.
                continue
            try:
                candidates = sorted(self.project_dir.glob(pattern))
            except (ValueError, OSError, NotImplementedError):
                continue
            for directory in candidates:
                if not directory.is_dir():
                    continue
                # `packages/**` matches vendored trees too, and adopting one is not merely
                # noise: a bundled copy of `react` became a workspace member, so a genuine
                # third-party import resolved as internal and came back `unresolved:react` —
                # the graph asserting that a real dependency is a missing local file.
                if any(part in _NEVER_A_WORKSPACE for part in directory.parts):
                    continue
                # SEC-023's third route, and the one `_scan_files` and `update` did not cover.
                # `Path.glob` follows a directory symlink, so a match can be a package whose
                # files live outside the project — and everything below opens its manifest and
                # then hands `_resolve_fs` a root under it, where `_contain` is lexical by
                # design (ADR-025) and mints `pkglink/ui/src/index.ts` for a file `_scan_files`
                # has already refused. That is two predicates disagreeing about one file in one
                # build, which is why `validate_graph` could only report the symptom ("names no
                # file in the graph").
                #
                # Same rule and same record as its two siblings: `containment.within` decides;
                # a declared target is a crossing rather than an intruder and is still not
                # adopted, because a declaration grants resolution and never re-authorises the
                # implicit crossing a symlink is (SEC-008); and the refusal goes into
                # `substrate.escaping_links`, because stderr is dead skill-to-skill (ADR-029).
                # Stated with its limit attached: `glob` has already listed that directory to
                # produce this candidate, and what stops here is opening, parsing and keying.
                # A glob match is lexically under the root by construction, so the `rel_within`
                # guard decides only whether the refusal is *disclosed*, never whether it
                # happens — the `continue` is not reached through it.
                if not containment.within(self.project_dir, directory):
                    rel = containment.rel_within(self.project_dir, directory)
                    if rel is not None:
                        self._record_escaping_link(normalize_key(rel),
                                                   self._outside_roots().key_for(directory))
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
            key = self._contain(candidate)
            if key is None:
                continue  # neither in the project nor under a declared root; not ours
            if self._is_real_file(candidate):
                return key
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

    def _parse_imports(self, content: str, language: str) -> List[tuple]:
        """Extract `(specifier, relation)` pairs from file content.

        One pair per distinct specifier, with `imports` beating `re_exports` when a file does
        both to the same one: it genuinely depends on the module, and `re_exports` is for the
        case where forwarding is *all* it does with it — the barrel.

        Deduping by specifier is not enough on its own. `./sub` and `./sub/index` are two
        specifiers naming one file, so the second dedupe — by *resolved target* — happens in
        `_build_file_info`, which is the first place that knows they are the same.
        """
        kinds = {}  # type: Dict[str, str]

        for pattern, relation in IMPORT_PATTERNS.get(language, []):
            for match in re.findall(pattern, content, re.MULTILINE):
                if isinstance(match, tuple):
                    match = match[0] if match[0] else match[1] if len(match) > 1 else ''
                match = (match or '').strip()
                # `from . import leaf` leaves only the dots here: the module name lives in the
                # import clause, which these patterns do not capture. Punctuation is not a
                # module reference, and emitting it would later surface as `unresolved:.` — a
                # parser artifact wearing the costume of a coverage gap. The edge is missed
                # either way (backlog item 10); this keeps it from also being misreported.
                if not match or not match.strip('.'):
                    continue
                if kinds.get(match) != _IMPORTS:
                    kinds[match] = relation

        return sorted(kinds.items())

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
                # A backend's output, for the same reason. graphify writes its extraction,
                # an HTML viewer and dated backups into graphify-out/ at the project root;
                # left in, the substrate would index its own working notes and report them
                # as project source. `project_shape` already skipped this directory for the
                # blind-spot census and the exclusion rules did not, which is the kind of
                # disagreement between two copies of one idea that this repo keeps paying for.
                'graphify-out',
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
            # indexing them is measurably noise: a top-level `docs/` here held the
            # published site's bundled JS and this spike's planted fixtures, none of
            # which belong in a blast radius. (This repo's own tree moved to
            # `knowledge-base/` on 2026-08-21, where `always_exclude_dirs` covers it at
            # any depth; the measurement stands, the path is history.) Below the root,
            # the name carries no such promise, so the judgement passes to
            # classifications.json — per-project and overridable, which a hardcoded
            # name list is not.
            #
            # 'scripts' is here rather than removed outright. Dropping it entirely was
            # the wider change: a root `scripts/` had been excluded in every project the
            # toolkit had ever run on, and un-excluding it everywhere to fix one repo's
            # nested `skills/*/scripts/` is a change nobody asked for. Top-level-only
            # restores the old answer at the root and keeps the fix below it.
            #
            # None of these is final. Every name here can be overridden per project —
            # see `_OVERRIDES_CONVENTIONS` and `_should_exclude`. A default that cannot
            # be argued with is a guess with no way to be wrong out loud.
            'top_level_exclude_dirs': {
                'docs', 'examples', 'scripts',
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

    def _override_root(self, rel_path: str, classified: Dict[str, Any]) -> Optional[str]:
        """The deepest ancestor of `rel_path` a person declared source, if any.

        Needed so an artifact-tree name can be re-matched against the path *below* that
        root — see `_should_exclude` step 3.
        """
        ancestors = rel_path.split('/')[:-1]
        for depth in range(len(ancestors), 0, -1):
            name = '/'.join(ancestors[:depth])
            verdict = classified.get(name)
            if (isinstance(verdict, dict) and verdict.get('type') == 'source'
                    and verdict.get('source') in _OVERRIDES_EVERYTHING):
                return name
        return None

    def _stated_verdict(self, rel_path: str,
                        classified: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        """The verdict that governs `rel_path`, from its classified ancestors.

        Two rules, in this order:

        1. **A stated verdict outranks a derived one, at any depth.** `user` and `ai`
           verdicts are judgements about this project; `rule` and `gitignore` verdicts are
           the built-in name lists' own output. Without this, marking `docs/` as source
           lost to a *stale* `docs/literate: exclude` that an earlier build had derived and
           cached — the lists beating the person by having got there first.
        2. **Among equals, deepest wins.** So `packages/` can be source while
           `packages/legacy/` is not, and a carve-out inside an override still applies.
        """
        ancestors = rel_path.split('/')[:-1]
        derived = None
        for depth in range(len(ancestors), 0, -1):
            verdict = classified.get('/'.join(ancestors[:depth]))
            if not isinstance(verdict, dict):
                continue
            if verdict.get('source') in _OVERRIDES_CONVENTIONS:
                return verdict
            if derived is None:
                derived = verdict
        return derived

    def _inherits_a_stated_verdict(self, dir_name: str,
                                   classified: Dict[str, Any]) -> bool:
        """Has this project already ruled on an ancestor of `dir_name`?

        If so the directory needs no verdict of its own — it inherits, and
        `_stated_verdict` will find the ancestor.

        Skipping it is not an optimisation. Classifying it anyway re-applies the very
        name lists the ancestor's verdict overrode, one level down, and writes the
        result *deeper* than the override — where the deepest-first walk then prefers
        it. Marking `docs/` as source achieved nothing for exactly this reason: the
        rules promptly classified `docs/literate` as excluded and won.
        """
        return (self._stated_verdict(dir_name, classified) or {}).get(
            'source') in _OVERRIDES_CONVENTIONS

    def _should_exclude(self, rel_path: str, gitignore_patterns: List[str],
                        classified: Optional[Dict[str, Any]] = None) -> bool:
        """Is this path out of scope for the graph?

        Two kinds of rule meet here, and the ordering between them is the point.

        The **built-in name lists** are defaults. They are guesses that hold for most
        repositories and cannot possibly hold for all of them — nothing in this file knows
        that some project keeps its source in `target/`, or that another's `docs/` is a
        literate-programming tree that really is the code.

        The **project's own classifications** are what that project says about itself. Until
        2026-08-20 they could only ever *narrow* scope: marking a directory `source` did
        nothing, because this method never consulted them, so `set_classification('docs',
        'source')` was accepted, written to disk, and then silently overruled. A default
        that cannot be argued with is not a default, it is a hardcoded answer — and the one
        thing certain about a hardcoded answer is that it is wrong for somebody.

        So a stated verdict is consulted first, and outranks the lists per
        `_OVERRIDES_EVERYTHING` / `_OVERRIDES_CONVENTIONS`. File patterns are the exception
        and stay unconditional: `*.d.ts` and `*.min.js` are claims about what a *file* is,
        not about which directories are in scope, and re-admitting a source map because its
        directory was marked source helps nobody.
        """
        from fnmatch import fnmatch

        rules = self._get_exclusion_rules()
        path_parts = Path(rel_path).parts
        filename = Path(rel_path).name

        # 1. File kinds, unconditionally. Not a scope judgement — see the docstring.
        for pattern in rules['always_exclude_files']:
            if fnmatch(filename, pattern):
                return True

        # 2. What the project says about itself, deepest ancestor first.
        verdict = self._stated_verdict(rel_path, classified or {})
        stated = (verdict or {}).get('type')
        source = (verdict or {}).get('source')
        if stated == 'exclude':
            # Held here rather than at the call sites, which each used to walk the ancestors
            # themselves — two copies of one rule, which is how they came to disagree.
            return True

        # 3. Artifact trees, wherever the name appears. A nested node_modules is still
        #    node_modules, so unlike the convention names these match at any depth.
        #
        #    Under a `user` override the check is re-applied *below the override root*
        #    rather than skipped. An override says "this directory is in scope, whatever the
        #    convention decided"; it does not say "and nothing inside it can ever be out of
        #    scope". Skipping it outright is the 50,000-file blowup
        #    `Exclusions._excluded_under_override` was written to close — measured on an
        #    npm-workspaces tree, where `{"packages": "source"}` admitted every
        #    `packages/*/node_modules/**` — and the fix had been applied to the contract's
        #    copy of the rule and not to this one. Two implementations of one rule, which is
        #    how they came to disagree; verified by asserting the two agree.
        override_root = self._override_root(rel_path, classified or {}) \
            if stated == 'source' and source in _OVERRIDES_EVERYTHING else None
        if override_root is None:
            checked_parts = path_parts
        else:
            checked_parts = Path(rel_path).parts[len(override_root.split('/')):]
        for exc_dir in rules['always_exclude_dirs']:
            if exc_dir in checked_parts:
                return True

        # 4. Convention directories, at the repo root only. See the set's comment.
        if stated != 'source' or source not in _OVERRIDES_CONVENTIONS:
            if len(path_parts) > 1 and path_parts[0] in rules['top_level_exclude_dirs']:
                return True
            # 5. gitignore — shared with _classify_with_rules.
            #
            # Overridable for the same reason: a project that gitignores its build output
            # and then vendors real source underneath it has said so explicitly, and git's
            # opinion about what to commit is not the same question as what to graph.
            return gitignore_excludes(rel_path, gitignore_patterns)

        return False

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

    def _declared_directories(self) -> Dict[str, Any]:
        """Directory verdicts from `knowledge-base/settings.json`, as classification entries.

        This is the committed half, and it is the only half that survives a clone.
        `classifications.json` is gitignored regenerable cache, so an override recorded only
        there worked for whoever typed it and vanished for everyone else — CI and every
        colleague silently graphed a smaller codebase and were told the build succeeded.
        ADR-019 had already rejected that file as a home for a decision, on exactly this
        ground, before the override was put in it.

        Labelled `source: 'user'` because that is what a committed, hand-written settings file
        is, and it is what earns the strongest override tier.
        """
        conf = settings.load(str(self.project_dir))
        for warning in conf.warnings:
            _announce_once('code-graph: %s' % warning)
        return {
            name: {'type': verdict, 'confidence': 1.0, 'source': 'user',
                   'reasoning': _DECLARED_IN_SETTINGS}
            for name, verdict in conf.directories.items()
        }

    def _load_classifications(self) -> Dict[str, Any]:
        """Directory verdicts: the committed ones, over the cached ones.

        The cache is `classifications.json`. The builder skips any directory already present
        there, so without the `RULES_VERSION` discard a rule change only ever reached a fresh
        clone: every project graphed before the change kept the old answer indefinitely, and
        `--clear` does not remove the file. Only `rule` and `gitignore` verdicts are dropped —
        they are re-derivable, so the rules are their single source of truth. An `ai` verdict
        is a judgement about this project that no rule change invalidates, and it stays.

        Over the top of all that go the verdicts declared in `settings.json`, which win because
        they are the ones a person wrote down and committed.

        Keys are folded to the form the graph uses. `"docs/"`, `"./docs"`, `"docs\\lit"` and
        `"docs//lit"` all name the same directory to a person, and only one of them used to
        match anything — the rest were dead keys that produced no error and no effect.
        """
        data = {'version': 1, 'rules_version': RULES_VERSION, 'directories': {}}
        if self.classifications_path.exists():
            try:
                with open(self.classifications_path) as f:
                    loaded = json.load(f)
                if isinstance(loaded, dict):
                    data = loaded
            except Exception:
                pass

        cached = data.get('directories')
        cached = cached if isinstance(cached, dict) else {}
        if data.get('rules_version') != RULES_VERSION:
            cached = {name: verdict for name, verdict in cached.items()
                      if not isinstance(verdict, dict)
                      or verdict.get('source') not in ('rule', 'gitignore')}
            data['rules_version'] = RULES_VERSION

        folded = {}  # type: Dict[str, Any]
        for name, verdict in cached.items():
            key = settings.normalise_dir_key(name)
            if key:
                folded[key] = verdict
        folded.update(self._declared_directories())
        data['directories'] = folded
        return data

    def _save_classifications(self, classifications: Dict[str, Any]) -> None:
        """Save classifications to file, minus anything `settings.json` declared.

        `_load_classifications` folds the committed verdicts over the cached ones so the
        build sees both. Persisting the result baked them into the cache as ordinary `user`
        entries — and then they outlived the file that declared them: deleting
        `"docs": "source"` from `settings.json` changed nothing, because the copy in
        `classifications.json` still outranked every rule, survived the `RULES_VERSION`
        discard (only `rule` and `gitignore` verdicts are dropped) and survived `--clear`
        (which deliberately keeps this file). The only way back was to hand-edit a
        gitignored cache.

        That inverts ADR-019 exactly: the committed file is supposed to be the source of
        truth, and the cache had quietly become the one that won. So the cache never holds
        a settings-declared verdict — it is not cache, it is a decision, and it has a home.
        """
        self._ensure_graph_dir()
        classifications['version'] = 1
        classifications['rules_version'] = RULES_VERSION
        classifications['classified_at'] = datetime.now(timezone.utc).isoformat()

        declared = set(self._declared_directories())
        directories = classifications.get('directories')
        if isinstance(directories, dict):
            classifications = dict(classifications)
            classifications['directories'] = {
                name: verdict for name, verdict in directories.items()
                # By key for what is declared now, and by marker for what an older version
                # already baked in — otherwise a stale entry from before this fix would
                # keep winning forever, which is the defect itself.
                if name not in declared
                and not (isinstance(verdict, dict)
                         and verdict.get('reasoning') == _DECLARED_IN_SETTINGS)
            }

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

            # An ancestor this project has already ruled on decides for it.
            if self._inherits_a_stated_verdict(dir_name, known_classifications):
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
                if self._inherits_a_stated_verdict(dir_name, known_classifications):
                    continue
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
                if self._inherits_a_stated_verdict(dir_name, known_classifications):
                    continue
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

        # Where to start globbing. A scan root has to be top-level, because that is what
        # `project_dir / src_dir` walks — but a *nested* source verdict still has to be
        # reachable, so it contributes its top-level ancestor as a root.
        #
        # Without that second half the escape hatch only half works: marking
        # `docs/literate` as source records the verdict, and then nothing ever globs
        # under `docs/` to find the files it was about. Widening the root is safe because
        # `_should_exclude` still runs per file, and everything under `docs/` that the
        # verdict did not name is still excluded by the convention rule.
        source_dirs = sorted({
            d.split('/')[0] for d, info in classified_dirs.items()
            if isinstance(info, dict) and info.get('type') == 'source'
        })

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

                # One decision, in one place. The ancestor walk used to be inlined here and
                # again in `update()`, each consulting only `exclude` verdicts — so a
                # `source` verdict was accepted, written to disk and never read by anything.
                if self._should_exclude(rel_path, gitignore_patterns, classified_dirs):
                    continue

                # SEC-023. Discovery is where a symlink crossed the root, and ADR-031's
                # "crossing is a declared act" was true of imports and false here: a symlink
                # committed *inside* the project whose target is outside it was globbed,
                # opened, parsed, and its declarations published as this node's `exports` —
                # no declaration, nothing on stderr. It is SEC-008's defect on the other
                # traversal; that one bounded docs-manager's YAML walk, and this walk never
                # got the same rule.
                #
                # `containment.within`, not `os.path.islink`: the question is not "is this a
                # link" but "does the file this names live inside the project". An in-project
                # symlink is legitimate and common — a monorepo links a package into place —
                # and blanket-refusing links would empty those graphs. `within` realpaths both
                # sides and catches the ValueError `commonpath` raises across Windows drives.
                #
                # Read the polarity carefully: `within` returning False is the *permissive*
                # branch for `exec_path.resolve` ("not the scanned repo's own binary, so run
                # it") and the *refusing* branch here. Same predicate, opposite question.
                if not containment.within(self.project_dir, f):
                    # Declared, so it is a crossing rather than an intruder — and it lands on
                    # the same side of the line as an import into a declared root: reported,
                    # never a node. Otherwise the declaration would buy strictly more through
                    # a symlink than through an import, which is incoherent.
                    self._record_escaping_link(rel_path, self._outside_roots().key_for(f))
                    continue

                filtered.append(f)
            except ValueError:
                continue

        # Remove duplicates
        # sorted, not list(set(...)): set iteration order varies per process, which
        # made graph.json key order — and every dependents list built from it —
        # differ between two builds of identical input.
        return sorted(set(filtered))

    def _build_file_info(self, file_path: Path) -> Dict[str, Any]:
        """Build file info dict for a single file.

        A file that cannot be read — a broken symlink, a permission denial, an I/O error —
        still gets a node, because it is genuinely part of the project and dropping it
        would silently shrink the file set. But it gets an *honest* one: the failure is
        announced and recorded on the node, rather than producing an entry that is
        indistinguishable from a real file which happens to import nothing.

        The difference matters because blast radius walks edges. A zero-edge node cuts
        every dependency chain that ran through it, and the build reported success with
        nothing on stderr and nothing in `substrate.validation` — a confidently empty
        answer about one file, which is the failure ADR-005 exists to prevent, scoped
        down small enough that nobody notices it.
        """
        try:
            content = file_path.read_text(encoding='utf-8', errors='ignore')
        except Exception as exc:
            try:
                rel = normalize_key(file_path.relative_to(self.project_dir))
            except ValueError:
                rel = str(file_path)
            _announce_once('code-graph: could not read %s (%s); it is in the graph with no '
                           'edges, so anything that depends through it will look '
                           'unaffected' % (rel, exc.__class__.__name__))
            return {'imports': [], 'dependents': [], 'exports': [],
                    'unreadable': exc.__class__.__name__}

        language = self._detect_language(file_path)
        rel_path = normalize_key(file_path.relative_to(self.project_dir))

        imports = self._parse_imports(content, language) if language else []
        exports = self._parse_exports(content, language) if language else []

        # Resolve + classify import paths (internal / external: / unresolved:), then wrap
        # each as an edge. Provenance is `extracted` throughout: this resolver reads import
        # statements out of the source text and nothing else, so claiming `inferred`
        # anywhere would overstate what it did.
        #
        # Keyed by resolved target, because two specifiers can name one file: `./sub` and
        # `./sub/index` both land on `src/sub/index.ts`. Keyed by specifier instead, that
        # file would carry two edges to one target with contradictory kinds, and every
        # dependents list would count it twice.
        by_target = {}  # type: Dict[str, str]
        for imp, kind in imports:
            target = self._classify_import(imp, rel_path, language)
            if by_target.get(target) != _IMPORTS:
                by_target[target] = kind
        resolved = [substrate.make_edge(target, kind=kind)
                    for target, kind in sorted(by_target.items())]

        return {
            'exports': exports,
            'imports': resolved,
            'dependents': [],
            'language': language,
        }

    def build(self, ai_response: Optional[str] = None, non_interactive: bool = False,
              exclusions: Optional[substrate.Exclusions] = None,
              selection_metadata: Optional[Dict[str, Any]] = None) -> substrate.Result:
        """Produce the dependency graph from scratch.

        Produce, not persist. Linking `dependents`, validating and writing belong to the
        contract and happen in `run_build` — see `substrate.Result`. This method's whole
        job is nodes and edges.

        Args:
            ai_response: Pre-fetched AI response for directory classification
                         (used when skill invokes this with AI access)
            non_interactive: Never prompt for directory classification (F6)
            exclusions: Contract obligation 6 — what the project has declared out of
                        scope. Omitted, the backend derives them from the project itself,
                        which is what every current caller relies on.
            selection_metadata: `degraded_from`/`degraded_reason` from backend selection.
                        Recorded in the graph so a fallback is visible in the artifact and
                        not only on the stderr of the run that produced it — a thin graph
                        must never be mistakable for a thin repo.
        """
        print(f'Scanning {self.project_dir}...', file=sys.stderr)

        # Step 1: Classify directories (rules → AI → user)
        print('Classifying directories...', file=sys.stderr)
        classifications = self._classify_directories(use_ai=True, ai_response=ai_response,
                                                      non_interactive=non_interactive)
        # `isinstance` because hand-editing this file is a documented path, and every other
        # reader already guards. Without it `"docs": "source"` — the obvious shorthand
        # mistake, given the docs talk about a `source` field — aborted the build with a raw
        # AttributeError instead of a message naming the bad key.
        verdicts = [v for v in (classifications.get('directories') or {}).values()
                    if isinstance(v, dict)]
        source_count = sum(1 for v in verdicts if v.get('type') == 'source')
        exclude_count = sum(1 for v in verdicts if v.get('type') == 'exclude')
        print(f'Classified: {source_count} source dirs, {exclude_count} excluded dirs', file=sys.stderr)

        # Step 2: Scan files using classifications
        files = self._scan_files(classifications)

        # A caller-supplied exclusion set is applied on top of the project's own, never
        # instead of it: the caller is adding scope knowledge, not overriding the repo's
        # .gitignore.
        if exclusions is not None:
            files = [f for f in files
                     if not exclusions.excludes(normalize_key(f.relative_to(self.project_dir)))]
        print(f'Found {len(files)} source files', file=sys.stderr)

        # Build file info
        graph = {
            'version': substrate.GRAPH_SCHEMA_VERSION,
            'commit': self._get_git_commit(),
            'timestamp': datetime.now(timezone.utc).isoformat(),
            'project_root': str(self.project_dir),
            'substrate': substrate.graph_metadata(
                self.name, self.coverage(),
                exclusions if exclusions is not None else self.project_exclusions(),
                degraded_from=(selection_metadata or {}).get('degraded_from'),
                degraded_reason=(selection_metadata or {}).get('degraded_reason')),
            'files': {},
        }

        for file_path in files:
            rel_path = normalize_key(file_path.relative_to(self.project_dir))
            graph['files'][rel_path] = self._build_file_info(file_path)

        # Held rather than returned-and-forgotten: `link_dependents` mutates in place, so
        # after `run_build` this same object is the finished graph.
        self.graph = graph
        return substrate.Result(graph, substrate.Result.BUILT)

    def load(self) -> Optional[Dict[str, Any]]:
        """Load the cached graph, bringing older ones forward on the way in.

        Two migrations, both on read for the same reason: the artifact is gitignored, so
        there is no committed copy to fix in a commit. Whatever is on a given machine's disk
        is whatever the last build there wrote, and refusing to read it would look exactly
        like a project with no dependencies.
        """
        if self.graph_path.exists():
            with open(self.graph_path, encoding='utf-8') as f:
                self.graph = substrate.upgrade_edges(migrate_separators(json.load(f)))
            return self.graph
        return None

    def update(self, non_interactive: bool = False,
               exclusions: Optional[substrate.Exclusions] = None,
               selection_metadata: Optional[Dict[str, Any]] = None) -> substrate.Result:
        """Incrementally update the graph. Produces; `run_update` persists."""
        graph = self.load()
        if not graph:
            print('No cached graph found. Running full build...', file=sys.stderr)
            return self.build(non_interactive=non_interactive, exclusions=exclusions,
                              selection_metadata=selection_metadata)

        last_commit = str(graph.get('commit') or '')
        if not re.fullmatch(r'[0-9a-fA-F]{7,64}', last_commit):
            print('No usable commit in cached graph. Running full build...', file=sys.stderr)
            return self.build(non_interactive=non_interactive, exclusions=exclusions,
                              selection_metadata=selection_metadata)

        produced_by = substrate.produced_by(graph)
        if produced_by is not None and produced_by != self.name:
            # A different backend wrote this artifact. Incrementally patching it would splice
            # this resolver's edges into another's graph — a file-level `imports` edge landing
            # beside symbol-refined `calls` edges, under a `substrate` block claiming the
            # other backend's coverage. And because freshness was judged from `commit` alone,
            # switching `substrate.backend` back to this one and running `--update` reported
            # `up_to_date` and kept the *other* backend's graph indefinitely.
            print('Cached graph was produced by %r, not %r. Running full build...'
                  % (produced_by, self.name), file=sys.stderr)
            return self.build(non_interactive=non_interactive, exclusions=exclusions,
                              selection_metadata=selection_metadata)

        if substrate.is_stale(graph):
            # A rebuild, not a rewrite. `load()` brings the *edges* forward, but a graph old
            # enough to be stale may predate the `substrate` block entirely — and that block
            # cannot be reconstructed from the artifact, only from a real build: it records
            # which backend ran and what that backend can see.
            #
            # Stamping the version without it was worse than doing nothing. The graph stopped
            # being stale, so `--update` never looked again, and it was left permanently
            # claiming no backend and no coverage — which is exactly the "is this repo empty
            # or is my backend blind?" question the block exists to answer.
            print('Cached graph is schema v%s (current is v%d). Running full build...'
                  % (graph.get('version'), substrate.GRAPH_SCHEMA_VERSION), file=sys.stderr)
            return self.build(non_interactive=non_interactive, exclusions=exclusions,
                              selection_metadata=selection_metadata)

        declared_then = _declared_roots(_outside_block(graph))
        declared_now = _declared_roots(self._outside_roots().to_dict())
        if declared_then != declared_now:
            # A declaration is not a per-file change, so per-file incrementality cannot see it.
            # `_get_changed_files` names what git says moved, and every *other* file keeps the
            # edges it was given under the old `outside` section — so the artifact ends up
            # holding one import specifier classified two ways, and `_outside_report`, which
            # reads the live settings file, stamps a `crossings` count over edges that were
            # never re-resolved. Both directions were reachable and both lie: remove a
            # declaration and the graph keeps `outside:` targets under no declaration at all,
            # which is the shape ADR-031 defers to "a second backend starts emitting
            # `outside:` tokens"; add one and the report says `crossings: 0` — a number
            # `_outside_report` defines as "a typo or a leftover" — over a file that does
            # cross. This is the same reason `RULES_VERSION` discards cached directory
            # verdicts: a rule change is not a file change.
            #
            # The comparison is over the declarations, not over what they resolve to. A root
            # whose target is replaced on disk between two runs keeps the same signature and
            # does not force a rebuild — git cannot see outside the project, so nothing here
            # could notice that, and the bound is stated rather than implied.
            print('The declared out-of-tree roots changed since the cached graph. '
                  'Running full build...', file=sys.stderr)
            return self.build(non_interactive=non_interactive, exclusions=exclusions,
                              selection_metadata=selection_metadata)

        changed_files = self._get_changed_files(last_commit)
        if changed_files is None:
            print('Cannot resolve %s against HEAD. Running full build...' % last_commit,
                  file=sys.stderr)
            return self.build(non_interactive=non_interactive, exclusions=exclusions,
                              selection_metadata=selection_metadata)
        if not changed_files:
            return substrate.Result(graph, substrate.Result.UP_TO_DATE, 0)

        print(f'Updating graph for {len(changed_files)} changed files...', file=sys.stderr)

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
            if self._should_exclude(rel_path, gitignore_patterns, classified):
                return True
            return exclusions is not None and exclusions.excludes(rel_path)

        for file_path in map(normalize_key, changed_files):
            full_path = self.project_dir / file_path
            # SEC-023 again, on the path the first fix did not reach. `_scan_files` refuses a
            # candidate whose realpath leaves the project; this loop never calls `_scan_files`,
            # so a committed symlink out of the tree was admitted here on `full_path.exists()`
            # — which follows the link — and `_build_file_info` then read the outside file and
            # published its exports as this node's. Worse than the hole it re-opened: `--build`
            # printed a line and recorded `escaping_links`, this printed nothing; and the
            # resulting key IS project-relative, so `validate_graph` passed it clean.
            #
            # It is also the path that matters most: `--update` is what `freya-wrap-up` runs, so
            # `--build` is the cold start and this is the steady state. Fixing discovery and not
            # the incremental loop fixed the rarer half.
            escaped = full_path.exists() and not containment.within(self.project_dir, full_path)
            if escaped:
                self._record_escaping_link(file_path, self._outside_roots().key_for(full_path))
            if full_path.exists() and not escaped and not out_of_scope(file_path):
                # Check if it's a source file
                if self._detect_language(full_path):
                    graph['files'][file_path] = self._build_file_info(full_path)
            elif file_path in graph['files']:
                # Deleted, or newly out of scope. Either way it leaves the graph, and the
                # dependents relink in `run_update` drops every edge that pointed at it —
                # which is why that relink rebuilds from scratch rather than appending.
                del graph['files'][file_path]

        # Update metadata. The substrate block is refreshed rather than carried over, so a
        # graph never claims coverage the currently-installed backend does not have.
        graph['version'] = substrate.GRAPH_SCHEMA_VERSION
        graph['commit'] = self._get_git_commit()
        graph['timestamp'] = datetime.now(timezone.utc).isoformat()
        graph['substrate'] = substrate.graph_metadata(
            self.name, self.coverage(),
            exclusions if exclusions is not None else self.project_exclusions(),
            degraded_from=(selection_metadata or {}).get('degraded_from'),
            degraded_reason=(selection_metadata or {}).get('degraded_reason'))

        self.graph = graph
        return substrate.Result(graph, substrate.Result.UPDATED, len(changed_files))

    def query(self, file_path: str) -> Optional[Dict[str, Any]]:
        """Everything the graph knows about one file.

        The one query that returns edges rather than paths. `--impact`, `--dependents` and
        `--dependencies` answer "which files", and their callers do set arithmetic on the
        answer; this one answers "tell me about this file", so the kind and provenance of
        each edge are the point rather than noise.
        """
        graph = self.load()
        if not graph:
            print('No cached graph found. Run /code-graph build first.', file=sys.stderr)
            return None

        # Normalize path. A caller on Windows naturally passes the path its shell,
        # git status or tab-completion produced (`src\lib\auth.ts`); the key is POSIX
        # on every host, so the lookup is folded rather than the key.
        file_path = normalize_key(file_path)

        info = graph['files'].get(file_path)
        if not info:
            print(f'File not found in graph: {file_path}', file=sys.stderr)
            return None

        # No `category`. The field was removed from the graph in 2026-08-20, and this kept
        # reporting it
        # anyway — always as the literal string 'unknown', for every file, because nothing
        # writes it any more. A field that can only ever hold a placeholder is not a field.
        answer = {
            'file': file_path,
            'exports': info.get('exports', []),
            'imports': info.get('imports', []),
            'dependents': info.get('dependents', []),
            'language': info.get('language'),
        }
        answer.update(_answer_caveats(graph))
        return answer

    def get_dependents(self, file_path: str,
                       transitive: bool = True,
                       announce: bool = True) -> Optional[Set[str]]:
        """Which files depend on this one. `None` if the graph cannot answer.

        `None` and `set()` are different answers and used to be the same one. An empty set
        meant both "nothing imports this" and "this file is not in the graph" — so a caller
        asking about a file the backend never indexed was told, confidently, that nothing
        depends on it.

        behavior-runner is where that lands: it takes an empty closure as a real answer and
        writes a one-file fingerprint into the committed `behavior.json`, which then narrows
        every later blast radius. Moving `scripts` back to a root-level exclusion made it
        newly reachable for any behaviour whose entry lives under one.
        """
        graph = self.load()
        if not graph:
            return None

        file_path = normalize_key(file_path)
        if file_path not in (graph.get('files') or {}):
            print('File not found in graph: %s' % file_path, file=sys.stderr)
            return None

        # Iterative, not recursive. A recursive DFS is bounded by the size of the reachable
        # component rather than by any notion of depth, so a 2,000-file import chain — an
        # ordinary monorepo, and reproduced on a fixture — raised RecursionError and exited
        # non-zero. That is not merely a crash: `run_behaviors` runs `--dependencies` with
        # `check=True`, so it becomes `graph-query-failed`, then `coverage: unknown` for every
        # integration behaviour, then a frozen committed `behavior.json`. The blast radius of a
        # stack overflow here is a silently narrower blast radius everywhere else.
        result = set()
        pending = [file_path]
        while pending:
            info = graph['files'].get(pending.pop(), {})
            # Paths, not edges. This is a *node* query — "which files are affected" — and
            # three other skills feed its output straight into set arithmetic. Returning
            # edge objects here would break them for no gain: the caller asked which files,
            # and `--query` is where the edge detail lives.
            for dep in substrate.edge_ends(info.get('dependents')):
                if dep not in result:
                    result.add(dep)
                    if transitive:
                        pending.append(dep)
        # A bare array has nowhere to qualify itself, so the caveat goes to stderr. See
        # `_announce_unmapped` for why the shape must not change instead.
        #
        # `announce=False` when `get_impact` calls this internally: that surface carries the
        # caveat in its own payload, and the stderr line names `--dependents/--dependencies`,
        # so emitting it from an `--impact` run pointed the reader at commands they had not
        # run and contradicted an answer that was already qualified correctly.
        if announce:
            _announce_unmapped(graph)
            _announce_outside(graph)
        return result

    def get_dependencies(self, file_path: str,
                         transitive: bool = True) -> Optional[Set[str]]:
        """Which files this one depends on. `None` if the graph cannot answer — see
        `get_dependents` for why that is not the same as an empty set."""
        graph = self.load()
        if not graph:
            return None

        file_path = normalize_key(file_path)
        if file_path not in (graph.get('files') or {}):
            print('File not found in graph: %s' % file_path, file=sys.stderr)
            return None

        # Iterative — see `get_dependents` for why a recursive walk was a real defect.
        result = set()
        pending = [file_path]
        while pending:
            info = graph['files'].get(pending.pop(), {})
            # Paths again, and internal ones only — see `get_dependents`.
            for imp in substrate.internal_ends(info.get('imports')):
                if imp not in result:
                    result.add(imp)
                    if transitive:
                        pending.append(imp)
        # A bare array has nowhere to qualify itself, so the caveat goes to stderr. See
        # `_announce_unmapped` for why the shape must not change instead.
        _announce_unmapped(graph)
        _announce_outside(graph)
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
        unknown = set()

        for file_path in file_paths:
            info = graph['files'].get(file_path)
            if info:
                direct.update(substrate.edge_ends(info.get('dependents')))
                all_dependents.add(file_path)
                # `info` is truthy, so the file is a node and this cannot be None. Guarded
                # anyway: the two are three lines apart today and will not always be.
                all_dependents.update(self.get_dependents(file_path, transitive=True, announce=False) or ())
            else:
                unknown.add(file_path)

        if unknown:
            # Said out loud, because the alternative is the failure this whole substrate
            # exists to remove. An input the backend never indexed used to contribute
            # nothing and vanish: `--impact Main.java` under the floor returned
            # `all_affected: []` with exit 0 and no stderr, which reads as "nothing depends
            # on this" and means "I have never seen this file". Its sibling `--dependents`
            # has always said so; this one did not, and it is the one wrap-up calls.
            _announce_once(
                'code-graph: %d of %d file(s) given to --impact are not in the graph (%s). '
                'They contribute no blast radius — which is not the same as having none.'
                % (len(unknown), len(file_paths),
                   ', '.join(sorted(unknown)[:5]) + (', …' if len(unknown) > 5 else '')))

        answer = {
            'input_files': set(file_paths),
            'direct_dependents': direct,
            'transitive_dependents': all_dependents - set(file_paths) - direct,
            'all_affected': all_dependents,
            # Reported in the payload as well as on stderr: the caller is usually another
            # skill reading `--format json`, and stderr is not part of what it parses.
            'not_in_graph': unknown,
        }
        # The same argument, one step wider: `not_in_graph` says the file you asked about is
        # unmapped, `unmapped_source` says this answer is computed over an incomplete graph.
        # Added only inside the populated envelope — the `{}` no-graph branch above is left
        # alone because `drift.py` uses the *presence* of `all_affected` as its "the graph
        # actually ran" signal, and an extra key there would flip every drift run to
        # `changed-only` at exit 0 with nothing going red.
        answer.update(_answer_caveats(graph))
        return answer

    def clear(self) -> bool:
        """Clear the cached graph, including every backend's copy.

        ADR-028 added `graph.<backend>.json` and this was not told about it, so a clear left a
        complete, current-looking graph behind that nothing would ever report as stale. It is
        the worse leftover of the two, because `graph.json` at least announces its absence.

        `classifications.json` is deliberately kept: it holds user and model judgements about
        which directories are source, which a cache clear has no business discarding.
        """
        removed = False
        for path in [self.graph_path] + sorted(self.graph_dir.glob('graph.*.json')):
            if path.exists():
                path.unlink()
                removed = True
        if removed:
            # Try to remove empty directory
            try:
                self.graph_dir.rmdir()
            except Exception:
                pass
            return True
        return False


# =============================================================================
# The contract's half of a build
# =============================================================================
#
# A backend produces nodes and edges. Everything after that — the reverse index, the
# conformance check, the two artifact files — is identical for every backend and is done
# here, once.
#
# The split is not tidiness. Until 2026-08-20 all of it lived inside `CodeGraph.build`,
# which meant the second backend could only get a persisted graph by reimplementing it, and
# would have been free to reimplement it differently. The first thing Phase 2 needs is for
# graphify's output to land in the same place, in the same shape, having passed the same
# check — and that cannot be a thing each backend is trusted to remember.

# Enough to diagnose the problem without turning the artifact into a log file.
_MAX_RECORDED_VALIDATION_ERRORS = 20

# Settings are read by several paths in one run — exclusions, classification, selection — and
# each would otherwise repeat the same complaint about the same typo. Said once per process.
_ANNOUNCED = set()  # type: set


def _announce_once(message: str) -> None:
    if message not in _ANNOUNCED:
        _ANNOUNCED.add(message)
        print(message, file=sys.stderr)


def persist_graph(project_dir: Any, backend_name: str, graph: Dict[str, Any]) -> str:
    """Write the graph as both the active artifact and this backend's own copy.

    `graph.json` stays the active graph because three other skills read that path directly.
    `graph.<backend>.json` is the addition (ADR-028): without it, switching substrates
    destroys the baseline at exactly the moment ADR-028 requires a diff against it.
    """
    directory = Path(substrate.graph_dir(project_dir))
    directory.mkdir(parents=True, exist_ok=True)
    _write_cache_gitignore(directory / '.gitignore')

    payload = json.dumps(graph, indent=2)
    active = substrate.active_graph_path(project_dir)
    for path in (active, substrate.backend_graph_path(project_dir, backend_name)):
        with open(path, 'w', encoding='utf-8') as handle:
            handle.write(payload)
    return active


def _finalise(backend: Any, result: Any,
              exclusions: Optional[substrate.Exclusions] = None) -> Dict[str, Any]:
    """Link, check and persist whatever a backend produced."""
    if not isinstance(result, substrate.Result):
        raise TypeError(
            '%r.%s returned %s; the contract requires a substrate.Result'
            % (getattr(backend, 'name', '?'), 'build/update', type(result).__name__))

    if not result.needs_writing:
        # Nothing to write — and deliberately so, even when the artifact is schema-old.
        #
        # This branch used to rewrite it: stamp the current version, relink, persist. That was
        # worse than leaving it. A graph old enough to be stale may predate the `substrate`
        # metadata block entirely, and that block cannot be reconstructed from the artifact —
        # only a real build knows which backend ran and what it can see. So the rewrite
        # produced a graph claiming no backend and no coverage, and by stamping the version it
        # guaranteed nothing would ever look at it again.
        #
        # Deciding to rebuild belongs to the backend, which has the metadata.
        # `CodeGraph.update` does it. A backend that reports `up_to_date` over a stale artifact
        # is breaking the contract, so say so rather than papering over it.
        if isinstance(result.graph, dict) and substrate.is_stale(result.graph):
            print('code-graph: %r reported up_to_date for a schema-v%s graph, which it should '
                  'have rebuilt. Leaving the artifact alone rather than stamping metadata that '
                  'cannot be recovered from it.'
                  % (getattr(backend, 'name', '?'), result.graph.get('version')),
                  file=sys.stderr)
        # The previous census is carried forward from the loaded artifact rather than re-run.
        # A steady-state `--update` that finds nothing changed still says what the graph
        # cannot see, pays no walk, and writes nothing.
        summary = {'status': result.status, 'files_changed': 0}
        summary.update(_answer_caveats(
            result.graph if isinstance(result.graph, dict) else None, full=True))
        return summary

    graph = substrate.link_dependents(result.graph)

    _refuse_to_erase(backend, graph)

    try:
        coverage = backend.coverage()
    except Exception:
        coverage = None
    errors = substrate.validate_graph(graph, coverage)
    if errors:
        # Written into the artifact as well as to stderr. A dangling edge is a real defect
        # and the run that produced it is the only place its stderr exists; whoever reads
        # the graph a week later needs to be able to see that it was already known to be
        # broken, rather than trusting it and finding out downstream.
        # Not `setdefault`: a backend that put something other than a dict in `substrate` is
        # exactly the kind of backend this branch is reporting on, and indexing its value
        # would turn a diagnostic into a crash.
        if not isinstance(graph.get('substrate'), dict):
            graph['substrate'] = {}
        graph['substrate']['validation'] = {
            'error_count': len(errors),
            'errors': errors[:_MAX_RECORDED_VALIDATION_ERRORS],
        }
        print('code-graph: the graph %r produced breaks the contract in %d place(s); '
              'writing it anyway and recording them under substrate.validation. First: %s'
              % (getattr(backend, 'name', '?'), len(errors), errors[0]), file=sys.stderr)

    # Before `persist_graph`, and here rather than inside `build()`, because `CodeGraph.update`
    # rebuilds `graph['substrate']` wholesale from `graph_metadata()` — anything written under
    # that key from inside a backend is dropped by the very next `--update`. This is also after
    # `_classify_directories` has persisted, so the census sees accurate scope on a first build.
    if not isinstance(graph.get('substrate'), dict):
        graph['substrate'] = {}
    census = _census(backend, graph, exclusions)
    graph['substrate']['unmapped_source'] = census
    if census.get('advice'):
        _announce_once('code-graph: %s' % census['advice'])

    # The same funnel, for the same reason, and the analogue of the census rather than a
    # second mechanism: ADR-029 obliges an answer to say what it could not read, and ADR-031
    # obliges it to say what it read from outside the project.
    crossed = _outside_report(backend.project_dir, graph)
    if crossed:
        graph['substrate']['outside_roots'] = crossed
        sentence = _outside_sentence(crossed)
        if sentence:
            _announce_once('code-graph: %s' % sentence)

    # SEC-023, and the third instance of the same funnel rather than a fourth mechanism: a
    # file this build declined to scan is a fact about the answer's completeness, exactly as
    # an unparseable source is. Absent, not empty, when nothing escaped — so a repository
    # with no symlinks produces byte-identical output (ADR-029).
    escaped = _escaping_links_report(backend)
    if escaped:
        graph['substrate']['escaping_links'] = escaped
        _announce_once('code-graph: %s' % _escaping_links_sentence(escaped))

    cached_to = persist_graph(backend.project_dir, backend.name, graph)

    if result.status != substrate.Result.BUILT:
        summary = {'status': result.status,
                   'files_changed': result.files_changed or 0,
                   'commit': graph.get('commit')}
        summary.update(_answer_caveats(graph, full=True))
        return summary
    summary = substrate.build_summary(graph, cached_to)
    summary['status'] = result.status
    summary.update(_answer_caveats(graph, full=True))
    return summary


class EmptiedTheGraph(RuntimeError):
    """A backend produced nothing where a previous build had found something."""


def _refuse_to_erase(backend: Any, graph: Dict[str, Any]) -> None:
    """Refuse to overwrite a populated graph with an empty one.

    Nothing else catches this. An empty `files` dict passes validation — there is no edge to be
    wrong about — so a backend that silently stops working writes a successful-looking empty
    graph over a good one and reports `status: built`. `_run_or_degrade` never fires, because
    nothing raised.

    It is the exact scenario that function's own docstring names: "the tool it wraps was
    upgraded". Any upstream change to the output shape this projection reads turns 6,000 links
    into zero files, and downstream every skill then reports a repository with no code in it —
    which is the confident-empty answer ADR-005 exists to prevent, arriving through the one
    door the contract had left open.

    Raised rather than warned, so the caller degrades to the floor and the previous artifact
    stays until something can replace it honestly.
    """
    if graph.get('files'):
        return
    previous = substrate.load_graph(substrate.active_graph_path(backend.project_dir))
    if previous and previous.get('files'):
        raise EmptiedTheGraph(
            'produced 0 files where the cached graph has %d; refusing to overwrite it'
            % len(previous['files']))


def _run_or_degrade(runner: Any, backend: Any, floor: Any, non_interactive: bool,
                    exclusions: Any, selection_metadata: Any) -> Dict[str, Any]:
    """Run `backend`; if it fails at *build* time, fall back to the floor and say so.

    Selection already degrades when a backend reports itself unavailable. This is the other
    half, and until now there was no other half: a backend that passed selection and then
    threw — because the tool it wraps was upgraded, or timed out, or exited 0 having written
    nothing — took the whole build down with it. The floor is stdlib-only and always
    installed, so a traceback is never the best available answer.

    The fallback is recorded in the artifact via `degraded_from`, not merely printed, so a
    graph produced this way says on its face that it is thinner than it should be.
    """
    try:
        return runner(backend, non_interactive=non_interactive, exclusions=exclusions,
                      selection_metadata=selection_metadata)
    except Exception as exc:
        if backend is floor or getattr(backend, 'name', None) == floor.name:
            raise  # the floor itself failed; there is nothing left to fall back to
        print('code-graph: %r failed during the build (%s: %s); using %r instead, with '
              'reduced coverage' % (getattr(backend, 'name', '?'), exc.__class__.__name__,
                                    exc, floor.name), file=sys.stderr)
        return runner(floor, non_interactive=non_interactive, exclusions=exclusions,
                      selection_metadata={
                          'degraded_from': getattr(backend, 'name', '?'),
                          'degraded_reason': 'failed during the build: %s' % exc})


def run_build(backend: Any, **kwargs: Any) -> Dict[str, Any]:
    """Build through `backend`, finalise, and return the summary."""
    return _finalise(backend, backend.build(**kwargs), kwargs.get('exclusions'))


def run_update(backend: Any, **kwargs: Any) -> Dict[str, Any]:
    """Update through `backend`, finalise, and return the summary.

    Obligation 5 is enforced here. A backend declares `coverage().incremental`, and `False`
    means "I cannot reliably drop deleted nodes" — at which point trusting an incremental pass
    leaves ghost nodes that answer `--dependents` confidently for files that no longer exist.
    The contract said it forced a full rebuild in that case, in the module docstring, in the
    schema reference, in the spec and in the decision record. Nothing read the flag: it was
    written into every graph and consulted by no code. Both shipped backends declare `True`,
    so no test had ever been in a position to notice.
    """
    try:
        declines = backend.coverage().incremental is False
    except Exception:
        # A backend that cannot describe its own coverage gets the safe answer, not the
        # convenient one.
        declines = True
    if declines:
        return _finalise(backend, backend.build(**kwargs), kwargs.get('exclusions'))
    return _finalise(backend, backend.update(**kwargs), kwargs.get('exclusions'))


def _unmapped_source_paths(scope: 'CodeGraph', covered_extensions: Any,
                           exclusions: Optional[substrate.Exclusions] = None,
                           limit: int = substrate.CENSUS_LIMIT) -> Tuple[List[str], bool]:
    """In-scope files on disk whose extension the running backend does not read.

    Uses the build's *own* scope rule — `_should_exclude` plus the caller's `Exclusions`,
    exactly the two layers `build()` applies — rather than the `substrate.exclusions` recorded
    in the artifact. The recorded set is a strict subset: it carries no `always_exclude_files`,
    no `top_level_exclude_dirs` and no `always_exclude_dirs` below depth two, and on a fresh
    project it is computed before directory classification has run, so it is nearly empty on
    exactly the bootstrap build this exists to serve.

    Getting that wrong is not cosmetic. Measured on this repository, a census that consults
    only `.gitignore`-style patterns reports 96 unread files of which 68 are deliberately out
    of scope — a 71% phantom. A caveat that cries wolf is worse than no caveat, because an
    agent learns to skip the field and then misses the one time it was real.
    """
    candidates = substrate.census_candidates(covered_extensions)
    if not candidates:
        return [], False

    gitignore = scope._parse_gitignore()
    classified = (scope._load_classifications().get('directories') or {})
    root = str(scope.project_dir)
    found = []  # type: List[str]

    for dirpath, dirnames, filenames in os.walk(root):
        # Prune before matching: `_should_exclude` is fnmatch-heavy and is only affordable
        # over the survivors.
        dirnames[:] = [d for d in dirnames
                       if d not in substrate.CENSUS_PRUNE and not d.startswith('.')]
        for filename in filenames:
            if filename.startswith('.'):
                continue  # dotfiles are configuration, not unread source
            ext = os.path.splitext(filename)[1].lower()
            if ext not in candidates:
                continue
            rel = normalize_key(os.path.relpath(os.path.join(dirpath, filename), root))
            if scope._should_exclude(rel, gitignore, classified):
                continue
            if exclusions is not None and exclusions.excludes(rel):
                continue
            found.append(rel)
            if len(found) >= limit:
                return found, True
    return found, False


def _census(backend: Any, graph: Dict[str, Any],
            exclusions: Optional[substrate.Exclusions] = None) -> Dict[str, Any]:
    """The `unmapped_source` block for a graph that is about to be written.

    Never fatal. A census that raises records an explicit error rather than a zero, because a
    silent zero here is indistinguishable from "this backend read everything" — which is the
    confidently-empty answer the whole feature exists to stop.
    """
    name = getattr(backend, 'name', None)
    try:
        try:
            covered = backend.coverage().extensions
        except Exception:
            covered = ()
        scope = CodeGraph(str(backend.project_dir))
        paths, truncated = _unmapped_source_paths(scope, covered, exclusions)
        counts = {}  # type: Dict[str, int]
        for path in paths:
            ext = os.path.splitext(path)[1].lower()
            counts[ext] = counts.get(ext, 0) + 1
        graphed = len(graph.get('files') or {})
        material = substrate.material_extensions(counts, graphed)
        remedies = {}  # type: Dict[str, int]
        # Not on a degraded run. `readable_by` is deliberately availability-blind, which is
        # right for a machine that never installed a better backend — but this run has just
        # *proved* the named backend unavailable and fallen back to the floor. Telling the
        # reader to `--use graphify` in the same breath as "graphify is unavailable" is advice
        # that contradicts the message above it.
        degraded = (graph.get('substrate') or {}).get('degraded_from') \
            if isinstance(graph.get('substrate'), dict) else None
        if material and not degraded:
            try:
                import backends
                remedies = backends.readable_by(material, covered)
            except Exception:
                remedies = {}
        return substrate.unmapped_report(paths, name, graphed, remedies, truncated)
    except Exception as exc:
        return substrate.unmapped_report([], name, error=type(exc).__name__)


def _answer_caveats(graph: Optional[Dict[str, Any]], full: bool = False) -> Dict[str, Any]:
    """The caveat keys an answer computed from `graph` has to carry, or `{}`.

    Absent — not empty — when there is nothing to say. That is the ADR-019 discipline enforced in
    one place rather than at each of the four surfaces: a monoglot repository's answers stay
    byte-identical to what they were before this existed, so nobody pays tokens for a field
    that would always read the same.
    """
    caveats = {}  # type: Dict[str, Any]
    digest = substrate.unmapped_digest(_census_block(graph), full=full)
    if digest:
        caveats['unmapped_source'] = digest
    crossed = _outside_block(graph)
    if crossed:
        # An answer computed over a graph with edges leaving the repository is not the same
        # sentence as one that is entirely in-tree, and it goes in the payload for the reason
        # ADR-029 puts the census there: the consumer is another skill reading `--format
        # json`, and stderr is dead skill-to-skill.
        #
        # Carried verbatim rather than digested, which is where this differs from
        # `unmapped_source`. That block has a prose `advice` sentence and a `readable_by`
        # recommendation worth trimming out of a per-file answer; this one is a handful of
        # aliases and counts, and a digest of it would be the same object with a different
        # name. It is repository-level on a per-file surface, deliberately — the fact being
        # qualified is the graph the answer was computed from, not the file asked about.
        caveats['outside_roots'] = crossed
    return caveats


#: Escaping links named individually in the artifact. A cap for the same reason
#: `_MAX_RECORDED_VALIDATION_ERRORS` has one — the count is the fact, the sample is the lead —
#: and pinned to that constant by a test rather than by this comment, because a parity claim
#: nothing checks is how the two drift.
_MAX_RECORDED_ESCAPING_LINKS = 20


def _escaping_links_report(backend: Any) -> Optional[Dict[str, Any]]:
    """Discovery candidates whose realpath left the project, or None when none did.

    None — the key absent rather than an empty block — so a repository with no symlinks
    produces byte-identical output to one built before this existed (ADR-029).

    Two buckets, because they are two different events and collapsing them would hide the
    one that matters. `refused` is a symlink that pointed out of the project with nothing
    declaring the target: it was not opened, not parsed, and is not a node. `crossed` is one
    whose target sits under a declared `outside` root (ADR-031): also not a node, but
    legitimate, and named with the same `outside:<alias>/<tail>` token an import into that
    root produces — so the two routes into a declared root read identically in the artifact,
    which is the point.

    Read as a completeness caveat and not as a security verdict. A `refused` entry means the
    graph is *smaller* than the file listing suggests, which is what a reader needs in order
    to know the blast radius is short. It does not mean anything hostile happened: a symlink
    out of the project is a perfectly ordinary thing for a monorepo checkout to contain.
    """
    escaping = getattr(backend, '_escaping_links', None)
    if not escaping:
        return None
    refused = sorted(rel for rel, crossing in escaping.items() if crossing is None)
    crossed = sorted(rel for rel, crossing in escaping.items() if crossing is not None)
    return {
        'refused': len(refused),
        'crossed': len(crossed),
        'sample': {
            'refused': refused[:_MAX_RECORDED_ESCAPING_LINKS],
            'crossed': {rel: escaping[rel] for rel in crossed[:_MAX_RECORDED_ESCAPING_LINKS]},
        },
        'advice': ('a symlink under this project resolves outside it; declare its target under '
                   '`outside` in knowledge-base/settings.json to have the crossing named, or '
                   'leave it refused'),
    }


def _escaping_links_sentence(block: Dict[str, Any]) -> str:
    """One line for the stderr surface, naming both counts.

    Both, always, even when one is zero: the reader's question is "is anything missing from
    this graph", and `refused: 0, crossed: 3` answers it as usefully as the other way round.
    """
    return ('%d symlink(s) resolve outside the project — %d refused, %d declared as crossings'
            % (block['refused'] + block['crossed'], block['refused'], block['crossed']))


def _outside_report(project_dir: Any, graph: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """What this build declared outside the project root and how far it got, or None.

    None — the key absent, not empty — when the project has no `outside` section, so a
    repository that has never used this produces byte-identical output (ADR-029).

    A declared root that nothing imported is reported with `crossings: 0` rather than dropped.
    A declaration that resolves nothing is usually a typo or a leftover, and configuration with
    no effect and no message is the defect this file has already paid for twice — in
    `classifications.json`, and in the dead directory keys `normalise_dir_key` was written to
    fold. A *refused* declaration is carried for the same reason: its warning goes to stderr,
    and stderr is dead skill-to-skill.

    "Usually", with the exception stated rather than left for the reader to hit: where two
    declared roots nest, `OutsideRoots.key_for` names a file under the *inner* one, so the
    outer root reads `crossings: 0` while covering everything the inner one does not. A zero
    therefore means "no edge was reported under this alias", which is a typo or a leftover
    unless another declared root contains this one. Advice that says "delete it" without that
    clause tells somebody to delete a working declaration.

    A count here is a fact about the edges in this artifact, and it is only in step with the
    settings file because `CodeGraph.update` forces a full rebuild when the declarations
    change. Without that it was recomputed from fresh settings over stale edges and was
    positively false in both directions.

    Counted off the edges rather than through a counter threaded down the resolver. The number
    is then derivable by anyone holding the artifact and cannot drift from what is in it, which
    is the property a count plumbed through the resolver would not have.
    """
    block = settings.load(str(project_dir)).outside.to_dict()
    if not block:
        return None
    counts = {}  # type: Dict[str, int]
    files = graph.get('files') if isinstance(graph, dict) else None
    for info in (files or {}).values():
        if not isinstance(info, dict):
            continue
        for edge in info.get('imports') or []:
            target = substrate.edge_other(edge)
            if not isinstance(target, str) or not target.startswith(substrate.OUTSIDE_PREFIX):
                continue
            alias = target[len(substrate.OUTSIDE_PREFIX):].split('/', 1)[0]
            counts[alias] = counts.get(alias, 0) + 1
    for entry in block.get('declared') or []:
        entry['crossings'] = counts.get(entry['alias'], 0)
    block['crossings'] = sum(counts.values())
    return block


def _outside_sentence(block: Dict[str, Any]) -> str:
    """One line naming each declared root and how many edges reached it, or ''.

    Empty when every declaration was refused: each refusal already produced its own warning
    through `Settings.warnings`, and saying it twice in one run trains a reader to skim both.

    **Two sentences, because there are two facts and only one of them was being told.** The
    claim "this graph leaves the project root" is about the *edges*, and it was gated on a
    declaration merely being in force — so the commonest state of a new declaration, one
    nobody has imported through yet, printed a sentence that was simply false, on `--build`
    and again on every `--dependents`. Worse on graphify, which never consults declarations at
    all: there the zero is not even a measurement, and the sentence asserted a crossing on a
    backend that never looked. So a total of zero says the roots were *not reached*, which is
    the true statement and also the one that reads as an invitation to check the declaration.

    Tolerant of a `declared` list that is not a list of dicts, via `_declared_entries`: this
    runs on `--dependents` and `--dependencies` over a persisted artifact, and ADR-031 requires
    those two to break closed rather than raise.
    """
    declared = _declared_entries(block)
    if not declared:
        return ''
    total = _outside_total(block)
    where = 'Declared in %s/%s; nothing outside the root is read, only resolved (ADR-031).' % (
        settings.SETTINGS_DIRNAME, settings.SETTINGS_FILENAME)
    if not total:
        return ('this graph does not leave the project root: nothing crossed to %s. %s'
                % ('; '.join('%r (%s)' % (entry.get('alias'), entry.get('path'))
                             for entry in declared),
                   where))
    return ('this graph leaves the project root: %s. %s'
            % ('; '.join('%d edge(s) into %r (%s)'
                         % (entry.get('crossings', 0), entry.get('alias'), entry.get('path'))
                         for entry in declared),
               where))


def _outside_block(graph: Optional[Dict[str, Any]]) -> Any:
    """The `outside_roots` block, tolerating any artifact shape.

    `isinstance` throughout, and for the reason `_census_block` records: a truthy non-dict
    `substrate` reached `.get` and raised, on a read path added without the guard the write
    path already had.
    """
    if not isinstance(graph, dict):
        return None
    block = graph.get('substrate')
    if not isinstance(block, dict):
        return None
    crossed = block.get('outside_roots')
    return crossed if isinstance(crossed, dict) else None


def _declared_entries(block: Any) -> List[Dict[str, Any]]:
    """The usable `declared` rows of an `outside_roots` block, in order, or `[]`.

    One tolerance rule for both readers of that list. `_outside_block` guards the outer dict
    and stopped there, so a persisted `{"declared": ["ui"]}` — or `"ui"`, which is truthy and
    iterates into characters — reached `.get` one level down and raised `AttributeError`, on
    `--dependents` and `--dependencies`, which ADR-031 requires to break *closed*. That is the
    same defect `_census_block`'s docstring records, one level deeper in the same block.
    """
    declared = block.get('declared') if isinstance(block, dict) else None
    if not isinstance(declared, list):
        return []
    return [entry for entry in declared if isinstance(entry, dict)]


def _declared_roots(block: Any) -> Tuple[Tuple[Any, Any], ...]:
    """The `(alias, path)` pairs a block says are in force — the declaration's identity.

    Deliberately not the `crossings` counts, which are a fact about the graph rather than about
    the declaration, and deliberately not the resolved paths, which `to_dict` does not carry
    into an artifact. One body, called on both sides of the `--update` comparison: the block
    persisted in the cached graph, and `OutsideRoots.to_dict()` for the settings file as it
    reads now. `OutsideRoots` sorts its roots, so the order is a function of the declarations
    and not of how the file spelled them, and this can compare tuples rather than sets.
    """
    return tuple((entry.get('alias'), entry.get('path')) for entry in _declared_entries(block))


def _outside_total(block: Any) -> int:
    """How many edges crossed, summed off the per-alias counts rather than off `crossings`.

    Derived from the rows the sentence is about to print, so the two can never disagree — the
    same argument `_outside_report` makes for counting off the edges instead of threading a
    counter down the resolver. A row whose count is missing or not an integer contributes
    nothing rather than raising: this runs over a persisted artifact on a surface that must
    break closed.
    """
    return sum(n for n in (entry.get('crossings') for entry in _declared_entries(block))
               if isinstance(n, int))


def _census_block(graph: Optional[Dict[str, Any]]) -> Any:
    """The `unmapped_source` block, tolerating any artifact shape.

    `isinstance`, not `or {}`: the latter rescues only a *falsy* substrate, so a truthy non-dict
    — a string, a list, a number — reached `.get` and raised. `_finalise` guards the write path
    against exactly that shape, twice, with a comment saying indexing it "would turn a
    diagnostic into a crash"; these read paths were added without the same guard, and every
    query surface now goes through one of them. Every other reader of this key in the codebase
    already uses isinstance.
    """
    if not isinstance(graph, dict):
        return None
    block = graph.get('substrate')
    return block.get('unmapped_source') if isinstance(block, dict) else None


def _announce_unmapped(graph: Optional[Dict[str, Any]]) -> None:
    """The caveat for the two surfaces that answer with a bare array.

    `--dependents` and `--dependencies` return a JSON list, which has nowhere to carry a
    qualification about itself. Changing them to objects was considered and rejected:
    `run_behaviors._code_graph_deps` validates `--dependencies` with `isinstance(data, list)`
    and falls to `graph-query-failed` otherwise, which routes every confirmed and every
    integration behaviour to `coverage: unknown` — freezing the committed `behavior.json` and
    taking wrap-up's gate green over zero behaviours. Breaking closed here is a repo-wide
    silent pass, not a loud failure.

    So the caveat goes to stderr, which is dead exactly where it must be dead and alive exactly
    where it must be alive: all three programmatic callers capture stderr and read only stdout
    on success, while `bin/freya_cli.py` inherits the streams, so an agent running the command
    from a shell sees it in the tool result. Do not "fix" this by moving it into the payload.
    """
    block = _census_block(graph)
    if not isinstance(block, dict) or not block.get('files'):
        return
    where = ', '.join(sorted(block.get('directories') or {})) or 'the paths above'
    if block.get('directories_omitted'):
        where += ' and %d more director%s' % (
            block['directories_omitted'], 'y' if block['directories_omitted'] == 1 else 'ies')
    _announce_once(
        'code-graph: this answer excludes %d source file(s) %r does not read (%s) under %s.\n'
        '  --dependents/--dependencies answer over the mapped subset only; grep those paths '
        'directly before concluding a change is contained.'
        % (block['files'], block.get('backend'),
           ', '.join(sorted(block.get('extensions') or {})), where))


def _announce_outside(graph: Optional[Dict[str, Any]]) -> None:
    """The crossing caveat for the two surfaces that answer with a bare array.

    Same channel and same reasoning as `_announce_unmapped`, which says why the shape of
    `--dependents`/`--dependencies` must not change instead: `run_behaviors` validates the
    answer with `isinstance(data, list)`, and an envelope there breaks *closed* across the
    whole repository.

    Worth saying on those two surfaces in particular. They answer in project-relative keys, and
    an `outside:` target is filtered out of both by `substrate.internal_ends` — correctly,
    since it names no node to walk to. So the one place a crossing is structurally invisible is
    exactly where a reader is most likely to conclude a change is contained.
    """
    block = _outside_block(graph)
    if not isinstance(block, dict):
        return
    sentence = _outside_sentence(block)
    if not sentence:
        return
    if not _outside_total(block):
        # Nothing crossed, so the second line has nothing to qualify. Printed unconditionally
        # it read as a warning about this answer — "a file under a declared root is resolved
        # to" — for an answer in which no file was.
        _announce_once('code-graph: %s' % sentence)
        return
    _announce_once('code-graph: %s\n'
                   '  --dependents/--dependencies answer over this project\'s own files '
                   'only; a file under a declared root is resolved to, never graphed.'
                   % sentence)


def _edge_annotation(edge: Any) -> str:
    """The `[kind]` / `[kind: from → to]` tail on one printed edge.

    The symbols were dropped here, which meant that with `substrate.symbols` enabled a file
    pair joined by sixty distinct symbol edges printed sixty byte-identical lines — the very
    symptom the reverse index was fixed to stop producing in the artifact, reintroduced one
    layer up in the only place a person actually reads.
    """
    kind = substrate.edge_kind(edge)
    from_symbol, to_symbol = substrate.edge_symbols(edge)
    detail = ' → '.join(s for s in (from_symbol, to_symbol) if s)
    if not detail:
        return '' if kind == _IMPORTS else '  [%s]' % kind
    line = edge.get('line') if isinstance(edge, dict) else None
    return '  [%s: %s%s]' % (kind, detail, ':%d' % line if isinstance(line, int) else '')


def _unmapped_line(data: Any, indent: str = '  - ') -> str:
    """The `NOT GRAPHED:` line for `--format summary`, or `''` when there is nothing to say.

    Empty string rather than a placeholder, so the human-readable output of a repository the
    backend reads completely is byte-identical to what it was before the census existed.
    """
    block = data.get('unmapped_source') if isinstance(data, dict) else None
    if not isinstance(block, dict):
        return ''
    if block.get('files') is None and block.get('error'):
        return '%sNOT GRAPHED: the coverage census could not run (%s)' % (indent, block['error'])
    if not block.get('files'):
        return ''
    exts = sorted(block.get('extensions') or {})
    where = sorted(block.get('directories') or {})
    tail = ' under %s' % ', '.join(where[:2]) if where else ''
    return ('%sNOT GRAPHED: %d source file(s) this backend cannot read (%s)%s'
            % (indent, block['files'], ', '.join(exts[:3]), tail))


def _outside_line(data: Any, indent: str = '  - ') -> str:
    """The crossing line for `--format summary`, or `''` when there is nothing to say.

    `_unmapped_line`'s counterpart, at the same five call sites — `--build`, both shapes of
    `--update`, `--query` and `--impact` — and for the same reason. ADR-029
    splits the caveat by audience — the payload for a skill, stderr for a person — and this
    surface fell through the split: `--query --format summary` printed an `outside:` target with
    no qualification at all, and `--impact --format summary` printed a blast radius with
    nothing on either stream, while both carried the block in `--format json`. That inverts the
    ADR: the machine was told and the person was not.

    All four sites, including the two whose stderr already carries the sentence, and that
    repetition is deliberate. `_announce_once` dedupes for the life of the process, so in any
    caller that has already said this — `run_update` falling back to a full build says it once
    for the build and would then be silent for the update — the stderr line is not there to be
    read. This one always is.

    The wording is `_outside_sentence`'s and not a second one, so a reader who does see both in
    a run reads the same claim twice rather than wondering whether they differ.
    """
    block = data.get('outside_roots') if isinstance(data, dict) else None
    sentence = _outside_sentence(block) if isinstance(block, dict) else ''
    return '%s%s' % (indent, sentence[:1].upper() + sentence[1:]) if sentence else ''


def format_summary(data: Any, operation: str) -> str:
    """Format output as human-readable summary."""
    if operation == 'build':
        lines = [f"""Built dependency graph:
  - {data['files_scanned']} files scanned
  - {data['total_imports']} import relationships
  - {data['total_exports']} export declarations"""]
        lines.extend(x for x in (_unmapped_line(data), _outside_line(data)) if x)
        lines.append(f"  - Cached to {data['cached_to']}")
        return '\n'.join(lines)

    elif operation == 'update':
        if data.get('status') == 'up_to_date':
            return '\n'.join(x for x in ["Graph is up to date. No changes detected.",
                                         _unmapped_line(data), _outside_line(data)] if x)
        if data.get('status') == substrate.Result.BUILT:
            # `--update` falls back to a full build when there is no usable cache.
            return format_summary(data, 'build')
        return '\n'.join(x for x in [f"""Updated dependency graph:
  - {data['files_changed']} files changed since last build
  - Graph updated at commit {data.get('commit', 'unknown')}""",
                                     _unmapped_line(data), _outside_line(data)] if x)

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
            for edge in data['imports']:
                target = substrate.edge_other(edge)
                # No arrow for a package, and none for a file under a declared root either:
                # the arrow says "this points at something in the graph", and a crossing
                # resolves to a real file that is deliberately not a node (ADR-031). A fourth
                # ad-hoc tuple of prefixes is what `substrate.IMPORT_SIGNALS` exists to stop,
                # but `is_internal` is the wrong test here — `unresolved:` is a signal and has
                # always printed with the arrow, and changing that is not this change's to make.
                arrow = "" if target.startswith(
                    ('external:', substrate.OUTSIDE_PREFIX)) else " →"
                lines.append(f"  -{arrow} {target}{_edge_annotation(edge)}")
            lines.append("")

        if data.get('dependents'):
            lines.append("Dependents (imported by):")
            for edge in data['dependents']:
                lines.append(f"  - {substrate.edge_other(edge)}{_edge_annotation(edge)}")
            lines.append("")

        if data.get('language'):
            lines.append(f"Language: {data['language']}")
        for caveat in (_unmapped_line(data, indent=''), _outside_line(data, indent='')):
            if caveat:
                lines.extend(["", caveat])
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
        if data.get('not_in_graph'):
            # A file the backend never indexed contributes nothing, and a bare zero reads
            # as "nothing depends on this" rather than "I have not seen this".
            lines.append("")
            lines.append(f"Not in the graph ({len(data['not_in_graph'])} files) — "
                         f"no blast radius could be computed for these:")
            for path in sorted(data['not_in_graph']):
                lines.append(f"  - {path}")
        for caveat in (_unmapped_line(data, indent=''), _outside_line(data, indent='')):
            if caveat:
                lines.extend(["", caveat])
        return '\n'.join(lines)

    elif operation == 'dependents':
        if not data:
            # `main()` exits before reaching here when the query could not be answered — a
            # missing graph or an unknown file returns None and takes the `sys.exit(1)` path.
            # So an empty collection at this point is a real answer, and saying "no cached
            # graph found" for it was the same empty-vs-unknown conflation the API layer was
            # fixed to remove, still live one layer up in the only place a person reads.
            return "Nothing depends on this file."

        lines = ["Dependents:"]
        for dep in sorted(data):
            lines.append(f"  - {dep}")
        return '\n'.join(lines)

    elif operation == 'dependencies':
        if not data:
            return "This file imports nothing in the project."

        lines = ["Dependencies:"]
        for dep in sorted(data):
            lines.append(f"  - {dep}")
        return '\n'.join(lines)

    elif operation == 'clear':
        return "Cleared dependency graph cache for this project."

    return str(data)


def _seed_from_machine_default(project_dir: str) -> None:
    """Write the machine-level backend into a project that has not answered for itself.

    Only ever carries an answer somebody actually gave — `seed_project_backend` returns None
    when there is no machine default, or when the project has already decided. A headless run
    with nothing configured writes nothing at all: recording the floor as though it were a
    choice is how a default becomes a decision nobody made.

    Never fatal. A read-only checkout is a perfectly good place to build a graph, and failing
    to persist a preference is not a reason to refuse.
    """
    known = set(known_backend_names())
    try:
        # The registry check is passed in, because `backends` imports `settings` and the
        # reverse would be a cycle. Without it a typo in a hand-edited machine file gets
        # copied into a project's *committed* settings, where it stops being one person's
        # mistake and becomes the repository's.
        path = settings.seed_project_backend(
            project_dir, is_known=(lambda n: n in known) if known else None)
    except (OSError, ValueError) as exc:
        _announce_once('code-graph: could not record the machine default in this project '
                       '(%s); using it for this run only' % exc.__class__.__name__)
        return
    if path:
        _announce_once(
            'code-graph: recorded your machine default in %s. Commit it so a clone and CI '
            'resolve the same backend — a project that leaves this implicit graphs '
            'differently on different machines.' % path)


def known_backend_names() -> List[str]:
    """Every name `--use` will accept, plus `auto`. Empty on an unimportable registry."""
    try:
        import backends
        return sorted(backends._registry()) + [settings.BACKEND_AUTO]
    except Exception:
        return []


def record_backend(name: str, project_dir: str, global_scope: bool) -> int:
    """`--use`: write the backend choice down, for this project or for the machine.

    Validated against the registry here rather than at read time, because this is the moment
    somebody is present to be told they typed it wrong. A name that reaches `settings.json`
    unchecked resolves to nothing, degrades to the floor, and the project spends a week
    believing it opted into something.
    """
    known = known_backend_names()
    if known and name not in known:
        print('code-graph: %r is not a backend. Known: %s'
              % (name, ', '.join(known)), file=sys.stderr)
        return 2

    if not global_scope and not os.path.isdir(project_dir):
        # A typo'd `--dir` used to be created from scratch, written to, and reported as
        # success — leaving the project the engineer meant still unconfigured, and a stray
        # `knowledge-base/` somewhere they never looked.
        print('code-graph: %s is not a directory. Pass --dir <project>, or --global to set '
              'the machine default.' % project_dir, file=sys.stderr)
        return 2

    scope = settings.SOURCE_GLOBAL if global_scope else settings.SOURCE_PROJECT
    try:
        path = settings.set_backend(name, project_dir=project_dir, scope=scope)
    except (OSError, ValueError) as exc:
        print('code-graph: could not record the backend (%s)' % exc, file=sys.stderr)
        return 1

    if global_scope and name == settings.BACKEND_AUTO:
        print('Machine default cleared (%s).\nProjects that have not decided for themselves '
              'will use the built-in backend, and freya will ask again next time it is '
              'installed or updated.' % path)
    elif global_scope:
        # Careful about what this promises. A project that has already been built has the
        # previous answer *recorded in its own settings.json*, and the project file wins —
        # so this changes what happens in projects that have not decided yet, not everywhere.
        print('Machine default is now %r (%s).\n'
              'Projects that have not decided for themselves will use it, and the first '
              'build in each records it there.\n'
              'A project already carrying a different answer keeps it — change that one with '
              '`freya code-graph --use %s` inside it.' % (name, path, name))
    else:
        print('This project now uses %r (%s).\nCommit that file so a clone, a colleague and '
              'CI all resolve the same backend.' % (name, path))

    # Said after the write, not instead of it: setting a backend before installing it is a
    # legitimate thing to do — a repository can declare what it wants and a machine can catch
    # up later, degrading to the floor and saying so in the meantime.
    if name != settings.BACKEND_AUTO:
        try:
            import backends
            if name not in {b.name for b in backends.available_backends(project_dir)}:
                print("\nNote: %r is not available on this machine yet, so builds here will "
                      "fall back to the floor and record that they did." % name,
                      file=sys.stderr)
        except Exception:
            pass
    return 0


def choose_backend(floor: Any, project_exclusions: Any) -> Tuple[Any, Optional[Dict[str, Any]]]:
    """Pick the backend to build with, and the degradation metadata to record.

    Returns `(backend, selection_metadata)`. Announced on stderr rather than stdout so it
    never contaminates `--format json`, and announced at all because spec §2.2 requires the
    choice to be visible: a caller must be able to tell a thin graph from a thin repo.

    Lifted out of `main()` so it can be tested. It could not be before — it was inline in an
    argparse entry point — and the one branch nobody exercised was the one that silently
    dropped the metadata.
    """
    try:
        import backends
        # The census only matters when there is something to choose between. With a
        # single installed backend it cannot change the answer, so walking the tree
        # before every build and every update would be pure cost.
        census = None
        if len(backends.available_backends(str(floor.project_dir))) > 1:
            census = backends.extension_census(str(floor.project_dir), project_exclusions)
        selection = backends.select(str(floor.project_dir), present_extensions=census)
        for warning in selection.warnings:
            _announce_once(warning if warning.startswith('code-graph:')
                           else 'code-graph: %s' % warning)

        errors = substrate.conformance_errors(selection.backend)
        if errors:
            # Announced before it is used, not after: a backend that fails the contract
            # must not be named as the one that ran.
            print('code-graph: %r does not satisfy the substrate contract (%s); '
                  'using %r' % (getattr(selection.backend, 'name', '?'),
                                '; '.join(errors), CodeGraph.name), file=sys.stderr)
            # And recorded, not merely printed. This is a degradation like any other: the
            # project asked for a backend and did not get it. Leaving the metadata unset
            # wrote a graph indistinguishable from an ordinary floor build, so a week later
            # nothing said the configured backend never ran — the one thing `degraded_from`
            # exists to preserve. Selection's own degradation is folded in here too, because
            # this branch used to skip the block that recorded it.
            return floor, {
                'degraded_from': (selection.degraded_from
                                  or getattr(selection.backend, 'name', '?')),
                'degraded_reason': 'does not satisfy the substrate contract: %s'
                                   % '; '.join(errors),
            }

        if selection.degraded or selection.backend.name != CodeGraph.name:
            print(selection.describe(), file=sys.stderr)
        metadata = None
        if selection.degraded:
            metadata = {'degraded_from': selection.degraded_from,
                        'degraded_reason': selection.reason}
        chosen = selection.backend if hasattr(selection.backend, 'build') else floor
        return chosen, metadata
    except Exception as exc:
        # Selection is an optimisation over "run the floor". It must never be the reason a
        # build fails, because the floor is what the build would have used anyway.
        print('code-graph: backend selection failed (%s); using %r'
              % (exc.__class__.__name__, CodeGraph.name), file=sys.stderr)
        return floor, None


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
    group.add_argument('--use', metavar='BACKEND',
                       help='Record which substrate backend this project uses '
                            "(or 'auto' to follow the machine default)")

    parser.add_argument('--global', dest='global_scope', action='store_true',
                        help='With --use: set the machine-level default for every project '
                             'that has not decided for itself')
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

    if args.use is not None:
        # `is not None`, not truthiness: `--use ""` is a mistake, and testing truthiness sent
        # it past every dispatch branch to the terminal `sys.exit(1)` — exit 1 with nothing on
        # stdout or stderr, which is the least useful way to be told anything.
        return record_backend(args.use, str(graph.project_dir), args.global_scope)

    selection_metadata = None
    # Derived from the project by the floor, before any backend substitution. Exclusions are
    # a project fact (obligation 6), so reading them must not require a method only the
    # incumbent has — and calling `selection.backend.project_exclusions()` did exactly that,
    # crashing the CLI on this repo's own reference backend.
    project_exclusions = graph.project_exclusions()
    if args.build or args.update:
        _seed_from_machine_default(str(graph.project_dir))
        graph, selection_metadata = choose_backend(graph, project_exclusions)
    output = None
    operation = None

    if args.build or args.update:
        # Obligation 6: exclusions are passed in, not left for the backend to decide.
        # Every other caller relied on the backend deriving them, which meant the only
        # production path never exercised the obligation it documents.
        runner = run_build if args.build else run_update
        operation = 'build' if args.build else 'update'
        try:
            output = _run_or_degrade(runner, graph, CodeGraph(args.dir), non_interactive,
                                     project_exclusions, selection_metadata)
        except EmptiedTheGraph as exc:
            # A refusal, not a crash. `_run_or_degrade` re-raises this when the running
            # backend is already the floor, and nothing caught it — so an entirely ordinary
            # action (committing `{"directories": {"src": "exclude"}}`, or deleting the last
            # source file) ended every subsequent build in a Python traceback and exit 1,
            # with the carefully composed message buried in it. The refusal is right; the
            # presentation was not.
            print('code-graph: %s\n'
                  '  The previous graph is kept. If the codebase really is empty now, or '
                  'the exclusions are intentional, run --clear first.' % exc,
                  file=sys.stderr)
            sys.exit(1)

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
    # `sys.exit(main())`, not `main()`: the return value is the exit code. Every other
    # failure path here reaches `sys.exit` directly, so discarding it went unnoticed until
    # a path wanted to *return* one — `--use` with a name that is not a backend printed the
    # error and exited 0, which is a shell script's definition of success.
    sys.exit(main())
