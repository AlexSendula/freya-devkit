#!/usr/bin/env python3
"""Four path-containment predicates, and the four different questions they ask.

Every one of them is some version of "is this path allowed to name what it
names", and the standing temptation is to write one function and call the rest
variants of it. Collapsing them is the error. They differ in three ways that
matter: whether the path exists yet, whether symlinks are part of the answer,
and what a wrong answer costs. Choose by the question, never by the shape of
the argument.

  escapes(value)          A value **declared** in checked-in data — spec
                          frontmatter, the command manifest, a tsconfig target.
                          Purely lexical, judged in both path flavours, and
                          `..` is refused outright.
  rel_within(root, cand)  A **resolved filesystem candidate** that has to become
                          a graph key. Symlinks are preserved, because the key
                          is the thing three artifacts join on (ADR-025).
  within(root, cand)      A **security decision** about a path that exists.
                          Symlinks are followed, because the question is which
                          file will actually be opened or executed.
  is_anchored(text)       Is this string already an absolute path, on any host
                          and any supported interpreter? Not the negation of
                          `escapes`: `C:x` both escapes and is not anchored, so
                          both terms have to exist.

There is exactly one other body of the `escapes` rule in this repository,
`bin/freya_cli.py:_escapes`, and it is a deliberate exception rather than an
oversight: the launcher has to be able to diagnose a skill tree that is missing
or broken, so it cannot import from one (ADR-030). The two are held together by
`bin/test_freya_cli.py::ContainmentParityTest`, not by hope.

Standard library only. Nothing here touches the filesystem except `within`.
"""

import ntpath
import os
import posixpath
from pathlib import Path, PurePosixPath, PureWindowsPath


def escapes(rel):
    """Could this declared value name anything but a path under the root?

    Judged with BOTH path flavours on every host, because the value comes from
    checked-in data that is read on all of them and the host must not decide
    what it means. `os.path.isabs` alone is not enough, and the first Windows CI
    run proved it on the newer interpreter only: Python 3.13 changed
    `ntpath.isabs` so a rooted path with no drive (`/etc/passwd`) is no longer
    absolute on Windows. On 3.9 that value was rejected; on 3.13 it sailed
    through, and a root-relative path joined onto a project discards the
    project's own path and lands on the drive root.

    So: reject a POSIX-absolute path, a Windows drive (`C:x` is drive-relative
    and still not ours), a Windows root, and any `..` in either spelling.

    `..` is rejected even where it would normalise back inside. No honest
    locator or manifest entry needs it, and a rule you can state in one sentence
    is worth more than the handful of paths it turns away.
    """
    win, posix = PureWindowsPath(rel), PurePosixPath(rel)
    return bool(
        posix.is_absolute() or win.drive or win.root
        or ".." in win.parts or ".." in posix.parts
    )


def rel_within(root, candidate):
    """`candidate` spelled relative to `root`, or None when it is not under it.

    This is the predicate for turning a path the filesystem walk just produced
    into the project-relative key that `graph.json`, `behavior.json` and
    `docs.json` are joined on (ADR-025). `Path.resolve()` is deliberately NOT
    used, and that is the whole reason this is a separate function from
    `within`: resolving would silently re-key a legitimately symlinked
    in-project file to its realpath, and a realpath key is a different string
    from the one the other two artifacts carry. The join is a set intersection
    on that string, so a re-keyed file does not join wrong — it stops joining at
    all, and a blast radius comes back quietly short.

    Normalisation still happens, because `a/../b` and `b` must not be two keys:
    `os.path.abspath` is `os.path.normpath` composed with a join onto the
    process working directory, so the collapse the key needs is done here, and a
    relative spelling on either side still gets a real answer instead of a
    silent None.

    Returns a native relative `Path`, not a key. The forward-slash fold that
    makes a key portable belongs to whoever writes the graph
    (`graph_ops.py:normalize_key`) — this function does not know which artifact
    it is feeding.
    """
    root_abs = os.path.abspath(root)
    cand_abs = os.path.abspath(candidate)
    try:
        return Path(cand_abs).relative_to(root_abs)
    except ValueError:
        # Not under `root` at all, or (on Windows) not even on the same drive.
        # Both are "no relative spelling exists", which is what None means.
        return None


def within(root, candidate):
    """Is the file `candidate` names really inside `root`?

    The security predicate: use it when the answer decides whether something
    gets opened, executed or trusted. Both sides go through `os.path.realpath`,
    so a symlink planted inside `root` that points out of it is not contained,
    and — the case that has already cost this repository a bug — macOS resolving
    `/var` to `/private/var` does not make a directory stop containing its own
    children (ADR-014). `normcase` is what makes `C:\\Tools` and `c:\\tools` one
    path on Windows while leaving POSIX case-sensitive, the same rule as
    `bin/installer.py:path_key`.

    `commonpath` rather than a string prefix test, because `/a/bc` starts with
    `/a/b` and is not under it.

    Never raises. The `ValueError` catch is not defensive padding: `ntpath`
    raises whenever the two arguments' drive components differ (split by
    `splitdrive` below 3.12 and by `splitroot` from 3.12, same rule either way),
    and the reachable case is a `C:` project against a `D:` candidate ("Paths
    don't have the same drive"), so a checker that omits the catch fails only on
    Windows and only long after the omission. That is the reachable source, not
    the only one — `\\\\?\\c:` and `c:` are also "different drives", so a Windows
    `realpath` that keeps the extended-length prefix on one side and strips it
    on the other lands here too. (`ntpath.realpath` strips it whenever
    `_getfinalpathname` agrees, including the >MAX_PATH case, so what is left is
    a path Win32 cannot address without the prefix — a trailing dot or space, or
    a reserved device name — which is not creatable through the Win32 API and
    would additionally have to be on PATH to reach the one caller.)

    False is the honest answer to *this* question: two drives have no common
    root, so neither contains the other. Read it as an answer and not as a
    verdict. `exec_path.resolve` asks "is this the scanned repository's own
    binary", where False means run it — the permissive branch. A future caller
    that needs to fail closed must invert its own question rather than assume a
    refusal here means "unsafe".
    """
    try:
        root_key = os.path.normcase(os.path.realpath(root))
        cand_key = os.path.normcase(os.path.realpath(candidate))
        return os.path.commonpath([root_key, cand_key]) == root_key
    except (OSError, ValueError):
        return False


def is_anchored(text):
    """Is `text` already an absolute path — the same answer everywhere?

    Not `os.path.isabs`, which answers for the platform the caller happens to be
    running on: `C:\\tools\\git.exe` reads as relative to posixpath, so a rule
    built on it is a violation on one leg of the CI matrix and clean on the
    other. And not `posixpath.isabs(text) or ntpath.isabs(text)` either, which
    is the form that looks obviously correct and is not version-stable —
    `ntpath.isabs` changed in 3.13 so a rooted path with no drive stopped being
    absolute. Measured over an eleven-case table on 3.9.6, 3.12.5 and 3.13.5:
    the union flips on `\\tools\\git.exe` (True on 3.9 and 3.12, False on 3.13),
    while the form below gives identical answers on all three.

    So the two unambiguous shapes are judged directly: a POSIX absolute path, or
    a Windows path carrying both a drive (or a UNC share) and a root. What that
    turns away is the point — `C:git.exe` is drive-relative and `\\tools\\git.exe`
    is rooted-but-driveless, and each takes part of its meaning from a current
    directory, which is precisely the thing an anchored path must not need.

    This is not the negation of `escapes`. `escapes("C:x")` is True and
    `is_anchored("C:x")` is False: one asks "may this value be joined onto my
    root", the other asks "does this value already stand on its own".
    """
    if posixpath.isabs(text):
        return True
    drive, rest = ntpath.splitdrive(text)
    return bool(drive) and rest[:1] in ("\\", "/")
