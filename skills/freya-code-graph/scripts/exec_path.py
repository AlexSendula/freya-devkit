#!/usr/bin/env python3
"""Resolve an external program to a path no search can redirect.

Almost every subprocess in this suite is spawned while the working directory is
a repository the operator merely pointed at, and several of them name their
program with a bare word: `graphify`, `claude`, `copilot`, `git`. A bare name is
a request to *search*, and the search is not ours to control.

  * On Windows, CPython's `shutil.which` inserts `os.curdir` at the head of the
    search path. Read out of the 3.12.5 and 3.13.5 sources: the insert happens
    inside the no-dirname branch and *after* the `path is None` default is
    applied, so passing an explicit `path=` does not avoid it — that mitigation
    does not exist. A `graphify.exe` committed to a scanned repository is
    therefore found before any real PATH entry.
  * `CreateProcess` searches the *parent* process's current directory before
    PATH, whatever `cwd=` says. Python documents that the program is not looked
    up relative to `cwd`.
  * On POSIX, `execvp` runs in the child — after the chdir to `cwd=` — so an
    empty or relative component in `$PATH` resolves inside the scanned project.

The rule here is therefore not "look it up more carefully". It is: **a
resolution that is not already absolute is refused, never made absolute.** The
security report got this backwards and asked for the result to be "resolved to
an absolute path"; running `abspath` over a working-directory hit hands
`CreateProcess` a fully-qualified path to the attacker's binary, spelled more
convincingly. `containment.is_anchored` is the test, so this module and the tree
invariant checker agree on what "absolute" means on every host.

**The 3.9-3.11 exposure, stated plainly.** The `NoDefaultCurrentDirectoryInExePath`
opt-out below is honoured from 3.12 onwards. On the Windows 3.9 leg of the CI
matrix it does nothing, so `shutil.which` still returns the working-directory
hit first and the absoluteness refusal is the ONLY control. The consequence is
that a hostile repository shipping `graphify.exe` at its root gets a *refusal*
there — the legitimate binary further down PATH is never reached, and the
command degrades with a stated reason. That is a denial of service traded for
arbitrary code execution, and it is the accepted trade. On 3.12+ the opt-out
removes the working-directory entry outright and the real binary is found
normally.

This module lives in a skill rather than in `bin/` so that it travels with every
install mode; ADR-030 records the measurement behind that.

Standard library only. Reads PATH, writes one environment variable on Windows,
spawns nothing.
"""

import os
import shutil
from collections import namedtuple

import containment

#: The answer. `path` is an absolute program path, or None with `reason` saying
#: why the program must not be run. A reason is a sentence beginning with the
#: program's name so a caller can print it unedited: "git is not on PATH" is
#: the wording `bin/updater.py:preconditions` already uses.
Resolution = namedtuple("Resolution", "path reason")

#: Windows only, 3.12+. Defining this variable — the value is irrelevant, only
#: its presence is read — makes `NeedCurrentDirectoryForExePath` return false,
#: which stops `shutil.which` putting the working directory at the head of the
#: search path and stops `CreateProcess` searching it. Belt to the absoluteness
#: rule's braces, and on 3.9-3.11 it is ignored entirely, which is why it is not
#: the control.
CURDIR_OPT_OUT = "NoDefaultCurrentDirectoryInExePath"

#: Read through a module global rather than at each call site so a test can
#: exercise the Windows branch on a POSIX runner. The CI matrix runs Windows,
#: but a developer's local run is the one that has to catch this.
_WINDOWS = os.name == "nt"


def _suppress_curdir_search():
    """Ask Windows to stop searching the working directory. A no-op elsewhere.

    `setdefault`, not assignment: an operator who has already set the variable
    has said something about their machine, and only the name's presence means
    anything to the API, so there is nothing to gain by overwriting their value.
    """
    if _WINDOWS:
        os.environ.setdefault(CURDIR_OPT_OUT, "1")


def resolve(name, project_dir=None):
    """Where `name` is, as a path the operating system will not re-choose.

    Returns a `Resolution`. `path` is None whenever the program must not be run
    and `reason` says which refusal applied. Nothing is raised: every caller of
    this already has a degrade path for "no such program", and a refusal is that
    same event with a better explanation, so making it an exception would buy a
    new failure mode and no new information.

    `project_dir`, when given, is the repository being analysed. A resolution
    inside it is refused, because a scanned repository choosing which binary the
    toolkit runs is the entire defect. `containment.within` decides that, which
    means the check follows symlinks: a `bin/git` in the repository that links
    to a file also in the repository is still the repository's own binary. A
    link pointing *out* of the repository is deliberately not refused — the file
    it names is one the operator's machine already had, not one the repository
    shipped.

    The process working directory is deliberately NOT also a forbidden root.
    `/usr/bin/git` is "inside" a working directory of `/`, and it does not need
    to be forbidden anyway: the absoluteness rule above already closes every
    route by which the working directory reaches the answer.
    """
    _suppress_curdir_search()
    # Exactly one argument, on purpose. An explicit `path=` does not suppress
    # the Windows curdir insert (see the module docstring), so it would buy no
    # security — and two of `DetectTest`'s three cases patch `shutil.which`
    # with a one-parameter lambda (`test_audit_adapter.py:307` and `:311`, in
    # `DetectTest`), so a second argument turns them into TypeErrors to pay for
    # nothing. The third patches with `return_value=None` (`:316`), a MagicMock
    # that takes any arity, and would not notice. That was written here as a
    # prediction, while `audit_adapter.detect` still called `shutil.which`
    # itself; detect now routes through this function
    # (`audit_adapter.py:program_for`) and the two lambdas were untouched by the
    # migration, which is what confirms it. The class is named as well as cited
    # because that file has grown twice under this comment and a bare number
    # went stale silently both times: `bin/check_doc_citations.py` reads
    # markdown, so nothing in the tree checks a citation written in Python.
    found = shutil.which(name)
    if found is None:
        return Resolution(None, "%s is not on PATH" % name)
    if not containment.is_anchored(found):
        return Resolution(
            None,
            "%s resolved to %r, which is not an absolute path — the working "
            "directory would be choosing the binary" % (name, found))
    if project_dir is not None and containment.within(project_dir, found):
        return Resolution(
            None,
            "%s resolved to %r, inside the project being scanned (%s) — refusing "
            "to run a scanned repository's own binary"
            % (name, found, os.path.abspath(project_dir)))
    return Resolution(found, None)
