# Skill: `behavior-runner`

Research brief for the freya-devkit plugin-wide explainer.

**Sources read (verbatim paths):**
- `skills/behavior-runner/SKILL.md`
- `skills/behavior-runner/scripts/run_behaviors.py`
- `skills/behavior-runner/scripts/test_run_behaviors.py`
- `skills/spec-manager/scripts/adapters.py` (for `parse_locator`, reused by the runner)

The skill dir contains only `SKILL.md` + `scripts/` (no `references/`, no `evals/`).
`scripts/` holds exactly two Python files plus `__pycache__`.

---

## 1. What it is

`behavior-runner` runs a project's **accepted, non-quarantined** behaviors through
their adapter and emits **observed coverage fingerprints** — the `TEST -> CODE`
`exercises` edges that say "running this behavior's test executed these source
files." It is a **producer only**: it prints fingerprints as JSON to stdout and
**never writes `behavior.json`** (that write is owned by the `behavior-graph`
skill).

> "Runs **accepted, non-quarantined** behaviors through their adapter and emits
> `observed` coverage fingerprints (the `TEST -> CODE` `exercises` edges). It is a
> **producer**: it prints fingerprints as JSON; it never writes `behavior.json`
> (that is `behavior-graph`)." — `SKILL.md`

The docstring in the script restates the contract:

> "behavior-runner — run accepted behaviors via their adapter and emit observed
> coverage fingerprints (TEST -> CODE edges). Producer only: it never writes
> behavior.json (that is behavior-graph's job)." — `run_behaviors.py`

## 2. Why it exists

It is the runtime evidence layer of the plugin's **BEHAVIOR → TEST → CODE**
projection. Specs (owned by `spec-manager`) declare behaviors and which test
(`locator`) exercises them; `behavior-runner` actually executes those tests and
observes which source files run, so downstream tooling can answer blast-radius
questions grounded in real execution rather than guesses. Its output feeds
`behavior-graph` (which assembles `behavior.json`) and `wrap-up` (which runs
accepted behaviors as a gate).

Design principle it enforces: **coverage-unknown is never silent and never
faked.** A behavior with no usable coverage is emitted as `coverage: "unknown"`
with an empty `exercises` list — never falsely attributed to source files.

> "A behavior with no usable coverage is emitted with `coverage: "unknown"` and an
> empty `exercises` list — never falsely attributed." — `SKILL.md`

## 3. Coverage capture model (per level)

Capture mechanism is chosen **per behavior level** (the vision is
test-level-agnostic). From `SKILL.md`:

| Level | Mechanism |
|-------|-----------|
| `unit` / `component` | in-process, runner-native V8 coverage (vitest/jest) |
| `integration` | running app over HTTP; the observed per-framework V8+CDP adapter is **deferred**, so the **static** code-graph closure of a declared **entry** is used (`source: static`) |
| `e2e` | browser (later plan) |

The `coverage` field on every fingerprint is one of three values:

- `observed` — captured at runtime from runner-native V8 coverage (unit/component).
- `static` — code-graph closure of a declared `entry` file (integration; static analysis only, no execution).
- `unknown` — no usable coverage produced.

Confidence constants (in `run_behaviors.py`):
- `OBSERVED_CONFIDENCE = 0.8`
- `STATIC_CONFIDENCE = 0.5`

## 4. Behavior states and how they route

`fingerprint_behavior()` (the per-behavior router) decides what to do by
**state first, then level/adapter**:

1. **`confirmed`** state → **never executed.** A confirmed behavior means
   "intent confirmed, test owed" (see spec-manager lifecycle) — it has no
   executable test yet. It gets an advisory **static** fingerprint from its
   `entry` (or `unknown` / `no-entry` if none). Because it is never executed it
   can never be `test-failed`, so **it never gates wrap-up.** State wins over
   level/adapter: a confirmed behavior naming a vitest test that doesn't exist
   yet is still not executed.
2. **`accepted` + `level: unit` + `adapter: vitest`** → executed via vitest with
   coverage (`run_unit_behavior`).
3. **`accepted` + `level: integration`** (adapter-agnostic: cucumber, native,
   etc.) → `static_fingerprint` driven by the `entry` field.
4. Anything else (other accepted levels/adapters) → `unknown` with
   `reason: "level-deferred"`.

> "Only the `vitest` unit path is implemented so far. jest and other adapters are
> handled in later plans; behaviors using them are emitted with
> `coverage: "unknown"` and `reason: "level-deferred"`." — `SKILL.md`

Default state selection is **accepted-only**. To also process confirmed
behaviors, pass `--states accepted confirmed`. This keeps the wrap-up "run
accepted behaviors" path accepted-only by default.

## 5. Pipeline (step by step)

For the fingerprint-emitting path (`--emit-fingerprints`):

1. **Resolve specs dir** — `--specs-dir` if given, else
   `<project>/knowledge-base/specs`.
2. **Load behaviors** (`load_behaviors`) — walk the specs dir, parse each `.md`
   file's frontmatter (via spec-manager's `frontmatter` parser), collect
   `behaviors:` list entries whose `state` is in `--states` (default
   `["accepted"]`), optionally filtered by `--level`. Each record is the
   behavior mapping plus injected `spec_id` and `spec_path`. **A malformed spec
   is skipped with a stderr warning — it does not abort the whole batch.**
3. **Filter to `--only` ids** if provided (`filter_only`).
4. **Get commit** — `git -C <project> rev-parse HEAD` (falls back to the string
   `"unknown"` if git is unavailable).
5. **Fingerprint each behavior** via `fingerprint_behavior` (routing in §4):
   - **Unit/vitest path** (`run_unit_behavior`): build argv, delete any stale
     `coverage/coverage-final.json`, run the test, then:
     - non-zero exit → `unknown` + `reason: "test-failed"` (test output echoed to stderr);
     - passed but no coverage file → `unknown` + `reason: "no-coverage"`;
     - passed with coverage → map the istanbul `coverage-final.json` to executed
       project-relative source keys (`coverage_files_to_keys`) and shape an
       `observed` fingerprint.
   - **Static path** (`static_fingerprint`): validate `entry`, compute
     entry + code-graph closure, tag edges `source: static`.
6. **Emit** a single JSON object: `{version, commit, fingerprints}` to stdout
   (`indent=2`).

### Vitest invocation (`vitest_argv`)

The `locator` is split by `parse_locator` (from `spec-manager/scripts/adapters.py`)
into `(test_file, fragment)`. Supported locator forms:
- Gherkin: `path#scenario-slug`
- pytest-style: `path::node`

The built argv is verbatim:
```
["pnpm", "vitest", "run", <test_file>, "-t", <fragment>, "--coverage"]
```
(the `-t <fragment>` pair is only added when a fragment is present; `--coverage`
is always appended). Run with `cwd=project_dir`.

### Coverage mapping rules (`coverage_files_to_keys`)

Given istanbul `coverage-final.json` (map of abs path → `{"s": {stmtId: count}}`):
- **Drop files with zero executed statements** (loaded but no statement ran).
- Resolve each path relative to the project root; **drop paths outside the project**.
- **Drop `node_modules/`** (prefix or `/node_modules/` anywhere).
- **Drop excluded paths** (the test file itself is excluded so the test file
  doesn't appear as its own coverage).
- Return the remaining keys sorted.

### Static closure (`static_fingerprint` + `_code_graph_deps`)

- Reads the code-graph cache at `<project>/knowledge-base/.graph/graph.json`.
- If that cache file is absent → returns `None` → `unknown` + `reason: "no-graph"`
  (explicitly distinguished from "empty closure").
- Otherwise invokes code-graph:
  `python <code-graph>/graph_ops.py --dependencies <entry> --dir <project> --format json`
  and takes the JSON list as the transitive import closure.
- The final static key set = `entry` file **plus** its dependency closure,
  deduped and sorted (`static_exercises`).

## 6. Exact CLI + flags

Entry point (verbatim from `SKILL.md`):
```bash
python "${CLAUDE_PLUGIN_ROOT}/skills/behavior-runner/scripts/run_behaviors.py" \
  --project /path/to/project --level unit --emit-fingerprints
```

Flags (from `argparse` in `run_behaviors.py`):

| Flag | Required | Default | Meaning |
|------|----------|---------|---------|
| `--project` | **yes** | — | Project root directory |
| `--specs-dir` | no | `<project>/knowledge-base/specs` | Specs directory to scan |
| `--level` | no | (all levels) | Only run behaviors at this level (e.g. `unit`) |
| `--states` | no | `accepted` | One or more states to load (`nargs="+"`), e.g. `accepted confirmed` |
| `--only` | no | (all) | Restrict to these BEH ids (`nargs="+"`, metavar `BEH`) |
| `--list` | no | off | List matching behaviors and exit (no execution) |
| `--emit-fingerprints` | no | off | Run each matching behavior and emit fingerprints JSON |

Three output modes:
- `--list` → prints one tab-separated line per behavior:
  `behavior_id \t level \t adapter \t locator`.
- `--emit-fingerprints` → the fingerprint JSON contract (§7).
- Neither → prints `{"behaviors": [<ids>]}`.

The two commands documented in `SKILL.md` are **`run` (default)** — the
`--emit-fingerprints` invocation — and **`--list`**.

## 7. Output contract (fingerprint JSON)

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

- `version`: `1`.
- `commit`: project HEAD (or `"unknown"`).
- `fingerprints`: map of `behavior_id` → fingerprint.
- Each edge in `exercises`: `{path, source, confidence, freshness}` where
  `freshness` is the commit and `confidence` is `0.8` (observed) or `0.5` (static).
- An `observed`/`static` fingerprint carries **no** `reason` key. An `unknown`
  fingerprint carries a `reason` **only when one was supplied** (tests
  `test_unknown_when_no_keys` / `test_unknown_with_none_reason_omits_reason`
  assert the key is omitted otherwise).

## 8. `coverage: "unknown"` reason codes (never-silent)

Every unknown result that has a discriminable cause carries a `reason` — the
"coverage-unknown-never-silent" contract. From `SKILL.md`:

| `reason` | Meaning |
|----------|---------|
| `level-deferred` | Non-vitest/non-unit behavior — adapter not yet implemented |
| `test-failed` | vitest process exited non-zero |
| `no-coverage` | vitest passed but produced no coverage file (check `@vitest/coverage-v8` + json reporter config) |
| `no-entry` | Integration behavior has no `entry` field declared |
| `entry-missing` | Integration behavior declares an `entry` that does not exist on disk |
| `no-graph` | No built code-graph cache at this project (run `code-graph build` first) |

## 9. Inputs / outputs / artifacts

**Inputs:**
- Spec markdown files under `<project>/knowledge-base/specs` with a `behaviors:`
  frontmatter list. Each behavior may carry `behavior_id`, `title`, `state`,
  `level`, `adapter`, `locator`, `entry`.
- For unit behaviors: a runnable `pnpm vitest` setup with `@vitest/coverage-v8`
  and the json coverage reporter (produces `coverage/coverage-final.json`).
- For integration/static behaviors: a built code-graph cache at
  `<project>/knowledge-base/.graph/graph.json`.

**Outputs / artifacts:**
- **stdout only** — fingerprint JSON or a behavior list. The skill writes **no**
  persistent artifact of its own (no `behavior.json`, no report file).
- Transiently reads/deletes `<project>/coverage/coverage-final.json` during a
  unit run (deletes stale copy before running, reads it after).
- Diagnostics go to **stderr** (unparseable specs, test failures, missing
  coverage, missing entry, missing code-graph).

## 10. How it composes with other skills

- **spec-manager** — the source of behaviors. The runner reuses spec-manager's
  stdlib-only `frontmatter` parser and its `adapters.parse_locator` helper by
  adding `spec-manager/scripts` to `sys.path` (zero-install reuse). Behavior
  states (`accepted` / `confirmed` / `proposed`) follow the spec-manager
  lifecycle.
- **code-graph** — supplies the static import closure for integration/confirmed
  fingerprints via `graph_ops.py --dependencies`. Requires a built graph cache.
- **behavior-graph** — the **consumer**: it takes these fingerprints and writes
  `behavior.json`. The runner deliberately does not.
- **wrap-up** — runs accepted behaviors as part of the post-implementation
  workflow; relies on the accepted-only default and the fact that confirmed
  behaviors never produce `test-failed`.

> "Producer for the behavior graph." / "Used by behavior-graph and wrap-up." — `SKILL.md` frontmatter

## 11. Degradation behavior

- **Malformed spec** → skipped with a stderr warning; the batch continues
  (test `test_malformed_spec_does_not_abort_batch`).
- **git unavailable** → `commit` / `freshness` become the literal string `"unknown"`.
- **Non-implemented adapter/level** → `unknown` + `reason: "level-deferred"`
  (no crash, no false coverage).
- **Vitest test fails** → `unknown` + `reason: "test-failed"`; the run never
  fabricates coverage.
- **Missing code-graph cache** → `unknown` + `reason: "no-graph"`, explicitly
  distinguished from an empty closure (`_code_graph_deps` returns `None` vs `[]`).
- **code-graph subprocess/parse error** (cache present) → treated as empty
  closure `[]`, which then shapes to `unknown` (no keys).

## 12. Honest limits / what is stubbed

- **Only the vitest unit path is implemented.** jest and every other unit/component
  adapter are stubbed → `level-deferred`.
- **Integration coverage is static-only.** The intended runtime per-framework
  **V8 + CDP** observed adapter for a running app over HTTP is **deferred**;
  today integration behaviors get the static code-graph closure of their `entry`
  (`source: static`, `confidence 0.5`), not real observed coverage.
- **e2e is not implemented** ("browser (later plan)").
- Static integration path is adapter-agnostic — for any integration behavior it
  ignores `adapter` and drives entirely off the `entry` field.
- The runner assumes **`pnpm`** as the vitest runner (argv is hardcoded to
  `pnpm vitest run ...`).

## 13. Gotchas / UNVERIFIED

- **UNVERIFIED**: the skill assumes vitest runs under `pnpm`; there is no flag to
  switch package managers (npm/yarn). Hardcoded in `vitest_argv`.
- **UNVERIFIED**: coverage is read only from `<project>/coverage/coverage-final.json`;
  a project with a non-default coverage output dir would surface as `no-coverage`.
- **UNVERIFIED**: `--only` metavar is `BEH` and the help text says "accepted
  behavior ids," but `--only` actually filters whatever `--states` loaded (it is
  a post-load id filter), so it can also restrict confirmed behaviors when
  `--states accepted confirmed` is used.
- **UNVERIFIED**: `--list` and the no-flag mode both ignore `--emit-fingerprints`;
  precedence is `--list` first, then `--emit-fingerprints`, then the bare id list.
- Sanitization note: the SKILL and tests use generic auth/WebAuthn examples
  (`lib/webauthn.ts`, `app/api/.../route.ts`, `SPEC-001 Passkey Login`); these
  are illustrative fixtures, not proprietary content.
