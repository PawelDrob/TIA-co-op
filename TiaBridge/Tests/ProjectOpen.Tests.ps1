# project_open and project_close: what the probes of 2026-11-04 found on TIA, held with stand-ins.
$here = Split-Path -Parent $MyInvocation.MyCommand.Path
foreach ($f in 'Mcp.ps1', 'Tia.ps1', 'Repo.ps1', 'Rules.ps1', 'Guards.ps1', 'Bridge.ps1', 'State.ps1', 'Tools\Objects.ps1', 'Tools\Session.ps1', 'Tools\Background.ps1') {
    . (Join-Path $here "..\$f")
}

function Get-DeadPid { $n = 999999; while (Get-Process -Id $n -ErrorAction SilentlyContinue) { $n-- }; $n }
function ConvertTo-Arguments($Hash) { [pscustomobject]$Hash }

Describe 'project_open' {
    function Import-Openness { }
    function Test-OpennessGroup { $script:groupProblem }
    function Get-TiaProcesses { $script:calls++; if ($script:started -and $script:calls -gt $script:holdsAfter) { @($script:fakeProcesses) + @(@{ processId = $script:tiaId; name = 'P'; path = $script:held; mode = 'WithUserInterface' }) } else { @($script:fakeProcesses) } }
    function Start-TiaProgram([string]$TiaRoot, [string]$Path) { $script:started++; $script:startedOn = $Path; $script:commandLines += @(New-CommandLine $script:tiaId "`"$Path`""); $script:tiaId }
    function Get-TiaCommandLines { $script:commandLines }
    function New-CommandLine([int]$Id, [string]$Arguments) { @{ processId = $Id; commandLine = "`"C:\none\Bin\Siemens.Automation.Portal.exe`" $Arguments" } }
    function Get-TiaBoxTitles([int]$ProcessId) { $script:boxes }

    $ap = Join-Path $TestDrive 'P\P.ap20'
    New-Item -ItemType Directory -Force -Path (Split-Path $ap) | Out-Null; Set-Content $ap 'ap'

    function Reset-Fakes {
        Initialize-BridgeContext @{ projectsRoot = (Join-Path $TestDrive 'projects'); tiaRoot = 'C:\none'; maxResponseChars = 20000 }
        $script:fakeProcesses = @(); $script:started = 0; $script:startedOn = ''; $script:calls = 0; $script:holdsAfter = 1
        $script:tiaId = $PID; $script:held = $ap; $script:boxes = @(); $script:groupProblem = $null; $script:commandLines = @()
        $script:ProjectOpenWaitMs = 2000; $script:ProjectOpenPollMs = 10
    }

    It 'starts the TIA program on the path and waits until the process it started holds the project' {
        Reset-Fakes
        $r = Invoke-ProjectOpenTool (ConvertTo-Arguments @{ path = $ap })
        $r.ok | Should Be $true
        $script:started | Should Be 1
        $script:startedOn | Should Be $ap
        $r.processId | Should Be $PID
        $r.projectPath | Should Be $ap
        $r.next | Should Match 'connect'
    }

    It 'takes no other TIA for the one it started, also when it holds this path' {
        Reset-Fakes
        $script:held = 'C:\other\P.ap20'
        $script:boxes = @('Open project (0025:000012)')
        $r = Invoke-ProjectOpenTool (ConvertTo-Arguments @{ path = $ap })
        $r.ok | Should Be $false
        $r.pending | Should Be $true
    }

    It 'after the wait says TIA waits for the user, naming the boxes, and leaves it open' {
        Reset-Fakes
        $script:holdsAfter = [int]::MaxValue
        $script:boxes = @('Log on')
        $r = Invoke-ProjectOpenTool (ConvertTo-Arguments @{ path = $ap })
        $r.ok | Should Be $false
        $r.pending | Should Be $true
        @($r.boxes) -join ',' | Should Be 'Log on'
        $r.refused | Should Match 'shows: Log on'
        $r.refused | Should Match 'Ask the user to look at TIA'
        $r.processId | Should Be $PID
    }

    It 'called again for the project it waits on, starts nothing and waits on that process' {
        Reset-Fakes
        $script:holdsAfter = [int]::MaxValue
        (Invoke-ProjectOpenTool (ConvertTo-Arguments @{ path = $ap })).pending | Should Be $true
        (Invoke-ProjectOpenTool (ConvertTo-Arguments @{ path = $ap })).pending | Should Be $true
        $script:started | Should Be 1
        # the user answered the box
        $script:holdsAfter = 0
        $r = Invoke-ProjectOpenTool (ConvertTo-Arguments @{ path = $ap })
        $r.ok | Should Be $true
        $script:started | Should Be 1
    }

    It 'counts a process waiting behind a box as a project beside another' {
        Reset-Fakes
        $script:holdsAfter = [int]::MaxValue
        $null = Invoke-ProjectOpenTool (ConvertTo-Arguments @{ path = $ap })
        $other = Join-Path $TestDrive 'Other.ap20'; Set-Content $other 'o'
        $r = Invoke-ProjectOpenTool (ConvertTo-Arguments @{ path = $other })
        $r.refused | Should Match 'waiting behind a box'
        $r.refused | Should Match 'second=true'
        $script:started | Should Be 1
    }

    It 'beside a second TIA the user asked for, still waits on the first: called again for it, starts nothing' {
        Reset-Fakes
        $script:holdsAfter = [int]::MaxValue
        $other = Join-Path $TestDrive 'Other.ap20'; Set-Content $other 'o'
        $null = Invoke-ProjectOpenTool (ConvertTo-Arguments @{ path = $ap })
        $null = Invoke-ProjectOpenTool (ConvertTo-Arguments @{ path = $other; second = $true })
        $script:started | Should Be 2
        (Invoke-ProjectOpenTool (ConvertTo-Arguments @{ path = $ap })).pending | Should Be $true
        (Invoke-ProjectOpenTool (ConvertTo-Arguments @{ path = $other })).pending | Should Be $true
        $script:started | Should Be 2
    }

    It 'after a bridge restart, waits on the process started before, which it knows by its command line' {
        Reset-Fakes
        $script:holdsAfter = [int]::MaxValue
        $script:commandLines = @(New-CommandLine $PID "`"$ap`"")
        $script:boxes = @('Log on')
        $r = Invoke-ProjectOpenTool (ConvertTo-Arguments @{ path = $ap })
        $r.pending | Should Be $true
        $r.processId | Should Be $PID
        @($r.boxes) -join ',' | Should Be 'Log on'
        $script:started | Should Be 0
    }

    It 'after a bridge restart, counts that process as a project beside another' {
        Reset-Fakes
        $script:commandLines = @(New-CommandLine $PID '"C:\Old Place\Old.ap20"')
        $r = Invoke-ProjectOpenTool (ConvertTo-Arguments @{ path = $ap })
        $r.refused | Should Match ([regex]::Escape("C:\Old Place\Old.ap20 (process $PID, still opening or waiting behind a box)"))
        $script:started | Should Be 0
    }

    It 'reads the project from a command line whatever its case and quotes, and only a project' {
        $listed = @(@{ processId = 21; path = ''; mode = 'WithUserInterface' })
        $script:commandLines = @(
            (New-CommandLine 20 'C:\P\Plain.AP20'), (New-CommandLine 21 '"C:\P\Listed.ap20"'),
            (New-CommandLine 22 ''), (New-CommandLine 23 '"C:\P\Old.ap19"'), @{ processId = 24; commandLine = '' })
        $waiting = @(Get-TiaWaiting $listed)
        $waiting.Count | Should Be 1
        $waiting[0].processId | Should Be 20
        $waiting[0].path | Should Be 'C:\P\Plain.AP20'
    }

    # a process listed in GetProcesses is behind no box: on V20, 2026-11-04, a TIA behind *Log on* stayed out of GetProcesses until the login,
    # and one whose project was closed stayed in it with no project
    It 'after a slow login and a close, opens the same project again in a new TIA, with no wait on the old one' {
        Reset-Fakes
        $script:commandLines = @(New-CommandLine $PID "`"$ap`"")
        $script:fakeProcesses = @(@{ processId = $PID; name = ''; path = ''; mode = 'WithUserInterface' })
        $script:tiaId = 4242
        $sw = [System.Diagnostics.Stopwatch]::StartNew()
        $r = Invoke-ProjectOpenTool (ConvertTo-Arguments @{ path = $ap })
        $r.ok | Should Be $true
        $r.processId | Should Be 4242
        $script:started | Should Be 1
        $sw.ElapsedMilliseconds | Should BeLessThan $script:ProjectOpenWaitMs
        @($r.idleTia) -join ',' | Should Be "$PID"
    }

    It 'after a slow login and a close, opens another project, not taking the old TIA for one behind a box' {
        Reset-Fakes
        $script:commandLines = @(New-CommandLine $PID '"C:\Old\Old.ap20"')
        $script:fakeProcesses = @(@{ processId = $PID; name = ''; path = ''; mode = 'WithUserInterface' })
        $script:tiaId = 4242
        $r = Invoke-ProjectOpenTool (ConvertTo-Arguments @{ path = $ap })
        $r.ok | Should Be $true
        $script:started | Should Be 1
    }

    It 'after a slow login with the project still open, names it as open, not as behind a box' {
        Reset-Fakes
        $script:commandLines = @(New-CommandLine $PID '"C:\Old\Old.ap20"')
        $script:fakeProcesses = @(@{ processId = $PID; name = 'Old'; path = 'C:\Old\Old.ap20'; mode = 'WithUserInterface' })
        $r = Invoke-ProjectOpenTool (ConvertTo-Arguments @{ path = $ap })
        $r.refused | Should Match ([regex]::Escape('Open in TIA now: C:\Old\Old.ap20.'))
        $r.refused | Should Not Match 'behind a box'
        $script:started | Should Be 0
    }

    It 'says so when no box can be read' {
        Reset-Fakes
        $script:holdsAfter = [int]::MaxValue
        $text = (Invoke-ProjectOpenTool (ConvertTo-Arguments @{ path = $ap })).refused
        $text | Should Match 'still opening, shows a box, or stands with no project'
        $text | Should Match 'If it shows nothing, the user closes that TIA'
    }

    It 'says so when the process it started ended' {
        Reset-Fakes
        $script:holdsAfter = [int]::MaxValue
        $script:tiaId = Get-DeadPid
        $r = Invoke-ProjectOpenTool (ConvertTo-Arguments @{ path = $ap })
        $r.ok | Should Be $false
        $r.refused | Should Match 'ended before it held'
    }

    # the started process gets a child of its own name, with no window, that GetProcesses never lists; its line as seen on V20, 2026-11-05
    It 'takes the child process of a TIA for no TIA waiting' {
        Reset-Fakes
        $child = New-CommandLine 41 '-Name=SearchReplaceBackgroundProcess -CallAutoLoadDlcs=True -SyncSettingService=False -serverGuid=0a3b8889 -processId=40 -appDomainId=1 -nosplashscreen -lang=en'
        $script:commandLines = @((New-CommandLine 40 "`"$ap`""), $child)
        $script:fakeProcesses = @(@{ processId = 40; name = ''; path = ''; mode = 'WithUserInterface' })
        @(Get-TiaWaiting $script:fakeProcesses).Count | Should Be 0
        (Invoke-ProjectOpenTool (ConvertTo-Arguments @{ path = $ap })).ok | Should Be $true
        $script:started | Should Be 1
    }

    It 'starts nothing for a project open already: that leaves a TIA behind a box' {
        Reset-Fakes
        $script:fakeProcesses = @(@{ processId = 11; name = 'P'; path = $ap; mode = 'WithUserInterface' })
        $r = Invoke-ProjectOpenTool (ConvertTo-Arguments @{ path = $ap })
        $r.ok | Should Be $true
        $r.alreadyOpen | Should Be $true
        $r.processId | Should Be 11
        $script:started | Should Be 0
    }

    It 'refuses a project a TIA without user interface holds' {
        Reset-Fakes
        $script:fakeProcesses = @(@{ processId = 12; name = 'P'; path = $ap; mode = 'WithoutUserInterface' })
        (Invoke-ProjectOpenTool (ConvertTo-Arguments @{ path = $ap })).refused | Should Match 'without user interface'
        $script:started | Should Be 0
    }

    It 'refuses to start a second TIA beside a project, unless the user says to' {
        Reset-Fakes
        $script:fakeProcesses = @(@{ processId = 13; name = 'Q'; path = 'C:\Q\Q.ap20'; mode = 'WithUserInterface' })
        $r = Invoke-ProjectOpenTool (ConvertTo-Arguments @{ path = $ap })
        $r.refused | Should Match ([regex]::Escape('C:\Q\Q.ap20'))
        $r.refused | Should Match 'second=true'
        $script:started | Should Be 0
        $script:calls = 0
        (Invoke-ProjectOpenTool (ConvertTo-Arguments @{ path = $ap; second = $true })).ok | Should Be $true
        $script:started | Should Be 1
    }

    It 'is not held back by a TIA without user interface that holds another project' {
        Reset-Fakes
        $script:fakeProcesses = @(@{ processId = 14; name = 'Q'; path = 'C:\Q\Q.ap20'; mode = 'WithoutUserInterface' })
        (Invoke-ProjectOpenTool (ConvertTo-Arguments @{ path = $ap })).ok | Should Be $true
    }

    It 'names a TIA that stands with no project' {
        Reset-Fakes
        $script:fakeProcesses = @(@{ processId = 15; name = ''; path = ''; mode = 'WithUserInterface' })
        $r = Invoke-ProjectOpenTool (ConvertTo-Arguments @{ path = $ap })
        $r.ok | Should Be $true
        @($r.idleTia) -join ',' | Should Be '15'
    }

    It 'names a TIA that stands with no project on a pending result too' {
        Reset-Fakes
        $script:holdsAfter = [int]::MaxValue
        $script:fakeProcesses = @(@{ processId = 15; name = ''; path = ''; mode = 'WithUserInterface' })
        $r = Invoke-ProjectOpenTool (ConvertTo-Arguments @{ path = $ap })
        $r.pending | Should Be $true
        @($r.idleTia) -join ',' | Should Be '15'
        $r.note | Should Match 'the user can close them'
    }

    It 'promises no wait past the box: once the process is listed it holds the project or stands behind none' {
        Reset-Fakes
        $script:holdsAfter = [int]::MaxValue
        (Invoke-ProjectOpenTool (ConvertTo-Arguments @{ path = $ap })).refused | Should Match 'while that box stands'
    }

    It 'refuses an archive and an older version, before starting a TIA' {
        Reset-Fakes
        $zap = Join-Path $TestDrive 'P.zap20'; Set-Content $zap 'z'
        (Invoke-ProjectOpenTool (ConvertTo-Arguments @{ path = $zap })).refused | Should Match 'is an archive'
        $old = Join-Path $TestDrive 'Old.ap19'; Set-Content $old 'o'
        (Invoke-ProjectOpenTool (ConvertTo-Arguments @{ path = $old })).refused | Should Match 'upgrade'
        $script:started | Should Be 0
    }

    It 'refuses a file that does not exist, before starting a TIA: that leaves one behind a box' {
        Reset-Fakes
        { Invoke-ProjectOpenTool (ConvertTo-Arguments @{ path = (Join-Path $TestDrive 'gone.ap20') }) } | Should Throw 'not found'
        $script:started | Should Be 0
    }

    It 'refuses when the Windows user may not use Openness' {
        Reset-Fakes
        $script:groupProblem = 'not in the group'
        (Invoke-ProjectOpenTool (ConvertTo-Arguments @{ path = $ap })).refused | Should Be 'not in the group'
        $script:started | Should Be 0
    }

    It 'is refused in a background session, whose bridge has its own TIA' {
        Reset-Fakes
        foreach ($write in $true, $false) {
            $script:Bridge.background = @{ write = $write; processId = $PID; steps = (New-Object System.Collections.ArrayList); session = (New-SessionState) }
            Get-BackgroundRefusal 'project_open' (ConvertTo-Arguments @{ path = $ap }) | Should Match 'refused in a background session'
            Get-BackgroundRefusal 'project_close' (New-Object psobject) | Should Match 'refused in a background session'
        }
    }
}

Describe 'Get-TiaCommandLines' {
    It 'reads nothing when the process list cannot be read, so the tool goes on as with no TIA waiting' {
        Initialize-BridgeContext @{ projectsRoot = (Join-Path $TestDrive 'projects') }
        function Get-CimInstance { throw 'no WMI' }
        @(Get-TiaCommandLines).Count | Should Be 0
        @(Get-TiaWaiting @()).Count | Should Be 0
    }

    It 'asks for the TIA program by its name' {
        function Get-CimInstance { param($ClassName, $Filter, $ErrorAction) $script:filter = $Filter; [pscustomobject]@{ ProcessId = 7; CommandLine = 'x' } }
        $r = @(Get-TiaCommandLines)
        $script:filter | Should Match 'Siemens\.Automation\.Portal\.exe'
        $r[0].processId | Should Be 7
        $r[0].commandLine | Should Be 'x'
    }
}

Describe 'Start-TiaProgram' {
    It 'says where it looked when the program is not there' {
        { Start-TiaProgram (Join-Path $TestDrive 'none') 'C:\P.ap20' } | Should Throw 'tiaRoot'
    }
}

Describe 'project_close' {
    function New-Project([bool]$Modified) {
        $p = New-Object psobject -Property @{ Name = 'P'; IsModified = $Modified; closed = 0 }
        $p | Add-Member ScriptMethod Close { $this.closed++ }
        $p
    }
    function Reset-Bound([bool]$Modified) {
        Initialize-BridgeContext @{ projectsRoot = (Join-Path $TestDrive 'projects'); tiaRoot = 'C:\none'; maxResponseChars = 20000 }
        $script:Bridge.portal = New-Object psobject -Property @{ disposed = 0 }
        $script:Bridge.portal | Add-Member ScriptMethod Dispose { $this.disposed++ }
        $script:Bridge.project = New-Project $Modified
        $script:Bridge.processId = $PID
        Set-BridgeProject -Name 'P' -Path 'C:\P\P.ap20' -Repo $null
    }
    function Get-TiaProject { $script:Bridge.project }
    function Import-Openness { }

    It 'refuses when nothing is bound' {
        Initialize-BridgeContext @{ projectsRoot = (Join-Path $TestDrive 'projects'); tiaRoot = 'C:\none' }
        (Invoke-ProjectCloseTool (New-Object psobject)).refused | Should Match 'call connect first'
    }

    It 'closes a project with no changes, detaches, and leaves no binding or session' {
        Reset-Bound $false
        $project = $script:Bridge.project; $portal = $script:Bridge.portal
        $r = Invoke-ProjectCloseTool (New-Object psobject)
        $r.ok | Should Be $true
        $r.closed | Should Be 'P'
        $r.discarded | Should Be $false
        $project.closed | Should Be 1
        $portal.disposed | Should Be 1
        $script:Bridge.projectName | Should BeNullOrEmpty
        $script:Bridge.project | Should BeNullOrEmpty
        $script:Bridge.sessions.ContainsKey('C:\P\P.ap20') | Should Be $false
    }

    It 'refuses unsaved changes: TIA itself would drop them with no question' {
        Reset-Bound $true
        $project = $script:Bridge.project
        $r = Invoke-ProjectCloseTool (New-Object psobject)
        $r.refused | Should Match 'unsaved changes'
        $r.refused | Should Match 'discard=true'
        $project.closed | Should Be 0
        $script:Bridge.projectName | Should Be 'P'
    }

    It 'drops them only with discard, and says it did' {
        Reset-Bound $true
        $project = $script:Bridge.project
        $r = Invoke-ProjectCloseTool (ConvertTo-Arguments @{ discard = $true })
        $r.ok | Should Be $true
        $r.discarded | Should Be $true
        $project.closed | Should Be 1
    }

    It 'after a person closed the project, says so, closes nothing and drops the binding and the session' {
        Reset-Bound $false
        function Get-TiaProcesses { @(@{ processId = $PID; name = ''; path = ''; mode = 'WithUserInterface' }) }
        $project = $script:Bridge.project; $portal = $script:Bridge.portal
        $project.Name = ''   # what a closed project reads
        $r = Invoke-ProjectCloseTool (New-Object psobject)
        $r.ok | Should Be $true
        $r.alreadyClosed | Should Be $true
        $r.closed | Should Be 'P'
        $r.discarded | Should Be $false
        $r.next | Should Match 'last save'
        $project.closed | Should Be 0
        $portal.disposed | Should Be 1
        $script:Bridge.projectName | Should BeNullOrEmpty
        $script:Bridge.project | Should BeNullOrEmpty
        $script:Bridge.sessions.ContainsKey('C:\P\P.ap20') | Should Be $false
    }

    It 'after TIA ended, says the same' {
        Reset-Bound $false
        function Get-TiaProcesses { @() }
        $script:Bridge.processId = (Get-DeadPid)
        $script:Bridge.tiaEnded = 'TIA Portal ended'
        $r = Invoke-ProjectCloseTool (New-Object psobject)
        $r.alreadyClosed | Should Be $true
        $script:Bridge.projectName | Should BeNullOrEmpty
        $script:Bridge.tiaEnded | Should Be 'TIA Portal ended'   # connect clears it, not the close
    }

    It 'with the connection lost and the project still open, closes it through Get-TiaProject, not taking it for closed' {
        Reset-Bound $false
        function Get-TiaProcesses { @(@{ processId = 31; name = 'P'; path = 'c:\p\P.AP20'; mode = 'WithUserInterface' }) }
        $project = $script:Bridge.project
        $script:Bridge.processId = (Get-DeadPid)
        $r = Invoke-ProjectCloseTool (New-Object psobject)
        $r.ok | Should Be $true
        $r.Contains('alreadyClosed') | Should Be $false
        $project.closed | Should Be 1
    }

    It 'keeps the binding when TIA refuses the close' {
        Reset-Bound $false
        $script:Bridge.project | Add-Member -Force ScriptMethod Close { throw 'no' }
        { Invoke-ProjectCloseTool (New-Object psobject) } | Should Throw 'no'
        $script:Bridge.projectName | Should Be 'P'
        $script:Bridge.sessions.ContainsKey('C:\P\P.ap20') | Should Be $true
    }
}

Describe 'tia_status: other bridges and scripts changed' {
    function Import-Openness { }
    function Get-TiaProcesses { $script:fakeProcesses }
    function Test-TiaAlive { $false }
    function Get-NewerBridgeScripts { $script:newer }

    $root = Join-Path $TestDrive 'projects'
    $dir = Get-BridgeStateDir $root
    New-Item -ItemType Directory -Force -Path $dir | Out-Null
    # a process that runs and is not this one, to stand for another bridge
    $other = Start-Process -FilePath "$env:SystemRoot\System32\ping.exe" -ArgumentList '-n 60 127.0.0.1' -WindowStyle Hidden -PassThru

    function Set-OtherBridge([int]$Tia) {
        Set-Content (Join-Path $dir "$($other.Id).json") (ConvertTo-Json @{ pid = $other.Id; started = (Get-Date).ToString('o'); project = 'Q'; session = 's2'; tia = @{ pid = $Tia } })
    }
    function Reset-Status {
        Initialize-BridgeContext @{ projectsRoot = $root; tiaRoot = 'C:\none'; maxResponseChars = 20000 }
        $script:newer = @()
        $script:fakeProcesses = @(@{ processId = 11; name = 'A'; path = 'C:\A\A.ap20'; mode = 'WithUserInterface' }, @{ processId = 12; name = 'B'; path = 'C:\B\B.ap20'; mode = 'WithoutUserInterface' })
    }

    It 'with nothing bound names a bridge on a TIA with a window, and says what that means' {
        Reset-Status
        Set-OtherBridge 11
        $r = Invoke-StatusTool (New-Object psobject)
        @($r.otherBridges).Count | Should Be 1
        $r.otherBridges[0].pid | Should Be $other.Id
        $r.otherBridges[0].tia | Should Be 11
        $r.otherBridges[0].project | Should Be 'Q'
        $r.otherBridgesNote | Should Match 'has hung it'
    }

    It 'with nothing bound leaves out a bridge on a TIA without a window: its own background session' {
        Reset-Status
        Set-OtherBridge 12
        $r = Invoke-StatusTool (New-Object psobject)
        $r.Contains('otherBridges') | Should Be $false
        $r.Contains('otherBridgesNote') | Should Be $false
    }

    It 'when bound names only a bridge on the bound TIA' {
        Reset-Status
        $script:Bridge.processId = 13
        Set-OtherBridge 13
        $r = @{ connected = $true; processes = $script:fakeProcesses }
        Set-BridgeStatusNotes $r
        @($r.otherBridges).Count | Should Be 1
        Set-OtherBridge 11
        $r = @{ connected = $true; processes = $script:fakeProcesses }
        Set-BridgeStatusNotes $r
        $r.Contains('otherBridges') | Should Be $false
    }

    It 'names the scripts changed since the bridge started, and says nothing when none has' {
        Reset-Status
        Remove-Item (Join-Path $dir '*.json')
        (Invoke-StatusTool (New-Object psobject)).Contains('scriptsNewer') | Should Be $false
        $script:newer = @('Tia.ps1', 'Tools\Session.ps1')
        $r = Invoke-StatusTool (New-Object psobject)
        $r.scriptsNewer | Should Match ([regex]::Escape('Tia.ps1, Tools\Session.ps1'))
        $r.scriptsNewer | Should Match 'restart'
    }

    It 'names the online state of each device of the bound project' {
        Reset-Status
        function Test-TiaAlive { $true }
        function Get-TiaSoftwareList { @(@{ device = 'PLC_1'; kind = 'plc'; deviceItem = 'cpu' }, @{ device = 'HMI_1'; kind = 'hmi'; deviceItem = 'panel' }) }
        function Get-OnlineProvider($Item) { if ($Item -eq 'cpu') { @{ State = 'Online' } } }
        function Get-InWorkTypes { @{ types = @(); complete = $true; walked = 0 } }
        function Get-LastLibraryLog { }
        $script:Bridge.projectName = 'A'
        $script:Bridge.project = New-Object psobject -Property @{ IsModified = $false; ProjectLibrary = $null }
        function Get-SessionSummary { }
        $r = Invoke-StatusTool (New-Object psobject)
        ($r.devices | ForEach-Object { "$($_.device):$($_.online)" }) -join ',' | Should Be 'PLC_1:online,HMI_1:unknown'
    }

    It 'looks for changed scripts in the bridge''s own folder' {
        Reset-Status
        function Get-NewerBridgeScripts([string]$Dir, [datetime]$Since) { $script:looked = $Dir; @() }
        $null = Invoke-StatusTool (New-Object psobject)
        $script:looked | Should Be ([System.IO.Path]::GetFullPath((Join-Path $here '..')))
    }

    Stop-Process -Id $other.Id -Force -ErrorAction SilentlyContinue
}

Describe 'Test-TiaAlive' {
    It 'calls a project closed under the bridge gone: its name reads empty, with no exception' {
        Initialize-BridgeContext @{ projectsRoot = (Join-Path $TestDrive 'projects') }
        $script:Bridge.processId = $PID
        $script:Bridge.project = New-Object psobject -Property @{ Name = 'P' }
        Test-TiaAlive | Should Be $true
        $script:Bridge.project.Name = ''
        Test-TiaAlive | Should Be $false
    }
}

Describe 'Get-SecondTiaWarning' {
    function Get-TiaProcesses { $script:fakeProcesses }

    It 'warns on a switch to a second TIA process with the first still open' {
        $script:fakeProcesses = @(@{ processId = 11; path = 'C:\A\A.ap20' }, @{ processId = 12; path = 'C:\B\B.ap20' })
        $w = Get-SecondTiaWarning 11 'C:\A\A.ap20' 12
        $w | Should Match 'second TIA process'
        $w | Should Match ([regex]::Escape('C:\A\A.ap20'))
        $w | Should Match 'stopping the bridge frees TIA'
    }

    It 'says nothing with no bridge bound before, in the same process, or with the first closed' {
        $script:fakeProcesses = @(@{ processId = 11; path = '' }, @{ processId = 12; path = 'C:\B\B.ap20' })
        Get-SecondTiaWarning 0 '' 12 | Should BeNullOrEmpty
        Get-SecondTiaWarning 12 'C:\B\B.ap20' 12 | Should BeNullOrEmpty
        Get-SecondTiaWarning 11 'C:\A\A.ap20' 12 | Should BeNullOrEmpty
    }
}
