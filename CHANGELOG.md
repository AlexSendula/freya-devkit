# Changelog

Versions are the ones in [`.claude-plugin/plugin.json`](.claude-plugin/plugin.json), which
is what a Claude marketplace consumer sees. **`freya update` consumers do not see versions
at all** — that path fast-forwards the checkout to the tracked branch's head, so every
pushed commit is live for them the moment they run it. See
[CONTRIBUTING.md § Releasing updates](CONTRIBUTING.md#releasing-updates).

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
[`docs/migrations/skill-rename.md`](docs/migrations/skill-rename.md).

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
