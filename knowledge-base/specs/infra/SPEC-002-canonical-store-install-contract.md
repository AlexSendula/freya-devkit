---
id: SPEC-002
title: Canonical-store install contract — install, update, uninstall
category: infra
tags: [installer, distribution, symlink, ownership, update, windows, safety]
status: implemented
certainty: 85
created: 2026-08-21
updated: 2026-08-24
related_code:
  - bin/installer.py
  - bin/updater.py
  - bin/freya_cli.py
  - install.sh
  - install.ps1
intentional_decisions:
  - "A real file or directory always blocks; --force extends only to things carrying proof they are ours"
  - "Ownership is decided lexically by path_key, never by touching the filesystem"
  - "On Windows the launcher is a generated shim plus a freya.cmd, written rather than symlinked"
  - "An ordinary command makes a throttled network call whose every failure is swallowed"
  - "freya update fast-forwards or refuses — never rebase, merge or stash"
behaviors:
  - behavior_id: BEH-006
    title: Installing links every skill in the store into the agent's skills directory
    state: proposed
    level: unit
    adapter: unittest
    locator: bin/test_installer.py#ApplyTest.test_creates_symlinks_that_resolve_into_the_store
  - behavior_id: BEH-007
    title: A `--copy` install materializes real directories, each carrying a marker naming this store
    state: proposed
    level: unit
    adapter: unittest
    locator: bin/test_installer.py#ApplyTest.test_copy_install_writes_a_marker_naming_its_source
  - behavior_id: BEH-008
    title: A target that cannot be proven ours blocks the install and survives untouched, `--force` included
    state: proposed
    level: unit
    adapter: unittest
    locator: bin/test_installer.py#ApplyTest.test_refuses_to_touch_a_real_directory_even_with_force
  - behavior_id: BEH-009
    title: A blocker anywhere in the invocation — including the launcher target — leaves every agent untouched
    state: proposed
    level: integration
    adapter: unittest
    entry: bin/installer.py
    locator: bin/test_installer.py#MultiAgentAtomicityTest.test_a_blocked_launcher_leaves_every_agent_untouched
  - behavior_id: BEH-010
    title: Uninstall removes only the entries provably ours and leaves everything else in place
    state: proposed
    level: unit
    adapter: unittest
    locator: bin/test_installer.py#UninstallTest.test_removes_only_links_into_this_store
  - behavior_id: BEH-011
    title: "`freya update` fast-forwards the store, re-links every agent, and says how to pick the change up"
    state: proposed
    level: integration
    adapter: unittest
    entry: bin/updater.py
    locator: bin/test_updater.py#UpdateTest.test_a_real_update_says_how_to_pick_it_up
  - behavior_id: BEH-012
    title: "`freya update` refuses and names the fix when the branch has no upstream"
    state: proposed
    level: unit
    adapter: unittest
    locator: bin/test_updater.py#PreconditionsTest.test_a_missing_upstream_names_the_fix
---

# Canonical-store install contract — install, update, uninstall

## What

The checkout **is** the store. `freya install` materializes nothing new: it
links each `freya-*` skill directory from `<store>/skills/` into every detected
agent's personal skills directory (`~/.claude/skills`, `~/.agents/skills`) and
puts the launcher at `~/.local/bin/freya`. `--copy` is the fallback where
symlinks are hostile, and every copied directory carries a `.freya-install`
marker naming the store it came from.

The guarantee that ties the three commands together is **ownership**: install,
`--force`, `freya update`'s re-link and `freya uninstall` may only ever remove
something that carries proof this store created it — a symlink resolving into
this store's `skills/`, a marker file naming it, or a launcher shim tagged with
it. Anything else is reported and left alone. `freya doctor`'s `agents`,
`orphaned entries` and `duplicate install` rows are the read-only view of that
same classification.

`freya update` keeps the store current the only way a git checkout can be kept
current without surprising its owner: fetch, fast-forward, re-link — or refuse
with an actionable message. Nothing here ever updates on its own; a separate
throttled check only *says* the remote has moved.

Out of scope: what the skills themselves do, and `freya init` (SPEC-003).

## Why

The suite is not separable — every script resolves siblings through the store's
directory layout, and every SKILL.md invokes `freya`, which lives in `bin/` and
not inside any skill — so a single-skill pull would be discoverable and entirely
non-functional. That, and the reasoning for the store-plus-symlink shape, the
repo-side `freya-` prefix, and git-only updates, are recorded in
[ADR-014](../../decisions/ADR-014-canonical-store-install-contract.md); this
spec records the observable guarantees rather than re-arguing them.

The ownership gates exist because this code runs unattended inside an agent
session, in directories full of other people's skills, where a destructive
mistake is both likely and unlikely to be noticed. Each rule in the code is
written against a concrete failure that was actually observed — a blocker that
only fired after every agent had already been installed, a `copytree` that
destroyed a working skill when it failed partway, a macOS `/var → /private/var`
mismatch that made `uninstall` silently remove nothing.

The refusals in `freya update` are load-bearing for the same reason: without the
unreachable-remote guard the flow reached `merge-base` against a stale local ref
and reported "already up to date" with exit 0 over a store that was not current.

**Certainty (85).** The intent is unusually well evidenced: ADR-014 states the
contract clause by clause, `installer.py` names the failure each guard was
written against, and the behaviors below are pinned by tests whose names state
the guarantee. Held below 90 because these were inferred from code rather than
authored, and because two of the shipped paths (`install.ps1`, `--copy` on real
Windows) are documented in ADR-014 as never having run on that platform, so what
a Windows user actually observes is partly inference.

## Behavior

| Behavior | State | Verified by |
|----------|-------|-------------|
| BEH-006 Installing links every skill in the store into the agent's skills directory | proposed | `bin/test_installer.py#ApplyTest.test_creates_symlinks_that_resolve_into_the_store` (unittest) |
| BEH-007 A `--copy` install materializes real directories, each carrying a marker naming this store | proposed | `bin/test_installer.py#ApplyTest.test_copy_install_writes_a_marker_naming_its_source` (unittest) |
| BEH-008 A target that cannot be proven ours blocks the install and survives untouched, `--force` included | proposed | `bin/test_installer.py#ApplyTest.test_refuses_to_touch_a_real_directory_even_with_force` (unittest) |
| BEH-009 A blocker anywhere in the invocation — including the launcher target — leaves every agent untouched | proposed | `bin/test_installer.py#MultiAgentAtomicityTest.test_a_blocked_launcher_leaves_every_agent_untouched` (unittest) |
| BEH-010 Uninstall removes only the entries provably ours and leaves everything else in place | proposed | `bin/test_installer.py#UninstallTest.test_removes_only_links_into_this_store` (unittest) |
| BEH-011 `freya update` fast-forwards the store, re-links every agent, and says how to pick the change up | proposed | `bin/test_updater.py#UpdateTest.test_a_real_update_says_how_to_pick_it_up` (unittest) |
| BEH-012 `freya update` refuses and names the fix when the branch has no upstream | proposed | `bin/test_updater.py#PreconditionsTest.test_a_missing_upstream_names_the_fix` (unittest) |

Adjacent guarantees that already have tests but no behavior record of their own,
because this scan's id block was exhausted: a second install reporting `skipped`
for every entry, `--force` replacing a foreign *symlink* or a foreign
marker-carrying copy, the crash-safe staged copy, `freya update` refusing a
dirty or diverged tree, and each `doctor` orphan/shadow clause.

## Intentional Design Decisions

### A real file or directory always blocks, and `--force` is not an override for it

**Decision**: `classify` reports a real path as `occupied` unless it carries
proof it is ours, and `occupied` blocks with or without `--force`. `--force`
extends only to a *foreign symlink*, a copy directory whose `.freya-install`
marker names another store (deleted whole, edits and all), and a launcher shim
tagged with another store. The one place the installer deletes a directory is
guarded by the marker, and an unreadable or undecodable marker means "not ours",
never "probably ours".

**Rationale**: `--force` is for links we could have made, not for other people's
data. The alternative — letting `--force` mean "remove whatever is in the way" —
is a `shutil.rmtree` over an arbitrary user directory running unattended inside
an agent session.

**Security Scan Note**: the `shutil.rmtree` calls in `installer.py` and
`updater.py` are gated on positive ownership proof and are intentional; see
ADR-014. The classification and blocker logic are mutation-tested — turning
`occupied` into `create`, or dropping the ownership comparison in
`uninstall_agent`, must break a named test. Flag a change that widens what
`--force` accepts, not the deletion itself.

### Ownership is decided lexically, never by touching the filesystem

**Decision**: `path_key` normalizes, case-folds per platform and strips
Windows' `\\?\` extended-length prefix, and every ownership comparison goes
through it. Paths are compared as strings; `resolve()` is applied only where a
parent is known to exist.

**Rationale**: half the paths being compared are *dangling* — a link left behind
by a moved checkout is exactly the case `doctor` must explain — so anything that
touched the filesystem would either raise or silently rewrite the very path the
user needs to see. The lexical rule is also what made the Windows fix possible:
`os.readlink` returns `\\?\C:\...` where `Path.resolve()` returns `C:\...`, and
comparing the two spellings directly classified every link a Windows install had
just made as `foreign`.

**Security Scan Note**: string comparison of paths is usually a smell (symlink
and normalization bypasses). Here it is deliberate and cannot be a privilege
bypass: a lexical mismatch produces the *safe* verdict (`foreign`/`occupied`),
which refuses to remove anything.

### On Windows the launcher is a written shim plus a generated `freya.cmd`

**Decision**: on Windows — with or without `--copy` — `bin/freya` is not
symlinked. A generated Python shim carrying the store's `bin/` path is written
to the launcher target, plus a `freya.cmd` beside it whose interpreter is
`sys.executable` rather than a bare `python`. The `.cmd` is generated by the
installer rather than shipped in the store, and it never outlives the launcher
it drives. A refused symlink (WinError 1314, Developer Mode off) falls back to
the same shim rather than failing the install.

**Rationale**: `freya` is extensionless and cmd.exe/PowerShell resolve bare
names through `PATHEXT`, so without the `.cmd` every `freya <command>` in every
SKILL.md is dead on that platform. A verbatim copy of `bin/freya` would import
nothing, because that file finds `freya_cli` next to its own realpath — hence a
*generated* shim, whose tag line doubles as its ownership proof. A bare `python`
on modern Windows is as likely to be the Microsoft Store alias stub as an
interpreter.

**Security Scan Note**: the installer writing an executable file into
`~/.local/bin` with an interpreter path baked in is intentional and is the only
way the launcher is runnable on Windows. It is gated on the same ownership proof
as everything else (`SHIM_TAG`), and `--force` will not overwrite an untagged
file there. ADR-013 records this as the residual gap in the single-launcher
decision.

### An ordinary command makes a network call, and every failure of it is swallowed

**Decision**: any `freya` command outside `NO_NOTIFY` runs a throttled (~24h)
synchronous `git ls-remote` under a hard 2s timeout to say whether the remote
has moved, prints to stderr, stamps its timestamp even on failure, and wraps the
whole thing so no exception can escape — the one deliberate bare `except` in the
codebase. `FREYA_NO_UPDATE_CHECK=1` silences it; `FREYA_DEBUG` makes a
permanently broken check visible; `doctor` runs it unthrottled.

**Rationale**: the check is housekeeping bolted onto unrelated commands, so it
must never break one or alter its exit code. Stamping on failure is what keeps
an offline machine from paying the timeout on every command. The message
deliberately does not claim a commit count, which would require a real fetch.

**Security Scan Note**: the bare `except` and the "silently ignored" state-file
write in `updater.notify` / `update_message` are intentional, not swallowed
errors that hide a fault — `FREYA_DEBUG` surfaces them on demand. The outbound
call is to the store's own configured git remote and writes nothing into the
repository.

### `freya update` fast-forwards or refuses — it never rebases, merges or stashes

**Decision**: refusal with exit 2 and a distinct message for a dirty tree, a
missing upstream, a detached HEAD, a local-only upstream, a non-git store, an
unreachable remote, or a diverged branch. On success it fast-forwards, re-links
every agent that already had the suite, and prints the reload hint only when the
store actually moved. Updates are never applied automatically.

**Rationale**: a merge commit, a rebase or a stash in someone's toolkit checkout
is silent history rewriting on work the toolkit does not own; an auto-update
that pulls latest `main` mid-task is exactly wrong for a toolkit that gates
`wrap-up`. Re-linking is not optional after a pull: a symlink picks up an edit
for free, but a skill *added* has no link and one *deleted* leaves a dangling
one, and a copy install tracks nothing at all.

**Security Scan Note**: `freya update` runs `git` in the store directory with a
remote name taken from the branch's own upstream configuration, not from user
input, and refuses to act on any tree it did not find clean. Its re-link step
prunes only entries that audit as ours. Which `git` binary that is, is decided by
`exec_path` — see below.

### `git` is resolved, never spelled; and there is no degraded resolver

**Decision**: `updater.git` resolves its program through the shared `exec_path` module, which
refuses a resolution that is not already absolute. The import is **guarded**, and a store where
the resolver is missing does not fall back to a bare `"git"` — the git-backed features refuse
with a stated reason instead.

**Rationale**: added 2026-08-24. Two things had to hold at once and they pull opposite ways.

The resolver lives in the code-graph skill rather than beside `bin/`, because `bin/` is not
copied into an agent's skills directory (ADR-030), so a helper here could not be imported from
an installed skill. Reaching the other way is safe for this module specifically: `updater` only
ever runs from the store.

The guard is the load-bearing half, and it was measured rather than reasoned about. `freya_cli`
imports this module *inside* `doctor_checks` and inside the `update` branch, and neither import
is wrapped. A bare `import exec_path` therefore turned a missing skill tree into a
`ModuleNotFoundError` out of `freya doctor` and `freya update` — a traceback from the two
commands whose entire job is to diagnose and repair that exact state. With `exec_path.py` moved
aside, both died at this module's import line while every other command survived.

An earlier draft got this backwards: it reasoned that `exec_path.py` travels in the same
checkout at the same commit, so a store missing it is a hand-broken clone that `git pull`
fixes. The circle is that `git pull` is spelled `freya update` here, and `freya update` was the
command that crashed.

**No fallback to a bare name**, and that is a separate decision from the guard. A resolver that
searched `PATH` on failure would reinstate exactly the hole `exec_path` exists to close
(SEC-002/SEC-003), and it would be a third body of the absoluteness rule. The resolver is
either present and authoritative, or absent and the feature refuses.

**Security Scan Note**: a guarded import whose failure path disables a feature rather than
substituting a default is the design. Flag any change that adds an `or "git"`, and note that
`freya doctor`'s `updates` row reports this refusal by asking `updater.git_program()` directly
(SPEC-001), so the two commands cannot tell different stories about it.

## Related Specs

- [SPEC-001: The `freya` launcher command surface](./SPEC-001-freya-launcher-command-surface.md) — the launcher this contract places on `PATH`, and the `doctor` command that reports on it
- [SPEC-003: The managed AGENTS.md block](./SPEC-003-agents-md-managed-block.md) — the one write that happens inside a user's project, and why it is not part of the install

## Change History

| Date | Change | Reason |
|------|--------|--------|
| 2026-08-24 | Added "`git` is resolved, never spelled; and there is no degraded resolver" | The `exec_path` resolution (SEC-002/SEC-003 family) reached `updater.git`; the guarded import and the refusal to fall back to a bare name are both measured decisions, not incidental |
| 2026-08-21 | Initial spec, inferred from code and tests by the brownfield scan | `freya-spec-manager bootstrap` — all behaviors `proposed`, none reviewed by a human yet |
