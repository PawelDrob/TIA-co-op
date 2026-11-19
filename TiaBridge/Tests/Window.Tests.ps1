$here = Split-Path -Parent $MyInvocation.MyCommand.Path
foreach ($f in 'Mcp.ps1', 'Times.ps1', 'Bridge.ps1', 'Window.ps1') { . (Join-Path $here "..\$f") }

# TIA's main window minimized for an export of many .s7dcl documents and put back after (Window.ps1): one test per way a
# call can leave the window, as the head of Window.ps1 lists them. The Windows calls are the seams.

# A fake TIA, process 4242, whose one main window 77 is in State (normal, max, min). Like Windows it keeps the state a
# restore brings back, and it handles the posted commands in order, only while it answers (busy: they wait in its queue).
# owner: the process Windows says the handle belongs to (0: no window).
function Initialize-WindowSession([hashtable]$Settings = @{}, [string]$State = 'normal') {
    Initialize-BridgeContext $Settings
    $script:Bridge.processId = 4242
    $script:win = @{ state = $State; restoreTo = $State; busy = $false; owner = 4242
                     queue = (New-Object System.Collections.ArrayList); shows = (New-Object System.Collections.ArrayList) }
    Mock Get-TiaMainWindows { if ($ProcessId -eq 4242) { [long]77 } }
    Mock Get-WindowProcessId { $script:win.owner }
    Mock Test-WindowMinimized { $script:win.state -eq 'min' }
    Mock Test-WindowMaximized { $script:win.state -eq 'max' }
    Mock Send-WindowShow { [void]$script:win.shows.Add($Command); [void]$script:win.queue.Add($Command); if (-not $script:win.busy) { Invoke-FakeTiaAnswer } }
}

# TIA answers again: it handles what was posted, in order.
function Invoke-FakeTiaAnswer {
    $script:win.busy = $false
    foreach ($c in @($script:win.queue)) { Invoke-FakeShow $c }
    $script:win.queue.Clear()
}

# One command as ShowWindow does it: 6 minimize (the state before is what a restore brings back), 9 restore (a window
# that is not minimized and maximized goes to its normal size), 3 maximize. The user's own clicks are these too.
function Invoke-FakeShow([int]$Command) {
    $w = $script:win
    switch ($Command) {
        6 { if ($w.state -ne 'min') { $w.restoreTo = $w.state; $w.state = 'min' } }
        9 { if ($w.state -eq 'min') { $w.state = $w.restoreTo } elseif ($w.state -eq 'max') { $w.state = 'normal' } }
        3 { $w.state = 'max' }
    }
}

# The wait for Windows to report the window minimized or back, at once in a test of a TIA that does not answer.
function Invoke-WithoutWait([scriptblock]$Body) {
    $wait = $script:ExportWindowWaitMs; $script:ExportWindowWaitMs = 0
    try { & $Body } finally { $script:ExportWindowWaitMs = $wait }
}

$restored = 'TIA''s window was minimized for the export and restored after: on one PC an .s7dcl export took about seven times as long with the window showing.'

Describe 'the Windows calls' {
    It 'lists the windows of a process and finds none for a process without one' {
        @(Get-TiaMainWindows 0).Count | Should Be 0
        Get-WindowProcessId 0 | Should Be 0
        Test-WindowMinimized 0 | Should Be $false
        Test-WindowMaximized 0 | Should Be $false
    }
}

Describe 'TIA''s window after an export: the export ran' {
    It 'exported all: a window in its normal size is minimized during the export and back in its normal size after' {
        Initialize-WindowSession
        Enter-ExportWindow 100
        $script:win.state | Should Be 'min'
        $note = Exit-ExportWindow
        $script:win.state | Should Be 'normal'
        ($script:win.shows -join ',') | Should Be '6,9'
        $note | Should Be $restored
    }

    It 'exported all: a maximized window is maximized again after' {
        Initialize-WindowSession -State 'max'
        Enter-ExportWindow 100
        $note = Exit-ExportWindow
        $script:win.state | Should Be 'max'
        $note | Should Be $restored
    }

    It 'the export threw: the window is back as it was, from the finally around it' {
        Initialize-WindowSession -State 'max'
        { try { Enter-ExportWindow 100; throw 'export failed' } finally { $null = Exit-ExportWindow } } | Should Throw 'export failed'
        $script:win.state | Should Be 'max'
    }

    It 'minimizes for an export whose count is not known before, and from 20 .s7dcl exports' {
        Initialize-WindowSession
        Enter-ExportWindow -1
        $script:win.state | Should Be 'min'
        Initialize-WindowSession
        Enter-ExportWindow 20
        $script:win.state | Should Be 'min'
    }

    It 'writes nothing into the output of the export it runs in' {
        Initialize-WindowSession
        @(Enter-ExportWindow 100).Count | Should Be 0
        $null = Exit-ExportWindow
        $script:Bridge.background = @{ processId = 4242 }
        @(Enter-ExportWindow 100).Count | Should Be 0
    }
}

Describe 'TIA''s window after an export: TIA ended or did not answer' {
    It 'TIA ended during the export: nothing to put back' {
        Initialize-WindowSession
        Enter-ExportWindow 100
        $script:win.owner = 0
        $note = Exit-ExportWindow
        ($script:win.shows -join ',') | Should Be '6'
        $note | Should Be 'TIA''s window was minimized for the export and is gone now (TIA ended): nothing to put back.'
    }

    It 'TIA ended and Windows gave the handle to another program, whose window is minimized: it is not touched' {
        Initialize-WindowSession
        Enter-ExportWindow 100
        $script:win.owner = 999
        Update-ExportWindowSeen 'after part blocks'
        $note = Exit-ExportWindow
        ($script:win.shows -join ',') | Should Be '6'
        $note | Should Match 'is gone now \(TIA ended\): nothing to put back'
    }

    It 'TIA does not answer at the start: the way back is posted behind the minimize, and the window ends as it was (<state>)' -TestCases @(
        @{ state = 'normal'; back = 9 }, @{ state = 'max'; back = 3 }
    ) {
        param($state, $back)
        Initialize-WindowSession -State $state
        $script:win.busy = $true
        Invoke-WithoutWait { Enter-ExportWindow 100; Update-ExportWindowSeen 'after part blocks'; $script:note = Exit-ExportWindow }
        ($script:win.shows -join ',') | Should Be "6,$back"
        $script:note | Should Be 'Left as it was: TIA did not minimize its window within 0 s (busy, or not answering), so the bridge asked it at once to put the window back as it was; the export ran with the window showing.'
        Invoke-FakeTiaAnswer
        $script:win.state | Should Be $state
    }

    It 'TIA does not answer at the start and answers during the export: the window is up, as it was, through the export' {
        Initialize-WindowSession -State 'max'
        $script:win.busy = $true
        Invoke-WithoutWait { Enter-ExportWindow 100 }
        Invoke-FakeTiaAnswer
        Update-ExportWindowSeen 'after part blocks'
        $note = Exit-ExportWindow
        $script:win.state | Should Be 'max'
        ($script:win.shows -join ',') | Should Be '6,3'
        $note | Should Match '^Left as it was: TIA did not minimize its window'
    }

    It 'TIA does not answer at the end: the restore is posted, the result says it comes when TIA answers, and it does' {
        Initialize-WindowSession -State 'max'
        Enter-ExportWindow 100
        $script:win.busy = $true
        $note = Invoke-WithoutWait { Exit-ExportWindow }
        $script:win.state | Should Be 'min'
        $note | Should Be ('TIA''s window was minimized for the export (on one PC an .s7dcl export took about seven times as long with the window showing). ' +
                           'The bridge asked TIA to restore it, and TIA had not within 0 s (busy, or not answering): it comes back when TIA answers.')
        Invoke-FakeTiaAnswer
        $script:win.state | Should Be 'max'
    }
}

Describe 'TIA''s window after an export: the user touched it' {
    It 'the user brought it up during the export: it is left up and is the user''s from then on' {
        Initialize-WindowSession
        Enter-ExportWindow 100
        Update-ExportWindowSeen 'after block A'
        Invoke-FakeShow 9
        Update-ExportWindowSeen 'after block B'
        Update-ExportWindowSeen 'after part blocks'
        $note = Exit-ExportWindow
        $script:win.state | Should Be 'normal'
        ($script:win.shows -join ',') | Should Be '6'
        $note | Should Be ('TIA''s window was minimized for the export (on one PC an .s7dcl export took about seven times as long with the window showing) and brought back up during it ' +
                           '(seen up after block B): from then on it was the user''s, and the bridge did not touch it again. It is up now. The .s7dcl exports while it was up cost what they cost with the window showing.')
    }

    It 'the user brought it up and put it down again: it stays down, the bridge does not restore it' {
        Initialize-WindowSession -State 'max'
        Enter-ExportWindow 100
        Invoke-FakeShow 9
        Update-ExportWindowSeen 'after block A'
        Invoke-FakeShow 6
        Update-ExportWindowSeen 'after block B'
        $note = Exit-ExportWindow
        $script:win.state | Should Be 'min'
        ($script:win.shows -join ',') | Should Be '6'
        $note | Should Match '\(seen up after block A\): .* It is minimized now, as the user left it.'
    }

    It 'the user brought it up, put it down and up again: it stays up' {
        Initialize-WindowSession
        Enter-ExportWindow 100
        Invoke-FakeShow 9; Update-ExportWindowSeen 'after block A'
        Invoke-FakeShow 6; Update-ExportWindowSeen 'after block B'
        Invoke-FakeShow 9; Update-ExportWindowSeen 'after block C'
        $note = Exit-ExportWindow
        $script:win.state | Should Be 'normal'
        ($script:win.shows -join ',') | Should Be '6'
        $note | Should Match '\(seen up after block A\): .* It is up now\.'
    }

    It 'the user brought it up after the last look: it is left up, seen at the end' {
        Initialize-WindowSession
        Enter-ExportWindow 100
        Update-ExportWindowSeen 'after block A'
        Invoke-FakeShow 9
        $note = Exit-ExportWindow
        ($script:win.shows -join ',') | Should Be '6'
        $note | Should Match '\(seen up at the end\): .* It is up now\.'
    }
}

Describe 'TIA''s window after an export: left as it was' {
    It 'a window minimized before the call stays minimized, and nothing is put back' {
        Initialize-WindowSession -State 'min'
        Enter-ExportWindow 100
        $note = Exit-ExportWindow
        $script:win.state | Should Be 'min'
        $script:win.shows.Count | Should Be 0
        $note | Should Be 'TIA''s window was minimized already: left so.'
    }

    It 'does nothing in a background session, which has no window' {
        Initialize-WindowSession
        $script:Bridge.background = @{ processId = 4242 }
        Enter-ExportWindow 100
        $script:ExportWindow | Should Be $null
        Exit-ExportWindow | Should Be $null
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
        Enter-ExportWindow $count; $note = Exit-ExportWindow
        $script:win.shows.Count | Should Be 0
        $script:win.state | Should Be 'normal'
        $note | Should Match "^Left as it was: .*$says"
    }

    It 'never stops the export: a window call that fails is said in the note' {
        Initialize-WindowSession
        Mock Get-TiaMainWindows { throw 'access denied' }
        { Enter-ExportWindow 100 } | Should Not Throw
        Exit-ExportWindow | Should Be 'Left as it was: access denied'
        Initialize-WindowSession
        Enter-ExportWindow 100
        Mock Get-WindowProcessId { throw 'handle not valid' }
        Exit-ExportWindow | Should Match 'could not be put back \(handle not valid\): the user can bring it up from the taskbar'
    }
}
