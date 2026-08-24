<p align="center">
  <img src="assets/freya.png" alt="Freya — the freya-devkit mascot" width="460">
</p>

<h1 align="center">freya-devkit</h1>

<p align="center">
The things around your code go stale as it changes — the docs, the design intent, the security
findings, what the code is <em>supposed</em> to do — and nobody redoes that upkeep by hand, in the
right order, every time. freya-devkit derives a dependency graph from your code, then gives each of
those artifacts a skill that re-syncs what a change actually reached.
</p>

> 📖 **New here? Read the explainer → [alexsendula.github.io/freya-devkit](https://alexsendula.github.io/freya-devkit/)** — a no-install webapp: the problem, the one idea, how to install and use it, and what is not proven.

Ten skills, on any agent that loads the [Agent Skills standard](https://agentskills.io/specification).
A change is known by the blast radius the graph reports rather than by the files you happened to
touch, and one skill, `freya-wrap-up`, runs the others in order and lands the result in two commits.

## What it runs on

**Claude Code and GitHub Copilot are both validated on a live run.** Other hosts that load the
standard should work, and have not been checked here. Whether the *graph* reads your language
depends on the backend, and choosing one is a person's decision, never an automatic one:

| Backend | Reads | Needs |
|---|---|---|
| `homegrown` | TypeScript, JavaScript, Python, Go — 4 languages, 6 extensions | nothing; ships with the toolkit |
| `graphify` | 40 languages, 93 extensions, plus `calls` / `inherits` / `references` edges | its binary on `PATH` |

`homegrown` is the floor and runs unless something else is named, so a locked-down machine where you
cannot install anything still gets a graph. The two differ on every axis that matters — regex
against AST, file-level against symbol-level — not only on the language count. `freya install` asks
once, and the first build records the answer in the project's committed
`knowledge-base/settings.json`, so a clone and CI resolve the same backend you do. Either way, an
answer says what the backend could not read, as a caveat to the agent asking rather than a refusal.

## Installation

```bash
git clone https://github.com/AlexSendula/freya-devkit.git
cd freya-devkit
./install.sh            # Windows: .\install.ps1
```

The checkout is the store: each skill is symlinked into your agent's skills directory and the
`freya` launcher lands at `~/.local/bin/freya`. Pick targets with `--agent claude --agent copilot`;
`--copy` where symlinks are awkward, `--dry-run` to preview, `--uninstall` to remove. **Python 3.9
or newer is the only requirement** — every script here is stdlib-only, and both installers probe for
an interpreter and refuse with one line rather than starting and dying partway through.

**One manual step: `~/.local/bin` has to be on your `PATH`.** The installer never edits your shell
profile; when that directory is missing from `PATH` it prints the line to add. Expect that note — a
stock macOS never has that directory on `PATH`, and Debian/Ubuntu's `~/.profile` adds it only if the
directory existed when you logged in, which it may not have until the installer just created it. If
`freya doctor` answers `command not found`, this is the step that was skipped.

```bash
echo 'export PATH="$HOME/.local/bin:$PATH"' >> ~/.zshrc   # or ~/.bashrc
```

**Claude Code can install from the plugin marketplace instead** — `/plugin marketplace add
AlexSendula/freya-devkit`, then `/plugin install freya-devkit@freya-devkit`. Skills appear as
`/freya-devkit:freya-code-graph` and no `PATH` step is needed, because Claude Code adds each
plugin's own `bin/` to the session `PATH`. That behaviour is the host's, not ours, and it is
undocumented: if a release drops it, `freya <command>` stops resolving and the fix is `install.sh`
from a checkout.

> **Use one path or the other.** With both, Claude registers every skill twice. `freya doctor`
> warns, but compares presence and not versions: if the two are different checkouts, a `SKILL.md`
> from one can invoke a `freya` command the other lacks, and the only symptom is
> `freya: unknown command`.

<details>
<summary><strong>Windows, and keeping it current</strong></summary>

**On Windows, prefer `install.ps1` on either path.** Only the installer writes the `freya.cmd` shim
Windows needs to run the launcher by name — a bare command name resolves through `PATHEXT`, and an
extensionless file is not in it. Creating a symlink there needs Developer Mode or an elevated shell,
so the installer probes for that privilege up front and falls back to `--copy` on its own rather
than failing. The `PATH` line it prints is the PowerShell form.

**`freya update` fast-forwards the store and re-links it** — a skill added upstream gets a link, one
removed loses its stale one. It refuses rather than guessing when git is missing, the store is not a
checkout, the branch has no upstream, the tree is dirty, the remote is unreachable, or the store has
diverged; each refusal says which, and `--dry-run` writes nothing. On the plugin path the equivalent
is `/plugin marketplace update freya-devkit`. **Reload your session afterwards** either way: agents
read their skill list once, when the session starts, so an update applied mid-task is invisible
until that session reloads. Coming from 0.1.0, every skill was renamed — the recipe is
[`migrations/skill-rename.md`](knowledge-base/migrations/skill-rename.md).

The full sequence, its exit codes and the once-a-day staleness notice are in
[DEPLOYMENT.md](knowledge-base/reference/DEPLOYMENT.md); symptom-by-symptom fixes are in
[TROUBLESHOOTING.md](knowledge-base/reference/TROUBLESHOOTING.md).

</details>

## First run

```bash
cd path/to/your/project
freya doctor                 # is the install healthy, and is the launcher on PATH
freya init                   # or: freya init path/to/project
freya code-graph --build     # the first graph; everything else reads it
```

`freya init` writes a short freya-devkit section into that project's `AGENTS.md`. HTML comment
markers delimit it, so re-running replaces it in place and leaves every other byte alone; markers
that turn up missing, reversed or duplicated make it refuse without touching the file rather than
guess where the block ends.

Then ask your agent for a skill by name — *"run the freya-docs-manager skill and update the docs"*.
**One hyphen changes the meaning:** `freya <command>` with a space is the CLI, `freya-<skill>` with
a hyphen is a skill name, and they are never interchangeable. There is no cross-agent slash form; on
the Claude plugin path it is `/freya-devkit:freya-docs-manager`.

## The daily loop

After you finish a change, ask for **`freya-wrap-up`**:

```text
commit 1 ── your code
      code-graph → docs-manager → spec-manager → behavior integrity + run → security scan
commit 2 ── everything those five regenerated
```

That split is mechanical rather than aesthetic — a security report names the commit it was generated
from, and the reference is only stable if the report is not in it. Skip phases with `--no-graph`,
`--no-docs`, `--no-specs`, `--no-security`.

**`freya-status` is the read-only counterpart:** what intent, tests, coverage and findings are
outstanding. It reads everything and writes exactly one file, `knowledge-base/BACKLOG.md`, by full
overwrite — so never hand-author there.

## What lands in your repository

**One directory, `knowledge-base/` at the project root** — docs, specs, ADRs, declared intent,
security reports, the backlog and the behavior graph. All of it is meant to be committed except four
generated cache files inside `.graph/`, which are gitignored while `.graph/` itself is not;
[ARCHITECTURE.md § Output Artifacts](knowledge-base/reference/ARCHITECTURE.md#output-artifacts)
marks every line tracked or ignored.

Three things land outside it: the `AGENTS.md` section, and only when you run `freya init`; a
`features/<category>/<name>.feature` scaffold in the code tree, written when a *person* accepts a
proposed behavior and never from a scan; and, on the `graphify` backend, that tool's own
`graphify-out/` at the project root, which the backend marks gitignored after the run.

## What it costs

**The security pass `freya-wrap-up` runs is the free one.** Its `update` mode is incremental and
stays in your session; wrap-up never runs the other two. `scan` and `audit` drive a real agent CLI
as a pool of headless workers and **cost money** — one finder worker measured $0.396 on a trivial
fixture, and `audit`'s budget of six categories, up to five rounds, and three skeptics per finding
is plausibly ~90 calls and tens of dollars on a real repository. The driver prints a cost plan and
refuses to spend without confirmation: `freya security audit --dry-run` prints the plan and the
ceiling and calls nothing.

## The skills

| Skill | Keeps coherent | Reach for it when |
|---|---|---|
| `freya-code-graph` | the dependency graph | you need a blast radius — everything below reads this |
| `freya-docs-manager` | project documentation | code moved and the docs still describe where it was |
| `freya-spec-manager` | specs, ADRs, principles, declared intent | a decision needs recording so it is not "fixed" later |
| `freya-behavior-graph` | `behavior.json` — intended behavior, both directions | you want the behaviors a change touches, or the code behind one |
| `freya-behavior-runner` | observed TEST→CODE coverage | accepted behaviors need running and fingerprinting |
| `freya-codebase-security-scan` | security findings | after a change (`update`), or before a release (the paid `scan` and `audit`) |
| `freya-codebase-security-resolver` | the same findings, interactively | you are working through what the scan found |
| `freya-dependency-vulnerability-check` | dependency CVEs | you want the supply chain checked rather than your own code |
| `freya-wrap-up` | all of the above, in order | you finished a change — this is the one to remember |
| `freya-status` | `knowledge-base/BACKLOG.md`, and nothing else | you want to know what is outstanding before starting |

Most days that is two names; the rest are what wrap-up calls, worth invoking directly when you want
one artifact rather than the whole pass. They degrade rather than fail — docs, specs and security
fall back to a plain `git diff` when the graph is unavailable, and the security scan reads your
specs and marks what it matches there as intentional design rather than reporting it. Per-skill
command tables: [SKILL_REFERENCE.md](knowledge-base/reference/SKILL_REFERENCE.md).

## What it does not do

**Coherence, not enforcement.** The patterns are guidelines, skills adapt them, and inferred specs
carry a 0–100 certainty score rather than rounding to confident. There are exactly two exceptions,
both deliberate: the behavior and governance layer, where deterministic facts — a broken test link,
a regressed accepted behavior — hard-block and model judgment must be resolved before you proceed;
and the agent-neutrality gate in CI, which has no exemptions.

**The graph stops at your project root.** An import resolving outside it comes back `unresolved:`
unless the project declares that directory in its committed `knowledge-base/settings.json`, and a
declaration buys resolution and nothing else: no declared root is globbed, walked or added as a scan
root, and no file under one is ever read. Only `homegrown` honours declarations, so `crossings: 0`
on the `graphify` backend means *not looked at*, not *nothing crossed*
([ADR-031](knowledge-base/decisions/ADR-031-crossing-the-root-is-a-declared-act.md)).

**Some of it has never been proven,** listed as risk rather than reassurance. No agent CLI has ever
run on Windows: CI installs and tests the toolkit there, but no agent runs on that runner. Each
install mode is exercised on one platform only — symlink on Linux, `--copy` on Windows — which
leaves the opposite diagonal untested on both. And whether GitHub Copilot delegates at scale on a
large codebase has never been tried. Those are three of them; the live list, re-verified against
shipped code, is [`roadmap.md`](knowledge-base/roadmap.md).

## Documentation

**[The explainer site](https://alexsendula.github.io/freya-devkit/)** is the human-facing narrative,
organised by what you want rather than by feature (source in
[`knowledge-base/explanations/`](knowledge-base/explanations/)):

| Page | For |
|---|---|
| **[Home](https://alexsendula.github.io/freya-devkit/)** | The problem, the one idea, and what is not proven |
| **[Using it](https://alexsendula.github.io/freya-devkit/using.html)** | Install, first run, the ten skills, what it writes and where |
| **[How it works](https://alexsendula.github.io/freya-devkit/how-it-works.html)** | Architecture, the graph substrate, the behavior layer, governance |
| **[Extending it](https://alexsendula.github.io/freya-devkit/extending.html)** | Writing a skill, the launcher, testing and CI |
| **[Reference](https://alexsendula.github.io/freya-devkit/reference.html)** | Where every command and artifact is documented |
| **[Decisions](https://alexsendula.github.io/freya-devkit/decisions.html)** | The thirty-one ADRs, and what each one rejected |
| **[How it evolved](https://alexsendula.github.io/freya-devkit/evolution.html)** | The plans that turned out wrong, and what replaced them |

The markdown under [`knowledge-base/`](knowledge-base/) is the agent-facing source of truth, and the
site links to it rather than restating it:

- [`philosophy.md`](knowledge-base/philosophy.md) and [`patterns.md`](knowledge-base/patterns.md) — why these skills exist, and what they share
- [`reference/`](knowledge-base/reference/) — architecture, deployment, environment, security, testing, style, troubleshooting, developer guide
- [`decisions/`](knowledge-base/decisions/) — the ADRs as markdown, each with its rejected alternatives and revisit conditions
- [`roadmap.md`](knowledge-base/roadmap.md) — the single live backlog
- [`migrations/`](knowledge-base/migrations/) — one-time moves between versions, including the `docs/` → `knowledge-base/` relayout for projects still on the pre-0.2.0 tree

That layout is what freya-devkit creates in any project it runs against, and this repo uses it on
itself: `reference/` and `knowledge-base/README.md` are written by `docs-manager`, and the rest —
including this file — is hand-authored. Working on the toolkit itself:
[CONTRIBUTING.md](CONTRIBUTING.md). Release history: [CHANGELOG.md](CHANGELOG.md).

## License

MIT — see [LICENSE](LICENSE).
