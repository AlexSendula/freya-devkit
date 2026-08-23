#!/usr/bin/env python3
"""freya — the portable launcher for the freya-devkit skill suite.

Gives every coding agent one command surface (`freya <command> [args...]`)
instead of Claude-specific `${CLAUDE_PLUGIN_ROOT}` script paths. Logic lives
here (importable, testable); `bin/freya` is the executable shim.
"""
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path, PurePosixPath, PureWindowsPath

MANIFEST_NAME = "commands.json"

#: Commands the update notice must not precede: `help` is the first thing a new
#: user runs, `update`/`install`/`uninstall` are the ones that would act on the
#: notice, and `doctor` asks the update question itself, unthrottled — running
#: the throttled notice first would pay for two remote calls on one diagnostic.
NO_NOTIFY = frozenset({"help", "-h", "--help", "update", "install", "uninstall", "doctor"})

#: Names `main` dispatches itself, before it ever consults the manifest. A
#: manifest entry with one of these names is unreachable, while `freya help`
#: still lists it under Commands as though it worked.
BUILTIN_COMMANDS = frozenset({"help", "-h", "--help", "doctor", "init",
                              "update", "install", "uninstall"})


def suite_root():
    """Absolute path of the freya-devkit checkout (the canonical store).

    `.resolve()` follows symlinks, so a skill directory linked into an agent's
    skills folder still resolves back to the real tree where sibling scripts live.
    """
    return Path(__file__).resolve().parents[1]


def _under(candidate, root):
    """Does `candidate` resolve to something inside `root`?

    Both sides are resolved before comparing, because the healthy install *is* a
    symlink: the PATH entry points into the canonical store, and only following it
    shows that the two are the same tree. Never raises — this is used by `doctor`,
    which has to survive being run against the broken installation it was called to
    explain, so an unreadable path is "not under", not a traceback.
    """
    try:
        Path(candidate).resolve().relative_to(Path(root).resolve())
    except (OSError, ValueError):
        return False
    return True


def _escapes(rel):
    """Could this manifest value name anything but a path under `skills/`?

    Judged with BOTH path flavours on every host, because the manifest is
    checked-in data read on all of them and the host must not decide what a
    value means. `os.path.isabs` alone is not enough, and the first Windows CI
    run proved it on the newer interpreter only: Python 3.13 changed
    `ntpath.isabs` so a rooted path with no drive (`/etc/passwd`) is no longer
    absolute on Windows. On 3.9 that value was rejected; on 3.13 it sailed
    through, and `resolve_command` joining a rooted path onto the store
    discards the store's own path and lands on the drive root.

    So: reject a POSIX-absolute path, a Windows drive (`C:x` is drive-relative
    and still not ours), a Windows root, and any `..` in either spelling.

    This is the second and last body of that rule. The canonical one is
    `skills/freya-code-graph/scripts/containment.py:escapes`, and everything
    else in the tree imports it from there. The launcher deliberately does not:
    `doctor` and `update` are the commands that diagnose and repair a skill
    tree, so they have to run when that tree is missing, half-installed or
    broken — and `load_manifest` is reached by `doctor_checks` on nearly every
    `freya` invocation, which would make the bootstrap depend on the payload it
    installs. ADR-030 records the exception; the two bodies are held together by
    `bin/test_freya_cli.py::ContainmentParityTest`, which errors rather than
    skips if the canonical module cannot be imported.
    """
    win, posix = PureWindowsPath(rel), PurePosixPath(rel)
    return bool(
        posix.is_absolute() or win.drive or win.root
        or ".." in win.parts or ".." in posix.parts
    )


def load_manifest(root=None):
    """Load the command -> script-path map.

    Validates the shape here, once, rather than only in `doctor_checks`: a
    structurally valid but wrong-shaped manifest (`null`, `[]`, `{"x": 5}` —
    a bad merge, a partially restored file) used to reach `resolve_command`
    and `format_help` as-is and surface as a raw TypeError/AttributeError
    traceback, while doctor handled the identical input cleanly and had four
    subtests proving it. Raising ValueError puts every one of those cases
    through `main`'s existing `except (OSError, ValueError)`, which prints the
    message that points at doctor — the one command that would explain it.
    """
    root = Path(root) if root is not None else suite_root()
    with open(root / "bin" / MANIFEST_NAME, encoding="utf-8") as fh:
        data = json.load(fh)
    if not isinstance(data, dict):
        raise ValueError(f"expected a JSON object, got {type(data).__name__}")
    if not all(isinstance(rel, str) for rel in data.values()):
        raise ValueError("every entry must map a command name to a string path")
    escaping = sorted(name for name, rel in data.items() if _escapes(rel))
    if escaping:
        # The manifest is an implicit trust boundary — `resolve_command` joins
        # its value onto the store and runs it. It is repo-owned today, so this
        # is a guard rather than a fix, but "a path under skills/" is the only
        # thing an entry is ever allowed to mean.
        raise ValueError(
            f"entries must be paths under skills/: {', '.join(escaping)}")
    return data


def resolve_command(name, manifest=None, root=None):
    """Path of the script for `name`, or None if unknown."""
    root = Path(root) if root is not None else suite_root()
    if manifest is None:
        manifest = load_manifest(root)
    rel = manifest.get(name)
    if rel is None:
        return None
    return root / "skills" / rel


def build_argv(script, args):
    """Command line for running a suite script with the *current* interpreter.

    Uses sys.executable so the launcher never depends on a bare `python` being
    on PATH — it frequently is not on modern systems.
    """
    return [sys.executable, str(script), *[str(a) for a in args]]


def child_env(script, env=None):
    """The environment a dispatched script runs in.

    Suite scripts import their siblings by bare name (`import audit_engine`),
    which normally works because CPython puts the script's own directory on
    sys.path. Under `PYTHONSAFEPATH` / `-P` / isolated mode it does not, and
    `freya security` died with ModuleNotFoundError while the one test that
    sets PYTHONSAFEPATH stayed green — it only ran `freya help`, which never
    spawns a child. Putting the script's directory on the child's PYTHONPATH
    restores exactly the entry that is normally there, for every command at
    once, rather than asking sixteen scripts to each hand-roll a sys.path
    insert. bin/freya already does the same thing for its own import.
    """
    env = dict(os.environ if env is None else env)
    script_dir = str(Path(script).resolve().parent)
    existing = env.get("PYTHONPATH", "")
    env["PYTHONPATH"] = (script_dir + os.pathsep + existing) if existing else script_dir
    return env


def run_command(name, args, root=None):
    """Run a suite command; return its exit code, or None if the name is unknown."""
    script = resolve_command(name, root=root)
    if script is None:
        return None
    if not script.is_file():
        # Without this the user sees CPython's own "can't open file" error,
        # which never mentions freya and exits 2 — the same code as an unknown
        # command. This is the shape a half-applied update or a pruned copy
        # install leaves, i.e. precisely what doctor exists to explain.
        sys.stderr.write(
            f"freya: '{name}' is registered but its script is missing ({script})\n"
            "Run 'freya doctor' to diagnose the installation.\n"
        )
        return 2
    code = subprocess.call(build_argv(script, args), env=child_env(script))
    # subprocess.call reports a signal-terminated child as -N; returning that
    # straight to SystemExit masks it to 256-N (241 for SIGTERM, 247 for
    # SIGKILL), which no shell convention explains. bin/freya's own
    # `SystemExit(130)` for Ctrl-C shows 128+N is the intent.
    return 128 - code if code < 0 else code


def skill_named(name, root=None):
    """The store's `freya-<name>` skill directory, or None.

    `wrap-up`, `docs-manager` and `spec-manager` are skills an agent invokes,
    not CLI commands — a distinction bin/agents_md.py spells out, but only
    ever inside a project's AGENTS.md, never where someone typing `freya
    wrap-up` would see it.
    """
    try:
        import installer

        wanted = f"{installer.SKILL_PREFIX}{name}"
        return next((s.name for s in installer.discover_skills(root or suite_root())
                     if s.name == wanted), None)
    except (OSError, ImportError):
        return None


def format_help(manifest=None):
    """Human-readable command listing."""
    if manifest is None:
        manifest = load_manifest()
    lines = [
        "freya — freya-devkit launcher",
        "",
        "Usage: freya <command> [args...]",
        "",
        "Commands:",
    ]
    lines += [f"  {name}" for name in sorted(manifest)]
    lines += [
        "",
        "Built-ins:",
        "  doctor    Check that the installation is healthy",
        "  install   Install the suite for an agent (--uninstall to remove)",
        "  init      Write a freya-devkit section into a project's AGENTS.md",
        "  update    Fast-forward the store and re-link (--dry-run to preview)",
        "  help      Show this message",
        "",
        "All arguments after <command> are passed through unchanged.",
        "",
        # The distinction bin/agents_md.py draws for a project's AGENTS.md,
        # said where a CLI user can also see it: `freya wrap-up` is the most
        # natural thing to type and it is not a command at all.
        "These are the low-level tools. The skills themselves (freya-wrap-up,",
        "freya-docs-manager, ...) are invoked through your agent, not here.",
    ]
    return "\n".join(lines)


#: The floor the *whole suite* runs on, not just this file. 3.9, not the 3.8
#: this used to declare: skills/freya-spec-manager/scripts/search_specs.py
#: annotates `-> list[Spec]` with no `from __future__ import annotations`, and
#: PEP 585 builtin generics are only subscriptable at runtime from 3.9, so
#: `freya spec` is a TypeError on 3.8. bin/freya, install.sh and install.ps1
#: all gate on this number and none of them can import it — test_freya_cli's
#: PythonFloorTest is what keeps the four in step.
MIN_PYTHON = (3, 9)

#: The plugin name this suite ships as, as Claude records it:
#: `<plugin>@<marketplace>`.
PLUGIN_NAME = "freya-devkit"


def plugin_installed(home=None):
    """Is the suite installed as a Claude marketplace plugin?

    Read from `installed_plugins.json`, not from the presence of a checkout
    under `plugins/marketplaces/`. That directory is created by `/plugin
    marketplace add` and survives `/plugin uninstall`, so probing it warned
    "every skill appears twice — remove one" at a user who had only ever added
    the marketplace; and a `directory`-source marketplace has no checkout
    there at all while its plugins are genuinely installed, which reported
    "none" while every skill really was registered twice. An `installPath`
    that no longer exists is not an install either — the cache directory is
    what the agent actually loads.
    """
    home = Path.home() if home is None else Path(home)
    record = home / ".claude" / "plugins" / "installed_plugins.json"
    try:
        with open(record, encoding="utf-8") as fh:
            data = json.load(fh)
    except (OSError, ValueError):
        return False
    plugins = data.get("plugins") if isinstance(data, dict) else None
    if not isinstance(plugins, dict):
        return False
    for key, entries in plugins.items():
        if key.split("@")[0] != PLUGIN_NAME or not isinstance(entries, list):
            continue
        for entry in entries:
            path = entry.get("installPath") if isinstance(entry, dict) else None
            if path and Path(path).is_dir():
                return True
    return False


def doctor_checks(root=None, targets=None, run=None):
    """Health checks as (name, status, detail); status is 'ok' | 'warn' | 'fail'.

    `run=` is the injection point for the `updates` check's git calls
    (defaults to `updater.git`), so a test can exercise every branch of that
    check without a network call.
    """
    root = Path(root) if root is not None else suite_root()
    checks = []

    skills_ok = (root / "skills").is_dir()
    checks.append(("suite root", "ok" if skills_ok else "fail", str(root)))

    # `manifest` stays None unless we loaded something we can actually trust.
    # doctor exists to diagnose broken installs, so a malformed manifest must be
    # reported, never crash — and the scripts check must not claim "all present"
    # when it never had a manifest to check against. The shape validation now
    # lives in load_manifest, so the path that *runs* commands rejects exactly
    # what this check reports.
    manifest = None
    try:
        manifest = load_manifest(root)
    except (OSError, ValueError) as exc:
        checks.append(("manifest", "fail", str(exc)))
    else:
        shadowed = sorted(set(manifest) & set(BUILTIN_COMMANDS))
        if shadowed:
            checks.append((
                "manifest", "fail",
                f"{', '.join(shadowed)} can never run — main dispatches that name "
                "itself, so the manifest entry is unreachable",
            ))
            manifest = None
        else:
            checks.append(("manifest", "ok", f"{len(manifest)} commands"))

    if manifest is None:
        checks.append(("scripts", "warn", "not evaluated — manifest unavailable"))
    else:
        try:
            missing = sorted(
                name for name, rel in manifest.items() if not (root / "skills" / rel).is_file()
            )
        except OSError as exc:
            # `is_file()` propagates EACCES. Unguarded, an unreadable skills/
            # directory killed doctor itself: the error escaped to main's
            # `except (OSError, ValueError)`, which blamed the manifest (which
            # read fine) and told the user to run the command they just ran.
            checks.append(("scripts", "fail", f"could not be checked ({exc})"))
        else:
            checks.append((
                "scripts",
                "fail" if missing else "ok",
                f"missing: {', '.join(missing)}" if missing else "all present",
            ))

    py_ok = sys.version_info >= MIN_PYTHON
    checks.append(("python", "ok" if py_ok else "fail", sys.version.split()[0]))

    # `which` finding *a* freya is not the same as it finding *this* one. In a healthy
    # install the PATH entry is a symlink into the store, so its realpath is under `root`;
    # so is the marketplace plugin's own bin/. When it is not, the `freya` a person types
    # runs a different copy than the tree doctor just inspected — every other row above is
    # then describing something the shell will not execute. Reporting that as "ok" was
    # found by running `./bin/freya doctor` from a checkout while the released plugin was
    # on PATH: the single most confusing state doctor exists to explain, and it was green.
    found = shutil.which("freya")
    if not found:
        checks.append(("freya on PATH", "warn",
                       "not found — run the installer or add bin/ to PATH"))
    elif _under(found, root):
        checks.append(("freya on PATH", "ok", found))
    else:
        checks.append((
            "freya on PATH", "warn",
            f"{found} — a different copy than the suite above ({root}). "
            f"`freya <cmd>` in a shell runs that one; this checkout only runs "
            f"via its own ./bin/freya.",
        ))

    import installer
    import updater

    try:
        store_skill_names = {s.name for s in installer.discover_skills(root)}
    except OSError as exc:
        # Same discipline as the scripts check above: every read doctor makes
        # is a read that can fail on exactly the broken installation doctor
        # was run to explain. It degrades to a row, never a traceback.
        checks.append(("store skills", "fail", f"could not be listed ({exc})"))
        store_skill_names = set()

    installed, orphaned, shadowed, unauditable = [], [], [], []
    for agent in sorted(installer.AGENT_TARGETS):
        target_dir = None if targets is None else targets.get(agent)
        if targets is not None and target_dir is None:
            continue
        try:
            entries = installer.audit_agent(root, agent, target_dir=target_dir)
        except (OSError, ValueError) as exc:
            # Silently skipping here used to leave `agents` reporting "not
            # installed for any agent — run freya install" for an agent whose
            # directory is merely unreadable — the wrong remedy entirely, and
            # the same condition updater.relink already counts as a failure
            # rather than swallowing. Naming it here is what keeps the two
            # commands from disagreeing about the same state.
            unauditable.append((agent, exc))
            continue
        ours = [e for e in entries if e.status == "ok"]
        if ours:
            # A copy is a real directory; a link is not. That is the whole
            # distinction, and it is why the old wording ("linked") was wrong
            # for a --copy install that is perfectly well installed.
            mode = updater.install_mode(entries)
            installed.append(f"{agent} ({len(ours)}, {mode})")
        orphaned += [(agent, e) for e in entries
                     if e.status in ("stale-store", "orphan-skill")]
        # A `foreign` or `occupied` entry whose name IS a skill this store
        # still has means that skill is not installed for this agent — the
        # target name it needs is taken by something else. Only entries whose
        # name collides with a real, current skill count; a stray
        # freya-prefixed directory that names nothing in the store is not
        # "shadowing" anything.
        shadowed += [(agent, e) for e in entries
                     if e.status in ("foreign", "occupied")
                     and e.path.name in store_skill_names]

    for agent, exc in unauditable:
        checks.append((f"agent: {agent}", "warn", f"could not be audited ({exc})"))

    if installed:
        checks.append(("agents", "ok", ", ".join(installed)))
    else:
        checks.append(("agents", "warn", "the suite is not installed for any agent — "
                                         "run `freya install`"))

    if orphaned or shadowed:
        # `stale-store`, `orphan-skill`, `foreign` and `occupied` are four
        # different failures with four different fixes (a moved/duplicated
        # checkout, a skill deleted from this one, a symlink to replace, or a
        # real path to move aside), so they cannot share one message — each
        # gets its own clause, and only non-empty kinds are shown.
        stale = [(agent, e) for agent, e in orphaned if e.status == "stale-store"]
        orphan_skill = [(agent, e) for agent, e in orphaned if e.status == "orphan-skill"]
        shadowed_foreign = [(agent, e) for agent, e in shadowed if e.status == "foreign"]
        shadowed_occupied = [(agent, e) for agent, e in shadowed if e.status == "occupied"]
        clauses = []
        if stale:
            agent, entry = stale[0]
            clauses.append(
                f"{len(stale)} pointing at a different store "
                f"(e.g. {agent}: {entry.path.name} -> {entry.points_at}) — "
                "the checkout moved; re-run `freya install --force`"
            )
        if orphan_skill:
            agent, entry = orphan_skill[0]
            clauses.append(
                f"{len(orphan_skill)} naming a skill this store no longer has "
                f"(e.g. {agent}: {entry.path.name} -> {entry.points_at}) — "
                "`freya update` prunes them"
            )
        if shadowed_foreign:
            agent, entry = shadowed_foreign[0]
            clauses.append(
                f"{len(shadowed_foreign)} foreign symlink occupying the name of a skill "
                f"this store still has (e.g. {agent}: {entry.path.name}) — that skill is "
                "not installed; re-run `freya install --force` to replace it"
            )
        if shadowed_occupied:
            agent, entry = shadowed_occupied[0]
            clauses.append(
                f"{len(shadowed_occupied)} occupying the name of a skill this store still "
                f"has (e.g. {agent}: {entry.path.name}) — that skill is not installed; "
                "move it aside, then re-run `freya install`"
            )
        checks.append(("orphaned entries", "warn", "; ".join(clauses)))
    else:
        checks.append(("orphaned entries", "ok", "none"))

    # `run` threads through every git call this check makes, defaulting to
    # updater.git — the injection point that lets a test exercise this whole
    # ladder (up to date / moved / no upstream / unreachable / not a checkout)
    # without ever reaching the real network.
    git_run = updater.git if run is None else run

    if os.environ.get(updater.OPT_OUT):
        checks.append(("updates", "ok", f"not checked ({updater.OPT_OUT} is set)"))
    elif not updater.is_git_store(root, run=git_run):
        checks.append(("updates", "warn",
                       "the store is not a git checkout — `freya update` cannot run"))
    else:
        # Unthrottled on purpose: a diagnostic that reports a cached answer is
        # not diagnosing anything.
        tracking = updater.upstream(root, run=git_run)
        if tracking is None:
            checks.append(("updates", "warn", "this branch has no upstream"))
        else:
            remote = updater.remote_head(root, tracking, run=git_run)
            local = updater.head(root, run=git_run)
            if remote is None:
                checks.append(("updates", "warn",
                               f"could not reach {tracking.partition('/')[0]}"))
            elif remote == local:
                checks.append(("updates", "ok", f"up to date with {tracking}"))
            elif updater.is_behind(root, remote, local, run=git_run):
                checks.append(("updates", "warn", f"{tracking} has moved — run `freya update`"))
            else:
                # Ahead, not behind. Reporting "has moved — run `freya update`"
                # here sent every contributor to a command that exits 2, and
                # the same wrong verdict reached the daily notice.
                checks.append(("updates", "ok",
                               f"ahead of {tracking} — nothing to pull"))

    # Same `targets` discipline as the `agents` loop above: a test that passes
    # targets={"claude": <tmp dir>} must never have this check fall back to the
    # real `installer.AGENT_TARGETS["claude"]` (the real ~/.claude), and a
    # targets dict that omits "claude" entirely means the caller has no
    # interest in this agent at all, so the check is skipped rather than
    # silently answered against the real home.
    if targets is None or "claude" in targets:
        claude_target_dir = None if targets is None else targets.get("claude")
        try:
            personally_installed = any(
                p.status == "ok"
                for p in installer.plan_agent(root, "claude", target_dir=claude_target_dir)
            )
        except (OSError, ValueError):
            personally_installed = False
        both = plugin_installed() and personally_installed
        if both:
            checks.append((
                "duplicate install", "warn",
                "the Claude marketplace plugin and the personal install are both present; "
                "every skill appears twice (`/freya-devkit:freya-x` and `/freya-x`). "
                "Remove one.",
            ))
        else:
            checks.append(("duplicate install", "ok", "none"))
    return checks


def doctor(root=None, run=None):
    """Print health checks; return 1 if any check failed, else 0."""
    label = {"ok": "ok", "warn": "warn", "fail": "FAIL"}
    checks = doctor_checks(root, run=run)
    for name, status, detail in checks:
        print(f"[{label[status]}] {name}: {detail}")
    return 1 if any(status == "fail" for _, status, _ in checks) else 0


def main(argv=None):
    argv = list(sys.argv[1:] if argv is None else argv)
    try:
        if not argv or argv[0] in ("help", "-h", "--help"):
            print(format_help())
            return 0
        name, rest = argv[0], argv[1:]
        if name not in NO_NOTIFY:
            try:
                import updater

                updater.notify(suite_root())
            except Exception:  # noqa: BLE001
                # notify() already swallows its own failures; this covers the
                # import itself, so a broken or missing updater module can never
                # be the reason a working command fails.
                pass
        if name == "doctor":
            return doctor()
        if name == "init":
            # Mirrors the `update` branch below: accept at most one
            # positional path plus an optional exact `--dry-run`. Anything
            # else — a malformed `--dry-run=1`, an unrecognized flag, or two
            # positionals — used to be silently dropped instead of rejected,
            # so `--dry-run=1` performed a real write.
            positionals = [a for a in rest if not a.startswith("-")]
            flags = [a for a in rest if a.startswith("-")]
            if len(positionals) > 1 or flags not in ([], ["--dry-run"]):
                sys.stderr.write("usage: freya init [<project>] [--dry-run]\n")
                return 2
            import agents_md

            project = positionals[0] if positionals else "."
            return agents_md.init(suite_root(), project, dry_run=flags == ["--dry-run"])
        if name == "update":
            # Exact match only: `"--dry-run" in rest` used to also match
            # `--dry-run=1` (and any other argument), so an argument no one
            # meant as a real run silently ran one.
            if rest not in ([], ["--dry-run"]):
                sys.stderr.write("usage: freya update [--dry-run]\n")
                return 2
            import updater

            return updater.update(suite_root(), dry_run=rest == ["--dry-run"])
        if name in ("install", "uninstall"):
            import installer

            passthrough = list(rest)
            if name == "uninstall":
                passthrough.append("--uninstall")
            return installer.main(passthrough)
        code = run_command(name, rest)
        if code is None:
            sys.stderr.write(f"freya: unknown command '{name}'\n")
            # `freya wrap-up` is the most natural thing a new user types, and
            # the distinction the AGENTS.md text draws — `freya <command>` is
            # the CLI, `freya-<skill>` is a skill the agent invokes — never
            # reached anyone at the CLI. Point at it here, where they are.
            skill = skill_named(name)
            if skill:
                sys.stderr.write(
                    f"\n'{name}' is a skill, not a CLI command — ask your agent to "
                    f"use `{skill}`.\n"
                )
            sys.stderr.write("\nRun 'freya help' for the command list.\n")
            return 2
        return code
    except (OSError, ValueError) as exc:
        sys.stderr.write(
            f"freya: cannot read the command manifest ({exc})\n"
            "Run 'freya doctor' to diagnose the installation.\n"
        )
        return 2


if __name__ == "__main__":
    # bin/freya is the shim everything is installed as, but a user whose
    # launcher is not on PATH reaches the diagnostic by running this module
    # directly — and without this guard that printed nothing and exited 0,
    # which reads exactly like a clean bill of health. (Recorded in the
    # phase-6 validation log as finding #1; the validation plan still tells
    # operators to run it this way.)
    try:
        raise SystemExit(main(sys.argv[1:]))
    except KeyboardInterrupt:
        raise SystemExit(130)
