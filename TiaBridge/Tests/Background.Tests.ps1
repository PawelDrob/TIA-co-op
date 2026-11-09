$here = Split-Path -Parent $MyInvocation.MyCommand.Path
foreach ($f in 'Mcp.ps1', 'Tia.ps1', 'Repo.ps1', 'Rules.ps1', 'Guards.ps1', 'Bridge.ps1', 'Tools\Objects.ps1', 'Tools\Session.ps1', 'Tools\Background.ps1') {
    . (Join-Path $here "..\$f")
}
. (Join-Path $here 'TestBridge.ps1')

# UMAC stand-ins (the V20 signatures: reflection of Siemens.Engineering.dll, 2026-10-30)
if (-not ('Siemens.Engineering.UmacDelegate' -as [type])) {
    Add-Type -TypeDefinition @'
namespace Siemens.Engineering {
    public enum UmacUserType { Project, Global }
    public class UmacCredentials {
        public string Name { get; set; }
        public UmacUserType Type { get; set; }
        public string Password;
        public void SetPassword(System.Security.SecureString s) {
            System.IntPtr b = System.Runtime.InteropServices.Marshal.SecureStringToBSTR(s);
            try { Password = System.Runtime.InteropServices.Marshal.PtrToStringBSTR(b); } finally { System.Runtime.InteropServices.Marshal.ZeroFreeBSTR(b); }
        }
    }
    public delegate void UmacDelegate(UmacCredentials credentials);
}
'@
}

# A protected project asks for the login (umacAsks times, as TIA might after a wrong one); the last credentials are kept.
function Invoke-FakeUmac($Projects, $Umac) {
    if (-not $Umac) { return }
    for ($i = 0; $i -lt $Projects.umacAsks; $i++) {
        $c = New-Object Siemens.Engineering.UmacCredentials
        $Umac.Invoke($c)
        $Projects.credentials = $c
    }
}

# Openness stand-ins: a portal whose Projects open or retrieve a project with no devices, as TIA would, and record the call
function New-FakePortal([string]$Fail = '') {
    $proj = New-Object psobject -Property @{ Name = 'Bg'; Path = $null; IsModified = $false; Devices = @(); DeviceGroups = @(); closed = $false }
    $proj | Add-Member ScriptMethod Close { $this.closed = $true }
    $projects = New-Object psobject -Property @{ project = $proj; fail = $Fail; calls = (New-Object System.Collections.ArrayList); umacAsks = 1; credentials = $null }
    $projects | Add-Member ScriptMethod Retrieve { param($File, $Dir, $Umac)
        [void]$this.calls.Add("Retrieve $($File.FullName) -> $($Dir.FullName)$(if ($Umac) { ' (login)' })"); Invoke-FakeUmac $this $Umac; if ($this.fail) { throw $this.fail }
        $p = Join-Path $Dir.FullName 'Bg\Bg.ap20'; New-Item -ItemType File -Force -Path $p | Out-Null
        $this.project.Path = [System.IO.FileInfo]$p; $this.project }
    $projects | Add-Member ScriptMethod RetrieveWithUpgrade { param($File, $Dir, $Umac)
        [void]$this.calls.Add("RetrieveWithUpgrade $($File.FullName)"); $this.Retrieve($File, $Dir, $Umac) }
    $projects | Add-Member ScriptMethod Open { param($File, $Umac)
        [void]$this.calls.Add("Open $($File.FullName)$(if ($Umac) { ' (login)' })"); Invoke-FakeUmac $this $Umac; if ($this.fail) { throw $this.fail }
        $this.project.Path = $File; $this.project }
    $projects | Add-Member ScriptMethod OpenWithUpgrade { param($File, $Umac)
        [void]$this.calls.Add("OpenWithUpgrade $($File.FullName)"); $this.Open($File, $Umac) }
    $portal = New-Object psobject -Property @{ Projects = $projects; disposed = $false }
    $portal | Add-Member ScriptMethod GetCurrentProcess { New-Object psobject -Property @{ Id = $PID } }   # a running process
    $portal | Add-Member ScriptMethod Dispose { $this.disposed = $true }
    $portal
}

function Initialize-TestBridge([string]$Root) {
    Initialize-BridgeContext @{ projectsRoot = (Join-Path $Root 'projects'); backgroundRoot = (Join-Path $Root 'bg'); tiaRoot = 'C:\none'
                                archivesKept = 10; maxResponseChars = 20000; useTransactions = $true }
}

if (-not ('Siemens.Engineering.ProjectArchivationMode' -as [type])) {
    Add-Type -TypeDefinition 'namespace Siemens.Engineering { public enum ProjectArchivationMode { None, Compressed, DiscardRestorableData, DiscardRestorableDataAndCompressed } }'
}

if (-not ('FakeSiemens.NonRecoverableException' -as [type])) {
    Add-Type -TypeDefinition 'namespace FakeSiemens { public class NonRecoverableException : System.Exception { public NonRecoverableException(string m) : base(m) { } } }'
}

Describe 'Get-BackgroundSource' {
    foreach ($n in 'P.ap20', 'A.zap20', 'Old.zap19', 'Older.ap15_1', 'New.ap21', 'notes.txt') { Set-Content (Join-Path $TestDrive $n) 'x' }

    It 'reads kind and version from the extension; an older version is upgraded' {
        $p = Get-BackgroundSource (Join-Path $TestDrive 'P.ap20')
        $p.kind | Should Be 'project'; $p.version | Should Be 20; $p.upgrade | Should Be $false
        $a = Get-BackgroundSource (Join-Path $TestDrive 'A.zap20')
        $a.kind | Should Be 'archive'; $a.upgrade | Should Be $false
        (Get-BackgroundSource (Join-Path $TestDrive 'Old.zap19')).upgrade | Should Be $true
        $o = Get-BackgroundSource (Join-Path $TestDrive 'Older.ap15_1')
        $o.version | Should Be 15; $o.upgrade | Should Be $true
    }

    It 'refuses a newer version, another file type and a missing file' {
        { Get-BackgroundSource (Join-Path $TestDrive 'New.ap21') } | Should Throw 'cannot open'
        { Get-BackgroundSource (Join-Path $TestDrive 'notes.txt') } | Should Throw 'neither'
        { Get-BackgroundSource (Join-Path $TestDrive 'gone.zap20') } | Should Throw 'not found'
        { Get-BackgroundSource '' } | Should Throw 'path is required'
    }
}

Describe 'background session: export only' {
    It 'refuses every tool but the export ones, before the handler runs' {
        Initialize-TestBridge $TestDrive
        Get-BackgroundRefusal 'import' (New-Object psobject) | Should BeNullOrEmpty   # no background session: unchanged
        $script:Bridge.background = @{ processId = $PID; steps = (New-Object System.Collections.ArrayList); session = (New-SessionState) }
        foreach ($t in 'import', 'delete', 'save', 'archive', 'connect', 'library_edit_type', 'library_release_chain',
                       'library_review', 'library_approve', 'master_copy_to_project', 'master_copy_from_project', 'some_new_tool') {
            Get-BackgroundRefusal $t (New-Object psobject) | Should Match 'refused in a background session'
        }
        foreach ($t in 'tia_status', 'list', 'export', 'full_export', 'probe', 'change_report', 'library_open', 'safety_login', 'background_close') {
            Get-BackgroundRefusal $t (New-Object psobject) | Should BeNullOrEmpty
        }
        # compile changes only the copy, never saved: its PLC software
        Get-BackgroundRefusal 'compile' ([pscustomobject]@{ scope = 'plc' }) | Should BeNullOrEmpty
        Get-BackgroundRefusal 'compile' ([pscustomobject]@{ scope = 'hmi' }) | Should Match 'scope plc or blocks'
        Get-BackgroundRefusal 'library_open' ('{"path":"x.al20","writable":true}' | ConvertFrom-Json) | Should Match 'read-only'

        $script:ran = $false
        $d = Invoke-BridgeTool 'import' { param($a) $script:ran = $true; @{ ok = $true } } (New-Object psobject)
        $script:ran | Should Be $false
        $d.result.ok | Should Be $false
        $d.result.refused | Should Match 'background_close'
    }

    It 'refuses a write that reaches Invoke-TiaWrite' {
        Initialize-TestBridge $TestDrive
        $script:Bridge.background = @{ processId = $PID; steps = (New-Object System.Collections.ArrayList); session = (New-SessionState) }
        { Invoke-TiaWrite 'import of 1 block file(s)' { 'x' } } | Should Throw 'background session'
    }

    It 'times every tool call with memory, and leaves the window session records of the repo alone' {
        Initialize-TestBridge $TestDrive
        $repo = Join-Path $TestDrive 'projects\Bg'
        Write-TextFile (Join-Path $repo '.tiabridge-session.json') '{"pending":{"plc:a":"plc:A"}}'
        $script:Bridge.projectName = 'Bg'; $script:Bridge.projectPath = 'C:\copy\Bg.ap20'; $script:Bridge.repo = $repo
        $script:Bridge.background = @{ processId = $PID; steps = (New-Object System.Collections.ArrayList); session = (New-SessionState) }
        $d = Invoke-BridgeTool 'export' { param($a) @{ ok = $true; items = @() } } (New-Object psobject)
        $d.result.step.step | Should Be 'export'
        $d.result.step.tia.workingSetMB | Should BeGreaterThan 0
        $d.result.step.bridge.peakWorkingSetMB | Should BeGreaterThan 0
        $script:Bridge.background.steps.Count | Should Be 1
        Get-Content (Join-Path $repo '.tiabridge-session.json') -Raw | Should Match 'plc:A'
        Test-WriteAllowed (Get-BridgeSession) | Should Match 'archive'
    }

    It 'says the session is lost when the background TIA is gone, instead of reattaching' {
        Initialize-TestBridge $TestDrive
        $script:Bridge.projectName = 'Bg'; $script:Bridge.projectPath = 'C:\copy\Bg.ap20'
        $script:Bridge.project = New-Object psobject -Property @{ Name = 'Bg' }; $script:Bridge.processId = 999999
        $script:Bridge.background = @{ processId = 999999; steps = (New-Object System.Collections.ArrayList); session = (New-SessionState) }
        { Get-TiaProject } | Should Throw 'background_close'
    }
}

Describe 'Initialize-ProjectRepo for a background session' {
    It 'keeps the project path and last connect of TIA''s project and records the source' {
        $root = Join-Path $TestDrive 'r1'
        $null = Initialize-ProjectRepo -Root $root -ProjectName 'P' -ProjectPath 'C:\P\P.ap20' -PlcDevices @('PLC') -HmiDevices @()
        $before = Get-Content (Join-Path $root 'P\tiabridge.json') -Raw | ConvertFrom-Json
        $m = Initialize-ProjectRepo -Root $root -ProjectName 'P' -ProjectPath 'C:\bg\x\P\P.ap20' -PlcDevices @('PLC') -HmiDevices @() -BackgroundSource 'C:\P\P.ap20'
        $m.pathChanged | Should Be $false
        $cfg = Get-Content (Join-Path $root 'P\tiabridge.json') -Raw | ConvertFrom-Json
        $cfg.projectPath | Should Be 'C:\P\P.ap20'
        $cfg.lastConnect | Should Be $before.lastConnect
        $cfg.lastBackground.source | Should Be 'C:\P\P.ap20'
        # a later connect keeps the record and sees no moved project
        $c = Initialize-ProjectRepo -Root $root -ProjectName 'P' -ProjectPath 'C:\P\P.ap20' -PlcDevices @('PLC') -HmiDevices @()
        $c.pathChanged | Should Be $false
        (Get-Content (Join-Path $root 'P\tiabridge.json') -Raw | ConvertFrom-Json).lastBackground.source | Should Be 'C:\P\P.ap20'
    }

    It 'writes no project path into a new repo, and takes another repo folder when asked' {
        $root = Join-Path $TestDrive 'r2'
        $m = Initialize-ProjectRepo -Root $root -ProjectName 'P' -ProjectPath 'C:\bg\P.ap20' -PlcDevices @() -HmiDevices @() -RepoName 'P-colleague' -BackgroundSource 'D:\P.zap20'
        $m.repo | Should Be (Join-Path $root 'P-colleague')
        $m.created | Should Be $true
        $cfg = Get-Content (Join-Path $root 'P-colleague\tiabridge.json') -Raw | ConvertFrom-Json
        $cfg.projectName | Should Be 'P'
        $cfg.projectPath | Should BeNullOrEmpty
    }
}

Describe 'background_open and background_close' {
    function Import-Openness { }
    function Get-TiaProcesses { $script:fakeProcesses }
    function Test-OpennessGroup { $script:groupRefusal }
    function Start-BackgroundTia { $script:started++; $script:fakePortal }
    function Wait-ProcessExit { $true }
    function Register-PromptGuard { }

    function Reset-Fakes([string]$Fail = '') {
        Initialize-TestBridge $TestDrive
        Remove-Item (Join-Path $TestDrive 'projects\Bg\tiabridge.json') -ErrorAction SilentlyContinue   # these tests open several sources; the repo records one
        $script:fakeProcesses = @(); $script:groupRefusal = $null; $script:started = 0
        $script:fakePortal = New-FakePortal $Fail
    }

    $zap = Join-Path $TestDrive 'in\Bg.zap20'
    New-Item -ItemType Directory -Force -Path (Split-Path $zap) | Out-Null; Set-Content $zap 'zap'

    It 'retrieves an archive into a scratch folder, exports into the project repo, and closes and removes it' {
        Reset-Fakes
        $r = Invoke-BackgroundOpenTool ("{`"path`":`"$($zap -replace '\\', '\\')`"}" | ConvertFrom-Json)
        $r.ok | Should Be $true
        $r.kind | Should Be 'archive'
        @($script:fakePortal.Projects.calls)[0] | Should Match "^Retrieve .*Bg\.zap20 -> .*\\bg\\\d{8}_\d{6}_$PID$"
        @($r.steps | ForEach-Object { $_.step }) -join ',' | Should Be 'start,retrieve,bind'
        $script:Bridge.projectName | Should Be 'Bg'
        $script:Bridge.repo | Should Be (Join-Path $TestDrive 'projects\Bg')
        (Get-Content (Join-Path $script:Bridge.repo 'tiabridge.json') -Raw | ConvertFrom-Json).lastBackground.source | Should Be $zap
        Get-BridgeSession | Should Be $script:Bridge.background.session
        $scratch = $script:Bridge.background.scratch
        Test-Path $scratch | Should Be $true

        $s = Get-BackgroundSummary
        $s.alive | Should Be $true
        $s.source | Should Be $zap

        $c = Invoke-BackgroundCloseTool (New-Object psobject)
        $c.ok | Should Be $true
        $c.tiaEnded | Should Be $true
        $script:fakePortal.Projects.project.closed | Should Be $true
        $script:fakePortal.disposed | Should Be $true
        Test-Path $scratch | Should Be $false
        $script:Bridge.background | Should BeNullOrEmpty
        $script:Bridge.projectName | Should BeNullOrEmpty
        @($c.steps)[-1].step | Should Be 'close'
        Test-Path $c.stepsLog | Should Be $true
        @((Get-Content $c.stepsLog -Raw | ConvertFrom-Json).steps).Count | Should Be 4
    }

    It 'upgrades an older archive, in the retrieved copy' {
        Reset-Fakes
        $old = Join-Path $TestDrive 'in\Bg.zap19'; Set-Content $old 'zap'
        $r = Invoke-BackgroundOpenTool ("{`"path`":`"$($old -replace '\\', '\\')`"}" | ConvertFrom-Json)
        $r.upgraded | Should Be $true
        @($script:fakePortal.Projects.calls)[0] | Should Match '^RetrieveWithUpgrade'
        $null = Invoke-BackgroundCloseTool (New-Object psobject)
    }

    It 'opens a copy of a project, never the original' {
        Reset-Fakes
        $ap = Join-Path $TestDrive 'orig\Bg\Bg.ap20'
        New-Item -ItemType Directory -Force -Path (Split-Path $ap) | Out-Null; Set-Content $ap 'ap'
        Set-Content (Join-Path (Split-Path $ap) 'PEData.plf') 'data'
        $r = Invoke-BackgroundOpenTool ("{`"path`":`"$($ap -replace '\\', '\\')`"}" | ConvertFrom-Json)
        $r.ok | Should Be $true
        @($r.steps | ForEach-Object { $_.step }) -join ',' | Should Be 'start,copy,open,bind'
        $opened = @($script:fakePortal.Projects.calls)[0]
        $opened | Should Match '^Open '
        $opened | Should Not Match ([regex]::Escape($ap))
        $r.copy | Should Match '\\bg\\\d{8}_\d{6}_\d+\\Bg\\Bg\.ap20$'
        Test-Path (Join-Path (Split-Path $r.copy) 'PEData.plf') | Should Be $true
        $null = Invoke-BackgroundCloseTool (New-Object psobject)
        Test-Path (Join-Path (Split-Path $ap) 'PEData.plf') | Should Be $true
    }

    It 'refuses a project open in a TIA, before starting one' {
        Reset-Fakes
        $ap = Join-Path $TestDrive 'orig\Bg\Bg.ap20'
        $script:fakeProcesses = @(@{ processId = 4711; name = 'Bg'; path = $ap.ToUpperInvariant(); mode = 'WithUserInterface' })
        $r = Invoke-BackgroundOpenTool ("{`"path`":`"$($ap -replace '\\', '\\')`"}" | ConvertFrom-Json)
        $r.ok | Should Be $false
        $r.refused | Should Match 'open in TIA \(process 4711\) and locked'
        $script:started | Should Be 0
    }

    It 'refuses without git on PATH, before starting a TIA' {
        Reset-Fakes
        $saved = $env:PATH
        try {
            $env:PATH = "$env:SystemRoot\System32"
            $r = Invoke-BackgroundOpenTool ("{`"path`":`"$($zap -replace '\\', '\\')`"}" | ConvertFrom-Json)
        } finally { $env:PATH = $saved }
        $r.ok | Should Be $false
        $r.refused | Should Match 'git not found on PATH'
        $script:started | Should Be 0
    }

    It 'refuses without the Openness group, before starting a TIA' {
        Reset-Fakes
        $script:groupRefusal = "not in the group 'Siemens TIA Openness'"
        $r = Invoke-BackgroundOpenTool ("{`"path`":`"$($zap -replace '\\', '\\')`"}" | ConvertFrom-Json)
        $r.refused | Should Match 'Siemens TIA Openness'
        $script:started | Should Be 0
    }

    It 'names the failing step with the error and a hint, ends its TIA, removes the copy and keeps the window binding' {
        Reset-Fakes 'The project is protected by UMAC; user authentication is required.'
        Set-BridgeProject -Name 'Window' -Path 'C:\W\Window.ap20' -Repo (Join-Path $TestDrive 'projects\Window')
        $r = Invoke-BackgroundOpenTool ("{`"path`":`"$($zap -replace '\\', '\\')`"}" | ConvertFrom-Json)
        $r.ok | Should Be $false
        $r.step | Should Be 'retrieve'
        $r.error.message | Should Match 'protected by UMAC'
        $r.hint | Should Match 'login prompt'
        $script:fakePortal.disposed | Should Be $true
        @(Get-ChildItem (Join-Path $TestDrive 'bg') -Directory -ErrorAction SilentlyContinue | Where-Object { $_.Name -match "_$PID$" }).Count | Should Be 0
        $script:Bridge.background | Should BeNullOrEmpty
        $script:Bridge.projectName | Should Be 'Window'
        $script:Bridge.projectPath | Should Be 'C:\W\Window.ap20'
    }

    It 'refuses a second background session' {
        Reset-Fakes
        $null = Invoke-BackgroundOpenTool ("{`"path`":`"$($zap -replace '\\', '\\')`"}" | ConvertFrom-Json)
        $r = Invoke-BackgroundOpenTool ("{`"path`":`"$($zap -replace '\\', '\\')`"}" | ConvertFrom-Json)
        $r.refused | Should Match 'background_close first'
        $null = Invoke-BackgroundCloseTool (New-Object psobject)
        (Invoke-BackgroundCloseTool (New-Object psobject)).refused | Should Match 'No background session'
    }

    It 'keeps the copy when asked, and when its TIA does not end' {
        Reset-Fakes
        $null = Invoke-BackgroundOpenTool ("{`"path`":`"$($zap -replace '\\', '\\')`"}" | ConvertFrom-Json)
        $c = Invoke-BackgroundCloseTool ('{"keep_copy":true}' | ConvertFrom-Json)
        Test-Path $c.copy | Should Be $true

        Reset-Fakes
        function Wait-ProcessExit { $false }
        $null = Invoke-BackgroundOpenTool ("{`"path`":`"$($zap -replace '\\', '\\')`"}" | ConvertFrom-Json)
        $scratch = $script:Bridge.background.scratch
        $c = Invoke-BackgroundCloseTool (New-Object psobject)
        $c.tiaEnded | Should Be $false
        $c.note | Should Match 'did not end'
        Test-Path $scratch | Should Be $true
    }
}

Describe 'background session: progress lines and the plain export folder' {
    function Import-Openness { }
    function Get-TiaProcesses { @() }
    function Test-OpennessGroup { $null }
    function Start-BackgroundTia { $script:fakePortal }
    function Wait-ProcessExit { $true }
    function Register-PromptGuard { }
    function Write-BridgeLog([string]$Text) { [void]$script:logLines.Add($Text) }
    # the progress lines since the last reset, as "event step state [pid] [upgrade]"
    function Get-StepLines {
        @($script:logLines | Where-Object { $_ -like 'progress {*' } | ForEach-Object {
            $p = $_.Substring(9) | ConvertFrom-Json
            (@($p.event, $p.step, $p.state) + @($(if ($p.pid) { 'pid' }), $(if ($p.upgrade) { 'upgrade' })) | Where-Object { $_ }) -join ' '
        })
    }
    function Reset-Fakes([string]$Fail = '') {
        Initialize-TestBridge $TestDrive
        Remove-Item (Join-Path $TestDrive 'projects\Bg\tiabridge.json') -ErrorAction SilentlyContinue   # these tests open several sources; the repo records one
        $script:fakePortal = New-FakePortal $Fail
        $script:logLines = New-Object System.Collections.ArrayList
    }
    $zap = Join-Path $TestDrive 'in\Bg.zap19'
    New-Item -ItemType Directory -Force -Path (Split-Path $zap) | Out-Null; Set-Content $zap 'zap'
    $open = "{`"path`":`"$($zap -replace '\\', '\\')`"}"

    It 'says each step before its Openness call and after it, and the TIA pid as soon as it is known' {
        Reset-Fakes
        $r = Invoke-BackgroundOpenTool ($open | ConvertFrom-Json)
        $r.ok | Should Be $true
        $null = Invoke-BackgroundCloseTool (New-Object psobject)
        (Get-StepLines) -join '|' | Should Be ('step start start|tia pid|step start done pid|step retrieve start pid upgrade|step retrieve done pid|' +
                                               'step bind start pid|step bind done pid|step close start pid|step close done pid')
        $line = @($script:logLines | Where-Object { $_ -like 'progress {"event":"step","step":"retrieve","state":"done"*' })[0]
        ($line.Substring(9) | ConvertFrom-Json).ms | Should Not BeNullOrEmpty
    }

    It 'says which step failed, then closes' {
        Reset-Fakes 'The project is protected by UMAC.'
        $r = Invoke-BackgroundOpenTool ($open | ConvertFrom-Json)
        $r.ok | Should Be $false
        (Get-StepLines) -join '|' | Should Be 'step start start|tia pid|step start done pid|step retrieve start pid upgrade|step retrieve failed pid|step close start pid|step close done pid'
    }

    It 'exports into a plain folder: tiabridge.json, no git, no skeleton, no change_report' {
        Reset-Fakes
        $r = Invoke-BackgroundOpenTool ("{`"path`":`"$($zap -replace '\\', '\\')`",`"repo`":`"cache-1`",`"plain`":true}" | ConvertFrom-Json)
        $r.ok | Should Be $true
        $r.plain | Should Be $true
        $r.repoCreated | Should Be $true
        $r.next | Should Match 'no git'
        $repo = Join-Path $TestDrive 'projects\cache-1'
        $script:Bridge.repo | Should Be $repo
        @(Get-ChildItem -LiteralPath $repo -Force | ForEach-Object Name) -join ',' | Should Be 'tiabridge.json'
        (Get-BackgroundRefusal 'change_report' (New-Object psobject)) | Should Match 'plain export folder'
        Get-BackgroundRefusal 'full_export' (New-Object psobject) | Should BeNullOrEmpty
        $d = Invoke-BridgeTool 'export' { param($a) @{ ok = $true; items = @() } } (New-Object psobject)
        Test-Path (Join-Path $repo $d.result.log) | Should Be $true
        $null = Invoke-BackgroundCloseTool (New-Object psobject)
        Test-Path (Join-Path $repo '.git') | Should Be $false
    }

    It 'binds the plain folder the caller names, never the repo of a project with the same name' {
        Reset-Fakes
        # the real project's repo: an upgraded .zap19 opens under the same name (Bg here)
        $real = Join-Path $TestDrive 'projects\Bg'
        $null = Initialize-ProjectRepo -Root (Join-Path $TestDrive 'projects') -ProjectName 'Bg' -ProjectPath 'C:\P\Bg.ap20' -PlcDevices @() -HmiDevices @()
        $before = Get-Content (Join-Path $real 'tiabridge.json') -Raw
        $r = Invoke-BackgroundOpenTool ("{`"path`":`"$($zap -replace '\\', '\\')`",`"repo`":`"run-7`",`"plain`":true}" | ConvertFrom-Json)
        $r.ok | Should Be $true
        $script:Bridge.projectName | Should Be 'Bg'
        $script:Bridge.repo | Should Be (Join-Path $TestDrive 'projects\run-7')
        $null = Invoke-BackgroundCloseTool (New-Object psobject)
        Get-Content (Join-Path $real 'tiabridge.json') -Raw | Should Be $before
        Test-Path (Join-Path $TestDrive 'projects\run-7\.git') | Should Be $false
    }

    It 'refuses plain without repo, with a path, or into a project repo, before starting a TIA' {
        Reset-Fakes
        $script:started = 0
        function Start-BackgroundTia { $script:started++; $script:fakePortal }
        $null = Initialize-ProjectRepo -Root (Join-Path $TestDrive 'projects') -ProjectName 'Bg' -ProjectPath 'C:\P\Bg.ap20' -PlcDevices @() -HmiDevices @()
        $p = $zap -replace '\\', '\\'
        (Invoke-BackgroundOpenTool ("{`"path`":`"$p`",`"plain`":true}" | ConvertFrom-Json)).refused | Should Match 'needs repo'
        (Invoke-BackgroundOpenTool ("{`"path`":`"$p`",`"plain`":true,`"repo`":`" `"}" | ConvertFrom-Json)).refused | Should Match 'needs repo'
        (Invoke-BackgroundOpenTool ("{`"path`":`"$p`",`"plain`":true,`"repo`":`"..`"}" | ConvertFrom-Json)).refused | Should Match 'not a path'
        (Invoke-BackgroundOpenTool ("{`"path`":`"$p`",`"plain`":true,`"repo`":`"C:\\x`"}" | ConvertFrom-Json)).refused | Should Match 'not a path'
        (Invoke-BackgroundOpenTool ("{`"path`":`"$p`",`"plain`":true,`"repo`":`"Bg`"}" | ConvertFrom-Json)).refused | Should Match 'is a project repo \(\.git\)'
        $script:started | Should Be 0
        { Initialize-ProjectRepo -Root (Join-Path $TestDrive 'projects') -ProjectName 'Bg' -ProjectPath 'C:\x' -PlcDevices @() -HmiDevices @() -Plain } | Should Throw 'no fallback'
    }

    foreach ($name in '.', '..', 'a\..\..', 'x.') {
        foreach ($plain in $false, $true) {
            It "refuses repo '$name' (plain $plain) before starting a TIA" {
                Reset-Fakes
                $script:started = 0
                function Start-BackgroundTia { $script:started++; $script:fakePortal }
                $r = Invoke-BackgroundOpenTool (New-Object psobject -Property @{ path = $zap; repo = $name; plain = $plain })
                $r.refused | Should Match 'plain folder name'
                $script:started | Should Be 0
                $script:Bridge.background | Should BeNullOrEmpty
                Test-Path (Join-Path $TestDrive '.git') | Should Be $false
                Test-Path (Join-Path $TestDrive 'projects\.git') | Should Be $false
            }
        }
    }

    It 'still opens with repo left out or empty: the project name is the folder' {
        Reset-Fakes
        $r = Invoke-BackgroundOpenTool (New-Object psobject -Property @{ path = $zap; repo = '' })
        $r.ok | Should Be $true
        $script:Bridge.repo | Should Be (Join-Path $TestDrive 'projects\Bg')
        $null = Invoke-BackgroundCloseTool (New-Object psobject)
    }

    It 'refuses plain with write, before starting a TIA' {
        Reset-Fakes
        $ap = Join-Path $TestDrive 'in\Bg.ap20'; Set-Content $ap 'ap'
        $r = Invoke-BackgroundOpenTool ("{`"path`":`"$($ap -replace '\\', '\\')`",`"write`":true,`"plain`":true}" | ConvertFrom-Json)
        $r.refused | Should Match 'plain=true is for export only'
        @(Get-StepLines).Count | Should Be 0
    }
}

Describe 'background_open export only: a repo that records another path' {
    function Import-Openness { }
    function Get-TiaProcesses { @() }
    function Test-OpennessGroup { $null }
    function Start-BackgroundTia { $script:started++; $script:fakePortal }
    function Wait-ProcessExit { $true }
    function Register-PromptGuard { }

    $script:caseNo = 0
    # every test its own projects root: the fake project is always called Bg
    function Reset-Fakes {
        $script:caseNo++
        Initialize-TestBridge (Join-Path $TestDrive "case$($script:caseNo)")
        $script:root = $script:Bridge.settings.projectsRoot
        $script:started = 0
        $script:fakePortal = New-FakePortal
    }
    function Open-Export([string]$Path, [hashtable]$More = @{}) {
        $a = @{ path = $Path }
        foreach ($k in $More.Keys) { $a[$k] = $More[$k] }
        Invoke-BackgroundOpenTool ([pscustomobject]$a)
    }
    function New-Source([string]$Rel) {
        $f = Join-Path $TestDrive $Rel
        New-Item -ItemType Directory -Force -Path (Split-Path $f) | Out-Null; Set-Content $f 'x'
        $f
    }
    $zap = New-Source 'in\Bg.zap20'
    $zap2 = New-Source 'other\Bg.zap20'
    $ap = New-Source 'orig\Bg\Bg.ap20'

    It 'refuses the repo named after the project when it records the project elsewhere, before a TIA starts, and leaves it alone' {
        Reset-Fakes
        $null = Initialize-ProjectRepo -Root $script:root -ProjectName 'Bg' -ProjectPath 'C:\P\Bg.ap20' -PlcDevices @() -HmiDevices @()
        $before = Get-Content (Join-Path $script:root 'Bg\tiabridge.json') -Raw
        $r = Open-Export $zap
        $r.ok | Should Be $false
        $r.refused | Should Match ([regex]::Escape('C:\P\Bg.ap20'))
        $r.refused | Should Match ([regex]::Escape($zap))
        $r.refused | Should Match 'repo: '
        $script:started | Should Be 0
        Get-Content (Join-Path $script:root 'Bg\tiabridge.json') -Raw | Should Be $before
    }

    It 'refuses a repo named in repo just the same, and moved does not open it' {
        Reset-Fakes
        $null = Initialize-ProjectRepo -Root $script:root -ProjectName 'Bg' -ProjectPath 'C:\P\Bg.ap20' -PlcDevices @() -HmiDevices @()
        (Open-Export $zap @{ repo = 'Bg' }).refused | Should Match ([regex]::Escape('C:\P\Bg.ap20'))
        (Open-Export $zap @{ moved = $true }).refused | Should Match ([regex]::Escape('C:\P\Bg.ap20'))
        $script:started | Should Be 0
    }

    It 'refuses a repo that only an earlier export-only session recorded, for another source' {
        Reset-Fakes
        (Open-Export $zap).ok | Should Be $true
        $null = Invoke-BackgroundCloseTool (New-Object psobject)
        $r = Open-Export $zap2
        $r.refused | Should Match ([regex]::Escape($zap))
        $r.refused | Should Match ([regex]::Escape($zap2))
        $script:started | Should Be 1
    }

    It 'goes on with a repo that does not exist yet, and again with the source it records' {
        Reset-Fakes
        (Open-Export $zap).ok | Should Be $true
        $null = Invoke-BackgroundCloseTool (New-Object psobject)
        (Open-Export $zap).ok | Should Be $true
        $script:Bridge.repo | Should Be (Join-Path $script:root 'Bg')
        $null = Invoke-BackgroundCloseTool (New-Object psobject)
    }

    It 'goes on with a copy of the project file the repo records, and keeps that path' {
        Reset-Fakes
        $null = Initialize-ProjectRepo -Root $script:root -ProjectName 'Bg' -ProjectPath $ap -PlcDevices @() -HmiDevices @()
        (Open-Export $ap).ok | Should Be $true
        $null = Invoke-BackgroundCloseTool (New-Object psobject)
        (Read-RepoConfig (Join-Path $script:root 'Bg')).projectPath | Should Be $ap
    }

    It 'goes on into the repo the caller names, and the project repo stays as it was' {
        Reset-Fakes
        $null = Initialize-ProjectRepo -Root $script:root -ProjectName 'Bg' -ProjectPath 'C:\P\Bg.ap20' -PlcDevices @() -HmiDevices @()
        $before = Get-Content (Join-Path $script:root 'Bg\tiabridge.json') -Raw
        (Open-Export $zap @{ repo = 'Bg-archive' }).ok | Should Be $true
        $script:Bridge.repo | Should Be (Join-Path $script:root 'Bg-archive')
        $null = Invoke-BackgroundCloseTool (New-Object psobject)
        Get-Content (Join-Path $script:root 'Bg\tiabridge.json') -Raw | Should Be $before
    }

    It 'refuses an archive in the project''s repo although it once took an export of that archive: the project path decides' {
        Reset-Fakes
        (Open-Export $zap).ok | Should Be $true
        $null = Invoke-BackgroundCloseTool (New-Object psobject)
        # a connect takes over the repo; lastBackground stays
        $null = Initialize-ProjectRepo -Root $script:root -ProjectName 'Bg' -ProjectPath 'C:\P\Bg.ap20' -PlcDevices @() -HmiDevices @()
        (Read-RepoConfig (Join-Path $script:root 'Bg')).lastBackground.source | Should Be $zap
        (Open-Export $zap).refused | Should Match ([regex]::Escape('C:\P\Bg.ap20'))
    }

    It 'catches an archive whose file name is not the project''s once TIA has opened it, ends that TIA and leaves the repo alone' {
        Reset-Fakes
        $null = Initialize-ProjectRepo -Root $script:root -ProjectName 'Bg' -ProjectPath 'C:\P\Bg.ap20' -PlcDevices @() -HmiDevices @()
        $before = Get-Content (Join-Path $script:root 'Bg\tiabridge.json') -Raw
        $named = New-Source 'in\tia-co-op-Bg-2026-10-06_093214.zap20'
        $r = Open-Export $named
        $r.ok | Should Be $false
        $r.step | Should Be 'bind'
        $r.error.message | Should Match ([regex]::Escape('C:\P\Bg.ap20'))
        $r.error.message | Should Match ([regex]::Escape($named))
        $r.error.message | Should Match 'repo: '
        $script:fakePortal.disposed | Should Be $true
        $script:Bridge.background | Should BeNullOrEmpty
        Get-Content (Join-Path $script:root 'Bg\tiabridge.json') -Raw | Should Be $before
    }

    It 'takes the one repo that records the source when the project''s name belongs to another path, as connect does' {
        Reset-Fakes
        $null = Initialize-ProjectRepo -Root $script:root -ProjectName 'Bg' -ProjectPath 'C:\P\Bg.ap20' -PlcDevices @() -HmiDevices @()
        (Open-Export $zap @{ repo = 'Bg-archive' }).ok | Should Be $true
        $null = Invoke-BackgroundCloseTool (New-Object psobject)
        $r = Open-Export $zap
        $r.ok | Should Be $true
        $script:Bridge.repo | Should Be (Join-Path $script:root 'Bg-archive')
        $r.repoByPath | Should Match 'Bg-archive'
        $null = Invoke-BackgroundCloseTool (New-Object psobject)
    }

    It 'never takes a plain export folder for the repo of the source' {
        Reset-Fakes
        $null = Initialize-ProjectRepo -Root $script:root -ProjectName 'Bg' -ProjectPath 'C:\P\Bg.ap20' -PlcDevices @() -HmiDevices @()
        (Open-Export $zap @{ repo = 'export'; plain = $true }).ok | Should Be $true
        $null = Invoke-BackgroundCloseTool (New-Object psobject)
        (Open-Export $zap).refused | Should Match ([regex]::Escape('C:\P\Bg.ap20'))
        Test-Path (Join-Path $script:root 'export\.git') | Should Be $false
    }

    It 'leaves a plain export folder out of it: another source goes on' {
        Reset-Fakes
        (Open-Export $zap @{ repo = 'export'; plain = $true }).ok | Should Be $true
        $null = Invoke-BackgroundCloseTool (New-Object psobject)
        (Open-Export $zap2 @{ repo = 'export'; plain = $true }).ok | Should Be $true
        (Read-RepoConfig (Join-Path $script:root 'export')).lastBackground.source | Should Be $zap2
        $null = Invoke-BackgroundCloseTool (New-Object psobject)
    }
}

Describe 'background session: the login of a protected project' {
    function Import-Openness { }
    function Get-TiaProcesses { @() }
    function Test-OpennessGroup { $null }
    function Start-BackgroundTia { $script:started++; $script:fakePortal }
    function Wait-ProcessExit { $true }
    function Register-PromptGuard { }
    function Reset-Fakes([string]$Fail = '') {
        Initialize-TestBridge $TestDrive
        $script:fakePortal = New-FakePortal $Fail
        $script:started = 0
    }
    $zap = Join-Path $TestDrive 'in\Bg.zap20'
    New-Item -ItemType Directory -Force -Path (Split-Path $zap) | Out-Null; Set-Content $zap 'zap'
    $ap = Join-Path $TestDrive 'in\Old\Bg.ap19'
    New-Item -ItemType Directory -Force -Path (Split-Path $ap) | Out-Null; Set-Content $ap 'ap'
    # background_open through the dispatch with stderr captured: the dispatch result plus stderr
    function Open-Plain([string]$Path, [hashtable]$More) {
        $a = [ordered]@{ path = $Path; plain = $true; repo = 'cache-1' }
        foreach ($k in $More.Keys) { $a[$k] = $More[$k] }
        $sw = New-Object System.IO.StringWriter
        $old = [Console]::Error
        [Console]::SetError($sw)
        try { $d = Invoke-BridgeTool 'background_open' { param($x) Invoke-BackgroundOpenTool $x } ([pscustomobject]$a) }
        finally { [Console]::SetError($old) }
        $d.stderr = $sw.ToString()
        $d
    }

    It 'answers the login with the user, password and user type passed in; none of them in the result, log or stderr' {
        Reset-Fakes
        $d = Open-Plain $zap @{ umc_user = 'op.anna'; umc_password = 'Zz-9431' }
        $d.result.ok | Should Be $true
        $script:fakePortal.Projects.calls[0] | Should Match 'Retrieve .* \(login\)$'
        $c = $script:fakePortal.Projects.credentials
        $c.Name | Should Be 'op.anna'
        $c.Password | Should Be 'Zz-9431'
        [string]$c.Type | Should Be 'Project'
        $d.result.umcLogin.userType | Should Be 'Project'
        $d.result.umcLogin.asked | Should Be 1
        $log = Get-Content (Join-Path $TestDrive "projects\cache-1\$($d.result.log)") -Raw
        foreach ($t in $d.text, $log, $d.stderr) { $t | Should Not Match 'Zz-9431|op\.anna' }
        $d.stderr | Should Match 'project login passed in \(Project user\)'
        $null = Invoke-BackgroundCloseTool (New-Object psobject)
    }

    It 'takes a UMC user with umc_global, also for an upgrading open of a project copy' {
        Reset-Fakes
        $d = Open-Plain $ap @{ umc_user = 'DOM\op'; umc_password = 'Zz-9431'; umc_global = $true }
        $d.result.ok | Should Be $true
        $d.result.upgraded | Should Be $true
        ($script:fakePortal.Projects.calls -join '|') | Should Match 'OpenWithUpgrade .*\|Open .* \(login\)'
        [string]$script:fakePortal.Projects.credentials.Type | Should Be 'Global'
        $d.result.umcLogin.userType | Should Be 'Global'
        $null = Invoke-BackgroundCloseTool (New-Object psobject)
    }

    It 'says so when the project did not ask for the login' {
        Reset-Fakes
        $script:fakePortal.Projects.umacAsks = 0
        $d = Open-Plain $zap @{ umc_user = 'op.anna'; umc_password = 'Zz-9431' }
        $d.result.umcLogin.asked | Should Be 0
        $null = Invoke-BackgroundCloseTool (New-Object psobject)
    }

    It 'names a login that is not accepted, hides it in the Siemens text, and stops answering a login asked again and again' {
        Reset-Fakes 'The project is protected. User op.anna is not authorized (password Zz-9431).'
        $d = Open-Plain $zap @{ umc_user = 'op.anna'; umc_password = 'Zz-9431' }
        $d.result.ok | Should Be $false
        $d.result.hint | Should Match 'login was not accepted.*umc_global: false'
        $d.result.error.message | Should Be 'The project is protected. User <umc user> is not authorized (password ***).'
        foreach ($t in $d.text, $d.stderr) { $t | Should Not Match 'Zz-9431|op\.anna' }

        Reset-Fakes
        $script:fakePortal.Projects.umacAsks = 4
        $d = Open-Plain $zap @{ umc_user = 'op.anna'; umc_password = 'Zz-9431' }
        $d.result.ok | Should Be $false
        ((@($d.result.error.message) + @($d.result.error.inner | ForEach-Object { $_.message })) -join ' ') | Should Match 'asked for the project login 4 times'
        $d.result.umcLogin.asked | Should Be 4
    }

    It 'tells a plain session without a login how a tool passes one' {
        Reset-Fakes 'The project is protected. You are not authorized to open the project in write mode.'
        $d = Open-Plain $zap @{}
        $d.result.hint | Should Match 'umc_user and umc_password'
    }

    It 'refuses the login outside a plain session, and a half one, before starting a TIA' {
        Reset-Fakes
        $p = $zap -replace '\\', '\\'
        (Invoke-BackgroundOpenTool ("{`"path`":`"$p`",`"umc_user`":`"a`",`"umc_password`":`"b`"}" | ConvertFrom-Json)).refused | Should Match 'plain session'
        (Invoke-BackgroundOpenTool ("{`"path`":`"$p`",`"umc_global`":true}" | ConvertFrom-Json)).refused | Should Match 'umc_global are for a tool'
        (Invoke-BackgroundOpenTool ("{`"path`":`"$p`",`"plain`":true,`"repo`":`"c`",`"umc_password`":`"b`"}" | ConvertFrom-Json)).refused | Should Match 'needs umc_user'
        (Invoke-BackgroundOpenTool ("{`"path`":`"$p`",`"plain`":true,`"repo`":`"c`",`"umc_user`":`"a`"}" | ConvertFrom-Json)).refused | Should Match 'needs umc_password'
        $script:started | Should Be 0
    }
}

Describe 'background session: write mode' {
    function Import-Openness { }
    function Get-TiaProcesses { $script:fakeProcesses }
    function Test-OpennessGroup { $null }
    function Start-BackgroundTia { $script:started++; $script:fakePortal }
    function Wait-ProcessExit { $true }
    function Register-PromptGuard { $script:guarded++; if ($script:guardFail) { throw $script:guardFail } }
    function Invoke-ProjectArchive { Register-Archive (Get-BridgeSession); @{ ok = $true; file = 'archives\tia-co-op-Bg.zap20' } }

    function Reset-Fakes([string]$Fail = '') {
        Initialize-TestBridge $TestDrive
        $script:fakeProcesses = @(); $script:started = 0; $script:guarded = 0; $script:guardFail = $null
        $script:fakePortal = New-FakePortal $Fail
    }
    function Open-Write([string]$Path) { Invoke-BackgroundOpenTool ("{`"path`":`"$($Path -replace '\\', '\\')`",`"write`":true}" | ConvertFrom-Json) }

    $ap = Join-Path $TestDrive 'real\Bg\Bg.ap20'
    New-Item -ItemType Directory -Force -Path (Split-Path $ap) | Out-Null; Set-Content $ap 'ap'

    It 'runs the writes of a connect session, but not connect, a writable library or an unknown tool' {
        Initialize-TestBridge $TestDrive
        $script:Bridge.background = @{ write = $true; processId = $PID; steps = (New-Object System.Collections.ArrayList); session = (New-SessionState) }
        foreach ($t in 'import', 'delete', 'compile', 'save', 'archive', 'export', 'list', 'change_report', 'library_edit_type', 'library_release_type',
                       'library_update_usages', 'library_review', 'library_approve', 'library_release_chain', 'master_copy_to_project',
                       'master_copy_from_project', 'background_close') {
            Get-BackgroundRefusal $t (New-Object psobject) | Should BeNullOrEmpty
        }
        foreach ($t in 'connect', 'some_new_tool') { Get-BackgroundRefusal $t (New-Object psobject) | Should Match 'write mode' }
        Get-BackgroundRefusal 'library_open' ('{"path":"x.al20","writable":true}' | ConvertFrom-Json) | Should Match 'read-only'
    }

    It 'lets a write through Invoke-TiaWrite' {
        Initialize-TestBridge $TestDrive
        $script:Bridge.settings.useTransactions = $false
        $script:Bridge.projectName = 'Bg'; $script:Bridge.projectPath = $ap; $script:Bridge.processId = $PID
        $script:Bridge.project = New-Object psobject -Property @{ Name = 'Bg' }
        $portal = New-Object psobject
        $portal | Add-Member ScriptMethod ExclusiveAccess { param($t) $ea = New-Object psobject; $ea | Add-Member ScriptMethod Dispose { }; $ea }
        $script:Bridge.portal = $portal
        $script:Bridge.background = @{ write = $true; processId = $PID; steps = (New-Object System.Collections.ArrayList); session = (New-SessionState) }
        (Invoke-TiaWrite 'import of 1 block file(s)' { 'done' }).output | Should Be 'done'
    }

    It 'opens the project file itself, archives it first, and closes it without removing it' {
        Reset-Fakes
        $r = Open-Write $ap
        $r.ok | Should Be $true
        $r.write | Should Be $true
        $script:guarded | Should Be 1
        @($script:fakePortal.Projects.calls)[0] | Should Be "Open $ap"
        $r.projectPath | Should Be $ap
        $r.copy | Should BeNullOrEmpty
        @($r.steps | ForEach-Object { $_.step }) -join ',' | Should Be 'start,open,bind,archive'
        $r.archive.ok | Should Be $true
        $r.session.writesAllowed | Should Be $true
        @(Get-ChildItem (Join-Path $TestDrive 'bg') -Directory -ErrorAction SilentlyContinue | Where-Object { $_.Name -match "_$PID$" }).Count | Should Be 0
        (Get-BackgroundSummary).write | Should Be $true

        $c = Invoke-BackgroundCloseTool (New-Object psobject)
        $c.ok | Should Be $true
        $c.discarded | Should Be $false
        $script:fakePortal.Projects.project.closed | Should Be $true
        $script:fakePortal.disposed | Should Be $true
        Test-Path $ap | Should Be $true
        $script:Bridge.background | Should BeNullOrEmpty
    }

    It 'refuses a project file whose repo belongs to another path, before starting a TIA, and leaves the repo alone' {
        Reset-Fakes
        $root = Join-Path $TestDrive 'projects'
        $null = Initialize-ProjectRepo -Root $root -ProjectName 'Other' -ProjectPath 'C:\P\Other.ap20' -PlcDevices @() -HmiDevices @()
        $before = Get-Content (Join-Path $root 'Other\tiabridge.json') -Raw
        $file = Join-Path $TestDrive 'real\Other\Other.ap20'
        New-Item -ItemType Directory -Force -Path (Split-Path $file) | Out-Null; Set-Content $file 'ap'
        $r = Open-Write $file
        $r.ok | Should Be $false
        $r.refused | Should Match ([regex]::Escape('C:\P\Other.ap20'))
        $r.refused | Should Match ([regex]::Escape($file))
        $script:started | Should Be 0
        Get-Content (Join-Path $root 'Other\tiabridge.json') -Raw | Should Be $before
    }

    It 'records the project file''s path in a new repo, so that another path is refused later' {
        Reset-Fakes
        $file = Join-Path $TestDrive 'real\Fresh\Bg.ap20'
        New-Item -ItemType Directory -Force -Path (Split-Path $file) | Out-Null; Set-Content $file 'ap'
        $r = Invoke-BackgroundOpenTool ("{`"path`":`"$($file -replace '\\', '\\')`",`"write`":true,`"repo`":`"Bg-fresh`"}" | ConvertFrom-Json)
        $r.ok | Should Be $true
        $null = Invoke-BackgroundCloseTool (New-Object psobject)
        (Get-Content (Join-Path $TestDrive 'projects\Bg-fresh\tiabridge.json') -Raw | ConvertFrom-Json).projectPath | Should Be $file
    }

    It 'moved=true keeps the repo and records the new path' {
        Reset-Fakes
        $root = Join-Path $TestDrive 'projects'
        $null = Initialize-ProjectRepo -Root $root -ProjectName 'Bg' -ProjectPath 'C:\Old\Bg.ap20' -PlcDevices @() -HmiDevices @() -RepoName 'Bg-moving'
        $file = Join-Path $TestDrive 'moved\Bg\Bg.ap20'
        New-Item -ItemType Directory -Force -Path (Split-Path $file) | Out-Null; Set-Content $file 'ap'
        $r = Invoke-BackgroundOpenTool ("{`"path`":`"$($file -replace '\\', '\\')`",`"write`":true,`"repo`":`"Bg-moving`",`"moved`":true}" | ConvertFrom-Json)
        $r.ok | Should Be $true
        $script:Bridge.repo | Should Be (Join-Path $root 'Bg-moving')
        $r.pathChanged | Should Match ([regex]::Escape('C:\Old\Bg.ap20'))
        $null = Invoke-BackgroundCloseTool (New-Object psobject)
        (Get-Content (Join-Path $root 'Bg-moving\tiabridge.json') -Raw | ConvertFrom-Json).projectPath | Should Be $file
    }

    It 'reports a session archive that ended TIA as TIA ended, and names background_close' {
        Reset-Fakes
        function Invoke-ProjectArchive { throw [System.Management.Automation.MethodInvocationException]::new('outer', [FakeSiemens.NonRecoverableException]::new('Unexpected exception')) }
        $r = Open-Write $ap
        $r.ok | Should Be $false
        $r.tiaEnded | Should Be $true
        $r.note | Should Match 'session archive'
        $r.note | Should Match 'background_close'
        $r.ContainsKey('next') | Should Be $false
        $null = Invoke-BackgroundCloseTool ('{"discard":true}' | ConvertFrom-Json)
    }

    It 'keeps a plain archive failure an ordinary failure, with the retry note' {
        Reset-Fakes
        function Invoke-ProjectArchive { throw 'disk full' }
        function Test-TiaAlive { $true }
        $r = Open-Write $ap
        $r.ok | Should Be $true
        $r.ContainsKey('tiaEnded') | Should Be $false
        $r.note | Should Match 'Retry archive'
        $r.next | Should Match 'Writes are refused'
        $r.next | Should Not Match 'import'
        $null = Invoke-BackgroundCloseTool ('{"discard":true}' | ConvertFrom-Json)
    }

    It 'refuses to close with unsaved changes unless discard=true' {
        Reset-Fakes
        $null = Open-Write $ap
        $script:fakePortal.Projects.project.IsModified = $true
        Register-Write $script:Bridge.background.session 'plc' 'PLC_1' @(@{ name = 'zzTest'; ok = $true })
        $c = Invoke-BackgroundCloseTool (New-Object psobject)
        $c.ok | Should Be $false
        $c.refused | Should Match 'never saves'
        @($c.saveBlockers).Count | Should Be 0
        $c.refused | Should Match 'Save them \(save\)'
        @(@($c.saveStanding)[0].notCompiled) -join ' ' | Should Match 'zzTest'
        $script:fakePortal.disposed | Should Be $false
        $script:Bridge.background | Should Not BeNullOrEmpty

        $c = Invoke-BackgroundCloseTool ('{"discard":true}' | ConvertFrom-Json)
        $c.ok | Should Be $true
        $c.discarded | Should Be $true
        $script:fakePortal.disposed | Should Be $true
        Test-Path $ap | Should Be $true
    }

    It 'discards unsaved changes when the bridge stops' {
        Reset-Fakes
        $null = Open-Write $ap
        $script:fakePortal.Projects.project.IsModified = $true
        Stop-BackgroundOnExit
        $script:fakePortal.disposed | Should Be $true
        $script:Bridge.background | Should BeNullOrEmpty
    }

    It 'refuses an older version, of a project or an archive, before starting a TIA' {
        Reset-Fakes
        $old = Join-Path $TestDrive 'real\Old\Old.ap19'
        New-Item -ItemType Directory -Force -Path (Split-Path $old) | Out-Null; Set-Content $old 'ap'
        (Open-Write $old).refused | Should Match 'does not upgrade'
        $oldZap = Join-Path $TestDrive 'real\Old.zap19'; Set-Content $oldZap 'zap'
        (Open-Write $oldZap).refused | Should Match 'does not upgrade'
        $script:started | Should Be 0
    }

    It 'refuses a project open in a TIA, and says to close it there' {
        Reset-Fakes
        $script:fakeProcesses = @(@{ processId = 4711; name = 'Bg'; path = $ap; mode = 'WithUserInterface' })
        $r = Open-Write $ap
        $r.refused | Should Match 'open in TIA \(process 4711\) and locked'
        $r.refused | Should Match 'close it there first'
        $script:fakeProcesses = @(@{ processId = 4712; name = 'Bg'; path = $ap; mode = 'WithoutUserInterface' })
        (Open-Write $ap).refused | Should Match 'without user interface'
        $script:started | Should Be 0
    }

    It 'gives up when the prompt guard cannot be attached in write mode, and goes on without it in export-only mode' {
        Reset-Fakes
        $script:guardFail = 'no Confirmation event'
        $r = Open-Write $ap
        $r.ok | Should Be $false
        $r.step | Should Be 'start'
        $r.hint | Should Match 'prompt guard'
        $script:fakePortal.disposed | Should Be $true
        $script:Bridge.background | Should BeNullOrEmpty

        Reset-Fakes
        $script:guardFail = 'no Confirmation event'
        $r = Invoke-BackgroundOpenTool ("{`"path`":`"$($ap -replace '\\', '\\')`"}" | ConvertFrom-Json)
        $r.ok | Should Be $true
        $r.promptGuard.message | Should Match 'no Confirmation event'
        $null = Invoke-BackgroundCloseTool (New-Object psobject)
    }
}

Describe 'background session: an archive opened for changes' {
    function Import-Openness { }
    function Get-TiaProcesses { @() }
    function Test-OpennessGroup { $null }
    function Start-BackgroundTia { $script:started++; $script:fakePortal }
    function Wait-ProcessExit { $true }
    function Register-PromptGuard { }
    function Invoke-ProjectArchive { Register-Archive (Get-BridgeSession); @{ ok = $true; file = 'archives\a.zap20' } }

    # The projects root lies in $TestDrive
    $script:TiaPathLimitOfTia = $script:TiaPathLimit
    $script:TiaPathLimit = Get-TestDrivePathLimit $script:TiaPathLimitOfTia
    AfterAll { $script:TiaPathLimit = $script:TiaPathLimitOfTia }

    function Reset-Fakes([string]$Fail = '') {
        Remove-Item (Join-Path $TestDrive 'projects') -Recurse -Force -ErrorAction SilentlyContinue
        Initialize-TestBridge $TestDrive
        $script:started = 0
        $script:fakePortal = New-FakePortal $Fail
    }
    function Open-Archive([string]$Repo = '') {
        $open = @{ path = $zap; write = $true }
        if ($Repo) { $open.repo = $Repo }
        Invoke-BackgroundOpenTool ([pscustomobject]$open)
    }
    New-Item -ItemType Directory -Force -Path (Join-Path $TestDrive 'real') | Out-Null
    $zap = Join-Path $TestDrive 'real\Plant_20261104.zap20'
    Set-Content $zap 'zap'
    $retrieved = Join-Path $TestDrive 'projects\_bridge\retrieved\Plant_20261104'

    It 'retrieves it to a folder of its own that stays, with a repo of the archive''s name, and leaves the archive alone' {
        Reset-Fakes
        $before = (Get-Item $zap).LastWriteTimeUtc
        $r = Open-Archive
        $r.ok | Should Be $true
        $r.write | Should Be $true
        $r.kind | Should Be 'archive'
        $r.retrievedTo | Should Be $retrieved
        $r.projectPath | Should Be (Join-Path $retrieved 'Bg\Bg.ap20')
        $r.reopen | Should Match 'background_open'
        $r.repo | Should BeNullOrEmpty
        $script:Bridge.repo | Should Be (Join-Path $TestDrive 'projects\Plant_20261104')
        $r.session.writesAllowed | Should Be $true
        @($script:fakePortal.Projects.calls)[0] | Should Match ([regex]::Escape("-> $retrieved"))
        (Invoke-BackgroundCloseTool (New-Object psobject)).ok | Should Be $true
        Test-Path (Join-Path $retrieved 'Bg\Bg.ap20') | Should Be $true
        (Get-Item $zap).LastWriteTimeUtc | Should Be $before
    }

    It 'takes folder and repo from repo when the user gives one' {
        Reset-Fakes
        $r = Open-Archive 'Plant-old'
        $r.retrievedTo | Should Be (Join-Path $TestDrive 'projects\_bridge\retrieved\Plant-old')
        $script:Bridge.repo | Should Be (Join-Path $TestDrive 'projects\Plant-old')
        $null = Invoke-BackgroundCloseTool (New-Object psobject)
    }

    It 'refuses a folder that stands, naming its project file, before a TIA starts' {
        Reset-Fakes
        $null = Open-Archive
        $file = $script:Bridge.projectPath
        $null = Invoke-BackgroundCloseTool (New-Object psobject)
        $script:started = 0
        $r = Open-Archive
        $r.refused | Should Match ([regex]::Escape($retrieved))
        $r.refused | Should Match ([regex]::Escape($file))
        $script:started | Should Be 0
    }

    It 'works on its project again by the .ap20, in the same repo' {
        Reset-Fakes
        $null = Open-Archive
        $file = $script:Bridge.projectPath
        $repo = $script:Bridge.repo
        $null = Invoke-BackgroundCloseTool (New-Object psobject)
        $script:fakePortal = New-FakePortal
        $r = Invoke-BackgroundOpenTool ([pscustomobject]@{ path = $file; write = $true })
        $r.ok | Should Be $true
        $script:Bridge.repo | Should Be $repo
        $null = Invoke-BackgroundCloseTool (New-Object psobject)
    }

    It 'leaves nothing that would refuse the next try when the retrieve fails, and quotes TIA with its hint' {
        Reset-Fakes 'The project is protected. You are not authorized to open the project in write mode.'
        $r = Open-Archive
        $r.ok | Should Be $false
        $r.step | Should Be 'retrieve'
        $r.error.message | Should Match 'not authorized'
        $r.hint | Should Match 'protected'
        Test-Path $retrieved | Should Be $false
    }

    It 'refuses a repo of that name that belongs to another project' {
        Reset-Fakes
        $repo = Join-Path $TestDrive 'projects\Plant_20261104'
        New-Item -ItemType Directory -Force -Path $repo | Out-Null
        Set-Content (Join-Path $repo 'tiabridge.json') (ConvertTo-Json @{ projectPath = 'C:\elsewhere\P.ap20' })
        $r = Open-Archive
        $r.refused | Should Match 'records C:'
        $script:started | Should Be 0
        Test-Path $retrieved | Should Be $false
    }

    It 'returns the repo''s standards, with the settings'' template in a new repo, also in an export-only session; a plain folder has none' {
        Reset-Fakes
        $template = Join-Path $TestDrive 'template'
        New-Item -ItemType Directory -Force -Path $template | Out-Null
        Set-Content (Join-Path $template 'zz.md') 'ours'
        $script:Bridge.settings.standardsTemplate = $template
        $r = Open-Archive
        @($r.standards.files) -join ',' | Should Be 'standards\zz.md'
        $null = Invoke-BackgroundCloseTool (New-Object psobject)
        Reset-Fakes
        (Open-Archive).Contains('standards') | Should Be $false
        $null = Invoke-BackgroundCloseTool (New-Object psobject)
        Reset-Fakes
        $script:Bridge.settings.standardsTemplate = $template
        $r = Invoke-BackgroundOpenTool ([pscustomobject]@{ path = $zap; repo = 'Plant-read' })
        @($r.standards.files) -join ',' | Should Be 'standards\zz.md'
        $null = Invoke-BackgroundCloseTool (New-Object psobject)
        Reset-Fakes
        $script:Bridge.settings.standardsTemplate = $template
        $r = Invoke-BackgroundOpenTool ([pscustomobject]@{ path = $zap; repo = 'Plant-plain'; plain = $true })
        $r.Contains('standards') | Should Be $false
        $null = Invoke-BackgroundCloseTool (New-Object psobject)
    }

    It 'says for a path too long what applies to the session' {
        $text = "The specified path' C:\x' (159 character) is too long. A maximum of 143 characters is allowed."
        Reset-Fakes $text
        $r = Open-Archive
        $r.hint | Should Match "at most $script:TiaPathLimit characters"
        $r.hint | Should Match 'with repo'
        Reset-Fakes $text
        $r = Invoke-BackgroundOpenTool ([pscustomobject]@{ path = $zap; repo = 'Plant-read' })
        $r.hint | Should Match 'backgroundRoot'
        $r.hint | Should Not Match 'repo'
        Reset-Fakes $text
        $file = Join-Path $TestDrive 'real\Lies\Lies.ap20'
        New-Item -ItemType Directory -Force -Path (Split-Path $file) | Out-Null; Set-Content $file 'ap'
        $r = Invoke-BackgroundOpenTool ([pscustomobject]@{ path = $file; write = $true })
        $r.hint | Should Match 'opens where it lies'
        $r.hint | Should Not Match 'repo'
    }

    It 'takes its limit from one name' {
        Reset-Fakes
        $saved = $script:TiaPathLimit
        try {
            $script:TiaPathLimit = 40
            (Open-Archive 'Plant').refused | Should Match 'at most 40 characters'
            Get-BackgroundFailureHint @{ type = 't'; message = 'x is too long' } | Should Match 'at most 40 characters'
        }
        finally { $script:TiaPathLimit = $saved }
    }

    It 'refuses a folder that records the source of an export-only session or a plain export' {
        Reset-Fakes
        $repo = Join-Path $TestDrive 'projects\Plant_20261104'
        New-Item -ItemType Directory -Force -Path $repo | Out-Null
        Set-Content (Join-Path $repo 'tiabridge.json') (ConvertTo-Json @{ lastBackground = @{ source = 'C:\elsewhere\Other.zap20' } })
        $r = Open-Archive
        $r.refused | Should Match 'Other\.zap20'
        $script:started | Should Be 0
    }

    It 'says the folder stays when TIA does not end after a failed retrieve' {
        Reset-Fakes 'Unable to retrieve'
        function Wait-ProcessExit { $false }
        $r = Open-Archive
        $r.note | Should Match ([regex]::Escape($retrieved))
        Test-Path $retrieved | Should Be $true
        Remove-Item $retrieved -Recurse -Force
    }

    It 'refuses a name TIA could not retrieve to, or archive under, before a TIA starts' {
        Reset-Fakes
        $r = Open-Archive ('x' * 150)
        $r.refused | Should Match 'too long'
        $r.refused | Should Match 'with repo'
        $script:started | Should Be 0
    }

    It 'refuses what would give a session archive path over the limit, though the retrieve folder fits' {
        Reset-Fakes
        $script:Bridge.settings.projectsRoot = 'C:\r'
        $saved = $script:TiaPathLimit
        try {
            $script:TiaPathLimit = $script:TiaPathLimitOfTia
            $target = Resolve-ArchiveTarget 'C:\a.zap20' ('x' * 110)
            $target.refused | Should Match 'session archive'
        }
        finally { $script:TiaPathLimit = $saved }
    }

    It 'an export-only session on an archive stays as it was' {
        Reset-Fakes
        $r = Invoke-BackgroundOpenTool ([pscustomobject]@{ path = $zap; repo = 'Plant-read' })
        $r.ok | Should Be $true
        $r.write | Should Be $false
        $r.retrievedTo | Should BeNullOrEmpty
        Test-Path $retrieved | Should Be $false
        $null = Invoke-BackgroundCloseTool (New-Object psobject)
    }
}

Describe 'background session: a project TIA marks modified on opening' {
    function Import-Openness { }
    function Get-TiaProcesses { @() }
    function Test-OpennessGroup { $null }
    function Start-BackgroundTia { $script:fakePortal }
    function Wait-ProcessExit { $true }
    function Register-PromptGuard { }

    # SaveFail: Save throws it. SaveKeepsModified: TIA marks the project modified again after the save.
    function Reset-Fakes([bool]$Modified, [string]$SaveFail = '', [switch]$SaveKeepsModified) {
        Initialize-TestBridge $TestDrive
        $script:fakePortal = New-FakePortal
        $script:fakePortal | Add-Member ScriptMethod ExclusiveAccess { param($t) $ea = New-Object psobject; $ea | Add-Member ScriptMethod Dispose { }; $ea }
        $p = $script:fakePortal.Projects.project
        $p.IsModified = $Modified
        $p | Add-Member NoteProperty calls (New-Object System.Collections.ArrayList)
        $p | Add-Member NoteProperty saveFail $SaveFail
        $p | Add-Member NoteProperty keepModified ([bool]$SaveKeepsModified)
        $p | Add-Member ScriptMethod Save { [void]$this.calls.Add('Save'); if ($this.saveFail) { throw $this.saveFail }; if (-not $this.keepModified) { $this.IsModified = $false } }
        $p | Add-Member ScriptMethod Archive { param($Dir, $Name, $Mode) [void]$this.calls.Add('Archive'); Set-Content (Join-Path $Dir.FullName $Name) 'zap' }
        $p
    }
    function Open-Write([string]$Path) { Invoke-BackgroundOpenTool ("{`"path`":`"$($Path -replace '\\', '\\')`",`"write`":true}" | ConvertFrom-Json) }
    function Get-Thrown([scriptblock]$Body) { try { & $Body; '' } catch { $_.Exception.Message } }

    $ap = Join-Path $TestDrive 'real\Bg\Bg.ap20'
    New-Item -ItemType Directory -Force -Path (Split-Path $ap) | Out-Null; Set-Content $ap 'ap'

    It 'saves it, then makes the session archive, and says so' {
        $p = Reset-Fakes $true
        $r = Open-Write $ap
        $r.ok | Should Be $true
        $p.calls -join ',' | Should Be 'Save,Archive'
        $r.savedBeforeArchive | Should Be $true
        $r.note | Should Match 'modified on opening'
        @($r.steps | ForEach-Object { $_.step }) -join ',' | Should Be 'start,open,bind,save,archive'
        $r.archive.ok | Should Be $true
        Test-Path (Join-Path $script:Bridge.repo $r.archive.file) | Should Be $true
        $r.session.writesAllowed | Should Be $true
        $r.next | Should Match 'import, delete, delete_folder, compile, save'
        $null = Invoke-BackgroundCloseTool (New-Object psobject)
    }

    It 'does not save a project that is not modified' {
        $p = Reset-Fakes $false
        $r = Open-Write $ap
        $p.calls -join ',' | Should Be 'Archive'
        $r.ContainsKey('savedBeforeArchive') | Should Be $false
        $r.ContainsKey('note') | Should Be $false
        @($r.steps | ForEach-Object { $_.step }) -join ',' | Should Be 'start,open,bind,archive'
        $null = Invoke-BackgroundCloseTool (New-Object psobject)
    }

    It 'does not save the copy of an export-only session' {
        $p = Reset-Fakes $true
        $r = Invoke-BackgroundOpenTool ("{`"path`":`"$($ap -replace '\\', '\\')`",`"repo`":`"Bg-copy`"}" | ConvertFrom-Json)
        $r.ok | Should Be $true
        $p.calls.Count | Should Be 0
        $r.ContainsKey('savedBeforeArchive') | Should Be $false
        $null = Invoke-BackgroundCloseTool (New-Object psobject)
    }

    It 'when the save fails: no archive, the result says so, writes stay refused' {
        $p = Reset-Fakes $true 'disk full'
        $r = Open-Write $ap
        $r.ok | Should Be $true
        $p.calls -join ',' | Should Be 'Save'
        $r.savedBeforeArchive | Should Be $false
        $r.archive.ok | Should Be $false
        $r.archive.error.message | Should Match 'disk full'
        @($r.steps | ForEach-Object { $_.step }) -join ',' | Should Be 'start,open,bind,save'
        $r.note | Should Match 'writes stay refused'
        $r.note | Should Match 'discard=true'
        $r.note | Should Match 'skip=true'
        $r.session.writesAllowed | Should Be $false
        $r.next | Should Match 'Writes are refused'
        $r.next | Should Not Match 'import'
        $r.next | Should Not Match 'work as under connect'
        $script:Bridge.background.session.archiveSkipped | Should Be $false
        Get-ArchiveRefusal 'import' | Should Match 'session archive'
        $null = Invoke-BackgroundCloseTool ('{"discard":true}' | ConvertFrom-Json)
    }

    It 'reports a save that ended TIA as TIA ended, naming the save' {
        $p = Reset-Fakes $true
        function Invoke-TiaWrite { throw [System.Management.Automation.MethodInvocationException]::new('outer', [FakeSiemens.NonRecoverableException]::new('Unexpected exception')) }
        $r = Open-Write $ap
        $r.ok | Should Be $false
        $r.tiaEnded | Should Be $true
        $r.savedBeforeArchive | Should Be $false
        $r.note | Should Match 'ended at the save before the session archive'
        $r.note | Should Match 'background_close'
        $p.calls.Count | Should Be 0
        $null = Invoke-BackgroundCloseTool ('{"discard":true}' | ConvertFrom-Json)
    }

    It 'keeps writes refused when the project is still modified after the save' {
        $p = Reset-Fakes $true -SaveKeepsModified
        $r = Open-Write $ap
        $p.calls -join ',' | Should Be 'Save'
        $r.savedBeforeArchive | Should Be $true
        $r.archive.ok | Should Be $false
        $r.archive.error.message | Should Match 'still marked modified'
        @($r.steps | ForEach-Object { $_.step }) -join ',' | Should Be 'start,open,bind,save'
        $r.note | Should Match 'did not clear'
        $r.note | Should Match 'discard=true'
        $r.note | Should Not Match 'Retry archive'
        $r.note | Should Not Match 'to make the session archive possible'
        $r.session.writesAllowed | Should Be $false
        $null = Invoke-BackgroundCloseTool ('{"discard":true}' | ConvertFrom-Json)
    }

    It 'offers the retry when the save cleared it and only the archive failed' {
        $p = Reset-Fakes $true
        $p | Add-Member ScriptMethod -Force Archive { param($Dir, $Name, $Mode) [void]$this.calls.Add('Archive'); throw 'disk full' }
        $r = Open-Write $ap
        $p.calls -join ',' | Should Be 'Save,Archive'
        $r.savedBeforeArchive | Should Be $true
        $r.archive.ok | Should Be $false
        $r.note | Should Match 'saved it'
        $r.note | Should Match 'Retry archive'
        $null = Invoke-BackgroundCloseTool ('{"discard":true}' | ConvertFrom-Json)
    }

    # save is refused by the archive gate here, so close must not send anyone to it
    It 'background_close without the session archive names discard=true and the skip, not save' {
        $p = Reset-Fakes $true 'disk full'
        $null = Open-Write $ap
        $c = Invoke-BackgroundCloseTool (New-Object psobject)
        $c.ok | Should Be $false
        $c.refused | Should Match 'never saves'
        $c.refused | Should Match 'discard=true'
        $c.refused | Should Match 'skip=true'
        $c.refused | Should Match 'user says'
        $c.refused | Should Not Match '\(save'
        $c.refused | Should Not Match 'Save them'
        $script:fakePortal.disposed | Should Be $false
        $c = Invoke-BackgroundCloseTool ('{"discard":true}' | ConvertFrom-Json)
        $c.ok | Should Be $true
        $c.discarded | Should Be $true
    }

    It 'background_close with a skipped session archive names save again: the gate is open' {
        $p = Reset-Fakes $true 'disk full'
        $null = Open-Write $ap
        $null = Invoke-ArchiveTool ('{"reason":"the user said so","skip":true}' | ConvertFrom-Json)
        (Invoke-BackgroundCloseTool (New-Object psobject)).refused | Should Match 'Save them \(save, after a clean compile'
        $null = Invoke-BackgroundCloseTool ('{"discard":true}' | ConvertFrom-Json)
    }

    It 'archive without the session archive: never saves, and names what works in a session without a window' {
        $p = Reset-Fakes $true 'disk full'
        $null = Open-Write $ap
        $p.calls.Clear()
        $m = Get-Thrown { Invoke-ArchiveTool ('{"reason":"x"}' | ConvertFrom-Json) }
        $m | Should Match 'unsaved changes'
        $m | Should Match 'discard=true'
        $m | Should Match 'background_open'
        $m | Should Match 'skip=true'
        $m | Should Not Match 'save in TIA'
        $m | Should Not Match 'use save'
        $p.calls.Count | Should Be 0
        $null = Invoke-BackgroundCloseTool ('{"discard":true}' | ConvertFrom-Json)
    }

    It 'archive with the session archive made: a later change is not saved for it, and save is what works' {
        $p = Reset-Fakes $false
        $null = Open-Write $ap
        $p.calls.Clear()
        $p.IsModified = $true
        $m = Get-Thrown { Invoke-ArchiveTool ('{"reason":"x"}' | ConvertFrom-Json) }
        $m | Should Match 'Use save'
        $m | Should Not Match 'background_open'
        $p.calls.Count | Should Be 0
        $null = Invoke-BackgroundCloseTool ('{"discard":true}' | ConvertFrom-Json)
    }
}

Describe 'prompt guard' {
    Add-Type -TypeDefinition @'
namespace TiaBridgeTest {
    [System.Flags] public enum Choices { None = 0, Ok = 1, Yes = 2, YesToAll = 4, Abort = 8, Retry = 16, Ignore = 32, No = 64, NoToAll = 128, Cancel = 256 }
    public enum Results { Ok, Yes, YesToAll, Abort, Retry, Ignore, No, NoToAll, Cancel }
    public class ConfirmArgs : System.EventArgs {
        public string Caption { get; set; } public string Text { get; set; } public string DetailText { get; set; }
        public Choices Choices { get; set; } public Results Result { get; set; } public bool IsHandled { get; set; }
    }
    public class NoteArgs : System.EventArgs {
        public string Caption { get; set; } public string Text { get; set; } public string DetailText { get; set; } public bool IsHandled { get; set; }
    }
    public class Portal {
        public event System.EventHandler<ConfirmArgs> Confirmation;
        public event System.EventHandler<NoteArgs> Notification;
        // TIA raises its events on another thread
        public void Ask(ConfirmArgs a) { var t = new System.Threading.Thread(() => Confirmation(this, a)); t.Start(); t.Join(); }
        public void Tell(NoteArgs a) { var t = new System.Threading.Thread(() => Notification(this, a)); t.Start(); t.Join(); }
    }
}
'@

    It 'answers a confirmation with Cancel or No, acknowledges a notification, and queues both for the result' {
        $null = @(Get-PromptLog)
        $portal = New-Object TiaBridgeTest.Portal
        Register-PromptGuard $portal
        $yesNo = New-Object TiaBridgeTest.ConfirmArgs -Property @{ Caption = 'Replace'; Text = 'Replace the test instance?'; Choices = 'Yes, No'; Result = 'Yes' }
        $portal.Ask($yesNo)
        $yesNo.Result | Should Be 'No'
        $yesNo.IsHandled | Should Be $true
        $all = New-Object TiaBridgeTest.ConfirmArgs -Property @{ Text = 'Go on?'; Choices = 'Yes, No, Cancel'; Result = 'Yes' }
        $portal.Ask($all)
        $all.Result | Should Be 'Cancel'
        $note = New-Object TiaBridgeTest.NoteArgs -Property @{ Text = 'Cannot delete or replace (0026:000074)' }
        $portal.Tell($note)
        $note.IsHandled | Should Be $true

        $log = @(Get-PromptLog)
        $log.Count | Should Be 3
        $log[0].kind | Should Be 'confirmation'
        $log[0].text | Should Be 'Replace the test instance?'
        $log[0].answer | Should Be 'No'
        $log[2].kind | Should Be 'notification'
        $log[2].text | Should Match '0026:000074'
        @(Get-PromptLog).Count | Should Be 0
    }

    It 'leaves a confirmation without a negative or Ok choice to TIA, and the dispatch puts prompts into the result' {
        Initialize-TestBridge $TestDrive
        $portal = New-Object TiaBridgeTest.Portal
        Register-PromptGuard $portal
        $script:askPortal = $portal
        $d = Invoke-BridgeTool 'compile' { param($a) $script:askPortal.Ask((New-Object TiaBridgeTest.ConfirmArgs -Property @{ Text = 'Retry?'; Choices = 'Retry, Ignore' })); @{ ok = $true } } (New-Object psobject)
        @($d.result.prompts)[-1].answer | Should Match 'left to TIA'
    }
}

Describe 'Remove-StaleBackgroundScratch' {
    It 'removes the copies of bridge processes that are gone, and only those' {
        $root = Join-Path $TestDrive 'scratch'
        foreach ($n in '20261029_101010_999999', "20261029_101011_$PID", 'keep-me') { New-Item -ItemType Directory -Force -Path (Join-Path $root "$n\P") | Out-Null }
        $r = @(Remove-StaleBackgroundScratch $root)
        $r.Count | Should Be 1
        $r[0].removed | Should Be $true
        Test-Path (Join-Path $root '20261029_101010_999999') | Should Be $false
        Test-Path (Join-Path $root "20261029_101011_$PID") | Should Be $true
        Test-Path (Join-Path $root 'keep-me') | Should Be $true
    }

    It 'lies under the projects root unless backgroundRoot is set' {
        Initialize-BridgeContext @{ projectsRoot = 'C:\TIA-Projects' }
        Get-BackgroundRoot | Should Be 'C:\TIA-Projects\_bridge\background'
    }
}

Describe 'Get-BackgroundFailureHint' {
    It 'names the limit for a path TIA calls too long' {
        Get-BackgroundFailureHint @{ type = 't'; message = "The specified path' C:\x' (159 character) is too long. A maximum of 143 characters is allowed." } | Should Match '143'
    }

    It 'names the usual causes from the Siemens error' {
        Get-BackgroundFailureHint @{ type = 'Siemens.Engineering.MissingProductsException'; message = 'x'; details = @(); inner = @() } | Should Match 'option package or HSP'
        Get-BackgroundFailureHint @{ type = 'Siemens.Engineering.LicenseNotFoundException'; message = 'x'; details = @(); inner = @() } | Should Match 'licence'
        Get-BackgroundFailureHint @{ type = 'Siemens.Engineering.EngineeringTargetInvocationException'; message = 'Project protection: password required'; details = @(); inner = @() } |
            Should Match 'protected'
        # V20 Update 7, a UMC-protected copy of project D opened without user interface (2026-10-29)
        Get-BackgroundFailureHint @{ type = 'Siemens.Engineering.EngineeringTargetInvocationException'; message = 'x'; inner = @()
                                     details = @('An error occurred while opening the project: The project is protected. You are not authorized to open the project in write mode. Log on with different access authorization.') } |
            Should Match 'protected'
        Get-BackgroundFailureHint @{ type = 'Siemens.Engineering.EngineeringSecurityException'; message = 'Access denied'; details = @(); inner = @() } | Should Match 'Openness'
        Get-BackgroundFailureHint @{ type = 'System.Exception'; message = 'x'; details = @(); inner = @(@{ type = 'Y'; message = 'The project must be upgraded' }) } | Should Match 'upgrade'
        Get-BackgroundFailureHint @{ type = 'Siemens.Engineering.EngineeringTargetInvocationException'; message = 'The project is already open'; details = @(); inner = @() } |
            Should Match 'close it there'
        Get-BackgroundFailureHint @{ type = 'System.IO.IOException'; message = 'disk full'; details = @(); inner = @() } | Should BeNullOrEmpty
    }
}

Describe 'connect leaves TIA processes without user interface alone' {
    function Import-Openness { }
    function Test-OpennessGroup { $null }
    function Get-TiaProcesses { @(@{ processId = 4712; name = 'Bg'; path = 'C:\bg\Bg\Bg.ap20'; mode = 'WithoutUserInterface' }) }

    It 'does not offer a headless TIA for connect' {
        Initialize-TestBridge $TestDrive
        { Invoke-ConnectTool (New-Object psobject) } | Should Throw 'No TIA Portal with an open project'
    }
}
