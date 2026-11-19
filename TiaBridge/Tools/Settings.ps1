# Tools\Settings.ps1 - the import kinds of four settings parts full_export writes (Tools\FullExport.ps1 exports them):
# project texts, alarm classes, system diagnostics settings and a PLC's ProDiag supervisions. Loaded after FullExport.ps1,
# whose export functions they call.

# These four parts go back through import, a kind each, over the project's own: each is one object that is always
# there, so a file of another name is refused before TIA sees it. Project texts and alarm classes TIA imports only outside
# a transaction (noUndo); system diagnostics settings and supervisions inside one. Tried on a real TIA V20: an unchanged
# round trip of each, and an edit of each but the supervisions (docs\agent\openness-v20.md, Settings parts through import). Supervision
# settings and PLC alarm texts are no kind: their import was not tried.

# The XML of a settings .dat: its one entry, as text, or @{ refused }.
function Read-SettingsDatXml([string]$Path) {
    Add-Type -AssemblyName System.IO.Compression.FileSystem
    try { $zip = [System.IO.Compression.ZipFile]::OpenRead($Path) }
    catch { return @{ refused = "$Path cannot be read as the zip TIA exports: $($_.Exception.Message)" } }
    try {
        $entries = @($zip.Entries)
        if ($entries.Count -ne 1) { return @{ refused = "$Path holds $($entries.Count) files; TIA exports one XML file in it." } }
        $reader = New-Object System.IO.StreamReader ($entries[0].Open())
        try { @{ xml = $reader.ReadToEnd() } } finally { $reader.Dispose() }
    }
    finally { $zip.Dispose() }
}

# Precheck of a settings part: the project's own (Name, as full_export writes it), and for a .dat kind (Root: the root
# element of its XML) an XML of that root, from the .xml, or from the .dat when the .xml beside it says the same.
function Test-SettingsPartFile($File, [object[]]$Entries, [string]$What, [string]$Root = '') {
    $own = @($Entries | ForEach-Object { [string]$_.name })
    if ($own -notcontains [string]$File.objectName) {
        $names = if ($own.Count) { ($own | ForEach-Object { "'$_'" }) -join ', ' } else { 'none' }
        return @{ ok = $false; refused = "The project has its own $What, which an import replaces, and no other: '$($File.objectName)' is not it (the project's: $names, as full_export names the files)." }
    }
    if (-not $Root) { return $null }
    $isDat = [System.IO.Path]::GetExtension($File.file) -eq '.dat'
    $xmlPath = [System.IO.Path]::ChangeExtension($File.file, '.xml')
    if ($isDat) {
        $dat = Read-SettingsDatXml $File.file
        if ($dat.refused) { return @{ ok = $false; refused = $dat.refused } }
        $text = $dat.xml
        if ((Test-Path -LiteralPath $xmlPath) -and ([System.IO.File]::ReadAllText($xmlPath) -replace '\r\n', "`n").Trim() -ne ($text -replace '\r\n', "`n").Trim()) {
            return @{ ok = $false; refused = "$xmlPath differs from the XML in $($File.file): an edit is made in the .xml. Import the .xml, which the bridge packs into a .dat as TIA exports it, or export again to drop the edit." }
        }
    }
    else { $text = [System.IO.File]::ReadAllText($File.file) }
    $doc = New-Object System.Xml.XmlDocument
    try { $doc.LoadXml($text) }
    catch { return @{ ok = $false; refused = "$($File.file) is no well-formed XML: $($_.Exception.Message)" } }
    if ($doc.DocumentElement.LocalName -ne $Root) {
        return @{ ok = $false; refused = "$($File.file) holds $($doc.DocumentElement.LocalName), not the $What ($Root), as full_export writes them." }
    }
    $null
}

# One import call into TIA: its result tree, an error state thrown (Assert-ExportResult reads both ways).
function Invoke-SettingsImport([scriptblock]$Import, [string]$What) {
    $tree = Assert-ExportResult (& $Import) "import of $What"
    $r = @{ ok = $true }
    if ($tree) { $r.tia = $tree }
    $r
}

# The import of a .dat kind: the .dat as given, or an .xml packed as TIA exports it (its one entry named as the .dat, UTF-8
# with a byte order mark) into a .dat of a temporary folder, removed after.
function Import-SettingsDat($Service, $File, [string]$What) {
    if ([System.IO.Path]::GetExtension($File.file) -ne '.xml') {
        return Invoke-SettingsImport { $Service.Import([System.IO.FileInfo]::new($File.file)) } $What
    }
    $dir = Join-Path ([System.IO.Path]::GetTempPath()) "TiaBridge-$PID-$([guid]::NewGuid().ToString('N'))"
    $entry = [System.IO.Path]::GetFileNameWithoutExtension($File.file) + '.dat'
    $dat = Join-Path $dir $entry
    [void][System.IO.Directory]::CreateDirectory($dir)
    try {
        Add-Type -AssemblyName System.IO.Compression, System.IO.Compression.FileSystem
        $bytes = (New-Object System.Text.UTF8Encoding $true).GetPreamble() + [System.Text.Encoding]::UTF8.GetBytes([System.IO.File]::ReadAllText($File.file))
        $zip = [System.IO.Compression.ZipFile]::Open($dat, [System.IO.Compression.ZipArchiveMode]::Create)
        try {
            $s = $zip.CreateEntry($entry).Open()
            try { $s.Write($bytes, 0, $bytes.Length) } finally { $s.Dispose() }
        }
        finally { $zip.Dispose() }
        Invoke-SettingsImport { $Service.Import([System.IO.FileInfo]::new($dat)) } $What
    }
    finally { Remove-Item -LiteralPath $dir -Recurse -Force -ErrorAction SilentlyContinue }
}

$script:NotInTransaction = 'TIA refuses it inside one: "The operation is not permitted within a transaction."'

Register-ObjectKind 'project_texts' @{
    scope = 'project'; dir = 'project\texts'; defaultOverride = $true; usedBy = @('plc', 'hmi'); extensions = @('.xlsx')
    noUndo = $script:NotInTransaction
    compileWhy = 'a block title edited through them turned the block not consistent'
    noDelete = 'Project texts are the texts of the project''s objects, not objects of their own.'
    description = 'project texts: project-texts_<reference>_<target>.xlsx per active language, as full_export writes them in project\texts, over the project''s own; outside a transaction, so only with no_undo; not deleted'
    items = { param($p)
        $languages = Get-ProjectTextLanguages $p
        foreach ($t in $languages.targets) { @{ obj = $p; name = (Get-ProjectTextsName $languages.ref $t); folder = '' } } }
    precheck = { param($file, $cache, $entries) Test-SettingsPartFile $file $entries 'project texts, a file per active language besides the reference language' }
    # the second argument is updateSourceLanguage: true takes the reference language's texts of the file too, as both
    # probes did (docs\agent\openness-v20.md). compileWhy: the probe of 2026-11-18 there.
    import = { param($p, $folder, $file, $override) Invoke-SettingsImport { $p.ImportProjectTexts([System.IO.FileInfo]::new($file.file), $true) } 'project texts' }
}

Register-ObjectKind 'alarm_classes' @{
    scope = 'project'; dir = 'project\alarmclasses'; defaultOverride = $true; usedBy = @('plc', 'hmi'); extensions = @('.dat', '.xml')
    noUndo = $script:NotInTransaction
    compileWhy = 'whether these need one was not tried'
    noDelete = 'The alarm classes are one settings file of the project; change them by importing it.'
    description = 'alarm classes: alarm-classes.dat, or the alarm-classes.xml full_export writes beside it (packed into a .dat for TIA), in project\alarmclasses; outside a transaction, so only with no_undo; not deleted'
    items = { param($p) @{ obj = $p; name = 'alarm-classes'; folder = '' } }
    precheck = { param($file, $cache, $entries) Test-SettingsPartFile $file $entries 'alarm classes' 'AlarmServiceGlobalSettingsData' }
    import = { param($p, $folder, $file, $override) Import-SettingsDat (Get-RequiredService $p ([Siemens.Engineering.SW.Alarm.AlarmClassDataProvider])) $file 'alarm classes' }
}

Register-ObjectKind 'diagnostics_settings' @{
    scope = 'project'; dir = 'project\diagnostics'; defaultOverride = $true; usedBy = @('plc'); extensions = @('.dat', '.xml')
    compileWhy = 'whether these need one was not tried'
    noDelete = 'The system diagnostics settings are one settings file of the project; change them by importing it.'
    description = 'system diagnostics settings: systemdiagnostics-settings.dat, or the .xml full_export writes beside it (packed into a .dat for TIA), in project\diagnostics; not deleted'
    items = { param($p) @{ obj = $p; name = 'systemdiagnostics-settings'; folder = '' } }
    precheck = { param($file, $cache, $entries) Test-SettingsPartFile $file $entries 'system diagnostics settings' 'SysDiagGlobalSettingsData' }
    import = { param($p, $folder, $file, $override) Import-SettingsDat (Get-RequiredService $p ([Siemens.Engineering.HW.Systemdiagnostics.Settings.SystemdiagnosticsSettingsDataProvider])) $file 'system diagnostics settings' }
}

# What importing a supervisions sheet did to a project without ProDiag settings (docs\agent\openness-v20.md): said in the
# import text before, and in the result when an import initialised them (Test-ProDiagSettings before and after).
$script:SupervisionsFirstImport = 'Importing a supervisions sheet into a project without ProDiag settings initialises them (seen with a sheet holding headers only), and the project texts gain rows of ProDiag categories: 230 on the project tried. full_export''s part supervision_settings reads none on such a project. Tell the user before such an import. An import rolled back took both back when tried.'

# Whether the project has ProDiag settings: 'yes' when their export works, 'no' when it answers "Global settings are not
# initialized" (Export-SupervisionSettings), 'unread' when it fails otherwise; into a temporary folder removed after.
function Test-ProDiagSettings {
    $dir = Join-Path ([System.IO.Path]::GetTempPath()) "TiaBridge-$PID-$([guid]::NewGuid().ToString('N'))"
    [void][System.IO.Directory]::CreateDirectory($dir)
    try { if ((Export-SupervisionSettings (Get-TiaProject) $dir).none) { 'no' } else { 'yes' } }
    catch {
        if (Test-TiaEndedError $_) { throw }
        Write-BridgeLog "ProDiag settings not read: $($_.Exception.Message)"
        'unread'
    }
    finally { Remove-Item -LiteralPath $dir -Recurse -Force -ErrorAction SilentlyContinue }
}

Register-ObjectKind 'supervisions' @{
    scope = 'plc'; dir = 'plc\supervisions'; defaultOverride = $true; extensions = @('.xlsx')
    compileWhy = 'whether these need one was not tried'
    noDelete = 'The ProDiag supervisions of a PLC are one sheet; change them by importing it.'
    description = 'ProDiag supervisions of a PLC: supervisions.xlsx, as full_export writes it in plc\supervisions, over the PLC''s own; not deleted'
    items = { param($plc) @{ obj = $plc; name = 'supervisions'; folder = '' } }
    # read once per call, before TIA is asked: the result names the side effect only when this import caused it
    precheck = { param($file, $cache, $entries)
        $why = Test-SettingsPartFile $file $entries 'ProDiag supervisions'
        if ($why) { return $why }
        if (-not $cache.ContainsKey('proDiag')) { $cache.proDiag = Test-ProDiagSettings }
        if ($cache.proDiag -ne 'yes') { @{ proDiagSettingsBefore = $cache.proDiag } } }
    import = { param($plc, $folder, $file, $override)
        $svc = Get-RequiredService $plc ([Siemens.Engineering.SW.Supervision.SupervisionProvider])
        $opt = if ($override) { [Siemens.Engineering.ImportOptions]::Override } else { [Siemens.Engineering.ImportOptions]::None }
        Invoke-SettingsImport { $svc.ImportSupervisionsFromXlsx([System.IO.FileInfo]::new($file.file), $opt) } 'ProDiag supervisions' }
    afterImport = { param($result, $items)
        $before = @($items | Where-Object { $_.ok -and $_.proDiagSettingsBefore } | ForEach-Object { $_.proDiagSettingsBefore })
        if (-not $before.Count) { return }
        $after = Test-ProDiagSettings
        if ($before -contains 'no' -and $after -eq 'yes') {
            $result.prodiag = 'This import initialised the project''s ProDiag settings, which it had none of before. On the project tried that also added rows of ProDiag categories to the project texts (230). Tell the user.'
        }
        elseif ($before -contains 'unread' -or $after -eq 'unread') {
            $result.prodiag = "Whether this import initialised the project's ProDiag settings could not be read. $script:SupervisionsFirstImport"
        } }
}
