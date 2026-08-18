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
import json
import os
import sys
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
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
            if entry and not (root / entry).exists():
                errors.append(_err(s.id, bid, "entry-unresolved",
                                   f"entry path does not exist: {entry}"))

            if adapter == "manual":
                continue

            # Only `accepted` asserts a real linked test, so only accepted
            # *requires* a locator. `proposed`/`confirmed` are pre-test (intent
            # confirmed, test owed — design 03 §3): a missing locator is fine. A
            # locator that IS present is resolved whatever the state, so a typo
            # fails loud.
            if not locator:
                if state == "accepted":
                    errors.append(_err(s.id, bid, "missing-locator",
                                       f"{bid} has adapter '{adapter}' but no locator"))
                continue

            rel_path, _frag = parse_locator(locator)
            abs_path = root / rel_path
            if not abs_path.exists():
                errors.append(_err(s.id, bid, "locator-unresolved",
                                   f"locator path does not exist: {rel_path}"))
                continue

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
