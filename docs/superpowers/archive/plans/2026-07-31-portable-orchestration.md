# Portable Orchestration Implementation Plan (Phase 4)

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make the three LLM fan-out flows run correctly on any agent — parallel where subagents exist, sequential where they don't — without changing what the workers actually do.

**Architecture:** Separate the *unit of work* from the *scheduling*. Each flow already produces N independent worker tasks; the fix is to stop issuing `spawn … in parallel` as an unconditional imperative and instead state that the N tasks are independent, that parallel is the default where supported, and what the fallback is. A new conformance rule (R9) makes the portability clause mandatory wherever fan-out language appears, so it cannot regress.

**Tech Stack:** Markdown (three `SKILL.md` files) plus one new rule in the existing stdlib-Python checker.

## Context

This is **Phase 4 of 6** ([`docs/design/portability/01-design.md`](../../../design/portability/01-design.md) §6, §11). Branch `feat/polyglot-portability` stays open through all six phases. Phase 2 made the skill layer agent-neutral; Phase 3 renamed the skills and built the installer.

### What is actually wrong today

All three flows issue parallelism as an **unconditional imperative** with no fallback written anywhere:

| File | Line | Today |
|---|---|---|
| `freya-docs-manager` | 75 | "The coordinator spawns worker agents **IN PARALLEL** for each doc type" |
| `freya-codebase-security-scan` | 109 | "Launch the following specialized agents **in parallel**" |
| `freya-codebase-security-scan` | 575 | "Run the passes **in parallel** across findings" |
| `freya-spec-manager` | 220 | "**Spawns parallel** discovery agents for each area" |

On Claude that is fine — the Task tool does exactly this. On an agent without subagents the instruction has no defined meaning, and the agent improvises: probably sequential in one context, possibly skipping workers, possibly just narrating. **That ambiguity is the bug** — the cost question is secondary.

### Copilot cannot be commanded, only structured (verified 2026-07-31)

From <https://code.visualstudio.com/docs/copilot/agents/subagents>: subagent delegation is **agent-initiated**, "not directly invoked by users in chat" — the main agent "recognizes the part of the task that benefits from isolated context" and "decides execution strategy autonomously based on task structure." A user can only *hint*; their own documented example is `"Perform these tasks in parallel: 1. … 2. …"`. Nesting is capped at depth 5, and subagents spawning subagents is off by default. `copilot --help` on 1.0.75 confirms the CLI exposes `--agent` but no parallel-orchestration flag.

**Consequence for this phase:** on Claude, "run these in parallel" is a directive; on Copilot it is a hint. The lever that actually works on Copilot is *task structure* — N visibly independent, self-contained units. That is the same restructuring portability needs anyway, so the portable phrasing is not a compromise; on Copilot it is the only thing that works.

> **DECISION (project owner, 2026-07-31): parallel stays the default.** This is also the no-behaviour-change option for existing Claude users — the port makes the *fallback* explicit rather than leaving it undefined.

### Not in this phase

- **Phase 4b — the `audit` driver.** `codebase-security-scan audit` runs on Claude's Workflow tool and is ported separately by re-hosting the engine as a Python driver with a headless agent adapter (design §6.1). The four "Workflow tool" references and two `${CLAUDE_PLUGIN_ROOT}` lines in `freya-codebase-security-scan/SKILL.md` stay exactly as they are, and the checker's `AUDIT_WORKFLOW_MARKER` exemption and `AGENT_TOOL_NAMES` omission stay in place.
- Changing *what* any worker does, *which* workers exist, or the doc/spec/finding formats they produce. This phase is scheduling only.

## Global Constraints

- **The canonical scheduling block below is copied verbatim** into every flow. Only the italicised lead-in sentence varies per skill. Do not paraphrase the two shared paragraphs — R9 anchors on an exact sentinel phrase.
- **The sentinel is the literal string `if your agent supports subagents`.** R9 requires it in any `SKILL.md` containing fan-out language.
- **Scheduling only.** Do not add, remove, reorder, or reword worker tasks; do not change what a worker analyses, returns, or writes.
- **Do not touch the `audit` mode**, the four "Workflow tool" references, or the two `${CLAUDE_PLUGIN_ROOT}` lines in `freya-codebase-security-scan/SKILL.md`.
- **Two names, one character apart:** `freya <command>` (space) is the CLI; `freya-<skill>` (hyphen) is a skill name.
- Python 3 **stdlib only**; **never bare `python`** — use `python3`. Tests colocated, `unittest`, output pristine.
- **Do not modify** `docs/design/`, `docs/explanations/`, `docs/migrations/`, `docs/superpowers/plans/`, `.claude-plugin/`, or `workflows/`.
- **Commit locally after each task. Do NOT push.**
- Commit messages end with:
  `Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>`

## The canonical scheduling block

Two paragraphs, **verbatim**, preceded by one skill-specific lead-in sentence.

````markdown
*<lead-in: states how many tasks, that they are independent, and what each one emits>*

Run them **in parallel — the default** — if your agent supports subagents (Claude
Code, Cursor, Codex and OpenCode all do; Copilot delegates on its own when the
tasks are visibly independent). If it does not, run them one at a time: the
result is identical, only slower.

Parallel fan-out costs roughly 7× the tokens of a sequential pass, because each
subagent carries its own context window. Ask for a sequential run when spend
matters more than wall-clock.
````

The lead-in differs because the flows differ in what a worker emits, and that is what makes a sequential run safe from context accumulation:

| Skill | Lead-in |
|---|---|
| `freya-docs-manager` | *These N documentation tasks are independent — none reads another's output, and each writes its own file before the next begins.* |
| `freya-spec-manager` | *These five discovery tasks are independent — none reads another's output, and each writes its specs before the next begins.* |
| `freya-codebase-security-scan` (scanners) | *These six category scans are independent — none reads another's output, and each returns a compact list of candidate findings rather than file contents.* |
| `freya-codebase-security-scan` (refutation) | *The refutation passes are independent of each other and of every other finding's passes; each returns a one-line verdict.* |

Do not claim a worker "writes its output before the next begins" where it does not. The security scanners **return** findings to the coordinator for aggregation in Step 4 — that is why their lead-in says so instead.

## File Structure

| File | Responsibility |
|---|---|
| `bin/check_skill_conformance.py` | **Modify.** Add R9: fan-out language requires the sentinel. |
| `bin/test_check_skill_conformance.py` | **Modify.** Tests for R9. |
| `skills/freya-docs-manager/SKILL.md` | **Modify.** 10 sites. |
| `skills/freya-spec-manager/SKILL.md` | **Modify.** 5 sites. |
| `skills/freya-codebase-security-scan/SKILL.md` | **Modify.** 8 sites, two flows. |

---

### Task 1: R9 — fan-out language requires the portability clause

Written first so Tasks 2–4 have an objective finish line. R9 starts **red** on all three files and is driven green by them.

**Files:**
- Modify: `bin/check_skill_conformance.py`
- Test: `bin/test_check_skill_conformance.py`

**Interfaces:**
- Consumes: the existing `check_file(path, rel, allowed)` and `RULES`.
- Produces: rule `R9`, plus module-level `FANOUT` and `SUBAGENT_SENTINEL`.

R9 is a **file-level** rule, unlike R1–R8 which are per-occurrence: a single sentinel anywhere in the file satisfies every fan-out mention in it. It reports at the first fan-out line so the message points somewhere useful.

- [ ] **Step 1: Write the failing tests**

Add to `bin/test_check_skill_conformance.py`:

```python
class FanoutTest(unittest.TestCase):
    """R9: a skill that fans out must say what to do without subagents."""

    SENTINEL = (
        "Run them in parallel if your agent supports subagents; otherwise "
        "run them one at a time.\n"
    )

    def _skill(self, body):
        return "---\nname: demo\ndescription: d\n---\n\n" + body

    def test_unconditional_parallel_imperative_is_flagged(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = build_root(tmp, skill_md=self._skill(
                "The coordinator spawns worker agents IN PARALLEL for each doc type.\n"))
            self.assertIn("R9", rules_hit(root))

    def test_sentinel_satisfies_the_whole_file(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = build_root(tmp, skill_md=self._skill(
                "Spawn discovery agents for each area.\n"
                "Launch the following specialized agents in parallel.\n" + self.SENTINEL))
            self.assertNotIn("R9", rules_hit(root))

    def test_flagged_once_per_file_not_per_mention(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = build_root(tmp, skill_md=self._skill(
                "Spawn worker agents.\nLaunch parallel agents.\nRun them in parallel.\n"))
            self.assertEqual(rules_hit(root).count("R9"), 1)

    def test_descriptive_parallel_mention_is_flagged(self):
        """`description:` advertising parallel subagents is a portability claim too."""
        with tempfile.TemporaryDirectory() as tmp:
            root = build_root(
                tmp,
                skill_md="---\nname: demo\ndescription: Audits a codebase using parallel subagents.\n---\n",
            )
            self.assertIn("R9", rules_hit(root))

    def test_unrelated_fanout_word_is_not_flagged(self):
        """wrap-up says 're-inference fan-out'; spec-manager says 'dispatch key'."""
        with tempfile.TemporaryDirectory() as tmp:
            root = build_root(tmp, skill_md=self._skill(
                "A change never triggers an unbounded re-inference fan-out.\n"
                "A typo in the runner's dispatch key fails loud.\n"))
            self.assertNotIn("R9", rules_hit(root))

    def test_literal_spawn_regex_in_a_code_block_is_not_flagged(self):
        """security-scan documents `spawn\\(` as a detection pattern, not an instruction."""
        with tempfile.TemporaryDirectory() as tmp:
            root = build_root(tmp, skill_md=self._skill(
                "Detection pattern:\n```\nspawn\\([^)]*\\+\n```\n"))
            self.assertNotIn("R9", rules_hit(root))

    def test_reference_file_is_not_checked(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = build_root(tmp, reference_md="Spawn worker agents in parallel.\n")
            self.assertNotIn("R9", rules_hit(root))
```

- [ ] **Step 2: Run to verify they fail**

Run: `cd bin && python3 -m unittest test_check_skill_conformance -v`
Expected: FAIL — the four `assertIn("R9", …)` / count tests fail because no rule R9 exists.

- [ ] **Step 3: Implement**

In `bin/check_skill_conformance.py`, add beside the other patterns:

```python
#: A fan-out instruction: telling the agent to run N workers, or advertising that
#: the skill does. Deliberately narrow — it must not match `re-inference fan-out`,
#: a `dispatch key`, or the literal `spawn\(` regex the security scanner documents
#: as a detection pattern.
FANOUT = re.compile(
    r"\b(spawn|launch|dispatch)\w*\s+(the\s+|these\s+|\d+\s+|one\s+)?"
    r"(parallel\s+|specialized\s+|following\s+)*"
    r"(worker|discovery|coordinator|security|area)?\s*(agent|subagent|worker)s?\b"
    r"|\bin parallel\b"
    r"|\bparallel\s+(sub)?agents?\b|\bparallel\s+workers?\b"
    r"|\bparallel\s+(discovery|security)\b",
    re.IGNORECASE,
)

#: The exact phrase that makes a fan-out portable. Skills must state the fallback
#: for agents without subagents; an unconditional "run these in parallel" has no
#: defined meaning there.
SUBAGENT_SENTINEL = "if your agent supports subagents"
```

Add to `RULES`:

```python
    "R9": "fan-out without a portability clause — say what to do when the agent "
          "has no subagents (include the phrase \"if your agent supports subagents\")",
```

In `check_file`, after the R8 block:

```python
    if path.name == "SKILL.md" and SUBAGENT_SENTINEL not in text:
        for lineno, line in enumerate(lines, 1):
            if FANOUT.search(line):
                violations.append((rel, lineno, "R9", line.strip()))
                break  # one violation per file: the sentinel fixes them all at once
```

`check_file` needs the file's full text for the sentinel check. If it currently only holds `lines`, reconstruct with `text = "\n".join(lines)` at the top of the function rather than re-reading the file.

- [ ] **Step 4: Run to verify they pass**

Run: `cd bin && python3 -m unittest test_check_skill_conformance -v`
Expected: PASS — 62 tests, `OK`, output pristine.

- [ ] **Step 5: Confirm R9 is red on exactly the three fan-out skills**

Run: `python3 bin/check_skill_conformance.py; echo "exit=$?"`

Expected — `exit=1`, and exactly three R9 lines, one per file:

```
skills/freya-codebase-security-scan/SKILL.md:4: R9: ...
skills/freya-docs-manager/SKILL.md:19: R9: ...
skills/freya-spec-manager/SKILL.md:166: R9: ...
```

No other rule may appear. If R9 fires on `freya-wrap-up` or any other skill, the pattern is too broad — fix the pattern, not the skill.

- [ ] **Step 6: Mutation-check**

1. Replace `SUBAGENT_SENTINEL` with `"parallel"` (a word that already appears in fan-out text).
   Expected: FAIL on `test_descriptive_parallel_mention_is_flagged` and
   `test_flagged_once_per_file_not_per_mention`. **Restore.**
   (Not `test_unconditional_parallel_imperative_is_flagged` — its fixture says
   "IN PARALLEL" in caps, and the sentinel check is case-sensitive, so a lowercase
   `"parallel"` sentinel still does not match that file. Verified 2026-07-31.)
2. Remove the `break` so R9 reports per line.
   Expected: FAIL on `test_flagged_once_per_file_not_per_mention`. **Restore.**
3. In `FANOUT`, add `|\bfan-?out\b` to the alternation.
   Expected: FAIL on `test_unrelated_fanout_word_is_not_flagged`. **Restore.**

Re-run after restoring all three: PASS, 62 tests.

- [ ] **Step 7: Commit**

```bash
git add bin/check_skill_conformance.py bin/test_check_skill_conformance.py
git commit -F - <<'EOF'
test(conformance): add R9 — fan-out needs a portability clause

Three skills tell the agent to spawn workers in parallel with no fallback
written anywhere. On Claude that is a directive; on an agent without subagents
it has no defined meaning and the agent improvises.

R9 is file-level: any SKILL.md containing fan-out language must also say what
to do without subagents. It is red on exactly the three fan-out skills today
and is driven green by the rest of this phase.

The pattern is deliberately narrow — verified not to match wrap-up's
"re-inference fan-out", spec-manager's "dispatch key", or the literal
`spawn\(` regex the security scanner documents as a detection pattern.

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>
EOF
```

---

### Task 2: `freya-docs-manager` — 12 documentation workers

**Files:**
- Modify: `skills/freya-docs-manager/SKILL.md` (10 fan-out sites: lines 19 ×3, 57, 61, 73, 75 ×2, 369, 447)

**Interfaces:**
- Consumes: R9 from Task 1, and the canonical block above.
- Produces: R9 green for this file.

- [ ] **Step 1: Rewrite the Phase 2 heading and imperative**

Lines 73–75 are the flow itself. Replace:

```markdown
### Phase 2: Parallel Worker Agents

The coordinator spawns worker agents IN PARALLEL for each doc type:
```

with:

```markdown
### Phase 2: Documentation Workers

The coordinator turns its plan into one self-contained task per document type:
```

Then, immediately **after** the worker list and the "Each worker receives" block, insert the canonical scheduling block with the docs-manager lead-in:

```markdown
*These documentation tasks are independent — none reads another's output, and each
writes its own file before the next begins.*

Run them **in parallel — the default** — if your agent supports subagents (Claude
Code, Cursor, Codex and OpenCode all do; Copilot delegates on its own when the
tasks are visibly independent). If it does not, run them one at a time: the
result is identical, only slower.

Parallel fan-out costs roughly 7× the tokens of a sequential pass, because each
subagent carries its own context window. Ask for a sequential run when spend
matters more than wall-clock.
```

Placing it after the worker list matters: the list *is* the "N visibly independent tasks" structure that makes Copilot choose to parallelise.

- [ ] **Step 2: Rewrite the remaining descriptive mentions**

These describe the architecture rather than instruct; make them accurate without promising a capability the host may not have.

```
line 19  (description: frontmatter)
-  ... using a **coordinator + parallel workers** architecture ... spawns specialized agents in parallel ...
+  ... using a **coordinator + workers** architecture: one coordinator plans, then one
+  self-contained task per document type, run in parallel where the agent supports it.

line 57
-## Architecture: Coordinator + Parallel Workers
+## Architecture: Coordinator + Workers

line 61
-Launch ONE coordinator agent that:
+Run ONE coordinator pass that:

line 369
-→ Coordinator asks about project purpose, spawns parallel workers, resolves placeholders, then runs review
+→ Coordinator asks about project purpose, runs the documentation workers, resolves placeholders, then runs review

line 447
-... using a coordinator + parallel workers architecture ...
+... using a coordinator + workers architecture ...
```

Read each line in place before editing — line numbers shift as you go. Keep every surrounding sentence intact.

- [ ] **Step 3: Verify**

```bash
python3 bin/check_skill_conformance.py --rule R9; echo "exit=$?"
```
Expected: two R9 violations remain (`freya-spec-manager`, `freya-codebase-security-scan`); **none** for `freya-docs-manager`.

```bash
grep -c 'if your agent supports subagents' skills/freya-docs-manager/SKILL.md
```
Expected: `1`.

```bash
grep -n 'Worker 1:\|Worker 12:' skills/freya-docs-manager/SKILL.md
```
Expected: both still present — the worker list is unchanged.

- [ ] **Step 4: Commit**

```bash
git add skills/freya-docs-manager/SKILL.md
git commit -F - <<'EOF'
refactor(docs-manager): make the worker fan-out portable

"The coordinator spawns worker agents IN PARALLEL" is a directive on Claude and
undefined anywhere else. The worker list is unchanged; what changes is that the
tasks are now presented as N independent units followed by an explicit
scheduling paragraph — parallel by default, sequential where subagents do not
exist.

Presenting the list before the scheduling note is deliberate: visible task
independence is what makes Copilot choose to delegate, since its subagent
dispatch is agent-initiated and cannot be commanded.

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>
EOF
```

---

### Task 3: `freya-spec-manager` — five discovery areas

**Files:**
- Modify: `skills/freya-spec-manager/SKILL.md` (5 fan-out sites: 166, 217, 220, 222, 328)

- [ ] **Step 1: Rewrite the `scan` coordinator and Phase 2 heading**

Lines 217–222. Replace:

```markdown
Spawn ONE coordinator agent that:
1. Scans codebase structure (Glob for key patterns)
2. Identifies feature areas: auth, api, ui, data, infra
3. Spawns parallel discovery agents for each area

**Phase 2: Parallel Discovery Agents**

Each area agent:
```

with:

```markdown
Run ONE coordinator pass that:
1. Scans codebase structure (Glob for key patterns)
2. Identifies feature areas: auth, api, ui, data, infra
3. Produces one self-contained discovery task per area

**Phase 2: Discovery Tasks**

Each area task:
```

Then insert the canonical block immediately after the **Discovery areas** list (so the five areas are visible first):

```markdown
*These five discovery tasks are independent — none reads another's output, and each
writes its specs before the next begins.*

Run them **in parallel — the default** — if your agent supports subagents (Claude
Code, Cursor, Codex and OpenCode all do; Copilot delegates on its own when the
tasks are visibly independent). If it does not, run them one at a time: the
result is identical, only slower.

Parallel fan-out costs roughly 7× the tokens of a sequential pass, because each
subagent carries its own context window. Ask for a sequential run when spend
matters more than wall-clock.
```

- [ ] **Step 2: Rewrite the two remaining mentions**

```
line 166  (bootstrap, brownfield branch)
-**Warn first** that scan over a large repo spawns discovery agents and can take a while.
+**Warn first** that scan over a large repo runs a discovery task per area and can take a while.

line 328  (update flow)
-1. Spawn discovery agents for changed areas only (not full codebase)
+1. Run discovery tasks for changed areas only (not full codebase)
```

- [ ] **Step 3: Verify**

```bash
python3 bin/check_skill_conformance.py --rule R9; echo "exit=$?"
```
Expected: one R9 violation remains (`freya-codebase-security-scan`).

```bash
grep -c 'if your agent supports subagents' skills/freya-spec-manager/SKILL.md
grep -n '\*\*Auth\*\*\|\*\*Infra\*\*' skills/freya-spec-manager/SKILL.md
```
Expected: `1`, and both discovery areas still present.

- [ ] **Step 4: Commit**

```bash
git add skills/freya-spec-manager/SKILL.md
git commit -F - <<'EOF'
refactor(spec-manager): make scan's discovery fan-out portable

The five discovery areas are unchanged; the coordinator now produces one
self-contained task per area and the scheduling is stated explicitly —
parallel by default, sequential where subagents do not exist.

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>
EOF
```

---

### Task 4: `freya-codebase-security-scan` — two flows

This skill fans out twice: the category scanners (Step 3) and the adversarial refutation passes (the verification step). Both need the treatment; they get **one** sentinel between them, since R9 is file-level.

**Files:**
- Modify: `skills/freya-codebase-security-scan/SKILL.md` (8 fan-out sites: 4, 27, 33, 107, 109 ×2, 189, 575)

**Interfaces:**
- Produces: R9 green — the phase's finish line.

- [ ] **Step 1: Rewrite the Step 3 scanner fan-out**

Lines 107–109. Replace:

```markdown
### Step 3: Spawn Parallel Security Agents

Launch the following specialized agents **in parallel** to scan different security categories:
```

with:

```markdown
### Step 3: Run the Security Category Scans

Each security category below is a self-contained scan over the same codebase:
```

Then insert the canonical block immediately **after** the last category agent block and before `### Step 4: Aggregate Findings`:

```markdown
*These category scans are independent — none reads another's output, and each returns
a compact list of candidate findings rather than file contents.*

Run them **in parallel — the default** — if your agent supports subagents (Claude
Code, Cursor, Codex and OpenCode all do; Copilot delegates on its own when the
tasks are visibly independent). If it does not, run them one at a time: the
result is identical, only slower.

Parallel fan-out costs roughly 7× the tokens of a sequential pass, because each
subagent carries its own context window. Ask for a sequential run when spend
matters more than wall-clock.
```

Note the lead-in says the scanners **return** findings — they do not write files. Step 4 aggregates them. Do not claim otherwise.

- [ ] **Step 2: Rewrite the refutation-pass scheduling**

Line 575. Replace:

```markdown
Each pass returns **REFUTED** (with a reason) or **UPHELD**. Run the passes in parallel across findings.
```

with:

```markdown
Each pass returns **REFUTED** (with a reason) or **UPHELD**. The passes are independent
of each other and of every other finding's passes, and each returns a one-line verdict —
so run them in parallel where supported, one at a time otherwise. The existing cost
guardrail below still applies.
```

The file's sentinel comes from Step 1's block, so this passage does not repeat it.

- [ ] **Step 3: Rewrite the three descriptive mentions**

```
line 4  (description: frontmatter)
-  Performs comprehensive security audit of entire codebase using parallel subagents.
+  Performs a comprehensive security audit of an entire codebase, scanning each
+  security category as an independent task (run in parallel where the agent supports it).

line 27
-This skill performs a comprehensive security audit of your entire codebase using specialized parallel ...
+This skill performs a comprehensive security audit of your entire codebase using specialized
+per-category scans ...

line 33
-3. **Parallel Scanning**: Spawn specialized agents for different security categories
+3. **Category Scanning**: One self-contained scan per security category

line 189
-1. Spawn security agents ONLY for affected files
+1. Run the category scans ONLY over affected files
```

Read line 27 in place and preserve the rest of its sentence.

- [ ] **Step 4: Confirm the audit mode is untouched**

```bash
grep -c 'Workflow tool' skills/freya-codebase-security-scan/SKILL.md
grep -c 'CLAUDE_PLUGIN_ROOT' skills/freya-codebase-security-scan/SKILL.md
```
Expected: `4` and `2` — unchanged. Phase 4b owns these.

- [ ] **Step 5: Verify the phase is complete**

```bash
python3 bin/check_skill_conformance.py; echo "exit=$?"
```
Expected: `skill layer is conformant.` and `exit=0`. **This is the phase's finish line.**

```bash
for s in freya-docs-manager freya-spec-manager freya-codebase-security-scan; do
  printf '%-32s %s\n' "$s" "$(grep -c 'if your agent supports subagents' skills/$s/SKILL.md)"
done
```
Expected: `1` for each.

```bash
grep -n 'Agent 1:\|Agent 6:' skills/freya-codebase-security-scan/SKILL.md
```
Expected: the category list is unchanged.

- [ ] **Step 6: Run every test suite**

```bash
for t in bin/test_*.py skills/*/scripts/test_*.py; do
  d=$(dirname "$t"); m=$(basename "$t" .py)
  ( cd "$d" && python3 -m unittest "$m" -q ) >/dev/null 2>&1 && echo "ok    $t" || echo "FAIL  $t"
done
```
Expected: `ok` for all 18. Nothing in this phase touches Python, so a failure is a real regression.

- [ ] **Step 7: Commit**

```bash
git add skills/freya-codebase-security-scan/SKILL.md
git commit -F - <<'EOF'
refactor(security-scan): make both fan-outs portable

Two flows fan out here — the per-category scanners and the adversarial
refutation passes. Both now present independent units and state the schedule
explicitly: parallel by default, sequential where subagents do not exist.

The scanners' lead-in says they *return* findings rather than writing files,
because Step 4 aggregates them — the sequential-safety claim has to match what
the workers actually do.

The audit mode, its four Workflow-tool references and its two
${CLAUDE_PLUGIN_ROOT} lines are untouched; Phase 4b ports that engine.

check_skill_conformance now exits 0.

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>
EOF
```

---

## Definition of done

- `python3 bin/check_skill_conformance.py` exits 0, with R9 satisfied by all three flows.
- Each of the three skills contains the sentinel exactly once.
- The worker/category/area lists are unchanged — same workers, same scopes, same outputs.
- `grep -c 'Workflow tool'` → 4 and `grep -c 'CLAUDE_PLUGIN_ROOT'` → 2 in `freya-codebase-security-scan/SKILL.md`.
- All 18 test suites pass.
- `.claude-plugin/` and `workflows/` unchanged from `main`.
- **Nothing pushed.**

## Carried forward

- **Phase 4b:** port `workflows/codebase-security-audit.js` to a Python driver plus a headless agent adapter (design §6.1, spike results §6.1.1). Removing it retires, as one unit: the four "Workflow tool" references and two `${CLAUDE_PLUGIN_ROOT}` lines in `freya-codebase-security-scan/SKILL.md`, the `AUDIT_WORKFLOW_MARKER` exemption and the `AGENT_TOOL_NAMES` omission in `bin/check_skill_conformance.py`, and `CONTRIBUTING.md`'s Workflow bullet. **Cost is the live risk:** the spike measured $0.396 for one finder worker on a *trivial* fixture, so guardrails (cheaper finder model, hard round/finding caps, an upfront estimate) are part of that design rather than an afterthought.
- **Phase 5:** `freya update` + notify-only check + `freya init`. Also: store relocation orphans install links, which `doctor` can already see but does not report.
- **Phase 6:** validate both flows on Copilot end-to-end. The open question this phase cannot answer is *behavioural*: given N visibly independent tasks, does Copilot actually delegate them in parallel, or narrate them sequentially? Its dispatch is agent-initiated, so only a real run tells us. If it declines, the fallback is correct but the 7× note is misleading on that agent.
- The `~7×` figure comes from the landscape research in `00-vision.md` §3 and has **not** been measured against this suite. Worth measuring in Phase 6 rather than continuing to quote it.
