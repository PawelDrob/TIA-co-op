$here = Split-Path -Parent $MyInvocation.MyCommand.Path
foreach ($f in 'Mcp.ps1', 'Tia.ps1', 'Repo.ps1', 'Rules.ps1', 'Guards.ps1', 'Bridge.ps1', 'Tools\Objects.ps1', 'Tools\Plc.ps1', 'Tools\Hmi.ps1',
               'Tools\Library.ps1', 'Tools\FullExport.ps1') { . (Join-Path $here "..\$f") }

# full_export skips the blocks, DBs, data types and PLC tag tables TIA says it has not changed since the last export
# (Tools\ExportRecord.ps1). Each reason to export everything, and each reason to export one object, has a test here.

if (-not ('Siemens.Engineering.ExportOptions' -as [type])) {
    Add-Type -TypeDefinition 'namespace Siemens.Engineering { [System.Flags] public enum ExportOptions { None = 0, WithDefaults = 1, WithReadOnly = 2 } }'
}

if (-not ('FakeSiemens.NonRecoverableException' -as [type])) {
    Add-Type -TypeDefinition 'namespace FakeSiemens { public class NonRecoverableException : System.Exception { public NonRecoverableException(string m) : base(m) { } } }'
}

function Test-TiaAlive { $true }
function Get-LibraryLink { $null }
function Get-TiaVersionText { $script:tiaVersion }

# A fake PLC object: its dates and other attributes as properties, its export writing what TIA holds of it (text).
# Blocks, DBs and data types export .s7dcl and .s7res; a tag table SimaticML. exports counts its export calls.
function New-PlcObject([string]$Name, [string]$Text = '', [hashtable]$More = @{}) {
    $o = [pscustomobject]@{ Name = $Name; text = $(if ($Text) { $Text } else { "code of $Name" }); exports = 0
                            ModifiedDate = [datetime]::new(2026, 10, 8, 12, 0, 0, [DateTimeKind]::Utc)
                            InterfaceModifiedDate = [datetime]::new(2026, 10, 8, 12, 0, 0, [DateTimeKind]::Utc)
                            IsConsistent = $true; IsKnowHowProtected = $false }
    foreach ($k in $More.Keys) { $o | Add-Member NoteProperty $k $More[$k] -Force }
    $o | Add-Member ScriptMethod ExportAsDocuments { param($d, $n)
        $this.exports++
        [System.IO.File]::WriteAllText((Join-Path $d.FullName "$n.s7dcl"), $this.text)
        [System.IO.File]::WriteAllText((Join-Path $d.FullName "$n.s7res"), "texts of $($this.Name)")
        [pscustomobject]@{ State = 'Success'; Messages = @() } }
    $o | Add-Member ScriptMethod Export { param($f, $opt) $this.exports++; [System.IO.File]::WriteAllText($f.FullName, $this.text) }
    $o
}
function New-TagTable([string]$Name) {
    $t = New-PlcObject $Name "<tags of $Name/>"
    $t.PSObject.Properties.Remove('ModifiedDate'); $t.PSObject.Properties.Remove('InterfaceModifiedDate'); $t.PSObject.Properties.Remove('IsConsistent')
    $t | Add-Member NoteProperty ModifiedTimeStamp ([datetime]::new(2026, 10, 8, 12, 0, 0, [DateTimeKind]::Utc))
    $t
}
function New-Group([object[]]$Items, [string]$Property, [object[]]$Groups = @()) {
    $g = [pscustomobject]@{ Name = ''; Groups = $Groups }
    $g | Add-Member NoteProperty $Property $Items
    $g
}
# Gives a fake object TIA's GetAttributes and GetAttributeInfos [PROBE] (2026-11-19): GetAttributes answers a list of names
# in one call and refuses the whole call when the object lacks one of them. It offers its properties and attrs (the names
# only GetAttribute reads); Lacks: properties it does not offer as attributes. calls counts the calls of each. Single: no
# GetAttributes, as the objects the bridge read one name at a time.
function Add-AttributeMethods($Obj, [string[]]$Lacks = @(), [switch]$Single) {
    if (-not $Obj.PSObject.Properties['attrs']) { $Obj | Add-Member NoteProperty attrs @{} }
    $Obj | Add-Member NoteProperty lacks $Lacks -Force
    $Obj | Add-Member NoteProperty calls @{ GetAttributes = 0; GetAttributeInfos = 0; GetAttribute = 0 } -Force
    $Obj | Add-Member ScriptMethod Offered { @(@($this.PSObject.Properties | Where-Object { $_.MemberType -eq 'NoteProperty' -and $this.lacks -notcontains $_.Name } | ForEach-Object { $_.Name }) + @($this.attrs.Keys)) } -Force
    $Obj | Add-Member ScriptMethod GetAttributeInfos { $this.calls.GetAttributeInfos++; @($this.Offered() | ForEach-Object { [pscustomobject]@{ Name = $_ } }) } -Force
    $Obj | Add-Member ScriptMethod GetAttribute { param($Name)
        $this.calls.GetAttribute++
        if ($this.Offered() -notcontains $Name) { throw "'$Name' is not supported by type 'Fake'." }
        if ($this.attrs.ContainsKey($Name)) { $this.attrs[$Name] } else { $this.$Name } } -Force
    if ($Single) { return }
    $Obj | Add-Member ScriptMethod GetAttributes { param($Names)
        $this.calls.GetAttributes++
        $offered = $this.Offered()
        foreach ($n in $Names) { if ($offered -notcontains $n) { throw "'$n' is not supported by type 'Fake'." } }
        , @(foreach ($n in $Names) { if ($this.attrs.ContainsKey($n)) { $this.attrs[$n] } else { $this.$n } }) } -Force
}
function New-Ending { [System.Management.Automation.MethodInvocationException]::new('outer', [FakeSiemens.NonRecoverableException]::new('Unexpected exception')) }
# Moves an object's date on, as an edit in TIA does.
function Step-Date($Obj, [string]$Attribute = 'ModifiedDate') { $Obj.$Attribute = $Obj.$Attribute.AddSeconds(1) }

# A fresh PLC with blocks FB1, FC1, instance DB IDB1 of FB1, global DB DB1, data type UDT1 and tag table Tags; the repo
# exported once and committed. SimaticMl: the objects whose SD export TIA refuses, so they are written as SimaticML.
function Initialize-SkipTest([string]$Name, [string[]]$SimaticMl = @()) {
    $script:repo = Join-Path $TestDrive $Name
    Initialize-BridgeContext @{ maxResponseChars = 20000 }
    Set-BridgeProject -Name 'P' -Path 'C:\P.ap20' -Repo $script:repo
    $script:tiaVersion = '2000.7.201.2'
    $script:o = @{
        FB1 = New-PlcObject 'FB1'; FC1 = New-PlcObject 'FC1'
        IDB1 = New-PlcObject 'IDB1' '' @{ InstanceOfName = 'FB1' }; DB1 = New-PlcObject 'DB1'
        UDT1 = New-PlcObject 'UDT1'; Tags = New-TagTable 'Tags'
    }
    foreach ($n in $SimaticMl) {
        $script:o[$n] | Add-Member ScriptMethod ExportAsDocuments { param($d, $f) [pscustomobject]@{ State = 'Failure'; Messages = @([pscustomobject]@{ State = 'Error'; Description = 'refused' }) } } -Force
    }
    $script:sub = New-Group @() 'Blocks'
    $script:sub.Name = 'Sub'
    $script:blocks = New-Group @($script:o.FB1, $script:o.FC1, $script:o.IDB1, $script:o.DB1) 'Blocks' @($script:sub)
    $script:plc = [pscustomobject]@{ BlockGroup = $script:blocks; TypeGroup = (New-Group @($script:o.UDT1) 'Types'); TagTableGroup = (New-Group @($script:o.Tags) 'TagTables') }
    $script:software = @(@{ device = 'PLC_1'; kind = 'plc'; software = $script:plc })
    $en = [System.Globalization.CultureInfo]::GetCultureInfo('en-US')
    $script:project = [pscustomobject]@{ Name = 'P'; ProjectLibrary = $null
                                         LanguageSettings = [pscustomobject]@{ ReferenceLanguage = [pscustomobject]@{ Culture = $en }; ActiveLanguages = @([pscustomobject]@{ Culture = $en }) } }
    $null = Invoke-FullExportTool $script:parts
    Save-SkipRepo
    Reset-Exports
}
function Save-SkipRepo {
    if (-not (Test-Path (Join-Path $script:repo '.git'))) { Invoke-Git $script:repo @('init', '-q') }
    Invoke-Git $script:repo @('add', '-A')
    Invoke-Git $script:repo @('commit', '-q', '--allow-empty', '-m', 'test')
}
# The names of the objects the last export called TIA for, sorted; not the tag table, which every run exports once to
# compare it (Get-TagTableDifference).
function Get-Exported { (@($script:o.Keys | Where-Object { $_ -ne 'Tags' -and $script:o[$_].exports } | Sort-Object) -join ',') }
function Reset-Exports { foreach ($x in $script:o.Values) { $x.exports = 0 } }
# The files under plc\ with their content: what two exports must leave the same.
function Get-PlcFiles {
    $root = Join-Path $script:repo 'plc'
    (@(Get-ChildItem -LiteralPath $root -File -Recurse -Force | Where-Object { $_.Name -ne '.gitkeep' } | Sort-Object FullName |
        ForEach-Object { "$($_.FullName.Substring($root.Length + 1))=$([System.IO.File]::ReadAllText($_.FullName))" }) -join "`n")
}
# The default export, then full: true on the same TIA, which finds nothing to change or remove. Returns the default's result.
function Assert-SameAsFull {
    $r = Invoke-FullExportTool $script:parts
    $r.ok | Should Be $true
    $after = Get-PlcFiles
    $exported = Get-Exported
    $f = Invoke-FullExportTool ([pscustomobject]@{ parts = $script:parts.parts; full = $true })
    $f.ok | Should Be $true
    $f.exportedAll | Should Be 'full: true'
    Get-PlcFiles | Should Be $after
    @($f.removed).Count | Should Be 0
    $script:exportedByDefault = $exported
    $r
}

$script:parts = [pscustomobject]@{ parts = @('blocks', 'dbs', 'types', 'plc_tags') }

Describe 'full_export skips what TIA has not changed' {
    Mock Get-TiaSoftwareList { $script:software }
    Mock Get-TiaProject { $script:project }
    Mock Test-IsDataBlock { $Block.Name -like '*DB*' }

    It 'exports nothing a second time when nothing changed, and leaves the files as they are' {
        Initialize-SkipTest 'nothing'
        $r = Invoke-FullExportTool $script:parts
        $r.ok | Should Be $true
        Get-Exported | Should Be ''
        $r.exported | Should Be 0
        $r.skipped | Should Be 6
        $r.removedCount | Should Be 0
        Get-Content (Join-Path $script:repo 'plc\blocks\FB1.s7dcl') | Should Be 'code of FB1'
        ($r.parts -join '|') | Should Match 'blocks@PLC_1: 0/2, [\d.]+ s, 2 skipped'
    }

    It 'skips again after a run that skipped: the record is written anew' {
        Initialize-SkipTest 'again'
        $first = Invoke-FullExportTool $script:parts
        $first.skipped | Should Be 6
        Reset-Exports
        $r = Invoke-FullExportTool $script:parts
        $r.skipped | Should Be 6
        Get-Exported | Should Be ''
    }

    It 'says per part why it exported, and marks a skipped object in its progress line' {
        Initialize-SkipTest 'progress'
        Step-Date $script:o.FC1
        Mock Write-BridgeProgress { }
        $r = Invoke-FullExportTool $script:parts
        @($r.details | Where-Object { $_.part -eq 'blocks' })[0].why['changed in TIA'] | Should Be 1
        Assert-MockCalled Write-BridgeProgress -Scope It -ParameterFilter { $Fields.event -eq 'object' -and $Fields.name -eq 'FB1' -and $Fields.skipped }
        Assert-MockCalled Write-BridgeProgress -Scope It -Times 0 -ParameterFilter { $Fields.event -eq 'object' -and $Fields.name -eq 'FC1' -and $Fields.skipped }
    }

    It 'times the plan apart: the values read of TIA, the record, its files, the tag table''s export for the compare' {
        Initialize-SkipTest 'times'
        Step-Date $script:o.FC1
        $t = (Invoke-FullExportTool $script:parts).times
        foreach ($s in 'tia_list', 'tia_state', 'record_read', 'record_files', 'record_compare', 'tia_export_tag_table', 'compare', 'other') { $t.plan.steps.Contains($s) | Should Be $true }
        $t.plan.steps.tia_state.n | Should Be 6
        $t.plan.steps.tia_export_tag_table.n | Should Be 1
        $blocks = $t.parts | Where-Object { $_.part -eq 'blocks' }
        "$($blocks.steps.tia_export_s7dcl.n) $($blocks.steps.record.n)" | Should Be '1 2'
        @($blocks.slowest | Where-Object { $_.skipped } | ForEach-Object { $_.name }) | Should Be 'FB1'
        @($blocks.slowest | Where-Object { -not $_.skipped } | ForEach-Object { $_.name }) | Should Be 'FC1'
        ($t.once.steps.Keys -contains 'record_save') | Should Be $true
    }
}

Describe 'full_export exports everything when the record cannot be used' {
    Mock Get-TiaSoftwareList { $script:software }
    Mock Get-TiaProject { $script:project }
    Mock Test-IsDataBlock { $Block.Name -like '*DB*' }

    $cases = @(
        @{ why = 'full: true'; make = { $script:parts2 = [pscustomobject]@{ parts = $script:parts.parts; full = $true } }; reason = '^full: true$' }
        @{ why = 'no record'; make = { Remove-Item (Join-Path $script:repo '.tiabridge-export.json') }; reason = '^no record yet' }
        @{ why = 'a record that does not read'; make = { [System.IO.File]::WriteAllText((Join-Path $script:repo '.tiabridge-export.json'), '{ not json') }; reason = '^the record does not read' }
        @{ why = 'a record of another form'; make = {
                $f = Join-Path $script:repo '.tiabridge-export.json'
                [System.IO.File]::WriteAllText($f, ([System.IO.File]::ReadAllText($f) -replace '"form":1', '"form":0')) }
           reason = 'another form' }
        @{ why = 'another project'; make = { Set-BridgeProject -Name 'P' -Path 'C:\Other\P.ap20' -Repo $script:repo }; reason = 'another project \(C:\\P\.ap20\)' }
        @{ why = 'another TIA version'; make = { $script:tiaVersion = '2000.8.0.0' }; reason = 'written by TIA 2000\.7\.201\.2, this is 2000\.8\.0\.0' }
        @{ why = 'a TIA version that does not read'; make = { $script:tiaVersion = '' }; reason = 'version of TIA cannot be read'; stays = $true }
        @{ why = 'other project languages'; make = {
                $de = [System.Globalization.CultureInfo]::GetCultureInfo('de-DE')
                $script:project.LanguageSettings.ActiveLanguages = @($script:project.LanguageSettings.ActiveLanguages) + @([pscustomobject]@{ Culture = $de }) }
           reason = 'languages changed' }
        @{ why = 'another PLC device'; make = {
                $two = [pscustomobject]@{ BlockGroup = (New-Group @() 'Blocks'); TypeGroup = (New-Group @() 'Types'); TagTableGroup = (New-Group @() 'TagTables') }
                $script:software = @($script:software) + @(@{ device = 'PLC_2'; kind = 'plc'; software = $two }) }
           reason = 'PLC devices differ' }
        @{ why = 'a bridge with other code'; make = { $script:BridgeCodeHash = 'other' }; reason = "bridge's code changed" }
        @{ why = 'a bridge with other code, the next run back on this code'; make = { $script:BridgeCodeHash = 'other' }; reason = "bridge's code changed"; back = $true; stays = $true }
    )
    foreach ($c in $cases) {
        It "exports everything, with the reason, for $($c.why)" {
            Initialize-SkipTest 'all'
            $script:parts2 = $script:parts
            & $c.make
            try {
                $r = Invoke-FullExportTool $script:parts2
                $r.ok | Should Be $true
                $r.skipped | Should Be 0
                Get-Exported | Should Be 'DB1,FB1,FC1,IDB1,UDT1'
                $r.exportedAll | Should Match $c.reason
                # the record it wrote holds for the next export, unless what differed stays unknown or changes back
                if ($c.back) { $script:BridgeCodeHash = $null }
                Reset-Exports
                (Invoke-FullExportTool $script:parts).skipped | Should Be $(if ($c.stays) { 0 } else { 6 })
            }
            finally { $script:BridgeCodeHash = $null }
        }
    }

    Context 'what TIA says does not read' {
    It 'exports everything when what TIA says of the objects does not read, and keeps the record' {
        Initialize-SkipTest 'plan-fails'
        $f = Join-Path $script:repo '.tiabridge-export.json'
        $before = [System.IO.File]::ReadAllText($f)
        Mock Read-ExportState { throw 'busy' }
        $r = Invoke-FullExportTool $script:parts
        $r.exportedAll | Should Match '^what TIA says of the objects did not read: busy'
        $r.skipped | Should Be 0
        Get-Exported | Should Be 'DB1,FB1,FC1,IDB1,UDT1'
        [System.IO.File]::ReadAllText($f) | Should Be $before
    }
    }

    It 'binds a background session to the source it copied, not to its copy' {
        Initialize-SkipTest 'background'
        $script:Bridge.background = @{ source = 'C:\P.ap20'; plain = $false; session = (New-SessionState) }
        Set-BridgeProject -Name 'P' -Path 'C:\Temp\copy-1\P.ap20' -Repo $script:repo
        try { (Invoke-FullExportTool $script:parts).skipped | Should Be 6 }
        finally { $script:Bridge.background = $null }
    }

    It 'keeps no record in a plain export folder and exports everything there' {
        Initialize-SkipTest 'plain'
        $script:Bridge.background = @{ source = 'C:\P.ap20'; plain = $true; session = (New-SessionState) }
        try {
            $r = Invoke-FullExportTool $script:parts
            $r.skipped | Should Be 0
            $r.exportedAll | Should Match 'plain export folder'
        }
        finally { $script:Bridge.background = $null }
    }
}

Describe 'full_export exports every object of a PLC after a change there that may change the files of others' {
    Mock Get-TiaSoftwareList { $script:software }
    Mock Get-TiaProject { $script:project }
    Mock Test-IsDataBlock { $Block.Name -like '*DB*' }

    It 'a block added' {
        Initialize-SkipTest 'added'
        $script:o.FC2 = New-PlcObject 'FC2'
        $script:blocks.Blocks = @($script:blocks.Blocks) + @($script:o.FC2)
        $r = Assert-SameAsFull
        $r.exportedAllOf | Should Be 'PLC_1: objects added, deleted or renamed (+block|FC2)'
        Test-Path (Join-Path $script:repo 'plc\blocks\FC2.s7dcl') | Should Be $true
    }

    It 'a block deleted: its files are removed as by full: true' {
        Initialize-SkipTest 'deleted'
        $script:blocks.Blocks = @($script:blocks.Blocks | Where-Object { $_.Name -ne 'FC1' })
        $r = Assert-SameAsFull
        $r.exportedAllOf | Should Be 'PLC_1: objects added, deleted or renamed (-block|FC1)'
        (@($r.removed) | Sort-Object) -join '|' | Should Be 'plc\blocks\FC1.s7dcl|plc\blocks\FC1.s7res'
    }

    It 'a block renamed' {
        Initialize-SkipTest 'renamed'
        $script:o.FC1.Name = 'FC9'; Step-Date $script:o.FC1
        $r = Assert-SameAsFull
        $r.exportedAllOf | Should Be 'PLC_1: objects added, deleted or renamed (+block|FC9, -block|FC1)'
        Test-Path (Join-Path $script:repo 'plc\blocks\FC1.s7dcl') | Should Be $false
    }

    It 'a block renamed only in case: others name it, and PowerShell compares names without case' {
        Initialize-SkipTest 'case'
        $script:o.FC1.Name = 'fc1'; Step-Date $script:o.FC1
        $script:o.FB1.text = 'FB1 calling fc1'
        $r = Assert-SameAsFull
        $r.exportedAllOf | Should Be 'PLC_1: objects added, deleted or renamed (+block|fc1, -block|FC1)'
    }

    It 'a data type changed only in the case of a value' {
        Initialize-SkipTest 'value-case'
        $script:o.UDT1 | Add-Member NoteProperty IsKnowHowProtected 'false' -Force
        $null = Invoke-FullExportTool $script:parts
        Reset-Exports
        $script:o.UDT1.IsKnowHowProtected = 'False'
        $r = Invoke-FullExportTool $script:parts
        $r.exportedAllOf | Should Be 'PLC_1: the data type UDT1 changed'
    }

    It 'a data type changed, its users consistent (a default value): they may hold its members' {
        Initialize-SkipTest 'udt'
        $script:o.UDT1.text = 'UDT1 with another default'; Step-Date $script:o.UDT1; Step-Date $script:o.UDT1 'InterfaceModifiedDate'
        $script:o.DB1.text = 'DB1 without the start value the new default makes the same'
        $r = Assert-SameAsFull
        $r.exportedAllOf | Should Be 'PLC_1: the data type UDT1 changed'
        $script:exportedByDefault | Should Be 'DB1,FB1,FC1,IDB1,UDT1'
    }

    It 'a tag table whose file is not in the repo' {
        Initialize-SkipTest 'tag-file-gone'
        Remove-Item (Join-Path $script:repo 'plc\tags\Tags.xml')
        $r = Assert-SameAsFull
        $r.exportedAllOf | Should Be 'PLC_1: the tag table Tags changed: its file is not in the repo'
    }


    It 'a tag table changed' {
        Initialize-SkipTest 'tags'
        Step-Date $script:o.Tags 'ModifiedTimeStamp'
        $script:o.FC1.text = 'FC1 with the renamed tag'
        $r = Assert-SameAsFull
        $r.exportedAllOf | Should Be 'PLC_1: the tag table Tags changed'
    }

    It 'a tag table whose export changed with no date of it moving (a tag renamed through Openness)' {
        Initialize-SkipTest 'tag-rename'
        $script:o.Tags.text = '<tags of Tags, one renamed/>'
        $r = Assert-SameAsFull
        $r.exportedAllOf | Should Be 'PLC_1: the tag table Tags changed: its export differs from its file in the repo'
        Get-Content (Join-Path $script:repo 'plc\tags\Tags.xml') | Should Be '<tags of Tags, one renamed/>'
    }

    It 'a tag table whose export for the compare fails' {
        Initialize-SkipTest 'tag-compare-fails'
        $script:o.Tags | Add-Member NoteProperty failOnce $true
        $script:o.Tags | Add-Member ScriptMethod Export { param($f, $opt) if ($this.failOnce) { $this.failOnce = $false; throw 'busy' }; $this.exports++; [System.IO.File]::WriteAllText($f.FullName, $this.text) } -Force
        $r = Invoke-FullExportTool $script:parts
        $r.exportedAllOf | Should Match '^PLC_1: the tag table Tags changed: its export for the compare failed \(.*busy'
        $r.skipped | Should Be 0
    }


    It 'a PLC the record holds nothing of' {
        Initialize-SkipTest 'nothing-of-plc'
        $f = Join-Path $script:repo '.tiabridge-export.json'
        [System.IO.File]::WriteAllText($f, ([System.IO.File]::ReadAllText($f) -replace '"devices":\{"PLC_1":', '"devices":{"PLC_0":'))
        $r = Invoke-FullExportTool $script:parts
        $r.exportedAllOf | Should Be 'PLC_1: the record holds nothing of PLC_1'
        $r.skipped | Should Be 0
    }
}

Describe 'full_export exports one object when' {
    Mock Get-TiaSoftwareList { $script:software }
    Mock Get-TiaProject { $script:project }
    Mock Test-IsDataBlock { $Block.Name -like '*DB*' }

    It 'TIA moved one of its dates on' {
        Initialize-SkipTest 'date'
        $script:o.FC1.text = 'FC1 edited'; Step-Date $script:o.FC1
        $r = Assert-SameAsFull
        $script:exportedByDefault | Should Be 'FC1'
        $r.exported | Should Be 1
        $r.skipped | Should Be 5
        $r.exportedAll | Should BeNullOrEmpty
        $r.exportedAllOf | Should BeNullOrEmpty
    }

    It 'a date reads older than the record (closed without saving after an import)' {
        Initialize-SkipTest 'older'
        $script:o.FC1.ModifiedDate = $script:o.FC1.ModifiedDate.AddDays(-1)
        $null = Invoke-FullExportTool $script:parts
        Get-Exported | Should Be 'FC1'
    }

    It 'another value of it changed, its dates not (a number)' {
        Initialize-SkipTest 'number'
        $script:o.FC1 | Add-Member NoteProperty Number 7
        $null = Invoke-FullExportTool $script:parts
        Get-Exported | Should Be 'FC1'
    }

    It 'a header value of it changed, its dates not (its version, which its file holds)' {
        Initialize-SkipTest 'header'
        $script:o.FC1 | Add-Member NoteProperty HeaderVersion '0.1'
        $null = Invoke-FullExportTool $script:parts
        Reset-Exports
        $script:o.FC1.HeaderVersion = '0.2'
        $null = Invoke-FullExportTool $script:parts
        Get-Exported | Should Be 'FC1'
    }

    It 'its IEC check changed, its dates not: a value only GetAttribute reads, where TIA names it' {
        Initialize-SkipTest 'iec'
        # as TIA: no .NET property, the attribute infos name it, GetAttribute reads it; FB1 is an F-block naming only the IEC check
        foreach ($b in $script:o.FC1, $script:o.FB1) {
            $b | Add-Member NoteProperty attrs @{ IsIECCheckEnabled = $false }
            $b | Add-Member ScriptMethod GetAttributeInfos { @($this.attrs.Keys | ForEach-Object { [pscustomobject]@{ Name = $_ } }) }
            $b | Add-Member ScriptMethod GetAttribute { param($n) if (-not $this.attrs.ContainsKey($n)) { throw "'$n' is not supported" }; $this.attrs[$n] }
        }
        $script:o.FC1.attrs.SetENOAutomatically = $false
        $null = Invoke-FullExportTool $script:parts
        Reset-Exports
        $null = Invoke-FullExportTool $script:parts
        Get-Exported | Should Be ''
        $script:o.FC1.attrs.IsIECCheckEnabled = $true
        $r = Invoke-FullExportTool $script:parts
        Get-Exported | Should Be 'FC1'
        @($r.details | Where-Object { $_.part -eq 'blocks' })[0].why['changed in TIA'] | Should Be 1
        Reset-Exports
        $script:o.FC1.attrs.SetENOAutomatically = $true
        $null = Invoke-FullExportTool $script:parts
        Get-Exported | Should Be 'FC1'
    }

    It 'it moved to another folder: its old files go as by full: true' {
        Initialize-SkipTest 'moved'
        $script:blocks.Blocks = @($script:blocks.Blocks | Where-Object { $_.Name -ne 'FC1' })
        $script:sub.Blocks = @($script:o.FC1)
        $r = Assert-SameAsFull
        $script:exportedByDefault | Should Be 'FC1'
        (@($r.removed) | Sort-Object) -join '|' | Should Be 'plc\blocks\FC1.s7dcl|plc\blocks\FC1.s7res'
        Test-Path (Join-Path $script:repo 'plc\blocks\Sub\FC1.s7dcl') | Should Be $true
        @($r.details | Where-Object { $_.part -eq 'blocks' })[0].why['moved to another folder'] | Should Be 1
    }

    It 'TIA holds it not consistent' {
        Initialize-SkipTest 'inconsistent'
        $script:o.FC1.IsConsistent = $false
        $null = Invoke-FullExportTool $script:parts
        Reset-Exports
        $null = Invoke-FullExportTool $script:parts
        Get-Exported | Should Be 'FC1'
    }

    It 'a file of it was edited in the repo' {
        Initialize-SkipTest 'edited'
        [System.IO.File]::WriteAllText((Join-Path $script:repo 'plc\blocks\FC1.s7res'), 'edited by hand')
        $r = Assert-SameAsFull
        $script:exportedByDefault | Should Be 'FC1'
        Get-Content (Join-Path $script:repo 'plc\blocks\FC1.s7res') | Should Be 'texts of FC1'
        @(@($r.details | Where-Object { $_.part -eq 'blocks' })[0].why.Keys) | Should Be 'plc\blocks\FC1.s7res was changed in the repo'
    }

    It 'a file of it was removed from the repo' {
        Initialize-SkipTest 'removed'
        Remove-Item (Join-Path $script:repo 'plc\types\UDT1.s7dcl')
        $null = Assert-SameAsFull
        $script:exportedByDefault | Should Be 'UDT1'
        Test-Path (Join-Path $script:repo 'plc\types\UDT1.s7dcl') | Should Be $true
    }

    It 'a file was added beside it that its export removes' {
        Initialize-SkipTest 'added-file'
        [System.IO.File]::WriteAllText((Join-Path $script:repo 'plc\blocks\FC1.xml'), '<added by hand/>')
        $r = Assert-SameAsFull
        $script:exportedByDefault | Should Be 'FC1'
        @($r.removed) | Should Be 'plc\blocks\FC1.xml'
    }

    It 'not when a file was added by hand in its folder: the mirror removes it, as by full: true' {
        Initialize-SkipTest 'mirror'
        [System.IO.File]::WriteAllText((Join-Path $script:repo 'plc\blocks\Stray.s7dcl'), 'stray')
        Save-SkipRepo
        $r = Assert-SameAsFull
        $script:exportedByDefault | Should Be ''
        @($r.removed) | Should Be 'plc\blocks\Stray.s7dcl'
    }

    It 'its last export failed' {
        Initialize-SkipTest 'failed'
        $script:o.FC1 | Add-Member ScriptMethod ExportAsDocuments { param($d, $n) $this.exports++; throw 'refused' } -Force
        $script:o.FC1 | Add-Member ScriptMethod Export { param($f, $opt) throw 'refused' } -Force
        Step-Date $script:o.FC1
        $r = Invoke-FullExportTool $script:parts
        $r.failedCount | Should Be 1
        Reset-Exports
        $r = Invoke-FullExportTool $script:parts
        Get-Exported | Should Be 'FC1'
        @($r.details | Where-Object { $_.part -eq 'blocks' })[0].why['its last export failed'] | Should Be 1
    }

    It 'its last export ended ok but wrote no file of it' {
        Initialize-SkipTest 'no-file'
        # TIA answers Success and writes nothing: Export-PlcObject returns ok with no files, and the record keeps no file
        $script:o.FC1 | Add-Member ScriptMethod ExportAsDocuments { param($d, $n) $this.exports++; [pscustomobject]@{ State = 'Success'; Messages = @() } } -Force
        Step-Date $script:o.FC1
        $r = Invoke-FullExportTool $script:parts
        $r.failedCount | Should Be 0
        Reset-Exports
        $r = Invoke-FullExportTool $script:parts
        Get-Exported | Should Be 'FC1'
        @($r.details | Where-Object { $_.part -eq 'blocks' })[0].why['the record holds no file of it'] | Should Be 1
    }

    It 'TIA gives no date of it' {
        Initialize-SkipTest 'no-date'
        $script:o.FC1.PSObject.Properties.Remove('ModifiedDate')
        $null = Invoke-FullExportTool $script:parts
        Reset-Exports
        $r = Invoke-FullExportTool $script:parts
        Get-Exported | Should Be 'FC1'
        @($r.details | Where-Object { $_.part -eq 'blocks' })[0].why['TIA gives no date of it'] | Should Be 1
    }

    It 'a value of it does not read (its getter throws, which PowerShell would read as no value)' {
        Initialize-SkipTest 'unread'
        if (-not ('SkipTestBlock' -as [type])) {
            Add-Type -TypeDefinition 'public class SkipTestBlock { public string Name; public System.DateTime ModifiedDate { get { return new System.DateTime(2026, 10, 8, 0, 0, 0, System.DateTimeKind.Utc); } } public bool IsConsistent { get { return true; } } public System.DateTime CompileDate { get { throw new System.NotSupportedException("not offered"); } } }'
        }
        $b = New-Object SkipTestBlock
        $b.Name = 'FC1'
        foreach ($m in 'ExportAsDocuments', 'Export') { $b | Add-Member ScriptMethod $m $script:o.FC1.PSObject.Methods[$m].Script }
        $b | Add-Member NoteProperty text 'code of FC1'
        $b | Add-Member NoteProperty exports 0
        $b | Add-Member NoteProperty IsKnowHowProtected $false
        $script:blocks.Blocks = @($script:o.FB1, $b, $script:o.IDB1, $script:o.DB1)
        $script:o.FC1 = $b
        $null = Invoke-FullExportTool $script:parts
        Reset-Exports
        $r = Invoke-FullExportTool $script:parts
        Get-Exported | Should Be 'FC1'
        @($r.details | Where-Object { $_.part -eq 'blocks' })[0].why['a value of it does not read'] | Should Be 1
    }

    It 'a block it calls changed its interface, and TIA holds it not consistent until the compile' {
        Initialize-SkipTest 'not-consistent'
        Step-Date $script:o.FC1; Step-Date $script:o.FC1 'InterfaceModifiedDate'
        $script:o.FB1.IsConsistent = $false
        $r = Assert-SameAsFull
        $r.exportedAllOf | Should BeNullOrEmpty
        $script:exportedByDefault | Should Be 'FB1,FC1,IDB1'
    }

    It "the interface of a block it calls changed, and the compile rewrote it: its own dates moved" {
        Initialize-SkipTest 'interface'
        Step-Date $script:o.FC1; Step-Date $script:o.FC1 'InterfaceModifiedDate'
        $script:o.FB1.text = 'FB1 calling the new interface'; Step-Date $script:o.FB1
        $r = Assert-SameAsFull
        $r.exportedAllOf | Should BeNullOrEmpty
        $script:exportedByDefault | Should Be 'FB1,FC1,IDB1'
    }

    It 'it was written as SimaticML, and another block changed in TIA, its interface or only its code' {
        Initialize-SkipTest 'xml-code' -SimaticMl 'DB1'
        Test-Path (Join-Path $script:repo 'plc\blocks\DB1.xml') | Should Be $true
        Step-Date $script:o.FC1
        $r = Assert-SameAsFull
        $script:exportedByDefault | Should Be 'DB1,FC1'
        @($r.details | Where-Object { $_.part -eq 'dbs' })[0].why['FC1 changed in TIA, and its SimaticML may show it'] | Should Be 1
    }

    It 'not when it was written as SimaticML and nothing else changed in TIA' {
        Initialize-SkipTest 'xml-nothing' -SimaticMl 'DB1'
        $r = Invoke-FullExportTool $script:parts
        Get-Exported | Should Be ''
    }

    It 'it is an instance DB of an FB that is exported' {
        Initialize-SkipTest 'instance'
        $script:o.FB1.text = 'FB1 with a new comment'; Step-Date $script:o.FB1
        $script:o.IDB1.text = 'IDB1 with the comment of its FB'
        $r = Assert-SameAsFull
        $script:exportedByDefault | Should Be 'FB1,IDB1'
        @($r.details | Where-Object { $_.part -eq 'dbs' })[0].why['its FB FB1 is exported'] | Should Be 1
    }
}

Describe 'the record of full_export' {
    Mock Get-TiaSoftwareList { $script:software }
    Mock Get-TiaProject { $script:project }
    Mock Test-IsDataBlock { $Block.Name -like '*DB*' }

    It 'a run of some parts keeps the snapshot of the run before' {
        Initialize-SkipTest 'parts'
        Step-Date $script:o.Tags 'ModifiedTimeStamp'
        $null = Invoke-FullExportTool ([pscustomobject]@{ parts = @('plc_tags') })
        # the tag table is compared with the snapshot of all four parts: every block may name its tags
        $r = Invoke-FullExportTool $script:parts
        $r.exportedAllOf | Should Be 'PLC_1: the tag table Tags changed'
    }

    Context 'TIA ends at an object' {
        It 'a run that stopped writes no record' {
            Initialize-SkipTest 'stopped'
            $f = Join-Path $script:repo '.tiabridge-export.json'
            $before = [System.IO.File]::ReadAllText($f)
            Step-Date $script:o.FC1
            $script:fc1Ended = $false
            Mock Test-TiaAlive { -not $script:fc1Ended }
            $script:o.FC1 | Add-Member ScriptMethod ExportAsDocuments { param($d, $n) $script:fc1Ended = $true; throw 'TIA ended' } -Force
            $r = Invoke-FullExportTool $script:parts
            $r.tiaEnded | Should Be $true
            $r.note | Should Match 'TIA Portal ended at part blocks'
            [System.IO.File]::ReadAllText($f) | Should Be $before
        }
    }

    It 'is ignored by git in a new repo' {
        $script:RepoGitignore | Should Match '(?m)^\.tiabridge-export\.json\r?$'
        $script:RepoGitignore | Should Match '(?m)^\.tiabridge-export\.json\.\*\.tmp\r?$'
        Initialize-SkipTest 'ignored'
        [System.IO.File]::WriteAllText((Join-Path $script:repo '.gitignore'), $script:RepoGitignore)
        @((Invoke-GitRaw $script:repo @('status', '--porcelain', '--untracked-files=all')).output | Where-Object { $_ -match 'tiabridge-export' }).Count | Should Be 0
    }

    It 'the result says when its write failed' {
        Initialize-SkipTest 'write-failed'
        Mock Write-TextFileAtomic { throw 'disk full' }
        $r = Invoke-FullExportTool $script:parts
        $r.recordError | Should Match 'not written.*disk full'
    }
}

Describe 'full_export reads what TIA says of an object in one call, and lists TIA''s tree once' {
    Mock Get-TiaSoftwareList { $script:software }
    Mock Get-TiaProject { $script:project }
    Mock Test-IsDataBlock { $Block.Name -like '*DB*' }

    # A block with a value for every name the record reads of a block: one call can answer them all. The IEC check and ENO are
    # attributes only GetAttribute reads; a null value is left out, as before.
    function New-FullBlock {
        $b = New-PlcObject 'FC9' '' @{ CodeModifiedDate = [datetime]::new(2026, 10, 8, 13, 0, 0, [DateTimeKind]::Local); ParameterModified = [datetime]::new(2026, 10, 8, 14, 0, 0, [DateTimeKind]::Unspecified)
                                       StructureModified = [datetime]::new(2026, 10, 8, 15, 0, 0, [DateTimeKind]::Utc); CompileDate = [datetime]::new(2026, 10, 9, 0, 0, 0, [DateTimeKind]::Utc)
                                       CreationDate = [datetime]::new(2026, 1, 1, 0, 0, 0, [DateTimeKind]::Utc); Number = 9; ProgrammingLanguage = [System.DayOfWeek]::Monday
                                       MemoryLayout = 'Optimized'; HeaderAuthor = 'me'; HeaderFamily = ''; HeaderName = 'n'; HeaderVersion = '0.1'; Namespace = $null }
        $b | Add-Member NoteProperty attrs @{ IsIECCheckEnabled = $true; SetENOAutomatically = $false }
        $b
    }
    function Get-Text($Obj, [string]$Kind = 'block') { Get-StateText (Read-ExportState (Get-ObjectKind $Kind) @{ obj = $Obj; name = $Obj.Name }) }

    It 'gives the same state text as the reads one name at a time, in one call into TIA' {
        $single = New-FullBlock; Add-AttributeMethods $single -Single
        $one = New-FullBlock; Add-AttributeMethods $one
        Reset-AttributeReads
        $text = Get-Text $one
        $text | Should Be (Get-Text $single)
        $text | Should Match '(?m)^CodeModifiedDate=2026-10-08T13:00:00\.0000000[+-]\d\d:\d\d$'
        $text | Should Match '(?m)^ProgrammingLanguage=Monday$'
        $text | Should Match '(?m)^IsIECCheckEnabled=True$'
        $text | Should Not Match 'Namespace'
        "$($one.calls.GetAttributes) $($one.calls.GetAttributeInfos) $($one.calls.GetAttribute)" | Should Be '1 0 0'
    }

    It 'a name the object lacks: TIA refuses the whole call, and the names it offers are read in one more' {
        Reset-AttributeReads
        $single = New-FullBlock; $single.attrs.Remove('SetENOAutomatically'); Add-AttributeMethods $single -Single
        $one = New-FullBlock; $one.attrs.Remove('SetENOAutomatically'); Add-AttributeMethods $one
        $text = Get-Text $one
        $text | Should Be (Get-Text $single)
        $text | Should Not Match 'SetENOAutomatically'
        "$($one.calls.GetAttributes) $($one.calls.GetAttributeInfos)" | Should Be '2 1'
        # the next object of the kind asks which names it offers first; one that offers them all turns that back
        $next = New-FullBlock; Add-AttributeMethods $next
        $null = Get-Text $next
        "$($next.calls.GetAttributes) $($next.calls.GetAttributeInfos)" | Should Be '1 1'
        $last = New-FullBlock; Add-AttributeMethods $last
        $null = Get-Text $last
        "$($last.calls.GetAttributes) $($last.calls.GetAttributeInfos)" | Should Be '1 0'
    }

    It 'a property TIA does not offer as an attribute is read as before' {
        Reset-AttributeReads
        $single = New-FullBlock; Add-AttributeMethods $single -Single
        $one = New-FullBlock; Add-AttributeMethods $one -Lacks 'Number'
        $text = Get-Text $one
        $text | Should Be (Get-Text $single)
        $text | Should Match '(?m)^Number=9$'
    }

    It 'an object whose values do not read in one call is read one name at a time, and exported when one of them does not read' {
        Initialize-SkipTest 'unread-one-call'
        if (-not ('SkipTestBlock' -as [type])) {
            Add-Type -TypeDefinition 'public class SkipTestBlock { public string Name; public System.DateTime ModifiedDate { get { return new System.DateTime(2026, 10, 8, 0, 0, 0, System.DateTimeKind.Utc); } } public bool IsConsistent { get { return true; } } public System.DateTime CompileDate { get { throw new System.NotSupportedException("not offered"); } } }'
        }
        $b = New-Object SkipTestBlock
        $b.Name = 'FC1'
        foreach ($m in 'ExportAsDocuments', 'Export') { $b | Add-Member ScriptMethod $m $script:o.FC1.PSObject.Methods[$m].Script }
        $b | Add-Member NoteProperty text 'code of FC1'
        $b | Add-Member NoteProperty exports 0
        $b | Add-Member NoteProperty IsKnowHowProtected $false
        $b | Add-Member NoteProperty reads 0
        # as TIA: the getter's error refuses the call, whichever names it holds
        $b | Add-Member ScriptMethod GetAttributeInfos { @('ModifiedDate', 'IsConsistent', 'CompileDate') | ForEach-Object { [pscustomobject]@{ Name = $_ } } }
        $b | Add-Member ScriptMethod GetAttributes { param($Names) $this.reads++; throw 'not offered' }
        $script:blocks.Blocks = @($script:o.FB1, $b, $script:o.IDB1, $script:o.DB1)
        $script:o.FC1 = $b
        $null = Invoke-FullExportTool $script:parts
        Reset-Exports
        $r = Invoke-FullExportTool $script:parts
        Get-Exported | Should Be 'FC1'
        @($r.details | Where-Object { $_.part -eq 'blocks' })[0].why['a value of it does not read'] | Should Be 1
        $b.reads | Should Be 4
    }

    It 'the parts take the plan''s lists: TIA''s tree is listed once' {
        Initialize-SkipTest 'lists'
        $t = (Invoke-FullExportTool $script:parts).times
        $t.plan.steps.tia_list.n | Should Be 4
        foreach ($p in $t.parts) { "$($p.part) $($p.steps.Contains('tia_list'))" | Should Be "$($p.part) False" }
    }

    Context 'TIA ends in the read' {
        It 'stops the export at the first part, as before, and asks TIA nothing more of the object' {
            Initialize-SkipTest 'ended-read'
            $f = Join-Path $script:repo '.tiabridge-export.json'
            $before = [System.IO.File]::ReadAllText($f)
            Add-AttributeMethods $script:o.FC1
            $script:readEnded = $false
            $script:o.FC1 | Add-Member ScriptMethod GetAttributes { param($Names) $this.calls.GetAttributes++; $script:readEnded = $true; throw (New-Ending) } -Force
            Mock Test-TiaAlive { -not $script:readEnded }
            $r = Invoke-FullExportTool $script:parts
            $r.tiaEnded | Should Be $true
            $r.note | Should Match 'TIA Portal ended at part blocks'
            "$($script:o.FC1.calls.GetAttributes) $($script:o.FC1.calls.GetAttributeInfos) $($script:o.FC1.calls.GetAttribute)" | Should Be '1 0 0'
            [System.IO.File]::ReadAllText($f) | Should Be $before
        }
    }
}
