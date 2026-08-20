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
        # The already-loaded module, when there is one. `graph_ops.py` is executed as a
        # script by the CLI, so it lives in `sys.modules` under `__main__`; importing it
        # by name here built a *second* module object with its own module-level state.
        # The visible symptom was every settings warning printed twice, from a helper
        # whose whole contract is "said once per process" — but two copies of a module
        # that owns caches and constants is a class of bug, not one bug.
        module = sys.modules.get('graph_ops')
        if module is None:
            main = sys.modules.get('__main__')
            module = main if hasattr(main, 'CodeGraph') else None
        if module is None:
            import graph_ops as module  # noqa: F811
        return module.CodeGraph(project_dir)

    def graphify(project_dir):
        import backend_graphify
        return backend_graphify.GraphifyBackend(project_dir)

    return {FLOOR: homegrown, 'graphify': graphify}


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


# `_score` lived here until 2026-08-20. It ranked backends by how many of a repository's
# files each could read, and `auto` picked the winner — behaviour CD-23 removed, because it
# meant installing a binary silently changed the substrate for every project on the machine.
# Deleted rather than left unused: its docstring explained at length why `auto` should "see
# the most of this repo", which is now the opposite of what happens forty lines below.


def select(project_dir: str,
           present_extensions: Optional[Dict[str, int]] = None,
           registry: Optional[Dict[str, Callable[[str], Any]]] = None) -> Selection:
    """Choose a backend for `project_dir`.

    `auto` is the floor. A named backend is used if available, and otherwise degrades to the
    floor — the run continues, but says what it lost. Naming one *is* the opt-in; there is no
    separate permission list, because a project that has written the name down has decided.
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

    # `auto` resolves to the floor, and deliberately does not go shopping.
    #
    # It used to pick whichever installed backend scored highest against the repo, which reads
    # like the helpful thing and is not. Spec §11 mitigates "the dependency breaks zero-install"
    # with *graphify is opt-in*, and CD-13 requires a substrate change to be a measured
    # migration — diffed before it is trusted. Scoring silently would have done the opposite:
    # installing a tool, anywhere on PATH, would have swapped the substrate under every project
    # on the machine at once, changing every blast radius with no diff and no decision.
    #
    # Measured on this repository, that was not hypothetical — graphify scored 63 to
    # homegrown's 58 and would have taken over on the next build.
    #
    # What `auto` does instead is *say* what it is leaving on the table, which is the part a
    # project actually cannot discover for itself.
    floor = by_name.get(FLOOR) or usable[0]
    if present_extensions:
        for other in sorted(usable, key=lambda b: b.name):
            if other.name == floor.name:
                continue
            unseen = _unseen_by_floor(floor, other, present_extensions)
            if unseen:
                warnings.append(
                    'code-graph: %r is installed and declares it reads %d file(s) here that '
                    '%r cannot (%s). It is opt-in: set substrate.backend to %r in '
                    'knowledge-base/settings.json to use it.'
                    % (other.name, sum(unseen.values()), floor.name,
                       ', '.join(sorted(unseen)), other.name))
    return Selection(floor, requested, warnings=warnings)


def _unseen_by_floor(floor: Any, other: Any,
                     present_extensions: Dict[str, int]) -> Dict[str, int]:
    """Extensions in this repo that `other` reads and `floor` does not, with counts.

    A backend may declare an extension whose selection is really *name*-based —
    `package.json` produces nodes, an arbitrary `x.json` does not. Declaring it is correct;
    using it as evidence for a migration is not, because nearly every repository has one and
    the hint would then fire everywhere on the strength of a file the backend may well ignore.
    A backend names those on `over_claimed`, and they are excluded from the evidence while
    staying in the declaration.
    """
    try:
        floor_ext = set(floor.coverage().extensions)
        other_ext = set(other.coverage().extensions)
    except Exception:
        return {}
    uncertain = set(getattr(other, 'over_claimed', ()) or ())
    return {ext: count for ext, count in present_extensions.items()
            if ext in other_ext and ext not in floor_ext and ext not in uncertain}


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
