$here = Split-Path -Parent $MyInvocation.MyCommand.Path
foreach ($f in 'Mcp.ps1', 'Tia.ps1', 'Repo.ps1', 'Rules.ps1', 'Guards.ps1', 'Bridge.ps1', 'Tools\Objects.ps1', 'Tools\Plc.ps1', 'Tools\Hmi.ps1', 'Tools\Library.ps1',
               'Tools\Report.ps1') { . (Join-Path $here "..\$f") }

# master_copy_from_project of a user folder (source_folder). The V20 API lists the folders as a source of
# MasterCopies.Create; not yet tried on a real project, so these tests hold what the bridge asks of TIA, not what TIA does.
# Stand-ins: the folder trees of a PLC and an HMI device, and a library whose Create records what it was given.

function New-FakeFolder([string]$Name, [object[]]$Groups = @()) {
    [pscustomobject]@{ Name = $Name; Groups = @($Groups); Folders = @($Groups); Blocks = @(); Types = @(); TagTables = @(); Screens = @() }
}

function New-FakeMasterCopies {
    $c = [pscustomobject]@{ made = New-Object System.Collections.ArrayList; existing = @{}; fails = $false; failingLeaves = $null }
    $c | Add-Member ScriptMethod Find { param($n) $this.existing[$n] }
    $c | Add-Member ScriptMethod Create {
        param($source)
        if ($this.fails) {
            if ($this.failingLeaves) { $this.existing[$this.failingLeaves] = [pscustomobject]@{ } }
            throw [System.InvalidOperationException]::new('TIA said no')
        }
        [void]$this.made.Add($source)
    }
    $c
}

function New-FakeLibrary {
    $copies = New-FakeMasterCopies
    # the library folder the master copy goes in: Get-OrCreateGroup finds or makes it
    $target = [pscustomobject]@{ Name = 'x'; MasterCopies = $copies; Folders = $null; asked = $null }
    $folders = [pscustomobject]@{ target = $target }
    $folders | Add-Member ScriptMethod Find { param($n) $this.target.asked = $n; $this.target }
    $root = [pscustomobject]@{ Name = 'MasterCopies'; MasterCopies = $copies; Folders = $folders }
    $lib = [pscustomobject]@{ MasterCopyFolder = $root; IsReadOnly = $false; saved = 0; copies = $copies; target = $target }
    $lib | Add-Member ScriptMethod Save { $this.saved++ }
    $lib
}

function Get-KindRoot { $script:device }
function Get-TiaLibrary { $script:library }
function Invoke-TiaWrite([string]$Description, [scriptblock]$Body, [switch]$NoTransaction, [scriptblock]$RollbackIf) {
    $script:writes++
    @{ output = @(& $Body); transaction = $true; rolledBack = $false; commitError = $null; note = $null }
}

function Set-FakeProject {
    Initialize-BridgeContext @{ maxResponseChars = 20000 }
    Set-BridgeProject -Name 'P' -Path 'C:\P.ap20' -Repo (Join-Path $TestDrive ('R' + [guid]::NewGuid().ToString('N')))
    Register-Archive (Get-BridgeSession)
    $script:writes = 0
    $script:inner = New-FakeFolder 'inner'
    $script:zzFolder = New-FakeFolder 'zzFolder' -Groups @($script:inner)
    $script:typeFolder = New-FakeFolder 'zzTypes'
    $script:tagFolder = New-FakeFolder 'zzTags'
    $script:screenFolder = New-FakeFolder 'zzScreens'
    $script:device = [pscustomobject]@{
        BlockGroup = New-FakeFolder 'root' -Groups @($script:zzFolder)
        TypeGroup = New-FakeFolder 'root' -Groups @($script:typeFolder)
        TagTableGroup = New-FakeFolder 'root' -Groups @($script:tagFolder)
        ScreenFolder = New-FakeFolder 'root' -Groups @($script:screenFolder)
    }
    $script:library = New-FakeLibrary
}

function Invoke-FromProject([hashtable]$Arguments) { Invoke-MasterCopyFromProjectTool ([pscustomobject]$Arguments) }

Describe 'master_copy_from_project of a user folder' {
    It 'hands that folder to TIA, in the library folder asked for, and names the master copy after it' {
        Set-FakeProject
        $r = Invoke-FromProject @{ kind = 'block'; source_folder = 'zzFolder'; folder = 'x' }
        $r.ok | Should Be $true
        $r.masterCopy | Should Be 'zzFolder'
        $r.sourceFolder | Should Be 'zzFolder'
        $r.folder | Should Be 'x'
        $script:library.target.asked | Should Be 'x'
        $script:library.copies.made.Count | Should Be 1
        [object]::ReferenceEquals($script:library.copies.made[0], $script:zzFolder) | Should Be $true
    }

    It 'finds a folder inside another by its whole path' {
        Set-FakeProject
        $r = Invoke-FromProject @{ kind = 'block'; source_folder = 'zzFolder/inner' }
        $r.ok | Should Be $true
        $r.masterCopy | Should Be 'inner'
        $r.sourceFolder | Should Be 'zzFolder/inner'
        [object]::ReferenceEquals($script:library.copies.made[0], $script:inner) | Should Be $true
    }

    It 'reads the tree of the kind it is given' {
        Set-FakeProject
        (Invoke-FromProject @{ kind = 'db'; source_folder = 'zzFolder' }).ok | Should Be $true
        (Invoke-FromProject @{ kind = 'type'; source_folder = 'zzTypes' }).ok | Should Be $true
        (Invoke-FromProject @{ kind = 'plc_tag_table'; source_folder = 'zzTags' }).ok | Should Be $true
        $script:library.copies.made.Count | Should Be 3
        [object]::ReferenceEquals($script:library.copies.made[1], $script:typeFolder) | Should Be $true
        [object]::ReferenceEquals($script:library.copies.made[2], $script:tagFolder) | Should Be $true
    }

    It 'refuses an existing master copy of that name without replace, and replaces it with replace=true' {
        Set-FakeProject
        $old = [pscustomobject]@{ deleted = 0 }
        $old | Add-Member ScriptMethod Delete { $this.deleted++ }
        $script:library.copies.existing['zzFolder'] = $old
        $r = Invoke-FromProject @{ kind = 'block'; source_folder = 'zzFolder' }
        $r.ok | Should Be $false
        $r.refused | Should Match 'replace=true'
        $script:writes | Should Be 0
        $r = Invoke-FromProject @{ kind = 'block'; source_folder = 'zzFolder'; replace = $true }
        $r.ok | Should Be $true
        $r.replaced | Should Be $true
        $old.deleted | Should Be 1
    }

    It 'saves a global library, as for an object' {
        Set-FakeProject
        $r = Invoke-FromProject @{ kind = 'block'; source_folder = 'zzFolder'; library = 'G' }
        $r.globalLibrarySaved | Should Be $true
        $script:library.saved | Should Be 1
    }

    It 'lets the exception of TIA through, and holds nothing for a name the library folder still does not have' {
        Set-FakeProject
        $script:library.copies.fails = $true
        { Invoke-FromProject @{ kind = 'block'; source_folder = 'zzFolder' } } | Should Throw 'TIA said no'
        (Get-BridgeSession).failed.Count | Should Be 0
    }

    It 'holds a failed replace, as the old master copy may be gone, until the same folder is written again' {
        Set-FakeProject
        $old = [pscustomobject]@{ }
        $old | Add-Member ScriptMethod Delete { }
        $script:library.copies.existing['zzFolder'] = $old
        $script:library.copies.fails = $true
        { Invoke-FromProject @{ kind = 'block'; source_folder = 'zzFolder'; replace = $true } } | Should Throw 'TIA said no'
        (Get-BridgeSession).failed.Keys -join ',' | Should Be 'library:mc:zzfolder'
        $script:library.copies.fails = $false
        (Invoke-FromProject @{ kind = 'block'; source_folder = 'zzFolder'; replace = $true }).ok | Should Be $true
        (Get-BridgeSession).failed.Count | Should Be 0
    }

    It 'keeps the hold of an earlier failure when a retry fails with nothing standing: the old master copy is gone' {
        Set-FakeProject
        $old = [pscustomobject]@{ }
        # a global library has no transaction: the delete stays when Create throws
        $old | Add-Member ScriptMethod Delete { $script:library.copies.existing.Remove('zzFolder') }
        $script:library.copies.existing['zzFolder'] = $old
        $script:library.copies.fails = $true
        { Invoke-FromProject @{ kind = 'block'; source_folder = 'zzFolder'; library = 'G'; replace = $true } } | Should Throw 'TIA said no'
        { Invoke-FromProject @{ kind = 'block'; source_folder = 'zzFolder'; library = 'G' } } | Should Throw 'TIA said no'
        (Get-BridgeSession).failed.Keys -join ',' | Should Be 'library:mc:zzfolder'
    }

    It 'holds a failure that left a master copy of that name behind' {
        Set-FakeProject
        $script:library.copies.fails = $true
        $script:library.copies.failingLeaves = 'zzFolder'
        { Invoke-FromProject @{ kind = 'block'; source_folder = 'zzFolder' } } | Should Throw 'TIA said no'
        (Get-BridgeSession).failed.Keys -join ',' | Should Be 'library:mc:zzfolder'
    }

    It 'holds a failure when the library can no longer be read' {
        Set-FakeProject
        $script:library.copies.fails = $true
        $script:library.copies | Add-Member ScriptMethod Find { param($n) if ($script:createAsked) { throw 'TIA gone' } } -Force
        $script:library.copies | Add-Member ScriptMethod Create { param($s) $script:createAsked = $true; throw [System.InvalidOperationException]::new('TIA said no') } -Force
        $script:createAsked = $false
        { Invoke-FromProject @{ kind = 'block'; source_folder = 'zzFolder' } } | Should Throw 'TIA said no'
        (Get-BridgeSession).failed.Keys -join ',' | Should Be 'library:mc:zzfolder'
    }
}

Describe 'master_copy_from_project of a named object' {
    function Set-FakeBlock {
        Set-FakeProject
        $script:block = [pscustomobject]@{ Name = 'zzBlock' }
        $script:zzFolder.Blocks = @($script:block)
    }

    It 'hands that object to TIA, finds it in any folder, and names no source folder' {
        Set-FakeBlock
        $r = Invoke-FromProject @{ kind = 'block'; name = 'zzBlock'; folder = 'x' }
        $r.ok | Should Be $true
        $r.masterCopy | Should Be 'zzBlock'
        $r.folder | Should Be 'x'
        $r.ContainsKey('sourceFolder') | Should Be $false
        $script:library.copies.made.Count | Should Be 1
        [object]::ReferenceEquals($script:library.copies.made[0], $script:block) | Should Be $true
        (Get-BridgeSession).failed.Count | Should Be 0
    }

    It 'lets the exception of TIA through, and holds nothing for a name the library folder still does not have' {
        Set-FakeBlock
        $script:library.copies.fails = $true
        { Invoke-FromProject @{ kind = 'block'; name = 'zzBlock' } } | Should Throw 'TIA said no'
        (Get-BridgeSession).failed.Count | Should Be 0
    }

    It 'holds a failed replace until the same object is written again' {
        Set-FakeBlock
        $old = [pscustomobject]@{ }
        $old | Add-Member ScriptMethod Delete { }
        $script:library.copies.existing['zzBlock'] = $old
        $script:library.copies.fails = $true
        { Invoke-FromProject @{ kind = 'block'; name = 'zzBlock'; replace = $true } } | Should Throw 'TIA said no'
        (Get-BridgeSession).failed.Keys -join ',' | Should Be 'library:mc:zzblock'
        $script:library.copies.fails = $false
        (Invoke-FromProject @{ kind = 'block'; name = 'zzBlock'; replace = $true }).ok | Should Be $true
        (Get-BridgeSession).failed.Count | Should Be 0
    }
}

Describe 'master_copy_from_project refuses, asking nothing of TIA' {
    It 'a folder of an HMI kind, as nothing can place it, and says so' {
        Set-FakeProject
        $r = Invoke-FromProject @{ kind = 'hmi_screen'; source_folder = 'zzScreens' }
        $r.ok | Should Be $false
        $r.refused | Should MatchExactly 'HMI folder'
        $r.refused | Should Match 'block, db, plc_tag_table, type'
        $script:writes | Should Be 0
    }

    It 'both a name and a folder, and neither' {
        Set-FakeProject
        (Invoke-FromProject @{ kind = 'block'; name = 'A'; source_folder = 'zzFolder' }).refused | Should Match 'not both'
        (Invoke-FromProject @{ kind = 'block' }).refused | Should Match 'source_folder'
        $script:writes | Should Be 0
    }

    It 'a root folder' {
        Set-FakeProject
        (Invoke-FromProject @{ kind = 'block'; source_folder = '/' }).refused | Should Match 'root folder'
        $script:writes | Should Be 0
    }

    It 'wildcards and a path with an empty part' {
        Set-FakeProject
        (Invoke-FromProject @{ kind = 'block'; source_folder = 'zz*' }).refused | Should Match 'wildcard'
        (Invoke-FromProject @{ kind = 'block'; source_folder = 'zzFolder//inner' }).refused | Should Match 'exact'
        $script:writes | Should Be 0
    }

    It 'a folder that does not exist, with the folders that do at that level; names are exact' {
        Set-FakeProject
        $r = Invoke-FromProject @{ kind = 'block'; source_folder = 'zzFolder/nope' }
        $r.refused | Should Match "No folder 'zzFolder/nope'"
        $r.refused | Should Match 'inner'
        (Invoke-FromProject @{ kind = 'block'; source_folder = 'zzfolder' }).refused | Should Match "No folder 'zzfolder'"
        $script:writes | Should Be 0
    }
}

Describe 'master_copy_from_project with the name of a folder, not of an object' {
    It 'says it is a folder, where it stands and what to pass, also for one deeper' {
        Set-FakeProject
        $r = Invoke-FromProject @{ kind = 'block'; name = 'zzFolder'; folder = 'x' }
        $r.ok | Should Be $false
        $r.refused | Should Match "No block named 'zzFolder'"
        $r.refused | Should Match "source_folder: 'zzFolder'"
        (Invoke-FromProject @{ kind = 'block'; name = 'inner' }).refused | Should Match "source_folder: 'zzFolder/inner'"
        $script:writes | Should Be 0
    }

    It 'says a folder of an HMI kind cannot be made' {
        Set-FakeProject
        $r = Invoke-FromProject @{ kind = 'hmi_screen'; name = 'zzScreens' }
        $r.refused | Should Match "No hmi_screen named 'zzScreens'"
        $r.refused | Should MatchExactly 'HMI folder'
        $r.refused | Should Not Match 'source_folder:'
    }

    It 'stays the plain refusal when nothing has that name' {
        Set-FakeProject
        (Invoke-FromProject @{ kind = 'block'; name = 'zzNothing' }).refused | Should Be "No block named 'zzNothing'."
    }
}

Describe 'master_copy_to_project of a folder' {
    It 'knows the PLC folders, which have a CreateFrom for it' {
        (Get-MasterCopyTarget 'PlcBlockUserGroup').composition | Should Be 'Groups'
        (Get-MasterCopyTarget 'PlcTypeUserGroup').composition | Should Be 'Groups'
        (Get-MasterCopyTarget 'PlcTagTableUserGroup').composition | Should Be 'Groups'
    }

    It 'says an HMI folder cannot be placed, before anything is written' {
        { Get-MasterCopyTarget 'ScreenUserFolder' } | Should Throw 'cannot be placed by the bridge'
    }
}
