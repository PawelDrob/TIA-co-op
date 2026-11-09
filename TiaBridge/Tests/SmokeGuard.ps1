# SmokeGuard.ps1 - a smoke script starts a bridge of its own, and a second bridge on one TIA has hung it. Dot-sourced by the
# smoke scripts, whose first act is Assert-NoBoundBridge. It reads the state files under the projects root of this tree's
# settings and of the main working tree's: first setup writes settings.json there only, so a worktree usually has none.
. (Join-Path $PSScriptRoot '..\Repo.ps1')
. (Join-Path $PSScriptRoot '..\State.ps1')

# TiaBridge\settings.json of the main working tree of the clone that holds Folder; nothing outside git.
function Get-MainTreeSettingsPath([string]$Folder) {
    $ErrorActionPreference = 'Continue'    # a smoke script runs under Stop, where git's message outside a repo would end it
    $common = git -C $Folder rev-parse --path-format=absolute --git-common-dir 2>$null
    if ($LASTEXITCODE -eq 0 -and $common) { Join-Path (Split-Path -Parent $common) 'TiaBridge\settings.json' }
}

function Assert-NoBoundBridge([string]$SettingsPath = (Join-Path $PSScriptRoot '..\settings.json')) {
    $paths = @($SettingsPath) + @(Get-MainTreeSettingsPath (Split-Path -Parent $SettingsPath))
    $roots = @($paths | ForEach-Object { (Get-BridgeSettings $_).projectsRoot } | Select-Object -Unique)
    $bound = @($roots | ForEach-Object { Get-OtherBridges (Get-BridgeStateDir $_) } | Where-Object { Get-Process -Id $_.tia -ErrorAction SilentlyContinue })
    if ($bound.Count) {
        $names = ($bound | ForEach-Object { "bridge $($_.pid) on $($_.project), TIA $($_.tia)" }) -join '; '
        throw "A smoke script starts a bridge of its own and must not run beside one bound to a TIA: $names. Stop that session first."
    }
}
