#!/usr/bin/env python3
"""
Behavior adapters: link a Behavior record to the test that verifies it.

Two adapters in Phase 1 (vision §5, 01-phase-1.md §4.3):

- **Gherkin** (`cucumber` / `behave` / `pytest-bdd`): the default for new,
  user-visible behavior. spec-manager writes a **skeleton `.feature`** — required
  `@SPEC-NNN` / `@BEH-NNN` tags and a `TODO(scaffold)` marker, but **no real
  steps and no step definitions** (authoring real steps is forward-design work
  for a human). The scaffold points back at the spec for intent.
- **Native** (`jest`, `playwright`, `pytest`, …): links an **existing** test by
  `locator`. No file is written and nothing is rewritten — this keeps adoption
  cheap for projects that already have tests.

This module only knows the *shape* of a scaffold and how to read a locator; it
writes no files itself. `verify_links.py` (Step 5) reuses these helpers to check
that an `accepted` behavior is not still sitting on a `TODO(scaffold)` marker and
that locators resolve.
"""

import argparse
import re
import sys

SCAFFOLD_MARKER = "TODO(scaffold)"
# Adapters that own a written .feature scaffold (vs. native adapters that link an
# existing test in place). Used by verify to decide which integrity checks apply.
GHERKIN_ADAPTERS = ("cucumber", "behave", "pytest-bdd")
_TAG_RE = re.compile(r"@([A-Za-z]+-\d+)")


def slugify(text: str) -> str:
    """`"Successful passkey login"` -> `"successful-passkey-login"`."""
    return re.sub(r"[^a-z0-9]+", "-", text.strip().lower()).strip("-")


def feature_locator(category: str, feature_name: str, scenario_title: str) -> str:
    """Conventional Gherkin locator: `features/<cat>/<name>.feature#<scenario-slug>`."""
    return f"features/{category}/{feature_name}.feature#{slugify(scenario_title)}"


def render_scenario_scaffold(behavior_id: str, title: str) -> str:
    """A single tagged Scenario with the scaffold marker and placeholder steps."""
    return (
        f"  @{behavior_id}\n"
        f"  Scenario: {title}\n"
        f"    # {SCAFFOLD_MARKER}: replace with real steps. Step definitions are not generated.\n"
        f"    Given <initial state>\n"
        f"    When <action>\n"
        f"    Then <expected outcome>\n"
    )


def render_feature_scaffold(spec_id: str, feature_title: str, spec_relpath: str, behaviors) -> str:
    """A full skeleton `.feature` file.

    `behaviors` is an iterable of (behavior_id, title). The Feature carries the
    `@SPEC-NNN` tag; each Scenario carries its `@BEH-NNN` tag. The tags are the
    reverse links and are required.
    """
    header = (
        f"@{spec_id}\n"
        f"Feature: {feature_title}\n"
        f"  # Intent and rationale live in {spec_relpath}\n"
    )
    scenarios = "\n".join(render_scenario_scaffold(bid, title) for bid, title in behaviors)
    return f"{header}\n{scenarios}"


def extract_tags(text: str, prefix: str) -> set:
    return {t for t in _TAG_RE.findall(text) if t.startswith(prefix + "-")}


def extract_spec_tags(text: str) -> set:
    return extract_tags(text, "SPEC")


def extract_behavior_tags(text: str) -> set:
    return extract_tags(text, "BEH")


def has_scaffold_marker(text: str) -> bool:
    """True while a scaffold still has its unfilled `TODO(scaffold)` marker."""
    return SCAFFOLD_MARKER in text


def scenario_blocks(text: str):
    """Split a feature file into per-Scenario blocks.

    Returns `[(behavior_tags:set, block_text)]`, one entry per `Scenario` /
    `Scenario Outline`, where `block_text` includes the contiguous tag lines
    directly above the header. This lets checks be **scoped to one behavior's
    scenario** — e.g. an authored, accepted scenario in a file that also contains
    a separate proposed scaffold must not be flagged by the other scenario's
    `TODO(scaffold)` marker.
    """
    lines = text.split("\n")
    headers = [
        i for i, ln in enumerate(lines)
        if ln.strip().startswith(("Scenario:", "Scenario Outline:"))
    ]
    blocks = []
    for idx, h in enumerate(headers):
        start = h
        j = h - 1
        while j >= 0 and lines[j].strip().startswith("@"):
            start = j
            j -= 1
        if idx + 1 < len(headers):
            nxt = headers[idx + 1]
            end = nxt
            m = nxt - 1
            while m > h and lines[m].strip().startswith("@"):
                end = m
                m -= 1
        else:
            end = len(lines)
        block = "\n".join(lines[start:end])
        blocks.append((extract_behavior_tags(block), block))
    return blocks


def scenario_block_for(text: str, behavior_id: str):
    """Return the scenario block tagged with `@behavior_id`, or None."""
    for tags, block in scenario_blocks(text):
        if behavior_id in tags:
            return block
    return None


def parse_locator(locator: str):
    """Split a locator into (path, fragment).

    Supports the Gherkin `path#scenario-slug` form and the pytest-style
    `path::node` form. Returns (path, None) when there is no fragment.
    """
    if "#" in locator:
        path, _, frag = locator.partition("#")
        return path, frag
    if "::" in locator:
        path, _, frag = locator.partition("::")
        return path, frag
    return locator, None


def _parse_behavior_arg(value: str):
    """`BEH-007:Successful passkey login` -> ('BEH-007', 'Successful passkey login')."""
    bid, sep, title = value.partition(":")
    if not sep or not title.strip():
        raise argparse.ArgumentTypeError(
            f"--behavior must be 'BEH-NNN:Title', got {value!r}"
        )
    return bid.strip(), title.strip()


def main():
    parser = argparse.ArgumentParser(description="Behavior adapter helpers")
    sub = parser.add_subparsers(dest="cmd", required=True)

    g = sub.add_parser("gherkin-scaffold", help="Emit a skeleton .feature file")
    g.add_argument("--spec-id", required=True)
    g.add_argument("--title", required=True, help="Feature title")
    g.add_argument("--spec-path", required=True, help="Path to the spec, for the intent pointer")
    g.add_argument("--behavior", required=True, action="append", type=_parse_behavior_arg,
                   help="BEH-NNN:Scenario title (repeatable)")

    args = parser.parse_args()
    if args.cmd == "gherkin-scaffold":
        sys.stdout.write(
            render_feature_scaffold(args.spec_id, args.title, args.spec_path, args.behavior)
        )


if __name__ == "__main__":
    main()
