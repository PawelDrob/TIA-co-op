# A project is its .ap20 path, not its name: the session state (archive gate, save rules), the choice between open
# projects, the attach and the project repo. Two projects of one name (a retrieved archive, a copy) never share them.
$here = Split-Path -Parent $MyInvocation.MyCommand.Path
foreach ($f in 'Mcp.ps1', 'Tia.ps1', 'Repo.ps1', 'Rules.ps1', 'Guards.ps1', 'Bridge.ps1', 'Tools\Objects.ps1', 'Tools\Session.ps1') { . (Join-Path $here "..\$f") }

if (-not ('Siemens.Engineering.ProjectArchivationMode' -as [type])) {
    Add-Type -TypeDefinition 'namespace Siemens.Engineering { public enum ProjectArchivationMode { None, Compressed, DiscardRestorableData, DiscardRestorableDataAndCompressed } }'
}

Describe 'Session state per project path' {
    $root = Join-Path $TestDrive 'projects'
    $a = 'C:\P\Same\Same.ap20'; $b = 'D:\Copy\Same\Same.ap20'

    function Reset-Bridge { Initialize-BridgeContext @{ projectsRoot = $root; maxResponseChars = 20000 } }

    It 'does not give a project of the same name at another path the first one''s archive' {
        Reset-Bridge
        Set-BridgeProject -Name 'Same' -Path $a -Repo (Join-Path $root 'Same')
        Register-Archive (Get-BridgeSession)
        Get-ArchiveRefusal 'import' | Should BeNullOrEmpty
        Set-BridgeProject -Name 'Same' -Path $b -Repo (Join-Path $root 'Same-copy')
        Get-ArchiveRefusal 'import' | Should Match 'session archive'
    }

    It 'does not give it the first one''s save rules' {
        Reset-Bridge
        Set-BridgeProject -Name 'Same' -Path $a -Repo (Join-Path $root 'Same')
        Register-Write (Get-BridgeSession) -Scope 'plc' -Device 'PLC_1' -Items @(@{ name = 'FB1'; ok = $true })
        Set-BridgeProject -Name 'Same' -Path $b -Repo (Join-Path $root 'Same-copy')
        @(Test-SaveAllowed (Get-BridgeSession)).Count | Should Be 0
    }

    It 'keeps the state of each path when switching back, whatever the case of the path' {
        Reset-Bridge
        Set-BridgeProject -Name 'Same' -Path $a -Repo (Join-Path $root 'Same')
        Register-Archive (Get-BridgeSession)
        Set-BridgeProject -Name 'Same' -Path $b -Repo (Join-Path $root 'Same-copy')
        Test-WriteAllowed (Get-BridgeSession) | Should Match 'archive'
        Set-BridgeProject -Name 'Same' -Path $a.ToUpperInvariant() -Repo (Join-Path $root 'Same')
        Test-WriteAllowed (Get-BridgeSession) | Should BeNullOrEmpty
    }

    It 'stores the save rules of the bound path in its repo after a tool call' {
        Reset-Bridge
        Set-BridgeProject -Name 'Same' -Path $a -Repo (Join-Path $root 'Same')
        Register-Write (Get-BridgeSession) -Scope 'plc' -Device 'PLC_1' -Items @(@{ name = 'OnlyInA'; ok = $true })
        $copyRepo = Join-Path $root 'Same-copy'
        Set-BridgeProject -Name 'Same' -Path $b -Repo $copyRepo
        $null = Invoke-BridgeTool 'list' { param($x) @{ ok = $true; items = @() } } (New-Object psobject)
        Get-Content (Join-Path $copyRepo '.tiabridge-session.json') -Raw | Should Not Match 'OnlyInA'
    }
}

Describe 'Select-TiaProject with two open projects of one name' {
    $open = @(
        @{ processId = 11; name = 'Same'; path = 'C:\P\Same\Same.ap20' }
        @{ processId = 12; name = 'Same'; path = 'D:\Copy\Same\Same.ap20' }
        @{ processId = 13; name = 'Other'; path = 'C:\P\Other\Other.ap20' }
    )

    It 'refuses the name and names both paths' {
        { Select-TiaProject -Open $open -Requested 'Same' } | Should Throw 'C:\P\Same\Same.ap20'
        { Select-TiaProject -Open $open -Requested 'same' } | Should Throw 'D:\Copy\Same\Same.ap20'
    }

    It 'takes either by its path, and a name only one project has' {
        (Select-TiaProject -Open $open -Requested 'D:\Copy\Same\Same.ap20').processId | Should Be 12
        (Select-TiaProject -Open $open -Requested 'Other').processId | Should Be 13
    }

    It 'lists the paths of the shared name when no project is requested, since the name would not choose' {
        { Select-TiaProject -Open $open -Requested '' } | Should Throw 'D:\Copy\Same\Same.ap20'
    }
}

Describe 'Find-PortalProject (the project of the selected path in the attached TIA)' {
    function New-Project([string]$Path) { New-Object psobject -Property @{ Path = [System.IO.FileInfo]$Path } }
    function New-Portal([object[]]$Projects) {
        $p = New-Object psobject -Property @{ Projects = $Projects; disposed = $false }
        $p | Add-Member ScriptMethod Dispose { $this.disposed = $true }
        $p
    }

    It 'returns the project at that path, not the first one' {
        $portal = New-Portal @((New-Project 'C:\A\A.ap20'), (New-Project 'C:\B\B.ap20'))
        (Find-PortalProject $portal 'C:\B\B.ap20').Path.FullName | Should Be 'C:\B\B.ap20'
    }

    It 'does not fall back to another project: names the path and detaches' {
        $portal = New-Portal @((New-Project 'C:\A\A.ap20'))
        { Find-PortalProject $portal 'C:\B\B.ap20' } | Should Throw 'C:\B\B.ap20'
        $portal.disposed | Should Be $true
    }
}

Describe 'A repo belongs to one project path' {
    $root = Join-Path $TestDrive 'r'
    $a = 'C:\P\P\P.ap20'; $b = 'D:\Copy\P\P.ap20'
    function New-Repo([string]$Folder, [string]$Path) {
        $null = Initialize-ProjectRepo -Root $root -ProjectName 'P' -ProjectPath $Path -PlcDevices @() -HmiDevices @() -RepoName $Folder
    }
    New-Repo 'P' $a

    It 'Initialize-ProjectRepo refuses another path and leaves tiabridge.json as it was' {
        $before = Get-Content (Join-Path $root 'P\tiabridge.json') -Raw
        { Initialize-ProjectRepo -Root $root -ProjectName 'P' -ProjectPath $b -PlcDevices @() -HmiDevices @() } | Should Throw $a
        Get-Content (Join-Path $root 'P\tiabridge.json') -Raw | Should Be $before
    }

    It 'Initialize-ProjectRepo moves the repo to the new path with -Moved, and says so' {
        $null = New-Repo 'P-moving' $a
        $r = Initialize-ProjectRepo -Root $root -ProjectName 'P' -ProjectPath $b -PlcDevices @() -HmiDevices @() -RepoName 'P-moving' -Moved
        $r.pathChanged | Should Be $true
        $r.oldPath | Should Be $a
        (Get-Content (Join-Path $root 'P-moving\tiabridge.json') -Raw | ConvertFrom-Json).projectPath | Should Be $b
        Remove-Item (Join-Path $root 'P-moving') -Recurse -Force
    }

    It 'Resolve-ProjectRepo: no repo yet, or the same path in any case, needs nothing' {
        (Resolve-ProjectRepo -Root $root -ProjectName 'New' -ProjectPath 'C:\New.ap20').refused | Should BeNullOrEmpty
        (Resolve-ProjectRepo -Root $root -ProjectName 'P' -ProjectPath $a.ToLowerInvariant()).refused | Should BeNullOrEmpty
    }

    It 'Resolve-ProjectRepo: another path is refused with both paths and the two ways on' {
        $r = Resolve-ProjectRepo -Root $root -ProjectName 'P' -ProjectPath $b
        $r.refused | Should Match ([regex]::Escape($a))
        $r.refused | Should Match ([regex]::Escape($b))
        $r.refused | Should Match 'moved: true'
        $r.refused | Should Match 'repo: '
    }

    It 'Resolve-ProjectRepo: moved passes, and what is no folder name is refused' {
        (Resolve-ProjectRepo -Root $root -ProjectName 'P' -ProjectPath $b -Moved).refused | Should BeNullOrEmpty
        (Resolve-ProjectRepo -Root $root -ProjectName 'P' -ProjectPath $b -RepoName '..').refused | Should Match 'plain folder name'
    }

    It 'Resolve-ProjectRepo: takes the one repo that records the path, and refuses when two do' {
        New-Repo 'P-b' $b
        $r = Resolve-ProjectRepo -Root $root -ProjectName 'P' -ProjectPath $b
        $r.refused | Should BeNullOrEmpty
        $r.repoName | Should Be 'P-b'
        New-Repo 'P-c' $b
        $r = Resolve-ProjectRepo -Root $root -ProjectName 'P' -ProjectPath $b
        $r.refused | Should Match 'P-b'
        $r.refused | Should Match 'P-c'
    }

    It 'sees no other path for a path with non-ASCII characters' {
        # tiabridge.json is UTF-8: read as ANSI, the same path would look like another one on every connect
        $u = 'C:\P\Pr' + [char]0x00FC + 'f' + [char]0x0142 + '\U.ap20'
        $null = Initialize-ProjectRepo -Root $root -ProjectName 'U' -ProjectPath $u -PlcDevices @() -HmiDevices @()
        (Resolve-ProjectRepo -Root $root -ProjectName 'U' -ProjectPath $u).refused | Should BeNullOrEmpty
        (Initialize-ProjectRepo -Root $root -ProjectName 'U' -ProjectPath $u -PlcDevices @() -HmiDevices @()).pathChanged | Should Be $false
    }
}

Describe 'connect: a repo belongs to one project path' {
    $root = Join-Path $TestDrive 'Projects'
    $first = 'C:\P\Hp\Hp.ap20'
    $copy = 'D:\Copy\Hp\Hp.ap20'

    function New-FakeProject([string]$Path) {
        $p = New-Object psobject -Property @{ Name = 'Hp'; Path = [System.IO.FileInfo]$Path; IsModified = $false }
        $p | Add-Member ScriptMethod Archive { param($Dir, $Name, $Mode) $script:archives++; Set-Content (Join-Path $Dir.FullName $Name) 'zap' }
        $p
    }
    function Import-Openness { }
    function Test-OpennessGroup { $null }
    function Get-TiaProcesses { @(foreach ($p in $script:openPaths) { @{ processId = 1; name = 'Hp'; path = $p } }) }
    function Connect-Tia($Selected) { $script:attached++; $script:Bridge.project = New-FakeProject $Selected.path }
    function Reset-TiaConnection { $script:Bridge.project = $null }
    function Get-TiaProject { $script:Bridge.project }
    function Get-TiaSoftwareList { @() }
    function Read-Cfg([string]$Repo) { Get-Content (Join-Path $root "$Repo\tiabridge.json") -Raw | ConvertFrom-Json }
    function Connect-To([string]$Path, [string]$Extra = '') {
        $script:openPaths = @($Path)
        Invoke-ConnectTool ("{`"project`":`"$($Path -replace '\\', '\\')`"$Extra}" | ConvertFrom-Json)
    }
    function Reset-Bridge {
        Initialize-BridgeContext @{ projectsRoot = $root; archivesKept = 10; maxResponseChars = 20000 }
        $script:attached = 0; $script:archives = 0
    }
    # every test starts from no repos: one per test keeps them independent
    function Reset-Repos { if (Test-Path $root) { Remove-Item $root -Recurse -Force } }

    It 'refuses a project of the same name at another path, names both paths, attaches to nothing and changes nothing' {
        Reset-Repos; Reset-Bridge
        (Connect-To $first).ok | Should Be $true
        $before = Get-Content (Join-Path $root 'Hp\tiabridge.json') -Raw
        $script:attached = 0
        $r = Connect-To $copy
        $r.ok | Should Be $false
        $r.refused | Should Match ([regex]::Escape($first))
        $r.refused | Should Match ([regex]::Escape($copy))
        $script:attached | Should Be 0
        Get-Content (Join-Path $root 'Hp\tiabridge.json') -Raw | Should Be $before
        $script:Bridge.projectPath | Should Be $first
    }

    It 'moved: true keeps the repo, records the new path and makes a session archive for that path' {
        Reset-Repos; Reset-Bridge
        (Connect-To $first).ok | Should Be $true
        $script:archives = 0
        $r = Connect-To $copy ',"moved":true'
        $r.ok | Should Be $true
        $script:Bridge.repo | Should Be (Join-Path $root 'Hp')
        (Read-Cfg 'Hp').projectPath | Should Be $copy
        $r.pathChanged | Should Match ([regex]::Escape($first))
        $script:archives | Should Be 1
        $r.session.writesAllowed | Should Be $true
    }

    It 'repo: gives the other project its own repo, with its own archive, and leaves the first repo alone' {
        Reset-Repos; Reset-Bridge
        (Connect-To $first).ok | Should Be $true
        $before = Get-Content (Join-Path $root 'Hp\tiabridge.json') -Raw
        $script:archives = 0
        $r = Connect-To $copy ',"repo":"Hp-copy"'
        $r.ok | Should Be $true
        $script:Bridge.repo | Should Be (Join-Path $root 'Hp-copy')
        (Read-Cfg 'Hp-copy').projectPath | Should Be $copy
        $r.pathChanged | Should BeNullOrEmpty
        $script:archives | Should Be 1
        @(Get-ChildItem (Join-Path $root 'Hp-copy\archives')).Count | Should Be 1
        Get-Content (Join-Path $root 'Hp\tiabridge.json') -Raw | Should Be $before
    }

    It 'finds that repo again without repo: the repo that records the path is the project''s repo' {
        Reset-Repos; Reset-Bridge
        (Connect-To $first).ok | Should Be $true
        (Connect-To $copy ',"repo":"Hp-copy"').ok | Should Be $true
        Reset-Bridge        # a new bridge process
        $r = Connect-To $copy
        $r.ok | Should Be $true
        $script:Bridge.repo | Should Be (Join-Path $root 'Hp-copy')
        $r.repoByPath | Should Match 'Hp-copy'
    }

    It 'refuses a repo: that belongs to another path as well' {
        Reset-Repos; Reset-Bridge
        (Connect-To $first).ok | Should Be $true
        $r = Connect-To 'E:\Third\Hp\Hp.ap20' ',"repo":"Hp"'
        $r.ok | Should Be $false
        $r.refused | Should Match ([regex]::Escape($first))
    }

    It 'refuses a repo: that is not a plain folder name, before attaching' {
        Reset-Repos; Reset-Bridge
        (Connect-To $first ',"repo":".."').refused | Should Match 'plain folder name'
        $script:attached | Should Be 0
    }

    It 'refuses a name two open projects share, with both paths, and takes either by its path' {
        Reset-Repos; Reset-Bridge
        $script:openPaths = @($first, $copy)
        { Invoke-ConnectTool ('{"project":"Hp"}' | ConvertFrom-Json) } | Should Throw $copy
        $script:attached | Should Be 0
        (Invoke-ConnectTool ("{`"project`":`"$($copy -replace '\\', '\\')`"}" | ConvertFrom-Json)).projectPath | Should Be $copy
    }

    It 'reports a switch between two projects of one name by the path' {
        Reset-Repos; Reset-Bridge
        (Connect-To $first).ok | Should Be $true
        (Connect-To $copy ',"repo":"Hp-copy"').switchedFrom | Should Be $first
    }

    It 'makes the archive again for the second project of one name, and only once for each when switching back' {
        Reset-Repos; Reset-Bridge
        (Connect-To $first).archive.ok | Should Be $true
        (Connect-To $copy ',"repo":"Hp-copy"').archive.ok | Should Be $true
        $script:archives = 0
        (Connect-To $first).archive | Should BeNullOrEmpty
        (Connect-To $copy).archive | Should BeNullOrEmpty
        $script:archives | Should Be 0
    }
}
