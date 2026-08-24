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

# Security cross-ref — accepted behaviors whose exercised code includes FILE
# (add --verify to re-run each returned behavior's linked test instead of trusting the record):
freya behavior-graph --covering lib/webauthn.ts --project /path/to/project
```

`--check` and `--surface` both carry a **`skipped`** boolean. `skipped: true` means the run
selected nothing and ran nothing — git could not diff `base..HEAD`, or (for `--surface`) there
is no code-graph — and its `note` says which. Read it before trusting `--check`'s exit 0:
`0 affected, 0 failed` is what a clean change and an unresolvable `--base` both produce, and
`skipped` is the only field that tells them apart. A base git cannot resolve is a labelled
skip and not a block, per ADR-009's fail-open.

## What `--covering` answers, and what it does not

`--covering` is the one query whose answer licenses a security finding to be downgraded, so
it labels its own evidence rather than leaving the caller to guess. Real output, measured
2026-08-24 against a fixture with one accepted behavior whose passing pytest test exercises
`src/webauthn.py`:

```json
{
  "version": 1,
  "file": "src/webauthn.py",
  "covering": [
    {
      "behavior_id": "BEH-003",
      "spec_id": "SPEC-004",
      "coverage": "observed",
      "locator": "tests/test_webauthn.py::test_rejects_an_expired_challenge",
      "source": "observed",
      "symbols": ["verify_assertion"]
    }
  ],
  "verified": false,
  "evidence": "state and locator re-derived from knowledge-base/specs; only `source: observed` exercised paths counted, so a statically inferred edge licenses nothing. Exercised paths and symbols are read from the project's committed knowledge-base/.graph/behavior.json, which records that a test passed once — no test was run by this query, so this is a label on the evidence and not a verification of it. Re-run with --verify to execute the linked tests."
}
```

`state`, `spec_id` and `locator` are re-read from the spec frontmatter, not taken from
`behavior.json`, and a locator that does not resolve to a file inside the project drops the
row. So a behavior demoted to `proposed`, or one whose test file was renamed, stops licensing
a downgrade at the *next query* rather than at the next `--build`. A row can therefore
disappear between two runs with no code change: that is the check working.

**A locator is required, and so is `source: observed`.** A behavior declaring no locator is
dropped, not returned — it names no test, so it is not evidence that anything ran. That is a
real narrowing and ADR-012 records it: an `accepted` behavior with `adapter: manual`
legitimately has no locator and no longer downgrades anything. `source` is the other half:
an `exercises` entry is either a real run with coverage (`observed`) or `static`, **inferred
from the import graph with no test involved at all**, and only `observed` counts here.
`symbols` names the functions that actually ran, where the runner captured them — judge
relevance against those rather than against the file, because a test touching a 500-line
module says nothing about the line the finding names.

**`--verify` re-runs the linked test; without it nothing does.** By default both inputs
belong to the project being scanned, so `observed` means *a test passed once, on somebody's
machine* — a label on evidence, not a verification of it, and `verified: false` says so.
With `--verify` each returned behavior's test is handed to `freya-behavior-runner` for a
fresh run and the row gains `"verified": {"passed": …, "reason": …}`.

Read a failing verdict carefully rather than reporting it as a red test: **`test-failed` is
the runner's word for any non-zero exit from the test command**, so a checkout with no
toolchain installed (no `pnpm`, no `pytest`) is spelled exactly like a failing test. Those
rows carry a `note` saying so, and the runner's own stderr — forwarded, not swallowed — is
where the difference is visible. `could not run: …` is narrower and unambiguous: the runner
never started.

Either way, carry the query's `evidence` string into the report a human reads verbatim — see
`freya-codebase-security-scan`, `check-specs` Phase 3.
