#!/usr/bin/env python3
"""Tests for the graphify backend (Track B Phase 2).

Split deliberately in two. The **projection** is a pure function from graphify's payload to the
contract's shape, so it is tested against fixtures and runs everywhere — including CI, which
has no graphify. The handful of tests that need the real binary are skipped when it is absent,
and say so rather than passing quietly.

That split is the point rather than a convenience: the projection is where every decision
lives — which relations become edges, what happens to intra-file links, how exclusions are
applied — and none of it should require an external tool to verify.

Run: python test_backend_graphify.py
"""

import json
import os
import pathlib
import shutil
import subprocess
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import backend_graphify  # noqa: E402
import graph_ops  # noqa: E402
import substrate  # noqa: E402
from backend_graphify import GraphifyBackend, GraphifyUnavailable  # noqa: E402

HAVE_GRAPHIFY = shutil.which(backend_graphify.BINARY) is not None
needs_graphify = unittest.skipUnless(
    HAVE_GRAPHIFY, 'the graphify binary is not installed on this machine')


def graphify_module_source(dotted):
    """Read a module out of graphify's own interpreter, or None if it cannot be reached.

    graphify installs as a `uv tool` in its own virtualenv, so it is on PATH but not on this
    process's import path. The binary's shebang names the interpreter that *can* import it.
    """
    binary = shutil.which(backend_graphify.BINARY)
    if not binary:
        return None
    try:
        shebang = pathlib.Path(binary).read_text(errors='replace').splitlines()[0]
    except (OSError, IndexError):
        return None
    if not shebang.startswith('#!'):
        return None
    interpreter = shebang[2:].strip()
    try:
        out = subprocess.run(
            [interpreter, '-c',
             'import %s as m; print(m.__file__)' % dotted],
            capture_output=True, text=True, timeout=60)
    except (OSError, subprocess.TimeoutExpired):
        return None
    if out.returncode != 0:
        return None
    try:
        return pathlib.Path(out.stdout.strip()).read_text(encoding='utf-8')
    except OSError:
        return None


def node(node_id, source_file, label='sym', line='L1', file_type='code'):
    return {'id': node_id, 'label': label, 'source_file': source_file,
            'source_location': line, 'file_type': file_type, '_origin': 'ast'}


def link(source, target, relation='calls', confidence='EXTRACTED', location='L10'):
    return {'source': source, 'target': target, 'relation': relation,
            'confidence': confidence, 'source_location': location, '_origin': 'ast'}


# ---------------------------------------------------------------------------
# The registries, and what each member has to *do*
# ---------------------------------------------------------------------------
#
# `backend_graphify.RELATIONS` had 32 keys and this file named 12 of them. Twenty — including
# every one of `extends`, `implements`, `mixes_in`, `instantiates`, `re_exports` and
# `dynamic_import` — appeared nowhere, so a wrong mapping on any of them was invisible and a
# relation added tomorrow would arrive covered by nothing.
#
# The fix is a `subTest` table driven off the registry itself. What it must NOT be is
# `assertEqual(RELATIONS[r], RELATIONS[r])`: reading the expectation back out of the constant
# under test passes with the projection deleted entirely. So the expectations below are
# **literals**, the convention this repository already states verbatim at
# test_audit_engine.py:180 — "Literals, not the constants under test."
#
# The loops run over `set(registry) | set(this table)`, which is what makes both directions
# fail loudly:
#
#   a relation added to the mapping    -> red here until somebody records what it must produce
#   a relation deleted from the mapping -> red here, because the behaviour recorded stops
#
# `None` means "listed deliberately as not-a-dependency" — which is a behaviour of its own,
# and a different one from being unknown: an unlisted relation is counted into
# `unmapped_relations` and printed, a listed-None relation is silent.
RELATION_BEHAVIOUR = {
    # Module-level dependency.
    'imports': 'imports',
    'imports_from': 'imports',
    'includes': 'imports',            # C/C++ `#include`
    'requires': 'imports',            # CommonJS / Ruby
    'dynamic_import': 'imports',      # `import()` — a real dependency, resolved late
    'crate_depends_on': 'imports',    # Rust manifest edge
    'depends_on': 'imports',          # package manifest edge
    're_exports': 're_exports',       # barrels keep their own kind; they are not plain imports
    # Invocation. Constructing a type is calling its constructor.
    'calls': 'calls',
    'indirect_call': 'calls',
    'instantiates': 'calls',
    # Type hierarchy. Four spellings of the same fact across four language families.
    'inherits': 'inherits',
    'extends': 'inherits',
    'implements': 'inherits',
    'mixes_in': 'inherits',
    # Named without being invoked.
    'references': 'references',
    'references_constant': 'references',
    'uses': 'references',
    'uses_component': 'references',   # JSX/Vue component usage
    'uses_static_prop': 'references',
    'reads_from': 'references',
    'embeds': 'references',
    'bound_to': 'references',
    # Listed as not-a-dependency. Being on the table is the whole point: it is what stops
    # each of these appearing in the "dropped N links" report on every single build.
    'contains': None,                  # file has symbol — the node hierarchy
    'method': None,                    # class has method — the same, one level down
    'binds_method': None,
    'defines': None,
    'rationale_for': None,             # graphify's docstring index; docs.json owns docs
    'cites': None,                     # prose citation — ADR-026
    'requires_env': None,              # an environment variable is not a file
    'listened_by': None,               # event wiring, not a source dependency
    'semantically_similar_to': None,   # clustering output, not a fact about the code
}

# graphify's confidence values against the contract's provenance axis. Literals, same rule.
PROVENANCE_BEHAVIOUR = {
    'EXTRACTED': 'extracted',
    'INFERRED': 'inferred',
}

# The three small registries, as literals, for the same union trick. Measured: a loop written
# only as `for x in registry` passes on an empty registry, so `ANCHOR_NODE_TYPES = ()` —
# which is the change that re-introduces the fabricated `s1.swift -> s3.swift` edge — was
# invisible to its own table until these existed.
#
# graphify emits one node per module and per namespace across the whole corpus, and gives it
# whichever file was parsed first as its `source_file`. Both must stay signals, not files.
AGGREGATE_ANCHOR_TYPES = ('module', 'namespace')

# Dispatched to graphify's *document* extractor, so they produce `document` and `rationale`
# nodes which this projection filters out. Declaring them as code would claim coverage of
# files that can never reach the graph.
DOCUMENT_ONLY_EXTENSIONS = ('.md', '.mdx', '.qmd', '.skill')

# Declared, but selected by *name* rather than by suffix: `package.json` and `pom.xml` produce
# nodes where an arbitrary `x.json` or `x.xml` produces nothing.
NAME_BASED_EXTENSIONS = ('.json', '.xml')

# The extensions whose language is not deducible from the extension by anyone reading it, and
# where the *available wrong answer* is the one graphify's own dispatch would give. Everything
# else is covered by the property table (non-null, in LANGUAGES, inside declared coverage);
# these are pinned by name because a property check cannot tell `typescript` from `javascript`.
NAMED_LANGUAGES = {
    # One extractor (`extract_js`) reads all eight. Labelling a `.ts` file javascript is a
    # worse answer than the question deserves — which is why this table exists at all.
    '.ts': 'typescript', '.tsx': 'typescript', '.cts': 'typescript', '.mts': 'typescript',
    '.js': 'javascript', '.jsx': 'javascript', '.mjs': 'javascript', '.cjs': 'javascript',
    '.h': 'c',              # a bare header is C; `.hpp` is where cpp starts
    '.hpp': 'cpp',
    '.m': 'objectivec',     # not matlab, not ocaml — `.ml` is ocaml
    '.ml': 'ocaml',
    '.metal': 'cpp',
    '.gradle': 'groovy',    # a build script, named for the tool and written in the language
    '.toc': 'lua',
    '.cls': 'apex',         # not commonlisp, whose files are `.cl` / `.lisp`
    '.cl': 'commonlisp',
    '.cshtml': 'razor',
    '.csproj': 'msbuild', '.fsproj': 'msbuild', '.sln': 'msbuild',
    '.inc': 'pascal',
    '.dme': 'dm',
    '.f90': 'fortran',
    '.rs': 'rust', '.java': 'java', '.py': 'python', '.go': 'go',
}


class Base(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)
        self.backend = GraphifyBackend(self.tmp)

    def translate(self, nodes, links, **kw):
        return self.backend.translate({'nodes': nodes, 'links': links}, **kw)

    def edges(self, graph, path):
        return graph['files'][path]['imports']


class TestTheProjection(Base):
    """graphify's nodes are symbols; ours are files. Every link is projected onto the file
    pair its endpoints live in."""

    def test_a_symbol_link_becomes_a_file_edge(self):
        g = self.translate(
            [node('a', 'src/a.py', 'main'), node('b', 'src/b.py', 'helper')],
            [link('a', 'b', 'calls')])
        self.assertEqual(self.edges(g, 'src/a.py'), [
            {'to': 'src/b.py', 'kind': 'calls', 'provenance': 'extracted'}])

    def test_every_file_with_a_symbol_becomes_a_node_even_with_no_edges(self):
        """A file graphify saw but found no dependency in is still a file it saw. Dropping it
        would report a smaller repo than exists."""
        g = self.translate([node('a', 'src/lonely.py')], [])
        self.assertIn('src/lonely.py', g['files'])
        self.assertEqual(self.edges(g, 'src/lonely.py'), [])

    def test_every_confidence_becomes_the_provenance_the_behaviour_table_records(self):
        """One row per member of `backend_graphify.PROVENANCE`, so a third trust tier arriving
        upstream is exercised the moment it is mapped rather than silently collapsing into
        `inferred` via the fallback below."""
        for confidence in sorted(set(backend_graphify.PROVENANCE)
                                 | set(PROVENANCE_BEHAVIOUR)):
            with self.subTest(confidence=confidence):
                self.assertIn(confidence, PROVENANCE_BEHAVIOUR,
                              'a confidence value was added to backend_graphify.PROVENANCE; '
                              'record here what it must become, as a literal')
                self.assertIn(confidence, backend_graphify.PROVENANCE,
                              'this confidence value was removed, so links carrying it now '
                              'fall through to `inferred`')
                g = self.translate(
                    [node('a', 'src/a.py'), node('b', 'src/b.py')],
                    [link('a', 'b', 'calls', confidence=confidence)])
                self.assertEqual(self.edges(g, 'src/a.py')[0]['provenance'],
                                 PROVENANCE_BEHAVIOUR[confidence])

    def test_an_unrecognised_confidence_is_inferred_not_extracted(self):
        """The cautious direction. `extracted` means "stated in the source"; claiming it for a
        value we do not recognise would assert something nobody checked."""
        g = self.translate(
            [node('a', 'src/a.py'), node('b', 'src/b.py')],
            [link('a', 'b', 'calls', confidence='SOMETHING_NEW')])
        self.assertEqual(self.edges(g, 'src/a.py')[0]['provenance'], 'inferred')

    def test_an_unknown_extension_has_no_language_rather_than_a_guess(self):
        g = self.translate([node('a', 'thing.wat')], [])
        self.assertIsNone(g['files']['thing.wat']['language'])


class TestTheExtensionTable(Base):
    """Every one of the 93 declared extensions, through the projection.

    Two were named by hand before this (`.java` and `.rs`), and the two registries that have
    to agree — `EXTENSIONS`, the coverage declaration, and `_LANGUAGE_BY_EXT`, the per-file
    label — were compared to *each other* by a pair of tests that never ran a file through
    `translate` at all. Both would have passed with the language lookup removed.

    So the loop runs over the union of the two registries and asserts what a real file with
    that suffix comes out as: it gets a language, the language is one the backend declares,
    and the graph it lands in still passes `validate_graph` against the coverage block. That
    last one is the check with teeth — `validate_graph` flags any file outside the declared
    coverage, which is precisely the defect the 93-extension declaration was written to fix,
    seen from the other side.
    """

    def one_file(self, path):
        return self.translate([node('a', path)], [])

    def language_of(self, path):
        return self.one_file(path)['files'][path]['language']

    def test_every_declared_extension_gets_a_language_on_a_real_file(self):
        """`language: null` on a file the backend claims it reads is the exact failure the
        declaration exists to prevent: the artifact says "I read this" and "I do not know what
        it is" about the same file."""
        for ext in sorted(set(backend_graphify.EXTENSIONS)
                          | set(backend_graphify._LANGUAGE_BY_EXT)):
            with self.subTest(extension=ext):
                language = self.language_of('src/thing' + ext)
                self.assertIsNotNone(language, 'declared but produces no language')
                self.assertIn(language, backend_graphify.LANGUAGES,
                              'produces a language the coverage block does not declare')

    def test_no_declared_extension_falls_outside_the_declared_coverage(self):
        """The other direction: an entry in `_LANGUAGE_BY_EXT` that `EXTENSIONS` does not
        claim gets a language *and* is reported by `validate_graph` as outside coverage — a
        backend contradicting its own declaration on a file it successfully read."""
        coverage = self.backend.coverage()
        for ext in sorted(set(backend_graphify.EXTENSIONS)
                          | set(backend_graphify._LANGUAGE_BY_EXT)):
            with self.subTest(extension=ext):
                self.assertEqual(
                    substrate.validate_graph(self.one_file('src/thing' + ext), coverage), [])

    def test_the_extension_lookup_is_case_insensitive(self):
        """`Main.PY` and `main.py` are the same file type, and `Coverage.handles` lowercases —
        so without the matching `.lower()` in the projection an upper-cased suffix is declared
        covered and given `language: null`, which is the contradiction above reached by a
        route no lowercase fixture can see."""
        for ext in sorted(set(backend_graphify.EXTENSIONS)
                          | set(backend_graphify._LANGUAGE_BY_EXT)):
            with self.subTest(extension=ext):
                shouted = self.language_of('src/thing' + ext.upper())
                self.assertIsNotNone(shouted)
                self.assertEqual(shouted, self.language_of('src/thing' + ext))

    def test_the_extensions_whose_language_is_not_obvious_are_pinned_by_name(self):
        """The property table above cannot tell `typescript` from `javascript` — both are
        non-null and both are declared. These are the rows where the *available wrong answer*
        is the one graphify's own dispatch would give, so they are pinned as literals."""
        for ext, language in sorted(NAMED_LANGUAGES.items()):
            with self.subTest(extension=ext):
                self.assertIn(ext, backend_graphify.EXTENSIONS,
                              'pinned here but no longer declared')
                self.assertEqual(self.language_of('src/thing' + ext), language)

    def test_no_document_extension_is_claimed_as_code(self):
        """`.md` and friends dispatch to graphify's *document* extractor, and this projection
        keeps `code` nodes only — so declaring them would claim coverage of files that can
        never appear in the graph, making "no docs edges" indistinguishable from "we do not
        read docs". docs.json (ADR-026) owns that question.

        Asserted through the projection so it runs without the binary. The `_DISPATCH` pin
        that proves the same thing against graphify itself carries `@needs_graphify` and is
        one of the tests CI skips.
        """
        for ext in sorted(set(backend_graphify.DOCUMENT_EXTENSIONS)
                          | set(DOCUMENT_ONLY_EXTENSIONS)):
            with self.subTest(extension=ext):
                self.assertIn(ext, backend_graphify.DOCUMENT_EXTENSIONS,
                              'dropped from the excluded-deliberately list, which is what '
                              'stops the next person "fixing" the gap by declaring it')
                self.assertNotIn(ext, backend_graphify.EXTENSIONS)
                g = self.translate(
                    [node('d', 'docs/notes' + ext, file_type='document')], [])
                self.assertEqual(g['files'], {})

    def test_every_over_claimed_extension_is_declared_and_still_flagged(self):
        """`.json` and `.xml` are selected by *name* — `package.json` produces nodes and an
        arbitrary `x.json` produces nothing. Declaring them is still right, because
        under-reporting what a backend saw is the failure the contract exists to prevent, but
        they must stay named on `over_claimed`: that attribute is what keeps them out of the
        evidence that a project would gain from switching backends, and almost every
        repository contains one."""
        for ext in sorted(set(backend_graphify.OVER_CLAIMED_EXTENSIONS)
                          | set(NAME_BASED_EXTENSIONS)):
            with self.subTest(extension=ext):
                self.assertIn(ext, self.backend.coverage().extensions)
                self.assertTrue(self.backend.coverage().handles('pkg/x' + ext))
                # Read the way `backends.py` reads it, so deleting the attribute — or
                # emptying the tuple — is red here rather than silently weakening the
                # switch-to-graphify evidence in every project that has a package.json.
                self.assertIn(ext, getattr(self.backend, 'over_claimed', ()))


class TestAnchorNodeTypes(Base):
    """Every member of `ANCHOR_NODE_TYPES`, which is the registry that fabricates edges when
    it is wrong. Each of these node types is an *aggregate*: graphify emits one node per label
    across the whole corpus and gives it whichever file was parsed first as its `source_file`.

    Read as a file, three Swift files that each `import Foundation` produced `s1.swift ->
    s3.swift` and `s2.swift -> s3.swift`, neither of which exists in the source. `namespace`
    was the same defect one language over, and it was missed when `module` was fixed because
    the fix enumerated the case it had seen rather than the class it belonged to. Driving the
    table off the tuple is what stops the third one being missed the same way.
    """

    def test_every_anchor_type_becomes_an_external_signal_rather_than_a_file(self):
        for anchor in sorted(set(backend_graphify.ANCHOR_NODE_TYPES)
                             | set(AGGREGATE_ANCHOR_TYPES)):
            with self.subTest(node_type=anchor):
                self.assertIn(anchor, backend_graphify.ANCHOR_NODE_TYPES,
                              'dropped from ANCHOR_NODE_TYPES, so its aggregate node is '
                              'read as a file again')
                nodes = [node('x', 'src/ParsedFirst.cs', label='Shared'),
                         node('a', 'src/A.cs', label='A'),
                         node('b', 'src/B.cs', label='B')]
                nodes[0]['type'] = anchor
                g = self.translate(nodes, [link('a', 'x', 'imports'),
                                           link('b', 'x', 'imports')])
                pairs = {(src, substrate.edge_other(e))
                         for src, info in g['files'].items() for e in info['imports']}
                self.assertEqual(pairs, {('src/A.cs', 'external:Shared'),
                                         ('src/B.cs', 'external:Shared')})
                self.assertNotIn('src/ParsedFirst.cs', g['files'])

    def test_an_anchor_with_no_label_still_never_becomes_a_file(self):
        """The label is what the signal is named after, and an unlabelled node falling back
        to the file path would put the anchor's accidental `source_file` into the graph as a
        dependency target — the fabricated edge again, wearing an `external:` prefix."""
        for anchor in sorted(set(backend_graphify.ANCHOR_NODE_TYPES)
                             | set(AGGREGATE_ANCHOR_TYPES)):
            with self.subTest(node_type=anchor):
                self.assertIn(anchor, backend_graphify.ANCHOR_NODE_TYPES,
                              'dropped from ANCHOR_NODE_TYPES, so its aggregate node is '
                              'read as a file again')
                nodes = [node('x', 'src/ParsedFirst.cs', label=''),
                         node('a', 'src/A.cs', label='A')]
                nodes[0]['type'] = anchor
                g = self.translate(nodes, [link('a', 'x', 'imports')])
                self.assertNotIn('src/ParsedFirst.cs', g['files'])
                self.assertEqual(substrate.edge_ends(self.edges(g, 'src/A.cs')),
                                 ['external:x'])


class TestRelationMapping(Base):
    """Every one of the 32 rows of `RELATIONS`, driven off the registry itself.

    Before this class the file named 12 of them across five hand-listed tests, four of which
    were bare `for` loops: the first failing relation aborted the rest and the message did not
    say which one broke. Twenty relations were mentioned nowhere at all.

    The expectations come from `RELATION_BEHAVIOUR` — literals — for the reason given there.
    """

    def two(self, relation):
        """One cross-file link carrying `relation`, projected. The strongest fixture for the
        dropped rows too: a *cross-file* `contains` still must not become an edge, even though
        the real ones are always intra-file and would be dropped by the self-edge guard."""
        return self.translate(
            [node('a', 'src/a.py'), node('b', 'src/b.py')],
            [link('a', 'b', relation)])

    def test_every_relation_produces_the_edge_the_behaviour_table_records(self):
        for relation in sorted(set(backend_graphify.RELATIONS) | set(RELATION_BEHAVIOUR)):
            with self.subTest(relation=relation):
                self.assertIn(
                    relation, RELATION_BEHAVIOUR,
                    'a relation was added to backend_graphify.RELATIONS; record here what a '
                    'link carrying it must produce, as a literal')
                self.assertIn(
                    relation, backend_graphify.RELATIONS,
                    'this relation was removed from backend_graphify.RELATIONS; links '
                    'carrying it are now counted as unmapped and dropped')
                expected = RELATION_BEHAVIOUR[relation]
                edges = self.edges(self.two(relation), 'src/a.py')
                if expected is None:
                    self.assertEqual(edges, [],
                                     'listed as not-a-dependency, but it produced an edge')
                    continue
                self.assertEqual(len(edges), 1, edges)
                self.assertEqual(edges[0]['to'], 'src/b.py')
                self.assertEqual(edges[0]['kind'], expected)

    def test_no_relation_on_the_table_is_reported_as_unmapped(self):
        """Being listed — with a kind *or* with an explicit None — is what keeps a relation
        out of the "dropped N links" stderr report on every single build. A None row that
        fell off the table would still produce no edge, so this is the only thing that can
        tell the difference between "deliberately not a dependency" and "never heard of it".

        Over the union, not over `RELATIONS`: looping the registry alone made the deletion of
        a None row invisible, because the deleted row also left the loop. Measured — dropping
        `cites` stayed green until this read the union.
        """
        for relation in sorted(set(backend_graphify.RELATIONS) | set(RELATION_BEHAVIOUR)):
            with self.subTest(relation=relation):
                self.assertNotIn('unmapped_relations', self.two(relation)['substrate'])

    def test_every_mapped_relation_produces_a_graph_that_still_conforms(self):
        """The kind a row maps to has to be in the contract's vocabulary *and* inside this
        backend's own coverage declaration. A row mapping to a kind the declaration does not
        claim writes an edge `validate_graph` rejects — a backend contradicting its own
        coverage block, which is the one thing that block cannot survive."""
        coverage = self.backend.coverage()
        for relation, kind in sorted(RELATION_BEHAVIOUR.items()):
            if kind is None:
                continue
            with self.subTest(relation=relation):
                g = self.two(relation)
                substrate.link_dependents(g)
                self.assertEqual(substrate.validate_graph(g, coverage), [])
                emitted = self.edges(g, 'src/a.py')[0]['kind']
                self.assertIn(emitted, substrate.RELATION_KINDS)
                self.assertIn(emitted, coverage.relations)

    def test_a_dropped_relation_still_leaves_both_files_in_the_graph(self):
        """Dropping the *link* must not drop the *files*. graphify saw them, and a file it saw
        with no dependency in it is still a file — omitting it reports a smaller repo than
        exists, which is the failure mode the whole substrate contract is against."""
        for relation, kind in sorted(RELATION_BEHAVIOUR.items()):
            if kind is not None:
                continue
            with self.subTest(relation=relation):
                self.assertEqual(sorted(self.two(relation)['files']),
                                 ['src/a.py', 'src/b.py'])

    def test_graphifys_own_docs_graph_is_not_adopted(self):
        """`rationale_for` is 543 links between `rationale`/`document` nodes. We already have
        a docs graph built from citations we control (ADR-026); a second one would give two
        answers to "which docs describe this file"."""
        g = self.translate(
            [node('a', 'docs/why.md', file_type='rationale'), node('b', 'src/b.py')],
            [link('a', 'b', 'rationale_for')])
        self.assertNotIn('docs/why.md', g['files'])
        self.assertEqual(self.edges(g, 'src/b.py'), [])

    def test_an_unknown_future_relation_is_dropped_rather_than_guessed(self):
        g = self.two('teleports_to')
        self.assertEqual(self.edges(g, 'src/a.py'), [])


class TestWhatIsDeliberatelyNotAnEdge(Base):
    def test_a_non_code_node_is_not_a_file(self):
        g = self.translate([node('d', 'README.md', file_type='document')], [])
        self.assertEqual(g['files'], {})

    def test_an_intra_file_link_is_not_a_self_edge(self):
        """1,475 of graphify's `calls` links on this repository are intra-file. Every one
        would make a file its own dependent, and blast radius walks these edges — so a file
        would always appear in its own blast radius."""
        g = self.translate(
            [node('a', 'src/a.py', 'outer'), node('b', 'src/a.py', 'inner')],
            [link('a', 'b', 'calls')])
        self.assertIn('src/a.py', g['files'])
        self.assertEqual(self.edges(g, 'src/a.py'), [])

    def test_a_link_to_a_node_that_does_not_exist_is_dropped(self):
        g = self.translate([node('a', 'src/a.py')], [link('a', 'ghost')])
        self.assertEqual(self.edges(g, 'src/a.py'), [])

    def test_a_node_with_no_source_file_cannot_anchor_an_edge(self):
        payload = {'nodes': [node('a', 'src/a.py'), node('b', None)],
                   'links': [link('a', 'b')]}
        g = self.backend.translate(payload)
        self.assertEqual(self.edges(g, 'src/a.py'), [])

    def test_malformed_links_are_skipped_not_fatal(self):
        g = self.translate([node('a', 'src/a.py'), node('b', 'src/b.py')],
                           ['not a dict', None, 42, {}, link('a', 'b')])
        self.assertEqual(len(self.edges(g, 'src/a.py')), 1)

    def test_duplicate_links_between_the_same_pair_collapse_to_one_edge(self):
        """Without symbols an edge is (from, to, kind), so the 417 symbol-level links on this
        repository become 73 file pairs. Keeping all of them would count one dependency many
        times in every dependents list."""
        g = self.translate(
            [node('a', 'src/a.py', 'f1'), node('a2', 'src/a.py', 'f2'),
             node('b', 'src/b.py', 'g')],
            [link('a', 'b', 'calls'), link('a2', 'b', 'calls')])
        self.assertEqual(len(self.edges(g, 'src/a.py')), 1)

    def test_two_kinds_between_one_pair_stay_two_edges(self):
        """They are different facts. Collapsing them would lose the distinction the object
        edge shape was introduced to carry."""
        g = self.translate(
            [node('a', 'src/a.py'), node('b', 'src/b.py')],
            [link('a', 'b', 'imports'), link('a', 'b', 'calls')])
        self.assertEqual({e['kind'] for e in self.edges(g, 'src/a.py')},
                         {'imports', 'calls'})


class TestSymbolRefinement(Base):
    """Phase 3. Symbols refine a file anchor; they never replace it (spec §5, ADR-024)."""

    def test_off_by_default(self):
        """Measured on this repository, symbols turn 73 file-level edges into 417 — a test
        module calling one helper sixty times is sixty symbol pairs and one dependency.
        Nothing downstream reads them yet, so the cost is not imposed by default."""
        g = self.translate([node('a', 'src/a.py', 'main'), node('b', 'src/b.py', 'helper')],
                           [link('a', 'b', 'calls')])
        self.assertEqual(self.edges(g, 'src/a.py')[0],
                         {'to': 'src/b.py', 'kind': 'calls', 'provenance': 'extracted'})

    def test_on_request_an_edge_names_both_ends(self):
        g = self.translate([node('a', 'src/a.py', 'main'), node('b', 'src/b.py', 'helper')],
                           [link('a', 'b', 'calls', location='L42')], symbols=True)
        self.assertEqual(self.edges(g, 'src/a.py')[0], {
            'to': 'src/b.py', 'kind': 'calls', 'provenance': 'extracted',
            'from_symbol': 'main', 'to_symbol': 'helper', 'line': 42})

    def test_the_file_anchor_survives_refinement(self):
        """The floor. A consumer that ignores symbols must behave exactly as before."""
        plain = self.translate([node('a', 'src/a.py', 'm'), node('b', 'src/b.py', 'h')],
                               [link('a', 'b', 'imports')])
        refined = self.translate([node('a', 'src/a.py', 'm'), node('b', 'src/b.py', 'h')],
                                 [link('a', 'b', 'imports')], symbols=True)
        self.assertEqual(substrate.edge_ends(self.edges(plain, 'src/a.py')),
                         substrate.edge_ends(self.edges(refined, 'src/a.py')))

    def test_symbols_split_edges_the_file_view_would_merge(self):
        """Two calls into one file are one dependency and two facts. Without symbols they
        collapse; with them, both survive — which is the whole point of the refinement."""
        nodes = [node('a1', 'src/a.py', 'first'), node('a2', 'src/a.py', 'second'),
                 node('b', 'src/b.py', 'helper')]
        links = [link('a1', 'b', 'calls'), link('a2', 'b', 'calls')]
        self.assertEqual(len(self.edges(self.translate(nodes, links), 'src/a.py')), 1)
        self.assertEqual(
            len(self.edges(self.translate(nodes, links, symbols=True), 'src/a.py')), 2)

    def test_a_method_symbol_is_qualified_by_its_owning_class(self):
        """graphify labels a method with its own name only — `.setUp()`. Measured on this
        repository, 64 of 1,731 code symbols share a bare label with a sibling in the same
        file (three different `._run()` in one test module). Unqualified, a symbol name
        describes a symbol without identifying one."""
        g = self.translate(
            [node('cls', 'src/a.py', 'InitTest'), node('m', 'src/a.py', '.run()'),
             node('t', 'src/b.py', 'helper')],
            [link('cls', 'm', 'method'), link('m', 't', 'calls')], symbols=True)
        self.assertEqual(self.edges(g, 'src/a.py')[0]['from_symbol'], 'InitTest.run()')

    def test_qualification_disambiguates_siblings_that_share_a_bare_label(self):
        g = self.translate(
            [node('c1', 'src/a.py', 'FirstTest'), node('c2', 'src/a.py', 'SecondTest'),
             node('m1', 'src/a.py', '._run()'), node('m2', 'src/a.py', '._run()'),
             node('t', 'src/b.py', 'helper')],
            [link('c1', 'm1', 'method'), link('c2', 'm2', 'method'),
             link('m1', 't', 'calls'), link('m2', 't', 'calls')], symbols=True)
        self.assertEqual(
            sorted(e['from_symbol'] for e in self.edges(g, 'src/a.py')),
            ['FirstTest._run()', 'SecondTest._run()'])

    def test_a_module_level_function_is_left_unqualified(self):
        """There is nothing to qualify it with, and inventing a prefix would be worse."""
        g = self.translate([node('a', 'src/a.py', 'main()'), node('b', 'src/b.py', 'h')],
                           [link('a', 'b', 'calls')], symbols=True)
        self.assertEqual(self.edges(g, 'src/a.py')[0]['from_symbol'], 'main()')

    def test_method_is_still_not_an_edge(self):
        """Kept as a lookup, dropped as a dependency — it never crosses a file boundary."""
        g = self.translate(
            [node('cls', 'src/a.py', 'C'), node('m', 'src/a.py', '.run()')],
            [link('cls', 'm', 'method')], symbols=True)
        self.assertEqual(self.edges(g, 'src/a.py'), [])

    def test_a_missing_line_is_omitted_rather_than_guessed(self):
        bad = link('a', 'b', 'calls')
        bad['source_location'] = 'not-a-line'
        g = self.translate([node('a', 'src/a.py', 'm'), node('b', 'src/b.py', 'h')],
                           [bad], symbols=True)
        self.assertNotIn('line', self.edges(g, 'src/a.py')[0])

    def test_an_unnamed_symbol_is_omitted_rather_than_recorded_empty(self):
        g = self.translate([node('a', 'src/a.py', ''), node('b', 'src/b.py', 'h')],
                           [link('a', 'b', 'calls')], symbols=True)
        edge = self.edges(g, 'src/a.py')[0]
        self.assertNotIn('from_symbol', edge)
        self.assertEqual(edge['to_symbol'], 'h')

    def test_a_refined_graph_still_validates(self):
        g = self.translate([node('a', 'src/a.py', 'm'), node('b', 'src/b.py', 'h')],
                           [link('a', 'b', 'imports')], symbols=True)
        substrate.link_dependents(g)
        self.assertEqual(substrate.validate_graph(g, self.backend.coverage()), [])


class TestExclusionsArePostFiltered(Base):
    """`graphify update` takes no exclusion flag, so obligation 6 is honoured on the way out.
    That settles spec open question 3, which had left the mechanism undecided."""

    def test_an_excluded_file_is_neither_a_node_nor_an_edge_end(self):
        g = self.translate(
            [node('a', 'src/a.py'), node('v', 'vendor/lib.py')],
            [link('a', 'v', 'imports')],
            exclusions=substrate.Exclusions(directories=['vendor']))
        self.assertNotIn('vendor/lib.py', g['files'])
        self.assertEqual(self.edges(g, 'src/a.py'), [])

    def test_an_edge_out_of_an_excluded_file_goes_too(self):
        g = self.translate(
            [node('a', 'src/a.py'), node('v', 'vendor/lib.py')],
            [link('v', 'a', 'imports')],
            exclusions=substrate.Exclusions(directories=['vendor']))
        self.assertEqual(list(g['files']), ['src/a.py'])

    def test_an_override_keeps_a_file_the_defaults_would_drop(self):
        g = self.translate(
            [node('a', 'src/a.py'), node('d', 'docs/lit.py')],
            [link('a', 'd', 'imports')],
            exclusions=substrate.Exclusions(directories=['docs'], overrides=['docs']))
        self.assertIn('docs/lit.py', g['files'])


class TestTheContractIsSatisfied(Base):
    def test_it_conforms(self):
        self.assertEqual(substrate.conformance_errors(self.backend), [])

    def test_the_declaration_claims_exactly_the_kinds_the_projection_emits(self):
        """Written down twice, the two drift. A row added to the mapping must not leave the
        coverage declaration claiming less — or more — than the projection can emit.

        This compared `coverage().relations` to `set(RELATIONS.values())`: two constants held
        against each other, which stays green with `translate` returning edgeless files. The
        set is measured through the projection instead — one link per relation, collect the
        kinds that actually came out the far side.
        """
        emitted = set()
        for relation in backend_graphify.RELATIONS:
            g = self.translate([node('a', 'src/a.py'), node('b', 'src/b.py')],
                               [link('a', 'b', relation)])
            emitted.update(e['kind'] for e in self.edges(g, 'src/a.py'))
        self.assertEqual(set(self.backend.coverage().relations), emitted)
        # A floor, because the equality above is *consistency* and an empty mapping is
        # perfectly consistent — measured: with `RELATIONS = {}` it stayed green. This is the
        # capability claim that separates graphify from the floor backend, which emits
        # `imports` and nothing else, so it is worth stating as a literal.
        self.assertEqual(emitted, set(substrate.RELATION_KINDS))

    def test_an_unmapped_relation_is_reported_rather_than_defaulted(self):
        """The vocabulary cannot be enumerated: grepping graphify's source finds 26 relation
        names, and `reads_from` — which this repository's own graph contains — is not one of
        them. So a name this table has never seen is a capability arriving upstream, and it
        has to surface as "dropped N links" rather than as a repository that looks thin."""
        g = self.translate(
            [node('a', 'src/a.py'), node('b', 'src/b.py')],
            [link('a', 'b', 'teleports_to'), link('a', 'b', 'teleports_to'),
             link('a', 'b', 'imports')])
        self.assertEqual(g['substrate']['unmapped_relations'], {'teleports_to': 2})
        self.assertEqual(len(self.edges(g, 'src/a.py')), 1)

    def test_a_relation_known_not_to_be_a_dependency_is_not_reported(self):
        """`contains` is listed with an explicit None. Being on the table is what stops it
        appearing in the unmapped report on every single build."""
        g = self.translate([node('a', 'src/a.py'), node('b', 'src/a.py')],
                           [link('a', 'b', 'contains')])
        self.assertNotIn('unmapped_relations', g['substrate'])

    def test_direction_disagreeing_with_the_link_s_own_source_file_is_counted(self):
        """graphify writes `directed: false`, so field order is the only carrier of
        direction — and Phase 0 measured that losing it takes mean blast radius from 5 files
        to 188. Each link repeats its own source_file, which is a free cross-check."""
        bad = link('a', 'b', 'imports')
        bad['source_file'] = 'somewhere/else.py'
        g = self.translate([node('a', 'src/a.py'), node('b', 'src/b.py')], [bad])
        self.assertEqual(g['substrate']['direction_warnings'], 1)

    def test_a_consistent_graph_carries_no_direction_warning(self):
        good = link('a', 'b', 'imports')
        good['source_file'] = 'src/a.py'
        g = self.translate([node('a', 'src/a.py'), node('b', 'src/b.py')], [good])
        self.assertNotIn('direction_warnings', g['substrate'])

    def test_a_translated_graph_validates(self):
        g = self.translate([node('a', 'src/a.py'), node('b', 'src/b.py')],
                           [link('a', 'b', 'imports')])
        substrate.link_dependents(g)
        self.assertEqual(substrate.validate_graph(g, self.backend.coverage()), [])

    def test_the_graph_says_which_backend_made_it(self):
        g = self.translate([node('a', 'src/a.py')], [])
        self.assertEqual(g['substrate']['backend'], 'graphify')
        self.assertEqual(g['version'], substrate.GRAPH_SCHEMA_VERSION)

    def test_edges_are_ordered_so_two_runs_agree(self):
        nodes = [node('a', 'src/a.py'), node('b', 'src/b.py'), node('c', 'src/c.py')]
        links = [link('a', 'c', 'imports'), link('a', 'b', 'imports')]
        first = self.translate(nodes, links)
        second = self.translate(nodes, list(reversed(links)))
        self.assertEqual(first['files']['src/a.py']['imports'],
                         second['files']['src/a.py']['imports'])


class TestFailureIsReportedNotSwallowed(Base):
    """A backend that cannot produce a graph must say so. Returning an empty one is the
    confident-empty failure the whole contract exists to remove."""

    def test_a_missing_binary_raises_rather_than_returning_nothing(self):
        self.backend.available = lambda: False
        with self.assertRaises(GraphifyUnavailable):
            self.backend.build()

    def test_success_with_no_output_file_is_a_failure(self):
        self.backend.available = lambda: True
        self.backend._run = lambda: None
        original = subprocess.run

        def fake(*a, **kw):
            return original([sys.executable, '-c', ''], capture_output=True, text=True)

        backend_graphify.subprocess.run = fake
        self.addCleanup(setattr, backend_graphify.subprocess, 'run', original)
        with self.assertRaises(GraphifyUnavailable) as ctx:
            self.backend.build()
        self.assertIn('wrote no', str(ctx.exception))

    def test_a_build_failure_degrades_to_the_floor_rather_than_crashing(self):
        """Selection degrades when a backend is unavailable. This is the other half: one that
        passed selection and then threw used to take the whole build down with it."""
        os.makedirs(os.path.join(self.tmp, 'src'))
        with open(os.path.join(self.tmp, 'src', 'a.py'), 'w') as handle:
            handle.write('x = 1\n')

        class Exploding(GraphifyBackend):
            def build(self, **kw):
                raise GraphifyUnavailable('boom')

        out = graph_ops._run_or_degrade(
            graph_ops.run_build, Exploding(self.tmp), graph_ops.CodeGraph(self.tmp),
            True, None, None)
        self.assertEqual(out['files_scanned'], 1)
        written = json.load(open(out['cached_to'], encoding='utf-8'))
        self.assertEqual(written['substrate']['backend'], 'homegrown')
        self.assertEqual(written['substrate']['degraded_from'], 'graphify')

    def test_nodes_without_a_links_list_is_a_failure_not_a_thin_graph(self):
        """A shape assertion on the one key this projection cannot do without.

        `nodes` and no `links` is what an upstream rename of the edge container looks like
        from here: every file still present, every edge gone, `status: built`, exit 0.
        `_refuse_to_erase` cannot catch it — the file set is full — so a project's entire
        blast radius would quietly become empty and the run would report success.
        """
        os.makedirs(os.path.join(self.tmp, backend_graphify.OUTPUT_DIR))
        with open(self.backend.output_path(), 'w', encoding='utf-8') as handle:
            json.dump({'nodes': [node('a', 'src/a.py')], 'edges': []}, handle)
        self.backend.available = lambda: True
        original = subprocess.run

        def fake(*a, **kw):
            return original([sys.executable, '-c', ''], capture_output=True, text=True)

        backend_graphify.subprocess.run = fake
        self.addCleanup(setattr, backend_graphify.subprocess, 'run', original)
        with self.assertRaises(GraphifyUnavailable) as ctx:
            self.backend.build()
        self.assertIn('links', str(ctx.exception))

    def test_an_edgeless_repository_is_not_mistaken_for_a_shape_change(self):
        """graphify writes `"links": []` for a repo with nothing to connect. That is a
        list, and it passes."""
        os.makedirs(os.path.join(self.tmp, backend_graphify.OUTPUT_DIR))
        with open(self.backend.output_path(), 'w', encoding='utf-8') as handle:
            json.dump({'nodes': [node('a', 'src/a.py')], 'links': []}, handle)
        self.backend.available = lambda: True
        original = subprocess.run

        def fake(*a, **kw):
            return original([sys.executable, '-c', ''], capture_output=True, text=True)

        backend_graphify.subprocess.run = fake
        self.addCleanup(setattr, backend_graphify.subprocess, 'run', original)
        self.assertIn('src/a.py', self.backend.build().graph['files'])

    def test_the_floor_failing_is_not_silently_swallowed(self):
        """There is nothing left to fall back to, so it must surface."""
        class BrokenFloor(graph_ops.CodeGraph):
            def build(self, **kw):
                raise RuntimeError('the floor itself is broken')

        floor = BrokenFloor(self.tmp)
        with self.assertRaises(RuntimeError):
            graph_ops._run_or_degrade(graph_ops.run_build, floor, floor, True, None, None)


class TestTheUnderReportingGate(unittest.TestCase):
    """Spec §9.1, the test that blocks adoption: **does graphify lose an edge the homegrown
    resolver finds?** A lost edge narrows a behaviour's blast radius, the behaviour is not
    flagged, and a regression walks through the wrap-up gate.

    Run against a committed fixture and a *recorded* graphify extraction, so it gates the half
    that can regress here — our projection — on any machine, with no binary. graphify's own
    extraction is gated separately by the live tests below, which skip when it is absent.
    """

    FIXTURE = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                           'testdata', 'gate91.json')

    @classmethod
    def setUpClass(cls):
        with open(cls.FIXTURE, encoding='utf-8') as handle:
            cls.data = json.load(handle)

    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)
        for rel, body in self.data['files'].items():
            path = os.path.join(self.tmp, rel)
            os.makedirs(os.path.dirname(path), exist_ok=True)
            with open(path, 'w', encoding='utf-8') as handle:
                handle.write(body)

    def pairs(self, graph):
        return {(src, substrate.edge_other(e))
                for src, info in graph['files'].items()
                for e in info['imports']
                if substrate.is_internal(substrate.edge_other(e))}

    def kinded(self, graph):
        return {(src, substrate.edge_other(e), substrate.edge_kind(e))
                for src, info in graph['files'].items() for e in info['imports']}

    def both(self):
        homegrown = graph_ops.CodeGraph(self.tmp).build(non_interactive=True).graph
        translated = GraphifyBackend(self.tmp).translate(self.data['graphify'])
        return self.pairs(homegrown), self.pairs(translated)

    def test_graphify_loses_no_edge_the_floor_finds(self):
        floor, graphify = self.both()
        missed = floor - graphify
        # The one known exception, and it is homegrown's defect rather than graphify's:
        # `shim.py` contains `from util import compute` inside a *string literal*, and the
        # homegrown regexes read string bodies (backlog item 10). graphify parses.
        self.assertEqual(missed, {('src/shim.py', 'src/util.py')},
                         'graphify lost edges beyond the known homegrown false positive: %s'
                         % sorted(missed - {('src/shim.py', 'src/util.py')}))

    def test_the_known_miss_really_is_a_string_literal(self):
        """Pinned so the exemption above cannot quietly start excusing something else."""
        body = self.data['files']['src/shim.py']
        self.assertIn('"from util import compute', body)

    def test_graphify_sees_a_language_the_floor_is_blind_to(self):
        """The polyglot half. Without this the gate would pass for a backend that merely
        matched the floor, which is not why the second substrate exists."""
        floor, graphify = self.both()
        java = {p for p in graphify if p[0].endswith('.java')}
        self.assertTrue(java, 'no Java edge in the recorded extraction')
        self.assertFalse({p for p in floor if p[0].endswith('.java')})

    def test_direction_is_preserved_and_not_symmetrised(self):
        """graphify writes `directed: false`. Phase 0 measured that reading it as undirected
        takes mean blast radius from 5 files to 188, so direction is the single
        highest-consequence silent regression available here."""
        _, graphify = self.both()
        self.assertIn(('src/app.ts', 'src/helper.ts'), graphify)
        self.assertNotIn(('src/helper.ts', 'src/app.ts'), graphify)

    def test_the_projected_edge_set_is_pinned_exactly(self):
        """Pairs alone are far too weak, and the first version of this gate proved it: run in
        isolation it caught **one of six** deliberate mapping mutations. The fixture carries
        each pair on several relations, so dropping one changed nothing it could see.

        Pinning (from, to, kind) over a fixture that actually exercises each guard — an
        intra-file call, a document node, a vendored tree — is what makes it bite.
        """
        translated = GraphifyBackend(self.tmp).translate(self.data['graphify'])
        self.assertEqual(self.kinded(translated), {
            ('java/Service.java', 'java/Repo.java', 'calls'),
            ('src/app.ts', 'src/helper.ts', 'calls'),
            ('src/app.ts', 'src/helper.ts', 'imports'),
            ('src/main.py', 'src/util.py', 'calls'),
            ('src/main.py', 'src/util.py', 'imports'),
            ('src/s1.swift', 'external:Foundation', 'imports'),
            ('src/s2.swift', 'external:Foundation', 'imports'),
            ('vendor/lib.py', 'src/util.py', 'calls'),
            ('vendor/lib.py', 'src/util.py', 'imports'),
        })

    def test_an_external_module_is_a_signal_not_a_file(self):
        """graphify emits ONE node per external module, and its `source_file` is whichever
        importer happened to be parsed first. Read as a file, two Swift files that each
        `import Foundation` became `s1.swift -> s2.swift` — an edge that exists nowhere in
        the source, in the direction that inflates blast radius."""
        translated = GraphifyBackend(self.tmp).translate(self.data['graphify'])
        self.assertNotIn('src/s2.swift', [t for _, t, _ in self.kinded(translated)])
        self.assertIn(('src/s1.swift', 'external:Foundation', 'imports'),
                      self.kinded(translated))

    def test_a_namespace_anchor_is_a_signal_not_a_file(self):
        """The same defect as the module node, one language over.

        graphify canonicalises C# namespaces to one node per label across every file that
        declares it, and that node keeps a `source_file` — whichever `.cs` file was parsed
        first. Read as a file, `using App.Core;` in twenty files all became edges into that
        one file. The original fix enumerated the case it had seen (`module`) rather than
        the class it belonged to; graphify's own resolver skips namespace nodes in two
        places for exactly this reason.
        """
        nodes = [
            node('ns', 'src/Core/Thing.cs', label='App.Core'),
            node('a', 'src/A.cs', label='A'),
            node('b', 'src/B.cs', label='B'),
        ]
        nodes[0]['type'] = 'namespace'
        translated = GraphifyBackend(self.tmp).translate({
            'nodes': nodes,
            'links': [link('a', 'ns', relation='imports'),
                      link('b', 'ns', relation='imports')],
        })
        pairs = {(src, substrate.edge_other(e))
                 for src, info in translated['files'].items() for e in info['imports']}
        self.assertEqual(pairs, {('src/A.cs', 'external:App.Core'),
                                 ('src/B.cs', 'external:App.Core')})
        self.assertNotIn('src/Core/Thing.cs', {t for _, t in pairs})

    def test_a_package_node_stays_a_file(self):
        """A manifest node is anchored to a real path, and graphify prunes dependency edges
        whose target manifest is not in the corpus — so `a/package.json ->
        b/package.json` is a true statement about two files that exist."""
        nodes = [node('pa', 'packages/a/package.json', label='@x/a'),
                 node('pb', 'packages/b/package.json', label='@x/b')]
        for n in nodes:
            n['type'] = 'package'
        translated = GraphifyBackend(self.tmp).translate({
            'nodes': nodes, 'links': [link('pa', 'pb', relation='depends_on')]})
        self.assertEqual(
            substrate.edge_other(translated['files']['packages/a/package.json']['imports'][0]),
            'packages/b/package.json')

    def test_a_method_symbol_carries_its_owning_class(self):
        """`Service.run()`, not `.run()`. A bare method label describes a symbol without
        identifying one — 64 of this repository's own symbols share a bare label with a
        sibling in the same file."""
        refined = GraphifyBackend(self.tmp).translate(self.data['graphify'], symbols=True)
        self.assertIn('Service.run()',
                      {e.get('from_symbol') for i in refined['files'].values()
                       for e in i['imports']})

    def test_no_file_is_its_own_dependency(self):
        """The fixture contains two real intra-file calls — `helper.ts` calling `inner()`
        and `main.py` calling `local_wrap()`. Without the guard each becomes a self-edge, and
        blast radius walks those, so every such file lands in its own blast radius."""
        translated = GraphifyBackend(self.tmp).translate(self.data['graphify'])
        self.assertEqual([(s, t) for s, t, _ in self.kinded(translated) if s == t], [])

    def test_structural_links_never_reach_the_graph(self):
        """11 `contains` and 2 `method` links in this fixture. They are the node hierarchy."""
        translated = GraphifyBackend(self.tmp).translate(self.data['graphify'])
        substrate.link_dependents(translated)
        self.assertEqual(substrate.validate_graph(translated), [])
        self.assertLessEqual(len(self.kinded(translated)), 9)

    def test_a_document_node_is_not_a_source_file(self):
        """The fixture has a markdown file, so graphify emits `document` nodes for it."""
        translated = GraphifyBackend(self.tmp).translate(self.data['graphify'])
        self.assertNotIn('docs/notes.md', translated['files'])

    def test_exclusions_are_actually_applied(self):
        """Distinguishes "the override works" from "exclusions are switched off entirely" —
        without a vendored tree in the fixture, a post-filter that never ran looked identical
        to one that ran and matched nothing."""
        excluded = GraphifyBackend(self.tmp).translate(
            self.data['graphify'],
            exclusions=substrate.Exclusions(directories=['vendor']))
        self.assertNotIn('vendor/lib.py', excluded['files'])
        self.assertEqual([e for e in self.kinded(excluded) if 'vendor' in e[0]], [])
        self.assertIn('src/util.py', excluded['files'])

    def test_symbol_lines_are_the_lines_graphify_reported(self):
        """Pins `line`, which nothing else in the gate reads — an off-by-one here would be
        invisible and would point every consumer one line off."""
        refined = GraphifyBackend(self.tmp).translate(self.data['graphify'], symbols=True)
        node = {n['id']: n for n in self.data['graphify']['nodes']}
        expected = {int(l['source_location'][1:])
                    for l in self.data['graphify']['links']
                    if l['relation'] == 'imports_from'
                    and node[l['source']].get('source_file')
                    != node[l['target']].get('source_file')}
        got = {e['line'] for i in refined['files'].values() for e in i['imports']
               if e['kind'] == 'imports' and 'line' in e}
        self.assertTrue(expected <= got, '%s not in %s' % (expected, got))

    def test_the_translated_graph_satisfies_the_contract(self):
        translated = GraphifyBackend(self.tmp).translate(self.data['graphify'])
        substrate.link_dependents(translated)
        errors = substrate.validate_graph(translated,
                                          GraphifyBackend(self.tmp).coverage())
        self.assertEqual(errors, [])

    @needs_graphify
    def test_the_recording_still_matches_what_graphify_produces(self):
        """The fixture is a snapshot, and a snapshot rots. This is the canary: when graphify
        changes what it emits for this tree, the gate above is still passing against a graph
        nobody produces any more."""
        live = GraphifyBackend(self.tmp).build().graph
        self.assertEqual(self.pairs(live),
                         self.pairs(GraphifyBackend(self.tmp).translate(
                             self.data['graphify'])),
                         'recorded fixture has drifted from graphify %s — re-record it'
                         % self.data.get('graphify_version'))


@needs_graphify
class TestAgainstTheRealBinary(Base):
    """The claims about graphify that fixtures cannot check."""

    def project(self, files):
        for rel, body in files.items():
            path = os.path.join(self.tmp, rel)
            os.makedirs(os.path.dirname(path), exist_ok=True)
            with open(path, 'w', encoding='utf-8') as handle:
                handle.write(body)
        return self.tmp

    def test_it_extracts_a_language_the_floor_cannot_read(self):
        """The entire argument for this backend. A Java repo is graphed as empty by the
        homegrown resolver and reported as a success."""
        self.project({
            'src/Main.java': ('public class Main {\n'
                              '  public int run() { return new Helper().help(); }\n}\n'),
            'src/Helper.java': 'public class Helper {\n  public int help() { return 1; }\n}\n',
        })
        graph = GraphifyBackend(self.tmp).build().graph
        self.assertIn('src/Main.java', graph['files'])
        self.assertIn('src/Helper.java', graph['files'])

        floor = graph_ops.CodeGraph(self.tmp).build(non_interactive=True).graph
        self.assertEqual(floor['files'], {}, 'the floor should see no Java at all')

    def test_the_mapping_covers_graphifys_own_dependency_vocabulary(self):
        """The authority for "is this relation a dependency?" is graphify, not us.

        `DEFAULT_AFFECTED_RELATIONS` is the vocabulary its own blast-radius traversal walks.
        Every name in it must map to one of our kinds — a name missing from our table is a
        dependency graphify would follow and we would silently drop.

        This exists because a hand-maintained table drifted within an hour of being written:
        four relations were removed from it on the strength of a grep that only matched
        `relation = "..."` assignments and could not see a tuple constant.
        """
        import ast

        text = graphify_module_source('graphify.affected')
        if text is None:
            self.skipTest('graphify.affected could not be read from its own interpreter')
        source = ast.parse(text)
        theirs = None
        for statement in ast.walk(source):
            if (isinstance(statement, ast.Assign)
                    and any(getattr(t, 'id', None) == 'DEFAULT_AFFECTED_RELATIONS'
                            for t in statement.targets)):
                theirs = {e.value for e in statement.value.elts
                          if isinstance(e, ast.Constant) and isinstance(e.value, str)}
        self.assertTrue(theirs, 'could not read DEFAULT_AFFECTED_RELATIONS')

        unmapped = sorted(r for r in theirs if backend_graphify.RELATIONS.get(r) is None)
        self.assertEqual(unmapped, [],
                         'graphify walks these as dependencies and we drop them: %s'
                         % unmapped)

    def test_graphify_agrees_the_structural_relations_are_not_dependencies(self):
        """Independent confirmation of the three we drop: graphify's own traversal excludes
        them too, at affected.py's `not in ("method", "contains")` guard."""
        source = graphify_module_source('graphify.affected')
        if source is None:
            self.skipTest('graphify.affected could not be read from its own interpreter')
        self.assertIn('"method", "contains"', source)
        for structural in ('contains', 'method', 'rationale_for'):
            with self.subTest(relation=structural):
                self.assertIsNone(backend_graphify.RELATIONS[structural])

    def test_a_deleted_file_leaves_the_graph(self):
        """This is what `coverage.incremental=True` claims, so it is measured, not assumed."""
        self.project({'src/a.py': 'from b import h\ndef m(): return h()\n',
                      'src/b.py': 'def h(): return 1\n'})
        self.assertIn('src/b.py', GraphifyBackend(self.tmp).build().graph['files'])
        os.remove(os.path.join(self.tmp, 'src', 'b.py'))
        self.assertNotIn('src/b.py', GraphifyBackend(self.tmp).update().graph['files'])

    def test_two_runs_of_unchanged_source_agree(self):
        self.project({'src/a.py': 'def m(): return 1\n'})
        first = GraphifyBackend(self.tmp).build().graph['files']
        second = GraphifyBackend(self.tmp).build().graph['files']
        self.assertEqual(first, second)

    def test_an_empty_project_still_gets_a_graph(self):
        """graphify exits 1 on a project with nothing to extract — its message,
        "Nothing to update or rebuild failed", conflates the two cases and cannot be told
        apart without matching on a string that will change between versions.

        So the backend reports it as a failure, which is honest, and the contract degrades to
        the floor, which produces the correct empty graph. Asserted through `_run_or_degrade`
        because the guarantee that matters is the one a user gets, not the one the backend
        returns.
        """
        out = graph_ops._run_or_degrade(
            graph_ops.run_build, GraphifyBackend(self.tmp),
            graph_ops.CodeGraph(self.tmp), True, None, None)
        written = json.load(open(out['cached_to'], encoding='utf-8'))
        self.assertEqual(written['files'], {})
        self.assertEqual(written['substrate']['backend'], 'homegrown')
        self.assertEqual(written['substrate']['degraded_from'], 'graphify')

    def test_a_second_run_over_unchanged_source_is_not_mistaken_for_a_failure(self):
        """The cached no-op path. If it exited non-zero like the empty case, every steady
        state `--update` would degrade to the floor and the opt-in would quietly stop
        applying."""
        self.project({'src/a.py': 'def m(): return 1\n'})
        GraphifyBackend(self.tmp).build()
        again = GraphifyBackend(self.tmp).update()
        self.assertEqual(again.status, substrate.Result.UPDATED)
        self.assertIn('src/a.py', again.graph['files'])

    def test_an_artifact_from_another_backend_is_replaced_rather_than_reported_current(self):
        """"Nothing changed" is about the *source*. An artifact written by a different
        backend, or against an older schema, has to be replaced whatever the source did —
        and reporting `up_to_date` over one left it in place indefinitely, because every
        later update reached the same short-circuit."""
        self.project({'src/a.py': 'def m(): return 1\n'})
        graph_ops.run_build(GraphifyBackend(self.tmp), non_interactive=True,
                            exclusions=None, selection_metadata=None)
        active = substrate.active_graph_path(self.tmp)
        with open(active, encoding='utf-8') as handle:
            stale = json.load(handle)
        stale['substrate']['backend'] = 'homegrown'
        with open(active, 'w', encoding='utf-8') as handle:
            json.dump(stale, handle)

        again = GraphifyBackend(self.tmp).update()
        self.assertEqual(again.status, substrate.Result.UPDATED)
        self.assertEqual(again.graph['substrate']['backend'], 'graphify')

    def test_up_to_date_reports_on_the_artifact_on_disk(self):
        """The staleness guard in `_finalise` asks the returned graph what version it is.
        Handing it a freshly-built one made that check answer about something other than
        the artifact it was asked about."""
        self.project({'src/a.py': 'def m(): return 1\n'})
        graph_ops.run_build(GraphifyBackend(self.tmp), non_interactive=True,
                            exclusions=None, selection_metadata=None)
        active = substrate.active_graph_path(self.tmp)
        with open(active, encoding='utf-8') as handle:
            downgraded = json.load(handle)
        downgraded['version'] = 1
        with open(active, 'w', encoding='utf-8') as handle:
            json.dump(downgraded, handle)

        again = GraphifyBackend(self.tmp).update()
        self.assertEqual(again.status, substrate.Result.UPDATED,
                         'a schema-old artifact must be rewritten, not reported current')

    def test_the_output_directory_is_marked_not_committable(self):
        """`graphify-out/` lands at the project root, outside every ignore rule this
        toolkit writes, so `git add -A` staged a multi-megabyte generated tree in any
        project that opted in. Same defect as the per-backend artifact once was, one
        directory over."""
        self.project({'src/a.py': 'def m(): return 1\n'})
        GraphifyBackend(self.tmp).build()
        marker = os.path.join(self.tmp, backend_graphify.OUTPUT_DIR, '.gitignore')
        self.assertTrue(os.path.exists(marker))
        with open(marker, encoding='utf-8') as handle:
            self.assertIn('*', handle.read().split('\n'))

    def test_a_hand_edited_marker_is_left_alone(self):
        self.project({'src/a.py': 'def m(): return 1\n'})
        GraphifyBackend(self.tmp).build()
        marker = os.path.join(self.tmp, backend_graphify.OUTPUT_DIR, '.gitignore')
        with open(marker, 'w', encoding='utf-8') as handle:
            handle.write('# mine\n!graph.json\n')
        GraphifyBackend(self.tmp).build()
        with open(marker, encoding='utf-8') as handle:
            self.assertEqual(handle.read(), '# mine\n!graph.json\n')


class TestTheDeclaredCoverageMatchesTheTool(unittest.TestCase):
    """The coverage block is only worth having if it is true.

    It was hand-written from what two fixtures produced, and declared 34 of the 93
    extensions graphify actually dispatches — so a `.groovy`, `.kts` or `.f90` file the tool
    had successfully parsed was written into the artifact, flagged by `validate_graph` as
    outside the declared coverage, and given `language: null`. Under-claiming is the
    direction the module's own comment calls dangerous, and this is the check that keeps it
    from happening again as graphify grows.
    """

    def dispatch(self):
        """`extract._DISPATCH`, read out of graphify's own interpreter.

        Executed rather than parsed: the table maps a suffix to a *function reference*, so
        the interpreter that owns those functions is the only place it can be read honestly.
        This is the same shape as the relation table's pin against
        `DEFAULT_AFFECTED_RELATIONS` — and it exists because the previous attempt to verify
        graphify's vocabulary with a regex reported four real relations as invented.
        """
        binary = shutil.which(backend_graphify.BINARY)
        if not binary:
            self.skipTest('graphify is not installed')
        shebang = pathlib.Path(binary).read_text(errors='replace').splitlines()[0]
        if not shebang.startswith('#!'):
            self.skipTest('graphify is not a shebang script on this machine')
        out = subprocess.run(
            [shebang[2:].strip(), '-c',
             'from graphify import extract; import json;'
             ' print(json.dumps({k.lower(): getattr(v, "__name__", "?")'
             ' for k, v in extract._DISPATCH.items()'
             ' if isinstance(k, str) and k.startswith(".")}))'],
            capture_output=True, text=True, timeout=120)
        if out.returncode != 0:
            self.skipTest('graphify._DISPATCH is not readable: %s' % out.stderr.strip())
        return json.loads(out.stdout)

    @needs_graphify
    def test_every_code_extension_graphify_dispatches_is_declared(self):
        dispatch = self.dispatch()
        expected = {ext for ext, fn in dispatch.items() if fn != 'extract_markdown'}
        missing = expected - set(backend_graphify.EXTENSIONS)
        self.assertEqual(missing, set(),
                         'graphify parses these and the coverage block does not claim them')

    @needs_graphify
    def test_document_extensions_are_excluded_deliberately(self):
        """Claiming `.md` would say we cover files that can never reach the graph — the
        projection keeps `code` nodes only. docs.json owns that question."""
        dispatch = self.dispatch()
        docs = {ext for ext, fn in dispatch.items() if fn == 'extract_markdown'}
        self.assertEqual(docs, set(backend_graphify.DOCUMENT_EXTENSIONS))
        self.assertEqual(docs & set(backend_graphify.EXTENSIONS), set())

    def test_the_declared_languages_are_exactly_what_the_projection_produces(self):
        """`set(LANGUAGES) == set(_LANGUAGE_BY_EXT.values())` compares two constants and would
        pass with `translate` never consulting either of them. Measured instead: one file per
        declared extension, through the projection, collecting what came out.

        The per-extension half of this — that each one gets a language at all, and that the
        language is declared — is `TestTheExtensionTable`, which names the failing extension
        in its subTest. This is the whole-set assertion: a language declared that nothing can
        ever produce, which no per-extension row can see.
        """
        tmp = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, tmp, ignore_errors=True)
        backend = GraphifyBackend(tmp)
        produced = set()
        for ext in backend_graphify.EXTENSIONS:
            path = 'src/thing' + ext
            graph = backend.translate({'nodes': [node('a', path)], 'links': []})
            produced.add(graph['files'][path]['language'])
        self.assertEqual(set(backend_graphify.LANGUAGES), produced)


if __name__ == '__main__':
    unittest.main()
