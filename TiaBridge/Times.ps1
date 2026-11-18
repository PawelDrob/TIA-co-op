# Times.ps1 - where the time of a full_export goes (decided 2026-11-17): per part and step, and the slowest objects of a part.
# One stopwatch, its ticks given to one step at a time: a step entered inside another stops the outer one's share until it
# ends, so the steps of a part add up to the part's time. Steps named tia_* are calls into Openness; every other step is the
# bridge's own work, and other is what no step names. A step is entered and left by the class below, called directly:
#     $step = [TiaBridgeTimes]::Enter('move'); try { ... } finally { [TiaBridgeTimes]::Exit($step) }
# Off outside a full_export (Enter returns $null). On, a step costs about 2 microseconds and no call into TIA.

if (-not ('TiaBridgeTimes' -as [type])) {
    Add-Type -TypeDefinition @'
using System; using System.Collections.Generic; using System.Diagnostics;
public static class TiaBridgeTimes {
    public static bool On; public static bool Retry;
    public static string Step = "other";
    public static long Mark, TiaTicks, Changes;
    // a test sets the clock's ticks; below 0 the stopwatch runs
    public static long TestTicks = -1;
    public static Dictionary<string, long[]> Bucket;
    static Stopwatch clock = new Stopwatch();
    static bool tia;
    public static long Now() { return TestTicks >= 0 ? TestTicks : clock.ElapsedTicks; }
    public static void Start(Dictionary<string, long[]> bucket) {
        clock.Restart(); Mark = Now(); Step = "other"; tia = false; TiaTicks = 0; Changes = 0; Retry = false; Bucket = bucket; On = true;
    }
    public static void Stop() { On = false; Retry = false; Bucket = null; TestTicks = -1; clock.Stop(); }
    // the ticks since the last change to the step that ran; To runs from now. Count: To was entered.
    static void Give(string to, bool count) {
        long now = Now(); long d = now - Mark; long[] a;
        Mark = now; Changes++;
        if (!Bucket.TryGetValue(Step, out a)) { a = new long[2]; Bucket[Step] = a; }
        a[0] += d;
        if (tia) TiaTicks += d;
        Step = to; tia = to.StartsWith("tia_", StringComparison.Ordinal);
        if (count) { if (!Bucket.TryGetValue(to, out a)) { a = new long[2]; Bucket[to] = a; } a[1]++; }
    }
    // Enters a step; returns the one that ran, for Exit. An export after a refused one (Retry) is tia_export_retry.
    public static string Enter(string step) {
        if (!On) return null;
        if (Retry && step.StartsWith("tia_export_", StringComparison.Ordinal)) step = "tia_export_retry";
        string was = Step; Give(step, true); return was;
    }
    public static void Exit(string was) { if (On && was != null) Give(was, false); }
    // Brings the ticks up to now into the step that runs.
    public static void Flush() { if (On) Give(Step, false); }
    // Gives the ticks up to now to the bucket in use, then counts into Next from step other.
    public static void UseBucket(Dictionary<string, long[]> next) { if (!On) return; Give("other", false); Bucket = next; tia = false; }
}
'@
}

$script:ExportTimes = $null
$script:SlowestObjectCount = 10

function New-TimesBucket([string]$Part = '', [string]$Device = '') {
    @{ part = $Part; device = $Device; steps = (New-Object 'System.Collections.Generic.Dictionary[string,long[]]'); start = [long]0
       slowest = (New-Object System.Collections.ArrayList); objectTicks = (New-Object 'System.Collections.Generic.List[long]') }
}

# Starts the times of a full_export: from here every tick goes to a step of the export (once) until a part begins.
function Start-ExportTimes {
    $once = New-TimesBucket
    $script:ExportTimes = @{ once = $once; bucket = $once; plan = $null; parts = (New-Object System.Collections.ArrayList) }
    [TiaBridgeTimes]::Start($once.steps)
}

# The exports between Enter-ExportRetry and Exit-ExportRetry are second ones, after a refused first one.
function Enter-ExportRetry { [TiaBridgeTimes]::Retry = [TiaBridgeTimes]::On }
function Exit-ExportRetry { [TiaBridgeTimes]::Retry = $false }

# The plan (what TIA says of the objects, before any part) or a part: its steps from here to Exit-PartTimes.
function Enter-PartTimes([string]$Part, [string]$Device = '') {
    $t = $script:ExportTimes
    if (-not $t) { return }
    $b = New-TimesBucket $Part $Device
    [TiaBridgeTimes]::UseBucket($b.steps)
    $b.start = [TiaBridgeTimes]::Mark
    $t.bucket = $b
}

# Ms: the part's time as the part measured it (its line); the plan gives none and takes the span of its steps.
function Exit-PartTimes([int]$Ms = -1, [switch]$Plan) {
    $t = $script:ExportTimes
    if (-not $t -or $t.bucket -eq $t.once) { return }
    $b = $t.bucket
    [TiaBridgeTimes]::UseBucket($t.once.steps)
    $b.ms = $(if ($Ms -ge 0) { $Ms } else { [int](ConvertTo-Ms ([TiaBridgeTimes]::Mark - $b.start)) })
    if ($Plan) { $t.plan = $b } else { [void]$t.parts.Add($b) }
    $t.bucket = $t.once
}

# Where one object begins: @(ticks, Openness ticks) for Add-ObjectTime, $null when off.
function Get-ObjectTimeMark {
    if (-not [TiaBridgeTimes]::On) { return $null }
    [TiaBridgeTimes]::Flush()
    , @([TiaBridgeTimes]::Mark, [TiaBridgeTimes]::TiaTicks)
}

# One object of a part done (Mark: Get-ObjectTimeMark at its start): its time, kept among the slowest of the part. Files:
# its files, repo-relative; their sizes are read once the part is done, of the slowest only. Skipped: it kept its files.
function Add-ObjectTime($Mark, [string]$Name, [string]$Folder, [object[]]$Files, [switch]$Skipped) {
    $t = $script:ExportTimes
    if (-not $t -or -not $Mark -or -not [TiaBridgeTimes]::On) { return }
    [TiaBridgeTimes]::Flush()   # the Openness ticks up to now
    $ticks = [TiaBridgeTimes]::Mark - $Mark[0]
    $b = $t.bucket
    $b.objectTicks.Add($ticks)
    $s = $b.slowest
    if ($s.Count -ge $script:SlowestObjectCount) {
        $min = 0
        for ($i = 1; $i -lt $s.Count; $i++) { if ($s[$i].ticks -lt $s[$min].ticks) { $min = $i } }
        if ($s[$min].ticks -ge $ticks) { return }
        $s.RemoveAt($min)
    }
    [void]$s.Add(@{ name = $Name; folder = $Folder; ticks = $ticks; tiaTicks = [TiaBridgeTimes]::TiaTicks - $Mark[1]; files = @($Files | Where-Object { $_ }); skipped = [bool]$Skipped })
}

function ConvertTo-Ms([long]$Ticks) { [Math]::Round($Ticks * 1000.0 / [System.Diagnostics.Stopwatch]::Frequency, 1) }

# A bucket's steps, the longest first: name -> @{ ms; n } (n: times entered; other has none).
function Get-StepTimes($Bucket) {
    $out = [ordered]@{}
    foreach ($k in @($Bucket.steps.Keys | Sort-Object { $Bucket.steps[$_][0] } -Descending)) {
        $a = $Bucket.steps[$k]
        $out[$k] = $(if ($a[1]) { [ordered]@{ ms = ConvertTo-Ms $a[0]; n = [int]$a[1] } } else { [ordered]@{ ms = ConvertTo-Ms $a[0] } })
    }
    $out
}

function Get-TiaStepMs($Bucket) {
    [long]$n = 0
    foreach ($k in $Bucket.steps.Keys) { if ($k.StartsWith('tia_')) { $n += $Bucket.steps[$k][0] } }
    ConvertTo-Ms $n
}

# The size of files in the repo, bytes; one that is not there counts 0.
function Get-RepoFilesBytes([object[]]$Files) {
    [long]$n = 0
    foreach ($f in $Files) {
        $fi = New-Object System.IO.FileInfo (Join-Path $script:Bridge.repo $f)
        if ($fi.Exists) { $n += $fi.Length }
    }
    $n
}

function Get-BucketTimes($Bucket, [switch]$Part) {
    $r = [ordered]@{}
    if ($Part) { $r.part = $Bucket.part; if ($Bucket.device) { $r.device = $Bucket.device } }
    $r.ms = $Bucket.ms
    $r.tiaMs = Get-TiaStepMs $Bucket
    $r.steps = Get-StepTimes $Bucket
    $n = $Bucket.objectTicks.Count
    if ($n) {
        $sorted = $Bucket.objectTicks.ToArray(); [Array]::Sort($sorted)
        $r.objects = [ordered]@{ n = $n; medianMs = ConvertTo-Ms $sorted[[int][Math]::Floor(($n - 1) / 2)]
                                 p90Ms = ConvertTo-Ms $sorted[[int][Math]::Ceiling(0.9 * $n) - 1]; maxMs = ConvertTo-Ms $sorted[$n - 1] }
        $r.slowest = @(foreach ($o in @($Bucket.slowest | Sort-Object { $_.ticks } -Descending)) {
            $e = [ordered]@{ name = $o.name }
            if ($o.folder) { $e.folder = $o.folder }
            $e.ms = ConvertTo-Ms $o.ticks; $e.tiaMs = ConvertTo-Ms $o.tiaTicks
            $e.bytes = Get-RepoFilesBytes $o.files; $e.files = $o.files.Count
            if ($o.skipped) { $e.skipped = $true }
            $e
        })
    }
    $r
}

# Ends the times; returns them for the log: ms; tiaMs (in Openness); plan; parts; once (what is outside the plan and the
# parts: the session, the mirror, git, the count of unchanged files, the record, the result); stepChanges.
function Stop-ExportTimes {
    $t = $script:ExportTimes
    if (-not $t) { return $null }
    if ($t.bucket -ne $t.once) { Exit-PartTimes }
    [TiaBridgeTimes]::Flush()
    $r = [ordered]@{
        about = 'ms per step: steps named tia_* are calls into Openness, the others the bridge''s own work; a part''s steps add up to its ms. slowest: the objects of a part that took longest, with the size of their files.'
        ms = [int](ConvertTo-Ms ([TiaBridgeTimes]::Mark)); tiaMs = ConvertTo-Ms ([TiaBridgeTimes]::TiaTicks)
    }
    if ($t.plan) { $r.plan = Get-BucketTimes $t.plan }
    $r.parts = @(foreach ($b in $t.parts) { Get-BucketTimes $b -Part })
    [long]$n = 0
    foreach ($a in $t.once.steps.Values) { $n += $a[0] }
    $t.once.ms = [int](ConvertTo-Ms $n)
    $r.once = Get-BucketTimes $t.once
    $r.stepChanges = [TiaBridgeTimes]::Changes
    Stop-ExportTimesClock
    $r
}

# Off: no step counts until the next Start-ExportTimes.
function Stop-ExportTimesClock {
    [TiaBridgeTimes]::Stop()
    $script:ExportTimes = $null
}
