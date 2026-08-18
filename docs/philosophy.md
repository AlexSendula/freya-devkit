# Philosophy

The core beliefs and mental model behind this skills ecosystem.

## Why Skills Over Monolithic Prompts

Traditional AI assistance uses one big prompt with all instructions. This approach has problems:

- **Context bloat**: Everything loaded even when not needed
- **Hard to maintain**: One change affects everything
- **No modularity**: Can't mix and match capabilities

Skills solve this by being:

- **Focused**: Each skill does one thing well
- **Composable**: Skills can use other skills
- **Progressive**: Load what you need, when you need it

## The Mental Model

Think of skills as **specialized team members** working on a codebase:

```
┌─────────────────────────────────────────────────────────┐
│                     Your Codebase                        │
└─────────────────────────────────────────────────────────┘
                           │
       ┌───────────────────┼───────────────────┐
       │                   │                   │
       ▼                   ▼                   ▼
┌─────────────┐    ┌─────────────┐    ┌─────────────┐
│ code-graph  │    │ docs-manager│    │spec-manager │
│  "Analyst"  │    │ "Writer"    │    │ "Architect" │
└─────────────┘    └─────────────┘    └─────────────┘
       │                   │                   │
       └───────────────────┼───────────────────┘
                           │
                           ▼
                  ┌─────────────┐
                  │   wrap-up   │
                  │ "Integrator"│
                  └─────────────┘
```

Each skill has a role, knows its job, and can collaborate with others.

> This is a representative sketch, not the full roster. The toolkit is **ten skills across five tiers** — the three "team members" above plus the **behavior layer** (`behavior-graph`, `behavior-runner`), `status`, the security skills, and `dependency-vulnerability-check`. See [architecture.md](architecture.md) for the complete tier map.

## Core Concepts

### 1. Intentional Design

Code isn't just "correct" or "incorrect" - some things are **intentional**.

```yaml
# A security scan might flag this as a vulnerability:
"Missing role check on DELETE - any user can delete"

# But the spec says:
decision: "Any authenticated user can CRUD posts"
rationale: "Collaborative tool with equal access"
```

Skills should understand that some "issues" are design decisions. The `spec-manager` captures these so `codebase-security-scan` doesn't flag them.

### 2. Certainty Scoring

When AI generates documentation or specs, it doesn't always know it's right.

| Score | Meaning | Action |
|-------|---------|--------|
| 90-100 | High confidence | Trust it |
| 70-89 | Good confidence | Quick review |
| 50-69 | Medium confidence | Ask user |
| 0-49 | Low confidence | Detailed review |

This acknowledges AI uncertainty rather than hiding it.

### 3. Impact Awareness

When code changes, what else is affected?

```
code-graph tracks:
  file A imports file B
  file B is imported by files C, D, E

If A changes → check B → check C, D, E
```

Skills use `code-graph` to understand blast radius. A documentation update isn't just about changed files - it's about affected files.

### 4. Incremental Over Full

Don't re-scan everything every time.

- **Full scan**: Initial setup, complete refresh
- **Incremental**: After code changes, only process what's different
- **Tracking files**: `.spec-last-update`, `.security-last-scan` remember state

This makes skills fast enough to run frequently.

### 5. Separation of Concerns

Code changes are different from generated artifacts.

```
Commit 1: Code changes
  - src/lib/auth.ts
  - src/api/routes.ts

Commit 2: Generated artifacts
  - knowledge-base/reference/API.md
  - knowledge-base/specs/auth/SPEC-001.md
  - knowledge-base/security/...
```

The two-commit pattern keeps git history clean and lets tools reference stable commits.

### 6. Intended Behavior as First-Class

Tests are usually written *from* the code, so they verify "what the code does," not "what it should do." The behavior layer makes **intended behavior** its own first-class, executable artifact.

- Each observable behavior becomes a stable record — `BEH-NNN` — with a lifecycle `state`: `proposed → confirmed → accepted` (plus `quarantined` / `deprecated`). Only **accepted** behavior is authoritative and gates.
- `behavior-graph` projects these into `behavior.json`, a **sibling** of the code graph (`graph.json`), linking BEHAVIOR → TEST → CODE. It answers two directions of blast radius: *code change → which behaviors are affected*, and *behavior → the code that implements it*.
- `behavior-runner` runs the accepted behaviors via their test adapter and captures observed TEST → CODE coverage; where it cannot observe an edge, it says so (`unknown`, never falsely attributed).
- `wrap-up` gains a **Phase 3.5** that re-runs only the accepted behaviors a change actually touches and gates on real regressions — verification "upgraded from eyeballing prose to actually running the linked tests."

This turns specs from inert prose that nothing runs into executable, governed guarantees.

### 7. Agent-Neutral by Construction

The toolkit began as a Claude Code plugin and is now meant to run on any agent that reads
the Agent Skills standard. That is not a compatibility layer bolted on the side; it is a
constraint on how skills are written:

- **No host-specific construct in a skill.** No `${CLAUDE_PLUGIN_ROOT}`, no
  `/freya-devkit:` slash names, no host tool names, no `~/.claude` paths. Every script is
  invoked as `freya <command>`, through one self-locating launcher.
- **Capabilities are asked for, not assumed.** Where a skill wants parallelism it says
  *"in parallel if your agent supports subagents, one at a time otherwise"* — and says
  what the sequential path costs, so degrading is a choice rather than a surprise.
- **A guarantee that lives in a sentence is a suggestion.** Where the property actually
  matters, prose is not enough: validation caught a host running a six-way fan-out
  sequentially and reporting it as parallel. The security scan therefore drives its own
  worker processes, because the one thing an agent cannot be asked is whether it did what
  it said.

The last point generalizes: *prefer the mechanism that cannot be misreported.* Prose
where the cost of being wrong is slower; code where the cost of being wrong is a missed
vulnerability.

## What This Enables

### For Development

1. Implement a feature
2. Run `freya-wrap-up`
3. Get: updated docs, specs, security scan, all committed

### For Understanding

1. New AI session starts
2. Reads `knowledge-base/reference/` for context
3. Reads `knowledge-base/specs/` for intentional design decisions
4. Has full understanding without being told everything

### For Maintenance

1. Security scan finds potential issues
2. Cross-references specs for intentional design
3. Reports only real vulnerabilities
4. Tracks finding lifecycle across scans

## What This Doesn't Mean

- **Not prescriptive**: Skills don't have to follow every pattern
- **Not complete**: The ecosystem grows over time
- **Not perfect**: Certainty scores acknowledge uncertainty
- **Mostly not enforced**: Conventions guide, they don't restrict

The goal is coherence and collaboration, not rigid compliance.

**One exception, and it is deliberate.** Agent-neutrality is *not* a convention — it is a
gate. `bin/check_skill_conformance.py` fails the build on a Claude-only construct in any
skill, and CI runs it on every push. The reason is that this class of mistake is
invisible where it is made: a `${CLAUDE_PLUGIN_ROOT}` path works perfectly on Claude and
breaks silently everywhere else, and an over-long `description` had one skill loading on
Claude and being dropped without a word by Copilot for five phases. Guidance cannot catch
a defect whose symptom never appears on the author's own machine.
