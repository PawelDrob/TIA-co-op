$here = Split-Path -Parent $MyInvocation.MyCommand.Path
foreach ($f in 'Mcp.ps1', 'Tia.ps1', 'Repo.ps1', 'Rules.ps1', 'Guards.ps1', 'Bridge.ps1', 'Tools\Objects.ps1', 'Tools\Plc.ps1', 'Tools\Hmi.ps1',
               'Tools\Library.ps1', 'Tools\FullExport.ps1') { . (Join-Path $here "..\$f") }

# full_export: device folders, the SimaticML fallback, the mirror of the export folders.

if (-not ('Siemens.Engineering.ExportOptions' -as [type])) {
    Add-Type -TypeDefinition 'namespace Siemens.Engineering { [System.Flags] public enum ExportOptions { None = 0, WithDefaults = 1, WithReadOnly = 2 } }'
}

function Test-TiaAlive { $true }
function Get-LibraryLink { $null }

# An object whose Export writes '<name> <options>' (SimaticML), or throws when Fail is set.
function New-XmlObject([string]$Name, [switch]$Fail) {
    $o = [pscustomobject]@{ Name = $Name; IsKnowHowProtected = $false; fail = [bool]$Fail }
    $o | Add-Member ScriptMethod Export { param($f, $opt) if ($this.fail) { throw "Export of $($this.Name) refused" }; [System.IO.File]::WriteAllText($f.FullName, "$($this.Name) $opt") }
    $o
}
# A block whose ExportAsDocuments writes .s7dcl and .s7res, or reports State Failure (an SD export TIA refuses);
# its Export writes SimaticML.
function New-Block([string]$Name, [string]$State = 'Success') {
    $b = New-XmlObject $Name
    $b | Add-Member NoteProperty state $State
    $b | Add-Member ScriptMethod ExportAsDocuments { param($d, $n)
        if ($this.state -eq 'Success') { foreach ($x in '.s7dcl', '.s7res') { Set-Content (Join-Path $d.FullName "$n$x") 'sd' } }
        [pscustomobject]@{ State = $this.state; Messages = @([pscustomobject]@{ State = 'Error'; Description = 'SimaticSdEnabler needed' }) } }
    $b
}
function New-FakeHmi([object[]]$Screens) { [pscustomobject]@{ ScreenFolder = [pscustomobject]@{ Screens = $Screens; Folders = @() } } }
function Write-Old([string]$Repo, [string]$Rel) { $p = Join-Path $Repo $Rel; New-Item -ItemType Directory -Force -Path (Split-Path -Parent $p) | Out-Null; [System.IO.File]::WriteAllText($p, 'old') }
# Commits everything in Repo, a git repo from then on: what the mirror finds there is no longer uncommitted.
function Save-TestRepo([string]$Repo) {
    if (-not (Test-Path (Join-Path $Repo '.git'))) { Invoke-Git $Repo @('init', '-q') }
    Invoke-Git $Repo @('add', '-A')
    Invoke-Git $Repo @('commit', '-q', '--allow-empty', '-m', 'test')
}

Describe 'device folders' {
    It 'puts the device folder after plc\ or hmi\ only when the project has several devices of that kind' {
        Mock Get-TiaSoftwareList { @(@{ device = 'S7/1500'; kind = 'plc' }, @{ device = 'HMI_A'; kind = 'hmi' }, @{ device = 'HMI_B'; kind = 'hmi' }) }
        Get-KindRelDir (Get-ObjectKind 'hmi_screen') 'HMI_A' | Should Be 'hmi\HMI_A\screens'
        Get-KindRelDir (Get-ObjectKind 'hmi_tag_table') 'HMI_B' | Should Be 'hmi\HMI_B\tags'
        Get-KindRelDir (Get-ObjectKind 'block') 'S7/1500' | Should Be 'plc\blocks'
        Get-KindRelDir (Get-ObjectKind 'library_type') 'HMI_A' | Should Be 'library\types'
        Get-KindRelDir (Get-ObjectKind 'hmi_screen') '' | Should Be 'hmi\screens'
        Mock Get-TiaSoftwareList { @(@{ device = 'S7/1500'; kind = 'plc' }, @{ device = 'S7/1200'; kind = 'plc' }) }
        Get-KindRelDir (Get-ObjectKind 'block') 'S7/1500' | Should Be 'plc\S7_1500\blocks'
    }

    It 'export with device writes into the device folder' {
        $repo = Join-Path $TestDrive 'dev'
        Initialize-BridgeContext @{ maxResponseChars = 20000 }
        Set-BridgeProject -Name 'P' -Path 'C:\P.ap20' -Repo $repo
        Mock Get-TiaSoftwareList { @(@{ device = 'HMI_A'; kind = 'hmi' }, @{ device = 'HMI_B'; kind = 'hmi' }) }
        Mock Get-KindRoot { New-FakeHmi @(New-XmlObject 'S1') }
        $r = Invoke-ExportTool ([pscustomobject]@{ kind = 'hmi_screen'; names = @('S1'); device = 'HMI_B' })
        $r.ok | Should Be $true
        $r.items[0].files | Should Be 'hmi\HMI_B\screens\S1.xml'
    }
}

Describe 'Get-MirrorRemovals' {
    It 'removes only files neither written nor of a failed object, and keeps .gitkeep, .released and .partial' {
        $d = Join-Path $TestDrive 'mirror'
        foreach ($f in 'A.s7dcl', 'Gone.s7dcl', 'F\Bad.xml', 'F\Bad.s7res', 'Lib\T\T.libinfo', 'Lib\T.released\T.s7dcl', 'X.xml.partial', '.gitkeep', 'Sub\Stale.xml') { Write-Old $d $f }
        $out = @(Get-MirrorRemovals $d @((Join-Path $d 'A.s7dcl')) @((Join-Path $d 'F\Bad'), (Join-Path $d 'Lib\T')) | ForEach-Object { $_.Substring($d.Length + 1) } | Sort-Object)
        ($out -join '|') | Should Be 'Gone.s7dcl|Sub\Stale.xml'
        $m = Remove-MirrorFiles $d @(Get-MirrorRemovals $d @((Join-Path $d 'A.s7dcl')) @((Join-Path $d 'F\Bad'), (Join-Path $d 'Lib\T')))
        $m.removed.Count | Should Be 2
        Test-Path (Join-Path $d 'Sub') | Should Be $false
        Test-Path (Join-Path $d 'F\Bad.xml') | Should Be $true
    }
}

Describe 'Export-ObjectFolder' {
    It 'keeps the image folder a graphic export writes beside its .xml and returns its files for the mirror' {
        $g = [pscustomobject]@{ Name = 'Logo' }
        $g | Add-Member ScriptMethod Export { param($f, $opt)
            $files = Join-Path $f.DirectoryName 'Logo files'
            New-Item -ItemType Directory -Force -Path $files | Out-Null
            [System.IO.File]::WriteAllText((Join-Path $files 'DefaultImageStream.png'), 'png')
            [System.IO.File]::WriteAllText($f.FullName, '<DefaultImageStream external="path">Logo files\DefaultImageStream.png</DefaultImageStream>') }
        $d = Join-Path $TestDrive 'graphics'
        New-Item -ItemType Directory -Force -Path $d | Out-Null
        Write-Old $d 'Logo files\Old.png'

        $files = @(Export-ObjectFolder $g $d 'Logo' ([Siemens.Engineering.ExportOptions]::WithDefaults))

        (@($files | ForEach-Object { $_.Substring($d.Length + 1) } | Sort-Object) -join '|') | Should Be 'Logo files\DefaultImageStream.png|Logo.xml'
        Test-Path (Join-Path $d 'Logo files\Old.png') | Should Be $false
        Test-Path (Join-Path $d 'Logo.partial') | Should Be $false
        @(Get-MirrorRemovals $d $files @()).Count | Should Be 0
    }
}

Describe 'full_export' {
    $repo = Join-Path $TestDrive 'repo'
    Initialize-BridgeContext @{ maxResponseChars = 20000 }
    Set-BridgeProject -Name 'P' -Path 'C:\P.ap20' -Repo $repo
    $plc = [pscustomobject]@{ BlockGroup = [pscustomobject]@{ Blocks = @((New-Block 'A'), (New-Block 'B' 'Failure'), (New-Block 'DB1')); Groups = @() }
                              ExternalSourceGroup = [pscustomobject]@{ ExternalSources = @([pscustomobject]@{ Name = 'Src' }); Groups = @() } }
    $hmiA = New-FakeHmi @(New-XmlObject 'S1')
    $hmiB = New-FakeHmi @((New-XmlObject 'S2'), (New-XmlObject 'Bad' -Fail))
    Mock Get-TiaSoftwareList { @(@{ device = 'PLC_1'; kind = 'plc'; software = $plc }, @{ device = 'HMI_A'; kind = 'hmi'; software = $hmiA }, @{ device = 'HMI_B'; kind = 'hmi'; software = $hmiB }) }
    Mock Get-TiaProject { [pscustomobject]@{ Name = 'P'; ProjectLibrary = $null } }
    Mock Test-IsDataBlock { $Block.Name -like 'DB*' }

    It 'exports every device into its folder, falls back to SimaticML, mirrors the folders and keeps what it must not touch' {
        foreach ($f in 'plc\blocks\Old.s7dcl', 'plc\blocks\B.s7dcl', 'hmi\HMI_A\screens\Gone.xml', 'hmi\HMI_B\screens\Bad.xml', 'hmi\generated\screens\G.xml', 'hmi\handbuilt.json', 'gen\g.py') { Write-Old $repo $f }
        Save-TestRepo $repo
        $r = Invoke-FullExportTool ([pscustomobject]@{ parts = @('blocks', 'dbs', 'hmi_screens', 'external_sources') })
        $r.ok | Should Be $false
        $r.exported | Should Be 5
        $r.failedCount | Should Be 1
        $r.failed[0] | Should Match '^hmi_screens@HMI_B: Bad: .*Export of Bad refused'
        Get-Content (Join-Path $repo 'plc\blocks\A.s7dcl') | Should Be 'sd'
        Get-Content (Join-Path $repo 'plc\blocks\B.xml') | Should Be 'B WithDefaults'
        Get-Content (Join-Path $repo 'hmi\HMI_A\screens\S1.xml') | Should Be 'S1 WithDefaults, WithReadOnly'
        Get-Content (Join-Path $repo 'hmi\HMI_B\screens\S2.xml') | Should Be 'S2 WithDefaults, WithReadOnly'
        $r.details | Where-Object { $_.part -eq 'blocks' } | ForEach-Object { $_.fellBack[0].note } | Should Match 'SimaticSdEnabler'
        (@($r.removed) | Sort-Object) -join '|' | Should Be 'hmi\HMI_A\screens\Gone.xml|plc\blocks\B.s7dcl|plc\blocks\Old.s7dcl'
        # the failed screen keeps its last export; generated documents and the rest are not export folders
        foreach ($f in 'hmi\HMI_B\screens\Bad.xml', 'hmi\generated\screens\G.xml', 'hmi\handbuilt.json', 'gen\g.py') { Test-Path (Join-Path $repo $f) | Should Be $true }
        ($r.parts -join '|') | Should Match 'blocks@PLC_1: 2/2, [\d.]+ s, 1 as SimaticML'
        ($r.parts -join '|') | Should Match 'hmi_screens@HMI_B: 1/2, [\d.]+ s, 1 failed'
        $r.leftOut | Should Match '^1 external source files'
    }

    It 'does not mirror a folder when a part writing it did not run' {
        Write-Old $repo 'plc\blocks\Old2.s7dcl'
        $r = Invoke-FullExportTool ([pscustomobject]@{ parts = @('blocks') })
        (@($r.removed) -join "|") | Should Be ""
        Test-Path (Join-Path $repo 'plc\blocks\Old2.s7dcl') | Should Be $true
        Test-Path (Join-Path $repo 'plc\blocks\DB1.s7dcl') | Should Be $true
    }

    It 'refuses an unknown part' {
        (Invoke-FullExportTool ([pscustomobject]@{ parts = @('nope') })).refused | Should Match 'Unknown part'
    }

    It 'has no hardware part any more (removed 2026-10-30)' {
        (Invoke-FullExportTool ([pscustomobject]@{ parts = @('hardware') })).refused | Should Match 'Unknown part\(s\): hardware\.'
    }

    It 'says each part before and after it, and each object with n of m' {
        $script:logLines = New-Object System.Collections.ArrayList
        function Write-BridgeLog([string]$Text) { [void]$script:logLines.Add($Text) }
        $null = Invoke-FullExportTool ([pscustomobject]@{ parts = @('blocks', 'hmi_screens') })
        $lines = @($script:logLines | Where-Object { $_ -like 'progress {*' } | ForEach-Object {
            $p = $_.Substring(9) | ConvertFrom-Json
            if ($p.event -eq 'part') { "part $($p.part)@$($p.device) $($p.state)$(if ($p.state -ne 'start') { " $($p.exported)/$($p.count) failed $($p.failed)" })" }
            else { "$($p.event) $($p.part)@$($p.device) $($p.kind) $($p.n)/$($p.of) $($p.name) $($p.ok)" }
        })
        $lines -join '|' | Should Be ('part blocks@PLC_1 start|object blocks@PLC_1 block 1/2 A True|object blocks@PLC_1 block 2/2 B True|part blocks@PLC_1 done 2/2 failed 0|' +
            'part hmi_screens@HMI_A start|object hmi_screens@HMI_A hmi_screen 1/1 S1 True|part hmi_screens@HMI_A done 1/1 failed 0|' +
            'part hmi_screens@HMI_B start|object hmi_screens@HMI_B hmi_screen 1/2 S2 True|object hmi_screens@HMI_B hmi_screen 2/2 Bad False|part hmi_screens@HMI_B done 1/2 failed 1')
    }

    It 'export says each object with n of m, every match once' {
        $script:logLines = New-Object System.Collections.ArrayList
        function Write-BridgeLog([string]$Text) { [void]$script:logLines.Add($Text) }
        $r = Invoke-ExportTool ([pscustomobject]@{ kind = 'hmi_screen'; names = @('S*', 'Bad', 'S2', 'Nope'); device = 'HMI_B' })
        @($r.items).Count | Should Be 3
        $lines = @($script:logLines | Where-Object { $_ -like 'progress {*' } | ForEach-Object { $p = $_.Substring(9) | ConvertFrom-Json; "$($p.kind) $($p.device) $($p.n)/$($p.of) $($p.name) $($p.ok)" })
        $lines -join '|' | Should Be 'hmi_screen HMI_B 1/2 S2 True|hmi_screen HMI_B 2/2 Bad False'
    }
}

Describe 'file parts' {
    $repo = Join-Path $TestDrive 'files'
    Initialize-BridgeContext @{ maxResponseChars = 20000 }
    Set-BridgeProject -Name 'P' -Path 'C:\P.ap20' -Repo $repo
    function New-Rec($Part) { New-PartRecord $Part '' }

    It 'replaces the folder after a good export and lists the old files it no longer holds' {
        Write-Old $repo 'project\texts\project-texts_en-US_de-DE.xlsx'
        Save-TestRepo $repo
        $part = @{ name = 't'; scope = 'project'; dir = 'project\texts'; file = { param($r, $d) [System.IO.File]::WriteAllText((Join-Path $d 'project-texts_en-US_es-ES.xlsx'), 'new'); @{ notes = @('n') } } }
        $rec = New-Rec $part
        Invoke-FullExportFilePart $part $null '' $rec
        $rec.exported | Should Be 1
        @($rec.removed) | Should Be 'project\texts\project-texts_en-US_de-DE.xlsx'
        @(Get-ChildItem (Join-Path $repo 'project\texts')).Name | Should Be 'project-texts_en-US_es-ES.xlsx'
        Test-Path (Join-Path $repo 'project\texts.partial') | Should Be $false
    }

    It 'keeps the old folder when the export fails' {
        $part = @{ name = 't'; scope = 'project'; dir = 'project\texts'; file = { param($r, $d) [System.IO.File]::WriteAllText((Join-Path $d 'half.xlsx'), 'x'); throw 'TIA said no' } }
        $rec = New-Rec $part
        Invoke-FullExportFilePart $part $null '' $rec
        $rec.failed[0].error.message | Should Be 'TIA said no'
        @(Get-ChildItem (Join-Path $repo 'project\texts')).Name | Should Be 'project-texts_en-US_es-ES.xlsx'
    }

    It 'removes the folder when there is nothing to export' {
        Save-TestRepo $repo
        $part = @{ name = 't'; scope = 'project'; dir = 'project\texts'; file = { param($r, $d) @{ none = $true } } }
        $rec = New-Rec $part
        Invoke-FullExportFilePart $part $null '' $rec
        $rec.none | Should Be $true
        Test-Path (Join-Path $repo 'project\texts') | Should Be $false
        @($rec.removed) | Should Be 'project\texts\project-texts_en-US_es-ES.xlsx'
    }
}

Describe 'uncommitted files and the mirror' {
    $script:n = 0
    # A new temp repo with its bridge session; the PLC holds block A.
    function New-TestProject {
        $script:n++
        $r = Join-Path $TestDrive "unc$($script:n)"
        Initialize-BridgeContext @{ maxResponseChars = 20000 }
        Set-BridgeProject -Name 'P' -Path 'C:\P.ap20' -Repo $r
        $r
    }
    $plc = [pscustomobject]@{ BlockGroup = [pscustomobject]@{ Blocks = @(New-Block 'A'); Groups = @() } }
    Mock Get-TiaSoftwareList { @(@{ device = 'PLC_1'; kind = 'plc'; software = $plc }) }
    Mock Get-TiaProject { [pscustomobject]@{ Name = 'P'; ProjectLibrary = $null } }
    Mock Test-IsDataBlock { $false }
    $blocks = [pscustomobject]@{ parts = @('blocks', 'dbs') }

    It 'keeps and lists an untracked new block and removes a committed stale file' {
        $repo = New-TestProject
        Write-Old $repo 'plc\blocks\Stale.s7dcl'
        Save-TestRepo $repo
        Write-Old $repo 'plc\blocks\New.s7dcl'
        $r = Invoke-FullExportTool $blocks
        $r.ok | Should Be $true
        @($r.keptUncommitted) | Should Be 'plc\blocks\New.s7dcl'
        $r.keptCount | Should Be 1
        @($r.removed) | Should Be 'plc\blocks\Stale.s7dcl'
        Test-Path (Join-Path $repo 'plc\blocks\New.s7dcl') | Should Be $true
        Test-Path (Join-Path $repo 'plc\blocks\Stale.s7dcl') | Should Be $false
        $r.next | Should Match 'keptUncommitted'
    }

    It 'keeps a stale file with uncommitted edits, staged or not, and a new file only staged' {
        $repo = New-TestProject
        foreach ($f in 'Edited.s7dcl', 'Staged.s7dcl') { Write-Old $repo "plc\blocks\$f" }
        Save-TestRepo $repo
        foreach ($f in 'Edited.s7dcl', 'Staged.s7dcl', 'Added.s7dcl') { [System.IO.File]::WriteAllText((Join-Path $repo "plc\blocks\$f"), 'edit') }
        Invoke-Git $repo @('add', 'plc/blocks/Staged.s7dcl', 'plc/blocks/Added.s7dcl')
        $r = Invoke-FullExportTool $blocks
        (@($r.keptUncommitted) | Sort-Object) -join '|' | Should Be 'plc\blocks\Added.s7dcl|plc\blocks\Edited.s7dcl|plc\blocks\Staged.s7dcl'
        @($r.removed).Count | Should Be 0
        Get-Content (Join-Path $repo 'plc\blocks\Edited.s7dcl') | Should Be 'edit'
    }

    It 'keeps a file whose name has spaces and non-ASCII letters' {
        $repo = New-TestProject
        Write-Old $repo 'tiabridge.json'
        Save-TestRepo $repo
        $name ="Gr$([char]0xFC)n $([char]0x0142)a.s7dcl"
        Write-Old $repo "plc\blocks\$name"
        $r = Invoke-FullExportTool $blocks
        @($r.keptUncommitted) | Should Be "plc\blocks\$name"
        Test-Path -LiteralPath (Join-Path $repo "plc\blocks\$name") | Should Be $true
    }

    It 'keeps a file git ignores: it was never committed either' {
        $repo = New-TestProject
        Write-Old $repo '.gitignore'
        [System.IO.File]::WriteAllText((Join-Path $repo '.gitignore'), "*.bak`n")
        Save-TestRepo $repo
        Write-Old $repo 'plc\blocks\Note.bak'
        $r = Invoke-FullExportTool $blocks
        @($r.keptUncommitted) | Should Be 'plc\blocks\Note.bak'
    }

    It 'still replaces the uncommitted edit of an object it exports, as export does' {
        $repo = New-TestProject
        Write-Old $repo 'plc\blocks\A.s7dcl'
        Save-TestRepo $repo
        [System.IO.File]::WriteAllText((Join-Path $repo 'plc\blocks\A.s7dcl'), 'edit')
        $r = Invoke-FullExportTool $blocks
        Get-Content (Join-Path $repo 'plc\blocks\A.s7dcl') | Should Be 'sd'
        @($r.keptUncommitted).Count | Should Be 0
        $r.keptCount | Should Be 0
    }

    It 'removes nothing and says so when the repo has no git' {
        $repo = New-TestProject
        Write-Old $repo 'plc\blocks\Stale.s7dcl'
        $r = Invoke-FullExportTool $blocks
        $r.ok | Should Be $false
        $r.gitError | Should Match 'git'
        @($r.removed).Count | Should Be 0
        @($r.keptUncommitted) | Should Be 'plc\blocks\Stale.s7dcl'
        Test-Path (Join-Path $repo 'plc\blocks\Stale.s7dcl') | Should Be $true
    }

    It 'removes nothing and says so when git status fails' {
        $repo = New-TestProject
        Write-Old $repo 'plc\blocks\Stale.s7dcl'
        [System.IO.File]::WriteAllText((Join-Path $repo '.git'), 'gitdir: C:\nowhere')
        $r = Invoke-FullExportTool $blocks
        $r.ok | Should Be $false
        # git's own words differ by version: 2.56 says "gitfile does not point to a valid repository"
        $r.gitError | Should Match 'git status exited with \d+: .*(not a git repository|does not point to a valid repository)'
        Test-Path (Join-Path $repo 'plc\blocks\Stale.s7dcl') | Should Be $true
    }

    It 'mirrors a plain export folder without git, as before' {
        $repo = New-TestProject
        Write-Old $repo 'plc\blocks\Stale.s7dcl'
        $script:Bridge.background = @{ plain = $true }
        try { $r = Invoke-FullExportTool $blocks } finally { $script:Bridge.background = $null }
        $r.ok | Should Be $true
        @($r.removed) | Should Be 'plc\blocks\Stale.s7dcl'
        @($r.keptUncommitted).Count | Should Be 0
        $r.Contains('gitError') | Should Be $false
    }

    $write = @{ name = 't'; scope = 'project'; dir = 'project\texts'; file = { param($r, $d) [System.IO.File]::WriteAllText((Join-Path $d 'new.xlsx'), 'new'); @{} } }
    $empty = @{ name = 't'; scope = 'project'; dir = 'project\texts'; file = { param($r, $d) @{ none = $true } } }

    It 'a file part keeps an untracked file, in a subfolder too, through the replacement of its folder' {
        $repo = New-TestProject
        Write-Old $repo 'project\texts\committed.xlsx'
        Save-TestRepo $repo
        Write-Old $repo 'project\texts\sub\mine.txt'
        $rec = New-PartRecord $write ''
        Invoke-FullExportFilePart $write $null '' $rec
        @($rec.keptUncommitted) | Should Be 'project\texts\sub\mine.txt'
        @($rec.removed) | Should Be 'project\texts\committed.xlsx'
        Get-Content (Join-Path $repo 'project\texts\sub\mine.txt') | Should Be 'old'
        Test-Path (Join-Path $repo 'project\texts\new.xlsx') | Should Be $true
        Test-Path (Join-Path $repo 'project\texts\committed.xlsx') | Should Be $false
    }

    It 'a file part with nothing to export keeps only the uncommitted files' {
        $repo = New-TestProject
        Write-Old $repo 'project\texts\committed.xlsx'
        Save-TestRepo $repo
        Write-Old $repo 'project\texts\mine.txt'
        $rec = New-PartRecord $empty ''
        Invoke-FullExportFilePart $empty $null '' $rec
        $rec.none | Should Be $true
        @($rec.keptUncommitted) | Should Be 'project\texts\mine.txt'
        @($rec.removed) | Should Be 'project\texts\committed.xlsx'
        (@(Get-ChildItem (Join-Path $repo 'project\texts')).Name) | Should Be 'mine.txt'
    }

    It 'a file part removes nothing of the old folder when git status fails' {
        $repo = New-TestProject
        Write-Old $repo 'project\texts\old.xlsx'
        $rec = New-PartRecord $write ''
        Invoke-FullExportFilePart $write $null '' $rec
        $rec.gitError | Should Match 'git'
        @($rec.keptUncommitted) | Should Be 'project\texts\old.xlsx'
        @($rec.removed).Count | Should Be 0
        Test-Path (Join-Path $repo 'project\texts\old.xlsx') | Should Be $true
    }

    It 'the result of a run holds what a file part kept and its git error' {
        $repo = New-TestProject
        Write-Old $repo 'project\texts\project-texts_old.xlsx'
        Mock Export-ProjectTexts { [System.IO.File]::WriteAllText((Join-Path $Dir 'new.xlsx'), 'new'); @{} }
        $r = Invoke-FullExportTool ([pscustomobject]@{ parts = @('project_texts') })
        @($r.keptUncommitted) | Should Be 'project\texts\project-texts_old.xlsx'
        $r.ok | Should Be $false
        $r.gitError | Should Match 'git'
    }
}

# A repo inside the folders the mirror works on: git status of the outer repo names only its folder.
Describe 'a git repo inside an export folder' {
    $script:n = 0
    function New-TestProject {
        $script:n++
        $r = Join-Path $TestDrive "nested$($script:n)"
        Initialize-BridgeContext @{ maxResponseChars = 20000 }
        Set-BridgeProject -Name 'P' -Path 'C:\P.ap20' -Repo $r
        $r
    }
    # A repo with one commit and an edit it has not committed. Returns its folder.
    function New-NestedRepo([string]$Repo, [string]$Rel) {
        $d = Join-Path $Repo $Rel
        Write-Old $d 'history.txt'
        Save-TestRepo $d
        Write-Old $d 'work.txt'
        $d
    }
    function Get-Head([string]$Dir) { (Invoke-GitRaw $Dir @('rev-parse', 'HEAD')).output -join '' }
    # A bare repo with one commit, its refs packed: its refs folders are then empty, and git needs them. Returns its folder.
    function New-BareRepo([string]$Repo, [string]$Rel) {
        $d = Join-Path $Repo $Rel
        New-Item -ItemType Directory -Force -Path $d | Out-Null
        Invoke-Git $d @('init', '-q', '--bare')
        $from = New-NestedRepo $TestDrive "barefrom$([guid]::NewGuid().ToString('N'))"
        Invoke-Git $d @('fetch', '-q', $from, 'HEAD:refs/heads/b')
        Invoke-Git $d @('symbolic-ref', 'HEAD', 'refs/heads/b')
        Invoke-Git $d @('pack-refs', '--all')
        $d
    }
    function Assert-BareWhole([string]$Dir, [string]$Head) {
        Test-Path (Join-Path $Dir 'refs') | Should Be $true
        Get-Head $Dir | Should Be $Head
    }
    # A fresh repo's refs\tags is an empty folder, and git refuses a repo without refs.
    function Assert-RepoWhole([string]$Dir, [string]$Head) {
        Get-Head $Dir | Should Be $Head
        (Invoke-GitRaw $Dir @('rev-parse', '--show-toplevel')).exitCode | Should Be 0
        Test-Path (Join-Path $Dir 'history.txt') | Should Be $true
        Test-Path (Join-Path $Dir 'work.txt') | Should Be $true
        Test-Path (Join-Path $Dir '.git\refs\tags') | Should Be $true
    }
    $plc = [pscustomobject]@{ BlockGroup = [pscustomobject]@{ Blocks = @(New-Block 'A'); Groups = @() } }
    Mock Get-TiaSoftwareList { @(@{ device = 'PLC_1'; kind = 'plc'; software = $plc }) }
    Mock Get-TiaProject { [pscustomobject]@{ Name = 'P'; ProjectLibrary = $null } }
    Mock Test-IsDataBlock { $false }
    $blocks = [pscustomobject]@{ parts = @('blocks', 'dbs') }

    It 'a kind part leaves it whole, lists it once, and still removes a stale file beside it' {
        $repo = New-TestProject
        Write-Old $repo 'plc\blocks\Stale.s7dcl'
        Save-TestRepo $repo
        $d = New-NestedRepo $repo 'plc\blocks\sub'
        $head = Get-Head $d
        $r = Invoke-FullExportTool $blocks
        Assert-RepoWhole $d $head
        $r.ok | Should Be $true
        @($r.keptRepos) | Should Be 'plc\blocks\sub'
        @($r.removed) | Should Be 'plc\blocks\Stale.s7dcl'
        @($r.keptUncommitted).Count | Should Be 0
        $r.next | Should Match 'keptRepos'
    }

    $write = @{ name = 't'; scope = 'project'; dir = 'project\texts'; file = { param($r, $d) [System.IO.File]::WriteAllText((Join-Path $d 'new.xlsx'), 'new'); @{} } }
    $empty = @{ name = 't'; scope = 'project'; dir = 'project\texts'; file = { param($r, $d) @{ none = $true } } }

    It 'a file part with new files leaves it whole, writes around it and lists it' {
        $repo = New-TestProject
        Write-Old $repo 'project\texts\stale.xlsx'
        Save-TestRepo $repo
        $d = New-NestedRepo $repo 'project\texts\sub'
        $head = Get-Head $d
        $rec = New-PartRecord $write ''
        Invoke-FullExportFilePart $write $null '' $rec
        Assert-RepoWhole $d $head
        @($rec.keptRepos) | Should Be 'project\texts\sub'
        @($rec.removed) | Should Be 'project\texts\stale.xlsx'
        @($rec.keptUncommitted).Count | Should Be 0
        $rec.exported | Should Be 1
        Test-Path (Join-Path $repo 'project\texts\new.xlsx') | Should Be $true
        Test-Path (Join-Path $repo 'project\texts\stale.xlsx') | Should Be $false
        Test-Path (Join-Path $repo 'project\texts.partial') | Should Be $false
    }

    It 'a file part with nothing to export leaves it whole and lists it' {
        $repo = New-TestProject
        Write-Old $repo 'project\texts\stale.xlsx'
        Save-TestRepo $repo
        $d = New-NestedRepo $repo 'project\texts\sub'
        $head = Get-Head $d
        $rec = New-PartRecord $empty ''
        Invoke-FullExportFilePart $empty $null '' $rec
        Assert-RepoWhole $d $head
        $rec.none | Should Be $true
        @($rec.keptRepos) | Should Be 'project\texts\sub'
        @($rec.removed) | Should Be 'project\texts\stale.xlsx'
        Test-Path (Join-Path $repo 'project\texts\stale.xlsx') | Should Be $false
    }

    It 'the result of a run holds the repo a file part kept' {
        $repo = New-TestProject
        Write-Old $repo 'README.txt'
        Save-TestRepo $repo
        $null = New-NestedRepo $repo 'project\texts\sub'
        Mock Export-ProjectTexts { [System.IO.File]::WriteAllText((Join-Path $Dir 'new.xlsx'), 'new'); @{} }
        $r = Invoke-FullExportTool ([pscustomobject]@{ parts = @('project_texts') })
        $r.ok | Should Be $true
        @($r.keptRepos) | Should Be 'project\texts\sub'
    }

    It 'a worktree inside the folder, its .git a file, is left whole too' {
        $repo = New-TestProject
        Write-Old $repo 'plc\blocks\Stale.s7dcl'
        Save-TestRepo $repo
        $main = New-NestedRepo $TestDrive 'wtmain'
        $wt = Join-Path $repo 'plc\blocks\wt'
        Invoke-Git $main @('worktree', 'add', '-q', $wt)
        Write-Old $wt 'work.txt'
        $r = Invoke-FullExportTool $blocks
        @($r.keptRepos) | Should Be 'plc\blocks\wt'
        @($r.removed) | Should Be 'plc\blocks\Stale.s7dcl'
        Get-Head $wt | Should Be (Get-Head $main)
        Test-Path (Join-Path $wt 'history.txt') | Should Be $true
        Test-Path (Join-Path $wt 'work.txt') | Should Be $true
    }

    It 'a repo the outer repo holds as a submodule pointer is left whole too' {
        $repo = New-TestProject
        Write-Old $repo 'plc\blocks\Stale.s7dcl'
        $d = New-NestedRepo $repo 'plc\blocks\sub'
        $head = Get-Head $d
        Save-TestRepo $repo
        $r = Invoke-FullExportTool $blocks
        Assert-RepoWhole $d $head
        @($r.keptRepos) | Should Be 'plc\blocks\sub'
    }

    It 'an export folder inside a repo removes nothing of it and still writes the new files' {
        $repo = New-TestProject
        Write-Old $repo 'README.txt'
        Save-TestRepo $repo
        $d = New-NestedRepo $repo 'project'
        Write-Old $d 'texts\stale.xlsx'
        Save-TestRepo $d
        Write-Old $d 'work.txt'
        $head = Get-Head $d
        $rec = New-PartRecord $write ''
        Invoke-FullExportFilePart $write $null '' $rec
        Assert-RepoWhole $d $head
        @($rec.keptRepos) | Should Be 'project'
        @($rec.removed).Count | Should Be 0
        Test-Path (Join-Path $d 'texts\stale.xlsx') | Should Be $true
        Test-Path (Join-Path $d 'texts\new.xlsx') | Should Be $true
    }

    It 'a plain export folder without git leaves it whole too' {
        $repo = New-TestProject
        Write-Old $repo 'plc\blocks\Stale.s7dcl'
        $d = New-NestedRepo $repo 'plc\blocks\sub'
        $head = Get-Head $d
        $script:Bridge.background = @{ plain = $true }
        try { $r = Invoke-FullExportTool $blocks } finally { $script:Bridge.background = $null }
        Assert-RepoWhole $d $head
        @($r.keptRepos) | Should Be 'plc\blocks\sub'
        @($r.removed) | Should Be 'plc\blocks\Stale.s7dcl'
    }

    It 'a file part whose export fails lists it too' {
        $repo = New-TestProject
        Write-Old $repo 'README.txt'
        Save-TestRepo $repo
        $d = New-NestedRepo $repo 'project\texts\sub'
        $head = Get-Head $d
        $fails = @{ name = 't'; scope = 'project'; dir = 'project\texts'; file = { param($r, $to) throw 'TIA said no' } }
        $rec = New-PartRecord $fails ''
        Invoke-FullExportFilePart $fails $null '' $rec
        Assert-RepoWhole $d $head
        @($rec.keptRepos) | Should Be 'project\texts\sub'
    }

    It 'the export of a graphic refuses to replace its image folder holding one' {
        $repo = New-TestProject
        $d = New-NestedRepo $repo 'project\graphics\Logo files\sub'
        $head = Get-Head $d
        $g = [pscustomobject]@{ Name = 'Logo' }
        $g | Add-Member ScriptMethod Export { param($f, $opt)
            $files = Join-Path $f.DirectoryName 'Logo files'
            New-Item -ItemType Directory -Force -Path $files | Out-Null
            [System.IO.File]::WriteAllText((Join-Path $files 'Image.png'), 'png')
            [System.IO.File]::WriteAllText($f.FullName, 'xml') }
        { Export-ObjectFolder $g (Join-Path $repo 'project\graphics') 'Logo' ([Siemens.Engineering.ExportOptions]::WithDefaults) } | Should Throw 'git repo'
        Assert-RepoWhole $d $head
    }

    It 'a repo made during the export of a file part with nothing to export is left whole and listed' {
        foreach ($beside in $false, $true) {
            $repo = New-TestProject
            Write-Old $repo 'project\texts\stale.xlsx'
            Save-TestRepo $repo
            if ($beside) { Write-Old $repo 'project\texts\mine.txt' }
            $late = @{ name = 't'; scope = 'project'; dir = 'project\texts'; file = { param($r, $to)
                $script:lateRepo = New-NestedRepo ($to -replace '\.partial$', '') 'sub'
                @{ none = $true } } }
            $rec = New-PartRecord $late ''
            Invoke-FullExportFilePart $late $null '' $rec
            Test-Path (Join-Path $script:lateRepo '.git\HEAD') | Should Be $true
            Test-Path (Join-Path $script:lateRepo 'history.txt') | Should Be $true
            Test-Path (Join-Path $script:lateRepo 'work.txt') | Should Be $true
            @($rec.keptRepos) | Should Be 'project\texts\sub'
            @($rec.removed) | Should Be 'project\texts\stale.xlsx'
        }
    }

    It 'a repo made during the export of a file part with new files is left whole and listed' {
        $repo = New-TestProject
        Write-Old $repo 'project\texts\stale.xlsx'
        Save-TestRepo $repo
        $late = @{ name = 't'; scope = 'project'; dir = 'project\texts'; file = { param($r, $to)
            $script:lateRepo = New-NestedRepo ($to -replace '\.partial$', '') 'sub'
            [System.IO.File]::WriteAllText((Join-Path $to 'new.xlsx'), 'new')
            @{} } }
        $rec = New-PartRecord $late ''
        Invoke-FullExportFilePart $late $null '' $rec
        Test-Path (Join-Path $script:lateRepo '.git\HEAD') | Should Be $true
        @($rec.keptRepos) | Should Be 'project\texts\sub'
        $rec.exported | Should Be 1
        Test-Path (Join-Path $repo 'project\texts\new.xlsx') | Should Be $true
    }

    It 'a bare repo in a plain export folder is left whole and listed' {
        $repo = New-TestProject
        Write-Old $repo 'plc\blocks\Stale.s7dcl'
        $d = New-BareRepo $repo 'plc\blocks\x.git'
        $head = Get-Head $d
        $script:Bridge.background = @{ plain = $true }
        try { $r = Invoke-FullExportTool $blocks } finally { $script:Bridge.background = $null }
        Assert-BareWhole $d $head
        @($r.keptRepos) | Should Be 'plc\blocks\x.git'
        @($r.removed) | Should Be 'plc\blocks\Stale.s7dcl'
    }

    It 'a bare repo in the export folder of a project repo is left whole and listed, by a kind part' {
        $repo = New-TestProject
        Write-Old $repo 'plc\blocks\Stale.s7dcl'
        Save-TestRepo $repo
        $d = New-BareRepo $repo 'plc\blocks\x.git'
        $head = Get-Head $d
        $r = Invoke-FullExportTool $blocks
        Assert-BareWhole $d $head
        @($r.keptRepos) | Should Be 'plc\blocks\x.git'
        @($r.keptUncommitted).Count | Should Be 0
    }

    It 'a bare repo in the folder of a file part is left whole and listed, with new files and with none' {
        foreach ($part in $write, $empty) {
            $repo = New-TestProject
            Write-Old $repo 'project\texts\stale.xlsx'
            Save-TestRepo $repo
            $d = New-BareRepo $repo 'project\texts\x.git'
            $head = Get-Head $d
            $rec = New-PartRecord $part ''
            Invoke-FullExportFilePart $part $null '' $rec
            Assert-BareWhole $d $head
            @($rec.keptRepos) | Should Be 'project\texts\x.git'
            @($rec.removed) | Should Be 'project\texts\stale.xlsx'
            @($rec.keptUncommitted).Count | Should Be 0
        }
    }

    It 'the export of a graphic refuses to replace its image folder holding a bare repo' {
        $repo = New-TestProject
        $d = New-BareRepo $repo 'project\graphics\Logo files\x.git'
        $head = Get-Head $d
        $g = [pscustomobject]@{ Name = 'Logo' }
        $g | Add-Member ScriptMethod Export { param($f, $opt)
            $files = Join-Path $f.DirectoryName 'Logo files'
            New-Item -ItemType Directory -Force -Path $files | Out-Null
            [System.IO.File]::WriteAllText((Join-Path $files 'Image.png'), 'png')
            [System.IO.File]::WriteAllText($f.FullName, 'xml') }
        { Export-ObjectFolder $g (Join-Path $repo 'project\graphics') 'Logo' ([Siemens.Engineering.ExportOptions]::WithDefaults) } | Should Throw 'git repo'
        Assert-BareWhole $d $head
    }

    It 'next says what a repo around an export folder got: nothing removed, the new files written' {
        $repo = New-TestProject
        Write-Old $repo 'README.txt'
        Save-TestRepo $repo
        $null = New-NestedRepo $repo 'project'
        Mock Export-ProjectTexts { [System.IO.File]::WriteAllText((Join-Path $Dir 'new.xlsx'), 'new'); @{} }
        $r = Invoke-FullExportTool ([pscustomobject]@{ parts = @('project_texts') })
        @($r.keptRepos) | Should Be 'project'
        $r.next | Should Not Match 'left whole'
        $r.next | Should Match 'nothing of them was removed'
        $r.next | Should Match 'holds an export folder.*new files'
    }

    It 'next says what git add -A does to each kind of repo, and it does that' {
        $repo = New-TestProject
        Write-Old $repo 'plc\blocks\Stale.s7dcl'
        Save-TestRepo $repo
        $null = New-NestedRepo $repo 'plc\blocks\sub'
        $null = New-BareRepo $repo 'plc\blocks\x.git'
        $r = Invoke-FullExportTool $blocks
        $r.next | Should Match 'a repo with a \.git as one pointer, not its files'
        $r.next | Should Match 'a bare repo as files of the project repo'
        Invoke-Git $repo @('add', '-A')
        $sub = (Invoke-GitRaw $repo @('ls-files', '-s', 'plc/blocks/sub')).output
        @($sub).Count | Should Be 1
        $sub | Should Match '^160000 '
        @((Invoke-GitRaw $repo @('ls-files', 'plc/blocks/x.git')).output) -contains 'plc/blocks/x.git/HEAD' | Should Be $true
    }

    It 'next says git add -A stops on a repo with no commit, staging nothing, and it does' {
        $repo = New-TestProject
        Write-Old $repo 'plc\blocks\Stale.s7dcl'
        Save-TestRepo $repo
        $d = Join-Path $repo 'plc\blocks\u2'
        Write-Old $d 'work.txt'
        Invoke-Git $d @('init', '-q')
        $r = Invoke-FullExportTool $blocks
        Test-Path (Join-Path $d 'work.txt') | Should Be $true
        @($r.keptRepos) | Should Be 'plc\blocks\u2'
        $r.next | Should Match 'a repo with no commit stops it with an error, nothing staged'
        $add = Invoke-GitRaw $repo @('add', '-A')
        $add.exitCode | Should Not Be 0
        ($add.output -join ' ') | Should Match 'does not have a commit checked out'
        @((Invoke-GitRaw $repo @('diff', '--cached', '--name-only')).output).Count | Should Be 0
    }

    It 'a project with no repo inside lists none and says nothing of them' {
        $repo = New-TestProject
        Write-Old $repo 'plc\blocks\Stale.s7dcl'
        Save-TestRepo $repo
        $r = Invoke-FullExportTool $blocks
        @($r.keptRepos).Count | Should Be 0
        $r.next | Should Not Match 'keptRepos'
    }
}

Describe 'objects TIA does not export by design' {
    $repo = Join-Path $TestDrive 'left'
    Initialize-BridgeContext @{ maxResponseChars = 20000 }
    Set-BridgeProject -Name 'P' -Path 'C:\P.ap20' -Repo $repo
    $fob = New-Block 'FOB_RTG1'
    $fob | Add-Member ScriptMethod ExportAsDocuments { param($d, $n) throw "The export of block 'FOB_RTG1' is not permitted." } -Force
    $fob | Add-Member ScriptMethod Export { param($f, $o) throw "The export of block 'FOB_RTG1' is not permitted." } -Force
    $plc = [pscustomobject]@{ BlockGroup = [pscustomobject]@{ Blocks = @((New-Block 'A'), $fob); Groups = @() } }
    Mock Get-TiaSoftwareList { @(@{ device = 'PLC_1'; kind = 'plc'; software = $plc }) }
    Mock Get-TiaProject { [pscustomobject]@{ Name = 'P'; ProjectLibrary = $null } }
    Mock Test-IsDataBlock { $false }

    It 'lists them in leftOut, not as failed, and keeps their last export' {
        Write-Old $repo 'plc\blocks\FOB_RTG1.xml'
        $r = Invoke-FullExportTool ([pscustomobject]@{ parts = @('blocks', 'dbs') })
        $r.failedCount | Should Be 0
        $r.ok | Should Be $true
        ($r.leftOut -join '|') | Should Match '^1 F-system blocks and the F-OB of the F-runtime group: TIA does not permit their export: FOB_RTG1$'
        ($r.parts -join '|') | Should Match 'blocks@PLC_1: 1/2, [\d.]+ s, 1 not exportable'
        Test-Path (Join-Path $repo 'plc\blocks\FOB_RTG1.xml') | Should Be $true
    }
}

Describe 'Export-SettingsDat' {
    It 'keeps the .dat and writes the XML it holds beside it' {
        Add-Type -AssemblyName System.IO.Compression, System.IO.Compression.FileSystem
        $svc = [pscustomobject]@{}
        $svc | Add-Member ScriptMethod Export { param($f)
            $z = [System.IO.Compression.ZipFile]::Open($f.FullName, 'Create')
            try { $w = New-Object System.IO.StreamWriter ($z.CreateEntry('alarm-classes.dat').Open()); $w.Write('<AlarmServiceGlobalSettingsData />'); $w.Dispose() } finally { $z.Dispose() }
            [pscustomobject]@{ State = 'Success' } }
        $d = Join-Path $TestDrive 'dat'; New-Item -ItemType Directory -Force -Path $d | Out-Null
        (Export-SettingsDat $svc $d 'alarm-classes' 'alarm classes').objects | Should Be 1
        Test-Path (Join-Path $d 'alarm-classes.dat') | Should Be $true
        Get-Content (Join-Path $d 'alarm-classes.xml') | Should Be '<AlarmServiceGlobalSettingsData />'
    }
}

Describe 'full_export of a project with several PLCs' {
    $repo = Join-Path $TestDrive 'twoplcs'
    Initialize-BridgeContext @{ maxResponseChars = 20000 }
    Set-BridgeProject -Name 'P' -Path 'C:\P.ap20' -Repo $repo
    $sources = [pscustomobject]@{ ExternalSources = @([pscustomobject]@{ Name = 'Src' }); Groups = @() }
    $noSources = [pscustomobject]@{ ExternalSources = @(); Groups = @() }
    $plc1 = [pscustomobject]@{ BlockGroup = [pscustomobject]@{ Blocks = @(New-Block 'A'); Groups = @() }; ExternalSourceGroup = $sources }
    $plc2 = [pscustomobject]@{ BlockGroup = [pscustomobject]@{ Blocks = @(New-Block 'B'); Groups = @() }; ExternalSourceGroup = $noSources }
    $hmi = New-FakeHmi @(New-XmlObject 'S1')
    Mock Get-TiaSoftwareList { @(@{ device = 'PLC_1'; kind = 'plc'; software = $plc1 }, @{ device = 'PLC_2'; kind = 'plc'; software = $plc2 }, @{ device = 'HMI_A'; kind = 'hmi'; software = $hmi }) }
    Mock Get-TiaProject { [pscustomobject]@{ Name = 'P'; ProjectLibrary = $null } }
    Mock Test-IsDataBlock { $false }

    # Every test here runs as the bridge does: under Continue a null method call only writes an error record.
    It 'gives a part without a folder no folder, whatever the device' {
        $ErrorActionPreference = 'Stop'
        Get-PartDir (Get-FullExportPart 'external_sources') 'PLC_1' | Should BeNullOrEmpty
        Get-PartDir (Get-FullExportPart 'plc_alarm_texts') 'PLC_1' | Should Be 'plc\PLC_1\alarms'
        Get-PartDir (Get-FullExportPart 'blocks') 'PLC_2' | Should Be 'plc\PLC_2\blocks'
    }

    It 'runs every part without parts: past external_sources, each PLC in its folder, with the whole summary' {
        $ErrorActionPreference = 'Stop'
        $r = Invoke-FullExportTool ([pscustomobject]@{ })
        $r.error | Should BeNullOrEmpty
        $lines = $r.parts -join '|'
        $lines | Should Match 'blocks@PLC_1: 1/1'
        $lines | Should Match 'blocks@PLC_2: 1/1'
        $lines | Should Match 'external_sources@PLC_1: 1 not exportable'
        $lines | Should Match 'external_sources@PLC_2: none'
        # the parts after it, one of each scope
        $lines | Should Match 'hmi_screens@HMI_A: 1/1'
        $lines | Should Match '\|project_texts: '
        $lines | Should Match '\|master_copies: '
        $r.leftOut -join '|' | Should Match '1 external source files: .* \(PLC_1\)'
        Test-Path (Join-Path $repo 'plc\PLC_1\blocks\A.s7dcl') | Should Be $true
        Test-Path (Join-Path $repo 'plc\PLC_2\blocks\B.s7dcl') | Should Be $true
        Test-Path (Join-Path $repo 'hmi\screens\S1.xml') | Should Be $true
    }
}

Describe 'a part that fails keeps the summary of the others' {
    $repo = Join-Path $TestDrive 'summary'
    Register-ObjectKind 'fakegood' @{
        scope = 'project'; dir = 'project\good'; description = 'test kind that lists nothing'
        items = { param($root) @() }
        export = { param($e, $dir, $opt) @{ ok = $true; format = 'xml'; files = @() } }
    }
    Mock Get-TiaSoftwareList { @() }
    Mock Get-TiaProject { [pscustomobject]@{ Name = 'P'; ProjectLibrary = $null } }
    # The parts around the one that fails; the list of parts is restored afterwards.
    function Invoke-FakeFullExport([object[]]$Parts) {
        Initialize-BridgeContext @{ maxResponseChars = 20000 }
        Set-BridgeProject -Name 'P' -Path 'C:\P.ap20' -Repo $repo
        $saved = $script:FullExportParts
        $script:FullExportParts = $Parts
        try { Invoke-FullExportTool ([pscustomobject]@{ }) } finally { $script:FullExportParts = $saved }
    }
    $before = @{ name = 'before'; scope = 'project'; kind = 'fakegood' }
    $after = @{ name = 'after'; scope = 'project'; counter = { param($r) @('one') }; leftOut = 'things Openness cannot export' }

    It 'a part whose folder cannot be told: reported, and the parts after it still run' {
        $ErrorActionPreference = 'Stop'
        $r = Invoke-FakeFullExport @($before, @{ name = 'broken'; scope = 'project'; kind = 'nosuchkind' }, $after)
        $r.ok | Should Be $false
        $r.failed -join '|' | Should Match '^broken: not listed: '
        $r.parts -join '|' | Should Match '^before: 0/0.*\|broken: .*not listed\|after: 1 not exportable$'
        $r.leftOut | Should Match '^1 things Openness cannot export'
    }

    It 'a part whose folder cannot be told: nothing is mirrored, a folder it shares may hold its files' {
        $ErrorActionPreference = 'Stop'
        Write-Old $repo 'project\good\Other.xml'
        Save-TestRepo $repo
        $r = Invoke-FakeFullExport @($before, @{ name = 'broken'; scope = 'project'; kind = 'nosuchkind' })
        @($r.removed).Count | Should Be 0
        Test-Path (Join-Path $repo 'project\good\Other.xml') | Should Be $true
        $r.removeErrors -join '|' | Should Match 'mirror'
    }

    It 'a mirror that fails: said in the result, with every part line' {
        $ErrorActionPreference = 'Stop'
        Mock Get-MirrorRemovals { throw 'folder locked' }
        $r = Invoke-FakeFullExport @($before, $after)
        $r.ok | Should Be $false
        $r.removeErrors -join '|' | Should Match 'project.good: .*folder locked'
        $r.parts -join '|' | Should Match '^before: 0/0.*\|after: 1 not exportable$'
    }
}

Describe 'supervision settings' {
    if (-not ('Siemens.Engineering.SW.Supervision.SupervisionSettingsProvider' -as [type])) {
        Add-Type -TypeDefinition 'namespace Siemens.Engineering.SW.Supervision { public class SupervisionSettingsProvider { } }'
    }
    $repo = Join-Path $TestDrive 'supervision'
    Initialize-BridgeContext @{ maxResponseChars = 20000 }
    Set-BridgeProject -Name 'P' -Path 'C:\P.ap20' -Repo $repo
    Mock Get-TiaSoftwareList { @() }
    Mock Get-TiaProject { [pscustomobject]@{ Name = 'P'; ProjectLibrary = $null } }
    # A provider whose Export answers ErrorRollback with this text, as TIA does.
    function New-RefusingService([string]$Text, [switch]$LeavesFile) {
        $svc = [pscustomobject]@{ text = $Text; leavesFile = [bool]$LeavesFile }
        $svc | Add-Member ScriptMethod Export { param($f) if ($this.leavesFile) { [System.IO.File]::WriteAllText($f.FullName, '') }; [pscustomobject]@{ State = 'ErrorRollback'; Messages = @([pscustomobject]@{ State = 'Error'; Description = $this.text }) } }
        $svc
    }

    It 'a project without them has none: not a failure, and the run stays ok' {
        $ErrorActionPreference = 'Stop'
        $script:svc = New-RefusingService 'Global settings are not initialized!'
        Mock Get-RequiredService { $script:svc }
        Write-Old $repo 'tiabridge.json'
        Save-TestRepo $repo
        $r = Invoke-FullExportTool ([pscustomobject]@{ parts = @('supervision_settings') })
        $r.failedCount | Should Be 0
        $r.ok | Should Be $true
        $r.parts | Should Be 'supervision_settings: none'
    }

    It 'any other refusal stays a failure' {
        $ErrorActionPreference = 'Stop'
        $script:svc = New-RefusingService 'Something else went wrong'
        Mock Get-RequiredService { $script:svc }
        $r = Invoke-FullExportTool ([pscustomobject]@{ parts = @('supervision_settings') })
        $r.ok | Should Be $false
        $r.failed -join '|' | Should Match 'TIA reported ErrorRollback: Something else went wrong'
    }

    It 'none holds also when TIA leaves a file behind on the rollback: it replaces nothing' {
        $ErrorActionPreference = 'Stop'
        $repo2 = Join-Path $TestDrive 'supervision2'
        Set-BridgeProject -Name 'P' -Path 'C:\P.ap20' -Repo $repo2
        foreach ($f in 'supervision-settings.dat', 'supervision-settings.xml') { Write-Old $repo2 "project\supervision\$f" }
        Save-TestRepo $repo2
        $script:svc = New-RefusingService 'Global settings are not initialized!' -LeavesFile
        Mock Get-RequiredService { $script:svc }
        $r = Invoke-FullExportTool ([pscustomobject]@{ parts = @('supervision_settings') })
        $r.parts | Should Be 'supervision_settings: none'
        $r.exported | Should Be 0
        (@($r.removed) | Sort-Object) -join '|' | Should Be 'project\supervision\supervision-settings.dat|project\supervision\supervision-settings.xml'
        Test-Path (Join-Path $repo2 'project\supervision') | Should Be $false
    }
}

Describe 'Get-GitUncommittedFiles, with the git context of a parent inherited' {
    It 'names the files of the repo asked for' {
        $a = Join-Path $TestDrive 'context\A'
        $b = Join-Path $TestDrive 'context\B'
        foreach ($repo in $a, $b) {
            New-Item -ItemType Directory -Force -Path $repo | Out-Null
            & git -C $repo init -q
        }
        Set-Content -LiteralPath (Join-Path $a 'only-in-a.txt') -Value 'a'
        $inB = Join-Path $b 'only-in-b.txt'
        Set-Content -LiteralPath $inB -Value 'b'
        try {
            $env:GIT_DIR = Join-Path $a '.git'
            $env:GIT_WORK_TREE = $a
            $env:GIT_INDEX_FILE = Join-Path $a '.git\index'
            $found = Get-GitUncommittedFiles $b
        } finally { foreach ($n in 'GIT_DIR', 'GIT_WORK_TREE', 'GIT_INDEX_FILE') { Remove-Item "Env:$n" -ErrorAction SilentlyContinue } }
        $found.error | Should BeNullOrEmpty
        @($found.paths.Keys) | Should Be @([System.IO.Path]::GetFullPath($inB).ToLowerInvariant())
    }
}

Describe 'a full_export with no change in TIA' {
    . (Join-Path $here 'Fixtures\ExportFiles.ps1')
    foreach ($t in 'Siemens.Engineering.SW.Alarm.AlarmClassDataProvider', 'Siemens.Engineering.HW.Systemdiagnostics.Settings.SystemdiagnosticsSettingsDataProvider') {
        if (-not ($t -as [type])) { $ns, $n = $t -replace '\.(\w+)$', '|$1' -split '\|'; Add-Type -TypeDefinition "namespace $ns { public class $n { } }" 3>$null }
    }
    $repo = Join-Path $TestDrive 'again'
    Initialize-BridgeContext @{ maxResponseChars = 20000 }
    Set-BridgeProject -Name 'P' -Path 'C:\P.ap20' -Repo $repo
    # what TIA holds; each export writes it with a new export time, new zip entry times and new relationship Ids
    $script:tia = @{ screen = '<Hmi.Screen.Screen ID="0" />'; cell = 'text'; alarmClass = 'Acknowledgement' }
    $screen = [pscustomobject]@{ Name = 'S1' }
    $screen | Add-Member ScriptMethod Export { param($f, $opt) Write-TestText $f.FullName (Get-SimaticMlText $script:tia.screen) -Bom }
    $en = [System.Globalization.CultureInfo]::GetCultureInfo('en-US')
    $project = [pscustomobject]@{ Name = 'P'; ProjectLibrary = $null
                                  LanguageSettings = [pscustomobject]@{ ReferenceLanguage = [pscustomobject]@{ Culture = $en }; ActiveLanguages = @([pscustomobject]@{ Culture = $en }) } }
    $project | Add-Member ScriptMethod ExportProjectTexts { param($f, $from, $to) Write-TestXlsx $f.FullName $script:tia.cell }
    $script:project = $project
    $settings = [pscustomobject]@{}
    $settings | Add-Member ScriptMethod Export { param($f) Write-SettingsDat $f.FullName $script:tia.alarmClass; [pscustomobject]@{ State = 'Success' } }
    $script:settings = $settings
    $script:hmi = New-FakeHmi @($screen)
    Mock Get-TiaSoftwareList { @(@{ device = 'HMI_1'; kind = 'hmi'; software = $script:hmi }) }
    Mock Get-TiaProject { $script:project }
    Mock Get-RequiredService { $script:settings }
    $parts = [pscustomobject]@{ parts = @('hmi_screens', 'project_texts', 'alarm_classes', 'diagnostics_settings') }
    function Get-Status { @((Invoke-GitRaw $repo @('status', '--porcelain', '--untracked-files=all')).output | Where-Object { $_ -and $_ -notmatch ' logs/' }) }

    It 'export, commit, export again: git status is clean' {
        $r = Invoke-FullExportTool $parts
        $r.ok | Should Be $true
        $r.exported | Should Be 4
        $r.unchanged | Should Be 0
        Save-TestRepo $repo
        $r = Invoke-FullExportTool $parts
        $r.ok | Should Be $true
        Get-Status | Should BeNullOrEmpty
        # the screen, the project texts, two .dat files and the XML beside each
        $r.unchanged | Should Be 6
    }

    It 'a change made in TIA between two exports still shows in the files' {
        $script:tia.screen = '<Hmi.Screen.Screen ID="0"><AttributeList><Width>800</Width></AttributeList></Hmi.Screen.Screen>'
        $script:tia.cell = 'edited text'
        $script:tia.alarmClass = 'Warnings'
        $r = Invoke-FullExportTool $parts
        $r.ok | Should Be $true
        $r.unchanged | Should Be 0
        (Get-Status | ForEach-Object { $_.Substring(3) } | Sort-Object) -join '|' |
            Should Be 'hmi/screens/S1.xml|project/alarmclasses/alarm-classes.dat|project/alarmclasses/alarm-classes.xml|project/diagnostics/systemdiagnostics-settings.dat|project/diagnostics/systemdiagnostics-settings.xml|project/texts/project-texts_en-US_en-US.xlsx'
        Get-Content (Join-Path $repo 'hmi\screens\S1.xml') -Raw | Should Match '<Width>800</Width>'
    }

    It 'export counts the files it left as they were, as full_export does' {
        Mock Get-KindRoot { $script:hmi }
        $script:tia.screen = '<Hmi.Screen.Screen ID="0" />'
        $r = Invoke-ExportTool ([pscustomobject]@{ kind = 'hmi_screen'; names = @('S1') })
        $r.ok | Should Be $true
        $r.unchanged | Should Be 0
        $r = Invoke-ExportTool ([pscustomobject]@{ kind = 'hmi_screen'; names = @('S1') })
        $r.unchanged | Should Be 1
        $script:tia.screen = '<Hmi.Screen.Screen ID="1" />'
        $r = Invoke-ExportTool ([pscustomobject]@{ kind = 'hmi_screen'; names = @('S1') })
        $r.unchanged | Should Be 0
    }

    It 'a file part whose folder holds a git repo, written around it, keeps such a file too' {
        $sub = Join-Path $repo 'project\texts\sub'
        New-Item -ItemType Directory -Force -Path $sub | Out-Null
        Invoke-Git $sub @('init', '-q')
        $f = Join-Path $repo 'project\texts\project-texts_en-US_en-US.xlsx'
        $before = [System.IO.File]::ReadAllBytes($f)
        $r = Invoke-FullExportTool ([pscustomobject]@{ parts = @('project_texts') })
        @($r.keptRepos) | Should Be 'project\texts\sub'
        [System.IO.File]::ReadAllBytes($f) -join ',' | Should Be ($before -join ',')
        $script:tia.cell = 'edited again'
        $null = Invoke-FullExportTool ([pscustomobject]@{ parts = @('project_texts') })
        [System.IO.File]::ReadAllBytes($f) -join ',' | Should Not Be ($before -join ',')
    }
}
