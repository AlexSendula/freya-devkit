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
# (the skill is invoked via an absolute ${CLAUDE_PLUGIN_ROOT} path).
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from frontmatter import parse_frontmatter  # noqa: E402


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


def parse_spec_file(file_path: str) -> Optional[Spec]:
    """Parse a spec file and return a Spec object."""
    try:
        with open(file_path, 'r', encoding='utf-8') as f:
            content = f.read()

        frontmatter, body = parse_frontmatter(content)

        if not frontmatter.get('id'):
            return None

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
    except Exception as e:
        print(f"Warning: Error parsing {file_path}: {e}", file=sys.stderr)
        return None


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


def load_all_specs(specs_dir: str) -> list[Spec]:
    """Load all specs from the specs directory."""
    specs = []
    specs_path = Path(specs_dir)

    if not specs_path.exists():
        return specs

    for md_file in specs_path.rglob("*.md"):
        # Skip README files
        if md_file.name.lower() == "readme.md":
            continue

        spec = parse_spec_file(str(md_file))
        if spec:
            specs.append(spec)

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
    specs = load_all_specs(specs_dir)

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


if __name__ == "__main__":
    main()
