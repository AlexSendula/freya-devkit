---
name: freya-codebase-security-scan
description: |
  Performs a comprehensive security audit of an entire codebase. The `freya security`
  driver fans out over the six security categories on its own worker pool and verifies
  every finding with three adversarial lenses, so the parallelism does not depend on
  the agent choosing to delegate. Reads /knowledge-base/reference for project context
  first, then reports findings, severity ratings and remediation steps to
  /knowledge-base/security/codebase-security/.

  TRIGGER when: user asks to "scan codebase for security", "security audit", "code security check",
  "check for vulnerabilities in code", "security review", "audit my code", mentions "codebase security",
  "application security", or wants a comprehensive security assessment beyond just dependencies.

  INTEGRATION: uses freya-code-graph for incremental scanning and blast-radius analysis, and
  freya-spec-manager to cross-reference findings against intentional design decisions, when
  those skills are available.
---

# Codebase Security Scan

This skill performs a comprehensive security audit of your entire codebase using specialized
per-category scans.

## Overview

1. **Context Gathering**: Read project docs from `/knowledge-base/reference` to understand architecture, auth, data flows
2. **Spec Loading**: Read specs from `/knowledge-base/specs/` to understand intentional design decisions
3. **Category Scanning**: `freya security scan` — one self-contained agent task per security category, scheduled by the driver
4. **Validation Phase**: Verify findings against online sources AND specs to eliminate false positives
5. **Aggregation**: Combine validated findings into a comprehensive security report
6. **Re-evaluation**: Compare against previous reports to track finding lifecycle (RESOLVED, PERSISTENT, REGRESSED)
7. **Report Generation**: Save to `/knowledge-base/security/codebase-security/YYYY-MM-DD.md`

## Commands

| Command | Description |
|---------|-------------|
| `scan` | Full codebase security scan (all files), run by the `freya security scan` driver. **Paid** — spawns headless agent workers. |
| `update` | Incremental scan - only files affected by recent changes. Free: stays in the main loop, including on its first run. |
| `audit` | Exhaustive discovery + adversarial verification (`freya security audit`). On-demand / pre-release. **Paid**, and the expensive one. |
| `impact <file>` | Show security blast radius for a specific file |
| `check-specs [report]` | Cross-reference findings against specs to identify intentional design |
| `help` | Display help information |

**Recommendation:** Use `update` for day-to-day security checks after code changes — it is the only mode `freya-wrap-up` runs, and the only free one. Use `scan` for an initial security assessment or a complete audit when the user has agreed to the spend. Use `audit` periodically (e.g. before a release) for an exhaustive multi-agent deep audit — it is heavier and is **not** part of the `freya-wrap-up` pipeline. Use `check-specs` to validate existing findings against project specifications.

`scan` and `audit` are two presets of the same driver: both fan out over the six categories on a worker pool and verify every finding with three adversarial lenses; `scan` runs one round of discovery, `audit` loops until dry. `update` stays in the main loop — it is scoped to a git diff and its blast radius, which the driver has no way to express — and verifies its findings with the lighter Step 3.5 pass.

## Workflow

### Step 1: Gather Project Context

First, read documentation from `/knowledge-base/reference` to understand:
- Application architecture and components
- Authentication and authorization mechanisms
- Data flows and sensitive data handling
- API endpoints and external integrations
- Infrastructure and deployment setup

Look for files like:
- `architecture.md` or `system-design.md`
- `api.md` or `endpoints.md`
- `auth.md` or `authentication.md`
- `data-flow.md`
- `deployment.md` or `infrastructure.md`
- `README.md`

If no docs exist, note this and proceed with codebase scanning.

### Step 2: Load Project Specs

**CRITICAL for accurate security assessment.** Read specifications from `/knowledge-base/specs/` to understand intentional design decisions that might appear as security issues.

Look for:
- Feature specs in `/knowledge-base/specs/features/`
- Security-relevant decisions (auth patterns, access control, data exposure)
- Any spec with `security_implications` or `intentional` markers

**Why this matters:**
A security scan might flag "Missing role check on DELETE - any authenticated user can delete any post" as a vulnerability. But if the spec says "Any authenticated user can CRUD posts", this is **intentional design**, not a security flaw.

**Spec patterns to look for:**
```yaml
# Example spec that affects security interpretation
decision: "Any authenticated user can perform CRUD on posts"
rationale: "This is a collaborative tool where all users have equal access"
security_implications: "No role-based access control needed for post operations"
```

If no specs exist, note this and proceed (but warn that findings may include intentional design decisions).

**Also cross-reference accepted behaviors.** Beyond declarative specs, an
`accepted` behavior whose intent explains a finding is the **strongest**
"intentional" evidence on offer — which is not the same thing as a verified
guarantee, and the query says so itself. When validating findings (in
`scan`/`update` as well as `check-specs`), apply the behavior cross-reference
exactly as in **`check-specs` Phase 3**: run `behavior-graph --covering
<finding-file>`, judge whether an accepted behavior explains the finding, and on
a match mark it intentional with `behavior_ref` plus the query's `evidence`
string copied verbatim. `proposed`/`confirmed` never downgrade; they stay open.

### Step 3: Run the Security Category Scans

**Run the driver — do not schedule the six category scans yourself.**

```bash
freya security scan --project . --yes
```

**`--yes` is not optional here, and the money gate moves into this loop.** Without
it the driver asks for confirmation, and an agent shell has no tty to answer with —
it declines on your behalf and exits `4` having run nothing. So: tell the user what
this costs *before* you run it (`--dry-run` prints the plan and spends nothing), get
their go-ahead in the conversation, and then pass `--yes`. The prompt the driver
would have shown is one you cannot see; the one you show the user is one they can.

`freya security scan` owns the fan-out: it makes one call per category, on its own
worker pool, with a read-only tool allowlist, then dedups by
`file + line-window + category`, runs three adversarial lenses per surviving finding,
and prints a JSON array of verified findings on stdout. It writes nothing.

**Why the driver and not a prose instruction.** This skill used to ask the agent to
run the six category scans as independent tasks. Validation on GitHub Copilot showed
it running them itself, as a sequence of greps, and then reporting "six category
scans run in parallel" — and an agent's own account of its work cannot be used to
tell the difference. Scheduling the work in the driver is the only version of that
guarantee that is not a suggestion.

**`scan` vs `audit`, same driver:** `scan` runs **one** round of discovery; `audit`
loops until dry (max 5). Both verify every finding with the same three skeptic
lenses — the preset never buys cheapness out of the verification pass, because a
single lens's refutation is a unanimous one and would drop a real finding silently.
Worst case at three findings: 16 agent tasks for `scan`, 40 for `audit`.

**Read the exit code before you read the findings:**

| Exit | Meaning | What to do |
|---|---|---|
| `0` | Complete. The JSON array is the whole result. | Skip Step 3.5 — the driver already ran it — and go to **Step 4: Aggregate Findings**. The driver's three lenses do not include the currency check, so still run the Validation Phase's online checks on what survived. |
| `3` | **Incomplete** — the call ceiling stopped the run early, some tasks got no usable answer, or discovery found more than `--max-findings` and discarded the rest. Its banner names how many. | Report the findings, and record that coverage was truncated — quote the count. **Never** describe this run as clean. |
| `2` | Failed — bad project path, no usable answers, the context call failed, or the ceiling is too low to verify even one finding. | Report the error. Do **not** write a report; there are no results to write. |
| `4` | **Declined** — the driver asked to confirm the spend and got no answer: either the user said no, or the shell has no tty and `--yes` was not passed. | Nothing ran, nothing was spent. Do **not** fall back to the in-loop scan — the driver is right there. Re-run with `--yes`, or take the refusal to the user. |
| `1` | **No agent CLI is usable** — either none is installed, or the one found was refused. The driver prints which, per CLI, on stderr. | Fall back to the in-loop scan below, and quote the driver's stderr. |

**Exit `1` means one thing: no agent CLI can be started.** It does *not* mean
"declined" or "no tty" — those used to land here, which is how a perfectly healthy
driver got read as a missing CLI and the whole fan-out quietly reverted to the prose
version this step exists to replace. Those are `4` now.

**But "cannot be started" now has two causes, and they need different words to the
user.** A CLI can be absent, or it can be present and *refused*: argv[0] must be an
absolute path, and it must not resolve inside the project being audited — a `claude`
a scanned repository shipped is not one the operator installed (SEC-003, ADR-030). So
do not tell the user to install a CLI on the strength of the exit code alone. Read the
stderr, which names each CLI and why it was unusable, and quote that line. The
fallback action is the same either way; the sentence you write about it is not.

**An empty array with exit `0` means clean. An empty array with any other exit code
means the scan did not run.** The driver refuses to exit `0` when no task got a
usable answer, precisely so a broken run cannot be mistaken for a clean codebase.

`--max-calls` (default 200 attempts) is the single cost knob, `--concurrency` sets the
pool width, `--yes` answers the confirmation up front, and `--dry-run` prints the plan
and spends nothing. Set `--max-calls` too low and the driver refuses to start (exit
`2`) rather than run a scan whose ceiling cannot pay to verify a single finding — a
configuration that can only ever report a false clean.

**`--agent` and `--model` go together.** `--agent` picks the worker CLI (`claude` or
`copilot`); without it the driver autodetects, preferring `claude` because it reports
per-call spend. `--model` names a model **of that CLI**, and the two vocabularies do
not overlap — observed live in phase 7, a Copilot model name handed to an
autodetected `claude` worker failed the whole run with `unrecognized_model`. Pass
both, or neither.

#### Fallback: no agent CLI on PATH (exit `1`)

The driver needs `claude` or `copilot` installed. Without one, run the same six
category scans in this agent's main loop instead — the categories below are exactly
the ones the driver uses. Run them **in parallel if your agent supports subagents**;
one at a time otherwise. On a small project the result is the same, only slower; on
a large one a sequential run accumulates every task's reading context in a single
window and may not fit, so narrow the scope — fewer files, or fewer categories per
run — rather than letting it truncate. Then verify the findings using Step 3.5.

*Either way the categories are the same, and either way they are independent — none
reads another's output, and each returns a compact list of candidate findings rather
than file contents.*

#### Category 1: Authentication & Authorization
Scan for:
- Hardcoded credentials, API keys, tokens
- Weak password policies
- Missing authentication checks
- Insecure session management
- Broken access control patterns
- JWT/oauth misconfigurations

#### Category 2: Input Validation & Injection
Scan for:
- SQL injection vulnerabilities
- XSS (cross-site scripting) patterns
- Command injection risks
- Path traversal vulnerabilities
- SSRF (server-side request forgery)
- Unsafe deserialization
- Missing input sanitization

#### Category 3: Secrets & Sensitive Data
Scan for (report the location and a fingerprint, never the value — see [Redaction](#redaction)):
- Exposed secrets in code (API keys, passwords, tokens)
- Sensitive data in logs
- PII exposure risks
- Insecure data storage
- Missing encryption for sensitive data
- Hardcoded encryption keys or IVs

#### Category 4: API & Network Security
Scan for:
- Missing rate limiting
- CORS misconfigurations
- Missing HTTPS enforcement
- Insecure API endpoints
- Missing input validation on APIs
- Exposed internal APIs
- GraphQL security issues

#### Category 5: Configuration & Dependencies
Scan for:
- Debug mode enabled in production
- Exposed admin endpoints
- Insecure default configurations
- Missing security headers
- Outdated or insecure middleware
- Environment variable exposure

#### Category 6: File & Resource Handling
Scan for:
- Unsafe file upload handling
- Path traversal in file operations
- Missing file type validation
- Insecure temporary file handling
- Resource exhaustion vulnerabilities
- Unsafe file permissions

Concurrent scanning costs roughly 7× the tokens of a sequential pass, because each
worker carries its own context window. Running the categories one at a time trades
wall-clock for spend; it does not change what is scanned. (Under the driver the same
trade is `--concurrency 1` — a flag this fallback path, by definition, cannot use.)

### `freya-codebase-security-scan update` (Incremental Scan)

Git-aware incremental security scan using code-graph impact analysis.

**Workflow:**

**Phase 1: Change Detection**
1. Read `.security-last-scan` from `knowledge-base/security/` for last commit hash
2. If missing (the first run on this project): there is no diff to be incremental
   about, so cover the whole codebase — but do it **in the main loop, never the
   driver.** Run the six categories over all files exactly as in the Step 3
   fallback, then verify with Step 3.5. Say so in the summary: "first run — full
   in-loop pass, no diff available yet."

   **Why not `scan`.** `scan` is the paid driver now. `update` is what
   `freya-wrap-up` runs on every wrap-up, and wrap-up promises in writing that it
   spends nothing (see its Phase 4 note). A fallback into `scan` would mean the
   very first wrap-up on any repo silently bought a fan-out of headless agent
   calls — the one run where nobody has agreed to anything yet. If the user wants
   the driver's fan-out for that first pass, they can have it: tell them
   `freya security scan --project . --yes` is the faster, paid alternative, name
   what it costs, and run it only if they say yes.
3. Run `git diff <last-commit>..HEAD --name-only` to get changed files
4. If no changes: report "no security-relevant changes detected" and exit

**Phase 2: Impact Analysis (Code-Graph Enhanced)**
1. **When the dependency-graph skill (`freya-code-graph` — registered as `freya-devkit:freya-code-graph` under a Claude plugin install) is available:**
   - Call `freya-code-graph impact <changed-files>` to get blast radius
   - Include dependent files in security scan
   - Provides deeper coverage than just changed files
2. **If code-graph is not available (fallback):**
   - Use only directly changed files from git diff
   - Warn user: "code-graph not available - scanning only directly changed files"

**Phase 3: Targeted Security Scanning**
1. Run the category scans ONLY over affected files
2. Each agent focuses on its category within the affected scope
3. Validate findings against online sources (per Step 3.4)

**Phase 4: Blast Radius Analysis**
For each finding:
1. Call `freya-code-graph dependents <vulnerable-file>` (if available)
2. Calculate impact: direct + transitive dependents
3. Assign priority based on blast radius:
   - 1-3 files affected: Low priority
   - 4-10 files affected: Medium priority
   - 10+ files affected: High priority

**Phase 5: Re-evaluate Previous Findings**
1. Find the most recent report in `/knowledge-base/security/codebase-security/`
2. Extract all findings with their locations and statuses
3. For each previous finding:
   - Check if the vulnerable code still exists at the reported location
   - If code changed: re-validate and update status
   - If code removed: mark as **RESOLVED**
   - If still present with same issue: mark as **PERSISTENT**
4. Include re-evaluation results in the new report

**Phase 6: Generate Incremental Report**
1. Create report at `/knowledge-base/security/codebase-security/YYYY-MM-DD.md`
2. **Overwrite existing report** - always use the same filename (no -2, -3 suffixes)
3. Include all findings:
   - Unresolved findings (CONFIRMED, PERSISTENT, REGRESSED, etc.)
   - Resolved findings in "Resolved Findings" section (shows what was fixed)
4. Include:
   - Changed files analyzed
   - Blast radius summary
   - New findings with impact analysis
   - Previous findings re-evaluation results

**Phase 7: Update Tracking**
Write to `knowledge-base/security/.security-last-scan`:
```yaml
# Security Scan Last Update
commit: <current-hash>
timestamp: <ISO-8601>
files_scanned: <count>
findings: <count>
scan_type: incremental
```

### `freya-codebase-security-scan impact <file>`

Show security implications and blast radius for a specific file.

**Use when:**
- Considering changes to a security-sensitive file
- Investigating a potential vulnerability
- Understanding the security impact of a component

**Workflow:**
1. Analyze the file for security-relevant patterns (auth, crypto, data handling)
2. **When the dependency-graph skill (`freya-code-graph`) is available:** Get all dependents (direct + transitive)
3. Identify security implications of the dependency chain
4. Generate impact report with recommendations

**Output:**
```
Security Impact Analysis: src/lib/auth/validateToken.ts

Category: Authentication
Risk Level: HIGH (authentication component)

Direct Dependents (3 files):
  - src/api/middleware/auth.ts [auth middleware]
  - src/api/routes/users.ts [user routes]
  - src/lib/auth/index.ts [auth exports]

Transitive Dependents (5 files):
  - src/api/routes/admin.ts [admin routes - elevated privileges]
  - src/api/routes/dashboard.ts [dashboard routes]
  - src/pages/api/user.ts [user API]
  - src/pages/api/settings.ts [settings API]
  - src/lib/auth/session.ts [session management]

Security Implications:
  - 8 files depend on this authentication logic
  - Vulnerabilities here could affect all protected routes
  - Changes require thorough testing of dependent files

Recommendations:
  - High priority for security review
  - Any changes should trigger full auth flow testing
  - Consider adding additional security tests for dependent files
```

### `freya-codebase-security-scan check-specs [report]`

Cross-reference security findings against project specifications to identify intentional design decisions.

**Use when:**
- Reviewing an existing security report for false positives
- Validating that specs cover all security-relevant behaviors
- Understanding which findings are intentional vs actual vulnerabilities
- After creating/updating specs to re-evaluate existing findings

**Arguments:**
- `report` (optional): Path to existing security report. If omitted, uses the most recent report in `/knowledge-base/security/codebase-security/`

**Workflow:**

**Phase 1: Load Findings**
1. Read the specified security report (or find most recent)
2. Extract all findings with their categories and locations
3. Note any findings already marked as INTENTIONAL DESIGN

**Phase 2: Load Specs**
1. Read all specs from `/knowledge-base/specs/features/`
2. Index specs by:
   - Affected endpoints/routes
   - Security-relevant keywords (auth, access, role, permission, delete, admin)
   - `security_implications` markers
   - Decision rationale

**Phase 3: Cross-Reference Each Finding**
For each finding, check two evidence sources — declarative specs and accepted behaviors:

*Declarative specs (existing):*
1. Identify the feature/component involved
2. Search specs for matching feature/component
3. Check if a spec explicitly allows the "vulnerable" behavior
4. If a spec match is found:
   - Update status to **INTENTIONAL DESIGN**
   - Add the spec reference (`spec_ref`) and include the rationale from the spec

*Accepted behaviors (the stronger evidence — read what it is evidence of):*
5. Run the behavior graph to find the `accepted` behaviors that exercise the
   finding's file, **and re-run their tests while you are there**:
   ```bash
   freya behavior-graph \
     --covering <finding-file> --project . --verify
   ```
   `--verify` is not the default for that query — other callers use it in a loop and it
   spawns a test run — but this is the one caller whose answer can stop a security finding
   from counting, and a scan is already expensive. Use it.
6. For each returned behavior, read its intent (its spec's Behavior entry /
   rationale) and judge: **does this behavior's intent explain this finding?**
   (the same relevance judgment as for specs). Where the row carries `symbols`, those are
   the named functions that actually ran — judge against those and not merely against the
   file, because a test touching a 500-line module says nothing about the line flagged in it.
7. If an accepted behavior explains the finding:
   - Update status to **INTENTIONAL DESIGN** and record `behavior_ref: BEH-NNN`
   - Note `intentional per BEH-NNN (SPEC-MMM)`, then copy the query's own
     `evidence` string into the note **verbatim**. The evidence string states whether a
     test was re-run or a committed record was trusted; never substitute your own summary
     of it, and never write *"verified by passing test"* unless `verified.passed` is true
     for that row.
   - A row whose `verified.passed` is **false** is evidence *against* the behavior. It does
     not downgrade anything, and it is worth a note of its own: a repository asserting an
     accepted behavior whose test does not pass is a finding in its own right.
8. **Only `accepted` behaviors downgrade a finding**, and only on what `--covering`
   checked: `state` and `spec_id` re-read from the specs, a locator that resolves to a file
   in the project — **required, not optional** — and an exercised path whose `source` is
   `observed`. A statically inferred edge is the import graph's guess that no test ever
   backed, and it licenses nothing. `proposed`/`confirmed`: note *"intended, test owed"*,
   and stay open.

**Phase 4: Update Original Report In Place**
Enhance the existing security report directly (no new file created):

1. **Add Spec Validation Section** to the existing report:
   ```markdown
   ---

   ## Spec Validation

   **Validated:** {timestamp}
   **Specs Analyzed:** {count}
   **Spec Manager:** freya-spec-manager skill

   ### Summary

   | Category | Count |
   |----------|-------|
   | Confirmed Vulnerabilities | {n} |
   | Intentional Design | {n} |
   | Needs Review | {n} |
   | Unmatched (no spec found) | {n} |

   ### Intentional Design Findings

   {For each finding that matches a spec:}

   #### {Finding Title}

   | Field | Value |
   |-------|-------|
   | **Original Status** | {previous status} |
   | **New Status** | Intentional Design |
   | **Spec Reference** | `{spec-path}` |
   | **Spec Decision** | {quote from spec} |

   **Rationale:**
   {Why this is intentional design per the spec}

   ### Unmatched Findings (No Spec Coverage)

   | Finding | Category | Recommendation |
   |---------|----------|----------------|
   | {title} | {category} | Consider creating a spec or confirming as vulnerability |

   ### Spec Coverage Analysis

   **Well-Documented Security Decisions:**
   {Specs that clearly cover security-relevant behaviors}

   **Missing Spec Coverage:**
   {Areas where security scan found issues but no spec exists}

   **Recommendation:** Create specs for these areas to document intentional design decisions.
   ```

2. **Update Finding Statuses** in the main findings section:
   - Change status from CONFIRMED/MITIGATED to INTENTIONAL DESIGN where applicable
   - Add spec references to relevant findings
   - Include validation notes

3. **Add Validation Metadata** at the top of the report:
   ```markdown
   **Validated Against Specs:** {timestamp}
   **Spec Coverage:** {n} specs analyzed
   ```

**Output:**
```
Spec Validation Complete

Report: knowledge-base/security/codebase-security/2024-01-15.md
Specs analyzed: 12
Findings reviewed: 8

Results:
  ✅ 3 findings confirmed as INTENTIONAL DESIGN
  ⚠️  5 findings remain as potential vulnerabilities
  📝 2 areas need spec coverage

The original report has been updated in place with:
  - New "Spec Validation" section added
  - 3 finding statuses updated to INTENTIONAL DESIGN
  - Spec references added to relevant findings
```

**Example Usage:**
```
# Validate most recent report
freya-codebase-security-scan check-specs

# Validate specific report
freya-codebase-security-scan check-specs knowledge-base/security/codebase-security/2024-01-15.md
```

### `freya-codebase-security-scan audit` (Deep Audit)

Exhaustive discovery plus a stronger adversarial verification pass, run by the `freya security audit` driver. On-demand / periodic — run before a release or on a slow cadence. **Not** run by `freya-wrap-up` (which uses `update`).

**How it differs from `scan`:** one setting. `scan` runs a single round of discovery;
`audit` **loops until dry** (repeat until K=2 consecutive empty rounds, max 5 rounds)
for exhaustive coverage. Everything else is shared — the same six categories, the same
dedup, and the same **3 diverse-lens skeptics** (exploitability, compensating-controls,
spec-intentional) per finding. `audit` is heavier and slower; it is not more careful.

**Engine:** `freya security audit` — the same Python driver `scan` uses, bundled with
this skill. It owns the control flow (loop-until-dry, dedup, majority voting) and calls
whichever agent CLI is installed (`claude` or `copilot`) as a headless, read-only worker.

**Critical division of labor — the driver returns DATA, the skill writes the REPORT:**
The driver does NOT write the report, assign `SEC-###` IDs, or re-evaluate previous
findings. Its workers run with an explicit read-only tool allowlist and return a JSON
array of deduped, adversarially-verified findings. The skill's **main loop** then does
everything that keeps the report format stable.

**Workflow:**

**Phase 1: Run the audit driver**

Show the user the plan and the ceiling first — this run is the expensive one:

```bash
freya security audit --project . --dry-run
```

Then, once they have agreed to that spend:

```bash
freya security audit --project . --yes
```

Both steps are required. The driver's own confirmation prompt cannot reach a user
through an agent shell — with no tty it declines and exits `4` — so the gate has to
be a turn in this conversation instead. Never pass `--yes` without having shown the
dry-run plan and been told to go ahead.

It prints the worst-case call count and a cost warning, and without `--yes` asks for
confirmation on **stderr** (stdout carries only the JSON payload). It executes: context →
exhaustive discovery (loop-until-dry over the 6 categories) → dedup by
`file + line-window + category` → per-finding adversarial verification → unanimous-refute
drop, and prints a JSON array of survivors on stdout. Each carries `disposition`
(`confirmed` / `mitigated` / `intentional-design` / `needs-review`), optional
`specReference`, `verification` (`{upheld, total, lenses}` — `lenses` names the lenses
that actually answered, not the ones that were asked), and `colocated`. No IDs, no
file writes.

**Cost.** One worker measured ~$0.40 on a trivial fixture, and a full audit is dozens of
calls. `--max-calls` (default 200 attempts) is the single cost knob; `--max-findings` is
derived from it so the two cannot disagree, and `--model` points workers at a cheaper
model. Attempts, not tasks, are what the ceiling counts — each task may retry once.

**Read the exit code before you read the findings** — the table in Step 3 applies
unchanged, with one substitution: on exit `1` (no agent CLI on PATH) use `update`, or
`scan`'s in-loop fallback. Nothing in the core workflow depends on `audit`. Exit `4`
here means the user declined the spend, or `--yes` was missing: report that, and do
not quietly run the audit's work some other way — declining an audit is a decision,
not an obstacle.

**Phase 2: Re-evaluate previous findings (MAIN LOOP — reuse Step 5 unchanged)**
Run the existing "Re-evaluate Previous Findings" logic (Step 5) against the most recent report (RESOLVED / PERSISTENT / REGRESSED). This stays in the skill, not the workflow.

**Phase 3: Assign IDs and format (MAIN LOOP)**
1. **Resolve `colocated` first, before IDs are assigned.** A non-empty `colocated` list
   names the other categories that reported a finding in the same file and five-line
   window. Usually that is one vulnerability seen through two category lenses — live on
   the phase 7 fixture, the `auth` finder and the `injection` finder both reported the
   same SQL injection at `src/auth.js:5`. Read the two titles and descriptions and
   decide:
   - **Same issue** → merge into one `SEC-###` entry, and list both categories in the
     Category field (`Injection + Auth`). Union their remediation advice.
   - **Genuinely different issues** (e.g. a hardcoded key on one line and an injection
     on the next) → keep both, and say in each Description that they share a location.

   The driver deliberately does not decide this for you. Dropping category from its
   dedup key would collapse the second case silently, and between a visible duplicate
   and a silent deletion a security tool takes the duplicate.
2. Assign `SEC-###` IDs in the existing format (continue numbering from the prior report).
3. Map each finding's `disposition` to an existing Status: `confirmed`→CONFIRMED, `mitigated`→MITIGATED, `intentional-design`→INTENTIONAL DESIGN, `needs-review`→NEEDS REVIEW.
4. Render the additive **Verification** row from `verification` (`Upheld {upheld}/{total} · {lenses}`). Quote `lenses` as given — a finding whose skeptic call failed reports fewer lenses, and that is the point.
5. Write `/knowledge-base/security/codebase-security/YYYY-MM-DD.md` using the SAME report template (overwrite, no suffixes).

**Phase 4: Update tracking (MAIN LOOP)**
Write `knowledge-base/security/.security-last-scan` with the current commit hash and `scan_type: audit` (same shape as `update`).

**When to use:**
- Before a release or major milestone
- Periodically (e.g. monthly), not on every change
- When you suspect `update`/`scan` missed attack surface

**Do NOT** wire `audit` into `freya-wrap-up` — it is a long, paid, multi-agent run and wrap-up's commit pipeline must stay fast and free.

### Step 3.4: Validation Phase (Critical for Accuracy)

**This phase eliminates false positives by verifying each finding against current documentation and security sources.**

For each potential finding, search the web to validate:

#### What to Verify
1. **Is this still a vulnerability?**
   - Search: `"{pattern/issue}" security vulnerability {framework/library} 2024 2025`
   - Check if newer versions have fixed this
   - Verify the issue applies to the project's version

2. **Is the remediation still current?**
   - Search: `"{framework/library}" {issue} fix solution latest`
   - Check official documentation for current best practices
   - Look for migration guides if APIs have changed

3. **Are there framework-specific considerations?**
   - Search: `"{framework}" {issue} configuration security`
   - Example: "Next.js middleware security 2025" might reveal that `middleware` was renamed to `proxy`
   - Check for environment-specific behavior differences

4. **Is this intentional design? (Spec Cross-Reference)**
   - Check `/knowledge-base/specs/` for related specifications
   - Search for specs mentioning the affected feature/endpoint/component
   - Look for `security_implications` or intentional design notes
   - If spec explicitly allows this behavior → mark as **INTENTIONAL DESIGN**

#### Validation Examples

**Example 1: Missing Middleware Check**
```
Initial Finding: "No middleware.ts found - missing request validation"
Validation Search: "Next.js middleware vs proxy 2025" or "Next.js middleware renamed"
Result: Next.js changed middleware to proxy configuration
Action: Mark as FALSE POSITIVE, do not include in report
```

**Example 2: Regex Pattern Match**
```
Initial Finding: "innerHTML usage detected - potential XSS"
Validation: Read surrounding code context
- If using a sanitization library (DOMPurify), mark as MITIGATED
- If user-controlled input without sanitization, mark as CONFIRMED
```

**Example 3: Outdated Security Practice**
```
Initial Finding: "CSP header not set"
Validation Search: "Next.js CSP configuration 2025"
Result: Project uses next.config.js headers with CSP
Action: Mark as FALSE POSITIVE after verifying config
```

**Example 4: Intentional Design (Spec Cross-Reference)**
```
Initial Finding: "Missing role check on DELETE /posts - any authenticated user can delete any post"
Validation: Check specs in /knowledge-base/specs/features/post-management.md
Spec Content:
  decision: "Any authenticated user can perform CRUD on posts"
  rationale: "Collaborative tool with equal access for all users"
  security_implications: "No role-based access control needed"
Action: Mark as INTENTIONAL DESIGN, reference spec in report
```

#### Finding Status Categories

After validation, each finding gets a status:

| Status | Description | Include in Report |
|--------|-------------|-------------------|
| **CONFIRMED** | Verified vulnerability, still applicable | Yes, with full details |
| **MITIGATED** | Vulnerability exists but has compensating controls | Yes, note the mitigation |
| **INTENTIONAL DESIGN** | Appears as vulnerability but is spec'd behavior | Yes, with spec reference |
| **FALSE POSITIVE** | Not actually a vulnerability or outdated info | No |
| **NEEDS REVIEW** | Cannot determine automatically, requires human review | Yes, marked for review |
| **PERSISTENT** | Found in previous scan, still unresolved | Yes, note duration and first detected |
| **RESOLVED** | Previously reported, now fixed or code removed | Yes, in "Resolved Findings" section |
| **REGRESSED** | Previously mitigated, but controls removed | Yes, flagged for immediate attention |

> Step 3.5 (Adversarial Verification) maps its verdicts onto these existing statuses; it never introduces a new status.

#### Validation Process

1. **Batch similar findings** - Group related issues to validate together
2. **Batch validation** - Validate findings as independent checks; run them in parallel where the agent supports it
3. **Document sources** - Note which documentation/source confirmed or denied the finding
4. **Be conservative** - If uncertain, include with "NEEDS REVIEW" status rather than discarding

### Step 3.5: Adversarial Verification (Standard)

**When this runs:** on `update`, and on the Step 3 **fallback** path (no agent CLI on
PATH). It does **not** run after a successful `freya security scan` or
`freya security audit` — the driver has already verified every finding it returned,
with three lenses, and re-running the pass here would pay twice for the same answer.
Findings that arrive with a `verification` object are done.

Keep this version synchronous and prose-driven so it composes inside
`freya-wrap-up`'s linear pipeline.

After Step 3.4 filters obvious false positives, subject every *surviving* candidate finding to a short refutation pass. The goal is to kill the false positives that slipped through validation **before** findings are aggregated and assigned IDs.

#### Mechanism

For each surviving finding, run **2-3 independent refutation passes**, each prompted to *disprove* the finding (not confirm it), one per lens:

1. **Exploitability / reachability** - "Construct a concrete path from an untrusted entry point to this code with attacker-controlled input. If you cannot reach it, the finding is refuted."
2. **Compensating controls** - "Find any existing validation, sanitization, auth gate, framework default, or upstream guard that already neutralizes this. If one exists, refute (or downgrade to MITIGATED)."
3. **Intentional / spec'd** - "Check `/knowledge-base/specs/` and surrounding code comments for evidence this behavior is deliberate. If spec'd, this is INTENTIONAL DESIGN, not a vulnerability." (Reuses the spec cross-reference as a refutation lens.)

Each pass returns **REFUTED** (with a reason) or **UPHELD**. The passes are independent
of each other and of every other finding's passes, and each returns a one-line verdict —
so run them in parallel where supported, one at a time otherwise. The existing cost
guardrail below still applies.

#### Disposition (reuse EXISTING statuses only — never introduce a new one)

| Refutation result | Disposition | Status assigned |
|-------------------|-------------|-----------------|
| Majority UPHELD (2/2, 2/3, 3/3) | Keep as a real finding | Existing Step 3.4 status (CONFIRMED / MITIGATED) |
| **Unanimous** REFUTED on exploitability/controls | Drop it | **FALSE POSITIVE** (excluded from report) |
| Majority REFUTED as spec'd | Reclassify | **INTENTIONAL DESIGN** (+ spec reference) |
| Split / inconclusive | Keep but flag for a human | **NEEDS REVIEW** |

Conservatism rule: only a **unanimous** refutation drops a finding. Any disagreement (split verdict) keeps it as **NEEDS REVIEW** — never silently delete an upheld or contested finding.

#### Recording the verdict (additive — does NOT change required fields)

Add one optional row to each finding's detail table to record the outcome. This is purely additive; the required fields (ID, Severity, Category, Status, Location, Recommendation) are unchanged, so `codebase-security-resolver` and `check-specs` keep parsing reports unchanged.

Format: `<Upheld|Refuted|Split> <n>/<total> · <lenses that drove the verdict>` — e.g. `Upheld 2/2 · exploitability+controls`. Findings dropped as FALSE POSITIVE are not written to the report (their verdict only appears in the scan log).

#### Cost guardrail

Cheap by design: a fixed 2-3 passes per finding, run across findings on the schedule chosen above. On `update` (incremental) the candidate set is small. On a large full `scan`, verify Critical/High exhaustively and sample Medium/Low rather than blocking the report.

### Step 4: Aggregate Findings

Collect and organize findings by:
1. Severity (Critical, High, Medium, Low)
2. Category
3. File location
4. Ease of remediation

**Driver findings carry a `colocated` list.** Resolve it here, before IDs are assigned,
exactly as described in `audit` Phase 3 step 1: two categories reporting the same
location are usually one vulnerability seen twice, but not always, so read both and
decide. The driver states the ambiguity rather than resolving it, because resolving it
in the dedup key would sometimes delete a real second finding silently.

### Step 5: Re-evaluate Previous Findings

**Critical for tracking vulnerability lifecycle.** Before generating the new report:

1. **Find Previous Reports**
   - Look in `/knowledge-base/security/codebase-security/` for the most recent report
   - If no previous report exists, skip this step

2. **Extract Previous Findings**
   - Parse all findings with their:
     - Location (file:line)
     - Status (Confirmed, Mitigated, Intentional Design, etc.)
     - Category and severity
     - Original description

3. **Re-evaluate Each Finding**
   For each previous finding:
   - Read the file at the reported location
   - Check if the vulnerable code still exists
   - Determine new status:

   | Situation | New Status | Action |
   |-----------|------------|--------|
   | Code unchanged, issue persists | **PERSISTENT** | Include with note about duration |
   | Code changed, issue fixed | **RESOLVED** | Include in "Resolved Findings" section |
   | Code changed, issue still present | **CONFIRMED** | Re-validate and update details |
   | Code removed/file deleted | **RESOLVED** | Include in "Resolved Findings" section (note: code removed) |
   | Previously Mitigated, controls removed | **REGRESSED** | Flag for immediate attention |

4. **Cross-reference with New Findings**
   - Match new findings against previous to identify duplicates
   - Update severity if changed
   - Merge findings for same issue in same location

### Step 6: Generate Security Report

Create the report at `/knowledge-base/security/codebase-security/YYYY-MM-DD.md`:

> **Write the report. Do not commit it.** Staging or committing anything — the
> report, `findings.json`, `.security-last-scan`, or any file you touched — is
> `freya-wrap-up`'s job, not this skill's. That separation is the two-commit
> pattern: code changes are one commit, generated artifacts are another, and the
> user decides when the second one happens. Observed in phase 6 validation: an
> agent running this skill with broad tool permissions inferred a `git commit`
> that nothing here asked for, and pushed a malformed message into the history of
> a repository it had only been asked to scan.

```markdown
# Codebase Security Report

**Generated:** {timestamp}
**Project:** {from docs or package.json}
**Scan Type:** Full Codebase Security Audit

---

## Executive Summary

{Brief summary of overall security posture, total findings by severity,
most critical issues requiring immediate attention}

## Severity Breakdown

| Severity | Count |
|----------|-------|
| Critical | {n}   |
| High     | {n}   |
| Medium   | {n}   |
| Low      | {n}   |
| **Total**| {n}   |

---

## Critical Findings

{For each critical/high finding:}

### {Finding Title}

| Field | Value |
|-------|-------|
| **Severity** | {Critical/High/Medium/Low} |
| **Category** | {Auth/Injection/Secrets/API/Config/File} |
| **Status** | {Confirmed/Mitigated/Intentional Design/Needs Review} |
| **Verification** | {Upheld 2/2 · exploitability+controls} (additive; from Step 3.5 — omit for older reports) |
| **Location** | `{file_path:line_number}` |
| **CWE** | {CWE-ID if applicable} |
| **Blast Radius** | {n} files affected |
| **Spec Reference** | {path/to/spec.md if INTENTIONAL DESIGN} |

**Description:**
{What the vulnerability is and why it's dangerous}

**Vulnerable Code:**
```{language}
{code snippet — a Secrets finding reaches you already fingerprinted as <redacted len={n} prefix='{first 4}' sha256={first 8 hex}>; leave it that way, never write a real secret value}
```

**Validation:**
{How this finding was verified - e.g., "Confirmed via OWASP documentation" or "Tested against version X.Y.Z"}

**Remediation:**
{Specific steps to fix the issue, verified against current documentation}

**Blast Radius Analysis (via code-graph):**

Direct dependents:
- file1.ts
- file2.ts

Transitive dependents:
- file3.ts (via file1.ts)
- file4.ts (via file2.ts)

**Remediation Priority:** {HIGH/MEDIUM/LOW} based on blast radius

**References:**
- {Links to OWASP, CWE, official docs, or other verified sources}

---

### Example: Intentional Design Finding

When a finding is determined to be intentional design per specs:

| Field | Value |
|-------|-------|
| **Severity** | N/A (Informational) |
| **Category** | Auth |
| **Status** | Intentional Design |
| **Location** | `src/api/routes/posts.ts:45` |
| **Spec Reference** | `knowledge-base/specs/features/post-management.md` |

**Description:**
Initially flagged as: "Missing role check on DELETE /posts/:id - any authenticated user can delete any post"

**Spec Validation:**
Cross-referenced with `knowledge-base/specs/features/post-management.md`:
```
decision: "Any authenticated user can perform CRUD on posts"
rationale: "This is a collaborative tool where all users have equal access"
security_implications: "No role-based access control needed for post operations"
```

**Conclusion:**
This is **intentional design**, not a vulnerability. The application is designed as a collaborative tool where all authenticated users have equal access to post management.

**Recommendation:**
No code changes needed. Consider documenting this design decision in API documentation if not already present.

---

{Repeat for each finding}

## Previous Findings Re-evaluation

{If a previous report exists, include this section:}

**Compared Against:** `{previous-report-filename}`
**Previous Scan Date:** {date}

### Status Changes Since Last Scan

| Finding | Previous Status | Current Status | Notes |
|---------|-----------------|----------------|-------|
| {finding title} | {status} | {status} | {resolution or change details} |

### Resolved Findings

{For findings that are now RESOLVED:}

#### {Finding Title}

| Field | Value |
|-------|-------|
| **Previous Severity** | {severity} |
| **Previous Status** | {status} |
| **Current Status** | ✅ RESOLVED |
| **Location** | `{file_path:line_number}` |
| **Resolution** | {How it was fixed - code change, mitigation applied, or code removed} |

**Original Issue:**
{Brief description of the original finding}

**Resolution Details:**
{What changed to resolve this issue}

---

### Persistent Findings

{For findings that remain unresolved across multiple scans:}

#### {Finding Title}

| Field | Value |
|-------|-------|
| **Severity** | {severity} |
| **Status** | ⚠️ PERSISTENT |
| **Location** | `{file_path:line_number}` |
| **First Detected** | {date of first report} |
| **Scans Present** | {n} scans |
| **Days Open** | {n} days |

**Description:**
{What the vulnerability is}

**Why Still Open:**
{If known - awaiting review, scheduled for sprint X, etc.}

**Recommendation:**
{Priority should be elevated due to duration}

---

### Regressed Findings

{For findings that were previously MITIGATED but controls have been removed:}

#### {Finding Title}

| Field | Value |
|-------|-------|
| **Severity** | {severity} |
| **Status** | 🔴 REGRESSED |
| **Location** | `{file_path:line_number}` |
| **Previous Mitigation** | {what was in place} |
| **Regression Detected** | {date} |

**Description:**
{What the vulnerability is}

**What Changed:**
{What mitigation was removed or changed}

**Immediate Action Required:**
{Steps to restore mitigation or fix the underlying issue}

---

{If no previous report exists:}

**No previous report found.** This is the first security scan. Future scans will compare findings against this baseline.

---

## Security Posture Assessment

### Strengths
{What the codebase does well security-wise}

### Weaknesses
{Areas that need improvement}

### Recommendations

1. **Immediate Actions** (Critical/High issues)
   - {action}
   - {action}

2. **Short-term Improvements** (Medium issues)
   - {action}
   - {action}

3. **Long-term Enhancements** (Low issues + best practices)
   - {action}
   - {action}

---

## Scan Coverage

| Category | Files Scanned | Findings |
|----------|---------------|----------|
| Authentication & Authorization | {n} | {n} |
| Input Validation & Injection | {n} | {n} |
| Secrets & Sensitive Data | {n} | {n} |
| API & Network Security | {n} | {n} |
| Configuration & Dependencies | {n} | {n} |
| File & Resource Handling | {n} | {n} |

---

## Next Steps

1. Address all Critical and High severity findings immediately
2. Create tickets/issues for Medium and Low findings
3. Implement automated security testing in CI/CD
4. Schedule regular security audits (run `freya-codebase-security-scan` weekly via your agent's scheduler or cron)
5. Consider penetration testing for production systems

---

*Report generated by codebase-security-scan skill*
```

#### Also emit `findings.json` (structured index)

Whenever you write or update the prose report, also write a machine-readable
index at `knowledge-base/security/codebase-security/findings.json` following
`references/findings-schema.md`. The document is an object, not a bare array:
`version`, `scanned_commit` (git HEAD at scan time), `report` (the path of the
prose report it mirrors) and `findings`. All four are required — a phase 7 live
run emitted `findings` alone, which leaves a consumer unable to tell which
commit the findings describe. It mirrors the report's findings exactly —
one entry per finding with `id`, `title`, `severity` (lowercase), `status`
(`open`/`resolved`/`intentional`), `file`, optional `line`, `spec_ref`
when a declarative spec marks the finding intentional, and `behavior_ref` when an
`accepted` behavior explains it (the stronger evidence, not a verified one). This lets `freya-status`
and the backlog surface open findings without parsing prose. Overwrite it on
each report write (no dated suffixes — it always reflects the latest report).

## Important Notes

### For Each Agent
- Search the codebase with appropriate patterns to find potential vulnerabilities
- Open the suspicious code and examine it in context
- Focus on actual vulnerabilities, not false positives
- Provide specific file paths and line numbers
- Include code snippets showing the issue, with any secret literal in them redacted first

### Severity Guidelines

- **Critical**: Actively exploitable, leads to data breach or system compromise
- **High**: Easily exploitable, significant security impact
- **Medium**: Requires specific conditions to exploit, moderate impact
- **Low**: Best practice violations, difficult to exploit, low impact

### Pattern Examples

When scanning, agents should look for patterns like:

```
# Secrets
api_key\s*=\s*['\"][^'\"]+['\"]
password\s*=\s*['\"][^'\"]+['\"]
secret\s*=\s*['\"][^'\"]+['\"]
-----BEGIN (RSA |DSA |EC |OPENSSH )?PRIVATE KEY-----

# SQL Injection
execute\([^)]*\+
query\([^)]*\+
\.query\(.*\$\{

# XSS
innerHTML\s*=
dangerouslySetInnerHTML
document\.write\(

# Command Injection
exec\([^)]*\+
spawn\([^)]*\+
eval\(

# Path Traversal
\.\./
path\.join\([^)]*req\.
readFile\([^)]*req\.
```

### Redaction

The four Secrets patterns above match live credentials, and the report is a file
`freya-wrap-up` commits. So: **never write a real secret value into the report, into
`findings.json`, or into anything else you leave behind.** A key that lived only in a
gitignored `.env` must not come out of it as a tracked blob — the operator can rotate
the key, but deleting the report tomorrow does not delete the blob.

A fingerprint goes where the value would have gone: how long it was, the first few
characters, and a truncated SHA-256 of the whole of it. That is enough to act on the
finding, to tell a live credential from a test fixture, and to recognize the same value
again on the next scan — the digest is what makes last month's report diffable against
this one. The `file:line` in the **Location** field is how a reader goes and looks;
nobody needs the secret quoted back at them.

The driver has already done this for you. Every `secrets`-category finding comes back
from `freya security` with its `codeSnippet` replaced, and with that same literal
scrubbed out of the finding's prose fields, in this shape:

```
<redacted len=44 prefix='sk-p' sha256=8991bfb4>
```

An empty `prefix=''` is not a bug: a value short enough that four characters would be
most of it gets none, because `len=7 prefix='hunte'` is a hint rather than a redaction.
Match that shape when you write a snippet by hand, and never edit a fingerprint back
into a value — the driver redacts what the finder handed it, so a credential you
paraphrase yourself is one nothing downstream will catch.

The rule covers passwords, tokens, private keys, connection strings carrying either, and
every other Category 3 hit — in the report, in `findings.json`, and in whatever you say
on the way past.

## Output Format

After generating the report:

1. **If critical/high findings found:**
   - Display summary with severity counts
   - List top 3 most critical issues
   - Provide path to full report
   - Recommend immediate action

2. **If no critical issues found:**
   - Report overall healthy security posture
   - Note any medium/low findings for improvement
   - Suggest scheduling regular scans

## Scheduling

Run the `freya-codebase-security-scan` skill on a recurring schedule using whatever
your agent provides — a built-in loop/scheduler command, a CI job, or a system cron
entry.

- **Weekly, full `scan`** — a complete security assessment.
- **Daily, `update` mode** — incremental analysis of what changed.

`audit` mode is deliberately absent here: it is on-demand and expensive. Run it
before a release, not on a timer.

## Code-Graph Integration

When the dependency-graph skill (`freya-code-graph`) is available, security scanning is enhanced:

### Incremental Mode Benefits
- **Faster scans**: Only analyze files affected by changes
- **Deeper coverage**: Include dependent files, not just changed files
- **Smart prioritization**: Focus on high-impact areas

### Blast Radius Analysis
For each vulnerability found:
1. Get direct dependents via `freya-code-graph dependents`
2. Calculate transitive impact
3. Include in report for prioritization

### Fallback Behavior
If the dependency-graph skill (`freya-code-graph`) is not available:
- `update` falls back to simple git diff (only changed files)
- `impact` returns "code-graph not available" error
- `scan` works normally (doesn't need code-graph)

### Used By
This skill uses `freya-code-graph` for:
- Impact analysis in `update` mode
- Blast radius calculations in findings
- `impact` command implementation

## Spec-Manager Integration

When specifications exist in `/knowledge-base/specs/`, security scanning is enhanced:

### False Positive Reduction
Cross-reference findings against intentional design decisions:
- Access control patterns that appear "missing" but are spec'd behavior
- Data exposure that's intentionally allowed
- API behaviors that look insecure but are by design

### Finding Status: INTENTIONAL DESIGN
When a finding matches a spec:
- Mark as **INTENTIONAL DESIGN** (not a vulnerability)
- Include spec reference in the report
- Note the rationale from the spec
- Still include in report for transparency

### Spec Search Priority
When validating findings, search specs for:
1. Features/endpoints mentioned in the finding
2. Security-relevant keywords (auth, access, role, permission, delete, admin)
3. `security_implications` or `intentional` markers
4. Decision rationale that explains the behavior

### Example Spec Match
```yaml
# /knowledge-base/specs/features/post-management.md
decision: "Any authenticated user can CRUD posts"
rationale: "Collaborative tool with equal access"
security_implications: "No RBAC needed for posts"
```

If finding: "Missing role check on post deletion"
→ Mark as **INTENTIONAL DESIGN**
→ Reference: `knowledge-base/specs/features/post-management.md`

## Report File Management

### Naming Convention
- All reports use `YYYY-MM-DD.md` format
- **Overwrites existing report** - always same filename, no -2, -3 suffixes
- Location: `/knowledge-base/security/codebase-security/`
- Git provides history if you need to see previous versions

### Command Behavior

| Command | File Behavior |
|---------|---------------|
| `scan` | Creates/overwrites `YYYY-MM-DD.md` |
| `update` | Overwrites existing `YYYY-MM-DD.md` (same file, updated content) |
| `check-specs` | Updates existing report in place (no new file) |

**All commands overwrite** - no -2, -3 suffixes. Use git to see previous versions if needed.

### Report Sections

Each report accumulates sections as commands are run:

1. **Initial scan:** Executive Summary, Findings, Recommendations
2. **After `check-specs`:** Adds Spec Validation section, updates finding statuses to INTENTIONAL DESIGN where applicable

### Why This Matters

- **Single source of truth:** One report per day containing all security information
- **Accumulated context:** `check-specs` enhances the existing report rather than fragmenting information
- **Easy tracking:** Clear chronological organization of security assessments

## Tracking File

The `.security-last-scan` file tracks incremental scan state:

**Location:** `knowledge-base/security/.security-last-scan`

```yaml
# Security Scan Last Update
commit: abc123def456
timestamp: 2024-01-15T10:30:00Z
files_scanned: 23
findings: 3
scan_type: incremental
```

**Usage:**
- Created automatically after first full `scan`
- Updated after each `update` scan
- Read by `update` to determine what changed since last scan
- Delete to force a full scan on next `update`

## Integration with Dependency Scan

This skill complements the `dependency-vulnerability-check` skill:
- Run both for comprehensive security coverage
- Dependency scan: Supply chain security
- Codebase scan: Application code security
