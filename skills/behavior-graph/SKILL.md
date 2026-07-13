---
name: behavior-graph
description: |
  Own behavior.json (the BEHAVIOR -> TEST -> CODE projection) and answer the two
  blast-radius directions: code change -> affected behaviors, and behavior ->
  implementing code. Pure graph layer over code-graph + behavior-runner.

  TRIGGER when: building/refreshing the behavior graph, asking which behaviors a
  code change affects, or which code implements a behavior. Used by wrap-up and
  brainstorming.
---

# Behavior Graph

Owns `behavior.json` (a **generated** projection at `knowledge-base/.graph/behavior.json`,
sibling to `graph.json`). It projects spec frontmatter, orchestrates `behavior-runner`
for coverage fingerprints, **merges by trust** (`observed > static`), and serves:

- **Direction A** — `affected <changed-files>`: which accepted or confirmed behaviors a code change touches.
- **Direction B** — `implements <BEH-NNN>`: which code a behavior exercises.

> **Freshness note:** Direction A and B query results reflect the last `--build` snapshot — re-run `--build` after spec or code changes to refresh.

It is the pure graph layer (vision §5b): it *queries* `code-graph` (`--impact`) and
`behavior-runner` (`--emit-fingerprints`); `code-graph` stays unaware of behaviors.

## Merge by trust

| Incoming run | Result |
|---|---|
| `observed` | take it (highest trust) |
| `static` | take it, unless the prior edge was `observed` (don't downgrade) |
| `unknown` + `reason: test-failed` | **invalidate** (the test is red) |
| `unknown` + any other reason | **preserve** the prior fingerprint |

> **Confirmed behaviors are advisory.** `confirmed` behaviors (intent confirmed,
> test owed) are projected into `behavior.json` and surface in Direction A/B, but
> the runner never executes them, so they only ever carry a `static` or `unknown`
> fingerprint — never `test-failed`. The regression `--check` therefore never
> blocks on a confirmed behavior; only `accepted` behaviors gate.

## Commands

Exactly **one mode per run** (mutually exclusive). `--check` and `--surface` also take `--base <commit>`.

```bash
# Build/refresh behavior.json (projects specs, runs behaviors, merges):
python "${CLAUDE_PLUGIN_ROOT}/skills/behavior-graph/scripts/behavior_graph.py" --build --project /path/to/project

# Direction A — which behaviors does a code change touch:
python "${CLAUDE_PLUGIN_ROOT}/skills/behavior-graph/scripts/behavior_graph.py" --affected lib/webauthn.ts --project /path/to/project

# Direction B — which code does a behavior exercise:
python "${CLAUDE_PLUGIN_ROOT}/skills/behavior-graph/scripts/behavior_graph.py" --implements BEH-003 --project /path/to/project

# Regression check (wrap-up Phase 3.5) — re-run affected accepted behaviors for base..HEAD; exit 1 on a test-failed:
python "${CLAUDE_PLUGIN_ROOT}/skills/behavior-graph/scripts/behavior_graph.py" --check --base <commit> --project /path/to/project

# Validate-on-hit — surface affected proposed/confirmed behaviors (+ recall gaps) for base..HEAD; advisory, never blocks:
python "${CLAUDE_PLUGIN_ROOT}/skills/behavior-graph/scripts/behavior_graph.py" --surface --base <commit> --project /path/to/project

# Whole-repo uncovered-code audit (source files no behavior covers):
python "${CLAUDE_PLUGIN_ROOT}/skills/behavior-graph/scripts/behavior_graph.py" --gaps --project /path/to/project

# Security cross-ref — accepted behaviors whose exercised code includes FILE:
python "${CLAUDE_PLUGIN_ROOT}/skills/behavior-graph/scripts/behavior_graph.py" --covering lib/webauthn.ts --project /path/to/project
```
