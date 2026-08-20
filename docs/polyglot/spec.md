# Track B — the polyglot substrate

**Design spec · written 2026-08-19 · approved and fully implemented 2026-08-20**

Product of the brainstorm recorded in [`log.md`](log.md). Distilled into ADRs and the reference
docs when the feature ships; this file is deleted with the rest of `polyglot/`.

> **Read this as the design, not as the outcome.** All six phases below have shipped, and several
> clauses were refuted or superseded while building them. The corrections are listed immediately
> under this note and are *not* woven back into the text — a spec that is silently edited to match
> what happened stops being evidence of what was intended.
>
> For what was actually built, see [`explainer/index.html`](explainer/index.html); for the
> decisions that superseded parts of this, [`decisions.md`](decisions.md).

### Where this document was wrong, or has been superseded

| Clause | Status |
|---|---|
| §2.2 *"Default: graphify when installed and the project contains a language homegrown does not cover"* | **Superseded by CD-23.** `auto` is the floor and never switches on its own; naming a backend is the opt-in. Scoring silently would change every blast radius on a machine the moment a binary landed on `PATH` |
| §2.2 / §4.1 *the semantic pass* | **Not built, and not needed for anything shipped.** Everything Phase 2 produces is deterministic. CD-5 stands as the decision if it is ever enabled |
| §4 *the `extracted`/`inferred` mapping onto ADR-009* | **Half refuted.** Both provenances come out of the same AST pass with no model involved, so this is not the deterministic-versus-model-judged axis. The tier is real but narrower than described; two file pairs on this repo now rest solely on `inferred` links |
| §4 / §11 *"only `extracted` edges may gate `wrap-up`"* | **Recorded, not implemented.** No production code reads an edge's provenance, so an `inferred` edge reaches blast radius indistinguishable from an `extracted` one. Found by the closing review. Either the filter gets written or the promise gets struck — it must not stay stated as present fact |
| §4 *`unresolved` as a third provenance value* | **Never was one.** `PROVENANCE` has two, and `validate_graph` rejects a third. `unresolved:` is a prefix on the edge's *target*, because "could not be resolved" is a fact about where the edge points, not about how it was read |
| §7 *"`exports`: yes" under graphify* | **False.** The graphify backend emits no `exports` at all, so a backend swap empties the field. Same for source→package `external:` edges on TS/JS/Python. Both are upstream limitations, and the coverage block has no way to declare either |
| §5 / §10 Phase 3 *"thread it through the fingerprint comparison"* | **Describes something that does not exist.** Nothing in the toolkit compares two fingerprints' exercise sets. Recorded in [`log.md`](log.md) rather than reinterpreted into whatever is nearest |
| §7 *"graphify parses SQL schemas… config comes free"* and §9.4's premise | **Refuted for YAML** — no support and no warning. JSON is manifest-only. SQL and Terraform work behind pip extras. The conclusion (no config graph, CD-9) survives on independent reasoning |
| §9 *the three-repo gate* | **Discharged 2026-08-20**, having initially been run on one repository only. Testbed 630 pairs vs 627 with 0 misses; Java 11 pairs matching Phase 0's ground truth; freya-devkit 73 vs 65, the one "miss" being homegrown's own false positive |
| §10 Phase 5 *"fixed for free by Phase 2 and must be re-verified, not assumed"* | **Discharged.** The Java repo reports `unknown` on the floor with its blind-spot reason, and `brownfield` on graphify. Never `greenfield` |
| §12 open question 3 *how exclusions reach graphify* | **Answered:** a post-filter on its output. `graphify update` has no exclusion flag |

---

## 1. Goal

Make freya-devkit useful on **any** coding project, not just TS/JS webapps.

Today `freya-code-graph` is a regex import-scraper covering TypeScript, JavaScript, Python and
Go (`graph_ops.py:30`, `:50`). Everything in the toolkit stands on that graph — blast radius,
behavior tracking, drift detection, incremental security scanning — so on a Java, Kotlin, C# or
Ruby repo the toolkit installs and runs and sees nothing. 0.2.0 made it run anywhere without
making it *see* anywhere.

### Success criteria

1. Pointing freya at a Java repo produces a code graph with real internal edges.
2. On the repos the homegrown resolver already handles, the new substrate **does not
   under-report** relative to it (§9.1).
3. `docs-manager` can answer "which docs does this code change affect?" from a recorded edge
   rather than by re-deciding it each run.
4. No project is *required* to install anything to keep what it has today.

### Non-goals

Explicitly out of scope, each decided during the brainstorm and recorded with its reason in
[`log.md`](log.md):

| Not doing | Why |
|---|---|
| Helm chart graph | A chart is a Go template, not YAML, until `helm template` runs. Highest cost in the feature, least value: one hop, few files, and no consumer asks the question |
| A "resource graph" for Docker / K8s / compose | Config relationships are one hop and never branch. A three-node chain is a list, not a graph |
| A config identifier index | Proposed as the replacement for the above, then dropped — graphify already parses YAML/JSON/HCL deterministically, so it is likely redundant. Confirmed or refuted by §9.4 |
| SCIP backend | Compiler-grade precision requires each language's full toolchain and a green build. That inverts "point it at any repo and it works" |
| Terraform HCL parsing | The one genuine DAG in the config world, and `terraform graph` already emits it. Consume it if ever needed; never parse HCL ourselves |
| Materialising the governance graph | `SPEC → BEHAVIOR → TEST → CODE` is already navigable and small. Filed in [`../backlog.md`](../backlog.md) with its revisit trigger |

---

## 2. The core decision: a contract, not a tool

Picking a better parser means picking again in two years. So the parser is not the
architecture — **the socket it plugs into is.**

`freya-code-graph` gains a **substrate contract**. Any backend satisfying it can produce the
code graph. The contract is the deliverable; the backends are implementations.

### 2.1 What the contract requires

A backend must:

1. **Resolve** — given a project root, emit nodes and edges for the languages it claims.
2. **Report what it could not resolve** — an unresolvable import is emitted as
   `unresolved:<raw>`, never dropped. A silently-empty answer is the failure mode ADR-005
   exists to prevent, and it is worse than an honest gap.
3. **Carry per-edge provenance** — every edge states how it was obtained and how much to trust
   it (§4).
4. **Declare its coverage** — which languages and file types it actually handled, so a caller
   can distinguish "no dependencies" from "this backend does not read Java".
5. **Support incremental update, or decline it** — a backend that cannot correctly remove
   deleted nodes must say so, and the contract then forces a full rebuild for that backend
   rather than trusting a stale incremental (§9.2).
6. **Honour the project's exclusions** — the caller passes the excluded directories in; the
   backend does not decide for itself what is out of scope.

Exclusions are a **project** concern, not a backend one: "`vendor/` is not mine" is true
whichever parser runs. `classifications.json` — today an internal cache in `graph_ops.py` that
stops the interactive classifier re-prompting — becomes the store behind this, read by the
contract and passed to whichever backend is selected. Without it a backend will happily graph
`vendor/` and generated output, and blast radius fills with noise nobody can switch off.

Points 2, 4 and 5 exist because of specific past failures: F7 (path aliases producing a
confidently-empty graph), F9 (cwd-sensitive resolution silently dropping edges), and the
staleness risk in §9.2.

### 2.2 The backends

| Backend | Role | Requires |
|---|---|---|
| **homegrown** | the floor. Stays as-is, remains the default where it already works | nothing — stdlib Python |
| **graphify** | the polyglot backend. [`Graphify-Labs/graphify`](https://github.com/Graphify-Labs/graphify), tree-sitter, 37 languages | `uv`/pip install |

**Two backends, not one, deliberately.** An interface with a single implementation is fiction —
it leaks the assumptions of its only caller and nobody notices until the second one arrives.
Homegrown and graphify differ on every axis that matters (regex vs AST, zero-install vs
dependency, 4 languages vs 37, file-level vs symbol-level), so satisfying both proves the
contract is real.

**Homegrown is not legacy baggage — it is the floor, and the floor is load-bearing.** freya is
stdlib-only today; graphify needs `uv`/pip and network access. The driving case for this whole
initiative is a **locked-down work laptop**, and if enterprise policy blocks installing a Python
package then graphify never runs in the one environment Track B exists to serve. Keeping the
homegrown resolver is what guarantees freya degrades to *something* everywhere rather than to
nothing.

**Two distinct opt-ins, not one.** graphify-the-backend is opt-in because it is a dependency you
install. The semantic pass (§4.1) is opt-in because it costs money and needs a model. Either can
be on without the other.

**Selection.** Per project, in config. Default: graphify when installed and the project contains
a language homegrown does not cover; homegrown otherwise. Never silent — the chosen backend and
its declared coverage appear in the graph metadata.

**Degradation.** If the configured backend is unavailable, freya falls back to homegrown, emits
its reduced coverage in the metadata, and says so on stderr. It does not fail the run, and it
does not pretend the graph is complete.

---

## 3. Artifacts

Three files, each with its own producer, joined by file path.

| Artifact | Holds | Producer | Requires | Committed |
|---|---|---|---|---|
| `knowledge-base/.graph/graph.json` | code → code | the substrate backend | a backend | no |
| `knowledge-base/.graph/behavior.json` | behavior → test → code | behavior-runner | a green test suite | **yes** (ADR-017) |
| `knowledge-base/.graph/docs.json` | doc section → code | markdown citation parser | nothing | no |

**Why separate rather than one store.** Different producers with different dependencies and
different failure modes. If a missing graphify degraded a single combined file, a caller could
not tell which half survived. Separate files fail independently — a broken code substrate costs
you nothing in docs edges.

This extends the arrangement vision §6 already chose: `behavior.json` is a sibling of
`graph.json`, not a schema bump to it, *specifically so the code-substrate decision stays
decoupled*. The contract reinforces that choice rather than conflicting with it, which resolves
the tension the 2026-07-12 "unify the graphs" lean created. **That lean is dropped.**

**No linking graph.** Every artifact anchors on file paths, so there is no identifier
translation to store and a linking layer would be an empty table. What is needed instead is a
**query layer**: a reader that loads whichever artifacts are present and answers across them.

---

## 4. Provenance and trust tiers

graphify tags every relationship `EXTRACTED` (explicit in source) or `INFERRED` (derived by
resolution). freya already has a matching two-tier model in ADR-009 — deterministic checks
block, model judgment is resolve-to-proceed and fails open. They map directly:

| Provenance | Meaning | May gate `wrap-up` |
|---|---|---|
| `extracted` | read from source text | **yes** |
| `inferred` | resolved by name matching or by a model | no — advisory only |
| `unresolved` | could not be resolved; recorded with the raw reference | no — surfaced as a coverage gap |

**Why this matters more than it sounds.** Syntactic substrates fail by *cross-language
mis-wiring* — a name-only index links Python's `sorted()` to a Swift `func sorted`. freya's
principle is never to present an uncertain answer as certain. Per-edge provenance is what makes
adopting a name-resolving backend safe, and it is a contract requirement, not an optimisation.

### 4.1 The semantic pass

graphify's Markdown, PDF and image handling requires a model. It is **opt-in, never required**,
and it runs through the driver pattern freya already owns (ADR-015): `--agent` selects the CLI,
`--model` selects a model of that CLI, both or neither.

That means it uses the engineer's **existing subscription** — `claude -p`, `copilot -p` — not a
separate API key. A cheap fast model is appropriate; this is extraction and classification, not
reasoning.

**Defaults are per-agent**, because model names belong to a CLI, not to freya: Copilot →
`gpt-5.6-luna` (already validated live in Phase 7), Claude → Sonnet 5. `--model` overrides;
passing `--model` without `--agent` remains an error, matching the security driver's existing
rule.

`--code-only` is the **default**. Everything the semantic pass produces is `inferred`, so it can
never block a commit.

---

## 5. Granularity: symbols refine files, never replace them

graphify records `calls`, `inherits` and `mixes_in` between **symbols**. The homegrown resolver
records imports between **files**. Symbol-level is sharper — "this function changed, these three
callers care" beats "this file changed, these twelve importers care".

But symbol names are not durable identifiers. Vision §6 says so directly, which is why
behaviors carry stable `BEH-NNN` ids rather than being keyed on scenario titles. Rename a
function and a symbol anchor breaks silently — and `behavior.json` is committed, so a broken
anchor becomes a diff someone must fix.

**So symbol is an optional refinement on a file anchor, in every artifact:**

```json
{ "path": "lib/webauthn.ts", "symbol": "verifyChallenge",
  "provenance": "extracted", "confidence": 0.9 }
```

With `symbol` present you get the sharp answer. Absent or stale, it degrades to exactly the
file-level behaviour that ships today. **The floor is current behaviour**, which is what makes
this safe to adopt incrementally.

This applies to `behavior.json`'s `exercises` and to `docs.json` edges alike. Observed coverage
genuinely supports it — istanbul's `coverage-final.json` carries an `fnMap` of function names
and locations, and coverage.py provides the equivalent.

---

## 6. The docs graph

### 6.1 The gap it closes

`docs-manager` currently decides which docs are stale by: git diff → `code-graph impact` → the
*agent judging* which docs correspond to the affected files. Nothing records that
`ARCHITECTURE.md` documents those files, so the judgment is re-made every run — inconsistent
and unverifiable.

Meanwhile the reverse query has no answer at all: *"I changed `graph_ops.py` — which docs now
lie?"* This session is the evidence. Changing how `.graph/.gitignore` is written invalidated
claims in `architecture.md` and `skill-reference.md`; both were found by grep, and both cited
`graph_ops.py:212` in text no tool reads.

### 6.2 Edge sources — all deterministic

| Source | Example | Provenance |
|---|---|---|
| `path:line` citations in prose | `graph_ops.py:212` — 62 distinct in this repo | `extracted` |
| Markdown relative links | a relative link from a doc to a source file | `extracted` |
| `related_code:` frontmatter | on every spec and ADR already | `extracted` |
| graphify's semantic markdown pass | opt-in, §4.1 | `inferred` |

### 6.3 Anchoring

Edges anchor at **section**, not line:

```
architecture.md#output-artifacts → graph_ops.py
```

Line numbers shift the moment anyone inserts a paragraph; the heading is stable and it matches
the actual question — *which section is now wrong*. The `path:line` citation is retained as
evidence *within* the edge, not as its anchor.

The **target** follows §5: a file path, refined with an optional `symbol` when the citation
carries a line and the substrate can map that line to one. Measured on this repo, 62 citations
carry a line and 43 are bare file references, so the field populates for the majority. Under the
homegrown backend there are no symbol ranges, so every docs edge is file-level — the same floor
as everywhere else.

### 6.4 Chunking rules

Sectioning a markdown file must not corrupt its content:

1. Split **only** at heading boundaries.
2. Treat every block as **atomic** — a fenced code block, a table, an HTML block is never
   divided.
3. Never split inside a fence, under any size pressure. If a section is large, split between
   top-level blocks or leave it whole.

This is not hypothetical. `architecture.md` contains ASCII trees inside fences and the site has
mermaid diagrams; a line-count splitter would cut a diagram in half. The F7 fix is the
precedent for this bug class — a naive regex JSONC stripper mis-read `/*` inside the string
`"@/*"`, caught by a TDD regression test before shipping.

---

## 7. What the code graph gains and loses

| Field today | Under graphify |
|---|---|
| `imports` | yes |
| `dependents` | yes (reverse of imports) |
| `exports` | yes |
| `language` (4) | yes (37) |
| `category` (auth/api/data/ui/…) | **no equivalent — being removed, see below** |
| — | `calls` between symbols |
| — | `inherits` / `mixes_in` |
| — | `# NOTE:` / `# WHY:` comments as nodes linked to code |
| — | package deps from `pom.xml`, `go.mod`, `pyproject.toml` |

**`category` is removed.** It is written by `_categorize_file` (`graph_ops.py:309`) on every
build and **read by nothing**. Three unrelated things in this repo are called "category" —
the spec frontmatter field (live, used by `contradictions.py` for peer scoping) and
`classifications.json` (live, directory source/exclude) both stay. Only the dead per-file graph
field goes. This is a pre-existing cleanup the substrate work surfaced; it is not caused by
graphify.

**Manifest parsing is free.** graphify already extracts package dependencies from `pom.xml`,
`go.mod` and `pyproject.toml`, so the "manifest parsers" line item from the early brainstorm
disappears. `pom.xml` was the load-bearing one for Java multi-module boundaries.

**Database schemas are code.** `schema.prisma`, `*.sql`, JPA entities and Django models define
types that code depends on, usually through a generated client — a genuine import chain, and
graphify parses SQL schemas. **Migrations are not graph material**: an ordered append-only log
is a chain, not a DAG, and "what does the schema look like now" is answered by the schema file.
Where a project has *only* migrations and no schema file, the current schema is emitted as
`unresolved` rather than inferred by folding them — the same rule as Helm, for the same reason.

---

## 8. Component boundaries

| Component | Does | Depends on |
|---|---|---|
| substrate contract | defines the interface, validates a backend's declared coverage | nothing |
| homegrown backend | today's resolver, unchanged behind the contract | stdlib |
| graphify backend | invokes graphify, maps `graphify-out/graph.json` onto the contract's shape | graphify |
| docs producer | parses citations, links and `related_code` into `docs.json` | nothing |
| query layer | loads present artifacts, answers across them | the artifacts |

Each is separately testable. The query layer is the only component that knows more than one
artifact exists.

---

## 9. Phase 0 — the spike. Nothing else starts until this passes.

The substrate decision must be **measured, not argued**. Five tests, all cheap, run against
three repos: the testbed (232 source files, 609 known internal edges), freya-devkit itself
(Python, 50 files), and a Java project.

### 9.1 Under-reporting — the blocking test

Build both backends on the same repo. Diff the edge sets in both directions.

- Edges homegrown finds that graphify does not → **the risk**
- Edges graphify finds that homegrown does not → the coverage gain; spot-check for mis-wiring

**Misses are the dangerous direction.** A missing edge narrows a behavior's static closure, the
behavior is not flagged as affected, and a regression walks through the wrap-up gate. A spurious
extra edge only runs a test you did not need.

**Acceptance:** graphify does not under-report against homegrown on the languages homegrown
covers. Any miss must be explained before adoption, not tallied.

### 9.2 Deletion and staleness

graphify's `--update` "preserves existing graph structure", which could mean "does not rebuild
untouched nodes" or "never removes anything". The second is fatal — a graph accumulating deleted
symbols returns blast radius pointing at code that no longer exists.

Delete a file, rename a function, remove an import → `--update` → assert the nodes and edges are
gone and nothing dangles.

Our own resolver is already correct here (`graph_ops.py:1216-1218` deletes the entry and rebuilds
all dependents), so this is a test graphify must also pass.

**Acceptance:** stale nodes are removed. If not, the contract forces a full rebuild for that
backend.

### 9.3 Reproducibility

Build twice on identical input; diff. The homegrown resolver is content-stable but byte-unstable
(measured 2026-08-19: 10 of 10 differing entries were pure reordering of `imports` arrays, which
come out of a set). graphify is unmeasured.

**Acceptance:** content-stable. If it is not, the graph cannot be trusted incrementally at all.
Byte-instability is tolerable for `graph.json` (gitignored) but not for anything derived into
`behavior.json`, which is committed and already sorted at write time.

### 9.4 Config coverage

graphify lists SQL schemas, YAML/JSON configs and Terraform HCL under deterministic file
support. Run it on a repo containing them and inspect the edges.

**Decides:** whether config relationships come free, or are simply absent. Either answer is
fine; the point is to stop guessing. A "yes" also retires the identifier-index idea for good.

### 9.5 Degradation and output location

Confirm what happens when graphify is not installed, and confirm it writes to its own
`graphify-out/` rather than into `knowledge-base/.graph/`.

**Why the second matters:** ADR-017 carries a revisit trigger — if a substrate owns or clears
`.graph/`, `behavior.json` must move out, because it is the one artifact that cannot be
regenerated from source. Current evidence says graphify uses its own directory and the trigger
will not fire. Confirm rather than assume.

---

## 10. Phases after the spike

Each phase ends with the working record in [`log.md`](log.md) updated — decisions, reversals and
measurements as they happen, not reconstructed afterwards.

**Phase 1 — the contract.** Define the interface. Move the homegrown resolver behind it with no
behaviour change; the existing test suite is the regression gate. Add coverage declaration and
the `unresolved` signal to the metadata. Remove the dead `category` field.

**Phase 2 — the graphify backend.** Map `graphify-out/graph.json` onto the contract. Selection,
degradation and provenance tagging. Validate against §9.1 on all three repos.

**Phase 3 — symbols.** Extend the contract's edge shape with the optional `symbol`. Thread it
through `behavior.json`'s `exercises` and the fingerprint comparison. File-level behaviour
remains the floor throughout.

**Phase 4 — the docs graph.** The citation parser, `docs.json`, the chunking rules, and the
`docs impact` query. Rewire `docs-manager` to consume recorded edges instead of re-judging.

**Phase 5 — the agnosticism sweep.** The Next/Prisma assumptions the graph does not fix:
`docs-manager`'s templates (`NEXTAUTH_SECRET`, "Next.js pages"), `detect_project.py`'s Prisma
check, and `project_shape.classify()` — which calls a repo *greenfield* at 0 internal edges and
therefore reads a Java repo as greenfield today. That last one is fixed for free by Phase 2 and
must be re-verified, not assumed.

---

## 11. Risks

| Risk | Mitigation |
|---|---|
| graphify under-reports on covered languages | §9.1 blocks adoption. Homegrown stays the default where it already works |
| Cross-language mis-wiring inflates blast radius | Per-edge provenance; `inferred` edges never gate. Over-approximation is the safe direction |
| Static fingerprints shift when the substrate changes | Expected, not a bug. `observed` edges are unaffected — they come from test runs, not the graph. Treat a swap as a measured migration: diff before trusting |
| Symbol anchors break on rename | `symbol` is optional; every edge keeps its file anchor and degrades to today's behaviour |
| graphify is abandoned | The contract is the point. A third backend is cheap once two exist |
| The dependency breaks zero-install | Homegrown remains, unchanged and installed by default. graphify is opt-in |

---

## 12. Open questions

1. ~~**Which model for the semantic pass.**~~ **Resolved:** the engineer chooses via `--model`;
   defaults are per-agent (§4.1). A cost/quality comparison on real docs would refine the
   defaults but does not block anything, since the pass is off unless asked for.
2. ~~**Do docs edges anchor to symbols as well as files?**~~ **Resolved: both**, on the same
   optional-refinement rule as §5. Measured on this repo's `docs/`: **62** citations carry a line
   (`graph_ops.py:212`) and **43** are bare file references — so the symbol field is
   majority-populated, not mostly empty as first assumed. It is filled when the citation has a
   line *and* the substrate provides symbol ranges to map it onto; otherwise the edge is
   file-level, which is exactly today's behaviour.
3. ~~**Does `classifications.json` survive graphify?**~~ **Resolved:** yes, promoted — exclusions
   move into the contract as a project-level input (§2.1) and both backends honour them. What
   remains to check in Phase 2 is narrower: whether graphify's own file selection needs
   exclusions passed as a CLI flag, a config file, or a post-filter on its output.
