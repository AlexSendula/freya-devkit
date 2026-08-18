#!/bin/sh
# Bootstrap for the freya-devkit installer.
#
# All logic lives in bin/installer.py — this only finds a Python 3 and
# delegates, because before installation `freya` is not on PATH.
set -eu

here=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd -P)

# 3.9 is the real floor, not "any Python 3": installer.py and updater.py open
# with `from __future__ import annotations` (3.7+), and search_specs.py uses
# PEP 585 generics in evaluated annotations (3.9+). Gating on the major
# version alone let an older interpreter through, and the install then died
# with a SyntaxError from a file the user never named. Keep in step with
# freya_cli.MIN_PYTHON.
for py in python3 python; do
    if command -v "$py" >/dev/null 2>&1 && "$py" -c 'import sys; sys.exit(sys.version_info < (3, 9))'; then
        exec "$py" "$here/bin/installer.py" "$@"
    fi
done

echo "install.sh: no Python 3.9+ found on PATH." >&2
exit 1
