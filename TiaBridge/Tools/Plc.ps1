# Tools\Plc.ps1 - PLC kinds for list/export/import/delete (Tools\Objects.ps1): block (FB, FC, OB), db, type (UDT),
# plc_tag_table. Formats: .s7dcl/.s7res via ExportAsDocuments/ImportFromDocuments, SimaticML via Export/Import.

# The items of a folder tree with their folder paths, read again when TIA changed a list during the read (Read-TiaList).
function Get-GroupTree($Root, [string]$ItemsProperty, [string]$GroupsProperty) {
    Read-TiaList {
        $stack = New-Object System.Collections.Stack
        $stack.Push(@($Root, ''))
        while ($stack.Count) {
            $e = $stack.Pop(); $g = $e[0]; $prefix = $e[1]
            foreach ($o in $g.$ItemsProperty) { @{ obj = $o; name = $o.Name; folder = $prefix } }
            foreach ($s in $g.$GroupsProperty) { $stack.Push(@($s, $(if ($prefix) { "$prefix/$($s.Name)" } else { $s.Name }))) }
        }
    }
}

function Get-OrCreateGroup($Root, [string]$Folder, [string]$GroupsProperty) {
    $g = $Root
    foreach ($part in ($Folder -split '/' | Where-Object { $_ })) {
        $sub = $g.$GroupsProperty.Find($part)
        if (-not $sub) { $sub = $g.$GroupsProperty.Create($part) }
        $g = $sub
    }
    $g
}

function Get-PlcBlockClass($Block) { $Block.GetType().Name }   # FB, FC, OB, GlobalDB, InstanceDB, ArrayDB
function Test-IsDataBlock($Block) { (Get-PlcBlockClass $Block) -match 'DB$' }

# Library link of a project object, or $null (LibraryTypeInstanceInfo service).
function Get-LibraryLink($Obj) {
    try {
        $info = Get-TiaService $Obj ([Siemens.Engineering.Library.Types.LibraryTypeInstanceInfo])
        if ($info) {
            $v = $info.LibraryTypeVersion
            return @{ type = $v.TypeObject.Name; version = [string]$v.VersionNumber; inWork = ([string]$v.State -eq 'InWork') }
        }
    } catch { }
    $null
}

function Get-PlcExportOptions([bool]$Full) {
    if ($Full) { [Siemens.Engineering.ExportOptions]::WithDefaults -bor [Siemens.Engineering.ExportOptions]::WithReadOnly }
    else { [Siemens.Engineering.ExportOptions]::WithDefaults }
}

# Export of one block or type: format chosen by the guard (OBs and know-how protected blocks as SimaticML).
function Export-PlcObject($Entry, [string]$Dir, $Options, [bool]$IsBlock) {
    $obj = $Entry.obj
    $isOb = $IsBlock -and (Get-PlcBlockClass $obj) -eq 'OB'
    $format = Select-BlockExportFormat -IsOb $isOb -IsKnowHowProtected ([bool]$obj.IsKnowHowProtected) -Requested ([string]$Options.format)
    New-Item -ItemType Directory -Force -Path $Dir | Out-Null
    $base = ConvertTo-SafeFileName $Entry.name
    # every export goes into a fresh folder first: the previous files are replaced only by a successful export
    # (a refused SD export, e.g. without SimaticSdEnabler, must not delete the last good one)
    $partial = New-ExportWorkPath (Join-Path $Dir $base)
    New-Item -ItemType Directory -Force -Path $partial | Out-Null
    try {
        if ($format -eq 's7dcl') {
            $res = $obj.ExportAsDocuments([System.IO.DirectoryInfo]::new($partial), $base)
            $tree = ConvertTo-ResultTree $res
            $exts = @('.s7dcl', '.s7res')
            $ok = $tree.state -eq 'Success'
        } else {
            $obj.Export([System.IO.FileInfo]::new((Join-Path $partial "$base.xml")), (Get-PlcExportOptions ([bool]$Options.full)))
            $tree = $null; $exts = @('.xml'); $ok = $true
        }
        $paths = @(); $removed = @(); $notes = @()
        if ($ok) {
            foreach ($x in $exts) {
                $f = Join-Path $Dir "$base$x"
                $p = Join-Path $partial "$base$x"
                if (Test-Path -LiteralPath $p) { Move-ExportIntoPlace $p $f; $paths += $f }
            }
            # the block's export in the other format, or an .s7res the new export no longer writes, no longer matches
            # the project (seen on a real project: SimaticML of refused SD exports beside the later .s7dcl); removed only once the new
            # export is in place, and listed so the removal goes into the project repo's next commit
            if ($paths -contains (Join-Path $Dir "$base$($exts[0])")) {
                foreach ($x in @('.s7dcl', '.s7res', '.xml')) {
                    $f = Join-Path $Dir "$base$x"
                    if ($paths -contains $f -or -not (Test-Path -LiteralPath $f)) { continue }
                    try { Remove-Item -LiteralPath $f -Force -ErrorAction Stop; $removed += $f }
                    catch { $notes += "The old export $f could not be removed (another process holds it open?); remove it by hand: $($_.Exception.Message)" }
                }
            }
        }
    }
    finally { Remove-Item -LiteralPath $partial -Recurse -Force -ErrorAction SilentlyContinue }
    $r = @{ ok = $ok; format = $format; files = $paths }
    if ($removed.Count) { $r.removed = $removed }
    if ($notes.Count) { $r.note = $notes -join ' ' }
    if ($tree) { $r.messages = $tree }
    $r
}

function Get-DocumentImportOptions([bool]$Override) {
    if ($Override) { [Siemens.Engineering.SW.ImportDocumentOptions]::Override } else { [Siemens.Engineering.SW.ImportDocumentOptions]::None }
}
function Get-ImportOptions([bool]$Override) {
    if ($Override) { [Siemens.Engineering.ImportOptions]::Override } else { [Siemens.Engineering.ImportOptions]::None }
}

# The precheck of the kinds of Import-PlcFile: before the write, as the group of a new object is made on the way into it.
function Test-PlcFileFormat($File) {
    if ($File.format -ne 's7dcl') { return $null }
    $refusal = Test-S7dclImportAllowed $File.file
    if ($refusal) { @{ ok = $false; refused = $refusal } }
}

# Import into a block or type composition. $File: entry of Resolve-ImportFiles.
function Import-PlcFile($Composition, $File, [bool]$Override) {
    if ($File.format -eq 's7dcl') {
        $lineEnds = Repair-DocumentLineEnds $File.file
        $res = $Composition.ImportFromDocuments([System.IO.DirectoryInfo]::new([System.IO.Path]::GetDirectoryName($File.file)), $File.name, (Get-DocumentImportOptions $Override))
        $tree = ConvertTo-ResultTree $res
        $r = @{ ok = ($tree.state -eq 'Success'); messages = $tree }
        foreach ($p in $res.PSObject.Properties | Where-Object { $_.Name -like 'Imported*' }) { $r.imported = @($res.($p.Name) | ForEach-Object { $_.Name }) }
        if ($lineEnds) { $r.note = $lineEnds }
        return $r
    }
    Import-SimaticMlFile $Composition $File $Override
}

# A SimaticML file through Import of a composition. Check: what the kind asks of the objects Import returned, inside the
# write: an error (@{ type; message }) fails the item, and the call rolls back; $null passes.
function Import-SimaticMlFile($Composition, $File, [bool]$Override, [scriptblock]$Check = $null) {
    $list = @($Composition.Import([System.IO.FileInfo]::new($File.file), (Get-ImportOptions $Override)))
    $err = if ($Check) { & $Check $list }
    if ($err) { return @{ ok = $false; error = $err } }
    @{ ok = $true; imported = @($list | ForEach-Object { $_.Name }) }
}

# Whose file a .s7dcl or SimaticML of a block, PLC data type, tag table or HMI document is: @{ name } of the name it
# declares, whatever the file is called, else $null (the file's name is the object's). TIA goes by the declared name, so
# this is the object an override replaces: the guards (F-block, know-how, test instance in work, an existing tag table) must
# see it, not a new object.
function Get-DocumentFileObject($File) {
    $declared = Get-DocumentDeclaredName $File.file
    if ($declared) { @{ name = $declared } }
}

Register-ObjectKind 'block' @{
    scope = 'plc'; dir = 'plc\blocks'; defaultOverride = $true
    description = 'FB, FC, OB'
    sharesNamesWith = @('db', 'technology_object')
    items = { param($plc) Get-GroupTree $plc.BlockGroup 'Blocks' 'Groups' | Where-Object { -not (Test-IsDataBlock $_.obj) } }
    tree = { param($plc) $plc.BlockGroup }; groups = 'Groups'
    info = { param($e) $b = $e.obj
        $i = @{ class = Get-PlcBlockClass $b; number = $b.Number; language = [string]$b.ProgrammingLanguage; consistent = $b.IsConsistent; knowHowProtected = $b.IsKnowHowProtected }
        if ($i.class -eq 'OB') { $i.obType = [string]$b.SecondaryType }
        $l = Get-LibraryLink $b; if ($l) { $i.library = $l }
        $i }
    export = { param($e, $dir, $opt) Export-PlcObject $e $dir $opt $true }
    precheck = { param($file, $cache) Test-PlcFileFormat $file }
    import = { param($plc, $folder, $file, $override) Import-PlcFile (Get-OrCreateGroup $plc.BlockGroup $folder 'Groups').Blocks $file $override }
    whoseFile = { param($file, $entries) Get-DocumentFileObject $file }
}

Register-ObjectKind 'db' @{
    scope = 'plc'; dir = 'plc\blocks'; defaultOverride = $true
    description = 'global, instance and array DBs'
    sharesNamesWith = @('block', 'technology_object')
    items = { param($plc) Get-GroupTree $plc.BlockGroup 'Blocks' 'Groups' | Where-Object { Test-IsDataBlock $_.obj } }
    tree = { param($plc) $plc.BlockGroup }; groups = 'Groups'
    info = { param($e) $b = $e.obj
        $i = @{ class = Get-PlcBlockClass $b; number = $b.Number; consistent = $b.IsConsistent }
        $l = Get-LibraryLink $b; if ($l) { $i.library = $l }
        $i }
    export = { param($e, $dir, $opt) Export-PlcObject $e $dir $opt $true }
    precheck = { param($file, $cache) Test-PlcFileFormat $file }
    import = { param($plc, $folder, $file, $override) Import-PlcFile (Get-OrCreateGroup $plc.BlockGroup $folder 'Groups').Blocks $file $override }
    whoseFile = { param($file, $entries) Get-DocumentFileObject $file }
}

Register-ObjectKind 'type' @{
    scope = 'plc'; dir = 'plc\types'; defaultOverride = $true
    description = 'PLC data types (UDT)'
    items = { param($plc) Get-GroupTree $plc.TypeGroup 'Types' 'Groups' }
    tree = { param($plc) $plc.TypeGroup }; groups = 'Groups'
    info = { param($e) $i = @{ consistent = $e.obj.IsConsistent }; $l = Get-LibraryLink $e.obj; if ($l) { $i.library = $l }; $i }
    export = { param($e, $dir, $opt) Export-PlcObject $e $dir $opt $false }
    precheck = { param($file, $cache) Test-PlcFileFormat $file }
    import = { param($plc, $folder, $file, $override) Import-PlcFile (Get-OrCreateGroup $plc.TypeGroup $folder 'Groups').Types $file $override }
    whoseFile = { param($file, $entries) Get-DocumentFileObject $file }
}

# One object as SimaticML into <dir>\<name>.xml.
function Export-PlcXml($Entry, [string]$Dir, $Options) {
    $file = Join-Path $Dir "$(ConvertTo-SafeFileName $Entry.name).xml"
    Export-ObjectFile $Entry.obj $file (Get-PlcExportOptions ([bool]$Options.full))
    @{ ok = $true; format = 'xml'; files = @($file) }
}

Register-ObjectKind 'plc_tag_table' @{
    scope = 'plc'; dir = 'plc\tags'; defaultOverride = $true
    description = 'PLC tag tables (SimaticML)'
    items = { param($plc) Get-GroupTree $plc.TagTableGroup 'TagTables' 'Groups' }
    tree = { param($plc) $plc.TagTableGroup }; groups = 'Groups'
    info = { param($e) @{ isDefault = $e.obj.IsDefault } }
    whoseFile = { param($file, $entries) Get-DocumentFileObject $file }
    export = { param($e, $dir, $opt) Export-PlcXml $e $dir $opt }
    precheck = { param($file, $cache) if ($file.format -ne 'xml') { @{ ok = $false; refused = 'PLC tag tables are SimaticML (.xml) only.' } } }
    import = { param($plc, $folder, $file, $override) Import-SimaticMlFile (Get-OrCreateGroup $plc.TagTableGroup $folder 'Groups').TagTables $file $override }
}

# The check of the watch or force tables Import returned: TIA answers OK to a row whose symbol the PLC does not have,
# written without DisplayFormat (with one, a force table's row makes TIA throw), and leaves the table not consistent
# (docs\agent\openness-v20.md, Watch and force tables), so a table not consistent is an error. What: the table in words
# for the message ('watch table'). RowsLost: the message says TIA kept none of its rows, as seen of watch tables. Reads
# IsConsistent only: counting Entries inside the transaction ended TIA.
function Test-ImportedTables([object[]]$Tables, [string]$What, [switch]$RowsLost) {
    $broken = @($Tables | Where-Object { -not $_.IsConsistent } | ForEach-Object { [string]$_.Name })
    if (-not $broken.Count) { return $null }
    $rows = if ($RowsLost) { ', with none of its rows' }
    @{ type = 'TiaBridge.NotConsistent'
       message = "TIA took the file and left $What '$($broken -join "', '")' not consistent${rows}: a row names a symbol the PLC does not have (a tag or DB member, also a nested member written flat). TIA does not say which row. Check each row's Name against the PLC, fix the file and import it again ($(Get-GuidePath 'openness-v20.md') section 1, Watch and force tables)." }
}

Register-ObjectKind 'watch_table' @{
    scope = 'plc'; dir = 'plc\watchtables'; defaultOverride = $true
    description = 'watch tables (SimaticML)'
    items = { param($plc) Get-GroupTree $plc.WatchAndForceTableGroup 'WatchTables' 'Groups' }
    tree = { param($plc) $plc.WatchAndForceTableGroup }; groups = 'Groups'
    whoseFile = { param($file, $entries) Get-DocumentFileObject $file }
    export = { param($e, $dir, $opt) Export-PlcXml $e $dir $opt }
    precheck = { param($file, $cache) if ($file.format -ne 'xml') { @{ ok = $false; refused = 'Watch tables are SimaticML (.xml) only.' } } }
    import = { param($plc, $folder, $file, $override)
        Import-SimaticMlFile (Get-OrCreateGroup $plc.WatchAndForceTableGroup $folder 'Groups').WatchTables $file $override { param($list) Test-ImportedTables $list 'watch table' -RowsLost } }
}

# One force table per PLC, which TIA makes and has no Delete() for: Import over it takes its rows, and a file of another
# name answers "'Create' is not supported by type '...PlcForceTableComposition'", so the bridge refuses that name first. A
# row of a missing symbol throws, or with no DisplayFormat leaves the table not consistent, as a watch table's does.
# ForceIntention is read-only, so no file arms a force (docs\agent\openness-v20.md, Watch and force tables).
$script:ForceTableOnline = 'A force table import changes the offline force table only, nothing in the CPU: a file cannot set a force mark (ForceIntention is read-only), and whether a row marked in TIA keeps its mark through an import was not tried. Forcing stays the user''s, online in TIA.'

Register-ObjectKind 'force_table' @{
    scope = 'plc'; dir = 'plc\forcetables'; defaultOverride = $true
    description = 'force tables (SimaticML; the PLC''s one table, imported over itself)'
    noDelete = 'A PLC has one force table, which TIA makes and keeps: it has no Delete.'
    items = { param($plc) Get-GroupTree $plc.WatchAndForceTableGroup 'ForceTables' 'Groups' }
    whoseFile = { param($file, $entries) Get-DocumentFileObject $file }
    export = { param($e, $dir, $opt) Export-PlcXml $e $dir $opt }
    precheck = { param($file, $cache, $entries)
        if ($file.format -ne 'xml') { return @{ ok = $false; refused = 'Force tables are SimaticML (.xml) only.' } }
        if (-not @($entries | Where-Object { $_.name -eq $file.objectName }).Count) {
            $own = @($entries | ForEach-Object { "'$($_.name)'" }) -join ', '
            @{ ok = $false; refused = "A PLC has one force table, and TIA makes no other: '$($file.objectName)' is not it$(if ($own) { " (the PLC's is $own)" }). Import the PLC's force table under its own name." }
        } }
    import = { param($plc, $folder, $file, $override)
        Import-SimaticMlFile (Get-OrCreateGroup $plc.WatchAndForceTableGroup $folder 'Groups').ForceTables $file $override { param($list) Test-ImportedTables $list 'force table' } }
    afterImport = { param($result, $items) $result.online = $script:ForceTableOnline }
}

# Technology objects go back through TechnologicalInstanceDBComposition.Import with Override. What a real TIA V20 was
# tried with, by system library element and version ("<OfSystemLibElement> <OfSystemLibVersion>" of the document), and
# how where it matters: each made new from a file and round tripped identically (docs\agent\openness-v20.md, Technology objects). After an import the object
# reads not consistent and TIA refuses its export until the PLC is compiled; a block that uses it was seen not consistent
# until then too.
$script:VirtualAxisTried = 'as a virtual axis only, without a drive'
$script:TechnologyObjectsTried = [ordered]@{
    'PID_Compact 2.4' = ''; 'PID_3Step 2.3' = ''; 'PID_Temp 1.1' = ''
    'TO_SpeedAxis 6.0' = $script:VirtualAxisTried; 'TO_PositioningAxis 6.0' = $script:VirtualAxisTried; 'TO_SynchronousAxis 6.0' = $script:VirtualAxisTried
}

# "<element> <version>" of a technology object's document, '' when it names no system library element.
function Get-TechnologyObjectElement([string]$Path) {
    try {
        $list = (Read-DocumentXml $Path).SelectSingleNode("$script:DocumentObjectsXPath/AttributeList")
        $element = $list.SelectSingleNode('OfSystemLibElement')
        if (-not $element -or -not $element.InnerText) { return '' }
        $version = $list.SelectSingleNode('OfSystemLibVersion')
        "$($element.InnerText) $(if ($version) { $version.InnerText })".Trim()
    } catch { '' }
}

# Items by their element and version, as "<element> <version> (<names>[; how it was tried])", joined by commas.
function Format-TechnologyObjectElements([object[]]$Items) {
    @($Items | Group-Object { $_.technology } | ForEach-Object {
        $element = if ($_.Name) { $_.Name } else { 'no system library element named' }
        $names = @($_.Group | ForEach-Object { $_.name }) -join ', '
        $how = if ($_.Name) { $script:TechnologyObjectsTried[$_.Name] }
        "$element ($names$(if ($how) { "; $how" }))" }) -join ', '
}

# What the result says of the elements and versions of a call's technology objects: the items the precheck read
# (technology, tried), tried first. $null when no item got that far.
function Get-TechnologyObjectTriedNote([object[]]$Items) {
    $read = @($Items | Where-Object { $_.Contains('technology') })
    if (-not $read.Count) { return $null }
    $tried = @($read | Where-Object { $_.tried })
    $untried = @($read | Where-Object { -not $_.tried })
    $text = @()
    if ($tried.Count) { $text += "Tried on a real TIA: $(Format-TechnologyObjectElements $tried)." }
    if ($untried.Count) {
        $text += "Not tried: $(Format-TechnologyObjectElements $untried). TIA refuses an element or version it does not have, and takes one it has as the file writes it, unchecked (a PID_Compact marked 2.3 with the parameters of a 2.4 went in so): have the user look at each in TIA before the save. Tried were $(@($script:TechnologyObjectsTried.Keys) -join ', ')."
    }
    $text -join ' '
}

Register-ObjectKind 'technology_object' @{
    scope = 'plc'; dir = 'plc\technology'; defaultOverride = $true
    description = 'technology objects (SimaticML)'
    sharesNamesWith = @('block', 'db')
    noDelete = 'Deleting a technology object was not tried on a real TIA. Delete it in TIA.'
    # IsKnowHowProtected read true of a PID_Compact 2.4 that nobody protected (false of an external encoder 6.0). Its
    # export imported back identically; the bridge imports over every technology object (the maintainer's word, 2026-11-12)
    systemKnowHow = $true
    compileWhy = 'the PLC as a whole: until then the technology object reads not consistent and TIA refuses its export, and a block that uses it may read not consistent'
    items = { param($plc) Get-GroupTree $plc.TechnologicalObjectGroup 'TechnologicalObjects' 'Groups' }
    info = { param($e) @{ technology = "$($e.obj.OfSystemLibElement) $($e.obj.OfSystemLibVersion)".Trim(); number = $e.obj.Number; consistent = $e.obj.IsConsistent } }
    whoseFile = { param($file, $entries) Get-DocumentFileObject $file }
    export = { param($e, $dir, $opt) Export-PlcXml $e $dir $opt }
    # an import over an object of another element or version was not tried: refused before TIA, as the namesake guard does
    precheck = { param($file, $cache, $entries)
        if ($file.format -ne 'xml') { return @{ ok = $false; refused = 'Technology objects are SimaticML (.xml) only.' } }
        $element = Get-TechnologyObjectElement $file.file
        $existing = @($entries | Where-Object { $_.name -eq $file.objectName })[0]
        if ($existing) {
            $has = "$($existing.obj.OfSystemLibElement) $($existing.obj.OfSystemLibVersion)".Trim()
            if ($has -ne $element) {
                return @{ ok = $false; technology = $element; refused = "technology object '$($file.objectName)' is a $has in the project, and the document $(if ($element) { "a $element" } else { 'names no system library element' }): an import over an object of another element or version was not tried on a real TIA. Nothing imported: change it in TIA, or give the document another name." }
            }
        }
        @{ technology = $element; tried = [bool]($element -and $script:TechnologyObjectsTried.Contains($element)) } }
    import = { param($plc, $folder, $file, $override)
        Import-SimaticMlFile (Get-OrCreateGroup $plc.TechnologicalObjectGroup $folder 'Groups').TechnologicalObjects $file $override }
    afterImport = { param($result, $items)
        $note = Get-TechnologyObjectTriedNote $items
        if ($note) { $result.technology = $note } }
}

# Export only: SimaticML through Export, as the Openness V20 assembly offers it for these
# objects [PROBE] (2026-10-30, project A).

Register-ObjectKind 'system_block' @{
    scope = 'plc'; dir = 'plc\systemblocks'; exportOnly = $true
    description = 'system blocks (export only; F-system blocks cannot be exported)'
    # BlockGroup.SystemBlockGroups: 'System blocks' with 'STEP 7 Safety' and 'Program resources' below it [PROBE]
    items = { param($plc)
        foreach ($g in $plc.BlockGroup.SystemBlockGroups) {
            foreach ($e in Get-GroupTree $g 'Blocks' 'Groups') { $e.folder = $(if ($e.folder) { "$($g.Name)/$($e.folder)" } else { $g.Name }); $e }
        } }
    info = { param($e) $b = $e.obj; @{ class = Get-PlcBlockClass $b; number = $b.Number; language = [string]$b.ProgrammingLanguage } }
    export = { param($e, $dir, $opt) Export-PlcXml $e $dir $opt }
}
