# Runs the Pester 3.4 unit tests (no TIA needed). Usage: powershell -NoProfile -File run.ps1 [test file]
# A relative test file is looked up in the current folder, then in this folder. Exits non-zero when a test fails,
# the file does not exist or no test ran.
# A folder's test files run in PRE_COMMIT_WORKERS PowerShell processes at once, dealt out by size (default 4, no more
# than the cores; 1 runs them here). Each worker's Pester output comes whole, one after the other, then the sum of all.
param([string]$Path = $PSScriptRoot)
$found = @($Path, (Join-Path $PSScriptRoot $Path)) | Where-Object { Test-Path $_ } | Select-Object -First 1
if (-not $found) { [Console]::Error.WriteLine("run.ps1: test file not found: $Path"); exit 2 }
# Started by a git-aware parent (a hook or an alias of another repo), a run by hand would carry the parent's repo into
# every git -C of a fixture, whose commits would land there: the names git reads a repo from leave this process.
# Without git, or when it fails, they stay and the tests that need no git still run.
$problem = ''
try {
    $names = @(& git rev-parse --local-env-vars)
    if ($LASTEXITCODE) { $problem = "failed (exit code $LASTEXITCODE)" }
} catch {
    $problem = "did not answer ($($_.Exception.Message))"
}
if ($problem) {
    $names = @()
    [Console]::Error.WriteLine("run.ps1: git rev-parse --local-env-vars $($problem): the names git reads a repo from stay in this process")
}
foreach ($name in $names) { Remove-Item "Env:$name" -ErrorAction SilentlyContinue }
Import-Module Pester -MaximumVersion 3.99
$resolved = (Resolve-Path $found).ProviderPath
$workers = 0
if (-not ([int]::TryParse("$env:PRE_COMMIT_WORKERS", [ref]$workers) -and $workers -gt 0)) {
    $workers = [Math]::Min(4, [Environment]::ProcessorCount)
}
$files = @(if (Test-Path -LiteralPath $resolved -PathType Container) {
    Get-ChildItem -LiteralPath $resolved -Recurse -Filter '*.Tests.ps1' | Sort-Object Length -Descending | ForEach-Object { $_.FullName }
})
if ($workers -le 1 -or $files.Count -le 1) {
    $r = Invoke-Pester -Path $resolved -PassThru
    if ($r.FailedCount) { exit 1 }
    if (-not $r.TotalCount) { [Console]::Error.WriteLine("run.ps1: no test ran in $found"); exit 3 }
    exit 0
}

# The biggest file to the worker with the least so far. A worker gets its files and where to write its counts as
# arguments: its script holds no path, whatever letters the user's temp folder has.
$workers = [Math]::Min($workers, $files.Count)
$batches = @(for ($i = 0; $i -lt $workers; $i++) { , (New-Object System.Collections.Generic.List[string]) })
$sizes = New-Object long[] $workers
foreach ($file in $files) {
    $least = 0
    for ($i = 1; $i -lt $workers; $i++) { if ($sizes[$i] -lt $sizes[$least]) { $least = $i } }
    $batches[$least].Add($file)
    $sizes[$least] += (Get-Item -LiteralPath $file).Length
}
$worker = @'
param([string]$Batch, [string]$Counts)
Import-Module Pester -MaximumVersion 3.99
$r = Invoke-Pester -Path ([IO.File]::ReadAllLines($Batch)) -PassThru
@{ Total = $r.TotalCount; Passed = $r.PassedCount; Failed = $r.FailedCount; Skipped = $r.SkippedCount; Pending = $r.PendingCount
   Inconclusive = $r.InconclusiveCount } | ConvertTo-Json | Set-Content -LiteralPath $Counts -Encoding UTF8
'@
$clock = [Diagnostics.Stopwatch]::StartNew()
$temp = Join-Path ([IO.Path]::GetTempPath()) "tiabridge-pester-$PID-$([Guid]::NewGuid().ToString('N').Substring(0, 8))"
New-Item -ItemType Directory -Path $temp | Out-Null
$workerFile = Join-Path $temp 'worker.ps1'
# with a BOM: Windows PowerShell reads one without in the ANSI code page
[IO.File]::WriteAllText($workerFile, $worker, (New-Object Text.UTF8Encoding $true))
$running = @()
try {
    for ($i = 0; $i -lt $workers; $i++) {
        $batch = Join-Path $temp "batch-$i.txt"
        [IO.File]::WriteAllLines($batch, $batches[$i])
        $start = New-Object Diagnostics.ProcessStartInfo
        $start.FileName = "$env:SystemRoot\System32\WindowsPowerShell\v1.0\powershell.exe"
        $start.Arguments = "-NoProfile -ExecutionPolicy Bypass -File `"$workerFile`" -Batch `"$batch`" -Counts `"$temp\counts-$i.json`""
        $start.UseShellExecute = $false
        $start.CreateNoWindow = $true
        $start.RedirectStandardOutput = $true
        $start.RedirectStandardError = $true
        $p = [Diagnostics.Process]::Start($start)
        $running += @{ process = $p; out = $p.StandardOutput.ReadToEndAsync(); err = $p.StandardError.ReadToEndAsync()
                       counts = "$temp\counts-$i.json"; files = $batches[$i] }
    }
    $sum = @{ Total = 0; Passed = 0; Failed = 0; Skipped = 0; Pending = 0; Inconclusive = 0 }
    $broken = $false
    foreach ($w in $running) {
        $w.process.WaitForExit()
        # its own sum lines leave: the hook's summary greps the one sum below
        [Console]::Out.Write((($w.out.Result -split '\r?\n' | Where-Object { $_ -notmatch '^(Tests completed in |Passed: \d+ Failed: )' }) -join "`r`n"))
        if ($w.err.Result) { [Console]::Error.Write($w.err.Result) }
        if ($w.process.ExitCode -or -not (Test-Path -LiteralPath $w.counts)) {
            $broken = $true
            [Console]::Out.WriteLine("[-] run.ps1: the worker of $($w.files -join ', ') ended with exit code $($w.process.ExitCode)" +
                                     $(if (Test-Path -LiteralPath $w.counts) { '' } else { ', its counts unwritten' }))
            continue
        }
        $counts = Get-Content -LiteralPath $w.counts -Raw | ConvertFrom-Json
        foreach ($key in @($sum.Keys)) { $sum[$key] += [int]$counts.$key }
    }
    [Console]::Out.WriteLine("Tests completed in {0:N2}s" -f $clock.Elapsed.TotalSeconds)
    [Console]::Out.WriteLine("Passed: $($sum.Passed) Failed: $($sum.Failed) Skipped: $($sum.Skipped) Pending: $($sum.Pending) Inconclusive: $($sum.Inconclusive)")
    if ($broken -or $sum.Failed) { exit 1 }
    if (-not $sum.Total) { [Console]::Error.WriteLine("run.ps1: no test ran in $found"); exit 3 }
    exit 0
} finally {
    foreach ($w in $running) { if (-not $w.process.HasExited) { try { $w.process.Kill() } catch { } } }
    Remove-Item -LiteralPath $temp -Recurse -Force -ErrorAction SilentlyContinue
}
