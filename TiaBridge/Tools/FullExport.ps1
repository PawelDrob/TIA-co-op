# Tools\FullExport.ps1 - full_export: the whole project into its repo in one call. Every PLC and HMI device, the
# project-level data and the project library, part by part; what Openness cannot export is listed with the reason
# (leftOut). Read only: works under connect and in a background session (export only). The repo then mirrors the
# project: files of objects no longer in it are removed, only in the folders the export writes (decided
# 2026-10-30), unless git has no commit of them as they are: those stay and are listed (keptUncommitted); a git
# repo inside such a folder stays whole and is listed (keptRepos). The hardware part (CAx/AutomationML) was removed
# 2026-10-30: nothing read the .aml and it took most of the time. Blocks, DBs, data types and PLC tag tables TIA has not
# changed since the last export are skipped (Tools\ExportRecord.ps1), unless full: true.

. (Join-Path $PSScriptRoot 'ExportRecord.ps1')

# Project graphics: TIA took back its export with the image folder beside it identically, and a replaced image and a new
# graphic landed; a graphic list naming the graphic exported the same after it [PROBE] (2026-11-12, test project). The
# same through this bridge, and a document naming no image went in as a graphic with no image [PROBE] (2026-11-17).
Register-ObjectKind 'graphic' @{
    scope = 'project'; dir = 'project\graphics'; defaultOverride = $true
    usedBy = 'hmi'
    noDelete = 'Deleting a graphic was not tried on a real TIA, and graphic lists and screens name it. Delete it in TIA.'
    description = 'project graphics (multilingual graphics of the HMI): <name>.xml with its image folder ''<name> files'' beside it, as the export writes them; an image the document names that is not there is refused; not deleted'
    items = { param($p) foreach ($g in $p.Graphics) { @{ obj = $g; name = $g.Name; folder = '' } } }
    # a multilingual graphic writes its images beside the .xml
    export = { param($e, $dir, $opt)
        $files = @(Export-ObjectFolder $e.obj $dir (ConvertTo-SafeFileName $e.name) ([Siemens.Engineering.ExportOptions]::WithDefaults))
        @{ ok = $true; format = 'xml'; files = $files } }
    precheck = { param($file, $cache) Test-GraphicFile $file }
    import = { param($p, $folder, $file, $override) Import-SimaticMlFile $p.Graphics $file $override }
    whoseFile = { param($file, $entries) Get-DocumentFileObject $file }
}

# The precheck of kind graphic: SimaticML of a multilingual graphic, and every image it names (external="path", relative
# to the .xml) there, as TIA reads them from beside the document.
function Test-GraphicFile($File) {
    $doc = Read-HmiDocumentObject $File 'Hmi.Globalization.MultiLingualGraphic' 'graphic'
    if ($doc.refused) { return $doc }
    $name = if ($File.objectName) { [string]$File.objectName } else { [string]$File.name }
    $dir = [System.IO.Path]::GetDirectoryName($File.file)
    $images = @($doc.node.SelectNodes(".//*[@external='path']"))
    # every export seen names its DefaultImageStream; TIA takes a document without one as a graphic with no image
    if (-not $images.Count) {
        return @{ ok = $false; refused = "Graphic '$name' names no image (an element with external=`"path`", as DefaultImageStream in an export): TIA would make it a graphic with no image, which shows nothing. Nothing imported: name its image as the export does." }
    }
    foreach ($node in $images) {
        $image = $node.InnerText.Trim()
        if (-not $image -or -not (Test-Path -LiteralPath ([System.IO.Path]::Combine($dir, $image)) -PathType Leaf)) {
            return @{ ok = $false; refused = "Graphic '$name' names the image '$image', which is not beside its document ($dir). TIA reads the images from where the document names them, relative to it, as the export writes them into '<name> files': copy the image folder with the .xml." }
        }
    }
}

# ------------------------------------------------------------------ file parts (one export call writes a file)

# Throws when an Openness result reports an error (states Error, Failure, ErrorRollback); returns its tree.
function Assert-ExportResult($Result, [string]$What) {
    $tree = ConvertTo-ResultTree $Result
    if ($tree -and [string]$tree.state -match 'Error|Failure') {
        $text = @($tree.messages | ForEach-Object { $_.description } | Where-Object { $_ }) -join ' | '
        throw "$What`: TIA reported $($tree.state)$(if ($text) { ": $text" })"
    }
    $tree
}

function Get-RequiredService($Obj, [type]$Type) {
    $step = [TiaBridgeTimes]::Enter('tia_properties')
    try { $s = Get-TiaService $Obj $Type }
    finally { [TiaBridgeTimes]::Exit($step) }
    if (-not $s) { throw "$($Type.Name) is not offered here." }
    $s
}

# One export call of a file part into TIA (Export): its result, timed as tia_export_file.
function Invoke-TiaFileExport([scriptblock]$Export) {
    $step = [TiaBridgeTimes]::Enter('tia_export_file')
    try { & $Export }
    finally { [TiaBridgeTimes]::Exit($step) }
}

# PLC alarm text lists and alarm instance texts as .xlsx: the only file format Openness V20 offers for them
# (PlcAlarmTextListProvider, PlcAlarmTextProvider; PlcAlarmUserTextlist has no Export) [PROBE] (2026-10-30).
function Export-PlcAlarmTexts($Plc, [string]$Dir) {
    $notes = @()
    $lists = Get-RequiredService $Plc ([Siemens.Engineering.SW.Alarm.PlcAlarmTextListProvider])
    try { $null = Assert-ExportResult (Invoke-TiaFileExport { $lists.ExportToXlsx([System.IO.FileInfo]::new((Join-Path $Dir 'alarm-textlists.xlsx'))) }) 'PLC alarm text lists' }
    catch {
        if ((ConvertTo-BridgeError $_).type -notmatch 'TextListNotFound') { throw }
        $notes += 'no PLC alarm text lists'
    }
    $texts = Get-RequiredService $Plc ([Siemens.Engineering.SW.Alarm.PlcAlarmTextProvider])
    # languages $null: every project language. A PLC without program alarms: "There is no exportable alarm." [PROBE]
    try {
        $null = Assert-ExportResult (Invoke-TiaFileExport { $texts.ExportInstanceTextsToXlsx([System.IO.FileInfo]::new((Join-Path $Dir 'alarm-texts.xlsx')), $null,
                                     [Siemens.Engineering.SW.Alarm.PlcAlarmTextXlsxExportOption]::All) }) 'PLC alarm texts'
    }
    catch {
        if ((ConvertTo-BridgeError $_).message -notmatch 'no exportable alarm') { throw }
        $notes += 'no program alarms'
    }
    @{ notes = $notes }
}

# ProDiag global supervisions (.xlsx).
function Export-PlcSupervisions($Plc, [string]$Dir) {
    $svc = Get-RequiredService $Plc ([Siemens.Engineering.SW.Supervision.SupervisionProvider])
    $null = Assert-ExportResult (Invoke-TiaFileExport { $svc.ExportSupervisionsToXlsx([System.IO.FileInfo]::new((Join-Path $Dir 'supervisions.xlsx'))) }) 'ProDiag supervisions'
    @{}
}

# Project texts: one .xlsx per active language besides the reference language (ExportProjectTexts takes one source
# and one target language); the reference language alone when it is the only one.
function Get-ProjectTextLanguages($Project) {
    $ls = $Project.LanguageSettings
    $ref = $ls.ReferenceLanguage.Culture
    $targets = @($ls.ActiveLanguages | Where-Object { $_.Culture.Name -ne $ref.Name } | ForEach-Object { $_.Culture })
    if (-not $targets.Count) { $targets = @($ref) }
    @{ ref = $ref; targets = $targets }
}

# The file name, without extension, of the project texts of one target language.
function Get-ProjectTextsName($Ref, $Target) { "project-texts_$($Ref.Name)_$($Target.Name)" }

function Export-ProjectTexts($Project, [string]$Dir) {
    $languages = Get-ProjectTextLanguages $Project
    $ref = $languages.ref
    foreach ($t in $languages.targets) {
        Invoke-TiaFileExport { $Project.ExportProjectTexts([System.IO.FileInfo]::new((Join-Path $Dir "$(Get-ProjectTextsName $ref $t).xlsx")), $ref, $t) }
    }
    @{ notes = @("reference language $($ref.Name); $($languages.targets.Count) file(s)") }
}

# The project settings below export as .dat only: .xml is refused ("The file to be processed has an invalid extension.
# Abort." for alarm classes, .xlsx too; "Filename suffix must be .dat" for diagnostics). A .dat is a zip holding one
# XML file of the same name [PROBE] (2026-10-30, project A). The .dat is kept (it is what Import takes) and its XML is
# written beside it as <name>.xml, so the settings can be read and diffed.
function Export-SettingsDat($Service, [string]$Dir, [string]$Name, [string]$What) {
    $dat = Join-Path $Dir "$Name.dat"
    $null = Assert-ExportResult (Invoke-TiaFileExport { $Service.Export([System.IO.FileInfo]::new($dat)) }) $What
    Add-Type -AssemblyName System.IO.Compression.FileSystem
    $zip = [System.IO.Compression.ZipFile]::OpenRead($dat)
    try {
        $entries = @($zip.Entries)
        if ($entries.Count -ne 1) { return @{ notes = @("$Name.dat holds $($entries.Count) files; not expanded") } }
        $reader = New-Object System.IO.StreamReader ($entries[0].Open())
        try { Write-TextFile (Join-Path $Dir "$Name.xml") $reader.ReadToEnd() } finally { $reader.Dispose() }
    }
    finally { $zip.Dispose() }
    @{ objects = 1 }
}

function Export-AlarmClasses($Project, [string]$Dir) {
    Export-SettingsDat (Get-RequiredService $Project ([Siemens.Engineering.SW.Alarm.AlarmClassDataProvider])) $Dir 'alarm-classes' 'alarm classes'
}

# A project without them answers ErrorRollback "Global settings are not initialized!": nothing to export, like a PLC
# without program alarms. Seen on every full_export of project C (2026-11-02), not on projects A and B, which export them.
function Export-SupervisionSettings($Project, [string]$Dir) {
    $svc = Get-RequiredService $Project ([Siemens.Engineering.SW.Supervision.SupervisionSettingsProvider])
    try { Export-SettingsDat $svc $Dir 'supervision-settings' 'supervision settings' }
    catch {
        if ((ConvertTo-BridgeError $_).message -notmatch 'Global settings are not initialized') { throw }
        @{ none = $true }
    }
}

function Export-DiagnosticsSettings($Project, [string]$Dir) {
    Export-SettingsDat (Get-RequiredService $Project ([Siemens.Engineering.HW.Systemdiagnostics.Settings.SystemdiagnosticsSettingsDataProvider])) $Dir 'systemdiagnostics-settings' 'system diagnostics settings'
}

# Master copies have no export in Openness: their names, folders and contents as an index.
function Export-MasterCopyIndex($Library, [string]$Dir) {
    $k = Get-ObjectKind 'master_copy'
    $list = @(foreach ($e in Get-KindItems $k $Library) {
        $step = [TiaBridgeTimes]::Enter('tia_properties')
        try { $i = & $k.info $e }
        finally { [TiaBridgeTimes]::Exit($step) }
        [ordered]@{ folder = $e.folder; name = $e.name; author = $i.author; created = $i.created; content = @($i.content) }
    })
    if (-not $list.Count) { return @{ none = $true } }
    Write-TextFile (Join-Path $Dir 'mastercopies.json') (ConvertTo-Json -Depth 5 -InputObject $list)
    @{ objects = $list.Count }
}

# ------------------------------------------------------------------ parts

# scope: plc and hmi parts run once per device, project and library parts once. A part exports a kind object by
# object (kind; fallback: an SD export TIA refuses is done as SimaticML; filter: entries to leave out), or writes
# the files of its own folder (dir + file: (root, folder) -> @{ notes; none; objects }), or only counts what Openness
# cannot export (counter + leftOut).
$script:FullExportParts = @(
    @{ name = 'blocks'; scope = 'plc'; kind = 'block'; fallback = $true }
    @{ name = 'dbs'; scope = 'plc'; kind = 'db'; fallback = $true }
    @{ name = 'types'; scope = 'plc'; kind = 'type'; fallback = $true }
    @{ name = 'plc_tags'; scope = 'plc'; kind = 'plc_tag_table' }
    @{ name = 'system_blocks'; scope = 'plc'; kind = 'system_block' }
    @{ name = 'technology_objects'; scope = 'plc'; kind = 'technology_object' }
    @{ name = 'watch_tables'; scope = 'plc'; kind = 'watch_table' }
    @{ name = 'force_tables'; scope = 'plc'; kind = 'force_table' }
    @{ name = 'plc_alarm_texts'; scope = 'plc'; dir = 'plc\alarms'; file = { param($r, $d) Export-PlcAlarmTexts $r $d } }
    @{ name = 'supervisions'; scope = 'plc'; dir = 'plc\supervisions'; file = { param($r, $d) Export-PlcSupervisions $r $d } }
    @{ name = 'external_sources'; scope = 'plc'; counter = { param($r) @(Get-GroupTree $r.ExternalSourceGroup 'ExternalSources' 'Groups') }
       leftOut = 'external source files: Openness V20 offers no export of their content' }
    @{ name = 'hmi_screens'; scope = 'hmi'; kind = 'hmi_screen' }
    @{ name = 'hmi_templates'; scope = 'hmi'; kind = 'hmi_template' }
    @{ name = 'hmi_popups'; scope = 'hmi'; kind = 'hmi_popup' }
    @{ name = 'hmi_slideins'; scope = 'hmi'; kind = 'hmi_slidein' }
    @{ name = 'hmi_screen_globals'; scope = 'hmi'; kind = 'hmi_screen_global' }
    @{ name = 'hmi_tags'; scope = 'hmi'; kind = 'hmi_tag_table' }
    @{ name = 'hmi_textlists'; scope = 'hmi'; kind = 'hmi_textlist' }
    @{ name = 'hmi_graphiclists'; scope = 'hmi'; kind = 'hmi_graphiclist' }
    @{ name = 'hmi_scripts'; scope = 'hmi'; kind = 'hmi_vbscript' }
    @{ name = 'hmi_cycles'; scope = 'hmi'; kind = 'hmi_cycle' }
    @{ name = 'hmi_connections'; scope = 'hmi'; kind = 'hmi_connection' }
    @{ name = 'graphics'; scope = 'project'; kind = 'graphic' }
    @{ name = 'project_texts'; scope = 'project'; dir = 'project\texts'; file = { param($r, $d) Export-ProjectTexts $r $d } }
    @{ name = 'alarm_classes'; scope = 'project'; dir = 'project\alarmclasses'; file = { param($r, $d) Export-AlarmClasses $r $d } }
    @{ name = 'supervision_settings'; scope = 'project'; dir = 'project\supervision'; file = { param($r, $d) Export-SupervisionSettings $r $d } }
    @{ name = 'diagnostics_settings'; scope = 'project'; dir = 'project\diagnostics'; file = { param($r, $d) Export-DiagnosticsSettings $r $d } }
    @{ name = 'library_types'; scope = 'library'; kind = 'library_type'; fallback = $true
       filter = { param($e) $e.obj.GetType().Name -notmatch 'Faceplate' } }
    @{ name = 'faceplate_types'; scope = 'library'; kind = 'faceplate_type' }
    @{ name = 'master_copies'; scope = 'library'; dir = 'library\mastercopies'; file = { param($r, $d) Export-MasterCopyIndex $r $d } }
)

# What no part can export (Openness V20 limits, Siemens manual and [PROBE]s), listed in every result.
$script:FullExportLimits = @(
    'WinCC Comfort/Advanced alarms (discrete, analog), recipes, data and alarm logs, user administration: no Openness object in V20 (Siemens.Engineering.Hmi.Alarm/.Recipe/.Logging hold enums only)'
    'screen objects Openness cannot export (alarm view, trend view, recipe view, system diagnostics view, ...): the screen export leaves them out without a message'
    'faceplate type contents: version metadata only (library\faceplates)'
    'master copy contents: no export in Openness; library\mastercopies\mastercopies.json lists them'
    'hardware configuration: not exported (the CAx/AutomationML part was removed 2026-10-30)'
    'know-how protected blocks: SimaticML with the interface only, unless unprotected'
    'F-system blocks: cannot be exported (Siemens); F-blocks of the user export like other blocks'
)

function Get-FullExportPart([string]$Name) { $script:FullExportParts | Where-Object { $_.name -eq $Name } | Select-Object -First 1 }

# The repo folder a part writes (relative), for a device of its scope; nothing for a part that only counts.
function Get-PartDir($Part, [string]$Device) {
    if ($Part.kind) { Get-KindRelDir (Get-ObjectKind $Part.kind) $Device }
    elseif ($Part.dir) {
        $d = Get-DeviceDir $Part.scope $Device
        if ($d) { "$($Part.dir.Substring(0, 4))$d\$($Part.dir.Substring(4))" } else { $Part.dir }
    }
}

# Whether Path is a file an object of that base path exports: <base>.*, <base>\*, the images of a graphic (<base> files\*)
# or a faceplate type's version file (<base>_V<version>.xml). Base '<dir>\': the .xml an object without a name wrote.
function Test-MirrorKept([string]$Path, [string]$Base) {
    foreach ($prefix in "$Base.", "$Base\", "$Base files\") { if ($Path.StartsWith($prefix, [StringComparison]::OrdinalIgnoreCase)) { return $true } }
    [regex]::IsMatch($Path, "^$([regex]::Escape($Base))_V\d[\d.]*\.xml$", 'IgnoreCase')
}

# The git repos a mirror of Dir must leave whole, full paths: those inside Dir, Dir itself, or a folder between Dir and
# the project repo (Test-GitRepoFolder). git status of the outer repo names only the folder of a repo with a .git, so no
# file of it reads as uncommitted; a bare one needs its empty folders; and a repo's history is not in the outer repo.
function Get-NestedRepos([string]$Dir) {
    $found = @(if (Test-Path -LiteralPath $Dir) { Get-GitRepoFolders $Dir })
    if ($script:Bridge.repo) {
        $top = [System.IO.Path]::GetFullPath($script:Bridge.repo).TrimEnd('\')
        $p = [System.IO.Path]::GetFullPath($Dir).TrimEnd('\')
        while ($p.StartsWith("$top\", [StringComparison]::OrdinalIgnoreCase)) {
            if (Test-GitRepoFolder $p) { $found += $p }
            $p = [System.IO.Path]::GetDirectoryName($p)
        }
    }
    $found = @($found | Sort-Object -Unique)
    @($found | Where-Object { -not (Test-InNestedRepo $_ $found) })
}

# Whether Path lies inside one of the repos (Get-NestedRepos).
function Test-InNestedRepo([string]$Path, [string[]]$Repos) {
    foreach ($r in $Repos) { if ($Path.StartsWith("$r\", [StringComparison]::OrdinalIgnoreCase)) { return $true } }
    $false
}

# Files under Dir that Mirror removes: not written by this export (Written, full paths), not of an object whose
# export failed (Kept: full base paths, Test-MirrorKept), no .gitkeep, nothing under a *.released folder
# (comparison exports of library types), no .partial leftover of another call and nothing of a nested repo.
function Get-MirrorRemovals([string]$Dir, [string[]]$Written, [string[]]$Kept) {
    if (-not (Test-Path -LiteralPath $Dir)) { return @() }
    $repos = Get-NestedRepos $Dir
    $w = @{}; foreach ($f in $Written) { $w[[System.IO.Path]::GetFullPath($f).ToLowerInvariant()] = $true }
    foreach ($f in @(Get-ChildItem -LiteralPath $Dir -File -Recurse -Force)) {
        $p = $f.FullName
        if ($w[$p.ToLowerInvariant()] -or $f.Name -eq '.gitkeep' -or $p -match '\.released\\' -or $p -match '\.partial(\\|$)' -or (Test-InNestedRepo $p $repos)) { continue }
        $hold = $false
        foreach ($k in $Kept) { if (Test-MirrorKept $p $k) { $hold = $true; break } }
        if (-not $hold) { $p }
    }
}

# Files of Repo that git could not bring back once removed: untracked, ignored, or changed and not committed (staged
# or not). Returns @{ paths = lower-case full path -> $true; error }. Repo must be the top of its git repo. Not through
# Invoke-GitRaw: its pipe decodes git's UTF-8 with the console code page, a non-ASCII name would not be found and its
# file removed. -z: names as they are, not quoted; --no-renames: one name per entry.
function Get-GitUncommittedFiles([string]$Repo) {
    $step = [TiaBridgeTimes]::Enter('git')
    try { Read-GitUncommittedFiles $Repo }
    finally { [TiaBridgeTimes]::Exit($step) }
}

function Read-GitUncommittedFiles([string]$Repo) {
    if (-not (Test-Path -LiteralPath (Join-Path $Repo '.git'))) { return @{ paths = @{}; error = "$Repo is not a git repo (no .git)" } }
    Clear-GitContext
    $psi = New-Object System.Diagnostics.ProcessStartInfo
    $psi.FileName = 'git'
    $psi.Arguments = '--no-optional-locks status --porcelain=v1 -z --untracked-files=all --ignored --no-renames'
    $psi.WorkingDirectory = $Repo
    $psi.UseShellExecute = $false
    $psi.CreateNoWindow = $true
    $psi.RedirectStandardOutput = $true
    $psi.RedirectStandardError = $true
    $psi.StandardOutputEncoding = [System.Text.Encoding]::UTF8
    $psi.StandardErrorEncoding = [System.Text.Encoding]::UTF8
    try { $p = [System.Diagnostics.Process]::Start($psi) }
    catch { return @{ paths = @{}; error = "git could not be started: $($_.Exception.Message)" } }
    $err = $p.StandardError.ReadToEndAsync()
    $out = $p.StandardOutput.ReadToEnd()
    $p.WaitForExit()
    if ($p.ExitCode) { return @{ paths = @{}; error = "git status exited with $($p.ExitCode): $($err.Result.Trim())" } }
    $paths = @{}
    foreach ($e in $out.Split([char]0)) {
        if ($e.Length -gt 3) { $paths[[System.IO.Path]::GetFullPath((Join-Path $Repo $e.Substring(3).Replace('/', '\'))).ToLowerInvariant()] = $true }
    }
    @{ paths = $paths; error = $null }
}

# Splits files a mirror would remove -> @{ remove; keep; error }: uncommitted ones stay. Asked right before the removal,
# so a file written during a long export counts. When git cannot tell (error), all stay. A plain export folder has no git.
function Split-MirrorRemovals([string[]]$Files) {
    $Files = @($Files | Where-Object { $_ })
    if (-not $Files.Count -or ($script:Bridge.background -and $script:Bridge.background.plain)) { return @{ remove = $Files; keep = @(); error = $null } }
    $u = Get-GitUncommittedFiles $script:Bridge.repo
    if ($u.error) { return @{ remove = @(); keep = $Files; error = $u.error } }
    $keep = @($Files | Where-Object { $u.paths[[System.IO.Path]::GetFullPath($_).ToLowerInvariant()] })
    $remove = @($Files | Where-Object { -not $u.paths[[System.IO.Path]::GetFullPath($_).ToLowerInvariant()] })
    @{ remove = $remove; keep = $keep; error = $null }
}

# Removes the files and then the folders below Dir left empty, none of a nested repo (a repo holds empty folders it
# cannot do without). Returns @{ removed; errors }.
function Remove-MirrorFiles([string]$Dir, [string[]]$Files) {
    $removed = @(); $errors = @()
    foreach ($f in $Files) {
        try { Remove-Item -LiteralPath $f -Force -ErrorAction Stop; $removed += $f }
        catch { $errors += "$f`: $($_.Exception.Message)" }
    }
    $repos = Get-NestedRepos $Dir
    $dirs = @(Get-ChildItem -LiteralPath $Dir -Directory -Recurse -Force -ErrorAction SilentlyContinue | Where-Object { -not (Test-InNestedRepo $_.FullName $repos) } | Sort-Object { $_.FullName.Length } -Descending)
    foreach ($d in $dirs) { if (-not @(Get-ChildItem -LiteralPath $d.FullName -Force).Count) { Remove-Item -LiteralPath $d.FullName -Force -ErrorAction SilentlyContinue } }
    @{ removed = $removed; errors = $errors }
}

# Why TIA does not export an object by design (then it is left out, not failed), or $null [PROBE] (2026-10-30, project A):
# the F-system blocks under System blocks/STEP 7 Safety (219) and the F-OB of the F-runtime group (FOB_RTG1) answer
# "The export of block '...' is not permitted."; a know-how protected library type answers ExportAsDocuments with
# "The block is know-how-protected and cannot be exported." in either format.
function Get-LeftOutReason($Item) {
    $m = [string]$Item.error.message
    if ($m -match "export of block '.*' is not permitted") { return 'F-system blocks and the F-OB of the F-runtime group: TIA does not permit their export' }
    if ($m -match 'know-how-protected and cannot be exported') { return 'know-how protected library types: no documents (their project instance is exported as SimaticML, interface only)' }
    $null
}

# A part failed outside one object (its list, its file export): the run stops when that ended TIA, also while its
# process is still up (TIA ends it seconds later), or when TIA does not answer after it. Err: ConvertTo-BridgeError.
function Set-PartStopped($Record, $Err) {
    if ($Err.tiaEnded) { $Record.stopped = $true; $Record.endedBy = $Err.type }
    else { Stop-PartIfTiaGone $Record }
}

# The run stops at a part after which TIA does not answer.
function Stop-PartIfTiaGone($Record) {
    if (-not (Test-TiaAlive)) { $Record.stopped = $true; $Record.endedBy = 'it does not answer any more' }
}

# The refusal of a device with several software items of a scope, or $null. Each item has its device's name (two CPUs of one
# station), so both would write one folder, one over the other; export refuses them too ("Several plc devices"). Whether
# TIA can produce this is not known; 14 real full exports show none. Names differing in case have folders of their own.
function Get-DeviceNameRefusal($Part, [string]$Device) {
    if ($Part.scope -notin 'plc', 'hmi' -or -not $Device) { return $null }
    $same = @(Get-TiaSoftwareList | Where-Object { $_.kind -eq $Part.scope -and [string]::Equals([string]$_.device, $Device, [StringComparison]::Ordinal) })
    if ($same.Count -le 1) { return $null }
    @{ type = 'TiaBridge.DeviceNameCollision'
       message = "Device '$Device' holds $($same.Count) $($Part.scope) software items, and their files would land in one folder, one over the other: nothing of the device is exported and its files stay as they are. The bridge cannot tell them apart by the device's name; report it." }
}

# One kind part: every object, SD refusals again as SimaticML (fallback). Returns the part record. Plan (Get-ExportPlan):
# the objects of a skipping kind come from it, and one it does not export keeps its files, which count as written.
function Invoke-FullExportKindPart($Part, $Root, [string]$Device, $Record, $Plan = $null) {
    $Record.listError = Get-DeviceNameRefusal $Part $Device
    if ($Record.listError) { return }
    $k = Get-ObjectKind $Part.kind
    $dp = if ($Plan -and $Plan.devices.ContainsKey($Device) -and $Plan.devices[$Device].entries.ContainsKey($k.name)) { $Plan.devices[$Device] }
    $entries = @(if ($dp) { $dp.entries[$k.name] } else { Get-KindItems $k $Root })
    if ($Part.filter) { $entries = @($entries | Where-Object { & $Part.filter $_ }) }
    $Record.count = $entries.Count
    # the other kinds of the folder from the plan too: what was listed for it holds for this call
    $collisions = Get-ExportCollisions $k $entries $Root '' $Device $(if ($dp) { $dp.entries } else { @{} })
    $none = New-Object psobject
    # every object into one work folder; its files go in place when the part's objects are done, or it stopped (Invoke-ExportBatch)
    $done = New-Object System.Collections.ArrayList
    $null = Invoke-ExportBatch (Get-KindDir $k '' '' $Device) {
        $n = 0
        foreach ($e in $entries) {
            # the object's time, from here to its progress line (Times.ps1); the moves of its files count in the part's
            $mark = Get-ObjectTimeMark
            $item = $null; $kept = $null
            try {
                $o = if ($dp) { $dp.objects["$($k.name)|$($e.name)"] }
                # an object sharing its file with another is never skipped; it cannot be reached either, as both failed last time
                if ($o -and -not $o.export -and -not $collisions[(Get-ExportBase $k $e '' $Device)]) {
                    $step = [TiaBridgeTimes]::Enter('record')
                    try {
                        $o.recorded = $o.old
                        $Record.skipped++
                        $kept = @((Get-EntryFiles $o.old).Keys)
                        foreach ($f in $kept) { [void]$Record.written.Add((Join-Path $script:Bridge.repo $f)) }
                        if ($k.name -eq 'block' -and (Get-StateValue $o.state 'IsKnowHowProtected') -eq 'True') { [void]$Record.knowHowProtected.Add($e.name) }
                    }
                    finally { [TiaBridgeTimes]::Exit($step) }
                    $n++
                    Write-ObjectProgress $k.name $n $entries.Count @{ name = $e.name; ok = $true } -Part $Part.name -Device $Device -Skipped
                    continue
                }
                if ($o) { $Record.why[$o.export] = 1 + [int]$Record.why[$o.export] }
                $item = Export-KindEntry $k $e $none $Device '' $collisions
                if (-not $item.ok -and -not $item.collision -and $Part.fallback -and (Test-TiaAlive)) {
                    $why = if ($item.error) { $item.error.message } else { @($item.messages.messages | ForEach-Object { $_.description }) -join ' | ' }
                    Enter-ExportRetry
                    try { $retry = Export-KindEntry $k $e (New-Object psobject -Property @{ format = 'xml' }) $Device }
                    finally { Exit-ExportRetry }
                    if ($retry.ok) { $item = $retry; $item.fellBack = "SimaticML: TIA refused the SD export: $why" }
                    # the SD attempt was asked about before the retry: a TIA that ended in the retry is told by the retry's item
                    elseif (Test-ItemEndedTia $retry) { $item = $retry }
                }
                $n++
                Write-ObjectProgress $k.name $n $entries.Count $item -Part $Part.name -Device $Device
                # a call into TIA, so here and not after the batch: TIA may end at a later object
                $khp = $false
                if ($item.ok -and $k.name -eq 'block') {
                    $step = [TiaBridgeTimes]::Enter('tia_properties')
                    try { $khp = [bool]$e.obj.IsKnowHowProtected }
                    finally { [TiaBridgeTimes]::Exit($step) }
                }
                [void]$done.Add(@{ entry = $e; object = $o; item = $item; knowHowProtected = $khp })
                # Set-ItemError asked TIA after the object's last call into TIA (the retry's, when that ended TIA): its answer
                # stands. The part stops where its loop ends, whatever the item is (one TIA does not permit to export too):
                # a part that ended early and is not stopped would be mirrored, with the files of the objects after it removed
                if (Test-ItemEndedTia $item) { $Record.stopped = $true; $Record.endedBy = Get-ItemTiaEndedCause $item; break }
            }
            finally {
                if ($null -ne $kept) { Add-ObjectTime $mark ([string]$e.name) ([string]$e.folder) $kept -Skipped }
                else { Add-ObjectTime $mark ([string]$e.name) ([string]$e.folder) @($item.files) }
            }
        }
    }
    # the items as their files went in place: one whose move failed is failed here, and its files stay as they were
    foreach ($d in $done) {
        $e = $d.entry; $item = $d.item
        if ($d.object) { $d.object.recorded = New-ExportRecordEntry $d.object $item }
        if ($item.ok) {
            $Record.exported++
            foreach ($f in $item.files) { if ($f) { [void]$Record.written.Add((Join-Path $script:Bridge.repo $f)) } }
            foreach ($f in $item.removed) { if ($f) { [void]$Record.removed.Add($f) } }
            if ($item.fellBack) { [void]$Record.fellBack.Add([ordered]@{ name = $item.name; folder = $item.folder; note = $item.fellBack }) }
            if ($d.knowHowProtected) { [void]$Record.knowHowProtected.Add($item.name) }
            continue
        }
        $dir = Get-KindDir $k $e.folder '' $Device
        [void]$Record.kept.Add((Join-Path $dir (ConvertTo-SafeFileName $e.name)))
        if (-not $e.name) { [void]$Record.kept.Add("$dir\") }
        $why = Get-LeftOutReason $item
        if ($why) { [void]$Record.notExported.Add([ordered]@{ name = $item.name; folder = $item.folder; reason = $why; message = $item.error.message }); continue }
        $f = [ordered]@{ name = $item.name; folder = $item.folder }
        if ($item.error) { $f.error = $item.error } elseif ($item.messages) { $f.messages = $item.messages }
        [void]$Record.failed.Add($f)
    }
}

# Copies a file, making its folder.
function Copy-FileWithFolder([string]$From, [string]$To) {
    New-Item -ItemType Directory -Force -Path (Split-Path -Parent $To) | Out-Null
    Copy-Item -LiteralPath $From -Destination $To -Force -ErrorAction Stop
}

# One file part: its folder is written next to the old one and replaces it only when the export did not fail; a
# part with nothing to export (none) removes the old folder. Uncommitted files the new folder does not hold stay, and
# a git repo in the folder stays whole (keptRepos).
function Invoke-FullExportFilePart($Part, $Root, [string]$Device, $Record) {
    $Record.listError = Get-DeviceNameRefusal $Part $Device
    if ($Record.listError) { return }
    $dir = Join-Path $script:Bridge.repo (Get-PartDir $Part $Device)
    $partial = "$dir.partial"
    $step = [TiaBridgeTimes]::Enter('work_folder')
    try {
        if (Test-Path -LiteralPath $partial) { Remove-Item -LiteralPath $partial -Recurse -Force }
        New-Item -ItemType Directory -Force -Path $partial | Out-Null
    }
    finally { [TiaBridgeTimes]::Exit($step) }
    try {
        # the part's own export: its calls into TIA are tia_export_file, the rest (a .dat unpacked, a list written) is file_part
        $step = [TiaBridgeTimes]::Enter('file_part')
        try { $r = & $Part.file $Root $partial }
        catch {
            $err = ConvertTo-BridgeError $_
            [void]$Record.failed.Add([ordered]@{ name = $Part.name; error = $err })
            Set-PartStopped $Record $err
            foreach ($d in (Get-NestedRepos $dir)) { [void]$Record.keptRepos.Add((Get-RepoRelative $d)) }
            return
        }
        finally { [TiaBridgeTimes]::Exit($step) }
        # the files put in place: the folder's listing, git, the compare, the moves; the removals are remove
        $step = [TiaBridgeTimes]::Enter('move')
        try { Move-FilePartIntoPlace $r $dir $partial $Record }
        finally { [TiaBridgeTimes]::Exit($step) }
    }
    finally {
        $step = [TiaBridgeTimes]::Enter('work_folder')
        Remove-Item -LiteralPath $partial -Recurse -Force -ErrorAction SilentlyContinue
        [TiaBridgeTimes]::Exit($step)
    }
}

# The files a file part exported into Partial put in place of Dir, with the old ones it no longer holds removed unless
# git has no commit of them; a git repo in Dir stays whole. R: what the part's export returned.
function Move-FilePartIntoPlace($R, [string]$Dir, [string]$Partial, $Record) {
    if ($r.notes) { $Record.notes = @($r.notes) }
    # Asked after the export, as Split-MirrorRemovals asks git: a repo made during a long export counts.
    $repos = Get-NestedRepos $dir
    foreach ($d in $repos) { [void]$Record.keptRepos.Add((Get-RepoRelative $d)) }
    $old = @(Get-ChildItem -LiteralPath $dir -File -Recurse -Force -ErrorAction SilentlyContinue | Where-Object { -not (Test-InNestedRepo $_.FullName $repos) } | ForEach-Object { $_.FullName.Substring($dir.Length) })
    # none: nothing to export, whatever the export left in the partial folder
    $new = @(if (-not $r.none) { Get-ChildItem -LiteralPath $partial -File -Recurse -Force | ForEach-Object { $_.FullName.Substring($partial.Length) } })
    $Record.count = $(if ($null -ne $r.objects) { [int]$r.objects } else { $new.Count })
    $s = Split-MirrorRemovals @($old | Where-Object { $new -notcontains $_ } | ForEach-Object { "$dir$_" })
    if ($s.error) { $Record.gitError = $s.error }
    if ($new.Count) {
        if ($repos.Count) {
            # No replacement of the folder: a repo stays where it is, the new files go in around it; one that differs
            # only in the export time is the old file again (Restore-UnchangedExports, as Move-ExportIntoPlace does).
            Restore-UnchangedExports $partial $dir
            foreach ($f in $new) { Copy-FileWithFolder "$partial$f" "$dir$f" }
            Remove-PartFiles $s.remove
        } else {
            foreach ($f in $s.keep) { Copy-FileWithFolder $f "$partial$($f.Substring($dir.Length))" }
            Move-ExportIntoPlace $partial $dir
        }
        $Record.exported = $Record.count
        foreach ($f in $new) { [void]$Record.written.Add("$dir$f") }
    } else {
        $Record.none = $true
        if ($s.keep.Count -or $repos.Count) { Remove-PartFiles $s.remove }
        elseif (Test-Path -LiteralPath $dir) { Remove-PartFiles @($dir) }
    }
    foreach ($f in $s.remove) { [void]$Record.removed.Add((Get-RepoRelative $f)) }
    foreach ($f in $s.keep) { [void]$Record.keptUncommitted.Add((Get-RepoRelative $f)) }
}

# Removes files, or a folder with what it holds; the first that fails throws.
function Remove-PartFiles([string[]]$Paths) {
    $step = [TiaBridgeTimes]::Enter('remove')
    try { foreach ($p in $Paths) { if ($p) { Remove-Item -LiteralPath $p -Recurse -Force -ErrorAction Stop } } }
    finally { [TiaBridgeTimes]::Exit($step) }
}

# Holds nothing that can fail: a part's failure goes into its record, and the record into the result. The caller sets
# dir inside the part's try.
function New-PartRecord($Part, [string]$Device) {
    [ordered]@{ part = $Part.name; device = $Device; dir = $null; count = 0; exported = 0; skipped = 0; why = [ordered]@{}; ms = 0
                failed = (New-Object System.Collections.ArrayList); fellBack = (New-Object System.Collections.ArrayList)
                knowHowProtected = (New-Object System.Collections.ArrayList); notExported = (New-Object System.Collections.ArrayList)
                removed = (New-Object System.Collections.ArrayList); keptUncommitted = (New-Object System.Collections.ArrayList)
                keptRepos = (New-Object System.Collections.ArrayList)
                written = (New-Object System.Collections.ArrayList); kept = (New-Object System.Collections.ArrayList) }
}

# One line per part for the response: "<part>[@<device>]: <exported>/<count>, <s> s[, <failed> failed][, ...]".
function Format-PartLine($R) {
    $s = "$($R.part)$(if ($R.device) { "@$($R.device)" }): "
    if ($R.leftOut) { return "$s$($R.count) not exportable" }
    if ($R.none) { return "${s}none" }
    $s += "$($R.exported)/$($R.count), $([Math]::Round($R.ms / 1000.0, 1)) s"
    if ($R.skipped) { $s += ", $($R.skipped) skipped" }
    if ($R.failed.Count) { $s += ", $($R.failed.Count) failed" }
    if ($R.notExported.Count) { $s += ", $($R.notExported.Count) not exportable" }
    if ($R.fellBack.Count) { $s += ", $($R.fellBack.Count) as SimaticML" }
    if ($R.knowHowProtected.Count) { $s += ", $($R.knowHowProtected.Count) know-how protected" }
    if ($R.listError) { $s += $(if ($R.listError.type -eq 'TiaBridge.DeviceNameCollision') { ', device refused' } else { ', not listed' }) }
    $s
}

# The run with its times (Times.ps1) in result.times, which the bridge writes into the log only (Bridge.ps1).
function Invoke-FullExportTool($a) {
    Start-ExportTimes
    $script:ExportWindow = $null   # no window of an earlier call
    try {
        # TIA's window, minimized after the plan when the run has many .s7dcl exports (Enter-ExportWindow), is put back here
        try { $r = Invoke-FullExportRun $a }
        finally { $window = Exit-ExportWindow }
        if ($r -is [System.Collections.IDictionary] -and -not $r.refused) {
            if ($window) { $r.window = $window }
            $r.times = Stop-ExportTimes
        }
        $r
    }
    finally { Stop-ExportTimesClock }
}

# How many objects the run exports as .s7dcl, for TIA's window (Enter-ExportWindow): the blocks, DBs and data types the plan
# exports in the selected parts; 0 when no part selected exports .s7dcl, or only those of PLCs and the project has none; -1
# when that cannot be told before (no plan, or library types, which no plan lists, alone). Those TIA refuses as .s7dcl and
# exports as SimaticML count too.
function Get-S7dclExportCount($Plan, [object[]]$Selected, [int]$PlcCount) {
    $kinds = @($Selected | Where-Object { $script:ExportWindowKinds -contains $_.kind } | ForEach-Object { $_.kind })
    if (-not $kinds.Count) { return 0 }
    $planned = @($kinds | Where-Object { $_ -ne 'library_type' })
    if (-not $planned.Count) { return -1 }
    if (-not $PlcCount) { return 0 }
    if (-not $Plan) { return -1 }
    $n = 0
    foreach ($d in $Plan.devices.Values) { foreach ($o in $d.objects.Values) { if ($o.export -and $planned -contains $o.kind) { $n++ } } }
    $n
}

function Invoke-FullExportRun($a) {
    $null = Get-BridgeSession
    $want = @($a.parts | Where-Object { $_ })
    $unknown = @($want | Where-Object { -not (Get-FullExportPart $_) })
    if ($unknown.Count) { return New-Refusal "Unknown part(s): $($unknown -join ', '). Parts: $(@($script:FullExportParts | ForEach-Object { $_.name }) -join ', ')." }
    $selected = @($script:FullExportParts | Where-Object { -not $want.Count -or $want -contains $_.name })
    $step = [TiaBridgeTimes]::Enter('tia_list')
    try {
        $software = @(Get-TiaSoftwareList)
        $project = Get-TiaProject
    }
    finally { [TiaBridgeTimes]::Exit($step) }
    $started = [System.Diagnostics.Stopwatch]::StartNew()
    $script:UnchangedExports.Clear()
    $full = Get-OptionalBool $a 'full' $false

    # what TIA says of the skipping kinds, read before any export; no plan: every object is exported, as before
    $plan = $null; $planNote = $null
    $planWatch = [System.Diagnostics.Stopwatch]::StartNew()
    if (@($selected | Where-Object { $script:SkipKinds -contains $_.kind }).Count -and @($software | Where-Object { $_.kind -eq 'plc' }).Count) {
        if ($script:Bridge.background -and $script:Bridge.background.plain) { $planNote = 'a plain export folder keeps no record' }
        else {
            Enter-PartTimes 'plan'
            try { $plan = Get-ExportPlan $software $project $full }
            catch { $planNote = "what TIA says of the objects did not read: $((ConvertTo-BridgeError $_).message)" }
            finally { Exit-PartTimes -Plan }
        }
    }
    $planMs = [int]$planWatch.ElapsedMilliseconds
    $plcCount = @($software | Where-Object { $_.kind -eq 'plc' }).Count
    Enter-ExportWindow (Get-S7dclExportCount $plan $selected $plcCount)

    # (part, device) pairs of every part, selected or not: a folder is mirrored only when every part that writes it ran
    $jobs = @(foreach ($p in $script:FullExportParts) {
        $devices = switch ($p.scope) { { $_ -in 'plc', 'hmi' } { @($software | Where-Object { $_.kind -eq $p.scope }) } default { @(@{ device = ''; software = $null }) } }
        foreach ($d in $devices) { @{ part = $p; device = [string]$d.device; software = $d.software; run = ($selected -contains $p) } }
    })
    $records = New-Object System.Collections.ArrayList
    $stopped = $false
    foreach ($j in @($jobs | Where-Object { $_.run })) {
        $p = $j.part
        $rec = New-PartRecord $p $j.device
        [void]$records.Add($rec)
        $sw = [System.Diagnostics.Stopwatch]::StartNew()
        Enter-PartTimes $p.name $j.device
        $step = [TiaBridgeTimes]::Enter('progress')
        Write-BridgeLog "full_export $($p.name)$(if ($j.device) { " @ $($j.device)" }) ..."
        $pp = [ordered]@{ event = 'part'; part = $p.name }
        if ($j.device) { $pp.device = $j.device }
        $pp.state = 'start'
        Write-BridgeProgress $pp
        [TiaBridgeTimes]::Exit($step)
        try {
            $rec.dir = Get-PartDir $p $j.device
            $root = switch ($p.scope) { { $_ -in 'plc', 'hmi' } { $j.software } 'project' { $project } 'library' { $project.ProjectLibrary } }
            if ($p.counter) {
                $step = [TiaBridgeTimes]::Enter('tia_list')
                try { $rec.count = @(& $p.counter $root).Count }
                finally { [TiaBridgeTimes]::Exit($step) }
                if ($rec.count) { $rec.leftOut = $p.leftOut } else { $rec.none = $true }
            }
            elseif ($p.kind) { Invoke-FullExportKindPart $p $root $j.device $rec $plan }
            else { Invoke-FullExportFilePart $p $root $j.device $rec }
            # TIA is asked once a part, after it: the paths of its objects do not ask (Test-TiaAliveInCall), and a skipped
            # object makes no call into TIA
            if (-not $rec.stopped -and -not $rec.listError) { Stop-PartIfTiaGone $rec }
        }
        catch {
            # the part's folder or objects could not be told: nothing of the part is mirrored
            $rec.listError = ConvertTo-BridgeError $_
            Set-PartStopped $rec $rec.listError
        }
        $rec.ms = [int]$sw.ElapsedMilliseconds
        Exit-PartTimes $rec.ms
        Update-ExportWindowSeen
        $step = [TiaBridgeTimes]::Enter('progress')
        Write-BridgeLog "full_export $(Format-PartLine $rec)"
        $pp.state = $(if ($rec.listError -or $rec.stopped) { 'failed' } else { 'done' })
        $pp.exported = [int]$rec.exported; $pp.count = [int]$rec.count; $pp.failed = $rec.failed.Count; $pp.ms = $rec.ms
        Write-BridgeProgress $pp
        [TiaBridgeTimes]::Exit($step)
        if ($rec.stopped) { $stopped = $true; break }
    }

    # mirror: per folder of the kind parts, once every part writing it ran and listed its objects
    $removed = New-Object System.Collections.ArrayList; $removeErrors = @()
    $keptUncommitted = New-Object System.Collections.ArrayList; $keptRepos = New-Object System.Collections.ArrayList; $gitError = $null
    $step = [TiaBridgeTimes]::Enter('mirror')
    if (-not $stopped) {
        # A failure here costs the mirror, never the summary. No folder can be told for one part: nothing is mirrored,
        # the folder it shares with another part may hold its files.
        try {
            $byDir = @{}
            foreach ($j in @($jobs | Where-Object { $_.part.kind })) {
                $key = (Get-PartDir $j.part $j.device).ToLowerInvariant()
                if (-not $byDir[$key]) { $byDir[$key] = New-Object System.Collections.ArrayList }
                [void]$byDir[$key].Add($j)
            }
        }
        catch {
            $byDir = @{}
            $removeErrors += "The mirror did not run, nothing was removed: $($_.Exception.Message)"
        }
        foreach ($key in $byDir.Keys) {
            $recs = @(foreach ($j in $byDir[$key]) { $records | Where-Object { $_.part -eq $j.part.name -and $_.device -eq $j.device } | Select-Object -First 1 })
            if (@($byDir[$key]).Count -ne $recs.Count -or @($recs | Where-Object { $_.listError }).Count) { continue }
            try {
                $dir = Join-Path $script:Bridge.repo $recs[0].dir
                $files = @(Get-MirrorRemovals $dir @($recs | ForEach-Object { $_.written }) @($recs | ForEach-Object { $_.kept }))
                $s = Split-MirrorRemovals $files
                if ($s.error) { $gitError = $s.error }
                foreach ($f in $s.keep) { [void]$keptUncommitted.Add((Get-RepoRelative $f)) }
                foreach ($d in (Get-NestedRepos $dir)) { [void]$keptRepos.Add((Get-RepoRelative $d)) }
                $m = Remove-MirrorFiles $dir $s.remove
                foreach ($f in $m.removed) { [void]$removed.Add((Get-RepoRelative $f)) }
                $removeErrors += $m.errors
            }
            catch { $removeErrors += "$($recs[0].dir): $($_.Exception.Message)" }
        }
    }
    [TiaBridgeTimes]::Exit($step)
    # the result: its lines, the record, the count of unchanged files
    $step = [TiaBridgeTimes]::Enter('summary')
    foreach ($r in $records) {
        foreach ($f in $r.removed) { [void]$removed.Add($f) }
        foreach ($f in $r.keptUncommitted) { [void]$keptUncommitted.Add($f) }
        foreach ($d in $r.keptRepos) { [void]$keptRepos.Add($d) }
        if ($r.gitError) { $gitError = $r.gitError }
    }

    $refusedDevices = @{}   # one line per device, not one per part of it
    $failed = @(foreach ($r in $records) {
        foreach ($f in $r.failed) {
            $line = "$($r.part)$(if ($r.device) { "@$($r.device)" }): $(if ($f.folder) { "$($f.folder)/" })$($f.name)"
            if ($f.error) { "$line`: $($f.error.type): $(Limit-Text $f.error.message 300)" } else { "$line`: export state $($f.messages.state)" }
        }
        if ($r.listError.type -eq 'TiaBridge.DeviceNameCollision') {
            if (-not $refusedDevices[$r.device]) { $refusedDevices[$r.device] = $true; "$($r.device): $($r.listError.type): $($r.listError.message)" }
        }
        elseif ($r.listError) { "$($r.part)$(if ($r.device) { "@$($r.device)" }): not listed: $($r.listError.type): $(Limit-Text $r.listError.message 300)" }
    })
    $leftOut = @(foreach ($r in $records | Where-Object { $_.leftOut }) { "$($r.count) $($r.leftOut)$(if ($r.device) { " ($($r.device))" })" })
    $khp = @($records | ForEach-Object { $_.knowHowProtected } | Where-Object { $_ })
    if ($khp.Count) { $leftOut += "$($khp.Count) know-how protected block(s), interface only: $($khp -join ', ')" }
    foreach ($g in @($records | ForEach-Object { $_.notExported } | Where-Object { $_ }) | Group-Object { $_.reason }) {
        $names = @($g.Group | ForEach-Object { $_.name })
        $leftOut += "$($g.Count) $($g.Name): $(@($names | Select-Object -First 10) -join ', ')$(if ($names.Count -gt 10) { ', ...' })"
    }
    $details = @(foreach ($r in $records) {
        $d = [ordered]@{}
        foreach ($k in $r.Keys) { if ($k -notin 'written', 'kept') { $d[$k] = $r[$k] } }
        $d
    })
    $exported = 0; $skipped = 0; foreach ($r in $records) { $exported += [int]$r.exported; $skipped += [int]$r.skipped }
    $saveWatch = [System.Diagnostics.Stopwatch]::StartNew()
    $recordError = if ($plan -and -not $stopped) { Save-ExportRecord $plan $records }
    $saveMs = [int]$saveWatch.ElapsedMilliseconds
    $countStep = [TiaBridgeTimes]::Enter('unchanged_count')
    $unchanged = Get-UnchangedExportCount @($records | ForEach-Object { $_.written })
    [TiaBridgeTimes]::Exit($countStep)
    $result = [ordered]@{
        ok = (-not $failed.Count -and -not $stopped -and -not $removeErrors.Count -and -not $gitError)
        exported = $exported; skipped = $skipped; unchanged = $unchanged; failedCount = $failed.Count; removedCount = $removed.Count; keptCount = $keptUncommitted.Count; totalMs = [int]$started.ElapsedMilliseconds
        parts = @($records | ForEach-Object { Format-PartLine $_ })
        failed = $failed; leftOut = $leftOut; limits = $script:FullExportLimits
        removed = @($removed); keptUncommitted = @($keptUncommitted); keptRepos = @($keptRepos | Select-Object -Unique); details = $details
        next = 'Commit the project repo (git add -A: the removed files go with it). Read failed and leftOut; the log holds every part in details.'
    }
    if ($keptUncommitted.Count) {
        $result.next = 'keptUncommitted: files of objects TIA does not have, not committed, so not removed. Decide on each before committing: import or commit it, or delete it (git add -A would commit them). ' + $result.next
    }
    if ($keptRepos.Count) {
        $result.next = 'keptRepos: git repos in or around the export folders: nothing of them was removed. A repo that holds an export folder did get the new files of the export. git add -A would stage a repo with a .git as one pointer, not its files, and a bare repo as files of the project repo, and a repo with no commit stops it with an error, nothing staged: move each out, or ignore it, before committing. ' + $result.next
    }
    if ($gitError) {
        $result.gitError = "git could not say what is committed, so nothing was removed from the folders it concerns (keptUncommitted lists the files): $gitError"
        $result.next = 'Fix what gitError names and run full_export again, then commit. Read failed and leftOut; the log holds every part in details.'
    }
    if ($script:Bridge.background -and $script:Bridge.background.plain) { $result.next = 'Plain export folder: nothing to commit. Read failed and leftOut; the log holds every part in details.' }
    if ($removeErrors.Count) { $result.removeErrors = $removeErrors }
    # why objects of the skipping kinds were exported whole: everything, or every one of a PLC
    if ($planNote) { $result.exportedAll = $planNote }
    elseif ($plan -and $plan.all) { $result.exportedAll = $plan.all }
    elseif ($plan) {
        $byPlc = @(foreach ($dev in @($plan.devices.Keys | Sort-Object)) { if ($plan.devices[$dev].all) { "$dev`: $($plan.devices[$dev].all)" } })
        if ($byPlc.Count) { $result.exportedAllOf = $byPlc }
    }
    if ($recordError) { $result.recordError = $recordError }
    # what the skipping costs: the read of TIA's values and the record's files before the export, the record's write after
    if ($plan) { $result.planMs = $planMs; $result.saveMs = $saveMs }
    $folderNotes = @(foreach ($s in $software) {
        Get-SharedFolderNote 'Device' ([string]$s.device) @($software | Where-Object { $_.kind -eq $s.kind } | ForEach-Object { [string]$_.device })
    })
    $folderNotes = @($folderNotes | Where-Object { $_ })
    if ($folderNotes.Count) { $result.deviceFolders = $folderNotes }
    if ($stopped) {
        $at = @($records | Where-Object { $_.stopped })[-1]
        $result.ok = $false
        $result.tiaEnded = $true
        $result.stopped = "The export stopped at part $($at.part), and no folder was mirrored; what was exported before stays in the repo."
        $result.note = "TIA Portal ended at part $($at.part). $(Set-TiaEnded $at.endedBy)"
        $result.next = 'Do not commit a partial export as the whole project. ' + $(if ($script:Bridge.background) { 'Open the session again, then run full_export again.' } else { 'Connect again, then run full_export again.' })
    }
    [TiaBridgeTimes]::Exit($step)
    $result
}

function Register-FullExportTool {
    Register-McpTool -Name 'full_export' -Handler { param($a) Invoke-WithNotificationGuard { Invoke-FullExportTool $a } } -Description (
        'Export the whole project into its repo in one call: every PLC (blocks, DBs, UDTs as .s7dcl with SimaticML where TIA refuses SD, OBs and ' +
        'know-how protected blocks as SimaticML; tag tables, system blocks, technology objects, watch and force tables, alarm texts and ProDiag supervisions as .xlsx), ' +
        'every HMI device (screens, templates, pop-ups, slide-ins, global elements, tags, text and graphic lists, VB scripts, cycles, connections), ' +
        'project texts (.xlsx), alarm classes, supervision and diagnostics settings, graphics, project library types, faceplate ' +
        'metadata and a master copy index. With several PLC or HMI devices each gets plc\<device>\ or hmi\<device>\. Mirrors the project: files of ' +
        'objects no longer in it are removed from the folders the export writes (removed), except files not committed (untracked, ignored or changed), which stay and ' +
        'are listed (keptUncommitted: import, commit or delete each before committing); a git repo inside such a folder stays whole and is listed (keptRepos), an object whose own export folder holds one is refused and in failed, and a repo around such a folder loses nothing, gets the new files and is listed too; the export of an object still replaces uncommitted edits of its own files, as export does. ' +
        'A file that differs from the one in the repo only in what TIA writes anew per export (the export time; in an .xlsx also its relationship Ids) stays as it is: a full_export with no change in TIA changes no file; unchanged counts the files left so. ' +
        'Blocks, DBs, data types and PLC tag tables TIA has not changed since the last full_export are not exported and keep their files (skipped counts them). ' +
        'This rests on the dates and other values TIA keeps of each object, compared for unequal (every edit of a block, DB or data type tried on V20 moved a date of it; a move to another folder moved none, so the folder is compared), on a fresh export of each tag table compared with its file (a tag renamed moves no date of its table), and on the files the last export left (.tiabridge-export.json, ignored by git); a comment edited in TIA''s editors and a move were tried by a person in TIA, not by an agent; block properties edited in TIA dialogs were not tried, those Openness reads are compared as values. ' +
        'It exports an object when a value differs, it moved, it is not consistent, its last export failed, a file of it was edited, removed or added beside it in the repo, or it is an instance DB of an exported FB; a block, DB or data type written as SimaticML also when another block or DB changed; every object of a PLC when a data type changed, a tag table exports differently or an object was added, deleted or renamed (exportedAllOf); ' +
        'everything when there is no usable record, or the project, TIA version, project languages, PLC devices or the bridge differ from it (exportedAll); details counts per part why objects were exported. HMI, library and the other parts export every time. full: true exports everything. ' +
        'hmi\generated, gen, library\changes, changes, logs, archives and standards are never touched. Read only: works under connect and in a background session. Long: about minutes per thousand objects; ' +
        'parts runs a subset (a folder is then mirrored only when every part writing it ran). Result: one line per part, failed items, ' +
        'leftOut (what Openness cannot export, with the reason); the log has details, and times: where the time went, per part and step (tia_* are the calls into Openness), with the slowest objects of each part. Objects whose names give one file name are in failed: neither is exported, the files there stay and are not mirrored away; rename one in TIA. ' +
        'Devices whose names give one folder each get a folder with a mark (deviceFolders); a device holding two software items of one kind is refused and in failed: nothing of it is exported, its files stay. In a TIA with a window, boxes of the call with the icon Success or Information are acknowledged; every other box and every question stays with the user, who may have to close it; all notifications are listed with their icon (prompts). ' +
        "In a TIA with a window, a run with $script:ExportWindowFrom or more blocks, DBs and data types to export as .s7dcl minimizes TIA's main window once it has read what to export, and restores it after: on one PC an .s7dcl export took about seven times as long with the window showing. " +
        'Before the call, tell the user: "Full export minimizes TIA for performance." Pass on window in the result. Commit the repo afterwards.') -Schema @{
        type = 'object'
        properties = @{ parts = @{ type = 'array'; items = @{ type = 'string'; enum = @($script:FullExportParts | ForEach-Object { $_.name }) }
                                   description = 'only these parts; default all' }
                        full = @{ type = 'boolean'; description = 'export every object, also those TIA says it has not changed since the last export; default false' } } }
}
