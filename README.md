<p align="center">
  <img src="assets/freya.png" alt="Freya — the freya-devkit mascot" width="460">
</p>

<h1 align="center">freya-devkit</h1>

<p align="center">
An integrated, AI-assisted development toolkit for <strong>any coding agent</strong> — Claude Code, GitHub Copilot, and the ~30 others that read the Agent Skills standard. Ten skills that work together to keep your dependency graph, documentation, feature specs, intended behavior, and security posture in sync as you build — plus a one-command wrap-up workflow that runs them all.
</p>

> 📖 **New here? Read the explainer → [alexsendula.github.io/freya-devkit](https://alexsendula.github.io/freya-devkit/)** — a no-install webapp: the problem it solves, how to install and use it, how it works, and how it evolved.

## What's new since 0.3.0 — declaring a directory outside the repo

**None of this is in a numbered release yet.**
[`.claude-plugin/plugin.json`](.claude-plugin/plugin.json) still reads `0.3.0`, and that file is
the version a Claude marketplace install sees — so everything below reaches marketplace users at
the next version bump, not before. `freya update` consumers see no version at all: that path
fast-forwards the checkout to its tracked branch, so this is live for them the moment it is
pushed.

**One new capability.** Inside the project root, discovery is automatic and needs no
configuration — that has not changed. What is new is that a project can name a directory
*outside* its root, in its committed `knowledge-base/settings.json`:

```json
{ "outside": { "ui": "../packages/ui" } }
```

An import in your code that resolves under a declared root becomes the edge target
`outside:ui/src/Button.tsx` — a fourth kind of answer beside `external:` (a package) and
`unresolved:` (a gap) — so a system split across sibling checkouts can finally tell *"ours,
over there"* from *"npm"*.

**A declaration buys resolution and nothing else.** Nothing under a declared root is scanned,
walked or globbed, and a declaration causes no file under one to be read — the whole filesystem
reach it grants is a `realpath` on the candidate an in-project import named, one `is_file()`,
and one cached `listdir` of that file's own directory. No file under a declared root ever
becomes a node in the graph. Crossing is never implicit either, by any route: an import's
`..`, a tsconfig `paths` escape and an absolute import all come back `unresolved:`, and a file
symlink committed inside the project whose target is outside it is refused rather than followed
(SEC-023, fixed). A symlink that stays inside the project is untouched — a monorepo linking a
package into place still works — because the rule asks where the file *is*, not whether the
entry is a link. Only relative paths are
accepted — `~` and absolute paths are refused by name, because that file is committed and both
of those mean a different directory for every reader. It is a per-project setting and never a
machine-wide one.

**Only the built-in `homegrown` resolver honours declarations.** Every build that has one prints
what it declared and how far each root got, zero crossings included — but on the `graphify`
backend that block always reads `crossings: 0`, not because nothing crossed, but because that
backend never consults the declarations. Read a zero there as "not looked at", not as "nothing
crossed". See
[ADR-031](knowledge-base/decisions/ADR-031-crossing-the-root-is-a-declared-act.md), which
records this as a known limit.

**Everything else here is a security pass** and changes nothing you type. The toolkit was
audited against itself; of the nineteen open findings, eighteen are fixed and one more was
found and fixed on the way. Two of them mattered on Windows, where `CreateProcess` searches
the working directory before `PATH`: a scanned repository that committed a `graphify.exe` or a
`claude.exe` at its root could get its own binary run as you. Both are closed the same way —
`graphify` and the agent CLIs are resolved to an absolute path before they are spawned, or
refused. That is narrower than "no bare names remain", which is not true: eight read-only `git`
spawns still use a bare name and are carried in an explicit allowlist CI turns red on a ninth,
and the project's own test command (`pnpm vitest`) is neither resolved nor allowlisted, because
running a project's tests executes that project's code anyway. Three behaviour changes worth
knowing:

- On **Windows with Python 3.9–3.11 only**, the toolkit now *refuses to run the program at
  all* when a scanned repository has a binary of that name at its root — the legitimate one
  further down `PATH` is never reached, and the command degrades with a stated reason. Those
  interpreters ignore the `NoDefaultCurrentDirectoryInExePath` opt-out (3.12+ honours it), so
  refusing is the only control left there. A denial of service traded for arbitrary code
  execution, deliberately. On 3.12+, and on every other platform, the real binary is found and
  nothing changes.
- The docs-manager's infrastructure detector no longer follows directory symlinks out of the
  project, so **a manifest reachable only through a symlinked directory is no longer detected**.
  It also stops at a file and byte cap rather than reading the whole tree.
- The `graphifyy` install line `freya install` prints is now **version-pinned**, and says out
  loud that the package is `graphifyy` with two y's while the command it installs is `graphify`
  with one.

Every GitHub Action this repo runs is SHA-pinned, with Dependabot to move the pins. One finding
is **mitigated rather than closed** and is deliberately still listed as open:
`--covering` now *labels* the evidence behind an accepted behavior instead of calling it a
verified guarantee, because the only evidence that would not come from the scanned repository
itself is running that repository's tests, which is worse than the problem.

## What's new in 0.3.0 — the graph reads your language

Everything here stands on the dependency graph, and until this release it was one
hand-written resolver that read four languages. Pointed at a Java project it found nothing,
printed *"Built dependency graph: 0 files scanned"*, and exited 0 — and the shape detector,
which decides whether a project is new by counting internal edges, then classified a
decade-old codebase as an empty scaffold.

The graph is now produced through a **contract with interchangeable backends**:

| Backend | Reads | Needs |
|---|---|---|
| `homegrown` | 4 languages, 6 extensions | nothing — ships with the toolkit |
| `graphify` | **40 languages, 93 extensions**, plus `calls` / `inherits` / `references` | its binary on `PATH` |

`homegrown` is the **floor**: it always runs unless something else is named, so a locked-down
machine where you cannot install anything still gets a graph. `graphify` is opt-in.

**Choosing one is a person's decision, never an automatic one.** `freya install` asks once and
records your answer; the first build in a project writes it into that project's committed
`knowledge-base/settings.json`, so a clone and CI resolve the same backend you do. Installing a
binary somewhere on `PATH` must not silently change every blast radius on the machine.

And every answer now says **what the backend could not read** — as a caveat to the agent
asking, never as a refusal. See [ADR-018 …
ADR-029](knowledge-base/decisions/) and the [CHANGELOG](CHANGELOG.md).

<details>
<summary><strong>Upgrading from 0.1.0 or 0.2.0</strong></summary>

**From 0.2.0** — nothing to do. A project that says nothing gets `homegrown`, which is the
resolver it already had.

**From 0.1.0** — every skill was renamed: `/freya-devkit:wrap-up` is now
`/freya-devkit:freya-wrap-up`, and so on for all ten. See
[`knowledge-base/migrations/skill-rename.md`](knowledge-base/migrations/skill-rename.md).

</details>

## Installation

### Any agent (Claude Code, GitHub Copilot, …)

```bash
git clone https://github.com/AlexSendula/freya-devkit.git
cd freya-devkit
./install.sh
```

The checkout is the store: `install.sh` symlinks each skill into your agent's
skills directory and places the `freya` launcher at **`~/.local/bin/freya`**. Pick
agents explicitly with `--agent claude --agent copilot`; use `--copy` where symlinks
are awkward, `--dry-run` to preview, and `--uninstall` to remove.

**Python 3.9 or newer** is the only requirement — nothing else is installed, and every
script here is stdlib-only. Both installers look for a suitable interpreter and refuse
with a plain message rather than starting and failing partway through.

**One manual step: `~/.local/bin` has to be on your `PATH`.** The installer never edits
your shell profile; it prints the line to add when that directory is missing from `PATH`.
Expect that note — a stock macOS never has `~/.local/bin` on `PATH`, and on
Debian/Ubuntu `~/.profile` only adds it if the directory already existed when you logged
in, which it may not have until the installer just created it. Make it stick:

```bash
echo 'export PATH="$HOME/.local/bin:$PATH"' >> ~/.zshrc   # or ~/.bashrc
exec $SHELL -l
```

Then verify with `freya doctor`, whose "freya on PATH" row answers this exactly. If
`freya doctor` answers `command not found`, this is the step that was skipped.

Skills install as `freya-code-graph`, `freya-wrap-up`, and so on.

**Windows.** Use `install.ps1`. Creating a symlink there needs Developer Mode or an
elevated shell, so the installer probes for the privilege up front and falls back to
`--copy` on its own rather than failing — you can also pass `--copy` explicitly. It
writes a `freya.cmd` beside the launcher, because Windows resolves a bare command name
through `PATHEXT` and an extensionless file is not in it. The `PATH` line it prints is
the PowerShell form, session and permanent.

### Keeping it current

```bash
freya update
```

Fast-forwards the checkout and re-links: a skill added upstream gets a link, one
removed loses its stale one, and a `--copy` install is re-copied. Before it
fetches anything, it refuses if git isn't on PATH, the store isn't a git
checkout, the branch has no upstream, or the tree is dirty — each says which.
It also refuses if the remote can't be reached, or if the store has diverged
from its upstream once it does fetch — either way, nothing is merged. A
re-link that fails partway exits differently: the fetch and merge already
succeeded, so it reports which agent failed rather than describing the store
itself as broken. `--dry-run` reports what would happen and writes nothing.

**Reload your session afterwards.** Agents read their skill list once, when a
session starts, so an update applied mid-task is invisible to that session until
it reloads — a skill added upstream will not appear, and one renamed or removed
keeps being offered and then fails on use. Run your agent's skill reload
(Claude Code: `/reload-skills`, GitHub Copilot: `/skills`) or start a new
session. `freya update` prints this reminder whenever it actually moves the
store.

Roughly once a day an ordinary `freya` command may print `an update is
available` to stderr — never for `help`, `update`, `install`, `uninstall` or
`doctor`, which either act on the notice directly or, for `doctor`, ask the
question themselves. It is a notice and nothing else — nothing is ever
downloaded or applied on its own. Set `FREYA_NO_UPDATE_CHECK=1` to turn it off.

### Telling a project's agent about the toolkit

```bash
freya init            # or: freya init path/to/project
```

Writes a short freya-devkit section into that project's `AGENTS.md` — the file ~30
agents read — listing the installed skills and the `freya` command surface. The
section is delimited by HTML comment markers: re-running replaces it in place and
leaves every other byte of the file alone, so it is safe on an `AGENTS.md` you already
maintain by hand. If those markers turn up missing, reversed, or duplicated, it
refuses without touching the file rather than guess where the block ends.

### Claude Code, via the plugin marketplace

```
/plugin marketplace add AlexSendula/freya-devkit
/plugin install freya-devkit@freya-devkit
```

Skills appear as `/freya-devkit:freya-code-graph`. No `PATH` step is needed on this
path: Claude Code adds each installed plugin's own `bin/` directory to the session
`PATH`, so the `freya` launcher the skills invoke resolves from the plugin cache.
That behaviour is the host's, not ours, and it is undocumented — if a future Claude
Code release drops it, `freya <command>` stops resolving and the fix is to run
`install.sh` from a checkout as above. On **Windows**, prefer `install.ps1` regardless:
the store ships `bin/freya` without an extension, and only the installer writes the
`freya.cmd` shim that Windows needs to run it by name.

**Upgrading from 0.1.0 on this path,** `/plugin marketplace update freya-devkit`
renames all ten skills — see [`knowledge-base/migrations/skill-rename.md`](knowledge-base/migrations/skill-rename.md).
Reload the session afterwards, or the old names keep being offered and then fail.

> Use one path or the other. With both, Claude registers every skill twice —
> once namespaced by the plugin and once from your personal directory.
> `freya doctor` warns when it sees this. It does **not** compare versions: if the
> two are different checkouts, a SKILL.md from one can invoke a `freya` command the
> other's `bin/commands.json` does not have, and the only symptom is
> `freya: unknown command`.

(For local development, see [CONTRIBUTING.md](CONTRIBUTING.md).)

## The skills

| Skill | Purpose | Example |
|-------|---------|---------|
| `freya-code-graph` | Dependency graphs, impact analysis, blast radius — through a backend contract, so it reads 4 languages or 40 depending on which you chose | `freya-code-graph impact src/auth.ts` |
| `freya-docs-manager` | Standardized project documentation | `freya-docs-manager update` |
| `freya-spec-manager` | Feature specs + intentional design decisions, ADRs, principles, and the behavior lifecycle | `freya-spec-manager scan` |
| `freya-behavior-graph` | Behavior graph: intended behavior as first-class records; blast radius code→behavior and behavior→code | `freya-behavior-graph --affected src/auth.ts` |
| `freya-behavior-runner` | Runs accepted behaviors, captures observed TEST→CODE coverage | `freya-behavior-runner run` |
| `freya-codebase-security-scan` | Security auditing (with adversarial verification + deep `audit` mode) | `freya-codebase-security-scan update` |
| `freya-codebase-security-resolver` | Interactive fixing of security findings | `freya-codebase-security-resolver` |
| `freya-dependency-vulnerability-check` | Supply-chain / dependency CVE auditing | `freya-dependency-vulnerability-check` |
| `freya-wrap-up` | Post-implementation orchestrator (runs the above in sequence) | `/freya-wrap-up` |
| `freya-status` | Read-only census of outstanding intent, tests owed, coverage gaps, and findings; refreshes `BACKLOG.md` | `freya-status` |

## How they fit together

```
code-graph (foundation: dependency + blast-radius data)
    │
    ├─> docs-manager        (impact-aware doc updates)
    ├─> spec-manager        (impact-aware spec updates + intent/governance)
    ├─> behavior-graph      (behavior.json — intended behavior, sibling of graph.json)
    │       └─> behavior-runner (runs accepted behaviors, captures TEST→CODE coverage)
    └─> codebase-security-scan ──┐
                                 │ (specs + accepted behaviors reduce false positives)
        codebase-security-resolver (fixes findings, documents intentional ones)

wrap-up  ── orchestrates: code-graph → docs → specs → behavior integrity & run → security, two-commit pattern
status   ── read-only counterpart of wrap-up: what intent / tests / coverage / findings are outstanding
```

- **code-graph is the keystone.** The doc, spec, and security skills query it for blast radius and degrade gracefully to plain `git diff` when it's unavailable.
- **specs are the false-positive filter.** The security scan reads `/knowledge-base/specs/` and marks spec'd behavior as *intentional design* rather than a vulnerability.
- **incremental by default.** Each skill tracks the last processed commit and only reprocesses what changed.

## Core patterns

1. **Two-commit pattern** — code changes land in one commit; generated artifacts (graph, docs, specs, security reports) in a second.
2. **Incremental updates** — git-aware; only process what changed.
3. **Coordinator + independent tasks** — one agent plans, then N independent tasks run in parallel if the agent supports subagents, else one at a time. Where the guarantee is load-bearing (the security scan) a driver schedules the work on its own process pool instead, because an agent's account of whether it parallelized cannot be checked.
4. **Certainty scoring** — AI-generated specs carry a 0–100 confidence score.

## Typical workflow

After implementing a feature:

```text
/freya-wrap-up
```

This runs `code-graph update` → `docs-manager update` → `spec-manager update` → **behavior integrity & accepted-behavior run** (Phase 3.5) → `codebase-security-scan update`, then makes the two commits. Skip steps with `--no-security`, `--no-docs`, `--no-specs`, `--no-graph`.

For a deep, exhaustive security pass before a release:

```text
freya-codebase-security-scan audit
```

`audit` and `scan` both drive a real agent CLI (`claude` or `copilot`) as a pool of
headless workers, so they **cost money** — `audit` can reach tens of dollars on a large
repo. The driver prints a cost plan and refuses to spend without confirmation; ask it for
the plan first (the skill runs `freya security audit --dry-run`, which spends nothing).
`wrap-up` never uses `audit`.

## Documentation

**[The explainer site](https://alexsendula.github.io/freya-devkit/)** — a no-install webapp on
GitHub Pages (source in [`knowledge-base/explanations/`](knowledge-base/explanations/)). Organised by what you want,
not by feature:

| Page | For |
|---|---|
| **[Home](https://alexsendula.github.io/freya-devkit/)** | The problem, the one idea, and whether this is for you |
| **[Using it](https://alexsendula.github.io/freya-devkit/using.html)** | Install, first run, the ten skills, what it writes and where |
| **[How it works](https://alexsendula.github.io/freya-devkit/how-it-works.html)** | Architecture, the graph substrate, the behavior layer, governance |
| **[Extending it](https://alexsendula.github.io/freya-devkit/extending.html)** | Writing a skill, the launcher, testing and CI |
| **[Reference](https://alexsendula.github.io/freya-devkit/reference.html)** | Where every command and artifact is documented |
| **[Decisions](https://alexsendula.github.io/freya-devkit/decisions.html)** | The thirty-one ADRs, and what each one rejected |
| **[How it evolved](https://alexsendula.github.io/freya-devkit/evolution.html)** | The plans that turned out wrong, and what replaced them |

The site is the human-facing narrative. The markdown in
[`knowledge-base/`](knowledge-base/) is the agent-facing source of truth for lookup material,
and the site links to it rather than restating it:

- [`philosophy.md`](knowledge-base/philosophy.md) — why these skills exist
- [`patterns.md`](knowledge-base/patterns.md) — reusable patterns across skills
- [`reference/ARCHITECTURE.md`](knowledge-base/reference/ARCHITECTURE.md) — how they connect, data flow
- [`reference/DEVELOPER.md`](knowledge-base/reference/DEVELOPER.md) — integration guidelines
- [`reference/SKILL_REFERENCE.md`](knowledge-base/reference/SKILL_REFERENCE.md) — quick command reference
- [`decisions/`](knowledge-base/decisions/) — thirty-one ADRs: what was decided, why, and what was rejected
- [`roadmap.md`](knowledge-base/roadmap.md) — the single live backlog, Track B first
- [`migrations/`](knowledge-base/migrations/) — one-time moves between versions

`knowledge-base/` is the layout freya-devkit creates in any project it runs against, and this
repo now uses it on itself: `reference/` and `README.md` are written by `docs-manager`, the
rest is hand-authored.

Release history: [CHANGELOG.md](CHANGELOG.md).

## License

MIT — see [LICENSE](LICENSE).
