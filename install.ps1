# Bootstrap for the freya-devkit installer on Windows.
#
# All logic lives in bin/installer.py — this only finds a Python and
# delegates. Symlinks on Windows need Developer Mode or an elevated shell; the
# installer probes for that up front and copies instead when it is refused, so
# --copy is a way to force that mode rather than something you must know to
# pass. Either way the launcher is written as a shim plus a freya.cmd, because
# an extensionless file is not executable on this platform at all.
$ErrorActionPreference = 'Stop'
$here = Split-Path -Parent $MyInvocation.MyCommand.Path

foreach ($py in @('python3', 'python', 'py')) {
    $cmd = Get-Command $py -ErrorAction SilentlyContinue
    if (-not $cmd) { continue }
    # A Python 2 `python`, or a Microsoft Store alias stub masquerading as
    # one, must not be handed the script — mirrors install.sh's own check.
    # 3.9 is the real floor (freya_cli.MIN_PYTHON: PEP 585 generics in
    # search_specs.py's evaluated annotations); anything older passed the old
    # major-version test and then died with a SyntaxError or a TypeError.
    & $cmd.Source -c 'import sys; sys.exit(0 if sys.version_info >= (3, 9) else 1)' 2>$null
    if ($LASTEXITCODE -ne 0) { continue }
    & $cmd.Source (Join-Path $here 'bin/installer.py') @args
    exit $LASTEXITCODE
}

Write-Error 'install.ps1: no Python 3.9+ found on PATH.'
exit 1
