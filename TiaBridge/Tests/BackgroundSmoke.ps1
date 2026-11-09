# BackgroundSmoke.ps1 - manual integration run of the tools Smoke.ps1 and LibrarySmoke.ps1 do not reach: a background session
# for export only and one with write, full_export, change_report after a save and a commit, library_create_type and
# library_discard_type. It needs no TIA with a window. Run it only on a throwaway copy of a closed project, with a repo of its own,
# and with no other bridge bound to a TIA: it starts its own bridge and its own TIA without user interface.
#   -Path    the .ap20 of the copy
#   -Repo    the repo folder under the projects root, never the project's own
#   -SafetyLogin  also calls safety_login: a password window opens on the screen, so only with the person at it
# What it does to the copy: session archive, a new FC zzSmokeBgFc imported, compiled, saved and committed, changed, compiled,
# saved and committed, then deleted and saved; a new library type zzSmokeBgType created in zzSmokeBg and discarded. It leaves
# the folder zzSmokeBg empty and takes it away with delete_folder. Not reached by any of the three: library_left_behind, which
# stands at the end of a reviewed change with types left behind, and full_export under connect.
# Results: Tests\smoke_background_<time>.jsonl (one response per line). Exit 0 when every step answered as it should.
param(
    [Parameter(Mandatory = $true)][string]$Path,
    [Parameter(Mandatory = $true)][string]$Repo,
    [switch]$SafetyLogin
)
$ErrorActionPreference = 'Stop'
. (Join-Path $PSScriptRoot 'SmokeGuard.ps1')
Assert-NoBoundBridge
$bridge = Join-Path $PSScriptRoot '..\TiaBridge.ps1'
$outFile = Join-Path $PSScriptRoot "smoke_background_$(Get-Date -Format yyyyMMdd_HHmmss).jsonl"

$psi = New-Object System.Diagnostics.ProcessStartInfo
$psi.FileName = "$env:SystemRoot\System32\WindowsPowerShell\v1.0\powershell.exe"
$psi.Arguments = "-NoProfile -STA -ExecutionPolicy Bypass -File `"$bridge`""
$psi.UseShellExecute = $false
$psi.RedirectStandardInput = $true
$psi.RedirectStandardOutput = $true
$psi.StandardOutputEncoding = New-Object System.Text.UTF8Encoding $false
$p = [System.Diagnostics.Process]::Start($psi)
$utf8 = New-Object System.Text.UTF8Encoding $false
$script:id = 0
$script:summary = New-Object System.Collections.ArrayList
$script:wrong = New-Object System.Collections.ArrayList

function Call([string]$Tool, $Arguments = @{}, [string]$Step = '', [bool]$WantOk = $true) {
    $script:id++
    $req = ConvertTo-Json @{ jsonrpc = '2.0'; id = $script:id; method = 'tools/call'; params = @{ name = $Tool; arguments = $Arguments } } -Depth 20 -Compress
    $bytes = $utf8.GetBytes($req + "`n")
    $p.StandardInput.BaseStream.Write($bytes, 0, $bytes.Length); $p.StandardInput.BaseStream.Flush()
    $started = Get-Date
    $line = $p.StandardOutput.ReadLine()
    if ($null -eq $line) { throw "The bridge exited during $Tool." }
    Add-Content -Path $outFile -Value $line -Encoding UTF8
    $text = ($line | ConvertFrom-Json).result.content[0].text
    $body = $text | ConvertFrom-Json
    $label = if ($Step) { $Step } else { $Tool }
    $mark = if ([bool]$body.ok -eq $WantOk) { 'as it should' } else { [void]$script:wrong.Add($label); 'WRONG' }
    $s = "{0,-38} ok={1,-5} {2,-12} {3,6:n1}s  {4}" -f $label, $body.ok, $mark, ((Get-Date) - $started).TotalSeconds, $text.Substring(0, [Math]::Min(160, $text.Length))
    [void]$script:summary.Add($s)
    Write-Host $s
    $body
}

function Write-Document([string]$File, [string]$Text) {
    New-Item -ItemType Directory -Force -Path (Split-Path $File) | Out-Null
    [System.IO.File]::WriteAllText($File, ($Text -replace "`r?`n", "`r`n"), (New-Object System.Text.UTF8Encoding $true))
}

$head = '{ S7_PreferredLanguage := "LAD"; S7_GenerateENOforSCL := "FALSE"; S7_IECCheck := "FALSE"; S7_Optimized := "TRUE"; S7_Version := "0.1" }'
function Get-FcDocument([string]$Name, [string]$Members) {
    "$head`nFUNCTION `"$Name`" : Void`nVAR_INPUT`n$Members`nEND_VAR`n`n{ S7_Language := `"SCL`" }`nNETWORK`n    ;`nEND_NETWORK`nEND_FUNCTION`n"
}

try {
    $null = Call 'tia_status'

    # ---------------------------------------------------------------- export only: a copy of the project file
    $e = Call 'background_open' @{ path = $Path; repo = $Repo } 'background_open, export only'
    if (-not $e.ok) { throw 'background_open failed' }
    $null = Call 'import' @{ kind = 'block'; paths = @('nothing.s7dcl') } 'import is refused in this session' $false
    $null = Call 'full_export' @{ parts = @('types', 'project_texts') } 'full_export of two parts'
    $null = Call 'background_close' @{} 'background_close, export only'

    # ---------------------------------------------------------------- write: the project file itself
    $w = Call 'background_open' @{ path = $Path; repo = $Repo; write = $true } 'background_open, write'
    if (-not $w.ok) { throw 'background_open with write failed' }
    $root = $w.repo
    # Under the script's Stop, Windows PowerShell 5.1 makes any line git writes to stderr a terminating error, a warning too.
    function Invoke-RepoGit {
        $ErrorActionPreference = 'Continue'
        & git -C $root @args 2>$null
        if ($LASTEXITCODE) { throw "git $($args -join ' ') failed with exit code $LASTEXITCODE" }
    }
    function Save-And-Commit([string]$Why) {
        $null = Call 'save' @{ reason = $Why } "save: $Why"
        Invoke-RepoGit add -A
        Invoke-RepoGit -c user.name=smoke -c user.email=smoke@example.invalid commit -q -m "background smoke: $Why"
    }
    $fcFile = 'plc\blocks\zzSmokeBg\zzSmokeBgFc.s7dcl'
    Write-Document (Join-Path $root $fcFile) (Get-FcDocument 'zzSmokeBgFc' '    first1 : Bool;')
    $null = Call 'import' @{ kind = 'block'; paths = @($fcFile); target_folder = 'zzSmokeBg' } 'import a new FC'
    $null = Call 'compile' @{ scope = 'blocks'; names = @('zzSmokeBgFc') } 'compile it'
    Save-And-Commit 'new FC'
    Write-Document (Join-Path $root $fcFile) (Get-FcDocument 'zzSmokeBgFc' "    first1 : Bool;`n    second1 : Bool;")
    $null = Call 'import' @{ kind = 'block'; paths = @($fcFile) } 'import the change'
    $null = Call 'compile' @{ scope = 'blocks'; names = @('zzSmokeBgFc') } 'compile the change'
    Save-And-Commit 'FC changed'
    $r = Call 'change_report' @{ title = 'background smoke' } 'change_report of the last commit'
    if (@($r.blocks | Where-Object { $_.name -eq 'zzSmokeBgFc' }).Count -eq 0) { [void]$script:wrong.Add('change_report does not name zzSmokeBgFc') }
    $null = Call 'archive' @{ reason = 'background smoke' }

    # ---------------------------------------------------------------- a new library type, and away again
    $typeFile = 'library\types\zzSmokeBg\zzSmokeBgType\zzSmokeBgType.s7dcl'
    Write-Document (Join-Path $root $typeFile) (Get-FcDocument 'zzSmokeBgType' '    first1 : Bool;')
    $null = Call 'library_create_type' @{ path = $typeFile; target_folder = 'zzSmokeBg'; library_folder = 'zzSmokeBg' } 'library_create_type'
    $null = Call 'compile' @{ scope = 'blocks'; names = @('zzSmokeBgType') } 'compile the type by name'
    $null = Call 'library_discard_type' @{ name = 'zzSmokeBgType' } 'library_discard_type'

    # ---------------------------------------------------------------- take the FC and its folder away
    $null = Call 'delete' @{ kind = 'block'; names = @('zzSmokeBgFc') } 'delete the FC'
    $null = Call 'delete_folder' @{ kind = 'block'; folder = 'zzSmokeBg' } 'delete_folder of what it leaves empty'
    Remove-Item -LiteralPath (Join-Path $root 'plc\blocks\zzSmokeBg') -Recurse -Force
    Remove-Item -LiteralPath (Join-Path $root 'library\types\zzSmokeBg') -Recurse -Force
    Save-And-Commit 'FC deleted'

    if ($SafetyLogin) {
        Write-Host 'safety_login: a password window opens on the screen.' -ForegroundColor Cyan
        $null = Call 'safety_login' @{} 'safety_login'
    }
    $null = Call 'tia_status' @{} 'tia_status at the end'
    $null = Call 'background_close' @{} 'background_close, write'
}
catch { [void]$script:wrong.Add($_.Exception.Message); Write-Host "BACKGROUND SMOKE ABORTED: $($_.Exception.Message)" -ForegroundColor Red }
finally {
    $p.StandardInput.Close()
    if (-not $p.WaitForExit(30000)) { $p.Kill() }
    Write-Host "`n==== summary"; $script:summary | ForEach-Object { Write-Host $_ }
    Write-Host "Full responses: $outFile"
    if ($script:wrong.Count) { Write-Host "NOT AS IT SHOULD: $($script:wrong -join '; ')" -ForegroundColor Red }
}
exit $script:wrong.Count
