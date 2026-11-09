$here = Split-Path -Parent $MyInvocation.MyCommand.Path
foreach ($f in 'Mcp.ps1', 'Tia.ps1', 'Tools\Objects.ps1', 'Tools\Probe.ps1') { . (Join-Path $here "..\$f") }

Describe 'Format-ProbeValue' {
    It 'shows a library type version as its type name, number and state' {
        $v = [pscustomobject]@{ VersionNumber = [version]'0.0.25'; State = 'Committed'; TypeObject = [pscustomobject]@{ Name = 'typeTelegramRead' } }
        Format-ProbeValue $v | Should Be "<typeTelegramRead V 0.0.25 Committed>"
    }

    It 'shows a library type instance info as its instance' {
        $i = [pscustomobject]@{ LibraryTypeInstance = [pscustomobject]@{ Name = 'typePosition' }; LibraryTypeVersion = $null }
        Format-ProbeValue $i | Should Match "typePosition"
    }

    It 'shows a project language as its culture' {
        Format-ProbeValue ([pscustomobject]@{ Culture = [System.Globalization.CultureInfo]'es-ES' }) | Should Match 'es-ES>$'
    }

    It 'keeps simple values and named objects as before' {
        Format-ProbeValue 42 | Should Be '42'
        Format-ProbeValue ([pscustomobject]@{ Name = 'Main' }) | Should Match "'Main'"
    }
}

Describe 'Resolve-ProbeMember' {
    It 'returns an empty collection as the collection, not as null' {
        $list = New-Object System.Collections.Generic.List[string]
        $v = [pscustomobject]@{ Dependencies = $list }
        $r = Resolve-ProbeMember $v 'Dependencies'
        $null -eq $r | Should Be $false
        $r.GetType().Name | Should Be 'List`1'
        $r.Count | Should Be 0
    }

    It 'keeps the type of a full collection and indexes into it' {
        $list = New-Object System.Collections.Generic.List[string]; $list.Add('a'); $list.Add('b')
        $v = [pscustomobject]@{ Versions = $list }
        (Resolve-ProbeMember $v 'Versions').GetType().Name | Should Be 'List`1'
        Resolve-ProbeMember $v 'Versions[1]' | Should Be 'b'
    }
}

Describe 'probe that ends TIA' {
    . (Join-Path $here '..\Bridge.ps1')
    . (Join-Path $here '..\Repo.ps1')
    . (Join-Path $here '..\Rules.ps1')
    if (-not ('Siemens.Engineering.IEngineeringServiceProvider' -as [type])) { Add-Type -TypeDefinition 'namespace Siemens.Engineering { public interface IEngineeringServiceProvider { } }' }
    if (-not ('FakeProbe.Target' -as [type])) {
        Add-Type -TypeDefinition @"
namespace Siemens.Engineering { public interface IEngineeringObject { } }
namespace FakeProbe {
    public class NonRecoverableException : System.Exception { public NonRecoverableException(string m) : base(m) { } }
    public class Info { public string Name { get; set; } public string AccessMode { get; set; } }
    public class Target : Siemens.Engineering.IEngineeringObject {
        public bool Ends { get; set; }
        public Info[] GetAttributeInfos() { return new[] { new Info { Name = "A", AccessMode = "Read" } }; }
        public object GetAttribute(string n) {
            if (Ends) throw new NonRecoverableException("Unexpected exception");
            throw new System.InvalidOperationException("not here");
        }
        public string[] GetCompositionInfos() { return new string[0]; }
        public string[] GetInvocationInfos() { return new string[0]; }
    }
}
"@
    }
    function Resolve-ProbeRoot([string]$Path) { $script:probed }

    It 'reaches the dispatch when an attribute throws it, and refuses TIA calls until connect' {
        Initialize-BridgeContext @{ maxResponseChars = 20000 }
        Set-BridgeProject -Name 'P' -Path 'C:\P.ap20' -Repo (Join-Path $TestDrive 'R')
        $script:probed = New-Object FakeProbe.Target -Property @{ Ends = $true }
        $d = Invoke-BridgeTool 'probe' { param($a) Invoke-ProbeTool $a } ([pscustomobject]@{ object_path = 'x' })
        $d.result.error.tiaEnded | Should Be $true
        $d.result.error.note | Should Match 'call connect'
        { Get-TiaProject } | Should Throw 'call connect'
    }

    It 'keeps a plain failure as the error of that attribute' {
        $script:probed = New-Object FakeProbe.Target
        $r = Invoke-ProbeTool ([pscustomobject]@{ object_path = 'x' })
        $r.ok | Should Be $true
        @($r.attributes | Where-Object { $_.name -eq 'A' })[0].error | Should Match 'not here'
    }
}

Describe 'probe of a project with several devices' {
    Register-ObjectKind 'fakeprobe' @{
        scope = 'plc'; dir = 'plc\probe'; description = 'test kind'
        items = { param($root) @{ name = 'X'; folder = ''; obj = (New-Object FakeProbe.Target) } }
    }
    function Get-TiaSoftware([string]$Kind, [string]$Device = '') { $script:asked = "$Kind/$Device"; 'root' }

    It 'takes the device of a <kind>:<name> from the device argument' {
        $r = Invoke-ProbeTool ([pscustomobject]@{ object_path = 'fakeprobe:X'; device = 'PLC_2' })
        $r.ok | Should Be $true
        $script:asked | Should Be 'plc/PLC_2'
    }

    It 'asks for no device without it, as in a project with one' {
        $null = Resolve-ProbeRoot 'fakeprobe:X'
        $script:asked | Should Be 'plc/'
    }

    It 'takes the device argument for plc and hmi as well; plc:<device> wins' {
        $null = Resolve-ProbeRoot 'hmi' 'HMI_2'
        $script:asked | Should Be 'hmi/HMI_2'
        $null = Resolve-ProbeRoot 'plc:PLC_3' 'PLC_2'
        $script:asked | Should Be 'plc/PLC_3'
    }

    It 'offers the device in its schema and shows made-up names in its description' {
        Reset-McpTools; Register-ProbeTool
        $t = $script:McpTools['probe']
        $t.inputSchema.properties.ContainsKey('device') | Should Be $true
        $t.description | Should Match 'block:MyBlock'
    }
}
