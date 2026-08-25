# Developer Guide

Two things in one file: the local loop for working on freya-devkit itself — run the suite,
run the conformance gate, isolate a test that reads machine state — and the integration
conventions a new skill has to follow to fit the rest of the suite.

[CONTRIBUTING.md](../../CONTRIBUTING.md) is the companion and is not duplicated here. It
covers the plugin development loop, live agent validation under a redirected `HOME`, the CI
matrix and what a green tick does *not* prove, and the two release paths. This file covers
what you run on your own machine and what a skill must look like.

Most of what follows is prose you are asked to follow. Some of it a script enforces; those
carry a rule id (`R3`, `R8`, `R9`, …) and cannot be got wrong quietly, because
`bin/check_skill_conformance.py` exits non-zero and CI runs it. Where a convention is
unenforceable — the "Artifacts, not commits" paragraph is the clearest case — it says so.

## Working on the toolkit

**Prerequisites: CPython 3.9 or newer, and nothing else.** The runtime is pure standard
library — every import across `bin/` and `skills/*/scripts/` is either stdlib or a sibling
module in this repo. The floor is a hard one and what you may write against it is
[STYLE_GUIDE.md § Target CPython 3.9](STYLE_GUIDE.md#target-cpython-39).

```bash
git clone <fork> && cd freya-devkit
./install.sh --agent claude      # or --agent copilot; --dry-run prints the plan
bin/freya doctor
```

`freya doctor` is the first thing to run when an install looks wrong: it reports the suite
root, the manifest size, missing scripts, the interpreter version, whether `freya` resolves on
`PATH`, which agents the suite is installed for and in which mode (link or copy), orphaned
entries, whether `freya update` can run, and whether
a Claude marketplace install and a personal install are both present and shadowing each other
(`bin/freya_cli.py:288`).

### Running the tests

The suite is stdlib `unittest`, living beside the code it covers (`bin/test_*.py`,
`skills/*/scripts/test_*.py`):

```bash
python3 -m pytest bin/ skills/ -q
```

Run it **from the repository root**, and sandbox `FREYA_HOME` in any test class that reads
machine state — see
[TESTING.md § FREYA_HOME sandboxing in `setUp`](TESTING.md#freya_home-sandboxing-in-setup) for
the rule and
[TESTING.md § What the suite is, measured](TESTING.md#what-the-suite-is-measured) for the
current count and the per-area breakdown.

pytest is the only thing ever installed; everything under test is stdlib-only and stays that
way. `python3 -m unittest discover -s bin -p 'test_*.py'` works per directory if you would
rather not install a runner — but `unittest` does not read `conftest.py` at all, so on that
path the per-test sandbox is the only protection there is.

### The conformance gate

```bash
python3 bin/check_skill_conformance.py     # must exit 0
```

Not redundant with pytest, but not independent of it either: `ShippedTreeTest`
(`bin/test_check_skill_conformance.py:919`) runs this same scan over this checkout and asserts
zero violations, so a violation injected into a shipped `SKILL.md` fails the suite too —
measured 2026-08-24 on a full tree copy, with a `${CLAUDE_PLUGIN_ROOT}` line appended to
`skills/freya-wrap-up/SKILL.md`: `1 failed, 2088 passed`, and the standalone gate exits 1 on the
same input. What the script adds is the readable report and the two flags below, and CI runs it
as its own step so neither signal hides the other. Run both before you commit.

It walks every `*.md` and `*.py` under `skills/` and nothing else — `bin/`, `knowledge-base/`
and the repo root are out of scope (`bin/check_skill_conformance.py:491`); 23 markdown and 56
Python files on 2026-08-24. Output is one `path:line: RULE: excerpt` per violation on stdout, a
per-rule count on stderr, exit 1; a `bin/commands.json` it cannot read is exit 2
(`bin/check_skill_conformance.py:520`).

**Fourteen rules**, each with its one-line rationale at `bin/check_skill_conformance.py:29`. The
ones most often tripped:

| Rule | What it rejects |
|---|---|
| R1 | `${CLAUDE_PLUGIN_ROOT}` and the bare `$CLAUDE_PLUGIN_ROOT` — use a `freya <command>` invocation |
| R2 | `/freya-devkit:` — use the prefixed skill name `freya-<skill>` |
| R3 | a `freya <command>` with no entry in `bin/commands.json` |
| R4 | agent-specific tool names, including backticked and `Workflow-powered` forms |
| R5, R10, R11, R12 | frontmatter outside the Agent Skills spec: unknown keys; values over the length limits (`description` 1024, `compatibility` 500, `name` 64 — `bin/check_skill_conformance.py:60`); a missing `description`; a `name` outside the grammar |
| R8 | a `name:` that does not equal the parent directory name |
| R9 | a fan-out with no portability clause |
| R13 | `~/.claude`, `.claude/`, `.claude-plugin`, `CLAUDE_*` env vars |
| R14 | a SKILL.md that sends a worker at secret-bearing material without stating the redaction rule — the sentinel *and* a placeholder (`[REDACTED]`, `<redacted …>`) — and without restating it in a copied-source slot (`bin/check_skill_conformance.py:50`) |

**R14 is the odd one and knowing why saves an argument.** R1–R13 are agent-neutrality rules:
they exist so a skill written on one host loads and works on another. R14 is a *secrets* rule
and has nothing to do with portability — it landed with SEC-009 because prose elsewhere in the
file was being accepted as the rule being in force. It is `SKILL.md`-only, deliberately: widening
it to every markdown file under `skills/` trips `references/templates.md` on 18 lines of fenced
scaffolding that instructs nobody, and a rule that cries wolf gets switched off
(`bin/check_skill_conformance.py:436`). It is also a presence check, so it pins the copied-source
slot rather than the whole file — [TESTING.md § The conformance
gate](TESTING.md#the-conformance-gate) has what it measurably does and does not catch. Anywhere a
comment or a doc still spells the gate `R1–R13`, that is now wrong by one and wrong in kind.

Two flags help while iterating: `--rule R9` (repeatable) narrows the report to one rule, and
`--root PATH` points the scan at another checkout.

### There is no linter

Checked, because the `# noqa: E402` markers scattered through `bin/` imply one: the tree
contains no `pyproject.toml`, `setup.cfg`, `.flake8`, `ruff.toml`, `tox.ini`, `pytest.ini` or
`.editorconfig`. The `test` job in [`.github/workflows/ci.yml`](../../.github/workflows/ci.yml)
installs pytest and then runs two checks — the suite and the conformance gate — and there is
no lint or format step anywhere in the workflow. Match the surrounding file's style by eye;
nothing will tell you if you don't.

[TODO: Are the `# noqa` markers vestigial, or is flake8 expected to be run by hand? If a
formatter is wanted, that is a decision worth an ADR before someone reformats the tree.]

### Citations in this tree are parsed, not decorative

`freya docs-graph` reads the markdown under `docs/` and `knowledge-base/` — this tree — and
turns every `path:line` token and relative markdown link into a doc-section → code edge
(`skills/freya-docs-manager/scripts/docs_graph.py:199`,
`skills/freya-docs-manager/scripts/docs_graph.py:337`). Only paths naming a file that is
actually in the code graph become edges, and a bare filename is resolved only when exactly one
file carries it (`skills/freya-docs-manager/scripts/docs_graph.py:214`). So a citation you
invent resolves to nothing and is silently dropped, and a citation you get right is what makes
a later code change point back at the paragraph that needs rewriting. Cite the file you
actually opened.

## SKILL.md Structure

While the official skill-development guide covers general structure, here are ecosystem-specific conventions:

### Frontmatter: Integration Declarations

```yaml
---
name: freya-my-skill
description: |
  Clear description of what this skill does.

  TRIGGER when: user says "X", "Y", "Z" or mentions specific keywords.

  INTEGRATION: Uses freya-other-skill (when available) for purpose.
  Used by: freya-wrapper-skill for orchestration.
---
```

The `INTEGRATION` and `Used by` lines help an agent understand relationships. They are a
convention rather than a requirement, and an uneven one: measured on the shipped tree, three of
the ten skills carry `INTEGRATION:` and one carries `Used by:`.

The cross-reference form is not optional: `freya-<skill>`, no leading slash and no
`/freya-devkit:` namespace. A slash form is a Claude Code invocation and does not
resolve on a portable install; the namespaced form is Claude's alone. See
[CONTRIBUTING.md](../../CONTRIBUTING.md) — "Cross-references use the prefixed skill
name". `name:` must also equal the skill's directory name, so a skill in
`skills/freya-my-skill/` declares `name: freya-my-skill`
(`bin/check_skill_conformance.py` rule R8).

## Invoking Bundled Scripts

A SKILL.md never spells out a path to its own scripts. It calls the launcher:

```markdown
Build the graph:

    freya code-graph --build --dir <project>
```

`freya` self-locates from its own `__file__`, resolves the command through
`bin/commands.json`, and runs the target with `sys.executable` — so no `python` needs
to be on `PATH` and no agent-specific path variable is involved. Register any new
`__main__`-bearing script under `skills/*/scripts/` in `bin/commands.json` or it is
unreachable through `freya` (rule R3 flags a `freya <command>` with no manifest entry;
`bin/test_freya_cli.py` fails if a script has no entry at all).

Mind the one-character distinction: `freya <command>` (space) is the CLI;
`freya-<skill>` (hyphen) is a skill name. They are never interchangeable.

### How the launcher resolves a command

Worth knowing in full, because every portability property the skill layer has rests on it.
All of it is in `bin/freya` and `bin/freya_cli.py`:

1. **`bin/freya` is the only file from this tree that lands on `PATH`** — on Windows the
   installer writes a generated `freya.cmd` beside it, because an extensionless file is not
   runnable there (`bin/installer.py:747`). It is deliberately thin — it checks
   the Python floor, then puts its own directory on `sys.path` using `os.path.realpath`, not
   `abspath` (`bin/freya:25`). Under `-P` / `PYTHONSAFEPATH` CPython does not auto-insert a
   resolved `sys.path[0]`, so `abspath` would point at the symlink's own directory and the
   import would fail.
2. **The store is found from `__file__`, not from an environment variable.**
   `suite_root()` is `Path(__file__).resolve().parents[1]` (`bin/freya_cli.py:31`). `.resolve()`
   follows symlinks, so a skill directory linked into an agent's skills folder still resolves
   back to the checkout where its sibling scripts live. This is why no agent-specific path
   variable appears anywhere.
3. **Built-ins are dispatched before the manifest is consulted** — `help`, `doctor`, `init`,
   `update`, `install`, `uninstall` (`bin/freya_cli.py:27`). A manifest entry colliding with one
   of those names would be unreachable while `freya help` still advertised it under Commands,
   so a test asserts the two sets stay disjoint (`bin/test_freya_cli.py:641`).
4. **Everything else is looked up in `bin/commands.json`** and joined onto `<root>/skills/`
   (`bin/freya_cli.py:128`) — 17 entries, counted 2026-08-24, all kebab-case. The manifest is validated on
   load rather than at the point of use: it must be a JSON object of string values, and each
   value must name a path *under* `skills/`. A POSIX-absolute path, a Windows drive or root,
   and a `..` in either spelling are all rejected, judged with both path flavours on every host
   (`bin/freya_cli.py:56`, `bin/freya_cli.py:98`). It is repo-owned data, so this is a guard
   rather than a fix, but the entry is joined onto the store and then executed.
5. **The target runs under `sys.executable`**, never a bare `python` — which frequently is not
   on modern systems (`bin/freya_cli.py:139`) — with the script's own directory prepended to the
   child's `PYTHONPATH`, restoring the `sys.path` entry that `-P` / isolated mode removes
   (`bin/freya_cli.py:148`).

Exit codes: the child's own code is propagated unchanged, except that a signal-terminated
child (`-N` from `subprocess.call`) is reported as `128+N` rather than masked to `256-N`. An
unknown command is 2. A registered-but-missing script is also 2, but with a message naming
`freya doctor` instead of CPython's "can't open file" (`bin/freya_cli.py:168`).

Three tests hold the manifest to its seams, and between them they are why a stale instruction
in a SKILL.md fails in CI rather than in front of a user: every entry must point at a file
that exists; every `skills/*/scripts/*.py` carrying a `__main__` block must have an entry
(`bin/test_freya_cli.py:41`, `bin/test_freya_cli.py:51`); and every `freya <command>` that any
`SKILL.md` or the root `README.md` prescribes must resolve to a real command
(`bin/test_freya_cli.py:638`).

## The shapes a new skill follows

The general forms — incremental updates keyed on a tracking dotfile, graceful fallback when
`freya-code-graph` is absent, cross-referencing specs before reporting a finding, the
coordinator + independent-tasks fan-out — are in [patterns.md](../patterns.md) and are not
restated here. The one repo-specific convention worth naming: a skill's tracking dotfile lives
under its own output directory, as `knowledge-base/<skill-output-dir>/.<skill>-last-<action>`.

What *is* specific to this repo is the obligation that comes with a code-graph answer.

**Check whether the answer is complete.** Availability is not the only way an answer can be
narrower than the question. `build`, `update`, `query` and `impact` may carry an
`unmapped_source` block naming the in-scope source files the backend could not parse, and the
directories to search instead; `dependents`/`dependencies` say the same on stderr. It is absent
whenever there is nothing to say, so its **presence** means the blast radius you just received
was computed over an incomplete graph.

```markdown
**If the answer carries `unmapped_source`:**
- Proceed — it is never a refusal, and the answer it qualifies is still correct as far as it goes
- Search the named directories directly (grep/glob) before concluding a change is contained
- Say so in whatever you report, rather than presenting the narrow answer as the whole one
```

It is patterns.md's graceful-fallback rule one level finer: a confidently empty answer is the
dangerous failure, and "3 dependents" and "3 dependents, and a fifth of this repo is unread" are
different claims. See ADR-029.

### If your skill spawns a binary, or asks whether a path is contained

Two obligations, and both are "import the one body, do not write a second". They exist because
each was a HIGH finding on this repository before it was a convention.

**Never put a bare program name in argv[0].** `skills/freya-code-graph/scripts/exec_path.py:84`
answers where a program is, as a `Resolution` carrying either an absolute path or a printable
reason. It refuses a result that is not already absolute, and — when you pass the project being
analysed — one that resolves inside it. Do not "fix" a refusal by calling `abspath()`: on
Windows `CreateProcess` searches the parent process's working directory before `PATH`, and the
working directory under documented usage *is* the repository you were pointed at, so
absolutising the hit hands the OS a fully-qualified path to the attacker's binary. `INV-2`
(`bin/check_invariants.py`) catches the literal bare-name case and CI runs it, but it reads
argv[0] at the call site: build the argv in a helper and the rule cannot see it, which is why
`audit_adapter._guard` re-checks at runtime and `Argv0Test` pins that.

**Never write a second body of a containment rule.**
`skills/freya-code-graph/scripts/containment.py` has four predicates and the module docstring
tells you which question each answers; pick by the question, not by the shape of your argument.
The one duplicate in the tree, `bin/freya_cli.py:56`, exists because the launcher must be able to
diagnose a broken skill tree and therefore cannot import from one, and it is held to parity by a
test rather than by intent.

Both modules live under `skills/freya-code-graph/scripts/` and are imported by the `parents[2]`
sibling pattern, never from `bin/` — [ADR-030](../decisions/ADR-030-shared-primitives-live-in-a-skill.md)
measured why, against a real `--copy` install. If your skill can be reached on a damaged store —
`doctor`, `update`, or a security driver that a `--copy` install may have landed without
`freya-code-graph` — guard the import and **refuse**, with a message naming the missing file.
There is no fallback to a bare name: a damaged tree is exactly when "just search `PATH`" looks
like graceful degradation (`bin/updater.py:53`).

## Where a new skill's output goes

Under `knowledge-base/`, in the subdirectory the skill owns.
[ARCHITECTURE.md § Output Artifacts](ARCHITECTURE.md#output-artifacts) is the per-path
breakdown, with the reasoning and which lines are tracked. Dated reports go to
`knowledge-base/<type>/<YYYY-MM-DD>.md` and overwrite within the day; git is the history.

Two skills ship an `evals/evals.json` — `freya-docs-manager` and `freya-spec-manager` — and
**nothing in this repository executes them**, verified by grep across `bin/`, `.github/`,
`.claude-plugin/` and the skill bodies. Both also predate the `docs/` → `knowledge-base/` move
and assert outcomes like "Creates docs/ directory", so they cannot be run as written. Adding one
buys no automated coverage; the gates that run are pytest and `check_skill_conformance.py`.

## Artifacts, Not Commits

A skill **writes** its artifacts and stops. Staging and committing them is
`freya-wrap-up`'s job and nobody else's — that separation is what makes the
[two-commit pattern](../patterns.md#pattern-two-commit-separation) hold.

Say so explicitly in the skill body. Re-measured 2026-08-24: **five** `SKILL.md` files carry an
"Artifacts, not commits" heading — `freya-behavior-graph`, `freya-dependency-vulnerability-check`,
`freya-docs-manager`, `freya-spec-manager` and `freya-status` — and
`freya-codebase-security-scan` says the same thing inline at its report step ("Write the report.
Do not commit it."). This page previously said four, and singled out `freya-status` as the one
still owing a paragraph; `freya-status` has carried it since `2deb4ef`. The skill that writes an
artifact and carries no such statement is **`freya-code-graph`**, which writes the whole of
`knowledge-base/.graph/`.

The reason is empirical: phase-6 validation watched an agent with broad tool permissions infer a
`git commit` that no skill had asked for **and push a malformed message into the history of a
repository it had only been asked to scan**
(`skills/freya-codebase-security-scan/SKILL.md:826`). An agent will fill in the step you left
implicit, so leave none. No conformance rule can check this — prose is the only lever a skill
has — which is why it is a checklist item below rather than something the gate catches for you.

## Creating New Skills

When creating a skill for this ecosystem:

1. **Check existing skills** - Can you extend an existing one?
2. **Consider integration** - Would this benefit from freya-code-graph? freya-spec-manager?
3. **Follow patterns** - Coordinator+workers? Incremental updates?
4. **Document integration** - Add INTEGRATION section to frontmatter
5. **Provide fallbacks** - What happens if dependencies are missing?
6. **Place artifacts correctly** - Follow the knowledge-base/ structure
7. **Stay agent-neutral** - `python3 bin/check_skill_conformance.py` must exit 0
8. **Register and test any script** - a `__main__`-bearing script under
   `skills/<skill>/scripts/` needs a `bin/commands.json` entry and a `test_*.py` beside it;
   if it reads settings or builds a graph, its test class sandboxes `FREYA_HOME`

## Integration Checklist

Before considering a skill complete for this ecosystem:

- [ ] Frontmatter includes TRIGGER phrases
- [ ] `name:` equals the directory name, and both carry the `freya-` prefix
- [ ] INTEGRATION section documents dependencies
- [ ] Fallback behavior described if dependencies missing
- [ ] Artifacts placed in appropriate knowledge-base/ subdirectory
- [ ] **The skill writes artifacts and does not stage or commit them — and says so**
- [ ] Tracking file convention followed (if incremental)
- [ ] Help command included
- [ ] Cross-references to related skills where appropriate, as `freya-<skill>`
- [ ] Any fan-out carries the scheduling clause (see [CONTRIBUTING.md](../../CONTRIBUTING.md))
- [ ] Every bundled script has a `bin/commands.json` entry and a `test_*.py` beside it
- [ ] Any test class that reads settings or builds a graph sandboxes `FREYA_HOME` in `setUp`
- [ ] Any subprocess names its program by an absolute path from `exec_path.resolve`, or the
      site is added to `KNOWN_BARE_BINARIES` with a reason
- [ ] Any "is this path inside the project" question uses a `containment.py` predicate, chosen
      by the question it asks
- [ ] `python3 -m pytest bin/ skills/ -q` is green, run from the repository root
- [ ] `python3 bin/check_skill_conformance.py` exits 0
- [ ] `python3 bin/check_doc_citations.py` and `python3 bin/check_invariants.py` exit 0

## Related Documentation

- [CONTRIBUTING.md](../../CONTRIBUTING.md) — the plugin development loop, live agent
  validation, the CI matrix and what it does not cover, and the two release paths
- [ARCHITECTURE.md](ARCHITECTURE.md) — how the ten skills connect, the `bin/` and `skills/`
  layout, and which artifacts are tracked
- [SKILL_REFERENCE.md](SKILL_REFERENCE.md) — every skill's commands, at a glance
- [patterns.md](../patterns.md) — the reusable patterns these conventions are drawn from
- [philosophy.md](../philosophy.md) — why the skills exist at all
- [decisions/](../decisions/) — the ADRs. The authority for *why*, and the place to look
  before re-litigating a settled question
