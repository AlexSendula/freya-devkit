# Ecosystem Wiring: How the Behavior Layer Composes

*Research brief for the Behavior Layer explainer. Audience: an engineer on the
original `main` who has never seen this feature. Everything here is grounded in
the SKILL.md files (`wrap-up`, `spec-manager`, `code-graph`, `behavior-graph`)
and the design vision (`docs/design/behavior-layer/00-vision.md`).*

---

## 1. The one-paragraph mental model

The Behavior Layer turns "specs" from **inert prose that nothing runs** into
**executable, governed guarantees**. Before, a spec captured *why* well but its
"what" was "an inert acceptance-criteria checklist that nothing executes and
`verify` can only eyeball" (vision line 21). The behavior layer makes each
observable behavior a first-class record (`BEH-NNN`) with a lifecycle `state`,
linked by an *adapter + locator* to a real test. The composition story is: at
**design time** the constitution (`principles.md`) is soft-injected so you build
with the rules in view; at **wrap-up** a graduated pipeline runs the affected
accepted behaviors and checks the change against declared intent — **blocking
only on deterministic facts, never on model confidence**; and `verify` is
"upgraded from eyeballing prose to actually running the linked tests" (vision
line 133).

---

## 2. Who does what (the cast)

| Skill | Role in the composition |
|---|---|
| `code-graph` | Foundation. Builds `knowledge-base/.graph/graph.json` (import/export dependency graph). Answers `impact <file>` = blast radius. Everything else scopes changes through it. |
| `spec-manager` | Owns `principles.md`, `specs/`, `decisions/` (ADRs), `intents/`. Owns the deterministic scripts (`verify_links.py`, `verify_intent.py`, `adr.py`, `principles.py`, `contradictions.py`, `drift.py`). |
| `behavior-graph` | Owns `knowledge-base/.graph/behavior.json` — the **BEHAVIOR → TEST → CODE** projection. Pure graph layer over `code-graph` + `behavior-runner`. Serves Direction A (`--affected`/`--check`) and Direction B (`--implements`). |
| `behavior-runner` | Runs a project's *accepted* behaviors via their adapter, captures TEST → CODE coverage fingerprints. Producer for the behavior graph. |
| `wrap-up` | The orchestrator. Runs the whole post-implementation pipeline in order and enforces the two-commit pattern. |
| `status` | Read-only counterpart of wrap-up; refreshes `knowledge-base/BACKLOG.md`. |
| **brainstorming** / **planning** (superpowers) | Design-time consumers of the soft-injected constitution + behavior graph. |

---

## 3. The two-commit pattern (and WHY)

wrap-up separates every run into **two commits**:

- **Commit 1 — Code** (only if uncommitted code changes exist): stage and commit
  code files only.
- **Commit 2 — Artifacts**: docs, specs, security report, dependency graph,
  tracking files, `BACKLOG.md`, ADRs, resolution JSONLs, and `proposed`/unaccepted
  behavior scaffolds.

**Why two commits** (verbatim rationale from `wrap-up/SKILL.md`):
- "Security scan has a stable commit to reference"
- "Clean git history (code changes vs. generated files)"
- "No tracking file hacks needed - the one-commit 'lag' is harmless since
  artifacts contain no code"

The tracking files (`.security-last-scan`, `.spec-last-update`,
`.intent-last-verified`) all point at the **code** commit. The artifacts commit
sits one ahead, "but this is harmless since it contains no code to scan."

---

## 4. The behavior-aware staging rule (subtle, important)

Normally you'd sort files into the two commits by *location* (code tree vs.
`knowledge-base/`). The behavior layer breaks that: a `.feature` scaffold lives
under `features/` in the **code tree**, but wrap-up stages it by its **lifecycle
`state`, not its file location**.

> "A behavior scaffold's commit class follows its **lifecycle `state`, not its
> file location.** A `.feature` scaffold lives in the code tree, but until it is
> `accepted` and authored it is *intent under review*, not executable code"

The staging table from `wrap-up/SKILL.md`:

| Artifact | Commit |
|---|---|
| `proposed` behaviors / unaccepted scaffolds (still carrying `TODO(scaffold)`) | **Artifacts** (commit 2) — intent under review |
| `accepted` behaviors' tests (`.feature` + steps, or the linked native test) | **Code** (commit 1) — executable, real |
| `SPEC-*.md`, `principles.md` | **Artifacts** (commit 2) |
| `knowledge-base/decisions/ADR-*.md` + `decisions/README.md` | **Artifacts** (commit 2) |
| `INTENT-NNN.md` records + `.intent-last-verified` marker | **Artifacts** (commit 2) |
| `principle-resolutions.jsonl` + any `principles.md` amendment | **Artifacts** (commit 2) |
| `contradiction-resolutions.jsonl` + any `principles.md`/spec amendment | **Artifacts** (commit 2) |
| `knowledge-base/drift-resolutions.jsonl` | **Artifacts** (commit 2) |
| an accepted test's edit + its `Intent: INTENT-NNN` commit trailer | **Code** (commit 1) |

**The key sentence:** "So a `proposed`/`TODO` scaffold is staged with the
artifacts even though it sits under `features/`; it joins the **code** commit
only once it is `accepted` and its `TODO(scaffold)` marker is gone. Read each
behavior's `state` from its spec frontmatter to classify."

**Why:** intent cannot be reliably inferred from code. A `proposed` scaffold is a
draft *proposal about intent under review*, not a verified guarantee — committing
it as "code" would blur the line the whole behavior layer exists to keep sharp.

---

## 5. The wrap-up Phase 3.5 pipeline (IN ORDER)

This is the heart of the composition. Phase 3.5 ("Behavior Integrity &
Accepted-Behavior Run") runs after graph/docs/specs updates (Phases 1–3) and
before the security scan (Phase 4). Steps, in order, with block-vs-advisory
marked:

### Step 1 — Deterministic link integrity — **HARD-BLOCK**
```bash
python "${CLAUDE_PLUGIN_ROOT}/skills/spec-manager/scripts/verify_links.py" --format json
```
Non-zero exit blocks on: unresolved locator, missing reverse tag, `accepted`-but-
`TODO(scaffold)`, duplicate `BEH-NNN`, orphan tag. Also runs ADR integrity at the
same tier:
```bash
python "${CLAUDE_PLUGIN_ROOT}/skills/spec-manager/scripts/adr.py" verify --project .
```
ADR non-zero (duplicate `ADR-NNN`, dangling `supersedes`/`superseded_by`, bad
status, malformed frontmatter) **hard-blocks** at the same tier as `verify_links`.

### Step 2 — Declared-intent gate (governance G1) — **HARD-BLOCK**
```bash
python ".../skills/spec-manager/scripts/verify_intent.py" --project . --format json
```
Blocks when an `accepted` behavior's test was modified/deleted in this change-set
**without a new `INTENT-NNN` record** naming it. Remedy: `spec-manager intent new
<BEH-NNN>` or revert the test edit. With no `.intent-last-verified` baseline the
gate **skips**. Rule: "**Read the JSON on the non-zero exit — never
`check=True`.**"

### Step 3 — Build/refresh behavior graph + run affected accepted behaviors — **HARD-BLOCK on regression**
```bash
BASE=$(git rev-parse HEAD~1)
python ".../skills/behavior-graph/scripts/behavior_graph.py" --build --project . >/dev/null \
&& python ".../skills/behavior-graph/scripts/behavior_graph.py" --check --base "$BASE" --project .
```
This is the **Direction-A regression check**: it re-runs *only* the accepted
behaviors whose exercised code the change touched — **not the whole suite**.
Non-zero exit = an affected accepted behavior is **`test-failed`**, a
deterministic failure that blocks until classified: fix the code (regression),
record an intended change, or `quarantine` a test-infra failure.
`proposed`/`quarantined`/`deprecated` behaviors are **never run**. The `&&`
chaining is deliberate: "a failed `--build` aborts BEFORE `--check` — never let
`--check` run on a stale/absent graph and report a false green." `behavior.json`
is written under the git-ignored `knowledge-base/.graph/`.

### Step 4 — Validate-on-hit — **ADVISORY (never blocks)**
```bash
python ".../skills/behavior-graph/scripts/behavior_graph.py" --surface --base "$BASE" --project .
```
"**read-only and never changes the exit code.**" Surfaces JSON buckets:
- `validate_candidates` — affected `proposed`/`confirmed` behaviors (bounded to the
  touched subset). For each the engineer reviews, **re-infer against current code**,
  then offer **confirm / edit then confirm / skip**. On confirm, bump `state`
  `proposed → confirmed`. "Never auto-accept — confirming intent does not author a
  test." **The whole step is skippable.**
- `recall_gaps` — changed source files no behavior covers; optionally author a new
  `proposed`/`confirmed` behavior. Skippable.
- `affected_accepted` — context only; already run by step 3, do not re-validate.

Bounded + skippable so "a large change never triggers an unbounded re-inference
fan-out."

### Step 5 — Principle checkpoint (governance G2) — **RESOLVE-TO-PROCEED (procedural, model judgment)**
Not a script exit — "wrap-up **must not complete while a finding is unresolved.**"
- (a) Load constitution (this is *also the soft-injection point*):
  ```bash
  python ".../skills/spec-manager/scripts/principles.py" list --project .
  ```
  Empty output ⇒ no `principles.md` ⇒ **skip**.
- (b) Judge `git diff "$BASE"` against each principle (whole list — principles are
  few and project-wide, no blast-radius scoping).
- (c) Triage findings against prior resolutions (`principles.py prior`): **auto-clear**
  (`--verdict auto-cleared`), **retire** (`--verdict superseded`), or **escalate**.
  Guardrails: re-judge current hunk vs the *specific* prior reason; **bias to
  escalate** on ambiguity; a finding with **no prior always goes to the human**.
- (d) Resolve each escalated finding: **Fix** (code rides commit 1) / **Refute**
  (`--verdict refuted`) / **Amend** (edit `principles.md` + `--verdict amended`).
  "'Ignore and push' is **not** a resolution." No backlog debt. Logged to append-only
  `knowledge-base/principle-resolutions.jsonl`.

### Step 6 — Contradiction check (governance G3) — **RESOLVE-TO-PROCEED (procedural)**
Checks *intent-vs-intent* on the specs AND ADRs changed this cycle (`specs/**` and
`decisions/**` in `git diff "$BASE" --name-only`). No changed specs/ADRs ⇒ **skip**.
Authority order: **principle > ADR > spec**. Uses:
```bash
python ".../skills/spec-manager/scripts/contradictions.py" context --project . --spec <SPEC-ID>
python ".../skills/spec-manager/scripts/contradictions.py" adr-context --project . --adr <ADR-NNN>
```
`context` now returns `adrs` (all active ADRs — always-global, no category scoping)
and `adr_warnings` (malformed ADRs surfaced, never silently dropped). A spec-vs-ADR
conflict means **fix the spec** (ADR outranks). Resolve via `contradictions.py
resolve` (`--verdict refuted|amended|auto-cleared|superseded`). Logged to
`contradiction-resolutions.jsonl`.

### Step 7 — Declarative-drift check (governance P4b) — **RESOLVE-TO-PROCEED (procedural)**
Checks *code-vs-declared-intent* (spec `intentional_decisions`/prose, or an accepted
ADR's body). **P4b is code-anchored** — it scopes by blast radius (only declared
items whose `related_code` intersects the change), *deliberately NOT* always-global
like G3.
```bash
python ".../skills/spec-manager/scripts/drift.py" context --base "$BASE" --project .
```
Returns `{base, impact_source, impact_count, targets, warnings}`. Each target has
`item`, `kind` (`spec`|`adr`), `related_code`, `hit_paths`, plus `decisions`+`file_path`
(spec) or `title`+`body` (ADR). No targets ⇒ **skip**. Fail-open: when
`impact_source` is `changed-only` (code-graph absent), the blast radius is narrower —
note it to the engineer; "this is **never a silent empty set**." Resolve via
`drift.py resolve` → `knowledge-base/drift-resolutions.jsonl`. Note:
`drift.py gaps` is **on-demand only and must NOT run here**.

### Canonical ordering (from the wrap-up scope note)
> "deterministic facts (G1 + links + **adr verify** + accepted-behavior run) →
> G2 principle checkpoint (step 5) → G3 intent-coherence (step 6) → P4b
> declarative-drift (step 7)."

Deterministic-first is deliberate: cheap, certain facts block early; expensive
model judgment runs only after the facts are clean.

---

## 6. The block-vs-warn philosophy (the design keystone)

From vision `00-vision.md` §8 (lines 154–157), verbatim:

> "Failures are gated by **what kind of check produced them**, not by a model's
> self-reported confidence"

- **Deterministic failures HARD-BLOCK.** "A Tier-1 link break, an *accepted*
  behavior's test failing, or a behavior-test change with **no** declared-intent
  record. These are facts; wrap-up refuses to complete until they're resolved."
  A test-infra failure is resolved by **quarantine**.
- **Model findings (Tier-2 contradictions) must be *acknowledged*, but never
  hard-block on certainty alone.** "A model's 'high certainty' is not a calibrated
  probability, and blocking on it would train people to rubber-stamp 'declare
  intent' to escape noise." A model finding surfaces and requires an explicit
  acknowledgement — but **"model-confidence is promoted to a hard gate *only
  after* its false-positive rate is measured on a real project and shown
  acceptable."**

This is *the* reason the pipeline is graded: steps 1–3 (deterministic) block;
steps 5–7 (model judgment) are procedural resolve-to-proceed gates. The whole
Phase 1 principle: "run *accepted* behaviors at wrap-up and **block only
deterministic failures**" (vision line 167).

---

## 7. Soft injection: `principles.md` into brainstorming / planning

`principles.md` (borrowed from spec-kit's `constitution.md`) is "the project's
constitution: project-wide rules above all specs and decisions." It is "enforced
two ways, and no more" (vision line 137):

- **Soft** — "auto-injected into the working context of brainstorming, planning,
  and wrap-up, so the agent designs with the constitution in view."
- **Checkpoint** — "wrap-up and code-review diff the change against it and raise a
  finding on violation."

The consumer table (vision lines 131–133):
> - **brainstorming** — "At design time, query the behavior graph → *'this change
>   touches behaviors X, Y — change or preserve?'* `principles.md` is auto-injected
>   here so design happens with the constitution in view."
> - **wrap-up** — "Run *accepted* behaviors, refresh fingerprints, flag *undeclared*
>   regressions, keep spec↔behavior in sync, and run principle + consistency checks."
> - **verify** — "Upgraded from eyeballing prose to actually running the linked tests."

The concrete soft-injection call (`principles.py list --project .`) appears at
every design-time entry point:
- `spec-manager create` step 1 ("Surface the constitution first")
- `spec-manager scan` Phase 1 ("Load the constitution first")
- wrap-up Phase 3.5 step 5a (the G2 load doubles as the soft-injection point)

"A passive file is not enforcement; these two mechanisms are."

---

## 8. `verify` upgraded — from eyeballing to running tests

The single most quotable framing (vision line 133): **"Upgraded from eyeballing
prose to actually running the linked tests."**

Before the behavior layer, `verify` could only re-read prose against code and
guess. Now `spec-manager verify` (and the wrap-up gate that mirrors it) runs the
deterministic Tier-1 checks:
- `verify_links.py` — locator resolves, reverse tags present, no `accepted`-but-
  `TODO`, no duplicate `BEH-NNN`, no orphan tags, `entry` resolves.
- `verify_intent.py` (G1) — accepted test edited without an `INTENT-NNN`.
- `adr.py verify` — ADR integrity.

And the actual *behavior run* happens through `behavior-graph --check`, which
delegates to `behavior-runner` to execute the accepted behaviors via their
adapter. Note the SKILL's own scoping caveat: "Model-based contradiction checking
… is **Tier-2 / Phase 3** — not part of this command yet. Phase 1 `verify` ships
only the deterministic checks above." (The model-judgment steps live in wrap-up,
not in `spec-manager verify`.)

---

## 9. How code-graph is the substrate underneath all of it

- **spec-manager** calls `code-graph impact <changed-files>` to widen its blast
  radius from "directly changed files" to "changed files + their dependents",
  then maps that to specs via `related_code`. Falls back to plain git diff if
  code-graph is unavailable.
- **behavior-graph** is explicitly "the pure graph layer (vision §5b): it
  *queries* `code-graph` (`--impact`) and `behavior-runner`
  (`--emit-fingerprints`); `code-graph` stays unaware of behaviors." Direction A
  (`--affected`) rides on `code-graph`'s impact traversal.
- **P4b drift** degrades gracefully: `impact_source` becomes `changed-only` when
  code-graph is absent — narrower radius, explicitly flagged, never a silent empty
  set.
- Non-interactive mode matters for composition: when `code-graph build` is invoked
  by wrap-up (stdin not a TTY), it "never prompts; uncertain directories default
  to **source** so real code is never silently dropped."

The vision names a **capability contract** as a precondition for trusting any
block decision built on the substrate: resolve imports (incl. TS path aliases),
stable file identity, language coverage, per-edge confidence, freshness,
changed-file impact, and an explicit "coverage unknown" signal instead of a
falsely-small blast radius. "Coverage-unknown, never silent" — governance leans
on the graph, so it must report when it cannot resolve an edge.

---

## 10. Merge-by-trust (why the graph doesn't lie about coverage)

`behavior-graph` merges fingerprints by trust so re-runs never downgrade good data:

| Incoming run | Result |
|---|---|
| `observed` | take it (highest trust) |
| `static` | take it, unless the prior edge was `observed` (don't downgrade) |
| `unknown` + `reason: test-failed` | **invalidate** (the test is red) |
| `unknown` + any other reason | **preserve** the prior fingerprint |

Critically for the regression gate: "`confirmed` behaviors … the runner never
executes them, so they only ever carry a `static` or `unknown` fingerprint —
never `test-failed`. The regression `--check` therefore never blocks on a
confirmed behavior; **only `accepted` behaviors gate.**"

---

## 11. End-to-end walk (a newcomer's flow)

1. **Design time.** You run `brainstorming` / `spec-manager create`. `principles.md`
   is soft-injected. You author a spec; new behaviors start `proposed`. G3 runs on
   the new spec.
2. **Implement.** You write code (and, for an accepted behavior, its real test).
3. **`wrap-up`.**
   - Phase 0 splits files into the two commits, applying the behavior-aware staging
     rule (proposed scaffolds → artifacts; accepted tests → code).
   - Commit 1 = code.
   - Phases 1–3 refresh graph/docs/specs.
   - Phase 3.5 runs the graded pipeline: deterministic blocks (links, G1, accepted-
     behavior run) → validate-on-hit (advisory) → G2 → G3 → P4b.
   - Phase 4 = incremental security scan (`update`, not `audit`).
   - Phase 5 = commit 2 (artifacts), plus advancing `.intent-last-verified` and
     refreshing `BACKLOG.md`.
4. **Result:** clean git history, a stable code commit for the security scan to
   reference, and every accepted guarantee actually executed and classified.

---

## 12. Quotable one-liners (verbatim, for explainer copy)

- "Upgraded from eyeballing prose to actually running the linked tests." (vision, `verify`)
- "Failures are gated by **what kind of check produced them**, not by a model's self-reported confidence." (vision §8)
- "A model's 'high certainty' is not a calibrated probability, and blocking on it would train people to rubber-stamp 'declare intent' to escape noise." (vision §8)
- "So a `proposed`/`TODO` scaffold is staged with the artifacts even though it sits under `features/`; it joins the **code** commit only once it is `accepted` and its `TODO(scaffold)` marker is gone." (wrap-up)
- "No tracking file hacks needed - the one-commit 'lag' is harmless since artifacts contain no code." (wrap-up)
- "A passive file is not enforcement; these two mechanisms are." (vision, on `principles.md`)
- "'Ignore and push' is **not** a resolution." (wrap-up, G2/G3/P4b)

---

## 13. Notes / caveats

- The `${CLAUDE_PLUGIN_ROOT}` prefix and the hard-coded
  `/Users/main/.claude/plugins/cache/freya-devkit/freya-devkit/0.1.0/...` path both
  appear in the source for the same scripts (the latter for `verify_intent.py`,
  `adr.py`, `intent.py`, `contradictions.py`). This is a source inconsistency (a
  dogfooding/local-dev artifact), noted below in `unverified`.
- "vision §8", "§7", "§5b", "§10", "P4a", "P4b", "SP3", "SP4", "F5" are section/
  work-item labels used inside the source docs; I reproduce them as-is.
</content>
</invoke>
