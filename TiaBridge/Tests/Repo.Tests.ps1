$here = Split-Path -Parent $MyInvocation.MyCommand.Path
. (Join-Path $here '..\Repo.ps1')

Describe 'standards of a project repo' {
    function New-Repo([string]$Name, [string]$Template = '', [switch]$Plain) {
        Initialize-ProjectRepo -Root (Join-Path $TestDrive 'r') -ProjectName $Name -ProjectPath "C:\$Name\$Name.ap20" -PlcDevices @() -HmiDevices @() -StandardsTemplate $Template -RepoName $Name -Plain:$Plain
    }
    $template = Join-Path $TestDrive 'template'
    New-Item -ItemType Directory -Force -Path (Join-Path $template 'sub') | Out-Null
    Set-Content (Join-Path $template 'style.md') 'ours'
    Set-Content (Join-Path $template 'sub\skeleton.md') 'skeleton'

    It 'makes the folder, and says nothing while it holds no file' {
        $m = New-Repo 'Empty'
        Test-Path (Join-Path $m.repo 'standards') -PathType Container | Should Be $true
        Get-StandardsResult $m.repo | Should BeNullOrEmpty
        $m.standardsNote | Should BeNullOrEmpty
    }

    It 'names the files by path in the repo, with what to do with them' {
        $m = New-Repo 'Held'
        Set-Content (Join-Path $m.repo 'standards\a.md') 'a'
        $s = Get-StandardsResult $m.repo
        @($s.files) -join ',' | Should Be 'standards\a.md'
        $s.use | Should Match 'Before you edit, read those that fit the work'
        $s.use | Should Match 'follow the guide and tell the user'
    }

    It 'names the files whole when the repo is given by a path with .. in it' {
        $m = New-Repo 'Dotted'
        Set-Content (Join-Path $m.repo 'standards\style.md') 'a'
        $given = Join-Path $TestDrive 'r\x\..\Dotted'
        @((Get-StandardsResult $given).files) -join ',' | Should Be 'standards\style.md'
    }

    It 'copies the template into a new repo, folders kept, and commits it' {
        $m = New-Repo 'Fresh' $template
        (@((Get-StandardsResult $m.repo).files)) -join ',' | Should Be 'standards\style.md,standards\sub\skeleton.md'
        (git -C $m.repo status --short) | Should BeNullOrEmpty
        (git -C $m.repo ls-files standards) -join ',' | Should Be 'standards/style.md,standards/sub/skeleton.md'
    }

    It 'never copies it over a file, nor into a repo that exists' {
        $m = New-Repo 'Older'
        Set-Content (Join-Path $template 'late.md') 'late'
        $again = New-Repo 'Older' $template
        Test-Path (Join-Path $again.repo 'standards\style.md') | Should Be $false
        $standards = Join-Path $TestDrive 'standing'
        New-Item -ItemType Directory -Force -Path $standards | Out-Null
        Set-Content (Join-Path $standards 'style.md') 'theirs'
        Copy-StandardsTemplate $template $standards | Should BeNullOrEmpty
        (Get-Content (Join-Path $standards 'style.md')) | Should Be 'theirs'
        Test-Path (Join-Path $standards 'sub\skeleton.md') | Should Be $true
    }

    It 'gives an existing repo the empty folder on the next session' {
        $m = New-Repo 'Existing'
        Remove-Item (Join-Path $m.repo 'standards') -Recurse -Force
        $again = New-Repo 'Existing'
        Test-Path (Join-Path $again.repo 'standards') -PathType Container | Should Be $true
    }

    It 'says so when the template is no folder, and goes on' {
        $m = New-Repo 'Missing' (Join-Path $TestDrive 'nothing')
        $m.standardsNote | Should Match 'no folder'
        Test-Path (Join-Path $m.repo '.git') | Should Be $true
    }

    It 'a plain export folder has none' {
        $m = New-Repo 'Plain' $template -Plain
        Test-Path (Join-Path $m.repo 'standards') | Should Be $false
    }
}

Describe 'Initialize-ProjectRepo' {
    $root = Join-Path $TestDrive 'TIA-Projects'

    It 'creates the skeleton, tiabridge.json, the docs bundle stubs and an initial commit for a new project' {
        $r = Initialize-ProjectRepo -Root $root -ProjectName 'TiaBridgeTest' -ProjectPath 'C:\P\TiaBridgeTest\TiaBridgeTest.ap20' -PlcDevices @('PLC_1') -HmiDevices @('HMI_1')
        $r.created | Should Be $true
        $r.repo | Should Be (Join-Path $root 'TiaBridgeTest')
        foreach ($d in 'plc', 'hmi', 'library', 'gen', 'logs', 'archives') { Test-Path (Join-Path $r.repo $d) | Should Be $true }
        $cfg = Get-Content (Join-Path $r.repo 'tiabridge.json') -Raw | ConvertFrom-Json
        $cfg.projectPath | Should Be 'C:\P\TiaBridgeTest\TiaBridgeTest.ap20'
        $cfg.plcDevices[0] | Should Be 'PLC_1'
        $cfg.hmiDevices[0] | Should Be 'HMI_1'
        $project = Get-Content (Join-Path $r.repo 'docs\project.md') -Raw
        $project | Should Match '^---\ntype: Project\ntitle: "TiaBridgeTest"\n'
        $project | Should Match 'generated: \{ by: process:tiabridge, at: \d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}[+-]\d{2}:\d{2} \}'
        (Get-Content (Join-Path $r.repo 'docs\index.md') -Raw) | Should Match '^---\nokf_version: "0.2"\n---'
        (Get-Content (Join-Path $r.repo 'docs\log.md') -Raw) | Should Match '## \d{4}-\d{2}-\d{2}\n\* \*\*Initialization\*\*'
        (Get-Content (Join-Path $r.repo '.gitignore') -Raw) | Should Match 'archives/[\s\S]*changes/reports/'
        (& git -C $r.repo log --oneline | Measure-Object).Count | Should Be 1
        (& git -C $r.repo status --porcelain) | Should BeNullOrEmpty
    }

    It 'reuses an existing repo and leaves docs\project.md alone' {
        Set-Content (Join-Path $root 'TiaBridgeTest\docs\project.md') 'my notes'
        $r = Initialize-ProjectRepo -Root $root -ProjectName 'TiaBridgeTest' -ProjectPath 'C:\P\TiaBridgeTest\TiaBridgeTest.ap20' -PlcDevices @('PLC_1') -HmiDevices @('HMI_1')
        $r.created | Should Be $false
        $r.pathChanged | Should Be $false
        (Get-Content (Join-Path $r.repo 'docs\project.md') -Raw).Trim() | Should Be 'my notes'
    }

    It 'updates the recorded project path when the project was moved, and says so' {
        $r = Initialize-ProjectRepo -Root $root -ProjectName 'TiaBridgeTest' -ProjectPath 'D:\Copy\TiaBridgeTest.ap20' -PlcDevices @() -HmiDevices @() -Moved
        $r.pathChanged | Should Be $true
        $r.oldPath | Should Be 'C:\P\TiaBridgeTest\TiaBridgeTest.ap20'
        (Get-Content (Join-Path $r.repo 'tiabridge.json') -Raw | ConvertFrom-Json).projectPath | Should Be 'D:\Copy\TiaBridgeTest.ap20'
    }

    It 'makes a folder name from a project name with characters Windows forbids' {
        $r = Initialize-ProjectRepo -Root $root -ProjectName 'A:B*C' -ProjectPath 'C:\x.ap20' -PlcDevices @() -HmiDevices @()
        Split-Path $r.repo -Leaf | Should Be 'A_B_C'
    }

    It 'creates the repo under ErrorActionPreference Stop, as the bridge runs, although git writes warnings to stderr' {
        $ErrorActionPreference = 'Stop'
        $r = Initialize-ProjectRepo -Root $root -ProjectName 'StrictMode' -ProjectPath 'C:\s.ap20' -PlcDevices @() -HmiDevices @()
        $r.created | Should Be $true
        (& git -C $r.repo log --oneline | Measure-Object).Count | Should Be 1
    }

    It 'completes a repo whose creation stopped before the initial commit' {
        $r = Initialize-ProjectRepo -Root $root -ProjectName 'HalfDone' -ProjectPath 'C:\h.ap20' -PlcDevices @() -HmiDevices @()
        Remove-Item -Recurse -Force (Join-Path $r.repo '.git')
        & git -C $r.repo init -q
        $r = Initialize-ProjectRepo -Root $root -ProjectName 'HalfDone' -ProjectPath 'C:\h.ap20' -PlcDevices @() -HmiDevices @()
        $r.created | Should Be $true
        (& git -C $r.repo log --oneline | Measure-Object).Count | Should Be 1
        (& git -C $r.repo status --porcelain) | Should BeNullOrEmpty
    }

    It 'escapes a project name for the YAML header and keeps it as written in the index' {
        $r = Initialize-ProjectRepo -Root $root -ProjectName 'Line "B" \ 2' -ProjectPath 'C:\y.ap20' -PlcDevices @() -HmiDevices @()
        (Get-Content (Join-Path $r.repo 'docs\project.md') -Raw) | Should Match ([regex]::Escape('title: "Line \"B\" \\ 2"'))
        (Get-Content (Join-Path $r.repo 'docs\index.md') -Raw) | Should Match ([regex]::Escape('* [Line "B" \ 2](project.md) - Notes for agents working on the TIA project Line "B" \ 2,'))
    }
}

Describe 'Resolve-RepoFolder' {
    It 'gives the folder below the root for a plain folder name' {
        $r = Resolve-RepoFolder 'C:\TIA-Projects' 'cache-1.v2'
        $r.path | Should Be 'C:\TIA-Projects\cache-1.v2'
        $r.refused | Should BeNullOrEmpty
    }

    foreach ($name in '', ' ', '.', '..', '...', 'a\..\..', '..\x', 'a/b', 'C:\x', 'C:x', 'x.', 'x ', 'x. ', 'a*b', 'a?b', 'a|b') {
        It "refuses '$name' as not a plain folder name" {
            $r = Resolve-RepoFolder 'C:\TIA-Projects' $name
            $r.refused | Should Match 'plain folder name'
            $r.path | Should BeNullOrEmpty
        }
    }

    foreach ($name in 'NUL', 'nul', 'CON', 'COM1', 'LPT9', 'aux.txt') {
        It "refuses the Windows device name '$name'" {
            (Resolve-RepoFolder 'C:\TIA-Projects' $name).refused | Should Match 'device name'
        }
    }

    It 'refuses the folder of the bridge itself, in any case' {
        (Resolve-RepoFolder 'C:\TIA-Projects' '_bridge').refused | Should Match "bridge's own folder"
        (Resolve-RepoFolder 'C:\TIA-Projects' '_BRIDGE').refused | Should Match "bridge's own folder"
    }
}

Describe 'Initialize-ProjectRepo: the repo folder' {
    # below the test drive: when a guard fails, the repo lands in the parent folder of the test, nowhere else
    $parent = Join-Path $TestDrive 'guard'
    $root = Join-Path $parent 'projects'
    New-Item -ItemType Directory -Force -Path $root | Out-Null

    foreach ($name in '.', '..', 'a\..\..', 'x.') {
        foreach ($plain in $false, $true) {
            It "refuses RepoName '$name' (plain $plain) and writes nothing" {
                { Initialize-ProjectRepo -Root $root -ProjectName 'P' -ProjectPath 'C:\P.ap20' -PlcDevices @() -HmiDevices @() -RepoName $name -Plain:$plain } | Should Throw 'plain folder name'
                @(Get-ChildItem -LiteralPath $parent -Force | ForEach-Object Name) -join ',' | Should Be 'projects'
                @(Get-ChildItem -LiteralPath $root -Force).Count | Should Be 0
            }
        }
    }

    It 'uses the folder Windows makes of a project name that ends in a dot' {
        $r = Initialize-ProjectRepo -Root $root -ProjectName 'Line 1.' -ProjectPath 'C:\y.ap20' -PlcDevices @() -HmiDevices @() -BackgroundSource 'C:\y.ap20'
        $r.repo | Should Be (Join-Path $root 'Line 1')
        Remove-Item -LiteralPath $r.repo -Recurse -Force
    }

    foreach ($name in '.', '..') {
        It "refuses the project name '$name' as the repo folder" {
            { Initialize-ProjectRepo -Root $root -ProjectName $name -ProjectPath 'C:\y.ap20' -PlcDevices @() -HmiDevices @() } | Should Throw 'plain folder name'
            @(Get-ChildItem -LiteralPath $root -Force).Count | Should Be 0
        }
    }
}

Describe 'git missing from PATH' {
    It 'says so instead of taking the missing command for success' {
        $saved = $env:PATH
        try {
            $env:PATH = "$env:SystemRoot\System32"
            Get-GitProblem | Should Match '^git not found on PATH\. Install Git for Windows'
            { Invoke-GitRaw $TestDrive @('status') } | Should Throw 'git not found on PATH'
            { Test-GitHasCommit $TestDrive } | Should Not Throw   # no .git: git is not called
        } finally { $env:PATH = $saved }
        Get-GitProblem | Should BeNullOrEmpty
    }
}

Describe 'python check (change_report, HMI import validator)' {
    It 'reads the probe: version, missing modules' {
        Get-PythonProbeProblem 0 "3.13.3`r`n`r`n" '' | Should BeNullOrEmpty
        Get-PythonProbeProblem 0 "3.12.0`r`n" '' | Should BeNullOrEmpty
        Get-PythonProbeProblem 0 "3.13.3`r`nyaml`r`n" '' | Should Be 'python 3.13.3 lacks PyYAML.'
        Get-PythonProbeProblem 0 "3.11.9`r`n`r`n" '' | Should Be 'python is 3.11.9; the tools need 3.12 or later.'
        Get-PythonProbeProblem 1 "2.7.18`r`n" 'ImportError: No module named util' | Should Match 'is 2\.7\.18; the tools need 3\.12'
        Get-PythonProbeProblem 1 '' 'boom' | Should Match 'did not run the check \(exit 1\): boom'
    }

    It 'runs the .venv of the tool repo by absolute path' {
        $root = [System.IO.Path]::GetFullPath((Join-Path $PSScriptRoot '..\..'))
        $script:PythonExe | Should Be (Join-Path $root '.venv\Scripts\python.exe')
    }

    It 'says run uv sync when the .venv is missing, also with a python on PATH' {
        $saved = $script:PythonExe
        try {
            $script:PythonExe = Join-Path $TestDrive 'no-venv\python.exe'
            $script:PythonReady = @{}
            $p = Get-PythonProblem @('yaml')
        } finally { $script:PythonExe = $saved; $script:PythonReady = @{} }
        $p | Should Match 'no-venv\\python\.exe not found\. Setup: run uv sync in '
    }

    It 'runs the probe with the python of the .venv' {
        $script:PythonReady = @{}
        Get-PythonProblem | Should BeNullOrEmpty
        Get-PythonProblem @('no_such_module_tiabridge') | Should Match 'lacks no_such_module_tiabridge\. Setup:'
        $script:PythonReady.ContainsKey('no_such_module_tiabridge') | Should Be $false
    }
}

Describe 'Merge-HmiTypeIdentifier' {
    It 'returns the identifier as a string for one HMI device' {
        $r = Merge-HmiTypeIdentifier -Old $null -OldDevices @() -Devices @('HMI_1') -Read @{ HMI_1 = 'OrderNumber:6AV2 124-0MC01-0AX0/17.0.0.0' }
        $r | Should Be 'OrderNumber:6AV2 124-0MC01-0AX0/17.0.0.0'
    }

    It 'keeps the identifier of the last connect for one device that could not be read' {
        $r = Merge-HmiTypeIdentifier -Old 'OrderNumber:old' -OldDevices @('HMI_1') -Devices @('HMI_1') -Read @{}
        $r | Should Be 'OrderNumber:old'
    }

    It 'returns a map device -> identifier for several HMI devices' {
        $r = Merge-HmiTypeIdentifier -Old $null -OldDevices @() -Devices @('HMI_1', 'HMI_2') -Read @{ HMI_1 = 'OrderNumber:a'; HMI_2 = 'OrderNumber:b' }
        $r['HMI_1'] | Should Be 'OrderNumber:a'
        $r['HMI_2'] | Should Be 'OrderNumber:b'
    }
}

Describe 'Initialize-ProjectRepo with several HMI devices' {
    $root = Join-Path $TestDrive 'TIA-Projects'

    It 'writes hmiTypeIdentifier as a map and keeps the hmiDevice key the user set' {
        $r = Initialize-ProjectRepo -Root $root -ProjectName 'TwoPanels' -ProjectPath 'C:\t.ap20' -PlcDevices @() -HmiDevices @('HMI_1', 'HMI_2') `
            -HmiTypeIdentifiers @{ HMI_1 = 'OrderNumber:a'; HMI_2 = 'OrderNumber:b' }
        $cfgPath = Join-Path $r.repo 'tiabridge.json'
        $cfg = Get-Content $cfgPath -Raw | ConvertFrom-Json
        $cfg.hmiTypeIdentifier.HMI_2 | Should Be 'OrderNumber:b'
        $cfg | Add-Member -NotePropertyName hmiDevice -NotePropertyValue 'HMI_2'
        Set-Content $cfgPath (ConvertTo-Json $cfg -Depth 5)
        $r = Initialize-ProjectRepo -Root $root -ProjectName 'TwoPanels' -ProjectPath 'C:\t.ap20' -PlcDevices @() -HmiDevices @('HMI_1', 'HMI_2')
        $cfg = Get-Content $cfgPath -Raw | ConvertFrom-Json
        $cfg.hmiDevice | Should Be 'HMI_2'
        $cfg.hmiTypeIdentifier.HMI_1 | Should Be 'OrderNumber:a'
    }
}

Describe 'Get-BridgeSettings' {
    It 'falls back to the defaults without a settings file' {
        $s = Get-BridgeSettings (Join-Path $TestDrive 'none.json')
        $s.projectsRoot | Should Be (Join-Path $env:USERPROFILE 'TIA-Projects')
        $s.tiaRoot | Should Be 'C:\Program Files\Siemens\Automation\Portal V20'
        $s.archivesKept | Should Be 10
    }

    It 'takes values from the settings file and keeps defaults for the rest' {
        $f = Join-Path $TestDrive 'settings.json'
        Set-Content $f '{ "archivesKept": 3 }'
        $s = Get-BridgeSettings $f
        $s.archivesKept | Should Be 3
        $s.tiaRoot | Should Be 'C:\Program Files\Siemens\Automation\Portal V20'
    }
}

Describe 'Write-ToolLog' {
    It 'writes the full result to logs\<timestamp>_<tool>.json and returns the relative path' {
        $repo = Join-Path $TestDrive 'logrepo'
        $at = [datetime]'2026-10-04 10:15:00'
        $rel = Write-ToolLog -Repo $repo -Tool 'import' -Result @{ ok = $true; items = @(@{ name = 'A' }) } -At $at
        $rel | Should Be 'logs\20261004_101500_import.json'
        (Get-Content (Join-Path $repo $rel) -Raw | ConvertFrom-Json).items[0].name | Should Be 'A'
    }

    It 'does not overwrite a log of the same tool in the same second' {
        $repo = Join-Path $TestDrive 'logrepo2'
        $at = [datetime]'2026-10-04 10:15:00'
        $a = Write-ToolLog -Repo $repo -Tool 'export' -Result @{ ok = $true } -At $at
        $b = Write-ToolLog -Repo $repo -Tool 'export' -Result @{ ok = $false } -At $at
        $b | Should Not Be $a
    }
}

Describe 'Remove-OldArchives' {
    It 'keeps the newest N archives by name' {
        $dir = Join-Path $TestDrive 'archives'
        New-Item -ItemType Directory $dir | Out-Null
        foreach ($n in '20261001_080000_a', '20261002_080000_b', '20261003_080000_c', '20261004_080000_d') { Set-Content (Join-Path $dir "$n.zap20") 'x' }
        $removed = Remove-OldArchives -Dir $dir -Keep 2
        @($removed).Count | Should Be 2
        (Get-ChildItem $dir -Filter *.zap20 | ForEach-Object BaseName) -join ',' | Should Be '20261003_080000_c,20261004_080000_d'
    }

    It 'keeps the newest archive whatever the setting says: the session gate counts it' {
        foreach ($keep in 0, -3) {
            $dir = Join-Path $TestDrive "archives-keep$($keep + 10)"
            New-Item -ItemType Directory $dir | Out-Null
            foreach ($n in '20261001_080000_a', '20261002_080000_b') { Set-Content (Join-Path $dir "$n.zap20") 'x' }
            @(Remove-OldArchives -Dir $dir -Keep $keep).Count | Should Be 1
            (Get-ChildItem $dir -Filter *.zap20 | ForEach-Object BaseName) -join ',' | Should Be '20261002_080000_b'
        }
    }

    It 'orders old and new names by their time and leaves files without one alone' {
        $dir = Join-Path $TestDrive 'archives2'
        New-Item -ItemType Directory $dir | Out-Null
        foreach ($n in '20261005_080000_session', 'tia-co-op-PlantA-Line-Area-00001-2026-10-06_093214',
            'tia-co-op-PlantA-Line-Area-00001-2026-10-06_120000-before_refactor', 'handmade') { Set-Content (Join-Path $dir "$n.zap20") 'x' }
        $removed = Remove-OldArchives -Dir $dir -Keep 2
        @($removed | ForEach-Object { Split-Path $_ -Leaf }) -join ',' | Should Be '20261005_080000_session.zap20'
        Test-Path (Join-Path $dir 'handmade.zap20') | Should Be $true
    }

    It 'rotates archives of the former prefix tia-coop- and of tia-co-op- as one set, by their time' {
        $dir = Join-Path $TestDrive 'archives3'
        New-Item -ItemType Directory $dir | Out-Null
        foreach ($n in 'tia-coop-P-2026-10-06_093214', 'tia-co-op-P-2026-10-07_093214', 'tia-coop-P-2026-10-08_093214-before_refactor',
            'tia-co-op-P-2026-10-09_093214') { Set-Content (Join-Path $dir "$n.zap20") 'x' }
        $removed = Remove-OldArchives -Dir $dir -Keep 2
        @($removed | ForEach-Object { Split-Path $_ -Leaf }) -join ',' | Should Be 'tia-co-op-P-2026-10-07_093214.zap20,tia-coop-P-2026-10-06_093214.zap20'
        Test-Path (Join-Path $dir 'tia-coop-P-2026-10-08_093214-before_refactor.zap20') | Should Be $true
        Test-Path (Join-Path $dir 'tia-co-op-P-2026-10-09_093214.zap20') | Should Be $true
    }
}

Describe 'Resolve-ImportFiles' {
    $repo = Join-Path $TestDrive 'R'
    foreach ($f in 'plc\blocks\Motion\Axes\DriveVerticalAxis.s7dcl', 'plc\blocks\Motion\Axes\DriveVerticalAxis.s7res', 'plc\blocks\Main.xml', 'hmi\screens\5000 - Unit screens\G05\5051 - G05 Op.xml') {
        Write-TextFile (Join-Path $repo $f) 'x'
    }

    It 'takes paths relative to the repo, treats an .s7dcl/.s7res pair as one item, and infers the TIA folder from the repo tree' {
        $set = @(Resolve-ImportFiles -Repo $repo -KindDir 'plc\blocks' -Paths @('plc\blocks\Motion\Axes\DriveVerticalAxis.s7dcl', 'plc\blocks\Motion\Axes\DriveVerticalAxis.s7res', 'plc\blocks\Main.xml'))
        $set.Count | Should Be 2
        $set[0].name | Should Be 'DriveVerticalAxis'
        $set[0].format | Should Be 's7dcl'
        $set[0].folder | Should Be 'Motion/Axes'
        $set[1].format | Should Be 'xml'
        $set[1].folder | Should Be ''
    }

    It 'accepts an absolute path and a lone .s7res as its pair' {
        $abs = Join-Path $repo 'plc\blocks\Motion\Axes\DriveVerticalAxis.s7res'
        $set = @(Resolve-ImportFiles -Repo $repo -KindDir 'plc\blocks' -Paths @($abs))
        $set[0].format | Should Be 's7dcl'
        $set[0].file | Should Be (Join-Path $repo 'plc\blocks\Motion\Axes\DriveVerticalAxis.s7dcl')
    }

    It 'gives no folder for a file outside the kind directory, and reports a missing file' {
        $set = @(Resolve-ImportFiles -Repo $repo -KindDir 'plc\types' -Paths @('plc\blocks\Main.xml', 'plc\blocks\Nope.xml'))
        $set[0].folder | Should Be ''
        $set[1].missing | Should Be $true
    }

    It 'keeps spaces in HMI folder names' {
        $set = @(Resolve-ImportFiles -Repo $repo -KindDir 'hmi\screens' -Paths @('hmi\screens\5000 - Unit screens\G05\5051 - G05 Op.xml'))
        $set[0].folder | Should Be '5000 - Unit screens/G05'
        $set[0].name | Should Be '5051 - G05 Op'
    }
}

Describe 'Repair-DocumentLineEnds' {
    $bom = [byte[]](0xEF, 0xBB, 0xBF)
    function Write-Doc([string]$Name, [string]$Text) {
        $path = Join-Path $TestDrive $Name
        [System.IO.File]::WriteAllBytes($path, $bom + [System.Text.Encoding]::UTF8.GetBytes($Text))
        $path
    }
    function Read-Doc([string]$Path) { [System.Text.Encoding]::UTF8.GetString([System.IO.File]::ReadAllBytes($Path)) }

    It 'writes a file with LF as CRLF, says so, and changes nothing else' {
        $text = "NETWORK`n        #r := 1; // d$([char]0xFC)nn`n              (* comment at 14`n`t tab`n*)`n"
        $path = Write-Doc 'lf.s7dcl' $text
        Repair-DocumentLineEnds $path | Should Match 'CRLF'
        $bytes = [System.IO.File]::ReadAllBytes($path)
        ($bytes[0..2] -join ',') | Should Be '239,187,191'
        Read-Doc $path | Should Be ([string][char]0xFEFF + ($text -replace "`n", "`r`n"))
    }

    It 'leaves a CRLF file alone: no write, no note' {
        $path = Write-Doc 'crlf.s7dcl' "NETWORK`r`n        #r := 1;`r`n"
        $old = (Get-Date).AddDays(-1)
        [System.IO.File]::SetLastWriteTime($path, $old)
        Repair-DocumentLineEnds $path | Should BeNullOrEmpty
        [System.IO.File]::GetLastWriteTime($path) | Should Be $old
    }

    It 'adds the CR only where it is missing in a file with both' {
        $path = Write-Doc 'mixed.s7dcl' "a`r`nb`nc`r`nd`n"
        Repair-DocumentLineEnds $path | Should Not BeNullOrEmpty
        Read-Doc $path | Should Be ([string][char]0xFEFF + "a`r`nb`r`nc`r`nd`r`n")
    }

    It 'does not touch a file in UTF-16, where a byte is not a character' {
        $path = Join-Path $TestDrive 'utf16.s7dcl'
        [System.IO.File]::WriteAllText($path, "a`nb`n", [System.Text.Encoding]::Unicode)
        $before = [System.IO.File]::ReadAllBytes($path) -join ','
        Repair-DocumentLineEnds $path | Should BeNullOrEmpty
        [System.IO.File]::ReadAllBytes($path) -join ',' | Should Be $before
    }
}

Describe 'git in a repo, with the git context of a parent inherited' {
    $a = Join-Path $TestDrive 'context\A'
    $b = Join-Path $TestDrive 'context\B'
    foreach ($r in @($a, 'in A'), @($b, 'in B')) {
        New-Item -ItemType Directory -Force -Path $r[0] | Out-Null
        & git -C $r[0] init -q
        Set-Content -LiteralPath (Join-Path $r[0] 'kept.txt') -Value $r[1]
        & git -C $r[0] add -A
        & git -C $r[0] -c user.name=t -c user.email=t@t -c commit.gpgsign=false commit -q -m $r[1]
    }
    function Set-ParentContext {
        $env:GIT_DIR = Join-Path $a '.git'
        $env:GIT_WORK_TREE = $a
        $env:GIT_INDEX_FILE = Join-Path $a '.git\index'
    }
    function Clear-ParentContext { foreach ($n in 'GIT_DIR', 'GIT_WORK_TREE', 'GIT_INDEX_FILE') { Remove-Item "Env:$n" -ErrorAction SilentlyContinue } }

    It 'clears every name git reads a repo from' {
        $names = @(& git rev-parse --local-env-vars)
        $names -contains 'GIT_DIR' | Should Be $true
        @($names | Where-Object { (Get-GitContextNames) -notcontains $_ }).Count | Should Be 0
    }

    It 'reads the repo asked for' {
        try {
            Set-ParentContext
            (Invoke-GitRaw $b @('log', '-1', '--format=%s')).output | Should Be 'in B'
        } finally { Clear-ParentContext }
    }

    It 'writes to the repo asked for and leaves the parent as it was' {
        $index = Join-Path $a '.git\index'
        $indexBefore = [Convert]::ToBase64String([System.IO.File]::ReadAllBytes($index))
        $headBefore = & git -C $a rev-parse HEAD
        Set-Content -LiteralPath (Join-Path $b 'new.txt') -Value 'new'
        try {
            Set-ParentContext
            Invoke-Git $b @('add', '-A')
            Invoke-Git $b @('-c', 'user.name=t', '-c', 'user.email=t@t', '-c', 'commit.gpgsign=false', 'commit', '-q', '-m', 'second in B')
        } finally { Clear-ParentContext }
        & git -C $b log -1 --format=%s | Should Be 'second in B'
        & git -C $a rev-parse HEAD | Should Be $headBefore
        [Convert]::ToBase64String([System.IO.File]::ReadAllBytes($index)) | Should Be $indexBefore
    }

    It 'keeps the rest of the environment' {
        try {
            Set-ParentContext
            # as on a machine with no git identity of its own (a CI runner): git var refuses an author without an email
            $env:GIT_CONFIG_GLOBAL = 'NUL'
            $env:GIT_CONFIG_NOSYSTEM = '1'
            $env:GIT_AUTHOR_NAME = 'Somebody Else'
            $env:GIT_AUTHOR_EMAIL = 'else@example.invalid'
            (Invoke-GitRaw $b @('var', 'GIT_AUTHOR_IDENT')).output | Should Match 'Somebody Else'
        } finally {
            Clear-ParentContext
            Remove-Item Env:GIT_CONFIG_GLOBAL, Env:GIT_CONFIG_NOSYSTEM, Env:GIT_AUTHOR_NAME, Env:GIT_AUTHOR_EMAIL -ErrorAction SilentlyContinue
        }
    }
}

Describe 'an export that differs only in the export time keeps the file in the repo' {
    . (Join-Path $here 'Fixtures\ExportFiles.ps1')
    $d = Join-Path $TestDrive 'times'
    # one file name in two folders: a .dat names the file it holds after itself
    function Test-ExportPair([string]$Ext, [scriptblock]$Write) { $a = Join-Path $d "new\f$Ext"; $b = Join-Path $d "old\f$Ext"; & $Write $a 0; & $Write $b 1; Test-OnlyExportTimeDiffers $a $b }

    It 'SimaticML: only its Created in DocumentInfo' {
        Test-ExportPair '.xml' { param($p) Write-TestText $p (Get-SimaticMlText) -Bom } | Should Be $true
        Test-ExportPair '.xml' { param($p, $i) Write-TestText $p (Get-SimaticMlText "<SW.Blocks.OB ID=`"$i`" />") -Bom } | Should Be $false
        # a Created outside the head is content, and a BOM is a byte like any other
        Test-ExportPair '.xml' { param($p) Write-TestText $p (Get-SimaticMlText "<Created>$(New-ExportTime)</Created>" '2026-11-05T22:50:53.3412301Z') -Bom } | Should Be $false
        Test-ExportPair '.xml' { param($p, $i) Write-TestText $p (Get-SimaticMlText '<x />' '2026-11-05T22:50:53.3412301Z') -Bom:($i -eq 0) } | Should Be $false
    }

    It 'settings XML: only the CreationDate on its root' {
        Test-ExportPair '.xml' { param($p) Write-TestText $p (Get-SettingsText) } | Should Be $true
        Test-ExportPair '.xml' { param($p, $i) Write-TestText $p (Get-SettingsText "Class$i") } | Should Be $false
        Test-ExportPair '.xml' { param($p) Write-TestText $p "<?xml version=`"1.0`"?>`r`n<R>`r`n  <C CreationDate=`"$((New-ExportTime))`" />`r`n</R>" } | Should Be $false
    }

    It '.dat: the root CreationDate of the XML it holds, and its zip entry time' {
        Test-ExportPair '.dat' { param($p) Write-SettingsDat $p } | Should Be $true
        Test-ExportPair '.dat' { param($p, $i) Write-SettingsDat $p "Class$i" } | Should Be $false
        Test-ExportPair '.dat' { param($p, $i) Write-TestZip $p ([ordered]@{ "n$i.dat" = (Get-SettingsText) }) } | Should Be $false
    }

    It '.xlsx: its zip entry times and the Ids of its relationships, not where they point' {
        Test-ExportPair '.xlsx' { param($p) Write-TestXlsx $p } | Should Be $true
        Test-ExportPair '.xlsx' { param($p, $i) Write-TestXlsx $p "cell$i" } | Should Be $false
        Test-ExportPair '.xlsx' { param($p, $i) Write-TestXlsx $p -Swap:($i -eq 0) } | Should Be $false
        Test-ExportPair '.xlsx' { param($p, $i) $x = Get-XlsxParts; if ($i) { $x.Remove('xl/styles.xml') }; Write-TestZip $p $x } | Should Be $false
    }

    It 'any other file only when equal; a file that does not read or is missing differs' {
        Test-ExportPair '.s7dcl' { param($p) Write-TestText $p 'FUNCTION "A" : Void' } | Should Be $true
        Test-ExportPair '.s7dcl' { param($p, $i) Write-TestText $p "FUNCTION `"A$i`" : Void" } | Should Be $false
        Test-ExportPair '.xlsx' { param($p, $i) Write-TestText $p "no zip $i" } | Should Be $false
        Test-OnlyExportTimeDiffers (Join-Path $d 'new\f.xlsx') (Join-Path $d 'old\missing.xlsx') | Should Be $false
    }

    It 'Move-ExportIntoPlace keeps the old file then, and takes a changed one' {
        $f = Join-Path $d 'Main.xml'
        Write-TestText $f (Get-SimaticMlText) -Bom
        $before = [System.IO.File]::ReadAllBytes($f)
        $p = New-ExportWorkPath $f; Write-TestText $p (Get-SimaticMlText) -Bom
        Move-ExportIntoPlace $p $f
        [System.IO.File]::ReadAllBytes($f) -join ',' | Should Be ($before -join ',')
        Test-Path -LiteralPath $p | Should Be $false
        $p = New-ExportWorkPath $f; Write-TestText $p (Get-SimaticMlText '<SW.Blocks.OB ID="9" />') -Bom
        Move-ExportIntoPlace $p $f
        Get-Content -LiteralPath $f -Raw | Should Match 'ID="9"'
    }

    It 'Move-ExportIntoPlace of a folder keeps each such file, takes the others and the new ones' {
        $dest = Join-Path $d 'texts'
        Write-TestXlsx (Join-Path $dest 'same.xlsx'); Write-TestXlsx (Join-Path $dest 'sub\changed.xlsx') 'old'
        $same = [System.IO.File]::ReadAllBytes((Join-Path $dest 'same.xlsx'))
        $p = New-ExportWorkPath $dest
        Write-TestXlsx (Join-Path $p 'same.xlsx'); Write-TestXlsx (Join-Path $p 'sub\changed.xlsx') 'new'; Write-TestText (Join-Path $p 'added.txt') 'x'
        $changed = [System.IO.File]::ReadAllBytes((Join-Path $p 'sub\changed.xlsx'))
        Move-ExportIntoPlace $p $dest
        [System.IO.File]::ReadAllBytes((Join-Path $dest 'same.xlsx')) -join ',' | Should Be ($same -join ',')
        [System.IO.File]::ReadAllBytes((Join-Path $dest 'sub\changed.xlsx')) -join ',' | Should Be ($changed -join ',')
        Test-Path (Join-Path $dest 'added.txt') | Should Be $true
    }
}
