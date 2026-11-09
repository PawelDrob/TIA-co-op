$here = Split-Path -Parent $MyInvocation.MyCommand.Path
foreach ($f in 'Mcp.ps1', 'Tia.ps1', 'Repo.ps1', 'Rules.ps1', 'Guards.ps1', 'Bridge.ps1', 'Tools\Objects.ps1', 'Tools\Plc.ps1', 'Tools\Hmi.ps1', 'Tools\Library.ps1',
               'Tools\Report.ps1') { . (Join-Path $here "..\$f") }

# Small guards from the bridge audit: override of an HMI tag table, python with a time limit, exact export names,
# know-how protected blocks under a master copy with Replace.

if (-not ('Siemens.Engineering.Library.MasterCopies.MasterCopyMode' -as [type])) {
    Add-Type -TypeDefinition 'namespace Siemens.Engineering.Library.MasterCopies { public enum MasterCopyMode { ThrowIfExists, Replace, Rename } }'
}
if (-not ('FakeMc.Composition' -as [type])) {
    Add-Type -TypeDefinition @'
namespace FakeMc {
    public class ContentKind { public string Name { get; set; } }
    public class Content { public ContentKind ContentType { get; set; } public string ContentName { get; set; } }
    public class MasterCopy { public Content[] ContentDescriptions { get; set; } }
    public class Composition {
        public int Placed { get; set; }
        public object CreateFrom(MasterCopy copy, object mode) { Placed++; return null; }
    }
}
'@
}

function Initialize-Project {
    Initialize-BridgeContext @{ maxResponseChars = 20000 }
    Set-BridgeProject -Name 'P' -Path 'C:\P.ap20' -Repo (Join-Path $TestDrive ('R' + [guid]::NewGuid().ToString('N')))
    Register-Archive (Get-BridgeSession)
}
function Get-KindRoot { 'root' }
function Get-TiaDeviceName { 'DEV_1' }
function Get-LibraryLink { $null }
function Invoke-TiaWrite([string]$Description, [scriptblock]$Body, [switch]$NoTransaction, [scriptblock]$RollbackIf) {
    $script:written++
    @{ output = @(& $Body); transaction = $true; rolledBack = $false; commitError = $null; note = $null }
}

Describe 'import of an HMI tag table' {
    function Test-HmiImportGuard { @{} }   # the validator guard: HmiImport.Tests.ps1
    function Get-GroupTree { foreach ($n in $script:tables) { @{ name = $n; folder = ''; obj = [pscustomobject]@{ Name = $n } } } }
    function Import-HmiFile($Composition, $File, [bool]$Override) { $script:imported += @($File.name); @{ ok = $true } }
    function Invoke-TagImport([string]$Name, $Extra = @{}) {
        Initialize-Project
        $script:written = 0; $script:imported = @()
        Write-TextFile (Join-Path $script:Bridge.repo "hmi\generated\tags\$Name.xml") '<Document />'
        $a = @{ kind = 'hmi_tag_table'; paths = @("hmi\generated\tags\$Name.xml") }
        foreach ($k in $Extra.Keys) { $a[$k] = $Extra[$k] }
        Invoke-ImportTool ([pscustomobject]$a)
    }

    It 'refuses override and says to delete the table first, without touching TIA' {
        $script:tables = @('T')
        $r = Invoke-TagImport 'T' @{ override = $true }
        $r.ok | Should Be $false
        $r.refused | Should Match 'delete it first, then import'
        $script:written | Should Be 0
    }

    It 'refuses override also when no table has the file name: the name inside the file may differ' {
        $script:tables = @()
        $r = Invoke-TagImport 'New' @{ override = $true }
        $r.refused | Should Match 'delete it first, then import'
        $script:written | Should Be 0
    }

    It 'says the same when the table exists and override is not passed' {
        $script:tables = @('T')
        $r = Invoke-TagImport 'T'
        $r.ok | Should Be $false
        @($r.items)[0].refused | Should Match 'delete it first, then import'
    }

    It 'imports a new table' {
        $script:tables = @()
        $r = Invoke-TagImport 'New'
        $r.ok | Should Be $true
        $script:imported -join ',' | Should Be 'New'
    }
}

Describe 'python with a time limit' {
    $savedExe = $script:PythonExe; $savedReady = $script:PythonReady
    $savedValidator = $script:HmiValidatorLimitMinutes; $savedReport = $script:ChangeReportLimitMinutes

    function Use-FakePython([string]$Body) {
        $file = Join-Path $TestDrive 'fake-python.cmd'
        Set-Content -LiteralPath $file -Value "@echo off`r`n$Body" -Encoding ASCII
        $script:PythonExe = $file
        $script:PythonReady = @{ '' = $true; yaml = $true }
    }
    # a child process that hangs; its count marks the test, so a test sees only its own
    function Get-Hang([int]$Count) { "ping -n $Count 127.0.0.1 >nul" }
    # How many pings of that count still run. A process ended by taskkill can still be listed for a moment (on a CI
    # runner it was): asked again until none is, for 10 s at most. It returns the number, not the processes: a function
    # gives one process back unwrapped, and the .Count of one process reads empty in Windows PowerShell 5.1.
    function Get-LeftOverPing([int]$Count) {
        $watch = [System.Diagnostics.Stopwatch]::StartNew()
        while ($true) {
            $left = @(Get-CimInstance Win32_Process -Filter "Name='PING.EXE'" | Where-Object { $_.CommandLine -match "-n $Count 127\.0\.0\.1" })
            if (-not $left.Count -or $watch.Elapsed.TotalSeconds -ge 10) { return $left.Count }
            Start-Sleep -Milliseconds 200
        }
    }

    try {
        It 'stops the HMI validator and its child processes at the limit, and says so' {
            Use-FakePython (Get-Hang 47)
            $script:HmiValidatorLimitMinutes = 0.01
            $watch = [System.Diagnostics.Stopwatch]::StartNew()
            { Invoke-HmiValidator -Repo $TestDrive -OverrideStale $false } | Should Throw 'did not finish within 0.01 minutes'
            $watch.Elapsed.TotalSeconds | Should BeLessThan 30
            Get-LeftOverPing 47 | Should Be 0
        }

        It 'refuses the import when the validator hit the limit' {
            Use-FakePython (Get-Hang 48)
            $script:HmiValidatorLimitMinutes = 0.01
            $r = Test-HmiImportGuard $TestDrive @(@{ file = (Join-Path $TestDrive 'hmi\generated\screens\S.xml') }) $false
            @($r.Values)[0].refused | Should Match 'nothing is imported unchecked.*did not finish within'
            Get-LeftOverPing 48 | Should Be 0
        }

        It 'stops change_report at the limit, and says so' {
            Use-FakePython (Get-Hang 49)
            $script:ChangeReportLimitMinutes = 0.01
            { Invoke-ChangeReports @('--git', 'x') } | Should Throw 'did not finish within 0.01 minutes'
            Get-LeftOverPing 49 | Should Be 0
        }

        It 'has a limit of minutes for both, the report the longer one' {
            $savedValidator | Should BeGreaterThan 0
            $savedReport | Should BeGreaterThan $savedValidator
        }

        It 'still returns what python printed' {
            Use-FakePython 'echo [{"severity":"error","document":"a.xml","object":"o","rule":"r","message":"m"}]'
            $script:HmiValidatorLimitMinutes = 1
            @(Invoke-HmiValidator -Repo $TestDrive -OverrideStale $false)[0].rule | Should Be 'r'
        }

        It 'still reports an exit code with stderr' {
            Use-FakePython "echo broken 1>&2`r`nexit /b 3"
            $script:ChangeReportLimitMinutes = 1
            { Invoke-ChangeReports @('--git', 'x') } | Should Throw 'exited with 3: broken'
        }
    }
    finally {
        $script:PythonExe = $savedExe; $script:PythonReady = $savedReady
        $script:HmiValidatorLimitMinutes = $savedValidator; $script:ChangeReportLimitMinutes = $savedReport
    }
}

Describe 'export and list by name' {
    Register-ObjectKind 'fakenames' @{
        scope = 'plc'; dir = 'plc\names'; defaultOverride = $true; description = 'test kind'
        items = { param($root) foreach ($n in 'Arr[1]', 'Arr[1]_x', 'Arr2', 'Plain') { @{ name = $n; folder = ''; obj = [pscustomobject]@{ Name = $n } } } }
        export = { param($e, $dir, $opt) $script:exported += @($e.name); @{ ok = $true; format = 'xml'; files = @() } }
    }
    function Invoke-Named([string[]]$Names) {
        Initialize-Project
        $script:exported = @()
        Invoke-ExportTool ([pscustomobject]@{ kind = 'fakenames'; names = $Names })
    }

    It 'takes a name with [ ] as that exact name' {
        (Invoke-Named @('Arr[1]')).ok | Should Be $true
        $script:exported -join ',' | Should Be 'Arr[1]'
    }

    It 'keeps [ ] literal in a wildcard name' {
        $null = Invoke-Named @('Arr[1]*')
        $script:exported -join ',' | Should Be 'Arr[1],Arr[1]_x'
    }

    It 'still takes * and ?' {
        $null = Invoke-Named @('Arr?')
        $script:exported -join ',' | Should Be 'Arr2'
        $null = Invoke-Named @('*')
        @($script:exported).Count | Should Be 4
    }

    It 'gives [ ] without * or ? no pattern meaning' {
        $r = Invoke-Named @('[P]lain')
        $r.ok | Should Be $false
        @($r.items)[0].error.type | Should Be 'TiaBridge.NotFound'
        @($script:exported).Count | Should Be 0
    }

    It 'lists by the same rules' {
        Initialize-Project
        function Get-Filtered([string[]]$Filter) { @((Invoke-ListTool ([pscustomobject]@{ kind = 'fakenames'; filter = $Filter })).items | ForEach-Object { $_.name }) -join ',' }
        Get-Filtered @('Arr[1]') | Should Be 'Arr[1]'
        Get-Filtered @('Arr[1]*') | Should Be 'Arr[1],Arr[1]_x'
        Get-Filtered @('[P]lain') | Should Be ''
    }
}

Describe 'master_copy_to_project with Replace over a know-how protected block' {
    function New-Entry([string]$Name, [string]$Folder, [bool]$Db, [bool]$Protected) { @{ name = $Name; folder = $Folder; obj = [pscustomobject]@{ IsDb = $Db; IsKnowHowProtected = $Protected } } }
    $script:withBoth = @((New-Entry 'Khp' 'Top/Grp/Sub' $false $true), (New-Entry 'KhpDb' 'Data' $true $true), (New-Entry 'Std' 'Other' $false $false), (New-Entry 'StdDb' 'Data' $true $false))
    $script:withDb = @((New-Entry 'KhpDb' 'Data' $true $true), (New-Entry 'Std' 'Other' $false $false))
    $script:withNone = @((New-Entry 'Std' 'Other' $false $false), (New-Entry 'StdDb' 'Data' $true $false))
    function Get-GroupTree { $script:tree }
    function Test-IsDataBlock($Block) { $Block.IsDb }
    function Get-SafetyProgramRefusal { $null }
    function Get-TiaLibrary { 'lib' }
    function Get-OrCreateGroup { $script:written++; [pscustomobject]@{ Blocks = $script:composition; Groups = $script:composition } }
    function New-FakeMasterCopy([string]$Content) {
        $kind = New-Object FakeMc.ContentKind -Property @{ Name = 'FB' }
        $item = New-Object FakeMc.Content -Property @{ ContentName = $Content; ContentType = $kind }
        New-Object FakeMc.MasterCopy -Property @{ ContentDescriptions = @($item) }
    }
    function Find-MasterCopy { @{ obj = (New-FakeMasterCopy $script:content) } }
    function Get-MasterCopyTarget { @{ kind = $script:targetKind; composition = $script:target } }
    function Invoke-Place([string]$Content, [string]$Mode, $Knowhow = $null, [string]$Target = 'Blocks', [string]$Kind = 'block', [object[]]$Tree = $script:withBoth) {
        Initialize-Project
        $script:written = 0; $script:content = $Content; $script:target = $Target; $script:targetKind = $Kind; $script:tree = $Tree
        $script:composition = New-Object FakeMc.Composition
        Invoke-MasterCopyToProjectTool ([pscustomobject]@{ name = 'M'; folder = 'F'; mode = $Mode; knowhow = $Knowhow })
    }

    It 'is refused without knowhow: true, names the block and touches nothing in TIA' {
        $r = Invoke-Place 'Khp' 'Replace'
        $r.ok | Should Be $false
        $r.refused | Should Match "'Khp' is know-how protected"
        $r.refused | Should Match 'knowhow: true'
        $r.refused | Should Match 'user asked'
        $script:written | Should Be 0
    }

    It 'only a true opens it, not the text false' {
        (Invoke-Place 'Khp' 'Replace' 'false').ok | Should Be $false
    }

    It 'places it with knowhow: true' {
        (Invoke-Place 'Khp' 'Replace' $true).ok | Should Be $true
        $script:composition.Placed | Should Be 1
    }

    It 'lets Replace over a block that is not protected go on' {
        (Invoke-Place 'Std' 'Replace').ok | Should Be $true
    }

    It 'lets a mode that replaces nothing go on' {
        (Invoke-Place 'Khp' 'Rename').ok | Should Be $true
    }

    It 'checks the same name over blocks and DBs, whichever of the two the master copy holds' {
        (Invoke-Place 'KhpDb' 'Replace').refused | Should Match "'KhpDb' is know-how protected"
        (Invoke-Place 'Khp' 'Replace' $null 'Blocks' 'db').refused | Should Match "'Khp' is know-how protected"
        (Invoke-Place 'KhpDb' 'Replace' $null 'Blocks' 'db').refused | Should Match "'KhpDb' is know-how protected"
    }

    It 'refuses Replace of a folder of any name when the PLC has a know-how protected block: its contents are not known' {
        $r = Invoke-Place 'Other' 'Replace' $null 'Groups'
        $r.ok | Should Be $false
        $r.refused | Should Match 'master copy of a folder'
        $r.refused | Should Match 'Khp'
        $script:written | Should Be 0
    }

    It 'refuses Replace of a folder when the only protected one is a DB' {
        $r = Invoke-Place 'Other' 'Replace' $null 'Groups' 'block' $script:withDb
        $r.ok | Should Be $false
        $r.refused | Should Match 'KhpDb'
    }

    It 'names the first 10 protected objects of a folder refusal and says how many more there are' {
        $many = @(1..13 | ForEach-Object { New-Entry "Khp$_" 'Top' $false $true })
        $r = Invoke-Place 'Other' 'Replace' $null 'Groups' 'block' $many
        $r.refused | Should Match "'Khp10' and 3 more"
        $r.refused | Should Not Match 'Khp11'
        (Invoke-Place 'Other' 'Replace' $null 'Groups' 'block' @($many | Select-Object -First 10)).refused | Should Not Match ' more '
    }

    It 'places a folder with knowhow: true' {
        (Invoke-Place 'Other' 'Replace' $true 'Groups').ok | Should Be $true
    }

    It 'lets Replace of a folder go on when the PLC has no know-how protected block or DB' {
        (Invoke-Place 'Other' 'Replace' $null 'Groups' 'block' $script:withNone).ok | Should Be $true
    }

    It 'lets a folder with a mode that replaces nothing go on' {
        (Invoke-Place 'Other' 'Rename' $null 'Groups').ok | Should Be $true
    }
}
