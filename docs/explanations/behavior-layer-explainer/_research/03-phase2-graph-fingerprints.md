# Phase 2 — The Behavior Graph & Impact Fingerprints (research brief)

> Audience: an engineer on the original `main` who has never seen the Behavior Layer.
> Scope: Phase 2 — `behavior.json`, the `TEST → CODE` fingerprint, the two blast-radius
> directions, the `behavior-runner` + `behavior-graph` skills, and the measurement gate.
> Sources: `docs/design/behavior-layer/02-phase-2.md` (+ `02b`–`02f` plans),
> `skills/behavior-runner/scripts/run_behaviors.py`, `skills/behavior-graph/scripts/behavior_graph.py`,
> `skills/behavior-runner/SKILL.md`, `skills/behavior-graph/SKILL.md`,
> `skills/code-graph/scripts/graph_ops.py`, `docs/design/behavior-layer/dogfooding-notes.md`.

---

## 1. The one-sentence idea

After Phase 1 you can *declare* intended behaviors (stable `BEH-NNN` ids, a lifecycle,
a test locator). Phase 2 makes those behaviors **traceable to the code that implements them**,
so you can answer two questions mechanically:

- **Direction A (code → behavior):** "I changed these files — which intended behaviors did I touch?"
- **Direction B (intent → behavior):** "This behavior — which code implements it?"

The new, never-certain edge that makes this possible is **`TEST → CODE`** (called `exercises`):
"running behavior X's test executed these source files." The full chain is:

```
SPEC  →  BEHAVIOR  →  TEST  →  CODE  →  CODE (transitive deps)
```

`SPEC → BEHAVIOR → TEST` come from Phase-1 spec frontmatter (deterministic, authored).
`TEST → CODE` is **captured**, not authored — from observed runtime coverage or a static
import closure. `CODE → CODE` is the existing code-graph dependency edge that Direction A
rides on to compute a blast radius.

---

## 2. `behavior.json` — a SIBLING of `graph.json`, not a schema bump

`behavior.json` is a **generated projection** (derived from specs + coverage runs + static
parse — never hand-edited). It lives at:

```
<project>/knowledge-base/.graph/behavior.json
```

right next to `code-graph`'s `graph.json` in the same git-ignored `.graph/` dir. Both are
regenerable caches (`behavior-graph` writes a self-ignoring `.gitignore` containing `*` into
`.graph/`, exactly as code-graph already does).

**Why a separate file, not a new field on `graph.json`?** (design §3, §5b)

1. **Decouple the substrate decision.** code-graph might one day be swapped for a different
   engine (e.g. graphify). Keeping `behavior.json` separate means "how we build the code↔code
   graph" and "how we project behaviors onto it" stay independent decisions. The relationship is
   a **contract** (same file-key format + the blast-radius query), *not* shared ownership.
2. **code-graph stays pure.** code-graph is a static-parse, no-subprocess, deterministically-testable
   data layer that **knows nothing about behaviors**. `behavior.json` is owned by the new
   `behavior-graph` skill and sits *on top of* code-graph.
3. **Paths are `graph.json` file keys.** Every `exercises[].path` in `behavior.json` is a
   project-relative key that also appears in `graph.json`, so Direction A can intersect a code
   blast radius (from code-graph) with these fingerprints.

### The schema (design §3)

```json
{
  "version": 1,
  "commit": "<commit the graph was built at>",
  "behaviors": {
    "BEH-003": {
      "spec_id": "SPEC-001",
      "state": "accepted",
      "level": "integration",
      "adapter": "cucumber",
      "locator": "features/auth/passkey-login.feature#unknown-email-does-not-reveal-whether-a-user-exists",
      "coverage": "observed",
      "exercises": [
        { "path": "app/api/auth/passkey/authenticate/start/route.ts", "source": "observed", "confidence": 0.8, "freshness": "8223fa5" },
        { "path": "lib/webauthn.ts", "source": "observed", "confidence": 0.8, "freshness": "8223fa5" }
      ]
    }
  }
}
```

- **Keyed by stable `BEH-NNN`.** `spec_id` / `state` / `level` / `adapter` / `locator` are
  **projected** from spec frontmatter (single source of truth — not re-authored here).
  In code, the projected fields are exactly `_PROJECTED_FIELDS = ("state", "level", "adapter", "locator")`
  plus `spec_id`.
- **`level`** is a new field on behaviors: `unit | component | integration | e2e`. The behavior
  layer is **test-level-agnostic** — a behavior is verified by whatever level best proves it;
  `level` is the runner's dispatch key, not a separate skill. (Phase 2 implements `unit` +
  `integration`; component/e2e are accommodated by the model but deferred.)
- **`exercises`** are the `TEST → CODE` edges. Each carries `source`, `confidence`, `freshness`.

---

## 3. Trust order, confidence, freshness, and "coverage-unknown, never silent"

Each `exercises` edge has a **provenance**:

| `source` | Meaning | Confidence | How captured |
|----------|---------|-----------|--------------|
| `observed` | The test actually executed this file at runtime | `0.8` (`OBSERVED_CONFIDENCE`) | vitest V8 coverage (unit) |
| `static` | The file is in the declared entry's import closure | `0.5` (`STATIC_CONFIDENCE`) | code-graph transitive deps (integration) |
| `explicit` | (reserved) hand-authored anchor | — | **not implemented** — evidence-gated future lever |

**Trust order: `explicit > observed > static`.** On merge, higher trust wins (`explicit` is
reserved; today it's effectively `observed > static`). Static is **lower trust** because it
over-approximates: it lists everything the entry *could* reach, not what a test *did* reach.

- **`confidence`** — a per-edge trust weight (`0.8` observed, `0.5` static).
- **`freshness`** — the commit the edge was captured at (e.g. `"8223fa5"`). Lets the system
  detect a **stale** fingerprint: an edge whose `freshness` commit predates a change to its files.

### The `coverage` enum and the never-silent rule (design §3)

Per-behavior `coverage` is one of **`observed | static | unknown`**. The cardinal rule:
**never a falsely-empty or falsely-attributed `exercises` list.** If a behavior can't be
fingerprinted, it is `coverage: "unknown"` with an **empty** `exercises` list — never faked.

An `unknown` result carries a **`reason`** discriminator so the consumer can tell *why* it's
unknown (and whether to preserve a prior good edge on merge). The reasons emitted by the runner:

| `reason` | Meaning |
|----------|---------|
| `level-deferred` | Non-vitest/non-unit accepted behavior — adapter not implemented yet |
| `test-failed` | The vitest process exited non-zero (the test is red) |
| `no-coverage` | vitest passed but produced no coverage file (misconfigured reporter) |
| `no-entry` | Integration behavior declares no `entry` field |
| `entry-missing` | Integration behavior's `entry` file does not exist on disk |
| `no-graph` | No built code-graph cache (run `code-graph build` first) |
| `not-run` | (graph-side default) behavior projected but the runner emitted nothing for it |

This mirrors code-graph's own "never silent" fix: after the Phase-1 dogfooding (F7/F9), code-graph
now tags imports `external:<pkg>` vs `unresolved:<imp>` instead of silently dropping a failed
resolution — so "no dependencies" is distinguishable from "couldn't resolve."

---

## 4. The two producers of `TEST → CODE` edges

### 4a. Observed fingerprint (unit level) — the precise one

Path: `run_unit_behavior(behavior, project_dir)` in `run_behaviors.py`.

Pipeline:
1. Turn the behavior's `locator` into a filtered vitest command via `vitest_argv(behavior)`:
   `parse_locator` (reused from spec-manager's `adapters.py`) splits `path::fragment` into
   `(test_file, fragment)`, producing argv like
   `["pnpm", "vitest", "run", "lib/webauthn.test.ts", "-t", "rejects an expired challenge", "--coverage"]`.
2. Delete any stale `coverage/coverage-final.json`, then run vitest **in-process** (the code under
   test runs in the test process, so coverage is the runner's native **V8** output — precise, no
   bundler in the path).
3. Read the istanbul-shaped `coverage/coverage-final.json` (keyed by absolute path; each value has a
   statement-hit map `s`).
4. `coverage_files_to_keys(coverage_final, project_dir, exclude={test_file})` — keep files with **at
   least one executed statement** (`any(count > 0 for count in statements.values())`), drop
   `node_modules`, drop files outside `project_dir`, drop the test file itself, and map absolute paths
   to sorted project-relative `graph.json` keys.
5. `shape_fingerprint(keys, commit)` → `{"coverage": "observed", "exercises": [{path, source:"observed", confidence:0.8, freshness:commit}, ...]}`.

Failure handling (never-silent): non-zero exit → `shape_fingerprint([], commit, reason="test-failed")`;
passed-but-no-coverage-file → `reason="no-coverage"`.

The testbed exemplar is **BEH-002** ("login with an expired challenge is rejected") — proven by a
vitest test on the challenge-validation function, in-process, with a **mocked clock** (the one
legitimate nondeterministic boundary). Its observed fingerprint is exactly **1 file** (`lib/webauthn.ts`).

### 4b. Static fingerprint (integration level) — the safe over-approximation

Path: `static_fingerprint(behavior, project_dir)` in `run_behaviors.py`.

**Why static, not observed, for integration?** (dogfooding **F10** + **F11**)
- **F10:** an integration behavior must drive the app over its **real interface (HTTP)** against a
  *running instance*, never by importing the framework route handler in-process. On a CommonJS-default
  Next.js project, importing `next/server`'s ESM cycle under Node 24's `require(esm)` rules is
  forbidden (flipping to `"type":"module"` gives a *false green* and is a non-starter adoption barrier).
- **F11:** observed V8 coverage of the running `next dev` app captured **only Next's own internals**
  (`next/dist/...`), zero app code — App Router runs route handlers in a separate render worker that
  doesn't inherit the env-var capture, and app code is bundled. Real observed integration coverage is
  *solved but framework-specific* (a `--inspect` + CDP + source-map-remap dance; the `nextcov` tool
  does this for Next only). That collides with F10's framework-agnostic principle, so it's **deferred**
  to a per-framework coverage adapter (parking-lot).

So integration uses the **framework-agnostic static fallback**:
1. The behavior declares an **`entry`** field (project-relative route/handler path), e.g.
   `app/api/auth/passkey/authenticate/start/route.ts`.
2. `_code_graph_deps(entry, project_dir)` shells out to
   `graph_ops.py --dependencies <entry> --dir <project> --format json` — the **transitive import
   closure** of the entry (project-relative keys). (If no `graph.json` cache exists it returns `None`
   → `reason="no-graph"`, distinct from an empty closure.)
3. `static_exercises(entry, deps)` = `sorted({entry, *deps})` — the entry plus its closure.
4. `shape_fingerprint(..., source="static", confidence=STATIC_CONFIDENCE)` →
   `{"coverage": "static", "exercises": [{path, source:"static", confidence:0.5, ...}]}`.

Guards: no `entry` → `reason="no-entry"`; entry file missing on disk → `reason="entry-missing"`.

The testbed exemplar is **BEH-003** ("unknown email → generic options; no user enumeration"). Its
static fingerprint is **3 files**: `app/api/auth/passkey/authenticate/start/route.ts`, `lib/prisma.ts`,
`lib/webauthn.ts` — broader than the observed unit fingerprint, but that's the **safe direction** for
blast radius (a false "might be affected" only runs an extra test; a false "not affected" misses a
regression).

**Dispatch** happens in `fingerprint_behavior(behavior, project_dir, commit)`:
`confirmed` behaviors → always `static_fingerprint` (never executed); `unit`+`vitest` → `run_unit_behavior`;
`integration` (any adapter) → `static_fingerprint`; everything else → `reason="level-deferred"`.

### The runner is a PRODUCER only

`behavior-runner` **prints fingerprints as JSON; it never writes `behavior.json`.** Its output
contract (`--emit-fingerprints`):

```json
{ "version": 1, "commit": "<HEAD>", "fingerprints": { "BEH-002": { "coverage": "observed", "exercises": [...] } } }
```

Only **accepted (and, since SP1, `confirmed`) non-quarantined** behaviors are considered; the default
state filter is `accepted` only (`--states accepted confirmed` opts confirmed in). `proposed` /
`quarantined` / `deprecated` are never run.

---

## 5. `behavior-graph` — the owner, merge-by-trust, and the two directions

`behavior-graph` is the **pure, deterministic graph layer** (parallels code-graph in character). It
owns `behavior.json`, projects spec frontmatter, orchestrates `behavior-runner`, **merges by trust**,
and serves Direction A/B. It **queries** code-graph (`--impact`) and behavior-runner
(`--emit-fingerprints`) but is never queried *by* them (all dependency arrows point up:
`behavior-graph → behavior-runner + code-graph + spec-manager`).

**Why two skills, not one?** (design §5b) They change for different reasons (SRP). `behavior-runner`
changes when you add a runner/adapter/level or coverage mechanism — it's the **heavy, flaky,
tooling-coupled** part (boots servers, drives runners, captures runtime coverage). `behavior-graph`
changes when the projection schema, trust/merge rules, or query semantics change — it's **pure and
unit-testable without ever running a test**. Bundling execution into the graph layer would pollute a
clean data layer with the one messy operation.

### Merge by trust — `merge_fingerprint(prior, incoming)`

`prior`/`incoming` are coverage-parts `{coverage, exercises, reason?}` (`prior` may be `None`):

| Incoming run | Result |
|---|---|
| `observed` | take it (highest trust) |
| `static` | take it, **unless** the prior edge was `observed` (don't downgrade) |
| `unknown` + `reason: test-failed` | **invalidate** — `{coverage:"unknown", exercises:[], reason:"test-failed"}` (the test is red) |
| `unknown` + any other reason | **preserve** the prior fingerprint |

The key insight: a transient "couldn't capture" (`level-deferred`, `no-graph`, `not-run`, …) must not
*erase* a good prior edge — only a genuine **red test** invalidates.

### `build(project_dir)` — the orchestration

`project_behaviors(specs_dir)` (project accepted+confirmed frontmatter) → `_run_behavior_runner`
(shell out for fingerprints) → for each behavior, `merge_fingerprint(prior_part, incoming)` against the
prior `behavior.json` → `write_behavior_json`. Missing fingerprint defaults to
`{"coverage":"unknown","exercises":[],"reason":"not-run"}`.

### Direction B — `direction_b(behaviors, beh_id)`

Returns the **sorted** `exercises[].path` list for one behavior — the implementing code.

### Direction A — `direction_a(behaviors, changed_files, project_dir)`

1. `_code_graph_impact(changed_files, project_dir)` shells out to
   `graph_ops.py --impact <files> --dir <project> --format json`, which returns
   `{input_files, direct_dependents, transitive_dependents, all_affected}`; the impact set =
   the changed files ∪ `input_files` ∪ `direct_dependents` ∪ `transitive_dependents`.
2. `_affected_from_impact` returns the **sorted** BEH ids whose `exercises` paths intersect that
   impact set.

This is the "double duty" of Direction A (design §4a): at wrap-up it both **selects** which behaviors
to re-run and **flags** any whose test now fails.

---

## 6. The CLI (verbatim flags)

`behavior_graph.py` takes a required `--project`, a **mutually-exclusive** action group, and an
optional `--base`:

```bash
# Build/refresh behavior.json (project specs, run behaviors, merge by trust, write):
python behavior_graph.py --build --project /path/to/project

# Direction A — behaviors affected by changed files:
python behavior_graph.py --affected lib/webauthn.ts --project /path/to/project

# Direction B — code a behavior exercises:
python behavior_graph.py --implements BEH-003 --project /path/to/project

# Incremental Direction-A regression GATE (re-run only affected accepted behaviors; diff base..HEAD):
python behavior_graph.py --check --base <commit> --project /path/to/project

# Validate-on-hit surface (affected proposed/confirmed + recall gaps) for base..HEAD:
python behavior_graph.py --surface --base <commit> --project /path/to/project

# Whole-repo uncovered-code audit (source files no behavior covers):
python behavior_graph.py --gaps --project /path/to/project

# Accepted behaviors whose exercised code includes FILE (security cross-ref):
python behavior_graph.py --covering app/api/.../route.ts --project /path/to/project
```

The runner's own CLI:
```bash
python run_behaviors.py --project <p> --level unit --emit-fingerprints
python run_behaviors.py --project <p> --level unit --list
python run_behaviors.py --project <p> --emit-fingerprints --only BEH-002   # subset (incremental)
python run_behaviors.py --project <p> --states accepted confirmed --emit-fingerprints
```

> Note: `--build`, `--affected`, `--implements`, `--check` are the Phase-2 core (plans 4–5).
> `--surface`, `--gaps`, `--covering` were added by the later SP1–SP5 dogfooding passes
> (validate-on-hit, backlog/status, security cross-reference). `--check`/`--surface` require `--base`.

### `--check` — the incremental Direction-A regression gate (`regression_check`)

This is what wrap-up's **Phase 3.5** calls. `regression_check(project_dir, base)`:
1. `_changed_files(base, project_dir)` = `git diff --name-only base..HEAD`.
2. `direction_a(...)` → the affected accepted/confirmed behaviors. If none: `exit 0`, `affected: []`.
3. `_run_behavior_runner(project_dir, only=affected)` — re-run **only** the affected behaviors
   (via the runner's `--only` filter → `filter_only`), not the whole suite.
4. Merge each result back into `behavior.json`; collect `failed` = affected behaviors that came back
   `coverage:"unknown"` + `reason:"test-failed"` — **but only if `state == "accepted"`** (a local
   invariant so confirmed/proposed can never gate).
5. Return `({affected, failed, changed}, exit_code)` where `exit_code = 1 if failed else 0`.

**Only a deterministic failure blocks** (vision §8): a real `test-failed` of an *affected, accepted,
executed* behavior. That's a genuine test failure, not a fingerprint inference. Everything
fingerprint-driven stays **advisory** until the false-positive rate is measured at scale.
`confirmed` behaviors are surfaced by Direction A but never executed → they can only ever carry
`static`/`unknown`, never `test-failed`, so they never gate.

---

## 7. Direction A vs Direction B — where they surface

- **Direction A (code → behavior)** — regression early-warning *and* the test-selection lever.
  `git diff` → code-graph blast radius → intersect with fingerprints → "these accepted behaviors
  exercise code you changed." Surfaced at **wrap-up** (Phase 3.5): selects which behaviors to re-run
  and flags any that now fail as a deterministic regression.
- **Direction B (intent → behavior)** — the planning question. A behavior → its fingerprint →
  implementing code. Available to **brainstorming** at design time: "this change touches behaviors
  X, Y — change or preserve?"

---

## 8. Incremental execution + freshness caching (why per-behavior scales)

Attribution is **per-behavior** (each scenario/test = one `BEH-NNN`), which is about *granularity*,
not run volume. Volume is bounded by:

- **Incremental execution (Direction A doing double duty).** At wrap-up: diff → code-graph blast
  radius → intersect with fingerprints → **re-run only the affected behaviors**. Steady-state that's a
  handful regardless of total behavior count. A full sweep runs only on first index or explicit rebuild.
- **Freshness caching.** A behavior whose files are unchanged since its `freshness` commit reuses its
  cached fingerprint — no re-run. (Note: full freshness caching — skipping an *affected* behavior whose
  files are unchanged since its `freshness` commit — is flagged as an optional post-Phase-2 follow-up in
  Plan 5's "Next plan"; Phase 2 ships the Direction-A *selection* that re-runs only affected behaviors.)

**Stale-fingerprint detection:** a fingerprint whose `freshness` commit predates a change to its files
is flagged stale (design §2). The `behavior-graph` SKILL.md is honest that Direction A/B results reflect
the last `--build` snapshot — re-run `--build` after spec or code changes to refresh.

---

## 9. Measurement — the evidence gate (design §6a, on the testbed, 2026-06-29)

Phase 2 is **evidence-gated**: it must *measure* fingerprint breadth, false-positive rate, runtime, and
coverage-attribution reliability before anything downstream (Phase 3 governance) may trust the
fingerprints. Measured on the testbed's **2 accepted behaviors** (BEH-002 unit/observed,
BEH-003 integration/static). **Illustrative, not statistically significant — 2 behaviors, 3 changes.**

- **Fingerprint breadth:** BEH-002 (observed/unit) = **1 file** (`lib/webauthn.ts`) — precise.
  BEH-003 (static/integration) = **3 files** (route + `lib/prisma.ts` + `lib/webauthn.ts`) — broader.
  Observed is tighter than static, as expected.
- **False-positive rate (hand-judged):**
  - edit `lib/webauthn.ts` → flags **[BEH-002, BEH-003]** — both genuinely depend on it. FP = 0/2.
  - edit `lib/audit.ts` → flags **[]** — correct selectivity, no false positives.
  - edit `…/authenticate/start/route.ts` → flags **[BEH-003]** only. FP = 0/1.
  - → **FP rate 0** on this small set; the gate is selective, not flag-everything.
- **Runtime:** full `--build` (BEH-002 vitest + BEH-003 static) = **~1.4–2.4 s** (vitest-startup-dominated).
  Incremental `--check` on a change touching **no** exercised code = **0.07 s** (zero re-runs — the
  scaling win). Read-only queries = **0.03–0.06 s**.
- **Static-vs-observed:** BEH-003 static (3 files) over-approximates vs BEH-002 observed (1 file) — the
  **safe** direction.

### The four gated decisions, answered (provisionally, pending scale)

1. **Observed trustworthy?** Yes at the **unit** level — no need to reintroduce hand-authored anchors.
2. **Per-behavior fast enough?** Yes — incremental `--check` skips unaffected behaviors; the
   single-boot + inspector-delta optimization is **not** needed at this scale.
3. **Integration source-map remap reliable?** **Deferred (F11)** — observed integration coverage isn't
   captured on Next; **static** (code-graph closure) is used instead.
4. **Can governance hard-block?** **Deterministic blocking is already safe** and shipped (wrap-up
   Phase 3.5 blocks on a real `test-failed` of an affected, executed behavior). **Fingerprint-driven**
   governance stays **advisory** until the FP rate is measured on a larger suite — the bar Phase 3
   must clear.

---

## 10. The testbed close-the-loop (two levels, two adapters, two mechanisms)

To validate the level-agnostic claim, Phase 2 proves **two levels** on the testbed
(`viva-croatia-testbed`, a throwaway Next.js sandbox — production untouched):

- **`integration` — BEH-003** ("unknown email → generic options"): a cucumber-js scenario driving
  `POST /api/auth/passkey/authenticate/start` over **real HTTP** against a running `next dev`
  (app-under-test harness boots once via `BeforeAll`/`AfterAll`). Already `accepted` from Plan 1;
  Phase 2 adds its **static** fingerprint.
- **`unit` — BEH-002** ("expired challenge rejected"): a vitest test on the challenge-validation
  function, in-process, mocked clock. Validates the unit level, the **native (second) adapter**, and
  the observed coverage path.
- **BEH-001 "successful passkey login" stays `proposed`** — a valid login needs a WebAuthn assertion
  unforgeable below the browser/E2E layer (deferred).

The end-to-end verification (Plan 4 Task 4): `--build` → `behaviors.BEH-002.coverage == "observed"`
(exercises `lib/webauthn.ts`), `behaviors.BEH-003.coverage == "static"` (route + prisma + webauthn);
`--affected lib/webauthn.ts` → `{"affected": ["BEH-002", "BEH-003"]}`; `--implements BEH-003` →
`{"implements": ["app/api/auth/passkey/authenticate/start/route.ts", "lib/prisma.ts", "lib/webauthn.ts"]}`.

---

## 11. Folded-in dogfooding fixes (Phase 2)

- **F5 — wrap-up never-synced guard.** wrap-up's incremental `update` commands (code-graph / docs /
  specs / security) must **not** silently run a full-codebase generation on a project that's never been
  synced (no tracking file). Report unsynced + run the explicit first `scan`/`build`, or skip with a
  clear message.
- **F3 — `spec-manager init` keeps empty spec category dirs.** Drop a `.gitkeep` in each category dir
  (`auth/`, `api/`, `data/`, `features/`, `infra/`, `integration/`, `ui/`) so the structure survives
  Git (Git doesn't track empty dirs), mirroring the `decisions/` README rationale.
- **F4 — carried forward** (certainty model for agent-drafted/human-confirmed intent). Doesn't naturally
  arise in Phase 2; remains an open finding.

---

## 12. Out of scope / deferred (so newcomers don't over-claim)

- **Hand-authored explicit `exercises:` edges** — deliberately dropped (users won't maintain edges by
  hand; automation is the point). `explicit` is a reserved trust tier, a future evidence-gated lever.
- **Test creation / TDD / test generation** — the layer **links to whatever tests exist**; it composes
  with superpowers TDD and gsd (which write tests), never owns test creation or methodology.
- **Observed integration coverage** (V8+CDP+source-map remap; `nextcov`-style) — deferred per-framework
  adapter (parking-lot). Static is the baseline.
- **E2E / component-level capture** — accommodated by the model, not implemented in Phase 2.
- **Model-based contradiction checks / principle enforcement / hard-blocking on fingerprints** — Phase 3.
- **Single-boot + inspector-delta** integration optimization — deferred until measurement shows
  boot-per-behavior too slow.

---

## Note on scope drift (what the shipped code has beyond the base Phase-2 plans)

The plans `02b`–`02f` describe the core (`--build`/`--affected`/`--implements`/`--check`). The shipped
`behavior_graph.py` has since grown a **`confirmed`** lifecycle state (SP1 — intent confirmed, test
owed; advisory, never gates) and three more read-only commands from the SP2–SP5 dogfooding track:
`--surface` (validate-on-hit: affected proposed/confirmed + recall gaps), `--gaps` (whole-repo
uncovered-code audit), `--covering` (accepted behaviors exercising a file, for the security
cross-reference). These are adjacent tracks, not the Phase-2 fingerprint core, but they share the same
`behavior.json` and merge/projection machinery.
