#!/usr/bin/env python3
"""The substrate contract: what a code-graph backend must provide.

freya's dependency graph was one hand-written resolver. Track B makes it a *socket*, so a
project can run the stdlib-only resolver that ships with the toolkit, or a real multi-language
parser, and everything downstream — blast radius, docs impact, behavior fingerprints — keeps
working either way.

This module is the socket. It holds no parsing logic, and outside the standard library it
imports only its sibling `containment` (ADR-030), so a backend inherits nothing by using it.

Six obligations. The spec they came from was a working document, deleted with the rest of
that record on 2026-08-21; the decisions it settled are ADR-018 (the contract), ADR-019 (the
floor and the backend choice) and ADR-020 (who persists). Git history has the original:
`git show 2762d54:docs/polyglot/spec.md`.


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

import containment

# ---------------------------------------------------------------------------
# Vocabulary
# ---------------------------------------------------------------------------

# The relation kinds a backend may declare and emit. Fixed deliberately: a contract whose
# vocabulary each backend defines for itself is describing implementations, not an interface,
# and a caller could not then ask "does this backend give me calls?" in a portable way.
#
# Defined here in Phase 1 rather than in Phase 3, where symbols land, because inventing a
# vocabulary during a migration is worse than agreeing one before it (ADR-018).
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

# A target that resolved to a real file under a directory this project *declared* outside its
# own root — the `outside` section of `knowledge-base/settings.json` (ADR-031). The tail is
# `<alias>/<path under that root>`: the alias the project chose, never the path, so the token
# is the same string in every clone and no absolute path reaches an artifact.
#
# It is a signal and not a key, and that is the whole of the design. `is_internal` is false for
# it, so `link_dependents` builds no reverse edge and `validate_graph` demands no node, and the
# key space stays exactly what ADR-025 says it is — which is what lets the `files`-key rule in
# `validate_graph` stay unconditional. It is also why a consumer that has never heard of
# declarations fails *closed*: `outside:ui/src/Button.tsx` joined onto any root names nothing
# that exists, and it carries no `..`, no drive and no leading slash with which to try.
OUTSIDE_PREFIX = 'outside:'

# Prefixes that mark an import specifier as a signal rather than a resolved path. Kept in one
# place because three skills independently filter on them, and a fourth prefix added without
# updating all of them would be counted as an internal edge. That is not hypothetical: the
# fourth arrived on 2026-08-23, and `graph_ops` and `project_shape` had each grown their own
# copy of the tuple by then. Both import this one now.
IMPORT_SIGNALS = ('external:', 'unresolved:', OUTSIDE_PREFIX)

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
    """Is this import specifier a resolved project file, rather than a signal?

    Four answers, not three, since 2026-08-23: a file in this project, a package
    (`external:`), something that could not be resolved (`unresolved:`), and something that
    resolved under a declared out-of-tree root (`outside:`). Only the first is internal. The
    fourth is the one worth stating, because it *did* resolve to a real file and is still not
    a node: a declaration buys resolution, never a place in the key space (ADR-031).
    """
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
# and optionally, when a backend can see that far (Phase 3):
#
#   from_symbol   the symbol the edge leaves, e.g. `conformance_errors`
#   to_symbol     the symbol it arrives at
#   line          1-based line of the statement that produced it
#
# The three are *refinement*, never replacement (spec §5, ADR-024). Every edge keeps its file
# anchor, so a consumer that ignores them behaves exactly as it did before they existed —
# which is what makes symbol support optional per backend rather than a schema change.
#
# Every reader goes through the accessors below, which take a string *or* an object. That
# tolerance is not politeness to old code — an already-written graph.json on someone's disk
# has string edges, and the alternative to reading it is silently reporting a repo with no
# dependencies, which is the exact failure this whole initiative exists to remove.

EDGE_DEFAULT_KIND = 'imports'
EDGE_DEFAULT_PROVENANCE = 'extracted'

# The optional Phase 3 refinement, named once so the reverse index and the
# validator cannot disagree about what a symbol field is called.
SYMBOL_FIELDS = ('from_symbol', 'to_symbol')


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


def _symbol_errors(edge: Dict[str, Any]) -> List[str]:
    """Ways an edge's optional symbol refinement is malformed. Absent is always fine.

    Checked because "optional" is where the sloppiness goes. An empty string or a `null` is
    not a symbol, and it reads as one to anything doing a truthiness test — the difference
    between "this edge has no symbol" and "this edge has a symbol whose name is nothing"
    matters to whoever tries to display it.
    """
    problems = []  # type: List[str]
    for field in SYMBOL_FIELDS:
        if field not in edge:
            continue
        value = edge[field]
        if not isinstance(value, str) or not value.strip():
            problems.append('has %s %r, which is not a symbol name' % (field, value))
    if 'line' in edge:
        line = edge['line']
        if not isinstance(line, int) or isinstance(line, bool) or line < 1:
            problems.append('has line %r, which is not a 1-based line number' % (line,))
    return problems


def edge_symbols(edge: Any) -> Tuple[Optional[str], Optional[str]]:
    """`(from_symbol, to_symbol)` for an edge, or `(None, None)` if it carries none."""
    if not isinstance(edge, dict):
        return (None, None)
    out = []
    for field in SYMBOL_FIELDS:
        value = edge.get(field)
        out.append(value if isinstance(value, str) and value.strip() else None)
    return (out[0], out[1])


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


def produced_by(graph: Dict[str, Any]) -> Optional[str]:
    """Which backend wrote this graph, or None if it does not say."""
    substrate_block = graph.get('substrate')
    if not isinstance(substrate_block, dict):
        return None
    name = substrate_block.get('backend')
    return name if isinstance(name, str) and name else None


def graph_dir(project_dir: Any) -> str:
    return os.path.join(str(project_dir), *GRAPH_DIR)


def active_graph_path(project_dir: Any) -> str:
    """The graph other skills read. One path, whichever backend produced it."""
    return os.path.join(graph_dir(project_dir), ACTIVE_GRAPH)


def backend_graph_path(project_dir: Any, backend_name: str) -> str:
    """This backend's own copy (ADR-028), so a swap can be diffed against the baseline."""
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
            if target == path:
                # Never link a file to itself; `validate_graph` reports it separately. Doing
                # it here as well means a backend that emits one gets a wrong-looking graph
                # rather than a wrong *answer* — blast radius walks `dependents`, so a
                # self-entry puts every file in its own blast radius.
                continue
            # `isinstance` on the *target's* entry, not just this one. Linking runs before
            # validation — it has to, since validation checks the reverse index it produces —
            # so a backend emitting a non-dict node would crash here with
            # `TypeError: string indices must be integers`, one line before the validator
            # that was about to name the offending file.
            if is_internal(target) and isinstance(files.get(target), dict):
                # The reverse edge carries the forward edge's kind, provenance *and*
                # symbols. An `inherits` edge read backwards is still `inherits`, and blast
                # radius has to be able to ask which kind reached it.
                #
                # Carrying the symbols is not symmetry for its own sake. Under
                # `substrate.symbols` one file pair legitimately holds many forward edges of
                # the same kind, distinguished only by which symbols they join. Dropping the
                # symbols on the way back collapsed all of them into byte-identical dicts —
                # measured on this repository: 417 dependent entries of which 322 were exact
                # duplicates, one file listing the same dependent 60 times, and `--query`
                # printing that line 60 times. The information that made them distinct was
                # thrown away at precisely the point it was needed.
                #
                # Built directly rather than through `make_edge`, which raises for a kind or
                # provenance outside the vocabulary. Linking runs one line *before*
                # `validate_graph`, so routing this through the constructor meant a backend
                # emitting `mixes_in` died here with a bare ValueError — and the validator's
                # own message, which names the file and the offending kind and is the whole
                # point of having one, was unreachable. The reverse edge mirrors whatever the
                # forward edge said; if that is wrong, the validator is what says so.
                reverse = {'from': path,
                           'kind': edge_kind(edge),
                           'provenance': edge_provenance(edge)}
                for field in SYMBOL_FIELDS + ('line',):
                    if field in edge:
                        reverse[field] = edge[field]
                files[target]['dependents'].append(reverse)
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
    query instead of distrusting the whole graph (ADR-018).
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
                return self._excluded_under_override(rel, parts, directory)
        for directory in self.directories:
            if self._under(parts, directory):
                return True
        if self._matcher and self.patterns:
            return bool(self._matcher(rel, self.patterns))
        return False

    def _excluded_under_override(self, rel: str, parts: Sequence[str], override: str) -> bool:
        """Is a path *inside* an overridden directory still excluded by something?

        An override says "this directory is in scope, whatever the convention lists and
        `.gitignore` decided". It does **not** say "and nothing inside it can ever be out of
        scope", and reading it that way was a real defect: this method used to return
        `bool(deeper)` and never reach the pattern matcher at all, so
        `{"directories": {"packages": "source"}}` on an npm-workspaces tree pulled every
        `packages/*/node_modules/**` into the graph. Measured on a two-package fixture: the
        override admitted the whole vendored tree, and the control build without it did not.

        That is the 50,000-file blast radius ADR-022's two-tier design exists to prevent,
        reached through an ordinary ancestor verdict — and nothing could switch it back off,
        because the classifier does not descend into a directory whose ancestor already
        carries a stated verdict, so no nested `exclude` is ever derived to catch it.

        The rule instead: a rule aimed **at the override or above it** is what the override
        overrules; a rule that describes something **inside** it still applies. So the
        patterns are re-matched against the path *relative to the override root* —
        `node_modules/` still catches `packages/app/node_modules/lodash/index.js` via its
        tail, while `packages/` (the entry the override exists to beat) matches no tail at
        all and is correctly ignored.
        """
        # A carve-out the project stated itself, deeper than the override it sits in.
        depth = override.count('/')
        if any(x.count('/') > depth and self._under(parts, x) for x in self.directories):
            return True
        if self._matcher and self.patterns:
            tail = '/'.join(parts[len(override.split('/')):])
            if tail:
                return bool(self._matcher(tail, self.patterns))
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
        # The name becomes a filename (graph.<name>.json, ADR-028).
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
        if isinstance(path, str) and containment.escapes(path):
            # `containment.escapes` and not `rel_within`, because this judges a string that
            # is already *in* the artifact and there is no root here to resolve it against:
            # a graph.json is read on machines that did not write it, so `project_root`
            # names someone else's filesystem. The rule has to be one the string alone can
            # answer. Nothing checked keys until now — every edge was validated and never
            # the key it hangs off — so `backend_graphify`'s `lstrip('/')` could turn
            # `/etc/passwd` into the key `etc/passwd` and the graph validated clean
            # (SEC-015). This is the rule's only home that binds a backend nobody has
            # written yet.
            #
            # Unconditional, with no exception for a declared out-of-project root: such a
            # file may be *resolved against*, but it never becomes a key.
            #
            # Reported and not `continue`d — the rest of the entry is still worth checking,
            # and one finding per defect beats a cascade.
            errors.append('files[%r]: not a project-relative path — a graph key is a '
                          'project-relative POSIX path (ADR-025)' % path)
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
                errors.extend('files[%r]: edge to %r %s' % (path, spec, why)
                              for why in _symbol_errors(edge))
            if spec == path:
                # A file is never its own dependency. `link_dependents` would make it its own
                # dependent and every traversal walks that, so `--impact` on the file reports
                # the file as directly affected by itself.
                #
                # The homegrown resolver has dropped these since it learned to (its comment at
                # `_classify_import` explains the `rich/abc.py` case), but nothing *checked* —
                # so the rule lived in one backend rather than in the contract. graphify is
                # the reason it matters: 1,516 of its mapped links on this repository are
                # intra-file, which at file level is 1,516 self-edges.
                errors.append('files[%r]: edge to itself — a file is not its own dependency'
                              % path)
            elif is_internal(spec) and spec not in files:
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
                # The comment above names "one that lost its kind on the way back" as a
                # reason to validate the reverse index, and then only the key and the source
                # were checked — so the stated reason was the one thing not covered. A
                # reverse edge is an edge; it is held to the same vocabulary as a forward one.
                if isinstance(edge, dict):
                    if edge.get('kind') not in RELATION_KINDS:
                        errors.append('files[%r]: dependent %r has kind %r, which is not in %s'
                                      % (path, source, edge.get('kind'), list(RELATION_KINDS)))
                    if edge.get('provenance') not in PROVENANCE:
                        errors.append('files[%r]: dependent %r has provenance %r, not one of %s'
                                      % (path, source, edge.get('provenance'), list(PROVENANCE)))
                    errors.extend('files[%r]: dependent %r %s' % (path, source, why)
                                  for why in _symbol_errors(edge))

        # Extensionless files are exempt, for the same reason `Coverage.blind_spots` skips
        # them: this model keys on extension, so about `bin/freya` or `Makefile` it has
        # nothing to say — and "outside the declared coverage" is an assertion, not silence.
        # A real backend does read them: graphify extracts shell functions from an
        # extensionless script with a shebang, and flagging that as a contract breach reports
        # the model's limitation as the backend's fault.
        if (coverage is not None and os.path.splitext(path)[1]
                and not coverage.handles(path)):
            errors.append('files[%r]: outside the declared coverage %s'
                          % (path, list(coverage.extensions)))

    return errors


# ---------------------------------------------------------------------------
# The unmapped-source census — ADR-029
# ---------------------------------------------------------------------------
#
# ADR-005 says the graph must never answer "nothing" when it means "I don't know". That was
# implemented at the *repository* level: a Java repo will not classify itself greenfield. It
# was never implemented at the *answer* level, and the two are different claims. "3 dependents"
# and "3 dependents, and I could not read a fifth of this repo" are not the same sentence, and
# until now the tool said the first when it meant the second.
#
# The consumer here is the agent driving the toolkit, not a person. A build runs with no
# keyboard attached almost every time — `--non-interactive` auto-enables whenever stdin is not
# a TTY, which is every agent-driven run and every `wrap-up` — so a printed warning lands
# nowhere. The signal has to ride in the machine-readable answer, which is the same argument
# `get_impact` already makes for `not_in_graph`, generalised from "the file you asked about is
# unmapped" to "this answer is incomplete".
#
# ADR-019's discipline applies: absent when there is nothing to say. A field that fires on every
# repository with a README is one an agent learns to skip inside a single context window, after
# which it costs tokens forever and changes no decision.

# Program source a backend might reasonably be expected to graph. Closed-world on purpose: an
# extension nobody listed produces silence, which is the right default for a signal whose only
# value is being believed. The cost is that a language nobody listed goes unreported — a real,
# narrower instance of the hole this closes, and recorded as such in ADR-029.
SOURCE_EXTENSIONS = frozenset({
    # JVM / .NET
    '.java', '.kt', '.kts', '.scala', '.groovy', '.gradle', '.clj', '.cljs', '.cljc',
    '.cs', '.fs', '.fsx', '.vb', '.razor', '.cshtml', '.csproj', '.fsproj', '.vbproj',
    # C family
    '.c', '.h', '.cc', '.cpp', '.cxx', '.hpp', '.hh', '.m', '.mm', '.cu', '.cuh', '.metal',
    # dynamic
    '.rb', '.rake', '.php', '.pl', '.pm', '.lua', '.luau', '.r', '.jl', '.pas', '.tcl',
    # systems / functional
    '.rs', '.go', '.swift', '.dart', '.zig', '.ex', '.exs', '.erl', '.hrl', '.cr', '.nim',
    '.hs', '.ml', '.mli', '.elm', '.lisp', '.cl', '.asd', '.lsp', '.dm',
    # hardware / scientific
    '.v', '.sv', '.svh', '.vhd', '.f', '.f90', '.f95', '.f03', '.f08',
    # platform-specific source
    '.cls', '.trigger', '.xaml',
    # web component source the floor cannot read
    '.vue', '.svelte', '.astro',
    # ESM/TS variants outside the floor's FILE_PATTERNS
    '.mjs', '.cjs', '.mts', '.cts', '.pyi', '.pyx',
    # declarative source: schemas, contracts, executable specs
    '.tf', '.tfvars', '.hcl', '.proto', '.sol', '.prisma', '.feature',
})

# Source in *some* repositories, glue in most. Reported only when they dominate — see
# `material_extensions`. Splitting these out is what keeps one PowerShell installer or three
# SQL migrations from firing the caveat on every build of every repo, without going silent on
# a repository that genuinely *is* a shell or stored-procedure codebase.
SCRIPT_EXTENSIONS = frozenset({
    '.sh', '.bash', '.zsh', '.ksh', '.fish', '.ps1', '.psm1', '.psd1',
    '.sql', '.awk', '.bat', '.cmd', '.vbs', '.applescript',
})

# A tier-2 extension has to beat both the graphed file count and this floor. The floor is what
# stops a two-file repository reporting its own build script; it is a tuned constant, chosen
# because it silences a single `.sh` without silencing a twelve-file PowerShell project.
SCRIPT_MATERIALITY_FLOOR = 2

# Directories never worth descending into for a census. A fourth copy of this idea — the other
# three are in project_shape, backends and detect_project, and they disagree with each other.
# Put here because the contract is what a consolidation would consolidate onto.
CENSUS_PRUNE = frozenset({
    'node_modules', 'dist', 'build', 'out', '.output', '.next', '__pycache__',
    'venv', '.venv', 'vendor', 'target', 'coverage', 'graphify-out',
})

CENSUS_LIMIT = 20000
UNMAPPED_EXT_CAP = 8
UNMAPPED_DIR_CAP = 5


def census_candidates(covered_extensions: Iterable[str]) -> frozenset:
    """Extensions worth walking for, given what the running backend already reads.

    Empty means the backend covers every candidate, and the caller can skip the walk entirely.
    """
    covered = {str(e).lower() for e in covered_extensions or ()}
    return frozenset((SOURCE_EXTENSIONS | SCRIPT_EXTENSIONS) - covered)


def material_extensions(counts: Dict[str, int], files_graphed: int,
                        cap: Optional[int] = UNMAPPED_EXT_CAP) -> Dict[str, int]:
    """Which unread extensions are worth reporting, given how much *was* read.

    `cap=None` returns every material extension. `unmapped_report` uses that to count honestly
    before truncating for display — taking the total from the capped dict published a number
    smaller than the truth.

    Tier 1 is unconditional: one unreadable `.java` in a 500-file TypeScript repo is exactly
    the case worth knowing about, and a count-based threshold would hide it. Tier 2 has to
    dominate — more unread files than the graph holds, and more than the floor — because a
    build script is not a blind spot in a repository that is not made of build scripts.
    """
    material = {}  # type: Dict[str, int]
    bar = max(files_graphed, SCRIPT_MATERIALITY_FLOOR)
    for ext, count in (counts or {}).items():
        if ext in SOURCE_EXTENSIONS:
            material[ext] = count
        elif ext in SCRIPT_EXTENSIONS and count > bar:
            material[ext] = count
    # Tier 1 first, so a high-count tier-2 entry can never evict the finding that mattered —
    # a cap that drops `.prisma` to make room for `.sql` has inverted its own purpose.
    ordered = sorted(material.items(),
                     key=lambda kv: (kv[0] not in SOURCE_EXTENSIONS, -kv[1], kv[0]))
    return dict(ordered if cap is None else ordered[:cap])


def rollup_directories(paths: Iterable[str]) -> Tuple[Dict[str, int], int]:
    """Group unread paths into the fewest directories an agent could usefully grep.

    `{".java": 12}` makes an agent derive a search target; `{"src/main/java/com/acme": 12}`
    *is* the search target. Grouped by top-level root, then collapsed to the deepest prefix
    common to everything under that root, so a package tree becomes one entry rather than four.
    """
    by_root = {}  # type: Dict[str, List[List[str]]]
    for path in paths:
        parts = (path or '').split('/')
        root = parts[0] if len(parts) > 1 else '.'
        by_root.setdefault(root, []).append(parts[:-1])

    grouped = {}  # type: Dict[str, int]
    for root, dirs in by_root.items():
        common = list(dirs[0])
        for parts in dirs[1:]:
            keep = 0
            for a, b in zip(common, parts):
                if a != b:
                    break
                keep += 1
            common = common[:keep]
        grouped['/'.join(common) if common else '.'] = len(dirs)

    ordered = sorted(grouped.items(), key=lambda kv: (-kv[1], kv[0]))
    kept = dict(ordered[:UNMAPPED_DIR_CAP])
    return kept, max(0, len(ordered) - UNMAPPED_DIR_CAP)


def unmapped_report(paths: Iterable[str], backend: Optional[str], files_graphed: int = 0,
                    readable_by: Optional[Dict[str, int]] = None,
                    truncated: bool = False,
                    error: Optional[str] = None) -> Dict[str, Any]:
    """The census block, as it is recorded in the graph artifact.

    `files` and `backend` are always present. The always-present `files: 0` is the
    discriminator that lets a reader tell "censused and clean" from "this graph predates the
    census" without bumping the schema version — which would force a rebuild everywhere and
    churn every committed behaviour fingerprint for a field nothing reads yet.
    """
    if error is not None:
        # Never a silent zero. A census that could not run is precisely the "I don't know"
        # ADR-005 exists for, and it is reported as one.
        return {'files': None, 'backend': backend, 'error': error}

    # Materialised once: `paths` is an Iterable and this function walks it twice. With a
    # generator the second pass saw nothing, so the directories rollup — the actionable half —
    # came back empty while the counts looked right.
    paths = list(paths)
    counts = {}  # type: Dict[str, int]
    for path in paths:
        ext = os.path.splitext(path)[1].lower()
        counts[ext] = counts.get(ext, 0) + 1
    # Uncapped, so the count below is the truth. Taking the total from the capped dict
    # published a number smaller than reality: on a repository with 22 unread source files
    # across 11 extensions the answer was 16, and three languages were named nowhere at all.
    # A caveat that under-reports the very thing it exists to report is worse than no caveat,
    # and this one asserted it flatly in prose — "16 source file(s) here are not in this graph".
    every = material_extensions(counts, files_graphed, cap=None)
    if not every:
        return {'files': 0, 'backend': backend}
    material = material_extensions(counts, files_graphed)
    ext_omitted = len(every) - len(material)

    kept_paths = [p for p in paths if os.path.splitext(p)[1].lower() in every]
    directories, omitted = rollup_directories(kept_paths)
    total = sum(every.values())
    exts = ', '.join(sorted(material))
    if ext_omitted:
        exts += ' and %d more' % ext_omitted
    where = ', '.join(sorted(directories))
    advice = ('%d source file(s) here are not in this graph: %r does not read %s. Every '
              'dependency, dependent and impact answer from this graph excludes them. Before '
              'concluding a change is contained, search these paths directly (grep/glob): %s.'
              % (total, backend, exts, where))
    if readable_by:
        best = sorted(readable_by.items(), key=lambda kv: (-kv[1], kv[0]))[0]
        advice += (' (%r reads %d of them — freya code-graph --use %s.)'
                   % (best[0], best[1], best[0]))

    report = {
        'files': total,
        'extensions': material,
        'directories': directories,
        'backend': backend,
        'advice': advice,
    }  # type: Dict[str, Any]
    if readable_by:
        report['readable_by'] = dict(sorted(readable_by.items()))
    if omitted:
        report['directories_omitted'] = omitted
    if ext_omitted:
        # Counted, never silently dropped — the same rule the directory cap already followed.
        # A truncation nobody is told about reads as completeness.
        report['extensions_omitted'] = ext_omitted
    if truncated:
        report['truncated'] = True
    return report


def unmapped_digest(block: Any, full: bool = False) -> Optional[Dict[str, Any]]:
    """What an answer carries, or `None` when there is nothing to say.

    `None` on a clean repository is what keeps every answer byte-identical to what it was
    before this existed — the ADR-019 discharge, enforced in one place rather than at each of
    the surfaces.
    """
    if not isinstance(block, dict):
        return None
    files = block.get('files')
    if files is None and block.get('error'):
        return {'files': None, 'error': block['error']}
    if not files:
        return None
    if full:
        return dict(block)
    # The prose and the backend recommendation ride the build payload and stderr only. This
    # digest is attached to surfaces an agent hits repeatedly in one session, where a sentence
    # that restates the structured fields is pure cost.
    digest = {'files': files,
              'extensions': dict(block.get('extensions') or {}),
              'directories': dict(block.get('directories') or {})}
    # The truncation markers are not optional detail — they are the difference between "grep
    # these two directories and you have covered it" and "grep these two of nine". Dropping
    # them presented a partial search target as a complete one, on the surfaces an agent
    # actually acts from. They cost four tokens and only when they are true.
    for key in ('directories_omitted', 'extensions_omitted', 'truncated'):
        if block.get(key):
            digest[key] = block[key]
    return digest


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
