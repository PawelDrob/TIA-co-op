$here = Split-Path -Parent $MyInvocation.MyCommand.Path
foreach ($f in 'Mcp.ps1', 'Tia.ps1', 'Repo.ps1', 'Rules.ps1', 'Guards.ps1', 'Bridge.ps1', 'Tools\Objects.ps1', 'Tools\Library.ps1', 'Tools\LibraryChange.ps1') {
    . (Join-Path $here "..\$f")
}

# The shape of a real project (2026-10-06): typePosition in typeUnitId in typePalletData in BaseStation, and an FC beside it.
$script:graph = @{
    typePosition = @(); typeUnitId = @('typePosition', 'typeUnitFlags'); typeUnitFlags = @()
    typePalletData = @('typeUnitId'); BaseStation = @('typePalletData', 'typePosition'); CommReceive = @('typeUnitId')
}

function New-TestRecord {
    $types = @(
        @{ name = 'typePosition'; class = 'PlcTypeLibraryType'; folder = 'UDT'; released = '4.4.0'; inWork = '4.4.1' }
        @{ name = 'typeUnitId'; class = 'PlcTypeLibraryType'; folder = 'UDT'; released = '4.4.0'; inWork = '' }
        @{ name = 'typePalletData'; class = 'PlcTypeLibraryType'; folder = 'UDT'; released = '4.4.0'; inWork = '' }
        @{ name = 'BaseStation'; class = 'CodeBlockLibraryType'; folder = '_Library'; released = '4.4.0'; inWork = '' }
        @{ name = 'CommReceive'; class = 'CodeBlockLibraryType'; folder = '_Library'; released = '4.4.0'; inWork = '' })
    $levels = Get-ImpactLevels -DependsOn $script:graph -Root 'typePosition' -Dependents @('typeUnitId', 'typePalletData', 'BaseStation', 'CommReceive')
    New-ChangeRecord -Root 'typePosition' -From '4.4.0' -To '4.4.1' -Types $types -Levels $levels -At ([datetime]'2026-10-06 11:53')
}

Describe 'Get-ImpactLevels' {
    It 'puts every type one level above the highest change type it contains' {
        $l = Get-ImpactLevels -DependsOn $script:graph -Root 'typePosition' -Dependents @('typeUnitId', 'typePalletData', 'BaseStation', 'CommReceive')
        $l['typePosition'] | Should Be 0
        $l['typeUnitId'] | Should Be 1
        $l['typePalletData'] | Should Be 2
        $l['CommReceive'] | Should Be 2
        $l['BaseStation'] | Should Be 3
    }
}

Describe 'Format-ChangeReport and Read-ReportApprovals' {
    It 'writes one checkbox per dependent type by level, none for the changed type, and reads the ticks back' {
        $r = New-TestRecord
        $r.types['typeUnitId'].inWork = '4.4.1'; $r.types['typeUnitId'].inWorkBy = 'tia'
        $r.types['typeUnitId'].review = @{ verdict = 'reference-only'; references = @('typePosition 4.4.0 -> 4.4.1'); unexpected = @(); content = @() }
        $r.types['typeUnitId'].approved = $true
        $md = Format-ChangeReport $r
        $md | Should Match '# Library change: typePosition 4\.4\.0 -> 4\.4\.1'
        $md | Should Match '4 dependent library types'
        $md | Should Match '- `typePosition` - data type - 4\.4\.0 -> 4\.4\.1 in work - .*\(the change\)|- `typePosition` - data type - 4\.4\.0 -> 4\.4\.1 in work \(the change\)'
        $md | Should Match '## Level 3'
        $md | Should Match '- \[x\] `typeUnitId` - data type - 4\.4\.0 -> 4\.4\.1 in work \(by TIA\) - reference only: typePosition 4\.4\.0 -> 4\.4\.1'
        $md | Should Match '- \[ \] `BaseStation` - code block - 4\.4\.0, not in work yet'
        $a = Read-ReportApprovals $md
        $a['typeUnitId'] | Should Be $true
        $a['BaseStation'] | Should Be $false
        $a.ContainsKey('typePosition') | Should Be $false
    }

    It 'shows a flagged review with its count, diff file and the references' {
        $r = New-TestRecord
        $r.types['typeUnitId'].inWork = '4.4.1'
        $r.types['typeUnitId'].review = @{ verdict = 'flagged'; references = @('typePosition 4.4.0 -> 4.4.1'); unexpected = @()
                                         content = @('a + x', 'a + y', 'a + z'); diff = 'library\changes\c\typeUnitId.diff'; format = 'xml' }
        Format-ChangeReport $r | Should Match '\*\*FLAGGED\*\*: 3 other lines differ \(library\\changes\\c\\typeUnitId\.diff\); references: typePosition 4\.4\.0 -> 4\.4\.1 - compared as SimaticML \(unverified\)'
    }
}

Describe 'Read-LibintDependsOn' {
    It 'reads the DependsOn list of an exported .libint' {
        $text = "$([char]0xFEFF)LibraryVersion:`r`n  DependsOn:`r`n    - TypeName: typeUnitFlags`r`n      VersionNumber: 4.4.0`r`n    - TypeName: typePosition`r`n      VersionNumber: 4.4.1`r`n"
        $d = Read-LibintDependsOn $text
        $d['typeUnitFlags'] | Should Be '4.4.0'
        $d['typePosition'] | Should Be '4.4.1'
    }
}

Describe 'Compare-TypeDocuments' {
    function Write-Export([string]$Dir, [string]$Plc, [string]$Body) {
        New-Item -ItemType Directory -Force -Path $Dir | Out-Null
        Set-Content (Join-Path $Dir 't.libint') "LibraryVersion:`r`n  DependsOn:`r`n    - TypeName: typePosition`r`n      VersionNumber: $Plc`r`n    - TypeName: typeUnitFlags`r`n      VersionNumber: 4.4.0" -Encoding UTF8
        Set-Content (Join-Path $Dir 't.libinfo') "VersionNumber: x$Plc" -Encoding UTF8
        Set-Content (Join-Path $Dir 't.s7dcl') $Body -Encoding UTF8
    }
    $change = @('typePosition', 'typeUnitId')

    It 'passes a type that differs only in the version of a change type (CommReceive)' {
        Write-Export "$TestDrive\a.released" '4.4.0' "TYPE`r`n  x : Int;`r`nEND_TYPE"
        Write-Export "$TestDrive\a" '4.4.1' "TYPE`r`n  x : Int;`r`nEND_TYPE"
        $c = Compare-TypeDocuments "$TestDrive\a.released" "$TestDrive\a" $change
        $c.verdict | Should Be 'reference-only'
        $c.references | Should Be 'typePosition 4.4.0 -> 4.4.1'
    }

    It 'flags any other difference in the documents (typeUnitId) and lists the lines' {
        Write-Export "$TestDrive\b.released" '4.4.0' "TYPE`r`n  target : _.typePosition;`r`nEND_TYPE"
        Write-Export "$TestDrive\b" '4.4.1' "TYPE`r`n  { S7_Setpoint := `"False`" }`r`n  target : _.typePosition;`r`nEND_TYPE"
        $c = Compare-TypeDocuments "$TestDrive\b.released" "$TestDrive\b" $change
        $c.verdict | Should Be 'flagged'
        @($c.content).Count | Should Be 1
        $c.content[0] | Should Be 't.s7dcl +   { S7_Setpoint := "False" }'
    }

    It 'flags a reference to a type outside the change' {
        Write-Export "$TestDrive\c.released" '4.4.0' 'same'
        Write-Export "$TestDrive\c" '4.4.0' 'same'
        Set-Content "$TestDrive\c\t.libint" "LibraryVersion:`r`n  DependsOn:`r`n    - TypeName: typePosition`r`n      VersionNumber: 4.4.0`r`n    - TypeName: typeUnitFlags`r`n      VersionNumber: 4.4.2" -Encoding UTF8
        $c = Compare-TypeDocuments "$TestDrive\c.released" "$TestDrive\c" $change
        $c.verdict | Should Be 'flagged'
        $c.unexpected | Should Be 'typeUnitFlags 4.4.0 -> 4.4.2'
    }

    It 'reads names YAML quotes because of a colon, so they count as change types (BaseStation)' {
        $d = Read-LibintDependsOn "LibraryVersion:`r`n  DependsOn:`r`n    - TypeName: 'Lib:ClearDb'`r`n      VersionNumber: 4.4.1"
        $d['Lib:ClearDb'] | Should Be '4.4.1'
    }

    It 'names a difference of S7_Setpoint attributes only, rewritten pragma blocks included (typeDepotInterlock)' {
        Write-Export "$TestDrive\e.released" '4.4.0' "TYPE`r`n  { S7_MLC := `"MLC_4ui`" }`r`n  x : Int;`r`nEND_TYPE"
        Write-Export "$TestDrive\e" '4.4.1' "TYPE`r`n  {`r`n    S7_MLC := `"MLC_4ui`";`r`n    S7_Setpoint := `"False`"`r`n  }`r`n  x : Int;`r`nEND_TYPE"
        $c = Compare-TypeDocuments "$TestDrive\e.released" "$TestDrive\e" $change
        $c.verdict | Should Be 'flagged'
        $c.kind | Should Be 'setpoint-only'
        Write-Export "$TestDrive\f.released" '4.4.0' "IF #i <= #MAX THEN"
        Write-Export "$TestDrive\f" '4.4.1' "IF #i <= #MAX AND #i > 0 THEN"
        (Compare-TypeDocuments "$TestDrive\f.released" "$TestDrive\f" $change).kind | Should Be ''
    }

    It 'leaves out the element numbers and export times of SimaticML, which change on every export (BaseDriveRead)' {
        foreach ($d in "$TestDrive\g.released", "$TestDrive\g") { New-Item -ItemType Directory -Force -Path $d | Out-Null }
        Set-Content "$TestDrive\g.released\t.xml" "<Document>`r`n  <Created>2026-10-06T17:49:35.2071028Z</Created>`r`n  <SW.Blocks.CompileUnit ID=`"4E`" CompositionName=`"CompileUnits`">`r`n</Document>" -Encoding UTF8
        Set-Content "$TestDrive\g\t.xml" "<Document>`r`n  <Created>2026-10-06T17:49:35.0792848Z</Created>`r`n  <SW.Blocks.CompileUnit ID=`"19`" CompositionName=`"CompileUnits`">`r`n</Document>" -Encoding UTF8
        (Compare-TypeDocuments "$TestDrive\g.released" "$TestDrive\g" $change).verdict | Should Be 'unchanged'
    }

    It 'says unchanged when nothing differs' {
        Write-Export "$TestDrive\d.released" '4.4.0' 'same'
        Write-Export "$TestDrive\d" '4.4.0' 'same'
        (Compare-TypeDocuments "$TestDrive\d.released" "$TestDrive\d" $change).verdict | Should Be 'unchanged'
    }
}

Describe 'Get-ApprovedReleaseSet' {
    It 'releases approved types contained-first and holds a type whose contained change type is not approved' {
        $r = New-TestRecord
        $r.types['typePosition'].releasedAs = '4.4.1'
        foreach ($n in 'typeUnitId', 'typePalletData', 'BaseStation', 'CommReceive') { $r.types[$n].inWork = '4.4.1' }
        foreach ($n in 'typeUnitId', 'BaseStation', 'CommReceive') { $r.types[$n].approved = $true }
        $s = Get-ApprovedReleaseSet $r $script:graph
        ($s.order -join ',') | Should Be 'typeUnitId,CommReceive'
        $s.waiting[0].type | Should Be 'BaseStation'
        ($s.waiting[0].for -join ',') | Should Be 'typePalletData'
        ($s.notApproved -join ',') | Should Be 'typePalletData'
    }

    It 'holds everything while the changed type itself is not released' {
        $r = New-TestRecord
        $r.types['typeUnitId'].inWork = '4.4.1'; $r.types['typeUnitId'].approved = $true
        $s = Get-ApprovedReleaseSet $r $script:graph
        @($s.order).Count | Should Be 0
        ($s.waiting[0].for -join ',') | Should Be 'typePosition'
    }
}

Describe 'Test-ChangeDone' {
    It 'is done once the changed type is released, the project updated, and nothing of the change is in work unreleased' {
        $r = New-TestRecord
        $r.types['typePosition'].releasedAs = '4.4.1'
        Test-ChangeDone $r | Should Be $false                       # released, not updated yet: nothing put in work so far
        $r.updated = $true
        $r.types['typeUnitId'].inWork = '4.4.1'
        Test-ChangeDone $r | Should Be $false                       # typeUnitId in work, not released
        $r.types['typeUnitId'].releasedAs = '4.4.1'
        Test-ChangeDone $r | Should Be $true                        # BaseStation etc. never in work: keep their versions
        Format-ChangeTypeLine 'BaseStation' $r.types['BaseStation'] $true | Should Match 'not put in work: keeps its version'
    }
}

Describe 'Find-StaleDependencies' {
    It 'names a type whose default version uses an old version of another type (faceplates, 2026-10-06)' {
        $versions = @(
            @{ name = 'faceplateDeskBOperate'; deps = @(@{ name = 'typeHmiDeskB'; version = '0.0.1' }) }
            @{ name = 'typeHmiControlFan'; deps = @(@{ name = 'typeHmiCycle'; version = '0.0.5' }) })
        $s = Find-StaleDependencies $versions @{ typeHmiDeskB = '0.0.2'; typeHmiCycle = '0.0.5' }
        @($s.Keys) -join ',' | Should Be 'faceplateDeskBOperate'
        $s['faceplateDeskBOperate'][0] | Should Be 'typeHmiDeskB (uses 0.0.1, default 0.0.2)'
    }

    It 'keeps a change open while a type of it uses an old version, and reopens a done one' {
        $r = New-TestRecord
        $r.types['typePosition'].releasedAs = '4.4.1'; $r.updated = $true
        Test-ChangeDone $r | Should Be $true
        $r.types['BaseStation'].stale = @('typePalletData (uses 4.4.0, default 4.4.1)')
        Test-ChangeDone $r | Should Be $false
        Format-ChangeTypeLine 'BaseStation' $r.types['BaseStation'] $true | Should Match 'NOT USING THE DEFAULT VERSION\*\* of typePalletData \(uses 4\.4\.0, default 4\.4\.1\)'
        $repo = Join-Path $TestDrive 'stale'
        $r.status = 'done'
        $null = Save-ChangeRecord $repo $r
        (Read-ChangeRecord $repo $r.id).status | Should Be 'open'
    }
}

Describe 'Update-ChangeReleasedOutside' {
    It 'records a type released in TIA, outside the bridge (the faceplates of 2026-10-06_1455)' {
        $r = New-TestRecord
        Update-ChangeReleasedOutside $r @(@{ name = 'BaseStation'; released = '4.4.1'; inWork = '' }, @{ name = 'typeUnitId'; released = '4.4.0'; inWork = '' },
                                          @{ name = 'typePosition'; released = '4.4.9'; inWork = '' })
        $r.types['BaseStation'].releasedAs | Should Be '4.4.1'
        $r.types['typeUnitId'].releasedAs | Should BeNullOrEmpty
        $r.types['typePosition'].releasedAs | Should BeNullOrEmpty
        Format-ChangeTypeLine 'BaseStation' $r.types['BaseStation'] | Should Match '- \[x\] `BaseStation` - code block - released 4\.4\.1 in TIA'
    }
}

Describe 'Test-ChangeDone with an update outstanding' {
    It 'is not done while the update has not reached the project' {
        $r = New-TestRecord
        foreach ($n in @($r.types.Keys)) { $r.types[$n].releasedAs = '4.4.1'; $r.types[$n].inWork = '' }
        $r.updated = $true
        Test-ChangeDone $r | Should Be $true
        $r.updateOutstanding = $true
        Test-ChangeDone $r | Should Be $false
    }
}

Describe 'Update-ChangeInWork' {
    It 'records who put a type in work, once, and ignores types outside the change' {
        $r = New-TestRecord
        Update-ChangeInWork $r @(@{ type = 'typeUnitId'; inWork = '4.4.1' }, @{ type = 'Other'; inWork = '1.0.1' }) 'tia'
        Update-ChangeInWork $r @(@{ type = 'typeUnitId'; inWork = '4.4.1' }, @{ type = 'CommReceive'; inWork = '4.4.1' }) 'bridge'
        $r.types['typeUnitId'].inWorkBy | Should Be 'tia'
        $r.types['CommReceive'].inWorkBy | Should Be 'bridge'
        $r.types.Contains('Other') | Should Be $false
    }
}

Describe 'Get-LiveChange' {
    . (Join-Path $here '..\Tools\Plc.ps1')   # Get-GroupTree
    function Add-LibraryLog([string]$Line) { }

    It 'marks a change abandoned when its new version is gone from the library (closed without saving)' {
        $repo = Join-Path $TestDrive 'live'
        Initialize-BridgeContext @{ maxResponseChars = 20000 }
        Set-BridgeProject -Name 'P' -Path 'C:\P.ap20' -Repo $repo
        $r = New-TestRecord
        $null = Save-ChangeRecord $repo $r
        $plc = [pscustomobject]@{ Name = 'typePosition'; Versions = @([pscustomobject]@{ VersionNumber = [version]'4.4.0'; State = 'Committed'; IsDefault = $true }) }
        $lib = [pscustomobject]@{ TypeFolder = [pscustomobject]@{ Types = @($plc); Folders = @() } }
        Get-LiveChange $lib 'typeUnitId' | Should BeNullOrEmpty
        (Read-ChangeRecord $repo $r.id).status | Should Be 'abandoned'

        $r2 = New-TestRecord; $r2.id = 'second'
        $null = Save-ChangeRecord $repo $r2
        $plc.Versions = @($plc.Versions) + [pscustomobject]@{ VersionNumber = [version]'4.4.1'; State = 'InWork'; IsDefault = $false }
        (Get-LiveChange $lib 'typeUnitId').id | Should Be 'second'
    }
}

Describe 'change record files' {
    It 'saves the record and the report, and takes the ticks of the report as approvals' {
        $repo = Join-Path $TestDrive 'repo'
        $r = New-TestRecord
        $r.types['typeUnitId'].inWork = '4.4.1'
        $md = Save-ChangeRecord $repo $r
        $md | Should Be 'library\changes\2026-10-06_1153-typePosition.md'
        $path = Join-Path $repo $md
        (Get-Content $path -Raw) -replace '- \[ \] `typeUnitId`', '- [x] `typeUnitId`' | Set-Content $path -Encoding UTF8
        $back = Read-ChangeRecord $repo $r.id
        $back.types['typeUnitId'].approved | Should Be $true
        $back.types['typePalletData'].approved | Should Be $false
        (Find-OpenChange $repo 'typeUnitId').id | Should Be $r.id
        Find-OpenChange $repo 'Other' | Should BeNullOrEmpty
    }
}

Describe 'change ids are plain file names' {
    foreach ($bad in '..\..\secret', '../secret', 'C:\x', '..', '.', '', 'a\b', 'a/b') {
        It "refuses to read the change id '$bad'" {
            $repo = Join-Path $TestDrive 'ids'
            Write-TextFile (Join-Path $repo 'secret.json') '{ "id": "secret", "status": "open", "types": { } }'
            { Read-ChangeRecord $repo $bad } | Should Throw 'plain file name'
        }
    }

    It 'refuses to save a record whose id is not a plain file name, and writes nothing outside' {
        $repo = Join-Path $TestDrive 'ids2'
        $r = New-TestRecord
        $r.id = '..\..\evil'
        { Save-ChangeRecord $repo $r } | Should Throw 'plain file name'
        Test-Path (Join-Path $repo 'evil.json') | Should Be $false
        Test-Path (Join-Path $repo 'library\evil.json') | Should Be $false
    }

    It 'takes the id New-ChangeId makes of a type name with dots at its end' {
        $repo = Join-Path $TestDrive 'ids3'
        $r = New-TestRecord
        $r.id = New-ChangeId 'type.V2.' ([datetime]'2026-10-06 11:53')
        $null = Save-ChangeRecord $repo $r
        (Read-ChangeRecord $repo $r.id).id | Should Be $r.id
    }
}
