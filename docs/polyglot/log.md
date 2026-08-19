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

## 2026-08-19 — the design brainstorm

**Outcome:** [`spec.md`](spec.md). This entry records what *changed* during the conversation,
because the reversals are the part that will not be in any diff.

### Reversals — each of these was my recommendation before it was overturned

| First proposed | Landed on | Why it flipped |
|---|---|---|
| Four graphs (code, behavior, docs, resource) | **Two new + the existing one** | Config edges are one hop and never branch. A three-node chain that does not branch is a list; a graph earns its keep on transitive closure |
| Resource graph for Docker/K8s, Helm deferred to v2 | **Config dropped entirely** | Asked what consumes it and there was no answer. The code graph already tells docs/specs/behaviors what to re-check |
| A config identifier index instead | **Also dropped** | Invented to replace the resource graph, then graphify turned out to parse YAML/JSON/HCL deterministically. §9.4 confirms or refutes |
| Use graphify `--code-only`, skip the semantic pass | **Semantic pass in, as a second trust tier** | The objection was that blast radius gates wrap-up. That argues for *labelling* inferred edges, not discarding them — and graphify already tags EXTRACTED vs INFERRED, which maps onto ADR-009's two tiers |
| Semantic pass needs an API key | **Runs on the existing subscription** | freya already drives `claude -p` / `copilot -p` headlessly (ADR-015), and graphify ships as a skill that uses the host assistant's model |
| Manifest parsers are extra work | **Free** | graphify already extracts package deps from `pom.xml`, `go.mod`, `pyproject.toml` |
| Docs edges anchored at `path:line` | **Anchored at section** | Line numbers shift when anyone inserts a paragraph, and the real question is *which section is wrong* |
| Fold graphify's symbol edges down to file level | **Symbol as an optional refinement on a file anchor** | Symbol-level is sharper, but names are not durable — vision §6 already learned this, which is why behaviors carry stable ids. Keeping the file anchor means the floor is current behaviour |
| SCIP as a documented future backend | **Out of the design** | User call. It also requires a green build and each language's toolchain, which inverts the goal |
| "Merging the graphs is mechanically impossible because ADR-017 commits one of them" | **Overstated** | `behavior.json` *is* reproducible — by rerunning the suite. The distinction is cost and preconditions, not possibility. The separate-files conclusion survives on producer isolation instead |

### Corrections to earlier claims in this file

- **The `.graph/`-ownership trigger looks unlikely to fire.** graphify writes to its own
  `graphify-out/`, so it never touches `knowledge-base/.graph/`. ADR-017's revisit condition
  stays on the books as a defensive check — §9.5 confirms it rather than assuming.
- **graphify is not RAG.** No embeddings, no vector store. Deterministic tree-sitter AST plus
  Leiden clustering on graph topology. It is the same category of thing as our resolver, which
  is what makes the comparison in §9.1 meaningful.

### Findings worth keeping

- **The graph's per-file `category` field is dead.** Written by `_categorize_file`
  (`graph_ops.py:309`) on every build, read by nothing. Three unrelated things in this repo are
  called "category"; the other two are live. Removal is a pre-existing cleanup this work
  surfaced, not something graphify causes.
- **Our incremental update handles deletions correctly** (`graph_ops.py:1216-1218` removes the
  entry and rebuilds all dependents). That is the bar graphify has to clear in §9.2.
- **62 distinct `path:line` citations** already exist across `docs/` — the docs graph parses
  what is written, it does not infer.
- **The governance graph already exists, undeclared.** `SPEC → BEHAVIOR → TEST → CODE` plus ADR
  supersession and the authority order is a typed graph walked ad hoc by re-reading frontmatter.
  Filed in [`../backlog.md`](../backlog.md) rather than built — materialising it means another
  derived cache to keep in sync.

---

## 2026-08-19 — Phase 0, the substrate spike

**Outcome:** [`phases/phase_0/findings.md`](phases/phase_0/findings.md). The gate passes.
This entry records only what *changed*, plus measurements worth carrying.

### The headline, so it is not restated from memory later

graphify missed **0 of 608** homegrown edges on the testbed and gained 18 real ones; per-file
reverse blast radius was identical on 220 files, larger on 12, **smaller on none**. On the Java
fixture it scored **11/11 including both same-package inheritance edges**, with no false
positives. Verified by three independent derivations and two adversarial refutation passes.

### Reversals and refuted claims — mine unless noted

| Claimed | Actually | How it was caught |
|---|---|---|
| The `--force` flag guards against a shrinking graph, so deletion may be unsafe | It does not fire on code deletion at all — a 62% node drop went through silently. It protects the curated/LLM layer | Tested the threshold instead of reading the help text |
| `graphify` is skill-mediated, so headless determinism will be awkward | `graphify update <path>` is a full headless deterministic build. No LLM, no assistant | Ran `--help` rather than trusting the README |
| freya-devkit's empty graph is caused by the depth-2 classification limit | Caused by `'scripts'` in `always_exclude_dirs`, matched against *any* path component. The depth limit is real but latent | Read `_should_exclude` after the classification dump did not explain it |
| Removing the `'scripts'` exclusion fixes freya-devkit's graph | Necessary but nowhere near sufficient — 10→51 files, still **1** internal edge, and it dangles. Python sibling imports are tagged `external:` | Patched the exclusion set and rebuilt |
| `app/api/auth/[...nextauth]/route.ts` is skipped because of Next.js catch-all bracket syntax | Skipped because the string `...nextauth` **contains `.next`**, caught by the gitignore substring branch at `:637`. A sibling `[...path]` route survives | Verification agent; my hypothesis was wrong |
| The 18 extra edges share one root cause, probably path aliases | Two causes, and the alias hypothesis is refuted — homegrown resolves `@/` correctly. 16 are `import type`, 2 are a barrel import | Verification agent read all 18 against source |
| graphify under-reports third-party deps ~100%, a real regression | It names 74 of 79 packages, but only via `package.json`; there are 0 source→package links. Not a practical regression: `external:` exists in freya **only to be filtered out**, and `dependency-vulnerability-check` reads `package.json` directly | Skeptic raised it; checked the consumers |
| §9.4 confirms graphify parses YAML/JSON/HCL, retiring the config identifier index | **Refuted for YAML.** No YAML support and *no warning*. JSON is manifest-only. SQL and HCL work, but only behind pip extras | The §9.4 fixture |

### The §9.4 correction matters more than it looks

The reversal table above (2026-08-19 brainstorm) retired the config identifier index because
"graphify turned out to parse YAML/JSON/HCL deterministically." **That premise is false for
YAML.** The *conclusion* — no config graph — still stands on its independent reasoning (one hop,
nothing consumes it), but the justification must not be reused, and anything else resting on it
should be re-derived.

### Measurements worth carrying

- **Reproducibility, measured with the cache destroyed.** Node and link sets identical; every
  link field identical; drift confined to `community`/`community_name` (6 of 2901 nodes). Same
  profile as homegrown — content-stable, byte-unstable — but in a field the contract never
  reads. Measured with the Leiden extra **absent**; re-check if it is installed.
- **`"directed": false` is a contract hazard, not a data loss.** Direction is recoverable from
  ordered `source`/`target`, and `graphify affected` traverses correctly. But honouring the
  flag inflates mean blast radius **5.0 → 188.2 files** (median 1 → 218). Phase 2 must read
  links as tuples and pin it with a test.
- **`EXTRACTED`/`INFERRED` is not deterministic/model-judged.** Both come from the AST pass with
  no API key. And **0 file-level edges anywhere rest solely on an INFERRED link** (0/131 devkit,
  0/11 Java, 3 self-loops on the testbed). The ADR-009 mapping in §4 buys nothing at the
  contract's granularity today.
- **Size, not speed, is the scaling risk.** ~9.3 KB/file against homegrown's ~0.5 KB. Wall-clock
  is comparable (3.0 s cold on 292 files); a 5,000-file repo implies ~46 MB, `json.load`ed by
  every skill on every invocation. Untested at that scale.
- **graphify indexes everything not gitignored** — verified with a control. Opposite philosophy
  from homegrown's whitelist, and the direct reason homegrown silently lost 40 files.

### Findings about our own code, not graphify

- **freya-devkit cannot graph itself:** 10 of 50 tracked Python files, **0 internal edges**,
  exit 0, reported as success. It therefore reads as *greenfield* to `project_shape.classify()`
  — a second instance of the open question the spec expected only Java to raise.
- Four resolver defects, all in `graph_ops.py`: the `'scripts'` exclusion (`:569`), `import type`
  invisibility (`:53`, `:67`), the `.next` substring match (`:637`), and bare-specifier sibling
  imports tagged `external:`.
- **Phase 1's stated regression gate does not work.** `test_graph_ops.py` is 18 tests over
  synthetic fixtures, all green while the resolver is this broken. Freezing "no behaviour
  change" against it would preserve nothing. Hence the recommendation to fix the four defects
  *before* Phase 1 and re-run §9.1 against a corrected baseline.

### Process note worth keeping

The spike's own artifacts had two integrity defects, both found by the completeness critic and
both fixed: `build_seconds: 2.4` was recorded for three different workloads (transcription, not
measurement), and the SQL/Terraform extras were installed **after** all three graphs were built,
so the documented environment was not the one that produced the numbers. All three graphs were
rebuilt under the documented environment; **608/0/18 and 11/11 held unchanged.**

### Doc impact — outstanding

- `spec.md` §4 — the trust-tier mapping onto `EXTRACTED`/`INFERRED` needs rewriting
- `spec.md` §9.4 / this log's brainstorm entry — the YAML premise is refuted
- `../backlog.md` — the four homegrown resolver defects
- `evolution.html` at feature end — the `--force` misread and the `[...nextauth]` misdiagnosis
  are both good entries: each was a confident wrong reading of a *cause*, corrected by testing

---

## ~~Open questions carried into the vision~~ — ANSWERED by the brainstorm

Kept for the record. All four are resolved in [`spec.md`](spec.md); the reasoning is in the
reversal table above.

1. ~~**The substrate fork.**~~ → **Neither branch.** A contract with two backends: homegrown
   stays as the zero-install floor, graphify becomes the polyglot backend. The 2026-07-12 lean
   toward graphify-as-*standard* is superseded — it is a backend, not the standard.
2. ~~**Does unifying the graphs conflict with vision §6?**~~ → **Moot; unification is dropped.**
   §6 keeps `behavior.json` a sibling so the substrate choice stays decoupled, and a contract
   *reinforces* that rather than fighting it. Artifacts stay separate, joined on file path, and
   a third (`docs.json`) joins them on the same terms.
3. ~~**One graph or two for config-as-code?**~~ → **Neither.** No config graph at all. The
   relationships are one hop and nothing consumes them.
4. ~~**What does the shape detector do on a Java repo?**~~ → Still calls it *greenfield* at 0
   internal edges, so still wrong today. Phase 2 should fix it for free by giving Java real
   edges; spec §10 requires re-verifying rather than assuming that.
