# Tools\Hmi.ps1 - WinCC Comfort/Advanced kinds for list/export/import/delete (Tools\Objects.ps1):
# hmi_screen, hmi_template, hmi_popup, hmi_tag_table, hmi_textlist, hmi_cycle, hmi_graphiclist, hmi_slidein,
# hmi_screen_global, hmi_vbscript, and the HMI kind the bridge only exports.
# All SimaticML; see docs/agent/wincc-comfort-openness.md.

function Get-HmiExportOptions([bool]$Full) {
    if ($Full) { [Siemens.Engineering.ExportOptions]::WithDefaults -bor [Siemens.Engineering.ExportOptions]::WithReadOnly }
    else { [Siemens.Engineering.ExportOptions]::None }   # minimal: only non-default attributes
}

function Get-AttributeOrNull($Obj, [string]$Name) { try { $Obj.GetAttribute($Name) } catch { $null } }

function Export-HmiObject($Entry, [string]$Dir, $Options) {
    $file = Join-Path $Dir "$(ConvertTo-SafeFileName $Entry.name).xml"
    Export-ObjectFile $Entry.obj $file (Get-HmiExportOptions ([bool]$Options.full))
    @{ ok = $true; format = 'xml'; files = @($file) }
}

# Screens, templates, pop-ups: the full export only (WithDefaults + WithReadOnly), whatever options.full says. A full
# export imports back unchanged (2026-10-06: read-only attributes included, 0 compile errors, export identical
# apart from the timestamp); the HMI preview draws and validates only what a document carries (decided 2026-10-06).
function Export-HmiFullObject($Entry, [string]$Dir) {
    $file = Join-Path $Dir "$(ConvertTo-SafeFileName $Entry.name).xml"
    Export-ObjectFile $Entry.obj $file (Get-HmiExportOptions $true)
    @{ ok = $true; format = 'xml'; files = @($file) }
}

# Faceplate guard (5.5): every FaceplateTypeName in the file must name a type version in the project library.
# Run as the kind's precheck, before the write: Cache holds the library types for every file of one import call.
function Test-HmiFaceplates($File, [hashtable]$Cache = @{}) {
    $refs = @(Get-FaceplateRefs $File.file)
    if (-not $refs.Count) { return $null }
    if (-not $Cache.ContainsKey('types')) { $Cache.types = @(Get-ProjectLibraryTypes) }
    $problems = @(Test-FaceplateRefs -Refs $refs -LibraryTypes $Cache.types)
    if (-not $problems.Count) { return $null }
    @{ ok = $false; refused = 'Faceplate type check failed (a wrong version crashed TIA on 2026-10-02).'; faceplates = $problems }
}

# ------------------------------------------------------------------ validator guard

# The hmipreview package (python -m hmipreview) sits in TiaHmiGenerator next to TiaBridge.
$script:HmiPreviewDir = [System.IO.Path]::GetFullPath((Join-Path $PSScriptRoot '..\..\TiaHmiGenerator'))
# It takes seconds; what takes longer than this hangs.
$script:HmiValidatorLimitMinutes = 10

# Runs `python -m hmipreview validate <repo> --json --import [--override] [--device <folder>]` and returns its
# findings (objects with severity, document, object, rule, message). Throws when the validator cannot run.
function Invoke-HmiValidator([string]$Repo, [bool]$OverrideStale, [string]$Device = '') {
    $missing = Get-PythonProblem
    if ($missing) { throw $missing }
    $psi = New-Object System.Diagnostics.ProcessStartInfo
    $psi.FileName = $script:PythonExe
    $psi.Arguments = "-X utf8 -m hmipreview validate `"$($Repo.TrimEnd('\'))`" --json --import"
    if ($OverrideStale) { $psi.Arguments += ' --override' }
    if ($Device) { $psi.Arguments += " --device `"$Device`"" }
    $psi.WorkingDirectory = $script:HmiPreviewDir
    $psi.UseShellExecute = $false
    $psi.CreateNoWindow = $true
    $psi.RedirectStandardOutput = $true
    $psi.RedirectStandardError = $true
    $psi.StandardOutputEncoding = [System.Text.Encoding]::UTF8
    $psi.StandardErrorEncoding = [System.Text.Encoding]::UTF8
    $psi.EnvironmentVariables['PYTHONIOENCODING'] = 'utf-8'
    try { $p = [System.Diagnostics.Process]::Start($psi) }
    catch { throw "python could not be started: $($_.Exception.Message) $($script:PythonSetup)" }
    $r = Wait-ToolProcess $p $script:HmiValidatorLimitMinutes 'python -m hmipreview validate'
    if ($r.exitCode -notin 0, 1) { throw "python -m hmipreview validate exited with $($r.exitCode): $($r.err.Trim())" }
    try { $list = $r.out | ConvertFrom-Json }
    catch { throw "python -m hmipreview validate printed no JSON: $($r.err.Trim())" }
    @($list | ForEach-Object { $_ })
}

# The HMI device folder of a document the validator checks: <device> of hmi\<device>\generated\... or of a document in an
# export folder it checks for an import (hmi\<device>\cycles\..., slideins, global), '' for hmi\generated\... and
# hmi\cycles\... (one HMI device) or a path outside the repo.
function Get-HmiDeviceFolder([string]$Repo, [string]$File) {
    $root = [System.IO.Path]::GetFullPath($Repo).TrimEnd('\') + '\'
    $full = [System.IO.Path]::GetFullPath($File)
    if (-not $full.StartsWith($root, [StringComparison]::OrdinalIgnoreCase)) { return '' }
    $parts = $full.Substring($root.Length) -split '\\'
    if ($parts.Count -ge 4 -and $parts[0] -eq 'hmi' -and $parts[1] -ne 'generated' -and $parts[2] -in 'generated', 'cycles', 'slideins', 'global') { return $parts[1] }
    ''
}

# Import guard of hmi_screen / hmi_template / hmi_popup / hmi_tag_table. Files: Resolve-ImportFiles entries, all of
# one HMI device (the import folder); the validator checks that device (--device).
# Returns @{ <file path> = @{ refused = <reason or $null>; findings = @(...) } }: errors on the file's own document
# and on repo-level files (tiabridge.json, planned.json, ...) refuse it; staleness is an error unless OverrideStale
# (the caller passed override true explicitly; the TIA Override default of screens does not count).
function Test-HmiImportGuard([string]$Repo, [object[]]$Files, [bool]$OverrideStale) {
    $result = @{}
    $device = if ($Files.Count) { Get-HmiDeviceFolder $Repo $Files[0].file } else { '' }
    try { $findings = @(Invoke-HmiValidator -Repo $Repo -OverrideStale $OverrideStale -Device $device) }
    catch {
        $reason = "The HMI validator could not run, so nothing is imported unchecked: $($_.Exception.Message)"
        foreach ($f in $Files) { $result[$f.file] = @{ refused = $reason; findings = @() } }
        return $result
    }
    $repoRoot = [System.IO.Path]::GetFullPath($Repo).TrimEnd('\') + '\'
    $repoLevel = @($findings | Where-Object { -not ([string]$_.document).EndsWith('.xml', [StringComparison]::OrdinalIgnoreCase) })
    foreach ($f in $Files) {
        $doc = $f.file
        if ($doc.StartsWith($repoRoot, [StringComparison]::OrdinalIgnoreCase)) { $doc = $doc.Substring($repoRoot.Length) }
        $doc = $doc.Replace('\', '/')
        $own = @($findings | Where-Object { [string]::Equals([string]$_.document, $doc, [StringComparison]::OrdinalIgnoreCase) }) + $repoLevel
        $list = @($own | ForEach-Object { [ordered]@{ severity = $_.severity; document = $_.document; object = $_.object; rule = $_.rule; message = $_.message } })
        $errors = @($list | Where-Object { $_.severity -eq 'error' })
        $reason = $null
        if ($errors.Count) {
            $rules = @($errors | ForEach-Object { $_.rule } | Sort-Object -Unique)
            $reason = "HMI validator: $($errors.Count) error(s) ($($rules -join ', ')); see findings. Fix the document or its generator, then import again."
            if ($rules -contains 'links.planned') { $reason += ' links.planned: a planned item is still open; build it in TIA and export it first.' }
            if ($rules -contains 'staleness.export-newer') { $reason += ' staleness.export-newer: the TIA export is newer than the generated document; regenerate it, or import with override true to overwrite the TIA edits.' }
        }
        $result[$f.file] = @{ refused = $reason; findings = $list }
    }
    $result
}

# The importGuard of the screen kinds (hmi_screen, hmi_template, hmi_popup), of hmi_tag_table (an Int tag with Length 1
# ended TIA on import: the validator's rules\tagtable.py), of hmi_cycle (rules\cycle.py) and of hmi_slidein and
# hmi_screen_global (rules\slidein.py, rules\globalscreen.py, rules\handbuilt.py).
$script:HmiImportGuard = { param($repo, $files, $a) Test-HmiImportGuard $repo $files (Get-OptionalBool $a 'override' $false) }

# The precheck of the HMI kinds: before the write, as the folder of a new object is made on the way into it. SimaticML
# only, and none TIA would refuse for how it is written (Get-XmlDocumentRefusal).
function Test-HmiFileFormat($File) {
    if ($File.format -ne 'xml') { return @{ ok = $false; refused = 'HMI objects are SimaticML (.xml) only.' } }
    $why = Get-XmlDocumentRefusal $File.file
    if ($why) { @{ ok = $false; refused = $why } }
}

# The object of a SimaticML for a kind whose composition takes one class of object only: @{ node } when it is of Class (such
# as Hmi.Globalization.MultiLingualGraphic, or one of several), else @{ refused }. What: the kind's objects in words, for
# the refusal.
function Read-HmiDocumentObject($File, [string[]]$Class, [string]$What) {
    $refusal = Test-HmiFileFormat $File
    if ($refusal) { return $refusal }
    try { $node = (Read-DocumentXml $File.file).SelectSingleNode($script:DocumentObjectsXPath) }
    catch { return @{ ok = $false; refused = "$($File.file) cannot be read as XML ($($_.Exception.GetBaseException().Message)); nothing imported." } }
    if (-not $node -or $node.Name -cnotin $Class) {
        $holds = if ($node) { $node.Name } else { 'no object' }
        return @{ ok = $false; refused = "$($File.file) holds $holds, no $What`: import it with its own kind." }
    }
    @{ node = $node }
}

function Test-HmiScreenFile($File, [hashtable]$Cache) {
    $refusal = Test-HmiFileFormat $File
    if ($refusal) { return $refusal }
    Test-HmiFaceplates $File $Cache
}

# ------------------------------------------------------------------ screen numbers

# A screen number is unique on the HMI device, and an import that would break that ends TIA [PROBE] (2026-11-12, V20
# Update 7): a new screen, or an override of one, whose number another screen has throws NonRecoverableException (The
# "screen number '2' for screen '...' is not unique for this device.). An override takes the document's number, so the
# number it had is free after it; a document without a number gets the lowest number no other screen has. Templates and
# pop-ups have no number.

# The number a screen document declares, $null for none. Throws for a document that cannot be read or a number that is no
# whole number: the guard cannot tell which screen it would clash with, and what TIA does with it was not tried.
function Get-ScreenDocumentNumber([string]$Path) {
    $node = (Read-DocumentXml $Path).SelectSingleNode('/Document/Hmi.Screen.Screen/AttributeList/Number')
    if (-not $node) { return $null }
    $n = 0
    if (-not [int]::TryParse($node.InnerText.Trim(), [ref]$n)) { throw "its number '$($node.InnerText)' is no whole number" }
    $n
}

# The device's screens in TIA by number: number -> name. Openness gives a screen its name only (get_Number is not
# supported), so each one is exported without defaults: 20-30 ms a screen, a full export up to 2 s; the number is left out
# when it is 1, the default [PROBE]. Throws, naming the screen, when one cannot be exported.
function Get-HmiScreenNumbers([object[]]$Entries) {
    $numbers = @{}
    $dir = Join-Path ([System.IO.Path]::GetTempPath()) "TiaBridge-$([guid]::NewGuid().ToString('N'))"
    try {
        $i = 0
        foreach ($e in $Entries) {
            $file = Join-Path $dir "$i.xml"; $i++
            try { Export-ObjectFile $e.obj $file (Get-HmiExportOptions $false); $n = Get-ScreenDocumentNumber $file }
            catch { throw "Screen '$($e.name)' could not be exported to read its number: $($_.Exception.Message)" }
            $numbers[$(if ($null -eq $n) { 1 } else { $n })] = $e.name
        }
    }
    finally { Remove-Item -LiteralPath $dir -Recurse -Force -ErrorAction SilentlyContinue }
    $numbers
}

# The screen-number guard of hmi_screen, in its precheck: the files of one call in order, as TIA imports them. Entries: the
# device's screens in TIA. Cache.screenNumbers starts as their numbers and takes each document checked, in place of the
# number its screen had; a document whose number another screen has is refused, naming that screen.
function Test-HmiScreenNumber($File, [hashtable]$Cache, [object[]]$Entries) {
    if (-not $Cache.ContainsKey('screenNumbers')) {
        $Cache.screenNumbers = @{}
        try { $live = Get-HmiScreenNumbers $Entries; foreach ($n in $live.Keys) { $Cache.screenNumbers[$n] = @{ name = $live[$n] } } }
        catch { $Cache.screenNumbersFailed = "The screens' numbers in TIA could not be read, so no screen is imported unchecked: $($_.Exception.Message)" }
    }
    if ($Cache.screenNumbersFailed) { return @{ ok = $false; refused = $Cache.screenNumbersFailed } }
    $taken = $Cache.screenNumbers
    $name = if ($File.objectName) { [string]$File.objectName } else { [string]$File.name }
    try { $n = Get-ScreenDocumentNumber $File.file }
    catch { return @{ ok = $false; refused = "Screen '$name': $($_.Exception.Message), so its number cannot be checked against the other screens of the device. Write the number as an export does." } }
    $holder = if ($null -ne $n) { $taken[$n] }
    if ($holder -and -not [string]::Equals($holder.name, $name, [StringComparison]::OrdinalIgnoreCase)) {
        $whose = if ($holder.path) { "screen '$($holder.name)' of $($holder.path) in this import" } else { "screen '$($holder.name)' in TIA" }
        return @{ ok = $false; refused = "Screen '$name' has number $n, which $whose has: TIA ended on such an import (The `"screen number '$n' for screen '$name' is not unique for this device.). Give the document a number no screen of the device has, or renumber '$($holder.name)' first." }
    }
    foreach ($k in @($taken.Keys)) { if ([string]::Equals($taken[$k].name, $name, [StringComparison]::OrdinalIgnoreCase)) { $taken.Remove($k) } }
    if ($null -eq $n) { $n = 1; while ($taken.ContainsKey($n)) { $n++ } }
    $taken[$n] = @{ name = $name; path = Get-RepoRelative $File.file }
}

function Import-HmiFile($Composition, $File, [bool]$Override) {
    $list = $Composition.Import([System.IO.FileInfo]::new($File.file), (Get-ImportOptions $Override))
    @{ ok = $true; imported = @($list | ForEach-Object { $_.Name }) }
}

Register-ObjectKind 'hmi_screen' @{
    scope = 'hmi'; dir = 'hmi\screens'; importDir = 'hmi\generated\screens'
    importGuard = $script:HmiImportGuard
    defaultOverride = $true
    description = 'screens; an import whose number another screen of the device has is refused (it ended TIA)'
    items = { param($hmi) Get-GroupTree $hmi.ScreenFolder 'Screens' 'Folders' }
    tree = { param($hmi) $hmi.ScreenFolder }; groups = 'Folders'
    # no info: a Comfort screen offers only Name through Openness; number and template are in its export only
    # [PROBE] (2026-10-06: GetAttributeInfos lists Name alone, list had shown null for every screen)
    export = { param($e, $dir, $opt) Export-HmiFullObject $e $dir }
    precheck = { param($file, $cache, $entries)
        $refusal = Test-HmiScreenFile $file $cache
        if ($refusal) { $refusal } else { Test-HmiScreenNumber $file $cache $entries } }
    import = { param($hmi, $folder, $file, $override) Import-HmiFile (Get-OrCreateGroup $hmi.ScreenFolder $folder 'Folders').Screens $file $override }
    whoseFile = { param($file, $entries) Get-DocumentFileObject $file }
}

Register-ObjectKind 'hmi_template' @{
    scope = 'hmi'; dir = 'hmi\templates'; importDir = 'hmi\generated\templates'
    importGuard = $script:HmiImportGuard
    defaultOverride = $false
    description = 'screen templates; an existing template is skipped unless override is true (it may hold an alarm view Openness cannot carry)'
    items = { param($hmi) Get-GroupTree $hmi.ScreenTemplateFolder 'ScreenTemplates' 'Folders' }
    tree = { param($hmi) $hmi.ScreenTemplateFolder }; groups = 'Folders'
    info = { param($e) @{} }
    export = { param($e, $dir, $opt) Export-HmiFullObject $e $dir }
    precheck = { param($file, $cache) Test-HmiScreenFile $file $cache }
    import = { param($hmi, $folder, $file, $override) Import-HmiFile (Get-OrCreateGroup $hmi.ScreenTemplateFolder $folder 'Folders').ScreenTemplates $file $override }
    whoseFile = { param($file, $entries) Get-DocumentFileObject $file }
}

Register-ObjectKind 'hmi_popup' @{
    scope = 'hmi'; dir = 'hmi\popups'; importDir = 'hmi\generated\popups'
    importGuard = $script:HmiImportGuard
    defaultOverride = $true
    description = 'pop-up screens'
    items = { param($hmi) Get-GroupTree $hmi.ScreenPopupFolder 'ScreenPopups' 'Folders' }
    tree = { param($hmi) $hmi.ScreenPopupFolder }; groups = 'Folders'
    info = { param($e) @{} }
    export = { param($e, $dir, $opt) Export-HmiFullObject $e $dir }
    precheck = { param($file, $cache) Test-HmiScreenFile $file $cache }
    import = { param($hmi, $folder, $file, $override) Import-HmiFile (Get-OrCreateGroup $hmi.ScreenPopupFolder $folder 'Folders').ScreenPopups $file $override }
    whoseFile = { param($file, $entries) Get-DocumentFileObject $file }
}

Register-ObjectKind 'hmi_tag_table' @{
    scope = 'hmi'; dir = 'hmi\tags'; importDir = 'hmi\generated\tags'
    importGuard = $script:HmiImportGuard
    defaultOverride = $false
    noOverride = 'Replacing an HMI tag table crashed TIA on 2026-10-01: delete it first, then import.'
    description = 'HMI tag tables, imported from hmi\generated\tags after the HMI validator passed (a tag whose Length did not fit its data type ended TIA); an existing table is refused and override is refused (replacing a tag table crashed TIA on 2026-10-01: delete it first, then import)'
    items = { param($hmi) Get-GroupTree $hmi.TagFolder 'TagTables' 'Folders' }
    tree = { param($hmi) $hmi.TagFolder }; groups = 'Folders'
    info = { param($e) @{ isSystem = $e.obj.IsSystemObject } }
    export = { param($e, $dir, $opt) Export-HmiObject $e $dir $opt }
    precheck = { param($file, $cache) Test-HmiFileFormat $file }
    import = { param($hmi, $folder, $file, $override) Import-HmiFile (Get-OrCreateGroup $hmi.TagFolder $folder 'Folders').TagTables $file $override }
    whoseFile = { param($file, $entries) Get-DocumentFileObject $file }
}

Register-ObjectKind 'hmi_textlist' @{
    scope = 'hmi'; dir = 'hmi\textlists'; defaultOverride = $true
    description = 'device text lists (no folders)'
    items = { param($hmi) foreach ($t in $hmi.TextLists) { @{ obj = $t; name = $t.Name; folder = '' } } }
    info = { param($e) @{} }
    export = { param($e, $dir, $opt) Export-HmiObject $e $dir $opt }
    precheck = { param($file, $cache) Test-HmiFileFormat $file }
    import = { param($hmi, $folder, $file, $override) Import-HmiFile $hmi.TextLists $file $override }
    whoseFile = { param($file, $entries) Get-DocumentFileObject $file }
}

# Cycles: the full export only, and imported from it. A minimal export leaves out StartAtStartingPoint when it is true,
# and TIA's import of it set that false on every cycle, system cycles too; a full export went back unchanged, an edited
# time and a new cycle landed [PROBE] (2026-11-12). The validator (rules\cycle.py) refuses a cycle document
# that is no full export, so the import goes from the export folder, where it looks. Not deleted: that was not tried,
# and an HMI tag names its acquisition cycle.
Register-ObjectKind 'hmi_cycle' @{
    scope = 'hmi'; dir = 'hmi\cycles'; importDir = 'hmi\cycles'
    importGuard = $script:HmiImportGuard
    defaultOverride = $true
    noDelete = 'Deleting a cycle was not tried on a real TIA, and an HMI tag names its acquisition cycle. Delete it in TIA.'
    description = 'cycles (no folders), exported full and imported from hmi\[<device>\]cycles after the HMI validator passed (a minimal export, as older repos hold, is refused: TIA sets StartAtStartingPoint false from it); not deleted'
    items = { param($hmi) foreach ($c in $hmi.Cycles) { @{ obj = $c; name = $c.Name; folder = '' } } }
    info = { param($e) @{ isSystem = $e.obj.IsSystemObject } }
    export = { param($e, $dir, $opt) Export-HmiFullObject $e $dir }
    precheck = { param($file, $cache) Test-HmiFileFormat $file }
    import = { param($hmi, $folder, $file, $override) Import-HmiFile $hmi.Cycles $file $override }
    whoseFile = { param($file, $entries) Get-DocumentFileObject $file }
}

# Graphic lists: a new one from a file, entries linking a graphic by name (<LinkList><Picture><Name>), went in and round
# tripped identically; the minimal export imported over the list left its full export identical, entries of
# non-default values (flashing, transparent colours, a range) and the comment too; a graphic I/O field linking the list
# (<PictureList>) exported the same after an import over it [PROBE] (2026-11-12 and 2026-11-17, test project). An entry
# naming a graphic the project lacks is refused before TIA sees it (Test-GraphicListFile): TIA takes it and the HMI
# compile then fails. Not deleted: that was not tried, and screens name a graphic list.
Register-ObjectKind 'hmi_graphiclist' @{
    scope = 'hmi'; dir = 'hmi\graphiclists'; defaultOverride = $true
    noDelete = 'Deleting a graphic list was not tried on a real TIA, and screens name it. Delete it in TIA.'
    description = 'graphic lists (no folders); an entry naming a graphic the project does not have is refused; not deleted'
    items = { param($hmi) foreach ($t in $hmi.GraphicLists) { @{ obj = $t; name = $t.Name; folder = '' } } }
    export = { param($e, $dir, $opt) Export-HmiObject $e $dir $opt }
    precheck = { param($file, $cache) Test-GraphicListFile $file $cache }
    import = { param($hmi, $folder, $file, $override) Import-HmiFile $hmi.GraphicLists $file $override }
    whoseFile = { param($file, $entries) Get-DocumentFileObject $file }
}

# The precheck of hmi_graphiclist: SimaticML of a graphic list, whose entries name graphics the project has. Cache.graphics
# holds the project's graphic names for every file of the call. Matched without case, as TIA links them: an entry naming
# 'home' linked the graphic Home, which the export then wrote [PROBE] (2026-11-17, test project). An entry naming a graphic
# the project lacks TIA imported as written, and the HMI compile failed: "A graphic is missing in graphics list".
function Test-GraphicListFile($File, [hashtable]$Cache) {
    $doc = Read-HmiDocumentObject $File 'Hmi.TextGraphicList.GraphicList' 'graphic list'
    if ($doc.refused) { return $doc }
    if (-not $Cache.ContainsKey('graphics')) {
        $names = New-Object System.Collections.Hashtable ([StringComparer]::OrdinalIgnoreCase)
        try { foreach ($g in @(Read-TiaList { foreach ($g in (Get-TiaProject).Graphics) { $g } })) { $names[[string]$g.Name] = $true } }
        catch { $Cache.graphicsFailed = "The project's graphics could not be read, so no graphic list is imported unchecked: $($_.Exception.Message)" }
        $Cache.graphics = $names
    }
    if ($Cache.graphicsFailed) { return @{ ok = $false; refused = $Cache.graphicsFailed } }
    $name = if ($File.objectName) { [string]$File.objectName } else { [string]$File.name }
    foreach ($node in @($doc.node.SelectNodes('.//LinkList/Picture/Name'))) {
        $graphic = $node.InnerText
        if (-not $Cache.graphics.ContainsKey($graphic)) {
            return @{ ok = $false; refused = "Graphic list '$name' names the graphic '$graphic', which the project does not have. Nothing imported: TIA would take the entry, and the HMI compile then fails (a graphic is missing in the list). Import the graphic first (kind graphic), or name one the project has." }
        }
    }
}

# Slide-ins, the global elements and the screen overview: exported full, and imported from that export folder after the
# HMI validator passed, over the device's own only. A slide-in's full export imported over it with Override left its export
# identical; an added text field and a new Dimension landed and round tripped. The overview's Height landed; the global
# elements' BackColor landed, and after an import their export no longer writes the empty layer 0 it wrote before (the
# layer still counts 1). A text field in the global elements ended TIA ("The HmiScreenItemData object is not allowed in
# screen Global screen."): the validator refuses a screen item there (rules\globalscreen.py). Without Override TIA
# refused an existing slide-in and the overview [PROBE] (2026-11-12, test project). That an Override drops what their
# exports cannot carry, as it is taken to on a screen, is [INFERRED], not tried: the validator refuses one listed in
# handbuilt.json (rules\handbuilt.py), and the result says so. A new one and a delete were not tried.
# overrideLoses of the result, when one went in.
$script:HmiFixedScreenNote = 'An Override is taken to drop what Openness cannot export, as on a screen; on these it was not tried. If the global elements held an alarm window or alarm indicator, or a slide-in a control the export leaves out, look in TIA whether it is still there; the session archive holds the project as it was. List such a slide-in or the global elements in hmi\[<device>\]handbuilt.json, and the validator refuses the next import over it.'
$script:HmiFixedScreenAfterImport = { param($result, $items) if (@($items | Where-Object { $_.ok }).Count) { $result.overrideLoses = $script:HmiFixedScreenNote } }
# The global screens by name, as list and whoseFile name them, with the HmiTarget import of each; the document's object
# is Hmi.Screen.<name>.
$script:HmiGlobalScreens = [ordered]@{ ScreenGlobalElements = 'ImportScreenGlobalElements'; ScreenOverview = 'ImportScreenOverview' }

# The precheck of a slide-in or global screen: over the device's own only (Entries), as a new one was not tried.
function Test-HmiFixedScreen($File, [object[]]$Entries, [string]$What) {
    if (@($Entries | Where-Object { [string]::Equals($_.name, [string]$File.objectName, [StringComparison]::OrdinalIgnoreCase) }).Count) { return $null }
    $have = @($Entries | ForEach-Object { $_.name }) -join ', '
    @{ ok = $false; refused = "The HMI device has no $What '$($File.objectName)' (it has: $have). The bridge imports over the device's own only: a new one was not tried." }
}

Register-ObjectKind 'hmi_slidein' @{
    scope = 'hmi'; dir = 'hmi\slideins'; importDir = 'hmi\slideins'
    importGuard = $script:HmiImportGuard
    defaultOverride = $true
    noDelete = 'A slide-in is one of the device''s, by its edge; a delete was not tried on a real TIA.'
    description = 'slide-in screens, named by their panel edge (SlideinType); exported full and imported from hmi\[<device>\]slideins after the HMI validator passed, over the device''s own only; not deleted'
    # a slide-in has no Name; ScreenSlidein.SlideinType tells them apart, as Find(SlideinType) does
    # [PROBE: reflection of V20 Siemens.Engineering.dll, 2026-11-02; a real export holds <SlideinType>Right</SlideinType>]
    items = { param($hmi) foreach ($s in $hmi.ScreenSlideinFolder.ScreenSlideins) { @{ obj = $s; name = [string]$s.SlideinType; folder = '' } } }
    export = { param($e, $dir, $opt) Export-HmiFullObject $e $dir }
    precheck = { param($file, $cache, $entries) Test-HmiFixedScreen $file $entries 'slide-in' }
    import = { param($hmi, $folder, $file, $override)
        $list = $hmi.ScreenSlideinFolder.ScreenSlideins.Import([System.IO.FileInfo]::new($file.file), (Get-ImportOptions $override))
        @{ ok = $true; imported = @($list | ForEach-Object { [string]$_.SlideinType }) } }
    afterImport = $script:HmiFixedScreenAfterImport
    # the slide-in is the edge the document declares, whatever the file is called
    whoseFile = { param($file, $entries)
        $doc = Read-HmiDocumentObject $file 'Hmi.Screen.ScreenSlidein' 'slide-in'
        if ($doc.refused) { return $doc }
        $edge = $doc.node.SelectSingleNode('AttributeList/SlideinType')
        if (-not $edge -or -not $edge.InnerText.Trim()) { return @{ ok = $false; refused = "$($file.file) declares no SlideinType, so which slide-in it is cannot be told. Write it as the export does." } }
        @{ name = $edge.InnerText.Trim() } }
}

Register-ObjectKind 'hmi_screen_global' @{
    scope = 'hmi'; dir = 'hmi\global'; importDir = 'hmi\global'
    importGuard = $script:HmiImportGuard
    defaultOverride = $true
    noDelete = 'The global elements and the screen overview are the device''s own; a delete was not tried on a real TIA.'
    description = 'the global elements and the screen overview (ScreenGlobalElements, ScreenOverview); exported full and imported from hmi\[<device>\]global after the HMI validator passed, over the device''s own only; a screen item in the global elements is refused (a text field there ended TIA, others were not tried); not deleted'
    items = { param($hmi)
        foreach ($n in $script:HmiGlobalScreens.Keys) { $o = $hmi.$n; if ($null -ne $o) { @{ obj = $o; name = $n; folder = '' } } } }
    export = { param($e, $dir, $opt) Export-HmiFullObject $e $dir }
    precheck = { param($file, $cache, $entries) Test-HmiFixedScreen $file $entries 'global screen' }
    import = { param($hmi, $folder, $file, $override)
        $method = $script:HmiGlobalScreens[[string]$file.objectName]
        $null = $hmi.$method([System.IO.FileInfo]::new($file.file), (Get-ImportOptions $override))
        @{ ok = $true } }
    afterImport = $script:HmiFixedScreenAfterImport
    whoseFile = { param($file, $entries)
        $doc = Read-HmiDocumentObject $file @($script:HmiGlobalScreens.Keys | ForEach-Object { "Hmi.Screen.$_" }) 'global elements or screen overview'
        if ($doc.refused) { return $doc }
        @{ name = $doc.node.Name.Substring('Hmi.Screen.'.Length) } }
}

# VB scripts: a new one from a file (Code, PreCode, Type) went in, into the folder its path mirrors, and TIA adds a line
# end to Code on the first import; after that the round trip is identical. The minimal export leaves out PreCode and Type
# when they hold their defaults (two line ends, Sub), and imported over the script it leaves the full export identical, a
# Function with a PreCode and a comment too. A screen whose button calls the script (FunctionListEntry Type VBScript)
# exported the same after an edited script was imported over it. A syntax error imports without a word; the HMI compile
# reported no error while nothing called the script and failed once that screen did [PROBE] (2026-11-12 and 2026-11-19,
# test project). Not deleted: that was not tried, and screens call a script by name.
Register-ObjectKind 'hmi_vbscript' @{
    scope = 'hmi'; dir = 'hmi\scripts'; defaultOverride = $true
    noDelete = 'Deleting a VB script was not tried on a real TIA, and screens call it by name. Delete it in TIA.'
    description = 'VB scripts (a syntax error goes in; the HMI compile found it only once a screen called the script); not deleted'
    items = { param($hmi) Get-GroupTree $hmi.VBScriptFolder 'VBScripts' 'Folders' }
    export = { param($e, $dir, $opt) Export-HmiObject $e $dir $opt }
    precheck = { param($file, $cache) $doc = Read-HmiDocumentObject $file 'Hmi.RuntimeScripting.VBScript' 'VB script'; if ($doc.refused) { $doc } }
    import = { param($hmi, $folder, $file, $override) Import-HmiFile (Get-OrCreateGroup $hmi.VBScriptFolder $folder 'Folders').VBScripts $file $override }
    whoseFile = { param($file, $entries) Get-DocumentFileObject $file }
}

# Export only: SimaticML through Export [PROBE] (2026-10-30, project A).
Register-ObjectKind 'hmi_connection' @{
    scope = 'hmi'; dir = 'hmi\connections'; exportOnly = $true
    description = 'connections of the HMI device (export only)'
    items = { param($hmi) foreach ($c in $hmi.Connections) { @{ obj = $c; name = $c.Name; folder = '' } } }
    export = { param($e, $dir, $opt) Export-HmiObject $e $dir $opt }
}
