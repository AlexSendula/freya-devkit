# Patterns

Reusable patterns that appear across multiple skills. These are conventions, not requirements - use them when they fit.

## Pattern: Coordinator + Independent Tasks

**Problem**: Processing a large codebase is slow if done one task at a time — but
not every agent can run tasks concurrently, so the pattern can't assume it will.

**Two solutions, and the second one replaced the first where it mattered most.**

*Prose fan-out (`freya-docs-manager`, `freya-spec-manager`).* One coordinator plans,
then presents N independent, self-contained tasks and schedules them with the canonical
block, copied byte-for-byte between the two skills. It says three things: run them **in
parallel — the default — if your agent supports subagents**; if it cannot, run them **one
at a time, all of them, in order**; and on a large project a sequential run accumulates
every task's reading context into a single window and may not fit, so narrow the scope
rather than let it truncate. It also names the awkward case explicitly — Copilot *does*
have subagents, but its own instructions tell it not to split a small-enough scope, so by
default it runs the tasks itself and may still describe them as parallel.
`bin/check_skill_conformance.py` rule R9 enforces the floor: any fan-out language must be
accompanied by the sentinel phrase *and* a sequential fallback. Nothing mechanical checks
the rest, so copy the block rather than paraphrasing it.

*Driver-owned fan-out (`freya-codebase-security-scan`).* Phase 6 validation asked
Copilot to run a six-way fan-out this way. It ran the six tasks itself, as a sequence
of greps, and reported them as parallel — and the agent's own account of its work is
the one thing that cannot tell you which happened. Phase 7 instrumented it: across a
twelve-way fan-out, `task` and `explore` were invoked **zero** times, and Copilot's own
sub-agent instructions say why — *"never delegate parts of a codebase that is small
enough to read directly, regardless of how it divides into separate areas"*.

Copilot **does** support subagents (`task`, `/fleet`, `/subagents`); it is simply
instructed not to use them for this shape of work at small scope, and `/fleet` is an
interactive toggle a headless `-p` run cannot set. So where the guarantee is
load-bearing, the skill now calls a driver (`freya security scan`) that schedules the
work on its own worker pool — separate OS processes, not subagents, so no agent gets a
vote. A guarantee that lives in a sentence is a suggestion.

The prose form is still right for the two skills above, and *not* because they are
smaller — `docs-manager` fans out to twelve workers, twice the security scan's six.
It is because **their workers write files.** The driver's whole security model is a
read-only allowlist, and the phase-4b spike showed a blanket grant lets a worker write
through the shell regardless of `--deny-tool=write`. A docs driver needs workers that
produce documents, which inverts the property the driver exists to guarantee. Nor is
there a compact contract to return: the audit driver hands back schema-validated JSON
for the skill to format, whereas a doc worker's output *is* the artifact.

Neither flow is security-critical, which is why a non-guaranteed fan-out is an
acceptable residual risk there. A doc written sequentially is the same doc; a
vulnerability missed sequentially is missed.

```
┌─────────────┐
│ Coordinator │  ← Analyzes structure, plans work
└─────────────┘
       │
       │ presents
       ▼
┌──────────────────────────────────────────────┐
│              Independent Tasks                │
├──────────┬──────────┬──────────┬─────────────┤
│ Task 1   │ Task 2   │ Task 3   │ Task N      │
│ (auth)   │ (api)    │ (data)   │ (features)  │
└──────────┴──────────┴──────────┴─────────────┘
       │
       │ results
       ▼
┌─────────────┐
│ Aggregation │  ← Combine results
└─────────────┘
```

**Used by**: `freya-docs-manager` and `freya-spec-manager` (scan mode) in the prose form;
`freya-codebase-security-scan` in the driver-owned form.

**When to use**: When work can be partitioned by area/category and combined at the end.
Reach for the driver form only when the *guarantee* matters and the workers are read-only
with a small structured result; otherwise the prose form is right.

**Example from docs-manager**:
```
Coordinator: Detect project type, ask user about business context
    ↓
Task 1: Generate ARCHITECTURE.md
Task 2: Generate API.md
Task 3: Generate DATABASE.md
... (in parallel if the agent supports subagents; otherwise one at a time, all of them, in order)
    ↓
Combine: Create README.md index
```

## Pattern: Two-Commit Separation

**Problem**: Generated artifacts reference code commits. If artifacts are in the same commit, the reference is unstable.

**Solution**: Separate commits for code and artifacts.

```
Commit 1 (code):
  - src/lib/auth.ts
  - src/api/routes.ts
  - tests/auth.test.ts

Commit 2 (artifacts):
  - knowledge-base/reference/API.md
  - knowledge-base/specs/auth/SPEC-001.md
  - knowledge-base/security/.../2024-03-27.md
  - knowledge-base/.graph/graph.json
```

**Benefits**:
- Security scan has stable commit to reference
- Git history is cleaner (code vs generated)
- No tracking file hacks needed

**Used by**: wrap-up

**The rule that makes it hold: only `freya-wrap-up` stages or commits.** Every other
skill writes its artifacts and stops. This belongs in the body of every artifact-writing
skill — see [conventions.md](conventions.md#artifacts-not-commits) for which skills
carry the paragraph today — because phase-6 validation watched an agent with
broad tool permissions infer a `git commit` no skill had asked for, and prose is the only
lever a skill has against that. A new artifact-writing skill needs its own
"Artifacts, not commits" paragraph; no conformance rule can check for one.

**Behavior-aware refinement**: a behavior's commit class follows its **lifecycle `state`, not its file location**. A `.feature` scaffold lives under the code tree, but until it is `accepted` and authored (its `TODO(scaffold)` marker gone) it is *intent under review* → it rides the **artifacts** commit (commit 2). Once `accepted`, its test joins the **code** commit (commit 1). `wrap-up` stages accordingly — a `proposed` scaffold is a draft proposal, not a verified guarantee.

**When to use**: When generating artifacts that reference or describe code changes.

## Pattern: Incremental Updates

**Problem**: Full scans are expensive. Most changes affect only a small area.

**Solution**: Track last processed state, only process changes since then.

```
1. Read tracking file → get last_commit: abc123
2. Run git diff abc123..HEAD → changed_files
3. If code-graph available:
     blast_radius = freya-code-graph impact changed_files
   else:
     blast_radius = changed_files
4. Process only blast_radius files
5. Update tracking file with current commit
```

**Used by**: code-graph update, docs-manager update, spec-manager update, security-scan update

**When to use**: When processing is expensive and changes are typically localized.

**Tracking files**:
```
knowledge-base/specs/.spec-last-update
knowledge-base/security/.security-last-scan
knowledge-base/.graph/graph.json (has commit field)
```

## Pattern: Certainty Scoring

**Problem**: AI-generated content isn't always correct. Users need to know confidence levels.

**Solution**: Assign a certainty score (0-100) to AI-generated specs.

| Score | Meaning | Action |
|-------|---------|--------|
| 90-100 | High confidence | Auto-accept |
| 70-89 | Good confidence | Brief review |
| 50-69 | Medium confidence | Ask user to confirm |
| 0-49 | Low confidence | Detailed review needed |

**Factors that increase certainty**:
- Code comments explain intent
- Matching documentation exists
- Clear patterns in code
- Tests present

**Factors that decrease certainty**:
- No comments
- Ambiguous code
- Multiple interpretations possible
- No tests

**Used by**: spec-manager

**When to use**: When generating content that may need human verification.

## Pattern: Intentional Design Tracking

**Problem**: Security scans flag things that are actually intentional design decisions.

**Solution**: Specs include an "intentional design decisions" section that security tools respect.

```yaml
# In a spec
intentional_decisions:
  - decision: "No password authentication fallback"
    rationale: "Would create phishing vector"
    security_note: "Ignore security tools flagging missing password auth"
```

**Flow**:
```
1. Security scan finds potential issue
2. Check specs for intentional design matching this issue
3. If found → mark as INTENTIONAL DESIGN, not vulnerability
4. Include spec reference in report
```

**Used by**: spec-manager (stores), codebase-security-scan (reads)

**When to use**: When documenting features that might look like bugs/security issues.

## Pattern: Fallback Without Dependencies

**Problem**: Skills might be used in isolation without their optional dependencies.

**Solution**: Check if dependency exists, fall back gracefully if not.

```yaml
# In SKILL.md
if freya-code-graph skill available:
    impact = freya-code-graph impact <files>
    process impact files
else:
    # Fallback: simple git diff
    process only directly changed files
    warn user about reduced coverage
```

**Used by**: All skills that have optional dependencies

**When to use**: Whenever a skill can benefit from another skill but doesn't strictly require it.

## Pattern: An Answer That Qualifies Itself

**Problem**: A caller cannot tell "nothing" from "I could not see". An empty blast radius looks
exactly like a safe change, and it gets acted on — where an error would have stopped someone.

**Solution**: Every answer carries the limits of the run that produced it, in the answer itself,
and carries nothing when there is nothing to say.

```python
# The answer, not a log line, because the consumer is another process
{
  "all_affected": ["src/a.ts", "src/b.ts"],
  "not_in_graph": [],                 # the file you asked about was unmapped
  "unmapped_source": {                # this answer is over an incomplete graph
    "files": 12,
    "extensions": {".java": 12},
    "directories": {"src/main/java/com/acme": 12}   # go grep here
  }
}
```

Three rules make it work rather than become noise:

1. **Absent when empty.** A field that fires on every repository is one a reader learns to skip
   inside a single session, after which it costs tokens forever and changes no decision.
2. **Never a refusal.** It may change what an answer says about itself; it may never change what
   the answer *is*, or whether there is one. A caveat that becomes a refusal turns a routine
   condition into an outage.
3. **Say where, not just what.** `{".java": 12}` makes the caller derive a search target;
   `{"src/main/java/com/acme": 12}` *is* one.

**Used by**: code-graph (`unmapped_source`, `not_in_graph`, `degraded_from`), behavior-runner
(`coverage: unknown` with a reason rather than an empty exercise list), spec-manager's drift
check (narrows its scope *and says so*), the security scan (exits non-zero when every worker
failed rather than reporting a clean codebase).

**When to use**: Any time a result can be narrower than the question and the caller cannot tell
from the shape. Ask what a *zero* means in your output — if it has two possible meanings, one of
them is a bug waiting to be believed.

**See**: ADR-005 (never confidently empty), ADR-029 (the answer-level version).

## Pattern: The Contract Is the Architecture, Not the Tool

**Problem**: A capability depends on a specific tool. Replacing it later means every consumer
moves with it, so the choice quietly becomes permanent.

**Solution**: Define the contract the tool satisfies, and let the tool be configuration.

```python
# substrate.py — the socket. Standard library only, so a backend can depend on it
# without inheriting anything, and structural rather than a base class.
BUILD_KWARGS = ('exclusions', 'non_interactive', 'selection_metadata')
# A backend satisfies the contract by having the right attributes, and conformance
# is checked by BINDING THE SIGNATURE, not by hasattr: "callable" is not a contract.
```

**Two implementations from the start, deliberately.** An interface with a single implementation
is fiction — it encodes the assumptions of its only caller, and nobody finds out until the
second one arrives. This is not a slogan: the substrate contract was written with one backend
behind it, and the review that built the second found the contract could not actually run
anything else. Saving the artifact, validating it and building the reverse index all still lived
*inside* the incumbent, so a conforming backend produced nothing and reported success.

**Keep the humble implementation as the floor.** The zero-install one stays installed and stays
the default, so the system degrades to *something* everywhere rather than to nothing. Adopting
the better tool is opt-in, and never automatic: scoring silently would mean installing a binary
somewhere on `PATH` changed every answer on the machine, with no diff.

**Used by**: code-graph (`substrate.py` with `homegrown` and `graphify`), the behavior layer's
adapters, the security scan's driver.

**When to use**: When you are about to pick a dependency that five things will stand on. Ask
what you would have to change to swap it in two years — if the answer is "every consumer", write
the contract first.

**See**: ADR-018, ADR-019, ADR-020.

## Pattern: Phase-Based Execution

**Problem**: Complex workflows have multiple steps that should be clear to users.

**Solution**: Break execution into named phases, report progress.

```
[Phase 1: Change Detection]
  - Found 5 changed files
[Phase 2: Impact Analysis]
  - Blast radius: 12 files
[Phase 3: Update Specs]
  - Updated 3 specs
[Phase 4: Review]
  - 2 specs need attention
```

**Used by**: Most skills with multi-step workflows

**When to use**: When workflow has distinct stages and user benefit from visibility.

## Pattern: Git-Aware State

**Problem**: Knowing "what changed" requires remembering "last state".

**Solution**: Store last-processed git commit in a tracking file.

```yaml
# .spec-last-update
commit: abc123def456
timestamp: 2024-03-27T10:30:00Z
specs_updated: 5
specs_created: 2
```

Next run:
```bash
git diff abc123def456..HEAD --name-only
# → files changed since last update
```

**Used by**: spec-manager, security-scan

**When to use**: When you need to know what changed since last run.

## Pattern: Validation Against Specs

**Problem**: Security findings might be false positives if they're actually intentional design.

**Solution**: Cross-reference findings against specs before finalizing report.

```
For each security finding:
  1. Identify affected feature/component
  2. Search specs for matching feature
  3. Check if spec explicitly allows the "vulnerable" behavior
  4. If yes → mark as INTENTIONAL DESIGN
  5. If no → keep as potential vulnerability
```

**Used by**: codebase-security-scan check-specs command

**When to use**: When generating findings that might conflict with intentional design.

## Pattern: Worker Agent Specialization

**Problem**: Generic agents are less effective than specialized ones.

**Solution**: Spawn specialized agents for specific task types.

```
# docs-manager workers:
Worker 1: PROJECT_OVERVIEW (business context)
Worker 2: ARCHITECTURE (system design)
Worker 3: DATABASE (schema, models)
Worker 4: API (endpoints, formats)
...

# security-scan workers (scheduled by the driver, not by the agent):
Worker 1: Authentication & Authorization
Worker 2: Input Validation & Injection
Worker 3: Secrets & Sensitive Data
Worker 4: API & Network Security
...
```

**Used by**: docs-manager (agent-scheduled), codebase-security-scan (driver-scheduled —
each worker is a separate headless agent process under a read-only tool allowlist)

**When to use**: When work can be partitioned by domain expertise.

## Pattern: Resolution Logs (resolve-to-proceed governance)

**Problem**: Some governance checks are model *judgment*, not deterministic *facts*. They shouldn't hard-block on confidence alone, but "ignore and push" must not be a silent escape hatch — and the same finding shouldn't re-prompt every run once a human has resolved it.

**Solution**: Append-only JSONL **resolution logs**. Each governance gate triages a finding against prior resolutions and records a verdict, so a resolved finding stays resolved until its inputs change.

```
knowledge-base/principle-resolutions.jsonl      ← G2 (principles.py)
knowledge-base/contradiction-resolutions.jsonl  ← G3 (contradictions.py)
knowledge-base/drift-resolutions.jsonl          ← P4b (drift.py)
```

One shared core (`resolution_log.py`) provides `append` / `load` / `active`, keyed by a caller-supplied tuple; verdicts include *refuted*, *amended*, *superseded*. A straight code fix is **not** logged — git already records it.

**Used by**: spec-manager governance gates (G2/G3/P4b), driven from wrap-up Phase 3.5

**When to use**: For checks that need human judgment to clear, where you want an auditable, non-repeating record instead of a hard block.
