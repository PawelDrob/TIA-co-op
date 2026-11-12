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
    $list = $Composition.Import([System.IO.FileInfo]::new($File.file), (Get-ImportOptions $Override))
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
    sharesNamesWith = 'db'
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
    sharesNamesWith = 'block'
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
    import = { param($plc, $folder, $file, $override)
        $list = (Get-OrCreateGroup $plc.TagTableGroup $folder 'Groups').TagTables.Import([System.IO.FileInfo]::new($file.file), (Get-ImportOptions $override))
        @{ ok = $true; imported = @($list | ForEach-Object { $_.Name }) } }
}

# Import of a watch table. A row whose symbol the PLC does not have: TIA answers OK and leaves the table not consistent with
# no rows, the good ones gone too [PROBE] (2026-11-12, ticket 323). So the item fails on the IsConsistent of what Import
# returned, and the transaction rolls the table back. Entries is not read here: counting them in the transaction ended TIA.
function Import-WatchTableFile($Composition, $File, [bool]$Override) {
    $list = @($Composition.Import([System.IO.FileInfo]::new($File.file), (Get-ImportOptions $Override)))
    $r = @{ ok = $true; imported = @($list | ForEach-Object { $_.Name }) }
    $broken = @($list | Where-Object { -not $_.IsConsistent } | ForEach-Object { [string]$_.Name })
    if ($broken.Count) {
        $r.ok = $false
        $r.error = @{ type = 'TiaBridge.NotConsistent'
                      message = "TIA took the file and left watch table '$($broken -join "', '")' not consistent, with none of its rows: a row names a symbol the PLC does not have (a tag or DB member, also a nested member written flat). TIA does not say which row. Check each row's Name against the PLC, fix the file and import it again ($(Get-GuidePath 'openness-v20.md') section 1, Watch and force tables)." }
    }
    $r
}

Register-ObjectKind 'watch_table' @{
    scope = 'plc'; dir = 'plc\watchtables'; defaultOverride = $true
    description = 'watch tables (SimaticML)'
    items = { param($plc) Get-GroupTree $plc.WatchAndForceTableGroup 'WatchTables' 'Groups' }
    whoseFile = { param($file, $entries) Get-DocumentFileObject $file }
    export = { param($e, $dir, $opt) Export-PlcXml $e $dir $opt }
    precheck = { param($file, $cache) if ($file.format -ne 'xml') { @{ ok = $false; refused = 'Watch tables are SimaticML (.xml) only.' } } }
    import = { param($plc, $folder, $file, $override) Import-WatchTableFile (Get-OrCreateGroup $plc.WatchAndForceTableGroup $folder 'Groups').WatchTables $file $override }
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

Register-ObjectKind 'technology_object' @{
    scope = 'plc'; dir = 'plc\technology'; exportOnly = $true
    description = 'technology objects (export only, SimaticML)'
    items = { param($plc) Get-GroupTree $plc.TechnologicalObjectGroup 'TechnologicalObjects' 'Groups' }
    export = { param($e, $dir, $opt) Export-PlcXml $e $dir $opt }
}

Register-ObjectKind 'force_table' @{
    scope = 'plc'; dir = 'plc\forcetables'; exportOnly = $true
    description = 'force tables (export only, SimaticML)'
    items = { param($plc) Get-GroupTree $plc.WatchAndForceTableGroup 'ForceTables' 'Groups' }
    export = { param($e, $dir, $opt) Export-PlcXml $e $dir $opt }
}
