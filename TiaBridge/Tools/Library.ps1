# Tools\Library.ps1 -library kinds (library_type, faceplate_type, master_copy) for list/export, and the library tools:
# library_open, library_create_type, library_edit_type, library_discard_type, library_release_type, library_update_usages,
# master_copy_to_project, master_copy_from_project. Type contents go through their project instances (export/import).

$script:LibraryKindNote = 'Library objects change through the library tools: library_create_type, library_edit_type, library_discard_type, library_release_type, library_update_usages, master_copy_to_project, master_copy_from_project.'

# ------------------------------------------------------------------ version and content rules (pure)

# Versions: objects with VersionNumber ([version]) and State ('InWork'|'Committed'). TIA numbers a version in work
# with the number it proposes for the release; a requested number must be above every released one.
function Get-ReleaseVersion([object[]]$Versions, [string]$Requested = '') {
    $released = @($Versions | Where-Object { [string]$_.State -ne 'InWork' } | ForEach-Object { [version]$_.VersionNumber } | Sort-Object)
    $highest = if ($released.Count) { $released[-1] } else { [version]'0.0.0' }
    if ($Requested) {
        $v = [version]$Requested
        if ($v -le $highest) { throw "Version $Requested is not above the released version $highest." }
        return [string]$v
    }
    $work = Select-TypeVersion -Versions $Versions -InWork
    if ($work -and [version]$work.VersionNumber -gt $highest) { return [string]$work.VersionNumber }
    $parts = @($highest.Major, $highest.Minor, [Math]::Max(0, $highest.Build))
    $parts[2]++
    $parts -join '.'
}

# -InWork: the version in work, or $null. Otherwise the version to edit: the default one, else the highest released.
function Select-TypeVersion([object[]]$Versions, [switch]$InWork) {
    if ($InWork) { return $Versions | Where-Object { [string]$_.State -eq 'InWork' } | Select-Object -First 1 }
    $default = $Versions | Where-Object { $_.IsDefault -and [string]$_.State -ne 'InWork' } | Select-Object -First 1
    if ($default) { return $default }
    $Versions | Where-Object { [string]$_.State -ne 'InWork' } | Sort-Object { [version]$_.VersionNumber } | Select-Object -Last 1
}

# Every type of the library by name, in one walk. Without case, as TIA.
function Get-LibraryTypeMap($Library) {
    $map = New-Object System.Collections.Hashtable ([StringComparer]::OrdinalIgnoreCase)
    foreach ($e in Get-GroupTree $Library.TypeFolder 'Types' 'Folders') { $map[[string]$e.name] = $e.obj }
    $map
}

# What a release with AutomaticallyCreateOrReleaseDependenciesIfRequired did beside what was asked, and TIA does not say: it
# releases the contained types in work and makes a library type of a plain block or data type it uses [PROBE] (2026-11-03).
# InWorkBefore: names. Asked: what was to be released. Returns @{ made; alsoReleased = @(names) }.
function Compare-LibraryAroundRelease($Library, [hashtable]$MapBefore, [string[]]$InWorkBefore, [string[]]$Asked) {
    $now = Get-LibraryTypeMap $Library
    @{ made = @($now.Keys | Where-Object { -not $MapBefore.ContainsKey($_) } | Sort-Object)
       alsoReleased = @($InWorkBefore | Where-Object { $Asked -notcontains $_ -and $now[$_] -and -not (Select-TypeVersion -Versions @($now[$_].Versions) -InWork) }) }
}

# Types in work in After and not in Before, as @{ type; version }. Each: the types of a Get-InWorkTypes.
function Get-TypesNewlyInWork([object[]]$Before, [object[]]$After) {
    $had = @($Before | ForEach-Object { $_.type })
    foreach ($w in $After) { if ($w -and $had -notcontains $w.type) { @{ type = [string]$w.type; version = [string]$w.inWork } } }
}

function Format-TypeVersionsCapped([object[]]$Types) { Format-NamesCapped @($Types | ForEach-Object { "$($_.type) $($_.version)" }) }

# Next step after a release of a type that others contain. InWork: which of them stand in work; InWorkKnown: that was read whole.
function Format-NextAfterRelease([string]$Type, [string[]]$InWork, [bool]$InWorkKnown) {
    $names = @($InWork | Where-Object { $_ })
    if (-not $InWorkKnown) { return "library_update_usages with types=['$Type'], then library_release_chain." }
    if ($names.Count) { return "library_update_usages with types=['$Type'], then library_release_chain. In work already: $(Format-NamesCapped $names)." }
    "library_update_usages with types=['$Type']: TIA puts the dependent data types in work; then library_release_chain."
}

# What a version just released still sits on: "name (uses x, default y)" for each type it contains on a version that is not that
# type's default. A version in work lists no dependencies, so this can only be read after the release.
function Get-VersionOldUses($Type, [string]$Number) {
    $v = @(@($Type.Versions) | Where-Object { [string]$_.VersionNumber -eq $Number })[0]
    if (-not $v) { return }
    $defaults = @{}
    $deps = @(foreach ($d in @($v.Dependencies)) {
        $dn = [string]$d.TypeObject.Name
        $defaults[$dn] = [string](Select-TypeVersion -Versions @($d.TypeObject.Versions)).VersionNumber
        @{ name = $dn; version = [string]$d.VersionNumber }
    })
    $stale = Find-StaleDependencies @(@{ name = 'x'; deps = $deps }) $defaults
    @($stale['x'] | Where-Object { $_ })
}

function Format-MadeTypesWayOut([string[]]$Made) {
    "$(@($Made) -join ', ') would become library types, and nobody made them: TIA makes a type of a plain block or data type a released type uses. Nothing was released. " +
    'Make it a type yourself (export it, delete it, library_create_type from that document), or take it out of the type.'
}

# A type with no released version yet: only a version in work.
function Test-NeverReleased([object[]]$Versions) { -not @($Versions | Where-Object { [string]$_.State -ne 'InWork' }).Count }

# Content type name of a master copy (MasterCopyContentDescription.ContentType.Name) -> where CreateFrom creates it.
# kind: the object kind whose folder tree receives it; composition: the collection on that folder.
$script:MasterCopyTargets = @{
    FB = @('block', 'Blocks'); FC = @('block', 'Blocks'); OB = @('block', 'Blocks')
    GlobalDB = @('db', 'Blocks'); InstanceDB = @('db', 'Blocks'); ArrayDB = @('db', 'Blocks')
    PlcBlockUserGroup = @('block', 'Groups')
    PlcType = @('type', 'Types'); PlcStruct = @('type', 'Types'); PlcTypeUserGroup = @('type', 'Groups')
    PlcTagTable = @('plc_tag_table', 'TagTables'); PlcTagTableUserGroup = @('plc_tag_table', 'Groups')
    Screen = @('hmi_screen', 'Screens')
    ScreenPopup = @('hmi_popup', 'ScreenPopups'); ScreenTemplate = @('hmi_template', 'ScreenTemplates')
    TagTable = @('hmi_tag_table', 'TagTables')
}
# DependsOn: type name -> names of the types it contains (from LibraryTypeVersion.Dependencies).
# Every type that contains Name, directly or deeper: TIA puts all of them in work when the project is updated
# to a new version of Name (2026-10-05: one comment in typePosition put 29 types in work).
function Get-TypeDependents([hashtable]$DependsOn, [string]$Name) {
    $found = @{}
    $queue = New-Object System.Collections.Queue
    $queue.Enqueue($Name)
    while ($queue.Count) {
        $n = $queue.Dequeue()
        foreach ($t in $DependsOn.Keys) {
            if (-not $found.ContainsKey($t) -and @($DependsOn[$t]) -contains $n) { $found[$t] = $true; $queue.Enqueue($t) }
        }
    }
    @($found.Keys)
}

# Names in an order that releases contained types before the types containing them; refuses a cycle.
function Get-ReleaseOrder([hashtable]$DependsOn, [string[]]$Names) {
    $inSet = @{}; foreach ($n in $Names) { $inSet[$n] = $true }
    $state = @{}   # visiting | done
    $order = New-Object System.Collections.ArrayList
    $visit = $null
    $visit = {
        param($n)
        if ($state[$n] -eq 'done') { return }
        if ($state[$n] -eq 'visiting') {
            throw "The library types contain each other, so no release order exists: $(@($state.Keys | Where-Object { $state[$_] -eq 'visiting' } | Sort-Object) -join ', ')."
        }
        $state[$n] = 'visiting'
        foreach ($d in @($DependsOn[$n])) { if ($inSet[$d]) { & $visit $d } }
        $state[$n] = 'done'
        [void]$order.Add($n)
    }
    foreach ($n in $Names) { & $visit $n }
    @($order)
}

# IncompleteAfter: number of types walked when the walk stopped at its time limit (0 = complete).
function Format-LibrarySummary([string]$Action, [string]$Type, [string]$From, [string]$To, [string[]]$Dependents, [string]$Next, [int]$IncompleteAfter = 0) {
    # a type never released has no From, and a version in work lists no dependencies [PROBE]: what uses it in work is not counted
    $s = if ($From) { "$Type $From -> $To $Action. " } else { "$Type $To $Action, no released version before it. " }
    $deps = @($Dependents | Where-Object { $_ } | Sort-Object)
    if ($IncompleteAfter) { $s += "Dependents not counted: the library walk stopped after $IncompleteAfter types (time limit). " }
    elseif ($deps.Count) {
        $shown = @($deps | Select-Object -First 3) -join ', '
        if ($deps.Count -gt 3) { $shown += ', ...' }
        $s += "Affects $($deps.Count) dependent library types ($shown). "
    } elseif ($From) { $s += 'No dependent library types. ' }
    else { $s += 'No released type depends on it; a version in work lists no dependencies, so types in work are not counted. ' }
    $s + "Next: $Next"
}

# Compile result tree (ConvertTo-ResultTree) -> its errors: @{ path; object; description }. The object is the
# innermost path segment shaped "name (UDT)" / "name (FC422)"; the closing "Compiling finished" line is left out.
function Get-CompileErrors($Tree) {
    $stack = New-Object System.Collections.Stack
    foreach ($m in @($Tree.messages)) { $stack.Push(@($m, @())) }
    $out = New-Object System.Collections.ArrayList
    while ($stack.Count) {
        $e = $stack.Pop(); $m = $e[0]
        $segments = @($e[1]) + @(if ($m.path) { [string]$m.path })
        $children = @($m.messages | Where-Object { $_ })
        if ($children.Count) {
            for ($i = $children.Count - 1; $i -ge 0; $i--) { $stack.Push(@($children[$i], $segments)) }
            continue
        }
        if ([string]$m.state -ne 'Error' -or ([string]$m.description -like 'Compiling finished*')) { continue }
        $object = ''
        for ($i = $segments.Count - 1; $i -ge 0; $i--) {
            if ($segments[$i] -match '^(.+?) \([A-Z]+\d*\)$') { $object = $Matches[1]; break }
        }
        [void]$out.Add(@{ path = ($segments -join '/'); object = $object; description = [string]$m.description })
    }
    @($out)
}

# What library_release_chain will do, decided before anything is released: TIA releases a type even while the
# project does not compile (probed 2026-10-05), so the bridge refuses itself. Returns @{ ok; order } or
# @{ ok = $false; refused; toEdit } (library blocks that use a changed type and are not in work).
function Get-ReleaseChainPlan([string[]]$InWork, [hashtable]$DependsOn, [object[]]$CompileErrors, [string[]]$LibraryTypes) {
    $inWork = @($InWork | Where-Object { $_ })
    if (-not $inWork.Count) { return @{ ok = $false; refused = 'No library type is in work: nothing to release.'; toEdit = @() } }
    $errors = @($CompileErrors | Where-Object { $_ })
    if ($errors.Count) {
        $toEdit = @($errors | Where-Object { $_.description -match 'incompatible changes' -and $LibraryTypes -contains $_.object -and $inWork -notcontains $_.object } |
            ForEach-Object { $_.object } | Sort-Object -Unique)
        $other = @($errors | Where-Object { $toEdit -notcontains $_.object })
        $lines = @()
        if ($toEdit.Count) { $lines += "These library blocks use a changed type and are not in work: put each in work (library_edit_type), compile, then run the chain again: $($toEdit -join ', ')." }
        if ($other.Count) {
            $lines += 'Compile errors: ' + (@($other | Select-Object -First 10 | ForEach-Object { "$(if ($_.object) { $_.object } else { $_.path }): $($_.description)" }) -join ' | ')
            if ($other.Count -gt 10) { $lines += "... and $($other.Count - 10) more (see the compile log)." }
        }
        return @{ ok = $false; refused = "Nothing released: the project does not compile. $($lines -join ' ')"; toEdit = $toEdit }
    }
    @{ ok = $true; order = @(Get-ReleaseOrder -DependsOn $DependsOn -Names $inWork) }
}

function Get-MasterCopyTarget([string]$ContentType) {
    $t = $script:MasterCopyTargets[$ContentType]
    if (-not $t) { throw "Master copies holding '$ContentType' cannot be placed by the bridge. Supported: $(@($script:MasterCopyTargets.Keys | Sort-Object) -join ', ')." }
    @{ kind = $t[0]; composition = $t[1] }
}

# @{ name; folder; class; versions[] } of every type in the project library (faceplate guard, list).
function Get-ProjectLibraryTypes {
    $lib = (Get-TiaProject).ProjectLibrary
    foreach ($e in Get-GroupTree $lib.TypeFolder 'Types' 'Folders') {
        @{ name = $e.name; folder = $e.folder; class = $e.obj.GetType().Name
           versions = @($e.obj.Versions | ForEach-Object { [string]$_.VersionNumber }) }
    }
}

# notDefaultDependencies: the default version uses another type in a version that is not that type's default (stale).
function Get-LibraryTypeInfo($Entry) {
    $i = @{ class = $Entry.obj.GetType().Name
            versions = @($Entry.obj.Versions | ForEach-Object { @{ version = [string]$_.VersionNumber; state = [string]$_.State; isDefault = $_.IsDefault; author = $_.Author } }) }
    $v = Select-TypeVersion -Versions @($Entry.obj.Versions)
    if ($v) {
        $defaults = @{}
        $deps = @(foreach ($d in @($v.Dependencies)) {
            $dn = [string]$d.TypeObject.Name
            $defaults[$dn] = [string](Select-TypeVersion -Versions @($d.TypeObject.Versions)).VersionNumber
            @{ name = $dn; version = [string]$d.VersionNumber }
        })
        $s = Find-StaleDependencies @(@{ name = $Entry.name; deps = $deps }) $defaults
        if ($s.Count) { $i.notDefaultDependencies = @($s[$Entry.name]) }
    }
    $i
}

# Version metadata only: Openness cannot export the contents of a faceplate type (WinCC guide section 6).
function Export-LibraryTypeVersions($Entry, [string]$Dir) {
    New-Item -ItemType Directory -Force -Path $Dir | Out-Null
    $files = @(foreach ($v in $Entry.obj.Versions) {
        $file = Join-Path $Dir "$(ConvertTo-SafeFileName $Entry.name)_V$($v.VersionNumber).xml"
        Export-ObjectFile $v $file ([Siemens.Engineering.ExportOptions]::WithDefaults)
        $file
    })
    # The metadata files do not name the type; the HMI preview reads the exact name, library folder and versions
    # from this index (TiaHmiGenerator\hmipreview\model.py, faceplate links).
    $index = Join-Path $Dir "$(ConvertTo-SafeFileName $Entry.name).type.json"
    $versions = @($Entry.obj.Versions | ForEach-Object { [string]$_.VersionNumber })
    Write-TextFile $index (ConvertTo-Json -Depth 3 -InputObject ([ordered]@{ name = [string]$Entry.name; folder = [string]$Entry.folder; versions = $versions }))
    $files += $index
    @{ ok = $true; format = 'xml'; files = $files; note = 'Version metadata only (author, version, comment), not the type contents; <type>.type.json lists name, library folder and versions.' }
}

# Supported export formats of a type version -> the one the bridge writes, or $null (faceplate types offer none).
function Select-LibraryExportFormat([string[]]$Supported) {
    foreach ($f in 'SimaticSD', 'SimaticMLWithExportOptionsWithDefaults') { if ($Supported -contains $f) { return $f } }
    if (@($Supported).Count) { return $Supported[0] }
    $null
}

# The format a type's documents have in the repo: 'xml', 's7dcl' or '' (no export yet). Dir: the type's folder.
function Get-LibraryTypeRepoFormat([string]$Dir, [string]$Name) {
    $base = Join-Path $Dir (ConvertTo-SafeFileName $Name)
    if (Test-Path -LiteralPath "$base.xml") { return 'xml' }
    if (Test-Path -LiteralPath "$base.s7dcl") { return 's7dcl' }
    ''
}

# options.format of export (s7dcl | xml | '') -> the TIA format name. Without one the type keeps the format its
# documents have in the repo (Current), so an export of '*' does not turn a SimaticML type back into SD; a new type
# gets Select-LibraryExportFormat. SimaticML as WithDefaults, like the SimaticML of blocks (Plc.ps1). Throws when the
# type offers no such format.
function Resolve-LibraryExportFormat([string[]]$Supported, [string]$Requested, [string]$Current) {
    $want = if ($Requested) { $Requested } else { $Current }
    switch ($want) {
        'xml' {
            foreach ($f in 'SimaticMLWithExportOptionsWithDefaults', 'SimaticMLWithExportOptionsNone') { if ($Supported -contains $f) { return $f } }
            $ml = @($Supported | Where-Object { $_ -like 'SimaticML*' })
            if ($ml.Count) { return $ml[0] }
        }
        's7dcl' { if ($Supported -contains 'SimaticSD') { return 'SimaticSD' } }
    }
    if ($Requested) { throw "The type offers no $Requested export. Supported: $(if (@($Supported).Count) { $Supported -join ', ' } else { 'none' })." }
    Select-LibraryExportFormat $Supported
}

# LAD and FBD networks of a .s7dcl text with an operand indexed in several dimensions (a[i, j]): the SD import keeps
# only the last index of each (docs/agent/s7dcl-format.md 8.14c, checklist 17a; SCL networks keep them). Returns their count.
function Get-MultiIndexLadNetworks([string]$Text) {
    $preferred = if ($Text -match 'S7_PreferredLanguage := "(\w+)"') { $Matches[1] } else { '' }
    $count = 0; $lang = ''; $inNetwork = $false; $hit = $false
    foreach ($line in ($Text -split "`r?`n")) {
        if ($line -match '^\s*\{?\s*S7_Language := "(\w+)"') { $lang = $Matches[1]; continue }
        if ($line -match '^\s*NETWORK\s*$') { $inNetwork = $true; $hit = $false; if (-not $lang) { $lang = $preferred }; continue }
        if ($line -match '^\s*END_NETWORK\s*$') { if ($hit) { $count++ }; $inNetwork = $false; $lang = ''; continue }
        if ($inNetwork -and -not $hit -and $lang -in 'LAD', 'FBD' -and $line -match '\[[^\[\]]*,[^\[\]]*\]') { $hit = $true }
    }
    $count
}

# The type's documents, from the version in work (else the default one), into a folder of its own.
# A type version exports without a project instance; SimaticSD for PLC data types, SimaticML for code block types [PROBE].
# Released: the default released version into <name>.released, the base for reviewing what a version in work changed;
# kept apart so it is never imported by mistake (it would overwrite the version in work).
# Format: a TIA format name (library_review). As: options.format of export, s7dcl | xml | '' (Resolve-LibraryExportFormat).
# The folder's files are replaced as a whole, so the type has its documents in one format only; removed lists the files of the
# previous export that the new one does not write (the other format), for the commit. Its subfolders stay: a library folder
# of the type's name holds other types there (type Foo beside folder Foo with type Bar).
function Export-LibraryTypeDocuments($Entry, [string]$Dir, [switch]$Released, [string]$Format = '', [string]$As = '') {
    $type = $Entry.obj
    # The documents of a global library's type versions cannot be exported: "Cannot get supported export formats for a
    # type in the global library", and ExportAsDocuments with any format "Cannot export a version of a type in the
    # global library" [PROBE] (2026-10-06). Their version metadata exports, as for faceplate types.
    $formats = if ($Format) { @($Format) } else {
        try {
            $supported = @($type.GetSupportedExportFormats() | ForEach-Object { [string]$_ })
            $current = Get-LibraryTypeRepoFormat (Join-Path $Dir (ConvertTo-SafeFileName $Entry.name)) $Entry.name
            @(Resolve-LibraryExportFormat $supported $As $current | Where-Object { $_ })
        }
        catch {
            if ((ConvertTo-BridgeError $_).message -notmatch 'global library') { throw }
            $r = Export-LibraryTypeVersions $Entry $Dir
            $r.note = 'Version metadata only: Openness cannot export the documents of a type in a global library. To work on it, bring it into the project library (library_update_usages with library=<name>) and export it there.'
            return $r
        }
    }
    # The if statement unrolls a one-element array: $formats is then a string, and $formats[0] its first letter
    # ("The export format 'S' is not supported", 2026-10-08)
    $formats = @($formats | Where-Object { $_ })
    if (-not $formats.Count) { return Export-LibraryTypeVersions $Entry $Dir }
    $work = if ($Released) { $null } else { Select-TypeVersion -Versions @($type.Versions) -InWork }
    $version = if ($work) { $work } else { Select-TypeVersion -Versions @($type.Versions) }
    $folder = ConvertTo-SafeFileName $Entry.name
    if ($Released) { $folder += '.released' }
    $target = Join-Path $Dir $folder
    $format = $formats[0]
    # into a fresh folder first: the previous export is replaced only by a successful one
    $partial = New-ExportWorkPath $target
    New-Item -ItemType Directory -Force -Path $partial | Out-Null
    try {
        $r = $version.ExportAsDocuments([System.IO.DirectoryInfo]::new($partial), (ConvertTo-SafeFileName $Entry.name), $format,
                                        [Siemens.Engineering.Library.LibraryExportOptions]::WithLibraryVersionInfoFile)
        # copied, not moved: until the swap below the old folder is whole, and a failure leaves it as it was
        foreach ($sub in @(Get-ChildItem -LiteralPath $target -Directory -Force -ErrorAction SilentlyContinue)) {
            Copy-Item -LiteralPath $sub.FullName -Destination (Join-Path $partial $sub.Name) -Recurse -Force -ErrorAction Stop
        }
    } catch { Remove-Item -LiteralPath $partial -Recurse -Force -ErrorAction SilentlyContinue; throw }
    $old = @(Get-ChildItem -LiteralPath $target -File -ErrorAction SilentlyContinue | ForEach-Object { $_.Name })
    Move-ExportIntoPlace $partial $target
    $files = @(Get-ChildItem -LiteralPath $target -File | ForEach-Object { $_.FullName })
    $names = @($files | ForEach-Object { [System.IO.Path]::GetFileName($_) })
    $note = if ($Released) { 'Released version, for comparison with the version in work; never import these files.' }
            elseif ($work) { 'In work: edit these files, then import them with kind library_type.' } else { 'Released version: library_edit_type first to change it.' }
    if ($format -eq 'SimaticSD' -and -not $Released) {
        $sd = Join-Path $target "$folder.s7dcl"
        $n = if (Test-Path -LiteralPath $sd) { Get-MultiIndexLadNetworks ([System.IO.File]::ReadAllText($sd)) } else { 0 }
        if ($n) { $note += " $n LAD/FBD networks use operands indexed in several dimensions (a[i, j]): an import of this .s7dcl keeps only their last index ($(Get-GuidePath 's7dcl-format.md') 8.14c, 17a). To change the type, export it with options.format xml and edit the SimaticML." }
    }
    $result = @{ ok = $true; format = $format; version = [string]$version.VersionNumber; inWork = [bool]$work
                 files = $files; messages = (ConvertTo-ResultTree $r); note = $note }
    $removed = @($old | Where-Object { $names -notcontains $_ } | ForEach-Object { Join-Path $target $_ })
    if ($removed.Count) { $result.removed = $removed }
    $result
}

function Test-ReleasedExportPath([string]$Path) {
    [System.IO.Path]::GetFileName([System.IO.Path]::GetDirectoryName($Path)) -like '*.released'
}

# The format of the documents an import of File reads: 'xml' or 's7dcl', or @{ refused } (before TIA is touched).
# CreateFromDocuments takes the folder and the type name, not a file, so the folder must hold one format only:
# SimaticML for blocks the SD import damages (17a), else SD (export writes one; a copy by hand may leave both).
function Get-LibraryTypeImportFormat($File) {
    $base = Join-Path ([System.IO.Path]::GetDirectoryName($File.file)) $File.name
    $xml = Test-Path -LiteralPath "$base.xml"
    $sd = Test-Path -LiteralPath "$base.s7dcl"
    if ($xml -and $sd) { return @{ refused = "The folder of $($File.name) holds both $($File.name).xml and $($File.name).s7dcl; TIA would read either. Keep one format: export the type again with options.format xml or s7dcl." } }
    if ($xml) { 'xml' } elseif ($sd) { 's7dcl' } else { @{ refused = "No $($File.name).xml or $($File.name).s7dcl beside $($File.file)." } }
}

# Whether a project instance of any version of the type has this name. Asks TIA, so only when a name differs.
function Test-TypeInstanceName($Type, [string]$Name) {
    foreach ($v in @($Type.Versions)) { foreach ($i in Get-TypeInstances $v) { if ($i.name -eq $Name) { return $true } } }
    $false
}

# Which library type the documents of File are: @{ name } or @{ refused } (before TIA is touched). A file name is the
# type's name made file-safe, so Ns_Block may be the type Ns_Block or the type Ns:Block. Importing over the wrong one must
# not happen, so an exact match does not win: every type with that file-safe form counts, two are refused, and the
# document must declare the one that is left or a project instance of it: a type's document can carry the instance's name
# (TIA imported one, docs/agent/openness-v20.md section 3). No name written into .libinfo: it is TIA's own file, the
# next export replaces it and TIA may read it on import.
function Resolve-LibraryTypeFile($File, [object[]]$Entries) {
    $format = Get-LibraryTypeImportFormat $File
    if ($format -is [hashtable]) { return $format }
    $hits = @($Entries | Where-Object { (ConvertTo-SafeFileName $_.name) -eq $File.name })
    if (-not $hits.Count) { return @{ refused = "No library type named '$($File.name)', also not in file-safe form." } }
    if ($hits.Count -gt 1) {
        return @{ refused = "The file name '$($File.name)' fits the library types $(@($hits | ForEach-Object { "'$($_.name)'" } | Sort-Object) -join ' and '): they share one file name and the bridge will not guess. Rename one of them in TIA, then export it again." }
    }
    $name = [string]$hits[0].name
    $declared = Get-DocumentDeclaredName (Join-Path ([System.IO.Path]::GetDirectoryName($File.file)) "$($File.name).$format")
    if ($declared -and $declared -ne $name -and -not (Test-TypeInstanceName $hits[0].obj $declared)) {
        return @{ refused = "$($File.file) declares '$declared', its file name fits the library type '$name', and no project instance of that type has that name. Export the type again, or correct the name in the document." }
    }
    # a file with the type's own name needs no proof: the plan refuses a .s7dcl with a keyword whose object cannot be read
    # (Get-DocumentRefusal), and one with no keyword, or a SimaticML with no name, fails in TIA, as it always did
    if (-not $declared -and $name -ne $File.name) { return @{ refused = "$($File.file) declares no name the bridge can read, so it cannot confirm it is the library type '$name'. Export the type again." } }
    @{ name = $name }
}

# The blocks and data types of the PLC by key, or $null when they cannot be read: a compare must not fail the write it looks at.
function Read-PlcObjectKeySet {
    try { $set = @{}; foreach ($k in @(Get-PlcObjectKeys)) { $set[$k] = $true }; $set }
    catch { if (Test-TiaEndedError $_) { throw }; Write-BridgeLog "The objects of the PLC were not read around the import: $($_.Exception.Message)"; $null }
}

# What came into the PLC since Before (Read-PlcObjectKeySet), as Get-PlcObjectRecords has them, sorted by key. When that fuller read fails TIA has
# taken the import all the same: what came is named by its key, marked unread, as what it is was not read.
function Get-PlcObjectsSince($Before) {
    if ($null -eq $Before) { return }
    $now = Read-PlcObjectKeySet
    if ($null -eq $now) { return }
    $came = @($now.Keys | Where-Object { -not $Before.ContainsKey($_) } | Sort-Object)
    if (-not $came.Count) { return }
    $records = $null
    try { $records = Get-PlcObjectRecords }
    catch { if (Test-TiaEndedError $_) { throw }; Write-BridgeLog "What came with the import was not read: $($_.Exception.Message)" }
    foreach ($k in $came) {
        if ($records -and $records[$k]) { $records[$k]; continue }
        $device, $null, $name = $k -split "`t", 3
        @{ object = $name; device = $device; folder = ''; unread = $true }
    }
}

function Format-CopiesBack([object[]]$Copies) {
    $types = @($Copies | Where-Object { $_.type } | ForEach-Object { [string]$_.type } | Sort-Object -Unique)
    $shown = @($Copies | Select-Object -First 10 | ForEach-Object { if ($_.unread) { [string]$_.object } else { Format-RemovedList @($_) } }) -join ', '
    "The import brought these into the PLC: $shown$(if (@($Copies).Count -gt 10) { " and $(@($Copies).Count - 10) more (copiesBack)" }). " +
    'TIA makes them from what the older version of the type was built on, also from a document that is right. Nothing uses them, so the next update removes them, named' +
    $(if ($types.Count) { ": library_update_usages with $(Format-TypesArgument $types 'copiesBack')" }) + '. While they stand an export of the type reads their names.'
}

# types=['a', 'b'] of at most ten; Field: where the rest stands.
function Format-TypesArgument([string[]]$Types, [string]$Field) {
    "types=[$(@($Types | Select-Object -First 10 | ForEach-Object { "'$_'" }) -join ', ')]$(if (@($Types).Count -gt 10) { " and $(@($Types).Count - 10) more (the types in $Field)" })"
}

# After the batch, as only then it is known what was kept: a batch rolled back brought nothing.
function Add-CopiesBackFacts($Result, [object[]]$Items) {
    $kept = New-Object System.Collections.ArrayList
    foreach ($i in $Items) {
        if (-not $i.copiesBack) { continue }
        if ($i.rolledBack) { $i.Remove('copiesBack'); continue }
        foreach ($c in @($i.copiesBack)) { [void]$kept.Add($c) }
    }
    if (-not $kept.Count) { return }
    $text = Format-CopiesBack @($kept)
    $Result.copiesBack = @($kept)
    $Result.next = "$(([string]$Result.next).TrimEnd('.')). $text"
    Add-LibraryLog $text
}

# Edited documents back into the version in work: Versions.CreateFromDocuments with Override [PROBE] (2026-10-05);
# SimaticML documents the same way (project A Trolley, 2026-10-29: 13 s, no prompt, the multi-dimensional indices kept).
function Import-LibraryTypeDocuments($Library, $File) {
    if (Test-ReleasedExportPath $File.file) { return @{ ok = $false; refused = "$($File.file) is an export of the released version, for comparison only: import the files of the version in work." } }
    $format = Get-LibraryTypeImportFormat $File
    if ($format -is [hashtable]) { return @{ ok = $false; refused = $format.refused } }
    $e = Find-LibraryType $Library $File.objectName
    $work = Select-TypeVersion -Versions @($e.obj.Versions) -InWork
    if (-not $work) { return @{ ok = $false; refused = "Type '$($e.name)' has no version in work: library_edit_type first." } }
    $lineEnds = if ($format -eq 's7dcl') { Repair-DocumentLineEnds (Join-Path ([System.IO.Path]::GetDirectoryName($File.file)) "$($File.name).s7dcl") }
    # TIA makes copies of what the type's older version contains, on the old versions, and says nothing [PROBE] (2026-11-03)
    $scope = Get-LibraryTypeScope $e.obj
    $objectsBefore = $(if ($scope -eq 'plc') { Read-PlcObjectKeySet })
    # the name of the documents in the folder, as ExportAsDocuments got it; a type with ':' goes by its file-safe name here [PROBE] (2026-11-04)
    $r = $e.obj.Versions.CreateFromDocuments([System.IO.DirectoryInfo]::new([System.IO.Path]::GetDirectoryName($File.file)), $File.name,
                                             [Siemens.Engineering.Library.Types.CreateOptions]::Override, [Siemens.Engineering.Library.LibraryImportOptions]::None)
    $tree = ConvertTo-ResultTree $r
    $tree.state = [string]$r.TransferResultState   # Success or Warning; failures throw
    # the version object read before CreateFromDocuments no longer answers; read it again
    $after = Select-TypeVersion -Versions @($e.obj.Versions) -InWork
    $version = [string]$after.VersionNumber
    Add-LibraryLog "$($e.name) $version in work: documents imported. Next: compile, then library_release_type."
    $result = @{ ok = $true; version = $version; format = $format; messages = $tree; scope = $scope }
    if ($lineEnds) { $result.note = $lineEnds }
    $came = @(Get-PlcObjectsSince $objectsBefore)
    if ($came.Count) { $result.copiesBack = @(ConvertTo-RemovedResult $came) }
    $result
}

Register-ObjectKind 'library_type' @{
    scope = 'library'; dir = 'library\types'; defaultOverride = $true
    description = 'project library types: export writes the documents of the version in work (else the default one); import writes edited documents back into the version in work'
    items = { param($lib) Get-GroupTree $lib.TypeFolder 'Types' 'Folders' }
    info = { param($e) Get-LibraryTypeInfo $e }
    export = { param($e, $dir, $opt) Export-LibraryTypeDocuments $e $dir -Released:([bool]$opt.released) -As ([string]$opt.format) }
    import = { param($lib, $folder, $file, $override) Import-LibraryTypeDocuments $lib $file }
    precheck = { param($file, $cache) $f = Get-LibraryTypeImportFormat $file; if ($f -is [hashtable]) { $f } }
    whoseFile = { param($file, $entries) Resolve-LibraryTypeFile $file $entries }
    afterImport = { param($result, $items) Add-CopiesBackFacts $result $items }
}

Register-ObjectKind 'faceplate_type' @{
    scope = 'library'; dir = 'library\faceplates'
    description = 'faceplate types: names, versions, metadata; contents cannot be exported or imported through Openness'
    items = { param($lib) Get-GroupTree $lib.TypeFolder 'Types' 'Folders' | Where-Object { $_.obj.GetType().Name -match 'Faceplate' } }
    info = { param($e) Get-LibraryTypeInfo $e }
    export = { param($e, $dir, $opt) Export-LibraryTypeVersions $e $dir }
}

Register-ObjectKind 'master_copy' @{
    scope = 'library'; dir = 'library\mastercopies'
    description = 'master copies of the project library or an open global library (master_copy_to_project / master_copy_from_project)'
    items = { param($lib) Get-GroupTree $lib.MasterCopyFolder 'MasterCopies' 'Folders' }
    info = { param($e) @{ author = $e.obj.Author; created = [string]$e.obj.CreationDate
                          content = @($e.obj.ContentDescriptions | ForEach-Object { "$($_.ContentType.Name) $($_.ContentName)" }) } }
}

# ------------------------------------------------------------------ libraries

# '' = project library; else a global library already open in TIA (library_open, or opened by the user), by name.
function Get-TiaLibrary([string]$Name = '') {
    $project = Get-TiaProject
    if (-not $Name) { return $project.ProjectLibrary }
    $lib = Get-GlobalLibraryList | Where-Object { $_.Name -eq $Name } | Select-Object -First 1
    if (-not $lib) {
        $open = @(Get-GlobalLibraryList | ForEach-Object { $_.Name }) -join ', '
        throw "Global library '$Name' is not open. Open: $(if ($open) { $open } else { 'none' }). Use library_open."
    }
    $lib
}

function Find-LibraryType($Library, [string]$Name) {
    $e = Get-GroupTree $Library.TypeFolder 'Types' 'Folders' | Where-Object { $_.name -eq $Name } | Select-Object -First 1
    if (-not $e) { throw "No library type named '$Name'." }
    $e
}

# 'plc' or 'hmi': which software a type's instances live in (save rules).
function Get-LibraryTypeScope($Type) { if ($Type.GetType().Name -match 'Faceplate|Screen|Hmi|Style') { 'hmi' } else { 'plc' } }

function Get-UpdateScopes {
    $list = New-Object 'System.Collections.Generic.List[Siemens.Engineering.Library.Types.IUpdateProjectScope]'
    foreach ($s in Get-TiaSoftwareList) { $list.Add($s.software) }
    , $list
}

# Project instances of a type version, as kind + name the object tools understand. FindInstances returns
# LibraryTypeInstanceInfo objects; the instance is their LibraryTypeInstance [PROBE] (2026-10-04). info is kept for Edit.
function Get-TypeInstances($Version) {
    foreach ($s in Get-TiaSoftwareList) {
        try { $found = @($Version.FindInstances($s.software)) } catch { $found = @() }
        foreach ($info in $found) {
            $o = $info.LibraryTypeInstance
            $class = $o.GetType().Name
            $kind = if ($script:MasterCopyTargets[$class]) { $script:MasterCopyTargets[$class][0] } else { $class }
            @{ device = $s.device; kind = $kind; class = $class; name = [string]$o.Name; info = $info }
        }
    }
}

# The blocks and PLC data types of every PLC, one line each, to see what a call took away. HMI objects are not read.
function Get-PlcObjectKeys {
    foreach ($s in @(Get-TiaSoftwareList | Where-Object { $_.kind -eq 'plc' })) {
        foreach ($e in Get-GroupTree $s.software.BlockGroup 'Blocks' 'Groups') { "$($s.device)`tblock`t$($e.name)" }
        foreach ($e in Get-GroupTree $s.software.TypeGroup 'Types' 'Groups') { "$($s.device)`ttype`t$($e.name)" }
    }
}

# What each of them is, read before an update, as nothing can be asked of an object TIA has removed. One walk, outside the write.
function Get-PlcObjectRecords {
    $records = @{}
    foreach ($s in @(Get-TiaSoftwareList | Where-Object { $_.kind -eq 'plc' })) {
        foreach ($part in @(@('block', $s.software.BlockGroup, 'Blocks'), @('type', $s.software.TypeGroup, 'Types'))) {
            foreach ($e in Get-GroupTree $part[1] $part[2] 'Groups') {
                $l = Get-LibraryLink $e.obj
                $records["$($s.device)`t$($part[0])`t$($e.name)"] = @{ object = [string]$e.name; device = $s.device; folder = [string]$e.folder; language = $(if ($part[0] -eq 'block') { [string]$e.obj.ProgrammingLanguage })
                    number = $(if ($part[0] -eq 'block') { $e.obj.Number }); class = $(if ($part[0] -eq 'block') { $e.obj.GetType().Name }); type = $(if ($l) { [string]$l.type }); version = $(if ($l) { [string]$l.version }); knowhow = [bool]$e.obj.IsKnowHowProtected }
            }
        }
    }
    $records
}

# UpdateProject takes out of the PLC every instance of a released type that nothing uses, of any type, selected or not, and
# then what only those used [PROBE] (2026-11-03: FB, FC, UDT, a test instance or one made by CreateFrom; one in work or one a
# plain block calls stays; DoNotDelete is about versions in the library). It is TIA's behaviour: its help says so and its own
# window does it. The bridge lets it, and compares the PLC around the update so that the result can say what went.
# Update: runs the update on the list of selected types it is given. Names: the types, empty for all.
# Returns @{ transaction; commitError; removed = @(records of Get-PlcObjectRecords) }.
function Invoke-ProjectUpdate($Library, [string[]]$Names, [scriptblock]$Update, [string]$Description) {
    $selection = New-Object 'System.Collections.Generic.List[Siemens.Engineering.Library.Types.ILibraryTypeOrFolderSelection]'
    $wanted = @($Names | Where-Object { $_ })
    if ($wanted.Count) { foreach ($n in $wanted) { $selection.Add((Find-LibraryType $Library $n).obj) } } else { $selection.Add($Library.TypeFolder) }
    $objectsBefore = Get-PlcObjectRecords
    $gone = New-Object System.Collections.ArrayList
    try {
        $w = Invoke-TiaWrite $Description -Body {
            & $Update $selection
            $now = @{}; foreach ($k in @(Get-PlcObjectKeys)) { $now[$k] = $true }
            foreach ($k in @($objectsBefore.Keys)) { if (-not $now[$k]) { [void]$gone.Add($k) } }
        }
    }
    catch {
        # rolled back it has taken nothing; without a transaction what it had done by then stands, so look
        if (-not (Test-TiaEndedError $_)) {
            $left = $null
            try { $now = @{}; foreach ($k in @(Get-PlcObjectKeys)) { $now[$k] = $true }; $left = @($objectsBefore.Keys | Where-Object { -not $now[$_] } | Sort-Object | ForEach-Object { $objectsBefore[$_] }) }
            catch { Write-BridgeLog "What the failed update took was not read: $($_.Exception.Message)" }
            if (@($left).Count) { Save-RemovedFact $left; $_.Exception.Data['removed'] = @($left) }
        }
        throw
    }
    # a refused commit kept nothing
    $removed = @($(if (-not $w.commitError -and -not $w.rolledBack) { @($gone | Sort-Object | ForEach-Object { $objectsBefore[$_] }) }) | Where-Object { $_ })
    if ($removed.Count) { Save-RemovedFact $removed }
    @{ transaction = $w.transaction; commitError = $w.commitError; removed = $removed; numbersChanged = @(Get-NumbersChanged $objectsBefore) }
}

# Blocks that stand on another number than before: a free number keeps this empty, and whatever still changes one is named.
# Before: what this update read; a block read before an instance was made counts from there.
function Get-NumbersChanged([hashtable]$Before) {
    $base = @{}
    foreach ($k in $Before.Keys) { $base[$k] = $Before[$k] }
    if ($script:NumberBaseline -and $script:NumberBaseline.project -eq $script:Bridge.projectPath) { foreach ($k in $script:NumberBaseline.records.Keys) { $base[$k] = $script:NumberBaseline.records[$k] } }
    $script:NumberBaseline = $null
    try { $now = Get-PlcObjectRecords }
    catch {
        if (Test-TiaEndedError $_) { throw }
        Write-BridgeLog "The block numbers after the update were not read: $($_.Exception.Message)"
        return
    }
    foreach ($k in @($base.Keys | Sort-Object)) {
        if ($base[$k].number -and $now.ContainsKey($k) -and $now[$k].number -and $now[$k].number -ne $base[$k].number) {
            @{ object = $base[$k].object; device = $base[$k].device; from = $base[$k].number; to = $now[$k].number }
        }
    }
}

# Said at once: the log and the result of any failure later in the call hold it (Set-CommittedFact).
function Save-RemovedFact([object[]]$Removed) {
    Set-CommittedFact 'instancesRemoved' @(ConvertTo-RemovedResult $Removed)
    Add-LibraryLog "TIA removed from the PLC: $(Format-RemovedList $Removed)."
}

function ConvertTo-RemovedResult([object[]]$Removed) {
    @($Removed | ForEach-Object {
        $one = @{ object = $_.object; device = $_.device; folder = $_.folder }
        foreach ($k in 'type', 'version', 'number', 'numberWas', 'unread') { if ($_[$k]) { $one[$k] = $_[$k] } }   # a data type has no number, a plain block no type
        $one
    })
}

function Format-RemovedList([object[]]$Removed) {
    @($Removed | ForEach-Object { "$($_.object) ($(if ($_.type) { "type $($_.type) $($_.version), " } else { 'no library type, ' })$(if ($_.folder) { "folder $($_.folder)" } else { 'top folder' }))" }) -join ', '
}

# What is gone holds nothing for the save rules under its own name: no compile by name could clear it. The update itself
# stays held until a compile of the scope, which is where what used it shows.
function Register-RemovedInstances($Session, $Update) {
    foreach ($r in @($Update.removed | Where-Object { $_ })) {
        Clear-ObjectWrites $Session 'plc' @($r.device) @(@($r.object) + @(if ($r.type) { "type:$($r.type)" }))
    }
}

function Format-RemovedInstances([object[]]$Removed, [bool]$Archived) {
    "TIA removed $(@($Removed).Count) from the PLC, as nothing uses them: $(Format-RemovedList $Removed). It does so on every update, as its own window does; the types stay in the library. " +
    $(if ($Archived) { 'The session archive is the way back.' } else { 'This session has no archive: closing without saving is the way back, until the next save.' })
}

# Why an update did not reach the project, or $null: it failed, or TIA refused its commit, so nothing of it was kept.
function Get-UpdateFailure($Update) {
    if ($Update.refused) { return [string]$Update.refused }
    if ($Update.commitError) { return "TIA refused the commit of the update, so nothing of it was kept: $($Update.commitError.message)" }
    $null
}

function Add-UpdateFacts($Result, $Update, $Session) {
    $removed = @($Update.removed | Where-Object { $_ })
    if ($removed.Count) {
        $Result.instancesRemoved = @(ConvertTo-RemovedResult $removed)
        $Result.summary += " $(Format-RemovedInstances $removed ([bool]$Session.archived))"
    }
    $numbers = @($Update.numbersChanged | Where-Object { $_ })
    if ($numbers.Count) {
        $Result.numbersChanged = @($numbers)
        $Result.summary += " Block numbers changed: $(@($numbers | Select-Object -First 10 | ForEach-Object { "$($_.object) $($_.from) -> $($_.to)" }) -join ', ')$(if ($numbers.Count -gt 10) { " and $($numbers.Count - 10) more (numbersChanged)" })."
    }
    $failure = Get-UpdateFailure $Update
    if ($failure) { $Result.ok = $false; $Result.updateRefused = $failure; $Result.summary += " The project was not updated: $failure" }
}

# Walks of the whole library stop at a time limit: after a release on 2026-10-05 a walk that took 5 s before
# ran for over 20 minutes and blocked the bridge. A stopped walk says so (complete = $false); progress goes to stderr.
# 180 s since 2026-10-06: on a real project (784 types) a walk took 20-38 s, and after a release in the same bridge process one
# walked only 264 types in 30 s, so the change report and the release chain gave up on a normal day.
$script:LibraryWalkBudgetMs = 180000

function Write-WalkProgress([string]$What, [int]$Walked, $Stopwatch) {
    if ($Walked % 100 -eq 0) { Write-BridgeLog "$What`: $Walked types in $($Stopwatch.ElapsedMilliseconds) ms" }
}

# Type name -> names of the types its version in work and its default version contain, together.
# A version in work reports no Dependencies at all (2026-10-06: typeUnitId 4.4.1 in work 0, released 4.4.0 4),
# so the in-work version alone dropped 91 of 133 dependents and gave the release chain no order.
# Returns @{ graph; complete; walked; ms }.
function Get-LibraryDependsOn($Library, [int]$BudgetMs = $script:LibraryWalkBudgetMs) {
    $sw = [Diagnostics.Stopwatch]::StartNew()
    $g = @{}; $walked = 0; $complete = $true
    foreach ($t in Get-GroupTree $Library.TypeFolder 'Types' 'Folders') {
        if ($sw.ElapsedMilliseconds -gt $BudgetMs) { $complete = $false; break }
        $versions = @($t.obj.Versions)
        $vs = @((Select-TypeVersion -Versions $versions -InWork), (Select-TypeVersion -Versions $versions) | Where-Object { $_ })
        $g[$t.name] = @($vs | ForEach-Object { try { $_.Dependencies | ForEach-Object { [string]$_.TypeObject.Name } } catch { } } | Sort-Object -Unique)
        $walked++; Write-WalkProgress 'dependency graph' $walked $sw
    }
    Write-BridgeLog "dependency graph: $walked types in $($sw.ElapsedMilliseconds) ms, complete=$complete"
    @{ graph = $g; complete = $complete; walked = $walked; ms = $sw.ElapsedMilliseconds }
}

# One line per library change in logs\library.log of the project repo: the history at a glance.
function Add-LibraryLog([string]$Line) {
    if (-not $script:Bridge.repo) { return }
    $f = Join-Path $script:Bridge.repo 'logs\library.log'
    [System.IO.File]::AppendAllText($f, "$((Get-Date).ToString('yyyy-MM-dd HH:mm')) $Line`r`n", (New-Object System.Text.UTF8Encoding $false))
}

function Get-LastLibraryLog {
    $f = Join-Path ([string]$script:Bridge.repo) 'logs\library.log'
    if ($script:Bridge.repo -and (Test-Path -LiteralPath $f)) { Get-Content -LiteralPath $f -Tail 1 -Encoding UTF8 }
}

# Returns @{ types (@{ type; folder; inWork }); complete; walked; ms }.
function Get-InWorkTypes($Library, [int]$BudgetMs = $script:LibraryWalkBudgetMs) {
    $sw = [Diagnostics.Stopwatch]::StartNew()
    $found = New-Object System.Collections.ArrayList; $walked = 0; $complete = $true
    foreach ($t in Get-GroupTree $Library.TypeFolder 'Types' 'Folders') {
        if ($sw.ElapsedMilliseconds -gt $BudgetMs) { $complete = $false; break }
        $w = Select-TypeVersion -Versions @($t.obj.Versions) -InWork
        if ($w) { [void]$found.Add(@{ type = $t.name; folder = $t.folder; inWork = [string]$w.VersionNumber }) }
        $walked++; Write-WalkProgress 'in-work types' $walked $sw
    }
    Write-BridgeLog "in-work types: $walked types in $($sw.ElapsedMilliseconds) ms, complete=$complete"
    @{ types = @($found); complete = $complete; walked = $walked; ms = $sw.ElapsedMilliseconds }
}

function Format-Instances($Instances) { @($Instances | ForEach-Object { @{ device = $_.device; kind = $_.kind; class = $_.class; name = $_.name } }) }

function Get-VersionList($Type) {
    @($Type.Versions | ForEach-Object { @{ version = [string]$_.VersionNumber; state = [string]$_.State; isDefault = $_.IsDefault } })
}

function Invoke-LibraryOpenTool($a) {
    $path = [string]$a.path
    if (-not $path) { return New-Refusal 'path is required (.al20 file of the global library).' }
    $full = [System.IO.Path]::GetFullPath($path)
    # TIA refuses it itself, with a window on the screen in a session that has one
    if ($full.Length -gt $script:TiaPathLimit) { return New-Refusal "$full has $($full.Length) characters: TIA opens a global library at a path of at most $script:TiaPathLimit. Ask the user to copy it to a shorter path." }
    $null = Get-TiaProject
    $lib = Get-GlobalLibraryList | Where-Object { $_.Path -and $_.Path.FullName -eq $full } | Select-Object -First 1
    $already = [bool]$lib
    if (-not $lib) {
        $mode = if (Get-OptionalBool $a 'writable' $false) { [Siemens.Engineering.OpenMode]::ReadWrite } else { [Siemens.Engineering.OpenMode]::ReadOnly }
        $lib = $script:Bridge.portal.GlobalLibraries.Open([System.IO.FileInfo]::new($full), $mode)
    }
    @{ ok = $true; library = $lib.Name; path = $full; alreadyOpen = $already; readOnly = [bool]$lib.IsReadOnly
       types = @(Get-GroupTree $lib.TypeFolder 'Types' 'Folders').Count; masterCopies = @(Get-GroupTree $lib.MasterCopyFolder 'MasterCopies' 'Folders').Count
       next = "list and export take library='$($lib.Name)'." }
}

# What documents would become a new library type, before TIA is touched: @{ name; class; format } or @{ refused }.
# File: entry of Resolve-ImportFiles. TIA goes by the name the document declares, not by the file's.
function Get-NewTypeDocument($File, [bool]$Safety) {
    if ($File.missing) { return @{ refused = "File not found: $($File.file)" } }
    if (Test-ReleasedExportPath $File.file) { return @{ refused = "$($File.file) is an export of a released version, for comparison only." } }
    $format = Get-LibraryTypeImportFormat $File
    if ($format -is [hashtable]) { return $format }
    $path = Join-Path ([System.IO.Path]::GetDirectoryName($File.file)) "$($File.name).$format"
    $why = Get-DocumentRefusal 'library_type' $path
    if ($why) { return @{ refused = $why } }
    $name = Get-DocumentDeclaredName $path
    $class = Get-DocumentObjectClass $path
    if (-not $name -or -not $class) { return @{ refused = "$path declares no object the bridge can read, so it cannot say what the type would be." } }
    if (-not $Safety -and (Test-FBlockDocument $path)) { return @{ refused = (Get-FBlockRefusal 'library_type' $name 'create') } }
    @{ name = $name; class = $class; format = $format }
}

# A new type from documents [PROBE] (2026-11-03): the target is the group of its test instance, which TIA makes with it;
# without one, or with the PlcSoftware, TIA answers "The selected target is invalid". The version comes up in work.
function Invoke-LibraryCreateTool($a) {
    $session = Get-BridgeSession
    $gate = Test-WriteAllowed $session
    if ($gate) { return New-Refusal $gate }
    if (-not $a.path) { return New-Refusal 'path is required: the .s7dcl or .xml of the new type.' }
    $null = Get-TiaProject   # binds the repo the path is relative to
    $file = @(Resolve-ImportFiles -Repo $script:Bridge.repo -KindDir 'library\types' -Paths @([string]$a.path))[0]
    $doc = Get-NewTypeDocument $file ($a.safety -eq $true)
    if ($doc.refused) { return New-Refusal $doc.refused }
    $lib = Get-TiaLibrary
    $taken = @(Get-GroupTree $lib.TypeFolder 'Types' 'Folders') | Where-Object { [string]$_.name -ieq $doc.name } | Select-Object -First 1
    if ($taken) { return New-Refusal "Library type '$($taken.name)' exists. library_edit_type puts it in work; nothing was created." }
    $entry = Get-TiaSoftwareEntry 'plc' ([string]$a.device)
    $plc = $entry.software
    $device = [string]$entry.device
    $root = if ($doc.class -eq 'type') { $plc.TypeGroup } else { $plc.BlockGroup }
    $target = [string]$a.target_folder
    $libraryFolder = [string]$a.library_folder
    $dir = [System.IO.DirectoryInfo]::new([System.IO.Path]::GetDirectoryName($file.file))
    $lineEnds = if ($doc.format -eq 's7dcl') { Repair-DocumentLineEnds $file.file }
    try {
        $w = Invoke-TiaWrite "create library type $($doc.name)" {
            $group = Get-OrCreateGroup $root $target 'Groups'
            $folder = Get-OrCreateGroup $lib.TypeFolder $libraryFolder 'Folders'
            $folder.Types.CreateFromDocuments($dir, $file.name, $group, [Siemens.Engineering.Library.LibraryImportOptions]::None)
        }
    }
    catch {
        # a failure that left no type holds nothing for the save rules, as a failed import of a new name
        if (-not (Test-TiaEndedError $_)) {
            $left = $null
            try { $left = @(Get-GroupTree $lib.TypeFolder 'Types' 'Folders') | Where-Object { [string]$_.name -ieq $doc.name } | Select-Object -First 1 } catch { $left = $true }
            if ($left) { Register-Write $session -Scope 'plc' -Device $device -Items @(@{ name = "type:$($doc.name)"; ok = $false }) }
        }
        throw
    }
    if ($w.commitError) { return @{ ok = $false; commitError = $w.commitError; rolledBack = [bool]$w.rolledBack; note = "TIA refused the commit: nothing of $($doc.name) was kept." } }
    $res = @($w.output)[-1]
    $tree = ConvertTo-ResultTree $res
    $state = [string]$res.TransferResultState
    $name = [string]$res.CreatedType.Name
    Register-Write $session -Scope 'plc' -Device $device -Items @(@{ name = "type:$name"; ok = $true })
    $e = Find-LibraryType $lib $name
    $work = Select-TypeVersion -Versions @($e.obj.Versions) -InWork
    $next = "compile scope blocks with names ['$name'], what it contains first. Change it through export and import of kind library_type, never by importing over its instance; library_release_type gives it its first released version, and only then the reviewed change can start; library_discard_type removes it while it is in work."
    $summary = "Library type $name V $($work.VersionNumber) created, in work, with its test instance in $device$(if ($target) { "/$target" })$(if ($state -ne 'Success') { " (state $state`: see messages)" }). Next: $next"
    Add-LibraryLog $summary
    $r = @{ ok = $true; summary = $summary; type = $name; class = $e.obj.GetType().Name; folder = $e.folder; version = [string]$work.VersionNumber; state = $state; messages = $tree
            instances = @(Format-Instances (Get-TypeInstances $work)); transaction = $w.transaction; next = $next }
    if ($name -ne $doc.name) { $r.note = "TIA named the type '$name'; the document declares '$($doc.name)'." }
    if ($lineEnds) { $r.lineEnds = $lineEnds }
    if ($w.note) { $r.transactionNote = $w.note }
    $r
}

# Why the version in work of a type must not be discarded, or $null. Discard takes the instance back to the released version,
# or away with the type, so it changes what is in the PLC as an import does.
function Get-DiscardRefusal([string]$Name, [object[]]$Instances, [bool]$Safety, [bool]$Knowhow) {
    foreach ($i in $Instances) {
        $o = $i.info.LibraryTypeInstance
        if (-not $Safety -and (Test-FBlockLanguage ([string]$o.ProgrammingLanguage))) { return Get-FBlockRefusal 'library_type' $Name 'discard' }
        if (-not $Knowhow -and $o.IsKnowHowProtected) { return Get-KnowHowRefusal 'library_type' $Name 'discard' }
    }
    $null
}

# Discard() of the version in work [PROBE] (2026-11-03): of the only version it removes the type and its test instance.
function Invoke-LibraryDiscardTool($a) {
    $session = Get-BridgeSession
    $gate = Test-WriteAllowed $session
    if ($gate) { return New-Refusal $gate }
    $lib = Get-TiaLibrary
    $e = Find-LibraryType $lib ([string]$a.name)
    $type = $e.obj
    $scope = Get-LibraryTypeScope $type
    # Edit of a faceplate type ended TIA (2026-10-06); its Discard was never tried
    if ($scope -eq 'hmi') { return New-Refusal "Type '$($e.name)' is an HMI type (faceplate); the user discards it in TIA." }
    $work = Select-TypeVersion -Versions @($type.Versions) -InWork
    if (-not $work) { return New-Refusal "Type '$($e.name)' has no version in work: nothing to discard." }
    $number = [string]$work.VersionNumber
    $why = Get-DiscardRefusal $e.name @(Get-TypeInstances $work) ($a.safety -eq $true) ($a.knowhow -eq $true)
    if ($why) { return New-Refusal $why }
    $devices = @(Get-TiaDeviceNames $scope)
    # read before the discard: a change with no changed type goes by what it has in work, and would read as closed without saving at its last one
    $change = Get-LiveChange $lib $e.name
    try { $w = Invoke-TiaWrite "discard library type $($e.name) V $number" { $work.Discard() } }
    catch { Register-LibraryTypeWrite $session $scope $devices "type:$($e.name)" $false; throw }
    if ($w.commitError) { return @{ ok = $false; commitError = $w.commitError; rolledBack = [bool]$w.rolledBack; note = "TIA refused the commit: $($e.name) V $number stays in work." } }
    $left = @(Get-GroupTree $lib.TypeFolder 'Types' 'Folders') | Where-Object { [string]$_.name -eq $e.name } | Select-Object -First 1
    if ($left) { Register-LibraryTypeWrite $session $scope $devices "type:$($e.name)" $true }
    else {
        # the type is gone, so nothing of that name is left to compile; what used it shows only in a compile of the
        # whole scope, as after a delete, so that much stays held, under what it is
        Clear-ObjectWrites $session $scope $devices @("type:$($e.name)")
        Register-LibraryTypeWrite $session $scope $devices "discarded:$($e.name)" $true
    }
    # the change of a discarded root ends with it; a type that only joined one leaves it
    $atDiscard = $null
    $endedWithIt = $null
    if ($change -and $change.root -eq $e.name -and -not (Test-ChangeAlive $lib $change)) {
        Set-ChangeAbandoned $script:Bridge.repo $change 'its version in work was discarded'
        $endedWithIt = $change.id
    }
    elseif ($change -and $change.types.Contains($e.name)) {
        # the changed type in work by a yes: its release stands, and the change could never read its end without it
        if ($e.name -eq $change.root -and [string]$change.leftBehindAnswer -eq 'yes') { Restore-RootAtYes $change }
        else { $change.types[$e.name].inWork = ''; $change.types[$e.name].inWorkBy = '' }
        $atDiscard = Update-ChangeAtDiscard $lib $change
    }
    $summary = if ($left) { "$($e.name) V $number discarded; the released version stays." } else { "$($e.name) V $number discarded; it was the only version, so the type and its test instance are gone." }
    # a version in work lists no dependencies, so TIA and the bridge cannot name what used it [PROBE]: a type on it just stops compiling
    $next = if ($left) { "compile scope blocks with names ['$($e.name)'], and what used the version in work." } else { 'compile the plc scope: what used it shows there, and a compile by name cannot clear what is gone.' }
    Add-LibraryLog $summary
    $r = @{ ok = $true; summary = "$summary Next: $next"; type = $e.name; discarded = $number; typeRemoved = -not [bool]$left; next = $next; transaction = $w.transaction }
    if ($left) { $r.versions = @(Get-VersionList $left.obj) }
    if ($atDiscard) {
        $said = Format-ChangeAtDiscard $atDiscard
        $r.summary += " $said"
        $r.next += " $said"
        $r.status = $atDiscard.record.status
        $r.report = $atDiscard.report
        if (@($atDiscard.stale | Where-Object { $_ }).Count) { $r.stale = @($atDiscard.stale) }
        Add-LeftBehindFacts $r $lib $atDiscard.read $atDiscard.record
    }
    if ($endedWithIt) {
        $said = "Library change $endedWithIt ended with it, as abandoned. If the released version stands on old versions of what it contains, library_update_usages removes an instance nothing uses, and the type is then on the list again."
        $r.summary += " $said"
        $r.next += " $said"
        $r.status = 'abandoned'
        Add-LeftBehindFacts $r $lib
    }
    $r
}

function Test-PlcDataLibraryType($Type) { $Type.GetType().Name -match 'PlcType' }

# CreateFrom keeps the number the type's block had, also when a block of the PLC holds it, and the next compile settles that
# by moving one of them, the user's too [PROBE] (2026-11-03). So a new block whose number is held takes a free one first. FBs, FCs and DBs
# number apart, all DBs as one. Records: Get-PlcObjectRecords. New: their keys. Returns @(@{ key; from; to }).
function Get-NumberMoves([hashtable]$Records, [string[]]$New) {
    $space = { param($r) if ([string]$r.class -match 'DB$') { "$($r.device)`tDB" } else { "$($r.device)`t$($r.class)" } }
    $used = @{}
    foreach ($k in $Records.Keys) {
        $r = $Records[$k]
        if ($r.number -and $New -notcontains $k) { $used["$(& $space $r)`t$($r.number)"] = $true }
    }
    foreach ($k in @($New | Sort-Object)) {
        $r = $Records[$k]
        if (-not $r.number) { continue }
        $sp = & $space $r
        if (-not $used["$sp`t$($r.number)"]) { $used["$sp`t$($r.number)"] = $true; continue }
        $numbers = @($used.Keys | Where-Object { $_.StartsWith("$sp`t") } | ForEach-Object { [int]($_ -split "`t")[-1] })
        $free = ($numbers | Measure-Object -Maximum).Maximum + 1
        if ($free -gt 59999) { $free = 1; while ($numbers -contains $free) { $free++ } }
        $used["$sp`t$free"] = $true
        @{ key = $k; from = $r.number; to = $free }
    }
}

function Format-NumbersMoved([object[]]$Records) {
    $moved = @($Records | Where-Object { $_.numberWas })
    if (-not $moved.Count) { return '' }
    " Taken a free number, as a block of the PLC holds its own: $(@($moved | Select-Object -First 10 | ForEach-Object { "$($_.object) $($_.numberWas) -> $($_.number)" }) -join ', ')$(if ($moved.Count -gt 10) { " and $($moved.Count - 10) more" })."
}

# Makes an instance of a type that has none, from the version given, and puts it in work, in one transaction [PROBE]
# (2026-11-03). What it contains comes along as copies <name>_1 on the versions this version was built with, when the
# project holds those types on newer ones. Folder: default the type's folder in the library.
# It adds to the PLC and nothing else: a call that would change or take an object there is taken back, and a new block takes a free
# number when its own is held (Get-NumberMoves), which needs automatic numbering off for that moment: Number is refused while it is on [PROBE].
# Temporary: only the instance, not in work, for library_left_behind. Refused then when what comes is know-how protected, and when the
# instance does not get the type's name, as a plain object holds it: that name would go into the type's next version [PROBE] (2026-11-03).
# A refusal takes it all back; without a transaction nothing does: then standing names what is there, and the caller holds it for the save.
# Returns @{ instance; copies; objects } of Get-PlcObjectRecords records, or @{ refused; standing }, or @{ commitError }.
function New-TypeInstanceInWork($Entry, $Version, [string]$Folder, [string]$Device, [bool]$Safety, [switch]$Temporary) {
    $software = Get-TiaSoftwareEntry 'plc' $Device
    $isData = Test-PlcDataLibraryType $Entry.obj
    $root = $(if ($isData) { $software.software.TypeGroup } else { $software.software.BlockGroup })
    $items = $(if ($isData) { 'Types' } else { 'Blocks' })
    $target = $(if ($Folder) { $Folder } else { [string]$Entry.folder })
    $before = Get-PlcObjectRecords
    # the blocks as they were before anything was made, for what the next update says about their numbers: a compile comes in between
    if (-not $script:NumberBaseline -or $script:NumberBaseline.project -ne $script:Bridge.projectPath) { $script:NumberBaseline = @{ project = $script:Bridge.projectPath; records = $before } }
    $newRecords = New-Object System.Collections.ArrayList
    $fBlocks = New-Object System.Collections.ArrayList
    $protected = New-Object System.Collections.ArrayList
    $touched = New-Object System.Collections.ArrayList
    $otherName = New-Object System.Collections.ArrayList
    $heldNumber = New-Object System.Collections.ArrayList
    try {
        $w = Invoke-TiaWrite "instance of library type $($Entry.name)$(if (-not $Temporary) { ', in work' })" -RollbackIf { $fBlocks.Count -gt 0 -or $protected.Count -gt 0 -or $touched.Count -gt 0 -or $otherName.Count -gt 0 -or $heldNumber.Count -gt 0 } -Body {
            $null = (Get-OrCreateGroup $root $target 'Groups').$items.CreateFrom($Version, [Siemens.Engineering.Library.Types.UpdatePathsMode]::KeepExistingPathsInTarget)
            $now = Get-PlcObjectRecords
            foreach ($k in @($now.Keys | Where-Object { -not $before.ContainsKey($_) } | Sort-Object)) {
                [void]$newRecords.Add($now[$k])
                if (-not $Safety -and (Test-FBlockLanguage ([string]$now[$k].language))) { [void]$fBlocks.Add($now[$k].object) }
                if ($Temporary -and $now[$k].knowhow) { [void]$protected.Add($now[$k].object) }
                if ($Temporary -and $now[$k].type -eq $Entry.name -and $now[$k].object -ne $Entry.name) { [void]$otherName.Add($now[$k].object) }
            }
            foreach ($k in @($before.Keys)) {
                if (-not $now.ContainsKey($k) -or [string]$now[$k].type -ne [string]$before[$k].type -or [string]$now[$k].version -ne [string]$before[$k].version) { [void]$touched.Add($before[$k].object) }
            }
            $moves = @(Get-NumberMoves $now @($now.Keys | Where-Object { -not $before.ContainsKey($_) }))
            # a protected block takes no other number: TIA answers that set_AutoNumber is not supported [PROBE] (2026-11-03)
            foreach ($m in $moves) { if ($now[$m.key].knowhow) { [void]$heldNumber.Add("$($now[$m.key].object), number $($m.from)") } }
            if ($moves.Count -and -not $protected.Count -and -not $heldNumber.Count) {
                $blocks = @{}; foreach ($e in Get-GroupTree $software.software.BlockGroup 'Blocks' 'Groups') { $blocks[[string]$e.name] = $e.obj }
                foreach ($m in $moves) {
                    $r = $now[$m.key]
                    $o = $blocks[[string]$r.object]
                    # with automatic numbering left off the document says S7_BlockNumber, and a release would keep that as a fixed number
                    $auto = $o.AutoNumber
                    $o.AutoNumber = $false
                    $o.Number = [int]$m.to
                    $o.AutoNumber = $auto
                    $r.numberWas = $m.from; $r.number = $m.to
                }
            }
            if (-not $Temporary -and -not $fBlocks.Count -and -not $touched.Count -and -not $heldNumber.Count) {
                $found = @($Version.FindInstances($software.software))
                $null = $Version.Edit($found[0])
            }
        }
    }
    catch {
        # a transaction took it back; without one what it had made stands, so look: the caller holds it for the save (Data standing)
        if (-not (Test-TiaEndedError $_)) {
            $left = $null
            try { $after = Get-PlcObjectRecords; $left = @($after.Keys | Where-Object { -not $before.ContainsKey($_) } | Sort-Object | ForEach-Object { $after[$_] }) }
            catch { Write-BridgeLog "What the failed instance left was not read: $($_.Exception.Message)" }
            if (@($left).Count) {
                Set-CommittedFact 'objectsStanding' @(ConvertTo-RemovedResult $left)
                $_.Exception.Data['standing'] = @($left)
                Add-LibraryLog "A failed instance of $($Entry.name) left in the PLC: $(Format-RemovedList $left)."
            }
        }
        throw
    }
    $why = $null
    if ($fBlocks.Count) { $why = Get-FBlockRefusal 'library_type' $Entry.name "instance of it ($($fBlocks -join ', '))" }
    elseif ($protected.Count) { $why = "know-how protected ($($protected -join ', ')): its code cannot be changed without the password, so it cannot move to the new versions here." }
    elseif ($heldNumber.Count) { $why = "know-how protected ($($heldNumber -join '; ')): a block of the PLC holds that number, and a protected block cannot take another without the password. Move the other block to a free number, or leave the type." }
    elseif ($otherName.Count) { $why = "the name $($Entry.name) is taken in the PLC by an object that is not its instance, so TIA would name the instance $($otherName -join ', ') and that name would go into its next version. Rename that object, or leave the type." }
    elseif ($touched.Count) { $why = "its instance would change what is already in the PLC ($($touched -join ', '))." }
    if ($why) {
        if ($w.rolledBack) { return @{ refused = "$why Taken back." } }
        $standing = @($newRecords) + @($before.Values | Where-Object { $touched -contains $_.object })
        return @{ refused = "$why Without a transaction this was not taken back: $(@($standing | ForEach-Object { $_.object } | Sort-Object) -join ', ') stand as it left them, held for the save, until each is deleted or written again."; standing = $standing }
    }
    if ($w.commitError) { return @{ commitError = $w.commitError } }
    $instance = @($newRecords | Where-Object { $_.type -eq $Entry.name })[0]
    @{ instance = $instance; copies = @($newRecords | Where-Object { $_.type -ne $Entry.name }); objects = @($newRecords) }
}

# What a refusal left without a transaction: there, and no write that went right, so a save stops at it.
function Register-ObjectsStanding($Session, $Made) {
    foreach ($o in @($Made.standing | Where-Object { $_ })) { Register-Write $Session -Scope 'plc' -Device $o.device -Items @(@{ name = $o.object; ok = $false }) }
}

# Said at once: the log and the result of any failure later in the call hold it (Set-CommittedFact).
function Save-InstanceMadeFact($Made) {
    Set-CommittedFact 'instanceMade' @(ConvertTo-RemovedResult @($Made.instance))[0]
    if (@($Made.copies).Count) { Set-CommittedFact 'copiesMade' @(ConvertTo-RemovedResult @($Made.copies)) }
    Add-LibraryLog "An instance made in the PLC: $(Format-RemovedList @(@($Made.instance) + @($Made.copies)))."
}

function Save-FoldersMadeFact([object[]]$Folders) {
    if (-not @($Folders).Count) { return }
    Set-CommittedFact 'foldersMade' @($Folders)
    Add-LibraryLog "Folders made in the PLC: $(Format-FolderList $Folders)."
}

function Format-OnOldList([object[]]$OnOld) {
    "$(@($OnOld | Select-Object -First 10) -join ', ')$(if (@($OnOld).Count -gt 10) { " and $(@($OnOld).Count - 10) more (onOldVersions)" })"
}

function Format-InstanceMade([string]$Type, $Instance, [object[]]$Copies) {
    $s = "It had no instance, so one was made: $(Format-RemovedList @($Instance)).$(Format-NumbersMoved (@($Instance) + @($Copies)))"
    if (@($Copies).Count) {
        $s += " Made with it, as this version was built on older versions of what it contains: $(Format-RemovedList @($Copies | Select-Object -First 10))$(if (@($Copies).Count -gt 10) { " and $(@($Copies).Count - 10) more (copiesMade)" }); the project now holds two versions of those. " +
              "library_update_usages moves $Type to the new versions and TIA removes the copies, as nothing uses them then; until that update it cannot be released."
    }
    $s + " If nothing uses $Type once it is released, the next update removes its instance again."
}

function Invoke-LibraryEditTool($a) {
    $session = Get-BridgeSession
    $gate = Test-WriteAllowed $session
    if ($gate) { return New-Refusal $gate }
    $e = Find-LibraryType (Get-TiaLibrary) ([string]$a.name)
    $type = $e.obj
    $scope = Get-LibraryTypeScope $type
    $devices = @(Get-TiaDeviceNames $scope)
    $work = Select-TypeVersion -Versions @($type.Versions) -InWork
    $created = $false
    $from = Select-TypeVersion -Versions @($type.Versions)
    $yesInWork = Get-EditYesRefusal (Get-TiaLibrary) $e.name
    if ($yesInWork) { return New-Refusal $yesInWork }
    if (-not $work -and $scope -eq 'hmi') {
        # Edit(LibraryTypeInstanceInfo) of a faceplate type crashed TIA V20 Update 7 (NonRecoverableException,
        # "Unexpected exception - no exception message available", 2026-10-06 16:04)
        return New-Refusal "Type '$($e.name)' is an HMI type (faceplate); putting it in work through Openness crashed TIA (2026-10-06). The user puts it in work and updates it in TIA."
    }
    if (-not $work) {
        # Edit() without an instance fails with no message on V20; Edit(LibraryTypeInstanceInfo) works [PROBE] (2026-10-04).
        # The bridge changes a type through a project instance anyway.
        $instances = @(Get-TypeInstances $from)
        if ($a.instance) { $instances = @($instances | Where-Object { $_.name -eq [string]$a.instance }) }
        if (-not $instances.Count -and $a.instance) {
            return New-Refusal "Type '$($e.name)' V $($from.VersionNumber) has no instance named '$($a.instance)' in this project; nothing was put in work."
        }
        if (-not $instances.Count -and (Test-TypeHasInstance (Get-TiaLibrary) $e.name)) {
            # on an older version, or a read that failed: making one would be a second instance of the type in the PLC
            $elsewhere = @(foreach ($v in @($type.Versions)) { foreach ($i in Get-TypeInstances $v) { "$($i.name) on $($v.VersionNumber)" } })
            return New-Refusal ("Type '$($e.name)' V $($from.VersionNumber) has no instance, but the type has: $(if ($elsewhere.Count) { $elsewhere -join ', ' } else { 'which, could not be read' }). Nothing was made or put in work. " +
                                'library_update_usages moves an instance to the default version; TIA removes it if nothing uses it, then this makes one.')
        }
        if (-not $instances.Count) {
            # an update removes what nothing uses, and Edit needs an instance: make one and put it in work, as one write
            $plc = Get-TiaSoftwareEntry 'plc' ([string]$a.device)
            $foldersBefore = @(Get-PlcFolderPaths $plc.software)
            try { $madeHere = New-TypeInstanceInWork $e $from ([string]$a.target_folder) ([string]$a.device) ($a.safety -eq $true) }
            catch { Register-ObjectsStanding $session @{ standing = $_.Exception.Data['standing'] }; throw }
            if ($madeHere.refused) { Register-ObjectsStanding $session $madeHere; return New-Refusal $madeHere.refused }
            if ($madeHere.commitError) { return @{ ok = $false; commitError = $madeHere.commitError; rolledBack = $true; note = "TIA refused the commit: nothing of $($e.name) was made." } }
            foreach ($o in $madeHere.objects) { Register-Write $session -Scope 'plc' -Device $o.device -Items @(@{ name = $o.object; ok = $true }) }
            Save-InstanceMadeFact $madeHere   # first: what the read below may throw must not hide it
            $foldersMade = @(Get-FoldersMadeSince $foldersBefore $plc)
            Save-FoldersMadeFact $foldersMade
        }
        else {
            $info = $instances[0].info
            try { $null = Invoke-TiaWrite "edit library type $($e.name)" { $from.Edit($info) } }
            catch { Register-LibraryTypeWrite $session $scope $devices "type:$($e.name)" $false; throw }
        }
        $work = Select-TypeVersion -Versions @($type.Versions) -InWork
        $created = $true
        Register-LibraryTypeWrite $session $scope $devices "type:$($e.name)" ([bool]$work)
    }
    $graph = Get-LibraryDependsOn (Get-TiaLibrary)
    $dependents = @(Get-TypeDependents -DependsOn $graph.graph -Name $e.name | Sort-Object)
    $next = 'export kind library_type, edit the files, import them with kind library_type, compile, then library_release_type. Do not import over the instances: TIA cannot replace a test instance.'
    $summaryNext = 'export kind library_type, edit, import kind library_type, compile, library_release_type.'
    if ($madeHere -and @($madeHere.copies).Count) {
        # an export now reads the copies' names; an import brings them back from any document, and says so (copiesBack)
        $summaryNext = "compile, library_update_usages with $(Format-TypesArgument @($madeHere.copies | ForEach-Object { [string]$_.type } | Sort-Object -Unique) 'copiesMade'), compile, and only then export kind library_type, edit, import kind library_type, compile, library_release_type."
        $next = "$summaryNext An export before that update reads the names of the copies, and a version made from that document cannot be released. An import brings the copies back from any document, and names them (copiesBack); the next update removes them. Do not import over the instances: TIA cannot replace a test instance."
    }
    $summary = Format-LibrarySummary -Action 'put in work' -Type $e.name -From ([string]$from.VersionNumber) -To ([string]$work.VersionNumber) -Dependents $dependents `
        -Next $summaryNext -IncompleteAfter $(if ($graph.complete) { 0 } else { $graph.walked })
    $change = if ($work) { Register-ChangeOnEdit (Get-TiaLibrary) $e ([string]$from.VersionNumber) ([string]$work.VersionNumber) $graph $dependents }
    if ($change.joined) { $summary += " Joined library change $($change.id) (put in work by the bridge); report: $($change.report)." }
    elseif ($change.report) { $summary += " Library change report: $($change.report) (one checkbox per dependent type)." }
    elseif ($change.note) { $summary += " $($change.note)" }
    $changeFacts = $(if ($change) { Format-EditChangeFacts $change })
    if ($changeFacts) { $summary += " $changeFacts" }
    if ($madeHere) {
        $madeText = Format-InstanceMade $e.name $madeHere.instance $madeHere.copies
        if (@($foldersMade).Count) {
            $madeText += " Folders made: $(Format-FoldersCapped $foldersMade 'foldersMade'). Once TIA has removed what stands in them, delete_folder takes them."
            if ($change.id) { Add-ChangeFolders $change.id $foldersMade }
        }
        $summary += " $madeText"
        $next = "$next $madeText"
    }
    if ($created) { Add-LibraryLog $summary }
    $edited = @{ ok = [bool]$work; summary = $summary; type = $e.name; folder = $e.folder; inWork = [string]$work.VersionNumber; created = $created
       dependents = $dependents; instances = @(Format-Instances (Get-TypeInstances $work)); versions = @(Get-VersionList $type); next = $next
       change = $(if ($change) { $change.id }); report = $(if ($change) { $change.report }) }
    if ($change -and @($change.superseded | Where-Object { $_ }).Count) { $edited.superseded = @($change.superseded) }
    if ($madeHere) {
        $edited.instanceMade = @(ConvertTo-RemovedResult @($madeHere.instance))[0]
        if (@($madeHere.copies).Count) { $edited.copiesMade = @(ConvertTo-RemovedResult @($madeHere.copies)) }
        if (@($foldersMade).Count) { $edited.foldersMade = @($foldersMade) }
    }
    $edited
}

function Invoke-LibraryReleaseTool($a) {
    $session = Get-BridgeSession
    $gate = Test-WriteAllowed $session
    if ($gate) { return New-Refusal $gate }
    $comment = [string]$a.comment
    if (-not $comment) { return New-Refusal 'comment is required: what changed in this version.' }
    $e = Find-LibraryType (Get-TiaLibrary) ([string]$a.name)
    $type = $e.obj
    $work = Select-TypeVersion -Versions @($type.Versions) -InWork
    if (-not $work) { return New-Refusal "Type '$($e.name)' has no version in work: call library_edit_type first." }
    $number = Get-ReleaseVersion -Versions @($type.Versions) -Requested ([string]$a.version)
    $previous = [string](Select-TypeVersion -Versions @($type.Versions)).VersionNumber
    $author = if ($script:Bridge.settings.author) { [string]$script:Bridge.settings.author } else { $env:USERNAME }
    $mode = [Siemens.Engineering.Library.Types.CreateOrReleaseDependenciesMode]::AutomaticallyCreateOrReleaseDependenciesIfRequired
    $scope = Get-LibraryTypeScope $type
    $devices = @(Get-TiaDeviceNames $scope)
    # this mode takes the contained types in work along and makes types of plain objects, and TIA says neither: compare around it
    $inWorkBefore = Get-InWorkTypes (Get-TiaLibrary)
    $typesBefore = Get-LibraryTypeMap (Get-TiaLibrary)
    $seen = New-Object System.Collections.ArrayList
    $made = New-Object System.Collections.ArrayList
    $onOld = New-Object System.Collections.ArrayList
    try {
        $w = Invoke-TiaWrite "release library type $($e.name) V $number" -RollbackIf { $made.Count -gt 0 -or $onOld.Count -gt 0 } -Body {
            $work.Release($mode, [version]$number, $author, $comment)
            $around = Compare-LibraryAroundRelease (Get-TiaLibrary) $typesBefore @($inWorkBefore.types | ForEach-Object { $_.type }) @($e.name)
            foreach ($n in $around.alsoReleased) { [void]$seen.Add($n) }
            foreach ($n in $around.made) { [void]$made.Add($n) }
            # a released version cannot be taken back: on old versions of what it contains it would only burn a number
            foreach ($u in @(Get-VersionOldUses $type $number)) { [void]$onOld.Add($u) }
        }
    }
    catch { Register-LibraryTypeWrite $session $scope $devices "type:$($e.name)" $false; throw }
    if ($made.Count -and $w.rolledBack) {
        $why = "Release of $($e.name) refused: $(Format-MadeTypesWayOut @($made))"
        Add-LibraryLog $why
        return @{ ok = $false; summary = $why; refused = $why; wouldMakeTypes = @($made); rolledBack = $true; transaction = $w.transaction }
    }
    if ($onOld.Count -and $w.rolledBack) {
        $why = "Release of $($e.name) refused: this version sits on old versions of what it contains: $(@($onOld) -join ', '). Released it would burn a version. Nothing was released. " +
               'library_update_usages with those types moves it to the new versions; compile, and release it then.'
        Add-LibraryLog $why
        return @{ ok = $false; summary = $why; refused = $why; onOldVersions = @($onOld); rolledBack = $true; transaction = $w.transaction }
    }
    Register-LibraryTypeWrite $session $scope $devices "type:$($e.name)" $true
    $alsoReleased = @(foreach ($n in $seen) {
        Register-LibraryTypeWrite $session $scope $devices "type:$n" $true
        @{ type = [string]$n; version = [string](@($inWorkBefore.types | Where-Object { $_.type -eq $n })[0].inWork) }
    })
    # the types containing it still hold the previous version: they are found through the dependency graph
    $graph = Get-LibraryDependsOn (Get-TiaLibrary)
    $dependents = @(Get-TypeDependents -DependsOn $graph.graph -Name $e.name | Sort-Object)
    # TIA can put what contains it in work without a word: read after the commit, so a result names what stands, not what is expected
    $inWorkAfter = Get-InWorkTypes (Get-TiaLibrary)
    $newKnown = [bool]($inWorkBefore.complete -and $inWorkAfter.complete)
    $alsoInWork = @(if ($newKnown) { Get-TypesNewlyInWork @($inWorkBefore.types) @($inWorkAfter.types) })
    $next = if ($previous) { 'library_update_usages, then compile.' } else { "compile scope blocks with names ['$($e.name)']: a released instance reads not consistent until then. Release what uses it next." }
    if ($dependents.Count -or -not $graph.complete) {
        $next = Format-NextAfterRelease $e.name @($dependents | Where-Object { @($inWorkAfter.types | ForEach-Object { $_.type }) -contains $_ }) ([bool]$inWorkAfter.complete)
    }
    $summary = Format-LibrarySummary -Action 'released' -Type $e.name -From $previous -To $number -Dependents $dependents -Next $next `
        -IncompleteAfter $(if ($graph.complete) { 0 } else { $graph.walked })
    $releasedMap = @{ $e.name = $number }
    foreach ($x in $alsoReleased) { $releasedMap[$x.type] = $x.version }
    $atRelease = Update-ChangeAtRelease (Get-TiaLibrary) $releasedMap @($inWorkAfter.types)
    $report = $(if ($atRelease) { $atRelease.report } else { '' })
    if ($alsoReleased.Count) { $summary += " Released with it, as it contains them: $(@($alsoReleased | ForEach-Object { "$($_.type) $($_.version)" }) -join ', ')." }
    if (-not $inWorkBefore.complete) { $summary += " Whether it took contained types along is not known: the library walk stopped at its time limit." }
    if ($alsoInWork.Count) { $summary += " In work now, not before this release: $(Format-TypeVersionsCapped $alsoInWork)." }
    if (-not $inWorkAfter.complete) { $summary += " Which types are in work now is not known: the library walk stopped at its time limit." }
    elseif (-not $newKnown -and @($inWorkAfter.types).Count) { $summary += " In work now: $(Format-TypeVersionsCapped @(Get-TypesNewlyInWork @() @($inWorkAfter.types))); which of them are new since before this release is not known: the library walk before it stopped at its time limit." }
    if ($report) { $summary += " Change report: $report." }
    $r = @{ ok = $true; summary = $summary; type = $e.name; released = $number; author = $author; versions = @(Get-VersionList $type)
            dependents = $dependents; next = $next; report = $report }
    if ($alsoReleased.Count) { $r.alsoReleased = @($alsoReleased) }
    if ($alsoInWork.Count) { $r.alsoInWork = @($alsoInWork) }
    if ($made.Count) { $r.typesMade = @($made); $r.summary += " Without a transaction TIA made library types nobody asked for: $(@($made) -join ', ')." }
    if ($onOld.Count) { $r.onOldVersions = @($onOld); $r.summary += " Without a transaction it was released on old versions of what it contains: $(@($onOld) -join ', ')." }
    if ($atRelease) {
        if ($atRelease.record.status -in 'done', 'left-behind') {
            $cleanup = Format-FolderCleanup $atRelease.record
            $r.next += $cleanup; $r.summary += $cleanup
            $r.status = $atRelease.record.status
        }
        Add-LeftBehindFacts $r (Get-TiaLibrary) $atRelease.read $atRelease.record
    }
    Add-LibraryLog $r.summary
    $r
}

function Invoke-LibraryUpdateTool($a) {
    $session = Get-BridgeSession
    $gate = Test-WriteAllowed $session
    if ($gate) { return New-Refusal $gate }
    $unsafe = Get-SafetyProgramRefusal 'library_update_usages' $a.safety
    if ($unsafe) { return New-Refusal $unsafe }
    $project = Get-TiaProject
    $libName = [string]$a.library
    $lib = Get-TiaLibrary $libName
    $names = @($a.types | Where-Object { $_ })
    foreach ($n in $names) { $null = Find-LibraryType $lib $n }
    $scopes = Get-UpdateScopes
    $written = @(Get-TiaSoftwareList | Group-Object { $_.kind })   # UpdateProject gets every device (Get-UpdateScopes)
    try {
        $update = Invoke-ProjectUpdate $lib $names {
            param($selection)
            if ($libName) { $lib.UpdateProject($selection, $scopes) }
            else { $lib.UpdateProject($selection, $scopes, [Siemens.Engineering.Library.Types.DeleteUnusedVersionsMode]::DoNotDelete) }
        } "update the project from library $(if ($libName) { $libName } else { 'project library' })"
    }
    catch { foreach ($sc in $written) { Register-Write $session -Scope $sc.Name -Device @($sc.Group | ForEach-Object { $_.device }) -Items @(@{ name = 'library update'; ok = $false }) }; throw }
    $failure = Get-UpdateFailure $update
    if ($failure) { return New-Refusal $failure }
    foreach ($sc in $written) { Register-Write $session -Scope $sc.Name -Device @($sc.Group | ForEach-Object { $_.device }) -Items @(@{ name = 'library update'; ok = $true }) }
    Register-RemovedInstances $session $update
    $check = ConvertTo-ResultTree ($project.ProjectLibrary.UpdateCheck($project, [Siemens.Engineering.Library.Types.UpdateCheckMode]::ReportOutOfDateOnly))
    # updating to a new version of a type puts the data types containing it in work (2026-10-05: 29 for one UDT);
    # library blocks using it are not put in work: the chain finds them through the compile
    $work = Get-InWorkTypes $project.ProjectLibrary
    $inWork = @($work.types)
    $source = if ($names.Count) { $names -join ', ' } else { 'all types' }
    if (-not $work.complete) {
        $next = 'tia_status to see the types in work, compile, then library_release_chain.'
        $summary = "Project updated from $source. The types in work were not counted: the library walk stopped after $($work.walked) types (time limit). Next: $next"
    } elseif ($inWork.Count) {
        $shown = @($inWork | Select-Object -First 3 | ForEach-Object { $_.type }) -join ', '
        if ($inWork.Count -gt 3) { $shown += ', ...' }
        $next = 'compile plc and hmi; fix what does not compile (export/import kind library_type); then library_release_chain.'
        $summary = "Project updated from $source. $($inWork.Count) library types are in work ($shown). Next: $next"
    } else {
        $next = 'compile the plc and hmi scopes, then save.'
        $summary = "Project updated from $source. No library type is in work. Next: $next"
    }
    # a reviewed library change: what TIA put in work, and the library blocks it left out put in work too
    $change = if (-not $libName) { Update-ChangeAfterUpdate $lib $inWork (Get-OptionalBool $a 'put_left_out_in_work' $true) $session }
    if ($change -and $change.ended) { Add-LibraryLog $change.ended.note; $change.ended.summary = $change.ended.note; return $change.ended }
    if (-not $change -and -not $libName -and $script:Bridge.repo) { $summary += ' It belongs to no open library change.' }
    if ($change) {
        $next = $(if ($change.status -in 'done', 'left-behind') { Format-ChangeEndNext $change.record }
                  else { 'compile, then library_review; ask the user to approve per type (library_approve); then library_release_chain.' })
        $summary = "Project updated from $source. Library change $($change.id): TIA put $(@($change.byTia).Count) of its types in work" +
                   $(if (@($change.standing).Count) { ", $(@($change.standing).Count) stood in work before this update ($(Format-NamesCapped @($change.standing)))" }) +
                   $(if (@($change.byBridge).Count) { ", the bridge put $(@($change.byBridge).Count) more that TIA leaves out ($(@($change.byBridge) -join ', '))" }) +
                   $(if (@($change.failed).Count) { "; could not put in work: $(@($change.failed | ForEach-Object { "$($_.type) ($($_.error))" }) -join '; ')" }) +
                   ". Report: $($change.report). Next: $next"
    }
    $r = @{ ok = -not ($change -and @($change.failed).Count); summary = $summary; sources = $(if ($names.Count) { $names } else { @('all types') }); inWork = $inWork
            inWorkComplete = $work.complete; outOfDate = $check; next = $next; change = $(if ($change) { $change.id }); report = $(if ($change) { $change.report }) }
    Add-UpdateFacts $r $update $session
    if (-not $libName) { Add-LeftBehindFacts $r $lib $(if ($change) { $change.leftBehindRead }) $(if ($change) { $change.record }) }
    Add-LibraryLog $r.summary
    $r
}

# Next step after a release chain. Types already in work before the chain and left out of it (types=...) are
# named apart: they are someone else's work, not a next level of the chain (2026-10-06).
function Format-ReleaseChainNext([string[]]$After, [string[]]$Outside, [int]$CompileErrors) {
    $new = @($After | Where-Object { $_ -and $Outside -notcontains $_ })
    $kept = @($After | Where-Object { $_ -and $Outside -contains $_ })
    $s = if ($new.Count) { "$($new.Count) types are in work after the update ($(($new | Sort-Object) -join ', ')): compile, fix, then library_release_chain again." }
         elseif ($CompileErrors) { "the PLC has $CompileErrors compile errors: fix them (blocks, or library types through library_edit_type), compile, then save." }
         else { 'save, then commit the project repo.' }
    if ($kept.Count) { $s += " Still in work from before, not part of this chain: $(($kept | Sort-Object) -join ', ')." }
    $s
}

function Invoke-LibraryReleaseChainTool($a) {
    $session = Get-BridgeSession
    $gate = Test-WriteAllowed $session
    if ($gate) { return New-Refusal $gate }
    $comment = [string]$a.comment
    if (-not $comment) { return New-Refusal 'comment is required: what changed in this chain of versions.' }
    $unsafe = Get-SafetyProgramRefusal 'library_release_chain' $a.safety
    if ($unsafe) { return New-Refusal $unsafe }
    $lib = Get-TiaLibrary
    $work = Get-InWorkTypes $lib
    if (-not $work.complete) { return New-Refusal "The library walk stopped after $($work.walked) types (time limit), so the chain is not known. Nothing released." }
    $allInWork = @($work.types | ForEach-Object { $_.type })
    $inWork = $allInWork
    if ($a.types) { $inWork = @($inWork | Where-Object { @($a.types) -contains $_ }) }
    $graph = Get-LibraryDependsOn $lib
    if (-not $graph.complete) { return New-Refusal "The dependency graph stopped after $($graph.walked) types (time limit). Nothing released." }

    # an open library change: only the types the user approved, and only once what they contain is released
    $change = if (-not $a.types) { Get-LiveChange $lib }
    $set = $null
    if ($change) {
        Update-ChangeInWork $change @($work.types) 'tia'
        $set = Get-ApprovedReleaseSet $change $graph.graph
        $inWork = @($set.order)
        if (-not $inWork.Count) {
            $why = @()
            if (@($set.waiting).Count) { $why += "waiting for contained types: $(@($set.waiting | ForEach-Object { "$($_.type) (for $($_.for -join ', '))" }) -join '; ')" }
            if (@($set.notApproved).Count) { $why += "not approved: $($set.notApproved -join ', ')" }
            $report = Save-ChangeRecord $script:Bridge.repo $change
            if (-not $why.Count) { $why += 'no type of it is in work unreleased' }
            $nothing = @{ ok = $false; summary = "Nothing to release in library change $($change.id): $($why -join '. '). Report: $report."
                          waiting = @($set.waiting); notApproved = @($set.notApproved); report = $report }
            Add-LeftBehindFacts $nothing $lib
            return $nothing
        }
    }

    # 1. compile first: TIA would release a version whose users do not compile
    $scopes = @('plc') + @(if (@($inWork | Where-Object { $n = $_; (Get-LibraryTypeScope (Find-LibraryType $lib $n).obj) -eq 'hmi' }).Count) { 'hmi' })
    $scopeDevices = @{}; foreach ($sc in $scopes) { $scopeDevices[$sc] = @(Get-TiaDeviceNames $sc) }
    $errors = @(foreach ($sc in $scopes) {
        $c = Invoke-CompileEveryDevice $sc
        foreach ($i in @($c.items)) { if ($i.messages) { Get-CompileErrors $i.messages } }
    })
    # library blocks in work but not in this release are not "left out": only types not in work at all are named to edit
    $plan = Get-ReleaseChainPlan -InWork $inWork -DependsOn $graph.graph -CompileErrors $errors -LibraryTypes @($graph.graph.Keys | Where-Object { $allInWork -notcontains $_ })
    if (-not $plan.ok) {
        $summary = "Release chain refused: $($plan.refused)"
        Add-LibraryLog $summary
        $refusedPlan = @{ ok = $false; summary = $summary; refused = $plan.refused; toEdit = @($plan.toEdit); inWork = $inWork; compileErrors = $errors.Count }
        Add-LeftBehindFacts $refusedPlan $lib
        return $refusedPlan
    }

    # 2. release in order, contained types first, as one transaction: one failure and nothing is released
    $author = if ($script:Bridge.settings.author) { [string]$script:Bridge.settings.author } else { $env:USERNAME }
    $mode = [Siemens.Engineering.Library.Types.CreateOrReleaseDependenciesMode]::DoNotAutomaticallyCreateOrReleaseDependencies
    $items = New-Object System.Collections.ArrayList
    # a type never released takes the contained types in work with it, listed or not, and makes types of plain objects it uses: seen only after the release
    $typesBefore = Get-LibraryTypeMap $lib
    $moved = New-Object System.Collections.ArrayList
    $made = New-Object System.Collections.ArrayList
    $onOld = New-Object System.Collections.ArrayList
    $w = Invoke-TiaWrite "release chain of $($plan.order.Count) library types" -RollbackIf { @($items | Where-Object { -not $_.ok }).Count -gt 0 -or $moved.Count -gt 0 -or $made.Count -gt 0 -or $onOld.Count -gt 0 } -Body {
        $stopped = $false
        foreach ($n in $plan.order) {
            $item = [ordered]@{ type = $n }
            if ($stopped) { $item.ok = $false; $item.notAttempted = $true; [void]$items.Add($item); continue }
            try {
                $t = (Find-LibraryType $lib $n).obj
                $wv = Select-TypeVersion -Versions @($t.Versions) -InWork
                if ($wv) {
                    $number = Get-ReleaseVersion -Versions @($t.Versions)
                    # a version in work lists no dependencies, so the order of types never released is only by name, and TIA refuses
                    # one whose contained type is still in work without a reason [PROBE]: TIA takes that one with it
                    $itemMode = if (Test-NeverReleased @($t.Versions)) { [Siemens.Engineering.Library.Types.CreateOrReleaseDependenciesMode]::AutomaticallyCreateOrReleaseDependenciesIfRequired } else { $mode }
                    $wv.Release($itemMode, [version]$number, $author, $comment)
                    $item.released = $number
                } else {
                    $item.released = [string](Select-TypeVersion -Versions @($t.Versions)).VersionNumber
                    $item.withContaining = $true
                }
                $item.ok = $true
            }
            catch { $item.ok = $false; $item.error = ConvertTo-BridgeError $_ }
            [void]$items.Add($item)
            if (-not $item.ok) { $stopped = $true }
        }
        if (-not $stopped) {
            $around = Compare-LibraryAroundRelease $lib $typesBefore $allInWork @($plan.order)
            foreach ($n in $around.alsoReleased) { [void]$moved.Add($n) }
            foreach ($n in $around.made) { [void]$made.Add($n) }
            # a released version cannot be taken back: on old versions of what it contains it would only burn a number. Read once all
            # are released, as a type may sit on one released in this chain.
            $releasedTypes = Get-LibraryTypeMap $lib
            foreach ($i in $items) {
                foreach ($u in @(Get-VersionOldUses $releasedTypes[$i.type] ([string]$i.released))) { [void]$onOld.Add("$($i.type): $u") }
            }
        }
    }
    $ended = Get-TiaEndedResult $items 'release chain'
    if ($ended) { Add-LibraryLog $ended.note; $ended.summary = $ended.note; return $ended }
    if ($w.rolledBack) { Set-RolledBack $items }
    if ($made.Count -and $w.rolledBack) {
        $summary = "Release chain refused: $(Format-MadeTypesWayOut @($made))"
        Add-LibraryLog $summary
        return @{ ok = $false; summary = $summary; refused = $summary; wouldMakeTypes = @($made); wouldAlsoRelease = @($moved); rolledBack = $true; transaction = $w.transaction }
    }
    if ($moved.Count -and $w.rolledBack) {
        $summary = "Release chain refused: releasing $(@($plan.order) -join ', ') would also release $(@($moved) -join ', '), in work and not in this release: TIA takes a contained type along with a type never released. Nothing was released. Name it in types and have it approved, or release it first."
        Add-LibraryLog $summary
        return @{ ok = $false; summary = $summary; refused = $summary; wouldAlsoRelease = @($moved); rolledBack = $true; transaction = $w.transaction }
    }
    if ($onOld.Count -and $w.rolledBack) {
        $summary = "Release chain refused: these versions sit on old versions of what they contain: $(Format-OnOldList @($onOld)). Released they would burn versions. Nothing was released. " +
                   'library_update_usages with those types moves them to the new versions; compile, and run the chain then.'
        Add-LibraryLog $summary
        return @{ ok = $false; summary = $summary; refused = $summary; onOldVersions = @($onOld); rolledBack = $true; transaction = $w.transaction }
    }
    $failed = @($items | Where-Object { $_.error })
    foreach ($sc in $scopes) { Register-LibraryTypeWrite $session $sc $scopeDevices[$sc] 'library release chain' (-not $failed.Count) }
    if (-not $failed.Count) {
        Set-CommittedFact 'released' @($items)
        Add-LibraryLog "Released in the chain: $(@($items | ForEach-Object { "$($_.type) $($_.released)" }) -join ', ')."
    }
    if ($failed.Count) {
        $summary = "Release chain stopped at $($failed[0].type): $($failed[0].error.message) Nothing was released$(if (-not $w.transaction) { ' (no transaction: the types before it stay released)' })."
        # TIA gives no reason for this one [PROBE] (2026-11-03: Error when calling method 'Release')
        $heldBy = @(@($graph.graph[$failed[0].type]) | Where-Object { $_ -and $allInWork -contains $_ -and @($plan.order) -notcontains $_ } | Sort-Object)
        if ($heldBy.Count) { $summary += " $($failed[0].type) contains $($heldBy -join ', '), in work and not in this release, and TIA does not release a type on that: finish it or take it back (library_discard_type) first." }
        Add-LibraryLog $summary
        $stoppedAt = @{ ok = $false; summary = $summary; items = @($items); rolledBack = [bool]$w.rolledBack; transaction = $w.transaction }
        if ($heldBy.Count) { $stoppedAt.heldBy = $heldBy }
        return $stoppedAt
    }

    # 3. update the project to the released versions; that can put the next level of containing types in work
    $released = @($items | ForEach-Object { $_.type })
    $updateScopes = Get-UpdateScopes
    try {
        $update = Invoke-ProjectUpdate $lib $released {
            param($selection)
            $lib.UpdateProject($selection, $updateScopes, [Siemens.Engineering.Library.Types.DeleteUnusedVersionsMode]::DoNotDelete)
        } 'update the project to the released chain'
    }
    catch {
        if (Test-TiaEndedError $_) { throw }
        # what it released stands: the result has to say so, and what the update took without a transaction
        $update = @{ refused = (ConvertTo-BridgeError $_).message; removed = @($_.Exception.Data['removed'] | Where-Object { $_ }) }
    }
    Register-RemovedInstances $session $update
    $compile = Invoke-CompileEveryDevice 'plc'
    # after the compile: TIA can put types in work at that too, and a type it did must not read as left out
    $after = Get-InWorkTypes $lib
    $shown = @($released | Select-Object -First 3) -join ', '
    if ($released.Count -gt 3) { $shown += ', ...' }
    $outside = @($work.types | ForEach-Object { $_.type } | Where-Object { $inWork -notcontains $_ })
    $next = Format-ReleaseChainNext -After @($after.types | ForEach-Object { $_.type }) -Outside $outside -CompileErrors ([int]$compile.errors)
    $report = ''
    $notUpdated = Get-UpdateFailure $update
    if ($change) {
        # the released types stand, the project is not on them: the change stays open until an update reaches it
        $change.updateOutstanding = [bool]$notUpdated
        $null = Save-ChangeRecord $script:Bridge.repo $change
        $map = @{}; foreach ($i in $items) { $map[$i.type] = $i.released }
        $report = Set-ChangeReleased $lib $map
        $rest = Get-LiveChange $lib -Id $change.id
        # what the update put in work is the next level, not a type left out
        Update-ChangeInWork $rest @($after.types) 'found'
        if (-not $notUpdated) { $rest.updated = $true; $rest.releasedSinceUpdate = $false }
        $stale = @(Update-ChangeStale $lib $rest)
        $leftRead = Read-LeftBehind $lib
        Set-RecordLeftBehind $rest $leftRead
        $report = Save-ChangeRecord $script:Bridge.repo $rest
        $set = Get-ApprovedReleaseSet $rest $graph.graph
        $open = @($rest.types.Keys | Where-Object { $rest.types[$_].inWork -and -not $rest.types[$_].releasedAs })
        $next = if ($rest.status -in 'done', 'left-behind') { Format-ChangeEndNext $rest }
                elseif (@($set.order).Count) { "library_release_chain again: $(@($set.order).Count) approved types can follow now." }
                elseif ($open.Count) { "$($open.Count) types of the change are not released: review and approval missing for $(@($set.notApproved).Count), waiting $(@($set.waiting).Count). library_review, ask the user, library_approve, then library_release_chain." }
                else { "$($stale.Count) types were not put in work and are not using the default version of a change type ($($stale -join ', ')): they need a new version: library_edit_type for PLC types; faceplate types the user updates in TIA (Openness crashed TIA on them). Then library_review again." }
        if ($compile.errors) { $next = "the PLC has $($compile.errors) compile errors: fix them first. Then $next" }
        $next += " Report: $report."
    }
    if ($notUpdated) { $next = "the project is not updated to the released types, so this is not done: fix what the update says, then library_update_usages.$(if ($report) { " Report: $report." })" }
    $summary = "Released $($released.Count) library types in order ($shown). Next: $next"
    if ($moved.Count) { $summary += " Without a transaction this also released $(@($moved) -join ', '), in work and not in this release." }
    if ($made.Count) { $summary += " Without a transaction TIA made library types nobody asked for: $(@($made) -join ', ')." }
    if ($onOld.Count) { $summary += " Without a transaction they were released on old versions of what they contain: $(Format-OnOldList @($onOld))." }
    $r = @{ ok = $true; summary = $summary; released = @($items); inWorkAfter = @($after.types); compileErrors = [int]$compile.errors; next = $next; report = $report }
    if ($moved.Count) { $r.alsoReleased = @($moved) }
    if ($made.Count) { $r.typesMade = @($made) }
    if ($onOld.Count) { $r.onOldVersions = @($onOld) }
    Add-UpdateFacts $r $update $session
    Add-LeftBehindFacts $r $lib $leftRead $(if ($change) { $rest })
    Add-LibraryLog $r.summary
    $r
}

function Find-MasterCopy($Library, [string]$Name) {
    $e = Get-GroupTree $Library.MasterCopyFolder 'MasterCopies' 'Folders' | Where-Object { $_.name -eq $Name } | Select-Object -First 1
    if (-not $e) { throw "No master copy named '$Name'." }
    $e
}

function Invoke-MasterCopyToProjectTool($a) {
    $session = Get-BridgeSession
    $gate = Test-WriteAllowed $session
    if ($gate) { return New-Refusal $gate }
    $mc = (Find-MasterCopy (Get-TiaLibrary ([string]$a.library)) ([string]$a.name)).obj
    $types = @($mc.ContentDescriptions | ForEach-Object { $_.ContentType.Name } | Sort-Object -Unique)
    if ($types.Count -ne 1) { return New-Refusal "Master copy '$($a.name)' holds $($types -join ', '); the bridge places master copies of one content type only." }
    $target = Get-MasterCopyTarget $types[0]
    $k = Get-ObjectKind $target.kind
    $root = Get-KindRoot $k ([string]$a.device)
    $writeDevice = Get-TiaDeviceName $k.scope ([string]$a.device)
    # what a master copy holds is not known before it is placed: any block, DB or data type may be of the safety program
    if ($k.name -in 'block', 'db', 'type') {
        $unsafe = Get-SafetyProgramRefusal 'master_copy_to_project' $a.safety @($writeDevice)
        if ($unsafe) { return New-Refusal $unsafe }
    }
    $modeName = if ($a.mode) { [string]$a.mode } else { 'ThrowIfExists' }
    # the same rule as delete: only a true opens it, not the text 'false'
    if ($modeName -eq 'Replace' -and $k.scope -eq 'plc' -and $a.knowhow -ne $true) {
        # blocks and DBs are two kinds of one tree, and their names are unique across it
        $kinds = if ($k.name -in 'block', 'db') { @('block', 'db') } else { @($k.name) }
        $entries = @(foreach ($n in $kinds) { Get-KindItems (Get-ObjectKind $n) $root })
        $isGroup = $target.composition -eq 'Groups'
        $hits = @(Get-KnowHowReplaced $entries @($mc.ContentDescriptions | ForEach-Object { $_.ContentName }) $isGroup)
        if ($hits.Count) {
            $why = Get-KnowHowRefusal $k.name (@($hits | Select-Object -First 10) -join "', '") 'replace' ([Math]::Max(0, $hits.Count - 10))
            return New-Refusal $(if ($isGroup) { "A master copy of a folder may replace any object of the PLC, and what it holds is not known before it is placed. $why" } else { $why })
        }
    }
    $folder = Get-OrCreateGroup (& $k.tree $root) ([string]$a.folder) $k.groups
    $mode = [Siemens.Engineering.Library.MasterCopies.MasterCopyMode]$modeName
    $composition = $folder.($target.composition)
    # CreateFrom(MasterCopy) does not throw on an existing name, it renames ([PROBE] 2026-10-04: Communication_FB_2).
    # The mode overload exists for PLC compositions; for the others the bridge enforces ThrowIfExists itself.
    $withMode = @($composition.GetType().GetMethods() | Where-Object { $_.Name -eq 'CreateFrom' -and $_.GetParameters().Count -eq 2 -and
                                                                        $_.GetParameters()[0].ParameterType.Name -eq 'MasterCopy' }).Count -gt 0
    if (-not $withMode) {
        if ($modeName -eq 'Replace') { return New-Refusal "$($k.name) master copies cannot be placed with Replace (TIA offers no mode there): delete the object first." }
        if ($modeName -eq 'ThrowIfExists') {
            $clash = @($mc.ContentDescriptions | Where-Object { $composition.Find($_.ContentName) } | ForEach-Object { $_.ContentName })
            if ($clash.Count) { return New-Refusal "Exists already: $($clash -join ', '). Use mode Rename, or delete it first." }
        }
    }
    try {
        $w = Invoke-TiaWrite "create from master copy $($a.name)" {
            if ($withMode) { $composition.CreateFrom($mc, $mode) } else { $composition.CreateFrom($mc) }
        }
    }
    catch { Register-Write $session -Scope $k.scope -Device $writeDevice -Items @(@{ name = "mc:$($a.name)"; ok = $false }); throw }
    $created = @($w.output | Where-Object { $_ } | ForEach-Object { [string]$_.Name })
    Register-Write $session -Scope $k.scope -Device $writeDevice -Items @(@{ name = "mc:$($a.name)"; ok = $true })
    @{ ok = $true; masterCopy = [string]$a.name; content = $types[0]; kind = $k.name; folder = [string]$a.folder; created = $created; mode = $modeName
       next = "compile the $($k.scope) scope." }
}

# A kind the bridge makes master copies of: one with a folder tree whose objects it can also place (MasterCopyTargets).
# A watch table has folders and no such target: not tried.
function Test-MasterCopyKind($Kind) { [bool]($Kind.tree -and @($script:MasterCopyTargets.Values | Where-Object { $_[0] -eq $Kind.name }).Count) }

# A kind whose folder a master copy can be made of: one the bridge can also place. By the public API of V20 every user
# folder is a source of MasterCopies.Create, but the user folder compositions of an HMI device have no
# CreateFrom(MasterCopy), so the bridge could not use such a master copy.
function Test-MasterCopyFolderKind($Kind) { (Test-MasterCopyKind $Kind) -and $Kind.scope -eq 'plc' }

function Get-HmiFolderMasterCopyRefusal {
    $kinds = @($script:ObjectKinds.Values | Where-Object { Test-MasterCopyFolderKind $_ } | ForEach-Object { $_.name } | Sort-Object)
    "A master copy of an HMI folder cannot be made through the bridge: Openness offers no way to place one (no CreateFrom on those folders). Folders of these kinds can: $($kinds -join ', ')."
}

# A name that is no object of the kind may be a folder's, which reads as a mistyped name unless the refusal says so.
function Get-NoSuchObjectRefusal($Kind, $Root, [string]$Name) {
    $text = "No $($Kind.name) named '$Name'."
    $paths = @(Get-UserFolderPaths (& $Kind.tree $Root) $Kind.groups | Where-Object { ($_ -split '/')[-1] -eq $Name })
    if (-not $paths.Count) { return $text }
    $where = "A folder of that name stands at $($paths -join ', ')."
    if (-not (Test-MasterCopyFolderKind $Kind)) { return "$text $where $(Get-HmiFolderMasterCopyRefusal)" }
    "$text $where For a master copy of the folder, pass source_folder: '$($paths[0])' instead of name."
}

# What a master copy is made of, a named object or a user folder by its exact path: @{ name; obj; label; path } or @{ refused }.
function Find-MasterCopySource($Kind, $a) {
    $name = [string]$a.name
    $path = [string]$a.source_folder
    if ($name -and $path) { return @{ refused = 'Name an object with name or a folder with source_folder, not both.' } }
    if (-not $name -and -not $path) { return @{ refused = 'Name an object with name, or a folder with source_folder.' } }
    $root = Get-KindRoot $Kind ([string]$a.device)
    if ($name) {
        $e = @(Get-KindItems $Kind $root) | Where-Object { $_.name -eq $name } | Select-Object -First 1
        if (-not $e) { return @{ refused = (Get-NoSuchObjectRefusal $Kind $root $name) } }
        return @{ name = $name; obj = $e.obj; label = "$($Kind.name) $name" }
    }
    if (-not (Test-MasterCopyFolderKind $Kind)) { return @{ refused = (Get-HmiFolderMasterCopyRefusal) } }
    $split = Split-UserFolderPath $path 'source_folder' 'A root folder cannot be made into a master copy: name a user folder.'
    if ($split.refused) { return @{ refused = $split.refused } }
    $hit = Find-UserFolder (& $Kind.tree $root) $Kind.groups $split.parts $Kind.name
    if ($hit.refused) { return @{ refused = $hit.refused } }
    @{ name = $split.parts[-1]; obj = $hit.folder; label = "folder $path"; path = $path }
}

# Whether the library folder holds a master copy of that name, also when that cannot be read.
function Test-MasterCopyStands($Folder, [string]$Name) {
    try { [bool]$Folder.MasterCopies.Find($Name) } catch { $true }
}

function Invoke-MasterCopyFromProjectTool($a) {
    $session = Get-BridgeSession
    $gate = Test-WriteAllowed $session
    if ($gate) { return New-Refusal $gate }
    $k = Get-ObjectKind ([string]$a.kind)
    if (-not (Test-MasterCopyKind $k)) { return New-Refusal "Kind $($k.name) cannot be made into a master copy by the bridge." }
    $source = Find-MasterCopySource $k $a
    if ($source.refused) { return New-Refusal $source.refused }
    $name = $source.name
    $libName = [string]$a.library
    $lib = Get-TiaLibrary $libName
    if ($libName -and $lib.IsReadOnly) { return New-Refusal "Global library '$libName' is open read-only: library_open with writable=true." }
    $folder = Get-OrCreateGroup $lib.MasterCopyFolder ([string]$a.folder) 'Folders'
    $existing = $folder.MasterCopies.Find($name)
    if ($existing -and -not (Get-OptionalBool $a 'replace' $false)) { return New-Refusal "Master copy '$name' exists in that folder; pass replace=true to replace it." }
    $key = "mc:$name"
    try {
        # a global library is not part of the project's transaction, and keeps nothing that is not saved
        $null = Invoke-TiaWrite "master copy from $($source.label)" -NoTransaction:([bool]$libName) {
            if ($existing) { $existing.Delete() }
            $null = $folder.MasterCopies.Create($source.obj)
            if ($libName) { $lib.Save() }
        }
    }
    catch {
        # as a failed import of a name never created: nothing of it stands, and if TIA never takes this source no later write could
        # clear it, so it adds no hold. It takes none away either: an earlier failure may have lost the master copy this one found gone.
        if ($existing -or (Test-MasterCopyStands $folder $name)) { Register-LibraryWrite $session -Name $key -Ok $false }
        throw
    }
    Register-LibraryWrite $session -Name $key -Ok $true
    $r = @{ ok = $true; masterCopy = $name; library = $(if ($libName) { $libName } else { 'project library' }); folder = [string]$a.folder
            replaced = [bool]$existing; globalLibrarySaved = [bool]$libName }
    if ($source.path) { $r.sourceFolder = $source.path }
    $r
}

function Register-LibraryTools {
    $kinds = @($script:ObjectKinds.Keys)
    $library = @{ type = 'string'; description = 'name of a global library opened with library_open; default the project library' }
    $device = @{ type = 'string'; description = 'PLC or HMI device name; needed only when the project has several' }
    $changesF = 'It can change F-blocks: refused without safety: true when TIA would let it change the safety program of a PLC (logged on, or no password).'

    Register-McpTool -Name 'library_open' -Handler { param($a) Invoke-LibraryOpenTool $a } -Description (
        'Open a global library (.al20) in TIA, read-only unless writable=true; a library already open is reused. list/export of library kinds and the ' +
        'master copy tools then take library=<its name>.') -Schema @{
        type = 'object'; required = @('path'); properties = @{ path = @{ type = 'string' }; writable = @{ type = 'boolean' } } }

    Register-McpTool -Name 'library_create_type' -Handler { param($a) Invoke-LibraryCreateTool $a } -Description (
        'Create a new PLC library type in the project library from one document in the repo (.s7dcl with its .s7res, or .xml; a PLC data type, FB or FC; the name it declares is the name of the type). ' +
        'TIA makes the version in work (0.0.1, or the VersionNumber of a .libinfo beside the document; no meta file is needed, and one copied from an existing type is refused for its Guid) and its test instance in the PLC, in target_folder. ' +
        'Never replaces anything: a library type of that name is refused, and TIA refuses a name the PLC already has. Refused: an OB, DB, tag table or HMI document, a document declaring a second object or one whose object cannot be read, any write before the session archive, and the document of an F-block or F-compliant PLC data type without safety: true. ' +
        'Put what it contains in first; TIA takes a missing data type with a warning, and the compile shows it. Compile afterwards, what it contains first. It has no released version until library_release_type, so a reviewed change cannot start before that; ' +
        'a version in work lists no dependencies, so types on each other get theirs at their release, contained types first. ' +
        'Its test instance stays only while something uses it: once released, the next update of any type removes it, as TIA does. library_discard_type removes it while it is in work.') -Schema @{
        type = 'object'; required = @('path')
        properties = @{ path = @{ type = 'string'; description = 'the .s7dcl, .s7res or .xml of the new type, relative to the project repo or absolute; library\types\<folder>\<name>\ keeps it where export writes it' }
                        target_folder = @{ type = 'string'; description = 'PLC folder with / for the test instance, created if missing; default the top of Program blocks or PLC data types' }
                        library_folder = @{ type = 'string'; description = 'folder with / in the project library types, created if missing; default the top' }
                        device = $device; safety = $script:SafetyArgument } }

    Register-McpTool -Name 'library_discard_type' -Handler { param($a) Invoke-LibraryDiscardTool $a } -Description (
        'Discard the version in work of a PLC library type: what was changed in it is lost. A released version stays; a type with no other version goes, with its test instance. ' +
        'Refused without safety: true when its instance is an F-block (an F-compliant PLC data type is not recognised here), and without knowhow: true when it is know-how protected. ' +
        'TIA does not refuse it when a type in work uses it: that type stops compiling. A type of a library change: the change reads what is left (status, stale, typesLeftBehind), as it is not done while its types stand on old versions. ' +
        'Only when the user asked for it, or for a test type the agent created. Compile the plc scope afterwards.') -Schema @{
        type = 'object'; required = @('name')
        properties = @{ name = @{ type = 'string' }; safety = $script:SafetyArgument
                        knowhow = @{ type = 'boolean'; description = 'allows the discard of a know-how protected instance. Only when the user asked for it; never to get past the refusal' } } }

    Register-McpTool -Name 'library_edit_type' -Handler { param($a) Invoke-LibraryEditTool $a } -Description (
        'Put a project library type in work (Edit of its default version through one of its project instances: instance, else the first) and list ' +
        'its project instances. Change the type through export/import of kind library_type (its documents), never by importing over an instance. ' +
        'A type already in work is reused. A PLC type with no instance gets one, in target_folder, and instanceMade names it: an update removes what nothing uses, so this is the way to edit such a type. ' +
        'What it contains comes along as copies name_1 on old versions when the project holds newer ones (copiesMade): compile, then library_update_usages moves the type to the new versions and TIA removes the copies; export only after that, as an export before it reads the names of the copies. An import brings the copies back from any document, and names them (copiesBack); the next update removes them. foldersMade names the folders that made in the PLC, for delete_folder once they stand empty. ' +
        'An instance that would be an F-block is refused without safety: true. While a yes of library_left_behind is in work, the changed type of its change and a type those in work contain are refused. A type on the list of types left behind with no dependents starts a change too. Counts as a write of the scope of the type.') -Schema @{
        type = 'object'; required = @('name')
        properties = @{ name = @{ type = 'string' }; instance = @{ type = 'string'; description = 'the project instance to edit through; default the first one' }
                        target_folder = @{ type = 'string'; description = 'PLC folder with / for an instance made because there is none; default the folder of the type in the library' }
                        device = $device; safety = $script:SafetyArgument } }

    Register-McpTool -Name 'library_release_type' -Handler { param($a) Invoke-LibraryReleaseTool $a } -Description (
        'Release the version in work of a project library type, with the number TIA proposed (or version, above every released one) and a comment. ' +
        'Contained types in work are released with it: alsoReleased names them. alsoInWork names the types in work now that were not before it. If TIA would make a library type of a plain block or data type it uses, nothing is released and wouldMakeTypes names it. A version that sits on old versions of what it contains is refused too, as it would burn a version: onOldVersions names them. Lists the containing types that still use the old version. Its instance reads not consistent until the next compile.') -Schema @{
        type = 'object'; required = @('name', 'comment')
        properties = @{ name = @{ type = 'string' }; comment = @{ type = 'string' }; version = @{ type = 'string'; description = 'e.g. 0.0.4' } } }

    Register-McpTool -Name 'library_update_usages' -Handler { param($a) Invoke-LibraryUpdateTool $a } -Description (
        'Update the project (all PLC and HMI software) to the newest versions of the given types, or of all types, from the project library or an open ' +
        'global library. Returns what is still out of date and every type still in work. With an open library change (started by library_edit_type) ' +
        'it compiles and puts in work the library blocks of the change that TIA leaves out (put_left_out_in_work, default true), and updates ' +
        "the change report. Any update removes every instance of a released type that nothing uses, as TIA's own window does, also of types not selected (seen through Openness, not tried in the window): instancesRemoved names them, the types stay in the library. A know-how protected instance goes the same way, with no knowhow flag asked, and only a project archive holds its code. To keep one, have something use it. DeleteUnusedVersions is about versions in the library, not this. HMI objects are not compared. typesLeftBehind names the types with no instance still on old versions; at the end of a change the user is asked about them (library_left_behind). Compile afterwards. $changesF") -Schema @{
        type = 'object'; properties = @{ types = @{ type = 'array'; items = @{ type = 'string' } }; library = $library
                                         put_left_out_in_work = @{ type = 'boolean' }; safety = $script:SafetyArgument } }

    Register-McpTool -Name 'library_release_chain' -Handler { param($a) Invoke-LibraryReleaseChainTool $a } -Description (
        'With an open library change: release only the types the user approved in its report (library_approve), contained types first, and ' +
        'only once the change types they contain are released; others stay in work. Without one: ' +
        'release every project library type in work (or the given ones) in dependency order, contained types first, after library_update_usages ' +
        'put the containing types in work. Compiles first and releases nothing while the project does not compile (TIA itself would); names library ' +
        'blocks that use a changed type and must be put in work. Releases as one transaction, then updates the project, which removes every instance of a released type that nothing uses, as the window of TIA does, also of types not selected (seen through Openness, not tried in the window; instancesRemoved names them, know-how protected ones too, with no knowhow flag asked, the types stay in the library; HMI objects are not compared), and compiles again, which clears the compile errors on record. typesLeftBehind names the types with no instance still on old versions: at the end of a change the user is asked about them (library_left_behind), and it is not plainly done while they stand. ' +
        "A type never released takes a contained type in work with it, and TIA makes a library type of a plain block or data type it uses: then nothing is released, and wouldAlsoRelease or wouldMakeTypes names them. A version that sits on old versions of what it contains is refused too, as it would burn a version: onOldVersions names them. A release TIA refuses for a contained type in work outside this release names that type (heldBy). Run it again while the result says types are in work. $changesF") -Schema @{
        type = 'object'; required = @('comment')
        properties = @{ comment = @{ type = 'string'; description = 'what changed, written into every released version' }
                        types = @{ type = 'array'; items = @{ type = 'string' }; description = 'only these types in work; default all' }
                        safety = $script:SafetyArgument } }

    Register-McpTool -Name 'master_copy_to_project' -Handler { param($a) Invoke-MasterCopyToProjectTool $a } -Description (
        'Create project objects from a master copy (blocks, DBs, UDTs, tag tables, screens, pop-ups, templates, or a PLC folder of blocks, data types or tag tables) in folder, ' +
        'created if missing. mode: ThrowIfExists (default), Rename or Replace. Compile afterwards. Blocks, DBs and PLC data types can be F-blocks: refused without safety: true ' +
        'when TIA would let them change the safety program of that PLC (logged on, or no password). Replace is refused without knowhow: true over a know-how protected block or DB of the same name, ' +
        'and for a master copy of a folder when the PLC has any (its code cannot be exported, so only a project archive can restore it: the session archive, unless it was skipped).') -Schema @{
        type = 'object'; required = @('name')
        properties = @{ name = @{ type = 'string' }; folder = @{ type = 'string'; description = 'TIA folder path with /' }
                        mode = @{ type = 'string'; enum = @('ThrowIfExists', 'Rename', 'Replace') }; library = $library; safety = $script:SafetyArgument
                        knowhow = @{ type = 'boolean'; description = 'allows Replace over know-how protected blocks. Only when the user asked for this replace; never to get past the refusal' }; device = $device } }

    Register-McpTool -Name 'master_copy_from_project' -Handler { param($a) Invoke-MasterCopyFromProjectTool $a } -Description (
        'Create a master copy from a project object (name), or from a user folder of the PLC with what it holds (source_folder; the kinds block, db, type, plc_tag_table say which tree), ' +
        'in the project library or a writable global library (saved afterwards), in folder (created if missing). It takes the name of the object or folder. ' +
        'An existing master copy of that name is replaced only with replace=true. A folder of an HMI kind is refused: Openness offers no way to place one. ' +
        'Making a folder is read from the V20 API and not yet tried on a real project: quote what TIA answers.') -Schema @{
        type = 'object'; required = @('kind')
        properties = @{ kind = @{ type = 'string'; enum = $kinds }; name = @{ type = 'string'; description = 'the object; or source_folder' }
                        source_folder = @{ type = 'string'; description = 'exact path of the user folder, as list prints it (a/b); or name' }
                        folder = @{ type = 'string'; description = 'where the master copy goes in the library' }
                        library = $library; replace = @{ type = 'boolean' }; device = $device } }
}
