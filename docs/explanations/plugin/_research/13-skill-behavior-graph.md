# Skill: behavior-graph

> Research brief for the plugin-wide explainer. Backing/sourced layer — cite before asserting.
> Deep mechanics of the behavior layer live in the dedicated behavior-layer explainer; this brief
> stays at the ecosystem level (what the skill is, how it composes, its CLI surface).

## Sources read

- `skills/behavior-graph/SKILL.md`
- `skills/behavior-graph/scripts/behavior_graph.py` (the entire implementation)
- `skills/behavior-graph/scripts/test_behavior_graph.py` (behavioral contract via tests)
- `skills/behavior-runner/SKILL.md` (the producer it orchestrates)
- Composition call-sites: `skills/wrap-up/SKILL.md`, `skills/status/SKILL.md`,
  `skills/codebase-security-scan/SKILL.md`, `skills/spec-manager/SKILL.md`

---

## 1. What it is

`behavior-graph` **owns `behavior.json`** — a generated projection stored at
`knowledge-base/.graph/behavior.json`, sibling to `code-graph`'s `graph.json`. It is the graph
layer for the plugin's **behavior layer**: it links specs to the code their behaviors exercise, and
answers two blast-radius questions in both directions.

Verbatim (SKILL.md):

> "Own behavior.json (the BEHAVIOR -> TEST -> CODE projection) and answer the two blast-radius
> directions: code change -> affected behaviors, and behavior -> implementing code. Pure graph
> layer over code-graph + behavior-runner."

> "Owns `behavior.json` (a **generated** projection at `knowledge-base/.graph/behavior.json`,
> sibling to `graph.json`). It projects spec frontmatter, orchestrates `behavior-runner` for
> coverage fingerprints, **merges by trust** (`observed > static`)..."

The two directions:

- **Direction A** — `affected <changed-files>`: which accepted or confirmed behaviors a code change
  touches.
- **Direction B** — `implements <BEH-NNN>`: which code a behavior exercises.

It is described as a "pure graph layer (vision §5b): it *queries* `code-graph` (`--impact`) and
`behavior-runner` (`--emit-fingerprints`); `code-graph` stays unaware of behaviors."

## 2. The SPEC → BEHAVIOR → TEST → CODE chain

This skill sits in the middle of a four-link chain that the plugin uses to reason about intent,
verification, and impact:

- **SPEC** — a spec-manager markdown file under `knowledge-base/specs/**.md`. Its frontmatter carries
  an `id` (e.g. `SPEC-001`) and a `behaviors:` list.
- **BEHAVIOR** — each list item is a `BEH-NNN` record with fields `behavior_id`, `title`, `state`
  (`proposed` | `confirmed` | `accepted` | others such as `quarantined`/`deprecated`), `level`
  (`unit` | `component` | `integration` | `e2e`), `adapter` (e.g. `vitest`, `cucumber`), `locator`
  (test address), and/or `entry` (project-relative route/handler file).
- **TEST** — the runner (`behavior-runner`) executes accepted behaviors through their adapter and
  captures which files run.
- **CODE** — the resulting `exercises` edges: `{path, source, confidence, freshness}` records naming
  the implementing files.

`behavior-graph` builds `behavior.json` by **projecting** the SPEC/BEHAVIOR frontmatter and
**merging** in the TEST→CODE fingerprints from the runner. It then queries both ends of the chain.

Only `accepted` and `confirmed` behaviors are projected into the graph; `proposed` is deliberately
excluded (see `project_behaviors`, lines 61–88):

> "accepted (authoritative) + confirmed (advisory, test owed) both belong in the graph so Direction
> A/B can see them; proposed does not (it is not confirmed intent)."

Projected fields per behavior: `_PROJECTED_FIELDS = ("state", "level", "adapter", "locator")` plus
`spec_id` (behavior_graph.py line 31, 84–87).

## 3. How it works — the `--build` pipeline

`build(project_dir)` (lines 127–144) is the core pipeline:

1. **Project** specs: `project_behaviors(knowledge-base/specs)` walks every `*.md`, parses
   frontmatter (reusing spec-manager's stdlib-only `frontmatter` parser via `sys.path` insert), and
   maps each `accepted`/`confirmed` `BEH-NNN` → its projected fields.
2. **Run** behaviors: `_run_behavior_runner(project_dir)` shells out to
   `behavior-runner/scripts/run_behaviors.py` with `--states accepted confirmed --emit-fingerprints`
   and parses its JSON stdout (lines 118–124). (Note: it always requests both states — proven by
   `test_run_behavior_runner_requests_accepted_and_confirmed`.)
3. **Load prior** `behavior.json` (if any) so observed edges survive a run that couldn't re-observe.
4. **Merge by trust** per behavior via `merge_fingerprint(prior, incoming)`.
5. **Write** `{version: 1, commit, behaviors}` to `knowledge-base/.graph/behavior.json` and print it.

For behaviors with no fingerprint from the runner, the default incoming is
`{"coverage": "unknown", "exercises": [], "reason": "not-run"}` (line 137).

### Merge-by-trust table (SKILL.md + `merge_fingerprint`, lines 27–58)

| Incoming run | Result |
|---|---|
| `observed` | take it (highest trust) |
| `static` | take it, unless the prior edge was `observed` (don't downgrade) |
| `unknown` + `reason: test-failed` | **invalidate** (the test is red) |
| `unknown` + any other reason | **preserve** the prior fingerprint |

Trust order is `observed > static`. A `static` incoming will *not* overwrite a prior `observed` edge
(it keeps the prior observed exercises). A `test-failed` unknown wipes the fingerprint even over a
prior `observed`. Any other unknown reason (e.g. `level-deferred`, `no-coverage`, `no-entry`)
preserves whatever was there before — coverage is never falsely lost just because a run couldn't
re-observe it.

## 4. behavior.json — the artifact

- **Path:** `knowledge-base/.graph/behavior.json` (function `_behavior_json_path`, line 91–92).
- **Git-ignored & regenerable:** `write_behavior_json` creates the `.graph` dir and drops a
  `.gitignore` containing `*` if none exists (lines 106–115). So the whole `.graph/` cache
  (graph.json + behavior.json) is a local build artifact, never committed. It does not overwrite an
  existing `.gitignore`.
- **Shape:**
  ```json
  {
    "version": 1,
    "commit": "<runner project HEAD>",
    "behaviors": {
      "BEH-002": {
        "spec_id": "SPEC-001",
        "state": "accepted",
        "level": "unit",
        "adapter": "vitest",
        "locator": "lib/example.test.ts::rejects an expired challenge",
        "coverage": "observed",
        "exercises": [
          { "path": "lib/example.ts", "source": "observed", "confidence": 0.8, "freshness": "<commit>" }
        ]
      }
    }
  }
  ```
- **Coverage values:** `observed | static | unknown` (produced by the runner; the graph merges them).

**Freshness caveat (SKILL.md):**

> "Direction A and B query results reflect the last `--build` snapshot — re-run `--build` after spec
> or code changes to refresh."

## 5. CLI reference (verbatim flags)

Entry point:
`python "${CLAUDE_PLUGIN_ROOT}/skills/behavior-graph/scripts/behavior_graph.py"`

`--project` is **required** on every invocation. Exactly one mode flag is required (mutually
exclusive group, lines 372–385).

| Mode flag | Args | What it does | Documented in SKILL.md? |
|---|---|---|---|
| `--build` | — | Build/refresh `behavior.json` (project + run + merge; writes file, prints JSON) | Yes |
| `--affected` | `FILE [FILE...]` (nargs `+`) | Direction A: behaviors affected by these changed files | Yes |
| `--implements` | `BEH` | Direction B: sorted list of code paths a behavior exercises | Yes |
| `--check` | (needs `--base`) | Direction-A **regression check**: re-run affected accepted behaviors; exit 1 if any is test-failed | No (script + wrap-up only) |
| `--surface` | (needs `--base`) | Validate-on-hit surface for `base..HEAD` (affected proposed/confirmed + recall gaps) | No (script + wrap-up only) |
| `--gaps` | — | Whole-repo uncovered-code audit (graph source files no behavior covers) | No (script + status only) |
| `--covering` | `FILE` | Accepted behaviors whose exercised code includes FILE (security cross-ref) | No (script + security-scan only) |
| `--base` | `COMMIT` | Base commit for `--check` / `--surface` (diff `base..HEAD`) | via those flags |

> **Doc-vs-code gap (worth noting for the explainer):** `SKILL.md` only documents `--build`,
> `--affected`, and `--implements`. The script implements four more modes (`--check`, `--surface`,
> `--gaps`, `--covering`) that are exercised by wrap-up, status, and security-scan. They are fully
> implemented and tested, just not listed in this skill's own SKILL.md command block.

Examples (from SKILL.md, generic paths):

```bash
# Build/refresh behavior.json:
python "${CLAUDE_PLUGIN_ROOT}/skills/behavior-graph/scripts/behavior_graph.py" --build --project /path/to/project

# Direction A — which behaviors does a code change touch:
python "${CLAUDE_PLUGIN_ROOT}/skills/behavior-graph/scripts/behavior_graph.py" --affected lib/example.ts --project /path/to/project

# Direction B — which code does a behavior exercise:
python "${CLAUDE_PLUGIN_ROOT}/skills/behavior-graph/scripts/behavior_graph.py" --implements BEH-003 --project /path/to/project
```

`--affected`/`--implements` are **read-only** (they load the existing `behavior.json`; they do not
rebuild it). Output is always JSON on stdout: `{"affected": [...]}` or `{"implements": [...]}`.

## 6. Both blast-radius directions in detail

### Direction B — behavior → code (`--implements BEH-NNN`)

`direction_b` (lines 147–152): looks up the behavior in `behavior.json` and returns the sorted
`exercises[].path` list. Unknown behavior → empty list. Pure lookup, no subprocess.

### Direction A — code → behaviors (`--affected FILE...`)

`direction_a` (lines 184–186) is two steps:

1. `_code_graph_impact(changed_files, project_dir)` (lines 155–171) computes the **blast radius**: it
   shells out to `code-graph/scripts/graph_ops.py --impact <files> --dir <project> --format json` and
   unions `input_files ∪ direct_dependents ∪ transitive_dependents` (plus the inputs themselves). On
   any failure (CalledProcessError, JSON error, missing file) it degrades to just the changed files.
2. `_affected_from_impact` (lines 174–181): returns every `BEH` whose `exercises[].path` set
   intersects the impact set. Sorted.

So Direction A is transitive: a change deep in a dependency surfaces every behavior whose exercised
closure includes it, because `code-graph` expands the change into its dependent set first.

## 7. The other four modes (used by sibling skills)

These are the composition surfaces — where behavior-graph plugs into the rest of the toolkit.

### `--check --base <commit>` → wrap-up's regression gate

`regression_check` (lines 333–366): diffs `base..HEAD`, computes Direction-A affected behaviors,
then **re-runs only those** via the runner (`only=affected`), merges the fresh fingerprints back into
`behavior.json`, and returns `{affected, failed, changed}` with exit code `1` iff any **accepted**
behavior came back `unknown` + `test-failed`. Only `accepted` behaviors can gate — there is an
explicit guard (lines 353–361) plus a defense-in-depth test proving a `confirmed` behavior with a
(hypothetical) `test-failed` incoming still exits 0.

wrap-up chains build then check (wrap-up/SKILL.md lines ~177–182):

```bash
python ".../behavior_graph.py" --build --project . >/dev/null \
&& python ".../behavior_graph.py" --check --base "$BASE" --project .
```

The `&&` is deliberate: "so a failed `--build` aborts BEFORE `--check` — never let `--check` [run on
a stale graph]".

### `--surface --base <commit>` → wrap-up's validate-on-hit

`surface` (lines 214–279): read-only, advisory. For `base..HEAD` it returns three buckets:

- `affected_accepted` — accepted behaviors the change touches (context only; the gate is `--check`).
- `validate_candidates` — affected **proposed + confirmed** behaviors to confirm on hit (proposed are
  matched by their declared `entry ∈ impact`; confirmed by graph intersection).
- `recall_gaps` — changed source files (that code-graph tracks) covered by **no** behavior.

The proposed-matching trick (docstring): a proposed behavior is affected iff its `entry` is in the
impact set — because `impact = changed ∪ transitive dependents` and the entry depends on its whole
closure, `entry ∈ impact` is equivalent to `closure(entry) ∩ impact ≠ ∅` "without recomputing
closures." This bounds cost so a single change "never triggers an unbounded re-inference fan-out."

### `--gaps` → status's coverage audit

`gaps` (lines 282–298): whole-repo audit. Returns `{gaps: [...], total: N}` — every source file in
`graph.json` that no behavior covers (`covered` = union of all `exercises` paths ∪ all declared
`entry` values, via `_covered`, lines 201–211). Consumed by the `status` skill (status/SKILL.md
lines 46–47).

### `--covering <file>` → security-scan's finding downgrade

`covering` (lines 301–318): returns `{file, covering: [{behavior_id, spec_id, coverage}]}` listing
only **`accepted`** behaviors whose `exercises` include the file. Confirmed/proposed are excluded on
purpose:

> "Only `accepted` (test-verified) behaviors are returned — they are the strongest 'intentional'
> evidence for the security cross-reference (SP5)."

security-scan uses this so that "Only `accepted` behaviors downgrade a finding"
(codebase-security-scan/SKILL.md lines 103, 324–335).

## 8. How it composes with other skills

- **Depends on `code-graph`** (queries `graph_ops.py --impact` for blast radius; reads `graph.json`'s
  `files` keys for the source-file universe in `--surface`/`--gaps`). `code-graph` stays unaware of
  behaviors — dependency is one-directional.
- **Depends on `behavior-runner`** — the producer. behavior-graph orchestrates it (`--emit-
  fingerprints`) and merges its output; it never lets the runner write `behavior.json`.
- **Reuses `spec-manager`** code: imports spec-manager's `frontmatter` parser and behavior-runner's
  `run_behaviors.load_behaviors` (for reading proposed behaviors in surface/gaps) via `sys.path`
  inserts (lines 18–29).
- **Consumed by `wrap-up`** — `--build` then `--check` (regression gate) and `--surface` (validate-
  on-hit). Wrap-up treats a failed `--build` as blocking.
- **Consumed by `status`** — `--gaps` for the coverage-gap worklist / BACKLOG.md.
- **Consumed by `codebase-security-scan`** — `--covering` to downgrade findings that an accepted
  behavior demonstrably exercises.
- **Consumed by `spec-manager` bootstrap** — greenfield/brownfield onboarding runs
  `/freya-devkit:behavior-graph --build --project .` to initialize the graph (empty on greenfield is
  correct and expected).

## 9. Degradation behavior (honest, verified in tests)

- **No code-graph** (`graph.json` absent): `--surface` and `--gaps` skip with an explanatory `note`
  ("no code-graph at knowledge-base/.graph/graph.json — run code-graph build") and empty buckets;
  `--covering` returns empty `covering` with the file echoed. Direction A degrades to treating only
  the literal changed files as the impact set (code-graph subprocess failure is swallowed).
- **No changed files** in `base..HEAD`: `--surface` returns a `note` and empty results; `--check`
  finds nothing affected and exits 0.
- **No behavior.json**: `load_behavior_json` returns `{}` (also on JSON/OS error), so queries return
  empty rather than crashing.
- **Runner can't observe a behavior**: coverage stays `unknown` with a `reason`, and merge-by-trust
  **preserves** any prior fingerprint (never falsely drops coverage) unless the reason is
  `test-failed`.
- **git errors** in `_changed_files`: returns `[]` (empty) rather than raising.

## 10. Honest limits & gotchas

- **Query freshness is snapshot-based.** `--affected`/`--implements` read the last `--build`'s
  `behavior.json`; they do not rebuild. Stale after spec/code changes until you re-run `--build`.
- **Only `accepted` behaviors ever gate.** `confirmed` behaviors are advisory: projected and visible
  in Direction A/B, but the runner never executes them, so they only ever carry `static`/`unknown`
  (never `test-failed`). Enforced twice (runner contract + a local guard in `regression_check`).
- **`proposed` behaviors are not in `behavior.json`.** They live only in specs; `--surface` reads
  them from disk separately by `entry`. So a brownfield `bootstrap` yields a near-empty
  `behavior.json` even with many proposed candidates — "expected," per spec-manager.
- **Coverage fidelity is bounded by the runner.** Per behavior-runner/SKILL.md, only the `vitest`
  unit path is implemented; jest/other adapters and integration/e2e observed coverage are
  deferred — those behaviors come back `unknown`/`level-deferred` or `static` (code-graph closure of
  `entry`), not truly observed. behavior-graph inherits this fidelity ceiling.
- **UNVERIFIED — "confidence"/"freshness" semantics.** The `exercises` records carry `source`,
  `confidence`, `freshness` fields, but behavior-graph only reads `path` (in every direction/query).
  It passes the other fields through from the runner unmodified; it does not interpret them. Their
  precise meaning is owned by behavior-runner, not this skill.
- **UNVERIFIED — "vision §5b" / SP2–SP5 references.** The code cites a "vision" doc and SP2/SP3/SP4/
  SP5 plan phases (e.g. "SP2/SP3 executable paths", "once SP4 lands"). Those describe planned/
  future executable-test paths; the guard comments imply some are not yet implemented. Exact status
  lives in `docs/design/behavior-layer/` and the behavior-layer explainer, not this skill.
- **SKILL.md under-documents the CLI** (see §5): four of seven modes are absent from its command
  block though implemented and tested.

## 11. Verbatim quotable lines

- "Own behavior.json (the BEHAVIOR -> TEST -> CODE projection) and answer the two blast-radius
  directions: code change -> affected behaviors, and behavior -> implementing code. Pure graph layer
  over code-graph + behavior-runner." — `skills/behavior-graph/SKILL.md`
- "It is the pure graph layer (vision §5b): it *queries* `code-graph` (`--impact`) and
  `behavior-runner` (`--emit-fingerprints`); `code-graph` stays unaware of behaviors." —
  `skills/behavior-graph/SKILL.md`
- "Confirmed behaviors are advisory. `confirmed` behaviors (intent confirmed, test owed) are
  projected into `behavior.json` and surface in Direction A/B, but the runner never executes them, so
  they only ever carry a `static` or `unknown` fingerprint — never `test-failed`." —
  `skills/behavior-graph/SKILL.md`
- "Direction A and B query results reflect the last `--build` snapshot — re-run `--build` after spec
  or code changes to refresh." — `skills/behavior-graph/SKILL.md`
- "Only `accepted` (test-verified) behaviors are returned — they are the strongest 'intentional'
  evidence for the security cross-reference (SP5)." — `behavior_graph.py` `covering()` docstring
- "a change never triggers an unbounded re-inference fan-out" — `skills/wrap-up/SKILL.md` (on
  `--surface`)
