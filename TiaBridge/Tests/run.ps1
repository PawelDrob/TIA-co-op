# Runs the Pester 3.4 unit tests (no TIA needed). Usage: powershell -NoProfile -File run.ps1 [test file]
# A relative test file is looked up in the current folder, then in this folder. Exits non-zero when a test fails,
# the file does not exist or no test ran.
param([string]$Path = $PSScriptRoot)
$found = @($Path, (Join-Path $PSScriptRoot $Path)) | Where-Object { Test-Path $_ } | Select-Object -First 1
if (-not $found) { [Console]::Error.WriteLine("run.ps1: test file not found: $Path"); exit 2 }
Import-Module Pester -MaximumVersion 3.99
$r = Invoke-Pester -Path (Resolve-Path $found).ProviderPath -PassThru
if ($r.FailedCount) { exit 1 }
if (-not $r.TotalCount) { [Console]::Error.WriteLine("run.ps1: no test ran in $found"); exit 3 }
