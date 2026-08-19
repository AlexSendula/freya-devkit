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
        "backend": "auto"          // auto | homegrown | <name of an installed backend>
      }
    }
"""

import json
import os
from typing import Any, Dict, List, Optional

SETTINGS_DIRNAME = 'knowledge-base'
SETTINGS_FILENAME = 'settings.json'

# `auto` is the default and means: prefer the backend that can see the most of this project,
# fall back to the one that is always installed. Resolved at selection time, not here — this
# module reads a file, it does not know which backends exist.
BACKEND_AUTO = 'auto'

DEFAULTS = {
    'substrate': {
        'backend': BACKEND_AUTO,
    },
}


def settings_path(project_dir: str) -> str:
    return os.path.join(project_dir, SETTINGS_DIRNAME, SETTINGS_FILENAME)


class Settings:
    """Project settings, with defaults for everything.

    `warnings` carries anything wrong with the file. They are collected rather than raised so a
    typo degrades to the default *visibly*, instead of either crashing the build or being
    silently ignored — the latter being how a project ends up convinced it is using a backend
    it is not.
    """

    __slots__ = ('data', 'path', 'present', 'warnings')

    def __init__(self, data: Dict[str, Any], path: str, present: bool,
                 warnings: Optional[List[str]] = None):
        self.data = data
        self.path = path
        self.present = present
        self.warnings = warnings or []

    @property
    def backend(self) -> str:
        """The configured backend name, or `auto`."""
        substrate = self.data.get('substrate')
        if not isinstance(substrate, dict):
            return BACKEND_AUTO
        name = substrate.get('backend')
        if not isinstance(name, str) or not name.strip():
            return BACKEND_AUTO
        return name.strip()

    def to_dict(self) -> Dict[str, Any]:
        return json.loads(json.dumps(self.data))  # deep copy, plain types only

    def __repr__(self) -> str:
        return 'Settings(backend=%r, present=%s, warnings=%d)' % (
            self.backend, self.present, len(self.warnings))


def load(project_dir: str) -> Settings:
    """Read `<project>/knowledge-base/settings.json`, falling back to defaults."""
    path = settings_path(project_dir)
    if not os.path.exists(path):
        return Settings(_defaults(), path, present=False)

    try:
        with open(path, encoding='utf-8') as handle:
            raw = json.load(handle)
    except OSError as exc:
        return Settings(_defaults(), path, present=True,
                        warnings=['%s: could not be read (%s); using defaults'
                                  % (path, exc.__class__.__name__)])
    except ValueError as exc:
        return Settings(_defaults(), path, present=True,
                        warnings=['%s: is not valid JSON (%s); using defaults' % (path, exc)])

    if not isinstance(raw, dict):
        return Settings(_defaults(), path, present=True,
                        warnings=['%s: top level must be an object; using defaults' % path])

    warnings = []  # type: List[str]
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

    return Settings(merged, path, present=True, warnings=warnings)


def write(project_dir: str, settings: Dict[str, Any]) -> str:
    """Write settings, creating `knowledge-base/` if needed. Returns the path.

    Never called during a build. This file is committed and belongs to the engineer, so it is
    created when they ask for it, not as a side effect of running a graph.
    """
    path = settings_path(project_dir)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, 'w', encoding='utf-8') as handle:
        json.dump(settings, handle, indent=2, sort_keys=True)
        handle.write('\n')
    return path


def _defaults() -> Dict[str, Any]:
    return json.loads(json.dumps(DEFAULTS))
