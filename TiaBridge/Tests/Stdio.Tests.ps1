$here = Split-Path -Parent $MyInvocation.MyCommand.Path
$bridge = Join-Path $here '..\TiaBridge.ps1'
$toolScript = Join-Path $here 'Fixtures\TestTools.ps1'
. (Join-Path $here '..\Repo.ps1')
. (Join-Path $here '..\Tia.ps1')

# Starts the bridge as Claude Code does (powershell.exe -STA, pipes), sends the lines as UTF-8, returns stdout lines.
function Invoke-BridgeProcess([string[]]$Lines, [string]$BridgeArgs) {
    $psi = New-Object System.Diagnostics.ProcessStartInfo
    $psi.FileName = "$env:SystemRoot\System32\WindowsPowerShell\v1.0\powershell.exe"
    $psi.Arguments = "-NoProfile -STA -ExecutionPolicy Bypass -File `"$bridge`" $BridgeArgs"
    $psi.UseShellExecute = $false
    $psi.RedirectStandardInput = $true
    $psi.RedirectStandardOutput = $true
    $psi.RedirectStandardError = $true
    $psi.StandardOutputEncoding = New-Object System.Text.UTF8Encoding $false
    $p = [System.Diagnostics.Process]::Start($psi)
    $errTask = $p.StandardError.ReadToEndAsync()
    $bytes = (New-Object System.Text.UTF8Encoding $false).GetBytes(($Lines -join "`n") + "`n")
    $p.StandardInput.BaseStream.Write($bytes, 0, $bytes.Length)
    $p.StandardInput.Close()
    $out = $p.StandardOutput.ReadToEnd()
    if (-not $p.WaitForExit(60000)) { $p.Kill(); throw 'bridge did not exit' }
    $script:LastStderr = $errTask.Result
    @($out -split "`n" | Where-Object { $_.Trim() })
}

Describe 'TiaBridge.ps1 over stdio' {
    $settings = Join-Path $TestDrive "settings.json"
    Set-Content $settings (ConvertTo-Json @{ projectsRoot = (Join-Path $TestDrive "p"); maxResponseChars = 1000000 })
    $umlauts = "Gr$([char]0xF6)$([char]0xDF)e $([char]0xC4)$([char]0x20AC)"
    $long = 'x' * 200000
    $lines = @(
        '{"jsonrpc":"2.0","id":1,"method":"initialize","params":{"protocolVersion":"2025-06-18","capabilities":{},"clientInfo":{"name":"t","version":"1"}}}'
        '{"jsonrpc":"2.0","method":"notifications/initialized"}'
        ('{"jsonrpc":"2.0","id":2,"method":"tools/call","params":{"name":"echo","arguments":{"text":"' + $umlauts + '"}}}')
        'this is not json'
        ('{"jsonrpc":"2.0","id":3,"method":"tools/call","params":{"name":"echo","arguments":{"text":"' + $long + '"}}}')
        '{"jsonrpc":"2.0","id":4,"method":"tools/list"}'
        '{"jsonrpc":"2.0","id":5,"method":"tools/call","params":{"name":"apartment","arguments":{}}}'
    )
    $out = Invoke-BridgeProcess $lines "-ToolScript `"$toolScript`" -NoTools -SettingsPath `"$settings`""

    It 'writes exactly one response line per request and none for the notification' {
        $out.Count | Should Be 6
    }

    It 'keeps stray Write-Host and pipeline output of a tool off stdout' {
        foreach ($l in $out) { { $l | ConvertFrom-Json } | Should Not Throw }
    }

    It 'round-trips UTF-8 text' {
        $r = $out[1] | ConvertFrom-Json
        $r.id | Should Be 2
        ($r.result.content[0].text | ConvertFrom-Json).text | Should BeExactly $umlauts
    }

    It 'answers malformed input with a parse error and keeps going' {
        ($out[2] | ConvertFrom-Json).error.code | Should Be -32700
    }

    It 'handles a 200 kB message' {
        $r = $out[3] | ConvertFrom-Json
        $r.id | Should Be 3
        ($r.result.content[0].text | ConvertFrom-Json).text.Length | Should Be 200000
    }

    It 'still answers after all of that' {
        ($out[4] | ConvertFrom-Json).id | Should Be 4
    }

    # Openness queues TIA's call-backs for a session attached from an STA thread until that thread calls again, and TIA waits
    # for each: started -STA, as setup registers it, the bridge must still attach from an MTA thread
    It 'runs its tools on an MTA thread when started -STA' {
        (($out[5] | ConvertFrom-Json).result.content[0].text | ConvertFrom-Json).apartment | Should Be 'MTA'
        $script:LastStderr | Should Match 'STA: False'
    }
}

Describe 'TiaBridge.ps1 with the bridge tools, without a connected project' {
    $settings = Join-Path $TestDrive 'settings.json'
    $root = Join-Path $TestDrive 'projects'
    Set-Content $settings (ConvertTo-Json @{ projectsRoot = $root })
    $tiaRunning = @(Get-Process -Name 'Siemens.Automation.Portal' -ErrorAction SilentlyContinue).Count -gt 0
    # A PC without TIA Portal V20 (a CI runner): the tests that load Openness skip, one checks the bridge says why
    $openness = Test-Path -LiteralPath (Get-OpennessDll (Get-BridgeSettings $settings).tiaRoot)
    $out = Invoke-BridgeProcess @(
        '{"jsonrpc":"2.0","id":1,"method":"tools/list"}'
        '{"jsonrpc":"2.0","id":2,"method":"tools/call","params":{"name":"tia_status","arguments":{}}}'
        '{"jsonrpc":"2.0","id":3,"method":"tools/call","params":{"name":"list","arguments":{"kind":"block"}}}'
        '{"jsonrpc":"2.0","id":4,"method":"tools/call","params":{"name":"import","arguments":{"kind":"hmi_screen","paths":["x.xml"]}}}'
        '{"jsonrpc":"2.0","id":5,"method":"tools/call","params":{"name":"connect","arguments":{}}}'
    ) "-SettingsPath `"$settings`""
    function Get-Body($line) { ($line | ConvertFrom-Json).result.content[0].text | ConvertFrom-Json }

    It 'offers every tool' {
        $names = @(($out[0] | ConvertFrom-Json).result.tools | ForEach-Object { $_.name }) | Sort-Object
        ($names -join ',') | Should Be 'archive,background_close,background_open,change_report,compile,connect,delete,delete_folder,export,full_export,import,library_approve,library_create_type,library_discard_type,library_edit_type,library_left_behind,library_open,library_release_chain,library_release_type,library_review,library_update_usages,list,master_copy_from_project,master_copy_to_project,probe,project_close,project_open,safety_login,save,tia_status'
    }

    It 'lists the login arguments the archive compare tool looks for (TiaArchiveCompare\runner\bridge.py)' {
        $tools = @(($out[0] | ConvertFrom-Json).result.tools)
        $open = ($tools | Where-Object { $_.name -eq 'background_open' }).inputSchema.properties.PSObject.Properties.Name
        foreach ($p in 'plain', 'umc_user', 'umc_password', 'umc_global') { $open -contains $p | Should Be $true }
        ($tools | Where-Object { $_.name -eq 'safety_login' }).inputSchema.properties.PSObject.Properties.Name -contains 'password' | Should Be $true
    }

    It 'offers safety on every tool that can change F-blocks, reserved for a safety change the user asked for, and says what the login allows' {
        $tools = @(($out[0] | ConvertFrom-Json).result.tools)
        foreach ($n in 'import', 'delete', 'library_create_type', 'library_discard_type', 'library_update_usages', 'library_release_chain', 'master_copy_to_project') {
            $t = $tools | Where-Object { $_.name -eq $n }
            $t.inputSchema.properties.safety.type | Should Be 'boolean'
            $t.inputSchema.properties.safety.description | Should Match 'user asked'
            $t.description | Should Match 'F-block'
        }
        ($tools | Where-Object { $_.name -eq 'import' }).description | Should Match 'know-how protected'
        $login = ($tools | Where-Object { $_.name -eq 'safety_login' }).description
        $login | Should Match 'allows changes'
        foreach ($n in 'library_update_usages', 'library_release_chain', 'master_copy_to_project') { $login | Should Match $n }
    }

    It 'says on background_open that an export-only session refuses a repo of another path' {
        $tools = @(($out[0] | ConvertFrom-Json).result.tools)
        $d = ($tools | Where-Object { $_.name -eq 'background_open' }).description
        $d | Should Match 'records another path.*also when repo names it'
        $d | Should Match 'repo: "<name>"'
    }

    It 'says on background_open that write mode saves a project TIA marks modified on opening' {
        $tools = @(($out[0] | ConvertFrom-Json).result.tools)
        ($tools | Where-Object { $_.name -eq 'background_open' }).description | Should Match 'modified on opening.*savedBeforeArchive'
    }

    It 'does not promise a session archive for know-how protected blocks: it may have been skipped' {
        $tools = @(($out[0] | ConvertFrom-Json).result.tools)
        foreach ($t in $tools) { $t.description | Should Not Match 'only the session archive' }
    }

    It 'offers knowhow on delete, reserved for a delete the user asked for' {
        $delete = @(($out[0] | ConvertFrom-Json).result.tools) | Where-Object { $_.name -eq 'delete' }
        $delete.inputSchema.properties.knowhow.type | Should Be 'boolean'
        $delete.inputSchema.properties.knowhow.description | Should Match 'user asked'
        $delete.description | Should Match 'know-how protected'
    }

    It 'loads Openness and reports the TIA processes' -Skip:(-not $openness) {
        $b = Get-Body $out[1]
        $b.ok | Should Be $true
        $b.connected | Should Be $false
        $script:LastStderr | Should Not Match 'Exception'
    }

    It 'says on tia_status and connect that TIA Openness is missing, without TIA Portal V20' -Skip:$openness {
        foreach ($l in $out[1], $out[4]) { (Get-Body $l).error.message | Should Match '^TIA Portal V20 with TIA Openness required' }
        $script:LastStderr | Should Not Match 'Exception'
    }

    It 'refuses object tools before connect, logging the call outside any repo' {
        foreach ($l in $out[2], $out[3]) {
            $b = Get-Body $l
            $b.ok | Should Be $false
            # import is a write tool: the dispatch refuses it, the handler does not run
            "$($b.error.message)$($b.refused)" | Should Match 'call connect first'
            Test-Path $b.log | Should Be $true
        }
    }

    It 'says that no project is open when TIA is not running' -Skip:(-not $openness -or $tiaRunning) {
        (Get-Body $out[4]).error.message | Should Match 'No TIA Portal with an open project'
    }
}
