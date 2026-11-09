# Tools\Background.ps1 - background_open, background_close: a project (.ap20, copied) or an archive (.zap20,
# retrieved) opened from a scratch copy in a TIA Portal without user interface that the bridge starts itself,
# export only, closed and removed again. In write mode (write=true) the .ap20 itself is opened, with the writes and
# the rules of a connect session; closing never saves. An archive in write mode is retrieved once, to a folder that
# stays, and is a project of its own from then on. The user's TIA is not touched: a project open there is locked,
# and the session refuses it.

# How long background_close waits for the TIA process to end after Dispose.
$script:BackgroundExitWaitMs = 60000

# Source file -> @{ path; kind = 'project'|'archive'; version; upgrade }. Throws for what TIA Portal V20 cannot open.
# The version comes from the extension (.ap20, .zap19, .ap15_1); an older one is upgraded, in the copy only.
function Get-BackgroundSource([string]$Path) {
    if (-not $Path) { throw 'path is required: a TIA project (.ap20) or a project archive (.zap20).' }
    $full = [System.IO.Path]::GetFullPath($Path)
    if (-not (Test-Path -LiteralPath $full -PathType Leaf)) { throw "$full not found." }
    $ext = [System.IO.Path]::GetExtension($full).ToLowerInvariant()
    if ($ext -notmatch '^\.(z?)ap(\d+)(_\d+)?$') { throw "$full is neither a TIA project (.ap20) nor a project archive (.zap20)." }
    $kind = if ($Matches[1]) { 'archive' } else { 'project' }
    $version = [int]$Matches[2]
    if ($version -gt 20) { throw "$full is a TIA Portal V$version $kind; TIA Portal V20 cannot open it." }
    @{ path = $full; kind = $kind; version = $version; upgrade = ($version -lt 20) }
}

# The TIA process (Get-TiaProcesses entry) that has the project at Path open, or $null.
function Find-TiaHolding([object[]]$Processes, [string]$Path) {
    @($Processes | Where-Object { $_ -and $_.path -and [string]::Equals($_.path, $Path, [StringComparison]::OrdinalIgnoreCase) }) | Select-Object -First 1
}

# A hint for a failed start or open, from the Siemens error (ConvertTo-BridgeError). The patterns are not probed
# on a failing project yet; the error itself is always quoted in full beside the hint.
# TooLong: what the session can do about a path too long, as that depends on where it opens the project.
function Get-BackgroundFailureHint($Err, [string]$TooLong = '') {
    $text = (@($Err.type, $Err.message) + @($Err.details) + @($Err.inner | ForEach-Object { $_.type; $_.message })) -join "`n"
    if ($text -match 'MissingProducts|option package|Optionspaket|support package|\bHSP\b') {
        return 'TIA Portal on this guest lacks a product, option package or HSP the project uses (the details name it). Install it, or open the project where it is installed.'
    }
    if ($text -match 'LicenseNotFound|licen[cs]e|Lizenz') { return 'No valid licence for TIA Portal or a package the project uses (Automation License Manager).' }
    if ($text -match 'already open|already in use|is locked|being used by another|bereits ge.ffnet|gesperrt|wird verwendet') {
        return 'The project is open in another TIA (another Windows session or user, or a TIA without user interface) and locked there: ask the user to close it there.'
    }
    if ($text -match 'UMAC|\bUMC\b|user management|Benutzerverwaltung|protected project|project is protected|not authorized|access authorization|project protection|Projektschutz|password|Passwort|Kennwort|credential|authenticat') {
        return 'The project is protected (project protection or UMC user management). A background TIA cannot answer the login prompt: open the project in TIA, or ask for an unprotected copy.'
    }
    if ($text -match 'EngineeringSecurity|Openness') {
        return "Openness access was refused: the Windows user must be in the group 'Siemens TIA Openness' (log off and on after adding)."
    }
    if ($text -match 'too long|zu lang') { return "TIA allows a project path of at most $script:TiaPathLimit characters (the error names the path).$(if ($TooLong) { " $TooLong" })" }
    if ($text -match 'upgrade|hochr') { return 'The project needs an upgrade to V20; name the file with its version extension (.ap19, .zap19) so the copy is upgraded.' }
    $null
}

# Where write=true retrieves the archive at Source -> @{ name; dir; repoDir } or @{ refused }, before TIA starts. Folder and repo take
# Repo, else the archive's file name: an opened archive is its own project, and an archive of another date another one, with no
# shared history. It is retrieved once: a folder that stands is refused, naming its project file. The .zap20 is never touched.
function Resolve-ArchiveTarget([string]$Source, [string]$Repo) {
    $root = $script:Bridge.settings.projectsRoot
    $name = $(if ($Repo) { $Repo } else { [System.IO.Path]::GetFileNameWithoutExtension($Source) })
    $folder = Resolve-RepoFolder $root $name
    if ($folder.refused) { return @{ refused = $folder.refused } }
    $name = Split-Path -Leaf $folder.path
    $dir = Join-Path $root "_bridge\retrieved\$name"
    if (Test-Path -LiteralPath $dir) {
        $file = @(Get-ChildItem -LiteralPath $dir -Filter '*.ap20' -Recurse -File -ErrorAction SilentlyContinue | Select-Object -First 1 | ForEach-Object { $_.FullName })
        $open = $(if ($file) { ": open its project with background_open, path $file and write=true" })
        return @{ refused = "$dir exists, so this archive was opened before$open. An archive of another date, or a new start from this one: name its own with repo. Ask the user before removing that folder." }
    }
    # what the folder records: a project's path, or the source of an export-only session or a plain export
    $recorded = Get-RepoRecordedPath (Read-RepoConfig $folder.path)
    if ($recorded -and -not $recorded.StartsWith("$dir\", [StringComparison]::OrdinalIgnoreCase)) {
        return @{ refused = "$($folder.path) records ${recorded}: this archive would mix with it. Name another with repo." }
    }
    # TIA's limit is on the project's folder too; the name of the project inside is known only once it is retrieved, and TIA then refuses it
    if ("$dir\p".Length -gt $script:TiaPathLimit) { return @{ refused = "$dir is too long: TIA retrieves into a path of at most $script:TiaPathLimit characters. Give a shorter name with repo, or ask the user for a shorter projects root." } }
    $archives = Join-Path $folder.path 'archives'
    $shortest = ConvertTo-ArchiveName -Project '' -Reason 'session' -Dir $archives
    if ((Join-Path $archives ($shortest -replace '\.zap20$', '')).Length -gt $script:TiaPathLimit) { return @{ refused = "$archives is too long for the session archive: TIA writes an archive at a path of at most $script:TiaPathLimit characters. Give a shorter name with repo, or ask the user for a shorter projects root." } }
    @{ name = $name; dir = $dir; repoDir = $folder.path }
}

# $null when Repo names a folder a plain export may go to, else why not. The caller names it, always: the project
# name is no fallback (an upgraded .zap19 opens as <name>_V20, the name of the V20 project and of its repo),
# and a project repo (.git, docs\project.md) is never taken as a plain folder.
function Get-PlainFolderRefusal([string]$Repo) {
    if (-not $Repo.Trim()) { return 'plain=true needs repo: the export folder under the projects root (the project name is no fallback).' }
    $folder = Resolve-RepoFolder $script:Bridge.settings.projectsRoot $Repo
    if ($folder.refused) { return $folder.refused }
    $dir = $folder.path
    foreach ($m in '.git', 'docs\project.md') {
        if (Test-Path -LiteralPath (Join-Path $dir $m)) { return "$dir is a project repo ($m); plain=true writes only into a folder of its own." }
    }
    $null
}

function Get-BackgroundRoot {
    if ($script:Bridge.settings.backgroundRoot) { return [string]$script:Bridge.settings.backgroundRoot }
    Join-Path $script:Bridge.settings.projectsRoot '_bridge\background'
}

# Scratch folders <yyyyMMdd_HHmmss>_<bridge PID> of bridge processes that ended before background_close: removed.
# One whose process still runs (this bridge, or a PID taken again) stays. Returns @{ path; removed; error }.
function Remove-StaleBackgroundScratch([string]$Root) {
    foreach ($d in @(Get-ChildItem -LiteralPath $Root -Directory -ErrorAction SilentlyContinue)) {
        if ($d.Name -notmatch '^\d{8}_\d{6}_(\d+)$') { continue }
        $owner = [int]$Matches[1]
        if ($owner -eq $PID -or (Get-Process -Id $owner -ErrorAction SilentlyContinue)) { continue }
        try { Remove-Item -LiteralPath $d.FullName -Recurse -Force -ErrorAction Stop; @{ path = $d.FullName; removed = $true } }
        catch { @{ path = $d.FullName; removed = $false; error = $_.Exception.Message } }
    }
}

# Prompts of a TIA without user interface: no one sees a message box there, so a call that waits on one would hang
# (an import over a test instance waited 29 min on a modal message). The guard answers every Confirmation with
# the first of Cancel, Abort, No, NoToAll, Ok that TIA offers, so the operation fails instead of waiting, and marks
# every Notification handled; each one is queued for the tool result (prompts), with its icon. Plain C#: TIA raises the events on
# another thread, where a PowerShell script block cannot run; reflection, so the Siemens types are not compiled in.
$script:PromptGuardSource = @'
using System; using System.Collections.Concurrent; using System.Reflection;
public static class TiaBridgePromptGuard {
    public static readonly ConcurrentQueue<string[]> Seen = new ConcurrentQueue<string[]>();
    static readonly string[] Answers = { "Cancel", "Abort", "No", "NoToAll", "Ok" };
    public static void Attach(object portal) {
        Hook(portal, "Confirmation", "OnConfirmation");
        Hook(portal, "Notification", "OnNotification");
    }
    // The notifications only, for one call in a TIA with a window: questions stay with the person at TIA.
    public static Delegate AttachNotifications(object portal) { return Hook(portal, "Notification", "OnWindowNotification"); }
    public static void Detach(object portal, Delegate handler) { portal.GetType().GetEvent("Notification").RemoveEventHandler(portal, handler); }
    static Delegate Hook(object portal, string name, string handler) {
        EventInfo ev = portal.GetType().GetEvent(name);
        if (ev == null) throw new InvalidOperationException(portal.GetType().FullName + " has no event " + name + ".");
        MethodInfo m = typeof(TiaBridgePromptGuard).GetMethod(handler, BindingFlags.Static | BindingFlags.NonPublic);
        Delegate d = Delegate.CreateDelegate(ev.EventHandlerType, m);
        ev.AddEventHandler(portal, d);
        return d;
    }
    static string Text(object o, string p) {
        try { PropertyInfo i = o.GetType().GetProperty(p); object v = i == null ? null : i.GetValue(o, null); return v == null ? "" : v.ToString(); }
        catch { return ""; }
    }
    static void OnConfirmation(object sender, EventArgs e) {
        string answer = "";
        try {
            object choices = e.GetType().GetProperty("Choices").GetValue(e, null);
            long offered = Convert.ToInt64(choices);
            PropertyInfo result = e.GetType().GetProperty("Result");
            foreach (string a in Answers) {
                if ((offered & Convert.ToInt64(Enum.Parse(choices.GetType(), a))) == 0) continue;
                result.SetValue(e, Enum.Parse(result.PropertyType, a), null);
                e.GetType().GetProperty("IsHandled").SetValue(e, true, null);
                answer = a;
                break;
            }
            if (answer == "") answer = "(none of Cancel, Abort, No, NoToAll, Ok offered: left to TIA)";
        }
        catch (Exception x) { answer = "(not answered: " + x.Message + ")"; }
        Seen.Enqueue(new string[] { "confirmation", Text(e, "Caption"), Text(e, "Text"), Text(e, "DetailText"), Text(e, "Choices"), answer, Text(e, "Icon") });
    }
    static void OnNotification(object sender, EventArgs e) {
        string answer = "handled";
        try { e.GetType().GetProperty("IsHandled").SetValue(e, true, null); }
        catch (Exception x) { answer = "(not handled: " + x.Message + ")"; }
        Seen.Enqueue(new string[] { "notification", Text(e, "Caption"), Text(e, "Text"), Text(e, "DetailText"), "", answer, Text(e, "Icon") });
    }
    // Someone can see these boxes: only one that reports a success or plain information is closed for them, and an icon that
    // cannot be read closes nothing. A Warning or Error box ("The file to be processed has an invalid extension. Abort.") stays.
    static void OnWindowNotification(object sender, EventArgs e) {
        string icon = Text(e, "Icon");
        string answer = "left to the person at TIA";
        if (icon == "Success" || icon == "Information") {
            answer = "handled";
            try { e.GetType().GetProperty("IsHandled").SetValue(e, true, null); }
            catch (Exception x) { answer = "(not handled: " + x.Message + ")"; }
        }
        Seen.Enqueue(new string[] { "notification", Text(e, "Caption"), Text(e, "Text"), Text(e, "DetailText"), "", answer, icon });
    }
}
'@

function Register-PromptGuard($Portal) {
    if (-not ('TiaBridgePromptGuard' -as [type])) { Add-Type -TypeDefinition $script:PromptGuardSource }
    $o = if ($Portal -is [psobject]) { $Portal.PSObject.BaseObject } else { $Portal }
    [TiaBridgePromptGuard]::Attach($o)
}

# Runs Body with the Success and Information boxes of a TIA with a window acknowledged, and every notification queued for
# the result (prompts): a full export waited 590 s behind an "Export Completed (0032:000002)" box (project texts,
# 2026-11-02). Confirmations are not touched, they are the person's, nor are Warning and Error boxes. A background session
# has the whole guard already. Attaching can only help: when it fails, Body runs as it did.
# Without window that box arrives as this event and the part stays under 60 s (7 real background exports, about 11 s on the
# largest project). With a window not probed: whether handling closes the box, what icon it carries (only Success or
# Information closes it), and whether a box of the person's own work during the call reaches the guard: the event is the
# portal's, not the call's.
function Invoke-WithNotificationGuard([scriptblock]$Body) {
    $portal = $script:Bridge.portal
    $handler = $null
    if ($null -ne $portal -and -not $script:Bridge.background) {
        $o = if ($portal -is [psobject]) { $portal.PSObject.BaseObject } else { $portal }
        try {
            if (-not ('TiaBridgePromptGuard' -as [type])) { Add-Type -TypeDefinition $script:PromptGuardSource }
            $handler = [TiaBridgePromptGuard]::AttachNotifications($o)
        }
        catch { Write-BridgeLog "No notification guard for this call: $($_.Exception.Message)" }
    }
    try { & $Body }
    finally {
        if ($handler) {
            try { [TiaBridgePromptGuard]::Detach($o, $handler) }
            catch { Write-BridgeLog "The notification guard could not let go: $($_.Exception.Message)" }
        }
    }
}

# The prompts queued since the last call (the dispatch puts them into the tool result), oldest first.
function Get-PromptLog {
    if (-not ('TiaBridgePromptGuard' -as [type])) { return }
    $p = $null
    while ([TiaBridgePromptGuard]::Seen.TryDequeue([ref]$p)) {
        [ordered]@{ kind = $p[0]; caption = $p[1]; text = $p[2]; detail = $p[3]; choices = $p[4]; answer = $p[5]; icon = $p[6] }
    }
}

# The login of a protected project (UMAC: project users, or UMC users with umc_global), passed in by a tool in a
# plain session (umc_user, umc_password). Openness calls the UmacDelegate of Open / Retrieve (and their
# WithUpgrade forms) when the project asks for a login; Answer fills the UmacCredentials it gets (Name, Type,
# SetPassword) [PROBE: reflection of V20 Siemens.Engineering.dll, 2026-10-30; not run on a protected project].
# Plain C# as the prompt guard (TIA may call it on another thread); reflection, so the Siemens types are not
# compiled in. A login TIA asks for again and again is not accepted: after MaxCalls the delegate throws.
$script:UmacLoginSource = @'
using System; using System.Reflection; using System.Security;
public sealed class TiaBridgeUmacLogin : IDisposable {
    public const int MaxCalls = 3;
    readonly string name; readonly SecureString password; readonly bool global;
    public int Calls;
    public TiaBridgeUmacLogin(string name, SecureString password, bool global) { this.name = name; this.password = password; this.global = global; }
    public string UserType { get { return global ? "Global" : "Project"; } }
    public void Answer(object credentials) {
        Calls++;
        if (Calls > MaxCalls) throw new InvalidOperationException("TIA asked for the project login " + Calls + " times; the login given is not accepted.");
        Type t = credentials.GetType();
        PropertyInfo type = t.GetProperty("Type");
        type.SetValue(credentials, Enum.Parse(type.PropertyType, UserType), null);
        t.GetProperty("Name").SetValue(credentials, name, null);
        t.GetMethod("SetPassword", new Type[] { typeof(SecureString) }).Invoke(credentials, new object[] { password });
    }
    public Delegate For(Type delegateType) { return Delegate.CreateDelegate(delegateType, this, typeof(TiaBridgeUmacLogin).GetMethod("Answer")); }
    public void Dispose() { password.Dispose(); }
}
'@

function New-UmacLogin([string]$User, [string]$Password, [bool]$Global) {
    if (-not ('TiaBridgeUmacLogin' -as [type])) { Add-Type -TypeDefinition $script:UmacLoginSource }
    New-Object TiaBridgeUmacLogin -ArgumentList $User, (ConvertTo-SecurePassword $Password), $Global
}

# $null when the UMC arguments may be used, else why not. Only a tool in a plain session passes a login; an agent
# leaves the arguments out (a protected project opens in the user's TIA).
function Get-UmacArgumentRefusal($a, [bool]$Plain) {
    $given = @('umc_user', 'umc_password', 'umc_global' | Where-Object { $a.PSObject.Properties[$_] })
    if (-not $given.Count) { return $null }
    if (-not $Plain) { return "$($given -join ', ') are for a tool in a plain session (plain=true) that asks the user itself; a protected project otherwise opens in the user's TIA." }
    if (-not ([string]$a.umc_user).Trim()) { return 'The project login needs umc_user (the user name).' }
    if (-not ([string]$a.umc_password).Length) { return 'The project login needs umc_password.' }
    $null
}

# The Openness call that opens the project: Retrieve for an archive, Open for a project file, the WithUpgrade form
# for an older version; with a login, the overload that takes a UmacDelegate.
function Open-BackgroundProject($Portal, $Src, [System.IO.FileInfo]$File, [System.IO.DirectoryInfo]$Dir, $Login) {
    $p = $Portal.Projects
    $umac = if ($Login) { $Login.For([Siemens.Engineering.UmacDelegate]) } else { $null }
    if ($Src.kind -eq 'archive') {
        if ($umac) { if ($Src.upgrade) { return $p.RetrieveWithUpgrade($File, $Dir, $umac) } else { return $p.Retrieve($File, $Dir, $umac) } }
        if ($Src.upgrade) { return $p.RetrieveWithUpgrade($File, $Dir) } else { return $p.Retrieve($File, $Dir) }
    }
    if ($umac) { if ($Src.upgrade) { return $p.OpenWithUpgrade($File, $umac) } else { return $p.Open($File, $umac) } }
    if ($Src.upgrade) { return $p.OpenWithUpgrade($File) } else { return $p.Open($File) }
}

# Seams for the tests: start a TIA Portal without user interface (its Dispose ends that process again), and wait
# for a process to end.
function Start-BackgroundTia { New-Object Siemens.Engineering.TiaPortal ([Siemens.Engineering.TiaPortalMode]::WithoutUserInterface) }

function Wait-ProcessExit([int]$ProcessId, [int]$TimeoutMs) {
    $deadline = [DateTime]::UtcNow.AddMilliseconds($TimeoutMs)
    while (Get-Process -Id $ProcessId -ErrorAction SilentlyContinue) {
        if ([DateTime]::UtcNow -ge $deadline) { return $false }
        Start-Sleep -Milliseconds 500
    }
    $true
}

# Closes the project without saving and disposes the portal, which ends the TIA process the bridge started.
# Returns @{ errors; exited }.
function Stop-BackgroundTia($Project, $Portal, [int]$ProcessId) {
    $errors = @()
    if ($Project) { try { $Project.Close() } catch { $errors += ConvertTo-BridgeError $_ } }
    if ($Portal) { try { $Portal.Dispose() } catch { $errors += ConvertTo-BridgeError $_ } }
    $exited = ($ProcessId -le 0) -or (Wait-ProcessExit $ProcessId $script:BackgroundExitWaitMs)
    @{ errors = $errors; exited = $exited }
}

function Get-BackgroundSummary {
    $bg = $script:Bridge.background
    if (-not $bg) { return $null }
    @{ source = $bg.source; kind = $bg.kind; write = [bool]$bg.write; upgraded = $bg.upgraded; copy = $bg.scratch; processId = $bg.processId
       openedAt = $bg.openedAt; alive = (Test-TiaAlive); steps = $bg.steps.Count; tia = (Get-ProcessMemory $bg.processId) }
}

# Before the session archive of a write session. TIA can mark a project modified on opening, with no write made
# (2026-11-01). It archives only a saved project and save waits for the archive, so nothing would get out of that but
# archive(skip=true). Saving is safe only here: the session has made no write and has no window for a user's edits.
# Under connect the changes may be the user's: archive keeps refusing there. Returns $false when the save failed or did
# not clear the flag: the result says so and writes stay refused.
function Save-ModifiedOnOpening($Result, [System.Collections.ArrayList]$Steps, [int]$TiaProcessId) {
    $sw = [System.Diagnostics.Stopwatch]::StartNew()
    $saved = $false; $cleared = $false
    try {
        if (-not (Get-TiaProject).IsModified) { return $true }
        Write-StepProgress 'save' 'start' $TiaProcessId
        $null = Invoke-TiaWrite 'save before the session archive' -NoTransaction { (Get-TiaProject).Save() }
        $saved = $true
        if ((Get-TiaProject).IsModified) { throw 'The project is still marked modified after the save, and TIA archives only a saved project.' }
        $cleared = $true
    }
    catch {
        $what = $(if ($saved) { 'the save did not clear that' } else { 'saving it failed' })
        Set-SessionArchiveFailure $Result $_ ("TIA marked the project modified on opening, with no write made, and $what (archive.error), so there is no session archive and writes stay refused. " +
            'Call background_close with discard=true and background_open again, or archive(skip=true, reason) only when the user says so.') 'the save before the session archive'
    }
    $Result.savedBeforeArchive = $saved
    [void]$Steps.Add((New-BackgroundStep 'save' $sw.ElapsedMilliseconds $TiaProcessId))
    $cleared
}

function Invoke-BackgroundOpenTool($a) {
    if ($script:Bridge.background) { return New-Refusal "A background session is open ($($script:Bridge.background.source)): call background_close first." }
    $write = Get-OptionalBool $a 'write' $false
    $plain = Get-OptionalBool $a 'plain' $false
    if ($write -and $plain) { return New-Refusal 'plain=true is for export only; write=true needs the project repo (archives, save, commits).' }
    # before TIA starts; a repo left out takes the project name, known only once TIA has opened the project
    $why = $(if ($plain) { Get-PlainFolderRefusal ([string]$a.repo) }
             elseif ([string]$a.repo) { (Resolve-RepoFolder $script:Bridge.settings.projectsRoot ([string]$a.repo)).refused })
    if ($why) { return New-Refusal $why }
    $why = Get-UmacArgumentRefusal $a $plain
    if ($why) { return New-Refusal $why }
    # a plain export folder has no git; the project repo needs it after TIA has opened the project
    if (-not $plain) { $why = Get-GitProblem; if ($why) { return New-Refusal $why } }
    $src = Get-BackgroundSource ([string]$a.path)
    if ($write -and $src.upgrade) {
        return New-Refusal ("write=true does not upgrade: $($src.path) is a V$($src.version) $($src.kind), and the upgrade writes a new project. The user upgrades it in TIA, " +
                            'or open it without write (export only, upgraded in a copy).')
    }
    # an archive opened for changes is a project of its own: nothing it could have moved from
    $target = $null
    if ($write -and $src.kind -eq 'archive') {
        $target = Resolve-ArchiveTarget $src.path ([string]$a.repo)
        if ($target.refused) { return New-Refusal $target.refused }
    }
    # write mode works on the project file itself, so its repo belongs to that path as under connect; export only would
    # commit a copy or archive as a change to the project a repo records. Refused before a TIA starts; a plain folder has no commits.
    $repoName = [string]$a.repo
    $moved = $write -and -not $target -and (Get-OptionalBool $a 'moved' $false)
    $choice = $null
    if ($target) { $repoName = $target.name }
    elseif (-not $plain) {
        $choice = Resolve-ProjectRepo -Root $script:Bridge.settings.projectsRoot -ProjectName ([System.IO.Path]::GetFileNameWithoutExtension($src.path)) -ProjectPath $src.path -RepoName $repoName -Moved:$moved -ExportOnly:(-not $write)
        if ($choice.refused) { return New-Refusal $choice.refused }
        $repoName = $choice.repoName
    }
    Import-Openness $script:Bridge.settings.tiaRoot
    $processes = @(Get-TiaProcesses)
    if ($src.kind -eq 'project') {
        $holder = Find-TiaHolding $processes $src.path
        if ($holder) {
            $where = if ($holder.mode -eq 'WithoutUserInterface') { 'a TIA without user interface (another bridge''s background session, or one left by a stopped bridge)' } else { 'TIA' }
            return New-Refusal ("$($src.path) is open in $where (process $($holder.processId)) and locked there; the background session does not take it over. " +
                                $(if ($write) { 'Ask the user to close it there first (save or discard their changes), then call background_open again; or use connect to work on it in that TIA.' }
                                  else { 'Use connect to work on it in that TIA, or ask the user to close it there.' }))
        }
    }
    $group = Test-OpennessGroup
    if ($group) { return New-Refusal $group }

    $root = Get-BackgroundRoot
    $stale = @(Remove-StaleBackgroundScratch $root)
    # write mode opens the project file itself: no scratch copy
    $scratch = $null
    if ($target) { New-Item -ItemType Directory -Force -Path $target.dir | Out-Null }
    if (-not $write) {
        $scratch = Join-Path $root "$((Get-Date).ToString('yyyyMMdd_HHmmss'))_$PID"
        New-Item -ItemType Directory -Force -Path $scratch | Out-Null
    }
    # the window session's binding, back in place when the open fails (the next call then reattaches to it)
    $previous = @{ name = $script:Bridge.projectName; path = $script:Bridge.projectPath; repo = $script:Bridge.repo }
    Reset-TiaConnection

    $steps = New-Object System.Collections.ArrayList
    $portal = $null; $project = $null; $tiaPid = 0; $step = 'start'; $guardError = $null
    $login = $null
    if ($a.PSObject.Properties['umc_user']) {
        $login = New-UmacLogin ([string]$a.umc_user) ([string]$a.umc_password) (Get-OptionalBool $a 'umc_global' $false)
        Write-BridgeLog "background open: project login passed in ($($login.UserType) user)"
    }
    $sw = [System.Diagnostics.Stopwatch]::new()
    # the upgrade happens inside retrieve or open (one Openness call each)
    $up = $(if ($src.upgrade) { @{ upgrade = $true } } else { @{} })
    try {
        $sw.Restart()
        Write-StepProgress 'start' 'start'
        $portal = Start-BackgroundTia
        $tiaPid = [int]$portal.GetCurrentProcess().Id
        Write-BridgeProgress ([ordered]@{ event = 'tia'; pid = $tiaPid })
        # before the first project call: a prompt no one answers would hang the call
        try { Register-PromptGuard $portal }
        catch {
            $guardError = ConvertTo-BridgeError $_
            if ($write) { throw }
        }
        [void]$steps.Add((New-BackgroundStep 'start' $sw.ElapsedMilliseconds $tiaPid))
        if ($src.kind -eq 'archive') {
            # Retrieve unpacks and opens in one call
            $step = 'retrieve'; $sw.Restart()
            Write-StepProgress 'retrieve' 'start' $tiaPid $up
            $project = Open-BackgroundProject $portal $src ([System.IO.FileInfo]::new($src.path)) ([System.IO.DirectoryInfo]::new($(if ($target) { $target.dir } else { $scratch }))) $login
            [void]$steps.Add((New-BackgroundStep 'retrieve' $sw.ElapsedMilliseconds $tiaPid))
        } else {
            $open = $src.path
            if (-not $write) {
                $step = 'copy'; $sw.Restart()
                Write-StepProgress 'copy' 'start' $tiaPid
                $folder = Split-Path -Parent $src.path
                Copy-Item -LiteralPath $folder -Destination $scratch -Recurse -Force
                $open = Join-Path (Join-Path $scratch (Split-Path -Leaf $folder)) (Split-Path -Leaf $src.path)
                [void]$steps.Add((New-BackgroundStep 'copy' $sw.ElapsedMilliseconds $tiaPid))
            }
            $step = 'open'; $sw.Restart()
            Write-StepProgress 'open' 'start' $tiaPid $up
            $project = Open-BackgroundProject $portal $src ([System.IO.FileInfo]::new($open)) $null $login
            [void]$steps.Add((New-BackgroundStep 'open' $sw.ElapsedMilliseconds $tiaPid))
        }
        if (-not $project) { throw 'TIA opened no project.' }

        $step = 'bind'; $sw.Restart()
        Write-StepProgress 'bind' 'start' $tiaPid
        $script:Bridge.portal = $portal; $script:Bridge.project = $project; $script:Bridge.processId = $tiaPid; $script:Bridge.software = $null
        $script:Bridge.projectName = $project.Name; $script:Bridge.projectPath = $project.Path.FullName; $script:Bridge.repo = $null
        $script:Bridge.background = @{ source = $src.path; kind = $src.kind; write = $write; plain = $plain; upgraded = $src.upgrade; scratch = $scratch; processId = $tiaPid
                                       openedAt = (Get-Date).ToString('yyyy-MM-ddTHH:mm:ss'); steps = $steps; session = (New-SessionState) }
        $software = @(Get-TiaSoftwareList)
        $typeIds = @{}
        foreach ($h in @($software | Where-Object { $_.kind -eq 'hmi' })) { $typeIds[$h.device] = Get-DeviceTypeIdentifier $h.deviceObject }
        $map = Initialize-ProjectRepo -Root $script:Bridge.settings.projectsRoot -ProjectName $project.Name -ProjectPath $project.Path.FullName `
            -PlcDevices @($software | Where-Object { $_.kind -eq 'plc' } | ForEach-Object { $_.device }) `
            -HmiDevices @($software | Where-Object { $_.kind -eq 'hmi' } | ForEach-Object { $_.device }) -HmiTypeIdentifiers $typeIds `
            -RepoName $repoName -BackgroundSource $src.path -Plain:$plain -BackgroundWrite:$write -Moved:$moved -StandardsTemplate ([string]$script:Bridge.settings.standardsTemplate)
        $script:Bridge.repo = $map.repo
        [void]$steps.Add((New-BackgroundStep 'bind' $sw.ElapsedMilliseconds $tiaPid))
    }
    catch {
        $err = ConvertTo-BridgeError $_
        Write-StepProgress $step 'failed' $tiaPid
        Write-StepProgress 'close' 'start' $tiaPid
        $stop = Stop-BackgroundTia $project $portal $tiaPid
        Write-StepProgress 'close' $(if ($stop.exited) { 'done' } else { 'failed' }) $tiaPid
        $script:Bridge.portal = $null; $script:Bridge.project = $null; $script:Bridge.processId = 0; $script:Bridge.software = $null
        $script:Bridge.background = $null
        $script:Bridge.projectName = $previous.name; $script:Bridge.projectPath = $previous.path; $script:Bridge.repo = $previous.repo
        $r = @{ ok = $false; step = $step; error = $err; steps = @($steps) }
        if ($login) { $r.umcLogin = @{ userType = $login.UserType; asked = $login.Calls }; $login.Dispose() }
        if ($write -and $guardError -and $step -eq 'start') { $r.hint = 'The prompt guard could not be attached; write mode needs it (a TIA prompt would hang the background TIA).' }
        else {
            $hint = Get-BackgroundFailureHint $err $(if ($target) { 'Give a shorter name with repo, or ask the user for a shorter projects root.' }
                                                     elseif ($write) { 'The project opens where it lies: ask the user to move it to a shorter path.' }
                                                     else { "The copy goes under $root`: a shorter backgroundRoot in TiaBridge\settings.json." })
            if ($hint -and $hint -like 'The project is protected*') {
                $hint = $(if ($login) { "The project login was not accepted: user name, password or user type (umc_global: $(if ($login.UserType -eq 'Global') { 'true, a UMC user' } else { 'false, a project user' })). $hint" }
                          elseif ($plain) { "$hint A tool passes the login as umc_user and umc_password (umc_global for a UMC user)." }
                          else { $hint })
            }
            if ($hint) { $r.hint = $hint }
        }
        if (-not $stop.exited) { $r.note = "The background TIA process $tiaPid did not end$(if ($scratch) { "; the copy stays in $scratch" })$(if ($target) { "; the folder $($target.dir) stays, and refuses this archive until the user removes it" })." }
        elseif ($scratch) { Remove-Item -LiteralPath $scratch -Recurse -Force -ErrorAction SilentlyContinue }
        # nothing of a retrieve that failed stays to refuse the next try
        if ($target -and $stop.exited) { Remove-Item -LiteralPath $target.dir -Recurse -Force -ErrorAction SilentlyContinue }
        return $r
    }
    $r = @{ ok = $true; source = $src.path; kind = $src.kind; write = $write; upgraded = $src.upgrade; processId = $tiaPid
            repoCreated = $map.created; devices = @($software | ForEach-Object { @{ device = $_.device; kind = $_.kind } })
            readFirst = (Join-Path $map.repo 'docs\project.md') }
    # asked: how often TIA called for the login (0: the project is not protected)
    if ($login) { $r.umcLogin = @{ userType = $login.UserType; asked = $login.Calls }; $login.Dispose() }
    if ($map.pathChanged) { $r.pathChanged = "The project was at $($map.oldPath); tiabridge.json now records the new path." }
    if (-not $plain) { Set-StandardsResult $r $map }
    if ($target) { $r.retrievedTo = $target.dir; $r.reopen = "This project stays at $($project.Path.FullName) after background_close: background_open with that path and write=true works on it again." }
    if ($choice -and $choice.found) { $r.repoByPath = Get-RepoByPathNote $choice }
    if ($write) {
        $r.projectPath = $project.Path.FullName
        # the session archive, as connect makes it: writes are refused until it exists
        if (Save-ModifiedOnOpening $r $steps $tiaPid) {
            $saved = $(if ($r.savedBeforeArchive) { 'TIA marked the project modified on opening, with no write made; the bridge saved it to make the session archive possible. ' })
            if ($saved) { $r.note = $saved.TrimEnd() }
            $sw.Restart()
            Write-StepProgress 'archive' 'start' $tiaPid
            try { $r.archive = Invoke-ProjectArchive 'session' }
            catch { Set-SessionArchiveFailure $r $_ "${saved}The session archive failed, so writes are refused. Retry archive(reason), or archive(skip=true, reason) if the user says to skip it." }
            [void]$steps.Add((New-BackgroundStep 'archive' $sw.ElapsedMilliseconds $tiaPid))
        }
        $r.session = Get-SessionSummary
        if (-not $r.tiaEnded) {
            $r.next = $(if ($r.session.writesAllowed) { 'Write mode on the project file itself: import, delete, delete_folder, compile, save, archive and the library tools work as under connect (save rules ' +
                                                        'included); connect and a writable library_open are refused. ' }
                        else { 'Writes are refused until the session archive exists: see note. ' }) +
                      'TIA prompts are answered Cancel/No (prompts in the result). background_close when done: it never saves, and refuses unsaved changes unless discard=true.'
        }
    } else {
        $r.copy = $project.Path.FullName
        $r.next = $(if ($plain) { 'Export only into a plain folder, no git (list, export, full_export, probe, read-only library_open; compile and safety_login on the copy, never saved); background_close when done.' }
                    else { 'Export only (list, export, full_export, probe, change_report, read-only library_open; compile and safety_login on the copy, never saved); background_close when done.' })
        if ($plain) { $r.plain = $true }
    }
    $r.steps = @($steps)
    if ($guardError) { $r.promptGuard = $guardError }
    if ($previous.name) { $r.switchedFrom = $previous.name }
    if (@($stale).Count) { $r.staleCopies = $stale }
    # each TIA without user interface holds GBs of memory; one left by a stopped bridge is ended by the user, not here
    $headless = @($processes | Where-Object { $_ -and $_.mode -eq 'WithoutUserInterface' })
    if ($headless.Count) { $r.otherHeadlessTia = $headless }
    $r
}

function Invoke-BackgroundCloseTool($a) {
    $bg = $script:Bridge.background
    if (-not $bg) { return New-Refusal 'No background session is open.' }
    $keep = Get-OptionalBool $a 'keep_copy' $false
    $discard = Get-OptionalBool $a 'discard' $false
    # write mode: closing never saves; unsaved changes stay open until saved or discarded explicitly
    $unsaved = $false
    if ($bg.write -and (Test-TiaAlive)) {
        try { $unsaved = [bool]$script:Bridge.project.IsModified } catch { Write-BridgeLog "IsModified not read: $($_.Exception.Message)" }
        if ($unsaved -and -not $discard) {
            $how = $(if (Test-WriteAllowed $bg.session) { 'save waits for the session archive, which does not exist: call background_close with discard=true to close without saving ' +
                                                          '(the project file keeps its last save), or archive(skip=true, reason) only when the user says so.' }
                     else { "Save them (save$(if (-not $bg.session.archived) { ', after a clean compile' })), or call background_close with discard=true to close without saving; the project file keeps its last save." })
            return @{ ok = $false; refused = "The project has unsaved changes, and background_close never saves. $how"
                      saveBlockers = @(Test-SaveAllowed $bg.session); saveStanding = @(Get-SaveStanding $bg.session) }
        }
    }
    $sw = [System.Diagnostics.Stopwatch]::StartNew()
    $before = Get-ProcessMemory $bg.processId
    Write-StepProgress 'close' 'start' $bg.processId
    $stop = Stop-BackgroundTia $script:Bridge.project $script:Bridge.portal $bg.processId
    $closeStep = New-BackgroundStep 'close' $sw.ElapsedMilliseconds $bg.processId
    $closeStep.tiaBefore = $before
    [void]$bg.steps.Add($closeStep)
    $repo = $script:Bridge.repo
    $script:Bridge.portal = $null; $script:Bridge.project = $null; $script:Bridge.processId = 0; $script:Bridge.software = $null
    $script:Bridge.background = $null
    $script:Bridge.projectName = $null; $script:Bridge.projectPath = $null; $script:Bridge.repo = $null

    # write mode has no copy: the project file stays where it is
    $copyRemoved = $false
    if ($bg.scratch -and -not $keep -and $stop.exited) {
        try { Remove-Item -LiteralPath $bg.scratch -Recurse -Force -ErrorAction Stop; $copyRemoved = $true }
        catch { Write-BridgeLog "Background copy not removed: $($_.Exception.Message)" }
    }
    $peak = @($bg.steps | Where-Object { $_.tia } | ForEach-Object { $_.tia.peakWorkingSetMB } | Measure-Object -Maximum).Maximum
    $total = 0; foreach ($s in $bg.steps) { $total += [int]$s.ms }
    $summary = [ordered]@{ source = $bg.source; kind = $bg.kind; write = [bool]$bg.write; upgraded = $bg.upgraded; openedAt = $bg.openedAt; totalMs = $total
                           tiaPeakWorkingSetMB = $peak; steps = @($bg.steps) }
    $r = @{ ok = (-not @($stop.errors).Count); closed = $true; source = $bg.source; write = [bool]$bg.write; tiaEnded = $stop.exited; totalMs = $total
            tiaPeakWorkingSetMB = $peak; steps = @($bg.steps); next = 'Not connected now: connect binds to a project open in TIA.' }
    if ($bg.write) { $r.discarded = $unsaved }
    if ($repo) { $r.stepsLog = Join-Path $repo (Write-ToolLog -Repo $repo -Tool 'background_steps' -Result $summary) }
    if (@($stop.errors).Count) { $r.errors = @($stop.errors) }
    if (-not $stop.exited) {
        $r.note = "The background TIA process $($bg.processId) did not end within $($script:BackgroundExitWaitMs / 1000) s; ask the user before ending it." +
                  $(if ($bg.scratch) { " The copy stays in $($bg.scratch)." } else { " It may still hold $($bg.source) open (locked)." })
    }
    elseif ($bg.scratch -and ($keep -or -not $copyRemoved)) { $r.copy = $bg.scratch }
    $r
}

# When the bridge stops (stdin closed) with a background session open, its TIA process is ended too; in write mode
# changes not saved are discarded (no one is left to save them, and the bridge never saves on its own).
function Stop-BackgroundOnExit {
    if (-not $script:Bridge.background) { return }
    Write-BridgeLog 'Closing the background session before the bridge stops (unsaved changes are discarded).'
    $r = Invoke-BackgroundCloseTool (New-Object psobject -Property @{ discard = $true })
    if ($r.discarded) { Write-BridgeLog "Unsaved changes to $($r.source) discarded." }
}

function Register-BackgroundTools {
    Register-McpTool -Name 'background_open' -Handler { param($a) Invoke-BackgroundOpenTool $a } -Description (
        'Only when the user asks for it (it starts a TIA process and needs several GB of memory): open a TIA project (.ap20, copied first) or a project archive ' +
        '(.zap20, retrieved) in a TIA Portal without user interface that the bridge starts, from a copy under <projects root>\_bridge\background; an older ' +
        'version (.ap19, .zap19) is upgraded in the copy only. Refused for a project open in a TIA (locked there: use connect, or the user closes it there). Export only: tia_status, list, ' +
        'export, full_export, probe, change_report and read-only library_open work, every other tool is refused until background_close. Exports go to the project repo ' +
        '(named after the project), or to repo. A repo that records another path (its project''s, or the source of an earlier export-only session) is refused, naming both, also when repo names it: ' +
        'an export committed there would read as a change to that project. Say repo: "<name>" for a repo of its own; a repo that does not exist yet or records this source goes on. plain=true (for tools, not for agent work): repo (required, never the project name) is a plain export folder, no git, no commits, no repo skeleton ' +
        '(tiabridge.json and logs\ beside the exports); change_report is refused. ' +
        'write=true, only when the user asks for changes in a background session: opens the .ap20 itself (V20, no copy, no upgrade), or retrieves a V20 .zap20 once to <projects root>\_bridge\retrieved\<name>, which stays (the archive is never touched; folder and repo take the archive''s file name, or repo; a folder that exists is refused, naming its .ap20), and makes the session ' +
        'archive as connect does (a project TIA marks modified on opening, with no write made, is saved first: savedBeforeArchive in the result), then import, delete, delete_folder, compile, save, archive and the library tools work as under connect, with the archive gate and the save ' +
        'rules; connect and a writable library_open stay refused. As under connect, a repo that records another path is refused, naming both: ask the user, then moved=true or repo. TIA prompts no one can see are answered Cancel/No and listed in the result (prompts), so ' +
        'such a call fails instead of waiting. Every step and tool call returns its time and memory (step). A failure names the step and quotes the Siemens error, with a hint ' +
        '(missing package or HSP, licence, protected project, Openness group, locked project). Export only also compiles the copy (compile scope plc or blocks, ' +
        'safety_login), never saved. umc_user, umc_password (umc_global): the login of a protected project, for a tool in a plain session only (refused elsewhere); ' +
        'never set them yourself.') -Schema @{
        type = 'object'; required = @('path')
        properties = @{ path = @{ type = 'string'; description = '.ap20 or .zap20 file (older versions: .ap19, .zap19, ...); write=true: a V20 .ap20 or .zap20' }
                        write = @{ type = 'boolean'; description = 'open the project file itself, or an archive as a project of its own, with writes allowed; only when the user asks for it' }
                        moved = @{ type = 'boolean'; description = 'write=true only: the user says the project was moved: keep the repo, record the new path' }
                        plain = @{ type = 'boolean'; description = 'export into the plain folder repo (required; not a project repo): no git, no repo skeleton (not with write)' }
                        repo = @{ type = 'string'; description = 'repo folder: a plain folder name under the projects root, not a path; default the project name. Use another for an archive whose state must not mix with the project repo' }
                        umc_user = @{ type = 'string'; description = 'plain=true only (a tool, not an agent): user name for a protected project; hidden in results and logs' }
                        umc_password = @{ type = 'string'; description = 'plain=true only: password of umc_user; hidden in results and logs' }
                        umc_global = @{ type = 'boolean'; description = 'plain=true only: umc_user is a UMC user (UmacUserType Global); default false, a project user' } } }

    Register-McpTool -Name 'background_close' -Handler { param($a) Invoke-BackgroundCloseTool $a } -Description (
        'Close the background session: the project closes without saving, its TIA process ends, the copy is removed (keep_copy=true keeps it). Write mode: ' +
        'refused while the project has unsaved changes (save first, or discard=true to drop them); the project file is never removed. Returns the ' +
        'time and memory of every step, also written to logs\<time>_background_steps.json of the repo. Afterwards the bridge is not connected.') -Schema @{
        type = 'object'; properties = @{ keep_copy = @{ type = 'boolean' }
                                         discard = @{ type = 'boolean'; description = 'write mode: close without saving although the project has unsaved changes' } } }
}
