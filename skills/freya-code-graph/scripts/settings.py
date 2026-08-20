#!/usr/bin/env python3
"""Per-project freya settings — `knowledge-base/settings.json`.

The toolkit had nowhere to record a project-level choice. Directory classifications lived in
`knowledge-base/.graph/classifications.json`, which is gitignored regenerable cache: fine for a
derived verdict, wrong for a decision. Anything stored there is lost on `--clear` and never
reaches a fresh clone, so every checkout would re-decide.

`knowledge-base/` is where this belongs (CD-15). It already exists wherever freya runs, its name
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
      }
    }

`directories` is where a project argues with the built-in exclusion lists. It landed here on
2026-08-20 rather than in `classifications.json`, which is where the override was first put —
and which is the mistake this module's second paragraph was already written to prevent. An
override survived on the machine that made it and vanished on clone, so CI and every colleague
silently graphed a smaller codebase and were told it succeeded.
"""

import json
import os
import posixpath
from typing import Any, Callable, Dict, List, Optional, Sequence, Tuple

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

# `auto` means **defer**: to the machine-level default if one is set, and otherwise to the
# floor — the backend that is always installed.
#
# It deliberately does not go shopping. Scoring the installed backends against the repo and
# picking the widest meant that installing a binary anywhere on PATH silently changed the
# substrate, and therefore every blast radius, for every project on the machine at once
# (CD-23 removed that behaviour after it had already shipped). A machine-level default is the
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
}


def normalise_dir_key(name: Any) -> str:
    """A directory key as the graph spells it: POSIX, no leading or trailing slash.

    Every form a person actually types has to land on the same key. The docs here and in
    SKILL.md write directories with a trailing slash throughout (`node_modules/`, `dist/`),
    Windows users type backslashes, and a hand-edited file picks up `./` and doubled slashes.
    Without folding them, `"docs/"` was a key nothing ever looked up: no error, no warning, an
    unchanged graph — and, worse, it still reached the contract as a live override, so the
    artifact claimed a scope the filter had not applied.
    """
    text = str(name or '').replace('\\', '/').strip()
    if not text:
        return ''
    text = posixpath.normpath(text).strip('/')
    return '' if text in ('.', '..') else text


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

    __slots__ = ('data', 'path', 'present', 'warnings', 'directories',
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
        self._check_substrate()

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
        """
        declared = self.data.get('directories')
        if not isinstance(declared, dict):
            return {}
        verdicts = {}  # type: Dict[str, str]
        for name, verdict in declared.items():
            key = normalise_dir_key(name)
            if not key:
                self.warnings.append('%s: directories: %r is not a directory path; ignored'
                                     % (self.path, name))
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
    the same property CD-15 was written for.

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
    if conf.decided:
        return None
    name = _clean_backend(_dig(conf.global_data, ('substrate', 'backend')))
    if not name or name == BACKEND_AUTO:
        return None
    if is_known is not None and not is_known(name):
        return None

    path = settings_path(project_dir)
    data = _read_object(path)
    substrate = data.get('substrate')
    data['substrate'] = substrate if isinstance(substrate, dict) else {}
    data['substrate']['backend'] = name
    symbols = _dig(conf.global_data, ('substrate', 'symbols'))
    if isinstance(symbols, bool) and conf.file_symbols is None:
        data['substrate']['symbols'] = symbols
    return write(project_dir, data)


def _clean_backend(value: Any) -> Optional[str]:
    """A backend name as written, or None if the value is not one."""
    if not isinstance(value, str) or not value.strip():
        return None
    return value.strip()


def _defaults() -> Dict[str, Any]:
    return json.loads(json.dumps(DEFAULTS))
