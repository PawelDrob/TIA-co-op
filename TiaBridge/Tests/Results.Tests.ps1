$here = Split-Path -Parent $MyInvocation.MyCommand.Path
foreach ($f in 'Mcp.ps1', 'Tia.ps1', 'Repo.ps1', 'Rules.ps1', 'Guards.ps1', 'Bridge.ps1', 'Results.ps1', 'Tools\Objects.ps1', 'Tools\Plc.ps1', 'Tools\Hmi.ps1',
               'Tools\Library.ps1', 'Tools\FullExport.ps1') { . (Join-Path $here "..\$f") }

# The short result (Results.ps1): what a tool returns to the agent, while its log keeps the whole result. Each call goes
# through the dispatch, so each test also reads the log the call wrote.

# The call of a tool whose handler returns $script:TestResult.
function Invoke-Short([string]$Tool) { Invoke-BridgeTool $Tool { param($a) $script:TestResult } (New-Object psobject) }

function Read-CallLog($D) { [System.IO.File]::ReadAllText((Join-Path $script:TestRepo $D.result.log)) | ConvertFrom-Json }

# An object of full_export that failed, as Invoke-FullExportKindPart records it.
function New-Failure([string]$Name, [string]$Message, [string]$Type = 'Siemens.Engineering.EngineeringTargetInvocationException') {
    [ordered]@{ name = $Name; folder = 'F'; error = [ordered]@{ type = $Type; message = $Message; details = @($Message); inner = @(@{ type = 'Inner.Type'; message = "inner of $Name" }) } }
}

function New-PartRecord2([string]$Part, [int]$Count, [object[]]$Failed = @()) {
    [ordered]@{ part = $Part; device = 'PLC_1'; dir = 'plc\blocks'; count = $Count; exported = $Count - @($Failed).Count; skipped = 0; why = [ordered]@{}; ms = 10
                failed = @($Failed); fellBack = @(); knowHowProtected = @(); notExported = @(); removed = @(); keptUncommitted = @(); keptRepos = @() }
}

Describe 'The short result of a tool' {
    $root = Join-Path $TestDrive 'projects'
    $script:TestRepo = Join-Path $root 'P1'

    BeforeEach {
        Initialize-BridgeContext @{ projectsRoot = $root; maxResponseChars = 20000 }
        Set-BridgeProject -Name 'P1' -Path 'C:\P1.ap20' -Repo $script:TestRepo
        Register-Archive (Get-BridgeSession)   # import and save are write tools: the archive gate lets them run
        $script:McpClientName = 'claude-code'
    }
    AfterEach { $script:McpClientName = '' }

    It 'full_export: a failure that repeats said once with how many and their names, a different one beside it whole' {
        $records = @(
            (New-PartRecord2 'blocks' 3 @((New-Failure 'B1' "The export of block 'B1' is not permitted."), (New-Failure 'B2' "The export of block 'B2' is not permitted.")))
            (New-PartRecord2 'system_blocks' 2 @((New-Failure 'S1' "The export of block 'S1' is not permitted."), (New-Failure 'S2' 'The table is inconsistent and cannot be exported.' 'Siemens.Engineering.Other'))))
        $script:TestResult = [ordered]@{ ok = $false; failedCount = 4; parts = @($records | ForEach-Object { Format-PartLine $_ })
                                         failed = @(Get-FullExportFailures $records | ForEach-Object { $_.text }); leftOut = @(); limits = $script:FullExportLimits
                                         removed = @(); keptUncommitted = @(); keptRepos = @(); details = $records; next = 'Commit.' }
        $d = Invoke-Short 'full_export'
        $a = $d.text | ConvertFrom-Json
        @($a.failed).Count | Should Be 2
        $a.failed[0] | Should Be "blocks@PLC_1: F/B1: Siemens.Engineering.EngineeringTargetInvocationException: The export of block 'B1' is not permitted. (+2 alike: F/B2, system_blocks@PLC_1: F/S1)"
        $a.failed[1] | Should Be 'system_blocks@PLC_1: F/S2: Siemens.Engineering.Other: The table is inconsistent and cannot be exported.'
        $a.failedCount | Should Be 4
        # the log as before: one line per object, every part's record, the limits
        $log = Read-CallLog $d
        @($log.failed).Count | Should Be 4
        $log.failed[3] | Should Be 'system_blocks@PLC_1: F/S2: Siemens.Engineering.Other: The table is inconsistent and cannot be exported.'
        @($log.details).Count | Should Be 2
        $log.details[0].failed[1].error.inner[0].message | Should Be 'inner of B2'
        @($log.limits).Count | Should Be @($script:FullExportLimits).Count
    }

    It 'full_export: parts that hold nothing counted, and details, limits, times and empty lists left to the log' {
        $records = @((New-PartRecord2 'blocks' 2), (New-PartRecord2 'technology_objects' 0), (New-PartRecord2 'watch_tables' 0))
        $none = New-PartRecord2 'plc_alarm_texts' 0; $none.none = $true
        $out = New-PartRecord2 'external_sources' 3; $out.leftOut = 'external source files: no export'
        $records += @($none, $out)
        $script:TestResult = [ordered]@{ ok = $true; failedCount = 0; parts = @($records | ForEach-Object { Format-PartLine $_ }); failed = @(); leftOut = @('3 external source files')
                                         limits = $script:FullExportLimits; removed = @(); keptUncommitted = @(); keptRepos = @(); details = $records
                                         planMs = 5; saveMs = 6; times = [ordered]@{ ms = 5 }; next = 'Commit.' }
        $d = Invoke-Short 'full_export'
        $a = $d.text | ConvertFrom-Json
        @($a.parts) -join '|' | Should Be 'blocks@PLC_1: 2/2, 0 s|external_sources@PLC_1: 3 not exportable'
        $a.emptyParts | Should Be 3
        foreach ($k in 'details', 'limits', 'times', 'planMs', 'saveMs', 'removed', 'keptUncommitted', 'keptRepos', 'failed') { $a.PSObject.Properties[$k] | Should BeNullOrEmpty }
        $a.leftOut | Should Be '3 external source files'
        $log = Read-CallLog $d
        @($log.parts).Count | Should Be 5
        @($log.details).Count | Should Be 5
        $log.planMs | Should Be 5
        $log.times.ms | Should Be 5
    }

    It 'import: an error that repeats said once with its count, a different one beside it whole with its Siemens texts' {
        $e = { param($n, $m) [ordered]@{ at = 'at Import-PlcFile, Plc.ps1: line 121'; message = $m; details = @($m, "detail of $n"); inner = @(); tiaEnded = $false; type = 'Siemens.X'; tiaDisconnected = $false } }
        $script:TestResult = [ordered]@{ ok = $false; transaction = $false; items = @(
            [ordered]@{ name = 'A'; path = 'plc\blocks\A.s7dcl'; ok = $false; error = (& $e 'A' "Block 'A' has a syntax error."); imported = @() }
            [ordered]@{ name = 'B'; path = 'plc\blocks\B.s7dcl'; ok = $false; error = (& $e 'B' "Block 'B' has a syntax error."); imported = @() }
            [ordered]@{ name = 'C'; path = 'plc\blocks\C.s7dcl'; ok = $false; error = (& $e 'C' 'The connection is not connected.') }
            [ordered]@{ name = 'D'; path = 'plc\blocks\D.s7dcl'; ok = $true; note = 'Line ends of D.s7dcl written as CRLF.' }
            [ordered]@{ name = 'E'; path = 'plc\blocks\E.s7dcl'; ok = $true; note = 'Line ends of E.s7dcl written as CRLF.' }) }
        $d = Invoke-Short 'import'
        $a = $d.text | ConvertFrom-Json
        $a.items[0].error.message | Should Be "Block 'A' has a syntax error."
        @($a.items[0].error.details) -join '|' | Should Be "Block 'A' has a syntax error.|detail of A"
        $a.items[0].error.type | Should Be 'Siemens.X'
        $a.items[0].error.alike | Should Be 1
        $a.items[1].error | Should Be 'as A'
        $a.items[2].error.message | Should Be 'The connection is not connected.'
        $a.items[2].error.PSObject.Properties['alike'] | Should BeNullOrEmpty
        $a.items[3].note | Should Be 'Line ends of D.s7dcl written as CRLF.'
        $a.items[4].note | Should Be 'as D'
        foreach ($k in 'at', 'inner', 'tiaEnded', 'tiaDisconnected') { $a.items[0].error.PSObject.Properties[$k] | Should BeNullOrEmpty }
        $a.items[0].PSObject.Properties['imported'] | Should BeNullOrEmpty
        $a.items[1].ok | Should Be $false
        $a.transaction | Should Be $false
        # the log as the tool returned it
        $log = Read-CallLog $d
        $log.items[1].error.message | Should Be "Block 'B' has a syntax error."
        $log.items[0].error.at | Should Match 'Import-PlcFile'
        $log.items[0].error.tiaEnded | Should Be $false
        $log.items[4].note | Should Be 'Line ends of E.s7dcl written as CRLF.'
    }

    It 'import: an inner chain stays whole' {
        $script:TestResult = [ordered]@{ ok = $false; items = @([ordered]@{ name = 'A'; ok = $false; error = [ordered]@{ type = 'T'; message = 'm'; details = @('m')
                                                                     inner = @([ordered]@{ type = 'Inner'; message = 'why' }) } }) }
        $a = (Invoke-Short 'import').text | ConvertFrom-Json
        $a.items[0].error.inner[0].type | Should Be 'Inner'
        $a.items[0].error.inner[0].message | Should Be 'why'
    }

    It 'compile: items with errors or warnings, the clean ones counted, a warning on every item said once' {
        $tree = { param($b, $state, $desc) [ordered]@{ state = $state; errors = [int]($state -eq 'Error'); warnings = [int]($state -eq 'Warning'); messages = @(
            [ordered]@{ path = 'PLC_1'; state = $state; description = ''; messages = @(
                [ordered]@{ path = $b; state = $state; description = ''; messages = @([ordered]@{ path = 'Network 1'; state = $state; description = $desc; messages = @() }) }) }
            [ordered]@{ path = ''; state = 'Success'; description = 'Compiling finished.'; messages = @() }) } }
        $script:TestResult = [ordered]@{ ok = $false; scope = 'blocks'; errors = 1; failed = @(); items = @(
            [ordered]@{ name = 'A'; ok = $true; errors = 0; warnings = 0; messages = (& $tree 'A (FB1)' 'Success' 'Block was successfully compiled.') }
            [ordered]@{ name = 'B'; ok = $true; errors = 0; warnings = 1; messages = (& $tree 'B (FB2)' 'Warning' 'Tag X is not used.') }
            [ordered]@{ name = 'C'; ok = $true; errors = 0; warnings = 1; messages = (& $tree 'C (FB3)' 'Warning' 'Tag X is not used.') }
            [ordered]@{ name = 'D'; ok = $false; errors = 1; warnings = 0; messages = (& $tree 'D (FB4)' 'Error' 'Y is not defined.') }
            [ordered]@{ name = 'E'; ok = $true; errors = 0; warnings = 0; messages = (& $tree 'E (FB5)' 'Success' 'Block was successfully compiled.') }) }
        $d = Invoke-Short 'compile'
        $a = $d.text | ConvertFrom-Json
        $a.cleanItems | Should Be 2
        @($a.items | ForEach-Object { $_.name }) -join ',' | Should Be 'B,C,D'
        $a.items[0].messages[0].path | Should Be 'PLC_1 / B (FB2) / Network 1'
        $a.items[0].messages[0].description | Should Be 'Tag X is not used.'
        $a.items[1].messages[0].description | Should Be 'as in B'
        $a.items[2].messages[0].state | Should Be 'Error'
        $a.items[2].messages[0].description | Should Be 'Y is not defined.'
        @($a.items[2].messages).Count | Should Be 1
        @($a.failed).Count | Should Be 0
        $a.PSObject.Properties['failed'] | Should Not BeNullOrEmpty
        $log = Read-CallLog $d
        @($log.items).Count | Should Be 5
        $log.items[2].messages.messages[0].messages[0].messages[0].description | Should Be 'Tag X is not used.'
    }

    It 'compile: a message that repeats inside one item said once with every path' {
        $leaf = { param($p) [ordered]@{ path = $p; state = 'Warning'; description = 'Same warning.'; messages = @() } }
        $script:TestResult = [ordered]@{ ok = $true; scope = 'plc'; errors = 0; items = @([ordered]@{ name = 'PLC software'; ok = $true; errors = 0; warnings = 2
                                         messages = [ordered]@{ state = 'Warning'; warnings = 2; messages = @((& $leaf 'X'), (& $leaf 'Y')) } }) }
        $a = (Invoke-Short 'compile').text | ConvertFrom-Json
        @($a.items[0].messages).Count | Should Be 1
        @($a.items[0].messages[0].paths) -join ',' | Should Be 'X,Y'
    }

    It 'background_open and background_close: the steps as a count and the total time, a slow step by name' {
        $step = { param($n, $ms) [ordered]@{ step = $n; ms = $ms; at = '2026-11-21T14:23:43'; tia = [ordered]@{ workingSetMB = 1223 }; bridge = [ordered]@{ workingSetMB = 171 }; freeMB = 10775 } }
        $script:TestResult = [ordered]@{ ok = $true; processId = 6056; steps = @((& $step 'start' 3987), (& $step 'open' 70000), (& $step 'bind' 2188)) }
        $d = Invoke-Short 'background_open'
        $a = $d.text | ConvertFrom-Json
        $a.steps.count | Should Be 3
        $a.steps.ms | Should Be 76175
        @($a.steps.slow).Count | Should Be 1
        $a.steps.slow[0].step | Should Be 'open'
        $a.steps.slow[0].ms | Should Be 70000
        $a.processId | Should Be 6056
        (Read-CallLog $d).steps[0].tia.workingSetMB | Should Be 1223
        $script:TestResult = [ordered]@{ ok = $true; closed = $true; totalMs = 6175; steps = @((& $step 'start' 3987), (& $step 'bind' 2188)); stepsLog = 'C:\P1\logs\x_background_steps.json' }
        $a = (Invoke-Short 'background_close').text | ConvertFrom-Json
        $a.steps.count | Should Be 2
        $a.steps.PSObject.Properties['slow'] | Should BeNullOrEmpty
        $a.stepsLog | Should Be 'C:\P1\logs\x_background_steps.json'
    }

    It 'change_report: default and empty values left out, every row kept' {
        $script:TestResult = [ordered]@{ ok = $true; page = 'changes\reports\x.html'; otherFiles = @(); blocks = @(
            [ordered]@{ name = 'Main'; kind = 'OB'; state = 'changed'; interface = $false; properties = $false; networks = @([ordered]@{ state = 'new'; lang = 'LAD'; before = $null; after = 8; title = '' }) }
            [ordered]@{ name = 'Gone'; kind = 'FB'; state = 'removed'; interface = $true; properties = $false; networks = @() }) }
        $d = Invoke-Short 'change_report'
        $a = $d.text | ConvertFrom-Json
        @($a.blocks).Count | Should Be 2
        @($a.blocks[0].PSObject.Properties.Name) -join ',' | Should Be 'name,kind,state,networks'
        @($a.blocks[0].networks[0].PSObject.Properties.Name) -join ',' | Should Be 'state,lang,after'
        @($a.blocks[1].PSObject.Properties.Name) -join ',' | Should Be 'name,kind,state,interface'
        $a.PSObject.Properties['otherFiles'] | Should BeNullOrEmpty
        (Read-CallLog $d).blocks[0].interface | Should Be $false
    }

    It 'the envelope: project and repo said once and again when they change; the step of a background session left to the log' {
        $script:TestResult = [ordered]@{ ok = $true }
        $c = (Invoke-Short 'connect').text | ConvertFrom-Json
        $c.project | Should Be 'P1'
        $c.repo | Should Be $script:TestRepo
        $a = Invoke-Short 'save'
        ($a.text | ConvertFrom-Json).PSObject.Properties['project'] | Should BeNullOrEmpty
        ($a.text | ConvertFrom-Json).PSObject.Properties['repo'] | Should BeNullOrEmpty
        ($a.text | ConvertFrom-Json).log | Should Match '^logs\\'
        (Read-CallLog $a).project | Should Be 'P1'
        $script:TestResult = [ordered]@{ ok = $true }
        ((Invoke-Short 'connect').text | ConvertFrom-Json).project | Should Be 'P1'
        $script:Bridge.repo = Join-Path $root 'P2'
        $script:Bridge.projectName = 'P2'
        $script:TestRepo = Join-Path $root 'P2'
        $l = (Invoke-Short 'list').text | ConvertFrom-Json
        $l.project | Should Be 'P2'
        $l.repo | Should Be $script:TestRepo
        $script:TestRepo = Join-Path $root 'P1'
    }

    It 'the envelope: the step record of a background call is left out, the step a background_open failed at stays' {
        $step = [ordered]@{ step = 'export'; ms = 5; at = 'x'; tia = $null; bridge = $null; freeMB = 1 }
        $short = Get-ShortResult 'export' ([ordered]@{ ok = $true; step = $step; items = @() }) @{}
        $short.Contains('step') | Should Be $false
        (Get-ShortResult 'background_open' ([ordered]@{ ok = $false; step = 'open'; error = @{ type = 'T'; message = 'm' } }) @{}).step | Should Be 'open'
    }

    It 'gives a program of this repo, and a report run, the whole result' {
        $script:TestResult = [ordered]@{ ok = $true; parts = @('a: 0/0, 0 s'); failed = @(); limits = @('x'); details = @((New-PartRecord2 'a' 0)) }
        $script:McpClientName = 'TiaArchiveCompare'
        $a = (Invoke-Short 'full_export').text | ConvertFrom-Json
        @($a.details).Count | Should Be 1
        $a.limits | Should Be 'x'
        $a.project | Should Be 'P1'
        $script:McpClientName = 'claude-code'
        $script:Bridge.reportRun = $true
        @(((Invoke-Short 'full_export').text | ConvertFrom-Json).details).Count | Should Be 1
        $script:Bridge.reportRun = $false
        ((Invoke-Short 'full_export').text | ConvertFrom-Json).PSObject.Properties['details'] | Should BeNullOrEmpty
    }

    It 'gives the whole result when the short one cannot be made' {
        $script:TestResult = [ordered]@{ ok = $true; items = @([ordered]@{ name = 'A'; ok = $true }) }
        Mock Get-ShortResult { throw 'a shape it does not know' }
        $a = (Invoke-Short 'export').text | ConvertFrom-Json
        $a.items[0].name | Should Be 'A'
        $a.project | Should Be 'P1'
    }

    It 'names the clients that read the whole result as their code does' {
        $client = [System.IO.File]::ReadAllText((Join-Path $here '..\..\TiaArchiveCompare\runner\bridge.py'))
        foreach ($n in $script:WholeResultClients) { $client | Should Match ([regex]::Escape("'clientInfo': {'name': '$n'")) }
        [System.IO.File]::ReadAllText((Join-Path $here '..\..\TiaAgentStatus\reportrun.py')) | Should Match "'-ReportRun'"
    }

    It 'leaves the limits of full_export to the Openness guide, which holds each one' {
        $guide = [System.IO.File]::ReadAllText((Join-Path $here '..\..\docs\agent\openness-v20.md'))
        foreach ($l in $script:FullExportLimits) { $guide | Should Match ([regex]::Escape("- $l")) }
    }
}
