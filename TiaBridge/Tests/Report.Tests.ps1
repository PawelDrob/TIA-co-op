$here = Split-Path -Parent $MyInvocation.MyCommand.Path
foreach ($f in 'Mcp.ps1', 'Repo.ps1', 'Rules.ps1', 'Bridge.ps1', 'Tools\Objects.ps1', 'Tools\Report.ps1') { . (Join-Path $here "..\$f") }

# change_report: the report of a commit of the project repo through the real TiaChangeReports
# (the python of the repo's .venv). No TIA: the tool reads git only.

# A small LAD + SCL block (as in TiaChangeReports\tests); the second commit changes one contact.
$script:Src = @'
FUNCTION_BLOCK "A"
    VAR_INPUT
        a : Bool;
        b : Bool;
    END_VAR
    VAR
        x : Bool;
    END_VAR
    {
        S7_Language := "LAD";
        S7_NetworkTitle := "MLC_1"
    }
    NETWORK
        RUNG wire#powerrail
            Contact( #a )
            I_Contact( #b )
            Coil( #x )
        END_RUNG
    END_NETWORK
END_FUNCTION_BLOCK
'@ -replace "`r`n", "`n"
$script:Res = "MultiLingualTexts:`n  - id: MLC_1`n    en-US: Seal-in`n"

function Invoke-FixtureGit([string]$Repo) { $null = & git -C $Repo -c user.name=Fixture -c user.email=fixture@example.invalid @args 2>&1; if ($LASTEXITCODE) { throw "git $args failed" } }

# A project repo with one commit, or two (the second changes block A); committed on 2026-10-28.
function New-ReportRepo([string]$Name, [int]$Commits = 2) {
    $repo = Join-Path $TestDrive $Name
    Write-TextFile (Join-Path $repo 'plc\A.s7dcl') $script:Src
    Write-TextFile (Join-Path $repo 'plc\A.s7res') $script:Res
    Write-TextFile (Join-Path $repo '.gitignore') "archives/`n"
    Invoke-FixtureGit $repo init -q
    Invoke-FixtureGit $repo config core.autocrlf false
    $env:GIT_COMMITTER_DATE = '2026-10-28T12:00:00+00:00'
    try {
        Invoke-FixtureGit $repo add -A
        Invoke-FixtureGit $repo commit -q -m one
        if ($Commits -gt 1) {
            Write-TextFile (Join-Path $repo 'plc\A.s7dcl') ($script:Src -replace 'I_Contact\( #b \)', 'I_Contact( #a )')
            Invoke-FixtureGit $repo add -A
            Invoke-FixtureGit $repo commit -q -m two
        }
    } finally { Remove-Item Env:\GIT_COMMITTER_DATE }
    $repo
}

function Invoke-Report([string]$Repo, [hashtable]$Arguments = @{}) {
    Initialize-BridgeContext @{ maxResponseChars = 20000 }
    Set-BridgeProject -Name 'P' -Path 'C:\P.ap20' -Repo $Repo
    Invoke-ChangeReportTool ([pscustomobject]$Arguments)
}

function Get-ShortSha([string]$Repo, [string]$Rev) { (& git -C $Repo rev-parse --short $Rev).Trim() }

Describe 'change_report' {
    It 'is refused before connect' {
        Initialize-BridgeContext @{ maxResponseChars = 20000 }
        { Invoke-ChangeReportTool ([pscustomobject]@{}) } | Should Throw 'call connect first'
    }

    It 'writes the report of the last commit into changes\reports, ignored by git' {
        $repo = New-ReportRepo 'Last'
        $r = Invoke-Report $repo
        $r.ok | Should Be $true
        $r.page | Should Be "changes\reports\2026-10-28_$(Get-ShortSha $repo HEAD).html"
        Test-Path (Join-Path $repo $r.page) | Should Be $true
        $r.ContainsKey('changelog') | Should Be $false
        @($r.blocks).Count | Should Be 1
        $r.blocks[0].name | Should Be 'A'
        $r.blocks[0].state | Should Be 'changed'
        $r.blocks[0].networks[0].title | Should Be 'Seal-in'
        $r.before | Should Match 'HEAD~1'
        (Get-Content (Join-Path $repo '.gitignore')) -contains 'changes/reports/' | Should Be $true
        (& git -C $repo status --porcelain) | Should Match '\.gitignore'
        (& git -C $repo status --porcelain) | Should Not Match 'changes/'
    }

    It 'titles the page' {
        $repo = New-ReportRepo 'Title'
        $r = Invoke-Report $repo @{ title = 'Trolley fix' }
        [IO.File]::ReadAllText((Join-Path $repo $r.page)) | Should Match '<title>Trolley fix</title>'
    }

    It 'names the page after both commits when rev1 is given' {
        $repo = New-ReportRepo 'Range'
        $r = Invoke-Report $repo @{ rev1 = 'HEAD~1'; rev2 = 'HEAD' }
        $r.ok | Should Be $true
        $r.page | Should Be "changes\reports\2026-10-28_$(Get-ShortSha $repo HEAD~1)-$(Get-ShortSha $repo HEAD).html"
    }

    It 'limits the report to the given blocks' {
        $repo = New-ReportRepo 'Blocks'
        $r = Invoke-Report $repo @{ blocks = @('Other') }
        $r.ok | Should Be $true
        @($r.blocks).Count | Should Be 0
        $r.unmatched.blocks | Should Be 'Other'
    }

    It 'lists the PLC tag tables that changed, and leaves plcTags out when none did' {
        $repo = New-ReportRepo 'Tags'
        (Invoke-Report $repo).ContainsKey('plcTags') | Should Be $false
        $table = '<Document><SW.Tags.PlcTagTable ID="0"><AttributeList><Name>Plant</Name></AttributeList></SW.Tags.PlcTagTable></Document>'
        Write-TextFile (Join-Path $repo 'plc\tags\Plant.xml') $table
        Invoke-FixtureGit $repo add -A
        Invoke-FixtureGit $repo commit -q -m three
        $r = Invoke-Report $repo
        @($r.plcTags).Count | Should Be 1
        $r.plcTags[0].name | Should Be 'Plant'
        $r.plcTags[0].state | Should Be 'new'
    }

    It 'names the changed files it does not read, and leaves otherFiles out when there are none' {
        $repo = New-ReportRepo 'Others'
        (Invoke-Report $repo).ContainsKey('otherFiles') | Should Be $false
        Write-TextFile (Join-Path $repo 'library\mastercopies\mastercopies.json') '{}'
        Invoke-FixtureGit $repo add -A
        Invoke-FixtureGit $repo commit -q -m three
        @((Invoke-Report $repo).otherFiles) | Should Be 'library/mastercopies/mastercopies.json'
    }

    It 'names skipped files and leaves skipped and unmatched out when there are none' {
        $repo = New-ReportRepo 'Skipped'
        $r = Invoke-Report $repo
        $r.ContainsKey('skipped') | Should Be $false
        $r.ContainsKey('unmatched') | Should Be $false
        Write-TextFile (Join-Path $repo 'plc\A.s7dcl') $script:Src
        Write-TextFile (Join-Path $repo 'plc\Broken.s7dcl') "FUNCTION_BLOCK `"Broken`"`nthis is { not s7dcl`n"
        Invoke-FixtureGit $repo add -A
        Invoke-FixtureGit $repo commit -q -m three
        $r = Invoke-Report $repo
        @($r.blocks).Count | Should Be 1
        @($r.skipped).Count | Should Be 1
        $r.skipped[0].path | Should Be 'plc/Broken.s7dcl'
        $r.skipped[0].reason | Should Match '^unreadable: '
    }

    It 'refuses when the repo has only one commit or a revision does not exist' {
        $one = New-ReportRepo 'One' -Commits 1
        (Invoke-Report $one).refused | Should Match 'only one commit'
        $repo = New-ReportRepo 'Bad'
        (Invoke-Report $repo @{ rev2 = 'nosuchrev' }).refused | Should Match "nosuchrev"
    }

    It 'lists the HMI objects of the commit and gives one part with only' {
        $repo = New-ReportRepo 'Hmi'
        $screen = '<?xml version="1.0" encoding="utf-8"?><Document><Hmi.Screen.Screen ID="0"><AttributeList><Height>800</Height>' +
            '<Name>Silo</Name><Number>1</Number><Width>1280</Width></AttributeList><ObjectList><Hmi.Screen.ScreenLayer ID="1" ' +
            'CompositionName="Layers"><AttributeList><Index>0</Index><VisibleES>true</VisibleES></AttributeList><ObjectList>' +
            '<Hmi.Screen.Rectangle ID="2" CompositionName="ScreenItems"><AttributeList><Height>40</Height><Left>LEFT</Left>' +
            '<ObjectName>r1</ObjectName><Top>100</Top><Width>40</Width></AttributeList></Hmi.Screen.Rectangle></ObjectList>' +
            '</Hmi.Screen.ScreenLayer></ObjectList></Hmi.Screen.Screen></Document>'
        Write-TextFile (Join-Path $repo 'hmi\screens\Silo.xml') ($screen -creplace 'LEFT', '10')
        Invoke-FixtureGit $repo add -A
        Invoke-FixtureGit $repo commit -q -m three
        Write-TextFile (Join-Path $repo 'hmi\screens\Silo.xml') ($screen -creplace 'LEFT', '50')
        Invoke-FixtureGit $repo add -A
        Invoke-FixtureGit $repo commit -q -m four
        $r = Invoke-Report $repo
        @($r.hmi).Count | Should Be 1
        $r.hmi[0].name | Should Be 'Silo'
        $r.hmi[0].kind | Should Be 'screen'
        $r.hmi[0].state | Should Be 'changed'
        $r.hmi[0].changes | Should Be 1
        $p = Invoke-Report $repo @{ rev1 = 'HEAD~3'; only = 'plc' }
        $p.ContainsKey('hmi') | Should Be $false
        @($p.blocks).Count | Should Be 1
        (Invoke-Report $repo @{ only = 'both' }).refused | Should Match 'only must be plc or hmi'
    }

    It 'reports a python that cannot be started' {
        $repo = New-ReportRepo 'NoPython'
        $saved = $script:PythonExe
        try {
            $script:PythonExe = Join-Path $TestDrive 'no-venv\python.exe'
            $script:PythonReady = @{}
            { Invoke-Report $repo } | Should Throw 'not found. Setup: run uv sync in'
            # python gone after a good check in this bridge process
            $script:PythonReady = @{ yaml = $true }
            { Invoke-Report $repo } | Should Throw 'python could not be started'
        } finally { $script:PythonExe = $saved; $script:PythonReady = @{} }
    }
}

Describe 'ConvertTo-ProcessArgument (Windows command-line quoting)' {
    It 'quotes spaces, quotes and trailing backslashes, and leaves plain words alone' {
        ConvertTo-ProcessArgument 'HEAD~1' | Should Be 'HEAD~1'
        ConvertTo-ProcessArgument 'C:\My Projects\PlantA' | Should Be '"C:\My Projects\PlantA"'
        ConvertTo-ProcessArgument 'C:\My Projects\' | Should Be '"C:\My Projects\\"'
        ConvertTo-ProcessArgument 'say "hi"' | Should Be '"say \"hi\""'
        ConvertTo-ProcessArgument '' | Should Be '""'
    }
}
