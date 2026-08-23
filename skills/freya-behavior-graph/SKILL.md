---
name: freya-behavior-graph
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

## Artifacts, not commits

Write the artifacts this skill owns. **Do not stage or commit them** — that is
`freya-wrap-up`'s job. The two-commit pattern keeps code changes in one commit and
generated artifacts in another, and the user decides when the second happens.
Phase 6 validation observed an agent with broad tool permissions infer a `git commit`
that no skill had asked for, in a repository it had only been asked to read.

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
freya behavior-graph --build --project /path/to/project

# Direction A — which behaviors does a code change touch:
freya behavior-graph --affected lib/webauthn.ts --project /path/to/project

# Direction B — which code does a behavior exercise:
freya behavior-graph --implements BEH-003 --project /path/to/project

# Regression check (wrap-up Phase 3.5) — re-run affected accepted behaviors for base..HEAD; exit 1 on a test-failed:
freya behavior-graph --check --base <commit> --project /path/to/project

# Validate-on-hit — surface affected proposed/confirmed behaviors (+ recall gaps) for base..HEAD; advisory, never blocks:
freya behavior-graph --surface --base <commit> --project /path/to/project

# Whole-repo uncovered-code audit (source files no behavior covers):
freya behavior-graph --gaps --project /path/to/project

# Security cross-ref — accepted behaviors whose exercised code includes FILE:
freya behavior-graph --covering lib/webauthn.ts --project /path/to/project
```

## What `--covering` answers, and what it does not

`--covering` is the one query whose answer licenses a security finding to be downgraded, so
it labels its own evidence rather than leaving the caller to guess. Real output of the
command above, against a project with one accepted behavior over `lib/webauthn.ts`:

```json
{
  "version": 1,
  "file": "lib/webauthn.ts",
  "covering": [
    {
      "behavior_id": "BEH-003",
      "spec_id": "SPEC-004",
      "coverage": "observed",
      "locator": "tests/webauthn.spec.ts::logs in with a passkey"
    }
  ],
  "evidence": "state and locator re-derived from knowledge-base/specs; exercised paths and coverage read from the project's committed knowledge-base/.graph/behavior.json. No test was run by this query, so this is a label on the evidence, not a verification of it."
}
```

`state`, `spec_id` and `locator` are re-read from the spec frontmatter, not taken from
`behavior.json`, and a declared locator that does not resolve to a file inside the project
drops the row. So a behavior demoted to `proposed`, or one whose test file was renamed,
stops licensing a downgrade at the *next query* rather than at the next `--build`. A row can
therefore disappear between two runs with no code change: that is the check working.

**The locator check only runs on a locator that is there.** `covering()` never reads
`adapter`, so a behavior declaring none skips the check entirely — measured 2026-08-23,
`state: accepted, adapter: vitest` with no locator is refused by `verify_links` at Tier 1
(`missing-locator`) and returned here, as a row with `"locator": null`. Read that null as
"nothing was checked", not as "nothing to check".

**No test is run by this query.** Both inputs belong to the project being scanned, and the
only evidence that would not be is executing that project's suite. `evidence` says as much
in one sentence, and the caller is expected to carry that sentence into the report a human
reads — see `freya-codebase-security-scan`, `check-specs` Phase 3.
