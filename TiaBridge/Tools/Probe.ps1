# Tools\Probe.ps1 - read-only reflection on a live Openness object: closes [GAP] items without a script.
# It reads properties, attributes, what the object describes of itself (attribute, composition, creation, invocation
# and service infos) and which services it gives, and lists methods. It never creates, imports, writes or invokes
# anything, also where the descriptions offer it. One object a call: nothing is followed, so no cycle can be walked.

# object_path: tia | project | library | plc[:device] | hmi[:device] | <kind>:<name>  (kinds of list/export)
# Device: the PLC or HMI device of a project with several; a name in the path (plc:<device>) goes first.
function Resolve-ProbeRoot([string]$Path, [string]$Device = '') {
    $head, $rest = $Path -split ':', 2
    switch ($head) {
        'tia' { Get-TiaProject | Out-Null; return $script:Bridge.portal }
        'project' { return Get-TiaProject }
        'library' { return (Get-TiaProject).ProjectLibrary }
        'plc' { return Get-TiaSoftware 'plc' $(if ($rest) { [string]$rest } else { $Device }) }
        'hmi' { return Get-TiaSoftware 'hmi' $(if ($rest) { [string]$rest } else { $Device }) }
    }
    $k = Get-ObjectKind $head
    if (-not $rest) { throw "object_path '$Path': give a name after '$($head):'." }
    $e = @(Get-KindItems $k (Get-KindRoot $k $Device)) | Where-Object { $_.name -eq $rest } | Select-Object -First 1
    if (-not $e) { throw "No $head named '$rest'." }
    $e.obj
}

# member: dotted property path, items by index: 'ProjectLibrary.TypeFolder.Types[0].Versions'
function Resolve-ProbeMember($Obj, [string]$Member) {
    foreach ($seg in ($Member -split '\.' | Where-Object { $_ })) {
        if ($seg -match '^(\w*)\[(\d+)\]$') {
            if ($Matches[1]) { $Obj = $Obj.($Matches[1]) }
            $Obj = @($Obj)[[int]$Matches[2]]
        } else { $Obj = $Obj.$seg }
        if ($null -eq $Obj) { throw "Member '$seg' of '$Member' is null." }
    }
    # the comma keeps a collection whole: unrolled, an empty one came back as null (2026-10-06, Dependencies of a
    # type that contains none) and a full one as Object[]
    , $Obj
}

function Format-ProbeValue($V) {
    if ($null -eq $V) { return $null }
    if ($V -is [string] -or $V -is [ValueType] -or $V -is [version]) { return [string]$V }
    if ($V -is [System.IO.FileSystemInfo]) { return $V.FullName }
    $p = $V.PSObject.Properties
    # library type versions have no Name: show the type and the number (dependencies of a type)
    if ($p['VersionNumber'] -and $p['TypeObject']) { return "<$($V.TypeObject.Name) V $($V.VersionNumber) $($V.State)>" }
    if ($p['LibraryTypeInstance']) { return "<instance $($V.LibraryTypeInstance.Name)>" }
    # a project language has no Name: show its culture (LanguageSettings.ActiveLanguages, 2026-10-06)
    if ($p['Culture'] -and $V.Culture -is [System.Globalization.CultureInfo]) { return "<$($V.GetType().Name) $($V.Culture.Name)>" }
    $n = $null; try { $n = $V.Name } catch { }
    if ($n) { "<$($V.GetType().Name) '$n'>" } else { "<$($V.GetType().FullName)>" }
}

function Get-EngineeringServiceTypes {
    if ($script:ProbeServiceTypes) { return $script:ProbeServiceTypes }
    $svcBase = [Siemens.Engineering.IEngineeringService]
    $script:ProbeServiceTypes = @(foreach ($asm in [AppDomain]::CurrentDomain.GetAssemblies() | Where-Object { $_.GetName().Name -like 'Siemens.Engineering*' }) {
        try { $types = $asm.GetExportedTypes() } catch [System.Reflection.ReflectionTypeLoadException] { $types = $_.Exception.Types | Where-Object { $_ } } catch { $types = @() }
        $types | Where-Object { ($_.IsInterface -or ($_.IsClass -and -not $_.IsAbstract)) -and $svcBase.IsAssignableFrom($_) -and $_ -ne $svcBase }
    })
    $script:ProbeServiceTypes
}

# Entry[Key] = the list Read gives, or Entry['<Key>Error'] = why it failed; an error that ended TIA goes up.
function Add-ProbeList($Entry, [string]$Key, [scriptblock]$Read) {
    try { $Entry[$Key] = @(& $Read) }
    catch {
        if (Test-TiaEndedError $_) { throw }
        $Entry["${Key}Error"] = (ConvertTo-BridgeError $_).message
    }
}

# What a composition can create (EngineeringCreationInfo): the type and its parameters. Read only: nothing is created.
function ConvertFrom-ProbeCreationInfos($Infos) {
    foreach ($c in $Infos) {
        [ordered]@{ type = $c.Type.FullName
                    parameters = @(foreach ($p in $c.ParameterInfos) { [ordered]@{ name = $p.Name; mandatory = [bool]$p.IsMandatory } }) }
    }
}

# What an object or a composition can do (EngineeringInvocationInfo): the action and its parameters. Nothing is invoked.
function ConvertFrom-ProbeInvocationInfos($Infos) {
    foreach ($i in $Infos) {
        [ordered]@{ name = $i.Name
                    parameters = @(foreach ($p in $i.ParameterInfos) { [ordered]@{ name = $p.Name; type = $(if ($p.Type) { $p.Type.FullName }) } }) }
    }
}

# The services of an object, each with advertised (GetServiceInfos names it) and state: available (GetService gives
# one), null, or failed (GetService threw, with its error). Listed: every one advertised, available or failed; the other
# candidates answered null unadvertised and are counted in servicesNull. A GetServiceInfos that fails is named in
# serviceInfosError, and every candidate is still tried.
function Read-ProbeServices($Obj, $Result) {
    $advertised = @()
    try { $advertised = @($Obj.GetServiceInfos() | ForEach-Object { $_.Type } | Where-Object { $_ }) }
    catch {
        if (Test-TiaEndedError $_) { throw }
        $Result.serviceInfosError = (ConvertTo-BridgeError $_).message
    }
    $isAdvertised = @{ }
    foreach ($t in $advertised) { $isAdvertised[$t.FullName] = $true }
    $seen = @{ }
    $candidates = @(foreach ($t in @(Get-EngineeringServiceTypes) + $advertised) { if (-not $seen[$t.FullName]) { $seen[$t.FullName] = $true; $t } })
    $nulls = 0
    $Result.services = @(foreach ($svc in $candidates) {
        $e = [ordered]@{ type = $svc.FullName; advertised = [bool]$isAdvertised[$svc.FullName] }
        try { $e.state = $(if (Get-TiaService $Obj $svc) { 'available' } else { 'null' }) }
        catch {
            if (Test-TiaEndedError $_) { throw }
            $e.state = 'failed'; $e.error = (ConvertTo-BridgeError $_).message
        }
        if ($e.state -eq 'null' -and -not $e.advertised) { $nulls++; continue }
        $e
    })
    $Result.servicesNull = $nulls
}

# The items of a collection shown; count counts them all.
$script:ProbeItemsShown = 100

# What Obj gives and says of itself, read only (the head of this file). Each part that fails is named beside it, an
# error that ended TIA goes up. Research scripts call it on objects no object_path reaches (a software unit).
function Read-ProbeObject($obj) {
    $t = $obj.GetType()
    $r = [ordered]@{ type = $t.FullName }
    # what the type inherits and implements: a member the methods below lack may be declared there (an explicit interface
    # implementation, as IEngineeringObject's on Openness classes); Siemens' Private interfaces are left out
    $r.bases = @(for ($b = $t.BaseType; $b -and $b -ne [object]; $b = $b.BaseType) { $b.ToString() })
    $r.interfaces = @($t.GetInterfaces() | Where-Object { $_.IsPublic -and $_.Namespace -notlike 'Siemens.Engineering.Private*' } | ForEach-Object { $_.ToString() } | Sort-Object)

    $r.properties = @(foreach ($p in $t.GetProperties() | Where-Object { $_.GetIndexParameters().Count -eq 0 } | Sort-Object Name) {
        $entry = [ordered]@{ name = $p.Name; type = $p.PropertyType.Name }
        # by reflection: PowerShell 5.1 answers a getter that throws with null and no error
        try { $entry.value = Format-ProbeValue ($p.GetValue($obj.PSObject.BaseObject, $null)) }
        catch {
            if (Test-TiaEndedError $_) { throw }
            $entry.error = (ConvertTo-BridgeError $_).message
        }
        $entry
    })
    if ($obj -is [Siemens.Engineering.IEngineeringObject]) {
        $r.attributes = @(foreach ($info in $obj.GetAttributeInfos()) {
            $entry = [ordered]@{ name = $info.Name; access = [string]$info.AccessMode }
            try {
                $entry.createRelevance = [string]$info.CreateRelevance
                $entry.supportedTypes = @($info.SupportedTypes | ForEach-Object { $_.FullName })
            } catch {
                if (Test-TiaEndedError $_) { throw }
                $entry.infoError = (ConvertTo-BridgeError $_).message
            }
            try { $entry.value = Format-ProbeValue ($obj.GetAttribute($info.Name)) }
            catch {
                if (Test-TiaEndedError $_) { throw }
                $entry.error = (ConvertTo-BridgeError $_).message
            }
            $entry
        })
        $r.compositions = @(foreach ($ci in $obj.GetCompositionInfos()) {
            $c = [ordered]@{ name = $ci.Name }
            Add-ProbeList $c 'creations' { ConvertFrom-ProbeCreationInfos ($obj.GetCreationInfos($ci.Name)) }
            $c
        })
        Add-ProbeList $r 'invocations' { ConvertFrom-ProbeInvocationInfos $obj.GetInvocationInfos() }
    }
    $signature = { "$($_.Name)(" + (($_.GetParameters() | ForEach-Object { "$($_.ParameterType.Name) $($_.Name)" }) -join ', ') + ") : $($_.ReturnType.Name)" }
    $r.methods = @($t.GetMethods() | Where-Object { -not $_.IsSpecialName -and $_.DeclaringType -ne [object] } | ForEach-Object $signature | Sort-Object -Unique)
    # an interface's methods under its name: an Openness class implements IEngineeringObject's out of sight
    $r.methods += @(foreach ($i in $t.GetInterfaces() | Where-Object { $_.IsPublic -and $_.Namespace -notlike 'Siemens.Engineering.Private*' }) {
        $i.GetMethods() | Where-Object { -not $_.IsSpecialName } | ForEach-Object { "$($i.Name).$(& $signature)" }
    }) | Sort-Object -Unique
    if ($obj -is [Siemens.Engineering.IEngineeringServiceProvider]) {
        Read-ProbeServices $obj $r
    }
    if ($obj -is [Siemens.Engineering.IEngineeringComposition]) {
        Add-ProbeList $r 'creations' { ConvertFrom-ProbeCreationInfos $obj.GetCreationInfos() }
        Add-ProbeList $r 'invocations' { ConvertFrom-ProbeInvocationInfos $obj.GetInvocationInfos() }
    }
    if ($obj -is [System.Collections.IEnumerable] -and $obj -isnot [string]) {
        $all = @($obj)
        $r.count = $all.Count
        $r.items = @($all | Select-Object -First $script:ProbeItemsShown | ForEach-Object { Format-ProbeValue $_ })
        if ($all.Count -gt $script:ProbeItemsShown) { $r.itemsCut = $true }
    }
    $r
}

function Invoke-ProbeTool($a) {
    $path = [string]$a.object_path
    if (-not $path) { return New-Refusal 'object_path is required.' }
    $obj = Resolve-ProbeRoot $path ([string]$a.device)
    if ($a.member) { $obj = Resolve-ProbeMember $obj ([string]$a.member) }
    $r = [ordered]@{ ok = $true; objectPath = $path; member = [string]$a.member }
    $read = Read-ProbeObject $obj
    foreach ($k in $read.Keys) { $r[$k] = $read[$k] }
    $r
}

function Register-ProbeTool {
    Register-McpTool -Name 'probe' -Handler { param($a) Invoke-ProbeTool $a } -Description (
        'Read-only reflection on a live Openness object: properties with values, attributes (GetAttributeInfos, with create relevance and supported types), ' +
        'compositions with the types each can create, actions with their parameters, base types and public interfaces, methods, services (each advertised or not, ' +
        'and available, null or failed), items of a collection (the first 100, all counted). It creates, writes and invokes nothing. object_path: tia, project, library, plc[:device], hmi[:device], or <kind>:<name> (e.g. block:MyBlock, hmi_screen:MyScreen; device names the PLC or HMI device when the project has several). ' +
        'member: dotted property path with [i] for items, e.g. TypeFolder.Types[0].Versions. Record what you find in the project''s docs\project.md with [PROBE].') -Schema @{
        type = 'object'; required = @('object_path')
        properties = @{ object_path = @{ type = 'string' }; member = @{ type = 'string' }
                        device = @{ type = 'string'; description = 'PLC or HMI device name; needed only when the project has several' } } }
}
