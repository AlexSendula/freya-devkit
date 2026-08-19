# Phase 0 — the substrate spike

Executed **2026-08-19**. The gate for Track B: nothing in Phases 1–5 starts until the
substrate decision is measured rather than argued ([spec §9](../../spec.md)).

| File | What it is |
|---|---|
| [`plan.md`](plan.md) | what was tested, on what, by what method, and the limits of the method |
| [`findings.md`](findings.md) | **the result and the verdict** — start here |
| [`harness/`](harness/) | the scripts that produced the numbers, so they can be re-run rather than believed |
| [`data/`](data/) | raw output: edge diffs, the Java ground truth, per-repo measurements |

## Reproducing

```bash
uv tool install "graphifyy[sql,terraform]"
```

Then, from this directory, for any repo with both graphs built:

```bash
python3 harness/compare_graphs.py --homegrown <repo>/knowledge-base/.graph/graph.json --graphify <repo>/graphify-out/graph.json
```

The Java fixture is scored against a hand-written ground truth rather than a diff, because
the homegrown resolver produces nothing for Java and there is no baseline to regress against:

```bash
python3 harness/check_java.py --graphify ~/Documents/projects/java-graph-fixture/graphify-out/graph.json --truth data/java_ground_truth.json
```

## Lifecycle

This directory follows [the rule in `../../README.md`](../../README.md): it is a working
record, it gets distilled into ADRs and the live docs when Track B ships, and then the whole
`docs/polyglot/` tree is deleted. Git history keeps it.

Decisions made here belong in [`../../decisions.md`](../../decisions.md); reversals and
measurements belong in [`../../log.md`](../../log.md). `findings.md` is the evidence those
two point at, not a substitute for either.
