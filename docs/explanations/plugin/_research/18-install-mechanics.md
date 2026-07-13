# Install & Plugin Mechanics

Research brief for the freya-devkit plugin-wide explainer.
Topic: how freya-devkit is packaged, published as its own marketplace, installed, namespaced, developed locally, and how its bundled Workflow engine and `${CLAUDE_PLUGIN_ROOT}` path resolution work.

Sources read (all paths relative to repo root `/Users/main/Documents/projects/freya-devkit`):
- `README.md`
- `CONTRIBUTING.md`
- `.claude-plugin/plugin.json`
- `.claude-plugin/marketplace.json`
- `workflows/codebase-security-audit.js`
- `skills/codebase-security-scan/SKILL.md` (audit-mode invocation of the Workflow)
- `skills/*/SKILL.md` frontmatter (namespacing, `compatibility` fields)
- `.gitignore` (runtime marker + generated-artifact exclusions)
- `docs/conventions.md`, `docs/architecture.md` (namespaced cross-references)

---

## 1. What it is

freya-devkit is **simultaneously a Claude Code plugin and its own single-plugin marketplace**. One git repo serves both roles:

- The **plugin manifest** lives at `.claude-plugin/plugin.json`.
- The **marketplace manifest** lives at `.claude-plugin/marketplace.json`, and it lists exactly one plugin whose `source` is `"."` — i.e. the marketplace points back at the same repo root.

From `CONTRIBUTING.md` (verbatim):
> "This repo is both a Claude Code **plugin** and its own **marketplace**. The skills live in `skills/`, the deep-audit Workflow in `workflows/`, and design documentation in `docs/`."

The repo top level contains: `.claude-plugin/` (the two manifests), `skills/` (10 skill directories), `workflows/` (one bundled Workflow engine), `docs/`, `README.md`, `CONTRIBUTING.md`, `LICENSE`, `.gitignore`, and a runtime marker dir `.in_use/`.

The 10 skills present under `skills/`: `behavior-graph`, `behavior-runner`, `code-graph`, `codebase-security-resolver`, `codebase-security-scan`, `dependency-vulnerability-check`, `docs-manager`, `spec-manager`, `status`, `wrap-up`. (Note: the README's "seven skills" tagline predates the behavior-* and status additions — see Gotchas.)

## 2. The two manifests

### `.claude-plugin/plugin.json` (the plugin identity)
```json
{
  "name": "freya-devkit",
  "version": "0.1.0",
  "description": "An integrated AI-assisted development toolkit: dependency graphs, documentation, feature specs, security scanning/resolution, and a post-implementation wrap-up workflow that keeps them all in sync.",
  "author": { "name": "Alex", "email": "dev+github@alexsendula.com" },
  "license": "MIT",
  "keywords": ["skills", "code-graph", "dependencies", "documentation", "specs", "security", "workflow", "wrap-up"]
}
```
Key fields for mechanics: `name` (`freya-devkit`) and `version` (`0.1.0`, semver). The manifest does **not** explicitly enumerate skills or workflows — skills are auto-discovered from `skills/*/SKILL.md`; the Workflow is **not** auto-registered (see §6).

### `.claude-plugin/marketplace.json` (the marketplace catalog)
```json
{
  "name": "freya-devkit",
  "owner": { "name": "Alex", "email": "dev+github@alexsendula.com" },
  "description": "Freya devkit marketplace — the freya-devkit AI-assisted development plugin.",
  "plugins": [
    {
      "name": "freya-devkit",
      "source": ".",
      "description": "Dependency graphs, docs, specs, security scan/resolve, and a wrap-up workflow that keeps them in sync.",
      "category": "development",
      "tags": ["dependencies", "documentation", "specs", "security", "workflow"]
    }
  ]
}
```
The marketplace `name` and the single plugin `name` are **both** `freya-devkit`. `source: "."` means the plugin's files are the marketplace repo itself. This is why the install string reads `freya-devkit@freya-devkit` — that is `<plugin-name>@<marketplace-name>`, and here they happen to be identical.

## 3. How consumers install (exact CLI, verbatim)

From `README.md`:
```text
/plugin marketplace add AlexSendula/freya-devkit
/plugin install freya-devkit@freya-devkit
```

- `/plugin marketplace add AlexSendula/freya-devkit` — registers the marketplace from the GitHub `owner/repo` shorthand `AlexSendula/freya-devkit`.
- `/plugin install freya-devkit@freya-devkit` — installs the plugin named `freya-devkit` from the marketplace named `freya-devkit`.

## 4. Namespacing: `/freya-devkit:<skill>`

Once installed, **every** skill is invoked with the plugin namespace prefix. From `README.md`:
> "Skills are invoked with the plugin namespace: **`/freya-devkit:<skill>`**."

Examples (verbatim from README table): `/freya-devkit:code-graph impact src/auth.ts`, `/freya-devkit:docs-manager update`, `/freya-devkit:spec-manager scan`, `/freya-devkit:codebase-security-scan update`, `/freya-devkit:wrap-up`.

**Cross-references between skills must also be namespaced.** From `CONTRIBUTING.md` (verbatim):
> "**Namespaced cross-references.** Skills call each other as `/freya-devkit:<skill>`, never the bare `/<skill>` form (bare names only resolve for loose `~/.claude/skills/` installs, not plugin installs)."

This is enforced in practice: `skills/*/SKILL.md` frontmatter and `docs/conventions.md`/`docs/architecture.md` consistently write `/freya-devkit:code-graph`, `/freya-devkit:spec-manager`, `/freya-devkit:wrap-up`, etc. Example from `codebase-security-scan` frontmatter `compatibility:` line: `Optional: /freya-devkit:code-graph skill, /freya-devkit:spec-manager skill`.

The bare `/<skill>` form only worked in the older "loose" model where skills were dropped directly into `~/.claude/skills/`. Under a plugin install, bare names do not resolve, so all inter-skill calls carry the prefix.

## 5. Local development loop (symlink-style install from a checkout)

From `CONTRIBUTING.md`, the local-dev loop mirrors what consumers do, but points the marketplace at a local absolute path instead of the GitHub shorthand:
```text
/plugin marketplace add /absolute/path/to/freya-devkit
/plugin install freya-devkit@freya-devkit
```
> "Install the plugin from your local checkout so you experience exactly what consumers do."

Edit-and-reload cycle (verbatim):
> "Edit a skill under `skills/<name>/SKILL.md`, then reload to pick up changes:"
```text
/plugin marketplace update freya-devkit
```
And: "Invoke skills with the plugin namespace, e.g. `/freya-devkit:code-graph help`."

**Runtime marker (`.in_use/`).** The `.gitignore` documents a marker directory created by a local-dev symlink install:
> "# Plugin runtime marker (created when this repo is symlinked as a local-dev plugin install)" → ignores `.in_use/`

Observed in the working tree: `.in_use/` contains small (~52-byte) files named by numeric IDs (e.g. `20044`, `66086`) — these look like per-process/PID markers written when the repo is actively loaded as a symlinked plugin. This directory is git-ignored and is a side effect of local-dev installs, not a committed artifact. (Exact semantics of the marker files are UNVERIFIED — see Gotchas.)

**Cross-project memory note (external to this repo):** the user's global `~/.claude/CLAUDE.md` and auto-memory describe a Phase-1 dogfooding "local-dev symlink install (MUST REVERT before release)" and a "session-restart requirement for reloading plugin code." This corroborates that symlink installs are the local-dev mechanism and that a restart may be needed for code (script) changes. This detail comes from user memory, not repo files.

## 6. The Workflow engine (`workflows/codebase-security-audit.js`)

freya-devkit bundles **one** Workflow script: `workflows/codebase-security-audit.js`. It powers the `audit` mode of `/freya-devkit:codebase-security-scan` — an exhaustive, on-demand/pre-release security pass. It is separate from the lighter `scan`/`update` modes that run inline (and inside `wrap-up`).

**Workflows are NOT an auto-registered plugin component.** From `CONTRIBUTING.md` (verbatim):
> "**The audit Workflow** is invoked via the Workflow tool's `scriptPath: "${CLAUDE_PLUGIN_ROOT}/workflows/codebase-security-audit.js"` — workflows are not an auto-registered plugin component."

From `skills/codebase-security-scan/SKILL.md` (verbatim):
> "**Engine:** `${CLAUDE_PLUGIN_ROOT}/workflows/codebase-security-audit.js` — a saved Workflow script bundled with this plugin. Invoke it via the Workflow tool's `scriptPath` (workflows are not auto-registered as a plugin component, so name-based resolution won't find it). Fallback if `${CLAUDE_PLUGIN_ROOT}` doesn't resolve inside `scriptPath`: copy that file into your project's `.claude/workflows/` and invoke it by name (`codebase-security-audit`)."

So the invocation is: run the Workflow tool with `scriptPath: "${CLAUDE_PLUGIN_ROOT}/workflows/codebase-security-audit.js"`. Because a Workflow is not auto-discovered like a skill, you cannot call it by name from a plugin install — you must give the explicit `scriptPath`.

**Runtime constraints the Workflow must honor** (from its header comment and CONTRIBUTING, verbatim from the JS file):
> "Runtime constraints honored: plain JS (not TS); meta is a pure literal; schemas are JSON Schema; no Date.now()/Math.random()/new Date() (only Math.floor is used)."

CONTRIBUTING restates the same constraints: "plain JS, `meta` a pure literal, JSON-Schema schemas, no `Date.now()`/`Math.random()`/`new Date()`."

**Shape of the Workflow** (from `workflows/codebase-security-audit.js`): it exports a `meta` literal with `name`, `description`, and three `phases` (`Context`, `Discovery`, `Verify`). It uses helper primitives `phase()`, `agent()`, `parallel()`, `log()`, and `return`s structured data. Key constants: `CATEGORIES = ['auth','injection','secrets','api','config','file']`, `K_EMPTY = 2` (consecutive dry rounds to stop discovery), `MAX_ROUNDS = 5` (budget guard), `SKEPTICS = ['exploitability','compensating-controls','spec-intentional']`. All agents use `agentType: 'Explore'` (read-only Read/Grep/Glob, no Write) to enforce a no-file-writes boundary at the tool level.

**Division of labor (contract, verbatim from the JS header):**
> "this workflow RETURNS structured findings as JSON. It does NOT write the report, assign SEC-### IDs, or re-evaluate previous findings — the skill's main loop does all of that, so the report format stays identical and the resolver/check-specs keep working."

## 7. `${CLAUDE_PLUGIN_ROOT}` — how bundled files are addressed

`${CLAUDE_PLUGIN_ROOT}` is the environment variable that resolves to the plugin's install directory at runtime. It is the mechanism that lets skills reference bundled scripts and the Workflow regardless of where the plugin was installed (GitHub cache, local symlink, etc.).

From `CONTRIBUTING.md` (verbatim):
> "**Bundled script paths.** Reference bundled scripts via `${CLAUDE_PLUGIN_ROOT}`, e.g. `python \"${CLAUDE_PLUGIN_ROOT}/skills/code-graph/scripts/graph_ops.py\" ...`. Always quote (handles spaces in the install path)."

Usage is pervasive — 151 references across skills/workflows. Representative patterns:
- `python "${CLAUDE_PLUGIN_ROOT}/skills/spec-manager/scripts/verify_links.py" --format json` (from `wrap-up` and `spec-manager`)
- `python "${CLAUDE_PLUGIN_ROOT}/skills/behavior-graph/scripts/behavior_graph.py" ...` (from `wrap-up`)
- `python "${CLAUDE_PLUGIN_ROOT}/skills/status/scripts/collect_status.py" ...` (from `wrap-up`)
- Workflow: `scriptPath: "${CLAUDE_PLUGIN_ROOT}/workflows/codebase-security-audit.js"`

Convention: **always double-quote** the interpolated path so install paths containing spaces don't break the command.

## 8. Releasing / update propagation

From `CONTRIBUTING.md` (verbatim):
> "Consumers receive updates based on the `version` in `.claude-plugin/plugin.json`:
> 1. Bump `version` (semver) in `.claude-plugin/plugin.json`.
> 2. Commit and push.
> 3. Consumers run `/plugin marketplace update freya-devkit` to pull the new version."

Important nuance (verbatim):
> "If `version` is omitted, the git commit SHA is used and every commit looks like an update — so prefer bumping `version` deliberately per release."

So `/plugin marketplace update freya-devkit` is the single update command for both consumers (pull new released version) and local devs (reload after editing SKILL.md).

## 9. Inputs / outputs / artifacts (of install mechanics specifically)

- **Committed inputs** that define packaging: `.claude-plugin/plugin.json`, `.claude-plugin/marketplace.json`, `skills/*/SKILL.md` (+ their `scripts/`, `references/`, `evals/`), `workflows/codebase-security-audit.js`.
- **Runtime-generated / git-ignored** (from `.gitignore`): `__pycache__/`, `.DS_Store`, code-graph caches (`docs/.code-graph/`, `**/.code-graph/`), and the local-dev plugin marker `.in_use/`.
- The install mechanics themselves produce no committed artifacts in a consumer project — skills write their outputs (graphs, docs, specs, security reports) into the consumer's `knowledge-base/` etc., which is out of scope for this brief.

## 10. Composition with other skills

Install mechanics are the substrate every skill depends on:
- Namespacing (`/freya-devkit:<skill>`) is how `wrap-up` orchestrates `code-graph → docs-manager → spec-manager → codebase-security-scan`, and how `docs-manager`/`spec-manager`/`codebase-security-scan` optionally call `/freya-devkit:code-graph`.
- `${CLAUDE_PLUGIN_ROOT}` is how every SKILL.md locates its own bundled Python scripts.
- The Workflow engine is invoked only by `codebase-security-scan audit` mode; `wrap-up` deliberately uses the lighter `update` mode instead (Workflow-powered audit is not part of wrap-up).

## 11. Degradation behavior

- **Bare-name fallback:** bare `/<skill>` only resolves in a loose `~/.claude/skills/` install, not a plugin install; freya-devkit standardizes on namespaced calls so inter-skill references keep working under plugin installs.
- **Workflow `scriptPath` fallback:** if `${CLAUDE_PLUGIN_ROOT}` fails to resolve inside `scriptPath`, copy `codebase-security-audit.js` into the project's `.claude/workflows/` and invoke it by name (`codebase-security-audit`). (The global CLAUDE.md also notes a fallback copy is kept at `~/.claude/workflows/codebase-security-audit.js` — external to this repo.)
- **Missing `code-graph` skill:** dependent skills degrade to plain `git diff` analysis (documented in README §"How they fit together" and `docs/conventions.md`) — this is skill-level, not install-level, but is enabled by the optional-namespaced-call pattern.
- **Version omitted:** update propagation falls back to git SHA (every commit reads as an update).

## 12. Honest limits / gotchas

- **GOTCHA — README "seven skills" is stale.** README says "Seven skills" and lists 7, but `skills/` actually contains 10 directories (adds `behavior-graph`, `behavior-runner`, `status`). The extra skills are real (they appear in `wrap-up`'s pipeline and have SKILL.md frontmatter). Treat "seven" as marketing copy, not an inventory.
- **GOTCHA — `freya-devkit@freya-devkit` is not a typo.** It is `<plugin>@<marketplace>`; both names are `freya-devkit` by design (single-plugin, self-hosting marketplace with `source: "."`).
- **GOTCHA — Workflows are second-class vs skills.** Skills auto-register from `skills/*/SKILL.md`; the Workflow does **not** auto-register and must be called with an explicit `scriptPath`. Name-based resolution only works after the manual fallback copy into `.claude/workflows/`.
- **GOTCHA — always quote `${CLAUDE_PLUGIN_ROOT}`.** Unquoted usage breaks on install paths containing spaces (CONTRIBUTING is explicit about this).
- **UNVERIFIED — `.in_use/` marker file semantics.** The dir is a local-dev symlink-install runtime marker (per `.gitignore`), and its files appear PID-named (~52 bytes each), but the exact contents/lifecycle were not opened/confirmed from source. Do not assert internals.
- **UNVERIFIED — session-restart requirement.** User global memory states plugin *code* (script) changes need a session restart while SKILL.md prose reloads via `/plugin marketplace update`. This is not stated in the repo's own README/CONTRIBUTING; treat as external/user-environment guidance.
- **UNVERIFIED — `${CLAUDE_PLUGIN_ROOT}` resolution edge cases.** The docs anticipate it "doesn't resolve inside `scriptPath`" in some environments (hence the fallback), but the precise conditions are not documented in-repo.
- **Version is `0.1.0`** — pre-1.0; the repo is on branch `feat/behavior-layer` at time of writing, so some skills (behavior-*) are newer than the README's framing.

## 13. Quotable lines (verbatim, tagged)

- "This repo is both a Claude Code **plugin** and its own **marketplace**." — `CONTRIBUTING.md`
- "Skills are invoked with the plugin namespace: **`/freya-devkit:<skill>`**." — `README.md`
- "Skills call each other as `/freya-devkit:<skill>`, never the bare `/<skill>` form (bare names only resolve for loose `~/.claude/skills/` installs, not plugin installs)." — `CONTRIBUTING.md`
- "Reference bundled scripts via `${CLAUDE_PLUGIN_ROOT}` ... Always quote (handles spaces in the install path)." — `CONTRIBUTING.md`
- "workflows are not auto-registered as a plugin component, so name-based resolution won't find it." — `skills/codebase-security-scan/SKILL.md`
- "If `version` is omitted, the git commit SHA is used and every commit looks like an update — so prefer bumping `version` deliberately per release." — `CONTRIBUTING.md`
- "this workflow RETURNS structured findings as JSON. It does NOT write the report, assign SEC-### IDs, or re-evaluate previous findings — the skill's main loop does all of that." — `workflows/codebase-security-audit.js`
