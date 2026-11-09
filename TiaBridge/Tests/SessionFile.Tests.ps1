# The session file on disk: how it is written, and what a save gate reads back after the write went wrong.
$here = Split-Path -Parent $MyInvocation.MyCommand.Path
. (Join-Path $here '..\Repo.ps1')
. (Join-Path $here '..\Rules.ps1')

Describe 'an interrupted replacement of the session file' {
    function New-FailedRecord([string]$Repo) {
        New-Item -ItemType Directory -Force -Path $Repo | Out-Null
        $s = New-SessionState
        Register-Write $s -Scope plc -Device PLC_1 -Items @(@{ name = 'Broken'; ok = $false })
        Save-SessionWrites $Repo $s
        $s
    }
    function Read-SaveBlockers([string]$Repo) {
        $b = New-SessionState
        Restore-SessionWrites $Repo $b
        $b.archived = $true     # with an archive only a failed write refuses
        (Test-SaveAllowed $b) -join ' '
    }

    Context 'the disk fills up' {     # a mock lasts to the end of its block
        It 'keeps the record before it when the write stops half way' {
            $repo = Join-Path $TestDrive 'halfway'
            $s = New-FailedRecord $repo
            Mock Write-TextFile { [System.IO.File]::WriteAllText($Path, $Text.Substring(0, 5)); throw 'disk full' }
            { Save-SessionWrites $repo $s } | Should Throw 'disk full'
            Read-SaveBlockers $repo | Should Match 'plc@PLC_1:Broken'
        }
    }

    # ReplaceFile, on ERROR_UNABLE_TO_MOVE_REPLACEMENT without a backup name: the old file gone, the new one under its temporary name
    Context 'the replace fails having removed the old file' {
        It 'stores the new record' {
            $repo = Join-Path $TestDrive 'gone'
            $s = New-FailedRecord $repo
            Register-Write $s -Scope plc -Device PLC_1 -Items @(@{ name = 'Newer'; ok = $false })
            $script:moves = 0
            Mock Move-FileOver {
                $script:moves++
                if ($script:moves -gt 1) { [System.IO.File]::Move($From, $To); return }
                Remove-Item -LiteralPath $To
                throw 'unable to move replacement'
            }
            Save-SessionWrites $repo $s
            Read-SaveBlockers $repo | Should Match 'plc@PLC_1:Newer'
            @(Get-ChildItem -LiteralPath $repo -Force | ForEach-Object { $_.Name }) -join ',' | Should Be '.tiabridge-session.json'
        }
    }

    Context 'the replace fails having removed the old file, and the move after it too' {
        It 'says so and keeps the only copy' {
            $repo = Join-Path $TestDrive 'gonetwice'
            $s = New-FailedRecord $repo
            Mock Move-FileOver { if (Test-Path -LiteralPath $To) { Remove-Item -LiteralPath $To }; throw 'unable to move replacement' }
            { Save-SessionWrites $repo $s } | Should Throw 'unable to move replacement'
            @(Get-ChildItem -LiteralPath $repo -Force | ForEach-Object { $_.Name }) -join ',' | Should Match '^\.tiabridge-session\.json\.\d+\.tmp$'
            Read-SaveBlockers $repo | Should Match '\.tiabridge-session\.json\.\d+\.tmp'
        }
    }

    It 'keeps the record before it when the replace itself fails, and leaves no temporary file' {
        $repo = Join-Path $TestDrive 'held'
        $s = New-FailedRecord $repo
        $file = Join-Path $repo '.tiabridge-session.json'
        $held = [System.IO.File]::Open($file, 'Open', 'Read', 'Read')
        try { { Save-SessionWrites $repo $s } | Should Throw } finally { $held.Dispose() }
        Read-SaveBlockers $repo | Should Match 'plc@PLC_1:Broken'
        @(Get-ChildItem -LiteralPath $repo -Force | ForEach-Object { $_.Name }) -join ',' | Should Be '.tiabridge-session.json'
    }

    It 'reads the record, not what a process killed before the replace left beside it' {
        $repo = Join-Path $TestDrive 'killed'
        $null = New-FailedRecord $repo
        [System.IO.File]::WriteAllText((Join-Path $repo '.tiabridge-session.json.4711.tmp'), '{"failed":')
        Read-SaveBlockers $repo | Should Match 'plc@PLC_1:Broken'
    }

    It 'replaces the record it had, and makes a first one' {
        $repo = Join-Path $TestDrive 'replace'
        $s = New-FailedRecord $repo
        $s.failed.Clear()
        Save-SessionWrites $repo $s
        Read-SaveBlockers $repo | Should BeNullOrEmpty
        @(Get-ChildItem -LiteralPath $repo -Force | ForEach-Object { $_.Name }) -join ',' | Should Be '.tiabridge-session.json'
    }
}

Describe 'the temporary session file in the project repo' {
    function Test-Ignored([string]$Repo, [string]$Name) {
        & git -C $Repo check-ignore -q $Name 2>$null
        $LASTEXITCODE -eq 0
    }

    It 'is ignored in a new repo' {
        $r = Initialize-ProjectRepo -Root (Join-Path $TestDrive 'newRoot') -ProjectName 'New' -ProjectPath 'C:\n.ap20' -PlcDevices @() -HmiDevices @() -BackgroundSource 'C:\n.ap20'
        Test-Ignored $r.repo '.tiabridge-session.json.4711.tmp' | Should Be $true
    }

    It 'a repo made before gets the line at connect, once' {
        $root = Join-Path $TestDrive 'oldRoot'
        $a = Initialize-ProjectRepo -Root $root -ProjectName 'Old' -ProjectPath 'C:\o.ap20' -PlcDevices @() -HmiDevices @() -BackgroundSource 'C:\o.ap20'
        $gi = Join-Path $a.repo '.gitignore'
        [System.IO.File]::WriteAllText($gi, "archives/`n.tiabridge-session.json`n")
        Test-Ignored $a.repo '.tiabridge-session.json.4711.tmp' | Should Be $false
        foreach ($i in 1, 2) { $null = Initialize-ProjectRepo -Root $root -ProjectName 'Old' -ProjectPath 'C:\o.ap20' -PlcDevices @() -HmiDevices @() -BackgroundSource 'C:\o.ap20' }
        Test-Ignored $a.repo '.tiabridge-session.json.4711.tmp' | Should Be $true
        @([regex]::Matches([System.IO.File]::ReadAllText($gi), [regex]::Escape('.tiabridge-session.json.*.tmp'))).Count | Should Be 1
    }
}

Describe 'a session record that cannot be read' {
    function New-RepoWith([string]$Content) {
        $repo = Join-Path $TestDrive ('r' + [guid]::NewGuid().ToString('N'))
        New-Item -ItemType Directory -Force -Path $repo | Out-Null
        [System.IO.File]::WriteAllText((Join-Path $repo '.tiabridge-session.json'), $Content)
        $repo
    }
    function Restore-Archived([string]$Repo) {
        $s = New-SessionState
        Restore-SessionWrites $Repo $s @(@{ device = 'PLC_1'; kind = 'plc' })     # with a device: the old keys are expanded for it
        $s.archived = $true     # the gate that stood with a failed write only; the archive gate is passed
        $s
    }
    $complete = '"pending":{},"failed":{},"compileErrors":{}'

    # file content -> what the refusal says is wrong with it
    $damaged = @(
        @('{"failed":', 'not valid JSON'),
        @('', 'empty'),
        @('[]', 'not a record'),
        @('null', 'not a record'),
        @('5', 'not a record'),
        @('{}', 'pending'),
        @('{"pending":{}}', 'failed'),
        @('{"pending":{},"failed":{}}', 'compileErrors'),
        @('{"pending":{},"failed":5,"compileErrors":{}}', 'failed'),
        @('{"pending":[],"failed":{},"compileErrors":{}}', 'pending'),
        @('{"pending":{},"failed":null,"compileErrors":{}}', 'failed'),
        @('{"pending":{},"failed":"x","compileErrors":{}}', 'failed'),
        @("{$complete,`"written`":5}", 'written'),
        @("{$complete,`"notConsistent`":null}", 'notConsistent'),
        @('{"pending":{"plc:x":null},"failed":{},"compileErrors":{}}', 'pending'),
        @('{"pending":{"plc:x":5},"failed":{},"compileErrors":{}}', 'pending'),
        @('{"pending":{"plc:x":"ab"},"failed":{},"compileErrors":{}}', 'pending'),
        @('{"pending":{},"failed":{"plc@p:x":null},"compileErrors":{}}', 'failed'),
        @('{"pending":{},"failed":{"plc@p:x":{"a":1}},"compileErrors":{}}', 'failed'),
        @("{$complete,`"written`":{`"plc@p:x`":5}}", 'written'),
        @("{$complete,`"named`":{`"plc@p:x`":`"`"}}", 'named')
    )
    foreach ($case in $damaged) {
        $content = $case[0]; $why = $case[1]
        It "refuses writes and saves on [$content], naming the file and $why" {
            $s = Restore-Archived (New-RepoWith $content)
            Test-WriteAllowed $s | Should Match '\.tiabridge-session\.json'
            Test-WriteAllowed $s | Should Match $why
            (Test-SaveAllowed $s) -join ' ' | Should Match '\.tiabridge-session\.json'
        }
    }

    It 'refuses with archive(skip=true) as well: the skip passes the archive gate only' {
        $s = New-SessionState
        Restore-SessionWrites (New-RepoWith '{"failed":') $s
        Register-Archive $s -Skipped
        Test-WriteAllowed $s | Should Match '\.tiabridge-session\.json'
        (Test-SaveAllowed $s) -join ' ' | Should Match '\.tiabridge-session\.json'
    }

    It 'reads apart from a missing file, which is no record and refuses nothing' {
        $repo = Join-Path $TestDrive 'nofile'
        New-Item -ItemType Directory -Force -Path $repo | Out-Null
        $s = Restore-Archived $repo
        Test-WriteAllowed $s | Should BeNullOrEmpty
        @(Test-SaveAllowed $s).Count | Should Be 0
    }

    It 'refuses on a file it cannot open' {
        $repo = New-RepoWith "{$complete}"
        $held = [System.IO.File]::Open((Join-Path $repo '.tiabridge-session.json'), 'Open', 'ReadWrite', 'None')
        try { $s = Restore-Archived $repo } finally { $held.Dispose() }
        Test-WriteAllowed $s | Should Match '\.tiabridge-session\.json'
    }

    Context 'the record gone, a temporary file left beside it' {
        function New-RepoLeftTemp {
            $repo = New-RepoWith '{"pending":{},"failed":{"plc@p:a":"plc@P:A"},"compileErrors":{}}'
            Rename-Item -LiteralPath (Join-Path $repo '.tiabridge-session.json') -NewName '.tiabridge-session.json.4711.tmp'
            $repo
        }

        It 'refuses writes and saves, names the file to delete, and takes nothing from it' {
            $s = Restore-Archived (New-RepoLeftTemp)
            Test-WriteAllowed $s | Should Match 'Deleting .*\.tiabridge-session\.json\.4711\.tmp'
            (Test-SaveAllowed $s) -join ' ' | Should Match '\.tiabridge-session\.json\.4711\.tmp'
            $s.failed.Count | Should Be 0
        }

        It 'is no record once that file is deleted' {
            $repo = New-RepoLeftTemp
            Remove-Item -LiteralPath (Join-Path $repo '.tiabridge-session.json.4711.tmp')
            Test-WriteAllowed (Restore-Archived $repo) | Should BeNullOrEmpty
        }

        It 'ignores it beside a record' {
            $repo = New-RepoLeftTemp
            [System.IO.File]::WriteAllText((Join-Path $repo '.tiabridge-session.json'), "{$complete}")
            Test-WriteAllowed (Restore-Archived $repo) | Should BeNullOrEmpty
        }
    }

    It 'takes nothing from a record it refuses' {
        $s = Restore-Archived (New-RepoWith '{"pending":{"plc@p:a":"plc@P:A"},"failed":5,"compileErrors":{}}')
        $s.pending.Count | Should Be 0
    }

    It 'takes nothing from a record with one value that is no name' {
        $s = Restore-Archived (New-RepoWith '{"pending":{"plc@p:a":"plc@P:A","plc:x":5},"failed":{},"compileErrors":{}}')
        $s.pending.Count | Should Be 0
    }

    It 'still reads the old keys with their names, and a master copy with its own' {
        $s = Restore-Archived (New-RepoWith '{"pending":{"plc:x":"plc:X"},"failed":{"library:mc:m":"mc:M"},"compileErrors":{}}')
        $s.unreadable | Should BeNullOrEmpty
        @($s.pending.Values) -join ',' | Should Be 'plc@PLC_1:X'
        @($s.failed.Values) -join ',' | Should Be 'mc:M'
    }

    It 'still reads a complete older file, without the parts added later' {
        $s = Restore-Archived (New-RepoWith '{"pending":{},"failed":{"plc@p:a":"plc@P:A"},"compileErrors":{}}')
        Test-WriteAllowed $s | Should BeNullOrEmpty
        (Test-SaveAllowed $s) -join ' ' | Should Match 'plc@P:A'
    }

    It 'does not overwrite the damaged file' {
        $repo = New-RepoWith '{"failed":'
        $s = Restore-Archived $repo
        Save-SessionWrites $repo $s
        [System.IO.File]::ReadAllText((Join-Path $repo '.tiabridge-session.json')) | Should Be '{"failed":'
    }

    It 'a project without unsaved changes ends it, and the record is written again' {
        $repo = New-RepoWith '{"failed":'
        $s = Restore-Archived $repo
        Clear-SessionWrites $s
        Test-WriteAllowed $s | Should BeNullOrEmpty
        @(Test-SaveAllowed $s).Count | Should Be 0
        Save-SessionWrites $repo $s
        $b = Restore-Archived $repo
        Test-WriteAllowed $b | Should BeNullOrEmpty
    }
}
