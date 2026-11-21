# Window.ps1 - TIA's main window minimized for an export of many .s7dcl documents, and restored after (decided 2026-11-19).
# On one PC an ExportAsDocuments call took about seven times as long in a TIA with its window showing as with that window
# minimized (docs\agent\openness-measurements.md, Export time with a window).
# Only in a session with a window (connect); a background session has none. The window is the one top-level window of the
# bound TIA process (by its id, not a title) that is visible, has no owner and has a minimize box, and every call that
# changes it first checks that the handle still belongs to that process. The calls are posted (ShowWindowAsync): a busy
# TIA never holds the bridge, and TIA handles them in the order they were posted, also after the bridge's call ended.
# The window ends each call as it was, unless the user touched it: once seen up during the export, it is the user's.
#
# Every way a call leaves the window, as the user at the screen sees it (Tests\Window.Tests.ps1 has one test each):
# - exported all, or the export threw: minimized, then back as it was (maximized, normal size, its monitor); a throw
#   carries no result, the window comes back all the same
# - TIA ended during the export, or in the wait for its minimize: nothing to put back; a handle Windows gave to another
#   program is not touched
# - TIA does not answer at the start (not minimized within the wait): the bridge posts the way back at once, behind its
#   minimize, so whenever TIA handles the two the window ends as it was; the export runs with the window showing
# - TIA does not answer at the end: the restore is posted and waited for; not done within the wait, the result says it
#   comes back when TIA answers, as TIA handles it then
# - TIA does not answer at the start and at the end: as at the start; nothing is left to do at the end
# - the user brought it up during the export: left up; put down again: left down; either way the bridge does not touch
#   it again, and the result says the user brought it up
# - minimized before the call, or none or several windows that could be TIA's main window: left as it was

if (-not ('TiaBridgeWindow' -as [type])) {
    Add-Type -TypeDefinition @'
using System; using System.Collections.Generic; using System.Runtime.InteropServices;
public static class TiaBridgeWindow {
    delegate bool EnumProc(IntPtr h, IntPtr l);
    [DllImport("user32.dll")] static extern bool EnumWindows(EnumProc f, IntPtr l);
    [DllImport("user32.dll")] static extern uint GetWindowThreadProcessId(IntPtr h, out uint pid);
    [DllImport("user32.dll")] static extern bool IsWindowVisible(IntPtr h);
    [DllImport("user32.dll")] static extern IntPtr GetWindow(IntPtr h, uint cmd);
    [DllImport("user32.dll", EntryPoint = "GetWindowLongPtrW")] static extern IntPtr GetWindowLongPtr(IntPtr h, int index);
    [DllImport("user32.dll")] static extern bool IsWindow(IntPtr h);
    [DllImport("user32.dll")] public static extern bool IsIconic(IntPtr h);
    [DllImport("user32.dll")] public static extern bool IsZoomed(IntPtr h);
    [DllImport("user32.dll")] public static extern bool ShowWindowAsync(IntPtr h, int cmd);
    // The top-level windows of a process that can be its main window: visible, no owner, a minimize box.
    public static long[] MainWindows(int pid) {
        var found = new List<long>();
        EnumWindows((h, l) => {
            uint p; GetWindowThreadProcessId(h, out p);
            if (p == (uint)pid && IsWindowVisible(h) && GetWindow(h, 4) == IntPtr.Zero
                && (GetWindowLongPtr(h, -16).ToInt64() & 0x00020000L) != 0) found.Add(h.ToInt64());
            return true;
        }, IntPtr.Zero);
        return found.ToArray();
    }
    // The process a window belongs to; 0 when there is no such window.
    public static int ProcessOf(IntPtr h) {
        if (!IsWindow(h)) return 0;
        uint p; GetWindowThreadProcessId(h, out p);
        return (int)p;
    }
}
'@
}

# The kinds an export writes as .s7dcl (unless as SimaticML); from this many such exports in one call the window is
# minimized; the wait for Windows to report a window minimized or back.
$script:ExportWindowKinds = @('block', 'db', 'type', 'library_type')
$script:ExportWindowFrom = 20
$script:ExportWindowWaitMs = 3000
# ShowWindowAsync's commands
$script:SwMinimize = 6
$script:SwRestore = 9
$script:SwShowMaximized = 3
# The window of the export running: Enter-ExportWindow sets it, Update-ExportWindowSeen and Exit-ExportWindow read it.
$script:ExportWindow = $null

# Seams for the tests: the Windows calls.
function Get-TiaMainWindows([int]$ProcessId) { @([TiaBridgeWindow]::MainWindows($ProcessId)) }
function Get-WindowProcessId([long]$Handle) { [TiaBridgeWindow]::ProcessOf([IntPtr]$Handle) }
function Test-WindowMinimized([long]$Handle) { [TiaBridgeWindow]::IsIconic([IntPtr]$Handle) }
function Test-WindowMaximized([long]$Handle) { [TiaBridgeWindow]::IsZoomed([IntPtr]$Handle) }
function Send-WindowShow([long]$Handle, [int]$Command) { $null = [TiaBridgeWindow]::ShowWindowAsync([IntPtr]$Handle, $Command) }

# Whether the handle is still a window of the bound TIA process: Windows gives a closed window's handle to others.
function Test-TiaWindow([long]$Handle) { (Get-WindowProcessId $Handle) -eq [int]$script:Bridge.processId }

# Waits until Windows reports the window minimized (or, -Back, not minimized), at most ExportWindowWaitMs; whether it is.
function Wait-WindowState([long]$Handle, [switch]$Back) {
    $w = [System.Diagnostics.Stopwatch]::StartNew()
    while ((Test-WindowMinimized $Handle) -eq [bool]$Back) {
        if ($w.ElapsedMilliseconds -ge $script:ExportWindowWaitMs) { return $false }
        Start-Sleep -Milliseconds 50
    }
    $true
}

# Minimizes TIA's main window for an export of Count .s7dcl documents (-1: not known before, as many as it may be). Keeps
# the window's state for Exit-ExportWindow, with note set when it was left as it is; none in a background session, which
# has no window. Never throws: the export runs whatever happens to the window. Outputs nothing.
function Enter-ExportWindow([int]$Count) {
    $script:ExportWindow = $null
    if ($script:Bridge.background) { return }
    # minimized: Windows reported it minimized for this export; touched: the user was seen to have it up since
    $s = @{ handle = [long]0; minimized = $false; touched = $false; note = $null }
    $script:ExportWindow = $s
    $step = [TiaBridgeTimes]::Enter('window')
    try {
        if ($script:Bridge.reportRun) { $s.note = 'TIA left as it was: report run of the TIA dashboard.' }
        elseif ($script:Bridge.settings.minimizeTiaForExport -eq $false) { $s.note = 'TIA left as it was: minimizeTiaForExport is false.' }
        elseif ($Count -ge 0 -and $Count -lt $script:ExportWindowFrom) { $s.note = "TIA left as it was: only $Count object(s) to export as .s7dcl." }
        else {
            $found = @(Get-TiaMainWindows ([int]$script:Bridge.processId))
            if ($found.Count -ne 1) {
                $s.note = "TIA left as it was: $($found.Count) windows could be its main window."
            }
            elseif (Test-WindowMinimized $found[0]) { $s.note = 'TIA was minimized already: left so.' }
            else {
                $h = [long]$found[0]
                $gone = 'TIA left as it was: its window is gone (TIA ended).'
                $back = if (Test-WindowMaximized $h) { $script:SwShowMaximized } else { $script:SwRestore }
                if (-not (Test-TiaWindow $h)) { $s.note = $gone }
                else {
                    Send-WindowShow $h $script:SwMinimize
                    if (Wait-WindowState $h) { $s.handle = $h; $s.minimized = $true }
                    # 3 s later the handle may be another program's: TIA ended in the wait, and its queue with it
                    elseif (-not (Test-TiaWindow $h)) { $s.note = $gone }
                    else {
                        # behind the minimize, so TIA handles both in that order whenever it answers: the window ends as it was
                        Send-WindowShow $h $back
                        $s.note = 'TIA left as it was: it did not answer in time.'
                    }
                }
            }
        }
    }
    catch { $s.note = "TIA left as it was: $($_.Exception.Message)"; Write-BridgeLog "TIA's window: $($_.Exception.Message)" }
    finally { [TiaBridgeTimes]::Exit($step) }
}

# After an object or a part of the export: notes whether the window minimized for it is up. From then on it is the
# user's: Exit-ExportWindow does not touch it.
function Update-ExportWindowSeen {
    $s = $script:ExportWindow
    if (-not $s -or -not $s.minimized -or $s.touched) { return }
    try { if ((Test-TiaWindow $s.handle) -and -not (Test-WindowMinimized $s.handle)) { $s.touched = $true } }
    catch { Write-BridgeLog "TIA's window: $($_.Exception.Message)" }
}

# Puts back the window Enter-ExportWindow minimized, unless the user touched it; what was done, for the result's window
# ($null when Enter-ExportWindow kept nothing). Never throws.
function Exit-ExportWindow {
    $State = $script:ExportWindow
    $script:ExportWindow = $null
    if (-not $State) { return $null }
    if (-not $State.minimized) { return $State.note }
    $step = [TiaBridgeTimes]::Enter('window')
    try {
        if (-not (Test-TiaWindow $State.handle)) { return 'TIA ended during the export: nothing to restore.' }
        if (-not (Test-WindowMinimized $State.handle)) { $State.touched = $true }
        if ($State.touched) {
            if (Test-WindowMinimized $State.handle) { return 'TIA was minimized; the user brought it up during the export, and it is minimized again: left so.' }
            return 'TIA was minimized; the user brought it up during the export: left up.'
        }
        Send-WindowShow $State.handle $script:SwRestore   # maximized again if it was, at its place
        if (Wait-WindowState $State.handle -Back) { return 'TIA was minimized for the export and restored.' }
        'TIA was minimized and is not answering: it comes back up when it answers.'
    }
    catch {
        Write-BridgeLog "TIA's window: $($_.Exception.Message)"
        "TIA was minimized and could not be restored ($($_.Exception.Message)): bring it up from the taskbar."
    }
    finally { [TiaBridgeTimes]::Exit($step) }
}
