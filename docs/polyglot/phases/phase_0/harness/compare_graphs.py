#!/usr/bin/env python3
"""Normalise a homegrown graph.json and a graphify graph.json onto the same shape
and diff them.

The comparison is deliberately at **file level**. graphify records symbol-level edges
(`calls`, `inherits`) that the homegrown resolver has no equivalent for; folding those
down to the files they connect is the only way to ask "does graphify see everything we
see" without the answer being dominated by a granularity difference.

Two views are always reported, because only the second one is evidence:

  raw        every internal edge each side found
  restricted edges whose *both* endpoints are files present in both graphs

The raw diff is dominated by file-selection differences (one side indexes tests or
configs the other skips), which says nothing about extraction quality. The restricted
diff is the §9.1 measurement.

Usage:
    compare_graphs.py --homegrown A/graph.json --graphify B/graphify-out/graph.json
                      [--json OUT] [--limit N]
"""

import argparse
import json
import os
import sys
from collections import Counter

# graphify emits these between a file node and a symbol it defines. They are intra-file
# bookkeeping, not dependencies, so they never become an edge.
CONTAINMENT_RELATIONS = {"contains", "defines", "declares"}


def _norm(path):
    """Repo-relative, forward-slashed, no leading './'.

    Deliberately not `lstrip('./')` — that strips *characters*, so a dotfile path like
    '.github/workflows/ci.yml' would come back as 'github/workflows/ci.yml' and silently
    fail to match its counterpart on the other side.
    """
    if not path:
        return None
    p = str(path).replace(os.sep, "/")
    while p.startswith("./"):
        p = p[2:]
    p = p.lstrip("/")
    return p or None


def load_homegrown(path):
    """-> (edges, files, meta). Edges are (src, dst) of internal imports.

    The homegrown format marks third-party imports with an 'external:' prefix; anything
    without it is a repo-relative path.
    """
    with open(path, encoding="utf-8") as fh:
        data = json.load(fh)

    files_raw = data.get("files", {})
    files = {_norm(f) for f in files_raw}
    files.discard(None)

    edges = set()
    dangling = set()
    for src, info in files_raw.items():
        s = _norm(src)
        for imp in (info.get("imports") or []):
            if imp.startswith("external:"):
                continue
            d = _norm(imp)
            if not d or d == s:
                continue
            edges.add((s, d))
            if d not in files:
                dangling.add((s, d))

    meta = {
        "backend": "homegrown",
        "file_count": len(files),
        "edge_count": len(edges),
        "languages": dict(Counter(
            (info.get("language") or "unknown") for info in files_raw.values())),
        # Edges whose target is not itself a node. Homegrown resolves extensionless
        # imports by guessing, so it can point at something it never indexed.
        "dangling_edges": sorted(dangling),
    }
    return edges, files, meta


def load_graphify(path, repo_root=None):
    """-> (edges, files, meta). Symbol endpoints are folded to their source_file."""
    with open(path, encoding="utf-8") as fh:
        data = json.load(fh)

    # node id -> owning file
    owner = {}
    for node in data.get("nodes", []):
        nid = node.get("id")
        src = _norm(node.get("source_file"))
        if nid is None:
            continue
        owner[nid] = src

    files = {f for f in owner.values() if f}

    # graphify mints pseudo-nodes for third-party packages, and their source_file can
    # name something that is not a file on disk ('next', 'postcss-load-config'). Counting
    # those as indexed files overstates its coverage, so drop them when we can check.
    phantom = set()
    if repo_root:
        root = os.path.abspath(repo_root)
        phantom = {f for f in files if not os.path.exists(os.path.join(root, f))}
        files -= phantom

    edges = set()
    # (src,dst) -> {relations that produced it}. Needed because folding symbol edges to
    # file level can make graphify "cover" an import edge via an unrelated call, which
    # would look like agreement while resting on a different fact.
    edge_relations = {}
    relation_counts = Counter()
    confidence_counts = Counter()
    dropped_unmapped = 0
    for link in data.get("links", []):
        rel = link.get("relation")
        relation_counts[rel] += 1
        confidence_counts[link.get("confidence")] += 1
        if rel in CONTAINMENT_RELATIONS:
            continue
        s = owner.get(link.get("source"))
        d = owner.get(link.get("target"))
        if s is None or d is None:
            dropped_unmapped += 1
            continue
        if s == d:
            continue  # intra-file once folded
        edges.add((s, d))
        edge_relations.setdefault((s, d), set()).add(rel)

    meta = {
        "backend": "graphify",
        "directed": data.get("directed"),
        "multigraph": data.get("multigraph"),
        "node_count": len(data.get("nodes", [])),
        "link_count": len(data.get("links", [])),
        "file_count": len(files),
        "edge_count": len(edges),
        "relations": dict(relation_counts),
        "confidence": dict(confidence_counts),
        "links_dropped_unmapped_endpoint": dropped_unmapped,
        "phantom_source_files_excluded": sorted(phantom),
    }
    return edges, files, meta, edge_relations


def _undirected(edges):
    return {tuple(sorted(e)) for e in edges}


# Relations that mean "this file references that file" the way an import does. An edge
# backed only by something outside this set agrees with homegrown on the connection but
# not on the reason for it.
IMPORT_FAMILY = {"imports", "imports_from", "re_exports", "dynamic_import"}


def compare(hg_edges, hg_files, gf_edges, gf_files, gf_edge_relations=None):
    common_files = hg_files & gf_files

    def restrict(edges):
        return {(s, d) for s, d in edges if s in common_files and d in common_files}

    hg_r, gf_r = restrict(hg_edges), restrict(gf_edges)

    # graphify's graph is undirected; comparing directed pairs would report a miss for
    # an edge it found but stored the other way round. Both views are reported so the
    # cost of that property is visible rather than smoothed away.
    hg_u, gf_u = _undirected(hg_r), _undirected(gf_r)

    # Of the edges both sides agree on, how many does graphify justify with an actual
    # import rather than only with a call or reference that happens to cross the same
    # two files?
    shared = hg_r & gf_r
    backing = Counter()
    import_backed = []
    other_backed = []
    for edge in sorted(shared):
        rels = (gf_edge_relations or {}).get(edge, set())
        if rels & IMPORT_FAMILY:
            backing["import_family"] += 1
            import_backed.append(edge)
        else:
            backing["other_only"] += 1
            other_backed.append((edge, sorted(rels)))

    # The restriction has a failure mode of its own: if graphify parses a file to zero
    # nodes, that file leaves `common_files` and every homegrown edge touching it is
    # excused rather than counted as a miss. That is exactly backwards — a total
    # extraction failure is the worst case, not an exempt one. So score it explicitly.
    missing_files = hg_files - gf_files
    excused = sorted(e for e in hg_edges - gf_edges
                     if e[0] in missing_files or e[1] in missing_files)

    return {
        "unrestricted": {
            "homegrown_edges": len(hg_edges),
            "missed_by_graphify": len(hg_edges - gf_edges),
            "examples": sorted(hg_edges - gf_edges)[:20],
        },
        "excused_by_restriction": {
            "homegrown_files_graphify_produced_no_nodes_for": sorted(missing_files),
            "homegrown_edges_thereby_excused": excused,
            "count": len(excused),
        },
        "shared_edge_backing": {
            "counts": dict(backing),
            "agreed_via_non_import_relation_only": other_backed[:40],
        },
        "files": {
            "homegrown_only": sorted(hg_files - gf_files),
            "graphify_only": sorted(gf_files - hg_files),
            "common": len(common_files),
            "homegrown_total": len(hg_files),
            "graphify_total": len(gf_files),
        },
        "raw": {
            "homegrown_edges": len(hg_edges),
            "graphify_edges": len(gf_edges),
        },
        "restricted": {
            "common_files": len(common_files),
            "homegrown_edges": len(hg_r),
            "graphify_edges": len(gf_r),
            "shared": len(hg_r & gf_r),
            "missed_by_graphify": sorted(hg_r - gf_r),
            "extra_in_graphify": sorted(gf_r - hg_r),
        },
        "restricted_undirected": {
            "homegrown_edges": len(hg_u),
            "graphify_edges": len(gf_u),
            "shared": len(hg_u & gf_u),
            "missed_by_graphify": sorted(hg_u - gf_u),
            "extra_in_graphify": sorted(gf_u - hg_u),
        },
    }


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--homegrown", required=True)
    ap.add_argument("--graphify", required=True)
    ap.add_argument("--json", help="write the full result here")
    ap.add_argument("--repo-root",
                    help="repo root; lets phantom third-party source_files be excluded "
                         "from graphify's file count")
    ap.add_argument("--limit", type=int, default=15,
                    help="examples printed per category (default 15)")
    args = ap.parse_args()

    hg_edges, hg_files, hg_meta = load_homegrown(args.homegrown)
    gf_edges, gf_files, gf_meta, gf_rels = load_graphify(args.graphify, args.repo_root)
    result = compare(hg_edges, hg_files, gf_edges, gf_files, gf_rels)
    result["homegrown_meta"] = hg_meta
    result["graphify_meta"] = gf_meta

    if args.json:
        with open(args.json, "w", encoding="utf-8") as fh:
            json.dump(result, fh, indent=2, sort_keys=True)

    f = result["files"]
    r = result["restricted"]
    u = result["restricted_undirected"]

    print(f"homegrown : {hg_meta['file_count']:>5} files  {hg_meta['edge_count']:>5} internal edges")
    print(f"graphify  : {gf_meta['file_count']:>5} files  {gf_meta['edge_count']:>5} internal edges "
          f"({gf_meta['node_count']} nodes, {gf_meta['link_count']} links, directed={gf_meta['directed']})")
    print(f"file sets : {f['common']} common | {len(f['homegrown_only'])} homegrown-only | "
          f"{len(f['graphify_only'])} graphify-only")
    print()
    print(f"-- restricted to the {r['common_files']} common files --")
    print(f"homegrown {r['homegrown_edges']} | graphify {r['graphify_edges']} | shared {r['shared']}")
    print(f"MISSED by graphify : {len(r['missed_by_graphify'])} (directed) / "
          f"{len(u['missed_by_graphify'])} (undirected)")
    print(f"EXTRA  in graphify : {len(r['extra_in_graphify'])} (directed) / "
          f"{len(u['extra_in_graphify'])} (undirected)")

    ex = result["excused_by_restriction"]
    print(f"\nunrestricted misses: {result['unrestricted']['missed_by_graphify']} "
          f"(of which {ex['count']} excused by the restriction)")
    if ex["homegrown_files_graphify_produced_no_nodes_for"]:
        print("  WARNING files homegrown indexed but graphify produced no nodes for: "
              f"{ex['homegrown_files_graphify_produced_no_nodes_for'][:5]}")
    if gf_meta.get("phantom_source_files_excluded"):
        print(f"  phantom (non-existent) source_files excluded from graphify's count: "
              f"{gf_meta['phantom_source_files_excluded']}")

    if u["missed_by_graphify"]:
        print(f"\nmisses (undirected, first {args.limit}):")
        for s, d in u["missed_by_graphify"][:args.limit]:
            print(f"  {s}  <->  {d}")

    b = result["shared_edge_backing"]["counts"]
    print(f"\nof the {r['shared']} agreed edges: {b.get('import_family', 0)} backed by an "
          f"import-family relation, {b.get('other_only', 0)} only by calls/references")

    print("\ngraphify relations:", gf_meta["relations"])
    print("graphify confidence:", gf_meta["confidence"])
    if hg_meta["dangling_edges"]:
        print(f"homegrown dangling edges: {len(hg_meta['dangling_edges'])} "
              f"e.g. {hg_meta['dangling_edges'][:3]}")

    return 0


if __name__ == "__main__":
    sys.exit(main())
