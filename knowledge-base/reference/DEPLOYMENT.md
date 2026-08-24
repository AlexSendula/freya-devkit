# Deployment

How freya-devkit reaches a machine, how it is kept current, and what is published.

> Verified against the working tree at `f407251` (branch `test/dogfood-polyglot`) on
> 2026-08-21. Line citations are that commit's; `docs_graph.py` reads them, so they are
> load-bearing rather than decorative.

There is **no separate infrastructure document and no infrastructure to describe.** GitHub
is the whole of it: the repository is the distribution channel, GitHub Actions runs the two
workflows, and GitHub Pages serves one static site. There is no server, no VM, no database, no
container image, no package registry, no DNS record beyond GitHub's own, and no deployment
secret beyond the `GITHUB_TOKEN` the Pages job is granted for the length of one run. There is
one environment, not a dev/staging/production split: `main` is what the marketplace and Pages
serve, and whatever branch a store tracks is what `freya update` serves. There is nothing to
monitor, because nothing runs anywhere but on a user's machine and on GitHub's runners — the
health surface is `freya doctor`.

## What ships

The product is a **git checkout**. Nothing is built, bundled, compiled, or uploaded to a
registry on the way to a user.

- There is no `pyproject.toml`, `setup.py`, `package.json`, `requirements.txt`, `Makefile`
  or `Dockerfile` anywhere in the tree — checked at every depth on 2026-08-21.
- The only runtime requirement is **Python 3.9 or newer**
  ([STYLE_GUIDE.md § Target CPython 3.9](STYLE_GUIDE.md#target-cpython-39)). What matters at
  install time is that `install.sh:17` and `install.ps1:20` probe candidate interpreters and
  refuse with one line rather than starting and dying partway.
- Nothing under `.gitignore` excludes `bin/` or `skills/`, so what is cloned is what runs.
- **Nothing is configured by environment at install.** The runtime variables are
  [ENVIRONMENT.md](ENVIRONMENT.md).

## Distribution paths

Three, all live at once, all over the same `skills/` tree.

| Path | Entry point | Places | Updates by |
|---|---|---|---|
| Any agent, POSIX | `./install.sh` | Symlinks per skill + `~/.local/bin/freya` | `freya update` |
| Any agent, Windows | `.\install.ps1` | Copies (usually) + `freya` and `freya.cmd` | `freya update` |
| Claude Code only | `/plugin marketplace add AlexSendula/freya-devkit` | Claude's plugin cache | `/plugin marketplace update freya-devkit` |

Both shell entry points are bootstraps and nothing more: `install.sh:18` `exec`s
`bin/installer.py` with the arguments unchanged, and `install.ps1:22` does the same. All
install logic is in one Python file, which is why the two platforms cannot drift.

Use **one path or the other** on Claude Code. With both, every skill is registered twice —
once namespaced by the plugin and once from the personal directory — and `freya doctor`
warns about it (`bin/freya_cli.py:539-515`).

## The canonical store (ADR-014)

**The checkout is the store.** Installing does not materialise a second copy of anything: it
links each `freya-<skill>` directory into the agent's skills directory
(`bin/installer.py:370`). Nothing is rewritten on the way in, which is only possible because
the store's directory names are already the installed names — the Agent Skills spec requires
a skill's `name` to equal its parent directory, so the `freya-` prefix lives in the
repository rather than being applied at install time. The full reasoning, including why an
install-time prefix turned out to be impossible rather than merely awkward, is
[ADR-014](../decisions/ADR-014-canonical-store-install-contract.md).

Where the links go (`bin/installer.py:36-39`):

| Agent | Skills directory |
|---|---|
| `claude` | `~/.claude/skills` |
| `copilot` | `~/.agents/skills` |

Copilot reads both `~/.agents/skills` and `~/.copilot/skills`; the shared cross-agent
location is used and `~/.copilot/skills` deliberately skipped, so the suite is not
registered twice. Detection of which agents are present is deliberately *not* the same set:
`default_agents` (`bin/installer.py:807-824`) probes `~/.claude`, `~/.copilot` and
`~/.agents`, because Copilot creates `~/.copilot` and never `~/.agents`, so probing the
install targets would miss every Copilot-only machine.

The suite installs whole. It is **not separable** — every script resolves its siblings
through the store, and every SKILL.md invokes the launcher, so a single skill pulled alone
would be discoverable and entirely non-functional.

### Ownership: the installer never removes what it did not create

Every target is classified `create` / `ok` / `foreign` / `occupied` before anything is
touched (`bin/installer.py:143`). A real file or directory is `occupied` and always blocks,
*unless* it carries positive proof it is ours:

- a `.freya-install` marker naming this exact store, dropped inside a `--copy` skill
  directory (`bin/installer.py:30`, written at `:422`);
- a shim tag line naming this store, for a copied launcher (`bin/installer.py:48`, matched
  at `:595-608`).

Proof naming *another* store reads `foreign`. `--force` may replace a foreign symlink or a
foreign proof-carrying copy, and nothing else (`bin/installer.py:300-306`, `:344-363`).
`uninstall` removes only symlinks pointing into this store's `skills/`, copy directories
whose marker names it, and a launcher shim tagged with it (`bin/installer.py:445-516`).

Two properties are worth stating because they are easy to lose:

- **A multi-agent install plans everything before mutating anything.** Agents *and* the
  launcher are planned and blocker-checked up front (`bin/installer.py:919-941`), so
  `--agent claude --agent copilot` cannot leave claude fully installed when copilot is
  blocked. Plans whose target path a prior agent already claimed are dropped
  (`bin/installer.py:926-927`), which is what stops two agents sharing one physical skills
  directory from applying the same install twice.
- **A `--copy` install is staged and renamed, never written onto the target.**
  `copy_into_place` (`bin/installer.py:399-442`) copies into a dot-prefixed sibling, writes
  the marker last, and only then `os.replace`s it in. A failure before the rename leaves the
  previous state exactly as it was. The `except BaseException` at `:423` is deliberate: a
  Ctrl-C mid-copy is one of the two cases this exists for.

### The launcher on PATH

`bin/freya` is symlinked (or written as a shim) to `~/.local/bin/freya`
(`bin/installer.py:519-521`). The installer **never edits a shell profile**; when that
directory is absent from `PATH` it prints the line to add, in the shell the user is actually
in (`bin/installer.py:969-971`, `path_hint` at `:534-550`). `setx` is deliberately not
offered on Windows — it expands `%PATH%` into a literal and truncates at 1024 characters,
which is a way to lose someone's `PATH`.

Expect that note on most machines; the symptom and the fix are
[TROUBLESHOOTING.md § `freya: command not found`](TROUBLESHOOTING.md#freya-command-not-found).

### One question, asked once

After a successful (non-dry-run) install, `installer.main` calls
`backend_setup.offer_quietly(store)` (`bin/installer.py:985-990`) to ask which code-graph
substrate backend this machine should default to. It is asked here because this is the one
moment a person is definitely at a keyboard: `offer` returns immediately when stdin is not a
TTY (`bin/backend_setup.py:116-130`), so a scripted or CI install neither blocks nor prints.
Every part of it is best-effort — even the import is guarded, because under `-P` / `-I` /
`PYTHONSAFEPATH` the script's own directory is off `sys.path` and an unguarded import would
turn a completed install into a traceback and exit 1.

## The single-launcher rule (ADR-013)

Every SKILL.md invokes `freya <command> <args>` and nothing under `skills/` names an
interpreter, a path, or a host-specific construct
([ADR-013](../decisions/ADR-013-single-freya-launcher.md)). The resolution mechanism is
[DEVELOPER.md § How the launcher resolves a command](DEVELOPER.md#how-the-launcher-resolves-a-command),
and it is a gate rather than a convention —
[DEVELOPER.md § The conformance gate](DEVELOPER.md#the-conformance-gate) has the rules.

What is deployment-specific is where the launcher lands: `~/.local/bin/freya`, plus the
generated `freya.cmd` beside it on Windows (below).

## Windows

Windows is the platform every branch in the installer exists for, and the one with the most
ways to fail quietly.

- **Symlink privilege is probed, not demanded.** Creating a symlink needs Developer Mode or
  an elevated shell, and Windows refuses at `symlink_to` time — invisible to a pre-flight
  that only reads disk state. `symlinks_available` (`bin/installer.py:779-804`) creates and
  removes a probe link in each target directory during pre-flight; when any is refused the
  install switches to `--copy` and says so (`bin/installer.py:944-958`). The probe is skipped
  under `--dry-run`, because "a preview writes nothing" is the stronger promise; the cost is
  that a Windows preview says `linked` where the real run may copy.
- **The launcher is always written, never linked** (`launcher_uses_copy`,
  `bin/installer.py:684-695`). A copy of `bin/freya` placed elsewhere would import nothing,
  so the copied form is a generated shim carrying the store's `bin` path
  (`shim_text`, `:553-572`).
- **`freya.cmd` is generated at install time and never shipped** (`cmd_shim_text`,
  `:575-592`, written at `:750`). Windows resolves a bare command name through `PATHEXT` and
  an extensionless file is not in it, so without the `.cmd` every `freya <command>` in every
  SKILL.md is dead. The interpreter is baked into the shim rather than left as a bare
  `python`, which on a modern box is as likely to be the Microsoft Store alias stub as an
  interpreter.
- **Path spellings.** The kernel hands `os.readlink` an extended-length `\\?\C:\...` while
  `Path.resolve()` strips the prefix, so the two halves of every ownership comparison arrived
  spelled differently. `strip_extended_prefix` / `path_key` / `same_path`
  (`bin/installer.py:87-128`) are the single funnel every comparison goes through. Before
  that fix — found on the first Windows CI run, 2026-08-18 — every link a Windows install had
  just created classified as `foreign`.
- **Removing a directory symlink** needs `RemoveDirectoryW`, not `DeleteFileW`; `remove_link`
  (`bin/installer.py:375-396`) falls back to `os.rmdir` *only* on Windows, because on POSIX a
  failed `unlink` is a real failure and retrying would mask it.

## The Claude plugin and marketplace path

Two files, both at the repo root under `.claude-plugin/`:

- `plugin.json` — `name: freya-devkit`, `version: 0.3.1` (`plugin.json:2-3`), description, author
  `github@alexsendula.com`, MIT, keywords. There is no `skills` key; the plugin relies on the
  host loading the repository's `skills/` directory by convention.
- `marketplace.json` — one plugin entry whose `"source": "."` (`marketplace.json:11`) makes the repository
  root the plugin. Nothing narrows that: there is no manifest of shipped paths and no
  ignore file scoping it, so the plugin's unit is the whole repository.

**The host copies the repository in whole and filters nothing.** Measured on 2026-08-21 by
listing `~/.claude/plugins/cache/freya-devkit/freya-devkit/` on a machine with the plugin
installed: the `0.2.0` snapshot's root is exactly `51bdadb`'s tracked root — `.claude-plugin`,
`.github`, `.gitignore`, `assets`, `bin`, `docs`, `skills`, `install.sh`, `install.ps1`,
`README.md`, `CHANGELOG.md`, `CONTRIBUTING.md`, `LICENSE` — with no `.git`. `bin/` is present
including its `test_*.py` files. There is no `knowledge-base/`, only `docs/`, because `0.2.0`
predates the rename. The `0.1.0` snapshot beside it has no `bin/` directory at all, which is
what ADR-013:35 recorded. This matters because the plugin path's `freya` launcher resolves out
of that cache.

Consumers run `/plugin marketplace add AlexSendula/freya-devkit` then
`/plugin install freya-devkit@freya-devkit`, and skills appear as
`/freya-devkit:freya-code-graph`.

**No `PATH` step is needed on this path, and that is the host's doing, not ours.** Claude
Code adds each installed plugin's own `bin/` directory to the session `PATH`. This was
verified empirically on macOS on 2026-08-18 and recorded as the cost of ADR-013: the entry
was present even though the cached 0.1.0 snapshot has no `bin/` directory at all, which
shows it is added by convention rather than discovered
([ADR-013:35](../decisions/ADR-013-single-freya-launcher.md)). It is undocumented host behaviour
that nothing here tests. It *is* observable, though: doctor's `freya on PATH` row reports
whichever launcher `shutil.which` resolves, from any store and without going through the
launcher it is reporting on (`bin/freya_cli.py:354-356`), so running `doctor` from a second
checkout names the plugin-cache launcher when the convention is holding — measured that way on
2026-08-21, see
[TROUBLESHOOTING.md § `freya: command not found`](TROUBLESHOOTING.md#freya-command-not-found).
What no check covers is *why* the entry is there, or whether a future release still adds it. If
one stops, `freya <command>` stops resolving and the remedy is to run `install.sh` from a
checkout.

On Windows, prefer `install.ps1` on this path too: the store ships `bin/freya` without an
extension, and only the installer writes the `freya.cmd` that Windows needs to run it by
name.

`freya doctor` detects a plugin install by reading
`~/.claude/plugins/installed_plugins.json` and requiring an `installPath` that still exists
(`bin/freya_cli.py:255-275`) — not by probing `plugins/marketplaces/`, which survives
`/plugin uninstall` and so warned at users who had only added the marketplace.

## `freya update`

```bash
freya update            # fast-forward the store and re-link
freya update --dry-run  # report what would happen; writes nothing
```

**Which ref it follows: the current branch's own upstream, `@{u}`** — resolved at
`bin/updater.py:196-155` and used for both the fetch and the merge (`:322-281`, `:360`). It is
not hardcoded to `main`. For a default clone of this repository that resolves to
`origin/main`; for a store parked on a feature branch it is that branch's upstream, and for
a branch with no upstream `update` refuses and says how to set one (`:293-294`).

The sequence, all of it in `update()` (`bin/updater.py:309-279`):

1. **Preconditions, short-circuiting, at most one reason returned** (`:260-306`): git not on
   `PATH`; the store is not itself a git work tree (equality-checked, so a checkout nested
   inside another repository cannot make `update` fast-forward the wrong project, `:177-193`);
   detached `HEAD`; no upstream; an upstream that is a *local* branch; a dirty tree.
2. `git fetch <remote>` under a 60 s bound (`:346`, `FETCH_TIMEOUT` at `:97`). An unreachable
   remote exits 2 — without this guard the flow reached `merge-base` against the stale local
   ref and reported "already up to date" over a store that was not current.
3. `merge-base --is-ancestor HEAD <tracking>` (`:354`) asks "can this fast-forward?" before
   attempting it, so a diverged store gets its own message instead of git's.
4. `git merge --ff-only <tracking>` (`:360`). **Fast-forward only, by design** — no rebase,
   no merge commit, no stash. A store that has diverged is a situation only its owner can
   resolve.
5. **Re-link** (`:373`, `relink` at `:418-465`). Pulling is not enough: a symlink picks up an
   edit for free, but a skill *added* upstream has no link at all, one *deleted* leaves a
   dangling link, and a copy tracks nothing. An agent with zero `ok` entries is skipped
   entirely — a guard that is load-bearing twice over, because a store whose `skills/` went
   missing would otherwise audit every entry as an orphan and prune the lot (`:436-446`).
6. **Reload hint**, printed only when the store actually moved (`:113-116`, `:372`). Agents
   snapshot their skill list at session start, so an update applied mid-session is invisible
   until the session reloads: Claude Code `/reload-skills`, Copilot `/skills`, or a new
   session.
7. The backend question again, guarded and silent for anyone who has already answered
   (`:385-396`).

Exit codes: `2` for any refusal, `1` if the re-link failed for an agent (the store itself is
already updated, so the message says which agent to retry, `:463-464`), `0` otherwise.

**It cannot roll a store back.** Fast-forward only means there is no downgrade command:
`git checkout <ref>` in the store by hand, then re-run the installer.

### The staleness notice

Any `freya` command except `help`, `update`, `install`, `uninstall` and `doctor`
(`bin/freya_cli.py:22`, checked at `:558`) may first print one line to stderr:
`freya: an update is available — run freya update` (`bin/updater.py:571`).

- Notify-only. Nothing is ever downloaded or applied on its own.
- Throttled to roughly one network call a day (`CHECK_INTERVAL`, `bin/updater.py:567`), via
  `git ls-remote` under a hard 2 s timeout (`:98`, `:230`). Both the query and the answer are
  fully qualified as `refs/heads/<branch>`, because a bare pattern matches the tail of every
  advertised ref and an origin holding `dev/main` answered a query for `main` with the wrong
  SHA.
- "Behind" is `merge-base --is-ancestor`, not SHA inequality (`:240-257`). A contributor with
  a local commit is *ahead*, and answering "an update is available" there produced a daily
  notice for an update that then refused with "your store has diverged".
- A failure stamps the clock exactly as a success does, so an offline machine goes quiet for
  a day rather than paying the timeout on every command (`:630-638`).
- `notify()` (`:642-675`) contains the single justified bare `except` in the suite: a
  notification that can break the command it precedes is worse than no notification. The
  write is *inside* the guard. `FREYA_DEBUG` opts into the traceback, because a permanently
  broken check is otherwise indistinguishable from "no update, ever".

## `freya doctor`

The health check. It prints one row per check and returns 1 if any row is `FAIL`; warnings do
not fail it (`bin/freya_cli.py:552-525`).

| Row | `ok` when | Notes |
|---|---|---|
| `suite root` | `<store>/skills` is a directory | prints the resolved store path |
| `manifest` | `commands.json` loads and shadows no built-in | `fail` also when an entry's name is one `main` dispatches itself |
| `scripts` | every manifest target exists | `warn` "not evaluated" when the manifest was unusable |
| `python` | `>= 3.9` | prints the running version |
| `freya on PATH` | `shutil.which("freya")` finds a launcher that resolves *under this store* | `warn` both when nothing is found (this is the `~/.local/bin` step) and when what is found is a different copy — finding *a* `freya` is not finding *this* one (`:344-356`) |
| `store skills` | (only appears on failure) | the store's own `skills/` could not be listed |
| `agent: <name>` | (only appears on failure) | the agent's directory could not be audited |
| `agents` | at least one agent has `ok` entries | reports count and mode, e.g. `claude (10, symlink), copilot (10, copy)` |
| `orphaned entries` | none | four distinct clauses with four distinct remedies: `stale-store`, `orphan-skill`, shadowing `foreign`, shadowing `occupied` (`:424-452`) |
| `updates` | up to date, or ahead | run **unthrottled** — a diagnostic reporting a cached answer is not diagnosing anything (`:491-512`) |
| `duplicate install` | not both plugin and personal | `:529-538` |

Every read `doctor` makes is one that can fail on exactly the broken installation it was run
to explain, so each degrades to a row rather than a traceback (`:321-326`, `:363-368`,
`:377-385`).

## Continuous integration

**CI does not build, publish or deploy** — `.github/workflows/ci.yml` runs with
`permissions: contents: read` (`ci.yml:25-26`), and the only thing installed anywhere in it is pytest.
What it runs is [TESTING.md § CI](TESTING.md#ci); the matrix is
[CONTRIBUTING.md § Tests and the CI gate](../../CONTRIBUTING.md#tests-and-the-ci-gate). One
deployment-shaped detail is its own: the `install` job drives `install.sh` / `install.ps1` end
to end into `$RUNNER_TEMP` and resolves the launcher **by name off `PATH`** (`ci.yml:157-250`), which
is the only automated proof that either install path still works.

**These commits have not been through CI.** The last CI run was on `main` at `51bdadb`
(2026-08-18, 2 m 4 s, success); this branch is **63 commits ahead of `origin/main` and
unpushed**, so no runner has seen the polyglot substrate or the `knowledge-base/` move. The
local numbers above are one platform and one interpreter — they say nothing about the 3.9 leg
or about Windows.

## The explainer site (GitHub Pages)

`.github/workflows/pages.yml` publishes `knowledge-base/explanations/` — 11 HTML pages plus
`assets/site.js` and `assets/styles.css`, 432 KB total — as the site root.

- Triggers: a push to `main` touching `knowledge-base/explanations/**` or the workflow file
  itself, plus `workflow_dispatch` (`pages.yml:8-13`).
- Permissions: `contents: read`, `pages: write`, `id-token: write` (`pages.yml:15-18`). It is the only
  workflow here with write scopes.
- Concurrency `group: pages`, `cancel-in-progress: false` (`pages.yml:21-23`) — one deployment at a
  time, and a run in flight is never cancelled.
- Steps: checkout, `configure-pages@v5`, `upload-pages-artifact@v3` with
  `path: knowledge-base/explanations`, `deploy-pages@v4` (`pages.yml:32-42`). **Uploaded verbatim.
  There is no build step**, so anything added to that directory is published, and the seven
  top-level page filenames — `index`, `using`, `how-it-works`, `extending`, `reference`,
  `decisions`, `evolution` — are pinned URLs.

Repository Pages settings, read from the API on 2026-08-21: `build_type: workflow` (the
GitHub Actions source, which `deploy-pages` requires), `html_url:
https://alexsendula.github.io/freya-devkit/`, `cname: null` (no custom domain),
`https_enforced: true`, `public: true`, `custom_404: false`.

The job targets a `github-pages` environment (`pages.yml:27-29`), and that environment carries one
protection rule — a branch policy admitting only `main`. So the restriction to `main` is
enforced twice, independently: a `workflow_dispatch` run started from any other branch is
rejected at the environment gate, not merely skipped by the push trigger.

**The live site is currently built from the pre-rename layout.** The workflow only fires on
`main`, and `main` is at `51bdadb`, where the tree still has `docs/` and the workflow's path
filter and upload path both name `docs/explanations`. The rename to
`knowledge-base/explanations/` landed on this branch in `8a384fa` and reaches the site only
when the branch merges — at which point the push touches `knowledge-base/explanations/**`
and triggers a deploy on its own. Last successful deploy: run `32155951130`,
2026-08-18T15:41:12Z, 18 s.

## Versioning and release

**The current version is `0.3.1`** (`.claude-plugin/plugin.json:3`).

**It matches the newest CHANGELOG heading**, `## 0.3.0 — the polyglot substrate, and the
toolkit run on itself (2026-08-23)` (`CHANGELOG.md:9`). The previous release heading,
`## 0.2.0 — portability (2026-08-18)`, is the one below it.

Until 2026-08-23 those two disagreed: the version stayed at `0.2.0` while the changelog carried
an `Unreleased` heading, so the polyglot substrate was described but unversioned. That gap is
worth naming rather than deleting, because it is easy to re-open — the version is bumped by
hand and nothing checks that it moved when the changelog gained a section.

The release procedure for both consumer paths — versioned marketplace, unversioned
`freya update` — is [CONTRIBUTING.md § Releasing updates](../../CONTRIBUTING.md#releasing-updates)
and is not repeated here. What this document adds is the state above: the two are out of step
today, and every commit on the tracked branch is already live for the second.

There is nothing deployed to roll back, so rollback is git: push the revert and the next
`freya update` fast-forwards onto it, or bump to a fixed marketplace version. A broken *local*
install is the case with its own tooling — `freya doctor` names the failure and the remedy per
row, and `install.sh --uninstall` removes only what this store put down.

## Known gaps

Install-path defects live in [roadmap.md § Open defects](../roadmap.md#open-defects) — today
items 1, 2 and 5 — and the untested paths in § Platform-blocked, most sharply "Windows, with a
live agent". Two more are carried in ADR-014 § Revisit Conditions: there is no per-project
vendored install (`install.sh --project` fails argparse), and concurrent installs race between
classify and link. Do not restate any of them here; roadmap.md is the single live backlog.

## Related documentation

- [ADR-013](../decisions/ADR-013-single-freya-launcher.md) — one self-locating `freya`
  launcher is the sole command surface
- [ADR-014](../decisions/ADR-014-canonical-store-install-contract.md) — the canonical-store
  install contract, in five clauses
- [ARCHITECTURE.md](ARCHITECTURE.md) — what `bin/` and `skills/` contain and how the skills
  compose
- [DEVELOPER.md](DEVELOPER.md) — conventions for writing a skill that survives the
  conformance gate
- [CONTRIBUTING.md](../../CONTRIBUTING.md) — § Releasing updates, the two consumer paths
- [CHANGELOG.md](../../CHANGELOG.md) — what each version changed
- [migrations/](../migrations/) — runnable recipes for adopting a new version
- [roadmap.md](../roadmap.md) — the single live backlog, including the open defects above
