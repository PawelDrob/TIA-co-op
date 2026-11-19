$here = Split-Path -Parent $MyInvocation.MyCommand.Path
foreach ($f in 'Mcp.ps1', 'Tia.ps1', 'Repo.ps1', 'Rules.ps1', 'Guards.ps1', 'Bridge.ps1', 'Tools\Objects.ps1', 'Tools\Plc.ps1', 'Tools\Hmi.ps1',
               'Tools\Library.ps1', 'Tools\FullExport.ps1') { . (Join-Path $here "..\$f") }
. (Join-Path $here 'TestBridge.ps1')
. (Join-Path $here 'Fixtures\ExportFiles.ps1')

# The work folder of an export (Repo.ps1): every object of an export call or a full_export part is exported
# into one folder, and the files go in place together. Each property the per-object folders had holds through it.

if (-not ('Siemens.Engineering.ExportOptions' -as [type])) {
    Add-Type -TypeDefinition 'namespace Siemens.Engineering { [System.Flags] public enum ExportOptions { None = 0, WithDefaults = 1, WithReadOnly = 2 } }'
}

function Test-TiaAlive { Test-FakeTiaAlive }
function Get-LibraryLink { $null }

# A block. ExportAsDocuments writes <name>.s7dcl and .s7res with Sd and reports State (a refused one writes 'half' first);
# Export writes Xml as SimaticML, or throws when XmlFail, and refuses a file that is there, as TIA does; FailOnce: its first
# Export writes 'half' and throws. KnowHow: know-how protected, so exported as SimaticML. Gone: TIA answers no more after
# its export. Each folder TIA is given goes into $script:workDirs, and $script:probe runs at each export.
function New-TestBlock([string]$Name, [string]$State = 'Success', [string]$Xml = "$Name xml", [switch]$XmlFail, [switch]$FailOnce, [switch]$KnowHow, [switch]$Gone) {
    $b = [pscustomobject]@{ Name = $Name; IsKnowHowProtected = [bool]$KnowHow; state = $State; xml = $Xml; xmlFail = [bool]$XmlFail; failOnce = [bool]$FailOnce; gone = [bool]$Gone }
    $b | Add-Member ScriptMethod ExportAsDocuments { param($d, $n)
        $script:workDirs += @($d.FullName)
        if ($script:probe) { & $script:probe $this.Name }
        if ($this.gone) { $script:tiaGone = $true; throw 'TIA said no' }
        $text = if ($this.state -eq 'Success') { "$($this.Name) sd" } else { 'half' }
        foreach ($x in '.s7dcl', '.s7res') { [System.IO.File]::WriteAllText((Join-Path $d.FullName "$n$x"), $text) }
        [pscustomobject]@{ State = $this.state; Messages = @([pscustomobject]@{ State = 'Error'; Description = 'SimaticSdEnabler needed' }) } }
    $b | Add-Member ScriptMethod Export { param($f, $o)
        $script:workDirs += @($f.DirectoryName)
        if ($script:probe) { & $script:probe $this.Name }
        if ($this.gone) { $script:tiaGone = $true; throw 'TIA said no' }
        if ($this.xmlFail) { throw "Export of $($this.Name) refused" }
        if ([System.IO.File]::Exists($f.FullName)) { throw "The file $($f.FullName) exists already." }
        if ($this.failOnce) { $this.failOnce = $false; [System.IO.File]::WriteAllText($f.FullName, 'half'); throw "Export of $($this.Name) broke off" }
        [System.IO.File]::WriteAllText($f.FullName, $this.xml) }
    $b
}

function Write-Old([string]$Repo, [string]$Rel, [string]$Text = 'old') {
    $p = Join-Path $Repo $Rel
    New-Item -ItemType Directory -Force -Path (Split-Path -Parent $p) | Out-Null
    [System.IO.File]::WriteAllText($p, $Text)
}
function Read-Repo([string]$Rel) { [System.IO.File]::ReadAllText((Join-Path $script:repo $Rel)) }
# Every work folder left in the repo: none, after an export.
function Get-WorkLeft { @(Get-ChildItem -LiteralPath $script:repo -Recurse -Force -Filter '*.partial' | ForEach-Object { $_.FullName }) }

# A new repo with Blocks in its PLC, and the bridge bound to it.
function New-TestRepo([object[]]$Blocks) {
    $script:repo = Join-Path $TestDrive ([guid]::NewGuid().ToString('N').Substring(0, 8))
    New-Item -ItemType Directory -Force -Path $script:repo | Out-Null
    $script:workDirs = @(); $script:probe = $null; $script:tiaGone = $false
    Initialize-BridgeContext @{ maxResponseChars = 20000 }
    Set-TestBridgeProject $script:repo
    Read-CallFirstProject
    $script:plc = [pscustomobject]@{ BlockGroup = [pscustomobject]@{ Blocks = @($Blocks); Groups = @() } }
}
function Invoke-TestExport([string[]]$Names = @('*'), $Options = $null) {
    $a = [pscustomobject]@{ kind = 'block'; names = $Names }
    if ($Options) { $a | Add-Member NoteProperty options $Options }
    Invoke-ExportTool $a
}
function Invoke-TestPart {
    $rec = New-PartRecord @{ name = 'blocks' } ''
    Invoke-FullExportKindPart (Get-FullExportPart 'blocks') $script:plc '' $rec
    $rec
}

function Get-KindRoot { if ($script:kindRoot) { $script:kindRoot } else { $script:plc } }
function Test-IsDataBlock { $false }
function Get-TiaSoftwareList { @(@{ device = 'PLC_1'; kind = 'plc'; software = $script:plc }) }

Describe 'one work folder per export' {
    foreach ($how in 'export', 'full_export') {
        It "$how exports every object into one work folder beside the kind's folder, and puts the files in place after the last" {
            New-TestRepo @((New-TestBlock 'A'), (New-TestBlock 'B'), (New-TestBlock 'C'))
            Write-Old $script:repo 'plc\blocks\A.s7dcl'
            $script:probe = { param($n) if ($n -eq 'C') { $script:atC = Read-Repo 'plc\blocks\A.s7dcl' } }
            if ($how -eq 'export') { $null = Invoke-TestExport } else { $null = Invoke-TestPart }
            @($script:workDirs | Sort-Object -Unique).Count | Should Be 1
            $script:workDirs[0] | Should Match '\\plc\\blocks\.[0-9a-f]{8}\.partial$'
            $script:atC | Should Be 'old'
            Read-Repo 'plc\blocks\A.s7dcl' | Should Be 'A sd'
            Read-Repo 'plc\blocks\C.s7res' | Should Be 'C sd'
            Get-WorkLeft | Should BeNullOrEmpty
        }
    }

    It 'holds the TIA folders below the kind folder as the repo does' {
        New-TestRepo @()
        $script:plc.BlockGroup.Groups = @([pscustomobject]@{ Name = 'Sub'; Blocks = @(New-TestBlock 'S'); Groups = @() })
        $r = Invoke-TestExport
        $script:workDirs[0] | Should Match '\\plc\\blocks\.[0-9a-f]{8}\.partial\\Sub$'
        $r.items[0].files -join '|' | Should Be 'plc\blocks\Sub\S.s7dcl|plc\blocks\Sub\S.s7res'
        Read-Repo 'plc\blocks\Sub\S.s7dcl' | Should Be 'S sd'
    }

    It 'an export function called outside an export has a work folder of its own, gone when it returns' {
        New-TestRepo @()
        $dir = Join-Path $script:repo 'tags'
        $r = Export-PlcObject @{ name = 'T'; obj = (New-TestBlock 'T') } $dir (New-Object psobject) $false
        $r.ok | Should Be $true
        $script:workDirs[0] | Should Match '\\tags\.[0-9a-f]{8}\.partial$'
        Read-Repo 'tags\T.s7dcl' | Should Be 'T sd'
        Get-WorkLeft | Should BeNullOrEmpty
    }
}

Describe 'a refused or failed export keeps the last good files' {
    It 'an SD export TIA reports failed, whose SimaticML fails too, changes none of its files' {
        New-TestRepo @((New-TestBlock 'A'), (New-TestBlock 'B' 'Failure' -XmlFail), (New-TestBlock 'C'))
        Write-Old $script:repo 'plc\blocks\B.s7dcl' 'old B'; Write-Old $script:repo 'plc\blocks\B.s7res' 'old B'
        $rec = Invoke-TestPart
        $rec.failed.Count | Should Be 1
        $rec.failed[0].name | Should Be 'B'
        Read-Repo 'plc\blocks\B.s7dcl' | Should Be 'old B'
        Read-Repo 'plc\blocks\B.s7res' | Should Be 'old B'
        Test-Path (Join-Path $script:repo 'plc\blocks\B.xml') | Should Be $false
        Read-Repo 'plc\blocks\C.s7dcl' | Should Be 'C sd'
        Get-WorkLeft | Should BeNullOrEmpty
    }

    It 'an SD export TIA refuses, with its leftovers in the work folder, is exported again as SimaticML' {
        New-TestRepo @((New-TestBlock 'A'), (New-TestBlock 'B' 'Failure'), (New-TestBlock 'C'))
        Write-Old $script:repo 'plc\blocks\B.s7dcl' 'old B'
        $rec = Invoke-TestPart
        $rec.failed.Count | Should Be 0
        $rec.fellBack.Count | Should Be 1
        Read-Repo 'plc\blocks\B.xml' | Should Be 'B xml'
        Test-Path (Join-Path $script:repo 'plc\blocks\B.s7dcl') | Should Be $false
        Test-Path (Join-Path $script:repo 'plc\blocks\B.s7res') | Should Be $false
        @($rec.removed) | Should Be 'plc\blocks\B.s7dcl'
    }

    It 'an object of several files that fails after its first keeps that one as it was' {
        Register-ObjectKind 'twofiles' @{
            scope = 'plc'; dir = 'plc\two'; description = 'test kind: two files, the second may fail'
            items = { param($root) foreach ($n in 'Good', 'Half') { @{ name = $n; folder = ''; obj = [pscustomobject]@{ Name = $n } } } }
            export = { param($e, $dir, $opt)
                $one = [pscustomobject]@{ Name = $e.name }
                $one | Add-Member ScriptMethod Export { param($f, $o) [System.IO.File]::WriteAllText($f.FullName, 'new') }
                Export-ObjectFile $one (Join-Path $dir "$($e.name)_1.xml") $null
                if ($e.name -eq 'Half') { throw 'the second version did not export' }
                Export-ObjectFile $one (Join-Path $dir "$($e.name)_2.xml") $null
                @{ ok = $true; format = 'xml'; files = @((Join-Path $dir "$($e.name)_1.xml"), (Join-Path $dir "$($e.name)_2.xml")) } }
        }
        New-TestRepo @()
        Write-Old $script:repo 'plc\two\Half_1.xml'
        $r = Invoke-ExportTool ([pscustomobject]@{ kind = 'twofiles'; names = @('*') })
        ($r.items | ForEach-Object { "$($_.name) $($_.ok)" }) -join '|' | Should Be 'Good True|Half False'
        Read-Repo 'plc\two\Good_2.xml' | Should Be 'new'
        Read-Repo 'plc\two\Half_1.xml' | Should Be 'old'
        Get-WorkLeft | Should BeNullOrEmpty
    }

    It 'a SimaticML export that failed half way leaves nothing its retry in the same work folder meets' {
        New-TestRepo @((New-TestBlock 'A'), (New-TestBlock 'K' -KnowHow -FailOnce))
        Write-Old $script:repo 'plc\blocks\K.xml'
        $rec = Invoke-TestPart
        $rec.failed.Count | Should Be 0
        Read-Repo 'plc\blocks\K.xml' | Should Be 'K xml'
        Get-WorkLeft | Should BeNullOrEmpty
    }

    It 'the versions of a faceplate type stay as they were when the first does not go in place' {
        Register-ObjectKind 'versions' @{
            scope = 'plc'; dir = 'plc\versions'; description = 'test kind: the versions of a type, as faceplate types export'
            items = { param($root) @{ name = 'F'; folder = ''; obj = $script:faceplate } }
            export = { param($e, $dir, $opt) Export-LibraryTypeVersions $e $dir }
        }
        $script:faceplate = [pscustomobject]@{ Versions = @(foreach ($v in '1.0.0', '2.0.0') {
            $x = [pscustomobject]@{ VersionNumber = $v }
            $x | Add-Member ScriptMethod Export { param($f, $o) [System.IO.File]::WriteAllText($f.FullName, "new $($this.VersionNumber)") }
            $x }) }
        New-TestRepo @()
        foreach ($f in 'F_V1.0.0.xml', 'F_V2.0.0.xml', 'F.type.json') { Write-Old $script:repo "plc\versions\$f" }
        $lock = [System.IO.File]::Open((Join-Path $script:repo 'plc\versions\F_V1.0.0.xml'), 'Open', 'Read', 'None')
        try { $r = Invoke-ExportTool ([pscustomobject]@{ kind = 'versions'; names = @('F') }) }
        finally { $lock.Dispose() }
        $r.items[0].ok | Should Be $false
        $r.items[0].error.message | Should Match 'F_V1\.0\.0\.xml'
        foreach ($f in 'F_V1.0.0.xml', 'F_V2.0.0.xml', 'F.type.json') { Read-Repo "plc\versions\$f" | Should Be 'old' }
        Get-WorkLeft | Should BeNullOrEmpty
    }
}

Describe 'TIA ending in the middle of an export' {
    It 'export: what was exported before the end is in place, the object TIA ended at keeps its files, and no work folder stays' {
        New-TestRepo @((New-TestBlock 'A'), (New-TestBlock 'B' -Gone), (New-TestBlock 'C'))
        Write-Old $script:repo 'plc\blocks\B.s7dcl'
        $r = Invoke-TestExport
        $r.tiaEnded | Should Be $true
        ($r.items | ForEach-Object { "$($_.name) $($_.ok)" }) -join '|' | Should Be 'A True|B False'
        Read-Repo 'plc\blocks\A.s7dcl' | Should Be 'A sd'
        Read-Repo 'plc\blocks\B.s7dcl' | Should Be 'old'
        Get-WorkLeft | Should BeNullOrEmpty
    }

    It 'full_export: the same, and the part stops there' {
        New-TestRepo @((New-TestBlock 'A'), (New-TestBlock 'B' -Gone), (New-TestBlock 'C'))
        $rec = Invoke-TestPart
        $rec.stopped | Should Be $true
        @($rec.written | ForEach-Object { Split-Path -Leaf $_ }) -join '|' | Should Be 'A.s7dcl|A.s7res'
        Read-Repo 'plc\blocks\A.s7dcl' | Should Be 'A sd'
        Test-Path (Join-Path $script:repo 'plc\blocks\C.s7dcl') | Should Be $false
        Get-WorkLeft | Should BeNullOrEmpty
    }

    It 'an export that throws between objects puts what it exported in place and leaves no work folder' {
        New-TestRepo @((New-TestBlock 'A'), (New-TestBlock 'B'))
        Mock Write-ObjectProgress { throw 'the bridge failed' }
        { Invoke-TestExport } | Should Throw 'the bridge failed'
        Read-Repo 'plc\blocks\A.s7dcl' | Should Be 'A sd'
        Get-WorkLeft | Should BeNullOrEmpty
    }
}

Describe 'a file that differs only in what TIA writes anew per export' {
    It 'keeps its bytes and counts as unchanged' {
        $block = New-TestBlock 'X' -Xml (Get-SimaticMlText '<SW.Blocks.FB ID="0" />' '2026-11-19T01:00:00.0000000Z')
        New-TestRepo @($block)
        $old = Get-SimaticMlText '<SW.Blocks.FB ID="0" />' '2026-11-18T01:00:00.0000000Z'
        Write-Old $script:repo 'plc\blocks\X.xml' $old
        $r = Invoke-TestExport -Options ([pscustomobject]@{ format = 'xml' })
        $r.items[0].ok | Should Be $true
        $r.unchanged | Should Be 1
        Read-Repo 'plc\blocks\X.xml' | Should Be $old
    }
}

Describe 'names and destinations' {
    It 'refuses names that give one file before any export, and leaves their file as it is' {
        New-TestRepo @((New-TestBlock 'Ns:B'), (New-TestBlock 'Ns_B'))
        Write-Old $script:repo 'plc\blocks\Ns_B.s7dcl'
        $r = Invoke-TestExport
        @($r.items | Where-Object { $_.collision }).Count | Should Be 2
        $script:workDirs | Should BeNullOrEmpty
        Read-Repo 'plc\blocks\Ns_B.s7dcl' | Should Be 'old'
    }

    foreach ($how in 'export', 'full_export') {
        It "$how fails an object whose destination stays locked, naming it, keeps its files, and puts the others in place" {
            New-TestRepo @((New-TestBlock 'A'), (New-TestBlock 'L'), (New-TestBlock 'C'))
            Write-Old $script:repo 'plc\blocks\L.s7dcl'; Write-Old $script:repo 'plc\blocks\L.xml'
            $lock = [System.IO.File]::Open((Join-Path $script:repo 'plc\blocks\L.s7dcl'), 'Open', 'Read', 'None')
            try { if ($how -eq 'export') { $r = Invoke-TestExport } else { $rec = Invoke-TestPart } }
            finally { $lock.Dispose() }
            if ($how -eq 'export') {
                $l = $r.items[1]
                $r.ok | Should Be $false
            } else {
                $l = $rec.failed[0]
                $rec.exported | Should Be 2
                @($rec.kept | ForEach-Object { Split-Path -Leaf $_ }) | Should Be 'L'
                @($rec.written | Where-Object { $_ -like '*\L.*' }) | Should BeNullOrEmpty
                @($rec.removed) | Should BeNullOrEmpty
            }
            $l.name | Should Be 'L'
            $l.error.message | Should Match 'L\.s7dcl'
            Read-Repo 'plc\blocks\L.s7dcl' | Should Be 'old'
            Read-Repo 'plc\blocks\L.xml' | Should Be 'old'
            Read-Repo 'plc\blocks\C.s7dcl' | Should Be 'C sd'
            Get-WorkLeft | Should BeNullOrEmpty
        }
    }

    It 'keeps a git repo in the image folder of a graphic whole, and fails the graphic' {
        New-TestRepo @()
        $g = [pscustomobject]@{ Name = 'Logo' }
        $g | Add-Member ScriptMethod Export { param($f, $opt)
            $files = Join-Path $f.DirectoryName 'Logo files'
            New-Item -ItemType Directory -Force -Path $files | Out-Null
            [System.IO.File]::WriteAllText((Join-Path $files 'DefaultImageStream.png'), 'png')
            [System.IO.File]::WriteAllText($f.FullName, '<x />') }
        $script:kindRoot = [pscustomobject]@{ Graphics = @($g) }
        Write-Old $script:repo 'project\graphics\Logo files\.git\HEAD' 'ref: refs/heads/main'
        try { $r = Invoke-ExportTool ([pscustomobject]@{ kind = 'graphic'; names = @('Logo') }) } finally { $script:kindRoot = $null }
        $r.items[0].ok | Should Be $false
        $r.items[0].error.message | Should Match 'git repo'
        Read-Repo 'project\graphics\Logo files\.git\HEAD' | Should Be 'ref: refs/heads/main'
        Get-WorkLeft | Should BeNullOrEmpty
    }
}

Describe 'the mirror' {
    It 'removes only the files of objects gone, once the new files are in place, and keeps those of an object whose files did not go in place' {
        New-TestRepo @((New-TestBlock 'A'), (New-TestBlock 'L'))
        foreach ($f in 'A.s7dcl', 'Gone.s7dcl', 'L.s7dcl', 'L.xml') { Write-Old $script:repo "plc\blocks\$f" }
        $script:Bridge.background = @{ plain = $true }
        Mock Get-TiaProject { [pscustomobject]@{ Name = 'P'; ProjectLibrary = $null } }
        $lock = [System.IO.File]::Open((Join-Path $script:repo 'plc\blocks\L.s7dcl'), 'Open', 'Read', 'None')
        try { $r = Invoke-FullExportTool ([pscustomobject]@{ parts = @('blocks', 'dbs') }) }
        finally { $lock.Dispose(); $script:Bridge.background = $null }
        @($r.removed) | Should Be 'plc\blocks\Gone.s7dcl'
        Read-Repo 'plc\blocks\A.s7dcl' | Should Be 'A sd'
        Read-Repo 'plc\blocks\L.s7dcl' | Should Be 'old'
        Read-Repo 'plc\blocks\L.xml' | Should Be 'old'
        $r.failed | Should Match '^blocks@PLC_1: L: '
    }

    It 'stops at an object TIA does not permit to export, after which TIA did not answer, though it answers again, and removes no file of the objects after it' {
        $f = New-TestBlock 'F'
        $f | Add-Member -Force ScriptMethod ExportAsDocuments { param($d, $n) $script:goneOnce = $true; throw "The export of block 'F' is not permitted." }
        $f | Add-Member -Force ScriptMethod Export { param($file, $o) throw "The export of block 'F' is not permitted." }
        New-TestRepo @((New-TestBlock 'A'), $f, (New-TestBlock 'C'))
        foreach ($x in 'A.s7dcl', 'C.s7dcl') { Write-Old $script:repo "plc\blocks\$x" }
        Invoke-Git $script:repo @('init', '-q'); Invoke-Git $script:repo @('add', '-A'); Invoke-Git $script:repo @('commit', '-q', '-m', 'test')
        Mock Get-TiaProject { [pscustomobject]@{ Name = 'P'; ProjectLibrary = $null } }
        # no answer once, right after F's export; an answer at every ask after it
        Mock Test-TiaAlive { if ($script:goneOnce) { $script:goneOnce = $false; return $false }; $true }
        $r = Invoke-FullExportTool ([pscustomobject]@{ parts = @('blocks', 'dbs') })
        Read-Repo 'plc\blocks\C.s7dcl' | Should Be 'old'
        @($r.removed) | Should BeNullOrEmpty
        $r.tiaEnded | Should Be $true
    }
}
