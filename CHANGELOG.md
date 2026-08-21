# Changelog

Versions are the ones in [`.claude-plugin/plugin.json`](.claude-plugin/plugin.json), which
is what a Claude marketplace consumer sees. **`freya update` consumers do not see versions
at all** — that path fast-forwards the checkout to the tracked branch's head, so every
pushed commit is live for them the moment they run it. See
[CONTRIBUTING.md § Releasing updates](CONTRIBUTING.md#releasing-updates).

## Unreleased — the polyglot substrate (2026-08-21)

The code graph everything else stands on was one hand-written resolver reading four languages.
Point it at a Java project and it found nothing, printed *"Built dependency graph: 0 files
scanned"*, and exited 0 — and the shape detector, which decides whether a project is new by
counting internal edges, then classified a decade-old codebase as an empty scaffold. That was
the wall, hit on the first attempt to use the toolkit on a work laptop.

**The graph is now produced through a contract with interchangeable backends.**

- `homegrown` ships with the toolkit, needs nothing but Python, reads 4 languages across 6
  extensions, and is the floor — it always runs unless something else is named. The driving
  case is a locked-down machine where a package install is blocked, and the floor is what
  guarantees the toolkit degrades to *something* everywhere rather than to nothing.
- `graphify` is opt-in, needs its binary on `PATH`, and reads **40 languages across 93
  extensions** plus `calls`/`inherits`/`references` relations the floor has no notion of.

**Choosing one is a person's decision.** `freya install` asks once and records the answer as
your machine default; the first build in a project writes it into that project's committed
`knowledge-base/settings.json`, so a clone and CI resolve the same backend you do. It is never
scored automatically — installing a binary anywhere on `PATH` must not silently change every
blast radius on the machine.

```bash
uv tool install "graphifyy[sql,terraform]"
freya code-graph --use graphify --global
```

**Every answer now says what it could not read.** `build`, `update`, `query` and `impact` may
carry an `unmapped_source` block naming the in-scope source the backend could not parse and the
directories to grep instead; `dependents`/`dependencies` keep their bare arrays and say it on
stderr. The key is absent when there is nothing to say, so its presence means the answer above
it is computed over an incomplete graph.

**Also in this change**

- An edge is an object carrying `kind` and `provenance` behind a versioned schema, instead of a
  bare path string. Measured: the old shape could express 2,102 of graphify's 5,027 connections.
- Optional symbol refinement on edges — which symbol an edge leaves and arrives at — off by
  default, and never replacing the file anchor.
- Every built-in exclusion is now a default a project can overrule, in two tiers.
- Each backend writes its own `graph.<backend>.json` beside the active graph, so a substrate
  swap can be diffed rather than destroying the baseline it should be measured against.
- Fixed: `--update` silently no-opped whenever the project sat below the git root, freezing the
  graph while reporting success. Fixed: transitive traversal was recursive and raised
  `RecursionError` on repositories past roughly 1,200 connected files.

**Migration:** none. Existing graphs are read and brought forward; a project that names no
backend gets the floor, which is what it already had.

**Decisions:** ADR-018 through ADR-029.

### freya-devkit now runs on itself

The toolkit had never been pointed at its own repository, because its documentation lived in a
hand-maintained `docs/` and the skills read and write `knowledge-base/`. That tree has moved:

| Was | Is |
|---|---|
| `docs/architecture.md` | `knowledge-base/reference/ARCHITECTURE.md` |
| `docs/conventions.md` | `knowledge-base/reference/DEVELOPER.md` |
| `docs/skill-reference.md` | `knowledge-base/reference/SKILL_REFERENCE.md` |
| `docs/backlog.md` | `knowledge-base/roadmap.md` |
| everything else under `docs/` | the same path under `knowledge-base/` |

This affects anyone who linked to a file in this repo's `docs/` — including the explainer site,
which now points at the new paths. `backlog.md` is `roadmap.md` because `freya status` writes
`knowledge-base/BACKLOG.md` by full overwrite, and a hand-written backlog parked there would be
destroyed on the first run.

**Three defects surfaced the moment it ran on itself**, all of them in the shipped tool rather
than in this repo:

- `docs-manager` could not see its own output. Its stack detector looked only for `docs/`, so
  on any project that had already adopted `knowledge-base/` it reported no documentation at all
  and planned a from-scratch create instead of a reverse-sync.
- `freya principles list` printed a blank line and exited 0 for a project with no
  `principles.md` — indistinguishable from a file that exists and declares nothing.
- `freya doctor` reported a `freya` on `PATH` as healthy without checking it was the same tree
  it had just inspected, so running it from a checkout while a released copy was installed gave
  a green row for a binary the shell would never run.

Also: `**/.graph/` is gone from this repo's `.gitignore`. `code-graph` writes its own
`.gitignore` inside `knowledge-base/.graph/` naming the regenerable files individually so
`behavior.json` stays committable (ADR-017) — but git never descends into a directory an
ancestor ignored, so the root rule silently won. Any adopting project that added `**/.graph/`
by hand has the same problem.

## 0.2.0 — portability (2026-08-18)

The toolkit stops being a Claude Code plugin that happens to be portable and becomes an
agent-neutral suite that happens to ship as a Claude plugin too. Validated live on
**GitHub Copilot CLI** and **Claude Code**.

### Breaking — every skill was renamed

The Agent Skills spec requires a skill's frontmatter `name` to equal its directory name,
and a shared `~/.agents/skills/` has no namespace to keep `status` or `code-graph` from
colliding with someone else's skill. So the directories themselves carry the prefix now,
rather than the installer applying one:

| Before | After |
|---|---|
| `/freya-devkit:code-graph` | `/freya-devkit:freya-code-graph` |
| `/freya-devkit:docs-manager` | `/freya-devkit:freya-docs-manager` |
| `/freya-devkit:spec-manager` | `/freya-devkit:freya-spec-manager` |
| `/freya-devkit:behavior-graph` | `/freya-devkit:freya-behavior-graph` |
| `/freya-devkit:behavior-runner` | `/freya-devkit:freya-behavior-runner` |
| `/freya-devkit:codebase-security-scan` | `/freya-devkit:freya-codebase-security-scan` |
| `/freya-devkit:codebase-security-resolver` | `/freya-devkit:freya-codebase-security-resolver` |
| `/freya-devkit:dependency-vulnerability-check` | `/freya-devkit:freya-dependency-vulnerability-check` |
| `/freya-devkit:wrap-up` | `/freya-devkit:freya-wrap-up` |
| `/freya-devkit:status` | `/freya-devkit:freya-status` |

There is no alias and no deprecation period: the old names are directory names that no
longer exist. Anything that referenced one — a saved prompt, a team runbook, a project's
`AGENTS.md`, a `CLAUDE.md` — needs the new name. Full migration notes, including the
non-Claude install paths:
[`knowledge-base/migrations/skill-rename.md`](knowledge-base/migrations/skill-rename.md).

### Added

- **`freya`, a launcher.** One command surface for every agent
  (`freya code-graph --build`, `freya status`, …), self-locating via `__file__` and
  running targets with `sys.executable`. Commands are declared in `bin/commands.json`.
- **`install.sh` / `install.ps1`.** The checkout is the canonical store; the installer
  symlinks (or `--copy`-materializes) each skill into an agent's skills directory and
  places the launcher in `~/.local/bin`. `--agent`, `--copy`, `--force`, `--dry-run`,
  `--uninstall`.
- **`freya update`** — fast-forward-only refresh of the store plus a re-link, with a
  throttled, notify-only "update available" line on ordinary commands
  (`FREYA_NO_UPDATE_CHECK=1` disables it).
- **`freya doctor`** — suite root, Python, launcher on PATH, per-agent links, orphaned
  entries, duplicate installs.
- **`freya init`** — writes a marker-delimited freya-devkit section into a project's
  `AGENTS.md`, replacing it in place on re-runs and leaving every other byte alone.
- **The audit driver** (`freya security scan|audit`) — a Python driver that owns the
  security fan-out on its own worker pool of headless agent processes, under a read-only
  tool allowlist, with schema validation, bounded retry, cross-round dedup and N-skeptic
  majority voting. It replaces the Claude Workflow engine and it is why the security
  scan's guarantee no longer depends on the agent choosing to delegate.
- **CI** (`.github/workflows/ci.yml`) — the suite, the conformance gate and a real
  end-to-end install, on Linux and Windows, Python 3.9 and 3.13.

### Changed

- Every `SKILL.md` invocation moved from `python "${CLAUDE_PLUGIN_ROOT}/…"` to
  `freya <command>`. `bin/check_skill_conformance.py` fails the build if a Claude-only
  construct comes back.
- Fan-out prose is agent-neutral: run in parallel where the agent supports subagents,
  one at a time otherwise. Where the guarantee is load-bearing (the security scan) the
  prose was replaced outright by the driver.

### Removed

- `workflows/codebase-security-audit.js` — the Claude Workflow implementation of `audit`,
  superseded by the driver above. `audit` now runs on any supported agent CLI.

## 0.1.0

The Claude Code plugin as it stood before the portability track: ten skills invoked as
`/freya-devkit:<skill>`, scripts located through `${CLAUDE_PLUGIN_ROOT}`, `audit` running
on the Claude Workflow tool.
