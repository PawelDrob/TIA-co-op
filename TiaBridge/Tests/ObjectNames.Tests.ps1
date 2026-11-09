$here = Split-Path -Parent $MyInvocation.MyCommand.Path
foreach ($f in 'Mcp.ps1', 'Tia.ps1', 'Repo.ps1', 'Rules.ps1', 'Guards.ps1', 'Bridge.ps1', 'Tools\Objects.ps1', 'Tools\Plc.ps1', 'Tools\Hmi.ps1',
               'Tools\Library.ps1', 'Tools\LibraryChange.ps1', 'Tools\FullExport.ps1', 'Tools\Background.ps1') { . (Join-Path $here "..\$f") }

# Object names that do not fit a file name: two names on one file, names Windows changes or refuses, names that came back
# from TIA as another name. Every name here is made up; what TIA itself allows is for a real run.

if (-not ('Siemens.Engineering.ExportOptions' -as [type])) {
    Add-Type -TypeDefinition 'namespace Siemens.Engineering { [System.Flags] public enum ExportOptions { None = 0, WithDefaults = 1, WithReadOnly = 2 } }'
}
if (-not ('Siemens.Engineering.ImportOptions' -as [type])) {
    Add-Type -TypeDefinition 'namespace Siemens.Engineering { public enum ImportOptions { None, Override } }'
}
if (-not ('Siemens.Engineering.SW.ImportDocumentOptions' -as [type])) {
    Add-Type -TypeDefinition 'namespace Siemens.Engineering.SW { public enum ImportDocumentOptions { None, Override } }'
}
if (-not ('Siemens.Engineering.Library.LibraryExportOptions' -as [type])) {
    Add-Type -TypeDefinition 'namespace Siemens.Engineering.Library { public enum LibraryExportOptions { None, WithLibraryVersionInfoFile } }'
}
if (-not ('TiaBridgeNames.Portal' -as [type])) {
    Add-Type -TypeDefinition @'
namespace TiaBridgeNames {
    public class NoteArgs : System.EventArgs { public string Caption { get; set; } public string Text { get; set; } public string DetailText { get; set; } public string Icon { get; set; } public bool IsHandled { get; set; } }
    public class ConfirmArgs : System.EventArgs { public string Text { get; set; } public bool IsHandled { get; set; } }
    public class Portal {
        public event System.EventHandler<NoteArgs> Notification;
        public event System.EventHandler<ConfirmArgs> Confirmation;
        public void Tell(NoteArgs a) { var h = Notification; if (h != null) h(this, a); }
        public void Ask(ConfirmArgs a) { var h = Confirmation; if (h != null) h(this, a); }
    }
    public class NoEvents { }
}
'@
}

function Get-KindRoot { $script:root }
# the HMI validator guard of tag tables has tests of its own (HmiImport.Tests.ps1); here it passes everything
function Test-HmiImportGuard { @{} }
function Get-TiaSoftwareList { $script:software }
function Get-TiaService { $null }
function Get-TiaProject { [pscustomobject]@{ Name = 'P'; ProjectLibrary = $null } }
function Test-TiaAlive { $true }
function Get-LibraryLink { $null }
function Select-TypeVersion { param($Versions, [switch]$InWork) if ($InWork) { $null } else { @($Versions)[0] } }
function ConvertTo-ResultTree { @{ state = 'Success' } }
function Get-PlcBlockClass($Block) { if ($Block.Class) { $Block.Class } else { 'FB' } }
function Invoke-TiaWrite([string]$Description, [scriptblock]$Body, [switch]$NoTransaction, [scriptblock]$RollbackIf) {
    $out = @(& $Body)
    @{ output = $out; transaction = $true; rolledBack = [bool]($RollbackIf -and (& $RollbackIf)); commitError = $null; note = $null }
}

# File APIs that take a literal path, as TIA's do: a helper that globbed would hide what the code under test does with [ ].
function New-XmlObject([string]$Name) {
    $o = [pscustomobject]@{ Name = $Name; IsKnowHowProtected = $false; ProgrammingLanguage = 'SCL' }
    $o | Add-Member ScriptMethod Export { param($f, $opt) $script:exportCalls += @($this.Name); [System.IO.File]::WriteAllText($f.FullName, "written by $($this.Name)") }
    $o
}
function New-Block([string]$Name, [string]$Class = 'FB') {
    $b = New-XmlObject $Name
    $b | Add-Member NoteProperty Class $Class
    $b | Add-Member ScriptMethod ExportAsDocuments { param($d, $n)
        $script:exportCalls += @($this.Name)
        foreach ($x in '.s7dcl', '.s7res') { [System.IO.File]::WriteAllText((Join-Path $d.FullName "$n$x"), "written by $($this.Name)") }
        [pscustomobject]@{ State = 'Success'; Messages = @() } }
    $b
}
function New-FakeHmi([object[]]$Screens) { [pscustomobject]@{ ScreenFolder = [pscustomobject]@{ Screens = $Screens; Folders = @() } } }
function New-Folder([string]$Name, [object[]]$Screens) { [pscustomobject]@{ Name = $Name; Screens = $Screens; Folders = @() } }
function Write-Old([string]$Repo, [string]$Rel) {
    $p = Join-Path $Repo $Rel
    [void][System.IO.Directory]::CreateDirectory([System.IO.Path]::GetDirectoryName($p))
    [System.IO.File]::WriteAllText($p, 'old')
}
function Read-Repo([string]$Repo, [string]$Rel) { [System.IO.File]::ReadAllText((Join-Path $Repo $Rel)) }
function Save-TestRepo([string]$Repo) {
    if (-not (Test-Path -LiteralPath (Join-Path $Repo '.git'))) { Invoke-Git $Repo @('init', '-q') }
    Invoke-Git $Repo @('add', '-A')
    Invoke-Git $Repo @('commit', '-q', '--allow-empty', '-m', 'test')
}
$script:repoCount = 0
function New-TestRepo {
    $script:repoCount++
    $repo = Join-Path $TestDrive "r$script:repoCount"
    [void][System.IO.Directory]::CreateDirectory($repo)
    Initialize-BridgeContext @{ maxResponseChars = 20000 }
    Set-BridgeProject -Name 'P' -Path 'C:\P.ap20' -Repo $repo
    Register-Archive (Get-BridgeSession)
    $script:exportCalls = @()
    $script:software = @(@{ device = 'PLC_1'; kind = 'plc'; software = $null }, @{ device = 'HMI_1'; kind = 'hmi'; software = $null })
    $repo
}
function Invoke-ScreenExport($Screens, [string[]]$Names) {
    $script:root = New-FakeHmi $Screens
    Invoke-ExportTool ([pscustomobject]@{ kind = 'hmi_screen'; names = $Names })
}

# Every character the file name mapping changes or a path API could read as something else, and those real names hold.
$script:specialCharacters = @(
    @{ label = 'backslash'; c = '\' }, @{ label = 'slash'; c = '/' }, @{ label = 'colon'; c = ':' }, @{ label = 'star'; c = '*' }
    @{ label = 'question mark'; c = '?' }, @{ label = 'double quote'; c = '"' }, @{ label = 'less than'; c = '<' }
    @{ label = 'greater than'; c = '>' }, @{ label = 'pipe'; c = '|' }, @{ label = 'tab'; c = "`t" }, @{ label = 'space'; c = ' ' }
    @{ label = 'dot'; c = '.' }, @{ label = 'plus'; c = '+' }, @{ label = 'minus'; c = '-' }, @{ label = 'equals'; c = '=' }
    @{ label = 'open bracket'; c = '[' }, @{ label = 'close bracket'; c = ']' }, @{ label = 'open paren'; c = '(' }, @{ label = 'close paren'; c = ')' }
    @{ label = 'open brace'; c = '{' }, @{ label = 'close brace'; c = '}' }, @{ label = 'single quote'; c = "'" }, @{ label = 'backtick'; c = '`' }
    @{ label = 'semicolon'; c = ';' }, @{ label = 'comma'; c = ',' }, @{ label = 'bang'; c = '!' }, @{ label = 'hash'; c = '#' }
    @{ label = 'dollar'; c = '$' }, @{ label = 'percent'; c = '%' }, @{ label = 'ampersand'; c = '&' }, @{ label = 'caret'; c = '^' }
    @{ label = 'tilde'; c = '~' }, @{ label = 'at'; c = '@' }, @{ label = 'non-ASCII letter'; c = [string][char]0xE4 }
)

Describe 'ConvertTo-SafeFileName' {
    It 'keeps a plain name, and what a real project has in its names' {
        ConvertTo-SafeFileName 'Block_1' | Should BeExactly 'Block_1'
        ConvertTo-SafeFileName '0100 Overview-A+B=C' | Should BeExactly '0100 Overview-A+B=C'
    }

    It 'maps the nine characters Windows forbids' {
        ConvertTo-SafeFileName 'a\b/c:d*e?f"g<h>i|j' | Should BeExactly 'a_b_c_d_e_f_g_h_i_j'
    }

    It 'maps control characters, which throw at the path' {
        ConvertTo-SafeFileName "a`tb`nc" | Should BeExactly 'a_b_c'
        ConvertTo-SafeFileName "a$([char]1)b" | Should BeExactly 'a_b'
    }

    It 'maps a dot or a space at the end, which Windows would drop or refuse' {
        ConvertTo-SafeFileName 'Block.' | Should BeExactly 'Block_'
        ConvertTo-SafeFileName 'Block ' | Should BeExactly 'Block_'
        ConvertTo-SafeFileName 'Block. .' | Should BeExactly 'Block_'
        ConvertTo-SafeFileName '...' | Should BeExactly '_'
    }

    It 'keeps a dot or a space inside a name' {
        ConvertTo-SafeFileName 'a.b c' | Should BeExactly 'a.b c'
    }

    It 'maps a Windows device name, in any case and with an extension behind it' {
        foreach ($n in 'CON', 'con', 'PRN', 'AUX', 'NUL', 'nul', 'COM1', 'com9', 'LPT1', 'lpt9', "COM$([char]0xB9)", "LPT$([char]0xB3)", 'CONIN$', 'CONOUT$') {
            ConvertTo-SafeFileName $n | Should BeExactly "${n}_"
        }
        ConvertTo-SafeFileName 'NUL.txt' | Should BeExactly 'NUL_.txt'
    }

    It 'leaves a name that only starts like a device name' {
        foreach ($n in 'CONSOLE', 'NULL', 'COM', 'COM10', 'LPT', 'AUXILIARY', 'MyCON') { ConvertTo-SafeFileName $n | Should BeExactly $n }
    }

    It 'gives a name without any character a file name that is one' {
        ConvertTo-SafeFileName '' | Should BeExactly '_'
    }

    It 'gives names a file and a folder can be made of, and read back under the same name' {
        $dir = Join-Path $TestDrive 'made'
        foreach ($n in 'Block.', 'Block ', 'NUL', 'CON', 'COM1', 'aux.x', "a`tb", '...', '') {
            $safe = ConvertTo-SafeFileName $n
            $sub = Join-Path $dir $safe
            [void][System.IO.Directory]::CreateDirectory($sub)
            [System.IO.File]::WriteAllText((Join-Path $sub "$safe.xml"), $n)
            [System.IO.File]::ReadAllText((Join-Path $sub "$safe.xml")) | Should BeExactly $n
            [System.IO.Path]::GetFileName(@(Get-ChildItem -LiteralPath $sub -File)[0].FullName) | Should BeExactly "$safe.xml"
        }
    }
}

Describe 'export: two names on one file' {
    It 'refuses both and writes nothing, the file there stays as it was' {
        $repo = New-TestRepo
        Write-Old $repo 'hmi\screens\Ns_S.xml'
        $r = Invoke-ScreenExport @((New-XmlObject 'Ns:S'), (New-XmlObject 'Ns_S')) @('*')
        $r.ok | Should Be $false
        @($script:exportCalls).Count | Should Be 0
        Read-Repo $repo 'hmi\screens\Ns_S.xml' | Should BeExactly 'old'
        foreach ($i in $r.items) {
            $i.ok | Should Be $false
            $i.error.type | Should Be 'TiaBridge.NameCollision'
            $i.error.message | Should Match "'Ns:S' and 'Ns_S'"
            $i.error.message | Should Match 'Ns_S'
            $i.error.message | Should Match 'Rename one'
            @($i.collision) -join ',' | Should Be 'Ns:S,Ns_S'
        }
    }

    It 'refuses a name asked for alone, since its file may hold the other object' {
        $repo = New-TestRepo
        Write-Old $repo 'hmi\screens\Ns_S.xml'
        $r = Invoke-ScreenExport @((New-XmlObject 'Ns:S'), (New-XmlObject 'Ns_S')) @('Ns:S')
        $r.ok | Should Be $false
        $r.items.Count | Should Be 1
        $r.items[0].error.message | Should Match "'Ns:S' and 'Ns_S'"
        Read-Repo $repo 'hmi\screens\Ns_S.xml' | Should BeExactly 'old'
    }

    It 'exports the others of the call' {
        $repo = New-TestRepo
        $r = Invoke-ScreenExport @((New-XmlObject 'Ns:S'), (New-XmlObject 'Ns/S'), (New-XmlObject 'Other')) @('*')
        $r.ok | Should Be $false
        @($r.items | Where-Object { $_.ok } | ForEach-Object { $_.name }) -join ',' | Should Be 'Other'
        Read-Repo $repo 'hmi\screens\Other.xml' | Should BeExactly 'written by Other'
        Test-Path -LiteralPath (Join-Path $repo 'hmi\screens\Ns_S.xml') | Should Be $false
    }

    It 'knows names that differ only in case share a file' {
        $null = New-TestRepo
        $r = Invoke-ScreenExport @((New-XmlObject 'Abc'), (New-XmlObject 'ABC')) @('*')
        @($script:exportCalls).Count | Should Be 0
        $r.items[0].error.type | Should Be 'TiaBridge.NameCollision'
    }

    It 'knows a name Windows would change shares a file with what it becomes' {
        $null = New-TestRepo
        $r = Invoke-ScreenExport @((New-XmlObject 'Abc.'), (New-XmlObject 'Abc_')) @('*')
        @($script:exportCalls).Count | Should Be 0
        $r.items[0].error.type | Should Be 'TiaBridge.NameCollision'
    }

    It 'knows objects of two kinds in one folder share a file: an FB beside a DB' {
        $repo = New-TestRepo
        Write-Old $repo 'plc\blocks\Ns_X.s7dcl'
        $script:root = [pscustomobject]@{ BlockGroup = [pscustomobject]@{ Blocks = @((New-Block 'Ns:X'), (New-Block 'Ns_X' 'GlobalDB')); Groups = @() } }
        $r = Invoke-ExportTool ([pscustomobject]@{ kind = 'block'; names = @('Ns:X') })
        $r.ok | Should Be $false
        $r.items[0].error.type | Should Be 'TiaBridge.NameCollision'
        @($script:exportCalls).Count | Should Be 0
        Read-Repo $repo 'plc\blocks\Ns_X.s7dcl' | Should BeExactly 'old'
    }

    It 'knows files in one folder from two TIA folders of one file-safe name' {
        $null = New-TestRepo
        $hmi = [pscustomobject]@{ ScreenFolder = [pscustomobject]@{ Screens = @(); Folders = @((New-Folder 'A:B' @(New-XmlObject 'Ns:S')), (New-Folder 'A_B' @(New-XmlObject 'Ns_S'))) } }
        $script:root = $hmi
        $r = Invoke-ExportTool ([pscustomobject]@{ kind = 'hmi_screen'; names = @('*') })
        @($script:exportCalls).Count | Should Be 0
        $r.items[0].error.type | Should Be 'TiaBridge.NameCollision'
    }

    It 'lets one name stand in two TIA folders that stay two folders' {
        $repo = New-TestRepo
        $hmi = [pscustomobject]@{ ScreenFolder = [pscustomobject]@{ Screens = @(); Folders = @((New-Folder 'A' @(New-XmlObject 'S')), (New-Folder 'B' @(New-XmlObject 'S'))) } }
        $script:root = $hmi
        (Invoke-ExportTool ([pscustomobject]@{ kind = 'hmi_screen'; names = @('*') })).ok | Should Be $true
        Test-Path -LiteralPath (Join-Path $repo 'hmi\screens\A\S.xml') | Should Be $true
        Test-Path -LiteralPath (Join-Path $repo 'hmi\screens\B\S.xml') | Should Be $true
    }

    It 'does not call a name a collision because of a sibling kind in another folder' {
        $null = New-TestRepo
        $script:root = [pscustomobject]@{ BlockGroup = [pscustomobject]@{ Blocks = @((New-Block 'X'), (New-Block 'Y' 'GlobalDB')); Groups = @() } }
        (Invoke-ExportTool ([pscustomobject]@{ kind = 'block'; names = @('X') })).ok | Should Be $true
    }
}

Describe 'full_export: two names on one file' {
    It 'exports neither, says so in failed, and the mirror keeps the file they share' {
        $repo = New-TestRepo
        foreach ($f in 'hmi\screens\Ns_S.xml', 'hmi\screens\Gone.xml') { Write-Old $repo $f }
        Save-TestRepo $repo
        $hmi = New-FakeHmi @((New-XmlObject 'Ns:S'), (New-XmlObject 'Ns_S'), (New-XmlObject 'Other'))
        $script:software = @(@{ device = 'HMI_1'; kind = 'hmi'; software = $hmi })
        $r = Invoke-FullExportTool ([pscustomobject]@{ parts = @('hmi_screens', 'hmi_templates') })
        $r.ok | Should Be $false
        $r.exported | Should Be 1
        $r.failedCount | Should Be 2
        ($r.failed -join '|') | Should Match "Ns:S: TiaBridge.NameCollision: .*'Ns:S' and 'Ns_S'"
        ($r.failed -join '|') | Should Match "Ns_S: TiaBridge.NameCollision"
        Read-Repo $repo 'hmi\screens\Ns_S.xml' | Should BeExactly 'old'
        @($r.removed) -join '|' | Should Be 'hmi\screens\Gone.xml'
        @($script:exportCalls) -join ',' | Should Be 'Other'
    }

    It 'does not try the SimaticML fallback on them' {
        $repo = New-TestRepo
        $plc = [pscustomobject]@{ BlockGroup = [pscustomobject]@{ Blocks = @((New-Block 'Ns:X'), (New-Block 'Ns_X')); Groups = @() } }
        $script:software = @(@{ device = 'PLC_1'; kind = 'plc'; software = $plc })
        $r = Invoke-FullExportTool ([pscustomobject]@{ parts = @('blocks') })
        @($script:exportCalls).Count | Should Be 0
        $r.failedCount | Should Be 2
        @(Get-ChildItem -LiteralPath $repo -Recurse -File -ErrorAction SilentlyContinue | Where-Object { $_.FullName -match 'Ns_X' }).Count | Should Be 0
    }

    It 'sees an FB beside a DB in the part of either' {
        $null = New-TestRepo
        $plc = [pscustomobject]@{ BlockGroup = [pscustomobject]@{ Blocks = @((New-Block 'Ns:X'), (New-Block 'Ns_X' 'GlobalDB')); Groups = @() } }
        $script:software = @(@{ device = 'PLC_1'; kind = 'plc'; software = $plc })
        $r = Invoke-FullExportTool ([pscustomobject]@{ parts = @('blocks', 'dbs') })
        @($script:exportCalls).Count | Should Be 0
        $r.failedCount | Should Be 2
    }
}

Describe 'objects without a name' {
    function New-Slidein([string]$Type) {
        $o = New-XmlObject ''
        $o | Add-Member NoteProperty SlideinType $Type
        $o | Add-Member ScriptMethod Export { param($f, $opt) $script:exportCalls += @($this.SlideinType); [System.IO.File]::WriteAllText($f.FullName, "written by $($this.SlideinType)") } -Force
        $o
    }
    function New-SlideinHmi([string[]]$Types) { [pscustomobject]@{ ScreenSlideinFolder = [pscustomobject]@{ ScreenSlideins = @($Types | ForEach-Object { New-Slidein $_ }) } } }

    It 'names a slide-in by its panel edge, so the four land in four files' {
        $repo = New-TestRepo
        $script:root = New-SlideinHmi @('Top', 'Bottom', 'Left', 'Right')
        $r = Invoke-ExportTool ([pscustomobject]@{ kind = 'hmi_slidein'; names = @('*') })
        $r.ok | Should Be $true
        @($r.items | ForEach-Object { $_.name }) -join ',' | Should Be 'Top,Bottom,Left,Right'
        foreach ($t in 'Top', 'Bottom', 'Left', 'Right') { Read-Repo $repo "hmi\slideins\$t.xml" | Should BeExactly "written by $t" }
        Test-Path -LiteralPath (Join-Path $repo 'hmi\slideins\.xml') | Should Be $false
    }

    It 'lists a slide-in under that name' {
        $null = New-TestRepo
        $script:root = New-SlideinHmi @('Top', 'Right')
        @((Invoke-ListTool ([pscustomobject]@{ kind = 'hmi_slidein' })).items | ForEach-Object { $_.name }) -join ',' | Should Be 'Top,Right'
    }

    It 'refuses two objects without a name, and calls them that' {
        $repo = New-TestRepo
        $script:root = [pscustomobject]@{ Connections = @((New-XmlObject ''), (New-XmlObject '')) }
        $r = Invoke-ExportTool ([pscustomobject]@{ kind = 'hmi_connection'; names = @('*') })
        $r.ok | Should Be $false
        @($script:exportCalls).Count | Should Be 0
        $r.items[0].error.type | Should Be 'TiaBridge.NameCollision'
        $r.items[0].error.message | Should Match '\(no name\)'
    }

    It 'writes one object without a name to a file with a name' {
        $repo = New-TestRepo
        $script:root = [pscustomobject]@{ Connections = @(New-XmlObject '') }
        (Invoke-ExportTool ([pscustomobject]@{ kind = 'hmi_connection'; names = @('*') })).items[0].files | Should Be 'hmi\connections\_.xml'
    }
}

Describe 'library_review: two types of one change on one file' {
    It 'names the types whose review documents would overwrite each other' {
        $c = Get-ReviewNameClashes @('Ns:T', 'Ns_T', 'Other')
        @($c['Ns:T']) -join ',' | Should Be 'Ns_T'
        @($c['Ns_T']) -join ',' | Should Be 'Ns:T'
        $c.ContainsKey('Other') | Should Be $false
    }
}

Describe 'import that lands under another name' {
    function New-TagHmi([string]$Answer, [string[]]$Existing = @()) {
        $tables = New-Object System.Collections.ArrayList
        foreach ($n in $Existing) { [void]$tables.Add([pscustomobject]@{ Name = $n; IsKnowHowProtected = $false; ProgrammingLanguage = '' }) }
        Add-Member -InputObject $tables NoteProperty Answer $Answer
        Add-Member -InputObject $tables ScriptMethod Import { param($f, $o)
            $script:importCalls += @($f.Name)
            if ($this.Answer) { [pscustomobject]@{ Name = $this.Answer } } }
        [pscustomobject]@{ TagFolder = [pscustomobject]@{ TagTables = $tables; Folders = @() } }
    }
    function Write-TagDoc([string]$Repo, [string]$File, [string]$Name) {
        Write-TextFile (Join-Path $Repo "hmi\generated\tags\$File.xml") "<?xml version=`"1.0`" encoding=`"utf-8`"?><Document><Hmi.Tag.TagTable ID=`"0`"><AttributeList><Name>$Name</Name></AttributeList></Hmi.Tag.TagTable></Document>"
    }
    function Invoke-TagImport([string]$File) {
        $script:importCalls = @()
        Invoke-ImportTool ([pscustomobject]@{ kind = 'hmi_tag_table'; paths = @("hmi\generated\tags\$File.xml") })
    }

    It 'says so: the result is not ok and names both' {
        $repo = New-TestRepo
        Write-TagDoc $repo 'Conveyor' 'Conveyor'
        $script:root = New-TagHmi 'Conveyor_1'
        $r = Invoke-TagImport 'Conveyor'
        $r.ok | Should Be $false
        $r.items[0].importedAs | Should Be 'Conveyor_1'
        @($r.namedOtherwise).Count | Should Be 1
        @($r.namedOtherwise)[0] | Should Match "'Conveyor'.*'Conveyor_1'"
        $r.next | Should Match "delete 'Conveyor_1'"
    }

    It 'does not roll back or stop the batch for it: the object is in TIA' {
        $repo = New-TestRepo
        Write-TagDoc $repo 'Conveyor' 'Conveyor'
        $script:root = New-TagHmi 'Conveyor_1'
        $r = Invoke-TagImport 'Conveyor'
        $r.rolledBack | Should Be $false
        $r.items[0].ok | Should Be $true
    }

    It 'counts the write under the name TIA gave, for the compile and save rules' {
        $repo = New-TestRepo
        Write-TagDoc $repo 'Conveyor' 'Conveyor'
        $script:root = New-TagHmi 'Conveyor_1'
        $null = Invoke-TagImport 'Conveyor'
        @((Get-BridgeSession).pending.Values) -join ' ' | Should Match 'Conveyor_1'
    }

    It 'says nothing when TIA gave the name asked for' {
        $repo = New-TestRepo
        Write-TagDoc $repo 'Conveyor' 'Conveyor'
        $script:root = New-TagHmi 'Conveyor'
        $r = Invoke-TagImport 'Conveyor'
        $r.ok | Should Be $true
        $r.items[0].Contains('importedAs') | Should Be $false
        $r.ContainsKey('namedOtherwise') | Should Be $false
    }

    It 'goes by the declared name, not the file name: Ns:T in Ns_T.xml is no other name' {
        $repo = New-TestRepo
        Write-TagDoc $repo 'Ns_T' 'Ns:T'
        $script:root = New-TagHmi 'Ns:T'
        $r = Invoke-TagImport 'Ns_T'
        $r.ok | Should Be $true
        $r.items[0].name | Should Be 'Ns:T'
    }

    It 'takes the file-safe form of the name when a document declares none it can read' {
        $repo = New-TestRepo
        Write-TextFile (Join-Path $repo 'hmi\generated\tags\Ns_T.xml') 'not a document the reader understands'
        $script:root = New-TagHmi 'Ns:T'
        (Invoke-TagImport 'Ns_T').ok | Should Be $true
    }

    It 'claims nothing when TIA names nothing' {
        $repo = New-TestRepo
        Write-TagDoc $repo 'Conveyor' 'Conveyor'
        $script:root = New-TagHmi ''
        (Invoke-TagImport 'Conveyor').ok | Should Be $true
    }

    It 'reads it from a document import of a block too' {
        $repo = New-TestRepo
        Write-TextFile (Join-Path $repo 'plc\blocks\A.s7dcl') "FUNCTION_BLOCK `"A`"`r`nEND_FUNCTION_BLOCK"
        $blocks = New-Object System.Collections.ArrayList
        Add-Member -InputObject $blocks ScriptMethod ImportFromDocuments { param($d, $n, $o) [pscustomobject]@{ State = 'Success'; Messages = @(); ImportedBlocks = @([pscustomobject]@{ Name = 'A_1' }) } }
        $script:root = [pscustomobject]@{ BlockGroup = [pscustomobject]@{ Blocks = $blocks; Groups = @() } }
        $r = Invoke-ImportTool ([pscustomobject]@{ kind = 'block'; paths = @('plc\blocks\A.s7dcl') })
        $r.ok | Should Be $false
        $r.items[0].importedAs | Should Be 'A_1'
    }

    It 'keeps the guard of an existing tag table when the file name differs from the name it declares: override crashed TIA' {
        $repo = New-TestRepo
        Write-TagDoc $repo 'Ns_T' 'Ns:T'
        $script:root = New-TagHmi 'Ns:T' @('Ns:T')
        $r = Invoke-TagImport 'Ns_T'
        $r.ok | Should Be $false
        $r.items[0].refused | Should Match "hmi_tag_table 'Ns:T' exists"
        @($script:importCalls).Count | Should Be 0
    }
}

Describe 'Get-DocumentDeclaredName of HMI documents' {
    It 'reads the Name of screens, tag tables and text lists' {
        foreach ($tag in 'Hmi.Screen.Screen', 'Hmi.Tag.TagTable', 'Hmi.TextGraphicList.TextList') {
            $p = Join-Path $TestDrive "$tag.xml"
            Write-TextFile $p "<Document><Engineering version=`"V20`" /><$tag ID=`"0`"><AttributeList><Name>Ns:T</Name></AttributeList></$tag></Document>"
            Get-DocumentDeclaredName $p | Should BeExactly 'Ns:T'
        }
    }
}

Describe 'guards on a file whose name holds wildcard characters' {
    It 'reads an OB in Ns[1].s7dcl: the OB guard is no pass because the path did not glob' {
        $p = Join-Path $TestDrive 'Ns[1].s7dcl'
        [System.IO.File]::WriteAllText($p, "ORGANIZATION_BLOCK `"Ns[1]`"`r`nEND_ORGANIZATION_BLOCK")
        Test-S7dclImportAllowed $p | Should Match 'event class'
    }

    It 'reads the faceplates of Ns[1].xml: the faceplate guard is no pass because the path did not glob' {
        $p = Join-Path $TestDrive 'Screen[1].xml'
        [System.IO.File]::WriteAllText($p, '<Document><FaceplateTypeName>_Library@$@Fp V 1.0.0</FaceplateTypeName></Document>')
        @(Get-FaceplateRefs $p).Count | Should Be 1
    }

    It 'writes a text file below a folder whose name holds wildcard characters' {
        $p = Join-Path $TestDrive 'Ns[1]\sub[2]\a.txt'
        Write-TextFile $p 'x'
        [System.IO.File]::ReadAllText($p) | Should BeExactly 'x'
    }
}

Describe 'one test per special character' {
    foreach ($s in $script:specialCharacters) {
        $label = $s.label
        $name = "Ns$($s.c)Block"
        $safe = ConvertTo-SafeFileName $name
        $s7dcl = 'FUNCTION_BLOCK "' + $name.Replace('"', '""') + '"' + "`r`nEND_FUNCTION_BLOCK"

        It "$label`: exports to a file of its own, in the expected form" {
            $repo = New-TestRepo
            $script:root = [pscustomobject]@{ BlockGroup = [pscustomobject]@{ Blocks = @(New-Block $name); Groups = @() } }
            $r = Invoke-ExportTool ([pscustomobject]@{ kind = 'block'; names = @($name) })
            $r.ok | Should Be $true
            @($r.items[0].files) -join ',' | Should BeExactly "plc\blocks\$safe.s7dcl,plc\blocks\$safe.s7res"
            Read-Repo $repo "plc\blocks\$safe.s7dcl" | Should BeExactly "written by $name"
        }

        It "$label`: reads the name a .s7dcl declares" {
            $p = Join-Path $TestDrive "read_$($label -replace ' ', '_').s7dcl"
            [System.IO.File]::WriteAllText($p, $s7dcl)
            Get-DocumentDeclaredName $p | Should BeExactly $name
        }

        It "$label`: reads the name a SimaticML declares" {
            $p = Join-Path $TestDrive "read_$($label -replace ' ', '_').xml"
            [System.IO.File]::WriteAllText($p, "<Document><SW.Blocks.FB ID=`"0`"><AttributeList><Name>$([System.Security.SecurityElement]::Escape($name))</Name></AttributeList></SW.Blocks.FB></Document>")
            Get-DocumentDeclaredName $p | Should BeExactly $name
        }

        It "$label`: an import finds the existing block by the name its file declares" {
            $repo = New-TestRepo
            $file = Join-Path $repo "plc\blocks\$safe.s7dcl"
            Write-TextFile $file $s7dcl
            $existing = New-Block $name
            $blocks = New-Object System.Collections.ArrayList
            [void]$blocks.Add($existing)
            Add-Member -InputObject $blocks NoteProperty Answer $name
            Add-Member -InputObject $blocks ScriptMethod ImportFromDocuments { param($d, $n, $o)
                $script:importedDocs = $n
                [pscustomobject]@{ State = 'Success'; Messages = @(); ImportedBlocks = @([pscustomobject]@{ Name = $this.Answer }) } }
            $group = [pscustomobject]@{ Name = 'F'; Blocks = $blocks; Groups = @() }
            $groups = New-Object System.Collections.ArrayList
            [void]$groups.Add($group)
            Add-Member -InputObject $groups ScriptMethod Find { param($n) $this | Where-Object { $_.Name -eq $n } | Select-Object -First 1 }
            $script:root = [pscustomobject]@{ BlockGroup = [pscustomobject]@{ Blocks = @(); Groups = $groups } }
            $r = Invoke-ImportTool ([pscustomobject]@{ kind = 'block'; paths = @($file) })
            $r.ok | Should Be $true
            $r.items[0].name | Should BeExactly $name
            $r.items[0].folder | Should Be 'F'
            $script:importedDocs | Should BeExactly $safe
        }

        It "$label`: an import finds the library type by the form of its file name" {
            $dir = Join-Path $TestDrive "lib_$($label -replace ' ', '_')"
            $file = Join-Path $dir "$safe.s7dcl"
            Write-TextFile $file $s7dcl
            $r = Resolve-LibraryTypeFile @{ file = $file; name = $safe } @(@{ name = $name; obj = $null })
            $r.refused | Should BeNullOrEmpty
            $r.name | Should BeExactly $name
        }
    }

    It 'a double quote: a name that holds one has it doubled in a .s7dcl (an assumption until a real export holds one)' {
        $p = Join-Path $TestDrive 'quote.s7dcl'
        [System.IO.File]::WriteAllText($p, "FUNCTION_BLOCK `"a`"`"b`"`r`nEND_FUNCTION_BLOCK")
        Get-DocumentDeclaredName $p | Should BeExactly 'a"b'
    }
}

Describe 'names Windows changes or refuses, as a block and as a folder' {
    foreach ($n in 'Block.', 'Block ', 'NUL', 'CON', 'COM1', 'LPT1', 'AUX', 'PRN') {
        $name = $n
        It "'$name' exports as a block, and its export is found again" {
            $repo = New-TestRepo
            $script:root = [pscustomobject]@{ BlockGroup = [pscustomobject]@{ Blocks = @(New-Block $name); Groups = @() } }
            $r = Invoke-ExportTool ([pscustomobject]@{ kind = 'block'; names = @($name) })
            $r.ok | Should Be $true
            $safe = ConvertTo-SafeFileName $name
            Read-Repo $repo "plc\blocks\$safe.s7dcl" | Should BeExactly "written by $name"
        }

        It "'$name' as a TIA folder holds a screen" {
            $repo = New-TestRepo
            $script:root = [pscustomobject]@{ ScreenFolder = [pscustomobject]@{ Screens = @(); Folders = @(New-Folder $name @(New-XmlObject 'S')) } }
            $r = Invoke-ExportTool ([pscustomobject]@{ kind = 'hmi_screen'; names = @('S') })
            $r.ok | Should Be $true
            Read-Repo $repo "hmi\screens\$(ConvertTo-SafeFileName $name)\S.xml" | Should BeExactly 'written by S'
        }
    }

    It 'gives a device of such a name a folder of a project with several devices' {
        $null = New-TestRepo
        $script:software = @(@{ device = 'NUL'; kind = 'hmi'; software = $null }, @{ device = 'Line.'; kind = 'hmi'; software = $null })
        Get-KindRelDir (Get-ObjectKind 'hmi_screen') 'NUL' | Should Be 'hmi\NUL_\screens'
        Get-KindRelDir (Get-ObjectKind 'hmi_screen') 'Line.' | Should Be 'hmi\Line_\screens'
    }

    It 'still refuses such a name for a repo folder named in a tool argument' {
        (Resolve-RepoFolder $TestDrive 'NUL').refused | Should Match 'device name'
        (Resolve-RepoFolder $TestDrive 'Repo.').refused | Should Match 'dot or space'
    }
}

Describe 'Invoke-WithNotificationGuard' {
    function Initialize-Guard($Portal) {
        $null = New-TestRepo
        $script:Bridge.portal = $Portal
        $script:Bridge.background = $null
        $null = @(Get-PromptLog)
    }

    It 'acknowledges a notification during the call and lists it, as a box must not stall a full export' {
        $portal = New-Object TiaBridgeNames.Portal
        Initialize-Guard $portal
        $note = New-Object TiaBridgeNames.NoteArgs -Property @{ Caption = 'Export'; Text = 'Export Completed (0032:000002)'; Icon = 'Success' }
        $r = Invoke-WithNotificationGuard { $portal.Tell($note); 'done' }
        $r | Should Be 'done'
        $note.IsHandled | Should Be $true
        $log = @(Get-PromptLog)
        $log.Count | Should Be 1
        $log[0].kind | Should Be 'notification'
        $log[0].text | Should Match '0032:000002'
    }

    It 'leaves a confirmation to the person at TIA: a question is theirs to answer' {
        $portal = New-Object TiaBridgeNames.Portal
        Initialize-Guard $portal
        $ask = New-Object TiaBridgeNames.ConfirmArgs -Property @{ Text = 'Replace?' }
        $null = Invoke-WithNotificationGuard { $portal.Ask($ask) }
        $ask.IsHandled | Should Be $false
        @(Get-PromptLog).Count | Should Be 0
    }

    It 'lets go after the call: a box of the person''s own work is theirs' {
        $portal = New-Object TiaBridgeNames.Portal
        Initialize-Guard $portal
        $null = Invoke-WithNotificationGuard { 'done' }
        $note = New-Object TiaBridgeNames.NoteArgs -Property @{ Text = 'Later'; Icon = 'Success' }
        $portal.Tell($note)
        $note.IsHandled | Should Be $false
        @(Get-PromptLog).Count | Should Be 0
    }

    It 'lets go when the call fails' {
        $portal = New-Object TiaBridgeNames.Portal
        Initialize-Guard $portal
        { Invoke-WithNotificationGuard { throw 'export failed' } } | Should Throw 'export failed'
        $note = New-Object TiaBridgeNames.NoteArgs -Property @{ Text = 'Later'; Icon = 'Success' }
        $portal.Tell($note)
        $note.IsHandled | Should Be $false
    }

    It 'adds nothing in a background session, whose guard already answers every prompt' {
        $portal = New-Object TiaBridgeNames.Portal
        Initialize-Guard $portal
        $script:Bridge.background = @{ plain = $true }
        $note = New-Object TiaBridgeNames.NoteArgs -Property @{ Text = 'Not seen here'; Icon = 'Success' }
        $null = Invoke-WithNotificationGuard { $portal.Tell($note) }
        $note.IsHandled | Should Be $false
        $script:Bridge.background = $null
    }

    It 'wraps the full_export tool, and its arguments reach the export' {
        $portal = New-Object TiaBridgeNames.Portal
        Initialize-Guard $portal
        Register-FullExportTool
        $r = Invoke-McpHandler $script:McpTools['full_export'].handler ([pscustomobject]@{ parts = @('nope') })
        $r.refused | Should Match 'Unknown part\(s\): nope'
        $script:McpTools['full_export'].handler.ToString() | Should Match 'Invoke-WithNotificationGuard'
    }

    It 'runs the call when a portal offers no such event, and without a portal' {
        Initialize-Guard (New-Object TiaBridgeNames.NoEvents)
        Invoke-WithNotificationGuard { 'done' } | Should Be 'done'
        $script:Bridge.portal = $null
        Invoke-WithNotificationGuard { 'done' } | Should Be 'done'
    }
}

# ------------------------------------------------------------------ probes: file names, the mirror, the notification guard

function New-Thing([string]$Name) {
    $o = [pscustomobject]@{ Name = $Name }
    $o | Add-Member ScriptMethod Export { param($f, $opt) [System.IO.File]::WriteAllText($f.FullName, "written by $($this.Name)") }
    $o
}
function New-TypeVersion {
    $version = [pscustomobject]@{ VersionNumber = '1.0.0'; IsDefault = $true; State = 'Committed' }
    $version | Add-Member ScriptMethod ExportAsDocuments { param($d, $n, $fmt, $opt)
        if ($script:exportFails) { throw 'export refused' }
        [System.IO.File]::WriteAllText((Join-Path $d.FullName "$n.s7dcl"), 'type Foo'); $null }
    $version
}
function Invoke-FooExport([string]$Repo) {
    Export-LibraryTypeDocuments @{ obj = [pscustomobject]@{ Name = 'Foo'; Versions = @(New-TypeVersion) }; name = 'Foo'; folder = '' } (Join-Path $Repo 'library\types') -Format 'SimaticSD'
}

Describe 'two devices on one device folder' {
    function New-TagPlc([string]$Device) { @{ device = $Device; kind = 'plc'; software = [pscustomobject]@{ TagTableGroup = [pscustomobject]@{ TagTables = @(New-Thing "Tags of $Device"); Groups = @() } } } }

    It 'full_export does not let one device overwrite the other (PLC:1 and PLC_1)' {
        $repo = New-TestRepo
        $script:software = @((New-TagPlc 'PLC:1'), (New-TagPlc 'PLC_1'))
        $part = @{ name = 'plc_tags'; scope = 'plc'; kind = 'plc_tag_table' }
        foreach ($d in $script:software) { Invoke-FullExportKindPart $part $d.software $d.device (New-PartRecord $part $d.device) }
        $files = @(Get-ChildItem -LiteralPath (Join-Path $repo 'plc') -Recurse -File)
        $files.Count | Should Be 2
        @($files | ForEach-Object { [System.IO.File]::ReadAllText($_.FullName) } | Sort-Object) -join ',' | Should Be 'written by Tags of PLC:1,written by Tags of PLC_1'
    }

    It 'knows names that differ only in case share a folder' {
        $null = New-TestRepo
        $script:software = @(@{ device = 'Plc'; kind = 'plc' }, @{ device = 'PLC'; kind = 'plc' })
        (Get-DeviceDir 'plc' 'Plc') | Should Not Be (Get-DeviceDir 'plc' 'PLC')
    }

    It 'gives each the same folder at every call, whatever the order of the devices' {
        $null = New-TestRepo
        $script:software = @(@{ device = 'PLC:1'; kind = 'plc' }, @{ device = 'PLC_1'; kind = 'plc' })
        $a = Get-DeviceDir 'plc' 'PLC:1'
        $script:software = @(@{ device = 'PLC_1'; kind = 'plc' }, @{ device = 'PLC:1'; kind = 'plc' })
        Get-DeviceDir 'plc' 'PLC:1' | Should BeExactly $a
        $a | Should Match '^PLC_1~[0-9a-f]{8}$'
    }

    It 'leaves the folder of a device no other shares' {
        $null = New-TestRepo
        $script:software = @(@{ device = 'PLC:1'; kind = 'plc' }, @{ device = 'PLC:2'; kind = 'plc' })
        Get-DeviceDir 'plc' 'PLC:1' | Should BeExactly 'PLC_1'
    }

    It 'keeps the file parts of both apart: their folders go through the same name' {
        $null = New-TestRepo
        $script:software = @(@{ device = 'PLC:1'; kind = 'plc' }, @{ device = 'PLC_1'; kind = 'plc' })
        $p = Get-FullExportPart 'plc_alarm_texts'
        (Get-PartDir $p 'PLC:1') | Should Not Be (Get-PartDir $p 'PLC_1')
    }

    It 'says so in the result of export and of full_export' {
        $repo = New-TestRepo
        $script:software = @((New-TagPlc 'PLC:1'), (New-TagPlc 'PLC_1'))
        $script:root = $script:software[0].software
        $r = Invoke-ExportTool ([pscustomobject]@{ kind = 'plc_tag_table'; names = @('*'); device = 'PLC:1' })
        $r.folderNote | Should Match "'PLC:1'.*'PLC_1'"
        $r.folderNote | Should Match 'PLC_1~'
        $full = Invoke-FullExportTool ([pscustomobject]@{ parts = @('plc_tags') })
        @($full.deviceFolders).Count | Should Be 2
    }

    It 'says nothing when no device shares a folder' {
        $null = New-TestRepo
        $hmi = New-FakeHmi @(New-XmlObject 'S')
        $script:software = @(@{ device = 'A'; kind = 'hmi'; software = $hmi }, @{ device = 'B'; kind = 'hmi'; software = $hmi })
        $script:root = $hmi
        (Invoke-ExportTool ([pscustomobject]@{ kind = 'hmi_screen'; names = @('S'); device = 'A' })).ContainsKey('folderNote') | Should Be $false
        (Invoke-FullExportTool ([pscustomobject]@{ parts = @('hmi_screens') })).Contains('deviceFolders') | Should Be $false
    }

    It 'gives two open global libraries of one file-safe name two folders' {
        $null = New-TestRepo
        $script:Bridge.portal = [pscustomobject]@{ GlobalLibraries = @([pscustomobject]@{ Name = 'Lib:A' }, [pscustomobject]@{ Name = 'Lib_A' }) }
        $k = Get-ObjectKind 'library_type'
        (Get-KindDir $k '' 'Lib:A') | Should Not Be (Get-KindDir $k '' 'Lib_A')
        $script:Bridge.portal = [pscustomobject]@{ GlobalLibraries = @([pscustomobject]@{ Name = 'Lib:A' }) }
        (Get-KindDir $k '' 'Lib:A') | Should Match 'library\\global\\Lib_A\\types$'
        $script:Bridge.portal = $null
    }
}

Describe 'a library type beside a folder of its name' {
    It 'exporting type Foo keeps the documents of type Bar in folder Foo' {
        $repo = New-TestRepo
        Write-Old $repo 'library\types\Foo\Bar\Bar.s7dcl'
        $r = Invoke-FooExport $repo
        Read-Repo $repo 'library\types\Foo\Bar\Bar.s7dcl' | Should BeExactly 'old'
        Read-Repo $repo 'library\types\Foo\Foo.s7dcl' | Should BeExactly 'type Foo'
        @($r.files).Count | Should Be 1
        $r.ContainsKey('removed') | Should Be $false
    }

    It 'still replaces the files of the type itself, and lists those the new export does not write' {
        $repo = New-TestRepo
        Write-Old $repo 'library\types\Foo\Foo.xml'
        $r = Invoke-FooExport $repo
        Test-Path -LiteralPath (Join-Path $repo 'library\types\Foo\Foo.xml') | Should Be $false
        @($r.removed).Count | Should Be 1
    }

    It 'keeps both when the export fails, and leaves nothing behind' {
        $repo = New-TestRepo
        Write-Old $repo 'library\types\Foo\Bar\Bar.s7dcl'
        Write-Old $repo 'library\types\Foo\Foo.s7dcl'
        $script:exportFails = $true
        try { { Invoke-FooExport $repo } | Should Throw 'export refused' } finally { $script:exportFails = $false }
        Read-Repo $repo 'library\types\Foo\Foo.s7dcl' | Should BeExactly 'old'
        Read-Repo $repo 'library\types\Foo\Bar\Bar.s7dcl' | Should BeExactly 'old'
        @(Get-ChildItem -LiteralPath (Join-Path $repo 'library\types') -Directory | ForEach-Object { $_.Name }) -join ',' | Should Be 'Foo'
    }

    foreach ($sibling in 'Foo.old', 'Foo.partial') {
        $name = $sibling
        It "exporting type Foo keeps a sibling type named $name" {
            $repo = New-TestRepo
            Write-Old $repo "library\types\$name\$name.s7dcl"
            Write-Old $repo 'library\types\Foo\Foo.s7dcl'
            $null = Invoke-FooExport $repo
            Read-Repo $repo "library\types\$name\$name.s7dcl" | Should BeExactly 'old'
            Read-Repo $repo 'library\types\Foo\Foo.s7dcl' | Should BeExactly 'type Foo'
            @(Get-ChildItem -LiteralPath (Join-Path $repo 'library\types') -Directory | ForEach-Object { $_.Name } | Sort-Object) -join ',' | Should Be "Foo,$name"
        }
    }

    It 'refuses Foo.released beside Foo: that is the folder of the comparison export of Foo' {
        $null = New-TestRepo
        $type = { param($n) [pscustomobject]@{ Name = $n; Versions = @(New-TypeVersion) } }
        $script:root = [pscustomobject]@{ TypeFolder = [pscustomobject]@{ Types = @((& $type 'Foo'), (& $type 'Foo.released')); Folders = @() } }
        $r = Invoke-ExportTool ([pscustomobject]@{ kind = 'library_type'; names = @('Foo') })
        $r.items[0].error.type | Should Be 'TiaBridge.NameCollision'
    }

    It 'exporting block X keeps a block folder named X.partial' {
        $repo = New-TestRepo
        Write-Old $repo 'plc\blocks\X.partial\Y.s7dcl'
        $script:root = [pscustomobject]@{ BlockGroup = [pscustomobject]@{ Blocks = @(New-Block 'X'); Groups = @() } }
        (Invoke-ExportTool ([pscustomobject]@{ kind = 'block'; names = @('X') })).ok | Should Be $true
        Read-Repo $repo 'plc\blocks\X.partial\Y.s7dcl' | Should BeExactly 'old'
        @(Get-ChildItem -LiteralPath (Join-Path $repo 'plc\blocks') -Directory | ForEach-Object { $_.Name }) -join ',' | Should Be 'X.partial'
    }

    It 'Move-ExportIntoPlace replaces a folder without touching what is named like its work folders' {
        $d = Join-Path $TestDrive 'move'
        foreach ($p in 'T\old.txt', 'T.old\keep.txt', 'T.partial\keep.txt', 'new\new.txt') { Write-TextFile (Join-Path $d $p) 'x' }
        Move-ExportIntoPlace (Join-Path $d 'new') (Join-Path $d 'T')
        Test-Path -LiteralPath (Join-Path $d 'T\new.txt') | Should Be $true
        Test-Path -LiteralPath (Join-Path $d 'T\old.txt') | Should Be $false
        Test-Path -LiteralPath (Join-Path $d 'T.old\keep.txt') | Should Be $true
        Test-Path -LiteralPath (Join-Path $d 'T.partial\keep.txt') | Should Be $true
        @(Get-ChildItem -LiteralPath $d -Directory | ForEach-Object { $_.Name } | Sort-Object) -join ',' | Should Be 'T,T.old,T.partial'
    }

    It 'Move-ExportIntoPlace refuses to replace a folder holding a git repo, by .git or bare, and keeps it as it was' {
        foreach ($git in 'T\sub\.git\HEAD', 'T\.git', 'T\sub\HEAD') {
            $d = Join-Path $TestDrive ([guid]::NewGuid().ToString('N'))
            foreach ($p in $git, 'T\sub\work.txt', 'T\old.txt', 'new\new.txt') { Write-TextFile (Join-Path $d $p) 'x' }
            if ($git -eq 'T\sub\HEAD') { foreach ($p in 'T\sub\objects', 'T\sub\refs') { New-Item -ItemType Directory -Force -Path (Join-Path $d $p) | Out-Null } }
            { Move-ExportIntoPlace (Join-Path $d 'new') (Join-Path $d 'T') } | Should Throw 'git repo'
            Test-Path -LiteralPath (Join-Path $d $git) | Should Be $true
            Test-Path -LiteralPath (Join-Path $d 'T\sub\work.txt') | Should Be $true
            Test-Path -LiteralPath (Join-Path $d 'T\old.txt') | Should Be $true
            Test-Path -LiteralPath (Join-Path $d 'T\new.txt') | Should Be $false
            Test-Path -LiteralPath (Join-Path $d 'new') | Should Be $false
        }
    }
}

Describe 'the mirror keeps the files of a refused object' {
    function Get-Removed([string]$Dir, [string[]]$Kept) { @(Get-MirrorRemovals $Dir @() $Kept | ForEach-Object { Split-Path -Leaf $_ }) }

    It 'a faceplate type: its version files stay' {
        $d = Join-Path (New-TestRepo) 'library\faceplates'
        [void][System.IO.Directory]::CreateDirectory($d)
        foreach ($f in 'Ns_F_V1.0.0.xml', 'Ns_F.type.json') { [System.IO.File]::WriteAllText((Join-Path $d $f), 'x') }
        (Get-Removed $d @((Join-Path $d 'Ns_F'))).Count | Should Be 0
    }

    It 'a faceplate type: a type whose name only starts like it does not stay for it' {
        $d = Join-Path (New-TestRepo) 'library\faceplates'
        [void][System.IO.Directory]::CreateDirectory($d)
        foreach ($f in 'Ns_F_V1.0.0.xml', 'Ns_F_Valve_V1.0.0.xml') { [System.IO.File]::WriteAllText((Join-Path $d $f), 'x') }
        (Get-Removed $d @((Join-Path $d 'Ns_F'))) -join ',' | Should Be 'Ns_F_Valve_V1.0.0.xml'
    }

    It 'a graphic: its image folder stays' {
        $d = Join-Path (New-TestRepo) 'project\graphics'
        [void][System.IO.Directory]::CreateDirectory((Join-Path $d 'Ns_G files'))
        [System.IO.File]::WriteAllText((Join-Path $d 'Ns_G.xml'), 'x')
        [System.IO.File]::WriteAllText((Join-Path $d 'Ns_G files\en-US.png'), 'x')
        (Get-Removed $d @((Join-Path $d 'Ns_G'))).Count | Should Be 0
    }

    It 'a block: all its files stay' {
        $d = Join-Path (New-TestRepo) 'plc\blocks'
        [void][System.IO.Directory]::CreateDirectory($d)
        foreach ($f in 'Ns_B.s7dcl', 'Ns_B.s7res') { [System.IO.File]::WriteAllText((Join-Path $d $f), 'x') }
        (Get-Removed $d @((Join-Path $d 'Ns_B'))).Count | Should Be 0
    }
}

Describe 'slide-ins whose edge cannot be read' {
    function Invoke-UnreadPart {
        $repo = New-TestRepo
        $script:d = Join-Path $repo 'hmi\slideins'
        Write-Old $repo 'hmi\slideins\.xml'
        $hmi = [pscustomobject]@{ ScreenSlideinFolder = [pscustomobject]@{ ScreenSlideins = @((New-Thing ''), (New-Thing '')) } }
        $script:software = @(@{ device = 'H'; kind = 'hmi'; software = $hmi })
        $part = @{ name = 'hmi_slideins'; scope = 'hmi'; kind = 'hmi_slidein' }
        $script:rec = New-PartRecord $part 'H'
        Invoke-FullExportKindPart $part $hmi 'H' $script:rec
    }

    It 'the file of the last good export stays when all refuse' {
        Invoke-UnreadPart
        @(Get-MirrorRemovals $script:d $script:rec.written $script:rec.kept).Count | Should Be 0
    }

    It 'does not tell the user to rename what cannot be named' {
        Invoke-UnreadPart
        $m = $script:rec.failed[0].error.message
        $m | Should Not Match 'Rename'
        $m | Should Match '\(no name\)'
        $m | Should Match 'no name the bridge can read'
    }

    It 'still says rename one when one of them has a name' {
        $null = New-TestRepo
        $script:root = [pscustomobject]@{ Connections = @((New-XmlObject ''), (New-XmlObject '_')) }
        (Invoke-ExportTool ([pscustomobject]@{ kind = 'hmi_connection'; names = @('*') })).items[0].error.message | Should Match 'Rename'
    }
}

Describe 'names Windows folds together, as the check sees them' {
    foreach ($pair in @(@('Abc', 'ABC'), @("Sp$([char]0xB5)m", "Sp$([char]0x3BC)m"), @("a$([char]0x131)", 'aI'), @("a$([char]0x17F)", 'aS'), @("a$([char]0x3C2)", "a$([char]0x3C3)"), @("Stra$([char]0xDF)e", 'STRASSE'), @("a$([char]0x212A)", 'ak'), @("$([char]0xC4)", "$([char]0xE4)"))) {
        $a = $pair[0]; $b = $pair[1]
        It "file system and check agree on $a / $b" {
            $repo = New-TestRepo
            [System.IO.File]::WriteAllText((Join-Path $repo "$a.xml"), 'x')
            $fsSame = [System.IO.File]::Exists((Join-Path $repo "$b.xml"))
            [System.IO.File]::Delete((Join-Path $repo "$a.xml"))
            $r = Invoke-ScreenExport @((New-XmlObject $a), (New-XmlObject $b)) @('*')
            $r.ok | Should Be (-not $fsSame)
            @($script:exportCalls).Count | Should Be $(if ($fsSame) { 0 } else { 2 })
        }
    }
}

Describe 'names a culture compare takes for one, which NTFS keeps apart' {
    $strasse = "Stra$([char]0xDF)e"

    It 'an import of one does not take the other for the existing object' {
        $repo = New-TestRepo
        Write-TextFile (Join-Path $repo 'hmi\generated\tags\STRASSE.xml') '<Document><Hmi.Tag.TagTable ID="0"><AttributeList><Name>STRASSE</Name></AttributeList></Hmi.Tag.TagTable></Document>'
        $tables = New-Object System.Collections.ArrayList
        [void]$tables.Add([pscustomobject]@{ Name = $strasse; IsKnowHowProtected = $false; ProgrammingLanguage = '' })
        Add-Member -InputObject $tables ScriptMethod Import { param($f, $o) [pscustomobject]@{ Name = 'STRASSE' } }
        $script:root = [pscustomobject]@{ TagFolder = [pscustomobject]@{ TagTables = $tables; Folders = @() } }
        (Invoke-ImportTool ([pscustomobject]@{ kind = 'hmi_tag_table'; paths = @('hmi\generated\tags\STRASSE.xml') })).ok | Should Be $true
    }

    It 'an import still finds an object whose name differs only in case: TIA does not tell them apart' {
        $repo = New-TestRepo
        Write-TextFile (Join-Path $repo 'hmi\generated\tags\ABC.xml') '<Document><Hmi.Tag.TagTable ID="0"><AttributeList><Name>ABC</Name></AttributeList></Hmi.Tag.TagTable></Document>'
        $tables = New-Object System.Collections.ArrayList
        [void]$tables.Add([pscustomobject]@{ Name = 'Abc'; IsKnowHowProtected = $false; ProgrammingLanguage = '' })
        $script:root = [pscustomobject]@{ TagFolder = [pscustomobject]@{ TagTables = $tables; Folders = @() } }
        (Invoke-ImportTool ([pscustomobject]@{ kind = 'hmi_tag_table'; paths = @('hmi\generated\tags\ABC.xml') })).items[0].refused | Should Match 'exists'
    }

    It 'two devices keep their plain folders' {
        $null = New-TestRepo
        $script:software = @(@{ device = $strasse; kind = 'plc' }, @{ device = 'STRASSE'; kind = 'plc' })
        Get-DeviceDir 'plc' 'STRASSE' | Should BeExactly 'STRASSE'
        Get-DeviceDir 'plc' $strasse | Should BeExactly $strasse
    }

    It 'two types of a library change are compared' {
        (Get-ReviewNameClashes @($strasse, 'STRASSE')).Count | Should Be 0
    }
}

Describe 'names Windows treats as a device after the mapping' {
    foreach ($n in 'NUL', 'NUL.txt', 'NUL .txt', 'COM1 .txt', 'CON .a.b', 'AUX. .x', 'nul  ', 'COM0', 'LPT0', 'con.', ' NUL') {
        $name = $n
        It "'$name' + .xml lands in a file" {
            $d = Join-Path $TestDrive ([guid]::NewGuid().ToString('N').Substring(0, 8))
            [void][System.IO.Directory]::CreateDirectory($d)
            [System.IO.File]::WriteAllText((Join-Path $d "$(ConvertTo-SafeFileName $name).xml"), 'x')
            @(Get-ChildItem -LiteralPath $d -File).Count | Should Be 1
        }
    }
}

Describe 'the blanks .NET drops at the end of a path' {
    foreach ($c in 0xA0, 0x85) {
        $code = $c
        It ("U+{0:X4} at the end of a TIA folder does not land on the folder without it" -f $code) {
            $repo = New-TestRepo
            $folder = "F$([char]$code)"
            $script:root = [pscustomobject]@{ ScreenFolder = [pscustomobject]@{ Screens = @(); Folders = @((New-Folder $folder @(New-XmlObject 'S')), (New-Folder 'F' @(New-XmlObject 'S'))) } }
            (Invoke-ExportTool ([pscustomobject]@{ kind = 'hmi_screen'; names = @('*') })).ok | Should Be $true
            Read-Repo $repo 'hmi\screens\F_\S.xml' | Should BeExactly 'written by S'
            Read-Repo $repo 'hmi\screens\F\S.xml' | Should BeExactly 'written by S'
        }
    }
}

Describe 'the mapping of the bridge and of the HMI generator' {
    It 'is one mapping, name by name' {
        if (Get-PythonProblem) { return }
        $names = @('Plain', 'a\b/c:d*e?f"g<h>i|j', "a`tb", "a`nb", 'Line.', 'Line ', 'Line. .', '...', 'a.b c', 'NUL', 'nul', 'COM1', 'LPT9', "COM$([char]0xB9)", "LPT$([char]0xB3)",
                   'CONIN$', 'conout$', 'NUL.txt', 'NUL .txt', 'con.', ' NUL', 'CONSOLE', 'COM10', 'COM0', "F$([char]0xA0)", "F$([char]0x85)", "F$([char]0xA0).", "Stra$([char]0xDF)e", '[x]', '~a')
        $in = Join-Path $TestDrive 'names.json'
        $out = Join-Path $TestDrive 'mapped.json'
        [System.IO.File]::WriteAllText($in, (ConvertTo-Json -InputObject $names))
        $py = Join-Path $TestDrive 'map.py'
        [System.IO.File]::WriteAllText($py, "import json, sys`nsys.path.insert(0, sys.argv[3])`nfrom hmipreview.model import folder_name`nnames = json.load(open(sys.argv[1], encoding='utf-8'))`njson.dump([folder_name(n) for n in names], open(sys.argv[2], 'w', encoding='utf-8'))`n")
        & $script:PythonExe -X utf8 $py $in $out (Join-Path $PSScriptRoot '..\..\TiaHmiGenerator')
        $mapped = @([System.IO.File]::ReadAllText($out) | ConvertFrom-Json)
        $mapped = @($mapped | ForEach-Object { $_ })
        $mapped.Count | Should Be $names.Count
        for ($i = 0; $i -lt $names.Count; $i++) { $mapped[$i] | Should BeExactly (ConvertTo-SafeFileName $names[$i]) }
    }
}

Describe 'the notification guard by the icon of the box' {
    function Initialize-IconGuard {
        $script:portal = New-Object TiaBridgeNames.Portal
        $null = New-TestRepo
        $script:Bridge.portal = $script:portal
        $script:Bridge.background = $null
        $null = @(Get-PromptLog)
    }
    function Send-Note([string]$Icon) {
        $note = New-Object TiaBridgeNames.NoteArgs -Property @{ Text = "A $Icon box"; Icon = $Icon }
        $null = Invoke-WithNotificationGuard { $script:portal.Tell($note) }
        $note
    }

    foreach ($i in 'Success', 'Information') {
        $icon = $i
        It "acknowledges $icon in a window, and lists the icon" {
            Initialize-IconGuard
            (Send-Note $icon).IsHandled | Should Be $true
            $log = @(Get-PromptLog)
            $log[0].icon | Should Be $icon
            $log[0].answer | Should Be 'handled'
        }
    }

    foreach ($i in 'Warning', 'Error', '') {
        $icon = $i
        It "leaves a box with icon '$icon' to the person in a window, and lists it" {
            Initialize-IconGuard
            (Send-Note $icon).IsHandled | Should Be $false
            $log = @(Get-PromptLog)
            $log.Count | Should Be 1
            $log[0].kind | Should Be 'notification'
            $log[0].icon | Should Be $icon
            $log[0].answer | Should Match 'left to the person'
        }
    }

    It 'lists the icon of a background session too, whose guard handles every box as no one can see them' {
        $portal = New-Object TiaBridgeNames.Portal
        $null = @(Get-PromptLog)
        Register-PromptGuard $portal
        $note = New-Object TiaBridgeNames.NoteArgs -Property @{ Text = 'An Error box'; Icon = 'Error' }
        $portal.Tell($note)
        $note.IsHandled | Should Be $true
        @(Get-PromptLog)[0].icon | Should Be 'Error'
    }
}

# ------------------------------------------------------------------ more probes: devices, work folders, the mirror

Describe 'a device or library named in another case, with no real clash' {
    function New-TagDevice([string]$Device) { @{ device = $Device; kind = 'plc'; software = [pscustomobject]@{ TagTableGroup = [pscustomobject]@{ TagTables = @(New-Thing 'T'); Groups = @() } } } }

    It 'plc_1 goes to the folder of PLC_1, as TIA names it' {
        $null = New-TestRepo
        $script:software = @((New-TagDevice 'PLC_1'), (New-TagDevice 'PLC_2'))
        Get-DeviceDir 'plc' 'plc_1' | Should BeExactly 'PLC_1'
    }

    It 'export and import that way use that folder, and no note claims a shared name' {
        $repo = New-TestRepo
        $script:software = @((New-TagDevice 'PLC_1'), (New-TagDevice 'PLC_2'))
        $script:root = $script:software[0].software
        $r = Invoke-ExportTool ([pscustomobject]@{ kind = 'plc_tag_table'; names = @('T'); device = 'plc_1' })
        $r.items[0].files | Should BeExactly 'plc\PLC_1\tags\T.xml'
        $r.ContainsKey('folderNote') | Should Be $false
        Get-KindRelDir (Get-ObjectKind 'plc_tag_table') 'plc_1' | Should BeExactly 'plc\PLC_1\tags'
    }

    It 'a real clash named in another case gets the folder of the device it names, and its note' {
        $null = New-TestRepo
        $script:software = @((New-TagDevice 'PLC:1'), (New-TagDevice 'PLC_1'))
        Get-DeviceDir 'plc' 'plc:1' | Should BeExactly (Get-DeviceDir 'plc' 'PLC:1')
        Get-SharedFolderNote 'Device' 'plc:1' @('PLC:1', 'PLC_1') | Should Match "Device 'PLC:1'.*'PLC_1'"
    }

    It 'lib:a goes to the folder of Lib:A' {
        $null = New-TestRepo
        $script:Bridge.portal = [pscustomobject]@{ GlobalLibraries = @([pscustomobject]@{ Name = 'Lib:A' }, [pscustomobject]@{ Name = 'Other' }) }
        Get-KindDir (Get-ObjectKind 'library_type') '' 'lib:a' | Should Match 'library\\global\\Lib_A\\types$'
        $script:Bridge.portal = $null
    }

    It 'leaves a name in no list as it is: the tool refuses it after' {
        Get-UniqueFolderName 'Nope:1' @('PLC_1', 'PLC_2') | Should BeExactly 'Nope_1'
    }
}

Describe 'a work folder left by a killed bridge' {
    function New-IgnoreRepo {
        $repo = New-TestRepo
        Write-TextFile (Join-Path $repo '.gitignore') $script:RepoGitignore
        Invoke-Git $repo @('init', '-q')
        $repo
    }
    function Test-Ignored([string]$Repo, [string]$Rel) {
        Write-Old $Repo $Rel
        [bool](& git -C $Repo check-ignore -- $Rel.Replace('\', '/'))
    }

    It 'stays out of the project repo, in the shape New-ExportWorkPath gives it' {
        $repo = New-IgnoreRepo
        $work = New-ExportWorkPath (Join-Path $repo 'plc\blocks\Foo')
        Test-Ignored $repo ((Join-Path $work 'Foo.s7dcl').Substring($repo.Length + 1)) | Should Be $true
    }

    It 'a work file too' {
        $repo = New-IgnoreRepo
        $work = New-ExportWorkPath (Join-Path $repo 'hmi\screens\S.xml')
        Test-Ignored $repo ($work.Substring($repo.Length + 1)) | Should Be $true
    }

    It 'a real object''s folder or file is not ignored' {
        $repo = New-IgnoreRepo
        foreach ($rel in 'plc\blocks\X.partial\Y.s7dcl', 'library\types\Foo.partial\Foo.partial.s7dcl', 'plc\blocks\Foo.partial.s7dcl', 'plc\blocks\Foo.bad1.partial\Y.s7dcl') {
            Test-Ignored $repo $rel | Should Be $false
        }
    }

    It 'a repo made before gets the line at connect, once' {
        $root = Join-Path $TestDrive 'ignoreRoot'
        $a = Initialize-ProjectRepo -Root $root -ProjectName 'Old' -ProjectPath 'C:\o.ap20' -PlcDevices @() -HmiDevices @() -BackgroundSource 'C:\o.ap20'
        $gi = Join-Path $a.repo '.gitignore'
        [System.IO.File]::WriteAllText($gi, "archives/`n.tiabridge-session.json`n")
        $null = Initialize-ProjectRepo -Root $root -ProjectName 'Old' -ProjectPath 'C:\o.ap20' -PlcDevices @() -HmiDevices @() -BackgroundSource 'C:\o.ap20'
        $null = Initialize-ProjectRepo -Root $root -ProjectName 'Old' -ProjectPath 'C:\o.ap20' -PlcDevices @() -HmiDevices @() -BackgroundSource 'C:\o.ap20'
        @([regex]::Matches([System.IO.File]::ReadAllText($gi), [regex]::Escape($script:WorkPathIgnore))).Count | Should Be 1
    }
}

Describe 'two software items under one device name in full_export' {
    function New-TwinPlc([string]$Device, [string]$TagTable) { @{ device = $Device; kind = 'plc'; software = [pscustomobject]@{ TagTableGroup = [pscustomobject]@{ TagTables = @(New-Thing $TagTable); Groups = @() } } } }

    It 'writes nothing of that device, at the level of a part too' {
        $repo = New-TestRepo
        $script:software = @((New-TwinPlc 'Station' 'Tags'), (New-TwinPlc 'Station' 'Tags'))
        $part = @{ name = 'plc_tags'; scope = 'plc'; kind = 'plc_tag_table' }
        foreach ($d in $script:software) {
            $rec = New-PartRecord $part $d.device
            Invoke-FullExportKindPart $part $d.software $d.device $rec
            $rec.exported | Should Be 0
            $rec.listError.type | Should Be 'TiaBridge.DeviceNameCollision'
        }
        Test-Path -LiteralPath (Join-Path $repo 'plc') | Should Be $false
    }

    It 'writes no file part of that device' {
        $repo = New-TestRepo
        $script:software = @(@{ device = 'Station'; kind = 'plc' }, @{ device = 'Station'; kind = 'plc' })
        $script:fileRuns = 0
        $part = @{ name = 'x'; scope = 'plc'; dir = 'plc\x'; file = { param($r, $d) $script:fileRuns++; @{} } }
        $rec = New-PartRecord $part 'Station'
        Invoke-FullExportFilePart $part $null 'Station' $rec
        $script:fileRuns | Should Be 0
        $rec.listError.type | Should Be 'TiaBridge.DeviceNameCollision'
    }

    It 'says so once for the device, is not ok, keeps its files and exports the other devices' {
        $repo = New-TestRepo
        foreach ($f in 'plc\Station\tags\Tags.xml', 'plc\Other\tags\Gone.xml') { Write-Old $repo $f }
        Save-TestRepo $repo
        $script:software = @((New-TwinPlc 'Station' 'Tags'), (New-TwinPlc 'Station' 'Tags'), (New-TwinPlc 'Other' 'OtherTags'))
        $r = Invoke-FullExportTool ([pscustomobject]@{ parts = @('plc_tags') })
        $r.ok | Should Be $false
        $r.exported | Should Be 1
        @($r.failed).Count | Should Be 1
        $r.failed[0] | Should Match "^Station: TiaBridge.DeviceNameCollision: .*'Station'"
        $r.failed[0] | Should Not Match 'Rename'
        Read-Repo $repo 'plc\Station\tags\Tags.xml' | Should BeExactly 'old'
        Read-Repo $repo 'plc\Other\tags\OtherTags.xml' | Should BeExactly 'written by OtherTags'
        @($r.removed) -join ',' | Should Be 'plc\Other\tags\Gone.xml'
        ($r.parts -join '|') | Should Match 'plc_tags@Station: .*refused'
    }

    It 'does not call two devices of one name in two kinds a collision' {
        $null = New-TestRepo
        $script:software = @(@{ device = 'Station'; kind = 'plc' }, @{ device = 'Station'; kind = 'hmi' })
        Get-DeviceNameRefusal @{ scope = 'plc' } 'Station' | Should BeNullOrEmpty
    }

    It 'does not call names differing in case one device: each has its marked folder' {
        $null = New-TestRepo
        $script:software = @(@{ device = 'Station'; kind = 'plc' }, @{ device = 'STATION'; kind = 'plc' })
        Get-DeviceNameRefusal @{ scope = 'plc' } 'Station' | Should BeNullOrEmpty
    }
}

Describe 'the mirror keeps the object, brackets in its name too, not its neighbours' {
    It 'exporting Foo[1] keeps folder Foo[1]\Bar[2] and its file' {
        $repo = New-TestRepo
        Write-Old $repo 'library\types\Foo[1]\Bar[2]\Bar[2].s7dcl'
        $r = Export-LibraryTypeDocuments @{ obj = [pscustomobject]@{ Name = 'Foo[1]'; Versions = @(New-TypeVersion) }; name = 'Foo[1]'; folder = '' } (Join-Path $repo 'library\types') -Format 'SimaticSD'
        Read-Repo $repo 'library\types\Foo[1]\Bar[2]\Bar[2].s7dcl' | Should BeExactly 'old'
        [System.IO.File]::Exists((Join-Path $repo 'library\types\Foo[1]\Foo[1].s7dcl')) | Should Be $true
        @($r.files).Count | Should Be 1
        @(Get-ChildItem -LiteralPath (Join-Path $repo 'library\types') -Directory).Count | Should Be 1
    }

    It 'Test-MirrorKept holds the object, not its neighbours' {
        Test-MirrorKept 'C:\r\a\Foo.xml' 'C:\r\a\Foo' | Should Be $true
        Test-MirrorKept 'C:\r\a\Foo_V1.0.0.xml' 'C:\r\a\Foo' | Should Be $true
        Test-MirrorKept 'C:\r\a\Foo files\x.png' 'C:\r\a\Foo' | Should Be $true
        Test-MirrorKept 'C:\r\a\Foobar.xml' 'C:\r\a\Foo' | Should Be $false
        Test-MirrorKept 'C:\r\a\Foo_Va.xml' 'C:\r\a\Foo' | Should Be $false
        Test-MirrorKept 'C:\r\a[1]\Foo_V2.xml' 'C:\r\a[1]\Foo' | Should Be $true
    }
}
