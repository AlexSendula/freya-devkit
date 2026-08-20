#!/usr/bin/env python3
"""The graphify backend — the second substrate, and the reason the contract exists.

`graphify` is an external, stdlib-independent tool that extracts a symbol-level graph from a
repository with no model in the loop. It reads ninety-three file extensions across forty
languages where the homegrown resolver reads six across four, which is the whole polyglot
argument: a Java or Rust repository is otherwise graphed as empty and reported as a success.

This module owns exactly one thing — translating `graphify-out/graph.json` into the shape
`substrate.py` specifies. It does not persist, validate or link `dependents`; the contract
does that for every backend (ADR-020), which is what stops the second backend from having to
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
#                 not overlap docs.json (which is doc-section → code-file, ADR-026) and does not
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
    'cites': None,             # prose citation — docs.json owns that question (ADR-026)
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

# Node types that are *aggregate anchors*, not files. Each carries a `source_file` anyway,
# and that field is whichever project file the thing happened to be seen in first — graphify
# emits one node per module and per namespace, not one per file that mentions it.
#
# Reading one as a file fabricates edges, silently and in the worst direction. Three Swift
# files that each `import Foundation` produced:
#     src/s1.swift -> src/s3.swift  (imports)
#     src/s2.swift -> src/s3.swift  (imports)
# Neither edge exists in the source. Blast radius on `s3.swift` would have claimed two files
# that have never heard of it.
#
# `namespace` is the same shape one language over: graphify canonicalises C# namespaces to one
# node per label across every file that declares it, so `using App.Core;` in twenty files
# resolves to whichever `.cs` file was parsed first. It was missed when `module` was fixed
# because the fix enumerated the case it had seen rather than the class it belonged to.
# graphify's own resolver skips namespace nodes in two places for the same reason.
#
# `package` deliberately stays a file: its `source_file` is the manifest it was parsed from —
# a real path — and graphify prunes dependency edges whose target manifest is not in the
# corpus, so `packages/a/package.json -> packages/b/package.json` is a true statement about
# two files that exist.
#
# An anchor becomes an `external:` signal instead, which is exactly what the contract has for
# "a real dependency that is not a file of ours", and what the homegrown resolver already does
# with `import react`.
ANCHOR_NODE_TYPES = ('module', 'namespace')

# Derived from graphify's own suffix dispatch table (`extract._DISPATCH`), not hand-written
# from what two fixtures happened to produce. The hand-written version declared 34 of the 93
# extensions graphify has real extractors for, and the 59 it left out failed in the direction
# the comment below calls the dangerous one: a `.groovy`, `.kts`, `.f90` or `.razor` file that
# graphify *did* parse was written into the artifact, reported by `validate_graph` as
# "outside the declared coverage", and given `language: null`. A backend contradicting its own
# coverage block on files it successfully read is the one thing that block cannot survive.
#
# `extract_markdown`'s extensions (`.md`, `.mdx`, `.qmd`, `.skill`) are deliberately excluded:
# they produce `document` and `rationale` nodes, which this projection filters out. Declaring
# them would claim coverage of files that can never appear in the graph — which is the *other*
# failure, "no docs edges" made indistinguishable from "we do not read docs". docs.json (ADR-026)
# owns that question.
#
# Two extensions are still name-based rather than suffix-based, and they knowingly over-claim:
# `package.json` and `pom.xml` produce nodes while an arbitrary `x.json` or `x.xml` produces
# nothing. Declaring them is still right — under-reporting what a backend saw is the failure
# the contract exists to prevent — but they are listed in `OVER_CLAIMED_EXTENSIONS` so they
# are never used as evidence that a project would gain from switching.
#
# Pinned by a test that reads `_DISPATCH` out of graphify's own interpreter, the same way the
# relation table is pinned against `DEFAULT_AFFECTED_RELATIONS`. A hand-maintained mirror of
# somebody else's registry drifts silently; one that fails the build when it drifts does not.
EXTENSIONS = (
    '.asd', '.astro', '.bash', '.c', '.cc', '.cjs', '.cl', '.cls', '.cpp', '.cs',
    '.cshtml', '.csproj', '.cts', '.cu', '.cuh', '.cxx', '.dart', '.dfm', '.dm', '.dme',
    '.dmf', '.dmi', '.dmm', '.dpk', '.dpr', '.ex', '.exs', '.f', '.f03', '.f08', '.f90',
    '.f95', '.fsproj', '.go', '.gradle', '.groovy', '.h', '.hcl', '.hpp', '.inc', '.java',
    '.jl', '.js', '.json', '.jsx', '.kt', '.kts', '.lfm', '.lisp', '.lpk', '.lpr', '.lsp',
    '.lua', '.luau', '.m', '.metal', '.mjs', '.ml', '.mli', '.mm', '.mts', '.pas', '.php',
    '.pp', '.ps1', '.psd1', '.psm1', '.py', '.rake', '.razor', '.rb', '.rs', '.scala',
    '.sh', '.sln', '.slnx', '.sql', '.sv', '.svelte', '.svh', '.swift', '.tf', '.tfvars',
    '.toc', '.trigger', '.ts', '.tsx', '.v', '.vbproj', '.vue', '.xaml', '.xml', '.zig',
)

# Extensions graphify dispatches to a *document* extractor. Excluded from the declaration
# above rather than forgotten — naming them here is what stops the next person "fixing" the
# gap by adding them back.
DOCUMENT_EXTENSIONS = ('.md', '.mdx', '.qmd', '.skill')

# Extensions this backend declares but whose selection is *name*-based, so the declaration
# knowingly over-claims: `package.json` produces nodes and an arbitrary `x.json` produces
# nothing. Declaring them is still right — under-reporting what a backend saw is the failure
# the contract exists to prevent — but they must not be used as evidence that a project would
# gain from switching, because almost every repository contains one.
OVER_CLAIMED_EXTENSIONS = ('.json', '.xml')

LANGUAGES = (
    'apex', 'astro', 'c', 'commonlisp', 'cpp', 'csharp', 'dart', 'dm', 'elixir', 'fortran',
    'go', 'groovy', 'java', 'javascript', 'json', 'julia', 'kotlin', 'lua', 'msbuild',
    'objectivec', 'ocaml', 'pascal', 'php', 'powershell', 'python', 'razor', 'ruby',
    'rust', 'scala', 'shell', 'sql', 'svelte', 'swift', 'terraform', 'typescript',
    'verilog', 'vue', 'xaml', 'xml', 'zig',
)

# One name per extension, for the per-file `language` field. graphify's own dispatch groups
# by *extractor*, which is coarser than what a reader wants: `extract_js` handles `.ts` and
# `.js` alike, and labelling a TypeScript file `javascript` is a worse answer than the
# question deserves. So the extractor is the authority for *which* extensions exist and this
# table is the authority for what to call them.
_LANGUAGE_BY_EXT = {
    '.asd': 'commonlisp', '.astro': 'astro', '.bash': 'shell', '.c': 'c', '.cc': 'cpp',
    '.cjs': 'javascript', '.cl': 'commonlisp', '.cls': 'apex', '.cpp': 'cpp',
    '.cs': 'csharp', '.cshtml': 'razor', '.csproj': 'msbuild', '.cts': 'typescript',
    '.cu': 'cpp', '.cuh': 'cpp', '.cxx': 'cpp', '.dart': 'dart', '.dfm': 'pascal',
    '.dm': 'dm', '.dme': 'dm', '.dmf': 'dm', '.dmi': 'dm', '.dmm': 'dm', '.dpk': 'pascal',
    '.dpr': 'pascal', '.ex': 'elixir', '.exs': 'elixir', '.f': 'fortran',
    '.f03': 'fortran', '.f08': 'fortran', '.f90': 'fortran', '.f95': 'fortran',
    '.fsproj': 'msbuild', '.go': 'go', '.gradle': 'groovy', '.groovy': 'groovy', '.h': 'c',
    '.hcl': 'terraform', '.hpp': 'cpp', '.inc': 'pascal', '.java': 'java', '.jl': 'julia',
    '.js': 'javascript', '.json': 'json', '.jsx': 'javascript', '.kt': 'kotlin',
    '.kts': 'kotlin', '.lfm': 'pascal', '.lisp': 'commonlisp', '.lpk': 'pascal',
    '.lpr': 'pascal', '.lsp': 'commonlisp', '.lua': 'lua', '.luau': 'lua',
    '.m': 'objectivec', '.metal': 'cpp', '.mjs': 'javascript', '.ml': 'ocaml',
    '.mli': 'ocaml', '.mm': 'objectivec', '.mts': 'typescript', '.pas': 'pascal',
    '.php': 'php', '.pp': 'pascal', '.ps1': 'powershell', '.psd1': 'powershell',
    '.psm1': 'powershell', '.py': 'python', '.rake': 'ruby', '.razor': 'razor',
    '.rb': 'ruby', '.rs': 'rust', '.scala': 'scala', '.sh': 'shell', '.sln': 'msbuild',
    '.slnx': 'msbuild', '.sql': 'sql', '.sv': 'verilog', '.svelte': 'svelte',
    '.svh': 'verilog', '.swift': 'swift', '.tf': 'terraform', '.tfvars': 'terraform',
    '.toc': 'lua', '.trigger': 'apex', '.ts': 'typescript', '.tsx': 'typescript',
    '.v': 'verilog', '.vbproj': 'msbuild', '.vue': 'vue', '.xaml': 'xaml', '.xml': 'xml',
    '.zig': 'zig',
}


# `graphify update` writes its extraction, an HTML viewer, a cache and dated backups into
# `graphify-out/` at the project *root* — outside `knowledge-base/`, which is the only place
# this toolkit's own ignore rules reach. Nothing marked it, so the first build in an adopting
# project left a multi-megabyte generated tree that `git add -A` stages: verified on a fresh
# repository, `graphify-out/graph.json` was staged alongside the source.
#
# That is the same defect this repository already fixed once, for `graph.<backend>.json`, and
# it recurred one directory over at ~9.3 KB per file. Opting into a backend must not quietly
# make a cache committable.
#
# `*` rather than a list of names, because the whole directory is graphify's regenerable
# output and we do not own its filenames — enumerating them would go stale the first time it
# writes something new, which is exactly how the last one happened.
OUTPUT_GITIGNORE = (
    '# graphify\'s extraction output — regenerable, not committed.\n'
    '# Written by freya-code-graph\'s graphify backend. Delete this file to keep the\n'
    '# directory; it is only rewritten when it is absent or unchanged from this text.\n'
    '*\n'
)


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
        the per-backend difference `Coverage` exists to express (ADR-018): a caller needing
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

        # "Nothing changed" is about the *source*, and it is not the only reason to write.
        # An artifact from an older schema, or from a different backend, has to be replaced
        # whatever the source did — and reporting `up_to_date` over one left it in place
        # indefinitely, since every later update reached this same short-circuit. A
        # pre-substrate artifact stayed permanently without a `substrate` block: no backend,
        # no coverage, and therefore no way to tell a thin graph from a thin repo, which is
        # the whole point of the block.
        obsolete = bool(previous) and (substrate.is_stale(previous)
                                       or substrate.produced_by(previous) != self.name)
        if not changed and previous.get('files') and not obsolete:
            # The graph *on disk*, not the one just built. Nothing is written on this path,
            # so the only thing the returned graph is used for is the contract's staleness
            # check — and handing it a freshly-built v2 graph made that check answer about
            # something other than the artifact it was asked about.
            return substrate.Result(previous, substrate.Result.UP_TO_DATE, 0)
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

    def _mark_output_ignored(self) -> None:
        """Keep `graphify-out/` out of the project's commits. Never fails a build.

        Written after the tool has run, because the directory is graphify's to create. A
        file that is present and is not ours was edited by hand and is left alone — the
        same rule the cache directory's own marker follows, and for the same reason: a
        project that has deliberately changed it should not have that undone every build.
        """
        marker = os.path.join(self.project_dir, OUTPUT_DIR, '.gitignore')
        try:
            if os.path.exists(marker):
                with open(marker, encoding='utf-8') as handle:
                    if handle.read() != OUTPUT_GITIGNORE:
                        return
            elif not os.path.isdir(os.path.dirname(marker)):
                return
            with open(marker, 'w', encoding='utf-8') as handle:
                handle.write(OUTPUT_GITIGNORE)
        except OSError:
            # A cache marker is not worth failing a build over; the graph is the product.
            pass

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

        self._mark_output_ignored()

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

        # A shape assertion, not a heuristic. This projection reads exactly two keys, and
        # `nodes` without `links` is what an upstream rename of the edge container looks
        # like from here: every file still present, every edge gone, `status: built`, exit
        # 0. `_refuse_to_erase` cannot catch it — the file set is full — so the graph would
        # be written and every blast radius in the project would quietly become empty.
        #
        # A genuinely edgeless repository is not caught by this: graphify writes
        # `"links": []`, which is a list and passes.
        if raw.get('nodes') and not isinstance(raw.get('links'), list):
            raise GraphifyUnavailable(
                '%s has %d node(s) and no `links` list (%s) — the output shape this backend '
                'reads has changed' % (path, len(raw['nodes']),
                                       type(raw.get('links')).__name__))
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
            if node.get('type') in ANCHOR_NODE_TYPES:
                # Its `source_file` is a coincidence of which file was parsed first.
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
