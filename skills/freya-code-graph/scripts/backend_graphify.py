#!/usr/bin/env python3
"""The graphify backend — the second substrate, and the reason the contract exists.

`graphify` is an external, stdlib-independent tool that extracts a symbol-level graph from a
repository with no model in the loop. It reads seventeen languages where the homegrown
resolver reads four, which is the whole polyglot argument: a Java or Rust repository is
currently graphed as empty and reported as a success.

This module owns exactly one thing — translating `graphify-out/graph.json` into the shape
`substrate.py` specifies. It does not persist, validate or link `dependents`; the contract
does that for every backend (CD-19), which is what stops the second backend from having to
reimplement the first one's private methods.

**The shapes are not the same, and the mismatch is the interesting part.** graphify's nodes are
*symbols*; ours are *files*. Its links run symbol → symbol. So every link is projected onto the
file pair its endpoints live in, and the symbol names ride along as optional refinement (spec
§5: symbols refine file anchors, they never replace them).

Measured on this repository at commit 774e7f2, which is where the mapping below comes from
rather than from reading graphify's documentation:

    6,289 links out of the extractor
      417 survive the projection as cross-file edges
       73 distinct file pairs
       71 of those backed by at least one EXTRACTED link; 2 rest solely on INFERRED

Against the homegrown resolver on the same commit, that is **73 pairs against 65, losing
nothing** — the one edge homegrown has and graphify does not is `bin/installer.py →
bin/freya_cli.py`, which comes from an import statement inside a *string literal* that
installer.py writes into a generated shim. Homegrown's regexes read string bodies (backlog
item 10); graphify parses. The miss is ours.
"""

import json
import os
import shutil
import subprocess
import sys
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import settings as settings_mod  # noqa: E402
import substrate  # noqa: E402

BINARY = 'graphify'
OUTPUT_DIR = 'graphify-out'
OUTPUT_FILE = 'graph.json'

# `graphify update` re-extracts and rewrites the graph with no model involved. Measured at
# 2.4s over this repository's 136 source files, so there is no need for a cheaper path.
UPDATE_TIMEOUT_SECONDS = 900


# ---------------------------------------------------------------------------
# The mapping
# ---------------------------------------------------------------------------
#
# graphify emits eleven relations; the contract's vocabulary has five. The table below is
# derived from counting what each relation actually connects on this repository, not from its
# name. Three are dropped, and dropping them is the point rather than a limitation:
#
#   contains      1,199 links, every one of them intra-file or pointing at a non-code node.
#                 This is the *node hierarchy* — file contains symbol — not a dependency.
#   method        1,119 links, all intra-file. Class-has-method. Same thing one level down.
#   rationale_for   543 links, a `rationale` node to a `code` node, 543 of 543 intra-file and
#                 543 of 543 in `.py` files. It is a *docstring index* — the source node's
#                 label is the first line of a docstring — not a documentation graph. It does
#                 not overlap docs.json (which is doc-section → code-file, CD-7) and does not
#                 compete with it; it simply cannot express a dependency between two files.
#
# All 2,861 are 100% intra-file, which is the argument on its own: a relation that never
# crosses a file boundary cannot produce a file → file edge under any mapping. It can only
# produce self-edges, and 57.8% of the graph is this.
#
# The table below covers far more than the eleven relations a Python repository exercises,
# because **the vocabulary cannot be enumerated reliably**. Grepping graphify's own source for
# relation assignments yields 26 names — and `reads_from`, which this repository's graph
# actually contains, is not among them. Some are built somewhere a static scan does not reach.
#
# That is precisely why there is no default. An unlisted relation is counted into
# `substrate.unmapped_relations` and reported on stderr, so a capability arriving upstream
# shows up as "dropped 40 `embeds` links" rather than as a repository that looks thinner than
# it is. A silent fallthrough is the failure Phase 0 recorded against config coverage:
# "nothing, and no warning".
#
# The authority for which relations are *dependencies* is graphify's own
# `DEFAULT_AFFECTED_RELATIONS` (affected.py:12) — the vocabulary its blast-radius traversal
# walks. All fourteen are mapped here. Everything in that tuple and nothing structural: the
# same file explicitly excludes `contains` and `method` from its walk, which is independent
# confirmation of the three dropped above.
RELATIONS = {
    # Module-level dependency.
    'imports': 'imports',
    'imports_from': 'imports',
    'includes': 'imports',
    'requires': 'imports',
    'dynamic_import': 'imports',
    'crate_depends_on': 'imports',
    'depends_on': 'imports',
    're_exports': 're_exports',
    # Invocation. `instantiates` is constructing a type, which is calling its constructor.
    'calls': 'calls',
    'indirect_call': 'calls',
    'instantiates': 'calls',
    # Type hierarchy.
    'inherits': 'inherits',
    'extends': 'inherits',
    'implements': 'inherits',
    'mixes_in': 'inherits',
    # Named without being invoked.
    'references': 'references',
    'references_constant': 'references',
    'uses': 'references',
    'uses_component': 'references',
    'uses_static_prop': 'references',
    'reads_from': 'references',
    'embeds': 'references',
    'bound_to': 'references',
    # Not dependencies, and explicitly so rather than by omission — being listed here is what
    # stops them showing up in the unmapped report every single build.
    'contains': None,          # file has symbol — the node hierarchy
    'method': None,            # class has method — the same, one level down
    'binds_method': None,      # ditto
    'defines': None,           # ditto
    'rationale_for': None,     # docstring index; see above
    'cites': None,             # prose citation — docs.json owns that question (CD-7)
    'requires_env': None,      # an environment variable is not a file
    'listened_by': None,       # event wiring, not a source dependency
    'semantically_similar_to': None,   # clustering output, not a fact about the code
}

# Every kind the table can produce. Derived rather than written down twice, so a new row
# cannot claim a relation the coverage declaration then denies.
EMITTED_KINDS = tuple(k for k in substrate.RELATION_KINDS if k in set(RELATIONS.values()))

# graphify's own trust axis, which lines up with the contract's. Phase 0 recorded that the
# two-tier design was "unexercised" because no file-level edge rested solely on an INFERRED
# link. That is no longer true: measured at 774e7f2, two file pairs exist only because of
# INFERRED links, both of them duck-typed calls through an interface
# (`substrate.conformance_errors` calling `backend.coverage()`, which graphify guesses might
# reach `CodeGraph.coverage`). Exactly the speculative-but-plausible edge the tier is for.
PROVENANCE = {
    'EXTRACTED': 'extracted',
    'INFERRED': 'inferred',
}

# Only `code` nodes describe source. `document` and `rationale` are graphify's doc graph;
# `concept` is a clustering artifact.
CODE_NODE = 'code'

# A node marked `type: module` is an *external* module — `Foundation`, `express` — not a file
# in this project. It carries a `source_file` anyway, and that field is whichever project file
# the module happened to be seen in first, because graphify emits one node per module and not
# one per importer.
#
# Reading it as a file fabricates edges, and the fabrication is silent and wrong in the worst
# direction. Three Swift files that each `import Foundation` produced:
#     src/s1.swift -> src/s3.swift  (imports)
#     src/s2.swift -> src/s3.swift  (imports)
# Neither edge exists in the source. Blast radius on `s3.swift` would have claimed two files
# that have never heard of it.
#
# So a module node becomes an `external:` signal instead — which is exactly what the contract
# has for this, and what the homegrown resolver already does with `import react`.
EXTERNAL_NODE_TYPE = 'module'

# Measured, not declared. Two fixtures — one symbol per language — were extracted and these
# are the extensions that produced `code` nodes, unioned with a census of what graphify emits
# on this repository. Twenty-odd of them are languages the homegrown resolver cannot see at
# all, which is the entire reason this backend exists.
#
# Declaring this by hand at all is a compromise, and the reason is worth writing down: the
# extractor's file selection is partly *name*-based, not purely extension-based. An arbitrary
# `x.json` produces nothing while `package.json` (and `pom.xml`) produce nodes, so `.json` and
# `.xml` appear here and over-claim — a project full of unrecognised JSON would be reported as covered when it is
# not. The alternative, leaving `.json` out, under-claims on every repository that has a
# manifest, and the contract's whole purpose is to stop a backend under-reporting what it saw.
# Over-claiming is the direction where the graph merely looks emptier than expected; under-
# claiming is the direction where a missing file looks like an absent dependency.
EXTENSIONS = (
    '.bash', '.c', '.cjs', '.cpp', '.cs', '.dart', '.ex', '.go', '.h', '.hpp',
    '.java', '.js', '.json', '.jsx', '.kt', '.lua', '.mjs', '.mts', '.php', '.ps1',
    '.py', '.rb', '.rs', '.scala', '.sh', '.sql', '.svelte', '.swift', '.tf',
    '.ts', '.tsx', '.vue', '.xml', '.zig',
)

# Extensions this backend declares but whose selection is *name*-based, so the declaration
# knowingly over-claims: `package.json` produces nodes and an arbitrary `x.json` produces
# nothing. Declaring them is still right — under-reporting what a backend saw is the failure
# the contract exists to prevent — but they must not be used as evidence that a project would
# gain from switching, because almost every repository contains one.
OVER_CLAIMED_EXTENSIONS = ('.json', '.xml')

LANGUAGES = (
    'c', 'cpp', 'csharp', 'dart', 'elixir', 'go', 'java', 'javascript', 'json',
    'kotlin', 'lua', 'php', 'powershell', 'python', 'ruby', 'rust', 'scala',
    'shell', 'sql', 'svelte', 'swift', 'terraform', 'typescript', 'vue', 'xml', 'zig',
)

_LANGUAGE_BY_EXT = {
    '.bash': 'shell', '.c': 'c', '.cjs': 'javascript', '.cpp': 'cpp', '.cs': 'csharp',
    '.dart': 'dart', '.ex': 'elixir', '.go': 'go', '.h': 'c', '.hpp': 'cpp',
    '.java': 'java', '.js': 'javascript', '.json': 'json', '.jsx': 'javascript',
    '.kt': 'kotlin', '.lua': 'lua', '.mjs': 'javascript', '.mts': 'typescript',
    '.php': 'php', '.ps1': 'powershell', '.py': 'python', '.rb': 'ruby', '.rs': 'rust',
    '.scala': 'scala', '.sh': 'shell', '.sql': 'sql', '.svelte': 'svelte',
    '.swift': 'swift', '.tf': 'terraform', '.ts': 'typescript', '.tsx': 'typescript',
    '.vue': 'vue', '.xml': 'xml', '.zig': 'zig',
}


class GraphifyUnavailable(RuntimeError):
    """graphify could not produce a graph. The caller degrades; it does not crash."""


class GraphifyBackend:
    """freya's polyglot backend, behind the substrate contract."""

    name = 'graphify'
    over_claimed = OVER_CLAIMED_EXTENSIONS

    def __init__(self, project_dir: Optional[str] = None):
        self.project_dir = os.path.abspath(project_dir or os.getcwd())
        self.graph = {}  # type: Dict[str, Any]

    # -- contract ----------------------------------------------------------

    def available(self) -> bool:
        """Is the binary on PATH?

        Deliberately only that. `available()` runs during selection on every build, so it must
        not cost a subprocess; and a graphify that is installed but broken is a *runtime*
        failure, which `build()` reports honestly rather than something to pre-empt here.
        """
        return shutil.which(BINARY) is not None

    def coverage(self) -> substrate.Coverage:
        """What this backend reads, and which relations it emits.

        `relations` is derived from the mapping table, so adding a row cannot leave the
        declaration claiming less — or more — than the projection can actually emit. That is
        the per-backend difference `Coverage` exists to express (CD-16): a caller needing
        `calls` can see that this backend has them and the homegrown one does not.
        """
        return substrate.Coverage(
            languages=LANGUAGES,
            extensions=EXTENSIONS,
            relations=EMITTED_KINDS,
            # Measured, not assumed. A file deleted between runs loses its nodes and its
            # links — verified at both 1-of-2 and 19-of-20 files removed, the second being
            # well past the shrink guard that `--force` exists to override.
            incremental=True,
        )

    def build(self, ai_response: Optional[str] = None, non_interactive: bool = False,
              exclusions: Optional[substrate.Exclusions] = None,
              selection_metadata: Optional[Dict[str, Any]] = None) -> substrate.Result:
        """Extract, then project onto the contract. Produces; `run_build` persists."""
        raw = self._extract()
        graph = self.translate(raw, exclusions=exclusions,
                               selection_metadata=selection_metadata,
                               symbols=self._symbols_requested())
        self.graph = graph
        return substrate.Result(graph, substrate.Result.BUILT)

    def update(self, non_interactive: bool = False,
               exclusions: Optional[substrate.Exclusions] = None,
               selection_metadata: Optional[Dict[str, Any]] = None) -> substrate.Result:
        """The same extraction. `graphify update` *is* the incremental path.

        It caches per file and drops deleted ones, so there is no cheaper correct route and no
        reason to keep a second one. A full re-projection also means the artifact is always
        written at the current schema, so the staleness rebuild in `CodeGraph.update` has no
        equivalent here.
        """
        previous = substrate.load_graph(substrate.active_graph_path(self.project_dir)) or {}
        result = self.build(non_interactive=non_interactive, exclusions=exclusions,
                            selection_metadata=selection_metadata)
        changed = _changed_files(previous.get('files') or {}, result.graph.get('files') or {})
        if not changed and previous.get('files'):
            return substrate.Result(result.graph, substrate.Result.UP_TO_DATE, 0)
        return substrate.Result(result.graph, substrate.Result.UPDATED, changed)

    # -- extraction --------------------------------------------------------

    def _symbols_requested(self) -> bool:
        """Does this project want symbol refinement on its edges? (Phase 3, opt-in.)"""
        try:
            return settings_mod.load(self.project_dir).symbols
        except Exception:
            # Configuration must never be the reason a build fails; the floor behaviour —
            # file-level edges — is the correct answer either way.
            return False

    def output_path(self) -> str:
        return os.path.join(self.project_dir, OUTPUT_DIR, OUTPUT_FILE)

    def _extract(self) -> Dict[str, Any]:
        """Run graphify and read what it wrote.

        Every failure becomes `GraphifyUnavailable` with the tool's own stderr attached. The
        caller degrades to the floor and records that it did — a backend failing must never be
        the reason a project has no graph, because the floor was what it would have used
        anyway.
        """
        if not self.available():
            raise GraphifyUnavailable('%r is not on PATH' % BINARY)
        try:
            proc = subprocess.run(
                [BINARY, 'update', self.project_dir],
                cwd=self.project_dir, capture_output=True, text=True,
                timeout=UPDATE_TIMEOUT_SECONDS,
            )
        except subprocess.TimeoutExpired:
            raise GraphifyUnavailable(
                '%r did not finish within %ds' % (BINARY, UPDATE_TIMEOUT_SECONDS))
        except OSError as exc:
            raise GraphifyUnavailable('%r could not be run (%s)' % (BINARY, exc))

        if proc.returncode != 0:
            tail = (proc.stderr or proc.stdout or '').strip().splitlines()
            raise GraphifyUnavailable(
                '%r exited %d: %s' % (BINARY, proc.returncode,
                                      tail[-1] if tail else 'no output'))

        path = self.output_path()
        try:
            with open(path, encoding='utf-8') as handle:
                raw = json.load(handle)
        except OSError:
            # It reported success and wrote nothing. Exactly the failure the contract's
            # obligation 2 is about, so it is raised rather than translated into an empty
            # graph that would look like a repository with no code in it.
            raise GraphifyUnavailable('%r exited 0 but wrote no %s' % (BINARY, path))
        except ValueError as exc:
            raise GraphifyUnavailable('%s is not valid JSON (%s)' % (path, exc))
        if not isinstance(raw, dict):
            raise GraphifyUnavailable('%s is not an object' % path)
        return raw

    # -- projection --------------------------------------------------------

    def translate(self, raw: Dict[str, Any],
                  exclusions: Optional[substrate.Exclusions] = None,
                  selection_metadata: Optional[Dict[str, Any]] = None,
                  symbols: bool = False) -> Dict[str, Any]:
        """graphify's symbol graph, projected onto the contract's file graph.

        `symbols=True` keeps each edge's endpoints distinct by symbol name, which turns 73 file
        pairs into 417 edges on this repository. That is Phase 3's refinement and it is off by
        default here, so Phase 2's artifact is file-level exactly as spec §5 requires.
        """
        nodes, external = self._index_nodes(raw, exclusions)
        files = {}  # type: Dict[str, Dict[str, Any]]
        for info in nodes.values():
            files.setdefault(info[0], {
                'exports': [],
                'imports': [],
                'dependents': [],
                'language': _LANGUAGE_BY_EXT.get(os.path.splitext(info[0])[1].lower()),
            })

        seen = set()  # type: set
        unmapped = {}  # type: Dict[str, int]
        misdirected = 0
        for link in raw.get('links') or []:
            if isinstance(link, dict):
                relation = link.get('relation')
                if relation not in RELATIONS:
                    unmapped[str(relation)] = unmapped.get(str(relation), 0) + 1
                if self._misdirected(link, nodes):
                    misdirected += 1
            edge = self._project(link, nodes, external, symbols=symbols)
            if edge is None:
                continue
            source, payload, key = edge
            if key in seen:
                continue
            seen.add(key)
            files[source]['imports'].append(payload)

        for info in files.values():
            info['imports'].sort(key=lambda e: (e['to'], e['kind'],
                                                e.get('from_symbol') or '',
                                                e.get('to_symbol') or ''))

        metadata = substrate.graph_metadata(
            self.name, self.coverage(), exclusions,
            degraded_from=(selection_metadata or {}).get('degraded_from'),
            degraded_reason=(selection_metadata or {}).get('degraded_reason'))
        if unmapped:
            # Reported, not defaulted. A relation this table has never seen is a capability
            # arriving, and the graph should say it was dropped rather than let a caller infer
            # from a thin result that the repository is thin.
            metadata['unmapped_relations'] = dict(sorted(unmapped.items()))
            print('code-graph: graphify emitted %d relation(s) this backend does not map (%s);'
                  ' they are recorded under substrate.unmapped_relations and dropped.'
                  % (sum(unmapped.values()), ', '.join(sorted(unmapped))), file=sys.stderr)
        if misdirected:
            # graphify writes `directed: false`, so the source/target field order is the only
            # carrier of direction. Phase 0 measured what losing it costs: reading the graph as
            # undirected took mean blast radius from 5 files to 188. Each link also repeats its
            # own `source_file`, which gives a free cross-check on that field order — if the two
            # ever disagree, the assumption this backend rests on has broken.
            metadata['direction_warnings'] = misdirected
            print('code-graph: %d graphify link(s) disagree with their own source_file; edge '
                  'direction may be unreliable in this graph.' % misdirected, file=sys.stderr)

        return {
            'version': substrate.GRAPH_SCHEMA_VERSION,
            'commit': raw.get('built_at_commit') or self._git_commit(),
            'timestamp': datetime.now(timezone.utc).isoformat(),
            'project_root': self.project_dir,
            'substrate': metadata,
            'files': files,
        }

    def _index_nodes(self, raw: Dict[str, Any],
                     exclusions: Optional[substrate.Exclusions]
                     ) -> Tuple[Dict[str, Tuple[str, str, Optional[int]]], Dict[str, str]]:
        """node id -> (source_file, label, line), for code nodes that are in scope.

        Exclusions are applied here, as a post-filter. `graphify update` takes no exclusion
        flag — verified against its `--help` and by watching it index `node_modules/` — so
        obligation 6 has to be honoured on the way out rather than on the way in. That answers
        spec open question 3, which had left the mechanism undecided.
        """
        owners = self._method_owners(raw)
        index = {}    # node id -> (file, symbol, line)
        external = {}  # node id -> 'external:<module>'
        for node in raw.get('nodes') or []:
            if not isinstance(node, dict) or node.get('file_type') != CODE_NODE:
                continue
            node_id = node.get('id')
            if not isinstance(node_id, str) or not node_id:
                continue
            label = node.get('label')
            label = label if isinstance(label, str) else ''
            if node.get('type') == EXTERNAL_NODE_TYPE:
                # Its `source_file` is a coincidence of which importer was parsed first.
                external[node_id] = 'external:%s' % (label or node_id)
                continue
            source_file = node.get('source_file')
            if not isinstance(source_file, str) or not source_file:
                continue
            key = source_file.replace('\\', '/').lstrip('/')
            if exclusions is not None and exclusions.excludes(key):
                continue
            index[node_id] = (key, owners.get(node_id, label),
                              _line(node.get('source_location')))
        return index, external

    @staticmethod
    def _method_owners(raw: Dict[str, Any]) -> Dict[str, str]:
        """node id -> `Class.method()`, for every method the graph names.

        graphify labels a method with its own name only — `.setUp()`, `._run()` — and the
        owning class reaches it through a `method` link. Measured on this repository, **64 of
        1,731 code symbols share a bare label with a sibling in the same file**: three
        different `._run()` in one test module, and so on. Qualifying with the owner takes
        that to zero.

        Which is why `method` is dropped as an *edge* and kept as a *lookup*. It is not a
        dependency — it never crosses a file boundary — but it is the only thing that makes
        Phase 3's symbol names identify a symbol rather than merely describe one.
        """
        labels = {n.get('id'): n.get('label') for n in (raw.get('nodes') or [])
                  if isinstance(n, dict)}
        owners = {}  # type: Dict[str, str]
        for link in raw.get('links') or []:
            if not isinstance(link, dict) or link.get('relation') != 'method':
                continue
            owner = labels.get(link.get('source'))
            member = labels.get(link.get('target'))
            if isinstance(owner, str) and isinstance(member, str) and owner and member:
                # Method labels already begin with '.', so this composes to `Class.method()`.
                owners[link['target']] = owner + member if member.startswith('.') \
                    else '%s.%s' % (owner, member)
        return owners

    def _project(self, link: Any, nodes: Dict[str, Tuple[str, str, Optional[int]]],
                 external: Dict[str, str],
                 symbols: bool) -> Optional[Tuple[str, Dict[str, Any], tuple]]:
        """One symbol → symbol link as one file → file edge, or None if it is not one."""
        if not isinstance(link, dict):
            return None
        relation = link.get('relation')
        if not isinstance(relation, str) or RELATIONS.get(relation) is None:
            return None
        kind = RELATIONS[relation]
        source = nodes.get(link.get('source'))
        if source is None:
            return None

        outside = external.get(link.get('target'))
        if outside is not None:
            # A third-party module. Recorded, not dropped: `external:` is how the contract
            # says "this dependency is real and is not ours", and losing it would understate
            # what the file depends on.
            payload = substrate.make_edge(
                outside, kind=kind,
                provenance=PROVENANCE.get(link.get('confidence'), 'inferred'))
            return source[0], payload, (source[0], outside, kind, None, None)

        target = nodes.get(link.get('target'))
        if target is None:
            return None
        if source[0] == target[0]:
            # A file-level self-edge. 1,475 of graphify's `calls` links on this repository are
            # intra-file, and every one of them would make a file its own dependent — blast
            # radius walks these edges, so a file would always be in its own blast radius.
            #
            # The information is real and is not being thrown away for tidiness: spec §5 says a
            # symbol *refines a file anchor*, and an intra-file call has no file anchor pair to
            # refine. Recording the intra-file call graph needs a node type we do not have.
            # Backlog, not silently lost.
            return None

        extra = {}  # type: Dict[str, Any]
        if symbols:
            if source[1]:
                extra['from_symbol'] = source[1]
            if target[1]:
                extra['to_symbol'] = target[1]
            line = _line(link.get('source_location'))
            if line is not None:
                extra['line'] = line

        payload = substrate.make_edge(
            target[0], kind=kind,
            provenance=PROVENANCE.get(link.get('confidence'), 'inferred'),
            **extra)
        key = (source[0], target[0], kind,
               extra.get('from_symbol'), extra.get('to_symbol'))
        return source[0], payload, key

    @staticmethod
    def _misdirected(link: Dict[str, Any],
                     nodes: Dict[str, Tuple[str, str, Optional[int]]]) -> bool:
        """Does a link's own `source_file` disagree with its source node's?

        A free consistency check on the one assumption this whole projection rests on. It is
        counted rather than raised: one odd link is not a reason to refuse a graph, but a
        graph full of them means direction is no longer readable and the caller must be told.
        """
        stated = link.get('source_file')
        source = nodes.get(link.get('source'))
        if source is None or not isinstance(stated, str) or not stated:
            return False
        return stated.replace('\\', '/').lstrip('/') != source[0]

    def _git_commit(self) -> Optional[str]:
        try:
            proc = subprocess.run(['git', 'rev-parse', 'HEAD'], cwd=self.project_dir,
                                  capture_output=True, text=True)
        except OSError:
            return None
        return proc.stdout.strip()[:12] if proc.returncode == 0 else None


def _changed_files(before: Dict[str, Any], after: Dict[str, Any]) -> int:
    """How many file entries differ between two graphs.

    Reported as `files_changed`, which `format_summary` prints as "N files changed since last
    build". It used to be the *total* file count, so an update over untouched source announced
    that the entire repository had changed — and anything that trusts the number (wrap-up,
    status) would have believed it.

    Counted by diffing entries rather than asking git, because this backend re-extracts
    everything anyway: the diff is what actually moved, which is a better answer than what git
    says was touched.

    `dependents` is excluded from the comparison. It is derived by the contract *after* the
    backend returns, so the persisted graph has it and a freshly produced one does not — and
    comparing whole entries therefore reported every file with an incoming edge as changed.
    Thirty of sixty-seven, on an update run seconds after the build it was compared against.
    """
    def produced(entry):
        return {k: v for k, v in (entry or {}).items() if k != 'dependents'}

    keys = set(before) | set(after)
    return sum(1 for key in keys if produced(before.get(key)) != produced(after.get(key)))


def _line(location: Any) -> Optional[int]:
    """graphify writes a location as `L265`. Anything else is no line rather than a guess."""
    if not isinstance(location, str) or not location.startswith('L'):
        return None
    try:
        return int(location[1:])
    except ValueError:
        return None
