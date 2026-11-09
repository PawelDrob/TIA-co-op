# What a real run on TIA showed: UpdateProject removes instances without a word; the chain and types never released;
# a type in work again on a change still open.
$here = Split-Path -Parent $MyInvocation.MyCommand.Path
foreach ($f in 'Mcp.ps1', 'Tia.ps1', 'Repo.ps1', 'Rules.ps1', 'Guards.ps1', 'Bridge.ps1', 'Tools\Objects.ps1', 'Tools\Plc.ps1', 'Tools\Library.ps1', 'Tools\LibraryChange.ps1') {
    . (Join-Path $here "..\$f")
}
if (-not ('Siemens.Engineering.Library.Types.DeleteUnusedVersionsMode' -as [type])) {
    Add-Type -TypeDefinition @'
namespace Siemens.Engineering.Library.Types {
    public interface ILibraryTypeOrFolderSelection { }
    public class FakeTypeSelection : ILibraryTypeOrFolderSelection { }
    public enum DeleteUnusedVersionsMode { DoNotDelete }
    public enum UpdateCheckMode { ReportOutOfDateOnly }
}
'@
}

Describe 'Invoke-ProjectUpdate' {
    # The PLC holds blocks and data types. An update takes those $script:swept names, whatever is selected.
    function Get-TiaSoftwareList { @(@{ kind = 'plc'; device = 'Plc1'; software = [pscustomobject]@{ BlockGroup = 'b'; TypeGroup = 't' } }) }
    function Get-GroupTree { param($Root, $Items, $Groups)
        if ($Root -eq 'b') { $script:blocks | ForEach-Object { @{ name = $_; obj = [pscustomobject]@{ Name = $_; Number = $script:numbers[$_] }; folder = 'f' } } }
        elseif ($Root -eq 't') { $script:udts | ForEach-Object { @{ name = $_; obj = [pscustomobject]@{ Name = $_ }; folder = '' } } }
    }
    function Get-LibraryLink { param($Obj) if ($script:links[$Obj.Name]) { @{ type = $script:links[$Obj.Name]; version = '0.0.1'; inWork = $false } } }
    function Find-LibraryType { param($Library, $Name) $script:selected += @($Name); @{ name = $Name; obj = [Siemens.Engineering.Library.Types.FakeTypeSelection]::new() } }
    function Invoke-TiaWrite { param($Description, $Body, $RollbackIf)
        $script:writes++
        $b = @($script:blocks); $u = @($script:udts)
        $null = & $Body
        if ($script:commitRefused) { $script:blocks = $b; $script:udts = $u; return @{ transaction = $true; rolledBack = $true; commitError = @{ message = 'no commit' } } }
        @{ transaction = $script:hasTransaction; rolledBack = $false }
    }
    function Reset-Fake {
        $script:blocks = @('Called', 'Unused', 'Plain'); $script:udts = @('UnusedUdt'); $script:numbers = @{ Called = 1; Unused = 2; Plain = 3 }
        $script:links = @{ Called = 'TCalled'; Unused = 'TUnused'; UnusedUdt = 'TUdt' }; $script:swept = @()
        $script:hasTransaction = $true; $script:commitRefused = $false; $script:writes = 0; $script:updates = 0; $script:selected = @()
    }
    $library = [pscustomobject]@{ TypeFolder = [Siemens.Engineering.Library.Types.FakeTypeSelection]::new() }
    $update = { param($selection)
        $script:updates++
        $script:blocks = @($script:blocks | Where-Object { $script:swept -notcontains $_ })
        $script:udts = @($script:udts | Where-Object { $script:swept -notcontains $_ })
    }

    It 'says nothing when nothing goes' {
        Reset-Fake
        $r = Invoke-ProjectUpdate $library @('TCalled') $update 'u'
        @($r.removed).Count | Should Be 0
        $script:updates | Should Be 1
    }
    It 'lets TIA remove them, once, and names each with its type, version, folder and number' {
        Reset-Fake
        $script:swept = @('Unused', 'UnusedUdt')
        $r = Invoke-ProjectUpdate $library @('TCalled') $update 'u'
        $script:updates | Should Be 1
        $script:writes | Should Be 1
        $script:blocks -contains 'Unused' | Should Be $false
        @($r.removed).Count | Should Be 2
        $u = @($r.removed | Where-Object { $_.object -eq 'Unused' })[0]
        $u.type | Should Be 'TUnused'; $u.version | Should Be '0.0.1'; $u.folder | Should Be 'f'; $u.number | Should Be 2; $u.device | Should Be 'Plc1'
        @($r.removed | Where-Object { $_.object -eq 'UnusedUdt' })[0].number | Should Be $null
    }
    It 'names a type not selected too, and works on all types' {
        Reset-Fake
        $script:swept = @('Unused')
        @((Invoke-ProjectUpdate $library @() $update 'u').removed | ForEach-Object { $_.object }) | Should Be 'Unused'
        @($script:selected).Count | Should Be 0
    }
    It 'names one with no library link, should TIA ever take one' {
        Reset-Fake
        $script:swept = @('Plain')
        $r = Invoke-ProjectUpdate $library @('TCalled') $update 'u'
        @($r.removed)[0].object | Should Be 'Plain'
        @($r.removed)[0].type | Should Be $null
    }
    It 'names what went also without a transaction' {
        Reset-Fake
        $script:hasTransaction = $false; $script:swept = @('Unused')
        @((Invoke-ProjectUpdate $library @('TCalled') $update 'u').removed)[0].object | Should Be 'Unused'
    }
    It 'names nothing when TIA refuses the commit, as nothing was kept' {
        Reset-Fake
        $script:commitRefused = $true; $script:swept = @('Unused')
        $r = Invoke-ProjectUpdate $library @('TCalled') $update 'u'
        @($r.removed).Count | Should Be 0
        $r.commitError.message | Should Be 'no commit'
        $script:blocks -contains 'Unused' | Should Be $true
    }
}

Describe 'Add-UpdateFacts and what TIA removed' {
    $one = @{ object = 'U'; type = 'TU'; version = '0.0.1'; device = 'P'; folder = 'f'; number = 7 }
    It 'adds nothing when the update said nothing' {
        $r = @{ summary = 's'; ok = $true }
        Add-UpdateFacts $r @{ transaction = $true; removed = @() } @{ archived = $true }
        $r.summary | Should Be 's'
        $r.ok | Should Be $true
        $r.Contains('instancesRemoved') | Should Be $false
    }
    It 'names object and type, stays ok, and says the session archive is the way back' {
        $r = @{ summary = 's'; ok = $true }
        Add-UpdateFacts $r @{ removed = @($one) } @{ archived = $true }
        $r.ok | Should Be $true
        @($r.instancesRemoved)[0].object | Should Be 'U'
        @($r.instancesRemoved)[0].type | Should Be 'TU'
        $r.summary | Should Match 'TIA removed 1 from the PLC'
        $r.summary | Should Match 'U \(type TU 0\.0\.1, folder f\)'
        $r.summary | Should Match 'as its own window does'
        $r.summary | Should Match 'session archive is the way back'
    }
    It 'leaves out what an object does not have, so a data type shows no empty number' {
        $r = @{ summary = 's'; ok = $true }
        Add-UpdateFacts $r @{ removed = @(@{ object = 'V'; type = 'TV'; version = '0.0.1'; device = 'P'; folder = ''; number = $null }) } @{ archived = $true }
        @($r.instancesRemoved)[0].Contains('number') | Should Be $false
        ($r.instancesRemoved | ConvertTo-Json -Depth 3) | Should Not Match '\{\s*\}'
    }
    It 'says what is left as a way back without an archive' {
        $r = @{ summary = 's'; ok = $true }
        Add-UpdateFacts $r @{ removed = @($one) } @{ archived = $false; archiveSkipped = $true }
        $r.summary | Should Match 'no archive: closing without saving'
    }
    It 'says when the update did not reach the project' {
        $r = @{ summary = 's'; ok = $true }
        Add-UpdateFacts $r @{ refused = 'no' } @{ archived = $true }
        $r.ok | Should Be $false
        $r.updateRefused | Should Be 'no'
    }
    It 'takes back the writes under the name of what is gone, not the update itself' {
        $s = New-SessionState
        Register-Write $s -Scope 'plc' -Device 'P' -Items @(@{ name = 'type:TU'; ok = $true }, @{ name = 'U'; ok = $true }, @{ name = 'library update'; ok = $true }, @{ name = 'type:Other'; ok = $true })
        Register-RemovedInstances $s @{ removed = @($one) }
        @($s.pending.Values | Sort-Object) -join ',' | Should Be 'plc@P:library update,plc@P:type:Other'
    }
}

Describe 'Test-NeverReleased' {
    It 'tells a type with only a version in work' {
        Test-NeverReleased @([pscustomobject]@{ State = 'InWork' }) | Should Be $true
        Test-NeverReleased @([pscustomobject]@{ State = 'Committed' }, [pscustomobject]@{ State = 'InWork' }) | Should Be $false
    }
}

Describe 'Update-ChangeInWork, a type in work again after its release' {
    function New-Record {
        @{ root = 'A'; types = [ordered]@{
            A = @{ inWork = '0.0.2'; inWorkBy = 'change'; releasedAs = '0.0.2'; released = '0.0.1'; approved = $false; review = $null }
            B = @{ inWork = '0.0.2'; inWorkBy = 'tia'; releasedAs = '0.0.2'; released = '0.0.1'; approved = $true; review = @{ verdict = 'reference-only' } } } }
    }
    It 'goes through review and approval again' {
        $r = New-Record
        Update-ChangeInWork $r @(@{ type = 'B'; inWork = '0.0.3' }) 'bridge'
        $r.types.B.releasedAs | Should Be ''
        $r.types.B.inWork | Should Be '0.0.3'
        $r.types.B.released | Should Be '0.0.2'
        $r.types.B.approved | Should Be $false
        $r.types.B.review | Should Be $null
        $r.types.B.inWorkBy | Should Be 'bridge'
    }
    It 'leaves a released type on the same number alone, and the changed type too' {
        $r = New-Record
        Update-ChangeInWork $r @(@{ type = 'B'; inWork = '0.0.2' }, @{ type = 'A'; inWork = '0.0.3' }) 'tia'
        $r.types.B.releasedAs | Should Be '0.0.2'
        $r.types.A.releasedAs | Should Be '0.0.2'
    }
}

Describe 'Register-ChangeOnEdit, the changed type edited again after its release' {
    function New-Graph { @{ complete = $true; graph = @{ A = @(); B = @('A') } } }
    function Get-ChangeTypeInfo { param($Library, $Names) @($Names | ForEach-Object { @{ name = $_; class = 'PlcTypeLibraryType'; folder = ''; released = '0.0.2'; inWork = '' } }) }
    function Test-ChangeAlive { $true }
    function Add-LibraryLog { }

    It 'closes the old change as superseded and starts a new one' {
        $script:Bridge = @{ repo = [string]$TestDrive; settings = @{} }
        $old = New-ChangeRecord -Root 'A' -From '0.0.1' -To '0.0.2' -Types @(@{ name = 'A'; class = 'PlcTypeLibraryType'; folder = ''; released = '0.0.1'; inWork = '0.0.2' }, @{ name = 'B'; class = 'PlcTypeLibraryType'; folder = ''; released = '0.0.1'; inWork = '' }) -Levels @{ A = 0; B = 1 } -At ([datetime]'2026-11-03 10:00')
        $old.types.A.releasedAs = '0.0.2'
        $null = Save-ChangeRecord $TestDrive $old
        $r = Register-ChangeOnEdit $null @{ name = 'A' } '0.0.2' '0.0.3' (New-Graph) @('B')
        $r.joined | Should Be $false
        $r.id | Should Not Be $old.id
        (Read-ChangeRecord $TestDrive $old.id).status | Should Be 'superseded'
    }
    # an id holds the minute only: both records in one minute, whatever the clock does between them
    Context 'the clock held in one minute' {
        Mock Get-Date { [datetime]'2026-11-07 18:14:59.9' }
        It 'does not overwrite the superseded record in the same minute, and says which approvals went' {
            $script:Bridge = @{ repo = (Join-Path $TestDrive 'r3'); settings = @{} }
            New-Item -ItemType Directory -Force -Path $script:Bridge.repo | Out-Null
            $repo = $script:Bridge.repo
            $old = New-ChangeRecord -Root 'A' -From '0.0.1' -To '0.0.2' -Types @(@{ name = 'A'; class = 'PlcTypeLibraryType'; folder = ''; released = '0.0.1'; inWork = '0.0.2' }, @{ name = 'B'; class = 'PlcTypeLibraryType'; folder = ''; released = '0.0.1'; inWork = '0.0.2' }) -Levels @{ A = 0; B = 1 } -At ([datetime]'2026-11-07 18:14:00')
            $old.types.A.releasedAs = '0.0.2'; $old.types.B.approved = $true
            $null = Save-ChangeRecord $repo $old
            $r = Register-ChangeOnEdit $null @{ name = 'A' } '0.0.2' '0.0.3' (New-Graph) @('B')
            $r.id | Should Be "$($old.id)-2"
            (Read-ChangeRecord $repo $old.id).status | Should Be 'superseded'
            (Read-ChangeRecord $repo $r.id).status | Should Be 'open'
            @(@($r.superseded)[0].approvalsDropped) | Should Be 'B'
            Format-EditChangeFacts $r | Should Match "$($old.id) is superseded"
            Format-EditChangeFacts $r | Should Match 'approvals of B are dropped: they have to be given again, tell the user'
        }
    }
    It 'says so also when no new change starts, as nothing depends on it now' {
        $script:Bridge = @{ repo = (Join-Path $TestDrive 'r4'); settings = @{} }
        New-Item -ItemType Directory -Force -Path $script:Bridge.repo | Out-Null
        $old = New-ChangeRecord -Root 'A' -From '0.0.1' -To '0.0.2' -Types @(@{ name = 'A'; class = 'PlcTypeLibraryType'; folder = ''; released = '0.0.1'; inWork = '0.0.2' }) -Levels @{ A = 0 } -At (Get-Date)
        $old.types.A.releasedAs = '0.0.2'
        $null = Save-ChangeRecord $script:Bridge.repo $old
        $r = Register-ChangeOnEdit $null @{ name = 'A' } '0.0.2' '0.0.3' (New-Graph) @()
        $r.id | Should Be ''
        Format-EditChangeFacts $r | Should Match 'is superseded'
    }
    It 'says so when a type joins again and its approval goes' {
        $script:Bridge = @{ repo = (Join-Path $TestDrive 'r5'); settings = @{} }
        New-Item -ItemType Directory -Force -Path $script:Bridge.repo | Out-Null
        $old = New-ChangeRecord -Root 'A' -From '0.0.1' -To '0.0.2' -Types @(@{ name = 'A'; class = 'PlcTypeLibraryType'; folder = ''; released = '0.0.1'; inWork = '0.0.2' }, @{ name = 'B'; class = 'PlcTypeLibraryType'; folder = ''; released = '0.0.1'; inWork = '0.0.2' }) -Levels @{ A = 0; B = 1 } -At (Get-Date)
        $old.types.B.approved = $true; $old.types.B.releasedAs = '0.0.2'
        $null = Save-ChangeRecord $script:Bridge.repo $old
        $r = Register-ChangeOnEdit $null @{ name = 'B' } '0.0.2' '0.0.3' (New-Graph) @()
        $r.joined | Should Be $true
        Format-EditChangeFacts $r | Should Match 'approval of B is dropped'
    }
    It 'still joins a change whose changed type is not released yet' {
        $script:Bridge = @{ repo = (Join-Path $TestDrive 'r2'); settings = @{} }
        New-Item -ItemType Directory -Force -Path $script:Bridge.repo | Out-Null
        $old = New-ChangeRecord -Root 'A' -From '0.0.1' -To '0.0.2' -Types @(@{ name = 'A'; class = 'PlcTypeLibraryType'; folder = ''; released = '0.0.1'; inWork = '0.0.2' }, @{ name = 'B'; class = 'PlcTypeLibraryType'; folder = ''; released = '0.0.1'; inWork = '' }) -Levels @{ A = 0; B = 1 } -At ([datetime]'2026-11-03 10:00')
        $null = Save-ChangeRecord $script:Bridge.repo $old
        $r = Register-ChangeOnEdit $null @{ name = 'B' } '0.0.1' '0.0.2' (New-Graph) @()
        $r.joined | Should Be $true
        $r.id | Should Be $old.id
    }
}

if (-not ('Siemens.Engineering.Library.Types.CreateOrReleaseDependenciesMode' -as [type])) {
    Add-Type -TypeDefinition 'namespace Siemens.Engineering.Library.Types { public enum CreateOrReleaseDependenciesMode { AutomaticallyCreateOrReleaseDependenciesIfRequired, DoNotAutomaticallyCreateOrReleaseDependencies } }'
}

# A library of fake types: released versions, a version in work, and what a type contains, as TIA takes that along.
function New-FakeVersion([string]$Number, [string]$State, [bool]$IsDefault = $false) {
    $v = [pscustomobject]@{ VersionNumber = [version]$Number; State = $State; IsDefault = $IsDefault; Dependencies = @() }
    Add-Member -InputObject $v ScriptMethod Release { param($mode, $number, $author, $comment)
        if ([string]$mode -like 'Automatically*') {
            foreach ($p in @($script:plainUsed[$this.owner])) { if ($p) { $script:fakeLib.TypeFolder.Types = @($script:fakeLib.TypeFolder.Types) + @(New-FakeType $p @(New-FakeVersion '0.0.1' 'Committed' $true)) } }
            foreach ($c in @($script:contains[$this.owner])) { foreach ($x in @($script:fakeTypes | Where-Object { $_.Name -eq $c } | ForEach-Object { $_.Versions })) { if ($x.State -eq 'InWork') { $x.State = 'Committed'; $x.IsDefault = $true } } }
        }
        $this.State = 'Committed'; $this.IsDefault = $true }
    $v
}
function New-FakeType([string]$Name, [object[]]$Versions) {
    foreach ($v in $Versions) { Add-Member -InputObject $v NoteProperty owner $Name }
    [pscustomobject]@{ Name = $Name; Versions = $Versions }
}
function Set-FakeLibrary([object[]]$Types) {
    $script:fakeTypes = $Types
    $script:fakeGraph = @{}; foreach ($t in $Types) { $script:fakeGraph[$t.Name] = @() }   # every type has its line, as in a real walk
    $script:fakeLib = [pscustomobject]@{ TypeFolder = [pscustomobject]@{ Types = $Types; Folders = @() } }
}

Describe 'library_release_chain and a contained type nobody listed' {
    function Get-BridgeSession { $script:chainState }
    function Get-TiaLibrary { $script:fakeLib }
    function Get-SafetyProgramRefusal { $null }
    function Get-TiaDeviceNames { @('Plc1') }
    function Get-LibraryTypeScope { 'plc' }
    function Add-LibraryLog { }
    function Get-UpdateScopes { @() }
    function Get-LibraryDependsOn { @{ graph = $script:fakeGraph; complete = $true; walked = 1 } }
    function Get-InWorkTypes { @{ complete = $true; walked = 0; types = @($script:fakeTypes | ForEach-Object { $t = $_; @($t.Versions | Where-Object { $_.State -eq 'InWork' }) | ForEach-Object { @{ type = $t.Name; inWork = [string]$_.VersionNumber } } }) } }
    function Invoke-CompileEveryDevice { @{ items = @(); errors = 0 } }
    function Invoke-ProjectUpdate { $script:projectUpdates++; $script:updateAnswer }
    function Invoke-TiaWrite { param($Description, $Body, $RollbackIf)
        $saved = @($script:fakeTypes | ForEach-Object { $_.Versions } | ForEach-Object { @{ v = $_; state = $_.State; def = $_.IsDefault } })
        $savedTypes = @($script:fakeLib.TypeFolder.Types)
        $out = @(& $Body)
        $back = [bool]($RollbackIf -and (& $RollbackIf))
        if ($back -and $script:chainTransaction) { foreach ($x in $saved) { $x.v.State = $x.state; $x.v.IsDefault = $x.def }; $script:fakeLib.TypeFolder.Types = $savedTypes }
        @{ output = $out; transaction = $script:chainTransaction; rolledBack = ($back -and $script:chainTransaction) }
    }
    function Reset-Chain {
        $script:chainState = New-SessionState; Register-Archive $script:chainState
        $script:contains = @{}; $script:plainUsed = @{}; $script:fakeGraph = @{}; $script:updateAnswer = @{ transaction = $true }; $script:projectUpdates = 0; $script:chainTransaction = $true
        $script:Bridge = @{ repo = [string]$TestDrive; settings = @{} }
    }
    function Get-LiveChange { $null }

    It 'refuses, releases nothing, and names it' {
        Reset-Chain
        $script:contains = @{ New = @('Old') }
        $new = New-FakeType 'New' @(New-FakeVersion '0.0.1' 'InWork')
        $old = New-FakeType 'Old' @((New-FakeVersion '0.0.1' 'Committed' $true), (New-FakeVersion '0.0.2' 'InWork'))
        Set-FakeLibrary @($new, $old)
        $r = Invoke-LibraryReleaseChainTool ([pscustomobject]@{ comment = 'c'; types = @('New') })
        $r.ok | Should Be $false
        @($r.wouldAlsoRelease) | Should Be 'Old'
        $r.refused | Should Match 'would also release Old'
        @($new.Versions)[0].State | Should Be 'InWork'
        @($old.Versions)[1].State | Should Be 'InWork'
        $script:projectUpdates | Should Be 0
        @($script:chainState.pending.Keys).Count | Should Be 0
    }
    It 'goes through when the contained type is in the release, and says it came along' {
        Reset-Chain
        $script:contains = @{ New = @('Old') }
        Set-FakeLibrary @((New-FakeType 'New' @(New-FakeVersion '0.0.1' 'InWork')), (New-FakeType 'Old' @(New-FakeVersion '0.0.1' 'InWork')))
        $r = Invoke-LibraryReleaseChainTool ([pscustomobject]@{ comment = 'c'; types = @('New', 'Old') })
        $r.ok | Should Be $true
        (@($r.released) | Where-Object { $_.type -eq 'Old' }).withContaining | Should Be $true
        $r.Contains('alsoReleased') | Should Be $false
    }
    It 'leaves another type in work alone when it is not contained' {
        Reset-Chain
        $other = New-FakeType 'Other' @(New-FakeVersion '0.0.1' 'InWork')
        Set-FakeLibrary @((New-FakeType 'New' @(New-FakeVersion '0.0.1' 'InWork')), $other)
        $r = Invoke-LibraryReleaseChainTool ([pscustomobject]@{ comment = 'c'; types = @('New') })
        $r.ok | Should Be $true
        @($other.Versions)[0].State | Should Be 'InWork'
    }
    It 'refuses a release that would make a library type of a plain object, nothing released, and names it with the way out' {
        Reset-Chain
        $script:plainUsed = @{ New = @('PlainFc') }
        $new = New-FakeType 'New' @(New-FakeVersion '0.0.1' 'InWork')
        Set-FakeLibrary @($new)
        $r = Invoke-LibraryReleaseChainTool ([pscustomobject]@{ comment = 'c'; types = @('New') })
        $r.ok | Should Be $false
        @($r.wouldMakeTypes) | Should Be 'PlainFc'
        $r.refused | Should Match 'nobody made them'
        $r.refused | Should Match 'library_create_type'
        @($new.Versions)[0].State | Should Be 'InWork'
        @($script:fakeLib.TypeFolder.Types).Count | Should Be 1
        $script:projectUpdates | Should Be 0
    }
    It 'names the type it made when there is no transaction to take it back' {
        Reset-Chain
        $script:chainTransaction = $false
        $script:plainUsed = @{ New = @('PlainFc') }
        Set-FakeLibrary @(New-FakeType 'New' @(New-FakeVersion '0.0.1' 'InWork'))
        $r = Invoke-LibraryReleaseChainTool ([pscustomobject]@{ comment = 'c'; types = @('New') })
        @($r.typesMade) | Should Be 'PlainFc'
        $r.summary | Should Match 'made library types nobody asked for: PlainFc'
    }
    It 'names it when there is no transaction to take it back' {
        Reset-Chain
        $script:chainTransaction = $false
        $script:contains = @{ New = @('Old') }
        Set-FakeLibrary @((New-FakeType 'New' @(New-FakeVersion '0.0.1' 'InWork')), (New-FakeType 'Old' @(New-FakeVersion '0.0.1' 'InWork')))
        $r = Invoke-LibraryReleaseChainTool ([pscustomobject]@{ comment = 'c'; types = @('New') })
        @($r.alsoReleased) | Should Be 'Old'
        $r.summary | Should Match 'also released Old'
    }
    Context 'a version on old versions of what it contains' {
        function Set-OnOld([string]$Uses) {
            Reset-Chain
            $s = New-FakeType 'S' @((New-FakeVersion '0.0.1' 'Committed'), (New-FakeVersion '0.0.2' 'Committed' $true))
            $script:x = New-FakeType 'X' @((New-FakeVersion '0.0.1' 'Committed' $true), (New-FakeVersion '0.0.2' 'InWork'))
            @($script:x.Versions)[1].Dependencies = @([pscustomobject]@{ VersionNumber = [version]$Uses; TypeObject = $s })
            Set-FakeLibrary @($script:x, $s)
        }
        It 'refuses, names them, releases nothing and updates nothing' {
            Set-OnOld '0.0.1'
            $r = Invoke-LibraryReleaseChainTool ([pscustomobject]@{ comment = 'c'; types = @('X') })
            $r.ok | Should Be $false
            @($r.onOldVersions) | Should Be 'X: S (uses 0.0.1, default 0.0.2)'
            $r.refused | Should Match 'would burn'
            $r.refused | Should Match 'library_update_usages'
            @($script:x.Versions)[1].State | Should Be 'InWork'
            $script:projectUpdates | Should Be 0
            @($script:chainState.pending.Keys).Count | Should Be 0
        }
        It 'goes through on the new versions' {
            Set-OnOld '0.0.2'
            $r = Invoke-LibraryReleaseChainTool ([pscustomobject]@{ comment = 'c'; types = @('X') })
            $r.ok | Should Be $true
            $r.Contains('onOldVersions') | Should Be $false
            @($script:x.Versions)[1].State | Should Be 'Committed'
        }
        It 'does not refuse a type on a version released in the same chain' {
            Reset-Chain
            $s = New-FakeType 'S' @((New-FakeVersion '0.0.1' 'Committed'), (New-FakeVersion '0.0.2' 'InWork'))
            $x = New-FakeType 'X' @((New-FakeVersion '0.0.1' 'Committed' $true), (New-FakeVersion '0.0.2' 'InWork'))
            @($x.Versions)[1].Dependencies = @([pscustomobject]@{ VersionNumber = [version]'0.0.2'; TypeObject = $s })
            Set-FakeLibrary @($x, $s)
            $script:fakeGraph = @{ X = @('S'); S = @() }
            $r = Invoke-LibraryReleaseChainTool ([pscustomobject]@{ comment = 'c'; types = @('X', 'S') })
            $r.ok | Should Be $true
            @($r.released | ForEach-Object { $_.type }) -join ',' | Should Be 'S,X'
        }
        It 'names them when there is no transaction to take it back' {
            Set-OnOld '0.0.1'
            $script:chainTransaction = $false
            $r = Invoke-LibraryReleaseChainTool ([pscustomobject]@{ comment = 'c'; types = @('X') })
            @($r.onOldVersions) | Should Be 'X: S (uses 0.0.1, default 0.0.2)'
            $r.summary | Should Match 'released on old versions'
        }
    }
    It 'a release TIA refuses says which contained type in work stands in its way' {
        Reset-Chain
        $x = New-FakeType 'X' @((New-FakeVersion '0.0.1' 'Committed' $true), (New-FakeVersion '0.0.2' 'InWork'))
        $g = New-FakeType 'G' @((New-FakeVersion '0.0.1' 'Committed' $true), (New-FakeVersion '0.0.2' 'InWork'))
        Add-Member -InputObject @($x.Versions)[1] ScriptMethod Release { param($m, $n, $au, $c) throw "Error when calling method 'Release'" } -Force
        Set-FakeLibrary @($x, $g)
        $script:fakeGraph = @{ X = @('G'); G = @() }
        $r = Invoke-LibraryReleaseChainTool ([pscustomobject]@{ comment = 'c'; types = @('X') })
        $r.ok | Should Be $false
        $r.summary | Should Match "Error when calling method 'Release'"
        $r.summary | Should Match 'X contains G, in work and not in this release'
        @($r.heldBy) | Should Be 'G'
    }
    It 'adds nothing to a refusal with no such type' {
        Reset-Chain
        $x = New-FakeType 'X' @((New-FakeVersion '0.0.1' 'Committed' $true), (New-FakeVersion '0.0.2' 'InWork'))
        Add-Member -InputObject @($x.Versions)[1] ScriptMethod Release { param($m, $n, $au, $c) throw 'TIA said no' } -Force
        Set-FakeLibrary @($x)
        $r = Invoke-LibraryReleaseChainTool ([pscustomobject]@{ comment = 'c'; types = @('X') })
        $r.summary | Should Not Match 'in work and not in this release'
        $r.Contains('heldBy') | Should Be $false
    }
}

Describe 'library_release_chain over an update that did not reach the project' {
    function Get-BridgeSession { $script:chainState }
    function Get-TiaLibrary { $script:fakeLib }
    function Get-SafetyProgramRefusal { $null }
    function Get-TiaDeviceNames { @('Plc1') }
    function Get-LibraryTypeScope { 'plc' }
    function Add-LibraryLog { }
    function Get-UpdateScopes { @() }
    function Get-LibraryDependsOn { @{ graph = $script:fakeGraph; complete = $true; walked = 1 } }
    function Get-InWorkTypes { @{ complete = $true; walked = 0; types = @($script:fakeTypes | ForEach-Object { $t = $_; @($t.Versions | Where-Object { $_.State -eq 'InWork' }) | ForEach-Object { @{ type = $t.Name; inWork = [string]$_.VersionNumber } } }) } }
    function Invoke-CompileEveryDevice { @{ items = @(); errors = 0 } }
    function Invoke-ProjectUpdate { $script:projectUpdates++; $script:updateAnswer }
    function Invoke-TiaWrite { param($Description, $Body, $RollbackIf)
        $saved = @($script:fakeTypes | ForEach-Object { $_.Versions } | ForEach-Object { @{ v = $_; state = $_.State; def = $_.IsDefault } })
        $savedTypes = @($script:fakeLib.TypeFolder.Types)
        $out = @(& $Body)
        $back = [bool]($RollbackIf -and (& $RollbackIf))
        if ($back -and $script:chainTransaction) { foreach ($x in $saved) { $x.v.State = $x.state; $x.v.IsDefault = $x.def }; $script:fakeLib.TypeFolder.Types = $savedTypes }
        @{ output = $out; transaction = $script:chainTransaction; rolledBack = ($back -and $script:chainTransaction) }
    }
    function Reset-Chain {
        $script:chainState = New-SessionState; Register-Archive $script:chainState
        $script:contains = @{}; $script:plainUsed = @{}; $script:fakeGraph = @{}; $script:updateAnswer = @{ transaction = $true }; $script:projectUpdates = 0; $script:chainTransaction = $true
        $script:Bridge = @{ repo = [string]$TestDrive; settings = @{} }
    }

    function New-OpenChange {
        Set-FakeLibrary @(
            (New-FakeType 'A' @((New-FakeVersion '0.0.1' 'Committed'), (New-FakeVersion '0.0.2' 'Committed' $true))),
            (New-FakeType 'B' @((New-FakeVersion '0.0.1' 'Committed' $true), (New-FakeVersion '0.0.2' 'InWork'))))
        $script:fakeGraph = @{ A = @(); B = @('A') }
        $rec = New-ChangeRecord -Root 'A' -From '0.0.1' -To '0.0.2' -Types @(@{ name = 'A'; class = 'PlcTypeLibraryType'; folder = ''; released = '0.0.1'; inWork = '0.0.2' }, @{ name = 'B'; class = 'PlcTypeLibraryType'; folder = ''; released = '0.0.1'; inWork = '0.0.2' }) -Levels @{ A = 0; B = 1 } -At ([datetime]'2026-11-03 10:00')
        $rec.types.A.releasedAs = '0.0.2'; $rec.types.B.approved = $true; $rec.updated = $true
        $null = Save-ChangeRecord $TestDrive $rec
        $rec.id
    }

    It 'answers not ok, keeps the change open, and says the update is outstanding' {
        Reset-Chain
        $id = New-OpenChange
        $script:updateAnswer = @{ refused = 'The update would take X out of the PLC.' }
        $r = Invoke-LibraryReleaseChainTool ([pscustomobject]@{ comment = 'c' })
        $r.ok | Should Be $false
        $r.updateRefused | Should Match 'take X out'
        $r.next | Should Match 'not updated'
        $r.next | Should Not Match 'library change done'
        $r.released | Should Not Be $null
        $rec = Read-ChangeRecord $TestDrive $id
        $rec.status | Should Be 'open'
        $rec.updateOutstanding | Should Be $true
        Format-ChangeReport $rec | Should Match 'not updated to the released types'
    }
    It 'takes a refused commit for the same thing' {
        Reset-Chain
        $id = New-OpenChange
        $script:updateAnswer = @{ commitError = @{ message = 'no commit' }; transaction = $true }
        $r = Invoke-LibraryReleaseChainTool ([pscustomobject]@{ comment = 'c' })
        $r.ok | Should Be $false
        $r.updateRefused | Should Match 'no commit'
        (Read-ChangeRecord $TestDrive $id).status | Should Be 'open'
    }
    It 'closes the change when the update goes through, also after one that did not' {
        Reset-Chain
        $id = New-OpenChange
        $rec = Read-ChangeRecord $TestDrive $id
        $rec.updateOutstanding = $true
        $null = Save-ChangeRecord $TestDrive $rec
        $r = Invoke-LibraryReleaseChainTool ([pscustomobject]@{ comment = 'c' })
        $r.ok | Should Be $true
        $r.next | Should Match 'library change done'
        (Read-ChangeRecord $TestDrive $id).status | Should Be 'done'
    }
    It 'keeps what it released when the update throws, and says it is outstanding' {
        Reset-Chain
        $id = New-OpenChange
        function Invoke-ProjectUpdate { throw 'TIA said no.' }
        $r = Invoke-LibraryReleaseChainTool ([pscustomobject]@{ comment = 'c' })
        $r.ok | Should Be $false
        $r.updateRefused | Should Match 'TIA said no\.'
        (Read-ChangeRecord $TestDrive $id).status | Should Be 'open'
    }
}

Describe 'library_release_type names all it released' {
    function Get-BridgeSession { $script:chainState }
    function Get-TiaLibrary { $script:fakeLib }
    function Get-TiaDeviceNames { @('Plc1') }
    function Get-LibraryTypeScope { 'plc' }
    function Add-LibraryLog { }
    function Get-LibraryDependsOn { @{ graph = $script:fakeGraph; complete = $true; walked = 1 } }
    function Get-InWorkTypes { @{ complete = $script:walkComplete; walked = 0; types = @($script:fakeTypes | ForEach-Object { $t = $_; @($t.Versions | Where-Object { $_.State -eq 'InWork' }) | ForEach-Object { @{ type = $t.Name; inWork = [string]$_.VersionNumber } } }) } }
    function Invoke-TiaWrite { param($Description, $Body, $RollbackIf)
        $savedTypes = @($script:fakeLib.TypeFolder.Types)
        $states = @($script:fakeTypes | ForEach-Object { $_.Versions } | ForEach-Object { @{ v = $_; state = $_.State } })
        $out = @(& $Body)
        $back = [bool]($RollbackIf -and (& $RollbackIf))
        if ($back) { foreach ($x in $states) { $x.v.State = $x.state }; $script:fakeLib.TypeFolder.Types = $savedTypes }
        @{ output = $out; transaction = $true; rolledBack = $back }
    }
    function Set-Fake { $script:chainState = New-SessionState; Register-Archive $script:chainState; $script:contains = @{}; $script:plainUsed = @{}; $script:walkComplete = $true; $script:Bridge = @{ repo = [string]$TestDrive; settings = @{} } }

    It 'names the contained type TIA took along, with its version, and holds it for the compile' {
        Set-Fake
        $script:contains = @{ Top = @('Base') }
        Set-FakeLibrary @((New-FakeType 'Top' @(New-FakeVersion '0.0.1' 'InWork')), (New-FakeType 'Base' @(New-FakeVersion '0.0.4' 'InWork')), (New-FakeType 'Other' @(New-FakeVersion '0.0.1' 'InWork')))
        $r = Invoke-LibraryReleaseTool ([pscustomobject]@{ name = 'Top'; comment = 'c' })
        $r.released | Should Be '0.0.1'
        @($r.alsoReleased).Count | Should Be 1
        @($r.alsoReleased)[0].type | Should Be 'Base'
        @($r.alsoReleased)[0].version | Should Be '0.0.4'
        $r.summary | Should Match 'Released with it, as it contains them: Base 0\.0\.4'
        $script:chainState.pending.ContainsKey('plc@plc1:type:base') | Should Be $true
    }
    It 'refuses a release that would make a library type of a plain object, and holds nothing' {
        Set-Fake
        $script:plainUsed = @{ Top = @('PlainUdt') }
        $top = New-FakeType 'Top' @(New-FakeVersion '0.0.1' 'InWork')
        Set-FakeLibrary @($top)
        $r = Invoke-LibraryReleaseTool ([pscustomobject]@{ name = 'Top'; comment = 'c' })
        $r.ok | Should Be $false
        @($r.wouldMakeTypes) | Should Be 'PlainUdt'
        $r.refused | Should Match 'Release of Top refused'
        @($top.Versions)[0].State | Should Be 'InWork'
        @($script:fakeLib.TypeFolder.Types).Count | Should Be 1
        @($script:chainState.pending.Keys).Count | Should Be 0
    }
    It 'adds nothing when it took nothing along' {
        Set-Fake
        Set-FakeLibrary @((New-FakeType 'Top' @(New-FakeVersion '0.0.1' 'InWork')), (New-FakeType 'Other' @(New-FakeVersion '0.0.1' 'InWork')))
        $r = Invoke-LibraryReleaseTool ([pscustomobject]@{ name = 'Top'; comment = 'c' })
        $r.Contains('alsoReleased') | Should Be $false
        $r.summary | Should Not Match 'Released with it'
    }
    It 'says so when the walk stopped and it cannot tell' {
        Set-Fake
        $script:walkComplete = $false
        Set-FakeLibrary @(New-FakeType 'Top' @(New-FakeVersion '0.0.1' 'InWork'))
        (Invoke-LibraryReleaseTool ([pscustomobject]@{ name = 'Top'; comment = 'c' })).summary | Should Match 'is not known'
    }
}

Describe 'A type left on old versions, with no instance' {
    function Get-LibraryStale { if ($script:staleThrows) { throw 'the walk failed' }; $d = @{}; foreach ($k in $script:staleMap.Keys) { $d[$k] = @() }; @{ stale = $script:staleMap; complete = $script:staleComplete; walked = 2; deps = $d } }
    function Find-LibraryType { param($Library, $Name)
        $v = [pscustomobject]@{ VersionNumber = [version]'0.0.1'; State = 'Committed'; IsDefault = $true }
        Add-Member -InputObject $v ScriptMethod FindInstances { param($sw) if ($script:findThrows) { throw 'FindInstances failed' }; $script:instancesOfD }
        @{ name = $Name; obj = [pscustomobject]@{ Versions = @($v) } }
    }
    function Get-TiaSoftwareList { @(@{ kind = 'plc'; device = 'P'; software = 'sw' }) }
    function Get-LibraryTypeScope { $script:scopeOfD }
    function Add-LibraryLog { }
    function Get-LibraryTypeMap { $script:mapWalks++; $h = @{ }; foreach ($k in $script:staleMap.Keys) { $h[$k] = (Find-LibraryType $null $k).obj }; $h }
    function New-Record {
        $types = @(@{ name = 'A'; class = 'PlcTypeLibraryType'; folder = ''; released = '0.0.1'; inWork = '0.0.2' }, @{ name = 'D'; class = 'CodeBlockLibraryType'; folder = ''; released = '0.0.1'; inWork = '' })
        $r = New-ChangeRecord -Root 'A' -From '0.0.1' -To '0.0.2' -Types $types -Levels @{ A = 0; D = 1 } -At ([datetime]'2026-11-03 10:00')
        $r.types.A.releasedAs = '0.0.2'; $r.updated = $true
        $r
    }
    function Reset-Fake {
        $script:staleMap = @{ D = @('A (uses 0.0.1, default 0.0.2)') }; $script:staleComplete = $true; $script:staleThrows = $false
        $script:instancesOfD = @(); $script:findThrows = $false; $script:scopeOfD = 'plc'
    }

    It 'does not keep the change open, and the report says so plainly, with nothing to tick' {
        Reset-Fake
        $r = New-Record
        @(Update-ChangeStale $null $r).Count | Should Be 0
        $r.types.D.noInstance | Should Be $true
        Test-ChangeDone $r | Should Be $true
        $text = Format-ChangeReport $r
        $text | Should Match 'LEFT ON OLD VERSIONS\*\*, no instance in this project, so no update moved it: uses A \(uses 0\.0\.1, default 0\.0\.2\) - see below'
        $text | Should Not Match '\[ \] `D`'
    }
    It 'keeps it open while the type has an instance, as it can be put in work' {
        Reset-Fake
        $script:instancesOfD = @('one')
        $r = New-Record
        @(Update-ChangeStale $null $r) | Should Be 'D'
        Test-ChangeDone $r | Should Be $false
    }
    It 'a FindInstances that fails counts as an instance, which holds the change' {
        Reset-Fake
        $script:findThrows = $true
        $r = New-Record
        @(Update-ChangeStale $null $r) | Should Be 'D'
        Test-ChangeDone $r | Should Be $false
    }
    It 'an HMI type counts as having one, as they are not known to be found this way' {
        Reset-Fake
        $script:scopeOfD = 'hmi'
        Test-TypeHasInstance $null 'D' | Should Be $true
    }
    It 'a stale read that fails holds the change, and the report says so' {
        Reset-Fake
        $script:staleThrows = $true
        $r = New-Record
        @(Update-ChangeStale $null $r).Count | Should Be 0
        $r.staleUnread | Should Match 'the walk failed'
        Test-ChangeDone $r | Should Be $false
        Format-ChangeReport $r | Should Match 'was not read, so this stays open'
    }
    It 'a stale read cut by the time limit holds it too' {
        Reset-Fake
        $script:staleComplete = $false
        $r = New-Record
        $null = Update-ChangeStale $null $r
        $r.staleUnread | Should Match 'time limit'
        Test-ChangeDone $r | Should Be $false
    }
    It 'the update computes it, so a change with no type to put in work ends there, not as done' {
        Reset-Fake
        function Get-LiveChange { $script:rec }
        function Save-ChangeRecord { param($Repo, $Record) if ($Record.status -in 'open', 'done', 'left-behind') { $Record.status = Get-ChangeStatus $Record }; 'r.md' }
        $script:Bridge = @{ repo = [string]$TestDrive; settings = @{} }
        $script:rec = New-Record; $script:rec.updated = $false
        $u = Update-ChangeAfterUpdate $null @() $false (New-SessionState)
        $u.status | Should Be 'left-behind'
        $script:rec.types.D.noInstance | Should Be $true
    }
    It 'names each with what it uses and what to do, in summary, field and next' {
        Reset-Fake
        $r = @{ summary = 's'; next = 'n'; ok = $true }
        Add-LeftBehindFacts $r $null
        @($r.typesLeftBehind)[0].type | Should Be 'D'
        @($r.typesLeftBehind)[0].version | Should Be '0.0.1'
        @(@($r.typesLeftBehind)[0].uses) | Should Be 'A (uses 0.0.1, default 0.0.2)'
        $r.summary | Should Match 'Left on old versions'
        $r.summary | Should Match 'D 0\.0\.1 \(uses A \(uses 0\.0\.1, default 0\.0\.2\)\)'
        $r.summary | Should Match 'Ask the user, once, with this list'
        $r.next | Should Match 'library_left_behind with answer yes'
        $r.ok | Should Be $true
    }
    It 'reads the library once, however many are stale' {
        Reset-Fake
        $script:staleMap = @{ D = @('A (uses 0.0.1, default 0.0.2)'); E = @('A (uses 0.0.1, default 0.0.2)'); F = @('A (uses 0.0.1, default 0.0.2)') }
        $script:mapWalks = 0
        $b = Get-TypesLeftBehind $null
        @($b.types).Count | Should Be 3
        $script:mapWalks | Should Be 1
    }
    It 'makes no walk when nothing is stale' {
        Reset-Fake
        $script:staleMap = @{ }
        $script:mapWalks = 0
        @((Get-TypesLeftBehind $null).types).Count | Should Be 0
        $script:mapWalks | Should Be 0
    }
    It 'says nothing when there is nothing, and when each stale type has an instance' {
        Reset-Fake
        $script:instancesOfD = @('one')
        $r = @{ summary = 's'; ok = $true }
        Add-LeftBehindFacts $r $null
        $r.summary | Should Be 's'
        $r.Contains('typesLeftBehind') | Should Be $false
    }
    It 'says a read that fails or stops, not that there are none' {
        Reset-Fake
        $script:staleThrows = $true
        $r = @{ summary = 's' }
        Add-LeftBehindFacts $r $null
        $r.typesLeftBehindUnread | Should Match 'the walk failed'
        $script:staleThrows = $false; $script:staleComplete = $false; $script:staleMap = @{}
        $r = @{ summary = 's' }
        Add-LeftBehindFacts $r $null
        $r.typesLeftBehindUnread | Should Match 'time limit'
    }
    It 'library_review with no open change still names them, in its refusal' {
        Reset-Fake
        function Get-BridgeSession { New-SessionState }
        function Get-TiaLibrary { $null }
        function Get-LiveChange { $null }
        $script:Bridge = @{ repo = [string]$TestDrive; settings = @{} }
        $r = Invoke-LibraryReviewTool ([pscustomobject]@{ })
        $r.refused | Should Match 'No open library change'
        @($r.typesLeftBehind)[0].type | Should Be 'D'
    }
}

Describe 'library_update_usages and the chain name what is left behind' {
    function Get-BridgeSession { $script:chainState }
    function Get-TiaLibrary { $script:fakeLib }
    function Get-SafetyProgramRefusal { $null }
    function Get-TiaDeviceNames { @('Plc1') }
    function Get-LibraryTypeScope { 'plc' }
    function Add-LibraryLog { }
    function Get-UpdateScopes { @() }
    function Get-LibraryDependsOn { @{ graph = $script:fakeGraph; complete = $true; walked = 1 } }
    function Get-InWorkTypes { @{ complete = $true; walked = 0; types = @($script:fakeTypes | ForEach-Object { $t = $_; @($t.Versions | Where-Object { $_.State -eq 'InWork' }) | ForEach-Object { @{ type = $t.Name; inWork = [string]$_.VersionNumber } } }) } }
    function Invoke-CompileEveryDevice { @{ items = @(); errors = 0 } }
    function Invoke-ProjectUpdate { $script:projectUpdates++; $script:updateAnswer }
    function Invoke-TiaWrite { param($Description, $Body, $RollbackIf)
        $saved = @($script:fakeTypes | ForEach-Object { $_.Versions } | ForEach-Object { @{ v = $_; state = $_.State; def = $_.IsDefault } })
        $savedTypes = @($script:fakeLib.TypeFolder.Types)
        $out = @(& $Body)
        $back = [bool]($RollbackIf -and (& $RollbackIf))
        if ($back -and $script:chainTransaction) { foreach ($x in $saved) { $x.v.State = $x.state; $x.v.IsDefault = $x.def }; $script:fakeLib.TypeFolder.Types = $savedTypes }
        @{ output = $out; transaction = $script:chainTransaction; rolledBack = ($back -and $script:chainTransaction) }
    }
    function Reset-Chain {
        $script:chainState = New-SessionState; Register-Archive $script:chainState
        $script:contains = @{}; $script:plainUsed = @{}; $script:fakeGraph = @{}; $script:updateAnswer = @{ transaction = $true }; $script:projectUpdates = 0; $script:chainTransaction = $true
        $script:Bridge = @{ repo = [string]$TestDrive; settings = @{} }
    }
    function Get-LiveChange { $null }
    function Get-TiaProject { $l = [pscustomobject]@{ }; Add-Member -InputObject $l ScriptMethod UpdateCheck { param($p, $m) @{ } }; [pscustomobject]@{ ProjectLibrary = $l } }
    function ConvertTo-ResultTree { @{ } }
    function Get-TiaSoftwareList { @(@{ kind = 'plc'; device = 'Plc1' }) }
    function Get-TypesLeftBehind { @{ types = @(@{ type = 'D'; version = '0.0.1'; uses = @('A (uses 0.0.1, default 0.0.2)') }); complete = $true } }

    It 'library_update_usages, also with no change open' {
        Reset-Chain
        Set-FakeLibrary @(New-FakeType 'A' @(New-FakeVersion '0.0.1' 'Committed' $true))
        $r = Invoke-LibraryUpdateTool ([pscustomobject]@{ types = @('A'); safety = $true })
        $r.ok | Should Be $true
        @($r.typesLeftBehind)[0].type | Should Be 'D'
        $r.summary | Should Match 'library_left_behind'
        $r.next | Should Match 'library_left_behind'
    }
    It 'the chain when it released' {
        Reset-Chain
        Set-FakeLibrary @(New-FakeType 'A' @(New-FakeVersion '0.0.1' 'InWork'))
        $r = Invoke-LibraryReleaseChainTool ([pscustomobject]@{ comment = 'c' })
        @($r.typesLeftBehind)[0].type | Should Be 'D'
    }
    It 'the chain with nothing to release' {
        Reset-Chain
        Set-FakeLibrary @(New-FakeType 'A' @(New-FakeVersion '0.0.1' 'Committed' $true))
        $r = Invoke-LibraryReleaseChainTool ([pscustomobject]@{ comment = 'c' })
        $r.ok | Should Be $false
        @($r.typesLeftBehind)[0].type | Should Be 'D'
    }
}

Describe 'library_update_usages over an update that did not reach the project' {
    function Get-BridgeSession { $script:chainState }
    function Get-TiaLibrary { $script:fakeLib }
    function Get-SafetyProgramRefusal { $null }
    function Get-TiaDeviceNames { @('Plc1') }
    function Get-LibraryTypeScope { 'plc' }
    function Add-LibraryLog { }
    function Get-UpdateScopes { @() }
    function Get-LibraryDependsOn { @{ graph = $script:fakeGraph; complete = $true; walked = 1 } }
    function Get-InWorkTypes { @{ complete = $true; walked = 0; types = @($script:fakeTypes | ForEach-Object { $t = $_; @($t.Versions | Where-Object { $_.State -eq 'InWork' }) | ForEach-Object { @{ type = $t.Name; inWork = [string]$_.VersionNumber } } }) } }
    function Invoke-CompileEveryDevice { @{ items = @(); errors = 0 } }
    function Invoke-ProjectUpdate { $script:projectUpdates++; $script:updateAnswer }
    function Invoke-TiaWrite { param($Description, $Body, $RollbackIf)
        $saved = @($script:fakeTypes | ForEach-Object { $_.Versions } | ForEach-Object { @{ v = $_; state = $_.State; def = $_.IsDefault } })
        $savedTypes = @($script:fakeLib.TypeFolder.Types)
        $out = @(& $Body)
        $back = [bool]($RollbackIf -and (& $RollbackIf))
        if ($back -and $script:chainTransaction) { foreach ($x in $saved) { $x.v.State = $x.state; $x.v.IsDefault = $x.def }; $script:fakeLib.TypeFolder.Types = $savedTypes }
        @{ output = $out; transaction = $script:chainTransaction; rolledBack = ($back -and $script:chainTransaction) }
    }
    function Reset-Chain {
        $script:chainState = New-SessionState; Register-Archive $script:chainState
        $script:contains = @{}; $script:plainUsed = @{}; $script:fakeGraph = @{}; $script:updateAnswer = @{ transaction = $true }; $script:projectUpdates = 0; $script:chainTransaction = $true
        $script:Bridge = @{ repo = [string]$TestDrive; settings = @{} }
    }
    function Get-LiveChange { $null }
    function Get-TiaProject { [pscustomobject]@{ ProjectLibrary = [pscustomobject]@{ } } }
    function Get-TiaSoftwareList { @(@{ kind = 'plc'; device = 'Plc1' }) }

    It 'refuses on a refused commit, not as updated' {
        Reset-Chain
        Set-FakeLibrary @(New-FakeType 'A' @(New-FakeVersion '0.0.1' 'Committed' $true))
        $script:updateAnswer = @{ commitError = @{ message = 'no commit' }; transaction = $true }
        $r = Invoke-LibraryUpdateTool ([pscustomobject]@{ types = @('A'); safety = $true })
        $r.ok | Should Be $false
        $r.refused | Should Match 'no commit'
        @($script:chainState.pending.Keys).Count | Should Be 0
    }
}

Describe 'What is committed is named, whatever fails later' {
    function Get-TiaSoftwareList { @(@{ kind = 'plc'; device = 'Plc1'; software = [pscustomobject]@{ BlockGroup = 'b'; TypeGroup = 't' } }) }
    function Get-GroupTree { param($Root, $Items, $Groups)
        if ($Root -eq 'b') { $script:blocks | ForEach-Object { @{ name = $_; obj = [pscustomobject]@{ Name = $_; Number = 5 }; folder = 'f' } } }
    }
    function Get-LibraryLink { param($Obj) @{ type = "T$($Obj.Name)"; version = '0.0.1' } }
    function Find-LibraryType { param($Library, $Name) @{ name = $Name; obj = [Siemens.Engineering.Library.Types.FakeTypeSelection]::new() } }
    function Add-LibraryLog { param($Line) $script:logged += @($Line) }
    function Invoke-TiaWrite { param($Description, $Body) $null = & $Body; @{ transaction = $true; rolledBack = $false } }
    $library = [pscustomobject]@{ TypeFolder = [Siemens.Engineering.Library.Types.FakeTypeSelection]::new() }
    function Reset-Fake { $script:blocks = @('Keep', 'Gone'); $script:logged = @(); $script:CommittedFacts = $null }

    It 'logs what went at once and keeps it for the result of a later failure' {
        Reset-Fake
        $null = Invoke-ProjectUpdate $library @('T') { param($s) $script:blocks = @('Keep') } 'u'
        $script:logged -join ' ' | Should Match 'TIA removed from the PLC: Gone \(type TGone 0\.0\.1, folder f\)'
        @($script:CommittedFacts['instancesRemoved'])[0].object | Should Be 'Gone'
    }
    It 'looks after a throw inside the update without a transaction, and says what went' {
        Reset-Fake
        { Invoke-ProjectUpdate $library @('T') { param($s) $script:blocks = @('Keep'); throw 'TIA said no.' } 'u' } | Should Throw 'TIA said no.'
        @($script:CommittedFacts['instancesRemoved'])[0].object | Should Be 'Gone'
        $script:logged -join ' ' | Should Match 'Gone'
    }
    It 'says nothing after a throw that took nothing, as a transaction rolled it back' {
        Reset-Fake
        { Invoke-ProjectUpdate $library @('T') { param($s) throw 'TIA said no.' } 'u' } | Should Throw
        $script:CommittedFacts | Should Be $null
        @($script:logged).Count | Should Be 0
    }
}

Describe 'library_edit_type on a type with no instance' {
    function Get-BridgeSession { $script:editState }
    function Get-TiaLibrary { 'lib' }
    function Get-TiaDeviceNames { @('Plc1') }
    function Get-LibraryTypeScope { 'plc' }
    function Add-LibraryLog { }
    function Get-LibraryDependsOn { @{ graph = @{ }; complete = $true; walked = 1 } }
    function Get-TypeDependents { @() }
    function Register-ChangeOnEdit { $null }
    function Get-TypeInstances { param($v) @($script:instanceOnOld | Where-Object { $_.on -eq [string]$v.VersionNumber }) }
    function Format-Instances { @() }
    function Find-LibraryType { @{ name = 'X'; folder = 'libFolder'; obj = $script:typeX } }
    function Get-TiaSoftwareList { @(@{ kind = 'plc'; device = 'Plc1'; software = 'sw' }) }
    function Test-PlcDataLibraryType { $script:xIsData }
    function Get-TiaSoftwareEntry { @{ device = 'Plc1'; software = [pscustomobject]@{ BlockGroup = 'blocks'; TypeGroup = 'types' } } }
    function Get-OrCreateGroup { param($Root, $Folder, $Prop) $script:askedRoot = $Root; $script:askedFolder = $Folder; $script:group }
    function Get-PlcObjectRecords { $h = @{ }; foreach ($r in $script:records) { $h["Plc1`tblock`t$($r.object)"] = $r }; $h }
    function Invoke-TiaWrite { param($Description, $Body, $RollbackIf)
        $savedRecords = @($script:records); $savedVersions = @($script:typeX.Versions)
        $null = & $Body
        $back = [bool]($RollbackIf -and (& $RollbackIf))
        if ($back) { $script:records = $savedRecords; $script:typeX.Versions = $savedVersions; return @{ transaction = $true; rolledBack = $true } }
        if ($script:commitRefused) { $script:records = $savedRecords; $script:typeX.Versions = $savedVersions; return @{ transaction = $true; rolledBack = $true; commitError = @{ message = 'no commit' } } }
        @{ transaction = $true; rolledBack = $false }
    }
    function Reset-Fake {
        $script:editState = New-SessionState; Register-Archive $script:editState
        $script:records = @(@{ object = 'Other'; device = 'Plc1'; folder = ''; type = $null })
        $script:comes = @(@{ object = 'X'; device = 'Plc1'; folder = 'libFolder'; type = 'X'; version = '0.0.1'; number = 4; language = 'LAD' })
        $script:xIsData = $false; $script:commitRefused = $false; $script:edited = $false; $script:findThrows = $false; $script:instanceOnOld = @()
        $v = [pscustomobject]@{ VersionNumber = [version]'0.0.1'; State = 'Committed'; IsDefault = $true }
        Add-Member -InputObject $v ScriptMethod FindInstances { param($sw) if ($script:findThrows) { throw 'FindInstances failed' }; @($script:records | Where-Object { $_.type -eq 'X' } | ForEach-Object { 'info' }) }
        Add-Member -InputObject $v ScriptMethod Edit { param($i) $script:edited = $true; $script:typeX.Versions = @($script:typeX.Versions) + @([pscustomobject]@{ VersionNumber = [version]'0.0.2'; State = 'InWork'; IsDefault = $false }) }
        $script:typeX = [pscustomobject]@{ Name = 'X'; Versions = @($v) }
        $made = [pscustomobject]@{ }
        Add-Member -InputObject $made ScriptMethod CreateFrom { param($ver, $mode) $script:createdMode = [string]$mode; $script:records = @($script:records) + @($script:comes) }
        $script:group = [pscustomobject]@{ Blocks = $made; Types = $made }
    }
    if (-not ('Siemens.Engineering.Library.Types.UpdatePathsMode' -as [type])) {
        Add-Type -TypeDefinition 'namespace Siemens.Engineering.Library.Types { public enum UpdatePathsMode { UpdatePathsInTarget, KeepExistingPathsInTarget, ThrowIfPathsConflict } }'
    }

    It 'makes one in the folder of the type, puts it in work, and names it' {
        Reset-Fake
        $r = Invoke-LibraryEditTool ([pscustomobject]@{ name = 'X' })
        $r.ok | Should Be $true
        $script:edited | Should Be $true
        $r.inWork | Should Be '0.0.2'
        $r.instanceMade.object | Should Be 'X'
        $r.instanceMade.folder | Should Be 'libFolder'
        $r.instanceMade.number | Should Be 4
        $r.Contains('copiesMade') | Should Be $false
        $script:askedRoot | Should Be 'blocks'
        $script:askedFolder | Should Be 'libFolder'
        $script:createdMode | Should Be 'KeepExistingPathsInTarget'
        $r.summary | Should Match 'It had no instance, so one was made: X \(type X 0\.0\.1, folder libFolder\)'
        $r.summary | Should Match 'the next update removes its instance again'
        $script:editState.pending.ContainsKey('plc@plc1:x') | Should Be $true
        $script:editState.pending.ContainsKey('plc@plc1:type:x') | Should Be $true
    }
    It 'takes the folder asked for, and the type group for a data type' {
        Reset-Fake
        $script:xIsData = $true
        $null = Invoke-LibraryEditTool ([pscustomobject]@{ name = 'X'; target_folder = 'my/place' })
        $script:askedRoot | Should Be 'types'
        $script:askedFolder | Should Be 'my/place'
    }
    It 'names the copies of old versions it brought, with the way out' {
        Reset-Fake
        $script:comes += @(@{ object = 'S_1'; device = 'Plc1'; folder = 'libFolder'; type = 'S'; version = '0.0.1'; language = $null })
        $r = Invoke-LibraryEditTool ([pscustomobject]@{ name = 'X' })
        @($r.copiesMade)[0].object | Should Be 'S_1'
        @($r.copiesMade)[0].type | Should Be 'S'
        $r.summary | Should Match 'S_1 \(type S 0\.0\.1, folder libFolder\)'
        $r.summary | Should Match 'library_update_usages'
        $r.next | Should Match "^compile, library_update_usages with types=\['S'\], compile, and only then export"
        $r.next | Should Match 'An export before that update reads the names of the copies'
        $r.summary | Should Match "Next: compile, library_update_usages with types=\['S'\]"
        $script:editState.pending.ContainsKey('plc@plc1:s_1') | Should Be $true
    }
    It 'refuses when it would be an F-block, and has made nothing' {
        Reset-Fake
        $script:comes = @(@{ object = 'X'; device = 'Plc1'; folder = ''; type = 'X'; version = '0.0.1'; language = 'F_LAD' })
        $r = Invoke-LibraryEditTool ([pscustomobject]@{ name = 'X' })
        $r.refused | Should Match 'safety program'
        $script:edited | Should Be $false
        @($script:records).Count | Should Be 1
        @($script:editState.pending.Keys).Count | Should Be 0
    }
    It 'takes it with safety: true' {
        Reset-Fake
        $script:comes = @(@{ object = 'X'; device = 'Plc1'; folder = ''; type = 'X'; version = '0.0.1'; language = 'F_LAD' })
        (Invoke-LibraryEditTool ([pscustomobject]@{ name = 'X'; safety = $true })).ok | Should Be $true
    }
    It 'holds nothing when TIA refuses the commit' {
        Reset-Fake
        $script:commitRefused = $true
        $r = Invoke-LibraryEditTool ([pscustomobject]@{ name = 'X' })
        $r.ok | Should Be $false
        $r.note | Should Match 'nothing of X was made'
        @($script:editState.pending.Keys).Count | Should Be 0
    }
    It 'refuses when an older version has the instance, makes nothing, and says where it is' {
        Reset-Fake
        $old = [pscustomobject]@{ VersionNumber = [version]'0.0.1'; State = 'Committed'; IsDefault = $false }
        Add-Member -InputObject $old ScriptMethod FindInstances { param($sw) @('info') }
        $def = [pscustomobject]@{ VersionNumber = [version]'0.0.2'; State = 'Committed'; IsDefault = $true }
        Add-Member -InputObject $def ScriptMethod FindInstances { param($sw) @() }
        $script:typeX.Versions = @($old, $def)
        $script:instanceOnOld = @(@{ name = 'X'; on = '0.0.1' })
        $r = Invoke-LibraryEditTool ([pscustomobject]@{ name = 'X' })
        $r.refused | Should Match "Type 'X' V 0\.0\.2 has no instance, but the type has: X on 0\.0\.1"
        $r.refused | Should Match 'library_update_usages'
        $script:edited | Should Be $false
        @($script:records).Count | Should Be 1
        @($script:editState.pending.Keys).Count | Should Be 0
    }
    It 'refuses when the read of instances fails, rather than make a second one' {
        Reset-Fake
        $script:findThrows = $true
        $r = Invoke-LibraryEditTool ([pscustomobject]@{ name = 'X' })
        $r.refused | Should Match 'could not be read'
        @($script:records).Count | Should Be 1
    }
    It 'still refuses an instance named that is not there, and makes nothing' {
        Reset-Fake
        $r = Invoke-LibraryEditTool ([pscustomobject]@{ name = 'X'; instance = 'Nope' })
        $r.refused | Should Match "no instance named 'Nope'"
        $script:edited | Should Be $false
    }
    It 'a failure right after it made the instance names what stands, in the result and the log' {
        Reset-Fake
        $script:logged = @(); $script:CommittedFacts = $null
        function Add-LibraryLog { param($Line) $script:logged += @($Line) }
        function Get-LibraryDependsOn { throw 'the walk failed' }
        $script:comes += @(@{ object = 'S_1'; device = 'Plc1'; folder = 'libFolder'; type = 'S'; version = '0.0.1'; language = $null })
        { Invoke-LibraryEditTool ([pscustomobject]@{ name = 'X' }) } | Should Throw 'the walk failed'
        $script:CommittedFacts['instanceMade'].object | Should Be 'X'
        @($script:CommittedFacts['copiesMade'])[0].object | Should Be 'S_1'
        $script:logged -join ' ' | Should Match 'X \(type X 0\.0\.1, folder libFolder\).*S_1 \(type S 0\.0\.1, folder libFolder\)'
    }
    It 'a refused call names nothing as made' {
        Reset-Fake
        $script:CommittedFacts = $null
        $script:comes[0].language = 'F_LAD'
        $null = Invoke-LibraryEditTool ([pscustomobject]@{ name = 'X' })
        $script:CommittedFacts | Should Be $null
    }
    It 'names the folders the instance and its copies made in the PLC, for delete_folder' {
        Reset-Fake
        function Get-PlcFolderPaths { if (@($script:records).Count -gt 1) { "block`tmine"; "block`tlibFolder"; "type`tlibFolder/sub" } else { "block`tmine" } }
        $r = Invoke-LibraryEditTool ([pscustomobject]@{ name = 'X' })
        @($r.foldersMade | ForEach-Object { "$($_.kind) $($_.folder) $($_.device)" }) -join ',' | Should Be 'block libFolder Plc1,type libFolder/sub Plc1'
        $r.summary | Should Match 'Folders made: block libFolder, type libFolder/sub'
        $r.next | Should Match 'delete_folder'
    }
    It 'has no folder field when it made none' {
        Reset-Fake
        (Invoke-LibraryEditTool ([pscustomobject]@{ name = 'X' })).Contains('foldersMade') | Should Be $false
    }
    It 'keeps the folders in the change it starts, so that its end names them' {
        Reset-Fake
        $script:repoMade = Join-Path $TestDrive ([guid]::NewGuid().ToString('N'))
        New-Item -ItemType Directory -Force -Path (Join-Path $script:repoMade 'library\changes') | Out-Null
        $was = $script:Bridge
        $script:Bridge = @{ repo = $script:repoMade; settings = @{} }
        function Get-PlcFolderPaths { if (@($script:records).Count -gt 1) { "block`tlibFolder" } }
        function Register-ChangeOnEdit {
            $rec = New-ChangeRecord -Root 'X' -From '0.0.1' -To '0.0.2' -Types @(@{ name = 'X'; class = 'CodeBlockLibraryType'; folder = ''; released = '0.0.1'; inWork = '0.0.2' }) -Levels @{ X = 0 } -At ([datetime]'2026-11-04 10:00')
            @{ id = $rec.id; report = (Save-ChangeRecord $script:repoMade $rec); joined = $false }
        }
        $r = Invoke-LibraryEditTool ([pscustomobject]@{ name = 'X' })
        $saved = Read-ChangeRecord $script:repoMade $r.change
        @($saved.foldersMade)[0].folder | Should Be 'libFolder'
        Format-FolderCleanup $saved | Should Match 'delete_folder with kind block, folder libFolder'
        $script:Bridge = $was
    }
    It 'a know-how type whose number is held is refused for that, not with what TIA says of AutoNumber' {
        Reset-Fake
        $script:records[0].number = 4; $script:records[0].class = 'FC'
        $script:comes[0].class = 'FC'; $script:comes[0].knowhow = $true
        $block = [pscustomobject]@{ Name = 'X' }
        Add-Member -InputObject $block ScriptProperty AutoNumber { $true } { throw "'set_AutoNumber' is not supported" }
        function Get-GroupTree { param($Root, $Items, $Groups) @(@{ name = 'X'; obj = $block; folder = 'libFolder' }) }
        $r = Invoke-LibraryEditTool ([pscustomobject]@{ name = 'X' })
        $r.refused | Should Match 'know-how protected \(X, number 4\)'
        $r.refused | Should Not Match 'AutoNumber'
        $script:edited | Should Be $false
        @($script:records).Count | Should Be 1
    }
    It 'without a transaction a refusal says what stands, and the save rules hold it' {
        Reset-Fake
        function Invoke-TiaWrite { param($Description, $Body, $RollbackIf) $null = & $Body; @{ transaction = $false; rolledBack = $false } }
        $script:comes[0].language = 'F_LAD'
        $script:comes += @(@{ object = 'S_1'; device = 'Plc1'; folder = 'libFolder'; type = 'S'; version = '0.0.1'; language = $null })
        $r = Invoke-LibraryEditTool ([pscustomobject]@{ name = 'X' })
        $r.refused | Should Match 'safety program'
        $r.refused | Should Match 'Without a transaction .*S_1, X stand as it left them'
        $script:editState.failed.ContainsKey('plc@plc1:x') | Should Be $true
        $script:editState.failed.ContainsKey('plc@plc1:s_1') | Should Be $true
    }
    It 'without a transaction a refusal names what it changed of the user, and holds that too' {
        Reset-Fake
        function Invoke-TiaWrite { param($Description, $Body, $RollbackIf) $null = & $Body; @{ transaction = $false; rolledBack = $false } }
        $made = [pscustomobject]@{ }
        Add-Member -InputObject $made ScriptMethod CreateFrom { param($ver, $mode) $script:records = @(@{ object = 'Other'; device = 'Plc1'; folder = ''; type = 'X'; version = '0.0.1' }) + @($script:comes) }
        $script:group = [pscustomobject]@{ Blocks = $made; Types = $made }
        $r = Invoke-LibraryEditTool ([pscustomobject]@{ name = 'X' })
        $r.refused | Should Match 'would change what is already in the PLC \(Other\)'
        $r.refused | Should Match 'Other, X stand as it left them'
        $script:editState.failed.ContainsKey('plc@plc1:other') | Should Be $true
    }
    It 'a throw inside it without a transaction names what stands, and the save rules hold it' {
        Reset-Fake
        $script:CommittedFacts = $null
        function Invoke-TiaWrite { param($Description, $Body, $RollbackIf) $null = & $Body; @{ transaction = $false; rolledBack = $false } }
        Add-Member -InputObject @($script:typeX.Versions)[0] ScriptMethod Edit { param($i) throw 'TIA said no to Edit' } -Force
        { Invoke-LibraryEditTool ([pscustomobject]@{ name = 'X' }) } | Should Throw 'TIA said no to Edit'
        @($script:CommittedFacts['objectsStanding'])[0].object | Should Be 'X'
        $script:editState.failed.ContainsKey('plc@plc1:x') | Should Be $true
    }
    It 'a throw inside it that a transaction took back names nothing' {
        Reset-Fake
        $script:CommittedFacts = $null
        function Invoke-TiaWrite { param($Description, $Body, $RollbackIf) $saved = @($script:records); try { $null = & $Body } catch { $script:records = $saved; throw }; @{ transaction = $true; rolledBack = $false } }
        Add-Member -InputObject @($script:typeX.Versions)[0] ScriptMethod Edit { param($i) throw 'TIA said no to Edit' } -Force
        { Invoke-LibraryEditTool ([pscustomobject]@{ name = 'X' }) } | Should Throw 'TIA said no to Edit'
        $script:CommittedFacts | Should Be $null
        @($script:editState.failed.Keys).Count | Should Be 0
    }
    It 'a folder read that fails after the instance was made still names the instance' {
        Reset-Fake
        $script:CommittedFacts = $null
        function Get-PlcFolderPaths { if (@($script:records).Count -gt 1) { throw 'no folders' } }
        { Invoke-LibraryEditTool ([pscustomobject]@{ name = 'X' }) } | Should Throw 'no folders'
        $script:CommittedFacts['instanceMade'].object | Should Be 'X'
    }
    It 'keeps summary and next within the response limit however many copies and folders it made' {
        Reset-Fake
        foreach ($n in 1..300) { $script:comes += @(@{ object = "LongTypeNameOfTheLibrary_$($n)_1"; device = 'Plc1'; folder = 'library/some/path/of/a/type'; type = "LongTypeNameOfTheLibrary_$n"; version = '0.0.1'; language = $null }) }
        function Get-PlcFolderPaths { if (@($script:records).Count -gt 1) { foreach ($n in 1..300) { "block`tlibrary/some/path/of/a/type/folder_$n" } } }
        $r = Invoke-LibraryEditTool ([pscustomobject]@{ name = 'X' })
        @($r.copiesMade).Count | Should Be 300
        @($r.foldersMade).Count | Should Be 300
        $r.next | Should Match 'and 290 more \(the types in copiesMade\)'
        $r.next | Should Match 'and 290 more \(foldersMade\)'
        $l = Limit-ToolResponse $r 20000 | ConvertFrom-Json
        $l.summary | Should Not Be '[in the log file]'
        $l.next | Should Not Be '[in the log file]'
    }
    It 'with a transaction a refusal holds nothing' {
        Reset-Fake
        $script:comes[0].language = 'F_LAD'
        $r = Invoke-LibraryEditTool ([pscustomobject]@{ name = 'X' })
        $r.refused | Should Not Match 'Without a transaction'
        @($script:editState.failed.Keys).Count | Should Be 0
        @($script:editState.pending.Keys).Count | Should Be 0
    }
}

Describe 'A version on old versions of what it contains' {
    function Get-BridgeSession { $script:relState }
    function Get-TiaLibrary { $script:fakeLib }
    function Get-TiaDeviceNames { @('Plc1') }
    function Get-LibraryTypeScope { 'plc' }
    function Add-LibraryLog { }
    function Get-LibraryDependsOn { @{ graph = @{ }; complete = $true; walked = 1 } }
    function Get-InWorkTypes { @{ complete = $true; walked = 0; types = @($script:fakeTypes | ForEach-Object { $t = $_; @($t.Versions | Where-Object { $_.State -eq 'InWork' }) | ForEach-Object { @{ type = $t.Name; inWork = [string]$_.VersionNumber } } }) } }
    function Invoke-TiaWrite { param($Description, $Body, $RollbackIf)
        $states = @($script:fakeTypes | ForEach-Object { $_.Versions } | ForEach-Object { @{ v = $_; state = $_.State; def = $_.IsDefault } })
        $out = @(& $Body)
        $back = [bool]($RollbackIf -and (& $RollbackIf))
        if ($back -and $script:relTransaction) { foreach ($x in $states) { $x.v.State = $x.state; $x.v.IsDefault = $x.def } }
        @{ output = $out; transaction = $script:relTransaction; rolledBack = ($back -and $script:relTransaction) }
    }
    function Set-Fake([string]$Uses) {
        $script:relState = New-SessionState; Register-Archive $script:relState
        $script:contains = @{}; $script:plainUsed = @{}; $script:relTransaction = $true
        $script:Bridge = @{ repo = [string]$TestDrive; settings = @{} }
        $s = New-FakeType 'S' @((New-FakeVersion '0.0.1' 'Committed'), (New-FakeVersion '0.0.2' 'Committed' $true))
        $x = New-FakeType 'X' @((New-FakeVersion '0.0.1' 'Committed' $true), (New-FakeVersion '0.0.2' 'InWork'))
        @($x.Versions)[1].Dependencies = @([pscustomobject]@{ VersionNumber = [version]$Uses; TypeObject = $s })
        Set-FakeLibrary @($x, $s)
        $x
    }

    It 'refuses it, names them, and releases nothing' {
        $x = Set-Fake '0.0.1'
        $r = Invoke-LibraryReleaseTool ([pscustomobject]@{ name = 'X'; comment = 'c' })
        $r.ok | Should Be $false
        @($r.onOldVersions) | Should Be 'S (uses 0.0.1, default 0.0.2)'
        $r.refused | Should Match 'would burn a version'
        $r.refused | Should Match 'library_update_usages'
        @($x.Versions)[1].State | Should Be 'InWork'
        @($script:relState.pending.Keys).Count | Should Be 0
    }
    It 'releases it on the new versions' {
        $x = Set-Fake '0.0.2'
        $r = Invoke-LibraryReleaseTool ([pscustomobject]@{ name = 'X'; comment = 'c' })
        $r.ok | Should Be $true
        @($x.Versions)[1].State | Should Be 'Committed'
        $r.Contains('onOldVersions') | Should Be $false
    }
    It 'names them when there is no transaction to take it back' {
        $null = Set-Fake '0.0.1'
        $script:relTransaction = $false
        $r = Invoke-LibraryReleaseTool ([pscustomobject]@{ name = 'X'; comment = 'c' })
        $r.ok | Should Be $true
        @($r.onOldVersions) | Should Be 'S (uses 0.0.1, default 0.0.2)'
        $r.summary | Should Match 'released on old versions'
    }
}

Describe 'library_edit_type with copies: the order' {
    It 'sends to the update first, and export only after it' {
        $s = Format-InstanceMade 'X' @{ object = 'X'; type = 'X'; version = '0.0.1'; folder = 'f' } @(@{ object = 'S_1'; type = 'S'; version = '0.0.1'; folder = 'f' })
        $s | Should Match 'until that update it cannot be released'
    }
}

Describe 'One list, one answer about who decided' {
    function Get-BridgeSession { $script:state }
    function Get-TiaLibrary { $script:fakeLib }
    function Get-SafetyProgramRefusal { $null }
    function Get-TiaDeviceNames { @('Plc1') }
    function Get-LibraryTypeScope { 'plc' }
    function Add-LibraryLog { $script:logged += @($args[0]) }
    function Get-UpdateScopes { @() }
    function Get-LibraryDependsOn { @{ graph = @{ }; complete = $true; walked = 1 } }
    function Get-InWorkTypes { @{ complete = $true; walked = 0; types = @($script:fakeTypes | ForEach-Object { $t = $_; @($t.Versions | Where-Object { $_.State -eq 'InWork' }) | ForEach-Object { @{ type = $t.Name; inWork = [string]$_.VersionNumber } } }) } }
    function Invoke-CompileEveryDevice { @{ items = @(); errors = 0 } }
    function Invoke-ProjectUpdate { @{ transaction = $true } }
    function Invoke-TiaWrite { param($Description, $Body, $RollbackIf) @{ output = @(& $Body); transaction = $true; rolledBack = $false } }
    function Get-TiaProject { $l = [pscustomobject]@{ }; Add-Member -InputObject $l ScriptMethod UpdateCheck { param($p, $m) @{ } }; [pscustomobject]@{ ProjectLibrary = $l } }
    function ConvertTo-ResultTree { @{ } }
    function Get-TiaSoftwareList { @(@{ kind = 'plc'; device = 'Plc1' }) }
    function Get-LibraryStale { @{ stale = $script:staleNow; complete = $true; walked = 1; deps = @{ } } }
    function Test-TypeObjectHasInstance { param($Type) $script:withInstance -contains $Type.Name }
    function Get-TypesLeftBehind { @{ types = @($script:leftNow); complete = $script:leftComplete; deps = @{ } } }
    function Get-PlcFolderPaths { $script:foldersNow }

    function Get-Left([string]$Name) { @{ type = $Name; version = '0.0.1'; uses = @('S (uses 0.0.1, default 0.0.2)') } }
    function Reset-Fake {
        $script:repo = Join-Path $TestDrive ([guid]::NewGuid().ToString('N'))
        New-Item -ItemType Directory -Force -Path (Join-Path $script:repo 'library\changes') | Out-Null
        $script:Bridge = @{ repo = $script:repo; settings = @{ } }
        $script:state = New-SessionState; Register-Archive $script:state
        $script:contains = @{ }; $script:plainUsed = @{ }; $script:logged = @(); $script:leftComplete = $true; $script:foldersNow = @(); $script:staleNow = @{ }; $script:withInstance = @()
        $script:leftNow = @((Get-Left 'X'), (Get-Left 'Y'))
        # S and G released; W in work; X and Y as a close without saving left them: on 0.0.1, nothing in work
        Set-FakeLibrary @(
            (New-FakeType 'S' @((New-FakeVersion '0.0.1' 'Committed'), (New-FakeVersion '0.0.2' 'Committed' $true))),
            (New-FakeType 'X' @(New-FakeVersion '0.0.1' 'Committed' $true)),
            (New-FakeType 'Y' @(New-FakeVersion '0.0.1' 'Committed' $true)),
            (New-FakeType 'G' @((New-FakeVersion '0.0.1' 'Committed'), (New-FakeVersion '0.0.2' 'Committed' $true))),
            (New-FakeType 'W' @((New-FakeVersion '0.0.1' 'Committed' $true), (New-FakeVersion '0.0.2' 'InWork'))))
    }
    # the same library, with X and Y in the state named: InWork, or released on 0.0.2
    function Set-YesTypes([string]$State) {
        $typeAtTwo = { param($n) if ($State -eq 'InWork') { New-FakeType $n @((New-FakeVersion '0.0.1' 'Committed' $true), (New-FakeVersion '0.0.2' 'InWork')) } else { New-FakeType $n @((New-FakeVersion '0.0.1' 'Committed'), (New-FakeVersion '0.0.2' 'Committed' $true)) } }
        Set-FakeLibrary @(
            (New-FakeType 'S' @((New-FakeVersion '0.0.1' 'Committed'), (New-FakeVersion '0.0.2' 'Committed' $true))),
            (& $typeAtTwo 'X'), (& $typeAtTwo 'Y'),
            (New-FakeType 'G' @((New-FakeVersion '0.0.1' 'Committed'), (New-FakeVersion '0.0.2' 'Committed' $true))),
            (New-FakeType 'W' @((New-FakeVersion '0.0.1' 'Committed' $true), (New-FakeVersion '0.0.2' 'InWork'))))
    }
    function Get-TypeRow([string]$Name, [string]$InWork = '') { @{ name = $Name; class = 'PlcTypeLibraryType'; folder = ''; released = '0.0.1'; inWork = $InWork } }
    # the older change, as a yes on X and Y leaves it: open, both in work by the bridge, folders made
    function Save-YesChange {
        $a = New-ChangeRecord -Root 'S' -From '0.0.1' -To '0.0.2' -Types @((Get-TypeRow 'S' '0.0.2'), (Get-TypeRow 'X'), (Get-TypeRow 'Y')) -Levels @{ S = 0; X = 1; Y = 2 } -At ([datetime]'2026-11-04 01:35')
        $a.types.S.releasedAs = '0.0.2'; $a.updated = $true
        $a.leftBehindAnswer = 'yes'; $a.leftBehindAsked = @('X', 'Y'); $a.leftBehindRefused = @{ }
        foreach ($n in 'X', 'Y') { $a.types[$n].inWork = '0.0.2'; $a.types[$n].inWorkBy = 'bridge' }
        $a.temporaryFolder = 'LibraryUpdateTemp'; $a.foldersMade = @(@{ kind = 'block'; folder = 'LibraryUpdateTemp'; device = 'Plc1' })
        $a.usesOutside = @('S')
        $a.leftBehind = @()
        $null = Save-ChangeRecord $script:repo $a
        $a.id
    }
    # X and Y through to their release in the record of that change
    function Set-YesReleased([string]$Id) {
        $rec = Read-ChangeRecord $script:repo $Id
        foreach ($n in 'X', 'Y') { $rec.types[$n].inWork = ''; $rec.types[$n].releasedAs = '0.0.2' }
        $null = Save-ChangeRecord $script:repo $rec
    }
    # the later change: G released, W its last type, in work and approved
    function Save-LaterChange {
        $b = New-ChangeRecord -Root 'G' -From '0.0.1' -To '0.0.2' -Types @((Get-TypeRow 'G' '0.0.2'), (Get-TypeRow 'W' '0.0.2')) -Levels @{ G = 0; W = 1 } -At ([datetime]'2026-11-04 01:41')
        $b.types.G.releasedAs = '0.0.2'; $b.updated = $true
        $b.types.W.inWorkBy = 'tia'; $b.types.W.approved = $true
        $null = Save-ChangeRecord $script:repo $b
        $b.id
    }
    function Read-Report([string]$Id) { Get-Content (Join-Path $script:repo "library\changes\$Id.md") -Raw }

    Context 'a yes a close without saving took back' {
        It 'the record of it reads left-behind, the list, not decided, no types in work, no folders' {
            Reset-Fake
            $a = Save-YesChange
            Get-LiveChange $script:fakeLib | Should Be $null
            $rec = Read-ChangeRecord $script:repo $a
            $rec.status | Should Be 'left-behind'
            $rec.leftBehindAnswer | Should Be $null
            $rec.leftBehindAsked | Should Be $null
            $rec.temporaryFolder | Should Be $null
            @($rec.foldersMade | Where-Object { $_ }).Count | Should Be 0
            @($rec.usesOutside | Where-Object { $_ }).Count | Should Be 0
            @($rec.leftBehind | ForEach-Object { $_.type }) -join ',' | Should Be 'X,Y'
            $rec.types.X.inWork | Should Be ''
            $rec.types.X.inWorkBy | Should Be ''
            $report = Read-Report $a
            $report | Should Match 'Status: left-behind'
            $report | Should Match 'Not decided yet'
            $report | Should Not Match 'The user chose'
            $report | Should Not Match 'in work \(by the bridge\)'
            $report | Should Not Match 'Temporary folder:'
            $report | Should Match '`X` 0\.0\.1: uses'
            $script:logged -join ' ' | Should Match "$a.*yes.*no longer in the project"
        }
        It 'the same when asked for that change by its id' {
            Reset-Fake
            $a = Save-YesChange
            (Get-LiveChange $script:fakeLib -Id $a).leftBehindAnswer | Should Be $null
            (Read-ChangeRecord $script:repo $a).status | Should Be 'left-behind'
        }
        It 'a release the record holds of it goes too, when that version is not in the library' {
            Reset-Fake
            $a = Save-YesChange
            $rec = Read-ChangeRecord $script:repo $a
            $rec.types.X.inWork = ''; $rec.types.X.releasedAs = '0.0.2'
            $null = Save-ChangeRecord $script:repo $rec
            Get-LiveChange $script:fakeLib | Should Be $null
            $rec = Read-ChangeRecord $script:repo $a
            $rec.leftBehindAnswer | Should Be $null
            $rec.types.X.releasedAs | Should Be ''
        }
        It 'also when it had reached its end, and the record read done' {
            Reset-Fake
            $a = Save-YesChange
            Set-YesReleased $a
            (Read-ChangeRecord $script:repo $a).status | Should Be 'done'
            $r = @{ summary = 's'; next = 'n' }
            Add-LeftBehindFacts $r $script:fakeLib
            $r.summary | Should Match 'Not decided yet'
            $r.summary | Should Not Match 'The user chose'
            $rec = Read-ChangeRecord $script:repo $a
            $rec.status | Should Be 'left-behind'
            $rec.leftBehindAnswer | Should Be $null
        }
        It 'on a list not fully read the yes goes, and the change stays open until a read that is whole' {
            Reset-Fake
            $a = Save-YesChange
            $script:leftComplete = $false
            (Get-LiveChange $script:fakeLib).id | Should Be $a
            $rec = Read-ChangeRecord $script:repo $a
            $rec.leftBehindAnswer | Should Be $null
            $rec.status | Should Be 'open'
            $rec.staleUnread | Should Match 'time limit'
            $script:leftComplete = $true
            $null = Invoke-LibraryReviewTool ([pscustomobject]@{ })
            $rec = Read-ChangeRecord $script:repo $a
            $rec.status | Should Be 'left-behind'
            @($rec.leftBehind | ForEach-Object { $_.type }) -join ',' | Should Be 'X,Y'
        }
        It 'a folder that stands stays to be deleted, made by an earlier yes or an edit' {
            Reset-Fake
            $a = Save-YesChange
            $rec = Read-ChangeRecord $script:repo $a
            $rec.foldersMade = @(@($rec.foldersMade) + @(@{ kind = 'type'; folder = 'Earlier'; device = 'Plc1' }))
            $null = Save-ChangeRecord $script:repo $rec
            $script:foldersNow = @("type`tEarlier")
            $null = Get-LiveChange $script:fakeLib
            $rec = Read-ChangeRecord $script:repo $a
            @($rec.foldersMade | ForEach-Object { $_.folder }) -join ',' | Should Be 'Earlier'
            $rec.temporaryFolder | Should Be $null
            Read-Report $a | Should Not Match 'Temporary folder:'
            Format-FolderCleanup $rec | Should Match 'kind type, folder Earlier'
        }
        It 'the temporary folder stays while it stands, as an earlier yes made it and was saved' {
            Reset-Fake
            $a = Save-YesChange
            $script:foldersNow = @("block`tLibraryUpdateTemp")
            $null = Get-LiveChange $script:fakeLib
            $rec = Read-ChangeRecord $script:repo $a
            $rec.leftBehindAnswer | Should Be $null
            $rec.temporaryFolder | Should Be 'LibraryUpdateTemp'
        }
        It 'a yes through to its end that a close took back goes too, also with a later change newer than it' {
            Reset-Fake
            $a = Save-YesChange
            Set-YesReleased $a
            $null = Save-LaterChange
            $r = Invoke-LibraryReleaseTool ([pscustomobject]@{ name = 'W'; comment = 'c' })
            $r.summary | Should Match 'Not decided yet'
            $rec = Read-ChangeRecord $script:repo $a
            $rec.status | Should Be 'left-behind'
            $rec.leftBehindAnswer | Should Be $null
            $rec.types.X.releasedAs | Should Be ''
        }
        It 'a change that ended otherwise stays as it was' {
            Reset-Fake
            $a = Save-YesChange
            $rec = Read-ChangeRecord $script:repo $a
            $rec.status = 'superseded'
            $null = Save-ChangeRecord $script:repo $rec
            $null = Get-LiveChange $script:fakeLib -Id $a
            (Read-ChangeRecord $script:repo $a).leftBehindAnswer | Should Be 'yes'
        }
        It 'a change with no changed type is abandoned, and forgets it as well' {
            Reset-Fake
            $r = New-LeftBehindRecord ([datetime]'2026-11-04 01:35')
            $r.leftBehindAnswer = 'yes'; $r.leftBehindAsked = @('X'); $r.temporaryFolder = 'T'
            $r.foldersMade = @(@{ kind = 'block'; folder = 'T'; device = 'Plc1' })
            $r.types['X'] = [ordered]@{ level = 1; kind = 'code block'; folder = ''; released = '0.0.1'; inWork = '0.0.2'; inWorkBy = 'bridge'; review = $null; approved = $false; releasedAs = '' }
            $null = Save-ChangeRecord $script:repo $r
            Get-LiveChange $script:fakeLib | Should Be $null
            $rec = Read-ChangeRecord $script:repo $r.id
            $rec.status | Should Be 'abandoned'
            $rec.leftBehindAnswer | Should Be $null
            $rec.types.X.inWork | Should Be ''
            $report = Read-Report $r.id
            $report | Should Not Match 'The user chose'
            $report | Should Not Match 'in work \(by the bridge\)'
            $report | Should Not Match 'Temporary folder:'
        }
        It 'a change abandoned as its own version was discarded is not taken for a close' {
            Reset-Fake
            $a = Save-YesChange
            $rec = Read-ChangeRecord $script:repo $a
            Set-ChangeAbandoned $script:repo $rec 'its version in work was discarded'
            (Read-ChangeRecord $script:repo $a).leftBehindAnswer | Should Be 'yes'
        }
        # as Add-ChangeLeftBehindTypes leaves it: in work by the bridge, released holds the version at the yes
        function Save-RootYes([string[]]$Listed) {
            $a = New-ChangeRecord -Root 'S' -From '0.0.1' -To '0.0.2' -Types @((Get-TypeRow 'S' '0.0.2'), (Get-TypeRow 'X')) -Levels @{ S = 0; X = 1 } -At ([datetime]'2026-11-04 01:35')
            $a.updated = $true
            $a.leftBehindAnswer = 'yes'; $a.leftBehindAsked = @($Listed); $a.leftBehindRefused = @{ }
            foreach ($n in $Listed) { $a.types[$n].released = '0.0.2'; $a.types[$n].inWork = '0.0.3'; $a.types[$n].inWorkBy = 'bridge'; $a.types[$n].releasedAs = '' }
            if ($Listed -notcontains 'X') { $a.types.X.releasedAs = '0.0.1' }
            $a.temporaryFolder = 'LibraryUpdateTemp'; $a.foldersMade = @(@{ kind = 'block'; folder = 'LibraryUpdateTemp'; device = 'Plc1' })
            $a.leftBehind = @()
            $null = Save-ChangeRecord $script:repo $a
            $a.id
        }
        It 'the changed type alone on the list: back to its release, left-behind, not decided, nothing in work' {
            Reset-Fake
            $script:leftNow = @(Get-Left 'S')
            $a = Save-RootYes @('S')
            $r = @{ summary = 's'; next = 'n' }
            Add-LeftBehindFacts $r $script:fakeLib
            $r.summary | Should Match 'Not decided yet'
            $r.summary | Should Not Match 'The user chose'
            $rec = Read-ChangeRecord $script:repo $a
            $rec.status | Should Be 'left-behind'
            $rec.leftBehindAnswer | Should Be $null
            $rec.to | Should Be '0.0.2'
            $rec.types.S.releasedAs | Should Be '0.0.2'
            $rec.types.S.released | Should Be '0.0.1'
            $rec.types.S.inWorkBy | Should Be 'change'
            $report = Read-Report $a
            $report | Should Not Match 'in work \(by the bridge\)'
            $report | Should Match '`S` - data type - released 0\.0\.2'
        }
        It 'the changed type and another on the list: the change does not stay open, and a later update does not name it' {
            Reset-Fake
            $script:leftNow = @((Get-Left 'S'), (Get-Left 'X'))
            $a = Save-RootYes @('S', 'X')
            $b = Save-LaterChange
            $null = Invoke-LibraryReleaseTool ([pscustomobject]@{ name = 'W'; comment = 'c' })
            (Read-ChangeRecord $script:repo $a).status | Should Be 'left-behind'
            $u = Invoke-LibraryUpdateTool ([pscustomobject]@{ })
            $u.change | Should Be $null
            $u.next | Should Not Match 'library_approve'
        }
        It 'the changed type through to its release, the number gone: back to the one before, not abandoned' {
            Reset-Fake
            $script:leftNow = @(Get-Left 'S')
            $a = Save-RootYes @('S')
            $rec = Read-ChangeRecord $script:repo $a
            $rec.to = '0.0.3'; $rec.types.S.inWork = ''; $rec.types.S.releasedAs = '0.0.3'
            $null = Save-ChangeRecord $script:repo $rec
            (Find-CurrentChange $script:fakeLib).id | Should Be $a
            $rec = Read-ChangeRecord $script:repo $a
            $rec.status | Should Be 'left-behind'
            $rec.to | Should Be '0.0.2'
            $rec.leftBehindAnswer | Should Be $null
        }
        It 'the changed type in work and standing in TIA: the yes stands' {
            Reset-Fake
            Set-FakeLibrary @((New-FakeType 'S' @((New-FakeVersion '0.0.2' 'Committed' $true), (New-FakeVersion '0.0.3' 'InWork'))), (New-FakeType 'X' @(New-FakeVersion '0.0.1' 'Committed' $true)))
            $a = Save-RootYes @('S')
            (Get-LiveChange $script:fakeLib).id | Should Be $a
            (Read-ChangeRecord $script:repo $a).leftBehindAnswer | Should Be 'yes'
        }
        It 'the changed type refused on the way, and the others gone: its own release says nothing about the yes' {
            Reset-Fake
            $script:leftNow = @((Get-Left 'S'), (Get-Left 'X'))
            $a = Save-RootYes @('X')
            $rec = Read-ChangeRecord $script:repo $a
            $rec.types.S.releasedAs = '0.0.2'
            $rec.leftBehindAsked = @('S', 'X'); $rec.leftBehindRefused = @{ S = 'know-how protected' }
            $null = Save-ChangeRecord $script:repo $rec
            $null = Get-LiveChange $script:fakeLib
            (Read-ChangeRecord $script:repo $a).leftBehindAnswer | Should Be $null
        }
        It 'a change with no changed type that reached done is abandoned too, at any library call, and forgets it' {
            foreach ($call in { Find-CurrentChange $script:fakeLib }, { Get-EditYesRefusal $script:fakeLib 'X' }, { Add-LeftBehindFacts @{ summary = 's' } $script:fakeLib }) {
                Reset-Fake
                $r = New-LeftBehindRecord ([datetime]'2026-11-04 01:35')
                $r.leftBehindAnswer = 'yes'; $r.leftBehindAsked = @('X'); $r.temporaryFolder = 'T'; $r.foldersMade = @(@{ kind = 'block'; folder = 'T'; device = 'Plc1' })
                $r.types['X'] = [ordered]@{ level = 1; kind = 'code block'; folder = ''; released = '0.0.1'; inWork = ''; inWorkBy = ''; review = $null; approved = $true; releasedAs = '0.0.2' }
                $r.leftBehind = @()
                $null = Save-ChangeRecord $script:repo $r
                (Read-ChangeRecord $script:repo $r.id).status | Should Be 'done'
                $out = & $call
                @($out | Where-Object { $_ -and $_.id -eq $r.id }).Count | Should Be 0
                $rec = Read-ChangeRecord $script:repo $r.id
                $rec.status | Should Be 'abandoned'
                $rec.leftBehindAnswer | Should Be $null
                $rec.types.X.releasedAs | Should Be ''
                $report = Read-Report $r.id
                $report | Should Not Match 'The user chose'
                $report | Should Not Match 'released 0\.0\.2'
                $report | Should Not Match 'Temporary folder:'
            }
        }
        It 'a change with no changed type keeps what stands of an earlier yes, and is not abandoned for the later one' {
            Reset-Fake
            Set-FakeLibrary @(
                (New-FakeType 'X' @((New-FakeVersion '0.0.1' 'Committed'), (New-FakeVersion '0.0.2' 'Committed' $true))),
                (New-FakeType 'Y' @(New-FakeVersion '0.0.1' 'Committed' $true)))
            $r = New-LeftBehindRecord ([datetime]'2026-11-04 01:35')
            $r.leftBehindAnswer = 'yes'; $r.leftBehindAsked = @('Y'); $r.temporaryFolder = 'T'
            $r.types['X'] = [ordered]@{ level = 1; kind = 'code block'; folder = ''; released = '0.0.1'; inWork = ''; inWorkBy = ''; review = $null; approved = $true; releasedAs = '0.0.2' }
            $r.types['Y'] = [ordered]@{ level = 1; kind = 'code block'; folder = ''; released = '0.0.1'; inWork = '0.0.2'; inWorkBy = 'bridge'; review = $null; approved = $false; releasedAs = '' }
            $script:leftNow = @(Get-Left 'Y')
            $null = Save-ChangeRecord $script:repo $r
            $null = Get-LiveChange $script:fakeLib
            $rec = Read-ChangeRecord $script:repo $r.id
            $rec.status | Should Be 'left-behind'
            $rec.leftBehindAnswer | Should Be $null
            $rec.types.X.releasedAs | Should Be '0.0.2'
            $rec.types.Y.inWork | Should Be ''
        }
        It 'the changed type a yes put in work, discarded: back to its release, and the change comes to its end' {
            function Get-DiscardRefusal { $null }
            function Get-TypeInstances { @() }
            function Register-LibraryTypeWrite { }
            function Find-LibraryType { param($L, $N) @{ name = $N; obj = @($script:fakeTypes | Where-Object { $_.Name -eq $N })[0]; folder = '' } }
            Reset-Fake
            $work = New-FakeVersion '0.0.3' 'InWork'
            Add-Member -InputObject $work ScriptMethod Discard { $t = @($script:fakeTypes | Where-Object { $_.Name -eq 'S' })[0]; $t.Versions = @($t.Versions | Where-Object { [string]$_.State -ne 'InWork' }) }
            Set-FakeLibrary @(
                (New-FakeType 'S' @((New-FakeVersion '0.0.1' 'Committed'), (New-FakeVersion '0.0.2' 'Committed' $true), $work)),
                (New-FakeType 'X' @(New-FakeVersion '0.0.1' 'Committed' $true)))
            $script:leftNow = @()
            $a = Save-RootYes @('S')
            $script:foldersNow = @("block`tLibraryUpdateTemp")
            # its temporary instance still stands, on the old versions
            $script:staleNow = @{ S = @('X (uses 0.0.1, default 0.0.2)') }; $script:withInstance = @('S')
            $d = Invoke-LibraryDiscardTool ([pscustomobject]@{ name = 'S' })
            $d.ok | Should Be $true
            $rec = Read-ChangeRecord $script:repo $a
            $rec.types.S.releasedAs | Should Be '0.0.2'
            $rec.types.S.inWork | Should Be '0.0.2'
            $rec.types.S.inWorkBy | Should Be 'change'
            $rec.types.S.released | Should Be '0.0.1'
            $rec.to | Should Be '0.0.2'
            $rec.status | Should Be 'open'
            @($d.stale) | Should Be 'S'
            # the update removes that instance, and the type is on the list again
            $script:withInstance = @(); $script:leftNow = @(Get-Left 'S')
            $u = Invoke-LibraryUpdateTool ([pscustomobject]@{ })
            $u.change | Should Be $a
            $u.next | Should Not Match 'library_approve'
            (Read-ChangeRecord $script:repo $a).status | Should Be 'left-behind'
            $x = Invoke-LibraryLeftBehindTool ([pscustomobject]@{ answer = 'no' })
            $x.change | Should Be $a
            $x.status | Should Be 'left-behind'
            (Read-ChangeRecord $script:repo $a).leftBehindAnswer | Should Be 'no'
        }
        It 'a read of the folders that fails keeps them named, and says so in the report and the log' {
            Reset-Fake
            function Get-PlcFolderPaths { throw 'the folders could not be read' }
            $a = Save-YesChange
            Get-LiveChange $script:fakeLib | Should Be $null
            $rec = Read-ChangeRecord $script:repo $a
            $rec.leftBehindAnswer | Should Be $null
            @($rec.foldersMade | ForEach-Object { $_.folder }) -join ',' | Should Be 'LibraryUpdateTemp'
            $rec.temporaryFolder | Should Be 'LibraryUpdateTemp'
            Read-Report $a | Should Match 'still stand was not read, so they stay named: Plc1: .*could not be read'
            $script:logged -join ' ' | Should Match 'still stand was not read.*could not be read'
        }
        It 'an edit as the first call clears a yes through to its end, before it can make its number stand again' {
            Reset-Fake
            $a = Save-YesChange
            Set-YesReleased $a
            (Read-ChangeRecord $script:repo $a).status | Should Be 'done'
            Get-EditYesRefusal $script:fakeLib 'Y' | Should Be $null
            $rec = Read-ChangeRecord $script:repo $a
            $rec.status | Should Be 'left-behind'
            $rec.leftBehindAnswer | Should Be $null
            $rec.types.Y.releasedAs | Should Be ''
            Read-Report $a | Should Not Match 'Temporary folder:'
        }
        It 'an edit that looks at the yes in work finds it gone, and is not refused for it' {
            Reset-Fake
            $a = Save-YesChange
            Get-EditYesRefusal $script:fakeLib 'G' | Should Be $null
            (Read-ChangeRecord $script:repo $a).leftBehindAnswer | Should Be $null
        }
    }

    Context 'a yes that stands keeps its record' {
        It 'in work in TIA: the change stays open with the answer and its folders' {
            Reset-Fake
            Set-YesTypes 'InWork'
            $script:leftNow = @()
            $a = Save-YesChange
            (Get-LiveChange $script:fakeLib).id | Should Be $a
            $rec = Read-ChangeRecord $script:repo $a
            $rec.status | Should Be 'open'
            $rec.leftBehindAnswer | Should Be 'yes'
            $rec.temporaryFolder | Should Be 'LibraryUpdateTemp'
        }
        It 'one of them in work is enough' {
            Reset-Fake
            Set-FakeLibrary @(
                (New-FakeType 'S' @((New-FakeVersion '0.0.1' 'Committed'), (New-FakeVersion '0.0.2' 'Committed' $true))),
                (New-FakeType 'X' @(New-FakeVersion '0.0.1' 'Committed' $true)),
                (New-FakeType 'Y' @((New-FakeVersion '0.0.1' 'Committed' $true), (New-FakeVersion '0.0.2' 'InWork'))))
            $null = Save-YesChange
            (Get-LiveChange $script:fakeLib).leftBehindAnswer | Should Be 'yes'
        }
        It 'finished: released and standing, the answer stays' {
            Reset-Fake
            Set-YesTypes 'Committed'
            $script:leftNow = @()
            $a = Save-YesChange
            Set-YesReleased $a
            (Find-CurrentChange $script:fakeLib).leftBehindAnswer | Should Be 'yes'
            (Read-ChangeRecord $script:repo $a).status | Should Be 'done'
        }
        It 'all refused, nothing put in work: what was refused stays said' {
            Reset-Fake
            $a = Save-YesChange
            $rec = Read-ChangeRecord $script:repo $a
            foreach ($n in 'X', 'Y') { $rec.types[$n].inWork = ''; $rec.types[$n].inWorkBy = '' }
            $rec.Remove('temporaryFolder'); $rec.Remove('foldersMade')
            $rec.leftBehindRefused = @{ X = 'know-how protected'; Y = 'it contains X, refused' }
            Set-RecordLeftBehind $rec @{ types = $script:leftNow; failed = $false; unread = '' }
            $null = Save-ChangeRecord $script:repo $rec
            $r = @{ summary = 's'; next = 'n' }
            Add-LeftBehindFacts $r $script:fakeLib
            $r.summary | Should Match 'Refused on the way: X \(know-how protected\)'
            (Read-ChangeRecord $script:repo $a).leftBehindAnswer | Should Be 'yes'
        }
        It 'all discarded: the answer stays, as a discard does not end the matter' {
            Reset-Fake
            $a = Save-YesChange
            $rec = Read-ChangeRecord $script:repo $a
            foreach ($n in 'X', 'Y') { $rec.types[$n].inWork = ''; $rec.types[$n].inWorkBy = '' }
            Set-RecordLeftBehind $rec @{ types = $script:leftNow; failed = $false; unread = '' }
            $null = Save-ChangeRecord $script:repo $rec
            $r = @{ summary = 's'; next = 'n' }
            Add-LeftBehindFacts $r $script:fakeLib
            $r.summary | Should Match 'The user chose to bring them up to date'
            @((Read-ChangeRecord $script:repo $a).foldersMade | Where-Object { $_ }).Count | Should Be 1
        }
    }

    Context 'the last type of a later change, step by step' {
        It 'library_release_type says not decided, from its own record, in the result, its next and the log' {
            Reset-Fake
            $a = Save-YesChange
            $b = Save-LaterChange
            $r = Invoke-LibraryReleaseTool ([pscustomobject]@{ name = 'W'; comment = 'c' })
            $r.status | Should Be 'left-behind'
            @($r.typesLeftBehind | ForEach-Object { $_.type }) -join ',' | Should Be 'X,Y'
            foreach ($text in $r.summary, $r.next, $script:logged[-1]) {
                $text | Should Match 'Not decided yet: the user is asked whether to bring them up to date through a temporary folder'
                $text | Should Match 'Ask the user, once, with this list'
                $text | Should Not Match 'The user chose'
            }
            $script:logged[-1] | Should Match 'released'
            $rec = Read-ChangeRecord $script:repo $b
            $rec.status | Should Be 'left-behind'
            $rec.leftBehindAnswer | Should Be $null
            Read-Report $b | Should Match 'Not decided yet: the user is asked whether to bring them up to date through a temporary folder'
            $older = Read-ChangeRecord $script:repo $a
            $older.status | Should Be 'left-behind'
            $older.leftBehindAnswer | Should Be $null
        }
        It 'library_update_usages right after belongs to no open change, sends to no approval, and says the same' {
            Reset-Fake
            $a = Save-YesChange
            $b = Save-LaterChange
            $null = Invoke-LibraryReleaseTool ([pscustomobject]@{ name = 'W'; comment = 'c' })
            $r = Invoke-LibraryUpdateTool ([pscustomobject]@{ })
            $r.ok | Should Be $true
            $r.change | Should Be $null
            $r.summary | Should Match 'belongs to no open library change'
            $r.next | Should Not Match 'library_approve'
            foreach ($text in $r.summary, $r.next) {
                $text | Should Match 'Not decided yet'
                $text | Should Not Match 'The user chose'
            }
            (Read-ChangeRecord $script:repo $a).status | Should Be 'left-behind'
            (Read-ChangeRecord $script:repo $b).status | Should Be 'left-behind'
        }
        It 'library_review right after says the same, and turns no record' {
            Reset-Fake
            $a = Save-YesChange
            $b = Save-LaterChange
            $null = Invoke-LibraryReleaseTool ([pscustomobject]@{ name = 'W'; comment = 'c' })
            $null = Invoke-LibraryUpdateTool ([pscustomobject]@{ })
            $r = Invoke-LibraryReviewTool ([pscustomobject]@{ })
            $r.summary | Should Match 'Not decided yet'
            $r.summary | Should Not Match 'The user chose'
            (Read-ChangeRecord $script:repo $a).status | Should Be 'left-behind'
            (Read-ChangeRecord $script:repo $a).leftBehindAnswer | Should Be $null
            (Read-ChangeRecord $script:repo $b).status | Should Be 'left-behind'
        }
        It 'an answer then goes on the later change, not on the older one' {
            Reset-Fake
            $a = Save-YesChange
            $b = Save-LaterChange
            $null = Invoke-LibraryReleaseTool ([pscustomobject]@{ name = 'W'; comment = 'c' })
            $x = Invoke-LibraryLeftBehindTool ([pscustomobject]@{ answer = 'no' })
            $x.change | Should Be $b
            (Read-ChangeRecord $script:repo $a).leftBehindAnswer | Should Be $null
            $x.next | Should Match 'as the user chose'
        }
    }

    Context 'an older change whose yes stands, while a later one reaches its end' {
        function Set-OlderStands {
            Reset-Fake
            Set-YesTypes 'InWork'
            $script:leftNow = @(Get-Left 'Q')
        }
        It 'the later change speaks from its own record, the older keeps its answer' {
            Set-OlderStands
            $a = Save-YesChange
            $null = Save-LaterChange
            $r = Invoke-LibraryReleaseTool ([pscustomobject]@{ name = 'W'; comment = 'c' })
            $r.status | Should Be 'left-behind'
            $r.summary | Should Match 'Not decided yet'
            $r.summary | Should Not Match 'The user chose'
            $rec = Read-ChangeRecord $script:repo $a
            $rec.status | Should Be 'open'
            $rec.leftBehindAnswer | Should Be 'yes'
        }
        It 'a refused yes of the older change does not speak for the later one' {
            Set-OlderStands
            $a = Save-YesChange
            $rec = Read-ChangeRecord $script:repo $a
            $rec.leftBehindRefused = @{ Q = 'know-how protected' }
            $null = Save-ChangeRecord $script:repo $rec
            $null = Save-LaterChange
            $r = Invoke-LibraryReleaseTool ([pscustomobject]@{ name = 'W'; comment = 'c' })
            $r.summary | Should Match 'Not decided yet'
            $r.summary | Should Not Match 'Refused on the way'
        }
        It 'an update then belongs to the change that is open' {
            Set-OlderStands
            $a = Save-YesChange
            $null = Save-LaterChange
            $null = Invoke-LibraryReleaseTool ([pscustomobject]@{ name = 'W'; comment = 'c' })
            (Invoke-LibraryUpdateTool ([pscustomobject]@{ })).change | Should Be $a
        }
    }

    It 'a finished yes of an older change does not speak for a later change' {
        Reset-Fake
        Set-YesTypes 'Committed'
        $script:leftNow = @(Get-Left 'Q')
        $a = Save-YesChange
        Set-YesReleased $a
        $null = Save-LaterChange
        $r = Invoke-LibraryReleaseTool ([pscustomobject]@{ name = 'W'; comment = 'c' })
        $r.summary | Should Match 'Not decided yet'
        $r.summary | Should Not Match 'The user chose'
        (Read-ChangeRecord $script:repo $a).leftBehindAnswer | Should Be 'yes'
    }
    It 'library_update_usages on a change that is open names that change, and no line about none' {
        Reset-Fake
        $b = Save-LaterChange
        $r = Invoke-LibraryUpdateTool ([pscustomobject]@{ })
        $r.change | Should Be $b
        $r.summary | Should Not Match 'belongs to no open library change'
    }
}

# The record once said "not put in work" of a type TIA had in work, as nothing read that between the edit and the review. A release is
# followed by a compile by name, and which of the two has TIA do it is not known: both read it, and say what they read.
Describe 'What is in work, read at the release and at a compile' {
    function Get-BridgeSession { $script:state }
    function Get-TiaLibrary { $script:fakeLib }
    function Get-TiaDeviceNames { @('Plc1') }
    function Get-LibraryTypeScope { 'plc' }
    function Add-LibraryLog { $script:logged += @($args[0]) }
    function Get-UpdateScopes { @() }
    function Get-SafetyProgramRefusal { $null }
    function Get-LibraryDependsOn { @{ graph = $script:fakeGraph; complete = $true; walked = 1 } }
    function Get-InWorkTypes { $script:walks++; @{ complete = $(if ($script:walks -eq 1) { $script:walkFirst } else { $script:walkComplete }); walked = 9; types = @($script:fakeTypes | ForEach-Object { $t = $_; @($t.Versions | Where-Object { $_.State -eq 'InWork' }) | ForEach-Object { @{ type = $t.Name; inWork = [string]$_.VersionNumber } } }) } }
    function Invoke-TiaWrite { param($Description, $Body, $RollbackIf) $out = @(& $Body); @{ output = $out; transaction = $true; rolledBack = $false } }
    function Invoke-CompileEveryDevice { & $script:atCompile; @{ items = @(); errors = 0 } }
    function Invoke-ProjectUpdate { & $script:atUpdate; if ($script:updateRefused) { @{ refused = 'TIA said no.'; transaction = $true } } else { @{ transaction = $true } } }
    function Get-TiaProject { $l = [pscustomobject]@{ }; Add-Member -InputObject $l ScriptMethod UpdateCheck { param($p, $m) @{ } }; [pscustomobject]@{ ProjectLibrary = $l } }
    function ConvertTo-ResultTree { @{ } }
    function Get-TiaSoftwareList { @(@{ kind = 'plc'; device = 'Plc1' }) }
    function Test-TypeObjectHasInstance { $true }
    function Get-TypesLeftBehind { @{ types = @(); complete = $true; deps = @{} } }

    # R (data type) <- B (data type) <- C (code block) <- D (code block), and D holds R too; each released 0.0.1 with an instance. R 0.0.2 in work.
    function Reset-Fake {
        $script:repo = Join-Path $TestDrive ([guid]::NewGuid().ToString('N'))
        New-Item -ItemType Directory -Force -Path (Join-Path $script:repo 'library\changes') | Out-Null
        $script:Bridge = @{ repo = $script:repo; settings = @{} }
        $script:state = New-SessionState; Register-Archive $script:state
        $script:contains = @{}; $script:plainUsed = @{}; $script:logged = @(); $script:walkComplete = $true; $script:walkFirst = $true; $script:walks = 0; $script:atUpdate = { }; $script:atCompile = { }; $script:updateRefused = $false; $script:compileNote = $null
        $script:r = New-FakeType 'R' @((New-FakeVersion '0.0.1' 'Committed' $true), (New-FakeVersion '0.0.2' 'InWork'))
        $script:b = New-FakeType 'B' @(New-FakeVersion '0.0.1' 'Committed' $true)
        $script:c = New-FakeType 'C' @(New-FakeVersion '0.0.1' 'Committed' $true)
        $script:d = New-FakeType 'D' @(New-FakeVersion '0.0.1' 'Committed' $true)
        @($script:b.Versions)[0].Dependencies = @([pscustomobject]@{ VersionNumber = [version]'0.0.1'; TypeObject = $script:r })
        @($script:c.Versions)[0].Dependencies = @([pscustomobject]@{ VersionNumber = [version]'0.0.1'; TypeObject = $script:b })
        @($script:d.Versions)[0].Dependencies = @([pscustomobject]@{ VersionNumber = [version]'0.0.1'; TypeObject = $script:r })
        $script:atRelease = { }
        Add-Member -InputObject @($script:r.Versions)[1] ScriptMethod Release { param($m, $n, $au, $co)
            $this.State = 'Committed'; $this.IsDefault = $true; @($script:r.Versions)[0].IsDefault = $false; & $script:atRelease } -Force
        Set-FakeLibrary @($script:r, $script:b, $script:c, $script:d)
        $script:fakeGraph = @{ R = @(); B = @('R'); C = @('B'); D = @('R', 'C') }
        $row = { param($n, $k, $w) @{ name = $n; class = $k; folder = ''; released = '0.0.1'; inWork = $w } }
        $rec = New-ChangeRecord -Root 'R' -From '0.0.1' -To '0.0.2' -Levels @{ R = 0; B = 1; C = 2; D = 3 } -At ([datetime]'2026-11-04 01:06') -Types @(
            (& $row 'R' 'PlcTypeLibraryType' '0.0.2'), (& $row 'B' 'PlcTypeLibraryType' ''), (& $row 'C' 'CodeBlockLibraryType' ''), (& $row 'D' 'CodeBlockLibraryType' ''))
        $script:id = $rec.id
        $null = Save-ChangeRecord $script:repo $rec
    }
    function Add-WorkVersion($Type) {
        $v = New-FakeVersion '0.0.2' 'InWork'
        Add-Member -InputObject $v NoteProperty owner $Type.Name
        $Type.Versions = @($Type.Versions) + @($v)
    }
    # TIA puts B and D in work at the release itself, one way the real run can have gone
    function Set-InWorkAtRelease { $script:atRelease = { Add-WorkVersion $script:b; Add-WorkVersion $script:d } }
    function Read-Report { Get-Content (Join-Path $script:repo "library\changes\$script:id.md") -Raw }
    function Read-Record { Read-ChangeRecord $script:repo $script:id }
    $release = [pscustomobject]@{ name = 'R'; comment = 'c' }
    function Invoke-CompileTool { $n = @{ ok = $true; scope = [string]$args[0].scope; errors = 0; items = @() }; if ($script:compileNote) { $n.note = $script:compileNote }; $n }
    $byName = [pscustomobject]@{ scope = 'blocks'; names = @('R') }

    Context 'TIA put them in work at the release' {
        It 'the result names them, and next does not give that as a step to come' {
            Reset-Fake; Set-InWorkAtRelease
            $r = Invoke-LibraryReleaseTool $release
            @($r.alsoInWork | ForEach-Object { "$($_.type) $($_.version)" }) -join ',' | Should Be 'B 0.0.2,D 0.0.2'
            $r.summary | Should Match 'In work now, not before this release: B 0\.0\.2, D 0\.0\.2\.'
            $r.next | Should Not Match 'TIA puts'
            $r.next | Should Match "library_update_usages with types=\['R'\]"
            $r.next | Should Match 'In work already: B, D\.'
            $script:logged[-1] | Should Match 'In work now, not before this release: B 0\.0\.2'
        }
        It 'the report and the record read in work, and C stays not in work yet' {
            Reset-Fake; Set-InWorkAtRelease
            $null = Invoke-LibraryReleaseTool $release
            $md = Read-Report
            $md | Should Match '`B` - data type - 0\.0\.1 -> 0\.0\.2 in work( |\r?\n)'
            $md | Should Match '`D` - code block - 0\.0\.1 -> 0\.0\.2 in work( |\r?\n)'
            $md | Should Not Match 'by TIA'
            $md | Should Match '`C` - code block - 0\.0\.1, not in work yet'
            $md | Should Not Match 'not put in work'
            $md | Should Not Match 'needs a new version'
            $rec = Read-Record
            $rec.types.B.inWork | Should Be '0.0.2'
            $rec.types.D.inWork | Should Be '0.0.2'
            $rec.types.C.inWork | Should Be ''
            $rec.status | Should Be 'open'
        }
        It 'does not name a type that stood in work before the release, but next says it is in work' {
            Reset-Fake
            Add-WorkVersion $script:b
            $r = Invoke-LibraryReleaseTool $release
            $r.Contains('alsoInWork') | Should Be $false
            $r.summary | Should Not Match 'In work now'
            $r.next | Should Match 'In work already: B\.'
        }
        It 'an update after it does not count them as its own' {
            Reset-Fake; Set-InWorkAtRelease
            $null = Invoke-LibraryReleaseTool $release
            $c = Update-ChangeAfterUpdate $script:fakeLib @(@{ type = 'B'; inWork = '0.0.2' }, @{ type = 'D'; inWork = '0.0.2' }) $false $script:state
            @($c.byTia).Count | Should Be 0
            @($c.standing) -join ',' | Should Be 'B,D'
        }
        It 'an update says what it put in work and what stood there, with no claim of who did that' {
            Reset-Fake; Set-InWorkAtRelease
            $null = Invoke-LibraryReleaseTool $release
            $script:atUpdate = { Add-WorkVersion $script:c }
            $r = Invoke-LibraryUpdateTool ([pscustomobject]@{ types = @('R'); put_left_out_in_work = $false })
            $r.summary | Should Match 'TIA put 1 of its types in work, 2 stood in work before this update \(B, D\)'
            $again = Invoke-LibraryUpdateTool ([pscustomobject]@{ types = @('R'); put_left_out_in_work = $false })
            $again.summary | Should Match 'TIA put 0 of its types in work, 2 stood in work before this update \(B, D\)'
        }
        It 'is no sign of an update: released to the last type with none, the change stays open, and an update closes it' {
            Reset-Fake; Set-InWorkAtRelease
            @($script:c.Versions)[0].Dependencies = @()
            $null = Invoke-LibraryReleaseTool $release
            foreach ($x in $script:b, $script:d) { @($x.Versions)[0].IsDefault = $false }   # so nothing but the missing update holds it
            $null = Invoke-LibraryReleaseTool ([pscustomobject]@{ name = 'B'; comment = 'c' })
            $last = Invoke-LibraryReleaseTool ([pscustomobject]@{ name = 'D'; comment = 'c' })
            $last.Contains('status') | Should Be $false
            (Read-Record).status | Should Be 'open'
            $c = Update-ChangeAfterUpdate $script:fakeLib @() $false $script:state
            $c.status | Should Be 'done'
        }
    }

    Context 'nothing in work at the release' {
        It 'names none, keeps the step to come, and the report says no more than was read' {
            Reset-Fake
            $r = Invoke-LibraryReleaseTool $release
            $r.Contains('alsoInWork') | Should Be $false
            $r.next | Should Match 'TIA puts the dependent data types in work'
            $md = Read-Report
            $md | Should Match '`B` - data type - 0\.0\.1, not in work yet: \*\*NOT USING THE DEFAULT VERSION\*\* of R \(uses 0\.0\.1, default 0\.0\.2\)'
            $md | Should Not Match 'not put in work'
            $md | Should Not Match 'needs a new version'
        }
        It 'the walk stopped: it claims neither, and says it is not known' {
            Reset-Fake; Set-InWorkAtRelease
            $script:walkFirst = $false; $script:walkComplete = $false
            $r = Invoke-LibraryReleaseTool $release
            $r.Contains('alsoInWork') | Should Be $false
            $r.summary | Should Match 'Which types are in work now is not known'
            $r.next | Should Not Match 'TIA puts'
            $r.next | Should Not Match 'In work already'
        }
        It 'only the walk before it stopped: what is in work is known, which are new is not' {
            Reset-Fake; Set-InWorkAtRelease
            $script:walkFirst = $false
            $r = Invoke-LibraryReleaseTool $release
            $r.Contains('alsoInWork') | Should Be $false
            $r.summary | Should Not Match 'Which types are in work now is not known'
            $r.summary | Should Match 'In work now: B 0\.0\.2, D 0\.0\.2; which of them are new since before this release is not known'
            $r.next | Should Match 'In work already: B, D\.'
        }
        It 'only the walk before it stopped, and nothing in work: it has nothing to say of them, and the step stays to come' {
            Reset-Fake
            $script:walkFirst = $false
            $r = Invoke-LibraryReleaseTool $release
            $r.summary | Should Not Match 'In work now'
            $r.next | Should Match 'TIA puts the dependent data types in work'
        }
        It 'only the walk after it stopped: it says what is in work is not known' {
            Reset-Fake; Set-InWorkAtRelease
            $script:walkFirst = $true; $script:walkComplete = $false
            $r = Invoke-LibraryReleaseTool $release
            $r.Contains('alsoInWork') | Should Be $false
            $r.summary | Should Match 'Which types are in work now is not known'
            $r.next | Should Not Match 'In work already'
        }
        It 'names them with no change to hold them' {
            Reset-Fake; Set-InWorkAtRelease
            Remove-Item (Join-Path $script:repo "library\changes\$script:id.*")
            @((Invoke-LibraryReleaseTool $release).alsoInWork | ForEach-Object { $_.type }) -join ',' | Should Be 'B,D'
        }
    }

    Context 'TIA put them in work at the compile by name' {
        It 'the compile names them, the report and the record read in work, and the log has it' {
            Reset-Fake
            $null = Invoke-LibraryReleaseTool $release
            Add-WorkVersion $script:b; Add-WorkVersion $script:d
            $r = Invoke-CompileAndReadChange $byName
            $r.ok | Should Be $true
            @($r.alsoInWork | ForEach-Object { "$($_.type) $($_.version)" }) -join ',' | Should Be 'B 0.0.2,D 0.0.2'
            $r.note | Should Match 'in work now, not when its record was last read: B 0\.0\.2, D 0\.0\.2'
            $r.report | Should Match "$script:id\.md"
            $script:logged[-1] | Should Match 'in work now, not when its record was last read'
            $md = Read-Report
            $md | Should Match '`B` - data type - 0\.0\.1 -> 0\.0\.2 in work'
            $md | Should Not Match 'NOT USING THE DEFAULT VERSION'
            (Read-Record).types.D.inWork | Should Be '0.0.2'
        }
        It 'keeps a note the compile gave' {
            Reset-Fake
            $null = Invoke-LibraryReleaseTool $release
            Add-WorkVersion $script:b
            $script:compileNote = 'failed: what TIA holds.'
            (Invoke-CompileAndReadChange $byName).note | Should Match '^failed: what TIA holds\. Library change'
        }
        It 'with nothing new it adds nothing and writes nothing' {
            Reset-Fake; Set-InWorkAtRelease
            $null = Invoke-LibraryReleaseTool $release
            $file = Join-Path $script:repo "library\changes\$script:id.json"
            $before = (Get-Item $file).LastWriteTimeUtc
            $n = $script:logged.Count
            $r = Invoke-CompileAndReadChange $byName
            $r.Contains('alsoInWork') | Should Be $false
            $r.Contains('note') | Should Be $false
            (Get-Item $file).LastWriteTimeUtc | Should Be $before
            $script:logged.Count | Should Be $n
        }
        It 'an HMI compile, a refused one and the copy of an export-only session do not touch the record' {
            Reset-Fake
            $null = Invoke-LibraryReleaseTool $release
            Add-WorkVersion $script:b
            (Invoke-CompileAndReadChange ([pscustomobject]@{ scope = 'hmi' })).Contains('alsoInWork') | Should Be $false
            (Read-Record).types.B.inWork | Should Be ''
            function Invoke-CompileTool { @{ ok = $false; refused = 'scope blocks needs names.' } }
            (Invoke-CompileAndReadChange $byName).Contains('alsoInWork') | Should Be $false
            function Invoke-CompileTool { @{ ok = $true; scope = 'plc'; errors = 0; items = @() } }
            $script:Bridge.background = @{ write = $false }
            (Invoke-CompileAndReadChange ([pscustomobject]@{ scope = 'plc' })).Contains('alsoInWork') | Should Be $false
            (Read-Record).types.B.inWork | Should Be ''
            $script:Bridge.background = @{ write = $true }
            @((Invoke-CompileAndReadChange ([pscustomobject]@{ scope = 'plc' })).alsoInWork)[0].type | Should Be 'B'
        }
        It 'ends no change: one no longer in TIA stays as it is' {
            Reset-Fake
            $script:r.Versions = @(@($script:r.Versions)[0])
            Add-WorkVersion $script:b
            (Invoke-CompileAndReadChange $byName).Contains('alsoInWork') | Should Be $false
            $rec = Read-Record
            $rec.status | Should Be 'open'
            $rec.types.B.inWork | Should Be ''
        }
        It 'a record it cannot read costs the compile nothing, and says so' {
            Reset-Fake
            Set-Content -LiteralPath (Join-Path $script:repo "library\changes\$script:id.json") -Value '{ not json'
            $r = Invoke-CompileAndReadChange $byName
            $r.ok | Should Be $true
            $r.changeUnread | Should Not BeNullOrEmpty
        }
        It 'the tool the agent calls is this one' {
            $script:compileHandler = $null
            function Register-McpTool { param($Name, $Handler, $Description, $Schema) if ($Name -eq 'compile') { $script:compileHandler = [string]$Handler } }
            Register-ObjectTools
            $script:compileHandler | Should Match 'Invoke-CompileAndReadChange'
        }
    }

    Context 'the release chain' {
        function Set-ChainOnB {
            $null = Invoke-LibraryReleaseTool $release
            Add-WorkVersion $script:b
            @($script:b.Versions)[0].IsDefault = $false
            $rec = Read-Record; $rec.types.B.inWork = '0.0.2'; $rec.types.B.inWorkBy = 'found'; $rec.types.B.approved = $true; $null = Save-ChangeRecord $script:repo $rec
        }
        It 'reads after its own compile: a type that compile put in work does not read as left out' {
            Reset-Fake
            Set-ChainOnB
            # the chain compiles before the release too: only the compile after its update does it
            $script:atUpdate = { $script:atCompile = { Add-WorkVersion $script:d; $script:atCompile = { } } }
            $r = Invoke-LibraryReleaseChainTool ([pscustomobject]@{ comment = 'c' })
            $r.next | Should Not Match 'not put in work'
            @($r.inWorkAfter | ForEach-Object { $_.type }) -contains 'D' | Should Be $true
            (Read-Record).types.D.inWork | Should Be '0.0.2'
            $md = Read-Report
            $md | Should Match '`D` - code block - 0\.0\.1 -> 0\.0\.2 in work'
            $md | Should Not Match '`D`[^\r\n]*needs a new version'
        }
        It 'its update counts as one since its release, and one refused does not' {
            Reset-Fake
            @($script:c.Versions)[0].Dependencies = @()
            Set-ChainOnB
            $null = Invoke-LibraryReleaseChainTool ([pscustomobject]@{ comment = 'c' })
            Read-Report | Should Match '`C` - code block - 0\.0\.1, not put in work: keeps its version'
            Reset-Fake
            @($script:c.Versions)[0].Dependencies = @()
            Set-ChainOnB
            $rec = Read-Record; $rec.updated = $true; $null = Save-ChangeRecord $script:repo $rec
            $script:updateRefused = $true
            $null = Invoke-LibraryReleaseChainTool ([pscustomobject]@{ comment = 'c' })
            Read-Report | Should Match '`C` - code block - 0\.0\.1, not in work yet'
        }
        It 'records what its update put in work, so the next level does not read as left out' {
            Reset-Fake
            $null = Invoke-LibraryReleaseTool $release
            Add-WorkVersion $script:b
            $rec = Read-Record; $rec.types.B.inWork = '0.0.2'; $rec.types.B.inWorkBy = 'tia'; $rec.types.B.approved = $true; $null = Save-ChangeRecord $script:repo $rec
            $script:atUpdate = { Add-WorkVersion $script:d }
            $r = Invoke-LibraryReleaseChainTool ([pscustomobject]@{ comment = 'c' })
            $r.next | Should Not Match 'not put in work'
            $rec = Read-Record
            $rec.types.D.inWork | Should Be '0.0.2'
            $rec.updated | Should Be $true
            Read-Report | Should Match '`D` - code block - 0\.0\.1 -> 0\.0\.2 in work'
        }
    }

    Context 'a release by name after an update' {
        # R released, the project updated, B in work: then B is released by name
        function Set-UpdateThenReleaseB {
            $null = Invoke-LibraryReleaseTool $release
            $null = Update-ChangeAfterUpdate $script:fakeLib @() $false $script:state
            Add-WorkVersion $script:b
            @($script:b.Versions)[0].IsDefault = $false
            Invoke-LibraryReleaseTool ([pscustomobject]@{ name = 'B'; comment = 'c' })
        }
        It 'what contains it reads not in work yet, as its next says, while the change stays updated' {
            Reset-Fake
            $r = Set-UpdateThenReleaseB
            $r.next | Should Match 'TIA puts the dependent data types in work'
            $md = Read-Report
            $md | Should Match '`C` - code block - 0\.0\.1, not in work yet: \*\*NOT USING THE DEFAULT VERSION\*\* of B \(uses 0\.0\.1, default 0\.0\.2\)'
            $md | Should Not Match 'not put in work'
            $md | Should Not Match 'needs a new version'
            (Read-Record).updated | Should Be $true
        }
        It 'a type not on an old version does not read as keeping its version either' {
            Reset-Fake
            @($script:c.Versions)[0].Dependencies = @()
            $null = Set-UpdateThenReleaseB
            $md = Read-Report
            $md | Should Match '`C` - code block - 0\.0\.1, not in work yet'
            $md | Should Not Match 'keeps its version'
        }
        It 'the next update brings the old wording back, as it has then left them out' {
            Reset-Fake
            $null = Set-UpdateThenReleaseB
            $null = Update-ChangeAfterUpdate $script:fakeLib @() $false $script:state
            Read-Report | Should Match '`C` - code block - 0\.0\.1, not put in work: \*\*NOT USING THE DEFAULT VERSION\*\* of B \(uses 0\.0\.1, default 0\.0\.2\) - needs a new version'
        }
        It 'as the last step of a change it ends it, and what never moved keeps its version' {
            Reset-Fake
            @($script:c.Versions)[0].Dependencies = @()
            @($script:d.Versions)[0].Dependencies = @()
            $r = Set-UpdateThenReleaseB
            $r.status | Should Be 'done'
            (Read-Record).status | Should Be 'done'
            $md = Read-Report
            $md | Should Match '`C` - code block - 0\.0\.1, not put in work: keeps its version'
            $md | Should Not Match 'not in work yet'
        }
        It 'library_review asks the same' {
            Reset-Fake
            $null = Set-UpdateThenReleaseB
            $r = Invoke-LibraryReviewTool ([pscustomobject]@{ })
            $r.summary | Should Not Match 'not put in work'
            $r.summary | Should Match 'no update is on record since its last release'
        }
    }

    Context 'library_review' {
        function Export-ForReview { @{ ok = $false; note = 'n' } }
        It 'before any update it does not say they were not put in work' {
            Reset-Fake
            $null = Invoke-LibraryReleaseTool $release
            $r = Invoke-LibraryReviewTool ([pscustomobject]@{ })
            @($r.stale) -join ',' | Should Be 'B,D'
            $r.summary | Should Not Match 'not put in work'
            $r.summary | Should Match '2 types are not in work and not using the default version of a change type \(B, D\): no update is on record since its last release'
        }
        It 'after an update it does' {
            Reset-Fake
            $null = Invoke-LibraryReleaseTool $release
            $null = Update-ChangeAfterUpdate $script:fakeLib @() $false $script:state
            $r = Invoke-LibraryReviewTool ([pscustomobject]@{ })
            $r.summary | Should Match '2 types were not put in work and are not using the default version of a change type \(B, D\): they need a new version too'
            Read-Report | Should Match 'not put in work: \*\*NOT USING THE DEFAULT VERSION\*\* of R \(uses 0\.0\.1, default 0\.0\.2\) - needs a new version'
        }
    }
}
