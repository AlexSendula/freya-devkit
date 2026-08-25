#!/usr/bin/env python3
"""
Spec Search Utility

Fast local search for feature specifications in /knowledge-base/specs/

Usage:
    python search_specs.py --query "authentication"
    python search_specs.py --tag security --min-certainty 70
    python search_specs.py --category auth
    python search_specs.py --id SPEC-001
    python search_specs.py --sort-certainty
    python search_specs.py --below 100
    python search_specs.py --status implemented
    python search_specs.py --intentional

Output formats:
    --format table   (default) Human-readable markdown table
    --format json    Machine-readable JSON
    --format paths   Just file paths

This module is also the corpus loader every other spec-manager script reads
through, so what it does with a file it cannot parse is a governance question
rather than a search one. A spec that drops out of the corpus is a spec whose
`accepted` behaviors do not exist as far as the two Tier-1 gates are concerned,
and both then print their success sentence over it. So an unreadable spec is an
alarm here: `load_specs` returns it, `load_all_specs` raises rather than answer
a quiet subset, and `freya spec` exits non-zero saying which files its answer is
short by (ADR-005, SPEC-027).
"""

import argparse
import json
import os
import re
import sys
from dataclasses import dataclass, field, asdict
from pathlib import Path
from typing import Optional

# Import the sibling scoped frontmatter parser. Adding the script's own
# directory to sys.path keeps the import working regardless of the caller's cwd
# (the freya launcher runs this script at its canonical path, not the caller's).
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from frontmatter import parse_frontmatter, FrontmatterError  # noqa: E402


@dataclass
class Spec:
    """Represents a parsed specification."""
    id: str
    title: str
    category: str
    tags: list
    status: str
    certainty: int
    created: str
    updated: str
    related_code: list = field(default_factory=list)
    intentional_decisions: list = field(default_factory=list)
    behaviors: list = field(default_factory=list)
    file_path: str = ""
    content_preview: str = ""


@dataclass
class UnreadableSpec:
    """A file in the specs tree that claims to be a spec and could not be read.

    Deliberately not the same type as "a file that is not a spec". The tree
    legitimately holds non-records — the index README, a prose note, a template
    with no frontmatter — and those are an absence with nothing behind it. This
    is an absence with a record behind it, and the two cannot share a
    representation, because every consumer of the corpus wants to say something
    about the second and nothing about the first.
    """
    file_path: str
    reason: str


class SpecCorpusError(Exception):
    """Part of the corpus could not be read, so the corpus is short.

    Carries `unreadable`, the `UnreadableSpec` list, so a caller that catches
    this can say which files rather than only that something went wrong.

    It exists because the alternative — returning the specs that did parse —
    is a shortened corpus that is indistinguishable from a repository which
    never had those specs. Measured 2026-08-24 on the version that did: delete
    the single line `id: SPEC-001` from a spec whose `accepted` behavior's test
    had just been edited without an authorizing record, and `verify_intent`
    printed `OK — no accepted test changed without an authorizing intent
    record.` at exit 0, `verify_links` printed `OK — all behavior links pass
    Tier-1 integrity checks.` at exit 0, and `--advance` then moved the intent
    baseline over the edit, which does not defer that finding but clears it on
    every future run. One deleted line, and two hard-block gates certified a
    file neither of them had read (ADR-005: never confidently empty).
    """

    def __init__(self, unreadable):
        self.unreadable = list(unreadable)
        super().__init__("; ".join(f"{u.file_path}: {u.reason}"
                                   for u in self.unreadable))


#: How far down a fence may sit and still mean "this was meant to be a record".
#: Three lines covers the shapes that actually occur — a BOM, one or two stray blank
#: lines from an editor or a bad merge — without claiming that any `---` anywhere in a
#: markdown file is frontmatter. A horizontal rule in prose is a `---` too, and it is
#: usually further down than this; a document whose fourth line is `---` and which meant
#: it as a rule gets a false alarm, which is the direction to fail in.
_FENCE_GRACE_LINES = 3


def _opens_a_fence_late(content: str) -> bool:
    """Does a `---` fence sit just below the top, rather than at line 1?

    Only ever called after `parse_frontmatter` has already answered "no fence at line 1",
    so it does not re-ask that: a BOM-prefixed `---` reaches here precisely BECAUSE
    `str.strip()` does not remove `\\ufeff`, and an early "line 1 is a fence, nothing to
    see" guard would send that case straight back out again. It did, on the first
    attempt at this fix — the blank-line shapes alarmed and the BOM shape stayed silent.
    """
    lines = content.lstrip("﻿").split("\n")
    for line in lines[:_FENCE_GRACE_LINES]:
        if line.strip() == "---":
            return True
    return False


def _unreadable(file_path: str, reason: str) -> SpecCorpusError:
    return SpecCorpusError([UnreadableSpec(file_path, reason)])


def parse_spec_file(file_path: str) -> Optional[Spec]:
    """A Spec, or None when the file is not a spec at all.

    Raises `SpecCorpusError` when the file *is* a record and cannot be read.
    Until 2026-08-24 every one of those cases returned None — some with a
    `Warning:` line on stderr that no skill-to-skill caller ever sees, the
    missing-`id` case with nothing on any stream — and the file simply left the
    corpus.

    **The discriminator is the frontmatter block, not the `id`.**
    `parse_frontmatter` returns an empty mapping for a file that never opens a
    `---` fence, and that is what this tree's legitimate non-records look like,
    so they stay a quiet None. A file that opens a fence and then carries no
    `id:` is the other thing entirely: a record that lost the one field it is
    addressed by, most often to a hand edit or a merge conflict. SPEC-017 put
    exactly that question in a `[NEEDS CLARIFICATION]` — "should a file with
    frontmatter but no `id` warn, while a file with no frontmatter at all stays
    quiet?" — and this is the answer, promoted from a warning to an alarm
    because of what the two Tier-1 gates do with the silence.
    """
    try:
        with open(file_path, 'r', encoding='utf-8') as f:
            content = f.read()
    except OSError as exc:
        raise _unreadable(file_path,
                          f"could not be opened ({exc.__class__.__name__})") from exc

    try:
        frontmatter, body = parse_frontmatter(content)
    except FrontmatterError as exc:
        raise _unreadable(file_path, f"unparseable frontmatter — {exc}") from exc

    if not frontmatter:
        # `parse_frontmatter` returns `{}` when line 1 is not exactly `---`, so this
        # branch answers "does the file OPEN with a fence", not "does it have one". A
        # spec that is plainly a spec — a fence one blank line down, or behind the UTF-8
        # BOM a Windows editor writes by default, which `str.strip()` does not remove —
        # took this return and dropped out of the corpus silently. Both Tier-1 gates then
        # printed their success sentence over a file they never read, and `--advance`
        # moved the baseline over it. That is the same hole the `id:`/FrontmatterError
        # arms above were written to close, reachable by inserting one blank line, which
        # is quieter than deleting a line.
        #
        # So: a file that has a fence *somewhere* near the top is a record that failed to
        # parse, not a document. A file with no fence at all is prose and still returns
        # None — README.md lives in this tree too, and making it an error would be the
        # over-correction that gets the check deleted.
        if _opens_a_fence_late(content):
            raise _unreadable(file_path,
                              "frontmatter fence does not start at line 1 — a leading "
                              "blank line or a UTF-8 BOM, either of which makes the whole "
                              "record invisible")
        return None

    if not frontmatter.get('id'):
        raise _unreadable(file_path,
                          "frontmatter carries no `id:` — a spec is addressed by "
                          "its id, so nothing can reach this one")

    try:
        # Create content preview (first 500 chars of body, cleaned)
        preview = re.sub(r'\s+', ' ', body)[:500].strip()

        return Spec(
            id=frontmatter.get('id', ''),
            title=frontmatter.get('title', ''),
            category=frontmatter.get('category', ''),
            tags=frontmatter.get('tags', []) if isinstance(frontmatter.get('tags'), list) else [],
            status=frontmatter.get('status', 'draft'),
            certainty=int(frontmatter.get('certainty', 0)),
            created=frontmatter.get('created', ''),
            updated=frontmatter.get('updated', ''),
            related_code=frontmatter.get('related_code', []) if isinstance(frontmatter.get('related_code'), list) else [],
            intentional_decisions=frontmatter.get('intentional_decisions', []) if isinstance(frontmatter.get('intentional_decisions'), list) else [],
            behaviors=frontmatter.get('behaviors', []) if isinstance(frontmatter.get('behaviors'), list) else [],
            file_path=file_path,
            content_preview=preview
        )
    except Exception as exc:  # noqa: BLE001 — a surprise is an alarm, never a traceback
        # The reachable case is a `certainty:` that is not an integer, which
        # `int()` refuses. Anything else in the constructor lands here too, and
        # a Tier-1 gate that dies mid-corpus is worse than one that names the
        # file and blocks on it.
        raise _unreadable(file_path, f"malformed frontmatter — {exc}") from exc


def find_specs_dir(start_path: str = None) -> str:
    """Find the knowledge-base/specs directory, starting from current dir or given path."""
    if start_path:
        search_path = Path(start_path)
    else:
        search_path = Path.cwd()

    # Prefer the knowledge-base layout; fall back to the legacy docs/specs
    # location so a not-yet-migrated project stays readable.
    possible_paths = [
        search_path / "knowledge-base" / "specs",
        search_path / "specs",
        search_path.parent / "knowledge-base" / "specs",
        search_path / "docs" / "specs",            # legacy fallback
        search_path.parent / "docs" / "specs",     # legacy fallback
    ]

    for path in possible_paths:
        if path.exists() and path.is_dir():
            return str(path.resolve())

    # Default to knowledge-base/specs relative to current directory
    return str((search_path / "knowledge-base" / "specs").resolve())


def load_specs(specs_dir: str):
    """(specs, unreadable) — the corpus, and the files it is short by.

    The loss is returned rather than printed because every consumer of the
    corpus is a checker with its own channel for "I could not read this", and
    each has to say it in its own voice: `verify_intent` an error that blocks
    and that stops `--advance` moving the baseline, `verify_links` an error row,
    `freya spec` a stderr note and a non-zero exit. A stderr warning from in
    here reaches none of them — they run this as a library call, and the two
    that matter print JSON a consumer parses.
    """
    specs, unreadable = [], []
    specs_path = Path(specs_dir)

    if not specs_path.exists():
        return specs, unreadable

    for md_file in specs_path.rglob("*.md"):
        # Skip README files
        if md_file.name.lower() == "readme.md":
            continue

        try:
            spec = parse_spec_file(str(md_file))
        except SpecCorpusError as exc:
            unreadable.extend(exc.unreadable)
            continue
        if spec:
            specs.append(spec)

    return specs, unreadable


def load_all_specs(specs_dir: str) -> list[Spec]:
    """The whole corpus, or an exception — never a quiet subset.

    A caller that wants to keep going past a file it could not read has to say
    so, by calling `load_specs` and doing something with the second half of what
    it hands back. That asymmetry is the fix: this is the name a new consumer
    reaches for, and it used to answer a shortened corpus with no way to tell
    the shortening from a small repository.

    `drift` and `contradictions` still call this one, so an unreadable spec
    stops them with the file named instead of scoping a checkpoint to a corpus
    they could not read. That is loud rather than good — the shape those two
    want is `load_specs` plus a `spec_warnings` key beside the `adr_warnings`
    they already carry (SPEC-020), and the agent instructions that tell a reader
    to surface it.
    """
    specs, unreadable = load_specs(specs_dir)
    if unreadable:
        raise SpecCorpusError(unreadable)
    return specs


def search_specs(
    specs: list[Spec],
    query: str = None,
    tag: str = None,
    category: str = None,
    status: str = None,
    spec_id: str = None,
    min_certainty: int = None,
    max_certainty: int = None,
    intentional_only: bool = False,
    sort_by_certainty: bool = False
) -> list[Spec]:
    """Filter and search specs based on criteria."""

    results = []

    for spec in specs:
        # Filter by ID
        if spec_id and spec.id.lower() != spec_id.lower():
            continue

        # Filter by tag
        if tag:
            tag_lower = tag.lower()
            if not any(tag_lower == t.lower() for t in spec.tags):
                continue

        # Filter by category
        if category and spec.category.lower() != category.lower():
            continue

        # Filter by status
        if status and spec.status.lower() != status.lower():
            continue

        # Filter by certainty range
        if min_certainty is not None and spec.certainty < min_certainty:
            continue

        if max_certainty is not None and spec.certainty >= max_certainty:
            continue

        # Filter for intentional decisions only
        if intentional_only and not spec.intentional_decisions:
            continue

        # Full-text search in query
        if query:
            query_lower = query.lower()
            searchable = f"{spec.title} {spec.category} {' '.join(spec.tags)} {spec.content_preview}".lower()
            if query_lower not in searchable:
                continue

        results.append(spec)

    # Sort by certainty (lowest first) if requested
    if sort_by_certainty:
        results.sort(key=lambda s: s.certainty)

    return results


def format_table(specs: list[Spec], show_intentional: bool = False) -> str:
    """Format specs as a markdown table."""
    if not specs:
        return "No specs found matching criteria."

    if show_intentional:
        # Include intentional decisions column
        lines = [
            "# Spec Search Results",
            "",
            "| ID | Title | Category | Certainty | Status | Intentional Decisions |",
            "|----|-------|----------|-----------|--------|----------------------|"
        ]
        for spec in specs:
            decisions = "; ".join(spec.intentional_decisions[:2])
            if len(spec.intentional_decisions) > 2:
                decisions += f" (+{len(spec.intentional_decisions) - 2} more)"
            if not decisions:
                decisions = "-"
            lines.append(f"| {spec.id} | {spec.title} | {spec.category} | {spec.certainty}% | {spec.status} | {decisions} |")
    else:
        lines = [
            "# Spec Search Results",
            "",
            "| ID | Title | Category | Certainty | Status |",
            "|----|-------|----------|-----------|--------|"
        ]
        for spec in specs:
            lines.append(f"| {spec.id} | {spec.title} | {spec.category} | {spec.certainty}% | {spec.status} |")

    lines.append("")
    lines.append(f"Found {len(specs)} spec{'s' if len(specs) != 1 else ''} matching criteria.")

    return "\n".join(lines)


def format_json(specs: list[Spec]) -> str:
    """Format specs as JSON."""
    return json.dumps([asdict(s) for s in specs], indent=2)


def format_paths(specs: list[Spec]) -> str:
    """Format specs as file paths only."""
    return "\n".join(spec.file_path for spec in specs)


def main():
    parser = argparse.ArgumentParser(
        description="Search and filter feature specifications",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
    %(prog)s --query "authentication"
    %(prog)s --tag security --min-certainty 70
    %(prog)s --category auth
    %(prog)s --id SPEC-001
    %(prog)s --sort-certainty --below 100
    %(prog)s --intentional --format json
"""
    )

    # Search filters
    parser.add_argument("--query", "-q", help="Full-text search query")
    parser.add_argument("--tag", "-t", help="Filter by tag")
    parser.add_argument("--category", "-c", help="Filter by category")
    parser.add_argument("--status", "-s", help="Filter by status (draft, in-progress, implemented, deprecated)")
    parser.add_argument("--id", help="Get specific spec by ID")
    parser.add_argument("--min-certainty", type=int, help="Minimum certainty score (0-100)")
    parser.add_argument("--max-certainty", type=int, help="Maximum certainty score (0-100)")
    parser.add_argument("--below", type=int, help="Show specs below this certainty (shorthand for --max-certainty)")
    parser.add_argument("--intentional", action="store_true", help="Only show specs with intentional decisions")

    # Sorting
    parser.add_argument("--sort-certainty", action="store_true", help="Sort by certainty (lowest first)")

    # Output format
    parser.add_argument("--format", "-f", choices=["table", "json", "paths"], default="table",
                        help="Output format (default: table)")

    # Directory override
    parser.add_argument("--dir", "-d", help="Specs directory path (default: knowledge-base/specs)")

    args = parser.parse_args()

    # Handle --below shorthand
    max_certainty = args.max_certainty
    if args.below is not None:
        max_certainty = args.below

    # Find specs directory
    specs_dir = args.dir if args.dir else find_specs_dir()

    # Load all specs
    specs, unreadable = load_specs(specs_dir)

    # Search/filter
    results = search_specs(
        specs,
        query=args.query,
        tag=args.tag,
        category=args.category,
        status=args.status,
        spec_id=args.id,
        min_certainty=args.min_certainty,
        max_certainty=max_certainty,
        intentional_only=args.intentional,
        sort_by_certainty=args.sort_certainty
    )

    # Format output
    if args.format == "json":
        print(format_json(results))
    elif args.format == "paths":
        print(format_paths(results))
    else:
        # Table format with intentional column if --intentional flag used
        print(format_table(results, show_intentional=args.intentional))

    if unreadable:
        # The results still print, and the exit code is what says they are
        # short — the same split SPEC-027 uses for the security driver, where
        # an empty array means a clean codebase only at exit 0. `--format json`
        # therefore stays parseable on stdout while the answer is disowned.
        print(f"\n{len(unreadable)} spec file(s) could not be read, so this "
              f"answer is short by them:", file=sys.stderr)
        for u in unreadable:
            print(f"  {u.file_path}: {u.reason}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
