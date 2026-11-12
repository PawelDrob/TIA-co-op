$here = Split-Path -Parent $MyInvocation.MyCommand.Path
foreach ($f in 'Mcp.ps1', 'Tia.ps1', 'Repo.ps1', 'Rules.ps1', 'Guards.ps1', 'Bridge.ps1', 'Tools\Objects.ps1', 'Tools\Plc.ps1', 'Tools\Hmi.ps1') { . (Join-Path $here "..\$f") }

# The delete_folder tool: a user folder goes only when every collection it reports is empty. Delete() itself takes a
# folder with everything in it, without a word (probed 2026-11-02), so these tests hold the guard.
# Stand-ins: folders with the engineering interface of the real ones, and Invoke-TiaWrite that runs the body and
# honours -RollbackIf like the real one.

function Get-KindRoot { $script:root }
function Invoke-TiaWrite([string]$Description, [scriptblock]$Body, [switch]$NoTransaction, [scriptblock]$RollbackIf) {
    $script:writes++
    $out = @(& $Body)
    $rb = [bool]($RollbackIf -and (& $RollbackIf))
    $script:committed = -not $rb
    @{ output = $out; transaction = $true; rolledBack = $rb; commitError = $script:commitError; note = $null }
}

# Collections: name -> items. Groups is the subfolder collection of the fake kind.
function New-FakeFolder([string]$Name, [object[]]$Groups = @(), [string[]]$Types = @(), [hashtable]$More = @{}) {
    $c = [ordered]@{ Groups = @($Groups); Types = @($Types | ForEach-Object { [pscustomobject]@{ Name = $_ } }) }
    foreach ($k in $More.Keys) { $c[$k] = @($More[$k] | ForEach-Object { [pscustomobject]@{ Name = $_ } }) }
    $o = [pscustomobject]@{ Name = $Name; Groups = @($Groups); collections = $c; fails = $false }
    $o | Add-Member ScriptMethod GetCompositionInfos { foreach ($n in $this.collections.Keys) { [pscustomobject]@{ Name = $n } } }
    $o | Add-Member ScriptMethod GetComposition { param($n) , $this.collections[$n] }
    $o | Add-Member ScriptMethod Delete {
        $script:deleted += @($this.Name)
        if ($this.fails) { throw [System.InvalidOperationException]::new('TIA said no') }
    }
    $o
}

Register-ObjectKind 'fakeTree' @{
    scope = 'plc'; dir = 'plc\fake'; defaultOverride = $true; description = 'test kind with a folder tree'
    items = { param($r) @() }
    tree = { param($r) $r }; groups = 'Groups'
}
Register-ObjectKind 'fakeFlat' @{
    scope = 'plc'; dir = 'plc\flat'; defaultOverride = $true; description = 'test kind without folders'
    items = { param($r) @() }
}

function Invoke-FakeDeleteFolder([string]$Folder, [string]$Kind = 'fakeTree', [switch]$NoArchive) {
    Initialize-BridgeContext @{ maxResponseChars = 20000 }
    Set-BridgeProject -Name 'P' -Path 'C:\P.ap20' -Repo (Join-Path $TestDrive 'D')
    if (-not $NoArchive) { Register-Archive (Get-BridgeSession) }
    $script:deleted = @(); $script:writes = 0; $script:committed = $null
    Invoke-DeleteFolderTool ([pscustomobject]@{ kind = $Kind; folder = $Folder })
}

function Set-FakeTree {
    $script:commitError = $null
    $script:root = New-FakeFolder 'root' -Groups @(
        (New-FakeFolder 'zzEmpty')
        (New-FakeFolder 'zzStaging' -Groups @((New-FakeFolder 'inner')))
        (New-FakeFolder 'zzHolds' -Types @('A', 'B'))
        (New-FakeFolder 'zzDocument' -More @{ Documents = @('NamedValues') })
        (New-FakeFolder 'zzFails')
    )
    ($script:root.Groups | Where-Object { $_.Name -eq 'zzFails' }).fails = $true
}

Describe 'delete_folder of an empty folder' {
    It 'deletes it, in one write' {
        Set-FakeTree
        $r = Invoke-FakeDeleteFolder 'zzEmpty'
        $r.ok | Should Be $true
        $r.folder | Should Be 'zzEmpty'
        $script:deleted -join ',' | Should Be 'zzEmpty'
        $script:committed | Should Be $true
    }

    It 'finds a folder inside another by its whole path' {
        Set-FakeTree
        $r = Invoke-FakeDeleteFolder 'zzStaging/inner'
        $r.ok | Should Be $true
        $script:deleted -join ',' | Should Be 'inner'
    }

    It 'asks for no compile: the save rules stay as they were (a folder delete changes no consistency, probed)' {
        Set-FakeTree
        $null = Invoke-FakeDeleteFolder 'zzEmpty'
        @((Get-BridgeSession).pending.Keys).Count | Should Be 0
        @(Test-SaveAllowed (Get-BridgeSession)).Count | Should Be 0
    }
}

Describe 'delete_folder of a folder that is not empty' {
    It 'refuses a folder holding objects, names them, and never calls Delete' {
        Set-FakeTree
        $r = Invoke-FakeDeleteFolder 'zzHolds'
        $r.ok | Should Be $false
        $r.refused | Should Match 'not empty'
        (@($r.holds.Types) -join ',') | Should Be 'A,B'
        @($script:deleted).Count | Should Be 0
    }

    It 'refuses a folder holding a subfolder, never recursive' {
        Set-FakeTree
        $r = Invoke-FakeDeleteFolder 'zzStaging'
        $r.ok | Should Be $false
        (@($r.holds.Groups) -join ',') | Should Be 'inner'
        @($script:deleted).Count | Should Be 0
    }

    It 'refuses on a collection the kind does not name: a PLC data type folder also has Documents' {
        Set-FakeTree
        $r = Invoke-FakeDeleteFolder 'zzDocument'
        $r.ok | Should Be $false
        (@($r.holds.Documents) -join ',') | Should Be 'NamedValues'
        @($script:deleted).Count | Should Be 0
    }

    It 'keeps nothing of the write it opened to look under exclusive access' {
        Set-FakeTree
        $null = Invoke-FakeDeleteFolder 'zzHolds'
        $script:committed | Should Be $false
    }

    It 'reads the folder when the write has exclusive access, not before: what a person added meanwhile counts' {
        Set-FakeTree
        $late = $script:root.Groups | Where-Object { $_.Name -eq 'zzEmpty' }
        $script:lateFolder = $late
        function script:Invoke-TiaWrite([string]$Description, [scriptblock]$Body, [switch]$NoTransaction, [scriptblock]$RollbackIf) {
            $script:lateFolder.collections.Types = @([pscustomobject]@{ Name = 'Late' })
            $null = @(& $Body)
            @{ output = @(); transaction = $true; rolledBack = $true; commitError = $null; note = $null }
        }
        try { $r = Invoke-FakeDeleteFolder 'zzEmpty' }
        finally {
            function script:Invoke-TiaWrite([string]$Description, [scriptblock]$Body, [switch]$NoTransaction, [scriptblock]$RollbackIf) {
                $script:writes++
                $out = @(& $Body)
                $rb = [bool]($RollbackIf -and (& $RollbackIf))
                $script:committed = -not $rb
                @{ output = $out; transaction = $true; rolledBack = $rb; commitError = $script:commitError; note = $null }
            }
        }
        $r.ok | Should Be $false
        (@($r.holds.Types) -join ',') | Should Be 'Late'
        @($script:deleted).Count | Should Be 0
    }

    It 'refuses a folder that reports no subfolder collection: it cannot tell what the folder holds' {
        Set-FakeTree
        $odd = [pscustomobject]@{ Name = 'zzOdd'; collections = [ordered]@{ Types = @() } }
        $odd | Add-Member ScriptMethod GetCompositionInfos { foreach ($n in $this.collections.Keys) { [pscustomobject]@{ Name = $n } } }
        $odd | Add-Member ScriptMethod GetComposition { param($n) , $this.collections[$n] }
        $odd | Add-Member ScriptMethod Delete { $script:deleted += @($this.Name) }
        $script:root.Groups = @($script:root.Groups) + @($odd)
        $r = Invoke-FakeDeleteFolder 'zzOdd'
        $r.ok | Should Be $false
        $r.refused | Should Match 'cannot tell'
        @($script:deleted).Count | Should Be 0
    }

    It 'refuses a folder with a collection that comes back null: GetComposition may answer null, and that is not empty' {
        foreach ($missing in 'Types', 'Groups') {
            Set-FakeTree
            $bad = New-FakeFolder 'zzNull'
            $bad | Add-Member NoteProperty missing $missing
            $bad | Add-Member -Force ScriptMethod GetComposition { param($n) if ($n -eq $this.missing) { return $null }; , $this.collections[$n] }
            $script:root.Groups = @($script:root.Groups) + @($bad)
            $r = Invoke-FakeDeleteFolder 'zzNull'
            $r.ok | Should Be $false
            $r.refused | Should Match 'cannot tell'
            $r.refused | Should Match $missing
            @($script:deleted).Count | Should Be 0
        }
    }

    It 'calls no Delete when a collection cannot be read' {
        Set-FakeTree
        $bad = New-FakeFolder 'zzUnreadable'
        $bad | Add-Member -Force ScriptMethod GetComposition { param($n) throw [System.InvalidOperationException]::new('cannot read') }
        $script:root.Groups = @($script:root.Groups) + @($bad)
        { Invoke-FakeDeleteFolder 'zzUnreadable' } | Should Throw 'cannot read'
        @($script:deleted).Count | Should Be 0
    }
}

Describe 'delete_folder path' {
    It 'refuses the root: only user folders can go' {
        Set-FakeTree
        foreach ($p in '', '/') {
            $r = Invoke-FakeDeleteFolder $p
            $r.ok | Should Be $false
            $r.refused | Should Match 'root'
        }
        $script:writes | Should Be 0
    }

    It 'refuses wildcards' {
        Set-FakeTree
        foreach ($p in 'zz*', 'zzEmpt?', 'zzStaging/*') {
            $r = Invoke-FakeDeleteFolder $p
            $r.ok | Should Be $false
            $r.refused | Should Match 'wildcard'
        }
        $script:writes | Should Be 0
    }

    It 'refuses a path with an empty part, as list never prints one' {
        Set-FakeTree
        foreach ($p in '/zzEmpty', 'zzEmpty/', 'zzStaging//inner') {
            $r = Invoke-FakeDeleteFolder $p
            $r.ok | Should Be $false
            $r.refused | Should Match 'exact'
        }
        @($script:deleted).Count | Should Be 0
    }

    It 'refuses a folder that does not exist, with the folders that do at that level' {
        Set-FakeTree
        $r = Invoke-FakeDeleteFolder 'zzStaging/nope'
        $r.ok | Should Be $false
        $r.refused | Should Match "No folder 'zzStaging/nope'"
        $r.refused | Should Match 'inner'
        $script:writes | Should Be 0
    }

    It 'takes the name exactly: TIA''s Find ignores case, this does not (probed)' {
        Set-FakeTree
        $r = Invoke-FakeDeleteFolder 'ZZEMPTY'
        $r.ok | Should Be $false
        $r.refused | Should Match 'No folder'
        @($script:deleted).Count | Should Be 0
    }
}

Describe 'delete_folder kinds' {
    It 'refuses a kind without folders' {
        Set-FakeTree
        $r = Invoke-FakeDeleteFolder 'zzEmpty' -Kind 'fakeFlat'
        $r.ok | Should Be $false
        $r.refused | Should Match 'no folders'
        $script:writes | Should Be 0
    }

    It 'offers the block, data type, tag table, watch table and HMI folder kinds, library kinds not' {
        $names = @(Get-FolderKindNames | Where-Object { $_ -notlike 'fake*' }) -join ','
        $names | Should Be 'block,db,type,plc_tag_table,watch_table,hmi_screen,hmi_template,hmi_popup,hmi_tag_table'
    }
}

Describe 'delete_folder gates' {
    It 'refuses before the session archive' {
        Set-FakeTree
        $r = Invoke-FakeDeleteFolder 'zzEmpty' -NoArchive
        $r.ok | Should Be $false
        $r.refused | Should Match 'archive'
        $script:writes | Should Be 0
    }

    It 'is a write tool for the archive gate of the dispatch, and runs in a background session in write mode only' {
        $script:WriteTools -contains 'delete_folder' | Should Be $true
        $script:BackgroundWriteTools -contains 'delete_folder' | Should Be $true
        $script:BackgroundTools -contains 'delete_folder' | Should Be $false
    }
}

Describe 'delete_folder when TIA refuses' {
    It 'lets the Siemens failure through to the dispatch, which quotes it' {
        Set-FakeTree
        { Invoke-FakeDeleteFolder 'zzFails' } | Should Throw 'TIA said no'
    }

    It 'adds nothing to the save rules: the folder is still there' {
        Set-FakeTree
        try { $null = Invoke-FakeDeleteFolder 'zzFails' } catch { }
        @(Test-SaveAllowed (Get-BridgeSession)).Count | Should Be 0
    }

    It 'says not ok when the commit fails, as TIA kept nothing' {
        Set-FakeTree
        $script:commitError = @{ type = 'X'; message = 'commit refused' }
        $r = Invoke-FakeDeleteFolder 'zzEmpty'
        $r.ok | Should Be $false
        $r.commitError.message | Should Be 'commit refused'
    }
}
