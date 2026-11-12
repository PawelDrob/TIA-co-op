$here = Split-Path -Parent $MyInvocation.MyCommand.Path
foreach ($f in 'Mcp.ps1', 'Tia.ps1', 'Repo.ps1', 'Rules.ps1', 'Bridge.ps1') { . (Join-Path $here "..\$f") }
if (-not ('FakeSiemens.NonRecoverableException' -as [type])) {
    Add-Type -TypeDefinition 'namespace FakeSiemens { public class NonRecoverableException : System.Exception { public NonRecoverableException(string m) : base(m) { } } }'
}

Describe 'Invoke-BridgeTool (error contract and logs on every call)' {
    $root = Join-Path $TestDrive 'projects'

    It 'turns an exception into ok = false with the unwrapped error and logs it outside any repo before connect' {
        Initialize-BridgeContext @{ projectsRoot = $root; maxResponseChars = 20000 }
        $handler = { param($a) throw [System.Management.Automation.MethodInvocationException]::new('outer', [System.IO.IOException]::new('locked')) }
        $d = Invoke-BridgeTool 'list' $handler (New-Object psobject)
        $d.result.ok | Should Be $false
        $d.result.error.type | Should Be 'System.IO.IOException'
        $d.result.error.message | Should Be 'locked'
        Test-Path $d.result.log | Should Be $true
        $d.result.log | Should Match '_bridge\\logs\\\d{8}_\d{6}_list\.json$'
        ($d.text | ConvertFrom-Json).error.message | Should Be 'locked'
    }

    It 'adds project and repo, and logs into the repo once connected' {
        Initialize-BridgeContext @{ projectsRoot = $root; maxResponseChars = 20000 }
        $repo = Join-Path $root 'P1'
        Set-BridgeProject -Name 'P1' -Path 'C:\P1.ap20' -Repo $repo
        $d = Invoke-BridgeTool 'list' { param($a) @{ ok = $true; items = @() } } (New-Object psobject)
        $d.result.project | Should Be 'P1'
        $d.result.repo | Should Be $repo
        $d.result.log | Should Match '^logs\\'
        Test-Path (Join-Path $repo $d.result.log) | Should Be $true
    }

    It 'keeps the full result in the log when the response is shortened' {
        Initialize-BridgeContext @{ projectsRoot = $root; maxResponseChars = 2000 }
        $d = Invoke-BridgeTool 'export' { param($a) @{ ok = $true; items = @(foreach ($i in 1..100) { @{ name = "B$i"; ok = $true; path = 'plc\blocks\' + ('x' * 50) } }) } } (New-Object psobject)
        $d.text.Length | Should BeLessThan 2001
        ($d.text | ConvertFrom-Json).truncated | Should Be $true
        @((Get-Content $d.result.log -Raw | ConvertFrom-Json).items).Count | Should Be 100
    }

    It 'gives every project its own session state, kept when switching back' {
        Initialize-BridgeContext @{ projectsRoot = $root; maxResponseChars = 20000 }
        Set-BridgeProject -Name 'A' -Path 'C:\A.ap20' -Repo (Join-Path $root 'A')
        Register-Archive (Get-BridgeSession)
        Set-BridgeProject -Name 'B' -Path 'C:\B.ap20' -Repo (Join-Path $root 'B')
        Test-WriteAllowed (Get-BridgeSession) | Should Match 'archive'
        Set-BridgeProject -Name 'A' -Path 'C:\A.ap20' -Repo (Join-Path $root 'A')
        Test-WriteAllowed (Get-BridgeSession) | Should BeNullOrEmpty
    }
}

Describe 'TIA ended (NonRecoverableException)' {
    $root = Join-Path $TestDrive 'projects'

    It 'turns a thrown NonRecoverableException into a note that asks for connect, and refuses TIA calls until then' {
        Initialize-BridgeContext @{ projectsRoot = $root; maxResponseChars = 20000 }
        Set-BridgeProject -Name 'P1' -Path 'C:\P1.ap20' -Repo (Join-Path $root 'P1')
        Register-Archive (Get-BridgeSession)
        $handler = { param($a) throw [System.Management.Automation.MethodInvocationException]::new('outer', [FakeSiemens.NonRecoverableException]::new('Unexpected exception')) }
        $d = Invoke-BridgeTool 'library_edit_type' $handler (New-Object psobject)
        $d.result.error.tiaEnded | Should Be $true
        $d.result.error.note | Should Match 'call connect'
        { Get-TiaProject } | Should Throw 'call connect'
    }

    It 'finds the item that ended TIA in a write of library types (release chain items carry a type, no name)' {
        Initialize-BridgeContext @{ projectsRoot = $root; maxResponseChars = 20000 }
        $items = @([ordered]@{ type = 'T1'; ok = $true }, [ordered]@{ type = 'T2'; ok = $false; error = @{ type = 'Siemens.Engineering.NonRecoverableException'; tiaEnded = $true } })
        $r = Get-TiaEndedResult $items 'release chain'
        $r.note | Should Match 'Nothing of the release chain is in TIA: TIA Portal ended at T2'
        $items[0].lost | Should Be $true
        Get-TiaEndedResult @([ordered]@{ type = 'T1'; ok = $false; error = @{ type = 'X'; tiaEnded = $false } }) 'release chain' | Should BeNullOrEmpty
    }
}

Describe 'A failure after a commit' {
    $root = Join-Path $TestDrive 'projects'
    It 'carries what was committed, with the error' {
        Initialize-BridgeContext @{ projectsRoot = $root; maxResponseChars = 20000 }
        $h = { param($a) Set-CommittedFact 'instancesRemoved' @(@{ object = 'Gone' }); throw 'the walk failed' }
        $d = (Invoke-BridgeTool 'tia_status' $h (New-Object psobject)).result
        $d.ok | Should Be $false
        $d.error.message | Should Match 'the walk failed'
        @($d.instancesRemoved)[0].object | Should Be 'Gone'
        $d.summary | Should Match 'already kept part of it'
    }
    It 'adds nothing to a failure that committed nothing, nor carries one call into the next' {
        Initialize-BridgeContext @{ projectsRoot = $root; maxResponseChars = 20000 }
        $null = Invoke-BridgeTool 'tia_status' { param($a) Set-CommittedFact 'released' @('x'); @{ ok = $true } } (New-Object psobject)
        $d = (Invoke-BridgeTool 'tia_status' { param($a) throw 'no' } (New-Object psobject)).result
        $d.released | Should Be $null
        $d.summary | Should Be $null
    }
}

# The bridge runs on an MTA thread (TiaBridge.ps1, ticket 94); a window needs an STA thread of its own.
Describe 'Invoke-OnStaThread' {
    It 'runs the block on an STA thread when called from an MTA thread, with its arguments, and returns its output' {
        $rs = [runspacefactory]::CreateRunspace(); $rs.ApartmentState = 'MTA'; $rs.Open()
        $ps = [powershell]::Create(); $ps.Runspace = $rs
        $null = $ps.AddScript({ param($Dir)
            foreach ($f in 'Mcp.ps1', 'Tia.ps1', 'Repo.ps1', 'Rules.ps1', 'Bridge.ps1') { . (Join-Path $Dir $f) }
            "caller $([Threading.Thread]::CurrentThread.GetApartmentState())"
            Invoke-OnStaThread { param($x) "block $([Threading.Thread]::CurrentThread.GetApartmentState()) $x" } 'given' }).AddArgument((Join-Path $here '..'))
        $out = @($ps.Invoke())
        $ps.Dispose(); $rs.Dispose()
        ($out -join '|') | Should Be 'caller MTA|block STA given'
    }

    It 'throws what the block throws' {
        { Invoke-OnStaThread { throw 'from the block' } } | Should Throw 'from the block'
    }
}
