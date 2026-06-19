# freya-devkit

An integrated, AI-assisted development toolkit for Claude Code. Seven skills that work together to keep your dependency graph, documentation, feature specs, and security posture in sync as you build — plus a one-command wrap-up workflow that runs them all.

## Install

```text
/plugin marketplace add AlexSendula/freya-devkit
/plugin install freya-devkit@freya-devkit
```

(For local development, see [CONTRIBUTING.md](CONTRIBUTING.md).)

Skills are invoked with the plugin namespace: **`/freya-devkit:<skill>`**.

## The skills

| Skill | Purpose | Example |
|-------|---------|---------|
| `code-graph` | Dependency graphs, impact analysis, blast radius | `/freya-devkit:code-graph impact src/auth.ts` |
| `docs-manager` | Standardized project documentation | `/freya-devkit:docs-manager update` |
| `spec-manager` | Feature specs capturing intentional design decisions | `/freya-devkit:spec-manager scan` |
| `codebase-security-scan` | Security auditing (with adversarial verification + deep `audit` mode) | `/freya-devkit:codebase-security-scan update` |
| `codebase-security-resolver` | Interactive fixing of security findings | `/freya-devkit:codebase-security-resolver` |
| `dependency-vulnerability-check` | Supply-chain / dependency CVE auditing | `/freya-devkit:dependency-vulnerability-check` |
| `wrap-up` | Post-implementation orchestrator (runs the above in sequence) | `/freya-devkit:wrap-up` |

## How they fit together

```
code-graph (foundation: dependency + blast-radius data)
    │
    ├─> docs-manager        (impact-aware doc updates)
    ├─> spec-manager        (impact-aware spec updates)
    └─> codebase-security-scan ──┐
                                 │ (specs reduce false positives)
        codebase-security-resolver (fixes findings, documents intentional ones)

wrap-up  ── orchestrates: code-graph → docs → specs → security, with a clean two-commit pattern
```

- **code-graph is the keystone.** The doc, spec, and security skills query it for blast radius and degrade gracefully to plain `git diff` when it's unavailable.
- **specs are the false-positive filter.** The security scan reads `/docs/specs/` and marks spec'd behavior as *intentional design* rather than a vulnerability.
- **incremental by default.** Each skill tracks the last processed commit and only reprocesses what changed.

## Core patterns

1. **Two-commit pattern** — code changes land in one commit; generated artifacts (graph, docs, specs, security reports) in a second.
2. **Incremental updates** — git-aware; only process what changed.
3. **Coordinator + parallel workers** — one agent plans, parallel workers execute.
4. **Certainty scoring** — AI-generated specs carry a 0–100 confidence score.

## Typical workflow

After implementing a feature:

```text
/freya-devkit:wrap-up
```

This runs `code-graph update` → `docs-manager update` → `spec-manager update` → `codebase-security-scan update`, then makes the two commits. Skip steps with `--no-security`, `--no-docs`, `--no-specs`, `--no-graph`.

For a deep, exhaustive security pass before a release:

```text
/freya-devkit:codebase-security-scan audit
```

## Documentation

Design rationale and architecture live in [`docs/`](docs/):

- [`philosophy.md`](docs/philosophy.md) — why these skills exist
- [`architecture.md`](docs/architecture.md) — how they connect, data flow
- [`patterns.md`](docs/patterns.md) — reusable patterns across skills
- [`conventions.md`](docs/conventions.md) — integration guidelines
- [`skill-reference.md`](docs/skill-reference.md) — quick command reference

## License

MIT — see [LICENSE](LICENSE).
