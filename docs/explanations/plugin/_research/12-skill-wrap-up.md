# Skill Brief: `wrap-up`

**Source of record:** `skills/wrap-up/SKILL.md` (self-contained — no `scripts/`, `references/`, or `evals/` subdirectories exist in the skill dir; the skill orchestrates *other* skills' scripts).

---

## 1. What it is

`wrap-up` is the **post-implementation orchestrator** of freya-devkit. It is the
"finish my feature" skill: after you have written code, you invoke it once and it
runs every downstream freya-devkit maintenance skill in a fixed sequence, enforces
a set of governance gates, and commits the results using a disciplined **two-commit
pattern** (code separate from generated artifacts).

Frontmatter description (verbatim):

> "Complete your feature implementation workflow by running all post-implementation
> tasks in sequence: update dependency graph, update docs, update specs, run security
> scan, and commit everything together."

Trigger phrases (verbatim): "wrap up", "complete feature", "finish up", "done
implementing", "commit everything".

Namespaced invocation: `/freya-devkit:wrap-up`.

---

## 2. Why it exists

It is the top of the freya-devkit skill tier — the "orchestrates everything" node.
Individually the maintenance skills (code-graph, docs-manager, spec-manager,
behavior-graph, codebase-security-scan) each keep one kind of artifact in sync with
code. `wrap-up` exists so an engineer doesn't have to remember to run all of them in
the right order, in the right dependency sequence, with the right incremental
(`update`) modes, and commit them cleanly. It also folds in governance checks
(principle / contradiction / drift / intent gates) so that intent and code stay
coherent at the moment work is finalized.

One-line self-description:

> "Run all post-implementation tasks in sequence with clean two-commit separation."

---

## 3. The two-commit pattern

The central discipline. Two separate commits are produced:

- **Commit 1 — Code** (only if uncommitted code changes exist): stage and commit
  **code files only**.
- **Commit 2 — Artifacts**: docs, specs, security report, dependency graph, tracking
  files, `proposed`/unaccepted behavior scaffolds, ADRs, resolution logs, backlog.

Rationale given verbatim ("Why Two Commits?"):

> - Security scan has a stable commit to reference
> - Clean git history (code changes vs. generated files)
> - No tracking file hacks needed - the one-commit "lag" is harmless since artifacts contain no code

The "lag" idea: tracking files (e.g. `.security-last-scan`) point at the **code**
commit. The artifacts commit ends up one commit ahead of what those markers
reference, which is deliberately harmless because the artifacts commit contains no
code to analyze.

---

## 4. State-keyed staging (the behavior-aware staging rule)

A behavior scaffold's **commit class follows its lifecycle `state`, not its file
location**. A `.feature` scaffold physically lives in the code tree (`features/`),
but until it is `accepted` and authored it is *intent under review*, not executable
code. The skill reads each behavior's `state` from its spec frontmatter to classify.

Verbatim table:

| Artifact | Commit |
|----------|--------|
| `proposed` behaviors / unaccepted scaffolds (still carrying `TODO(scaffold)`) | **Artifacts** (commit 2) — intent under review |
| `accepted` behaviors' tests (`.feature` + steps, or the linked native test) | **Code** (commit 1) — executable, real |
| `SPEC-*.md`, `principles.md` | **Artifacts** (commit 2) |
| `knowledge-base/decisions/ADR-*.md` + `decisions/README.md` | **Artifacts** (commit 2) |
| `INTENT-NNN.md` records + `.intent-last-verified` marker | **Artifacts** (commit 2) |
| `principle-resolutions.jsonl` + any `principles.md` amendment | **Artifacts** (commit 2) |
| `contradiction-resolutions.jsonl` + any `principles.md`/spec amendment | **Artifacts** (commit 2) |
| `knowledge-base/drift-resolutions.jsonl` | **Artifacts** (commit 2) |
| an accepted test's edit + its `Intent: INTENT-NNN` commit trailer | **Code** (commit 1) |

Key rule (verbatim): "a `proposed`/`TODO` scaffold is staged with the artifacts even
though it sits under `features/`; it joins the **code** commit only once it is
`accepted` and its `TODO(scaffold)` marker is gone."

---

## 5. The exact pipeline (step by step)

### Phase 0 — Check for code changes
- Runs `git status --porcelain`.
- If code changes exist: separate code files from artifact directories (the
  `knowledge-base/` tree, etc.) applying the behavior-aware staging rule → stage code
  files only → generate or use provided commit message → create code commit → capture
  new commit hash.
- If no code changes (already committed, e.g. from security-resolver): skip to Phase 1.
  Security tracking still works.

**Never-synced guard (F5)** — a hard caveat: the `update` commands are incremental
and assume a prior sync. If a project has **never been synced** (no tracking file —
no `knowledge-base/specs/.spec-last-update`, no `.graph/`, no `.security-last-scan`),
wrap-up must **not** let `update` silently run a full-codebase generation. It should
report the project is unsynced and either run the explicit first-time command
(`scan` / `build`) deliberately or skip that phase. Verbatim: "wrap-up must not
trigger a surprise full generation."

### Phase 1 — Update dependency graph
Runs `/freya-devkit:code-graph update`. Refreshes the graph so docs-manager,
spec-manager, and the security scan all have accurate impact / blast-radius data.
It is deliberately first because the others consume it.

### Phase 2 — Update documentation
Runs `/freya-devkit:docs-manager update`. Updates `/knowledge-base/reference/`
(architecture docs, API docs, DB schemas, etc.).

### Phase 3 — Update specifications
Runs `/freya-devkit:spec-manager update`. Updates `/knowledge-base/specs/` (feature
specs, design decisions, certainty scores).

### Phase 3.5 — Behavior integrity & accepted-behavior run
The governance heart of wrap-up. Rule (verbatim): "**Only deterministic failures
block** (vision §8); everything else is advisory." It has 7 sub-steps:

1. **Deterministic link integrity (HARD-BLOCK).**
   - `python "${CLAUDE_PLUGIN_ROOT}/skills/spec-manager/scripts/verify_links.py" --format json`
     — non-zero exit (unresolved locator, missing reverse tag, `accepted`-but-`TODO(scaffold)`,
     duplicate `BEH-NNN`, orphan tag) blocks wrap-up.
   - `python "${CLAUDE_PLUGIN_ROOT}/skills/spec-manager/scripts/adr.py" verify --project .`
     — non-zero exit (duplicate `ADR-NNN`, dangling `supersedes`/`superseded_by`, bad
     status, malformed ADR frontmatter) hard-blocks at the same tier.

2. **Declared-intent gate (HARD-BLOCK).**
   `python ".../skills/spec-manager/scripts/verify_intent.py" --project . --format json`
   — non-zero exit means an `accepted` behavior's test was modified/deleted without a
   new `INTENT-NNN` record naming it (governance G1). Resolve by
   `spec-manager intent new <BEH-NNN>` or revert the test edit. With no
   `.intent-last-verified` baseline the gate skips. Verbatim: "**Read the JSON on the
   non-zero exit — never `check=True`.**"

3. **Build/refresh behavior graph + run affected accepted behaviors (HARD-BLOCK on
   regression).** Direction-A regression check re-runs *only* accepted behaviors whose
   exercised code the change touched (not the whole suite):
   ```bash
   BASE=$(git rev-parse HEAD~1)
   python "${CLAUDE_PLUGIN_ROOT}/skills/behavior-graph/scripts/behavior_graph.py" \
     --build --project . >/dev/null \
   && python "${CLAUDE_PLUGIN_ROOT}/skills/behavior-graph/scripts/behavior_graph.py" \
     --check --base "$BASE" --project .
   ```
   Chained with `&&` so a failed `--build` aborts before `--check` (never report a
   false green on a stale/absent graph). Non-zero exit = an affected accepted behavior
   is `test-failed` → blocks until classified (fix regression, record intended change,
   or `quarantine` infra failure). `proposed`/`quarantined`/`deprecated` behaviors are
   never run. `behavior.json` is written under git-ignored `knowledge-base/.graph/`.

4. **Validate-on-hit (ADVISORY — never blocks).**
   `python ".../behavior_graph.py" --surface --base "$BASE" --project .` — read-only,
   never changes exit code. JSON buckets:
   - `validate_candidates` — affected proposed/confirmed behaviors (bounded to touched
     subset); re-infer against current code, offer **confirm / edit then confirm /
     skip**; on confirm bump `state` `proposed → confirmed`. Never auto-accept.
   - `recall_gaps` — changed source files no behavior covers; optionally author a new
     `proposed`/`confirmed` behavior. Skippable.
   - `affected_accepted` — context only (already run in step 3).
   Bounded + skippable → no unbounded re-inference on large changes.

5. **Principle checkpoint (governance G2 — resolve-to-proceed).** Model judgment, a
   *procedural* gate (not a script exit) but wrap-up must not complete while a finding
   is unresolved.
   - Load constitution: `python ".../spec-manager/scripts/principles.py" list --project .`
     Empty output ⇒ no `principles.md` ⇒ skip.
   - Judge `git diff "$BASE"` against each principle.
   - Triage against priors: `principles.py prior --project . --paths <files> --principle <N>`
     → auto-clear / retire (superseded) / escalate, all via `principles.py resolve`
     with verdicts `auto-cleared` / `superseded` / `refuted` / `amended`.
   - Guardrails: re-judge current hunk against the *specific* prior reason; bias to
     escalate on ambiguity; a finding with no prior always goes to the human.
   - "Ignore and push" is not a resolution; not carried to backlog. Fail-open on no
     git / no diff / tooling error.

6. **Contradiction check (governance G3 — resolve-to-proceed).** Checks *intent vs
   intent* for specs/ADRs changed this cycle (`knowledge-base/specs/**` +
   `knowledge-base/decisions/**` in `git diff "$BASE" --name-only`). Uses
   `contradictions.py context` / `adr-context` / `prior` / `resolve`. Judges changed
   spec against principles (higher authority), peer decisions (same authority), and
   active ADRs (ADR outranks the spec). ADR-level check judges changed ADR against
   principles (fix the ADR) and peer ADRs (reconcile). Surfaces `adr_warnings`.
   Fail-open on no changed specs/ADRs / no principles / tooling error.

7. **Declarative-drift check (governance P4b — resolve-to-proceed).** Checks *code vs
   declared intent* (spec `intentional_decisions`/prose, or accepted ADR body).
   - `drift.py context --base "$BASE" --project .` → `{base, impact_source,
     impact_count, targets, warnings}`. No targets ⇒ skip. When `impact_source` is
     `changed-only` (code-graph absent) note the narrower blast radius — "never a
     silent empty set."
   - Judge each target's `hit_paths` diff (`git diff "$BASE"..HEAD -- <hit_paths>`)
     against declared intent; triage via `drift.py prior`; resolve via `drift.py
     resolve` (verdicts `auto-cleared` / `superseded` / `amended` / `refuted`), or fix
     the code.
   - Verbatim: "`drift.py gaps` is on-demand only and **must NOT run here.**"

**Phase 3.5 ordering (verbatim):** "deterministic facts (G1 + links + **adr verify** +
accepted-behavior run) → G2 principle checkpoint (step 5) → G3 intent-coherence
(step 6) → P4b declarative-drift (step 7)."

### Phase 4 — Security scan
Runs `/freya-devkit:codebase-security-scan update` for incremental analysis →
`/knowledge-base/security/codebase-security/`. `.security-last-scan` points to the
code commit (artifacts commit is one ahead, harmless).

Verbatim caveat: "Do **not** substitute `/freya-devkit:codebase-security-scan audit`
here — `audit` is a heavier, on-demand Workflow-powered mode that must not run inside
wrap-up." The `update` mode includes lightweight in-loop adversarial verification
(synchronous, no background workflow), so it composes cleanly in this linear pipeline.

### Phase 5 — Artifacts commit
0a. Advance the declared-intent baseline (only reached because the Phase 3.5 gate
   passed): `python ".../spec-manager/scripts/verify_intent.py" --project . --advance`.
   Stage `knowledge-base/intents/` (new `INTENT-NNN.md` + updated
   `.intent-last-verified`).
0b. Refresh the backlog:
   `python "${CLAUDE_PLUGIN_ROOT}/skills/status/scripts/collect_status.py" --project .
   --write-backlog >/dev/null`. Stage `knowledge-base/BACKLOG.md`.
1. Stage all artifacts (docs, specs, security report, dependency graph, tracking
   files, `BACKLOG.md`, `decisions/ADR-*.md` + `decisions/README.md`,
   `drift-resolutions.jsonl`, `proposed`/unaccepted behavior scaffolds).
2. Generate artifacts commit message (default pattern: `docs: update docs, specs, and
   security report`).
3. Create the commit.

---

## 6. CLI + flags (verbatim)

Invocation:
```
/freya-devkit:wrap-up
/freya-devkit:wrap-up "feat: add user authentication"
```
- No argument → analyze `git diff` to generate a commit message, ask to confirm/edit.
- Message argument → used directly for the **code** commit.

Skip flags ("Skipping Steps", verbatim):
```
/freya-devkit:wrap-up --no-security    # Skip security scan
/freya-devkit:wrap-up --no-docs        # Skip documentation update
/freya-devkit:wrap-up --no-specs       # Skip specification update
/freya-devkit:wrap-up --no-graph       # Skip dependency graph update
```
Combinable, e.g.:
```
/freya-devkit:wrap-up --no-security --no-specs "fix: typo in README"
```
Note: there is **no `--no-behavior`** style flag documented for Phase 3.5; the
documented skip flags cover only graph/docs/specs/security.

Commit message generation (when none provided): `git diff --stat` for changed files,
`git log -1 --pretty=%s` for recent style, categorize (feature / bug fix /
refactoring / documentation), pick prefix (feat/fix/refactor/docs/chore), summarize.

---

## 7. Inputs / outputs / artifacts

**Inputs:** the working tree state (`git status --porcelain`), an optional commit
message argument, `$BASE` (commit before the wrap-up's code change, default
`HEAD~1`), and pre-existing tracking files (sync markers).

**Outputs / artifacts touched:**
- Code commit (commit 1) — code files + accepted behaviors' tests.
- Artifacts commit (commit 2) — everything under `knowledge-base/`:
  `reference/` docs, `specs/SPEC-*.md`, `principles.md`, `decisions/ADR-*.md` +
  `decisions/README.md`, `intents/INTENT-NNN.md` + `.intent-last-verified`,
  resolution logs (`principle-resolutions.jsonl`, `contradiction-resolutions.jsonl`,
  `drift-resolutions.jsonl`), `security/codebase-security/<date>.md`, dependency graph,
  `BACKLOG.md`, `proposed`/unaccepted behavior scaffolds.
- `behavior.json` under git-ignored `knowledge-base/.graph/`.
- Tracking markers: `.security-last-scan`, `knowledge-base/specs/.spec-last-update`,
  `.graph/`, `.intent-last-verified`.

---

## 8. How it composes with other skills

wrap-up is a pure orchestrator — it calls into other skills' commands and scripts:

| Phase | Skill / script invoked | Mode |
|-------|------------------------|------|
| 1 | `/freya-devkit:code-graph` | `update` |
| 2 | `/freya-devkit:docs-manager` | `update` |
| 3 | `/freya-devkit:spec-manager` | `update` |
| 3.5 | `spec-manager` scripts: `verify_links.py`, `adr.py verify`, `verify_intent.py`, `principles.py`, `contradictions.py`, `drift.py` | direct script calls |
| 3.5 | `behavior-graph/scripts/behavior_graph.py` | `--build` / `--check` / `--surface` |
| 4 | `/freya-devkit:codebase-security-scan` | `update` (NOT `audit`) |
| 5 | `status/scripts/collect_status.py` | `--write-backlog` |

Required skills (verbatim "Requirements"): `/freya-devkit:code-graph`,
`/freya-devkit:docs-manager`, `/freya-devkit:spec-manager`,
`/freya-devkit:codebase-security-scan`. "If any skill is missing, the skill will warn
you and skip that step."

It is the counterpart of the read-only `status` skill (which aggregates outstanding
work without committing). It is also the terminal step invoked by
`codebase-security-resolver`'s workflow ("implement → commit code → run
/freya-devkit:wrap-up") — hence the "code already committed" path in Phase 0.

---

## 9. Degradation behavior

- **Skill missing** → warn and skip that step.
- **Step fails** → report error, ask whether to continue with remaining steps; if
  declined, stop so the user can fix, then re-run wrap-up.
- **Never-synced project (F5)** → refuse to let `update` silently do a full
  generation; report unsynced and run explicit `scan`/`build` or skip.
- **Governance gates fail-open** where they are model-judgment (G2/G3/P4b): on no git
  / no diff / no principles / no changed specs / tooling error → note and continue.
- **Hard-block gates fail-closed** (verify_links, adr verify, verify_intent,
  behavior_graph --check): non-zero exit stops wrap-up until fixed/reclassified.
- **`--build` failure** is treated as blocking (do not proceed as if the behavior run
  passed).
- **code-graph absent for drift** → `impact_source` degrades to `changed-only`
  (narrower blast radius, surfaced to engineer, never a silent empty set).

---

## 10. Honest limits / gotchas

- **GOTCHA (hardcoded absolute paths in source):** Two commands in SKILL.md use a
  machine-specific absolute path instead of `${CLAUDE_PLUGIN_ROOT}`:
  `python "/Users/main/.claude/plugins/cache/freya-devkit/freya-devkit/0.1.0/skills/spec-manager/scripts/verify_intent.py"`
  appears in Phase 3.5 step 2 and Phase 5 step 0. Elsewhere the same script is not
  path-hardcoded conceptually — this is an inconsistency in the doc (all other calls
  use `${CLAUDE_PLUGIN_ROOT}`). Abstracted here; the portable form is
  `${CLAUDE_PLUGIN_ROOT}/skills/spec-manager/scripts/verify_intent.py`. This ties the
  doc to a specific install version (`0.1.0`) and a specific user home — flagged for
  the explainer, not reproduced as guidance.
- **UNVERIFIED — script existence:** the brief cites the scripts by the paths in
  SKILL.md; I did not open `verify_links.py`, `adr.py`, `verify_intent.py`,
  `principles.py`, `contradictions.py`, `drift.py`, `behavior_graph.py`, or
  `collect_status.py` to confirm their exact flag surfaces. Flags are quoted verbatim
  from SKILL.md, which may drift from the actual script args.
- **UNVERIFIED — `--no-*` scope:** only `--no-security`, `--no-docs`, `--no-specs`,
  `--no-graph` are documented. Whether Phase 3.5 (behavior/governance) can be skipped
  via a flag is not stated; appears **not** skippable via a top-level flag (individual
  advisory sub-steps are skippable interactively).
- **Example paths/dates are illustrative:** the Example Session references
  `src/lib/auth/passkeys.ts`, `SPEC-003`, dated report filenames, and commit hashes
  like `abc123def` — these are generic doc examples, not real project data.
- **`knowledge-base/` is the artifact root** in this repo's variant (the plugin
  version). Note the non-plugin/local `docs-manager` variant uses `docs/` instead;
  wrap-up's SKILL.md consistently uses `knowledge-base/`.
- **When NOT to use** (verbatim list): WIP commits, temporary changes, experimental
  code, changes that don't need documentation.

---

## 11. Quotable lines (verbatim, from `skills/wrap-up/SKILL.md`)

- "Run all post-implementation tasks in sequence with clean two-commit separation."
- "No tracking file hacks needed - the one-commit 'lag' is harmless since artifacts contain no code"
- "A behavior scaffold's commit class follows its **lifecycle `state`, not its file location.**"
- "wrap-up must not trigger a surprise full generation."
- "**Only deterministic failures block** (vision §8); everything else is advisory in Phase 1."
- "**Read the JSON on the non-zero exit — never `check=True`.**"
- "Chain with && so a failed --build aborts BEFORE --check — never let --check run on a stale/absent graph and report a false green."
- "'Ignore and push' is **not** a resolution."
- "`drift.py gaps` is on-demand only and **must NOT run here.**"
- "Do **not** substitute `/freya-devkit:codebase-security-scan audit` here — `audit` is a heavier, on-demand Workflow-powered mode that must not run inside wrap-up."
- "If any skill is missing, the skill will warn you and skip that step."
