# Architecture

How skills connect, share data, and work together.

## Skill Dependency Graph

The toolkit is **ten skills across five tiers**. Each tier builds on the ones above it:

```
Tier 1 — Foundation
    code-graph ............ builds knowledge-base/.graph/graph.json (impact / blast radius)
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

This is the foundation. It knows what files depend on what, enabling impact-aware operations.

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
    ├─ one context call, then N category finders on a bounded process pool
    │     each an independent headless agent CLI (`claude -p` / `copilot -p`)
    │     under an explicit read-only tool allowlist — no writes, no shell
    ├─ dedup by file + line-window + category, across rounds
    ├─ three adversarial lenses per surviving finding, majority vote
    └─ a JSON array of verified findings on stdout; the skill formats the report
```

The two modes are presets of one engine and differ **only** in discovery rounds — `scan`
runs one, `audit` loops until dry (max 5). Verification is never cut, because a single
lens's refutation is unanimous and would drop a real finding silently.

Why a driver rather than the prose fan-out every other skill uses: validation watched a
host agent run a six-way fan-out itself, sequentially, and then report it as parallel —
and an agent's own account of its work cannot distinguish the two. The workers here are
separate OS processes, so no agent gets a vote. The trade is that the driver needs an
agent CLI on `PATH`; without one it exits `1` and the skill falls back to an in-loop
scan. It also spends real money, which is why it refuses to run unconfirmed and why
`wrap-up` uses `update`, never `audit`.

The other two fan-outs (`docs-manager`, `spec-manager scan`) stay prose deliberately —
their workers *write files*, which inverts the read-only property the driver's guarantee
rests on. See [patterns.md](../patterns.md#pattern-coordinator--independent-tasks).

### Tier 4: Orchestration

| Skill | Purpose | Dependencies |
|-------|---------|--------------|
| `wrap-up` | Post-implementation workflow (mutates + commits) | All above |
| `status` | Read-only outstanding-work aggregation; refreshes `BACKLOG.md` | All above (read-only) |

`wrap-up` is the do/sync command; `status` is its read-only check-counterpart — "where do I stand, what's outstanding?"

### Tier 5: Resolution

| Skill | Purpose | Dependencies |
|-------|---------|--------------|
| `codebase-security-resolver` | Fix security issues | security-scan |

Handles the output of security scanning.

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
                                          │        code-graph           │
                                          │   builds dependency graph   │
                                          └─────────────────────────────┘
                                                        │
                                                        ▼
                                          knowledge-base/.graph/graph.json
```

### Output Artifacts

**Everything under `knowledge-base/` is committed except `.graph/`.** That is the rule; the
tree below marks each line so you never have to infer it.

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
│ ├── settings.json             ← the engineer     tracked      │
│ └── .graph/                                                  │
│     ├── .gitignore            ← written by us   tracked      │
│     ├── graph.json            ← code-graph      ignored      │
│     ├── graph.<backend>.json  ← code-graph      ignored      │
│     ├── classifications.json  ← code-graph      ignored      │
│     ├── docs.json             ← docs-manager    ignored      │
│     └── behavior.json         ← behavior-graph  tracked      │
└─────────────────────────────────────────────────────────────┘
```

`.graph/` ignores its cache by name: `code-graph --build` writes a `.gitignore` listing
`graph.json`, `graph.*.json`, `classifications.json` and `docs.json`
(`skills/freya-code-graph/scripts/graph_ops.py`, `CACHE_GITIGNORE`), so an adopting project
never has to touch its root `.gitignore`. Those four are a **parse cache** — rebuildable from
source in seconds, large (124 KB on a ~230-file app), and not byte-stable across builds, since
their `imports` arrays come out of a set. Committing them would put a diff in every build with
zero code change. `graph.*.json` is the per-backend copy each substrate writes beside the active
graph, so a backend swap can be diffed rather than destroying the baseline it should be measured
against (ADR-028).

`knowledge-base/settings.json` sits outside `.graph/` and **is** tracked: it is where a project
records which backend it wants and which built-in exclusions it overrules, and both have to
survive a clone and reach CI. See ADR-019 and ADR-022.

**`behavior.json` is deliberately not ignored.** It is not a parse cache: its
`source: observed` edges are captured by running the test suite, so they cannot be recovered by
re-reading source — only by re-running a green suite. Ignoring it would leave a fresh clone with
no observed coverage, silently degrading to `static`/`unknown`. Its `exercises` are sorted by
path at write time so the committed file is byte-stable. See
[ADR-017](../decisions/ADR-017-behavior-json-is-committed.md).

The governance resolution logs (`principle-`, `contradiction-`, `drift-resolutions.jsonl`) also live under `knowledge-base/`, and are **tracked**; see [patterns.md](../patterns.md).

### Integration Data Flow

```
1. Code changes committed
         │
         ▼
2. code-graph update
   - Reads git diff
   - Updates graph.json
   - Provides impact analysis
         │
         ▼
3. docs-manager update
   - Asks code-graph for blast radius
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

These enable "only process what changed" behavior.

## Fallback Behavior

Skills gracefully degrade when dependencies are missing:

```yaml
# Example from docs-manager
if code-graph available:
    blast_radius = freya-code-graph impact <changed-files>
    update docs for affected files
else:
    # Fallback to simple git diff
    update docs for directly changed files
```

This means skills work standalone but work better together. The behavior layer degrades the same way: with no `code-graph` cache the declarative-drift check bounds its blast radius to changed files (never a silent empty set), and non-vitest / non-unit behaviors are emitted `coverage: "unknown"` rather than falsely marked passing.

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
└── check_skill_conformance.py  # the agent-neutrality gate (R1–R13)
```

`freya <command> …` resolves through `bin/commands.json` and runs the target with
`sys.executable`, so a SKILL.md never names an interpreter or a path.
`bin/freya` self-locates via `os.path.realpath(__file__)` — deliberately `realpath`, not
`abspath`, because under `-P` / `PYTHONSAFEPATH` CPython does not auto-insert a resolved
`sys.path[0]`. Since `realpath` follows symlinks, a skill linked into an agent's directory
still resolves back to the store where its siblings live.

```
skills/
├── freya-code-graph/
│   ├── SKILL.md
│   ├── scripts/
│   │   └── graph_ops.py
│   └── references/
├── freya-docs-manager/
│   ├── SKILL.md
│   ├── evals/
│   ├── references/
│   └── scripts/
│       └── detect_project.py
├── freya-spec-manager/
│   ├── SKILL.md
│   ├── evals/
│   ├── scripts/
│   │   ├── search_specs.py       # spec CRUD / search
│   │   ├── frontmatter.py        # schema + validation
│   │   ├── adr.py                # ADRs (P4a)
│   │   ├── principles.py         # G2 principle checkpoint
│   │   ├── contradictions.py     # G3 contradiction check
│   │   ├── drift.py              # P4b declarative-drift check
│   │   ├── intent.py             # INTENT-NNN records
│   │   ├── verify_intent.py      # G1 declared-intent gate
│   │   ├── verify_links.py       # link integrity
│   │   ├── adapters.py           # test-adapter detection
│   │   ├── project_shape.py      # greenfield / brownfield detection for `bootstrap`
│   │   └── resolution_log.py     # shared append-only resolution log
│   └── references/
│       ├── spec-template.md
│       ├── categories.md
│       └── ...
├── freya-behavior-graph/
│   ├── SKILL.md
│   └── scripts/
│       └── behavior_graph.py
├── freya-behavior-runner/
│   ├── SKILL.md
│   └── scripts/
│       └── run_behaviors.py
├── freya-codebase-security-scan/
│   ├── SKILL.md
│   ├── scripts/                    # the audit driver (see below)
│   │   ├── audit.py                # CLI, budget guard, confirmation, exit codes
│   │   ├── audit_engine.py         # discovery loop, dedup, skeptic voting, disposition
│   │   ├── audit_adapter.py        # per-agent argv (claude / copilot) + read-only flags
│   │   └── audit_io.py             # categories, lenses, JSON schemas, extract + validate
│   └── references/
├── freya-codebase-security-resolver/
│   └── SKILL.md
├── freya-dependency-vulnerability-check/
│   └── SKILL.md
├── freya-status/
│   ├── SKILL.md
│   └── scripts/
│       └── collect_status.py
└── freya-wrap-up/
    └── SKILL.md
```

Each skill follows a similar structure but adapts to its needs.
