$here = Split-Path -Parent $MyInvocation.MyCommand.Path
. (Join-Path $here '..\Guards.ps1')
$fx = Join-Path $here 'Fixtures'

Describe 'Select-BlockExportFormat (OB refusal, 5.2 / 5.5)' {
    It 'exports FBs, FCs, UDTs and DBs as s7dcl by default' {
        Select-BlockExportFormat -IsOb $false -IsKnowHowProtected $false | Should Be 's7dcl'
    }

    It 'exports an OB or a know-how protected block as SimaticML' {
        Select-BlockExportFormat -IsOb $true -IsKnowHowProtected $false | Should Be 'xml'
        Select-BlockExportFormat -IsOb $false -IsKnowHowProtected $true | Should Be 'xml'
    }

    It 'refuses an explicit s7dcl export of an OB with the reason' {
        { Select-BlockExportFormat -IsOb $true -IsKnowHowProtected $false -Requested 's7dcl' } | Should Throw 'event class'
    }

    It 'honours an explicit xml request for any block' {
        Select-BlockExportFormat -IsOb $false -IsKnowHowProtected $false -Requested 'xml' | Should Be 'xml'
    }
}

Describe 'Test-S7dclImportAllowed' {
    It 'refuses the s7dcl of an OB with the reason' {
        Test-S7dclImportAllowed (Join-Path $fx 'CyclicInterrupt.s7dcl') | Should Match 'event class'
    }

    It 'allows any other block, even one mentioning the keyword in a comment' {
        Test-S7dclImportAllowed (Join-Path $fx 'ControlConveyorStart.s7dcl') | Should BeNullOrEmpty
    }
}

Describe 'Test-FBlockLanguage' {
    It 'takes every language of the F_ family as an F-block' {
        foreach ($l in 'F_LAD', 'F_FBD', 'F_STL', 'F_DB', 'F_CALL', 'F_LAD_LIB', 'F_FBD_LIB') { Test-FBlockLanguage $l | Should Be $true }
    }

    It 'leaves standard languages out, those starting with F too' {
        foreach ($l in 'LAD', 'FBD', 'FBD_IEC', 'FCP', 'FLD', 'SCL', 'DB', '') { Test-FBlockLanguage $l | Should Be $false }
    }
}

Describe 'Test-FBlockDocument' {
    function New-Doc([string]$Name, [string]$Text) {
        $p = Join-Path $TestDrive $Name
        Set-Content -LiteralPath $p -Value $Text -Encoding UTF8
        $p
    }

    It 'finds the S7_Safety attribute of an F-FB and an F-DB, in any case and among other attributes' {
        Test-FBlockDocument (New-Doc 'Ffb.s7dcl' "{ S7_Safety := `"True`" }`r`nFUNCTION_BLOCK `"Ffb`"`r`nEND_FUNCTION_BLOCK") | Should Be $true
        Test-FBlockDocument (New-Doc 'Fdb.s7dcl' "{ S7_Optimized := `"TRUE`";`r`n  S7_SAFETY:=`"true`" }`r`nDATA_BLOCK `"Fdb`"`r`nEND_DATA_BLOCK") | Should Be $true
    }

    It 'does not take a standard block, S7_Safety false, or the word below the block keyword' {
        Test-FBlockDocument (New-Doc 'Std.s7dcl' "{ S7_Optimized := `"TRUE`" }`r`nFUNCTION_BLOCK `"Std`"`r`nEND_FUNCTION_BLOCK") | Should Be $false
        Test-FBlockDocument (New-Doc 'Off.s7dcl' "{ S7_Safety := `"False`" }`r`nFUNCTION `"Off`" : Void`r`nEND_FUNCTION") | Should Be $false
        Test-FBlockDocument (New-Doc 'Word.s7dcl' "FUNCTION_BLOCK `"Word`"`r`n// { S7_Safety := `"True`" }`r`nEND_FUNCTION_BLOCK") | Should Be $false
    }

    It 'finds the F_ language of a SimaticML document and leaves a standard one out' {
        Test-FBlockDocument (New-Doc 'FXml.xml' '<Document><SW.Blocks.FB><ProgrammingLanguage>F_LAD</ProgrammingLanguage></SW.Blocks.FB></Document>') | Should Be $true
        Test-FBlockDocument (New-Doc 'SXml.xml' '<Document><SW.Blocks.FB><ProgrammingLanguage>LAD</ProgrammingLanguage></SW.Blocks.FB></Document>') | Should Be $false
    }

    It 'still finds S7_Safety behind a comment or a multi-line value with a line starting like a keyword' {
        Test-FBlockDocument (New-Doc 'Note1.s7dcl' "(*`r`nFunction of this block`r`n*)`r`n{ S7_Safety := `"True`" }`r`nFUNCTION_BLOCK `"Note1`"`r`nEND_FUNCTION_BLOCK") | Should Be $true
        Test-FBlockDocument (New-Doc 'Note2.s7dcl' "/*`r`nType of drive`r`n*/`r`n{ S7_Safety := `"True`" }`r`nDATA_BLOCK `"Note2`"`r`nEND_DATA_BLOCK") | Should Be $true
        Test-FBlockDocument (New-Doc 'Note3.s7dcl' "{ S7_BlockTitle := `"first`r`nFunction second`";`r`n  S7_Safety := `"True`" }`r`nFUNCTION `"Note3`" : Void`r`nEND_FUNCTION") | Should Be $true
    }

    It 'finds S7_Safety with the value in single quotes or without quotes' {
        Test-FBlockDocument (New-Doc 'Single.s7dcl' "{ S7_Safety := 'True' }`r`nFUNCTION_BLOCK `"Single`"`r`nEND_FUNCTION_BLOCK") | Should Be $true
        Test-FBlockDocument (New-Doc 'Bare.s7dcl' "{ S7_Safety := True }`r`nFUNCTION_BLOCK `"Bare`"`r`nEND_FUNCTION_BLOCK") | Should Be $true
    }

    # The file is the agent's next edit and the next export's target: import -> compile -> export again.
    It 'leaves the file free to overwrite after a block read to its keyword, an F-block and a SimaticML document' {
        foreach ($d in @(
                @('FreeStd.s7dcl', "{ S7_Optimized := `"TRUE`" }`r`nFUNCTION_BLOCK `"FreeStd`"`r`nEND_FUNCTION_BLOCK"),
                @('FreeF.s7dcl', "{ S7_Safety := `"True`" }`r`nFUNCTION_BLOCK `"FreeF`"`r`nEND_FUNCTION_BLOCK"),
                @('FreeF.xml', '<Document><ProgrammingLanguage>F_LAD</ProgrammingLanguage></Document>'),
                @('FreeStd.xml', '<Document><ProgrammingLanguage>LAD</ProgrammingLanguage></Document>'))) {
            $p = New-Doc $d[0] $d[1]
            $null = Test-FBlockDocument $p
            { [System.IO.File]::WriteAllText($p, 'edited') } | Should Not Throw
            [System.IO.File]::ReadAllText($p) | Should Be 'edited'
        }
    }

    It 'reads the attributes of a PLC data type, which come after its keyword, in the form TIA writes' {
        Test-FBlockDocument (New-Doc 'FUdt.s7dcl' "TYPE`r`n    { S7_Safety := `"True`" }`r`n    PlainData : STRUCT`r`n    END_STRUCT;`r`nEND_TYPE") | Should Be $true
        Test-FBlockDocument (New-Doc 'FUdtQ.s7dcl' "TYPE`r`n    {`r`n        S7_BlockComment := `"MLC_1`";`r`n        S7_Safety := `"True`"`r`n    }`r`n    `"Ns:Data`" : STRUCT`r`n    END_STRUCT;`r`nEND_TYPE") | Should Be $true
        Test-FBlockDocument (New-Doc 'SUdt.s7dcl' "TYPE`r`n    { S7_BlockTitle := `"MLC_1`" }`r`n    PlainData : STRUCT`r`n    END_STRUCT;`r`nEND_TYPE") | Should Be $false
        Test-FBlockDocument (New-Doc 'SUdt2.s7dcl' "TYPE`r`n    PlainData : STRUCT`r`n    S7_Safety : Bool;`r`n    END_STRUCT;`r`nEND_TYPE") | Should Be $false
    }

    It 'reads the F-compliant mark of a PLC data type in SimaticML' {
        Test-FBlockDocument (New-Doc 'FUdtX.xml' '<Document><SW.Types.PlcStruct ID="0"><AttributeList><IsFailsafeCompliant>true</IsFailsafeCompliant></AttributeList></SW.Types.PlcStruct></Document>') | Should Be $true
        Test-FBlockDocument (New-Doc 'SUdtX.xml' '<Document><SW.Types.PlcStruct ID="0"><AttributeList><IsFailsafeCompliant>false</IsFailsafeCompliant></AttributeList></SW.Types.PlcStruct></Document>') | Should Be $false
    }

    It 'reads the documents beside a library type file that is neither (.libinfo)' {
        $null = New-Doc 'LibF.s7dcl' "{ S7_Safety := `"True`" }`r`nFUNCTION_BLOCK `"LibF`"`r`nEND_FUNCTION_BLOCK"
        Test-FBlockDocument (New-Doc 'LibF.libinfo' 'x') | Should Be $true
        Test-FBlockDocument (New-Doc 'LibS.libinfo' 'x') | Should Be $false
    }
}

Describe 'Faceplate guard' {
    $library = @(
        @{ name = 'faceplatePump20Operate'; folder = 'Redesign/Faceplate'; versions = @('0.0.1', '0.0.3') }
        @{ name = 'faceplateSafetyDevice'; folder = 'Redesign/Faceplate'; versions = @('1.0.0') }
    )

    It 'reads every FaceplateTypeName of a screen file' {
        $refs = @(Get-FaceplateRefs (Join-Path $fx 'Screen_Faceplates.xml'))
        $refs.Count | Should Be 3
        $refs[0].name | Should Be 'faceplatePump20Operate'
        $refs[0].version | Should Be '0.0.2'
        $refs[0].folder | Should Be 'Redesign/Faceplate'
        $refs[2].folder | Should Be ''
    }

    It 'reports a missing version with the versions the library has, and a missing type' {
        $problems = @(Test-FaceplateRefs -Refs (Get-FaceplateRefs (Join-Path $fx 'Screen_Faceplates.xml')) -LibraryTypes $library)
        $problems.Count | Should Be 2
        $problems[0].type | Should Be 'faceplatePump20Operate'
        $problems[0].reason | Should Match 'V 0.0.2'
        ($problems[0].available -join ',') | Should Be '0.0.1,0.0.3'
        $problems[1].type | Should Be 'faceplateMissing'
        $problems[1].reason | Should Match 'not in the project library'
    }

    It 'passes a screen whose faceplate types are all in the library' {
        $refs = @(Get-FaceplateRefs (Join-Path $fx 'Screen_Faceplates.xml'))[1]
        @(Test-FaceplateRefs -Refs $refs -LibraryTypes $library).Count | Should Be 0
    }
}
