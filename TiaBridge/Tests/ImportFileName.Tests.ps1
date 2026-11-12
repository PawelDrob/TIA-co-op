$here = Split-Path -Parent $MyInvocation.MyCommand.Path
foreach ($f in 'Mcp.ps1', 'Tia.ps1', 'Repo.ps1', 'Rules.ps1', 'Guards.ps1', 'Bridge.ps1', 'Tools\Objects.ps1', 'Tools\Plc.ps1', 'Tools\Library.ps1') { . (Join-Path $here "..\$f") }

# A type or block named Ns:Block has its documents in Ns_Block: ':' cannot be in a Windows file name. The import tool must
# find the object it writes to, and must not take Ns_Block's file for the type Ns:Block or the other way round.
if (-not ('Siemens.Engineering.Library.Types.CreateOptions' -as [type])) {
    Add-Type -TypeDefinition 'namespace Siemens.Engineering.Library.Types { public enum CreateOptions { None, Override } }'
}
if (-not ('Siemens.Engineering.Library.LibraryImportOptions' -as [type])) {
    Add-Type -TypeDefinition 'namespace Siemens.Engineering.Library { public enum LibraryImportOptions { None } }'
}
if (-not ('Siemens.Engineering.ImportOptions' -as [type])) {
    Add-Type -TypeDefinition 'namespace Siemens.Engineering { public enum ImportOptions { None, Override } }'
}
if (-not ('Siemens.Engineering.SW.ImportDocumentOptions' -as [type])) {
    Add-Type -TypeDefinition 'namespace Siemens.Engineering.SW { public enum ImportDocumentOptions { None, Override } }'
}

function Get-KindRoot { $script:root }
function Get-TiaSoftwareList { @(@{ device = 'PLC_1'; kind = 'plc' }) }
function Get-TiaService { $null }
function Test-TiaAlive { $true }
function ConvertTo-ResultTree($r) { @{ state = 'Success' } }
function Get-PlcBlockClass($Block) { if ($Block.Class) { $Block.Class } else { 'FB' } }
function Get-LibraryLink($Obj) { $Obj.Link }
function Invoke-TiaWrite([string]$Description, [scriptblock]$Body, [switch]$NoTransaction, [scriptblock]$RollbackIf) {
    $out = @(& $Body)
    @{ output = $out; transaction = $true; rolledBack = [bool]($RollbackIf -and (& $RollbackIf)); commitError = $null; note = $null }
}

function New-FakeType([string]$Name, [bool]$InWork = $true, [string]$Instance = '') {
    $versions = New-Object System.Collections.ArrayList
    [void]$versions.Add([pscustomobject]@{ VersionNumber = [version]'1.0.0'; State = 'Committed'; IsDefault = $true })
    if ($InWork) { [void]$versions.Add([pscustomobject]@{ VersionNumber = [version]'1.0.1'; State = 'InWork'; IsDefault = $false }) }
    $last = $versions[$versions.Count - 1]
    Add-Member -InputObject $last NoteProperty InstanceName $Instance
    Add-Member -InputObject $last ScriptMethod FindInstances {
        param($software)
        if ($this.InstanceName) { [pscustomobject]@{ LibraryTypeInstance = [pscustomobject]@{ Name = $this.InstanceName } } }
    }
    Add-Member -InputObject $versions NoteProperty TypeName $Name
    Add-Member -InputObject $versions ScriptMethod CreateFromDocuments {
        param($dir, $name, $create, $import)
        $script:created += @("$($this.TypeName) <- $name")
        [pscustomobject]@{ TransferResultState = 'Success' }
    }
    [pscustomobject]@{ Name = $Name; Versions = $versions }
}

function Invoke-LibraryImport([string[]]$TypeNames, [string[]]$Paths, [object[]]$Types = @()) {
    $types = @($Types) + @($TypeNames | ForEach-Object { New-FakeType $_ })
    $script:root = [pscustomobject]@{ TypeFolder = [pscustomobject]@{ Types = $types; Folders = @() } }
    Invoke-FileImport 'library_type' $Paths
}

function Invoke-FileImport([string]$Kind, [string[]]$Paths) {
    Initialize-BridgeContext @{ maxResponseChars = 20000 }
    Set-BridgeProject -Name 'P' -Path 'C:\P.ap20' -Repo $script:repo
    Register-Archive (Get-BridgeSession)
    $script:created = @(); $script:imported = @()
    Invoke-ImportTool ([pscustomobject]@{ kind = $Kind; paths = $Paths })
}

Describe 'Get-DocumentDeclaredName' {
    function Read-Name([string]$File, [string]$Text) {
        $p = Join-Path $TestDrive $File
        Write-TextFile $p $Text
        Get-DocumentDeclaredName $p
    }

    It 'reads a quoted name right after the block keyword, past the pragma in front of it' {
        Read-Name 'a.s7dcl' "{ S7_Optimized := `"True`" }`r`nFUNCTION_BLOCK `"Ns:Block`"`r`nVERSION : 0.1`r`nEND_FUNCTION_BLOCK" | Should Be 'Ns:Block'
        Read-Name 'b.s7dcl' "{ S7_Optimized := `"True`" }`r`nFUNCTION `"Ns:Calc`" : Void`r`nEND_FUNCTION" | Should Be 'Ns:Calc'
        Read-Name 'c.s7dcl' "ORGANIZATION_BLOCK `"Ns:Main`"`r`nEND_ORGANIZATION_BLOCK" | Should Be 'Ns:Main'
    }

    It 'reads the forms of a data block: quoted or not, with or without its type' {
        Read-Name 'd.s7dcl' "{ S7_Optimized := `"True`" }`r`nDATA_BLOCK `"Ns:Db`" : `"Ns:Block`"`r`nEND_DATA_BLOCK" | Should Be 'Ns:Db'
        Read-Name 'e.s7dcl' "{ S7_Optimized := `"True`" }`r`nDATA_BLOCK PlainDb : PlainFb`r`nEND_DATA_BLOCK" | Should Be 'PlainDb'
        Read-Name 'f.s7dcl' "{ S7_Optimized := `"True`" }`r`nDATA_BLOCK PlainDb`r`nEND_DATA_BLOCK" | Should Be 'PlainDb'
    }

    It 'reads the forms of a PLC data type: TYPE alone on its line, an optional pragma, then the name' {
        Read-Name 'g.s7dcl' "TYPE`r`n    PlainData : STRUCT`r`n        a : Bool;`r`n    END_STRUCT;`r`nEND_TYPE" | Should Be 'PlainData'
        Read-Name 'h.s7dcl' "TYPE`r`n    { S7_Safety := `"True`" }`r`n    PlainData : STRUCT`r`n    END_STRUCT;`r`nEND_TYPE" | Should Be 'PlainData'
        Read-Name 'i.s7dcl' "TYPE`r`n    { S7_Safety := `"True`" }`r`n    `"Ns:Data`" : STRUCT`r`n    END_STRUCT;`r`nEND_TYPE" | Should Be 'Ns:Data'
        Read-Name 'j.s7dcl' "TYPE`r`n    {`r`n        S7_BlockComment := `"MLC_1`"`r`n    }`r`n    `"Ns/Data`" : STRUCT`r`n    END_STRUCT;`r`nEND_TYPE" | Should Be 'Ns/Data'
    }

    It 'does not take text inside a pragma for the declaration' {
        Read-Name 'k.s7dcl' "{ S7_BlockTitle := `"a } b`r`nTYPE Trap`r`n`" }`r`nFUNCTION_BLOCK `"Ns:Block`"`r`nEND_FUNCTION_BLOCK" | Should Be 'Ns:Block'
        Read-Name 'l.s7dcl' "TYPE`r`n    { S7_BlockTitle := `"Trap : STRUCT }`" }`r`n    PlainData : STRUCT`r`nEND_TYPE" | Should Be 'PlainData'
    }

    It 'reads the block Name of a SimaticML, not a member of its interface' {
        $xml = '<Document><Engineering version="V20" /><SW.Blocks.FB ID="0"><AttributeList><Interface><Sections><Section Name="Input"><Member Name="Other"><Name>Inner</Name></Member></Section></Sections></Interface><Name>Ns:Block</Name></AttributeList></SW.Blocks.FB></Document>'
        Read-Name 'f.xml' $xml | Should Be 'Ns:Block'
        Read-Name 'g.xml' '<Document><SW.Types.PlcStruct ID="0"><AttributeList><Name>Ns:Data</Name></AttributeList></SW.Types.PlcStruct></Document>' | Should Be 'Ns:Data'
    }

    It 'reads past comments in front of the keyword and between it and the name' {
        Read-Name 'm.s7dcl' "// one  `r`n// two`r`n(* three *)`r`n/* four */`r`nFUNCTION_BLOCK `"Ns:Block`"`r`nEND_FUNCTION_BLOCK" | Should Be 'Ns:Block'
        Read-Name 'n.s7dcl' "TYPE // one`r`n(* two *)`r`nPlainData : STRUCT`r`nEND_TYPE" | Should Be 'PlainData'
    }

    It 'reads past a pragma value in single quotes, whatever it holds, and an apostrophe left open' {
        Read-Name 'o.s7dcl' "{ S7_BlockTitle := 'a}b' }`r`nFUNCTION_BLOCK `"Ns:Block`"`r`nEND_FUNCTION_BLOCK" | Should Be 'Ns:Block'
        Read-Name 'p.s7dcl' "{ S7_BlockTitle := 'a`"b' }`r`nFUNCTION_BLOCK `"Ns:Block`"`r`nEND_FUNCTION_BLOCK" | Should Be 'Ns:Block'
        Read-Name 'q.s7dcl' "{ S7_BlockTitle := it's }`r`nFUNCTION_BLOCK `"Ns:Block`"`r`nEND_FUNCTION_BLOCK" | Should Be 'Ns:Block'
    }

    # In a job, so a regex that backtracks exponentially fails the test instead of holding the commit hook for days.
    It 'answers at once on a long hand-written header with no keyword after it' {
        $tail = "no_keyword `"Ns:Block`"`r`nend_function_block"
        $docs = [ordered]@{
            'lines' = (('// a comment line' + "`r`n") * 5000) + $tail
            'spaces' = (('// a comment line   ' + "`r`n") * 5000) + $tail
            'paren' = (('(* a comment *)' + "`r`n") * 5000) + $tail
            'slash' = (('/* a comment */' + "`r`n") * 5000) + $tail
            'pragma' = (('{ S7_BlockTitle := "x" }' + "`r`n") * 5000) + $tail
            'apostrophe' = ("{ S7_BlockTitle := it's" + "`r`n") * 5000
            'unclosed' = ('{ S7_BlockTitle := "x" ' + "`r`n") * 5000
            'open' = (('(* never closed ' + "`r`n") * 5000) + $tail
            'after' = "TYPE`r`n" + (('// a comment line' + "`r`n") * 5000) + ':'
        }
        $files = @(foreach ($k in $docs.Keys) { $f = Join-Path $TestDrive "long_$k.s7dcl"; Write-TextFile $f $docs[$k]; $f })
        $job = Start-Job -ArgumentList (Join-Path $here '..\Repo.ps1'), $files -ScriptBlock {
            param($repo, $paths)
            . $repo
            foreach ($p in $paths) { "[$(Get-DocumentDeclaredName $p)]" }
        }
        try {
            $finished = Wait-Job $job -Timeout 30
            $finished | Should Not BeNullOrEmpty
            (Receive-Job $job) -join '' | Should Be ('[]' * $files.Count)
        }
        finally { Remove-Job $job -Force }
    }

    It 'gives nothing for a document it cannot read a name from, without throwing' {
        Read-Name 'h.s7dcl' 'no block here' | Should Be ''
        Read-Name 'i.xml' '<Document />' | Should Be ''
        Read-Name 'j.xml' '<not closed' | Should Be ''
        Get-DocumentDeclaredName (Join-Path $TestDrive 'gone.s7dcl') | Should Be ''
    }
}

Describe 'import of a library type whose name does not fit a file name' {
    $script:repo = Join-Path $TestDrive 'R'
    New-Item -ItemType Directory -Force -Path (Join-Path $script:repo 'logs') | Out-Null
    $colon = "FUNCTION_BLOCK `"Ns:Block`"`r`nEND_FUNCTION_BLOCK"
    $under = "FUNCTION_BLOCK `"Ns_Block`"`r`nEND_FUNCTION_BLOCK"
    Write-TextFile (Join-Path $script:repo 'library\types\Colon\Ns_Block.s7dcl') $colon
    Write-TextFile (Join-Path $script:repo 'library\types\Colon\Ns_Block.libinfo') 'LibraryVersion:'
    Write-TextFile (Join-Path $script:repo 'library\types\Under\Ns_Block.s7dcl') $under
    Write-TextFile (Join-Path $script:repo 'library\types\Xml\Ns_Block.xml') '<Document><SW.Blocks.FB ID="0"><AttributeList><Name>Ns:Block</Name></AttributeList></SW.Blocks.FB></Document>'
    Write-TextFile (Join-Path $script:repo 'library\types\Blank\Ns_Block.s7dcl') 'no block here'
    Write-TextFile (Join-Path $script:repo 'library\types\Plain\Plain.s7dcl') 'no block here'
    Write-TextFile (Join-Path $script:repo 'library\types\Other\Plain.s7dcl') "TYPE`r`n    Other : STRUCT`r`n    END_STRUCT;`r`nEND_TYPE"
    Write-TextFile (Join-Path $script:repo 'library\types\Udt\Ns_Data.s7dcl') "TYPE`r`n    { S7_BlockTitle := `"MLC_1`" }`r`n    `"Ns:Data`" : STRUCT`r`n    END_STRUCT;`r`nEND_TYPE"
    Write-TextFile (Join-Path $script:repo 'library\types\FUdt\Ns_Data.s7dcl') "TYPE`r`n    { S7_Safety := `"True`" }`r`n    `"Ns:Data`" : STRUCT`r`n    END_STRUCT;`r`nEND_TYPE"
    Write-TextFile (Join-Path $script:repo 'library\types\Inst\Ns_Block.s7dcl') "FUNCTION_BLOCK `"Ns:Block_1`"`r`nEND_FUNCTION_BLOCK"
    $colonFile = 'library\types\Colon\Ns_Block.s7dcl'
    $underFile = 'library\types\Under\Ns_Block.s7dcl'

    It 'imports into the type the document declares, under the name the files have' {
        $r = Invoke-LibraryImport @('Ns:Block', 'Plain') @($colonFile)
        $r.ok | Should Be $true
        $r.items[0].name | Should Be 'Ns:Block'
        $script:created -join ',' | Should Be 'Ns:Block <- Ns_Block'
    }

    It 'imports SimaticML the same way, and takes the .libinfo path for the folder' {
        (Invoke-LibraryImport @('Ns:Block') @('library\types\Xml\Ns_Block.xml')).ok | Should Be $true
        $script:created -join ',' | Should Be 'Ns:Block <- Ns_Block'
        (Invoke-LibraryImport @('Ns:Block') @('library\types\Colon\Ns_Block.libinfo')).ok | Should Be $true
        $script:created -join ',' | Should Be 'Ns:Block <- Ns_Block'
    }

    It 'counts the write for the save rules under the name of the type' {
        $null = Invoke-LibraryImport @('Ns:Block') @($colonFile)
        @((Get-BridgeSession).pending.Values) -join ' ' | Should Match 'PLC_1:Ns:Block'
    }

    It 'still imports a type with a plain name' {
        (Invoke-LibraryImport @('Plain') @('library\types\Plain\Plain.s7dcl')).ok | Should Be $true
        $script:created -join ',' | Should Be 'Plain <- Plain'
    }

    It 'refuses the document of an F-compliant PLC data type without safety, and does not call it an F-block alone' {
        $r = Invoke-LibraryImport @('Ns:Data') @('library\types\FUdt\Ns_Data.s7dcl')
        $r.items[0].refused | Should Match "library_type 'Ns:Data' is an F-block or F-compliant PLC data type"
        @($script:created).Count | Should Be 0
    }

    It 'imports a PLC data type in the form TIA writes' {
        $r = Invoke-LibraryImport @('Ns:Data') @('library\types\Udt\Ns_Data.s7dcl')
        $r.ok | Should Be $true
        $script:created -join ',' | Should Be 'Ns:Data <- Ns_Data'
    }

    It 'takes a document declaring a project instance of the type, into the type' {
        $r = Invoke-LibraryImport @() @('library\types\Inst\Ns_Block.s7dcl') @(New-FakeType 'Ns:Block' $true 'Ns:Block_1')
        $r.ok | Should Be $true
        $r.items[0].name | Should Be 'Ns:Block'
        $script:created -join ',' | Should Be 'Ns:Block <- Ns_Block'
    }

    It 'refuses a document declaring a name no instance of the type has, or the instance of another type' {
        $r = Invoke-LibraryImport @() @('library\types\Inst\Ns_Block.s7dcl') @(New-FakeType 'Ns:Block' $true 'Ns:Block_2'), (New-FakeType 'Ns:Other' $true 'Ns:Block_1')
        $r.items[0].refused | Should Match "declares 'Ns:Block_1'"
        $r.items[0].refused | Should Match 'no project instance'
        @($script:created).Count | Should Be 0
    }

    It 'refuses when the file name fits two types, whichever the document declares: an exact match does not win' {
        foreach ($file in $colonFile, $underFile) {
            $r = Invoke-LibraryImport @('Ns:Block', 'Ns_Block') @($file)
            $r.ok | Should Be $false
            $r.items[0].refused | Should Match "'Ns:Block' and 'Ns_Block'"
            @($script:created).Count | Should Be 0
        }
    }

    It 'refuses the document of Ns:Block over the type Ns_Block, the only one the file name fits' {
        $r = Invoke-LibraryImport @('Ns_Block') @($colonFile)
        $r.ok | Should Be $false
        $r.items[0].refused | Should Match "declares 'Ns:Block'"
        $r.items[0].refused | Should Match "library type 'Ns_Block'"
        @($script:created).Count | Should Be 0
    }

    It 'refuses the document of Ns_Block over the type Ns:Block' {
        $r = Invoke-LibraryImport @('Ns:Block') @($underFile)
        $r.ok | Should Be $false
        $r.items[0].refused | Should Match "declares 'Ns_Block'"
        @($script:created).Count | Should Be 0
    }

    It 'refuses a document of another name, also with no special character in sight' {
        $r = Invoke-LibraryImport @('Plain') @('library\types\Other\Plain.s7dcl')
        $r.items[0].refused | Should Match "declares 'Other'"
        @($script:created).Count | Should Be 0
    }

    It 'refuses when it cannot confirm a type whose name differs from the file; with the same name TIA judges the document' {
        $r = Invoke-LibraryImport @('Ns:Block') @('library\types\Blank\Ns_Block.s7dcl')
        $r.items[0].refused | Should Match 'cannot confirm'
        @($script:created).Count | Should Be 0
        (Invoke-LibraryImport @('Plain') @('library\types\Plain\Plain.s7dcl')).ok | Should Be $true
    }

    It 'refuses before TIA is touched when no type fits, and imports nothing of the batch' {
        $r = Invoke-LibraryImport @('Plain') @('library\types\Plain\Plain.s7dcl', $colonFile)
        $r.ok | Should Be $false
        $r.items[0].notAttempted | Should Be $true
        $r.items[1].refused | Should Match "No library type named 'Ns_Block'"
        @($script:created).Count | Should Be 0
    }

    It 'names the type, not the file, when it has no version in work' {
        $r = Invoke-LibraryImport @() @($colonFile) @(New-FakeType 'Ns:Block' $false)
        $r.items[0].refused | Should Match "Type 'Ns:Block' has no version in work"
    }
}

# Not found by its file name, the object looked new: no refusal, and TIA, going by the name in the document, replaced it.
Describe 'import of a project object: the name the document declares is the object' {
    $script:repo = Join-Path $TestDrive 'P'
    $fbDoc = "{ S7_Optimized := `"True`" }`r`nFUNCTION_BLOCK `"Ns:Block`"`r`nEND_FUNCTION_BLOCK"
    $udtDoc = "TYPE`r`n    { S7_BlockTitle := `"MLC_1`" }`r`n    `"Ns:Data`" : STRUCT`r`n    END_STRUCT;`r`nEND_TYPE"
    Write-TextFile (Join-Path $script:repo 'plc\blocks\Ns_Block.s7dcl') $fbDoc
    Write-TextFile (Join-Path $script:repo 'plc\blocks\Copy.s7dcl') $fbDoc
    Write-TextFile (Join-Path $script:repo 'plc\blocks\NewFb.s7dcl') "FUNCTION_BLOCK `"Fresh`"`r`nEND_FUNCTION_BLOCK"
    Write-TextFile (Join-Path $script:repo 'plc\blocks\NoName.s7dcl') 'no block here'
    Write-TextFile (Join-Path $script:repo 'plc\blocks\Ns_Xml.xml') '<Document><SW.Blocks.FB ID="0"><AttributeList><Name>Ns:Block</Name></AttributeList></SW.Blocks.FB></Document>'
    Write-TextFile (Join-Path $script:repo 'plc\blocks\CopyDb.s7dcl') "{ S7_Optimized := `"True`" }`r`nDATA_BLOCK PlainDb : PlainFb`r`nEND_DATA_BLOCK"
    Write-TextFile (Join-Path $script:repo 'plc\types\Ns_Data.s7dcl') $udtDoc
    Write-TextFile (Join-Path $script:repo 'plc\types\CopyUdt.s7dcl') "TYPE`r`n    PlainData : STRUCT`r`n    END_STRUCT;`r`nEND_TYPE"
    Write-TextFile (Join-Path $script:repo 'plc\types\NewF.s7dcl') "TYPE`r`n    { S7_Safety := `"True`" }`r`n    FreshF : STRUCT`r`n    END_STRUCT;`r`nEND_TYPE"
    $otherRepo = Join-Path $TestDrive 'P2'
    Write-TextFile (Join-Path $otherRepo 'plc\blocks\Ns_Block.s7dcl') "FUNCTION_BLOCK `"Ns_Block`"`r`nEND_FUNCTION_BLOCK"

    function Invoke-PlcImport([string]$Kind, [string]$Path, $Object) {
        $list = New-Object System.Collections.ArrayList
        [void]$list.Add($Object)
        Add-Member -InputObject $list ScriptMethod ImportFromDocuments {
            param($dir, $name, $options)
            $script:imported += @($name)
            [pscustomobject]@{}
        }
        $group = [pscustomobject]@{ Blocks = $list; Types = $list; Groups = @() }
        $script:root = [pscustomobject]@{ BlockGroup = $group; TypeGroup = $group }
        Invoke-FileImport $Kind @($Path)
    }
    function New-Object1([string]$Name, $Extra = @{}) {
        $p = @{ Name = $Name; ProgrammingLanguage = 'LAD'; IsKnowHowProtected = $false; Link = $null; Class = 'FB' }
        foreach ($key in $Extra.Keys) { $p[$key] = $Extra[$key] }
        [pscustomobject]$p
    }
    $inWork = @{ Link = @{ inWork = $true; type = 'Ns:Lib'; version = '1.0.1' } }

    It 'replaces the block the document declares, reading the files by their own name' {
        $r = Invoke-PlcImport 'block' 'plc\blocks\Ns_Block.s7dcl' (New-Object1 'Ns:Block')
        $r.ok | Should Be $true
        $r.items[0].name | Should Be 'Ns:Block'
        $script:imported -join ',' | Should Be 'Ns_Block'
    }

    It 'refuses a know-how protected block, by its name' {
        $r = Invoke-PlcImport 'block' 'plc\blocks\Ns_Block.s7dcl' (New-Object1 'Ns:Block' @{ IsKnowHowProtected = $true })
        $r.items[0].refused | Should Match "block 'Ns:Block' is know-how protected"
        @($script:imported).Count | Should Be 0
    }

    It 'refuses an F-block without safety, by its name, even when the file has no F mark' {
        $r = Invoke-PlcImport 'block' 'plc\blocks\Ns_Block.s7dcl' (New-Object1 'Ns:Block' @{ ProgrammingLanguage = 'F_LAD' })
        $r.items[0].refused | Should Match "block 'Ns:Block' is an F-block"
        @($script:imported).Count | Should Be 0
    }

    It 'refuses the test instance of a type in work, by its name, where TIA would wait on a modal message' {
        $r = Invoke-PlcImport 'block' 'plc\blocks\Ns_Block.s7dcl' (New-Object1 'Ns:Block' $inWork)
        $r.items[0].refused | Should Match "block 'Ns:Block' is the test instance"
        @($script:imported).Count | Should Be 0
    }

    It 'goes by the declaration whatever the file is called: a copy of another name meets the same guards' {
        foreach ($extra in @{ ProgrammingLanguage = 'F_LAD' }, @{ IsKnowHowProtected = $true }, $inWork) {
            $r = Invoke-PlcImport 'block' 'plc\blocks\Copy.s7dcl' (New-Object1 'Ns:Block' $extra)
            $r.ok | Should Be $false
            $r.items[0].name | Should Be 'Ns:Block'
            $r.items[0].refused | Should Match "block 'Ns:Block'"
            @($script:imported).Count | Should Be 0
        }
    }

    It 'reads SimaticML the same way' {
        $r = Invoke-PlcImport 'block' 'plc\blocks\Ns_Xml.xml' (New-Object1 'Ns:Block' @{ IsKnowHowProtected = $true })
        $r.items[0].refused | Should Match "block 'Ns:Block' is know-how protected"
    }

    It 'refuses a PLC data type in the form TIA writes, quoted or not, the test instance of a type in work' {
        $r = Invoke-PlcImport 'type' 'plc\types\Ns_Data.s7dcl' (New-Object1 'Ns:Data' $inWork)
        $r.items[0].refused | Should Match "type 'Ns:Data' is the test instance"
        $r = Invoke-PlcImport 'type' 'plc\types\CopyUdt.s7dcl' (New-Object1 'PlainData' $inWork)
        $r.items[0].refused | Should Match "type 'PlainData' is the test instance"
        @($script:imported).Count | Should Be 0
    }

    It 'refuses a new F-compliant PLC data type without safety: S7_Safety comes after the keyword' {
        $r = Invoke-PlcImport 'type' 'plc\types\NewF.s7dcl' (New-Object1 'Other')
        $r.items[0].name | Should Be 'FreshF'
        $r.items[0].refused | Should Match "type 'FreshF' is an F-compliant PLC data type"
        $r.items[0].refused | Should Match 'safety: true'
        @($script:imported).Count | Should Be 0
    }

    It 'refuses a data block with an unquoted name under another file name' {
        $r = Invoke-PlcImport 'db' 'plc\blocks\CopyDb.s7dcl' (New-Object1 'PlainDb' @{ Class = 'InstanceDB'; ProgrammingLanguage = 'F_DB' })
        $r.items[0].refused | Should Match "db 'PlainDb' is an F-block"
        @($script:imported).Count | Should Be 0
    }

    It 'imports a new object under the name it declares, with the file read by its own name' {
        $r = Invoke-PlcImport 'block' 'plc\blocks\NewFb.s7dcl' (New-Object1 'Ns:Block' @{ IsKnowHowProtected = $true })
        $r.ok | Should Be $true
        $r.items[0].name | Should Be 'Fresh'
        $script:imported -join ',' | Should Be 'NewFb'
    }

    It 'goes by the file name when the document declares nothing readable' {
        $r = Invoke-PlcImport 'block' 'plc\blocks\NoName.s7dcl' (New-Object1 'NoName' @{ IsKnowHowProtected = $true })
        $r.items[0].refused | Should Match "block 'NoName' is know-how protected"
    }

    It 'leaves a block the document names Ns_Block alone: that is another block than Ns:Block' {
        $keep = $script:repo
        $script:repo = $otherRepo
        try { $r = Invoke-PlcImport 'block' 'plc\blocks\Ns_Block.s7dcl' (New-Object1 'Ns:Block' @{ IsKnowHowProtected = $true }) } finally { $script:repo = $keep }
        $r.ok | Should Be $true
        $r.items[0].name | Should Be 'Ns_Block'
    }
}

Describe 'Get-DocumentDeclaredName and Get-DocumentObjectClass: a keyword in lower case' {
    function New-DocFile([string]$File, [string]$Text) { $p = Join-Path $TestDrive $File; Write-TextFile $p $Text; $p }

    It 'reads the name and the class, whatever the case of the keyword' {
        $p = New-DocFile 'a.s7dcl' "function_block `"Ns:Block`"`r`nend_function_block"
        Get-DocumentDeclaredName $p | Should BeExactly 'Ns:Block'
        Get-DocumentObjectClass $p | Should Be 'block'
        $p = New-DocFile 'b.s7dcl' "Data_Block PlainDb : PlainFb`r`nEnd_Data_Block"
        Get-DocumentDeclaredName $p | Should BeExactly 'PlainDb'
        Get-DocumentObjectClass $p | Should Be 'DB'
        $p = New-DocFile 'c.s7dcl' "type`r`n    { S7_BlockTitle := `"x`" }`r`n    `"Ns:Data`" : struct`r`n    end_struct;`r`nend_type"
        Get-DocumentDeclaredName $p | Should BeExactly 'Ns:Data'
        Get-DocumentObjectClass $p | Should Be 'type'
    }

    It 'still takes no word of a comment or a pragma for the keyword' {
        Get-DocumentDeclaredName (New-DocFile 'd.s7dcl' "// function_block `"Trap`"`r`n{ S7_BlockTitle := `"type Trap`" }`r`nno block here") | Should Be ''
    }
}

Describe 'Get-DocumentSecondDeclaration' {
    function Read-Second([string]$File, [string]$Text) {
        $p = Join-Path $TestDrive $File
        Write-TextFile $p $Text
        Get-DocumentSecondDeclaration $p
    }
    $one = "FUNCTION_BLOCK `"A`"`r`nVERSION : 0.1`r`nEND_FUNCTION_BLOCK"

    It 'names what a .s7dcl declares after the end of its first object' {
        Read-Second 'a.s7dcl' "$one`r`n{ S7_Safety := `"True`" }`r`nFUNCTION_BLOCK `"B`"`r`nEND_FUNCTION_BLOCK" | Should BeExactly 'B'
        Read-Second 'b.s7dcl' "$one`r`nDATA_BLOCK PlainDb : A`r`nEND_DATA_BLOCK" | Should BeExactly 'PlainDb'
        Read-Second 'c.s7dcl' "TYPE`r`n    D1 : STRUCT`r`n    END_STRUCT;`r`nEND_TYPE`r`nTYPE`r`n    `"Ns:D2`" : STRUCT`r`n    END_STRUCT;`r`nEND_TYPE" | Should BeExactly 'Ns:D2'
        Read-Second 'd.s7dcl' "FUNCTION `"F`" : Void`r`nEND_FUNCTION FUNCTION_BLOCK `"B`"`r`nEND_FUNCTION_BLOCK" | Should BeExactly 'B'
    }

    It 'names a second type listed after a first that is no STRUCT, as its ; ends it as END_STRUCT does' {
        Read-Second 'l1.s7dcl' "TYPE`r`n    A : `"Other`";`r`n    B : STRUCT`r`n    END_STRUCT;`r`nEND_TYPE" | Should BeExactly 'B'
        Read-Second 'l2.s7dcl' "TYPE`r`n    A : ARRAY[0..1] OF INT;`r`n    B : STRUCT`r`n    END_STRUCT;`r`nEND_TYPE" | Should BeExactly 'B'
        Read-Second 'l3.s7dcl' "TYPE`r`n    A : INT;`r`n    B : INT;`r`nEND_TYPE" | Should BeExactly 'B'
        Read-Second 'l4.s7dcl' "type`r`n    A : INT; // first`r`n    /* then */ `"Ns:B`" : INT;`r`nend_type" | Should BeExactly 'Ns:B'
    }

    It 'finds no second type in one type that ends in a ;, or in the ; of a member, a pragma or a block' {
        Read-Second 'n1.s7dcl' "TYPE`r`n    A : `"Other`";`r`nEND_TYPE" | Should BeExactly ''
        Read-Second 'n2.s7dcl' "type`r`n    A : ARRAY[0..1] OF INT; // first`r`nend_type;" | Should BeExactly ''
        Read-Second 'n3.s7dcl' "TYPE`r`n    { S7_Note := `"x; y`" }`r`n    A : STRUCT`r`n        M : INT;`r`n        N : STRUCT`r`n            O : INT;`r`n        END_STRUCT;`r`n    END_STRUCT;`r`nEND_TYPE" | Should BeExactly ''
        Read-Second 'n4.s7dcl' "FUNCTION_BLOCK `"A`"`r`nBEGIN`r`n    x := 1;`r`n    y := 2;`r`nEND_FUNCTION_BLOCK" | Should BeExactly ''
    }

    It 'finds a second declaration in lower case, and one without a name it can read' {
        Read-Second 'e.s7dcl' "function_block `"A`"`r`nend_function_block`r`nfunction_block `"B`"`r`nend_function_block" | Should BeExactly 'B'
        Read-Second 'f.s7dcl' "$one`r`nFUNCTION_BLOCK" | Should BeExactly 'FUNCTION_BLOCK'
    }

    It 'finds a second type listed in one TYPE, past a pragma in front of it, not what a STRUCT holds' {
        Read-Second 'n.s7dcl' "TYPE`r`n    A : STRUCT`r`n    END_STRUCT;`r`n    { S7_Safety := `"True`" }`r`n    B : STRUCT`r`n    END_STRUCT;`r`nEND_TYPE" | Should BeExactly 'B'
        Read-Second 'o.s7dcl' "TYPE`r`n    A : STRUCT`r`n        in : Struct`r`n            x : Bool;`r`n        End_Struct;`r`n        l : Array[0..1] of STRUCT`r`n            y : Bool;`r`n        END_STRUCT;`r`n    END_STRUCT;`r`nEND_TYPE" | Should Be ''
    }

    It 'is not led past the end of the first object by an apostrophe or a quote left open' {
        foreach ($body in "REGION it's`r`nEND_REGION", "// it's", "{ S7_T := 'a`"b' }", "{ S7_T := 'a}b' }", "x := `"open`r`ny := 1;") {
            Read-Second 'p.s7dcl' "FUNCTION_BLOCK `"A`"`r`n$body`r`nEND_FUNCTION_BLOCK`r`nFUNCTION_BLOCK `"B`"`r`nEND_FUNCTION_BLOCK" | Should BeExactly 'B'
        }
    }

    It 'gives nothing for one object, whatever its body holds' {
        Read-Second 'g.s7dcl' $one | Should Be ''
        Read-Second 'h.s7dcl' "$one`r`n// FUNCTION_BLOCK `"Note`"`r`n(* TYPE Note *)`r`n/* DATA_BLOCK Note */`r`n" | Should Be ''
        # members may carry the words of the keywords; only the end of the first object opens the search
        Read-Second 'i.s7dcl' "FUNCTION_BLOCK `"A`"`r`nVAR`r`n    Type : Int;`r`n    Function : Int;`r`nEND_VAR`r`nEND_FUNCTION_BLOCK" | Should Be ''
        # an END in a comment is not the end of the object
        Read-Second 'j.s7dcl' "FUNCTION_BLOCK `"A`"`r`n// END_FUNCTION_BLOCK`r`nTYPE`r`nEND_FUNCTION_BLOCK" | Should Be ''
        # nor one in a text, a quoted name or a pragma
        Read-Second 'k.s7dcl' "FUNCTION_BLOCK `"A`"`r`nx := 'END_FUNCTION_BLOCK FUNCTION it`$'s';`r`ny := `"END_FUNCTION_BLOCK`";`r`n{ S7_T := `"END_FUNCTION_BLOCK TYPE`" }`r`nEND_FUNCTION_BLOCK" | Should Be ''
    }

    It 'names the second object of a SimaticML, not what the first holds' {
        Read-Second 'a.xml' '<Document><SW.Blocks.FB ID="0"><AttributeList><Name>A</Name></AttributeList><ObjectList><SW.Blocks.CompileUnit ID="1"><AttributeList><Name>Inner</Name></AttributeList></SW.Blocks.CompileUnit></ObjectList></SW.Blocks.FB></Document>' | Should Be ''
        Read-Second 'b.xml' '<Document><SW.Blocks.FB ID="0"><AttributeList><Name>A</Name></AttributeList></SW.Blocks.FB><SW.Blocks.GlobalDB ID="1"><AttributeList><Name>B</Name></AttributeList></SW.Blocks.GlobalDB></Document>' | Should BeExactly 'B'
    }

    It 'gives nothing for a document it cannot read, without throwing' {
        Read-Second 'l.s7dcl' 'no block here' | Should Be ''
        Read-Second 'c.xml' '<not closed' | Should Be ''
        Get-DocumentSecondDeclaration (Join-Path $TestDrive 'gone.s7dcl') | Should Be ''
    }

    # In a job, as the name reader above: every token must succeed once, or a comment never closed rescans the file per line.
    It 'answers at once on a long body of things never closed' {
        $head = "FUNCTION_BLOCK `"A`"`r`n"
        $docs = [ordered]@{
            'paren' = $head + (('(* never closed ' + "`r`n") * 20000)
            'slash' = $head + (('/* never closed ' + "`r`n") * 20000)
            'pragma' = $head + (('{ never closed ' + "`r`n") * 20000)
            'quote' = $head + (('{ S7_T := "never closed ' + "`r`n") * 20000)
            'text' = $head + (("x := '`$" + "`r`n") * 20000)
            'after' = $head + "END_FUNCTION_BLOCK`r`n" + (('// a comment line ' + "`r`n") * 20000)
        }
        $files = @(foreach ($k in $docs.Keys) { $f = Join-Path $TestDrive "open_$k.s7dcl"; Write-TextFile $f $docs[$k]; $f })
        $job = Start-Job -ArgumentList (Join-Path $here '..\Repo.ps1'), $files -ScriptBlock {
            param($repo, $paths)
            . $repo
            foreach ($p in $paths) { "[$(Get-DocumentSecondDeclaration $p)]" }
        }
        try {
            $finished = Wait-Job $job -Timeout 30
            $finished | Should Not BeNullOrEmpty
            (Receive-Job $job) -join '' | Should Be ('[]' * $files.Count)
        }
        finally { Remove-Job $job -Force }
    }
}

# Each kind lists its own objects only, and block and db share plc\blocks: the wrong kind saw no existing object, so no guard
# fired, and TIA, going by the document, answers the test instance in work with its modal message.
Describe 'import under the wrong kind, or of a name another kind holds' {
    $script:repo = Join-Path $TestDrive 'K'
    $fbDoc = "FUNCTION_BLOCK `"Fb1`"`r`nEND_FUNCTION_BLOCK"
    $dbDoc = "DATA_BLOCK `"Db1`" : `"Fb1`"`r`nEND_DATA_BLOCK"
    $udtDoc = "TYPE`r`n    Udt1 : STRUCT`r`n    END_STRUCT;`r`nEND_TYPE"
    Write-TextFile (Join-Path $script:repo 'plc\blocks\Fb1.s7dcl') $fbDoc
    Write-TextFile (Join-Path $script:repo 'plc\blocks\Fb1Lower.s7dcl') "function_block `"Fb1`"`r`nend_function_block"
    Write-TextFile (Join-Path $script:repo 'plc\blocks\Db1.s7dcl') $dbDoc
    Write-TextFile (Join-Path $script:repo 'plc\blocks\Db1Xml.xml') '<Document><SW.Blocks.InstanceDB ID="0"><AttributeList><Name>Db1</Name></AttributeList></SW.Blocks.InstanceDB></Document>'
    Write-TextFile (Join-Path $script:repo 'plc\blocks\Fb1Xml.xml') '<Document><SW.Blocks.FB ID="0"><AttributeList><Name>Fb1</Name></AttributeList></SW.Blocks.FB></Document>'
    Write-TextFile (Join-Path $script:repo 'plc\blocks\Fb1AsDb.s7dcl') "DATA_BLOCK `"Fb1`"`r`nEND_DATA_BLOCK"
    Write-TextFile (Join-Path $script:repo 'plc\blocks\Db1AsFb.s7dcl') "FUNCTION_BLOCK `"Db1`"`r`nEND_FUNCTION_BLOCK"
    Write-TextFile (Join-Path $script:repo 'plc\blocks\Udt1.s7dcl') $udtDoc
    Write-TextFile (Join-Path $script:repo 'plc\types\Udt1.s7dcl') $udtDoc
    Write-TextFile (Join-Path $script:repo 'plc\types\Fb1.s7dcl') $fbDoc
    Write-TextFile (Join-Path $script:repo 'plc\blocks\NoName.s7dcl') 'no block here'
    Write-TextFile (Join-Path $script:repo 'plc\blocks\Two.s7dcl') "$fbDoc`r`n{ S7_Safety := `"True`" }`r`nFUNCTION_BLOCK `"FFb`"`r`nEND_FUNCTION_BLOCK"
    Write-TextFile (Join-Path $script:repo 'plc\blocks\TwoXml.xml') '<Document><SW.Blocks.FB ID="0"><AttributeList><Name>Fb1</Name></AttributeList></SW.Blocks.FB><SW.Blocks.FB ID="1"><AttributeList><Name>FFb</Name></AttributeList></SW.Blocks.FB></Document>'
    Write-TextFile (Join-Path $script:repo 'plc\blocks\Fresh.s7dcl') "FUNCTION_BLOCK `"Fresh`"`r`nEND_FUNCTION_BLOCK"
    Write-TextFile (Join-Path $script:repo 'plc\blocks\FreshDb.s7dcl') "DATA_BLOCK `"FreshDb`"`r`nEND_DATA_BLOCK"
    Write-TextFile (Join-Path $script:repo 'plc\blocks\Fb1.txt') '<Document><SW.Blocks.FB ID="0"><AttributeList><Name>Fb1</Name></AttributeList></SW.Blocks.FB></Document>'
    Write-TextFile (Join-Path $script:repo 'plc\blocks\Unread.s7dcl') "(* (* nested *) *)`r`nFUNCTION_BLOCK `"Fb1`"`r`nEND_FUNCTION_BLOCK"
    Write-TextFile (Join-Path $script:repo 'plc\blocks\NoNameUdt.s7dcl') "TYPE`r`n: STRUCT`r`nEND_TYPE"
    Write-TextFile (Join-Path $script:repo 'plc\blocks\OneLineOb.s7dcl') "/* note */ ORGANIZATION_BLOCK `"Ob1`"`r`nEND_ORGANIZATION_BLOCK"
    Write-TextFile (Join-Path $script:repo 'library\types\Db\Lib1.s7dcl') "DATA_BLOCK `"Lib1`"`r`nEND_DATA_BLOCK"
    Write-TextFile (Join-Path $script:repo 'library\types\Two\Lib1.s7dcl') "FUNCTION_BLOCK `"Lib1`"`r`nEND_FUNCTION_BLOCK`r`nFUNCTION_BLOCK `"Lib2`"`r`nEND_FUNCTION_BLOCK"
    Write-TextFile (Join-Path $script:repo 'library\types\Safe\Lib1.s7dcl') "{ S7_Safety := `"True`" }`r`nFUNCTION_BLOCK `"Lib1`"`r`nEND_FUNCTION_BLOCK"
    Write-TextFile (Join-Path $script:repo 'library\types\Safe\Lib1.libinfo') 'LibraryVersion:'
    Write-TextFile (Join-Path $script:repo 'plc\blocks\Fb1.libinfo') 'LibraryVersion:'
    Write-TextFile (Join-Path $script:repo 'plc\blocks\Lone.libinfo') 'LibraryVersion:'
    $tableXml = '<Document><SW.Tags.PlcTagTable ID="0"><AttributeList><Name>Tags1</Name></AttributeList></SW.Tags.PlcTagTable></Document>'
    $screenXml = '<Document><Hmi.Screen.Screen ID="0"><AttributeList><Name>Screen1</Name></AttributeList></Hmi.Screen.Screen></Document>'
    Write-TextFile (Join-Path $script:repo 'plc\tags\Tags1.xml') $tableXml
    Write-TextFile (Join-Path $script:repo 'plc\tags\Screen1.xml') $screenXml
    Write-TextFile (Join-Path $script:repo 'plc\tags\Watch1.xml') '<Document><SW.WatchAndForceTables.PlcWatchTable ID="0"><AttributeList><Name>Watch1</Name></AttributeList></SW.WatchAndForceTables.PlcWatchTable></Document>'
    Write-TextFile (Join-Path $script:repo 'library\types\Table\Lib1.xml') $tableXml.Replace('Tags1', 'Lib1')
    Write-TextFile (Join-Path $script:repo 'library\types\Screen\Lib1.xml') $screenXml.Replace('Screen1', 'Lib1')
    Write-TextFile (Join-Path $script:repo 'library\types\Watch\Lib1.xml') (Get-Content (Join-Path $script:repo 'plc\tags\Watch1.xml') -Raw).Replace('Watch1', 'Lib1')
    Write-TextFile (Join-Path $script:repo 'plc\tags\Force1.xml') '<Document><SW.WatchAndForceTables.PlcForceTable ID="0"><AttributeList><Name>Force1</Name></AttributeList></SW.WatchAndForceTables.PlcForceTable></Document>'
    Write-TextFile (Join-Path $script:repo 'library\types\Force\Lib1.xml') (Get-Content (Join-Path $script:repo 'plc\tags\Force1.xml') -Raw).Replace('Force1', 'Lib1')
    # as Python's ElementTree writes them back: a tag table declaring utf-8-sig, an OB with its namespaces as prefixes
    Write-TextFile (Join-Path $script:repo 'plc\tags\SigTags.xml') "<?xml version=`"1.0`" encoding=`"utf-8-sig`"?>`r`n$tableXml"
    Write-TextFile (Join-Path $script:repo 'plc\blocks\TreeOb.xml') ("<?xml version='1.0' encoding='utf-8'?>`n<Document xmlns:ns0=`"http://www.siemens.com/automation/Openness/SW/Interface/v5`">`n" +
        '<SW.Blocks.OB ID="0"><AttributeList><Interface><ns0:Sections /></Interface><Name>Ob1</Name></AttributeList></SW.Blocks.OB></Document>')
    Write-TextFile (Join-Path $script:repo 'library\types\Sig\Lib1.xml') ('<?xml version="1.0" encoding="utf-8-sig"?>' + (Get-Content (Join-Path $script:repo 'plc\blocks\Fb1Xml.xml') -Raw).Replace('Fb1', 'Lib1'))

    function Invoke-KindImport([string]$Kind, [string]$Path, [object[]]$Objects) {
        $list = New-Object System.Collections.ArrayList
        foreach ($o in $Objects) { [void]$list.Add($o) }
        Add-Member -InputObject $list ScriptMethod ImportFromDocuments {
            param($dir, $name, $options)
            $script:imported += @($name)
            [pscustomobject]@{}
        }
        Add-Member -InputObject $list ScriptMethod Import {
            param($file, $options)
            $script:imported += @($file.Name)
            @()
        }
        $group = [pscustomobject]@{ Blocks = $list; Types = $list; TagTables = $list; Groups = @() }
        $script:root = [pscustomobject]@{ BlockGroup = $group; TypeGroup = $group; TagTableGroup = $group }
        Invoke-FileImport $Kind @($Path)
    }
    function New-Block([string]$Name, [string]$Class = 'FB', $Extra = @{}) {
        $p = @{ Name = $Name; ProgrammingLanguage = 'LAD'; IsKnowHowProtected = $false; Link = $null; Class = $Class }
        foreach ($key in $Extra.Keys) { $p[$key] = $Extra[$key] }
        [pscustomobject]$p
    }
    $inWork = @{ Link = @{ inWork = $true; type = 'Fb1'; version = '1.0.1' } }

    It 'refuses kind db with the document of an FB, the test instance of a type in work' {
        $r = Invoke-KindImport 'db' 'plc\blocks\Fb1.s7dcl' @(New-Block 'Fb1' 'FB' $inWork)
        $r.ok | Should Be $false
        $r.items[0].refused | Should Match 'holds an FB or FC'
        $r.items[0].refused | Should Match 'kind block'
        @($script:imported).Count | Should Be 0
    }

    It 'refuses it the same way with a keyword in lower case, under another file name' {
        $r = Invoke-KindImport 'db' 'plc\blocks\Fb1Lower.s7dcl' @(New-Block 'Fb1' 'FB' $inWork)
        $r.items[0].name | Should Be 'Fb1'
        $r.items[0].refused | Should Match 'kind block'
        @($script:imported).Count | Should Be 0
    }

    It 'refuses each document under a kind that is not its own, also as SimaticML' {
        foreach ($case in @(
            @('block', 'plc\blocks\Db1.s7dcl', 'kind db'),
            @('block', 'plc\blocks\Db1Xml.xml', 'kind db'),
            @('db', 'plc\blocks\Fb1Xml.xml', 'kind block'),
            @('block', 'plc\blocks\Udt1.s7dcl', 'kind type'),
            @('db', 'plc\blocks\Udt1.s7dcl', 'kind type'),
            @('type', 'plc\types\Fb1.s7dcl', 'kind block'),
            @('plc_tag_table', 'plc\blocks\Fb1Xml.xml', 'kind block'))) {
            $r = Invoke-KindImport $case[0] $case[1] @()
            $r.ok | Should Be $false
            $r.items[0].refused | Should Match $case[2]
            @($script:imported).Count | Should Be 0
        }
    }

    It 'refuses a DB document of a name that is an FB in the project, and the other way round' {
        $r = Invoke-KindImport 'db' 'plc\blocks\Fb1AsDb.s7dcl' @(New-Block 'Fb1' 'FB' $inWork)
        $r.items[0].refused | Should Match "'Fb1'.*kind block"
        @($script:imported).Count | Should Be 0
        $r = Invoke-KindImport 'block' 'plc\blocks\Db1AsFb.s7dcl' @(New-Block 'db1' 'InstanceDB')
        $r.items[0].refused | Should Match "'Db1'.*kind db"
        @($script:imported).Count | Should Be 0
    }

    It 'imports each document under its own kind' {
        (Invoke-KindImport 'block' 'plc\blocks\Fb1.s7dcl' @(New-Block 'Fb1')).ok | Should Be $true
        $script:imported -join ',' | Should Be 'Fb1'
        (Invoke-KindImport 'db' 'plc\blocks\Db1.s7dcl' @((New-Block 'Db1' 'InstanceDB'), (New-Block 'Fb1'))).ok | Should Be $true
        (Invoke-KindImport 'db' 'plc\blocks\Db1Xml.xml' @(New-Block 'Db1' 'InstanceDB')).ok | Should Be $true
        (Invoke-KindImport 'type' 'plc\types\Udt1.s7dcl' @(New-Block 'Udt1')).ok | Should Be $true
        (Invoke-KindImport 'block' 'plc\blocks\Fresh.s7dcl' @(New-Block 'Fb1')).ok | Should Be $true
        (Invoke-KindImport 'db' 'plc\blocks\FreshDb.s7dcl' @(New-Block 'Fb1')).ok | Should Be $true
    }

    It 'refuses SimaticML TIA would refuse for how it is written, naming the line, and imports nothing' {
        $r = Invoke-KindImport 'plc_tag_table' 'plc\tags\SigTags.xml' @()
        $r.ok | Should Be $false
        $r.items[0].refused | Should Match "line 1 declares encoding 'utf-8-sig'"
        $r = Invoke-KindImport 'block' 'plc\blocks\TreeOb.xml' @()
        $r.items[0].refused | Should Match "line 2 holds the namespace prefix 'ns0'"
        @($script:imported).Count | Should Be 0
        $r = Invoke-LibraryImport @('Lib1') @('library\types\Sig\Lib1.xml')
        $r.items[0].refused | Should Match 'utf-8-sig'
        @($script:created).Count | Should Be 0
        $file = @(Resolve-ImportFiles -Repo $script:repo -KindDir 'library\types' -Paths @('library\types\Sig\Lib1.xml'))[0]
        (Get-NewTypeDocument $file $false).refused | Should Match 'utf-8-sig'
    }

    It 'leaves a document it cannot read to TIA, by its file name' {
        (Invoke-KindImport 'db' 'plc\blocks\NoName.s7dcl' @()).ok | Should Be $true
    }

    It 'refuses a document with a second declaration, naming both' {
        foreach ($path in 'plc\blocks\Two.s7dcl', 'plc\blocks\TwoXml.xml') {
            $r = Invoke-KindImport 'block' $path @(New-Block 'Fb1')
            $r.ok | Should Be $false
            $r.items[0].refused | Should Match "declares 'Fb1' and also 'FFb'"
            @($script:imported).Count | Should Be 0
        }
    }

    It 'refuses a file that is no document, which TIA would read as SimaticML' {
        $r = Invoke-KindImport 'db' 'plc\blocks\Fb1.txt' @(New-Block 'Fb1' 'FB' $inWork)
        $r.items[0].refused | Should Match 'is no document'
        @($script:imported).Count | Should Be 0
    }

    It 'refuses a .libinfo under a kind of PLC objects, with or without a document beside it: only a library type goes by it' {
        foreach ($case in @(@('block', 'plc\blocks\Fb1.libinfo'), @('block', 'plc\blocks\Lone.libinfo'), @('db', 'plc\blocks\Lone.libinfo'), @('type', 'plc\blocks\Lone.libinfo'))) {
            $r = Invoke-KindImport $case[0] $case[1] @()
            $r.ok | Should Be $false
            $r.items[0].refused | Should Match 'is no document'
            @($script:imported).Count | Should Be 0
        }
    }

    It 'refuses a SimaticML tag table, watch table, force table or HMI document under a kind of other objects' {
        foreach ($case in @(
            @('block', 'plc\tags\Watch1.xml', 'holds a watch table.*kind watch_table'),
            @('plc_tag_table', 'plc\tags\Watch1.xml', 'holds a watch table.*kind watch_table'),
            @('watch_table', 'plc\tags\Tags1.xml', 'holds a PLC tag table.*kind plc_tag_table'),
            @('watch_table', 'plc\tags\Screen1.xml', 'holds an HMI object'),
            @('block', 'plc\tags\Force1.xml', 'holds a force table.*kind force_table'),
            @('plc_tag_table', 'plc\tags\Force1.xml', 'holds a force table.*kind force_table'),
            @('watch_table', 'plc\tags\Force1.xml', 'holds a force table.*kind force_table'),
            @('force_table', 'plc\tags\Tags1.xml', 'holds a PLC tag table.*kind plc_tag_table'),
            @('force_table', 'plc\tags\Screen1.xml', 'holds an HMI object'),
            @('block', 'plc\tags\Tags1.xml', 'holds a PLC tag table.*kind plc_tag_table'),
            @('db', 'plc\tags\Tags1.xml', 'holds a PLC tag table.*kind plc_tag_table'),
            @('type', 'plc\tags\Tags1.xml', 'holds a PLC tag table.*kind plc_tag_table'),
            @('block', 'plc\tags\Screen1.xml', 'holds an HMI object'),
            @('db', 'plc\tags\Screen1.xml', 'holds an HMI object'),
            @('type', 'plc\tags\Screen1.xml', 'holds an HMI object'),
            @('plc_tag_table', 'plc\tags\Screen1.xml', 'holds an HMI object'))) {
            $r = Invoke-KindImport $case[0] $case[1] @()
            $r.ok | Should Be $false
            $r.items[0].refused | Should Match $case[2]
            @($script:imported).Count | Should Be 0
        }
    }

    It 'imports a SimaticML tag table under its own kind' {
        (Invoke-KindImport 'plc_tag_table' 'plc\tags\Tags1.xml' @()).ok | Should Be $true
        $script:imported -join ',' | Should Be 'Tags1.xml'
    }

    It 'refuses a tag table, watch table, force table or HMI document for a library type, new or in work' {
        foreach ($path in 'library\types\Table\Lib1.xml', 'library\types\Screen\Lib1.xml', 'library\types\Watch\Lib1.xml', 'library\types\Force\Lib1.xml') {
            $r = Invoke-LibraryImport @('Lib1') @($path)
            $r.items[0].refused | Should Match 'a library type is a PLC data type, an FB or an FC'
            @($script:created).Count | Should Be 0
            $file = @(Resolve-ImportFiles -Repo $script:repo -KindDir 'library\types' -Paths @($path))[0]
            (Get-NewTypeDocument $file $false).refused | Should Match 'a library type is a PLC data type, an FB or an FC'
        }
    }

    It 'refuses a keyword whose object it cannot read, as the file name would then stand for the object' {
        foreach ($path in 'plc\blocks\Unread.s7dcl', 'plc\blocks\NoNameUdt.s7dcl') {
            $r = Invoke-KindImport 'db' $path @(New-Block 'Fb1' 'FB' $inWork)
            $r.items[0].refused | Should Match 'cannot read the object'
            @($script:imported).Count | Should Be 0
        }
    }

    It 'refuses the .s7dcl of an OB whose keyword stands after a comment on its line' {
        $r = Invoke-KindImport 'block' 'plc\blocks\OneLineOb.s7dcl' @()
        $r.items[0].refused | Should Match 'event class'
        @($script:imported).Count | Should Be 0
    }

    It 'refuses a DB document under a library type of its name' {
        $r = Invoke-LibraryImport @('Lib1') @('library\types\Db\Lib1.s7dcl')
        $r.items[0].refused | Should Match 'holds a DB'
        @($script:created).Count | Should Be 0
    }

    It 'refuses a second declaration in the document of a library type' {
        $r = Invoke-LibraryImport @('Lib1') @('library\types\Two\Lib1.s7dcl')
        $r.items[0].refused | Should Match "declares 'Lib1' and also 'Lib2'"
        @($script:created).Count | Should Be 0
    }

    It 'reads the documents beside the .libinfo of a library type: an F-block is refused by it too' {
        $r = Invoke-LibraryImport @('Lib1') @('library\types\Safe\Lib1.libinfo')
        $r.items[0].refused | Should Match 'safety: true'
        @($script:created).Count | Should Be 0
    }

    It 'refuses a second declaration for a new library type' {
        $file = @(Resolve-ImportFiles -Repo $script:repo -KindDir 'library\types' -Paths @('library\types\Two\Lib1.s7dcl'))[0]
        (Get-NewTypeDocument $file $false).refused | Should Match "declares 'Lib1' and also 'Lib2'"
    }
}
