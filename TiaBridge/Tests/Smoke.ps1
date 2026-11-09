# Smoke.ps1 - manual integration run of the tools under connect against an open test project.
# Those of a background session: BackgroundSmoke.ps1; the library tools: LibrarySmoke.ps1.
# Confirm the Openness access dialog in TIA when it appears. What it does to the project:
#   - session archive (connect), then one more archive
#   - round trip (export, import unchanged, re-export, compare) of one SCL block, one LAD block, one UDT and one
#     PLC tag table, picked automatically: no library instances, no know-how protection, not the default tag table
#   - HMI import on copies only: a copy of a screen as zzSmokeScreen (folder zzStaging) and of an HMI tag table as
#     zzSmokeTags (tags renamed), both deleted again; originals are never overwritten (alarm views, guide 7.1/7.2);
#     then delete_folder of zzStaging, which goes only if nothing else is in it
#   - compile PLC and HMI, save, a forced error (broken .s7dcl of a new name), which leaves no save blocker
# Results: Tests\smoke_<time>.jsonl (one response per line).
param([string]$Project = '')
$ErrorActionPreference = 'Stop'
. (Join-Path $PSScriptRoot 'SmokeGuard.ps1')
Assert-NoBoundBridge
$bridge = Join-Path $PSScriptRoot '..\TiaBridge.ps1'
$outFile = Join-Path $PSScriptRoot "smoke_$(Get-Date -Format yyyyMMdd_HHmmss).jsonl"

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
    $s = "{0,-34} ok={1,-5} {2,6:n1}s  {3}" -f $label, $body.ok, ((Get-Date) - $started).TotalSeconds, $text.Substring(0, [Math]::Min(220, $text.Length))
    [void]$script:summary.Add($s)
    Write-Host $s
    $body
}

function Get-RepoFile([string]$Rel) { Join-Path $script:repo $Rel }

# File text for a round-trip comparison: SimaticML carries its export time in DocumentInfo/Created.
function Get-ComparableText([string]$Path) { (Get-Content -LiteralPath $Path -Raw) -replace "<Created>[^<]*</Created>", "" }

# Renames the root object (and with -Members the objects of that element type) of a SimaticML file; writes UTF-8 with BOM.
function Copy-SimaticMl([string]$From, [string]$To, [string]$NewName, [string]$NewNumber = '', [string]$MemberElement = '', [string]$MemberPrefix = '') {
    [xml]$doc = Get-Content -LiteralPath $From -Raw -Encoding UTF8
    $root = $doc.Document.ChildNodes | Where-Object { $_.LocalName -like 'Hmi.*' } | Select-Object -First 1
    $root.AttributeList.Name = $NewName
    if ($NewNumber -and $root.AttributeList.Number) { $root.AttributeList.Number = $NewNumber }
    if ($MemberElement) { foreach ($n in $doc.SelectNodes("//$MemberElement/AttributeList/Name")) { $n.InnerText = $MemberPrefix + $n.InnerText } }
    New-Item -ItemType Directory -Force -Path (Split-Path $To) | Out-Null
    $w = New-Object System.Xml.XmlTextWriter($To, (New-Object System.Text.UTF8Encoding $true))
    $w.Formatting = 'Indented'; $doc.Save($w); $w.Close()
}

try {
    $null = Call 'tia_status'
    Write-Host 'connect: confirm the Openness access dialog in TIA if it appears; the session archive follows.' -ForegroundColor Cyan
    $c = Call 'connect' $(if ($Project) { @{ project = $Project } } else { @{} })
    if (-not $c.ok) { throw 'connect failed' }
    $script:repo = $c.repo
    if (-not $c.archive.ok) { $null = Call 'archive' @{ reason = 'smoke'; skip = $false } }

    $lists = @{}
    foreach ($k in 'block', 'db', 'type', 'plc_tag_table', 'hmi_screen', 'hmi_template', 'hmi_popup', 'hmi_tag_table', 'hmi_textlist', 'library_type', 'faceplate_type', 'master_copy') {
        $lists[$k] = @((Call 'list' @{ kind = $k } "list $k").items)
    }

    # ---------------------------------------------------------------- PLC round trip
    $plain = { param($i) -not $i.library -and -not $i.knowHowProtected }
    $pick = @(
        @('block', ($lists.block | Where-Object { $_.class -in 'FB', 'FC' -and $_.language -eq 'SCL' -and (& $plain $_) } | Select-Object -First 1)),
        @('block', ($lists.block | Where-Object { $_.class -in 'FB', 'FC' -and $_.language -eq 'LAD' -and (& $plain $_) } | Select-Object -First 1)),
        @('type', ($lists.type | Where-Object { & $plain $_ } | Select-Object -First 1)),
        @('plc_tag_table', ($lists.plc_tag_table | Where-Object { -not $_.isDefault } | Select-Object -First 1))
    )
    foreach ($x in $pick) {
        $kind = $x[0]; $obj = $x[1]
        if (-not $obj) { Write-Host "no suitable $kind for the round trip" -ForegroundColor Yellow; continue }
        $e1 = Call 'export' @{ kind = $kind; names = @($obj.name) } "export $kind $($obj.name)"
        if (-not $e1.ok) { continue }
        $files = @($e1.items[0].files)
        $before = @{}; foreach ($f in $files) { $before[$f] = Get-ComparableText (Get-RepoFile $f) }
        $null = Call 'import' @{ kind = $kind; paths = @($files[0]); override = $true } "import $kind $($obj.name)"
        $e2 = Call 'export' @{ kind = $kind; names = @($obj.name) } "re-export $kind $($obj.name)"
        foreach ($f in $files) {
            $same = (Get-ComparableText (Get-RepoFile $f)) -eq $before[$f]
            Write-Host ("   round trip {0}: {1}" -f $f, $(if ($same) { 'identical' } else { 'DIFFERS (see git diff in the project repo)' })) -ForegroundColor $(if ($same) { 'Green' } else { 'Yellow' })
            [void]$script:summary.Add("   round trip $f : $(if ($same) { 'identical' } else { 'differs' })")
        }
    }
    $null = Call 'compile' @{ scope = 'plc' } 'compile plc'

    # ---------------------------------------------------------------- HMI on copies
    $screen = $lists.hmi_screen | Where-Object { $_.name -notmatch 'alarm|diag|zz' } | Select-Object -First 1
    $tagTables = @($lists.hmi_tag_table | Where-Object { -not $_.isSystem -and $_.name -notmatch '^zz' })
    $hmiCopies = @()
    if ($screen) {
        $e = Call 'export' @{ kind = 'hmi_screen'; names = @($screen.name) } "export screen $($screen.name)"
        if ($e.ok) {
            # screens are imported from hmi\generated\screens only, through the HMI validator (import guard)
            Copy-SimaticMl (Get-RepoFile $e.items[0].files[0]) (Get-RepoFile 'hmi\generated\screens\zzStaging\zzSmokeScreen.xml') 'zzSmokeScreen' '9901'
            $i = Call 'import' @{ kind = 'hmi_screen'; paths = @('hmi\generated\screens\zzStaging\zzSmokeScreen.xml') } 'import zzSmokeScreen (zzStaging)'
            if ($i.ok) { $hmiCopies += , @('hmi_screen', 'zzSmokeScreen') }
        }
    }
    # a table with broken tags does not export (WinCC guide 7.2): take the first one that does, at most three tries
    foreach ($tagTable in $tagTables | Select-Object -First 3) {
        $e = Call 'export' @{ kind = 'hmi_tag_table'; names = @($tagTable.name) } "export HMI tags $($tagTable.name)"
        if ($e.ok) {
            # tag tables too come from hmi\generated\tags only, through the HMI validator
            Copy-SimaticMl (Get-RepoFile $e.items[0].files[0]) (Get-RepoFile 'hmi\generated\tags\zzSmokeTags.xml') 'zzSmokeTags' '' 'Hmi.Tag.Tag' 'zzSmoke_'
            $i = Call 'import' @{ kind = 'hmi_tag_table'; paths = @('hmi\generated\tags\zzSmokeTags.xml') } 'import zzSmokeTags'
            if ($i.ok) { $hmiCopies += , @('hmi_tag_table', 'zzSmokeTags') }
            break
        }
    }
    $null = Call 'export' @{ kind = 'faceplate_type'; names = @('*') } 'export faceplate metadata'
    $null = Call 'compile' @{ scope = 'hmi' } 'compile hmi (with copies)'
    foreach ($h in $hmiCopies) { $null = Call 'delete' @{ kind = $h[0]; names = @($h[1]) } "delete $($h[1])" }
    if ($hmiCopies.Count) { $null = Call 'compile' @{ scope = 'hmi' } 'compile hmi (copies deleted)' }
    if (@($hmiCopies | Where-Object { $_[0] -eq 'hmi_screen' }).Count) { $null = Call 'delete_folder' @{ kind = 'hmi_screen'; folder = 'zzStaging' } 'delete_folder zzStaging' }

    # ---------------------------------------------------------------- save, archive, probe
    $null = Call 'save' @{ reason = 'smoke round trip' }
    $null = Call 'archive' @{ reason = 'smoke' }
    $null = Call 'probe' @{ object_path = 'project'; member = 'ProjectLibrary' } 'probe project.ProjectLibrary'
    $null = Call 'tia_status'

    # ---------------------------------------------------------------- forced error: the full Siemens chain must come back
    $broken = Get-RepoFile 'plc\blocks\zzSmokeBroken.s7dcl'
    Set-Content -Path $broken -Value "FUNCTION_BLOCK `"zzSmokeBroken`"`nthis is not S7DCL`nEND_FUNCTION_BLOCK" -Encoding ASCII
    $e = Call 'import' @{ kind = 'block'; paths = @('plc\blocks\zzSmokeBroken.s7dcl') } 'forced error: broken .s7dcl'
    Remove-Item $broken
    Write-Host ($e.items[0] | ConvertTo-Json -Depth 20)
    $null = Call 'tia_status' @{ } 'tia_status (the failed import of a new name holds nothing: saveBlockers empty)'
}
catch { Write-Host "SMOKE ABORTED: $($_.Exception.Message)" -ForegroundColor Red }
finally {
    $p.StandardInput.Close()
    if (-not $p.WaitForExit(15000)) { $p.Kill() }
    Write-Host "`n==== summary"; $script:summary | ForEach-Object { Write-Host $_ }
    Write-Host "Full responses: $outFile"
}
