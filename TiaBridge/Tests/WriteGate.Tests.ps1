# The archive gate in the dispatch (Bridge.ps1): every write tool is refused until the session archive exists, and
# every registered tool is classified, so a new tool fails this file until it is in $script:WriteTools or
# $script:ReadTools.
$here = Split-Path -Parent $MyInvocation.MyCommand.Path
foreach ($f in 'Mcp.ps1', 'Tia.ps1', 'Repo.ps1', 'Rules.ps1', 'Bridge.ps1') { . (Join-Path $here "..\$f") }

# What is wrong with the classification of these registered tools; empty when each is in exactly one list and each
# listed tool is registered.
function Get-ClassificationProblems([string[]]$Registered, [string[]]$Write = $script:WriteTools, [string[]]$Read = $script:ReadTools) {
    foreach ($t in $Registered) {
        $in = @($Write -contains $t) + @($Read -contains $t) | Where-Object { $_ }
        if (@($in).Count -eq 0) { "$t is in neither the write list nor the read list: add it to `$script:WriteTools or `$script:ReadTools in Bridge.ps1" }
        if (@($in).Count -gt 1) { "$t is in both the write list and the read list" }
    }
    foreach ($t in @($Write) + @($Read)) { if ($Registered -notcontains $t) { "$t is listed but not registered" } }
}

# A started bridge, as Claude Code sees it, without a project: the JSON responses to the requests, by id.
function Invoke-StartedBridge([string]$Root, [string[]]$Requests) {
    $settings = Join-Path $Root 'settings.json'
    Set-Content $settings (ConvertTo-Json @{ projectsRoot = (Join-Path $Root 'p') })
    $out = $Requests | & "$env:SystemRoot\System32\WindowsPowerShell\v1.0\powershell.exe" -NoProfile -STA -ExecutionPolicy Bypass -File (Join-Path $here '..\TiaBridge.ps1') -SettingsPath $settings 2>$null
    $byId = @{}
    foreach ($line in @($out | Where-Object { $_ })) { $r = $line | ConvertFrom-Json; $byId[[int]$r.id] = $r }
    $byId
}

function Initialize-GateBridge([string]$Root) {
    Initialize-BridgeContext @{ projectsRoot = $Root; maxResponseChars = 20000 }
    Set-BridgeProject -Name 'P' -Path 'C:\P.ap20' -Repo (Join-Path $Root 'P')
}

Describe 'tool classification' {
    # the real tools and the real dispatch: tools/list, then a call of every write tool
    $requests = @('{"jsonrpc":"2.0","id":0,"method":"tools/list"}')
    $i = 0
    foreach ($t in $script:WriteTools) { $i++; $requests += '{"jsonrpc":"2.0","id":' + $i + ',"method":"tools/call","params":{"name":"' + $t + '","arguments":{}}}' }
    $responses = Invoke-StartedBridge $TestDrive $requests
    $registered = @($responses[0].result.tools | ForEach-Object { $_.name })

    It 'reads the registered tools from a started bridge' {
        $registered -contains 'import' | Should Be $true
        $registered -contains 'tia_status' | Should Be $true
    }

    It 'has every registered tool in exactly one list' {
        @(Get-ClassificationProblems $registered) -join '; ' | Should BeNullOrEmpty
    }

    It 'refuses every write tool on a started bridge without a project' {
        foreach ($n in 1..$script:WriteTools.Count) {
            ($responses[$n].result.content[0].text | ConvertFrom-Json).refused | Should Match 'call connect'
        }
    }

    It 'fails for a tool in no list, in both lists, or listed but not registered' {
        @(Get-ClassificationProblems (@($registered) + 'some_new_tool')) -join '; ' | Should Match 'some_new_tool is in neither'
        @(Get-ClassificationProblems $registered -Write ($script:WriteTools + 'list')) -join '; ' | Should Match 'list is in both'
        @(Get-ClassificationProblems @($registered | Where-Object { $_ -ne 'import' })) -join '; ' | Should Match 'import is listed but not registered'
    }
}

Describe 'a session record that cannot be read, in the dispatch' {
    function Initialize-DamagedBridge([string]$Root) {
        Write-TextFile (Join-Path $Root 'P\.tiabridge-session.json') '{"failed":'
        Initialize-GateBridge $Root
        Register-Archive (Get-BridgeSession)
    }

    foreach ($tool in $script:WriteTools) {
        It "refuses $tool with the archive made, without running the handler" {
            Initialize-DamagedBridge $TestDrive
            $script:ran = $false
            $d = Invoke-BridgeTool $tool { param($a) $script:ran = $true; @{ ok = $true } } (New-Object psobject)
            $script:ran | Should Be $false
            $d.result.refused | Should Match '\.tiabridge-session\.json'
        }
    }

    foreach ($tool in 'list', 'export', 'compile', 'archive', 'tia_status') {
        It "runs $tool" {
            Initialize-DamagedBridge $TestDrive
            (Invoke-BridgeTool $tool { param($a) @{ ok = $true } } (New-Object psobject)).result.ok | Should Be $true
        }
    }

    It 'leaves the damaged file for the next bridge process, which refuses too' {
        Initialize-DamagedBridge $TestDrive
        $null = Invoke-BridgeTool 'list' { param($a) @{ ok = $true } } (New-Object psobject)
        [System.IO.File]::ReadAllText((Join-Path $TestDrive 'P\.tiabridge-session.json')) | Should Be '{"failed":'
        Initialize-GateBridge $TestDrive
        Register-Archive (Get-BridgeSession)
        (Invoke-BridgeTool 'save' { param($a) @{ ok = $true } } (New-Object psobject)).result.refused | Should Match '\.tiabridge-session\.json'
    }
}

Describe 'a session record that could not be stored' {
    It 'says so in the result, and the next call stores it' {
        Initialize-GateBridge $TestDrive
        $file = Join-Path $TestDrive 'P\.tiabridge-session.json'
        $null = Invoke-BridgeTool 'list' { param($a) @{ ok = $true } } (New-Object psobject)
        $held = [System.IO.File]::Open($file, 'Open', 'Read', 'Read')
        try {
            $d = Invoke-BridgeTool 'list' { param($a) Register-Write (Get-BridgeSession) -Scope plc -Device PLC_1 -Items @(@{ name = 'Broken'; ok = $false }); @{ ok = $true } } (New-Object psobject)
        }
        finally { $held.Dispose() }
        $d.result.recordNotStored | Should Match 'restart'
        $d.result.recordNotStored | Should Not Match 'The file holds'
        $d.result.recordNotStored | Should Match 'with that record gone, refuses'
        $d.result.recordNotStored | Should Match 'can record one is marked'
        (Invoke-BridgeTool 'list' { param($a) @{ ok = $true } } (New-Object psobject)).result.ContainsKey('recordNotStored') | Should Be $false
        [System.IO.File]::ReadAllText($file) | Should Match 'plc@PLC_1:Broken'
    }

    function New-RecordRoot { Join-Path $TestDrive ([guid]::NewGuid().ToString('N')) }

    # A store that fails after the write has run: the handler takes hold of the file once the bridge has passed it.
    function Invoke-WriteNotStored([string]$Root) {
        $script:recordFile = Join-Path $Root 'P\.tiabridge-session.json'
        $script:held = $null
        try {
            Invoke-BridgeTool 'import' {
                param($a)
                Register-Write (Get-BridgeSession) -Scope plc -Device PLC_1 -Items @(@{ name = 'Broken'; ok = $false })
                $script:held = [System.IO.File]::Open($script:recordFile, 'Open', 'Read', 'Read')
                @{ ok = $false }
            } (New-Object psobject)
        }
        finally { if ($script:held) { $script:held.Dispose() } }
    }
    function Initialize-ArchivedBridge([string]$Root) {
        Initialize-GateBridge $Root
        Register-Archive (Get-BridgeSession)
    }

    It 'a restart after a write it could not store refuses writes and saves, naming that write' {
        $root = New-RecordRoot
        Initialize-ArchivedBridge $root
        $null = Invoke-BridgeTool 'list' { param($a) @{ ok = $true } } (New-Object psobject)
        (Invoke-WriteNotStored $root).result.recordNotStored | Should Match 'restart'
        Initialize-ArchivedBridge $root
        $s = Get-BridgeSession
        Test-WriteAllowed $s | Should Match 'import'
        (Test-SaveAllowed $s) -join ' ' | Should Match 'import'
    }

    It 'the refusal names the failed writes the record holds from before that write, and takes none of them' {
        $root = New-RecordRoot
        Initialize-ArchivedBridge $root
        $null = Invoke-BridgeTool 'list' { param($a) Register-Write (Get-BridgeSession) -Scope plc -Device PLC_1 -Items @(@{ name = 'Older'; ok = $false }); @{ ok = $true } } (New-Object psobject)
        $null = Invoke-WriteNotStored $root
        Initialize-ArchivedBridge $root
        $s = Get-BridgeSession
        Test-WriteAllowed $s | Should Match 'plc@PLC_1:Older'
        $s.failed.Count | Should Be 0
    }

    It 'a restart after the next store reads the whole record: the failed write, and no refusal' {
        $root = New-RecordRoot
        Initialize-ArchivedBridge $root
        $null = Invoke-BridgeTool 'list' { param($a) @{ ok = $true } } (New-Object psobject)
        $null = Invoke-WriteNotStored $root
        $null = Invoke-BridgeTool 'list' { param($a) @{ ok = $true } } (New-Object psobject)
        Initialize-ArchivedBridge $root
        $s = Get-BridgeSession
        Test-WriteAllowed $s | Should BeNullOrEmpty
        (Test-SaveAllowed $s) -join ' ' | Should Match 'plc@PLC_1:Broken'
    }

    It 'a bridge that stops during a write leaves a record that refuses, naming that write' {
        $root = New-RecordRoot
        Initialize-ArchivedBridge $root
        $script:recordRepo = Join-Path $root 'P'
        $script:readDuring = $null
        $null = Invoke-BridgeTool 'library_update_usages' {
            param($a)
            $script:readDuring = New-SessionState     # what a restart at this moment reads
            Restore-SessionWrites $script:recordRepo $script:readDuring
            @{ ok = $true }
        } (New-Object psobject)
        $script:readDuring.unreadable | Should Match 'library_update_usages'
        $script:readDuring.failed.Count | Should Be 0
        Initialize-ArchivedBridge $root
        Test-WriteAllowed (Get-BridgeSession) | Should BeNullOrEmpty    # the call ended and was stored: nothing stands
    }

    It 'a bridge that stops during a call of a read tool leaves the record as it was' {
        $root = New-RecordRoot
        Initialize-ArchivedBridge $root
        $script:recordRepo = Join-Path $root 'P'
        $script:readDuring = $null
        $null = Invoke-BridgeTool 'compile' {
            param($a)
            $script:readDuring = New-SessionState
            Restore-SessionWrites $script:recordRepo $script:readDuring
            @{ ok = $true }
        } (New-Object psobject)
        $script:readDuring.unreadable | Should BeNullOrEmpty
    }

    It 'a background session in write mode does not touch the window session''s record' {
        $root = New-RecordRoot
        Initialize-GateBridge $root
        $file = Join-Path $root 'P\.tiabridge-session.json'
        Write-TextFile $file '{"pending":{},"failed":{},"compileErrors":{}}'
        $session = New-SessionState
        Register-Archive $session
        $script:Bridge.background = @{ write = $true; processId = 0; steps = (New-Object System.Collections.ArrayList); session = $session }
        $script:readFile = $file
        $script:during = $null
        $null = Invoke-BridgeTool 'import' { param($a) $script:during = [System.IO.File]::ReadAllText($script:readFile); @{ ok = $true } } (New-Object psobject)
        $script:during | Should Be '{"pending":{},"failed":{},"compileErrors":{}}'
    }

    It 'refuses a write it cannot mark in the record, without running the handler, and runs it once it can' {
        $root = New-RecordRoot
        Initialize-ArchivedBridge $root
        $file = Join-Path $root 'P\.tiabridge-session.json'
        $null = Invoke-BridgeTool 'list' { param($a) @{ ok = $true } } (New-Object psobject)
        $script:ran = $false
        $held = [System.IO.File]::Open($file, 'Open', 'Read', 'Read')
        try { $d = Invoke-BridgeTool 'import' { param($a) $script:ran = $true; @{ ok = $true } } (New-Object psobject) }
        finally { $held.Dispose() }
        $script:ran | Should Be $false
        $d.result.ok | Should Be $false
        $d.result.refused | Should Match 'session record'
        $d.result.refused | Should Match 'import'
        (Invoke-BridgeTool 'import' { param($a) $script:ran = $true; @{ ok = $true } } (New-Object psobject)).result.ok | Should Be $true
        $script:ran | Should Be $true
    }

    # What a restart during the call reads, from a bridge with an archive.
    function Get-RecordDuringCall([string]$Tool) {
        $root = New-RecordRoot
        Initialize-ArchivedBridge $root
        $script:recordRepo = Join-Path $root 'P'
        $script:readDuring = $null
        $null = Invoke-BridgeTool $Tool {
            param($a)
            $script:readDuring = New-SessionState
            Restore-SessionWrites $script:recordRepo $script:readDuring
            @{ ok = $true }
        } (New-Object psobject)
        $script:readDuring
    }

    # Neither can record a failed write, so the record from before them is sound.
    foreach ($tool in 'save', 'delete_folder') {
        It "a bridge that stops during $tool leaves a record that does not refuse" {
            (Get-RecordDuringCall $tool).unreadable | Should BeNullOrEmpty
        }

        It "$tool runs while the record cannot be stored, and says it was not stored" {
            $root = New-RecordRoot
            Initialize-ArchivedBridge $root
            $file = Join-Path $root 'P\.tiabridge-session.json'
            $null = Invoke-BridgeTool 'list' { param($a) @{ ok = $true } } (New-Object psobject)
            $script:ran = $false
            $held = [System.IO.File]::Open($file, 'Open', 'Read', 'Read')
            try { $d = Invoke-BridgeTool $tool { param($a) $script:ran = $true; @{ ok = $true } } (New-Object psobject) }
            finally { $held.Dispose() }
            $script:ran | Should Be $true
            $d.result.ok | Should Be $true
            $d.result.recordNotStored | Should Match 'restart'
        }
    }

    # By the list of all write tools, so that a new one is here without a line for it.
    foreach ($tool in @($script:WriteTools | Where-Object { 'save', 'delete_folder' -notcontains $_ })) {
        It "$tool is marked in the record while it runs" {
            (Get-RecordDuringCall $tool).unreadable | Should Match $tool
        }
    }
}

Describe 'archive gate in the dispatch' {
    foreach ($tool in $script:WriteTools) {
        It "refuses $tool before the session archive, without running the handler" {
            Initialize-GateBridge $TestDrive
            $script:ran = $false
            $d = Invoke-BridgeTool $tool { param($a) $script:ran = $true; @{ ok = $true } } (New-Object psobject)
            $script:ran | Should Be $false
            $d.result.ok | Should Be $false
            $d.result.refused | Should Match 'session archive'
        }

        It "runs $tool once the archive exists, and once it was skipped" {
            Initialize-GateBridge $TestDrive
            Register-Archive (Get-BridgeSession)
            (Invoke-BridgeTool $tool { param($a) @{ ok = $true } } (New-Object psobject)).result.ok | Should Be $true
            Initialize-GateBridge $TestDrive
            Register-Archive (Get-BridgeSession) -Skipped
            (Invoke-BridgeTool $tool { param($a) @{ ok = $true } } (New-Object psobject)).result.ok | Should Be $true
        }

        It "refuses $tool when no project is connected, without running the handler" {
            Initialize-BridgeContext @{ projectsRoot = $TestDrive; maxResponseChars = 20000 }
            $script:ran = $false
            $d = Invoke-BridgeTool $tool { param($a) $script:ran = $true; @{ ok = $true } } (New-Object psobject)
            $script:ran | Should Be $false
            $d.result.refused | Should Match 'call connect'
        }

        It "holds a background session in write mode to the gate for $tool, and runs it once its archive exists" {
            Initialize-GateBridge $TestDrive
            $session = New-SessionState
            $script:Bridge.background = @{ write = $true; processId = 0; steps = (New-Object System.Collections.ArrayList); session = $session }
            (Invoke-BridgeTool $tool { param($a) @{ ok = $true } } (New-Object psobject)).result.refused | Should Match 'session archive'
            Register-Archive $session
            (Invoke-BridgeTool $tool { param($a) @{ ok = $true } } (New-Object psobject)).result.ok | Should Be $true
        }
    }

    foreach ($tool in $script:ReadTools) {
        It "runs $tool before the session archive" {
            Initialize-GateBridge $TestDrive
            (Invoke-BridgeTool $tool { param($a) @{ ok = $true } } (New-Object psobject)).result.ok | Should Be $true
        }
    }

    It 'runs a read tool with no project connected: the handler says what it needs' {
        Initialize-BridgeContext @{ projectsRoot = $TestDrive; maxResponseChars = 20000 }
        (Invoke-BridgeTool 'connect' { param($a) @{ ok = $true } } (New-Object psobject)).result.ok | Should Be $true
    }
}
