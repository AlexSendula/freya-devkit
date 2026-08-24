#!/usr/bin/env python3
"""Per-project freya settings — `knowledge-base/settings.json`.

The toolkit had nowhere to record a project-level choice. Directory classifications lived in
`knowledge-base/.graph/classifications.json`, which is gitignored regenerable cache: fine for a
derived verdict, wrong for a decision. Anything stored there is lost on `--clear` and never
reaches a fresh clone, so every checkout would re-decide.

`knowledge-base/` is where this belongs (ADR-019). It already exists wherever freya runs, its name
is fixed rather than configurable, and only `.graph/` inside it is gitignored — `specs/`,
`decisions/` and `principles.md` are tracked, so a settings file beside them is committed by
default and travels with the repo. It also keeps the project root clean, which a `freya.json`
would not.

Not `package.json`: Java, Python and Go repos do not have one, and keying the polyglot
toolkit's own configuration to a Node manifest is the framework assumption Track B exists to
remove. Worth supporting later as an *optional* override for Node projects; never as the home.

Absent or malformed, the file yields defaults. A build must not fail because configuration is
missing — the whole point of `auto` is that a project works before anyone configures anything.

Shape:

    {
      "substrate": {
        "backend": "auto",         // auto | homegrown | <name of an installed backend>
        "symbols": false           // record which symbol each edge leaves and arrives at
      },
      "directories": {
        "docs": "source",          // this project's docs/ really is source
        "packages/legacy": "exclude"
      },
      "outside": {
        "ui": "../packages/ui"     // a sibling checkout this project's code imports
      }
    }

`directories` is where a project argues with the built-in exclusion lists. It landed here on
2026-08-20 rather than in `classifications.json`, which is where the override was first put —
and which is the mistake this module's second paragraph was already written to prevent. An
override survived on the machine that made it and vanished on clone, so CI and every colleague
silently graphed a smaller codebase and were told it succeeded.

`outside` is the other half of the same subject and the two must not be confused, so the split
is stated here where both are defined. **`directories` names paths INSIDE the project root**;
its keys are project-relative and every consumer reads them as the prefix of one, which is why
`normalise_dir_key` refuses a key that escapes rather than folding it. **`outside` names a
directory that is NOT inside the root**, by alias, and it is the only way anything beyond the
root is ever reached (ADR-031). Inside the root, discovery stays automatic and needs no entry
in either map; crossing the root is never implicit.
"""

import json
import os
import posixpath
import string
from typing import Any, Callable, Dict, List, Optional, Sequence, Tuple

# The containment rule is imported and never re-derived here (ADR-030). A directory key is a
# value *declared* in checked-in data, which is the question `escapes` answers — and the
# reason it, rather than one of the other three predicates, is what `normalise_dir_key` calls.
import containment
# The token a crossing is spelled with is edge vocabulary, so it belongs to the contract and
# not to the file reader — and one string written out twice is exactly how `IMPORT_SIGNALS`
# came to have three bodies. The direction is settings -> substrate -> containment and it must
# stay that way: `substrate` imports nothing first-party but `containment`, and a
# `substrate -> settings` edge would make the contract depend on the configuration file, which
# is the coupling ADR-018 exists to prevent.
#
# The name is imported rather than the module, because four functions below bind a *local*
# called `substrate` for the settings section of that name, and a module shadowed in four
# places is a trap laid for whoever edits one of them next.
#
# Not a re-export, and it carried a `# noqa: F401 — re-exported` saying it was: the name is
# used here, in `OutsideRoots.key_for`, so F401 could never have fired, and nothing anywhere
# reads `settings.OUTSIDE_PREFIX` — every other reader goes to `substrate`, which is where the
# comment above says the definition belongs.
from substrate import OUTSIDE_PREFIX

SETTINGS_DIRNAME = 'knowledge-base'
SETTINGS_FILENAME = 'settings.json'

# The machine-level default, answered once when the suite is installed and used by every
# project that has not decided for itself. `FREYA_HOME` overrides it, which is what lets the
# tests exercise this without writing into the real home directory — and what lets someone
# keep a per-checkout answer if they ever want one.
#
# Its own directory, not one belonging to an agent: this suite installs for more than one
# host and the answer is the same on all of them, so it must not live inside any single
# host's skills directory. Deliberately not inside the checkout either — `freya update`
# fast-forwards that tree, and configuration a `git pull` can clobber is not configuration.
GLOBAL_ENV_VAR = 'FREYA_HOME'
GLOBAL_DIRNAME = '.freya'

# What the machine-level file is allowed to say. Only preferences that mean the same thing in
# every repository: which parser to use, and how much detail to record.
#
# `directories` is deliberately excluded, and the reason matters. A global "docs is source"
# would apply to repositories nobody has looked at, and a global `node_modules: source` would
# be a 50,000-file graph on every project on the machine. Scope is a fact about *one* project;
# a parser preference is a fact about the person.
GLOBAL_KEYS = (('substrate', 'backend'), ('substrate', 'symbols'))

# What a project may say about one of its directories.
DIRECTORY_VERDICTS = ('source', 'exclude')

# Where a project declares a directory OUTSIDE its own root (ADR-031).
#
# A top-level section and not a third verdict on `directories`, and the reason is the key space
# rather than taste. That map's *keys* are project-relative paths, and every consumer reads
# them as the prefix of one: the scan roots are `project_dir / key.split('/')[0]`, the override
# lookups match prefixes, and so does `Exclusions._under`. A path outside the root has no such
# spelling — which is why `{"directories": {"../shared": "source"}}` did not extend the
# mechanism, it corrupted the graph (see `normalise_dir_key` below for the measurement).
# `_classify_directories` cannot produce a verdict for a directory it cannot reach by
# `project_dir.iterdir()` either, so an out-of-tree entry could never carry the `ai` tier the
# two-tier design in ADR-022 is built around.
#
# The alias, and never the path, is what reaches an answer. It is the same string in every
# clone, it carries no absolute path into an artifact, and it is what makes
# `outside:<alias>/<rel>` splittable on the first `/`.
OUTSIDE_SECTION = 'outside'

# What an alias may be spelled with. Deliberately narrow: no `/`, because the token splits on
# the first one; no `:`, because the token already carries one; no whitespace, because an alias
# that differs from another by a space is a typo nobody will see in a diff.
_ALIAS_CHARS = frozenset(string.ascii_letters + string.digits + '._-')

# `auto` means **defer**: to the machine-level default if one is set, and otherwise to the
# floor — the backend that is always installed.
#
# It deliberately does not go shopping. Scoring the installed backends against the repo and
# picking the widest meant that installing a binary anywhere on PATH silently changed the
# substrate, and therefore every blast radius, for every project on the machine at once
# (ADR-019 removed that behaviour after it had already shipped). A machine-level default is the
# opposite of that: somebody answered a question, once, on purpose.
#
# Naming a backend explicitly — including `homegrown` — is how a project opts *out* of the
# machine default. That is why "not set" and "set to homegrown" have to stay distinguishable.
BACKEND_AUTO = 'auto'

# Where a resolved backend came from. Carried so the caller can say so, and so the seeding in
# `seed_project_backend` knows whether there is anything to write down.
SOURCE_PROJECT = 'project'
SOURCE_GLOBAL = 'global'
SOURCE_DEFAULT = 'default'

DEFAULTS = {
    'substrate': {
        'backend': BACKEND_AUTO,
        # Off by default. Symbol refinement is genuinely useful and genuinely not free:
        # measured on this repository it turns 120 file-level edges into 698, over the same
        # 77 file pairs, because a test module calling one helper sixty times is sixty
        # distinct symbol pairs and one dependency. Nothing downstream reads them yet, so
        # switching it on for everybody would be paying the size now for a consumer that does
        # not exist. Spec §5 is explicit that file-level behaviour is the floor and symbols
        # only refine it.
        'symbols': False,
    },
    'directories': {},
    # Present so that `load()` type-checks the section and warns on a non-object, rather than
    # copying it through the forward-compatibility branch untouched. An older freya reading a
    # newer file still ignores it there and simply does not cross the root, which is the right
    # way for this to fail on a version that does not understand it.
    'outside': {},
}


def normalise_dir_key(name: Any) -> str:
    """A directory key as the graph spells it: POSIX, relative, no leading or trailing slash.

    Every form a person actually types has to land on the same key. The docs here and in
    SKILL.md write directories with a trailing slash throughout (`node_modules/`, `dist/`),
    Windows users type backslashes, and a hand-edited file picks up `./` and doubled slashes.
    Without folding them, `"docs/"` was a key nothing ever looked up: no error, no warning, an
    unchanged graph — and, worse, it still reached the contract as a live override, so the
    artifact claimed a scope the filter had not applied.
    Folding alone was not enough, and refusing only the two bare strings `.` and `..` was the
    gap. `''` is returned for anything that does not name a directory *inside* this project,
    because every consumer joins this key onto the project root or matches it as the prefix of
    a project-relative path — the scan roots are `project_dir / key.split('/')[0]`, and the
    override lookups and `Exclusions._under` compare prefixes. A key that escapes has no such
    reading, and the build does not fail on it: it succeeds, wrongly. Measured 2026-08-23 at
    `abd1de3`, a committed `{"directories": {"../shared": "source"}}` graphed the sibling tree
    — `../shared/secret.ts` a node, its exports read out of the file — and, because the scan
    root is the key's first component, `..` walked back into the project and gave every
    in-project file a second node under `../<checkout-name>/`. Nothing was printed and
    `validate_graph` returned clean.

    That last clause is the one with a shelf life, and it has already expired — which is why
    the measurement is pinned to a commit and not to "the shipped code". Back this refusal out
    today and the same fixture prints three `files[...]: not a project-relative path` errors,
    because `substrate.validate_graph` now checks that every key under `files` is
    project-relative (ADR-025). That is not a substitute for this and does not make it
    redundant: the message says so itself — "writing it anyway" — and by the time it runs,
    `secret.ts` has been opened and `SECRET` is already sitting in the artifact being audited.
    That check reads the graph; this one refuses the read. `D:/secrets` is the same hole on
    Windows: the drive survives the fold, and `PureWindowsPath('C:/proj') / 'D:'` is `D:` with
    the project root discarded.

    `containment.escapes` is the predicate, because a directory key is a value **declared** in
    checked-in data — judged in both path flavours so the host reading the file does not get
    to decide what a committed key means. It is applied to the *folded* text rather than to
    the text as written, which is the one way this differs from checking a locator: `a/../b`
    and `b` have to be one key (ADR-025), so the question is whether the key the consumers
    will actually join escapes, not whether a `..` appeared on the way to it. Refusing is all
    this does: naming a directory outside the root stays impossible rather than becoming a
    third verdict here, because the keys of `directories` are project-relative and every
    consumer reads them as the prefix of one.

    A leading `/` still folds rather than being refused, and so does a UNC-looking
    `\\\\server\\share`. SPEC-012 fixes `/docs/` as another spelling of `docs`, and rebasing an
    absolute-looking key onto the project is what that spelling promises. What comes back is a
    relative key naming either something under this project or nothing at all, and a key that
    matches nothing is a dead entry rather than an escape — refusing them would be the easy
    over-correction, and it would start telling projects their settings file is wrong.

    With one exception, which is a price and not an oversight. A folded key whose *first*
    component is a single character followed by `:` is a Windows drive to the flavour this
    rule must also judge in, so a POSIX project with a top-level directory literally named
    `a:b` — or `x:` — is told its key does not name a directory inside the project, when it
    does. Measured on this tree, that is the whole of it: the boundary is exactly one
    character, so `my:dir`, `docs:v2` and `2024:notes` all survive, and a colon anywhere but
    the first component (`docs/a:b`, `src/C:x`) survives too. Narrowing it means a second,
    POSIX-only containment rule living in this file against ADR-030's one body, bought by
    letting a committed key mean a directory on one leg of the CI matrix and a drive on the
    other — which is the exact thing `containment.escapes` exists to refuse. So the sentence
    above is qualified rather than withdrawn: this does tell one project its settings file is
    wrong, it tells it out loud and by name, and the entry beside it still takes effect.

    The cache goes through here too: `graph_ops._load_classifications` folds every key it read
    out of `classifications.json` with this function before folding the committed verdicts over
    them, so an escaping key that reached that file is refused on the same rule and by the same
    line, rather than by a second one somebody has to remember to keep in step.
    """
    text = str(name or '').replace('\\', '/').strip()
    if not text:
        return ''
    text = posixpath.normpath(text).strip('/')
    if text in ('', '.') or containment.escapes(text):
        return ''
    return text


class OutsideRoots:
    """The directories this project declared outside its own root, resolved once.

    One predicate — `key_for` — answering one question: may this candidate be crossed to, and
    what is the crossing called. Empty is the default and the common case; a project that
    declares nothing gets an instance that answers None to everything without touching the
    filesystem, which is what keeps the zero-config path free.

    The grant is **resolution, never traversal**. Nothing here walks, globs or reads a declared
    root. The most this can cause is `os.path.realpath` on a candidate some in-project file
    named, and — once the caller has a key — the `is_file()` plus one cached `listdir` of that
    file's own directory that the in-project resolver already performs. No content outside the
    project is ever read, and no file under a declared root ever becomes a `graph['files']`
    key. That is what lets `validate_graph`'s key rule stay unconditional, and it is the whole
    difference between this and SEC-008 with a declaration written on it.

    Fail-closed is structural rather than a rule somebody has to remember. A crossing is only
    ever spelled `outside:<alias>/<rel>`, never as an ordinary path, so a consumer that has not
    been taught about declarations cannot open one: the token has no drive, no leading slash
    and no `..`, so joining it onto any root is safe and names nothing that exists. It refuses;
    it does not read. Emitting the real `../packages/ui/src/Button.tsx` instead would have
    handed every untaught consumer a working path out of the project.
    """

    __slots__ = ('roots', 'refused')

    def __init__(self, roots: Sequence[Tuple[str, str, str]] = (),
                 refused: Sequence[Tuple[str, str, str]] = ()):
        #: (alias, path as written, resolved absolute path) for each root in force, ordered
        #: **most specific first** and not as the file happened to spell them. Two roots where
        #: one contains the other are both legal — `{"ui": "../packages/ui", "pkgs":
        #: "../packages"}` is an ordinary thing to write — and `key_for` returns on the first
        #: match, so without this the token a file is reported under was decided by JSON key
        #: order. That is not a theoretical instability: `write()` re-serialises this map with
        #: `sort_keys=True`, and `seed_project_backend` calls it on the first build of any
        #: project carrying a machine default, so freya alphabetised the aliases itself and
        #: changed every `outside:` token in the next graph with no code change at all.
        #:
        #: The longest resolved path is the most specific one, because a contained root is a
        #: prefix of its container plus at least one more component. The alias breaks ties, so
        #: two aliases naming the same directory still resolve the same way in every clone.
        self.roots = tuple(sorted(roots, key=lambda root: (-len(root[2]), root[0])))
        #: (alias, value as written, why) for each declaration that was turned away.
        self.refused = tuple(refused)

    def __bool__(self) -> bool:
        return bool(self.roots)

    def __repr__(self) -> str:
        return 'OutsideRoots(%s)' % ', '.join(
            ['%s=%r' % (alias, declared) for alias, declared, _ in self.roots]
            + ['%s=refused' % alias for alias, _, _ in self.refused])

    def key_for(self, candidate: Any) -> Optional[str]:
        """`outside:<alias>/<path under that root>` for a declared crossing, else None.

        `containment.within` and not one of its neighbours, because this is the security
        question: the answer decides whether a path outside the project is touched at all. Both
        sides go through `realpath`, so a symlink planted under a declared root that points
        somewhere else — back into the project, or at `/etc` — is not contained and the
        crossing is refused. A symlink is an *implicit* crossing, and a declaration never
        re-authorises one (SEC-008).

        The extra `realpath` for the relative spelling is paid deliberately rather than
        hoisted out of `within`: re-deriving the containment comparison here to save a syscall
        would be a second body of the rule (ADR-030), and this runs only for a candidate that
        is already known not to be in the project, which on any real repository is a handful of
        imports.

        A candidate that *is* the root resolves to the empty tail, `outside:<alias>/`. It never
        reaches an edge — the caller's next question is `_is_real_file`, and a directory is not
        one — but it keeps "split on the first `/`" true for every token this can produce.

        First match wins, and `__init__` is what makes "first" mean *most specific* rather than
        *first written*. Where two declared roots nest, the inner one names the file; the outer
        one is not consulted for anything the inner one already covers, which is why its
        `crossings` count can be zero while it is doing its job — see `_outside_report`.
        """
        for alias, _declared, resolved in self.roots:
            if not containment.within(resolved, candidate):
                continue
            rel = os.path.relpath(os.path.realpath(candidate), resolved)
            tail = '' if rel == os.curdir else rel.replace(os.sep, '/')
            return OUTSIDE_PREFIX + alias + '/' + tail
        return None

    def to_dict(self) -> Optional[Dict[str, Any]]:
        """The declarations as an artifact should record them, or None if there were none.

        `None` and not `{}`, so a repository that has never declared anything produces
        byte-identical output (ADR-029's absent-not-empty rule).

        The *resolved* absolute path is deliberately not carried. It is derivable from the
        graph's own project root and the declared value, and an absolute path written into a
        machine-readable artifact is a path off this machine the moment the artifact moves.

        Refusals are carried beside the roots in force for ADR-029's reason: each one also
        produces a warning, and stderr is dead skill-to-skill. A declaration that was thrown
        away is precisely the thing a reader of the artifact needs told.
        """
        if not self.roots and not self.refused:
            return None
        block = {}  # type: Dict[str, Any]
        if self.roots:
            block['declared'] = [{'alias': alias, 'path': declared}
                                 for alias, declared, _ in self.roots]
        if self.refused:
            block['refused'] = [{'alias': alias, 'path': declared, 'reason': why}
                                for alias, declared, why in self.refused]
        return block


#: What a value that is not project-relative is told. One string, because the two places that
#: can produce it — an anchored value, and a drive-relative tail after the `..` — are the same
#: mistake and reading two different sentences for it would suggest they were not.
_NOT_RELATIVE = ('is not a relative path — a declared root is written relative to the project '
                 'root, so that the same commit names the same directory in every clone')


def _outside_target(value: Any) -> Tuple[Optional[str], Optional[str]]:
    """`(relative path, None)` for a declarable value, or `(None, why not)`.

    The grammar of a declaration is deliberately small: *n* leading `..` components, then a
    tail that would itself be a legal `directories` key. That decomposition is what lets the
    existing predicates answer this without a fifth body of either — `containment.escapes`
    refuses `..` outright, which is the one thing a declaration must be *allowed*, so it is
    asked about the tail rather than about the value.

    Three refusals, in the order that gets each one the right sentence:

    * `~` first, and by name. Every `~` value would be refused anyway by the `up == 0` clause
      below — no home path starts with `../` — so this branch exists for the *message*. Without
      it a person who wrote `~/shared` is told their path is inside the project, which is the
      one answer guaranteed to send them looking in the wrong place. This file is committed and
      `~` names a different directory for every reader, which is the failure that is silent on
      every machine at once.
    * `containment.escapes` on the tail. This is also where **absoluteness** is judged, and
      that is not a coincidence: stripping leading `../` from an absolute value strips nothing,
      so an absolute path arrives at this line as its own tail. `is_anchored` was written into
      an earlier draft of this function beside it and measured redundant — every spelling it
      caught, `escapes` had already caught one line later with the same sentence.

      The predicate matters and `os.path.isabs` will not do, which is the 3.9/3.13 trap in a
      new place: `os.path.isabs('C:/shared')` is False on Linux and `ntpath.isabs('/opt/sdk')`
      is False on Windows from 3.13, so the host rule waves through one spelling on each leg
      of the CI matrix. `escapes` judges in both flavours, so a committed value means the same
      thing wherever it is read.
    * `up == 0` last: a value that never leaves the root is not a declaration at all, and it
      is sent to `directories`. That clause carries most of the refusals by count, which is
      worth knowing when reading the two above — they are there for the *reason* at least as
      often as for the verdict.

    A known boundary, the same one `normalise_dir_key` documents and priced the same way: a
    first component of one character then `:` is a drive to the flavour this must also judge
    in, so a POSIX project with a sibling directory literally named `x:` cannot declare it. On
    the other side of the same boundary, `C:shared` — drive-relative, no root — is caught by
    `escapes` and gets the relativeness sentence, which is what a Windows reader needs.

    Both refusals are portability, not security, and the limit belongs in plain sight:
    refusing absolutes is **not** a bound on where a declaration can reach. `../../../../etc`
    is expressible and resolves exactly where it reads. What the relative form buys is that the
    destination is legible in review — `../packages/ui` beside a checkout is a sentence anyone
    can check — and that the same commit means the same thing in every clone. The bound on what
    a declaration *does* is the resolution-only grant, not this.
    """
    if not isinstance(value, str) or not value.strip():
        return None, 'is not a directory path'
    text = value.replace('\\', '/').strip()
    if text.startswith('~'):
        return None, ('starts with ~, which names a different directory for every user; this '
                      'file is committed, so write the path relative to the project')
    text = posixpath.normpath(text)
    up = 0
    while text == '..' or text.startswith('../'):
        up += 1
        text = '' if text == '..' else text[3:]
    if containment.escapes(text):
        return None, _NOT_RELATIVE
    if not up:
        return None, ('names a directory inside this project; a scope inside the root belongs '
                      'in "directories", and inside the root nothing needs declaring at all')
    return posixpath.join(*(['..'] * up + ([text] if text else []))), None


def parse_outside(raw: Any, project_dir: str,
                  path: str) -> Tuple[OutsideRoots, List[str]]:
    """Read the `outside` section. Returns `(OutsideRoots, warnings)`.

    A bad entry is a warning and a skip, never a crash and never a silent drop — the same shape
    as every other malformation in this file, and for the reason its opening paragraph gives: a
    build must not fail because configuration is wrong, and a project whose committed file
    carries a stale root would otherwise stop being able to build at all. Refusing one entry
    loses nothing that worked, because a declaration that cannot be resolved never reached
    anything in the first place.

    Every refusal carries the value it turned away and why. A declaration is the one thing in
    this file that a person writes expecting the toolkit to look somewhere new; a silent
    no-effect entry there is worse than a dead directory key, because nothing else in the
    output would ever hint at it.

    The first two branches guard **direct callers only**, and that is worth saying because they
    look like the file-reading path and are not. `DEFAULTS` carries `'outside': {}`, so `load()`
    type-checks this section itself and substitutes the default with its own sentence ("using
    defaults for it") before `Settings` ever reaches here; a `null` or a list in the committed
    file is caught there and never arrives. They are kept rather than deleted because this is a
    module-level parser with a public name and a caller that hands it a list should get a
    sentence rather than an `AttributeError` — but they are pinned by a test that calls this
    function directly, because a branch no test can reach is how the next reader concludes the
    live ones are optional too.
    """
    if raw is None:
        return OutsideRoots(), []
    if not isinstance(raw, dict):
        return OutsideRoots(), ['%s: "%s" must be an object; ignoring it'
                                % (path, OUTSIDE_SECTION)]

    roots = []  # type: List[Tuple[str, str, str]]
    refused = []  # type: List[Tuple[str, str, str]]
    warnings = []  # type: List[str]
    taken = set()  # type: set

    def turn_away(alias: Any, value: Any, why: str) -> None:
        shown = alias if isinstance(alias, str) else repr(alias)
        refused.append((shown, value if isinstance(value, str) else repr(value), why))
        warnings.append('%s: %s.%s: %r %s; ignored'
                        % (path, OUTSIDE_SECTION, shown, value, why))

    for alias, value in raw.items():
        name = alias.strip() if isinstance(alias, str) else ''
        if not name or not set(name) <= _ALIAS_CHARS:
            turn_away(alias, value,
                      'is not usable as an alias — an alias is one or more letters, digits, '
                      '".", "_" or "-", and it is the name a crossing is reported under')
            continue
        target, why = _outside_target(value)
        if why:
            turn_away(name, value, why)
            continue
        # The one call in this loop that raises instead of answering. A value carrying a NUL
        # — which JSON can spell and no filesystem can address — reaches `lstat` and raises
        # `ValueError`, and since `Settings.__init__` parses this section unconditionally the
        # traceback took out `--build`, `--update` and every read-only query with it: the
        # crash the paragraph above says configuration must never cause. A lone surrogate
        # (`"\ud800"`, also spellable in JSON) raises `UnicodeEncodeError`, a `ValueError`
        # too, so one clause covers both. `isdir` and `containment.within` answer False for
        # these rather than raising, which is why this was the only line that had to change.
        try:
            resolved = os.path.realpath(os.path.join(project_dir, target))
        except ValueError:
            turn_away(name, value, 'is not a path this system can address')
            continue
        if not os.path.isdir(resolved):
            turn_away(name, value, 'does not name a directory that exists')
            continue
        # `within` on both sides, and in this order. The first catches a root that resolves
        # back inside the project — through `..` and in again, or through a symlink — which
        # would give one file two spellings, `src/a.ts` and `outside:x/a.ts`, and break the
        # key space ADR-025 depends on from the other direction. The second catches `..` and
        # `../..`, which name an ancestor: an ancestor is not a scope, and declaring one would
        # quietly re-admit the whole tree the project sits in.
        if containment.within(project_dir, resolved):
            turn_away(name, value,
                      'resolves inside this project; a scope inside the root belongs in '
                      '"directories"')
            continue
        if containment.within(resolved, project_dir):
            turn_away(name, value,
                      'contains this project, which is not a scope — point freya at that '
                      'directory instead if it is the real project root')
            continue
        # Two entries cannot share an alias. JSON cannot spell a literal duplicate key, so this
        # only ever fires on two spellings that `strip()` folds together — `"ui"` and `" ui "` —
        # which is exactly the typo `_ALIAS_CHARS` refuses whitespace to keep out of a diff.
        # Left unchecked it was not merely cosmetic: both entries reached `declared`, `key_for`
        # answered from whichever sorted first, and `_outside_report` counted the crossing once
        # and stamped it on both, so the artifact reported two crossings against a total of one.
        if name in taken:
            turn_away(name, value,
                      'repeats an alias already declared in this section; an alias is the name '
                      'a crossing is reported under, so two roots cannot share one')
            continue
        # Honoured, and said out loud. A declared root reached through a symlink is not the
        # implicit crossing SEC-008 refuses — the path was declared, and `key_for` still refuses
        # a symlink *under* the root that leaves it. But it is the one case where the committed
        # text is not the whole answer, and this record's argument for refusing absolute paths
        # is that a relative one is legible in review. `../packages/ui` is only a sentence
        # anyone can check while every component of it is what it looks like, so when one is
        # not, the run says where the declaration actually landed.
        #
        # Compared against the project's own *realpath*, deliberately. Measuring from the
        # unresolved `project_dir` would fire on every macOS checkout under `/tmp` and every
        # repository reached through a symlinked home, which is a warning nobody would read
        # twice. What is left is divergence contributed by the declaration itself.
        lexical = os.path.normpath(os.path.join(os.path.realpath(project_dir), target))
        if os.path.normcase(lexical) != os.path.normcase(resolved):
            warnings.append(
                '%s: %s.%s: %r reaches %s through a symlink; the declaration is honoured, but '
                'the committed path is not where the build looked'
                % (path, OUTSIDE_SECTION, name, value, _relative_to(resolved, project_dir)))
        taken.add(name)
        roots.append((name, value, resolved))

    return OutsideRoots(roots, refused), warnings


def _relative_to(target: str, project_dir: str) -> str:
    """`target` spelled from the project root, or absolutely when it has no such spelling.

    Only ever used in a stderr sentence, so the fallback is a real answer rather than a
    refusal: on Windows a declared root on another drive has no relative spelling at all
    (`ntpath.relpath` raises), and naming the absolute path is more use to the reader than
    saying nothing. An absolute path in an *artifact* is the thing `OutsideRoots.to_dict`
    refuses, and this is not one.
    """
    try:
        return os.path.relpath(target, os.path.realpath(project_dir)).replace(os.sep, '/')
    except ValueError:
        return target


def settings_path(project_dir: str) -> str:
    return os.path.join(project_dir, SETTINGS_DIRNAME, SETTINGS_FILENAME)


def global_home() -> str:
    """The directory holding the machine-level answer."""
    override = os.environ.get(GLOBAL_ENV_VAR)
    if override and override.strip():
        return override.strip()
    return os.path.join(os.path.expanduser('~'), GLOBAL_DIRNAME)


def global_settings_path() -> str:
    return os.path.join(global_home(), SETTINGS_FILENAME)


def _dig(data: Any, path: Sequence[str]) -> Any:
    for key in path:
        if not isinstance(data, dict):
            return None
        data = data.get(key)
    return data


def load_global() -> Tuple[Dict[str, Any], List[str]]:
    """The machine-level preferences, filtered to what may legitimately be global.

    Returns `(data, warnings)`. Unreadable, malformed or absent all yield `({}, ...)`: a
    machine-level file must never be able to stop a build in a project that has nothing to do
    with it, and the whole point of the floor is that everything works before anyone
    configures anything.

    Keys outside `GLOBAL_KEYS` are dropped **and reported**, rather than silently honoured.
    Somebody who writes `directories` in here has a reasonable expectation it does something,
    and the answer — that scope belongs to a project because it is a fact about that project —
    is worth one line of stderr.
    """
    path = global_settings_path()
    if not os.path.exists(path):
        return {}, []
    try:
        with open(path, encoding='utf-8') as handle:
            raw = json.load(handle)
    except OSError as exc:
        return {}, ['%s: could not be read (%s); ignoring the machine-level default'
                    % (path, exc.__class__.__name__)]
    except ValueError as exc:
        return {}, ['%s: is not valid JSON (%s); ignoring the machine-level default'
                    % (path, exc)]
    if not isinstance(raw, dict):
        return {}, ['%s: top level must be an object; ignoring it' % path]

    allowed = {}  # type: Dict[str, Any]
    warnings = []  # type: List[str]
    for keys in GLOBAL_KEYS:
        value = _dig(raw, keys)
        if value is None:
            continue
        node = allowed
        for key in keys[:-1]:
            node = node.setdefault(key, {})
        node[keys[-1]] = value

    for section, value in raw.items():
        wanted = {k[0] for k in GLOBAL_KEYS}
        if section not in wanted:
            warnings.append(
                '%s: %r is not a machine-level setting and was ignored — only %s apply '
                'everywhere; anything about *this* project belongs in its own settings.json'
                % (path, section, ', '.join('.'.join(k) for k in GLOBAL_KEYS)))
            continue
        if not isinstance(value, dict):
            warnings.append('%s: "%s" must be an object; ignoring it' % (path, section))
            continue
        for key in value:
            if (section, key) not in GLOBAL_KEYS:
                warnings.append(
                    '%s: %s.%s is not a machine-level setting and was ignored'
                    % (path, section, key))

    # The same audibility the project file has. A wrong-typed machine default was dropped in
    # complete silence — no seeding, no message, the floor used — which is precisely how
    # somebody ends up convinced their machine is set to something it is not.
    backend = _dig(allowed, ('substrate', 'backend'))
    if backend is not None and _clean_backend(backend) is None:
        warnings.append('%s: substrate.backend: %r is not a backend name; ignoring it'
                        % (path, backend))
    symbols = _dig(allowed, ('substrate', 'symbols'))
    if symbols is not None and not isinstance(symbols, bool):
        warnings.append('%s: substrate.symbols: %r is not true or false; ignoring it'
                        % (path, symbols))
    return allowed, warnings


class Settings:
    """Project settings, with defaults for everything.

    `warnings` carries anything wrong with the file. They are collected rather than raised so a
    typo degrades to the default *visibly*, instead of either crashing the build or being
    silently ignored — the latter being how a project ends up convinced it is using a backend
    it is not.
    """

    __slots__ = ('data', 'path', 'present', 'warnings', 'directories', 'outside',
                 'global_data', 'file_backend', 'file_symbols')

    def __init__(self, data: Dict[str, Any], path: str, present: bool,
                 warnings: Optional[List[str]] = None,
                 global_data: Optional[Dict[str, Any]] = None,
                 file_backend: Optional[str] = None,
                 file_symbols: Optional[bool] = None):
        self.data = data
        self.path = path
        self.present = present
        self.global_data = global_data or {}
        # What the file on disk literally said, or None where it said nothing. `data` cannot
        # answer this: it is merged over `DEFAULTS`, which supplies `auto` and `False`, so
        # "absent" and "explicitly chosen" look identical there — and for `backend` that is
        # the difference between a project nobody has answered for and one that asked to keep
        # following the machine, while for `symbols` it decides whether an explicit `false`
        # can turn the machine default back off.
        self.file_backend = file_backend
        self.file_symbols = file_symbols
        self.warnings = warnings or []
        # Parsed here, eagerly, and not behind a property. It used to be one, and the
        # property was what *appended* the warnings — so every caller that read `.warnings`
        # before touching `.directories` got an empty list and printed nothing. Both of them
        # did, which meant a typo'd verdict was dropped in complete silence.
        self.directories = self._parse_directories()
        # Eagerly, and for the same reason as the line above: a lazily parsed field appends
        # its own warnings, so every caller that reads `.warnings` before touching the field
        # prints nothing and a refused declaration vanishes. That has already happened once in
        # this class; repeating it in the one field whose whole purpose is to make a crossing
        # visible would be the easiest possible way to ship a silent one.
        self.outside, outside_warnings = parse_outside(
            self.data.get(OUTSIDE_SECTION), self._project_dir(), self.path)
        self.warnings.extend(outside_warnings)
        self._check_substrate()

    def _project_dir(self) -> str:
        """This project's root, derived from the settings path rather than passed in.

        `settings_path` is `<project>/knowledge-base/settings.json`, so two `dirname`s get back
        what `load()` was handed. Derived and not a new constructor parameter, because every
        existing `Settings(...)` call site — including the tests that build one by hand — would
        otherwise have to grow an argument to keep working.
        """
        return os.path.dirname(os.path.dirname(self.path))

    def _check_substrate(self) -> None:
        """Warn about a `substrate` value of the wrong type, rather than dropping it.

        Every other malformation in this file is reported — bad JSON, a section that is not
        an object, a directory verdict that is not `source`/`exclude`. A wrong-typed
        `backend` or `symbols` was the exception: `{"backend": 42}` or `{"symbols": "true"}`
        fell through to the default in complete silence, which is how a project ends up
        convinced it has opted into a backend it is not running. The accessors below are
        deliberately still forgiving; this only makes the fallback audible.
        """
        substrate = self.data.get('substrate')
        if not isinstance(substrate, dict):
            return
        backend = substrate.get('backend')
        if backend is not None and (not isinstance(backend, str) or not backend.strip()):
            self.warnings.append(
                '%s: substrate.backend: %r is not a backend name; using %r'
                % (self.path, backend, BACKEND_AUTO))
        symbols = substrate.get('symbols')
        if symbols is not None and not isinstance(symbols, bool):
            self.warnings.append(
                '%s: substrate.symbols: %r is not true or false; symbols stay off'
                % (self.path, symbols))

    @property
    def backend(self) -> str:
        """The backend to use here: the project's answer, the machine's, or `auto`.

        `auto` from the project means *defer*, so the machine-level default answers it. An
        explicit name — including `homegrown` — is the project deciding for itself, which is
        how one repository opts out of a machine default without changing it for the others.
        """
        name = self.declared_backend
        if name is not None:
            return name
        name = _clean_backend(_dig(self.global_data, ('substrate', 'backend')))
        return name or BACKEND_AUTO

    @property
    def declared_backend(self) -> Optional[str]:
        """The backend *this project* decided on, or None if it defers.

        `None` and `'homegrown'` are different answers and must stay that way: the first
        means nobody has decided, and the second means somebody decided against the machine
        default.
        """
        return None if self.file_backend in (None, BACKEND_AUTO) else self.file_backend

    @property
    def decided(self) -> bool:
        """Has this project answered the backend question at all, even with `auto`?

        `seed_project_backend` writes only when this is False. An explicit `auto` is an
        answer — "keep following whatever the machine says" — and overwriting it with the
        concrete name would silently unsubscribe the project from the thing it asked for.
        """
        return self.file_backend is not None

    @property
    def backend_source(self) -> str:
        """Which layer supplied `backend`. Carried so a run can say so out loud."""
        if self.declared_backend is not None:
            return SOURCE_PROJECT
        if _clean_backend(_dig(self.global_data, ('substrate', 'backend'))):
            return SOURCE_GLOBAL
        return SOURCE_DEFAULT

    def _parse_directories(self) -> Dict[str, str]:
        """Committed directory verdicts, keyed the way the graph keys paths.

        These outrank the built-in exclusion lists. They live here rather than in
        `classifications.json` because that file is gitignored regenerable cache: an override
        recorded there worked for whoever typed it and disappeared on clone, so CI and every
        colleague graphed a smaller codebase and were told the build succeeded.

        A bad value is a warning and a skip, never a crash and never a silent drop. Getting no
        graph because of a typo, or getting a quietly different one, are both worse than being
        told which key was wrong.

        That includes a key that escapes the project (`../shared`, `D:/secrets`), which
        `normalise_dir_key` began refusing on 2026-08-23. A skip and not a raise, deliberately:
        this module's contract is that a malformed settings file degrades to defaults
        *visibly*, and a project whose committed file already carries such a key would
        otherwise stop being able to build at all — an escaping entry never widened scope
        correctly in the first place, so refusing just that entry loses nothing that worked,
        while raising would take away the graph as well, over an entry that was never doing
        anything. The same shape as every other malformation in this file, and the same shape
        as `_check_substrate`.

        It also covers the one key shape `normalise_dir_key` over-refuses — a top-level POSIX
        directory named `a:b`, a drive in the flavour that rule must also judge in — and that
        is what makes the over-refusal affordable: the entry is dropped by name, in a message
        carrying the file it came from, rather than quietly.
        """
        declared = self.data.get('directories')
        if not isinstance(declared, dict):
            return {}
        verdicts = {}  # type: Dict[str, str]
        for name, verdict in declared.items():
            key = normalise_dir_key(name)
            if not key:
                self.warnings.append(
                    '%s: directories: %r does not name a directory inside this project; '
                    'ignored. A directory outside the project root is declared under "%s", '
                    'by alias (ADR-031)' % (self.path, name, OUTSIDE_SECTION))
                continue
            if verdict not in DIRECTORY_VERDICTS:
                self.warnings.append(
                    '%s: directories.%s: %r is not one of %s; ignored'
                    % (self.path, key, verdict, ', '.join(DIRECTORY_VERDICTS)))
                continue
            verdicts[key] = verdict
        return verdicts

    @property
    def symbols(self) -> bool:
        """Should edges record the symbols they leave and arrive at, where the backend knows?

        A backend that cannot see symbols is unaffected — this asks for refinement, it does
        not require it, so turning it on never makes a graph worse or a build fail.
        """
        if isinstance(self.file_symbols, bool):
            return self.file_symbols
        return _dig(self.global_data, ('substrate', 'symbols')) is True

    def to_dict(self) -> Dict[str, Any]:
        return json.loads(json.dumps(self.data))  # deep copy, plain types only

    def __repr__(self) -> str:
        return 'Settings(backend=%r, symbols=%s, directories=%d, present=%s, warnings=%d)' % (
            self.backend, self.symbols, len(self.directories), self.present,
            len(self.warnings))


def load(project_dir: str) -> Settings:
    """Read this project's settings, layered over the machine-level default."""
    path = settings_path(project_dir)
    global_data, global_warnings = load_global()

    def fallback(warnings):
        return Settings(_defaults(), path, present=os.path.exists(path),
                        warnings=global_warnings + warnings, global_data=global_data)

    if not os.path.exists(path):
        return Settings(_defaults(), path, present=False, warnings=list(global_warnings),
                        global_data=global_data)

    try:
        with open(path, encoding='utf-8') as handle:
            raw = json.load(handle)
    except OSError as exc:
        return fallback(['%s: could not be read (%s); using defaults'
                         % (path, exc.__class__.__name__)])
    except ValueError as exc:
        return fallback(['%s: is not valid JSON (%s); using defaults' % (path, exc)])

    if not isinstance(raw, dict):
        return fallback(['%s: top level must be an object; using defaults' % path])

    warnings = list(global_warnings)
    merged = _defaults()
    for section, value in raw.items():
        if section not in DEFAULTS:
            # Not an error. Forward compatibility: a newer freya writes a section this one does
            # not know, and an older one must not discard or reject it.
            merged[section] = value
            continue
        if not isinstance(value, dict):
            warnings.append('%s: "%s" must be an object; using defaults for it'
                            % (path, section))
            continue
        merged[section].update(value)

    raw_symbols = _dig(raw, ('substrate', 'symbols'))
    return Settings(merged, path, present=True, warnings=warnings,
                    global_data=global_data,
                    file_backend=_clean_backend(_dig(raw, ('substrate', 'backend'))),
                    file_symbols=raw_symbols if isinstance(raw_symbols, bool) else None)


def write(project_dir: str, settings: Dict[str, Any]) -> str:
    """Write this project's settings, creating `knowledge-base/` if needed.

    Called when somebody answers the question — `--use`, or the seeding below carrying a
    machine-level answer into a project that had none. Never called to record a default
    nobody chose: a committed file saying `homegrown` because a headless run needed
    *something* is a decision attributed to a person who never made it.
    """
    path = settings_path(project_dir)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, 'w', encoding='utf-8') as handle:
        json.dump(settings, handle, indent=2, sort_keys=True)
        handle.write('\n')
    return path


def write_global(data: Dict[str, Any]) -> str:
    """Write the machine-level default, creating `~/.freya/` if needed."""
    path = global_settings_path()
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, 'w', encoding='utf-8') as handle:
        json.dump(data, handle, indent=2, sort_keys=True)
        handle.write('\n')
    return path


def set_backend(name: str, project_dir: Optional[str] = None,
                scope: str = SOURCE_PROJECT) -> str:
    """Record a backend choice. Returns the path written.

    Merges rather than replaces, so setting a backend never discards the directory verdicts
    or anything a newer version wrote alongside them.
    """
    if scope == SOURCE_GLOBAL and name == BACKEND_AUTO:
        # At machine level `auto` means "no machine default", so recording it as an answer is
        # a contradiction — and a damaging one: `already_answered()` counted the string as an
        # answer while `seed_project_backend` correctly skipped it, so `--use auto --global`
        # left no default in effect *and* permanently suppressed the install-time question,
        # under a success message claiming the opposite. It clears the setting instead, which
        # is also the only way to un-answer that question.
        return clear_global_backend()

    path = global_settings_path() if scope == SOURCE_GLOBAL else settings_path(str(project_dir))
    # The file as written, not as *interpreted*. `load_global()` filters to `GLOBAL_KEYS`, so
    # merging into its result and writing that back deleted every other key in the machine
    # file — including a forward-compatible section a newer freya had put there. Reading the
    # raw file is the only way this stays a merge rather than a replacement.
    data = _read_object(path)
    substrate = data.get('substrate')
    data['substrate'] = substrate if isinstance(substrate, dict) else {}
    data['substrate']['backend'] = name
    return write_global(data) if scope == SOURCE_GLOBAL else write(str(project_dir), data)


def clear_global_backend() -> str:
    """Remove the machine-level backend, leaving everything else in the file. Returns the path."""
    path = global_settings_path()
    data = _read_object(path)
    substrate = data.get('substrate')
    if isinstance(substrate, dict):
        substrate.pop('backend', None)
        if not substrate:
            data.pop('substrate', None)
    return write_global(data)


def _read_object(path: str) -> Dict[str, Any]:
    """The JSON object at `path`, or `{}` if there is nothing there.

    Raises rather than returning `{}` for a file that exists and is not a readable object. A
    settings file is hand-editable and committed, so overwriting one we could not understand
    would throw away work — and "valid JSON but not an object" is exactly the case that used
    to slip through the parse check and get silently replaced.
    """
    if not os.path.exists(path):
        return {}
    try:
        with open(path, encoding='utf-8') as handle:
            loaded = json.load(handle)
    except (OSError, ValueError):
        raise ValueError('%s exists and is not readable JSON; fix or remove it first' % path)
    if not isinstance(loaded, dict):
        raise ValueError('%s exists and is not a JSON object; fix or remove it first' % path)
    return loaded


def seed_project_backend(project_dir: str,
                         is_known: Optional[Callable[[str], bool]] = None) -> Optional[str]:
    """Carry the machine-level answer into a project that has not answered. Returns the path.

    This is what makes a machine-level default safe to have. Left implicit, the same commit
    would graph differently on a machine with the default and one without — and integration
    behaviours' static fingerprints come from the code-graph closure into `behavior.json`,
    which is committed, so the divergence would arrive as a diff that reads like behaviour
    drift.

    Writing it down makes the repository self-describing: a colleague who clones it, and CI,
    resolve the same backend without having to share anyone's machine configuration. That is
    the same property ADR-019 was written for.

    `symbols` rides along when the machine sets it, for the same reason and with more force:
    it changes graph *content* several-fold, so a machine-level `symbols: true` left implicit
    is the same commit producing a different graph on two laptops.

    `is_known` is an optional predicate the caller supplies to validate the name. This module
    cannot check the registry itself — `backends` imports *this*, so reaching the other way
    would be a cycle — and a typo in a hand-edited machine file must not be copied into a
    project's committed settings, where it becomes permanent and per-repository.

    None when there is nothing to do — no machine default, or the project has already
    answered (including with an explicit `auto`, which is an answer meaning "keep following
    the machine").
    """
    conf = load(project_dir)

    # The two keys are considered separately. Returning early on `conf.decided` meant the
    # `symbols` carry could only ever fire on a project that had never chosen a backend — and
    # the seeding write itself made the project decided, so that window closed permanently on
    # its own first use. A machine that turns `symbols` on afterwards would never reach any
    # project again, leaving the divergence in the one setting that changes what is *in* the
    # graph rather than which parser produced it.
    pending = {}  # type: Dict[str, Any]

    if not conf.decided:
        name = _clean_backend(_dig(conf.global_data, ('substrate', 'backend')))
        if name and name != BACKEND_AUTO and (is_known is None or is_known(name)):
            pending['backend'] = name

    if conf.file_symbols is None:
        symbols = _dig(conf.global_data, ('substrate', 'symbols'))
        if isinstance(symbols, bool):
            pending['symbols'] = symbols

    if not pending:
        return None

    path = settings_path(project_dir)
    data = _read_object(path)
    substrate = data.get('substrate')
    data['substrate'] = substrate if isinstance(substrate, dict) else {}
    data['substrate'].update(pending)
    return write(project_dir, data)


def _clean_backend(value: Any) -> Optional[str]:
    """A backend name as written, or None if the value is not one."""
    if not isinstance(value, str) or not value.strip():
        return None
    return value.strip()


def _defaults() -> Dict[str, Any]:
    return json.loads(json.dumps(DEFAULTS))
