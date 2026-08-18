#!/usr/bin/env python3
"""Write the freya-devkit section of a project's AGENTS.md.

AGENTS.md is the cross-tool instructions file ~30 agents read. It is a per-repo
file by convention, which is why this is `freya init`, run on request, and not
part of the global install: writing into someone's repository unasked would be
intrusive.

The block is marker-delimited so a re-run replaces it in place and touches
nothing else in the file. Everything outside the markers is the user's file
and must survive byte-for-byte — including its line endings, which is why this
module never goes through `Path.read_text`/`write_text` (universal newlines
would silently turn every CRLF into LF on the way through).
"""

from __future__ import annotations

import errno
import os
import shutil
import stat
import tempfile
from pathlib import Path

import check_skill_conformance as conformance
import installer

BEGIN = "<!-- freya-devkit:begin (managed by `freya init` — edits inside are overwritten) -->"
END = "<!-- freya-devkit:end -->"

#: Tokens after which a period does not end a sentence — `first_sentence`
#: must not stop at "e.g." or a lone initial like "J.".
ABBREVIATIONS = frozenset({"e.g", "i.e", "vs", "etc"})

#: Characters that end a sentence. "." alone used to, so a description whose
#: summary ended in "!" or "?" had no recognized boundary at all and the whole
#: thing — TRIGGER keyword list included — went into one table cell.
TERMINATORS = ".!?"

PREAMBLE = """## freya-devkit

This project uses the freya-devkit skill suite. Its skills are installed for
your agent under their own names, and its tools are reached through one launcher.

- `freya <command>` (a space) is the CLI — for example `freya code-graph --build`.
  Run `freya help` for the full list. Do not call the bundled scripts by path,
  and never with a bare `python`.
- `freya-<skill>` (a hyphen) is a skill name. Skills refer to each other this way.
- Generated artifacts — documentation, specs, security reports — are committed
  separately from the code change that prompted them: the two-commit pattern.
- Where a skill fans work out across several independent tasks, run them in
  parallel if your agent supports subagents, and one at a time if it does not."""


def _sentence_end(collapsed, start):
    """Index of the next sentence terminator followed by a space, or -1."""
    for idx in range(start, len(collapsed) - 1):
        if collapsed[idx] in TERMINATORS and collapsed[idx + 1] == " ":
            return idx
    return -1


def first_sentence(text):
    """The first sentence of a description, whitespace-collapsed.

    A SKILL.md description is written for skill *selection*: a summary sentence
    followed by usage notes and a pile of TRIGGER keywords. Only the first
    sentence belongs in a table a human reads.

    A period does not end a sentence when the token right before it is a known
    abbreviation ("e.g", "i.e", "vs", "etc") — otherwise "e.g. widgets" or
    "vs. that" would truncate the summary mid-clause.

    A single-letter token before the period ("J.") is only treated as an
    initial — and so skipped — when the word right after it does *not* start
    with a capital letter: an initial is followed by more of a name ("J.
    Smith"), while an actual sentence end is followed by a new capitalized
    sentence. Without that check, a summary like "Reports a | b. And a
    second sentence." never terminates at "b." and runs the second sentence
    on.
    """
    collapsed = " ".join(text.split())
    search_from = 0
    while True:
        idx = _sentence_end(collapsed, search_from)
        if idx == -1:
            return collapsed
        # Only a period can be an abbreviation or an initial; "!" and "?"
        # always end the sentence, so they skip both checks below.
        if collapsed[idx] == ".":
            word_start = idx
            while word_start > 0 and collapsed[word_start - 1] != " ":
                word_start -= 1
            token = collapsed[word_start:idx].strip("([{\"'").lower()
            if token in ABBREVIATIONS:
                search_from = idx + 2
                continue
            if len(token) == 1 and token.isalpha():
                next_start = idx + 2
                next_end = collapsed.find(" ", next_start)
                if next_end == -1:
                    next_end = len(collapsed)
                next_word = collapsed[next_start:next_end]
                if not next_word[:1].isupper():
                    search_from = idx + 2
                    continue
        return collapsed[:idx + 1]


def skill_rows(store):
    """[(skill name, one-line summary)] for every skill in the store."""
    rows = []
    for path in installer.discover_skills(store):
        lines = (path / "SKILL.md").read_text(encoding="utf-8").splitlines()
        description = conformance.frontmatter_value(lines, "description") or ""
        # A pipe inside a description would silently split the table cell.
        summary = first_sentence(description).replace("|", r"\|")
        rows.append((path.name, summary))
    return rows


def render_block(store, newline="\n"):
    """The managed region, markers included, ending in exactly one newline.

    `newline` is whatever line ending the target file predominantly uses, so
    the inserted block matches the rest of a CRLF file instead of mixing
    conventions within one document. Built with "\\n" first and translated
    afterward rather than joined with `newline` directly, because PREAMBLE is
    itself a multi-line string — joining the top-level list would leave its
    *internal* line breaks as bare LF no matter what `newline` was.
    """
    lines = [BEGIN, "", PREAMBLE, "", "| Skill | Use it for |", "|---|---|"]
    lines += [f"| `{name}` | {summary} |" for name, summary in skill_rows(store)]
    lines += ["", END]
    block = "\n".join(lines) + "\n"
    return block if newline == "\n" else block.replace("\n", newline)


def _fenced_spans(text):
    """Index ranges of `text` that sit inside a closed code fence.

    A run of three or more backticks or tildes at the start of a line (up to
    three leading spaces, as CommonMark allows) opens a fenced code block; a
    later run of the same character, at least as long and with nothing but
    whitespace after it, closes it. Markers inside such a block are an
    *example* of the managed region, not the region itself — a team that
    documented freya-devkit in their own AGENTS.md had that example treated
    as the real block: the body between their markers was deleted, the
    managed section was written inert inside the fence, and `freya init`
    reported "updated AGENTS.md".

    Only *closed* fences count. An unclosed run is malformed markdown, and
    treating the whole rest of the file as fenced would hide a real block
    from every future run — each one would then append another block to the
    end of the file, growing it forever, which is worse than the defect this
    fixes. Indented (four-space) code blocks need nothing here: their
    markers are not at the start of a line, so they are already ignored.
    """
    spans = []
    open_at = None
    open_fence = ""
    pos = 0
    for line in text.splitlines(keepends=True):
        body = line.lstrip(" ")
        char = body[:1]
        if len(line) - len(body) <= 3 and char in ("`", "~"):
            run = len(body) - len(body.lstrip(char))
            if run >= 3:
                if open_at is None:
                    open_at, open_fence = pos, char * run
                elif char == open_fence[0] and run >= len(open_fence) and not body[run:].strip():
                    spans.append((open_at, pos + len(line)))
                    open_at = None
        pos += len(line)
    return spans


def _line_start_positions(text, marker):
    """Indexes where `marker` occurs at the start of a line, outside a fence.

    A mid-line occurrence — someone's prose naming the marker — cannot be
    the real thing, since the real marker is always written at the start of
    its own line. Nor can an occurrence inside a fenced code block, which is
    a documented example of the region and not the region. Both are ignored
    entirely rather than counted as ambiguity, or a user documenting
    freya-devkit in their own AGENTS.md would lock themselves out of
    `freya init` forever.
    """
    fenced = _fenced_spans(text)
    positions = []
    search_from = 0
    while True:
        pos = text.find(marker, search_from)
        if pos == -1:
            break
        if (pos == 0 or text[pos - 1] == "\n") and not any(s <= pos < e for s, e in fenced):
            positions.append(pos)
        search_from = pos + 1
    return positions


def _locate_marker(text, marker):
    """Index of the sole start-of-line occurrence of `marker`, or None.

    None covers the two cases the caller must treat identically — absent, or
    present at the start of more than one line — because a marker that fails
    either cannot be trusted to bound a replace. Two real markers (say, one
    left over from a previous malformed run and one freshly written) still
    refuse rather than guessing which one is genuine.
    """
    positions = _line_start_positions(text, marker)
    if len(positions) != 1:
        return None
    return positions[0]


def merge(existing, block, newline="\n"):
    """AGENTS.md content with the managed block present exactly once.

    Never rewrites a byte outside the markers — the rest of the file is the
    user's. Raises ValueError if the markers are unusable at the start of a
    line (missing, reversed, or appearing more than once there), because
    guessing where a half-written block ends is how you eat someone's notes.
    A marker that is only being *shown* — mentioned mid-line in prose, or
    written out inside a fenced code block — is not an unusable marker; it is
    ignored, and the real block (if any) is still found and replaced.
    """
    if existing == "":
        return block
    if not _line_start_positions(existing, BEGIN) and not _line_start_positions(existing, END):
        if existing.endswith(newline * 2):
            separator = ""
        elif existing.endswith(newline):
            separator = newline
        else:
            separator = newline * 2
        return existing + separator + block
    start = _locate_marker(existing, BEGIN)
    end = _locate_marker(existing, END)
    if start is None or end is None or end < start:
        raise ValueError(
            "AGENTS.md has a malformed freya-devkit block (an unpaired, reversed, "
            "or duplicated marker) — fix or delete it, then run `freya init` again."
        )
    return existing[:start] + block.rstrip("\r\n") + existing[end + len(END):]


def _detect_newline(existing):
    """The line ending `existing` predominantly uses; "\\n" for a new file.

    Counts CRLF occurrences against LF-only occurrences (a `\\r\\n` also
    contains a `\\n`, so it is subtracted out first) rather than sniffing only
    the first line break, since a file can be inconsistent and the majority
    convention is the one a new block should match.

    The vote is taken over everything *outside* the managed block, because
    the block is this module's own output and must not get a say in what
    convention it should adopt. On Windows a block first written into an
    empty AGENTS.md (LF, the new-file default) outvoted the user's CRLF
    prose for every file shorter than the ~30-line block, so the block could
    never convert and the document stayed mixed forever. Falls back to the
    whole file when nothing outside the block has a line break to vote with.
    """
    outside = existing
    start = _locate_marker(existing, BEGIN)
    end = _locate_marker(existing, END)
    if start is not None and end is not None and start < end:
        outside = existing[:start] + existing[end + len(END):]
    if "\n" not in outside:
        outside = existing
    crlf = outside.count("\r\n")
    lf_only = outside.count("\n") - crlf
    return "\r\n" if crlf > lf_only else "\n"


def _read_target(target):
    """`target`'s contents with line endings untranslated, or "" if absent."""
    if not target.is_file():
        return ""
    with open(target, "r", encoding="utf-8", newline="") as fh:
        return fh.read()


def _remove_temp(tmp):
    """Best-effort removal of a temp file we created.

    Restores the write bit first: the temp carries the original's
    permissions, and Windows refuses to unlink a read-only file. Without
    that, a failed write leaves an `AGENTS.md.freya-init-*.tmp` behind in
    the user's repo, which no .gitignore covers.
    """
    try:
        os.chmod(tmp, stat.S_IRUSR | stat.S_IWUSR)
    except OSError:
        pass
    try:
        tmp.unlink()
    except OSError:
        pass


def _write_target(target, content, *, probe=False):
    """Write `content` to `target` atomically, line endings untranslated.

    Writes to a temporary file in the same directory first, then
    `os.replace`s it into place — same-filesystem, and atomic on both POSIX
    and Windows. `open(target, "w")` would truncate the user's file before a
    single byte of the replacement is written, so a failure mid-write (a
    full disk, a permissions change, the process being killed) would leave
    it empty instead of intact. That contradicts this module's one hard
    rule, so the original is never touched until the new content is
    completely and successfully written elsewhere.

    Three more ways an "atomic" write can still damage the original, all
    fixed here. First, `os.replace` does not follow a symlink — replacing
    the raw, unresolved `target` path when it is itself a symlink would
    unlink the symlink and put a plain file in its place, breaking whatever
    it pointed at. Resolving to the real file first makes the swap land on
    the file the symlink points to, leaving the symlink itself intact.
    Second, the temp file is born with the umask's default mode, not the
    original's, so a 0600 AGENTS.md would come back 0644 after every
    `freya init`: `tempfile.mkstemp` creates it 0600 (and O_EXCL, so a
    predictable name in a shared checkout cannot be pre-created by someone
    else), and `shutil.copymode` carries the original's permission bits
    across before the swap. Third — copy*mode*, not copystat: copystat also
    carries st_flags and st_mtime. The flags turned an immutable (chflags
    uchg) AGENTS.md's temp file immutable too, so `os.replace` failed and
    the cleanup below could not delete its own temp; the mtime made a file
    whose contents had just changed still look untouched to editors,
    `find -newer`, make and rsync. Only the permission bits were wanted.

    `probe=True` does everything a real write does except the swap, then
    removes the temp — that is how `--dry-run` predicts the real run's
    outcome instead of assuming it would succeed.
    """
    real_target = target.resolve()
    if probe and real_target.is_dir():
        # The one failure the probe cannot observe by writing a temp file
        # beside the target: os.replace is what refuses a directory, and a
        # probe never gets that far. Reported exactly as the real run
        # reports it ("Is a directory").
        raise IsADirectoryError(errno.EISDIR, os.strerror(errno.EISDIR), str(real_target))
    fd, tmp_name = tempfile.mkstemp(
        dir=str(real_target.parent),
        prefix=f"{real_target.name}.freya-init-",
        suffix=".tmp",
    )
    tmp = Path(tmp_name)
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="") as fh:
            fh.write(content)
        if real_target.exists():
            shutil.copymode(real_target, tmp)
        if probe:
            _remove_temp(tmp)
            return
        os.replace(tmp, real_target)
    except BaseException:
        _remove_temp(tmp)
        raise


def init(store, project, *, dry_run=False, out=print):
    """Write or refresh the freya-devkit section of a project's AGENTS.md."""
    target = Path(project) / "AGENTS.md"
    try:
        existing = _read_target(target)
    except OSError as exc:
        out(f"freya init: {target}: {exc.strerror or exc}")
        return 2
    except UnicodeDecodeError as exc:
        # UnicodeDecodeError is a ValueError, not an OSError, so it used to
        # slip past the guard above, escape init entirely, and land in
        # freya_cli.main's blanket handler — which blamed "the command
        # manifest" and sent the user to `freya doctor`, where the install
        # then reports perfectly healthy. The file at fault is the user's
        # own, so name it. Reachable on Windows in particular: PowerShell
        # 5.1 writes UTF-16 by default and this project ships an install.ps1.
        out(f"freya init: {target}: not valid UTF-8 ({exc.reason}) — "
            "freya init only edits UTF-8 files")
        return 2
    newline = _detect_newline(existing)
    # render_block reads the *store* (a broken or unreadable SKILL.md raises
    # OSError), while merge validates the *target*'s markers (a malformed
    # block raises ValueError). Separate faults with separate owners, so
    # they are caught separately and each names the file actually at fault.
    # Catching only ValueError around the pair once let an OSError from the
    # store side escape all the way to freya_cli.main, which reported it as
    # "cannot read the command manifest" — a message about the wrong file
    # entirely; catching both together then reported merge's complaint about
    # the target as "cannot read the skill store", the same mistake pointing
    # the other way.
    try:
        if not installer.discover_skills(store):
            # A store with no discoverable skills renders a header-only
            # table: every skill row silently deleted from the user's
            # AGENTS.md, reported as "updated". `installer.main` and
            # `freya doctor` both treat that store state as an error, and
            # the one path that writes into someone else's repo must not be
            # the lenient one.
            out(f"freya init: no skills found in {store / 'skills'} — "
                "the store looks incomplete; run `freya doctor`")
            return 2
        block = render_block(store, newline=newline)
    except (OSError, ValueError) as exc:
        out(f"freya init: cannot read the skill store ({store}): {exc}")
        return 2
    try:
        merged = merge(existing, block, newline=newline)
    except ValueError as exc:
        out(f"freya init: {target}: {exc}")
        return 2
    if merged == existing:
        out(f"freya init: {target} is already up to date")
        return 0
    if dry_run:
        # Predict what the real run would do rather than assuming it would
        # succeed: --dry-run used to report "would create" and exit 0 for a
        # missing project directory, a path already occupied by a directory,
        # or a checkout the user cannot write to — the three cases where the
        # real run exits 2, and the only ones anyone rehearses for.
        try:
            _write_target(target, merged, probe=True)
        except OSError as exc:
            out(f"freya init: {target}: {exc.strerror or exc}")
            return 2
        out(f"freya init: would {'update' if existing else 'create'} {target}")
        return 0
    try:
        _write_target(target, merged)
    except OSError as exc:
        out(f"freya init: {target}: {exc.strerror or exc}")
        return 2
    out(f"freya init: {'updated' if existing else 'created'} {target}")
    return 0
