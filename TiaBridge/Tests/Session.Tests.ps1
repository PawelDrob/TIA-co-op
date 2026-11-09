$here = Split-Path -Parent $MyInvocation.MyCommand.Path
foreach ($f in 'Mcp.ps1', 'Tia.ps1', 'Repo.ps1', 'Rules.ps1', 'Guards.ps1', 'Bridge.ps1', 'Tools\Objects.ps1', 'Tools\Session.ps1') { . (Join-Path $here "..\$f") }
. (Join-Path $here 'TestBridge.ps1')

if (-not ('Siemens.Engineering.ProjectArchivationMode' -as [type])) {
    Add-Type -TypeDefinition 'namespace Siemens.Engineering { public enum ProjectArchivationMode { None, Compressed, DiscardRestorableData, DiscardRestorableDataAndCompressed } }'
}

if (-not ('FakeSiemens.NonRecoverableException' -as [type])) {
    Add-Type -TypeDefinition 'namespace FakeSiemens { public class NonRecoverableException : System.Exception { public NonRecoverableException(string m) : base(m) { } } }'
}

Describe 'archive tool' {
    $repo = Join-Path $TestDrive 'P'
    # stands in for Siemens.Engineering.Project: Archive writes the file, as Openness does
    $script:fakeProject = New-Object psobject -Property @{ IsModified = $false }
    $script:fakeProject | Add-Member ScriptMethod Archive { param($Dir, $Name, $Mode) Set-Content (Join-Path $Dir.FullName $Name) 'zap' }
    function Get-TiaProject { $script:fakeProject }

    It 'archives when called on its own, not only from connect' {
        Initialize-BridgeContext @{ projectsRoot = $TestDrive; archivesKept = 10; maxResponseChars = 20000 }
        Set-BridgeProject -Name 'P' -Path 'C:\P.ap20' -Repo $repo
        $saved = $script:TiaPathLimit
        try {
            $script:TiaPathLimit = Get-TestDrivePathLimit $saved     # $repo lies in $TestDrive
            $r = Invoke-ArchiveTool ('{"reason":"before refactor"}' | ConvertFrom-Json)
        }
        finally { $script:TiaPathLimit = $saved }
        $r.ok | Should Be $true
        $r.file | Should Match '^archives\\tia-co-op-P-\d{4}-\d{2}-\d{2}_\d{6}-before_refactor\.zap20$'
        Test-Path (Join-Path $repo $r.file) | Should Be $true
        Test-WriteAllowed (Get-BridgeSession) | Should BeNullOrEmpty
    }

    It 'names the session archive tia-co-op-<project>-<date>_<time> without a reason' {
        ConvertTo-ArchiveName -Project 'PlantA-Line-Area-00001' -Reason 'session' -At ([datetime]'2026-10-06 09:32:14') |
            Should Be 'tia-co-op-PlantA-Line-Area-00001-2026-10-06_093214.zap20'
        ConvertTo-ArchiveName -Project 'My Project' -Reason 'before refactor' -At ([datetime]'2026-10-06 09:32:14') |
            Should Be 'tia-co-op-My_Project-2026-10-06_093214-before_refactor.zap20'
    }

    It 'shortens the reason so the archive path stays within the 143 characters TIA allows (2026-10-06)' {
        $dir = 'C:\Users\someone\TIA-Projects\PlantA-Line-Area-00001\archives'
        $n = ConvertTo-ArchiveName -Project 'PlantA-Line-Area-00001' -Reason 'Session archive before the first HMI preview import' -At ([datetime]'2026-10-06 17:17:38') -Dir $dir
        ($dir.Length + 1 + $n.Length - '.zap20'.Length) | Should Not BeGreaterThan 143
        $n | Should Match '^tia-co-op-PlantA-Line-Area-00001-2026-10-06_171738-Session_archive_before_the_fir\w*\.zap20$'
    }

    It 'refuses to archive a project with unsaved changes, which TIA cannot archive, and keeps writes refused' {
        Initialize-BridgeContext @{ projectsRoot = $TestDrive; archivesKept = 10; maxResponseChars = 20000 }
        Set-BridgeProject -Name 'Q' -Path 'C:\Q.ap20' -Repo (Join-Path $TestDrive 'Q')
        $script:fakeProject.IsModified = $true
        try { { Invoke-ArchiveTool ('{"reason":"x"}' | ConvertFrom-Json) } | Should Throw 'unsaved changes' }
        finally { $script:fakeProject.IsModified = $false }
        @(Get-ChildItem (Join-Path $TestDrive 'Q\archives') -ErrorAction SilentlyContinue).Count | Should Be 0
        Test-WriteAllowed (Get-BridgeSession) | Should Match 'archive'
    }

    It 'without the session archive save is refused too, so the refusal asks the user and does not name save' {
        Initialize-BridgeContext @{ projectsRoot = $TestDrive; archivesKept = 10; maxResponseChars = 20000 }
        Set-BridgeProject -Name 'R' -Path 'C:\R.ap20' -Repo (Join-Path $TestDrive 'R')
        $script:fakeProject.IsModified = $true
        try {
            $m = try { Invoke-ArchiveTool ('{"reason":"x"}' | ConvertFrom-Json); '' } catch { $_.Exception.Message }
        } finally { $script:fakeProject.IsModified = $false }
        $m | Should Match 'unsaved changes'
        $m | Should Match 'Ask the user to save in TIA'
        $m | Should Match 'skip=true'
        $m | Should Not Match 'use save'
        $m | Should Not Match 'background'
    }

    It 'with the session archive made save works, so the refusal names it' {
        Initialize-BridgeContext @{ projectsRoot = $TestDrive; archivesKept = 10; maxResponseChars = 20000 }
        Set-BridgeProject -Name 'S' -Path 'C:\S.ap20' -Repo (Join-Path $TestDrive 'S')
        $null = Invoke-ArchiveTool ('{"reason":"session"}' | ConvertFrom-Json)
        $script:fakeProject.IsModified = $true
        try {
            $m = try { Invoke-ArchiveTool ('{"reason":"x"}' | ConvertFrom-Json); '' } catch { $_.Exception.Message }
        } finally { $script:fakeProject.IsModified = $false }
        $m | Should Match 'Use save'
        $m | Should Match 'the user'
        $m | Should Not Match 'clean compile'
    }

    It 'a skipped session archive lets save run too, so the refusal names it' {
        Initialize-BridgeContext @{ projectsRoot = $TestDrive; archivesKept = 10; maxResponseChars = 20000 }
        Set-BridgeProject -Name 'T' -Path 'C:\T.ap20' -Repo (Join-Path $TestDrive 'T')
        $null = Invoke-ArchiveTool ('{"reason":"the user said so","skip":true}' | ConvertFrom-Json)
        $script:fakeProject.IsModified = $true
        try {
            $m = try { Invoke-ArchiveTool ('{"reason":"x"}' | ConvertFrom-Json); '' } catch { $_.Exception.Message }
        } finally { $script:fakeProject.IsModified = $false }
        $m | Should Match 'Use save \(after a clean compile'
    }
}

Describe 'connect stores the HMI type identifier' {
    $root = Join-Path $TestDrive 'Projects'

    # Openness stand-ins: a device and its device items carry TypeIdentifier, as in TIA (where exactly is not probed yet)
    function New-FakeItem([string]$Name, [string]$TypeIdentifier, [object[]]$Items = @()) {
        New-Object psobject -Property @{ Name = $Name; TypeIdentifier = $TypeIdentifier; DeviceItems = @($Items) }
    }
    function Set-FakeTia([object[]]$Software) {
        Initialize-BridgeContext @{ projectsRoot = $root; archivesKept = 10; maxResponseChars = 20000 }
        $p = New-Object psobject -Property @{ Name = 'Hp'; Path = [System.IO.FileInfo]'C:\P\Hp\Hp.ap20'; IsModified = $false }
        $p | Add-Member ScriptMethod Archive { param($Dir, $Name, $Mode) Set-Content (Join-Path $Dir.FullName $Name) 'zap' }
        $script:fakeTiaProject = $p
        $script:fakeSoftware = $Software
    }
    function Import-Openness { }
    function Test-OpennessGroup { $script:groupRefusal }
    function Get-TiaProcesses { @{ processId = 1; name = 'Hp'; path = 'C:\P\Hp\Hp.ap20' } }
    function Connect-Tia { $script:attached++; $script:Bridge.project = $script:fakeTiaProject }
    $script:groupRefusal = $null
    function Reset-TiaConnection { }
    function Get-TiaProject { $script:fakeTiaProject }
    function Get-TiaSoftwareList { $script:fakeSoftware }
    function Read-Config { Get-Content (Join-Path $root 'Hp\tiabridge.json') -Raw | ConvertFrom-Json }
    function New-Hmi([string]$Name, [string]$OrderNumber) {
        New-FakeItem $Name 'System:Device.SIMATIC_HMI' @(
            (New-FakeItem 'Rack' 'System:Rack.Hmi'),
            (New-FakeItem "${Name}_RT" 'System:Rack.Hmi' @((New-FakeItem 'Panel' $OrderNumber))))
    }
    $plc = @{ device = 'PLC_1'; kind = 'plc'; deviceObject = (New-FakeItem 'PLC_1' 'OrderNumber:6ES7 515-2AM02-0AB0/V3.0') }

    It 'returns the standards of the repo only when it holds files' {
        Set-FakeTia @($plc)
        $r = Invoke-ConnectTool ('{"repo":"Hp-standards"}' | ConvertFrom-Json)
        $r.Contains('standards') | Should Be $false
        Set-Content (Join-Path $root 'Hp-standards\standards\style.md') 'ours'
        $r = Invoke-ConnectTool ('{"repo":"Hp-standards"}' | ConvertFrom-Json)
        @($r.standards.files) -join ',' | Should Be 'standards\style.md'
        $r.standards.use | Should Match 'Before you edit'
    }

    It 'copies the settings'' template into a new repo, and says so when it cannot' {
        Set-FakeTia @($plc)
        $template = Join-Path $TestDrive 'template'
        New-Item -ItemType Directory -Force -Path $template | Out-Null
        Set-Content (Join-Path $template 'zz.md') 'ours'
        $script:Bridge.settings.standardsTemplate = $template
        $r = Invoke-ConnectTool ('{"repo":"Hp-template"}' | ConvertFrom-Json)
        @($r.standards.files) -join ',' | Should Be 'standards\zz.md'
        $r.Contains('standardsNote') | Should Be $false
        Set-FakeTia @($plc)
        $script:Bridge.settings.standardsTemplate = Join-Path $TestDrive 'gone'
        $r = Invoke-ConnectTool ('{"repo":"Hp-gone"}' | ConvertFrom-Json)
        $r.standardsNote | Should Match 'no folder'
    }

    It 'names the online state of each device' {
        function Get-OnlineProvider($Item) { if ($Item.Name -eq 'PLC_1') { @{ State = 'Online' } } }
        Set-FakeTia @(@{ device = 'PLC_1'; kind = 'plc'; deviceObject = $plc.deviceObject; deviceItem = $plc.deviceObject })
        $r = Invoke-ConnectTool ('{"repo":"Hp-online"}' | ConvertFrom-Json)
        "$($r.devices[0].device):$($r.devices[0].online)" | Should Be 'PLC_1:online'
    }

    It 'warns on a switch to a project in a second TIA process' {
        Set-FakeTia @($plc)
        $script:Bridge.processId = 7; $script:Bridge.projectName = 'Other'; $script:Bridge.projectPath = 'C:\Other\Other.ap20'
        function Get-TiaProcesses { @(@{ processId = 7; name = 'Other'; path = 'C:\Other\Other.ap20' }, @{ processId = 1; name = 'Hp'; path = 'C:\P\Hp\Hp.ap20' }) }
        $r = Invoke-ConnectTool ('{"project":"Hp","repo":"Hp-second"}' | ConvertFrom-Json)
        $r.secondTia | Should Match 'second TIA process \(1\)'
        $r.secondTia | Should Match ([regex]::Escape('C:\Other\Other.ap20'))
        $r.switchedFrom | Should Be 'Other'
    }

    It 'does not warn on a first connect, or with the project before closed' {
        Set-FakeTia @($plc)
        (Invoke-ConnectTool ('{"repo":"Hp-first"}' | ConvertFrom-Json)).Contains('secondTia') | Should Be $false
        Set-FakeTia @($plc)
        $script:Bridge.processId = 7; $script:Bridge.projectName = 'Other'; $script:Bridge.projectPath = 'C:\Other\Other.ap20'
        function Get-TiaProcesses { @(@{ processId = 7; name = ''; path = '' }, @{ processId = 1; name = 'Hp'; path = 'C:\P\Hp\Hp.ap20' }) }
        (Invoke-ConnectTool ('{"project":"Hp","repo":"Hp-first"}' | ConvertFrom-Json)).Contains('secondTia') | Should Be $false
    }

    It 'reports a session archive that ended TIA as TIA ended, and refuses TIA calls until the next connect' {
        Set-FakeTia @($plc)
        $script:fakeTiaProject | Add-Member ScriptMethod Archive { param($Dir, $Name, $Mode) throw [System.Management.Automation.MethodInvocationException]::new('outer', [FakeSiemens.NonRecoverableException]::new('Unexpected exception')) } -Force
        $r = Invoke-ConnectTool ('{}' | ConvertFrom-Json)
        $r.ok | Should Be $false
        $r.tiaEnded | Should Be $true
        $r.archive.error.tiaEnded | Should Be $true
        $r.note | Should Match 'session archive'
        $r.note | Should Match 'call connect'
        $script:Bridge.tiaEnded | Should Match 'call connect'
    }

    It 'keeps a plain archive failure an ordinary failure, with the retry note' {
        Set-FakeTia @($plc)
        $script:fakeTiaProject | Add-Member ScriptMethod Archive { param($Dir, $Name, $Mode) throw 'disk full' } -Force
        function Test-TiaAlive { $true }
        $r = Invoke-ConnectTool ('{}' | ConvertFrom-Json)
        $r.ok | Should Be $true
        $r.ContainsKey('tiaEnded') | Should Be $false
        $r.note | Should Match 'retry archive'
        $script:Bridge.tiaEnded | Should BeNullOrEmpty
    }

    It 'never saves a modified project itself: its changes may be the user''s, so writes stay refused and it asks the user' {
        Set-FakeTia @(@{ device = 'PLC_1'; kind = 'plc' })
        function Test-TiaAlive { $true }
        $script:fakeTiaProject.IsModified = $true
        $script:fakeTiaProject | Add-Member NoteProperty saves 0
        $script:fakeTiaProject | Add-Member ScriptMethod Save { $this.saves++ }
        $r = Invoke-ConnectTool ('{}' | ConvertFrom-Json)
        $script:fakeTiaProject.saves | Should Be 0
        $r.ContainsKey('savedBeforeArchive') | Should Be $false
        $r.archive.ok | Should Be $false
        $r.archive.error.message | Should Match 'Ask the user to save in TIA'
        $r.note | Should Match 'ask the user to save it in TIA'
        $r.session.writesAllowed | Should Be $false
    }

    It 'drops the session keys of a device the project no longer has, and says so' {
        Set-FakeTia @($plc)
        $script:fakeTiaProject.IsModified = $true
        function Test-TiaAlive { $true }
        $repo = Join-Path $root 'Hp'
        Write-TextFile (Join-Path $repo '.tiabridge-session.json') '{ "pending": { "plc@gone:a": "plc@Gone:A", "plc@plc_1:b": "plc@PLC_1:B" }, "failed": { }, "compileErrors": { "hmi@Gone": true } }'
        $r = Invoke-ConnectTool ('{}' | ConvertFrom-Json)
        $r.droppedWrites | Should Match 'plc@Gone:A'
        $r.droppedWrites | Should Match 'hmi@Gone'
        $r.droppedWrites | Should Not Match 'PLC_1'
        (Test-SaveAllowed (Get-BridgeSession)) -join ' ' | Should Match 'plc@PLC_1:B'
        (Test-SaveAllowed (Get-BridgeSession)) -join ' ' | Should Not Match 'Gone'
        Remove-Item (Join-Path $repo '.tiabridge-session.json')
    }

    It 'says nothing of dropped keys when a project without unsaved changes clears them all' {
        Set-FakeTia @($plc)
        Write-TextFile (Join-Path $root 'Hp\.tiabridge-session.json') '{ "pending": { "plc@gone:a": "plc@Gone:A" }, "failed": { }, "compileErrors": { } }'
        $r = Invoke-ConnectTool ('{}' | ConvertFrom-Json)
        $r.ContainsKey('droppedWrites') | Should Be $false
        Remove-Item (Join-Path $root 'Hp\.tiabridge-session.json')
    }

    It 'writes the order number of the one HMI device, found on a device item, and keeps hmiDevices' {
        Set-FakeTia @($plc, @{ device = 'HMI_1'; kind = 'hmi'; deviceObject = (New-Hmi 'HMI_1' 'OrderNumber:6AV2 124-0MC01-0AX0/17.0.0.0') })
        $r = Invoke-ConnectTool ('{}' | ConvertFrom-Json)
        $r.ok | Should Be $true
        $cfg = Read-Config
        $cfg.hmiTypeIdentifier | Should Be 'OrderNumber:6AV2 124-0MC01-0AX0/17.0.0.0'
        @($cfg.hmiDevices) | Should Be @('HMI_1')
    }

    It 'keeps a startScreen that the user or an agent put into tiabridge.json' {
        $path = Join-Path $root 'Hp\tiabridge.json'
        $cfg = Get-Content $path -Raw | ConvertFrom-Json
        $cfg | Add-Member -NotePropertyName startScreen -NotePropertyValue '010 Overview'
        Set-Content $path (ConvertTo-Json $cfg)
        Set-FakeTia @($plc, @{ device = 'HMI_1'; kind = 'hmi'; deviceObject = (New-Hmi 'HMI_1' 'OrderNumber:6AV2 124-0MC01-0AX0/17.0.0.0') })
        $null = Invoke-ConnectTool ('{}' | ConvertFrom-Json)
        (Read-Config).startScreen | Should Be '010 Overview'
    }

    It 'writes a map device -> identifier for several HMI devices, a //Portrait suffix as it is' {
        Set-FakeTia @($plc,
            @{ device = 'HMI_1'; kind = 'hmi'; deviceObject = (New-Hmi 'HMI_1' 'OrderNumber:6AV2 124-0MC01-0AX0/17.0.0.0') },
            @{ device = 'HMI_2'; kind = 'hmi'; deviceObject = (New-FakeItem 'HMI_2' 'OrderNumber:6AV2 124-0GC01-0AX0/17.0.0.0//Portrait') })
        $null = Invoke-ConnectTool ('{}' | ConvertFrom-Json)
        $cfg = Read-Config
        $cfg.hmiTypeIdentifier.HMI_1 | Should Be 'OrderNumber:6AV2 124-0MC01-0AX0/17.0.0.0'
        $cfg.hmiTypeIdentifier.HMI_2 | Should Be 'OrderNumber:6AV2 124-0GC01-0AX0/17.0.0.0//Portrait'
        @($cfg.hmiDevices) | Should Be @('HMI_1', 'HMI_2')
        (Read-Config).startScreen | Should Be '010 Overview'
    }

    It 'connects when the identifier cannot be read, and keeps the one of the last connect' {
        # Openness throws on a disposed object: PowerShell 5.1 turns a throwing getter into $null, but enumerating
        # DeviceItems throws through
        if (-not ('TiaBridgeTest.DisposedDevice' -as [type])) {
            Add-Type -TypeDefinition ('namespace TiaBridgeTest { public class DisposedDevice { public string Name { get { return "HMI_1"; } } ' +
                'public string TypeIdentifier { get { throw new System.InvalidOperationException("Access to a disposed object"); } } ' +
                'public System.Collections.Generic.IEnumerable<object> DeviceItems { get { return Items(); } } ' +
                'System.Collections.Generic.IEnumerable<object> Items() { if (Name.Length > 0) { throw new System.InvalidOperationException("Access to a disposed object"); } yield break; } } }')
        }
        Set-FakeTia @($plc, @{ device = 'HMI_1'; kind = 'hmi'; deviceObject = (New-Object TiaBridgeTest.DisposedDevice) },
                            @{ device = 'HMI_2'; kind = 'hmi'; deviceObject = (New-FakeItem 'HMI_2' 'System:Device.SIMATIC_HMI') })
        $ErrorActionPreference = 'Stop'   # as in TiaBridge.ps1
        $r = Invoke-ConnectTool ('{}' | ConvertFrom-Json)
        $r.ok | Should Be $true
        $cfg = Read-Config
        $cfg.hmiTypeIdentifier.HMI_1 | Should Be 'OrderNumber:6AV2 124-0MC01-0AX0/17.0.0.0'
        $cfg.hmiTypeIdentifier.HMI_2 | Should Be 'OrderNumber:6AV2 124-0GC01-0AX0/17.0.0.0//Portrait'
    }

    It 'refuses without git on PATH, before it attaches to TIA' {
        Set-FakeTia @($plc)
        $script:attached = 0
        $saved = $env:PATH
        try {
            $env:PATH = "$env:SystemRoot\System32"
            $r = Invoke-ConnectTool ('{}' | ConvertFrom-Json)
        } finally { $env:PATH = $saved }
        $r.ok | Should Be $false
        $r.refused | Should Match 'git not found on PATH'
        $script:attached | Should Be 0
    }

    It 'refuses without the Openness group, before it attaches to TIA' {
        Set-FakeTia @($plc)
        $script:attached = 0
        $script:groupRefusal = "The Windows user X is not in the group 'Siemens TIA Openness'"
        try { $r = Invoke-ConnectTool ('{}' | ConvertFrom-Json) } finally { $script:groupRefusal = $null }
        $r.ok | Should Be $false
        $r.refused | Should Match "not in the group 'Siemens TIA Openness'"
        $script:attached | Should Be 0
    }

    It 'reads a session file with the old keys for every device of the scope, when the project has unsaved changes' {
        Set-FakeTia @($plc, @{ device = 'PLC_2'; kind = 'plc'; deviceObject = (New-FakeItem 'PLC_2' 'OrderNumber:6ES7 515-2AM02-0AB0/V3.0') })
        $script:fakeTiaProject.IsModified = $true
        Write-TextFile (Join-Path $root 'Hp\.tiabridge-session.json') '{ "pending": { "plc:a": "plc:A" }, "failed": { }, "compileErrors": { } }'
        (Invoke-ConnectTool ('{}' | ConvertFrom-Json)).ok | Should Be $true
        @((Get-BridgeSession).pending.Values | Sort-Object) -join ',' | Should Be 'plc@PLC_1:A,plc@PLC_2:A'
    }

    Context 'a session record that cannot be read' {
        $file = Join-Path $root 'Hp\.tiabridge-session.json'
        $damaged = '{"failed":'

        It 'refuses writes and saves with unsaved changes, and says what ends it, the archive refusal too' {
            Set-FakeTia @($plc)
            $script:fakeTiaProject.IsModified = $true
            Write-TextFile $file $damaged
            $r = Invoke-ConnectTool ('{}' | ConvertFrom-Json)
            $r.ok | Should Be $true
            $r.session.writesAllowed | Should Be $false
            $r.session.recordUnreadable | Should Match 'ask the user to save in TIA'
            $r.session.saveBlockers -join ' ' | Should Match '\.tiabridge-session\.json'
            $r.ContainsKey('recordReset') | Should Be $false
            $r.archive.error.message | Should Match 'ask the user to save in TIA'
            $r.archive.error.message | Should Not Match 'Use save'
            $r.note | Should Not Match 'skip'
            $r.note | Should Match 'recordUnreadable'
            Remove-Item $file
        }

        It 'refuses on a name that is no name in the old keys, with the way out, where connect failed' {
            Set-FakeTia @($plc)
            $script:fakeTiaProject.IsModified = $true
            Write-TextFile $file '{ "pending": { "plc:x": null }, "failed": { }, "compileErrors": { } }'
            $r = Invoke-ConnectTool ('{}' | ConvertFrom-Json)
            $r.ok | Should Be $true
            $r.session.recordUnreadable | Should Match 'ask the user to save in TIA'
            $script:fakeTiaProject.IsModified = $false
            (Invoke-ConnectTool ('{}' | ConvertFrom-Json)).session.writesAllowed | Should Be $true
            Remove-Item $file
        }

        It 'refuses on a write still marked as underway, naming it, and ends when the user saved in TIA' {
            Set-FakeTia @($plc)
            $script:fakeTiaProject.IsModified = $true
            Write-TextFile $file '{ "pending": { }, "failed": { }, "compileErrors": { }, "writeUnderway": "import" }'
            $r = Invoke-ConnectTool ('{}' | ConvertFrom-Json)
            $r.session.writesAllowed | Should Be $false
            $r.session.recordUnreadable | Should Match 'call of import'
            $r.session.recordUnreadable | Should Match 'ask the user to save in TIA'
            $r.session.saveBlockers -join ' ' | Should Match 'call of import'
            $script:fakeTiaProject.IsModified = $false
            $r = Invoke-ConnectTool ('{}' | ConvertFrom-Json)
            $r.recordReset | Should Match 'no unsaved changes'
            $r.session.writesAllowed | Should Be $true
            Remove-Item $file
        }

        It 'refuses when only a temporary file is left, and ends when the user deleted it' {
            Set-FakeTia @($plc)
            $script:fakeTiaProject.IsModified = $true
            $left = Join-Path $root 'Hp\.tiabridge-session.json.4711.tmp'
            Write-TextFile $left '{ "pending": { }, "failed": { "plc@plc_1:a": "plc@PLC_1:A" }, "compileErrors": { } }'
            $r = Invoke-ConnectTool ('{}' | ConvertFrom-Json)
            $r.session.writesAllowed | Should Be $false
            $r.session.recordUnreadable | Should Match 'json\.4711\.tmp'
            Remove-Item $left
            (Invoke-ConnectTool ('{}' | ConvertFrom-Json)).session.ContainsKey('recordUnreadable') | Should Be $false
        }

        It 'ends when the user saved in TIA and connect comes again' {
            Set-FakeTia @($plc)
            $script:fakeTiaProject.IsModified = $true
            Write-TextFile $file $damaged
            $null = Invoke-ConnectTool ('{}' | ConvertFrom-Json)
            $script:fakeTiaProject.IsModified = $false
            $r = Invoke-ConnectTool ('{}' | ConvertFrom-Json)
            $r.recordReset | Should Match 'no unsaved changes'
            $r.session.writesAllowed | Should Be $true
            $r.session.ContainsKey('recordUnreadable') | Should Be $false
            @($r.session.saveBlockers).Count | Should Be 0
            Remove-Item $file
        }

        It 'ends at the first connect when the project has no unsaved changes' {
            Set-FakeTia @($plc)
            Write-TextFile $file $damaged
            $r = Invoke-ConnectTool ('{}' | ConvertFrom-Json)
            $r.recordReset | Should Match 'no unsaved changes'
            $r.session.writesAllowed | Should Be $true
            Remove-Item $file
        }

        It 'connect reads a repaired file again, and keeps what it names' {
            Set-FakeTia @($plc)
            $script:fakeTiaProject.IsModified = $true
            Write-TextFile $file $damaged
            $null = Invoke-ConnectTool ('{}' | ConvertFrom-Json)
            Write-TextFile $file '{ "pending": { }, "failed": { "plc@plc_1:a": "plc@PLC_1:A" }, "compileErrors": { } }'
            $r = Invoke-ConnectTool ('{}' | ConvertFrom-Json)
            $r.session.ContainsKey('recordUnreadable') | Should Be $false
            $r.session.saveBlockers -join ' ' | Should Match 'plc@PLC_1:A'
            Remove-Item $file
        }

        It 'a file the user deleted is no record at the next connect' {
            Set-FakeTia @($plc)
            $script:fakeTiaProject.IsModified = $true
            Write-TextFile $file $damaged
            $null = Invoke-ConnectTool ('{}' | ConvertFrom-Json)
            Remove-Item $file
            $r = Invoke-ConnectTool ('{}' | ConvertFrom-Json)
            $r.session.ContainsKey('recordUnreadable') | Should Be $false
            $r.ContainsKey('recordReset') | Should Be $false
        }

        It 'still refuses at the next connect while the file stays damaged and the project unsaved' {
            Set-FakeTia @($plc)
            $script:fakeTiaProject.IsModified = $true
            Write-TextFile $file $damaged
            $null = Invoke-ConnectTool ('{}' | ConvertFrom-Json)
            (Invoke-ConnectTool ('{}' | ConvertFrom-Json)).session.writesAllowed | Should Be $false
            Remove-Item $file
        }
    }

    It 'writes no identifier for an HMI device that never had one' {
        Remove-Item (Join-Path $root 'Hp\tiabridge.json')
        Set-FakeTia @($plc, @{ device = 'HMI_1'; kind = 'hmi'; deviceObject = (New-FakeItem 'HMI_1' 'System:Device.SIMATIC_HMI') })
        (Invoke-ConnectTool ('{}' | ConvertFrom-Json)).ok | Should Be $true
        (Read-Config).PSObject.Properties.Name -contains 'hmiTypeIdentifier' | Should Be $false
    }
}

Describe 'archive names and rotation' {
    It 'shortens a project that leaves the path over the limit, and keeps the time' {
        $at = [datetime]'2026-01-01 12:00:00'
        $dir = 'C:\' + ('x' * 70)
        $n = ConvertTo-ArchiveName -Project ('P' * 80) -Reason 'session' -At $at -Dir $dir
        (Join-Path $dir ($n -replace '\.zap20$', '')).Length | Should Be 143
        $n | Should Match '^tia-co-op-P+-2026-01-01_120000\.zap20$'
        Get-ArchiveStamp $n | Should Be '20260101120000'
    }

    It 'leaves out the project and the reason when only the time fits' {
        $at = [datetime]'2026-01-01 12:00:00'
        $n = ConvertTo-ArchiveName -Project 'Plant' -Reason 'before' -At $at -Dir ('C:\' + ('x' * 120))
        $n | Should Be 'tia-co-op--2026-01-01_120000.zap20'
        Get-ArchiveStamp $n | Should Be '20260101120000'
    }

    It 'shortens the reason the same with or without a backslash at the end of the folder' {
        $at = [datetime]'2026-01-01 12:00:00'
        $dir = 'C:\' + ('x' * 100)
        $plain = ConvertTo-ArchiveName -Project 'P' -Reason ('r' * 40) -At $at -Dir $dir
        ConvertTo-ArchiveName -Project 'P' -Reason ('r' * 40) -At $at -Dir "$dir\" | Should Be $plain
        (Join-Path $dir ($plain -replace '\.zap20$', '')).Length | Should Be 143
    }

    It 'archivesKept 0 keeps the archive just made, which the session gate counts' {
        $script:fakeProject = New-Object psobject -Property @{ IsModified = $false }
        $script:fakeProject | Add-Member ScriptMethod Archive { param($Dir, $Name, $Mode) Set-Content (Join-Path $Dir.FullName $Name) 'zap' }
        function Get-TiaProject { $script:fakeProject }
        Initialize-BridgeContext @{ projectsRoot = $TestDrive; archivesKept = 0; maxResponseChars = 20000 }
        Set-BridgeProject -Name 'Keep0' -Path 'C:\Keep0.ap20' -Repo (Join-Path $TestDrive 'Keep0')
        $r = Invoke-ArchiveTool ('{"reason":"x"}' | ConvertFrom-Json)
        $r.ok | Should Be $true
        @($r.removed).Count | Should Be 0
        @(Get-ChildItem (Join-Path $TestDrive 'Keep0\archives') -Filter *.zap20).Count | Should Be 1
    }
}
