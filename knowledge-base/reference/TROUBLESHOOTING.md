# Troubleshooting

> Last updated: 2026-08-24

Every entry below is traced to an error path in the code or to a defect recorded in
[`roadmap.md`](../roadmap.md). Nothing here is a hypothetical failure: if a symptom could not be
produced from a real `raise`, `print(..., file=sys.stderr)` or a measured run in this checkout,
it was left out.

Two commands answer most questions before you read any further:

```bash
freya doctor                                  # the installation
freya code-graph --build --dir . --format summary   # the graph, and what it could not read
```

`doctor` prints one row per check and exits 1 only if a row says `FAIL`; a `warn` row does not
fail it (`bin/freya_cli.py:542`–`:548`). The full row table is in
[DEPLOYMENT.md § `freya doctor`](DEPLOYMENT.md#freya-doctor).

## Common Issues

### Installation and the launcher

#### `freya: command not found`

**Symptom.** A SKILL.md step, or anything you type at a shell, fails with
`freya: command not found` (POSIX) or `'freya' is not recognized …` (Windows). No skill can do
anything, because `freya <command>` is the only way any bundled script is invoked (ADR-013).

**Confirm.** `command -v freya`. Then run the diagnostic without needing the launcher at all:

```bash
python3 <store>/bin/freya_cli.py doctor
```

That route is supported — `bin/freya_cli.py:626`–`:636` exists so a user whose launcher is not
on `PATH` can still reach `doctor` (without the `__main__` guard it printed nothing and exited
0, which reads as a clean bill of health).

**Fix, per install path.**

- **`install.sh` / `install.ps1`.** The launcher goes to `~/.local/bin/freya`
  (`bin/installer.py:521`). The installer never edits your shell profile; it detects that the
  directory is absent from `PATH` (`bin/installer.py:524`) and prints the correct line for the
  platform (`bin/installer.py:534`, `:969`). Add it and reload the shell. A stock macOS never
  has `~/.local/bin` on `PATH`, and Debian/Ubuntu's `~/.profile` only adds it if the directory
  existed at login — which it may not have until the installer created it.
- **Claude Code plugin.** No `PATH` step is meant to be needed: the host adds each installed
  plugin's own `bin/` to the session `PATH`. That behaviour is the host's, undocumented, and
  nothing in this repo tests it. ADR-013 § Revisit Conditions still says `freya doctor`
  "structurally cannot check" it; that is stale — the `freya on PATH` row reports whichever
  launcher `shutil.which` resolves, from any store and without going through the launcher it
  is reporting on (`bin/freya_cli.py:344`–`:356`). What no check covers is *why* the entry is
  there. Measured again in this checkout on 2026-08-21: `doctor` found
  `~/.claude/plugins/cache/freya-devkit/freya-devkit/0.2.0/bin/freya` on `PATH`, so the
  convention still holds here. If it ever stops, the remedy needs no new code — clone the repo
  and run `install.sh`, which puts the launcher somewhere you control.
  [TODO: which Claude Code releases add `<plugin-cache>/<plugin>/<version>/bin` to `PATH`?
  Observed on 0.1.0 (2026-08-18, ADR-013) and on 0.2.0 (2026-08-21), both on macOS. Nothing
  pins a version range, and no other host has been checked.]
- **Windows.** `bin/freya` ships without an extension, and cmd.exe and PowerShell resolve a
  bare name through `PATHEXT`, which does not include "no extension". Only the installer writes
  the `freya.cmd` shim beside the launcher (`bin/installer.py:575`), so a plugin install on
  Windows leaves `freya` unrunnable by name. Use `install.ps1` there regardless of how the
  skills were obtained.
  [TODO: on Windows, does an agent-spawned shell resolve `freya` through the generated
  `freya.cmd`? No live agent run has ever happened on that platform — CI proves the install,
  the launcher and the uninstall, and nothing more (roadmap.md § Platform-blocked). This entry
  is derived from the code, not observed.]

#### `doctor` says the `freya` on `PATH` is a different copy

**Symptom.** A `warn` row like this one, taken verbatim from this checkout on 2026-08-21:

```
[warn] freya on PATH: /Users/…/.claude/plugins/cache/freya-devkit/freya-devkit/0.2.0/bin/freya
       — a different copy than the suite above (/Users/…/freya-devkit-dogfood).
       `freya <cmd>` in a shell runs that one; this checkout only runs via its own ./bin/freya.
```

**Why it matters.** `shutil.which("freya")` finding *a* launcher is not the same as it finding
*this* one (`bin/freya_cli.py:344`). In a healthy install the `PATH` entry is a symlink into the
store, so its realpath is under the store root; when it is not, every other row doctor printed
describes a tree the shell will not execute (`bin/freya_cli.py:351`–`:356`). This row was added
after running `./bin/freya doctor` from a checkout while the released plugin was on `PATH`
reported green.

**Confirm.** `command -v freya` and compare with the `suite root` row.

**Fix.** Decide which store is authoritative. Run the one you mean explicitly (`./bin/freya …`
from the checkout), or reinstall from it. If both a plugin install and a personal install are
present, doctor says so separately (`bin/freya_cli.py:520`–`:538`) — and it compares presence
only, never versions. Two different checkouts registered at once is how a SKILL.md from one
comes to invoke a `freya` command the other's `bin/commands.json` does not have; the only
symptom is `freya: unknown command`.

#### `freya: unknown command '<name>'`

**Symptom.** Exit 2 and `freya: unknown command 'wrap-up'` (or `docs-manager`, `spec-manager`,
…).

**Confirm.** `freya help` lists the manifest commands and the built-ins. There are 17 manifest
entries in `bin/commands.json` and 6 command names `main` dispatches itself — `help`, `doctor`,
`init`, `install`, `update`, `uninstall`. The frozenset at `bin/freya_cli.py:26` holds 8 entries
because `-h` and `--help` are aliases of `help`.

**Fix.** Usually nothing is broken: `wrap-up` is a *skill*, not a CLI command, and the launcher
says so rather than leaving you to guess — it looks the name up as `freya-<name>` in the store
and points you at your agent (`bin/freya_cli.py:604`–`:616`). If the name genuinely is a
manifest command, you are running a different store than the SKILL.md came from; see the
previous entry.

#### `freya: '<name>' is registered but its script is missing`

**Symptom.** Exit 2, with the resolved path in the message and a pointer to `doctor`.

**Confirm.** `freya doctor` — the `scripts` row lists every manifest target that does not exist.

**Fix.** This is the shape a half-applied update or a pruned `--copy` install leaves
(`bin/freya_cli.py:163`–`:172`). Re-run `freya update`, or `install.sh --force` from the store.
Without this branch you would see CPython's own "can't open file" error, which never mentions
freya and exits 2 — the same code as an unknown command.

#### `freya update` refuses and exits 2

**Symptom.** One line beginning `freya update:` and nothing merged.

**Confirm.** The message names the precondition. All of them are checked before anything is
fetched (`bin/updater.py:316`–`:320`): git cannot be run, the store is not a git checkout, the
branch has no upstream or tracks a local branch, or the tree is dirty. After the fetch there are
two more: the remote could not be reached (`bin/updater.py:346`–`:350`) and the store has
diverged, since update only fast-forwards (`bin/updater.py:354`–`:358`).

**"git cannot be run" now has three spellings, and two of them are new.** The precondition asks
`git_program()` — the same body `git()` spawns from and `doctor` prints from, so a precondition
cannot pass on a git the spawn would then refuse (`bin/updater.py:275`). On the common path the
message is byte-identical to the old one, `git is not on PATH`. The two others are a resolution
that is not absolute, and:

```
freya update: the store is incomplete: skills/freya-code-graph/scripts/exec_path.py could not
be loaded, and it is what decides which git is safe to run. Re-clone the repository, or restore
the file with `git checkout -- skills/`
```

That last one is the guard against a damaged skill tree (`bin/updater.py:86`), and it is
deliberately a refusal rather than a fallback: there is no degraded resolver and no bare-`"git"`
path, because a damaged tree is exactly when "just search `PATH`" looks like graceful
degradation. It says "could not be loaded" rather than "is missing" on purpose — the guard
catches a *corrupt* `exec_path.py` as well as an absent one, and telling someone a file is
missing when they can see it sends them to look for the wrong problem.

**Fix.** Reconcile the store with git yourself and run it again — a merge commit or a rebase in
your toolkit checkout is a surprise the updater will not create for you. `freya update
--dry-run` reports what would happen and writes nothing.

**And then reload your agent session.** Agents read their skill list once, at session start, so
an update applied mid-task is invisible until the session reloads: a new skill will not appear,
and a renamed or removed one keeps being offered and then fails on use. `freya update` prints
this reminder whenever it actually moves the store (`bin/updater.py:372`).

#### `freya install --force` silently turned a `--copy` install into symlinks

**Symptom.** `doctor`'s `agents` row changes from `claude (10, copy)` to `claude (10, symlink)`
after repairing an orphaned install.

**Why.** `install.sh --force` without `--copy` replaces copy directories with links. That is
what the flags ask for, but the remedy string that sends people there — "the checkout moved;
re-run `freya install --force`" (`bin/freya_cli.py:414`–`:453`) — carries no mode warning, and
`--copy` is the *normal* mode on Windows. Roadmap item 5.

**Fix, and the trap in it.** Re-running `install.sh --copy --force` does **not** convert back. A
symlink that points at this store classifies as `ok` (`bin/installer.py:153`–`:160`), and
`apply_plan` skips every `ok` entry before the copy/link decision is ever made
(`bin/installer.py:333`–`:335`). Uninstall first, then install with `--copy`:

```bash
freya uninstall
./install.sh --copy
```

#### `freya init` refuses to touch `AGENTS.md`

**Symptom.** `AGENTS.md has a malformed freya-devkit block (an unpaired, reversed, or duplicated
marker) — fix or delete it, then run 'freya init' again.`

**Confirm.** Search the file for the two HTML comment markers. The block is located only when a
marker appears exactly once at the start of a line; unpaired, doubled or out of order all fail
the same way (`bin/agents_md.py:241`–`:244`). Both markers absent is not a failure — that is a
first install, and the block is appended (`bin/agents_md.py:230`–`:237`).

**Fix.** Delete the malformed block by hand and re-run. The refusal is deliberate — guessing
where a half-written block ends is how the rest of a hand-maintained `AGENTS.md` gets eaten. A
marker merely *shown* in prose or inside a fenced code block is ignored and is not the cause.

#### A skill loads on Claude Code and is invisible on Copilot

**Symptom.** No error anywhere. The skill is installed, linked, and simply never offered by one
host.

**Confirm.** Run the conformance gate: `python3 bin/check_skill_conformance.py`. Rule **R10**
reports any frontmatter value over its spec limit — `description` 1024, `compatibility` 500,
`name` 64 (`bin/check_skill_conformance.py:60`, checked at `:399`–`:405`).

**Fix.** Shorten the value. This is not a theoretical limit: phase 6 validation found GitHub
Copilot silently omitting a skill whose `description` ran to 1251 characters while Claude Code
loaded it happily (`bin/check_skill_conformance.py:55`–`:60`). `description` is the only thing a
host matches a request against, so an over-long one makes the skill unreachable rather than
degraded.

#### The conformance gate fails on `freya uninstall`

**Symptom.** `R3 — unknown freya command` on a line that documents a command that works.

**Confirm.**

```bash
python3 -c "import sys; sys.path.insert(0,'bin'); \
import check_skill_conformance as c, pathlib; \
print('uninstall' in c.load_allowed_commands(pathlib.Path('.')))"
```

Prints `False` in this checkout.

**Fix.** None available in a skill — this is a defect in the gate, not in your SKILL.md. The
allowed set is the union of `bin/commands.json` and `BUILTIN_COMMANDS`
(`bin/check_skill_conformance.py:483`–`:488`), and `BUILTIN_COMMANDS` at
`bin/check_skill_conformance.py:20` lists only `install`, `update`, `doctor`, `init`, `help`,
while `bin/freya_cli.py:26`–`:27` also ships `uninstall`. Until the list is corrected, avoid
writing `freya uninstall` inside a code span under `skills/`. Roadmap item 2.

### The code graph

#### The graph is empty, or much smaller than the repository

**Symptom.** `files_scanned` is a fraction of what you expect, or `--impact` on a file you just
changed returns nothing.

**Confirm.** Read the artifact's own account of itself. Three fields answer three different
questions:

```bash
python3 - <<'PY'
import json
g = json.load(open('knowledge-base/.graph/graph.json'))
s = g.get('substrate', {})
print('backend        ', s.get('backend'))
print('degraded_from  ', s.get('degraded_from'), s.get('degraded_reason'))
print('unmapped_source', s.get('unmapped_source'))
print('files          ', len(g.get('files', {})))
PY
```

- **`degraded_from` is set.** The project asked for a backend and did not get one. That is
  abnormal — see the next entry.
- **`unmapped_source.files` is a positive number.** The backend the project *chose* cannot read
  some of the repository. This is the floor's ordinary condition on a polyglot repository, not a
  fault (ADR-029). The block names the extensions and, more usefully, the directories to grep
  instead; `rollup_directories` collapses each tree to one search target rather than four.
- **`unmapped_source` is `{"files": 0, …}`.** The census ran and found nothing material. That is
  what this repository published on both backends when it was last measured — 2026-08-21,
  `graph.homegrown.json` (62 files) and `graph.graphify.json` (65 files) both carrying
  `{"files": 0}`. Both artifacts are gitignored and absent from a fresh clone, so rebuild before
  comparing your own figure against those.
- **`unmapped_source` is `{"files": null, "error": …}`.** The census itself failed. It is never
  reported as a zero, because a silent zero is indistinguishable from "this backend read
  everything" (`skills/freya-code-graph/scripts/substrate.py:994`–`:997`).
- **The key is absent entirely.** The artifact predates the census; rebuild.

The block reaches each command in the shape that command can carry. `--build` and `--update`
carry it whole, including a prose `advice` sentence
(`skills/freya-code-graph/scripts/substrate.py:1025`, announced once on stderr at
`skills/freya-code-graph/scripts/graph_ops.py:2652`–`:2655`); `--query` and `--impact` carry a
digest; `--dependents` and `--dependencies` keep their bare JSON arrays and say the same thing on
stderr (`graph_ops.py:3106`–`:3134`). `--format summary` prints a `NOT GRAPHED:` line.

**Fix.** If the files named are ones you need edges for, switch backends (below). If the census
is silent but you know a language is missing, the tier lists are closed-world by design
(`substrate.py:867` for tier 1, `:894` for tier 2): an extension nobody listed produces silence.
Tier-2 extensions — `.sh`, `.sql`, `.ps1` — are reported only when their count beats both the
graphed file count and a floor of 2 (`substrate.py:902`, `:926`–`:950`), so a handful of build
scripts under a large graphed tree are deliberately not reported. Both are recorded revisit
conditions in ADR-029, not oversights.

**A caveat is never a refusal.** Nothing declines to answer, changes an exit code or takes a gate
red because of `unmapped_source`, and the rule is written into the code beside the one refusal it
must not join (`skills/freya-behavior-runner/scripts/run_behaviors.py:593`–`:604`). If you find
yourself "fixing" a run by making it refuse on blind spots, read that comment first: it would
return `coverage: unknown` for every confirmed and integration behaviour on every polyglot repo,
and wrap-up's gate would then run zero behaviours and exit 0.

#### `--impact` answers `all_affected: []` for a file you changed

**Symptom.** An empty blast radius that reads as "nothing depends on this".

**Confirm.** The answer says which of the two it is, in the payload and on stderr. Measured in
this checkout on 2026-08-21:

```
$ freya code-graph --impact bin/does_not_exist.java --dir .
code-graph: 1 of 1 file(s) given to --impact are not in the graph (bin/does_not_exist.java).
They contribute no blast radius — which is not the same as having none.
{ … "all_affected": [], "not_in_graph": ["bin/does_not_exist.java"] }
```

`not_in_graph` is in the JSON, not only on stderr, because the caller is usually another skill
reading `--format json` (`graph_ops.py:2488`–`:2501`).

**Fix.** A non-empty `not_in_graph` means the file is not a node: either the backend cannot read
its extension (see `unmapped_source` above), or the path is excluded by the build's scope rule
(`graph_ops.py:1391`), or the graph is stale. Rebuild, then check `unmapped_source`, then check
`knowledge-base/settings.json` for a directory verdict that excludes it.

#### The build used `homegrown` when `settings.json` says `graphify`

**Symptom.** One line on stderr —
`code-graph: 'graphify' unavailable (not installed) — using 'homegrown' instead, with reduced
coverage` — and `substrate.degraded_from` set in the artifact
(`skills/freya-code-graph/scripts/backends.py:53`–`:56`, printed at `graph_ops.py:3495`–`:3496`).

**Confirm.** Read `substrate.degraded_reason`. It distinguishes two mistakes deliberately
(`backends.py:139`–`:150`):

| `degraded_reason` | What it means | Fix |
|---|---|---|
| `not installed` | The name is a real backend that did not report itself **usable**. For `graphify` that is now `exec_path.resolve('graphify', project_dir)` returning no path (`skills/freya-code-graph/scripts/backend_graphify.py:318`), which covers three different situations — see below | Install it, accept the floor, or read the next paragraph |
| `unknown backend` | The name is not a backend at all. `--use` refuses unknown names, so this only reaches a hand-edited `settings.json` | Correct the file |
| `does not satisfy the substrate contract: …` | A registered backend failed the structural check and was not used (`graph_ops.py:3475`–`:3493`) | Report it; the floor ran instead |
| `failed during the build: …` | The backend was selected, then threw (`graph_ops.py:2720`–`:2745`) | Usually the wrapped tool was upgraded |

**`not installed` no longer means only "not on `PATH`".** Since the binary is resolved rather
than searched, the same reason string covers three states, and the third is the one that will
surprise you:

1. `shutil.which` found nothing — the ordinary case, and the fix is to install it.
2. The resolution is **not an absolute path**. On Windows CPython's `shutil.which` inserts the
   working directory at the head of the search path, so a `graphify.exe` in the repository you
   pointed freya at is found first and then refused. That is the intended outcome, not a
   malfunction: the binary the *operator* installed is not the one that was found. On Windows
   with Python 3.9–3.11 the opt-out that would remove the working directory from the search is
   ignored, so this is the only control on that leg —
   [SECURITY.md § The one accepted regression](SECURITY.md#the-one-accepted-regression-windows-on-python-39-311).
3. The resolution is **inside the project being analysed**. Same reasoning, on every platform:
   `containment.within` resolves both sides, so a `bin/graphify` symlink inside the repository
   that points at another file inside it is still the repository's binary
   (`skills/freya-code-graph/scripts/exec_path.py:95`). A symlink pointing *out* of the
   repository is deliberately not refused — that file is one the machine already had.

To tell them apart, ask the resolver directly rather than guessing:

```bash
python3 -c "import sys; sys.path.insert(0, 'skills/freya-code-graph/scripts'); \
import exec_path; print(exec_path.resolve('graphify', '.'))"
```

A `Resolution(path=None, reason=…)` prints the sentence the refusal would have used. The same
call with `'claude'` or `'copilot'` answers the audit driver's version of this question.

**Fix.** A degraded graph is not just thinner — it makes `behavior-runner` refuse to compute a
static closure at all, returning `unknown` with the reason rather than committing a narrower
closure into `behavior.json` (`run_behaviors.py:581`–`:592`). So this is worth resolving rather
than living with. Related: a wrong-*typed* value (`{"backend": 42}`) is not a degradation, it is
ignored with a warning on stderr and `auto` is used instead
(`skills/freya-code-graph/scripts/settings.py:716`–`:724`).

**If nothing at all is available**, selection raises rather than promoting something else:
`no code-graph backend is available, not even 'homegrown' — this should be impossible, since it
is stdlib-only. Check the installation.` (`backends.py:127`–`:130`). That means the install is
broken, not that a backend is missing.

#### The machine default does not apply to a project

**Symptom.** `freya code-graph --use graphify --global` had no effect in a repository.

**Why.** Precedence is project, then machine, then floor
(`skills/freya-code-graph/scripts/settings.py:727`–`:738`), and the first build in a project that
has not decided *records* the machine answer in that project's own
`knowledge-base/settings.json` (`graph_ops.py:3351`–`:3378`). Once recorded, the project file
wins and changing the machine default later does not reach back into it.

**Fix.** `freya code-graph --use <backend>` inside the project. And commit
`knowledge-base/settings.json` — the build prints one line asking you to, and nothing verifies
that you did; that line is the entire mechanism (`graph_ops.py:3375`–`:3378`). A project that
leaves the choice implicit graphs differently on different machines.

#### A key in `~/.freya/settings.json` is ignored

**Symptom.** A setting written into the machine-level file has no effect anywhere.

**Why.** Only `substrate.backend` and `substrate.symbols` are honoured at machine level
(`skills/freya-code-graph/scripts/settings.py:102`). `directories` is excluded on purpose: a
global `docs: source` would apply to repositories nobody has looked at, and a global
`node_modules: source` is a 50,000-file graph on every project on the machine
(`settings.py:98`–`:101`).

**Confirm.** Anything else is dropped **and reported on stderr**, not silently honoured
(`settings.py:619`); a wrong-typed value is reported the same way rather than quietly defaulted
(`settings.py:636`–`:643`). Read the stderr of any `code-graph` command.

**Fix.** Put the setting in the project's own `knowledge-base/settings.json`, which accepts
`substrate.*` and `directories.*`. See
[ENVIRONMENT.md § The machine file and the project file](ENVIRONMENT.md#the-machine-file-and-the-project-file).

#### The build refuses: "produced 0 files where the cached graph has N"

**Symptom.**

```
code-graph: produced 0 files where the cached graph has 65; refusing to overwrite it
  The previous graph is kept. If the codebase really is empty now, or the exclusions are
  intentional, run --clear first.
```

Exit 1, and the previous artifact is untouched (`graph_ops.py:2694`–`:2717`, presented at
`:3573`–`:3584`).

**Confirm.** The ordinary causes are a directory verdict committed to
`knowledge-base/settings.json` that excludes the whole source tree — `{"directories": {"src":
"exclude"}}` — or every source file having genuinely been removed. Nothing else catches this:
an empty `files` dict passes validation, because there is no edge to be wrong about.

**Fix.** Remove the over-broad exclusion, or, if the emptiness is real, `freya code-graph --clear`
and rebuild. Do not "fix" the refusal itself: it exists because a backend that silently stops
working otherwise writes a successful-looking empty graph over a good one and reports
`status: built`, after which every skill downstream reports a repository with no code in it.

#### After switching backends

**Symptom.** Blast radius changed everywhere at once, with no diff to point at.

**What actually happens.** Every build is written twice, so a swap leaves the previous backend's
graph intact at its own path —
[ARCHITECTURE.md § The graph substrate](ARCHITECTURE.md#the-graph-substrate) has the two
artifacts and ADR-028 the reasoning. What matters here is that the diff is yours to run.

**Confirm — the diff is run by hand.** **Nothing in the toolkit reads
`graph.<backend>.json`.** There is no `compare` subcommand, and the incremental path does not
warm-start from it either: a graph produced by a different backend forces a full rebuild rather
than splicing one resolver's edges into another's (`graph_ops.py:2226`–`:2237`). What ADR-028
buys is a preserved baseline, not an automated comparison. Compare the two file sets and edge
sets yourself; the direction that matters is *narrowing* — edges the old backend found and the
new one does not shrink a behaviour's static closure and can let a regression through wrap-up's
gate unflagged.

Nothing checks the copy's freshness either, so a comparison will happily diff today's graph
against one produced weeks ago and report the difference as a substrate effect. Check both
artifacts' `commit` and `timestamp` before believing a diff.

**Fix / expectations.** `freya code-graph --clear` removes the active graph **and** every
`graph.*.json` beside it (`graph_ops.py:2512`–`:2534`) — a clear that knew about only one of the
two would leave a complete, current-looking graph that nothing would ever report as stale. Copies
accumulate one per backend name ever used and nothing prunes them; a renamed backend orphans its
old file under the old name forever.

For what the swap actually bought on this repository — +6 real cross-skill edges, −1 false
positive, −389 `external:` edges (42 distinct `external:` nodes, none of which graphify emits)
— see roadmap item 16. The honest summary there is that graphify's 40 languages buy almost
nothing on a Python repo; what they bought was correct resolution of imports crossing a
`sys.path` boundary.

#### An `outside` declaration has no effect, or is reported as refused

**Symptom.** A `knowledge-base/settings.json` carrying `{"outside": {"ui": "../packages/ui"}}`
either does nothing, or the build prints a line on stderr beginning
`knowledge-base/settings.json: outside.ui: '…'` and ending `; ignored`.

**Confirm.** Read that line — it carries the value it turned away and the reason. Every per-alias
refusal is emitted through one helper (`skills/freya-code-graph/scripts/settings.py:466`), drawing
its reason either from the value grammar (`settings.py:364`) or from the checks around it
(`settings.py:472`–`:512`). The table below is the whole list as of 2026-08-24, in the order the
code applies them; it is deliberately not preceded by a count, because a reason added later would
falsify the number and not the table:

| Reason ends with | Means |
|---|---|
| `is not usable as an alias — …` | the key, after `strip()`, is empty or holds a character outside letters, digits, `.`, `_`, `-` (`settings.py:127`) |
| `is not a directory path` | the value is not a non-empty string |
| `starts with ~, …` | `~` names a different directory for every reader, and this file is committed |
| the not-relative message (`_NOT_RELATIVE`, `settings.py:360`) | an absolute path, judged with `containment.escapes` and therefore in **both** path flavours — so `C:\shared` is refused on Linux too |
| `names a directory inside this project; …` | the value has no leading `..` at all, so it never leaves the root — `{"ui": "packages/ui"}`. The code's own note says this clause carries most refusals by count (`settings.py:392`–`:393`) |
| `does not name a directory that exists` | reported rather than silently inert, because a declaration that buys nothing is a typo or a leftover |
| `resolves inside this project; …` | it *does* start with `..` but lands back inside — `../<this repo>/sub`, or a symlink that returns. Put it in `directories` instead: one file must never have two spellings |
| `contains this project, …` | an ancestor is not a scope; point freya at that directory instead |
| `repeats an alias already declared …` | two spellings `strip()` folded together, e.g. `"ui"` and `" ui "` |

Two more lines come from the same section and are *not* in that table, because neither is a
per-alias refusal: `"outside" must be an object; ignoring it` discards the whole section at once
(`settings.py:458`), and the `reaches … through a symlink` line is a notice on a declaration that
was **honoured** (`settings.py:527`).

**A declaration that is in force and still shows `crossings: 0` is not broken.** Two separate
sentences are reported and they answer different questions: a declaration being in force, and
an edge actually crossing. A total of zero says the roots were **not reached**
(`skills/freya-code-graph/scripts/graph_ops.py:2996`) — which is the true statement and the one
that reads as an invitation to check the declaration. Where two roots nest, `../packages` and
`../packages/ui`, the **most specific** one names the file, decided by resolved path length, so
an outer root can honestly report zero while an inner one covers everything it would have.

**On the `graphify` backend a zero is not even a measurement.** Only the floor's own resolver
consults declarations; graphify never looks at them (`graph_ops.py:3006`), so `crossings: 0`
there means the question was never asked. If you have declared a root and want the crossings
recorded, build on `homegrown` — `freya code-graph --use homegrown` — or read the zero as
"unknown" rather than "none".

**And a declared root reached through a symlink is honoured, not refused** — it is named on
stderr instead (`skills/freya-code-graph/scripts/settings.py:527`), because nothing was crossed
implicitly and `../packages -> …` is an ordinary layout. A symlink planted *under* a declared
root that points elsewhere is the other case and is refused.

**Fix.** Correct the value, or accept the refusal. Note that changing the declarations discards
the cached graph and forces a full rebuild on the next `--update`
(`skills/freya-code-graph/scripts/graph_ops.py:2254`), so a declaration edited between two
`freya-wrap-up` runs costs a full build rather than an incremental one. That is deliberate: the
report is recomputed from the settings file while `--update` re-resolves only what git says
moved, and without the rebuild the artifact contradicts itself in both directions.

#### A stale `classifications.json`

**Symptom.** A directory keeps being treated as source (or excluded) after you changed the rules,
edited `knowledge-base/settings.json`, or upgraded — and a rebuild does not shift it.

**Why.** `knowledge-base/.graph/classifications.json` caches per-directory verdicts, and the
builder skips any directory already present there. Three properties matter:

- `--clear` deliberately **does not** remove it: the clear loop unlinks `graph.json` and
  `graph.*.json` and nothing else (`graph_ops.py:2523`, stated at `:2519`). It holds user and
  model judgements about which directories are source, which a cache clear has no business
  discarding.
- A rules change only invalidates part of it. `RULES_VERSION`
  (`skills/freya-code-graph/scripts/graph_ops.py:154`) discards only `rule` and `gitignore`
  verdicts on load (`graph_ops.py:1609`–`:1613`); `user` and `ai` verdicts survive on purpose.
  The commonest label in a non-TTY run is `auto-source-default` (`graph_ops.py:1869`), which is
  not a judgement either and survives every rules bump anyway — roadmap item 11a, cache-only, no
  effect on graph output.
- Verdicts declared in `knowledge-base/settings.json` are folded over the cache on load and are
  never written back into it (`graph_ops.py:1624`–`:1638`). That is the fix for a real defect:
  they used to be persisted as ordinary `user` entries and then outlived the file that declared
  them, so deleting a verdict from `settings.json` changed nothing.

**Confirm.**

```bash
python3 -c "import json; d=json.load(open('knowledge-base/.graph/classifications.json')); \
print(d.get('rules_version')); print(json.dumps(d['directories'], indent=2))"
```

**Fix.** Record the verdict you want in `knowledge-base/settings.json`, where it outranks every
rule and is committed. To reset the cache there is no command — delete the file. It is
regenerable, and `.graph/.gitignore` already names it, so nothing is lost from git.

### Documentation, status and specs

#### `docs.json` has documents and no edges

**Symptom.** `freya docs-graph --build --format summary` reports documents parsed and `0` edges,
and "which docs now lie about this file?" has no answer.

**Confirm.** The summary says which of the two causes it is:

```
  no code graph found — every citation was discarded, because there was nothing to check a
  path against
```

(`skills/freya-docs-manager/scripts/docs_graph.py:454`–`:456`, from `code_graph_present` at
`:392`.)

**Fix, cause 1 — no code graph.** `load_code_files` returns an empty set when
`knowledge-base/.graph/graph.json` is missing or unreadable
(`docs_graph.py:321`–`:334`), and a citation only becomes an edge if its target is a file the
code graph knows (`docs_graph.py:229`). Build the code graph first, then rebuild the docs graph.

**Fix, cause 2 — the docs cite no code.** Edges come from three deterministic readers only:
fenced code blocks, inline `path:line` citations, and link targets. There is no semantic pass —
it was designed and never built (roadmap.md § The semantic pass for the docs graph), so a project
whose documentation cites no code paths gets a document list with zero edges and no remedy short
of adding citations. This repository is unusually citation-heavy because its own conventions
demand `path:line` provenance: measured 2026-08-21, 48 documents, 1,010 edges, and 5 documents
with no edges at all. That figure has not been re-measured since — `docs.json` is gitignored and
this branch has not rebuilt it — and the citation gate alone now reads well over 1,800
citations, so treat 1,010 as a floor rather than a current count.

**A third cause worth knowing.** Because edges are filtered against the code graph's file set, a
citation to a file the *backend cannot read* is silently discarded. On a repository where
`unmapped_source` is non-empty, missing doc edges and missing code edges have the same root
cause.

#### `coverage gaps` is a large number that never goes down — fixed, and here is what it means now

**Symptom, historical.** `freya status` and the generated `BACKLOG.md` used to report a
coverage-gap count padded with files no behaviour could ever cover. Measured on this repository
on 2026-08-21: 65 reported against 32 actually behaviour-coverable, the other 33 being
test-infrastructure files and shell scripts. `gaps()` subtracted covered files from *every* file
in the code graph, and a behaviour's `exercises` names production code, so a `test_*.py` could
never appear there — every one was a permanent, unactionable entry.

**Resolved.** `gaps()` now filters through `_is_coverable`
(`skills/freya-behavior-graph/scripts/behavior_graph.py:380`, applied at
`behavior_graph.py:497`), which drops three classes a behavior can never name: test files
matched by anchored convention rather than by substring
(`skills/freya-behavior-graph/scripts/behavior_graph.py:362` — the unanchored version of that
idea already shipped once and made `contest.py` look like a test), extensionless scripts and
executables such as `bin/freya` or a `Makefile`, and languages no import system can address.
Roadmap item 15 is struck as resolved by item 18.

**What is still true, and is not a defect.** The filter is applied by `gaps` only.
`surface`'s per-change `recall_gaps` asks the same shape of question with the same noise and is
deliberately left alone, because its answer is advisory per change rather than a tracked census
(`behavior_graph.py:383`). So a wrap-up's validate-on-hit prompt can still name a file the
whole-repo census would not. Read the census as the worklist and the per-change prompt as a
nudge.

#### `BACKLOG.md` lost hand-written content

**Symptom.** Notes added to `knowledge-base/BACKLOG.md` are gone after a `freya status
--write-backlog` or a wrap-up.

**Why.** It is rewritten by full overwrite — the file is opened `"w"` and replaced
(`skills/freya-status/scripts/collect_status.py:346`–`:349`). It is the only markdown file in
the tree that code rewrites wholesale; every other whole-file write is a tool-owned JSON
artifact (`graph_ops.py:2579`, `docs_graph.py:427`, `behavior_graph.py:172`).

**Fix.** Put hand-maintained items in [`roadmap.md`](../roadmap.md), which is why it carries that
name: on a case-insensitive filesystem `backlog.md` is the same path the generator overwrites.

### The security audit driver

#### `freya security scan` exits 1 without scanning

**Symptom**, quoted from the current message
(`skills/freya-codebase-security-scan/scripts/audit.py:391`–`:394`):

```
scan needs an agent CLI on PATH (claude or copilot) and none was usable.
  claude is not on PATH
  copilot is not on PATH
There is no other binary to run: the portable fallback is the freya-codebase-security-scan
skill's own in-loop scan, which the agent performs itself and which is what wrap-up uses.
```

**"none was usable", not "none was found", and the two indented lines are the point.** They are
per-CLI reasons from `program_for`, printed because "not on PATH" is no longer the only way to
reach this branch: a CLI that resolves inside the repository being audited is refused, and an
operator who can see `claude` on their `PATH` has to be told that rather than told it is missing
(`skills/freya-codebase-security-scan/scripts/audit.py:389`). Read the indented line before
reaching for an installer — if it says the resolution is inside the project, or is not an
absolute path, the fix is not to install anything. See the `not installed` breakdown under
[The build used `homegrown`](#the-build-used-homegrown-when-settingsjson-says-graphify), which
is the same resolver answering the same question.

**Confirm.** `command -v claude`, `command -v copilot`. The driver fans out over the six
categories on its own thread pool (`audit.py:303`), each worker shelling out to the agent CLI,
so it needs a headless one; without a usable one the driver exits `EXIT_NOTHING_TO_DO`
(`skills/freya-codebase-security-scan/scripts/audit.py:395`). `--agent claude` does not skip
this: it skips *detection*, and `main()` still resolves the named adapter once before the cost
plan prints, so a refusal costs nothing and arrives explained
(`skills/freya-codebase-security-scan/scripts/audit.py:403`–`:406`).

**Fix.** Nothing to install from this repo. Fall back to the skill's in-loop scan, which is what
`wrap-up` uses anyway.

#### `freya security` exits 4 in an unattended run

**Symptom.** No findings, no work done, exit 4.

**Why.** The confirmation gate refuses to spend money without a TTY rather than defaulting to
yes (`audit.py:448`–`:467`). Exit 4 exists precisely so this cannot be mistaken for "no agent CLI
found": exit 1 used to carry both meanings, and an agent read the table, concluded the CLI was
missing, and silently reverted to a prose fan-out on a machine where the CLI was installed
(`audit.py:63`–`:69`).

**Fix.** Pass `--yes` deliberately, after `--dry-run` shows the cost plan. Note also that a
`--max-calls` ceiling too small to verify anything is refused rather than warned — a
configuration whose only possible output is a false clean bill of health must not be allowed to
run.

### Development and tests

#### Tests pass on one machine and fail on another

**Symptom.** Ten or so failures around backend selection that nobody else can reproduce.

**Confirm.** Check where you invoked pytest from. `conftest.py` points `FREYA_HOME` at a
throwaway directory for the whole session (`conftest.py:26`–`:27`), but it is only collected when
pytest's rootdir is the repository — so `cd skills && pytest .` routes around it entirely and the
suite runs against your real `~/.freya/settings.json` (`conftest.py:14`–`:20`, which records that
ten tests failed exactly that way).

**Fix.** Run pytest from the repository root. Any new test that reads machine-level state should
isolate itself rather than relying on the session net; see
[TESTING.md § FREYA_HOME sandboxing in `setUp`](TESTING.md#freya_home-sandboxing-in-setup).

#### `SyntaxError` from a file you did not name

**Symptom.** An install or a command dies inside a bundled script with a syntax error.

**Confirm.** `python3 --version`. The floor for the whole suite is **3.9**
(`bin/freya_cli.py:238`), not "any Python 3": `search_specs.py` uses PEP 585 builtin generics in
evaluated annotations, which are only subscriptable at runtime from 3.9.

**Fix.** Use a newer interpreter. `install.sh` gates on the same number and refuses with a plain
message rather than starting and failing partway through (`install.sh:16`–`:22`); `freya doctor`
reports the running version in its `python` row.

## Debugging Tips

**Start with the artifact, not the console.** Every agent-driven run is non-interactive —
`code-graph` auto-enables non-interactive mode whenever stdin is not a TTY — and all three
skill-to-skill callers capture stderr and read only stdout on success. A warning printed to
stderr is dead skill-to-skill and alive agent-to-CLI, which is why `degraded_from`,
`unmapped_source` and `not_in_graph` are written *into* the JSON. When something looks wrong,
open `knowledge-base/.graph/graph.json` before reading any log.

**Ask each command for a summary.** `--format summary` exists on `code-graph` and `docs-graph`
and prints the caveats in prose, including the `NOT GRAPHED:` line. It costs nothing and answers
"did this run see my repository?" faster than reading JSON.

**Turn the update notice off while debugging.** `FREYA_NO_UPDATE_CHECK=1` silences the daily
staleness notice on stderr (`bin/updater.py:568`, `:604`), which otherwise interleaves with a
command's own output. It never fires for `help`, `update`, `install`, `uninstall` or `doctor`
anyway (`bin/freya_cli.py:21`). `FREYA_DEBUG=1` prints the traceback from the one code path
designed to fail silently.

**Point machine state somewhere disposable.** `FREYA_HOME` relocates `~/.freya` — both the
machine-level settings file (`skills/freya-code-graph/scripts/settings.py:92`) and the update
throttle stamp (`bin/updater.py:562`–`:566`). Set it to a temp directory to reproduce "a
machine that has never configured anything".

**Two words that are not synonyms.** `degraded_from` means *the project asked for a backend and
did not get one* — abnormal, and grounds for `behavior-runner` to refuse rather than answer
narrowly. `unmapped_source` means *the backend the project chose cannot read everything* — the
floor's ordinary condition on a polyglot repository. Conflating them is the first "fix" a reader
reaches for and it is wrong in both directions; ADR-029 records why.

**A whole class of symptom has one cause.** If docs edges, blast radius and behaviour coverage
all look thin at once, check the graph first. Skills compose through on-disk artifacts, not by
calling each other, so a thin `graph.json` degrades every consumer downstream of it
simultaneously.

## Getting Help

If the symptom is not above, check [`roadmap.md` § Open defects](../roadmap.md#open-defects) —
eighteen numbered entries as of 2026-08-24, numbered 1–18, of which four are struck rather than
deleted so the reasoning survives (7, 9, 15 and 18), leaving fourteen open. Each is verified
against shipped code, and several are the cause of a symptom rather than a coincidence; recount
with `grep -cE '^### (~~)?[0-9]+\.' knowledge-base/roadmap.md` rather than trusting this
sentence. Then run `freya doctor` and include its full output in any
report at [github.com/AlexSendula/freya-devkit](https://github.com/AlexSendula/freya-devkit); it
is the only thing that distinguishes a broken install from a broken repository.

## Related Documentation

- [ENVIRONMENT.md](ENVIRONMENT.md) — environment variables, external binaries, and the machine
  file and the project file
- [DEPLOYMENT.md](DEPLOYMENT.md) — install paths, the `freya doctor` row table, `freya update`,
  and the verified known gaps
- [ARCHITECTURE.md](ARCHITECTURE.md) — the substrate, the shape of an edge, and which paths are
  tool-owned
- [SECURITY.md](SECURITY.md) — why a binary can be refused rather than found, the containment
  predicates, and the one accepted regression on Windows with Python 3.9-3.11
- [DEVELOPER.md](DEVELOPER.md) — the conformance gate, test conventions, and how the launcher
  resolves a command
- [roadmap.md](../roadmap.md) — the single live backlog; every open defect cited above
- [ADR-013](../decisions/ADR-013-single-freya-launcher.md) — one self-locating `freya` launcher,
  and the `PATH` assumption it rests on
- [ADR-019](../decisions/ADR-019-the-floor-and-choosing-a-backend.md) — the floor, and how a
  backend is chosen
- [ADR-028](../decisions/ADR-028-graphs-are-stored-per-backend.md) — why a backend swap leaves a
  baseline on disk
- [ADR-029](../decisions/ADR-029-an-answer-says-what-it-could-not-read.md) — the census, and why
  it is never a refusal
- [ADR-030](../decisions/ADR-030-shared-primitives-live-in-a-skill.md) — where the containment
  and program-resolution primitives live, and why a damaged store refuses instead of searching
- [ADR-031](../decisions/ADR-031-crossing-the-root-is-a-declared-act.md) — the `outside`
  section, what a declaration grants, and what it deliberately does not
