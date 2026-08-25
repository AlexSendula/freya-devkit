#!/usr/bin/env python3
"""The one moment a human is definitely at a keyboard: ask which parser to use.

The code graph is produced by a substrate *backend*, and which one runs is a per-project
setting. Somebody has to choose it — and every other place we could ask is the wrong one:

  - **Mid-workflow** is the obvious idea and it does not work. `code-graph` auto-enables
    non-interactive mode whenever stdin is not a TTY, which is every agent-driven run and
    every `wrap-up` run. A prompt there fires almost exclusively for someone typing the
    command by hand.
  - **Through the agent** works, but the instruction telling the agent what to do would live
    in the skill layer, read on every single invocation to say nothing on almost all of them.
    Standing token cost for a question asked once per machine.

`freya install` and `freya update` are run by a person, in a terminal, on purpose. So the
question goes here, the answer becomes the machine-level default, and no project ever has to
ask again: the first build in each records it in that project's own committed settings.

Everything in here is best-effort. A failure to ask, to read, or to write must never be the
reason an install fails — the floor works with no configuration at all, which is the whole
point of having one.
"""
import os
import sys
from pathlib import Path

#: Enough about each backend to choose between them without leaving the terminal.
#: Deliberately not derived from `Coverage`: this is a sales pitch for a human, and
#: "40 languages incl. Java, Kotlin, Swift" is a better answer to "which one do I want?"
#: than a sorted list of ninety-two file extensions.
_BLURB = {
    "homegrown": "4 languages — TypeScript, JavaScript, Python, Go. Built in, nothing to install",
    "graphify": "40 languages — adds Java, Kotlin, Swift, Rust, C#, Scala, Ruby, PHP, SQL, …",
}

#: Shown when the only backend available is the floor. Not a question — a question with one
#: answer is noise — but the one line that closes the discovery gap, since nothing else in
#: the toolkit tells you another backend exists before you have already installed it.
_UPSELL = (
    "freya reads TypeScript, JavaScript, Python and Go out of the box.\n"
    "For Java, Kotlin, Swift, Rust, C# and thirty more, install graphifyy — two y's:\n"
    # The extras matter and were missing here. graphify declares .sql, .tf and .tfvars
    # unconditionally, but parses them only when the optional grammars are installed — so
    # without the extras those extensions are *declared* and produce nothing. The census
    # filters candidates by the running backend's declared extensions, which means it would
    # then affirm that nothing was unread while the graph held no nodes for them: a
    # confidently-empty answer with a second confidently-empty answer vouching for it.
    # Pinned: graphifyy is 0.x, and 0.9.47 is the release this toolkit was measured on.
    '  uv tool install "graphifyy[sql,terraform]==0.9.47"   (or pip, on Python 3.10+)\n'
    "then run, naming graphify — one y, the command it installed:\n"
    "  freya code-graph --use graphify --global"
)


def _scripts_dir(store):
    return Path(store) / "skills" / "freya-code-graph" / "scripts"


def _load_modules(store):
    """Import the settings and registry modules out of the store. None if unavailable.

    Imported by path rather than duplicated: the machine-level file's location and shape have
    exactly one definition, in `settings.py`. A second copy here is the "two implementations
    of one idea" shape this repository has already paid for more than once.
    """
    path = str(_scripts_dir(store))
    if not os.path.isdir(path):
        return None, None
    added = path not in sys.path
    if added:
        sys.path.insert(0, path)
    try:
        import settings as settings_mod
        import backends as backends_mod

        return settings_mod, backends_mod
    except Exception:  # noqa: BLE001 — a broken skill tree must not fail an install
        return None, None


def already_answered(store):
    """Has this machine already been asked? Absent file or unreadable both count as 'no'."""
    settings_mod, _ = _load_modules(store)
    if settings_mod is None:
        return False
    try:
        data, _ = settings_mod.load_global()
        name = (data.get("substrate") or {}).get("backend")
        return isinstance(name, str) and bool(name.strip())
    except Exception:  # noqa: BLE001
        return False


def _choices(store, backends_mod):
    """Backend names available on this machine, floor first."""
    try:
        names = sorted({b.name for b in backends_mod.available_backends(str(store))})
    except Exception:  # noqa: BLE001
        return []
    floor = getattr(backends_mod, "FLOOR", "homegrown")
    return ([floor] if floor in names else []) + [n for n in names if n != floor]


def offer(store, stream=None, reader=None, interactive=None, options=None):
    """Ask which backend to use, once per machine. Returns the name chosen, or None.

    `reader`, `interactive` and `options` are injection points so the whole flow is testable
    without a terminal *and without depending on what happens to be installed on the machine
    running the tests*; production passes none of them.

    That last one is not hypothetical: written against `_choices` directly, five of these
    tests passed here and failed on every CI runner, because the runner installs nothing but
    pytest and so has only one backend to choose between.
    """
    out = stream or sys.stdout
    if interactive is None:
        interactive = sys.stdin is not None and sys.stdin.isatty()

    settings_mod, backends_mod = _load_modules(store)
    if settings_mod is None or backends_mod is None:
        return None
    if already_answered(store):
        return None

    if not interactive:
        # A scripted or piped install must not block, must not answer on the user's behalf,
        # and must not talk either. Checked *before* the single-option branch below, which
        # otherwise printed the upsell into the log of every CI install and every `freya
        # update`, forever — advice nobody was in a position to act on.
        return None

    if options is None:
        options = _choices(store, backends_mod)
    if len(options) < 2:
        # Nothing to choose between. Say what is missing and how to get it, then stop —
        # asking a question with one answer trains people to skip questions.
        out.write("\n" + _UPSELL + "\n")
        return None

    out.write("\nWhich parser should freya use to read your code?\n\n")
    for index, name in enumerate(options, 1):
        out.write("  [%d] %-11s %s\n" % (index, name, _BLURB.get(name, "")))
    out.write("\nThis becomes the default for every project. Any project can override it\n"
              "later with `freya code-graph --use <backend>`.\n")

    choice = _ask(out, reader, len(options))
    if choice is None:
        out.write("Skipped. Run `freya code-graph --use <backend> --global` when you decide.\n")
        return None

    name = options[choice - 1]
    try:
        path = settings_mod.set_backend(name, scope=settings_mod.SOURCE_GLOBAL)
    except OSError as exc:
        out.write("Could not save that (%s). Nothing changed.\n" % exc.__class__.__name__)
        return None
    out.write("\nUsing %r by default (%s).\n" % (name, path))
    return name


def _ask(out, reader, count):
    """One index in 1..count, or None if the person declined or the input ended.

    Three attempts, then it gives up rather than looping — a prompt that will not let you
    leave is worse than an unanswered question, and the answer has a perfectly good default.
    """
    read = reader or (lambda: input("Your choice (1-%d, or Enter to skip): " % count))
    for _ in range(3):
        try:
            raw = (read() or "").strip()
        except (EOFError, KeyboardInterrupt):
            out.write("\n")
            return None
        if not raw:
            return None
        # `int()` rather than `isdigit()` then `int()`: `"²".isdigit()` is True and
        # `int("²")` raises, so the guard let exactly the input it was meant to catch through
        # and turned a typo into a traceback out of an install.
        try:
            value = int(raw)
        except ValueError:
            value = None
        if value is not None and 1 <= value <= count:
            return value
        out.write("  Please enter a number between 1 and %d, or press Enter to skip.\n" % count)
    return None


def offer_quietly(store, **kwargs):
    """`offer`, with every failure swallowed. The form the install path calls."""
    try:
        return offer(store, **kwargs)
    except Exception:  # noqa: BLE001 — never the reason an install or update fails
        return None
