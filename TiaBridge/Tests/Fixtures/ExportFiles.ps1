# Files as TIA writes them on each export (Repo.ps1, Test-OnlyExportTimeDiffers): the export time, the zip entry times and
# the relationship Ids of an .xlsx drawn anew per call, the content as given. Shapes as on a test project, 2026-11-05.
Add-Type -AssemblyName System.IO.Compression, System.IO.Compression.FileSystem

function New-ExportTime { [DateTime]::UtcNow.AddSeconds((Get-Random -Maximum 100000)).ToString('yyyy-MM-ddTHH:mm:ss.fffffffZ') }
function New-RelationshipId { 'R' + [guid]::NewGuid().ToString('N').Substring(0, 16) }

function Write-TestText([string]$Path, [string]$Text, [switch]$Bom) {
    New-Item -ItemType Directory -Force -Path (Split-Path -Parent $Path) | Out-Null
    [System.IO.File]::WriteAllText($Path, $Text, (New-Object System.Text.UTF8Encoding ([bool]$Bom)))
}

# SimaticML of an object, BOM and CRLF as TIA writes them; Body: what follows DocumentInfo.
function Get-SimaticMlText([string]$Body = '<SW.Blocks.OB ID="0" />', [string]$Created = (New-ExportTime)) {
    "<?xml version=`"1.0`" encoding=`"utf-8`"?>`r`n<Document>`r`n  <Engineering version=`"V20`" />`r`n  <DocumentInfo>`r`n    <Created>$Created</Created>`r`n" +
    "    <ExportSetting>WithDefaults</ExportSetting>`r`n  </DocumentInfo>`r`n  $Body`r`n</Document>"
}

# The XML of the alarm classes, as Export-SettingsDat writes it beside the .dat and as the .dat holds it.
function Get-SettingsText([string]$Class = 'Acknowledgement', [string]$Created = ((New-ExportTime) -replace '\.\d+Z$', 'Z')) {
    "<?xml version=`"1.0`" encoding=`"utf-8`"?>`r`n<AlarmServiceGlobalSettingsData SchemaVersion=`"2.0`" ProjectName=`"P`" CreationDate=`"$Created`">`r`n" +
    "  <AlarmClass Name=`"$Class`" />`r`n</AlarmServiceGlobalSettingsData>"
}

# A zip of Parts (name -> text), each entry with the time When.
function Write-TestZip([string]$Path, $Parts, [DateTime]$When = [DateTime]::Now.AddSeconds(-(Get-Random -Maximum 100000))) {
    New-Item -ItemType Directory -Force -Path (Split-Path -Parent $Path) | Out-Null
    if (Test-Path -LiteralPath $Path) { Remove-Item -LiteralPath $Path -Force }
    $z = [System.IO.Compression.ZipFile]::Open($Path, 'Create')
    try {
        foreach ($name in $Parts.Keys) {
            $e = $z.CreateEntry($name)
            $e.LastWriteTime = $When
            $w = New-Object System.IO.StreamWriter ($e.Open()), (New-Object System.Text.UTF8Encoding $true)
            try { $w.Write($Parts[$name]) } finally { $w.Dispose() }
        }
    }
    finally { $z.Dispose() }
}

function Write-SettingsDat([string]$Path, [string]$Class = 'Acknowledgement') {
    Write-TestZip $Path ([ordered]@{ ([System.IO.Path]::GetFileName($Path)) = (Get-SettingsText $Class) })
}

# The parts of an .xlsx as TIA's export writes it: two sheets, Ids drawn anew. Swap: the workbook points each sheet at
# the other's relationship. Cell: what the first sheet holds.
function Get-XlsxParts([string]$Cell = 'a', [switch]$Swap) {
    $doc = New-RelationshipId; $styles = New-RelationshipId; $s1 = New-RelationshipId; $s2 = New-RelationshipId
    $ns = 'xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships"'
    $rel = 'http://schemas.openxmlformats.org/officeDocument/2006/relationships'
    $first, $second = if ($Swap) { $s2, $s1 } else { $s1, $s2 }
    [ordered]@{
        'xl/workbook.xml' = "<?xml version=`"1.0`" encoding=`"utf-8`"?><x:workbook xmlns:x=`"http://schemas.openxmlformats.org/spreadsheetml/2006/main`"><x:sheets>" +
                            "<x:sheet name=`"One`" sheetId=`"1`" r:id=`"$first`" $ns /><x:sheet name=`"Two`" sheetId=`"2`" r:id=`"$second`" $ns /></x:sheets></x:workbook>"
        '_rels/.rels' = "<?xml version=`"1.0`" encoding=`"utf-8`"?><Relationships xmlns=`"http://schemas.openxmlformats.org/package/2006/relationships`">" +
                        "<Relationship Type=`"$rel/officeDocument`" Target=`"/xl/workbook.xml`" Id=`"$doc`" /></Relationships>"
        'xl/_rels/workbook.xml.rels' = "<?xml version=`"1.0`" encoding=`"utf-8`"?><Relationships xmlns=`"http://schemas.openxmlformats.org/package/2006/relationships`">" +
                                       "<Relationship Type=`"$rel/styles`" Target=`"/xl/styles.xml`" Id=`"$styles`" />" +
                                       "<Relationship Type=`"$rel/worksheet`" Target=`"/xl/worksheets/sheet.xml`" Id=`"$s1`" />" +
                                       "<Relationship Type=`"$rel/worksheet`" Target=`"/xl/worksheets/sheet2.xml`" Id=`"$s2`" /></Relationships>"
        'xl/styles.xml' = '<?xml version="1.0" encoding="utf-8"?><x:styleSheet xmlns:x="http://schemas.openxmlformats.org/spreadsheetml/2006/main" />'
        'xl/worksheets/sheet.xml' = "<?xml version=`"1.0`" encoding=`"utf-8`"?><x:worksheet xmlns:x=`"http://schemas.openxmlformats.org/spreadsheetml/2006/main`"><x:c><x:v>$Cell</x:v></x:c></x:worksheet>"
        'xl/worksheets/sheet2.xml' = '<?xml version="1.0" encoding="utf-8"?><x:worksheet xmlns:x="http://schemas.openxmlformats.org/spreadsheetml/2006/main" />'
        '[Content_Types].xml' = '<?xml version="1.0" encoding="utf-8"?><Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types" />'
    }
}

function Write-TestXlsx([string]$Path, [string]$Cell = 'a', [switch]$Swap) { Write-TestZip $Path (Get-XlsxParts $Cell -Swap:$Swap) }
