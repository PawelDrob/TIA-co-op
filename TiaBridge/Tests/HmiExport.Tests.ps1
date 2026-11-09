$here = Split-Path -Parent $MyInvocation.MyCommand.Path
foreach ($f in 'Mcp.ps1', 'Tia.ps1', 'Repo.ps1', 'Rules.ps1', 'Guards.ps1', 'Bridge.ps1', 'Tools\Objects.ps1', 'Tools\Plc.ps1', 'Tools\Hmi.ps1') { . (Join-Path $here "..\$f") }

# Export of HMI screens, templates and pop-ups through the export tool: only the full export (WithDefaults +
# WithReadOnly) into hmi\<kind dir> with the TIA folder tree; options.full changes nothing (decided 2026-10-06).

if (-not ('Siemens.Engineering.ExportOptions' -as [type])) {
    Add-Type -TypeDefinition 'namespace Siemens.Engineering { [System.Flags] public enum ExportOptions { None = 0, WithDefaults = 1, WithReadOnly = 2 } }'
}

function Test-TiaAlive { $true }

# An HMI object whose Export writes which options it got.
function New-FakeHmiObject([string]$Name) {
    $o = [pscustomobject]@{ Name = $Name }
    $o | Add-Member ScriptMethod Export { param($f, $opt) [System.IO.File]::WriteAllText($f.FullName, "$($this.Name) $opt") }
    $o
}

# A screen folder tree: root with one subfolder 'Station' holding 'S1'; templates and pop-ups at the root.
function New-FakeHmi {
    $sub = [pscustomobject]@{ Name = 'Station'; Screens = @(New-FakeHmiObject 'S1'); Folders = @() }
    [pscustomobject]@{
        ScreenFolder = [pscustomobject]@{ Screens = @(); Folders = @($sub) }
        ScreenTemplateFolder = [pscustomobject]@{ ScreenTemplates = @(New-FakeHmiObject 'T1'); Folders = @() }
        ScreenPopupFolder = [pscustomobject]@{ ScreenPopups = @(New-FakeHmiObject 'P1'); Folders = @() }
    }
}
function Get-KindRoot { New-FakeHmi }

Describe 'export of HMI screens, templates and pop-ups' {
    $repo = Join-Path $TestDrive 'repo'
    Initialize-BridgeContext @{ maxResponseChars = 20000 }
    Set-BridgeProject -Name 'P' -Path 'C:\P.ap20' -Repo $repo

    It 'writes only the full export into hmi\screens with the folder tree' {
        $r = Invoke-ExportTool ([pscustomobject]@{ kind = 'hmi_screen'; names = @('S1') })
        $r.ok | Should Be $true
        ($r.items[0].files -join '|') | Should Be 'hmi\screens\Station\S1.xml'
        Get-Content (Join-Path $repo 'hmi\screens\Station\S1.xml') | Should Be 'S1 WithDefaults, WithReadOnly'
        Test-Path -LiteralPath (Join-Path $repo 'hmi\full') | Should Be $false
    }

    It 'ignores options.full: the same full export' {
        $r = Invoke-ExportTool ([pscustomobject]@{ kind = 'hmi_screen'; names = @('S1'); options = [pscustomobject]@{ full = $false } })
        ($r.items[0].files -join '|') | Should Be 'hmi\screens\Station\S1.xml'
        Get-Content (Join-Path $repo 'hmi\screens\Station\S1.xml') | Should Be 'S1 WithDefaults, WithReadOnly'
    }

    It 'does the same for templates and pop-ups' {
        (Invoke-ExportTool ([pscustomobject]@{ kind = 'hmi_template'; names = @('T1') })).items[0].files -join '|' |
            Should Be 'hmi\templates\T1.xml'
        Get-Content (Join-Path $repo 'hmi\templates\T1.xml') | Should Be 'T1 WithDefaults, WithReadOnly'
        (Invoke-ExportTool ([pscustomobject]@{ kind = 'hmi_popup'; names = @('P1') })).items[0].files -join '|' |
            Should Be 'hmi\popups\P1.xml'
        Get-Content (Join-Path $repo 'hmi\popups\P1.xml') | Should Be 'P1 WithDefaults, WithReadOnly'
    }

    It 'fails the item when the file cannot be replaced, keeps the old file and leaves no .partial' {
        $file = Join-Path $repo 'hmi\popups\P1.xml'
        [System.IO.File]::WriteAllText($file, 'old')
        $lock = [System.IO.File]::Open($file, 'Open', 'Read', 'None')
        try { $r = Invoke-ExportTool ([pscustomobject]@{ kind = 'hmi_popup'; names = @('P1') }) }
        finally { $lock.Dispose() }
        $r.ok | Should Be $false
        $r.items[0].ok | Should Be $false
        $r.items[0].error.message | Should Match 'P1.xml'
        [System.IO.File]::ReadAllText($file) | Should Be 'old'
        Test-Path -LiteralPath "$file.partial" | Should Be $false
    }

    It 'keeps options.full for tag tables: the full export replaces the minimal one in hmi\tags' {
        $hmi = [pscustomobject]@{ TagFolder = [pscustomobject]@{ TagTables = @(New-FakeHmiObject 'Tags'); Folders = @() } }
        Mock Get-KindRoot { $hmi }
        $r = Invoke-ExportTool ([pscustomobject]@{ kind = 'hmi_tag_table'; names = @('Tags'); options = [pscustomobject]@{ full = $true } })
        $r.items[0].files | Should Be 'hmi\tags\Tags.xml'
        Get-Content (Join-Path $repo 'hmi\tags\Tags.xml') | Should Be 'Tags WithDefaults, WithReadOnly'
    }
}

Describe 'Export-HmiObject over a file another process holds open' {
    $dir = Join-Path $TestDrive 'locked'
    New-Item -ItemType Directory -Force -Path $dir | Out-Null
    $file = Join-Path $dir '040 - Operating Mode.xml'

    It 'keeps the old file, leaves no .partial and throws when the file stays locked (2026-10-06)' {
        [System.IO.File]::WriteAllText($file, 'old')
        $lock = [System.IO.File]::Open($file, 'Open', 'Read', 'None')
        try {
            { Export-HmiObject @{ name = '040 - Operating Mode'; obj = (New-FakeHmiObject 'new') } $dir (New-Object psobject) } |
                Should Throw '040 - Operating Mode.xml'
        } finally { $lock.Dispose() }
        [System.IO.File]::ReadAllText($file) | Should Be 'old'
        Test-Path -LiteralPath "$file.partial" | Should Be $false
    }

    It 'replaces the file once the lock is released within the retry time' {
        [System.IO.File]::WriteAllText($file, 'old')
        $lock = [System.IO.File]::Open($file, 'Open', 'Read', 'None')
        $ps = [powershell]::Create()
        [void]$ps.AddScript({ param($l) Start-Sleep -Milliseconds 400; $l.Dispose() }).AddArgument($lock)
        $h = $ps.BeginInvoke()
        try {
            $r = Export-HmiObject @{ name = '040 - Operating Mode'; obj = (New-FakeHmiObject 'new') } $dir (New-Object psobject)
        } finally { [void]$ps.EndInvoke($h); $ps.Dispose(); $lock.Dispose() }
        $r.ok | Should Be $true
        [System.IO.File]::ReadAllText($file) | Should Be 'new None'
        Test-Path -LiteralPath "$file.partial" | Should Be $false
    }
}
