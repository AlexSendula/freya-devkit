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
4. **Run security scan** - `/freya-devkit:codebase-security-scan update` for incremental scan

**Commit 2 - Artifacts:**
- Docs, specs, security report, dependency graph, tracking files

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
1. Separate code files from artifact directories (docs/, specs/, etc.)
2. Stage code files only
3. Generate or use provided commit message
4. Create code commit
5. Capture the new commit hash

**If no code changes (already committed, e.g., from security-resolver):**
- Skip to Phase 1
- Note: Security tracking will still work correctly

### Phase 1: Update Dependency Graph

Run `/freya-devkit:code-graph update` to refresh the dependency graph with any code changes.

This ensures:
- docs-manager has accurate impact analysis
- spec-manager knows affected code areas
- security scan has correct blast radius data

### Phase 2: Update Documentation

Run `/freya-devkit:docs-manager update` to sync project documentation.

This updates files in `/docs/project/` based on code changes:
- Architecture docs
- API documentation
- Database schemas
- etc.

### Phase 3: Update Specifications

Run `/freya-devkit:spec-manager update` to sync feature specifications.

This updates files in `/docs/specs/` based on code changes:
- Feature specs
- Design decisions
- Certainty scores

### Phase 4: Security Scan

Run `/freya-devkit:codebase-security-scan update` for incremental security analysis.

This creates/updates the security report in `/docs/security-reports/codebase-security/`.

> Note: `update` now includes lightweight in-loop adversarial verification of each finding (synchronous, no background workflow), so it composes cleanly inside this linear pipeline. Do **not** substitute `/freya-devkit:codebase-security-scan audit` here — `audit` is a heavier, on-demand Workflow-powered mode that must not run inside wrap-up.

The `.security-last-scan` file will point to the code commit. The artifacts commit will be one ahead, but this is harmless since it contains no code to scan.

### Phase 5: Artifacts Commit

1. Stage all artifact changes:
   - Updated docs
   - Updated specs
   - Security report
   - Updated dependency graph
   - Tracking files
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
   - Documentation (docs/ changes only)
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

[1/4] Updating dependency graph...
  - 3 files changed since last build
  - Graph updated

[2/4] Updating documentation...
  - API.md updated
  - ARCHITECTURE.md updated

[3/4] Updating specifications...
  - SPEC-003 updated (auth flow)
  - Certainty: 85%

[4/4] Running security scan...
  - 0 new findings
  - Report: docs/security-reports/codebase-security/2024-03-26.md

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

[1/4] Updating dependency graph...
  - Graph updated based on latest commit

[2/4] Updating documentation...
  - API.md updated

[3/4] Updating specifications...
  - specs updated to reflect security fixes

[4/4] Running security scan...
  - Scanning changes since pre-fix commit
  - 0 new findings (fixes confirmed!)
  - Report: docs/security-reports/codebase-security/2024-03-26.md

Staging artifact changes...

Created commit: abc124def (artifacts)

Done! Artifacts committed separately from code changes.
```

## Requirements

This skill requires the following skills to be available:
- `/freya-devkit:code-graph` - Dependency graph
- `/freya-devkit:docs-manager` - Documentation management
- `/freya-devkit:spec-manager` - Specification management
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
