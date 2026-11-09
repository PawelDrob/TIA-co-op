# Tools\Session.ps1 - tia_status, connect, save, archive.

function ConvertTo-ArchiveReason([string]$Reason) {
    $r = ($Reason -replace '[^A-Za-z0-9_-]+', '_').Trim('_')
    if ($r.Length -gt 40) { $r = $r.Substring(0, 40) }
    if (-not $r) { $r = 'archive' }
    $r
}

# tia-co-op-<project>-<yyyy-MM-dd>_<HHmmss>[-<reason>].zap20; the session archive carries no reason.
# The time stays in the name so two archives of one day do not collide.
# TIA refuses an archive path (folder + name, without .zap20) over 143 characters (2026-10-06): with -Dir the
# project and the reason are shortened to fit. The time alone tells archives apart (Get-ArchiveStamp, Repo.ps1).
function ConvertTo-ArchiveName([string]$Project, [string]$Reason, [datetime]$At = (Get-Date), [string]$Dir) {
    $p = ($Project -replace '[^A-Za-z0-9_-]+', '_').Trim('_')
    $stamp = $At.ToString('yyyy-MM-dd_HHmmss')
    if ($Dir) {
        $room = $script:TiaPathLimit - ($Dir.TrimEnd('\').Length + 1) - "tia-co-op--$stamp".Length
        if ($p.Length -gt $room) { $p = $p.Substring(0, [Math]::Max($room, 0)).TrimEnd('_') }
    }
    $name = "tia-co-op-$p-$stamp"
    if ($Reason -ne 'session') {
        $r = ConvertTo-ArchiveReason $Reason
        if ($Dir) {
            $room = $script:TiaPathLimit - ($Dir.TrimEnd('\').Length + 1) - $name.Length - 1
            $r = if ($room -gt 0) { $r.Substring(0, [Math]::Min($r.Length, $room)).TrimEnd('_') } else { '' }
        }
        if ($r) { $name += "-$r" }
    }
    "$name.zap20"
}

# Why an archive is refused while the project has unsaved changes, and what works: save waits for the session archive,
# so it is the way out only once that archive exists or was skipped. A background session has no window to save in.
function Get-UnsavedArchiveRefusal {
    $why = 'The project has unsaved changes, and TIA archives only a saved project. '
    $background = [bool]$script:Bridge.background
    $s = Get-BridgeSession
    if ($s.unreadable) { return $why + $s.unreadable }
    if (-not (Test-WriteAllowed $s)) {
        # with the session archive save goes through as it stands; after a skip it needs the clean compile
        return $why + $(if ($background) { "Use save$(if (-not $s.archived) { ' (after a clean compile)' }), then archive." }
                        else { "Use save ($(if (-not $s.archived) { 'after a clean compile; ' })it also stores the user's own edits), then archive, or ask the user to save in TIA." })
    }
    $why + 'save waits for the session archive. ' +
        $(if ($background) { 'This session has no window to save in: call background_close with discard=true and background_open again, or archive(skip=true, reason) only when the user says so.' }
          else { 'Ask the user to save in TIA (their edits included), then retry archive(reason), or archive(skip=true, reason) only when the user says so.' })
}

# Project.Archive into <repo>\archives, newest N kept. TIA archives only a saved project.
function Invoke-ProjectArchive([string]$Reason) {
    $project = Get-TiaProject
    # TIA refuses: "Operation is not possible while project has unsaved changes" (probed 2026-10-04)
    if ($project.IsModified) { throw (Get-UnsavedArchiveRefusal) }
    $dir = Join-Path $script:Bridge.repo 'archives'
    New-Item -ItemType Directory -Force -Path $dir | Out-Null
    $name = ConvertTo-ArchiveName -Project $script:Bridge.projectName -Reason $Reason -Dir $dir
    $project.Archive([System.IO.DirectoryInfo]::new($dir), $name, [Siemens.Engineering.ProjectArchivationMode]::Compressed)
    Register-Archive (Get-BridgeSession)
    $removed = @(Remove-OldArchives -Dir $dir -Keep ([int]$script:Bridge.settings.archivesKept))
    @{ ok = $true; file = "archives\$name"; reason = $Reason; unsavedChanges = [bool]$project.IsModified
       removed = @($removed | ForEach-Object { Split-Path $_ -Leaf }) }
}

# A session archive that failed, into the result of connect or background_open: writes stay refused, Note says what to
# do. An archive that ended TIA is no ordinary failure: the session is over (Set-TiaEnded). At: the call that failed.
function Set-SessionArchiveFailure($Result, $ErrorRecord, [string]$Note, [string]$At = 'the session archive') {
    $err = ConvertTo-BridgeError $ErrorRecord
    $Result.archive = @{ ok = $false; error = $err }
    if ($err.tiaEnded -or -not (Test-TiaAlive)) {
        $Result.ok = $false; $Result.tiaEnded = $true
        $Result.note = "TIA Portal ended at $At. $(Set-TiaEnded $(if ($err.tiaEnded) { $err.type } else { 'it does not answer any more' }))"
    }
    else { $Result.note = $Note }
}

function Get-SessionSummary {
    if (-not $script:Bridge.projectName) { return $null }
    $s = Get-BridgeSession
    $summary = @{ archived = $s.archived; archiveSkipped = $s.archiveSkipped; writesAllowed = -not (Test-WriteAllowed $s)
                  saveBlockers = @(Test-SaveAllowed $s); saveStanding = @(Get-SaveStanding $s) }
    if ($s.unreadable) { $summary.recordUnreadable = $s.unreadable }
    $summary
}

# What tia_status adds about this bridge: other bridges on this TIA (when not bound, on any TIA with a window: connect would join them), as a second one has
# hung TIA; and scripts changed since this bridge started.
function Set-BridgeStatusNotes($Result) {
    $ids = $(if ($Result.connected) { @([int]$script:Bridge.processId) } else { @($Result.processes | Where-Object { $_.mode -ne 'WithoutUserInterface' } | ForEach-Object { [int]$_.processId }) })
    $others = @(Get-OtherBridges (Get-BridgeStateDir $script:Bridge.settings.projectsRoot) $ids)
    if ($others.Count) { $Result.otherBridges = $others; $Result.otherBridgesNote = 'Another bridge on one TIA has hung it (cause unknown). Tell the user before you write; only the user stops a bridge of another session.' }
    $newer = @(Get-NewerBridgeScripts (Split-Path -Parent $PSScriptRoot) (Get-Process -Id $PID).StartTime)
    if ($newer.Count) { $Result.scriptsNewer = "Changed since this bridge started, so not in what it runs: $($newer -join ', '). A restart of the bridge (/mcp in Claude Code) loads them." }
}

function Invoke-StatusTool($a) {
    Import-Openness $script:Bridge.settings.tiaRoot
    $r = @{ ok = $true; processes = @(Get-TiaProcesses); connected = (Test-TiaAlive); session = (Get-SessionSummary) }
    if ($script:Bridge.background) { $r.background = Get-BackgroundSummary }
    Set-BridgeStatusNotes $r
    if ($script:Bridge.projectName -and $r.connected) {
        $r.devices = @(Get-DeviceStates @(Get-TiaSoftwareList))
        $r.unsavedChanges = [bool]$script:Bridge.project.IsModified
        # a short time limit: tia_status must answer even when the library walk is slow (2026-10-05: 20+ min)
        $work = Get-InWorkTypes $script:Bridge.project.ProjectLibrary -BudgetMs 30000
        $last = Get-LastLibraryLog
        $r.library = @{ inWork = @($work.types).Count; inWorkTypes = @($work.types | ForEach-Object { $_.type } | Select-Object -First 10)
                        counted = $(if ($work.complete) { 'all types' } else { "first $($work.walked) types (time limit)" })
                        lastChange = $(if ($last) { [string]$last } else { $null }) }
    }
    $r
}

function Invoke-ConnectTool($a) {
    $script:Bridge.tiaEnded = $null      # connect is the way back after TIA ended (Set-TiaEnded)
    # before the attach: TIA would show its access dialog for a connect that then fails on the repo
    $why = Get-GitProblem
    if ($why) { return New-Refusal $why }
    Import-Openness $script:Bridge.settings.tiaRoot
    $why = Test-OpennessGroup
    if ($why) { return New-Refusal $why }
    # a TIA without user interface (a background session's, or one left by a stopped bridge) shows no access dialog to confirm
    $sel = Select-TiaProject @(Get-TiaProcesses | Where-Object { $_.path -and $_.mode -ne 'WithoutUserInterface' }) ([string]$a.project)
    $moved = Get-OptionalBool $a 'moved' $false
    # before the attach: no access dialog for a connect that is refused, and the bound project stays bound
    $choice = Resolve-ProjectRepo -Root $script:Bridge.settings.projectsRoot -ProjectName $sel.name -ProjectPath $sel.path -RepoName ([string]$a.repo) -Moved:$moved
    if ($choice.refused) { return New-Refusal $choice.refused }
    $why = Get-OtherAttachRefusal $sel $(if ($choice.repoName) { $choice.repoName } else { Get-ProjectFolderName $sel.name })
    if ($why) { return New-Refusal $why }
    $previous = $script:Bridge.projectName
    $previousPath = $script:Bridge.projectPath
    $previousTia = [int]$script:Bridge.processId
    try {
        Connect-Tia $sel
        $project = $script:Bridge.project
        $script:Bridge.projectPath = $project.Path.FullName   # Get-TiaSoftwareList needs the binding
        $script:Bridge.software = $null
        $sw = @(Get-TiaSoftwareList)
        $typeIds = @{}
        foreach ($h in @($sw | Where-Object { $_.kind -eq 'hmi' })) { $typeIds[$h.device] = Get-DeviceTypeIdentifier $h.deviceObject }
        $map = Initialize-ProjectRepo -Root $script:Bridge.settings.projectsRoot -ProjectName $project.Name -ProjectPath $project.Path.FullName `
            -PlcDevices @($sw | Where-Object { $_.kind -eq 'plc' } | ForEach-Object { $_.device }) `
            -HmiDevices @($sw | Where-Object { $_.kind -eq 'hmi' } | ForEach-Object { $_.device }) -HmiTypeIdentifiers $typeIds -RepoName $choice.repoName -Moved:$moved -StandardsTemplate ([string]$script:Bridge.settings.standardsTemplate)
        $dropped = @(Set-BridgeProject -Name $project.Name -Path $project.Path.FullName -Repo $map.repo -Software $sw)
    }
    catch {
        # never leave the new TIA project paired with the previous project's repo and session state
        Reset-TiaConnection
        $script:Bridge.projectName = $null; $script:Bridge.projectPath = $null; $script:Bridge.repo = $null
        throw
    }
    $r = @{ ok = $true; projectPath = $project.Path.FullName; repoCreated = $map.created
            devices = @(Get-DeviceStates $sw)
            readFirst = (Join-Path $map.repo 'docs\project.md'); unsavedChanges = [bool]$project.IsModified }
    if ($previousPath -and $previousPath -ne $project.Path.FullName) { $r.switchedFrom = $(if ($previous -ne $project.Name) { $previous } else { $previousPath }) }
    $warning = Get-SecondTiaWarning $previousTia $previousPath $sel.processId
    if ($warning) { $r.secondTia = $warning }
    Set-StandardsResult $r $map
    if ($choice.found) { $r.repoByPath = Get-RepoByPathNote $choice }
    if ($map.pathChanged) { $r.pathChanged = "The project was at $($map.oldPath); tiabridge.json now records the new path." }
    $s = Get-BridgeSession
    if (-not $project.IsModified) {
        if ($s.unreadable) { $r.recordReset = 'The session record could not be read, or lacked the result of a write. The project has no unsaved changes, so it held nothing a save could store: a new record starts.' }
        Clear-SessionWrites $s
    }
    elseif ($dropped.Count) {
        $r.droppedWrites = "No longer counted for save, since the project has no such device any more (renamed or deleted in TIA) and no compile could clear them: $($dropped -join ', '). If the device was renamed, compile it under its new name before save."
    }
    # a report run reads and writes nothing to TIA: no archive to return to
    if (-not ($s.archived -or $s.archiveSkipped -or $script:Bridge.reportRun)) {
        try { $r.archive = Invoke-ProjectArchive 'session' }
        catch {
            Set-SessionArchiveFailure $r $_ $(if ($s.unreadable) { 'The session archive failed, and writes are refused by the session record: session.recordUnreadable says what ends that.' }
                                              else { 'The session archive failed, so writes are refused. If the project has unsaved changes, ask the user to save it in TIA first; then retry archive(reason), or archive(skip=true, reason) if the user says to skip it.' })
        }
    }
    $r.session = Get-SessionSummary
    $r
}

# Why an agent's bridge may not attach to TIA process Tia for the repo at Repo, or $null: a report run of the TIA dashboard
# (TiaAgentStatus\reportrun.py) is on that TIA or that repo, as its record in <projectsRoot>\_bridge\report-runs\ says,
# the record not ended, and its process alive (not started after the record: a pid taken again) or its bridge alive (started
# after it: a run killed leaves its bridge in the call it is in). As TiaAgentStatus\reportrun.py is_running reads it. A
# record that cannot be read says nothing.
function Get-ReportRunRefusal([string]$ProjectsRoot, [int]$Tia, [string]$Repo) {
    $want = $(if ($Repo) { [System.IO.Path]::GetFullPath($Repo).TrimEnd('\') } else { '' })
    foreach ($f in @(Get-ChildItem -LiteralPath (Join-Path $ProjectsRoot '_bridge\report-runs') -Filter '*.json' -ErrorAction SilentlyContinue)) {
        try {
            $r = Get-Content -LiteralPath $f.FullName -Raw -Encoding UTF8 | ConvertFrom-Json
            if ($r.ended -or -not $r.pid) { continue }
            $started = [DateTime]$r.started
            $p = Get-Process -Id ([int]$r.pid) -ErrorAction SilentlyContinue
            $b = $(if ($r.bridge) { Get-Process -Id ([int]$r.bridge) -ErrorAction SilentlyContinue })
            $runs = ($p -and $p.StartTime -le $started.AddSeconds(5)) -or ($b -and $b.StartTime -ge $started.AddSeconds(-5))
            if (-not $runs) { continue }
            $same = ($r.tia -and [int]$r.tia -eq $Tia) -or ($want -and $r.repo -and [System.IO.Path]::GetFullPath([string]$r.repo).TrimEnd('\') -eq $want)
        }
        catch { continue }
        if ($same) {
            return "The TIA dashboard is making a change report of $($r.project) on this TIA, since $(([DateTime]$r.started).ToString('HH:mm')): connect after it ends; the dashboard shows when. Two programs on one TIA have hung it."
        }
    }
    $null
}

# The programs attached to TIA process ProcessId but this one: @{ pid; path }. Read from TIA without an attach.
function Get-TiaAttachedPrograms([int]$ProcessId) {
    $proc = [Siemens.Engineering.TiaPortal]::GetProcesses() | Where-Object { $_.Id -eq $ProcessId } | Select-Object -First 1
    foreach ($s in @(if ($proc) { $proc.AttachedSessions })) {
        if ($s.ProcessId -ne $PID) { @{ pid = [int]$s.ProcessId; path = [string]$s.ProcessPath } }
    }
}

# Why connect may not attach to the selected TIA for the repo folder RepoName, or $null: two programs on one TIA have
# hung it (docs\agent\openness-v20.md). A report run of the TIA dashboard refuses a TIA another program is attached to;
# an agent's bridge refuses the TIA and the repo of a report run. Each first says which TIA it is about to attach to (the
# bridge in its state file, the report run in its record), then looks for the other: two at once both refuse.
function Get-OtherAttachRefusal($Selected, [string]$RepoName) {
    if ($script:Bridge.reportRun) {
        $others = @(Get-TiaAttachedPrograms $Selected.processId)
        if (-not $others.Count) { return $null }
        return "Not now: a program is connected to this TIA: $(@($others | ForEach-Object { "$($_.path) (process $($_.pid))" }) -join ', '). Two programs on one TIA have hung it."
    }
    Write-BridgeProgress @{ event = 'tia'; pid = [int]$Selected.processId; window = $true }   # the user's TIA
    Get-ReportRunRefusal $script:Bridge.settings.projectsRoot $Selected.processId (Join-Path $script:Bridge.settings.projectsRoot $RepoName)
}

function Get-RepoByPathNote($Choice) {
    "$($Choice.repoName) records this project's path$(if ($Choice.owner) { "; the repo named after the project belongs to $($Choice.owner)" })."
}

# The standards entries of a session's result, from Initialize-ProjectRepo's map.
function Set-StandardsResult($Result, $Map) {
    $standards = Get-StandardsResult $Map.repo
    if ($standards) { $Result.standards = $standards }
    if ($Map.standardsNote) { $Result.standardsNote = $Map.standardsNote }
}

# A switch to a project in another TIA process, with the one before still open: why that is to be said (2026-10-20, 2026-10-21).
function Get-SecondTiaWarning([int]$PreviousTia, [string]$PreviousPath, [int]$Tia) {
    if (-not $PreviousTia -or $PreviousTia -eq $Tia) { return $null }
    if (-not @(Get-TiaProcesses | Where-Object { $_.processId -eq $PreviousTia -and $_.path }).Count) { return $null }
    "This project is in a second TIA process ($Tia), beside $PreviousPath in process $PreviousTia. A project bound second, in a second TIA process, has got slow and then hung TIA (cause unknown). " +
        'Tell the user. When a write takes more than a minute and TIA shows only the exclusive-access box, stopping the bridge frees TIA: offer that.'
}

$script:ProjectOpenWaitMs = 90000
$script:ProjectOpenPollMs = 2000

# Seams for the tests: start the TIA program, and read the titles of the boxes on a process's main window.
function Start-TiaProgram([string]$TiaRoot, [string]$Path) {
    $exe = Join-Path $TiaRoot 'Bin\Siemens.Automation.Portal.exe'
    if (-not (Test-Path -LiteralPath $exe)) { throw "The TIA program $exe was not found; set tiaRoot in TiaBridge\settings.json if V20 is installed elsewhere." }
    [int](Start-Process -FilePath $exe -ArgumentList "`"$Path`"" -PassThru).Id
}

function Get-TiaBoxTitles([int]$ProcessId) {
    try {
        Add-Type -AssemblyName UIAutomationClient, UIAutomationTypes
        $auto = [System.Windows.Automation.AutomationElement]
        $mine = New-Object System.Windows.Automation.PropertyCondition $auto::ProcessIdProperty, $ProcessId
        $box = New-Object System.Windows.Automation.PropertyCondition $auto::ControlTypeProperty, ([System.Windows.Automation.ControlType]::Window)
        foreach ($w in $auto::RootElement.FindAll([System.Windows.Automation.TreeScope]::Children, $mine)) {
            foreach ($b in $w.FindAll([System.Windows.Automation.TreeScope]::Children, $box)) { if ($b.Current.Name) { [string]$b.Current.Name } }
        }
    }
    catch { Write-BridgeLog "Boxes of TIA process $ProcessId not read: $($_.Exception.Message)" }
}

# The TIA programs running, each with the line it was started with. Empty when that cannot be read: project_open then starts as if none waits.
function Get-TiaCommandLines {
    try {
        Get-CimInstance Win32_Process -Filter "Name='Siemens.Automation.Portal.exe'" -ErrorAction Stop |
            ForEach-Object { @{ processId = [int]$_.ProcessId; commandLine = [string]$_.CommandLine } }
    }
    catch { Write-BridgeLog "Command lines of TIA not read: $($_.Exception.Message)" }
}

# The TIA processes started on a project file that GetProcesses does not list: still opening, or behind a box [PROBE 2026-11-04].
# Read from Windows, not kept by the bridge: they outlive it, and a person's start on a file counts as well. The child of the same
# name that GetProcesses never lists names no project on its line [PROBE 2026-11-05].
function Get-TiaWaiting([object[]]$Processes) {
    foreach ($line in @(Get-TiaCommandLines)) {
        if (@($Processes | Where-Object { $_.processId -eq $line.processId }).Count) { continue }
        $m = [regex]::Match($line.commandLine, '"([^"]+\.ap20)"|(\S+\.ap20)(?=\s|$)', [System.Text.RegularExpressions.RegexOptions]::IgnoreCase)
        if ($m.Success) { @{ processId = $line.processId; path = $(if ($m.Groups[1].Success) { $m.Groups[1].Value } else { $m.Groups[2].Value }) } }
    }
}

# Started with a path, TIA shows the project in its window and in GetProcesses, on the process started. Behind a box (a login, a
# project open elsewhere, a file not found) that process is not in GetProcesses and nothing times out in TIA [PROBE 2026-11-04].
# Openness's own Open blocks on such a box, and the TIA program does not end with the bridge: hence this way. So a call waits on a
# process waiting on this file (Get-TiaWaiting), as a second start would stand behind a box of its own.
function Invoke-ProjectOpenTool($a) {
    $src = Get-BackgroundSource ([string]$a.path)
    if ($src.kind -ne 'project') { return New-Refusal "project_open opens a V20 project file (.ap20); $($src.path) is an archive. Ask the user to retrieve it in TIA; or, when the user asks for a background session, background_open with write=true." }
    if ($src.upgrade) { return New-Refusal "$($src.path) is a V$($src.version) project, and opening it means an upgrade to V20, which writes a new project. Ask the user to upgrade it in TIA." }
    Import-Openness $script:Bridge.settings.tiaRoot
    $why = Test-OpennessGroup
    if ($why) { return New-Refusal $why }
    $processes = @(Get-TiaProcesses)
    $waiting = @(Get-TiaWaiting $processes)
    $pending = Find-TiaHolding $waiting $src.path
    $holder = Find-TiaHolding $processes $src.path
    if ($holder) {
        if ($holder.mode -eq 'WithoutUserInterface') { return New-Refusal "$($src.path) is open in a TIA without user interface (process $($holder.processId): a background session, or one left by a stopped bridge) and locked there. Ask the user." }
        return @{ ok = $true; alreadyOpen = $true; processId = $holder.processId; projectPath = $src.path; next = "Call connect with project: `"$($src.path)`"." }
    }
    $beside = @($processes | Where-Object { $_.path -and $_.mode -ne 'WithoutUserInterface' } | ForEach-Object { $_.path })
    $beside += @($waiting | Where-Object { $_ -ne $pending } | ForEach-Object { "$($_.path) (process $($_.processId), still opening or waiting behind a box)" })
    if (-not $pending -and $beside.Count -and -not (Get-OptionalBool $a 'second' $false)) {
        return New-Refusal ("Open in TIA now: $($beside -join ', '). TIA holds one project per process, so this would start a second TIA process beside it, and a project bound second has got slow and then hung TIA (cause unknown). " +
                            'Ask the user: close that project first (in TIA, or project_close on the user''s word), or second=true when the user says to run both.')
    }
    if ($pending) { $tia = $pending.processId }
    else {
        $tia = Start-TiaProgram $script:Bridge.settings.tiaRoot $src.path
        Write-BridgeLog "project_open: TIA process $tia started for $($src.path)"
    }
    $idle = @($processes | Where-Object { -not $_.path -and $_.mode -ne 'WithoutUserInterface' } | ForEach-Object { $_.processId })
    $sw = [System.Diagnostics.Stopwatch]::StartNew()
    while ($sw.ElapsedMilliseconds -lt $script:ProjectOpenWaitMs) {
        if (@(Get-TiaProcesses | Where-Object { $_.processId -eq $tia -and $_.path -eq $src.path }).Count) {
            return Add-IdleTiaNote @{ ok = $true; processId = $tia; projectPath = $src.path; seconds = [int]$sw.Elapsed.TotalSeconds; next = "Call connect with project: `"$($src.path)`"." } $idle
        }
        if (-not (Get-Process -Id $tia -ErrorAction SilentlyContinue)) { return @{ ok = $false; processId = $tia; refused = "TIA process $tia ended before it held $($src.path). Ask the user what it showed." } }
        Start-Sleep -Milliseconds $script:ProjectOpenPollMs
    }
    $boxes = @(Get-TiaBoxTitles $tia)
    Add-IdleTiaNote @{ ok = $false; pending = $true; processId = $tia; boxes = $boxes; projectPath = $src.path
       refused = ("TIA process $tia does not hold $($src.path) after $([int]($script:ProjectOpenWaitMs / 1000)) s" + $(if ($boxes.Count) { " and shows: $($boxes -join ', ')" } else { ': it is still opening, shows a box, or stands with no project. If it shows nothing, the user closes that TIA: until then project_open waits on it' }) + '. ' +
                  'It waits for the user (a login, a message); TIA has no time limit on it. Ask the user to look at TIA and answer it, then call connect; while that box stands, project_open again waits on this process and starts none. It stays open: the bridge ends no TIA.') } $idle
}

function Add-IdleTiaNote($Result, [object[]]$Idle) {
    if ($Idle.Count) { $Result.idleTia = $Idle; $Result.note = 'TIA processes with no project stand beside it, each holding memory: the user can close them.' }
    $Result
}

# Project.Close asks nothing, also with unsaved changes, and they are gone; TIA stays open with no project [PROBE 2026-11-04]. The
# session goes too: until a project is opened again a person can change it, so the next connect makes a new archive.
# Closed by a person, or with TIA ended, there is nothing to close: what the tool is for has happened, so the binding goes the same way.
function Invoke-ProjectCloseTool($a) {
    if (-not $script:Bridge.projectName) { return New-Refusal 'Not connected to a project: project_close closes the bound project, so call connect first.' }
    $path = $script:Bridge.projectPath
    $name = $script:Bridge.projectName
    $repo = $script:Bridge.repo
    $gone = $false
    if (-not (Test-TiaAlive)) {
        Import-Openness $script:Bridge.settings.tiaRoot
        $gone = -not (Find-TiaHolding @(Get-TiaProcesses) $path)
    }
    $unsaved = $false
    if (-not $gone) {
        $project = Get-TiaProject
        $unsaved = [bool]$project.IsModified
        if ($unsaved -and -not (Get-OptionalBool $a 'discard' $false)) {
            return New-Refusal "$path has unsaved changes, and TIA would drop them with no question. Use save, or ask the user: saving in TIA, or discard=true on the user's word."
        }
        $project.Close()
    }
    Reset-TiaConnection
    [void]$script:Bridge.sessions.Remove($path)
    $script:Bridge.projectName = $null; $script:Bridge.projectPath = $null; $script:Bridge.repo = $null
    $r = @{ ok = $true; closed = $name; projectPath = $path; projectRepo = $repo; discarded = $unsaved; next = 'TIA stays open with no project; the user closes it. Not connected now.' }
    if ($gone) { $r.alreadyClosed = $true; $r.next = 'It was not open in TIA any more (closed there, or TIA ended), so nothing was closed or dropped here; the project file holds the last save. Not connected now.' }
    $r
}

function Invoke-ArchiveTool($a) {
    $reason = [string]$a.reason
    if (-not $reason) { return New-Refusal 'reason is required.' }
    $s = Get-BridgeSession
    if (Get-OptionalBool $a 'skip' $false) {
        Register-Archive $s -Skipped
        Write-BridgeLog "Session archive skipped: $reason"
        return @{ ok = $true; skipped = $true; reason = $reason }
    }
    Invoke-ProjectArchive $reason
}

function Invoke-SaveTool($a) {
    $reason = [string]$a.reason
    if (-not $reason) { return New-Refusal 'reason is required.' }
    $s = Get-BridgeSession
    $gate = Test-WriteAllowed $s
    if ($gate) { return New-Refusal $gate }
    $blockers = @(Test-SaveAllowed $s)
    if ($blockers.Count) {
        return @{ ok = $false; refused = 'Save refused.'; blockers = $blockers
                  hint = "$(if (-not $s.archived) { 'Fix and compile; a' } else { 'A' }) failed write is cleared by writing the same object successfully. The user can still save in TIA." }
    }
    $standing = @(Get-SaveStanding $s)
    $null = Invoke-TiaWrite "save ($reason)" -NoTransaction { (Get-TiaProject).Save() }
    Register-Save $s
    $r = @{ ok = $true; saved = $true; reason = $reason; next = "Commit the project repo now (git -C `"$($script:Bridge.repo)`" add -A; git commit)." }
    if ($standing.Count) {
        $r.savedWith = $standing
        $r.note = 'Saved as it stands: savedWith names, per device, the writes not compiled since (deletes too) and the compile errors on record, and notConsistent what TIA held so after the last compile: errors and count count them all. messages shows at most ten, the rest are in logs\*_compile.json of the repo; names shows at most ten, what this session wrote or named first, list shows them all. Quote it to the user. ' +
                  $(if ($s.archived) { 'The session archive in archives\ of the repo is the way back. ' } else { 'This session has no archive, so there is no way back from this save. ' }) + 'This save clears the list: only a compile finds them again.'
    }
    $r
}

function Register-SessionTools {
    Register-McpTool -Name 'tia_status' -Handler { param($a) Invoke-StatusTool $a } -Description (
        'TIA Portal processes and their open projects; the bound project, its repo, devices with their online state (online: changes are refused until the user goes offline in TIA), unsaved changes, archive state, what blocks a save (saveBlockers) and what a save would store uncompiled, over known errors or not consistent (saveStanding). ' +
        'Names other bridges on the same TIA (otherBridges), and scripts changed since this bridge started (scriptsNewer).') -Schema @{
        type = 'object'; properties = @{} }

    Register-McpTool -Name 'connect' -Handler { param($a) Invoke-ConnectTool $a } -Description (
        'Bind to a project open in TIA (project_open opens one when the user named it). Without project: the only open project, else the list. Creates or reuses the ' +
        'project repo, archives the project once per session (writes are refused until that archive exists), names each device with its online state (online: changes are refused until the user goes offline in TIA), and returns docs\project.md (the project notes): read it first, and standards when the repo''s standards\ holds files. ' +
        'A switch to a project in a second TIA process is warned of (secondTia). Refused while the TIA dashboard makes a change report on that TIA or repo: the refusal says since when; tell the user. ' +
        'A session record that cannot be read, or that lacks the result of a write (the bridge stopped during it or could not store it), refuses writes and save (recordUnreadable says why and what ends it): connect reads it again, and ends it when the project has no unsaved changes. ' +
        'Calling it with another project switches the active project. A project is its .ap20 path: a name two open projects share is refused with both paths, and ' +
        'a project at a new path has its own session and archive. A repo belongs to one path: when the repo records another path, connect is refused and names both, changing nothing. ' +
        'Then ask the user: moved (moved=true) or a different project (repo="<other name>", its own repo); never decide this yourself.') -Schema @{
        type = 'object'; properties = @{ project = @{ type = 'string'; description = 'project name or .ap20 path (the path when two open projects share the name)' }
                                         moved = @{ type = 'boolean'; description = 'the user says the project was moved: keep the repo, record the new path' }
                                         repo = @{ type = 'string'; description = 'the user says it is a different project: its repo folder, a plain folder name under the projects root, not a path; default the project name' } } }

    Register-McpTool -Name 'project_open' -Handler { param($a) Invoke-ProjectOpenTool $a } -Description (
        'Open a V20 project file (.ap20) in a TIA with a window, when the user named a project to work on; then connect. It starts the TIA program, which stays open whatever happens to the bridge, and waits up to 90 s. ' +
        'Refused beside a project open in another TIA unless the user says to run both (second=true). A project that is open already only says so. Called again for a project a TIA was started on and waits behind a box, also after a bridge restart, it starts nothing. pending in the result: TIA waits behind a box the user has to answer (boxes names them): ask the user, then connect. A box in a TIA that stands with no project (a person reopening a protected project there) is not seen: a second TIA then stands behind a box of its own, and the result names that TIA in idleTia.') -Schema @{
        type = 'object'; required = @('path')
        properties = @{ path = @{ type = 'string'; description = 'the .ap20 file' }
                        second = @{ type = 'boolean'; description = 'the user says to run a second TIA process beside a project already open' } } }

    Register-McpTool -Name 'project_close' -Handler { param($a) Invoke-ProjectCloseTool $a } -Description (
        'Close the bound project, only in the user''s own words; TIA stays open with no project, and the session ends: the next connect makes a new archive. Closed in TIA already, or TIA ended: alreadyClosed says so, and the binding goes the same. Refused with unsaved changes, as TIA itself would drop them with no question; discard=true only when the user says to.') -Schema @{
        type = 'object'; properties = @{ discard = @{ type = 'boolean'; description = 'the user says to drop the unsaved changes' } } }

    Register-McpTool -Name 'archive' -Handler { param($a) Invoke-ArchiveTool $a } -Description (
        'Write a .zap20 restore point to archives\ of the project repo (newest N kept). skip=true records that the user told you to skip the session archive.') -Schema @{
        type = 'object'; required = @('reason')
        properties = @{ reason = @{ type = 'string' }; skip = @{ type = 'boolean' } } }

    Register-McpTool -Name 'save' -Handler { param($a) Invoke-SaveTool $a } -Description (
        'Save the TIA project. Refused while the session record cannot be read or lacks the result of a write (connect: what ends that; a background session does not read it), and while a write failed and was not redone successfully (a failed import of a name the project does not have holds nothing, nor does an import the bridge refused before TIA was asked). With an archive of this session a save goes through over writes not compiled since and known ' +
        'compile errors: savedWith in the result names them per device (not compiled, deletes too; errors counts all compile errors on record, messages shows at most ten, the rest are in the compile logs; notConsistent what TIA held so on the whole PLC after the last compile, whatever it reported, the user''s own blocks too, at most ten names, what this session wrote or named first, the rest in list), and you quote it to the user; the save clears that list. Without an archive of this session ' +
        '(skipped) it is also refused while, since the last save, a write was not followed by a compile of its scope on its device, or that compile had errors, or what this session wrote or named is left not consistent; another block on that PLC is only named in savedWith. ' +
        "NOTE: a save also stores the user's own unsaved edits in the TIA UI. Save after each finished change, compiled where the project lets you, then commit the project repo.") -Schema @{
        type = 'object'; required = @('reason'); properties = @{ reason = @{ type = 'string' } } }
}
