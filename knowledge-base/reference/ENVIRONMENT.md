# Environment

Every environment variable this project reads, and every external binary it runs. Compiled by
grepping `os.environ` / `getenv` / `shutil.which` / `subprocess` across `bin/` and `skills/` on
2026-08-21, not from recall, and re-measured on 2026-08-24 after the security work that moved
every external binary behind a resolver. Each claim carries the `path:line` it was read at.

## There is nothing to configure

freya-devkit runs with no environment variables set at all. Everything below is an override
with a working default, and the defaults are what CI and every ordinary install use. There is
**no `.env` file, no `.env.example`, and no secret of any kind in this repository** —
`find . -name '*.env*'` outside `.git/` returns nothing, and the only occurrence of the word
"secrets" in the runtime code is a security-scan *category* name
(`skills/freya-codebase-security-scan/scripts/audit_io.py:20`). Nothing here authenticates to
anything. The one place ambient credentials matter is the audit driver, which spawns another
vendor's CLI; that is covered under [Credentials](#credentials).

## Environment variables

### Read by this project

| Variable | Read at | Default | What changes when it is set |
|---|---|---|---|
| `FREYA_HOME` | `skills/freya-code-graph/scripts/settings.py:585`, `bin/updater.py:563` | `~/.freya` | Relocates the machine-level settings file and the update-check stamp. Nothing else. |
| `FREYA_NO_UPDATE_CHECK` | `bin/updater.py:604`, reported by `bin/freya_cli.py:488` | unset | Suppresses the once-a-day staleness check entirely. |
| `FREYA_DEBUG` | `bin/updater.py:673` | unset | Prints the traceback from the update check, whose contract is to swallow every exception. |
| `PATH` | `bin/installer.py:529`, plus every `shutil.which` below | — | Decides which external binaries are found, and whether the installer prints a "not on PATH" hint. |
| `PYTHONPATH` | `bin/freya_cli.py:163` | unset | Read and *extended* — the launcher prepends the dispatched script's own directory before running it. |

`HOME` (and `USERPROFILE` on Windows) is not read directly anywhere, but every path this
toolkit writes outside a project derives from it. See
[Home-derived paths](#home-derived-paths).

#### `FREYA_HOME`

The important one, and the subject of
[ADR-019](../decisions/ADR-019-the-floor-and-choosing-a-backend.md). It names the directory
holding this machine's answer to "which parser should freya use":

```
~/.freya/settings.json      the machine-level backend default
~/.freya/update-check.json  the update-check throttle stamp
```

Both definitions read the variable the same way and fall back to `~/.freya`
(`skills/freya-code-graph/scripts/settings.py:585`, `bin/updater.py:563`). A value that is
empty or whitespace-only is ignored and the default applies
(`skills/freya-code-graph/scripts/settings.py:586`, `bin/updater.py:564`). The two definitions
are deliberately kept in step by a test — `test_the_machine_level_home_has_one_definition`,
`bin/test_backend_setup.py:161` — because a variable that relocated one and not the other would
isolate a test run's configuration while still writing a throttle stamp into the real home
(`bin/updater.py:552`).

`~/.freya` is its own directory rather than one belonging to an agent, because the suite
installs for more than one host and the answer is the same on all of them
(`skills/freya-code-graph/scripts/settings.py:88`). It is also deliberately outside the
checkout: `freya update` fast-forwards that tree, and configuration a `git pull` can clobber is
not configuration (`skills/freya-code-graph/scripts/settings.py:90`).

**What `FREYA_HOME` does not do.** It does not relocate the install. The agent skills
directories and the launcher target are derived from `Path.home()` directly and ignore this
variable entirely — `~/.claude/skills` (`bin/installer.py:37`), `~/.agents/skills`
(`bin/installer.py:38`), `~/.local/bin/freya` (`bin/installer.py:521`). To move an entire
install, redirect `HOME` instead; `CONTRIBUTING.md:34` documents that as the sandbox recipe for
live agent validation and states its two limits.

The test suite sets this variable for exactly this reason: `conftest.py:27` points it at a
throwaway temporary directory before collection, so the answer to "does a project with nothing
configured resolve to the floor?" does not depend on whose laptop is running the tests.

#### `FREYA_NO_UPDATE_CHECK`

Every `freya` command *except* `help`, `install`, `uninstall`, `update` and `doctor` runs a
throttled staleness check — those five are exempt by name (`bin/freya_cli.py:22`, gated at
`freya_cli.py:568`), because they either act on the notice directly or ask the question
themselves. The check is at most one `git ls-remote` per 24 hours (`bin/updater.py:567`),
notify-only, printed to stderr, with every exception swallowed (`bin/updater.py:642`). Setting
this variable returns `None` before any of that happens (`bin/updater.py:604`).

The test is Python truthiness on the raw string, so **any non-empty value disables the check,
including `FREYA_NO_UPDATE_CHECK=0`**. `README.md:198` and `CHANGELOG.md:186` both suggest `=1`;
`=0` is not a way to turn it back on. Unset the variable instead.

`freya doctor` reports the variable rather than obeying it silently: it prints
`[ok] updates: not checked (FREYA_NO_UPDATE_CHECK is set)` and skips the network
(`bin/freya_cli.py:488`). When it is *not* set, doctor runs the same check unthrottled on
purpose — a diagnostic reporting a cached answer is not diagnosing anything
(`bin/freya_cli.py:502`).

#### `FREYA_DEBUG`

`notify()` swallows every exception (`except Exception`, `bin/updater.py:669`), because a
notification that can break the command it precedes is worse than no notification
(`bin/updater.py:645`). It is not the suite's only broad handler. Re-measured on 2026-08-24 by
walking the AST of every `.py` in the checkout: **37 handlers catching `Exception` or
`BaseException` outside the test files, and no bare `except:` anywhere at all.** The tree's last
one was in `detect_infrastructure`'s unbounded YAML read, and SEC-008 removed it along with the
read — a bare handler there swallowed the `MemoryError` from a `*.yaml` symlinked at `/dev/zero`,
which is why the replacement refuses symlinked files rather than catching what they raise
(`skills/freya-docs-manager/scripts/detect_project.py:387`). `notify()`'s own docstring still
calls itself "the only bare `except` in the suite"; it is a broad `except Exception` and always
was, and that sentence is now wrong twice over. A permanently broken update check is
indistinguishable from "no update available" forever, so this
variable — again, any non-empty value — prints the traceback to the notice stream
(`bin/updater.py:673`). It reads `os.environ` rather than the injected `env` mapping
deliberately: the injected mapping is a plausible source of the exception being handled
(`bin/updater.py:670`). It affects nothing else in the toolkit.

#### `PATH`

Read directly once, to decide whether the installer needs to print a PATH hint after writing
the launcher (`bin/installer.py:524`–`:531`), with a platform-correct instruction rather than an
unconditional POSIX `export` line (`bin/installer.py:534`). Every other use is a program lookup,
and **nine of those still hand a bare name to the OS search**: the eight bare-`git` sites, plus
the behavior runner's `pnpm` (`skills/freya-behavior-runner/scripts/run_behaviors.py:228`, spawned
at `:459`). Everything else goes through `exec_path.resolve`, which calls `shutil.which` exactly
once and then refuses two classes of answer. Only the eight are counted by INV-2 — the `pnpm`
argv is assembled in a helper and passed by variable, so the checker cannot read its argv[0] and
skips it without a word (`bin/check_invariants.py:411`). See
[External binaries](#external-binaries).

#### `PYTHONPATH`

This is the one variable the project *writes* as well as reads. `freya <command>` dispatches to
a script under `skills/<skill>/scripts/`, and those scripts import their siblings by bare name.
Under `PYTHONSAFEPATH` / `-P` / isolated mode CPython does not put the script's own directory on
`sys.path`, so the launcher restores exactly that entry by prepending the script's directory to
the child's `PYTHONPATH` (`bin/freya_cli.py:161`–`155`). The rest of the parent environment is
copied through unchanged (`bin/freya_cli.py:161`), and that copy propagates to grandchildren —
the agent CLIs the audit driver spawns inherit it too.

### Home-derived paths

No code reads `HOME` or `USERPROFILE` by name. Everything outside a project derives from
`Path.home()` or `os.path.expanduser('~')`, both of which follow `$HOME`. `CONTRIBUTING.md:39`
pins the counts as an invariant to check before a live agent run; re-measured on this worktree
on 2026-08-24 with the same three greps, all three still hold:

| Idiom | Count | Where |
|---|---|---|
| `Path.home()` | 6 | `bin/installer.py:37`, `installer.py:38`, `installer.py:521`, `installer.py:818`; `bin/freya_cli.py:268`; `bin/updater.py:566` |
| `expanduser` | 1 | `skills/freya-code-graph/scripts/settings.py:588` |
| `os.environ['HOME']` / `.get('HOME')` | 0 | — |

The single `expanduser` is the machine-level default's home, and it is the one that
`FREYA_HOME` overrides independently of `$HOME`.

### Read by the interpreter, not by this project

`PYTHONSAFEPATH` (equivalently `python -P` or isolated mode) is not read by any code here, but
it changes what happens: it is why the launcher resolves itself with `realpath` and why
`child_env` exists at all — see
[DEVELOPER.md § How the launcher resolves a command](DEVELOPER.md#how-the-launcher-resolves-a-command).
Worth recording because it is the shape of a test gap: a regression here once got past the suite
because the one test that sets `PYTHONSAFEPATH` only ran `freya help`, which never spawns a child
(`bin/freya_cli.py:155`).

### Deliberately not read: `CLAUDE_*`

Host environment variables are host-specific constructs, so nothing under `skills/` may name one
— rules R1 and R13 of the conformance gate
([DEVELOPER.md § The conformance gate](DEVELOPER.md#the-conformance-gate)). Re-verified
2026-08-24 with `git grep`: no file in the repository *reads* `CLAUDE_PLUGIN_ROOT` — there is no
`os.environ`/`getenv` access to it anywhere. Thirteen tracked files contain the string, and all
thirteen are the checker, its test, or prose: `bin/check_skill_conformance.py`,
`bin/test_check_skill_conformance.py`, `bin/freya_cli.py:5`, `CHANGELOG.md`, `CONTRIBUTING.md`,
`knowledge-base/philosophy.md`, `knowledge-base/explanations/extending.html`,
[ADR-013](../decisions/ADR-013-single-freya-launcher.md),
`knowledge-base/specs/infra/SPEC-001-freya-launcher-command-surface.md`, and four pages under
`knowledge-base/reference/` — `DEVELOPER.md`, `STYLE_GUIDE.md`, `TESTING.md` and this one. The
`.claude-plugin/` manifests contain no reference to it at all.

## The machine file and the project file

These two files, not environment variables, are where configuration actually lives. ADR-019 is
the authority for why.

| File | Scope | Committed? | May contain |
|---|---|---|---|
| `~/.freya/settings.json` (`FREYA_HOME` relocates) | one machine | no — outside every repo | `substrate.backend`, `substrate.symbols` only (`settings.py:102`) |
| `knowledge-base/settings.json` | one project | **yes** — belongs in the repo, and `--use` asks for it to be committed | `substrate.*`, `directories.*` and `outside.*` |

`outside` is the third top-level section and the newest
([ADR-031](../decisions/ADR-031-crossing-the-root-is-a-declared-act.md),
`skills/freya-code-graph/scripts/settings.py:122`). It maps an alias to a **relative** directory
outside the project root — `{"outside": {"ui": "../packages/ui"}}` — and it is the only way any
part of this toolkit looks past the root. It is machine-level-forbidden for the same reason
`directories` is: scope is a fact about one project. It is also *resolution only*: a declared
root is stat'd and imports are resolved against it, but no file under one is read and no
directory under one is enumerated, so a crossing appears in the graph as an
`outside:<alias>/<rel>` edge target and never as a `files` key. See
[ARCHITECTURE.md § The shape of an edge](ARCHITECTURE.md#the-shape-of-an-edge).

Both files are optional. Absent, unreadable or malformed all yield defaults rather than an
error, on the principle that a build must not fail because configuration is missing
(`skills/freya-code-graph/scripts/settings.py:871`, `settings.py:603`). The defaults are
`substrate.backend: "auto"`, `substrate.symbols: false`, and empty `directories` and `outside`
maps (`skills/freya-code-graph/scripts/settings.py:148`–`:166`). `outside` is present in
`DEFAULTS` rather than absent so `load()` type-checks the section and warns on a non-object
instead of copying it through the forward-compatibility branch untouched
(`skills/freya-code-graph/scripts/settings.py:161`).

Precedence and what a degrade records are
[ARCHITECTURE.md § The graph substrate](ARCHITECTURE.md#the-graph-substrate). One distinction
belongs here because it is a property of the *file*: "absent" and "explicitly `auto`" are
different states, and an explicit `auto` in a project file means *defer to the machine*
(`skills/freya-code-graph/scripts/settings.py:767`, `settings.py:777`).

Keys outside the two allowed at machine level are dropped **and reported on stderr**, not
silently honoured (`skills/freya-code-graph/scripts/settings.py:645`). `directories` is
excluded there on purpose: a global `docs: source` would apply to repositories nobody has
looked at, and a global `node_modules: source` is a 50,000-file graph on every project on the
machine (`skills/freya-code-graph/scripts/settings.py:98`–`:101`). `outside` is excluded by the
same rule and without a special case — `GLOBAL_KEYS` is an allowlist of two paths, so a section
added later is machine-level-forbidden by default rather than by somebody remembering to forbid
it.

Writing the answer down:

```
freya code-graph --use <backend>            # this project's knowledge-base/settings.json
freya code-graph --use <backend> --global   # ~/.freya/settings.json
freya code-graph --use auto --global        # clears the machine default
```

At machine scope `auto` is not an answer but the absence of one, so `--use auto --global`
deletes the key rather than writing it — the only way to un-answer the install-time question
(`skills/freya-code-graph/scripts/settings.py:941`, `settings.py:962`).

The name is validated against the registry at the moment somebody is present to be told they
typed it wrong (`skills/freya-code-graph/scripts/graph_ops.py:3437`), and the project-scope
message asks for the file to be committed so a clone, a colleague and CI all resolve the same
backend (`skills/freya-code-graph/scripts/graph_ops.py:3472`). The machine-scope message is
careful about what it promises: a project already carrying its own answer keeps it
(`skills/freya-code-graph/scripts/graph_ops.py:3466`).

The first `--build` or `--update` in a project that has not decided copies the machine's answer
into that project's own committed settings
(`skills/freya-code-graph/scripts/graph_ops.py:3598` → `graph_ops.py:3390` →
`skills/freya-code-graph/scripts/settings.py:994`), validating it against the registry on the
way. A headless run with nothing configured writes nothing. Nothing verifies that the seeded
file is actually committed — the build prints one line asking for it
(`skills/freya-code-graph/scripts/graph_ops.py:3414`) and that is the entire mechanism; ADR-019
states this gap rather than implying enforcement.

Read on this worktree on 2026-08-24, `knowledge-base/settings.json` is tracked (committed at
`2deb4ef`) and reads:

```json
{
  "substrate": {
    "backend": "graphify"
  }
}
```

## External binaries

| Binary | Required? | How it is located | Run at | Absent or refused ⇒ |
|---|---|---|---|---|
| `python3` / `python` (≥ 3.9) | **yes**, to install | `install.sh:16`, `install.ps1:12` | same | install.sh exits 1 with "no Python 3.9+ found on PATH" |
| the running interpreter | **yes** | `sys.executable` | `bin/freya_cli.py:145` | n/a — never depends on a bare `python` being on PATH |
| `git`, new enough to know `--end-of-options` | for update, and for accuracy elsewhere; the G1 intent gate **stops running** without it, see below | two sites resolve it (`exec_path.resolve`, `bin/updater.py:139` and `skills/freya-code-graph/scripts/backend_graphify.py:739`); eight still spawn a bare `"git"` — the census below | `bin/updater.py:170`, `backend_graphify.py:743`, plus the eight | `freya update` refuses with a distinct message (`bin/updater.py:277`); graph/status/spec commands degrade |
| `graphify` | **no** — opt-in | `exec_path.resolve`, `skills/freya-code-graph/scripts/backend_graphify.py:318` (probe) and `:430` (spawn) | `skills/freya-code-graph/scripts/backend_graphify.py:434` | build degrades to the floor and records that it did |
| `claude` / `copilot` | **no** — only `freya security` | `exec_path.resolve` through `program_for`, `skills/freya-codebase-security-scan/scripts/audit_adapter.py:210`; `detect` asks it (`audit_adapter.py:222`) and `main()` resolves once (`skills/freya-codebase-security-scan/scripts/audit.py:403`) | `skills/freya-codebase-security-scan/scripts/audit.py:240` | driver exits 1 (`EXIT_NOTHING_TO_DO`), prints the per-CLI reason and names the in-loop fallback (`audit.py:389`–`:394`) |
| `pnpm` + `vitest` | **no** — only in a target project | not probed and not resolved | `skills/freya-behavior-runner/scripts/run_behaviors.py:228`, `run_behaviors.py:459` | **the runner raises `FileNotFoundError`** — see below |
| `npm` / `yarn` / `pnpm audit` | **no** — agent-run, no script | not probed | `skills/freya-dependency-vulnerability-check/SKILL.md:57`, `skills/freya-dependency-vulnerability-check/SKILL.md:62`, `skills/freya-dependency-vulnerability-check/SKILL.md:67` | the skill has nothing to read |

Python 3.9+ is the floor, not "any Python 3"
([STYLE_GUIDE.md § Target CPython 3.9](STYLE_GUIDE.md#target-cpython-39)). What is
environment-shaped about it: `bin/freya:19` checks the version *before* importing any suite
module, so an interpreter too old to run the toolkit can still print the reason rather than
dying in a file the user never named (`bin/freya:12`).

### `shutil.which` is no longer the answer on its own

Three of the rows above changed shape rather than moving. `graphify`, the two agent CLIs and
two of the git sites are now located by `exec_path.resolve`
(`skills/freya-code-graph/scripts/exec_path.py:84`), which calls `shutil.which` once and then
**refuses** two classes of result: one that is not already an absolute path, and — when the
caller passes the project being analysed — one that resolves inside it. Both refusals return a
printable reason instead of a path, and every caller already had a degrade path for "no such
program", so a refusal arrives as that same event with a better explanation
(`skills/freya-code-graph/scripts/exec_path.py:88`).

The rule is refuse, never absolutise. On Windows CPython's `shutil.which` inserts the working
directory at the head of the search path, and `CreateProcess` searches the parent process's
working directory before `PATH` whatever `cwd=` says — so a `graphify.exe` or `claude.exe`
committed to a scanned repository was found ahead of every real `PATH` entry. Calling
`abspath()` on that hit would have handed `CreateProcess` a fully-qualified path to the
attacker's binary; the module docstring records why that reading is backwards
(`skills/freya-code-graph/scripts/exec_path.py:23`). On Windows the module also sets
`NoDefaultCurrentDirectoryInExePath` — always, with `setdefault` so an operator's own value is
left alone — and that variable, **when it is honoured**, removes the working-directory entry
outright. It is honoured from CPython 3.12 onwards; on 3.9, 3.10 and 3.11 it does nothing and
the absoluteness refusal is the only control
(`skills/freya-code-graph/scripts/exec_path.py:29`, `exec_path.py:65`, `exec_path.py:76`). See
[SECURITY.md § The one accepted regression](SECURITY.md#the-one-accepted-regression-windows-on-python-39-311).

`exec_path` lives under `skills/freya-code-graph/scripts/` rather than in `bin/` so it travels
with every install mode, including `--copy`; ADR-030 records the measurement behind that. Two
importers guard the import and fall back to *refusing*, never to a bare name — `bin/updater.py:75`
and `skills/freya-codebase-security-scan/scripts/audit_adapter.py:52` — because a damaged store
is exactly when "just search `PATH`" looks like graceful degradation
(`bin/updater.py:53`).

`git` is used well beyond `freya update`. Re-counted 2026-08-24, ten `subprocess` calls spawn
git. Two of them go through the resolver, at `bin/updater.py:170` (argv[0] from `git_program`,
`bin/updater.py:119`) and `skills/freya-code-graph/scripts/backend_graphify.py:743`. The other
eight still name it bare, and that list is not hand-maintained — it is what
`python3 bin/check_invariants.py --no-allowlist --rule INV2` prints, which on 2026-08-24 is
`8 violation(s)`:

```
bin/check_doc_citations.py:135
skills/freya-behavior-graph/scripts/behavior_graph.py:841
skills/freya-behavior-runner/scripts/run_behaviors.py:471
skills/freya-code-graph/scripts/graph_ops.py:551
skills/freya-code-graph/scripts/graph_ops.py:581
skills/freya-spec-manager/scripts/drift.py:73
skills/freya-spec-manager/scripts/verify_intent.py:87
skills/freya-status/scripts/collect_status.py:33
```

This page previously said "nine", and both halves of that were wrong: the count was ten before
the two conversions, and the list it printed omitted `bin/check_doc_citations.py`. Run the
command rather than trusting the paragraph — the allowlisted census in
`KNOWN_BARE_BINARIES` (`bin/check_invariants.py:119`) is what keeps the number honest, and it
records seven files rather than eight sites because `graph_ops.py` has two.

Every one of the ten treats a missing git as an answer rather than a crash —
`run_behaviors.py:476` catches `FileNotFoundError` and returns `"unknown"`,
`behavior_graph.py:846` returns an empty change list, `updater.git` returns `(1, "")` for a
missing, refused *or* unresolvable git (`bin/updater.py:167`) — so the toolkit degrades rather
than failing when git is absent. `freya doctor` is the exception that had to be made: it prints
`git_program`'s *reason* rather than inferring a repository fact from a git call that never
happened, because `(1, "")` reads identically as "not a checkout" (`bin/updater.py:124`).

**One git site does not degrade, it stops — and the difference is worth a version floor.** The
G1 declared-intent gate spawns
`git diff --name-status -M --end-of-options <baseline>^{commit} --`
(`skills/freya-spec-manager/scripts/verify_intent.py:219`, through `_git` at
`verify_intent.py:87`), and those tokens are what make a repository-committed marker unable to
be read as anything but a revision (`verify_intent.py:167`, `:170`). A git that does not
recognise `--end-of-options` treats it as an unknown option, and an unknown option in that slot
is **rc=129** — measured on this machine on 2026-08-24 with git 2.50.1,
`git diff --name-status -M --definitely-not-an-option HEAD --` returns 129. `_changed_status`
reads any non-zero as "git could not answer" and returns `ok=False`
(`verify_intent.py:222`–`:223`), so on such a host the gate reports a labelled skip and exit 0
on **every** run, for ever, under ADR-009's fail-open. It does not answer less accurately; **it
stops answering**, and the label is the only place that says so.

The floor that implies is `git 2.24` (November 2019) — recorded in the code rather than measured
here, since no old git is available to test against (`verify_intent.py:213`). `^{commit}` adds
no floor above it: `<rev>^{<type>}` is gitrevisions syntax from long before that option existed.
This is the one binary requirement on this page that is about a git *feature* rather than about
git being present; if a permanent labelled skip is what you are seeing, run
`git diff --end-of-options HEAD --` on the host.

**The unit-behavior runner is the one place where a missing binary is not handled.** It
hardcodes `["pnpm", "vitest", "run", ...]`
(`skills/freya-behavior-runner/scripts/run_behaviors.py:228`) and calls it with no exception
handler (`run_behaviors.py:459`). A failing *test* is handled properly — the fingerprint comes
back with `reason="test-failed"` and coverage is never faked (`run_behaviors.py:501`–`:504`).
A missing *`pnpm`* is not: `FileNotFoundError` propagates through `fingerprint_behavior`
(`run_behaviors.py:683`) and `main` (`run_behaviors.py:828`) and ends the run in a traceback,
and because `behavior-graph` invokes the runner with `check=True`
(`skills/freya-behavior-graph/scripts/behavior_graph.py:220`) the whole `behavior.json` build
fails with it. There is also no setting for another package manager or another runner; that
part is a known, deliberately deferred gap — see the P4c entry in [roadmap.md](../roadmap.md),
which describes replacing the hardcoded `(state, level, adapter)` ladder with a runner-adapter
registry.

## The optional backend binary: `graphify`

`graphify` is the second substrate backend behind the contract in
[ADR-018](../decisions/ADR-018-substrate-contract-for-the-code-graph.md). How a backend is
selected, and what a degrade records, is
[ARCHITECTURE.md § The graph substrate](ARCHITECTURE.md#the-graph-substrate) and
[ADR-019](../decisions/ADR-019-the-floor-and-choosing-a-backend.md); what follows is the binary
itself.

Installing it, quoted from the install-time prompt (`bin/backend_setup.py:49`–`:51`):

```
uv tool install "graphifyy[sql,terraform]==0.9.47"   (or pip, on Python 3.10+)
freya code-graph --use graphify --global
```

**The version is pinned and the pin is the only spec anyone should be told to type.** graphifyy
is 0.x, and 0.9.47 is the release everything measured on this page was measured on; the unpinned
command resolved to 0.9.48 within two days of that measurement. Nothing here declares graphifyy
as a dependency — INV-1 makes the standard library the whole runtime, so there is no manifest or
lockfile for a bot to bump and the install is prose in a prompt. What holds the pin is a test,
`TestTheInstallInstructionIsPinnedAndUnambiguous` (`bin/test_backend_setup.py:203`), which
enumerates every install command the prompt prints and asserts each one names the exact spec
(`bin/test_backend_setup.py:270`) — enumerated rather than searched for, because the failure to
expect is a second install line added beside the pinned one. That test reads
`backend_setup.py`'s output and nothing else: this page and `CHANGELOG.md:33` are outside its
reach and are named in its docstring rather than gated (`bin/test_backend_setup.py:214`).

**`pip` is not an equal alternative, and the prompt now says so.** Every graphifyy release,
0.9.47 included, declares `Requires-Python >=3.10`, while this toolkit's floor is 3.9 and CI
runs a 3.9 leg. `uv tool install` provisions its own interpreter and is unaffected; `pip` uses
the one you are standing on, so on the floor this project supports the pip spelling simply
fails. Hence `(or pip, on Python 3.10+)` rather than `or: pip install …`. The caveat is read off
`MIN_PYTHON` rather than asserted, so raising the floor to 3.10 turns the guarding test red
instead of leaving a stale warning behind (`bin/test_backend_setup.py:292`).

The distribution name really is `graphifyy` with two y's while the command it installs is
`graphify` — confirmed on this machine on 2026-08-21: `uv tool list` reports
`graphifyy v0.9.47` providing `graphify` and `graphify-mcp`, and `graphify` resolves to
`~/.local/bin/graphify`. A separate `graphify` project exists on PyPI and is not this one, so
the single-y spelling installs a stranger's package; the prompt states both spellings at the
moment somebody is about to type one, and a second test pins that it does
(`bin/test_backend_setup.py:284`). The `[sql,terraform]` extras matter for a different reason:
graphify declares `.sql`, `.tf` and `.tfvars` unconditionally but only parses them when those
grammars are installed, so without the extras the extension census would affirm that nothing
went unread while the graph held no nodes for them (`bin/backend_setup.py:42`–`:47`).

**What happens when it is absent.** Nothing fails — the build degrades to the floor and records
that it did. `available()` costs no subprocess deliberately, because it runs during selection on
every build; what it no longer is, is a bare `PATH` check. It asks `exec_path.resolve` and treats
a refusal exactly like an absence (`skills/freya-code-graph/scripts/backend_graphify.py:318`), so
a `graphify` that resolves to a path inside the repository being analysed reads as "not
installed" and selection degrades to the floor — the honest answer, since there is no graphify
the *operator* chose. The spawn re-resolves rather than reusing the probe's verdict, so the exact
string that passed the check is the one that becomes argv[0]
(`skills/freya-code-graph/scripts/backend_graphify.py:425`). There is still **no version check**:
an incompatible release is selected and then degrades rather than being refused up front. One
degrade path is specific to this binary: a run that exceeds the 900-second timeout
(`skills/freya-code-graph/scripts/backend_graphify.py:53`, `backend_graphify.py:439`–`:441`).
The reasons a degrade can carry are tabulated in
[TROUBLESHOOTING.md § The build used `homegrown`](TROUBLESHOOTING.md#the-build-used-homegrown-when-settingsjson-says-graphify).

**What it writes.** `graphify update <project>` puts its extraction (`graph.json`), an HTML
viewer (`graph.html`), a report (`GRAPH_REPORT.md`), a manifest and a cache in
`graphify-out/` at the project root — measured on 0.9.47, over two runs, it keeps no dated
backups, though `backend_graphify.py:266` and `graph_ops.py:1281` still say it does. That
directory is outside `knowledge-base/`, which is
the only place this toolkit's own ignore rules reach. The backend therefore writes
`graphify-out/.gitignore` containing `*` after the tool has run
(`skills/freya-code-graph/scripts/backend_graphify.py:279`, `backend_graphify.py:395`),
leaving a hand-edited marker alone. freya reads only `graphify-out/graph.json`
(`skills/freya-code-graph/scripts/backend_graphify.py:48`, `backend_graphify.py:49`,
`backend_graphify.py:392`). This repository also ignores `graphify-out/` in its own root
`.gitignore`.

**Measured difference, 2026-08-21**, on a checkout where both per-backend graphs were present
under `knowledge-base/.graph/` (ADR-028 keeps one per backend so a swap can be diffed). Counting
`files` entries and the declared coverage in each artifact:

| | `graph.homegrown.json` | `graph.graphify.json` |
|---|---|---|
| files in the graph | 62 | 65 |
| declared languages | 4 | 40 |
| declared extensions | 6 | 93 |

Neither carried `degraded_from`. This is a different measurement from ADR-019's "68 of the 90
in-scope files", which is a *declared-coverage census* taken at commit `2762d54`; the numbers
above are file entries in the graphs as built then.

**Read that table as a record, not as something to re-read today.** Every `graph*.json` is named
in `.graph/.gitignore` (lines 13–14), so no graph survives a clone — but ignored is not absent,
and this worktree is not a fresh clone. Listed 2026-08-24, `knowledge-base/.graph/` holds four
files: the two tracked ones, `.gitignore` and `behavior.json`, plus two ignored graphs,
`graph.json` and `graph.graphify.json`, byte-identical to each other and both written by the
graphify backend at commit `9b7a3bc`. So the right-hand column can be spot-checked here and the
left-hand one cannot — there is no homegrown artifact on disk to re-read. The two that are
present read 77 files, 40 declared languages, 93 declared extensions and no `degraded_from`,
which is a later tree than the 2026-08-21 table above and not a correction to it. Rebuild with
`freya code-graph --build --dir .` under each backend before quoting either column.

## Credentials

freya-devkit reads no API key, token or password. The audit driver is the only component that
touches a credentialed service, and it does so by spawning another vendor's CLI — `claude` or
`copilot`, whichever is **usable** first
(`skills/freya-codebase-security-scan/scripts/audit_adapter.py:184`,
`audit_adapter.py:190`, `audit_adapter.py:213`). "Usable" is stricter than "on `PATH`": a CLI
that resolves inside the repository being audited is not one the operator installed, so `detect`
skips it and `main()` prints the refusal instead of reporting the binary missing. freya passes no
`env=` to `subprocess.run` (`skills/freya-codebase-security-scan/scripts/audit.py:240`), so each
worker inherits the full parent environment, including anything credential-shaped that happens
to be in it.

The code's assumption is that the CLI uses its own stored login: `Health` exists precisely
because "an expired login, a bad `--model` or a missing `--project` produce a run of empty
finders that is indistinguishable from a clean codebase"
(`skills/freya-codebase-security-scan/scripts/audit.py:110`), and the run is reported as
INCOMPLETE rather than clean when tasks go unanswered.

[TODO: Is an ambient credential in the environment (e.g. `ANTHROPIC_API_KEY`, `GH_TOKEN`) a
supported way to authenticate audit workers, or is the agent CLI's own stored login the only
sanctioned path? The driver inherits the whole environment either way, and nothing in the repo
records a policy.]

Three properties of the workers are enforced rather than assumed, and all three are about
capability rather than credentials: every argv is an explicit read-only allowlist; `build_argv`
refuses to emit a blanket permission flag even if one is smuggled in through the prompt
(`skills/freya-codebase-security-scan/scripts/audit_adapter.py:74`, `audit_adapter.py:83`,
`audit_adapter.py:123`); and argv[0] must be an absolute path or `_guard` refuses the invocation
outright (`audit_adapter.py:107`). The reason for the first two is recorded at
`skills/freya-codebase-security-scan/scripts/audit_adapter.py:7`:
`--allow-all-tools --deny-tool=write` still let a worker create a file with a shell redirect.
The reason for the third is that the first two constrain what a worker may **do** and say
nothing about **which file is started** — see
[SECURITY.md § What a worker can and cannot do](SECURITY.md#what-a-worker-can-and-cannot-do).
The `program` parameter carries no default, deliberately: a fallback would make the rule opt-in
per call site, and the one site that forgot would search `PATH` in silence
(`audit_adapter.py:124`).

## Configuration files

| Path | Written by | Committed? | Purpose |
|---|---|---|---|
| `~/.freya/settings.json` | `freya install` / `freya update` prompt, `--use --global` | outside every repo | machine-level backend + symbols default |
| `~/.freya/update-check.json` | `bin/updater.py:588` | outside every repo | update-check throttle stamp (`checked_at`, `behind`) |
| `knowledge-base/settings.json` | `freya code-graph --use`, or by hand | **meant to be committed**, and tracked here since `2deb4ef` | this project's backend, directory verdicts and `outside` declarations |
| `knowledge-base/.graph/.gitignore` | `code-graph --build` | tracked here since `2deb4ef` — not ignored | ignores the parse cache by name, leaving `behavior.json` committable |
| `graphify-out/.gitignore` | graphify backend, after a successful run | no — its own `*` matches itself, and this repo's root `.gitignore` ignores `graphify-out/` too | ignores graphify's whole output tree |
| `AGENTS.md` (managed block only) | `freya init` (`bin/agents_md.py:230`) | tracked, in the adopting project | the agent primer; only the text between the two markers is ours |
| `bin/commands.json` | hand-maintained | tracked | `freya <command>` → script manifest |
| `.claude-plugin/plugin.json`, `marketplace.json` | hand-maintained | tracked | Claude Code plugin install path; contains no environment references |

## Related documentation

- [ADR-019](../decisions/ADR-019-the-floor-and-choosing-a-backend.md) — why the floor always
  ships, why `auto` does not go shopping, and why the machine answer is recorded per project
- [ADR-013](../decisions/ADR-013-single-freya-launcher.md) — why one launcher, and why no
  host-specific environment variable appears under `skills/`
- [ADR-028](../decisions/ADR-028-graphs-are-stored-per-backend.md) — why both per-backend graphs
  are kept
- [reference/ARCHITECTURE.md](ARCHITECTURE.md) — what is tracked and what is ignored under
  `knowledge-base/`
- [reference/DEVELOPER.md](DEVELOPER.md) — how a skill invokes a bundled script
- [reference/TROUBLESHOOTING.md](TROUBLESHOOTING.md) — every configuration-shaped failure mode,
  each with a way to confirm it; this document describes the knobs, that one the symptoms
- [CONTRIBUTING.md](../../CONTRIBUTING.md) — the redirected-`HOME` sandbox recipe for live agent
  validation, and its limits
