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
| CPython 3.9 floor | `bin/test_freya_cli.py:473` (`PythonFloorTest`) | Red test if the four declarations drift apart; a `SyntaxError` in front of a user if the syntax itself is too new |
| No host-specific construct under `skills/` | `bin/check_skill_conformance.py`, run by CI | Exit 1, one `path:line: RULE: excerpt` per violation |
| Every bundled script reachable as `freya <command>` | R3, plus `bin/test_freya_cli.py:40` and `:50` | Red test, or an instruction that fails in front of a user |
| One pinned spec for the one third-party install the toolkit ever prints | `bin/test_backend_setup.py:203` | Red test if the prompt prints an unpinned, extras-free or second install line |
| Comments explain why | Nothing automated | Nothing — which is why it is a review matter |
| Naming | R8/R12 for skills; nothing for Python | Skill: exit 1. Python: nothing |
| Two-commit separation | Nothing automated | A security report that references an unstable commit |

## The standard library is the whole runtime

There are no third-party runtime imports and adding one is an architectural decision, not a
convenience. Re-measured on 2026-08-24 by walking the AST of all 73 modules under `bin/` and
`skills/*/scripts/`: 69 distinct top-level module names are imported, and **every one is
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
above no longer depends on someone re-running it by hand. **A genuine optional dependency
here is an ADR rather than a broad `except`, and INV-1 grows no carve-out for the
guarded-import shape.**

The reason it grows none is not that the shape is absent. Measured 2026-08-24 with the AST,
twelve `try` blocks in the tree open with an import, eleven of them in shipped code, and **every
one of them names a module of this checkout** — `installer` (`bin/freya_cli.py:189`), `settings`
and `backends`
(`bin/backend_setup.py:72`), `backend_setup` (`bin/installer.py:985`, `bin/updater.py:391`),
`backends` four times in `skills/freya-code-graph/scripts/graph_ops.py`, `updater`
(`bin/freya_cli.py:559`), and the two shared-primitive bootstrap guards ADR-030 argues for,
`exec_path` (`bin/updater.py:75`) and `containment` + `exec_path`
(`skills/freya-codebase-security-scan/scripts/audit_adapter.py:52`). The twelfth is in a test and
is not a guard at all — `bin/test_freya_cli.py:1365` pairs `try: import containment` with a
`finally` that removes the path it just added, and has no `except` clause. None of the twelve is
third-party, so none is what a carve-out would be *for*, and INV-1 permits all of them already
because they name sibling modules. That is the point: the *shape* is not evidence, and a rule
that skipped a name because it was guarded would exempt a future `try: import yaml` on the
strength of a syntax twelve existing sites already use for something else. The argument is kept
beside the code that refuses it (`bin/check_invariants.py:250`).

Two smaller corrections while this is being read. This section previously said "the tree
contains no such import"; that was already false when written, since nine of the eleven shipped
sites predate the security work, and the two `exec_path` guards are only what made it visible. And
`check_imports`' own docstring and ADR-030 both say **four** rather than eleven: they are
counting the guards that exist to survive a *damaged store*, a narrower and more interesting
set, and their four includes `skills/freya-behavior-runner/scripts/run_behaviors.py:270`, which
guards `importlib.util.find_spec` and is not an `import` statement at all. Neither number is
wrong; they answer different questions, and only this one is a count of the syntax.

## Target CPython 3.9

Four files declare the floor and none of them can import the others, so they are kept in
step by a test rather than by a constant: `bin/freya:19`, `bin/freya_cli.py:238`,
`install.sh:17`, `install.ps1:20`, held together by `PythonFloorTest`
(`bin/test_freya_cli.py:473`).

The floor is 3.9 rather than 3.8 for one concrete reason, recorded where the constant lives
(`bin/freya_cli.py:231`): `skills/freya-spec-manager/scripts/search_specs.py:116` annotates
`-> list[Spec]` with no `from __future__ import annotations`, and PEP 585 builtin generics
are only subscriptable at runtime from 3.9, so `freya spec` is a `TypeError` on 3.8.

Practically:

- PEP 585 builtin generics (`list[Spec]`, `dict[str, int]`) are fine.
- Nothing newer is. Measured: no `match` statement and no PEP 604 `X | Y` annotation exists
  anywhere in `bin/` or `skills/*/scripts/`.
- `from __future__ import annotations` appears in 10 of the 73 modules. It is not free:
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
(`bin/check_skill_conformance.py:388`), which is why
`skills/freya-spec-manager/scripts/search_specs.py:8` documents itself as
`python search_specs.py --query "authentication"` — a direct invocation nothing flags. Write
the launcher form there too; the gate is a floor, not the convention.

Re-measured on 2026-08-24: 23 markdown and 56 Python files scanned, exit 0, and none of the ten
`SKILL.md` files names an interpreter. Naming a script by filename in prose is a separate matter
and not caught: `skills/freya-code-graph/SKILL.md:149` and `:599` both do.

## Comments explain why, and cite the thing that made them necessary

The convention is not "comment your code". It is: **a comment carries the failure or the
measurement that makes the code look the way it does**, so the next reader cannot "simplify"
it back into the bug. A comment that restates the line below it does not belong; a comment
that names a number, a corpus, a host or a dated validation run does.

Two real examples, quoted in full.

`bin/check_skill_conformance.py:55` — a limit that looks arbitrary, with the field report
that set it:

```python
#: Length limits from the Agent Skills specification. These are not advisory:
#: phase 6 validation found GitHub Copilot silently omitting a skill whose
#: description ran to 1251 characters, while Claude Code loaded it happily. The
#: skill was installed, linked and invisible — no error anywhere. R5 checks which
#: keys are present and never looked at how long their values were.
FRONTMATTER_LIMITS = {"description": 1024, "compatibility": 500, "name": 64}
```

`skills/freya-code-graph/scripts/graph_ops.py:1016`–`:1020` — a search order that reads like an
omission, with the measurement proving it is not:

```python
# A package member deliberately does NOT get its own directory. Python 3 removed
# implicit relative imports, so a bare `import logging` inside a package is absolute
# and must not bind the sibling `logging.py`. Keeping from_dir as a last-resort base
# reinstated Python 2 semantics: measured on a 2,098-file stock-library corpus, 91 of
# 91 edges it produced were wrong, 24 of them files importing themselves.
```

Supporting conventions, all with examples:

- **`#:` above a module-level constant, `#` inside a function.** Re-counted 2026-08-24: 819
  `#:` lines across 33 modules, up from 221 across 13 three days earlier — the convention
  spread with the security work, which is comment-heavy by necessity. The form documents the
  name that follows it — `bin/installer.py:50`,
  `bin/updater.py:100` (three paragraphs on why an update prints a reload hint, ending with
  why both agents are named).
- **Docstrings carry the same load as comments.** `bin/freya_cli.py:56` explains why a
  manifest path is judged with both `PureWindowsPath` and `PurePosixPath`, and cites the
  CI run where 3.13's `ntpath.isabs` change let `/etc/passwd` through on Windows while 3.9
  rejected it.
- **A test's docstring says what the test is protecting.** `bin/test_freya_cli.py:473` and
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
| `namedtuple` alias | `PascalCase` — it names a type, not a constant | `LinkPlan` (`bin/installer.py:51`), `Resolution` (`skills/freya-code-graph/scripts/exec_path.py:57`) | no |
| Shared primitive | a `snake_case.py` module under `skills/freya-code-graph/scripts/`, imported by the `parents[2]` sibling pattern — never `bin/`, never a non-skill directory ([ADR-030](../decisions/ADR-030-shared-primitives-live-in-a-skill.md)) | `containment.py`, `exec_path.py` | no |

Conformance re-measured 2026-08-24 across `bin/*.py` and `skills/*/scripts/*.py`: 3179
functions, 63 outside `snake_case` — all of them `setUp`/`tearDown`/`setUpClass`, imposed by
`unittest`. 407 classes, 10 outside `PascalCase` — all `_`-prefixed test doubles and fixtures.
325 module-level assignments, 11 outside `UPPER_SNAKE` — ten `namedtuple` aliases and one test
module's feature flag (`needs_graphify`). All 10 skill directories carry the `freya-` prefix;
all 17 command names are kebab-case; no module file is outside `snake_case`. The counts are
roughly 40% higher than the 2026-08-21 figures for one reason: the tree grew, mostly in tests.

**Tests live beside the code they cover**, which is also how the suite is discovered
(`python3 -m pytest bin/ skills/ -q`). Re-measured 2026-08-24: **35 of the 36 non-test modules
have a sibling `test_<module>.py`**, and the one that does not is
`skills/freya-code-graph/scripts/backends.py`, exercised through
`skills/freya-code-graph/scripts/test_substrate.py` and `test_graph_ops.py`. `settings.py` was
the other exception and now has `test_settings.py` beside it; `search_specs.py` was the one
before that. The census is hand-run, so it is a snapshot rather than a gate — and it has moved
three times in four days, which is the argument for re-running it rather than quoting it.

**One hyphen changes the meaning.** `freya <command>` (space) is the CLI;
`freya-<skill>` (hyphen) is a skill name. They are never interchangeable
([DEVELOPER.md](DEVELOPER.md#invoking-bundled-scripts)).

## Formatting

There is no formatter and no linter — checked; [DEVELOPER.md](DEVELOPER.md#there-is-no-linter)
owns that finding and the open question about the `# noqa: E402` markers. Match the
surrounding file by eye. What "by eye" currently means, re-measured 2026-08-24 over the 48,102
lines of Python in `bin/` and `skills/*/scripts/`: 4-space indent, median line 51 characters,
99th percentile 95, and 117 lines over 100. Treat ~96 columns as the working limit.

**Pass an explicit encoding.** In shipped (non-test) code every `Path.read_text` and
`Path.write_text` call passes `encoding="utf-8"` — checked by AST on 2026-08-24, not by grep,
because two of them pass it on the following line. The 44 bare calls in the tree are all in test
files, reading files those tests just wrote. This is a Windows rule: CI runs the whole suite on
`windows-latest`, where the platform default is not UTF-8.

Ten shipped-code `open()` calls do not follow it and fall back to the platform default — eight
in `skills/freya-docs-manager/scripts/detect_project.py` (reading `package.json`,
`pyproject.toml`, `schema.prisma`) and two in
`skills/freya-code-graph/scripts/graph_ops.py:1584` and `:1643` (reading and writing
`classifications.json`). It was eleven and nine before SEC-008: the Kubernetes probe that used
to `open()` a whole YAML file in text mode now reads a bounded prefix in **binary** and matches
`b"apiVersion"`, so it takes no encoding argument and left the census by being rewritten rather
than by being annotated (`skills/freya-docs-manager/scripts/detect_project.py:483`). Reading
bytes there is the fix, not a shortcut — a `UnicodeDecodeError` is a `ValueError`, so the
`except OSError` the security report asked for would have turned a swallowed error into an
uncaught traceback on the first non-UTF-8 byte.

[TODO: Are those ten `open()` calls deliberate, or a defect to file on the roadmap? A
non-UTF-8 `package.json` on a Windows host is the failing case, and nothing in the tree
records a decision either way.]

**Type annotations are a per-module choice, not a repo-wide one.** 286 of 3179 functions
carry any annotation, and they are concentrated: `graph_ops.py` annotates 99 of 100 functions
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
Nothing enforces it. Re-measured 2026-08-24: 18 commits are reachable from `HEAD`, 17 of them
follow the format and 10 carry a scope. The distribution is 9 `docs`, 5 `feat`, 3 `fix`; scopes
are the thing changed (`code-graph`, `security`, `adr`, `readme`). The one exception is the
release commit `0.3.0 — the polyglot substrate, and the toolkit run on itself`, which is a
squash and is deliberately titled as a version rather than a change.

The earlier figure here — 68 commits, 36 `docs`, 17 `fix`, 12 `feat`, one each of `test`,
`spike` and `chore` — was true on 2026-08-21 and describes a history that no longer exists: the
0.3.0 release squashed it. Any per-commit census on this page is a statement about the current
`git log` and nothing more.

Bodies are prose paragraphs that carry the measurement or the reasoning — the same standard as
a comment — not a bullet list of files.

## Related documentation

- [DEVELOPER.md](DEVELOPER.md) — the local loop, the conformance gate rule by rule, the
  `FREYA_HOME` sandboxing rule for tests, and the integration conventions for a new skill
- [CONTRIBUTING.md](../../CONTRIBUTING.md) — the plugin development loop, live agent
  validation, the CI matrix and the release paths
- [patterns.md](../patterns.md) — the two-commit pattern and the rest of the reusable set
- [philosophy.md](../philosophy.md) — why agent-neutrality is a gate and everything else is
  guidance
- [decisions/](../decisions/) — the ADRs, and the format and correction rules for writing one
