$here = Split-Path -Parent $MyInvocation.MyCommand.Path
foreach ($f in 'Mcp.ps1', 'Tia.ps1', 'Repo.ps1', 'Tools\Objects.ps1', 'Tools\Library.ps1') { . (Join-Path $here "..\$f") }

function V([string]$Number, [string]$State = 'Committed', [bool]$IsDefault = $false) {
    [pscustomobject]@{ VersionNumber = [version]$Number; State = $State; IsDefault = $IsDefault }
}

Describe 'Get-ReleaseVersion' {
    It 'proposes the number TIA gave the version in work' {
        Get-ReleaseVersion -Versions @((V '0.0.1'), (V '0.0.3'), (V '0.0.4' 'InWork')) | Should Be '0.0.4'
        Get-ReleaseVersion -Versions @((V '1.2'), (V '1.10' 'InWork')) | Should Be '1.10'
    }

    It 'takes a requested version above every released one' {
        Get-ReleaseVersion -Versions @((V '0.0.3'), (V '0.0.4' 'InWork')) -Requested '0.1.0' | Should Be '0.1.0'
    }

    It 'refuses a requested version that is not above the released ones' {
        { Get-ReleaseVersion -Versions @((V '0.0.3'), (V '0.0.4' 'InWork')) -Requested '0.0.3' } | Should Throw '0.0.3'
    }
}

Describe 'Select-TypeVersion' {
    It 'finds the version in work' {
        (Select-TypeVersion -Versions @((V '0.0.3' 'Committed' $true), (V '0.0.4' 'InWork')) -InWork).VersionNumber | Should Be '0.0.4'
    }

    It 'takes the default version as the one to edit, else the highest released one' {
        (Select-TypeVersion -Versions @((V '0.0.2' 'Committed' $true), (V '0.0.3'))).VersionNumber | Should Be '0.0.2'
        (Select-TypeVersion -Versions @((V '0.0.2'), (V '0.0.3'))).VersionNumber | Should Be '0.0.3'
    }

    It 'returns nothing when no version is in work' {
        Select-TypeVersion -Versions @((V '0.0.3')) -InWork | Should BeNullOrEmpty
    }
}

Describe 'Select-LibraryExportFormat' {
    It 'prefers SIMATIC SD, then SimaticML with defaults' {
        Select-LibraryExportFormat @('SimaticMLWithExportOptionsNone', 'SimaticMLWithExportOptionsWithDefaults', 'UDT', 'SimaticSD') | Should Be 'SimaticSD'
        Select-LibraryExportFormat @('SimaticMLWithExportOptionsNone', 'SimaticMLWithExportOptionsWithDefaults', 'SCL') | Should Be 'SimaticMLWithExportOptionsWithDefaults'
    }

    It 'gives nothing when the type offers no format (faceplate types)' {
        Select-LibraryExportFormat @() | Should BeNullOrEmpty
    }
}

# typePosition is contained in typeUnitId and typeDepotArray; typeUnitId in typePalletData; typePalletData in typeDBPalletData.
$script:graph = @{
    typePosition = @(); typeDepotArray = @('typePosition'); typeUnitId = @('typePosition')
    typePalletData = @('typeUnitId'); typeDBPalletData = @('typePalletData', 'typeDepotArray'); typeOther = @()
}

Describe 'Get-TypeDependents' {
    It 'finds every type that contains the type, directly or deeper, each once' {
        (@(Get-TypeDependents -DependsOn $script:graph -Name 'typePosition') | Sort-Object) -join ',' |
            Should Be 'typeDBPalletData,typeDepotArray,typePalletData,typeUnitId'
        @(Get-TypeDependents -DependsOn $script:graph -Name 'typeOther').Count | Should Be 0
    }
}

Describe 'Get-ReleaseOrder' {
    It 'releases contained types before the types that contain them' {
        $order = @(Get-ReleaseOrder -DependsOn $script:graph -Names @('typeDBPalletData', 'typeUnitId', 'typePosition', 'typePalletData', 'typeDepotArray'))
        $order.Count | Should Be 5
        foreach ($pair in @(@('typePosition', 'typeUnitId'), @('typeUnitId', 'typePalletData'), @('typePalletData', 'typeDBPalletData'), @('typeDepotArray', 'typeDBPalletData'))) {
            [array]::IndexOf($order, $pair[0]) | Should BeLessThan ([array]::IndexOf($order, $pair[1]))
        }
    }

    It 'orders only the given types, ignoring dependencies outside them' {
        (Get-ReleaseOrder -DependsOn $script:graph -Names @('typePalletData', 'typeDBPalletData')) -join ',' | Should Be 'typePalletData,typeDBPalletData'
    }

    It 'refuses a cycle and names the types in it' {
        { Get-ReleaseOrder -DependsOn @{ a = @('b'); b = @('a') } -Names @('a', 'b') } | Should Throw 'a, b'
    }
}

Describe 'Format-LibrarySummary' {
    It 'says what changed, how many dependent types it affects (naming a few), and what comes next' {
        $s = Format-LibrarySummary -Action 'released' -Type 'typePosition' -From '0.0.1' -To '0.0.2' -Dependents @('typeUnitId', 'typePalletData', 'typeDepotArray', 'typeDBPalletData') -Next 'library_update_usages'
        $s | Should Match '^typePosition 0\.0\.1 -> 0\.0\.2 released\.'
        $s | Should Match 'Affects 4 dependent library types \(typeDBPalletData, typeDepotArray, typePalletData, \.\.\.\)'
        $s | Should Match 'Next: library_update_usages$'
    }

    It 'says the dependents are not counted when the library walk stopped at its time limit' {
        $s = Format-LibrarySummary -Action 'released' -Type 'T' -From '0.0.1' -To '0.0.2' -Dependents @('A') -Next 'x' -IncompleteAfter 120
        $s | Should Match 'Dependents not counted: the library walk stopped after 120 types \(time limit\)\.'
        $s | Should Not Match 'Affects'
    }

    It 'says so when nothing depends on the type' {
        Format-LibrarySummary -Action 'put in work' -Type 'typeOther' -From '0.0.1' -To '0.0.2' -Dependents @() -Next 'edit' | Should Match 'No dependent library types\.'
    }
}

# The shape of TIA's compile tree after the gate run (2026-10-05), shortened.
function New-CompileTree {
    $leaf = { param($d) [ordered]@{ path = 'Interface'; state = 'Error'; description = $d; errors = 1; warnings = 0; messages = @() } }
    [ordered]@{ state = 'Error'; errors = 3; messages = @(
        [ordered]@{ path = 'MCCXX'; state = 'Error'; messages = @(
            [ordered]@{ path = 'PLC data types'; state = 'Error'; messages = @(
                [ordered]@{ path = 'typeUnitId (UDT)'; state = 'Error'; messages = @(& $leaf 'The interface of the block or data type contains incompatible changes.') }
                [ordered]@{ path = 'typePosition (UDT)'; state = 'Success'; description = 'The data type was successfully updated.'; messages = @() }) }
            [ordered]@{ path = 'Program blocks'; state = 'Error'; messages = @(
                [ordered]@{ path = 'Lib_SendTelegram (FC422)'; state = 'Error'; messages = @(& $leaf 'The interface of the block or data type contains incompatible changes.') }
                [ordered]@{ path = 'Main (OB1)'; state = 'Error'; messages = @([ordered]@{ path = 'Network 3'; state = 'Error'; description = 'Tag "station" not defined.'; messages = @() }) }) }) }
        [ordered]@{ path = ''; state = 'Error'; description = 'Compiling finished (errors: 3; warnings: 0)'; messages = @() }) }
}

Describe 'Get-CompileErrors' {
    It 'lists each error with the object it belongs to, without the summary line' {
        $e = @(Get-CompileErrors (New-CompileTree))
        $e.Count | Should Be 3
        ($e | ForEach-Object { $_.object }) -join ',' | Should Be 'typeUnitId,Lib_SendTelegram,Main'
        $e[2].description | Should Be 'Tag "station" not defined.'
        $e[2].path | Should Be 'MCCXX/Program blocks/Main (OB1)/Network 3'
    }
}

Describe 'Get-ReleaseChainPlan' {
    $libTypes = @('typePosition', 'typeUnitId', 'typePalletData', 'Lib_SendTelegram')

    It 'refuses when nothing is in work' {
        (Get-ReleaseChainPlan -InWork @() -DependsOn $script:graph -CompileErrors @() -LibraryTypes $libTypes).refused | Should Match 'No library type is in work'
    }

    It 'gives the release order when the compile is clean' {
        $p = Get-ReleaseChainPlan -InWork @('typePalletData', 'typeUnitId') -DependsOn $script:graph -CompileErrors @() -LibraryTypes $libTypes
        $p.ok | Should Be $true
        $p.order -join ',' | Should Be 'typeUnitId,typePalletData'
    }

    It 'refuses while a library block reports incompatible changes and names it for library_edit_type' {
        $p = Get-ReleaseChainPlan -InWork @('typeUnitId') -DependsOn $script:graph -CompileErrors @(Get-CompileErrors (New-CompileTree)) -LibraryTypes $libTypes
        $p.ok | Should Be $false
        $p.toEdit -join ',' | Should Be 'Lib_SendTelegram'
        $p.refused | Should Match 'library_edit_type'
    }

    It 'refuses on any other compile error and lists it' {
        $errors = @(Get-CompileErrors (New-CompileTree) | Where-Object { $_.object -eq 'Main' })
        $p = Get-ReleaseChainPlan -InWork @('typeUnitId') -DependsOn $script:graph -CompileErrors $errors -LibraryTypes $libTypes
        $p.ok | Should Be $false
        $p.refused | Should Match 'Main: Tag "station" not defined\.'
    }
}

# A library of N types whose Versions getter takes DelayMs, as TIA did after a release (2026-10-05: tia_status ran 20+ min).
function New-SlowLibrary([int]$Count, [int]$DelayMs, [string]$InWorkName = '') {
    $types = @(foreach ($i in 1..$Count) {
        $t = [pscustomobject]@{ Name = "type$i"; delay = $DelayMs; inWork = ("type$i" -eq $InWorkName) }
        $t | Add-Member ScriptProperty Versions {
            Start-Sleep -Milliseconds $this.delay
            $v = @([pscustomobject]@{ VersionNumber = [version]'0.0.1'; State = 'Committed'; IsDefault = $true; Dependencies = @() })
            if ($this.inWork) { $v += [pscustomobject]@{ VersionNumber = [version]'0.0.2'; State = 'InWork'; IsDefault = $false; Dependencies = @() } }
            $v
        }
        $t
    })
    [pscustomobject]@{ TypeFolder = [pscustomobject]@{ Types = $types; Folders = @() } }
}

Describe 'Test-ReleasedExportPath' {
    It 'recognises the comparison export of a released version, not the documents in work' {
        Test-ReleasedExportPath 'C:\R\library\types\UDT\typeUnitId.released\typeUnitId.s7dcl' | Should Be $true
        Test-ReleasedExportPath 'C:\R\library\types\UDT\typeUnitId\typeUnitId.s7dcl' | Should Be $false
    }
}

Describe 'Export-LibraryTypeDocuments for a type of a global library' {
    if (-not ('Siemens.Engineering.Library.LibraryExportOptions' -as [type])) {
        Add-Type -TypeDefinition 'namespace Siemens.Engineering.Library { public enum LibraryExportOptions { None, WithLibraryVersionInfoFile } }'
    }
    function ConvertTo-ResultTree($r) { $r }

    if (-not ('Siemens.Engineering.ExportOptions' -as [type])) {
        Add-Type -TypeDefinition 'namespace Siemens.Engineering { public enum ExportOptions { None, WithDefaults, WithReadOnly } }'
    }

    It 'exports the version metadata of a type whose documents Openness refuses to export (global library, 2026-10-06)' {
        $v = [pscustomobject]@{ VersionNumber = [version]'0.0.1'; State = 'Committed'; IsDefault = $true }
        $v | Add-Member ScriptMethod Export { param($file, $opt) Set-Content $file.FullName 'meta' }
        $t = [pscustomobject]@{ Versions = @($v) }
        $t | Add-Member ScriptMethod GetSupportedExportFormats { throw 'Cannot get supported export formats for a type in the global library.' }
        $r = Export-LibraryTypeDocuments @{ name = 'typeX'; obj = $t } "$TestDrive\glob"
        $r.note | Should Match 'Openness cannot export the documents of a type in a global library'
        Test-Path "$TestDrive\glob\typeX_V0.0.1.xml" | Should Be $true
    }

    It 'keeps the previous export folder and leaves no .partial when a file in it stays locked' {
        $dir = "$TestDrive\lock"
        New-Item -ItemType Directory -Force -Path "$dir\typeL" | Out-Null
        [System.IO.File]::WriteAllText("$dir\typeL\typeL.s7dcl", 'old')
        $v = [pscustomobject]@{ VersionNumber = [version]'0.0.1'; State = 'Committed'; IsDefault = $true }
        $v | Add-Member ScriptMethod ExportAsDocuments { param($d, $n, $f, $o) [System.IO.File]::WriteAllText((Join-Path $d.FullName "$n.s7dcl"), 'new') }
        $t = [pscustomobject]@{ Versions = @($v) }
        $t | Add-Member ScriptMethod GetSupportedExportFormats { @('SimaticSD') }
        $lock = [System.IO.File]::Open("$dir\typeL\typeL.s7dcl", 'Open', 'Read', 'None')
        try { { Export-LibraryTypeDocuments @{ name = 'typeL'; obj = $t } $dir } | Should Throw 'typeL' }
        finally { $lock.Dispose() }
        [System.IO.File]::ReadAllText("$dir\typeL\typeL.s7dcl") | Should Be 'old'
        Test-Path "$dir\typeL.partial" | Should Be $false
        Test-Path "$dir\typeL.old" | Should Be $false

        $r = Export-LibraryTypeDocuments @{ name = 'typeL'; obj = $t } $dir
        $r.ok | Should Be $true
        [System.IO.File]::ReadAllText("$dir\typeL\typeL.s7dcl") | Should Be 'new'
    }

    It 'refuses to replace the export folder of a type when it holds a git repo, and keeps it as it was' {
        $dir = "$TestDrive\typerepo"
        New-Item -ItemType Directory -Force -Path "$dir\typeR" | Out-Null
        [System.IO.File]::WriteAllText("$dir\typeR\.git", 'gitdir: C:\elsewhere')
        [System.IO.File]::WriteAllText("$dir\typeR\typeR.s7dcl", 'old')
        $v = [pscustomobject]@{ VersionNumber = [version]'0.0.1'; State = 'Committed'; IsDefault = $true }
        $v | Add-Member ScriptMethod ExportAsDocuments { param($d, $n, $f, $o) [System.IO.File]::WriteAllText((Join-Path $d.FullName "$n.s7dcl"), 'new') }
        $t = [pscustomobject]@{ Versions = @($v) }
        $t | Add-Member ScriptMethod GetSupportedExportFormats { @('SimaticSD') }
        { Export-LibraryTypeDocuments @{ name = 'typeR'; obj = $t } $dir } | Should Throw 'git repo'
        [System.IO.File]::ReadAllText("$dir\typeR\typeR.s7dcl") | Should Be 'old'
        Test-Path -LiteralPath "$dir\typeR\.git" | Should Be $true
        @(Get-ChildItem -LiteralPath $dir -Force | ForEach-Object { $_.Name }) -join ',' | Should Be 'typeR'
    }

    It 'passes the whole format name when the type supports one format or the caller names one (2026-10-08)' {
        $script:passedFormats = @()
        $v = [pscustomobject]@{ VersionNumber = [version]'0.0.1'; State = 'Committed'; IsDefault = $true }
        $v | Add-Member ScriptMethod ExportAsDocuments { param($d, $n, $f, $o) $script:passedFormats += $f; [System.IO.File]::WriteAllText((Join-Path $d.FullName "$n.s7dcl"), 'x') }
        $t = [pscustomobject]@{ Versions = @($v) }
        $t | Add-Member ScriptMethod GetSupportedExportFormats { @('SimaticSD') }
        (Export-LibraryTypeDocuments @{ name = 'typeF'; obj = $t } "$TestDrive\fmt").format | Should Be 'SimaticSD'
        (Export-LibraryTypeDocuments @{ name = 'typeF'; obj = $t } "$TestDrive\fmt2" -Format 'SimaticSD').format | Should Be 'SimaticSD'
        $script:passedFormats | Should Be @('SimaticSD', 'SimaticSD')
    }

    It 'keeps a version metadata file when its export fails' {
        $dir = "$TestDrive\meta"
        New-Item -ItemType Directory -Force -Path $dir | Out-Null
        [System.IO.File]::WriteAllText("$dir\fpX_V0.0.1.xml", 'old')
        $v = [pscustomobject]@{ VersionNumber = [version]'0.0.1'; State = 'Committed'; IsDefault = $true }
        $v | Add-Member ScriptMethod Export { param($file, $opt) throw 'The type version could not be exported' }
        { Export-LibraryTypeVersions @{ name = 'fpX'; obj = [pscustomobject]@{ Versions = @($v) } } $dir } | Should Throw 'could not be exported'
        [System.IO.File]::ReadAllText("$dir\fpX_V0.0.1.xml") | Should Be 'old'
        Test-Path "$dir\fpX_V0.0.1.xml.partial" | Should Be $false
    }

    It 'still reports any other failure to name the formats' {
        $t = [pscustomobject]@{ Versions = @() }
        $t | Add-Member ScriptMethod GetSupportedExportFormats { throw 'Something else.' }
        { Export-LibraryTypeDocuments @{ name = 'typeY'; obj = $t } "$TestDrive\glob" } | Should Throw 'Something else'
    }
}

Describe 'Resolve-LibraryExportFormat' {
    $all = @('SimaticMLWithExportOptionsNone', 'SimaticMLWithExportOptionsWithDefaults', 'SimaticSD')

    It 'maps options.format to the TIA format name' {
        Resolve-LibraryExportFormat $all 'xml' '' | Should Be 'SimaticMLWithExportOptionsWithDefaults'
        Resolve-LibraryExportFormat @('SimaticMLWithExportOptionsNone', 'SimaticSD') 'xml' '' | Should Be 'SimaticMLWithExportOptionsNone'
        Resolve-LibraryExportFormat $all 's7dcl' 'xml' | Should Be 'SimaticSD'
    }

    It 'keeps the format the type has in the repo when none is asked for, else takes SD' {
        Resolve-LibraryExportFormat $all '' 'xml' | Should Be 'SimaticMLWithExportOptionsWithDefaults'
        Resolve-LibraryExportFormat $all '' 's7dcl' | Should Be 'SimaticSD'
        Resolve-LibraryExportFormat $all '' '' | Should Be 'SimaticSD'
    }

    It 'refuses a format the type does not offer' {
        { Resolve-LibraryExportFormat @('SimaticMLWithExportOptionsWithDefaults', 'SCL') 's7dcl' '' } | Should Throw 'no s7dcl export'
    }
}

Describe 'Get-MultiIndexLadNetworks' {
    $text = @'
{
    S7_PreferredLanguage := "LAD"
}
FUNCTION_BLOCK "Trolley"
    VAR_IN_OUT
        ioTrolleyData : Array[*, *, *] of _.TrolleyData_UDT;
    END_VAR
    {
        S7_Language := "SCL"
    }
    NETWORK
        IF #ioTrolleyData[#iLevel, #iColumn, #iLine].Config.Type = #LT THEN
        END_IF;
    END_NETWORK
    {
        S7_Language := "LAD";
        S7_NetworkTitle := "MLC_YU"
    }
    NETWORK
        RUNG wire#powerrail
            EQ_Contact(
                in1 := #ioTrolleyData[#iLevel, #iColumn, #iLine].Status.Mode,
                in2 := #AUTO
            )
            Coil( #a[#i, 1] )
        END_RUNG
    END_NETWORK
    NETWORK
        RUNG wire#powerrail
            Contact( #b[#i, #j] )
        END_RUNG
    END_NETWORK
    NETWORK
        RUNG wire#powerrail
            Contact( #c[#i].d )
        END_RUNG
    END_NETWORK
END_FUNCTION_BLOCK
'@

    It 'counts LAD networks with operands indexed in several dimensions, not SCL networks or declarations (17a)' {
        # the third network has no S7_Language: the block's preferred language (LAD)
        Get-MultiIndexLadNetworks $text | Should Be 2
    }

    It 'finds none in a block without them' {
        Get-MultiIndexLadNetworks ($text -replace '\[#iLevel, #iColumn, #iLine\]', '[#iLine]' -replace '\[#i, 1\]', '[1]' -replace '\[#i, #j\]', '[#j]') | Should Be 0
    }
}

Describe 'Library type documents as SimaticSD or SimaticML' {
    if (-not ('Siemens.Engineering.Library.LibraryExportOptions' -as [type])) {
        Add-Type -TypeDefinition 'namespace Siemens.Engineering.Library { public enum LibraryExportOptions { None, WithLibraryVersionInfoFile } }'
    }
    function ConvertTo-ResultTree($r) { $r }

    # a type in work whose ExportAsDocuments writes what TIA writes for each format
    function New-DocType([string]$Lad = 'Contact( #a[#i] )') {
        $script:passedFormats = @()
        $script:lad = $Lad
        $v = [pscustomobject]@{ VersionNumber = [version]'3.0.6'; State = 'InWork'; IsDefault = $false }
        $v | Add-Member ScriptMethod ExportAsDocuments {
            param($d, $n, $f, $o)
            $script:passedFormats += $f
            $p = Join-Path $d.FullName $n
            [System.IO.File]::WriteAllText("$p.libinfo", 'LibraryVersion:')
            [System.IO.File]::WriteAllText("$p.libint", 'LibraryVersion:')
            if ($f -like 'SimaticML*') { [System.IO.File]::WriteAllText("$p.xml", '<Document />') }
            else {
                [System.IO.File]::WriteAllText("$p.s7dcl", "{ S7_Language := `"LAD`" }`r`nNETWORK`r`n$script:lad`r`nEND_NETWORK")
                [System.IO.File]::WriteAllText("$p.s7res", 'MLC: {}')
            }
        }
        $released = [pscustomobject]@{ VersionNumber = [version]'3.0.5'; State = 'Committed'; IsDefault = $true }
        $released | Add-Member ScriptMethod ExportAsDocuments $v.PSObject.Methods['ExportAsDocuments'].Script
        $t = [pscustomobject]@{ Versions = @($released, $v) }
        $t | Add-Member ScriptMethod GetSupportedExportFormats { @('SimaticMLWithExportOptionsNone', 'SimaticMLWithExportOptionsWithDefaults', 'SimaticSD') }
        @{ name = 'Trolley'; obj = $t }
    }

    It 'exports SimaticML on options.format xml and lists the SD files it replaced as removed' {
        $dir = "$TestDrive\x1"
        $e = New-DocType
        $sd = Export-LibraryTypeDocuments $e $dir
        $sd.format | Should Be 'SimaticSD'
        $sd.removed | Should BeNullOrEmpty

        $r = Export-LibraryTypeDocuments $e $dir -As 'xml'
        $r.format | Should Be 'SimaticMLWithExportOptionsWithDefaults'
        @($r.files | ForEach-Object { Split-Path -Leaf $_ } | Sort-Object) | Should Be @('Trolley.libinfo', 'Trolley.libint', 'Trolley.xml')
        @($r.removed | ForEach-Object { Split-Path -Leaf $_ } | Sort-Object) | Should Be @('Trolley.s7dcl', 'Trolley.s7res')
        Test-Path "$dir\Trolley\Trolley.s7dcl" | Should Be $false
    }

    It 'keeps SimaticML on a later export without format, and goes back to SD on options.format s7dcl' {
        $dir = "$TestDrive\x2"
        $e = New-DocType
        $null = Export-LibraryTypeDocuments $e $dir -As 'xml'
        (Export-LibraryTypeDocuments $e $dir).format | Should Be 'SimaticMLWithExportOptionsWithDefaults'
        (Export-LibraryTypeDocuments $e $dir -Released).format | Should Be 'SimaticMLWithExportOptionsWithDefaults'
        $r = Export-LibraryTypeDocuments $e $dir -As 's7dcl'
        $r.format | Should Be 'SimaticSD'
        @($r.removed | ForEach-Object { Split-Path -Leaf $_ }) | Should Be @('Trolley.xml')
        Test-Path "$dir\Trolley\Trolley.xml" | Should Be $false
    }

    It 'notes an SD export whose LAD has operands indexed in several dimensions' {
        $r = Export-LibraryTypeDocuments (New-DocType 'Contact( #d[#i, #j, #k].x )') "$TestDrive\x3"
        $r.note | Should Match '1 LAD/FBD networks .* options.format xml'
        (Export-LibraryTypeDocuments (New-DocType) "$TestDrive\x4").note | Should Not Match 'several dimensions'
    }

    It 'passes the format through the export kind' {
        $dir = "$TestDrive\x5"
        $k = Get-ObjectKind 'library_type'
        $r = & $k.export (New-DocType) $dir ([pscustomobject]@{ format = 'xml' })
        $r.format | Should Be 'SimaticMLWithExportOptionsWithDefaults'
    }

    It 'imports the format the folder holds and refuses a folder with both, before TIA is touched' {
        $dir = "$TestDrive\i1\Trolley"
        New-Item -ItemType Directory -Force -Path $dir | Out-Null
        [System.IO.File]::WriteAllText("$dir\Trolley.xml", '<Document />')
        $file = @{ file = "$dir\Trolley.xml"; name = 'Trolley' }
        Get-LibraryTypeImportFormat $file | Should Be 'xml'
        $k = Get-ObjectKind 'library_type'
        & $k.precheck $file @{} | Should BeNullOrEmpty

        [System.IO.File]::WriteAllText("$dir\Trolley.s7dcl", 'x')
        (& $k.precheck $file @{}).refused | Should Match 'both Trolley.xml and Trolley.s7dcl'
        $r = Import-LibraryTypeDocuments $null $file
        $r.ok | Should Be $false
        $r.refused | Should Match 'Keep one format'

        Remove-Item "$dir\Trolley.xml"
        Get-LibraryTypeImportFormat @{ file = "$dir\Trolley.s7dcl"; name = 'Trolley' } | Should Be 's7dcl'
    }
}

Describe 'Format-ReleaseChainNext' {
    It 'does not ask to release types that were in work before and left out of the chain' {
        $s = Format-ReleaseChainNext -After @('ComputeOffset', 'Lib:SetupIoDevice') -Outside @('ComputeOffset', 'Lib:SetupIoDevice') -CompileErrors 0
        $s | Should Match '^save, then commit the project repo\.'
        $s | Should Match 'Still in work from before, not part of this chain: ComputeOffset, Lib:SetupIoDevice\.'
    }

    It 'asks for the next round when the update put new types in work' {
        $s = Format-ReleaseChainNext -After @('typePalletData', 'ComputeOffset') -Outside @('ComputeOffset') -CompileErrors 0
        $s | Should Match '^1 types are in work after the update \(typePalletData\)'
    }

    It 'names compile errors when nothing new is in work' {
        Format-ReleaseChainNext -After @() -Outside @() -CompileErrors 3 | Should Match '^the PLC has 3 compile errors'
    }
}

Describe 'Get-LibraryDependsOn' {
    . (Join-Path $here '..\Tools\Plc.ps1')   # Get-GroupTree

    It 'keeps the contained types of a type in work, whose version in work reports none (2026-10-06)' {
        $pos = [pscustomobject]@{ Name = 'typePosition' }
        $flags = [pscustomobject]@{ Name = 'typeUnitFlags' }
        $unit = [pscustomobject]@{ Name = 'typeUnitId'; Versions = @(
            [pscustomobject]@{ VersionNumber = [version]'4.4.0'; State = 'Committed'; IsDefault = $true
                               Dependencies = @([pscustomobject]@{ TypeObject = $pos }, [pscustomobject]@{ TypeObject = $flags }) },
            [pscustomobject]@{ VersionNumber = [version]'4.4.1'; State = 'InWork'; IsDefault = $false; Dependencies = @() }) }
        $place = [pscustomobject]@{ Name = 'typePalletData'; Versions = @(
            [pscustomobject]@{ VersionNumber = [version]'1.0.0'; State = 'Committed'; IsDefault = $true; Dependencies = @([pscustomobject]@{ TypeObject = $unit }) }) }
        $lib = [pscustomobject]@{ TypeFolder = [pscustomobject]@{ Types = @($unit, $place); Folders = @() } }
        $g = Get-LibraryDependsOn -Library $lib -BudgetMs 10000
        ($g.graph['typeUnitId'] | Sort-Object) -join ',' | Should Be 'typePosition,typeUnitFlags'
        (@(Get-TypeDependents -DependsOn $g.graph -Name 'typePosition') | Sort-Object) -join ',' | Should Be 'typePalletData,typeUnitId'
    }
}

Describe 'library walks with a time limit' {
    . (Join-Path $here '..\Tools\Plc.ps1')   # Get-GroupTree

    It 'walks the whole library when there is time' {
        $w = Get-InWorkTypes -Library (New-SlowLibrary 5 0 'type3') -BudgetMs 10000
        $w.complete | Should Be $true
        @($w.types).Count | Should Be 1
        $w.types[0].type | Should Be 'type3'
        $g = Get-LibraryDependsOn -Library (New-SlowLibrary 5 0) -BudgetMs 10000
        $g.complete | Should Be $true
        $g.graph.Count | Should Be 5
    }

    It 'stops at the time limit and says the result is incomplete' {
        $sw = [Diagnostics.Stopwatch]::StartNew()
        $w = Get-InWorkTypes -Library (New-SlowLibrary 40 50) -BudgetMs 300
        $sw.ElapsedMilliseconds | Should BeLessThan 1500
        $w.complete | Should Be $false
        $g = Get-LibraryDependsOn -Library (New-SlowLibrary 40 50) -BudgetMs 300
        $g.complete | Should Be $false
        $g.walked | Should BeLessThan 40
    }
}

Describe 'Get-MasterCopyTarget' {
    It 'maps the content type of a master copy to the composition that creates it' {
        (Get-MasterCopyTarget 'FB').composition | Should Be 'Blocks'
        (Get-MasterCopyTarget 'GlobalDB').kind | Should Be 'db'
        (Get-MasterCopyTarget 'PlcType').composition | Should Be 'Types'
        (Get-MasterCopyTarget 'PlcTagTable').kind | Should Be 'plc_tag_table'
        (Get-MasterCopyTarget 'PlcBlockUserGroup').composition | Should Be 'Groups'
        (Get-MasterCopyTarget 'Screen').kind | Should Be 'hmi_screen'
        (Get-MasterCopyTarget 'TagTable').kind | Should Be 'hmi_tag_table'
    }

    It 'names the content types it cannot place' {
        { Get-MasterCopyTarget 'Device' } | Should Throw 'Device'
    }
}

# Export of faceplate types (kind faceplate_type): the version metadata files and the type index the HMI preview
# reads (library\faceplates\<folder>\<type>.type.json: name, folder, versions).
if (-not ('Siemens.Engineering.ExportOptions' -as [type])) {
    Add-Type -TypeDefinition 'namespace Siemens.Engineering { [System.Flags] public enum ExportOptions { None = 0, WithDefaults = 1, WithReadOnly = 2 } }'
}

Describe 'Export-LibraryTypeVersions' {
    function FV([string]$Number) {
        $v = [pscustomobject]@{ VersionNumber = [version]$Number }
        $v | Add-Member ScriptMethod Export { param($file, $opt) [System.IO.File]::WriteAllText($file.FullName, 'metadata') }
        $v
    }

    It 'writes one metadata file per version and the type index with the exact name, folder and versions' {
        $dir = Join-Path $TestDrive 'library\faceplates\Redesign\Faceplate'
        $entry = @{ name = 'faceplate:Drive'; folder = 'Redesign/Faceplate'; obj = [pscustomobject]@{ Versions = @((FV '0.0.2'), (FV '0.0.3')) } }
        $r = Export-LibraryTypeVersions $entry $dir
        $r.ok | Should Be $true
        Test-Path (Join-Path $dir 'faceplate_Drive_V0.0.3.xml') | Should Be $true
        $index = Join-Path $dir 'faceplate_Drive.type.json'
        @($r.files) -contains $index | Should Be $true
        $j = Get-Content -Raw $index | ConvertFrom-Json
        $j.name | Should Be 'faceplate:Drive'
        $j.folder | Should Be 'Redesign/Faceplate'
        (@($j.versions) -join ',') | Should Be '0.0.2,0.0.3'
    }
}

Describe 'Import-LibraryTypeDocuments, line ends of a .s7dcl' {
    if (-not ('Siemens.Engineering.Library.Types.CreateOptions' -as [type])) {
        Add-Type -TypeDefinition 'namespace Siemens.Engineering.Library.Types { public enum CreateOptions { Override } } namespace Siemens.Engineering.Library { public enum LibraryImportOptions { None } }'
    }
    function Select-TypeVersion { [pscustomobject]@{ VersionNumber = '1.0.1' } }
    function Add-LibraryLog { }
    function Get-LibraryTypeScope { 'plc' }
    function Find-LibraryType {
        $versions = [pscustomobject]@{ seen = $null }
        $versions | Add-Member ScriptMethod CreateFromDocuments { param($d, $n, $a, $b)
            $sd = Join-Path $d.FullName "$n.s7dcl"; if (Test-Path -LiteralPath $sd) { $script:seenByTia = [System.IO.File]::ReadAllText($sd) }
            [pscustomobject]@{ TransferResultState = 'Success' } }
        @{ name = 'T'; obj = [pscustomobject]@{ Versions = $versions } }
    }

    It 'gives TIA CRLF for a file written with LF, and says so' {
        $dir = Join-Path $TestDrive 'T'
        New-Item -ItemType Directory -Force -Path $dir | Out-Null
        $path = Join-Path $dir 'T.s7dcl'
        [System.IO.File]::WriteAllText($path, "FUNCTION `"T`" : Void`n        #r := 1;`n")
        $r = Import-LibraryTypeDocuments $null @{ file = $path; name = 'T'; objectName = 'T' }
        $script:seenByTia | Should Be "FUNCTION `"T`" : Void`r`n        #r := 1;`r`n"
        $r.ok | Should Be $true
        $r.note | Should Match 'CRLF'
    }

    It 'does not touch a SimaticML document' {
        $dir = Join-Path $TestDrive 'X'
        New-Item -ItemType Directory -Force -Path $dir | Out-Null
        $path = Join-Path $dir 'X.xml'
        [System.IO.File]::WriteAllText($path, "<Document />`n")
        Import-LibraryTypeDocuments $null @{ file = $path; name = 'X'; objectName = 'X' } | Out-Null
        [System.IO.File]::ReadAllText($path) | Should Be "<Document />`n"
    }

    Context 'objects the import brings into the PLC' {
        function New-Doc {
            $dir = Join-Path $TestDrive ([guid]::NewGuid().ToString('N'))
            New-Item -ItemType Directory -Force -Path $dir | Out-Null
            $path = Join-Path $dir 'T.xml'
            [System.IO.File]::WriteAllText($path, '<Document />')
            @{ file = $path; name = 'T'; objectName = 'T' }
        }
        function Find-LibraryType {
            $versions = [pscustomobject]@{}
            $versions | Add-Member ScriptMethod CreateFromDocuments { param($d, $n, $a, $b) $script:keys = @($script:keys) + @($script:comes); [pscustomobject]@{ TransferResultState = 'Success' } }
            @{ name = 'T'; obj = [pscustomobject]@{ Versions = $versions } }
        }
        function Get-PlcObjectKeys { $script:keys }
        function Get-PlcObjectRecords {
            @{ "P`tblock`tT" = @{ object = 'T'; device = 'P'; folder = 'f'; type = 'T'; version = '0.0.2' }
               "P`ttype`tS_1" = @{ object = 'S_1'; device = 'P'; folder = 'lib'; type = 'S'; version = '0.0.1' }
               "P`ttype`tR_1" = @{ object = 'R_1'; device = 'P'; folder = 'lib'; type = 'R'; version = '0.0.1' } }
        }

        It 'names what came, from any document, with what the update does about it' {
            $script:keys = @("P`tblock`tT"); $script:comes = @("P`ttype`tS_1", "P`ttype`tR_1")
            $r = Import-LibraryTypeDocuments $null (New-Doc)
            $r.ok | Should Be $true
            @($r.copiesBack | ForEach-Object { $_.object }) -join ',' | Should Be 'R_1,S_1'
            @($r.copiesBack)[1].type | Should Be 'S'
            @($r.copiesBack)[1].version | Should Be '0.0.1'
        }
        It 'says nothing when nothing came' {
            $script:keys = @("P`tblock`tT"); $script:comes = @()
            (Import-LibraryTypeDocuments $null (New-Doc)).Contains('copiesBack') | Should Be $false
        }
        It 'a compare that cannot be read does not fail the import' {
            $script:keys = @("P`tblock`tT"); $script:comes = @()
            function Get-PlcObjectKeys { throw 'no read' }
            (Import-LibraryTypeDocuments $null (New-Doc)).ok | Should Be $true
        }
        It 'names what came by its key when the fuller read fails after TIA took the import: not a failed import, and no false type' {
            $script:keys = @("P`tblock`tT"); $script:comes = @("P`ttype`tS_1")
            function Get-PlcObjectRecords { throw 'no record read' }
            $r = Import-LibraryTypeDocuments $null (New-Doc)
            $r.ok | Should Be $true
            @($r.copiesBack)[0].object | Should Be 'S_1'
            @($r.copiesBack)[0].device | Should Be 'P'
            @($r.copiesBack)[0].unread | Should Be $true
            Format-CopiesBack @($r.copiesBack) | Should Match 'brought these into the PLC: S_1\.'
            Format-CopiesBack @($r.copiesBack) | Should Not Match 'no library type'
        }
        It 'an HMI type is not compared' {
            function Get-LibraryTypeScope { 'hmi' }
            function Get-PlcObjectKeys { throw 'must not read' }
            function Write-BridgeLog { $script:loggedRead = $true }
            $script:loggedRead = $false
            $null = Import-LibraryTypeDocuments $null (New-Doc)
            $script:loggedRead | Should Be $false
        }
    }
}

Describe 'Format-CopiesBack' {
    It 'names them, the types for the update, and that the document is not at fault' {
        $t = Format-CopiesBack @(@{ object = 'S_1'; type = 'S'; version = '0.0.1'; folder = 'lib' }, @{ object = 'R_1'; type = 'R'; version = '0.0.1'; folder = '' })
        $t | Should Match 'S_1 \(type S 0\.0\.1, folder lib\)'
        $t | Should Match 'also from a document that is right'
        $t | Should Match "library_update_usages with types=\['R', 'S'\]"
        $t | Should Match 'next update removes them'
    }
    It 'caps the names' {
        $many = @(1..12 | ForEach-Object { @{ object = "C$($_)_1"; type = "C$_"; version = '0.0.1'; folder = '' } })
        $t = Format-CopiesBack $many
        $t | Should Match 'C10_1'
        $t | Should Not Match 'C11_1'
        $t | Should Match 'and 2 more \(copiesBack\)'
        $t | Should Match 'and 2 more \(the types in copiesBack\)'
        ([regex]::Matches($t, "'C\d+'")).Count | Should Be 10
    }
    It 'stays short at any length' {
        $many = @(1..300 | ForEach-Object { @{ object = "LongTypeNameOfTheLibrary_$($_)_1"; type = "LongTypeNameOfTheLibrary_$_"; version = '0.0.1'; folder = 'library/some/path/of/a/type' } })
        (Format-CopiesBack $many).Length | Should BeLessThan 5000
    }
}

Describe 'Add-CopiesBackFacts' {
    function Add-LibraryLog { $script:logged += @($args[0]) }
    $s1 = @{ object = 'S_1'; type = 'S'; version = '0.0.1'; folder = 'lib' }

    It 'takes them into the result and the log, with one full stop' {
        $script:logged = @()
        $r = @{ next = 'Then compile, then save.' }
        Add-CopiesBackFacts $r @(@{ name = 'T'; copiesBack = @($s1) })
        @($r.copiesBack)[0].object | Should Be 'S_1'
        $r.next | Should Match 'then save\. The import brought'
        $script:logged -join ' ' | Should Match 'S_1'
    }
    It 'a batch rolled back brought nothing: not in the items, the result or the log' {
        $script:logged = @()
        $r = @{ next = 'n' }
        $item = @{ name = 'T'; rolledBack = $true; copiesBack = @($s1) }
        Add-CopiesBackFacts $r @($item)
        $item.Contains('copiesBack') | Should Be $false
        $r.Contains('copiesBack') | Should Be $false
        $r.next | Should Be 'n'
        @($script:logged).Count | Should Be 0
    }
}

Describe 'library_open' {
    It 'refuses a path over 143 characters before TIA is asked' {
        $long = 'C:\' + ('x' * 136) + '.al20'
        $long.Length | Should Be 144
        (Invoke-LibraryOpenTool ([pscustomobject]@{ path = $long })).refused | Should Match 'at most 143'
    }
}
