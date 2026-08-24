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
depends on which backend you pick:

| Backend | Reads | Needs |
|---|---|---|
| `homegrown` | TypeScript, JavaScript, Python, Go — 4 languages | nothing; ships with the toolkit |
| `graphify` | 40 languages, and which symbol each edge leaves and arrives at | its binary on `PATH` |

`homegrown` is the floor and runs unless you say otherwise, so a locked-down machine where you
cannot install anything still gets a graph. `freya install` asks you once and records the answer in
the project, so a clone and CI resolve the same backend you do.

## Installation

```bash
git clone https://github.com/AlexSendula/freya-devkit.git
cd freya-devkit
./install.sh            # Windows: .\install.ps1
```

The checkout is the store: each skill is symlinked into your agent's skills directory and the
`freya` launcher lands at `~/.local/bin/freya`. Pick targets with `--agent claude --agent copilot`;
`--copy` where symlinks are awkward, `--dry-run` to preview, `--uninstall` to remove. **Python 3.9
or newer is the only requirement** — every script here is stdlib-only.

**One manual step: `~/.local/bin` has to be on your `PATH`.** The installer never edits your shell
profile; it prints the line to add. Expect that note — a stock macOS never has that directory on
`PATH`. If `freya doctor` answers `command not found`, this is the step that was skipped.

```bash
echo 'export PATH="$HOME/.local/bin:$PATH"' >> ~/.zshrc   # or ~/.bashrc
```

**Claude Code can install from the plugin marketplace instead** — `/plugin marketplace add
AlexSendula/freya-devkit`, then `/plugin install freya-devkit@freya-devkit`. Skills appear as
`/freya-devkit:freya-code-graph`, and no `PATH` step is needed.

> **Use one path or the other.** With both, Claude registers every skill twice. `freya doctor`
> warns when it sees this.

<details>
<summary><strong>Windows, and keeping it current</strong></summary>

**On Windows, prefer `install.ps1` on either path** — only the installer writes the `freya.cmd`
shim Windows needs to run the launcher by name. Creating a symlink there needs Developer Mode or
an elevated shell, so the installer checks first and falls back to `--copy` on its own rather than
failing.

**`freya update` fast-forwards the store and re-links it** — a skill added upstream gets a link,
one removed loses its stale one. It refuses rather than guessing when something is off (no git, a
dirty tree, an unreachable remote), and `--dry-run` writes nothing. On the plugin path the
equivalent is `/plugin marketplace update freya-devkit`. **Reload your session afterwards** either
way: agents read their skill list once, when the session starts. Coming from 0.1.0, every skill was
renamed — the recipe is
[`migrations/skill-rename.md`](knowledge-base/migrations/skill-rename.md).

The full sequence and its exit codes are in
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

`freya init` adds a short freya-devkit section to the project's `AGENTS.md`, fenced by comment
markers so re-running updates just that section and leaves the rest of your file alone.

Then ask your agent for a skill by name — *"run the freya-docs-manager skill and update the docs"*.
**One hyphen changes the meaning:** `freya <command>` with a space is the CLI, `freya-<skill>` with
a hyphen is a skill name. On the Claude plugin path it is `/freya-devkit:freya-docs-manager`.

## The daily loop

After you finish a change, ask for **`freya-wrap-up`**:

```text
commit 1 ── your code
      code-graph → docs-manager → spec-manager → behavior integrity + run → security scan
commit 2 ── everything those five regenerated
```

Two commits, so generated artifacts never land mixed in with your code. Skip phases with
`--no-graph`, `--no-docs`, `--no-specs`, `--no-security`.

**`freya-status` is the read-only counterpart:** what intent, tests, coverage and findings are
outstanding. It writes one file, `knowledge-base/BACKLOG.md`, and rewrites it completely each time —
so don't hand-edit that one.

## What lands in your repository

**One directory, `knowledge-base/` at the project root** — docs, specs, ADRs, declared intent,
security reports, the backlog and the behavior graph. It is meant to be committed, apart from a
small cache the toolkit regenerates;
[ARCHITECTURE.md § Output Artifacts](knowledge-base/reference/ARCHITECTURE.md#output-artifacts)
marks every file tracked or ignored.

Two things land outside it: the `AGENTS.md` section, when you run `freya init`; and a `.feature`
scaffold in your code tree, written only when you accept a proposed behavior.

## What it costs

**The security pass `freya-wrap-up` runs is the free one** — its `update` mode is incremental and
stays in your session. The deeper `scan` and `audit` modes drive a real agent CLI as a pool of
headless workers and **cost money**: tens of dollars on a large repository. Neither runs without
asking. `freya security audit --dry-run` prints the plan and the ceiling and spends nothing.

## The skills

| Skill | Keeps in sync | Reach for it when |
|---|---|---|
| `freya-code-graph` | the dependency graph | you need a blast radius — everything below reads this |
| `freya-docs-manager` | project documentation | code moved and the docs still describe where it was |
| `freya-spec-manager` | specs, ADRs, design decisions | a decision needs recording so it is not "fixed" later |
| `freya-behavior-graph` | what the code is supposed to do | you want the behaviors a change touches, or the code behind one |
| `freya-behavior-runner` | which tests actually cover which code | those behaviors need running to prove they still hold |
| `freya-codebase-security-scan` | security findings | after a change (free), or before a release (the paid modes) |
| `freya-codebase-security-resolver` | the same findings, interactively | you are working through what the scan found |
| `freya-dependency-vulnerability-check` | dependency CVEs | you want the supply chain checked rather than your own code |
| `freya-wrap-up` | all of the above, in order | you finished a change — this is the one to remember |
| `freya-status` | `knowledge-base/BACKLOG.md` | you want to know what is outstanding before starting |

Most days that is two names — `freya-wrap-up` and `freya-status`. The rest are what wrap-up calls,
worth invoking directly when you want one artifact rather than the whole pass. They degrade rather
than fail: without a graph they fall back to a plain `git diff`, and the security scan reads your
specs and marks what it matches there as intentional design rather than reporting it. Per-skill
command tables: [SKILL_REFERENCE.md](knowledge-base/reference/SKILL_REFERENCE.md).

## What it does not do

**Coherence, not enforcement.** The patterns are guidelines, skills adapt them, and inferred specs
carry a 0–100 certainty score rather than rounding to confident. The exception is the behavior
layer, where a broken test link or a failing accepted behavior blocks until you deal with it.

**The graph stops at your project root.** Imports resolving outside it come back unresolved, unless
you declare that directory in the project's settings — worth knowing if your code spans sibling
checkouts
([ADR-031](knowledge-base/decisions/ADR-031-crossing-the-root-is-a-declared-act.md)).

**Some of it has never been proven,** listed as risk rather than reassurance. No agent CLI has ever
run on Windows: CI installs and tests the toolkit there, but no agent runs on that runner. Each
install mode is exercised on one platform only — symlink on Linux, `--copy` on Windows — which
leaves the opposite diagonal untested on both. And whether GitHub Copilot delegates at scale on a
large codebase has never been tried. Those are three of them; the live list is
[`roadmap.md`](knowledge-base/roadmap.md).

## Documentation

**[The explainer site](https://alexsendula.github.io/freya-devkit/)** is the human-facing narrative,
organised by what you want rather than by feature (source in
[`knowledge-base/explanations/`](knowledge-base/explanations/)):

| Page | For |
|---|---|
| **[Home](https://alexsendula.github.io/freya-devkit/)** | The problem, the one idea, and what is not proven |
| **[Using it](https://alexsendula.github.io/freya-devkit/using.html)** | Install, first run, the ten skills, what it writes and where |
| **[How it works](https://alexsendula.github.io/freya-devkit/how-it-works.html)** | Architecture, how the graph is built, and how the pieces connect |
| **[Extending it](https://alexsendula.github.io/freya-devkit/extending.html)** | Writing a skill, the launcher, testing and CI |
| **[Reference](https://alexsendula.github.io/freya-devkit/reference.html)** | Where every command and artifact is documented |
| **[Decisions](https://alexsendula.github.io/freya-devkit/decisions.html)** | The thirty-one ADRs, and what each one rejected |
| **[How it evolved](https://alexsendula.github.io/freya-devkit/evolution.html)** | The plans that turned out wrong, and what replaced them |

The markdown under [`knowledge-base/`](knowledge-base/) is the agent-facing source of truth, and the
site links to it rather than restating it:

- [`philosophy.md`](knowledge-base/philosophy.md) and [`patterns.md`](knowledge-base/patterns.md) — why these skills exist, and what they share
- [`reference/`](knowledge-base/reference/) — architecture, deployment, environment, security, testing, style, troubleshooting, developer guide
- [`decisions/`](knowledge-base/decisions/) — the ADRs as markdown, each with its rejected alternatives
- [`roadmap.md`](knowledge-base/roadmap.md) — the single live backlog
- [`migrations/`](knowledge-base/migrations/) — one-time moves between versions

That layout is what freya-devkit creates in any project it runs against, and this repo uses it on
itself. Working on the toolkit itself: [CONTRIBUTING.md](CONTRIBUTING.md).
Release history: [CHANGELOG.md](CHANGELOG.md).

## License

MIT — see [LICENSE](LICENSE).
