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

function New-TestPartRecord([string]$Part, [int]$Count, [object[]]$Failed = @()) {
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
            (New-TestPartRecord 'blocks' 3 @((New-Failure 'B1' "The export of block 'B1' is not permitted."), (New-Failure 'B2' "The export of block 'B2' is not permitted.")))
            (New-TestPartRecord 'system_blocks' 2 @((New-Failure 'S1' "The export of block 'S1' is not permitted."), (New-Failure 'S2' 'The table is inconsistent and cannot be exported.' 'Siemens.Engineering.Other'))))
        $script:TestResult = [ordered]@{ ok = $false; failedCount = 4; parts = @($records | ForEach-Object { Format-PartLine $_ })
                                         failed = @(Get-FullExportFailures $records | ForEach-Object { $_.text }); leftOut = @(); limits = $script:FullExportLimits
                                         removed = @(); keptUncommitted = @(); keptRepos = @(); details = $records; next = 'Commit.' }
        $d = Invoke-Short 'full_export'
        $a = $d.text | ConvertFrom-Json
        @($a.failed).Count | Should Be 2
        $a.failed[0] | Should Be "blocks@PLC_1: F/B1: Siemens.Engineering.EngineeringTargetInvocationException: The export of block 'B1' is not permitted. (+2 alike: F/B2, system_blocks@PLC_1: F/S1)"
        $a.failed[1] | Should Be 'system_blocks@PLC_1: F/S2: Siemens.Engineering.Other: The table is inconsistent and cannot be exported.'
        $a.failedCount | Should Be 4
        # the first object of each kind with its whole Siemens error, as the agent quotes it
        @($a.failedErrors).Count | Should Be 2
        $a.failedErrors[0].object | Should Be 'blocks@PLC_1: F/B1'
        $a.failedErrors[0].error.type | Should Be 'Siemens.Engineering.EngineeringTargetInvocationException'
        $a.failedErrors[0].error.details[0] | Should Be "The export of block 'B1' is not permitted."
        $a.failedErrors[0].error.inner[0].message | Should Be 'inner of B1'
        $a.failedErrors[1].object | Should Be 'system_blocks@PLC_1: F/S2'
        $a.failedErrors[1].error.inner[0].type | Should Be 'Inner.Type'
        # the log as before: one line per object, every part's record, the limits
        $log = Read-CallLog $d
        @($log.failed).Count | Should Be 4
        $log.failed[3] | Should Be 'system_blocks@PLC_1: F/S2: Siemens.Engineering.Other: The table is inconsistent and cannot be exported.'
        @($log.details).Count | Should Be 2
        $log.details[0].failed[1].error.inner[0].message | Should Be 'inner of B2'
        @($log.limits).Count | Should Be @($script:FullExportLimits).Count
    }

    It 'full_export: parts that hold nothing counted, and details, limits, times and empty lists left to the log' {
        $records = @((New-TestPartRecord 'blocks' 2), (New-TestPartRecord 'technology_objects' 0), (New-TestPartRecord 'watch_tables' 0))
        $none = New-TestPartRecord 'plc_alarm_texts' 0; $none.none = $true
        $out = New-TestPartRecord 'external_sources' 3; $out.leftOut = 'external source files: no export'
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
        @($a.items[0].imported).Count | Should Be 0
        $a.items[1].ok | Should Be $false
        $a.transaction | Should Be $false
        # the log as the tool returned it
        $log = Read-CallLog $d
        $log.items[1].error.message | Should Be "Block 'B' has a syntax error."
        $log.items[0].error.at | Should Match 'Import-PlcFile'
        $log.items[0].error.tiaEnded | Should Be $false
        $log.items[4].note | Should Be 'Line ends of E.s7dcl written as CRLF.'
    }

    It 'never takes two messages that differ only in case for alike' {
        $script:TestResult = [ordered]@{ ok = $false; items = @(
            [ordered]@{ name = 'A'; ok = $false; error = [ordered]@{ type = 'T'; message = 'Value too large.' } }
            [ordered]@{ name = 'B'; ok = $false; error = [ordered]@{ type = 'T'; message = 'Value too LARGE.' } }) }
        $a = (Invoke-Short 'import').text | ConvertFrom-Json
        $a.items[1].error.message | Should Be 'Value too LARGE.'
        $leaf = { param($d) [ordered]@{ path = 'X'; state = 'Warning'; description = $d; messages = @() } }
        $script:TestResult = [ordered]@{ ok = $true; scope = 'plc'; errors = 0; items = @([ordered]@{ name = 'P'; ok = $true; errors = 0; warnings = 2
                                         messages = [ordered]@{ state = 'Warning'; messages = @((& $leaf 'Tag x unused.'), (& $leaf 'Tag X unused.')) } }) }
        $c = (Invoke-Short 'compile').text | ConvertFrom-Json
        @($c.items[0].messages | ForEach-Object { $_.description }) -join '|' | Should Be 'Tag x unused.|Tag X unused.'
    }

    It 'counts no null as a value: no steps, no inner chain, no failed lines' {
        $short = Get-ShortResult 'background_open' ([ordered]@{ ok = $false; step = 'start'; steps = $null }) @{}
        $short.steps.count | Should Be 0
        $short = Get-ShortResult 'import' ([ordered]@{ ok = $false; error = [ordered]@{ type = 'T'; message = 'm'; inner = $null } }) @{}
        $short.error.Contains('inner') | Should Be $false
        $short = Get-ShortResult 'full_export' ([ordered]@{ ok = $true; parts = @(); failed = $null; removed = $null; details = @() }) @{}
        $short.Contains('failed') | Should Be $false
        $short.Contains('removed') | Should Be $false
    }

    It 'full_export: a failure without an exception keeps TIA''s messages, alike only when they are the same' {
        $f = { param($n, $m) [ordered]@{ name = $n; folder = 'F'; messages = [ordered]@{ state = 'Error'; messages = @([ordered]@{ path = $n; state = 'Error'; description = $m; messages = @() }) } } }
        $records = @(New-TestPartRecord 'blocks' 3 @((& $f 'B1' "Block 'B1' is inconsistent."), (& $f 'B2' "Block 'B2' is inconsistent."), (& $f 'B3' 'The know-how cannot be read.')))
        $script:TestResult = [ordered]@{ ok = $false; failedCount = 3; parts = @($records | ForEach-Object { Format-PartLine $_ })
                                         failed = @(Get-FullExportFailures $records | ForEach-Object { $_.text }); details = $records }
        $a = (Invoke-Short 'full_export').text | ConvertFrom-Json
        @($a.failed) -join '|' | Should Be 'blocks@PLC_1: F/B1: export state Error (+1 alike: F/B2)|blocks@PLC_1: F/B3: export state Error'
        @($a.failedErrors).Count | Should Be 2
        $a.failedErrors[0].object | Should Be 'blocks@PLC_1: F/B1'
        $a.failedErrors[0].messages.messages[0].description | Should Be "Block 'B1' is inconsistent."
        $a.failedErrors[1].messages.messages[0].description | Should Be 'The know-how cannot be read.'
    }

    It 'full_export: a part that could not be listed keeps its detail texts and inner chain' {
        $long = 'x' * 400
        $rec = New-TestPartRecord 'types' 0
        $rec.listError = [ordered]@{ type = 'Siemens.Engineering.EngineeringTargetInvocationException'; message = $long; details = @('detail of types')
                                     inner = @([ordered]@{ type = 'Inner.Type'; message = 'why not' }); at = 'at Get-X' }
        $records = @((New-TestPartRecord 'blocks' 1), $rec)
        $script:TestResult = [ordered]@{ ok = $false; failedCount = 1; parts = @($records | ForEach-Object { Format-PartLine $_ })
                                         failed = @(Get-FullExportFailures $records | ForEach-Object { $_.text }); details = $records }
        $a = (Invoke-Short 'full_export').text | ConvertFrom-Json
        @($a.failed).Count | Should Be 1
        $a.failed[0] | Should Match '^types@PLC_1: not listed: '
        $a.failedErrors[0].object | Should Be 'types@PLC_1: not listed'
        $a.failedErrors[0].error.message | Should Be $long
        $a.failedErrors[0].error.details[0] | Should Be 'detail of types'
        $a.failedErrors[0].error.inner[0].message | Should Be 'why not'
        $a.failedErrors[0].error.PSObject.Properties['at'] | Should BeNullOrEmpty
    }

    It 'import: an ok item that brought nothing in says so' {
        $script:TestResult = [ordered]@{ ok = $true; transaction = $true; rolledBack = $false; override = $false; items = @(
            [ordered]@{ name = 'A'; path = 'plc\blocks\A.s7dcl'; folder = ''; ok = $true; imported = @() }
            [ordered]@{ name = 'B'; path = 'plc\blocks\B.s7dcl'; folder = 'F'; ok = $true; imported = @('B') }) }
        $a = (Invoke-Short 'import').text | ConvertFrom-Json
        $a.items[0].PSObject.Properties['imported'] | Should Not BeNullOrEmpty
        @($a.items[0].imported).Count | Should Be 0
        $a.items[0].folder | Should Be ''
        $a.override | Should Be $false
        $a.rolledBack | Should Be $false
    }

    It 'compile: an item that is no dictionary is passed as it is, a list not unrolled' {
        $result = [ordered]@{ ok = $false; scope = 'plc'; errors = 0; items = @('a text item', @('x', 'y'), [ordered]@{ name = 'A'; ok = $true; errors = 0; warnings = 0 }) }
        $short = Get-ShortResult 'compile' $result @{}
        @($short.items).Count | Should Be 2
        $short.items[0] | Should Be 'a text item'
        @($short.items[1]) -join ',' | Should Be 'x,y'
        $short.cleanItems | Should Be 1
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

    It 'connect and background_open: the languages always said, one active language as a list, not known as it is' {
        foreach ($tool in 'connect', 'background_open') {
            $script:TestResult = [ordered]@{ ok = $true; languages = [ordered]@{ active = @('en-US'); editing = 'en-US'; reference = 'en-US' } }
            $a = (Invoke-Short $tool).text | ConvertFrom-Json
            $a.languages.active -is [array] | Should Be $true
            @($a.languages.active) -join ',' | Should Be 'en-US'
            $a.languages.editing | Should Be 'en-US'
            $a.languages.reference | Should Be 'en-US'
            $script:TestResult = [ordered]@{ ok = $true; languages = [ordered]@{ notKnown = 'TIA gave the project no LanguageSettings.' } }
            ((Invoke-Short $tool).text | ConvertFrom-Json).languages.notKnown | Should Be 'TIA gave the project no LanguageSettings.'
        }
    }

    It 'connect and background_open: the logs taken out of git''s index said as the result says it' {
        $said = 'logs\ is ignored by git from now on: 3 tracked files there left git''s index, kept on disk. The next commit records the removal; the history keeps the old logs.'
        foreach ($tool in 'connect', 'background_open') {
            $script:TestResult = [ordered]@{ ok = $true; logsIgnored = $said }
            ((Invoke-Short $tool).text | ConvertFrom-Json).logsIgnored | Should Be $said
        }
    }

    It 'change_report: a value is left out only where its absence says the same, every fact of a change stays, rows as JSON gives them' {
        # Invoke-ChangeReports returns what ConvertFrom-Json makes of TiaChangeReports' output: its rows are no dictionaries
        $res = @'
{"blocks": [{"name": "Main", "kind": "OB", "state": "changed", "interface": false, "properties": false,
             "networks": [{"state": "new", "lang": "LAD", "before": null, "after": 8, "title": ""}]},
            {"name": "Gone", "kind": "FB", "state": "removed", "interface": true, "properties": false, "networks": []}],
 "plcTags": [{"name": "Tags", "state": "changed", "counts": {"new": 1, "changed": 1},
              "rows": [{"kind": "tag", "name": "Hidden", "state": "new", "changes": [], "before": null,
                        "after": {"type": "Bool", "address": "%M0.0", "comment": "", "accessible": false, "writable": false, "visible": false}},
                       {"kind": "tag", "name": "Locked", "state": "changed", "changes": ["writable"],
                        "before": {"type": "Bool", "address": "%M0.1", "comment": "", "accessible": true, "writable": true, "visible": true},
                        "after": {"type": "Bool", "address": "%M0.1", "comment": "", "accessible": true, "writable": false, "visible": true}}]}],
 "hmi": [{"device": "", "kind": "graphic", "name": "Logo", "state": "new", "changes": 0}]}
'@ | ConvertFrom-Json
        $script:TestResult = @{ ok = $true; page = 'changes\reports\x.html'; before = 'r @ HEAD~1'; after = 'r @ HEAD'; blocks = @($res.blocks); plcTags = @($res.plcTags); hmi = @($res.hmi) }
        $d = Invoke-Short 'change_report'
        $a = $d.text | ConvertFrom-Json
        @($a.blocks).Count | Should Be 2
        @($a.blocks[0].PSObject.Properties.Name) -join ',' | Should Be 'name,kind,state,interface,properties,networks'
        $a.blocks[0].interface | Should Be $false
        @($a.blocks[0].networks[0].PSObject.Properties.Name) -join ',' | Should Be 'state,lang,after'
        @($a.blocks[1].networks).Count | Should Be 0
        $a.blocks[1].PSObject.Properties['networks'] | Should Not BeNullOrEmpty
        # an added tag no HMI can reach, and a tag made read-only: the false is the change
        $hidden, $locked = $a.plcTags[0].rows
        @($hidden.PSObject.Properties.Name) -join ',' | Should Be 'kind,name,state,changes,after'
        @($hidden.after.PSObject.Properties.Name) -join ',' | Should Be 'type,address,accessible,writable,visible'
        foreach ($k in 'accessible', 'writable', 'visible') { $hidden.after.$k | Should Be $false }
        $locked.after.writable | Should Be $false
        $locked.before.writable | Should Be $true
        @($a.hmi[0].PSObject.Properties.Name) -join ',' | Should Be 'kind,name,state,changes'
        $a.hmi[0].changes | Should Be 0
        $log = Read-CallLog $d
        $log.blocks[0].networks[0].PSObject.Properties['before'] | Should Not BeNullOrEmpty
        $log.hmi[0].device | Should Be ''
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
        # tia_status, asked by an agent unsure where it stands, says them always: a log's path is relative to the repo when there is one
        $st = (Invoke-Short 'tia_status').text | ConvertFrom-Json
        $st.project | Should Be 'P1'
        $st.repo | Should Be $script:TestRepo
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
        $script:TestResult = [ordered]@{ ok = $true; parts = @('a: 0/0, 0 s'); failed = @(); limits = @('x'); details = @((New-TestPartRecord 'a' 0)) }
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
