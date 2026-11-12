$here = Split-Path -Parent $MyInvocation.MyCommand.Path
foreach ($f in 'Mcp.ps1', 'Tia.ps1', 'Repo.ps1', 'Rules.ps1', 'Guards.ps1', 'Bridge.ps1', 'Tools\Objects.ps1', 'Tools\Plc.ps1', 'Tools\Hmi.ps1') { . (Join-Path $here "..\$f") }

# The HMI import guard: import of generated screens, templates and pop-ups runs the real Python validator
# (TiaHmiGenerator\hmipreview) on a fixture project repo and refuses on its errors.
# Stand-ins for TIA: no existing objects, Import-HmiFile records the file, Invoke-TiaWrite runs the body.
function Get-KindRoot { [pscustomobject]@{ ScreenFolder = 'S'; ScreenTemplateFolder = 'T'; ScreenPopupFolder = 'P' } }
function Get-GroupTree { @() }
function Get-TiaSoftwareList { @(@{ device = 'HMI_1'; kind = 'hmi' }) }
function Get-OrCreateGroup { [pscustomobject]@{ Screens = 'screens'; ScreenTemplates = 'templates'; ScreenPopups = 'popups' } }
function Import-HmiFile($Composition, $File, [bool]$Override, [bool]$CheckFaceplates) {
    $script:imported += @($File.name)
    @{ ok = $true; imported = @($File.name) }
}
function Test-TiaAlive { $true }
function Invoke-TiaWrite([string]$Description, [scriptblock]$Body, [switch]$NoTransaction, [scriptblock]$RollbackIf) {
    $out = @(& $Body)
    @{ output = $out; transaction = $true; rolledBack = $false; commitError = $null; note = $null }
}

# SimaticML shapes from TiaHmiGenerator\Tests\fixture.py
function New-HmiDocument([string]$Name, [string[]]$Items, [string]$Template, [string]$Root = 'Hmi.Screen.Screen', [string]$Number) {
    $links = if ($Template) { "<LinkList><Template TargetID=`"@OpenLink`"><Name>$Template</Name></Template></LinkList>" } else { '' }
    $numberAttribute = if ($Number) { "<Number>$Number</Number>" } else { '' }
    "<?xml version=`"1.0`" encoding=`"utf-8`"?>`r`n<Document><Engineering version=`"V20`" />" +
    "<DocumentInfo><Created>2026-10-06T00:00:00</Created></DocumentInfo>" +
    "<$Root ID=`"0`"><AttributeList><Name>$Name</Name>$numberAttribute</AttributeList>$links<ObjectList>" +
    "<Hmi.Screen.ScreenLayer ID=`"0`" CompositionName=`"Layers`"><AttributeList><Index>0</Index><Name /></AttributeList>" +
    "<ObjectList>$($Items -join '')</ObjectList></Hmi.Screen.ScreenLayer></ObjectList></$Root></Document>`r`n"
}
function New-HmiItem([string]$Type, [string]$Name, [int]$Left = 10) {
    "<$Type ID=`"0`" CompositionName=`"ScreenItems`"><AttributeList><Height>50</Height><Left>$Left</Left>" +
    "<ObjectName>$Name</ObjectName><Top>90</Top><Width>100</Width></AttributeList></$Type>"
}

function Invoke-Git([string]$Repo) { $null = & git -C $Repo @args 2>&1; if ($LASTEXITCODE) { throw "git $args failed" } }

# A project repo with an export and a generated version of screen Main, committed; returns its path.
function New-HmiRepo([string]$Name, [string[]]$GeneratedItems = @((New-HmiItem 'Hmi.Screen.Rectangle' 'rect1')), [string]$Template, $Planned) {
    $repo = Join-Path $TestDrive $Name
    Write-TextFile (Join-Path $repo 'tiabridge.json') '{ "projectName": "Fixture", "hmiDevices": ["HMI_1"], "hmiTypeIdentifier": "OrderNumber:6AV2 124-0MC01-0AX0/17.0.0.0" }'
    Write-TextFile (Join-Path $repo 'hmi\screens\Main.xml') (New-HmiDocument 'Main' @((New-HmiItem 'Hmi.Screen.Rectangle' 'rect1')))
    Write-TextFile (Join-Path $repo 'hmi\generated\screens\Main.xml') (New-HmiDocument 'Main' $GeneratedItems $Template)
    if ($Planned) { Write-TextFile (Join-Path $repo 'hmi\generated\planned.json') (ConvertTo-Json -InputObject @($Planned) -Depth 3) }
    Invoke-Git $repo init -q
    Invoke-Git $repo config user.email fixture@example.invalid
    Invoke-Git $repo config user.name Fixture
    Invoke-Git $repo add -A
    # committed long before the generated file was written: not stale
    $env:GIT_COMMITTER_DATE = '2020-01-01T00:00:00+00:00'
    try { Invoke-Git $repo commit -q -m fixture } finally { Remove-Item Env:\GIT_COMMITTER_DATE }
    $repo
}

function Invoke-HmiImport([string]$Repo, [string]$Kind = 'hmi_screen', [string[]]$Paths = @('hmi\generated\screens\Main.xml'), $Override) {
    Initialize-BridgeContext @{ maxResponseChars = 20000 }
    Set-BridgeProject -Name 'P' -Path 'C:\P.ap20' -Repo $Repo
    Register-Archive (Get-BridgeSession)
    $script:imported = @()
    $a = [pscustomobject]@{ kind = $Kind; paths = $Paths }
    if ($null -ne $Override) { $a | Add-Member override $Override }
    Invoke-ImportTool $a
}

Describe 'import of generated HMI documents (validator guard)' {
    It 'imports a clean generated screen' {
        $repo = New-HmiRepo 'Clean'
        $r = Invoke-HmiImport $repo
        $r.ok | Should Be $true
        ($script:imported -join ',') | Should Be 'Main'
    }

    It 'refuses a screen the validator reports an error on, and lists the finding' {
        $repo = New-HmiRepo 'Broken' -GeneratedItems @((New-HmiItem 'Hmi.Screen.Rectangle' 'rect1'), (New-HmiItem 'Hmi.Screen.Invented' 'thing1' 200))
        $r = Invoke-HmiImport $repo
        $r.ok | Should Be $false
        @($script:imported).Count | Should Be 0
        $r.refused | Should Match 'Main'
        $f = @($r.items[0].findings)
        $f.Count | Should Be 1
        $f[0].rule | Should Be 'vocabulary.element-type'
        $f[0].object | Should Be 'thing1'
        $f[0].document | Should Be 'hmi/generated/screens/Main.xml'
    }

    It 'refuses a screen when the declared panel collides with the HMI device in TIA (repo-level error)' {
        $repo = New-HmiRepo 'Mismatch'
        Write-TextFile (Join-Path $repo 'hmi\panel.json') '{ "panel": "TP700 Comfort", "width": 800, "height": 480, "portrait": false }'
        $r = Invoke-HmiImport $repo
        $r.ok | Should Be $false
        @($script:imported).Count | Should Be 0
        $f = @($r.items[0].findings | Where-Object { $_.rule -eq 'resolution.mismatch' })
        $f.Count | Should Be 1
        $f[0].document | Should Be 'hmi/panel.json'
    }

    It 'imports when the declared panel matches the HMI device in TIA' {
        $repo = New-HmiRepo 'Declared'
        Write-TextFile (Join-Path $repo 'hmi\panel.json') '{ "panel": "TP1200 Comfort", "width": 1280, "height": 800, "portrait": false }'
        $r = Invoke-HmiImport $repo
        $r.ok | Should Be $true
    }

    It 'refuses a screen that links an open planned item' {
        $repo = New-HmiRepo 'Planned' -Template 'NewTemplate' -Planned @(@{ kind = 'template'; name = 'NewTemplate'; note = 'the user builds it' })
        $r = Invoke-HmiImport $repo
        $r.ok | Should Be $false
        @($script:imported).Count | Should Be 0
        $r.items[0].refused | Should Match 'planned item is still open'
        @($r.items[0].findings | Where-Object { $_.rule -eq 'links.planned' -and $_.severity -eq 'error' }).Count | Should Be 1
    }

    Context 'a generated screen older than its TIA export' {
        $repo = New-HmiRepo 'Stale'
        # The user edited Main in TIA and exported it after the screen was generated
        (Get-Item (Join-Path $repo 'hmi\generated\screens\Main.xml')).LastWriteTimeUtc = [datetime]'2021-01-01'
        Write-TextFile (Join-Path $repo 'hmi\screens\Main.xml') (New-HmiDocument 'Main' @((New-HmiItem 'Hmi.Screen.Rectangle' 'rect1'), (New-HmiItem 'Hmi.Screen.Rectangle' 'rect2')))
        Invoke-Git $repo commit -q -a -m 'export after a TIA edit'

        It 'is refused without an override argument although screens default to override, and the refusal names override' {
            $r = Invoke-HmiImport $repo
            $r.ok | Should Be $false
            $r.override | Should Be $true
            @($script:imported).Count | Should Be 0
            $r.items[0].refused | Should Match 'import with override true'
            $r.items[0].refused | Should Not Match 'override_stale'
            $r.items[0].findings[0].rule | Should Be 'staleness.export-newer'
        }

        It 'is refused with an explicit override false' {
            $r = Invoke-HmiImport $repo -Override $false
            $r.ok | Should Be $false
            @($script:imported).Count | Should Be 0
            $r.items[0].findings[0].rule | Should Be 'staleness.export-newer'
            $r.items[0].findings[0].severity | Should Be 'error'
        }

        It 'is imported with an explicit override true, and the staleness stays visible as a warning' {
            $r = Invoke-HmiImport $repo -Override $true
            $r.ok | Should Be $true
            ($script:imported -join ',') | Should Be 'Main'
            $r.items[0].findings[0].rule | Should Be 'staleness.export-newer'
            $r.items[0].findings[0].severity | Should Be 'warning'
        }

        It 'ignores a leftover override_stale argument' {
            Initialize-BridgeContext @{ maxResponseChars = 20000 }
            Set-BridgeProject -Name 'P' -Path 'C:\P.ap20' -Repo $repo
            Register-Archive (Get-BridgeSession)
            $script:imported = @()
            $r = Invoke-ImportTool ([pscustomobject]@{ kind = 'hmi_screen'; paths = @('hmi\generated\screens\Main.xml'); override_stale = $true })
            $r.ok | Should Be $false
            @($script:imported).Count | Should Be 0
        }

        It 'has no override_stale in the import schema' {
            Reset-McpTools
            Register-ObjectTools
            $tool = $script:McpTools['import']
            $tool | Should Not BeNullOrEmpty
            @($tool.inputSchema.properties.Keys) -contains 'override' | Should Be $true
            @($tool.inputSchema.properties.Keys) -contains 'override_stale' | Should Be $false
            $tool.description | Should Not Match 'override_stale'
        }
    }

    It 'refuses a screen file outside hmi\generated\screens, such as the TIA export itself' {
        $repo = New-HmiRepo 'ExportPath'
        $r = Invoke-HmiImport $repo -Paths @('hmi\screens\Main.xml')
        $r.ok | Should Be $false
        @($script:imported).Count | Should Be 0
        $r.items[0].refused | Should Match 'generated'
    }

    It 'refuses everything when the validator cannot run' {
        $repo = New-HmiRepo 'NoValidator'
        $saved = $script:PythonExe
        $script:PythonExe = Join-Path $TestDrive 'no-venv\python.exe'
        $script:PythonReady = @{}
        try { $r = Invoke-HmiImport $repo } finally { $script:PythonExe = $saved; $script:PythonReady = @{} }
        $r.ok | Should Be $false
        @($script:imported).Count | Should Be 0
        $r.items[0].refused | Should Match 'could not run, so nothing is imported unchecked: .*no-venv\\python\.exe not found\. Setup: run uv sync'
    }

    It 'checks templates and pop-ups the same way' {
        $repo = New-HmiRepo 'Popup'
        Write-TextFile (Join-Path $repo 'hmi\generated\popups\Pop.xml') (New-HmiDocument 'Pop' @((New-HmiItem 'Hmi.Screen.Invented' 'g')) -Root 'Hmi.Screen.ScreenPopup')
        $r = Invoke-HmiImport $repo -Kind 'hmi_popup' -Paths @('hmi\generated\popups\Pop.xml')
        $r.ok | Should Be $false
        $r.items[0].findings[0].rule | Should Be 'vocabulary.element-type'
        $r = Invoke-HmiImport $repo -Kind 'hmi_template' -Paths @('hmi\generated\screens\Main.xml')
        $r.items[0].refused | Should Match 'hmi\\generated\\templates'
    }
}

# A screen number is unique on the device: a new screen, or an override, whose number another screen has ended TIA
# (2026-11-12). The bridge reads the numbers of the screens in TIA from their exports and refuses before TIA sees the file.
Describe 'import of a screen whose number another screen has' {
    # the screens in TIA: Get-GroupTree lists them, Export-ObjectFile writes each one as an export without defaults does
    function Get-GroupTree { @($script:inTia | ForEach-Object { @{ obj = $_; name = $_.name; folder = '' } }) }
    function Get-HmiExportOptions { 'none' }
    function Export-ObjectFile($Obj, [string]$File, $Options) {
        if ($Obj.broken) { throw 'Export failed.' }
        $script:exported += @($Obj.name)
        Write-TextFile $File (New-HmiDocument $Obj.name @() -Number $(if ($Obj.number -ne 1) { $Obj.number }))   # 1, the default, left out
    }
    function Set-InTia([hashtable]$Numbers) {
        $script:inTia = @($Numbers.Keys | Sort-Object | ForEach-Object { [pscustomobject]@{ name = $_; number = $Numbers[$_]; broken = $false } })
    }
    function Write-Generated([string]$Repo, [string]$Name, [string]$Number) {
        Write-TextFile (Join-Path $Repo "hmi\generated\screens\$Name.xml") (New-HmiDocument $Name @((New-HmiItem 'Hmi.Screen.Rectangle' 'rect1')) -Number $Number)
        "hmi\generated\screens\$Name.xml"
    }
    function Invoke-NumberImport([string]$Repo, [string[]]$Paths) { $script:exported = @(); Invoke-HmiImport $Repo -Paths $Paths }

    It 'refuses a new screen whose number a screen in TIA has, which the validator cannot see, naming that screen' {
        $repo = New-HmiRepo 'TakenInTia'
        Set-InTia @{ Main = 1; Alarms = 2 }   # Alarms has no export in the repo
        $r = Invoke-NumberImport $repo @(Write-Generated $repo 'New' '2')
        $r.ok | Should Be $false
        @($script:imported).Count | Should Be 0
        $r.items[0].refused | Should Match "Screen 'New' has number 2, which screen 'Alarms' in TIA has: TIA ended on such an import"
    }

    Context 'the validator passes' {
        function Test-HmiImportGuard { @{} }

        It 'imports a screen over its namesake with the number it has' {
            $repo = New-HmiRepo 'Namesake'
            Set-InTia @{ Main = 1; Alarms = 2 }
            $r = Invoke-NumberImport $repo @(Write-Generated $repo 'Alarms' '2')
            $r.ok | Should Be $true
            ($script:imported -join ',') | Should Be 'Alarms'
        }

        It 'refuses an override that takes the number of another screen, read as 1 from an export that leaves it out' {
            $repo = New-HmiRepo 'OverrideTaken'
            Set-InTia @{ Main = 1; Alarms = 2 }
            $r = Invoke-NumberImport $repo @(Write-Generated $repo 'Alarms' '1')
            $r.ok | Should Be $false
            @($script:imported).Count | Should Be 0
            $r.items[0].refused | Should Match "Screen 'Alarms' has number 1, which screen 'Main' in TIA has"
        }

        It 'refuses two new screens with one number in one import, naming the first' {
            $repo = New-HmiRepo 'TwoNew'
            Set-InTia @{ Main = 1 }
            $r = Invoke-NumberImport $repo @((Write-Generated $repo 'A' '5'), (Write-Generated $repo 'B' '5'))
            $r.ok | Should Be $false
            @($script:imported).Count | Should Be 0
            $r.items[0].notAttempted | Should Be $true
            $r.items[1].refused | Should Match "Screen 'B' has number 5, which screen 'A' of hmi\\generated\\screens\\A\.xml in this import has"
        }

        It 'imports a screen that takes the number an earlier document of the import frees, reading TIA once' {
            $repo = New-HmiRepo 'Freed'
            Set-InTia @{ Main = 1; Alarms = 2 }
            $r = Invoke-NumberImport $repo @((Write-Generated $repo 'Alarms' '3'), (Write-Generated $repo 'New' '2'))
            $r.ok | Should Be $true
            ($script:imported -join ',') | Should Be 'Alarms,New'
            ($script:exported -join ',') | Should Be 'Alarms,Main'
        }

        It 'refuses a screen whose number an earlier document without one gets: the lowest number no other screen has' {
            $repo = New-HmiRepo 'NoNumber'
            Set-InTia @{ Main = 1 }
            $r = Invoke-NumberImport $repo @((Write-Generated $repo 'New' ''), (Write-Generated $repo 'Other' '2'))
            $r.ok | Should Be $false
            $r.items[1].refused | Should Match "Screen 'Other' has number 2, which screen 'New' of .* in this import has"
            $r = Invoke-NumberImport $repo @((Write-Generated $repo 'New' ''), (Write-Generated $repo 'Other' '3'))
            $r.ok | Should Be $true
        }

        It 'refuses every screen when a screen in TIA cannot be exported for its number' {
            $repo = New-HmiRepo 'Unreadable'
            Set-InTia @{ Main = 1; Alarms = 2 }
            $script:inTia[0].broken = $true
            $r = Invoke-NumberImport $repo @((Write-Generated $repo 'A' '5'), (Write-Generated $repo 'B' '6'))
            $r.ok | Should Be $false
            @($script:imported).Count | Should Be 0
            foreach ($i in $r.items) { $i.refused | Should Match "no screen is imported unchecked: Screen 'Alarms' could not be exported to read its number: Export failed\." }
        }
    }
}

# An Int tag with Length 1 ended TIA on import. A tag table comes from hmi\generated\tags and
# passes the validator (rules\tagtable.py), as a screen does.
Describe 'import of a generated HMI tag table (validator guard)' {
    function Get-KindRoot { [pscustomobject]@{ TagFolder = 'T' } }
    function Get-OrCreateGroup { [pscustomobject]@{ TagTables = 'tables' } }

    function New-TagDocument([string]$Name, [int]$Length) {
        "<?xml version=`"1.0`" encoding=`"utf-8`"?>`r`n<Document><Engineering version=`"V20`" /><Hmi.Tag.TagTable ID=`"0`">" +
        "<AttributeList><Name>$Name</Name></AttributeList><ObjectList><Hmi.Tag.Tag ID=`"1`" CompositionName=`"Tags`">" +
        "<AttributeList><Length>$Length</Length><Name>zzSpeed</Name></AttributeList><LinkList>" +
        "<AcquisitionCycle TargetID=`"@OpenLink`"><Name>1 s</Name></AcquisitionCycle>" +
        "<DataType TargetID=`"@OpenLink`"><Name>Int</Name></DataType><HmiDataType TargetID=`"@OpenLink`"><Name>Int</Name></HmiDataType>" +
        "</LinkList></Hmi.Tag.Tag></ObjectList></Hmi.Tag.TagTable></Document>`r`n"
    }

    It 'refuses an Int tag with Length 1 before TIA sees it, and lists the finding' {
        $repo = New-HmiRepo 'TagLength'
        Write-TextFile (Join-Path $repo 'hmi\generated\tags\Plant.xml') (New-TagDocument 'Plant' 1)
        $r = Invoke-HmiImport $repo -Kind 'hmi_tag_table' -Paths @('hmi\generated\tags\Plant.xml')
        $r.ok | Should Be $false
        @($script:imported).Count | Should Be 0
        $r.items[0].refused | Should Match 'tagtable.length'
        $f = @($r.items[0].findings)
        $f[0].rule | Should Be 'tagtable.length'
        $f[0].object | Should Be 'zzSpeed'
        $f[0].document | Should Be 'hmi/generated/tags/Plant.xml'
    }

    It 'imports a tag table the validator passes' {
        $repo = New-HmiRepo 'TagClean'
        Write-TextFile (Join-Path $repo 'hmi\generated\tags\Plant.xml') (New-TagDocument 'Plant' 2)
        $r = Invoke-HmiImport $repo -Kind 'hmi_tag_table' -Paths @('hmi\generated\tags\Plant.xml')
        $r.ok | Should Be $true
        ($script:imported -join ',') | Should Be 'Plant'
    }

    It 'refuses a tag table outside hmi\generated\tags, such as the TIA export folder' {
        $repo = New-HmiRepo 'TagExportPath'
        Write-TextFile (Join-Path $repo 'hmi\tags\Plant.xml') (New-TagDocument 'Plant' 2)
        $r = Invoke-HmiImport $repo -Kind 'hmi_tag_table' -Paths @('hmi\tags\Plant.xml')
        $r.ok | Should Be $false
        @($script:imported).Count | Should Be 0
        $r.items[0].refused | Should Match 'hmi\\generated\\tags'
    }
}

# A project with several HMI devices exports each into hmi\<device>\; its generated
# documents are in hmi\<device>\generated\<kind> and the validator checks that device (--device).
Describe 'import of generated HMI documents of a project with several HMI devices' {
    function Get-TiaSoftwareList { @(@{ device = 'HMI_A'; kind = 'hmi' }, @{ device = 'HMI_B'; kind = 'hmi' }) }

    function New-DeviceRepo([string]$Name, [string[]]$GeneratedItems = @((New-HmiItem 'Hmi.Screen.Rectangle' 'rect1'))) {
        $repo = Join-Path $TestDrive $Name
        Write-TextFile (Join-Path $repo 'tiabridge.json') '{ "projectName": "Fixture", "hmiDevices": ["HMI_A", "HMI_B"], "hmiTypeIdentifier": { "HMI_A": "OrderNumber:6AV2 124-0MC01-0AX0/17.0.0.0", "HMI_B": "OrderNumber:6AV2 124-0MC01-0AX0/17.0.0.0" } }'
        foreach ($d in 'HMI_A', 'HMI_B') { Write-TextFile (Join-Path $repo "hmi\$d\screens\Main.xml") (New-HmiDocument 'Main' @((New-HmiItem 'Hmi.Screen.Rectangle' 'rect1'))) }
        Write-TextFile (Join-Path $repo 'hmi\HMI_A\generated\screens\Main.xml') (New-HmiDocument 'Main' $GeneratedItems)
        Invoke-Git $repo init -q
        Invoke-Git $repo config user.email fixture@example.invalid
        Invoke-Git $repo config user.name Fixture
        Invoke-Git $repo add -A
        $env:GIT_COMMITTER_DATE = '2020-01-01T00:00:00+00:00'
        try { Invoke-Git $repo commit -q -m fixture } finally { Remove-Item Env:\GIT_COMMITTER_DATE }
        $repo
    }

    function Invoke-DeviceImport([string]$Repo, [string[]]$Paths = @('hmi\HMI_A\generated\screens\Main.xml')) {
        Initialize-BridgeContext @{ maxResponseChars = 20000 }
        Set-BridgeProject -Name 'P' -Path 'C:\P.ap20' -Repo $Repo
        Register-Archive (Get-BridgeSession)
        $script:imported = @()
        Invoke-ImportTool ([pscustomobject]@{ kind = 'hmi_screen'; paths = $Paths; device = 'HMI_A' })
    }

    It 'imports a clean screen of the device from its generated folder, validated for that device' {
        $repo = New-DeviceRepo 'DevClean'
        $r = Invoke-DeviceImport $repo
        $r.ok | Should Be $true
        ($script:imported -join ',') | Should Be 'Main'
    }

    It 'refuses a screen of the device that the validator reports an error on' {
        $repo = New-DeviceRepo 'DevBroken' -GeneratedItems @((New-HmiItem 'Hmi.Screen.Invented' 'thing1'))
        $r = Invoke-DeviceImport $repo
        $r.ok | Should Be $false
        @($script:imported).Count | Should Be 0
        $r.items[0].findings[0].rule | Should Be 'vocabulary.element-type'
        $r.items[0].findings[0].document | Should Be 'hmi/HMI_A/generated/screens/Main.xml'
    }

    It 'refuses a file outside the device''s generated folder' {
        $repo = New-DeviceRepo 'DevOutside'
        Write-TextFile (Join-Path $repo 'hmi\HMI_B\generated\screens\Main.xml') (New-HmiDocument 'Main' @((New-HmiItem 'Hmi.Screen.Rectangle' 'rect1')))
        $r = Invoke-DeviceImport $repo -Paths @('hmi\HMI_B\generated\screens\Main.xml')
        $r.ok | Should Be $false
        $r.items[0].refused | Should Match 'hmi\\HMI_A\\generated\\screens'
    }

    It 'finds the device folder of a generated document' {
        Get-HmiDeviceFolder 'C:\R' 'C:\R\hmi\HMI_A\generated\screens\x\Main.xml' | Should Be 'HMI_A'
        Get-HmiDeviceFolder 'C:\R\' 'C:\R\hmi\generated\screens\Main.xml' | Should Be ''
        Get-HmiDeviceFolder 'C:\R' 'C:\Other\hmi\HMI_A\generated\screens\Main.xml' | Should Be ''
    }
}

# The format is checked before the write, as a folder of a new object was made before the check inside it.
Describe 'import of an HMI object that is no SimaticML' {
    function Test-HmiImportGuard { @{} }   # the format is the question here, not the validator
    function Get-OrCreateGroup { $script:groupsMade++; [pscustomobject]@{ TagTables = 'tables' } }
    function Get-KindRoot { [pscustomobject]@{ TagFolder = 'T'; TextLists = @() } }

    It 'makes no folder and holds nothing: <kind>' -TestCases @(
        @{ kind = 'hmi_tag_table'; path = 'hmi\generated\tags\sub\New.s7dcl' }
        @{ kind = 'hmi_textlist'; path = 'hmi\textlists\New.s7dcl' }
    ) {
        param($kind, $path)
        $repo = Join-Path $TestDrive "NoXml$kind"
        Write-TextFile (Join-Path $repo $path) 'x'
        $script:groupsMade = 0
        $r = Invoke-HmiImport $repo -Kind $kind -Paths @($path)
        $r.items[0].refused | Should Match 'SimaticML'
        $script:groupsMade | Should Be 0
        @($script:imported).Count | Should Be 0
        @(Test-SaveAllowed (Get-BridgeSession)).Count | Should Be 0
    }

    It 'refuses SimaticML TIA would refuse for how it is written: <kind>' -TestCases @(
        @{ kind = 'hmi_tag_table' }
        @{ kind = 'hmi_textlist' }
        @{ kind = 'hmi_screen' }
    ) {
        param($kind)
        $p = Join-Path $TestDrive "Sig$kind.xml"
        Write-TextFile $p "<?xml version=`"1.0`" encoding=`"utf-8-sig`"?>`r`n<Document />"
        $r = & (Get-ObjectKind $kind).precheck @{ file = $p; name = "Sig$kind"; format = 'xml' } @{}
        $r.refused | Should Match "line 1 declares encoding 'utf-8-sig'"
    }

    It 'refuses a screen by its format before the faceplate guard reads it' {
        function Get-FaceplateRefs { throw 'read the file' }
        $r = & (Get-ObjectKind 'hmi_screen').precheck @{ file = 'C:\x\New.s7dcl'; name = 'New'; format = 's7dcl' } @{}
        $r.refused | Should Match 'SimaticML'
    }
}
