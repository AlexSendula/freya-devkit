---
name: codebase-security-scan
description: |
  Performs comprehensive security audit of entire codebase using parallel subagents.
  First reads project documentation from /knowledge-base/reference for context, then scans code
  for vulnerabilities across multiple security categories. Generates detailed reports
  in /knowledge-base/security/codebase-security/ with findings, severity ratings, and
  remediation recommendations.

  TRIGGER when: user asks to "scan codebase for security", "security audit", "code security check",
  "check for vulnerabilities in code", "security review", "audit my code", mentions "codebase security",
  "application security", or wants a comprehensive security assessment beyond just dependencies.

  INTEGRATION: Uses /freya-devkit:code-graph skill (when available) for:
  - Incremental scanning (only scan files affected by changes)
  - Blast radius analysis (trace vulnerability impact through dependencies)
  - Deep security analysis (understand how vulnerabilities propagate)

  Uses /freya-devkit:spec-manager skill (when available) for:
  - Cross-referencing findings against intentional design decisions
  - Identifying false positives that are actually spec'd behavior
  - Understanding security-relevant design choices
compatibility: Requires Agent, Read, Glob, Grep, Write, WebSearch tools. Optional: /freya-devkit:code-graph skill, /freya-devkit:spec-manager skill
---

# Codebase Security Scan

This skill performs a comprehensive security audit of your entire codebase using specialized parallel subagents.

## Overview

1. **Context Gathering**: Read project docs from `/knowledge-base/reference` to understand architecture, auth, data flows
2. **Spec Loading**: Read specs from `/knowledge-base/specs/` to understand intentional design decisions
3. **Parallel Scanning**: Spawn specialized agents for different security categories
4. **Validation Phase**: Verify findings against online sources AND specs to eliminate false positives
5. **Aggregation**: Combine validated findings into a comprehensive security report
6. **Re-evaluation**: Compare against previous reports to track finding lifecycle (RESOLVED, PERSISTENT, REGRESSED)
7. **Report Generation**: Save to `/knowledge-base/security/codebase-security/YYYY-MM-DD.md`

## Commands

| Command | Description |
|---------|-------------|
| `scan` | Full codebase security scan (all files) |
| `update` | Incremental scan - only files affected by recent changes |
| `audit` | Exhaustive discovery + adversarial verification (Workflow-powered). On-demand / pre-release. |
| `impact <file>` | Show security blast radius for a specific file |
| `check-specs [report]` | Cross-reference findings against specs to identify intentional design |
| `help` | Display help information |

**Recommendation:** Use `update` for day-to-day security checks after code changes. Use `scan` for initial security assessment or complete audits. Use `audit` periodically (e.g. before a release) for an exhaustive multi-agent deep audit — it is heavier and is **not** part of the `/freya-devkit:wrap-up` pipeline. Use `check-specs` to validate existing findings against project specifications.

All non-`audit` modes (`scan`, `update`) include lightweight standard adversarial verification of each finding (see Step 3.5); `audit` adds exhaustive loop-until-dry discovery plus a stronger multi-skeptic verification pass.

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

**Also cross-reference accepted behaviors (verified evidence).** Beyond declarative
specs, an `accepted`, test-backed behavior whose intent explains a finding is the
**strongest** "intentional" evidence — a verified guarantee, not a prose claim. When
validating findings (in `scan`/`update` as well as `check-specs`), apply the
behavior cross-reference exactly as in **`check-specs` Phase 3**: run
`behavior-graph --covering <finding-file>`, judge whether an accepted behavior
explains the finding, and on a match mark it intentional with `behavior_ref` +
"verified by passing test". Only `accepted` behaviors downgrade a finding;
`proposed`/`confirmed` add at most an advisory note and the finding stays open.

### Step 3: Spawn Parallel Security Agents

Launch the following specialized agents **in parallel** to scan different security categories:

#### Agent 1: Authentication & Authorization
Scan for:
- Hardcoded credentials, API keys, tokens
- Weak password policies
- Missing authentication checks
- Insecure session management
- Broken access control patterns
- JWT/oauth misconfigurations

#### Agent 2: Input Validation & Injection
Scan for:
- SQL injection vulnerabilities
- XSS (cross-site scripting) patterns
- Command injection risks
- Path traversal vulnerabilities
- SSRF (server-side request forgery)
- Unsafe deserialization
- Missing input sanitization

#### Agent 3: Secrets & Sensitive Data
Scan for:
- Exposed secrets in code (API keys, passwords, tokens)
- Sensitive data in logs
- PII exposure risks
- Insecure data storage
- Missing encryption for sensitive data
- Hardcoded encryption keys or IVs

#### Agent 4: API & Network Security
Scan for:
- Missing rate limiting
- CORS misconfigurations
- Missing HTTPS enforcement
- Insecure API endpoints
- Missing input validation on APIs
- Exposed internal APIs
- GraphQL security issues

#### Agent 5: Configuration & Dependencies
Scan for:
- Debug mode enabled in production
- Exposed admin endpoints
- Insecure default configurations
- Missing security headers
- Outdated or insecure middleware
- Environment variable exposure

#### Agent 6: File & Resource Handling
Scan for:
- Unsafe file upload handling
- Path traversal in file operations
- Missing file type validation
- Insecure temporary file handling
- Resource exhaustion vulnerabilities
- Unsafe file permissions

### `/freya-devkit:codebase-security-scan update` (Incremental Scan)

Git-aware incremental security scan using code-graph impact analysis.

**Workflow:**

**Phase 1: Change Detection**
1. Read `.security-last-scan` from `knowledge-base/security/` for last commit hash
2. If missing: fall back to full scan (`scan` command)
3. Run `git diff <last-commit>..HEAD --name-only` to get changed files
4. If no changes: report "no security-relevant changes detected" and exit

**Phase 2: Impact Analysis (Code-Graph Enhanced)**
1. **If `/freya-devkit:code-graph` skill is available:**
   - Call `/freya-devkit:code-graph impact <changed-files>` to get blast radius
   - Include dependent files in security scan
   - Provides deeper coverage than just changed files
2. **If code-graph is not available (fallback):**
   - Use only directly changed files from git diff
   - Warn user: "code-graph not available - scanning only directly changed files"

**Phase 3: Targeted Security Scanning**
1. Spawn security agents ONLY for affected files
2. Each agent focuses on its category within the affected scope
3. Validate findings against online sources (per Step 3)

**Phase 4: Blast Radius Analysis**
For each finding:
1. Call `/freya-devkit:code-graph dependents <vulnerable-file>` (if available)
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

### `/freya-devkit:codebase-security-scan impact <file>`

Show security implications and blast radius for a specific file.

**Use when:**
- Considering changes to a security-sensitive file
- Investigating a potential vulnerability
- Understanding the security impact of a component

**Workflow:**
1. Analyze the file for security-relevant patterns (auth, crypto, data handling)
2. **If `/freya-devkit:code-graph` available:** Get all dependents (direct + transitive)
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

### `/freya-devkit:codebase-security-scan check-specs [report]`

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
For each finding, check two evidence sources — declarative specs and verified behaviors:

*Declarative specs (existing):*
1. Identify the feature/component involved
2. Search specs for matching feature/component
3. Check if a spec explicitly allows the "vulnerable" behavior
4. If a spec match is found:
   - Update status to **INTENTIONAL DESIGN**
   - Add the spec reference (`spec_ref`) and include the rationale from the spec

*Accepted behaviors (verified guarantee — the stronger evidence):*
5. Run the behavior graph to find the `accepted` behaviors that exercise the
   finding's file:
   ```bash
   python "${CLAUDE_PLUGIN_ROOT}/skills/behavior-graph/scripts/behavior_graph.py" \
     --covering <finding-file> --project .
   ```
6. For each returned behavior, read its intent (its spec's Behavior entry /
   rationale) and judge: **does this behavior's verified intent explain this
   finding?** (the same relevance judgment as for specs)
7. If an accepted behavior explains the finding:
   - Update status to **INTENTIONAL DESIGN** and record `behavior_ref: BEH-NNN`
   - Note *"verified by passing test BEH-NNN (SPEC-MMM)"* — this is the **strongest**
     evidence and stands even when no declarative spec covers the finding (verified >
     a prose claim). A finding may carry both `spec_ref` and `behavior_ref`.
8. **Only `accepted` behaviors downgrade a finding.** `--covering` returns only
   accepted behaviors; if a `proposed`/`confirmed` behavior is known to be relevant,
   add only an advisory note ("intended per BEH-NNN, but test owed — not yet
   verified") and **leave the finding open**.

**Phase 4: Update Original Report In Place**
Enhance the existing security report directly (no new file created):

1. **Add Spec Validation Section** to the existing report:
   ```markdown
   ---

   ## Spec Validation

   **Validated:** {timestamp}
   **Specs Analyzed:** {count}
   **Spec Manager:** /freya-devkit:spec-manager skill

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
/freya-devkit:codebase-security-scan check-specs

# Validate specific report
/freya-devkit:codebase-security-scan check-specs knowledge-base/security/codebase-security/2024-01-15.md
```

### `/freya-devkit:codebase-security-scan audit` (Deep Audit)

Exhaustive discovery plus a stronger adversarial verification pass, powered by the **Workflow tool**. On-demand / periodic — run before a release or on a slow cadence. **Not** run by `/freya-devkit:wrap-up` (which uses `update`).

**How it differs from `scan`:**
- `scan` does one parallel pass of the 6 finders + standard verification (Step 3.5).
- `audit` runs the finders in a **loop-until-dry** (repeat until K=2 consecutive empty rounds, max 5 rounds) for exhaustive coverage, then runs **3 diverse-lens skeptics** (exploitability, compensating-controls, spec-intentional) per finding. It is heavier and slower.

**Engine:** `${CLAUDE_PLUGIN_ROOT}/workflows/codebase-security-audit.js` — a saved Workflow script bundled with this plugin. Invoke it via the Workflow tool's `scriptPath` (workflows are not auto-registered as a plugin component, so name-based resolution won't find it). Fallback if `${CLAUDE_PLUGIN_ROOT}` doesn't resolve inside `scriptPath`: copy that file into your project's `.claude/workflows/` and invoke it by name (`codebase-security-audit`).

**Critical division of labor — the Workflow returns DATA, the skill writes the REPORT:**
The workflow agents do NOT write the report, assign `SEC-###` IDs, or re-evaluate previous findings. They run as `Explore` agents (read-only — no Write) and return a JSON array of deduped, adversarially-verified findings. The skill's **main loop** then does everything that keeps the report format stable.

**Workflow:**

**Phase 1: Invoke the audit workflow**
1. Run the Workflow tool with `scriptPath: "${CLAUDE_PLUGIN_ROOT}/workflows/codebase-security-audit.js"`.
2. It executes: context → exhaustive discovery (loop-until-dry over the 6 categories) → dedup by `file + line-window + category` → per-finding adversarial verification → unanimous-refute drop.
3. It returns a JSON array of survivors, each with `disposition` (`confirmed` / `mitigated` / `intentional-design` / `needs-review`), optional `specReference`, and `verification` ({ upheld, total, lenses }). No IDs, no file writes.

**Phase 2: Re-evaluate previous findings (MAIN LOOP — reuse Step 5 unchanged)**
Run the existing "Re-evaluate Previous Findings" logic (Step 5) against the most recent report (RESOLVED / PERSISTENT / REGRESSED). This stays in the skill, not the workflow.

**Phase 3: Assign IDs and format (MAIN LOOP)**
1. Assign `SEC-###` IDs in the existing format (continue numbering from the prior report).
2. Map each finding's `disposition` to an existing Status: `confirmed`→CONFIRMED, `mitigated`→MITIGATED, `intentional-design`→INTENTIONAL DESIGN, `needs-review`→NEEDS REVIEW.
3. Render the additive **Verification** row from `verification` (`Upheld {upheld}/{total} · {lenses}`).
4. Write `/knowledge-base/security/codebase-security/YYYY-MM-DD.md` using the SAME report template (overwrite, no suffixes).

**Phase 4: Update tracking (MAIN LOOP)**
Write `knowledge-base/security/.security-last-scan` with the current commit hash and `scan_type: audit` (same shape as `update`).

**When to use:**
- Before a release or major milestone
- Periodically (e.g. monthly), not on every change
- When you suspect `update`/`scan` missed attack surface

**Do NOT** wire `audit` into `/freya-devkit:wrap-up` — it would inject a background multi-agent workflow into wrap-up's linear commit pipeline.

### Step 3: Validation Phase (Critical for Accuracy)

**This phase eliminates false positives by verifying each finding against current documentation and security sources.**

For each potential finding, use WebSearch to validate:

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
2. **Parallel validation** - Validate multiple findings simultaneously when possible
3. **Document sources** - Note which documentation/source confirmed or denied the finding
4. **Be conservative** - If uncertain, include with "NEEDS REVIEW" status rather than discarding

### Step 3.5: Adversarial Verification (Standard)

**Runs on every `scan` and `update`, in the main loop. This is NOT the Workflow tool** — keep it synchronous and prose-driven so it composes inside `/freya-devkit:wrap-up`'s linear pipeline (the heavier Workflow-powered version lives in `audit`).

After Step 3 filters obvious false positives, subject every *surviving* candidate finding to a short refutation pass. The goal is to kill the false positives that slipped through validation **before** findings are aggregated and assigned IDs.

#### Mechanism

For each surviving finding, run **2-3 independent refutation passes**, each prompted to *disprove* the finding (not confirm it), one per lens:

1. **Exploitability / reachability** - "Construct a concrete path from an untrusted entry point to this code with attacker-controlled input. If you cannot reach it, the finding is refuted."
2. **Compensating controls** - "Find any existing validation, sanitization, auth gate, framework default, or upstream guard that already neutralizes this. If one exists, refute (or downgrade to MITIGATED)."
3. **Intentional / spec'd** - "Check `/knowledge-base/specs/` and surrounding code comments for evidence this behavior is deliberate. If spec'd, this is INTENTIONAL DESIGN, not a vulnerability." (Reuses the spec cross-reference as a refutation lens.)

Each pass returns **REFUTED** (with a reason) or **UPHELD**. Run the passes in parallel across findings.

#### Disposition (reuse EXISTING statuses only — never introduce a new one)

| Refutation result | Disposition | Status assigned |
|-------------------|-------------|-----------------|
| Majority UPHELD (2/2, 2/3, 3/3) | Keep as a real finding | Existing Step 3 status (CONFIRMED / MITIGATED) |
| **Unanimous** REFUTED on exploitability/controls | Drop it | **FALSE POSITIVE** (excluded from report) |
| Majority REFUTED as spec'd | Reclassify | **INTENTIONAL DESIGN** (+ spec reference) |
| Split / inconclusive | Keep but flag for a human | **NEEDS REVIEW** |

Conservatism rule: only a **unanimous** refutation drops a finding. Any disagreement (split verdict) keeps it as **NEEDS REVIEW** — never silently delete an upheld or contested finding.

#### Recording the verdict (additive — does NOT change required fields)

Add one optional row to each finding's detail table to record the outcome. This is purely additive; the required fields (ID, Severity, Category, Status, Location, Recommendation) are unchanged, so `codebase-security-resolver` and `check-specs` keep parsing reports unchanged.

Format: `<Upheld|Refuted|Split> <n>/<total> · <lenses that drove the verdict>` — e.g. `Upheld 2/2 · exploitability+controls`. Findings dropped as FALSE POSITIVE are not written to the report (their verdict only appears in the scan log).

#### Cost guardrail

Cheap by design: a fixed 2-3 passes per finding, parallelized across findings. On `update` (incremental) the candidate set is small. On a large full `scan`, verify Critical/High exhaustively and sample Medium/Low rather than blocking the report.

### Step 4: Aggregate Findings

Wait for all agents to complete. Collect and organize findings by:
1. Severity (Critical, High, Medium, Low)
2. Category
3. File location
4. Ease of remediation

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
{code snippet}
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
4. Schedule regular security audits (use `/loop 1w /freya-devkit:codebase-security-scan`)
5. Consider penetration testing for production systems

---

*Report generated by codebase-security-scan skill*
```

#### Also emit `findings.json` (structured index)

Whenever you write or update the prose report, also write a machine-readable
index at `knowledge-base/security/codebase-security/findings.json` following
`references/findings-schema.md`. It mirrors the report's findings exactly —
one entry per finding with `id`, `title`, `severity`, `status`
(`open`/`resolved`/`intentional`), `file`, optional `line`, `spec_ref`
when a declarative spec marks the finding intentional, and `behavior_ref` when an
`accepted` behavior verifiably explains it (the stronger evidence). This lets `/freya-devkit:status`
and the backlog surface open findings without parsing prose. Overwrite it on
each report write (no dated suffixes — it always reflects the latest report).

## Important Notes

### For Each Agent
- Use Grep with appropriate patterns to find potential vulnerabilities
- Use Read to examine suspicious code in context
- Focus on actual vulnerabilities, not false positives
- Provide specific file paths and line numbers
- Include code snippets showing the issue

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

To run weekly security scans:
```
/loop 1w /freya-devkit:codebase-security-scan
```

For incremental updates after code changes:
```
/loop 1d /freya-devkit:codebase-security-scan update
```

## Code-Graph Integration

When the `/freya-devkit:code-graph` skill is available, security scanning is enhanced:

### Incremental Mode Benefits
- **Faster scans**: Only analyze files affected by changes
- **Deeper coverage**: Include dependent files, not just changed files
- **Smart prioritization**: Focus on high-impact areas

### Blast Radius Analysis
For each vulnerability found:
1. Get direct dependents via `/freya-devkit:code-graph dependents`
2. Calculate transitive impact
3. Include in report for prioritization

### Fallback Behavior
If `/freya-devkit:code-graph` is not available:
- `update` falls back to simple git diff (only changed files)
- `impact` returns "code-graph not available" error
- `scan` works normally (doesn't need code-graph)

### Used By
This skill uses `/freya-devkit:code-graph` for:
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
