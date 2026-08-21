# Migration: every skill is now `freya-<skill>` (0.1.0 → 0.2.0)

**Applies to everyone.** In 0.2.0 the skill *directories* carry the `freya-` prefix, and
so does each `SKILL.md`'s `name:` field. Invocation names changed with them. There is no
alias: the old names are directory names that no longer exist.

## Why

Two constraints met:

- The Agent Skills spec requires a skill's frontmatter `name` to equal its parent
  directory name. So the prefix cannot be applied at install time — a renamed directory
  with an unrenamed `name:` is non-conformant.
- The portable install target is a shared, **un-namespaced** skills directory
  (`~/.agents/skills/`, `~/.copilot/skills/`). Names like `status`, `code-graph` and
  `wrap-up` collide there with anything else a user has installed. Claude's plugin
  namespace hid that problem; nothing else has one.

The repo therefore renamed its directories, and the installer applies no prefix. (The
design originally decided the opposite; the reversal and its cause are recorded in
[`../decisions/ADR-014-canonical-store-install-contract.md`](../decisions/ADR-014-canonical-store-install-contract.md).)

## The mapping

| 0.1.0 | 0.2.0 |
|---|---|
| `code-graph` | `freya-code-graph` |
| `docs-manager` | `freya-docs-manager` |
| `spec-manager` | `freya-spec-manager` |
| `behavior-graph` | `freya-behavior-graph` |
| `behavior-runner` | `freya-behavior-runner` |
| `codebase-security-scan` | `freya-codebase-security-scan` |
| `codebase-security-resolver` | `freya-codebase-security-resolver` |
| `dependency-vulnerability-check` | `freya-dependency-vulnerability-check` |
| `wrap-up` | `freya-wrap-up` |
| `status` | `freya-status` |

On Claude's marketplace path each is namespaced by the plugin as well, so
`/freya-devkit:wrap-up` becomes `/freya-devkit:freya-wrap-up`.

## What you have to change

1. **Anything that names a skill.** Saved prompts, aliases, team runbooks, a project's
   `AGENTS.md` or `CLAUDE.md`, CI steps. Search for `freya-devkit:` and for the bare old
   names; add the `freya-` prefix.
2. **Nothing else.** Artifact layout, command semantics and the `knowledge-base/`
   contents are unchanged by this rename.

## Migrating, per install path

**Claude Code, via the marketplace plugin**

```text
/plugin marketplace update freya-devkit
```

Then reload the session (`/reload-skills` or a new session) — an agent reads its skill
list once at session start, so until it reloads the old names are still offered and then
fail on use.

**Any agent, via `install.sh`**

```bash
freya update
```

`freya update` fast-forwards the store and re-links: the ten new `freya-*` directories
get links and the ten old ones are pruned as orphans. Reload the session afterwards, for
the same reason. If you installed before the launcher existed, run `./install.sh` from
the checkout once instead.

Confirm with:

```bash
freya doctor
```

which lists the linked skills per agent and flags anything orphaned or double-registered.

## The `freya` command surface is *not* affected

`freya <command>` (space) is the CLI; `freya-<skill>` (hyphen) is a skill name. Only the
second changed. `freya code-graph --build` was already spelled that way and still is.
