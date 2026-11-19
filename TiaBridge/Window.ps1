# Window.ps1 - TIA's main window minimized for an export of many .s7dcl documents, and restored after (decided 2026-11-19).
# On one PC an ExportAsDocuments call took about seven times as long in a TIA with its window showing as with that window
# minimized (docs\agent\openness-v20.md, Export time with a window).
# Only in a session with a window (connect); a background session has none. The window is the one top-level window of the
# bound TIA process (by its id, not a title) that is visible, has no owner and has a minimize box, and every call that
# changes it first checks that the handle still belongs to that process. The calls are posted (ShowWindowAsync): a busy
# TIA never holds the bridge, and TIA handles them in the order they were posted, also after the bridge's call ended.
# The window ends each call as it was, unless the user touched it: once seen up during the export, it is the user's.
#
# Every way a call leaves the window, as the user at the screen sees it (Tests\Window.Tests.ps1 has one test each):
# - exported all, or the export threw: minimized, then back as it was (maximized, normal size, its monitor); a throw
#   carries no result, the window comes back all the same
# - TIA ended during the export: nothing to put back; a handle Windows gave to another program is not touched
# - TIA does not answer at the start (not minimized within the wait): the bridge posts the way back at once, behind its
#   minimize, so whenever TIA handles the two the window ends as it was; the export runs with the window showing
# - TIA does not answer at the end: the restore is posted and waited for; not done within the wait, the result says it
#   comes back when TIA answers, as TIA handles it then
# - TIA does not answer at the start and at the end: as at the start; nothing is left to do at the end
# - the user brought it up during the export: left up; put down again: left down; either way the bridge does not touch
#   it again, and the result says where it was first seen up
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
    # minimized: Windows reported it minimized for this export; touched: where the user was first seen to have it up
    $s = @{ handle = [long]0; minimized = $false; touched = $null; note = $null }
    $script:ExportWindow = $s
    $step = [TiaBridgeTimes]::Enter('window')
    try {
        if ($script:Bridge.reportRun) { $s.note = 'Left as it was: a report run of the TIA dashboard does not minimize TIA''s window.' }
        elseif ($script:Bridge.settings.minimizeTiaForExport -eq $false) { $s.note = 'Left as it was: minimizeTiaForExport is false in TiaBridge\settings.json.' }
        elseif ($Count -ge 0 -and $Count -lt $script:ExportWindowFrom) {
            $s.note = "Left as it was: $Count object(s) to export as .s7dcl; TIA's window is minimized from $script:ExportWindowFrom."
        }
        else {
            $found = @(Get-TiaMainWindows ([int]$script:Bridge.processId))
            if ($found.Count -ne 1) {
                $s.note = "Left as it was: TIA process $($script:Bridge.processId) has $($found.Count) windows that could be its main window (visible, without owner, with a minimize box), so the bridge cannot tell which."
            }
            elseif (Test-WindowMinimized $found[0]) { $s.note = 'TIA''s window was minimized already: left so.' }
            else {
                $h = [long]$found[0]
                $back = if (Test-WindowMaximized $h) { $script:SwShowMaximized } else { $script:SwRestore }
                Send-WindowShow $h $script:SwMinimize
                if (Wait-WindowState $h) { $s.handle = $h; $s.minimized = $true }
                else {
                    # behind the minimize, so TIA handles both in that order whenever it answers: the window ends as it was
                    Send-WindowShow $h $back
                    $s.note = "Left as it was: TIA did not minimize its window within $([int]($script:ExportWindowWaitMs / 1000)) s (busy, or not answering), so the bridge asked it at once to put the window back as it was; the export ran with the window showing."
                }
            }
        }
    }
    catch { $s.note = "Left as it was: $($_.Exception.Message)"; Write-BridgeLog "TIA's window: $($_.Exception.Message)" }
    finally { [TiaBridgeTimes]::Exit($step) }
}

# Where in the export it is (After: 'after part blocks', 'after block FB1'): notes the first place the window minimized for
# it was seen up. From then on it is the user's: Exit-ExportWindow does not touch it.
function Update-ExportWindowSeen([string]$After) {
    $s = $script:ExportWindow
    if (-not $s -or -not $s.minimized -or $s.touched) { return }
    try { if ((Test-TiaWindow $s.handle) -and -not (Test-WindowMinimized $s.handle)) { $s.touched = $After } }
    catch { Write-BridgeLog "TIA's window: $($_.Exception.Message)" }
}

# Puts back the window Enter-ExportWindow minimized, unless the user touched it; what was done, for the result's window
# ($null when Enter-ExportWindow kept nothing). Never throws.
function Exit-ExportWindow {
    $State = $script:ExportWindow
    $script:ExportWindow = $null
    if (-not $State) { return $null }
    if (-not $State.minimized) { return $State.note }
    $why = 'on one PC an .s7dcl export took about seven times as long with the window showing'
    $step = [TiaBridgeTimes]::Enter('window')
    try {
        if (-not (Test-TiaWindow $State.handle)) { return "TIA's window was minimized for the export and is gone now (TIA ended): nothing to put back." }
        if (-not $State.touched -and -not (Test-WindowMinimized $State.handle)) { $State.touched = 'at the end' }
        if ($State.touched) {
            $now = if (Test-WindowMinimized $State.handle) { 'minimized now, as the user left it' } else { 'up now' }
            return "TIA's window was minimized for the export ($why) and brought back up during it (seen up $($State.touched)): from then on it was the user's, and the bridge did not touch it again. It is $now. The .s7dcl exports while it was up cost what they cost with the window showing."
        }
        Send-WindowShow $State.handle $script:SwRestore   # maximized again if it was, at its place
        if (Wait-WindowState $State.handle -Back) { return "TIA's window was minimized for the export and restored after: $why." }
        "TIA's window was minimized for the export ($why). The bridge asked TIA to restore it, and TIA had not within $([int]($script:ExportWindowWaitMs / 1000)) s (busy, or not answering): it comes back when TIA answers."
    }
    catch {
        Write-BridgeLog "TIA's window: $($_.Exception.Message)"
        "TIA's window was minimized for the export and could not be put back ($($_.Exception.Message)): the user can bring it up from the taskbar."
    }
    finally { [TiaBridgeTimes]::Exit($step) }
}
