$here = Split-Path -Parent $MyInvocation.MyCommand.Path
foreach ($f in 'Mcp.ps1', 'Tia.ps1', 'Repo.ps1', 'Rules.ps1', 'Guards.ps1', 'Bridge.ps1', 'State.ps1', 'Tools\Objects.ps1', 'Tools\Session.ps1') { . (Join-Path $here "..\$f") }
if (-not ('Siemens.Engineering.ProjectArchivationMode' -as [type])) {
    Add-Type -TypeDefinition 'namespace Siemens.Engineering { public enum ProjectArchivationMode { None, Compressed, DiscardRestorableData, DiscardRestorableDataAndCompressed } }'
}

# The bridge a report run of the TIA dashboard starts (TiaBridge.ps1 -ReportRun, TiaAgentStatus\reportrun.py): it reads
# the project and makes its change report, and keeps out of the way of an agent's bridge on the same TIA.

Describe 'a report-run bridge' {
    $root = Join-Path $TestDrive 'projects'

    It 'refuses every tool but tia_status, connect, full_export and change_report, before the tool runs' {
        Initialize-BridgeContext @{ projectsRoot = $root; maxResponseChars = 20000 }
        $script:Bridge.reportRun = $true
        $script:ran = 0
        foreach ($name in 'import', 'save', 'archive', 'project_open', 'compile') {
            $d = Invoke-BridgeTool $name { param($a) $script:ran++; @{ ok = $true } } (New-Object psobject)
            $d.result.ok | Should Be $false
            $d.result.refused | Should Match "$name is refused in a report run"
        }
        $script:ran | Should Be 0
        foreach ($name in 'tia_status', 'connect', 'full_export', 'change_report') {
            (Invoke-BridgeTool $name { param($a) @{ ok = $true } } (New-Object psobject)).result.ok | Should Be $true
        }
    }

    It 'says in its state file that it is a report run, so the dashboard names it so' {
        Initialize-BridgeContext @{ projectsRoot = $root; maxResponseChars = 20000 }
        $script:BridgeState = @{ started = (Get-BridgeStateTime); project = $null; pendingTia = 0 }
        try {
            (Get-BridgeStateDocument).client | Should Be 'mcp'
            $script:Bridge.reportRun = $true
            (Get-BridgeStateDocument).client | Should Be 'report-run'
        }
        finally { $script:BridgeState = $null }
    }

    It 'leaves an agent''s bridge its tools' {
        Initialize-BridgeContext @{ projectsRoot = $root; maxResponseChars = 20000 }
        (Invoke-BridgeTool 'compile' { param($a) @{ ok = $true } } (New-Object psobject)).result.ok | Should Be $true
    }
}

Describe 'connect beside a report run' {
    $root = Join-Path $TestDrive 'Projects'
    $runs = Join-Path $root '_bridge\report-runs'

    # Openness stand-ins, as in Session.Tests.ps1: one TIA, process 1, with the project zzLine open
    function Set-FakeTia([switch]$ReportRun) {
        Initialize-BridgeContext @{ projectsRoot = $root; archivesKept = 10; maxResponseChars = 20000 }
        $script:Bridge.reportRun = [bool]$ReportRun
        $p = New-Object psobject -Property @{ Name = 'zzLine'; Path = [System.IO.FileInfo]'C:\P\zzLine\zzLine.ap20'; IsModified = $false }
        $p | Add-Member ScriptMethod Archive { param($Dir, $Name, $Mode) $script:archived++; Set-Content (Join-Path $Dir.FullName $Name) 'zap' }
        $script:fakeTiaProject = $p
        $script:attached = 0; $script:archived = 0; $script:others = @()
    }
    function Import-Openness { }
    function Test-OpennessGroup { $null }
    function Get-TiaProcesses { @{ processId = 1; name = 'zzLine'; path = 'C:\P\zzLine\zzLine.ap20' } }
    function Connect-Tia { $script:attached++; $script:Bridge.project = $script:fakeTiaProject; $script:Bridge.processId = 1 }
    function Reset-TiaConnection { }
    function Get-TiaProject { $script:fakeTiaProject }
    function Get-TiaSoftwareList { @() }
    function Get-TiaAttachedPrograms([int]$ProcessId) { $script:others }

    # the record a report run keeps while it runs (TiaAgentStatus\reportrun.py)
    function Write-RunRecord([string]$Folder, [hashtable]$More = @{}) {
        New-Item -ItemType Directory -Force -Path $runs | Out-Null
        $r = [ordered]@{ v = 1; pid = $PID; started = (Get-Date).ToString('yyyy-MM-ddTHH:mm:ss.fffzzz'); project = 'zzLine'
                         repo = (Join-Path $root $Folder); tia = $null; step = 'connect'; ended = $null }
        foreach ($k in $More.Keys) { $r[$k] = $More[$k] }
        Set-Content -LiteralPath (Join-Path $runs "$Folder.json") (ConvertTo-Json $r) -Encoding UTF8
    }
    function Clear-RunRecords { Remove-Item -LiteralPath $runs -Recurse -Force -ErrorAction SilentlyContinue }

    It 'makes no session archive in a report run: it reads, and an archive is no part of the report' {
        Set-FakeTia -ReportRun
        $r = Invoke-ConnectTool ('{}' | ConvertFrom-Json)
        $r.ok | Should Be $true
        $script:archived | Should Be 0
        $r.Contains('archive') | Should Be $false
        @(Get-ChildItem (Join-Path $root 'zzLine\archives') -ErrorAction SilentlyContinue).Count | Should Be 0
    }

    It 'in a report run, refuses a TIA another program is attached to, before it attaches' {
        Set-FakeTia -ReportRun
        $script:others = @(@{ pid = 4242; path = 'C:\Windows\System32\WindowsPowerShell\v1.0\powershell.exe' })
        $r = Invoke-ConnectTool ('{}' | ConvertFrom-Json)
        $r.ok | Should Be $false
        $r.refused | Should Match '^Not now: a program is connected to this TIA'
        $r.refused | Should Match 'process 4242'
        $script:attached | Should Be 0
    }

    It 'of an agent, refuses the repo of a report run that runs, before it attaches, and says when it can' {
        Clear-RunRecords
        Set-FakeTia
        Write-RunRecord 'zzLine'
        try { $r = Invoke-ConnectTool ('{}' | ConvertFrom-Json) } finally { Clear-RunRecords }
        $r.ok | Should Be $false
        $r.refused | Should Match 'The TIA dashboard is making a change report of zzLine'
        $r.refused | Should Match 'connect after it ends'
        $script:attached | Should Be 0
    }

    It 'of an agent, refuses the TIA of a report run that runs, whatever the repo' {
        Clear-RunRecords
        Set-FakeTia
        Write-RunRecord 'zzOther' @{ tia = 1 }
        try { $r = Invoke-ConnectTool ('{}' | ConvertFrom-Json) } finally { Clear-RunRecords }
        $r.ok | Should Be $false
        $r.refused | Should Match 'The TIA dashboard is making a change report'
        $script:attached | Should Be 0
    }

    It 'of an agent, refuses while the bridge of a run whose own process is gone still runs: it is on that TIA' {
        Clear-RunRecords
        Set-FakeTia
        $before = (Get-Process -Id $PID).StartTime.AddMinutes(-1).ToString('yyyy-MM-ddTHH:mm:ss.fffzzz')
        Write-RunRecord 'zzLine' @{ pid = 999999; bridge = $PID; started = $before }
        try { $r = Invoke-ConnectTool ('{}' | ConvertFrom-Json) } finally { Clear-RunRecords }
        $r.refused | Should Match 'The TIA dashboard is making a change report of zzLine'
        $script:attached | Should Be 0
    }

    It 'of an agent, connects beside a run that ended, a run whose process is gone, and a run on another TIA and repo' {
        Clear-RunRecords
        Write-RunRecord 'zzLine' @{ ended = (Get-Date).ToString('o') }
        Write-RunRecord 'zzGone' @{ pid = 999999; tia = 1 }
        Write-RunRecord 'zzOther' @{ tia = 2 }
        Set-FakeTia
        try { $r = Invoke-ConnectTool ('{}' | ConvertFrom-Json) } finally { Clear-RunRecords }
        $r.refused | Should BeNullOrEmpty
        $r.ok | Should Be $true
        $script:attached | Should Be 1
        $script:archived | Should Be 1
    }

    It 'of an agent, says in its state file which TIA it is about to attach to before it looks for a run, a TIA with a window' {
        Clear-RunRecords
        Set-FakeTia
        $script:BridgeState = @{ path = (Join-Path $TestDrive 'state.json'); started = (Get-BridgeStateTime); claude = $null; session = $null; herdr = $null
                                 project = $null; boundSince = $null; operation = $null; lastOperation = $null; lastPrompt = $null; pendingTia = 0; written = [DateTime]::MinValue }
        function Get-ReportRunRefusal { $script:seen = (Get-Content -LiteralPath $script:BridgeState.path -Raw | ConvertFrom-Json).tia; 'stop here' }
        try { $null = Invoke-BridgeTool 'connect' { param($a) Invoke-ConnectTool $a } ('{}' | ConvertFrom-Json) }
        finally { $script:BridgeState = $null }
        $script:seen.pid | Should Be 1
        # the user's TIA: read as one without a window, the dashboard and herdr would tell the user to end it
        $script:seen.window | Should Be $true
    }
}
