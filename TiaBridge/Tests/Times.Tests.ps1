$here = Split-Path -Parent $MyInvocation.MyCommand.Path
. (Join-Path $here '..\Times.ps1')

# The times of a full_export (Times.ps1): every tick in one step, a step inside another taken from the outer one, the
# steps of a part adding up to it, the calls into Openness apart, the slowest objects of a part.

# A clock the test moves: Ms on from where it stands.
function Start-TestTimes {
    [TiaBridgeTimes]::TestTicks = 0
    Start-ExportTimes
}
function Step-TestClock([double]$Ms) { [TiaBridgeTimes]::TestTicks += [long]($Ms * [System.Diagnostics.Stopwatch]::Frequency / 1000) }

Describe 'TiaBridgeTimes: Enter and Exit' {
    It 'gives each tick to the step that runs; a step inside another stops the outer one' {
        Start-TestTimes
        Enter-PartTimes 'blocks' 'PLC_1'
        Step-TestClock 1                                  # other
        $w = [TiaBridgeTimes]::Enter('move'); Step-TestClock 2
        $c = [TiaBridgeTimes]::Enter('compare'); Step-TestClock 5; [TiaBridgeTimes]::Exit($c)
        Step-TestClock 3; [TiaBridgeTimes]::Exit($w)
        $x = [TiaBridgeTimes]::Enter('tia_export_s7dcl'); Step-TestClock 50; [TiaBridgeTimes]::Exit($x)
        $x = [TiaBridgeTimes]::Enter('tia_export_s7dcl'); Step-TestClock 10; [TiaBridgeTimes]::Exit($x)
        Step-TestClock 4                                  # other
        Exit-PartTimes | Should Be 75
        $r = Stop-ExportTimes
        $p = $r.parts[0]
        "$($p.part)@$($p.device) $($p.ms) $($p.tiaMs)" | Should Be 'blocks@PLC_1 75 60'
        $p.steps.tia_export_s7dcl.ms | Should Be 60
        $p.steps.tia_export_s7dcl.n | Should Be 2
        $p.steps.move.ms | Should Be 5
        $p.steps.compare.ms | Should Be 5
        $p.steps.other.ms | Should Be 5
        @($p.steps.Keys)[0] | Should Be 'tia_export_s7dcl'
        $sum = 0; foreach ($s in $p.steps.Values) { $sum += $s.ms }
        $sum | Should Be 75
        $r.tiaMs | Should Be 60
    }

    It 'counts the export after a refused one apart, as tia_export_retry' {
        Start-TestTimes
        Enter-PartTimes 'blocks'
        $x = [TiaBridgeTimes]::Enter('tia_export_s7dcl'); Step-TestClock 7; [TiaBridgeTimes]::Exit($x)
        Enter-ExportRetry
        try { $x = [TiaBridgeTimes]::Enter('tia_export_xml'); Step-TestClock 9; [TiaBridgeTimes]::Exit($x) }
        finally { Exit-ExportRetry }
        $x = [TiaBridgeTimes]::Enter('tia_export_xml'); Step-TestClock 2; [TiaBridgeTimes]::Exit($x)
        $null = Exit-PartTimes
        $p = (Stop-ExportTimes).parts[0]
        "$($p.steps.tia_export_s7dcl.ms) $($p.steps.tia_export_retry.ms) $($p.steps.tia_export_xml.ms)" | Should Be '7 9 2'
    }

    It 'measures nothing outside a full_export' {
        Stop-ExportTimesClock
        $changes = [TiaBridgeTimes]::Changes
        [TiaBridgeTimes]::Enter('move') | Should Be $null
        [TiaBridgeTimes]::Exit('other')
        [TiaBridgeTimes]::Changes | Should Be $changes
        Enter-PartTimes 'blocks'; Exit-PartTimes | Should Be $null
        Get-ObjectTimeMark | Should Be $null
        Add-ObjectTime $null 'A' '' @()
        Stop-ExportTimes | Should Be $null
    }
}

Describe 'Stop-ExportTimes' {
    It 'puts what is outside the plan and the parts in once, and the plan apart' {
        Start-TestTimes
        Step-TestClock 3                                  # once: other
        Enter-PartTimes 'plan'
        $x = [TiaBridgeTimes]::Enter('tia_state'); Step-TestClock 20; [TiaBridgeTimes]::Exit($x)
        Step-TestClock 1
        $null = Exit-PartTimes -Plan
        Enter-PartTimes 'blocks'; Step-TestClock 30; $null = Exit-PartTimes
        $x = [TiaBridgeTimes]::Enter('mirror'); Step-TestClock 4
        $g = [TiaBridgeTimes]::Enter('git'); Step-TestClock 6; [TiaBridgeTimes]::Exit($g); [TiaBridgeTimes]::Exit($x)
        $r = Stop-ExportTimes
        "$($r.ms) $($r.tiaMs)" | Should Be '64 20'
        "$($r.plan.ms) $($r.plan.tiaMs) $($r.plan.steps.tia_state.ms) $($r.plan.steps.other.ms)" | Should Be '21 20 20 1'
        "$($r.once.ms) $($r.once.steps.other.ms) $($r.once.steps.mirror.ms) $($r.once.steps.git.ms)" | Should Be '13 3 4 6'
        $r.once.ms + $r.plan.ms + $r.parts[0].ms | Should Be $r.ms
        $r.stepChanges | Should BeGreaterThan 0
        $script:ExportTimes | Should Be $null
        [TiaBridgeTimes]::On | Should Be $false
    }

    It 'ends a part still open with the span of its steps' {
        Start-TestTimes
        Enter-PartTimes 'blocks'; Step-TestClock 12
        $r = Stop-ExportTimes
        $r.parts[0].ms | Should Be 12
    }
}

Describe 'the slowest objects of a part' {
    It 'keeps the ten slowest, the slowest first, with their time in Openness and the size of their files' {
        $repo = Join-Path $TestDrive 'repo'
        New-Item -ItemType Directory -Force -Path (Join-Path $repo 'plc\blocks') | Out-Null
        [System.IO.File]::WriteAllText((Join-Path $repo 'plc\blocks\B7.s7dcl'), '1234567')
        [System.IO.File]::WriteAllText((Join-Path $repo 'plc\blocks\B7.s7res'), '123')
        $script:Bridge = @{ repo = $repo }
        Start-TestTimes
        Enter-PartTimes 'blocks'
        foreach ($i in 1..12) {
            $m = Get-ObjectTimeMark
            $x = [TiaBridgeTimes]::Enter('tia_export_s7dcl'); Step-TestClock $i; [TiaBridgeTimes]::Exit($x)
            Step-TestClock 1
            Add-ObjectTime $m "B$i" 'F' @("plc\blocks\B$i.s7dcl", "plc\blocks\B$i.s7res")
        }
        $m = Get-ObjectTimeMark; Step-TestClock 0.5; Add-ObjectTime $m 'S' '' @('plc\blocks\S.s7dcl') -Skipped
        $null = Exit-PartTimes
        $p = (Stop-ExportTimes).parts[0]
        @($p.slowest | ForEach-Object { $_.name }) -join ',' | Should Be 'B12,B11,B10,B9,B8,B7,B6,B5,B4,B3'
        $b7 = $p.slowest | Where-Object { $_.name -eq 'B7' }
        "$($b7.folder) $($b7.ms) $($b7.tiaMs) $($b7.bytes) $($b7.files)" | Should Be 'F 8 7 10 2'
        $p.slowest[0].bytes | Should Be 0
        "$($p.objects.n) $($p.objects.medianMs) $($p.objects.p90Ms) $($p.objects.maxMs)" | Should Be '13 7 12 13'
    }

    It 'marks a skipped object among them' {
        $script:Bridge = @{ repo = $TestDrive }
        Start-TestTimes
        Enter-PartTimes 'blocks'
        $m = Get-ObjectTimeMark; Step-TestClock 2; Add-ObjectTime $m 'S' '' @() -Skipped
        $p = (Stop-ExportTimes).parts[0]
        $p.slowest[0].skipped | Should Be $true
    }
}
