#!/usr/bin/env python3
"""Check a graphify graph of java-graph-fixture against the hand-written ground truth.

Java is the case with no diff to run: the homegrown resolver produces nothing for it, so
the only available yardstick is an edge set written down by hand before the tool was run.

Usage:
    check_java.py --graphify PATH/graph.json --truth PATH/java_ground_truth.json
"""

import argparse
import json
import sys

sys.path.insert(0, __file__.rsplit("/", 1)[0])
from compare_graphs import load_graphify, _undirected  # noqa: E402


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--graphify", required=True)
    ap.add_argument("--truth", required=True)
    ap.add_argument("--json", help="write the result here")
    args = ap.parse_args()

    with open(args.truth, encoding="utf-8") as fh:
        truth = json.load(fh)

    expected = {(e["src"], e["dst"]) for e in truth["internal_edges"]}
    requires = {(e["src"], e["dst"]): e["requires"] for e in truth["internal_edges"]}
    expected_files = set(truth["source_files"])

    found, files, meta, rels = load_graphify(args.graphify)

    # Ground truth covers only the Java sources; graphify also indexes README/pom.
    java_found = {(s, d) for s, d in found
                  if s in expected_files and d in expected_files}

    exp_u, got_u = _undirected(expected), _undirected(java_found)
    missing = sorted(exp_u - got_u)
    extra = sorted(got_u - exp_u)

    by_requirement = {"import": [0, 0], "type-resolution": [0, 0]}
    for edge in expected:
        req = requires[edge]
        by_requirement[req][1] += 1
        if tuple(sorted(edge)) in got_u:
            by_requirement[req][0] += 1

    print(f"expected files : {len(expected_files)}  |  graphify indexed: {len(files)}")
    print(f"files missing from graph: "
          f"{sorted(expected_files - files) or 'none'}")
    print(f"\nexpected edges : {len(exp_u)}")
    print(f"found          : {len(got_u & exp_u)}")
    print(f"MISSING        : {len(missing)}")
    print(f"extra (beyond ground truth): {len(extra)}")
    for req, (hit, total) in by_requirement.items():
        print(f"  {req:16} {hit}/{total}")
    if missing:
        print("\nmissing:")
        for s, d in missing:
            print(f"  {s}  <->  {d}")
    if extra:
        print("\nextra:")
        for s, d in extra:
            print(f"  {s}  <->  {d}  via {sorted(rels.get((s, d)) or rels.get((d, s)) or [])}")

    print("\nrelations:", meta["relations"])

    result = {
        "expected": len(exp_u), "found": len(got_u & exp_u),
        "missing": missing, "extra": extra,
        "by_requirement": {k: {"found": v[0], "total": v[1]}
                           for k, v in by_requirement.items()},
        "relations": meta["relations"],
        "files_missing_from_graph": sorted(expected_files - files),
    }
    if args.json:
        with open(args.json, "w", encoding="utf-8") as fh:
            json.dump(result, fh, indent=2, sort_keys=True)
    return 0 if not missing else 1


if __name__ == "__main__":
    sys.exit(main())
