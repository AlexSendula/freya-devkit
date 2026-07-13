# Conventions

Integration conventions for creating skills that work well with this ecosystem. These are guidelines, not requirements - adapt as needed.

## SKILL.md Structure

While the official skill-development guide covers general structure, here are ecosystem-specific conventions:

### Frontmatter: Integration Declarations

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

The `INTEGRATION` and `Used by` lines help AI agents understand relationships.

### Integration Section in Body

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

## Command Patterns

### Update vs Scan

| Command | Scope | When to Use |
|---------|-------|-------------|
| `scan` | Full codebase | Initial setup, complete refresh |
| `update` | Changed files only | Day-to-day after code changes |
| `update <target>` | Specific item | Focused update |

Example:
```markdown
## Commands

| Command | Description |
|---------|-------------|
| `scan` | Full codebase scan |
| `update` | Git-aware incremental sync (recommended) |
| `update <name>` | Update specific item |
```

### Help Command

Always include a help command:

```markdown
### `/my-skill help`

Display usage information including:
- What the skill does
- Available commands
- Usage examples
```

## Incremental Update Convention

Skills that support incremental updates should:

1. **Track state** in a dotfile under the skill's `knowledge-base/` output directory:
   ```
   knowledge-base/<skill-output-dir>/.my-skill-last-update
   ```

2. **Read state** at start:
   ```markdown
   ### Phase 1: Change Detection
   1. Read `.my-skill-last-update` for last commit hash
   2. If missing, fall back to full scan
   3. Run `git diff <last-commit>..HEAD --name-only`
   ```

3. **Write state** at end:
   ```yaml
   # .my-skill-last-update
   commit: <current-hash>
   timestamp: <ISO-8601>
   items_processed: <count>
   ```

4. **Document fallback**:
   ```markdown
   If no tracking file exists, performs full scan like `scan` command.
   ```

## Code-Graph Integration

Skills that benefit from dependency awareness should:

### Check Availability

```markdown
**If `/freya-devkit:code-graph` skill is available:**
- Call `/freya-devkit:code-graph impact <changed-files>` for blast radius
- Include dependent files in processing

**If code-graph is not available (fallback):**
- Use only directly changed files from git diff
- Warn user: "code-graph not available - reduced coverage"
```

### Use Impact Analysis

```markdown
### Phase 2: Impact Analysis

1. Get changed files from git diff
2. **If `/freya-devkit:code-graph` available:**
   - `/freya-devkit:code-graph impact <changed-files>` → blast radius
   - Process all files in blast radius
3. **Fallback:**
   - Process only directly changed files
```

### Document the Integration

```markdown
## Code-Graph Integration

When available, this skill uses /freya-devkit:code-graph for:
- Impact analysis in update mode
- Understanding dependency chains

Fallback: Simple git diff if code-graph unavailable.
```

## Spec-Manager Integration

Skills that might flag intentional design should:

### Cross-Reference Before Reporting

```markdown
### Validation Phase

For each finding:
1. Identify affected feature/component
2. Check `/knowledge-base/specs/` for matching spec
3. Look for `intentional_decisions` or `security_implications`
4. If match found → mark as INTENTIONAL DESIGN
```

### Include Spec References

```markdown
| Field | Value |
|-------|-------|
| **Status** | Intentional Design |
| **Spec Reference** | `knowledge-base/specs/features/post-management.md` |
```

## Artifact Location Convention

Generated artifacts follow this structure:

```
knowledge-base/
├── README.md          ← Documentation index (docs-manager)
├── principles.md      ← Project constitution (spec-manager)
├── BACKLOG.md         ← Outstanding-work backlog, generated (status)
├── reference/         ← Project documentation (docs-manager)
├── specs/             ← Feature specifications (spec-manager)
├── decisions/         ← Cross-cutting ADRs (spec-manager)
├── intents/           ← Declared-intent records INTENT-NNN (spec-manager)
├── security/          ← Security findings (security-scan)
│   └── <scanner-name>/
│       └── YYYY-MM-DD.md
└── .graph/            ← Dependency data (code-graph) + behavior.json (behavior-graph)
```

New skills should place output in appropriate subdirectories.

## Report File Convention

Dated reports:

```markdown
- Location: knowledge-base/<type>/<YYYY-MM-DD>.md
- Overwrites existing: Yes (same date = same file)
- History: Use git to see previous versions
```

Example:
```
knowledge-base/security/codebase-security/2024-03-27.md
```

## Tracking File Convention

```yaml
# .<skill>-last-update (or .<skill>-last-<action>)
commit: abc123def456
timestamp: 2024-03-27T10:30:00Z
<relevant_metrics>: <values>
```

Location: In the directory containing the skill's primary output.

## Evals Structure

Skills can include evaluation tests:

```
skill-name/
├── SKILL.md
└── evals/
    └── evals.json
```

The evals.json structure:
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

## Writing Style for This Ecosystem

Beyond the official skill-development guidelines:

### Reference Other Skills Naturally

```markdown
# Good
This skill uses /freya-devkit:code-graph for impact analysis when available.

# Avoid
This skill requires the code-graph skill (install from...).
```

### Acknowledge Uncertainty

```markdown
# Good
Certainty: 75% (code lacks comments, inferred from patterns)

# Avoid
This is definitely how it works.
```

### Document Fallbacks

```markdown
# Good
If /freya-devkit:code-graph unavailable, falls back to git diff.
This provides reduced coverage but remains functional.

# Avoid
Requires code-graph to work.
```

## Creating New Skills

When creating a skill for this ecosystem:

1. **Check existing skills** - Can you extend an existing one?
2. **Consider integration** - Would this benefit from code-graph? spec-manager?
3. **Follow patterns** - Coordinator+workers? Incremental updates?
4. **Document integration** - Add INTEGRATION section to frontmatter
5. **Provide fallbacks** - What happens if dependencies are missing?
6. **Place artifacts correctly** - Follow the knowledge-base/ structure

## Integration Checklist

Before considering a skill complete for this ecosystem:

- [ ] Frontmatter includes TRIGGER phrases
- [ ] INTEGRATION section documents dependencies
- [ ] Fallback behavior described if dependencies missing
- [ ] Artifacts placed in appropriate knowledge-base/ subdirectory
- [ ] Tracking file convention followed (if incremental)
- [ ] Help command included
- [ ] Cross-references to related skills where appropriate
