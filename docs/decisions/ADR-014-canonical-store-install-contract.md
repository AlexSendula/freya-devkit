---
id: ADR-014
title: Install the whole suite from a canonical store by symlink, prefix in the repo, and touch only what we created
status: accepted
created: 2026-08-19
updated: 2026-08-19
tags:
  - portability
  - installer
  - distribution
  - update
  - agents-md
  - safety
---
# ADR-014: Install the whole suite from a canonical store by symlink, prefix in the repo, and touch only what we created

## Decision

One distribution contract, five clauses.

**The checkout is the store.** The installer materializes the suite once, then symlinks each `freya-<skill>` directory into every agent's skills directory (`~/.claude/skills`, `~/.copilot/skills`, preferring the cross-agent `~/.agents/skills`), with `--copy` as the fallback where symlinks are hostile. Default scope is global. The Claude marketplace plugin remains a second install path over the same skills. The skills are standard-*conformant* but not standard-*separable*: you install the suite, never an individual skill.

**The `freya-` prefix lives in the repository.** All ten skill directories and their frontmatter `name:` values carry it on disk; installation rewrites nothing.

**`freya update` is git-only and never automatic.** Fetch plus `merge --ff-only` in the existing checkout (`bin/updater.py:242`), then re-link. It refuses with a distinct, actionable message and exit 2 on a dirty tree, a missing upstream, a non-git store, an unreachable remote, or a diverged branch — no rebase, no merge commit, no stash. Any `freya` call runs a throttled (~24h) staleness check via synchronous `git ls-remote` under a hard 2s timeout, printed to stderr, wrapped so any exception is swallowed and the exit code is never altered, stamping its timestamp even on failure so an offline machine goes quiet for a day. `FREYA_NO_UPDATE_CHECK=1` silences it; `doctor` runs it unthrottled.

**`freya init` writes `AGENTS.md` and installs nothing.** Run explicitly inside a project, it emits a fixed preamble plus a skill table rendered at run time from each SKILL.md description, inside `freya-devkit:begin`/`end` markers. No file means create; no markers means append with existing prose never rewritten; markers present means replace between them, so a second run produces no diff. Malformed markers — unpaired, or `end` before `begin` — refuse with exit 2 and change nothing.

**Every destructive path is gated on ownership.** Targets classify as `create` / `ok` / `foreign` / `occupied` (`bin/installer.py:50`). A real file or directory is *always* `occupied` and always blocks (`bin/installer.py:146`); `--force` may replace a foreign symlink and nothing else; `uninstall` removes only symlinks pointing into this store. A multi-agent install plans every agent and the launcher before mutating anything.

## Rationale

**Why our own installer over the ecosystem's.** skills.sh, `gh skill`, skillz and Atlassian TWG are all built for a single skill from a repo-root SKILL.md, and fit a coupled suite poorly — the documented "install related skills independently, get behavioral drift" problem. So the installer is ours; the store-plus-symlink pattern underneath is theirs and proven: update once, every agent sees it.

**Why non-separable.** The engine's own design rules it out. Every script resolves siblings through `Path(__file__).resolve().parents[2] / "freya-<other-skill>" / "scripts"`, so a skill pulled alone fails at import. And since every SKILL.md invokes `freya`, it additionally needs the launcher, `bin/commands.json` and the store — none of which travel inside a skill directory. A single-skill pull would be discoverable and entirely non-functional, which is worse than not being listed at all.

**Why the prefix is in the repo, not applied at install.** A shared `~/.agents/skills/` has no namespace and the roster includes very generic names (`status`, `code-graph`, `wrap-up`, `docs-manager`), so prefixing is necessary. Applying it at install time was the original plan and turned out to be not merely awkward but *impossible*: the Agent Skills specification requires a skill's `name` to equal its parent directory name (agentskills.io/specification, verified 2026-07-30). A link `~/.claude/skills/freya-code-graph → <store>/skills/code-graph` yields a SKILL.md declaring `name: code-graph` under a `freya-code-graph` parent — spec-invalid, failing `skills-ref validate`. Rewriting `name:` at install forfeits symlinking entirely and makes the installed copy diverge from the store on every update. Phase 2 had already rewritten all 173 cross-references, so renaming the ten directories made the repo self-consistent; conformance rule R8 (name equals parent directory) was added *first* so the rename was verifiable, green before and after.

The cost was a breaking change for 0.1.0 users — all ten invocation names moved (`/freya-devkit:wrap-up` → `/freya-devkit:freya-wrap-up`), signalled only by the version bump and recorded in [`../migrations/skill-rename.md`](../migrations/skill-rename.md). The design's own migration line, "existing Claude users keep working after a one-time freya-on-PATH step", is wrong for exactly this reason.

**Why updates notify rather than apply.** An auto-update that silently pulls latest `main` onto a work laptop mid-task is exactly the wrong behaviour for a toolkit that gates `wrap-up`.

The refusals are load-bearing, not politeness. Without the unreachable-remote guard, the flow reaches `merge-base` against the stale local ref and reports "already up to date" with exit 0 over a store that is not current — predicted by pre-implementation review, reproduced by mutation, then confirmed live refusing correctly ("could not fetch origin", exit 2, in 0.13s). Four refusals were exercised live; divergence was observed by accident when local commits put a sandbox clone ahead of origin. Notify timings measured: `ls-remote` 0.551s, next call served from cache 0.083s.

The swallowed exception in the staleness check is the single justified bare `except` in the codebase: the check is housekeeping bolted onto unrelated commands and must never break one. Its message deliberately does not claim a commit count, which would require a real fetch.

The reload reminder exists because a mid-session update is invisible or worse. The skill registry is snapshotted at session start while the body is read from disk at invocation, so an *edited* skill is picked up by Copilot but not Claude once loaded, an *added* skill is not seen at all, and a *removed* skill is still offered and then fails with a raw `ENOENT`.

**Why AGENTS.md is per-project and rendered.** It is the cross-tool instructions standard (Agentic AI Foundation, ~30 tools) and a per-repository file by convention, so it has no home in a global install — and writing into someone's repo unasked, or clobbering an existing file, is intrusive. A static template would be a tenth place the skill list lives and would go stale on the next skill added; a bare pointer teaches a reading agent nothing about when to reach for what.

**Why the ownership gates.** The toolkit runs unattended inside an agent session, in directories full of other people's skills, so a destructive mistake is both likely and unlikely to be noticed. Each rule was written against a concrete failure:

- The install barrier was extended mid-flight after review found `link_launcher` ran its blocker check *after* the per-agent loop — so a real file at `~/.local/bin/freya` let every agent install in full and only then exited 2. That is precisely the "mutated but reported as failed" shape the barrier removes.
- `_write_target` originally used `open(target, "w")`, which truncates before writing a byte, so a mid-write failure left the user's `AGENTS.md` empty. It now goes through a temp file plus `os.replace`.
- `os.replace` on an *unresolved* path could clobber a symlinked `AGENTS.md` with a plain file and reset permissions to the umask default. The path is resolved and the original's mode copied over.
- macOS `/var → /private/var` already caused a real bug where `uninstall_agent` silently removed nothing.

Classification and blocker logic are mutation-tested: turning `occupied` into `create`, or dropping the ownership comparison in `uninstall_agent`, must break a named test.

Proven live in phase 6 from a fresh clone: ten skills linked per agent with `doctor` exiting 0 on every check; a second install printed `skipped` for all 21 entries; a `--copy` install produced real directories each carrying a `.freya-install` marker, with doctor reporting `claude (10, symlink), copilot (10, copy)`; a moved checkout produced "orphaned entries: 20" naming the old path and the remedy, repaired by `install.sh --force`; uninstall removed its own 20 entries and left a planted `freya-not-ours` directory untouched. `AGENTS.md` validated live: ten table rows, each a readable one-line summary, zero empty cells — the payoff of the block-scalar frontmatter reader, which a naive parser would have left as ten bare `|` values. A second run reported "already up to date" and left the file byte-identical. Against a CRLF file whose prose mentions the marker mid-sentence, the block was appended, the file still reported CRLF terminators, and the user's original bytes remained an unmodified prefix.

## Rejected Alternatives

- **Depend on skills.sh / `gh skill` / skillz.** Built for a single skill from a repo-root SKILL.md; a coupled suite installed piecemeal produces the documented behavioral-drift problem.
- **Claude marketplace as the only distribution.** Drops every non-Claude agent — the entire point of the portability track.
- **Per-repo vendored install as the default.** `--project`/`--global` were specified as opt-in, then deliberately deferred.
- **Copy-only placement.** Loses update-once-see-everywhere, the whole benefit of the canonical store.
- **Advertising that the ecosystem can pull individual skills.** Retracted 2026-08-18: a single-skill pull is discoverable and entirely non-functional.
- **Installer-applied prefix over short repo names.** Spec-invalid — `name` must equal the parent directory — and rewriting `name:` on copy forfeits symlinking and diverges from the store on every update.
- **No prefix at all**, or **relying on Claude's plugin namespacing.** The shared store has no namespace, and the namespacing exists only on the plugin path.
- **Copy-only install with rewriting on copy.** Abandons checkout-is-the-store and leaves `freya update` unable to refresh by pulling.
- **A tarball fallback for non-git stores.** Needs a destructive replace path that cannot be tested offline.
- **A managed clone under `~/.freya`.** Overturns the shipped store model.
- **A detached background update probe.** Orphaned children, a cache race, and news that arrives one run late.
- **Reading the already-fetched ref instead of hitting the network.** Free, but would almost never fire.
- **Auto-apply following `main`.** Wrong for a toolkit that gates `wrap-up`; the documented stable-tag escape hatch was deliberately left unbuilt.
- **Rebase, merge or stash past a diverged or dirty tree.** Silent history rewriting on someone's checkout.
- **Telling users to restart the session after an update.** Unnecessary: both hosts reload in place — `/reload-skills` on Claude Code, verified present in the 2.1.220 binary, `/skills` on Copilot.
- **Printing the reload reminder on every update run.** Noise on the common no-op path.
- **Writing `AGENTS.md` as part of the global install.** It is a per-repository file; writing into a user's repo unasked is intrusive.
- **Shipping `templates/AGENTS.md`.** Reversed by the phase-5 spec before implementation, though the design record was never amended — so a contributor looking for the template found nothing. To change what `freya init` writes, edit `bin/agents_md.py`.
- **Duplicating skill instructions inside the block**, or **skipping `AGENTS.md` entirely.** One goes stale, the other teaches a reading agent nothing.
- **Clobbering or reformatting an existing `AGENTS.md`**, or **best-effort repair of malformed markers.** Guessing at a user's file is how you destroy it.
- **Treating a marker string found anywhere in the file as a managed block.** Tried and reversed: it locked out any user who merely documented freya-devkit in prose or showed the marker in a fenced example. `_locate_marker` now counts only start-of-line occurrences.
- **Letting `--force` replace a real file or directory.** `--force` is for links we could have made, not for other people's data.
- **Installing agent by agent, aborting on the first blocker.** Leaves a half-installed machine reported as a failure.

## Revisit Conditions

- **A team asking for a committed, vendored install.** `--project` is the shipped-shaped gap: `install.sh --project` fails argparse today, so teams wanting a committed install have no supported route, and the deferral rationale lives only in a phase plan.
- **Windows is the weak point.** `install.ps1` and `--copy` have never run there, symlink privilege is untested, and `freya update` re-copies all ten skills even when nothing changed — each rewrite a brief window in which a skill is absent, on the platform where copy is the *normal* mode. Comparing content, or stamping the store HEAD in the `.freya-install` marker, would make the common case free.
- **Concurrent installs still race** between classify and link. Unlocked and non-destructive today; revisit if that stops being true.
- **If the Agent Skills spec drops the name-equals-directory rule**, or a namespacing mechanism lands in the shared store format, the repo-side prefix becomes redundant.
- **If a non-git distribution channel becomes primary**, the git-only update assumption stops holding. If users routinely hit the 2s notify timeout on slow networks, revisit the timeout.
- **If `AGENTS.md` gains a standardised machine-readable section format**, the hand-rolled marker protocol should give way to it.
