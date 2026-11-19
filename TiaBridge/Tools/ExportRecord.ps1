# Tools\ExportRecord.ps1 - full_export skips the blocks, DBs, PLC data types and PLC tag tables TIA says it has not changed
# since the last export (decided 2026-11-17). After an export the record (.tiabridge-export.json at the top of the project
# repo, ignored by git) holds, per object, what TIA said of it and the files its export left. The next full_export reads
# the same of TIA and exports an object when anything differs; everything else of those kinds is skipped and counted.
# What it rests on: docs\agent\openness-v20.md, Dates [PROBE]; what was not tried (block properties edited in TIA's
# dialogs): the README.
#
# Each entry stands on its own: the same values in TIA and the same file bytes mean its files are what an export gives
# now, whenever the entry was written. The head binds the record as a whole (project, TIA version, languages, PLC
# devices, the bridge's own code): any of it different, and everything is exported.

$script:ExportRecordForm = 1

# The kinds that skip; every other kind exports as before: HMI has no signal, and the rest is not probed yet.
$script:SkipKinds = @('block', 'db', 'type', 'plc_tag_table')

# What is read of each object and compared for unequal, never for newer: a project closed without saving after an import
# reads older dates. An attribute an object does not have reads $null and is left out. The dates: what each edit moves
# [PROBE] (2026-10-08). The rest is written into its file (the header: S7_Author, S7_Family, S7_UserDefinedId, S7_Version,
# S7_IECCheck, S7_GenerateENOforSCL), and whether editing it in TIA moves a date is not probed: Openness cannot set it.
# IsIECCheckEnabled and SetENOAutomatically have no .NET property; all of them are read in one call (Read-TiaAttributeValues).
$script:BlockHeaderAttributes = @('HeaderAuthor', 'HeaderFamily', 'HeaderName', 'HeaderVersion', 'IsIECCheckEnabled', 'SetENOAutomatically', 'Namespace')
$script:ExportStateAttributes = @{
    block = @('ModifiedDate', 'CodeModifiedDate', 'InterfaceModifiedDate', 'ParameterModified', 'StructureModified', 'CompileDate', 'CreationDate',
              'IsConsistent', 'Number', 'ProgrammingLanguage', 'MemoryLayout', 'IsKnowHowProtected') + $script:BlockHeaderAttributes
    db = @('ModifiedDate', 'CodeModifiedDate', 'InterfaceModifiedDate', 'ParameterModified', 'StructureModified', 'CompileDate', 'CreationDate',
           'IsConsistent', 'Number', 'MemoryLayout', 'IsKnowHowProtected', 'InstanceOfName') + $script:BlockHeaderAttributes
    type = @('ModifiedDate', 'CodeModifiedDate', 'InterfaceModifiedDate', 'ParameterModified', 'StructureModified', 'CompileDate', 'CreationDate',
             'IsConsistent', 'IsKnowHowProtected') + $script:BlockHeaderAttributes
    plc_tag_table = @('ModifiedTimeStamp')
}
# An object that reads none of these has no signal: it is exported.
$script:ExportSignalAttributes = @('ModifiedDate', 'ModifiedTimeStamp')

# The version of the Openness TIA runs (Siemens.Engineering.dll, as TIA's own: 2000.7.201.2 is V20 Update 7); '' unread.
function Get-TiaVersionText {
    try { [System.Diagnostics.FileVersionInfo]::GetVersionInfo([Siemens.Engineering.TiaPortal].Assembly.Location).FileVersion } catch { '' }
}

# A hash of the bridge's code (TiaBridge\*.ps1 and Tools\*.ps1): a bridge that may export other files than the record's
# does not use it. Any change counts; one full export after an update costs less than a guess.
function Get-BridgeCodeHash {
    if (-not $script:BridgeCodeHash) {
        $root = Split-Path -Parent $PSScriptRoot
        $files = @(@(Get-ChildItem -LiteralPath $root -Filter *.ps1 -File) + @(Get-ChildItem -LiteralPath (Join-Path $root 'Tools') -Filter *.ps1 -File) | Sort-Object Name)
        $script:BridgeCodeHash = Get-Sha256Text ([System.Text.Encoding]::ASCII.GetBytes((@($files | ForEach-Object { "$($_.Name)=$(Get-FileSha256 $_.FullName)" }) -join "`n")))
    }
    $script:BridgeCodeHash
}

function Get-Sha256Text([byte[]]$Bytes) {
    $sha = [System.Security.Cryptography.SHA256]::Create()
    try { [BitConverter]::ToString($sha.ComputeHash($Bytes)).Replace('-', '') }
    finally { $sha.Dispose() }
}

function Get-FileSha256([string]$Path) { Get-Sha256Text ([System.IO.File]::ReadAllBytes($Path)) }

# The project's languages: the reference language, then the active ones. A new language changes every block's .s7res.
function Get-ProjectLanguageText($Project) {
    try {
        $ls = $Project.LanguageSettings
        "$($ls.ReferenceLanguage.Culture.Name)|$(@($ls.ActiveLanguages | ForEach-Object { $_.Culture.Name } | Sort-Object) -join ',')"
    } catch { if (Test-TiaEndedError $_) { throw }; '' }
}

# What binds a record to the project and the bridge: compared field by field (Get-HeadDifference).
function Get-ExportRecordHead($Software, $Project) {
    $path = if ($script:Bridge.background) { [string]$script:Bridge.background.source } else { [string]$script:Bridge.projectPath }
    [ordered]@{
        form = $script:ExportRecordForm
        project = $path
        tia = [string](Get-TiaVersionText)
        languages = Get-ProjectLanguageText $Project
        plcs = (@($Software | Where-Object { $_.kind -eq 'plc' } | ForEach-Object { [string]$_.device } | Sort-Object) -join '|')
        bridge = Get-BridgeCodeHash
    }
}

# Why a record with head Old cannot be used now (New), or $null.
function Get-HeadDifference($Old, $New) {
    if ([string]$Old.form -ne [string]$New.form) { return "the record is of another form ($($Old.form))" }
    if (-not [string]::Equals([string]$Old.project, [string]$New.project, [StringComparison]::OrdinalIgnoreCase)) { return "the record is of another project ($($Old.project))" }
    if (-not $New.tia) { return 'the version of TIA cannot be read' }
    if ([string]$Old.tia -cne $New.tia) { return "the record was written by TIA $($Old.tia), this is $($New.tia)" }
    if ([string]$Old.languages -cne $New.languages) { return "the project's languages changed ($($Old.languages) -> $($New.languages))" }
    if ([string]$Old.plcs -cne $New.plcs) { return "the PLC devices differ from the record's ($($Old.plcs) -> $($New.plcs))" }
    if ([string]$Old.bridge -cne $New.bridge) { return "the bridge's code changed since the record was written" }
    $null
}

# The record of Repo -> @{ record; error }; record $null when there is none or it does not read.
function Read-ExportRecord([string]$Repo) {
    $p = Join-Path $Repo $script:ExportRecordName
    if (-not (Test-Path -LiteralPath $p)) { return @{ record = $null; error = 'no record yet: the first export of it' } }
    try {
        $r = [System.IO.File]::ReadAllText($p, [System.Text.Encoding]::UTF8) | ConvertFrom-Json
        if (-not $r.head -or -not $r.devices) { throw 'head or devices missing' }
        @{ record = $r; error = $null }
    }
    catch { @{ record = $null; error = "the record does not read ($($_.Exception.Message))" } }
}

# One property of a .NET object -> @{ has; value }; throws what its getter throws. PowerShell's $Obj.$Name returns $null
# for a getter that throws, as for a property the object does not have, and an attribute TIA refuses would read as one
# it does not offer. An object of PowerShell's own (a test's) is read as PowerShell reads it.
$script:PropertyInfos = @{}
function Read-ObjectProperty($Obj, [string]$Name) {
    $t = $Obj.GetType()
    if ($t -eq [System.Management.Automation.PSCustomObject]) {
        $p = $Obj.PSObject.Properties[$Name]
        return @{ has = [bool]$p; value = $(if ($p) { $p.Value }) }
    }
    $key = "$($t.FullName)|$Name"
    if (-not $script:PropertyInfos.ContainsKey($key)) {
        # the most derived one, where a class hides its base's property of the name
        $script:PropertyInfos[$key] = @($t.GetProperties() | Where-Object { $_.Name -eq $Name -and $_.CanRead -and -not $_.GetIndexParameters().Count })[0]
    }
    $pi = $script:PropertyInfos[$key]
    if (-not $pi) { return @{ has = $false; value = $null } }
    try { @{ has = $true; value = $pi.GetValue($Obj) } }
    catch [System.Reflection.TargetInvocationException] { throw $_.Exception.InnerException }
}

# Attributes with no .NET property, which only GetAttribute reads [PROBE] (2026-11-18, V20 Update 7): an FB, FC or OB
# names both in GetAttributeInfos, an F-block only IsIECCheckEnabled, a global DB and a data type neither (GetAttribute
# throws "not supported" there). Their values are S7_IECCheck and S7_GenerateENOforSCL of the block's file.
$script:GetAttributeOnly = @('IsIECCheckEnabled', 'SetENOAutomatically')
function Read-TiaAttribute($Obj, [string]$Name) {
    $step = [TiaBridgeTimes]::Enter('tia_attribute')
    try {
        if (-not $Obj.PSObject.Methods['GetAttributeInfos']) { return @{ has = $false; value = $null } }
        if (@($Obj.GetAttributeInfos() | ForEach-Object { [string]$_.Name }) -notcontains $Name) { return @{ has = $false; value = $null } }
        @{ has = $true; value = $Obj.GetAttribute($Name) }
    }
    finally { [TiaBridgeTimes]::Exit($step) }
}

# The values of Names of Obj, read in one call into TIA (IEngineeringObject.GetAttributes) -> name -> value, for the names
# Obj offers; $null when Obj has no GetAttributes (an object of PowerShell's own, a test's) or the read failed otherwise,
# and the caller reads the names one at a time. GetAttributes refuses the whole call when the object lacks one of the
# names (EngineeringNotSupportedException), not nulls as its documentation says: every DB and data type and the F-blocks
# among them [PROBE] (2026-11-19, docs\agent\openness-v20.md, GetAttributes). Then GetAttributeInfos says which names the
# object offers, and those are read in a second call. Kind: when the last object of it lacked a name, the next one asks
# GetAttributeInfos first, which saves the refused call; one that offered them all turns that back.
function Read-TiaAttributeValues($Obj, [string[]]$Names, [string]$Kind) {
    if (-not $Obj.PSObject.Methods['GetAttributes']) { return $null }
    try {
        if (-not $script:AttributeInfosFirst[$Kind]) {
            try { return ConvertTo-AttributeMap $Names $Obj.GetAttributes([System.Collections.Generic.IEnumerable[string]]$Names) }
            catch { if (Test-TiaEndedError $_) { throw } }
        }
        $step = [TiaBridgeTimes]::Enter('tia_attribute')
        try { $offered = @($Obj.GetAttributeInfos() | ForEach-Object { [string]$_.Name }) }
        finally { [TiaBridgeTimes]::Exit($step) }
        $asked = [string[]]@($Names | Where-Object { $offered -contains $_ })
        $script:AttributeInfosFirst[$Kind] = $asked.Count -lt $Names.Count
        if (-not $asked.Count) { return [ordered]@{} }
        ConvertTo-AttributeMap $asked $Obj.GetAttributes([System.Collections.Generic.IEnumerable[string]]$asked)
    }
    catch { if (Test-TiaEndedError $_) { throw }; $null }
}

function ConvertTo-AttributeMap([string[]]$Names, $Values) {
    $m = [ordered]@{}
    for ($i = 0; $i -lt $Names.Count; $i++) { $m[$Names[$i]] = $Values[$i] }
    $m
}

# A plan starts with no knowledge of which kinds lack names (Read-TiaAttributeValues).
function Reset-AttributeInfosFirst { $script:AttributeInfosFirst = @{} }
Reset-AttributeInfosFirst

# The values of an object compared for unequal: name -> text, the dates in round trip form ('o', with their Kind).
function Read-ExportState($Kind, $Entry) {
    $step = [TiaBridgeTimes]::Enter('tia_state')
    try { Read-ExportStateValues $Kind $Entry }
    finally { [TiaBridgeTimes]::Exit($step) }
}

# Each value from the one call (Read-TiaAttributeValues), when it gave one. Every other name is read on its own, as a .NET
# property, or through GetAttribute where it has none and the object offers it: a name the call did not answer (the
# object does not offer it, which then gives nothing), a name it answered null, and every name when the call failed. So a
# value whose getter throws is named (unread) and the object exported, whether TIA refuses the call for it or answers
# null: which of the two TIA does is not probed, as no object of the copies had such a getter (ticket 364).
function Read-ExportStateValues($Kind, $Entry) {
    $names = [string[]]$script:ExportStateAttributes[$Kind.name]
    $got = Read-TiaAttributeValues $Entry.obj $names $Kind.name
    $s = [ordered]@{}
    foreach ($a in $names) {
        try {
            $answered = $null -ne $got -and $got.Contains($a)
            if ($answered -and $null -ne $got[$a]) { $v = $got[$a] }
            else {
                $r = Read-ObjectProperty $Entry.obj $a
                if (-not $r.has -and ($null -eq $got -or $answered) -and $script:GetAttributeOnly -contains $a) { $r = Read-TiaAttribute $Entry.obj $a }
                $v = $r.value
            }
        }
        catch {
            if (Test-TiaEndedError $_) { throw }
            $s[$a] = "unread: $($_.Exception.Message)"; $s.unread = 'true'; continue
        }
        if ($null -eq $v) { continue }
        $s[$a] = $(if ($v -is [datetime]) { $v.ToString('o') } else { [string]$v })
    }
    $s
}

# A state (from TIA, or read back from the record) as one text: equal text, equal values.
function Get-StateText($State) {
    if ($null -eq $State) { return '' }
    $pairs = if ($State -is [System.Collections.IDictionary]) { @($State.Keys | ForEach-Object { "$_=$($State[$_])" }) }
             else { @($State.PSObject.Properties | ForEach-Object { "$($_.Name)=$($_.Value)" }) }
    (@($pairs | Sort-Object) -join "`n")
}

function Get-StateValue($State, [string]$Name) {
    if ($null -eq $State) { return $null }
    if ($State -is [System.Collections.IDictionary]) { $State[$Name] } else { $State.$Name }
}

# The entries of one PLC of the record -> key -> entry, keys with case; $null when the record has none of it. Read once:
# a property of a parsed object with thousands of them costs a search of them all (4 s for 5000 lookups).
function ConvertTo-EntryMap($Device) {
    if ($null -eq $Device) { return $null }
    $m = New-Object System.Collections.Hashtable ([StringComparer]::Ordinal)
    foreach ($p in $Device.PSObject.Properties) { $m[$p.Name] = $p.Value }
    , $m
}

# The files of a record entry: repo-relative path -> SHA-256.
function Get-EntryFiles($Old) {
    $h = [ordered]@{}
    if ($Old -and $Old.files) { foreach ($p in $Old.files.PSObject.Properties) { $h[$p.Name] = [string]$p.Value } }
    $h
}

# Why the files in the repo are not those the last export left (Old: record entry), or $null. Base: the object's path
# without extension; with Others, the files of the other formats there too (an export of a block removes them).
function Get-FileDifference($Old, [string]$Base, [switch]$Others) {
    $step = [TiaBridgeTimes]::Enter('record_files')
    try { Get-EntryFileDifference $Old $Base -Others:$Others }
    finally { [TiaBridgeTimes]::Exit($step) }
}

function Get-EntryFileDifference($Old, [string]$Base, [switch]$Others) {
    $files = Get-EntryFiles $Old
    # an export TIA answered Success without writing a file of it (Export-PlcObject: ok, no files) is recorded with none
    if (-not $files.Count) { return 'the record holds no file of it' }
    $mine = @{}
    foreach ($rel in $files.Keys) {
        $full = Join-Path $script:Bridge.repo $rel
        $mine[[System.IO.Path]::GetFullPath($full).ToLowerInvariant()] = $true
        if (-not [System.IO.File]::Exists($full)) { return "$rel is gone from the repo" }
        if ((Get-FileSha256 $full) -ne $files[$rel]) { return "$rel was changed in the repo" }
    }
    if ($Others) {
        foreach ($x in '.s7dcl', '.s7res', '.xml') {
            $f = "$Base$x"
            if ([System.IO.File]::Exists($f) -and -not $mine[[System.IO.Path]::GetFullPath($f).ToLowerInvariant()]) { return "$(Get-RepoRelative $f) was added beside it" }
        }
    }
    $null
}

# Why an object is exported although its PLC skips (Old: its record entry; State: read now), or $null to skip it.
function Get-ObjectExportReason($Kind, $Entry, $State, $Old, [string]$Device) {
    # cannot be reached: a PLC with an object the record lacks exports whole (Get-PlcExportReason)
    if (-not $Old) { return 'not in the record' }
    if ($Old.failed) { return 'its last export failed' }
    if ($State.unread) { return 'a value of it does not read' }
    if (-not @($script:ExportSignalAttributes | Where-Object { $State.Contains($_) }).Count) { return 'TIA gives no date of it' }
    if ((Get-StateText $State) -cne (Get-StateText $Old.state)) { return 'changed in TIA' }
    if ([string]$Old.folder -cne [string]$Entry.folder) { return 'moved to another folder' }
    if ($State.IsConsistent -eq 'False') { return 'not consistent' }
    $base = Join-Path (Get-KindDir $Kind $Entry.folder '' $Device) (ConvertTo-SafeFileName $Entry.name)
    $files = Get-FileDifference $Old $base -Others:($Kind.name -ne 'plc_tag_table')
    if ($files) { return $files }
    $null
}

# Why a tag table's export now differs from its file in the repo, or $null. Its date is no signal: a tag renamed through
# Openness moved no date of the table, and the table's file changed [PROBE] (2026-11-17, V20 Update 7). So the table
# is exported once to a temporary file and compared as an export compares (Test-OnlyExportTimeDiffers); tables are few.
# When the compare cannot be made, it differs.
function Get-TagTableDifference($Kind, $Entry, [string]$Device) {
    $file = Join-Path (Get-KindDir $Kind $Entry.folder '' $Device) "$(ConvertTo-SafeFileName $Entry.name).xml"
    if (-not [System.IO.File]::Exists($file)) { return 'its file is not in the repo' }
    $temp = Join-Path ([System.IO.Path]::GetTempPath()) "tiabridge-$PID-$([guid]::NewGuid().ToString('N')).xml"
    try {
        $step = [TiaBridgeTimes]::Enter('tia_export_tag_table')
        try { $Entry.obj.Export([System.IO.FileInfo]::new($temp), (Get-PlcExportOptions $false)) }
        finally { [TiaBridgeTimes]::Exit($step) }
        if (Test-OnlyExportTimeDiffers $temp $file) { $null } else { 'its export differs from its file in the repo' }
    }
    catch {
        if (Test-TiaEndedError $_) { throw }
        "its export for the compare failed ($($_.Exception.Message))"
    }
    finally { Remove-Item -LiteralPath $temp -Force -ErrorAction SilentlyContinue }
}

# Why every object of a PLC is exported, or $null. Old: its record entries (ConvertTo-EntryMap); Objects: key -> @{ kind; entry;
# state }. A block names other blocks and tags in its code, and a renamed one moved no date of a block naming it until the
# compile rewrote that block [PROBE] (2026-11-17, docs\agent\openness-v20.md, Dates): an object added, deleted or renamed,
# or a tag table that exports differently, exports them all. So does a changed data type: its members and their defaults
# show in the DBs and blocks that use it, and only a member added was tried, which left its users not consistent. Names
# compare with case: a block renamed Fb1 -> FB1 is named so in its callers' files, and PowerShell's -contains and
# hashtables ignore case.
function Get-PlcExportReason([hashtable]$Old, [hashtable]$Objects) {
    $gone = @($Old.Keys | Where-Object { -not $Objects.ContainsKey($_) })
    $new = @($Objects.Keys | Where-Object { -not $Old.ContainsKey($_) })
    if ($gone.Count -or $new.Count) {
        $names = @(@($gone | ForEach-Object { "-$_" }) + @($new | ForEach-Object { "+$_" }) | Sort-Object)
        return "objects added, deleted or renamed ($(@($names | Select-Object -First 5) -join ', ')$(if ($names.Count -gt 5) { ', ...' }))"
    }
    foreach ($key in @($Objects.Keys | Sort-Object)) {
        $o = $Objects[$key]; $was = $Old[$key]
        $same = (Get-StateText $o.state) -ceq (Get-StateText $was.state)
        if ($o.kind -eq 'type' -and -not $same) { return "the data type $($o.entry.name) changed" }
        if ($o.kind -ne 'plc_tag_table') { continue }
        if (-not $same) { return "the tag table $($o.entry.name) changed" }
        if ($o.differs) { return "the tag table $($o.entry.name) changed: $($o.differs)" }
    }
    $null
}

# Why the objects of a PLC that were exported as SimaticML are exported, or $null: a block or DB of it changed in TIA. A block
# that calls or uses a changed block or DB turned not consistent, and the compile that rewrote it moved its own dates, so its
# own values say so [PROBE] (2026-11-17, docs\agent\openness-v20.md, Dates; blocks exported as SD). A block exported as
# SimaticML (an OB, a know-how protected block, one whose SD export TIA refused) holds the parameters and members of what it
# calls in its file; whether that file follows the other one before its own compile was not tried, so these few are exported.
function Get-SimaticMlReason([hashtable]$Old, [hashtable]$Objects) {
    foreach ($key in @($Objects.Keys | Sort-Object)) {
        $o = $Objects[$key]
        if ($o.kind -in 'block', 'db' -and (Get-StateText $o.state) -cne (Get-StateText $Old[$key].state)) { return "$($o.entry.name) changed in TIA" }
    }
    $null
}

# Reads what TIA says of the skipping kinds and decides, before the export, what it exports and why. Returns the plan:
# @{ all = why everything is exported, or $null; unusable = why the record cannot be used, or $null; head; old (record);
#    devices = device -> @{ all; entries = kind -> entries; objects = key -> @{ kind; entry; state; old; export = why, or $null } } }
# A key is '<kind>|<name>'. Full: everything is exported (full: true), the record is written all the same.
function Get-ExportPlan($Software, $Project, [bool]$Full) {
    $step = [TiaBridgeTimes]::Enter('record_read')
    try {
        $head = Get-ExportRecordHead $Software $Project
        $read = Read-ExportRecord $script:Bridge.repo
    }
    finally { [TiaBridgeTimes]::Exit($step) }
    $unusable = $read.error
    if (-not $unusable) { $unusable = Get-HeadDifference $read.record.head $head }
    $plan = @{ head = $head; old = $read.record; unusable = $unusable; all = $(if ($Full) { 'full: true' } else { $unusable }); devices = @{} }
    Reset-AttributeInfosFirst
    foreach ($s in @($Software | Where-Object { $_.kind -eq 'plc' })) {
        $device = [string]$s.device
        $d = @{ all = $null; entries = @{}; objects = (New-Object System.Collections.Hashtable ([StringComparer]::Ordinal)) }
        $plan.devices[$device] = $d
        $step = [TiaBridgeTimes]::Enter('record_read')
        try { $old = if (-not $unusable) { ConvertTo-EntryMap $read.record.devices.$device } }
        finally { [TiaBridgeTimes]::Exit($step) }
        foreach ($kn in $script:SkipKinds) {
            $k = Get-ObjectKind $kn
            $d.entries[$kn] = @(Get-KindItems $k $s.software)
            foreach ($e in $d.entries[$kn]) {
                $key = "$kn|$($e.name)"
                $o = @{ kind = $kn; entry = $e; state = (Read-ExportState $k $e); old = $(if ($null -ne $old) { $old[$key] }); export = $null }
                if ($kn -eq 'plc_tag_table' -and -not $plan.all -and $null -ne $old) { $o.differs = Get-TagTableDifference $k $e $device }
                $d.objects[$key] = $o
            }
        }
        # the compare with the record; the files' hashes in it are record_files
        $step = [TiaBridgeTimes]::Enter('record_compare')
        try {
            if ($plan.all) { $d.all = $plan.all }
            elseif ($null -eq $old) { $d.all = "the record holds nothing of $device" }
            else { $d.all = Get-PlcExportReason $old $d.objects }
            $simaticMlWhy = if (-not $d.all) { Get-SimaticMlReason $old $d.objects }
            foreach ($o in @($d.objects.Values | Where-Object { $_.kind -ne 'db' }) + @($d.objects.Values | Where-Object { $_.kind -eq 'db' })) {
                $o.export = $(if ($d.all) { $d.all } else { Get-ObjectExportReason (Get-ObjectKind $o.kind) $o.entry $o.state $o.old $device })
                if (-not $o.export -and $simaticMlWhy -and $o.kind -ne 'plc_tag_table' -and @((Get-EntryFiles $o.old).Keys | Where-Object { $_ -like '*.xml' }).Count) {
                    $o.export = "$simaticMlWhy, and its SimaticML may show it"
                }
                # an instance DB's export holds its FB's interface
                if (-not $o.export -and $o.kind -eq 'db') {
                    $fb = Get-StateValue $o.state 'InstanceOfName'
                    $of = if ($fb) { $d.objects["block|$fb"] }
                    if ($of -and $of.export) { $o.export = "its FB $fb is exported" }
                }
            }
        }
        finally { [TiaBridgeTimes]::Exit($step) }
    }
    $plan
}

# The record entry of an object after its export: Item is the export's (files repo-relative); failed when it did not export.
function New-ExportRecordEntry($Object, $Item) {
    $step = [TiaBridgeTimes]::Enter('record')
    try {
        $e = [ordered]@{ folder = [string]$Object.entry.folder; state = $Object.state }
        if ($Item.ok) {
            $files = [ordered]@{}
            foreach ($f in @($Item.files | Where-Object { $_ })) { $files[$f] = Get-FileSha256 (Join-Path $script:Bridge.repo $f) }
            $e.files = $files
        } else { $e.failed = $true }
        $e
    }
    finally { [TiaBridgeTimes]::Exit($step) }
}

# Writes the record after an export that did not stop. A PLC's entries are one snapshot, taken by one run: the plan's
# values with the files of that run. A PLC whose four kind parts all ran and listed their objects gets the new snapshot;
# another keeps the one of the record, if usable, which still says what an export gave then (Get-PlcExportReason
# compares with it). Records: the part records of the run. Returns an error text, or $null.
function Save-ExportRecord($Plan, $Records) {
    $step = [TiaBridgeTimes]::Enter('record_save')
    try {
        $devices = [ordered]@{}
        if (-not $Plan.unusable) { foreach ($p in $Plan.old.devices.PSObject.Properties) { $devices[$p.Name] = $p.Value } }
        foreach ($device in $Plan.devices.Keys) {
            $complete = $true
            foreach ($kn in $script:SkipKinds) {
                $part = @($script:FullExportParts | Where-Object { $_.kind -eq $kn })[0].name
                $rec = @($Records | Where-Object { $_.part -eq $part -and $_.device -eq $device })[0]
                if (-not $rec -or $rec.listError) { $complete = $false }
            }
            if (-not $complete) { continue }
            $m = [ordered]@{}
            foreach ($key in @($Plan.devices[$device].objects.Keys | Sort-Object)) {
                $o = $Plan.devices[$device].objects[$key]
                # an object the run did not reach (a part stopped) has no entry: the snapshot is not whole
                if (-not $o.recorded) { $complete = $false; break }
                $m[$key] = $o.recorded
            }
            if ($complete) { $devices[$device] = $m } elseif ($devices.Contains($device)) { $devices.Remove($device) }
        }
        $r = [ordered]@{ head = $Plan.head; writtenAt = (Get-Date).ToString('yyyy-MM-ddTHH:mm:sszzz'); devices = $devices }
        Write-TextFileAtomic (Join-Path $script:Bridge.repo $script:ExportRecordName) (ConvertTo-Json -InputObject $r -Depth 8 -Compress)
        $null
    }
    catch { "The record of this export was not written; the next full_export goes by the one before, whose entries still hold for what they name: $($_.Exception.Message)" }
    finally { [TiaBridgeTimes]::Exit($step) }
}
