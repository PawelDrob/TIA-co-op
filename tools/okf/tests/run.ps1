# Runs the Pester 3.4 tests of the bundle checker. Usage: powershell -NoProfile -File tests\run.ps1 [test file]
param([string]$Path = $PSScriptRoot)
# Started by a git-aware parent (a hook or an alias of another repo), a run by hand would carry the parent's repo into
# every git -C of a fixture, whose commits would land there: the names git reads a repo from leave this process.
# Without git, or when it fails, they stay and the tests that need no git still run.
$problem = ''
try {
    $names = @(& git rev-parse --local-env-vars)
    if ($LASTEXITCODE) { $problem = "failed (exit code $LASTEXITCODE)" }
} catch {
    $problem = "did not answer ($($_.Exception.Message))"
}
if ($problem) {
    $names = @()
    [Console]::Error.WriteLine("run.ps1: git rev-parse --local-env-vars $($problem): the names git reads a repo from stay in this process")
}
foreach ($name in $names) { Remove-Item "Env:$name" -ErrorAction SilentlyContinue }
Import-Module Pester -MaximumVersion 3.99
$r = Invoke-Pester -Path $Path -PassThru
if ($r.FailedCount) { exit 1 }
