$here = Split-Path -Parent $MyInvocation.MyCommand.Path
$runner = Join-Path $here 'run.ps1'

# Runs run.ps1 in its own powershell.exe from the folder $Cwd; returns the exit code and the output.
function Invoke-Runner([string]$Arg, [string]$Cwd) {
    $psi = New-Object System.Diagnostics.ProcessStartInfo
    $psi.FileName = "$env:SystemRoot\System32\WindowsPowerShell\v1.0\powershell.exe"
    $psi.Arguments = "-NoProfile -ExecutionPolicy Bypass -File `"$runner`" `"$Arg`""
    $psi.WorkingDirectory = $Cwd
    $psi.UseShellExecute = $false
    $psi.RedirectStandardOutput = $true
    $psi.RedirectStandardError = $true
    $p = [System.Diagnostics.Process]::Start($psi)
    $errTask = $p.StandardError.ReadToEndAsync()
    $out = $p.StandardOutput.ReadToEnd()
    if (-not $p.WaitForExit(120000)) { $p.Kill(); throw 'run.ps1 did not exit' }
    @{ code = $p.ExitCode; text = $out + $errTask.Result }
}

Describe 'run.ps1' {
    $pass = Join-Path $TestDrive 'Pass.Tests.ps1'
    Set-Content $pass "Describe 'p' { It 'passes' { 1 | Should Be 1 } }"
    $fail = Join-Path $TestDrive 'Fail.Tests.ps1'
    Set-Content $fail "Describe 'f' { It 'fails' { 1 | Should Be 2 } }"
    $empty = Join-Path $TestDrive 'Empty.Tests.ps1'
    Set-Content $empty "Describe 'e' { }"

    It 'exits 0 when the tests pass' {
        (Invoke-Runner $pass $TestDrive).code | Should Be 0
    }

    It 'exits non-zero when a test fails' {
        (Invoke-Runner $fail $TestDrive).code | Should Not Be 0
    }

    It 'exits non-zero and names the path when it does not exist' {
        $r = Invoke-Runner 'Nope.Tests.ps1' $TestDrive
        $r.code | Should Not Be 0
        $r.text | Should Match 'Nope\.Tests\.ps1'
    }

    It 'exits non-zero when no test ran' {
        $r = Invoke-Runner $empty $TestDrive
        $r.code | Should Not Be 0
        $r.text | Should Match 'no test ran'
    }

    It 'resolves a bare file name against the Tests folder' {
        $r = Invoke-Runner 'List.Tests.ps1' $TestDrive
        $r.code | Should Be 0
        $r.text | Should Match 'Passed: 2'
    }

    It 'resolves a file name relative to the current folder first' {
        (Invoke-Runner 'Pass.Tests.ps1' $TestDrive).code | Should Be 0
    }
}
