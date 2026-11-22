$here = Split-Path -Parent $MyInvocation.MyCommand.Path
foreach ($f in 'Mcp.ps1', 'Tia.ps1', 'Tools\Objects.ps1', 'Tools\Probe.ps1') { . (Join-Path $here "..\$f") }

# Openness stand-ins: the interfaces the probe asks an object for, and the self-description it reads (the V20
# signatures: reflection of Siemens.Engineering.dll). Target and Comp record every call that would change TIA in
# Changed, which the tests expect empty.
if (-not ('FakeProbe.Target' -as [type])) {
    Add-Type -TypeDefinition @"
using System; using System.Collections.Generic;
namespace Siemens.Engineering {
    public interface IEngineeringInstance { }
    public interface IEngineeringService { }
    public interface IEngineeringObject : IEngineeringInstance { }
    public interface IEngineeringComposition : IEngineeringInstance, System.Collections.IEnumerable { }
    public interface IEngineeringServiceProvider { T GetService<T>() where T : class; }
    public enum EngineeringCreateRelevance { None, Relevant, Mandatory }
    public class EngineeringAttributeInfo { public string Name { get; set; } public string AccessMode { get; set; } public EngineeringCreateRelevance CreateRelevance { get; set; } public IEnumerable<Type> SupportedTypes { get; set; } }
    public class EngineeringCompositionInfo { public string Name { get; set; } }
    public class EngineeringCreationParameterInfo { public string Name { get; set; } public bool IsMandatory { get; set; } }
    public class EngineeringCreationInfo { public Type Type { get; set; } public IList<EngineeringCreationParameterInfo> ParameterInfos { get; set; } }
    public class EngineeringInvocationParameterInfo { public string Name { get; set; } public Type Type { get; set; } }
    public class EngineeringInvocationInfo { public string Name { get; set; } public IList<EngineeringInvocationParameterInfo> ParameterInfos { get; set; } }
    public class EngineeringServiceInfo { public Type Type { get; set; } }
}
namespace Siemens.Engineering.Private { public interface IInternalObjectAccess { } }
namespace FakeProbe {
    public class NonRecoverableException : Exception { public NonRecoverableException(string m) : base(m) { } }
    public class Target : Siemens.Engineering.IEngineeringObject, Siemens.Engineering.Private.IInternalObjectAccess {
        public bool Ends { get; set; }
        public object Refusing { get { throw new InvalidOperationException("getter refused"); } }
        public object Empty { get { return null; } }
        public List<string> Changed = new List<string>();
        public List<Siemens.Engineering.EngineeringAttributeInfo> Attributes = new List<Siemens.Engineering.EngineeringAttributeInfo> {
            new Siemens.Engineering.EngineeringAttributeInfo { Name = "A", AccessMode = "Read" } };
        public IList<Siemens.Engineering.EngineeringAttributeInfo> GetAttributeInfos() { return Attributes; }
        public object GetAttribute(string n) {
            if (Ends) throw new NonRecoverableException("Unexpected exception");
            throw new InvalidOperationException("not here");
        }
        public void SetAttribute(string n, object v) { Changed.Add("SetAttribute " + n); }
        public List<Siemens.Engineering.EngineeringCompositionInfo> Compositions = new List<Siemens.Engineering.EngineeringCompositionInfo>();
        public IList<Siemens.Engineering.EngineeringCompositionInfo> GetCompositionInfos() { return Compositions; }
        public Dictionary<string, List<Siemens.Engineering.EngineeringCreationInfo>> Creations = new Dictionary<string, List<Siemens.Engineering.EngineeringCreationInfo>>();
        public IList<Siemens.Engineering.EngineeringCreationInfo> GetCreationInfos(string composition) {
            if (composition == "Broken") throw new InvalidOperationException("no creation infos here");
            return Creations.ContainsKey(composition) ? Creations[composition] : new List<Siemens.Engineering.EngineeringCreationInfo>();
        }
        public Siemens.Engineering.IEngineeringObject Create(string composition, Type type, IEnumerable<KeyValuePair<string, object>> parameters) { Changed.Add("Create " + composition); return null; }
        public List<Siemens.Engineering.EngineeringInvocationInfo> Invocations = new List<Siemens.Engineering.EngineeringInvocationInfo>();
        public IList<Siemens.Engineering.EngineeringInvocationInfo> GetInvocationInfos() { return Invocations; }
        public object Invoke(string name, IEnumerable<KeyValuePair<Type, object>> parameters) { Changed.Add("Invoke " + name); return null; }
    }
    public class Comp : Siemens.Engineering.IEngineeringComposition {
        public int Size;
        public List<string> Changed = new List<string>();
        public System.Collections.IEnumerator GetEnumerator() { for (int i = 0; i < Size; i++) yield return "item" + i; }
        public IList<Siemens.Engineering.EngineeringCreationInfo> GetCreationInfos() {
            return new List<Siemens.Engineering.EngineeringCreationInfo> { new Siemens.Engineering.EngineeringCreationInfo {
                Type = typeof(Target), ParameterInfos = new List<Siemens.Engineering.EngineeringCreationParameterInfo> {
                    new Siemens.Engineering.EngineeringCreationParameterInfo { Name = "Name", IsMandatory = true } } } };
        }
        public IList<Siemens.Engineering.EngineeringInvocationInfo> GetInvocationInfos() {
            return new List<Siemens.Engineering.EngineeringInvocationInfo> { new Siemens.Engineering.EngineeringInvocationInfo {
                Name = "ImportFromDocuments", ParameterInfos = new List<Siemens.Engineering.EngineeringInvocationParameterInfo>() } };
        }
        public Siemens.Engineering.IEngineeringObject Create(Type type, IEnumerable<KeyValuePair<string, object>> parameters) { Changed.Add("Create"); return null; }
        public object Invoke(string name, IEnumerable<KeyValuePair<Type, object>> parameters) { Changed.Add("Invoke " + name); return null; }
    }
    public class SvcA : Siemens.Engineering.IEngineeringService { }
    public class SvcB : Siemens.Engineering.IEngineeringService { }
    public class SvcC : Siemens.Engineering.IEngineeringService { }
    public class SvcD : Siemens.Engineering.IEngineeringService { }
    public class SvcE : Siemens.Engineering.IEngineeringService { }
    public class SvcF : Siemens.Engineering.IEngineeringService { }
    public class ServiceTarget : Target, Siemens.Engineering.IEngineeringServiceProvider {
        public List<Type> Services = new List<Type>();
        public List<Type> Advertised = new List<Type>();
        public Type Refuses;
        public bool InfosFail;
        public T GetService<T>() where T : class {
            if (typeof(T) == Refuses) throw new InvalidOperationException("service refused");
            return Services.Contains(typeof(T)) ? (T)Activator.CreateInstance(typeof(T)) : null;
        }
        public IList<Siemens.Engineering.EngineeringServiceInfo> GetServiceInfos() {
            if (InfosFail) throw new InvalidOperationException("no service infos");
            List<Siemens.Engineering.EngineeringServiceInfo> l = new List<Siemens.Engineering.EngineeringServiceInfo>();
            foreach (Type t in Advertised) l.Add(new Siemens.Engineering.EngineeringServiceInfo { Type = t });
            return l;
        }
    }
}
"@
}

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
    . (Join-Path $here '..\Results.ps1')
    . (Join-Path $here '..\Repo.ps1')
    . (Join-Path $here '..\Rules.ps1')
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

Describe 'probe of what an object describes of itself' {
    function Resolve-ProbeRoot([string]$Path) { $script:probed }

    It 'gives each attribute its create relevance and the types it takes' {
        $t = New-Object FakeProbe.Target
        $t.Attributes.Add((New-Object Siemens.Engineering.EngineeringAttributeInfo -Property @{
            Name = 'Number'; AccessMode = 'Read, Write'; CreateRelevance = 'Mandatory'; SupportedTypes = [type[]]@([int], [string]) }))
        $script:probed = $t
        $r = Invoke-ProbeTool ([pscustomobject]@{ object_path = 'x' })
        $a = @($r.attributes | Where-Object { $_.name -eq 'Number' })[0]
        $a.createRelevance | Should Be 'Mandatory'
        ($a.supportedTypes -join ',') | Should Be 'System.Int32,System.String'
    }
}

Describe 'probe of the properties of an object' {
    function Resolve-ProbeRoot([string]$Path) { $script:probed }

    It 'keeps a getter that throws as the error of that property, apart from one that gives null' {
        $script:probed = New-Object FakeProbe.Target
        $r = Invoke-ProbeTool ([pscustomobject]@{ object_path = 'x' })
        $refusing = @($r.properties | Where-Object { $_.name -eq 'Refusing' })[0]
        $refusing.error | Should Match 'getter refused'
        $refusing.Contains('value') | Should Be $false
        $empty = @($r.properties | Where-Object { $_.name -eq 'Empty' })[0]
        $empty.Contains('error') | Should Be $false
        $null -eq $empty.value | Should Be $true
    }
}

Describe 'probe of what an object can make' {
    function Resolve-ProbeRoot([string]$Path) { $script:probed }

    It 'gives each composition the types it can create and their parameters, and creates nothing' {
        $t = New-Object FakeProbe.Target
        $t.Compositions.Add((New-Object Siemens.Engineering.EngineeringCompositionInfo -Property @{ Name = 'Units' }))
        $t.Compositions.Add((New-Object Siemens.Engineering.EngineeringCompositionInfo -Property @{ Name = 'Broken' }))
        $p1 = New-Object Siemens.Engineering.EngineeringCreationParameterInfo -Property @{ Name = 'Name'; IsMandatory = $true }
        $p2 = New-Object Siemens.Engineering.EngineeringCreationParameterInfo -Property @{ Name = 'Author'; IsMandatory = $false }
        $c = New-Object Siemens.Engineering.EngineeringCreationInfo -Property @{ Type = [System.Uri]; ParameterInfos = [Siemens.Engineering.EngineeringCreationParameterInfo[]]@($p1, $p2) }
        $t.Creations['Units'] = New-Object 'System.Collections.Generic.List[Siemens.Engineering.EngineeringCreationInfo]'
        $t.Creations['Units'].Add($c)
        $script:probed = $t
        $r = Invoke-ProbeTool ([pscustomobject]@{ object_path = 'x' })
        $units = @($r.compositions | Where-Object { $_.name -eq 'Units' })[0]
        $units.creations[0].type | Should Be 'System.Uri'
        ($units.creations[0].parameters | ForEach-Object { "$($_.name)=$($_.mandatory)" }) -join ',' | Should Be 'Name=True,Author=False'
        @($r.compositions | Where-Object { $_.name -eq 'Broken' })[0].creationsError | Should Match 'no creation infos here'
        $t.Changed.Count | Should Be 0
    }

    It 'gives each action its parameters with their types, and calls none' {
        $t = New-Object FakeProbe.Target
        $p = New-Object Siemens.Engineering.EngineeringInvocationParameterInfo -Property @{ Name = 'path'; Type = [System.IO.DirectoryInfo] }
        $t.Invocations.Add((New-Object Siemens.Engineering.EngineeringInvocationInfo -Property @{ Name = 'Export'; ParameterInfos = [Siemens.Engineering.EngineeringInvocationParameterInfo[]]@($p) }))
        $script:probed = $t
        $r = Invoke-ProbeTool ([pscustomobject]@{ object_path = 'x' })
        $r.invocations[0].name | Should Be 'Export'
        $r.invocations[0].parameters[0].name | Should Be 'path'
        $r.invocations[0].parameters[0].type | Should Be 'System.IO.DirectoryInfo'
        $t.Changed.Count | Should Be 0
    }
}

Describe 'probe of the services of an object' {
    function Resolve-ProbeRoot([string]$Path) { $script:probed }
    $script:ProbeServiceTypes = @([FakeProbe.SvcA], [FakeProbe.SvcB], [FakeProbe.SvcC], [FakeProbe.SvcD], [FakeProbe.SvcE])

    It 'tells a service advertised from one available, one that answers null and one that fails' {
        $t = New-Object FakeProbe.ServiceTarget
        foreach ($k in [FakeProbe.SvcA], [FakeProbe.SvcC], [FakeProbe.SvcF]) { $t.Services.Add($k) }
        foreach ($k in [FakeProbe.SvcA], [FakeProbe.SvcB], [FakeProbe.SvcF]) { $t.Advertised.Add($k) }
        $t.Refuses = [FakeProbe.SvcD]
        $script:probed = $t
        $r = Invoke-ProbeTool ([pscustomobject]@{ object_path = 'x' })
        $got = @($r.services | ForEach-Object { "$($_.type -replace '^FakeProbe\.')=$($_.advertised)/$($_.state)" }) -join ','
        $got | Should Be 'SvcA=True/available,SvcB=True/null,SvcC=False/available,SvcD=False/failed,SvcF=True/available'
        @($r.services | Where-Object { $_.state -eq 'failed' })[0].error | Should Match 'service refused'
        $r.servicesNull | Should Be 1
    }

    It 'still tries every service when the object cannot say which it offers' {
        $t = New-Object FakeProbe.ServiceTarget
        $t.Services.Add([FakeProbe.SvcA])
        $t.InfosFail = $true
        $script:probed = $t
        $r = Invoke-ProbeTool ([pscustomobject]@{ object_path = 'x' })
        $r.serviceInfosError | Should Match 'no service infos'
        @($r.services | ForEach-Object { "$($_.type -replace '^FakeProbe\.')=$($_.state)" }) -join ',' | Should Be 'SvcA=available'
    }

    It 'names the base types and the public interfaces, whose members the type may not list itself' {
        $script:probed = New-Object FakeProbe.ServiceTarget
        $r = Invoke-ProbeTool ([pscustomobject]@{ object_path = 'x' })
        $r.bases -join ',' | Should Be 'FakeProbe.Target'
        $r.interfaces -contains 'Siemens.Engineering.IEngineeringServiceProvider' | Should Be $true
        $r.interfaces -contains 'Siemens.Engineering.IEngineeringObject' | Should Be $true
        @($r.interfaces | Where-Object { $_ -like '*.Private.*' }).Count | Should Be 0
    }

    It 'lists the methods of each public interface under its name, as a class may implement them out of sight' {
        $script:probed = New-Object FakeProbe.ServiceTarget
        $r = Invoke-ProbeTool ([pscustomobject]@{ object_path = 'x' })
        @($r.methods | Where-Object { $_ -like 'IEngineeringServiceProvider.GetService(*' }).Count | Should Be 1
        @($r.methods | Where-Object { $_ -like 'IInternalObjectAccess.*' }).Count | Should Be 0
    }

    $script:ProbeServiceTypes = $null
}

Describe 'probe of a composition' {
    # a composition is reached through member, as on TIA: the root holds it
    function Resolve-ProbeRoot([string]$Path) { [pscustomobject]@{ Units = $script:probed } }

    It 'gives what a composition can create and do, and changes nothing' {
        $c = New-Object FakeProbe.Comp -Property @{ Size = 2 }
        $script:probed = $c
        $r = Invoke-ProbeTool ([pscustomobject]@{ object_path = 'x'; member = 'Units' })
        $r.creations[0].type | Should Be 'FakeProbe.Target'
        $r.creations[0].parameters[0].name | Should Be 'Name'
        $r.invocations[0].name | Should Be 'ImportFromDocuments'
        $c.Changed.Count | Should Be 0
    }

    It 'counts every item and shows the first 100, saying that it cut' {
        $script:probed = New-Object FakeProbe.Comp -Property @{ Size = 250 }
        $r = Invoke-ProbeTool ([pscustomobject]@{ object_path = 'x'; member = 'Units' })
        $r.count | Should Be 250
        @($r.items).Count | Should Be 100
        $r.itemsCut | Should Be $true
    }

    It 'says nothing of a cut when every item is shown' {
        $script:probed = New-Object FakeProbe.Comp -Property @{ Size = 3 }
        $r = Invoke-ProbeTool ([pscustomobject]@{ object_path = 'x'; member = 'Units' })
        @($r.items).Count | Should Be 3
        $r.Contains('itemsCut') | Should Be $false
    }
}
