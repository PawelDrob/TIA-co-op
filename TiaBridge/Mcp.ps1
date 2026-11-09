# Mcp.ps1 - MCP over stdio for Windows PowerShell 5.1: JSON-RPC, one message per line, tool registry.
# Nothing here writes to stdout except Start-McpLoop; diagnostics go to stderr (Write-BridgeLog).

$script:McpServerName = 'tia'
$script:McpServerVersion = '0.1.0'
# The protocol versions this server speaks, newest first: a client that asks for another one gets the newest.
$script:McpProtocols = @('2025-06-18', '2025-03-26', '2024-11-05')

# What initialize sends a client for its session, none when empty (TiaBridge.ps1 sets it: Guides.ps1).
$script:McpInstructions = ''

function Reset-McpTools { $script:McpTools = [ordered]@{} }
if (-not $script:McpTools) { Reset-McpTools }

function Write-BridgeLog([string]$Text) {
    if ($script:BridgeSecrets) { $Text = Hide-SecretText $Text $script:BridgeSecrets }
    [Console]::Error.WriteLine("[tiabridge $(Get-Date -Format 'HH:mm:ss')] $Text")
}

# Secret values of the tool call that runs (Bridge.ps1, Get-SecretValues): @{ value; word; mask }. A word secret (a
# user name) is replaced where it stands as a whole word, a password wherever it occurs.
$script:BridgeSecrets = @()

function Hide-SecretText([string]$Text, [object[]]$Secrets) {
    foreach ($s in $Secrets) {
        $pattern = [regex]::Escape($s.value)
        if ($s.word) { $pattern = "(?<![\w])$pattern(?![\w])" }
        $Text = [regex]::Replace($Text, $pattern, $s.mask)
    }
    $Text
}

# A machine-readable stderr line beside the human ones: "[tiabridge HH:mm:ss] progress {json}", the JSON on one
# line and ASCII only (\uXXXX), so a reader decodes it whatever code page the console has. Fields: event = tia |
# step | part | object, then the event's own.
function Write-BridgeProgress([System.Collections.IDictionary]$Fields) {
    $json = ConvertTo-Json -InputObject $Fields -Depth 4 -Compress
    $json = [regex]::Replace($json, '[^\x00-\x7F]', { param($m) '\u{0:x4}' -f [int][char]$m.Value })
    Write-BridgeLog "progress $json"
    if ($script:BridgeState) { Update-BridgeStateProgress $Fields }   # State.ps1
}

function ConvertTo-McpJson($Value) { ConvertTo-Json -InputObject $Value -Depth 64 -Compress }

# Handler: scriptblock taking the arguments object (PSCustomObject); returns a hashtable with at least 'ok'.
function Register-McpTool([string]$Name, [string]$Description, [hashtable]$Schema, [scriptblock]$Handler) {
    $script:McpTools[$Name] = @{ name = $Name; description = $Description; inputSchema = $Schema; handler = $Handler }
}

# Runs one tool. TiaBridge.ps1 replaces this hook to add the error contract, logs and response shortening;
# it receives (name, handler, arguments) and returns @{ result = <hashtable>; text = <response text> }.
$script:McpToolDispatch = {
    param($Name, $Handler, $Arguments)
    try { $r = Invoke-McpHandler $Handler $Arguments }
    catch { $r = @{ ok = $false; error = @{ type = $_.Exception.GetType().FullName; message = $_.Exception.Message } } }
    @{ result = $r; text = (ConvertTo-McpJson $r) }
}

# A handler's stray pipeline output must not replace its result: the last hashtable wins.
function Invoke-McpHandler([scriptblock]$Handler, $Arguments) {
    $out = @(& $Handler $Arguments)
    $r = $out | Where-Object { $_ -is [System.Collections.IDictionary] } | Select-Object -Last 1
    if ($null -eq $r) { $r = @{ ok = $false; error = @{ type = 'TiaBridge.NoResult'; message = 'The tool returned no result object.' } } }
    $r
}

function New-McpError($Id, [int]$Code, [string]$Message) {
    ConvertTo-McpJson @{ jsonrpc = '2.0'; id = $Id; error = @{ code = $Code; message = $Message } }
}

# One JSON-RPC message in, the response line out ($null for notifications).
function Invoke-McpRequest([string]$Line) {
    try { $msg = $Line | ConvertFrom-Json -ErrorAction Stop }
    catch { return (New-McpError $null -32700 "Parse error: $($_.Exception.Message)") }
    $isNotification = -not ($msg.PSObject.Properties.Name -contains 'id')
    if ($isNotification) { return $null }

    switch ($msg.method) {
        'initialize' {
            $proto = $msg.params.protocolVersion
            if ($script:McpProtocols -notcontains $proto) { $proto = $script:McpProtocols[0] }
            $result = @{ protocolVersion = $proto
                         capabilities = @{ tools = @{} }
                         serverInfo = @{ name = $script:McpServerName; version = $script:McpServerVersion } }
            if ($script:McpInstructions) { $result.instructions = $script:McpInstructions }
        }
        'ping' { $result = @{} }
        'tools/list' {
            $list = @(foreach ($t in $script:McpTools.Values) { @{ name = $t.name; description = $t.description; inputSchema = $t.inputSchema } })
            $result = @{ tools = $list }
        }
        'tools/call' {
            $name = [string]$msg.params.name
            $tool = $script:McpTools[$name]
            if (-not $tool) {
                $text = ConvertTo-McpJson @{ ok = $false; error = @{ type = 'TiaBridge.UnknownTool'; message = "Unknown tool '$name'." } }
                $result = @{ content = @(@{ type = 'text'; text = $text }); isError = $true }
            } else {
                $arguments = $msg.params.arguments
                if ($null -eq $arguments) { $arguments = New-Object psobject }
                $d = & $script:McpToolDispatch $name $tool.handler $arguments
                $result = @{ content = @(@{ type = 'text'; text = $d.text }); isError = (-not $d.result.ok) }
            }
        }
        default { return (New-McpError $msg.id -32601 "Method not found: $($msg.method)") }
    }
    ConvertTo-McpJson @{ jsonrpc = '2.0'; id = $msg.id; result = $result }
}

# Reads stdin until it closes. The protocol owns the raw stdout stream; everything else that would print to
# the console (Console.Write, Write-Host) is sent to stderr so it cannot corrupt a response line.
function Start-McpLoop {
    $utf8 = New-Object System.Text.UTF8Encoding $false
    $reader = New-Object System.IO.StreamReader ([Console]::OpenStandardInput()), $utf8
    $writer = New-Object System.IO.StreamWriter ([Console]::OpenStandardOutput()), $utf8
    $writer.AutoFlush = $true
    $writer.NewLine = "`n"
    [Console]::SetOut([Console]::Error)
    Write-BridgeLog "MCP server started (PID $PID, STA: $([Threading.Thread]::CurrentThread.GetApartmentState() -eq 'STA'))"
    while ($null -ne ($line = $reader.ReadLine())) {
        $line = $line.TrimStart([char]0xFEFF).Trim()
        if (-not $line) { continue }
        try { $resp = Invoke-McpRequest $line }
        catch { $resp = New-McpError $null -32603 "Internal error: $($_.Exception.Message)" }
        if ($resp) { $writer.WriteLine($resp) }
    }
    Write-BridgeLog 'stdin closed, MCP server stops'
}
