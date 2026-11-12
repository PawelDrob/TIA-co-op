# Bridge.ps1 - bridge context (settings, active project, per-project session state) and the tool dispatch that
# applies the error contract, writes the log of every call and shortens the response. The dispatch also holds
# a background session (Tools\Background.ps1) to its tools: export only, or the writes as well in write mode;
# and it refuses the write tools until the session archive exists.

function Initialize-BridgeContext([System.Collections.IDictionary]$Settings) {
    $script:Bridge = @{
        settings = $Settings
        portal = $null; project = $null; processId = 0     # Openness objects (Tia.ps1)
        software = $null                                    # cached device software list (Tia.ps1)
        reconnected = $null                                 # note for the next result after a lost connection
        projectName = $null; projectPath = $null; repo = $null
        sessions = @{}                                      # .ap20 path (any case) -> session state (Rules.ps1)
        background = $null                                  # open background session (Tools\Background.ps1)
        tiaEnded = $null                                    # TIA ended (Set-TiaEnded): every TIA call refused until connect
        reportRun = $false                                  # started by a report run of the TIA dashboard (TiaBridge.ps1 -ReportRun)
    }
}

# The session state belongs to the path: a project of the same name at another path (a retrieved archive, a copy) has
# its own archive to make and its own save rules.
# Software: the project's devices, for a session file with the keys from before the save rules counted per device,
# and to drop the keys of devices it no longer has. Returns what was dropped; without Software nothing is.
function Set-BridgeProject([string]$Name, [string]$Path, [string]$Repo, [object[]]$Software = $null) {
    $script:Bridge.projectName = $Name
    $script:Bridge.projectPath = $Path
    $script:Bridge.repo = $Repo
    if (-not $script:Bridge.sessions.ContainsKey($Path)) {
        $s = New-SessionState
        if ($Repo) { Restore-SessionWrites $Repo $s $Software }
        $script:Bridge.sessions[$Path] = $s
    }
    elseif ($Repo -and $script:Bridge.sessions[$Path].unreadable) { Restore-SessionWrites $Repo $script:Bridge.sessions[$Path] $Software }
    if ($null -ne $Software) { Remove-GoneDeviceKeys $script:Bridge.sessions[$Path] $Software }
}

function Get-BridgeSession {
    if (-not $script:Bridge.projectName) { throw 'Not connected to a project: call connect first.' }
    if ($script:Bridge.background) { return $script:Bridge.background.session }
    $script:Bridge.sessions[$script:Bridge.projectPath]
}

# The tools that change the project or a library: the dispatch refuses them until the session archive exists or was
# skipped, before the handler runs. Every registered tool is in this list or in $script:ReadTools, never both:
# Tests\WriteGate.Tests.ps1 fails for a new tool until it is classified.
$script:WriteTools = @('import', 'delete', 'delete_folder', 'save', 'library_create_type', 'library_edit_type', 'library_discard_type', 'library_release_type', 'library_update_usages',
    'library_release_chain', 'library_left_behind', 'master_copy_to_project', 'master_copy_from_project')
# The write tools not marked in the session record before they run (Set-WriteUnderway): neither can record a failed write. save
# only clears what the record holds and delete_folder registers nothing, so the record from before either is sound.
$script:WriteToolsNotMarked = @('save', 'delete_folder')
# The tools that run before the archive: those that only read TIA, the ones that make the archive or open a session, those that open
# or close a project (project_close drops unsaved changes only on discard=true, and there is no later write to guard),
# and those that leave the project's sources alone: compile (its compile results, and what stands in work in the record of an open library change), library_review and
# library_approve (files of the change in the repo), library_open and safety_login (session state of TIA).
$script:ReadTools = @('tia_status', 'connect', 'archive', 'list', 'export', 'full_export', 'compile', 'probe', 'change_report', 'library_open',
    'library_review', 'library_approve', 'safety_login', 'background_open', 'background_close', 'project_open', 'project_close')

# The tools a background session runs (export only); every other tool, a new one included, is refused. compile
# (scope plc or blocks) changes only the copy, which is never saved, so uncompiled blocks export; safety_login is its
# login for the safety program.
$script:BackgroundTools = @('tia_status', 'list', 'export', 'full_export', 'probe', 'change_report', 'library_open', 'compile', 'safety_login',
    'background_open', 'background_close')
# A background session in write mode (the project file itself) also runs the writes of a connect session. Not
# connect (the bridge would leave its own TIA for the user's) and not a writable global library (a file outside
# the project and its archive).
$script:BackgroundWriteTools = $script:BackgroundTools + $script:WriteTools + @('archive', 'library_review', 'library_approve')

# The tools of a bridge a report run of the TIA dashboard starts (TiaAgentStatus\reportrun.py): it reads the project the
# user has open and makes its change report; its connect makes no session archive (Tools\Session.ps1).
$script:ReportRunTools = @('tia_status', 'connect', 'full_export', 'change_report')

function Get-ReportRunToolRefusal([string]$Name) {
    if (-not $script:Bridge.reportRun -or $script:ReportRunTools -contains $Name) { return $null }
    "$Name is refused in a report run of the TIA dashboard: it runs $($script:ReportRunTools -join ', ') only."
}

# Tool arguments that carry a secret, passed in by a tool in a plain session (safety_login password; background_open
# umc_user, umc_password). The dispatch hides their values in the result, the tool log and every stderr line of the
# call, in case a Siemens text quotes one; the bridge itself never writes them.
$script:SecretArguments = [ordered]@{ password = '***'; umc_password = '***'; umc_user = '<umc user>' }

function Get-SecretValues($Arguments) {
    if (-not $Arguments) { return @() }
    foreach ($k in $script:SecretArguments.Keys) {
        $p = $Arguments.PSObject.Properties[$k]
        if ($p -and $p.Value -is [string] -and $p.Value.Length) {
            @{ value = $p.Value; word = ($k -eq 'umc_user'); mask = $script:SecretArguments[$k] }
        }
    }
}

# The value with every secret hidden in its strings: dictionaries and objects in place, a list or string new.
function Hide-Secrets($Value, [object[]]$Secrets) {
    if ($null -eq $Value -or -not @($Secrets).Count) { return , $Value }
    if ($Value -is [string]) { return (Hide-SecretText $Value $Secrets) }
    if ($Value -is [System.Collections.IDictionary]) {
        foreach ($k in @($Value.Keys)) { $Value[$k] = Hide-Secrets $Value[$k] $Secrets }
        return , $Value
    }
    if ($Value -is [System.Collections.IList]) {
        $list = @(foreach ($v in $Value) { , (Hide-Secrets $v $Secrets) })
        return , $list
    }
    if ($Value.PSObject.BaseObject -is [System.Management.Automation.PSCustomObject]) {
        foreach ($p in $Value.PSObject.Properties) { $p.Value = Hide-Secrets $p.Value $Secrets }
    }
    , $Value
}

# A password as a read-only SecureString, for Openness (safety login, UMC login).
function ConvertTo-SecurePassword([string]$Text) {
    $s = New-Object System.Security.SecureString
    foreach ($c in $Text.ToCharArray()) { $s.AppendChar($c) }
    $s.MakeReadOnly()
    $s
}

# $null when the tool may run, else why not.
function Get-BackgroundRefusal([string]$Name, $Arguments) {
    $bg = $script:Bridge.background
    if (-not $bg) { return $null }
    if ($bg.write) {
        if ($script:BackgroundWriteTools -notcontains $Name) {
            return "$Name is refused in a background session in write mode. Call background_close first (it refuses unsaved changes unless discard=true)."
        }
    }
    elseif ($script:BackgroundTools -notcontains $Name) {
        return "$Name is refused in a background session: it opens a copy for export only (tia_status, list, export, full_export, probe, change_report, " +
               "library_open read-only; compile of the copy, never saved). Call background_close; changes go to a project the user opened in TIA (connect), or, when the user asks for it, " +
               'to a background session in write mode (background_open write=true).'
    }
    elseif ($Name -eq 'compile' -and @('plc', 'blocks') -notcontains [string]$Arguments.scope) {
        return 'compile in a background session for export only compiles the PLC software of the copy (scope plc or blocks), never saved.'
    }
    if ($bg.plain -and $Name -eq 'change_report') { return 'change_report is refused in a plain export folder (background_open plain=true): it has no git history.' }
    if ($Name -eq 'library_open' -and $Arguments -and $Arguments.PSObject.Properties['writable'] -and $Arguments.writable) {
        return 'library_open writable=true is refused in a background session; open the library read-only.'
    }
    $null
}

# The archive gate of a write tool: $null when the tool may run, else why not. Without a project there is no session
# that could hold an archive, so a write tool is refused whatever its handler would do.
function Get-ArchiveRefusal([string]$Name) {
    if ($script:WriteTools -notcontains $Name) { return $null }
    if (-not $script:Bridge.projectName) { return 'Not connected to a project: call connect first.' }
    Test-WriteAllowed (Get-BridgeSession)
}

# Marks the write tool in the session record before it runs, so that a restart cannot read a record that lacks a failed write of
# it, with one bridge on the project: the store after the call takes the mark away, and if that store fails, or the bridge stops
# before it, the mark stands. A write tool is marked as it can register a failed write, a new one too, unless it is in
# $script:WriteToolsNotMarked. Returns $null, or why the tool may not run: the mark was not stored.
function Set-WriteUnderway([string]$Name) {
    if ($script:WriteTools -notcontains $Name -or $script:WriteToolsNotMarked -contains $Name -or -not $script:Bridge.repo -or $script:Bridge.background) { return $null }
    try { Save-SessionWrites $script:Bridge.repo (Get-BridgeSession) -WriteUnderway $Name; $null }
    catch {
        Write-BridgeLog "Session record not marked for $Name`: $($_.Exception.Message)"
        "$Name did not run: the session record could not be stored ($($_.Exception.Message)), and a restart could then forget a failed write of it. Nothing was changed. Call it again; if this stays, ask the user what holds the file or the disk."
    }
}

# Memory of a process in MB, $null when it is not running.
function Get-ProcessMemory([int]$ProcessId) {
    if ($ProcessId -le 0) { return $null }
    try { $p = Get-Process -Id $ProcessId -ErrorAction Stop } catch { return $null }
    [ordered]@{ workingSetMB = [int]($p.WorkingSet64 / 1MB); peakWorkingSetMB = [int]($p.PeakWorkingSet64 / 1MB); privateMB = [int]($p.PrivateMemorySize64 / 1MB) }
}

# One timed step of a background session (start, copy or retrieve, open, each tool call, close) with the memory of
# its TIA process and of the bridge after it, and the free memory of the machine: the numbers to compare with the
# window mode.
function New-BackgroundStep([string]$Step, [int]$Ms, [int]$TiaProcessId) {
    $free = $null
    try { $free = [int]((Get-CimInstance Win32_OperatingSystem -ErrorAction Stop).FreePhysicalMemory / 1KB) } catch { }
    $s = [ordered]@{ step = $Step; ms = $Ms; at = (Get-Date).ToString('yyyy-MM-ddTHH:mm:ss')
                     tia = (Get-ProcessMemory $TiaProcessId); bridge = (Get-ProcessMemory $PID); freeMB = $free }
    Write-BridgeLog "background $Step`: $Ms ms, TIA working set $(if ($s.tia) { "$($s.tia.workingSetMB) MB" } else { '-' }), free $free MB"
    Write-StepProgress $Step 'done' $TiaProcessId @{ ms = $Ms }
    $s
}

# The progress line of a background step (Write-BridgeProgress): state start before a long Openness call, done or
# failed after it; pid once the TIA process is known.
function Write-StepProgress([string]$Step, [string]$State, [int]$TiaProcessId = 0, [hashtable]$More = @{}) {
    $p = [ordered]@{ event = 'step'; step = $Step; state = $State }
    foreach ($k in $More.Keys) { $p[$k] = $More[$k] }
    if ($TiaProcessId -gt 0) { $p.pid = $TiaProcessId }
    Write-BridgeProgress $p
}

# TIA ends its own process after a NonRecoverableException, seconds after the call returned (an HMI import with a
# dependent property that does not follow its main property, 2026-10-31; a faceplate type edit, 2026-10-06). Detaches;
# a window session refuses every TIA call until connect (Get-TiaProject), since a reconnect within those seconds
# would attach to the ending process. Cause: what ended it. Returns the note for the result.
function Set-TiaEnded([string]$Cause) {
    Reset-TiaConnection
    if ($script:Bridge.background) {
        return "The background TIA Portal ended or is ending ($Cause). Call background_close, then background_open again." +
               $(if ($script:Bridge.background.write) { ' Changes not saved before are lost; the project file holds the last save.' })
    }
    $script:Bridge.tiaEnded = "TIA Portal ended or is ending ($Cause), even if its window is still there: changes not saved before are lost; the project file holds the last save. Ask the user to restart TIA and open the project, then call connect."
    $script:Bridge.tiaEnded
}

# A caught failure of one item: its error, and tiaGone when TIA does not answer after it.
function Set-ItemError($Item, $ErrorRecord) {
    $Item.ok = $false; $Item.error = ConvertTo-BridgeError $ErrorRecord
    if (-not (Test-TiaAlive)) { $Item.tiaGone = $true; $Item.note = 'TIA Portal does not answer any more.' }
}

# True when an item's error ended TIA: a NonRecoverableException, or TIA did not answer after it.
function Test-ItemEndedTia($Item) { [bool]($Item.error -and ($Item.error.tiaEnded -or $Item.tiaGone)) }

# What ended TIA at an item, for Set-TiaEnded.
function Get-ItemTiaEndedCause($Item) { if ($Item.error.tiaEnded) { $Item.error.type } else { 'it does not answer any more' } }

# The TIA-ended result of a write whose items caught their errors, or $null: an item's error is a
# NonRecoverableException, or TIA did not answer after it (item.tiaGone). Nothing of the write is in TIA any more:
# items that had passed are lost, not rolled back. Kind and What name the write ("import", "release chain").
function Get-TiaEndedResult($Items, [string]$What) {
    $hit = @($Items | Where-Object { Test-ItemEndedTia $_ }) | Select-Object -First 1
    if (-not $hit) { return $null }
    foreach ($i in $Items) {
        if ($i.Contains('rolledBack')) { $i.Remove('rolledBack') }
        if ($i.ok) { $i.ok = $false; $i.lost = $true }
    }
    $name = if ($hit.name) { $hit.name } else { $hit.type }
    @{ ok = $false; items = @($Items); tiaEnded = $true
       note = "Nothing of the $What is in TIA: TIA Portal ended at $name. $(Set-TiaEnded (Get-ItemTiaEndedCause $hit))" }
}

function Invoke-BridgeTool($Name, $Handler, $Arguments) {
    $secrets = @(Get-SecretValues $Arguments)
    $script:BridgeSecrets = $secrets
    # the state file for observers (State.ps1), when the bridge keeps one
    if ($script:BridgeState) { Enter-BridgeStateCall $Name }
    $d = $null
    try { $d = Invoke-BridgeToolCall $Name $Handler $Arguments $secrets }
    finally {
        if ($script:BridgeState) { Exit-BridgeStateCall $Name $(if ($d) { $d.result }) }
        $script:BridgeSecrets = @()
    }
    $d
}

function Invoke-BridgeToolCall($Name, $Handler, $Arguments, [object[]]$Secrets) {
    $started = Get-Date
    $script:CommittedFacts = $null
    $refusal = Get-ReportRunToolRefusal $Name
    if (-not $refusal) { $refusal = Get-BackgroundRefusal $Name $Arguments }
    if (-not $refusal) { $refusal = Get-ArchiveRefusal $Name }
    if (-not $refusal) { $refusal = Set-WriteUnderway $Name }
    if ($refusal) { $r = @{ ok = $false; refused = $refusal } }
    else {
        try { $r = Invoke-McpHandler $Handler $Arguments }
        catch {
            $err = ConvertTo-BridgeError $_
            if ($err.tiaEnded -and (Get-Command Reset-TiaConnection -ErrorAction SilentlyContinue)) { $err.note = Set-TiaEnded $err.type }
            elseif ($err.tiaDisconnected -and (Get-Command Reset-TiaConnection -ErrorAction SilentlyContinue)) {
                $err.note = $(if ($script:Bridge.background) {
                                  'The background TIA Portal ended or dropped the connection. Call background_close, then background_open again.' +
                                  $(if ($script:Bridge.background.write) { ' Changes not saved before are lost; the project file holds the last save.' })
                              }
                              else { 'TIA Portal closed, crashed or dropped the connection. The next call reconnects; check TIA first.' })
                Reset-TiaConnection
            }
            $r = @{ ok = $false; error = $err }
            if ($script:CommittedFacts) {
                foreach ($k in @($script:CommittedFacts.Keys)) { $r[$k] = $script:CommittedFacts[$k] }
                $r.summary = "This failed after TIA had already kept part of it: $(@($script:CommittedFacts.Keys) -join ', ') in this result. Those stand; what was to follow did not run."
            }
            # a compile of PLC software with a safety program needs the safety login (Tools\Safety.ps1)
            if ((@($err.message) + @($err.details)) -match 'permission to modify the safety program') {
                $r.hint = $(if ($script:Bridge.background -and $script:Bridge.background.plain) { 'The safety program needs a login: call safety_login with the password, then compile again.' }
                            else { 'The safety program needs a login: tell the user a password window will open on their screen, call safety_login, then compile again.' })
            }
        }
    }
    if ($script:Bridge.reconnected) { $r.reconnected = $script:Bridge.reconnected; $script:Bridge.reconnected = $null }
    # what a background TIA asked during the call, and the bridge's answer (Tools\Background.ps1)
    if (Get-Command Get-PromptLog -ErrorAction SilentlyContinue) {
        $prompts = @(Get-PromptLog)
        if ($prompts.Count) { $r.prompts = $prompts }
    }
    # a background session writes nothing a save could store, and must not replace the window session's records
    if ($script:Bridge.repo -and $script:Bridge.projectName -and -not $script:Bridge.background) {
        try { Save-SessionWrites $script:Bridge.repo (Get-BridgeSession) }
        catch {
            Write-BridgeLog "Session state not stored: $($_.Exception.Message)"
            $r.recordNotStored = "The session record was not stored ($($_.Exception.Message)). Until the next store a bridge restart reads the record from before this call, which lacks what this call changed, or, with that record gone, refuses writes and saves. No failed write is lost by that: a write tool that can record one is marked in the record as underway before it runs, and a restart refuses writes and saves on that mark too. The next tool call tries again."
        }
    }
    $r.project = $script:Bridge.projectName
    $r.repo = $script:Bridge.repo
    $r.durationMs = [int]((Get-Date) - $started).TotalMilliseconds
    if ($script:Bridge.background -and -not $refusal -and $Name -notlike 'background_*') {
        $r.step = New-BackgroundStep $Name $r.durationMs $script:Bridge.background.processId
        [void]$script:Bridge.background.steps.Add($r.step)
    }
    $r = Hide-Secrets $r $Secrets
    if ($script:Bridge.repo) { $r.log = Write-ToolLog -Repo $script:Bridge.repo -Tool $Name -Result $r }
    else {
        $dir = Join-Path $script:Bridge.settings.projectsRoot '_bridge'
        $r.log = Join-Path $dir (Write-ToolLog -Repo $dir -Tool $Name -Result $r)
    }
    @{ result = $r; text = (Limit-ToolResponse $r $script:Bridge.settings.maxResponseChars) }
}

# Runs Block on an STA thread of its own and returns its output: the bridge runs on an MTA thread (TiaBridge.ps1), and a window
# such as the safety password's needs STA. Block runs in a runspace of its own: it gets only its arguments, none of the
# bridge's functions or variables. What it throws is thrown here.
function Invoke-OnStaThread([scriptblock]$Block, [object[]]$ArgumentList = @()) {
    $rs = [runspacefactory]::CreateRunspace()
    $rs.ApartmentState = 'STA'; $rs.ThreadOptions = 'ReuseThread'; $rs.Open()
    $ps = [powershell]::Create(); $ps.Runspace = $rs
    try {
        $null = $ps.AddScript($Block.ToString())
        foreach ($a in $ArgumentList) { $null = $ps.AddArgument($a) }
        try { $out = $ps.Invoke() }
        catch { $e = $_.Exception; while ($e.InnerException -and $e -is [System.Management.Automation.MethodInvocationException]) { $e = $e.InnerException }; throw $e }
        if ($ps.Streams.Error.Count) { throw $ps.Streams.Error[0].Exception }
        $out
    }
    finally { $ps.Dispose(); $rs.Dispose() }
}
