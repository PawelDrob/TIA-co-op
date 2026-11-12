# Tools\Probe.ps1 - read-only reflection on a live Openness object: closes [GAP] items without a script.
# It reads properties and attributes and lists methods and services; it never calls a method.

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

function Invoke-ProbeTool($a) {
    $path = [string]$a.object_path
    if (-not $path) { return New-Refusal 'object_path is required.' }
    $obj = Resolve-ProbeRoot $path ([string]$a.device)
    if ($a.member) { $obj = Resolve-ProbeMember $obj ([string]$a.member) }
    $t = $obj.GetType()
    $r = [ordered]@{ ok = $true; objectPath = $path; member = [string]$a.member; type = $t.FullName }

    $r.properties = @(foreach ($p in $t.GetProperties() | Where-Object { $_.GetIndexParameters().Count -eq 0 } | Sort-Object Name) {
        $entry = [ordered]@{ name = $p.Name; type = $p.PropertyType.Name }
        try { $entry.value = Format-ProbeValue ($obj.($p.Name)) } catch { $entry.error = (ConvertTo-BridgeError $_).message }
        $entry
    })
    if ($obj -is [Siemens.Engineering.IEngineeringObject]) {
        $r.attributes = @(foreach ($info in $obj.GetAttributeInfos()) {
            $entry = [ordered]@{ name = $info.Name; access = [string]$info.AccessMode }
            try { $entry.value = Format-ProbeValue ($obj.GetAttribute($info.Name)) }
            catch {
                if (Test-TiaEndedError $_) { throw }
                $entry.error = (ConvertTo-BridgeError $_).message
            }
            $entry
        })
        $r.compositions = @($obj.GetCompositionInfos() | ForEach-Object { $_.Name })
        $r.invocations = @($obj.GetInvocationInfos() | ForEach-Object { $_.Name })
    }
    $r.methods = @($t.GetMethods() | Where-Object { -not $_.IsSpecialName -and $_.DeclaringType -ne [object] } | ForEach-Object {
        "$($_.Name)(" + (($_.GetParameters() | ForEach-Object { "$($_.ParameterType.Name) $($_.Name)" }) -join ', ') + ") : $($_.ReturnType.Name)"
    } | Sort-Object -Unique)
    if ($obj -is [Siemens.Engineering.IEngineeringServiceProvider]) {
        $r.services = @(foreach ($svc in Get-EngineeringServiceTypes) {
            try { if (Get-TiaService $obj $svc) { $svc.FullName } } catch { }
        })
    }
    if ($obj -is [System.Collections.IEnumerable] -and $obj -isnot [string]) {
        $all = @($obj)
        $r.count = $all.Count
        $r.items = @($all | Select-Object -First 100 | ForEach-Object { Format-ProbeValue $_ })
    }
    $r
}

function Register-ProbeTool {
    Register-McpTool -Name 'probe' -Handler { param($a) Invoke-ProbeTool $a } -Description (
        'Read-only reflection on a live Openness object: properties with values, attributes (GetAttributeInfos), compositions, methods, services, items of a ' +
        'collection. object_path: tia, project, library, plc[:device], hmi[:device], or <kind>:<name> (e.g. block:MyBlock, hmi_screen:MyScreen; device names the PLC or HMI device when the project has several). ' +
        'member: dotted property path with [i] for items, e.g. TypeFolder.Types[0].Versions. Record what you find in the project''s docs\project.md with [PROBE].') -Schema @{
        type = 'object'; required = @('object_path')
        properties = @{ object_path = @{ type = 'string' }; member = @{ type = 'string' }
                        device = @{ type = 'string'; description = 'PLC or HMI device name; needed only when the project has several' } } }
}
