# Phase 0 — findings

**Measured 2026-08-19.** Method and its limits: [`plan.md`](plan.md). Raw numbers:
[`data/measurements.json`](data/measurements.json).

---

## Verdict

**The gate passes. Proceed to Phase 1 — but fix the homegrown resolver first.**

graphify does not under-report against the homegrown resolver on the language homegrown
covers best, and it produces a correct graph for a language homegrown cannot see at all. The
blocking test is not close: **0 misses out of 608 edges**, with 18 real edges gained.

The sequencing condition is not about graphify. It is that Phase 0 found the homegrown
resolver to be substantially broken, and Phase 1's plan is to freeze its current behaviour
behind a permanent contract using a test suite that cannot observe the breakage.

---

## The five tests

| | Test | Result |
|---|---|---|
| 9.1 | Under-reporting | **PASS** — 0 of 608 missed; 18 gained; all agreement independently import-backed |
| 9.2 | Deletion and staleness | **PASS** — stale nodes removed, 0 dangling links |
| 9.3 | Reproducibility | **PASS** — content-stable; drift confined to clustering metadata |
| 9.4 | Config coverage | **MIXED** — SQL and Terraform yes, YAML no. Refutes a spec premise |
| 9.5 | Degradation and output location | **PASS** — ADR-017's revisit trigger does not fire |

### 9.1 — under-reporting (blocking)

On the testbed, restricted to the 232 files both tools indexed:

| | homegrown | graphify |
|---|---|---|
| files indexed | 232 | 292 |
| internal edges | 608 | 626 |
| **missed** | — | **0** |
| extra | — | 18 |

All **608** agreed edges are backed by an import-family relation on graphify's side, not by a
call that happens to cross the same two files. The agreement is real, not an artifact of
folding symbol edges down to file level.

The measurement that matters most is not the edge count but the query built on it: across all
232 files, **reverse blast radius was identical for 220, larger for 12, and smaller for zero.**
No file's blast radius shrank.

Unrestricted, graphify "misses" exactly one edge — `components/providers.tsx →
components/accessibility`. That is homegrown failing to resolve a barrel import to a directory
that has an `index.tsx`; graphify resolves it correctly into two edges. The single miss is a
homegrown defect.

**The 18 extra edges are all real. Zero mis-wiring.** Two independent causes, verified against
source:

- **16 of 18** — `import type { X } from '...'`, invisible to homegrown's regex
- **2 of 18** — the barrel import above

The path-alias hypothesis was **refuted**: homegrown resolves `@/lib/db-types` correctly. The
aliases in those lines were a red herring.

### 9.2 — deletion and staleness

Deleting a file, renaming a method and removing an import in a single `update`: nodes 40 → 35,
deleted file gone, stale `totalUnits` gone, renamed `sumUnits` present, **0 dangling links**.

One node survives — `inmemoryitemstore`, with `source_file: ""`. That is **correct, not stale**:
`AuditedItemStore.java:8` still says `extends InMemoryItemStore`, so graphify is faithfully
recording "inherits from a type I cannot locate."

→ **Phase 2 note:** unresolved-reference placeholders are distinguishable from real nodes
*only* by an empty `source_file`. The contract's mapping must filter on that.

The `--force` flag reads like a staleness guard but is not one: a 62% node drop (40 → 15) went
through without it and without any warning. It protects the curated/LLM layer, which is backed
up separately.

### 9.3 — reproducibility

Measured with `graphify-out/` **destroyed** between runs, so the SHA256 cache could not mask
instability.

- Small repo: byte-identical, including community assignment.
- 2,901-node repo: node and link sets identical, every link field identical — **6 nodes differ
  in `community` and `community_name`, and nothing else.**

Content-stable, which is the acceptance bar. This is the same profile as the homegrown
resolver, which is content-stable but byte-unstable through `imports` set ordering; the
difference is that graphify's instability sits in a field the contract does not read.

**Caveat:** `graspologic` (Leiden) is not installed, so a fallback clusterer was in use.
Installing the `leiden` extra may change this.

### 9.4 — config coverage

Fixture: [`fixtures/config/`](fixtures/config/) → [`data/config_result.json`](data/config_result.json).

| Format | Result |
|---|---|
| SQL | **works** with `graphifyy[sql]`. Tables, views, FK `references`, view `reads_from` — all `EXTRACTED` |
| Terraform / HCL | **works** with `graphifyy[terraform]`. Resolved `cloudfront → s3` interpolation |
| `package.json` | **works** — manifest dependencies extracted |
| YAML (k8s, compose) | **nothing, and no warning** |
| generic data JSON | nothing |

SQL and HCL warn clearly when their extra is missing. **YAML fails silently**, which is the
worse failure mode.

**This refutes a premise in the spec.** [`log.md`](../../log.md) retired the config identifier
index on the grounds that *"graphify already parses YAML/JSON/HCL deterministically."* YAML it
does not parse, and JSON only as a manifest. The *conclusion* — no config graph — survives on
its independent reasoning (the relationships are one hop and nothing consumes them), but the
stated justification was wrong and should not be reused.

### 9.5 — degradation and output location

graphify writes **only** to `graphify-out/`. `knowledge-base/.graph/` was untouched in both
repos. **ADR-017's revisit trigger does not fire — `behavior.json` does not need to move.**

Absent, it exits `127`, and the homegrown resolver is unaffected.

---

## What Phase 0 found that it was not looking for

The spike was designed to evaluate graphify. The most consequential findings are about
**freya's own resolver.**

### freya-devkit cannot graph itself

| | |
|---|---|
| Python files | 50 tracked (52 on disk) |
| files in the graph | **10** |
| internal edges | **0** |
| reported | `Built dependency graph: 10 files scanned`, exit 0 |

Two independent causes, both verified:

1. **`'scripts'` is in `always_exclude_dirs`** (`graph_ops.py:569`), and `_should_exclude`
   matches *any* path component. Every freya skill keeps its code in
   `skills/<skill>/scripts/`, so 40 files are dropped. `docs` and `knowledge-base` are in the
   same set — which lands directly on Phase 4.
2. **Bare-specifier imports are misclassified as third-party.** Removing the exclusion raises
   the scan from 10 to 51 files and still yields **one** internal edge, which is dangling.
   `import behavior_graph` — a sibling module — is recorded as `external:behavior_graph`.

So the exclusion is necessary but nowhere near sufficient. On the same repo graphify finds
**131** internal file-level edges.

**Consequence:** `project_shape.classify()` calls a repo *greenfield* at 0 internal edges, so
**freya-devkit reads as a greenfield project to its own tooling.** That is a second, independent
instance of the open question the spec expected only Java to raise.

### Two more homegrown defects, found while explaining the diff

- **`import type` is invisible** (`graph_ops.py:53`, `:67`) — 16 of the 18 missed edges.
- **`.next` is substring-matched** (`graph_ops.py:637`) — `app/api/auth/[...nextauth]/route.ts`
  is excluded because the string `...nextauth` contains `.next`. A sibling catch-all route
  `[...path]` survives. My initial guess that Next.js bracket syntax was the cause was **wrong**;
  the discriminator is purely the substring.

### The two-tier trust design is unexercised

`EXTRACTED` / `INFERRED` does **not** mean deterministic / model-judged. Every run here was
deterministic AST with no API key, and still produced `INFERRED` edges — they are type
resolution, e.g. `store.save(...)` on a declared `ItemStore`. All 12 on the Java fixture were
checked by hand and all are correct.

More importantly: **across all three repos, the number of file-level edges resting solely on an
INFERRED link is zero** — 0 of 131 on devkit, 0 of 11 on Java, and all 3 on the testbed are
self-loops. Spec §4 maps this split onto ADR-009's two trust tiers and threads it through
Phases 2–3. At the granularity the contract actually uses, it currently buys nothing.

→ **Do not build the two-tier machinery on this axis** until the semantic pass (§4.1), which is
the one place the distinction could become load-bearing, has actually been run.

### Exclusions mostly come free

graphify indexes **everything not gitignored** — verified with a control: an unconventionally
named gitignored directory was skipped, an unconventionally named non-ignored one was indexed.
That is the opposite philosophy from homegrown's whitelist, and it is why homegrown silently
lost 40 files that graphify found.

→ Open question 3 narrows: gitignore is honoured, so exclusions beyond it need a post-filter.
There is no CLI flag.

### Direction survives, but only per-link

`graph.json` declares `"directed": false`, and the canonical NetworkX loader honours it,
returning a `Graph` with no `.predecessors()`. Measured cost of honouring it: mean blast radius
**5.0 → 188.2 files**, median **1 → 218**. Blast radius degenerates to "the repo."

But direction is **not lost from the data** — `source`/`target` are ordered with verified-consistent
semantics per relation, and `graphify affected` traverses correctly (querying a leaf returns
only its one caller).

→ **Phase 2 must read links as ordered tuples, never load the graph as undirected, and pin that
with a regression test.**

### Third-party edges are not carried across

graphify names 74 of the testbed's 79 external packages — but those come from `package.json`
manifest parsing. There are **zero** links from any source file to any package node. Homegrown
records 491 such references.

This is a genuine difference, but **not a practical regression**: `external:` exists in freya
only to be filtered out (`project_shape.py:48`, `graph_ops.py:1159`, `:1226`), and
`dependency-vulnerability-check` reads `package.json` directly. Nothing consumes it. Recorded
so that "which files import react?" is known to be answerable by neither side.

---

## Performance

| Repo | homegrown | graphify cold | graphify warm | graph.json |
|---|---|---|---|---|
| testbed (232 / 292 files) | 2.42 s | 3.01 s | 2.12 s | 2.8 MB |
| freya-devkit (10 / 109 files) | 0.13 s | 1.98 s | 1.54 s | 3.3 MB |
| java fixture (0 / 8 files) | n/a | 0.16 s | 0.12 s | 47 KB |

Comparable wall-clock while doing far more work. **The size is the thing to watch:** ~9.3 KB
per file against homegrown's ~0.5 KB, a 22× artifact. Every skill `json.load`s this on each
invocation, so a 5,000-file repo implies roughly a 46 MB graph. Untested at that scale.

---

## Not tested — carried into Phase 2

Stated so the verdict is not read as broader than the evidence.

- **Scale.** Largest repo was 232 files. No memory measurement, no load-time measurement.
- **A polyglot repo.** Every target was single-language, so the spec's second-ranked risk —
  cross-language mis-wiring — is untouched.
- **graphify's cache invalidation.** `manifest.json` keys on `mtime`, `ast_hash`, `seen`,
  `semantic_hash` — **no tool version, no extras set, no config hash.** Upgrading graphify or
  adding a language extra invalidates nothing; the old-parser graph is served until file
  contents change. No corrupt-cache test either, which is the exact ADR-005 silent-empty
  failure the contract exists to prevent.
- **Git operations.** Branch switch, rebase and old-commit checkout all rewrite mtimes.
- **Supply chain.** `graphifyy` 0.9.47 is pre-1.0, single-maintainer, 32 transitive packages,
  run recursively over a whole codebase, and installs a second `graphify-mcp` entrypoint. Not
  reviewed. The semantic pass — which does ship source to a model — was never run.
- **§9.2 on a real repo.** It ran once, on the 6-file synthetic fixture. The homegrown bar is
  "removes the entry *and rebuilds all dependents*"; only the first half was checked.

---

## Addendum, same day — §9.1 re-run against the corrected baseline

The recommendation below was accepted, the six resolver defects were fixed
([backlog item 9](../../../backlog.md), [CD-14](../../decisions.md)), and §9.1 was re-measured.
**The blocking conclusion holds, and it no longer depends on homegrown being broken.**

| | before the repair | after |
|---|---|---|
| testbed — homegrown | 232 files, 609 edges | **234 files, 627 edges** |
| testbed — graphify missed | 0 | **0** |
| testbed — graphify extra | 18 | **1** |
| testbed — unrestricted misses | 1 | **0** |
| freya-devkit — homegrown | 10 files, **0 edges** | **50 files, 55 edges** |
| freya-devkit — shape detector | *greenfield* | **brownfield** |

The gap closed from 18 edges to 1 because homegrown now sees `import type` and resolves barrel
imports. The single remaining extra is a genuine graphify gain.

freya-devkit is now the **second two-sided diff** the spike lacked. It reports 1 miss and 5
extras — but the "miss" is `installer.py → freya_cli.py`, which homegrown invents from the
string literal `"from freya_cli import main\n"` at `installer.py:566`, written into a generated
launcher. graphify parses an AST and is correct to omit it. So across both repos graphify's only
apparent miss is an edge homegrown hallucinated.

**Regression check on code neither resolver was written against.** Six real libraries (jinja2,
requests, urllib3, yaml, rich, click — 190 files), old resolver vs new: **+693 internal edges,
31 dangling junk edges removed, 0 real edges lost.**

Two limits of that number, stated because they are easy to overclaim past. The 31 "losses" were
all edges pointing at `.`, the literal project root, so removing them is a fix rather than a
regression — but the count is still a *change*, and anything downstream that cached those edges
will see a diff. And an earlier automated pass reported "identical — 0 lost, 0 gained" on the
same packages; that was an artifact of the two versions sharing state, which is worth knowing
before trusting a no-change result.

**This also closes open question 4 a phase early.** Spec §10 assumed Phase 2 would fix the
greenfield misclassification for free by giving Java real edges. It was fixed here instead, so
the Phase 5 re-verification can be closed rather than carried.

---

## Recommendation

*Accepted and executed — see the addendum above.*

**Proceed to Phase 1, with the resolver fixes pulled in front of it.**

Phase 1 as specified moves the homegrown resolver behind the contract "with no behaviour
change; the existing test suite is the regression gate." That gate does not currently work:
`test_graph_ops.py` is 18 tests over synthetic `tempfile` fixtures, all green, while the
resolver excludes 40 of 50 files on its own repo and reports success. A no-behaviour-change
refactor pinned by a suite that cannot observe the behaviour preserves nothing — and what
would be frozen into the permanent zero-install floor is an empty graph on freya's own
language.

The four defects are known, small, and all in one file:

| Defect | Location |
|---|---|
| `'scripts'`, `'docs'`, `'knowledge-base'` in `always_exclude_dirs` | `graph_ops.py:569` |
| `import type` invisible to the regex | `graph_ops.py:53`, `:67` |
| `.next` substring match excludes `[...nextauth]` | `graph_ops.py:637` |
| bare-specifier sibling imports tagged `external:` | `_resolve_import_path` |

Fixing them first has a second payoff: it converts freya-devkit from a repo where the spike
could measure nothing into a **second real two-sided diff**, which this spike badly needs —
it currently has exactly one.

Then re-run §9.1 against the corrected baseline, so the contract is specified against a working
floor rather than a broken one. Expect the numbers to move: homegrown should recover most of
the 18 extras and the barrel edge.

**This is a sequencing constraint, not a reason to stop.** Freezing an interface does not
freeze bugs behind it, and every remaining gap above — scale, cache staleness, supply chain,
config coverage — blocks **Phase 2**, not Phase 1.
