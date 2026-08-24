# Roadmap

The single live backlog for freya-devkit. Everything genuinely outstanding lives here: the
next initiative, deferred capabilities, verified open defects, and the items that need a
platform or a live agent run we cannot give them yet.

It replaces the two backlogs that used to sit inside the historical design tree
(`design/notes.md` and `design/behavior-layer/parking-lot.md`). Those were written mid-flight
and accumulated entries that have since shipped. Every item below was re-verified against
shipped code on **2026-08-19**; delivered work was dropped rather than carried. Current
release: **0.3.1** (2026-08-24).

Each item says *what*, *why it was deferred*, and *how to pick it up*. Keep it that way —
an item nobody can act on is noise.

> **Why `roadmap.md` and not `backlog.md`.** `freya status --write-backlog` writes
> `knowledge-base/BACKLOG.md` by full overwrite (`collect_status.py:366`), and on a
> case-insensitive filesystem that is the same path as `backlog.md`. This file is
> hand-maintained and was renamed on 2026-08-21 to keep the toolkit from destroying it.
> `BACKLOG.md` beside it is the generated census — behaviors to confirm, tests owed,
> coverage gaps, open findings — and is regenerated, never edited.

---

## Track B: the polyglot substrate — shipped 2026-08-21

`freya-code-graph` was a regex-driven import scraper covering TypeScript, JavaScript, Python
and Go. Real work projects are Java, Kotlin, Swift, Rust, C#, plus config and deployment
material — and the graph was blind to all of it. Worse, it did not *say* so: a Java repository
produced zero files, zero edges, exit 0, and was then classified `greenfield` by the shape
detector. That was the wall, hit on the first attempt to use the toolkit on a work laptop.

It is done. The graph is now produced through a contract with interchangeable backends: a
stdlib-only floor that always ships, and an opt-in backend reading 40 languages across 93
extensions. Every answer carries what its backend could not read.

**The decisions are in [`decisions/`](decisions/), ADR-018 through ADR-029.** Start with
ADR-018 (the contract), ADR-019 (the floor, and how a backend is chosen) and ADR-029 (an
answer says what it could not read). The narrative is in
[`explanations/how-it-works.html`](explanations/how-it-works.html); the reversals are in
[`explanations/evolution.html`](explanations/evolution.html).

### What was deliberately not built

- **A resource graph for config-as-code** — no Helm, no HCL resource index, no Kubernetes
  edges. See ADR-027. The original justification for dropping it was *refuted* by the Phase 0
  spike and the conclusion survives on separate reasoning, which ADR-027 records; do not
  reuse the old argument.
- **Schema migrations as graph material** — same record.
- **A config identifier index.** Still unbuilt, and still wants a consumer before it is worth
  building.

### Still open, and carried forward

- **Per-edge provenance is recorded and enforced by nothing.** Every edge says whether it was
  read from the source or worked out by resolution, and the design says only the first kind
  may gate a commit. No code filters on it. Either write the filter or strike the promise —
  see ADR-021, and item 13 under *Open defects*.
- **The coverage block cannot say "I do not emit this field"** — item 14 below.
- **An unmapped file cannot surface as a coverage gap** in the git-tracked `BACKLOG.md`:
  `behavior_graph.gaps()` enumerates only files that are in the graph — and, since item 18,
  only the ones a behavior could name. The census is sitting in `graph.json` for it to read
  whenever the churn is judged worth it (ADR-029).
- **The framework-agnosticism sweep** over docs-manager templates, the shape detector and the
  security heuristics was scoped into Track B and only partly done. The shape detector is
  polyglot now; the doc templates and the security heuristics still assume a Node/Next shape.
- **Brownfield over a vendor substrate** — the ownership-boundary question below is unchanged
  and is the natural successor: work repos are usually *also* brownfield-over-a-platform.

## Deferred capabilities

### The semantic pass for the docs graph

`docs-graph` finds doc → code edges by three deterministic readers: fenced code blocks,
inline `path:line` citations, and link targets. A **semantic pass** — asking a model which code
a paragraph is about, when no citation exists — was designed and never built.

It matters for a specific adopter: one whose documentation cites no code at all. All three
readers then yield nothing, `docs.json` is a list of documents with zero edges, and the reverse
question ("I changed this file, which docs now lie?") has no answer for them. This repository is
unusually citation-heavy because its own conventions demand `path:line` provenance, which is not
evidence about anybody else. ADR-026's first revisit condition is the trigger: check it on the
first adopter whose docs were not written under that habit.

The design, if it is built: edges from the pass are `inferred`, never `extracted`, so they are
distinguishable from a real citation and can be filtered out wherever that distinction ever
starts being enforced (ADR-021). It runs on the engineer's own agent session rather than an API
key the toolkit holds — ADR-015's rule, and the reason there is no model call anywhere in the
shipped tree.

Recorded here rather than as an ADR because there is nothing to decide yet: it is unbuilt, and
a record describing behaviour that does not exist is the defect this project keeps catching.


### Per-framework observed-coverage adapter (V8 + CDP) — the big one

**What.** Real *observed* `TEST → CODE` coverage at the integration/e2e level: launch the app
under `--inspect`, collect V8 coverage over the Chrome DevTools Protocol (the actual worker
is at inspector **port + 1**), then remap bundled `.next` output back to source through source
maps. Reference implementation: **nextcov** (stevez/nextcov) — dev and prod, emits
istanbul-format, merges with vitest. `next-test-api-route-handler` is a related route-handler
test tool.

**Why deferred.** Framework-specific (the CDP port dance plus source-map remapping; nextcov
is Next-only and **Next 16 + Turbopack support is unverified**), a meaningful chunk of
engineering, and a Node dependency. Too big to bolt on mid-implementation.

**What ships instead today.** Static coverage via code-graph: `fingerprint_behavior()`
(`skills/freya-behavior-runner/scripts/run_behaviors.py`) runs observed coverage only at
`level: unit`, and returns a static fingerprint for integration. Static
is conservatively broad, which is the safe direction for blast radius. The observed adapter
*upgrades* integration behaviors from `static` to `observed` where a project opts in.

**How to pick it up.** Model it as a **coverage adapter**, parallel to runner adapters and
keyed by framework and level. Start with a focused spike confirming Turbopack + Next 16
source-map fidelity. Istanbul / `babel-plugin-istanbul` is a **dead end on App Router** (it
breaks Server Actions) — do not pursue it.

**Research.** [Why Istanbul fails on App Router](https://dev.to/stevez/why-istanbul-coverage-doesnt-work-with-nextjs-app-router-9ip)
· [nextcov](https://github.com/stevez/nextcov)
· [next.js Discussion #28606](https://github.com/vercel/next.js/discussions/28606)
· [Playwright coverage example](https://dev.to/anishkny/code-coverage-for-a-nextjs-app-using-playwright-tests-18n7)

### Tracing adapter — consume the app's existing observability

**What.** For apps that *already* emit structured logs or OpenTelemetry traces, derive
observed `exercises` edges by reading the trace for a test request to see which components
handled it. Zero instrumentation added by us.

**Why deferred.** App-specific: it depends on the app's tracing or log format, and span→file
mapping is coarse. This is the salvaged core of the "just add logging" idea — *generic*
logging-as-coverage is build instrumentation in disguise and hits the same bundling and
worker wall, so only the "consume existing traces" form is worth building.

**How to pick it up.** Another **coverage adapter** variant, opt-in for instrumented apps.

### P4c — the remaining runner adapters

> **Partly picked up, 2026-08-21.** The `pytest` half — which is the half that adds Python as a
> second language — lands in the same batch as this edit: `fingerprint_behavior` now routes
> `level: unit` with `adapter: pytest` or `unittest` to a real execution path
> (`skills/freya-behavior-runner/scripts/run_behaviors.py`, `PYTEST_ADAPTERS`). It was pulled
> forward because the brownfield scan wrote 149 `unittest` behaviors for this repository and
> there was nothing that could run one. The rest of the item stands as written: `jest` is still
> unbuilt, and the if-ladder is still an if-ladder.

**What.** Only the **vitest** unit runner was implemented (V8 →
`coverage-final.json` → observed fingerprint). `KNOWN_ADAPTERS`
(`skills/freya-spec-manager/scripts/frontmatter.py:94-100`) allow-lists eleven runner
adapters — cucumber, behave, pytest-bdd, jest, vitest, mocha, jasmine, playwright, cypress,
pytest, unittest — plus `manual` (human-verified, no runner), but everything except
vitest-unit fell through to `level-deferred` in `fingerprint_behavior()`
(`skills/freya-behavior-runner/scripts/run_behaviors.py`): unknown coverage, never run.
Integration is static via code-graph and therefore adapter-agnostic; authoring already handles
all of them (Gherkin scaffold plus native link).

**Why deferred.** Deprioritized deliberately: the development testbed uses vitest and TS, so
building jest or pytest support served nothing that existed. Phase 4 is "done enough" for the
TS case.

**How to pick it up.** `jest` is **near-free** — it emits the same Istanbul
`coverage-final.json` that vitest's parser already reads, so it needs only a new argv builder.
`pytest` is the interesting one: it adds **Python as a second language** (coverage.py
`--cov-report=json` → a small new parser). Both are unit-level and stdlib-parseable.
**Observed e2e (playwright/cypress) is not P4c** — it needs the V8+CDP coverage adapter above.
When picked up, replace the hardcoded `(state, level, adapter)` if-ladder in
`fingerprint_behavior` (`skills/freya-behavior-runner/scripts/run_behaviors.py`) with a small
**runner-adapter registry** (per adapter: argv builder, coverage parser,
observed-confidence), porting vitest onto it behavior-preservingly. The pytest adapter added a
third branch to that ladder rather than starting the registry, which is the cost the note above
bought its schedule with.

**Note the altitude.** The runner side is *not* the polyglot blocker — code-graph is. Doing
P4c does not unblock Track B, and Track B may change what an adapter should look like.

### Brownfield over a vendor substrate: ownership-boundary scoping

**What.** Support the third brownfield shape: a project where you own only a thin custom
layer (custom auth trees, nodes, scripts) sitting on a large vendor codebase you must not
touch and did not write. Canonical case: Ping / ForgeRock on-prem. Distinct from the two
shapes already exercised — greenfield where you own all of it, and brownfield where you own
all of it. The new requirement is a first-class **ownership boundary**.

**Why deferred, and why it matters.** `scan` walks *feature areas* and has no notion of "mine
versus the platform" — there is no owned-paths configuration anywhere in `skills/` or `bin/`
today. A full-repo scan of a codebase we own produced ~383 candidates; pointed at a ForgeRock
checkout the same walk produces **tens of thousands of vendor-code candidates**, burying the
few dozen that matter. Without scoping the vendor-substrate case is not suboptimal, it is
unusable. Deferred because it is its own track — config surface, code-graph boundary
semantics, and a config-as-code question — and the adoption/intent-lifecycle work was the
right place to stop.

**Design sketch for pickup.**
1. **Owned-paths config (load-bearing).** A small include/exclude glob config that **both
   `scan` and `code-graph` respect**: only owned paths get behaviors inferred, scaffolds
   written, or wrap-up gating. Everything else is frozen.
2. **Vendor code is a boundary, not invisible.** code-graph still resolves edges *into* the
   platform (a custom node calling a vendor API) for impact analysis, but never descends into
   or claims ownership of vendor files. They are leaf/boundary nodes: referenced by
   `exercises`, never specced, never scaffolded, never blocking.
3. **The seam is where the layer earns its keep.** Custom trees encode intent the vendor docs
   never capture, and that breaks *silently* on a platform upgrade. Pinned as `accepted`
   behaviors, a vendor version bump becomes a regression signal — the blast-radius direction
   generalizes from "code change → affected behaviors" to "**dependency/platform bump →
   affected seam behaviors light up**". Probably the strongest single adoption story the
   behavior layer has.
4. **Stretch: config-as-code.** Vendor trees are often JSON or config, not source, so a
   behavior may need to `exercise` a config file rather than a `.ts`. The locator/exercises
   model assumes source files today. This overlaps directly with Track B gap 2 — settle it
   there.

### Audit every fan-out flow, and revisit the generated-doc set

**What.** Several skills orchestrate a coordinator plus parallel workers: docs-manager spawns
twelve documentation workers (`skills/freya-docs-manager/SKILL.md:87-98`), the security scan
fans out over six categories, `spec-manager scan` over five discovery areas. Audit all of
them. Specifically for docs-manager, review **which documents we generate at all** — is
PROJECT_OVERVIEW / ARCHITECTURE / DATABASE / API / … the right set, and should it vary by
project type and stack?

**Why it was deferred, and why it is due now.** It sat downstream of portability, which was
reshaping *how* these flows are expressed. Portability shipped as 0.2.0 on 2026-08-18, so the
gate is open — and portability sharpened the item rather than closing it. Phase 7 instrumented
a docs-manager run on Copilot and counted **zero `task` and zero `explore` invocations across
a documented twelve-way fan-out**; the fan-out was executed by the main loop and *described*
as parallel. That is documented host policy, not a bug, and it is the right place to start
the audit.

**How to pick it up.** Enumerate every coordinator/worker flow and ask of each whether the
fan-out is buying anything on the hosts we actually run on. Then revisit the generated-doc set
against arbitrary stacks — which is the same work as the framework-agnosticism sweep in Track
B direction update #3, so sequence them together.

### P4d — calibrated model enforcement (evidence-gated)

**What.** Promoting *fingerprint-driven* governance checks (e.g. "you changed exercised code
without touching intent") from advisory to a hard block.

**Why deferred.** It is gated on evidence, not on effort. The false-positive rate measured on
the testbed was **0** — but on **2 behaviors across 3 changes**. That validates the mechanism;
it says nothing about trustworthiness at scale, and it is not a benchmark. Until the FP rate is
measured on a substantially larger suite, fingerprint-driven governance stays advisory.

**Already safe and shipped, do not confuse the two.** Deterministic blocking — wrap-up blocking
on a real `test-failed` of an *affected, executed* behavior — is a genuine test failure, not a
fingerprint inference, and it already gates.

**How to pick it up.** Get the measurement first: a project with enough accepted behaviors that
an FP rate means something, then re-run the same selectivity experiment before touching any
gating code.

### Minor: trim per-input-branch behavior candidates

**What.** Validation-heavy routes emit one candidate behavior per field-length check, which was
the main volume driver in the ~383-candidate full-repo scan.

**Why deferred.** Not blocking — the architecture never reviews the pile eagerly, so volume
costs tokens rather than attention.

**How to pick it up.** If review ergonomics are ever dogfooded properly (distinct from the
inventory measurement already done), collapse per-field-validation behaviors into one
"validates the payload" behavior per route.

---

### Materialise the governance graph

**What.** `SPEC → BEHAVIOR → TEST → CODE` is a four-hop typed chain, and there is more around
it: `ADR supersedes ADR`, `INTENT → BEHAVIOR`, `finding → behavior_ref → BEHAVIOR`, and the
`principle > ADR > spec` authority order. That is a graph. It is not stored as one — the links
live denormalised in frontmatter and in `behavior.json`, and `verify_links.py`,
`contradictions.py`, `drift.py` and the security cross-reference each re-read the files and
walk it themselves.

**Why deferred.** Nothing is broken. The links are already navigable, deterministic and small,
and every consumer gets a correct answer today. Materialising them means adding **another
derived cache to keep in sync**, which is the failure mode ADR-017 and the 2026-08-19 docs
restructure were both cleaning up after. A cache that can go stale is worse than a walk that
is merely slower, until the walk actually hurts.

**Trigger to revisit.** Traversal becomes slow enough to notice, or a query needs multi-hop
closure that is genuinely painful to compute by re-reading — for example "which specs' intent
transitively covers this file", which today has no single caller that can answer it.

**How to pick it up.** Through the substrate contract, like everything else — a governance
graph is a fourth producer with its own artifact, its own confidence model and its own refresh
cadence, joined on the same keys. Do not fold it into `graph.json`. Surfaced during the Track B
brainstorm, 2026-08-19.

---

## Open defects

Items 1–8 were re-verified against shipped code on 2026-08-19. Items 9–11 were found the same
day: 9 and 10 by the Track B Phase 0 spike, 11 by the review of the repair it prompted. Items
15–18 came out of running the toolkit on itself on 2026-08-21.

**Fixed, and struck rather than deleted so the reasoning survives:** 7, 9, and 15 (by 18).

### 1. A `--copy` install is re-copied on every `update`, even when nothing changed

`bin/updater.py:501`–`:506` queues every non-symlink `ok` entry for refresh unconditionally — no
content comparison and no HEAD comparison. It cannot do better with what it has: the install
marker written at `bin/installer.py:422` contains only `str(source)`, the source path, with no
commit stamp. Correct by design in the sense that a copy tracks nothing, but `--copy` is the
*normal* mode on Windows, so every update there rewrites all ten skills, and each rewrite is a
brief window in which a skill is absent. Fix: stamp the store's HEAD into the marker and
compare, or compare content.

### 2. `uninstall` is missing from the conformance checker's `BUILTIN_COMMANDS`

`bin/check_skill_conformance.py:20` lists only `install`, `update`, `doctor`, `init`, `help`.
`bin/freya_cli.py:26-27` also ships `uninstall`, and `bin/commands.json` does not list it
either (it holds only manifest subcommands). The allowed set is built from the union of both at
`check_skill_conformance.py:488`, so the first SKILL.md to write `freya uninstall` in a code
span trips rule **R3** ("unknown freya command") at `:394`. That is a trap, not a rule — a
documented, working command fails the gate.

### 3. `mitigated` is an unreachable disposition

`skills/freya-codebase-security-scan/SKILL.md:624` maps `mitigated` → MITIGATED in its
disposition table, and `:588` lists it among the valid values. `disposition()` in
`skills/freya-codebase-security-scan/scripts/audit_engine.py:364`–`:411` only ever returns
`intentional-design`, `needs-review`, `confirmed`, or `drop`. Neither the original JS engine
nor the Python port ever emitted `mitigated`. Either wire it up or remove it from the table and
the value list.

Re-checked 2026-08-24, and there is now a second reason to settle it. `findings.json`'s
`status` vocabulary (`skills/freya-codebase-security-scan/references/findings-schema.md:32`–`:37`)
is `open` / `resolved` / `intentional` — three values, none of them `mitigated` — and since
SEC-007 a fourth value is not silently ignored: `collect_status.security_bucket` names it in a
note (`skills/freya-status/scripts/collect_status.py:214`) and still counts it as **open**
(`:217`). So the two vocabularies are not the same list and cannot be made one by adding a
value to either. The
post-0.3.0 security pass hit this directly: SEC-006 is mitigated and not closed, and had to be left `open`
in the index because there is no state that says so. Whichever way `mitigated` goes in the
disposition table, say in the schema what a mitigated-but-not-closed finding is spelled as.

### 4. `status` and `review` are advertised but undefined (security-resolver)

`skills/freya-codebase-security-resolver/SKILL.md:34-35` lists `status` ("Quick count by
severity + last scan date") and `review` ("Show what was fixed in last session") in its Quick
Reference. The Commands section (`:86` onward) defines only the default interactive flow,
`list` (`:567`), `fix <ids...>` (`:605`, including the `--critical` / `--high` shortcuts) and
`fix --dry-run` (`:634`). Neither advertised command has a phase, an example, or any statement
of where it reads prior-session state from — git log, a diff between dated reports, something
else — so an agent invoked with `review` has to improvise. The consolidated explainer does not
preserve the gap either — `knowledge-base/explanations/using.html` (the `codebase-security-resolver`
entry) and `knowledge-base/explanations/reference.html` describe the skill without listing its command
surface at all, and the `knowledge-base/reference/SKILL_REFERENCE.md#codebase-security-resolver` they link out to
has no command table either, so neither the four defined commands nor the two undefined ones
are visible anywhere. Pick one: specify both
with a phase and an example, or remove them from the table.

### 5. Repairing a copy install with `--force` silently converts it to symlinks

`install.sh --force` without `--copy` replaces copy directories with links. That is what the
flags ask for, but the orphan remedy that sends users there —
`bin/freya_cli.py:427-431`, "the checkout moved; re-run `freya install --force`" at `:430` —
carries no mode warning, so a Windows user repairing an orphaned install flips modes without
noticing.
`doctor` reports the mode, which makes it discoverable *after* the fact; a clause in the remedy
would make it discoverable before.

### 6. Two `doctor` lines read oddly together

A moved checkout produces `agents: the suite is not installed for any agent`
(`bin/freya_cli.py:411`) beside `orphaned entries: 20 …` (`:453`). Each line is accurate —
no entry points at *this* store — but the pair invites the reading "nothing is installed, and
also twenty things are". The orphan line carries the remedy, so this is wording, not behaviour.

### ~~7. `behavior.json` is git-ignored by a rule written for its neighbours~~ — RESOLVED (2026-08-19)

**Fixed.** `.graph/.gitignore` now names `graph.json` and `classifications.json` instead of
using a blanket `*`, so `behavior.json` is committed. Its `exercises` are sorted by path at
write time, because the static edges come from code-graph's unordered import closure and an
unsorted file would have produced a spurious diff on every rebuild. Both writers upgrade a
legacy `*` in place, so already-onboarded projects pick the change up on their next build
without touching anything; a hand-edited `.gitignore` is left alone.

Reasoning, the rejected alternatives, and the revisit triggers are in
[ADR-017](decisions/ADR-017-behavior-json-is-committed.md). The `.graph/`-wipe risk that
argued for moving the file out turned out not to exist in shipped code, so it stayed put.

### 8. Redacted content is still reachable in `main`'s history

Two commits removed sensitive content from the design records — `05ff480` (a client/project
name) and `2c3b512` (a private email address used in `git -c user.email=…` command examples).
**Neither is an ancestor of `main`.** The portability branch was squash-merged as `51bdadb`,
whose sole parent is `bd6bdfb`, so main's own earlier history still holds the pre-redaction
blobs:

- `bd6bdfb:docs/design/behavior-layer/parking-lot.md` is `ed587af`, the exact blob `05ff480`
  replaced with `903d62a`.
- `bd6bdfb:docs/design/behavior-layer/02b-phase-2-plan.md` is `a79fe56`, the exact blob
  `2c3b512` replaced with `dd41ade`.

`bd6bdfb` is a direct ancestor of the `origin/main` tip, not an unreferenced object, so every
default clone of the public repo fetches it. Verify with `git merge-base --is-ancestor 05ff480
main` (exit 1) and `git cat-file -p bd6bdfb:docs/design/behavior-layer/02b-phase-2-plan.md`.

The working tree is clean; the history is not, and the repo is public. Deleting the files in a
later commit does not help, and the "decide before merging" window closed when `51bdadb`
landed. The only remedies left are a history rewrite plus force-push — which breaks every
existing clone and every `freya update` consumer tracking the branch — or a deliberate decision
to accept the exposure. Decide it explicitly rather than by default.

**Do not restate the address or the client name here or anywhere else in the repo;** the commit
and blob references above are enough to act on, and writing the values into a live file would
re-create the leak this entry exists to track.

---

### ~~9. The code-graph resolver cannot graph this repo, and reports success doing it~~ — RESOLVED (2026-08-19)

**Fixed.** Found by the Track B Phase 0 spike
(the Phase 0 spike, in git history at `2762d54:docs/polyglot/phases/phase_0/findings.md`)
and repaired before the substrate was frozen behind the contract — see
[ADR-005](decisions/ADR-005-repair-parsing-substrate-in-place.md) and
[ADR-018](decisions/ADR-018-substrate-contract-for-the-code-graph.md). freya-devkit went from **10 of 50 files and 0 internal edges**
— reported as success, exit 0 — to **50 files and 55 edges, 0 dangling**, and
`project_shape.classify()` now reads it as *brownfield* instead of *greenfield*.

Six defects, all in `skills/freya-code-graph/scripts/graph_ops.py`:

| # | Defect | Fix |
|---|---|---|
| a | `'scripts'`, `'docs'`, `'examples'`, `'generated'` in `always_exclude_dirs`, matched against *any* path component | `scripts` dropped entirely; the rest moved to a new `top_level_exclude_dirs` matched only at the repo root |
| b | Bare-specifier and dotted Python imports classified third-party | `_resolve_python_import` / `_python_search_bases` implement module semantics, including src-layout |
| c | `import type { X } from '...'` invisible to the regex | optional `(?:type\s+)?` on the three forms that accept it |
| d | gitignore patterns substring-matched, so `.next` excluded `[...nextauth]` | one shared `gitignore_excludes()`, matching per path component |
| e | `_resolve_fs` accepted a directory, so barrel imports resolved to the folder | `is_file()` instead of `exists()` |
| f | A rule change never reached an already-graphed project | `RULES_VERSION` discards cached `rule`/`gitignore` verdicts; `user`/`ai` ones survive |

(d) existed in **two** places with different semantics — `_should_exclude` and
`_classify_with_rules` — which is why the first attempt fixed only one of them. They now share
one function.

**Measured, on packages neither side was written against.** Rebuilding six real libraries
(jinja2, requests, urllib3, yaml, rich, click — 190 files) with the old and new resolver:
**+693 internal edges, 31 dangling junk edges removed, 0 real edges lost.** On the testbed,
232 files/609 edges → 234/627, and graphify's edge advantage narrowed from 18 to 1.

Deferred, and filed separately below: the Python import regex still misses
`from . import x`, drops all but the first name in `import a, b`, and cannot see indented
imports.

### 10. The import regexes read strings and comments, and miss three Python forms

Surfaced while fixing item 9. `_parse_imports` runs regexes over raw file text with no
awareness of strings or comments, and the Python patterns do not cover every statement shape.

| Symptom | Evidence |
|---|---|
| An import inside a string literal becomes an edge | `bin/installer.py:566` writes `"from freya_cli import main\n"` into a generated launcher; the graph records installer → freya_cli |
| An import in a comment or docstring becomes an edge | `graph_ops.py`'s own docstrings contribute every `unresolved:` entry in this repo's graph |
| `from . import x` / `from .. import y` are missed | the module name is in the import clause, which no pattern captures. **1,948** occurrences across **91,780** import lines in site-packages (22,042 files); **0 in this repo** |
| `import a, b` keeps only `a` | **21** per 91,780 |
| Indented imports are invisible | `^import` under `re.MULTILINE`, so lazy and `try:`-guarded imports. **1,957** per 91,780 |

Counted directly over site-packages on 2026-08-19; re-run the loop in the commit message for
this entry to reproduce. The two larger figures are the ones worth acting on.

All four need the same work — capture the import *clause*, not just the module path, and skip
strings and comments — so they are one item rather than four.

**Why deferred rather than fixed.** Doing it properly means parsing rather than matching, which
is an argument for the graphify backend (Track B Phase 2) rather than for more regex. The
phantom-edge direction is also the safe one: a spurious edge runs a test that was not needed,
where a missing one hides a regression. Worth revisiting only if the substrate contract keeps
the homegrown backend as more than a floor.

The case-insensitive-filesystem case named here originally is **fixed** — `_is_real_file`
compares against the on-disk name, so `import Foo` beside `foo.py` no longer emits a dangling
key. A symlinked directory inside the project still yields a lexical key; narrow enough to
leave.

### 11. Classification cache hardening

Four small defects in `classifications.json` handling, found by the read-only review of the
Phase 1 resolver work (2026-08-19). None changes graph output today; all are about persisted
state being wrong or unreachable.

| # | Defect | Why it is deferred |
|---|---|---|
| a | The `RULES_VERSION` discard keeps everything except `rule`/`gitignore`, but the commonest label in a non-TTY run is `auto-source-default`, which is not a judgement either. Those entries survive every future rules bump | Cache-only. The label is hardcoded `type: source` and `_should_exclude` re-applies the rules per file, so an upgraded graph is byte-identical to a fresh clone's — verified. Costs a wrong console count and a wasted glob. Fix by inverting the test to keep only `user` and `ai` |
| b | `_load_classifications` catches a `json.load` failure but not valid-JSON-that-is-not-an-object. A file containing `[]` raises `AttributeError` | Not a regression — the previous code crashed on the same input one frame later — and nothing in the toolkit can write a non-dict there, so it needs hand-corruption of a gitignored cache |
| c | `_save_classifications` truncates in place rather than writing to a temp file and renaming | Same blast radius as (b): an interrupted write leaves invalid JSON, which *is* caught, so the cache resets rather than corrupting |
| d | `--clear` unlinks `graph.json` but leaves `classifications.json` | Arguably correct — classifications include user judgements that a cache clear should not discard — but it is undocumented, and it is why a rules change needed `RULES_VERSION` in the first place |

Do (a) and (b) together; they are both in `_load_classifications` and about ten lines total.

**Adjacent, and the only path here that can shrink a graph.** With `non_interactive=False` and
no stdin, `_ask_user_classification` swallows `EOFError` and persists
`{'type': 'exclude', 'source': 'user'}` — a machine-forced verdict wearing a human's label,
which then survives every rules bump by design. Worth a look whenever (a) is done, since
inverting the discard set makes `user` strictly more powerful.

Re-checked against ADR-022 (2026-08-20), which made a `user` verdict outrank every built-in
exclusion: **this path did not get worse.** The EOF branch can only ever produce `exclude`, and
an `exclude` verdict was already honoured unconditionally. It cannot fabricate the powerful
direction. Still wrong to label a timeout as a person's decision.

### 12. Multi-repo projects are one repo at a time

Raised 2026-08-19 while scoping Track B; deferred by the user on the spot. Recorded so it is
not rediscovered.

A `CodeGraph` is constructed with one `project_dir` and every path in the artifact is relative
to it. A system split across several repositories — a mobile app, an API, and a shared contracts
repo — therefore gets one graph per repo and no edge between them, which is exactly the
relationship anyone asking for blast radius wants. It is the same shape as the monorepo problem the floor already solves for npm workspaces (`graph_ops.py`, `_workspace_globs`)
(`apps/mobile` → `packages/domain`) with the packages behind a repository boundary instead of a
directory one.

Not obviously the same fix. The workspace resolver could read those manifests because they were in the
tree; across repos there is no single tree, the sibling may not be checked out, and the two
sides can be at different commits — so a naive resolution would emit edges into a version of a
file nobody has. The honest floor is probably to resolve to `external:` as today but *say* it is
a known sibling rather than a third-party package, the way `unresolved:` distinguishes a real
gap from an absence.

Blocked on nothing but a decision. Worth revisiting once Phase 2 has settled what a backend is
allowed to see outside its own root.

**Update 2026-08-24 — the blocking question is answered, and the "honest floor" above shipped.**
ADR-031 settled what a build may see outside its root: nothing, unless the project declared it
in `knowledge-base/settings.json` under `outside`, and then only enough to *resolve* a
reference in-project code already wrote. An import landing under a declared root becomes the
edge target `outside:<alias>/<rel>` (`skills/freya-code-graph/scripts/substrate.py:79`), which
is exactly the "say it is a known sibling rather than a third-party package" this item asked
for — `is_internal` is false for it (`skills/freya-code-graph/scripts/substrate.py:102`), so it
distinguishes itself from `external:` without pretending to be a node.

What is **not** done, and is what remains of this item: there is still one graph per repository
and no edge *between* them. A declaration produces no reverse edge, no node and no blast radius
on the far side — `link_dependents` builds nothing for an `outside:` target and `validate_graph`
demands no node for it — and the sibling still has to be checked out for the reference to
resolve at all, at whatever commit it happens to be on. The two problems this item named as
unsolved (no single tree, two sides at different commits) are untouched. So: the labelling half
is shipped, the traversal half is still a decision nobody has made.

### 13. Per-edge provenance is recorded and enforced by nothing

Found 2026-08-20 by the closing review of Track B.

Every edge carries `provenance: extracted | inferred`. Spec §4 and §11, ADR-021 and the explainer
all state — in the present tense — that only `extracted` edges may gate `wrap-up` and that
`inferred` ones are advisory. **No production code reads the field.** An inferred edge reaches
blast radius indistinguishable from an extracted one.

The exposure today is small: over-approximating a blast radius is the safe direction, and
**one** file pair on this repository rests solely on an inferred link —
`audit_engine.py` → `substrate.py`. Of 120 edges, 12 are inferred; the other 11 pairs carrying
an inferred edge also carry an extracted one, so dropping the inferred half would not
disconnect them. The discrepancy is not small.

> Re-measured 2026-08-21 on `test/dogfood-polyglot` with the graphify backend. This entry
> previously said *two* pairs, "both duck-typed calls through an interface", which disagreed
> with ADR-021's *one* in both directions. ADR-021 was right. Reproduce with:
> `python3 -c "import json,collections; g=json.load(open('knowledge-base/.graph/graph.json')); p=collections.defaultdict(set); [p[(f,e['to'])].add(e.get('provenance')) for f,i in g['files'].items() for e in (i.get('imports') or []) if isinstance(e,dict) and e.get('to')]; print([k for k,v in p.items() if v=={'inferred'}])"` This is the third time a guard in this
toolkit has been written, documented as having an effect, and left unwired — `validate_graph`
had zero callers, `set_classification` was accepted and ignored, and now this.

Two honest resolutions, and picking between them needs a measurement rather than an argument:
implement the filter at the point blast radius is consumed, or strike the promise and let the
field stay descriptive. Measure the mis-wiring rate on a real polyglot repository first; ADR-021's
own revisit condition says exactly that.

### 14. The coverage block cannot say "I do not emit this field"

Found 2026-08-20, same review.

`Coverage` declares languages, extensions and relation kinds. It has no vocabulary for a field
a backend simply does not produce, and there are two:

- **`exports`** — the graphify backend never populates it, so switching backends silently empties
  the field for every file. Spec §7's table claims it is retained.
- **`external:` edges** — graphify emits no node for a third-party import in TS/JS/Python, so
  there is nothing to project. It reads package dependencies from manifests instead. Phase 0
  measured this and judged it acceptable because `external:` exists in freya only to be filtered
  out; that judgement stands, but it is recorded nowhere a caller can read.

Both are upstream limitations rather than projection defects. The gap is that a caller cannot
discover either from the artifact — which is the same class of problem the coverage block was
added to solve for languages. Documented in `references/graph-schema.md` in the meantime.

Becomes real the moment anything depends on `exports`. Nothing does today.

### ~~15. `coverage gaps` counts files no behavior could ever cover~~ — RESOLVED (2026-08-21)

**Fixed by 18 below**, which re-measured the same census after the spec corpus landed and
implemented the `coverable` predicate this entry asked for. The original text is kept because
the two measurements reconcile exactly and 18 shows the arithmetic.

Found 2026-08-21, running `freya status` on freya-devkit itself.

`behavior_graph.gaps()` subtracted covered files from *every* file in the code graph
(`skills/freya-behavior-graph/scripts/behavior_graph.py`, `gaps`), so the headline number in
`freya status` and in the generated `BACKLOG.md` included test files and shell scripts. A
behavior's `exercises` names production code; a `test_*.py` will never appear there, so every
one of them is a permanent, unactionable entry.

Measured on this repo: **65 reported, 32 actually behavior-coverable** — 30 test files and 3
shell scripts (`bin/freya`, `install.sh`, `install.ps1`) make up the other 51%. A number that
is half noise trains people to ignore it, which is the same failure mode as a check that cries
wolf.

Deferred at the time because the fix looked like a semantic choice rather than a bug fix:
excluding by filename convention is the kind of built-in judgement ADR-022 says should be a
project-overridable default rather than a hardcoded name list. 18 settles that by keeping the
predicate off directory names entirely — every rule it applies is a claim about a *file*, which
is the half ADR-022 never contested.

### 16. `graphify` on this repo: +6 real edges, -389 `external:` edges

Found 2026-08-21, measuring the backend swap before committing
`knowledge-base/settings.json`.

Not a defect — a measurement worth keeping, because it is the first head-to-head on a repo
anyone can re-run. Both graphs are in `knowledge-base/.graph/` as `graph.homegrown.json` and
`graph.graphify.json` (ADR-028), so the diff below reproduces.

| | homegrown | graphify |
|---|---|---|
| files | 62 | 65 |
| raw edges | 465 | 120 |
| internal edges | 76 | 78 |
| edge kinds | `imports` | `imports`, `calls`, `references` |
| provenance | all `extracted` | 108 `extracted`, 12 `inferred` |

The raw-edge collapse is entirely `external:` nodes, which graphify does not emit — defect 14
above. On internal edges graphify is strictly better here:

- **+6 real cross-skill dependencies homegrown missed**, all of them `sys.path`-style imports
  between skills (`behavior_graph.py` → `run_behaviors.py` and → `frontmatter.py`,
  `run_behaviors.py` → `adapters.py` and → `frontmatter.py`, `audit_engine.py` → `substrate.py`,
  `collect_status.py` → `frontmatter.py`), plus `bin/freya` → `bin/freya_cli.py`, which
  homegrown cannot see at all because it does not read shell.
- **-1 false positive**: homegrown reported `bin/installer.py` → `bin/freya_cli.py` from the
  string literal `"from freya_cli import main\n"` at `bin/installer.py:566` — the content of a
  shim it *writes*, not an import it makes. Defect 10 above, caught in the wild.
- **-4 `unresolved:` placeholders** invented from fixture strings inside `graph_ops.py` and
  `test_graph_ops.py`.

Worth re-running on a polyglot repo. On this one the honest summary is that graphify's 40
languages buy almost nothing — it is a Python repo — and what it actually bought was correct
resolution of imports that cross a `sys.path` boundary.

### 17. `freya security scan` persists nothing

Found 2026-08-21, running the scan on this repository.

The driver has **no write path**. `grep -n "open(" skills/freya-codebase-security-scan/scripts/*.py
| grep -v test_` returns exactly one hit, and it is a read — re-measured 2026-08-24, still one
(`skills/freya-codebase-security-scan/scripts/audit_engine.py:254`). *(The `| grep -v test_` is
new: the post-0.3.0 security pass added test files that make the recipe as first written return
eight, none of them a driver write.)* 73 agent calls produced 22 verified findings, and the
only durable record was the shell redirect the caller happened to add. Without `> file` the
whole run is lost when the terminal scrolls.

This is not a bug in the sense of a wrong answer — SKILL.md is explicit that the *skill* writes
`knowledge-base/security/codebase-security/YYYY-MM-DD.md` and `findings.json`, and the driver
only discovers and verifies. But the split means the expensive half is the durable-less half,
and `--format summary` — the obvious thing to run — discards the evidence and remediation that
the report needs, keeping only a one-line title per finding. Reconstructing them cost a second
pass over the code.

Two candidate fixes, and they are not exclusive:
- Have the driver write its own raw JSONL beside the report directory before returning, purely
  as a crash log. Cheap, and it makes the split survivable.
- Make `--format summary` a view over a structure that is always emitted, rather than the only
  thing produced.

Related: the cost line printed at the end (`$72.60` on this run) is the agent CLI's own
Anthropic-priced estimate. With `ANTHROPIC_BASE_URL` pointing elsewhere it does not describe
what the operator was actually charged, and nothing says so.

### ~~18. The coverage-gap census was inflated 2.4×, and `BACKLOG.md` handed the user the wrong number~~ — RESOLVED (2026-08-21)

**Fixed.** Found by re-running `freya status` on this repository after the brownfield scan wrote
149 behaviors, and closed in the same batch. This is item 15 above, measured a second time and
acted on.

`behavior_graph.gaps()` subtracted covered files from every file in the code graph, so the
headline counted files that no `exercises` list can ever name. Measured here:

| | files |
|---|---:|
| reported by `behavior-graph --gaps`, before the fix | 57 |
| `test_*.py` | 29 |
| `conftest.py` | 1 |
| addressable by no import statement: `install.sh`, `install.ps1`, and the extensionless `bin/freya` | 3 |
| **real, actionable gaps** | **24** |

Reproduce from the committed artifacts alone:

```bash
python3 -c "import json,glob,re,os; g=json.load(open('knowledge-base/.graph/graph.json'))['files']; e={m.group(1) for p in glob.glob('knowledge-base/specs/**/*.md',recursive=True) for m in re.finditer(r'^\s*entry:\s*(\S+)\s*$',open(p).read(),re.M)}; u=[f for f in g if f not in e]; print(len(u), len([f for f in u if os.path.basename(f).startswith('test_')]), len([f for f in u if not f.endswith('.py')]))"
# → 57 29 3
```

**The number reached the user.** `knowledge-base/BACKLOG.md` is git-tracked and regenerated by
`freya status --write-backlog`, so 57 was printed twice in the report the toolkit hands its
operator — once in the census line (`collect_status.py:310`) and again as the coverage-gap
section header (`collect_status.py:347`) — with 33 of the 57 permanently unactionable. That is
exactly the cry-wolf failure item 15 named, now with the arithmetic. The committed
`BACKLOG.md` still carries 57 until the next regeneration, which is wrap-up Phase 5's job
(`skills/freya-wrap-up/SKILL.md:467`).

**The fix** is a `_is_coverable` predicate applied by `gaps` in
`skills/freya-behavior-graph/scripts/behavior_graph.py`. Three rules, each a claim about what a
*file* is and never about which directory it sits in: anchored test-name conventions
(`test_x.py`, `x_test.go`, `x.spec.tsx`, plus the `conftest.py` basename), no extension at all,
and a recorded language that is invoked rather than imported (`shell`, `powershell`, `batch`).
Deliberately **not** "a `.py` file that is not a test" — the graph is polyglot (ADR-018,
ADR-019), so an extension allow-list would report a confident zero on any TS, Go or C# project,
which ADR-005 rules out. Where a rule is uncertain it under-excludes: a missing exclusion costs
one noisy line, a wrong one hides real uncovered code.

**The two measurements agree, which is why this is one defect and not two.** Item 15 counted 65
files with 33 non-coverable, so 32 coverable; between the two runs the scan declared `entry:` on
28 behaviors naming 8 distinct source files, and those 8 are discharged from the census as
covered. 65 − 8 = 57 reported, 32 − 8 = 24 real. The same 33 files are the noise in both.

**Carried forward, and not fixed here.** `surface`'s `recall_gaps` asks the same question over a
single change and still counts the same file kinds. Its answer is advisory and per-change rather
than a tracked census, so it is noise with a much shorter half-life — but it is the same
predicate's absence, and it is where this will resurface.

## Platform-blocked

Items that need a platform we do not have, or a live agent run we have not paid for. None is
blocked on code.

### Whatever runs live next: commit the evidence, and re-run the escape audit

Two conventions are owed rather than deferred.

**Evidence.** Every number in the phase 6 and phase 7 validation logs is prose transcription;
no raw artifact is committed. That includes the 800 KB debug log behind the delegation finding,
which lived under `/tmp` and is gone. There is nowhere for it to land: the next run that
produces load-bearing numbers should create `knowledge-base/evidence/` and commit, at minimum, the
tool-invocation counts, the quoted host prompt block, and one full driver stderr transcript
per adapter — and cite them by path from the prose. Otherwise "did Copilot's delegation policy change in 1.1.x?" has to be re-derived
from scratch, re-purchasing quota to do it.

**Escape audit.** The phase 6 isolation diff covers Part A only. Every live-agent run since —
including a Copilot session granted `--allow-tool=shell --allow-tool=write`, a window where the
real `~/Library/Keychains` was symlinked into the sandbox, and phase 7's Claude runs against
the real install — happened with nothing watching. Nothing suggests anything escaped; the point
is that no one looked. Re-running the baseline diff after a live session is four `ls -la` calls
and should be the closing step of any future live run.

### Windows, with a live agent

CI has run the suite, the conformance gate and a full `install.ps1` install → launcher →
uninstall on `windows-latest` since 2026-08-18 (`.github/workflows/ci.yml`), which was the
first execution of that code on the platform it exists for. **No live agent run has ever
happened on Windows.** Needs a Windows machine with a coding-agent CLI installed.

### The read-only bypass probe against Copilot CLI 1.0.75

Never run. The read-only guard has held in every observed run, on a fixture and on a real
repository, but nothing has actively tried to defeat it. Needs a deliberate adversarial run
with the driver's allowlist in place.

### `audit`'s multi-round loop-until-dry, on the Claude adapter

Live dry-round termination is demonstrated on **Copilot only** (25 calls, 2 findings, two
consecutive dry rounds). Both Claude runs stopped on `--max-findings` instead: phase 6's 22
calls / 3 findings solve uniquely to two discovery rounds, which cannot contain the two
consecutive dry rounds `K_EMPTY` requires, and phase 7's run 4 hit the cap inside round 1. The
path is pinned by five offline tests; the Claude adapter's round-boundary behaviour has never
been exercised on the wire. Needs a run with the cap set above the fixture's real finding
count.

### Does Copilot delegate at scale?

Copilot's own system prompt forbids delegating a labeled-area fan-out **"when its total scope
is small"** / "small enough to read directly". Every observation to date was on a small
fixture, so what is established is narrow: for scopes small enough to read directly, Copilot
will not delegate, by design. Its policy would permit delegation on a large codebase
("delegate only work that needs separate context"). Untested. Needs a live run against a large
repository, and it would change how much the driver has to own.

### The 60 s fetch timeout path

The unreachable-remote case fails in **0.13 s** — connection refused, not a hang — so the
timeout branch is still unexercised. A genuine hang is needed and no fixture produces one
honestly. Note also that a refused connection is not a hang: the other hang paths are
unexercised for the same reason.

### The `~7×` token-cost figure

Still an estimate. The wall-clock comparison that exists (209.3 s at `--concurrency 1` versus
91.4 s at `--concurrency 6`, so 2.29× and not 6× — the CLI does apply back-pressure) says
nothing about tokens. Needs a run with per-call token accounting on an adapter that reports it.
