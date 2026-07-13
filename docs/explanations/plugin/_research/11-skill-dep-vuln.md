# Skill: dependency-vulnerability-check

**Research brief for the freya-devkit plugin-wide explainer.**
Primary source: `skills/dependency-vulnerability-check/SKILL.md` (single, self-contained file — no `scripts/`, `references/`, or `evals/` subdirectories exist for this skill).
Cross-reference source: `skills/codebase-security-scan/SKILL.md` (lines 1096–1102).

---

## What it is

`dependency-vulnerability-check` is a freya-devkit skill (invoked namespaced as
`/freya-devkit:dependency-vulnerability-check`) that audits a Node.js project's
third-party dependencies for known security vulnerabilities and writes a dated,
human-readable markdown report.

It is **prompt-driven, not script-driven**: the entire skill is a set of natural-language
workflow instructions in `SKILL.md`. There is no Python/JS runner — the agent itself
runs shell commands (`npm/yarn/pnpm audit`), does web lookups, applies validation
judgement, and writes the report file. This distinguishes it from more mechanical
freya-devkit skills (e.g. code-graph) that ship executable scripts.

Frontmatter declares:
```
name: dependency-vulnerability-check
compatibility: Requires Bash, Read, Write, Glob, Grep, WebSearch tools
```

## Why it exists

It covers the **supply-chain / dependency** half of security. Per the sibling skill's
"Integration with Dependency Scan" section (`codebase-security-scan/SKILL.md:1096–1101`):

> - Dependency scan: Supply chain security
> - Codebase scan: Application code security

So the two skills are deliberately complementary: this one looks at *what you pulled in*
(npm packages and their transitive deps), while `codebase-security-scan` looks at *the
code you wrote*. Running both is the intended "comprehensive security coverage."

Stated use cases (SKILL.md "When to use"):
- User requests a dependency security check
- Setting up periodic scanning (pairs with `/loop` for daily/weekly)
- After adding new dependencies
- Before deploying to production
- When user mentions CVEs, security vulnerabilities, or supply chain risks

## How it works — the pipeline (5 steps)

The workflow is explicitly numbered in SKILL.md:

**Step 1 — Detect project type and package manager.**
Look for a lock file in project root and map it to a package manager:
- `package-lock.json` → npm
- `yarn.lock` → yarn
- `pnpm-lock.yaml` → pnpm

Confirm it's a Node.js project via `package.json`. If no Node.js project is detected,
tell the user the skill requires one.

**Step 2 — Run the appropriate audit command** (capture JSON output for parsing):
- npm: `npm audit --json`
- yarn: `yarn audit --json`
- pnpm: `pnpm audit --json`

If the audit command fails, check whether dependencies are installed first and run
`npm install` / `yarn install` / `pnpm install` as needed.

**Step 3 — Enhance with CVE database lookup.**
For each vulnerability, extract CVE IDs. For critical/high severity, use `WebSearch`
with a query shaped like `CVE-XXXX-XXXXX vulnerability details exploit` to gather
exploit info, affected versions, and real-world impact. (This is the "beyond npm audit"
layer — audit output alone is enriched with live web context.)

**Step 4 — Validate findings (eliminate false positives).**
Described as a "Critical step to ensure accuracy." For each finding, run validation
web-searches to answer four questions:
1. Is the affected version correct? — search `"{package}" {CVE-ID} affected versions`, compare vs installed version.
2. Is the fix still valid? — search `"{package}" update fix {CVE-ID} 2025`, watch for breaking changes.
3. Is there a newer security advisory? — search `"{package}" security advisory latest` (npm audit data can be stale, advisories may be superseded/withdrawn).
4. Is this relevant to your use case? — search `"{package}" {CVE-ID} exploit conditions`; if the vulnerable feature isn't used, mark NOT APPLICABLE.

Each finding is then assigned a **status** that decides whether/how it appears in the report:

| Status | Meaning | Action |
|--------|---------|--------|
| CONFIRMED | Verified vuln affecting your version | Include in report |
| NOT APPLICABLE | Exists but not in your code path | Note with explanation |
| FIXED IN LATEST | Update resolves it | Include with update instructions |
| FALSE POSITIVE | npm audit error / withdrawn advisory | Exclude from report |
| NEEDS REVIEW | Cannot verify automatically | Include for manual review |

**Step 5 — Generate the security report** (markdown), saved to a dated path (see below).

## Inputs / outputs / artifacts

**Inputs:** the project's lock file + `package.json`; audit JSON; live web-search results.

**Output artifact — a dated markdown report at:**
```
/knowledge-base/security/dependency-vulnerabilities/{YYYY-MM-DD}.md
```
Directories are created if missing. ISO date filenames (`YYYY-MM-DD`) are mandated so
reports sort chronologically; **previous reports are preserved for historical comparison**
(not overwritten — one file per scan date).

**Report structure** (from the template in SKILL.md):
- Header: Generated timestamp, Project name (from package.json), Package Manager
- **Executive Summary** (counts; or "No security vulnerabilities detected..." when clean)
- **Severity Breakdown** table: Critical / High / Moderate / Low / Total counts
- **Vulnerabilities** section — per vuln, a `{package_name}@{version}` block with a table of:
  Severity, Status, CVE, Vulnerable Versions, Patched Version, Dependency Path — plus
  Description, Validation ("how this was verified"), Remediation (a fix command in a
  bash block, e.g. `npm update package-name`), and Additional Context (CVE lookup detail
  for critical/high).
- **Recommended Actions** (prioritized)
- **Next Steps** (e.g. run `npm audit fix`, review breaking changes, schedule audits)
- Footer: `*Report generated by dependency-vulnerability-check skill*`

**Console output behavior after generating** (SKILL.md "Output format"):
- If vulns found: show summary with critical/high counts, list top 3 most severe briefly,
  give path to full report, suggest `npm audit fix`.
- If clean: report the project is clean, still write a minimal report noting no issues,
  suggest scheduling periodic checks.

## CLI / commands (verbatim from source)

Audit commands:
- `npm audit --json`
- `yarn audit --json`
- `pnpm audit --json`

Install fallbacks: `npm install` / `yarn install` / `pnpm install`
Auto-fix suggestion: `npm audit fix` (or package-manager equivalent)

Scheduling (via the separate `/loop` capability):
- Daily: `/loop 1d /freya-devkit:dependency-vulnerability-check`
- Weekly: `/loop 1w /freya-devkit:dependency-vulnerability-check`

WebSearch query templates used for enrichment/validation:
- `CVE-XXXX-XXXXX vulnerability details exploit`
- `"{package}" {CVE-ID} affected versions`
- `"{package}" update fix {CVE-ID} 2025`
- `"{package}" security advisory latest`
- `"{package}" {CVE-ID} exploit conditions`

## How it composes with other skills

- **codebase-security-scan** — the explicit partner. That skill's SKILL.md (line 1098)
  says: "This skill complements the `dependency-vulnerability-check` skill" and frames
  the split as supply-chain (deps) vs application-code (your source). They are meant to
  be run together for full coverage but are otherwise independent.
- **`/loop`** — not a freya-devkit skill but the recommended driver for periodic/scheduled
  runs (daily/weekly cron-like scanning).
- **Not wired into `wrap-up`.** Grep across `skills/` shows the only cross-reference to
  this skill is from `codebase-security-scan/SKILL.md`. wrap-up runs its own security
  scan step but does not invoke dependency-vulnerability-check. (See gotchas.)

## Degradation behavior / edge cases

From SKILL.md "Handling edge cases":
- **No lock file found:** ask the user to run the package-manager install first.
- **Outdated lock file:** warn that deps may have changed since last install.
- **Private packages:** note that private-registry packages may lack CVE data.
- **Monorepos:** run audit in each package directory that has its own `package.json`.
- **Transitive dependencies:** clearly show the dependency path so users see where a vuln enters.
- **Audit command fails:** treated as "deps probably not installed" → install then retry.
- **Non-Node.js project:** skill declines and tells the user it needs a Node.js project.

## Honest limits

- **Node.js / npm-ecosystem only.** No support for pip, cargo, go modules, Maven, etc.
  The whole detection layer keys off npm/yarn/pnpm lock files.
- **Accuracy depends on WebSearch + agent judgement.** Validation (false-positive
  elimination, applicability) is done by the model reading search results, not by a
  deterministic tool — quality varies with search availability and model reasoning.
- **npm audit's own limitations apply** (advisory-DB coverage, transitive-only findings,
  noisy dev-dependency alerts). The skill acknowledges audit data "may be slightly outdated."
- **No auto-remediation.** It reports and suggests `npm audit fix` / update commands but
  does not apply fixes itself.
- **CI/CD note is aspirational:** SKILL.md says "For CI/CD integration, the skill can be
  run as part of your pipeline with non-zero exit codes for critical vulnerabilities" —
  but there is no script implementing exit-code logic; this describes the underlying
  `npm audit` behavior, not skill-provided tooling.

## Verbatim quotable lines

- "Scans project dependencies for security vulnerabilities using npm audit, yarn audit, or pnpm audit." (frontmatter description)
- "Cross-references with CVE databases for comprehensive coverage." (frontmatter description)
- "**Critical step to ensure accuracy.** Before including findings in the report, validate each one:" (Step 4)
- "npm audit data may be slightly outdated" (Step 4, validation check 3)
- "This skill complements the `dependency-vulnerability-check` skill" (`codebase-security-scan/SKILL.md:1098`)
- "Dependency scan: Supply chain security / Codebase scan: Application code security" (`codebase-security-scan/SKILL.md:1100–1101`)
- "Always save reports with ISO date format (YYYY-MM-DD) for easy chronological sorting" (Important notes)
- "Previous reports are preserved for historical comparison" (Important notes)

## Gotchas / UNVERIFIED

- **Report path discrepancy between registry blurbs.** The installed freya-devkit skill
  description and SKILL.md both use `/knowledge-base/security/dependency-vulnerabilities/`.
  A *different* variant surfaced in the environment (`skill-creator:dependency-vulnerability-check`)
  cites `/docs/security-reports/dependency-vulnerabilities/`. The authoritative path for
  this repo's skill is the **knowledge-base** one (per the actual SKILL.md). The docs/
  path appears to be a stale/other copy — treat knowledge-base as canonical.
- **`.gitignore` guidance:** SKILL.md suggests the report directory "should be added to
  `.gitignore` if reports contain sensitive information about your stack." This is a
  suggestion, not enforced by the skill. (Note: other freya-devkit skills git-track
  knowledge-base artifacts, so this may conflict with wrap-up's commit behavior — UNVERIFIED
  whether the two paths overlap in practice.)
- **`2025` literal in a validation query** (`"{package}" update fix {CVE-ID} 2025`) is
  hardcoded in the template and will age; the model is expected to substitute the current
  year but the source text says `2025`.
- **No evals/tests** ship for this skill, so triggering accuracy and report quality are
  unmeasured within the repo (unlike skills that carry `evals/`).
