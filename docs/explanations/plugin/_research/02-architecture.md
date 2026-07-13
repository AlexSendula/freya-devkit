# Architecture — Research Brief

Backing brief for the freya-devkit plugin explainer. Topic: **Architecture** — skill
tiers / dependency graph, data flow, how skills query code-graph and degrade to git
diff, and the keystone role of code-graph.

Primary source: `docs/architecture.md`. Cross-checked against the live skills in
`skills/*/SKILL.md`, `skills/code-graph/scripts/graph_ops.py`,
`skills/code-graph/references/graph-schema.md`, `skills/behavior-graph/SKILL.md`,
`skills/behavior-graph/scripts/behavior_graph.py`, `skills/status/SKILL.md`,
`skills/wrap-up/SKILL.md`, and the consumer SKILLs (`docs-manager`, `spec-manager`,
`codebase-security-scan`).

> **Doc-vs-reality caveat (verified):** `docs/architecture.md` is partially stale. It
> shows a 7-skill `.claude/skills/` layout and does not mention the newer skills
> (`behavior-graph`, `behavior-runner`, `status`) that now ship in `skills/`. The
> conceptual tiering (code-graph = foundation, consumers use it, wrap-up orchestrates)
> is still accurate; the file list and the `.claude/` path prefix are not. Skills now
> ship as a plugin and are invoked namespaced as `/freya-devkit:<skill>`, with scripts
> referenced via `${CLAUDE_PLUGIN_ROOT}/skills/...`. This brief flags stale details as
> UNVERIFIED / superseded where relevant.

---

## 1. What it is

The architecture is a **layered set of skills that share a single generated dependency
graph** and a common on-disk artifact tree (`knowledge-base/`). One skill —
**code-graph** — builds and owns the dependency graph; every other analysis skill
either *queries* that graph for "blast radius" (what a change affects) or *degrades* to
a plain `git diff` when the graph is unavailable. A top-level **wrap-up** skill runs the
consumers in a fixed sequence after implementation, and a read-only **status** skill is
its non-mutating counterpart.

> "How skills connect, share data, and work together." — `docs/architecture.md:3`

---

## 2. Why it exists

The design goal is **impact-aware, incremental** maintenance of docs, specs, security
findings, and behavior coverage. Rather than re-scanning the whole codebase every time,
each consumer asks code-graph "if these files changed, what else is affected?" and only
updates the affected artifacts. code-graph is the shared substrate that makes this
possible.

> "This is the foundation. It knows what files depend on what, enabling impact-aware
> operations." — `docs/architecture.md:44`

> "This means skills work standalone but work better together." —
> `docs/architecture.md:182`

---

## 3. Skill tiers (the dependency graph of skills)

From `docs/architecture.md:36-78`, augmented with the live skills:

| Tier | Skill(s) | Role | Depends on |
|------|----------|------|-----------|
| 1 — Foundation | `code-graph` | Dependency graph, impact analysis | none (used by all) |
| 2 — Consumers | `docs-manager`, `spec-manager` | Maintain docs / feature specs | code-graph (**optional**) |
| 3 — Analysis | `codebase-security-scan`, `dependency-vulnerability-check` | Security auditing / supply-chain | code-graph + spec-manager (scan); none (dep-check) |
| 4 — Orchestration | `wrap-up` | Post-implementation sequence | all above |
| 5 — Resolution | `codebase-security-resolver` | Fix security findings | security-scan |

**Newer skills not yet reflected in `docs/architecture.md` (verified from `skills/`):**

- **`behavior-graph`** — owns `behavior.json`, "the pure graph layer over code-graph +
  behavior-runner" (`skills/behavior-graph/SKILL.md:6`). A *second* graph tier that sits
  **on top of** code-graph: it queries code-graph's `--impact` and never the reverse
  ("`code-graph` stays unaware of behaviors", `skills/behavior-graph/SKILL.md:25`).
- **`behavior-runner`** — executes accepted behaviors and emits TEST→CODE coverage
  fingerprints; the producer feeding behavior-graph.
- **`status`** — read-only "check-counterpart of wrap-up" (`skills/status/SKILL.md:12`);
  aggregates outstanding work and refreshes `knowledge-base/BACKLOG.md`.

**The keystone role of code-graph.** It is Tier 1 and "Used By: All other skills"
(`docs/architecture.md:42`). Every impact-aware feature — docs updates, spec updates,
security prioritization, and behavior blast-radius — is a query against the graph
code-graph produces. If code-graph is absent or has no cached graph, consumers fall back
to a coarser git-diff-only view (see §7). It is the single point that turns "changed
files" into "affected files."

### Skill dependency diagram (verbatim, `docs/architecture.md:7-34`)

```
                    ┌─────────────────────────────────────┐
                    │            wrap-up                  │
                    │   (orchestrates post-implementation) │
                    └─────────────────────────────────────┘
                                    │
            ┌───────────────────────┼───────────────────────┐
            ▼                       ▼                       ▼
    ┌───────────────┐     ┌───────────────┐     ┌───────────────────┐
    │  code-graph   │     │ docs-manager  │     │codebase-security- │
    └───────────────┘     └───────────────┘     │      scan         │
            │                       │            └───────────────────┘
            └───────────────────────┼───────────────────────┘
                                    ▼
                          ┌───────────────┐
                          │ spec-manager  │
                          └───────────────┘
                                    ▼
                          ┌───────────────┐
                          │ code-graph    │
                          │ (foundation)  │
                          └───────────────┘
```

---

## 4. How it works — the graph and the pipeline

### 4a. code-graph: build → store → query

code-graph parses import/export relationships across TypeScript/JS, Python, and Go and
stores a dependency graph plus a directory-classification file:

```
knowledge-base/.graph/
├── graph.json           # Dependency graph
└── classifications.json # Directory classifications (source/exclude)
```
(`skills/code-graph/SKILL.md:41-46`)

- **`graph.json`** holds, per file: `exports`, `imports`, `dependents` (reverse
  mapping), optional `category` and `language`, plus top-level `version`, `commit`,
  `timestamp`, `project_root` (`skills/code-graph/references/graph-schema.md:16-88`).
- **Import edges are tagged** as internal (a project-relative path), `external:<pkg>`,
  or `unresolved:<import>`. An import is *internal* only when it carries **neither** the
  `external:` nor the `unresolved:` prefix — "this is the predicate consumers use to
  count internal edges" (`skills/code-graph/references/graph-schema.md:222-228`).
  Unresolved imports are surfaced, not silently dropped, so "no dependencies" is
  distinguishable from "could not resolve" (`skills/code-graph/SKILL.md:160`).
- **Directory classification** is hybrid: rules first (known `src/`, `lib/`, `app/`… →
  source; `node_modules/`, `.next/`, `dist/`… → exclude), then AI for unknowns, then
  user confirmation for <80% confidence, cached to `classifications.json`
  (`skills/code-graph/SKILL.md:128-154`).
- **Impact algorithm:** `impact(file) = file + direct_dependents + transitive_dependents`
  — a recursive traversal over the `dependents` reverse edges
  (`skills/code-graph/SKILL.md:104-110`; reference impl at
  `skills/code-graph/references/graph-schema.md:234-249`).

### 4b. Integration data flow (verbatim intent, `docs/architecture.md:127-154`)

```
1. Code changes committed
2. code-graph update      → reads git diff, updates graph.json, provides impact analysis
3. docs-manager update    → asks code-graph for blast radius, updates affected docs
4. spec-manager update    → asks code-graph for blast radius, updates specs + certainty
5. security-scan update   → asks code-graph for blast radius, asks spec-manager for
                            intentional design, generates findings with context
```

### 4c. How consumers query code-graph (verified per skill)

Each consumer follows the same pattern: check if the skill/graph exists → call
`impact` (or `dependents`) → use the result → otherwise fall back to git diff.

- **docs-manager** (`skills/docs-manager/SKILL.md:409-422`): "Call
  `/freya-devkit:code-graph impact <changed-files>` to get blast radius" to decide which
  docs need updating.
- **spec-manager** (`skills/spec-manager/SKILL.md:300-304`): "Call
  `/freya-devkit:code-graph impact <changed-files>` to get blast radius … Map blast
  radius to existing specs via `related_code`."
- **codebase-security-scan** (`skills/codebase-security-scan/SKILL.md:181-198`): uses
  `impact <changed-files>` to widen the incremental scan and `dependents
  <vulnerable-file>` to compute a finding's blast radius → sets HIGH/MEDIUM/LOW
  remediation priority.
- **spec-manager bootstrap** (`skills/spec-manager/SKILL.md:159`): "Run
  `/freya-devkit:code-graph build` — the shape detector needs it," using the internal-edge
  count from the tagged imports.

### 4d. The behavior graph layer (on top of code-graph)

`behavior-graph` builds `behavior.json` (sibling to `graph.json` under the git-ignored
`knowledge-base/.graph/`) as a BEHAVIOR→TEST→CODE projection. It **queries** code-graph
`--impact` and behavior-runner `--emit-fingerprints`, merges by trust (`observed >
static`), and answers two directions (`skills/behavior-graph/SKILL.md:14-25`):

- **Direction A** — `--affected <changed-files>`: which accepted/confirmed behaviors a
  code change touches (blast radius, code → behavior).
- **Direction B** — `--implements <BEH-NNN>`: which code a behavior exercises
  (behavior → code).

Only `accepted` behaviors gate/regress; `confirmed` behaviors are advisory (never run,
only carry `static`/`unknown` fingerprints) — `skills/behavior-graph/SKILL.md:36-40`.

---

## 5. Exact CLI + flags (verbatim)

### code-graph — `graph_ops.py` (`skills/code-graph/scripts/graph_ops.py:1323-1334`)

Mutually-exclusive operation group + shared options:

| Flag | Meaning |
|------|---------|
| `--build` | Build graph from scratch |
| `--update` | Update graph incrementally |
| `--query FILE` | Query file info |
| `--impact FILE [FILE ...]` | Impact analysis (`nargs='+'`) |
| `--dependents FILE` | Get dependents |
| `--dependencies FILE` | Get dependencies |
| `--clear` | Clear cache |
| `--dir PATH` | Project directory |
| `--format {json,summary}` | Output format (default `json`) |
| `--non-interactive` | Never prompt; uncertain dirs default to **source** |

`--non-interactive` is also auto-enabled when stdin is not a TTY (e.g. when invoked by
wrap-up); uncertain directories default to **source** "so real code is never silently
dropped" (`skills/code-graph/SKILL.md:150-153`).

Slash-command equivalents: `build`, `update`, `query <file>`, `impact <file>`,
`dependents <file>`, `dependencies <file>`, `clear`, `help`
(`skills/code-graph/SKILL.md:25-34`).

Direct script call form (`skills/code-graph/SKILL.md:368-393`):
```bash
python "${CLAUDE_PLUGIN_ROOT}/skills/code-graph/scripts/graph_ops.py" --build --dir /path/to/project
python "${CLAUDE_PLUGIN_ROOT}/skills/code-graph/scripts/graph_ops.py" --impact src/lib/auth.ts --format json
```

### behavior-graph — `behavior_graph.py` (`skills/behavior-graph/scripts/behavior_graph.py:371-405`)

`--project` (required) + one of: `--build`, `--affected FILE [...]`, `--implements BEH`,
`--check`, `--surface`, `--gaps`, `--covering FILE`. `--check` and `--surface` require
`--base COMMIT` (diff `base..HEAD`).

### wrap-up skip flags (`skills/wrap-up/SKILL.md:599-608`)

`--no-security`, `--no-docs`, `--no-specs`, `--no-graph` (combinable).

---

## 6. Inputs, outputs, artifacts

### Inputs

Source files: `**/*.ts`, `**/*.tsx`, `**/*.js`, `**/*.jsx`, `**/*.py`, `**/*.go`
(`skills/code-graph/SKILL.md:162-166`). Excludes `node_modules`, `__pycache__`, `.git`,
`dist`, `build`, `venv`, framework build outputs (`.next`, `.nuxt`, `.output`, `out`),
`coverage`, `.cache`, plus `.gitignore` patterns and any AI/user "exclude" dirs
(`skills/code-graph/SKILL.md:167-173`).

### Output artifact tree (`docs/architecture.md:102-125`)

```
knowledge-base/
├── README.md             ← docs-manager (index)
├── principles.md         ← spec-manager (constitution)
├── reference/            ← docs-manager (ARCHITECTURE.md, API.md, ...)
├── specs/                ← spec-manager (features/, auth/, .spec-last-update)
├── decisions/            ← spec-manager (cross-cutting ADRs)
├── security/             ← security-scan (codebase-security/, .security-last-scan)
└── .graph/               ← code-graph (graph.json, classifications.json)
```
Plus (verified from live skills, not in the stale doc): `.graph/behavior.json`
(behavior-graph), `knowledge-base/BACKLOG.md` (status/wrap-up),
`knowledge-base/intents/` + `.intent-last-verified`, and `*-resolutions.jsonl`
resolution logs.

### Tracking files (incremental-update markers, `docs/architecture.md:156-166`)

| File | Owner | Purpose |
|------|-------|---------|
| `.spec-last-update` | spec-manager | Last commit scanned for specs |
| `.security-last-scan` | security-scan | Last commit scanned for security |
| `graph.json` → `commit` field | code-graph | Commit graph was built from |

> "These enable 'only process what changed' behavior." — `docs/architecture.md:166`

### The wrap-up pipeline (`skills/wrap-up/SKILL.md`)

Two-commit pattern: **Commit 1** = code; then artifact generation runs
code-graph → docs-manager → spec-manager → behavior integrity/run → security-scan;
**Commit 2** = artifacts. Rationale: "Security scan has a stable commit to reference"
and "Clean git history (code changes vs. generated files)"
(`skills/wrap-up/SKILL.md:38-42`). wrap-up warns and skips any missing required skill
(`skills/wrap-up/SKILL.md:584-592`).

---

## 7. Degradation behavior (query code-graph → fall back to git diff)

This is the load-bearing resilience property. Verbatim from `docs/architecture.md:168-182`:

```yaml
# Example from docs-manager
if code-graph available:
    blast_radius = /freya-devkit:code-graph impact <changed-files>
    update docs for affected files
else:
    # Fallback to simple git diff
    update docs for directly changed files
```

Verified per skill:

- **docs-manager** (`skills/docs-manager/SKILL.md:417-418`): "If
  `/freya-devkit:code-graph` is not available or no cached graph exists, fall back to
  simple git diff analysis."
- **spec-manager** (`skills/spec-manager/SKILL.md:293, 304`): missing graph or no git
  repo → "fall back to full scan (like `scan` command)"; no code-graph → fallback path.
- **codebase-security-scan** (`skills/codebase-security-scan/SKILL.md:185-187,
  996-1000`): without code-graph, `update` "falls back to simple git diff (only changed
  files)"; `impact` returns a "code-graph not available" error; `scan` "works normally
  (doesn't need code-graph)". Explicit warn: "code-graph not available - scanning only
  directly changed files."
- **behavior-graph drift** (via wrap-up, `skills/wrap-up/SKILL.md:363-367`): when
  code-graph is absent, `impact_source` is `changed-only` — the blast radius narrows to
  changed files (no dependents) and is surfaced, "never a silent empty set."
- **status** (`skills/status/SKILL.md`): "each source degrades to a `note` if
  unavailable, and the command never blocks."

**Net effect:** every consumer runs standalone (git-diff-only) but produces a *wider,
more accurate* impact set when code-graph's graph is present.

---

## 8. Honest limits / gotchas

- **`docs/architecture.md` is partially stale (verified):** it lists only 7 skills under
  a `.claude/skills/` tree and omits `behavior-graph`, `behavior-runner`, `status`. The
  tiering and data-flow concepts hold; the file inventory and paths do not.
- **code-graph limitations (`skills/code-graph/SKILL.md:401-406`):** may miss dynamic
  `import()` / `require(variable)`; only tracks local file relationships (not npm/pip
  package internals); supports TypeScript/JS, Python, Go only; monorepos should have one
  graph per subproject.
- **Graph is a snapshot.** behavior-graph Direction A/B "reflect the last `--build`
  snapshot — re-run `--build` after spec or code changes to refresh"
  (`skills/behavior-graph/SKILL.md:22`).
- **Never-synced guard (F5).** wrap-up must not let incremental `update` silently trigger
  a full-codebase generation on a project that was never synced — it reports unsynced and
  runs the explicit first-time `scan`/`build` (`skills/wrap-up/SKILL.md:101-107`).
- **Path-alias dependence.** Alias-heavy projects (e.g. Next.js `@/…`) need
  `tsconfig.json`/`jsconfig.json` `paths`+`baseUrl` or the internal graph is empty
  (`skills/code-graph/SKILL.md:158-159`).
- **UNVERIFIED — hardcoded absolute path in wrap-up:** two commands in
  `skills/wrap-up/SKILL.md` (lines 159 and 458) reference an absolute
  `/Users/main/.claude/plugins/cache/...verify_intent.py` path instead of
  `${CLAUDE_PLUGIN_ROOT}`. Noted as an apparent inconsistency, not a claim about intended
  behavior. (Machine-specific path abstracted here per sanitization rules.)
- **UNVERIFIED — gitignore of `.graph/`:** the docs say add `knowledge-base/.graph/` to
  `.gitignore` "if you don't want to commit the generated graph"
  (`skills/code-graph/SKILL.md:49`), yet also that the graph is stored under
  `knowledge-base/` "so it stays version-controlled" — the default (committed vs ignored)
  is presented both ways; `behavior.json` is described as living "under the git-ignored
  `knowledge-base/.graph/`" (`skills/wrap-up/SKILL.md:190`). Treat the ignore status as
  project-configurable.

---

## 9. Verbatim quotable lines

- "How skills connect, share data, and work together." — `docs/architecture.md:3`
- "This is the foundation. It knows what files depend on what, enabling impact-aware
  operations." — `docs/architecture.md:44`
- "These skills work standalone but work better together." — `docs/architecture.md:182`
- "impact(file) = file + direct_dependents(file) + transitive_dependents(file)" —
  `skills/code-graph/SKILL.md:107`
- "Pure graph layer over code-graph + behavior-runner." — `skills/behavior-graph/SKILL.md:6`
- "It *queries* `code-graph` (`--impact`) … `code-graph` stays unaware of behaviors." —
  `skills/behavior-graph/SKILL.md:24-25`
- "The read-only **check** counterpart of `/freya-devkit:wrap-up` (which *does/syncs*)." —
  `skills/status/SKILL.md:12`
- "code-graph not available - scanning only directly changed files" —
  `skills/codebase-security-scan/SKILL.md:187`

---

## Sources read

- `docs/architecture.md`
- `skills/code-graph/SKILL.md`
- `skills/code-graph/references/graph-schema.md`
- `skills/code-graph/scripts/graph_ops.py` (argparse block)
- `skills/behavior-graph/SKILL.md`
- `skills/behavior-graph/scripts/behavior_graph.py` (argparse block)
- `skills/status/SKILL.md`
- `skills/wrap-up/SKILL.md`
- `skills/docs-manager/SKILL.md`, `skills/spec-manager/SKILL.md`,
  `skills/codebase-security-scan/SKILL.md` (integration/fallback sections)
- `.claude-plugin/plugin.json`, `.claude-plugin/marketplace.json`
