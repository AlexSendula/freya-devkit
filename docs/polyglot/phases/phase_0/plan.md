# Phase 0 — the substrate spike

**Status:** executed 2026-08-19. Results in [`findings.md`](findings.md).

Phase 0 is a gate, not a deliverable. Nothing in Phases 1–5 starts until the substrate
decision is **measured rather than argued** — [`../../spec.md`](../../spec.md) §9.

## What is being decided

Whether [graphify](https://github.com/Graphify-Labs/graphify) can serve as the polyglot
backend behind the substrate contract, with the homegrown resolver kept as the zero-install
floor. The blocking question is not "is graphify good" but **"does graphify lose anything we
currently have"** — because a lost edge narrows a behavior's static closure, the behavior is
not flagged as affected, and a regression walks through the wrap-up gate.

## Targets

| Repo | Language | Role |
|---|---|---|
| `acme-site-testbed` | TypeScript, 232 files | the §9.1 diff. Homegrown's home turf, so any miss here is a straight regression |
| `freya-devkit` | Python, 51 files | dogfooding, and the second language homegrown claims |
| `java-graph-fixture` | Java, 6 files | the polyglot gain. Purpose-built for this spike |

**On the Java fixture.** Homegrown produces nothing at all for Java, so there is no diff to
run and no baseline to regress against. The only available yardstick is an edge set written
down **by hand, before the tool was run**
([`data/java_ground_truth.json`](data/java_ground_truth.json)). That is why it is hand-built
rather than a real repo: every edge is knowable, so a miss is provable rather than arguable.

Its sharpest property is deliberate: 9 of its 11 edges are derivable from `import` statements,
and 2 are same-package inheritance, where Java requires no import at all. An import-only
parser scores 9/11 and looks healthy while missing precisely the inheritance spine.

## The five tests

Each maps to a subsection of spec §9. Only the first can block.

| # | Test | Acceptance | Blocking |
|---|---|---|---|
| 9.1 | **Under-reporting.** Diff both backends' edge sets in both directions on the same repo | graphify does not under-report on languages homegrown covers. Any miss explained, not tallied | **yes** |
| 9.2 | **Deletion and staleness.** Delete a file, rename a function, remove an import, then `--update` | stale nodes removed, nothing dangles | no |
| 9.3 | **Reproducibility.** Build twice on identical input and diff | content-stable. Byte-instability tolerable only for gitignored output | no |
| 9.4 | **Config coverage.** Run over SQL, YAML, HCL and manifests | either answer is fine; the point is to stop guessing | no |
| 9.5 | **Degradation and output location.** Absence behaviour; confirm it writes to `graphify-out/` | does not own or clear `knowledge-base/.graph/` | no |

§9.5's second half exists because [ADR-017](../../../decisions/ADR-017-behavior-json-is-committed.md)
carries a revisit trigger: if a substrate owns or clears `.graph/`, then `behavior.json` — the
one artifact that cannot be regenerated from source — has to move out. Confirm rather than
assume.

## Method

Comparison is at **file level**, in both directions, restricted to files both tools indexed.

Folding to file level is forced: graphify records symbol-level `calls` and `inherits` that
homegrown has no equivalent for, so a symbol-level diff would measure a granularity
difference rather than a coverage difference.

Restricting to common files is the load-bearing choice. The unrestricted diff is dominated by
*file selection* — one tool indexing markdown or configs the other skips — which says nothing
about extraction quality. Both views are reported so the restriction cannot hide anything.

Two guards against the harness flattering the result:

- **Provenance of agreement.** Folding symbol edges to file level could let graphify "cover" an
  import edge via an unrelated call between the same two files. So for every agreed edge, the
  harness records whether graphify backs it with an import-family relation or only with a
  call. Agreement resting on a different fact is not agreement.
- **Directed and undirected views.** graphify's graph carries `"directed": false`. Comparing
  directed pairs alone would report a miss for an edge it found but stored the other way
  round; comparing undirected alone would hide a genuine direction loss. Both are reported.

## Harness

Re-runnable, so the numbers can be checked rather than believed.

| File | Does |
|---|---|
| [`harness/compare_graphs.py`](harness/compare_graphs.py) | normalises both formats to file-level edge sets and diffs them |
| [`harness/check_java.py`](harness/check_java.py) | scores a graphify graph against the hand-written Java ground truth |

```bash
python3 harness/compare_graphs.py \
  --homegrown ../../../../knowledge-base/.graph/graph.json \
  --graphify  ../../../../graphify-out/graph.json
```

## Known limits of this spike

Stated up front so the findings are not read as broader than they are.

- **One real language compared.** Only TypeScript produced a two-sided diff. Python was run,
  but homegrown yielded zero internal edges on `freya-devkit`, so there was nothing to compare
  against — itself a finding. Go and JavaScript are untested.
- **The Java fixture is synthetic and was never compiled.** No JDK on this machine. Both
  substrates parse rather than compile, so this does not invalidate the result, but a syntax
  error would still parse partially. The check is that all six files yielded symbols.
- **Java measures the gain, not a regression.** There is no homegrown baseline to lose against.
- **Absolute numbers are repo-specific.** They bound nothing about repos with different shapes.
