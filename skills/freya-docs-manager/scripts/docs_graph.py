#!/usr/bin/env python3
"""The docs graph: which documentation section describes which code.

`docs-manager` decides staleness today by taking a git diff, asking code-graph for the impact,
and then having the *agent judge* which docs correspond to the affected files. Nothing records
that `ARCHITECTURE.md` documents those files, so that judgement is re-made every run —
inconsistent between runs and impossible to verify.

The reverse question has had no answer at all: **"I changed `graph_ops.py` — which docs now
lie?"** That is not hypothetical. Changing how `.graph/.gitignore` is written invalidated
claims in two documents, both of which cited `graph_ops.py:212` in prose no tool read; they
were found by grep.

This records the edges instead of re-deriving them. Everything here is **parsed, never
inferred** — a docs graph that guesses is worse than none, because a wrong edge sends someone
to rewrite a document that was fine.

Anchoring is at **section**, not line (spec §6.3). A line number shifts the moment anyone
inserts a paragraph, and the real question is *which section is now wrong*. The cited line is
kept inside the edge as evidence.
"""

import json
import os
import re
import sys
from typing import Any, Dict, Iterable, List, Optional, Sequence, Set

DOCS_ARTIFACT = os.path.join('knowledge-base', '.graph', 'docs.json')

# Extensions worth treating as code targets. A citation of a .md file is a doc-to-doc link,
# which is a different relationship and not this artifact's job.
CODE_EXTENSIONS = (
    '.ts', '.tsx', '.js', '.jsx', '.mjs', '.cjs', '.mts',
    '.py', '.go', '.rs', '.java', '.kt', '.scala', '.rb', '.php', '.cs', '.swift',
    '.sql', '.tf', '.sh',
)

_FENCE = re.compile(r'^(\s{0,3})(`{3,}|~{3,})(.*)$')
_ATX = re.compile(r'^(#{1,6})\s+(.*?)\s*#*\s*$')
_SETEXT = re.compile(r'^(=+|-+)\s*$')


class Section:
    """One heading-delimited slice of a document."""

    __slots__ = ('title', 'slug', 'level', 'start_line', 'raw', 'warnings')

    def __init__(self, title, slug, level, start_line, raw, warnings=None):
        self.title = title
        self.slug = slug
        self.level = level
        self.start_line = start_line
        self.raw = raw
        self.warnings = warnings or []

    @property
    def body(self) -> str:
        return self.raw

    def __repr__(self) -> str:
        return 'Section(%r, slug=%r, line=%d)' % (self.title, self.slug, self.start_line)


def slugify(text: str) -> str:
    """GitHub-style anchor slug."""
    text = (text or '').strip().lower()
    text = re.sub(r'[^\w\s-]', '', text)
    return re.sub(r'[\s_]+', '-', text).strip('-')


def _strip_frontmatter(lines: List[str]) -> int:
    """Index of the first line after YAML frontmatter, or 0."""
    if not lines or lines[0].rstrip('\n') != '---':
        return 0
    for i in range(1, len(lines)):
        if lines[i].rstrip('\n') == '---':
            return i + 1
    return 0  # unterminated: treat the whole thing as body rather than eating the document


def split_sections(text: str) -> List[Section]:
    """Split markdown at heading boundaries without ever cutting a block.

    Three rules from spec §6.4, in order of how much damage breaking them does:

    1. Split only at headings.
    2. Every block is atomic — a fence, a table, an HTML block is never divided.
    3. Never split inside a fence, under any size pressure.

    Rule 3 is the one with teeth. A `# comment` inside a ```bash block is indistinguishable
    from an H1 by pattern alone, and `architecture.md` is full of ASCII trees and mermaid
    diagrams that a naive splitter would cut in half. The F7 JSONC stripper — which mis-read
    `/*` inside the string `"@/*"` — is the same bug class, and the precedent for testing it
    before shipping.

    The output is a **partition**: concatenating every `raw` reproduces the input exactly.
    """
    lines = text.splitlines(keepends=True)
    start = _strip_frontmatter(lines)

    boundaries = []  # (line_index, title, level)
    fence: Optional[str] = None
    fence_line = -1

    i = start
    while i < len(lines):
        line = lines[i].rstrip('\n')

        fence_match = _FENCE.match(line)
        if fence_match:
            marker = fence_match.group(2)
            if fence is None:
                fence = marker
                fence_line = i
            elif marker[0] == fence[0] and len(marker) >= len(fence):
                # A closing fence must use the same character and be at least as long, so
                # ```` can legitimately contain ``` verbatim.
                fence = None
            i += 1
            continue

        if fence is None:
            atx = _ATX.match(line)
            if atx:
                boundaries.append((i, atx.group(2).strip(), len(atx.group(1))))
                i += 1
                continue
            # Setext: the underline belongs to the line above, which must be plain text.
            if i > start and _SETEXT.match(line) and lines[i - 1].strip():
                prev = lines[i - 1].strip()
                if not _ATX.match(prev) and not _FENCE.match(prev):
                    level = 1 if line.startswith('=') else 2
                    boundaries.append((i - 1, prev, level))
        i += 1

    warnings = []
    if fence is not None:
        warnings.append(
            'unterminated %s fence opened at line %d — headings after it were treated as '
            'part of the block, so this document may be under-sectioned'
            % (fence[0] * 3, fence_line + 1))

    sections: List[Section] = []
    seen_slugs: Dict[str, int] = {}

    def add(title, level, first, last):
        raw = ''.join(lines[first:last])
        if not raw:
            return
        base = slugify(title) if title else ''
        slug = base
        if base:
            n = seen_slugs.get(base, 0)
            seen_slugs[base] = n + 1
            if n:
                slug = '%s-%d' % (base, n)
        sections.append(Section(title, slug, level, first + 1, raw))

    # Prose before the first heading is its own untitled slice, so that rejoining the
    # sections reproduces the body byte for byte. Frontmatter is skipped: it is metadata
    # *about* the document rather than a part of it, and `related_code:` is read separately.
    head_end = boundaries[0][0] if boundaries else len(lines)
    if head_end > start and ''.join(lines[start:head_end]).strip():
        # `.strip()`: the blank line that conventionally follows frontmatter is not a section.
        add(None, 0, start, head_end)

    for idx, (line_no, title, level) in enumerate(boundaries):
        end = boundaries[idx + 1][0] if idx + 1 < len(boundaries) else len(lines)
        add(title, level, line_no, end)

    if warnings and sections:
        sections[0].warnings.extend(warnings)
    return sections


class Citation:
    __slots__ = ('target', 'line', 'source')

    def __init__(self, target, line, source):
        self.target = target
        self.line = line
        self.source = source  # 'citation' | 'link' | 'related_code'

    def __eq__(self, other):
        return (isinstance(other, Citation) and self.target == other.target
                and self.line == other.line)

    def __hash__(self):
        return hash((self.target, self.line))

    def __repr__(self):
        return 'Citation(%r, line=%r, via=%r)' % (self.target, self.line, self.source)


# A path-shaped token, optionally followed by :line. Deliberately narrow: it must contain a
# dot-extension, and the surrounding characters are checked below so a URL's port or a
# timestamp cannot masquerade as a citation.
_PATH_LINE = re.compile(r'(?<![\w:/@.-])((?:[\w.-]+/)*[\w.-]+\.[A-Za-z][\w]*)(?::(\d+))?')
_MD_LINK = re.compile(r'\[[^\]]*\]\(([^)\s]+)\)')


def _is_code_path(path: str) -> bool:
    return path.lower().endswith(CODE_EXTENSIONS)


def _basename_index(code_files: Set[str]) -> Dict[str, List[str]]:
    index: Dict[str, List[str]] = {}
    for path in code_files:
        index.setdefault(os.path.basename(path), []).append(path)
    return index


def find_citations(text: str, doc_path: str, code_files: Set[str],
                   basenames: Optional[Dict[str, List[str]]] = None,
                   ambiguous: Optional[Set[str]] = None) -> List[Citation]:
    """Every code file this text points at, with the cited line where there is one.

    Only paths that name a file **actually in the code graph** become citations. That is what
    keeps the parser honest: it reads prose, and prose contains plenty of path-shaped strings
    that are not references to this repo.
    """
    found: Dict[Citation, Citation] = {}
    doc_dir = os.path.dirname(doc_path)
    if basenames is None:
        basenames = _basename_index(code_files)

    def record(target, line, source):
        if target in code_files:
            cite = Citation(target, line, source)
            found.setdefault(cite, cite)

    for match in _MD_LINK.finditer(text):
        href = match.group(1).split('#')[0]
        if not href or href.startswith(('http://', 'https://', 'mailto:')):
            continue
        if not _is_code_path(href):
            continue
        resolved = os.path.normpath(os.path.join(doc_dir, href)).replace(os.sep, '/')
        record(resolved, None, 'link')

    for match in _PATH_LINE.finditer(text):
        path, line = match.group(1), match.group(2)
        if not _is_code_path(path):
            continue
        # Reject a match sitting inside a URL, which the lookahead cannot see on its own.
        prefix = text[max(0, match.start() - 8):match.start()]
        if '//' in prefix or prefix.endswith(('@', ':')):
            continue
        candidates = [path]
        if doc_dir:
            candidates.append(
                os.path.normpath(os.path.join(doc_dir, path)).replace(os.sep, '/'))
        resolved = next((c for c in candidates if c in code_files), None)
        if resolved is None and '/' not in path:
            # Prose cites a bare filename far more often than a full path — 103 against 67 in
            # this repo — so refusing them would discard most of the graph. Only an
            # unambiguous name is resolved: two files sharing a basename would mean guessing,
            # and a wrong edge sends someone to rewrite a document that was fine.
            matches = basenames.get(path) or []
            if len(matches) == 1:
                resolved = matches[0]
            elif len(matches) > 1 and ambiguous is not None:
                ambiguous.add(path)
        if resolved is not None:
            record(resolved, int(line) if line else None, 'citation')

    return sorted(found.values(), key=lambda c: (c.target, c.line if c.line else 0))


# `[ \t]*`, not `\s*`: \s matches the newline, so a block list would capture its
# first item as though it were an inline value and then discard the rest.
_RELATED_BLOCK = re.compile(r'^related_code:[ \t]*(.*)$', re.M)


def find_related_code(text: str, code_files: Set[str]) -> List[str]:
    """`related_code:` from frontmatter — already present on every spec and ADR."""
    lines = text.splitlines()
    end = _strip_frontmatter([l + '\n' for l in lines])
    if end == 0:
        return []
    frontmatter = '\n'.join(lines[:end])

    match = _RELATED_BLOCK.search(frontmatter)
    if not match:
        return []

    targets: List[str] = []
    inline = match.group(1).strip()
    if inline.startswith('[') and inline.endswith(']'):
        targets = [t.strip().strip('\'"') for t in inline[1:-1].split(',')]
    elif inline:
        targets = [inline.strip('\'"')]
    else:
        start = frontmatter[:match.start()].count('\n') + 1
        for line in lines[start:end]:
            stripped = line.strip()
            if stripped.startswith('- '):
                targets.append(stripped[2:].strip().strip('\'"'))
            elif stripped and not line[:1].isspace():
                break

    return sorted({t for t in targets if t and t in code_files})


def _iter_markdown(project_dir: str, roots: Sequence[str]) -> Iterable[str]:
    skip = {'node_modules', '.git', 'dist', 'build', '__pycache__', 'venv', '.venv',
            'graphify-out', '.next'}
    for root in roots:
        base = os.path.join(project_dir, root) if root else project_dir
        if not os.path.isdir(base):
            continue
        for dirpath, dirnames, filenames in os.walk(base):
            dirnames[:] = [d for d in dirnames if d not in skip and not d.startswith('.')]
            for filename in sorted(filenames):
                if filename.lower().endswith('.md'):
                    full = os.path.join(dirpath, filename)
                    yield os.path.relpath(full, project_dir).replace(os.sep, '/')


def load_code_files(project_dir: str) -> Set[str]:
    """The file set the code graph knows about, or empty if there is no graph.

    An empty set means every citation is discarded, which is the honest outcome: without a
    code graph there is nothing to check a path against, and guessing would invent edges.
    """
    path = os.path.join(project_dir, 'knowledge-base', '.graph', 'graph.json')
    try:
        with open(path, encoding='utf-8') as handle:
            graph = json.load(handle)
    except (OSError, ValueError):
        return set()
    files = graph.get('files') if isinstance(graph, dict) else None
    return set(files) if isinstance(files, dict) else set()


def build(project_dir: str, roots: Sequence[str] = ('docs', 'knowledge-base'),
          code_files: Optional[Set[str]] = None) -> Dict[str, Any]:
    """Parse every markdown file under `roots` into doc-section → code edges."""
    if code_files is None:
        code_files = load_code_files(project_dir)

    docs: Dict[str, Any] = {}
    total_edges = 0
    basenames = _basename_index(code_files)
    ambiguous: Set[str] = set()

    for rel in sorted(_iter_markdown(project_dir, roots)):
        full = os.path.join(project_dir, rel)
        try:
            with open(full, encoding='utf-8') as handle:
                text = handle.read()
        except OSError:
            continue

        sections = split_sections(text)
        related = find_related_code(text, code_files)
        entry: Dict[str, Any] = {'sections': []}
        warnings = [w for s in sections for w in s.warnings]
        if warnings:
            entry['warnings'] = warnings

        for index, section in enumerate(sections):
            citations = find_citations(section.body, rel, code_files,
                                       basenames, ambiguous)
            edges = [{'target': c.target, 'line': c.line,
                      'via': c.source, 'provenance': 'extracted'}
                     for c in citations]
            # `related_code` describes the document, not one section of it, so it attaches to
            # the first real section rather than being duplicated across all of them.
            if index == 0 or (index == 1 and sections[0].title is None):
                for target in related:
                    if not any(e['target'] == target for e in edges):
                        edges.append({'target': target, 'line': None,
                                      'via': 'related_code', 'provenance': 'extracted'})
            total_edges += len(edges)
            entry['sections'].append({
                'title': section.title,
                'slug': section.slug,
                'level': section.level,
                'start_line': section.start_line,
                'edges': sorted(edges, key=lambda e: (e['target'], e['line'] or 0)),
            })

        docs[rel] = entry

    result: Dict[str, Any] = {
        'version': 1,
        'producer': 'docs-graph',
        'docs_scanned': len(docs),
        'edges': total_edges,
        'code_graph_present': bool(code_files),
        'docs': docs,
    }
    if ambiguous:
        # Named rather than silently dropped: a filename that matches two files is a real
        # citation the graph could not place, which is a gap worth seeing.
        result['ambiguous_citations'] = sorted(ambiguous)
    return result


def impact(graph: Dict[str, Any], code_path: str) -> List[Dict[str, Any]]:
    """Which doc sections cite `code_path` — the question that had no answer before."""
    hits = []
    for doc, entry in sorted((graph.get('docs') or {}).items()):
        for section in entry.get('sections') or []:
            matching = [e for e in section.get('edges') or [] if e.get('target') == code_path]
            if not matching:
                continue
            hits.append({
                'anchor': '%s#%s' % (doc, section.get('slug') or ''),
                'doc': doc,
                'section': section.get('title'),
                'lines_cited': sorted({e['line'] for e in matching if e.get('line')}),
                'via': sorted({e.get('via') for e in matching}),
            })
    return hits


def artifact_path(project_dir: str) -> str:
    return os.path.join(project_dir, DOCS_ARTIFACT)


def write(project_dir: str, graph: Dict[str, Any]) -> str:
    path = artifact_path(project_dir)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, 'w', encoding='utf-8') as handle:
        json.dump(graph, handle, indent=2, sort_keys=True)
        handle.write('\n')
    return path


def main() -> int:
    import argparse

    parser = argparse.ArgumentParser(description='Doc-section to code edges')
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument('--build', action='store_true', help='Parse docs and write docs.json')
    group.add_argument('--impact', metavar='FILE', help='Which doc sections cite FILE')
    parser.add_argument('--dir', metavar='PATH', default='.', help='Project directory')
    parser.add_argument('--roots', nargs='+', default=['docs', 'knowledge-base'],
                        help='Directories to scan for markdown')
    parser.add_argument('--format', choices=['json', 'summary'], default='json')
    args = parser.parse_args()

    project_dir = os.path.abspath(args.dir)

    if args.build:
        graph = build(project_dir, roots=args.roots)
        path = write(project_dir, graph)
        if args.format == 'summary':
            print('Parsed %d docs, %d edges -> %s'
                  % (graph['docs_scanned'], graph['edges'], path))
            if not graph['code_graph_present']:
                print('  no code graph found — every citation was discarded, because there '
                      'was nothing to check a path against', file=sys.stderr)
        else:
            print(json.dumps({k: v for k, v in graph.items() if k != 'docs'}, indent=2))
        return 0

    path = artifact_path(project_dir)
    try:
        with open(path, encoding='utf-8') as handle:
            graph = json.load(handle)
    except (OSError, ValueError):
        print('no docs graph at %s — run --build first' % path, file=sys.stderr)
        return 1

    hits = impact(graph, args.impact)
    if args.format == 'summary':
        if not hits:
            print('No doc section cites %s' % args.impact)
        for hit in hits:
            lines = (' (cites line %s)' % ', '.join(map(str, hit['lines_cited']))
                     if hit['lines_cited'] else '')
            print('%s%s' % (hit['anchor'], lines))
    else:
        print(json.dumps(hits, indent=2))
    return 0


if __name__ == '__main__':
    sys.exit(main())
