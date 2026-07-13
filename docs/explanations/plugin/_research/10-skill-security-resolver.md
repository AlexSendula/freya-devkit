# Skill: codebase-security-resolver

> Research brief for the freya-devkit plugin-wide explainer.
> Source of record: `skills/codebase-security-resolver/SKILL.md` (the skill directory contains **only** this one file — no `scripts/`, `references/`, or `evals/`).

---

## 1. What it is

`codebase-security-resolver` is the **consumer/actor half** of the freya-devkit security loop. Where `codebase-security-scan` (and its deeper `codebase-security-audit` engine) *produce* a security report, the resolver *reads that report and does something about each finding* — interactively.

It is not a scanner. It does not discover vulnerabilities. It takes an already-written report of findings and drives an end-to-end interactive workflow: **list findings → user selects → validate → summarize → confirm → plan → implement → commit code → hand off to `wrap-up`**.

From the frontmatter description (verbatim):

> "Resolve security findings from the codebase security scan interactively."

> "WORKFLOW: Lists findings → user selects -> validate findings → summarize with validation notes -> confirm -> enter plan mode → implement → commit code → run /freya-devkit:wrap-up"

Note: the entire skill is **prose instructions for the agent** — there is no executable resolver binary/script. The shell snippets in SKILL.md are illustrative commands the agent runs ad hoc (e.g. `test -f`, `grep -n`, `git branch --show-current`), not a packaged CLI. See "Honest limits" §9.

---

## 2. Why it exists

A raw security scan report has two problems the resolver is designed to solve:

1. **Findings need action, not just reading.** Someone has to decide which findings to fix, verify they are still real, implement the fix without breaking dependents, and commit cleanly. The resolver structures that into a repeatable interactive workflow.

2. **Not every finding should be "fixed."** Some findings are stale (reference deleted code), already resolved, misclassified (a scalability concern, not a security one), or represent an **intentional design decision**. The resolver's distinguishing feature is a **"metadata cleanup" lifecycle**: it routes these non-fix findings to the right terminal state — updating the report status and, for intentional ones, writing the decision back into the specs (via `spec-manager`) so future scans have context and don't re-flag them as bugs.

This is the concrete mechanism behind the plugin's recurring theme: "document intentional design decisions that might look like bugs/security issues."

---

## 3. Inputs & outputs

### Input: the security report

Reads findings from (verbatim path):

```
/knowledge-base/security/codebase-security/
├── latest.md          # Most recent scan (symlink or copy)
└── YYYY-MM-DD.md      # Dated reports
```

### Expected finding format

Each finding in the report should have:
- **ID** (e.g. `SEC-001`)
- **Severity** (critical, high, medium, low, info)
- **Title/Description**
- **Affected file(s)**
- **Status** (`CONFIRMED`, `POTENTIAL`, `FIXED`)
- **Recommendation**
- **Verification** (optional) — e.g. `"Upheld 2/2"` or `"Needs review · split"`. Present only in reports produced *after adversarial verification was added* to the scan; absent in older reports. Instruction: "Read it only if present."

### Severity indicators (verbatim table)

| Severity | Indicator | Priority |
|----------|-----------|----------|
| critical | 🔴 | Fix immediately |
| high | 🟠 | Fix soon |
| medium | 🟡 | Fix when possible |
| low | 🟢 | Consider fixing |
| info | ℹ️ | Informational |

### Outputs

- **Code changes** committed as a `fix(security): ...` commit (Phase 11).
- **Report mutations** — finding statuses updated in place (CONFIRMED → RESOLVED / INTENTIONAL / INFO / OBSOLETE).
- **Spec entries** — for intentional findings, an entry added to a specs file (example path used in SKILL.md: `knowledge-base/specs/security.decisions.md`).
- A **security fix branch** (`security/fix-YYYY-MM-DD`) when starting from `main`.
- Artifacts (docs/specs/graph/fresh scan) are **not** produced by the resolver itself — they are delegated to `wrap-up` (Phase 12).

---

## 4. Commands / CLI (verbatim)

Quick-reference table from SKILL.md:

| Command | Description |
|--------|-------------|
| (default) | interactive: list findings, select, validate, confirm, plan, fix, wrap-up |
| `list [--severity]` | Show findings (optionally filtered by severity) |
| `fix <ids...>` | Fix specific findings by ID (skip selection) |
| `fix --critical` | Fix all critical findings |
| `fix --high` | Fix all critical + high findings |
| `fix --dry-run` | Preview what would be fixed (no changes) |
| `status` | Quick count by severity + last scan date |
| `review` | Show what was fixed in last session |

Invocation forms seen in the body (verbatim):

```
/freya-devkit:codebase-security-resolver               # default interactive
/freya-devkit:codebase-security-resolver list
/freya-devkit:codebase-security-resolver list --critical   # Only critical
/freya-devkit:codebase-security-resolver list --high       # Critical + high
/freya-devkit:codebase-security-resolver list --medium     # Critical + high + medium
/freya-devkit:codebase-security-resolver fix SEC-001
/freya-devkit:codebase-security-resolver fix SEC-001 SEC-003 SEC-007
/freya-devkit:codebase-security-resolver fix --critical    # Fix all critical
/freya-devkit:codebase-security-resolver fix --high        # Fix all critical + high
/freya-devkit:codebase-security-resolver fix --dry-run
```

**Flag semantics worth noting (verbatim from body):**
- `list --high` = "Critical + high" (cumulative, not high-only). Same cumulative logic for `fix --high` ("Fix all critical + high") and `list --medium` ("Critical + high + medium").
- `fix --dry-run` = "Preview what would be fixed without making any changes."

**Gotcha:** The Quick-Reference table documents `status` and `review` commands, but the "Commands" section of SKILL.md provides detailed sub-sections **only** for the default workflow, `list`, `fix <ids...>`, and `fix --dry-run`. `status` and `review` have no detailed spec beyond the one-line table entry (see gotchas §10).

---

## 5. How it works — the phased pipeline

The default interactive command is a 12-phase (with sub-phases) sequence. The `fix <ids...>` command is a shortened path through the same phases.

**Phase 1: Load Report** — read `latest.md` from the report location.

**Phase 2: Present Findings** — display findings.

**Phase 3: Interactive Selection** — user picks which findings to act on.

**Phase 4: Validate Findings** — before confirming, validate each selected finding against the *current* code. Three checks:
1. **Code exists** — does the affected file/line still exist?
2. **Vulnerability applicable** — is the vulnerability still present?
3. **Dependency exists** — does referenced code/package still exist?

Validation is done with ad-hoc shell (verbatim examples): `test -f src/api/users.ts`, `grep -n "searchUsers" src/api/users.ts`, `grep -n "tiptap" package.json`. Stale findings get a ⚠️ and an alternative action ("Update spec as intentional", "Remove finding from report").

**Phase 4 also: Impact Analysis (via `/freya-devkit:code-graph`)** — for each finding, find the function/component at the affected line, query code-graph for dependents, and assess fix complexity from blast radius. Special case: **dead-code detection** — if a finding's location has **0 direct dependents**, the recommendation flips to *DELETE the file instead of fixing* ("Eliminates vulnerability entirely").

**Phase 4.5: Metadata Cleanup Detection** — for findings that will be *skipped* (not code-fixed), classify into one of four cleanup categories (this is the finding-lifecycle core):

| Category | Meaning | Action |
|----------|---------|--------|
| `ALREADY_RESOLVED` | Code fix already exists | Update report status to RESOLVED |
| `INTENTIONAL_DESIGN` | Valid finding but intentional decision | Check spec, add if missing + update report to INTENTIONAL |
| `OUTDATED_FINDING` | References removed code/dependencies | Remove from report or mark as OBSOLETE |
| `MISCLASSIFIED` | Not a security issue (e.g. scalability) | Move to appropriate doc or mark as INFO |

**Phase 5: Summary of Selected Findings** — a two-block summary: **CODE FIXES** table + **METADATA CLEANUP** table, with a total line like "2 code fixes + 3 metadata updates."

**Phase 6: Confirm to continue** — uses `askUserQuestion` with options `[Yes, continue]  [I have concerns about these findings]  [Cancel]`. If the user has concerns, the skill investigates each: if the user is right it adjusts the fix list; if the user may be wrong it makes the case for why the fix is still needed, then re-presents. Worked examples in SKILL.md cover a "we don't need Redis / single-instance app" concern (→ skip or document as intentional) and a "not sure we still have tiptap" concern (→ grep proves it's gone → the finding becomes a *real* code fix: tighten CSP).

**Phase 7: Final Confirmation** — shows the final fix list plus a ⚠️ Skipped section, then `[Yes, continue]  [Cancel]`.

**Phase 8: Branch Check** — verbatim logic:

```bash
current_branch=$(git branch --show-current)
if [ "$current_branch" = "main" ]; then
  today=$(date +%Y-%m-%d)
  git checkout -b "security/fix-$today"
else
  echo "Staying on branch: $current_branch"
fi
```
Rule: on `main` → create `security/fix-YYYY-MM-DD`; on a feature branch → stay put. "Security fixes should be done in isolation."

**Phase 9: Enter Plan Mode** — uses the `EnterPlanMode` tool. The plan is split into **PART 1: CODE FIXES** (each with file, fix direction, and code-graph blast radius: "Direct changes", "May need updates", "Safe to proceed") and **PART 2: METADATA CLEANUP** (the skipped findings with their spec/report actions).

**Phase 10: Implementation** — implement each fix; after each, run a quick code-graph check on changed files, verify dependents still compile, flag breaking changes immediately. If a fix changes a function signature, it surfaces affected dependents with options `[Update all dependents]  [Revert and try different approach]  [Show details]`.

**Phase 10.5: Final Impact Check** — after all fixes, check dependents of all changed files; "Codebase integrity: VERIFIED".

**Phase 10.6: Metadata Cleanup Execution** — actually apply the Phase 4.5 actions:
- **INTENTIONAL_DESIGN** → check spec for existing entry; if absent, add via `/freya-devkit:spec-manager` (example: add CSP/Tiptap decision to `knowledge-base/specs/security.decisions.md`); update report status CONFIRMED → INTENTIONAL with a spec reference link.
- **ALREADY_RESOLVED** → verify the fix is present in code (grep for the guard), update report CONFIRMED → RESOLVED with file/line note.
- **MISCLASSIFIED** → update report CONFIRMED → INFO, change severity HIGH → INFO, add note that it is architectural not security.

**Phase 11: Commit Code Changes** — commit code fixes *before* wrap-up:

```bash
git add <changed files>
git commit -m "fix(security): resolve SEC-001, SEC-003, SEC-007"
```
Rationale (verbatim): "Security scan update needs a commit hash to diff against. Wrap-up will handle the artifacts (docs, specs, scan) in a follow-up commit. Clean separation: code fixes in one commit, generated artifacts in another."

**Phase 12: Wrap-Up** — call `/freya-devkit:wrap-up`, which detects code is already committed (skips its Phase 0), updates graph/docs/specs, runs a fresh scan (confirming fixes by diffing against the pre-fix commit), and commits all artifacts together. Net result is the **two-commit pattern**:

```
commit A: fix(security): resolve SEC-001, SEC-003
commit B: docs: update docs, specs, and security report
```

---

## 6. Finding lifecycle (the mental model)

A finding enters as `CONFIRMED` / `POTENTIAL` and exits into exactly one terminal state:

```
                        ┌──> code-fixed ──> RESOLVED (via fresh scan in wrap-up)
CONFIRMED / POTENTIAL ──┤
   (from scan report)   ├──> ALREADY_RESOLVED  ──> report: RESOLVED
                        ├──> INTENTIONAL_DESIGN ──> spec entry + report: INTENTIONAL
                        ├──> OUTDATED_FINDING   ──> report: OBSOLETE / removed
                        └──> MISCLASSIFIED      ──> report: INFO (severity downgraded)
```

Key insight: **skipping a finding is not a no-op.** Tip 4 (verbatim): "Skipped findings still get attention. The skill updates the report and adds spec entries so future scans have context." This closes the loop so the next scan doesn't re-surface a decision that was already made.

---

## 7. How it composes with other skills

### `code-graph` (blast-radius engine)
Used at four points (verbatim list):
1. **Validation** — detect dead code vs active code.
2. **Planning** — include blast radius in the implementation plan.
3. **Implementation** — verify changes don't break dependents.
4. **Post-implementation** — final integrity check.

Commands referenced (verbatim):
- `/freya-devkit:code-graph dependents <file>` — files that import/use a file.
- `/freya-devkit:code-graph impact <file>` — blast radius for changes.

### `spec-manager` (intentional-decision sink)
Used for metadata cleanup:
1. **INTENTIONAL_DESIGN** — add intentional design decisions to spec.
2. **Validation** — check if the intentional design is already documented.
"When a finding is marked as intentional but not in spec, the skill adds it automatically."

### `wrap-up` (artifact finisher)
Phase 12 hands off. Resolver commits code; wrap-up commits generated artifacts + re-scans to confirm.

### Relationship to the scan side
The resolver is downstream of `codebase-security-scan` / `codebase-security-audit`, which produce the report it reads. The optional `Verification` field ("Upheld n/n" / "Needs review · split") is the interface point with the scan's adversarial verification.

---

## 8. Degradation behavior

- **No security report present:** the entire workflow is predicated on `latest.md` existing under `/knowledge-base/security/codebase-security/`. UNVERIFIED what the skill does if the report is missing — SKILL.md does not specify a fallback (see gotchas).
- **Older reports without `Verification` field:** explicitly handled — "If the field is absent (older report), fall back to normal validation." Verification is read "only if present."
- **`code-graph` availability:** the skill leans on code-graph for impact analysis but SKILL.md does not state explicit behavior if code-graph is unavailable. The scan-side pattern is "when available"; UNVERIFIED whether resolver degrades gracefully without it.
- **Stale/false-positive findings:** first-class handled — Phase 4 validation catches findings whose code no longer exists, routing them to metadata cleanup rather than a broken fix.

---

## 9. Honest limits / what's actually implemented

- **The skill is instruction prose, not code.** There is no resolver script, parser, or binary in the skill directory — only `SKILL.md`. All "output" blocks (tables, ✅/⚠️ lines, "Codebase integrity: VERIFIED") are *illustrative templates* the agent is expected to reproduce, not output emitted by a program. Actual behavior depends on the agent following the instructions.
- **Report format is a convention, not enforced.** The expected finding fields (ID, Severity, Status, etc.) are what the skill *hopes to find*; nothing validates the report schema. If the scan writes a differently-shaped report, parsing is best-effort by the agent.
- **`status` and `review` are under-specified.** They appear only in the quick-reference table with a one-line description each; there is no phase/example spec for them.
- **Dates in examples are illustrative** (`security/fix-2024-01-15`); the real branch uses `$(date +%Y-%m-%d)`.

---

## 10. Gotchas (incl. UNVERIFIED)

- **UNVERIFIED — missing report behavior:** SKILL.md does not describe what happens if there is no `latest.md` / no scan has ever run. Assume the agent must surface an error or suggest running a scan first, but this is not written.
- **UNVERIFIED — `status` / `review` mechanics:** no detailed spec; how they read "last session" state (git log? report diff?) is not documented.
- **UNVERIFIED — code-graph-unavailable degradation:** not stated for the resolver specifically.
- **`--high` is cumulative** ("critical + high"), not high-severity-only. Easy to misread. Same for `--medium` and `fix --high`.
- **Two-commit ordering is load-bearing:** code must be committed (Phase 11) *before* wrap-up, because the fresh scan diffs against that commit hash to confirm fixes. Skipping the intermediate commit breaks fix-confirmation.
- **Spec path is an example:** `knowledge-base/specs/security.decisions.md` is used illustratively; the actual target is whatever `spec-manager` owns.
- **Sanitization note:** SKILL.md's running examples reference a "tiptap editor" / "DOMPurify" / CSP `unsafe-inline` scenario and IDs like `SEC-H2`. These are illustrative teaching examples in the public skill file, not proprietary content, and are safe to reference generically.

---

## 11. Verbatim quotable lines

- "Resolve security findings with an interactive selection and planning workflow." (SKILL.md:22)
- "WORKFLOW: Lists findings → user selects -> validate findings → summarize with validation notes -> confirm -> enter plan mode → implement → commit code → run /freya-devkit:wrap-up" (frontmatter)
- "Assessment: Dead code - no callers found / Recommendation: DELETE the file instead of fixing" (SKILL.md ~171–173)
- "For findings that are skipped (outdated, already resolved, or intentional), determine what cleanup is needed" (SKILL.md:179)
- "Metadata cleanup matters - Skipped findings still get attention. The skill updates the report and adds spec entries so future scans have context." (Tip 4)
- "Dead code can be deleted - If code-graph shows no dependents, consider deletion instead of fixing. This eliminates the vulnerability entirely." (Tip 3)
- "Clean separation: code fixes in one commit, generated artifacts in another." (Phase 11)
- "Findings marked `Upheld n/n` are high-confidence; prioritize them. Findings marked `Needs review · split` survived verification only weakly — confirm them manually during Phase 4 before fixing." (Tip 10)
- "Trust but verify - The validation phase catches false positives, but your domain knowledge is valuable too." (Tip 9)

---

## Source files read
- `skills/codebase-security-resolver/SKILL.md` (only file in the skill directory)
