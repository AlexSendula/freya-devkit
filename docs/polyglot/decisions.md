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

## CD-15 — Project settings live in `knowledge-base/settings.json`

**Status:** taken 2026-08-19, ahead of Phase 1.

**Decision.** Per-project substrate configuration goes in `knowledge-base/settings.json` —
committed, travelling with the repo, and outside the project root.

**Rationale.** Three properties were needed at once: the setting has to survive a clone (a
teammate must get the same backend), it must not be lost when the cache is cleared, and it must
not add a file to the project root.

`knowledge-base/` satisfies all three, and it already exists wherever freya runs. Only
`knowledge-base/.graph/` is gitignored; `specs/`, `decisions/` and `principles.md` are tracked,
so a settings file beside them is committed by default. The directory name is hardcoded in
every skill, so the location is stable rather than another thing to configure.

**Rejected alternatives.**

- *`freya.json` at the repo root.* Proposed first and rejected by the engineer: it pollutes the
  root of every adopting project for a tool that already owns a directory.
- *Extend `knowledge-base/.graph/classifications.json`.* No new file, but that path is
  gitignored regenerable cache. Configuration there would not survive `--clear` and would not
  reach a fresh clone, so every checkout would re-decide its own backend.
- *A `"freya"` key in `package.json`.* Fine for Node, and worth supporting later as an optional
  override. Rejected as the home: Java, Python and Go repos have no `package.json`, and keying
  the polyglot toolkit's own config to a Node manifest is precisely the framework assumption
  Track B exists to remove.
- *No config; auto-detect only.* Zero surface, but unpinnable — a contributor without graphify
  installed silently produces a different graph, which is the "never silent" rule inverted.

**Revisit conditions.** If a project ever needs to relocate `knowledge-base/`, this moves with
it — the setting cannot live inside the thing it configures the location of.

---

## CD-16 — A backend declares languages *and* relation kinds

**Status:** taken 2026-08-19, ahead of Phase 1.

**Decision.** The coverage a backend declares in graph metadata names both the languages and
extensions it parses **and** the relation kinds it can emit (`imports`, `calls`, `inherits`, …).

**Rationale.** Languages alone answer "can you see this repo at all", which is the headline
Track B failure — a Java repo silently graphed as empty. Relation kinds answer the finer
question a caller actually asks: blast radius wants import edges, and a query that needs
symbol-level `calls` should be able to degrade by itself rather than distrust the whole graph.

It also forces Phase 1 to define the contract's edge-kind vocabulary. Phase 3 needs that
vocabulary anyway to thread the optional `symbol` through, and inventing it under the pressure
of a migration is worse than agreeing it now.

**Rejected alternatives.**

- *Languages only.* Least to build. Rejected: the scanner matches on extensions, so every
  caller would have to map language → extension itself, and those mappings would drift.
- *Languages + extensions, no relation kinds.* The simpler option, recommended at first.
  Rejected because it defers the edge-kind vocabulary to Phase 3, where it becomes a migration
  rather than a definition.

**Revisit conditions.** If the relation-kind list turns out to be per-backend rather than a
shared vocabulary, the contract is describing implementations instead of an interface — treat
that as a design failure and collapse it back to a fixed set.

---

## CD-17 — Graphs are stored per backend, side by side

**Status:** taken 2026-08-19, ahead of Phase 1.

**Decision.** Each backend writes `graph.<backend>.json`. Switching backends does not overwrite
the previous graph.

**Rationale.** [CD-13](#cd-13--the-substrate-change-is-a-measured-migration) requires a
substrate swap to be a *measured* migration — diff before trusting. That is impossible if the
new graph destroys the old one, because the baseline is gone at exactly the moment it is
needed. Phase 0 hit this directly: comparing homegrown against graphify meant moving files by
hand, and the numbers were nearly re-derived against the wrong baseline more than once.

Keeping both current also makes the degradation story checkable rather than asserted — the
reduced coverage a fallback declares can be diffed against what the preferred backend found.

**Rejected alternatives.**

- *One `graph.json`, overwritten.* Matches today and is simplest. Rejected: it makes the
  comparison CD-13 mandates cost a full rebuild of the backend you just replaced.
- *One `graph.json` plus a stashed `graph.previous.json`.* Cheap one-hop comparison without
  filename sprawl. Rejected because it cannot hold two backends *current*, which is what
  validating a fallback needs.

**Revisit conditions.** If the artifacts get large enough that keeping two is a real cost — the
2.8 MB / ~9.3 KB-per-file figure from Phase 0 scaled to a big repo — make retention explicit
rather than silently dropping one.

---

## CD-18 — Workspace packages resolve in the homegrown backend

**Status:** taken 2026-08-19, ahead of Phase 1.

**Decision.** The homegrown resolver reads `workspaces` from `package.json`, maps each package
name to its directory, and resolves cross-package imports internally. It does not wait for the
graphify backend.

**Rationale.** In a monorepo the cross-package edge is *the* architectural edge. Measured on a
two-package fixture, `apps/mobile` importing `@acme/domain` resolved to `external:@acme/domain` —
the toolkit reporting the most important relationship in the repo as a third-party dependency.
graphify resolves it correctly (`imports`, `imports_from` and `calls`), which confirms the edge
is real and findable rather than ambiguous.

Leaving it to graphify would mean the zero-install floor cannot see a monorepo — and per
[CD-2](#cd-2--two-backends-ship-and-the-homegrown-one-is-the-floor) the floor exists for the
locked-down machine, which is the environment least able to install a dependency. A floor that
collapses on the layout the immediate real target uses is not a floor.

The immediate target is concrete: acme-travel is moving to Expo/React Native with a
`packages/domain` + `apps/mobile` npm-workspaces shape, and plans to run freya on it before the
migration to capture undocumented behaviour.

**Rejected alternatives.**

- *File it; graphify covers it in Phase 2.* Keeps Phase 1 to contract plumbing. Rejected on the
  floor argument above.
- *Fix it after Phase 1, behind the interface.* Cleaner sequencing. Rejected only on timing —
  it is the same defect class as the six already fixed, and bounded.

**Revisit conditions.** pnpm and yarn workspaces declare membership differently
(`pnpm-workspace.yaml`, `package.json#workspaces.packages`). If supporting them turns into
per-tool special-casing, that is the signal to stop and let the substrate contract own package
resolution instead.

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
| Settings in `knowledge-base/settings.json` | CD-15 |
| Coverage declares languages **and** relation kinds | CD-16 |
| One graph artifact per backend | CD-17 |
| Workspace resolution in the homegrown backend | CD-18 |
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

## The fork, resolved 2026-08-20 — Phase 2 is unblocked

Phase 1's review reached a blunt verdict, and it is right: **the contract is homegrown's shape
wearing an interface.** The vocabulary and the metadata block are real, but the executable part
stops exactly where the incumbent's private methods begin. Demonstrated, not argued — a second
backend built to the contract, shaped like this repo's own reference stub:

1. crashed on a method the contract never mentions (fixed),
2. crashed on a keyword the contract never specified (fixed — the signature is now part of the
   contract and checked),
3. **then exited 0, printed `{"files_scanned": 3}`, and wrote no graph at all.**

The third is the one that matters, and it is a design question rather than a defect.

### What has to be decided

**A. Who owns the post-build step?** Persistence, validation and the `dependents` index all
live inside `CodeGraph`. `_write_graph` is a private method of the incumbent;
`substrate.validate_graph` has zero production callers; `dependents` — the reverse index every
consumer actually reads for blast radius — is not mentioned in the contract at all. A
conforming backend therefore produces nothing and reports success, which is ADR-005's
confident-empty failure one level up.

The fix is to move build → validate → derive `dependents` → persist into the socket, so a
backend returns a graph and the socket owns everything after it. `dependents` is a pure
function of `imports`, so deriving it centrally is strictly better than requiring every
backend to emit it correctly.

**B. Is the contract's unit a file or a node?** `RELATION_KINDS` offers `calls`, `inherits` and
`references`, but the shape `{files: {path: {imports: [str]}}}` has nowhere to put one — they
fold to a file pair and the kind is discarded. Measured against Phase 0's own numbers, the
vocabulary can name **2,102 of graphify's 5,027 real links and cannot express 58%**.

Related and sharper: obligation 3 mandates **per-edge provenance**, `PROVENANCE` is referenced
by no code, and it cannot be — `validate_graph` requires each specifier to be a *string*, so an
edge object is rejected. Spec §10 lists provenance tagging as a **Phase 2 deliverable**, so
Phase 2 as written cannot ship without reopening the contract Phase 1 existed to close.

Three coherent answers, and the choice is genuinely open:

| | Means | Cost |
|---|---|---|
| **File-level, honestly** | Drop `calls`/`inherits`/`references` from the vocabulary and strike provenance from the obligations and from Phase 2 | Loses CD-16's finer promise and most of what graphify knows. Cheapest, and matches spec §5's deliberate file-level floor |
| **Edge as an object now** | `{'to': …, 'kind': …, 'provenance': …}` instead of a bare string | One producer and one consumer today, so the migration is cheapest it will ever be. Touches every reader of `imports` |
| **Defer to Phase 3** | Keep strings, add the richer shape with symbols | Spec §10 already scopes the edge change to Phase 3 — but then Phase 2 must ship without the provenance it promises |

**Recommendation: A regardless, and B as "edge as an object now".** A is not really optional —
without it the socket cannot run anything but the plug it was moulded around. For B, the
argument for doing it now is that the cost only rises: every phase after this adds a reader.

### Decided

Both, as recommended, plus a third the user raised that neither branch of the fork covered.
They become CD-19, CD-20 and CD-21 below. Shipped in `b7b9d4b`; measured on freya-devkit as 57
files / 419 edges / 64 dependents, identical to the run before the change once the one new
`import substrate` in the test file is accounted for. 1,186 tests, up from 1,151.

### Everything else from that review

Fixed in `832029c` and the commit after it: the un-upgraded `.gitignore` that made
`graph.<backend>.json` committable, degradation never reaching the artifact, `--clear` leaving
a copy behind, the census running when it could not change the answer, exclusions never being
passed by the only production caller, and two workspace-glob defects.

Left deliberately: `Selection.metadata()` and `summarise_coverage()` still have no production
caller, and `coverage.relations` is written and read by nothing. All three are downstream of
decision A — wiring them before the socket exists would be wiring them to the wrong place.

---

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

---

## CD-19 — The contract persists the graph; a backend only produces it

**Status:** accepted 2026-08-20 · resolves fork A

### Context

`CodeGraph.build()` linked `dependents`, wrote both artifacts and returned a summary. A second
backend built strictly to the contract therefore produced nothing and reported success —
ADR-005's confident-empty failure one level up, demonstrated rather than argued.

### Decision

`build()` and `update()` return a `substrate.Result`: the graph, and what the backend did to
get it. `run_build` / `run_update` derive `dependents`, validate, and write both artifacts.

`Result` exists because a bare dict cannot say "nothing changed", which `update` has to be able
to say without a sentinel every caller then has to know about.

### Rejected

**Leave persistence in each backend and document what it must do.** A contract enforced by
documentation is the thing Phase 1's review found. The second backend satisfied every
documented obligation and still wrote no file.

**Put the shared code in `backends.py`.** Selection and finalisation are different concerns,
and a backend that is never selected still has to be finalisable by its own tests.

### Consequences

- `dependents` is rebuilt from scratch on every write, never appended to. An incremental pass
  that only adds entries leaves an edge behind when the import justifying it is deleted.
- `substrate.validate_graph` had **zero production callers**. It now runs on every build, and
  writes its errors into `substrate.validation` in the artifact — the run's stderr is gone by
  the time anyone reads the graph.
- `project_dir` joins the required backend attributes. The contract writes the files, so it has
  to know where.
- Roughly forty tests called `CodeGraph.build()` directly and asserted on its return value,
  which meant the suite had never exercised the path production uses. They go through the
  runner now.

---

## CD-20 — An edge is an object, and the schema is versioned

**Status:** accepted 2026-08-20 · resolves fork B

### Context

An edge was a bare string, so it could carry exactly one fact: where it pointed. `imports` and
`re_exports` were the same value; symbol-level relations could not be written at all. Measured
against Phase 0: **2,102 of graphify's 5,027 links expressible, 58% not.**

### Decision

`{"to": …, "kind": …, "provenance": …}`, and `{"from": …, …}` going backwards. `kind` comes
from `RELATION_KINDS`; `provenance` from `PROVENANCE`. Schema 1 → 2.

Two boundaries drawn at the same time, both load-bearing:

- **Node queries answer in paths, not edges.** `--impact`, `--dependents` and `--dependencies`
  answer "which files"; three other skills feed the result straight into set arithmetic, where
  an edge object raises `unhashable type: 'dict'` in a different skill for no gain. Only
  `--query` returns edges. Those three skills needed no change at all.
- **Readers accept both shapes, permanently until the version says otherwise.** `graph.json` is
  gitignored, so there is no committed copy to correct in a commit — an older one sits on a
  machine until something rewrites it, and refusing to read it is indistinguishable from a
  project with no dependencies.

### Rejected

**File-level, honestly** — drop the three symbol kinds and strike provenance from Phase 2.
Cheapest, and it matches spec §5's deliberate file-level floor, but it gives up most of what
the second backend knows in order to avoid a migration that only gets more expensive.

**Defer to Phase 3.** Matches spec §10, but Phase 2 promises per-edge provenance it then cannot
deliver, so the contract reopens anyway — later, with more readers.

**Keep strings and add a parallel `edges` key.** Zero downstream risk, and two representations
of one fact that drift. This repo has been bitten by exactly that (the byte-identical
`CACHE_GITIGNORE` in two skills).

### Consequences

- `export * from './y'` is recorded as `re_exports`, so a barrel file that only forwards a
  module is now distinguishable from one that uses it. The homegrown backend's coverage claims
  that relation rather than over- or under-stating what it emits.
- Importing *and* re-exporting the same module is one `imports` edge, not two. Two edges to one
  target would double it in every dependents list.
- `--update` rewrites a legacy artifact even when no source file changed. It is the command the
  steady-state workflow runs and it short-circuits on "nothing changed", so without this the
  migration reaches almost nobody. Verified on a hand-downgraded copy of this repo's own graph.
- `upgrade_edges` deliberately does **not** stamp `version`. That field records what is on
  disk; stamping it on read would make every graph report itself current at the moment reading
  is how we discover it is not.
- An upgraded edge claims `imports` / `extracted` — exactly what the string era could express.
  It must not claim a kind the old resolver never determined.

---

## CD-21 — The exclusion defaults are arguable

**Status:** accepted 2026-08-20 · raised by the user, not by the fork

### Context

The name lists in `_get_exclusion_rules` had just been re-scoped by depth (CD-14's follow-on).
The user objected: we cannot know what some other repository keeps in a folder called `docs/`,
so a default applied everywhere might break a project neither of us has seen — and proposed
scoping the rule to this project only.

Scoping it that way is not implementable without hardcoding a name or path, and the change was
strictly *more* inclusive than what it replaced, so it could cost noise but never a missed edge.
Checking whether a project could simply override the default found the real defect:
`set_classification('docs', 'source')` was accepted, written to `classifications.json`, and then
silently overruled — `_should_exclude` never consulted classifications at all.

So the lists were not defaults. They were hardcoded answers with no appeal, and a wrong one was
unfixable.

### Decision

A classification verdict outranks the built-in lists, in two tiers:

| Source | Overrides |
|---|---|
| `user` | Everything, including artifact-tree names and `.gitignore` |
| `ai` | Root convention names and `.gitignore`, not artifact trees |
| `rule` / `gitignore` | Nothing — they are the lists' own output, so overriding would be circular |

Precedence, stated once: **a stated verdict beats a derived one at any depth; among equals the
deepest wins.**

`scripts` returns to the root-only exclusion list. Dropping the name outright had un-excluded a
root `scripts/` in every project the toolkit had ever run on, to fix one repo's *nested*
`skills/*/scripts/`.

### Rejected

**One tier — any verdict overrides anything.** A model classifying `node_modules` as source is
a plausible failure mode and a person typing it is not, and the blast radius of the first is a
50,000-file graph.

**Scope the rule to freya-devkit.** The user's original proposal. Needs a name or path
hardcoded, and leaves every other project with the same unarguable defaults.

**Let file-kind patterns be overridden too.** `*.d.ts` and `*.min.js` are claims about what a
file *is*, not about which directories are in scope.

### Consequences

- Three layers had to agree, and it took three attempts to find them all: the file filter; the
  directory classifier, which re-asserted the rule one level *below* an override and won
  because a stale cached verdict sat deeper; and the `Exclusions` the CLI passes back into
  `build()`, assembled from the same `.gitignore`, which undid the override a step later.
- Overrides therefore travel on the contract as `Exclusions.overrides`, so a Phase 2 backend
  that has never heard of `classifications.json` honours them too.
- A directory whose ancestor already carries a stated verdict is no longer classified at all —
  it inherits. Classifying it re-applies the very lists the ancestor overrode.
- A nested source verdict widens the top-level scan root, or the override records an opinion
  nothing ever globs for.
- `RULES_VERSION` bumped to `2026-08-20`, so cached `rule`/`gitignore` verdicts are re-derived.
