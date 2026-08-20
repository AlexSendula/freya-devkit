# Backlog

The single live backlog for freya-devkit. Everything genuinely outstanding lives here: the
next initiative, deferred capabilities, verified open defects, and the items that need a
platform or a live agent run we cannot give them yet.

It replaces the two backlogs that used to sit inside the historical design tree
(`design/notes.md` and `design/behavior-layer/parking-lot.md`). Those were written mid-flight
and accumulated entries that have since shipped. Every item below was re-verified against
shipped code on **2026-08-19**; delivered work was dropped rather than carried. Current
release: **0.2.0** (2026-08-18).

Each item says *what*, *why it was deferred*, and *how to pick it up*. Keep it that way —
an item nobody can act on is noise.

---

## Next initiative — Track B: the polyglot substrate

This is the reason the design tree was cleaned up, and the next real body of work. It is an
initiative, not a ticket; it wants its own vision → brainstorm → spec before any code.

### The wall

`freya-code-graph` is a homegrown, regex-driven import scraper. `FILE_PATTERNS`
(`skills/freya-code-graph/scripts/graph_ops.py:30`) covers TypeScript, JavaScript, Python and
Go; `IMPORT_PATTERNS` (`:50`) matches import statements by regular expression. Real work
projects are **Java + Docker images + Helm charts + Python config + YAML/TOML + `.crt`/`.key`
+ `bin/`**. The graph is blind to all of it. This wall was hit immediately on the first
attempt to use the toolkit on a work laptop.

It is foundational rather than cosmetic: behaviors, drift detection and blast radius all
stand on the graph. **Portability without polyglot means installable but blind on Java.**
0.2.0 made the toolkit run anywhere; it did not make it *see* anything outside the TS/JS
world.

### Two distinct gaps

1. **Real languages need a real parser.** Java (and anything else with a non-trivial module
   system) cannot be served by regex import-scraping. This is a parser problem, not a
   pattern-list problem.
2. **Config-as-code needs a resource graph.** Helm → rendered manifests → images, Dockerfile
   `COPY`, YAML/TOML wiring, certs, keys, `bin/` scripts — these are **reference and
   deployment edges, not import edges**. They may well be a *second graph* alongside the code
   graph rather than more languages inside the same one. Deciding which is part of the work.

### The pivotal fork — decide this first, it gates everything else

The plugin's north star has been **stdlib-only Python, zero-install**. Java parsing,
tree-sitter and graphify all break that. So:

- **Keep zero-install** — homegrown per-language resolvers. Limited and brittle, but no
  dependency and no install story to maintain.
- **Adopt a dependency** — graphify or tree-sitter. Real multi-language support, at the cost
  of the zero-install property.

Vision §10 held graphify in reserve as the heavier off-the-shelf substrate, with a stated
trigger: adopt it if the homegrown resolver keeps accruing edge cases it cannot handle
cleanly. **Java is exactly that named trigger.** The homegrown resolver's known gaps today
are `extends` chains in tsconfig (deliberately not followed —
`graph_ops.py:325-330`), no per-edge confidence, and no monorepo support.

**Recorded lean (2026-07-12, from the user, not final): adopt a dependency — graphify as the
*standard* substrate.** Not a tiered "homegrown by default, graphify opt-in" model; that was
proposed and rejected. The rationale is that one real substrate would tighten the
behavior↔code connection and open the door to **unifying the code graph and the behavior
graph into a single graph**, rather than `behavior.json` sitting as a sibling of
`graph.json`. This supersedes "zero-install is a hard line" — a dependency is acceptable if
it makes the graph better.

**The tension that lean has to resolve.** Vision §6 deliberately keeps `behavior.json` a
*sibling* of `graph.json` precisely so the choice of code substrate stays decoupled from the
behavior layer. Unifying the two graphs runs against that decision — schema, ownership and
degradation behaviour all change. The research must resolve whether unification conflicts
with §6 or subsumes it; do not treat the lean as settled until it has.

### Scope is the whole toolkit, not just the graph

Direction update #3 (2026-07-12) expands this one altitude up: make the **entire toolkit**
framework- and stack-agnostic, so pointing it at a Java service, a Python API, a Go CLI or a
config-as-code repo yields something useful from every skill. The Next/Prisma assumptions are
still baked in, verifiably:

- **docs-manager templates** — `skills/freya-docs-manager/references/templates.md` names
  `NEXTAUTH_SECRET` (`:1131`, `:1157`, `:1166`) and "Next.js pages" (`:547`).
- **stack detection** — `skills/freya-docs-manager/scripts/detect_project.py:128-130` checks
  for `prisma/schema.prisma`.
- **the greenfield/brownfield shape detector** — `project_shape.classify()`
  (`skills/freya-spec-manager/scripts/project_shape.py:66`) calls a repo *greenfield*
  whenever the graph has **0 internal edges**. A Java or Helm repo produces exactly zero
  internal edges today, so a large existing codebase is confidently misread as greenfield.
  The detector inherits the substrate's blindness and converts it into a wrong answer.
- **security-scan heuristics** — Next-flavoured worked examples throughout
  `skills/freya-codebase-security-scan/SKILL.md:638-668`.

### Working record

While Track B is in flight, decisions, reversals and measurements are logged in
[`polyglot/`](polyglot/) — a temporary directory that is distilled into ADRs, these docs and
the explainer site when the feature ships, then deleted.

### How to pick it up

Its own vision/brainstorm, **opening with the substrate decision** — that fork gates the
design of everything after it. Then, in likely order: (a) a language-parser abstraction
inside code-graph, (b) a resource graph for config and deployment edges, (c) the
framework-agnosticism sweep over docs-manager templates, the shape detector and the security
heuristics.

Related and worth reading first: the vendor-substrate ownership-boundary item below. Work
repos are usually *also* brownfield-over-a-platform, and config-as-code was flagged there as
a stretch question before it became a Track B pillar.

---

## Deferred capabilities

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
(`skills/freya-behavior-runner/scripts/run_behaviors.py:212-229`) runs observed coverage only
for `level: unit` + `adapter: vitest`, and returns a static fingerprint for integration. Static
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

**What.** Only the **vitest** unit runner is actually implemented (V8 →
`coverage-final.json` → observed fingerprint). `KNOWN_ADAPTERS`
(`skills/freya-spec-manager/scripts/frontmatter.py:94-100`) allow-lists eleven runner
adapters — cucumber, behave, pytest-bdd, jest, vitest, mocha, jasmine, playwright, cypress,
pytest, unittest — plus `manual` (human-verified, no runner), but everything except
vitest-unit falls through to `level-deferred` in `fingerprint_behavior()`
(`run_behaviors.py:229`): unknown coverage, never run. Integration is
static via code-graph and therefore adapter-agnostic; authoring already handles all of them
(Gherkin scaffold plus native link).

**Why deferred.** Deprioritized deliberately: the development testbed uses vitest and TS, so
building jest or pytest support served nothing that existed. Phase 4 is "done enough" for the
TS case.

**How to pick it up.** `jest` is **near-free** — it emits the same Istanbul
`coverage-final.json` that vitest's parser already reads, so it needs only a new argv builder.
`pytest` is the interesting one: it adds **Python as a second language** (coverage.py
`--cov-report=json` → a small new parser). Both are unit-level and stdlib-parseable.
**Observed e2e (playwright/cypress) is not P4c** — it needs the V8+CDP coverage adapter above.
When picked up, replace the hardcoded `(state, level, adapter)` if-ladder at
`run_behaviors.py:220-229` with a small **runner-adapter registry** (per adapter: argv builder,
coverage parser, observed-confidence), porting vitest onto it behavior-preservingly.

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

Items 1–8 were re-verified against shipped code on 2026-08-19, and 7 and 9 have since been
fixed. Items 9–11 were found the same day: 9 and 10 by the Track B Phase 0 spike, 11 by the
review of the repair it prompted.

### 1. A `--copy` install is re-copied on every `update`, even when nothing changed

`bin/updater.py:371` queues every non-symlink `ok` entry for refresh unconditionally — no
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
`check_skill_conformance.py:371`, so the first SKILL.md to write `freya uninstall` in a code
span trips rule **R3** ("unknown freya command") at `:323`. That is a trap, not a rule — a
documented, working command fails the gate.

### 3. `mitigated` is an unreachable disposition

`skills/freya-codebase-security-scan/SKILL.md:605` maps `mitigated` → MITIGATED in its
disposition table, and `:569` lists it among the valid values. `disposition()` in
`skills/freya-codebase-security-scan/scripts/audit_engine.py:199-246` only ever returns
`intentional-design`, `needs-review`, `confirmed`, or `drop`. Neither the original JS engine
nor the Python port ever emitted `mitigated`. Either wire it up or remove it from the table and
the value list.

### 4. `status` and `review` are advertised but undefined (security-resolver)

`skills/freya-codebase-security-resolver/SKILL.md:34-35` lists `status` ("Quick count by
severity + last scan date") and `review` ("Show what was fixed in last session") in its Quick
Reference. The Commands section (`:86` onward) defines only the default interactive flow,
`list` (`:567`), `fix <ids...>` (`:605`, including the `--critical` / `--high` shortcuts) and
`fix --dry-run` (`:634`). Neither advertised command has a phase, an example, or any statement
of where it reads prior-session state from — git log, a diff between dated reports, something
else — so an agent invoked with `review` has to improvise. The consolidated explainer does not
preserve the gap either — `docs/explanations/using.html` (the `codebase-security-resolver`
entry) and `docs/explanations/reference.html` describe the skill without listing its command
surface at all, and the `docs/skill-reference.md#codebase-security-resolver` they link out to
has no command table either, so neither the four defined commands nor the two undefined ones
are visible anywhere. Pick one: specify both
with a phase and an example, or remove them from the table.

### 5. Repairing a copy install with `--force` silently converts it to symlinks

`install.sh --force` without `--copy` replaces copy directories with links. That is what the
flags ask for, but the orphan remedy that sends users there —
`bin/freya_cli.py:384-390`, "the checkout moved; re-run `freya install --force`" — carries no
mode warning, so a Windows user repairing an orphaned install flips modes without noticing.
`doctor` reports the mode, which makes it discoverable *after* the fact; a clause in the remedy
would make it discoverable before.

### 6. Two `doctor` lines read oddly together

A moved checkout produces `agents: the suite is not installed for any agent`
(`bin/freya_cli.py:370`) beside `orphaned entries: 20 …` (`:386-390`). Each line is accurate —
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
([findings](polyglot/phases/phase_0/findings.md)) and repaired before Phase 1 per
[CD-14](polyglot/decisions.md). freya-devkit went from **10 of 50 files and 0 internal edges**
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

Re-checked against CD-21 (2026-08-20), which made a `user` verdict outrank every built-in
exclusion: **this path did not get worse.** The EOF branch can only ever produce `exclude`, and
an `exclude` verdict was already honoured unconditionally. It cannot fabricate the powerful
direction. Still wrong to label a timeout as a person's decision.

### 12. Multi-repo projects are one repo at a time

Raised 2026-08-19 while scoping Track B; deferred by the user on the spot. Recorded so it is
not rediscovered.

A `CodeGraph` is constructed with one `project_dir` and every path in the artifact is relative
to it. A system split across several repositories — a mobile app, an API, and a shared contracts
repo — therefore gets one graph per repo and no edge between them, which is exactly the
relationship anyone asking for blast radius wants. It is the monorepo problem CD-18 solved
(`apps/mobile` → `packages/domain`) with the packages behind a repository boundary instead of a
directory one.

Not obviously the same fix. CD-18 could read the workspace manifests because they were in the
tree; across repos there is no single tree, the sibling may not be checked out, and the two
sides can be at different commits — so a naive resolution would emit edges into a version of a
file nobody has. The honest floor is probably to resolve to `external:` as today but *say* it is
a known sibling rather than a third-party package, the way `unresolved:` distinguishes a real
gap from an absence.

Blocked on nothing but a decision. Worth revisiting once Phase 2 has settled what a backend is
allowed to see outside its own root.

## Platform-blocked

Items that need a platform we do not have, or a live agent run we have not paid for. None is
blocked on code.

### Whatever runs live next: commit the evidence, and re-run the escape audit

Two conventions are owed rather than deferred.

**Evidence.** Every number in the phase 6 and phase 7 validation logs is prose transcription;
no raw artifact is committed. That includes the 800 KB debug log behind the delegation finding,
which lived under `/tmp` and is gone. There is nowhere for it to land: the next run that
produces load-bearing numbers should create `docs/evidence/` and commit, at minimum, the
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
