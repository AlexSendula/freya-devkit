# Portability — Vision & Brainstorm

**Track A of "work-laptop enablement." Status: brainstorm — 2026-07-13; open questions resolved 2026-07-14; corrections appended 2026-08-18 after the track shipped.**

> This is a **design record**. Where implementation went elsewhere, the original wording
> stays and a dated `> **Correction …**` block sits under it — see §4.1 here, and the
> seven in [`01-design.md`](01-design.md). Shipped code is the ground truth.

Make freya-devkit installable and runnable **outside Claude Code**, as a first-class multi-agent toolkit, with a **single command**. This is **Track A** of the work-laptop-enablement initiative; the **polyglot substrate** (Track B) and the **subagent-flow / generated-docs audit** ([`../notes.md`](../notes.md)) are separate, later efforts.

---

## 1. Problem

freya-devkit is a Claude Code *plugin*. The deterministic engine (the stdlib-Python CLIs under each skill's `scripts/`) is already agent-agnostic, but the **orchestration layer is Claude-specific**:

- `SKILL.md` prose invokes the Skill tool and `/freya-devkit:*`.
- Scripts are located via `${CLAUDE_PLUGIN_ROOT}`.
- Install goes through the Claude plugin marketplace.
- The coordinator + worker flows (`wrap-up`, `scan`) assume Claude subagents.

On a different agent — the driving case is **VS Code + GitHub Copilot** at $DAYJOB — it doesn't cleanly install or run.

## 2. Goal & scope

- **Goal:** one-command install of the **whole workflow** (not just the deterministic core) onto a target agent, running correctly there.
- **Architected for any agent, but the first implementation targets Copilot + Claude Code.** Others (Cursor, Codex, Gemini CLI, Aider, …) follow once the two-target design proves out.
- **Whole-workflow port**, including the orchestrated skills, via graceful degradation (§4.3).

### Non-goals (explicitly deferred)

- **Track B — polyglot substrate** (Java, config-as-code, framework-agnosticism). Separate initiative, after this. See `behavior-layer/parking-lot.md`.
- **Subagent-flow & generated-docs audit** — reviewing every coordinator/worker flow and what docs `docs-manager` produces. Captured in [`../notes.md`](../notes.md); after this feature.
- **Auto-apply updates** and a public **skills.sh listing** — see §4.4 / §6.
- *(Resolved, no longer a non-goal: `codebase-security-scan audit`. It runs on Claude's Workflow tool today, but is ported by owning the orchestration ourselves and driving any agent headlessly — see design §6.1.)*

## 3. The landscape (verified 2026-07-13/14 — this area moves monthly)

The ecosystem has converged on standards that make this *far* smaller than "build an installer from scratch":

- **Agent Skills open standard (`SKILL.md`)** — Anthropic's format, published as an open standard (Dec 2025, agentskills.io). A skill = a directory with `SKILL.md` (YAML frontmatter: `name` + `description`) + optional `scripts/` / `references/` / `assets/`. Read by Claude Code, **GitHub Copilot**, Codex, Cursor, Gemini CLI, Windsurf — ~30 tools. **freya-devkit already ships in exactly this layout**, so we're *conforming*, not rebuilding.
- **`AGENTS.md`** — the cross-tool *instructions* standard ("README for agents"), governed by the Linux Foundation's Agentic AI Foundation; ~30 tools read it. Per-repo, prose only. We don't ship one yet.
- **Subagents** — now broadly supported: native parallel in Claude Code, Codex, Cursor, **Copilot (VS Code agent mode + CLI `/fleet`)**, Antigravity, Devin, OpenCode. Single-threaded holdouts: **Aider, Gemini CLI**. **Invocation syntax differs per agent** (Claude `context: fork` / Task tool vs Copilot custom-agents / agent-initiated delegation) — that difference is what we design around, not an absence of the feature. Parallel fan-out costs ~7× the tokens of a sequential pass (each subagent carries its own context window), so sequential is often the sane default, not just a fallback.
- **Canonical store + symlinks** — the ecosystem's proven install pattern (skills.sh, `gh skill`, `skillz`, Atlassian TWG): shallow-fetch skills into **one** canonical store (`~/.agents/skills/` global, `./.agents/skills/` project) and **symlink** each agent's dir (`~/.claude/skills`, `~/.copilot/skills`, …) at it. Update once → every agent sees it. A **copy** fallback covers symlink-hostile cases (Windows, committed skills).
- **Installers** — the ecosystem tools are built for **single** skills from a repo-root `SKILL.md` and fit a **coupled suite** like ours poorly (the documented "install related skills independently → behavioral drift" problem) — so we ship our own, but reuse the store+symlink pattern.
- **MCP** — exposes tools over a protocol. Not needed here (§4.6): our tools are local Python CLIs the agent runs via bash.

## 4. Design decisions (resolved)

### 4.1 Install & distribution — our own suite-aware installer, ecosystem pattern underneath

A one-command `install.sh --agent copilot|claude` (extensible) that installs the **whole suite** using the ecosystem's proven model:

- Materialize the suite once into the **canonical store** — the cross-agent **`~/.agents/skills/`** (personal/global scope, since freya-devkit is a general toolkit you want in every project, not vendored per-repo).
- **Symlink** each target agent's skills dir at it (`~/.copilot/skills`, `~/.claude/skills`), with a **copy** fallback for Windows / symlink-hostile environments.
- Ship an **`AGENTS.md`** *template*, applied per-project on request (`freya init`) rather than as part of the global install — `AGENTS.md` is a per-repo file by convention, and writing into a user's repo unasked would be intrusive. See design §4.1.

We do **not** depend on skills.sh (single-skill model, markdown sprawl, drift), but we keep every skill **standard-conformant** so the ecosystem *can* pull individual skills for discoverability. This mirrors the symlink-to-repo pattern the Claude local-dev install already uses.

> **Correction (2026-08-18, after implementation).** Two amendments to this section; the
> vision is kept as written because the reasoning is the record.
>
> 1. **Conformant is not the same as separable, and this suite is not separable.** The
>    sentence above invites a reading — "the ecosystem can pull individual skills" — that
>    the design's own constraint rules out. Every script resolves its siblings through
>    `Path(__file__).resolve().parents[2] / "freya-<other-skill>" / "scripts"`, so a skill
>    pulled on its own fails at import time on the missing sibling; and since the
>    portability work, every `SKILL.md` invokes `freya <command>`, which additionally
>    needs the launcher, `bin/commands.json` and the whole store — none of which travel
>    inside a skill directory. A single-skill pull is *discoverable and entirely
>    non-functional*, which is worse than not being listed. The accurate claim: the skills
>    are standard-**conformant** (so the ecosystem can index and display them) but not
>    standard-**separable** — install the suite.
> 2. **The `AGENTS.md` template ships as generated output, not as a file.** No
>    `templates/AGENTS.md` exists; the prose is the `PREAMBLE` constant in
>    `bin/agents_md.py` and the skill table is rendered from the store, deliberately, so
>    the skill list cannot go stale. See the correction under design §4.1.

### 4.2 The `freya` launcher — the keystone

Ship one small self-locating entrypoint, **`freya`**, that the installer puts on `PATH`. It resolves the suite's location via Python's `__file__` and dispatches to the right script. This single move de-Claude-ifies both *invocation* and *path resolution*:

- SKILL.md invocations become clean and agent-agnostic: **`freya code-graph impact <file>`** — no `${CLAUDE_PLUGIN_ROOT}`, no absolute paths, no per-agent variable.
- Intra-suite script references self-locate via `__file__` (already portable).
- The "where am I" logic lives in **one** place instead of every SKILL.md, and works identically on Claude, Copilot, and any shell-capable agent.

### 4.3 Orchestration — decouple the unit-of-work from the scheduler; degrade parallel → sequential

Make each "worker" a standalone runnable unit; "parallel vs sequential" is then a *scheduling* choice the host makes. Split by kind of fan-out:

- **Deterministic fan-out** (build the graph over many files, fingerprints) → handled **inside** a `freya` command; portable everywhere, no agent primitive needed.
- **LLM fan-out** (`scan` discovery, security workers, `wrap-up` coordination) → SKILL.md describes **N self-contained tasks** + a hint: *"parallelize if your agent supports subagents, else sequential."* The host's own mechanism (Claude Task tool / Copilot delegation / `/fleet`) schedules; the **worker task definition stays agent-neutral**, separate from the scheduling. Degrades cleanly on Aider / Gemini CLI.

### 4.4 Updates — manual, notify-only

- **`freya update`** — manual, deliberate: re-fetches the latest into the canonical store and re-links. Git is invisible to the user (the launcher wraps it).
- The launcher runs a **throttled (≈ daily) notify-only** check: *"update available — run `freya update`."* It never changes anything on its own.
- **No auto-apply** for now — an auto-update that silently pulls latest `main` onto the work laptop mid-task is exactly the wrong behavior for a toolkit that gates `wrap-up`.
- **Escape hatch (documented, not built):** if auto-apply is ever wanted, add a lightweight **`stable`** tag/branch — develop on `main`, bump `stable` deliberately, and have auto-apply follow `stable`, never `main`. Not needed while updates are manual.

### 4.5 De-Claude-ify checklist

- `${CLAUDE_PLUGIN_ROOT}` → the `freya` launcher + `__file__` self-location (§4.2).
- `/freya-devkit:*` invocation → standard skill discovery + `freya <command>`.
- `.claude-plugin/` marketplace manifest → the standard `.agents/skills` layout (§4.1).
- Claude-only `SKILL.md` extensions (e.g. `context: fork`) → agent-neutral orchestration (§4.3).

### 4.6 Layered architecture

- **Agent Skills (`SKILL.md`)** — the portable unit (already have).
- **`freya` launcher** — self-location + a clean cross-agent command surface (new).
- **`AGENTS.md`** — a small per-project primer, opt-in via `freya init` (new).
- **Own installer** — canonical store + symlink/copy placement per agent (new).
- **MCP — considered and dropped.** Our tools are local Python CLIs the agent runs via bash from the skill; MCP would add a server to build/run/maintain for no gain. Revisit only for a shell-less agent or a hosted-service future.

## 5. Dual distribution (keep both paths)

- **Claude Code:** the existing plugin/marketplace install stays (best-in-class on Claude).
- **Everyone else:** the new portable installer + `freya` launcher.

Both draw from the *same* standard-conformant skills — one source of truth, two install paths.

## 6. Deferred to the implementation plan (minor)

The design is settled; these are implementation details, not open design questions:

- Exact `freya` self-location + `PATH` mechanism (console-script vs symlinked shim vs installer-written path).
- Whether the canonical store is a managed git clone or a shallow-fetched snapshot (drives what `freya update` does internally).
- Whether to also offer a `curl … | sh` bootstrap in addition to clone + `install.sh`.
- Optional per-agent niceties (e.g. a Copilot custom-agent definition for the worker role) — instruction-based is the portable baseline.
- Per-flow orchestration wording for each `scan` / security / `wrap-up` worker.

## 7. Next steps

1. Turn this vision into a concrete **design spec**, then an **implementation plan** (writing-plans).
2. Implement for **Copilot + Claude**; prove the whole workflow runs on both.
3. Then generalize to more agents → Track B (polyglot) → the subagent/docs audit.

## Sources (landscape, 2026-07-13/14)

- Agent Skills open standard — <https://agentskills.io> ; Anthropic: <https://www.anthropic.com/engineering/equipping-agents-for-the-real-world-with-agent-skills>
- `AGENTS.md` — <https://agents.md/>
- GitHub Copilot agent skills + scopes — <https://docs.github.com/en/copilot/how-tos/copilot-on-github/customize-copilot/customize-cloud-agent/add-skills>
- VS Code subagents — <https://code.visualstudio.com/docs/copilot/agents/subagents> ; multi-agent — <https://code.visualstudio.com/blogs/2026/02/05/multi-agent-development>
- Parallel-subagent support matrix + cost — <https://ssojet.com/blog/parallel-sub-agent-coding-tools>
- Canonical store + symlinks — <https://developer.atlassian.com/cloud/twg-cli/agents/skills/> ; skills.sh update model — <https://dev.to/toyama0919/managing-ai-agent-skills-with-npx-skills-a-practical-guide-2an8> ; skill script path resolution — <https://github.com/orgs/community/discussions/190400>
