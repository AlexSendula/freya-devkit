#!/usr/bin/env python3
"""Refresh the canonical store, and say when it is stale.

`freya update` fast-forwards the checkout that *is* the store and re-applies
the install; a throttled, notify-only check tells the user when the remote has
moved. Nothing here ever applies an update on its own — a toolkit that gates
wrap-up must not change under a running task.

Every function that touches git takes `run=`, so the whole module is testable
without a network and the CLI has exactly one place where a subprocess is born.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import time
import traceback
from collections import namedtuple
from pathlib import Path

import installer

#: Local git commands are instant; a fetch is not, and ls-remote sits in front
#: of an ordinary command the user is waiting on, so it gets the tight bound.
DEFAULT_TIMEOUT = 10
FETCH_TIMEOUT = 60
LS_REMOTE_TIMEOUT = 2

#: Printed after an update that actually moved the store — never after
#: "already up to date", because a hint nobody needs is a hint nobody reads.
#:
#: Agents cache their skill list when a session starts. Phase 7 measured it:
#: with a skill's file removed, Copilot still offered the name from its
#: start-up snapshot and then failed on it with a raw ENOENT, and Claude Code
#: answered a second load from memory ("no changes since last load"). So an
#: update applied mid-session is invisible until the session reloads — and an
#: update that reports only its commit range is exactly how a working update
#: comes to look like a broken one.
#:
#: Both hosts are named because there is no portable command to point at; the
#: instruction is agent-neutral and the two are examples of it.
RELOAD_HINT = (
    "open sessions cache skills at start — reload them to pick this up "
    "(Claude Code: /reload-skills · Copilot: /skills), or start a new session"
)


def git(args, cwd, timeout=DEFAULT_TIMEOUT):
    """Run git in `cwd`; return (returncode, stripped stdout).

    Never raises. A missing git, a timeout or a killed process all come back as
    a non-zero code, because every caller's next move is the same either way and
    an update check must not be able to crash the command it precedes.
    """
    try:
        proc = subprocess.run(["git", *args], cwd=str(cwd), capture_output=True,
                              text=True, timeout=timeout)
    except (OSError, subprocess.SubprocessError):
        return 1, ""
    return proc.returncode, proc.stdout.strip()


def is_git_store(store, run=git):
    """Is `store` itself the root of a git work tree?

    The equality matters: a checkout nested inside some other repository would
    otherwise pass, and `freya update` would fast-forward the wrong project.
    """
    code, out = run(["rev-parse", "--show-toplevel"], store)
    if code != 0 or not out:
        return False
    try:
        # Not `==` on two resolve()s: on Windows realpath preserves a `\\?\`
        # prefix that was already on its input (CPython ntpath.realpath), so a
        # store reached by an extended-length path compares unequal to itself
        # and `freya update` reports a git checkout as "not a git work tree".
        return installer.same_path(out, store)
    except OSError:
        return False


def upstream(store, run=git):
    """The tracking branch (`origin/main`), or None if the branch has no upstream."""
    code, out = run(["rev-parse", "--abbrev-ref", "--symbolic-full-name", "@{u}"], store)
    return out if code == 0 and out else None


def is_clean(store, run=git):
    """True when the work tree has no changes, staged, unstaged or untracked."""
    code, out = run(["status", "--porcelain"], store)
    return code == 0 and out == ""


def head(store, run=git):
    """The SHA of HEAD, or None."""
    code, out = run(["rev-parse", "HEAD"], store)
    return out if code == 0 and out else None


def remote_head(store, tracking, run=git):
    """The SHA the upstream branch points at, or None if it cannot be learned.

    Deliberately `ls-remote`: it asks the remote without writing a single byte
    into the local repository, which is what lets the notify check and
    `--dry-run` both run without side effects.

    Both the query and the answer are fully qualified. A bare pattern matches
    the *tail* of every advertised ref on a path-component boundary, and git
    sorts its output by ref name, so an origin that also holds `dev/main` or a
    tag named `main` answered a query for `main` with the wrong SHA first — a
    permanent "an update is available" that `freya update` then contradicts
    with "already up to date", and which the user has no way to clear.
    """
    remote, _, branch = tracking.partition("/")
    ref = f"refs/heads/{branch}"
    code, out = run(["ls-remote", remote, ref], store, LS_REMOTE_TIMEOUT)
    if code != 0 or not out:
        return None
    for line in out.splitlines():
        sha, _, name = line.partition("\t")
        if name.strip() == ref:
            return sha.strip()
    return None


def is_behind(store, remote, local, run=git):
    """Does the remote carry commits this store does not have?

    SHA inequality is not that question. A store with a local commit — every
    contributor's, and anyone parked on a feature branch — has a HEAD that
    differs from origin while being strictly *ahead*, and answering "an update
    is available" there produces a daily notice for an update that then
    refuses with "your store has diverged". The notice can never clear.

    `--is-ancestor` asks the real question. A remote SHA this repository has
    never fetched is not an ancestor of anything local, and git reports that
    as a non-zero exit — which is the right answer anyway: an object we do not
    have is one the remote has moved to.
    """
    if not remote or not local or remote == local:
        return False
    code, _ = run(["merge-base", "--is-ancestor", remote, local], store)
    return code != 0


def preconditions(store, run=git):
    """Reasons `freya update` must refuse. Empty means go.

    Ordered and short-circuiting: there is no point asking a plain directory
    about its upstream, and a dirty tree must be reported before anything is
    fetched. At most one reason comes back, which keeps the CLI's output to the
    one thing the user has to fix next.
    """
    if shutil.which("git") is None:
        return ["git is not on PATH — freya update refreshes the store with git."]
    if not is_git_store(store, run=run):
        return [f"{store} is not a git checkout — freya update refreshes the store "
                "with git. Re-clone the repository and run the installer again."]
    tracking = upstream(store, run=run)
    if tracking is None:
        _, branch = run(["rev-parse", "--abbrev-ref", "HEAD"], store)
        branch = branch or "HEAD"
        if branch == "HEAD":
            # `--abbrev-ref HEAD` returns the literal string "HEAD" when no
            # branch is checked out, and the generic remedy below then reads
            # "git branch --set-upstream-to origin/HEAD", which always fails
            # with "does not point to any branch" — a fix that cannot work,
            # for a state the message never names.
            return [f"the store is on a detached HEAD ({store}) — check out a branch "
                    "(git checkout main), then run this again."]
        return [f"branch {branch} has no upstream — set one with: "
                f"git branch --set-upstream-to origin/{branch}"]
    if "/" not in tracking:
        # `branch.<name>.remote = .` makes @{u} a bare local branch name.
        # Every precondition passed, and `git fetch <that name>` then failed
        # as "could not fetch — check your network" on a machine with a
        # perfectly good network.
        return [f"branch {tracking} is a local branch, not a remote one — this store "
                "tracks nothing to update from. Set a remote upstream with: "
                "git branch --set-upstream-to origin/<branch>"]
    if not is_clean(store, run=run):
        return [f"the store has uncommitted changes ({store}) — commit, stash or discard "
                "them. freya update never merges over local work."]
    return []


def update(store, *, dry_run=False, out=print, run=git, state=None):
    """Fast-forward the store to its upstream. Returns an exit code.

    Fast-forward only, by design: a merge commit or a rebase in the user's
    toolkit checkout is a surprise they did not ask for, and a store that has
    diverged is a situation only they can resolve.
    """
    reasons = preconditions(store, run=run)
    if reasons:
        for reason in reasons:
            out(f"freya update: {reason}")
        return 2

    tracking = upstream(store, run=run)
    remote_name = tracking.partition("/")[0]
    before = head(store, run=run)

    if dry_run:
        remote = remote_head(store, tracking, run=run)
        if remote is None:
            out(f"dry run: could not reach {remote_name}; nothing checked")
        elif remote == before:
            out(f"dry run: already up to date with {tracking}")
        else:
            out(f"dry run: {tracking} has moved to {remote[:8]} — "
                "freya update would fast-forward and re-link")
        # The re-link preview runs against the store as it sits on disk right
        # now (dry_run never fetches or merges), which is the same limitation
        # the "would fast-forward" message above already has — it is still
        # the only preview of the re-link step a dry run can honestly give,
        # and a dry-run relink is guaranteed to write nothing.
        relinked = relink(store, dry_run=True, out=out)
        # An agent that could not be audited must fail a preview exactly as it
        # fails a real run — discarding the result here used to let a dry run
        # exit 0 over the same condition that exits 1 on the real path.
        return 1 if relinked.failed else 0

    code, _ = run(["fetch", remote_name], store, FETCH_TIMEOUT)
    if code != 0:
        out(f"freya update: could not fetch {remote_name} — check your network "
            "and try again.")
        return 2

    # --is-ancestor is the question "can this fast-forward?" asked before
    # attempting it, so a diverged store gets its own message instead of git's.
    code, _ = run(["merge-base", "--is-ancestor", "HEAD", tracking], store)
    if code != 0:
        out(f"freya update: your store has diverged from {tracking} — freya update "
            "only fast-forwards. Reconcile it with git, then run this again.")
        return 2

    code, _ = run(["merge", "--ff-only", tracking], store)
    if code != 0:
        out(f"freya update: fast-forwarding to {tracking} failed. Reconcile the "
            "store with git, then run this again.")
        return 2

    after = head(store, run=run)
    if after == before:
        out("already up to date")
    else:
        _, count = run(["rev-list", "--count", f"{before}..{after}"], store)
        out(f"updated {before[:8]} -> {after[:8]} ({count} commit(s))")
        out(RELOAD_HINT)
    relinked = relink(store, out=out)
    # The cache still says "behind" from before this ran; leaving it would greet
    # the user's next command with a notice about the update they just applied.
    try:
        write_state(state_path() if state is None else state,
                    {"checked_at": time.time(), "behind": False})
    except OSError:
        # A throttle stamp must never fail an update that already succeeded —
        # the fast-forward and re-link above are done by this point, and an
        # unwritable $HOME here just means the next command re-checks a day
        # early, not that this update gets reported as broken.
        pass
    if not dry_run:
        # The migration path for everyone installed before the question existed. It asks
        # once, only if the machine has never answered and there is more than one backend
        # available — so it is silent for anyone who has already chosen, and silent again on
        # every update after the first. No version check and no separate migration command:
        # "has this machine answered?" is the only state that matters.
        try:
            import backend_setup

            backend_setup.offer_quietly(store)
        except Exception:  # noqa: BLE001 — never the reason an update reports failure
            pass
    return 1 if relinked.failed else 0


def install_mode(entries):
    """How this agent's suite is installed: `copy` or `symlink`.

    A copy is a real directory and a link is not — that single distinction is
    the whole test, and it is why an install must never be assumed to be links.
    """
    for entry in entries:
        if entry.status == "ok" and not entry.path.is_symlink():
            return "copy"
    return "symlink"


#: What a relink did: how many agents were brought back in step, and how many
#: failed partway. `failed` is not cosmetic — it is what stops `freya update`
#: from exiting 0 over a half-finished install.
RelinkResult = namedtuple("RelinkResult", "touched failed")


def relink(store, *, dry_run=False, out=print):
    """Bring every agent that already has the suite back in step with the store.

    Pulling is not enough. A symlink picks up an edit inside a skill for free,
    but a skill *added* to the store has no link at all and one *deleted* leaves
    a dangling link behind; a copy tracks nothing whatsoever.
    """
    touched = failed = 0
    for agent in sorted(installer.AGENT_TARGETS):
        try:
            entries = installer.audit_agent(store, agent)
        except (OSError, ValueError) as exc:
            # Silently skipping here used to mean an agent whose skills
            # directory turned unreadable was simply never mentioned again.
            # It must count against the run, not vanish from it.
            failed += 1
            out(f"{agent}: could not be audited ({exc})")
            continue
        if not any(e.status == "ok" for e in entries):
            # Two reasons this guard must never be relaxed. First, updating
            # must not install the suite for an agent that never had it — an
            # agent with zero `ok` entries has nothing here that is ours.
            # Second, and load-bearing: if the store's skills/ directory
            # itself goes missing or turns unreadable, every entry in every
            # agent audits as orphan-skill (its symlink target no longer
            # exists), and without this guard the removal loop below would
            # delete every single one of them — a catastrophic prune
            # triggered by a broken store, not a deliberate uninstall.
            continue
        touched += 1
        copy = install_mode(entries) == "copy"
        try:
            _relink_agent(store, agent, entries, copy=copy, dry_run=dry_run, out=out)
        # The skip in _relink_agent's plan loop below is the actual fix for a
        # plan whose status audit_agent already reported as foreign/occupied:
        # apply_plan raises RuntimeError for exactly those statuses, and such
        # a plan must never reach it a second time. Catching RuntimeError here
        # too is only the backstop, in case some future change reopens that
        # path — without it the error would escape all the way to
        # freya_cli.main's `except (OSError, ValueError)`, which reports it as
        # "cannot read the command manifest" after the orphan removals above
        # have already run, and a copytree that failed partway leaves a
        # directory with no marker, which audits as occupied next time too.
        except (OSError, RuntimeError) as exc:
            failed += 1
            out(f"{agent}: relink failed ({exc}). The store itself is updated; "
                "re-run `freya update` to finish linking.")
    return RelinkResult(touched, failed)


def _relink_agent(store, agent, entries, *, copy, dry_run, out):
    """Re-apply one agent's install. Raises OSError (or, only as a backstop,
    RuntimeError); `relink` reports either and counts it as a failure."""
    # Only used to decide whether a `foreign`/`occupied` entry is shadowing a
    # skill the store still has — see the branch below. A stray freya-*
    # entry that names nothing in the store shadows nothing, so it gets the
    # plain "left alone" line, not the "not installed" one.
    store_skill_names = {s.name for s in installer.discover_skills(store)}
    refresh = set()
    for entry in entries:
        if entry.status == "orphan-skill":
            if dry_run:
                out(f"{agent}: would remove {entry.path.name} (no longer in the store)")
            else:
                # Remove first, report after: if this raises, the caller must
                # see a failure, not a log line claiming a removal that never
                # happened.
                if entry.path.is_symlink():
                    installer.remove_link(entry.path)
                else:
                    shutil.rmtree(entry.path)
                out(f"{agent}: removed {entry.path.name} (no longer in the store)")
        elif entry.status in ("stale-store", "foreign", "occupied"):
            if entry.status in ("foreign", "occupied") and entry.path.name in store_skill_names:
                # A real file/directory or a symlink elsewhere is sitting on
                # the exact name a current skill needs. We never remove
                # something we did not create, but silence here used to
                # leave the user with no signal that the skill is therefore
                # simply not installed for this agent.
                out(f"{agent}: left alone {entry.path.name} ({entry.status}) — "
                    f"{entry.path.name} is therefore not installed")
            else:
                out(f"{agent}: left alone {entry.path.name} ({entry.status})")
        elif copy and not entry.path.is_symlink():
            # install_mode is per agent, not per entry: one --copy skill makes
            # every `ok` entry here a refresh candidate, including symlinks
            # from a mixed install. shutil.rmtree on a symlink raises OSError,
            # so only a real (non-symlink) `ok` directory is ever queued.
            refresh.add(entry.path)
            if dry_run:
                out(f"{agent}: would re-copy {entry.path.name}")

    for plan in installer.plan_agent(store, agent):
        # audit_agent already classified and reported this exact target above
        # (foreign/occupied entries are logged and left alone, never queued
        # into refresh); plan_agent's own classify() would call the same
        # target foreign/occupied again, and apply_plan raises RuntimeError
        # for both. Skipping here is what stops that raise from ever
        # happening — the except (OSError, RuntimeError) in relink() is only
        # a backstop for anything this skip does not anticipate.
        if plan.status in ("foreign", "occupied") and plan.target not in refresh:
            continue
        if plan.target in refresh:
            if dry_run:
                continue  # already reported above
            # One at a time, and only entries audit_agent proved are ours.
            # Deleting all of them up front would leave the agent with no
            # skills at all for the length of ten copytrees, where this window
            # is one.
            #
            # The old copy is deliberately NOT removed here: apply_plan's copy
            # path stages the new one beside it and swaps it in
            # (installer.copy_into_place). Removing it first meant a copytree
            # that failed partway — a full disk, a Ctrl-C, an antivirus lock on
            # the very platform --copy exists for — destroyed a working skill
            # and left an unmarked directory that audits as `occupied`, which
            # this function then "leaves alone" while reporting failed=0 and
            # exiting 0. The remedy printed below could never fix it.
            plan = plan._replace(status="create")
        for done, action in installer.apply_plan([plan], copy=copy, dry_run=dry_run):
            if action != "skipped":
                # apply_plan's own dry-run branch reports the same action verb
                # a real run would use ("linked", "copied", "replaced") — it
                # never learns dry_run itself, so the conditional voice has to
                # be added here, or this line would be the one place in an
                # otherwise all-"would" preview that claims the work is done.
                verb = f"would {action}" if dry_run else action
                out(f"{agent}: {verb} {done.target.name}")


#: Where the throttle lives. One file, one job: when we last asked, and what we
#: were told. Deliberately outside any agent's directory — the answer is about
#: the store, not about an agent.
#:
#: `~/.freya` is now shared with the machine-level settings file, whose location is defined
#: by `settings.global_home()` in the code-graph skill. The two must agree, including about
#: the `FREYA_HOME` override — otherwise pointing that variable somewhere would relocate one
#: and not the other, and a test run would isolate its configuration while still writing a
#: throttle stamp into the real home. `test_the_machine_level_home_has_one_definition` is
#: what keeps them from drifting apart.
FREYA_HOME_ENV = "FREYA_HOME"
STATE_FILE = "update-check.json"


def state_dir():
    override = os.environ.get(FREYA_HOME_ENV)
    if override and override.strip():
        return Path(override.strip())
    return Path.home() / ".freya"
CHECK_INTERVAL = 24 * 60 * 60
OPT_OUT = "FREYA_NO_UPDATE_CHECK"
#: Opt-in traceback for the one code path that is designed to fail silently.
DEBUG = "FREYA_DEBUG"
MESSAGE = "freya: an update is available — run `freya update`"


def state_path():
    return state_dir() / STATE_FILE


def read_state(path):
    """The throttle state, or {} for anything unreadable or malformed."""
    try:
        with open(path, encoding="utf-8") as fh:
            data = json.load(fh)
    except (OSError, ValueError):
        return {}
    return data if isinstance(data, dict) else {}


def write_state(path, data):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(data, fh)


def update_message(store, *, now, path=None, run=git, env=None):
    """The one-line notice to print, or None.

    Notify-only, and throttled: at most one network call a day, bounded by
    ls-remote's short timeout. A failure stamps the clock exactly like a success
    does, so an offline machine goes quiet for a day instead of paying the
    timeout on every single command.
    """
    env = os.environ if env is None else env
    if env.get(OPT_OUT):
        return None
    path = state_path() if path is None else Path(path)
    state = read_state(path)
    # "checked_at" absent (no state file yet, or a corrupt one) must never read
    # as "just checked": defaulting it to 0 and comparing against a small `now`
    # would call an unchecked store fresh, since 0 sits well within
    # CHECK_INTERVAL of any `now` under a day since the epoch.
    if "checked_at" in state:
        try:
            checked_at = float(state["checked_at"])
        except (TypeError, ValueError):
            checked_at = None
        # `checked_at` in the future — clock skew, or a hand-edited file — must
        # not read as fresh: `now - checked_at` would be negative, which is
        # always < CHECK_INTERVAL, and the check would go silent forever.
        if checked_at is not None and 0 <= now - checked_at < CHECK_INTERVAL:
            return MESSAGE if state.get("behind") else None

    behind = False
    if is_git_store(store, run=run):
        tracking = upstream(store, run=run)
        if tracking:
            remote = remote_head(store, tracking, run=run)
            local = head(store, run=run)
            behind = is_behind(store, remote, local, run=run)
    try:
        write_state(path, {"checked_at": now, "behind": behind})
    except OSError:
        # Same reasoning as update()'s guarded write, which this one was
        # missing: an unwritable ~/.freya (a file of that name, a read-only
        # home) must not swallow the answer we already paid a network call
        # for. Unguarded, the notice was silently dead forever *and* the
        # throttle never engaged, so every command paid a fresh ls-remote.
        pass
    return MESSAGE if behind else None


def notify(store, *, stream=None, now=None, env=None, **kwargs):
    """Print the update notice, if there is one. Swallows everything.

    The only bare `except` in the suite, and it is the correct one: a
    notification that can break the command it precedes is worse than no
    notification. It writes to stderr so stdout stays parseable for the agent
    that invoked the command.

    `stream` defaults to `None` and is resolved to `sys.stderr` inside the
    body, not in the signature: a default bound at import time would freeze
    in whatever `sys.stderr` was at that moment, so `contextlib.redirect_stderr`
    around a call made later could never capture the notice.

    The write is *inside* the guard, not after it: a BrokenPipeError on stderr
    would otherwise escape a function whose whole contract is that nothing
    escapes. And because a permanently broken check is otherwise
    indistinguishable from "no update available" forever, FREYA_DEBUG prints
    the traceback — opt-in, so the default path stays silent.
    """
    stream = sys.stderr if stream is None else stream
    env = os.environ if env is None else env
    try:
        message = update_message(store, now=time.time() if now is None else now,
                                 env=env, **kwargs)
        if message:
            stream.write(message + "\n")
        return message
    except Exception:  # noqa: BLE001 - see docstring
        # os.environ, not `env`: the injected mapping is a plausible source of
        # the exception we are already handling, and the recovery path must not
        # be able to raise the same failure a second time.
        if os.environ.get(DEBUG):
            traceback.print_exc(file=stream)
        return None
