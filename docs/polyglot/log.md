# Track B — working log

Newest last. See [README.md](README.md) for what belongs here and what happens to it.

---

## 2026-08-19 — `behavior.json` is committed (groundwork, pre-vision)

**Status:** shipped as `1fa8ff3`. Distilled already —
[ADR-017](../decisions/ADR-017-behavior-json-is-committed.md). Recorded here because it
constrains Track B and carries a revisit trigger that fires during it.

### Decision

`knowledge-base/.graph/.gitignore` names `graph.json` and `classifications.json` instead of a
blanket `*`, so `behavior.json` is tracked. `exercises` are sorted by path at write time.

### Why it came up now

Backlog item 7, raised during the docs restructure. `behavior.json` was ignored by a rule
nobody had weighed: the `*` came from dogfooding finding F8, filed as a bug when the
`docs/.code-graph/` → `knowledge-base/.graph/` rename lost an existing ignore, for a directory
that at the time held only the parse cache. `behavior.json` shipped in Phase 2 and inherited it.

### Measurement worth carrying

**The code graph is content-reproducible but not byte-reproducible.** Two builds of identical
input, diffed: same file set, same edge set, **10 of 10 differing entries were pure reordering**
inside `imports` arrays — Python set iteration order.

Two consequences, both load-bearing for Track B:

1. Regenerating the graph never invents or loses edges, so a substrate change cannot silently
   corrupt derived data. Reassuring, and worth re-measuring against whatever substrate Track B
   picks — *do not assume a new substrate inherits this property.*
2. Anything derived from the closure inherits the instability. That is why sorting
   `behavior.json` was a precondition for committing it, and it is a property any new substrate
   has to provide or have wrapped.

### Rejected, with a trigger that fires in Track B

Moving `behavior.json` out of `.graph/` to `knowledge-base/behavior.json` was recommended first,
on the reasoning that `.graph/` is the *substrate's* directory and a substrate swap could clear
it — taking the one unrebuildable artifact with it. Checking the code refuted that for today:
nothing does `rmtree` on `.graph/`, and `GraphOps.clear()` unlinks `graph.json` then calls
`rmdir()`, which fails harmlessly while other files are present.

**→ Track B action:** if the substrate decision introduces something that owns or clears
`.graph/` wholesale — likely if graphify becomes the standard substrate — this becomes real and
`behavior.json` must move out. Check it when the fork is decided, not after.

### Doc impact — already applied

- `../architecture.md` — Output Artifacts tree and the paragraph under it
- `../skill-reference.md` — File Locations table gained an `In git?` column
- `../decisions/README.md` — ADR-017 indexed
- `../backlog.md` — item 7 struck through and closed

### Site impact — outstanding

Nothing yet. At feature end this is a candidate entry for `evolution.html`: a rule written for
one artifact quietly applied to a different one for two phases, and the reasoning was
reconstructed rather than recorded. Small, but it is exactly the shape that chapter collects.

---

## Open questions carried into the vision

Not decisions yet — the things the Track B brainstorm has to answer first.

1. **The substrate fork.** Homegrown per-language resolvers (keeps stdlib-only, zero-install)
   vs adopting a dependency (graphify/tree-sitter). Recorded lean, 2026-07-12, not final:
   graphify as the *standard* substrate, not a tiered opt-in.
2. **Does unifying the code graph and behavior graph conflict with vision §6?** §6 keeps
   `behavior.json` a sibling of `graph.json` precisely so the substrate choice stays decoupled
   from the behavior layer. The graphify lean wants to unify them. The research must resolve
   whether unification subsumes §6 or contradicts it — the lean is not settled until it has.
   ADR-017 sits on the same seam.
3. **One graph or two?** Config-as-code edges (Helm → manifests → images, Dockerfile `COPY`)
   are reference and deployment edges, not import edges. Possibly a second graph rather than
   more languages in the first.
4. **What does the shape detector do on a Java repo?** `project_shape.classify()` calls a repo
   greenfield at 0 internal edges. A Java or Helm repo produces exactly zero today, so a large
   existing codebase is confidently misread as greenfield. The detector converts substrate
   blindness into a wrong answer — fixing the substrate may fix this for free, or may not.
