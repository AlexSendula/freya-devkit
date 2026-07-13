# Research Brief: Conventions

**Topic:** Integration conventions for the freya-devkit plugin
**Primary source:** `docs/conventions.md`
**Corroborating sources:** `skills/*/SKILL.md`, `skills/docs-manager/evals/evals.json`, actual on-disk skill layout
**Audience:** an engineer new to freya-devkit who wants to add or modify a skill so it "fits" the ecosystem.

---

## 1. What this is

`docs/conventions.md` is a **guide, not a rulebook**. Its opening line states this explicitly:

> "Integration conventions for creating skills that work well with this ecosystem. These are guidelines, not requirements - adapt as needed."

It documents the *shared vocabulary* that lets independently-authored skills compose: how to name commands, where to write artifacts, how to declare integrations in frontmatter, how to track incremental state, and how to degrade gracefully when a companion skill is absent. It is the "social contract" layer that sits above the code — the mechanism by which `code-graph`, `docs-manager`, `spec-manager`, `codebase-security-scan`, and `wrap-up` interoperate without hard-coded coupling.

It complements (does not replace) the official skill-development guide:

> "While the official skill-development guide covers general structure, here are ecosystem-specific conventions"

---

## 2. Why it exists

The plugin's design is **coordinator + loosely-coupled workers**. Skills reference each other by *name* and *convention* rather than by import. For that to work, every skill must agree on:

- **Where things live** (so `wrap-up` can find what `docs-manager`/`spec-manager`/`security-scan` produced).
- **What commands mean** (so `scan` vs `update` behave predictably across skills).
- **How to signal relationships** (so an AI agent reading frontmatter knows what calls what).
- **How to fail soft** (so a missing companion skill degrades coverage instead of breaking).

The conventions doc encodes these agreements as copy-paste-able snippets a new skill author can imitate.

---

## 3. The conventions, section by section

### 3.1 SKILL.md structure — integration declarations in frontmatter

Two frontmatter idioms carry relationship metadata for AI agents:

```yaml
---
name: my-skill
description: |
  Clear description of what this skill does.

  TRIGGER when: user says "X", "Y", "Z" or mentions specific keywords.

  INTEGRATION: Uses /other-skill (when available) for purpose.
  Used by: /wrapper-skill for orchestration.
---
```

> "The `INTEGRATION` and `Used by` lines help AI agents understand relationships."

**Verified in practice:** `INTEGRATION` / `Used by` appear in the frontmatter of `docs-manager`, `spec-manager`, `behavior-runner`, `code-graph`, `codebase-security-scan`, and `behavior-graph` SKILL.md files.

### 3.2 Integration section in the body

A parallel prose section is recommended inside the SKILL body:

```markdown
## Integration with Other Skills

### Dependencies
- **Required**: None (or list required skills)
- **Optional**: /freya-devkit:code-graph for impact analysis

### Used By
- /freya-devkit:wrap-up includes this skill in its workflow

### Fallback Behavior
If /freya-devkit:code-graph is not available, falls back to git diff analysis.
```

### 3.3 Command patterns — `scan` vs `update`

The canonical two-command model for any skill that maintains generated state:

| Command | Scope | When to Use |
|---------|-------|-------------|
| `scan` | Full codebase | Initial setup, complete refresh |
| `update` | Changed files only | Day-to-day after code changes |
| `update <target>` | Specific item | Focused update |

Recommended documentation table for a skill:

```markdown
| Command | Description |
|---------|-------------|
| `scan` | Full codebase scan |
| `update` | Git-aware incremental sync (recommended) |
| `update <name>` | Update specific item |
```

### 3.4 Help command

> "Always include a help command"

`/my-skill help` should display what the skill does, available commands, and usage examples.

### 3.5 Incremental update convention (4 steps)

Skills supporting incremental updates should:

1. **Track state in a dotfile**, doc's example: `docs/.my-skill-last-update`
   *(NOTE: the real layout uses `knowledge-base/`, not `docs/` — see §6 Drift.)*
2. **Read state at start** — read last commit hash; if missing, fall back to full scan; run `git diff <last-commit>..HEAD --name-only`.
3. **Write state at end** in YAML:
   ```yaml
   # .my-skill-last-update
   commit: <current-hash>
   timestamp: <ISO-8601>
   items_processed: <count>
   ```
4. **Document fallback:** "If no tracking file exists, performs full scan like `scan` command."

### 3.6 Code-graph integration (availability-gated)

Skills that benefit from dependency awareness should **check availability and branch**:

```markdown
**If `/freya-devkit:code-graph` skill is available:**
- Call `/freya-devkit:code-graph impact <changed-files>` for blast radius
- Include dependent files in processing

**If code-graph is not available (fallback):**
- Use only directly changed files from git diff
- Warn user: "code-graph not available - reduced coverage"
```

The impact-analysis phase pattern:

```markdown
### Phase 2: Impact Analysis
1. Get changed files from git diff
2. **If `/freya-devkit:code-graph` available:**
   - `/freya-devkit:code-graph impact <changed-files>` → blast radius
   - Process all files in blast radius
3. **Fallback:**
   - Process only directly changed files
```

### 3.7 Spec-manager integration (avoid false positives)

Skills that might flag *intentional* design should cross-reference specs before reporting:

```markdown
### Validation Phase
For each finding:
1. Identify affected feature/component
2. Check `/knowledge-base/specs/` for matching spec
3. Look for `intentional_decisions` or `security_implications`
4. If match found → mark as INTENTIONAL DESIGN
```

And surface the reference in output:

```markdown
| Field | Value |
|-------|-------|
| **Status** | Intentional Design |
| **Spec Reference** | `knowledge-base/specs/features/post-management.md` |
```

### 3.8 Artifact location convention (the shared knowledge-base layout)

The canonical output tree — every skill writes into its own subdirectory:

```
knowledge-base/
├── README.md          ← Documentation index (docs-manager)
├── principles.md      ← Project constitution (spec-manager)
├── reference/         ← Project documentation (docs-manager)
├── specs/             ← Feature specifications (spec-manager)
├── decisions/         ← Cross-cutting ADRs (spec-manager)
├── security/          ← Security findings (security-scan)
│   └── <scanner-name>/
│       └── YYYY-MM-DD.md
└── .graph/            ← Dependency data (code-graph)
```

> "New skills should place output in appropriate subdirectories."

### 3.9 Report file convention (dated reports)

```markdown
- Location: knowledge-base/<type>/<YYYY-MM-DD>.md
- Overwrites existing: Yes (same date = same file)
- History: Use git to see previous versions
```

Example: `knowledge-base/security/codebase-security/2024-03-27.md`

Key idea: **same date = same file** (idempotent within a day); git provides history instead of accumulating dated files.

### 3.10 Tracking file convention

```yaml
# .<skill>-last-update (or .<skill>-last-<action>)
commit: abc123def456
timestamp: 2024-03-27T10:30:00Z
<relevant_metrics>: <values>
```

> "Location: In the directory containing the skill's primary output."

### 3.11 Evals structure

```
skill-name/
├── SKILL.md
└── evals/
    └── evals.json
```

Doc's minimal example schema:

```json
{
  "evals": [
    {
      "name": "eval-name",
      "prompt": "User prompt to test",
      "expected_behavior": "What should happen"
    }
  ]
}
```

*(NOTE: the actual on-disk `evals.json` uses a richer schema — see §6 Drift.)*

### 3.12 Writing style for this ecosystem

Three stylistic norms, each shown as good/avoid pairs:

- **Reference other skills naturally** — "This skill uses /freya-devkit:code-graph for impact analysis when available." (Avoid: "requires the code-graph skill (install from...)").
- **Acknowledge uncertainty** — "Certainty: 75% (code lacks comments, inferred from patterns)." (Avoid: "This is definitely how it works.")
- **Document fallbacks** — "If /freya-devkit:code-graph unavailable, falls back to git diff. This provides reduced coverage but remains functional." (Avoid: "Requires code-graph to work.")

The through-line: **optional dependencies, soft degradation, honest confidence.**

### 3.13 Creating new skills (6-step checklist)

1. Check existing skills — can you extend one?
2. Consider integration — code-graph? spec-manager?
3. Follow patterns — coordinator+workers? incremental updates?
4. Document integration — add INTEGRATION section to frontmatter.
5. Provide fallbacks — what happens if dependencies missing?
6. Place artifacts correctly — follow the docs/ structure.

### 3.14 Integration checklist (definition of done)

> Before considering a skill complete for this ecosystem:
> - [ ] Frontmatter includes TRIGGER phrases
> - [ ] INTEGRATION section documents dependencies
> - [ ] Fallback behavior described if dependencies missing
> - [ ] Artifacts placed in appropriate docs/ subdirectory
> - [ ] Tracking file convention followed (if incremental)
> - [ ] Help command included
> - [ ] Cross-references to related skills where appropriate

---

## 4. How it composes with other skills

Conventions is a **meta-document** — it doesn't run; it constrains. Its rules are what make the rest of the pipeline coherent:

- **code-graph** owns `knowledge-base/.graph/` and exposes `impact <files>`; the conventions define the availability-check + fallback contract every consumer uses.
- **docs-manager** owns `knowledge-base/README.md` + `reference/`; follows the `scan`/`update` + tracking-file conventions.
- **spec-manager** owns `specs/`, `decisions/`, `principles.md`; the spec cross-reference convention lets other skills avoid flagging intentional design.
- **codebase-security-scan** writes dated reports under `security/<scanner>/YYYY-MM-DD.md` per the report convention.
- **wrap-up** is the orchestrator; it relies on every skill obeying the artifact-location convention so it can find and commit their outputs together (the two-commit pattern).

---

## 5. Degradation behavior (as prescribed)

The conventions doc *is* the degradation policy. Its prescribed behavior:

- Companion skills are declared **Optional**, never hard **Required**, wherever feasible.
- When a companion (e.g. code-graph) is absent, skills **narrow scope** (directly-changed files only) and **warn** ("code-graph not available - reduced coverage") rather than error.
- When no tracking file exists, a skill **falls back to a full `scan`**.
- The mantra: "reduced coverage but remains functional."

---

## 6. Drift / honest limits (implemented vs documented)

These are real mismatches between `docs/conventions.md` (written earlier) and the current on-disk reality. Flag them in the explainer rather than repeat the doc verbatim.

- **`docs/` vs `knowledge-base/` naming.** The conventions doc says "Place artifacts correctly - Follow the docs/ structure" and gives the incremental example path `docs/.my-skill-last-update`, but the actual artifact root is **`knowledge-base/`** (confirmed by every current SKILL.md). The Artifact Location and Report File sections already use `knowledge-base/`, so the doc is internally inconsistent — the `docs/`-worded lines (checklist item, "Creating New Skills" step 6, incremental §1 example) are stale. Treat `knowledge-base/` as authoritative.

- **evals.json schema is richer in practice.** The doc's example uses keys `name` / `prompt` / `expected_behavior`. The real `skills/docs-manager/evals/evals.json` uses `skill_name` (top-level), and per-eval `id`, `prompt`, `expected_output`, and an `expectations` array of assertion strings. Only `docs-manager` and `spec-manager` actually ship an `evals/` dir today.

- **Tracking dotfile names in practice.** Real dotfiles observed follow the `.<skill>-last-<action>` form: `.spec-last-update` (under `knowledge-base/specs/`), `.security-last-scan` (under `knowledge-base/security/`), and `.intent-last-verified`. These match the convention's stated pattern.

- **Additional artifacts not in the doc's tree.** The current `knowledge-base/` also contains items the conventions tree omits: `BACKLOG.md`, `intents/INTENT-NNN.md`, `.graph/behavior.json`, `.graph/classifications.json`, `.graph/graph.json`, `drift-resolutions.jsonl`, `principle-resolutions.jsonl`, and `security/codebase-security/findings.json`. The doc's tree is a simplified/older snapshot; the layout has grown (behavior layer, status/backlog, resolution logs).

- **UNVERIFIED:** Whether skills programmatically *enforce* any of these conventions, or whether they are purely advisory prose imitated by convention. Nothing in the doc suggests a linter/validator; the "Integration Checklist" is a manual human checklist.

---

## 7. Quotable lines (verbatim, `docs/conventions.md`)

- "Integration conventions for creating skills that work well with this ecosystem. These are guidelines, not requirements - adapt as needed."
- "The `INTEGRATION` and `Used by` lines help AI agents understand relationships."
- "Always include a help command"
- "New skills should place output in appropriate subdirectories."
- "Overwrites existing: Yes (same date = same file)" / "History: Use git to see previous versions"
- "Location: In the directory containing the skill's primary output."
- Good/Avoid: "This skill uses /freya-devkit:code-graph for impact analysis when available." vs "This skill requires the code-graph skill (install from...)."
- "Certainty: 75% (code lacks comments, inferred from patterns)"
- "If /freya-devkit:code-graph unavailable, falls back to git diff. This provides reduced coverage but remains functional."
```
