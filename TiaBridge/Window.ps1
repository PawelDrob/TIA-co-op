# Window.ps1 - TIA's main window minimized for an export of many .s7dcl documents, and restored after (decided 2026-11-19).
# On one PC an ExportAsDocuments call took about seven times as long in a TIA with its window showing as with that window
# minimized (docs\agent\openness-v20.md, Export time with a window).
# Only in a session with a window (connect); a background session has none. The window is the one top-level window of the
# bound TIA process (by its id, not a title) that is visible, has no owner and has a minimize box. Every call that changes
# it is posted (ShowWindowAsync): a busy TIA never holds the bridge. A window the user brings back up is left up.

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
    [DllImport("user32.dll")] public static extern bool IsWindow(IntPtr h);
    [DllImport("user32.dll")] public static extern bool IsIconic(IntPtr h);
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
}
'@
}

# From this many .s7dcl exports in one call the window is minimized; the wait for Windows to report it minimized.
$script:ExportWindowFrom = 20
$script:ExportWindowWaitMs = 3000
# The window of the export running (Enter-ExportWindow), for Update-ExportWindowSeen.
$script:ExportWindow = $null

# Seams for the tests: the Windows calls.
function Get-TiaMainWindows([int]$ProcessId) { @([TiaBridgeWindow]::MainWindows($ProcessId)) }
function Test-WindowMinimized([long]$Handle) { [TiaBridgeWindow]::IsIconic([IntPtr]$Handle) }
function Test-WindowThere([long]$Handle) { [TiaBridgeWindow]::IsWindow([IntPtr]$Handle) }
function Send-WindowShow([long]$Handle, [int]$Command) { $null = [TiaBridgeWindow]::ShowWindowAsync([IntPtr]$Handle, $Command) }

# Waits until Windows reports the window minimized, at most ExportWindowWaitMs; whether it is.
function Wait-WindowMinimized([long]$Handle) {
    $w = [System.Diagnostics.Stopwatch]::StartNew()
    while (-not (Test-WindowMinimized $Handle)) {
        if ($w.ElapsedMilliseconds -ge $script:ExportWindowWaitMs) { return $false }
        Start-Sleep -Milliseconds 50
    }
    $true
}

# Minimizes TIA's main window for an export of Count .s7dcl documents (-1: not known before, as many as it may be).
# Returns the window's state for Exit-ExportWindow, with note set when it was left as it is; $null in a background session,
# which has no window. Never throws: the export runs whatever happens to the window.
function Enter-ExportWindow([int]$Count) {
    $script:ExportWindow = $null
    if ($script:Bridge.background) { return $null }
    $s = @{ handle = [long]0; minimized = $false; late = $false; shownAfter = $null; note = $null }
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
                $s.handle = [long]$found[0]
                Send-WindowShow $s.handle 6   # SW_MINIMIZE
                $s.minimized = $true
                $s.late = -not (Wait-WindowMinimized $s.handle)
            }
        }
    }
    catch {
        if (-not $s.minimized) { $s.note = "Left as it was: $($_.Exception.Message)" }
        Write-BridgeLog "TIA's window: $($_.Exception.Message)"
    }
    finally { [TiaBridgeTimes]::Exit($step) }
    $s
}

# After part After of the export: notes the first part after which the window minimized for it was up again.
function Update-ExportWindowSeen([string]$After) {
    $s = $script:ExportWindow
    if (-not $s -or -not $s.minimized -or $s.shownAfter) { return }
    try { if ((Test-WindowThere $s.handle) -and -not (Test-WindowMinimized $s.handle)) { $s.shownAfter = $After } }
    catch { Write-BridgeLog "TIA's window: $($_.Exception.Message)" }
}

# Puts back the window Enter-ExportWindow minimized, if it is still minimized; what was done, for the result's window
# ($null for no state). Never throws.
function Exit-ExportWindow($State) {
    $script:ExportWindow = $null
    if (-not $State) { return $null }
    if (-not $State.minimized) { return $State.note }
    $why = 'on one PC an .s7dcl export took about seven times as long with the window showing'
    $step = [TiaBridgeTimes]::Enter('window')
    try {
        if (-not (Test-WindowThere $State.handle)) { return "TIA's window was minimized for the export and is gone now (TIA ended): nothing to put back." }
        if (-not (Test-WindowMinimized $State.handle)) {
            $when = if ($State.shownAfter) { " (seen after part $($State.shownAfter))" } else { '' }
            return "TIA's window was minimized for the export ($why) and brought back up during it${when}: left up, so the .s7dcl exports after that cost what they cost with the window showing."
        }
        Send-WindowShow $State.handle 9   # SW_RESTORE: maximized again if it was, at its place
        $late = if ($State.late) { " TIA took more than $([int]($script:ExportWindowWaitMs / 1000)) s to minimize it." } else { '' }
        "TIA's window was minimized for the export and restored after: $why.$late"
    }
    catch {
        Write-BridgeLog "TIA's window: $($_.Exception.Message)"
        "TIA's window was minimized for the export and could not be put back ($($_.Exception.Message)): the user can bring it up from the taskbar."
    }
    finally { [TiaBridgeTimes]::Exit($step) }
}
