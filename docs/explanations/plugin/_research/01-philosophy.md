# Research Brief 01 — Philosophy

**Topic:** Why the freya-devkit toolkit exists; its core beliefs, mental model, and non-goals.
**Scope:** The "why," not the "how-to." This is the backing layer for the plugin-wide explainer's philosophy section.

**Primary sources (read in full):**
- `docs/philosophy.md` — the canonical philosophy document
- `docs/README.md` — orientation / index for the `docs/` set
- `README.md` (repo root) — product framing and "how they fit together"
- `docs/patterns.md` — the concrete patterns that operationalize the beliefs

---

## 1. What freya-devkit is

freya-devkit is a **Claude Code plugin**: an integrated set of AI-assisted development skills that keep a project's dependency graph, documentation, feature specs, and security posture in sync as the code evolves. It is invoked as slash-commands namespaced under the plugin, e.g. `/freya-devkit:code-graph`, `/freya-devkit:wrap-up`.

Product-level one-liner (repo `README.md`, line 3):

> "An integrated, AI-assisted development toolkit for Claude Code. Seven skills that work together to keep your dependency graph, documentation, feature specs, and security posture in sync as you build — plus a one-command wrap-up workflow that runs them all."

The philosophy doc frames the same thing at the conceptual level (`docs/philosophy.md`, line 3):

> "The core beliefs and mental model behind this skills ecosystem."

**Note on skill count:** The docs and README describe **seven** skills; the actual `skills/` directory currently holds **ten**: `code-graph`, `docs-manager`, `spec-manager`, `codebase-security-scan`, `codebase-security-resolver`, `dependency-vulnerability-check`, `wrap-up`, plus three newer additions — `behavior-graph`, `behavior-runner`, and `status`. The philosophy/README prose predates the behavior-layer and status skills (see Gotchas).

---

## 2. Why it exists — the founding problem

The philosophy starts from a critique of the **monolithic prompt** (`docs/philosophy.md`, "Why Skills Over Monolithic Prompts"):

> "Traditional AI assistance uses one big prompt with all instructions. This approach has problems:
> - **Context bloat**: Everything loaded even when not needed
> - **Hard to maintain**: One change affects everything
> - **No modularity**: Can't mix and match capabilities"

The answer is skills that are:

> "- **Focused**: Each skill does one thing well
> - **Composable**: Skills can use other skills
> - **Progressive**: Load what you need, when you need it"

So the toolkit exists to replace one giant instruction blob with a set of small, focused, composable workflows that load progressively and can call each other.

---

## 3. The mental model — "specialized team members"

The central metaphor (`docs/philosophy.md`, "The Mental Model"):

> "Think of skills as **specialized team members** working on a codebase."

Each skill is cast as a role on a team operating over *your codebase*:

| Skill | Role (as named in philosophy.md) |
|-------|----------------------------------|
| `code-graph` | "Analyst" |
| `docs-manager` | "Writer" |
| `spec-manager` | "Architect" |
| `wrap-up` | "Integrator" |

The closing line of the section:

> "Each skill has a role, knows its job, and can collaborate with others."

The `docs/README.md` restates this as: "Skills are specialized workflows that work together to maintain a codebase."

---

## 4. Core beliefs (the five concepts)

`docs/philosophy.md` enumerates five "Core Concepts." Each is operationalized by a concrete pattern in `docs/patterns.md`.

### 4.1 Intentional Design
> "Code isn't just 'correct' or 'incorrect' - some things are **intentional**."

A security scan might flag "Missing role check on DELETE - any user can delete," but a spec may record that as a deliberate decision (e.g., "Any authenticated user can CRUD posts" with rationale "Collaborative tool with equal access"). The belief: **tools must distinguish design decisions from defects.** `spec-manager` captures intentional decisions so `codebase-security-scan` doesn't flag them. (Pattern: "Intentional Design Tracking" and "Validation Against Specs," `docs/patterns.md`.)

### 4.2 Certainty Scoring
> "When AI generates documentation or specs, it doesn't always know it's right."

AI-generated content carries a **0–100 confidence score**. The philosophy table:

| Score | Meaning | Action |
|-------|---------|--------|
| 90-100 | High confidence | Trust it |
| 70-89 | Good confidence | Quick review |
| 50-69 | Medium confidence | Ask user |
| 0-49 | Low confidence | Detailed review |

(`docs/patterns.md` gives a near-identical table but phrases the top action as "Accept automatically" and the bottom as "Needs detailed review," and lists certainty-increasing factors — code comments, matching docs, clear patterns, tests present — vs. decreasing factors — no comments, ambiguous code, multiple interpretations, no tests.) Belief: **acknowledge AI uncertainty rather than hide it.** Used by `spec-manager`.

### 4.3 Impact Awareness
> "When code changes, what else is affected?"

`code-graph` tracks import relationships (A imports B; B imported by C, D, E) so a change to A propagates a check through B and its dependents. Belief: **an update is about *affected* files, not just *changed* files** — the "blast radius." This is why `code-graph` is the foundation the other skills query.

### 4.4 Incremental Over Full
> "Don't re-scan everything every time."

Distinguishes **full scan** (initial setup / complete refresh) from **incremental** (after code changes, process only the diff). State is remembered in tracking files — the doc names `.spec-last-update` and `.security-last-scan`. Belief stated plainly: "This makes skills fast enough to run frequently." (Pattern: "Incremental Updates" and "Git-Aware State," `docs/patterns.md`.)

### 4.5 Separation of Concerns
> "Code changes are different from generated artifacts."

The **two-commit pattern**: commit 1 = code (e.g. `src/lib/auth.ts`, `src/api/routes.ts`); commit 2 = generated artifacts (e.g. `knowledge-base/reference/API.md`, `knowledge-base/specs/auth/SPEC-001.md`, security reports). Belief: "keeps git history clean and lets tools reference stable commits." (Pattern: "Two-Commit Separation," `docs/patterns.md`.)

---

## 5. How the beliefs compose (dependency / data flow)

The composition model appears in both `docs/README.md` and repo `README.md`. The foundation stack (`docs/philosophy.md` implicitly, `docs/README.md` explicitly):

```
code-graph (foundation)
    ↓
docs-manager, spec-manager (use code-graph for impact analysis)
    ↓
codebase-security-scan (uses code-graph + spec-manager)
    ↓
wrap-up (orchestrates everything)
```

Key composition beliefs (repo `README.md`, "How they fit together"):
- **"code-graph is the keystone."** Doc, spec, and security skills query it for blast radius and **degrade gracefully to plain `git diff` when it's unavailable.**
- **"specs are the false-positive filter."** The security scan reads specs and marks spec'd behavior as *intentional design* rather than a vulnerability.
- **"incremental by default."** Each skill tracks the last processed commit and only reprocesses what changed.

### "What This Enables" (three payoffs, from `docs/philosophy.md`)
1. **For Development:** implement a feature → run `/freya-devkit:wrap-up` → get updated docs, specs, security scan, all committed.
2. **For Understanding:** a new AI session reads `knowledge-base/reference/` for context and `knowledge-base/specs/` for intentional design decisions — "full understanding without being told everything."
3. **For Maintenance:** security scan finds potential issues → cross-references specs for intentional design → reports only real vulnerabilities → tracks finding lifecycle across scans.

---

## 6. Degradation behavior (a first-class belief)

Graceful degradation is a named pattern — "Fallback Without Dependencies" (`docs/patterns.md`):

> "Skills might be used in isolation without their optional dependencies. Check if dependency exists, fall back gracefully if not."

Concretely: if `code-graph` is available, a skill uses its `impact` output as the blast radius; otherwise it falls back to processing **only directly changed files** (a plain `git diff`) and warns the user about reduced coverage. The philosophy is that optional composition improves results but is never a hard requirement.

---

## 7. What it is NOT (non-goals)

The philosophy is emphatic that the toolkit is guidance, not law (`docs/philosophy.md`, "What This Doesn't Mean"):

> "- **Not prescriptive**: Skills don't have to follow every pattern
> - **Not complete**: The ecosystem grows over time
> - **Not perfect**: Certainty scores acknowledge uncertainty
> - **Not enforced**: Conventions guide, they don't restrict"

Closing thesis:

> "The goal is coherence and collaboration, not rigid compliance."

`docs/README.md` echoes this ("Integration Philosophy"):

> "Skills don't have to follow these patterns, but understanding them helps create skills that fit naturally into the ecosystem. The goal is coherence, not enforcement."

And `docs/patterns.md` opens: "These are conventions, not requirements - use them when they fit."

---

## 8. Verbatim quotable lines (high-value pull quotes)

- "The core beliefs and mental model behind this skills ecosystem." — `docs/philosophy.md`
- "Think of skills as **specialized team members** working on a codebase." — `docs/philosophy.md`
- "Each skill has a role, knows its job, and can collaborate with others." — `docs/philosophy.md`
- "Code isn't just 'correct' or 'incorrect' - some things are **intentional**." — `docs/philosophy.md`
- "This acknowledges AI uncertainty rather than hiding it." — `docs/philosophy.md`
- "A documentation update isn't just about changed files - it's about affected files." — `docs/philosophy.md`
- "The goal is coherence and collaboration, not rigid compliance." — `docs/philosophy.md`
- "The goal is coherence, not enforcement." — `docs/README.md`
- "code-graph is the keystone." — repo `README.md`
- "specs are the false-positive filter." — repo `README.md`
- "These are conventions, not requirements - use them when they fit." — `docs/patterns.md`

---

## 9. Gotchas / accuracy caveats

- **Doc drift on skill count and roster.** `docs/philosophy.md` and both READMEs describe a **seven-skill** ecosystem and a four-member team diagram (code-graph/docs-manager/spec-manager/wrap-up). The live `skills/` directory contains **ten** skills, adding `behavior-graph`, `behavior-runner`, and `status`. The philosophy doc does **not** mention the behavior layer or the status skill. Treat the "specialized team members" roster as illustrative, not exhaustive.
- **Path naming drift.** Philosophy/patterns examples show artifacts under `knowledge-base/...` (e.g. `knowledge-base/specs/`, `knowledge-base/reference/`). Some older philosophy examples and the security-scan reference also mention `/knowledge-base/specs/`. UNVERIFIED here whether every skill currently writes to `knowledge-base/` vs `docs/` — not checked in this brief (out of scope; verify against individual SKILL.md files if the explainer asserts exact paths).
- **Tracking-file names are illustrative.** `.spec-last-update` and `.security-last-scan` are named in the docs as examples of the incremental-state mechanism; the graph stores its commit inside `graph.json` (field), not a dotfile. Confirm exact filenames from each skill before quoting them as literal.
- **Certainty-score action labels differ between docs.** `philosophy.md` says top-band action = "Trust it" / bottom = "Detailed review"; `patterns.md` says "Accept automatically" / "Needs detailed review." Same bands, slightly different wording — quote the source you cite.
- **The five concepts are beliefs, not enforced mechanisms.** Per the "Not enforced" non-goal, nothing in the plugin *forces* a skill to score certainty, do impact analysis, or split commits. These are conventions the shipped skills happen to follow.
- **Sanitization:** All examples in this brief are generic (`src/lib/auth.ts`, "CRUD posts"). No proprietary/business content was present in the read sources.
