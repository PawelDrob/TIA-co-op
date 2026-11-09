# First setup of a clone, also its check: run it again at any time. uv and uv sync come first, as setup.py runs on what they make.
#   powershell -NoProfile -ExecutionPolicy Bypass -File tools/setup/setup.ps1 [--projects-root <path>]
$root = (Resolve-Path (Join-Path $PSScriptRoot '..\..')).Path
if (-not (Get-Command uv -ErrorAction SilentlyContinue)) {
    'missing  uv, which makes the Python environment of this repo: install it (https://docs.astral.sh/uv/), then run this again in a new terminal.'
    exit 1
}
Set-Location -LiteralPath $root
uv sync
if ($LASTEXITCODE) {
    "missing  the Python environment: uv sync failed with exit code $LASTEXITCODE. Its message is above."
    exit 1
}
& (Join-Path $root '.venv\Scripts\python.exe') -X utf8 (Join-Path $root 'tools\setup\setup.py') @args
exit $LASTEXITCODE
