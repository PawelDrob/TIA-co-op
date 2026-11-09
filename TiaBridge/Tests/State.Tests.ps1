$here = Split-Path -Parent $MyInvocation.MyCommand.Path
foreach ($f in 'Mcp.ps1', 'Tia.ps1', 'Repo.ps1', 'Rules.ps1', 'Bridge.ps1', 'State.ps1') { . (Join-Path $here "..\$f") }

function Read-StateFile { Get-Content -LiteralPath $script:BridgeState.path -Raw | ConvertFrom-Json }

# A process id no process has.
function Get-DeadPid { $n = 999999; while (Get-Process -Id $n -ErrorAction SilentlyContinue) { $n-- }; $n }

Describe 'Get-OtherBridges' {
    $dir = Join-Path $TestDrive 'sessions'
    New-Item -ItemType Directory -Force -Path $dir | Out-Null
    # a process that runs and is not this one, to stand for another bridge
    $other = Start-Process -FilePath "$env:SystemRoot\System32\ping.exe" -ArgumentList '-n 60 127.0.0.1' -WindowStyle Hidden -PassThru
    function Write-State([int]$Id, $Tia, [string]$Started = ((Get-Date).ToString('o'))) {
        Set-Content (Join-Path $dir "$Id.json") (ConvertTo-Json @{ pid = $Id; started = $Started; project = 'P'; session = 's1'; tia = $Tia })
    }

    It 'names a live bridge on one of the TIAs' {
        Write-State $other.Id @{ pid = 4711; window = $true }
        $r = @(Get-OtherBridges $dir @(4711))
        $r.Count | Should Be 1
        $r[0].pid | Should Be $other.Id
        $r[0].tia | Should Be 4711
        $r[0].project | Should Be 'P'
        $r[0].session | Should Be 's1'
    }

    It 'leaves out another TIA, no TIA, itself, a gone bridge, a pid taken again and a file it cannot read' {
        Remove-Item (Join-Path $dir '*.json')
        Write-State $other.Id @{ pid = 1 }
        @(Get-OtherBridges $dir @(4711)).Count | Should Be 0
        Write-State $other.Id $null
        @(Get-OtherBridges $dir @(4711)).Count | Should Be 0
        Write-State $other.Id @{ pid = 4711 } '2000-01-01T00:00:00'
        @(Get-OtherBridges $dir @(4711)).Count | Should Be 0
        Write-State $other.Id @{ pid = 4711 }
        Write-State $PID @{ pid = 4711 }
        Write-State (Get-DeadPid) @{ pid = 4711 }
        @(Get-OtherBridges $dir @(4711)).Count | Should Be 1
        Set-Content (Join-Path $dir "$($other.Id).json") '{not json'
        @(Get-OtherBridges $dir @(4711)).Count | Should Be 0
    }

    It 'has nothing to say with no folder' {
        @(Get-OtherBridges (Join-Path $TestDrive 'none') @(1)).Count | Should Be 0
    }

    Stop-Process -Id $other.Id -Force -ErrorAction SilentlyContinue
}

Describe 'Get-NewerBridgeScripts' {
    It 'names scripts of the bridge and its tools changed since, and no test' {
        $dir = Join-Path $TestDrive 'b'
        foreach ($f in 'Old.ps1', 'New.ps1', 'Tools\Tool.ps1', 'Tools\OldTool.ps1', 'Tests\T.Tests.ps1') { New-Item -ItemType File -Force -Path (Join-Path $dir $f) | Out-Null }
        $since = [datetime]'2026-06-01'
        foreach ($f in 'Old.ps1', 'Tools\OldTool.ps1') { (Get-Item (Join-Path $dir $f)).LastWriteTime = $since.AddDays(-1) }
        (@(Get-NewerBridgeScripts $dir $since) | Sort-Object) -join ',' | Should Be 'New.ps1,Tools\Tool.ps1'
        @(Get-NewerBridgeScripts $dir (Get-Date).AddDays(1)).Count | Should Be 0
        # names whole also from a path with .. in it
        (@(Get-NewerBridgeScripts (Join-Path $TestDrive 'x\..\b') $since) | Sort-Object) -join ',' | Should Be 'New.ps1,Tools\Tool.ps1'
    }
}

Describe 'State file of the bridge process' {
    $root = Join-Path $TestDrive 'projects'
    $dir = Join-Path $root '_bridge\sessions'

    It 'is written at the start with this process, its Claude process and no operation' {
        Initialize-BridgeContext @{ projectsRoot = $root; maxResponseChars = 20000 }
        Start-BridgeState $root
        $script:BridgeState.path | Should Be (Join-Path $dir "$PID.json")
        $s = Read-StateFile
        $s.v | Should Be 1
        $s.pid | Should Be $PID
        $s.client | Should Be 'mcp'
        $s.claude.pid | Should BeGreaterThan 0
        $s.project | Should BeNullOrEmpty
        $s.tia | Should BeNullOrEmpty
        $s.operation | Should BeNullOrEmpty
        Stop-BridgeState
    }

    It 'takes the Claude process and the herdr tab from the environment when given' {
        $saved = @{ pid = $env:CLAUDE_PID; tab = $env:HERDR_TAB_ID; pane = $env:HERDR_PANE_ID }
        try {
            $env:CLAUDE_PID = '4242'; $env:HERDR_TAB_ID = 'w1:t9'; $env:HERDR_PANE_ID = 'w1:p9'
            Start-BridgeState $root
            $s = Read-StateFile
            $s.claude.pid | Should Be 4242
            $s.claude.from | Should Be 'env'
            $s.herdr.tab | Should Be 'w1:t9'
            $s.herdr.pane | Should Be 'w1:p9'
        }
        finally { $env:CLAUDE_PID = $saved.pid; $env:HERDR_TAB_ID = $saved.tab; $env:HERDR_PANE_ID = $saved.pane; Stop-BridgeState }
    }

    It 'shows the call that runs, its n of m, and the last call when it ended' {
        Initialize-BridgeContext @{ projectsRoot = $root; maxResponseChars = 20000 }
        Start-BridgeState $root
        $script:BridgeStateObjectMs = 0
        $script:seen = $null
        $d = Invoke-BridgeTool 'export' {
            param($a)
            Write-BridgeProgress ([ordered]@{ event = 'part'; part = 'blocks'; state = 'start' })
            Write-BridgeProgress ([ordered]@{ event = 'object'; part = 'blocks'; kind = 'block'; n = 31; of = 115; name = 'FB_Silo'; ok = $true })
            $script:seen = Read-StateFile
            @{ ok = $true }
        } (New-Object psobject)
        $d.result.ok | Should Be $true
        $script:seen.operation.name | Should Be 'export'
        $script:seen.operation.part | Should Be 'blocks'
        $script:seen.operation.n | Should Be 31
        $script:seen.operation.of | Should Be 115
        { [DateTime]$script:seen.operation.since } | Should Not Throw
        $s = Read-StateFile
        $s.operation | Should BeNullOrEmpty
        $s.lastOperation.name | Should Be 'export'
        $s.lastOperation.ok | Should Be $true
        Stop-BridgeState
    }

    It 'writes object events at most once per interval' {
        Initialize-BridgeContext @{ projectsRoot = $root; maxResponseChars = 20000 }
        Start-BridgeState $root
        $script:BridgeStateObjectMs = 60000
        $script:seen = $null
        [void](Invoke-BridgeTool 'export' {
            param($a)
            Write-BridgeProgress ([ordered]@{ event = 'object'; kind = 'block'; n = 1; of = 3; name = 'A'; ok = $true })
            $script:seen = Read-StateFile
            @{ ok = $true }
        } (New-Object psobject))
        $script:seen.operation.n | Should BeNullOrEmpty
        $script:BridgeStateObjectMs = 1000
        Stop-BridgeState
    }

    It 'names the project and the window TIA of a connect session' {
        Initialize-BridgeContext @{ projectsRoot = $root; maxResponseChars = 20000 }
        Start-BridgeState $root
        Set-BridgeProject -Name 'zzPlant' -Path 'C:\zzPlant.ap20' -Repo (Join-Path $root 'zzPlant')
        $script:Bridge.processId = 4711
        [void](Invoke-BridgeTool 'list' { param($a) @{ ok = $true } } (New-Object psobject))
        $s = Read-StateFile
        $s.project | Should Be 'zzPlant'
        $s.repo | Should Be (Join-Path $root 'zzPlant')
        { [DateTime]$s.boundSince } | Should Not Throw
        $s.tia.pid | Should Be 4711
        $s.tia.window | Should Be $true
        Stop-BridgeState
    }

    It 'names the TIA without window from the moment background_open started it' {
        Initialize-BridgeContext @{ projectsRoot = $root; maxResponseChars = 20000 }
        Start-BridgeState $root
        $script:seen = @()
        [void](Invoke-BridgeTool 'background_open' {
            param($a)
            Write-StepProgress 'start' 'start'
            Write-BridgeProgress ([ordered]@{ event = 'tia'; pid = 5150 })
            Write-StepProgress 'open' 'start' 5150 @{ upgrade = $true }
            $script:seen += Read-StateFile
            $script:Bridge.processId = 5150
            $script:Bridge.background = @{ processId = 5150 }
            @{ ok = $true }
        } (New-Object psobject))
        $script:seen[0].tia.pid | Should Be 5150
        $script:seen[0].tia.window | Should Be $false
        $script:seen[0].operation.step | Should Be 'open'
        $s = Read-StateFile
        $s.tia.pid | Should Be 5150
        $s.tia.window | Should Be $false
        $s.operation | Should BeNullOrEmpty
        Stop-BridgeState
    }

    It 'keeps the last TIA prompt of a call' {
        Initialize-BridgeContext @{ projectsRoot = $root; maxResponseChars = 20000 }
        Start-BridgeState $root
        function Get-PromptLog { [ordered]@{ kind = 'confirmation'; caption = 'Import'; text = 'Overwrite?'; detail = ''; choices = 'Yes, No'; answer = 'No' } }
        try { [void](Invoke-BridgeTool 'import' { param($a) @{ ok = $false } } (New-Object psobject)) }
        finally { Remove-Item function:Get-PromptLog }
        $s = Read-StateFile
        $s.lastPrompt.text | Should Be 'Overwrite?'
        $s.lastPrompt.answer | Should Be 'No'
        { [DateTime]$s.lastPrompt.at } | Should Not Throw
        $s.lastOperation.ok | Should Be $false
        Stop-BridgeState
    }

    It 'keeps no prompt for a call that had none' {
        Initialize-BridgeContext @{ projectsRoot = $root; maxResponseChars = 20000 }
        Start-BridgeState $root
        [void](Invoke-BridgeTool 'connect' { param($a) @{ ok = $true } } (New-Object psobject))
        Update-BridgeStatePrompt @($null)
        (Read-StateFile).lastPrompt | Should BeNullOrEmpty
        Stop-BridgeState
    }

    It 'never fails a tool call when the file cannot be written' {
        Initialize-BridgeContext @{ projectsRoot = $root; maxResponseChars = 20000 }
        Start-BridgeState $root
        $script:BridgeState.path = Join-Path $TestDrive 'missing\folder\1.json'
        $d = Invoke-BridgeTool 'list' {
            param($a)
            Write-BridgeProgress ([ordered]@{ event = 'part'; part = 'blocks'; state = 'start' })
            @{ ok = $true }
        } (New-Object psobject)
        $d.result.ok | Should Be $true
        Stop-BridgeState
    }

    It 'is removed when the bridge ends' {
        Start-BridgeState $root
        $p = $script:BridgeState.path
        Test-Path $p | Should Be $true
        Stop-BridgeState
        Test-Path $p | Should Be $false
        $script:BridgeState | Should BeNullOrEmpty
    }

    It 'deletes orphans at the start: a dead pid, or a pid that started after the file' {
        [void][IO.Directory]::CreateDirectory($dir)
        $dead = Join-Path $dir "$(Get-DeadPid).json"
        Set-Content $dead '{"v":1}'
        $child = Start-Process powershell.exe -ArgumentList '-NoProfile', '-Command', 'Start-Sleep 30' -WindowStyle Hidden -PassThru
        try {
            $live = Join-Path $dir "$($child.Id).json"
            Set-Content $live (ConvertTo-Json @{ started = (Get-Date).AddMinutes(1).ToString('o') })
            $reused = $null
            Start-BridgeState $root
            Test-Path $dead | Should Be $false
            Test-Path $live | Should Be $true
            Set-Content $live (ConvertTo-Json @{ started = '2020-01-01T00:00:00+01:00' })
            Stop-BridgeState
            Start-BridgeState $root
            Test-Path $live | Should Be $false
        }
        finally { Stop-Process -Id $child.Id -Force -ErrorAction SilentlyContinue; Stop-BridgeState }
    }

    It 'does nothing in the hooks before it is started' {
        $script:BridgeState = $null
        Initialize-BridgeContext @{ projectsRoot = $root; maxResponseChars = 20000 }
        $d = Invoke-BridgeTool 'list' { param($a) Write-BridgeProgress ([ordered]@{ event = 'part'; part = 'x'; state = 'start' }); @{ ok = $true } } (New-Object psobject)
        $d.result.ok | Should Be $true
    }
}

Describe 'State file of TiaBridge.ps1 over stdio' {
    $root = Join-Path $TestDrive 'projects'
    $settings = Join-Path $TestDrive 'settings.json'
    Set-Content $settings (ConvertTo-Json @{ projectsRoot = $root })
    $tools = Join-Path $TestDrive 'StateTools.ps1'
    # a tool script has a script scope of its own: the handler finds the file by the bridge pid
    Set-Content $tools ("Register-McpTool -Name 'state' -Description 'Returns the state file' -Schema @{ type = 'object' } -Handler { param(`$a) " +
        "`$f = Join-Path '$root\_bridge\sessions' `"`$PID.json`"; @{ ok = `$true; path = `$f; state = (Get-Content -LiteralPath `$f -Raw | ConvertFrom-Json) } }")
    $psi = New-Object System.Diagnostics.ProcessStartInfo
    $psi.FileName = "$env:SystemRoot\System32\WindowsPowerShell\v1.0\powershell.exe"
    $psi.Arguments = "-NoProfile -STA -ExecutionPolicy Bypass -File `"$(Join-Path $here '..\TiaBridge.ps1')`" -NoTools -ToolScript `"$tools`" -SettingsPath `"$settings`""
    $psi.UseShellExecute = $false
    $psi.RedirectStandardInput = $true; $psi.RedirectStandardOutput = $true; $psi.RedirectStandardError = $true
    $p = [System.Diagnostics.Process]::Start($psi)
    $errTask = $p.StandardError.ReadToEndAsync()
    $p.StandardInput.WriteLine('{"jsonrpc":"2.0","id":1,"method":"tools/call","params":{"name":"state","arguments":{}}}')
    $p.StandardInput.Flush()
    $r = ($p.StandardOutput.ReadLine() | ConvertFrom-Json).result.content[0].text | ConvertFrom-Json
    $p.StandardInput.Close()
    [void]$p.StandardOutput.ReadToEnd()
    if (-not $p.WaitForExit(60000)) { $p.Kill() }
    $stderr = $errTask.Result

    It 'keeps a file named after the bridge process while it runs, with the call that runs' {
        $r.path | Should Be (Join-Path $root "_bridge\sessions\$($p.Id).json")
        $r.state.pid | Should Be $p.Id
        $r.state.claude.pid | Should BeGreaterThan 0
        $r.state.operation.name | Should Be 'state'
    }

    It 'removes it when stdin closes' {
        Test-Path $r.path | Should Be $false
    }

    It 'writes no state file errors' {
        $stderr | Should Not Match 'State file'
    }
}
