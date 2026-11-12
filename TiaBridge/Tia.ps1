# Tia.ps1 - Openness DLL loading, attach, object lookup, error unwrapping, result dumps.
# Openness facts used here: docs/agent/openness-v20.md, docs/agent/wincc-comfort-openness.md section 2.

# ------------------------------------------------------------------ error contract

# PowerShell wraps exceptions of .NET method calls; the Siemens exception is underneath.
function Get-InnermostWrapped([Exception]$Ex) {
    while ($Ex.InnerException -and (
            $Ex -is [System.Management.Automation.MethodInvocationException] -or
            $Ex -is [System.Management.Automation.GetValueInvocationException] -or
            $Ex -is [System.Management.Automation.SetValueInvocationException] -or
            $Ex -is [System.Reflection.TargetInvocationException] -or
            ($Ex -is [System.Management.Automation.RuntimeException] -and $Ex.GetType() -eq [System.Management.Automation.RuntimeException]))) {
        $Ex = $Ex.InnerException
    }
    $Ex
}

# Exception or ErrorRecord -> @{ type; message; details[]; inner[]; tiaDisconnected; tiaEnded }
# tiaEnded: a NonRecoverableException in the chain; TIA ends its own process after it (Set-TiaEnded).
function ConvertTo-BridgeError($ErrorOrException) {
    $ex = if ($ErrorOrException -is [System.Management.Automation.ErrorRecord]) { $ErrorOrException.Exception } else { $ErrorOrException }
    $outer = $ex
    $ex = Get-InnermostWrapped $ex
    $details = @()
    if ($ex.PSObject.Properties['DetailMessageData'] -and $ex.DetailMessageData) {
        foreach ($d in $ex.DetailMessageData) {
            $details += $(if ($d.DetailText) { "$($d.Text): $($d.DetailText)" } else { [string]$d.Text })
        }
    }
    $inner = @()
    $i = $ex.InnerException
    while ($i) { $inner += @{ type = $i.GetType().FullName; message = $i.Message }; $i = $i.InnerException }
    $disconnected = $false; $ended = $false
    $c = $outer
    while ($c) {
        if ($c -is [System.ObjectDisposedException] -or $c.GetType().Name -match 'ObjectDisposed|NonRecoverable|ProcessExited') { $disconnected = $true }
        if ($c.GetType().Name -match 'NonRecoverable') { $ended = $true }
        $c = $c.InnerException
    }
    $r = @{ type = $ex.GetType().FullName; message = $ex.Message; details = $details; inner = $inner; tiaDisconnected = $disconnected; tiaEnded = $ended }
    # where in the bridge it happened: finds a bridge bug, and names the bridge line that made a failing Openness call
    if ($ErrorOrException -is [System.Management.Automation.ErrorRecord] -and $ErrorOrException.ScriptStackTrace) {
        $r.at = ($ErrorOrException.ScriptStackTrace -split "`r?`n" | Select-Object -First 3) -join ' <- '
    }
    $r
}

# True for a NonRecoverableException in the chain. A catch that would keep going rethrows it, so that it reaches the
# dispatch (Set-TiaEnded): catch { if (Test-TiaEndedError $_) { throw }; ... }
function Test-TiaEndedError($ErrorOrException) { [bool](ConvertTo-BridgeError $ErrorOrException).tiaEnded }

# How many times Read-TiaList reads a list in all.
$script:TiaListReads = 3

# Runs Read, a loop that only reads TIA lists, and outputs what it gave once a whole read went through. The bridge attaches
# from an MTA thread (TiaBridge.ps1), so TIA, a person or another program can change a list between two pages of a read:
# "Collection was modified" reads it again, at most TiaListReads times in all; any other error is thrown at once. Never for
# a loop that writes: a second run would write again.
function Read-TiaList([scriptblock]$Read) {
    for ($readNo = 1; ; $readNo++) {
        try { $readItems = @(& $Read); break }
        catch {
            $readError = ConvertTo-BridgeError $_
            $readChanged = (@($readError.message) + @($readError.details) + @($readError.inner | ForEach-Object { $_.message })) -match 'Collection was modified'
            if (-not $readChanged -or $readNo -ge $script:TiaListReads) { throw }
            Write-BridgeLog "TIA changed a list during the read; read $($readNo + 1) of $script:TiaListReads."
        }
    }
    foreach ($o in $readItems) { $o }
}

# CompilerResult, DocumentImportResult, DocumentExportResult (or anything with State/Messages) -> nested hashtables
function ConvertTo-ResultTree($Result) {
    if ($null -eq $Result) { return $null }
    $t = [ordered]@{}
    $p = $Result.PSObject.Properties
    if ($p['Path']) { $t.path = [string]$Result.Path }
    if ($p['State']) { $t.state = [string]$Result.State }
    if ($p['Description']) { $t.description = [string]$Result.Description }
    elseif ($p['Message']) { $t.description = [string]$Result.Message }
    if ($p['ErrorCount']) { $t.errors = [int]$Result.ErrorCount }
    if ($p['WarningCount']) { $t.warnings = [int]$Result.WarningCount }
    if ($p['Messages']) { $t.messages = @(foreach ($m in $Result.Messages) { ConvertTo-ResultTree $m }) }
    $t
}

function Limit-Text([string]$Text, [int]$Max) { if ($Text.Length -le $Max) { $Text } else { $Text.Substring(0, $Max) + " ... [$($Text.Length) chars]" } }

# The MCP response may be shortened; the log keeps everything. Failed items come first, each reduced to its error.
function Limit-ToolResponse($Result, [int]$MaxChars) {
    $json = ConvertTo-Json $Result -Depth 64 -Compress
    if ($json.Length -le $MaxChars) { return $json }

    $short = [ordered]@{}
    foreach ($k in $Result.Keys) { if ($k -ne 'items') { $short[$k] = $Result[$k] } }
    $short.truncated = $true
    # the tool's own note stays in front: it can be the only word that TIA ended
    $short.note = (@($Result.note, "Response shortened to $MaxChars chars; the full result is in the log file.") | Where-Object { $_ }) -join ' '
    foreach ($k in @($short.Keys)) {   # oversized top-level values (e.g. a compile tree) stay in the log only
        if ($k -notin 'ok', 'project', 'repo', 'log', 'truncated', 'note' -and (ConvertTo-Json $short[$k] -Depth 64 -Compress).Length -gt $MaxChars / 4) {
            $short[$k] = '[in the log file]'
        }
    }
    if ($Result.Contains('items')) {
        $all = @($Result.items)
        # items of a list carry no ok field; only an item that says ok = false has failed
        $isFailed = { param($i) ($i -is [System.Collections.IDictionary]) -and $i.Contains('ok') -and -not $i.ok }
        $failed = @($all | Where-Object { & $isFailed $_ })
        $short.itemCount = $all.Count
        $short.failedCount = $failed.Count
        $ordered = @($failed) + @($all | Where-Object { -not (& $isFailed $_) })
        $reduced = @(foreach ($i in $ordered) {
            $s = [ordered]@{ name = $i.name }
            if (($i -is [System.Collections.IDictionary]) -and $i.Contains('ok')) { $s.ok = [bool]$i.ok }
            if ($i.folder) { $s.folder = $i.folder }
            foreach ($key in 'errors', 'warnings') { if (($i -is [System.Collections.IDictionary]) -and $i.Contains($key)) { $s[$key] = $i[$key] } }
            if ($i.path) { $s.path = $i.path }
            if ($i.error) {
                $s.error = @{ type = $i.error.type; message = (Limit-Text $i.error.message 500)
                              details = @($i.error.details | Select-Object -First 5 | ForEach-Object { Limit-Text $_ 300 }) }
            }
            $s
        })
        # as many items as fit
        $short.items = @()
        $budget = $MaxChars - (ConvertTo-Json $short -Depth 64 -Compress).Length - 200
        $kept = New-Object System.Collections.ArrayList
        foreach ($s in $reduced) {
            $len = (ConvertTo-Json $s -Depth 64 -Compress).Length + 1
            if ($len -gt $budget) { break }
            [void]$kept.Add($s); $budget -= $len
        }
        $short.items = @($kept)
        if ($kept.Count -lt $reduced.Count) { $short.itemsOmitted = $reduced.Count - $kept.Count }
    }
    $json = ConvertTo-Json $short -Depth 64 -Compress
    if ($json.Length -gt $MaxChars) {
        $json = ConvertTo-Json ([ordered]@{ ok = $Result.ok; project = $Result.project; log = $Result.log; truncated = $true
                                            note = 'Result too large for the response; read the log file.' }) -Compress
    }
    $json
}

# ------------------------------------------------------------------ attach

# Open: @{ processId; name; path } per TIA process with a project. Requested: '' or a project name or .ap20 path.
# A name that two open projects share chooses neither: their paths do.
function Select-TiaProject([object[]]$Open, [string]$Requested) {
    $Open = @($Open | Where-Object { $_ })
    if (-not $Open.Count) { throw 'No TIA Portal with an open project. If the user named a project to work on: project_open with its .ap20 path, then connect. Otherwise ask the user which project, or to open it in TIA.' }
    $shared = @($Open | Group-Object { $_.name } | Where-Object { $_.Count -gt 1 } | ForEach-Object { $_.Name })
    $names = @($Open | ForEach-Object { if ($shared -contains $_.name) { $_.path } else { $_.name } } | Sort-Object) -join ', '
    if (-not $Requested) {
        if ($Open.Count -eq 1) { return $Open[0] }
        throw "Several projects are open: $names. Call connect with one of these."
    }
    $hit = @($Open | Where-Object { $_.name -eq $Requested -or $_.path -eq $Requested })
    if (-not $hit.Count) { throw "Project '$Requested' is not open in TIA. Open projects: $names." }
    if ($hit.Count -gt 1) { throw "Several open projects are named '$Requested': $(@($hit | ForEach-Object { $_.path } | Sort-Object) -join ', '). Call connect with the .ap20 path of one." }
    $hit[0]
}

# The Openness DLL of the V20 API under tiaRoot; the tests that need TIA skip when it is missing.
function Get-OpennessDll([string]$TiaRoot) {
    Join-Path $TiaRoot 'PublicAPI\V20\Siemens.Engineering.dll'
}

# Why PublicAPI\V20 is missing: the TIA Portal folders beside tiaRoot (Portal V*) and tiaRoot itself, each with
# the Openness API versions under its PublicAPI folder. TiaBridge works with the V20 API only.
function Get-OpennessMissingMessage([string]$TiaRoot) {
    $dll = Get-OpennessDll $TiaRoot
    $root = $TiaRoot.TrimEnd([char]'\')
    $parent = Split-Path -Parent $root
    $dirs = @()
    if ($parent -and (Test-Path -LiteralPath $parent)) { $dirs = @(Get-ChildItem -LiteralPath $parent -Directory -Filter 'Portal V*' | ForEach-Object { $_.FullName }) }
    if ((Test-Path -LiteralPath $root) -and $dirs -notcontains $root) { $dirs += $root }
    $found = @(foreach ($d in ($dirs | Sort-Object)) {
        $api = @(Get-ChildItem -LiteralPath (Join-Path $d 'PublicAPI') -Directory -ErrorAction SilentlyContinue | ForEach-Object { $_.Name } | Sort-Object)
        "$d ($(if ($api.Count) { "Openness $($api -join ', ')" } else { 'no Openness' }))"
    })
    $where = if ($found.Count) { $found -join '; ' } else { "no TIA Portal under $parent" }
    "TIA Portal V20 with TIA Openness required: $dll not found. Found: $where. Install TIA Portal V20 with the TIA Openness option; " +
        'if V20 is installed in another folder, set tiaRoot in TiaBridge\settings.json.'
}

# $null when the Windows user is in the group 'Siemens TIA Openness' (or the group does not exist), else why TIA
# will refuse Openness. connect and background_open check it before they call TIA.
function Test-OpennessGroup {
    try { $sid = ([System.Security.Principal.NTAccount]'Siemens TIA Openness').Translate([System.Security.Principal.SecurityIdentifier]) }
    catch { return $null }
    $id = [System.Security.Principal.WindowsIdentity]::GetCurrent()
    if (@($id.Groups | Where-Object { $_.Value -eq $sid.Value }).Count) { return $null }
    "The Windows user $($id.Name) is not in the group 'Siemens TIA Openness' (or was added after the last logon: log off and on); TIA refuses Openness without it."
}

# Loads PublicAPI\V20\Siemens.Engineering.dll once per process. Add-Type on the DLL fails (it enumerates all
# types); dependencies come from the API folder through a C# resolver (a script block resolver recursed into
# itself on Attach: StackOverflowException).
function Import-Openness([string]$TiaRoot) {
    if ('Siemens.Engineering.TiaPortal' -as [type]) { return }
    if (-not [Environment]::Is64BitProcess) { throw 'TiaBridge needs the 64-bit Windows PowerShell.' }
    $dll = Get-OpennessDll $TiaRoot
    $apiDir = Split-Path -Parent $dll
    if (-not (Test-Path $dll)) { throw (Get-OpennessMissingMessage $TiaRoot) }
    if (-not ('TiaBridgeOpennessResolver' -as [type])) {
        Add-Type -TypeDefinition @"
using System; using System.IO; using System.Reflection;
public static class TiaBridgeOpennessResolver {
    static string dir;
    [ThreadStatic] static bool busy;
    public static void Register(string apiDir) { dir = apiDir; AppDomain.CurrentDomain.AssemblyResolve += Resolve; }
    static Assembly Resolve(object sender, ResolveEventArgs e) {
        if (busy) return null;
        string name = new AssemblyName(e.Name).Name;
        if (!name.StartsWith("Siemens.", StringComparison.OrdinalIgnoreCase)) return null;
        if (name.EndsWith(".resources", StringComparison.OrdinalIgnoreCase)) return null;
        string path = Path.Combine(dir, name + ".dll");
        if (!File.Exists(path)) return null;
        try { busy = true; return Assembly.LoadFrom(path); } finally { busy = false; }
    }
}
"@
    }
    [TiaBridgeOpennessResolver]::Register($apiDir)
    [void][System.Reflection.Assembly]::LoadFrom($dll)
}

# Every TIA Portal process: @{ processId; name; path; mode } (name and path empty without an open project).
function Get-TiaProcesses {
    foreach ($p in [Siemens.Engineering.TiaPortal]::GetProcesses()) {
        $path = if ($p.ProjectPath) { $p.ProjectPath.FullName } else { '' }
        @{ processId = $p.Id; path = $path; mode = [string]$p.Mode
           name = $(if ($path) { [System.IO.Path]::GetFileNameWithoutExtension($path) } else { '' }) }
    }
}

function Reset-TiaConnection {
    if ($script:Bridge.portal) { try { $script:Bridge.portal.Dispose() } catch { } }   # detaches; TIA stays open
    $script:Bridge.portal = $null; $script:Bridge.project = $null; $script:Bridge.processId = 0; $script:Bridge.software = $null
}

function Test-TiaAlive {
    if (-not $script:Bridge.project) { return $false }
    # a project closed under the bridge reads an empty name, with no exception (2026-11-04)
    try { $name = $script:Bridge.project.Name; $null = Get-Process -Id $script:Bridge.processId -ErrorAction Stop; [bool]$name }
    catch { $false }
}

# The project at Path in an attached TIA. No other project stands in for it: writes would go to the wrong one. Detaches
# when it is not there.
function Find-PortalProject($Portal, [string]$Path) {
    $project = @(Read-TiaList { foreach ($p in $Portal.Projects) { $p } }) | Where-Object { $_.Path.FullName -eq $Path } | Select-Object -First 1
    if ($project) { return $project }
    $Portal.Dispose()
    throw "The TIA process does not have the project $Path open any more. Ask the user to open it, then call connect."
}

# Attaches to the process of the selected project (Select-TiaProject). The first attach of a bridge process
# raises the Openness access dialog in TIA; the user confirms it.
function Connect-Tia($Selected) {
    if ($script:Bridge.processId -eq $Selected.processId -and (Test-TiaAlive) -and $script:Bridge.project.Path.FullName -eq $Selected.path) { return }
    Reset-TiaConnection
    $proc = [Siemens.Engineering.TiaPortal]::GetProcesses() | Where-Object { $_.Id -eq $Selected.processId } | Select-Object -First 1
    if (-not $proc) { throw "TIA Portal process $($Selected.processId) is gone." }
    Write-BridgeLog "Attaching to TIA process $($Selected.processId); confirm the Openness access dialog in TIA."
    $portal = $proc.Attach()
    $project = Find-PortalProject $portal $Selected.path
    $script:Bridge.portal = $portal; $script:Bridge.project = $project; $script:Bridge.processId = $Selected.processId
}

# The bound project; reconnects after TIA dropped the connection (same .ap20 path).
function Get-TiaProject {
    if (-not $script:Bridge.projectPath) { throw 'Not connected to a project: call connect first.' }
    # the TIA of a background session is the bridge's own: nothing to reconnect to when it is gone
    if ($script:Bridge.background) {
        if (Test-TiaAlive) { return $script:Bridge.project }
        throw "The background TIA Portal (process $($script:Bridge.background.processId)) ended or dropped the connection. Call background_close, then background_open again."
    }
    # no reconnect after TIA ended (Set-TiaEnded): it would attach to the process that is still ending
    if ($script:Bridge.tiaEnded) { throw $script:Bridge.tiaEnded }
    if (-not (Test-TiaAlive)) {
        $wasAttached = [bool]$script:Bridge.project
        Reset-TiaConnection
        Import-Openness $script:Bridge.settings.tiaRoot
        $open = @(Get-TiaProcesses | Where-Object { $_.path })
        $lost = if ($wasAttached) { 'The connection to TIA Portal was lost (TIA closed or crashed, or the project was closed). ' } else { '' }
        if (-not @($open | Where-Object { $_.path -eq $script:Bridge.projectPath }).Count) {
            throw "${lost}Project $($script:Bridge.projectPath) is not open in TIA any more. Ask the user to open it, then call connect."
        }
        Connect-Tia (Select-TiaProject $open $script:Bridge.projectPath)
        if ($lost) { $script:Bridge.reconnected = "${lost}Reconnected; check in TIA that the last changes are there before going on." }
        Write-BridgeLog "Reconnected to $($script:Bridge.projectPath)"
    }
    $script:Bridge.project
}

function Get-TiaService($Obj, [type]$Type) {
    [Siemens.Engineering.IEngineeringServiceProvider].GetMethod('GetService').MakeGenericMethod($Type).Invoke($Obj.PSObject.BaseObject, $null)
}

# PLC and HMI software of the project: @{ device; kind = 'plc'|'hmi'; software; deviceObject; deviceItem (the item that holds the software) }
function Get-TiaSoftwareList {
    $project = Get-TiaProject
    if ($script:Bridge.software) { return $script:Bridge.software }
    $list = @(Read-TiaList {
        $devices = New-Object System.Collections.ArrayList
        foreach ($d in $project.Devices) { [void]$devices.Add($d) }
        $stack = New-Object System.Collections.Stack
        foreach ($g in $project.DeviceGroups) { $stack.Push($g) }
        while ($stack.Count) { $g = $stack.Pop(); foreach ($d in $g.Devices) { [void]$devices.Add($d) }; foreach ($s in $g.Groups) { $stack.Push($s) } }
        foreach ($dev in $devices) {
            $items = New-Object System.Collections.Stack
            foreach ($i in $dev.DeviceItems) { $items.Push($i) }
            while ($items.Count) {
                $item = $items.Pop()
                foreach ($i in $item.DeviceItems) { $items.Push($i) }
                $sc = Get-TiaService $item ([Siemens.Engineering.HW.Features.SoftwareContainer])
                if (-not $sc) { continue }
                $kind = $(if ($sc.Software -is [Siemens.Engineering.SW.PlcSoftware]) { 'plc' } elseif ($sc.Software -is [Siemens.Engineering.Hmi.HmiTarget]) { 'hmi' })
                if ($kind) { @{ device = $dev.Name; kind = $kind; software = $sc.Software; deviceObject = $dev; deviceItem = $item } }
            }
        }
    })
    $script:Bridge.software = $list
    $list
}

# The OnlineProvider of the device item that holds the software (the CPU); $null where TIA offers none. Which device
# items carry one, an HMI's among them, is not probed yet.
function Get-OnlineProvider($Item) {
    $t = 'Siemens.Engineering.Online.OnlineProvider' -as [type]
    if (-not $t -or -not $Item) { return $null }
    Get-TiaService $Item $t
}

# Entries of Get-TiaSoftwareList -> @{ device; kind; online }, read now: online is TIA's OnlineState in lower case
# ('online', 'offline', 'connecting', ...), or 'unknown' where it cannot be read. Never throws but for TIA ended.
function Get-DeviceStates([object[]]$Software) {
    foreach ($s in @($Software)) {
        $state = 'unknown'
        try {
            $p = Get-OnlineProvider $s.deviceItem
            if ($p -and [string]$p.State) { $state = ([string]$p.State).ToLowerInvariant() }
        }
        catch {
            if (Test-TiaEndedError $_) { throw }
            Write-BridgeLog "Online state of $($s.device): $($_.Exception.Message)"
        }
        @{ device = $s.device; kind = $s.kind; online = $state }
    }
}

# TypeIdentifier OrderNumber:<MLFB>[/<fw>][//<additional>] of a device: the device's own, else the first device item
# (breadth first, in TIA's order) that carries one. Where TIA puts it for an HMI is not probed yet, so
# every read is guarded: $null, never an exception, and the reason goes to stderr.
function Get-DeviceTypeIdentifier($Device) {
    $queue = New-Object System.Collections.Queue
    $queue.Enqueue($Device)
    while ($queue.Count) {
        $o = $queue.Dequeue()
        try {
            $id = [string]$o.TypeIdentifier
            if ($id -like 'OrderNumber:*') { return $id }
            foreach ($i in @($o.DeviceItems)) { if ($null -ne $i) { $queue.Enqueue($i) } }
        }
        catch { Write-BridgeLog "TypeIdentifier of $($Device.Name): $($_.Exception.Message)" }
    }
    Write-BridgeLog "No OrderNumber TypeIdentifier on device $($Device.Name) or its device items."
    $null
}

# The entry of the PLC or HMI software to work on: the only one, or the one on Device.
function Get-TiaSoftwareEntry([string]$Kind, [string]$Device = '') {
    $all = @(Get-TiaSoftwareList | Where-Object { $_.kind -eq $Kind })
    if ($Device) { $all = @($all | Where-Object { $_.device -eq $Device }) }
    if ($all.Count -eq 1) { return $all[0] }
    $names = @(Get-TiaSoftwareList | Where-Object { $_.kind -eq $Kind } | ForEach-Object { $_.device }) -join ', '
    if (-not $all.Count) { throw "No $Kind '$Device' in the project. $Kind devices: $names." }
    throw "Several $Kind devices: $names. Pass device."
}

function Get-TiaSoftware([string]$Kind, [string]$Device = '') { (Get-TiaSoftwareEntry $Kind $Device).software }

# The device a tool's device argument resolves to, as TIA names it (save rules).
function Get-TiaDeviceName([string]$Kind, [string]$Device = '') { [string](Get-TiaSoftwareEntry $Kind $Device).device }

# Every device of a kind; none when the project has none.
function Get-TiaDeviceNames([string]$Kind) {
    @(Get-TiaSoftwareList | Where-Object { $_.kind -eq $Kind } | ForEach-Object { $_.device } | Sort-Object -Unique)
}

# What a tool has committed in TIA and not yet said: a failure later in the same call must not lose it (Bridge.ps1 puts it in
# the result of a failure). Cleared at the start of every call.
$script:CommittedFacts = $null
function Set-CommittedFact([string]$Key, $Value) {
    if (-not $script:CommittedFacts) { $script:CommittedFacts = [ordered]@{ } }
    $script:CommittedFacts[$Key] = $Value
}

# A write TIA is online for is refused, as nothing would roll it back (2026-11-05: "The operation is not permitted in
# online mode", and the bridge wrote without a transaction). TransactionError: why TIA refused the transaction, known
# by its words or by a device that reads online (another TIA language); $null for a write that asks for none
# (useTransactions off), refused by a device that reads online. The refusal text, or $null.
function Get-OnlineRefusal($TransactionError) {
    $online = @()
    try { $online = @(Get-DeviceStates @(Get-TiaSoftwareList) | Where-Object { $_.online -eq 'online' } | ForEach-Object { $_.device }) }
    catch {
        if (Test-TiaEndedError $_) { throw }
        Write-BridgeLog "Online states not read: $($_.Exception.Message)"
    }
    $said = [bool]($TransactionError -and ((@($TransactionError.message) + @($TransactionError.details)) -match 'online mode'))
    if (-not ($said -or $online.Count)) { return $null }
    $why = $(if ($TransactionError) { " TIA refused the transaction ($($TransactionError.message))." } else { '' })
    $who = $(if ($online.Count) { " Online: $($online -join ', ')." } else { '' })
    "TIA is online: go offline first.$why$who Nothing was written. Ask the user to go offline in TIA, then call this again."
}

# Every write runs under ExclusiveAccess (TIA shows the text and blocks its UI) and, if possible, in one
# Transaction (one undo step in TIA). The transaction rolls back when an exception escapes Body, when
# RollbackIf holds after Body, or when TIA refuses the commit (it does after any Openness exception inside the
# transaction). A write TIA is online for is refused before Body (Get-OnlineRefusal); one with -NoTransaction
# (save, compile) is not. Returns @{ output; transaction; rolledBack; commitError; note }.
# Body runs in a child scope of the caller, so it reads the caller's variables; it reports through its output
# or through collections it is handed (assignments inside Body stay local to it).
# OnCopy: the compile of an export-only background session, which changes only its copy (never saved).
function Invoke-TiaWrite([string]$Description, [scriptblock]$Body, [switch]$NoTransaction, [scriptblock]$RollbackIf, [switch]$OnCopy) {
    # the dispatch refuses the write tools already (Get-BackgroundRefusal); this holds for a tool that slips through
    if ($script:Bridge.background -and -not $script:Bridge.background.write -and -not $OnCopy) { throw "Refused in a background session (export only): $Description." }
    $project = Get-TiaProject
    $text = "TiaBridge: $Description"
    Write-BridgeLog "$text`: exclusive access"
    $ea = $script:Bridge.portal.ExclusiveAccess($text)
    $tx = $null; $note = $null
    try {
        if (-not $NoTransaction -and $script:Bridge.settings.useTransactions) {
            Write-BridgeLog "$text`: transaction"
            try { $tx = $ea.Transaction($project, $text) }
            catch {
                if (Test-TiaEndedError $_) { throw }
                $why = ConvertTo-BridgeError $_
                $refusal = Get-OnlineRefusal $why
                if ($refusal) { throw $refusal }
                $note = "Ran without a transaction: $($why.message)"
            }
        }
        elseif (-not $NoTransaction) {
            $refusal = Get-OnlineRefusal $null
            if ($refusal) { throw $refusal }
        }
        Write-BridgeLog "$text`: body"
        $out = @(& $Body)
        Write-BridgeLog "$text`: body done"
        $used = [bool]$tx
        $commitError = $null
        $rollback = [bool]($RollbackIf -and (& $RollbackIf))
        if ($tx) {
            if ($rollback) {
                # Dispose without CommitOnDispose rolls the transaction back
                try { $tx.Dispose() }
                catch {
                    if (Test-TiaEndedError $_) { throw }
                    Write-BridgeLog "Transaction rollback: $($_.Exception.Message)"
                }
            } else {
                # the commit happens in Dispose; when it fails, nothing of Body was kept
                try { $tx.CommitOnDispose(); $tx.Dispose() }
                catch {
                    if (Test-TiaEndedError $_) { throw }
                    $commitError = ConvertTo-BridgeError $_
                }
            }
            $tx = $null
        }
        @{ output = $out; transaction = $used; rolledBack = ($used -and ($rollback -or [bool]$commitError)); commitError = $commitError; note = $note }
    }
    finally {
        if ($tx) { try { $tx.Dispose() } catch { Write-BridgeLog "Transaction rollback: $($_.Exception.Message)" } }
        try { $ea.Dispose() } catch { Write-BridgeLog "ExclusiveAccess dispose: $($_.Exception.Message)" }
    }
}

# After a rollback no item of the batch was kept: the ones that had passed are marked rolled back.
function Set-RolledBack($Items) {
    foreach ($i in $Items) { if ($i.ok) { $i.ok = $false; $i.rolledBack = $true } }
}
