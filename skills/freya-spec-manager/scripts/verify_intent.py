#!/usr/bin/env python3
"""
Tier-1 deterministic declared-intent gate (governance G1).

Editing an `accepted` behavior's linked test is treated as an attempt to change
the intended behavior, and must be authorized by an in-change-set INTENT-NNN
record (knowledge-base/intents/). This check is git-aware and transition-based
(unlike verify_links.py, a stateless snapshot check), so it is a SIBLING script
that shares the same Tier-1 hard-block tier and exit-code convention.

Detection: files changed since the baseline commit ∩ accepted-behavior locators.
A record authorizes only when it is NEW in the change-set (absent at baseline),
which makes it self-scoping — a past record cannot bless a future edit.

Baseline: knowledge-base/intents/.intent-last-verified (G1's OWN marker — it must
NOT reuse .spec-last-update, which wrap-up advances in Phase 3 before this Phase
3.5 check runs). Absent marker => the check skips (fresh repo / full scan).

Exit 1 when an accepted test changed without an authorizing record (or a record
is malformed), so wrap-up can gate on it; exit 2 when `--advance` refuses, either
because that same gate is blocking or because it never ran. Fail-open on git error
— and a fail-open always says so, `skipped: true` with a note, never a quiet pass.
`skipped: true` is the field a consumer must read before trusting exit 0.

Corpus: a spec file this gate could not read is an `errors` entry, so it blocks
and `--advance` refuses over it. It used to drop out of `load_all_specs` and the
gate reported `skipped: false` with an empty `unauthorized` — the shape of a run
that happened — over a file it never opened.

Usage:
    python verify_intent.py --project .
    python verify_intent.py --project . --format json
    python verify_intent.py --project . --advance   # write marker = current HEAD
    python verify_intent.py --project . --advance --force   # ... over a block
"""

import argparse
import json
import os
import re
import subprocess
import sys
from pathlib import Path, PurePath

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
# The graph key rule is owned by freya-code-graph and imported, not copied
# (ADR-030) — the same sibling pattern verify_links.py uses for `containment`.
# A locator and a git path have to be compared as the same kind of string, and
# `normalize_key` is where this toolkit already decides what that kind is.
sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "freya-code-graph" / "scripts"))
from graph_ops import normalize_key  # noqa: E402
from search_specs import load_specs, find_specs_dir  # noqa: E402
from frontmatter import parse_frontmatter, FrontmatterError  # noqa: E402
from adapters import parse_locator  # noqa: E402

MARKER_RELPATH = "knowledge-base/intents/.intent-last-verified"
INTENTS_RELDIR = "knowledge-base/intents"

#: A baseline marker holds a commit hash and nothing else. `advance_marker` is the
#: only writer and it writes back what `git rev-parse HEAD` printed, so any other
#: shape is a corrupt marker or an attack. It is an attack worth the regex: the
#: marker is a file the scanned repository can commit — `git check-ignore` does
#: not cover it, and it reads as toolkit bookkeeping in a docs directory — and its
#: value is spent in a git REVISION slot, which accepts `--output=<file>`. That
#: truncates the named file, redirects the diff into it, and leaves this gate
#: looking at rc=0 with no output, so it reports `skipped: false` over a
#: change-set it never read. Both halves reproduced end to end, 2026-08-23.
#:
#: 7-64 hex covers an abbreviated hash, sha1 and sha256. Deliberately not "resolve
#: it with `git rev-parse --verify`", which is the stronger-looking variant: that
#: is a second bare-`git` spawn in a file budgeted for one, and INV-2 counts them.
#:
#: So read what this buys narrowly: hash-SHAPED is not hash-RESOLVED, and it is not
#: COMMIT-shaped either. It rules out a value that is an option, and nothing else.
#: Two shapes sail through and are stopped elsewhere: `deadbeef` is eight hex
#: characters and also a legal filename a scanned repository can commit, which git
#: reads as a PATHSPEC for rc=0; and a TREE hash is forty hex characters that git
#: will happily diff against the working tree. What stops both is the `^{commit}`
#: in `_changed_status`, not this regex. Two successive fixes for SEC-001 were
#: written believing otherwise, one per shape.
_COMMIT_RE = re.compile(r"[0-9a-fA-F]{7,64}")


def _git(project_dir, *args):
    """Run git in project_dir; return (returncode, stdout). Never raises."""
    try:
        out = subprocess.run(["git", "-C", project_dir, *args],
                             capture_output=True, text=True)
        return out.returncode, out.stdout
    except (FileNotFoundError, OSError):
        return 1, ""


def _read_baseline(project_dir):
    """(commit hash, warning) from the marker — a hash only when it is one.

    A None hash means "no usable baseline" and the caller takes BEH-090's
    documented skip. Warning and not error: ADR-009 forbids turning a corrupt
    artifact into a false block.

    The warning is not decoration. It is the ONLY thing that tells a marker which
    is absent from a marker which is present and unusable, and downstream that is
    the difference between "advance, this is a fresh repository" and "refuse, the
    gate read nothing" (`_skipped_without_checking`). So every branch that returns
    None for a marker that EXISTS returns a warning with it — including the two
    that used to return `(None, None)` silently. Measured 2026-08-23 on the version
    that did: a committed marker holding `commit:` with nothing after it, a marker
    with no `commit:` line, and a zero-byte marker each produced `skipped: true`
    with the fresh-repo note, after which `--advance` exited 0, moved the baseline
    to HEAD with an empty stderr, and erased an unauthorized accepted-test edit
    from every future run. An empty file is the cheapest such marker to author.
    """
    marker = Path(project_dir) / MARKER_RELPATH
    if not marker.exists():
        return None, None
    try:
        text = marker.read_text(encoding="utf-8", errors="replace")
    except OSError as exc:
        # A scanned repository can put a *directory* at the marker path by
        # committing any file underneath it, and `read_text` then raises
        # IsADirectoryError out of the Tier-1 gate as an uncaught traceback.
        # That failed closed, so it was never a bypass — but the module promises
        # "fail-open on git error, and a fail-open always says so", and a
        # traceback is neither a git error nor a labelled skip. It is now the
        # labelled skip it should always have been, which also means `--advance`
        # refuses over it like any other unusable marker.
        return None, (f"{MARKER_RELPATH} could not be read ({exc.__class__.__name__}) "
                      f"— ignored, so the gate is skipped")
    for line in text.splitlines():
        line = line.strip()
        if line.startswith("commit:"):
            value = line.split(":", 1)[1].strip()
            if not value:
                return None, (f"{MARKER_RELPATH} has an empty commit: value "
                              f"— ignored, so the gate is skipped")
            if not _COMMIT_RE.fullmatch(value):
                return None, (f"{MARKER_RELPATH} does not hold a commit hash "
                              f"({value!r}) — ignored, so the gate is skipped")
            return value, None
    return None, (f"{MARKER_RELPATH} exists but has no commit: line "
                  f"— ignored, so the gate is skipped")


def _changed_status(project_dir, baseline):
    """({project-relative path: status}, ok) for baseline..working-tree.

    `git diff --name-status -M <baseline>` (one ref) compares the baseline to the
    working tree, so committed changes since baseline AND tracked working-tree
    edits both count. Rename entries record the NEW path with a ('R', similarity)
    tuple; others map to 'M'/'A'/'D'.

    `ok` is False when git could not answer, and it is the second half of the
    SEC-001 fix rather than housekeeping. It used to be indistinguishable from
    "nothing changed": the caller intersected an empty map, matched no accepted
    test, and reported `skipped: false` with exit 0 — a Tier-1 gate stating it ran
    while having read nothing. The run still passes (ADR-009 fail-open); what
    changes is that it now says which of the two happened. Validating the marker
    does not cover this on its own, because `'0' * 40` is valid hex and reaches
    exactly this path: measured 2026-08-23, that marker produced `skipped: false,
    unauthorized: [], exit 0` over an edited accepted test.

    THREE tokens bracket the baseline. Two of them refuse a way of reading it that
    is not a revision; the third is not a refusal at all, and saying which is which
    is the point of the list. A fix that landed two shipped believing SEC-001 was
    closed; it was not.

      `--end-of-options` before it   — not an OPTION. The revision slot accepts
          `--output=<file>`: git truncates that file, writes the diff into it, and
          returns rc=0 with an empty stdout.
      `^{commit}` on it              — not a NON-COMMIT OBJECT, and not a PATHSPEC.
          A tree hash is 40 hex characters and git diffs a tree against the working
          tree happily: pick a SUBTREE and everything outside it reports as 'A',
          which `_is_change` calls free, so an edited accepted test is waved through
          with `skipped: false` — and `cat-file` cannot resolve
          `<subtree>:<record>`, so every pre-existing INTENT record reads as new and
          authorizes. Peeling also subsumes the pathspec shape that the previous fix
          was about: `deadbeef` passes `_COMMIT_RE` and is a legal filename a repo
          can commit, but `deadbeef^{commit}` is rc=128 either way, measured with
          the `--` and without it.
      `--` after it                  — nothing the peel does not already refuse.
          Say that plainly rather than let the table imply otherwise: this token
          was the whole of the previous fix and is now redundant AS A REFUSAL. It
          earns its place in the other direction. A repository that commits a file
          named `<its own marker sha>^{commit}` makes git call the argument
          ambiguous without it — rc=128 on every run, so the gate is off and exits
          0 forever. That is denial rather than a false clean, and just as quiet.

    Measured on git 2.50.1, 2026-08-23, in a repo holding a file named `deadbeef`
    and one real modification to report:
        `-M --end-of-options <subtree> --`            -> rc=0, 'A<TAB>deadbeef
                                                         R087<TAB>auth/login…'
        `-M --end-of-options <subtree>^{commit} --`   -> rc=128, not a commit
        `-M --end-of-options <root tree>^{commit} --` -> rc=128, not a commit
        `-M --end-of-options <blob>^{commit} --`      -> rc=128, not a commit
        `-M --end-of-options deadbeef^{commit} --`    -> rc=128, bad revision
        `-M --output=<f> --`                          -> rc=0, '', <f> truncated
        `-M --end-of-options --output=<f> --`         -> rc=128, <f> intact
        `-M --end-of-options <sha>^{commit}`  with a file of that exact name
                                                      -> rc=128, ambiguous argument
        ... the same, with `--`                       -> rc=0, the real change-set
    Controls, all rc=0 and all the same right answer bare or peeled: a full sha, an
    abbreviated sha, an annotated tag object. `^{commit}` costs no subprocess site
    and no version floor above the 2.24 that `--end-of-options` already imposes —
    `<rev>^{<type>}` is gitrevisions syntax from long before that option existed.

    What rc=0 now means, exactly, and not one word more: git resolved the marker to
    a COMMIT in this repository and diffed it. It does NOT mean the commit is one
    this toolkit chose — the marker is a file the scanned repository can commit, so
    a repo willing to write `commit: <its own HEAD>` gets an honest diff of nothing.
    That is ADR-008's trust model for the marker, not a gate lying about having run,
    and it is the residue these three tokens deliberately do not address.

    `--end-of-options` wants git 2.24 (Nov 2019), a floor this repository does not
    otherwise declare. Below it the option is unknown, so the diff fails on every
    run and this gate is not degraded but OFF — `ok=False` forever, a labelled skip
    and exit 0 on every change-set (ADR-009 fail-open). It never answers wrong; it
    stops answering, and the label is the only place that says so.
    """
    rc, out = _git(project_dir, "diff", "--name-status", "-M",
                   "--end-of-options", f"{baseline}^{{commit}}", "--")
    status = {}
    if rc != 0:
        return status, False
    for line in out.splitlines():
        parts = line.split("\t")
        if len(parts) < 2:
            continue
        code = parts[0]
        if code.startswith("R"):
            sim = int(code[1:] or "0")
            status[parts[-1]] = ("R", sim)
        else:
            status[parts[-1]] = code[0]
    return status, True


def _is_change(status):
    """Modified or deleted => a change. Added or pure-rename(100%) => not."""
    if status is None:
        return False
    if isinstance(status, tuple):        # rename: changed only if content moved too
        return status[1] < 100
    return status in ("M", "D")


def _changed_index(status):
    """(exact, folded) — a change-set indexed the way a locator will ask for it.

    `exact` is keyed by `normalize_key`, so a locator and git's spelling of the
    same file arrive as one string: `./tests/test_a.py`, `tests//test_a.py` and
    `tests/x/../test_a.py` all reduce to what git emits. Until 2026-08-24 the
    lookup was verbatim against git's map, and every one of those spellings
    missed — silently, and on the permissive side, so an accepted behavior's
    test could be edited with no record and the gate reported `skipped: false,
    unauthorized: [], exit 0`. None of the three is an error anywhere else in
    the toolkit: `verify_links` resolves them (`escapes` is false and `root /
    './tests/test_a.py'` is a file) and so does `behavior_graph`, so a fully
    green repository had a behavior only this gate could not see.

    `folded` is the case-insensitive index, and it exists to be a CANDIDATE
    list rather than an answer — see `_one_file` for why that distinction is the
    whole of the case handling.
    """
    exact, folded = {}, {}
    for path, st in status.items():
        key = normalize_key(path)
        exact[key] = st
        folded.setdefault(key.casefold(), []).append(key)
    return exact, folded


def _one_file(project_dir, a, b):
    """Do two spellings name one file? Asked of the filesystem, never guessed.

    `Tests/test_a.py` and `tests/test_a.py` are one file on macOS and Windows
    and two on Linux, and Linux is the host a governance gate most often runs
    on, so `casefold()` alone would match two genuinely different files there
    and report an edit to one as an edit to the other. `samefile` puts the
    question to the filesystem that owns the answer instead of to a table of
    platforms.

    It is only ever asked about a path git just named: the candidate comes from
    `_changed_index`'s folded map, so a locator reaching this line already
    reduces, modulo case, to an in-project path from the change-set. A locator
    that escapes the project cannot get here to be `stat`ed.

    The residue, stated where it is decided: a *deleted* accepted test whose
    locator differs in case is not matched, because there is no file left to
    ask about — and in that same run `verify_links` reports the locator as
    unresolved and hard-blocks on it, which is checked by
    `test_verify_intent.py#LocatorSpellingCase.test_a_deleted_test_is_caught_by_the_sibling_gate`
    rather than asserted here.
    """
    try:
        return os.path.samefile(os.path.join(project_dir, a),
                                os.path.join(project_dir, b))
    except OSError:
        return False


def _match_change(index, project_dir, rel_path):
    """(git's status for `rel_path`, the path it was matched to).

    Status is None when the file is not in the change-set; the second element is
    then the normalised locator path, which is what the caller reports.
    """
    exact, folded = index
    key = normalize_key(rel_path)
    if key in exact:
        return exact[key], key
    for candidate in folded.get(key.casefold(), ()):
        if _one_file(project_dir, key, candidate):
            return exact[candidate], candidate
    return None, key


def _git_relpath(path, project_dir):
    """`path` as GIT addresses it: project-relative, forward slashes, always.

    Git stores tree paths '/'-separated and matches a `<commit>:<path>` rev-spec
    against them verbatim, so `git cat-file -e HEAD:kb\\intents\\I.md` reports
    "path does not exist" — even on Windows, where that is exactly how the OS
    spells the file. The first Windows CI run caught this gate FAILING OPEN:
    os.path.relpath handed backslashes to _record_is_new, cat-file called every
    PRE-EXISTING record absent at the baseline, and so a record written for some
    past change silently authorized today's edit to an accepted test.

    Same rule as audit_engine.normalize_file() — forward slashes are the
    interchange form — but reached via as_posix(), which rewrites only the
    separator of the host OS. audit_engine folds backslashes unconditionally
    because it normalizes paths *an agent reported*, which may be Windows-spelled
    on any host; this path is one we just built from the local filesystem, and on
    POSIX a backslash is a legal character in a git path, not a separator.
    """
    return PurePath(os.path.relpath(str(path), project_dir)).as_posix()


def _record_is_new(project_dir, baseline, relpath):
    """True if `relpath` did not exist at the baseline commit (=> in-change).

    `relpath` must be git-spelled (see _git_relpath): cat-file cannot distinguish
    a path it fails to resolve from one that is genuinely absent, and both land
    on "new" — the PERMISSIVE side of this gate — so a mis-spelled path
    authorizes where it should block.

    `baseline` is the other half of that rev-spec and lands on the same side: an
    unresolvable one makes EVERY pre-existing record look new, so a record written
    for some past change blesses today's edit. Measured 2026-08-23, with a marker of
    `commit: deadbeef` and a committed file by that name, this function returned
    True for a record committed AT the baseline.

    One upstream condition keeps that out, and it is deliberately stated as a
    condition rather than as a count of guards: EVERY caller path to this line runs
    through `_changed_status` returning `ok=True`, which happens only when git
    resolved the baseline to a commit and diffed it. So the BASELINE half of
    `<baseline>:<relpath>` always resolves here, and a cat-file failure can only be
    the PATH half — which is the question this function is asking. `verify_intent`
    is the only caller (via this module's `_load_records`, not spec-manager's
    same-named one) and it returns on `not ok` before any record is read.

    Stated as a count it has been wrong twice. A docstring claiming "guarded twice"
    shipped while a hash-shaped PATHSPEC walked past both; its replacement counted
    three and a hash-shaped TREE walked past all three, because `git diff <tree> --`
    answers rc=0 and `cat-file <tree>:<record-outside-that-tree>` does not. Both
    were the same mistake — enumerating the shapes known that week and reading the
    list as a closure. What the condition above buys, and nothing more: whatever
    reaches this line was a commit a moment ago.

    So this function stays credulous on purpose. A caller that got here with a
    broken baseline has already skipped the check the record was meant to authorize,
    and a guard here would test for a state the gate no longer acts on. Weaken the
    condition and it is this function that fails open, silently, permissively.
    """
    rc, _ = _git(project_dir, "cat-file", "-e", f"{baseline}:{relpath}")
    return rc != 0


def _load_records(project_dir, baseline):
    """New-since-baseline INTENT records on disk.

    Filesystem scan (not git diff) so untracked, staged, and committed records
    all count uniformly. Returns (records, errors) where a record is
    {"id","behaviors":[...],"path"}; a malformed record yields an error string.
    """
    records, errors = [], []
    intents_dir = Path(project_dir) / INTENTS_RELDIR
    if not intents_dir.exists():
        return records, errors
    for f in sorted(intents_dir.glob("INTENT-*.md")):
        relpath = _git_relpath(f, project_dir)
        if not _record_is_new(project_dir, baseline, relpath):
            continue  # pre-existing => does not authorize (self-scoping)
        try:
            fm, _body = parse_frontmatter(f.read_text(encoding="utf-8", errors="replace"))
        except FrontmatterError as exc:
            errors.append(f"{f.name}: unparseable frontmatter — {exc}")
            continue
        except Exception as exc:  # noqa: BLE001 — defensive: never crash on a bad record
            errors.append(f"{f.name}: could not read record — {exc}")
            continue
        behaviors = fm.get("behaviors")
        if not isinstance(behaviors, list) or not behaviors:
            errors.append(f"{f.name}: malformed record — missing or empty 'behaviors:' list")
            continue
        records.append({"id": fm.get("id", f.stem), "behaviors": list(behaviors),
                        "path": relpath})
    return records, errors


def verify_intent(project_dir="."):
    project_dir = os.path.abspath(project_dir)
    specs_dir = find_specs_dir(project_dir)
    result = {"version": 1, "baseline": None, "skipped": False,
              "edited_accepted": [], "records_in_change": [],
              "authorized": [], "unauthorized": [], "errors": [], "warnings": []}

    baseline, marker_warning = _read_baseline(project_dir)
    result["baseline"] = baseline
    if marker_warning:
        result["warnings"].append(marker_warning)
    if not baseline:
        # Two states share this branch and only one of them is fine, and
        # `marker_warning` is what separates them — set for every marker that
        # exists, absent only when the file is not there. `--advance` prints this
        # note as the first line of its refusal, so "no baseline marker" over a
        # marker that exists and is hostile sends the operator to look for a file
        # that is sitting right there. It also decides, via
        # `_skipped_without_checking`, whether that refusal happens at all.
        result["skipped"] = True
        result["note"] = ("intent gate skipped — the baseline marker is unusable; "
                          "nothing was checked" if marker_warning else
                          "intent gate skipped — no baseline marker "
                          "(governs transitions only)")
        return result

    status, ok = _changed_status(project_dir, baseline)
    if not ok:
        # Fail-open per ADR-009, but never silently: an empty change-set because
        # git refused and an empty one because nothing changed are two answers.
        result["skipped"] = True
        result["note"] = ("intent gate skipped — git could not diff "
                          f"{baseline}..worktree; nothing was checked")
        return result

    specs, unreadable = load_specs(specs_dir)
    # A spec this gate could not read is a blocking error, not a shorter corpus.
    # `errors` already feeds `_blocking`, so this exits 1 and `advance_if_clear`
    # refuses to move the baseline over it — which is the half that matters,
    # because advancing does not defer an unauthorized edit, it clears it.
    spec_errors = [f"{_git_relpath(u.file_path, project_dir)}: {u.reason} "
                   f"— its behaviors were not checked" for u in unreadable]

    index = _changed_index(status)
    edited = []
    for s in specs:
        for b in s.behaviors:
            if b.get("state") != "accepted":
                continue
            locator = b.get("locator")
            if not locator:
                continue
            rel_path, _frag = parse_locator(locator)
            st, matched = _match_change(index, project_dir, rel_path)
            if _is_change(st):
                edited.append({"behavior_id": b.get("behavior_id"), "spec_id": s.id,
                               "locator": locator, "path": matched,
                               "status": ("R" if isinstance(st, tuple) else st)})
    result["edited_accepted"] = edited

    records, errors = _load_records(project_dir, baseline)
    result["records_in_change"] = records
    result["errors"] = spec_errors + errors

    all_bids = {b.get("behavior_id") for s in specs for b in s.behaviors}
    covered = set()
    for rec in records:
        for bid in rec["behaviors"]:
            covered.add(bid)
            if bid not in all_bids:
                result["warnings"].append(
                    f"{rec['id']} names {bid}, which is not a known behavior")

    for e in edited:
        if e["behavior_id"] in covered:
            result["authorized"].append(e["behavior_id"])
        else:
            result["unauthorized"].append(
                {"behavior_id": e["behavior_id"], "spec_id": e["spec_id"], "path": e["path"]})

    return result


def advance_marker(project_dir):
    """Write the baseline marker = current HEAD. Returns the commit, or None."""
    rc, out = _git(project_dir, "rev-parse", "HEAD")
    if rc != 0 or not out.strip():
        return None
    commit = out.strip()
    marker = Path(project_dir) / MARKER_RELPATH
    marker.parent.mkdir(parents=True, exist_ok=True)
    marker.write_text(f"# Intent gate last-verified\ncommit: {commit}\n", encoding="utf-8")
    return commit


def _blocking(result):
    return bool(result["unauthorized"]) or bool(result["errors"])


def _skipped_without_checking(result):
    """A skip that means "the gate did not run", as opposed to "nothing to run on".

    Exactly one cause of `skipped` is designed. No marker AT ALL is BEH-090: a
    repository that has never been wrapped up, no baseline to compare against,
    nothing wrong — and `--advance` must go through it, because writing the first
    marker is how that state ends. Every other cause is a failure wearing the same
    field: a marker with no usable `commit:` value, a value that is not hash-shaped,
    and a hash-shaped value git will not resolve to a commit.

    They have to be told apart HERE rather than by `_blocking`, which cannot see
    them: a gate that checked nothing leaves `unauthorized` and `errors` empty for
    exactly the same reason a clean run does. SEC-001's body says consumers must
    check `skipped` before trusting exit 0, and this is the consumer that writes
    governance state.

    The discriminator is structural. Not the note's wording — that is English and
    gets reworded — and not an enumeration of attacks, because the first version of
    this function shipped one and a fourth marker shape walked straight past it.
    `verify_intent` sets `skipped` on two returns and only two:

      * `not baseline` — `baseline` is None, and `warnings` carries a
        `_read_baseline` warning for every marker that EXISTS and nothing at all
        when the file is absent. That is the invariant `_read_baseline`'s docstring
        is about, and why it may not go back to returning a bare None.
      * `not ok` — reachable only with a non-None `baseline`.

    Both sit above the loop that appends unknown-behavior warnings, so nothing else
    can be in the list yet. `baseline is None and not warnings` is therefore
    reachable from the absent marker and from nowhere else — a property of two
    return statements, which the next reader can check, rather than a list of
    shapes, which the next attacker can extend.
    """
    if not result["skipped"]:
        return False
    return result["baseline"] is not None or bool(result["warnings"])


def advance_if_clear(project_dir, force=False):
    """Advance the baseline, but only over a gate that ran and did not block.

    Returns (commit, refusal): (<hash>, None) when the marker was written,
    (None, <result>) when the gate refused, (None, None) when git could not say
    what HEAD is.

    Advancing is what makes an unauthorized edit disappear. The gate diffs
    baseline..worktree, so moving the baseline to HEAD does not defer the finding,
    it clears it on every future run — and prints `intent baseline advanced to
    <sha>` while doing it. ADR-008 already said the marker is "advanced only after
    the gate passes"; until this function existed, the only thing enforcing that
    was the order of two steps in wrap-up's prose, which is to say an agent
    reading a document (SEC-011). Resume a partial wrap-up, reorder its phases, or
    read the Phase 3.5 exit 1 as noise because JSON came out with it, and the
    baseline moved over the block. The ordering is now checked where the write
    happens rather than asserted where someone might read it.

    A gate that DID NOT RUN refuses on the same terms, because otherwise SEC-011's
    refusal does not compose with the SEC-001 attack it exists to cover. Measured
    2026-08-23 against a version that gated on `_blocking` alone: with a hostile
    marker and a committed unauthorized edit to an accepted test, `--advance` exited
    0, printed `intent baseline advanced to <sha>` and an EMPTY stderr, moved the
    marker to HEAD, and the finding was gone from every subsequent run. One corrupt
    file in `knowledge-base/intents/` bought a permanent clean sheet, and the only
    thing that had noticed — `_read_baseline`'s warning — was on the branch this
    path never printed. `_skipped_without_checking` draws the line; the fresh-repo
    skip still advances, because that is the write which creates the first marker.

    `force` skips the gate rather than overriding its verdict: the caller who
    wants the override is the one who has already looked, and re-running the check
    only to ignore it would make the flag look like an argument. It remains the
    escape hatch for both refusals.
    """
    result = None if force else verify_intent(project_dir)
    if result is not None and (_blocking(result) or _skipped_without_checking(result)):
        return None, result
    return advance_marker(project_dir), None


def _print_text(result):
    if result["skipped"]:
        # Two reasons to skip now, and the warnings loop at the bottom of this
        # function is unreachable from here — so a hostile marker's warning would
        # be invisible in text mode, which is the one failure it exists to prevent.
        print(result.get("note", "intent gate skipped — no baseline marker"))
        for w in result["warnings"]:
            print(f"  [warn] {w}")
        return
    if not _blocking(result):
        print("OK — no accepted test changed without an authorizing intent record.")
    else:
        if result["unauthorized"]:
            print(f"{len(result['unauthorized'])} accepted test change(s) without an intent record:\n")
            for u in result["unauthorized"]:
                print(f"  [{u['behavior_id']}] {u['spec_id']}: {u['path']} changed — "
                      f"file knowledge-base/intents/INTENT-NNN.md naming {u['behavior_id']} "
                      f"(intent.py new --behavior {u['behavior_id']}), or revert the test edit.")
        if result["errors"]:
            # A headline of its own: an unreadable spec or a malformed record can
            # block on its own, with `unauthorized` empty, and the bare indented
            # `[error]` lines this used to print had nothing above them saying
            # what they were the reason for. "file(s)" rather than "record(s)"
            # because both a spec and an INTENT record land in this list.
            print(f"{len(result['errors'])} file(s) the gate could not read:\n")
        for e in result["errors"]:
            print(f"  [error] {e}")
    for w in result["warnings"]:
        print(f"  [warn] {w}")


def main():
    parser = argparse.ArgumentParser(description="Tier-1 declared-intent gate (G1)")
    parser.add_argument("--project", "-p", default=".", help="Project root (default: .)")
    parser.add_argument("--format", "-f", choices=["text", "json"], default="text")
    parser.add_argument("--advance", action="store_true",
                        help="Write the baseline marker = current HEAD (after a passing wrap-up).")
    parser.add_argument("--force", action="store_true",
                        help="With --advance: advance even when the gate blocks or "
                             "did not run (exit 2 otherwise).")
    args = parser.parse_args()

    if args.advance:
        commit, refused = advance_if_clear(args.project, force=args.force)
        if refused is not None:
            # Two refusals, two remedies, and the same exit 2 — wrap-up only needs
            # to tell refusal from the check's own exit 1. What it must not get is
            # the blocking wording over a skip: there is no BEH-NNN to declare and
            # no edit to revert, so "declare the intent" would send the operator
            # looking for a finding the gate never produced.
            if refused["skipped"]:
                print("refusing to advance the intent baseline — the gate did not run:",
                      file=sys.stderr)
                print(f"  {refused.get('note', 'intent gate skipped')}", file=sys.stderr)
                for w in refused["warnings"]:
                    print(f"  [warn] {w}", file=sys.stderr)
                print("advancing over a gate that checked nothing would clear whatever it "
                      "did not look at. Repair or delete "
                      f"{MARKER_RELPATH} (deleting it re-baselines "
                      "from scratch), or pass --force.", file=sys.stderr)
                sys.exit(2)
            print("refusing to advance the intent baseline — the gate is blocking:",
                  file=sys.stderr)
            for u in refused["unauthorized"]:
                print(f"  [{u['behavior_id']}] {u['spec_id']}: {u['path']}", file=sys.stderr)
            for e in refused["errors"]:
                print(f"  [error] {e}", file=sys.stderr)
            print("advancing would clear this on every future run. Declare the intent "
                  "(intent.py new --behavior BEH-NNN), revert the edit, or pass --force.",
                  file=sys.stderr)
            sys.exit(2)
        if commit:
            print(f"intent baseline advanced to {commit[:10]}")
            sys.exit(0)
        print("could not advance marker (git error)", file=sys.stderr)
        sys.exit(1)

    result = verify_intent(args.project)
    if args.format == "json":
        print(json.dumps(result, indent=2))
    else:
        _print_text(result)
    sys.exit(1 if _blocking(result) else 0)


if __name__ == "__main__":
    main()
