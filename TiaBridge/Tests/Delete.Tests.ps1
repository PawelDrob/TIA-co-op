$here = Split-Path -Parent $MyInvocation.MyCommand.Path
foreach ($f in 'Mcp.ps1', 'Tia.ps1', 'Repo.ps1', 'Rules.ps1', 'Guards.ps1', 'Bridge.ps1', 'Tools\Objects.ps1', 'Tools\Plc.ps1') { . (Join-Path $here "..\$f") }

# The delete tool: its guard for the test instance of a library type in work, and TIA ending during a delete.
# Stand-ins: a fake object kind, and Invoke-TiaWrite that runs the body and honours -RollbackIf like the real one.
if (-not ('FakeSiemens.NonRecoverableException' -as [type])) {
    Add-Type -TypeDefinition 'namespace FakeSiemens { public class NonRecoverableException : System.Exception { public NonRecoverableException(string m) : base(m) { } } }'
}
if (-not ('Siemens.Engineering.Library.Types.LibraryTypeInstanceInfo' -as [type])) {
    Add-Type -TypeDefinition 'namespace Siemens.Engineering.Library.Types { public class LibraryTypeInstanceInfo { } }'
}

function Get-KindRoot { 'root' }
function Get-TiaSoftwareList { @(@{ device = 'PLC_1'; kind = 'plc' }) }
function Test-TiaAlive { -not $script:tiaGone }
function Get-TiaService($Obj, [type]$Type) { $Obj.fakeInfo }
function Invoke-TiaWrite([string]$Description, [scriptblock]$Body, [switch]$NoTransaction, [scriptblock]$RollbackIf) {
    $script:writes++
    $out = @(& $Body)
    $rb = [bool]($RollbackIf -and (& $RollbackIf))
    $script:committed = -not $rb
    @{ output = $out; transaction = $true; rolledBack = $rb; commitError = $null; note = $null }
}

# An object of the fake kind. Fails: '' deletes it, 'plain' or 'ends' throw. InWork: the test instance of a type in work.
function New-FakeEntry([string]$Name, [string]$Fails = '', [switch]$InWork) {
    $info = $null
    if ($InWork) { $info = [pscustomobject]@{ LibraryTypeVersion = [pscustomobject]@{ TypeObject = [pscustomobject]@{ Name = 'Library_Notes' }; VersionNumber = [version]'0.0.2'; State = 'InWork' } } }
    $o = [pscustomobject]@{ Name = $Name; fails = $Fails; fakeInfo = $info }
    $o | Add-Member ScriptMethod Delete {
        $script:deleted += @($this.Name)
        if ($this.fails -eq 'plain') { throw [System.InvalidOperationException]::new('TIA said no') }
        if ($this.fails -eq 'ends') { throw [System.Management.Automation.MethodInvocationException]::new('outer', [FakeSiemens.NonRecoverableException]::new('Unexpected exception')) }
    }
    @{ name = $Name; folder = 'F'; obj = $o }
}

Register-ObjectKind 'fake' @{
    scope = 'plc'; dir = 'plc\fake'; defaultOverride = $true; description = 'test kind'
    items = { param($root) @($script:entries) }
}

function Invoke-FakeDelete([string[]]$Names, [switch]$Background, $Safety = $null, $Knowhow = $null) {
    Initialize-BridgeContext @{ maxResponseChars = 20000 }
    Set-BridgeProject -Name 'P' -Path 'C:\P.ap20' -Repo (Join-Path $TestDrive 'D')
    if ($Background) { $script:Bridge.background = @{ write = $true; session = (New-SessionState) } }
    Register-Archive (Get-BridgeSession)
    $script:deleted = @(); $script:writes = 0; $script:committed = $null
    Invoke-DeleteTool ([pscustomobject]@{ kind = 'fake'; names = $Names; safety = $Safety; knowhow = $Knowhow })
}

Describe 'delete of the test instance of a library type in work' {
    $script:entries = @((New-FakeEntry 'Instance' -InWork), (New-FakeEntry 'Plain'))

    It 'refuses it with the type and version, and never calls Delete on it (TIA would hold the call on a modal message)' {
        $r = Invoke-FakeDelete @('Instance')
        $r.ok | Should Be $false
        $r.items[0].refused | Should Match 'test instance of library type Library_Notes V 0.0.2, which is in work'
        $r.items[0].refused | Should Match 'cannot delete it'
        $r.items[0].refused | Should Not Match 'by import'
        @($script:deleted).Count | Should Be 0
    }

    It 'does not open a write when every name is refused' {
        $null = Invoke-FakeDelete @('Instance', 'Missing')
        $script:writes | Should Be 0
    }

    It 'counts no pending write for the refused object' {
        $null = Invoke-FakeDelete @('Instance')
        @((Get-BridgeSession).pending.Keys).Count | Should Be 0
    }

    It 'still deletes the others of the batch, as with a name that does not exist' {
        $r = Invoke-FakeDelete @('Instance', 'Plain')
        $r.ok | Should Be $false
        $r.items[0].refused | Should Match 'in work'
        $r.items[1].ok | Should Be $true
        $script:deleted -join ',' | Should Be 'Plain'
    }
}

Describe 'delete that ends TIA' {
    $script:entries = @((New-FakeEntry 'A'), (New-FakeEntry 'Ends' 'ends'), (New-FakeEntry 'Bad' 'plain'), (New-FakeEntry 'C'))

    It 'returns the TIA-ended result, stops at that object and refuses TIA calls until connect' {
        $r = Invoke-FakeDelete @('A', 'Ends', 'C')
        $r.ok | Should Be $false
        $r.tiaEnded | Should Be $true
        $r.kind | Should Be 'fake'
        $r.note | Should Match 'TIA Portal ended at Ends'
        $r.note | Should Match 'NonRecoverableException'
        $r.note | Should Match 'call connect'
        $r.items[0].lost | Should Be $true
        $r.items[1].error.tiaEnded | Should Be $true
        $r.items[2].notAttempted | Should Be $true
        $script:deleted -join ',' | Should Be 'A,Ends'
        { Get-TiaProject } | Should Throw 'call connect'
    }

    It 'does not try to commit on the TIA that is ending, and counts no pending write' {
        $null = Invoke-FakeDelete @('A', 'Ends')
        $script:committed | Should Be $false
        @((Get-BridgeSession).pending.Keys).Count | Should Be 0
    }

    It 'says so as well when TIA does not answer after a failure' {
        $script:tiaGone = $true
        try { $r = Invoke-FakeDelete @('A', 'Bad', 'C') } finally { $script:tiaGone = $false }
        $r.tiaEnded | Should Be $true
        $r.note | Should Match 'does not answer any more'
        $r.items[2].notAttempted | Should Be $true
        { Get-TiaProject } | Should Throw 'call connect'
    }

    It 'tells a background session to close and open again, and leaves the window session alone' {
        $r = Invoke-FakeDelete @('Ends') -Background
        $r.tiaEnded | Should Be $true
        $r.note | Should Match 'background_close, then background_open'
        $script:Bridge.tiaEnded | Should BeNullOrEmpty
    }

    It 'still reports a plain failure per item and goes on with the next name' {
        $r = Invoke-FakeDelete @('Bad', 'C')
        $r.Contains('tiaEnded') | Should Be $false
        $r.items[0].error.message | Should Be 'TIA said no'
        $r.items[1].ok | Should Be $true
        $script:committed | Should Be $true
        $script:Bridge.tiaEnded | Should BeNullOrEmpty
    }
}

Describe 'delete of F-blocks' {
    function New-Block([string]$Name, [string]$Language) {
        $e = New-FakeEntry $Name
        $e.obj | Add-Member NoteProperty ProgrammingLanguage $Language
        $e
    }
    $script:entries = @((New-Block 'Ffb' 'F_FBD'), (New-Block 'Fdb' 'F_DB'), (New-Block 'Std' 'LAD'))

    It 'refuses an F-block without safety, never calls Delete, and the other names go on' {
        $r = Invoke-FakeDelete @('Ffb', 'Std')
        $r.ok | Should Be $false
        $r.items[0].refused | Should Match 'F-block'
        $r.items[0].refused | Should Match 'safety: true'
        $r.items[1].ok | Should Be $true
        $script:deleted -join ',' | Should Be 'Std'
    }

    It 'opens no write when only F-blocks are named' {
        $r = Invoke-FakeDelete @('Ffb', 'Fdb')
        $r.ok | Should Be $false
        $script:writes | Should Be 0
    }

    It 'deletes them with safety: true' {
        $r = Invoke-FakeDelete @('Ffb', 'Fdb') -Safety $true
        $r.ok | Should Be $true
        $script:deleted -join ',' | Should Be 'Ffb,Fdb'
    }

    It 'takes the text false as no' {
        $null = Invoke-FakeDelete @('Ffb') -Safety 'false'
        @($script:deleted).Count | Should Be 0
    }
}

Describe 'delete of know-how protected blocks' {
    function New-Protected([string]$Name, [string]$Language = 'LAD') {
        $e = New-FakeEntry $Name
        $e.obj | Add-Member NoteProperty IsKnowHowProtected $true
        $e.obj | Add-Member NoteProperty ProgrammingLanguage $Language
        $e
    }
    $script:entries = @((New-Protected 'Khp'), (New-Protected 'Khp2'), (New-Protected 'FKhp' 'F_LAD'), (New-FakeEntry 'Std'))

    It 'refuses it without knowhow, says why, never calls Delete, and the other names go on' {
        $r = Invoke-FakeDelete @('Khp', 'Std')
        $r.ok | Should Be $false
        $r.items[0].refused | Should Match 'know-how protected'
        $r.items[0].refused | Should Match 'a project archive'
        $r.items[0].refused | Should Match 'unless it was skipped'
        $r.items[0].refused | Should Not Match 'only the session archive'
        $r.items[0].refused | Should Match 'knowhow: true'
        $r.items[0].refused | Should Match 'user asked'
        $r.items[1].ok | Should Be $true
        $script:deleted -join ',' | Should Be 'Std'
    }

    It 'opens no write and counts nothing pending when only such blocks are named' {
        $r = Invoke-FakeDelete @('Khp', 'Khp2')
        $r.ok | Should Be $false
        $script:writes | Should Be 0
        @((Get-BridgeSession).pending.Keys).Count | Should Be 0
    }

    It 'deletes it with knowhow: true' {
        $r = Invoke-FakeDelete @('Khp', 'Khp2') -Knowhow $true
        $r.ok | Should Be $true
        $script:deleted -join ',' | Should Be 'Khp,Khp2'
    }

    It 'takes the text false as no' {
        $null = Invoke-FakeDelete @('Khp') -Knowhow 'false'
        @($script:deleted).Count | Should Be 0
    }

    It 'safety: true does not lift it, and an F-block that is protected needs both flags' {
        (Invoke-FakeDelete @('Khp') -Safety $true).items[0].refused | Should Match 'knowhow: true'
        (Invoke-FakeDelete @('FKhp') -Knowhow $true).items[0].refused | Should Match 'safety: true'
        (Invoke-FakeDelete @('FKhp') -Safety $true).items[0].refused | Should Match 'knowhow: true'
        @($script:deleted).Count | Should Be 0
        (Invoke-FakeDelete @('FKhp') -Safety $true -Knowhow $true).ok | Should Be $true
        $script:deleted -join ',' | Should Be 'FKhp'
    }
}
