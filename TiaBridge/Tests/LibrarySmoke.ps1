# LibrarySmoke.ps1 - manual integration run of the library tools.
# Confirm the Openness access dialog in TIA. What it does to the project, which it does NOT save:
#   - edit (in work), round trip of one instance unchanged, compile, release with a new version, update usages, compile
#     of one PLC library type: -Type, else the first PLC data type in the project library that has a project instance
#   - master copy of -Block in the project library folder zzTiaBridge, then a copy of it back into the program folder
#     zzMasterCopyTest (mode Rename), deleted again
#   - before that delete, a master copy of the folder zzMasterCopyTest (source_folder), placed back at the top of the
#     program (mode Rename) and left there: delete_folder does not clear it, so discard the project
#   - the reviewed library change: library_review after the update; with -ApproveAll (the person running the script
#     approves) library_approve of every reviewed type and library_release_chain until it is done
#   - with -GlobalLibrary: library_open read-only, list its types and master copies; with -GlobalWritable (use a COPY
#     of a library) also a master copy of -Block into it and a project object from it, deleted again
# Afterwards: look at the project in TIA, then close it there without saving. Results: Tests\librarysmoke_<time>.jsonl.
param([string]$Type = '', [string]$Block = 'Communication_FB', [string]$GlobalLibrary = '', [switch]$GlobalWritable, [switch]$ApproveAll)
$ErrorActionPreference = 'Stop'
. (Join-Path $PSScriptRoot 'SmokeGuard.ps1')
Assert-NoBoundBridge
$bridge = Join-Path $PSScriptRoot '..\TiaBridge.ps1'
$outFile = Join-Path $PSScriptRoot "librarysmoke_$(Get-Date -Format yyyyMMdd_HHmmss).jsonl"

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

function Call([string]$Tool, $Arguments = @{}, [string]$Step = '') {
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
    $s = "{0,-40} ok={1,-5} {2,6:n1}s  {3}" -f $label, $body.ok, ((Get-Date) - $started).TotalSeconds, $text.Substring(0, [Math]::Min(220, $text.Length))
    [void]$script:summary.Add($s)
    Write-Host $s
    $body
}

try {
    $c = Call 'connect'
    if (-not $c.ok) { throw 'connect failed' }
    if (-not $c.archive.ok -and -not $c.session.writesAllowed) { throw 'no session archive: writes would be refused' }

    # ---------------------------------------------------------------- edit, round trip, release, update usages
    $types = @((Call 'list' @{ kind = 'library_type' } 'list library_type').items)
    $candidates = if ($Type) { @($types | Where-Object { $_.name -eq $Type }) } else { @($types | Where-Object { $_.class -match 'PlcType' }) }
    $edit = $null
    foreach ($t in $candidates | Select-Object -First 15) {
        $edit = Call 'library_edit_type' @{ name = $t.name } "edit $($t.name)"
        if ($edit.ok -and @($edit.instances).Count) { break }
        $edit = $null
    }
    if (-not $edit) { throw 'No library type with a project instance found; pass -Type.' }
    $inst = @($edit.instances)[0]
    Write-Host "   in work: $($edit.type) V $($edit.inWork); instance $($inst.kind) $($inst.name)"
    $e = Call 'export' @{ kind = $inst.kind; names = @($inst.name) } "export instance $($inst.name)"
    if ($e.ok) {
        $null = Call 'import' @{ kind = $inst.kind; paths = @($e.items[0].files[0]); override = $true } "import instance unchanged"
        $l = Call 'list' @{ kind = $inst.kind; filter = @($inst.name) } 'library link after import'
        Write-Host "   link after import: $($l.items[0].library | ConvertTo-Json -Compress)"
    }
    $null = Call 'compile' @{ scope = 'plc' } 'compile plc'
    $null = Call 'library_release_type' @{ name = $edit.type; comment = 'TiaBridge library smoke test' } "release $($edit.type)"
    $u = Call 'library_update_usages' @{ types = @($edit.type) } 'update usages'
    $null = Call 'compile' @{ scope = 'plc' } 'compile plc after update'
    if ($u.change) {
        $rv = Call 'library_review' @{} 'review the library change'
        if ($ApproveAll) {
            for ($round = 1; $round -le 10; $round++) {
                $names = @($rv.toApprove.PSObject.Properties | ForEach-Object { $_.Value.PSObject.Properties | ForEach-Object { $_.Value } })
                if ($names.Count) { $null = Call 'library_approve' @{ types = $names } "approve $($names.Count) types (round $round)" }
                $ch = Call 'library_release_chain' @{ comment = 'TiaBridge library smoke test' } "release chain (round $round)"
                if (-not $ch.ok -or $ch.next -match 'library change done') { break }
                $rv = Call 'library_review' @{} "review (round $($round + 1))"
            }
        }
    }

    # ---------------------------------------------------------------- master copies in and out
    $null = Call 'master_copy_from_project' @{ kind = 'block'; name = $Block; folder = 'zzTiaBridge'; replace = $true } "master copy from $Block"
    $mc = Call 'list' @{ kind = 'master_copy'; folder = 'zzTiaBridge' } 'list master copies'
    $to = Call 'master_copy_to_project' @{ name = $Block; folder = 'zzMasterCopyTest'; mode = 'Rename' } "project objects from master copy"
    $null = Call 'master_copy_from_project' @{ kind = 'block'; source_folder = 'zzMasterCopyTest'; folder = 'zzTiaBridge'; replace = $true } 'master copy of the folder zzMasterCopyTest'
    $null = Call 'list' @{ kind = 'master_copy'; folder = 'zzTiaBridge' } 'list master copies, with the one of the folder'
    $null = Call 'master_copy_to_project' @{ name = 'zzMasterCopyTest'; mode = 'Rename' } 'folder from its master copy'
    foreach ($n in @($to.created)) { $null = Call 'delete' @{ kind = 'block'; names = @($n) } "delete $n" }
    $null = Call 'compile' @{ scope = 'plc' } 'compile plc after master copies'

    if ($GlobalLibrary) {
        $g = Call 'library_open' @{ path = $GlobalLibrary; writable = [bool]$GlobalWritable } 'open global library'
        if ($g.ok) {
            $null = Call 'list' @{ kind = 'library_type'; library = $g.library } 'list global types'
            $null = Call 'list' @{ kind = 'master_copy'; library = $g.library } 'list global master copies'
            if ($GlobalWritable) {
                $null = Call 'master_copy_from_project' @{ kind = 'block'; name = $Block; folder = 'zzTiaBridge'; library = $g.library; replace = $true } "global master copy from $Block"
                $gt = Call 'master_copy_to_project' @{ name = $Block; folder = 'zzMasterCopyTest'; mode = 'Rename'; library = $g.library } 'project objects from global master copy'
                foreach ($n in @($gt.created)) { $null = Call 'delete' @{ kind = 'block'; names = @($n) } "delete $n" }
            }
        }
    }
    $null = Call 'tia_status'
}
catch { Write-Host "LIBRARY SMOKE ABORTED: $($_.Exception.Message)" -ForegroundColor Red }
finally {
    $p.StandardInput.Close()
    if (-not $p.WaitForExit(15000)) { $p.Kill() }
    Write-Host "`n==== summary"; $script:summary | ForEach-Object { Write-Host $_ }
    Write-Host "Full responses: $outFile"
}
