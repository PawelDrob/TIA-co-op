$here = Split-Path -Parent $MyInvocation.MyCommand.Path
foreach ($f in 'Mcp.ps1', 'Tia.ps1', 'Repo.ps1', 'Rules.ps1', 'Guards.ps1', 'Bridge.ps1', 'Tools\Objects.ps1', 'Tools\Plc.ps1') { . (Join-Path $here "..\$f") }

if (-not ('Siemens.Engineering.Library.Types.LibraryTypeInstanceInfo' -as [type])) {
    Add-Type -TypeDefinition 'namespace Siemens.Engineering.Library.Types { public class LibraryTypeInstanceInfo { } }'
}

# A project object whose LibraryTypeInstanceInfo service links it to a library type version (or to nothing).
function New-LinkedObject([string]$Type, [string]$Version, [string]$State) {
    $info = $null
    if ($Type) { $info = [pscustomobject]@{ LibraryTypeVersion = [pscustomobject]@{ TypeObject = [pscustomobject]@{ Name = $Type }; VersionNumber = [version]$Version; State = $State } } }
    [pscustomobject]@{ fakeInfo = $info }
}
function Get-TiaService($Obj, [type]$Type) { $Obj.fakeInfo }

# A block whose ExportAsDocuments writes 'new' into <name><ext> for each of Exts and reports State.
function New-SdBlock([string[]]$Exts, [string]$State = 'Success') {
    $b = [pscustomobject]@{ IsKnowHowProtected = $false; exts = $Exts; state = $State }
    $b | Add-Member ScriptMethod ExportAsDocuments { param($d, $n)
        foreach ($x in $this.exts) { Set-Content (Join-Path $d.FullName "$n$x") 'new' }
        [pscustomobject]@{ State = $this.state } }
    $b
}
# A block whose Export writes 'new xml' (SimaticML).
function New-XmlBlock {
    $b = [pscustomobject]@{ IsKnowHowProtected = $false }
    $b | Add-Member ScriptMethod Export { param($f, $o) Set-Content $f.FullName 'new xml' }
    $b
}

Describe 'Get-LibraryLink' {
    It 'names the type and version and says whether that version is in work' {
        $l = Get-LibraryLink (New-LinkedObject 'Library_Notes' '0.0.2' 'InWork')
        $l.type | Should Be 'Library_Notes'
        $l.version | Should Be '0.0.2'
        $l.inWork | Should Be $true
        (Get-LibraryLink (New-LinkedObject 'Library_Notes' '0.0.1' 'Committed')).inWork | Should Be $false
    }

    It 'returns nothing for an object without a library link' {
        Get-LibraryLink (New-LinkedObject '' '' '') | Should BeNullOrEmpty
    }
}

Describe 'Get-ImportRefusal' {
    It 'refuses to replace the test instance of a library type in work, which TIA answers with a modal message' {
        $r = Get-ImportRefusal -KindName 'block' -Name 'Library_Notes' -Existing @{ obj = (New-LinkedObject 'Library_Notes' '0.0.2' 'InWork') } -Override $true
        $r | Should Match 'in work'
        $r | Should Match 'Library_Notes V 0.0.2'
    }

    It 'refuses an existing object when override is false' {
        Get-ImportRefusal -KindName 'hmi_tag_table' -Name 'PLC' -Existing @{ obj = (New-LinkedObject '' '' '') } -Override $false | Should Match 'override is false'
    }

    It 'allows a new object, and an existing one that is unlinked or linked to a released version' {
        Get-ImportRefusal -KindName 'block' -Name 'New' -Existing $null -Override $true | Should BeNullOrEmpty
        Get-ImportRefusal -KindName 'block' -Name 'A' -Existing @{ obj = (New-LinkedObject '' '' '') } -Override $true | Should BeNullOrEmpty
        Get-ImportRefusal -KindName 'block' -Name 'B' -Existing @{ obj = (New-LinkedObject 'T' '0.0.1' 'Committed') } -Override $true | Should BeNullOrEmpty
    }
}

Describe 'Export-PlcObject' {
    if (-not ('Siemens.Engineering.ExportOptions' -as [type])) {
        Add-Type -TypeDefinition 'namespace Siemens.Engineering { public enum ExportOptions { None, WithDefaults, WithReadOnly } }'
    }

    It 'keeps the previous export when TIA refuses the new one, and replaces it after a successful one (2026-10-06)' {
        $dir = Join-Path $TestDrive 'plc'
        New-Item -ItemType Directory -Force -Path $dir | Out-Null
        Set-Content (Join-Path $dir 'T.s7dcl') 'old'; Set-Content (Join-Path $dir 'T.s7res') 'old'
        $bad = [pscustomobject]@{ IsKnowHowProtected = $false }
        $bad | Add-Member ScriptMethod ExportAsDocuments { param($d, $n) throw 'SIMATIC SD export failed ... SimaticSdEnabler' }
        { Export-PlcObject @{ name = 'T'; obj = $bad } $dir (New-Object psobject) $false } | Should Throw 'SimaticSdEnabler'
        Get-Content (Join-Path $dir 'T.s7dcl') | Should Be 'old'
        Test-Path (Join-Path $dir 'T.partial') | Should Be $false

        $good = [pscustomobject]@{ IsKnowHowProtected = $false }
        $good | Add-Member ScriptMethod Export { param($f, $o) Set-Content $f.FullName 'new xml' }
        $r = Export-PlcObject @{ name = 'T'; obj = $good } $dir ([pscustomobject]@{ format = 'xml' }) $false
        $r.ok | Should Be $true
        Get-Content (Join-Path $dir 'T.xml') | Should Be 'new xml'
    }

    It 'removes the SimaticML export of the block after a successful .s7dcl export, and lists it' {
        $dir = Join-Path $TestDrive 'sd'
        New-Item -ItemType Directory -Force -Path $dir | Out-Null
        Set-Content (Join-Path $dir 'F.xml') 'old xml'; Set-Content (Join-Path $dir 'G.xml') 'other block'
        $r = Export-PlcObject @{ name = 'F'; obj = (New-SdBlock @('.s7dcl', '.s7res')) } $dir (New-Object psobject) $true
        $r.ok | Should Be $true
        ($r.files | ForEach-Object { Split-Path -Leaf $_ }) -join '|' | Should Be 'F.s7dcl|F.s7res'
        ($r.removed | ForEach-Object { Split-Path -Leaf $_ }) -join '|' | Should Be 'F.xml'
        Test-Path (Join-Path $dir 'F.xml') | Should Be $false
        Get-Content (Join-Path $dir 'G.xml') | Should Be 'other block'
    }

    It 'removes the .s7dcl and .s7res of the block after a successful SimaticML export' {
        $dir = Join-Path $TestDrive 'xml'
        New-Item -ItemType Directory -Force -Path $dir | Out-Null
        Set-Content (Join-Path $dir 'O.s7dcl') 'old'; Set-Content (Join-Path $dir 'O.s7res') 'old'
        $r = Export-PlcObject @{ name = 'O'; obj = (New-XmlBlock) } $dir ([pscustomobject]@{ format = 'xml' }) $true
        ($r.files | ForEach-Object { Split-Path -Leaf $_ }) -join '|' | Should Be 'O.xml'
        ($r.removed | ForEach-Object { Split-Path -Leaf $_ }) -join '|' | Should Be 'O.s7dcl|O.s7res'
        Test-Path (Join-Path $dir 'O.s7dcl') | Should Be $false
        Test-Path (Join-Path $dir 'O.s7res') | Should Be $false
    }

    It 'removes an .s7res the new .s7dcl export no longer writes' {
        $dir = Join-Path $TestDrive 'nores'
        New-Item -ItemType Directory -Force -Path $dir | Out-Null
        Set-Content (Join-Path $dir 'D.s7dcl') 'old'; Set-Content (Join-Path $dir 'D.s7res') 'old'
        $r = Export-PlcObject @{ name = 'D'; obj = (New-SdBlock @('.s7dcl')) } $dir (New-Object psobject) $true
        Get-Content (Join-Path $dir 'D.s7dcl') | Should Be 'new'
        ($r.removed | ForEach-Object { Split-Path -Leaf $_ }) -join '|' | Should Be 'D.s7res'
        Test-Path (Join-Path $dir 'D.s7res') | Should Be $false
    }

    It 'removes nothing when TIA refuses the export or reports it failed' {
        $dir = Join-Path $TestDrive 'refused'
        New-Item -ItemType Directory -Force -Path $dir | Out-Null
        Set-Content (Join-Path $dir 'R.xml') 'old xml'
        $bad = [pscustomobject]@{ IsKnowHowProtected = $false }
        $bad | Add-Member ScriptMethod ExportAsDocuments { param($d, $n) throw 'SIMATIC SD export failed ... SimaticSdEnabler' }
        { Export-PlcObject @{ name = 'R'; obj = $bad } $dir (New-Object psobject) $true } | Should Throw 'SimaticSdEnabler'
        Get-Content (Join-Path $dir 'R.xml') | Should Be 'old xml'

        $r = Export-PlcObject @{ name = 'R'; obj = (New-SdBlock @('.s7dcl', '.s7res') 'Error') } $dir (New-Object psobject) $true
        $r.ok | Should Be $false
        $r.removed | Should BeNullOrEmpty
        Get-Content (Join-Path $dir 'R.xml') | Should Be 'old xml'
        Test-Path (Join-Path $dir 'R.s7dcl') | Should Be $false
    }

    It 'keeps the new export and reports the old file it could not remove' {
        $dir = Join-Path $TestDrive 'heldopen'
        New-Item -ItemType Directory -Force -Path $dir | Out-Null
        [System.IO.File]::WriteAllText((Join-Path $dir 'H.xml'), 'old xml')
        $lock = [System.IO.File]::Open((Join-Path $dir 'H.xml'), 'Open', 'Read', 'None')
        try { $r = Export-PlcObject @{ name = 'H'; obj = (New-SdBlock @('.s7dcl', '.s7res')) } $dir (New-Object psobject) $true }
        finally { $lock.Dispose() }
        $r.ok | Should Be $true
        Get-Content (Join-Path $dir 'H.s7dcl') | Should Be 'new'
        $r.removed | Should BeNullOrEmpty
        $r.note | Should Match 'H\.xml'
        Test-Path (Join-Path $dir 'H.xml') | Should Be $true
    }

    It 'keeps the previous file and reports the destination when it stays locked' {
        $dir = Join-Path $TestDrive 'plclock'
        New-Item -ItemType Directory -Force -Path $dir | Out-Null
        [System.IO.File]::WriteAllText((Join-Path $dir 'L.xml'), 'old')
        $good = [pscustomobject]@{ IsKnowHowProtected = $false }
        $good | Add-Member ScriptMethod Export { param($f, $o) Set-Content $f.FullName 'new xml' }
        $lock = [System.IO.File]::Open((Join-Path $dir 'L.xml'), 'Open', 'Read', 'None')
        try { { Export-PlcObject @{ name = 'L'; obj = $good } $dir ([pscustomobject]@{ format = 'xml' }) $false } | Should Throw 'L.xml' }
        finally { $lock.Dispose() }
        [System.IO.File]::ReadAllText((Join-Path $dir 'L.xml')) | Should Be 'old'
        Test-Path (Join-Path $dir 'L.partial') | Should Be $false
    }
}

Describe 'export tool, block' {
    It 'lists the removed export of the other format relative to the project repo (it goes into the next commit)' {
        $repo = Join-Path $TestDrive 'repo'
        Initialize-BridgeContext @{ maxResponseChars = 20000 }
        Set-BridgeProject -Name 'P' -Path 'C:\P.ap20' -Repo $repo
        $dir = Join-Path $repo 'plc\blocks\30Groups'
        New-Item -ItemType Directory -Force -Path $dir | Out-Null
        Set-Content (Join-Path $dir 'G01Mode.xml') 'old xml'
        $block = New-SdBlock @('.s7dcl', '.s7res') | Add-Member NoteProperty Name 'G01Mode' -PassThru
        $plc = [pscustomobject]@{ BlockGroup = [pscustomobject]@{ Blocks = @(); Groups = @([pscustomobject]@{ Name = '30Groups'; Blocks = @($block); Groups = @() }) } }
        Mock Get-KindRoot { $plc }
        Mock Test-IsDataBlock { $false }
        $r = Invoke-ExportTool ([pscustomobject]@{ kind = 'block'; names = @('G01Mode') })
        $r.ok | Should Be $true
        ($r.items[0].files -join '|') | Should Be 'plc\blocks\30Groups\G01Mode.s7dcl|plc\blocks\30Groups\G01Mode.s7res'
        ($r.items[0].removed -join '|') | Should Be 'plc\blocks\30Groups\G01Mode.xml'
    }
}

Describe 'plc_tag_table export' {
    It 'keeps the previous file when TIA refuses the export, and replaces it after a successful one' {
        $dir = Join-Path $TestDrive 'tags'
        New-Item -ItemType Directory -Force -Path $dir | Out-Null
        [System.IO.File]::WriteAllText((Join-Path $dir 'Tags.xml'), 'old')
        $export = (Get-ObjectKind 'plc_tag_table').export
        $bad = [pscustomobject]@{ Name = 'Tags' }
        $bad | Add-Member ScriptMethod Export { param($f, $o) throw 'Export refused' }
        { & $export @{ name = 'Tags'; obj = $bad } $dir (New-Object psobject) } | Should Throw 'Export refused'
        [System.IO.File]::ReadAllText((Join-Path $dir 'Tags.xml')) | Should Be 'old'
        Test-Path (Join-Path $dir 'Tags.xml.partial') | Should Be $false

        $good = [pscustomobject]@{ Name = 'Tags' }
        $good | Add-Member ScriptMethod Export { param($f, $o) [System.IO.File]::WriteAllText($f.FullName, 'new') }
        (& $export @{ name = 'Tags'; obj = $good } $dir (New-Object psobject)).ok | Should Be $true
        [System.IO.File]::ReadAllText((Join-Path $dir 'Tags.xml')) | Should Be 'new'
    }
}


Describe 'Import-PlcFile, line ends of a .s7dcl' {
    function Get-DocumentImportOptions { 'options' }
    # Reads the document as TIA would at the moment of the call.
    function New-Composition {
        $c = [pscustomobject]@{ seen = $null }
        $c | Add-Member ScriptMethod ImportFromDocuments { param($d, $n, $o)
            $this.seen = [System.IO.File]::ReadAllText((Join-Path $d.FullName "$n.s7dcl"))
            [pscustomobject]@{ State = 'Success' } }
        $c
    }

    It 'gives TIA CRLF for a file written with LF, and says so' {
        $path = Join-Path $TestDrive 'Lf.s7dcl'
        [System.IO.File]::WriteAllText($path, "FUNCTION `"Lf`" : Void`n        #r := 1;`n")
        $c = New-Composition
        $r = Import-PlcFile $c @{ file = $path; name = 'Lf'; format = 's7dcl' } $true
        $c.seen | Should Be "FUNCTION `"Lf`" : Void`r`n        #r := 1;`r`n"
        $r.ok | Should Be $true
        $r.note | Should Match 'CRLF'
    }

    It 'has no note for a file with CRLF' {
        $path = Join-Path $TestDrive 'Crlf.s7dcl'
        [System.IO.File]::WriteAllText($path, "FUNCTION `"Crlf`" : Void`r`n")
        $r = Import-PlcFile (New-Composition) @{ file = $path; name = 'Crlf'; format = 's7dcl' } $true
        $r.ContainsKey('note') | Should Be $false
    }

    It 'leaves the file of a refused import as it is' {
        $path = Join-Path $TestDrive 'Ob.s7dcl'
        [System.IO.File]::WriteAllText($path, "ORGANIZATION_BLOCK `"Ob`"`n")
        $r = & (Get-ObjectKind 'block').precheck @{ file = $path; name = 'Ob'; format = 's7dcl' } @{}
        $r.refused | Should Not BeNullOrEmpty
        [System.IO.File]::ReadAllText($path) | Should Be "ORGANIZATION_BLOCK `"Ob`"`n"
    }
}
