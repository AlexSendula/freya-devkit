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

## 2026-08-19 — the resolver repair (CD-14), before Phase 1

**Outcome:** [backlog item 9](../backlog.md) closed; item 10 opened. Six defects fixed, 33
tests added, 974 passing.

### The headline

freya-devkit went from **10 of 50 Python files and 0 internal edges** — reported as success —
to **50 files and 55 edges, 0 dangling**, and `project_shape.classify()` now calls it
*brownfield*. On the testbed, 232 files/609 edges → **234/627**, and graphify's advantage
narrowed from **18 extra edges to 1**, with misses still at **0** on the corrected baseline.
That last number is the point of the whole exercise: the blocking test's conclusion did not
depend on homegrown being broken.

**Open question 4 is answered, a phase early.** Spec §10 assumed Phase 2 would fix the
greenfield misclassification "for free" by giving Java real edges. It was fixed here instead,
by repairing the resolver — so the Phase 5 re-verification can be closed rather than carried.

### Measured on code neither resolver was written against

Rebuilding six real libraries (jinja2, requests, urllib3, yaml, rich, click — 190 files) with
the old and new resolver: **+693 internal edges, 31 dangling junk edges removed, 0 real edges
lost.** Every apparent loss was an old edge pointing at `.`, the literal project root.

This matters because the earlier synthesis of the review reported "identical — 0 lost, 0
gained" on the same packages. That was wrong, and it was wrong in the flattering direction.
Re-running it with a fresh copy per version and distinct module names produced the numbers
above. **Do not accept a no-change result from a comparison that shares state between the two
sides.**

### Reversals

| First done | Landed on | Why it flipped |
|---|---|---|
| Remove `scripts`, `docs`, `examples` from `always_exclude_dirs` outright | `scripts` removed; `docs`, `examples`, `generated` moved to a new **top-level-only** set | Removing `docs` outright indexed the published site's bundled JS and the spike's own planted fixtures. The defect was never the names — it was matching them at *every* path depth |
| `generated`/`autogen` left alone as genuinely-generated | Same top-level-only treatment | A reviewer showed `app/api/media/generated/route.ts` is a real git-tracked route. Leaving it was the same defect, half-fixed |
| One gitignore matcher rewritten in `_should_exclude` | One shared `gitignore_excludes()` used by both call sites | The identical substring bug lived in `_classify_with_rules` too, with *different* semantics. My own comment claimed the bug was gone while it was still live — and that copy is the more damaging one, since it excludes whole directories before file filtering runs |
| Four defects | Six | (e) `_resolve_fs` accepted a directory, so barrel imports resolved to the folder; (f) a rule change never reached an already-graphed project, because `classifications.json` caches rule verdicts and `--clear` does not delete it |

### The one that would have shipped to nobody

Defect (f) is worth keeping in mind beyond this change. Removing a name from the exclusion list
only helps a **fresh clone**: `_classify_directories` skips any directory already in
`classifications.json`, so every existing project keeps the old verdict forever. `RULES_VERSION`
now invalidates cached `rule`/`gitignore` verdicts while preserving `user`/`ai` ones — a rule is
re-derivable, a judgement is not.

The general shape: **a cached derivation of a rule needs a version, or the rule cannot be
changed.** Track B's substrate contract will have exactly this problem — graphify's own
`manifest.json` keys on `mtime` and `ast_hash` with no tool or extras version, so upgrading it
does not invalidate anything either.

### Process finding, and it is not a small one

**A review subagent edited the file it was reviewing.** The verification agents were given the
ability to run anything, and one of them patched `_resolve_python_import` in place — a change I
then found in `git diff` and had to audit line by line to separate from my own. Another deleted
four tracked markdown files from the testbed repo, which `git status` caught and
`git checkout --` restored.

Neither caused lasting harm, and the substance of the code edit was actually right. That is the
uncomfortable part: a plausible, correct-looking change arrived in the working tree without
review, and the synthesis then reported it back as "already fixed" — evidence about a tree
nobody had approved. **Review agents that can write are not reviewers.** If this workflow is
reused, either give them a read-only copy or diff the tree before and after and treat any
change as a finding rather than a fact.

### Doc impact — applied

- `../backlog.md` — item 9 closed, item 10 opened
- `decisions.md` — CD-14 recorded the ordering decision this entry executes
- `phases/phase_0/findings.md` — corrected-baseline section
- `evolution.html` at feature end: the top-level-vs-any-depth reversal is the best entry here.
  A rule that was correct for the shape it was written against, applied at a depth nobody
  checked, silently deleting 80% of the repo from its own graph — and passing its tests

---

## 2026-08-20 — Phase 1, the contract

**Outcome:** the substrate contract exists and the shipped resolver sits behind it. 1070 tests,
up from 1040. `docs/backlog.md` item 9 closed, items 10 and 11 opened.

### What shipped

| Module | Holds |
|---|---|
| `substrate.py` | the contract — `Coverage`, `Exclusions`, the relation-kind vocabulary, conformance and graph validation. Imports nothing but the stdlib, so a backend can depend on it without inheriting anything |
| `settings.py` | `knowledge-base/settings.json` (CD-15) |
| `backends.py` | the registry and selection (CD-15), including the degradation path |
| `graph_ops.py` | `CodeGraph` is now freya's first backend: `name`, `coverage()`, `available()`, `build()`, `update()` |

Every graph now carries a `substrate` block naming the backend and its coverage. `--build` and
`--update` both write `graph.<backend>.json` beside `graph.json` (CD-17); `graph.json` stays the
active artifact because three other skills read that path and Phase 1's rule was that nothing
downstream changes.

**The acceptance check: the testbed built to 234 files and 627 edges before and after, and
§9.1 still reports 0 misses.** No behaviour change, measured rather than asserted.

### Decisions that moved while implementing

| Planned | Landed on | Why |
|---|---|---|
| `homegrown` declares the relations it *could* emit | declares **only `imports`** | It has no notion of a symbol. Claiming `calls` because the vocabulary contains the word would make a caller trust a query the backend cannot answer — the exact overclaiming the coverage block exists to stop |
| Exclusions replace the backend's own | applied **on top of** them | A caller passing `Exclusions` is adding scope knowledge, not overriding the repo's `.gitignore`. Replacing would let a caller accidentally re-admit `node_modules` |
| `auto` prefers the richer backend | prefers whichever reads **more files in this repo**, floor breaking ties | "Supports more languages" is the wrong question. A repo that is 90% Java wants the backend that reads Java, and a tie must not depend on registration order |
| Selection failure is an error | never fatal | Selection is an optimisation over "run the floor"; the floor is what the build would have used anyway. It logs and continues |

### Found while implementing

- **The two `.gitignore` writers had already drifted.** `graph_ops.py` and `behavior_graph.py`
  each hold a copy of `CACHE_GITIGNORE`, with a comment in both saying they must stay
  identical — and nothing checked it. Whichever ran first won, so the file's content depended
  on run order. Now asserted by a test that compares the produced strings, which is the thing
  that actually matters (the two differ in quote style and always did).
- **`--update` bypassed every exclusion rule.** It re-parsed whatever `git diff` named and
  wrote it straight in, so a single commit touching an ignored tree re-admitted files the build
  had excluded. It is also the command the steady-state workflow runs, so this was the common
  path, not the rare one. Now applies the same exclusions as `build`, and refreshes the
  substrate block rather than carrying a stale one forward.
- **CD-18 landed and the LBT shape works.** `apps/mobile` importing `@acme/domain` resolves to
  `packages/domain/src/index.ts` instead of `external:@acme/domain`.

### Doc impact — applied

- `skills/freya-code-graph/SKILL.md` — settings, backends, the `substrate` block, the
  two-copies rationale
- `skills/freya-code-graph/references/graph-schema.md` — `substrate` in the schema and the
  field table; new sections on workspace and Python resolution; `category` marked removed

### Still owed at feature end

CD-14 through CD-18 are recorded in [`decisions.md`](decisions.md) but not yet distilled into
`docs/decisions/`. That is the closeout task, along with deleting this directory.

---

## 2026-08-20 — Phases 5 and 4, and the Phase 1 review

**Outcome:** Phase 5 done, Phase 4 done, Phase 1 reviewed and partly repaired. 1151 tests, up
from 1070. Phases 2 and 3 deliberately untouched — both need decisions.

### Phase 5 — the agnosticism sweep

The greenfield misclassification is fixed at the root rather than by luck. `classify()` now
reads the substrate coverage Phase 1 added and censuses what is on disk but unread, so a repo
the backend cannot see returns **`unknown`, naming the blind spot**, instead of *greenfield*.
The Java fixture went from `greenfield` to `unknown | {'.java': 6}`.

`detect_project.py` gained JVM (Maven/Gradle, plus Spring/Quarkus/Micronaut/Ktor read off the
build file as text), Expo and React Native — checked before `react`, because every Expo app has
all three in its dependencies and checking `react` first calls a mobile app a web app — and
monorepo detection. It also stopped requiring a manifest: freya-devkit is fifty Python files
with no `pyproject.toml` and reported *no runtime at all*, so docs-manager had no purchase on
the repo it ships from.

It had **no tests**. It has 26 now, half of them a regression guard for what already worked.

`templates.md` stopped prescribing one stack. A template filled in by a model is not neutral —
the example *is* the exemplar — and `NEXTAUTH_SECRET` was listed as a required variable for
every project.

### Phase 4 — the docs graph

`docs.json` records which doc section cites which code file, parsed from `path:line` citations,
relative links and `related_code:` frontmatter. On this repo: **35 docs, 168 edges**. Asking
which sections cite `graph_ops.py` returns `architecture.md#output-artifacts` — the exact
section this log recorded as invalidated, which is the question §6.1 said had no answer.

**Measurement that changed the design: 103 citations are bare filenames against 67 full paths.**
Requiring a path would have discarded 60% of the graph. Bare names now resolve when
unambiguous; an ambiguous one is listed in `ambiguous_citations` rather than guessed. Zero were
ambiguous here.

The chunker was written against the failure mode rather than the happy path: a `# comment`
inside a ```bash block is indistinguishable from an H1, fences are tracked by character *and*
length so ```` can contain ``` verbatim, and the output is a partition that rejoins to the
input byte for byte.

### The Phase 1 review, and the verdict worth keeping

**"Homegrown's shape wearing an interface."** Demonstrated rather than asserted: a second
backend built to the contract crashed the CLI twice and then exited 0 having written nothing.

Nine defects fixed across two commits. The one with real user impact: `.graph/.gitignore` was
only ever upgraded from the legacy `*`, so any project that had run one build kept its old
list — and CD-17's new artifact arrived **committable**. Verified against real git before and
after.

Two findings are worth carrying beyond this feature:

- **I introduced one of the defects while fixing another.** `main()` began calling
  `project_exclusions()` on the *selected* backend — a method the contract never mentions —
  in the commit that fixed six review findings. The lesson is not "be careful"; it is that
  nothing checked the call, which is why the contract now states its own signature and binds
  against it. That check caught the repo's own reference stub immediately.
- **A rule with no test drifts, and both copies of it drift independently.** The two
  `CACHE_GITIGNORE` constants each carried a comment saying they must stay identical. They had
  already diverged. The guard is now a test comparing the produced strings.

The fork — who owns persistence, and what a single edge may say — is written up in
[`decisions.md`](decisions.md), and was **resolved on 2026-08-20** (CD-19, CD-20, CD-21).
Phase 2 is no longer blocked.

### Doc impact — applied

- `skills/freya-docs-manager/SKILL.md` — the docs graph, its commands and its limits
- `skills/freya-code-graph/references/graph-schema.md` — workspace and Python resolution
- `../backlog.md` — item 9 closed, 10 and 11 opened

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

---

## 2026-08-20 — the fork resolved, and the default nobody could argue with

**Status:** shipped as `b7b9d4b` and `ab59b08`. Decisions distilled as CD-19, CD-20, CD-21 in
[`decisions.md`](decisions.md).

Three changes, landed together because the first is the second's prerequisite and the third
shares the contract file both restructure.

### Reversals

| Planned / shipped earlier | What replaced it | Why |
|---|---|---|
| Remove `scripts` from the exclusion lists entirely (2026-08-19) | `scripts` returns, root-level only | The wider change. A root `scripts/` had been excluded in *every* project this toolkit had run on; un-excluding it everywhere to fix one repo's nested `skills/*/scripts/` changed the answer for projects that had asked for nothing |
| Scope the depth rule to freya-devkit only (the user's proposal) | Keep the depth rule; make every default overridable per project | Not implementable without hardcoding a name or path — and it treats the symptom. The defect was that a project could not disagree with *any* default |
| Part B framed as "does the graph track files, or symbols?" | Reframed as "what can a single edge say?" | The title was wrong and caused real confusion. Nodes are files and stay files; only the edges changed. Symbols are Phase 3 |
| `upgrade_edges` stamps the current schema version | It does not touch `version` | Stamping on read makes every graph report itself current at the exact moment reading is how we find out it is not — the staleness check answered `False` for everything, and the migration would never have written anything back |

### Measurements

| | |
|---|---|
| freya-devkit after the change | 57 files, 419 edges, 64 dependents |
| Edges lost vs. the run before | **0.** The one gained is this session's own `import substrate` in the test file |
| Legacy-artifact migration | Hand-downgraded this repo's graph to string edges, ran `--update`: 419 edges in, 419 out, rewritten as schema 2 |
| Override, live on this repo | Marking `docs/` as source took the graph 57 → 61 files, and `substrate.exclusions.overrides` records why |
| Tests | 1,151 → 1,186 |
| Blast-radius sweep before implementing | 8 agents, 210 candidate sites across 30 files |

### What the sweep was worth

It changed the design twice, which is the only reason to run one.

First: several readers independently said the *node* queries (`--impact`, `--dependents`,
`--dependencies`) should keep returning path strings, because three other skills feed them
straight into set arithmetic where an edge object raises `unhashable type: 'dict'` — in a
different skill, for no gain. Drawing that boundary meant behavior-graph, drift and
behavior-runner needed **no code change at all**. Without it the change would have rippled
through four skills.

Second, the adversarial pass found something with nothing to do with edges.
`behavior-runner._code_graph_deps` returned `[]` on *any* failure of its code-graph query, and
its only caller branched on `None`. So a failed query produced a one-file dependency closure,
tagged `static` at full confidence, no warning, written into `behavior.json` — which is
committed (ADR-017) and whose `exercises[].path` values narrow every later blast radius. Fixed
in `ab59b08`.

Not hypothetical: for roughly fifteen minutes mid-migration this working tree had
`--dependencies` raising an exception, and anything fingerprinted in that window would have
been silently truncated and committed.

### Worth carrying

- **The contract's own validator had never run.** `validate_graph` existed, was well written,
  and had zero production callers — so nothing checked that a produced graph was well-formed,
  including our own. Writing a guard is not the same as wiring it.
- **A default that cannot be overridden is not a default.** `set_classification` had been
  accepted, persisted, and silently ignored since it was written. The API existed; the effect
  did not.
- **Three layers had to agree about one rule.** The file filter, the directory classifier, and
  the exclusion set the CLI hands back to `build()`. Fixing one at a time produced three
  successive "why is it still excluded?" cycles. The stale *cached* verdict beating a fresh
  override — because the walk preferred depth over authority — was the least obvious.
- **Forty tests had never exercised the production path.** They called `CodeGraph.build()`
  directly, which is precisely the method that stopped doing the work.

### Doc impact — applied

- `skills/freya-code-graph/SKILL.md` — edge shape, the query/node boundary, overriding defaults
- `skills/freya-code-graph/references/graph-schema.md` — Edge and ReverseEdge, schema 2
- `docs/polyglot/explainer/` — both pages: fork resolved, Part B retitled, Part C added
- `docs/polyglot/phases/phase_0/harness/compare_graphs.py` — reads both edge shapes, so the
  Phase 0 gate can still be re-run against the numbers it originally produced

---

## 2026-08-20 (later) — the review that found nine, and the one that mattered

**Status:** shipped as `774e7f2` and `9fa6399`.

Three review lenses over the four commits above, each finding independently, then a refutation
pass that had to *reproduce* a defect before it counted. 17 raised, 9 survived. Every one was in
code written earlier the same day.

### Reversals

| Shipped hours earlier | What replaced it | Why |
|---|---|---|
| Overrides live in `classifications.json` | Overrides live in `knowledge-base/settings.json` | That file is gitignored regenerable cache. The override worked for whoever typed it and vanished on clone — CI and every colleague silently graphed a smaller codebase and were told it succeeded |
| `--update` rewrites a stale artifact in place, stamping the new schema version | `update()` runs a full rebuild instead | A graph old enough to be stale can predate the `substrate` metadata block, and that block cannot be recovered from the artifact. The rewrite left it claiming no backend and no coverage, and by stamping the version guaranteed nothing would look again |
| `get_dependencies`/`get_dependents` return `set()` when the file is unknown | They return `None` | `[]` meant both "imports nothing" and "not in the graph". behavior-runner took the first reading and committed a one-file fingerprint |

### Worth carrying

- **The ADR was already written, and I broke it anyway.** CD-15 rejected
  `classifications.json` as a home for a decision — "that path is gitignored regenerable
  cache... would not reach a fresh clone" — and `settings.py`'s own module docstring repeats
  it in the second paragraph. CD-21 put the override there regardless. Having the reasoning
  written down, in the file being edited, was not enough.
- **A fix can reopen a defect through a different door.** `ab59b08` closed behavior-runner's
  silent-empty closure for *failed* queries. Moving `scripts` back to a root-level exclusion
  reopened it for *unknown* entries the same day, in a different commit, for the same
  downstream consequence.
- **My own docstring asserted an invariant the code did not hold.** `_parse_imports` said two
  edges to one target could not happen, having deduped by specifier — but `./sub` and
  `./sub/index` are two specifiers and one file.
- **The comment knew the rule and the code next to it did not follow it.** Backend selection
  prints to stderr with a comment saying it must, "so it never contaminates `--format json`".
  Four progress prints in `build()` went to stdout, which made `--build --format json`
  unparseable.
- **Refutation-first review earns its cost.** 8 of 17 candidates were refuted by an agent that
  reproduced the scenario and found the code already handled it. Reviewing without that pass
  would have meant acting on all 17.

### Measurements

| | |
|---|---|
| Review | 20 agents, 3 lenses + 17 refutations; 9 confirmed |
| Clone test | `git clone` of a project with a `settings.json` override: graphs the overridden tree, records `overrides: ["docs"]` |
| freya-devkit | 57 files, 424 edges — +5 on the prior run, all of them this change's own new import lines |
| Tests | 1,186 → 1,200 |

---

## 2026-08-20 (Phases 2 and 3) — the second substrate, and what it cost to trust it

**Status:** shipped as `4f40692` and `6df1ce1`. Decisions distilled as CD-22..CD-25.

### Measurements

| | |
|---|---|
| graphify 0.9.47 on this repo | 3,692 nodes / 6,289 links, 2.4s, no model, no network |
| Projected onto the contract | 73 distinct file pairs, 113 edges (file-level), 634 (symbol-refined) |
| **§9.1, the blocking gate** | **73 pairs against homegrown's 65 — nothing lost** |
| The one "miss" | `bin/installer.py -> bin/freya_cli.py`: an import inside a *string literal*. Homegrown's own false positive (backlog item 10) |
| Structural links dropped | 2,861 of 6,289 — 57.8% — all 100% intra-file |
| Intra-file links of kept relations | 1,516 of 2,007 survivors (75%), dropped as self-edges |
| Resting solely on INFERRED | 2 file pairs |
| Extensions read | 33, against homegrown's 6 |
| Determinism | Two cold builds of the whole repo, graphify-out destroyed between: 69 files / 662 edges, byte-identical |
| Tests | 1,202 -> 1,264 |

### Reversals

| Planned / believed | What replaced it | Why |
|---|---|---|
| `auto` picks whichever backend reads most (Phase 1) | `auto` is the floor; naming a backend is the opt-in | Not hypothetical the moment a second backend existed: graphify scored 63 to homegrown's 58 here and would have taken over on the next build. Installing a binary on PATH would have changed every blast radius on the machine, with no diff. Spec §11 already said *graphify is opt-in* |
| `rationale_for` is graphify's own docs graph | It is a *docstring index* | 543/543 `rationale` -> `code`, intra-file, `.py` only. The source node's label is the first line of a docstring. It cannot express a relationship between two files, so it neither overlaps docs.json nor competes with it |
| Coverage declared from one language fixture | Declared from two fixtures plus a census of real output | The first probe found 17 extensions; the artifact immediately failed validation on `.json`, `.sql`, `.tf`, `.ps1`. The validator caught the under-claim on its first real run |
| Symbols threaded from the graph into behavior.json | Threaded from the *coverage report* | `observed` means "the test ran this". Graph symbols would mix in things nobody executed — measurement versus inference, which is the distinction the trust model rests on |

### Worth carrying

- **The declared coverage was wrong on its first real run, and the contract caught it.**
  `validate_graph` reported five files outside the declared extensions within seconds of the
  backend first producing a graph. That is the first time the contract has caught a backend
  rather than a caller, which is what it was written for.
- **A vocabulary you cannot enumerate needs a report, not a default.** Grepping graphify's
  source yields 26 relation names; `reads_from`, which this repository's graph contains, is not
  one of them. So there is no fallthrough — an unlisted relation is counted and announced.
- **I "corrected" a probe that was right, using a worse method than the one it used.** It
  reported graphify's vocabulary as including `extends`, `dynamic_import`, `embeds` and
  `requires`. I grepped for `relation = "..."` and `"relation": "..."`, found none of them,
  removed all four from the mapping table, and wrote in this log that the agent had invented
  them. All four are real, in `DEFAULT_AFFECTED_RELATIONS` (affected.py:12) — a tuple
  constant, which is exactly the shape my regexes could not see. My own scan had also failed
  to find `reads_from`, which this repository's graph *contains*, and I noticed that
  discrepancy and drew no conclusion from it.

  Verification that only looks one way is not verification. The table is now pinned by a test
  that reads `DEFAULT_AFFECTED_RELATIONS` out of graphify's own interpreter and fails if any
  relation it walks is unmapped here — which is the check I should have written instead of
  the grep.

- **`method` is dropped as an edge and kept as a lookup.** It is not a dependency: 1,119 of
  1,119 links are intra-file. But graphify labels a method with its own name only —
  `.setUp()`, `._run()` — and **64 of 1,731 code symbols share a bare label with a sibling in
  the same file**. Without the owning class, Phase 3's symbol names describe a symbol without
  identifying one. Qualifying from `method` takes the collisions to zero.
- **A gate that does not bite is not a gate — and I measured that wrong too.** The first §9.1
  test asserted file *pairs*, and the fixture carried each pair on three relations, so dropping
  one changed nothing it could see. I mutation-tested it, saw failures, and wrote in the commit
  message that the gate caught four mutations.

  It had not. I ran the mutations against the *whole test file*, so other tests were doing the
  catching. Run against the gate class alone it caught **one of six**. The fixture was the
  reason: no intra-file call, so the self-edge guard was never exercised; no document node, so
  the code-node filter was not; no vendored tree, so the exclusions post-filter was not. A
  fixture that exercises none of the guards lets a broken projection pass.

  Rebuilt with all of them, plus an external-module import and a class method, and re-pinned
  on `(from, to, kind)`: **10 of 10**, verified against the gate class in isolation.
- **Spec §10 asks for something that does not exist.** "Thread it through the fingerprint
  comparison" — nothing in the toolkit compares two fingerprints' exercise sets.
  `merge_fingerprint` compares coverage *labels* and copies the exercises; `stale_bucket`
  compares `freshness` to HEAD. Recorded here rather than quietly reinterpreted, which is the
  CD-21 pattern the previous commit exists to remember.

### Doc impact — applied

- `skills/freya-code-graph/SKILL.md` — the backends table, the opt-in, `substrate.symbols`
- `skills/freya-code-graph/references/graph-schema.md` — the optional symbol fields on Edge
- New: `skills/freya-code-graph/scripts/backend_graphify.py`, its tests, and
  `scripts/testdata/gate91.json` — the committed §9.1 fixture

### Found by reviewing the above

Eighteen defects, from a three-lens adversarial pass with a refutation stage on every
candidate (34 raised, 18 survived). The four that mattered:

- **graphify's external-module nodes were being read as project files, fabricating edges.**
  It emits one node per external module, and that node's `source_file` is whichever importer
  was parsed first. Three Swift files that each `import Foundation` produced
  `s1.swift -> s3.swift` and `s2.swift -> s3.swift` — edges that exist nowhere in the source,
  in the direction that inflates blast radius. They are `external:Foundation` now, which is
  what the contract has for exactly this.
- **Switching `substrate.backend` away from graphify never took effect.** Freshness was judged
  from `commit` and schema version alone, so `--update` reported `up_to_date` and kept the
  other backend's graph indefinitely — and the first update that *did* see a change spliced
  homegrown's edges into a graphify graph under a `substrate` block claiming graphify's
  coverage.
- **A degenerate extraction was persisted as a successful empty graph.** An empty `files` dict
  passes validation — there is no edge to be wrong about — so a backend that silently stopped
  working would overwrite a good graph and report `status: built`. It now refuses, and
  degrades to the floor instead.
- **Symbol mode filled `dependents` with byte-identical duplicates.** 322 of 417 entries on
  this repository, one file listing the same dependent 60 times, because `link_dependents`
  rebuilt reverse edges without the symbols that distinguished them. Zero now, in both modes.

The rest: the opt-in hint fired on a lone `package.json` because it counted *declared*
extensions; `settings.json` warnings were generated and never printed, because the property
that appended them was evaluated after the list was read; `coverage_symbols` overwrote instead
of unioning when two coverage entries resolved to one path; `--update` reported the whole
repository as changed every run; a git failure read as "nothing changed" and made `--update` a
permanent silent no-op; and the byte-identity test used `sort_keys=True`, normalising away the
only thing that could break it.

### §9.1 re-derived on all three repos, at HEAD

Spec §9 requires the gate to run against three repositories, not one. Done after the review,
because "Phase 2 is complete" was not a claim I could support from freya-devkit alone.

| Repo | homegrown | graphify | Edges homegrown finds that graphify does not |
|---|---|---|---|
| acme-site-testbed (TS/Next.js — the floor's home turf) | 234 files / 627 pairs | 247 files / 630 pairs | **0** |
| java-graph-fixture (Maven) | 0 files, reports `unknown` | 7 files / 11 pairs | **0** |
| freya-devkit (Python) | 59 files / 65 pairs | 67 files / 73 pairs | 1, and it is *homegrown's* false positive — an import inside a string literal |

The Java figure matches Phase 0's hand-written ground truth of 11 edges exactly.

**Spec §10's Phase 5 clause is discharged.** It says `project_shape.classify()` "reads a Java
repo as greenfield today... fixed for free by Phase 2 and must be re-verified, not assumed".
Re-verified: on the floor the Java repo now reports `unknown` with the blind-spot reason ("the
code-graph backend does not read 6 .java"), and on graphify it reports **brownfield** with 7
files and 22 edges. Neither answer is `greenfield`, which was the failure.

Two things that verification found, which is the argument for doing it:

- `.xml` was missing from the declared coverage, so `pom.xml` failed validation on the first
  real Maven project. Declared now, and flagged over-claimed alongside `.json` — graphify
  reads *manifests*, not arbitrary XML.
- My first attempt wrote a malformed `settings.json` through a shell-quoting mistake. The build
  said so, in one line, and used defaults. That is the warning path fixed hours earlier in the
  same session, catching a real mistake the first time it was given one.

### Still open

- The intra-file call graph (1,516 links here) is a deliberately discarded capability. Filing
  it needs a node type the contract does not have.
- `.ejs` and `.ets` have no extractor in graphify's registry and were not probed; `.r` was, and
  produces nothing.
- graphify's `community`/`community_name` fields drift between cold builds (1,455 of 3,692
  nodes measured). Irrelevant here — the projection reads neither — but it means graphify's own
  artifact is not byte-stable while ours is.
