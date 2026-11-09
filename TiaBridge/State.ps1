# State.ps1 - the state file of this bridge process for observers (TiaAgentStatus: Claude Code status line, herdr
# watcher): <projectsRoot>\_bridge\sessions\<bridge pid>.json, written at the start and end of every tool call and on
# progress events (Write-BridgeProgress), removed when the bridge ends. Shape after the core's running\<pid>.json:
# v, pid, client, session, project, operation. The bridge cannot write during one blocking
# Openness call, so a reader computes elapsed time, memory and CPU itself from operation.since and tia.pid.
# A file whose pid is dead (or whose pid started after `started`: reused) is an orphan: readers skip it, the next
# bridge start deletes it. Best effort: a failed write goes to stderr and never fails a tool call.

$script:BridgeStateVersion = 1
$script:BridgeState = $null          # set by Start-BridgeState; the hooks do nothing while it is $null
$script:BridgeStateObjectMs = 1000   # object progress events are written at most once per this time

function Get-BridgeStateDir([string]$ProjectsRoot) { Join-Path $ProjectsRoot '_bridge\sessions' }

function Get-BridgeStateTime { (Get-Date).ToString('yyyy-MM-ddTHH:mm:ss.fffzzz') }

# The Claude Code process this bridge belongs to: CLAUDE_PID when Claude passes it, else the nearest ancestor named
# claude or node (a bridge Claude starts is its child), else the parent.
function Get-BridgeClaudeProcess {
    if ($env:CLAUDE_PID -match '^\d+$') { return @{ pid = [int]$env:CLAUDE_PID; from = 'env' } }
    $id = $PID; $parent = 0
    for ($i = 0; $i -lt 4; $i++) {
        $p = Get-CimInstance Win32_Process -Filter "ProcessId=$id" -ErrorAction Stop
        if (-not $p -or -not $p.ParentProcessId) { break }
        $id = [int]$p.ParentProcessId
        if (-not $parent) { $parent = $id }
        $q = Get-CimInstance Win32_Process -Filter "ProcessId=$id" -ErrorAction SilentlyContinue
        if ($q -and $q.Name -match '^(claude|node)(\.exe)?$') { return @{ pid = $id; from = 'ancestor' } }
    }
    @{ pid = $parent; from = 'parent' }
}

# Deletes the state files of bridges that are gone. A file the bridge cannot read or delete is left alone.
function Remove-OrphanBridgeStates([string]$Dir) {
    foreach ($f in @(Get-ChildItem -LiteralPath $Dir -Filter '*.json' -ErrorAction SilentlyContinue)) {
        if ($f.BaseName -notmatch '^\d+$') { continue }
        $owner = [int]$f.BaseName
        if ($owner -eq $PID) { continue }
        $p = Get-Process -Id $owner -ErrorAction SilentlyContinue
        if ($p) {
            try { $started = [DateTime]((Get-Content -LiteralPath $f.FullName -Raw | ConvertFrom-Json).started) } catch { continue }
            try { if ($p.StartTime -le $started.AddSeconds(5)) { continue } } catch { continue }
        }
        try { Remove-Item -LiteralPath $f.FullName -Force -ErrorAction Stop } catch { }
    }
}

# The other bridges with a TIA among Ids (with no Ids, with any TIA), from their state files: pid, tia, project, session. A file that cannot be read, or whose
# bridge is gone or whose pid was taken again, says nothing.
function Get-OtherBridges([string]$Dir, [int[]]$TiaIds) {
    foreach ($f in @(Get-ChildItem -LiteralPath $Dir -Filter '*.json' -ErrorAction SilentlyContinue)) {
        if ($f.BaseName -notmatch '^\d+$' -or [int]$f.BaseName -eq $PID) { continue }
        $p = Get-Process -Id ([int]$f.BaseName) -ErrorAction SilentlyContinue
        if (-not $p) { continue }
        try {
            $doc = Get-Content -LiteralPath $f.FullName -Raw | ConvertFrom-Json
            if ($p.StartTime -gt ([DateTime]$doc.started).AddSeconds(5)) { continue }
        }
        catch { continue }
        if (-not $doc.tia -or ($PSBoundParameters.ContainsKey('TiaIds') -and $TiaIds -notcontains [int]$doc.tia.pid)) { continue }
        [ordered]@{ pid = [int]$f.BaseName; tia = [int]$doc.tia.pid; project = $doc.project; session = $doc.session }
    }
}

# The bridge's scripts changed after Since, by name relative to Dir: the process still runs the old code. Tests stay out.
function Get-NewerBridgeScripts([string]$Dir, [datetime]$Since) {
    $Dir = (Get-Item -LiteralPath $Dir).FullName
    foreach ($folder in @($Dir, (Join-Path $Dir 'Tools'))) {
        foreach ($f in @(Get-ChildItem -LiteralPath $folder -Filter '*.ps1' -File -ErrorAction SilentlyContinue)) {
            if ($f.LastWriteTime -gt $Since) { $f.FullName.Substring($Dir.TrimEnd('\').Length + 1) }
        }
    }
}

function Start-BridgeState([string]$ProjectsRoot) {
    try {
        $dir = Get-BridgeStateDir $ProjectsRoot
        [void][System.IO.Directory]::CreateDirectory($dir)
        Remove-OrphanBridgeStates $dir
        $claude = $null
        try { $claude = Get-BridgeClaudeProcess } catch { Write-BridgeLog "State file: Claude process not found: $($_.Exception.Message)" }
        $script:BridgeState = @{
            path = Join-Path $dir "$PID.json"
            started = Get-BridgeStateTime
            claude = $claude
            session = $(if ($env:CLAUDE_CODE_SESSION_ID) { $env:CLAUDE_CODE_SESSION_ID } else { $null })
            herdr = $(if ($env:HERDR_TAB_ID -or $env:HERDR_PANE_ID) { [ordered]@{ tab = $env:HERDR_TAB_ID; pane = $env:HERDR_PANE_ID } } else { $null })
            project = $null; boundSince = $null
            operation = $null; lastOperation = $null; lastPrompt = $null
            pendingTia = 0                  # the TIA pid of a background_open in progress, or of a connect about to attach (progress event tia)
            pendingWindow = $false          # that TIA has a window: a connect's (event tia with window)
            written = [DateTime]::MinValue
        }
        Write-BridgeState
    }
    catch { Write-BridgeLog "State file not started: $($_.Exception.Message)" }
}

function Stop-BridgeState {
    if (-not $script:BridgeState) { return }
    try { if (Test-Path -LiteralPath $script:BridgeState.path) { Remove-Item -LiteralPath $script:BridgeState.path -Force -ErrorAction Stop } }
    catch { Write-BridgeLog "State file not removed: $($_.Exception.Message)" }
    $script:BridgeState = $null
}

# The file content from the bridge context and the state of the call that runs.
function Get-BridgeStateDocument {
    $st = $script:BridgeState
    $b = $script:Bridge
    $project = $(if ($b) { $b.projectName } else { $null })
    if ($project -ne $st.project) { $st.project = $project; $st.boundSince = $(if ($project) { Get-BridgeStateTime } else { $null }) }
    $tia = $null
    $tiaPid = $(if ($st.pendingTia) { $st.pendingTia } elseif ($b) { [int]$b.processId } else { 0 })
    if ($tiaPid -gt 0) { $tia = [ordered]@{ pid = $tiaPid; window = $(if ($st.pendingTia) { [bool]$st.pendingWindow } else { -not ($b -and $b.background) }) } }
    $now = Get-BridgeStateTime
    [ordered]@{
        v = $script:BridgeStateVersion
        pid = $PID; client = $(if ($b -and $b.reportRun) { 'report-run' } else { 'mcp' }); started = $st.started; updated = $now
        session = $st.session
        claude = $st.claude
        herdr = $st.herdr
        project = $project; repo = $(if ($b) { $b.repo } else { $null }); boundSince = $st.boundSince
        tia = $tia
        operation = $st.operation
        lastOperation = $st.lastOperation
        lastPrompt = $st.lastPrompt
    }
}

# Temp file + rename, so a reader never sees half a file. Never throws.
function Write-BridgeState {
    $st = $script:BridgeState
    if (-not $st) { return }
    try {
        $json = ConvertTo-Json -InputObject (Get-BridgeStateDocument) -Depth 6
        $tmp = "$($st.path).tmp"
        [System.IO.File]::WriteAllText($tmp, $json, (New-Object System.Text.UTF8Encoding $false))
        if ([System.IO.File]::Exists($st.path)) { [System.IO.File]::Replace($tmp, $st.path, [NullString]::Value) }
        else { [System.IO.File]::Move($tmp, $st.path) }
        $st.written = [DateTime]::UtcNow
    }
    catch { Write-BridgeLog "State file not written: $($_.Exception.Message)" }
}

# The newest prompt of a background TIA (Tools\Background.ps1 queues them) as lastPrompt, without taking it from the
# queue (the dispatch puts the queue into the tool result).
function Update-BridgeStatePrompt([object[]]$Prompts) {
    $Prompts = @(@($Prompts) | Where-Object { $_ })     # a result without prompts arrives as @($null)
    if (-not $Prompts -and ('TiaBridgePromptGuard' -as [type])) {
        $q = @([TiaBridgePromptGuard]::Seen.ToArray())
        if ($q.Count) {
            $p = @(foreach ($t in $q[-1]) { Hide-SecretText ([string]$t) $script:BridgeSecrets })
            $Prompts = @([ordered]@{ kind = $p[0]; caption = $p[1]; text = $p[2]; answer = $p[5] })
        }
    }
    if (-not @($Prompts).Count) { return }
    $p = @($Prompts)[-1]
    $last = $script:BridgeState.lastPrompt
    if ($last -and $last.kind -eq $p.kind -and $last.caption -eq $p.caption -and $last.text -eq $p.text -and $last.answer -eq $p.answer) { return }
    $script:BridgeState.lastPrompt = [ordered]@{ at = (Get-BridgeStateTime); kind = $p.kind; caption = $p.caption; text = $p.text; answer = $p.answer }
}

# Dispatch hook: a tool call starts.
function Enter-BridgeStateCall([string]$Name) {
    if (-not $script:BridgeState) { return }
    try {
        $script:BridgeState.operation = [ordered]@{ name = $Name; since = (Get-BridgeStateTime) }
        $script:BridgeState.pendingTia = 0; $script:BridgeState.pendingWindow = $false
        Write-BridgeState
    }
    catch { Write-BridgeLog "State file: $($_.Exception.Message)" }
}

# Dispatch hook: a tool call ended with result R (its prompts already taken from the queue).
function Exit-BridgeStateCall([string]$Name, $Result) {
    if (-not $script:BridgeState) { return }
    try {
        $st = $script:BridgeState
        Update-BridgeStatePrompt @($Result.prompts)
        $st.lastOperation = [ordered]@{ name = $Name; ok = [bool]$Result.ok; ended = (Get-BridgeStateTime); ms = [int]$Result.durationMs }
        $st.operation = $null
        $st.pendingTia = 0; $st.pendingWindow = $false
        Write-BridgeState
    }
    catch { Write-BridgeLog "State file: $($_.Exception.Message)" }
}

# Progress hook (Write-BridgeProgress): the step, part and n of m of the call that runs.
function Update-BridgeStateProgress([System.Collections.IDictionary]$Fields) {
    $st = $script:BridgeState
    if (-not $st -or -not $st.operation) { return }
    try {
        $op = $st.operation
        switch ([string]$Fields.event) {
            'tia' { $st.pendingTia = [int]$Fields.pid; $st.pendingWindow = [bool]$Fields.window }
            'step' {
                if ($Fields.state -eq 'start') { $op.step = [string]$Fields.step } else { $op.Remove('step') }
                if ($Fields.pid -and -not $st.pendingTia -and -not $script:Bridge.background) { $st.pendingTia = [int]$Fields.pid }
            }
            'part' {
                if ($Fields.state -eq 'start') { $op.part = [string]$Fields.part; if ($Fields.device) { $op.device = [string]$Fields.device } else { $op.Remove('device') } }
                else { foreach ($k in 'part', 'device', 'n', 'of') { $op.Remove($k) } }
            }
            'object' {
                $op.n = [int]$Fields.n; $op.of = [int]$Fields.of
                if ($Fields.kind) { $op.kind = [string]$Fields.kind }
                if (([DateTime]::UtcNow - $st.written).TotalMilliseconds -lt $script:BridgeStateObjectMs) { return }
            }
            default { return }
        }
        Update-BridgeStatePrompt @()
        Write-BridgeState
    }
    catch { Write-BridgeLog "State file: $($_.Exception.Message)" }
}
