# Style Guide

The conventions actually in force in this repository, read out of the code rather than
imported from a general Python guide. Every rule below has at least one example you can
open; a rule with no example is not in this file.

Some of it a script enforces and CI runs; the rest is prose you are asked to follow, and
where a convention is unenforced this file says so rather than implying a gate that does
not exist.

| Convention | Enforced by | What happens if you break it |
|---|---|---|
| Standard library only | Nothing automated | Silent: it works on your machine, and the zero-install promise is gone |
| CPython 3.9 floor | `bin/test_freya_cli.py:447` (`PythonFloorTest`) | Red test if the four declarations drift apart; a `SyntaxError` in front of a user if the syntax itself is too new |
| No host-specific construct under `skills/` | `bin/check_skill_conformance.py`, run by CI | Exit 1, one `path:line: RULE: excerpt` per violation |
| Every bundled script reachable as `freya <command>` | R3, plus `bin/test_freya_cli.py:39` and `:49` | Red test, or an instruction that fails in front of a user |
| Comments explain why | Nothing automated | Nothing — which is why it is a review matter |
| Naming | R8/R12 for skills; nothing for Python | Skill: exit 1. Python: nothing |
| Two-commit separation | Nothing automated | A security report that references an unstable commit |

## The standard library is the whole runtime

There are no third-party runtime imports and adding one is an architectural decision, not a
convenience. Measured on 2026-08-21 by walking the AST of every module under `bin/` and
`skills/*/scripts/`: 61 distinct top-level module names are imported, and **every one is
either stdlib or a sibling module in this checkout**. `pytest` is the only package ever
installed, only to run the tests, and only in CI and on your machine
([`.github/workflows/ci.yml`](../../.github/workflows/ci.yml) installs it before the test
step; nothing under test imports it).

The cost of this rule is visible where it bites. `skills/freya-spec-manager/scripts/frontmatter.py`
is a hand-written, schema-validated frontmatter parser rather than PyYAML, because the suite
is zero-install and PyYAML is an install step
([ADR-005](../decisions/ADR-005-repair-parsing-substrate-in-place.md)). The `homegrown` graph
backend is a regex resolver rather than a tree-sitter one for the same reason, which is why
the tree-sitter option ships as an opt-in second backend instead of a dependency
([ADR-019](../decisions/ADR-019-the-floor-and-choosing-a-backend.md)).

So: a new dependency is an ADR. An import that is not stdlib and not a sibling is a defect.
**`bin/check_invariants.py` is what says so.** It walks the AST of every module under `bin/`
and `skills/*/scripts/` — including the ones imported inside a function, which this tree
really does have — and reports any top-level name that is neither standard library nor
another module of this checkout. CI runs it, and `ShippedTreeTest` in
`bin/test_check_invariants.py` asserts the same thing where pytest can see it, so the census
above no longer depends on someone re-running it by hand. There is deliberately no exemption
for the `try: import X / except ImportError:` shape: the tree contains no such import, and a
genuine optional dependency here is an ADR rather than a bare `except`.

## Target CPython 3.9

Four files declare the floor and none of them can import the others, so they are kept in
step by a test rather than by a constant: `bin/freya:19`, `bin/freya_cli.py:238`,
`install.sh:17`, `install.ps1:20`, held together by `PythonFloorTest`
(`bin/test_freya_cli.py:447`).

The floor is 3.9 rather than 3.8 for one concrete reason, recorded where the constant lives
(`bin/freya_cli.py:231`): `skills/freya-spec-manager/scripts/search_specs.py:116` annotates
`-> list[Spec]` with no `from __future__ import annotations`, and PEP 585 builtin generics
are only subscriptable at runtime from 3.9, so `freya spec` is a `TypeError` on 3.8.

Practically:

- PEP 585 builtin generics (`list[Spec]`, `dict[str, int]`) are fine.
- Nothing newer is. Measured: no `match` statement and no PEP 604 `X | Y` annotation exists
  anywhere in `bin/` or `skills/*/scripts/`.
- `from __future__ import annotations` appears in 8 of the 61 modules. It is not free:
  it is a 3.7+ construct, so `bin/freya` has to check the version *before* importing
  anything, or an old interpreter dies with a `SyntaxError` from a file the user never named
  (`bin/freya:12`).
- CI runs 3.9 and 3.13 on Linux and Windows, so a 3.10-only construct goes red on the 3.9
  half of the matrix rather than reaching a user.

## Nothing under `skills/` may name a host

[philosophy.md](../philosophy.md) singles this out as the one convention promoted to a gate,
and says why; [DEVELOPER.md](DEVELOPER.md#the-conformance-gate) has the rule-by-rule table and
is the authority for it. What matters for style is what you write **instead**:

| Instead of | Write |
|---|---|
| `${CLAUDE_PLUGIN_ROOT}/skills/x/scripts/y.py` | `freya <command>` — and register the script in `bin/commands.json` |
| `/freya-devkit:code-graph` | `freya-code-graph` |
| "Use Read on the file" / "the Grep tool" | "read the file" / "search for" |
| "Spawn 6 workers in parallel" | "…in parallel if your agent supports subagents, one at a time otherwise" |
| "reports land in `~/.claude/skills/`" | a path relative to the project |

**A script docstring is out of the gate's scope, and the convention still applies to it.** A
`.py` file gets only the substring rules and returns before the `freya <command>` check
(`bin/check_skill_conformance.py:317`), which is why
`skills/freya-spec-manager/scripts/search_specs.py:8` documents itself as
`python search_specs.py --query "authentication"` — a direct invocation nothing flags. Write
the launcher form there too; the gate is a floor, not the convention.

Measured on 2026-08-21 at commit `f407251`: 18 markdown and 49 Python files scanned, exit 0,
and none of the ten `SKILL.md` files names an interpreter. Naming a script by filename in prose
is a separate matter and not caught: `skills/freya-code-graph/SKILL.md:132` and `:582` both do.

## Comments explain why, and cite the thing that made them necessary

The convention is not "comment your code". It is: **a comment carries the failure or the
measurement that makes the code look the way it does**, so the next reader cannot "simplify"
it back into the bug. A comment that restates the line below it does not belong; a comment
that names a number, a corpus, a host or a dated validation run does.

Two real examples, quoted in full.

`bin/check_skill_conformance.py:52` — a limit that looks arbitrary, with the field report
that set it:

```python
#: Length limits from the Agent Skills specification. These are not advisory:
#: phase 6 validation found GitHub Copilot silently omitting a skill whose
#: description ran to 1251 characters, while Claude Code loaded it happily. The
#: skill was installed, linked and invisible — no error anywhere. R5 checks which
#: keys are present and never looked at how long their values were.
FRONTMATTER_LIMITS = {"description": 1024, "compatibility": 500, "name": 64}
```

`skills/freya-code-graph/scripts/graph_ops.py:954` — a search order that reads like an
omission, with the measurement proving it is not:

```python
# A package member deliberately does NOT get its own directory. Python 3 removed
# implicit relative imports, so a bare `import logging` inside a package is absolute
# and must not bind the sibling `logging.py`. Keeping from_dir as a last-resort base
# reinstated Python 2 semantics: measured on a 2,098-file stock-library corpus, 91 of
# 91 edges it produced were wrong, 24 of them files importing themselves.
```

Supporting conventions, all with examples:

- **`#:` above a module-level constant, `#` inside a function.** 221 `#:` lines across 13
  modules. The form documents the name that follows it — `bin/installer.py:50`,
  `bin/updater.py:33` (three paragraphs on why an update prints a reload hint, ending with
  why both agents are named).
- **Docstrings carry the same load as comments.** `bin/freya_cli.py:56` explains why a
  manifest path is judged with both `PureWindowsPath` and `PurePosixPath`, and cites the
  CI run where 3.13's `ntpath.isabs` change let `/etc/passwd` through on Windows while 3.9
  rejected it.
- **A test's docstring says what the test is protecting.** `bin/test_freya_cli.py:447` and
  the module docstring of [`conftest.py`](../../conftest.py) both do this; the latter calls
  itself "a safety net, not the mechanism" and records the ten tests that failed when pytest
  was run from inside `skills/`.
- **Prose citations are parsed.** A `path:line` in a `knowledge-base/` document becomes a
  doc-section → code edge, so an invented citation resolves to nothing and is dropped
  silently. See [DEVELOPER.md](DEVELOPER.md#citations-in-this-tree-are-parsed-not-decorative),
  which owns that rule.

## Naming

| Thing | Convention | Example | Enforced |
|---|---|---|---|
| Skill directory | `freya-<name>`, lowercase, single hyphens | `skills/freya-code-graph/` | R8+R12 — grammar only, not the `freya-` prefix |
| `SKILL.md` `name:` | equals the parent directory name | `name: freya-code-graph` | R8 |
| Launcher command | kebab-case, in `bin/commands.json` | `freya verify-links` | R3 — registration only, not the casing |
| Script module | `snake_case.py` under `skills/<skill>/scripts/` | `verify_links.py` | no |
| Test module | `test_<module>.py`, beside the module | `test_verify_links.py` | no |
| Function | `snake_case`, `_leading_underscore` when private | `_escapes` | no |
| Class | `PascalCase`; a private test double gets `_PascalCase` | `_FakeBackend` | no |
| Module constant | `UPPER_SNAKE` | `MIN_PYTHON` | no |
| `namedtuple` alias | `PascalCase` — it names a type, not a constant | `LinkPlan` (`bin/installer.py:51`) | no |
| Shared primitive | a `snake_case.py` module under `skills/freya-code-graph/scripts/`, imported by the `parents[2]` sibling pattern — never `bin/`, never a non-skill directory ([ADR-030](../decisions/ADR-030-shared-primitives-live-in-a-skill.md)) | `containment.py` | no |

Conformance measured 2026-08-21 across `bin/*.py` and `skills/*/scripts/*.py`: 2288
functions, 38 outside `snake_case` — all of them `setUp`/`tearDown`/`setUpClass`, imposed by
`unittest`. 293 classes, 6 outside `PascalCase` — all `_`-prefixed test doubles. 228
module-level assignments, 7 outside `UPPER_SNAKE` — six `namedtuple` aliases and one test
module's feature flag. All 10 skill directories carry the `freya-` prefix; all 17 command
names are kebab-case; no module file is outside `snake_case`.

**Tests live beside the code they cover**, which is also how the suite is discovered
(`python3 -m pytest bin/ skills/ -q`). Re-measured 2026-08-23: 34 of the 36 non-test modules
have a sibling `test_<module>.py`. The two that do not are `backends.py` and `settings.py`,
both exercised through `skills/freya-code-graph/scripts/test_substrate.py` and
`test_graph_ops.py`. The count was 29 of 32 on 2026-08-21 and the third exception was
`search_specs.py`, which has had `test_search_specs.py` beside it since; the census is
hand-run, so it is a snapshot rather than a gate.

**One hyphen changes the meaning.** `freya <command>` (space) is the CLI;
`freya-<skill>` (hyphen) is a skill name. They are never interchangeable
([DEVELOPER.md](DEVELOPER.md#invoking-bundled-scripts)).

## Formatting

There is no formatter and no linter — checked; [DEVELOPER.md](DEVELOPER.md#there-is-no-linter)
owns that finding and the open question about the `# noqa: E402` markers. Match the
surrounding file by eye. What "by eye" currently means, measured over the 32,326 lines of
Python in `bin/` and `skills/*/scripts/`: 4-space indent, median line 47 characters, 99th
percentile 95, and 114 lines over 100. Treat ~96 columns as the working limit.

**Pass an explicit encoding.** In shipped (non-test) code every `Path.read_text` and
`Path.write_text` call passes `encoding="utf-8"`; the 17 bare `read_text()` calls in the
tree are all in test files, reading files those tests just wrote. This is a Windows rule:
CI runs the whole suite on `windows-latest`, where the platform default is not UTF-8.

Eleven shipped-code `open()` calls do not follow it and fall back to the platform default —
nine in `skills/freya-docs-manager/scripts/detect_project.py` (reading `package.json`,
`pyproject.toml`, `schema.prisma`) and two in
`skills/freya-code-graph/scripts/graph_ops.py:1522` and `:1581` (reading and writing
`classifications.json`).

[TODO: Are those eleven `open()` calls deliberate, or a defect to file on the roadmap? A
non-UTF-8 `package.json` on a Windows host is the failing case, and nothing in the tree
records a decision either way.]

**Type annotations are a per-module choice, not a repo-wide one.** 260 of 2288 functions
carry any annotation, and they are concentrated: `graph_ops.py` annotates 89 of 90 functions
and `substrate.py` 43 of 43, while most modules annotate none. Every heavily annotated
module — `graph_ops.py`, `substrate.py`, `settings.py`, `backend_graphify.py`,
`docs_graph.py` — imports from `typing` and uses no builtin generics at all.
`search_specs.py` is the exception, and it is the reason the floor is 3.9 rather than 3.8.

[TODO: Is "match the module you are editing" the intended rule, or should new code be
annotated regardless? Worth settling before someone annotates half of a module.]

## Writing a correction rather than a rewrite

The two authority orderings — principle > ADR > spec > reference among intent artifacts, and
shipped code over any record — are [ADR-002](../decisions/ADR-002-authority-order-single-ownership.md)
and [`../decisions/README.md`](../decisions/README.md). What this file adds is what to *do*
when you find a record the code has outrun.

A correction is **appended and dated, never a rewrite**
([ADR-016](../decisions/ADR-016-prove-it-against-the-real-thing.md)). The reasoning that led
somewhere else is the useful part of the record; silently editing it makes the *why*
unrecoverable and lets the same wrong path be walked twice.

The live example is
[`ADR-017`](../decisions/ADR-017-behavior-json-is-committed.md), which carries a
`> **Correction, 2026-08-21.**` block under its Decision section recording that the list the
Decision named had grown, that the first revisit condition was checked and is not met, and one
caveat the original did not anticipate. The Decision itself was reworded to stop naming a
mutable list — the correction quotes the superseded sentence, which is what keeps the rewrite
from being silent. Where a correction and the original disagree, the order is shipped code,
then the correction, then the original.

Two related rules from the same place: never write "none" under Rejected Alternatives — if
nothing was considered, the obvious default was rejected, so name it — and **do not cite
`roadmap.md` by line**. It is edited continuously and a line citation into it drifts
silently; cite it by defect number or section heading.

## Commits

**Code and generated artifacts go in separate commits.** Commit 1 is the code; commit 2 is
docs, specs, security reports, the graph and the tracking files
([patterns.md](../patterns.md#pattern-two-commit-separation);
`skills/freya-wrap-up/SKILL.md:23` and `:33`). The reason is mechanical rather than
aesthetic: a security report references the commit it was generated from, and that reference
is only stable if the report is not in it.

What makes it hold is prose in each skill body, and which skills carry that prose is
[DEVELOPER.md § Artifacts, Not Commits](DEVELOPER.md#artifacts-not-commits).

**Message format.** `type(scope): summary`, lowercase type and scope, no trailing period.
Nothing enforces it and it does not need to be: measured on 2026-08-21, all 68 commits
reachable from `HEAD` follow it, 51 of them with a scope. The distribution is 36 `docs`,
17 `fix`, 12 `feat`, and one each of `test`, `spike` and `chore`; scopes are the thing
changed (`code-graph`, `docs-manager`). Bodies are prose paragraphs that carry the measurement or the reasoning —
the same standard as a comment — not a bullet list of files.

## Related documentation

- [DEVELOPER.md](DEVELOPER.md) — the local loop, the conformance gate rule by rule, the
  `FREYA_HOME` sandboxing rule for tests, and the integration conventions for a new skill
- [CONTRIBUTING.md](../../CONTRIBUTING.md) — the plugin development loop, live agent
  validation, the CI matrix and the release paths
- [patterns.md](../patterns.md) — the two-commit pattern and the rest of the reusable set
- [philosophy.md](../philosophy.md) — why agent-neutrality is a gate and everything else is
  guidance
- [decisions/](../decisions/) — the ADRs, and the format and correction rules for writing one
