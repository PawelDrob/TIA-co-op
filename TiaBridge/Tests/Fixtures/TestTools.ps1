# Test-only tools, loaded with TiaBridge.ps1 -ToolScript. A noisy tool, as a careless handler would be.
Register-McpTool -Name 'echo' -Description 'Echoes text' -Schema @{ type = 'object' } -Handler {
    param($a)
    Write-Host 'noise from Write-Host'
    [Console]::WriteLine('noise from Console.WriteLine')
    'stray pipeline output'
    @{ ok = $true; text = $a.text }
}

# The apartment of the thread a tool runs on: TIA's call-backs wait on a bridge attached from an STA thread.
Register-McpTool -Name 'apartment' -Description 'The apartment of the tool thread' -Schema @{ type = 'object' } -Handler {
    param($a)
    @{ ok = $true; apartment = [string][Threading.Thread]::CurrentThread.GetApartmentState() }
}
