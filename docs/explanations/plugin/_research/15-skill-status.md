# Skill: `status`

Research brief for the freya-devkit plugin-wide explainer. Backing sources are cited inline; every claim traces to a file under `skills/status/`.

## Sources read

- `skills/status/SKILL.md` — skill definition, commands, BACKLOG.md contract, when-to-use.
- `skills/status/scripts/collect_status.py` — the deterministic aggregator core (10,991 bytes, stdlib-only).
- `skills/status/scripts/test_collect_status.py` — the proof suite (behavior of each bucket, degradation, backlog render).
- `skills/spec-manager/scripts/frontmatter.py` (line 93) — `BEHAVIOR_STATES` tuple that defines the census states.

No `references/` directory exists in this skill; the only scripts are `collect_status.py` and its test file (plus `__pycache__`).

---

## What it is

`status` is the **read-only "check" counterpart** of `/freya-devkit:wrap-up`. Where `wrap-up` *does and syncs* (updates graph, docs, specs, security, and commits), `status` only *reports* — it aggregates all outstanding behavior/coverage/security work into one summary and, on request, regenerates a single git-tracked artifact, `knowledge-base/BACKLOG.md`.

> "The read-only **check** counterpart of `/freya-devkit:wrap-up` (which *does/syncs*). `status` mutates nothing except, on request, the generated `knowledge-base/BACKLOG.md`." — `SKILL.md`

The engine is `collect_status.py`, described in its own docstring as:

> "collect_status.py — the deterministic core of the `status` skill. Aggregates the project's outstanding behavior / coverage / security work into one read-only report, and (optionally) regenerates knowledge-base/BACKLOG.md. Every source degrades independently: a missing graph / findings / specs yields an empty bucket plus a note, never a crash. Stdlib-only."

## Why it exists

Two motivating problems, both stated in `SKILL.md`:

1. **Situational awareness on demand.** After pulling changes, or before planning, an engineer needs to see what intent, tests, and findings are outstanding — without running `wrap-up` (which mutates and commits). `status` answers "where do I stand / what's outstanding / what's left to do" without side effects.

2. **Draining the cold tail deliberately.** `wrap-up` only validates behaviors it *hits* (validate-on-hit). Behaviors that no work ever touches are never surfaced by wrap-up. `status` exposes those as explicit worklists so they can be worked on purpose rather than by accident.

> "This is how the cold tail (behaviors never touched by work, so never surfaced by wrap-up's validate-on-hit) gets drained on purpose." — `SKILL.md`, `review intent`

The `BACKLOG.md` artifact exists so the outstanding-work view **diffs in PRs**:

> "It is to intent+security completeness what a coverage report is to test coverage: it diffs in PRs so the team sees the backlog without running anything." — `SKILL.md`

## Commands (from SKILL.md)

| Command | Description |
|---------|-------------|
| `status` | Print the status summary and refresh `BACKLOG.md` |
| `status` (summary only) | Print the summary without rewriting `BACKLOG.md` — run `collect_status.py` and omit `--write-backlog` |
| `gaps` | List whole-repo uncovered source files |
| `review intent` | Work the proposed → confirm worklist, one at a time |
| `review tests` | Work the confirmed → write-a-test worklist, one at a time |

Note: `gaps`, `review intent`, and `review tests` are **agent-driven procedures** the SKILL.md instructs the model to perform (reading JSON, presenting behaviors, editing spec frontmatter). Only `status` maps to a single script invocation. There is no `status`/`gaps`/`review` subcommand dispatcher in the code — these are workflow labels, not CLI verbs.

## Exact CLI + flags

The one concrete command, `collect_status.py`, has this interface (from `main()`):

```bash
python "${CLAUDE_PLUGIN_ROOT}/skills/status/scripts/collect_status.py" \
  --project . --format text --write-backlog
```

Argparse definition (`collect_status.py` lines 245–251):

- `--project` — **required** — "Project root directory."
- `--format` — choices `["json", "text"]`, default `text`.
- `--write-backlog` — `store_true` — "Regenerate knowledge-base/BACKLOG.md from the status."

Behavior of the flags:
- With `--write-backlog`, it writes the file and prints `wrote {path}` before the report.
- `--format json` prints `json.dumps(status, indent=2)`; otherwise it prints the human text summary.
- Exit code is always `0` on a normal run (`main()` returns `0`); missing sources do not raise.

The `gaps` command shells out to a *different* skill's script (`SKILL.md`):

```bash
python "${CLAUDE_PLUGIN_ROOT}/skills/behavior-graph/scripts/behavior_graph.py" \
  --gaps --project .
```

## How it works — the pipeline

`collect(project_dir)` (lines 152–171) assembles a status dict from independent buckets. Each bucket is a pure function returning `(data, note_or_None)`; notes accumulate into a `notes` list.

1. **`behavior_census(project_dir)`** (lines 40–82) — walks the specs tree and reads YAML frontmatter.
   - Resolves the specs dir as `<project>/knowledge-base/specs`; if that isn't a dir, falls back to treating `project_dir` itself as the specs dir (tests pass a specs dir directly).
   - Walks all `*.md` files, parses frontmatter via the spec-manager's `frontmatter.parse_frontmatter`. Files with parse/OS errors are skipped silently.
   - For each spec's `behaviors` list, counts every behavior by its `state` into a dict keyed by `BEHAVIOR_STATES` = `("proposed", "confirmed", "accepted", "quarantined", "deprecated")` (from `frontmatter.py:93`).
   - Builds two **worklists**:
     - `intent` — behaviors with `state == "proposed"`. Each record carries a `certainty` inherited from the parent spec's `certainty` field (defaulting to `100` if not an int). Sorted by `(certainty, behavior_id)` — **lowest certainty first**.
     - `test_owed` — behaviors with `state == "confirmed"`. Sorted by `behavior_id`.
   - Behaviors without a `behavior_id`, or malformed entries, are skipped.

2. **`gaps_bucket(project_dir)`** (lines 85–97) — whole-repo coverage gaps via a subprocess call to `behavior_graph.py --gaps --project <dir>`.
   - Uses `check=True` **deliberately** — a code comment notes `behavior-graph --gaps` always exits 0 (returns a JSON `note` on a missing graph rather than failing).
   - Returns `{"total": N, "sample": [...]}` where the sample is capped at `GAPS_SAMPLE = 20` (line 24), plus the graph's own `note` if any.
   - On `CalledProcessError / JSONDecodeError / FileNotFoundError / OSError`: degrades to `({"total": 0, "sample": []}, "could not compute gaps (behavior-graph --gaps)")`.

3. **`verify_bucket(project_dir)`** (lines 100–110) — Tier-1 link-integrity errors from spec-manager's `verify_links.py`, run against the specs dir with `--format json`.
   - **Does NOT use `check=True`** — `verify_links` exits non-zero when it finds errors, so `check=True` would raise and lose the JSON. This is the subject of a dedicated regression test (`VerifyBucketTest.test_returns_errors_even_when_subprocess_exits_nonzero`).
   - Parses stdout as a JSON list of error records; empty stdout → `[]`. On JSON/OS errors → `([], "could not run verify_links")`.

4. **`stale_bucket(project_dir)`** (lines 113–131) — behaviors whose captured fingerprint freshness no longer matches current git HEAD.
   - Reads `knowledge-base/.graph/behavior.json`. Missing → `([], "no behavior.json — run behavior-graph --build")`; unreadable → `([], "behavior.json unreadable")`.
   - Gets `_git_head` via `git -C <dir> rev-parse HEAD`; if no HEAD (not a repo / git missing), returns `([], None)` — cannot determine staleness, so reports nothing.
   - A behavior is stale when it has `exercises` with `freshness` values AND current HEAD is not among them. Returns the sorted list of stale behavior ids.

5. **`security_bucket(project_dir)`** (lines 134–149) — open findings from the structured security index.
   - Reads `knowledge-base/security/codebase-security/findings.json`. Missing → `([], "no findings.json — run codebase-security-scan")`; unreadable → `([], "findings.json unreadable")`.
   - Returns only findings whose `status == "open"` (resolved/intentional are excluded — proven by `SecurityBucketTest.test_open_findings_only`), projecting `{id, title, severity, file}`.

The assembled status dict (line 160) has shape:

```
{
  "version": 1,
  "project": <abspath>,
  "behavior_counts": {proposed, confirmed, accepted, quarantined, deprecated},
  "intent_worklist": [...],
  "test_owed_worklist": [...],
  "gaps": {"total": N, "sample": [...]},
  "verify_failures": [...],
  "stale_fingerprints": [...],
  "open_security_findings": [...],
  "notes": [...]
}
```

## Inputs / outputs / artifacts

**Inputs (all read-only, all optional):**
- `knowledge-base/specs/**/*.md` — spec frontmatter (census + worklists).
- `knowledge-base/.graph/behavior.json` — fingerprints for the stale bucket (produced by `behavior-graph --build`).
- `knowledge-base/security/codebase-security/findings.json` — the security index (produced by `codebase-security-scan`).
- The `behavior-graph` and `verify_links` scripts, invoked as subprocesses.
- git HEAD (for staleness).

**Outputs:**
- **stdout** — text summary (default) or JSON (`--format json`).
- **`knowledge-base/BACKLOG.md`** — written only with `--write-backlog`. `write_backlog` (lines 221–226) `os.makedirs` the parent and overwrites the file, returning its path.

### The text summary (`_format_text`, lines 229–242)

```
Status for <abspath>
  behaviors: <p> proposed, <c> confirmed, <a> accepted, <q> quarantined, <d> deprecated
  intent worklist (to confirm): <n>
  test-owed worklist:           <n>
  coverage gaps:                <n>
  verify failures:              <n>
  stale fingerprints:           <n>
  open security findings:       <n>
  note: <each note...>
```

### BACKLOG.md (`render_backlog`, lines 174–218)

Markdown with a fixed header and four sections. The header line:

> "> Generated by `/freya-devkit:status` — **do not edit**; run `status` to refresh."

Then a one-line **Census**: `<n> proposed · <n> confirmed · <n> accepted · <n> tests owed · <n> open findings · <n> coverage gaps`, followed by sections:
- **Behaviors to confirm** — table of the intent worklist (`Behavior | Title | Spec`), or `_None._`.
- **Tests owed** — table of the test-owed worklist, or `_None._`.
- **Coverage gaps** — count line + a bulleted sample (capped at 20).
- **Open security findings** — table (`ID | Severity | Title | File`), or `_None._`.

## The three agent-driven worklists / procedures

- **`gaps`** — surfaces source files that no behavior exercises or declares as an `entry`, so the engineer can capture a behavior for uncaptured intent. Delegates to `behavior-graph --gaps`.
- **`review intent`** (proposed → confirm) — the agent reads `intent_worklist` from `status --format json`, works it **certainty-sorted, lowest first**, one behavior at a time: re-reads the code, presents it, then confirms (bump `state` `proposed → confirmed` in spec frontmatter), edits-then-confirms, quarantines/deprecates, or skips.
- **`review tests`** (confirmed → accept) — the agent reads `test_owed_worklist`, links or writes a test per behavior, and once a real passing linked test exists, bumps `state` `confirmed → accepted` (after which the wrap-up regression gate governs it). SKILL.md is explicit: **"Never auto-author a test — that is the engineer's work."**

The state machine `status` operates against: `proposed → confirmed → accepted`, with `quarantined` / `deprecated` as side states — the same `BEHAVIOR_STATES` tuple used across spec-manager and behavior-graph.

## How it composes with other skills

`status` is a pure **aggregation layer** — it owns no data of its own; it reads what other skills produce:

- **spec-manager** — imports `frontmatter` and `BEHAVIOR_STATES` directly from `spec-manager/scripts/` (via `sys.path.insert`), and subprocess-invokes `spec-manager/scripts/verify_links.py`. The census and worklists are entirely a view over spec frontmatter.
- **behavior-graph** — subprocess-invokes `behavior-graph/scripts/behavior_graph.py --gaps`, and reads its output artifact `knowledge-base/.graph/behavior.json` for staleness.
- **codebase-security-scan** — reads its `findings.json` index for open findings.
- **wrap-up** — the mutating counterpart. Per `SKILL.md`, `wrap-up` **also regenerates `BACKLOG.md`** in its artifacts commit, so the backlog stays current even for engineers who never run `status` directly. `status` is the on-demand / read-only path to the same artifact.

The `review intent` / `review tests` procedures feed the behavior lifecycle that spec-manager, behavior-runner, and behavior-graph all depend on (moving behaviors toward `accepted`, where the wrap-up regression gate governs them).

## Degradation behavior

The defining design property: **every source degrades independently; the command never blocks and never crashes.**

> "It reports a census ... and open security findings — each source degrades to a `note` if unavailable, and the command never blocks." — `SKILL.md`

Concretely:
- Missing specs dir → empty counts + empty worklists (no note; just zeros).
- Missing/failed behavior-graph → `{total:0, sample:[]}` + a gaps note.
- `verify_links` non-zero exit is *expected* (it means findings exist) and is preserved, not treated as failure.
- Missing `behavior.json` / `findings.json` → empty bucket + an actionable note pointing at the producing skill (`run behavior-graph --build`, `run codebase-security-scan`).
- Not a git repo (no HEAD) → staleness silently reported as none.
- Individual unparseable spec files are skipped, not fatal.

## Honest limits

- `status` is **read-only** except for `BACKLOG.md`. It does not fix anything, run tests, or commit. Use `/freya-devkit:wrap-up` to actually sync/commit (`SKILL.md`, "When to use").
- The worklists are only as complete as the spec frontmatter. Behaviors without a `behavior_id`, or specs with unparseable frontmatter, silently drop out of the census.
- The coverage-gaps sample is capped at 20 items (`GAPS_SAMPLE`); `total` is accurate but the listed sample is truncated in both the text summary and BACKLOG.md.
- Staleness depends on `freshness` fields being populated in `behavior.json`; behaviors with no fingerprints (empty `exercises`) are never flagged stale.
- `review intent` / `review tests` / `gaps` are agent workflows, not deterministic CLI subcommands — their quality depends on the model following SKILL.md, and they intentionally require human judgment (never auto-author tests).

## Gotchas / notes

- **`check=True` asymmetry is intentional and load-bearing.** `gaps_bucket` uses `check=True` (behavior-graph always exits 0); `verify_bucket` must NOT (verify_links exits non-zero on findings). Both are documented with inline comments and guarded by tests. Swapping them would silently drop verify errors.
- **`certainty` inheritance:** a proposed behavior inherits `certainty` from its parent spec's frontmatter (default `100`), and the intent worklist is sorted lowest-certainty-first — so the least-certain proposed behaviors surface first for confirmation. Proven by `test_intent_worklist_is_proposed_with_certainty` (certainty 60 inherited).
- **Only `status == "open"` security findings count** — `resolved` and `intentional` are excluded.
- **`behavior_census` dual-mode path resolution** (project root vs. specs dir directly) exists mainly so the tests can pass a specs dir; in normal use pass the project root.
- UNVERIFIED: the exact schema/fields of `behavior_graph.py --gaps` output beyond `total`, `gaps`, and `note` (I read only how `collect_status.py` consumes it, not `behavior_graph.py` itself). The `entry`-declares-coverage claim comes from `SKILL.md`'s prose, not from reading behavior-graph source.
- UNVERIFIED: whether `${CLAUDE_PLUGIN_ROOT}` expands to the plugin install root at runtime — assumed from the documented invocation pattern shared across freya-devkit skills, not tested here.

## Verbatim quotable lines

- "Read-only project status: aggregate outstanding behavior/coverage/security work ... and refresh the git-tracked knowledge-base/BACKLOG.md. The check-counterpart of wrap-up." — `SKILL.md` frontmatter description.
- "`status` mutates nothing except, on request, the generated `knowledge-base/BACKLOG.md`." — `SKILL.md`.
- "Every source degrades independently: a missing graph / findings / specs yields an empty bucket plus a note, never a crash. Stdlib-only." — `collect_status.py` docstring.
- "This is how the cold tail (behaviors never touched by work, so never surfaced by wrap-up's validate-on-hit) gets drained on purpose." — `SKILL.md`.
- "Never auto-author a test — that is the engineer's work." — `SKILL.md`.
- "It is to intent+security completeness what a coverage report is to test coverage: it diffs in PRs so the team sees the backlog without running anything." — `SKILL.md`.
- "> Generated by `/freya-devkit:status` — **do not edit**; run `status` to refresh." — `render_backlog` header, `collect_status.py`.
