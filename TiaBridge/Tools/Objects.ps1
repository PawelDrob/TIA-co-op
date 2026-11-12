# Tools\Objects.ps1 - list, export, import, delete, delete_folder and compile over the object kinds that Tools\Plc.ps1,
# Tools\Hmi.ps1 and Tools\Library.ps1 register.
#
# A kind is a hashtable: scope ('plc'|'hmi'|'library'|'project'), dir (repo folder), description, defaultOverride,
# exportOnly (import and delete refused), noOverride (why import never replaces one: override refused), and
# scriptblocks items(root) -> @{ obj; name; folder }, info(entry), export(entry, dir, options),
# import(root, folder, file, override). A kind without export or import does not support it.
# Kinds with a folder tree also give tree(root) -> top folder and groups, the name of its subfolder collection
# (master copies are placed through them).

$script:ObjectKinds = [ordered]@{}

function Register-ObjectKind([string]$Name, [hashtable]$Definition) {
    $Definition.name = $Name
    $script:ObjectKinds[$Name] = $Definition
}

function Get-ObjectKind([string]$Name) {
    $k = $script:ObjectKinds[$Name]
    if (-not $k) { throw "Unknown kind '$Name'. Kinds: $(@($script:ObjectKinds.Keys) -join ', ')." }
    $k
}

# The objects of a kind under Root (its items), read again when TIA changed a list during the read (Read-TiaList).
function Get-KindItems($Kind, $Root) { Read-TiaList { & $Kind.items $Root } }

# Library: '' for the project library, else the name of a global library opened with library_open.
function Get-KindRoot($Kind, [string]$Device, [string]$Library = '') {
    switch ($Kind.scope) {
        'plc' { Get-TiaSoftware 'plc' $Device }
        'hmi' { Get-TiaSoftware 'hmi' $Device }
        'library' { Get-TiaLibrary $Library }
        'project' { Get-TiaProject }
    }
}

# The device's folder when the project has several devices of the scope: plc\<device>\..., hmi\<device>\...
# (decided 2026-10-30: five HMI devices of one project wrote into the same hmi\screens\);
# '' with one device, so one-device repos keep their layout. Without Device the scope has one device
# (Get-TiaSoftware refuses otherwise).
function Get-DeviceDir([string]$Scope, [string]$Device) {
    if (-not $Device -or $Scope -notin 'plc', 'hmi') { return '' }
    $devices = @(Get-TiaSoftwareList | Where-Object { $_.kind -eq $Scope } | ForEach-Object { [string]$_.device })
    if ($devices.Count -le 1) { return '' }
    Get-UniqueFolderName $Device $devices
}

# The names of the open global libraries, for their folders.
function Get-GlobalLibraryNames { @(Get-GlobalLibraryList | ForEach-Object { [string]$_.Name } | Where-Object { $_ }) }

# The global libraries open in the bound TIA, read again when TIA changed the list during the read (Read-TiaList).
function Get-GlobalLibraryList { Read-TiaList { foreach ($l in $script:Bridge.portal.GlobalLibraries) { $l } } }

# What a result says when a device or global library is not in the folder of its name, as another has that name in
# file-safe form (Get-UniqueFolderName), or $null. What: Device or Library.
function Get-SharedFolderNote([string]$What, [string]$Name, [string[]]$Names) {
    if (-not $Name) { return $null }
    $Name = Resolve-ListedName $Name $Names
    $others = @(Get-FolderSharers $Name $Names | ForEach-Object { "'$_'" }) -join ' and '
    if (-not $others) { return $null }
    $folder = Get-UniqueFolderName $Name $Names
    $safe = ConvertTo-SafeFileName $Name
    "$What '$Name' has one file name with $others, so its files are in the folder $folder, not $safe, and nothing is overwritten. Renaming one in TIA gives the plain folder. The HMI tools take that folder as the device."
}

# The kind's folder relative to the repo (Dir: another folder of it, such as its importDir), with the device folder
# after plc\ or hmi\ (Get-DeviceDir): hmi\<device>\generated\screens for the import of a project with several HMI devices.
function Get-KindRelDir($Kind, [string]$Device = '', [string]$Dir = '') {
    if (-not $Dir) { $Dir = $Kind.dir }
    $d = Get-DeviceDir $Kind.scope $Device
    if ($d) { "$($Dir.Substring(0, 4))$d\$($Dir.Substring(4))" } else { $Dir }
}

# A name is itself; it is a wildcard only when it holds * or ?. [ ] stay literal either way: TIA names hold them
# (an array element's name), and -like would read them as a character class that matches nothing of the kind.
function Test-NameLike([string]$Name, [object[]]$Patterns) {
    foreach ($p in $Patterns) {
        if ($Name -eq $p) { return $true }
        if ($p -match '[*?]' -and $Name -like ($p -replace '[\[\]`]', '`$0')) { return $true }
    }
    $false
}

# The entries one name of a call picks: those of that exact name, else what it matches as a wildcard.
function Select-NamedEntries([object[]]$Entries, [string]$Name) {
    $exact = @($Entries | Where-Object { $_.name -eq $Name })
    if ($exact.Count) { return $exact }
    $Entries | Where-Object { Test-NameLike $_.name @($Name) }
}

function Get-RepoRelative([string]$Path) {
    $repo = $script:Bridge.repo.TrimEnd('\') + '\'
    if ($Path.StartsWith($repo, [StringComparison]::OrdinalIgnoreCase)) { $Path.Substring($repo.Length) } else { $Path }
}

# Library: a global library's objects go to library\global\<library>\..., apart from the project library's, so an
# export from one never replaces the other's files (2026-10-06: a failed global export emptied a project one).
function Get-KindDir($Kind, [string]$Folder, [string]$Library = '', [string]$Device = '') {
    $rel = Get-KindRelDir $Kind $Device
    if ($Library) { $rel = Join-Path "library\global\$(Get-UniqueFolderName $Library (Get-GlobalLibraryNames))" ($Kind.dir -replace '^library\\', '') }
    $d = Join-Path $script:Bridge.repo $rel
    foreach ($part in ($Folder -split '/' | Where-Object { $_ })) { $d = Join-Path $d (ConvertTo-SafeFileName $part) }
    $d
}

# The path, without extension, that a kind's export of an entry writes: in lower case, which with an ordinal compare is what
# NTFS folds (947 pairs swept, none missed; a culture compare would also take Strasse for the other spelling, which NTFS
# keeps apart). A library type Foo.released is on the path of Foo: that is the folder of Foo's comparison export.
function Get-ExportBase($Kind, $Entry, [string]$Library = '', [string]$Device = '') {
    $b = (Join-Path (Get-KindDir $Kind $Entry.folder $Library $Device) (ConvertTo-SafeFileName $Entry.name)).ToLowerInvariant()
    if ($Kind.name -eq 'library_type') { $b -replace '\.released$', '' } else { $b }
}

# Objects whose exports would land on one path (Ns:Block and Ns_Block; Abc and ABC; two without a name): that path -> their
# names. Against every object of the folder, not only those a call exports, as the file may hold an object not asked for,
# and of every kind writing the folder (block and db share plc\blocks), as an export also removes the other format's files
# of its base. Entries: of Kind; Root: where the other kinds' items are read.
function Get-ExportCollisions($Kind, [object[]]$Entries, $Root, [string]$Library = '', [string]$Device = '') {
    $byBase = New-Object System.Collections.Hashtable ([StringComparer]::Ordinal)
    $add = { param($k, $e)
        $b = Get-ExportBase $k $e $Library $Device
        if (-not $byBase.ContainsKey($b)) { $byBase[$b] = New-Object System.Collections.ArrayList }
        [void]$byBase[$b].Add([string]$e.name)
    }
    foreach ($e in $Entries) { & $add $Kind $e }
    foreach ($o in $script:ObjectKinds.Values) {
        if ($o.name -eq $Kind.name -or $o.dir -ne $Kind.dir -or -not $o.export) { continue }
        foreach ($e in @(Get-KindItems $o $Root)) { & $add $o $e }
    }
    $hits = New-Object System.Collections.Hashtable ([StringComparer]::Ordinal)
    foreach ($b in $byBase.Keys) { if ($byBase[$b].Count -gt 1) { $hits[$b] = @($byBase[$b] | Sort-Object) } }
    $hits
}

# The refusal of an object that shares its file with others (Get-ExportCollisions). Nothing is written, so what the file
# holds stays; a guess at a second file name would break what goes by the file name (import of a library type, HMI preview).
function Get-CollisionError($Kind, $Entry, [string[]]$Names, [string]$Library = '', [string]$Device = '') {
    $shown = @($Names | ForEach-Object { if ($_) { "'$_'" } else { '(no name)' } }) -join ' and '
    $file = Get-RepoRelative (Join-Path (Get-KindDir $Kind $Entry.folder $Library $Device) (ConvertTo-SafeFileName $Entry.name))
    # an object without a readable name (a slide-in has only its edge) gives the user nothing to act on in TIA
    $message = if (@($Names | Where-Object { $_ }).Count) {
        "$shown share the file name $file`: exporting one would overwrite the other, so neither is exported and the files there stay as they are. Rename one in TIA, then export again."
    } else {
        "$shown`: these $(@($Names).Count) objects have no name the bridge can read and would all land on $file, so none is exported and the files there stay as they are. Report it: nothing in the project is wrong."
    }
    @{ type = 'TiaBridge.NameCollision'; message = $message }
}

# One SimaticML file through Obj.Export(file, options). Export refuses to overwrite, and a failed export must not
# delete the last good file: export next to it, then replace it (Move-ExportIntoPlace, Repo.ps1).
function Export-ObjectFile($Obj, [string]$File, $Options) {
    New-Item -ItemType Directory -Force -Path (Split-Path -Parent $File) | Out-Null
    $partial = New-ExportWorkPath $File
    try { $Obj.Export([System.IO.FileInfo]::new($partial), $Options) }
    catch { Remove-Item -LiteralPath $partial -ErrorAction SilentlyContinue; throw }
    Move-ExportIntoPlace $partial $File
}

# A SimaticML export that writes files beside the .xml (a multilingual graphic writes its images into
# '<name> files', which the .xml names by relative path): exported into a folder of its own, then each file and
# folder moved into Dir. Returns the files, those inside a moved folder too (the full_export mirror keeps them).
function Export-ObjectFolder($Obj, [string]$Dir, [string]$Name, $Options) {
    $partial = New-ExportWorkPath (Join-Path $Dir $Name)
    New-Item -ItemType Directory -Force -Path $partial | Out-Null
    try {
        $Obj.Export([System.IO.FileInfo]::new((Join-Path $partial "$Name.xml")), $Options)
        @(foreach ($f in @(Get-ChildItem -LiteralPath $partial)) {
            $dest = Join-Path $Dir $f.Name
            Move-ExportIntoPlace $f.FullName $dest
            if ($f.PSIsContainer) { @(Get-ChildItem -LiteralPath $dest -File -Recurse) | ForEach-Object { $_.FullName } }
            else { $dest }
        })
    }
    finally { Remove-Item -LiteralPath $partial -Recurse -Force -ErrorAction SilentlyContinue }
}

# One object of a kind into the repo -> the item of an export result (name, folder, ok, format, files, removed,
# messages, note; error when it failed). Options: as export takes them. Collisions: Get-ExportCollisions of its folder.
function Export-KindEntry($Kind, $Entry, $Options, [string]$Device = '', [string]$Library = '', [hashtable]$Collisions = @{}) {
    $item = [ordered]@{ name = $Entry.name; folder = $Entry.folder }
    $clash = $Collisions[(Get-ExportBase $Kind $Entry $Library $Device)]
    if ($clash) {
        $item.ok = $false; $item.collision = @($clash)
        $item.error = Get-CollisionError $Kind $Entry $clash $Library $Device
        return $item
    }
    try {
        $r = & $Kind.export $Entry (Get-KindDir $Kind $Entry.folder $Library $Device) $Options
        $item.ok = [bool]$r.ok; $item.format = $r.format
        $item.files = @($r.files | ForEach-Object { Get-RepoRelative $_ })
        if ($r.removed) { $item.removed = @($r.removed | ForEach-Object { Get-RepoRelative $_ }) }
        if ($r.messages) { $item.messages = $r.messages }
        if ($r.note) { $item.note = $r.note }
    }
    catch {
        Set-ItemError $item $_
        # the caller (export, full_export) stops at it; the next TIA call is refused until connect
        if (Test-ItemEndedTia $item) { $null = Set-TiaEnded (Get-ItemTiaEndedCause $item) }
    }
    $item
}

function New-Refusal([string]$Reason) { @{ ok = $false; refused = $Reason } }

# The progress line of one exported object (Write-BridgeProgress): n of the m objects the call (or full_export part)
# exports, after its export.
function Write-ObjectProgress([string]$Kind, [int]$N, [int]$Of, $Item, [string]$Part = '', [string]$Device = '') {
    $p = [ordered]@{ event = 'object' }
    if ($Part) { $p.part = $Part }
    if ($Device) { $p.device = $Device }
    $p.kind = $Kind; $p.n = $N; $p.of = $Of; $p.name = [string]$Item.name; $p.ok = [bool]$Item.ok
    Write-BridgeProgress $p
}

function Get-OptionalBool($Arguments, [string]$Name, [bool]$Default) {
    $p = $Arguments.PSObject.Properties[$Name]
    if ($p -and $null -ne $p.Value) { [bool]$p.Value } else { $Default }
}

# ------------------------------------------------------------------ list

function Invoke-ListTool($a) {
    $k = Get-ObjectKind ([string]$a.kind)
    $null = Get-BridgeSession
    $entries = @(Get-KindItems $k (Get-KindRoot $k ([string]$a.device) ([string]$a.library)))
    if ($a.filter) { $entries = @($entries | Where-Object { Test-NameLike $_.name @($a.filter) }) }
    if ($a.folder) { $f = [string]$a.folder; $entries = @($entries | Where-Object { $_.folder -eq $f -or $_.folder -like "$f/*" }) }
    $items = @(foreach ($e in $entries) {
        $i = [ordered]@{ name = $e.name; folder = $e.folder }
        try { if ($k.info) { $info = & $k.info $e; foreach ($key in $info.Keys) { $i[$key] = $info[$key] } } }
        catch {
            if (Test-TiaEndedError $_) { throw }
            $i.infoError = (ConvertTo-BridgeError $_).message
        }
        $i
    })
    @{ ok = $true; kind = $k.name; count = $items.Count; items = $items }
}

# ------------------------------------------------------------------ export

# How many files of the export items (repo-relative) the export left as they were (Get-UnchangedExportCount).
function Get-ExportItemsUnchanged([object[]]$Items) {
    Get-UnchangedExportCount @($Items | ForEach-Object { $_.files } | Where-Object { $_ } | ForEach-Object { Join-Path $script:Bridge.repo $_ })
}

function Invoke-ExportTool($a) {
    $k = Get-ObjectKind ([string]$a.kind)
    $null = Get-BridgeSession
    if (-not $k.export) { return New-Refusal "Kind $($k.name) cannot be exported. $script:LibraryKindNote" }
    $patterns = @($a.names | Where-Object { $_ })
    if (-not $patterns.Count) { return New-Refusal 'names is empty: give object names or wildcards (e.g. "*").' }
    $opt = $a.options
    if ($null -eq $opt) { $opt = New-Object psobject }
    $root = Get-KindRoot $k ([string]$a.device) ([string]$a.library)
    $entries = @(Get-KindItems $k $root)
    $collisions = Get-ExportCollisions $k $entries $root ([string]$a.library) ([string]$a.device)
    $script:UnchangedExports.Clear()
    # every match first, so each object's progress line has n of m. Ordinal: @{} goes by culture and would skip one of two
    # names it takes for one
    $done = New-Object System.Collections.Hashtable ([StringComparer]::Ordinal)
    $items = New-Object System.Collections.ArrayList
    $todo = New-Object System.Collections.ArrayList
    foreach ($p in $patterns) {
        $hits = @(Select-NamedEntries $entries $p)
        if (-not $hits.Count) { [void]$items.Add(@{ name = $p; ok = $false; error = @{ type = 'TiaBridge.NotFound'; message = "No $($k.name) matches '$p'." } }); continue }
        foreach ($e in $hits) {
            $key = "$($e.folder)/$($e.name)"
            if ($done[$key]) { continue }
            $done[$key] = $true
            [void]$todo.Add($e)
        }
    }
    $n = 0
    foreach ($e in $todo) {
        $item = Export-KindEntry $k $e $opt ([string]$a.device) ([string]$a.library) $collisions
        [void]$items.Add($item)
        $n++
        Write-ObjectProgress $k.name $n $todo.Count $item -Device ([string]$a.device)
        # what was exported before stays in the repo; only the export stops
        if (Test-ItemEndedTia $item) {
            return @{ ok = $false; kind = $k.name; items = @($items); tiaEnded = $true; stopped = "The export stopped at $($item.name)."
                      unchanged = Get-ExportItemsUnchanged $items
                      note = "TIA Portal ended at $($item.name). $(Set-TiaEnded (Get-ItemTiaEndedCause $item))" }
        }
    }
    $r = @{ ok = -not @($items | Where-Object { -not $_.ok }).Count; kind = $k.name; items = @($items); unchanged = Get-ExportItemsUnchanged $items }
    $note = if ($a.library) { Get-SharedFolderNote 'Library' ([string]$a.library) (Get-GlobalLibraryNames) }
            elseif ($a.device -and $k.scope -in 'plc', 'hmi') { Get-SharedFolderNote 'Device' ([string]$a.device) @(Get-TiaSoftwareList | Where-Object { $_.kind -eq $k.scope } | ForEach-Object { [string]$_.device }) }
    if ($note) { $r.folderNote = $note }
    $r
}

# ------------------------------------------------------------------ import

# Why TIA would not delete or replace an object, or $null: the test instance of a library type in work. TIA answers
# with a modal "Cannot delete or replace (0026:000074)" and the call waits until it is closed.
function Get-InWorkRefusal([string]$KindName, [string]$Name, $Obj, [string]$Cannot, [string]$Instead) {
    $link = Get-LibraryLink $Obj
    if ($link -and $link.inWork) {
        return "$KindName '$Name' is the test instance of library type $($link.type) V $($link.version), which is in work; TIA cannot $Cannot. $Instead"
    }
    $null
}

# Why a file must not be imported over the existing object, or $null. Existing: entry of the kind's items, or $null.
# Safety: the call's safety argument. FDocument: the file is the document of an F-block.
function Get-ImportRefusal([string]$KindName, [string]$Name, $Existing, [bool]$Override, [bool]$Safety = $false, [bool]$FDocument = $false) {
    if ($Existing -and -not $Override) { return "$KindName '$Name' exists and override is false; nothing imported." }
    # by the object too: a file with the F mark taken out would turn the F-block into a standard one
    if (-not $Safety -and ($FDocument -or ($Existing -and (Test-FBlockLanguage ([string]$Existing.obj.ProgrammingLanguage))))) {
        return Get-FBlockRefusal $KindName $Name 'import'
    }
    if (-not $Existing) { return $null }
    if ($Existing.obj.IsKnowHowProtected) {
        return "$KindName '$Name' is know-how protected: an override replaced such a block unprotected when tried (an FC, an instance DB), with no password and no message, and the repo holds no copy of its code. Nothing imported: remove the protection in TIA first if it is to change."
    }
    Get-InWorkRefusal $KindName $Name $Existing.obj 'replace it by import' 'Change it in TIA, or release or discard the version in work first.'
}

# Why a document must not be imported under a name another kind holds, or $null. Blocks and DBs have one list of names in
# TIA and two kinds here: the object would be replaced by a document of another class, past the guards of the kind that
# lists it, and what TIA does then is not probed. Walks the other kind once per call, only for a name not of this kind.
function Get-NamesakeRefusal($Kind, $Root, [string]$Name, [hashtable]$Cache) {
    if (-not $Kind.sharesNamesWith) { return $null }
    if (-not $Cache.ContainsKey('namesakes')) {
        $names = New-Object System.Collections.Hashtable ([StringComparer]::OrdinalIgnoreCase)
        foreach ($e in @(Get-KindItems (Get-ObjectKind $Kind.sharesNamesWith) $Root)) { $names[$e.name] = $true }
        $Cache.namesakes = $names
    }
    if (-not $Cache.namesakes.ContainsKey($Name)) { return $null }
    "$($Kind.name) '$Name': the project holds that name as kind $($Kind.sharesNamesWith), which the document would replace. Nothing imported: delete that object first if it is to change kind, or give the document another name."
}

# The name TIA gave an imported object when it is not the one asked for, else $null. TIA can answer an import with another
# name and no message (a tag table deleted and imported straight after came back as <name>_1). Asked: the name the document
# declares; FileName: the file's, when it declares none, which holds the name in its file-safe form. Imported: the names
# TIA returned; none is no claim. Compared as TIA does, without case.
function Get-ImportedOtherName([string]$Asked, [string]$FileName, [bool]$Declared, [string[]]$Imported) {
    $names = @($Imported | Where-Object { $_ })
    if (-not $names.Count -or $names -contains $Asked) { return $null }
    if (-not $Declared -and @($names | Where-Object { (ConvertTo-SafeFileName $_) -eq $FileName }).Count) { return $null }
    $names[0]
}

function Invoke-ImportTool($a) {
    $k = Get-ObjectKind ([string]$a.kind)
    $session = Get-BridgeSession
    $gate = Test-WriteAllowed $session
    if ($gate) { return New-Refusal $gate }
    if ($k.exportOnly) { return New-Refusal "Kind $($k.name) is export only; the bridge does not import it." }
    if (-not $k.import) { return New-Refusal "Kind $($k.name) cannot be imported. $script:LibraryKindNote" }
    $importDir = Get-KindRelDir $k ([string]$a.device) ([string]$k.importDir)
    $files = @(Resolve-ImportFiles -Repo $script:Bridge.repo -KindDir $importDir -Paths @($a.paths | Where-Object { $_ }))
    if (-not $files.Count) { return New-Refusal 'paths is empty.' }
    $importRoot = [System.IO.Path]::GetFullPath((Join-Path $script:Bridge.repo $importDir)).TrimEnd('\') + '\'
    $guard = @{}
    if ($k.importGuard) {
        $present = @($files | Where-Object { -not $_.missing -and $_.file.StartsWith($importRoot, [StringComparison]::OrdinalIgnoreCase) })
        if ($present.Count) { $guard = & $k.importGuard $script:Bridge.repo $present $a }
    }
    $override = Get-OptionalBool $a 'override' ([bool]$k.defaultOverride)
    # for every file, not only for an existing object: TIA goes by the name inside the file, which may differ from the file's
    if ($override -and $k.noOverride) { return New-Refusal "override is refused for $($k.name). $($k.noOverride)" }
    $safety = $a.safety -eq $true   # only a true opens the safety program, not the text 'false'
    $target = [string]$a.target_folder
    $root = Get-KindRoot $k ([string]$a.device)
    # the save rules: a plc or hmi kind writes to the device resolved here; a library type counts for every device of its scope
    $writeDevice = if ($k.scope -in 'plc', 'hmi') { Get-TiaDeviceName $k.scope ([string]$a.device) }
    $typeDevices = if ($k.scope -eq 'library') { @{ plc = @(Get-TiaDeviceNames 'plc'); hmi = @(Get-TiaDeviceNames 'hmi') } }
    $entries = @(Get-KindItems $k $root)
    # without case, as TIA; not by culture as @{}, which takes spellings for one that TIA keeps apart
    $existing = New-Object System.Collections.Hashtable ([StringComparer]::OrdinalIgnoreCase)
    foreach ($e in $entries) { $existing[$e.name] = $e }

    # A batch is all or nothing (decided 2026-10-05: blocks that depend on each other go in together).
    # Every file is checked before TIA is touched; one refusal imports nothing.
    # shared across the files: the kind's precheck (the faceplate guard walks the library once; the screen numbers of the
    # device, exported once, take each file in turn), the namesakes
    $cache = @{}
    $plan = @(foreach ($f in $files) {
        # a file name is the object's name made file-safe (Ns:Block in Ns_Block.s7dcl): the guards and the save rules go
        # by the object, so the kind says whose file it is; $f.name stays what the file is called
        $whose = if ($k.whoseFile -and -not $f.missing) { & $k.whoseFile $f $entries }
        $f.objectName = if ($whose.name) { $whose.name } else { $f.name }
        $f.declared = [bool]$whose.name
        $item = [ordered]@{ name = $f.objectName; path = Get-RepoRelative $f.file }
        $ex = $existing[$f.objectName]
        $g = $guard[$f.file]
        if ($g -and @($g.findings).Count) { $item.findings = @($g.findings) }
        if ($f.missing) { $item.refused = "File not found: $($f.file)" }
        elseif ($k.importDir -and -not $f.file.StartsWith($importRoot, [StringComparison]::OrdinalIgnoreCase)) {
            $item.refused = "$($k.name) files are imported from $importDir only (generated documents, checked by the HMI validator)."
        }
        elseif ($g -and $g.refused) { $item.refused = $g.refused }
        elseif ($whose.refused) { $item.refused = $whose.refused }
        elseif ($k.scope -in 'plc', 'library' -and ($why = Get-DocumentRefusal $k.name $f.file)) { $item.refused = $why }
        elseif (-not $ex -and ($why = Get-NamesakeRefusal $k $root $f.objectName $cache)) { $item.refused = $why }
        else {
            $fDocument = -not $safety -and $k.scope -in 'plc', 'library' -and (Test-FBlockDocument $f.file)
            $refusal = Get-ImportRefusal -KindName $k.name -Name $f.objectName -Existing $ex -Override $override -Safety $safety -FDocument $fDocument
            if ($refusal) { $item.refused = $(if ($k.noOverride) { "$refusal $($k.noOverride)" } else { $refusal }) }
            elseif ($k.precheck) {
                $g = & $k.precheck $f $cache $entries
                if ($g) { foreach ($key in $g.Keys) { if ($key -ne 'ok') { $item[$key] = $g[$key] } } }
            }
        }
        @{ item = $item; file = $f; existing = $ex }
    })
    $refused = @($plan | Where-Object { $_.item.refused } | ForEach-Object { $_.item.name })
    if ($refused.Count) {
        foreach ($p in $plan) { $p.item.ok = $false; if (-not $p.item.refused) { $p.item.notAttempted = $true } }
        return @{ ok = $false; kind = $k.name; override = $override; items = @($plan | ForEach-Object { $_.item })
                  refused = "Nothing imported: $($refused -join ', ') refused; the batch is all or nothing." }
    }

    # Stop at the first file that fails; the transaction then rolls the whole batch back.
    # One pass is enough for screens that link to each other: a link to a screen of the same batch that does not
    # exist yet is kept by name and resolves (2026-10-06; ImportStaging.ps1 imported screens twice for it).
    $items = New-Object System.Collections.ArrayList
    $w = Invoke-TiaWrite "import of $($files.Count) $($k.name) file(s)" -RollbackIf { @($items | Where-Object { -not $_.ok }).Count -gt 0 } -Body {
        $stopped = $false
        foreach ($p in $plan) {
            $item = $p.item
            if ($stopped) { $item.ok = $false; $item.notAttempted = $true; [void]$items.Add($item); continue }
            # an existing object is replaced where it is; a new one goes to target_folder or the folder its path mirrors
            $folder = if ($p.existing) { $p.existing.folder } elseif ($target) { $target } else { $p.file.folder }
            $item.folder = $folder
            try {
                Write-BridgeLog "import $($k.name) '$($item.name)' into '$folder'"
                $r = & $k.import $root $folder $p.file $override
                Write-BridgeLog "import $($k.name) '$($item.name)' returned"
                foreach ($key in $r.Keys) { $item[$key] = $r[$key] }
                if ($item.ok) {
                    $other = Get-ImportedOtherName $item.name $p.file.name $p.file.declared @($r.imported)
                    if ($other) { $item.importedAs = $other }
                }
            }
            catch {
                Set-ItemError $item $_
            }
            [void]$items.Add($item)
            if (-not $item.ok) { $stopped = $true }
        }
    }
    # TIA ended (a refused HMI import throws NonRecoverableException): no rollback, no compile, connect first
    $ended = Get-TiaEndedResult $items 'import'
    if ($ended) { $ended.kind = $k.name; $ended.override = $override; $ended.transaction = $w.transaction; return $ended }
    if ($w.rolledBack) { Set-RolledBack $items }
    # a failed import of a name the project still does not have holds nothing for the save rules
    $absent = @(Get-FailedNamesNotCreated $k $root $plan)
    if ($absent.Count) {
        if ($writeDevice) { Clear-ObjectWrites $session $k.scope $writeDevice $absent }
        else {
            foreach ($sc in 'plc', 'hmi') { Clear-ObjectWrites $session $sc $typeDevices[$sc] $absent }
            foreach ($n in $absent) { Register-LibraryWrite $session -Name "type:$n" -Ok $true }
        }
    }
    # rolled back: only the failure is remembered (save rule 1); otherwise everything that reached TIA counts as written
    # a library type reports the scope of its instances (plc or hmi); a library write without one counts by rule 1 only
    # refused by the kind: TIA was not asked and nothing changed, so it is no write, and what is on record for the name stands
    $written = @($items | Where-Object { -not $_.notAttempted -and -not $_.rolledBack -and -not $_.refused -and $absent -notcontains $_.name } |
        ForEach-Object { @{ name = $(if ($_.importedAs) { $_.importedAs } else { $_.name }); ok = [bool]$_.ok; scope = $(if ($_.scope) { $_.scope } else { $k.scope }) } })
    foreach ($g in $written | Group-Object { $_.scope }) {
        if ($writeDevice) { Register-Write $session -Scope $g.Name -Device $writeDevice -Items @($g.Group) }
        elseif ($g.Name -in 'plc', 'hmi') { foreach ($w1 in $g.Group) { Register-LibraryTypeWrite $session $g.Name $typeDevices[$g.Name] $w1.name $w1.ok } }
        else { foreach ($w1 in $g.Group) { Register-LibraryWrite $session -Name "type:$($w1.name)" -Ok $w1.ok } }
    }
    # a type whose import threw has no scope and is held as type:<name>: its good import, with a scope, clears that too
    if (-not $writeDevice) { foreach ($w1 in @($written | Where-Object { $_.ok })) { Register-LibraryWrite $session -Name "type:$($w1.name)" -Ok $true } }
    $failed = @($items | Where-Object { -not $_.ok -and -not $_.rolledBack -and -not $_.notAttempted })
    # a transaction on which nothing reached TIA rolled nothing back
    $reachedTia = @($items | Where-Object { -not $_.notAttempted -and -not $_.refused }).Count -gt 0
    $r = @{ ok = -not $failed.Count; kind = $k.name; override = $override; items = @($items); transaction = $w.transaction; rolledBack = [bool]$w.rolledBack -and $reachedTia
            next = "compile the $((@($written | ForEach-Object { $_.scope } | Where-Object { $_ -in 'plc', 'hmi' } | Sort-Object -Unique) + @()) -join ' and ') scope, then save" }
    if (-not $written.Count) { $r.next = 'Nothing of it is in TIA: fix the file and import it again.' }
    if ($failed.Count) {
        $r.note = if ($failed[0].refused -and -not $reachedTia) { "Nothing imported: $($failed[0].name) was refused before TIA was asked." }
                  elseif ($failed[0].refused -and $w.rolledBack) { "Nothing imported: $($failed[0].name) was refused before TIA was asked, and TIA rolled back the files before it." }
                  elseif ($failed[0].refused) { "$($failed[0].name) was refused before TIA was asked. No transaction: the files before it stay imported." }
                  elseif (-not $w.transaction) { 'No transaction: the files before the failure stay imported.' }
                  elseif ($w.rolledBack) { "Nothing imported: $($failed[0].name) failed and TIA rolled the batch back." }
    }
    if ($w.note) { $r.transactionNote = $w.note }
    if ($w.commitError) { $r.commitError = $w.commitError }
    # the object is in TIA, so no failed item and no rollback; not ok, as what refers to the name asked for is broken
    $other = @($items | Where-Object { $_.importedAs -and -not $_.rolledBack })
    if ($other.Count) {
        $r.ok = $false
        $r.namedOtherwise = @($other | ForEach-Object { "'$($_.name)' is in TIA as '$($_.importedAs)'" })
        $r.next = "TIA gave $($other.Count) object(s) another name than the document: $(@($other | ForEach-Object { "delete '$($_.importedAs)' and import '$($_.name)' again" }) -join '; '), or rename it in TIA. Then $($r.next)."
    }
    if ($k.afterImport) { & $k.afterImport $r @($items) }
    $r
}

# The names of a batch whose import failed, that were not in the project before and are not now. Listed again, as without
# a transaction a failure may leave what it made. A list that fails counts as there: the failure stays remembered.
function Get-FailedNamesNotCreated($Kind, $Root, [object[]]$Plan) {
    $new = @($Plan | Where-Object { -not $_.existing -and -not $_.item.ok -and -not $_.item.notAttempted -and -not $_.item.rolledBack -and -not $_.item.refused } | ForEach-Object { $_.item.name })
    if (-not $new.Count) { return }
    $now = New-Object System.Collections.Hashtable ([StringComparer]::OrdinalIgnoreCase)
    try { foreach ($e in @(Get-KindItems $Kind $Root)) { $now[$e.name] = $true } }
    catch { Write-BridgeLog "The objects were not listed after the failed import: $($_.Exception.Message)"; return }
    $new | Where-Object { -not $now.ContainsKey($_) }
}

# ------------------------------------------------------------------ delete

function Invoke-DeleteTool($a) {
    $k = Get-ObjectKind ([string]$a.kind)
    $session = Get-BridgeSession
    $gate = Test-WriteAllowed $session
    if ($gate) { return New-Refusal $gate }
    if ($k.scope -eq 'library') { return New-Refusal "Kind $($k.name) cannot be deleted. $script:LibraryKindNote" }
    if ($k.exportOnly) { return New-Refusal "Kind $($k.name) is export only; the bridge does not delete it." }
    $names = @($a.names | Where-Object { $_ })
    if (-not $names.Count) { return New-Refusal 'names is empty.' }
    if (@($names | Where-Object { $_ -match '[*?]' }).Count) { return New-Refusal 'delete takes exact names, no wildcards.' }
    $entries = @(Get-KindItems $k (Get-KindRoot $k ([string]$a.device) ([string]$a.library)))
    $writeDevice = Get-TiaDeviceName $k.scope ([string]$a.device)
    $safety = $a.safety -eq $true   # only a true opens the safety program, not the text 'false'
    $knowhow = $a.knowhow -eq $true
    # every name is checked before the write; a refusal leaves the other names of the call to go on
    $plan = @(foreach ($n in $names) {
        $e = $entries | Where-Object { $_.name -eq $n } | Select-Object -First 1
        $item = [ordered]@{ name = $n }
        $why = if (-not $e) { "No $($k.name) named '$n'." }
               elseif (-not $safety -and (Test-FBlockLanguage ([string]$e.obj.ProgrammingLanguage))) { Get-FBlockRefusal $k.name $n 'delete' }
               elseif (-not $knowhow -and $e.obj.IsKnowHowProtected) { Get-KnowHowRefusal $k.name $n 'delete' }
               else { Get-InWorkRefusal $k.name $n $e.obj 'delete it' 'Release the version in work first, or discard it (library_discard_type).' }
        if ($why) { $item.ok = $false; $item.refused = $why }
        @{ item = $item; entry = $e }
    })
    if (-not @($plan | Where-Object { -not $_.item.refused }).Count) {
        return @{ ok = $false; kind = $k.name; items = @($plan | ForEach-Object { $_.item }) }
    }
    $items = New-Object System.Collections.ArrayList
    # a TIA that is ending gets no further delete and no commit
    $w = Invoke-TiaWrite "delete of $($names.Count) $($k.name)(s)" -RollbackIf { @($items | Where-Object { Test-ItemEndedTia $_ }).Count -gt 0 } -Body {
        $stopped = $false
        foreach ($p in $plan) {
            $item = $p.item
            if ($item.refused) { [void]$items.Add($item); continue }
            if ($stopped) { $item.ok = $false; $item.notAttempted = $true; [void]$items.Add($item); continue }
            $item.folder = $p.entry.folder
            try { $p.entry.obj.Delete(); $item.ok = $true }
            catch { Set-ItemError $item $_; $stopped = Test-ItemEndedTia $item }
            [void]$items.Add($item)
        }
    }
    $ended = Get-TiaEndedResult $items 'delete'
    if ($ended) { $ended.kind = $k.name; $ended.transaction = $w.transaction; return $ended }
    if ($w.rolledBack) { Set-RolledBack $items }
    $done = @($items | Where-Object { -not $_.refused -and -not $_.rolledBack })
    Register-Write $session -Scope $k.scope -Device $writeDevice -Items @($done | ForEach-Object { @{ name = $_.name; ok = [bool]$_.ok } })
    $r = @{ ok = -not @($items | Where-Object { -not $_.ok }).Count; kind = $k.name; items = @($items); transaction = $w.transaction
            rolledBack = [bool]$w.rolledBack; commitError = $w.commitError }
    if (@($done | Where-Object { $_.ok }).Count) { $r.next = "compile the $($k.scope) scope: a compile by name cannot clear a deleted object, and what used it shows there." }
    $r
}

# ------------------------------------------------------------------ delete_folder

# The kinds with a folder tree; delete_folder works on their user folders.
function Get-FolderKindNames { @($script:ObjectKinds.Values | Where-Object { $_.tree } | ForEach-Object { $_.name }) }

# What a folder holds: every collection it reports -> the names of its items, $null for a collection TIA answers with
# null (GetComposition may): that is not known to be empty. Every one, not those a kind names: a PLC data type folder has
# Documents beside Types and Groups.
function Get-FolderContents($Folder) {
    $c = [ordered]@{}
    foreach ($i in $Folder.GetCompositionInfos()) {
        $n = [string]$i.Name
        $items = $Folder.GetComposition($n)
        $c[$n] = if ($null -eq $items) { $null } else { , @(foreach ($o in $items) { [string]$o.Name }) }
    }
    $c
}

# The parts of a user folder's exact path, as list prints it: @{ parts } or @{ refused }.
function Split-UserFolderPath([string]$Path, [string]$Subject, [string]$RootRefusal) {
    if (-not $Path.Trim('/')) { return @{ refused = $RootRefusal } }
    if ($Path -match '[*?]') { return @{ refused = "$Subject takes one exact path, no wildcards." } }
    $parts = @($Path -split '/')
    if (@($parts | Where-Object { -not $_ }).Count) { return @{ refused = "Give the exact path as list prints it (a/b): '$Path' has an empty part." } }
    @{ parts = $parts }
}

# The paths of every user folder below a folder, as list prints them.
function Get-UserFolderPaths($Group, [string]$GroupsProperty, [string]$Prefix = '') {
    foreach ($s in $Group.$GroupsProperty) {
        $p = if ($Prefix) { "$Prefix/$($s.Name)" } else { [string]$s.Name }
        $p
        Get-UserFolderPaths $s $GroupsProperty $p
    }
}

# The user folder at a path of exact names: @{ folder } or @{ refused }. By enumeration: TIA's Find ignores case.
function Find-UserFolder($Top, [string]$GroupsProperty, [string[]]$Parts, [string]$KindName) {
    $g = $Top
    $at = ''
    foreach ($part in $Parts) {
        $subs = @($g.$GroupsProperty)
        $next = $subs | Where-Object { [string]$_.Name -ceq $part } | Select-Object -First 1
        if (-not $next) {
            $where = if ($at) { "in '$at'" } else { 'at the top' }
            $names = @($subs | ForEach-Object { [string]$_.Name }) -join ', '
            return @{ refused = "No folder '$($Parts -join '/')' in kind $KindName. Folders $where`: $(if ($names) { $names } else { 'none' })." }
        }
        $g = $next
        $at = if ($at) { "$at/$part" } else { $part }
    }
    @{ folder = $g }
}

# Delete() takes a folder with everything in it, without a prompt or an error ([PROBE], docs\agent\openness-v20.md), so
# the check here is all that keeps a folder's contents. It runs under exclusive access, where no one can add to the folder
# before the Delete. Adds nothing to the save rules: deleting a folder changes no consistency, so there is nothing to
# compile, and when it fails the folder is still there.
function Invoke-DeleteFolderTool($a) {
    $k = Get-ObjectKind ([string]$a.kind)
    $gate = Test-WriteAllowed (Get-BridgeSession)
    if ($gate) { return New-Refusal $gate }
    if (-not $k.tree) { return New-Refusal "Kind $($k.name) has no folders delete_folder works on. Kinds: $((Get-FolderKindNames) -join ', ')." }
    $path = [string]$a.folder
    $split = Split-UserFolderPath $path 'delete_folder' 'A root folder cannot be deleted: name a user folder.'
    if ($split.refused) { return New-Refusal $split.refused }
    $hit = Find-UserFolder (& $k.tree (Get-KindRoot $k ([string]$a.device))) $k.groups $split.parts $k.name
    if ($hit.refused) { return New-Refusal $hit.refused }
    $stop = @{}
    $w = Invoke-TiaWrite "delete of the empty folder $path" -RollbackIf { [bool]$stop.refused } -Body {
        $contents = Get-FolderContents $hit.folder
        if (-not $contents.Contains($k.groups)) {
            $stop.refused = "It cannot tell what the folder '$path' holds: TIA reports no collection $($k.groups) for it, only $(@($contents.Keys) -join ', '). Nothing deleted."
            return
        }
        $unread = @($contents.Keys | Where-Object { $null -eq $contents[$_] })
        if ($unread.Count) {
            $stop.refused = "It cannot tell what the folder '$path' holds: TIA answers null for its collection $($unread -join ', '). Nothing deleted."
            return
        }
        $held = [ordered]@{}
        foreach ($n in $contents.Keys) { if ($contents[$n].Count) { $held[$n] = $contents[$n] } }
        if ($held.Count) {
            $stop.holds = $held
            $stop.refused = "The folder '$path' is not empty ($(@($held.Keys | ForEach-Object { "$($_): $($held[$_].Count)" }) -join ', ')). delete_folder never clears a folder: delete the objects by name with delete and the subfolders with delete_folder, then call it again."
            return
        }
        $hit.folder.Delete()
    }
    if ($stop.refused) {
        $r = New-Refusal $stop.refused
        $r.kind = $k.name; $r.folder = $path
        if ($stop.holds) { $r.holds = $stop.holds }
        return $r
    }
    $r = @{ ok = -not ($w.rolledBack -or $w.commitError); kind = $k.name; folder = $path; transaction = $w.transaction
            rolledBack = [bool]$w.rolledBack; commitError = $w.commitError }
    if ($w.note) { $r.transactionNote = $w.note }
    $r
}

# ------------------------------------------------------------------ compile

# Blocks and PLC data types of a PLC that are not consistent, as Get-GroupTree entries: their export fails. Changed and not
# compiled since, or compiled: a compile by name of several can leave all but the last so, with 0 errors and "All blocks are
# up-to-date" (seen on real blocks calling library instructions; cause not known).
function Get-InconsistentPlcObjects($Plc) {
    @(Get-GroupTree $Plc.BlockGroup 'Blocks' 'Groups') + @(Get-GroupTree $Plc.TypeGroup 'Types' 'Groups') | Where-Object { -not $_.obj.IsConsistent }
}

# $true for the error of a compile that lacks the safety login.
function Test-SafetyPermissionError($Err) {
    [bool]((@($Err.message) + @($Err.details)) -match 'permission to modify the safety program')
}

# One object of the compile one by one (export only, no safety login): its failure is an item, not the tool's.
function Invoke-CompileObject([string]$Name, $Obj) {
    $svc = Get-TiaService $Obj ([Siemens.Engineering.Compiler.ICompilable])
    if (-not $svc) { return @{ name = $Name; ok = $false; refused = 'This object offers no compile service.' } }
    try { $tree = ConvertTo-ResultTree $svc.Compile() }
    catch {
        $e = ConvertTo-BridgeError $_
        if ($e.tiaDisconnected) { throw }
        return @{ name = $Name; ok = $false; errors = 1; error = $e }
    }
    @{ name = $Name; ok = ([int]$tree.errors -eq 0); errors = [int]$tree.errors; warnings = [int]$tree.warnings; messages = $tree }
}

# The errors of a compile's items as one line each, for what a save names.
function Get-CompileErrorTexts([object[]]$Items) {
    foreach ($i in $Items) {
        if ($i.refused) { "$($i.name): $($i.refused)" }
        elseif ([int]$i.errors -and $i.messages) {
            foreach ($e in @(Get-CompileErrors $i.messages)) { "$(if ($e.object) { $e.object } else { $e.path }): $($e.description)" }
        }
    }
}

function Invoke-CompileTool($a) {
    $session = Get-BridgeSession
    $scope = [string]$a.scope
    $device = [string]$a.device
    $compilable = [Siemens.Engineering.Compiler.ICompilable]
    $results = @()
    $names = @()
    # export only: the compile changes the copy, which is never saved
    $copyOnly = [bool]($script:Bridge.background -and -not $script:Bridge.background.write)
    $compileState = @{ oneByOne = $null }
    $plc = $null
    switch ($scope) {
        'plc' { $plc = Get-TiaSoftware 'plc' $device; $targets = @(@{ name = 'PLC software'; obj = $plc }) }
        'hmi' { $targets = @(@{ name = 'HMI'; obj = (Get-TiaSoftware 'hmi' $device) }) }
        'blocks' {
            $names = @($a.names | Where-Object { $_ })
            if (-not $names.Count) { return New-Refusal 'scope blocks needs names.' }
            $plc = Get-TiaSoftware 'plc' $device
            # PLC data types too: an imported UDT is a pending write of its own, and a PlcStruct offers ICompilable
            # (probe 2026-10-08). Before, only scope plc cleared it.
            $all = @(Get-GroupTree $plc.BlockGroup 'Blocks' 'Groups') + @(Get-GroupTree $plc.TypeGroup 'Types' 'Groups')
            $missing = @($names | Where-Object { $n = $_; -not @($all | Where-Object { $_.name -eq $n }).Count })
            if ($missing.Count) { return New-Refusal "No block or PLC data type named: $($missing -join ', ')." }
            $targets = @(foreach ($n in $names) { @{ name = $n; obj = ($all | Where-Object { $_.name -eq $n } | Select-Object -First 1).obj } })
        }
        default { return New-Refusal "scope must be plc, blocks or hmi." }
    }
    $ruleScope = if ($scope -eq 'blocks') { 'plc' } else { $scope }
    $ruleDevice = Get-TiaDeviceName $ruleScope $device
    $w = Invoke-TiaWrite "compile ($scope)" -NoTransaction -OnCopy:$copyOnly {
        foreach ($t in $targets) {
            $svc = Get-TiaService $t.obj $compilable
            if (-not $svc) { @{ name = $t.name; ok = $false; refused = 'This object offers no compile service.' }; continue }
            try { $result = $svc.Compile() }
            catch {
                # export only: without the safety login the PLC software does not compile as a whole, its standard
                # blocks do one by one; F-blocks among them fail and stay in failed
                if (-not ($copyOnly -and $scope -eq 'plc' -and (Test-SafetyPermissionError (ConvertTo-BridgeError $_)))) { throw }
                $todo = @(Get-InconsistentPlcObjects $t.obj)
                $compileState.oneByOne = $todo.Count
                Write-BridgeLog "compile (plc): no safety login, compiling $($todo.Count) blocks and PLC data types one by one"
                foreach ($o in $todo) { Invoke-CompileObject $o.name $o.obj }
                continue
            }
            $tree = ConvertTo-ResultTree $result
            @{ name = $t.name; ok = ([int]$tree.errors -eq 0); errors = [int]$tree.errors; warnings = [int]$tree.warnings; messages = $tree }
        }
    }
    $results = @($w.output)
    $errors = 0; foreach ($r in $results) { $errors += [int]$r.errors; if ($r.refused) { $errors++ } }
    $texts = @(if ($errors) { Get-CompileErrorTexts $results })
    # What TIA holds not consistent, from TIA: a compile's 0 errors do not say it. $null: not read, so nothing is claimed.
    $notConsistent = $null
    $consistencyError = $null
    if ($plc) {
        try { $notConsistent = [string[]]@(Get-InconsistentPlcObjects $plc | ForEach-Object { $_.name }) }
        catch {
            if ($copyOnly) { throw }
            $e = ConvertTo-BridgeError $_
            if ($e.tiaDisconnected) { throw }
            $consistencyError = $e.message
        }
    }
    Register-Compile $session -Scope $ruleScope -Device $ruleDevice -Names $names -ErrorCount $errors -Messages $texts -NotConsistent $notConsistent
    $r = @{ ok = ($errors -eq 0); scope = $scope; errors = $errors; items = $results }
    if ($null -ne $notConsistent) {
        # export only keeps every name: TiaArchiveCompare reads them. Else the first ten and a count: so a long list costs no answer
        $r.failed = @(if ($copyOnly) { $notConsistent } else { Get-NotConsistentOrdered $session "${ruleScope}@$ruleDevice" | Select-Object -First 10 })
        if (-not $copyOnly) { $r.failedTotal = $notConsistent.Count }
    }
    if ($consistencyError) { $r.consistencyUnread = "Whether blocks are still not consistent could not be read: $consistencyError" }
    if (-not $copyOnly -and $notConsistent.Count) {
        $r.note = "failed: what TIA holds not consistent on the whole PLC, the user's own blocks too, whatever the compile reported. Their export fails, and a save stores them so: savedWith names them, and without a session archive those this session wrote or named refuse it. " +
                  'Fix what the compile reports and compile them. A compile with 0 errors has also left blocks so: a compile of scope plc cleared that once, on a test project; it needs safety_login on a safety password, so ask the user first.'
        if ($notConsistent.Count -gt 10) { $r.note += " failed shows the first ten of failedTotal, what this session wrote or named first; list, with consistent per block, shows them all." }
    }
    if ($copyOnly) {
        $r.note = 'Compiled the copy of a background session for export only: never saved. failed: the blocks and PLC data types still not consistent (their export fails).'
        if ($null -ne $compileState.oneByOne) {
            $r.safetyLogin = $false
            $r.note += " The PLC software has a safety program and this session has no safety login: the $($compileState.oneByOne) blocks and PLC data types " +
                       'not consistent were compiled one by one instead; F-blocks need safety_login, then compile scope plc.'
        }
    }
    $r
}

# The compile of a scope on every device of it, for the tools that write to all of them (library update and release).
# Returns @{ errors; items }.
function Invoke-CompileEveryDevice([string]$Scope) {
    $errors = 0
    $items = @(foreach ($d in Get-TiaDeviceNames $Scope) {
        $c = Invoke-CompileTool ([pscustomobject]@{ scope = $Scope; device = $d })
        $errors += [int]$c.errors
        @($c.items)
    })
    @{ errors = $errors; items = $items }
}

# ------------------------------------------------------------------ registration (after the kinds are loaded)

function Register-ObjectTools {
    $kinds = @($script:ObjectKinds.Keys)
    $kindList = @(foreach ($k in $script:ObjectKinds.Values) { "$($k.name) ($($k.description))" }) -join '; '
    $device = @{ type = 'string'; description = 'PLC or HMI device name; needed only when the project has several' }
    $library = @{ type = 'string'; description = 'library kinds: name of a global library opened with library_open; default the project library' }

    Register-McpTool -Name 'list' -Handler { param($a) Invoke-ListTool $a } -Description (
        "List objects of one kind with folder and key properties: class, number, language, OB type, library link (PLC); " +
        "names and folders only for screens (Openness offers no screen number or template; export them); versions and in-work state (library). Kinds: $kindList.") -Schema @{
        type = 'object'; required = @('kind')
        properties = @{
            kind = @{ type = 'string'; enum = $kinds }
            filter = @{ type = 'array'; items = @{ type = 'string' }; description = 'exact names, or wildcards with * and ? ([ ] are literal), e.g. ["Control*"]' }
            folder = @{ type = 'string'; description = 'TIA folder path with /, includes subfolders' }
            device = $device; library = $library } }

    Register-McpTool -Name 'export' -Handler { param($a) Invoke-ExportTool $a } -Description (
        'Export objects into the project repo (folders mirror the TIA tree) and return the file paths; edit the files with your own tools. ' +
        'A file that differs from the one in the repo only in its export time stays as it is, so an object nobody changed changes no file; unchanged counts them. ' +
        'Objects whose names give one file name (Ns:Block and Ns_Block; a name is made file-safe, and Windows does not tell case) are refused, whichever is asked for: never overwritten, the files there stay, rename one in TIA. ' +
        "block/db/type: .s7dcl + .s7res ($(Get-GuidePath 's7dcl-format.md')); OBs and know-how protected blocks: SimaticML. A successful block/db/type export removes " +
        'that object''s files in the other format (and an .s7res it no longer writes) and lists them in the item''s removed: commit the removals with the export. plc_tag_table and HMI kinds: SimaticML, ' +
        'hmi_screen/hmi_template/hmi_popup: always the full export (WithDefaults + WithReadOnly) into hmi\<kind dir>; options.full changes nothing for them. ' +
        'hmi_tag_table/hmi_textlist: minimal unless options.full, in hmi\<kind dir>. library_type: the documents of the version in work (else the default one) ' +
        'into a folder of the type, .libinfo + .libint + .s7dcl/.s7res (SD) or .xml (SimaticML); options.format picks one, without it the type keeps the format ' +
        'its folder holds (SD for a new export). The folder is replaced whole, so the type is in one format only (a folder holding a git repo is not: that export is refused and the folder stays as it was); the item''s removed lists the files of the other ' +
        'format: commit them with the export. Use xml for a type whose LAD/FBD has operands indexed in several dimensions (a[i, j]; the SD import keeps only the last index, ' +
        'the export''s note says so). options.released exports the default released version into <name>.released for comparison. faceplate_type: version metadata only, plus <type>.type.json (name, library folder, versions) for the HMI preview.') -Schema @{
        type = 'object'; required = @('kind', 'names')
        properties = @{
            kind = @{ type = 'string'; enum = $kinds }
            names = @{ type = 'array'; items = @{ type = 'string' }; description = 'exact names, or wildcards with * and ? ([ ] are literal)' }
            options = @{ type = 'object'; properties = @{
                    format = @{ type = 'string'; enum = @('s7dcl', 'xml'); description = 'blocks/types and library_type only; s7dcl is refused for OBs' }
                    full = @{ type = 'boolean'; description = 'export every attribute (WithDefaults + WithReadOnly); no effect on hmi_screen/hmi_template/hmi_popup, which are always exported full' }
                    released = @{ type = 'boolean'; description = 'library_type: the default released version, for comparison' } } }
            device = $device; library = $library } }

    Register-McpTool -Name 'import' -Handler { param($a) Invoke-ImportTool $a } -Description (
        'Import files from the project repo into TIA under ExclusiveAccess (one undoable transaction where TIA allows it). .s7dcl via ImportFromDocuments ' +
        '(give the .s7dcl or .s7res path; the pair goes together; a .s7dcl with LF line ends is first rewritten as CRLF in place, since TIA indents an SCL body deeper on every round trip otherwise), .xml via Import. library_type: the documents in the folder of the given file (SD or SimaticML, ' +
        'refused when the folder holds both) into the version in work through CreateFromDocuments; the file names the type in its file-safe form (Ns:Block in Ns_Block.s7dcl), ' +
        'refused when that fits two types or the document declares neither that type nor a project instance of it; what it makes in the PLC beside the type (copies name_1 on old versions, from any document) is named in copiesBack. Every other kind: the name the document declares is the object, whatever the file is called. ' +
        'Refused: a document declaring a second object, or one with a keyword whose object cannot be read, a document of another kind (an FB under db, a DB under block, a tag table, watch table or HMI document under block, db or type; a DB, OB, tag table, watch table or HMI document under library_type; a block, DB, data type or HMI document, or the other of the two tables, under plc_tag_table or watch_table), a document of a name the other of block and db holds, and for PLC objects and library types a file that is no .s7dcl or .xml; plc_tag_table, watch_table and the HMI kinds take .xml only. ' +
        'An import TIA answers with another name than the document declares is not ok, though the object is in TIA: the item has importedAs, the result namedOtherwise and what to do. ' +
        'watch_table: a row naming a symbol the PLC does not have makes TIA answer OK and leave the table not consistent with none of its rows; the bridge fails that item (error TiaBridge.NotConsistent, naming the table) and the call rolls back. Over an existing table the save is then refused until that table is imported good, after a rollback too, and without a transaction the table also stays not consistent and empty; a new table rolled back is not in the project and holds nothing. ' +
        'An existing object is replaced where it is; a new one goes to ' +
        'target_folder, else the TIA folder its repo path mirrors. Paths may be absolute and lie outside the repo, except for HMI screens, templates, pop-ups and tag tables. ' +
        'override defaults to true, except hmi_template and hmi_tag_table (an existing one is refused). ' +
        'HMI screens/templates/pop-ups/tag tables are imported from hmi\generated\<kind> only (tag tables: hmi\generated\tags; hmi\<device>\generated\<kind> in a project with several HMI devices) and checked first by python -m hmipreview validate --import [--device]: refused on its errors for the imported documents ' +
        '(findings listed per item), on open planned items, and for screens/templates/pop-ups on a TIA export newer than the generated document unless override is passed as true (the screen default does not count; an existing tag table is refused anyway). ' +
        'Refused: .s7dcl of an OB; HMI screens/templates/pop-ups whose faceplate type versions are not in the project library; ' +
        'an HMI screen whose number another screen of the device has, in TIA or earlier in the call, new or over another screen (it ended TIA; the bridge exports each screen of the device to read its number, ' +
        'an override takes the document''s number and frees the one it had, a document without a number gets the lowest free one); any write before the session archive; ' +
        'an F-block (the file or the object it replaces) or the document of an F-compliant PLC data type without safety: true (a data type by its document only: with the mark taken out, nothing refuses it); override of a know-how protected block; override of hmi_tag_table (it crashed TIA: delete the table first, then import). ' +
        'Import HMI documents only after the user''s yes to their preview. Skill tia-change, hmi.md, holds that stop and the order of HMI imports. Never re-import a screen that holds an alarm view or diagnostics view ' +
        '(the export drops them). A call is all or nothing: one refused or failed file and nothing of the call is imported ' +
        '(the result says which file and why); put blocks that depend on each other in one call. Compile afterwards.') -Schema @{
        type = 'object'; required = @('kind', 'paths')
        properties = @{
            kind = @{ type = 'string'; enum = $kinds }
            paths = @{ type = 'array'; items = @{ type = 'string' }; description = 'files, relative to the project repo or absolute' }
            target_folder = @{ type = 'string'; description = 'TIA folder path with / for new objects; created if missing' }
            override = @{ type = 'boolean'; description = 'replace existing objects (TIA Override). HMI screens/templates/pop-ups: passed as true it also imports a generated document older than its TIA export (overwrites the TIA edits); the default does not' }
            safety = $script:SafetyArgument
            device = $device } }

    Register-McpTool -Name 'delete' -Handler { param($a) Invoke-DeleteTool $a } -Description (
        'Delete objects by exact name (e.g. test blocks from bisecting, objects after a rename). Counts as a write: compile afterwards. ' +
        'Refused per name: the test instance of a library type in work (release the version in work first, or discard it with library_discard_type); an F-block without safety: true (an F-compliant PLC data type is not recognised here); a know-how protected block without knowhow: true (its code cannot be exported, so only a project archive can restore it: the session archive, unless it was skipped); the other names go on.') -Schema @{
        type = 'object'; required = @('kind', 'names')
        properties = @{ kind = @{ type = 'string'; enum = $kinds }; names = @{ type = 'array'; items = @{ type = 'string' } }; safety = $script:SafetyArgument
                        knowhow = @{ type = 'boolean'; description = 'allows the delete of know-how protected blocks. Only when the user asked for this delete; never to get past the refusal' }; device = $device } }

    Register-McpTool -Name 'delete_folder' -Handler { param($a) Invoke-DeleteFolderTool $a } -Description (
        'Delete one empty user folder by its exact path, as list prints it (a/b), e.g. the zzStaging the HMI workflow leaves behind. ' +
        'Refused unless the folder holds nothing, read from TIA under exclusive access across every collection it has; the result names what it holds (holds). ' +
        'Never recursive: TIA''s own delete of a folder would take everything in it without asking, so clear a folder with delete of the named objects first. ' +
        'A root folder cannot go. No wildcards. Library folders are not covered. Needs the session archive. Needs no compile: it changes no consistency, and the save rules stay as they were.') -Schema @{
        type = 'object'; required = @('kind', 'folder')
        properties = @{ kind = @{ type = 'string'; enum = @(Get-FolderKindNames) }; folder = @{ type = 'string'; description = 'exact TIA folder path with /' }; device = $device } }

    Register-McpTool -Name 'compile' -Handler { param($a) Invoke-CompileAndReadChange $a } -Description (
        'Compile the PLC software (scope plc), single blocks or PLC data types (scope blocks + names) or the HMI (scope hmi). Returns the full compiler message tree. ' +
        "failed names what TIA holds not consistent afterwards on the whole PLC, the user's own blocks too, also with 0 errors: their export fails. At most ten names, what this session wrote or named first, and failedTotal; list shows them all. In a session for export only every name. " +
        'consistencyUnread: that could not be read, so failed is left out and what a save holds stays as it was. ' +
        'Compile the written scope on each device written to before save; warnings are allowed. Errors, a write not compiled, or a block this session wrote or named left not consistent refuse the save only in a session without an archive; with one the save result names them (see save). A clean compile by name takes back the errors on record of those names. In a background session for export only it compiles ' +
        'the copy (scope plc or blocks), never saved, so uncompiled blocks export; failed names what is still not consistent. There, without safety_login, ' +
        'scope plc of a PLC with a safety program compiles the blocks not consistent one by one (safetyLogin false). ' +
        'With an open library change, a compile of the PLC or by name reads what stands in work: alsoInWork names the types of the change its record did not have in work, and its report takes them; changeUnread: that could not be read.') -Schema @{
        type = 'object'; required = @('scope')
        properties = @{
            scope = @{ type = 'string'; enum = @('plc', 'blocks', 'hmi') }
            names = @{ type = 'array'; items = @{ type = 'string' } }
            device = $device } }
}
