# Environment

Every environment variable this project reads, and every external binary it runs. Compiled by
grepping `os.environ` / `getenv` / `shutil.which` / `subprocess` across `bin/` and `skills/` on
2026-08-21, not from recall. Each claim carries the `path:line` it was read at.

## There is nothing to configure

freya-devkit runs with no environment variables set at all. Everything below is an override
with a working default, and the defaults are what CI and every ordinary install use. There is
**no `.env` file, no `.env.example`, and no secret of any kind in this repository** —
`find . -name '*.env*'` outside `.git/` returns nothing, and the only occurrence of the word
"secrets" in the runtime code is a security-scan *category* name
(`skills/freya-codebase-security-scan/scripts/audit_io.py:19`). Nothing here authenticates to
anything. The one place ambient credentials matter is the audit driver, which spawns another
vendor's CLI; that is covered under [Credentials](#credentials).

## Environment variables

### Read by this project

| Variable | Read at | Default | What changes when it is set |
|---|---|---|---|
| `FREYA_HOME` | `skills/freya-code-graph/scripts/settings.py:132`, `bin/updater.py:445` | `~/.freya` | Relocates the machine-level settings file and the update-check stamp. Nothing else. |
| `FREYA_NO_UPDATE_CHECK` | `bin/updater.py:486`, reported by `bin/freya_cli.py:452` | unset | Suppresses the once-a-day staleness check entirely. |
| `FREYA_DEBUG` | `bin/updater.py:555` | unset | Prints the traceback from the update check, whose contract is to swallow every exception. |
| `PATH` | `bin/installer.py:529`, plus every `shutil.which` below | — | Decides which external binaries are found, and whether the installer prints a "not on PATH" hint. |
| `PYTHONPATH` | `bin/freya_cli.py:142` | unset | Read and *extended* — the launcher prepends the dispatched script's own directory before running it. |

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
(`skills/freya-code-graph/scripts/settings.py:132`, `bin/updater.py:445`). A value that is
empty or whitespace-only is ignored and the default applies
(`skills/freya-code-graph/scripts/settings.py:133`, `bin/updater.py:446`). The two definitions
are deliberately kept in step by a test — `test_the_machine_level_home_has_one_definition`,
`bin/test_backend_setup.py:161` — because a variable that relocated one and not the other would
isolate a test run's configuration while still writing a throttle stamp into the real home
(`bin/updater.py:434`).

`~/.freya` is its own directory rather than one belonging to an agent, because the suite
installs for more than one host and the answer is the same on all of them
(`skills/freya-code-graph/scripts/settings.py:55`). It is also deliberately outside the
checkout: `freya update` fast-forwards that tree, and configuration a `git pull` can clobber is
not configuration (`skills/freya-code-graph/scripts/settings.py:57`).

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
throttled staleness check — those five are exempt by name (`bin/freya_cli.py:21`, gated at
`freya_cli.py:524`), because they either act on the notice directly or ask the question
themselves. The check is at most one `git ls-remote` per 24 hours (`bin/updater.py:449`),
notify-only, printed to stderr, with every exception swallowed (`bin/updater.py:524`). Setting
this variable returns `None` before any of that happens (`bin/updater.py:486`).

The test is Python truthiness on the raw string, so **any non-empty value disables the check,
including `FREYA_NO_UPDATE_CHECK=0`**. `README.md:88` and `CHANGELOG.md:140` both suggest `=1`;
`=0` is not a way to turn it back on. Unset the variable instead.

`freya doctor` reports the variable rather than obeying it silently: it prints
`[ok] updates: not checked (FREYA_NO_UPDATE_CHECK is set)` and skips the network
(`bin/freya_cli.py:452`). When it is *not* set, doctor runs the same check unthrottled on
purpose — a diagnostic reporting a cached answer is not diagnosing anything
(`bin/freya_cli.py:458`).

#### `FREYA_DEBUG`

`notify()` swallows every exception (`except Exception`, `bin/updater.py:551`), because a
notification that can break the command it precedes is worse than no notification
(`bin/updater.py:527`). It is not the suite's only broad handler — there are 33 outside the
tests, and the one literal bare `except:` is elsewhere
(`skills/freya-docs-manager/scripts/detect_project.py:330`). That makes a
permanently broken update check indistinguishable from "no update available" forever, so this
variable — again, any non-empty value — prints the traceback to the notice stream
(`bin/updater.py:555`). It reads `os.environ` rather than the injected `env` mapping
deliberately: the injected mapping is a plausible source of the exception being handled
(`bin/updater.py:552`). It affects nothing else in the toolkit.

#### `PATH`

Read directly once, to decide whether the installer needs to print a PATH hint after writing
the launcher (`bin/installer.py:524`–`531`), with a platform-correct instruction rather than an
unconditional POSIX `export` line (`bin/installer.py:534`). Every other use is a
`shutil.which()` lookup — see [External binaries](#external-binaries).

#### `PYTHONPATH`

This is the one variable the project *writes* as well as reads. `freya <command>` dispatches to
a script under `skills/<skill>/scripts/`, and those scripts import their siblings by bare name.
Under `PYTHONSAFEPATH` / `-P` / isolated mode CPython does not put the script's own directory on
`sys.path`, so the launcher restores exactly that entry by prepending the script's directory to
the child's `PYTHONPATH` (`bin/freya_cli.py:140`–`144`). The rest of the parent environment is
copied through unchanged (`bin/freya_cli.py:140`), and that copy propagates to grandchildren —
the agent CLIs the audit driver spawns inherit it too.

### Home-derived paths

No code reads `HOME` or `USERPROFILE` by name. Everything outside a project derives from
`Path.home()` or `os.path.expanduser('~')`, both of which follow `$HOME`. `CONTRIBUTING.md:39`
pins the counts as an invariant to check before a live agent run; re-measured on this worktree
on 2026-08-21 with the same three greps, they still hold:

| Idiom | Count | Where |
|---|---|---|
| `Path.home()` | 6 | `bin/installer.py:37`, `installer.py:38`, `installer.py:521`, `installer.py:818`; `bin/freya_cli.py:247`; `bin/updater.py:448` |
| `expanduser` | 1 | `skills/freya-code-graph/scripts/settings.py:135` |
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
(`bin/freya_cli.py:134`).

### Deliberately not read: `CLAUDE_*`

Host environment variables are host-specific constructs, so nothing under `skills/` may name one
— rules R1 and R13 of the conformance gate
([DEVELOPER.md § The conformance gate](DEVELOPER.md#the-conformance-gate)). Verified 2026-08-21:
no file in the repository *reads* `CLAUDE_PLUGIN_ROOT`. The thirteen that contain the string are
the conformance checker, its test, and prose — `CHANGELOG.md`, `CONTRIBUTING.md`,
`bin/freya_cli.py:5`, `knowledge-base/philosophy.md`,
`knowledge-base/explanations/extending.html`, four sibling pages under
`knowledge-base/reference/` and
[ADR-013](../decisions/ADR-013-single-freya-launcher.md). The `.claude-plugin/` manifests
contain no reference to it at all.

## The machine file and the project file

These two files, not environment variables, are where configuration actually lives. ADR-019 is
the authority for why.

| File | Scope | Committed? | May contain |
|---|---|---|---|
| `~/.freya/settings.json` (`FREYA_HOME` relocates) | one machine | no — outside every repo | `substrate.backend`, `substrate.symbols` only (`settings.py:69`) |
| `knowledge-base/settings.json` | one project | **yes** — belongs in the repo, and `--use` asks for it to be committed | `substrate.*` and `directories.*` |

Both are optional. Absent, unreadable or malformed all yield defaults rather than an error, on
the principle that a build must not fail because configuration is missing
(`skills/freya-code-graph/scripts/settings.py:383`, `settings.py:150`). The defaults are
`substrate.backend: "auto"` and `substrate.symbols: false`
(`skills/freya-code-graph/scripts/settings.py:93`–`106`).

Precedence and what a degrade records are
[ARCHITECTURE.md § The graph substrate](ARCHITECTURE.md#the-graph-substrate). One distinction
belongs here because it is a property of the *file*: "absent" and "explicitly `auto`" are
different states, and an explicit `auto` in a project file means *defer to the machine*
(`skills/freya-code-graph/scripts/settings.py:296`, `settings.py:306`).

Keys outside the two allowed at machine level are dropped **and reported on stderr**, not
silently honoured (`skills/freya-code-graph/scripts/settings.py:192`). `directories` is
excluded there on purpose: a global `docs: source` would apply to repositories nobody has
looked at, and a global `node_modules: source` is a 50,000-file graph on every project on the
machine (`skills/freya-code-graph/scripts/settings.py:65`–`68`).

Writing the answer down:

```
freya code-graph --use <backend>            # this project's knowledge-base/settings.json
freya code-graph --use <backend> --global   # ~/.freya/settings.json
freya code-graph --use auto --global        # clears the machine default
```

At machine scope `auto` is not an answer but the absence of one, so `--use auto --global`
deletes the key rather than writing it — the only way to un-answer the install-time question
(`skills/freya-code-graph/scripts/settings.py:453`, `settings.py:474`).

The name is validated against the registry at the moment somebody is present to be told they
typed it wrong (`skills/freya-code-graph/scripts/graph_ops.py:2943`), and the project-scope
message asks for the file to be committed so a clone, a colleague and CI all resolve the same
backend (`skills/freya-code-graph/scripts/graph_ops.py:2978`). The machine-scope message is
careful about what it promises: a project already carrying its own answer keeps it
(`skills/freya-code-graph/scripts/graph_ops.py:2972`).

The first `--build` or `--update` in a project that has not decided copies the machine's answer
into that project's own committed settings
(`skills/freya-code-graph/scripts/graph_ops.py:3104` → `graph_ops.py:2896` →
`skills/freya-code-graph/scripts/settings.py:506`), validating it against the registry on the
way. A headless run with nothing configured writes nothing. Nothing verifies that the seeded
file is actually committed — the build prints one line asking for it
(`skills/freya-code-graph/scripts/graph_ops.py:2920`) and that is the entire mechanism; ADR-019
states this gap rather than implying enforcement.

Measured on this worktree on 2026-08-21, `knowledge-base/settings.json` reads — this copy was
written by the run and is not committed on any branch here:

```json
{
  "substrate": {
    "backend": "graphify"
  }
}
```

## External binaries

| Binary | Required? | Looked up at | Run at | Absent ⇒ |
|---|---|---|---|---|
| `python3` / `python` (≥ 3.9) | **yes**, to install | `install.sh:16`, `install.ps1:12` | same | install.sh exits 1 with "no Python 3.9+ found on PATH" |
| the running interpreter | **yes** | `sys.executable` | `bin/freya_cli.py:124` | n/a — never depends on a bare `python` being on PATH |
| `git` | for update, and for accuracy elsewhere | `shutil.which`, `bin/updater.py:158` | nine sites, e.g. `bin/updater.py:60` | `freya update` refuses with a distinct message; graph/status/spec commands degrade |
| `graphify` | **no** — opt-in | `shutil.which`, `skills/freya-code-graph/scripts/backend_graphify.py:309` | `skills/freya-code-graph/scripts/backend_graphify.py:419` | build degrades to the floor and records that it did |
| `claude` / `copilot` | **no** — only `freya security` | `shutil.which`, `skills/freya-codebase-security-scan/scripts/audit_adapter.py:114` | `skills/freya-codebase-security-scan/scripts/audit.py:233` | driver exits 1 and names the fallback (`audit.py:371`) |
| `pnpm` + `vitest` | **no** — only in a target project | not probed | `skills/freya-behavior-runner/scripts/run_behaviors.py:221`, `run_behaviors.py:452` | **the runner raises `FileNotFoundError`** — see below |
| `npm` / `yarn` / `pnpm audit` | **no** — agent-run, no script | not probed | `skills/freya-dependency-vulnerability-check/SKILL.md:57`, `skills/freya-dependency-vulnerability-check/SKILL.md:62`, `skills/freya-dependency-vulnerability-check/SKILL.md:67` | the skill has nothing to read |

Python 3.9+ is the floor, not "any Python 3"
([STYLE_GUIDE.md § Target CPython 3.9](STYLE_GUIDE.md#target-cpython-39)). What is
environment-shaped about it: `bin/freya:19` checks the version *before* importing any suite
module, so an interpreter too old to run the toolkit can still print the reason rather than
dying in a file the user never named (`bin/freya:12`).

`git` is used well beyond `freya update`. Counted 2026-08-21, `["git", ...]` appears as the
argv of nine `subprocess` calls across `bin/updater.py:60`,
`skills/freya-code-graph/scripts/graph_ops.py:524` and `graph_ops.py:562`,
`skills/freya-code-graph/scripts/backend_graphify.py:680`,
`skills/freya-behavior-graph/scripts/behavior_graph.py:518`,
`skills/freya-behavior-runner/scripts/run_behaviors.py:436`,
`skills/freya-spec-manager/scripts/drift.py:69`,
`skills/freya-spec-manager/scripts/verify_intent.py:47` and
`skills/freya-status/scripts/collect_status.py:33`. Every one treats a missing git as an answer
rather than a crash — `run_behaviors.py:440` catches `FileNotFoundError` and returns
`"unknown"`, `behavior_graph.py:522` returns an empty change list — so the toolkit degrades
rather than failing when git is absent.

**The unit-behavior runner is the one place where a missing binary is not handled.** It
hardcodes `["pnpm", "vitest", "run", ...]`
(`skills/freya-behavior-runner/scripts/run_behaviors.py:221`) and calls it with no exception
handler (`run_behaviors.py:452`). A failing *test* is handled properly — the fingerprint comes
back with `reason="test-failed"` and coverage is never faked (`run_behaviors.py:453`–`456`).
A missing *`pnpm`* is not: `FileNotFoundError` propagates through `fingerprint_behavior`
(`run_behaviors.py:635`) and `main` (`run_behaviors.py:684`) and ends the run in a traceback,
and because `behavior-graph` invokes the runner with `check=True`
(`skills/freya-behavior-graph/scripts/behavior_graph.py:211`) the whole `behavior.json` build
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

Installing it, as printed by the install-time prompt (`bin/backend_setup.py:49`–`51`):

```
uv tool install "graphifyy[sql,terraform]"      # or: pip install "graphifyy[sql,terraform]"
freya code-graph --use graphify --global
```

The distribution name really is `graphifyy` with two y's while the command it installs is
`graphify` — confirmed on this machine on 2026-08-21: `uv tool list` reports
`graphifyy v0.9.47` providing `graphify` and `graphify-mcp`, and `graphify` resolves to
`~/.local/bin/graphify`. The `[sql,terraform]` extras matter: graphify declares `.sql`, `.tf`
and `.tfvars` unconditionally but only parses them when those grammars are installed, so
without the extras the extension census would affirm that nothing went unread while the graph
held no nodes for them (`bin/backend_setup.py:42`–`47`).

**What happens when it is absent.** Nothing fails — the build degrades to the floor and records
that it did. `available()` is a bare `PATH` check and deliberately costs no subprocess
(`skills/freya-code-graph/scripts/backend_graphify.py:309`), so an incompatible release is
selected and then degrades rather than being refused up front. One degrade path is specific to
this binary: a run that exceeds the 900-second timeout
(`skills/freya-code-graph/scripts/backend_graphify.py:52`, `backend_graphify.py:424`–`426`).
The reasons a degrade can carry are tabulated in
[TROUBLESHOOTING.md § The build used `homegrown`](TROUBLESHOOTING.md#the-build-used-homegrown-when-settingsjson-says-graphify).

**What it writes.** `graphify update <project>` puts its extraction (`graph.json`), an HTML
viewer (`graph.html`), a report (`GRAPH_REPORT.md`), a manifest and a cache in
`graphify-out/` at the project root — measured on 0.9.47, over two runs, it keeps no dated
backups, though `backend_graphify.py:265` and `graph_ops.py:1149` still say it does. That
directory is outside `knowledge-base/`, which is
the only place this toolkit's own ignore rules reach. The backend therefore writes
`graphify-out/.gitignore` containing `*` after the tool has run
(`skills/freya-code-graph/scripts/backend_graphify.py:278`, `backend_graphify.py:386`),
leaving a hand-edited marker alone. freya reads only `graphify-out/graph.json`
(`skills/freya-code-graph/scripts/backend_graphify.py:47`, `backend_graphify.py:48`,
`backend_graphify.py:383`). This repository also ignores `graphify-out/` in its own root
`.gitignore`.

**Measured difference on this checkout, 2026-08-21.** Both per-backend graphs are present under
`knowledge-base/.graph/` (ADR-028 keeps one per backend so a swap can be diffed). Counting
`files` entries and the declared coverage in each artifact:

| | `graph.homegrown.json` | `graph.graphify.json` |
|---|---|---|
| files in the graph | 62 | 65 |
| declared languages | 4 | 40 |
| declared extensions | 6 | 93 |

Neither carries `degraded_from`. This is a different measurement from ADR-019's "68 of the 90
in-scope files", which is a *declared-coverage census* taken at commit `2762d54`; the numbers
above are file entries in the graphs as built here.

## Credentials

freya-devkit reads no API key, token or password. The audit driver is the only component that
touches a credentialed service, and it does so by spawning another vendor's CLI — `claude` or
`copilot`, whichever is found first
(`skills/freya-codebase-security-scan/scripts/audit_adapter.py:102`,
`audit_adapter.py:108`, `audit_adapter.py:111`). freya passes no `env=` to `subprocess.run`
(`skills/freya-codebase-security-scan/scripts/audit.py:233`), so each worker inherits the full
parent environment, including anything credential-shaped that happens to be in it.

The code's assumption is that the CLI uses its own stored login: `Health` exists precisely
because "an expired login, a bad `--model` or a missing `--project` produce a run of empty
finders that is indistinguishable from a clean codebase"
(`skills/freya-codebase-security-scan/scripts/audit.py:110`), and the run is reported as
INCOMPLETE rather than clean when tasks go unanswered.

[TODO: Is an ambient credential in the environment (e.g. `ANTHROPIC_API_KEY`, `GH_TOKEN`) a
supported way to authenticate audit workers, or is the agent CLI's own stored login the only
sanctioned path? The driver inherits the whole environment either way, and nothing in the repo
records a policy.]

Two properties of the workers are enforced rather than assumed, and both are about capability
rather than credentials: every argv is an explicit read-only allowlist, and `build_argv` refuses
to emit a blanket permission flag even if one is smuggled in through the prompt
(`skills/freya-codebase-security-scan/scripts/audit_adapter.py:25`, `audit_adapter.py:34`,
`audit_adapter.py:45`). The reason is recorded at
`skills/freya-codebase-security-scan/scripts/audit_adapter.py:7`:
`--allow-all-tools --deny-tool=write` still let a worker create a file with a shell redirect.

## Configuration files

| Path | Written by | Committed? | Purpose |
|---|---|---|---|
| `~/.freya/settings.json` | `freya install` / `freya update` prompt, `--use --global` | outside every repo | machine-level backend + symbols default |
| `~/.freya/update-check.json` | `bin/updater.py:470` | outside every repo | update-check throttle stamp (`checked_at`, `behind`) |
| `knowledge-base/settings.json` | `freya code-graph --use`, or by hand | **meant to be committed**; untracked in this checkout | this project's backend and directory verdicts |
| `knowledge-base/.graph/.gitignore` | `code-graph --build` | committable — not ignored, but never yet committed in this repo | ignores the parse cache by name, leaving `behavior.json` committable |
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
