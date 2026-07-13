# Research Brief: Knowledge-Base Artifacts

**Topic:** The on-disk data the freya-devkit toolkit produces and shares.
**Scope:** The full `knowledge-base/` layout — `graph.json`, docs (`reference/`),
specs, security `findings.json`, `behavior.json`, governance JSONL logs, and the
tracking dotfiles (`.spec-last-update`, `.security-last-scan`, etc.). Who writes
each, who reads each, and how they degrade.

**Primary sources read:**
- `docs/conventions.md`
- `docs/architecture.md`
- `docs/migrations/knowledge-base.md`
- `skills/code-graph/references/graph-schema.md`, `skills/code-graph/SKILL.md`
- `skills/codebase-security-scan/references/findings-schema.md`, `skills/codebase-security-scan/SKILL.md`
- `skills/behavior-graph/SKILL.md`, `skills/behavior-graph/scripts/behavior_graph.py`
- `skills/behavior-runner/scripts/run_behaviors.py`
- `skills/spec-manager/SKILL.md`, `skills/spec-manager/references/spec-template.md`
- `skills/spec-manager/scripts/{resolution_log,principles,contradictions,drift,intent}.py`
- `skills/docs-manager/SKILL.md`
- `skills/status/SKILL.md`, `skills/status/scripts/collect_status.py`
- `skills/wrap-up/SKILL.md`
- `.gitignore`

---

## 1. What it is

Every freya-devkit skill that produces durable output writes it under a **single
project-local root directory: `knowledge-base/`**. This is the toolkit's shared
data layer — a version-controlled folder that lives inside the target project (not
in `~/.claude`), so the artifacts stay in sync with the branch and travel with the
code.

The root holds a mix of **human-readable prose** (docs, specs, principles),
**machine-readable indexes** (`graph.json`, `behavior.json`, `findings.json`),
**append-only governance logs** (`*-resolutions.jsonl`), and **tracking dotfiles**
that let skills do incremental (git-diff-scoped) updates instead of full re-scans.

> "The freya-devkit skills now read and write their generated artifacts under a
> single `knowledge-base/` root instead of scattering them under `docs/`. This
> changes **where** skills read/write, never **what** they do."
> — `docs/migrations/knowledge-base.md`

### Canonical layout

From `docs/conventions.md` ("Artifact Location Convention") and `skills/spec-manager/SKILL.md`:

```
knowledge-base/
├── README.md                       ← docs-manager (documentation index)
├── principles.md                   ← spec-manager (project constitution)
├── BACKLOG.md                      ← status (generated, "do not edit")
├── reference/                      ← docs-manager (ARCHITECTURE.md, API.md, …)
├── specs/                          ← spec-manager (per-feature intent)
│   ├── README.md
│   ├── auth/  api/  data/  features/  infra/  integration/  ui/
│   └── .spec-last-update           ← spec-manager tracking dotfile
├── decisions/                      ← spec-manager (cross-cutting ADR-*.md + README.md)
├── intents/                        ← spec-manager (INTENT-NNN.md + .intent-last-verified)
├── security/                       ← codebase-security-scan
│   ├── codebase-security/
│   │   ├── <YYYY-MM-DD>.md          ← prose report (dated, overwritten same day)
│   │   └── findings.json            ← machine-readable findings index
│   └── .security-last-scan          ← security tracking dotfile
├── principle-resolutions.jsonl      ← spec-manager (G2 governance log)
├── contradiction-resolutions.jsonl  ← spec-manager (G3 governance log)
├── drift-resolutions.jsonl          ← spec-manager (P4b governance log)
└── .graph/                          ← code-graph + behavior-graph (generated cache)
    ├── graph.json                   ← code-graph dependency graph
    ├── classifications.json         ← code-graph directory classifications
    ├── behavior.json                ← behavior-graph (BEHAVIOR→TEST→CODE projection)
    └── .gitignore ("*")             ← auto-written by behavior-graph
```

Ownership summary (who *writes* what):

| Artifact | Owner skill | Machine/prose |
|---|---|---|
| `README.md`, `reference/*.md` | docs-manager | prose |
| `principles.md`, `specs/**`, `decisions/**`, `intents/**` | spec-manager | prose |
| `*-resolutions.jsonl` (principle/contradiction/drift) | spec-manager | machine (JSONL) |
| `.graph/graph.json`, `.graph/classifications.json` | code-graph | machine |
| `.graph/behavior.json` | behavior-graph | machine |
| `security/codebase-security/<date>.md` + `findings.json` | codebase-security-scan | prose + machine |
| `BACKLOG.md` | status | prose (generated) |
| `.spec-last-update` | spec-manager | tracking |
| `.security-last-scan` | codebase-security-scan | tracking |
| `.intent-last-verified` | spec-manager | tracking |
| `.graph/graph.json` `commit` field | code-graph | tracking (embedded) |

---

## 2. Why it exists

Three reasons, all traceable to source:

1. **Single shared substrate for skill composition.** The skills form a tiered
   graph (`docs/architecture.md`): code-graph is the foundation; docs-manager and
   spec-manager consume it; security-scan consumes both; wrap-up orchestrates all.
   They cooperate by reading each other's on-disk artifacts rather than calling
   each other's code. Example: security-scan reads `specs/` to mark a finding
   "intentional"; status reads `findings.json` + `behavior.json` + specs to build
   the backlog.

2. **Version control + branch sync.** Keeping the graph "inside the project under
   `knowledge-base/` … so it stays version-controlled and in sync with branch
   changes" (`graph-schema.md`). Prose artifacts (specs, docs, ADRs) are meant to
   be committed and reviewed alongside code.

3. **Incremental updates.** Tracking dotfiles record the last-processed commit so
   `update` commands can run `git diff <last>..HEAD` and only reprocess what
   changed, instead of full re-scans (`docs/conventions.md` "Incremental Update
   Convention"; `docs/architecture.md` "Tracking Files").

---

## 3. The artifacts in detail

### 3.1 `graph.json` — the dependency graph (code-graph)

**Path:** `knowledge-base/.graph/graph.json`. **Schema:**
`skills/code-graph/references/graph-schema.md`.

Top-level fields: `version` (const `1`), `commit` (git hash graph was built from,
optional/null outside git), `timestamp` (ISO-8601), `project_root` (absolute
path), `files` (map of project-relative path → `FileInfo`).

Each `FileInfo`: `exports[]`, `imports[]` (required), `dependents[]` (required,
reverse of imports), `category` (`auth|api|data|ui|infra|util|config|test|unknown`),
`language` (`typescript|javascript|python|go`).

Import prefixes are load-bearing for consumers:
- `external:<pkg>` — external package import.
- `unresolved:<path>` — a relative/aliased import the resolver couldn't map to a
  real file (kept, not silently dropped).
- An import is **internal** (real project wiring) only when it carries *neither*
  prefix. This is the predicate `spec-manager bootstrap`'s shape detector uses to
  count internal edges.

The `commit` field doubles as the graph's own tracking marker (`docs/architecture.md`
Tracking Files table: "`graph.json` → `commit` field | code-graph | Commit graph
was built from").

**Written by:** `/freya-devkit:code-graph build` (full) / `update` (git-diff
incremental). **Read by:** docs-manager, spec-manager, security-scan (for impact/
blast-radius), behavior-runner (for the static import closure), behavior-graph
(for impact + the set of tracked source files).

Sidecar `classifications.json` (same dir): `version`, `classified_at`,
`project_context` (framework/language/package-manager), and cached
source/exclude directory classifications so re-scans skip re-classifying.

### 3.2 `reference/` + `README.md` — project docs (docs-manager)

**Paths:** `knowledge-base/README.md` (index, stays at root) and
`knowledge-base/reference/*.md`. docs-manager "owns `README.md` and `reference/`"
(`skills/docs-manager/SKILL.md`).

Standard `reference/` files (created only if relevant to the detected project):
`PROJECT_OVERVIEW.md`, `ARCHITECTURE.md`, `DATABASE.md`, `API.md`,
`ENVIRONMENT.md`, `DEPLOYMENT.md`, `DEVELOPER.md`, `TESTING.md`, `STYLE_GUIDE.md`,
`INFRASTRUCTURE.md`, `SECURITY.md`, `TROUBLESHOOTING.md`, `CHANGELOG.md`.

Produced by a **coordinator + parallel workers** architecture (one analysis agent,
then one worker per doc type). Uncollectable info becomes `[TODO: …]` placeholders,
resolved later in batched Q&A. Modes: `init`, `update`, `update <doc>`, `review`,
`sync`, `resolve`, `upgrade-diagrams`, `help`.

> Note: docs-manager's SKILL.md is internally inconsistent on the index path — the
> layout/prose say `knowledge-base/README.md`, but "Phase 3" and "Output Format"
> still say `docs/README.md`. The authoritative migrated path is
> `knowledge-base/README.md` (see gotchas).

### 3.3 `specs/`, `principles.md`, `decisions/`, `intents/` (spec-manager)

**`specs/`** — per-feature intent, organized by category subdir (`auth/`, `api/`,
`data/`, `features/`, `infra/`, `integration/`, `ui/`), each seeded with a
`.gitkeep`. Every spec is a markdown file with structured frontmatter
(`skills/spec-manager/references/spec-template.md`):

- Core: `id` (SPEC-NNN), `title`, `category`, `tags`, `status`
  (`draft|in-progress|implemented|deprecated`), `certainty` (0–100), `created`,
  `updated`, `related_code[]`, `intentional_decisions[]`.
- `behaviors[]` — first-class **Behavior records** (the behavior layer's source of
  truth). Each: `behavior_id` (BEH-NNN, never renumbered), `title`, `state`
  (`proposed|confirmed|accepted|quarantined|deprecated`), `level`
  (`unit|component|integration|e2e`), `adapter`
  (`cucumber|behave|pytest-bdd|jest|playwright|pytest|manual`), `locator`
  (test location), `entry` (required for `integration` level — the route/handler
  file), optional `spec_id`.

State semantics matter downstream: `proposed` = inferred candidate; `confirmed` =
human confirmed intent but test owed (advisory, never gates); `accepted` = confirmed
intent with a real linked test (authoritative, gates on failure).

**`principles.md`** — the "project constitution … the highest-authority intent
record." Created from `references/principles-template.md` on `init`.

**`decisions/`** — cross-cutting ADRs (`ADR-*.md` + a generated `README.md` index).

**`intents/`** — `INTENT-NNN.md` records that authorize a change to an accepted
behavior's test, plus the `.intent-last-verified` marker.

**`certainty` (0–100)** gates review of `scan`-inferred specs and backs declarative
decisions. Post-behavior-layer, it is *not* the trust signal for executable
behaviors — that is the behavior lifecycle `state`.

**Written by:** spec-manager (`init`, `bootstrap`, `create`, `scan`, `update`,
`intent new`, `adr create`). **Read by:** security-scan (intentional-design
cross-reference), behavior-graph / behavior-runner (parse `behaviors[]` frontmatter),
status (behavior census).

### 3.4 Governance JSONL logs (spec-manager)

Three **append-only JSONL** files at the `knowledge-base/` root, all backed by the
shared `resolution_log.py` core:

| File | Owner module | Purpose |
|---|---|---|
| `principle-resolutions.jsonl` | `principles.py` (G2) | resolutions of principle checks |
| `contradiction-resolutions.jsonl` | `contradictions.py` (G3) | resolutions of spec/principle contradictions |
| `drift-resolutions.jsonl` | `drift.py` (P4b) | resolutions of declarative-drift findings |

`resolution_log.py` provides `append(path, record)` (one JSON line, sorted keys),
`load(path, label)` → `(records, warnings)` (skips malformed lines with a warning;
missing file → empty), and `active(records, keys_of, want)` (latest record per key,
dropping `superseded` verdicts). Each caller keeps its own RELPATH, verdicts, and
record schema; only the mechanics are shared.

### 3.5 `behavior.json` — the behavior graph (behavior-graph)

**Path:** `knowledge-base/.graph/behavior.json`, "sibling to `graph.json`". A
**generated projection**: `BEHAVIOR → TEST → CODE`.

Shape (`build()` in `behavior_graph.py`):
```json
{ "version": 1, "commit": "<hash>", "behaviors": {
  "BEH-003": {
    "spec_id": "SPEC-002", "state": "accepted",
    "level": "unit", "adapter": "vitest", "locator": "...",
    "coverage": "observed",
    "exercises": [ {"path": "src/x.ts", "source": "observed",
                    "confidence": 0.8, "freshness": "<commit>"} ]
  } } }
```

How it is built:
1. **Project** spec frontmatter — include every `accepted` *or* `confirmed`
   behavior (`proposed` excluded), pulling `state`, `level`, `adapter`, `locator`.
2. **Run** behavior-runner (`--emit-fingerprints`, states `accepted confirmed`) to
   get per-behavior coverage fingerprints.
3. **Merge by trust:** `observed` > `static`; a `static` run never downgrades a
   prior `observed`; `unknown` + `reason: test-failed` **invalidates**; any other
   `unknown` **preserves** the prior fingerprint.

Coverage vocabulary (`run_behaviors.py`): `observed` (real runner V8/istanbul
coverage, confidence 0.8), `static` (code-graph transitive import closure of the
declared `entry`, confidence 0.5), `unknown` (no keys — carries a `reason` like
`test-failed`, `no-entry`, `entry-missing`, `no-graph`, `no-coverage`,
`level-deferred`, `not-run`).

Each `exercises` edge carries `freshness` (the commit it was captured at) — status
uses this to flag stale fingerprints (freshness ≠ current HEAD).

**Written by:** `/freya-devkit:behavior-graph --build` and `--check`. **Read by:**
behavior-graph queries (`--affected`, `--implements`, `--gaps`, `--covering`,
`--surface`), status (stale-fingerprint bucket), security-scan (via `--covering`,
which returns only `accepted` behaviors as the strongest "intentional" evidence).

Confirmed behaviors are **advisory**: they are projected and appear in queries but
the runner never executes them, so they only ever carry `static`/`unknown` — never
`test-failed` — and thus never block the regression `--check`.

### 3.6 Security artifacts (codebase-security-scan)

Two files per scan, both under `knowledge-base/security/codebase-security/`:

- **Prose report:** `<YYYY-MM-DD>.md`. Same date = same file, **always
  overwritten** (no `-2`/`-3` suffixes; history via git).
- **`findings.json`** (`skills/codebase-security-scan/references/findings-schema.md`)
  — machine-readable index written *alongside* the prose report, "git-tracked," so
  other skills read findings without parsing prose. Shape:
  ```json
  { "version": 1, "scanned_commit": "<HEAD short hash>",
    "report": "knowledge-base/security/codebase-security/<YYYY-MM-DD>.md",
    "findings": [ { "id": "SEC-001", "title": "...",
      "severity": "high|medium|low|info",
      "status": "open|resolved|intentional",
      "file": "src/...", "line": 42,
      "spec_ref": "SPEC-001", "behavior_ref": "BEH-003" } ] }
  ```
  `status: intentional` means explained by intent — either a declarative `spec_ref`
  (prose claim) or an `accepted`, test-backed `behavior_ref` (the stronger,
  verified evidence). "Consumers treat any finding whose `status` is not `open` as
  not outstanding."

**Read by:** status (`security_bucket` reads `findings.json`, surfaces `open` ones),
codebase-security-resolver (works the findings), spec-manager (cross-references).

### 3.7 `BACKLOG.md` — the status rollup (status)

**Path:** `knowledge-base/BACKLOG.md`. A **generated, git-tracked** file carrying
the header `"Generated by /freya-devkit:status — **do not edit**; run status to
refresh."` (`collect_status.py::render_backlog`).

`collect_status.py` aggregates, read-only, from every other artifact and degrades
independently per source (missing graph/findings/specs → empty bucket + a note,
never a crash):
- Behavior census + intent/test-owed worklists ← `specs/` frontmatter.
- Coverage gaps ← `behavior-graph --gaps`.
- Verify failures ← spec-manager `verify_links.py`.
- Stale fingerprints ← `behavior.json` (freshness ≠ HEAD).
- Open security findings ← `findings.json`.

Modes (`status`): with `--write-backlog` it (re)writes `BACKLOG.md`; without, it
prints the summary only. `status` "mutates nothing except, on request, the
generated `knowledge-base/BACKLOG.md`." It is the read-only "check-counterpart of
wrap-up."

### 3.8 Tracking dotfiles

| File | Location | Owner | Content |
|---|---|---|---|
| `.spec-last-update` | `knowledge-base/specs/` | spec-manager | `commit`, `timestamp`, `specs_updated`, `specs_created` |
| `.security-last-scan` | `knowledge-base/security/` | codebase-security-scan | `commit`, `timestamp`, `files_scanned`, `findings`, `scan_type` (`incremental`/`audit`) |
| `.intent-last-verified` | `knowledge-base/intents/` | spec-manager | declared-intent baseline commit (advanced by `verify_intent.py --advance`) |
| `graph.json` `commit` field | `knowledge-base/.graph/` | code-graph | embedded last-built commit |

Convention (`docs/conventions.md`): "Read state at start … Write state at end … If
no tracking file exists, performs full scan like `scan` command." All support
git-aware `update`.

---

## 4. Pipeline: how the artifacts get produced together (wrap-up)

`wrap-up` orchestrates the artifact refresh after a feature is implemented
(`skills/wrap-up/SKILL.md`), following the **two-commit pattern** (code separate
from generated artifacts — `docs/conventions.md` / user CLAUDE.md Core Patterns):

1. **Phase 1** — `/freya-devkit:code-graph update` → refresh `graph.json` (so
   downstream impact analysis is accurate).
2. **Phase 2** — docs-manager `update` → `reference/` + `README.md`.
3. **Phase 3** — spec-manager `update` → `specs/` + `.spec-last-update`.
4. Governance/behavior steps → `*-resolutions.jsonl`, `behavior.json`, `intents/`.
5. Security scan `update` → dated report + `findings.json` + `.security-last-scan`.
6. **Refresh backlog** — `collect_status.py --write-backlog` → `BACKLOG.md`.
7. **Artifacts commit (commit 2)** — stage docs, specs, security report, updated
   graph, tracking files, `BACKLOG.md`, ADRs, `drift-resolutions.jsonl`, and
   `proposed`/unaccepted behavior scaffolds still carrying `TODO(scaffold)`.

Commit-class rule (`wrap-up` SKILL.md): a behavior scaffold's commit class follows
its **lifecycle `state`, not its file location**. An `accepted` behavior's real
test is *code* (commit 1); a `proposed`/`TODO(scaffold)` behavior is *intent under
review* (commit 2) even though it sits under `features/`.

**Never-synced guard (F5):** if a project has no tracking files (`.spec-last-update`,
`.graph/`, `.security-last-scan`), wrap-up must **not** let `update` silently run a
full-codebase generation — it reports the project is unsynced and defers to the
explicit first-time command (`scan`/`build`).

---

## 5. Composition / dependency map (who reads whom)

```
code-graph ──graph.json──▶ docs-manager, spec-manager, security-scan,
                           behavior-runner (static closure), behavior-graph (impact)
spec-manager ──specs/──▶   behavior-graph, behavior-runner (parse behaviors),
                           security-scan (intentional), status (census)
behavior-runner ──fingerprints──▶ behavior-graph (merge → behavior.json)
behavior-graph ──behavior.json──▶ status (stale), security-scan (--covering)
security-scan ──findings.json──▶ status (open findings), security-resolver
status ──reads all──▶ BACKLOG.md
wrap-up ──orchestrates──▶ all of the above, two-commit
```

---

## 6. Degradation behavior

Every consumer is designed to degrade, not crash, when an artifact is missing:

- **No `graph.json`:** code-graph consumers fall back to raw `git diff` (directly
  changed files only), warning "code-graph not available — reduced coverage"
  (`docs/conventions.md`, `docs/architecture.md`). behavior-runner returns
  `coverage: unknown, reason: no-graph`; behavior-graph `surface`/`gaps` return a
  `note` and skip.
- **No tracking dotfile:** `update` falls back to full `scan`/`build` — *except*
  under wrap-up, where the never-synced guard blocks the surprise full generation.
- **No `findings.json` / `behavior.json` / specs:** status returns an empty bucket
  plus an explanatory `note` ("no findings.json — run codebase-security-scan",
  "no behavior.json — run behavior-graph --build") and never fails.
- **Malformed JSONL line:** `resolution_log.load` skips it with a warning, keeps
  going.
- **Malformed JSON graph/behavior file:** readers catch `JSONDecodeError`/`OSError`
  and return empty rather than propagating.
- **spec search legacy fallback:** spec-manager keeps a legacy `docs/specs` read
  fallback so a not-yet-migrated project stays readable, but **all writes go to
  `knowledge-base/`** (`docs/migrations/knowledge-base.md`).

---

## 7. Migration (old `docs/` layout → `knowledge-base/`)

`docs/migrations/knowledge-base.md` maps old→new and provides an **idempotent**
recipe (each `git mv` is a no-op if the source is absent):

| Old | New |
|---|---|
| `docs/specs/` | `knowledge-base/specs/` |
| `docs/project/` | `knowledge-base/reference/` |
| `docs/security-reports/` | `knowledge-base/security/` |
| `docs/.code-graph/` | `knowledge-base/.graph/` |
| `docs/README.md` (generated) | `knowledge-base/README.md` |
| — (new) | `knowledge-base/principles.md` |
| — (new) | `knowledge-base/decisions/` |

The graph is treated as a regenerable cache: "delete the old one and rebuild" (`rm
-rf docs/.code-graph` then `/freya-devkit:code-graph build`) rather than moved — "it
is a cache keyed to a commit; rebuilding is cheaper and safer than moving it."

---

## 8. Git-tracking status (what's committed vs ignored)

This is subtle and slightly contradictory across sources:

- **`.graph/graph.json` + `classifications.json`:** graph-schema.md and code-graph
  SKILL.md say the graph is stored inside the project "so it stays version-controlled"
  but **also** say "Add `knowledge-base/.graph/` to `.gitignore` if you prefer not to
  commit." So committing the graph is *optional/user choice.*
- **`.graph/behavior.json`:** `behavior_graph.py::write_behavior_json` **auto-writes
  a `.gitignore` containing `*`** into `.graph/` on every build. This means once the
  behavior graph is built, the *entire `.graph/` directory is git-ignored by default*
  — including `graph.json`. (Gotcha: this overrides the "version-controlled" framing
  above; the `.graph/` cache is effectively local-only unless force-added.)
- **This repo's own `.gitignore`** ignores the *old* `docs/.code-graph/` and
  `**/.code-graph/` paths (pre-migration names), not `knowledge-base/.graph/`.
- **`findings.json`, `BACKLOG.md`, specs, docs, principles, ADRs, resolution logs,
  intents, tracking dotfiles:** intended to be **git-tracked** and committed as the
  "artifacts" commit by wrap-up.

---

## 9. Honest limits / gotchas

- **UNVERIFIED — docs-manager index path inconsistency:** SKILL.md's Phase 3 and
  Output Format still reference `docs/README.md`, while the layout and migration doc
  say `knowledge-base/README.md`. The migrated, authoritative path is
  `knowledge-base/README.md`; the `docs/` mentions look like un-migrated leftovers.
- **`.graph/` git status is genuinely ambiguous.** The schema doc calls the graph
  "version-controlled," but behavior-graph auto-ignores the whole `.graph/` dir via a
  `*` `.gitignore`. Treat `.graph/` as a **regenerable local cache** in practice.
- **behavior-runner is partially implemented.** The `unit` level uses vitest
  (in-process, V8/istanbul coverage) and `integration` uses a static code-graph
  closure. Other levels (`component`, `e2e`) return `reason: level-deferred` — "added
  in later plans" (`run_behaviors.py` docstring). So `behavior.json` coverage is only
  as complete as the implemented levels.
- **Freshness is snapshot-based.** behavior-graph Direction A/B queries "reflect the
  last `--build` snapshot — re-run `--build` after spec or code changes to refresh"
  (`skills/behavior-graph/SKILL.md`). Stale fingerprints are only *reported* (by
  status), not auto-refreshed.
- **`graph.json` `commit` may be null** outside a git repo; consumers must tolerate
  its absence.
- **Absolute-path leakage:** `graph.json` stores `project_root` as an absolute path,
  and `classifications.json` embeds machine context — a reason the `.graph/` cache is
  reasonably kept out of version control.
- **Category/language enums are fixed.** graph.json `category` is one of a closed set
  (`auth|api|data|ui|infra|util|config|test|unknown`) and `language` covers only
  `typescript|javascript|python|go` — other stacks fall to `unknown`/absent.
- **`docs/conventions.md` uses pre-migration example paths** in some snippets (e.g.
  `docs/.my-skill-last-update`, `knowledge-base/security/codebase-security/2024-03-27.md`
  vs the generic `<scanner-name>/YYYY-MM-DD.md` layout). The dated-report and
  tracking-file *conventions* are current; treat specific example paths as
  illustrative.
