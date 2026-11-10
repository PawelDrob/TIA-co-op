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

# Started by a git-aware parent, the git -C of a fixture would commit to the parent's repo: run.ps1 takes the names git
# reads a repo from out of the test process.
Describe 'run.ps1 and a parent''s repo' {
    # Every name git gives, so a drop cut down to some of them fails here. None is left out: set to a folder, alone or
    # all at once, none made this call fail (git 2.45.1, 2026-11-10), as git answers it before it reads them. The two
    # a hook sets are in it whatever git says, also without git.
    try { $listed = @(& git rev-parse --local-env-vars) } catch { $listed = @() }
    $names = $listed + @('GIT_DIR', 'GIT_WORK_TREE' | Where-Object { $listed -notcontains $_ })
    $parent = @{}
    foreach ($name in $names) { $parent[$name] = "$TestDrive" }
    $kept = "@('$($names -join "', '")' | Where-Object { Test-Path ""Env:`$_"" }) -join ' '"
    $gone = Join-Path $TestDrive 'Gone.Tests.ps1'
    Set-Content $gone "Describe 'g' { It 'has none of its names' { $kept | Should Be '' } }"
    $stay = Join-Path $TestDrive 'Stay.Tests.ps1'
    Set-Content $stay "Describe 's' { It 'has its names' { $kept | Should Be '$($names -join ' ')' } }"
    $noGit = Join-Path $TestDrive 'no-git'
    New-Item -ItemType Directory $noGit | Out-Null
    # a program of Windows that fails on git's arguments stands in for a git that fails
    $failingGit = Join-Path $TestDrive 'failing-git'
    New-Item -ItemType Directory $failingGit | Out-Null
    Copy-Item "$env:SystemRoot\System32\where.exe" (Join-Path $failingGit 'git.exe')

    It 'takes its names out of the test process' {
        $r = Invoke-Runner $gone $TestDrive $parent
        $r.code | Should Be 0
        $r.err | Should Not Match 'git rev-parse --local-env-vars'
    }

    It 'leaves them and says so without git, and runs the tests' {
        $r = Invoke-Runner $stay $TestDrive ($parent + @{ PATH = $noGit })
        $r.code | Should Be 0
        $r.err | Should Match 'run\.ps1: git rev-parse --local-env-vars did not answer \('
    }

    It 'leaves them and says so when git fails, and runs the tests' {
        $r = Invoke-Runner $stay $TestDrive ($parent + @{ PATH = $failingGit })
        $r.code | Should Be 0
        $r.err | Should Match 'run\.ps1: git rev-parse --local-env-vars failed \(exit code \d+\)'
        $r.err | Should Not Match 'did not answer'
    }
}
