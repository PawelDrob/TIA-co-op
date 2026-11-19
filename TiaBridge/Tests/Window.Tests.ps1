$here = Split-Path -Parent $MyInvocation.MyCommand.Path
foreach ($f in 'Mcp.ps1', 'Times.ps1', 'Bridge.ps1', 'Window.ps1') { . (Join-Path $here "..\$f") }

# TIA's main window minimized for an export of many .s7dcl documents and restored after (Window.ps1). The Windows calls are
# the seams: a fake window that is minimized or not, there or gone.

# A connect session on TIA process 4242 whose one main window is 77, showing.
function Initialize-WindowSession([hashtable]$Settings = @{}) {
    Initialize-BridgeContext $Settings
    $script:Bridge.processId = 4242
    $script:win = @{ minimized = $false; there = $true; shows = (New-Object System.Collections.ArrayList) }
    Mock Get-TiaMainWindows { if ($ProcessId -eq 4242) { [long]77 } }
    Mock Test-WindowMinimized { $script:win.minimized }
    Mock Test-WindowThere { $script:win.there }
    Mock Send-WindowShow { [void]$script:win.shows.Add("$Handle $Command"); if ($Command -eq 6) { $script:win.minimized = $true } elseif ($Command -eq 9) { $script:win.minimized = $false } }
}

Describe 'the Windows calls' {
    It 'lists the windows of a process and finds none for a process without one' {
        @(Get-TiaMainWindows 0).Count | Should Be 0
        Test-WindowThere 0 | Should Be $false
        Test-WindowMinimized 0 | Should Be $false
    }
}

Describe 'TIA''s window for an export' {
    It 'minimizes the main window of the bound TIA and restores it after' {
        Initialize-WindowSession
        $s = Enter-ExportWindow 100
        $script:win.minimized | Should Be $true
        $note = Exit-ExportWindow $s
        ($script:win.shows -join ',') | Should Be '77 6,77 9'
        $note | Should Be 'TIA''s window was minimized for the export and restored after: on one PC an .s7dcl export took about seven times as long with the window showing.'
    }

    It 'minimizes for an export whose count is not known before' {
        Initialize-WindowSession
        $null = Enter-ExportWindow -1
        $script:win.minimized | Should Be $true
    }

    It 'leaves a window that was minimized already, and puts nothing back' {
        Initialize-WindowSession
        $script:win.minimized = $true
        $note = Exit-ExportWindow (Enter-ExportWindow 100)
        $script:win.shows.Count | Should Be 0
        $note | Should Be 'TIA''s window was minimized already: left so.'
    }

    It 'leaves the window up when it was brought back up during the export, and names the part after which it was seen' {
        Initialize-WindowSession
        $s = Enter-ExportWindow 100
        Update-ExportWindowSeen 'blocks'
        $script:win.minimized = $false
        Update-ExportWindowSeen 'dbs'
        Update-ExportWindowSeen 'types'
        $note = Exit-ExportWindow $s
        ($script:win.shows -join ',') | Should Be '77 6'
        $note | Should Match 'brought back up during it \(seen after part dbs\): left up, so the \.s7dcl exports after that'
    }

    It 'puts nothing back when TIA ended during the export' {
        Initialize-WindowSession
        $s = Enter-ExportWindow 100
        $script:win.there = $false
        $note = Exit-ExportWindow $s
        ($script:win.shows -join ',') | Should Be '77 6'
        $note | Should Match 'is gone now \(TIA ended\): nothing to put back'
    }

    It 'does nothing in a background session, which has no window' {
        Initialize-WindowSession
        $script:Bridge.background = @{ processId = 4242 }
        $s = Enter-ExportWindow 100
        $s | Should Be $null
        Exit-ExportWindow $s | Should Be $null
        $script:win.shows.Count | Should Be 0
    }

    It 'leaves the window as it is, and says why: <why>' -TestCases @(
        @{ why = 'a report run'; count = 100; settings = @{}; reportRun = $true; windows = 1; says = 'a report run of the TIA dashboard' }
        @{ why = 'the setting'; count = 100; settings = @{ minimizeTiaForExport = $false }; reportRun = $false; windows = 1; says = 'minimizeTiaForExport is false' }
        @{ why = 'few .s7dcl exports'; count = 19; settings = @{}; reportRun = $false; windows = 1; says = '19 object\(s\) to export as \.s7dcl; TIA''s window is minimized from 20' }
        @{ why = 'no main window'; count = 100; settings = @{}; reportRun = $false; windows = 0; says = 'has 0 windows that could be its main window' }
        @{ why = 'two main windows'; count = 100; settings = @{}; reportRun = $false; windows = 2; says = 'has 2 windows that could be its main window' }
    ) {
        param($why, $count, $settings, $reportRun, $windows, $says)
        Initialize-WindowSession $settings
        $script:Bridge.reportRun = $reportRun
        $script:windows = $windows
        Mock Get-TiaMainWindows { @([long]77, [long]78) | Select-Object -First $script:windows }
        $note = Exit-ExportWindow (Enter-ExportWindow $count)
        $script:win.shows.Count | Should Be 0
        $note | Should Match "^Left as it was: .*$says"
    }

    It 'minimizes from 20 .s7dcl exports' {
        Initialize-WindowSession
        $null = Enter-ExportWindow 20
        $script:win.minimized | Should Be $true
    }

    It 'restores a window TIA minimized only after the wait, and says it took long' {
        Initialize-WindowSession
        $script:ExportWindowWaitMs = 0
        try {
            Mock Send-WindowShow { [void]$script:win.shows.Add("$Handle $Command"); if ($Command -eq 9) { $script:win.minimized = $false } }
            $s = Enter-ExportWindow 100
            $script:win.minimized = $true   # TIA got to it during the export
            $note = Exit-ExportWindow $s
        }
        finally { $script:ExportWindowWaitMs = 3000 }
        ($script:win.shows -join ',') | Should Be '77 6,77 9'
        $note | Should Match 'restored after.* TIA took more than 0 s to minimize it\.$'
    }

    It 'never stops the export: a window call that fails is said in the note' {
        Initialize-WindowSession
        Mock Get-TiaMainWindows { throw 'access denied' }
        { $script:s = Enter-ExportWindow 100 } | Should Not Throw
        Exit-ExportWindow $script:s | Should Be 'Left as it was: access denied'
        Initialize-WindowSession
        $s = Enter-ExportWindow 100
        Mock Test-WindowThere { throw 'handle not valid' }
        Exit-ExportWindow $s | Should Match 'could not be put back \(handle not valid\): the user can bring it up from the taskbar'
    }
}
