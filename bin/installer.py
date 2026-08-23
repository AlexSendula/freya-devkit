#!/usr/bin/env python3
"""Install the freya-devkit suite for one or more coding agents.

The checkout is the canonical store: installing means symlinking each skill
directory into the agent's personal skills directory. Nothing is rewritten,
which is only possible because the store's directory names are already the
installed names (`freya-*`) — the Agent Skills spec requires a skill's `name`
to equal its parent directory.
"""

from __future__ import annotations

import argparse
import os
import shutil
import sys
from collections import namedtuple
from pathlib import Path

#: Only directories with this prefix are ours to install.
SKILL_PREFIX = "freya-"

#: Marker file dropped inside a `--copy` install so a later run — or an
#: uninstall — can prove a real directory is ours. A copied skill is a real
#: directory, so it can't be recognized as ours the way a symlink can (by
#: `readlink`); the marker, containing the source path it was copied from,
#: is the only thing that lets `classify` tell "our copy" from "someone
#: else's directory that happens to have the same name" without ever
#: guessing.
MARKER = ".freya-install"

#: Where each agent reads personal-scope skills. Verified 2026-07-30:
#: - Claude Code reads ~/.claude/skills only; its docs list no cross-agent path.
#: - Copilot reads both ~/.copilot/skills and ~/.agents/skills, so we use the
#:   shared location and skip ~/.copilot/skills to avoid registering twice.
AGENT_TARGETS = {
    "claude": Path.home() / ".claude" / "skills",
    "copilot": Path.home() / ".agents" / "skills",
}

#: The launcher's counterpart to MARKER. `bin/freya` resolves its *own*
#: directory to find `freya_cli`, so a verbatim copy of it placed on PATH would
#: import nothing — a copied launcher has to be a generated shim that carries
#: the store path. That generated line is also the only ownership proof
#: available for it: a real file cannot prove itself by `readlink` the way a
#: symlink can. Matched as a substring so the Python shim (`# ...`) and the
#: Windows `.cmd` shim (`@rem ...`) can share one reader.
SHIM_TAG = "freya-devkit launcher shim for "

#: One intended link. `status` is create | ok | foreign | occupied.
LinkPlan = namedtuple("LinkPlan", "target source status")

#: One entry found in an agent's skills directory, as seen from this store.
#: `status` is ok | stale-store | orphan-skill | foreign | occupied.
AgentEntry = namedtuple("AgentEntry", "path points_at status")


def store_root():
    """The canonical store — the checkout this file lives in."""
    return Path(__file__).resolve().parents[1]


def windows():
    """Are we on Windows? Read through one function, never inline.

    Every Windows-only branch here has to be provable from a Mac or a Linux
    runner as well as from `windows-latest`, and a test can only drive both
    sides of the branch if there is a single seam to patch.
    """
    return os.name == "nt"


#: Windows' extended-length path prefixes, `\\?\C:\...` and `\\?\UNC\srv\...`.
#: The kernel stores a symlink's target as `\??\C:\...`, and `os.readlink`
#: hands that back as `\\?\C:\...`, while `Path.resolve()` strips the prefix
#: again whenever the plain spelling still resolves to the same file. So the
#: two halves of every ownership comparison arrived in different spellings.
#: Found on the first Windows CI run (2026-08-18) and it is a product bug, not
#: a test one: every link a Windows install had just created classified as
#: `foreign`, so `freya install` refused to manage its own links, `freya
#: doctor` reported a healthy install as a moved checkout, and `freya update`
#: skipped every symlinked agent because none of its entries audited `ok`.
_EXTENDED_PREFIX = "\\\\?\\"
_EXTENDED_UNC_PREFIX = "\\\\?\\UNC\\"


def strip_extended_prefix(path):
    """`path` as a string, without Windows' `\\\\?\\` extended-length prefix.

    Only on Windows: `\\\\?\\foo` is a perfectly ordinary POSIX filename, and
    stripping it there would rename a real file out from under the comparison.

    Only for the two prefixed forms that name a path we could also spell
    normally — a drive (`\\\\?\\C:\\...`) or a UNC share (`\\\\?\\UNC\\...`).
    A volume-GUID path (`\\\\?\\Volume{...}\\...`) has no unprefixed spelling
    at all, so it is left exactly as it came; the worst that does is leave one
    such entry classified `foreign`, which is the safe verdict anyway.
    """
    text = str(path)
    if not windows():
        return text
    if text.startswith(_EXTENDED_UNC_PREFIX):
        return "\\\\" + text[len(_EXTENDED_UNC_PREFIX):]
    if text.startswith(_EXTENDED_PREFIX):
        rest = text[len(_EXTENDED_PREFIX):]
        if len(rest) >= 2 and rest[0].isalpha() and rest[1] == ":":
            return rest
    return text


def path_key(path):
    """The comparable identity of a path — the one way ownership is decided.

    Purely lexical, and deliberately so: half the paths compared here are
    *dangling* (a link left behind by a moved checkout), and anything that
    touched the filesystem would either raise or silently rewrite the very
    path we need to show the user.

    `normcase` is what makes `C:\\Users` and `c:\\users` one path on Windows.
    On POSIX it is the identity function, which is exactly right — there,
    two spellings that differ in case are two different files.
    """
    return os.path.normcase(os.path.normpath(strip_extended_prefix(path)))


def same_path(one, other):
    """Are these two spellings of the same path? See `path_key`."""
    return path_key(one) == path_key(other)


def discover_skills(store):
    """Return the sorted freya-* skill directories in the store."""
    skills_dir = store / "skills"
    if not skills_dir.is_dir():
        return []
    return sorted(
        path
        for path in skills_dir.iterdir()
        if path.is_dir() and path.name.startswith(SKILL_PREFIX) and (path / "SKILL.md").is_file()
    )


def classify(target, source):
    """Decide what a single target path means for us.

    Never reports a real file or directory as anything but `occupied` —
    *unless* it carries our MARKER naming this exact source, which is the
    one way a `--copy` install can be recognized as ours. A directory
    without the marker, or whose marker names some other source, is never
    anything but `occupied`/`foreign`: the installer must not be able to
    destroy something it did not create.
    """
    if target.is_symlink():
        try:
            points_at = Path(strip_extended_prefix(os.readlink(target)))
        except OSError:
            return "foreign"
        if not points_at.is_absolute():
            points_at = (target.parent / points_at)
        return "ok" if same_path(points_at, source) else "foreign"
    if target.is_dir():
        marker = target / MARKER
        if marker.is_file():
            try:
                content = marker.read_text(encoding="utf-8").strip()
            # A marker that can't be decoded is no more ours than one that
            # can't be read at all — both mean the directory can't be proven
            # to be ours, so both fall back to the same verdict.
            except (OSError, UnicodeDecodeError):
                return "foreign"
            # Through `same_path` like every other ownership test, not string
            # equality: on Windows the store the marker was written from may
            # be spelled `C:\` where this run says `c:\`, and one path in two
            # spellings must not read as two stores.
            return "ok" if same_path(content, source) else "foreign"
    if target.exists():
        return "occupied"
    return "create"


def plan_agent(store, agent, target_dir=None):
    """Return the LinkPlan list for installing every skill for one agent."""
    if target_dir is None:
        try:
            target_dir = AGENT_TARGETS[agent]
        except KeyError:
            raise ValueError(f"unknown agent: {agent!r} (known: {', '.join(sorted(AGENT_TARGETS))})")
    plans = []
    for source in discover_skills(store):
        target = target_dir / source.name
        plans.append(LinkPlan(target, source, classify(target, source)))
    return plans


def _link_target(entry):
    """The absolute path a symlink names, normalized but not resolved.

    Deliberately not `.resolve()`: a link left behind by a moved checkout is
    dangling, and resolving it would either raise or silently rewrite the very
    path we need to show the user.

    The extended-length prefix is dropped here rather than at each comparison
    because this value is *also* what doctor prints. The first Windows CI run
    put `\\\\?\\C:\\Users\\...` in front of the user in a warning about a store
    that had not moved at all.
    """
    points_at = Path(strip_extended_prefix(os.readlink(entry)))
    if not points_at.is_absolute():
        points_at = entry.parent / points_at
    return Path(os.path.normpath(points_at))


def target_key(path):
    """A physical identity for an install target, for the cross-agent dedupe.

    Comparing `Path`s compares strings, so two agents whose skills directories
    are the same physical directory through a symlinked parent
    (`~/.claude/skills -> ~/.agents/skills`, a real way to share one install)
    both planned `create` for it, the first applied, and the second died with
    EEXIST — after the first agent was fully installed. Only the *parent* is
    resolved: the target itself is precisely the thing that does not exist yet.
    Through `path_key` because two spellings of one path are one path on
    Windows — including the extended-length one, which `realpath` returns
    whenever the plain spelling would not resolve back to the same file.
    """
    return (path_key(os.path.realpath(str(path.parent))), path_key(path.name))


def _entry_status(points_at, skills_dir, name):
    """Where an entry's target places it relative to this store.

    Every comparison goes through `same_path`, including the two on bare
    names: a name is a one-component path, and on Windows `Freya-Status` and
    `freya-status` are one entry. Mixing `Path.__eq__` (case-insensitive on
    Windows) with `str.__eq__` (never) is how one half of a verdict came out
    case-blind and the other half did not.
    """
    if same_path(points_at.parent, skills_dir) and same_path(points_at.name, name):
        # Ours by location *and* by name. Without the name check a hand-edited
        # link (`freya-status -> <store>/skills/freya-code-graph`) audited as
        # `ok` while classify called the same entry `foreign` — doctor then
        # reported the agent as correctly installed, install refused to touch
        # it, and update skipped it without printing a line.
        return "ok" if points_at.exists() else "orphan-skill"
    if same_path(points_at.parent.name, "skills") and same_path(points_at.name, name):
        # Same shape, different store: a moved checkout, or a second one.
        # We cannot tell those apart and do not need to — both mean "not here".
        return "stale-store"
    return "foreign"


def audit_agent(store, agent, target_dir=None):
    """Classify every `freya-*` entry in an agent's skills directory.

    The counterpart to `plan_agent`, which iterates the skills in the *store*
    and so cannot see an entry whose skill no longer exists there, nor one left
    behind when the checkout moved. This walks the *agent's* directory instead,
    which is what `freya update` needs to prune and `freya doctor` needs to warn.

    Ownership rules are exactly `classify`'s: a symlink is ours if it points
    into this store's `skills/`, and a real directory is ours only if it carries
    our MARKER naming this store. Anything else is reported, never touched.
    """
    if target_dir is None:
        try:
            target_dir = AGENT_TARGETS[agent]
        except KeyError:
            raise ValueError(f"unknown agent: {agent!r} (known: {', '.join(sorted(AGENT_TARGETS))})")
    if not target_dir.is_dir():
        return []
    # Both sides of every `_entry_status` comparison lose the extended-length
    # prefix here, not just the link targets: `store` reaches us from
    # `store_root()`'s `.resolve()`, which keeps the prefix on any path long
    # enough that the plain spelling no longer names the same file.
    skills_dir = Path(os.path.normpath(strip_extended_prefix(store / "skills")))
    entries = []
    for path in sorted(target_dir.iterdir()):
        if not path.name.startswith(SKILL_PREFIX):
            continue
        if path.is_symlink():
            try:
                points_at = _link_target(path)
            except OSError:
                entries.append(AgentEntry(path, None, "foreign"))
                continue
        elif path.is_dir() and (path / MARKER).is_file():
            try:
                content = (path / MARKER).read_text(encoding="utf-8").strip()
            except (OSError, UnicodeDecodeError):
                entries.append(AgentEntry(path, None, "foreign"))
                continue
            points_at = Path(os.path.normpath(strip_extended_prefix(content)))
        else:
            entries.append(AgentEntry(path, None, "occupied"))
            continue
        entries.append(AgentEntry(path, points_at, _entry_status(points_at, skills_dir, path.name)))
    return entries


def blockers(plans, force):
    """Entries that must stop the install.

    `occupied` always blocks — we will not remove something we did not create.
    `foreign` blocks unless --force, which permits replacing a symlink only.
    """
    return [p for p in plans if p.status == "occupied" or (p.status == "foreign" and not force)]


def blocker_error(stopped):
    """The single refusal message for anything standing in the install's way."""
    detail = "\n".join(f"  {p.target} ({p.status})" for p in stopped)
    return RuntimeError(
        "cannot install — these targets are in the way:\n" + detail
        + "\n\nNothing we cannot prove is a freya install is ever removed. Move it "
          "aside, or re-run with --force to replace foreign symlinks and copy-installs "
          "owned by another checkout (which are deleted, edits and all)."
    )


def apply_plan(plans, *, copy=False, force=False, dry_run=False):
    """Execute a link plan. Returns [(plan, action)] where action is
    linked | copied | replaced | skipped.

    Raises RuntimeError before changing anything if any entry blocks, so a
    partial install cannot happen.
    """
    stopped = blockers(plans, force)
    if stopped:
        raise blocker_error(stopped)

    results = []
    for plan in plans:
        if plan.status == "ok":
            results.append((plan, "skipped"))
            continue
        # Decide the label once, before the dry-run branch, so a preview reports
        # what a real run would actually do — including replacing a foreign link.
        replaced = plan.status == "foreign"
        action = "replaced" if replaced else ("copied" if copy else "linked")
        if dry_run:
            results.append((plan, action))
            continue
        plan.target.parent.mkdir(parents=True, exist_ok=True)
        if replaced:
            if plan.target.is_symlink():
                remove_link(plan.target)
            elif plan.target.is_dir() and (plan.target / MARKER).is_file():
                # The only shape `classify` ever calls "foreign" for a real
                # directory: a --copy install owned by a *different* store
                # (one of ours would have classified as "ok"). The marker is
                # the entire justification for removing a directory here —
                # this is the one place in the installer a directory may be
                # deleted, and only because it carries proof it's ours.
                shutil.rmtree(plan.target)
            else:
                # Defensive: classify() never returns "foreign" for a bare
                # file/directory (that's "occupied", already blocked above).
                # If this fires, the safety contract broke somewhere — refuse
                # rather than guess.
                raise RuntimeError(
                    f"refusing to remove {plan.target}: neither a symlink "
                    "nor a directory carrying our install marker"
                )
        if copy:
            # Staged and renamed into place, never written straight onto the
            # target — see copy_into_place for why a partial copy is worse
            # than a failed one.
            copy_into_place(plan.source, plan.target)
        else:
            plan.target.symlink_to(plan.source, target_is_directory=True)
        results.append((plan, action))
    return results


def remove_link(path):
    """Delete a symlink — including a directory symlink on Windows.

    `os.unlink` there is DeleteFileW, which refuses a directory reparse point;
    RemoveDirectoryW is what removes the link without touching what it points
    at. Every skill link we create is a directory symlink, so without this
    fallback uninstall fails with WinError 5 on precisely the entries it owns.
    On POSIX the first call always succeeds, so the fallback is never taken
    there — and if `unlink` does fail, the original error is what propagates.
    """
    try:
        path.unlink()
    except OSError:
        # Windows only, and deliberately not a blanket retry: on POSIX
        # `unlink` on a symlink always removes the link, so a failure there is
        # a real one (permissions, a vanished mount) and retrying as `rmdir`
        # would only mask it behind a second, less informative error. The
        # first Windows CI run made that concrete — with `unlink` failing, the
        # fallback SUCCEEDED and a failed removal was counted as a good one.
        if not windows():
            raise
        os.rmdir(path)


def copy_into_place(source, target):
    """Copy `source` onto `target` without ever leaving a half-written skill.

    A plain `copytree` straight onto the target is not recoverable: the marker
    is written last (deliberately — a partial copy must never look like a
    completed one), so anything that interrupts the copy leaves a real
    directory with no marker, which `classify` calls `occupied`. Occupied
    blocks install, blocks `--force`, is skipped by uninstall and is left alone
    by `freya update` — the installer's own leftover permanently wedges every
    command that could clear it, and only a manual `rm -rf` recovers.
    `updater._relink_agent` makes it worse: it removes the live copy first, so
    the same interruption destroys a working skill.

    So: copy into a hidden sibling, write the marker inside it, and only then
    swap it into place. A failure anywhere before the rename leaves the
    previous state exactly as it was, and the staging name is dot-prefixed so
    `audit_agent`/`discover_skills` (both `freya-*`-only) never see it even if
    the cleanup itself fails.
    """
    staging = target.parent / f".{target.name}.freya-tmp-{os.getpid()}"
    shutil.rmtree(staging, ignore_errors=True)
    try:
        shutil.copytree(source, staging, symlinks=True)
        (staging / MARKER).write_text(str(source), encoding="utf-8")
    except BaseException:
        # BaseException, not Exception: a Ctrl-C mid-copy is one of the two
        # triggers this function exists for, and it must not be the one case
        # that still leaves the partial tree behind.
        shutil.rmtree(staging, ignore_errors=True)
        raise
    if target.is_symlink() or target.exists():
        # The only target that still exists here is one a caller proved is
        # ours (an `ok` copy being refreshed). Anything else was refused by
        # `blockers` or already removed by apply_plan's `foreign` branch, so
        # re-checking is cheap insurance against a future caller skipping that.
        if classify(target, source) != "ok":
            raise RuntimeError(
                f"refusing to replace {target}: it is not a copy of {source}"
            )
        if target.is_symlink():
            remove_link(target)
        else:
            shutil.rmtree(target)
    os.replace(staging, target)


def uninstall_agent(store, agent, target_dir=None, *, dry_run=False, problems=None):
    """Remove only the entries that are ours: symlinks into this store's
    skills/, and --copy directories carrying a MARKER that names this
    store. Returns the entries removed (or, under dry_run, that would be).

    dry_run collects the same list without unlinking or removing anything —
    a preview must be trustworthy on its own, not just a label on a real run.

    `problems` (a list, if given) collects `(path, exc)` for entries that could
    not be removed. One entry the loop cannot handle must never truncate the
    uninstall: entries are visited in sorted order, so an exception escaping
    here leaves everything before it deleted, everything after it installed,
    and the launcher — removed by `main` after this returns — still on PATH.
    """
    if target_dir is None:
        try:
            target_dir = AGENT_TARGETS[agent]
        except KeyError:
            raise ValueError(f"unknown agent: {agent!r}")
    if not target_dir.is_dir():
        return []
    skills_dir = (store / "skills").resolve()
    removed = []
    for entry in sorted(target_dir.iterdir()):
        if entry.is_symlink():
            try:
                points_at = Path(os.path.normpath(
                    entry.parent / strip_extended_prefix(os.readlink(entry))))
                # Resolve the *parent* before comparing: the link target itself may
                # be dangling, and on macOS a temp/symlinked prefix
                # (/var -> /private/var) otherwise makes a link we own look
                # foreign, so uninstall silently removes nothing.
                owner = points_at.parent.resolve()
            except OSError:
                continue
            if not same_path(owner, skills_dir):
                continue
            if not dry_run:
                try:
                    remove_link(entry)
                except OSError as exc:
                    if problems is not None:
                        problems.append((entry, exc))
                    continue
            removed.append(entry)
            continue
        if entry.is_dir():
            marker = entry / MARKER
            if not marker.is_file():
                continue
            try:
                content = marker.read_text(encoding="utf-8").strip()
                owner = Path(strip_extended_prefix(content)).resolve().parent
            # UnicodeDecodeError is a ValueError, not an OSError: a marker
            # written half-way through a crash, or corrupted on disk, used to
            # escape this loop and abort the whole uninstall partway. classify
            # (:92) and audit_agent (:172) were both widened for it; this
            # third marker read was missed. Undecodable means the same thing
            # here as there — not provably ours, so not ours to remove.
            except (OSError, UnicodeDecodeError):
                continue
            if not same_path(owner, skills_dir):
                continue
            if not dry_run:
                try:
                    shutil.rmtree(entry)
                except OSError as exc:
                    if problems is not None:
                        problems.append((entry, exc))
                    continue
            removed.append(entry)
    return removed


def launcher_target():
    """Where the `freya` launcher goes on PATH."""
    return Path.home() / ".local" / "bin" / "freya"


def path_contains(directory):
    """Is `directory` on PATH?"""
    wanted = os.path.normcase(os.path.normpath(str(directory)))
    return any(
        os.path.normcase(os.path.normpath(part)) == wanted
        for part in os.environ.get("PATH", "").split(os.pathsep)
        if part
    )


def path_hint(directory):
    """How to put `directory` on PATH, in the shell the user is actually in.

    The POSIX `export` line was printed unconditionally, including on the one
    platform where neither shell understands it — and Windows is exactly where
    the note fires, because ~/.local/bin is never on PATH there by default.
    `setx` is deliberately not offered: it expands %PATH% into a literal and
    truncates at 1024 characters, which is a way to lose a user's PATH.
    """
    if windows():
        return (
            f'  $env:PATH = "{directory};$env:PATH"                 # this session\n'
            '  [Environment]::SetEnvironmentVariable("PATH", '
            f'"{directory};" + '
            '[Environment]::GetEnvironmentVariable("PATH", "User"), "User")   # permanent'
        )
    return f'  export PATH="{directory}:$PATH"'


def shim_text(source):
    """The copied launcher: a generated stand-in for a symlink.

    Not a copy of `bin/freya` — that file finds `freya_cli` next to its own
    realpath, so a copy of it anywhere else imports nothing. This carries the
    store's bin directory instead, and mirrors bin/freya's KeyboardInterrupt
    handling so a Ctrl-C still exits 130 rather than printing a traceback.
    """
    return (
        "#!/usr/bin/env python3\n"
        f"# {SHIM_TAG}{source}\n"
        "import sys\n"
        f"sys.path.insert(0, {str(source.parent)!r})\n"
        "from freya_cli import main\n"
        'if __name__ == "__main__":\n'
        "    try:\n"
        "        raise SystemExit(main(sys.argv[1:]))\n"
        "    except KeyboardInterrupt:\n"
        "        raise SystemExit(130)\n"
    )


def cmd_shim_text(source):
    """The Windows `freya.cmd`, without which nothing named `freya` is runnable.

    cmd.exe and PowerShell resolve a bare name through PATHEXT, and an
    extensionless file is not in it — so even a launcher placed perfectly is
    unrunnable on Windows, and every `freya <command>` in every SKILL.md is
    dead. `%~dp0` keeps the shim tied to the launcher beside it, and `%*`
    passes arguments through with their original quoting.

    The interpreter is baked in rather than left as a bare `python`, for the
    reason `freya_cli.build_argv` gives: on a modern Windows box `python` is
    as likely to be the Microsoft Store alias stub as a real interpreter.
    """
    return (
        f"@rem {SHIM_TAG}{source}\n"
        "@echo off\n"
        f'"{sys.executable or "python"}" "%~dp0freya" %*\n'
    )


def shim_owner(target):
    """The source a shim of ours names, or None if this is not one of them.

    Proof has to be positive: unreadable, undecodable and untagged all mean
    "not ours", exactly as an unreadable MARKER does for a --copy skill.
    """
    try:
        head = target.read_text(encoding="utf-8")[:1024]
    except (OSError, UnicodeDecodeError):
        return None
    for line in head.splitlines()[:4]:
        if SHIM_TAG in line:
            return line.split(SHIM_TAG, 1)[1].strip()
    return None


def launcher_classify(target, source):
    """`classify`, plus the one shape only a launcher can take: a copied shim.

    A shim is a real file, so `classify` can only ever call it `occupied`,
    which always blocks — a second `--copy` install would refuse to proceed
    over its own launcher. The tag line naming this exact source is what
    makes it provably ours, the same role MARKER plays for a copied skill,
    and a tag naming a *different* store is `foreign` for the same reason a
    marker naming one is.
    """
    status = classify(target, source)
    if status != "occupied":
        return status
    owner = shim_owner(target)
    if owner is None:
        return "occupied"
    # `same_path`, not string equality, for the same reason MARKER uses it:
    # the tag line is a path, and one path in two spellings is one path.
    return "ok" if same_path(owner, source) else "foreign"


def launcher_plan(store, *, bin_dir=None):
    """Where bin/freya would go, and what installing it there would mean.

    Shared by `link_launcher` and `main`'s pre-flight blocker check, so the
    two can never compute a different status for the same launcher target —
    which is what let a real file at the launcher target block only after
    `link_launcher` ran, rather than before anything was mutated.
    """
    source = store / "bin" / "freya"
    target = (bin_dir / "freya") if bin_dir is not None else launcher_target()
    return target, source, launcher_classify(target, source)


def cmd_shim_plan(target, source):
    """The `freya.cmd` beside a launcher target, and what writing it means.

    Same three-way verdict as `launcher_plan`, on the same evidence, so the
    pre-flight pass can refuse before anything is written rather than dying
    on the very last file of the install.
    """
    cmd = target.with_name(target.name + ".cmd")
    if not cmd.exists() and not cmd.is_symlink():
        return cmd, "create"
    owner = shim_owner(cmd)
    if owner is None:
        return cmd, "occupied"
    # `same_path`, not `owner == str(source)`, for exactly the reason
    # launcher_classify above uses it. This site is Windows-EXCLUSIVE, so the
    # first Windows CI run could not catch it: a tag line written as
    # `\\?\C:\...` and a source spelled `C:\...` are one path in two
    # spellings, and string equality called the shim `foreign` — leaving
    # `freya install` refusing to manage its own freya.cmd.
    return cmd, "ok" if same_path(owner, source) else "foreign"


def launcher_blocked(status, force):
    """Would this launcher status stop an install? Mirrors `blockers` above:
    `occupied` always blocks, `foreign` blocks unless --force."""
    return status == "occupied" or (status == "foreign" and not force)


def launcher_blocker_error(target, status):
    """The refusal message for a blocked launcher target — the launcher's
    counterpart to `blocker_error` above, used by both `link_launcher` and
    `main`'s pre-flight check so the two can never say different things."""
    return RuntimeError(
        f"cannot place the launcher — {target} already exists ({status}). "
        "Move it aside, or re-run with --force to replace a foreign symlink or a "
        "launcher belonging to another checkout."
    )


def launcher_uses_copy(copy):
    """Write the launcher rather than symlink it?

    `--copy` is documented as the mode for "Windows without Developer Mode",
    but it only ever reached the skills: `link_launcher` symlinked
    unconditionally, and it runs *after* every skill has been applied, so the
    documented Windows path copied all ten skills and then died on the last
    file with WinError 1314 and exit 2. On Windows the launcher is written
    even without `--copy`, because there is no configuration of that platform
    where a symlink is the better answer for a single small file.
    """
    return bool(copy) or windows()


def link_launcher(store, *, bin_dir=None, force=False, dry_run=False, copy=False):
    """Put the `freya` launcher on PATH. Returns linked | copied | replaced |
    skipped, plus (on Windows) a `freya.cmd` beside it.

    Still performs its own blocker check — callers other than `main` call
    this directly, and it must refuse on its own rather than trust that some
    earlier pre-flight pass already checked. `main` additionally checks the
    same condition before installing any agent; see the pre-flight pass
    there for why that duplication exists.
    """
    target, source, status = launcher_plan(store, bin_dir=bin_dir)
    if launcher_blocked(status, force):
        raise launcher_blocker_error(target, status)
    as_copy = launcher_uses_copy(copy)
    cmd, cmd_status = cmd_shim_plan(target, source)
    if windows() and launcher_blocked(cmd_status, force):
        raise launcher_blocker_error(cmd, cmd_status)
    if status == "ok" and (not windows() or cmd_status == "ok"):
        return "skipped"
    # Decide the label once, before the dry-run branch — mirrors apply_plan,
    # so previewing over a foreign launcher symlink reports `replaced`, the
    # same as a real --force run, instead of the unconditional `linked` a
    # naive dry-run branch would print.
    action = "replaced" if status == "foreign" else ("copied" if as_copy else "linked")
    if dry_run:
        return action
    target.parent.mkdir(parents=True, exist_ok=True)
    if status in ("foreign", "ok") and (target.is_symlink() or target.exists()):
        # `ok` reaches here only when the launcher itself is already right and
        # we came back for a missing .cmd; unlinking and rewriting it is the
        # simplest way to keep one code path for both.
        target.unlink()
    if as_copy:
        target.write_text(shim_text(source), encoding="utf-8")
        # The shim is executed directly on POSIX (`freya <cmd>`), so it needs
        # the same mode bit the symlinked original relies on.
        os.chmod(target, 0o755)
    else:
        try:
            target.symlink_to(source)
        except OSError:
            # Windows refuses symlink creation without Developer Mode or an
            # elevated shell (WinError 1314), and it refuses at symlink time —
            # no pre-flight can see it coming. A launcher that falls back
            # instead of failing is the difference between an install that
            # works and one that reports failure after doing everything else.
            target.write_text(shim_text(source), encoding="utf-8")
            os.chmod(target, 0o755)
            action = "copied"
    if windows():
        if cmd_status in ("foreign", "ok") and cmd.exists():
            cmd.unlink()
        cmd.write_text(cmd_shim_text(source), encoding="utf-8")
    return action


def unlink_launcher(store, *, bin_dir=None, dry_run=False):
    """Remove the `freya` launcher — but only if it is ours.

    Reuses `launcher_classify` so the exact same contract applies as for every
    skill link: a symlink pointing at this store's bin/freya (or a shim naming
    it) is ours to remove; a foreign symlink, someone else's file, or nothing
    at all is left alone. Returns removed | skipped.
    """
    source = store / "bin" / "freya"
    target = (bin_dir / "freya") if bin_dir is not None else launcher_target()
    status = launcher_classify(target, source)
    cmd, cmd_status = cmd_shim_plan(target, source)
    if status != "ok":
        # The .cmd never outlives the launcher it drives: leaving one behind
        # would put a `freya` on PATH that runs a file that is no longer there.
        if cmd_status == "ok" and not dry_run:
            cmd.unlink()
        return "skipped"
    if not dry_run:
        target.unlink()
        if cmd_status == "ok":
            cmd.unlink()
    return "removed"


def symlinks_available(directory):
    """Can a symlink actually be created in `directory`?

    Windows refuses without Developer Mode or an elevated shell, and it
    refuses at `symlink_to` time — invisible to a pre-flight pass that only
    reads disk state, so the failure lands partway through applying the plan,
    which is the one outcome the whole pre-flight exists to prevent. Asking
    once, up front, is what lets the installer choose `--copy` for the user
    instead of demanding they know to pass it (01-design.md:85 promised
    exactly that: "copy fallback, auto on Windows without symlink privilege").
    """
    probe = directory / f".freya-symlink-probe-{os.getpid()}"
    try:
        directory.mkdir(parents=True, exist_ok=True)
        if probe.is_symlink():
            probe.unlink()
        probe.symlink_to(directory)
    except OSError:
        return False
    finally:
        try:
            if probe.is_symlink():
                probe.unlink()
        except OSError:
            pass
    return True


def default_agents(home=None):
    """Agents detected on this machine — what to install without --agent.

    Detection is deliberately independent of AGENT_TARGETS: Copilot creates
    ~/.copilot, never ~/.agents (that's only the shared install location, so
    two agents don't register the same skills directory twice — see
    AGENT_TARGETS above). Probing AGENT_TARGETS's install paths for presence
    would miss every Copilot-only machine, since ~/.agents never exists
    until something is installed into it.
    """
    if home is None:
        home = Path.home()
    present = []
    if (home / ".claude").is_dir():
        present.append("claude")
    if (home / ".copilot").is_dir() or (home / ".agents").is_dir():
        present.append("copilot")
    return sorted(present)


def main(argv=None):
    parser = argparse.ArgumentParser(
        prog="freya install",
        description="Install the freya-devkit suite for one or more coding agents.",
    )
    parser.add_argument("--agent", action="append", metavar="NAME",
                        help=f"repeatable; one of: {', '.join(sorted(AGENT_TARGETS))}")
    parser.add_argument("--copy", action="store_true",
                        help="copy instead of symlinking (Windows, or committed skills)")
    parser.add_argument("--force", action="store_true",
                        help="replace foreign symlinks and copy-installs owned by another "
                             "checkout (never anything we cannot prove is a freya install)")
    parser.add_argument("--dry-run", action="store_true", help="print the plan, change nothing")
    parser.add_argument("--uninstall", action="store_true",
                        help="remove links pointing into this store")
    parser.add_argument("--store", type=Path, default=None, help=argparse.SUPPRESS)
    parser.add_argument("--target-dir", type=Path, default=None, help=argparse.SUPPRESS)
    parser.add_argument("--bin-dir", type=Path, default=None, help=argparse.SUPPRESS)
    args = parser.parse_args(argv)

    store = args.store if args.store is not None else store_root()
    agents = args.agent or default_agents()
    # Dedup, order preserved: `--agent claude --agent claude` must behave
    # exactly like a single `--agent claude`, not plan (and try to apply)
    # the same install twice.
    deduped_agents = []
    for agent in agents:
        if agent not in deduped_agents:
            deduped_agents.append(agent)
    agents = deduped_agents
    if not agents:
        print("no agent directory found — pass --agent "
              f"({', '.join(sorted(AGENT_TARGETS))})", file=sys.stderr)
        return 1

    unknown = [a for a in agents if a not in AGENT_TARGETS]
    if unknown:
        print(f"unknown agent: {', '.join(unknown)} "
              f"(known: {', '.join(sorted(AGENT_TARGETS))})", file=sys.stderr)
        return 2

    try:
        if args.uninstall:
            verb = "would remove" if args.dry_run else "removed"
            problems = []
            for agent in agents:
                removed = uninstall_agent(store, agent, target_dir=args.target_dir,
                                          dry_run=args.dry_run, problems=problems)
                print(f"{agent}: {verb} {len(removed)} link(s)")
                for path in removed:
                    print(f"  - {path.name}")

            launcher_action = unlink_launcher(store, bin_dir=args.bin_dir, dry_run=args.dry_run)
            target = (args.bin_dir / "freya") if args.bin_dir else launcher_target()
            # unlink_launcher's return value is fixed (removed | skipped) so
            # callers can compare against it reliably; only the printed label
            # gets the dry-run "would" treatment, matching the skills report
            # above — a real "removed" and a previewed one must read differently.
            launcher_label = verb if launcher_action == "removed" else "skipped"
            print(f"launcher: {launcher_label:<12} {target}")
            # Reported after everything else has been removed, and non-zero:
            # an entry we could not delete is a real failure, but it must not
            # be allowed to abort the loop and leave the rest installed with
            # the launcher still on PATH.
            for path, exc in problems:
                print(f"could not remove {path}: {exc}", file=sys.stderr)
            return 2 if problems else 0

        # Plan every agent before mutating any of them. apply_plan's
        # "raises before changing anything" guarantee is per agent, which
        # still let `--agent claude --agent copilot` leave claude fully
        # installed when copilot was blocked. Collecting blockers across the
        # whole invocation — the agents' AND the launcher's — makes the
        # guarantee per invocation. The launcher used to be checked only
        # inside link_launcher, which runs after every agent below is
        # already applied: a real file at the launcher target let every
        # agent install in full and only then exited 2, which is exactly the
        # mutated-but-reported-as-failed shape this pass exists to prevent.
        #
        # But planning everything up front, before any of it is applied,
        # means each plan's `status` is only a snapshot of disk state at
        # planning time. Two agent names can resolve to the same physical
        # target directory — `--target-dir` is shared, or (after the dedup
        # above) two distinct agents just happen to point at one location —
        # and both snapshots are taken against the same pre-install disk, so
        # both say `status="create"` for the same path. Applying the first
        # one then invalidates the second one's snapshot: the path it was
        # planned against no longer matches disk, and applying it too would
        # call symlink_to on a path that now exists. So once every agent is
        # planned, drop any plan whose target path a prior agent in this
        # invocation already claimed — the duplicate describes the same
        # physical install, already handled, not a second one to apply.
        planned = []
        claimed_targets = set()
        for agent in agents:
            plans = plan_agent(store, agent, target_dir=args.target_dir)
            if not plans:
                print(f"{agent}: no skills found in {store / 'skills'}", file=sys.stderr)
                return 1
            deduped = [p for p in plans if target_key(p.target) not in claimed_targets]
            claimed_targets.update(target_key(p.target) for p in plans)
            planned.append((agent, deduped))

        stopped = [p for _, plans in planned for p in blockers(plans, args.force)]
        if stopped:
            raise blocker_error(stopped)

        launcher_target_path, launcher_source, launcher_status = launcher_plan(
            store, bin_dir=args.bin_dir)
        if launcher_blocked(launcher_status, args.force):
            raise launcher_blocker_error(launcher_target_path, launcher_status)
        if windows():
            cmd_path, cmd_status = cmd_shim_plan(launcher_target_path, launcher_source)
            if launcher_blocked(cmd_status, args.force):
                raise launcher_blocker_error(cmd_path, cmd_status)

        copy = args.copy
        if not copy and windows() and not args.dry_run:
            # Never under --dry-run: the probe creates the target directory and
            # a symlink inside it, and "a preview writes nothing" is the
            # stronger promise. The cost is that a Windows preview says
            # "linked" where the real run may copy.
            # The probe is part of the pre-flight, not a surprise mid-apply:
            # asking now is what turns "installed nine skills, then died on
            # WinError 1314" into an install that simply copies instead.
            probe_dirs = [p.target.parent for _, plans in planned for p in plans]
            probe_dirs.append(launcher_target_path.parent)
            refused = [d for d in dict.fromkeys(probe_dirs) if not symlinks_available(d)]
            if refused:
                copy = True
                print("note: symlink creation is refused here (Developer Mode off, "
                      "or an unelevated shell) — installing with --copy instead.")

        for agent, plans in planned:
            for plan, action in apply_plan(plans, copy=copy, force=args.force,
                                           dry_run=args.dry_run):
                print(f"{agent}: {action:<8} {plan.target.name}")

        action = link_launcher(store, bin_dir=args.bin_dir, force=args.force,
                               dry_run=args.dry_run, copy=copy)
        target = (args.bin_dir / "freya") if args.bin_dir else launcher_target()
        print(f"launcher: {action:<8} {target}")
        if not args.dry_run and not path_contains(target.parent):
            print(f"\nNote: {target.parent} is not on PATH. Add it:\n"
                  f"{path_hint(target.parent)}")
    except (RuntimeError, ValueError, OSError) as exc:
        print(f"install failed: {exc}", file=sys.stderr)
        return 2

    if not args.dry_run:
        # Asked here because this is the one moment a person is definitely at a keyboard.
        # Every run afterwards — agent-driven, wrap-up, CI — has no TTY, so a prompt there
        # would never fire; and putting the instruction in the skill layer would charge
        # every invocation for a question asked once. Best-effort throughout: an install
        # that worked must not be reported as failed because a preference could not be
        # saved — which is why even the import is guarded: under `-P`, `-I` or
        # PYTHONSAFEPATH the script's own directory is off sys.path, so an unguarded import
        # would turn a completed install into a traceback and exit 1.
        try:
            import backend_setup

            backend_setup.offer_quietly(store)
        except Exception:  # noqa: BLE001
            pass

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
