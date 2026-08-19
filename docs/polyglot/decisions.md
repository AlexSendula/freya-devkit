# Track B — decision register

Every decision taken during the Track B brainstorm, written in the shape an ADR needs so that
closing the feature is transcription rather than archaeology.

**How to use this at feature end.** Each numbered entry below is a **candidate ADR**. Take the
next free id from [`../decisions/README.md`](../decisions/README.md) — ADR-018 at time of
writing — fill the four fixed sections from the material here, and delete the entry. What is
written below is deliberately in ADR voice already: *Decision* as present fact, *Rationale* with
its evidence, *Rejected Alternatives* named individually, *Revisit Conditions* concrete.

**Why this file exists separately from the others.** [`spec.md`](spec.md) says what we are
building; [`log.md`](log.md) records what changed and what was measured, chronologically. Neither
is shaped like a decision record. Reconstructing "what did we decide and what did we reject" from
a spec plus a diff is exactly the work the 2026-08-19 restructure had to do across 51 documents,
and it took a day.

**Status.** Every entry is decided as of 2026-08-19 unless marked otherwise. The spike (spec §9)
will add decisions; append them here rather than only into the code.

---

## CD-1 — The substrate is a contract, not a tool

**Decision.** `freya-code-graph` defines a substrate contract. Any backend that satisfies it can
produce the code graph. The contract requires: resolve; report what could not be resolved as
`unresolved:<raw>`; carry per-edge provenance; declare which languages and file types it actually
handled; support incremental update or explicitly decline it; and honour project-level exclusions
passed in by the caller.

**Rationale.** The homegrown regex resolver covers four languages and cannot be extended to Java
without becoming a parser. But choosing a replacement tool means choosing again in a few years,
and every consumer — docs-manager, spec-manager, behavior-graph, security-scan, wrap-up — would
move with it each time. The contract makes the choice configuration instead of architecture.

Requirements 2, 4 and 5 are not generic good practice; each traces to a specific past failure.
F7: tsconfig path aliases made every internal import resolve as `external:`, producing a graph
that reported an empty blast radius *as if complete*. F9: relative imports resolved against the
process cwd were dropped entirely, not even tagged. The staleness risk in spec §9.2 is the third.

**Rejected alternatives.**

- *Pick graphify and wire it in directly.* Fastest to ship. Rejected because it reopens the whole
  question the first time graphify stalls or is abandoned, and by then every consumer depends on
  its output shape.
- *Extend the homegrown resolver per language.* Keeps the stdlib-only property. Rejected: Java
  and anything with a non-trivial module system needs a real parser, and vision §10 already named
  Java as the trigger to stop hand-rolling.
- *A tiered model — homegrown by default, a real substrate opt-in per feature.* Proposed
  2026-07-12 and rejected by the user then; recorded here because the contract supersedes the
  question rather than answering it.

**Revisit conditions.** If a third backend proves expensive to add rather than cheap, the contract
leaked assumptions from its first two implementations and needs tightening.

---

## CD-2 — Two backends ship, and the homegrown one is the floor

**Decision.** Two backends satisfy the contract at launch: the existing homegrown resolver, and
[`Graphify-Labs/graphify`](https://github.com/Graphify-Labs/graphify) (tree-sitter, 37 languages).
The homegrown resolver remains installed by default and remains the default where it already
covers the project's languages. graphify is opt-in because it is a dependency.

**Rationale.** Two reasons, and the second is the load-bearing one.

An interface with a single implementation is fiction — it silently encodes the assumptions of its
only caller, and nobody finds out until the second arrives. Homegrown and graphify differ on
every axis that matters (regex vs AST, zero-install vs dependency, 4 languages vs 37, file-level
vs symbol-level), so satisfying both is real evidence the contract holds.

And **the driving case for Track B is a locked-down work laptop.** freya is stdlib-only today;
graphify needs `uv`/pip and network access. If enterprise policy blocks installing a Python
package, graphify never runs in the one environment this initiative exists to serve. Keeping the
homegrown resolver is what makes freya degrade to *something* everywhere instead of to nothing.

**Rejected alternatives.**

- *Replace homegrown entirely once graphify works.* Less code to maintain, one code path.
  Rejected on the locked-down-laptop case above, and because it would make the zero-install
  property — which the project has held since 0.1.0 — depend on a third-party package.
- *Keep homegrown only as a spike reference, then delete it.* Its value as a diff target does
  expire after spec §9.1. Its value as a floor does not.

**Revisit conditions.** If graphify (or a successor) ever ships as a single self-contained binary
with no install step, the floor argument weakens considerably and this is worth reopening.

---

## CD-3 — Three artifacts joined on file path, no linking graph

**Decision.** The graph layer is three files, each with one producer:
`knowledge-base/.graph/graph.json` (code, backend-produced), `behavior.json` (behavior → test →
code, behavior-runner), and a new `docs.json` (doc section → code, markdown parser). They are
joined on **file path**. There is no combined store and no separate linking graph.

**Rationale.** The producers have different dependencies, different refresh cadences and
different failure modes. graphify may be absent; a test suite may be red; the markdown parser
needs nothing. If one combined file degraded, a caller could not tell which half survived —
whereas separate files fail independently, and a broken code substrate costs nothing in docs
edges.

This extends what vision §6 already chose for exactly this reason: `behavior.json` is a *sibling*
of `graph.json` rather than a schema bump to it, "so the code-substrate decision stays decoupled."
Adding a third sibling applies an existing pattern rather than inventing one, and it is why the
contract reinforces §6 instead of conflicting with it.

A linking graph would be an empty table: every artifact anchors on file paths natively, so there
is no identifier translation to store. What is needed instead is a query layer that reads
whichever artifacts are present.

**Rejected alternatives.**

- *One merged graph.* Simplest to query. Rejected on producer isolation. An earlier argument that
  merging was *mechanically* impossible — because ADR-017 commits `behavior.json` while
  `graph.json` is ignored — was overstated and should not be repeated: `behavior.json` is
  reproducible by rerunning the suite. The distinction is cost and preconditions, not possibility.
- *Three graphs plus a fourth linking graph.* Considered explicitly. Rejected: nothing to put in
  it while all three speak file paths.
- *Unify the code graph and the behavior graph.* The recorded 2026-07-12 lean, on the grounds
  that one real substrate would tighten the behavior↔code connection. **Dropped** — it conflicts
  with §6, and the contract delivers the same benefit without the conflict.

**Revisit conditions.** If a future artifact needs an identifier space that is not a file path —
symbol ids from a substrate that does not expose paths, for instance — the linking layer becomes
real and this changes.

---

## CD-4 — Provenance decides what may block

**Decision.** Every edge carries provenance: `extracted` (read from source text), `inferred`
(resolved by name matching or by a model), or `unresolved` (recorded with the raw reference).
Only `extracted` edges may gate `wrap-up`. `inferred` edges are advisory. `unresolved` is
surfaced as a coverage gap and never silently dropped.

**Rationale.** freya's substrate principle is never to present an uncertain answer as a certain
one (ADR-005). Adopting a name-resolving backend introduces a *new* failure mode: syntactic
substrates mis-wire across languages, linking Python's `sorted()` to a Swift `func sorted`. That
is confidently *wrong* rather than confidently *empty* — worse, because blast radius blocks
commits.

freya already has the enforcement shape for this in ADR-009: deterministic checks block, model
judgment is resolve-to-proceed and fails open. graphify already tags `EXTRACTED` vs `INFERRED`.
The two map directly, so this is adopting an existing distinction rather than inventing one.

**Rejected alternatives.**

- *Discard inferred edges; run `--code-only` and nothing else.* This was the first
  recommendation. Rejected: the objection was that inferred edges should not block, which argues
  for labelling them, not for throwing them away. Discarding loses real signal for free.
- *Treat all edges alike and accept a noisier gate.* Rejected: a gate people learn to ignore
  provides no protection, and the failure is silent.

**Revisit conditions.** If measurement shows inferred edges are accurate enough to gate on — a
low enough mis-wiring rate on real polyglot repos — the tiers could merge. Measure before
assuming; do not merge them on impression.

---

## CD-5 — The semantic pass runs on the engineer's own subscription

**Decision.** graphify's model-driven pass (Markdown, PDFs, images) is opt-in and off by default;
`--code-only` is the default. When enabled it runs through the driver pattern freya already owns
(ADR-015): `--agent` selects the CLI, `--model` selects a model of that CLI, both or neither.
Defaults are per-agent — `gpt-5.6-luna` on Copilot, Sonnet 5 on Claude.

**Rationale.** The pass produces genuinely useful edges that no deterministic parser can (prose
describing code without citing it). Requiring a separate API key would make it inaccessible to
most users and would put a paid third-party call inside a toolkit that has never needed one.
freya already drives `claude -p` and `copilot -p` headlessly under a read-only allowlist for the
security scan, so the machinery exists and is validated live. graphify ships as a skill for those
same hosts, so in-session it uses the host's model natively.

Model names belong to a CLI, not to freya, so defaults are per-agent rather than global.
`gpt-5.6-luna` is the model the Phase 7 driver work was validated against.

**Rejected alternatives.**

- *Require an API key.* Simplest to implement. Rejected: it adds a cost and a credential to a
  toolkit that has neither, and the engineer is already paying for a subscription.
- *Make the semantic pass mandatory.* Rejected: it costs money per run, and everything it
  produces is `inferred`, so nothing that gates depends on it. Mandatory spend for advisory
  output is the wrong trade.
- *A single global default model.* Rejected: `--model` names a model *of a CLI*; a global default
  would be wrong on at least one host. Passing `--model` without `--agent` stays an error, as it
  already does in the security driver.

**Revisit conditions.** If the named default models are retired, or a materially cheaper model
proves adequate on real docs.

---

## CD-6 — Symbols refine file anchors; they never replace them

**Decision.** Edges anchor on a file path, with an optional `symbol` field. Present, callers get
symbol-level precision; absent or stale, the edge degrades to file-level — which is exactly the
behaviour that ships today. This applies uniformly to `graph.json`, `behavior.json`'s `exercises`
and `docs.json`.

**Rationale.** graphify records `calls`, `inherits` and `mixes_in` between symbols, which is
strictly sharper than file-level imports: "this function changed, these three callers care" beats
"this file changed, these twelve importers care".

But symbol names are not durable identifiers, and this project already learned that — vision §6
requires stable `BEH-NNN` ids precisely "because file names and scenario titles are not durable
identifiers". Rename a function and a symbol-only anchor breaks silently. `behavior.json` is
committed (ADR-017), so a broken anchor becomes a diff someone has to resolve.

Keeping the file anchor makes **current behaviour the floor**. Nothing can regress below what
ships now, which is what allows this to be adopted incrementally rather than as a cutover.

Observed coverage supports the refinement genuinely rather than aspirationally: istanbul's
`coverage-final.json` carries an `fnMap` of function names and locations, and coverage.py
provides the equivalent.

**Rejected alternatives.**

- *Fold graphify's symbol edges down to file level and discard the detail.* Cheap; nothing
  downstream changes. Rejected: it throws away precision the backend already computed, for free.
- *Move wholly to symbol anchors.* Sharpest. Rejected on durability — and because it would make
  every rename a breaking change to a committed artifact.

**Revisit conditions.** If symbol anchors prove stable enough in practice that the file anchor is
never the thing that saves a query, the dual anchor is redundant complexity.

---

## CD-7 — The docs graph exists, anchored at section

**Decision.** A `docs.json` artifact records doc → code edges. The **source** anchor is a
markdown section (`architecture.md#output-artifacts`), not a line. The **target** is a file path
with an optional symbol, per CD-6. Edges are parsed from `path:line` citations, markdown relative
links, and the `related_code` frontmatter specs and ADRs already carry — all `extracted`.
graphify's semantic markdown pass may add `inferred` edges when enabled.

**Rationale.** The edge already exists conceptually and is currently *re-derived by model
judgment on every run*: docs-manager does git diff → `code-graph impact` → the agent deciding
which docs correspond to the affected files. Nothing records that `ARCHITECTURE.md` documents
those files, so the answer is inconsistent between runs and unverifiable after them.

The reverse query has no answer at all today: *"I changed `graph_ops.py` — which docs now lie?"*
The 2026-08-19 session is the evidence. Changing how `.graph/.gitignore` is written falsified
claims in both `architecture.md` and `skill-reference.md`; both were found by grep, and both
cited `graph_ops.py:212` in text no tool reads.

Section anchoring, not line: line numbers shift the moment anyone inserts a paragraph, and the
useful question is *which section is now wrong*. The `path:line` citation is retained as evidence
inside the edge.

Measured on this repo: 62 citations carry a line, 43 are bare file references. So the data is
already there, and the symbol field populates for the majority.

**Rejected alternatives.**

- *Keep re-deriving it per run.* Zero implementation. Rejected: it is unverifiable, inconsistent,
  and cannot answer the reverse query at all.
- *Anchor at `path:line` on the source side.* More precise-looking. Rejected: brittle to any
  edit above the citation, and it does not match the question anyone asks.
- *Use graphify's semantic markdown pass as the primary source.* Rejected as primary: it is
  `inferred`, needs a model, and our own citations are already deterministic. It is a useful
  supplement, not the foundation.

**Revisit conditions.** If a project's docs cite no code at all, the deterministic sources yield
nothing and the semantic pass becomes the only option — worth knowing whether that is common.

---

## CD-8 — Markdown is chunked structurally, never by size

**Decision.** Sectioning a markdown file splits **only** at heading boundaries. Every block —
fenced code, table, HTML block — is atomic and is never divided. If a section is large it is split
between top-level blocks or left whole; a fence is never split under any size pressure.

**Rationale.** Splitting inside a fence produces content that is not merely truncated but
actively wrong — half a mermaid diagram, half an ASCII tree. This repo's own
`architecture.md` contains directory trees inside fences and the explainer site carries mermaid,
so it would be hit immediately.

The precedent is exact: the F7 fix caught a naive regex JSONC stripper mis-reading `/*` inside
the string `"@/*"`, which broke alias resolution. Structure-unaware text processing is the same
bug class, and it was caught by a TDD regression test before shipping rather than in the field.

**Rejected alternatives.**

- *Chunk by line count or token budget.* Standard in RAG pipelines, trivial to implement.
  Rejected: guaranteed to cut a diagram in half on this repo's own docs.
- *Chunk by paragraph.* Finer granularity. Rejected: a paragraph is not the unit anyone asks
  about, and it multiplies edges without improving the answer.

**Revisit conditions.** If a single section grows large enough that its edges are uselessly
coarse — a 2,000-line section with one anchor — sub-section splitting on top-level block
boundaries becomes worth adding.

---

## CD-9 — No graph for config-as-code

**Decision.** No resource graph, no config identifier index, no Helm support, no HCL parsing. If
graphify's deterministic YAML/JSON/HCL support yields useful edges (spec §9.4) they are kept as
ordinary graph content; nothing is built specifically for config.

**Rationale.** A graph earns its place on **transitive closure**. Config relationships are one
hop and do not branch: `deployment.yaml → myapp:1.2.3 → Dockerfile → src/`. A chain of three that
never branches is a list, and most projects have a handful of config files.

And nothing consumes the answer. The graph exists so docs-manager, spec-manager and
behavior-graph know what to re-check when code changes. Changing `lib/auth.ts` and learning it
eventually lands in a container image does not change which docs are stale or which behaviours to
re-run — the code graph already answered.

Helm additionally cannot be parsed at all without executing it: `image: {{ .Values.image.tag }}`
is not a value until `helm template` merges `values.yaml`. That makes it the most expensive item
in the feature and the one buying the least.

**Rejected alternatives.**

- *A resource graph covering Docker, compose, K8s manifests and CI workflows, with Helm deferred.*
  Was in the design for most of the brainstorm. Rejected on the consumer question above.
- *A config identifier index* — a flat "this name is defined here, used there" table for env
  vars, image names and service names, answering "I renamed this, what else must change?" by
  lookup rather than traversal. Invented as the cheaper replacement, then dropped: graphify
  already parses YAML/JSON/HCL deterministically, so it is probably redundant.
- *Terraform HCL parsing.* Terraform genuinely has a branching DAG, unlike the rest of config.
  Rejected anyway because `terraform graph` already emits it — consume that if it is ever wanted,
  never hand-roll HCL.

**Revisit conditions.** A concrete question someone actually asks that only a resource graph can
answer. "Which chart deploys the service this code is in" would qualify if it arrived with a
caller. Absent a caller, no.

---

## CD-10 — Schemas are code; migrations are not graph material

**Decision.** Database schema files — `schema.prisma`, `*.sql`, JPA entities, Django models — are
graphed as code. Migrations are not. Where a project has only migrations and no schema file, the
current schema is emitted as `unresolved` rather than derived by folding them.

**Rationale.** Code depends on a schema, usually through a generated client: `User` model →
generated type → imported by `lib/auth.ts` is a genuine import chain, and "I changed the User
model, what touches it?" is exactly the query the graph exists to answer. graphify parses SQL
schemas in its deterministic tier.

Migrations are an ordered append-only log. That is a chain, not a DAG, and the useful question —
"what does the schema look like now" — is answered by the schema file. "Which migration added
this column" is closer to `git blame` than to blast radius.

Folding migrations to derive the current schema means *executing* them, which is the same
"must-run-to-know" problem as Helm, and gets the same answer: emit `unresolved` rather than guess.

**Rejected alternatives.**

- *Graph migrations as a chain.* Cheap. Rejected: no consumer, and it invites treating migration
  order as a dependency relationship it is not.
- *Fold migrations to reconstruct the current schema.* Rejected: requires execution, and a
  reconstructed schema presented as fact is the confidently-wrong failure mode.

**Revisit conditions.** If migration-only projects turn out to be common among adopters, the
`unresolved` answer may be too weak to be useful and running them in a scratch database becomes
worth considering.

---

## CD-11 — Exclusions belong to the contract

**Decision.** Excluded directories are a project-level input the contract owns. The caller passes
them to whichever backend is selected; a backend never decides for itself what is out of scope.
`classifications.json` — today an internal cache in `graph_ops.py` — becomes the store behind it.

**Rationale.** "`vendor/` is not mine" is true whichever parser runs, so it is a property of the
project, not of the parser. Left to the backend, graphify would graph `vendor/` and generated
output, and blast radius would fill with noise nobody can switch off — while the homegrown
backend, which does honour exclusions today, would behave differently on the same repo. Two
backends disagreeing about scope is worse than either behaviour alone.

`classifications.json` is a live cache, read six times in `graph_ops.py`, that stops the
interactive directory classifier re-prompting. Promoting it costs nothing.

**Rejected alternatives.**

- *Let each backend apply its own defaults.* Zero work. Rejected: the two backends would disagree
  about scope on the same repo, and a user could not fix it in one place.
- *Drop `classifications.json` and rely on graphify's file selection.* Rejected: it would strand
  the homegrown backend, which needs the same information.

**Revisit conditions.** None foreseen. If a backend cannot accept exclusions at all, the contract
post-filters its output instead — an implementation detail, not a change of decision.

---

## CD-12 — The dead `category` field is removed

**Decision.** The per-file `category` field in `graph.json` (`auth`/`api`/`data`/`ui`/…), written
by `_categorize_file` (`graph_ops.py:309`), is removed.

**Rationale.** It is computed on every build and **read by nothing** anywhere in the repo. Three
unrelated things are called "category" here, which is why it looked load-bearing: spec frontmatter
`category` is live (`contradictions.py` uses it for same-category peer scoping) and
`classifications.json` is live (directory source/exclude). Only the graph field is dead.

This is a pre-existing cleanup the substrate work surfaced, not something graphify causes. It is
recorded because deleting a field silently is how someone later reintroduces it.

**Rejected alternatives.**

- *Keep it and have the graphify backend synthesise an equivalent.* Rejected: implementing a
  field with no reader is work for nothing.
- *Leave it alone as harmless.* Rejected: it forces every backend to produce a field nobody
  consumes, and it makes the contract wider than it needs to be.

**Revisit conditions.** If a consumer ever wants coarse file categorisation, reintroduce it
deliberately with that consumer named.

---

## CD-13 — The substrate change is a measured migration

**Decision.** No substrate is adopted on argument. Phase 0 is a spike with five acceptance tests
(spec §9) run against three repos — the testbed, freya-devkit, and a Java project. The blocking
criterion is **under-reporting**: graphify must not find fewer edges than the homegrown resolver
on the languages homegrown covers, and any miss must be explained rather than tallied.

**Rationale.** Misses are asymmetric. A missing edge narrows a behaviour's static closure, so the
behaviour is not flagged as affected, so a regression passes the wrap-up gate. A spurious extra
edge only runs a test that was not needed. The safe direction is over-approximation, and only
measurement distinguishes them.

The other four tests exist because each has a known way to fail silently: deletion handling
(graphify's `--update` "preserves existing graph structure", which could mean either thing);
reproducibility (ours is content-stable but byte-unstable — measured, 10 of 10 differing entries
were pure reordering — and graphify is unmeasured); config coverage; and degradation when graphify
is absent.

This is ADR-016's discipline — prove it against the real thing — applied to a dependency decision.

**Rejected alternatives.**

- *Adopt graphify on reputation and fix problems as they surface.* Faster. Rejected: the failure
  mode is a silently narrower blast radius, which surfaces as an escaped regression rather than
  as an error.
- *Compare on synthetic fixtures only.* Cheaper and repeatable. Rejected: the testbed's 609 known
  internal edges and this repo's own Python are the representative cases, and fixtures would not
  have caught F7 either.

**Revisit conditions.** The tests are a gate on adoption, not a one-off. Any future backend passes
the same five before becoming a default.

---

## CD-14 — The homegrown resolver is repaired before it is frozen behind the contract

**Status:** taken 2026-08-19, on Phase 0 evidence
([findings](phases/phase_0/findings.md)).

**Decision.** Phase 1 does not begin with the refactor. It begins by fixing the four resolver
defects the spike found ([backlog item 9](../backlog.md)), adding real-repo regression tests
that would have caught them, and re-running §9.1 against the corrected baseline. Only then is
the resolver moved behind the contract.

**Rationale.** Phase 1's stated safety property is "no behaviour change, and the existing test
suite is the regression gate." Neither half holds today. `test_graph_ops.py` is 18 tests over
synthetic `tempfile` fixtures; it is green while the resolver, pointed at its own repo,
indexes 10 of 50 Python files, emits 0 internal edges and exits 0 reporting success. A suite
that cannot observe the behaviour cannot pin it, so "no behaviour change" would preserve
nothing — and the behaviour being frozen into the permanent zero-install floor is *an empty
graph on freya's own language*.

There is a second, independent payoff. The spike has exactly **one** two-sided diff, because
freya-devkit produced no homegrown edges to compare against. Repairing the resolver converts
it into a second real comparison, on a different language, before the contract's shape is
fixed.

Doing it after the contract is worse than doing it before: the fixes move the §9.1 baseline —
homegrown should recover most of the 18 `import type` edges and the barrel edge — so the
blocking test would otherwise be re-run against a different denominator *after* the interface
had already been specified around the old one.

**Rejected alternatives.**

- *Refactor first, fix the defects behind the contract afterwards.* This is the spec's stated
  order and it is defensible — a contract is backend-agnostic, so freezing an interface does
  not freeze bugs behind it. Rejected on sequencing only: it validates the contract against a
  floor known to be broken, and re-runs the gate against a moved baseline.
- *Treat the defects as Phase 5 agnosticism-sweep work.* Rejected: three of the four are not
  framework assumptions at all, and the fourth (`docs` in the exclusion set) blocks Phase 4.
- *Declare graphify the default and stop maintaining the homegrown resolver.* Rejected —
  CD-2 makes the floor load-bearing precisely for the locked-down-laptop case, which is the
  environment Track B exists to serve.

**Revisit conditions.** If fixing (b), the bare-specifier resolution, turns out to be
substantially larger than it looks, split it: ship (a), (c) and (d), record the internal-edge
count freya-devkit reaches, and let the contract absorb the rest.

---

## Coverage check

Every decision from the brainstorm maps to an entry above. Recorded so nothing is quietly lost
when these become ADRs.

| Decision | Entry |
|---|---|
| Contract with pluggable backends | CD-1 |
| `unresolved` is explicit, never dropped | CD-1 |
| Coverage declaration in metadata | CD-1 |
| Homegrown stays as the floor | CD-2 |
| graphify is the polyglot backend | CD-2 |
| graphify-the-backend and the semantic pass are separate opt-ins | CD-2, CD-5 |
| SCIP excluded | CD-1 (rejected alternatives) |
| Three artifacts, joined on file path | CD-3 |
| No linking graph | CD-3 |
| "Unify the graphs" lean dropped; vision §6 reinforced | CD-3 |
| Provenance tiers gate vs advise | CD-4 |
| Semantic pass on the existing subscription | CD-5 |
| Per-agent model defaults | CD-5 |
| Symbol refines file anchor | CD-6 |
| Docs graph, section-anchored | CD-7 |
| Docs edges carry file **and** symbol targets | CD-6, CD-7 |
| Structural chunking, fences atomic | CD-8 |
| No config/IaC graph | CD-9 |
| No identifier index | CD-9 |
| Helm out | CD-9 |
| Terraform consumed, never parsed | CD-9 |
| Schemas are code | CD-10 |
| Migrations are not graph material | CD-10 |
| Exclusions are a contract input | CD-11 |
| `category` removed | CD-12 |
| Spike-first, five acceptance tests | CD-13 |
| Repair the resolver before freezing it | CD-14 |
| Governance graph deferred | not an ADR — filed in [`../backlog.md`](../backlog.md) |

## Decisions the spike has now settled

Answers from [`phases/phase_0/findings.md`](phases/phase_0/findings.md). They become ADR
material at feature end; the reasoning is in the findings, not reconstructed here.

1. ~~**Is graphify's incremental mode trusted?**~~ **Yes.** Deletion, rename and import removal
   in one `update` left zero dangling links. `--force` is not a staleness guard and is not
   needed. *But* graphify's own cache keys on `mtime`/`ast_hash` only — no tool version, no
   extras set — so a tool upgrade does not invalidate it. Phase 2 owns that.
2. ~~**How do exclusions reach graphify?**~~ **Mostly for free: it indexes everything not
   gitignored.** There is no CLI flag, so any exclusion beyond `.gitignore` is a post-filter on
   its output.
3. ~~**Are graphify's config edges kept?**~~ **SQL and Terraform yes, YAML no** — and YAML fails
   without a warning. Does not disturb CD-9 (no config graph), but it **refutes the premise**
   that retired the identifier index.
4. ~~**Does `graph.json` stay gitignored?**~~ **Yes.** graphify is content-stable but not
   byte-stable — `community`/`community_name` drift between runs — so committing it would
   produce spurious diffs. It also writes only to `graphify-out/`, so **ADR-017's revisit
   trigger does not fire** and `behavior.json` stays where it is.

## Decisions still to come

Raised by the spike rather than answered by it. All are Phase 2 gates.

1. Whether the `EXTRACTED`/`INFERRED` split earns the two-tier machinery in CD-4 at all. It is
   **not** the deterministic/model-judged axis it was assumed to be, and **zero** file-level
   edges on any of the three repos rest solely on an `INFERRED` link.
2. What the contract does about graphify's cache being blind to tool and extras versions.
3. Whether a ~9.3 KB-per-file artifact is acceptable at scale, given every skill `json.load`s
   it per invocation.
4. Whether running a pre-1.0, single-maintainer dependency recursively over a whole codebase
   needs a supply-chain position before it is recommended to other people's repos.
