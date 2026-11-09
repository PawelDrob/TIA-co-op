$here = Split-Path -Parent $MyInvocation.MyCommand.Path
. (Join-Path $here '..\Tia.ps1')

Describe 'Select-TiaProject (connect without and with a name)' {
    $open = @(
        @{ processId = 11; name = 'PlantA'; path = 'C:\P\PlantA\PlantA.ap20' }
        @{ processId = 12; name = 'TiaBridgeTest'; path = 'C:\P\TiaBridgeTest\TiaBridgeTest.ap20' }
    )

    It 'picks the only open project when no name is given' {
        (Select-TiaProject -Open @($open[1]) -Requested '').name | Should Be 'TiaBridgeTest'
    }

    It 'refuses to guess between several open projects and lists them' {
        { Select-TiaProject -Open $open -Requested '' } | Should Throw 'PlantA, TiaBridgeTest'
    }

    It 'picks a project by name, case-insensitively, or by .ap20 path' {
        (Select-TiaProject -Open $open -Requested 'planta').processId | Should Be 11
        (Select-TiaProject -Open $open -Requested 'C:\P\TiaBridgeTest\TiaBridgeTest.ap20').processId | Should Be 12
    }

    It 'says so when no project is open, or the requested one is not' {
        { Select-TiaProject -Open @() -Requested '' } | Should Throw 'No TIA Portal with an open project'
        { Select-TiaProject -Open $open -Requested 'PlantB' } | Should Throw 'PlantB'
    }
}

Describe 'Get-OpennessMissingMessage (no TIA Portal V20 at tiaRoot)' {
    $siemens = Join-Path $TestDrive 'Siemens\Automation'

    It 'names V20 as required and lists the TIA Portal versions found beside tiaRoot' {
        New-Item -ItemType Directory -Force -Path (Join-Path $siemens 'Portal V19\PublicAPI\V19'), (Join-Path $siemens 'Portal V21\PublicAPI\V21') | Out-Null
        $m = Get-OpennessMissingMessage (Join-Path $siemens 'Portal V20')
        $m | Should Match '^TIA Portal V20 with TIA Openness required: .*Portal V20\\PublicAPI\\V20\\Siemens\.Engineering\.dll not found\.'
        $m | Should Match 'Portal V19 \(Openness V19\); .*Portal V21 \(Openness V21\)\.'
        $m | Should Match 'set tiaRoot in TiaBridge\\settings\.json'
    }

    It 'says when V20 is there without Openness, and when there is no TIA Portal at all' {
        New-Item -ItemType Directory -Force -Path (Join-Path $siemens 'Portal V20\Bin') | Out-Null
        Get-OpennessMissingMessage ((Join-Path $siemens 'Portal V20') + '\') | Should Match 'Portal V20 \(no Openness\)'
        Get-OpennessMissingMessage (Join-Path $TestDrive 'Nothing\Portal V20') | Should Match 'Found: no TIA Portal under .*Nothing\.'
    }

    It 'is the error of Import-Openness' {
        if ('Siemens.Engineering.TiaPortal' -as [type]) { return }   # loaded: Import-Openness returns at once
        { Import-Openness (Join-Path $siemens 'Portal V20') } | Should Throw 'TIA Portal V20 with TIA Openness required'
    }
}

Describe 'Invoke-TiaWrite' {
    . (Join-Path $here '..\Bridge.ps1')
    . (Join-Path $here '..\Mcp.ps1')
    function New-Disposable { $o = New-Object psobject; $o | Add-Member ScriptMethod Dispose { }; $o }
    function Get-TiaProject { $script:Bridge.project }
    $script:fakeSoftware = @()
    function Get-TiaSoftwareList { $script:fakeSoftware }
    function Get-OnlineProvider($Item) { if ($Item -and $Item.state) { @{ State = $Item.state } } }

    # stands in for TiaPortal.ExclusiveAccess(...).Transaction(...); the commit happens in the transaction's Dispose
    function Set-FakePortal([scriptblock]$TransactionDispose) {
        Initialize-BridgeContext @{ useTransactions = $true }
        $tx = New-Object psobject; $tx | Add-Member ScriptMethod CommitOnDispose { }; $tx | Add-Member ScriptMethod Dispose $TransactionDispose
        $ea = New-Disposable; $ea | Add-Member -NotePropertyName tx -NotePropertyValue $tx; $ea | Add-Member ScriptMethod Transaction { param($p, $t) $this.tx }
        $portal = New-Object psobject; $portal | Add-Member -NotePropertyName ea -NotePropertyValue $ea; $portal | Add-Member ScriptMethod ExclusiveAccess { param($t) $this.ea }
        $script:Bridge.portal = $portal; $script:Bridge.project = New-Object psobject
    }

    It 'runs the body in one committed transaction' {
        Set-FakePortal { }
        $w = Invoke-TiaWrite 'import' { 'done' }
        $w.output | Should Be 'done'
        $w.transaction | Should Be $true
        $w.commitError | Should BeNullOrEmpty
    }

    It 'rolls the transaction back without trying to commit when RollbackIf holds after the body' {
        $script:commitCalled = $false
        Set-FakePortal { }
        $script:Bridge.portal.ea.tx | Add-Member ScriptMethod CommitOnDispose { $script:commitCalled = $true } -Force
        $w = Invoke-TiaWrite 'import' { 'partly done' } -RollbackIf { $true }
        $w.rolledBack | Should Be $true
        $script:commitCalled | Should Be $false
    }

    It 'reports a failed commit instead of passing the batch as done, and marks the items rolled back' {
        Set-FakePortal { throw [System.InvalidOperationException]::new('commit refused') }
        $w = Invoke-TiaWrite 'import' { 'done' }
        $w.commitError.message | Should Be 'commit refused'
        $w.rolledBack | Should Be $true
        $items = @([ordered]@{ name = 'A'; ok = $true }, [ordered]@{ name = 'B'; ok = $false })
        Set-RolledBack $items
        $items[0].ok | Should Be $false
        $items[0].rolledBack | Should Be $true
    }

    # TIA ends after a NonRecoverableException: the dispatch has to see it (Set-TiaEnded), wherever in the write it comes
    if (-not ('FakeSiemens.NonRecoverableException' -as [type])) {
        Add-Type -TypeDefinition 'namespace FakeSiemens { public class NonRecoverableException : System.Exception { public NonRecoverableException(string m) : base(m) { } } }'
    }

    It 'throws a NonRecoverableException of the commit instead of reporting a rollback' {
        Set-FakePortal { throw [FakeSiemens.NonRecoverableException]::new('Unexpected exception') }
        { Invoke-TiaWrite 'import' { 'done' } } | Should Throw 'Unexpected exception'
    }

    It 'throws a NonRecoverableException of the rollback' {
        Set-FakePortal { throw [FakeSiemens.NonRecoverableException]::new('Unexpected exception') }
        { Invoke-TiaWrite 'import' { 'partly done' } -RollbackIf { $true } } | Should Throw 'Unexpected exception'
    }

    It 'throws a NonRecoverableException of opening the transaction instead of running without one' {
        Set-FakePortal { }
        $script:Bridge.portal.ea | Add-Member ScriptMethod Transaction { param($p, $t) throw [FakeSiemens.NonRecoverableException]::new('Unexpected exception') } -Force
        $script:bodyRan = $false
        { Invoke-TiaWrite 'import' { $script:bodyRan = $true } } | Should Throw 'Unexpected exception'
        $script:bodyRan | Should Be $false
    }

    It 'still runs without a transaction when opening one fails for another reason' {
        Set-FakePortal { }
        $script:Bridge.portal.ea | Add-Member ScriptMethod Transaction { param($p, $t) throw [System.InvalidOperationException]::new('no undo here') } -Force
        $w = Invoke-TiaWrite 'import' { 'done' }
        $w.output | Should Be 'done'
        $w.transaction | Should Be $false
        $w.note | Should Match 'no undo here'
    }

    # 2026-11-05: TIA online refused the transaction, the bridge wrote without one and returned ok
    It 'refuses the write when TIA refuses the transaction for online mode, and runs nothing' {
        Set-FakePortal { }
        $script:Bridge.portal.ea | Add-Member ScriptMethod Transaction { param($p, $t) throw [System.InvalidOperationException]::new('The operation is not permitted in online mode.') } -Force
        $script:fakeSoftware = @()
        $script:bodyRan = $false
        { Invoke-TiaWrite 'import' { $script:bodyRan = $true } } | Should Throw 'TIA is online: go offline first'
        $script:bodyRan | Should Be $false
    }

    It 'refuses the write when the transaction fails and a device reads online, whatever the words of the failure' {
        Set-FakePortal { }
        $script:Bridge.portal.ea | Add-Member ScriptMethod Transaction { param($p, $t) throw [System.InvalidOperationException]::new('Vorgang im Online-Betrieb nicht zulaessig') } -Force
        $script:fakeSoftware = @(@{ device = 'PLC_1'; kind = 'plc'; deviceItem = @{ state = 'Online' } }, @{ device = 'HMI_1'; kind = 'hmi'; deviceItem = $null })
        $script:bodyRan = $false
        $m = try { Invoke-TiaWrite 'import' { $script:bodyRan = $true }; '' } catch { $_.Exception.Message }
        $m | Should Match '^TIA is online: go offline first'
        $m | Should Match 'PLC_1'
        $m | Should Match 'Nothing was written'
        $script:bodyRan | Should Be $false
    }

    It 'refuses a write without transactions (useTransactions off) when a device reads online, and lets save and compile through' {
        Set-FakePortal { }
        $script:Bridge.settings.useTransactions = $false
        $script:fakeSoftware = @(@{ device = 'PLC_1'; kind = 'plc'; deviceItem = @{ state = 'Online' } })
        $script:bodyRan = $false
        { Invoke-TiaWrite 'import' { $script:bodyRan = $true } } | Should Throw 'TIA is online: go offline first. Online: PLC_1.'
        $script:bodyRan | Should Be $false
        (Invoke-TiaWrite 'save' -NoTransaction { 'saved' }).output | Should Be 'saved'
        $script:fakeSoftware = @(@{ device = 'PLC_1'; kind = 'plc'; deviceItem = @{ state = 'Offline' } })
        (Invoke-TiaWrite 'import' { 'done' }).output | Should Be 'done'
    }
}

Describe 'Get-DeviceStates (online state per device for connect and tia_status)' {
    function Write-BridgeLog([string]$Text) { }
    function Get-OnlineProvider($Item) { if ($Item -and $Item.state) { @{ State = $Item.state } } }

    It 'names each device with its kind and its online state, unknown where TIA offers none' {
        $d = @(Get-DeviceStates @(
            @{ device = 'PLC_1'; kind = 'plc'; deviceItem = @{ state = 'Online' } },
            @{ device = 'PLC_2'; kind = 'plc'; deviceItem = @{ state = 'Offline' } },
            @{ device = 'HMI_1'; kind = 'hmi'; deviceItem = @{} }))
        ($d | ForEach-Object { "$($_.device):$($_.kind):$($_.online)" }) -join ',' | Should Be 'PLC_1:plc:online,PLC_2:plc:offline,HMI_1:hmi:unknown'
    }

    It 'reads unknown when the state cannot be read, and does not fail' {
        function Get-OnlineProvider($Item) { throw [System.InvalidOperationException]::new('no service') }
        (Get-DeviceStates @(@{ device = 'PLC_1'; kind = 'plc'; deviceItem = @{} })).online | Should Be 'unknown'
    }
}

Describe 'Limit-ToolResponse with a note of the tool' {
    It 'keeps the note in a shortened response: a TIA-ended note must reach the agent' {
        $items = @(foreach ($i in 1..300) { @{ name = "Block$i"; ok = $true; messages = @(@{ description = 'y' * 400 }) } })
        $r = Limit-ToolResponse -Result @{ ok = $false; tiaEnded = $true; items = $items; note = 'TIA Portal ended at Block300. Ask the user to restart TIA.' } -MaxChars 8000 | ConvertFrom-Json
        $r.truncated | Should Be $true
        $r.tiaEnded | Should Be $true
        $r.note | Should Match 'TIA Portal ended at Block300'
        $r.note | Should Match 'Response shortened to 8000 chars'
    }
}

Describe 'Limit-ToolResponse with compile items' {
    It 'keeps the error and warning counts of a shortened compile item' {
        $tree = @{ state = 'Error'; messages = @(foreach ($i in 1..400) { @{ path = "x$i"; state = 'Warning'; description = 'w' * 80 } }) }
        $r = Limit-ToolResponse -Result @{ ok = $false; scope = 'plc'; errors = 3; items = @(@{ name = 'PLC software'; ok = $false; errors = 3; warnings = 55; messages = $tree }) } -MaxChars 3000 | ConvertFrom-Json
        $r.truncated | Should Be $true
        $r.items[0].errors | Should Be 3
        $r.items[0].warnings | Should Be 55
    }
}

Describe 'Limit-ToolResponse with list items' {
    It 'does not count items without an ok field (list results) as failed' {
        $items = @(foreach ($i in 1..300) { @{ name = "type$i"; folder = 'F'; versions = @(@{ version = '0.0.1'; state = 'Committed' }) } })
        $r = Limit-ToolResponse -Result @{ ok = $true; kind = 'library_type'; items = $items } -MaxChars 4000 | ConvertFrom-Json
        $r.failedCount | Should Be 0
        $r.items[0].PSObject.Properties.Name -contains 'ok' | Should Be $false
    }
}

Describe 'Limit-ToolResponse' {
    It 'returns a small result unchanged' {
        $json = Limit-ToolResponse -Result @{ ok = $true; items = @(@{ name = 'A'; ok = $true }) } -MaxChars 1000
        ($json | ConvertFrom-Json).items[0].name | Should Be 'A'
        ($json | ConvertFrom-Json).truncated | Should BeNullOrEmpty
    }

    It 'shortens a large result below the limit, names the log, and lists failed items first' {
        $items = @(foreach ($i in 1..300) { @{ name = "Block$i"; ok = $true; messages = @(@{ description = 'y' * 400 }) } })
        $items += @{ name = 'Broken'; ok = $false; error = @{ type = 'Siemens.X'; message = 'z' * 5000; details = @('d1', 'd2'); inner = @() } }
        $json = Limit-ToolResponse -Result @{ ok = $false; project = 'P'; items = $items; log = 'logs\x_import.json' } -MaxChars 8000
        $json.Length | Should BeLessThan 8001
        $r = $json | ConvertFrom-Json
        $r.truncated | Should Be $true
        $r.log | Should Be 'logs\x_import.json'
        $r.project | Should Be 'P'
        $r.items[0].name | Should Be 'Broken'
        $r.items[0].error.type | Should Be 'Siemens.X'
        $r.itemCount | Should Be 301
        $r.failedCount | Should Be 1
    }
}
