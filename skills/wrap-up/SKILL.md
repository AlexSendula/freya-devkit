---
name: wrap-up
description: |
  Complete your feature implementation workflow by running all post-implementation
  tasks in sequence: update dependency graph, update docs, update specs, run security
  scan, and commit everything together.

  TRIGGER when: user says "wrap up", "complete feature", "finish up", "done implementing",
  "commit everything", or wants to finalize their work after implementing changes.

  Use this skill at the end of your implementation workflow to ensure documentation,
  specifications, and security reports are all updated and committed together.
---

# Wrap-Up

Run all post-implementation tasks in sequence with clean two-commit separation.

## What It Does

This skill orchestrates the complete post-implementation workflow with a two-commit pattern:

**Commit 1 - Code (if uncommitted changes exist):**
- Stage and commit code changes only

**Then, artifact generation:**
1. **Update dependency graph** - `/freya-devkit:code-graph update` for impact-aware updates
2. **Update documentation** - `/freya-devkit:docs-manager update` for project docs
3. **Update specifications** - `/freya-devkit:spec-manager update` for feature specs
3.5. **Behavior integrity & run** - deterministic link checks + run *accepted* behaviors; **only deterministic failures block**
4. **Run security scan** - `/freya-devkit:codebase-security-scan update` for incremental scan

**Commit 2 - Artifacts:**
- Docs, specs, security report, dependency graph, tracking files
- `proposed` behaviors / unaccepted scaffolds (intent under review — see the behavior-aware staging rule)

## Why Two Commits?

Separating code from artifacts ensures:
- Security scan has a stable commit to reference
- Clean git history (code changes vs. generated files)
- No tracking file hacks needed - the one-commit "lag" is harmless since artifacts contain no code

## Usage

```
/freya-devkit:wrap-up
/freya-devkit:wrap-up "feat: add user authentication"
```

With no arguments, the skill will:
- Analyze git diff to generate an appropriate commit message
- Ask you to confirm or edit the message

With a message argument, it uses that directly for the code commit.

## Workflow Details

### Phase 0: Check for Code Changes

First, determine if there are uncommitted code changes:

```bash
git status --porcelain
```

**If code changes exist:**
1. Separate code files from artifact directories (the `knowledge-base/` tree, etc.), applying the **behavior-aware staging rule** below
2. Stage code files only
3. Generate or use provided commit message
4. Create code commit
5. Capture the new commit hash

#### Behavior-aware staging rule

A behavior scaffold's commit class follows its **lifecycle `state`, not its file
location.** A `.feature` scaffold lives in the code tree, but until it is
`accepted` and authored it is *intent under review*, not executable code:

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

So a `proposed`/`TODO` scaffold is staged with the artifacts even though it sits
under `features/`; it joins the **code** commit only once it is `accepted` and its
`TODO(scaffold)` marker is gone. Read each behavior's `state` from its spec
frontmatter to classify.

**If no code changes (already committed, e.g., from security-resolver):**
- Skip to Phase 1
- Note: Security tracking will still work correctly

> **Never-synced guard (F5).** The `update` commands below are incremental and
> assume a prior sync. If a project has **never been synced** (no tracking file —
> e.g. no `knowledge-base/specs/.spec-last-update`, no `.graph/`, no
> `.security-last-scan`), do **not** let `update` silently run a full-codebase
> generation. Instead, report that the project is unsynced and run the explicit
> first-time command (`scan` / `build`) deliberately, or skip that phase with a
> clear message. wrap-up must not trigger a surprise full generation.

### Phase 1: Update Dependency Graph

Run `/freya-devkit:code-graph update` to refresh the dependency graph with any code changes.

This ensures:
- docs-manager has accurate impact analysis
- spec-manager knows affected code areas
- security scan has correct blast radius data

### Phase 2: Update Documentation

Run `/freya-devkit:docs-manager update` to sync project documentation.

This updates files in `/knowledge-base/reference/` based on code changes:
- Architecture docs
- API documentation
- Database schemas
- etc.

### Phase 3: Update Specifications

Run `/freya-devkit:spec-manager update` to sync feature specifications.

This updates files in `/knowledge-base/specs/` based on code changes:
- Feature specs
- Design decisions
- Certainty scores

### Phase 3.5: Behavior Integrity & Accepted-Behavior Run

Verify behavior links and run the *accepted* behaviors. **Only deterministic
failures block** (vision §8); everything else is advisory in Phase 1.

1. **Deterministic link integrity (hard-block).** Run:
   ```bash
   python "${CLAUDE_PLUGIN_ROOT}/skills/spec-manager/scripts/verify_links.py" --format json
   ```
   A non-zero exit (unresolved locator, missing reverse tag, `accepted`-but-
   `TODO(scaffold)`, duplicate `BEH-NNN`, orphan tag) **blocks** wrap-up — fix the
   code/link, or re-classify the behavior (e.g. `quarantine` an infra failure).

   Also run ADR integrity:
   ```bash
   python "${CLAUDE_PLUGIN_ROOT}/skills/spec-manager/scripts/adr.py" verify --project .
   ```
   A non-zero exit (duplicate `ADR-NNN`, dangling `supersedes`/`superseded_by` link,
   bad status, malformed ADR frontmatter) **hard-blocks** wrap-up at the same tier as
   `verify_links` — fix or remove the offending ADR before continuing.
2. **Declared-intent gate (hard-block).** Run:
   ```bash
   python "${CLAUDE_PLUGIN_ROOT}/skills/spec-manager/scripts/verify_intent.py" --project . --format json
   ```
   A non-zero exit means an `accepted` behavior's test was modified/deleted in this
   change-set without a **new** `INTENT-NNN` record naming it (governance G1). This
   **blocks** wrap-up: either `spec-manager intent new <BEH-NNN>` to declare the
   intended change, or revert the test edit (a bare accepted-test change is a
   regression). With no `.intent-last-verified` baseline the gate skips. **Read the
   JSON on the non-zero exit — never `check=True`.**
3. **Build/refresh the behavior graph, then run the affected accepted behaviors
   (hard-block on a regression).** After the code commit, refresh the graph and
   run the Direction-A regression check (re-runs *only* the accepted behaviors
   whose exercised code the change touched — not the whole suite):
   ```bash
   # BASE = the commit before this wrap-up's code change(s). HEAD~1 is correct
   # for the standard single-code-commit flow; if you made several code commits
   # (or the code was already committed before wrap-up), set BASE to the commit
   # before the first relevant change.
   BASE=$(git rev-parse HEAD~1)
   # Chain with && so a failed --build aborts BEFORE --check — never let --check
   # run on a stale/absent graph and report a false green.
   python "${CLAUDE_PLUGIN_ROOT}/skills/behavior-graph/scripts/behavior_graph.py" \
     --build --project . >/dev/null \
   && python "${CLAUDE_PLUGIN_ROOT}/skills/behavior-graph/scripts/behavior_graph.py" \
     --check --base "$BASE" --project .
   ```
   (If `--build` fails, treat it as a blocking error — do not proceed as if the
   behavior run passed.)
   A non-zero exit means an affected accepted behavior is **`test-failed`** — a
   **deterministic failure** that blocks until classified: fix the code
   (regression), record an intended change, or `quarantine` a test-infra failure.
   `proposed`/`quarantined`/`deprecated` behaviors are never run. `behavior.json`
   is written under the git-ignored `knowledge-base/.graph/`.

4. **Validate-on-hit (advisory — never blocks).** After the gated check, surface the
   proposed/confirmed behaviors this change actually touched, plus any touched code no
   behavior covers:
   ```bash
   python "${CLAUDE_PLUGIN_ROOT}/skills/behavior-graph/scripts/behavior_graph.py" \
     --surface --base "$BASE" --project .
   ```
   This is **read-only and never changes the exit code.** Using its JSON buckets:
   - **`validate_candidates`** (the affected proposed/confirmed behaviors — bounded to
     the touched subset): present them prominently, **but the whole step is skippable.**
     For each candidate the engineer chooses to review, **re-infer it against the
     current code** — read the behavior's `entry` file as it is now and produce a
     refreshed title/description — then offer: **confirm**, **edit then confirm**, or
     **skip**. On confirm, bump the behavior's `state` `proposed → confirmed` in its
     spec frontmatter (`spec_path`); a candidate already `confirmed` stays `confirmed`
     and is noted as still owing a test (its worklist home arrives in SP4). Never
     auto-accept — confirming intent does not author a test.
   - **`recall_gaps`** (changed source files no behavior covers): if any, prompt
     "these N touched file(s) have no covering behavior — capture one?" and, if the
     engineer wants, author a new `proposed`/`confirmed` behavior via spec-manager.
     Skippable.
   - **`affected_accepted`** is context only — those behaviors were already run by the
     gated check in step 3; do not re-validate them.
   Re-inference is bounded by the affected subset and the step is skippable, so a large
   change never triggers an unbounded re-inference fan-out. If `--surface` returns a
   `note` (no graph / no changes), print it and continue.

5. **Principle checkpoint (governance G2 — resolve-to-proceed).** After the
   deterministic blocks and validate-on-hit, check the change against the project's
   constitution. This is **model judgment**, so it is a *procedural* gate (honored by
   you, the wrap-up agent), not a script exit — but wrap-up **must not complete while a
   finding is unresolved.**

   a. **Load the constitution** (this is also the soft-injection point):
      ```bash
      python "${CLAUDE_PLUGIN_ROOT}/skills/spec-manager/scripts/principles.py" list --project .
      ```
      Empty output ⇒ no `principles.md` ⇒ **skip this step** (nothing to enforce).

   b. **Judge** `git diff "$BASE"` (the same `BASE` from step 3) against each
      principle: *does anything in this diff violate this rule?* Produce candidate
      findings — each naming the **principle number**, the **file(s)/hunk**, and
      **why**. Principles are few and project-wide, so check the whole list; no
      blast-radius scoping.

   c. **Triage each finding against prior resolutions.** For a finding's files:
      ```bash
      python "${CLAUDE_PLUGIN_ROOT}/skills/spec-manager/scripts/principles.py" \
        prior --project . --paths <finding files> --principle <N>
      ```
      If it returns a prior resolution, **re-validate it against the *current* hunk**
      (not just the file):
      - **Still clearly valid** — the flagged code *is* the same intentional thing the
        prior reason described, materially unchanged → **auto-clear** and log it:
        ```bash
        python "${CLAUDE_PLUGIN_ROOT}/skills/spec-manager/scripts/principles.py" \
          resolve --project . --principle <N> --verdict auto-cleared \
          --reason "re-applied prior refutation; flagged code unchanged" --paths <files>
        ```
      - **Stale** — the code changed so the prior no longer maps → **retire** it and
        evaluate the finding fresh:
        ```bash
        python "${CLAUDE_PLUGIN_ROOT}/skills/spec-manager/scripts/principles.py" \
          resolve --project . --principle <N> --verdict superseded \
          --reason "code changed; prior no longer applies" --paths <files>
        ```
      - **Now a real violation** — the prior reason no longer excuses it → **escalate**.

      **Auto-clear guardrails:** re-judge the current hunk against the *specific* prior
      reason, not the file (a *new/different* violation in a previously-refuted file
      **escalates**); **bias to escalate** on any ambiguity; a finding with **no prior
      always goes to the human.**

   d. **Resolve every escalated finding with the engineer** — and do not complete
      wrap-up until each is resolved as one of:
      - **Fix** — change the code to comply and re-judge (the code fix rides the code commit).
      - **Refute** (false positive):
        ```bash
        python "${CLAUDE_PLUGIN_ROOT}/skills/spec-manager/scripts/principles.py" \
          resolve --project . --principle <N> --verdict refuted \
          --reason "<why it is not actually a violation>" --paths <files> [--ref SPEC-NNN]
        ```
      - **Amend** — edit `knowledge-base/principles.md` (with a dated change-history
        line) **and** log it:
        ```bash
        python "${CLAUDE_PLUGIN_ROOT}/skills/spec-manager/scripts/principles.py" \
          resolve --project . --principle <N> --verdict amended \
          --reason "<how/why the principle changed>" --paths <files>
        ```

   "Ignore and push" is **not** a resolution. Principle findings are **not** carried
   forward as backlog debt — each is resolved in the wrap-up that raised it. On no git
   / no diff / any tooling error, note it and continue (advisory, fail-open).

6. **Contradiction check (governance G3 — resolve-to-proceed).** After the principle
   checkpoint, check the *intent* changed this cycle. Same posture as step 5: **model
   judgment → procedural gate**, never a script hard-block, never auto-fail on model
   confidence; wrap-up **must not complete while a finding is unresolved.**

   a. **Find the specs and ADRs changed this cycle** — the `knowledge-base/specs/**`
      files AND `knowledge-base/decisions/**` files in `git diff "$BASE" --name-only`
      (the same `BASE` from step 3). No changed specs and no changed ADRs ⇒ **skip
      this step.**

   b. **For each changed spec, run the G3 contradiction check** — see the shared
      procedure in the spec-manager skill ("Contradiction Check (governance G3)"):
      assemble the comparison set with
      ```bash
      python "${CLAUDE_PLUGIN_ROOT}/skills/spec-manager/scripts/contradictions.py" \
        context --project . --spec <SPEC-ID>
      ```
      The returned context now includes `adrs` (all active ADRs — always-global, no
      category scoping) and `adr_warnings` (malformed/unparseable ADRs surfaced as
      warnings). Judge the changed spec's intent against each `principle` (higher
      authority), each `peer` decision (same authority), **and each active ADR (ADR
      outranks the spec — a spec-vs-ADR conflict means fix the spec)**. Surface any
      `adr_warnings` to the engineer. Triage findings against
      ```bash
      python "${CLAUDE_PLUGIN_ROOT}/skills/spec-manager/scripts/contradictions.py" \
        prior --project . --spec <SPEC-ID>
      ```
      (auto-clear / retire / escalate, per the same guardrails as G2), and **resolve**
      each escalated finding: **fix** the spec (or amend the principle / reconcile the
      peer ADR), or **refute** —
      ```bash
      python "${CLAUDE_PLUGIN_ROOT}/skills/spec-manager/scripts/contradictions.py" \
        resolve --project . --spec <SPEC-ID> --against <principle:N|SPEC-NNN|ADR-NNN> \
        --verdict <refuted|amended|auto-cleared|superseded> --reason "…"
      ```

   c. **For each changed ADR (`knowledge-base/decisions/ADR-*.md` in the diff),
      run the ADR-level G3 check.** Assemble the ADR comparison set with
      ```bash
      python "${CLAUDE_PLUGIN_ROOT}/skills/spec-manager/scripts/contradictions.py" \
        adr-context --project . --adr <ADR-NNN>
      ```
      This returns `adr` (the changed ADR), `principles` (higher authority), `peer_adrs`
      (all other active ADRs), and `adr_warnings`. Judge the changed ADR's body against:
      - each `principle` → **fix the ADR** (principle outranks);
      - each `peer_adr` → **reconcile** (same tier, both may need amending).

      Surface `adr_warnings`. Triage findings with the same auto-clear / retire /
      escalate guardrails as G2. Resolve each escalated finding — **fix** the ADR (or
      reconcile the peer), or **refute** —
      ```bash
      python "${CLAUDE_PLUGIN_ROOT}/skills/spec-manager/scripts/contradictions.py" \
        resolve --project . --spec <ADR-NNN> --against <principle:N|ADR-NNN> \
        --verdict <refuted|amended|auto-cleared|superseded> --reason "…"
      ```

   "Ignore and push" is not a resolution; contradictions are resolved in the cycle that
   raised them (no backlog). Fail-open on no changed specs/ADRs / no principles /
   tooling error.

7. **Declarative-drift check (governance P4b — resolve-to-proceed).** After the
   contradiction check, verify whether the code changed in this cycle contradicts any
   *declared* intent (spec `intentional_decisions` / spec prose, or an accepted ADR's
   body). Same posture as steps 5 and 6: **model judgment → procedural gate**, never a
   script hard-block, never auto-fail on model confidence; wrap-up **must not complete
   while a finding is unresolved.**

   a. **Gather the drift context** (reuse the same `$BASE` from step 3):
      ```bash
      python "${CLAUDE_PLUGIN_ROOT}/skills/spec-manager/scripts/drift.py" \
        context --base "$BASE" --project .
      ```
      This returns `{base, impact_source, impact_count, targets, warnings}`. Each
      target has `item` (e.g. `SPEC-003` or `ADR-007`), `kind` (`spec` | `adr`),
      `related_code` (the intent's full declared footprint), `hit_paths` (the
      subset of `related_code` inside the blast radius), and either
      `decisions` + `file_path` (spec targets) or `title` + `body` (ADR targets).
      Surface any `warnings` (e.g. malformed ADR). No targets ⇒ **skip** this step
      (nothing in-scope for this change). Fail-open on code-graph absence: when
      `impact_source` is `changed-only` note it to the engineer — the blast radius
      is narrower than normal (bounded to changed files only, not their dependents),
      so some related items may be out-of-scope; this is **never a silent empty set.**

   b. **Judge each target.** For each target, read:
      - The declared intent: for a spec target, the `decisions` list plus the spec's
        `file_path` prose; for an ADR target, the `body` field.
      - The diff of the target's `hit_paths`:
        ```bash
        git diff "$BASE"..HEAD -- <hit_paths>
        ```
      Judge whether anything in that diff **contradicts** the declared intent. Produce
      candidate findings — each naming the item id, the relevant `hit_paths`, and
      **why** the code and the declared intent conflict.

   c. **Triage each finding against prior resolutions.** For each candidate finding:
      ```bash
      python "${CLAUDE_PLUGIN_ROOT}/skills/spec-manager/scripts/drift.py" \
        prior --item <SPEC-NNN|ADR-NNN> --paths <hit_paths>
      ```
      If a prior resolution is returned, **re-validate it against the *current* hunk**
      (not just the file):
      - **Still clearly valid** — the flagged code is the same intentional thing the
        prior reason described, materially unchanged → **auto-clear** and log it:
        ```bash
        python "${CLAUDE_PLUGIN_ROOT}/skills/spec-manager/scripts/drift.py" \
          resolve --item <SPEC-NNN|ADR-NNN> --verdict auto-cleared \
          --reason "re-applied prior refutation; flagged code unchanged" \
          --paths <hit_paths>
        ```
      - **Stale** — the code changed so the prior no longer maps → **retire** it and
        evaluate the finding fresh:
        ```bash
        python "${CLAUDE_PLUGIN_ROOT}/skills/spec-manager/scripts/drift.py" \
          resolve --item <SPEC-NNN|ADR-NNN> --verdict superseded \
          --reason "code changed; prior no longer applies" --paths <hit_paths>
        ```
      - **Now a real conflict** — the prior reason no longer excuses it → **escalate.**

      **Auto-clear guardrails:** re-judge the current hunk against the *specific* prior
      reason, not the file (a new/different conflict in a previously-refuted item
      **escalates**); **bias to escalate** on any ambiguity; a finding with **no prior
      always goes to the human.**

   d. **Resolve every escalated finding with the engineer** — do not complete wrap-up
      until each is resolved as one of:
      - **Fix the code** — change the code to align with declared intent and re-judge.
        No resolution log needed; git records the fix.
      - **Amend the intent** — edit the spec's decision entry or the ADR body to
        reflect the new direction, **then** log the amendment:
        ```bash
        python "${CLAUDE_PLUGIN_ROOT}/skills/spec-manager/scripts/drift.py" \
          resolve --item <SPEC-NNN|ADR-NNN> --verdict amended \
          --reason "<how/why the declared intent changed>" --paths <hit_paths>
        ```
      - **Refute** (false positive — the conflict isn't real):
        ```bash
        python "${CLAUDE_PLUGIN_ROOT}/skills/spec-manager/scripts/drift.py" \
          resolve --item <SPEC-NNN|ADR-NNN> --verdict refuted \
          --reason "<why it does not actually contradict>" --paths <hit_paths>
        ```

   "Ignore and push" is **not** a resolution. Drift findings are resolved in the
   wrap-up that raised them (no backlog debt). Fail-open on no code-graph / no
   targets / any tooling error — note it and continue. `drift.py gaps` is on-demand
   only and **must NOT run here.**

> Scope: this phase runs the **affected** accepted behaviors via the behavior graph
> (Direction A) with deterministic-only blocking and records coverage fingerprints
> (Phase 2), then **surfaces** the affected proposed/confirmed behaviors and
> uncovered touched code for confirmation — advisory, never blocking (SP3).
> Model judgment enters here as the **principle checkpoint** (G2, step 5: code-vs-principle),
> the **contradiction check** (G3, step 6: intent-vs-intent), and the
> **declarative-drift check** (P4b, step 7: code-vs-declared-intent) — all
> resolve-to-proceed, procedural, never a script hard-block. Ordering: deterministic
> facts (G1 + links + **adr verify** + accepted-behavior run) → G2 principle checkpoint
> (step 5) → G3 intent-coherence (step 6) → P4b declarative-drift (step 7).

### Phase 4: Security Scan

Run `/freya-devkit:codebase-security-scan update` for incremental security analysis.

This creates/updates the security report in `/knowledge-base/security/codebase-security/`.

> Note: `update` now includes lightweight in-loop adversarial verification of each finding (synchronous, no background workflow), so it composes cleanly inside this linear pipeline. Do **not** substitute `/freya-devkit:codebase-security-scan audit` here — `audit` is a heavier, on-demand Workflow-powered mode that must not run inside wrap-up.

The `.security-last-scan` file will point to the code commit. The artifacts commit will be one ahead, but this is harmless since it contains no code to scan.

### Phase 5: Artifacts Commit

0. Advance the declared-intent baseline to the commit being wrapped (only reached
   because the Phase 3.5 gate passed):
   ```bash
   python "${CLAUDE_PLUGIN_ROOT}/skills/spec-manager/scripts/verify_intent.py" --project . --advance
   ```
   Stage `knowledge-base/intents/` (any new `INTENT-NNN.md` and the updated
   `.intent-last-verified`) with the other artifacts.

0. **Refresh the backlog.** Regenerate the generated, git-tracked backlog so it
   reflects the just-synced state:
   ```bash
   python "${CLAUDE_PLUGIN_ROOT}/skills/status/scripts/collect_status.py" \
     --project . --write-backlog >/dev/null
   ```
   Stage `knowledge-base/BACKLOG.md` with the other artifacts below.

1. Stage all artifact changes:
   - Updated docs
   - Updated specs
   - Security report
   - Updated dependency graph
   - Tracking files
   - `knowledge-base/BACKLOG.md`
   - `knowledge-base/decisions/ADR-*.md` + `decisions/README.md`
   - `knowledge-base/drift-resolutions.jsonl`
   - `proposed`/unaccepted behavior scaffolds (still carrying `TODO(scaffold)`)
2. Generate artifacts commit message (or use pattern: `docs: update docs, specs, and security report`)
3. Create the commit

## Commit Message Generation

When no message is provided, the skill analyzes changes to generate a message:

1. Run `git diff --stat` to see changed files
2. Run `git log -1 --pretty=%s` to see recent commit style
3. Categorize changes:
   - New features (new files, new routes, new components)
   - Bug fixes (modified existing files, test changes)
   - Refactoring (moved files, renamed functions)
   - Documentation (knowledge-base/ changes only)
4. Generate appropriate prefix (feat/fix/refactor/docs/chore)
5. Summarize the main changes

## Example Session

```
> /freya-devkit:wrap-up

Running post-implementation workflow...

[Phase 0] Checking for code changes...
  Found uncommitted code changes
  Staging: src/lib/auth/passkeys.ts, src/api/routes/auth.ts

Generated commit message:
  feat: add user authentication with passkeys

Proceed with code commit? [Y/n]

> Y

Created commit: abc123def (code)

[1/5] Updating dependency graph...
  - 3 files changed since last build
  - Graph updated

[2/5] Updating documentation...
  - API.md updated
  - ARCHITECTURE.md updated

[3/5] Updating specifications...
  - SPEC-003 updated (auth flow)
  - Certainty: 85%

[4/5] Behavior integrity & accepted-behavior run (Phase 3.5)...
  - Link / ADR / declared-intent checks: OK
  - 1 affected accepted behavior re-run: passed
  - Principle / contradiction / drift checkpoints: clear

[5/5] Running security scan...
  - 0 new findings
  - Report: knowledge-base/security/codebase-security/2024-03-26.md

Staging artifact changes...

Generated commit message:
  docs: update docs, specs, and security report

Proceed with artifacts commit? [Y/n]

> Y

Created commit: abc124def (artifacts)

Done! Your feature is now fully documented, specified, and secured.

Summary:
  abc123def: feat: add user authentication with passkeys
  abc124def: docs: update docs, specs, and security report
```

### When code is already committed (e.g., from security-resolver)

```
> /freya-devkit:wrap-up

Running post-implementation workflow...

[Phase 0] Checking for code changes...
  No uncommitted code changes
  Latest commit: fix(security): resolve SEC-001, SEC-003

[1/5] Updating dependency graph...
  - Graph updated based on latest commit

[2/5] Updating documentation...
  - API.md updated

[3/5] Updating specifications...
  - specs updated to reflect security fixes

[4/5] Behavior integrity & accepted-behavior run (Phase 3.5)...
  - Deterministic link / ADR / declared-intent gates: OK
  - Affected accepted behaviors re-run: passed

[5/5] Running security scan...
  - Scanning changes since pre-fix commit
  - 0 new findings (fixes confirmed!)
  - Report: knowledge-base/security/codebase-security/2024-03-26.md

Staging artifact changes...

Created commit: abc124def (artifacts)

Done! Artifacts committed separately from code changes.
```

## Requirements

This skill requires the following skills to be available:
- `/freya-devkit:code-graph` - Dependency graph
- `/freya-devkit:docs-manager` - Documentation management
- `/freya-devkit:spec-manager` - Specification management
- `/freya-devkit:behavior-graph` - Behavior graph (Phase 3.5 build/check/surface)
- `/freya-devkit:behavior-runner` - Runs accepted behaviors, captures coverage
- `/freya-devkit:codebase-security-scan` - Security scanning

If any skill is missing, the skill will warn you and skip that step.

## Skipping Steps

You can skip specific steps if needed:

```
/freya-devkit:wrap-up --no-security    # Skip security scan
/freya-devkit:wrap-up --no-docs        # Skip documentation update
/freya-devkit:wrap-up --no-specs       # Skip specification update
/freya-devkit:wrap-up --no-graph       # Skip dependency graph update
```

Multiple flags can be combined:

```
/freya-devkit:wrap-up --no-security --no-specs "fix: typo in README"
```

## Error Handling

If any step fails:
1. Report the error clearly
2. Ask if you want to continue with remaining steps
3. If you decline, stop and let you fix the issue

You can then re-run `/freya-devkit:wrap-up` after fixing the problem.

## When to Use

Use `/freya-devkit:wrap-up` after:
- Implementing a new feature
- Fixing a bug
- Refactoring code
- Making significant changes

Use it BEFORE pushing to ensure all documentation and security checks are current.

## When NOT to Use

Don't use `/freya-devkit:wrap-up` for:
- Work-in-progress commits (use regular git commit)
- Temporary changes
- Experimental code
- Changes that don't need documentation
