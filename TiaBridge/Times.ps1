# Times.ps1 - where the time of a full_export goes (decided 2026-11-17): per part and step, and the slowest objects of a part.
# One stopwatch, its ticks given to one step at a time: a step entered inside another stops the outer one's share until it
# ends, so the steps of a part add up to the part's time. Steps named tia_* are calls into Openness; every other step is the
# bridge's own work, and other is what no step names. Off ($script:ExportTimes $null) outside a full_export: a step then
# costs one test. On, a step costs about 20 microseconds (stepChanges counts them), no call into TIA.

$script:ExportTimes = $null
$script:SlowestObjectCount = 10

function New-TimesBucket([string]$Part = '', [string]$Device = '') {
    @{ part = $Part; device = $Device; steps = (New-Object 'System.Collections.Generic.Dictionary[string,long[]]'); start = [long]0
       slowest = (New-Object System.Collections.ArrayList); objectTicks = (New-Object 'System.Collections.Generic.List[long]') }
}

# Starts the times of a full_export: from here every tick goes to a step of the export (once) until a part begins.
function Start-ExportTimes {
    $once = New-TimesBucket
    $script:ExportTimes = @{ clock = [System.Diagnostics.Stopwatch]::StartNew(); mark = [long]0; step = 'other'; tia = $false; tiaTicks = [long]0
                             changes = 0; retry = $false; once = $once; bucket = $once; plan = $null; parts = (New-Object System.Collections.ArrayList) }
}

# Gives the ticks since the last change to the step that ran, and makes Step the one that runs. Count: Step was entered (n).
function Switch-ExportStep($T, [string]$Step, [bool]$Count) {
    $now = $T.clock.ElapsedTicks
    $d = $now - $T.mark
    $T.mark = $now
    $T.changes++
    $a = $null
    if (-not $T.bucket.steps.TryGetValue($T.step, [ref]$a)) { $a = [long[]]@(0, 0); $T.bucket.steps[$T.step] = $a }
    $a[0] += $d
    if ($T.tia) { $T.tiaTicks += $d }
    $T.step = $Step
    $T.tia = $Step.StartsWith('tia_')
    if ($Count) {
        if (-not $T.bucket.steps.TryGetValue($Step, [ref]$a)) { $a = [long[]]@(0, 0); $T.bucket.steps[$Step] = $a }
        $a[1]++
    }
}

# Enters Step; returns the step that ran, for Exit-ExportStep (in a finally). The Openness export of an object after TIA
# refused its first one (a SimaticML export after a refused SD export) counts as tia_export_retry.
function Enter-ExportStep([string]$Step) {
    $t = $script:ExportTimes
    if (-not $t) { return $null }
    if ($t.retry -and $Step.StartsWith('tia_export_')) { $Step = 'tia_export_retry' }
    $was = $t.step
    Switch-ExportStep $t $Step $true
    $was
}

function Exit-ExportStep([string]$Was) {
    $t = $script:ExportTimes
    if (-not $t -or -not $Was) { return }
    Switch-ExportStep $t $Was $false
}

# The exports between Enter-ExportRetry and Exit-ExportRetry are second ones, after a refused first one.
function Enter-ExportRetry { if ($script:ExportTimes) { $script:ExportTimes.retry = $true } }
function Exit-ExportRetry { if ($script:ExportTimes) { $script:ExportTimes.retry = $false } }

# The plan (what TIA says of the objects, before any part) or a part: its steps from here to Exit-PartTimes.
function Enter-PartTimes([string]$Part, [string]$Device = '') {
    $t = $script:ExportTimes
    if (-not $t) { return }
    Switch-ExportStep $t 'other' $false
    $b = New-TimesBucket $Part $Device
    $b.start = $t.mark
    $t.bucket = $b
}

# Ms: the part's time as the part measured it (its line); the plan gives none and takes the span of its steps.
function Exit-PartTimes([int]$Ms = -1, [switch]$Plan) {
    $t = $script:ExportTimes
    if (-not $t -or $t.bucket -eq $t.once) { return }
    Switch-ExportStep $t 'other' $false
    $b = $t.bucket
    $b.ms = $(if ($Ms -ge 0) { $Ms } else { [int](($t.mark - $b.start) * 1000 / [System.Diagnostics.Stopwatch]::Frequency) })
    if ($Plan) { $t.plan = $b } else { [void]$t.parts.Add($b) }
    $t.bucket = $t.once
    $t.step = 'other'; $t.tia = $false
}

# Where one object begins: @(ticks, Openness ticks) for Add-ObjectTime, $null when off.
function Get-ObjectTimeMark {
    $t = $script:ExportTimes
    if (-not $t) { return $null }
    , @($t.clock.ElapsedTicks, $t.tiaTicks)
}

# One object of a part done (Mark: Get-ObjectTimeMark at its start): its time, kept among the slowest of the part. Files:
# its files, repo-relative; their sizes are read once the part is done, of the slowest only. Skipped: it kept its files.
function Add-ObjectTime($Mark, [string]$Name, [string]$Folder, [object[]]$Files, [switch]$Skipped) {
    $t = $script:ExportTimes
    if (-not $t -or -not $Mark) { return }
    Switch-ExportStep $t $t.step $false   # the Openness ticks up to now
    $ticks = $t.mark - $Mark[0]
    $b = $t.bucket
    $b.objectTicks.Add($ticks)
    $s = $b.slowest
    if ($s.Count -ge $script:SlowestObjectCount) {
        $min = 0
        for ($i = 1; $i -lt $s.Count; $i++) { if ($s[$i].ticks -lt $s[$min].ticks) { $min = $i } }
        if ($s[$min].ticks -ge $ticks) { return }
        $s.RemoveAt($min)
    }
    [void]$s.Add(@{ name = $Name; folder = $Folder; ticks = $ticks; tiaTicks = $t.tiaTicks - $Mark[1]; files = @($Files | Where-Object { $_ }); skipped = [bool]$Skipped })
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

# Ends the times; returns them for the log: ms; tiaMs (in Openness); once (what is outside the plan and the parts: the
# session, the mirror, git, the count of unchanged files, the record, the result); plan; parts; stepChanges.
function Stop-ExportTimes {
    $t = $script:ExportTimes
    if (-not $t) { return $null }
    if ($t.bucket -ne $t.once) { Exit-PartTimes }
    Switch-ExportStep $t 'other' $false
    $r = [ordered]@{
        about = 'ms per step: steps named tia_* are calls into Openness, the others the bridge''s own work; a part''s steps add up to its ms. slowest: the objects of a part that took longest, with the size of their files.'
        ms = [int](ConvertTo-Ms $t.mark); tiaMs = ConvertTo-Ms $t.tiaTicks
    }
    if ($t.plan) { $r.plan = Get-BucketTimes $t.plan }
    $r.parts = @(foreach ($b in $t.parts) { Get-BucketTimes $b -Part })
    [long]$n = 0
    foreach ($a in $t.once.steps.Values) { $n += $a[0] }
    $t.once.ms = [int](ConvertTo-Ms $n)
    $r.once = Get-BucketTimes $t.once
    $r.stepChanges = $t.changes
    $script:ExportTimes = $null
    $r
}
