# Helpers of the bridge tests that more than one test file uses. Dot-source it after the bridge scripts.

# TIA's path limit for a test that makes its paths in $TestDrive. $TestDrive lies under TEMP, which may be long (an
# agent's scratch folder): the limit counts from it as from a root of C:\t, so that the guard refuses only what the
# test makes too long.
function Get-TestDrivePathLimit([int]$OfTia) { $OfTia + "$TestDrive".Length - 'C:\t'.Length }

# Test-TiaAlive of a fake TIA that answers until $script:tiaGone. Like the real one (Tia.ps1) it drops the kept yes first
# and keeps a new one for the bound project, so a test's call runs with the yes Get-TiaProject keeps (Test-TiaAliveInCall).
# A test file defines Test-TiaAlive { Test-FakeTiaAlive }.
function Test-FakeTiaAlive {
    $script:Bridge.aliveProject = $null
    if ($script:Bridge.project -and -not $script:tiaGone) { $script:Bridge.aliveProject = $script:Bridge.project }
    $null -ne $script:Bridge.aliveProject
}

# Binds project P as connect does: its path, and the TIA project Test-TiaAlive asks about.
function Set-TestBridgeProject([string]$Repo) {
    Set-BridgeProject -Name 'P' -Path 'C:\P.ap20' -Repo $Repo
    $script:Bridge.project = [pscustomobject]@{ Name = 'P' }
}

# A tool call's first read of the project, as the first path of a call makes it: TIA answers and its yes is kept for the
# call. A test of TIA ending in the call makes it before the tool, so that only where the bridge asks again sees the end.
function Read-CallFirstProject { $null = Get-TiaProject }
