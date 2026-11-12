# library_create_type and library_discard_type (no TIA): what the document is, what is refused before TIA is touched,
# where the test instance goes, and what the save rules hold afterwards.
$here = Split-Path -Parent $MyInvocation.MyCommand.Path
foreach ($f in 'Mcp.ps1', 'Tia.ps1', 'Repo.ps1', 'Rules.ps1', 'Guards.ps1', 'Bridge.ps1', 'Tools\Objects.ps1', 'Tools\Plc.ps1', 'Tools\Library.ps1', 'Tools\LibraryChange.ps1') {
    . (Join-Path $here "..\$f")
}
if (-not ('Siemens.Engineering.Library.Types.CreateOptions' -as [type])) {
    Add-Type -TypeDefinition 'namespace Siemens.Engineering.Library.Types { public enum CreateOptions { Override } } namespace Siemens.Engineering.Library { public enum LibraryImportOptions { None } }'
}

function Write-Doc([string]$Path, [string]$Text) {
    New-Item -ItemType Directory -Force -Path ([System.IO.Path]::GetDirectoryName($Path)) | Out-Null
    [System.IO.File]::WriteAllText($Path, $Text)
    $Path
}

function New-FileEntry([string]$Path) { @(Resolve-ImportFiles -Repo $TestDrive -KindDir 'library\types' -Paths @($Path))[0] }

Describe 'Get-DocumentObjectClass' {
    $cases = @(
        @{ text = "TYPE`r`n    A : STRUCT`r`n    END_STRUCT;`r`nEND_TYPE`r`n"; class = 'type' }
        @{ text = "TYPE`r`n    { S7_Safety := `"True`" }`r`n    `"Ns:A`" : STRUCT`r`n    END_STRUCT;`r`nEND_TYPE`r`n"; class = 'type' }
        @{ text = "{`r`n    S7_Optimized := `"TRUE`"`r`n}`r`nFUNCTION `"A`" : Void`r`nEND_FUNCTION`r`n"; class = 'block' }
        @{ text = "FUNCTION_BLOCK `"A`"`r`nEND_FUNCTION_BLOCK`r`n"; class = 'block' }
        @{ text = "ORGANIZATION_BLOCK `"A`"`r`nEND_ORGANIZATION_BLOCK`r`n"; class = 'OB' }
        @{ text = "DATA_BLOCK `"A`"`r`nEND_DATA_BLOCK`r`n"; class = 'DB' }
        @{ text = "// TYPE in a comment`r`nFUNCTION `"A`" : Void`r`nEND_FUNCTION`r`n"; class = 'block' }
        @{ text = "nothing to read"; class = '' }
    )
    It 'reads a .s7dcl by its keyword: <class>' -TestCases $cases {
        param($text, $class)
        Get-DocumentObjectClass (Write-Doc (Join-Path $TestDrive 'c\A.s7dcl') $text) | Should Be $class
    }

    $xml = @(
        @{ node = 'SW.Types.PlcStruct'; class = 'type' }, @{ node = 'SW.Blocks.FB'; class = 'block' }, @{ node = 'SW.Blocks.FC'; class = 'block' }
        @{ node = 'SW.Blocks.OB'; class = 'OB' }, @{ node = 'SW.Blocks.GlobalDB'; class = 'DB' }, @{ node = 'SW.Blocks.InstanceDB'; class = 'DB' }
        @{ node = 'SW.WatchAndForceTables.PlcWatchTable'; class = 'watch' }, @{ node = 'SW.WatchAndForceTables.PlcForceTable'; class = '' }
    )
    It 'reads a SimaticML by its node: <node>' -TestCases $xml {
        param($node, $class)
        Get-DocumentObjectClass (Write-Doc (Join-Path $TestDrive 'c\A.xml') "<Document><$node><AttributeList><Name>A</Name></AttributeList></$node></Document>") | Should Be $class
    }

    It 'says nothing of a document it cannot read' {
        Get-DocumentObjectClass (Write-Doc (Join-Path $TestDrive 'c\Bad.xml') 'no xml') | Should Be ''
        Get-DocumentObjectClass (Join-Path $TestDrive 'c\Missing.s7dcl') | Should Be ''
    }
}

Describe 'Get-NewTypeDocument' {
    It 'refuses a file that is not there' {
        (Get-NewTypeDocument (New-FileEntry (Join-Path $TestDrive 'n\None.s7dcl')) $false).refused | Should Match 'File not found'
    }
    It 'refuses the export of a released version' {
        $p = Write-Doc (Join-Path $TestDrive 'r\A.released\A.s7dcl') "TYPE`r`n    A : STRUCT`r`n    END_STRUCT;`r`nEND_TYPE`r`n"
        (Get-NewTypeDocument (New-FileEntry $p) $false).refused | Should Match 'released'
    }
    It 'refuses a folder holding both formats' {
        $p = Write-Doc (Join-Path $TestDrive 'b\A.s7dcl') "TYPE`r`n    A : STRUCT`r`n    END_STRUCT;`r`nEND_TYPE`r`n"
        $null = Write-Doc (Join-Path $TestDrive 'b\A.xml') '<Document />'
        (Get-NewTypeDocument (New-FileEntry $p) $false).refused | Should Match 'both'
    }
    It 'refuses an OB and a DB, naming what the file holds' {
        (Get-NewTypeDocument (New-FileEntry (Write-Doc (Join-Path $TestDrive 'o\A.s7dcl') "ORGANIZATION_BLOCK `"A`"`r`nEND_ORGANIZATION_BLOCK`r`n")) $false).refused | Should Match 'holds an OB'
        (Get-NewTypeDocument (New-FileEntry (Write-Doc (Join-Path $TestDrive 'd\A.s7dcl') "DATA_BLOCK `"A`"`r`nEND_DATA_BLOCK`r`n")) $false).refused | Should Match 'holds a DB'
    }
    It 'refuses a document it cannot read a name from' {
        (Get-NewTypeDocument (New-FileEntry (Write-Doc (Join-Path $TestDrive 'u\A.s7dcl') 'nothing')) $false).refused | Should Match 'declares no object'
    }
    It 'refuses the document of an F-block or F-compliant data type without safety, and takes it with' {
        $fb = New-FileEntry (Write-Doc (Join-Path $TestDrive 'f\A.s7dcl') "{`r`n    S7_Safety := `"True`"`r`n}`r`nFUNCTION `"A`" : Void`r`nEND_FUNCTION`r`n")
        (Get-NewTypeDocument $fb $false).refused | Should Match 'safety program'
        (Get-NewTypeDocument $fb $true).name | Should Be 'A'
        $ft = New-FileEntry (Write-Doc (Join-Path $TestDrive 'g\B.s7dcl') "TYPE`r`n    { S7_Safety := `"True`" }`r`n    B : STRUCT`r`n    END_STRUCT;`r`nEND_TYPE`r`n")
        (Get-NewTypeDocument $ft $false).refused | Should Match 'safety program'
    }
    It 'goes by the name the document declares, not the file name' {
        $d = Get-NewTypeDocument (New-FileEntry (Write-Doc (Join-Path $TestDrive 'k\Ns_A.s7dcl') "TYPE`r`n    `"Ns:A`" : STRUCT`r`n    END_STRUCT;`r`nEND_TYPE`r`n")) $false
        $d.name | Should Be 'Ns:A'
        $d.class | Should Be 'type'
        $d.format | Should Be 's7dcl'
    }
    It 'takes a SimaticML' {
        $d = Get-NewTypeDocument (New-FileEntry (Write-Doc (Join-Path $TestDrive 'x\A.xml') '<Document><SW.Blocks.FC><AttributeList><Name>A</Name></AttributeList></SW.Blocks.FC></Document>')) $false
        $d.name | Should Be 'A'; $d.class | Should Be 'block'; $d.format | Should Be 'xml'
    }
}

Describe 'Invoke-LibraryCreateTool' {
    function Get-BridgeSession { $script:state }
    function Get-TiaProject { }
    function Add-LibraryLog { }
    function ConvertTo-ResultTree { @{ state = 'Success'; messages = @() } }
    function Get-TypeInstances { @() }
    function Get-TiaSoftwareEntry { @{ device = 'Plc1'; software = [pscustomobject]@{ TypeGroup = 'typeGroup'; BlockGroup = 'blockGroup' } } }
    function Get-OrCreateGroup { param($Root, $Folder, $Prop) if ($Prop -eq 'Folders') { $script:libraryFolderAsked = $Folder; $Root } else { "$Root/$Folder" } }
    function Invoke-TiaWrite { param($Description, $Body) if ($script:commitError) { & $Body | Out-Null; return @{ commitError = @{ message = 'no commit' }; rolledBack = $true; transaction = $true } }; @{ output = @(& $Body); transaction = $true } }
    function Get-TiaLibrary { $script:lib }

    function New-Type([string]$Name) {
        [pscustomobject]@{ Name = $Name; Versions = @([pscustomobject]@{ VersionNumber = [version]'0.0.1'; State = 'InWork'; IsDefault = $false }) }
    }
    function Reset-Fake {
        $script:state = New-SessionState; Register-Archive $script:state
        $script:createCall = $null; $script:createFails = $false; $script:createLeavesType = $false; $script:commitError = $false
        $script:createState = 'Success'; $script:createdName = 'A'; $script:libraryFolderAsked = $null
        $types = New-Object System.Collections.ArrayList
        Add-Member -InputObject $types ScriptMethod CreateFromDocuments { param($d, $n, $t, $o)
            $script:createCall = @{ dir = $d.FullName; name = $n; target = $t; options = [string]$o }
            if ($script:createFails) { if ($script:createLeavesType) { $null = $script:libTypes.Add((New-Type 'A')) }; throw 'The import failed. An instance with the same name already exists.' }
            $null = $script:libTypes.Add((New-Type $script:createdName))
            [pscustomobject]@{ TransferResultState = $script:createState; CreatedType = [pscustomobject]@{ Name = $script:createdName } } }
        $script:libTypes = $types
        $script:lib = [pscustomobject]@{ TypeFolder = [pscustomobject]@{ Types = $types; Folders = @() } }
        $script:Bridge = @{ repo = [string]$TestDrive; settings = @{} }
    }
    $udt = Write-Doc (Join-Path $TestDrive 'lib\A\A.s7dcl') "TYPE`r`n    A : STRUCT`r`n    END_STRUCT;`r`nEND_TYPE`r`n"
    $fc = Write-Doc (Join-Path $TestDrive 'lib\F\F.s7dcl') "FUNCTION `"F`" : Void`r`nEND_FUNCTION`r`n"
    function Args-Of($Hash) { [pscustomobject]$Hash }

    It 'is refused before the session archive, TIA untouched' {
        Reset-Fake
        $script:state = New-SessionState
        (Invoke-LibraryCreateTool (Args-Of @{ path = $udt })).refused | Should Match 'session archive'
        $script:createCall | Should Be $null
    }
    It 'needs a path' {
        Reset-Fake
        (Invoke-LibraryCreateTool (Args-Of @{ })).refused | Should Match 'path is required'
    }
    It 'gives a data type the type group as its target, with the folder asked for' {
        Reset-Fake
        $r = Invoke-LibraryCreateTool (Args-Of @{ path = $udt; target_folder = 'zz/sub'; library_folder = 'lib/sub' })
        $r.ok | Should Be $true
        $script:createCall.target | Should Be 'typeGroup/zz/sub'
        $script:createCall.name | Should Be 'A'
        $script:createCall.options | Should Be 'None'
        $script:libraryFolderAsked | Should Be 'lib/sub'
        $r.version | Should Be '0.0.1'
        $r.type | Should Be 'A'
    }
    It 'gives a block the block group as its target' {
        Reset-Fake
        $script:createdName = 'F'
        $null = Invoke-LibraryCreateTool (Args-Of @{ path = $fc })
        $script:createCall.target | Should Be 'blockGroup/'
    }
    It 'takes a path relative to the repo' {
        Reset-Fake
        (Invoke-LibraryCreateTool (Args-Of @{ path = 'lib\A\A.s7dcl' })).ok | Should Be $true
    }
    It 'refuses a name the library has, in any case, TIA untouched' {
        Reset-Fake
        $null = $script:libTypes.Add((New-Type 'a'))
        (Invoke-LibraryCreateTool (Args-Of @{ path = $udt })).refused | Should Match "Library type 'a' exists"
        $script:createCall | Should Be $null
    }
    It 'holds the new type for the compile until a compile by its name' {
        Reset-Fake
        $null = Invoke-LibraryCreateTool (Args-Of @{ path = $udt })
        @($script:state.pending.Values) | Should Be 'plc@Plc1:type:A'
        Register-Compile $script:state 'plc' 'Plc1' @('A') 0
        @($script:state.pending.Values).Count | Should Be 0
    }
    It 'lets a failure that left no type hold nothing, and quotes TIA by throwing' {
        Reset-Fake
        $script:createFails = $true
        { Invoke-LibraryCreateTool (Args-Of @{ path = $udt }) } | Should Throw 'An instance with the same name already exists'
        @($script:state.failed.Keys).Count | Should Be 0
        @($script:state.pending.Keys).Count | Should Be 0
    }
    It 'remembers a failure that left the type' {
        Reset-Fake
        $script:createFails = $true; $script:createLeavesType = $true
        { Invoke-LibraryCreateTool (Args-Of @{ path = $udt }) } | Should Throw
        @($script:state.failed.Values) | Should Be 'plc@Plc1:type:A'
    }
    It 'holds nothing when TIA refuses the commit' {
        Reset-Fake
        $script:commitError = $true
        $r = Invoke-LibraryCreateTool (Args-Of @{ path = $udt })
        $r.ok | Should Be $false
        $r.note | Should Match 'nothing of A was kept'
        @($script:state.pending.Keys).Count | Should Be 0
    }
    It 'says so when TIA creates it with a warning' {
        Reset-Fake
        $script:createState = 'Warning'
        $r = Invoke-LibraryCreateTool (Args-Of @{ path = $udt })
        $r.ok | Should Be $true
        $r.state | Should Be 'Warning'
        $r.summary | Should Match 'state Warning'
    }
    It 'says so when TIA names it otherwise' {
        Reset-Fake
        $script:createdName = 'Other'
        $r = Invoke-LibraryCreateTool (Args-Of @{ path = $udt })
        $r.note | Should Match "named the type 'Other'"
    }
    It 'gives TIA CRLF for a file written with LF, and says so' {
        Reset-Fake
        $lf = Write-Doc (Join-Path $TestDrive 'lib\L\A.s7dcl') "TYPE`n    A : STRUCT`n    END_STRUCT;`nEND_TYPE`n"
        $r = Invoke-LibraryCreateTool (Args-Of @{ path = $lf })
        $r.lineEnds | Should Match 'CRLF'
        [System.IO.File]::ReadAllText($lf) | Should Match "TYPE`r`n"
    }
}

Describe 'Invoke-LibraryDiscardTool' {
    function Get-BridgeSession { $script:state }
    function Add-LibraryLog { }
    function Get-TiaDeviceNames { @('Plc1') }
    function Get-TiaLibrary { $script:lib }
    function Invoke-TiaWrite { param($Description, $Body) $null = & $Body; @{ output = @(); transaction = $true } }
    function Get-TypeInstances { @($script:instances) }
    function Get-LiveChange { $script:change }
    function Save-ChangeRecord { $script:changeSaved = $true; 'report.md' }

    function Set-Fake([bool]$Released = $false, [string]$Class = 'PlcTypeLibraryType') {
        $script:state = New-SessionState; Register-Archive $script:state
        $script:instances = @(); $script:change = $null; $script:changeSaved = $false; $script:discardFails = $false
        $work = [pscustomobject]@{ VersionNumber = [version]'0.0.2'; State = 'InWork'; IsDefault = $false }
        $work | Add-Member ScriptMethod Discard { if ($script:discardFails) { throw 'TIA said no.' }; $script:typeObject.Versions = @($script:typeObject.Versions | Where-Object { [string]$_.State -ne 'InWork' }); if (-not @($script:typeObject.Versions).Count) { $script:lib.TypeFolder.Types = @() } }
        $versions = @($work)
        if ($Released) { $versions = @([pscustomobject]@{ VersionNumber = [version]'0.0.1'; State = 'Committed'; IsDefault = $true }) + $versions }
        $script:typeObject = [pscustomobject]@{ Name = 'A'; Versions = $versions }
        $script:typeObject.PSObject.TypeNames.Insert(0, $Class)
        $script:lib = [pscustomobject]@{ TypeFolder = [pscustomobject]@{ Types = @($script:typeObject); Folders = @() } }
    }
    function Get-LibraryTypeScope { $script:scope }
    function Instance($Language, $Knowhow) { @{ name = 'A'; info = [pscustomobject]@{ LibraryTypeInstance = [pscustomobject]@{ ProgrammingLanguage = $Language; IsKnowHowProtected = $Knowhow } } } }
    function Args-Of($Hash) { [pscustomobject]$Hash }
    $script:scope = 'plc'

    It 'is refused before the session archive' {
        Set-Fake
        $script:state = New-SessionState
        (Invoke-LibraryDiscardTool (Args-Of @{ name = 'A' })).refused | Should Match 'session archive'
        @($script:typeObject.Versions).Count | Should Be 1
    }
    It 'names a type the library does not have' {
        Set-Fake
        { Invoke-LibraryDiscardTool (Args-Of @{ name = 'B' }) } | Should Throw "No library type named 'B'"
    }
    It 'refuses a type with nothing in work' {
        Set-Fake
        $script:typeObject.Versions = @([pscustomobject]@{ VersionNumber = [version]'0.0.1'; State = 'Committed'; IsDefault = $true })
        (Invoke-LibraryDiscardTool (Args-Of @{ name = 'A' })).refused | Should Match 'nothing to discard'
    }
    It 'refuses an HMI type, whose discard was never tried' {
        Set-Fake
        $script:scope = 'hmi'
        try { (Invoke-LibraryDiscardTool (Args-Of @{ name = 'A' })).refused | Should Match 'faceplate' }
        finally { $script:scope = 'plc' }
    }
    It 'refuses an F-block instance without safety, and takes it with' {
        Set-Fake $true
        $script:instances = @(Instance 'F_LAD' $false)
        (Invoke-LibraryDiscardTool (Args-Of @{ name = 'A' })).refused | Should Match 'safety program'
        (Invoke-LibraryDiscardTool (Args-Of @{ name = 'A'; safety = $true })).ok | Should Be $true
    }
    It 'refuses a know-how protected instance without knowhow, and takes it with' {
        Set-Fake $true
        $script:instances = @(Instance 'LAD' $true)
        (Invoke-LibraryDiscardTool (Args-Of @{ name = 'A' })).refused | Should Match 'know-how'
        (Invoke-LibraryDiscardTool (Args-Of @{ name = 'A'; knowhow = $true })).ok | Should Be $true
    }
    It 'says the type is gone when it was its only version' {
        Set-Fake
        $r = Invoke-LibraryDiscardTool (Args-Of @{ name = 'A' })
        $r.ok | Should Be $true
        $r.typeRemoved | Should Be $true
        $r.discarded | Should Be '0.0.2'
        $r.next | Should Match 'plc scope'
        @($script:state.pending.Values) | Should Be 'plc@Plc1:discarded:A'
    }
    It 'takes the write of the type back when the type is gone, and a compile by its name clears nothing more' {
        Set-Fake
        Register-Write $script:state -Scope 'plc' -Device 'Plc1' -Items @(@{ name = 'type:A'; ok = $true })
        $null = Invoke-LibraryDiscardTool (Args-Of @{ name = 'A' })
        @(@(Get-SaveStanding $script:state)[0].notCompiled) | Should Be 'discarded:A'
        Register-Compile $script:state 'plc' 'Plc1' @('A') 0
        @(@(Get-SaveStanding $script:state)[0].notCompiled) | Should Be 'discarded:A'
        Register-Compile $script:state 'plc' 'Plc1' @() 0
        @(Get-SaveStanding $script:state).Count | Should Be 0
    }
    It 'says the released version stays, and sends the compile to its name' {
        Set-Fake $true
        $r = Invoke-LibraryDiscardTool (Args-Of @{ name = 'A' })
        $r.typeRemoved | Should Be $false
        @($r.versions).Count | Should Be 1
        $r.next | Should Match "names \['A'\]"
    }
    It 'remembers a failed discard and quotes TIA by throwing' {
        Set-Fake $true
        $script:discardFails = $true
        { Invoke-LibraryDiscardTool (Args-Of @{ name = 'A' }) } | Should Throw 'TIA said no.'
        @($script:state.failed.Values) | Should Be 'plc@Plc1:type:A'
    }
    It 'takes a type that joined an open change out of its record' {
        Set-Fake $true
        $script:change = @{ types = [ordered]@{ A = @{ inWork = '0.0.2'; inWorkBy = 'bridge' } } }
        $null = Invoke-LibraryDiscardTool (Args-Of @{ name = 'A' })
        $script:change.types.A.inWork | Should Be ''
        $script:change.types.A.inWorkBy | Should Be ''
        $script:changeSaved | Should Be $true
    }
}

Describe 'Format-LibrarySummary of a type never released' {
    It 'names no empty version and does not say nothing depends on it' {
        $s = Format-LibrarySummary -Action 'released' -Type 'A' -From '' -To '0.0.1' -Dependents @() -Next 'compile.'
        $s | Should Match '^A 0\.0\.1 released, no released version before it\.'
        $s | Should Match 'types in work are not counted'
        $s | Should Not Match 'No dependent library types'
    }
    It 'stays as it was for a type with a released version' {
        Format-LibrarySummary -Action 'released' -Type 'A' -From '0.0.1' -To '0.0.2' -Dependents @() -Next 'compile.' | Should Match '^A 0\.0\.1 -> 0\.0\.2 released\. No dependent library types\.'
    }
}
