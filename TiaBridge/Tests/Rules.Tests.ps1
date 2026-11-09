$here = Split-Path -Parent $MyInvocation.MyCommand.Path
. (Join-Path $here '..\Repo.ps1')   # Write-TextFile
. (Join-Path $here '..\Rules.ps1')

function Ok([string]$Name) { @{ name = $Name; ok = $true } }
function Failed([string]$Name) { @{ name = $Name; ok = $false } }

Describe 'Test-WriteAllowed (archive gate, 6.1)' {
    It 'refuses writes until the session archive exists' {
        $s = New-SessionState
        Test-WriteAllowed $s | Should Match 'archive'
        Register-Archive $s
        Test-WriteAllowed $s | Should BeNullOrEmpty
    }

    It 'allows writes once the archive was skipped on request' {
        $s = New-SessionState
        Register-Archive $s -Skipped
        Test-WriteAllowed $s | Should BeNullOrEmpty
    }
}

Describe 'Test-SaveAllowed without a session archive (save rules, 6.2)' {
    $s = $null
    BeforeEach { $s = New-SessionState; Register-Archive $s -Skipped }

    It 'allows a save when nothing was written' {
        @(Test-SaveAllowed $s).Count | Should Be 0
    }

    It 'refuses a save after a write without a compile of that scope' {
        Register-Write $s -Scope plc -Device PLC_1 -Items @(Ok 'A')
        (Test-SaveAllowed $s) -join ' ' | Should Match 'compile'
        Register-Compile $s -Scope hmi -Device HMI_1 -ErrorCount 0
        @(Test-SaveAllowed $s).Count | Should Be 1
        Register-Compile $s -Scope plc -Device PLC_1 -ErrorCount 0
        @(Test-SaveAllowed $s).Count | Should Be 0
    }

    It 'counts a compile of a block list only for the blocks in it' {
        Register-Write $s -Scope plc -Device PLC_1 -Items @((Ok 'A'), (Ok 'B'))
        Register-Compile $s -Scope plc -Device PLC_1 -Names @('A') -ErrorCount 0
        (Test-SaveAllowed $s) -join ' ' | Should Match 'B'
        Register-Compile $s -Scope plc -Device PLC_1 -Names @('b') -ErrorCount 0
        @(Test-SaveAllowed $s).Count | Should Be 0
    }

    It 'refuses a save while the last compile of a scope reported errors, warnings are fine' {
        Register-Write $s -Scope hmi -Device HMI_1 -Items @(Ok 'Screen1')
        Register-Compile $s -Scope hmi -Device HMI_1 -ErrorCount 2
        (Test-SaveAllowed $s) -join ' ' | Should Match 'error'
        Register-Compile $s -Scope hmi -Device HMI_1 -ErrorCount 0
        @(Test-SaveAllowed $s).Count | Should Be 0
    }

    It 'keeps errors of a full compile when a later compile of single blocks is clean' {
        Register-Write $s -Scope plc -Device PLC_1 -Items @(Ok 'A')
        Register-Compile $s -Scope plc -Device PLC_1 -ErrorCount 3
        Register-Compile $s -Scope plc -Device PLC_1 -Names @('A') -ErrorCount 0
        (Test-SaveAllowed $s) -join ' ' | Should Match 'error'
        Register-Compile $s -Scope plc -Device PLC_1 -ErrorCount 0
        @(Test-SaveAllowed $s).Count | Should Be 0
    }

    It 'refuses a save after a failed write until the same object is written successfully and compiled' {
        Register-Write $s -Scope plc -Device PLC_1 -Items @((Ok 'A'), (Failed 'B'))
        Register-Compile $s -Scope plc -Device PLC_1 -ErrorCount 0
        (Test-SaveAllowed $s) -join ' ' | Should Match 'B'
        Register-Write $s -Scope plc -Device PLC_1 -Items @(Ok 'B')
        Register-Compile $s -Scope plc -Device PLC_1 -ErrorCount 0
        @(Test-SaveAllowed $s).Count | Should Be 0
    }

    It 'counts a failed library write (a master copy) against the save until it succeeds, but asks no compile for it' {
        Register-LibraryWrite $s -Name 'mc:DriveVerticalAxis' -Ok $false
        (Test-SaveAllowed $s) -join ' ' | Should Match 'mc:DriveVerticalAxis'
        Register-LibraryWrite $s -Name 'mc:DriveVerticalAxis' -Ok $true
        @(Test-SaveAllowed $s).Count | Should Be 0
    }

    It 'starts clean after a save and keeps the archive' {
        Register-Write $s -Scope plc -Device PLC_1 -Items @(Failed 'A')
        Register-Save $s
        @(Test-SaveAllowed $s).Count | Should Be 0
        Test-WriteAllowed $s | Should BeNullOrEmpty
    }

    It 'keeps the writes across a bridge restart through the project repo, but not the archive gate' {
        $repo = Join-Path $TestDrive 'sessionrepo'
        New-Item -ItemType Directory -Force -Path $repo | Out-Null
        $a = New-SessionState
        Register-Archive $a
        Register-Write $a -Scope plc -Device PLC_1 -Items @(@{ name = 'typeHmiCycle'; ok = $true })
        Register-Write $a -Scope hmi -Device HMI_1 -Items @(Failed 'Screen')
        Save-SessionWrites $repo $a
        $b = New-SessionState
        Restore-SessionWrites $repo $b
        (Test-SaveAllowed $b) -join ' ' | Should Match 'plc@PLC_1:typeHmiCycle'
        (Test-SaveAllowed $b) -join ' ' | Should Match 'hmi@HMI_1:Screen'
        Test-WriteAllowed $b | Should Match 'archive'
    }

    It 'forgets the writes of a project closed without saving, and keeps the archive' {
        Register-Write $s -Scope hmi -Device HMI_1 -Items @(@{ name = 'library update'; ok = $true })
        @(Test-SaveAllowed $s).Count | Should Be 1
        Clear-SessionWrites $s
        @(Test-SaveAllowed $s).Count | Should Be 0
        Test-WriteAllowed $s | Should BeNullOrEmpty
    }
}

Describe 'save with a session archive' {
    $s = $null
    BeforeEach { $s = New-SessionState; Register-Archive $s }

    It 'goes through over a write not compiled and over compile errors, and names them per device' {
        Register-Write $s -Scope plc -Device PLC_1 -Items @((Ok 'B'), (Ok 'A'))
        Register-Compile $s -Scope hmi -Device HMI_1 -ErrorCount 22 -Messages @('Screen1: broken')
        @(Test-SaveAllowed $s).Count | Should Be 0
        $at = @(Get-SaveStanding $s)
        ($at | ForEach-Object { $_.device }) -join ',' | Should Be 'hmi@HMI_1,plc@PLC_1'
        @($at[1].notCompiled) -join ',' | Should Be 'A,B'
        $at[0].compileErrors.errors | Should Be 22
        @($at[0].compileErrors.messages) -join ',' | Should Be 'Screen1: broken'
        @($at[0].notCompiled).Count | Should Be 0
    }

    It 'still refuses a failed write, also one into a library' {
        Register-Write $s -Scope plc -Device PLC_1 -Items @(Failed 'A')
        (Test-SaveAllowed $s) -join ' ' | Should Match 'plc@PLC_1:A'
        Register-LibraryWrite $s -Name 'mc:X' -Ok $false
        (Test-SaveAllowed $s) -join ' ' | Should Match 'mc:X'
    }

    It 'stands empty once all is compiled clean, and after a save' {
        Register-Write $s -Scope plc -Device PLC_1 -Items @(Ok 'A')
        Register-Compile $s -Scope plc -Device PLC_1 -ErrorCount 0
        @(Get-SaveStanding $s).Count | Should Be 0
        Register-Compile $s -Scope plc -Device PLC_1 -ErrorCount 1
        @(Get-SaveStanding $s).Count | Should Be 1
        Register-Save $s
        @(Get-SaveStanding $s).Count | Should Be 0
    }

    It 'does not name a failed write as not compiled' {
        Register-Write $s -Scope plc -Device PLC_1 -Items @(Failed 'A')
        @(Get-SaveStanding $s).Count | Should Be 0
    }

    It 'holds nothing for an object the device does not have, and leaves the other device' {
        Register-Write $s -Scope plc -Device @('PLC_1', 'PLC_2') -Items @(Ok 'A')
        Register-Write $s -Scope plc -Device PLC_1 -Items @(Failed 'A')
        Clear-ObjectWrites $s plc PLC_1 @('a')
        @($s.pending.Values) -join ',' | Should Be 'plc@PLC_2:A'
        $s.failed.Count | Should Be 0
    }

    It 'a compile by name with errors adds to what a whole compile found, and does not shrink it' {
        Register-Compile $s -Scope plc -Device PLC_1 -ErrorCount 22 -Messages @(1..22 | ForEach-Object { "e$_" })
        Register-Compile $s -Scope plc -Device PLC_1 -Names @('A') -ErrorCount 1 -Messages @('A: broken')
        $e = @(Get-SaveStanding $s)[0].compileErrors
        $e.errors | Should Be 23
        @($e.messages).Count | Should Be 10
        @($s.compileErrors['plc@PLC_1'].messages) -ccontains 'A: broken' | Should Be $true
    }

    It 'a clean compile by name takes back the errors of that name, as a save would quote what is gone' {
        $s = New-SessionState
        Register-Compile $s 'plc' 'P' @() 2 @('C: broken.', 'D: broken too.')
        Register-Compile $s 'plc' 'P' @('c') 0
        $s.compileErrors['plc@P'].errors | Should Be 1
        @($s.compileErrors['plc@P'].messages) | Should Be 'D: broken too.'
        Register-Compile $s 'plc' 'P' @('D') 0
        $s.compileErrors.ContainsKey('plc@P') | Should Be $false
        @(Get-SaveStanding $s).Count | Should Be 0
    }

    It 'a clean compile by name leaves the errors of other names, and of a name that only starts the same' {
        $s = New-SessionState
        Register-Compile $s 'plc' 'P' @() 2 @('C: broken.', 'CD: broken too.')
        Register-Compile $s 'plc' 'P' @('Other', 'C') 0
        @($s.compileErrors['plc@P'].messages) | Should Be 'CD: broken too.'
        $s.compileErrors['plc@P'].errors | Should Be 1
    }

    It 'a compile by name with errors takes nothing back' {
        $s = New-SessionState
        Register-Compile $s 'plc' 'P' @() 1 @('C: broken.')
        Register-Compile $s 'plc' 'P' @('C') 1 @('C: broken.')
        $s.compileErrors['plc@P'].errors | Should Be 1
    }

    It 'a count that says more than the texts stays' {
        $s = New-SessionState
        Register-Compile $s 'plc' 'P' @() 3 @('C: broken.')
        Register-Compile $s 'plc' 'P' @('C') 0
        $s.compileErrors['plc@P'].errors | Should Be 2
        @($s.compileErrors['plc@P'].messages).Count | Should Be 0
    }

    It 'a clean compile by name takes back two errors of one text' {
        $s = New-SessionState
        Register-Compile $s 'plc' 'P' @('C') 2 @('C: Tag #x not defined.', 'C: Tag #x not defined.')
        @($s.compileErrors['plc@P'].messages).Count | Should Be 1
        Register-Compile $s 'plc' 'P' @('C') 0
        $s.compileErrors.ContainsKey('plc@P') | Should Be $false
        @(Test-SaveAllowed $s).Count | Should Be 0
    }

    It 'two errors of one text beside another name: only that name goes' {
        $s = New-SessionState
        Register-Compile $s 'plc' 'P' @() 3 @('C: same.', 'C: same.', 'D: other.')
        Register-Compile $s 'plc' 'P' @('C') 0
        $s.compileErrors['plc@P'].errors | Should Be 1
        @($s.compileErrors['plc@P'].messages) | Should Be 'D: other.'
    }

    It 'the same error found again by name still does not count twice, and all of it goes at once' {
        $s = New-SessionState
        Register-Compile $s 'plc' 'P' @() 1 @('C: same.')
        Register-Compile $s 'plc' 'P' @('C') 1 @('C: same.')
        $s.compileErrors['plc@P'].errors | Should Be 1
        Register-Compile $s 'plc' 'P' @('C') 0
        $s.compileErrors.ContainsKey('plc@P') | Should Be $false
    }

    It 'a clean compile by name takes back from a record read back from the session file' {
        $s = New-SessionState
        $s.compileErrors['plc@P'] = ('{"errors": 2, "messages": ["C: same."], "occurrences": ["C: same.", "C: same."]}' | ConvertFrom-Json)
        Register-Compile $s 'plc' 'P' @('C') 0
        $s.compileErrors.ContainsKey('plc@P') | Should Be $false
    }

    It 'a clean compile by name keeps the flag of an older session file' {
        $s = New-SessionState
        $s.compileErrors['plc@P'] = $true
        Register-Compile $s 'plc' 'P' @('C') 0
        $s.compileErrors['plc@P'] | Should Be $true
    }

    It 'two compiles by name keep the errors of both' {
        Register-Compile $s -Scope plc -Device PLC_1 -Names @('A') -ErrorCount 2 -Messages @('A: one', 'A: two')
        Register-Compile $s -Scope plc -Device PLC_1 -Names @('B') -ErrorCount 1 -Messages @('B: broken')
        $e = @(Get-SaveStanding $s)[0].compileErrors
        $e.errors | Should Be 3
        @($e.messages) -join ',' | Should Be 'A: one,A: two,B: broken'
    }

    It 'the same error found again by name does not count twice' {
        Register-Compile $s -Scope plc -Device PLC_1 -ErrorCount 2 -Messages @('A: broken', 'B: broken')
        Register-Compile $s -Scope plc -Device PLC_1 -Names @('A') -ErrorCount 1 -Messages @('A: broken')
        Register-Compile $s -Scope plc -Device PLC_1 -Names @('A') -ErrorCount 1 -Messages @('A: broken')
        @(Get-SaveStanding $s)[0].compileErrors.errors | Should Be 2
    }

    It 'a whole compile with errors replaces the record, a clean one clears it' {
        Register-Compile $s -Scope plc -Device PLC_1 -Names @('A') -ErrorCount 2 -Messages @('A: one', 'A: two')
        Register-Compile $s -Scope plc -Device PLC_1 -ErrorCount 1 -Messages @('B: broken')
        $e = @(Get-SaveStanding $s)[0].compileErrors
        $e.errors | Should Be 1
        @($e.messages) -join ',' | Should Be 'B: broken'
        Register-Compile $s -Scope plc -Device PLC_1 -ErrorCount 0
        @(Get-SaveStanding $s).Count | Should Be 0
    }

    It 'a compile by name after the flag of an older session file keeps the count unknown' {
        $s.compileErrors['plc@PLC_1'] = $true
        Register-Compile $s -Scope plc -Device PLC_1 -Names @('A') -ErrorCount 1 -Messages @('A: broken')
        $e = @(Get-SaveStanding $s)[0].compileErrors
        $e.errors | Should BeNullOrEmpty
        @($e.messages) -join ',' | Should Be 'A: broken'
    }

    It 'a compile by name adds to a record read back from the session file' {
        $repo = Join-Path $TestDrive 'mergerepo'
        New-Item -ItemType Directory -Force -Path $repo | Out-Null
        Register-Compile $s -Scope plc -Device PLC_1 -ErrorCount 2 -Messages @('X: broken', 'Y: broken')
        Save-SessionWrites $repo $s
        $b = New-SessionState
        Restore-SessionWrites $repo $b
        Register-Compile $b -Scope plc -Device PLC_1 -Names @('A') -ErrorCount 1 -Messages @('A: broken')
        $e = @(Get-SaveStanding $b)[0].compileErrors
        $e.errors | Should Be 3
        @($e.messages) -join ',' | Should Be 'X: broken,Y: broken,A: broken'
    }

    It 'keeps the first ten messages and the whole count' {
        Register-Compile $s -Scope plc -Device PLC_1 -ErrorCount 12 -Messages @(1..12 | ForEach-Object { "e$_" })
        $e = @(Get-SaveStanding $s)[0].compileErrors
        $e.errors | Should Be 12
        @($e.messages).Count | Should Be 10
    }

    It 'names the errors through a clean compile of some blocks, until a whole compile is clean' {
        Register-Compile $s -Scope plc -Device PLC_1 -ErrorCount 3 -Messages @('X: broken')
        Register-Compile $s -Scope plc -Device PLC_1 -Names @('A') -ErrorCount 0
        @(Get-SaveStanding $s)[0].compileErrors.errors | Should Be 3
        Register-Compile $s -Scope plc -Device PLC_1 -ErrorCount 0
        @(Get-SaveStanding $s).Count | Should Be 0
    }

    It 'names what stands across a bridge restart, also the flag of an older session file' {
        $repo = Join-Path $TestDrive 'standingrepo'
        New-Item -ItemType Directory -Force -Path $repo | Out-Null
        Register-Write $s -Scope plc -Device PLC_1 -Items @(Ok 'Ns:Block')
        Register-Compile $s -Scope hmi -Device HMI_1 -ErrorCount 2 -Messages @('Screen1: broken')
        Save-SessionWrites $repo $s
        $b = New-SessionState
        Restore-SessionWrites $repo $b
        $b.compileErrors['hmi@HMI_2'] = $true
        $at = @(Get-SaveStanding $b)
        ($at | ForEach-Object { $_.device }) -join ',' | Should Be 'hmi@HMI_1,hmi@HMI_2,plc@PLC_1'
        $at[0].compileErrors.errors | Should Be 2
        @($at[0].compileErrors.messages) -join ',' | Should Be 'Screen1: broken'
        $at[1].compileErrors.errors | Should BeNullOrEmpty
        @($at[2].notCompiled) -join ',' | Should Be 'Ns:Block'
    }
}

Describe 'a compile of a library type''s name' {
    $s = $null
    BeforeEach { $s = New-SessionState; Register-Archive $s -Skipped }

    It 'clears the write of the type on that device only' {
        Register-LibraryTypeWrite $s 'plc' @('PLC_1', 'PLC_2') 'type:T' $true
        Register-Compile $s -Scope plc -Device PLC_1 -Names @('t') -ErrorCount 0
        @($s.pending.Values) -join ',' | Should Be 'plc@PLC_2:type:T'
        (Test-SaveAllowed $s) -join ' ' | Should Match 'plc@PLC_2:type:T'
    }

    It 'leaves a failed write of the type refused' {
        Register-LibraryTypeWrite $s 'plc' @('PLC_1') 'type:T' $false
        Register-Compile $s -Scope plc -Device PLC_1 -Names @('T') -ErrorCount 0
        (Test-SaveAllowed $s) -join ' ' | Should Match 'plc@PLC_1:type:T'
    }
}

Describe 'save rules per device' {
    $s = $null
    BeforeEach { $s = New-SessionState; Register-Archive $s -Skipped }

    It 'refuses the save after a write into PLC_2 and a clean compile of PLC_1, until PLC_2 compiles clean' {
        Register-Write $s -Scope plc -Device PLC_2 -Items @(Ok 'A')
        Register-Compile $s -Scope plc -Device PLC_1 -ErrorCount 0
        (Test-SaveAllowed $s) -join ' ' | Should Match 'plc@PLC_2:A'
        Register-Compile $s -Scope plc -Device PLC_2 -ErrorCount 0
        @(Test-SaveAllowed $s).Count | Should Be 0
    }

    It 'keeps the errors of PLC_2 through a clean compile of PLC_1 and names the device' {
        Register-Compile $s -Scope plc -Device PLC_2 -ErrorCount 1
        Register-Compile $s -Scope plc -Device PLC_1 -ErrorCount 0
        (Test-SaveAllowed $s) -join ' ' | Should Match 'plc@PLC_2'
        (Test-SaveAllowed $s) -join ' ' | Should Not Match 'plc@PLC_1'
        Register-Compile $s -Scope plc -Device PLC_2 -ErrorCount 0
        @(Test-SaveAllowed $s).Count | Should Be 0
    }

    It 'does the same for several HMI devices' {
        Register-Write $s -Scope hmi -Device HMI_B -Items @(Ok 'Screen1')
        Register-Compile $s -Scope hmi -Device HMI_A -ErrorCount 0
        (Test-SaveAllowed $s) -join ' ' | Should Match 'hmi@HMI_B:Screen1'
        Register-Compile $s -Scope hmi -Device HMI_B -ErrorCount 2
        (Test-SaveAllowed $s) -join ' ' | Should Match "'hmi@HMI_B' reported errors"
        Register-Compile $s -Scope hmi -Device HMI_B -ErrorCount 0
        @(Test-SaveAllowed $s).Count | Should Be 0
    }

    It 'clears a block of the same name on the compiled device only' {
        Register-Write $s -Scope plc -Device PLC_1 -Items @(Ok 'A')
        Register-Write $s -Scope plc -Device PLC_2 -Items @(Ok 'A')
        Register-Compile $s -Scope plc -Device PLC_1 -Names @('A') -ErrorCount 0
        @(Test-SaveAllowed $s).Count | Should Be 1
        (Test-SaveAllowed $s) -join ' ' | Should Match 'plc@PLC_2:A'
    }

    It 'keeps a failed write on its device: redoing it on the other device does not clear it' {
        Register-Write $s -Scope plc -Device PLC_2 -Items @(Failed 'A')
        Register-Write $s -Scope plc -Device PLC_1 -Items @(Ok 'A')
        (Test-SaveAllowed $s) -join ' ' | Should Match 'failed.*plc@PLC_2:A'
    }

    It 'takes a device name with wildcard characters literally' {
        Register-Write $s -Scope plc -Device 'PLC[1]' -Items @(Ok 'A')
        Register-Compile $s -Scope plc -Device 'PLC[1]' -ErrorCount 0
        @(Test-SaveAllowed $s).Count | Should Be 0
    }

    It 'registers one write for several devices, and each needs its compile' {
        Register-Write $s -Scope plc -Device @('PLC_1', 'PLC_2') -Items @(Ok 'library update')
        Register-Compile $s -Scope plc -Device PLC_1 -ErrorCount 0
        (Test-SaveAllowed $s) -join ' ' | Should Match 'plc@PLC_2:library update'
        Register-Compile $s -Scope plc -Device PLC_2 -ErrorCount 0
        @(Test-SaveAllowed $s).Count | Should Be 0
    }

    It 'refuses a write or a compile without a device, so no tool drops it unnoticed' {
        { Register-Write $s -Scope plc -Device @() -Items @(Ok 'A') } | Should Throw 'without a device'
        { Register-Compile $s -Scope plc -Device '' -ErrorCount 0 } | Should Throw 'without a device'
    }

    It 'counts a library type write for every device of its scope; with none, only its failure counts' {
        Register-LibraryTypeWrite $s 'plc' @('PLC_1', 'PLC_2') 'type:T' $true
        @($s.pending.Values | Sort-Object) -join ',' | Should Be 'plc@PLC_1:type:T,plc@PLC_2:type:T'
        $none = New-SessionState
        Register-LibraryTypeWrite $none 'hmi' @() 'type:F' $true
        @(Test-SaveAllowed $none).Count | Should Be 0
        Register-LibraryTypeWrite $none 'hmi' @() 'type:F' $false
        (Test-SaveAllowed $none) -join ' ' | Should Match 'type:F'
    }
}

Describe 'reading a session file with the keys from before the rules counted per device' {
    $software = @(@{ device = 'PLC_1'; kind = 'plc' }, @{ device = 'PLC_2'; kind = 'plc' }, @{ device = 'HMI_A'; kind = 'hmi' })

    function Restore-Old([string]$Json, [object[]]$Devices = $software) {
        $repo = Join-Path $TestDrive ('old' + [guid]::NewGuid().ToString('N'))
        New-Item -ItemType Directory -Force -Path $repo | Out-Null
        Set-Content -LiteralPath (Join-Path $repo '.tiabridge-session.json') -Value $Json -Encoding UTF8
        $st = New-SessionState
        Restore-SessionWrites $repo $st $Devices
        $st
    }

    It 'counts a pending write for every device of the scope, so each must compile before a save' {
        $st = Restore-Old '{ "pending": { "plc:a": "plc:A" }, "failed": { }, "compileErrors": { } }'
        @($st.pending.Values | Sort-Object) -join ',' | Should Be 'plc@PLC_1:A,plc@PLC_2:A'
        Register-Compile $st -Scope plc -Device PLC_1 -ErrorCount 0
        (Test-SaveAllowed $st) -join ' ' | Should Match 'plc@PLC_2:A'
        Register-Compile $st -Scope plc -Device PLC_2 -ErrorCount 0
        @(Test-SaveAllowed $st).Count | Should Be 0
    }

    It 'counts a failed write for every device of the scope and leaves a library write alone' {
        $st = Restore-Old '{ "pending": { }, "failed": { "hmi:screen": "hmi:Screen", "plc:b": "plc:B", "library:mc:x": "mc:X" }, "compileErrors": { } }'
        @($st.failed.Values | Sort-Object) -join ',' | Should Be 'hmi@HMI_A:Screen,mc:X,plc@PLC_1:B,plc@PLC_2:B'
        Register-Write $st -Scope plc -Device PLC_1 -Items @(Ok 'B')
        (Test-SaveAllowed $st) -join ' ' | Should Match 'plc@PLC_2:B'
    }

    It 'counts compile errors for every device of the scope and drops a clean flag' {
        $st = Restore-Old '{ "pending": { }, "failed": { }, "compileErrors": { "plc": true, "hmi": false } }'
        $st.compileErrors.ContainsKey('plc') | Should Be $false
        $st.compileErrors.ContainsKey('hmi') | Should Be $false
        (Test-SaveAllowed $st) -join ' ' | Should Match 'plc@PLC_1'
        Register-Compile $st -Scope plc -Device PLC_1 -ErrorCount 0
        (Test-SaveAllowed $st) -join ' ' | Should Match 'plc@PLC_2'
        Register-Compile $st -Scope plc -Device PLC_2 -ErrorCount 0
        @(Test-SaveAllowed $st).Count | Should Be 0
    }

    It 'keeps an entry whose scope has no device, so nothing pending is lost' {
        $st = Restore-Old '{ "pending": { "hmi:s": "hmi:S" }, "failed": { }, "compileErrors": { "hmi": true } }' @(@{ device = 'PLC_1'; kind = 'plc' })
        (Test-SaveAllowed $st) -join ' ' | Should Match 'hmi:S'
        (Test-SaveAllowed $st) -join ' ' | Should Match "'hmi' reported errors"
    }

    It 'leaves keys of the new form as they are, and writes the new form back' {
        $st = Restore-Old '{ "pending": { "plc@plc_2:a": "plc@PLC_2:A", "plc:b": "plc:B" }, "failed": { }, "compileErrors": { "plc@PLC_2": true } }'
        @($st.pending.Values | Sort-Object) -join ',' | Should Be 'plc@PLC_1:B,plc@PLC_2:A,plc@PLC_2:B'
        $st.compileErrors['plc@PLC_2'] | Should Be $true
        $st.compileErrors.ContainsKey('plc@PLC_1') | Should Be $false
        $repo = Join-Path $TestDrive 'written'
        New-Item -ItemType Directory -Force -Path $repo | Out-Null
        Save-SessionWrites $repo $st
        $text = Get-Content -LiteralPath (Join-Path $repo '.tiabridge-session.json') -Raw
        $text | Should Match 'plc@PLC_1:B'
        $text | Should Not Match '"plc:b"'
    }
}
