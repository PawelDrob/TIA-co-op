$here = Split-Path -Parent $MyInvocation.MyCommand.Path
foreach ($f in 'Mcp.ps1', 'Tia.ps1', 'Bridge.ps1', 'Tools\Objects.ps1') { . (Join-Path $here "..\$f") }

Describe 'Invoke-ListTool' {
    Mock Get-BridgeSession { @{} }
    Mock Get-KindRoot { $null }

    It 'lists a kind without info (screens) with name and folder only, no infoError' {
        Mock Get-ObjectKind { @{ name = 'hmi_screen'; items = { param($r) @(@{ obj = $null; name = '5051 - G05'; folder = '5000/G05' }) } } }
        $r = Invoke-ListTool ([pscustomobject]@{ kind = 'hmi_screen' })
        $r.count | Should Be 1
        $r.items[0].name | Should Be '5051 - G05'
        $r.items[0].Contains('infoError') | Should Be $false
    }

    It 'still adds the info of a kind that has one' {
        Mock Get-ObjectKind { @{ name = 'x'; items = { param($r) @(@{ obj = $null; name = 'a'; folder = '' }) }; info = { param($e) @{ number = 7 } } } }
        $r = Invoke-ListTool ([pscustomobject]@{ kind = 'x' })
        $r.items[0].number | Should Be 7
    }
}
