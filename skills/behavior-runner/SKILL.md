---
name: behavior-runner
description: |
  Run a project's accepted behaviors via their adapter and capture observed
  coverage as TEST -> CODE fingerprints. Producer for the behavior graph.

  TRIGGER when: running accepted behaviors, capturing behavior coverage, or
  refreshing behavior fingerprints. Used by behavior-graph and wrap-up.
---

# Behavior Runner

Runs **accepted, non-quarantined** behaviors through their adapter and emits
`observed` coverage fingerprints (the `TEST -> CODE` `exercises` edges). It is a
**producer**: it prints fingerprints as JSON; it never writes `behavior.json`
(that is `behavior-graph`).

Coverage capture is **per level** (vision: test-level-agnostic):

| Level | Mechanism |
|-------|-----------|
| `unit` / `component` | in-process, runner-native V8 coverage (vitest/jest) |
| `integration` | running app over HTTP; observed coverage is a deferred per-framework V8+CDP adapter, so the **static** code-graph closure of a declared **entry** is used (source: static) |
| `e2e` | browser (later plan) |

### Confirmed behaviors (advisory)

A `confirmed` behavior (intent confirmed, test owed — see the lifecycle in
spec-manager) has **no executable test yet**, so the runner never executes it.
When it declares an `entry` it gets an advisory **static** fingerprint (the
code-graph closure of that entry); with no `entry` it is `unknown` / `no-entry`.
Because it is never executed it can never be `test-failed`, so it never gates
wrap-up. Select confirmed behaviors with `--states accepted confirmed`; the
default is `accepted` only, so the wrap-up "run accepted behaviors" path stays
accepted-only.

## Commands

> **Note:** Only the `vitest` unit path is implemented so far. jest and other
> adapters are handled in later plans; behaviors using them are emitted with
> `coverage: "unknown"` and `reason: "level-deferred"`.

### `run` (default)
Emit fingerprints for accepted behaviors:
```bash
python "${CLAUDE_PLUGIN_ROOT}/skills/behavior-runner/scripts/run_behaviors.py" \
  --project /path/to/project --level unit --emit-fingerprints
```

### `--list`
List matching accepted behaviors without running them:
```bash
python "${CLAUDE_PLUGIN_ROOT}/skills/behavior-runner/scripts/run_behaviors.py" \
  --project /path/to/project --level unit --list
```

## Output (fingerprint contract)

```json
{
  "version": 1,
  "commit": "<project HEAD>",
  "fingerprints": {
    "BEH-002": {
      "coverage": "observed",
      "exercises": [
        { "path": "lib/webauthn.ts", "source": "observed", "confidence": 0.8, "freshness": "<commit>" }
      ]
    }
  }
}
```

A behavior with no usable coverage is emitted with `coverage: "unknown"` and an
empty `exercises` list — never falsely attributed.

The `coverage` field is one of `observed | static | unknown`:
- `observed` — captured at runtime from runner-native V8 coverage (unit/component).
- `static` — code-graph closure of a declared `entry` file (integration, static analysis only).
- `unknown` — no usable coverage produced.

Integration behaviors must declare an `entry` field (project-relative path to the route/handler entry file); its code-graph transitive import closure becomes `source: static` edges.

An `unknown` result may carry a `reason` field that discriminates the cause:

| `reason` | Meaning |
|----------|---------|
| `level-deferred` | Non-vitest/non-unit behavior — adapter not yet implemented |
| `test-failed` | vitest process exited non-zero |
| `no-coverage` | vitest passed but produced no coverage file (check `@vitest/coverage-v8` + json reporter config) |
| `no-entry` | Integration behavior has no `entry` field declared |
| `entry-missing` | Integration behavior declares an `entry` that does not exist on disk |
| `no-graph` | No built code-graph cache at this project (run `code-graph build` first) |
