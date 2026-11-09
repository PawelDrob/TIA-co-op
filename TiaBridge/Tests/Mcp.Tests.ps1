$here = Split-Path -Parent $MyInvocation.MyCommand.Path
. (Join-Path $here '..\Mcp.ps1')

Describe 'Invoke-McpRequest' {
    BeforeEach { Reset-McpTools }

    It 'answers initialize with the protocol version the client asked for and a tools capability' {
        $resp = Invoke-McpRequest '{"jsonrpc":"2.0","id":1,"method":"initialize","params":{"protocolVersion":"2025-06-18","capabilities":{},"clientInfo":{"name":"t","version":"1"}}}' | ConvertFrom-Json
        $resp.id | Should Be 1
        $resp.result.protocolVersion | Should Be '2025-06-18'
        $resp.result.serverInfo.name | Should Be 'tia'
        ($resp.result.capabilities.PSObject.Properties.Name -contains 'tools') | Should Be $true
    }

    It 'lists registered tools with their input schema' {
        Register-McpTool -Name 'echo' -Description 'Echoes text' -Schema @{ type = 'object'; properties = @{ text = @{ type = 'string' } }; required = @('text') } -Handler { param($a) @{ ok = $true; text = $a.text } }
        $resp = Invoke-McpRequest '{"jsonrpc":"2.0","id":"a","method":"tools/list"}' | ConvertFrom-Json
        $resp.id | Should Be 'a'
        @($resp.result.tools).Count | Should Be 1
        $resp.result.tools[0].name | Should Be 'echo'
        $resp.result.tools[0].inputSchema.required[0] | Should Be 'text'
    }

    It 'calls a tool and returns its result as JSON text, umlauts intact' {
        Register-McpTool -Name 'echo' -Description 'Echoes text' -Schema @{ type = 'object' } -Handler { param($a) @{ ok = $true; text = $a.text } }
        $resp = Invoke-McpRequest '{"jsonrpc":"2.0","id":2,"method":"tools/call","params":{"name":"echo","arguments":{"text":"Gr\u00f6\u00dfe \u00c4"}}}' | ConvertFrom-Json
        $resp.result.isError | Should Be $false
        ($resp.result.content[0].text | ConvertFrom-Json).text | Should BeExactly "Gr$([char]0xF6)$([char]0xDF)e $([char]0xC4)"
    }

    It 'flags a result with ok = false as a tool error' {
        Register-McpTool -Name 'fail' -Description 'x' -Schema @{ type = 'object' } -Handler { param($a) @{ ok = $false } }
        $resp = Invoke-McpRequest '{"jsonrpc":"2.0","id":3,"method":"tools/call","params":{"name":"fail"}}' | ConvertFrom-Json
        $resp.result.isError | Should Be $true
    }

    It 'turns an exception in a tool into a tool error carrying the exception type and message' {
        Register-McpTool -Name 'boom' -Description 'x' -Schema @{ type = 'object' } -Handler { param($a) throw [System.IO.FileNotFoundException]::new('no such file') }
        $resp = Invoke-McpRequest '{"jsonrpc":"2.0","id":4,"method":"tools/call","params":{"name":"boom","arguments":{}}}' | ConvertFrom-Json
        $resp.result.isError | Should Be $true
        $body = $resp.result.content[0].text | ConvertFrom-Json
        $body.ok | Should Be $false
        $body.error.type | Should Be 'System.IO.FileNotFoundException'
        $body.error.message | Should Be 'no such file'
    }

    It 'answers an unknown tool with a tool error naming it' {
        $resp = Invoke-McpRequest '{"jsonrpc":"2.0","id":5,"method":"tools/call","params":{"name":"nope"}}' | ConvertFrom-Json
        $resp.result.isError | Should Be $true
        $resp.result.content[0].text | Should Match 'nope'
    }

    It 'returns nothing for a notification' {
        Invoke-McpRequest '{"jsonrpc":"2.0","method":"notifications/initialized"}' | Should BeNullOrEmpty
    }

    It 'answers an unknown method with error -32601' {
        $resp = Invoke-McpRequest '{"jsonrpc":"2.0","id":6,"method":"resources/list"}' | ConvertFrom-Json
        $resp.error.code | Should Be -32601
    }

    It 'answers ping with an empty result' {
        $resp = Invoke-McpRequest '{"jsonrpc":"2.0","id":7,"method":"ping"}' | ConvertFrom-Json
        $resp.id | Should Be 7
        $resp.error | Should BeNullOrEmpty
    }

    It 'answers malformed JSON with a parse error and a null id' {
        $resp = Invoke-McpRequest '{"jsonrpc":"2.0", "id": 8, "method":' | ConvertFrom-Json
        $resp.error.code | Should Be -32700
        $resp.id | Should BeNullOrEmpty
    }
}

Describe 'Write-BridgeProgress' {
    It 'writes one "progress {json}" line, ASCII only, in the order of the fields' {
        $script:logLines = New-Object System.Collections.ArrayList
        function Write-BridgeLog([string]$Text) { [void]$script:logLines.Add($Text) }
        Write-BridgeProgress ([ordered]@{ event = 'object'; kind = 'block'; n = 1; of = 2; name = "Gr$([char]0xFC)$([char]0xDF)e`n<1>"; ok = $true })
        $script:logLines.Count | Should Be 1
        $line = $script:logLines[0]
        $u = [string][char]92 + 'u'     # backslash u
        $line | Should BeExactly "progress {`"event`":`"object`",`"kind`":`"block`",`"n`":1,`"of`":2,`"name`":`"Gr${u}00fc${u}00dfe\n${u}003c1${u}003e`",`"ok`":true}"
        ($line.Substring(9) | ConvertFrom-Json).name | Should Be "Gr$([char]0xFC)$([char]0xDF)e`n<1>"
    }
}

Describe 'initialize: the protocol version' {
    function Get-Answer([string]$Params) { (Invoke-McpRequest "{`"jsonrpc`":`"2.0`",`"id`":1,`"method`":`"initialize`",`"params`":$Params}" | ConvertFrom-Json).result.protocolVersion }

    It 'answers a version it supports with that version' {
        Get-Answer '{"protocolVersion":"2024-11-05"}' | Should Be '2024-11-05'
        Get-Answer '{"protocolVersion":"2025-03-26"}' | Should Be '2025-03-26'
        Get-Answer '{"protocolVersion":"2025-06-18"}' | Should Be '2025-06-18'
    }

    It 'answers its newest for a version it does not know, and for none' {
        Get-Answer '{"protocolVersion":"2999-01-01"}' | Should Be '2025-06-18'
        Get-Answer '{}' | Should Be '2025-06-18'
    }
}
