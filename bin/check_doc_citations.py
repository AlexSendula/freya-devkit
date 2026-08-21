#!/usr/bin/env python3
"""Guard prose-to-code citations against drift.

Every ADR, spec and reference page in this repo backs its claims with
`path.py:NNN` citations, and nothing checked them. The line numbers rot the
moment the cited file is edited. Measured at 296deda: the 101 tracked markdown
files carry 1,053 machine-checkable citations, 859 of them into a Python file
that still exists — and 20 of those land on a **blank line**. Nobody cites
whitespace, so every one is drift a reader would have taken as provenance.
Five commits running fixed citations by hand. This is the gate that does it
deterministically instead (Tier 1 under ADR-009: it blocks).

It is the sibling of bin/check_skill_conformance.py and is built to the same
shape: same argument handling, same `path:line: RULE: excerpt` output, same
exit codes. It covers what that one does not — the conformance gate hardcodes
`(root / "skills")`, which reaches 18 of those 101 files and left the other 83,
under knowledge-base/ and at the repo root, with no gate of any kind.

Three things are deliberately *not* errors:

* **Comment lines.** 80 citations land on a `#` line, and that is usually
  correct here: the constants in skills/freya-code-graph/scripts/substrate.py
  are documented in `#:` blocks, and an ADR citing the reasoning cites the
  comment.
* **A bare filename nothing in the tree matches.** `foo.py:12` is a
  convenience, not a path — this repo's ADRs write the full path once and the
  basename after that — so it is resolved against the tracked tree by path
  suffix. When that finds nothing there is no evidence of drift: 11 of the 13
  are basenames of the deleted design documents (`00-vision.md:41`) and the
  other two are ADR-023 citing `affected.py:12` and `resolution.py:671` inside
  the third-party graphify package, which is not in this tree and never will
  be. A citation carrying a directory component *does* assert a location here,
  so C1 applies to it.
* **An ambiguous suffix.** 19 citations name a bare `SKILL.md`, which ten
  tracked files match. Nothing can be concluded, so nothing is.

Both skipped kinds are counted and reported on stderr rather than dropped
silently.

Out of scope, stated with its size so it is not mistaken for coverage: the
continuation form `(`substrate.py:721`, `:724`)`, where a bare `:NNN` inherits
the path from the citation before it on the same line. There are 293 of those,
and resolving them means carrying state across a line.
"""

from __future__ import annotations

import argparse
import re
import subprocess
import sys
from collections import defaultdict, namedtuple
from pathlib import Path

RULES = {
    "C1": "cited file is not in the tracked tree — the path moved, or was deleted "
          "without the citation following it",
    "C2": "line number is past the end of the cited file",
    "C3": "citation lands on a blank line — nobody cites whitespace, so the file "
          "was edited under the citation",
}

#: Path prefixes whose citations are *not* expected to resolve against the
#: working tree, so they are not checked at all.
#:
#: The first three are the design documents these ADRs were distilled from —
#: docs/design/ and docs/superpowers/ deleted 2026-08-19, docs/polyglot/ on
#: 2026-08-21 — and knowledge-base/decisions/README.md says in as many words
#: that they resolve against git history (`git show 04a9b8b:<path>`, and
#: `git show 2762d54:<path>` for docs/polyglot/) and that the line numbers are
#: kept deliberately, "because a citation without a line is not provenance".
#: Flagging the 58 citations the records document as historical (44 into
#: docs/design/, 14 into docs/superpowers/) is how you build a gate that gets
#: deleted. docs/polyglot/ carries none with a line number today; it is listed
#: because the README says citations into it resolve the same way.
#:
#: `src/` is different: this repo has no src/ tree and will not grow one. Every
#: `src/...` citation is sample output inside a skill's example block
#: (`src/api/users.ts:45` in the resolver's impact-analysis illustration) or a
#: path from the phase-7 test fixture (`src/auth.js:5`). They are illustrations
#: of the citation *format*, not claims about this codebase.
EXEMPT_PREFIXES = (
    "docs/design/",
    "docs/polyglot/",
    "docs/superpowers/",
    "src/",
)

#: A `path:NNN` citation. The final component must carry a 1-4 letter
#: extension, which is what separates a citation from a bare `word:12`; the
#: leading lookbehind keeps the match off the tail of a longer token, so a URL
#: (`https://host/a.py:12`) and a path fragment inside a longer path both fail
#: to start a match rather than matching their own suffix. The trailing `\b`
#: rejects `a.py:12x`.
CITATION = re.compile(
    r"(?<![\w/.-])"
    r"((?:[\w.-]+/)*[\w-][\w.-]*\.[A-Za-z]{1,4})"
    r":(\d+)\b"
)

#: A full citation OR a *continuation* — a backticked bare `` `:NNN` `` that
#: means "the same file as the citation before me". The continuation is the
#: dominant shape in the ADRs, which write the path once and then a run of line
#: numbers: ``(`substrate.py:142`, `:154`, `:160`)``. There are 293 of them in
#: the tracked markdown and the first version of this gate resolved none, so it
#: printed a clean bill for a seventh of its input that it had never looked at.
#:
#: Backticks are required here and nowhere else in the grammar. A bare `:724`
#: loose in prose is the tail of a ratio, a time, or a sentence; requiring the
#: delimiters is what keeps this from being the kind of over-matching check
#: people switch off.
#: A range (`a.py:202-209`, `` `:202-209` ``) is cited by its START. The end
#: bound is prose — "and the few lines after" — and requiring it to be in range
#: would fail citations that are exact about where a construct begins and vague
#: about where it stops. The continuation form has to spell the range out
#: because it anchors on a closing backtick, and without it a range was not a
#: near-miss but a total miss: one repair found a continuation range bound 105
#: lines past its file's end, unseen because the regex never matched it.
ANY_CITATION = re.compile(
    r"(?<![\w/.-])"
    r"(?P<path>(?:[\w.-]+/)*[\w-][\w.-]*\.[A-Za-z]{1,4}):(?P<line>\d+)\b"
    r"|`:(?P<cont>\d+)(?:-\d+)?`"
)

#: What scan() reports: the violations, plus the census of what it did *not*
#: check. The counts are the whole reason this is not a bare list — a gate that
#: skips a fifth of its input and never says so is the failure mode this repo
#: keeps finding in its own tests.
Report = namedtuple("Report", "violations checked exempt unresolved")


def _git(root, *args):
    """Run git in root; return (returncode, stdout). Never raises."""
    try:
        out = subprocess.run(["git", "-C", str(root), *args],
                             capture_output=True, text=True)
    except (OSError, ValueError):
        return 1, ""
    return out.returncode, out.stdout


def tracked_files(root):
    """Return every git-tracked path under root, as forward-slash strings.

    Tracked, not globbed: a filesystem walk picks up `graphify-out/` reports
    and the nine `.pytest_cache/README.md` files, none of which anyone cites or
    maintains. Forward slashes come from git on every platform, so the reported
    paths are identical on Windows and Linux.

    Raises ValueError when git cannot answer. An empty answer is refused for
    the same reason: a gate that scans nothing must not print a clean bill of
    health (ADR-029, and the two silent-false-result paths closed in the
    2026-08-18 review).
    """
    rc, out = _git(root, "ls-files", "-z")
    if rc != 0:
        raise ValueError(f"git ls-files failed in {root}: not a git work tree?")
    files = sorted(part for part in out.split("\0") if part)
    if not files:
        raise ValueError(f"no tracked files under {root}")
    return files


def suffix_index(files):
    """Map every trailing path-component run to the tracked files that end with it.

    `skills/freya-code-graph/scripts/substrate.py` is indexed under
    `substrate.py`, `scripts/substrate.py`, `freya-code-graph/scripts/...` and
    its whole self. That single table resolves both shapes this repo's prose
    uses: the bare basename (`substrate.py:57`, 514 of the 1,053) and the
    partial path (`freya-wrap-up/SKILL.md:471`, written relative to skills/).
    """
    index = defaultdict(list)
    for rel in files:
        parts = rel.split("/")
        for start in range(len(parts)):
            index["/".join(parts[start:])].append(rel)
    return index


def resolve(cited, tracked, index):
    """Return the tracked path a citation names, or None.

    None covers two different things on purpose — nothing matched, and more
    than one did — because neither is evidence of drift, and check_file() tells
    them apart from the citation's own shape.
    """
    if cited in tracked:
        return cited
    candidates = index.get(cited, ())
    return candidates[0] if len(candidates) == 1 else None


def citations(lines):
    """Yield (lineno, cited_path, cited_lineno) for each citation in a file.

    Handles both the full form and the continuation (see `ANY_CITATION`). The
    antecedent carries across a line break, because prose wraps and the citation
    does not stop at the wrap — ADR-021 establishes `substrate.py` at the end of
    one line and continues with `` `:773` `` on the next.

    Scoped to one document: `path` starts empty on every call and this is called
    per file, so a bare number with nothing before it yields nothing rather than
    resolving against whatever the previous document happened to cite. Inventing
    a file there would be worse than missing one.
    """
    path = None
    for lineno, line in enumerate(lines, 1):
        for match in ANY_CITATION.finditer(line):
            cited, cont = match.group("path"), match.group("cont")
            if cited:
                path = cited
                yield lineno, path, int(match.group("line"))
            elif path is not None:
                yield lineno, path, int(cont)


def check_file(rel, lines, tracked, index, read_lines):
    """Return (violations, checked, exempt, unresolved) for one markdown file.

    `read_lines` maps a tracked path to its lines; injected so one cited file
    is read once per scan rather than once per citation (graph_ops.py is cited
    from nine different documents).
    """
    violations = []
    checked = exempt = unresolved = 0

    for lineno, cited, cited_line in citations(lines):
        if cited.startswith(EXEMPT_PREFIXES):
            exempt += 1
            continue
        target = resolve(cited, tracked, index)
        if target is None:
            # A directory component is a claim about where the file lives here;
            # a bare name is not, and is left alone. See the module docstring.
            if "/" in cited:
                violations.append((rel, lineno, "C1", f"{cited}:{cited_line}"))
            else:
                unresolved += 1
            continue
        checked += 1
        target_lines = read_lines(target)
        if cited_line < 1 or cited_line > len(target_lines):
            violations.append((
                rel, lineno, "C2",
                f"{cited}:{cited_line} -> {target} has {len(target_lines)} lines",
            ))
        elif not target_lines[cited_line - 1].strip():
            violations.append((
                rel, lineno, "C3", f"{cited}:{cited_line} -> {target}:{cited_line} is blank",
            ))

    return violations, checked, exempt, unresolved


def scan(root, rules=None):
    """Check every citation in every tracked .md file. Returns a Report."""
    root = Path(root)
    tracked = tracked_files(root)
    index = suffix_index(tracked)
    tracked_set = set(tracked)
    cache = {}

    def read_lines(target):
        if target not in cache:
            cache[target] = (root / target).read_text(
                encoding="utf-8", errors="replace").splitlines()
        return cache[target]

    violations = []
    checked = exempt = unresolved = 0
    for rel in tracked:
        if not rel.endswith(".md"):
            continue
        lines = (root / rel).read_text(encoding="utf-8", errors="replace").splitlines()
        found, n_checked, n_exempt, n_unresolved = check_file(
            rel, lines, tracked_set, index, read_lines)
        violations.extend(found)
        checked += n_checked
        exempt += n_exempt
        unresolved += n_unresolved

    if rules is not None:
        violations = [v for v in violations if v[2] in rules]
    return Report(sorted(violations), checked, exempt, unresolved)


def main(argv=None):
    parser = argparse.ArgumentParser(
        description="Check that path:line citations in the docs still resolve."
    )
    parser.add_argument("--root", type=Path, default=None, help="Repo root (default: this checkout)")
    parser.add_argument(
        "--rule", action="append", choices=sorted(RULES), help="Only report these rules (repeatable)"
    )
    args = parser.parse_args(argv)

    root = args.root if args.root is not None else Path(__file__).resolve().parents[1]

    try:
        report = scan(root, rules=set(args.rule) if args.rule else None)
    except (OSError, ValueError) as exc:
        print(f"check-doc-citations: {exc}", file=sys.stderr)
        return 2

    for rel, lineno, rule, excerpt in report.violations:
        print(f"{rel}:{lineno}: {rule}: {excerpt}")

    print(
        f"  {report.checked} checked, {report.exempt} exempt (git history, examples), "
        f"{report.unresolved} unresolvable bare name(s) skipped",
        file=sys.stderr,
    )

    if report.violations:
        counts = {}
        for _, _, rule, _ in report.violations:
            counts[rule] = counts.get(rule, 0) + 1
        print(file=sys.stderr)
        for rule in sorted(counts):
            print(f"  {rule} ({counts[rule]}): {RULES[rule]}", file=sys.stderr)
        print(f"\n{len(report.violations)} citation(s) do not resolve.", file=sys.stderr)
        return 1

    print(f"{report.checked} doc citation(s) resolve.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
