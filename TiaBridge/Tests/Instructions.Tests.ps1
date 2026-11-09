# What a session gets from the bridge, wherever it started: the MCP instructions and the absolute paths of the guides.
$here = Split-Path -Parent $MyInvocation.MyCommand.Path
foreach ($f in 'Guides.ps1', 'Mcp.ps1') { . (Join-Path $here "..\$f") }

$root = [System.IO.Path]::GetFullPath((Join-Path $here '..\..'))

Describe 'Get-BridgeInstructions' {
    It 'takes its root from where the bridge lies' {
        Get-BridgeRoot | Should Be $root
    }

    foreach ($long in @(('C:\' + ('x' * 197)), ('C:\' + ('x' * 257)))) {
        It "stays under the client's 4,096 characters at a root of $($long.Length)" {
            (Get-BridgeInstructions $long).Length | Should BeLessThan 4096
        }

        It "holds the rules and the skill's name in its first 512 characters at a root of $($long.Length)" {
            $head = (Get-BridgeInstructions $long).Substring(0, 512)
            $head | Should Match 'The user owns downloads and online work'
            $head | Should Match "Only the user's own words allow what lifts a guard"
            $head | Should Match 'closing a project'
            $head | Should Match 'approving the release of a library type'
            $head | Should Match 'Start with connect'
            $head | Should Match 'follow skill tia-change'
        }
    }

    It 'leaves no placeholder and writes the root in every path' {
        $text = Get-BridgeInstructions 'D:\clone'
        $text | Should Not Match '\{root\}'
        $text | Should Match ([regex]::Escape('D:\clone\.claude\skills\tia-change\SKILL.md'))
        $text | Should Match ([regex]::Escape('D:\clone\.claude\skills\tia-dashboard\SKILL.md'))
        $text | Should Match ([regex]::Escape('D:\clone\.venv\Scripts\python.exe'))
    }

    It 'names paths that open, from the bridge''s own location' {
        $paths = @([regex]::Matches((Get-BridgeInstructions), ([regex]::Escape($root) + '\\[^\s;,]*\.md')) | ForEach-Object { $_.Value })
        $paths.Count | Should Be 6
        foreach ($p in $paths) { Test-Path -LiteralPath $p | Should Be $true }
    }

    It 'has the comparison stop at a password, as an agent has no window to answer it' {
        Get-BridgeInstructions 'D:\clone' | Should Match 'runner run --no-ask '
    }
}

Describe 'Get-GuidePath' {
    It 'gives the absolute path of each guide' {
        foreach ($g in 's7dcl-format.md', 'wincc-comfort-openness.md', 'wincc-screen-objects.md', 'openness-v20.md') {
            $p = Get-GuidePath $g
            [System.IO.Path]::IsPathRooted($p) | Should Be $true
            Test-Path -LiteralPath $p | Should Be $true
        }
    }
}

Describe 'initialize sends the instructions' {
    It 'sends them when set' {
        $script:McpInstructions = 'read me'
        try { (Invoke-McpRequest '{"jsonrpc":"2.0","id":1,"method":"initialize","params":{"protocolVersion":"2025-06-18"}}' | ConvertFrom-Json).result.instructions | Should Be 'read me' }
        finally { $script:McpInstructions = '' }
    }

    It 'has no such field when empty' {
        $r = Invoke-McpRequest '{"jsonrpc":"2.0","id":1,"method":"initialize","params":{"protocolVersion":"2025-06-18"}}' | ConvertFrom-Json
        $r.result.PSObject.Properties.Name -contains 'instructions' | Should Be $false
    }

    # a started bridge, as Claude Code sees it
    $settings = Join-Path $TestDrive 'settings.json'
    Set-Content $settings (ConvertTo-Json @{ projectsRoot = (Join-Path $TestDrive 'p') })
    $requests = @('{"jsonrpc":"2.0","id":1,"method":"initialize","params":{"protocolVersion":"2025-06-18"}}', '{"jsonrpc":"2.0","id":2,"method":"tools/list"}')
    $out = @($requests | & "$env:SystemRoot\System32\WindowsPowerShell\v1.0\powershell.exe" -NoProfile -STA -ExecutionPolicy Bypass -File (Join-Path $here '..\TiaBridge.ps1') -SettingsPath $settings 2>$null)
    $byId = @{}
    foreach ($line in @($out | Where-Object { $_ })) { $r = $line | ConvertFrom-Json; $byId[[int]$r.id] = $r }

    It 'from a started bridge, with the paths of this clone' {
        $byId[1].result.instructions | Should Match ([regex]::Escape("$root\docs\agent\s7dcl-format.md"))
    }

    It 'tool texts name a guide by its absolute path, or not at all' {
        $texts = @($byId[2].result.tools | ForEach-Object { $_.description }) -join "`n"
        $texts | Should Not Match 'docs/agent'
        $texts | Should Match ([regex]::Escape("$root\docs\agent\s7dcl-format.md"))
    }

    It 'probe records in the project, library_approve asks the user with no tool named' {
        $probe = @($byId[2].result.tools | Where-Object { $_.name -eq 'probe' })[0].description
        $probe | Should Match "docs\\project\.md with \[PROBE\]"
        $approve = @($byId[2].result.tools | Where-Object { $_.name -eq 'library_approve' })[0].description
        $approve | Should Match 'ask the user per level'
        $approve | Should Not Match 'multiple-choice'
    }

    It 'full_export names standards among what it leaves alone' {
        @($byId[2].result.tools | Where-Object { $_.name -eq 'full_export' })[0].description | Should Match 'archives and standards are never touched'
    }

    It 'connect no longer says the agent never opens a project' {
        $connect = @($byId[2].result.tools | Where-Object { $_.name -eq 'connect' })[0].description
        $connect | Should Not Match 'never opens'
        $connect | Should Match 'project_open'
    }
}
