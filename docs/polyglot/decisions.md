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

> **Superseded for `summarise_coverage()` by CD-27 (2026-08-20).** It was deleted rather than
> wired. Leaving it was the right call while nothing could use it, and the wrong one once
> something could: its `blind_spots()` has no dotfile guard (`.env.local` → `.local`), no
> materiality filter and no notion of project scope, so wiring it up would have imported three
> live bugs and reported a measured 71% phantom. A dead function that *looks* like the answer
> is how the next person reimplements the wrong thing.

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

**Corrected the same day.** As first shipped, the only home for an override was
`classifications.json` — which `CACHE_GITIGNORE` declares regenerable and not to be
committed. So an override survived on the machine that made it and vanished on clone: CI and
every colleague silently graphed a smaller codebase and were told the build succeeded.
[CD-15](#cd-15--project-settings-live-in-knowledge-basesettingsjson) had already rejected that
file as a home for a decision, in those words, on exactly this ground. Writing an ADR does not
make you remember it.

Committed verdicts live in `knowledge-base/settings.json` under `directories`:

```json
{ "directories": { "docs": "source", "packages/legacy": "exclude" } }
```

`classifications.json` keeps the derived and model-authored verdicts, which are cache and are
re-derived when the rules change. Both are folded to one key form on read, because `"docs/"` —
the spelling the documentation uses throughout — matched nothing in the filter while still
reaching the contract as a live override.

A verdict outranks the built-in lists, in two tiers:

| Source | Overrides |
|---|---|
| `settings.json`, or a `user` classification | Everything, including artifact-tree names and `.gitignore` |
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

---

## CD-22 — graphify's symbol graph is projected onto file pairs, and three relations are dropped

**Status:** accepted 2026-08-20 · Phase 2

### Context

graphify's nodes are *symbols*; the contract's are *files*. Its links run symbol → symbol, and
it emits at least eleven relations against the contract's five.

### Decision

Every link is projected onto the file pair its endpoints live in. The mapping table is derived
from counting what each relation actually connects, not from its name.

Dropped, with the measurement that decided it:

| Relation | Links | Why not an edge |
|---|---|---|
| `contains` | 1,199 | File has symbol — the node hierarchy |
| `method` | 1,119 | Class has method — the same, one level down |
| `rationale_for` | 543 | A docstring index: 543/543 `rationale` → `code`, intra-file, `.py` only |

All 2,861 are 100% intra-file, which is the argument by itself: a relation that never crosses a
file boundary cannot produce a file → file edge under any mapping.

Intra-file links of the *kept* relations go too — 1,516 of the 2,007 survivors, 75% — because
each would make a file its own dependent and blast radius walks those edges.

**The table has no default.** graphify's vocabulary cannot be enumerated: grepping its source
yields 26 relation names, and `reads_from` — present in this repository's own graph — is not
one of them. An unlisted relation is counted into `substrate.unmapped_relations` and reported.

### Rejected

**Adopt `rationale_for` as a docs graph.** It is not one. It is a docstring index and cannot
express a relationship between two files. docs.json (CD-7) answers that question from citations
we control.

**Default unknown relations to `references`.** A silent fallthrough is the failure Phase 0
recorded against config coverage — "nothing, and no warning" — and would make an upstream
capability arrive as a graph that merely looks thin.

**Keep intra-file calls as self-edges.** Verified: one self-edge makes `--impact` report a file
as its own direct dependent. Now a validation error, and skipped when linking.

### Consequences

- A node marked `type: module` is an **external module**, not a file. Its `source_file` is
  whichever importer graphify parsed first, so reading it as a file fabricates edges — three
  Swift files each importing `Foundation` produced two edges that exist nowhere in the source.
  It becomes `external:<module>`, which is what the contract already had for this.
- §9.1 passes: 73 file pairs against homegrown's 65, losing nothing. The single edge homegrown
  has and graphify does not is an import inside a *string literal* — homegrown's own false
  positive (backlog item 10).
- Two file pairs rest solely on `INFERRED` links, so the two-tier trust design Phase 0 called
  "unexercised" is now exercised.
- Exclusions are a post-filter; `graphify update` has no exclusion flag. That settles spec open
  question 3.
- The intra-file call graph is a deliberately discarded capability, filed rather than lost.

---

## CD-23 — `auto` is the floor; any other backend is opt-in

**Status:** accepted 2026-08-20 · Phase 2 · supersedes the scoring behaviour added in Phase 1

### Context

`select()` resolved `auto` by scoring each installed backend against the repository and picking
the widest. With a second backend registered that stopped being hypothetical: graphify scored
63 to homegrown's 58 on this repository and would have taken over on the next build.

### Decision

`auto` is the floor. Naming a backend in `knowledge-base/settings.json` *is* the opt-in.
`auto` still runs the census, but only to say what it is leaving out:

```
code-graph: 'graphify' is installed and reads 5 file(s) here that 'homegrown' cannot
(.json, .ps1, .sh). It is opt-in: set substrate.backend to 'graphify' to use it.
```

### Rejected

**Keep scoring.** It means installing a binary anywhere on `PATH` silently changes the
substrate — and therefore every blast radius — for every project on the machine at once, with
no diff. Spec §11 mitigates the zero-install risk with *graphify is opt-in*; CD-13 requires a
substrate change to be a measured migration.

**A separate `substrate.allow` list.** More machinery for the same answer. A project that has
written the name down has decided.

**Silence when a better backend is available.** Opt-in must not mean undiscoverable. Which of
its own files another backend would read is the one thing a project cannot work out for itself.

### Consequences

- A backend that fails *during the build* now degrades to the floor rather than taking the
  build down. Selection already degraded on unavailability; there was no other half.
- The fallback is recorded as `degraded_from` in the artifact, not merely printed.

---

## CD-24 — symbols refine an edge, and are off by default

**Status:** accepted 2026-08-20 · Phase 3

### Context

Spec §5 and CD-6: symbols refine file anchors, they never replace them. Phase 3's deliverable
is the optional refinement, not a new node type.

### Decision

An edge may carry `from_symbol`, `to_symbol` and `line`, behind `substrate.symbols` (default
off). A backend that cannot see symbols is unaffected — this asks for refinement, it does not
require it.

### Rejected

**On by default.** Measured: 73 file-level edges become 417, because a test module calling one
helper sixty times is sixty symbol pairs and one dependency. Nothing downstream reads them yet.

**Symbols as graph nodes.** That is a different graph, and it would break every consumer that
joins artifacts on file path (CD-3).

### Consequences

- Verified rather than assumed: `--impact`, `--dependents` and `--dependencies` return the same
  path strings with refinement on or off.
- An unnamed symbol is omitted rather than recorded as an empty string, and validation rejects
  a symbol field that is present but not a name.

---

## CD-25 — a behaviour's symbols come from coverage, never from the graph

**Status:** accepted 2026-08-20 · Phase 3

### Context

Spec §10 asks for symbols threaded through `behavior.json`'s `exercises`. The obvious source is
the code graph; it is the wrong one.

### Decision

They come from the istanbul coverage report — `fnMap` names each function, `f` counts its
executions. An exercise entry gains an optional `symbols` list. One entry per file, not one per
symbol.

Two filters, both from reading real output (775 functions across 123 files):

- **executed only** (`f[i] > 0`);
- **named only.** 405 of the 775 are `(anonymous_N)`, where N is a positional counter per file,
  so inserting one function renumbers every later one.

### Rejected

**Take symbols from the graph.** `observed` means "the test ran this". Graph symbols would mix
in things nobody executed, which is the difference between measurement and inference — the
distinction the whole trust model rests on.

**One exercise entry per symbol.** `behavior-graph` intersects `exercises[].path` against the
impact set; splitting the entry changes that set's cardinality and every count derived from it.

**Bump `behavior.json`'s version.** It is written and read by nobody. The real compatibility
guarantee is that an entry with no symbols is byte-identical to one from before this existed —
which is asserted.

**Narrow Direction A with symbols.** `--impact` answers in path strings by design (CD-20), so
there is no symbol on the impact side to intersect against. Narrowing is the miss-generating
direction.

### Consequences

- `merge_fingerprint` needed no change: it copies entries by reference, so symbols ride through.
- Spec §10's "thread it through the fingerprint comparison" describes something that does not
  exist — nothing compares two fingerprints' exercise sets. Recorded in the log rather than
  silently reinterpreted.

---

## CD-26 — the backend is chosen once, at install, and recorded per project

**Status:** accepted 2026-08-20 · raised by the user, not by the plan

### Context

Phase 2 made the backend a per-project setting and CD-23 made naming one the opt-in. Neither
said how anybody was supposed to *do* that, and the answer turned out to be: by hand.
`settings.write()` existed with **zero production callers** — its own docstring said the file
"is created when they ask for it", and there was no way to ask. The only discovery path was a
stderr hint that fires when another backend is *already installed*, so you had to own the thing
before being told you might want it. The shipped skill layer never said how to install it.

Four places could ask, and three are wrong:

| Where | Why not |
|---|---|
| **Mid-workflow, in the terminal** | `code-graph` auto-enables non-interactive mode whenever stdin is not a TTY. That is every agent-driven run and every `wrap-up` run, which is to say the workflow. A prompt there fires almost exclusively for someone typing the command by hand |
| **Mid-workflow, through the agent** | Works — the script says "I need a decision", the agent asks in chat. But the instruction telling the agent to do that lives in the skill layer, **read on every invocation to say nothing on almost all of them**. Standing token cost for a question asked once per machine |
| **Per project, every time** | The same answer, retyped in every repository. The user's objection, and a fair one |

### Decision

**`freya install` asks, once.** It is run by a person, in a terminal, deliberately — the one
moment a keyboard is guaranteed. A numbered menu, the same shape as the directory classifier's
existing prompt. `freya update` asks too, which is the migration path for anyone installed
before the question existed: no version check and no migration command, because "has this
machine answered?" is the only state that matters.

The answer is the **machine-level default**, `~/.freya/settings.json` — a directory the updater
already owned for its throttle stamp, and deliberately not inside any single agent's skills
folder, because the suite installs for more than one host and the answer is the same on all of
them. `FREYA_HOME` overrides it, which is what makes the test suite independent of whose
laptop it runs on.

**Precedence: project, then machine, then floor.** In a project file, `auto` means *defer to
the machine*; an explicit name — including `homegrown` — means the project decided for itself,
which is how one repository opts out without changing the others.

**The first build in a project records the machine answer in that project's own committed
`settings.json`.** This is the load-bearing half. A machine default that stayed implicit would
mean the same commit graphs differently on a machine that has one and a machine that does not
— and integration behaviours' static fingerprints come from the code-graph closure into
`behavior.json`, which is committed, so that divergence would arrive as a diff reading like
behaviour drift (spec §11's own recorded risk). Writing it down makes the repository
self-describing: a clone and CI resolve the same backend without sharing anyone's machine
configuration. That is the property CD-15 exists for.

`freya code-graph --use <backend> [--global]` is the command, and it validates the name against
the registry — the moment somebody is present to be told they typed it wrong is the moment to
check, not a week later when the name resolved to nothing and the project quietly ran the floor.

### Rejected

**Ask through the agent, via the deferred-prompt protocol.** `needs_classification()` /
`get_classification_prompt()` / `classify_with_ai_response()` already exist for exactly this
shape — and have no CLI flag and no caller, which is the fourth instance of this codebase
writing an API whose effect does not exist. Finishing it would have been the bulk of the work
and it buys nothing here: the question is per machine, and install is a better place to ask a
per-machine question than the middle of somebody's commit. The protocol is still the right
answer for *directory* classification, which is genuinely per project and still stuck.

**A standing line in `SKILL.md` telling the agent what to do when a decision is needed.**
Rejected on cost: the skill layer is read on every invocation. An instruction that is relevant
once per machine, forever, is the wrong thing to put where everything is read every time. The
instruction rides in the *output* of the one run that needs it instead.

**Ask on first build instead of at install.** Same TTY problem, and it asks per project what
is a per-machine question.

**Let the machine default apply without recording it.** Cheaper, and it reintroduces exactly
the divergence the committed file prevents. Two engineers, same commit, different graphs, and
a committed `behavior.json` diff nobody can explain.

**Write the floor into `settings.json` when nobody answers.** Rejected firmly. A headless run
with nothing configured writes *nothing*: a committed file recording a decision no person made
is the confidently-wrong failure this whole substrate exists to refuse. "Not yet asked" is an
honest state and the build handles it.

**Allow `directories` at machine level.** A global "docs is source" would apply to
repositories nobody has looked at, and a global `node_modules: source` is a 50,000-file graph
on every project on the machine. Scope is a fact about one project; a parser preference is a
fact about the person. The key is dropped *and reported*, because someone who writes it has a
reasonable expectation it does something.

### Consequences

- `settings.write()` finally has a caller, and `Settings` grew `file_backend` / `file_symbols`
  so that "the key is absent" and "the key is explicitly set" stay distinguishable. Merging
  over `DEFAULTS` had collapsed them, which would have let seeding freeze a deliberate `auto`
  into a fixed name on the next build.
- A root `conftest.py` points `FREYA_HOME` at a throwaway directory for the whole session.
  Without it the suite's own result depends on unversioned state outside the checkout — green
  on one laptop, red on another, for a reason nothing in the repository records.
- `updater.STATE_DIR` became `state_dir()` honouring the same variable, so the override
  relocates both files rather than one. Pinned by a test that asserts the two agree, because
  two independent computations of one path is the shape this repository keeps paying for.
- `graph_ops.py` now does `sys.exit(main())`. It discarded the return code, which went
  unnoticed while every failure path called `sys.exit` directly — until one wanted to *return*
  a code, and `--use` with an invalid name printed its error and exited 0.


---

## CD-27 — Blind spots ride in the answer, filtered by materiality, and never become a refusal

**Context.**

The floor backend reads 4 languages / 6 extensions; graphify reads 40 / 93 and must be installed separately. `CodeGraph._scan_files` (graph_ops.py:1796) globs by `FILE_PATTERNS`, so a file the backend cannot read is never enumerated at Python level at all — it is not "skipped", it is invisible. On a repo of 12 `.java` + 3 `.ts` under the floor, the build prints `Found 3 source files` and returns `files_scanned: 3`. Reproduced live: nothing on stdout, nothing on stderr, nothing in the artifact mentions Java. `files_scanned` reads like a denominator and is a numerator.

`project_shape` compounded it: it reported blind spots only on the `internal_edges == 0` branch, so the same repo returned `recommendation: brownfield`, `source_files: 3`, `runtime: jvm` and no `blind_spots` key — asserting "jvm" and "3 source files" in one evidence block without noticing the tension.

The consumer is not a human. `--non-interactive` auto-enables whenever stdin is not a TTY, which is every agent-driven run and every wrap-up run, so a printed warning lands nowhere. Verified: `behavior_graph.py:249`, `drift.py:89` and `run_behaviors.py:318` all use `capture_output=True` and read only stdout on success; `run_behaviors` touches `exc.stderr` only inside `except CalledProcessError`, which no successful query produces. Stderr is dead skill-to-skill. It is alive agent-to-CLI, because `bin/freya_cli.py:146` is a plain `subprocess.call` with inherited streams.

The parts were already lying around and unwired: `Coverage.blind_spots` (substrate.py:415) is correct and reachable only through `summarise_coverage` (:810), which has zero production callers; `backends.extension_census` (backends.py:199) is the only census that honours exclusions and runs only when `len(available_backends()) > 1` — i.e. only when the better backend is already installed; the existing stderr hint (backends.py:159-174) fires under the same gate. Every existing nudge fires when you need it least.

ADR-005 promises the graph never answers "nothing" when it means "I don't know". That promise was implemented at the repository level (a Java repo will not call itself greenfield) and never at the **answer** level. `get_impact` already returns `not_in_graph` in the JSON payload, with the comment "the caller is usually another skill reading `--format json`, and stderr is not part of what it parses" (graph_ops.py:2250-2251) — the right argument, already written down here, applied only to "the file you asked about is unmapped" and never to "this answer is incomplete".

**Decision.**

Every build/update that writes the graph runs one pruned tree walk, filtered by the build's own scope rule (`CodeGraph._should_exclude`, not `substrate.exclusions`) and by a two-tier extension model, and records the result at `graph["substrate"]["unmapped_source"]`. `graph.json` is gitignored (`git check-ignore -v` -> `.gitignore:18:**/.graph/`; `behavior.json` is deliberately not), so the block costs zero tracked diff on every machine. The walk lives in `_finalise` — the single funnel every backend passes through, and the only point after `update()`'s wholesale `graph['substrate']` rewrite at :2095-2099. Measured 0.0007s–0.0146s across seven real repos, against the 2.105s `_scan_files` already pays on the largest.

`--build`, `--update`, `--query` and `--impact` carry it in the answer, for free, because `load()` already parses the whole `substrate` block into memory. `--build`/`--update` carry the full block including an `advice` sentence and a `readable_by` recommendation; `--query`/`--impact` carry a structured-only digest (~32 tokens) because those are the surfaces an agent hits repeatedly in one session. `--dependents` and `--dependencies` keep their bare arrays and get the caveat on **stderr** — dead where it must be dead (it cannot perturb `run_behaviors.py:334`'s `isinstance(data, list)` validator), alive where it must be alive.

`directories`, not just `extensions`. `{".java": 12}` makes an agent derive a search target; `{"src/main/java/com/acme": 12}` **is** the search target, and the paths are already in the walk's hand — both existing censuses hold them and throw them away.

The key is **absent** when there is nothing to say. Two tiers draw that line: `SOURCE_EXTENSIONS` (closed-world, definite program source) is always reported; `SCRIPT_EXTENSIONS` (`.sh`, `.sql`, `.ps1`, …) only when its count exceeds `max(files_graphed, 2)`. Measured: silent on freya-devkit, acme-media and acme-lab; `{".java": 12}` on the fixture; `{".mjs":3,".mts":2,".feature":1,".prisma":1}` on acme-site-testbed. A closed world defaults to silence on the unknown, which is the correct default for a signal whose only value is being believed.

`substrate.unmapped_source` is **never** a refusal. `degraded_from` means "you asked for X and got Y" (abnormal) and rightly makes `run_behaviors` decline to answer; blind spots mean "the backend you chose cannot read everything", the normal operating condition of the floor on any polyglot repo. Nothing refuses, warns loudly, or changes an exit code because of it. The rule is written into `run_behaviors._code_graph_deps` as a comment beside the existing `degraded_from` refusal and pinned by `test_a_repo_with_unmapped_files_still_fingerprints_static`.

`project_shape` reads the block instead of walking, reports it on every branch, and prints it in `--format text` — the surface bootstrap actually invokes and the one that dropped the field entirely.

**Rejected.**

*A standing instruction in SKILL.md* — barred by CD-26 on its face, and the counter-argument is already in this codebase at backends.py:165-167: "The instruction rides in this one run's output rather than living in the skill layer, where it would be read on every invocation forever to say nothing on almost all of them." The only documentation added is a reference-table row.

*Wrapping `--dependencies` in an envelope.* `run_behaviors.py:334` returns `graph-query-failed`; `fingerprint_behavior` routes every `confirmed` and every `integration` behaviour through `static_fingerprint`, so it is repo-wide; `merge_fingerprint` (behavior_graph.py:44-54) then freezes `behavior.json` where there is history or writes empty `exercises` where there is not; `_affected_from_impact` matches nothing; wrap-up's Direction-A gate runs **zero** behaviours and exits 0. Breaking "closed" here is a repo-wide silent green, not a loud failure — ADR-005's defect arriving through the door the validator was meant to close.

*Wrapping `--dependents` only.* It genuinely has zero programmatic consumers (verified: the only `.py` occurrences are its own argparse at :2748 and dispatch at :2820), so it is free. Rejected because it buys a shape asymmetry across a pair CD-20 presents as matched, on a surface nothing parses. The stderr line gives it a signal at no shape cost.

*Expressing blind spots through `degraded_from`.* Zero new plumbing; `_graph_degraded_from` already refuses on it. That is the bug: the refusal would fire on every polyglot floor-backend repo, making a routine condition behave like an abnormal one.

*Recording it in `behavior.json`.* Committed under ADR-017/CD-15, and it **churns** — one added `.java` file would rewrite every behaviour's fingerprint for a fact that belongs to none of them.

*Bumping `GRAPH_SCHEMA_VERSION` to imply the census's presence.* `is_stale` then forces a full rebuild on every machine — and, second-order, that rebuild changes the graph `--dependencies` closures are computed against, and those closures are written into the **committed** `behavior.json`. A `{"files": 0}` sentinel achieves the same discrimination for thirty bytes in a gitignored file and no forced rebuild.

*Reusing `summarise_coverage`.* Tempting: it computes the wanted `blind_spots` and its tests already pass. But its `blind_spots` has no dotfile guard (`.env.local` -> `.local`), no materiality filter and no notion of scope, so it would report the 71% phantom; and its missing half was never the aggregation, it was `present_files`.

*Reusing `backends.extension_census`.* Structurally the right walk, and it is what `scope_census` copies — but it honours only `Exclusions`, a strict subset of the real rule (8 of 9 probe paths missed; 310 vs 261 files on a 45k repo), and it is gated on the other backend already being installed.

*A query-time walk.* New per-query cost where build-time capture is free, and it answers about a **different instant** than the graph, conflating "unreadable" with "not rebuilt yet".

*Storing the census under `substrate` from inside `build()`.* Silently dropped by the next `--update`, which rebuilds `graph['substrate']` from a fresh `graph_metadata()` dict.

*Renaming `files_scanned` to `files_graphed`, and adding `files_in_scope`/`files_excluded`.* The rename churns two test assertions and `format_summary` for no in-repo reader. `files_in_scope` requires walking **every** extension, which re-admits the cost the candidate short-circuit removes and produces a new misleading denominator: measured, it reports freya-devkit as "62 of 90 in-scope graphed" — a 31% apparent blind spot on a repo whose real unmapped count is zero. Putting `unmapped_source.files: 12` next to `files_scanned: 3` fixes the misreading at the point of confusion instead.

*A "some registered backend could read it" filter.* Kept as `readable_by`, a recommendation, never a filter — a Ruby repo on a machine with no Ruby backend would otherwise report nothing, which is ADR-005's confidently-empty failure wearing a principled hat.

*Deleting `project_shape.unreadable_files` outright.* Larger blast radius than the alternative: it regresses every pre-census graph to "no blind spots at all" and breaks three fixture tests. Preferring the artifact and keeping the walk as fallback is six lines and breaks nothing.

**Known gaps, accepted.** Extension is structurally the wrong key for the third category — in-coverage-but-out-of-scope, e.g. a `.ts` under `docs/`. Verified: two such files vanished from a fixture's graph and appeared in no census. `directories` is a half-step toward paths and the seam a fuller version widens through. The tier lists are curated, so a language nobody listed gets silence; that is a narrower ADR-005 hole in the same family as the one being closed, and it is the price of a signal that is quiet enough to be believed. `SCRIPT_MATERIALITY_FLOOR = 2` is a guess with a number on it.
