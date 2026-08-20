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
#   rationale_for   543 links, every endpoint a `rationale` or `document` node. This is
#                 graphify's own documentation graph. We have one of those (docs.json, CD-7),
#                 built from citations we control; adopting a second would give two answers to
#                 "which docs describe this file".
#
# Emitting any of the three as a dependency edge would put 2,861 structural facts into a blast
# radius that is meant to answer "what breaks if I change this file".
RELATIONS = {
    'imports': 'imports',
    'imports_from': 'imports',
    'calls': 'calls',
    'indirect_call': 'calls',
    'inherits': 'inherits',
    'references': 'references',
    'uses': 'references',
    'reads_from': 'references',
    # Structural, deliberately unmapped — see above.
    'contains': None,
    'method': None,
    'rationale_for': None,
}

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

# Measured, not declared. Two fixtures — one symbol per language — were extracted and these
# are the extensions that produced `code` nodes, unioned with a census of what graphify emits
# on this repository. Twenty-odd of them are languages the homegrown resolver cannot see at
# all, which is the entire reason this backend exists.
#
# Declaring this by hand at all is a compromise, and the reason is worth writing down: the
# extractor's file selection is partly *name*-based, not purely extension-based. An arbitrary
# `x.json` produces nothing while `package.json` produces nodes, so `.json` appears here and
# over-claims — a project full of unrecognised JSON would be reported as covered when it is
# not. The alternative, leaving `.json` out, under-claims on every repository that has a
# manifest, and the contract's whole purpose is to stop a backend under-reporting what it saw.
# Over-claiming is the direction where the graph merely looks emptier than expected; under-
# claiming is the direction where a missing file looks like an absent dependency.
EXTENSIONS = (
    '.bash', '.c', '.cjs', '.cpp', '.cs', '.dart', '.ex', '.go', '.h', '.hpp',
    '.java', '.js', '.json', '.jsx', '.kt', '.lua', '.mjs', '.mts', '.php', '.ps1',
    '.py', '.rb', '.rs', '.scala', '.sh', '.sql', '.svelte', '.swift', '.tf',
    '.ts', '.tsx', '.vue', '.zig',
)

LANGUAGES = (
    'c', 'cpp', 'csharp', 'dart', 'elixir', 'go', 'java', 'javascript', 'json',
    'kotlin', 'lua', 'php', 'powershell', 'python', 'ruby', 'rust', 'scala',
    'shell', 'sql', 'svelte', 'swift', 'terraform', 'typescript', 'vue', 'zig',
)

_LANGUAGE_BY_EXT = {
    '.bash': 'shell', '.c': 'c', '.cjs': 'javascript', '.cpp': 'cpp', '.cs': 'csharp',
    '.dart': 'dart', '.ex': 'elixir', '.go': 'go', '.h': 'c', '.hpp': 'cpp',
    '.java': 'java', '.js': 'javascript', '.json': 'json', '.jsx': 'javascript',
    '.kt': 'kotlin', '.lua': 'lua', '.mjs': 'javascript', '.mts': 'typescript',
    '.php': 'php', '.ps1': 'powershell', '.py': 'python', '.rb': 'ruby', '.rs': 'rust',
    '.scala': 'scala', '.sh': 'shell', '.sql': 'sql', '.svelte': 'svelte',
    '.swift': 'swift', '.tf': 'terraform', '.ts': 'typescript', '.tsx': 'typescript',
    '.vue': 'vue', '.zig': 'zig',
}


class GraphifyUnavailable(RuntimeError):
    """graphify could not produce a graph. The caller degrades; it does not crash."""


class GraphifyBackend:
    """freya's polyglot backend, behind the substrate contract."""

    name = 'graphify'

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

        `relations` omits `re_exports`: graphify has no relation that means it, and claiming a
        kind a backend cannot emit is how a caller ends up trusting a query that always comes
        back empty. The homegrown backend claims it and this one does not, which is precisely
        the per-backend difference `Coverage` exists to express (CD-16).
        """
        return substrate.Coverage(
            languages=LANGUAGES,
            extensions=EXTENSIONS,
            relations=('imports', 'calls', 'inherits', 'references'),
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
                               selection_metadata=selection_metadata)
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
        result = self.build(non_interactive=non_interactive, exclusions=exclusions,
                            selection_metadata=selection_metadata)
        return substrate.Result(result.graph, substrate.Result.UPDATED,
                                len(result.graph.get('files') or {}))

    # -- extraction --------------------------------------------------------

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
        nodes = self._index_nodes(raw, exclusions)
        files = {}  # type: Dict[str, Dict[str, Any]]
        for info in nodes.values():
            files.setdefault(info[0], {
                'exports': [],
                'imports': [],
                'dependents': [],
                'language': _LANGUAGE_BY_EXT.get(os.path.splitext(info[0])[1].lower()),
            })

        seen = set()  # type: set
        for link in raw.get('links') or []:
            edge = self._project(link, nodes, symbols=symbols)
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

        return {
            'version': substrate.GRAPH_SCHEMA_VERSION,
            'commit': raw.get('built_at_commit') or self._git_commit(),
            'timestamp': datetime.now(timezone.utc).isoformat(),
            'project_root': self.project_dir,
            'substrate': substrate.graph_metadata(
                self.name, self.coverage(), exclusions,
                degraded_from=(selection_metadata or {}).get('degraded_from'),
                degraded_reason=(selection_metadata or {}).get('degraded_reason')),
            'files': files,
        }

    def _index_nodes(self, raw: Dict[str, Any],
                     exclusions: Optional[substrate.Exclusions]
                     ) -> Dict[str, Tuple[str, str, Optional[int]]]:
        """node id -> (source_file, label, line), for code nodes that are in scope.

        Exclusions are applied here, as a post-filter. `graphify update` takes no exclusion
        flag — verified against its `--help` and by watching it index `node_modules/` — so
        obligation 6 has to be honoured on the way out rather than on the way in. That answers
        spec open question 3, which had left the mechanism undecided.
        """
        index = {}
        for node in raw.get('nodes') or []:
            if not isinstance(node, dict) or node.get('file_type') != CODE_NODE:
                continue
            source_file = node.get('source_file')
            node_id = node.get('id')
            if not isinstance(source_file, str) or not source_file or not node_id:
                continue
            key = source_file.replace('\\', '/').lstrip('/')
            if exclusions is not None and exclusions.excludes(key):
                continue
            index[node_id] = (key, node.get('label') or '', _line(node.get('source_location')))
        return index

    def _project(self, link: Any, nodes: Dict[str, Tuple[str, str, Optional[int]]],
                 symbols: bool) -> Optional[Tuple[str, Dict[str, Any], tuple]]:
        """One symbol → symbol link as one file → file edge, or None if it is not one."""
        if not isinstance(link, dict):
            return None
        kind = RELATIONS.get(link.get('relation'))
        if kind is None:
            return None
        source = nodes.get(link.get('source'))
        target = nodes.get(link.get('target'))
        if source is None or target is None:
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

    def _git_commit(self) -> Optional[str]:
        try:
            proc = subprocess.run(['git', 'rev-parse', 'HEAD'], cwd=self.project_dir,
                                  capture_output=True, text=True)
        except OSError:
            return None
        return proc.stdout.strip()[:12] if proc.returncode == 0 else None


def _line(location: Any) -> Optional[int]:
    """graphify writes a location as `L265`. Anything else is no line rather than a guess."""
    if not isinstance(location, str) or not location.startswith('L'):
        return None
    try:
        return int(location[1:])
    except ValueError:
        return None
