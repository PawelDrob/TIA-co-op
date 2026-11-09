# Test-only tools, loaded with TiaBridge.ps1 -ToolScript. A noisy tool, as a careless handler would be.
Register-McpTool -Name 'echo' -Description 'Echoes text' -Schema @{ type = 'object' } -Handler {
    param($a)
    Write-Host 'noise from Write-Host'
    [Console]::WriteLine('noise from Console.WriteLine')
    'stray pipeline output'
    @{ ok = $true; text = $a.text }
}
