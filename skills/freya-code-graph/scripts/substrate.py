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

GRAPH_SCHEMA_VERSION = 1


def is_internal(specifier: str) -> bool:
    """Is this import specifier a resolved project file, rather than a signal?"""
    return bool(specifier) and not specifier.startswith(IMPORT_SIGNALS)


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
    """

    __slots__ = ('directories', 'patterns', '_matcher')

    def __init__(self,
                 directories: Iterable[str] = (),
                 patterns: Iterable[str] = (),
                 matcher: Optional[Callable[[str, Sequence[str]], bool]] = None):
        self.directories = tuple(sorted({d.strip('/') for d in directories if d}))
        self.patterns = tuple(p for p in patterns if p)
        self._matcher = matcher

    def excludes(self, rel_path: str) -> bool:
        rel = (rel_path or '').replace(os.sep, '/').lstrip('/')
        if not rel:
            return False
        parts = rel.split('/')
        for directory in self.directories:
            d = directory.split('/')
            if parts[:len(d)] == d:
                return True
        if self._matcher and self.patterns:
            return bool(self._matcher(rel, self.patterns))
        return False

    def to_dict(self) -> Dict[str, Any]:
        return {'directories': list(self.directories), 'patterns': list(self.patterns)}

    def __repr__(self) -> str:
        return 'Exclusions(directories=%d, patterns=%d)' % (
            len(self.directories), len(self.patterns))


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

REQUIRED_BACKEND_ATTRS = ('name', 'coverage', 'available', 'build', 'update')

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
        elif attr != 'name' and not callable(getattr(backend, attr)):
            errors.append('%s: must be callable' % attr)

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
        for spec in imports:
            if not isinstance(spec, str) or not spec:
                errors.append('files[%r]: import specifier must be a non-empty string' % path)
            elif is_internal(spec) and spec not in files:
                # Obligation 2 inverted: an internal edge must name a file in the graph.
                # Anything unresolvable belongs behind `unresolved:`, where it is visible.
                errors.append(
                    'files[%r]: edge to %r names no file in the graph — an unresolved '
                    'target must carry the unresolved: prefix' % (path, spec))
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

    internal = sum(1 for info in files.values()
                   for spec in (info.get('imports') or []) if is_internal(spec))
    unresolved = sum(1 for info in files.values()
                     for spec in (info.get('imports') or [])
                     if isinstance(spec, str) and spec.startswith('unresolved:'))

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
    """Read a graph artifact, or None if it is absent or unreadable."""
    try:
        with open(path, encoding='utf-8') as handle:
            data = json.load(handle)
    except (OSError, ValueError):
        return None
    return data if isinstance(data, dict) else None
