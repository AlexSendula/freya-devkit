# Architecture

How skills connect, share data, and work together.

## Skill Dependency Graph

The toolkit is **ten skills across five tiers**. Each tier builds on the ones above it:

```
Tier 1 — Foundation
    code-graph ............ builds knowledge-base/.graph/graph.json (impact / blast radius)
        └─ substrate ...... one contract, two backends — `homegrown` (the stdlib floor)
                            and `graphify` (external, opt-in). The contract persists the
                            graph; a backend only produces it.
        │
        ▼
Tier 2 — Knowledge / Consumers
    docs-manager .......... impact-aware documentation
    spec-manager .......... specs, ADRs, principles, and the behavior lifecycle
    behavior-graph ........ behavior.json (sibling of graph.json); BEHAVIOR → TEST → CODE
        └─ behavior-runner  runs accepted behaviors, captures TEST → CODE coverage
        │
        ▼
Tier 3 — Analysis
    codebase-security-scan .......... blast-radius- and intent-aware findings
    dependency-vulnerability-check .. supply-chain / CVE audit
        │
        ▼
Tier 4 — Orchestration
    wrap-up ... runs code-graph → docs → specs → behavior integrity & run (Phase 3.5) → security, then two commits
    status .... read-only counterpart: outstanding intent / tests / coverage / findings; refreshes BACKLOG.md
        │
        ▼
Tier 5 — Resolution
    codebase-security-resolver ...... fixes findings, documents intentional ones
```

## Skill Tiers

### Tier 1: Foundation

| Skill | Purpose | Used By |
|-------|---------|---------|
| `code-graph` | Dependency graph, impact analysis | All other skills |

#### The graph substrate

`code-graph` is not one resolver. `skills/freya-code-graph/scripts/substrate.py` holds a
contract, and the resolvers are implementations of it. A backend satisfies the contract
structurally — it supplies `name`, `project_dir`, `coverage()`, `available()`, `build()` and
`update()` (`skills/freya-code-graph/scripts/substrate.py:576`) and imports no base class,
because the second backend wraps a tool nobody here controls. The check binds the *call* as
well as the names, against `BUILD_KWARGS` / `UPDATE_KWARGS` (`substrate.py:586`), since a
backend that passes an attribute check can still be uninvokable. See
[ADR-018](../decisions/ADR-018-substrate-contract-for-the-code-graph.md).

Two backends are registered (`skills/freya-code-graph/scripts/backends.py:84`):

| Backend | What it is | Declares |
|---|---|---|
| `homegrown` | The stdlib-only regex resolver the toolkit already had. No install step. | 4 languages, 6 extensions, 2 relation kinds (`imports`, `re_exports`) |
| `graphify` | An external tree-sitter tool, installed with `uv` or pip. | 40 languages, 93 extensions, all five relation kinds |

Those figures are not from either project's documentation. They were read out of the
`substrate.coverage` block of the two artifacts a build in this checkout wrote on 2026-08-21,
`knowledge-base/.graph/graph.homegrown.json` and `graph.graphify.json`.

`homegrown` is the **floor** (`backends.py:26`). It is registered unconditionally and is where
every fallback path lands; if *no* backend reports itself usable, selection refuses outright
rather than continuing, because a stdlib-only backend being unavailable means the installation
is broken (`backends.py:127`). That guard is on the empty set, not on the floor specifically —
if the floor alone is unusable while another backend is not, selection promotes that other
backend (`backends.py:138`, `:166`). `auto` resolves to the floor and does not rank the
installed backends against the repository (`backends.py:166`) — another backend runs because a
person named it, not because a binary appeared on `PATH`. Precedence is project, then machine,
then floor (`skills/freya-code-graph/scripts/settings.py:282`): the project's answer lives in
the committed `knowledge-base/settings.json`, the machine's in `~/.freya/settings.json`,
relocatable with `FREYA_HOME` (`settings.py:59`), which may carry only `substrate.backend` and
`substrate.symbols` (`settings.py:69`). The machine question is asked once, at install or update
time (`bin/backend_setup.py:104`, called from `bin/installer.py:988` and `bin/updater.py:276`),
because that is where a keyboard is — `code-graph` auto-enables non-interactive mode whenever
stdin is not a TTY (`graph_ops.py:3087`), which is every agent-driven run. See
[ADR-019](../decisions/ADR-019-the-floor-and-choosing-a-backend.md).

A named backend that is not installed does not fail the build. It degrades to the floor with a
reason, and the reason goes into the graph's own metadata as `degraded_from`
(`backends.py:139`), not only onto stderr. That field is read rather than decorative:
behavior-runner refuses to compute a static closure from a degraded graph and returns `unknown`
with the reason, instead of a narrower answer that would look authoritative
(`skills/freya-behavior-runner/scripts/run_behaviors.py:316`).

**The contract persists the graph; a backend only produces it.** `build()` and `update()`
return a `substrate.Result` — the graph, and what was done to produce it
(`substrate.py:273`) — and one shared funnel, `_finalise`
(`skills/freya-code-graph/scripts/graph_ops.py:2423`), owns everything after that: it derives
the `dependents` reverse index from scratch on every write (`substrate.py:311`), refuses to
overwrite a populated graph with an empty one (`graph_ops.py:2460`), validates what the backend
emitted (`graph_ops.py:2466`), takes the census described below (`graph_ops.py:2491`), and
writes (`graph_ops.py:2496`). Validation **does not block**: a graph that fails is written
anyway with the errors recorded under `substrate.validation`, and no code in the toolkit
branches on that field. It is a diagnostic for whoever opens the graph later, not a guarantee
that a graph on disk is sound. See
[ADR-020](../decisions/ADR-020-the-contract-persists-the-graph.md).

Every build is written twice — the same payload to `knowledge-base/.graph/graph.json`, the
active artifact every consumer reads, and to `knowledge-base/.graph/graph.<backend>.json`, named
for the backend that produced it (`graph_ops.py:2404`, `:2417`; `substrate.py:264`). Switching
backends therefore leaves the previous one's graph intact at its own path, with the `timestamp`,
`commit` and `substrate` block of the build that produced it still inside. **Nothing in the
toolkit reads the per-backend copy.** There is no `compare` subcommand, and the incremental path
does not warm-start from it either — a graph produced by a different backend forces a full
rebuild (`graph_ops.py:2092`). What this buys is a preserved baseline on disk, not an automated
comparison; the diff is run by hand. `--clear` removes the active graph and every `graph.*.json`
beside it, and deliberately spares `classifications.json`, which holds human and model
judgements a cache clear has no business discarding (`graph_ops.py:2351`). See
[ADR-028](../decisions/ADR-028-graphs-are-stored-per-backend.md).

#### The shape of an edge

An edge in `graph.json` is an object, not a string. Forward it is
`{"to": …, "kind": …, "provenance": …}`; in the reverse index it is the same object keyed
`from`, carrying the forward edge's kind and provenance. `kind` is one of five values fixed by
the contract rather than by each backend (`substrate.py:49`), and `provenance` is one of exactly
two, `extracted` or `inferred` (`substrate.py:61`). The artifact carries `version: 2`
(`substrate.py:77`); readers still accept the bare-string shape, and `upgrade_edges` rewrites it
in memory on load without stamping the version, so a version-1 artifact is rebuilt rather than
papered over (`substrate.py:213`). "Could not be resolved" is a prefix on the edge's *target* —
`unresolved:<raw>`, alongside `external:` (`substrate.py:69`) — never a provenance value.

The node queries stay in paths. `--impact`, `--dependents` and `--dependencies` answer with path
strings, and only `--query` returns edges — the one query whose question is "tell me about this
file". Two of the three consumers do set arithmetic on the answer the moment they get it
(`skills/freya-spec-manager/scripts/drift.py:95`,
`skills/freya-behavior-graph/scripts/behavior_graph.py:267`), where an edge object would raise
`TypeError: unhashable type: 'dict'` in a skill that gains nothing from the extra fields; the
third type-checks it and degrades (`run_behaviors.py:346`).

**Provenance is recorded and read by nothing.** The design was that only `extracted` edges may
gate `wrap-up` and `inferred` ones are advisory; no code implements that filter, so an inferred
edge reaches blast radius indistinguishable from an extracted one. The tier is designed and
unenforced. Counted on this repository's graphify artifact on 2026-08-21, 12 of its 120
file-level edges are `inferred`. Symbol refinement — `from_symbol`, `to_symbol`, `line` — is an
optional addition to the same edge and is off unless a project asks for it
(`settings.py:103`); the graph in this checkout carries none. See
[ADR-021](../decisions/ADR-021-an-edge-is-an-object-with-kind-and-provenance.md) and
[ADR-024](../decisions/ADR-024-symbols-refine-an-anchor-never-replace-it.md).

#### Saying what the backend could not read

The floor reads 6 extensions where `graphify` declares 93, so on most repositories the running
backend is blind to something. That gap used to be invisible from the outside: a file whose
extension the backend does not handle is never enumerated at all, so `files_scanned` reads like
a denominator and is a numerator. Every build or update now runs one pruned walk over the
project and records what it found at `graph["substrate"]["unmapped_source"]` — how many in-scope
source files the running backend cannot read, which extensions they are, and which directories
to search instead (`graph_ops.py:2491`). It is filtered by the build's own scope rule
(`graph_ops.py:1284`), which is wider than the `Exclusions` recorded in the artifact, and by two
tiers of materiality: definite program source is reported unconditionally
(`substrate.py:825`), while scripting and data-definition extensions are reported only when
their count beats both the graphed file count and a floor of 2 (`substrate.py:852`,
`substrate.py:884`), so one build script never fires the caveat and a genuine PowerShell
codebase does.

The block reaches each surface in the shape that surface can carry. `--build` and `--update`
carry it whole, including a prose `advice` sentence and a `readable_by` recommendation;
`--query` and `--impact` carry a structured digest (`substrate.py:1012`); `--dependents` and
`--dependencies` keep their bare arrays and say the same thing on stderr
(`graph_ops.py:2712`), because behavior-runner rejects any `--dependencies` answer that is not a
list of strings and routes the behaviour to `coverage: unknown`
(`run_behaviors.py:346`). In an *answer* the key is **absent**, not empty, when there is nothing
to say (`graph_ops.py:2693`), so a repository the backend reads completely produces the same
output it did before this existed. The artifact is the exception: `_finalise` always writes the
block, so a clean census is recorded there as `{"files": 0}` rather than omitted.

It is never a refusal. Nothing changes an exit code or takes a gate red because of it, and the
rule is written into the code beside the `degraded_from` refusal it must not join
(`run_behaviors.py:317`). One reader does let it change what an answer *says*:
`spec-manager project-shape` reports `unknown` rather than `greenfield` when the census
contradicts an empty graph (`skills/freya-spec-manager/scripts/project_shape.py:243`, `:263`),
still exiting 0. Measured on this repository on 2026-08-21, both backends
published `{"files": 0}`: the census ran and found nothing material to report. See
[ADR-029](../decisions/ADR-029-an-answer-says-what-it-could-not-read.md).

### Tier 2: Knowledge / Consumers

| Skill | Purpose | Dependencies |
|-------|---------|--------------|
| `docs-manager` | Project documentation | code-graph (optional) |
| `spec-manager` | Feature specs, ADRs, principles, behavior lifecycle | code-graph (optional) |
| `behavior-graph` | Behavior graph (`behavior.json`); blast radius both directions | code-graph, behavior-runner |
| `behavior-runner` | Run accepted behaviors, capture coverage fingerprints | code-graph |

These skills maintain structured knowledge about the codebase. `behavior-graph` and `behavior-runner` form the **behavior layer**: intended behavior as first-class, executable records projected into `behavior.json` (a sibling of `graph.json`). They use `code-graph` when available for smarter updates and blast radius.

### Tier 3: Analysis

| Skill | Purpose | Dependencies |
|-------|---------|--------------|
| `codebase-security-scan` | Security auditing | code-graph, spec-manager, behavior-graph |
| `dependency-vulnerability-check` | Supply chain security | None |

Security analysis benefits from impact awareness (code-graph) and from understanding intentional design — both declarative specs and **accepted, test-backed behaviors** (the strongest "intentional" evidence).

#### The audit driver

`codebase-security-scan` is the one skill whose fan-out is **not** prose. Its `scan` and
`audit` modes call `freya security <mode>`, a driver that owns the control flow itself:

```
freya security scan|audit
    │
    ├─ one context call, then N category finders on a bounded thread pool
    │     (`audit.py:296`), each thread spawning one headless agent CLI process
    │     (`claude -p` / `copilot -p`) under an explicit read-only tool
    │     allowlist — no writes, no shell
    ├─ dedup by file + line-window + category, across rounds
    ├─ three adversarial lenses per surviving finding, majority vote
    └─ a JSON array of verified findings on stdout; the skill formats the report
```

The two modes are presets of one engine and differ **only** in discovery rounds — `scan`
runs one, `audit` loops until dry (max 5). Verification is never cut, because a single
lens's refutation is unanimous and would drop a real finding silently.

The trade is that the driver needs an agent CLI on `PATH`; without one it exits `1` and
the skill falls back to an in-loop scan. It also spends real money, which is why it
refuses to run unconfirmed and why `wrap-up` uses `update`, never `audit`.

Why a driver rather than prose, and why the other two fan-outs stay prose:
[ADR-015](../decisions/ADR-015-driver-owned-fan-out.md) and
[patterns.md § Coordinator + Independent Tasks](../patterns.md#pattern-coordinator--independent-tasks).

### Tiers 4 and 5: Orchestration and Resolution

| Skill | Purpose | Dependencies |
|-------|---------|--------------|
| `wrap-up` | Post-implementation workflow (mutates + commits) | All above |
| `status` | Read-only outstanding-work aggregation; refreshes `BACKLOG.md` | All above (read-only) |
| `codebase-security-resolver` | Fix the findings the scan produced | security-scan |

`wrap-up` is the do/sync command; `status` is its read-only check-counterpart — "where do I
stand, what's outstanding?" The resolver sits below both because it consumes a scan's output and
is the one skill that commits code of its own.

## Data Flow

### Input Sources

```
Codebase Files
      │
      ├── src/**/*.ts ─────────────────────────────────────┐
      ├── src/**/*.py                                       │
      └── ...                                               │
                                                            ▼
                                          ┌─────────────────────────────┐
                                          │   the selected backend      │
                                          │   homegrown | graphify      │
                                          │   produces nodes and edges  │
                                          └─────────────────────────────┘
                                                        │  substrate.Result
                                                        ▼
                                          ┌─────────────────────────────┐
                                          │   the contract (_finalise)  │
                                          │   reverse index, validate,  │
                                          │   census, persist           │
                                          └─────────────────────────────┘
                                                        │
                                ┌───────────────────────┴────────────────────┐
                                ▼                                            ▼
              knowledge-base/.graph/graph.json        knowledge-base/.graph/graph.<backend>.json
                 (what every consumer reads)             (the baseline a swap is diffed against)
```

The active graph and the copy the same build wrote are byte-identical; they diverge only when a
project switches backend. In this checkout, on 2026-08-21, `graph.json` and
`graph.graphify.json` are identical (51,387 bytes, 65 indexed files) and `graph.homegrown.json`
is the floor's build kept from before the switch (81,467 bytes, 62 indexed files) — measured
with `cmp` and by counting the `files` object in each artifact.

### Output Artifacts

**Everything under `knowledge-base/` is designed to be committed except the four generated cache
files inside `.graph/`** — `.graph/` itself is not ignored, and neither its `.gitignore` nor
`behavior.json` nor `settings.json` is. The tree below marks each line so you never have to
infer it. Three lines read `committable — untracked here`: this repository adopted the
`knowledge-base/` layout on 2026-08-21 and has not committed them yet, so `git ls-files` returns
nothing for them while `git check-ignore` also declines them.

```
┌─────────────────────────────────────────────────────────────┐
│                     knowledge-base/            tracked?      │
├─────────────────────────────────────────────────────────────┤
│ ├── README.md             ← docs-manager        tracked      │
│ ├── principles.md         ← spec-manager        tracked      │
│ ├── BACKLOG.md            ← status              tracked      │
│ ├── reference/            ← docs-manager        tracked      │
│ │   ├── ARCHITECTURE.md                         tracked      │
│ │   ├── API.md                                  tracked      │
│ │   └── ...                                     tracked      │
│ ├── specs/                ← spec-manager        tracked      │
│ │   ├── features/                               tracked      │
│ │   ├── auth/                                   tracked      │
│ │   └── .spec-last-update                       tracked      │
│ ├── decisions/            ← spec-manager        tracked      │
│ ├── intents/              ← spec-manager        tracked      │
│ ├── security/             ← security-scan       tracked      │
│ │   ├── codebase-security/                      tracked      │
│ │   │   └── 2024-01-15.md                       tracked      │
│ │   └── .security-last-scan                     tracked      │
│ ├── settings.json         ← engineer/code-graph committable* │
│ └── .graph/                                                  │
│     ├── .gitignore            ← written by us   committable* │
│     ├── graph.json            ← code-graph      ignored      │
│     ├── graph.<backend>.json  ← code-graph      ignored      │
│     ├── classifications.json  ← code-graph      ignored      │
│     ├── docs.json             ← docs-manager    ignored      │
│     └── behavior.json         ← behavior-graph  committable* │
│                                                              │
│   * not ignored, and not yet committed in this repository    │
└─────────────────────────────────────────────────────────────┘
```

`.graph/` ignores its cache by name: `code-graph --build` writes a `.gitignore` listing
`graph.json`, `graph.*.json`, `classifications.json` and `docs.json`
(`skills/freya-code-graph/scripts/graph_ops.py:245`, assembled into the file at
`graph_ops.py:247`), so an adopting project never has to touch its root `.gitignore`. Those four
are a **parse cache** — rebuildable from source in seconds, large (124 KB on a ~230-file app;
81.5 KB and 51.4 KB for the two artifacts in this checkout), and not byte-stable across builds,
since each records the wall-clock `timestamp` of the build that wrote it. (The edge arrays
themselves *are* deterministic: both the specifier pass and the resolved-target pass sort before
emitting, `graph_ops.py:1068` and `:1982`. Two consecutive builds of an unchanged tree, measured
2026-08-21, differed in `timestamp` and in nothing else.) Committing them would put a diff in
every build with zero code change. `graph.*.json` is the per-backend copy each substrate writes beside the
active graph, so a backend swap can be diffed rather than destroying the baseline it should be
measured against (ADR-028).

That list has to be upgradable in place, or a project onboarded before an artifact existed keeps
the shorter list it was given and every later artifact arrives committable — which is exactly
what `graph.<backend>.json` did when it was added. `_EVER_IGNORED` records every list the
toolkit has ever written, so a file containing only those entries is recognised as ours and
rewritten, and one containing anything else is treated as hand-edited and left alone
(`graph_ops.py:270`, `:278`).

`knowledge-base/settings.json` sits outside `.graph/` and is **meant to be committed**: it is
where a project records which backend it wants and which built-in exclusions it overrules, and both have to
survive a clone and reach CI. The first build in a project that has not decided seeds it from
the machine default rather than leaving the choice implicit, validating the name against the
registry on the way (`graph_ops.py:2913`), and prints one line asking for it to be committed
(`graph_ops.py:2921`). Nothing verifies that it was; that line is the entire mechanism. See
ADR-019 and ADR-022.

**`behavior.json` is deliberately not ignored.** It is not a parse cache: its
`source: observed` edges are captured by running the test suite, so they cannot be recovered by
re-reading source — only by re-running a green suite. Ignoring it would leave a fresh clone with
no observed coverage, silently degrading to `static`/`unknown`. Its `exercises` are sorted by
path at write time so the committed file is byte-stable. See
[ADR-017](../decisions/ADR-017-behavior-json-is-committed.md).

The governance resolution logs (`principle-`, `contradiction-`, `drift-resolutions.jsonl`) also live under `knowledge-base/`, and are **tracked**; see [patterns.md](../patterns.md).

### Which paths are tool-owned

Until 2026-08-21 this repository kept its hand-written documentation in a separate `docs/` tree
and had no `knowledge-base/` at all, on the reasoning that generated and hand-written content
should never mix. Running the toolkit on itself is what made that separation cost more than it
saved, so the two now share one directory and the boundary has to be stated instead of implied.

| Path | Owner | What that means |
|---|---|---|
| `knowledge-base/README.md` | `docs-manager` | Owned outright (`skills/freya-docs-manager/SKILL.md:64`); the index is created by the skill rather than hand-written (`SKILL.md:127`) |
| `knowledge-base/reference/` | `docs-manager` | This file's directory. Regenerated for affected areas on each update (`skills/freya-docs-manager/SKILL.md:444`) |
| `knowledge-base/BACKLOG.md` | `status` | Rewritten by full overwrite — the file is opened `"w"` and replaced (`skills/freya-status/scripts/collect_status.py:226`) |
| `knowledge-base/specs/`, `intents/`, `principles.md` | `spec-manager` | Created by the skill, hand-edited between runs |
| `knowledge-base/decisions/` | hand-written | `adr.py` allocates the id, writes the skeleton and verifies frontmatter integrity (`skills/freya-spec-manager/scripts/adr.py:69`, `:113`); everything that makes an ADR worth reading is written by a person |
| `knowledge-base/security/` | `codebase-security-scan` | One report per scan, plus its tracking file |
| `knowledge-base/.graph/` | `code-graph`, `behavior-graph`, `docs-manager` | Machine-written; see the tree above for what is tracked |
| `knowledge-base/settings.json` | the engineer, seeded by `code-graph` | Hand-edited; a first build may seed the backend key |
| `philosophy.md`, `patterns.md`, `roadmap.md`, `migrations/`, `explanations/` | hand-written | Read by the skills, never written by them |

Not every row exists in a given project. The tree materialises path by path as each skill first
runs, which is why the table is a statement of ownership rather than an inventory.

[knowledge-base/README.md](../README.md) lists ownership for the whole tree; the column above
records which of those are mechanical. **Only `BACKLOG.md` is enforced in code** — the file is
opened `"w"` and replaced. For `README.md` and `reference/` there is no code path that
overwrites them; ownership there is a convention an agent following `docs-manager`'s SKILL.md
happens to keep. The hand-maintained backlog is therefore `roadmap.md`, deliberately not
`BACKLOG.md` — `freya status --write-backlog` (`collect_status.py:251`) would overwrite anything
put there.

### Integration Data Flow

```
1. Code changes committed
         │
         ▼
2. code-graph update
   - Reads git diff
   - Runs the project's backend; the contract links, validates,
     censuses and persists graph.json + graph.<backend>.json
   - Provides impact analysis
         │
         ▼
3. docs-manager update
   - Asks code-graph for blast radius
   - Asks docs-graph which doc sections cite each affected file, rather
     than judging correspondence (skills/freya-docs-manager/SKILL.md:441)
   - Updates affected docs
         │
         ▼
4. spec-manager update
   - Asks code-graph for blast radius
   - Updates affected specs, adjusts certainty scores
         │
         ▼
5. behavior integrity & run  (wrap-up Phase 3.5)
   - behavior-graph builds/refreshes behavior.json (projects spec frontmatter,
     runs affected accepted behaviors via behavior-runner, merges by trust)
   - Deterministic link/ADR/declared-intent checks hard-block; a regression on an
     accepted behavior hard-blocks; principle/contradiction/drift checkpoints
     resolve-to-proceed
         │
         ▼
6. security-scan update
   - Asks code-graph for blast radius
   - Asks spec-manager + behavior-graph for intentional design
   - Generates findings with context
```

## Tracking Files

Skills use tracking files to enable incremental updates:

| File | Owner | Purpose |
|------|-------|---------|
| `.spec-last-update` | spec-manager | Last commit scanned for specs |
| `.security-last-scan` | security-scan | Last commit scanned for security |
| `.intent-last-verified` | spec-manager | Baseline for the declared-intent gate (G1) |
| `graph.json` → `commit` field | code-graph | Commit graph was built from |
| `graph.json` → `substrate.backend` | code-graph | Which backend produced the artifact. A foreign one forces a full rebuild rather than splicing one resolver's edges into another's graph (`graph_ops.py:2092`) |
| `graph.json` → `version` field | code-graph | Schema version on disk. A version-1 artifact forces a full rebuild ahead of the "nothing changed" short-circuit (`graph_ops.py:2105`) |

These enable "only process what changed" behavior. The last two are the exceptions that
deliberately *defeat* it: both are conditions under which an incremental pass would produce a
plausible-looking graph that is wrong about where its edges came from.

## Fallback Behavior

Skills degrade rather than fail when a dependency is missing — the general shape is
[patterns.md § Fallback Without Dependencies](../patterns.md#pattern-fallback-without-dependencies).
The behavior layer degrades the same way: with no `code-graph` cache the declarative-drift check
bounds its blast radius to changed files (never a silent empty set), and non-vitest / non-unit
behaviors are emitted `coverage: "unknown"` rather than falsely marked passing.

The substrate has its own ladder, and it is the one place where degrading is recorded in the
artifact rather than only announced. Five paths end in "run the stdlib floor and say so":

| The floor is used because | Recorded as `degraded_from`? |
|---|---|
| A named backend is not installed (`backends.py:139`) | yes, reason `not installed` |
| The name is not a backend at all (same branch, deliberately a different message — telling someone to install a backend that does not exist sends them nowhere) | yes, reason `unknown backend` |
| The selected backend fails the contract check (`graph_ops.py:3033`) | yes, with the conformance errors as the reason |
| The backend throws during the build (`graph_ops.py:2556`) | yes, reason `failed during the build: …` |
| Selection itself raises (`graph_ops.py:3048`) | **no** — stderr only |

The last row is the deliberate exception, and it is worth knowing about before trusting
`degraded_from` as a complete record: selection is an optimisation over "run the floor", so when
it fails the build proceeds as an ordinary floor build with no metadata attached.

`degraded_from` and `substrate.unmapped_source` are not interchangeable, and the rule that keeps
them apart — a caveat may change what an answer says about itself, never whether there is one —
is [patterns.md § An Answer That Qualifies Itself](../patterns.md#pattern-an-answer-that-qualifies-itself)
and [ADR-029](../decisions/ADR-029-an-answer-says-what-it-could-not-read.md). The diagnostic
version, for a reader who has hit the confusion, is
[TROUBLESHOOTING.md § Debugging Tips](TROUBLESHOOTING.md#debugging-tips).

## Directory Structure

The checkout is the **canonical store**. It has two layers: `bin/` (the launcher and the
install/update machinery, agent-independent) and `skills/` (the ten skills). Installing
links a `freya-<skill>` directory into an agent's skills directory; nothing is rewritten
on the way in.

```
bin/
├── freya                       # executable shim — the only thing that lands on PATH
├── freya_cli.py                # dispatch, `doctor`, `help`; logic lives here, importable
├── commands.json               # command -> skills/<skill>/scripts/<script>.py manifest
├── installer.py                # install.sh / install.ps1 back end: link, --copy, uninstall
├── updater.py                  # `freya update` (fast-forward + re-link) + the update notice
├── agents_md.py                # `freya init` — the managed AGENTS.md block
├── backend_setup.py            # the once-per-machine substrate question, asked at install/update
└── check_skill_conformance.py  # the agent-neutrality gate (R1–R13)
```

`backend_setup.py` is called from both `bin/installer.py:988` and `bin/updater.py:276` and lives
in `bin/` rather than under `skills/freya-code-graph/`, because the answer it records is a
property of the machine and belongs to whichever hosts the suite was installed for, not to one
skill. It is not in `commands.json`: there is no `freya backend-setup` command.

How `freya <command>` resolves to one of those scripts, and why every portability property the
skill layer has rests on it, is
[DEVELOPER.md § How the launcher resolves a command](DEVELOPER.md#how-the-launcher-resolves-a-command).

Every skill directory is `freya-<name>/` with a `SKILL.md` at its root, plus `scripts/` and
`references/` where it needs them. Three skills are prose only —
`freya-codebase-security-resolver`, `freya-dependency-vulnerability-check`, `freya-wrap-up`.
The rest carry the scripts below; each is reachable as `freya <command>` and nothing else
addresses it by path.

```
freya-code-graph/scripts/
  substrate.py          the contract: vocabulary, Result, Coverage, Exclusions,
                        conformance + graph validation
  backends.py           the registry, selection, the extension census
  graph_ops.py          the `homegrown` floor, the contract's funnel, the CLI
  backend_graphify.py   the graphify backend: extract, project onto file pairs
  settings.py           project + machine settings, and their precedence

freya-docs-manager/scripts/
  detect_project.py     stack / framework detection
  docs_graph.py         docs.json — doc section -> code file

freya-spec-manager/scripts/
  search_specs.py       spec CRUD / search          frontmatter.py    schema + validation
  adr.py                ADRs (P4a)                  principles.py     G2 principle checkpoint
  contradictions.py     G3 contradiction check      drift.py          P4b declarative drift
  intent.py             INTENT-NNN records          verify_intent.py  G1 declared-intent gate
  verify_links.py       link integrity              adapters.py       test-adapter detection
  project_shape.py      greenfield / brownfield detection for `bootstrap`
  resolution_log.py     shared append-only resolution log

freya-behavior-graph/scripts/behavior_graph.py     freya-status/scripts/collect_status.py
freya-behavior-runner/scripts/run_behaviors.py

freya-codebase-security-scan/scripts/              the audit driver (above)
  audit.py              CLI, budget guard, confirmation, exit codes
  audit_engine.py       discovery loop, dedup, skeptic voting, disposition
  audit_adapter.py      per-agent argv (claude / copilot) + read-only flags
  audit_io.py           categories, lenses, JSON schemas, extract + validate
```

## Key Design Decisions

The substrate work is the largest structural change since the behavior layer, and each fork in
it has a record. The full reasoning, including what was rejected and under what conditions to
revisit, is in [decisions/](../decisions/); this table is a map, not a summary.

| Decision | Why | Chief alternative rejected |
|---|---|---|
| The graph is produced through a contract, not by one resolver ([ADR-018](../decisions/ADR-018-substrate-contract-for-the-code-graph.md)) | Choosing a parser means choosing again in a few years, by which time every consumer is built on its output shape | Wire graphify in directly — fastest to ship, reopens the whole question on its first stall |
| The floor always ships; another backend runs because a person named it ([ADR-019](../decisions/ADR-019-the-floor-and-choosing-a-backend.md)) | A ranking `auto` makes "which parser produced this graph" a property of `PATH`, changing every blast radius with no diff | Score the installed backends and let `auto` pick the widest |
| The contract persists; a backend only produces ([ADR-020](../decisions/ADR-020-the-contract-persists-the-graph.md)) | A second backend satisfying every documented obligation exited 0 and wrote no graph | Leave persistence in each backend and document what it must do |
| An edge is an object with `kind` and `provenance` ([ADR-021](../decisions/ADR-021-an-edge-is-an-object-with-kind-and-provenance.md)) | A string carries exactly one fact — where the edge points — so a barrel that only forwards a module and a module that uses it were the same value | Stay file-level with bare strings and drop the symbol kinds |
| Each backend writes its own graph beside the active one ([ADR-028](../decisions/ADR-028-graphs-are-stored-per-backend.md)) | With one file the baseline is destroyed at exactly the moment a swap needs diffing | Copy the graph aside by hand before switching |
| Every answer says what the backend could not read ([ADR-029](../decisions/ADR-029-an-answer-says-what-it-could-not-read.md)) | A file whose extension the backend does not handle is never enumerated, so `files_scanned` reads like a denominator | Say it on stderr everywhere — discarded by all three skill-to-skill callers |

Two promises in that set are **designed and unenforced**, and are recorded that way rather than
in the present tense: the `extracted`/`inferred` trust tier has no filter behind it, and
`coverage.relations` is written on every build and consumed by no caller.

## External Dependencies

There are no third-party Python dependencies. Every bundled script imports the standard library
and nothing else, which is what lets the floor work on a machine where `uv`, pip and the network
are all unavailable — the case the polyglot effort exists to serve. What follows is either
already on the machine, or optional.

| Dependency | Required | Used for |
|---|---|---|
| Python 3 | yes | Everything. `bin/freya` runs each target with `sys.executable`, so no SKILL.md names an interpreter |
| `git` | for incremental work | The `commit` field a graph is built from (`graph_ops.py:524`) and the diff an update reads (`graph_ops.py:562`). `.gitignore` is also a scope input, but it is read as a plain file and needs no git |
| `graphify` | no | The second substrate backend. Availability is `shutil.which('graphify')` and nothing more (`skills/freya-code-graph/scripts/backend_graphify.py:309`) |
| an agent CLI (`claude` / `copilot`) | no | The security audit driver's worker processes. Without one it exits `1` and the skill falls back to an in-loop scan |
| `pytest` | development only | The runner CONTRIBUTING tells contributors to use. The suites themselves are not written for it — all 29 test modules in this checkout import `unittest` and none imports `pytest` |

`graphify` is the only one that changes what an artifact contains. Two costs are worth stating
before adopting it. It has **no version check**: `available()` tests for the binary on `PATH`
and nothing else, so an incompatible release is selected and then fails into the degrade path
rather than being refused up front. And it writes its own extraction output to `graphify-out/`
at the project root, which is a different order of magnitude from the projected graph — measured
in this checkout on 2026-08-21, `graphify-out/` is 16 MB with a 5.0 MB `graph.json`, against the
51 KB contract graph projected from it. The backend writes a `.gitignore` containing `*` into
that directory after the tool has run, and leaves a hand-edited one alone
(`backend_graphify.py:386`).

## Related Documentation

- [philosophy.md](../philosophy.md) — why the skills exist and the mental model behind them
- [patterns.md](../patterns.md) — the reusable patterns these components are instances of
- [SKILL_REFERENCE.md](SKILL_REFERENCE.md) — every skill, its commands, and what it reads and writes
- [DEVELOPER.md](DEVELOPER.md) — the conventions for writing a skill that fits
- [decisions/](../decisions/) — the ADRs. Authority for every "why" on this page
- [roadmap.md](../roadmap.md) — what is outstanding, including the unenforced promises named above
