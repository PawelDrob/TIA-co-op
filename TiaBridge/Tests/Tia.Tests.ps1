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

    # an import of project texts or alarm classes: TIA refuses it inside a transaction, so none is opened
    It 'opens no transaction for a write outside one, and refuses it when a device reads online' {
        Set-FakePortal { }
        $script:Bridge.portal.ea | Add-Member ScriptMethod Transaction { param($p, $t) $script:txOpened = $true } -Force
        $script:txOpened = $false
        $script:fakeSoftware = @(@{ device = 'PLC_1'; kind = 'plc'; deviceItem = @{ state = 'Offline' } })
        $w = Invoke-TiaWrite 'import' -OutsideTransaction { 'done' }
        $w.output | Should Be 'done'
        $w.transaction | Should Be $false
        $script:txOpened | Should Be $false
        $script:fakeSoftware = @(@{ device = 'PLC_1'; kind = 'plc'; deviceItem = @{ state = 'Online' } })
        $script:bodyRan = $false
        { Invoke-TiaWrite 'import' -OutsideTransaction { $script:bodyRan = $true } } | Should Throw 'TIA is online: go offline first. Online: PLC_1.'
        $script:bodyRan | Should Be $false
    }

    # it has no refusal of TIA's own behind the bridge's, as a transaction has: a state not read as offline refuses it
    It 'refuses a write outside a transaction unless every device reads offline, and says what is left for each state' {
        Set-FakePortal { }
        $script:bodyRan = $false
        $head = 'This write has no undo, as TIA runs it without a transaction, so the bridge runs it only while every device reads offline. Nothing was written.'
        $inTia = 'Until then the bridge does not import project texts or alarm classes: tell the user they can change them in TIA.'
        # a device TIA gives no state for: never offline, so the user is told what is left to them
        $script:fakeSoftware = @(@{ device = 'PLC_1'; kind = 'plc'; deviceItem = @{ state = 'Offline' } }, @{ device = 'HMI_1'; kind = 'hmi'; deviceItem = $null })
        $m = try { Invoke-TiaWrite 'import' -OutsideTransaction { $script:bodyRan = $true }; '' } catch { $_.Exception.Message }
        $m | Should Be "$head TIA gives no online state for HMI_1, and whether it ever does for such a device was not probed: while it gives none, this write is refused. $inTia"
        # a state on its way: wait, or go offline
        $script:fakeSoftware = @(@{ device = 'PLC_1'; kind = 'plc'; deviceItem = @{ state = 'Connecting' } })
        $m = try { Invoke-TiaWrite 'import' -OutsideTransaction { $script:bodyRan = $true }; '' } catch { $_.Exception.Message }
        $m | Should Be "$head PLC_1 reads connecting: wait until it reads offline, or ask the user to go offline in TIA, then call this again."
        # both at once: each is told
        $script:fakeSoftware = @(@{ device = 'PLC_1'; kind = 'plc'; deviceItem = @{ state = 'Connecting' } }, @{ device = 'HMI_1'; kind = 'hmi'; deviceItem = $null })
        $m = try { Invoke-TiaWrite 'import' -OutsideTransaction { $script:bodyRan = $true }; '' } catch { $_.Exception.Message }
        $m | Should Be "$head TIA gives no online state for HMI_1, and whether it ever does for such a device was not probed: while it gives none, this write is refused. $inTia PLC_1 reads connecting: wait until it reads offline, or ask the user to go offline in TIA, then call this again."
        # states that cannot be read
        function Get-TiaSoftwareList { throw 'the device list could not be read' }
        $m = try { Invoke-TiaWrite 'import' -OutsideTransaction { $script:bodyRan = $true }; '' } catch { $_.Exception.Message }
        $m | Should Be "$head The devices' online states could not be read (the device list could not be read): while they cannot be read, this write is refused. $inTia"
        $script:bodyRan | Should Be $false
        # a write in a transaction keeps TIA's own refusal behind the bridge's: an unknown state does not refuse it
        $script:fakeSoftware = @(@{ device = 'HMI_1'; kind = 'hmi'; deviceItem = $null })
        Remove-Item Function:\Get-TiaSoftwareList -ErrorAction SilentlyContinue
        $script:Bridge.settings.useTransactions = $false
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

# The bridge attaches from an MTA thread, so TIA can change a list while the bridge reads it. The Openness client then throws
# InvalidOperationException from MoveNext of its Siemens.Engineering.Internal.EngineeringEnumerator; this stand-in does the
# same, a given number of times, and reads through a PowerShell foreach as the bridge does.
if (-not ('Siemens.Engineering.Internal.FakeTiaList' -as [type])) {
    Add-Type -TypeDefinition @'
using System; using System.Collections; using System.Collections.Generic;
namespace Siemens.Engineering.Internal {
    public sealed class EngineeringEnumerator<T> : IEnumerator<T> {
        public static int Changes; public static bool Disposed;
        readonly T[] items; int i = -1;
        public EngineeringEnumerator(T[] items) { this.items = items; }
        public T Current { get { return items[i]; } }
        object IEnumerator.Current { get { return items[i]; } }
        public bool MoveNext() {
            if (Disposed) throw new ObjectDisposedException("list");
            i++;
            if (i == 1 && Changes > 0) { Changes--; throw new InvalidOperationException("Collection was modified; enumeration operation may not execute."); }
            return i < items.Length;
        }
        public void Reset() { i = -1; }
        public void Dispose() { }
    }
    public sealed class FakeTiaList : IEnumerable<string> {
        readonly string[] items;
        public FakeTiaList(string[] items) { this.items = items; }
        public IEnumerator<string> GetEnumerator() { return new EngineeringEnumerator<string>(items); }
        IEnumerator IEnumerable.GetEnumerator() { return GetEnumerator(); }
    }
}
'@
}

Describe 'Read-TiaList' {
    function Write-BridgeLog { }
    $fake = [Siemens.Engineering.Internal.EngineeringEnumerator[string]]
    function Set-Fake([int]$Changes, [bool]$Disposed = $false) { $fake::Changes = $Changes; $fake::Disposed = $Disposed; $script:n = 0 }
    $list = [Siemens.Engineering.Internal.FakeTiaList]::new([string[]]@('a', 'b', 'c'))

    It 'reads again when TIA changed the list meanwhile, and gives only the last whole read' {
        Set-Fake 2
        $r = @(Read-TiaList { $script:n++; foreach ($x in $list) { $x } })
        $script:n | Should Be 3
        ($r -join ',') | Should Be 'a,b,c'
    }

    It 'gives up after three reads and throws the change' {
        Set-Fake 5
        { Read-TiaList { $script:n++; foreach ($x in $list) { $x } } } | Should Throw
        $script:n | Should Be 3
    }

    It 'reads again only in the outermost of nested reads, so three reads stay the bound' {
        Set-Fake 5
        { Read-TiaList { Read-TiaList { $script:n++; foreach ($x in $list) { $x } } } } | Should Throw
        $script:n | Should Be 3
    }

    It 'knows the change by where it was thrown, not by its text: the same text from another list is thrown at once' {
        Set-Fake 0
        $own = New-Object System.Collections.Generic.List[string]; $own.Add('x'); $own.Add('y')
        { Read-TiaList { $script:n++; foreach ($x in $own) { $own.Add('z') } } } | Should Throw
        $script:n | Should Be 1
    }

    It 'reads once and throws any other error, a disposed list too' {
        Set-Fake 0 $true
        { Read-TiaList { $script:n++; foreach ($x in $list) { $x } } } | Should Throw
        $script:n | Should Be 1
        Set-Fake 0
        { Read-TiaList { $script:n++; throw [InvalidOperationException]::new('Collection was modified; enumeration operation may not execute.') } } | Should Throw
        $script:n | Should Be 1
    }
}

Describe 'Test-TiaAlive in the times of a full_export' {
    It 'gives the read of the project''s name to tia_alive and the look for TIA''s process to process_lookup' {
        $ticksPerMs = [System.Diagnostics.Stopwatch]::Frequency / 1000
        $project = New-Object psobject
        $project | Add-Member ScriptProperty Name ({ [TiaBridgeTimes]::TestTicks += [long](5 * $ticksPerMs); 'P' }.GetNewClosure())
        $script:Bridge = @{ project = $project; processId = $PID }
        Mock Get-Process { [TiaBridgeTimes]::TestTicks += [long](7 * $ticksPerMs); New-Object psobject }
        [TiaBridgeTimes]::TestTicks = 0
        Start-ExportTimes
        try {
            Test-TiaAlive | Should Be $true
            $t = Stop-ExportTimes
        }
        finally { Stop-ExportTimesClock }
        "$($t.once.steps.tia_alive.ms) $($t.once.steps.process_lookup.ms) $($t.tiaMs)" | Should Be '5 7 5'
    }
}

Describe 'Get-TiaProject asks TIA once in a call' {
    function New-AliveProject {
        $script:nameReads = 0; $script:lookups = 0
        $project = New-Object psobject
        $project | Add-Member ScriptProperty Name { $script:nameReads++; 'P' }
        $script:Bridge = @{ projectPath = 'C:\P\P.ap20'; project = $project; processId = $PID; portal = $null; software = $null; background = $null; tiaEnded = $null }
    }
    Mock Get-Process { $script:lookups++; if ($script:processGone) { throw 'gone' }; New-Object psobject }

    It 'looks for TIA''s process at the first path of a call, not at every path after it' {
        New-AliveProject
        foreach ($i in 1..4) { $null = Get-TiaProject }
        "$script:nameReads $script:lookups" | Should Be '1 1'
    }

    It 'asks again once the connection was reset' {
        New-AliveProject
        $null = Get-TiaProject
        $project = $script:Bridge.project
        Reset-TiaConnection
        $script:Bridge.project = $project; $script:Bridge.processId = $PID
        $null = Get-TiaProject
        $script:lookups | Should Be 2
    }

    It 'keeps a yes for the project it was asked for: another project bound in the call asks again' {
        New-AliveProject
        $null = Get-TiaProject
        $script:Bridge.project = [pscustomobject]@{ Name = 'Other' }
        (Get-TiaProject).Name | Should Be 'Other'
        $script:lookups | Should Be 2
    }

    It 'gives no project once none is bound, though TIA answered before in the call' {
        New-AliveProject
        $script:Bridge.background = @{ processId = $PID }
        $null = Get-TiaProject
        $script:Bridge.project = $null
        { Get-TiaProject } | Should Throw 'background_close'
    }

    It 'keeps no "no": after TIA did not answer, the next path asks again' {
        New-AliveProject
        $script:Bridge.background = @{ processId = $PID }
        $script:processGone = $true
        try { { Get-TiaProject } | Should Throw 'background_close' } finally { $script:processGone = $false }
        $null = Get-TiaProject
        $script:lookups | Should Be 2
    }

    It 'asks again after Test-TiaAlive found TIA gone, even after a yes before it in the call' {
        New-AliveProject
        $script:Bridge.background = @{ processId = $PID }
        $null = Get-TiaProject
        $script:processGone = $true
        try {
            Test-TiaAlive | Should Be $false
            { Get-TiaProject } | Should Throw 'background_close'
        }
        finally { $script:processGone = $false }
    }
}
