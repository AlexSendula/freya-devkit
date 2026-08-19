#!/usr/bin/env python3
"""Which substrate backend runs for this project, and why.

`substrate.py` is the contract and knows nothing about implementations. This module is the
other half: the registry that knows what is installed and picks one, following the project's
`knowledge-base/settings.json` (CD-15).

Selection is **never silent** (spec §2.2). Every decision here produces a `Selection` carrying
the backend, whether this was a fallback, and a human-readable reason, and the caller writes
all of it into the graph metadata. A graph that came from a degraded backend must say so on its
face — otherwise a thin graph is indistinguishable from a thin repo, which is the failure this
whole initiative exists to remove.
"""

import os
import sys
from typing import Any, Callable, Dict, List, Optional

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import settings as settings_mod  # noqa: E402
import substrate  # noqa: E402

# The backend used when nothing else is available. It is stdlib-only and therefore always
# installable, which is the whole reason it stays (CD-2): the driving case for the polyglot
# work is a locked-down machine, and that is exactly where a dependency cannot be added.
FLOOR = 'homegrown'


class Selection:
    """The chosen backend, plus why it was chosen."""

    __slots__ = ('backend', 'requested', 'degraded_from', 'reason', 'warnings')

    def __init__(self, backend: Any, requested: str, degraded_from: Optional[str] = None,
                 reason: str = '', warnings: Optional[List[str]] = None):
        self.backend = backend
        self.requested = requested
        self.degraded_from = degraded_from
        self.reason = reason
        self.warnings = warnings or []

    @property
    def degraded(self) -> bool:
        return self.degraded_from is not None

    def metadata(self, exclusions: Optional[substrate.Exclusions] = None) -> Dict[str, Any]:
        return substrate.graph_metadata(
            self.backend.name, self.backend.coverage(), exclusions,
            degraded_from=self.degraded_from, degraded_reason=self.reason or None)

    def describe(self) -> str:
        """One line for stderr. The user should never have to infer which backend ran."""
        if self.degraded:
            return ('code-graph: %r unavailable (%s) — using %r instead, with reduced coverage'
                    % (self.degraded_from, self.reason, self.backend.name))
        return 'code-graph: using the %r backend' % self.backend.name

    def __repr__(self) -> str:
        return 'Selection(backend=%r, degraded_from=%r)' % (
            getattr(self.backend, 'name', None), self.degraded_from)


def _registry() -> Dict[str, Callable[[str], Any]]:
    """name -> factory. Imported lazily so a broken optional backend cannot break a build."""
    def homegrown(project_dir):
        import graph_ops
        return graph_ops.CodeGraph(project_dir)

    return {FLOOR: homegrown}


def available_backends(project_dir: str,
                       registry: Optional[Dict[str, Callable[[str], Any]]] = None) -> List[Any]:
    """Every registered backend that reports itself usable here."""
    usable = []
    for name, factory in sorted((registry or _registry()).items()):
        try:
            backend = factory(project_dir)
        except Exception:
            # A backend that cannot even be constructed is simply not available. It must not
            # take the build down with it — that is what having a floor is for.
            continue
        try:
            if backend.available():
                usable.append(backend)
        except Exception:
            continue
    return usable


def _score(backend: Any, present_extensions: Dict[str, int]) -> int:
    """How many files on disk this backend could read.

    `auto` means "see the most of this repo", not "prefer whoever registered first". Counting
    files rather than languages is what makes a repo that is 90% Java pick the backend that
    reads Java, instead of one that technically supports more languages in the abstract.
    """
    try:
        coverage = backend.coverage()
    except Exception:
        return -1
    return sum(count for ext, count in present_extensions.items()
               if ext in coverage.extensions)


def select(project_dir: str,
           present_extensions: Optional[Dict[str, int]] = None,
           registry: Optional[Dict[str, Callable[[str], Any]]] = None) -> Selection:
    """Choose a backend for `project_dir`.

    `auto` picks whichever available backend can read the most of the repo, with the floor
    breaking ties so behaviour stays predictable. A named backend is used if available and
    otherwise degrades to the floor — the run continues, but says what it lost.
    """
    conf = settings_mod.load(project_dir)
    requested = conf.backend
    usable = available_backends(project_dir, registry)
    warnings = list(conf.warnings)

    if not usable:
        raise RuntimeError(
            'no code-graph backend is available, not even %r — this should be impossible, '
            'since it is stdlib-only. Check the installation.' % FLOOR)

    by_name = {b.name: b for b in usable}

    if requested != settings_mod.BACKEND_AUTO:
        chosen = by_name.get(requested)
        if chosen is not None:
            return Selection(chosen, requested, warnings=warnings)
        floor = by_name.get(FLOOR) or usable[0]
        return Selection(
            floor, requested, degraded_from=requested,
            reason='not installed' if requested not in _registry() else 'unavailable here',
            warnings=warnings)

    if present_extensions:
        best = max(usable, key=lambda b: (_score(b, present_extensions), b.name == FLOOR))
    else:
        best = by_name.get(FLOOR) or usable[0]
    return Selection(best, requested, warnings=warnings)


def extension_census(project_dir: str, exclusions: Optional[substrate.Exclusions] = None,
                     limit: int = 20000) -> Dict[str, int]:
    """Count files by extension, so `auto` can score backends against the real repo.

    Walks rather than globs so the obvious dependency trees can be pruned as it goes; on a big
    monorepo, descending into `node_modules` to decide which parser to use would cost more than
    the parse. `limit` stops a pathological tree turning selection into the slow step.
    """
    skip = {'node_modules', '.git', 'dist', 'build', '.next', '__pycache__', 'venv', '.venv',
            'vendor', 'target', 'coverage'}
    census = {}  # type: Dict[str, int]
    seen = 0
    for root, dirs, filenames in os.walk(project_dir):
        dirs[:] = [d for d in dirs if d not in skip and not d.startswith('.')]
        for filename in filenames:
            ext = os.path.splitext(filename)[1].lower()
            if not ext:
                continue
            rel = os.path.relpath(os.path.join(root, filename), project_dir)
            rel = rel.replace(os.sep, '/')
            if exclusions is not None and exclusions.excludes(rel):
                continue
            census[ext] = census.get(ext, 0) + 1
            seen += 1
            if seen >= limit:
                return census
    return census
