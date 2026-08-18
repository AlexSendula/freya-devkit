# Contributing to freya-devkit

This repo is an **agent-neutral skill suite** that also ships as a Claude Code **plugin** and its own **marketplace**. The skills live in `skills/`, the launcher and installer in `bin/`, and documentation in `docs/`. Two install paths are supported and both must keep working: `install.sh` / `install.ps1` for any agent, and the Claude marketplace plugin.

## Local development loop

Install the plugin from your local checkout so you experience exactly what consumers do:

```text
/plugin marketplace add /absolute/path/to/freya-devkit
/plugin install freya-devkit@freya-devkit
```

Edit a skill under `skills/freya-<name>/SKILL.md`, then reload to pick up changes:

```text
/plugin marketplace update freya-devkit
```

Invoke skills with the plugin namespace, e.g. `/freya-devkit:freya-code-graph help`.

The `freya` launcher those skills call resolves on this path because Claude Code puts each
installed plugin's own `bin/` directory on the session `PATH` — no extra step. That is
host behaviour we depend on and cannot test from here (see the correction under Decision 1
in [`docs/design/portability/01-design.md`](docs/design/portability/01-design.md)); if you
ever see `freya: command not found` inside a plugin install, that is the dependency
breaking, and `./install.sh` from the checkout is the fallback. **Test the other path too**
— `./install.sh --agent copilot` and a real Copilot session catch a whole class of defect a
Claude-only loop never will.

## Conventions to preserve

- **Agent-neutral skill layer.** Nothing under `skills/` may name a Claude-only
  construct. `python3 bin/check_skill_conformance.py` enforces this and must exit 0;
  run it before you commit.
- **Cross-references use the prefixed skill name.** When cross-referencing from
  inside a SKILL.md, skills refer to each other as `freya-<skill>` (e.g.
  `freya-code-graph`), never `/freya-devkit:freya-<skill>` and never the bare
  `<skill>` form. (Invoking a skill directly on Claude, as in the Local
  development loop section above, is a separate concern — that's
  `/freya-devkit:freya-<skill>`, the plugin-namespaced form Claude itself
  resolves.) Nothing gets rewritten at install time: the repo's directories
  are already named `freya-<skill>`, which is also each `SKILL.md`'s
  `name:` field, because the Agent Skills spec requires `name` to equal the
  parent directory — that constraint is why the repo renamed its skill
  directories instead of having the installer do it. Installing means
  symlinking a `freya-<skill>` directory straight into the agent's skills
  directory (or, with `--copy`, copying it and dropping a small ownership
  marker inside so the copy can still be recognized, re-run, and
  uninstalled as ours) — either way, every `freya-<skill>` cross-reference
  already resolves without any renaming step.
- **Script invocations go through the launcher.** Call bundled scripts as
  `freya <command> ...` (e.g. `freya code-graph --build`), never
  `python "${CLAUDE_PLUGIN_ROOT}/..."`. The launcher self-locates and runs the target
  with `sys.executable`, so no `python` needs to be on PATH.
- **Register new CLI scripts in `bin/commands.json`.** Any script under
  `skills/*/scripts/` with a `__main__` block must have a manifest entry, or it is
  unreachable through `freya`. `bin/test_freya_cli.py` fails if you forget.
- **Mind the one-character distinction.** `freya <command>` (space) is the CLI;
  `freya-<skill>` (hyphen) is a skill name. They are never interchangeable.
- **Fan-out skills say what to do without subagents.** Any skill that presents N
  independent tasks (worker/discovery/category fan-out) must schedule them
  portably. Two shapes are in the tree, and which one you need depends on who
  owns the fan-out:
  - **Prose fan-out — copy the canonical block.** `skills/freya-docs-manager/SKILL.md`
    holds the **reference copy**; `freya-spec-manager` mirrors it byte-identically
    and any new prose fan-out should too. Copy it rather than paraphrasing. It
    must carry all three things: the "run in parallel **if your agent supports
    subagents**" clause, the **sequential fallback** ("one at a time"), and the
    **token-cost note** — a sequential run accumulates every task's reading
    context into one window and may not fit, so narrow the scope rather than let
    it truncate.
  - **Driver-owned fan-out — a deliberately shorter variant.**
    `freya-codebase-security-scan` does **not** carry the canonical block, and that
    is correct: since phase 7 its fan-out belongs to the `freya security scan`
    driver, which schedules its own worker processes and gives no agent a vote.
    The one-sentence form there covers only the no-agent-CLI fallback path. Don't
    "fix" it to match, and don't copy it as the reference for a prose fan-out — it
    omits the token-cost note on purpose, because that path is the exception.

  What the gate actually enforces: `python3 bin/check_skill_conformance.py` rule R9
  requires the sentinel phrase *"if your agent supports subagents"* **and** a
  sequential fallback (`one at a time` / `one by one` / `sequentially` / `in
  sequence`) somewhere in the file. That is a floor, not the convention — nothing
  checks for the token-cost note, and nothing checks the wording matches the
  reference. R9 is also **file-scoped**: if a file already has the clause and you
  add a *second*, unrelated fan-out elsewhere in that same file, R9 won't catch it;
  check by hand.
- **Skills write artifacts; only `freya-wrap-up` commits them.** Every
  artifact-writing skill states this in its own body, and it is a convention with a
  cause: phase-6 validation watched an agent with broad tool permissions infer a
  `git commit` no skill had asked for. Prose is the only lever a skill has here, so
  a new artifact-writing skill needs its own "Artifacts, not commits" paragraph —
  no conformance rule can check this, and the two-commit invariant is only as good
  as the newest skill.
- **Additive report fields.** `codebase-security-resolver` parses security reports by required fields (ID, Severity, Title, file, Status, Recommendation). Keep any new fields additive so it doesn't break.

## Tests and the CI gate

The suite is stdlib `unittest`, living beside the code it covers (`bin/test_*.py`,
`skills/*/scripts/test_*.py`). Run all of it:

```bash
python3 -m pytest bin/ skills/ -q
```

pytest is the only thing that is ever installed — everything under test is stdlib-only
and stays that way. `python3 -m unittest discover -s bin -p 'test_*.py'` works too, per
directory, if you'd rather not install a runner.

The conformance gate is **separate and not redundant**:

```bash
python3 bin/check_skill_conformance.py     # must exit 0
```

A shipped `SKILL.md` can violate most of R1–R13 with the whole pytest suite green,
because only this script scans the tree that actually ships. Run both before you commit.

[`.github/workflows/ci.yml`](.github/workflows/ci.yml) runs both on every push and pull
request, across Linux and Windows on Python 3.9 and 3.13, plus a second job that drives
`install.sh` / `install.ps1` end to end and resolves the launcher by name off `PATH`.
That is **8 jobs** — `{tests, install} × {ubuntu-latest, windows-latest} × {3.9, 3.13}`.
`install` is deliberately a separate job from `test`, so a failing test can't hide the
install's answer behind an early exit.

**3.9 is the real floor** — `skills/freya-spec-manager/scripts/search_specs.py` uses PEP
585 builtin generics in an evaluated annotation, which is a `TypeError` on 3.8. Don't
reach past 3.9 syntax without moving the matrix with it.

**Know what the green tick does not cover**, so you don't read more into it than it says:

- The install job runs **symlink mode on Linux and `--copy` on Windows**. That mirrors
  how each platform is actually used, and it leaves the other diagonal — Linux `--copy`,
  Windows *with* Developer Mode — unexercised. Touch either path and test it by hand.
- **No agent CLI is installed on the runner.** CI proves the toolkit installs and its own
  tests pass on Windows; it has never proven that a live scan runs there.
- **Windows-exclusive code cannot go red on a POSIX run.** `cmd_shim_plan` is only
  reached on Windows, and that is exactly where the first pass shipped a bug the matrix
  couldn't see. New platform-specific branches need a test that runs on every platform —
  drive the helper directly rather than only through the platform gate.

## Releasing updates

**There are two consumer paths and they update by completely different mechanisms.** Both
are live at once, so a release has to be correct for both.

**1. Claude marketplace consumers — versioned.**

1. Bump `version` (semver) in `.claude-plugin/plugin.json`, and add the entry to
   [`CHANGELOG.md`](CHANGELOG.md).
2. Commit and push.
3. Consumers run `/plugin marketplace update freya-devkit` to pull the new version.

If `version` is omitted, the git commit SHA is used and every commit looks like an update
— so prefer bumping `version` deliberately per release. Pre-1.0, a breaking change bumps
the *minor* (0.1.0 → 0.2.0); the skill rename in 0.2.0 is the worked example.

**2. `freya update` consumers — unversioned, and already live.**

`freya update` **fast-forwards the checkout to its tracked branch's head** and re-links.
No version is read, compared or reported anywhere in that path. So **every commit you
push is immediately shipped** to anyone who runs `freya update` — there is no staging
between merge and release for them, and a half-finished change on the tracked branch is
a half-finished change on their machine. Two consequences worth internalising:

- Don't push work-in-progress to the branch users track. The design's own escape hatch,
  if this ever needs to change, is a `stable` tag that `freya update` follows instead of
  `main` — recorded in [`docs/design/portability/00-vision.md`](docs/design/portability/00-vision.md) §4.4, deliberately not built.
- A breaking change reaches them with **no signal at all** — no version, no changelog
  prompt, nothing. Anything breaking therefore needs a note in `CHANGELOG.md` *and* a
  page under [`docs/migrations/`](docs/migrations/) that stands on its own, because the
  migration doc is the only artifact both paths can be pointed at.

## Design docs

Read these before making structural changes. They describe the system **as it is**:

- [`docs/philosophy.md`](docs/philosophy.md) — why the skills exist, core concepts
- [`docs/architecture.md`](docs/architecture.md) — how skills connect, data flow
- [`docs/patterns.md`](docs/patterns.md) — reusable patterns
- [`docs/conventions.md`](docs/conventions.md) — integration guidelines
- [`docs/skill-reference.md`](docs/skill-reference.md) — every skill's commands, at a glance

Separately, [`docs/design/`](docs/design/) holds **dated design records** — what was
decided, when, and why, including the reasoning that turned out wrong. They are not
specifications and are not kept in sync with the code: where implementation went
elsewhere, the original wording stays and a dated `> **Correction …**` block goes
underneath it, because in a design record the discarded reasoning is the valuable part.
[`docs/design/portability/01-design.md`](docs/design/portability/01-design.md) carries
nine such corrections. **Shipped code beats a correction beats the original text.** If
you find a design record that says the opposite of what shipped, append a correction —
don't rewrite it, and don't take it as the contract.
