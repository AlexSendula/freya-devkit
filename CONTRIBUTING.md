# Contributing to freya-devkit

This repo is both a Claude Code **plugin** and its own **marketplace**. The skills live in `skills/`, the deep-audit Workflow in `workflows/`, and design documentation in `docs/`.

## Local development loop

Install the plugin from your local checkout so you experience exactly what consumers do:

```text
/plugin marketplace add /absolute/path/to/freya-devkit
/plugin install freya-devkit@freya-devkit
```

Edit a skill under `skills/<name>/SKILL.md`, then reload to pick up changes:

```text
/plugin marketplace update freya-devkit
```

Invoke skills with the plugin namespace, e.g. `/freya-devkit:code-graph help`.

## Conventions to preserve

- **Namespaced cross-references.** Skills call each other as `/freya-devkit:<skill>`, never the bare `/<skill>` form (bare names only resolve for loose `~/.claude/skills/` installs, not plugin installs).
- **Bundled script paths.** Reference bundled scripts via `${CLAUDE_PLUGIN_ROOT}`, e.g.
  `python "${CLAUDE_PLUGIN_ROOT}/skills/code-graph/scripts/graph_ops.py" ...`. Always quote (handles spaces in the install path).
- **The audit Workflow** is invoked via the Workflow tool's `scriptPath: "${CLAUDE_PLUGIN_ROOT}/workflows/codebase-security-audit.js"` — workflows are not an auto-registered plugin component. Keep the runtime constraints intact: plain JS, `meta` a pure literal, JSON-Schema schemas, no `Date.now()`/`Math.random()`/`new Date()`.
- **Additive report fields.** `codebase-security-resolver` parses security reports by required fields (ID, Severity, Title, file, Status, Recommendation). Keep any new fields additive so it doesn't break.

## Releasing updates

Consumers receive updates based on the `version` in `.claude-plugin/plugin.json`:

1. Bump `version` (semver) in `.claude-plugin/plugin.json`.
2. Commit and push.
3. Consumers run `/plugin marketplace update freya-devkit` to pull the new version.

If `version` is omitted, the git commit SHA is used and every commit looks like an update — so prefer bumping `version` deliberately per release.

## Design docs

Read these before making structural changes:

- [`docs/philosophy.md`](docs/philosophy.md) — why the skills exist, core concepts
- [`docs/architecture.md`](docs/architecture.md) — how skills connect, data flow
- [`docs/patterns.md`](docs/patterns.md) — reusable patterns
- [`docs/conventions.md`](docs/conventions.md) — integration guidelines
