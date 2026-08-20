#!/usr/bin/env python3
"""The substrate contract: what a code-graph backend must provide.

freya's dependency graph was one hand-written resolver. Track B makes it a *socket*, so a
project can run the stdlib-only resolver that ships with the toolkit, or a real multi-language
parser, and everything downstream — blast radius, docs impact, behavior fingerprints — keeps
working either way.

This module is the socket. It holds no parsing logic and imports nothing outside the standard
library, so a backend can depend on it without inheriting anything.

Six obligations, from `docs/polyglot/spec.md` §2.1:

  1. **Resolve** the languages it claims, given a project root.
  2. **Report what it could not resolve.** An unresolvable import is recorded as
     `unresolved:<raw>`, never dropped. A confidently-empty answer is the failure mode
     ADR-005 exists to prevent, and it is worse than an honest gap.
  3. **Carry per-edge provenance** — how the edge was obtained, and therefore how far to
     trust it.
  4. **Declare its coverage** — so a caller can tell "no dependencies" from "this backend
     cannot read Java".
  5. **Support incremental update, or decline it.** A backend that cannot correctly drop
     deleted nodes says so, and the contract rebuilds from scratch instead of trusting it.
  6. **Honour the project's exclusions**, which are passed in. `vendor/ is not mine` is true
     whichever parser runs, so it is a project fact, not a backend opinion.

Obligations 2, 4 and 5 each exist because of a specific past failure — dogfooding findings F7
and F9, and the staleness risk in spec §9.2. None of them is speculative.
"""

import json
import os
from typing import Any, Callable, Dict, Iterable, List, Optional, Sequence, Tuple

# ---------------------------------------------------------------------------
# Vocabulary
# ---------------------------------------------------------------------------

# The relation kinds a backend may declare and emit. Fixed deliberately: a contract whose
# vocabulary each backend defines for itself is describing implementations, not an interface,
# and a caller could not then ask "does this backend give me calls?" in a portable way.
#
# Defined here in Phase 1 rather than in Phase 3, where symbols land, because inventing a
# vocabulary during a migration is worse than agreeing one before it (CD-16).
RELATION_KINDS = (
    'imports',      # a file depends on another file, as stated in source
    're_exports',   # a file re-exports another file's surface (barrels)
    'calls',        # a symbol invokes another symbol
    'inherits',     # a type extends or implements another type
    'references',   # a symbol is named without being called
)

# How an edge was obtained. This is *not* the deterministic/model-judged axis — Phase 0
# measured graphify emitting INFERRED edges from a pure AST pass with no model involved
# (findings, "the two-tier trust design is unexercised"). It is about how directly the edge
# was read out of the source.
PROVENANCE = (
    'extracted',    # stated explicitly in the source text
    'inferred',     # derived by resolution the source did not spell out
)

# Prefixes that mark an import specifier as a signal rather than a resolved path. Kept in one
# place because three skills independently filter on them, and a fourth prefix added without
# updating all of them would be counted as an internal edge.
IMPORT_SIGNALS = ('external:', 'unresolved:')

# 1: edges were bare strings.
# 2: edges are objects carrying `kind` and `provenance` (2026-08-20).
#
# The bump is what makes the read-side tolerance *temporary* rather than permanent. Without
# a version there is no way to tell a graph that has been brought forward from one that
# never needed to be, so nothing can ever decide it is safe to stop accepting both.
GRAPH_SCHEMA_VERSION = 2

# Where a project's graph artifacts live, relative to its root. Here rather than on one
# backend because the contract — not the backend — is what persists them.
GRAPH_DIR = ('knowledge-base', '.graph')
ACTIVE_GRAPH = 'graph.json'


def is_internal(specifier: str) -> bool:
    """Is this import specifier a resolved project file, rather than a signal?"""
    return bool(specifier) and not specifier.startswith(IMPORT_SIGNALS)


# ---------------------------------------------------------------------------
# Edges
# ---------------------------------------------------------------------------
#
# An edge is an object, not a string. It was a string until 2026-08-20, and a string can
# carry exactly one fact — where the edge points. Phase 0 measured what that costs: of the
# 5,027 links graphify produces for the testbed, our shape could express 2,102. The missing
# 58% are not extra detail about the same edges, they are edges we cannot write down at all,
# because they are between *symbols* and they have a *kind*. `a.ts calls b.ts` and
# `a.ts imports b.ts` are the same string.
#
# The keys:
#   to / from     the other end. On `imports` it is the target, on `dependents` the source.
#                 Still a project-relative path, or an `external:` / `unresolved:` signal.
#   kind          one of RELATION_KINDS.
#   provenance    one of PROVENANCE — how directly it was read out of the source.
#
# Phase 3 adds `from_symbol`, `to_symbol` and `line` on top. They are deliberately not
# reserved here: the point of an object is that a field can arrive without a migration.
#
# Every reader goes through the accessors below, which take a string *or* an object. That
# tolerance is not politeness to old code — an already-written graph.json on someone's disk
# has string edges, and the alternative to reading it is silently reporting a repo with no
# dependencies, which is the exact failure this whole initiative exists to remove.

EDGE_DEFAULT_KIND = 'imports'
EDGE_DEFAULT_PROVENANCE = 'extracted'


def make_edge(other: str,
              kind: str = EDGE_DEFAULT_KIND,
              provenance: str = EDGE_DEFAULT_PROVENANCE,
              reverse: bool = False,
              **extra: Any) -> Dict[str, Any]:
    """One edge. `reverse=True` keys it as `from` (a dependents entry) rather than `to`."""
    if kind not in RELATION_KINDS:
        raise ValueError('relation kind %r is not in the contract vocabulary %s'
                         % (kind, list(RELATION_KINDS)))
    if provenance not in PROVENANCE:
        raise ValueError('provenance %r is not one of %s' % (provenance, list(PROVENANCE)))
    edge = {'from' if reverse else 'to': other, 'kind': kind, 'provenance': provenance}
    edge.update(extra)
    return edge


def edge_other(edge: Any) -> str:
    """The far end of an edge, whether it is an object or a legacy bare string."""
    if isinstance(edge, str):
        return edge
    if isinstance(edge, dict):
        value = edge.get('to')
        if value is None:
            value = edge.get('from')
        return value if isinstance(value, str) else ''
    return ''


def edge_kind(edge: Any) -> str:
    if isinstance(edge, dict) and isinstance(edge.get('kind'), str):
        return edge['kind']
    return EDGE_DEFAULT_KIND


def edge_provenance(edge: Any) -> str:
    if isinstance(edge, dict) and isinstance(edge.get('provenance'), str):
        return edge['provenance']
    return EDGE_DEFAULT_PROVENANCE


def edge_ends(edges: Any) -> List[str]:
    """Just the far ends, in order. The list a string-era caller used to get."""
    return [end for end in (edge_other(e) for e in (edges or [])) if end]


def internal_ends(edges: Any) -> List[str]:
    """The far ends that name a file in this project, dropping the signals."""
    return [end for end in edge_ends(edges) if is_internal(end)]


def upgrade_edges(graph: Dict[str, Any]) -> Dict[str, Any]:
    """Rewrite any bare-string edges in a loaded graph as objects, in place.

    Applied on read so a graph written before edges were objects keeps working and is
    corrected by the next build. The upgraded edge claims `imports`/`extracted`, which is
    exactly what the string era could express and therefore the only honest reading of it —
    it must not claim a kind the old resolver never determined.
    """
    files = graph.get('files')
    if not isinstance(files, dict):
        return graph
    for info in files.values():
        if not isinstance(info, dict):
            continue
        for key, reverse in (('imports', False), ('dependents', True)):
            edges = info.get(key)
            if not isinstance(edges, list) or not any(isinstance(e, str) for e in edges):
                continue
            info[key] = [make_edge(e, reverse=reverse) if isinstance(e, str) else e
                         for e in edges]
    # `version` is deliberately NOT stamped here. It records what is *on disk*, and this
    # function only fixes the copy in memory. Stamping it would make `is_stale` answer False
    # for every graph the moment it was read — which is exactly backwards, since reading is
    # how we find out it is stale. The stamp belongs to whoever writes the file.
    return graph


def is_stale(graph: Dict[str, Any]) -> bool:
    """Was the file this graph came from written against an older schema?"""
    version = graph.get('version')
    return not isinstance(version, int) or version < GRAPH_SCHEMA_VERSION


def graph_dir(project_dir: Any) -> str:
    return os.path.join(str(project_dir), *GRAPH_DIR)


def active_graph_path(project_dir: Any) -> str:
    """The graph other skills read. One path, whichever backend produced it."""
    return os.path.join(graph_dir(project_dir), ACTIVE_GRAPH)


def backend_graph_path(project_dir: Any, backend_name: str) -> str:
    """This backend's own copy (CD-17), so a swap can be diffed against the baseline."""
    return os.path.join(graph_dir(project_dir), 'graph.%s.json' % backend_name)


# ---------------------------------------------------------------------------
# What a backend hands back
# ---------------------------------------------------------------------------

class Result:
    """A backend's output: the graph it produced, and what it did to produce it.

    A bare dict cannot say "nothing changed", and `update` has to be able to — without
    inventing a sentinel that every caller then has to know about. It also cannot say how
    much moved, which is the only thing the update summary has to report.

    The graph inside is deliberately *unfinished*. Linking `dependents`, validating, and
    persisting are the contract's job, not the backend's (spec §2.1): every backend needs
    them done identically, and asking each one to remember is asking for the second backend
    to forget. A backend produces nodes and edges and stops.
    """

    __slots__ = ('graph', 'status', 'files_changed')

    BUILT = 'built'
    UPDATED = 'updated'
    UP_TO_DATE = 'up_to_date'

    def __init__(self, graph: Optional[Dict[str, Any]], status: str = BUILT,
                 files_changed: Optional[int] = None):
        if status not in (self.BUILT, self.UPDATED, self.UP_TO_DATE):
            raise ValueError('unknown status %r' % status)
        if graph is None and status != self.UP_TO_DATE:
            raise ValueError('status %r requires a graph' % status)
        self.graph = graph
        self.status = status
        self.files_changed = files_changed

    @property
    def needs_writing(self) -> bool:
        return self.status != self.UP_TO_DATE

    def __repr__(self) -> str:
        return 'Result(status=%r, files=%d)' % (
            self.status, len((self.graph or {}).get('files') or {}))


def link_dependents(graph: Dict[str, Any]) -> Dict[str, Any]:
    """Fill every file's `dependents` from every other file's `imports`.

    The reverse index is derived, so it is computed here once rather than by each backend.
    Rebuilt from scratch, never appended to: an incremental pass that only adds entries
    leaves an edge behind when the import that justified it is deleted, and blast radius
    then reports a dependency that no longer exists.
    """
    files = graph.get('files')
    if not isinstance(files, dict):
        return graph
    for info in files.values():
        if isinstance(info, dict):
            info['dependents'] = []
    for path, info in files.items():
        if not isinstance(info, dict):
            continue
        for edge in info.get('imports') or []:
            target = edge_other(edge)
            if is_internal(target) and target in files:
                # The reverse edge carries the forward edge's kind and provenance. An
                # `inherits` edge read backwards is still an `inherits` edge, and blast
                # radius has to be able to ask which kind reached it.
                files[target]['dependents'].append(
                    make_edge(path, kind=edge_kind(edge),
                              provenance=edge_provenance(edge), reverse=True))
    return graph


def build_summary(graph: Dict[str, Any], cached_to: str) -> Dict[str, Any]:
    files = graph.get('files') or {}
    return {
        'files_scanned': len(files),
        'total_imports': sum(len(f.get('imports') or []) for f in files.values()),
        'total_exports': sum(len(f.get('exports') or []) for f in files.values()),
        'commit': graph.get('commit'),
        'cached_to': cached_to,
    }


# ---------------------------------------------------------------------------
# Coverage
# ---------------------------------------------------------------------------

class Coverage:
    """What a backend actually handles — obligation 4.

    Declaring languages answers "can you see this repo at all", which is the headline Track B
    failure: a Java repo graphed as empty and reported as success. Declaring relation kinds
    answers the finer question, so a caller needing symbol-level `calls` can degrade that one
    query instead of distrusting the whole graph (CD-16).
    """

    __slots__ = ('languages', 'extensions', 'relations', 'incremental')

    def __init__(self,
                 languages: Iterable[str],
                 extensions: Iterable[str],
                 relations: Iterable[str],
                 incremental: bool):
        self.languages = tuple(sorted(set(languages)))
        self.extensions = tuple(sorted({_dotted(e) for e in extensions}))
        unknown = sorted(set(relations) - set(RELATION_KINDS))
        if unknown:
            raise ValueError(
                'relation kinds not in the contract vocabulary: %s (known: %s)'
                % (', '.join(unknown), ', '.join(RELATION_KINDS)))
        self.relations = tuple(r for r in RELATION_KINDS if r in set(relations))
        # Obligation 5. False means "rebuild me from scratch"; the contract must not quietly
        # trust an incremental pass that cannot remove deleted nodes.
        self.incremental = bool(incremental)

    def handles(self, path: str) -> bool:
        """Would this backend attempt the file at `path`?"""
        return os.path.splitext(path)[1].lower() in self.extensions

    def blind_spots(self, paths: Iterable[str]) -> Dict[str, int]:
        """Extensions present in `paths` that this backend does not read, with counts.

        The point of the whole declaration. Given the files a project actually contains, this
        is the honest answer to "what am I not seeing?", which is what lets a caller warn
        instead of returning a confident nothing.
        """
        missed = {}  # type: Dict[str, int]
        for path in paths:
            ext = os.path.splitext(path)[1].lower()
            if ext and ext not in self.extensions:
                missed[ext] = missed.get(ext, 0) + 1
        return dict(sorted(missed.items(), key=lambda kv: (-kv[1], kv[0])))

    def to_dict(self) -> Dict[str, Any]:
        return {
            'languages': list(self.languages),
            'extensions': list(self.extensions),
            'relations': list(self.relations),
            'incremental': self.incremental,
        }

    @classmethod
    def from_dict(cls, data: Optional[Dict[str, Any]]) -> Optional['Coverage']:
        if not isinstance(data, dict):
            return None
        try:
            return cls(
                languages=data.get('languages') or (),
                extensions=data.get('extensions') or (),
                relations=data.get('relations') or (),
                incremental=bool(data.get('incremental', False)),
            )
        except (TypeError, ValueError):
            return None

    def __eq__(self, other: Any) -> bool:
        return isinstance(other, Coverage) and self.to_dict() == other.to_dict()

    def __repr__(self) -> str:
        return 'Coverage(languages=%s, relations=%s, incremental=%s)' % (
            list(self.languages), list(self.relations), self.incremental)


def _dotted(ext: str) -> str:
    ext = (ext or '').strip().lower()
    if ext and not ext.startswith('.'):
        ext = '.' + ext
    return ext


# ---------------------------------------------------------------------------
# Exclusions
# ---------------------------------------------------------------------------

class Exclusions:
    """What the project has declared out of scope — obligation 6.

    Passed *into* a backend rather than decided by it. "`vendor/` is not mine" is a fact about
    the project, true whichever parser runs, and a backend left to guess will happily graph
    generated output and fill blast radius with noise nobody can switch off.

    `directories` are project-relative paths; `patterns` are gitignore-style. `matcher` is
    supplied by the caller so the contract does not have to own a second, subtly different
    implementation of gitignore semantics — there were two of those once, and they disagreed.

    `overrides` are directories the project has explicitly declared **in** scope, and they win
    over both of the above. They exist because exclusions are assembled from defaults and from
    `.gitignore`, neither of which can know that this repository keeps real source somewhere
    the convention says it should not. Without them the override implemented in the resolver
    would be undone one layer up — the caller passes these exclusions back into `build()`, so a
    gitignored directory the project had just declared source would be filtered out again.

    Carried on the contract rather than inside one backend on purpose: an override is a fact
    about the project (obligation 6), so every backend has to honour it, including ones that
    have never heard of `classifications.json`.
    """

    __slots__ = ('directories', 'patterns', 'overrides', '_matcher')

    def __init__(self,
                 directories: Iterable[str] = (),
                 patterns: Iterable[str] = (),
                 matcher: Optional[Callable[[str, Sequence[str]], bool]] = None,
                 overrides: Iterable[str] = ()):
        self.directories = tuple(sorted({d.strip('/') for d in directories if d}))
        self.patterns = tuple(p for p in patterns if p)
        self.overrides = tuple(sorted({d.strip('/') for d in overrides if d}))
        self._matcher = matcher

    @staticmethod
    def _under(parts: Sequence[str], directory: str) -> bool:
        d = directory.split('/')
        return list(parts[:len(d)]) == d

    def excludes(self, rel_path: str) -> bool:
        rel = (rel_path or '').replace(os.sep, '/').lstrip('/')
        if not rel:
            return False
        parts = rel.split('/')
        # Deepest override first, so `packages/` being declared source does not resurrect
        # `packages/legacy/` when that one is separately excluded.
        for directory in sorted(self.overrides, key=lambda d: -d.count('/')):
            if self._under(parts, directory):
                deeper = [x for x in self.directories
                          if x.count('/') > directory.count('/') and self._under(parts, x)]
                return bool(deeper)
        for directory in self.directories:
            if self._under(parts, directory):
                return True
        if self._matcher and self.patterns:
            return bool(self._matcher(rel, self.patterns))
        return False

    def to_dict(self) -> Dict[str, Any]:
        data = {'directories': list(self.directories),
                'patterns': list(self.patterns)}  # type: Dict[str, Any]
        if self.overrides:
            # Only when present, so a graph from a project that never overrode anything is
            # byte-identical to one written before overrides existed.
            data['overrides'] = list(self.overrides)
        return data

    def __repr__(self) -> str:
        return 'Exclusions(directories=%d, patterns=%d, overrides=%d)' % (
            len(self.directories), len(self.patterns), len(self.overrides))


# ---------------------------------------------------------------------------
# The backend interface
# ---------------------------------------------------------------------------
#
# Structural, not inherited. A backend satisfies this by having the right attributes; it does
# not import a base class. That matters because the second backend (graphify) wraps a tool
# nobody here controls, and a contract only the incumbent can satisfy is not a contract.
#
# Python 3.9 is the floor, so this is documented and checked at runtime by
# `conformance_errors()` rather than expressed as typing.Protocol with @runtime_checkable —
# which would only check that the names exist anyway.

REQUIRED_BACKEND_ATTRS = ('name', 'project_dir', 'coverage', 'available', 'build', 'update')

# The two that are values rather than methods.
_BACKEND_VALUE_ATTRS = ('name', 'project_dir')

# The call the caller actually makes. Written down because "callable" is not a contract: a
# backend can pass an attribute check and still be uninvokable, which is what happened — this
# repo's own reference backend satisfied `conformance_errors()` and then crashed the CLI on
# an unexpected keyword. A contract that green-lights something the only caller cannot call
# is not checking the thing that matters.
BUILD_KWARGS = ('exclusions', 'non_interactive', 'selection_metadata')
UPDATE_KWARGS = ('exclusions', 'non_interactive', 'selection_metadata')


def _accepts(func: Any, kwargs: Sequence[str]) -> Optional[str]:
    """None if `func` can be called with all of `kwargs`, else why not."""
    import inspect

    try:
        signature = inspect.signature(func)
    except (TypeError, ValueError):
        return None  # builtins and C callables cannot be introspected; do not fail them
    try:
        signature.bind(**{name: None for name in kwargs})
    except TypeError as exc:
        return str(exc)
    return None


def conformance_errors(backend: Any) -> List[str]:
    """Ways `backend` fails the contract. Empty list means it conforms.

    A runtime check rather than a type: the point is that a *new* backend can be validated by
    its own test suite before it is ever selected, so a non-conforming one fails loudly at
    registration instead of quietly at query time.
    """
    errors = []  # type: List[str]

    name = getattr(backend, 'name', None)
    if not isinstance(name, str) or not name:
        errors.append('name: must be a non-empty string')
    elif not name.replace('-', '').replace('_', '').isalnum():
        # The name becomes a filename (graph.<name>.json, CD-17).
        errors.append('name: %r is not filename-safe (letters, digits, - and _)' % name)

    for attr in REQUIRED_BACKEND_ATTRS:
        if not hasattr(backend, attr):
            errors.append('%s: missing' % attr)
        elif attr not in _BACKEND_VALUE_ATTRS and not callable(getattr(backend, attr)):
            errors.append('%s: must be callable' % attr)

    # The contract persists the graph, so it has to know where. Every backend is already
    # constructed with a project directory — this only requires it to keep it.
    if hasattr(backend, 'project_dir') and not str(getattr(backend, 'project_dir') or ''):
        errors.append('project_dir: must be a non-empty path')

    for attr, kwargs in (('build', BUILD_KWARGS), ('update', UPDATE_KWARGS)):
        func = getattr(backend, attr, None)
        if callable(func):
            why = _accepts(func, kwargs)
            if why:
                errors.append('%s: cannot be called as the contract calls it — %s '
                              '(expected keywords: %s)'
                              % (attr, why, ', '.join(kwargs)))

    if hasattr(backend, 'coverage') and callable(getattr(backend, 'coverage')):
        try:
            cov = backend.coverage()
        except Exception as exc:  # a backend that cannot describe itself is unusable
            errors.append('coverage(): raised %s' % exc.__class__.__name__)
        else:
            if not isinstance(cov, Coverage):
                errors.append('coverage(): must return a Coverage, got %s'
                              % type(cov).__name__)
            elif not cov.languages or not cov.extensions:
                errors.append('coverage(): declares no languages or no extensions, so it '
                              'can never be selected for anything')

    return errors


# ---------------------------------------------------------------------------
# Graph metadata and validation
# ---------------------------------------------------------------------------

def graph_metadata(backend_name: str,
                   coverage: Coverage,
                   exclusions: Optional[Exclusions] = None,
                   degraded_from: Optional[str] = None,
                   degraded_reason: Optional[str] = None) -> Dict[str, Any]:
    """The `substrate` block every graph carries.

    Written on every build so that a graph read months later still says which backend produced
    it and what that backend could see. Spec §2.2: selection is *never silent*.
    """
    meta = {
        'backend': backend_name,
        'coverage': coverage.to_dict(),
        'schema': GRAPH_SCHEMA_VERSION,
    }  # type: Dict[str, Any]
    if exclusions is not None:
        meta['exclusions'] = exclusions.to_dict()
    if degraded_from:
        # The configured backend was unavailable and we fell back. Recorded rather than
        # inferred later from a coverage gap, so a thin graph is never mistaken for a thin repo.
        meta['degraded_from'] = degraded_from
        meta['degraded_reason'] = degraded_reason or 'backend unavailable'
    return meta


def validate_graph(graph: Dict[str, Any], coverage: Optional[Coverage] = None) -> List[str]:
    """Ways a produced graph breaks the contract. Empty list means it conforms.

    Deliberately cheap and structural — it is a guard against a backend emitting something
    downstream cannot read, not a correctness check on the edges themselves. Only measurement
    against real source can do the latter, which is what spec §9.1 is for.
    """
    errors = []  # type: List[str]

    if not isinstance(graph, dict):
        return ['graph: must be a dict, got %s' % type(graph).__name__]

    files = graph.get('files')
    if not isinstance(files, dict):
        return ['files: must be a dict, got %s' % type(files).__name__]

    substrate = graph.get('substrate')
    if not isinstance(substrate, dict):
        errors.append('substrate: missing metadata block (obligation 4)')
    else:
        if not substrate.get('backend'):
            errors.append('substrate.backend: missing, so the graph cannot say what made it')
        if Coverage.from_dict(substrate.get('coverage')) is None:
            errors.append('substrate.coverage: missing or malformed')

    for path, info in files.items():
        if not isinstance(info, dict):
            errors.append('files[%r]: must be a dict' % path)
            continue
        imports = info.get('imports')
        if not isinstance(imports, list):
            errors.append('files[%r].imports: must be a list' % path)
            continue
        for edge in imports:
            spec = edge_other(edge)
            if not spec:
                errors.append('files[%r]: an edge names no target' % path)
                continue
            if isinstance(edge, dict):
                if edge.get('kind') not in RELATION_KINDS:
                    errors.append('files[%r]: edge to %r has kind %r, which is not in %s'
                                  % (path, spec, edge.get('kind'), list(RELATION_KINDS)))
                if edge.get('provenance') not in PROVENANCE:
                    errors.append('files[%r]: edge to %r has provenance %r, not one of %s'
                                  % (path, spec, edge.get('provenance'), list(PROVENANCE)))
            if is_internal(spec) and spec not in files:
                # Obligation 2 inverted: an internal edge must name a file in the graph.
                # Anything unresolvable belongs behind `unresolved:`, where it is visible.
                errors.append(
                    'files[%r]: edge to %r names no file in the graph — an unresolved '
                    'target must carry the unresolved: prefix' % (path, spec))

        # The reverse index went unvalidated until 2026-08-20, which was survivable while it
        # held mirrored strings and no longer is: an edge object keyed `to` instead of `from`,
        # or one that lost its kind on the way back, is now expressible and would pass
        # unnoticed. Every dependent must name a real file — unlike an import, there is no
        # such thing as an external dependent.
        dependents = info.get('dependents')
        if dependents is not None and not isinstance(dependents, list):
            errors.append('files[%r].dependents: must be a list' % path)
        else:
            for edge in dependents or []:
                if isinstance(edge, dict) and 'from' not in edge and 'to' in edge:
                    errors.append('files[%r]: dependent %r is keyed `to`; a reverse edge '
                                  'names its source with `from`' % (path, edge.get('to')))
                    continue
                source = edge_other(edge)
                if not source:
                    errors.append('files[%r]: a dependent names no source' % path)
                elif source not in files:
                    errors.append('files[%r]: dependent %r names no file in the graph'
                                  % (path, source))

        if coverage is not None and not coverage.handles(path):
            errors.append('files[%r]: outside the declared coverage %s'
                          % (path, list(coverage.extensions)))

    return errors


def summarise_coverage(graph: Dict[str, Any], present_files: Iterable[str]) -> Dict[str, Any]:
    """What this graph saw, and what it did not, against the files actually on disk.

    The answer to "is this repo really this sparse, or is my backend blind?" — which nothing
    in the toolkit could answer before, and which is why a Java repo read as greenfield.
    """
    substrate = graph.get('substrate') or {}
    coverage = Coverage.from_dict(substrate.get('coverage'))
    files = graph.get('files') or {}

    ends = [edge_other(e) for info in files.values() for e in (info.get('imports') or [])]
    internal = sum(1 for end in ends if is_internal(end))
    unresolved = sum(1 for end in ends if end.startswith('unresolved:'))

    summary = {
        'backend': substrate.get('backend'),
        'files_graphed': len(files),
        'internal_edges': internal,
        'unresolved_imports': unresolved,
        'degraded_from': substrate.get('degraded_from'),
    }  # type: Dict[str, Any]
    if coverage is not None:
        summary['coverage'] = coverage.to_dict()
        summary['blind_spots'] = coverage.blind_spots(present_files)
    return summary


def load_graph(path: str) -> Optional[Dict[str, Any]]:
    """Read a graph artifact, brought forward to the current schema. None if unreadable.

    The upgrade happens here rather than being left to the caller for the same reason it
    happens in `CodeGraph.load`: a reader that skips it sees string edges and quietly reports
    a repository with no dependencies. Two readers with different tolerance is worse than one
    with none.
    """
    try:
        with open(path, encoding='utf-8') as handle:
            data = json.load(handle)
    except (OSError, ValueError):
        return None
    return upgrade_edges(data) if isinstance(data, dict) else None
