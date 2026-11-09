# A change that reaches its end with types left on old versions, and library_left_behind: the user's answer. No TIA.
$here = Split-Path -Parent $MyInvocation.MyCommand.Path
foreach ($f in 'Mcp.ps1', 'Tia.ps1', 'Repo.ps1', 'Rules.ps1', 'Guards.ps1', 'Bridge.ps1', 'Tools\Objects.ps1', 'Tools\Plc.ps1', 'Tools\Library.ps1', 'Tools\LibraryChange.ps1') {
    . (Join-Path $here "..\$f")
}
if (-not ('Siemens.Engineering.Library.Types.UpdatePathsMode' -as [type])) {
    Add-Type -TypeDefinition 'namespace Siemens.Engineering.Library.Types { public enum UpdatePathsMode { UpdatePathsInTarget, KeepExistingPathsInTarget, ThrowIfPathsConflict } }'
}

function New-Change([string[]]$Others = @('S')) {
    $types = @(@{ name = 'R'; class = 'PlcTypeLibraryType'; folder = ''; released = '0.0.1'; inWork = '0.0.2' })
    $levels = @{ R = 0 }
    foreach ($o in $Others) { $types += @{ name = $o; class = 'PlcTypeLibraryType'; folder = ''; released = '0.0.1'; inWork = '' }; $levels[$o] = 1 }
    $r = New-ChangeRecord -Root 'R' -From '0.0.1' -To '0.0.2' -Types $types -Levels $levels -At ([datetime]'2026-11-03 10:00')
    $r.types.R.releasedAs = '0.0.2'; $r.updated = $true
    $r
}
function New-Left([string]$Name, [string]$Uses = 'S (uses 0.0.1, default 0.0.2)') { @{ type = $Name; version = '0.0.1'; uses = @($Uses) } }

Describe 'Which types are left behind' {
    function Get-LibraryStale { @{ stale = $script:stale; complete = $true; walked = 3; deps = $script:deps } }
    function Get-LibraryTypeMap { $h = @{}; foreach ($n in $script:deps.Keys) { $h[$n] = [pscustomobject]@{ Name = $n; Versions = @([pscustomobject]@{ VersionNumber = [version]'0.0.1'; State = 'Committed'; IsDefault = $true }) } }; $h }
    function Test-TypeObjectHasInstance { param($Type) $script:withInstance -contains $Type.Name }

    It 'takes a type with no instance on one left behind too, however far up, though it uses that one''s default version' {
        $script:stale = @{ X = @('S (uses 0.0.1, default 0.0.2)') }
        $script:deps = @{ S = @(); X = @('S'); Y = @('X'); Z = @('Y'); Other = @('S') }
        $script:withInstance = @('S', 'Other')
        $b = Get-TypesLeftBehind $null
        @($b.types | ForEach-Object { $_.type }) -join ',' | Should Be 'X,Y,Z'
        @($b.types)[1].uses | Should Be 'X (itself left on old versions)'
        $b.deps.Y | Should Be 'X'
    }
    It 'stops at a type that has an instance' {
        $script:stale = @{ X = @('S (uses 0.0.1, default 0.0.2)') }
        $script:deps = @{ S = @(); X = @('S'); Y = @('X'); Z = @('Y') }
        $script:withInstance = @('S', 'Y')
        @((Get-TypesLeftBehind $null).types | ForEach-Object { $_.type }) -join ',' | Should Be 'X'
    }
    It 'has none when the stale type has an instance, and takes nothing above it' {
        $script:stale = @{ X = @('S (uses 0.0.1, default 0.0.2)') }
        $script:deps = @{ S = @(); X = @('S'); Y = @('X') }
        $script:withInstance = @('X')
        @((Get-TypesLeftBehind $null).types).Count | Should Be 0
    }
}

Describe 'What a change says at its end' {
    It 'is left-behind, not done, while types stand on old versions, and done without them' {
        $r = New-Change
        $r.types.S.releasedAs = '0.0.2'
        Get-ChangeStatus $r | Should Be 'done'
        Set-RecordLeftBehind $r @{ types = @(New-Left 'X'); failed = $false; unread = '' }
        Get-ChangeStatus $r | Should Be 'left-behind'
        Set-RecordLeftBehind $r @{ types = @(); failed = $false; unread = '' }
        Get-ChangeStatus $r | Should Be 'done'
    }
    It 'stays open while it has work' {
        $r = New-Change
        $r.types.S.inWork = '0.0.2'
        Set-RecordLeftBehind $r @{ types = @(New-Left 'X'); failed = $false; unread = '' }
        Get-ChangeStatus $r | Should Be 'open'
    }
    It 'holds the change when the list cannot be read' {
        $r = New-Change
        $r.types.S.releasedAs = '0.0.2'
        Set-RecordLeftBehind $r @{ types = @(); failed = $true; unread = 'the walk failed' }
        Get-ChangeStatus $r | Should Be 'open'
    }
    It 'does not read as done in the report, lists each with what it uses, and gives nothing to tick' {
        $r = New-Change @('S', 'X', 'Y')
        $r.types.S.releasedAs = '0.0.2'
        $r.types.X.stale = @('S (uses 0.0.1, default 0.0.2)'); $r.types.X.noInstance = $true
        Set-RecordLeftBehind $r @{ types = @((New-Left 'X'), (New-Left 'Y' 'X (itself left on old versions)')); failed = $false; unread = '' }
        $r.status = Get-ChangeStatus $r
        $t = Format-ChangeReport $r
        $t | Should Match 'Status: left-behind'
        $t | Should Match '## Left on old versions'
        $t | Should Match '`X` 0\.0\.1: uses S \(uses 0\.0\.1, default 0\.0\.2\)'
        $t | Should Match '`Y` 0\.0\.1: uses X \(itself left on old versions\)'
        $t | Should Match 'Not decided yet'
        $t | Should Match 'A yes costs a new version of every type on the list'
        $t | Should Not Match '\[ \] `X`'
        $t | Should Not Match '\[ \] `Y`'
        $t | Should Not Match 'keeps its version'
    }
    It 'says in the report what the user chose, and what was refused' {
        $r = New-Change
        $r.leftBehindAnswer = 'no'
        Set-RecordLeftBehind $r @{ types = @(New-Left 'X'); failed = $false; unread = '' }
        Format-ChangeReport $r | Should Match 'The user chose to leave these'
        $r.leftBehindAnswer = 'yes'; $r.leftBehindRefused = @{ X = 'know-how protected' }
        Format-ChangeReport $r | Should Match '`X` 0\.0\.1: uses .* - refused: know-how protected'
    }
    It 'asks at the end only, and no more once answered' {
        Format-LeftBehindAsk @{ status = 'left-behind' } | Should Match '^Not decided yet: .* Ask the user, once, with this list'
        Format-LeftBehindAsk $null | Should Match '^Not decided yet: .* Ask the user, once'
        Format-LeftBehindAsk $null | Should Match 'A yes costs a new version of every type on the list, also of older changes and of a type that would move by itself, each through review and approval'
        Format-LeftBehindAsk @{ status = 'open' } | Should Match 'when this change reaches its end'
        Format-LeftBehindAsk @{ status = 'left-behind'; leftBehindAnswer = 'no' } | Should Match '^The user chose to leave them'
        Format-LeftBehindAsk @{ status = 'left-behind'; leftBehindAnswer = 'yes'; leftBehindRefused = @{ X = 'why' } } | Should Match '^Refused on the way: X \(why\)'
    }
    It 'next at the end: done names the folders deepest first, else not done' {
        $r = New-Change
        $r.status = 'done'
        Format-ChangeEndNext $r | Should Be 'library change done: compile, save, then commit the project repo.'
        $r.foldersMade = @(@{ kind = 'type'; folder = 'a' }, @{ kind = 'type'; folder = 'a/b' })
        Format-ChangeEndNext $r | Should Match 'delete_folder with kind type, folder a/b; kind type, folder a\.'
        $r.status = 'left-behind'
        Format-ChangeEndNext $r | Should Match 'is finished, but it is not done'
        $r.leftBehindAnswer = 'no'
        Format-ChangeEndNext $r | Should Match 'ended with types left on old versions, as the user chose: compile, save'
    }
    It 'caps the names in the text; the field holds them all' {
        $many = @(1..12 | ForEach-Object { New-Left "T$_" })
        $t = Format-TypesLeftBehind $many
        $t | Should Match 'T10 0\.0\.1'
        $t | Should Not Match 'T11 0\.0\.1'
        $t | Should Match 'and 2 more \(typesLeftBehind\)'
    }
    It 'clears what TIA no longer has in work, as a project closed without saving, not the changed type' {
        $r = New-Change @('S', 'X')
        $r.types.S.inWork = '0.0.2'; $r.types.S.inWorkBy = 'bridge'; $r.types.S.approved = $true
        $r.types.X.inWork = '0.0.2'; $r.types.X.inWorkBy = 'tia'
        $r.types.R.releasedAs = ''; $r.types.R.inWorkBy = 'change'
        Clear-ChangeInWorkGone $r @('X')
        $r.types.S.inWork | Should Be ''
        $r.types.S.approved | Should Be $false
        $r.types.X.inWork | Should Be '0.0.2'
        $r.types.R.inWork | Should Be '0.0.2'
    }
}

Describe 'A change with no changed type' {
    function Get-LibraryTypeMap { @{ X = [pscustomobject]@{ Versions = @([pscustomobject]@{ VersionNumber = [version]'0.0.2' }) } } }
    $script:Bridge = @{ repo = [string]$TestDrive; settings = @{} }

    It 'is done once what it holds is released, and has a report of its own' {
        $r = New-LeftBehindRecord ([datetime]'2026-11-03 10:00')
        $r.id | Should Be '2026-11-03_1000-left-behind'
        $r.root | Should Be ''
        Test-ChangeDone $r | Should Be $true
        $r.types['X'] = [ordered]@{ level = 1; kind = 'code block'; folder = ''; released = '0.0.1'; inWork = '0.0.2'; inWorkBy = 'bridge'; review = $null; approved = $false; releasedAs = '' }
        Test-ChangeDone $r | Should Be $false
        Format-ChangeReport $r | Should Match '# Library change: types left on old versions'
        $r.types.X.releasedAs = '0.0.2'
        Test-ChangeDone $r | Should Be $true
    }
    It 'lives while what it put in work is there, not when the project was closed without saving' {
        $r = New-LeftBehindRecord ([datetime]'2026-11-03 10:00')
        Test-ChangeAlive $null $r | Should Be $true
        $r.types['X'] = [ordered]@{ inWork = '0.0.2'; releasedAs = '' }
        Test-ChangeAlive $null $r | Should Be $true
        $r.types.X.inWork = '0.0.9'
        Test-ChangeAlive $null $r | Should Be $false
    }
}

Describe 'Older changes follow the list' {
    function Test-ChangeAlive { $true }
    It 'an older left-behind change is done once its types are up to date, and a record is written only when it changes' {
        $repo = Join-Path $TestDrive 'older'
        New-Item -ItemType Directory -Force -Path (Join-Path $repo 'library\changes') | Out-Null
        $script:Bridge = @{ repo = $repo; settings = @{} }
        $old = New-Change; $old.id = '2026-11-01_1000-R'; $old.types.S.releasedAs = '0.0.2'
        Set-RecordLeftBehind $old @{ types = @(New-Left 'X'); failed = $false; unread = '' }
        $null = Save-ChangeRecord $repo $old
        $new = New-Change; $new.id = '2026-11-02_1000-R'; $new.types.S.releasedAs = '0.0.2'
        $null = Save-ChangeRecord $repo $new
        $file = Join-Path $repo "library\changes\$($new.id).json"
        $stamp = (Get-Item $file).LastWriteTimeUtc
        $current = Update-ChangesLeftBehind $null @{ types = @(); failed = $false; unread = '' }
        $current.id | Should Be $new.id
        (Read-ChangeRecord $repo $old.id).status | Should Be 'done'
        (Get-Item $file).LastWriteTimeUtc | Should Be $stamp
        # a walk cut short lists too few: no record follows it
        $null = Update-ChangesLeftBehind $null @{ types = @(New-Left 'Q'); failed = $false; unread = 'the library walk stopped at its time limit' }
        (Read-ChangeRecord $repo $new.id).status | Should Be 'done'
        # a new type on the list goes on the current change only
        $current = Update-ChangesLeftBehind $null @{ types = @(New-Left 'Q'); failed = $false; unread = '' }
        (Read-ChangeRecord $repo $new.id).status | Should Be 'left-behind'
        (Read-ChangeRecord $repo $old.id).status | Should Be 'done'
    }
}

Describe 'library_left_behind' {
    function Get-BridgeSession { $script:state }
    function Get-TiaProject { $null }
    function Get-TiaLibrary { 'lib' }
    function Add-LibraryLog { $script:logged += @($args[0]) }
    function Test-ChangeAlive { $true }
    function Get-TypesLeftBehind { if ($script:readThrows) { throw 'the walk failed' }; @{ types = @($script:list | Where-Object { $script:hasInstance -notcontains $_.type -or $script:edits -notcontains $_.type }); complete = $script:readComplete; deps = $script:deps } }
    function Get-InWorkTypes { @{ types = @($script:inWorkNow | ForEach-Object { @{ type = $_ } }); complete = $true; walked = 1 } }
    function Get-LibraryTypeMap { $h = @{}; foreach ($n in $script:deps.Keys) { $h[$n] = (Get-FakeType $n) }; $h }
    function Get-FakeType([string]$Name) {
        if (-not $script:fake.ContainsKey($Name)) {
            $v = [pscustomobject]@{ VersionNumber = [version]'0.0.1'; State = 'Committed'; IsDefault = $true; TypeName = $Name }
            Add-Member -InputObject $v ScriptMethod FindInstances { param($sw) @("info of $($this.TypeName)") }
            Add-Member -InputObject $v ScriptMethod Edit { param($i)
                if ($script:editThrows -contains $this.TypeName) { throw "Edit of $($this.TypeName) failed" }
                $script:edits += @($this.TypeName)
                $t = $script:fake[$this.TypeName]
                $t.Versions = @($t.Versions) + @([pscustomobject]@{ VersionNumber = [version]'0.0.2'; State = 'InWork'; IsDefault = $false })
            }
            $script:fake[$Name] = [pscustomobject]@{ Name = $Name; Versions = @($v) }
        }
        $script:fake[$Name]
    }
    function Test-TypeObjectHasInstance { param($Type) $script:hasInstance -contains $Type.Name }
    function Test-FCompliantTypeVersion { param($Entry, $Version) $script:fCompliant -contains $Entry.name }
    function Get-ChangeTypeInfo { param($Library, $Names) foreach ($n in $Names) { @{ name = $n; class = 'CodeBlockLibraryType'; folder = 'lib'; released = '0.0.1'; inWork = '0.0.2' } } }
    function Get-PlcObjectRecords { $h = @{}; foreach ($o in $script:plcObjects) { $h["P`tblock`t$o"] = @{ object = $o } }; $h }
    function Invoke-TiaWrite { param($Description, $Body, $RollbackIf) $null = & $Body; @{ transaction = $true; rolledBack = $false } }
    function New-Group([string[]]$Subs = @()) {
        $g = [pscustomobject]@{ Groups = [pscustomobject]@{ Names = $Subs } }
        Add-Member -InputObject $g.Groups ScriptMethod Find { param($n) if ($this.Names -contains $n) { New-Group } }
        $g
    }
    function Get-PlcFolderPaths { if (@($script:makes).Count) { $script:foldersNow } else { $script:foldersBefore } }
    function Get-TiaSoftwareEntry { @{ device = 'P'; software = [pscustomobject]@{ BlockGroup = (New-Group $script:blockFolders); TypeGroup = (New-Group $script:typeFolders) } } }
    # what a real call does is in the tests of New-TypeInstanceInWork below
    function New-TypeInstanceInWork { param($Entry, $Version, [string]$Folder, [string]$Device, [bool]$Safety, [switch]$Temporary)
        $script:makes += @($Entry.name)
        $script:folderAsked = $Folder
        $script:temporary = [bool]$Temporary
        $script:hasInstance += @($Entry.name)
        if ($script:makeThrows -contains $Entry.name) { $script:hasInstance = @($script:hasInstance | Where-Object { $_ -ne $Entry.name }); throw "CreateFrom of $($Entry.name) failed" }
        if ($script:makeRefused.ContainsKey($Entry.name)) { $script:hasInstance = @($script:hasInstance | Where-Object { $_ -ne $Entry.name }); return @{ refused = $script:makeRefused[$Entry.name] } }
        $i = @{ object = $Entry.name; device = 'P'; folder = $Folder; type = $Entry.name; version = '0.0.1' }
        $c = @($script:copies[$Entry.name] | Where-Object { $_ })
        @{ instance = $i; copies = $c; objects = @(@($i) + $c) }
    }
    function Reset-Fake {
        $script:repo = Join-Path $TestDrive ([guid]::NewGuid().ToString('N'))
        New-Item -ItemType Directory -Force -Path (Join-Path $script:repo 'library\changes') | Out-Null
        New-Item -ItemType Directory -Force -Path (Join-Path $script:repo 'logs') | Out-Null
        $script:Bridge = @{ repo = $script:repo; settings = @{} }
        $script:state = New-SessionState; Register-Archive $script:state
        $script:list = @((New-Left 'X'), (New-Left 'Y' 'X (itself left on old versions)'), (New-Left 'Z' 'Y (itself left on old versions)'))
        $script:deps = @{ R = @(); S = @('R'); X = @('S'); Y = @('X'); Z = @('Y') }
        $script:readThrows = $false; $script:readComplete = $true; $script:inWorkNow = @(); $script:fake = @{}; $script:hasInstance = @()
        $script:fCompliant = @(); $script:plcObjects = @('Pm'); $script:blockFolders = @(); $script:typeFolders = @(); $script:foldersNow = @(); $script:foldersBefore = @()
        $script:makes = @(); $script:edits = @(); $script:makeThrows = @(); $script:editThrows = @(); $script:makeRefused = @{}; $script:copies = @{}; $script:logged = @()
    }
    function New-SavedChange {
        $r = New-Change; $r.types.S.releasedAs = '0.0.2'
        $null = Save-ChangeRecord $script:repo $r
        $r.id
    }

    It 'needs what the user said; no answer, no call' {
        Reset-Fake
        (Invoke-LibraryLeftBehindTool ([pscustomobject]@{})).refused | Should Match 'answer is required'
        (Invoke-LibraryLeftBehindTool ([pscustomobject]@{ answer = 'maybe' })).refused | Should Match 'answer is required'
        @($script:makes).Count | Should Be 0
    }
    It 'stands behind the archive gate' {
        Reset-Fake
        $script:state = New-SessionState
        (Invoke-LibraryLeftBehindTool ([pscustomobject]@{ answer = 'yes' })).refused | Should Match 'archive'
    }
    It 'refuses both answers while the change has work, and makes nothing' {
        Reset-Fake
        $r = New-Change; $r.types.S.inWork = '0.0.2'; $r.types.S.inWorkBy = 'tia'
        $null = Save-ChangeRecord $script:repo $r
        $script:inWorkNow = @('S')
        foreach ($a in 'yes', 'no') {
            $x = Invoke-LibraryLeftBehindTool ([pscustomobject]@{ answer = $a })
            $x.refused | Should Match 'has not reached its end: in work unreleased: S'
        }
        @($script:makes).Count | Should Be 0
        (Read-ChangeRecord $script:repo $r.id).leftBehindAnswer | Should Be $null
    }
    It 'does not wait for what TIA no longer has in work' {
        Reset-Fake
        $r = New-Change; $r.types.S.inWork = '0.0.2'; $r.types.S.inWorkBy = 'bridge'
        $null = Save-ChangeRecord $script:repo $r
        (Invoke-LibraryLeftBehindTool ([pscustomobject]@{ answer = 'no' })).ok | Should Be $true
    }
    It 'refuses while the update is outstanding' {
        Reset-Fake
        $r = New-Change; $r.types.S.releasedAs = '0.0.2'; $r.updateOutstanding = $true
        $null = Save-ChangeRecord $script:repo $r
        (Invoke-LibraryLeftBehindTool ([pscustomobject]@{ answer = 'yes' })).refused | Should Match 'not updated'
    }
    It 'refuses when the list cannot be read, or only in part' {
        Reset-Fake
        $script:readThrows = $true
        (Invoke-LibraryLeftBehindTool ([pscustomobject]@{ answer = 'yes' })).refused | Should Match 'the walk failed'
        $script:readThrows = $false; $script:readComplete = $false
        (Invoke-LibraryLeftBehindTool ([pscustomobject]@{ answer = 'no' })).refused | Should Match 'time limit'
        @($script:makes).Count | Should Be 0
    }
    It 'has nothing to do with an empty list' {
        Reset-Fake
        $script:list = @()
        $x = Invoke-LibraryLeftBehindTool ([pscustomobject]@{ answer = 'yes' })
        $x.ok | Should Be $true
        $x.summary | Should Match 'nothing to do'
        @($script:makes).Count | Should Be 0
    }

    Context 'answer no' {
        It 'ends the change as left-behind, makes nothing, lists them, and does not ask again' {
            Reset-Fake
            $id = New-SavedChange
            $x = Invoke-LibraryLeftBehindTool ([pscustomobject]@{ answer = 'no' })
            $x.ok | Should Be $true
            $x.status | Should Be 'left-behind'
            $x.change | Should Be $id
            @($x.typesLeftBehind).Count | Should Be 3
            $x.summary | Should Match 'X 0\.0\.1 \(uses S'
            $x.next | Should Match 'as the user chose: compile, save'
            $x.next | Should Not Match 'Ask the user'
            @($script:makes).Count | Should Be 0
            $rec = Read-ChangeRecord $script:repo $id
            $rec.leftBehindAnswer | Should Be 'no'
            $rec.status | Should Be 'left-behind'
            Get-Content (Join-Path $script:repo "library\changes\$id.md") -Raw | Should Match 'The user chose to leave these'
            # any later result lists them, and no question
            $later = @{ ok = $true; summary = 's'; next = 'n' }
            Add-LeftBehindFacts $later 'lib'
            @($later.typesLeftBehind).Count | Should Be 3
            $later.next | Should Match 'The user chose to leave them'
            $later.next | Should Not Match 'Ask the user'
        }
        It 'keeps the answer in a record of its own when no change has one' {
            Reset-Fake
            $x = Invoke-LibraryLeftBehindTool ([pscustomobject]@{ answer = 'no' })
            $x.change | Should Match 'left-behind$'
            $x.status | Should Be 'left-behind'
            $later = @{ ok = $true; summary = 's'; next = 'n' }
            Add-LeftBehindFacts $later 'lib'
            $later.next | Should Not Match 'Ask the user'
        }
    }

    Context 'answer yes' {
        It 'makes every instance contained types first, in one folder, and only then puts them in work' {
            Reset-Fake
            $id = New-SavedChange
            # by name Z would come first
            $script:list = @((New-Left 'Z' 'Y (itself left on old versions)'), (New-Left 'Y' 'X (itself left on old versions)'), (New-Left 'X'))
            $x = Invoke-LibraryLeftBehindTool ([pscustomobject]@{ answer = 'yes' })
            $x.ok | Should Be $true
            $script:makes -join ',' | Should Be 'X,Y,Z'
            $script:edits -join ',' | Should Be 'X,Y,Z'
            $script:temporary | Should Be $true
            $x.folder | Should Be 'LibraryUpdateTemp'
            $script:folderAsked | Should Be 'LibraryUpdateTemp'
            @($x.instancesMade | ForEach-Object { $_.object }) -join ',' | Should Be 'X,Y,Z'
            @($x.inWork)[0].inWork | Should Be '0.0.2'
        }
        It 'joins the change, on the level above what it contains, as any type in work; the record stays open' {
            Reset-Fake
            $id = New-SavedChange
            $x = Invoke-LibraryLeftBehindTool ([pscustomobject]@{ answer = 'yes' })
            $x.change | Should Be $id
            $rec = Read-ChangeRecord $script:repo $id
            $rec.status | Should Be 'open'
            $rec.leftBehindAnswer | Should Be 'yes'
            [int]$rec.types.S.level | Should Be 1
            [int]$rec.types.X.level | Should Be 2
            [int]$rec.types.Y.level | Should Be 3
            [int]$rec.types.Z.level | Should Be 4
            $rec.types.X.inWork | Should Be '0.0.2'
            $rec.types.X.inWorkBy | Should Be 'bridge'
            $rec.types.X.approved | Should Be $false
            Get-Content (Join-Path $script:repo "library\changes\$id.md") -Raw | Should Match '\[ \] `X` - code block - 0\.0\.1 -> 0\.0\.2 in work'
        }
        It 'moves a type already in the record to work, approval gone' {
            Reset-Fake
            $r = New-Change @('S', 'X'); $r.types.S.releasedAs = '0.0.2'; $r.types.X.noInstance = $true; $r.types.X.approved = $true
            $null = Save-ChangeRecord $script:repo $r
            $script:list = @(New-Left 'X')
            $null = Invoke-LibraryLeftBehindTool ([pscustomobject]@{ answer = 'yes' })
            $rec = Read-ChangeRecord $script:repo $r.id
            $rec.types.X.inWork | Should Be '0.0.2'
            $rec.types.X.noInstance | Should Be $false
            $rec.types.X.approved | Should Be $false
            [int]$rec.types.X.level | Should Be 1
        }
        It 'keeps what the types use outside the change, so a review reads it as expected' {
            Reset-Fake
            $id = New-SavedChange
            $script:list = @(New-Left 'W' 'V (uses 0.0.1, default 0.0.2)')
            $script:deps = @{ V = @(); W = @('V') }
            $null = Invoke-LibraryLeftBehindTool ([pscustomobject]@{ answer = 'yes' })
            @((Read-ChangeRecord $script:repo $id).usesOutside) -join ',' | Should Be 'V'
        }
        It 'names the copies and the folders, and next the update of what they contain' {
            Reset-Fake
            $null = New-SavedChange
            $script:copies = @{ X = @(@{ object = 'S_1'; device = 'P'; folder = 'lib'; type = 'S'; version = '0.0.1' }, @{ object = 'R_1'; device = 'P'; folder = 'lib'; type = 'R'; version = '0.0.1' }) }
            $script:foldersNow = @("block`tLibraryUpdateTemp", "type`tlib")
            $x = Invoke-LibraryLeftBehindTool ([pscustomobject]@{ answer = 'yes' })
            @($x.copiesMade | ForEach-Object { $_.object }) -join ',' | Should Be 'S_1,R_1'
            @($x.foldersMade | ForEach-Object { "$($_.kind) $($_.folder)" }) -join ',' | Should Be 'block LibraryUpdateTemp,type lib'
            $x.summary | Should Match 'S_1 \(type S 0\.0\.1, folder lib\)'
            $x.next | Should Match "^compile, library_update_usages with types=\['R', 'S'\], compile, library_review"
            $x.next | Should Match 'approve per level'
            $script:state.pending.ContainsKey('plc@p:s_1') | Should Be $true
            $script:state.pending.ContainsKey('plc@p:type:x') | Should Be $true
        }
        It 'starts a record of its own when no change has one, and it joins nothing else' {
            Reset-Fake
            $x = Invoke-LibraryLeftBehindTool ([pscustomobject]@{ answer = 'yes' })
            $x.change | Should Match 'left-behind$'
            $rec = Read-ChangeRecord $script:repo $x.change
            $rec.status | Should Be 'open'
            [int]$rec.types.X.level | Should Be 1
        }

        It 'never takes a folder of the user: a free name, or a refusal of the one asked for' {
            Reset-Fake
            $script:blockFolders = @('LibraryUpdateTemp'); $script:typeFolders = @('LibraryUpdateTemp_2')
            (Invoke-LibraryLeftBehindTool ([pscustomobject]@{ answer = 'yes' })).folder | Should Be 'LibraryUpdateTemp_3'
            Reset-Fake
            $script:typeFolders = @('Mine')
            $x = Invoke-LibraryLeftBehindTool ([pscustomobject]@{ answer = 'yes'; folder = 'Mine' })
            $x.refused | Should Match "The name 'Mine' is taken"
            @($script:makes).Count | Should Be 0
        }
        It 'takes no name of an object, as TIA refuses an object named as its folder' {
            Reset-Fake
            (Invoke-LibraryLeftBehindTool ([pscustomobject]@{ answer = 'yes'; folder = 'Pm' })).refused | Should Match 'is taken'
            (Invoke-LibraryLeftBehindTool ([pscustomobject]@{ answer = 'yes'; folder = 'a/X' })).refused | Should Match 'is taken'
            $script:plcObjects = @('LibraryUpdateTemp')
            (Invoke-LibraryLeftBehindTool ([pscustomobject]@{ answer = 'yes' })).folder | Should Be 'LibraryUpdateTemp_2'
        }
        It 'keeps long lists out of the text, and the fields hold them' {
            Reset-Fake
            $script:list = @(1..12 | ForEach-Object { New-Left "T$_" })
            $script:deps = @{}; foreach ($t in $script:list) { $script:deps[$t.type] = @() }
            $x = Invoke-LibraryLeftBehindTool ([pscustomobject]@{ answer = 'yes' })
            @($x.inWork).Count | Should Be 12
            $x.summary | Should Match 'and 2 more'
        }
        It 'takes the folder the user names' {
            Reset-Fake
            (Invoke-LibraryLeftBehindTool ([pscustomobject]@{ answer = 'yes'; folder = 'a/temp' })).folder | Should Be 'a/temp'
            $script:folderAsked | Should Be 'a/temp'
        }

        It 'a type refused stays on the list, takes along what contains it, and the others go on' {
            Reset-Fake
            $id = New-SavedChange
            $script:list = @((New-Left 'X'), (New-Left 'Y' 'X (itself left on old versions)'), (New-Left 'Z' 'Y (itself left on old versions)'), (New-Left 'Q'))
            $script:deps = @{ S = @(); X = @('S'); Y = @('X'); Z = @('Y'); Q = @('S') }
            $script:makeRefused = @{ X = 'know-how protected (X)' }
            $x = Invoke-LibraryLeftBehindTool ([pscustomobject]@{ answer = 'yes' })
            $x.ok | Should Be $false
            @($x.typesRefused | ForEach-Object { $_.type }) -join ',' | Should Be 'X,Y,Z'
            @($x.typesRefused)[1].why | Should Match 'it contains X, refused'
            $script:makes -join ',' | Should Be 'X,Q'
            @($x.inWork | ForEach-Object { $_.type }) | Should Be 'Q'
            $x.summary | Should Match 'they stay on the list and the change is not done'
            # Q released, the rest stands: not done, and the report and every result say why
            $script:list = @($script:list | Where-Object { $_.type -ne 'Q' })
            $rec = Read-ChangeRecord $script:repo $id
            $rec.types.Q.inWork = ''; $rec.types.Q.releasedAs = '0.0.2'
            Set-RecordLeftBehind $rec @{ types = $script:list; failed = $false; unread = '' }
            $null = Save-ChangeRecord $script:repo $rec
            $rec = Read-ChangeRecord $script:repo $id
            $rec.status | Should Be 'left-behind'
            Format-ChangeReport $rec | Should Match '`X` 0\.0\.1: uses .* - refused: know-how protected'
            $later = @{ ok = $true; summary = 's'; next = 'n' }
            Add-LeftBehindFacts $later 'lib'
            $later.next | Should Match 'Refused on the way: X \(know-how protected \(X\)\)'
        }
        It 'refuses an F-compliant data type by its document without safety: true, and takes it with' {
            Reset-Fake
            $script:list = @(New-Left 'X')
            $script:fCompliant = @('X')
            $x = Invoke-LibraryLeftBehindTool ([pscustomobject]@{ answer = 'yes' })
            @($x.typesRefused)[0].why | Should Match 'safety program'
            @($script:makes).Count | Should Be 0
            (Invoke-LibraryLeftBehindTool ([pscustomobject]@{ answer = 'yes'; safety = $true })).ok | Should Be $true
            $script:makes | Should Be 'X'
        }
        It 'a type whose making fails stays on the list and holds nothing for the save, as nothing was kept' {
            Reset-Fake
            $null = New-SavedChange
            $script:makeThrows = @('X')
            $x = Invoke-LibraryLeftBehindTool ([pscustomobject]@{ answer = 'yes' })
            $x.ok | Should Be $false
            @($x.typesRefused)[0].why | Should Match 'CreateFrom of X failed'
            @($x.typesRefused)[1].why | Should Match 'it contains X'
            @($script:state.failed.Keys).Count | Should Be 0
        }
        It 'a type that cannot be put in work stays refused and holds the save, as a failed write' {
            Reset-Fake
            $null = New-SavedChange
            $script:list = @(New-Left 'X')
            $script:editThrows = @('X')
            $x = Invoke-LibraryLeftBehindTool ([pscustomobject]@{ answer = 'yes' })
            $x.ok | Should Be $false
            @($x.typesRefused)[0].why | Should Match 'could not be put in work: .*Edit of X failed'
            $script:state.failed.ContainsKey('plc@p:type:x') | Should Be $true
        }
        It 'a type that came with what was made before it is not made again' {
            Reset-Fake
            $null = New-SavedChange
            $script:list = @(New-Left 'X'); $script:hasInstance = @('X')
            $x = Invoke-LibraryLeftBehindTool ([pscustomobject]@{ answer = 'yes' })
            @($script:makes).Count | Should Be 0
            $script:edits | Should Be 'X'
            $x.ok | Should Be $true
        }
        It 'never calls Edit on a type with a version in work, as that ended TIA: it goes on with that version' {
            Reset-Fake
            $null = New-SavedChange
            $script:list = @(New-Left 'X'); $script:hasInstance = @('X')
            $t = Get-FakeType 'X'
            $t.Versions = @($t.Versions) + @([pscustomobject]@{ VersionNumber = [version]'0.0.2'; State = 'InWork'; IsDefault = $false })
            $x = Invoke-LibraryLeftBehindTool ([pscustomobject]@{ answer = 'yes' })
            @($script:edits).Count | Should Be 0
            @($x.inWork)[0].inWork | Should Be '0.0.2'
            $x.ok | Should Be $true
        }
        It 'forgets a folder a close without saving took back, so that next does not send to it' {
            Reset-Fake
            $id = New-SavedChange
            $rec = Read-ChangeRecord $script:repo $id
            $rec.temporaryFolder = 'Gone'; $rec.foldersMade = @(@{ kind = 'block'; folder = 'Gone'; device = 'P' }, @{ kind = 'type'; folder = 'lib'; device = 'P' })
            $null = Save-ChangeRecord $script:repo $rec
            $script:foldersBefore = @("type`tlib"); $script:foldersNow = @("type`tlib", "block`tGone2")
            $x = Invoke-LibraryLeftBehindTool ([pscustomobject]@{ answer = 'yes'; folder = 'Gone2' })
            @($x.foldersMade | ForEach-Object { "$($_.kind) $($_.folder)" }) -join ',' | Should Be 'type lib,block Gone2'
        }
        It 'names a folder once when a later call makes it again' {
            Reset-Fake
            $id = New-SavedChange
            $rec = Read-ChangeRecord $script:repo $id
            $rec.foldersMade = @(@{ kind = 'type'; folder = 'lib'; device = 'P' })
            $null = Save-ChangeRecord $script:repo $rec
            $script:foldersNow = @("type`tlib")
            $x = Invoke-LibraryLeftBehindTool ([pscustomobject]@{ answer = 'yes' })
            @($x.foldersMade | ForEach-Object { "$($_.kind) $($_.folder)" }) -join ',' | Should Be 'type lib'
        }
        It 'reuses its own folder when called again after a refusal' {
            Reset-Fake
            $id = New-SavedChange
            $script:list = @((New-Left 'X'), (New-Left 'Q'))
            $script:deps = @{ S = @(); X = @('S'); Q = @('S') }
            $script:makeRefused = @{ Q = 'no' }
            $script:blockFolders = @()
            $first = Invoke-LibraryLeftBehindTool ([pscustomobject]@{ answer = 'yes' })
            $first.folder | Should Be 'LibraryUpdateTemp'
            # X went through to its end, and the folder stands, as ours
            $rec = Read-ChangeRecord $script:repo $id
            $rec.types.X.inWork = ''; $rec.types.X.releasedAs = '0.0.2'
            $null = Save-ChangeRecord $script:repo $rec
            $script:list = @(New-Left 'Q'); $script:makeRefused = @{}; $script:blockFolders = @('LibraryUpdateTemp')
            (Invoke-LibraryLeftBehindTool ([pscustomobject]@{ answer = 'yes' })).folder | Should Be 'LibraryUpdateTemp'
        }
    }
}

Describe 'Editing the changed type while a yes is in work' {
    function Get-LiveChange { $script:rec }
    function Save-ChangeRecord { 'r.md' }
    function Get-InWorkTypes { @{ types = @($script:inWorkNow | ForEach-Object { @{ type = $_ } }); complete = $script:walkComplete; walked = 1 } }
    $script:Bridge = @{ repo = [string]$TestDrive; settings = @{} }
    function Reset-Fake {
        $script:rec = New-Change @('S', 'X')
        $script:rec.types.S.releasedAs = '0.0.2'
        $script:rec.types.X.inWork = '0.0.2'; $script:rec.types.X.inWorkBy = 'bridge'
        $script:rec.leftBehindAnswer = 'yes'
        $script:inWorkNow = @('X'); $script:walkComplete = $true
    }
    It 'is refused, and the refusal names the types and the way out' {
        Reset-Fake
        $why = Get-EditYesRefusal $null 'R'
        $why | Should Match "holds the types of a yes in work: X"
        $why | Should Match 'library_discard_type'
    }
    It 'goes on once they are out' {
        Reset-Fake
        $script:rec.types.X.inWork = ''; $script:rec.types.X.releasedAs = '0.0.2'
        Get-EditYesRefusal $null 'R' | Should Be $null
    }
    It 'goes on when TIA no longer has them in work, as after a close without saving' {
        Reset-Fake
        $script:inWorkNow = @()
        Get-EditYesRefusal $null 'R' | Should Be $null
    }
    It 'holds when the walk stopped short' {
        Reset-Fake
        $script:inWorkNow = @(); $script:walkComplete = $false
        Get-EditYesRefusal $null 'R' | Should Match 'yes in work'
    }
    It 'does not touch a type of the change that is not its changed type, nor a change with no yes, nor one not yet released' {
        Reset-Fake
        Get-EditYesRefusal $null 'X' | Should Be $null
        $script:rec.leftBehindAnswer = 'no'
        Get-EditYesRefusal $null 'R' | Should Be $null
        Reset-Fake
        $script:rec.types.R.releasedAs = ''
        Get-EditYesRefusal $null 'R' | Should Be $null
    }
    It 'with no change it says nothing' {
        Reset-Fake
        $script:rec = $null
        Get-EditYesRefusal $null 'R' | Should Be $null
    }
}

Describe 'library_release_type as the last step of a change' {
    function Get-LiveChange { $script:rec }
    function Save-ChangeRecord { param($Repo, $Record) if ($Record.status -in 'open', 'done', 'left-behind') { $Record.status = Get-ChangeStatus $Record }; 'r.md' }
    function Get-LibraryStale { @{ stale = $script:stale; complete = $true; walked = 1; deps = @{} } }
    function Get-LibraryTypeMap { $h = @{}; foreach ($n in $script:stale.Keys) { $h[$n] = [pscustomobject]@{ Name = $n } }; $h }
    function Test-TypeObjectHasInstance { $false }
    function Get-TypesLeftBehind { @{ types = $script:list; complete = $true; deps = @{} } }
    function Test-ChangeAlive { $true }
    $script:Bridge = @{ repo = [string]$TestDrive; settings = @{} }
    function Reset-Fake {
        $script:rec = New-Change @('S', 'X')
        $script:rec.types.S.inWork = '0.0.2'; $script:rec.types.S.inWorkBy = 'tia'
        $script:stale = @{ X = @('S (uses 0.0.1, default 0.0.2)') }
        $script:list = @(New-Left 'X')
    }
    It 'does not read as done with types left: the record, its report and what it returns' {
        Reset-Fake
        $e = Update-ChangeAtRelease $null @{ S = '0.0.2' }
        $e.record.status | Should Be 'left-behind'
        $e.record.types.X.noInstance | Should Be $true
        @($e.read.types)[0].type | Should Be 'X'
        Format-ChangeReport $e.record | Should Match '## Left on old versions'
    }
    It 'is done with nothing left' {
        Reset-Fake
        $script:stale = @{}; $script:list = @()
        (Update-ChangeAtRelease $null @{ S = '0.0.2' }).record.status | Should Be 'done'
    }
    It 'stays open while another type of it is in work' {
        Reset-Fake
        $script:rec.types.X.inWork = '0.0.2'; $script:rec.types.X.inWorkBy = 'bridge'; $script:stale = @{}; $script:list = @()
        (Update-ChangeAtRelease $null @{ S = '0.0.2' }).record.status | Should Be 'open'
    }
    It 'says nothing with no change' {
        Reset-Fake
        $script:rec = $null
        Update-ChangeAtRelease $null @{ S = '0.0.2' } | Should Be $null
    }
    It 'a change at its end gets its folders in next' {
        Reset-Fake
        $script:stale = @{}; $script:list = @()
        $script:rec.foldersMade = @(@{ kind = 'block'; folder = 'temp' })
        $e = Update-ChangeAtRelease $null @{ S = '0.0.2' }
        Format-FolderCleanup $e.record | Should Match 'delete_folder with kind block, folder temp'
    }
}

Describe 'A new block never takes the number of a block of the PLC' {
    function New-Rec([string]$Name, [int]$Number, [string]$Class = 'FC', [string]$Device = 'P') { @{ object = $Name; device = $Device; number = $Number; class = $Class } }
    function Get-Moves([hashtable]$All, [string[]]$New) { , @(Get-NumberMoves $All $New) }

    It 'moves one whose number is held, above the highest of its kind' {
        $m = Get-Moves @{ a = (New-Rec 'Mine' 2); b = (New-Rec 'Other' 7); n = (New-Rec 'X' 2) } @('n')
        $m.Count | Should Be 1
        $m[0].key | Should Be 'n'; $m[0].from | Should Be 2; $m[0].to | Should Be 8
    }
    It 'leaves one whose number is free' {
        (Get-Moves @{ a = (New-Rec 'Mine' 2); n = (New-Rec 'X' 3) } @('n')).Count | Should Be 0
    }
    It 'FBs and FCs number apart, every DB with the others, each PLC by itself' {
        (Get-Moves @{ a = (New-Rec 'Mine' 2 'FB'); n = (New-Rec 'X' 2 'FC') } @('n')).Count | Should Be 0
        (Get-Moves @{ a = (New-Rec 'Mine' 2 'GlobalDB'); n = (New-Rec 'X' 2 'InstanceDB') } @('n')).Count | Should Be 1
        (Get-Moves @{ a = (New-Rec 'Mine' 2 'FC' 'Q'); n = (New-Rec 'X' 2 'FC' 'P') } @('n')).Count | Should Be 0
    }
    It 'two new ones on one number: one moves, and not onto another' {
        $m = Get-Moves @{ a = (New-Rec 'Mine' 5); n1 = (New-Rec 'X' 3); n2 = (New-Rec 'X_1' 3); n3 = (New-Rec 'Y' 5) } @('n1', 'n2', 'n3')
        @($m | ForEach-Object { $_.key }) -join ',' | Should Be 'n2,n3'
        @($m | ForEach-Object { $_.to }) -join ',' | Should Be '6,7'
    }
    It 'above the range it takes the lowest free one' {
        (Get-Moves @{ a = (New-Rec 'Mine' 59999); b = (New-Rec 'B' 1); n = (New-Rec 'X' 59999) } @('n'))[0].to | Should Be 2
    }
    It 'leaves a data type alone: it has no number' {
        (Get-Moves @{ a = @{ object = 'U'; device = 'P' }; n = @{ object = 'V'; device = 'P' } } @('n')).Count | Should Be 0
    }
    It 'an update names a block that stands on another number, counted from before the first instance, and forgets it then' {
        $script:Bridge = @{ projectPath = 'p' }
        $script:now = @{ a = (New-Rec 'Mine' 9); b = (New-Rec 'Other' 7); gone = $null }
        $script:now.Remove('gone')
        function Get-PlcObjectRecords { $script:now }
        $script:NumberBaseline = @{ project = 'p'; records = @{ a = (New-Rec 'Mine' 2) } }
        $c = @(Get-NumbersChanged @{ a = (New-Rec 'Mine' 9); b = (New-Rec 'Other' 7); x = (New-Rec 'Went' 3) })
        $c.Count | Should Be 1
        $c[0].object | Should Be 'Mine'; $c[0].from | Should Be 2; $c[0].to | Should Be 9
        $script:NumberBaseline | Should Be $null
        @(Get-NumbersChanged @{ a = (New-Rec 'Mine' 9) }).Count | Should Be 0
    }
    It 'a baseline of another project does not count' {
        $script:Bridge = @{ projectPath = 'p' }
        $script:now = @{ a = (New-Rec 'Mine' 9) }
        function Get-PlcObjectRecords { $script:now }
        $script:NumberBaseline = @{ project = 'q'; records = @{ a = (New-Rec 'Mine' 2) } }
        @(Get-NumbersChanged @{ a = (New-Rec 'Mine' 9) }).Count | Should Be 0
    }
    It 'the result of an update says so' {
        $r = @{ summary = 's'; ok = $true }
        Add-UpdateFacts $r @{ numbersChanged = @(@{ object = 'Mine'; device = 'P'; from = 2; to = 9 }) } @{ archived = $true }
        @($r.numbersChanged)[0].object | Should Be 'Mine'
        $r.summary | Should Match 'Block numbers changed: Mine 2 -> 9'
    }
    It 'says what moved' {
        Format-NumbersMoved @(@{ object = 'X'; number = 8; numberWas = 2 }, @{ object = 'Y'; number = 3 }) | Should Match 'X 2 -> 8'
        Format-NumbersMoved @(@{ object = 'Y'; number = 3 }) | Should Be ''
    }
}

Describe 'New-TypeInstanceInWork: what it refuses, taking it back' {
    function Get-TiaSoftwareEntry { @{ device = 'P'; software = [pscustomobject]@{ BlockGroup = 'b'; TypeGroup = 't' } } }
    function Test-PlcDataLibraryType { $false }
    function Get-OrCreateGroup { $script:group }
    function Get-PlcObjectRecords { $h = @{}; foreach ($r in $script:records) { $h["P`tblock`t$($r.object)"] = $r }; $h }
    function Invoke-TiaWrite { param($Description, $Body, $RollbackIf)
        $saved = @($script:records)
        $null = & $Body
        $back = [bool]($RollbackIf -and (& $RollbackIf))
        if ($back) { $script:records = $saved }
        @{ transaction = $true; rolledBack = $back }
    }
    function Reset-Fake {
        $script:records = @(@{ object = 'Mine'; device = 'P'; folder = 'f'; type = $null; version = $null; knowhow = $false })
        $script:comes = @(@{ object = 'X'; device = 'P'; folder = 'temp'; type = 'X'; version = '0.0.1'; language = 'SCL'; knowhow = $false })
        $script:after = $null; $script:edited = $false
        $made = [pscustomobject]@{}
        Add-Member -InputObject $made ScriptMethod CreateFrom { param($v, $m)
            $script:records = @($script:records) + @($script:comes)
            if ($script:after) { & $script:after }
        }
        $script:group = [pscustomobject]@{ Blocks = $made; Types = $made }
        $script:version = [pscustomobject]@{ VersionNumber = [version]'0.0.1' }
        Add-Member -InputObject $script:version ScriptMethod FindInstances { param($s) @('info') }
        Add-Member -InputObject $script:version ScriptMethod Edit { param($i) $script:edited = $true }
    }
    $entry = @{ name = 'X'; folder = 'lib'; obj = [pscustomobject]@{ Name = 'X' } }

    It 'makes the instance and leaves it out of work when told' {
        Reset-Fake
        $m = New-TypeInstanceInWork $entry $script:version 'temp' '' $false -Temporary
        $m.instance.object | Should Be 'X'
        $script:edited | Should Be $false
    }
    It 'puts it in work otherwise' {
        Reset-Fake
        $null = New-TypeInstanceInWork $entry $script:version 'temp' '' $false
        $script:edited | Should Be $true
    }
    It 'gives a new block a free number, automatic numbering off, before anything else, also for library_edit_type' {
        Reset-Fake
        function Get-GroupTree { param($Root, $Items, $Groups) @(@{ name = 'X'; obj = $script:xBlock; folder = 'temp' }) }
        $script:xBlock = [pscustomobject]@{ AutoNumber = $true; Number = 2 }

        $script:records[0].number = 2; $script:records[0].class = 'FC'
        $script:comes[0].number = 2; $script:comes[0].class = 'FC'
        $m = New-TypeInstanceInWork $entry $script:version 'temp' '' $false
        $script:xBlock.AutoNumber | Should Be $true
        $script:xBlock.Number | Should Be 3
        $m.instance.number | Should Be 3
        $m.instance.numberWas | Should Be 2
        $script:records[0].number | Should Be 2
        $script:edited | Should Be $true
    }
    It 'names a copy apart from the instance' {
        Reset-Fake
        $script:comes += @(@{ object = 'S_1'; device = 'P'; folder = 'lib'; type = 'S'; version = '0.0.1' })
        $m = New-TypeInstanceInWork $entry $script:version 'temp' '' $false -Temporary
        $m.instance.object | Should Be 'X'
        @($m.copies | ForEach-Object { $_.object }) | Should Be 'S_1'
    }
    It 'refuses and takes back an instance that does not get the name of the type, as a plain block has it' {
        Reset-Fake
        $script:comes[0].object = 'X_1'
        (New-TypeInstanceInWork $entry $script:version 'temp' '' $false -Temporary).refused | Should Match 'the name X is taken.*X_1'
        @($script:records).Count | Should Be 1
    }
    It 'library_edit_type goes on as it did with such an instance' {
        Reset-Fake
        $script:comes[0].object = 'X_1'
        (New-TypeInstanceInWork $entry $script:version 'temp' '' $false).instance.object | Should Be 'X_1'
        $script:edited | Should Be $true
    }
    It 'refuses and takes back what is know-how protected, when told' {
        Reset-Fake
        $script:comes[0].knowhow = $true
        $m = New-TypeInstanceInWork $entry $script:version 'temp' '' $false -Temporary
        $m.refused | Should Match 'know-how protected \(X\)'
        @($script:records).Count | Should Be 1
    }
    It 'a know-how type whose number is held reads know-how, and no number is touched' {
        Reset-Fake
        $script:records[0].number = 2; $script:records[0].class = 'FC'
        $script:comes[0].number = 2; $script:comes[0].class = 'FC'; $script:comes[0].knowhow = $true
        $script:xBlock = [pscustomobject]@{ Name = 'X' }
        Add-Member -InputObject $script:xBlock ScriptProperty AutoNumber { $true } { throw "'set_AutoNumber' is not supported" }
        function Get-GroupTree { param($Root, $Items, $Groups) @(@{ name = 'X'; obj = $script:xBlock; folder = 'temp' }) }
        $m = New-TypeInstanceInWork $entry $script:version 'temp' '' $false -Temporary
        $m.refused | Should Match 'know-how protected \(X\)'
        $m.refused | Should Not Match 'AutoNumber'
        @($script:records).Count | Should Be 1
    }
    It 'refuses and takes back an F-block' {
        Reset-Fake
        $script:comes[0].language = 'F_LAD'
        (New-TypeInstanceInWork $entry $script:version 'temp' '' $false -Temporary).refused | Should Match 'safety program'
        @($script:records).Count | Should Be 1
    }
    It 'refuses and takes back a call that changed an object of the user' {
        Reset-Fake
        $script:after = { $script:records[0] = @{ object = 'Mine'; device = 'P'; folder = 'f'; type = 'X'; version = '0.0.1' } }
        (New-TypeInstanceInWork $entry $script:version 'temp' '' $false -Temporary).refused | Should Match 'would change what is already in the PLC \(Mine\)'
        $script:edited | Should Be $false
    }
    It 'refuses and takes back a call that took one away' {
        Reset-Fake
        $script:after = { $script:records = @($script:records | Where-Object { $_.object -ne 'Mine' }) }
        (New-TypeInstanceInWork $entry $script:version 'temp' '' $false).refused | Should Match 'Mine'
        $script:edited | Should Be $false
    }
}

Describe 'Update-ChangeStale looks the library up once' {
    function Get-LibraryStale { @{ stale = @{ S = @('R (uses 0.0.1, default 0.0.2)'); X = @('R (uses 0.0.1, default 0.0.2)') }; complete = $true; walked = 2; deps = @{} } }
    function Get-LibraryTypeMap { $script:mapWalks++; if ($script:mapThrows) { throw 'no map' }; $h = @{}; foreach ($n in $script:known) { $h[$n] = [pscustomobject]@{ Name = $n } }; $h }
    function Find-LibraryType { $script:finds++; throw 'one lookup per type' }
    function Test-TypeObjectHasInstance { param($Type) $script:withInstance -contains $Type.Name }
    function Reset-Fake { $script:mapWalks = 0; $script:finds = 0; $script:mapThrows = $false; $script:known = @('R', 'S', 'X'); $script:withInstance = @('X') }

    It 'one map, however many are stale' {
        Reset-Fake
        $r = New-Change @('S', 'X')
        @(Update-ChangeStale $null $r) | Should Be 'X'
        $script:mapWalks | Should Be 1
        $script:finds | Should Be 0
        $r.types.S.noInstance | Should Be $true
        $r.types.X.noInstance | Should Be $false
    }
    It 'no map when nothing is stale' {
        Reset-Fake
        function Get-LibraryStale { @{ stale = @{}; complete = $true; walked = 2; deps = @{} } }
        $null = Update-ChangeStale $null (New-Change @('S'))
        $script:mapWalks | Should Be 0
    }
    It 'a map that fails, or a type not in it, counts as an instance, which holds the change' {
        Reset-Fake
        $script:mapThrows = $true
        @(Update-ChangeStale $null (New-Change @('S', 'X'))) -join ',' | Should Be 'S,X'
        Reset-Fake
        $script:known = @('R', 'X')
        @(Update-ChangeStale $null (New-Change @('S', 'X'))) -join ',' | Should Be 'S,X'
    }
}

Describe 'A read of instances that fails' {
    function Get-LibraryStale { @{ stale = @{ X = @('S (uses 0.0.1, default 0.0.2)') }; complete = $true; walked = 2; deps = @{ X = @('S'); S = @() } } }
    function Get-LibraryTypeScope { 'plc' }
    function Get-TiaSoftwareList { @(@{ kind = 'plc'; device = 'P'; software = 'sw' }) }
    function Get-LibraryTypeMap {
        $v = [pscustomobject]@{ VersionNumber = [version]'0.0.1'; State = 'Committed'; IsDefault = $true }
        Add-Member -InputObject $v ScriptMethod FindInstances { param($sw) throw 'FindInstances failed' }
        @{ X = [pscustomobject]@{ Name = 'X'; Versions = @($v) } }
    }

    It 'is said, not taken for an instance, for a type outside any change' {
        $b = Get-TypesLeftBehind $null
        @($b.types).Count | Should Be 0
        @($b.unread)[0] | Should Match 'X: .*FindInstances failed'
        $read = Read-LeftBehind $null
        $read.failed | Should Be $false
        $read.unread | Should Match 'whether these have an instance.*X'
    }
    It 'stands in the result, and holds the change' {
        function Update-ChangesLeftBehind { $null }
        $r = @{ summary = 's' }
        Add-LeftBehindFacts $r $null
        $r.typesLeftBehindUnread | Should Match 'X: '
        $r.summary | Should Match 'is not fully known: could not read whether these have an instance'
        $rec = New-Change; $rec.types.S.releasedAs = '0.0.2'
        Set-RecordLeftBehind $rec (Read-LeftBehind $null)
        Get-ChangeStatus $rec | Should Be 'open'
    }
    It 'Test-TypeObjectHasInstance alone still counts it as one' {
        Test-TypeObjectHasInstance (Get-LibraryTypeMap).X | Should Be $true
    }
}

Describe 'An answer covers what the user was asked about' {
    function Get-Change([string]$Answer, [string[]]$Asked, [string[]]$Listed) {
        $r = New-Change; $r.types.S.releasedAs = '0.0.2'
        $r.leftBehindAnswer = $Answer
        if ($null -ne $Asked) { $r.leftBehindAsked = @($Asked) }
        Set-RecordLeftBehind $r @{ types = @($Listed | ForEach-Object { New-Left $_ }); failed = $false; unread = '' }
        $r.status = Get-ChangeStatus $r
        $r
    }
    It 'a no does not cover a type that came later: that one is asked about' {
        $r = Get-Change 'no' @('X') @('X', 'Q')
        $t = Format-LeftBehindAsk $r @($r.leftBehind)
        $t | Should Match 'answered no before these came: Q'
        $t | Should Match 'Ask the user, once'
        $t | Should Not Match 'The user chose to leave them'
    }
    It 'a no covers what it was asked about' {
        $r = Get-Change 'no' @('X') @('X')
        Format-LeftBehindAsk $r @($r.leftBehind) | Should Match '^The user chose to leave them'
    }
    It 'a yes does not cover one that came later either' {
        $r = Get-Change 'yes' @('X') @('X', 'Q')
        Format-LeftBehindAsk $r @($r.leftBehind) | Should Match 'answered yes before these came: Q'
    }
    It 'a record from before this was kept counts as asked' {
        $r = Get-Change 'no' $null @('X', 'Q')
        Format-LeftBehindAsk $r @($r.leftBehind) | Should Match '^The user chose to leave them'
    }
    It 'waits for the end of a change still open' {
        $r = Get-Change 'no' @('X') @('X', 'Q')
        $r.status = 'open'
        Format-LeftBehindAsk $r @($r.leftBehind) | Should Match 'when this change reaches its end'
    }
    It 'the report and next do not say the user chose it' {
        $r = Get-Change 'no' @('X') @('X', 'Q')
        $t = Format-ChangeReport $r
        $t | Should Match 'Answered no before these came, so not decided yet: Q'
        $t | Should Not Match 'The user chose to leave these'
        Format-ChangeEndNext $r | Should Match 'is finished, but it is not done'
    }
}

Describe 'Register-ChangeOnEdit, a type on the list with no dependents' {
    function Get-ChangeTypeInfo { param($Library, $Names) @($Names | ForEach-Object { @{ name = $_; class = 'CodeBlockLibraryType'; folder = ''; released = '0.0.1'; inWork = '' } }) }
    function Test-ChangeAlive { $true }
    function Add-LibraryLog { }
    function Reset-Fake {
        $script:repo = Join-Path $TestDrive ([guid]::NewGuid().ToString('N'))
        New-Item -ItemType Directory -Force -Path (Join-Path $script:repo 'library\changes') | Out-Null
        $script:Bridge = @{ repo = $script:repo; settings = @{} }
    }
    function Save-Listed([string]$Type) {
        $r = New-Change; $r.types.S.releasedAs = '0.0.2'
        Set-RecordLeftBehind $r @{ types = @(New-Left $Type); failed = $false; unread = '' }
        $null = Save-ChangeRecord $script:repo $r
        $r.id
    }
    It 'makes a record, so the work on it is held and named' {
        Reset-Fake
        $null = Save-Listed 'X'
        $c = Register-ChangeOnEdit $null @{ name = 'X' } '0.0.1' '0.0.2' @{ complete = $true; graph = @{ X = @() } } @()
        $c.id | Should Match '-X$'
        $rec = Read-ChangeRecord $script:repo $c.id
        $rec.status | Should Be 'open'
        $rec.root | Should Be 'X'
        $rec.types.X.inWork | Should Be '0.0.2'
    }
    It 'makes none for a type not on a list, as before' {
        Reset-Fake
        $null = Save-Listed 'Other'
        Register-ChangeOnEdit $null @{ name = 'X' } '0.0.1' '0.0.2' @{ complete = $true; graph = @{ X = @() } } @() | Should Be $null
    }
    It 'is done by its release and an update, as any change' {
        Reset-Fake
        $null = Save-Listed 'X'
        $c = Register-ChangeOnEdit $null @{ name = 'X' } '0.0.1' '0.0.2' @{ complete = $true; graph = @{ X = @() } } @()
        $rec = Read-ChangeRecord $script:repo $c.id
        $rec.types.X.releasedAs = '0.0.2'
        Get-ChangeStatus $rec | Should Be 'open'
        $rec.updated = $true
        Get-ChangeStatus $rec | Should Be 'done'
    }
}

Describe 'A left-behind change whose work a close without saving took back' {
    function Add-LibraryLog { }
    function Test-ChangeAlive { param($Library, $Record) $script:alive -contains $Record.id }
    function Reset-Fake {
        $script:repo = Join-Path $TestDrive ([guid]::NewGuid().ToString('N'))
        New-Item -ItemType Directory -Force -Path (Join-Path $script:repo 'library\changes') | Out-Null
        $script:Bridge = @{ repo = $script:repo; settings = @{} }
    }
    function Save-Ended([datetime]$At, [string]$Left) {
        $types = @(@{ name = 'R'; class = 'PlcTypeLibraryType'; folder = ''; released = '0.0.1'; inWork = '0.0.2' })
        $r = New-ChangeRecord -Root 'R' -From '0.0.1' -To '0.0.2' -Types $types -Levels @{ R = 0 } -At $At
        $r.types.R.releasedAs = '0.0.2'; $r.updated = $true
        if ($Left) { Set-RecordLeftBehind $r @{ types = @(New-Left $Left); failed = $false; unread = '' } }
        $null = Save-ChangeRecord $script:repo $r
        $r.id
    }
    It 'is abandoned, when it is the newest' {
        Reset-Fake
        $id = Save-Ended ([datetime]'2026-11-03 10:00') 'X'
        $script:alive = @()
        Find-CurrentChange $null | Should Be $null
        (Read-ChangeRecord $script:repo $id).status | Should Be 'abandoned'
    }
    It 'is abandoned, when it is an older one' {
        Reset-Fake
        $old = Save-Ended ([datetime]'2026-11-03 09:00') 'X'
        $new = Save-Ended ([datetime]'2026-11-03 10:00') ''
        $script:alive = @($new)
        $null = Update-ChangesLeftBehind $null @{ types = @(New-Left 'X'); failed = $false; unread = '' }
        (Read-ChangeRecord $script:repo $old).status | Should Be 'abandoned'
    }
    It 'a done one that is gone stays as it was, and one alive keeps its status' {
        Reset-Fake
        $done = Save-Ended ([datetime]'2026-11-03 09:00') ''
        $left = Save-Ended ([datetime]'2026-11-03 10:00') 'X'
        $script:alive = @($left)
        (Find-CurrentChange $null).id | Should Be $left
        (Read-ChangeRecord $script:repo $left).status | Should Be 'left-behind'
        (Read-ChangeRecord $script:repo $done).status | Should Be 'done'
    }
}

Describe 'Get-EditYesRefusal, a type a yes in work contains' {
    function Add-LibraryLog { }
    function Test-ChangeAlive { $true }
    function Get-InWorkTypes { @{ types = @($script:inWorkNow | ForEach-Object { @{ type = $_ } }); complete = $true; walked = 1 } }
    function Get-LibraryDependsOn { $script:graphWalks++; @{ graph = @{ R = @(); S = @('R'); X = @('G'); G = @(); Y = @(); O = @() }; complete = $true; walked = 6 } }
    function Reset-Fake([string]$Answer = 'yes', [string]$XInWork = '0.0.2') {
        $script:repo = Join-Path $TestDrive ([guid]::NewGuid().ToString('N'))
        New-Item -ItemType Directory -Force -Path (Join-Path $script:repo 'library\changes') | Out-Null
        $script:Bridge = @{ repo = $script:repo; settings = @{} }
        $r = New-Change @('S', 'X')
        $r.leftBehindAnswer = $Answer
        $r.types.X.inWork = $XInWork; $r.types.X.inWorkBy = 'bridge'
        $null = Save-ChangeRecord $script:repo $r
        $script:inWorkNow = @('X'); $script:graphWalks = 0
    }
    function Save-Other([string]$Root, [string[]]$Others = @()) {
        $types = @(@{ name = $Root; class = 'PlcTypeLibraryType'; folder = ''; released = '0.0.1'; inWork = '0.0.2' })
        $levels = @{}; $levels[$Root] = 0
        foreach ($o in $Others) { $types += @{ name = $o; class = 'PlcTypeLibraryType'; folder = ''; released = '0.0.1'; inWork = '' }; $levels[$o] = 1 }
        $null = Save-ChangeRecord $script:repo (New-ChangeRecord -Root $Root -From '0.0.1' -To '0.0.2' -Types $types -Levels $levels -At ([datetime]'2026-11-03 12:00'))
    }
    It 'is refused, with the way out: a second change would stop the chain' {
        Reset-Fake
        $t = Get-EditYesRefusal $null 'G'
        $t | Should Match "Type 'G' is contained by X"
        $t | Should Match 'yes in work'
        $t | Should Match 'library_discard_type'
    }
    It 'is refused also when a newer open change has nothing to do with it' {
        Reset-Fake
        Save-Other 'O'
        Get-EditYesRefusal $null 'G' | Should Match "Type 'G' is contained by X"
    }
    It 'is refused also when the type stands in another open change' {
        Reset-Fake
        Save-Other 'O' @('G')
        Get-EditYesRefusal $null 'G' | Should Match "Type 'G' is contained by X"
    }
    It 'leaves a type alone that nothing of it contains' {
        Reset-Fake
        Get-EditYesRefusal $null 'Y' | Should Be $null
    }
    It 'walks nothing and refuses nothing with no yes in work' {
        Reset-Fake 'no'
        Get-EditYesRefusal $null 'G' | Should Be $null
        $script:graphWalks | Should Be 0
        Reset-Fake 'yes' ''
        Get-EditYesRefusal $null 'G' | Should Be $null
        $script:graphWalks | Should Be 0
    }
    It 'goes through when TIA no longer has them in work' {
        Reset-Fake
        $script:inWorkNow = @()
        Get-EditYesRefusal $null 'G' | Should Be $null
    }
    It 'refuses when the walk stopped short, as it cannot tell, for a type it did not find them containing' {
        Reset-Fake
        function Get-LibraryDependsOn { @{ graph = @{ G = @() }; complete = $false; walked = 1 } }
        $t = Get-EditYesRefusal $null 'G'
        $t | Should Match 'time limit'
        $t | Should Match 'Nothing was put in work'
    }
}

Describe 'Test-ChangeAlive, a version a later release deleted' {
    function Set-Library([string[]]$Versions) {
        $script:lib = [pscustomobject]@{ TypeFolder = [pscustomobject]@{ Types = @([pscustomobject]@{ Name = 'R'; Versions = @($Versions | ForEach-Object { [pscustomobject]@{ VersionNumber = [version]$_ } }) }); Folders = @() } }
    }
    It 'a later version keeps it alive, as a release can delete the one before it' {
        Set-Library @('0.0.3')
        Test-ChangeAlive $script:lib (New-Change) | Should Be $true
    }
    It 'only earlier ones do not: that is a close without saving' {
        Set-Library @('0.0.1')
        Test-ChangeAlive $script:lib (New-Change) | Should Be $false
    }
}

Describe 'library_discard_type, on real records' {
    function Get-BridgeSession { $script:state }
    function Add-LibraryLog { $script:logged += @($args[0]) }
    function Get-TiaDeviceNames { @('Plc1') }
    function Get-TiaLibrary { $script:lib }
    function Get-LibraryTypeScope { 'plc' }
    function Invoke-TiaWrite { param($Description, $Body) $null = & $Body; @{ output = @(); transaction = $true } }
    function Get-TypeInstances { @() }
    function Get-LibraryStale { @{ stale = @{ X = @('S (uses 0.0.1, default 0.0.2)') }; complete = $true; walked = 1; deps = @{} } }
    function Test-TypeObjectHasInstance { $true }
    function Get-TypesLeftBehind { @{ types = @(); complete = $true; deps = @{} } }
    function Reset-Fake {
        $script:repo = Join-Path $TestDrive ([guid]::NewGuid().ToString('N'))
        New-Item -ItemType Directory -Force -Path (Join-Path $script:repo 'library\changes') | Out-Null
        $script:Bridge = @{ repo = $script:repo; settings = @{} }
        $script:state = New-SessionState; Register-Archive $script:state
        $script:logged = @()
        $work = [pscustomobject]@{ VersionNumber = [version]'0.0.2'; State = 'InWork'; IsDefault = $false }
        $work | Add-Member ScriptMethod Discard { $script:typeObject.Versions = @($script:typeObject.Versions | Where-Object { [string]$_.State -ne 'InWork' }) }
        $script:typeObject = [pscustomobject]@{ Name = 'X'; Versions = @([pscustomobject]@{ VersionNumber = [version]'0.0.1'; State = 'Committed'; IsDefault = $true }, $work) }
        $script:lib = [pscustomobject]@{ TypeFolder = [pscustomobject]@{ Types = @($script:typeObject); Folders = @() } }
    }
    It 'the last type of a change with no changed type: not abandoned, and it says what stands' {
        Reset-Fake
        $rec = New-LeftBehindRecord ([datetime]'2026-11-03 10:00')
        $rec.leftBehindAnswer = 'yes'
        $rec.foldersMade = @(@{ kind = 'block'; folder = 'Temp'; device = 'Plc1' })
        $rec.types['X'] = [ordered]@{ level = 1; kind = 'code block'; folder = ''; released = '0.0.1'; inWork = '0.0.2'; inWorkBy = 'bridge'; review = $null; approved = $false; releasedAs = '' }
        $null = Save-ChangeRecord $script:repo $rec
        $r = Invoke-LibraryDiscardTool ([pscustomobject]@{ name = 'X' })
        (Read-ChangeRecord $script:repo $rec.id).status | Should Be 'open'
        $r.status | Should Be 'open'
        @($r.stale) | Should Be 'X'
        $r.summary | Should Match 'on old versions, with their instances in the PLC: X'
        $script:logged -join ' ' | Should Not Match 'closed without saving'
    }
    It 'the changed type of a change ends it, and says so' {
        Reset-Fake
        $rec = New-ChangeRecord -Root 'X' -From '0.0.1' -To '0.0.2' -Types @(@{ name = 'X'; class = 'CodeBlockLibraryType'; folder = ''; released = '0.0.1'; inWork = '0.0.2' }) -Levels @{ X = 0 } -At ([datetime]'2026-11-03 10:00')
        $null = Save-ChangeRecord $script:repo $rec
        $r = Invoke-LibraryDiscardTool ([pscustomobject]@{ name = 'X' })
        (Read-ChangeRecord $script:repo $rec.id).status | Should Be 'abandoned'
        $r.status | Should Be 'abandoned'
        $r.summary | Should Match "Library change $($rec.id) ended with it"
        $script:logged -join ' ' | Should Not Match 'closed without saving'
        $script:logged -join ' ' | Should Match "$($rec.id) abandoned: .*discarded"
    }
    It 'the changed type of a change ending with it still says what is left behind' {
        Reset-Fake
        function Get-TypesLeftBehind { @{ types = @(New-Left 'Q'); complete = $true; deps = @{} } }
        $rec = New-ChangeRecord -Root 'X' -From '0.0.1' -To '0.0.2' -Types @(@{ name = 'X'; class = 'CodeBlockLibraryType'; folder = ''; released = '0.0.1'; inWork = '0.0.2' }) -Levels @{ X = 0 } -At ([datetime]'2026-11-03 10:00')
        $null = Save-ChangeRecord $script:repo $rec
        $r = Invoke-LibraryDiscardTool ([pscustomobject]@{ name = 'X' })
        $r.status | Should Be 'abandoned'
        @($r.typesLeftBehind)[0].type | Should Be 'Q'
        $r.summary | Should Match 'Left on old versions.*Q 0\.0\.1'
        $r.next | Should Match 'Left on old versions.*Q 0\.0\.1'
        (Read-ChangeRecord $script:repo $rec.id).status | Should Be 'abandoned'
    }
    It 'names no more than ten folders in its text' {
        Reset-Fake
        $rec = New-LeftBehindRecord ([datetime]'2026-11-03 10:00')
        $rec.foldersMade = @(1..300 | ForEach-Object { @{ kind = 'block'; folder = "library/some/path/of/a/type/folder_$_"; device = 'Plc1' } })
        $rec.types['X'] = [ordered]@{ level = 1; kind = 'code block'; folder = ''; released = '0.0.1'; inWork = '0.0.2'; inWorkBy = 'bridge'; review = $null; approved = $false; releasedAs = '' }
        $null = Save-ChangeRecord $script:repo $rec
        $r = Invoke-LibraryDiscardTool ([pscustomobject]@{ name = 'X' })
        $r.next | Should Match 'and 290 more \(foldersMade in the report\)'
        $l = Limit-ToolResponse $r 20000 | ConvertFrom-Json
        $l.summary | Should Not Be '[in the log file]'
        $l.next | Should Not Be '[in the log file]'
    }
}

Describe 'library_discard_type of a type of a change reads what a release reads' {
    function Get-BridgeSession { $script:state }
    function Add-LibraryLog { }
    function Get-TiaDeviceNames { @('Plc1') }
    function Get-TiaLibrary { $script:lib }
    function Get-LibraryTypeScope { 'plc' }
    function Get-LiveChange { $script:rec }
    function Invoke-TiaWrite { param($Description, $Body) $null = & $Body; @{ output = @(); transaction = $true } }
    function Get-TypeInstances { @() }
    function Save-ChangeRecord { param($Repo, $Record) if ($Record.status -in 'open', 'done', 'left-behind') { $Record.status = Get-ChangeStatus $Record }; 'r.md' }
    function Get-LibraryStale { @{ stale = $script:stale; complete = $true; walked = 1; deps = @{} } }
    function Test-ChangeAlive { $true }
    function Get-LibraryTypeMap { $h = @{}; foreach ($n in 'R', 'S', 'X') { $h[$n] = [pscustomobject]@{ Name = $n } }; $h }
    function Test-TypeObjectHasInstance { param($Type) $true }
    function Get-TypesLeftBehind { @{ types = @(); complete = $true; deps = @{} } }
    function Find-CurrentChange { $script:rec }
    $script:Bridge = @{ repo = [string]$TestDrive; settings = @{} }
    function Reset-Fake {
        $script:state = New-SessionState; Register-Archive $script:state
        $script:rec = New-Change @('S', 'X')
        $script:rec.leftBehindAnswer = 'yes'; $script:rec.temporaryFolder = 'Temp'
        $script:rec.foldersMade = @(@{ kind = 'block'; folder = 'Temp'; device = 'Plc1' })
        $script:rec.types.S.releasedAs = '0.0.2'
        $script:rec.types.X.inWork = '0.0.2'; $script:rec.types.X.inWorkBy = 'bridge'
        $script:stale = @{ X = @('S (uses 0.0.1, default 0.0.2)') }
        $work = [pscustomobject]@{ VersionNumber = [version]'0.0.2'; State = 'InWork'; IsDefault = $false }
        $work | Add-Member ScriptMethod Discard { $script:typeObject.Versions = @($script:typeObject.Versions | Where-Object { [string]$_.State -ne 'InWork' }) }
        $script:typeObject = [pscustomobject]@{ Name = 'X'; Versions = @([pscustomobject]@{ VersionNumber = [version]'0.0.1'; State = 'Committed'; IsDefault = $true }, $work) }
        $script:lib = [pscustomobject]@{ TypeFolder = [pscustomobject]@{ Types = @($script:typeObject); Folders = @() } }
    }
    It 'does not read as done with the type on old versions, its instance and the folders in the PLC, and says so' {
        Reset-Fake
        $r = Invoke-LibraryDiscardTool ([pscustomobject]@{ name = 'X' })
        $r.ok | Should Be $true
        $script:rec.status | Should Be 'open'
        $r.status | Should Be 'open'
        @($r.stale) | Should Be 'X'
        $r.summary | Should Match 'stays open'
        $r.summary | Should Match 'on old versions, with their instances in the PLC: X'
        $r.summary | Should Match 'block Temp'
        $r.next | Should Match 'library_update_usages'
    }
    It 'reads done when nothing is left' {
        Reset-Fake
        $script:stale = @{}
        $r = Invoke-LibraryDiscardTool ([pscustomobject]@{ name = 'X' })
        $script:rec.status | Should Be 'done'
        $r.status | Should Be 'done'
        $r.Contains('stale') | Should Be $false
    }
}

Describe 'library_left_behind on a long list' {
    function Get-BridgeSession { $script:state }
    function Get-TiaProject { $null }
    function Get-TiaLibrary { 'lib' }
    function Add-LibraryLog { }
    function Test-ChangeAlive { $true }
    function Get-InWorkTypes { @{ types = @(); complete = $true; walked = 1 } }
    function Get-PlcObjectRecords { @{} }
    function Get-TypesLeftBehind { @{ types = @($script:list | Where-Object { $script:hasInstance -notcontains $_.type -or $script:refuseAll }); complete = $true; deps = $script:deps } }
    function Test-FCompliantTypeVersion { $false }
    function Test-TypeObjectHasInstance { param($Type) $script:hasInstance -contains $Type.Name -and -not $script:refuseAll }
    function Get-ChangeTypeInfo { param($Library, $Names) foreach ($n in $Names) { @{ name = $n; class = 'CodeBlockLibraryType'; folder = 'lib'; released = '0.0.1'; inWork = '0.0.2' } } }
    function Invoke-TiaWrite { param($Description, $Body, $RollbackIf) $null = & $Body; @{ transaction = $true; rolledBack = $false } }
    function New-EmptyGroup { $g = [pscustomobject]@{ Groups = [pscustomobject]@{} }; Add-Member -InputObject $g.Groups ScriptMethod Find { param($n) $null }; $g }
    function Get-TiaSoftwareEntry { @{ device = 'P'; software = [pscustomobject]@{ BlockGroup = (New-EmptyGroup); TypeGroup = (New-EmptyGroup) } } }
    function Get-PlcFolderPaths { if (@($script:hasInstance).Count) { foreach ($n in 1..100) { "block`tlibrary/some/path/of/a/type/folder_$n" } } }
    function New-FakeLibType([string]$Name) {
        $v = [pscustomobject]@{ VersionNumber = [version]'0.0.1'; State = 'Committed'; IsDefault = $true; TypeName = $Name }
        Add-Member -InputObject $v ScriptMethod FindInstances { param($sw) @('info') }
        Add-Member -InputObject $v ScriptMethod Edit { param($i)
            if ($script:editThrows -contains $this.TypeName) { throw "Edit of $($this.TypeName) failed" }
            $t = $script:map[$this.TypeName]
            $t.Versions = @($t.Versions) + @([pscustomobject]@{ VersionNumber = [version]'0.0.2'; State = 'InWork'; IsDefault = $false })
        }
        [pscustomobject]@{ Name = $Name; Versions = @($v) }
    }
    function Get-LibraryTypeMap { $script:map }
    function New-TypeInstanceInWork { param($Entry, $Version, [string]$Folder, [string]$Device, [bool]$Safety, [switch]$Temporary)
        $script:hasInstance += @($Entry.name)
        if ($script:refuseAll) { return @{ refused = "know-how protected ($($Entry.name)): its code cannot be changed without the password, so it cannot move to the new versions here. Taken back. $('x' * 600)" } }
        $i = @{ object = $Entry.name; device = 'P'; folder = $Folder; type = $Entry.name; version = '0.0.1' }
        $c = @{ object = "$($Entry.name)_1"; device = 'P'; folder = 'library/some/path'; type = "Sub$($Entry.name)"; version = '0.0.1' }
        @{ instance = $i; copies = @($c); objects = @($i, $c) }
    }
    function Reset-Fake([int]$Count = 100) {
        $script:repo = Join-Path $TestDrive ([guid]::NewGuid().ToString('N'))
        New-Item -ItemType Directory -Force -Path (Join-Path $script:repo 'library\changes') | Out-Null
        $script:Bridge = @{ repo = $script:repo; settings = @{ maxResponseChars = 20000 } }
        $script:state = New-SessionState; Register-Archive $script:state
        $script:hasInstance = @(); $script:editThrows = @(); $script:refuseAll = $false
        $script:names = @(1..$Count | ForEach-Object { 'LongTypeNameOfTheLibrary_{0:d3}' -f $_ })
        $script:list = @($script:names | ForEach-Object { @{ type = $_; version = '0.0.1'; uses = @(1..12 | ForEach-Object { "ContainedTypeOfTheLibrary_$_ (uses 0.0.1, default 0.0.2)" }) } })
        $script:deps = @{}; foreach ($n in $script:names) { $script:deps[$n] = @("ContainedTypeOfTheLibrary_$n") }
        $script:map = New-Object System.Collections.Hashtable ([StringComparer]::OrdinalIgnoreCase)
        foreach ($n in $script:names) { $script:map[$n] = New-FakeLibType $n }
    }
    function Read-Limited($Result) { Limit-ToolResponse $Result 20000 | ConvertFrom-Json }

    It 'next and the summary keep their text, capped, with the whole list in a field' {
        Reset-Fake
        $r = Invoke-LibraryLeftBehindTool ([pscustomobject]@{ answer = 'yes' })
        $r.next | Should Match 'and 190 more \(updateTypes\)'
        @($r.updateTypes).Count | Should Be 200
        @($r.foldersMade).Count | Should Be 100
        ([regex]::Matches($r.next, "'[^']+'")).Count | Should Be 10
        $l = Read-Limited $r
        $l.summary | Should Not Be '[in the log file]'
        $l.next | Should Not Be '[in the log file]'
    }
    It 'stays within the response limit at every length, and keeps summary and next' {
        foreach ($count in 10, 25, 40, 60, 100) {
            foreach ($refuse in $false, $true) {
                Reset-Fake $count
                $script:refuseAll = $refuse
                $r = Invoke-LibraryLeftBehindTool ([pscustomobject]@{ answer = 'yes' })
                $text = Limit-ToolResponse $r 20000
                $text.Length | Should BeLessThan 20001
                $l = $text | ConvertFrom-Json
                $l.summary | Should Not Be '[in the log file]'
                $l.next | Should Not Be '[in the log file]'
            }
        }
    }
    It 'with no more than ten it names them all' {
        Reset-Fake 3
        $r = Invoke-LibraryLeftBehindTool ([pscustomobject]@{ answer = 'yes' })
        $r.next | Should Not Match 'updateTypes'
        ([regex]::Matches($r.next, "'[^']+'")).Count | Should Be 6
    }
    It 'long reasons do not push the summary out of the result' {
        Reset-Fake
        $script:refuseAll = $true
        $r = Invoke-LibraryLeftBehindTool ([pscustomobject]@{ answer = 'yes' })
        @($r.typesRefused).Count | Should Be 100
        @($r.typesRefused)[0].why.Length | Should BeGreaterThan 600
        $l = Read-Limited $r
        $l.summary | Should Not Be '[in the log file]'
        $l.next | Should Not Be '[in the log file]'
    }
    It 'the end of the change caps the folders it names; the report has them all' {
        Reset-Fake 1
        $rec = New-Change; $rec.types.S.releasedAs = '0.0.2'
        $rec.foldersMade = @(1..30 | ForEach-Object { @{ kind = 'block'; folder = "f$_"; device = 'P' } })
        $t = Format-FolderCleanup $rec
        ([regex]::Matches($t, 'kind block')).Count | Should Be 10
        $t | Should Match 'and 20 more \(foldersMade in the report\)'
        Format-FoldersMade $rec | Should Match 'block f30'
    }
    It 'caps what a type uses in the text' {
        $t = Format-TypesLeftBehind @(@{ type = 'X'; version = '0.0.1'; uses = @('a', 'b', 'c', 'd', 'e') })
        $t | Should Match 'uses a; b and 3 more\)'
    }
}

Describe 'library_left_behind: a type whose Edit failed' {
    function Get-BridgeSession { $script:state }
    function Get-TiaProject { $null }
    function Get-TiaLibrary { 'lib' }
    function Add-LibraryLog { }
    function Test-ChangeAlive { $true }
    function Get-InWorkTypes { @{ types = @(); complete = $true; walked = 1 } }
    function Get-PlcObjectRecords { @{} }
    function Get-TypesLeftBehind { @{ types = @($script:list | Where-Object { $script:hasInstance -notcontains $_.type }); complete = $true; deps = @{ X = @(); K = @() } } }
    function Test-FCompliantTypeVersion { $false }
    function Test-TypeObjectHasInstance { param($Type) $script:hasInstance -contains $Type.Name }
    function Get-ChangeTypeInfo { param($Library, $Names) foreach ($n in $Names) { @{ name = $n; class = 'CodeBlockLibraryType'; folder = 'lib'; released = '0.0.1'; inWork = '0.0.2' } } }
    function Invoke-TiaWrite { param($Description, $Body, $RollbackIf) $null = & $Body; @{ transaction = $true; rolledBack = $false } }
    function New-EmptyGroup { $g = [pscustomobject]@{ Groups = [pscustomobject]@{} }; Add-Member -InputObject $g.Groups ScriptMethod Find { param($n) $null }; $g }
    function Get-TiaSoftwareEntry { @{ device = 'P'; software = [pscustomobject]@{ BlockGroup = (New-EmptyGroup); TypeGroup = (New-EmptyGroup) } } }
    function Get-PlcFolderPaths { }
    function New-FailingType([string]$Name) {
        $v = [pscustomobject]@{ VersionNumber = [version]'0.0.1'; State = 'Committed'; IsDefault = $true }
        Add-Member -InputObject $v ScriptMethod FindInstances { param($sw) @('info') }
        Add-Member -InputObject $v ScriptMethod Edit { param($i) throw 'Edit failed' }
        [pscustomobject]@{ Name = $Name; Versions = @($v) }
    }
    function Get-LibraryTypeMap { @{ X = (New-FailingType 'X'); K = (New-FailingType 'K') } }
    function New-TypeInstanceInWork { param($Entry, $Version, [string]$Folder, [string]$Device, [bool]$Safety, [switch]$Temporary)
        if ($Entry.name -eq 'K') { return @{ refused = 'know-how protected (K). Taken back.' } }
        $script:hasInstance += @($Entry.name)
        $i = @{ object = $Entry.name; device = 'P'; folder = $Folder; type = $Entry.name; version = '0.0.1' }
        @{ instance = $i; copies = @(); objects = @($i) }
    }
    function Reset-Fake {
        $script:repo = Join-Path $TestDrive ([guid]::NewGuid().ToString('N'))
        New-Item -ItemType Directory -Force -Path (Join-Path $script:repo 'library\changes') | Out-Null
        $script:Bridge = @{ repo = $script:repo; settings = @{} }
        $script:state = New-SessionState; Register-Archive $script:state
        $script:hasInstance = @()
        $script:list = @((New-Left 'X'), (New-Left 'K'))
    }
    It 'is not said to stay on the list: its instance stands, so it leaves it; what was refused before an instance stays' {
        Reset-Fake
        $r = Invoke-LibraryLeftBehindTool ([pscustomobject]@{ answer = 'yes' })
        $r.ok | Should Be $false
        $r.summary | Should Match 'Refused, they stay on the list and the change is not done: K'
        $r.summary | Should Not Match 'stay on the list and the change is not done: [^.]*X \('
        $r.summary | Should Match 'Not put in work, though an instance stands, so off the list until an update moves or removes it: X'
        (@($r.typesRefused) | Where-Object { $_.type -eq 'X' }).instanceStands | Should Be $true
        (@($r.typesRefused) | Where-Object { $_.type -eq 'K' }).Contains('instanceStands') | Should Be $false
    }
}

Describe 'library_left_behind without a transaction: a refused instance that stands' {
    function Get-BridgeSession { $script:state }
    function Get-TiaProject { $null }
    function Get-TiaLibrary { 'lib' }
    function Add-LibraryLog { }
    function Test-ChangeAlive { $true }
    function Get-InWorkTypes { @{ types = @(); complete = $true; walked = 1 } }
    function Get-PlcObjectRecords { @{} }
    function Get-TypesLeftBehind { @{ types = @($script:list); complete = $true; deps = @{ X = @() } } }
    function Test-FCompliantTypeVersion { $false }
    function Test-TypeObjectHasInstance { param($Type) $script:hasInstance -contains $Type.Name }
    function New-EmptyGroup { $g = [pscustomobject]@{ Groups = [pscustomobject]@{} }; Add-Member -InputObject $g.Groups ScriptMethod Find { param($n) $null }; $g }
    function Get-TiaSoftwareEntry { @{ device = 'P'; software = [pscustomobject]@{ BlockGroup = (New-EmptyGroup); TypeGroup = (New-EmptyGroup) } } }
    function Get-PlcFolderPaths { }
    function Get-LibraryTypeMap { @{ X = [pscustomobject]@{ Name = 'X'; Versions = @([pscustomobject]@{ VersionNumber = [version]'0.0.1'; State = 'Committed'; IsDefault = $true }) } } }
    function Reset-Fake {
        $script:repo = Join-Path $TestDrive ([guid]::NewGuid().ToString('N'))
        New-Item -ItemType Directory -Force -Path (Join-Path $script:repo 'library\changes') | Out-Null
        $script:Bridge = @{ repo = $script:repo; settings = @{} }
        $script:state = New-SessionState; Register-Archive $script:state
        $script:hasInstance = @(); $script:list = @(New-Left 'X')
    }
    It 'a refusal: off the list, and held for the save' {
        Reset-Fake
        function New-TypeInstanceInWork { param($Entry) $script:hasInstance += @($Entry.name); @{ refused = 'know-how protected (X). Without a transaction this was not taken back.'; standing = @(@{ object = 'X'; device = 'P'; type = 'X' }) } }
        $r = Invoke-LibraryLeftBehindTool ([pscustomobject]@{ answer = 'yes' })
        $r.summary | Should Match 'Not put in work, though an instance stands.*: X'
        $r.summary | Should Not Match 'stay on the list and the change is not done'
        @($r.typesRefused)[0].instanceStands | Should Be $true
        $script:state.failed.ContainsKey('plc@p:x') | Should Be $true
    }
    It 'a throw: the same' {
        Reset-Fake
        function New-TypeInstanceInWork { param($Entry)
            $script:hasInstance += @($Entry.name)
            $e = [System.InvalidOperationException]::new('TIA said no'); $e.Data['standing'] = @(@{ object = 'X_copy'; device = 'P'; type = 'S' }); throw $e
        }
        $r = Invoke-LibraryLeftBehindTool ([pscustomobject]@{ answer = 'yes' })
        @($r.typesRefused)[0].instanceStands | Should Be $true
        $script:state.failed.ContainsKey('plc@p:x_copy') | Should Be $true
        @($r.objectsStanding)[0].object | Should Be 'X_copy'
        $r.summary | Should Match 'Without a transaction these stand, held for the save until each is deleted or written again: X_copy'
    }
    It 'names what stands in the result, of every type, also when the call goes on' {
        Reset-Fake
        $script:list = @((New-Left 'X'), (New-Left 'Y'))
        function Get-LibraryTypeMap { $h = @{}; foreach ($n in 'X', 'Y') { $h[$n] = [pscustomobject]@{ Name = $n; Versions = @([pscustomobject]@{ VersionNumber = [version]'0.0.1'; State = 'Committed'; IsDefault = $true }) } }; $h }
        function Get-TypesLeftBehind { @{ types = @($script:list); complete = $true; deps = @{ X = @(); Y = @() } } }
        function New-TypeInstanceInWork { param($Entry)
            if ($Entry.name -eq 'X') { $e = [System.InvalidOperationException]::new('TIA said no'); $e.Data['standing'] = @(@{ object = 'S_1'; device = 'P'; type = 'S' }); throw $e }
            @{ refused = 'refused. Without a transaction this was not taken back.'; standing = @(@{ object = 'Y'; device = 'P'; type = 'Y' }) }
        }
        $r = Invoke-LibraryLeftBehindTool ([pscustomobject]@{ answer = 'yes' })
        @($r.objectsStanding | ForEach-Object { $_.object }) -join ',' | Should Be 'S_1,Y'
        @($script:CommittedFacts['objectsStanding']).Count | Should Be 2
    }
    It 'with a transaction there is nothing to name' {
        Reset-Fake
        function New-TypeInstanceInWork { param($Entry) @{ refused = 'know-how protected (X). Taken back.' } }
        $r = Invoke-LibraryLeftBehindTool ([pscustomobject]@{ answer = 'yes' })
        $r.Contains('objectsStanding') | Should Be $false
        $r.summary | Should Not Match 'these stand'
    }
}

Describe 'An answer records what it was asked about' {
    function Get-BridgeSession { $script:state }
    function Get-TiaProject { $null }
    function Get-TiaLibrary { 'lib' }
    function Add-LibraryLog { }
    function Test-ChangeAlive { $true }
    function Get-InWorkTypes { @{ types = @(); complete = $true; walked = 1 } }
    function Get-TypesLeftBehind { @{ types = @($script:list); complete = $true; deps = @{} } }
    It 'a no holds the list as it stood' {
        $script:repo = Join-Path $TestDrive ([guid]::NewGuid().ToString('N'))
        New-Item -ItemType Directory -Force -Path (Join-Path $script:repo 'library\changes') | Out-Null
        $script:Bridge = @{ repo = $script:repo; settings = @{} }
        $script:state = New-SessionState; Register-Archive $script:state
        $script:list = @((New-Left 'X'), (New-Left 'Y'))
        $r = New-Change; $r.types.S.releasedAs = '0.0.2'
        $null = Save-ChangeRecord $script:repo $r
        $x = Invoke-LibraryLeftBehindTool ([pscustomobject]@{ answer = 'no' })
        $saved = Read-ChangeRecord $script:repo $x.change
        @($saved.leftBehindAsked) -join ',' | Should Be 'X,Y'
        $x.next | Should Match 'The user chose to leave them'
        $script:list = @((New-Left 'X'), (New-Left 'Y'), (New-Left 'Q'))
        $later = @{ summary = 's'; next = 'n' }
        Add-LeftBehindFacts $later 'lib'
        $later.next | Should Match 'answered no before these came: Q'
        $later.next | Should Not Match 'The user chose to leave them'
    }
}
