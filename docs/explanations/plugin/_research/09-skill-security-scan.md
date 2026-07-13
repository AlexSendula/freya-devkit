# Research Brief — Skill: `codebase-security-scan`

> Sourced backing layer for the freya-devkit plugin explainer.
> Topic: application-code security auditing — the `scan`/`update`/`audit`/`impact`/`check-specs` modes, adversarial verification of findings, `findings.json`, how specs and accepted behaviors suppress intentional design, and the Workflow-powered audit engine.

## Sources read

- `skills/codebase-security-scan/SKILL.md` — skill definition, mode catalog, per-step workflow, report template, integration notes, tracking-file spec.
- `skills/codebase-security-scan/references/findings-schema.md` — JSON schema for the machine-readable `findings.json` index.
- `workflows/codebase-security-audit.js` — the Workflow script that powers `audit` mode (loop-until-dry discovery + multi-skeptic verification).

---

## 1. What it is

`codebase-security-scan` is freya-devkit's **application-code security auditor**. It performs a comprehensive security audit of an entire codebase using **parallel specialized subagents**, each owning one of six vulnerability categories, then validates findings, tracks their lifecycle across scans, and writes a dated Markdown report plus a machine-readable `findings.json` index into the target project's `knowledge-base/`.

It is invoked namespaced as `/freya-devkit:codebase-security-scan <mode>`.

From SKILL.md frontmatter:
> "Performs comprehensive security audit of entire codebase using parallel subagents. First reads project documentation from /knowledge-base/reference for context, then scans code for vulnerabilities across multiple security categories. Generates detailed reports in /knowledge-base/security/codebase-security/ with findings, severity ratings, and remediation recommendations."

It is distinct from (and complements) `dependency-vulnerability-check`:
> "Dependency scan: Supply chain security · Codebase scan: Application code security"

It requires the `Agent, Read, Glob, Grep, Write, WebSearch` tools, and optionally composes with the `/freya-devkit:code-graph` and `/freya-devkit:spec-manager` skills.

## 2. Why it exists

The skill sits near the top of the freya-devkit tier stack (`code-graph` → `docs-manager`/`spec-manager` → `codebase-security-scan` → `wrap-up`). Its purpose is to give a project a **repeatable, false-positive-resistant, code-level security assessment** that:

1. Understands the project's actual architecture and intentional design before flagging anything (so it doesn't report spec'd behavior as vulnerabilities).
2. Tracks each finding's **lifecycle** across scans (RESOLVED / PERSISTENT / REGRESSED) rather than re-emitting a flat list every time.
3. Feeds downstream consumers — the `codebase-security-resolver` skill (which fixes findings) and `/freya-devkit:status` (which surfaces open findings on the backlog) — via a stable report format and the `findings.json` index.

A central design goal is **precision over recall panic**: two full validation layers (online-source validation + adversarial refutation) exist specifically to kill false positives before they reach a human.

## 3. Modes / CLI

Invoked as `/freya-devkit:codebase-security-scan <command>`. Commands (verbatim from the SKILL.md "Commands" table):

| Command | Description |
|---------|-------------|
| `scan` | Full codebase security scan (all files) |
| `update` | Incremental scan - only files affected by recent changes |
| `audit` | Exhaustive discovery + adversarial verification (Workflow-powered). On-demand / pre-release. |
| `impact <file>` | Show security blast radius for a specific file |
| `check-specs [report]` | Cross-reference findings against specs to identify intentional design |
| `help` | Display help information |

Recommendation guidance from the skill:
> "Use `update` for day-to-day security checks after code changes. Use `scan` for initial security assessment or complete audits. Use `audit` periodically (e.g. before a release) for an exhaustive multi-agent deep audit — it is heavier and is **not** part of the `/freya-devkit:wrap-up` pipeline. Use `check-specs` to validate existing findings against project specifications."

Verification layering, verbatim:
> "All non-`audit` modes (`scan`, `update`) include lightweight standard adversarial verification of each finding (see Step 3.5); `audit` adds exhaustive loop-until-dry discovery plus a stronger multi-skeptic verification pass."

### Scheduling
The skill documents `/loop` scheduling (the `/loop` command is a separate harness feature):
```
/loop 1w /freya-devkit:codebase-security-scan
/loop 1d /freya-devkit:codebase-security-scan update
```

## 4. The core `scan` pipeline (step by step)

The Overview lists seven stages:
> "1. Context Gathering · 2. Spec Loading · 3. Parallel Scanning · 4. Validation Phase · 5. Aggregation · 6. Re-evaluation · 7. Report Generation"

Concretely, the Workflow section defines these steps:

**Step 1 — Gather project context.** Read docs from `/knowledge-base/reference` to understand architecture, auth/authz, data flows, API endpoints, infrastructure. It looks for files like `architecture.md`, `api.md`, `auth.md`, `data-flow.md`, `deployment.md`, `README.md`. If no docs exist, it notes that and proceeds.

**Step 2 — Load project specs.** Marked "CRITICAL for accurate security assessment." Reads `/knowledge-base/specs/` (esp. `/knowledge-base/specs/features/`) to learn intentional design decisions. Key illustrative rationale:
> "A security scan might flag 'Missing role check on DELETE - any authenticated user can delete any post' as a vulnerability. But if the spec says 'Any authenticated user can CRUD posts', this is **intentional design**, not a security flaw."

Step 2 **also** cross-references *accepted behaviors* (from the behavior layer), described as strictly stronger evidence than a prose spec:
> "an `accepted`, test-backed behavior whose intent explains a finding is the **strongest** 'intentional' evidence — a verified guarantee, not a prose claim."
> "Only `accepted` behaviors downgrade a finding; `proposed`/`confirmed` add at most an advisory note and the finding stays open."

**Step 3 — Spawn parallel security agents.** Six specialized agents run **in parallel**, one per category:
1. **Authentication & Authorization** — hardcoded creds, weak password policy, missing auth checks, insecure sessions, broken access control, JWT/oauth misconfig.
2. **Input Validation & Injection** — SQL injection, XSS, command injection, path traversal, SSRF, unsafe deserialization, missing sanitization.
3. **Secrets & Sensitive Data** — exposed secrets, secrets in logs, PII exposure, insecure storage, missing encryption, hardcoded keys/IVs.
4. **API & Network Security** — missing rate limiting, CORS misconfig, missing HTTPS, insecure endpoints, exposed internal APIs, GraphQL issues.
5. **Configuration & Dependencies** — debug mode in prod, exposed admin endpoints, insecure defaults, missing security headers, outdated middleware, env-var exposure.
6. **File & Resource Handling** — unsafe uploads, path traversal in file ops, missing type validation, insecure temp files, resource exhaustion, unsafe permissions.

Agents grep for patterns (the SKILL.md lists generic regex examples for secrets, SQL injection, XSS, command injection, path traversal), then Read the surrounding code for context.

**Step 3 (Validation Phase) — false-positive elimination via WebSearch.** For each candidate finding, verify against current online sources and specs: is it still a vulnerability for this version, is the remediation current, are there framework-specific considerations, and is it intentional design per specs? Documented example: a "missing middleware.ts" finding is dropped as FALSE POSITIVE once WebSearch reveals a framework renamed `middleware` to `proxy`. Conservatism rule: "If uncertain, include with 'NEEDS REVIEW' status rather than discarding."

**Step 3.5 — Adversarial Verification (Standard).** See §6 below.

**Step 4 — Aggregate findings** by severity, category, file location, ease of remediation.

**Step 5 — Re-evaluate previous findings.** See §7 (lifecycle tracking).

**Step 6 — Generate the security report** at `/knowledge-base/security/codebase-security/YYYY-MM-DD.md`, plus the `findings.json` index.

## 5. Finding statuses

After validation, each finding carries one of these statuses (from the "Finding Status Categories" table):

| Status | Meaning | In report? |
|--------|---------|-----------|
| CONFIRMED | Verified vulnerability, still applicable | Yes, full detail |
| MITIGATED | Exists but has compensating controls | Yes, note mitigation |
| INTENTIONAL DESIGN | Appears as vuln but is spec'd behavior | Yes, with spec reference |
| FALSE POSITIVE | Not actually a vuln / outdated info | **No** |
| NEEDS REVIEW | Cannot determine automatically | Yes, marked for review |
| PERSISTENT | Found in previous scan, still unresolved | Yes, note duration/first-detected |
| RESOLVED | Previously reported, now fixed/removed | Yes, in "Resolved Findings" section |
| REGRESSED | Previously mitigated, controls removed | Yes, flagged for immediate attention |

Crucially, verification never invents new statuses:
> "Step 3.5 (Adversarial Verification) maps its verdicts onto these existing statuses; it never introduces a new status."

## 6. Adversarial verification (the false-positive killer)

There are **two** verification implementations sharing the same philosophy — a lightweight prose one for `scan`/`update`, and a heavier Workflow one for `audit`.

### 6a. Step 3.5 — Standard adversarial verification (`scan`/`update`)
Explicitly *not* the Workflow tool — it runs synchronously in the main loop so it composes inside `/freya-devkit:wrap-up`'s linear pipeline:
> "This is NOT the Workflow tool — keep it synchronous and prose-driven so it composes inside `/freya-devkit:wrap-up`'s linear pipeline (the heavier Workflow-powered version lives in `audit`)."

For each *surviving* finding it runs **2–3 independent refutation passes**, each prompted to *disprove* the finding, one per lens:
1. **Exploitability / reachability** — construct a concrete path from an untrusted entry point to the code; if unreachable, refuted.
2. **Compensating controls** — find existing validation/sanitization/auth-gate/framework-default/upstream guard that neutralizes it; if found, refute or downgrade to MITIGATED.
3. **Intentional / spec'd** — check `/knowledge-base/specs/` and code comments; if spec'd, reclassify to INTENTIONAL DESIGN.

Each pass returns REFUTED or UPHELD, run in parallel across findings. Disposition mapping:

| Refutation result | Status assigned |
|-------------------|-----------------|
| Majority UPHELD (2/2, 2/3, 3/3) | Existing Step 3 status (CONFIRMED / MITIGATED) |
| **Unanimous** REFUTED on exploitability/controls | FALSE POSITIVE (excluded) |
| Majority REFUTED as spec'd | INTENTIONAL DESIGN (+ spec reference) |
| Split / inconclusive | NEEDS REVIEW |

Conservatism rule, verbatim:
> "only a **unanimous** refutation drops a finding. Any disagreement (split verdict) keeps it as **NEEDS REVIEW** — never silently delete an upheld or contested finding."

The verdict is recorded as one **additive, optional** row in the finding table so downstream parsers are unaffected:
> "Format: `<Upheld|Refuted|Split> <n>/<total> · <lenses that drove the verdict>` — e.g. `Upheld 2/2 · exploitability+controls`."

Cost guardrail: fixed 2–3 passes per finding; on a large full `scan`, "verify Critical/High exhaustively and sample Medium/Low rather than blocking the report."

### 6b. `audit` mode — Workflow-powered deep audit
`audit` is an on-demand / pre-release exhaustive audit powered by the **Workflow tool**, explicitly **not** wired into `wrap-up`:
> "Do NOT wire `audit` into `/freya-devkit:wrap-up` — it would inject a background multi-agent workflow into wrap-up's linear commit pipeline."

How it differs from `scan`:
> "`scan` does one parallel pass of the 6 finders + standard verification (Step 3.5). `audit` runs the finders in a **loop-until-dry** (repeat until K=2 consecutive empty rounds, max 5 rounds) for exhaustive coverage, then runs **3 diverse-lens skeptics** (exploitability, compensating-controls, spec-intentional) per finding."

**Critical division of labor** — the Workflow returns DATA, the skill writes the REPORT:
> "The workflow agents do NOT write the report, assign `SEC-###` IDs, or re-evaluate previous findings. They run as `Explore` agents (read-only — no Write) and return a JSON array of deduped, adversarially-verified findings. The skill's **main loop** then does everything that keeps the report format stable."

`audit`'s four phases:
- **Phase 1** — invoke the workflow; it returns a JSON array of survivors, each with `disposition` (`confirmed` / `mitigated` / `intentional-design` / `needs-review`), optional `specReference`, and `verification` (`{ upheld, total, lenses }`). No IDs, no file writes.
- **Phase 2** — re-evaluate previous findings (reuse Step 5 unchanged, in the skill).
- **Phase 3** — assign `SEC-###` IDs, map `disposition`→Status (`confirmed`→CONFIRMED, `mitigated`→MITIGATED, `intentional-design`→INTENTIONAL DESIGN, `needs-review`→NEEDS REVIEW), render the additive Verification row (`Upheld {upheld}/{total} · {lenses}`), write the dated report.
- **Phase 4** — update tracking with `scan_type: audit`.

## 7. The audit Workflow engine (`workflows/codebase-security-audit.js`)

A saved Workflow script bundled with the plugin. Invocation notes from the skill:
> "Invoke it via the Workflow tool's `scriptPath` (workflows are not auto-registered as a plugin component, so name-based resolution won't find it). Fallback if `${CLAUDE_PLUGIN_ROOT}` doesn't resolve inside `scriptPath`: copy that file into your project's `.claude/workflows/` and invoke it by name (`codebase-security-audit`)."

Primary path: `scriptPath: "${CLAUDE_PLUGIN_ROOT}/workflows/codebase-security-audit.js"`. (A fallback copy is also kept at `~/.claude/workflows/codebase-security-audit.js` per the repo CLAUDE.md.)

The script's own header states the contract:
> "this workflow RETURNS structured findings as JSON. It does NOT write the report, assign SEC-### IDs, or re-evaluate previous findings — the skill's main loop does all of that... All agents use agentType 'Explore' (read-only: Read/Grep/Glob, no Write), which enforces the no-file-writes boundary at the tool level."

Runtime constraints it deliberately honors (from the header comment):
> "plain JS (not TS); meta is a pure literal; schemas are JSON Schema; no Date.now()/Math.random()/new Date() (only Math.floor is used)."

**Key constants:**
```js
const CATEGORIES = ['auth', 'injection', 'secrets', 'api', 'config', 'file']
const K_EMPTY = 2          // consecutive dry rounds to stop discovery
const MAX_ROUNDS = 5       // budget guard
const SKEPTICS = ['exploitability', 'compensating-controls', 'spec-intentional']
```

**Three phases** (declared in `meta.phases`): Context → Discovery → Verify.

- **Phase 1 (Context):** one `Explore` agent reads `/knowledge-base/reference` and `/knowledge-base/specs` and summarizes architecture, auth model, trust boundaries, untrusted entry points, and an explicit list of SPEC'D-INTENTIONAL behaviors that must not be reported. Returns prose reused downstream.

- **Phase 2 (Discovery), loop-until-dry:** while `dry < K_EMPTY && round < MAX_ROUNDS`, it runs all 6 categories **in parallel**, passing each finder the context and the set of already-seen dedup keys ("skip these"). Fresh findings (not already `seen`) are deduped and accumulated. A round with no fresh findings increments `dry`; any fresh findings reset `dry = 0`. So discovery stops only after **2 consecutive empty rounds**, capped at **5 rounds** total.

  Dedup key (composite — collapses same file + same 5-line window + same category):
  ```js
  const key = (f) => `${f.file}::${Math.floor(f.line / 5)}::${f.category}`
  ```

- **Phase 3 (Verify):** for every accumulated finding, run all **3 skeptic lenses in parallel**, each prompted "Your job is to REFUTE this finding, not confirm it," returning `{ verdict: 'refuted' | 'upheld', reason, specReference? }`. Disposition logic:
  ```js
  if (specRefute) disposition = 'intentional-design'
  else if (upheld * 2 > total) disposition = 'confirmed'   // majority upheld
  else if (upheld === 0) disposition = 'drop'              // unanimous refute -> false positive
  else disposition = 'needs-review'                        // split / inconclusive
  ```
  A `spec-intentional` lens returning `refuted` forces `intentional-design` (with its `specReference`). The workflow returns only survivors — `drop` (unanimous refute) never leaves the workflow, so the skill/resolver never see false positives:
  ```js
  return verified.filter(Boolean).filter((r) => r.disposition !== 'drop')
  ```

Note the workflow's disposition vocabulary (`confirmed`/`mitigated`/`intentional-design`/`needs-review`/`drop`) is deliberately distinct from the report's Status vocabulary; the skill's Phase 3 maps between them. In the script itself, `mitigated` appears in the contract/skill description as a possible disposition but the inline disposition logic only emits `confirmed`, `intentional-design`, `drop`, and `needs-review` (see gotchas).

## 8. `update` mode (incremental, git-aware)

Seven phases:
1. **Change Detection** — read `.security-last-scan` for the last commit hash; if missing, fall back to full `scan`; run `git diff <last-commit>..HEAD --name-only`; if no changes, report "no security-relevant changes detected" and exit.
2. **Impact Analysis (code-graph enhanced)** — if `/freya-devkit:code-graph` is available, call `/freya-devkit:code-graph impact <changed-files>` to pull in dependent files; otherwise fall back to only directly changed files (with a warning).
3. **Targeted Security Scanning** — spawn the six agents only over affected files.
4. **Blast Radius Analysis** — call `/freya-devkit:code-graph dependents <vulnerable-file>`; assign priority by dependent count (1–3 = Low, 4–10 = Medium, 10+ = High).
5. **Re-evaluate Previous Findings** — RESOLVED / PERSISTENT / REGRESSED.
6. **Generate Incremental Report** — overwrite the same `YYYY-MM-DD.md` (no suffixes), including a Resolved Findings section.
7. **Update Tracking** — write `.security-last-scan` (`scan_type: incremental`).

## 9. `impact <file>` mode

Shows the security blast radius for one file: analyzes it for security-relevant patterns (auth/crypto/data handling), then (if code-graph is available) lists direct + transitive dependents and derives security implications and remediation priority. If code-graph is unavailable, `impact` returns a "code-graph not available" error.

## 10. `check-specs [report]` mode (intentional-design cross-reference)

Cross-references an existing report's findings against specs (and accepted behaviors) to downgrade false positives to INTENTIONAL DESIGN. Optional `report` arg; defaults to the most recent report.

Four phases: **Load Findings** → **Load Specs** (index by endpoint/route, security keywords like `auth, access, role, permission, delete, admin`, `security_implications` markers, decision rationale) → **Cross-Reference Each Finding** → **Update Original Report In Place** (adds a "Spec Validation" section; **no new file**).

Two evidence sources in Phase 3:
- **Declarative specs** — a matching spec that allows the "vulnerable" behavior sets status INTENTIONAL DESIGN and records `spec_ref` + rationale.
- **Accepted behaviors (the stronger evidence)** — run the behavior graph to find accepted behaviors covering the finding's file:
  ```bash
  python "${CLAUDE_PLUGIN_ROOT}/skills/behavior-graph/scripts/behavior_graph.py" \
    --covering <finding-file> --project .
  ```
  If an accepted behavior explains the finding, set INTENTIONAL DESIGN and record `behavior_ref: BEH-NNN`, noting *"verified by passing test BEH-NNN (SPEC-MMM)"*. Verbatim:
  > "Only `accepted` behaviors downgrade a finding. `--covering` returns only accepted behaviors; if a `proposed`/`confirmed` behavior is known to be relevant, add only an advisory note ('intended per BEH-NNN, but test owed — not yet verified') and **leave the finding open**."

## 11. Inputs / outputs / artifacts

All artifacts live **inside the target project** under `knowledge-base/`.

**Inputs (read):**
- `/knowledge-base/reference/*` — architecture/auth/data-flow/deployment docs (context).
- `/knowledge-base/specs/` and `/knowledge-base/specs/features/` — intentional-design decisions.
- Behavior graph (via `behavior-graph`) — accepted behaviors for the strongest intentional evidence.
- `knowledge-base/security/.security-last-scan` — last-scan commit hash (for `update`).
- `git diff` — changed files (for `update`).

**Outputs (written):**
- `knowledge-base/security/codebase-security/YYYY-MM-DD.md` — the prose report. **Overwritten** on every run (same filename, no `-2`/`-3` suffixes; git provides history).
- `knowledge-base/security/codebase-security/findings.json` — machine-readable index (see §12), overwritten each run.
- `knowledge-base/security/.security-last-scan` — tracking file (YAML):
  ```yaml
  # Security Scan Last Update
  commit: <current-hash>
  timestamp: <ISO-8601>
  files_scanned: <count>
  findings: <count>
  scan_type: incremental   # or: audit
  ```

**Report structure:** Executive Summary → Severity Breakdown → Critical Findings (per-finding tables with Severity, Category, Status, optional additive **Verification** row, Location, CWE, Blast Radius, Spec Reference) → Previous Findings Re-evaluation (Status Changes / Resolved / Persistent / Regressed) → Security Posture Assessment → Scan Coverage → Next Steps.

File-behavior table (verbatim):
| Command | File Behavior |
|---------|---------------|
| `scan` | Creates/overwrites `YYYY-MM-DD.md` |
| `update` | Overwrites existing `YYYY-MM-DD.md` (same file, updated content) |
| `check-specs` | Updates existing report in place (no new file) |

## 12. `findings.json` schema

Written alongside the prose report so other skills (notably `/freya-devkit:status`) can read findings without parsing prose. Git-tracked, overwritten each run, mirrors the prose report exactly.

```json
{
  "version": 1,
  "scanned_commit": "<git HEAD short hash at scan time>",
  "report": "knowledge-base/security/codebase-security/<YYYY-MM-DD>.md",
  "findings": [
    {
      "id": "SEC-001",
      "title": "Short finding title",
      "severity": "high | medium | low | info",
      "status": "open | resolved | intentional",
      "file": "src/path/to/file.ts",
      "line": 42,
      "spec_ref": "SPEC-001",
      "behavior_ref": "BEH-003"
    }
  ]
}
```

Field rules of note:
- `status` is one of `open` / `resolved` / `intentional` (note: this JSON vocabulary is *coarser* than the prose report's 8 statuses — e.g. CONFIRMED/MITIGATED/NEEDS REVIEW/PERSISTENT/REGRESSED all map to `open`).
- `intentional` requires either a `spec_ref` (a declarative spec — a prose claim) **or** a `behavior_ref` (an `accepted`, test-backed behavior — a *verified guarantee*, the stronger evidence). A finding may carry both.
- Consumers "treat any finding whose `status` is not `open` as not outstanding."

## 13. How it composes with other skills

- **`code-graph`** (optional dependency): powers `update`'s impact analysis (scan dependents, not just changed files), blast-radius priority in findings, and the whole `impact` command. Fallback: `update` degrades to git-diff-only; `impact` errors out; `scan` is unaffected (it doesn't need code-graph).
- **`spec-manager`** (optional dependency): supplies the specs read in Step 2 / the intentional-design cross-reference / `check-specs`. Without specs, findings "may include intentional design decisions" (warned).
- **`behavior-graph` / behavior layer**: supplies *accepted behaviors* — the strongest intentional-design evidence — via `behavior_graph.py --covering`.
- **`codebase-security-resolver`** (downstream consumer): reads the report (and its stable required fields) to interactively fix findings. The additive Verification row and `findings.json` are designed not to break its parsing.
- **`/freya-devkit:status`**: reads `findings.json` to surface open findings on the backlog.
- **`/freya-devkit:wrap-up`**: runs the security scan as one step of its post-implementation pipeline — using `update` (the linear, synchronous mode), **never** `audit`.
- **`dependency-vulnerability-check`**: complementary sibling — supply-chain security vs. this skill's application-code security.

## 14. Degradation behavior

- **No docs in `/knowledge-base/reference`** → note it, proceed with code scanning.
- **No specs in `/knowledge-base/specs/`** → note it, proceed, but warn findings may include intentional design.
- **No `code-graph` skill** → `update` falls back to git-diff-only changed files (with a warning); `impact` returns "code-graph not available"; `scan` unaffected.
- **No `.security-last-scan`** → `update` falls back to a full `scan`.
- **No git changes since last scan** → `update` exits with "no security-relevant changes detected."
- **No previous report** → Step 5 lifecycle re-evaluation is skipped; report notes this is the baseline.
- **`${CLAUDE_PLUGIN_ROOT}` unresolved in `scriptPath`** → copy the audit workflow into `.claude/workflows/` and invoke by name.
- **Large full `scan`** → verify Critical/High exhaustively, sample Medium/Low, to avoid blocking the report.

## 15. Honest limits

- **LLM-agent-driven, not a deterministic scanner.** The "agents," "parallel scanning," "refutation passes," and validation are prompt-driven subagent behavior described in SKILL.md — there is **no** deterministic engine for `scan`/`update`/`impact`/`check-specs` (unlike code-graph's `graph_ops.py`). Only the `audit` mode has an actual script (`codebase-security-audit.js`), and that script still delegates all real analysis to LLM `Explore` agents.
- **WebSearch dependency.** The validation phase relies on WebSearch for currency checks; results vary with what the model retrieves.
- **Recall is bounded.** Even `audit`'s loop-until-dry is capped at `MAX_ROUNDS = 5` and stops after `K_EMPTY = 2` dry rounds; the 5-line dedup window (`Math.floor(line/5)`) could theoretically collapse two genuinely distinct same-category findings within 5 lines of each other into one.
- **Verification is majority-vote, not proof.** A finding survives on a simple majority-upheld (`upheld * 2 > total`); the design intentionally errs toward keeping contested findings as NEEDS REVIEW rather than proving exploitability.

## 16. Gotchas / UNVERIFIED

- **UNVERIFIED — `mitigated` disposition in the workflow.** The audit script's `meta`/contract mentions `mitigated` as a possible disposition, and the skill's Phase 3 maps `mitigated`→MITIGATED, but the inline disposition branch in `codebase-security-audit.js` (lines 127–131) only ever produces `intentional-design`, `confirmed`, `drop`, or `needs-review`. So `mitigated` appears not to be emitted by the current engine — MITIGATED classification in `audit` mode looks unreachable from the workflow (it can still arise in `scan`/`update` Step 3.5). Worth confirming against intended behavior.
- **UNVERIFIED — no `findings.json` schema fields for the additive Verification row.** The prose report gains a Verification row, but `findings.json` (schema v1) has no field for verification verdicts, so downstream JSON consumers don't see them.
- **JSON status vocabulary is coarser than prose.** `findings.json` collapses 8 prose statuses into 3 (`open`/`resolved`/`intentional`); anything not `intentional`/`resolved` becomes `open`. This is by design but easy to miss.
- **`findings.json` id continuity.** The schema says `id` is "stable per finding across re-scans," but nothing in the source enforces stable ID assignment programmatically — it relies on the agent continuing numbering from the prior report.
- **Verbatim example paths are illustrative.** The SKILL.md's example finding paths (e.g. `src/api/routes/posts.ts:45`) and example spec `post-management.md` are generic illustrations in the skill text, not real project files.
- **`audit` timestamps.** The workflow deliberately avoids `Date.now()`/`new Date()` (runtime constraint), so the timestamp in reports/tracking is supplied by the skill's main loop, not the workflow.

## 17. Verbatim quotable lines

- "Performs comprehensive security audit of entire codebase using parallel subagents." (SKILL.md frontmatter)
- "**CRITICAL for accurate security assessment.** Read specifications from `/knowledge-base/specs/` to understand intentional design decisions that might appear as security issues." (SKILL.md Step 2)
- "But if the spec says 'Any authenticated user can CRUD posts', this is **intentional design**, not a security flaw." (SKILL.md Step 2)
- "an `accepted`, test-backed behavior whose intent explains a finding is the **strongest** 'intentional' evidence — a verified guarantee, not a prose claim." (SKILL.md Step 2)
- "This is NOT the Workflow tool — keep it synchronous and prose-driven so it composes inside `/freya-devkit:wrap-up`'s linear pipeline." (SKILL.md Step 3.5)
- "only a **unanimous** refutation drops a finding. Any disagreement (split verdict) keeps it as **NEEDS REVIEW** — never silently delete an upheld or contested finding." (SKILL.md Step 3.5)
- "Do NOT wire `audit` into `/freya-devkit:wrap-up` — it would inject a background multi-agent workflow into wrap-up's linear commit pipeline." (SKILL.md `audit`)
- "The workflow agents do NOT write the report, assign `SEC-###` IDs, or re-evaluate previous findings... The skill's **main loop** then does everything that keeps the report format stable." (SKILL.md `audit`)
- "this workflow RETURNS structured findings as JSON... All agents use agentType 'Explore' (read-only: Read/Grep/Glob, no Write), which enforces the no-file-writes boundary at the tool level." (codebase-security-audit.js header)
- "Your job is to REFUTE this finding, not confirm it." (codebase-security-audit.js verify prompt)
- "'drop' (unanimous refute) never leaves the workflow, so the skill/resolver never sees false positives." (codebase-security-audit.js)
- "Consumers treat any finding whose `status` is not `open` as not outstanding." (findings-schema.md)
