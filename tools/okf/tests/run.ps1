# Runs the Pester 3.4 tests of the bundle checker. Usage: powershell -NoProfile -File tests\run.ps1 [test file]
param([string]$Path = $PSScriptRoot)
Import-Module Pester -MaximumVersion 3.99
$r = Invoke-Pester -Path $Path -PassThru
if ($r.FailedCount) { exit 1 }
