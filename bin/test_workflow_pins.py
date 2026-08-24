#!/usr/bin/env python3
"""Every action this repository runs is named by a commit, not by a tag.

SEC-018. `.github/workflows/pages.yml` holds `pages: write` and
`id-token: write`, and it reached four actions by major tag. A tag is a mutable
pointer in a repository nobody here controls: whoever can move
`actions/deploy-pages@v4` runs their code inside a job that publishes this
project's public site and mints an OIDC token — with no diff in this
repository, no version number changing, and nothing for a reviewer to see.
Pinning to the commit is half the fix. This module is the other half: without a
gate the pin is a convention, and a convention is one convenient pull request
away from being a tag again.

Read as text, not as YAML, because PyYAML is a third-party import and INV-1
(`bin/check_invariants.py`) makes the standard library the whole runtime. That
makes this a YAML subset, so the subset is written down rather than assumed: a
step is a `uses:` key whose entire value sits on the same line, bare or inside
one pair of quotes, opening a sequence item or not. Every other spelling YAML
allows in that position — the value on the next line, a block scalar, an
anchor, an alias, a flow mapping, a quoted key — is legal, is a step GitHub
would run, and is refused **by name** as `UNREADABLE` rather than passed over.
A line this gate cannot read is not a clean line; it is a line nobody checked,
and a supply-chain gate reporting green over an unchecked `uses:` in front of
`pages: write` is worse than no gate. ADR-005, never confidently empty, applied
to the gate itself.

The cost is over-reporting in the other direction: a literal `uses:` inside a
`run: |` block, or in a trailing `#` remark, is read as a step, and the failure
that produces is a demand to pin something that is not an action. Loud, and
wrong in the safe direction. A full-line comment is the one exemption, because
a commented-out step is the ordinary way to park one.

The second half of the module reads `permissions:`, and that half decides
whether the first half's question about a persisted token is asked at all — so
a grant nobody could read is the more expensive of the two silences. The subset
is every spelling GitHub documents: a block mapping of `scope: read|write|none`
under a bare `permissions:`, the same mapping written inline as `{scope: level,
...}`, `read-all` or `write-all` as the whole value, and `{}` for none. One pair
of quotes comes off a scope or a level, and a trailing `# remark` comes off the
end of either — `pages: write   # publish the site` is the line this was fixed
for, and the pattern it replaced anchored past the remark and read that grant as
empty. Every other spelling — an anchor, an alias, a block scalar, a nested flow
collection, a level that is not one of the three, a `permissions:` key with
nothing under it — is refused **by name**, and the refusal makes the checkout
rule run anyway instead of switching it off. Both halves of that matter: a gate
that cannot read a grant must not report the workflow clean, and must not
quietly stop asking the question the grant unlocks.

All of `.github/` is scanned, not only `.github/workflows/`. A composite action
under `.github/actions/` executes third-party code with the same token as the
job that calls it, and a workflows-only scan would never look at it. There are
none today, which is exactly when the wider scope is free.
"""

import re
import shutil
import sys
import tempfile
import unittest
from collections import namedtuple
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

#: Everything GitHub reads: the two workflows, plus any composite action or
#: reusable workflow added later.
GITHUB_DIR = ROOT / ".github"

# The containment rules are owned by freya-code-graph and imported, not copied
# (ADR-030). Two of the four are the right questions here, and they are
# different questions: `escapes` judges a value *declared* in checked-in data —
# a `uses: ./...` target is exactly that, lexical, both path flavours, nothing
# on disk needed — while `rel_within` turns a path the filesystem walk produced
# into the repository-relative spelling a failure message quotes.
_GRAPH_SCRIPTS = ROOT / "skills" / "freya-code-graph" / "scripts"
sys.path.insert(0, str(_GRAPH_SCRIPTS))
from containment import escapes, rel_within  # noqa: E402

#: A `uses:` step reference and the trailing `# vN.N.N` comment it is reviewed
#: by — the one spelling this parser reads, with the whole value on the line.
#: The comment group is optional on purpose: a scanner that only matched
#: well-formed pins would report a clean tree by refusing to see the very lines
#: it exists to find.
USES = re.compile(
    r"^\s*(?:-\s+)?uses:\s*(?P<ref>\S+)\s*(?:#\s*(?P<comment>.*?))?\s*$"
)

#: The same key in any spelling at all, including the ones `USES` cannot read:
#: `uses :`, `"uses":`, `- {uses: ...}`, an anchored value, a value on the next
#: line. Nothing is judged by this pattern. It exists only for the difference
#: between the two — the lines `USES` did not match are the lines this gate did
#: not check, and they have to be told apart from the lines it checked and
#: found clean. The negative lookbehind is what keeps `re-uses:` and `houses:`
#: out; the optional quotes are what catch the JSON-flavoured key.
LOOSE_USES = re.compile(r"""(?<![\w-])["']?uses["']?\s*:""")

#: The `- ` that opens a sequence item, and the width of everything before the
#: item's first key. `step_block` needs both: when `uses:` is itself the opener
#: the step starts on that line, and its sibling keys align at exactly this
#: column.
ITEM_OPENER = re.compile(r"^\s*-\s+")

#: What `ref` says when the parser refused the line. Deliberately not a
#: plausible reference — no owner, no `@`, angle brackets a ref may not contain
#: — so `pin_problem` refuses it by name rather than by falling through some
#: branch meant for a real value, and so a failure message quoting it reads as
#: what it is.
UNREADABLE = "<unreadable uses: line>"

#: YAML value openers this parser will not follow. `|` and `>` put the value on
#: later lines, `&` and `*` put it elsewhere in the document, `{` and `[` put it
#: inside a flow collection nothing here walks. Every one is legal and every one
#: means the text after the colon is not the reference — which is the case for
#: refusing them out loud instead of reading them wrong.
UNFOLLOWABLE = "|>&*{["

#: A full commit id, lowercase. Deliberately not case-insensitive: git, the API
#: and every tool that writes a pin emit lowercase, so mixed case means the
#: value was typed by hand, and the string has to stay byte-comparable with
#: `git ls-remote` output — that command is how a reviewer re-verifies a pin.
SHA = re.compile(r"\A[0-9a-f]{40}\Z")

#: `# v4.1.1`, the conventional form, and the marker Dependabot rewrites when it
#: moves a pin (`.github/dependabot.yml`). Anchored, so `# pinned, see v4` fails.
VERSION_COMMENT = re.compile(r"\Av\d+(?:\.\d+)*\b")

#: The `permissions:` key at workflow or job level — the block that decides
#: what the job's token can do, and so which workflows are worth stealing one
#: from. Read in the one spelling this parser follows: the whole value on the
#: line, or nothing after the colon and the mapping on the lines below.
PERMISSIONS = re.compile(r"^(?P<indent>\s*)permissions:(?P<rest>.*)$")

#: The same key in any spelling at all, and nothing is judged by it — it exists
#: for the same difference `LOOSE_USES` exists for. A `permissions:` line the
#: strict pattern did not match is a line nothing read, and reading it as a
#: workflow that grants nothing is how this rule silently stopped applying.
LOOSE_PERMISSIONS = re.compile(r"""(?<![\w-])["']?permissions["']?\s*:""")

#: A scope name or a permission level: a bare word, or the same word inside one
#: balanced pair of quotes. Both are plain YAML scalars and GitHub reads them
#: identically, so refusing the quoted one would be a rule about typography.
WORD = r"""(?:[\w-]+|"[\w-]+"|'[\w-]+')"""

#: One `scope: level` line of a block mapping. The value is taken as whatever
#: follows the colon rather than matched here, so that a line whose value this
#: parser cannot read is refused with the rest of the block rather than failing
#: to match and being mistaken for the end of it.
SCOPE = re.compile(r"^\s*(?P<scope>%s)\s*:(?P<rest>.*)$" % WORD)

#: One entry of a flow mapping, between the braces and the commas.
FLOW_ENTRY = re.compile(r"^\s*(?P<scope>%s)\s*:\s*(?P<level>%s)\s*$" % (WORD, WORD))

#: A trailing YAML remark. The space before the `#` is required because that is
#: what makes it a comment: `write#publish` is the scalar `write#publish`, and
#: stripping it would turn a line GitHub rejects into one this gate approves.
REMARK = re.compile(r"\s#.*$")

#: The three levels a scope may take, and whether each is a grant. `none` is
#: here because GitHub accepts it and a parser that refused it would go loud on
#: a correct, deliberately-empty permission.
LEVELS = {"read": False, "write": True, "none": False}

#: The two values `permissions:` takes as a whole, in place of a mapping.
GRANT_ALL = {"read-all": False, "write-all": True}

#: What `permission_sites` records about a block it could not read. One message
#: for every unreadable spelling, because the remedy is the same one every time
#: — rewrite the block into the subset above — and because the line number is
#: what the reader actually needs, which the record carries beside it.
UNREADABLE_GRANT = ("this parser cannot read this `permissions:` block, so "
                    "nothing has checked what the job's token can do — write "
                    "it as `scope: read|write|none`, as `{scope: level, ...}`, "
                    "or as `read-all`/`write-all`")

#: The bare lowercase boolean, and only that. Every other spelling is reported
#: as a violation, and every one of those reports is a false positive. At the
#: commit this tree pins — `actions/checkout@3d3c42e5`, v7.0.1 —
#: `src/input-helper.ts` reads the input as
#: `(core.getInput('persist-credentials') || 'false').toUpperCase() === 'TRUE'`,
#: so a case-insensitive `true` is the only value that persists the token:
#: `'false'`, `False`, `no`, `off` and every typo all turn it off, and none of
#: them raises. That holds whichever YAML level GitHub's parser applies to `no`
#: and `off` — read as booleans they stringify to `false`, read as plain
#: strings they are still not `TRUE`. The over-report is chosen anyway. The
#: remedy is to write the canonical form, one keystroke, and a pattern wide
#: enough for every spelling checkout honours is a pattern that reads
#: `persist-credentials: flase` as a considered setting rather than as a line
#: somebody should look at. What may never slip through is the absent key and a
#: literal `true`; this matches neither.
PERSIST_OFF = re.compile(r"^\s*persist-credentials:\s*false\s*$")

Site = namedtuple("Site", "path line ref comment")

#: One `permissions:` block: the line it was read at, whether it grants a write
#: scope, and why it could not be read at all. `grants` is False on an
#: unreadable block and means nothing there — `problem` is the field that
#: decides, and the two are separate so that "grants nothing" and "nobody
#: checked" can never arrive at the caller as the same value.
Permission = namedtuple("Permission", "line grants problem")


def label(path):
    """`path` spelled relative to this repository, in forward slashes.

    Forward slashes on every host because CI runs this on Linux and on Windows,
    and a failure message that reads `.github\\workflows\\ci.yml` on one leg is a
    different string from the same failure on the other. A path outside the
    repository — a fixture tree under the temp directory — keeps its own
    spelling, which is what `rel_within` returning None means.
    """
    rel = rel_within(ROOT, path)
    return (rel.as_posix() if rel is not None else Path(path).as_posix())


def action_files(directory=GITHUB_DIR):
    """Every YAML file under `directory`, sorted, in one predictable order."""
    found = list(directory.rglob("*.yml")) + list(directory.rglob("*.yaml"))
    return sorted(found)


def _unquote(value):
    """`value` with one balanced surrounding pair of quotes taken off.

    `uses: "owner/repo@sha"` is the same step as the bare spelling and
    `pages: 'write'` is the same grant as the bare one, so refusing either
    would make these rules about typography rather than about pins and tokens.
    An unbalanced quote is left where it is: the value continues somewhere this
    parser is not looking, and each caller refuses it on that basis.
    """
    if len(value) > 1 and value[0] in "\"'" and value[-1] == value[0]:
        return value[1:-1]
    return value


def _reference(value):
    """The action reference `value` names, or UNREADABLE when it names none.

    Anything opening with a YAML indicator is refused instead of read. The text
    after the colon is genuinely not the reference in those cases, and a
    scanner that treated `>-` as an action name would go on to demand a commit
    for it — a failure pointing at the wrong thing, which teaches the next
    reader to distrust the gate rather than to fix the line.
    """
    value = _unquote(value)
    if not value or value[0] in UNFOLLOWABLE or '"' in value or "'" in value:
        return UNREADABLE
    return value


def uses_sites(directory=GITHUB_DIR):
    """Every `uses:` in the tree, as (path, line, ref, comment).

    A line naming the key that `USES` could not parse is recorded too, with
    `ref` set to UNREADABLE, rather than passed over. Passing over it is the
    shape of the failure this module exists to prevent, one level up: an
    unpinned action lands in a `pages: write` job, the scanner never sees the
    line, and the gate reports green. Recording it turns the same line into a
    failure naming the file and the line number (ADR-005).

    A full-line comment is skipped before either pattern runs, so a
    commented-out step stays a comment under both.
    """
    sites = []
    for path in action_files(directory):
        text = path.read_text(encoding="utf-8")
        for line, raw in enumerate(text.splitlines(), 1):
            if raw.lstrip().startswith("#"):
                continue
            match = USES.match(raw)
            if match:
                ref = _reference(match.group("ref"))
                comment = None if ref == UNREADABLE else match.group("comment")
                sites.append(Site(label(path), line, ref, comment))
            elif LOOSE_USES.search(raw):
                sites.append(Site(label(path), line, UNREADABLE, None))
    return sites


def pin_problem(ref):
    """Why `ref` is not an immutable pin, or None when it is one.

    Four shapes reach this, and only one of them is a supply chain. The first
    is not a reference at all: UNREADABLE, the marker `uses_sites` leaves on a
    line it could not parse. It fails here, because "this gate did not read the
    line" and "this gate read the line and it was fine" must not arrive at the
    same answer.

    A local `./` action is this repository's own tree at the commit under test,
    so there is nothing to pin — but it still has to stay inside the checkout,
    and `uses: ./../../elsewhere` is a path escape judged by the canonical rule
    rather than by a `..` test invented here.

    Everything else must name a commit. A `docker://` reference carries no
    commit at all and fails on the same branch as a bare `actions/checkout`,
    which is the right answer for the wrong stated reason: it should be pinned
    by image digest, and this rule does not know how to say so. Refuse it and
    let whoever adds one teach the rule, rather than waving it through.
    """
    if ref == UNREADABLE:
        return ("this parser cannot read the `uses:` line, so nothing has "
                "checked it — put the whole reference on the line, unquoted")
    if ref.startswith("./"):
        if escapes(ref[2:]):
            return "local action reaches outside the repository"
        return None
    if "@" not in ref:
        return "names no revision at all"
    rev = ref.rpartition("@")[2]
    if SHA.match(rev):
        return None
    return "`@%s` is a mutable ref, not a commit" % rev


def comment_problem(ref, comment):
    """Why this pin does not say which version it is, or None.

    A bare forty-hex string is unreviewable: nobody can tell v3.0.1 from an
    arbitrary commit on somebody's branch by looking at it, so a pin without
    its version is a pin nobody audits. It is also the marker Dependabot
    rewrites, so dropping it quietly opts the line out of updates.

    An unreadable line is not asked. `pin_problem` already refuses it, and two
    failures about one line would bury the one that says why.
    """
    if ref == UNREADABLE:
        return None
    if ref.startswith("./"):
        return None
    if not comment:
        return "no `# vN.N.N` comment, so the pin is unreadable in review"
    if not VERSION_COMMENT.match(comment):
        return "comment %r does not open with the version it pins" % comment
    return None


def _indent(line):
    return len(line) - len(line.lstrip())


def step_block(lines, index):
    """The whole step whose body contains `lines[index]`.

    Two shapes, differing in which line opens the step, and the second one is
    the trap. Usually a step's keys are indented past the `- name:` that opened
    it, so the step begins at the nearest preceding line indented *less* than
    this one. But when `uses:` is itself the sequence item — `- uses:
    owner/repo@sha`, GitHub's own canonical style for a step that needs no
    `name:` — there is no shallower line inside the step to find, and the
    backward scan runs past its own opener and up to `steps:`, returning every
    step in the job. `token_persisting_checkouts` then reads a
    `persist-credentials: false` belonging to some *other* step and calls this
    checkout protected, which is the one wrong answer that matters: the token
    stays in `.git/config` and the gate says so is fine. So an opener is
    detected first and the step starts there.

    Either way the forward scan ends at the next line indented less than the
    step's own key column — the column, and not a count of two-space levels,
    because the indent width is a style choice a future edit may change, and a
    rule keyed to the number 8 would then pass by reading the wrong step.
    """
    opener = ITEM_OPENER.match(lines[index])
    if opener:
        start, width = index, len(opener.group(0))
    else:
        width = _indent(lines[index])
        start = index
        while start > 0:
            previous = lines[start - 1]
            start -= 1
            if previous.strip() and _indent(previous) < width:
                break
    end = index + 1
    while end < len(lines):
        if lines[end].strip() and _indent(lines[end]) < width:
            break
        end += 1
    return lines[start:end]


def _value_after_colon(rest):
    """What a `key:` line assigns, or None when this parser cannot say.

    `rest` is everything after the colon. It has to open with whitespace or be
    empty, because `permissions:read-all` is not a mapping at all — YAML needs
    the space, GitHub rejects the line, and reading it as a grant would teach
    the gate a spelling nothing accepts. A trailing remark comes off the end;
    everything left is the value, with its own whitespace stripped.
    """
    if rest and not rest[:1].isspace():
        return None
    return REMARK.sub("", rest).strip()


def _scalar_permission(line, value):
    """`permissions: read-all` — the whole mapping replaced by one word.

    Those two words are the only whole-block values GitHub defines, so every
    other scalar is refused rather than guessed at. `permissions: read` reads
    perfectly reasonably and is not a thing; treating it as "grants nothing"
    would be this gate approving a line GitHub itself rejects.
    """
    level = _unquote(value)
    if level not in GRANT_ALL:
        return Permission(line, False, UNREADABLE_GRANT)
    return Permission(line, GRANT_ALL[level], None)


def _flow_permission(line, value):
    """`permissions: {contents: read, pages: write}` — the mapping written inline.

    An empty pair of braces is the documented way to grant nothing, and a
    trailing comma is legal YAML, so both read as a block with no grants rather
    than as a block nobody could read. Anything else between the braces — a
    nested collection, a level outside the three, a mapping that never closes —
    is refused, because the alternative is guessing at what a job's token can do.
    """
    if not value.endswith("}"):
        return Permission(line, False, UNREADABLE_GRANT)
    grants = False
    for entry in value[1:-1].split(","):
        if not entry.strip():
            continue
        found = FLOW_ENTRY.match(entry)
        level = _unquote(found.group("level")) if found else None
        if level not in LEVELS:
            return Permission(line, False, UNREADABLE_GRANT)
        grants = grants or LEVELS[level]
    return Permission(line, grants, None)


def _block_permission(lines, index, indent):
    """`permissions:` with its mapping on the lines below it — the common form.

    The block runs to the first line indented no further than the key itself,
    by column rather than by a count of levels, for the reason `step_block`
    computes the same thing: indent width is a style choice and a rule keyed to
    the number 2 reads the wrong block the day somebody reindents `.github/`.
    Blank lines and full-line comments are passed over inside it, because YAML
    ends a block on neither.

    A refusal names the offending scope line and not the `permissions:` line
    above it, so the failure sends its reader to the line nobody read. The one
    exception is a key with no value and no entries under it at all — `null`
    permissions, which GitHub rejects — where the key itself is the whole of
    the problem and there is no other line to name.
    """
    grants, seen = False, False
    for number, raw in enumerate(lines[index + 1:], index + 2):
        if not raw.strip() or raw.lstrip().startswith("#"):
            continue
        if _indent(raw) <= indent:
            break
        seen = True
        found = SCOPE.match(raw)
        value = _value_after_colon(found.group("rest")) if found else None
        level = _unquote(value) if value else None
        if level not in LEVELS:
            return Permission(number, False, UNREADABLE_GRANT)
        grants = grants or LEVELS[level]
    if not seen:
        return Permission(index + 1, False, UNREADABLE_GRANT)
    return Permission(index + 1, grants, None)


def permission_sites(text):
    """Every `permissions:` block in `text`, as (line, grants, problem).

    A line naming the key that `PERMISSIONS` could not parse is recorded with a
    `problem` rather than passed over, exactly as `uses_sites` records an
    unreadable step. It is the same defect one key up: the pattern this
    replaced was anchored at end of line, so `pages: write  # publish the site`
    matched nothing, the workflow read as granting nothing, and the
    persisted-token rule below stopped running over a job holding
    `pages: write` — with no failure, no marker, and nothing in the output to
    say a workflow had been skipped.

    The cost is the one the `uses:` half already pays: a literal `permissions:`
    inside a `run: |` block, or in a trailing remark, is read as a real key and
    refused. Loud, and wrong in the safe direction.
    """
    lines = text.splitlines()
    sites = []
    for index, raw in enumerate(lines):
        if raw.lstrip().startswith("#"):
            continue
        match = PERMISSIONS.match(raw)
        if match:
            value = _value_after_colon(match.group("rest"))
            if value is None:
                sites.append(Permission(index + 1, False, UNREADABLE_GRANT))
            elif value.startswith("{"):
                sites.append(_flow_permission(index + 1, value))
            elif value:
                sites.append(_scalar_permission(index + 1, value))
            else:
                sites.append(_block_permission(lines, index,
                                               len(match.group("indent"))))
        elif LOOSE_PERMISSIONS.search(raw):
            sites.append(Permission(index + 1, False, UNREADABLE_GRANT))
    return sites


def grants_write(text):
    """Does this workflow hand its job a token that can change anything — or is
    that a question this gate could not answer?

    True on both, deliberately, and `permission_sites` is where the two are
    told apart. Answering False on an unreadable block is the defect this was
    fixed for: `token_persisting_checkouts` asks this before it does anything,
    so one unparseable `permissions:` line switched the persisted-token rule off
    for the whole file and the suite stayed green. Now the rule runs over a
    workflow whose grant nobody could read — over-reporting, the direction this
    module chooses everywhere else — and the shipped-tree test fails naming the
    line, so the spelling gets fixed rather than tolerated.

    NO `permissions:` KEY AT ALL IS ALSO TRUE, and that was the same defect one
    step over: a workflow with no block simply had no sites, so `any([])` was
    False and the persisted-token rule silently did not apply to it. Absent is
    not "grants nothing" — GitHub falls back to the *repository* default, which
    can be read-and-write, so the effective grant is one this parser has no way
    to see. Reachable by the ordinary next edit: adding a workflow file.
    The cost of the over-report is that a genuinely read-only workflow must say
    so, which is a line worth writing in a repository that publishes a site.
    """
    sites = permission_sites(text)
    if not sites:
        return True
    return any(site.grants or site.problem for site in sites)


def token_persisting_checkouts(text):
    """Line numbers of checkout steps that leave the token in `.git/config`.

    Only asked of a workflow that grants a write scope — or whose grant this
    parser could not read, which `grants_write` answers True for and which is
    the whole of that function's fix — because that is where the answer costs
    something. `actions/checkout` defaults
    `persist-credentials` to true, which writes the job's GITHUB_TOKEN into
    `.git/config` as an extraheader every later step in the job can read — and
    in the Pages job that token carries `pages: write` and `id-token: write`
    while `upload-pages-artifact`, running right after it, is deliberately
    given no token of its own. That is not SEC-018 itself; it is the thing that
    makes SEC-018 worth exploiting.

    Only the `uses:` spelling `USES` reads is examined, so a checkout hidden in
    a form this parser refuses is not judged here. It does not have to be:
    `uses_sites` records that line as UNREADABLE and `pin_problem` fails it, so
    no tree containing one is ever green. The guarantee is the suite's, not this
    function's — which is worth knowing before calling it on its own.
    """
    lines = text.splitlines()
    if not grants_write(text):
        return []
    bad = []
    for index, raw in enumerate(lines):
        match = USES.match(raw)
        if not match:
            continue
        if not _reference(match.group("ref")).startswith("actions/checkout@"):
            continue
        if not any(PERSIST_OFF.match(line) for line in step_block(lines, index)):
            bad.append(index + 1)
    return bad


class PinRuleTest(unittest.TestCase):
    """The rule itself, on values rather than on the tree that ships."""

    def test_a_full_commit_id_is_a_pin(self):
        ref = "actions/checkout@3d3c42e5aac5ba805825da76410c181273ba90b1"
        self.assertIsNone(pin_problem(ref))

    def test_a_major_tag_is_not(self):
        self.assertIn("mutable", pin_problem("actions/checkout@v7"))

    def test_an_exact_version_tag_is_not_either(self):
        """`@v7.0.1` looks immutable and is not: a tag is a pointer, and the
        release it names can be re-cut over the same name. The pin has to be
        the commit, and the version belongs in the comment beside it."""
        self.assertIn("mutable", pin_problem("actions/checkout@v7.0.1"))

    def test_a_branch_is_not(self):
        self.assertIn("mutable", pin_problem("actions/checkout@main"))

    def test_an_abbreviated_commit_id_is_not(self):
        """Seven hex characters is still a commit, and still not a pin: a short
        id is a prefix, and a prefix can be made to match a second object."""
        self.assertIn("mutable", pin_problem("actions/checkout@3d3c42e"))

    def test_a_reference_with_no_revision_at_all_is_caught(self):
        self.assertEqual(pin_problem("actions/checkout"), "names no revision at all")

    def test_a_subdirectory_action_is_judged_on_its_revision(self):
        """`owner/repo/path@sha` is one reference with two slashes, and the
        slashes are not what the split is on."""
        ref = "github/codeql-action/init@" + "a" * 40
        self.assertIsNone(pin_problem(ref))

    def test_the_revision_is_taken_from_the_last_at_sign(self):
        """`git check-ref-format` forbids `@{` and a lone `@`, and permits an
        `@` anywhere else, so `v1@2` is a tag somebody may legitimately cut. On
        such a reference the first `@` is part of the name and only the last one
        separates the revision — which is what `rpartition` is for, and what the
        sibling test above cannot show, because one `@` splits the same either
        way."""
        self.assertIsNone(pin_problem("owner/repo/path@v1@" + "a" * 40))
        self.assertIn("mutable", pin_problem("owner/repo/path@" + "a" * 40 + "@v1"))

    def test_an_unreadable_line_is_refused_rather_than_assumed_clean(self):
        """The marker `uses_sites` leaves on a line it could not parse. It has
        to fail: an unchecked line reaching the same verdict as a checked one is
        how a gate reports green over the thing it was written to catch."""
        self.assertIn("cannot read", pin_problem(UNREADABLE))

    def test_a_local_action_needs_no_pin(self):
        self.assertIsNone(pin_problem("./.github/actions/setup"))

    def test_a_local_action_may_not_reach_out_of_the_checkout(self):
        self.assertIn("outside", pin_problem("./../../elsewhere"))

    def test_a_docker_reference_is_refused_rather_than_waved_through(self):
        self.assertIsNotNone(pin_problem("docker://alpine:3.20"))


class CommentRuleTest(unittest.TestCase):
    def test_a_version_comment_passes(self):
        self.assertIsNone(comment_problem("actions/checkout@" + "a" * 40, "v7.0.1"))

    def test_a_bare_major_comment_passes(self):
        self.assertIsNone(comment_problem("actions/checkout@" + "a" * 40, "v7"))

    def test_a_missing_comment_fails(self):
        self.assertIn("unreadable", comment_problem("actions/checkout@" + "a" * 40, None))

    def test_prose_that_merely_mentions_a_version_fails(self):
        problem = comment_problem("actions/checkout@" + "a" * 40, "pinned, see v7")
        self.assertIn("does not open with", problem)

    def test_a_local_action_is_not_asked_for_a_version(self):
        self.assertIsNone(comment_problem("./.github/actions/setup", None))

    def test_an_unreadable_line_is_not_asked_for_one_either(self):
        """`pin_problem` has already failed it. A second failure saying the
        pin has no version comment is true, useless, and printed above the one
        that says the line was never parsed."""
        self.assertIsNone(comment_problem(UNREADABLE, None))


class ScanTest(unittest.TestCase):
    """The text scan, against trees written for the purpose."""

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.tmp, True)

    def _write(self, name, body):
        path = self.tmp / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(body, encoding="utf-8")
        return path

    def test_it_reads_the_reference_and_the_comment_apart(self):
        self._write("w.yml", "jobs:\n  a:\n    steps:\n"
                             "      - uses: actions/checkout@v7 # v7.0.1\n")
        site = uses_sites(self.tmp)[0]
        self.assertEqual((site.line, site.ref, site.comment),
                         (4, "actions/checkout@v7", "v7.0.1"))

    def test_an_uncommented_reference_is_still_found(self):
        self._write("w.yml", "      - uses: actions/checkout@v7\n")
        self.assertEqual([s.ref for s in uses_sites(self.tmp)],
                         ["actions/checkout@v7"])

    def test_both_yaml_spellings_are_read(self):
        self._write("a.yml", "      - uses: one@v1\n")
        self._write("b.yaml", "      - uses: two@v2\n")
        self.assertEqual(sorted(s.ref for s in uses_sites(self.tmp)),
                         ["one@v1", "two@v2"])

    def test_a_nested_composite_action_is_reached(self):
        """The reason the scan is `.github/` and not `.github/workflows/`."""
        self._write("actions/setup/action.yml", "runs:\n  steps:\n"
                                                "    - uses: third/party@v9\n")
        self.assertEqual([s.ref for s in uses_sites(self.tmp)], ["third/party@v9"])

    def test_a_commented_out_step_is_not_a_step(self):
        self._write("w.yml", "      # - uses: actions/checkout@v7\n")
        self.assertEqual(uses_sites(self.tmp), [])

    def test_a_quoted_reference_is_read_without_its_quotes(self):
        """Both quote flavours, and a pin inside them is a pin. Leaving the
        quotes on the ref would make every quoted line fail — safe, but it would
        be a rule about typography wearing a supply chain's clothes."""
        pinned = "actions/checkout@" + "a" * 40
        self._write("s.yml", "      - uses: '%s' # v7.0.1\n" % pinned)
        self._write("d.yaml", '      - uses: "%s" # v7.0.1\n' % pinned)
        sites = uses_sites(self.tmp)
        self.assertEqual([s.ref for s in sites], [pinned, pinned])
        self.assertEqual([pin_problem(s.ref) for s in sites], [None, None])
        self.assertEqual([comment_problem(s.ref, s.comment) for s in sites],
                         [None, None])

    #: Every spelling of a step this parser refuses to read, each one legal
    #: YAML that GitHub executes. `yaml.safe_load` on any of them yields
    #: `{'steps': [{'uses': 'actions/checkout@v7'}]}` — checked by hand, not in
    #: this suite, because importing PyYAML to prove it would break INV-1.
    UNREADABLE_STEPS = {
        "value on the next line":
            "    steps:\n      - name: x\n        uses:\n          third/party@v9\n",
        "anchored value": "    steps:\n      - uses: &a third/party@v9\n",
        "aliased value": "    steps:\n      - uses: *a\n",
        "flow mapping": "    steps:\n      - {uses: third/party@v9}\n",
        "quoted key": '    steps:\n      - {"uses": "third/party@v9"}\n',
        "flow sequence": "    steps: [{uses: third/party@v9}]\n",
        "space before the colon": "    steps:\n      - uses : third/party@v9\n",
        "folded block scalar": "    steps:\n      - uses: >-\n          third/party@v9\n",
        "literal block scalar": "    steps:\n      - uses: |\n          third/party@v9\n",
    }

    def test_a_step_this_parser_cannot_read_goes_red_rather_than_unnoticed(self):
        """The one outcome a supply-chain gate may not have. Each of these is a
        third-party action on a mutable tag, written in a form the strict
        pattern does not match. Recording nothing would report the tree clean;
        what has to happen instead is a failure naming the line."""
        for description, body in sorted(self.UNREADABLE_STEPS.items()):
            with self.subTest(spelling=description):
                tmp = Path(tempfile.mkdtemp())
                self.addCleanup(shutil.rmtree, tmp, True)
                (tmp / "w.yml").write_text(body, encoding="utf-8")
                sites = uses_sites(tmp)
                self.assertEqual([s.ref for s in sites], [UNREADABLE])
                self.assertIsNotNone(pin_problem(sites[0].ref))

    def test_the_refusal_names_the_line_it_could_not_read(self):
        """A gate that fails without a line number sends the next reader to
        read all of `.github/` by eye, and that reader edits the gate out."""
        self._write("w.yml", "jobs:\n  a:\n    steps:\n"
                             "      - {uses: third/party@v9}\n")
        site = uses_sites(self.tmp)[0]
        self.assertEqual((site.path.endswith("w.yml"), site.line), (True, 4))

    def test_a_remark_mentioning_the_key_is_over_reported_not_ignored(self):
        """The stated cost of reading YAML as text, asserted so it stays a
        decision. A trailing `#` remark is not parsed out — telling a real value
        from one inside a comment needs the parser this module does not have —
        so the remark below fails, and the fix is to reword the remark. A
        full-line comment is the exemption, and it is the one that matters."""
        self._write("w.yml", "    steps:  # nothing uses: this yet\n")
        self.assertEqual([s.ref for s in uses_sites(self.tmp)], [UNREADABLE])

    def test_a_word_ending_in_uses_is_not_the_key(self):
        """`LOOSE_USES` is deliberately loose, and the lookbehind is what stops
        loose from meaning useless."""
        self._write("w.yml", "    houses: 1\n    re-uses: 2\n    disuses: 3\n")
        self.assertEqual(uses_sites(self.tmp), [])


class StepBlockTest(unittest.TestCase):
    """Which lines belong to the step, given a line inside it."""

    JOB = ["jobs:", "  a:", "    steps:",
           "      - uses: actions/checkout@x",
           "      - name: Two", "        uses: b@y",
           "      - name: Three", "        uses: c@z"]

    def test_a_name_less_step_is_bounded_by_its_own_sequence_item(self):
        """`- uses:` with no `name:` is GitHub's canonical style, and it is the
        shape with no shallower line inside it to scan back to. Returning the
        whole `steps:` list here is what let one step's setting vouch for
        another's."""
        self.assertEqual(step_block(self.JOB, 3), [self.JOB[3]])

    def test_a_named_step_still_includes_the_line_that_opened_it(self):
        self.assertEqual(step_block(self.JOB, 5), [self.JOB[4], self.JOB[5]])

    def test_a_name_less_step_keeps_its_own_deeper_keys(self):
        lines = ["    steps:", "      - uses: actions/checkout@x",
                 "        with:", "          persist-credentials: false",
                 "      - name: Two", "        uses: b@y"]
        self.assertEqual(step_block(lines, 1), lines[1:4])

    #: The same two shapes at indent widths that are not the tree's own. Every
    #: fixture above puts a step's keys at column 8, which is exactly the value
    #: a rule hard-coded to two levels of two-space indent would produce — so
    #: those fixtures cannot tell the computed column from the constant, and
    #: the docstring's reason for computing it goes untested. These two can.
    NARROW = ["jobs:", "  a:", "    steps:",
              "    - uses: actions/checkout@x",
              "      with:", "        persist-credentials: false",
              "    - name: Two", "      uses: b@y"]
    WIDE = ["jobs:", "  a:", "        steps:",
            "          - name: Two", "            uses: b@y",
            "            with:", "          - name: Three",
            "            uses: c@z"]

    def test_the_boundary_is_the_step_own_column_not_a_fixed_indent(self):
        """Indent width is a style choice, and a rule keyed to the number 8
        reads the wrong step the day somebody reindents `.github/`. Both
        branches are here: the narrow tree stops a name-less step short of its
        own `with:` block, and the wide one sends a named step's backward scan
        past `steps:` and up into the job."""
        self.assertEqual(step_block(self.NARROW, 3), self.NARROW[3:6])
        self.assertEqual(step_block(self.WIDE, 4), self.WIDE[3:6])


class PermissionScopeTest(unittest.TestCase):
    """What the token can do — and whether that could be read at all."""

    #: Every spelling of `permissions:` GitHub documents, and what each grants.
    #: The tree writes exactly one of them, `block mapping`. The rest are here
    #: because a gate that reads only the spelling already in front of it is a
    #: gate that stops working at the next edit, and that is how this hole was
    #: found: nobody had yet written `a remark after the level`, which is the
    #: same grant as the first row and used to be read as the opposite of it.
    READABLE = {
        "block mapping": ("permissions:\n  contents: read\n  pages: write\n", True),
        "block mapping, read only": ("permissions:\n  contents: read\n", False),
        "an explicit none": ("permissions:\n  contents: none\n", False),
        "a remark after the level": ("permissions:\n  pages: write   # publish the site\n", True),
        "a remark after the key": ("permissions:  # the deploy needs these\n  pages: write\n", True),
        "a quoted level": ("permissions:\n  pages: 'write'\n", True),
        "a quoted scope": ('permissions:\n  "pages": write\n', True),
        "space before the colon": ("permissions:\n  pages : write\n", True),
        "a blank line inside the block": ("permissions:\n\n  pages: write\n", True),
        "a comment line inside the block": ("permissions:\n  # for the deploy\n  pages: write\n", True),
        "a job-level block": ("jobs:\n  deploy:\n    permissions:\n      pages: write\n    steps:\n", True),
        "flow mapping": ("permissions: {contents: read, pages: write}\n", True),
        "flow mapping, read only": ("permissions: {contents: read}\n", False),
        "flow mapping, trailing comma": ("permissions: {pages: write,}\n", True),
        "flow mapping granting nothing": ("permissions: {}\n", False),
        "write-all": ("permissions: write-all\n", True),
        "read-all": ("permissions: read-all\n", False),
        "a quoted write-all": ("permissions: 'write-all'\n", True),
    }

    def test_every_spelling_github_accepts_is_read_rather_than_refused(self):
        """One site per row, no problem on any of them, and the grant read
        correctly in both directions — the second half being what stops the fix
        from being "call everything a grant and claim vigilance"."""
        for description, (body, grants) in sorted(self.READABLE.items()):
            with self.subTest(spelling=description):
                self.assertEqual([site.problem for site in permission_sites(body)],
                                 [None])
                self.assertEqual(grants_write(body), grants)

    #: Every spelling this parser refuses. Each is either legal YAML that this
    #: subset does not cover, or a line GitHub itself rejects — and either way
    #: what the old pattern did with it was return False and move on.
    UNREADABLE = {
        "anchored value": "permissions: &p\n  pages: write\n",
        "aliased value": "permissions: *p\n",
        "folded block scalar": "permissions: >-\n  write-all\n",
        "a nested flow collection": "permissions: {contents: {read: true}}\n",
        "a flow mapping that never closes": "permissions: {contents: read,\n",
        "a level outside the three": "permissions:\n  pages: writable\n",
        "a scope with no level": "permissions:\n  pages:\n    - write\n",
        "a sequence where a mapping belongs": "permissions:\n  - pages: write\n",
        "no value and no block under it": "permissions:\n",
        "no space after the colon": "permissions:read-all\n",
        "a scalar that is neither read-all nor write-all": "permissions: read\n",
        "space before the colon": "permissions : write-all\n",
        "a quoted key": '"permissions": write-all\n',
        "a remark with no space in front of it": "permissions:\n  pages: write#publish\n",
    }

    def test_a_grant_this_parser_cannot_read_is_named_rather_than_read_as_empty(self):
        """The finding, stated as the rule it broke. Every row records one site
        carrying a problem; none of them is passed over, and none of them
        arrives at the caller looking like a workflow that grants nothing."""
        for description, body in sorted(self.UNREADABLE.items()):
            with self.subTest(spelling=description):
                sites = permission_sites(body)
                self.assertEqual(len(sites), 1)
                self.assertIsNotNone(sites[0].problem)

    def test_a_commented_out_block_is_not_a_block(self):
        """The exemption `uses_sites` makes, for the same reason: parking a
        block behind a `#` while you work out what a job needs is ordinary, and
        reading it as a real key would fail the tree over a line GitHub never
        sees. It is the one place a `permissions:` this parser did not parse is
        allowed to record nothing."""
        self.assertEqual(
            permission_sites("# permissions: write-all\n  # pages: write\n"), [])

    def test_a_workflow_with_no_permissions_key_is_an_unknown_grant_not_an_empty_one(self):
        """The sibling of the unreadable-block case, and it was still open after
        that one was fixed.

        A workflow with no `permissions:` at all simply had no sites, so
        `any([])` was False, `grants_write` said no, and the persisted-token
        rule silently did not apply to the whole file. Absent is not "grants
        nothing": GitHub falls back to the repository default, which can be
        read-and-write, so the effective grant is one this parser cannot see —
        the exact thing the module's own docstring says must not produce a clean
        report.

        Reachable by the ordinary next edit. Both shipped workflows declare a
        block today, which is why the tree stayed green over it and why this
        fixture is synthetic.
        """
        no_block = ("name: Release\non: push\njobs:\n  build:\n"
                    "    runs-on: ubuntu-latest\n    steps:\n"
                    "      - uses: actions/checkout@" + "3d3c42e5" + "a" * 32 + "\n")
        self.assertEqual(permission_sites(no_block), [])
        self.assertTrue(grants_write(no_block),
                        "a grant this gate cannot see must not read as no grant")
        self.assertEqual(token_persisting_checkouts(no_block), [7],
                         "and the rule that grant unlocks must actually run")

    def test_the_key_named_inside_a_run_block_is_over_reported_not_ignored(self):
        """The stated cost of reading YAML as text, asserted so it stays a
        decision. Telling a real key from the same word inside a `run:` script
        or a trailing remark needs the parser this module does not have, so the
        line is refused and the fix is to reword it. Wrong in the safe
        direction, and the `uses:` half already pays exactly this."""
        body = "    steps:\n      - run: echo 'permissions: write-all'\n"
        self.assertEqual([site.problem is not None
                          for site in permission_sites(body)], [True])

    def test_the_refusal_names_the_line_it_could_not_read(self):
        """A scope line the parser could not read is reported at its own line
        and not at the `permissions:` key above it, for the reason the `uses:`
        half reports the same way: a failure without a line number sends its
        reader to read all of `.github/` by eye."""
        sites = permission_sites("permissions:\n  contents: read\n  pages: writable\n")
        self.assertEqual([(s.line, s.problem is None) for s in sites], [(3, False)])

    #: A job whose checkout takes the `persist-credentials` default, appended to
    #: each grant above. Nothing about it varies between rows: the row is the
    #: `permissions:` spelling, and the answer is whether the rule ran at all.
    CHECKOUT = ("jobs:\n  deploy:\n    steps:\n"
                "      - uses: actions/checkout@%s\n" % ("a" * 40))

    def test_an_unreadable_grant_still_asks_the_persisted_token_question(self):
        """The consequence, which is the finding itself: the pin gate read an
        unparseable `permissions:` line as granting nothing, `grants_write`
        returned False, and `token_persisting_checkouts` returned `[]` without
        examining a single step. A checkout leaving a write-scoped GITHUB_TOKEN
        in `.git/config` went unflagged and the shipped-tree test stayed green.
        Each of these bodies now reaches the rule instead of switching it off."""
        for description, body in sorted(self.UNREADABLE.items()):
            with self.subTest(spelling=description):
                self.assertTrue(token_persisting_checkouts(body + self.CHECKOUT))

    def test_a_readable_read_only_grant_is_still_not_asked(self):
        """The control for the test above, on the two parse paths that are new:
        refusing to read a block must not become refusing to read any block."""
        for description, body in [("block", "permissions:\n  contents: read\n"),
                                  ("flow", "permissions: {contents: read}\n"),
                                  ("read-all", "permissions: read-all\n")]:
            with self.subTest(spelling=description):
                self.assertEqual(token_persisting_checkouts(body + self.CHECKOUT), [])


class PersistedCredentialTest(unittest.TestCase):
    """The checkout that leaves a write-scoped token behind it."""

    WRITE_JOB = (
        "permissions:\n"
        "  contents: read\n"
        "  pages: write\n"
        "jobs:\n"
        "  deploy:\n"
        "    steps:\n"
        "      - name: Checkout\n"
        "        uses: actions/checkout@%s\n"
        "%s"
        "      - name: Next\n"
        "        uses: actions/deploy-pages@%s\n"
    ) % ("a" * 40, "%s", "b" * 40)

    def test_a_write_scoped_checkout_with_the_default_is_flagged(self):
        self.assertEqual(token_persisting_checkouts(self.WRITE_JOB % ""), [8])

    def test_turning_it_off_clears_the_flag(self):
        body = self.WRITE_JOB % ("        with:\n"
                                 "          persist-credentials: false\n")
        self.assertEqual(token_persisting_checkouts(body), [])

    #: The same job in GitHub's canonical style: the checkout needs no `name:`,
    #: so `uses:` is itself the sequence item. Both shapes are here because the
    #: shape is what the step-boundary rule turns on, and the tree happens to
    #: ship only the `- name:` one — which is how a hole survived a test written
    #: for it.
    CANONICAL_JOB = (
        "permissions:\n"
        "  contents: read\n"
        "  pages: write\n"
        "jobs:\n"
        "  deploy:\n"
        "    steps:\n"
        "      - uses: actions/checkout@%s\n"
        "%s"
        "      - name: Next\n"
        "        uses: actions/deploy-pages@%s\n"
    ) % ("a" * 40, "%s", "b" * 40)

    def test_the_setting_must_belong_to_the_checkout_step(self):
        """The same two lines under the *next* step do not protect the
        checkout. A rule that searched the whole file for the string would call
        this clean, and the token would still be in `.git/config`."""
        body = self.WRITE_JOB.replace(
            "      - name: Next\n",
            "      - name: Next\n        with:\n"
            "          persist-credentials: false\n") % ""
        self.assertEqual(token_persisting_checkouts(body), [8])

    def test_the_setting_must_belong_to_a_name_less_checkout_too(self):
        """The same assertion on the `- uses:` shape, which is the one that was
        wrong. The step has no `name:` line above it to bound it, so a rule that
        scans back for a shallower line reaches `steps:` and reads the whole
        job — including the *next* step's `persist-credentials: false`, which
        protects nothing here."""
        body = self.CANONICAL_JOB.replace(
            "      - name: Next\n",
            "      - name: Next\n        with:\n"
            "          persist-credentials: false\n") % ""
        self.assertEqual(token_persisting_checkouts(body), [7])

    def test_a_name_less_checkout_with_the_default_is_flagged(self):
        self.assertEqual(token_persisting_checkouts(self.CANONICAL_JOB % ""), [7])

    def test_a_name_less_checkout_is_cleared_by_its_own_setting(self):
        """The other direction, so the fix above cannot be a rule that flags
        every name-less checkout and calls that vigilance."""
        body = self.CANONICAL_JOB % ("        with:\n"
                                     "          persist-credentials: false\n")
        self.assertEqual(token_persisting_checkouts(body), [])

    def test_the_setting_is_read_for_its_value_not_its_presence(self):
        """`persist-credentials: true` is the default written out, and a rule
        keyed to the key rather than the value would read the line that says
        "leave the token here" as protection against leaving the token here."""
        body = self.CANONICAL_JOB % ("        with:\n"
                                     "          persist-credentials: true\n")
        self.assertEqual(token_persisting_checkouts(body), [7])

    #: Every value `actions/checkout` honours as off that this rule reports
    #: anyway. Each one reaches
    #: `(getInput(...) || 'false').toUpperCase() === 'TRUE'` as something other
    #: than `TRUE`, so each one leaves the token out of `.git/config` and the
    #: report below is a false positive by construction, not by accident.
    HONOURED_BUT_REFUSED = ["'false'", '"false"', "False", "FALSE", "no", "off"]

    def test_every_spelling_but_the_canonical_one_is_reported_anyway(self):
        """`PERSIST_OFF`'s false positives, asserted so they stay a choice
        rather than becoming a discovery — and so the constant cannot be
        widened to admit one of them without a test saying which. The remedy in
        every case is to write `false`."""
        for spelling in self.HONOURED_BUT_REFUSED:
            with self.subTest(value=spelling):
                body = self.CANONICAL_JOB % (
                    "        with:\n"
                    "          persist-credentials: %s\n" % spelling)
                self.assertEqual(token_persisting_checkouts(body), [7])

    def test_a_quoted_checkout_is_still_a_checkout(self):
        """The step-level rule reads the reference through the same unquoting
        as the pin rule. Matching the raw text instead would let one pair of
        quotes hide the checkout from this question entirely — and unlike an
        unreadable line, a quoted line raises nothing anywhere else."""
        quoted = self.CANONICAL_JOB.replace(
            "- uses: actions/checkout@" + "a" * 40,
            "- uses: 'actions/checkout@%s'" % ("a" * 40)) % ""
        self.assertEqual(token_persisting_checkouts(quoted), [7])

    def test_a_read_only_workflow_is_not_asked(self):
        """ci.yml's shape. Nothing is granted, so nothing is worth persisting,
        and demanding the setting there would be noise rather than a rule."""
        read_only = self.WRITE_JOB.replace("  pages: write\n", "") % ""
        self.assertEqual(token_persisting_checkouts(read_only), [])

    def test_a_job_level_grant_counts_as_much_as_a_workflow_level_one(self):
        moved = self.WRITE_JOB.replace(
            "permissions:\n  contents: read\n  pages: write\n", "")
        moved = moved.replace("  deploy:\n",
                              "  deploy:\n    permissions:\n      pages: write\n") % ""
        self.assertTrue(token_persisting_checkouts(moved))


class ShippedWorkflowTest(unittest.TestCase):
    """The guarantees the module exists to make, asserted on the real tree.

    Every class above builds a fixture. None of them looks at what actually
    runs on push, which is how four mutable tags sat in front of `pages: write`
    for a release and a half.
    """

    def test_every_action_is_pinned_to_a_commit(self):
        bad = [(site, pin_problem(site.ref)) for site in uses_sites()]
        bad = [(site, why) for site, why in bad if why]
        detail = "\n".join("%s:%d: %s: %s" % (s.path, s.line, s.ref, why)
                           for s, why in bad)
        self.assertEqual(bad, [], "unpinned actions:\n" + detail)

    def test_every_pin_records_the_version_it_was_taken_from(self):
        bad = [(site, comment_problem(site.ref, site.comment))
               for site in uses_sites()]
        bad = [(site, why) for site, why in bad if why]
        detail = "\n".join("%s:%d: %s: %s" % (s.path, s.line, s.ref, why)
                           for s, why in bad)
        self.assertEqual(bad, [], "pins nobody can review:\n" + detail)

    def test_no_write_scoped_job_persists_its_token_into_git_config(self):
        bad = []
        for path in action_files():
            text = path.read_text(encoding="utf-8")
            bad += ["%s:%d" % (label(path), line)
                    for line in token_persisting_checkouts(text)]
        self.assertEqual(bad, [], "checkouts leaving a write token behind: %s" % bad)

    def test_the_scan_found_the_files_it_is_supposed_to_check(self):
        """A guard against every assertion above passing over an empty list —
        the shape of the six green-and-vacuous tests this repository has found
        in itself.

        Named rather than counted, and a subset rather than an equality. Named,
        because a count survives `pages.yml` being renamed out from under the
        scan and `pages.yml` is the whole of SEC-018. A subset, because a
        composite action added later is a file this scan *should* pick up, and
        a rule that went red for finding more work to do would be edited out
        rather than obeyed.
        """
        required = {".github/workflows/ci.yml", ".github/workflows/pages.yml"}
        missed = required - {site.path for site in uses_sites()}
        self.assertEqual(missed, set(),
                         "workflows the scan never opened: %s" % sorted(missed))
        self.assertGreaterEqual(len(uses_sites()), 8)

    def test_every_permissions_block_in_the_tree_is_one_this_gate_can_read(self):
        """The `uses:` half's guarantee, one key up. A `permissions:` block
        written outside the readable subset does not fail the rule below — it
        stops the rule below from running — so it has to fail here, on its own,
        with a message asking for a rewrite rather than for a setting.
        """
        unread = []
        for path in action_files():
            unread += ["%s:%d" % (label(path), site.line)
                       for site in permission_sites(path.read_text(encoding="utf-8"))
                       if site.problem]
        self.assertEqual(unread, [],
                         "`permissions:` blocks written in a form this gate "
                         "cannot check, so nothing has checked what those "
                         "tokens can do: %s" % unread)

    def test_the_scan_read_the_grants_it_is_supposed_to_find(self):
        """The guard against the test above passing over an empty list, and it
        is not hypothetical: every assertion about permissions in this module
        is vacuous the moment `permission_sites` stops matching, and stopping
        matching is precisely what the pattern it replaced did.

        Both directions are named, because one alone is satisfied by a broken
        parser: pages.yml must read as granting write, so the persisted-token
        rule really runs over the job SEC-018 is about, and ci.yml must read as
        read-only, so the parser cannot be one that calls everything a grant.
        """
        read = {label(path): grants_write(path.read_text(encoding="utf-8"))
                for path in action_files()}
        self.assertEqual(read.get(".github/workflows/pages.yml"), True,
                         "the Pages workflow's write grant was not read: %s" % read)
        self.assertEqual(read.get(".github/workflows/ci.yml"), False,
                         "CI reads as write-scoped or unreadable: %s" % read)

    def test_the_scan_read_every_line_it_found(self):
        """`test_every_action_is_pinned_to_a_commit` already fails on an
        unreadable line, since `pin_problem` refuses the marker. This says the
        same thing in the words a reader needs: the failure is not "pin this",
        it is "rewrite this line into the subset the parser reads", and the two
        deserve different messages.
        """
        unread = ["%s:%d" % (s.path, s.line)
                  for s in uses_sites() if s.ref == UNREADABLE]
        self.assertEqual(unread, [],
                         "`uses:` lines written in a form this gate cannot "
                         "check, so nothing has checked them: %s" % unread)


if __name__ == "__main__":
    unittest.main()
