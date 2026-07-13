# Research Brief 05 — Skill Reference (quick command reference)

**Source of record:** `docs/skill-reference.md`
**Corroborating sources:** `skills/*/SKILL.md` frontmatter and `## Commands` sections (read for discrepancy-checking).

---

## What it is

`docs/skill-reference.md` is the **quick command-reference sheet** for the whole
freya-devkit plugin. It is documentation, not code: a single flat page that, for
each skill, lists its purpose, trigger phrases, the sub-commands it accepts, its
output artifact path, and which other skills it uses / is used by. It closes with
three lookup tables: a skill-relationship diagram, a "Quick Decision Guide"
("I want to… → use this skill"), and a "File Locations" table mapping artifact
types to on-disk paths.

Its job is to be the **fast index** an engineer reaches for when they know *what
they want to do* but not *which skill / which sub-command* does it. The deeper
"why" lives in `philosophy.md` / `architecture.md`; this file is the lookup layer.

## Why it exists

Every skill in this plugin is invoked as a slash command with a sub-command
argument (e.g. `/freya-devkit:code-graph build`). Without a single index you would
have to open each `SKILL.md` to recall the exact verb. This page consolidates all
of that into one scannable table set.

## Invocation & namespacing (the load-bearing rule)

Verbatim from the top of the source:

> **Invocation & namespacing.** These skills ship as the `freya-devkit` plugin, so they are invoked with the plugin namespace: `/freya-devkit:<skill> [args]` (e.g. `/freya-devkit:code-graph build`). The bare `/code-graph` form only works for skills installed loose in `~/.claude/skills/`, not for plugin-installed skills.

Takeaway: **always prefix `/freya-devkit:`** for plugin-installed skills. The bare
form is only valid for loose `~/.claude/skills/` installs.

## The skills, as documented in skill-reference.md

The reference groups skills under "Core Skills". Exact command tables, verbatim:

### code-graph
- **Purpose:** Build and query code dependency graphs for impact analysis.
- **Triggers:** "dependencies", "impact analysis", "blast radius", "what depends on", "affected files"
- **Commands:** `build` (full scan) · `update` (incremental via git diff) · `query <file>` (deps + usages) · `impact <file>` (blast radius) · `dependents <file>` · `dependencies <file>`
- **Output:** `knowledge-base/.graph/graph.json`
- **Used by:** docs-manager, spec-manager, codebase-security-scan

### docs-manager
- **Purpose:** Create and maintain standardized project documentation.
- **Triggers:** "docs", "documentation", "create docs", "update docs", "architecture doc"
- **Commands:** `init` · `update` · `update <doc>` · `review` · `sync` (full re-analysis) · `resolve` (fill placeholders) · `upgrade-diagrams` (ASCII → mermaid)
- **Output:** `knowledge-base/reference/*.md`
- **Uses:** code-graph (optional, for impact-aware updates)

### spec-manager
- **Purpose:** Create and manage feature specifications with certainty scoring.
- **Triggers:** "specs", "specifications", "design decisions", "why was this done", "that's intentional"
- **Commands:** `init` · `create <name>` · `scan` · `update` · `update <spec>` · `verify` · `search <query>` · `review` (low-certainty specs) · `get <id>`
- **Output:** `knowledge-base/specs/` with category subdirectories
- **Uses:** code-graph (optional, for impact-aware updates)

### codebase-security-scan
- **Purpose:** Comprehensive security audit using parallel subagents.
- **Triggers:** "scan codebase for security", "security audit", "code security check"
- **Commands:** `scan` (full) · `update` (changed files only) · `impact <file>` · `check-specs` (cross-reference against specs)
- **Output:** `knowledge-base/security/codebase-security/YYYY-MM-DD.md`
- **Uses:** code-graph (impact analysis), spec-manager (intentional design)

### codebase-security-resolver
- **Purpose:** Fix security issues found by codebase-security-scan.
- **Triggers:** "fix security issues", "resolve security findings", "remediate vulnerabilities"
- **Workflow:** Reads security report, proposes fixes, applies with user approval.
- **Uses:** codebase-security-scan (reads reports)

### dependency-vulnerability-check
- **Purpose:** Check for known vulnerabilities in project dependencies.
- **Triggers:** "check dependencies", "vulnerability check", "supply chain security"
- **Scope:** package.json, requirements.txt, go.mod dependencies

### wrap-up
- **Purpose:** Complete post-implementation workflow in sequence.
- **Triggers:** "wrap up", "complete feature", "finish up", "done implementing"
- **Workflow (verbatim ordering):** 1. Commit code changes (if any) → 2. `/freya-devkit:code-graph update` → 3. `/freya-devkit:docs-manager update` → 4. `/freya-devkit:spec-manager update` → 5. `/freya-devkit:codebase-security-scan update` → 6. Commit artifacts
- **Uses:** All core skills (orchestrates them)

## Skill relationships (as drawn in the doc)

```
                    wrap-up
                       │
       ┌───────────────┼───────────────┐
       ▼               ▼               ▼
 code-graph    docs-manager    spec-manager
       │               │               │
       └───────────────┴───────────────┘
                       ▼
            codebase-security-scan
                       ▼
            codebase-security-resolver
```

Reading: `code-graph` is the foundation; docs-manager and spec-manager consume it;
codebase-security-scan consumes all three; codebase-security-resolver consumes the
scan's reports; `wrap-up` orchestrates the whole stack.

## Quick Decision Guide (verbatim mapping)

| I want to… | Skill |
|---|---|
| Understand code dependencies | `/freya-devkit:code-graph query <file>` |
| See what's affected by a change | `/freya-devkit:code-graph impact <file>` |
| Set up project docs | `/freya-devkit:docs-manager init` |
| Update docs after changes | `/freya-devkit:docs-manager update` |
| Create a feature spec | `/freya-devkit:spec-manager create <name>` |
| Generate specs from code | `/freya-devkit:spec-manager scan` |
| Check for security issues | `/freya-devkit:codebase-security-scan scan` |
| Fix security issues | `/freya-devkit:codebase-security-resolver` |
| Check dependencies for vulnerabilities | `/freya-devkit:dependency-vulnerability-check` |
| Finish implementing a feature | `/freya-devkit:wrap-up` |

## File Locations (verbatim)

| Type | Location |
|---|---|
| Dependency graph | `knowledge-base/.graph/graph.json` |
| Project docs | `knowledge-base/reference/*.md` |
| Feature specs | `knowledge-base/specs/<category>/SPEC-*.md` |
| Security reports | `knowledge-base/security/codebase-security/YYYY-MM-DD.md` |
| Spec tracking | `knowledge-base/specs/.spec-last-update` |
| Security tracking | `knowledge-base/security/.security-last-scan` |

## How it composes with other skills

The reference itself encodes the composition graph: it is the human-readable
counterpart to the dependency structure the skills declare in their `SKILL.md`
`Used by` / `Uses` fields. The canonical mental model (also in the global CLAUDE.md):
`code-graph` (foundation) → `docs-manager` / `spec-manager` → `codebase-security-scan`
→ `wrap-up` (orchestrator).

## Degradation behavior (as stated in the doc)

- docs-manager and spec-manager list code-graph as **optional** ("for impact-aware
  updates") — they degrade to non-impact-aware behavior if the graph is absent.
- The bare-namespace caveat is itself a degradation note: loose installs get `/code-graph`; plugin installs must use `/freya-devkit:code-graph`.

## Honest limits / gotchas

- **STALE DOC — missing skills.** The shipped plugin has **10** skills under
  `skills/` (`behavior-graph`, `behavior-runner`, `code-graph`,
  `codebase-security-resolver`, `codebase-security-scan`,
  `dependency-vulnerability-check`, `docs-manager`, `spec-manager`, `status`,
  `wrap-up`). `docs/skill-reference.md` documents only **7** — it omits
  `behavior-graph`, `behavior-runner`, and `status`. The reference page is out of
  date relative to the code. (Verified by listing `skills/` and reading the three
  omitted skills' `SKILL.md`.)
- **Omitted skills' commands (from their own SKILL.md, not from the reference):**
  - `status`: `status` (print summary + refresh `knowledge-base/BACKLOG.md`) · `gaps` (uncovered source files) · `review intent` · `review tests`. Read-only except it can regenerate the git-tracked `knowledge-base/BACKLOG.md`. It is described as "the check-counterpart of wrap-up".
  - `behavior-runner`: `run` (default) and `--list`; invoked as a Python script (`scripts/run_behaviors.py`); produces TEST→CODE fingerprints with statuses `observed` / `static` / `unknown`.
  - `behavior-graph`: `--build` (projects specs, runs behaviors, merges into `behavior.json`, a sibling to `graph.json`); invoked as `scripts/behavior_graph.py`.
  - These three are invoked via `python "${CLAUDE_PLUGIN_ROOT}/skills/.../scripts/...py"` rather than the tidy sub-command verbs the reference table shows for the older skills — the reference table's format does not cover them.
- **wrap-up ordering does not mention the behavior layer.** The documented
  6-step wrap-up sequence predates behavior-graph/behavior-runner/status and does
  not list them. UNVERIFIED whether the current wrap-up implementation actually
  runs the behavior layer; the reference doc does not say.
- **No flags documented.** The reference lists sub-command *verbs* only, not flags
  (e.g. `--build`, `--format json`, `--write-backlog` seen in the newer skills'
  SKILL.md are absent here). For exact flags, consult each skill's `SKILL.md`.
- The relationship diagram omits `dependency-vulnerability-check` entirely (it
  appears in the tables but not the ASCII graph).

## Verbatim quotable lines

- "Quick reference for all skills in the ecosystem."
- "These skills ship as the `freya-devkit` plugin, so they are invoked with the plugin namespace: `/freya-devkit:<skill> [args]`"
- "The bare `/code-graph` form only works for skills installed loose in `~/.claude/skills/`, not for plugin-installed skills."
- "**Uses**: All core skills (orchestrates them)" — (wrap-up)
- "**Purpose**: Comprehensive security audit using parallel subagents." — (codebase-security-scan)
