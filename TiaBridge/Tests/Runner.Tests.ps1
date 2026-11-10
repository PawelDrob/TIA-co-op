$here = Split-Path -Parent $MyInvocation.MyCommand.Path
$runner = Join-Path $here 'run.ps1'

# Runs run.ps1 in its own powershell.exe from the folder $Cwd, with $Environment on top of this process's; returns the
# exit code, the output and what of it came on stderr.
function Invoke-Runner([string]$Arg, [string]$Cwd, [hashtable]$Environment = @{}) {
    $psi = New-Object System.Diagnostics.ProcessStartInfo
    $psi.FileName = "$env:SystemRoot\System32\WindowsPowerShell\v1.0\powershell.exe"
    $psi.Arguments = "-NoProfile -ExecutionPolicy Bypass -File `"$runner`" `"$Arg`""
    $psi.WorkingDirectory = $Cwd
    $psi.UseShellExecute = $false
    $psi.CreateNoWindow = $true
    $psi.RedirectStandardOutput = $true
    $psi.RedirectStandardError = $true
    foreach ($name in $Environment.Keys) { $psi.EnvironmentVariables[$name] = $Environment[$name] }
    $p = [System.Diagnostics.Process]::Start($psi)
    $errTask = $p.StandardError.ReadToEndAsync()
    $out = $p.StandardOutput.ReadToEnd()
    if (-not $p.WaitForExit(120000)) { $p.Kill(); throw 'run.ps1 did not exit' }
    @{ code = $p.ExitCode; text = $out + $errTask.Result; err = $errTask.Result }
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

# Started by a git-aware parent, the git -C of a fixture would commit to the parent's repo: run.ps1 takes the names git
# reads a repo from out of the test process.
Describe 'run.ps1 and a parent''s repo' {
    $parent = @{ GIT_DIR = "$TestDrive"; GIT_WORK_TREE = "$TestDrive" }
    $kept = "@('GIT_DIR', 'GIT_WORK_TREE' | Where-Object { Test-Path ""Env:`$_"" }) -join ' '"
    $gone = Join-Path $TestDrive 'Gone.Tests.ps1'
    Set-Content $gone "Describe 'g' { It 'has none of its names' { $kept | Should Be '' } }"
    $stay = Join-Path $TestDrive 'Stay.Tests.ps1'
    Set-Content $stay "Describe 's' { It 'has its names' { $kept | Should Be 'GIT_DIR GIT_WORK_TREE' } }"
    $noGit = Join-Path $TestDrive 'no-git'
    New-Item -ItemType Directory $noGit | Out-Null
    # a program of Windows that fails on git's arguments stands in for a git that fails
    $failingGit = Join-Path $TestDrive 'failing-git'
    New-Item -ItemType Directory $failingGit | Out-Null
    Copy-Item "$env:SystemRoot\System32\where.exe" (Join-Path $failingGit 'git.exe')

    It 'takes its names out of the test process' {
        $r = Invoke-Runner $gone $TestDrive $parent
        $r.code | Should Be 0
        $r.err | Should Not Match 'did not answer'
    }

    It 'leaves them and says so without git, and runs the tests' {
        $r = Invoke-Runner $stay $TestDrive ($parent + @{ PATH = $noGit })
        $r.code | Should Be 0
        $r.err | Should Match 'run\.ps1: git rev-parse --local-env-vars did not answer'
    }

    It 'leaves them and says so when git fails, and runs the tests' {
        $r = Invoke-Runner $stay $TestDrive ($parent + @{ PATH = $failingGit })
        $r.code | Should Be 0
        $r.err | Should Match 'run\.ps1: git rev-parse --local-env-vars did not answer \(exit code \d+\)'
    }
}
