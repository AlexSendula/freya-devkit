---
name: codebase-security-resolver
description: |
  Resolve security findings from the codebase security scan interactively.

  Use this skill when the user wants to:
  - View security findings from the latest scan
  - Select which vulnerabilities to fix
  - Get a plan for fixing security issues
  - Resolve security findings end-to-end

  TRIGGER when: user mentions "security findings", "fix vulnerabilities",
  "resolve security", "security issues", "vulnerability report", or asks
  to see/fix security problems.

  WORKFLOW: Lists findings → user selects -> validate findings → summarize with validation notes -> confirm -> enter plan mode →
  implement → commit code → run /freya-devkit:wrap-up
---

# Codebase Security Resolver

Resolve security findings with an interactive selection and planning workflow.

## Quick Reference

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

## How It works

### Security Report Location

Reads findings from:
```
/knowledge-base/security/codebase-security/
├── YYYY-MM-DD.md      # Dated reports — load the most recent
└── findings.json      # Machine-readable findings index
```

### Finding Format

Each finding in the report should have:
- ID (e.g., SEC-001)
- Severity (critical, high, medium, low, info)
- Title/Description
- Affected file(s)
- Status (CONFIRMED, POTENTIAL, FIXED)
- Recommendation
- Verification (optional, e.g. "Upheld 2/2" or "Needs review · split") — present in reports produced after adversarial verification was added; absent in older reports. Read it only if present.

### Severity Indicators

| Severity | Indicator | Priority |
|----------|-----------|----------|
| critical | 🔴 | Fix immediately |
| high | 🟠 | Fix soon |
| medium | 🟡 | Fix when possible |
| low | 🟢 | Consider fixing |
| info | ℹ️ | Informational |

### Branch Handling

Security fixes should be done in isolation:

1. **Detect current branch:**
   ```bash
   git branch --show-current
   ```

2. **Branch behavior:**
   - If on `main` → Create `security/fix-YYYY-MM-DD` branch
   - If on feature branch → Stay on current branch

3. **Branch naming:** `security/fix-2024-01-15` (today's date)

---

## Commands

### `/freya-devkit:codebase-security-resolver` (default)

Interactive workflow to resolve security findings.

**Phase 1: Load Report**
**Phase 2: Present Findings**
**Phase 3: Interactive Selection**
**Phase 4: Validate Findings**

Before confirming with the user, validate each selected finding.

**Validation checks:**
1. **Code exists** - Does the affected file/line still exist?
2. **Vulnerability applicable** - Is the vulnerability still present?
3. **Dependency exists** - Does referenced code/package still exist?

**Validation actions:**
```bash
# Check if file exists
test -f src/api/users.ts

# Check if function/code pattern exists
grep -n "searchUsers" src/api/users.ts

# Check if dependency exists
grep -n "tiptap" package.json
```

**Validation output:**
```
Validating 4 selected findings...

✅ SEC-001: SQL injection in user search
   File exists, vulnerable code pattern found

⚠️ SEC-H2: CSP allows unsafe-inline
   Finding references 'tiptap editor'...
   → No tiptap dependency found
   → This finding may be outdated
   → Recommend: Update spec instead of code fix

✅ SEC-H3: in-Memory Rate limiting
   File exists, in-memory rate limiting found

✅ SEC-H4: File Upload Missing Magic Number Validation
   File exists, upload handler found
```

**If findings are stale or outdated:**
- Mark with ⚠️ warning icon
- Suggest alternative action (e.g., "Update spec as intentional", "Remove finding from report")
- Ask user if they want to skip or adjust

**Impact Analysis (via /freya-devkit:code-graph):**

For each finding, check dependents to understand blast radius:

1. Find the function/component at the affected line
2. Query /freya-devkit:code-graph for dependents
3. Assess fix complexity based on impact

**Impact output:**
```
📊 Impact analysis for SEC-001: SQL injection in user search
   Location: src/api/users.ts:45 (searchUsers function)

   Direct dependents: 3 files
     → src/handlers/userHandler.ts (calls searchUsers)
     → src/services/userService.ts (wraps searchUsers)
     → tests/api/users.test.ts (tests searchUsers)

   Assessment: Active code with 3 dependents
   Fix approach: Parameterized queries (no signature change needed)
   Risk: Low - internal API, signature stays same
```

**Dead code detection:**
```
📊 Impact analysis for SEC-007: Path traversal in legacy upload
   Location: src/api/legacy-upload.ts:88 (handleUpload function)

   Direct dependents: 0 files

   Assessment: Dead code - no callers found
   Recommendation: DELETE the file instead of fixing
   → Reduces maintenance burden
   → Eliminates vulnerability entirely
```

**Phase 4.5: Metadata Cleanup Detection**

For findings that are skipped (outdated, already resolved, or intentional), determine what cleanup is needed:

**Cleanup categories:**

1. **ALREADY_RESOLVED** - Code fix already exists
   → Action: Update report status to RESOLVED

2. **INTENTIONAL_DESIGN** - Valid finding but intentional decision
   → Action: Check spec, add if missing + update report to INTENTIONAL

3. **OUTDATED_FINDING** - References removed code/dependencies
   → Action: Remove from report or mark as OBSOLETE

4. **MISCLASSIFIED** - Not a security issue (e.g., scalability concern)
   → Action: Move to appropriate doc or mark as INFO

**Cleanup detection output:**
```
📋 Metadata Cleanup Analysis

SEC-H2 (INTENTIONAL_DESIGN):
  Status: CSP allows unsafe-inline for Tiptap
  Spec check: No intentional design entry found
  Cleanup needed:
    → Add to spec: "CSP allows unsafe-inline for Tiptap editor (mitigated by DOMPurify)"
    → Update report: Mark as INTENTIONAL, link to spec

SEC-H3 (MISCLASSIFIED):
  Status: In-memory rate limiting - scalability, not security
  Spec check: Already documented in architecture decisions
  Cleanup needed:
    → Update report: Reclassify as INFO (not a security vulnerability)

SEC-H5 (ALREADY_RESOLVED):
  Status: Auth check already in code at lines 49-52
  Report status: Still marked as CONFIRMED
  Cleanup needed:
    → Update report: Mark as RESOLVED, note commit/line where fixed
```

**Phase 5: Summary of Selected Findings**

Show brief summary with validation notes, including both code fixes and metadata cleanup:

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                              SUMMARY                                         │
├─────────────────────────────────────────────────────────────────────────────┤
│ CODE FIXES (2)                                                              │
├─────────┬───────────────────────────────────────────────────────────────────┤
│ SEC-H1  │ Add rate limiting to upload/translate endpoints                   │
│ SEC-H4  │ Add magic number validation to file upload                        │
└─────────┴───────────────────────────────────────────────────────────────────┘

┌─────────────────────────────────────────────────────────────────────────────┐
│ METADATA CLEANUP (3)                                                        │
├─────────┬────────────────────┬──────────────────────────────────────────────┤
│ Finding │ Category           │ Action                                        │
├─────────┼────────────────────┼──────────────────────────────────────────────┤
│ SEC-H2  │ INTENTIONAL_DESIGN │ Add spec entry + mark report INTENTIONAL      │
│ SEC-H3  │ MISCLASSIFIED      │ Reclassify report as INFO (scalability note)  │
│ SEC-H5  │ ALREADY_RESOLVED   │ Mark report as RESOLVED (code already fixed)  │
└─────────┴────────────────────┴──────────────────────────────────────────────┘

Total actions: 2 code fixes + 3 metadata updates
```

**Detailed summary with fix direction:**

**Phase 6: Confirm to continue**

Use askUserQuestion with an open prompt:
```
Ready to proceed with 3 findings?

[Yes, continue]  [I have concerns about these findings]  [Cancel]
```

**If user selects "I have concerns":**
1. Ask user to describe their concerns
2. For each concern, investigate:
   - If user is correct → Adjust the fix list accordingly
   - If user may be wrong → Make a case for why the fix is still needed
3. Re-present the adjusted list for confirmation

**Concern handling examples:**

*User says: "We don't need Redis, this app won't have multiple instances"*

Evaluate the concern:
```
Analyzing concern about SEC-H3...

Looking at:
- Current deployment setup (check for docker-compose, k8s configs)
- Project scale and expected traffic
- Complexity trade-offs

Assessment: You're right. This is a single-instance app with moderate traffic.
In-memory rate limiting is sufficient. Adding Redis would add unnecessary
complexity.

Recommendation: Skip this finding, or document in spec as "intentional - single instance deployment

Would you like to:
[Skip this finding]  [Document as intentional]  [Still fix it anyway]
```

*User says: "Not sure if we still have the tiptap editor"*

Investigate first:
```
Checking for tiptap editor...

grep -r "tiptap" package.json → Not found
grep -r "@tiptap" src/ → Not found

Result: Tiptap editor has been removed from the codebase.

SEC-H2 is outdated. The CSP issue was tied to tiptap's requirements.
Since tiptap is gone, we can tighten CSP without breaking anything.

Updated recommendation for SEC-H2:
- Remove unsafe-inline and unsafe-eval from CSP
- This is now a valid code fix, not just a spec update
```

**Phase 7: Final Confirmation**

After addressing concerns, show final list:
```
Final fix list (3 findings):

✅ SEC-001: SQL injection in user search
✅ SEC-H2: CSP allows unsafe-inline (updated: tighten CSP, tiptap removed)
✅ SEC-H4: File Upload Missing Magic Number Validation

⚠️ Skipped (1):
  SEC-H3: in-Memory Rate Limiting → Not needed for single-instance deployment

Ready to proceed?
[Yes, continue]  [Cancel]
```

**Phase 8: Branch Check**

After confirmation, check and handle branches:
```bash
# Check current branch
current_branch=$(git branch --show-current)

if [ "$current_branch" = "main" ]; then
  # Create security fix branch
  today=$(date +%Y-%m-%d)
  git checkout -b "security/fix-$today"
  echo "Created branch: security/fix-$today"
else
  echo "Staying on branch: $current_branch"
fi
```

**Phase 9: Enter Plan Mode**

Use EnterPlanMode tool to create an implementation plan for the selected findings.

**Plan Context (includes impact data and metadata cleanup):**

When entering plan mode, include:
- List of selected findings with IDs for code fixes
- Affected files for each finding
- **Dependents for each affected file** (from code-graph)
- Brief fix direction for each
- Note about branch (new or existing)
- Risk assessment based on blast radius
- **Metadata cleanup actions** (for skipped findings)

Example plan header:
```
Implementation Plan: Security Fixes
====================================

PART 1: CODE FIXES
------------------

Finding: SEC-001 - SQL injection in user search
File: src/api/users.ts:45
Fix: Use parameterized queries

📊 Blast radius (from code-graph):
  Direct changes: 1 file
    - src/api/users.ts

  May need updates: 2 files
    - tests/api/users.test.ts (if query signature changes)

  Safe to proceed: Yes - no external API consumers

PART 2: METADATA CLEANUP
-------------------------

SEC-H2 (INTENTIONAL_DESIGN):
  → Add to spec: knowledge-base/specs/security.decisions.md
    "CSP allows unsafe-inline for Tiptap editor, mitigated by DOMPurify sanitization"
  → Update report: Mark as INTENTIONAL, add spec reference

SEC-H3 (MISCLASSIFIED):
  → Update report: Change severity from HIGH to INFO
    "Scalability consideration, not a security vulnerability"

SEC-H5 (ALREADY_RESOLVED):
  → Update report: Mark as RESOLVED
    "Fixed in commit abc123, auth check at lines 49-52"
```

**Phase 10: Implementation**

After plan approval:
1. Implement fixes for each finding
2. Verify fixes don't break existing functionality
3. Run any relevant tests

**After implementing each fix:**

1. Run quick code-graph check on changed files
2. Verify dependents still compile/work
3. Flag any breaking changes immediately

**Implementation output:**
```
Implementing SEC-001: SQL injection in user search...

✅ Changed src/api/users.ts
   - Replaced string concatenation with parameterized query

📊 Checking dependents...
   src/handlers/userHandler.ts
     → Still compatible ✓ (same function signature)

   src/services/userService.ts
     → Still compatible ✓ (same function signature)

   tests/api/users.test.ts
     → ⚠️ May need update
     → Test uses raw SQL assertion that may fail
     → Check test after running

⚠️ Note: tests/api/users.test.ts may need adjustment
   Run tests? [Yes] [Show me the test first] [Continue anyway]
```

**If breaking change detected:**
```
❌ Breaking change detected!

SEC-003 fix changed function signature of validateToken()
Affected dependents:
  - src/middleware/auth.ts (uses validateToken)
  - src/routes/protected.ts (uses validateToken)

Options:
[Update all dependents]  [Revert and try different approach]  [Show details]
```

**Phase 10.5: Final Impact Check**

After all fixes implemented, verify codebase integrity:

```
📊 Final Impact Check

Changed files: 3
  - src/api/users.ts
  - src/lib/auth/token.ts
  - src/api/upload.ts

Checking dependents of changed files...
  ✅ 12 dependents checked
  ✅ All dependents still resolve correctly
  ✅ No orphaned imports detected

Codebase integrity: VERIFIED

Proceeding to metadata cleanup...
```

**Phase 10.6: Metadata Cleanup Execution**

After code fixes, execute metadata cleanup for skipped findings:

**For INTENTIONAL_DESIGN:**
```
📝 SEC-H2: Documenting intentional design...

1. Checking spec for existing entry...
   → No entry found for CSP decision

2. Adding to spec (via /freya-devkit:spec-manager):
   → File: knowledge-base/specs/security.decisions.md
   → Entry: "CSP allows unsafe-inline for Tiptap editor"
   → Rationale: "Required for Tiptap, mitigated by DOMPurify"

3. Updating security report:
   → Status: CONFIRMED → INTENTIONAL
   → Added: Spec reference link

✅ SEC-H2: Documented as intentional
```

**For ALREADY_RESOLVED:**
```
📝 SEC-H5: Marking as resolved...

1. Verifying fix in code...
   → Found: `if (!isSuperAdmin) return 403` at lines 49-52
   → Confirmed: Auth check is in place

2. Updating security report:
   → Status: CONFIRMED → RESOLVED
   → Added: Resolution note with file/line reference

✅ SEC-H5: Marked as resolved
```

**For MISCLASSIFIED:**
```
📝 SEC-H3: Reclassifying finding...

1. Analyzing finding type...
   → Current: HIGH severity security issue
   → Actual: Scalability consideration, not a vulnerability

2. Updating security report:
   → Status: CONFIRMED → INFO
   → Severity: HIGH → INFO
   → Added: Note explaining this is architectural, not security

✅ SEC-H3: Reclassified as INFO
```

**Metadata cleanup summary:**
```
📋 Metadata Cleanup Complete

┌─────────┬────────────────────┬─────────────────────────────────┐
│ Finding │ Action             │ Result                          │
├─────────┼────────────────────┼─────────────────────────────────┤
│ SEC-H2  │ Add spec + update  │ ✅ Spec added, report updated   │
│ SEC-H3  │ Reclassify         │ ✅ Changed to INFO              │
│ SEC-H5  │ Mark resolved      │ ✅ Status → RESOLVED            │
└─────────┴────────────────────┴─────────────────────────────────┘

Proceeding to wrap-up...
```

**Phase 11: Commit Code Changes**

Before running wrap-up, commit the code fixes first. This ensures the security scan has a proper commit to reference.

```bash
git add <changed files>
git commit -m "fix(security): resolve SEC-001, SEC-003, SEC-007"
```

**Why commit first?**
- Security scan update needs a commit hash to diff against
- Wrap-up will handle the artifacts (docs, specs, scan) in a follow-up commit
- Clean separation: code fixes in one commit, generated artifacts in another

**Phase 12: Wrap-Up**

After committing code changes, call `/freya-devkit:wrap-up`. Wrap-up will:
1. Detect code is already committed (skip Phase 0)
2. Update dependency graph
3. Update documentation
4. Update specifications
5. Verify behavior integrity & run affected accepted behaviors (Phase 3.5)
6. Run fresh security scan (confirms fixes by comparing to pre-fix commit)
7. Commit all artifacts together (docs, specs, graph, security report)

Result: Two clean commits
```
commit A: fix(security): resolve SEC-001, SEC-003
commit B: docs: update docs, specs, and security report
```

---

### `/freya-devkit:codebase-security-resolver list [--severity]`

Show findings without entering selection/planning.

**Severity filters:**
```
/freya-devkit:codebase-security-resolver list              # All findings
/freya-devkit:codebase-security-resolver list --critical   # Only critical
/freya-devkit:codebase-security-resolver list --high       # Critical + high
/freya-devkit:codebase-security-resolver list --medium     # Critical + high + medium
```

**Output format:**
```
🔴 Critical Findings (3)

SEC-001: SQL injection in user search
   File: src/api/users.ts:45
   Status: CONFIRMED

SEC-003: Auth bypass in token validation
   File: src/lib/auth/token.ts:22
   Status: CONFIRMED

SEC-007: Path traversal in file upload
   File: src/api/upload.ts:88
   Status: CONFIRMED
```

**Finding display format:**
```
🔴 SEC-001: SQL injection in user search
   File: src/api/users.ts:45
   Status: CONFIRMED
```

---

### `/freya-devkit:codebase-security-resolver fix <ids...>`

Skip interactive selection, go directly to planning.

**Examples:**
```
/freya-devkit:codebase-security-resolver fix SEC-001
/freya-devkit:codebase-security-resolver fix SEC-001 SEC-003 SEC-007
```

**With severity shortcut:**
```
/freya-devkit:codebase-security-resolver fix --critical   # Fix all critical
/freya-devkit:codebase-security-resolver fix --high       # Fix all critical + high
```

**Workflow:**
1. Load findings from report
2. Validate findings (Phase 4)
3. Show summary with validation notes (Phase 5)
4. Confirm to continue (Phase 6)
5. Handle branch (Phase 8)
6. Enter plan mode
7. Implement
8. Commit code changes (Phase 11)
9. Run `/freya-devkit:wrap-up` for artifacts (Phase 12)

---

### `/freya-devkit:codebase-security-resolver fix --dry-run`

Preview what would be fixed without making any changes.

**Workflow:**
1. Load findings from report
2. Validate findings (Phase 4)
3. Show what would be done, no changes made
4. Show what branch action would happen

**Output:**
```
DRY RUN - No changes will be made

Validating 3 findings...

SEC-001: SQL injection in user search
  Problem: User input concatenated directly into SQL query
  Fix: Use parameterized queries

SEC-003: Auth bypass in token validation
  Problem: Token signature not verified
  Fix: Add proper signature verification

SEC-007: Path traversal in file upload
  Problem: filename not validated
  Fix: Sanitize file paths

⚠️ SEC-H2: CSP allows unsafe-inline
  → Tiptap editor not found in codebase
  → Checking if Tiptap is still used...

Result: Tiptap has been removed. Skipping this fix.

Alternative: Document as intentional in spec
  → S: This is already mitigated by DOMPurify sanitization

Branch action:
  Current: main
  Would create: security/fix-2024-01-15

To actually fix these, run:
  /freya-devkit:codebase-security-resolver fix --critical
```

---

## Integrations

### /freya-devkit:code-graph

This skill uses /freya-devkit:code-graph at multiple phases:

1. **Validation** - Detect dead code vs active code
2. **Planning** - Include blast radius in implementation plan
3. **Implementation** - Verify changes don't break dependents
4. **Post-implementation** - Final integrity check

Commands used:
- `/freya-devkit:code-graph dependents <file>` - Find files that import/use a file
- `/freya-devkit:code-graph impact <file>` - Get blast radius for changes

### /freya-devkit:spec-manager

This skill uses /freya-devkit:spec-manager for metadata cleanup:

1. **INTENTIONAL_DESIGN** - Add intentional design decisions to spec
2. **Validation** - Check if intentional design already documented

When a finding is marked as intentional but not in spec, the skill adds it automatically.

---

## Tips

1. **Prioritize by severity** - Critical findings should be addressed first, but consider blast radius too.

2. **Check impact first** - The skill uses code-graph to understand blast radius before fixing. If a finding affects many files, consider if it's worth the risk.

3. **Dead code can be deleted** - If code-graph shows no dependents, consider deletion instead of fixing. This eliminates the vulnerability entirely.

4. **Metadata cleanup matters** - Skipped findings still get attention. The skill updates the report and adds spec entries so future scans have context.

5. **Run tests after changes** - Even with code-graph verification, always run tests to catch runtime issues.

6. **Document intentional decisions** - If you choose not to fix a finding, document why in the spec using /freya-devkit:spec-manager.

7. **Use dry-run first** - For unfamiliar codebases, use `--dry-run` to preview changes before committing.

8. **One branch per session** - All fixes go into a single security branch for easy review and rollback.

9. **Trust but verify** - The validation phase catches false positives, but your domain knowledge is valuable too. Raise concerns during confirmation.

10. **Use the Verification field when present** - Findings marked `Upheld n/n` are high-confidence; prioritize them. Findings marked `Needs review · split` survived verification only weakly — confirm them manually during Phase 4 before fixing. If the field is absent (older report), fall back to normal validation.
