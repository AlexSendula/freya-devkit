#!/usr/bin/env python3
"""
Tier-1 deterministic link-integrity checks for behaviors.

No LLM, no test execution, no contradiction analysis (that is Tier-2 / Phase 3).
These checks are cheap and certain — they are the ones allowed to **hard-block**
at wrap-up (vision §8). They cover:

  forward (spec -> test):
    - every behavior `locator` resolves to a real file (skipped for `manual`);
    - a Gherkin behavior's feature file carries the `@SPEC-NNN` and `@BEH-NNN`
      reverse-link tags;
    - an `accepted` Gherkin behavior whose feature still has its `TODO(scaffold)`
      marker is an error (it claims to be authoritative but isn't authored yet);
  identity:
    - a `BEH-NNN` reused across specs is an error (ids must round-trip);
  reverse (test -> spec/behavior):
    - every `@SPEC`/`@BEH` tag found in a `.feature` file resolves to an existing
      spec / behavior (no orphan tags).

Exit code is non-zero when any error is found, so wrap-up can gate on it.

Usage:
    python verify_links.py
    python verify_links.py --dir knowledge-base/specs --format json
"""

import argparse
import ast
import json
import os
import sys
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
# The containment rule is owned by freya-code-graph and imported, not copied
# (ADR-030). This file used to carry its own body with a docstring claiming the
# two were "deliberately identical" — nothing held them to it, and a
# hand-maintained duplicate of a security predicate is the thing ADR-002 forbids.
_GRAPH_SCRIPTS = Path(__file__).resolve().parents[2] / "freya-code-graph" / "scripts"
sys.path.insert(0, str(_GRAPH_SCRIPTS))
from containment import escapes as _escapes  # noqa: E402
from search_specs import load_all_specs, find_specs_dir  # noqa: E402
from adapters import (  # noqa: E402
    parse_locator,
    has_scaffold_marker,
    scenario_block_for,
    extract_spec_tags,
    extract_behavior_tags,
    GHERKIN_ADAPTERS,
    SCAFFOLD_MARKER,
)

SKIP_DIRS = {".git", "node_modules", ".venv", "venv", "__pycache__", "knowledge-base", "dist", "build"}


def _err(spec_id, behavior_id, kind, message):
    return {"spec_id": spec_id, "behavior_id": behavior_id, "kind": kind, "message": message}


def _py_symbols(path: Path):
    """Every addressable name in a Python file: `func`, `Class`, `Class.method`.

    Returns None when the file cannot be parsed — which is NOT the same as "the
    symbol is missing". A syntax error tells us nothing about the link, and
    reporting `locator-symbol-unresolved` there would be a confidently-wrong
    answer of exactly the kind ADR-005 exists to prevent.

    Nesting stops at one level. `Class.method` is the deepest form any runner
    selects: pytest addresses `file::Class::method`, and a closure inside a
    method is not a node either runner can reach.
    """
    try:
        tree = ast.parse(path.read_text(encoding="utf-8", errors="replace"))
    except (SyntaxError, ValueError, OSError):
        return None
    names = set()
    for node in tree.body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            names.add(node.name)
        elif isinstance(node, ast.ClassDef):
            names.add(node.name)
            for sub in node.body:
                if isinstance(sub, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    names.add(f"{node.name}.{sub.name}")
    return names


def _symbol_candidates(fragment):
    """The spellings of `fragment` that name the same node.

    A locator is written `Class.method` by hand and `Class::method` by anyone
    copying a pytest node id. Both mean one thing, so both are accepted rather
    than making the author remember which half of the grammar they are in.
    """
    return {fragment, fragment.replace("::", ".")}


def _project_root(specs_dir: str) -> Path:
    """Behavior locators are relative to the project root (the parent of
    knowledge-base/). Derive it from the specs dir."""
    p = Path(specs_dir).resolve()
    if p.name == "specs" and p.parent.name == "knowledge-base":
        return p.parent.parent
    return p.parent


def _iter_feature_files(root: Path):
    for f in root.rglob("*.feature"):
        if any(part in SKIP_DIRS for part in f.parts):
            continue
        yield f


def verify(specs_dir: str = None) -> list:
    specs_dir = specs_dir or find_specs_dir()
    root = _project_root(specs_dir)
    specs = load_all_specs(specs_dir)
    errors = []

    spec_ids = {s.id for s in specs if s.id}

    # --- identity: build a global behavior index, flagging cross-spec reuse ---
    beh_index = {}
    for s in specs:
        for b in s.behaviors:
            bid = b.get("behavior_id")
            if not bid:
                continue
            if bid in beh_index:
                errors.append(_err(s.id, bid, "duplicate-id",
                                   f"behavior_id {bid} reused (already in {beh_index[bid][0]})"))
            else:
                beh_index[bid] = (s.id, b)

    # --- forward: spec -> test ---
    for s in specs:
        for b in s.behaviors:
            bid = b.get("behavior_id")
            adapter = b.get("adapter")
            state = b.get("state")
            locator = b.get("locator")

            # An integration behavior may declare an `entry` (the route/handler its
            # test drives) that behavior-runner expands into a static fingerprint.
            # If declared, it must resolve — checked independently of the adapter
            # (a non-resolving entry yields a silently-degraded fingerprint at run
            # time, so we fail loud here at Tier-1).
            entry = b.get("entry")
            if entry:
                if _escapes(entry):
                    errors.append(_err(s.id, bid, "entry-escapes-project",
                                       f"entry names a path outside the project: {entry}"))
                elif not (root / entry).exists():
                    errors.append(_err(s.id, bid, "entry-unresolved",
                                       f"entry path does not exist: {entry}"))

            # Only `accepted` asserts a real linked test, so only accepted
            # *requires* a locator. `proposed`/`confirmed` are pre-test (intent
            # confirmed, test owed — design 03 §3): a missing locator is fine. A
            # locator that IS present is resolved whatever the state, so a typo
            # fails loud.
            #
            # `manual` used to `continue` above this, exempting it from the whole
            # check rather than from the runner. Measured when that was found:
            # 17 manual behaviors here carried a locator, 11 named a method that
            # was not there and 6 named a file that had never existed, and this
            # command printed OK. Manual means nothing drives it; the address is
            # still a claim, and a claim gets checked.
            if not locator:
                if state == "accepted" and adapter != "manual":
                    errors.append(_err(s.id, bid, "missing-locator",
                                       f"{bid} has adapter '{adapter}' but no locator"))
                continue

            rel_path, frag = parse_locator(locator)
            if _escapes(rel_path):
                errors.append(_err(s.id, bid, "locator-escapes-project",
                                   f"locator names a path outside the project: {rel_path}"))
                continue
            abs_path = root / rel_path
            if not abs_path.exists():
                errors.append(_err(s.id, bid, "locator-unresolved",
                                   f"locator path does not exist: {rel_path}"))
                continue

            # A Python fragment names a node we can resolve, so resolve it. Every
            # other language's fragment is a runner selector we have no parser
            # for, and guessing at one would fail loud on links that are fine.
            if frag and rel_path.endswith(".py"):
                symbols = _py_symbols(abs_path)
                if symbols is None:
                    errors.append(_err(s.id, bid, "locator-unparseable",
                                       f"could not parse {rel_path} to resolve '{frag}'"))
                elif not (_symbol_candidates(frag) & symbols):
                    errors.append(_err(s.id, bid, "locator-symbol-unresolved",
                                       f"{rel_path} has no '{frag}'"))

            if adapter in GHERKIN_ADAPTERS:
                text = abs_path.read_text(encoding="utf-8", errors="replace")
                if bid not in extract_behavior_tags(text):
                    errors.append(_err(s.id, bid, "missing-reverse-tag",
                                       f"@{bid} tag not found in {rel_path}"))
                if s.id and s.id not in extract_spec_tags(text):
                    errors.append(_err(s.id, bid, "missing-spec-tag",
                                       f"@{s.id} tag not found in {rel_path}"))
                # Scope the scaffold-marker check to THIS behavior's own scenario
                # so a sibling proposed scaffold in the same file doesn't taint it.
                if state == "accepted":
                    block = scenario_block_for(text, bid)
                    if block is not None and has_scaffold_marker(block):
                        errors.append(_err(s.id, bid, "accepted-but-scaffold",
                                           f"accepted behavior still has {SCAFFOLD_MARKER} in {rel_path}"))

    # --- reverse: test -> spec/behavior (orphan tags) ---
    for f in _iter_feature_files(root):
        text = f.read_text(encoding="utf-8", errors="replace")
        rel = f.relative_to(root)
        for tag in extract_spec_tags(text):
            if tag not in spec_ids:
                errors.append(_err(tag, None, "orphan-spec-tag",
                                   f"@{tag} in {rel} has no matching spec"))
        for tag in extract_behavior_tags(text):
            if tag not in beh_index:
                errors.append(_err(None, tag, "orphan-behavior-tag",
                                   f"@{tag} in {rel} has no matching behavior"))

    return errors


def main():
    parser = argparse.ArgumentParser(description="Tier-1 deterministic behavior link checks")
    parser.add_argument("--dir", "-d", help="Specs directory (default: knowledge-base/specs)")
    parser.add_argument("--format", "-f", choices=["text", "json"], default="text")
    args = parser.parse_args()

    errors = verify(args.dir)

    if args.format == "json":
        print(json.dumps(errors, indent=2))
    else:
        if not errors:
            print("OK — all behavior links pass Tier-1 integrity checks.")
        else:
            print(f"{len(errors)} link-integrity error(s):\n")
            for e in errors:
                loc = " / ".join(x for x in (e["spec_id"], e["behavior_id"]) if x)
                print(f"  [{e['kind']}] {loc}: {e['message']}")

    sys.exit(1 if errors else 0)


if __name__ == "__main__":
    main()
