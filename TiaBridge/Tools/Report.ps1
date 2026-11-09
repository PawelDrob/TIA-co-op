# Tools\Report.ps1 - change_report: the change report of commits of the project repo (TiaChangeReports, the python
# of the repo's .venv). Reads git only; never touches TIA.

# TiaChangeReports sits in the tool repo next to TiaBridge; python -m TiaChangeReports runs from the tool repo root.
$script:ToolRepoRoot = [System.IO.Path]::GetFullPath((Join-Path $PSScriptRoot '..\..'))
$script:ReportsDir = 'changes\reports'
# A report over many commits of a large project takes minutes; what takes longer than this hangs.
$script:ChangeReportLimitMinutes = 30

# One argument for ProcessStartInfo.Arguments, quoted by the rules of CommandLineToArgvW (.NET Framework has no
# ArgumentList): backslashes double only before a quote or the closing quote.
function ConvertTo-ProcessArgument([string]$Arg) {
    if ($Arg -and $Arg -notmatch '[\s"]') { return $Arg }
    '"' + ($Arg -replace '(\\*)"', '$1$1\"' -replace '(\\+)$', '$1$1') + '"'
}

# Runs python -m TiaChangeReports <arguments> --json; returns its result object. Throws when it cannot run or fails.
function Invoke-ChangeReports([string[]]$Arguments) {
    $missing = Get-PythonProblem @('yaml')
    if ($missing) { throw "change_report needs python: $missing" }
    $psi = New-Object System.Diagnostics.ProcessStartInfo
    $psi.FileName = $script:PythonExe
    $psi.Arguments = (@('-X', 'utf8', '-m', 'TiaChangeReports') + $Arguments + @('--json') | ForEach-Object { ConvertTo-ProcessArgument $_ }) -join ' '
    $psi.WorkingDirectory = $script:ToolRepoRoot
    $psi.UseShellExecute = $false
    $psi.CreateNoWindow = $true
    $psi.RedirectStandardOutput = $true
    $psi.RedirectStandardError = $true
    $psi.StandardOutputEncoding = [System.Text.Encoding]::UTF8
    $psi.StandardErrorEncoding = [System.Text.Encoding]::UTF8
    $psi.EnvironmentVariables['PYTHONIOENCODING'] = 'utf-8'
    try { $p = [System.Diagnostics.Process]::Start($psi) }
    catch { throw "python could not be started: $($_.Exception.Message) $($script:PythonSetup)" }
    $r = Wait-ToolProcess $p $script:ChangeReportLimitMinutes 'python -m TiaChangeReports'
    if ($r.exitCode) { throw "python -m TiaChangeReports exited with $($r.exitCode): $($r.err.Trim())" }
    try { $r.out | ConvertFrom-Json }
    catch { throw "python -m TiaChangeReports printed no JSON: $($r.err.Trim())" }
}

# The short hash of a revision, $null when the repo has no such commit.
function Get-CommitShort([string]$Repo, [string]$Rev) {
    $r = Invoke-GitRaw $Repo @('rev-parse', '--verify', '-q', '--short', "$Rev^{commit}")
    if ($r.exitCode) { return $null }
    [string]$r.output[0]
}

# Report pages are regenerable from git and about 0.5 MB each: the project repo ignores them (decided 2026-10-28).
function Add-ReportsIgnore([string]$Repo) {
    $gi = Join-Path $Repo '.gitignore'
    if ((Test-Path -LiteralPath $gi) -and (Select-String -LiteralPath $gi -SimpleMatch 'changes/reports/' -Quiet)) { return }
    [System.IO.File]::AppendAllText($gi, "`nchanges/reports/`n", $script:Utf8NoBom)
}

# A path under the repo relative to it, any other path as it is.
function ConvertTo-RepoRelative([string]$Repo, [string]$Path) {
    $root = [System.IO.Path]::GetFullPath($Repo).TrimEnd('\') + '\'
    $full = [System.IO.Path]::GetFullPath($Path)
    if ($full.StartsWith($root, [StringComparison]::OrdinalIgnoreCase)) { return $full.Substring($root.Length) }
    $full
}

function Invoke-ChangeReportTool($a) {
    $null = Get-BridgeSession
    $repo = $script:Bridge.repo
    $rev2 = if ($a.rev2) { [string]$a.rev2 } else { 'HEAD' }
    $rev1 = if ($a.rev1) { [string]$a.rev1 } else { "$rev2~1" }

    $sha2 = Get-CommitShort $repo $rev2
    if (-not $sha2) { return New-Refusal "No commit '$rev2' in the project repo $repo." }
    $sha1 = Get-CommitShort $repo $rev1
    if (-not $sha1) {
        if (-not $a.rev1 -and (Invoke-GitRaw $repo @('rev-list', '--count', $rev2)).output[0] -eq '1') {
            return New-Refusal "The project repo has only one commit ($rev2): nothing before it to compare with. Commit the change after the export of the old state, or give rev1."
        }
        return New-Refusal "No commit '$rev1' in the project repo $repo."
    }

    # changes\reports\<commit date of rev2>_<rev2>.html; <rev1>-<rev2> when rev1 is given
    $date = [string](Invoke-GitRaw $repo @('log', '-1', '--format=%cs', $sha2)).output[0]
    $name = if ($a.rev1) { "${date}_$sha1-$sha2.html" } else { "${date}_$sha2.html" }
    $page = Join-Path $repo "$script:ReportsDir\$name"
    Add-ReportsIgnore $repo

    $cli = @('--git', $repo, $rev1, $rev2, '-o', $page)
    if ($a.title) { $cli += @('--title', [string]$a.title) }
    foreach ($b in @($a.blocks | Where-Object { $_ })) { $cli += @('--block', [string]$b) }
    if ($a.only) {
        if (@('plc', 'hmi') -notcontains [string]$a.only) { return New-Refusal "only must be plc or hmi, not '$($a.only)'." }
        $cli += @('--only', [string]$a.only)
    }
    $res = Invoke-ChangeReports $cli

    $out = @{ ok = $true; page = (ConvertTo-RepoRelative $repo $res.page); before = $res.before; after = $res.after
              blocks = @($res.blocks) }
    # the PLC tag tables, the HMI objects (screens, tag tables, ... of hmi\ and project\graphics\), files TiaChangeReports
    # could not read, and names in blocks that match nothing: only when there are
    if (@($res.plcTags | Where-Object { $_ }).Count) { $out.plcTags = @($res.plcTags) }
    if (@($res.hmi | Where-Object { $_ }).Count) { $out.hmi = @($res.hmi) }
    if ($res.skipped) { $out.skipped = @($res.skipped) }
    if ($res.otherFiles) { $out.otherFiles = @($res.otherFiles) }
    if ($res.unmatched) { $out.unmatched = $res.unmatched }
    $out
}

function Register-ReportTool {
    Register-McpTool -Name 'change_report' -Handler { param($a) Invoke-ChangeReportTool $a } -Description (
        'Change report of commits of the project repo (no TIA access): every changed block, UDT and DB before | after, LAD as ladder with the ' +
        'logic diff, SCL as a line diff, interfaces as tables; every changed PLC tag table (plcTags: tags and user constants added, removed, changed); ' +
        'on the same page every changed HMI object (screens, templates and pop-ups drawn ' +
        'before | after with their changes, tag tables and text lists with where-used, project graphics). Default: the last commit (rev2 HEAD, ' +
        'rev1 its parent); run it after save + commit. Writes changes\reports\<date>_<commit>.html (gitignored). The result lists the PLC tag tables ' +
        '(plcTags: name, state, counts, rows of tags and user constants), the HMI objects (hmi: device, kind, name, state, changes), files it ' +
        'skipped (skipped: path, reason), changed files it does not read (otherFiles: paths, the page names them too: quote them, it reads nothing of them) ' +
        'and names in blocks that match no block (unmatched), only when there are. blocks leaves the tag ' +
        'tables and the HMI part out.') -Schema @{
        type = 'object'
        properties = @{
            rev1 = @{ type = 'string'; description = 'before; default: the parent of rev2. Give it to report several commits at once' }
            rev2 = @{ type = 'string'; description = 'after; default HEAD' }
            title = @{ type = 'string'; description = 'title of the page' }
            blocks = @{ type = 'array'; items = @{ type = 'string' }; description = 'only these blocks; default: every changed one' }
            only = @{ type = 'string'; enum = @('plc', 'hmi'); description = 'only the PLC blocks and tag tables or only the HMI objects; default both' } } }
}
