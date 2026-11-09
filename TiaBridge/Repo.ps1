# Repo.ps1 - bridge settings, one git repo per TIA project, tool logs, archive rotation; the checks for git on PATH
# and for the python of the repo's .venv.

# also here: tests load this file alone
. (Join-Path $PSScriptRoot 'Guides.ps1')

$script:Utf8NoBom = New-Object System.Text.UTF8Encoding $false

# The longest project, archive or library path TIA takes (an archive without its .zap20).
$script:TiaPathLimit = 143

function Write-TextFile([string]$Path, [string]$Text) {
    $dir = Split-Path -Parent $Path
    if ($dir -and -not (Test-Path -LiteralPath $dir)) { [void][System.IO.Directory]::CreateDirectory($dir) }
    [System.IO.File]::WriteAllText($Path, $Text, $script:Utf8NoBom)
}

# For a file that a stop half way must not damage: the old one stands until the new one is whole. The temporary file sits
# beside it, as a replace within one folder is atomic; a process killed before the replace leaves it there, ignored by git
# (SessionTempIgnore), and the next process has its own.
function Write-TextFileAtomic([string]$Path, [string]$Text) {
    $temp = "$Path.$PID.tmp"
    try { Write-TextFile $temp $Text }
    catch { Remove-Item -LiteralPath $temp -Force -ErrorAction SilentlyContinue; throw }
    try { Move-FileOver $temp $Path }
    catch {
        if (Test-Path -LiteralPath $Path) { Remove-Item -LiteralPath $temp -Force -ErrorAction SilentlyContinue; throw }
        # ReplaceFile can fail with the old file gone (ERROR_UNABLE_TO_MOVE_REPLACEMENT): the new one, whole, is the only copy
        # left. If this move fails too it stays where it is, and Restore-SessionWrites refuses on it.
        Move-FileOver $temp $Path
    }
}

function Move-FileOver([string]$From, [string]$To) {
    if (Test-Path -LiteralPath $To) { [System.IO.File]::Replace($From, $To, [NullString]::Value) }
    else { [System.IO.File]::Move($From, $To) }
}

function Get-BridgeSettings([string]$Path) {
    $s = [ordered]@{
        projectsRoot = Join-Path $env:USERPROFILE 'TIA-Projects'
        tiaRoot = 'C:\Program Files\Siemens\Automation\Portal V20'
        archivesKept = 10
        maxResponseChars = 20000
        useTransactions = $true
    }
    if ($Path -and (Test-Path $Path)) {
        $f = Get-Content $Path -Raw | ConvertFrom-Json
        foreach ($p in $f.PSObject.Properties) { $s[$p.Name] = $p.Value }
    }
    $s
}

# An object's name as a file or folder name. Windows forbids nine characters and control characters, drops a dot or a space
# at the end (.NET also a no-break space and U+0085), and keeps device names for itself (NUL cannot be a folder; NUL.txt is NUL on older Windows). The form is not
# one to one: Ns:Block and Ns_Block get one file, which is why export refuses them (Get-ExportCollisions, Tools\Objects.ps1)
# and import goes by the name a document declares. TiaHmiGenerator\hmipreview\model.py folder_name is the same mapping.
function ConvertTo-SafeFileName([string]$Name) {
    if (-not $Name) { return '_' }
    $s = $Name -replace '[\\/:*?"<>|\x00-\x1F]', '_' -replace '[. \u00A0\u0085]+$', '_'
    $s -replace '^(con|prn|aux|nul|com[0-9\u00B9\u00B2\u00B3]|lpt[0-9\u00B9\u00B2\u00B3]|conin\$|conout\$)(\.|$)', '${1}_$2'
}

# Name as Names holds it: a tool's argument reaches a device or a library without case (Tia.ps1), and its folder goes by the
# exact name, so plc_1 is not taken for another device than PLC_1. As it is when it fits none, or two of different case:
# the tool refuses those.
function Resolve-ListedName([string]$Name, [string[]]$Names) {
    if (@($Names | Where-Object { [string]::Equals($_, $Name, [StringComparison]::Ordinal) }).Count) { return $Name }
    $hits = @($Names | Where-Object { [string]::Equals($_, $Name, [StringComparison]::OrdinalIgnoreCase) })
    if (-not $hits.Count -or @($hits | Where-Object { -not [string]::Equals($_, $hits[0], [StringComparison]::Ordinal) }).Count) { return $Name }
    [string]$hits[0]
}

# The others of Names with the file-safe name of Name. Ordinal, as what NTFS folds is equal in lower case; -eq and -ceq go by
# culture and take spellings for one that NTFS keeps apart.
function Get-FolderSharers([string]$Name, [string[]]$Names) {
    $Name = Resolve-ListedName $Name $Names
    $key = (ConvertTo-SafeFileName $Name).ToLowerInvariant()
    @($Names | Where-Object { -not [string]::Equals($_, $Name, [StringComparison]::Ordinal) -and [string]::Equals((ConvertTo-SafeFileName $_).ToLowerInvariant(), $key, [StringComparison]::Ordinal) })
}

# The folder of a device or a global library: its file-safe name, or when another of Names has that name too, that name and
# a mark of its own exact name, the same at every call and in any order. All of them get the mark: no folder is then
# mistaken for the device its plain name would be (the HMI tools map a device name to its plain folder and find none).
function Get-UniqueFolderName([string]$Name, [string[]]$Names) {
    $Name = Resolve-ListedName $Name $Names
    $safe = ConvertTo-SafeFileName $Name
    if (-not @(Get-FolderSharers $Name $Names).Count) { return $safe }
    $sha = [System.Security.Cryptography.SHA256]::Create()
    try { $hash = $sha.ComputeHash([System.Text.Encoding]::UTF8.GetBytes($Name)) } finally { $sha.Dispose() }
    "$safe~$(-join @($hash[0..3] | ForEach-Object { $_.ToString('x2') }))"
}

# Where an export waits next to Base until it replaces it. Never a fixed name: Foo.partial or Foo.old can be the folder of
# another object, and a fixed name would delete it. The mirror leaves *.partial alone, so one left by a killed bridge stays
# there; $script:WorkPathIgnore keeps it out of the project repo, as the next step of an export is git add -A.
function New-ExportWorkPath([string]$Base) { "$Base.$([guid]::NewGuid().ToString('N').Substring(0, 8)).partial" }

# The repo folder of a project: the folder Windows makes of its name (it drops a dot or space at the end). Not the mapping
# of objects above: what is no folder name ('.', '..', a device name) must reach Resolve-RepoFolder and be refused.
function Get-ProjectFolderName([string]$ProjectName) { ($ProjectName -replace '[\\/:*?"<>|]', '_').TrimEnd('. ') }

# A repo or export folder named in a tool argument -> @{ path } or @{ refused = why }. Only a plain folder name directly
# below the projects root passes: the bridge runs git init and git add -A in a new repo, so '..' would commit the
# whole user profile. Windows drops a trailing dot or space, so such a name would be another folder than the one named.
function Resolve-RepoFolder([string]$Root, [string]$Name) {
    if (-not $Name -or $Name.IndexOfAny([System.IO.Path]::GetInvalidFileNameChars()) -ge 0 -or $Name -match '[. ]$') {
        return @{ refused = "repo must be a plain folder name under the projects root, not a path (no . or .., no \ / : * ? `" < > |, no dot or space at the end): '$Name'." }
    }
    if ($Name -match '^(con|prn|aux|nul|com\d|lpt\d)(\.|$)') { return @{ refused = "repo '$Name' is a Windows device name, not a folder name." } }
    if ($Name -eq '_bridge') { return @{ refused = "repo '_bridge' is the bridge's own folder under the projects root." } }
    $below = [System.IO.Path]::GetFullPath($Root).TrimEnd('\') + '\'
    $full = [System.IO.Path]::GetFullPath((Join-Path $Root $Name))
    if (-not $full.StartsWith($below, [StringComparison]::OrdinalIgnoreCase)) { return @{ refused = "repo '$Name' resolves to $full, outside the projects root $below." } }
    @{ path = $full }
}

# Whether Path is the top of a git repo, as git knows one: a .git folder or file, or bare: a HEAD file with objects and
# refs folders (a --separate-git-dir folder has that shape too).
function Test-GitRepoFolder([string]$Path) {
    [System.IO.Directory]::Exists("$Path\.git") -or [System.IO.File]::Exists("$Path\.git") -or
        ([System.IO.File]::Exists("$Path\HEAD") -and [System.IO.Directory]::Exists("$Path\objects") -and [System.IO.Directory]::Exists("$Path\refs"))
}

# The git repos in Dir, Dir itself too, full paths. A repo's own .git folder answers as well.
function Get-GitRepoFolders([string]$Dir) {
    if (Test-GitRepoFolder $Dir) { $Dir }
    Get-ChildItem -LiteralPath $Dir -Directory -Recurse -Force | Where-Object { Test-GitRepoFolder $_.FullName } | ForEach-Object { $_.FullName }
}

# What TIA writes anew on every export of an object that did not change [PROBE] (test project, 2026-11-05: 44 files per
# full_export): the export time in the head of SimaticML (DocumentInfo/Created); the CreationDate on the root of the
# settings XML (alarm classes, system diagnostics), also inside their .dat (a zip of that XML), whose zip entry time
# moves too; in an .xlsx (a zip) its entry times and the Ids of its relationships. Nothing else differed. Text is
# compared as Latin-1, one character per byte, so equal text is equal bytes.
$script:Latin1 = [System.Text.Encoding]::GetEncoding(28591)
$script:XmlHead = '\A(?:\xEF\xBB\xBF)?<\?xml[^>]*\?>\s*'
$script:ExportTime = '\d{4}-\d\d-\d\dT\d\d:\d\d:\d\d(?:\.\d+)?Z'
$script:SimaticMlCreated = New-Object regex "($script:XmlHead<Document>\s*<Engineering\b[^>]*/>\s*<DocumentInfo>\s*<Created>)$script:ExportTime(</Created>)"
$script:RootCreationDate = New-Object regex "($script:XmlHead<[A-Za-z_][\w.:-]*\b[^<>]*?\sCreationDate=`")$script:ExportTime(`")"

# Text of an XML export without its export time: the one in the head of SimaticML, or on the root element.
function Remove-ExportTime([string]$Text) {
    $script:RootCreationDate.Replace($script:SimaticMlCreated.Replace($Text, '$1$2'), '$1$2')
}

# The files of a zip -> name -> Latin-1 text, names case-sensitive as in the zip. A name held twice throws.
function Read-ZipParts([string]$Path) {
    Add-Type -AssemblyName System.IO.Compression.FileSystem
    $parts = New-Object 'System.Collections.Generic.Dictionary[string,string]' ([StringComparer]::Ordinal)
    $zip = [System.IO.Compression.ZipFile]::OpenRead($Path)
    try {
        foreach ($e in $zip.Entries) {
            $ms = New-Object System.IO.MemoryStream
            $s = $e.Open()
            try { $s.CopyTo($ms) } finally { $s.Dispose() }
            $parts.Add($e.FullName, $script:Latin1.GetString($ms.ToArray()))
        }
    }
    finally { $zip.Dispose() }
    , $parts
}

# The Ids of the relationships of an Open XML zip numbered in the order its .rels lists them, there and in the namespaced
# attributes (r:id) of the part that .rels belongs to (xl/_rels/workbook.xml.rels -> xl/workbook.xml; _rels/.rels: the
# package). Equal afterwards: the same relationships, in the same order, to the same targets, used in the same places.
function Set-RelationshipNumbers($Parts) {
    foreach ($rels in @($Parts.Keys | Where-Object { $_ -cmatch '(^|/)_rels/[^/]*\.rels$' })) {
        $owner = $rels -creplace '(^|/)_rels/([^/]*)\.rels$', '$1$2'
        $ids = @([regex]::Matches($Parts[$rels], '<Relationship\b[^>]*?\sId="([^"]*)"') | ForEach-Object { $_.Groups[1].Value })
        for ($i = 0; $i -lt $ids.Count; $i++) {
            $id = [regex]::Escape($ids[$i]); $n = "$([char]1)$i"
            $Parts[$rels] = [regex]::Replace($Parts[$rels], "(<Relationship\b[^>]*?\sId=`")$id(`")", "`${1}$n`$2")
            if ($owner -and $Parts.ContainsKey($owner)) { $Parts[$owner] = [regex]::Replace($Parts[$owner], "(\s[\w.-]+:[\w.-]+=`")$id(`")", "`${1}$n`$2") }
        }
    }
}

# Whether two zips hold the same files, each the same after Normalize (text -> text) or as it is.
function Test-SameZipParts([string]$A, [string]$B, [scriptblock]$Normalize) {
    $pa = Read-ZipParts $A; $pb = Read-ZipParts $B
    if ($pa.Count -ne $pb.Count) { return $false }
    & $Normalize $pa; & $Normalize $pb
    foreach ($k in $pa.Keys) { if (-not $pb.ContainsKey($k) -or -not [string]::Equals($pa[$k], $pb[$k], [StringComparison]::Ordinal)) { return $false } }
    $true
}

# Whether the export New differs from the file Old in the repo at most in what TIA writes anew per export (above), by the
# extension of Old: .xml, .dat, .xlsx; any other file only when equal. A file that cannot be read differs.
function Test-OnlyExportTimeDiffers([string]$New, [string]$Old) {
    try {
        if (-not [System.IO.File]::Exists($New) -or -not [System.IO.File]::Exists($Old)) { return $false }
        $a = $script:Latin1.GetString([System.IO.File]::ReadAllBytes($New))
        $b = $script:Latin1.GetString([System.IO.File]::ReadAllBytes($Old))
        if ([string]::Equals($a, $b, [StringComparison]::Ordinal)) { return $true }
        switch ([System.IO.Path]::GetExtension($Old).ToLowerInvariant()) {
            '.xml' { return [string]::Equals((Remove-ExportTime $a), (Remove-ExportTime $b), [StringComparison]::Ordinal) }
            '.dat' { return Test-SameZipParts $New $Old { param($p) foreach ($k in @($p.Keys)) { $p[$k] = Remove-ExportTime $p[$k] } } }
            '.xlsx' { return Test-SameZipParts $New $Old { param($p) Set-RelationshipNumbers $p } }
        }
        $false
    }
    catch { $false }
}

# The files of the repo an export left as they were (full paths), for the count export and full_export give (unchanged):
# each clears it at its start. Byte-equal exports count too: their file stays as well.
$script:UnchangedExports = New-Object 'System.Collections.Generic.HashSet[string]' ([StringComparer]::OrdinalIgnoreCase)

# How many of Files (paths) an export left as they were since the last Clear.
function Get-UnchangedExportCount([string[]]$Files) {
    @($Files | Where-Object { $_ -and $script:UnchangedExports.Contains([System.IO.Path]::GetFullPath($_)) } | Sort-Object -Unique).Count
}

# Before an export folder (Partial) replaces Destination: each of its files that differs from the one at its place there
# only in what TIA writes anew per export takes that file's bytes, so git sees no change in it.
function Restore-UnchangedExports([string]$Partial, [string]$Destination) {
    if (-not [System.IO.Directory]::Exists($Destination)) { return }
    $Partial = [System.IO.Path]::GetFullPath($Partial).TrimEnd('\')
    foreach ($f in @(Get-ChildItem -LiteralPath $Partial -File -Recurse -Force)) {
        $old = Join-Path $Destination $f.FullName.Substring($Partial.Length + 1)
        if (Test-OnlyExportTimeDiffers $f.FullName $old) {
            [System.IO.File]::Copy($old, $f.FullName, $true)
            [void]$script:UnchangedExports.Add([System.IO.Path]::GetFullPath($old))
        }
    }
}

# Puts a finished export (<target>.partial, a file or a folder) in place of Destination. Another process may hold the
# old file open for a moment (2026-10-06: Move-Item -Force failed with "Cannot create a file when that file
# already exists" while a preview server watched the folder), so a locked destination is retried for RetryMs. If it
# stays locked, the partial is removed, the old file or folder stays as it was, and the error names the destination.
# A folder holding a git repo (Test-GitRepoFolder) is not replaced, the same way: the repo's history is nowhere else.
# A file that differs from the old one only in the export time keeps the old one (Test-OnlyExportTimeDiffers), in a
# folder too: an export of an object nobody changed changes nothing in the repo.
function Move-ExportIntoPlace([string]$Partial, [string]$Destination, [int]$RetryMs = 2000) {
    $isDir = [System.IO.Directory]::Exists($Partial)
    if ($isDir -and [System.IO.Directory]::Exists($Destination)) {
        $git = Get-GitRepoFolders $Destination | Select-Object -First 1
        if ($git) {
            Remove-Item -LiteralPath $Partial -Recurse -Force -ErrorAction SilentlyContinue
            throw (New-Object System.IO.IOException "The export did not replace '$Destination': it holds a git repo ($git), which the replacement would destroy. The previous version is kept. Move the repo out of the folder and export again.")
        }
    }
    if ($isDir) { Restore-UnchangedExports $Partial $Destination }
    elseif (Test-OnlyExportTimeDiffers $Partial $Destination) {
        Remove-Item -LiteralPath $Partial -Force -ErrorAction SilentlyContinue
        [void]$script:UnchangedExports.Add([System.IO.Path]::GetFullPath($Destination))
        return
    }
    $deadline = [DateTime]::UtcNow.AddMilliseconds($RetryMs)
    while ($true) {
        try {
            if ($isDir) {
                $old = New-ExportWorkPath $Destination
                $hadOld = [System.IO.Directory]::Exists($Destination)
                if ($hadOld) { [System.IO.Directory]::Move($Destination, $old) }
                try { [System.IO.Directory]::Move($Partial, $Destination) }
                catch { if ($hadOld) { [System.IO.Directory]::Move($old, $Destination) }; throw }
                if ($hadOld) { try { [System.IO.Directory]::Delete($old, $true) } catch { Write-BridgeLog "Could not remove $old`: $($_.Exception.Message)" } }
            } elseif ([System.IO.File]::Exists($Destination)) {
                [System.IO.File]::Replace($Partial, $Destination, [NullString]::Value)   # $null would arrive as ""
            } else {
                [System.IO.File]::Move($Partial, $Destination)
            }
            return
        } catch {
            $ex = $_.Exception
            while ($ex -is [System.Management.Automation.MethodInvocationException] -and $ex.InnerException) { $ex = $ex.InnerException }
            $transient = $ex -is [System.IO.IOException] -or $ex -is [System.UnauthorizedAccessException]
            if ($transient -and [DateTime]::UtcNow -lt $deadline) { Start-Sleep -Milliseconds 100; continue }
            if ($isDir) { Remove-Item -LiteralPath $Partial -Recurse -Force -ErrorAction SilentlyContinue }
            else { Remove-Item -LiteralPath $Partial -Force -ErrorAction SilentlyContinue }
            throw (New-Object System.IO.IOException ("The export could not replace '$Destination' (another process holds it open?); " +
                "the previous version is kept: $($ex.Message)"), $ex)
        }
    }
}

# $null when git is on PATH, else what to do. The bridge keeps the PATH it started with.
function Get-GitProblem {
    if (Get-Command git -CommandType Application -ErrorAction SilentlyContinue) { return $null }
    'git not found on PATH. Install Git for Windows (git-scm.com), then restart Claude Code so the bridge starts with the new PATH.'
}

# A parent (a hook, another git-aware tool) can leave these in the environment, and git prefers them to -C: a commit of
# the bridge would land in the parent's repo. Nothing here wants them, so they leave the whole process, children too.
function Clear-GitContext {
    foreach ($name in 'GIT_DIR', 'GIT_INDEX_FILE', 'GIT_WORK_TREE', 'GIT_PREFIX', 'GIT_COMMON_DIR') {
        [Environment]::SetEnvironmentVariable($name, $null)
    }
}

function Invoke-GitRaw([string]$Repo, [string[]]$GitArgs) {
    # Without git, & git under ErrorActionPreference Continue only writes an error record (into $out through 2>&1)
    # and leaves $LASTEXITCODE as it was ($null in a new process): it would pass as success.
    $missing = Get-GitProblem
    if ($missing) { throw $missing }
    Clear-GitContext
    # git writes warnings (line endings) to stderr; under ErrorActionPreference Stop, PowerShell 5.1 turns each
    # stderr line of a native command into a terminating error. Only the exit code decides.
    $saved = $ErrorActionPreference
    $ErrorActionPreference = 'Continue'
    try { $out = @(& git -C $Repo @GitArgs 2>&1 | ForEach-Object { "$_" }) }
    finally { $ErrorActionPreference = $saved }
    @{ exitCode = $LASTEXITCODE; output = $out }
}

function Invoke-Git([string]$Repo, [string[]]$GitArgs) {
    # The initial commit must not fail on a guest without a git identity.
    $id = @()
    if ((Invoke-GitRaw $Repo @('config', 'user.email')).exitCode) { $id = @('-c', 'user.name=TiaBridge', '-c', 'user.email=tiabridge@localhost') }
    $r = Invoke-GitRaw $Repo ($id + $GitArgs)
    if ($r.exitCode) { throw "git $($GitArgs -join ' ') failed in $Repo (exit $($r.exitCode)): $($r.output -join ' ')" }
}

# ------------------------------------------------------------------ python (change_report, HMI import validator)

# The python the tools run: the .venv of this tool repo by absolute path, never python from PATH. The setup step the
# messages name. The bridge asks again on every call until the answer is good, so no restart after uv sync.
$script:PythonRoot = [System.IO.Path]::GetFullPath((Join-Path $PSScriptRoot '..'))
$script:PythonExe = Join-Path $script:PythonRoot '.venv\Scripts\python.exe'
$script:PythonSetup = "Setup: run uv sync in $($script:PythonRoot) (uv: https://docs.astral.sh/uv/)."
$script:PythonMinimum = [version]'3.12'
$script:PythonPackages = @{ yaml = 'PyYAML' }
# Prints the version, then the modules named in argv that cannot be imported. An old Python prints its version
# before it fails on importlib.util.
$script:PythonProbe = "import sys; print('%d.%d.%d' % tuple(sys.version_info[:3])); import importlib.util as u; print(' '.join(m for m in sys.argv[1:] if u.find_spec(m) is None))"
$script:PythonReady = @{}

# What the probe's answer says is wrong, $null when nothing is.
function Get-PythonProbeProblem([int]$ExitCode, [string]$Out, [string]$Err) {
    $lines = @(([string]$Out).Trim() -split '\r?\n')
    if ($lines[0] -notmatch '^\d+\.\d+\.\d+$') {
        return "python did not run the check (exit $ExitCode): $(([string]$Err).Trim())"
    }
    $v = [version]$lines[0]
    if ($v -lt $script:PythonMinimum) { return "python is $v; the tools need $($script:PythonMinimum) or later." }
    if ($ExitCode) { return "python $v failed the check (exit $ExitCode): $(([string]$Err).Trim())" }
    $missing = @(if ($lines.Count -gt 1) { $lines[1].Trim() -split ' ' | Where-Object { $_ } })
    if ($missing.Count) {
        $names = @($missing | ForEach-Object { if ($script:PythonPackages[$_]) { $script:PythonPackages[$_] } else { $_ } })
        return "python $v lacks $($names -join ', ')."
    }
    $null
}

# $null when the python the tools run is recent enough and imports Modules, else what is wrong and the setup step.
# A good answer is kept for the bridge process.
function Get-PythonProblem([string[]]$Modules = @()) {
    $key = (@($Modules) | Sort-Object) -join ','
    if ($script:PythonReady[$key]) { return $null }
    $psi = New-Object System.Diagnostics.ProcessStartInfo
    $psi.FileName = $script:PythonExe
    $psi.Arguments = (@('-X', 'utf8', '-c', "`"$($script:PythonProbe)`"") + @($Modules)) -join ' '
    $psi.UseShellExecute = $false
    $psi.CreateNoWindow = $true
    $psi.RedirectStandardOutput = $true
    $psi.RedirectStandardError = $true
    try { $p = [System.Diagnostics.Process]::Start($psi) }
    catch { return "$($script:PythonExe) not found. $($script:PythonSetup)" }
    $err = $p.StandardError.ReadToEndAsync()
    $out = $p.StandardOutput.ReadToEnd()
    if (-not $p.WaitForExit(30000)) {
        try { $p.Kill() } catch { }
        return "python did not answer within 30 s. $($script:PythonSetup)"
    }
    $problem = Get-PythonProbeProblem $p.ExitCode $out $err.Result
    if ($problem) { return "$problem $($script:PythonSetup)" }
    $script:PythonReady[$key] = $true
    $null
}

# Ends a process and the children it started (git under TiaChangeReports).
function Stop-ProcessTree($Process) {
    $saved = $ErrorActionPreference
    $ErrorActionPreference = 'Continue'
    try { $null = & taskkill.exe /PID $Process.Id /T /F 2>&1 } catch { } finally { $ErrorActionPreference = $saved }
    if (-not $Process.WaitForExit(5000)) { try { $Process.Kill() } catch { } }
}

# The output of a process started with redirected stdout and stderr -> @{ exitCode; out; err }. The bridge answers one
# call at a time, so a python that hangs would hold it for good: past LimitMinutes the process is ended and this throws.
# What: the command, for the message. Both streams are read in the background, or a full pipe would hang the process.
function Wait-ToolProcess($Process, [double]$LimitMinutes, [string]$What) {
    $out = $Process.StandardOutput.ReadToEndAsync()
    $err = $Process.StandardError.ReadToEndAsync()
    if (-not $Process.WaitForExit([int]($LimitMinutes * 60000))) {
        Stop-ProcessTree $Process
        throw "$What did not finish within $LimitMinutes minutes, so the bridge ended it. Run it by hand to see where it hangs."
    }
    # a child that outlives the process can hold the pipes open: nothing more comes that the result needs
    if (-not $out.Wait(10000) -or -not $err.Wait(10000)) { throw "$What ended, but a process it started still holds its output open." }
    @{ exitCode = $Process.ExitCode; out = $out.Result; err = $err.Result }
}

function Test-GitHasCommit([string]$Repo) {
    (Test-Path (Join-Path $Repo '.git')) -and -not (Invoke-GitRaw $Repo @('rev-parse', '--verify', '-q', 'HEAD')).exitCode
}

# docs\ is an OKF v0.2 bundle (rules: tools\okf\README.md of this repo): project.md (the notes connect points to), index.md, log.md.
# {0} project name, {1} the name escaped for a YAML double-quoted value, {2} now with offset, {3} today.
$script:ProjectMdStub = @'
---
type: Project
title: "{1}"
description: "Notes for agents working on the TIA project {1}, with its current state, backlog and decisions."
tags: [tia-portal]
generated: {{ by: process:tiabridge, at: {2} }}
---

# {0}

Notes for agents working on this TIA project. Read at the start of every session; keep it current.

## Current state

## Backlog

## Decisions
'@

$script:DocsIndexStub = @'
---
okf_version: "0.2"
---

# Projects

* [{0}](project.md) - Notes for agents working on the TIA project {0}, with its current state, backlog and decisions.
'@

$script:DocsLogStub = @'
# Log

## {3}
* **Initialization**: Repo created by TiaBridge for the TIA project {0}.
'@

# The shape New-ExportWorkPath gives, 8 hex digits: not a real object's X.partial, nor its X.partial.s7dcl.
$script:WorkPathIgnore = '*.[0-9a-f][0-9a-f][0-9a-f][0-9a-f][0-9a-f][0-9a-f][0-9a-f][0-9a-f].partial'

# What Write-TextFileAtomic leaves of the session file when killed before its replace.
$script:SessionTempIgnore = '.tiabridge-session.json.*.tmp'

$script:RepoGitignore = @"
archives/
*.zap20
.obsidian/
.tiabridge-session.json
$script:SessionTempIgnore
changes/reports/
$script:WorkPathIgnore
"@

# Writes the docs\ stubs that are missing; never overwrites.
function Initialize-ProjectDocs([string]$Repo, [string]$ProjectName, [datetime]$At = (Get-Date)) {
    $f = @($ProjectName, ($ProjectName -replace '\\', '\\' -replace '"', '\"'), $At.ToString('yyyy-MM-ddTHH:mm:sszzz'), $At.ToString('yyyy-MM-dd'))
    foreach ($s in @(@('project.md', $script:ProjectMdStub), @('index.md', $script:DocsIndexStub), @('log.md', $script:DocsLogStub))) {
        $p = Join-Path $Repo "docs\$($s[0])"
        if (-not (Test-Path $p)) { Write-TextFile $p (($s[1] -f $f) -replace '\r', '') }
    }
}

# What connect and background_open tell a session about the project's standards.
$script:StandardsUse = "This project's rules for what you write. Before you edit, read those that fit the work; say so if you cannot read one. Follow them in everything you write or change, and run any checklist they hold before import. Leave code you are not changing as it is, and tell the user where it breaks them. TIA's limits come first: if a guide and a standard conflict, follow the guide and tell the user."

# The standards entry of a tool's result, $null while the repo's standards\ holds no file. Files by path in the repo.
function Get-StandardsResult([string]$Repo) {
    $dir = Join-Path $Repo 'standards'
    if (-not (Test-Path -LiteralPath $dir -PathType Container)) { return $null }
    # FullName, as the files' own: a projects root as written may hold .. or a slash
    $prefix = (Get-Item -LiteralPath $Repo).FullName.TrimEnd('\').Length + 1
    $files = @(Get-ChildItem -LiteralPath $dir -Recurse -File -Force | ForEach-Object { $_.FullName.Substring($prefix) } | Sort-Object)
    if (-not $files.Count) { return $null }
    @{ files = $files; use = $script:StandardsUse }
}

# The settings' standardsTemplate into a new repo's standards\, folders kept; a file that stands there stays. Returns a note for
# the result when it cannot, $null otherwise: a template that fails stops no session.
function Copy-StandardsTemplate([string]$Template, [string]$Standards) {
    if (-not $Template) { return $null }
    if (-not (Test-Path -LiteralPath $Template -PathType Container)) { return "standardsTemplate $Template is no folder here: nothing was copied into $Standards." }
    try {
        $source = (Get-Item -LiteralPath $Template).FullName.TrimEnd('\')
        foreach ($f in @(Get-ChildItem -LiteralPath $source -Recurse -File -Force)) {
            $target = Join-Path $Standards $f.FullName.Substring($source.Length + 1)
            if (Test-Path -LiteralPath $target) { continue }
            [void][System.IO.Directory]::CreateDirectory((Split-Path -Parent $target))
            Copy-Item -LiteralPath $f.FullName -Destination $target
        }
        $null
    }
    catch { "standardsTemplate $Template was not copied whole into ${Standards}: $($_.Exception.Message)" }
}

# The hmiTypeIdentifier value for tiabridge.json: identifiers read now, else the ones of the last connect.
function Merge-HmiTypeIdentifier($Old, [string[]]$OldDevices, [string[]]$Devices, [System.Collections.IDictionary]$Read) {
    $prev = @{}
    if ($Old -is [string]) { if (@($OldDevices).Count -eq 1) { $prev[$OldDevices[0]] = $Old } }
    elseif ($null -ne $Old) { foreach ($p in $Old.PSObject.Properties) { $prev[$p.Name] = [string]$p.Value } }
    $map = [ordered]@{}
    foreach ($d in $Devices) {
        $id = $(if ($Read.Contains($d) -and $Read[$d]) { [string]$Read[$d] } else { $prev[$d] })
        if ($id) { $map[$d] = $id }
    }
    if (@($Devices).Count -eq 1) { if ($map.Count) { return @($map.Values)[0] } else { return $null } }
    if ($map.Count) { return $map }
    $null
}

# tiabridge.json of a repo folder, $null without one. It is UTF-8: read as ANSI, a path with a non-ASCII character
# would differ from itself and the repo would seem to belong to another path.
function Read-RepoConfig([string]$Repo) {
    $f = Join-Path $Repo 'tiabridge.json'
    if (-not (Test-Path -LiteralPath $f)) { return $null }
    Get-Content -LiteralPath $f -Raw -Encoding UTF8 | ConvertFrom-Json
}

# The path a repo stands for, for an export-only session: its project's (connect, write mode), else the source an
# export-only session recorded. $null when it records neither. The project's path decides: an archive exported into
# that repo earlier stays another path.
function Get-RepoRecordedPath($Config) {
    if (-not $Config) { return $null }
    if ($Config.projectPath) { return [string]$Config.projectPath }
    if ($Config.lastBackground) { return [string]$Config.lastBackground.source }
    $null
}

# The repo folders below Root whose tiabridge.json records this project path. Recorded: by Get-RepoRecordedPath, git
# repos only (a plain export folder records its source too, and is no repo to work in).
function Find-ReposOfPath([string]$Root, [string]$ProjectPath, [switch]$Recorded) {
    if (-not (Test-Path -LiteralPath $Root)) { return }
    foreach ($d in @(Get-ChildItem -LiteralPath $Root -Directory | Sort-Object Name)) {
        $cfg = $null
        try { $cfg = Read-RepoConfig $d.FullName } catch { continue }
        if (-not $cfg) { continue }
        if ($Recorded) {
            if ((Get-RepoRecordedPath $cfg) -eq $ProjectPath -and (Test-Path -LiteralPath (Join-Path $d.FullName '.git'))) { $d.Name }
        }
        elseif ($cfg.projectPath -eq $ProjectPath) { $d.Name }
    }
}

function Get-RepoOwnerRefusal([string]$Repo, [string]$Owner, [string]$ProjectPath, [string[]]$Others = @()) {
    "The repo $Repo belongs to the project at $Owner, and this project is at ${ProjectPath}: exports and commits of the two would mix. " +
        'Nothing was changed. Ask the user which it is, then call this tool again: the same project, moved (moved: true keeps the repo and records the new path), ' +
        "or a different project (repo: `"<other name>`" gives it its own repo)." +
        $(if (@($Others).Count) { " Repos that record this path: $($Others -join ', ')." } else { '' })
}

function Get-ExportRepoRefusal([string]$Repo, [string]$Recorded, [string]$Source, [string[]]$Others = @()) {
    "The repo $Repo records $Recorded, and this export-only session opens a copy of ${Source}: an export committed there would read as a change to that project. " +
        "Nothing was changed. Call this tool again with repo: `"<other name>`", a repo of its own for this source. If the project itself was moved, connect with moved: true records the new path." +
        $(if (@($Others).Count) { " Repos that record this path: $($Others -join ', ')." } else { '' })
}

# The repo folder of a session on the project file at ProjectPath (connect, background_open write=true), before TIA is
# touched -> @{ repoName } ('' = the default, the project name), with found = $true when it was found by the path; or
# @{ refused }. A repo belongs to one path: one that records another path is refused unless Moved. Without RepoName,
# the one repo that records this path is the project's repo: the user chose it at an earlier connect.
# ExportOnly: ProjectPath is the source of an export-only session, compared with Get-RepoRecordedPath.
function Resolve-ProjectRepo([string]$Root, [string]$ProjectName, [string]$ProjectPath, [string]$RepoName = '', [switch]$Moved, [switch]$ExportOnly) {
    $folder = Resolve-RepoFolder $Root $(if ($RepoName) { $RepoName } else { (Get-ProjectFolderName $ProjectName) })
    if ($folder.refused) { return @{ refused = $folder.refused } }
    $cfg = Read-RepoConfig $folder.path
    $owner = $(if ($ExportOnly) { Get-RepoRecordedPath $cfg } elseif ($cfg) { $cfg.projectPath } else { $null })
    if ($Moved -or $owner -eq $ProjectPath) { return @{ repoName = $RepoName } }
    # a project whose repo is not named after it (an archive opened for changes, repo given at an earlier connect) has that repo,
    # also with no repo of its name
    $others = @(if (-not $RepoName) { Find-ReposOfPath $Root $ProjectPath -Recorded:$ExportOnly })
    if ($others.Count -eq 1) { return @{ repoName = $others[0]; found = $true; owner = $owner } }
    if (-not $owner) { return @{ repoName = $RepoName } }
    @{ refused = $(if ($ExportOnly) { Get-ExportRepoRefusal $folder.path $owner $ProjectPath $others } else { Get-RepoOwnerRefusal $folder.path $owner $ProjectPath $others }) }
}

# Returns @{ repo; created; pathChanged; oldPath }. A repo belongs to one project path: a session on another project
# file is refused, whatever its name, unless Moved says it is the same project (Resolve-ProjectRepo says so before TIA
# is touched; this is the guard for a project whose name is not its file's).
# HmiTypeIdentifiers: HMI device name -> TypeIdentifier ($null where it could not be read). tiabridge.json gets
# hmiTypeIdentifier: a string for one HMI device, an object device -> identifier for several; a device whose
# identifier could not be read keeps the value of the last connect. Keys the bridge does not write (startScreen,
# hmiDevice: the device the HMI preview uses when there are several) stay.
# RepoName: the repo folder, default the project name. BackgroundSource: the .ap20/.zap20 a background session opened
# a copy of; projectPath and lastConnect then stay those of the last connect, lastBackground records the source. Such
# a session is refused on a repo that records another path (Get-RepoRecordedPath), Plain excepted; Resolve-ProjectRepo
# says so before TIA is touched, this is the guard for an archive whose file name is not its project's.
# BackgroundWrite: that session works on the project file itself, so the repo belongs to its path as under connect.
# Plain: a plain export folder (background_open plain=true): tiabridge.json only, no skeleton, docs stubs, .gitignore
# or git; created then means no tiabridge.json was there.
# StandardsTemplate: the settings' folder for standards\ of a new repo, in its first commit (Copy-StandardsTemplate).
function Initialize-ProjectRepo([string]$Root, [string]$ProjectName, [string]$ProjectPath, [string[]]$PlcDevices, [string[]]$HmiDevices,
                                [System.Collections.IDictionary]$HmiTypeIdentifiers = @{}, [string]$RepoName = '', [string]$BackgroundSource = '', [string]$StandardsTemplate = '',
                                [switch]$Plain, [switch]$BackgroundWrite, [switch]$Moved) {
    if ($Plain -and -not $RepoName) { throw 'A plain export folder needs its folder name (RepoName); the project name is no fallback.' }
    # a project name is no argument: its folder stays the one Windows makes of it (without trailing dots or spaces)
    $folder = Resolve-RepoFolder $Root $(if ($RepoName) { $RepoName } else { (Get-ProjectFolderName $ProjectName) })
    if ($folder.refused) { throw $folder.refused }
    $repo = $folder.path
    $cfgPath = Join-Path $repo 'tiabridge.json'
    $old = Read-RepoConfig $repo
    $oldPath = $(if ($old) { $old.projectPath } else { $null })
    $ownsPath = (-not $BackgroundSource) -or $BackgroundWrite
    $otherPath = [bool]($ownsPath -and $oldPath -and $oldPath -ne $ProjectPath)
    if ($otherPath -and -not $Moved) { throw (Get-RepoOwnerRefusal $repo $oldPath $ProjectPath) }
    if ($BackgroundSource -and -not $ownsPath -and -not $Plain) {
        $recorded = Get-RepoRecordedPath $old
        if ($recorded -and $recorded -ne $BackgroundSource) {
            $others = @(if (-not $RepoName) { Find-ReposOfPath $Root $BackgroundSource -Recorded })
            throw (Get-ExportRepoRefusal $repo $recorded $BackgroundSource $others)
        }
    }

    if (-not $Plain) {
        foreach ($d in 'plc', 'hmi', 'library', 'gen', 'logs', 'archives', 'standards') {
            New-Item -ItemType Directory -Force -Path (Join-Path $repo $d) | Out-Null
        }
    }
    $cfg = [ordered]@{
        projectName = $ProjectName
        projectPath = $ProjectPath
        plcDevices = @($PlcDevices)
        hmiDevices = @($HmiDevices)
        lastConnect = (Get-Date).ToString('yyyy-MM-ddTHH:mm:ss')
    }
    if ($BackgroundSource) {
        if (-not $ownsPath) { $cfg.projectPath = $oldPath }
        $cfg.lastConnect = $(if ($old) { $old.lastConnect } else { $null })
        $cfg.lastBackground = [ordered]@{ source = $BackgroundSource; at = (Get-Date).ToString('yyyy-MM-ddTHH:mm:ss') }
    }
    $typeIds = Merge-HmiTypeIdentifier -Old $(if ($old) { $old.hmiTypeIdentifier } else { $null }) -OldDevices $(if ($old) { @($old.hmiDevices) } else { @() }) `
        -Devices @($HmiDevices) -Read $HmiTypeIdentifiers
    if ($null -ne $typeIds) { $cfg.hmiTypeIdentifier = $typeIds }
    if ($old) {
        foreach ($p in $old.PSObject.Properties) { if (-not $cfg.Contains($p.Name) -and $p.Name -ne 'hmiTypeIdentifier') { $cfg[$p.Name] = $p.Value } }
    }
    Write-TextFile $cfgPath (ConvertTo-Json $cfg -Depth 5)
    if ($Plain) { return @{ repo = $repo; created = (-not $old); pathChanged = $false; oldPath = $oldPath; plain = $true } }

    Initialize-ProjectDocs $repo $ProjectName
    # created: no initial commit yet, also when an earlier connect stopped before it
    $created = -not (Test-GitHasCommit $repo)
    $standardsNote = $null
    if ($created) {
        $standardsNote = Copy-StandardsTemplate $StandardsTemplate (Join-Path $repo 'standards')
        if (-not (Test-Path (Join-Path $repo '.gitignore'))) { Write-TextFile (Join-Path $repo '.gitignore') $script:RepoGitignore }
        foreach ($d in 'plc', 'hmi', 'library', 'gen', 'logs') { Write-TextFile (Join-Path $repo "$d\.gitkeep") '' }
        if (-not (Test-Path (Join-Path $repo '.git'))) { Invoke-Git $repo @('init', '-q') }
        Invoke-Git $repo @('add', '-A')
        Invoke-Git $repo @('commit', '-q', '-m', "TiaBridge: repo for TIA project $ProjectName")
    }
    # repos made before these ignore lines existed (the session file: 2026-10-06) get them
    $gi = Join-Path $repo '.gitignore'
    foreach ($line in '.tiabridge-session.json', $script:SessionTempIgnore, $script:WorkPathIgnore) {
        if ((Test-Path -LiteralPath $gi) -and -not (Select-String -LiteralPath $gi -SimpleMatch $line -Quiet)) {
            [System.IO.File]::AppendAllText($gi, "`n$line`n", $script:Utf8NoBom)
        }
    }
    @{ repo = $repo; created = $created; pathChanged = $otherPath; oldPath = $oldPath; standardsNote = $standardsNote }
}

# Full, untruncated result -> logs\<yyyyMMdd_HHmmss>_<tool>.json; returns the path relative to the repo.
function Write-ToolLog([string]$Repo, [string]$Tool, $Result, [datetime]$At = (Get-Date)) {
    $base = "logs\$($At.ToString('yyyyMMdd_HHmmss'))_$Tool"
    $rel = "$base.json"
    $n = 2
    while (Test-Path (Join-Path $Repo $rel)) { $rel = "${base}_$n.json"; $n++ }
    Write-TextFile (Join-Path $Repo $rel) (ConvertTo-Json $Result -Depth 64)
    $rel
}

# Import paths (relative to the repo or absolute) -> one entry per object:
# @{ file; name; format = 's7dcl'|'xml'; folder = 'A/B' (TIA folder mirrored under KindDir, else ''); missing }
function Resolve-ImportFiles([string]$Repo, [string]$KindDir, [string[]]$Paths) {
    $seen = @{}
    $kindRoot = [System.IO.Path]::GetFullPath((Join-Path $Repo $KindDir)).TrimEnd('\') + '\'
    foreach ($p in $Paths) {
        $full = if ([System.IO.Path]::IsPathRooted($p)) { $p } else { Join-Path $Repo $p }
        $full = [System.IO.Path]::GetFullPath($full)
        $ext = [System.IO.Path]::GetExtension($full).ToLowerInvariant()
        $format = 'xml'
        if ($ext -eq '.s7dcl' -or $ext -eq '.s7res') { $format = 's7dcl'; $full = [System.IO.Path]::ChangeExtension($full, '.s7dcl') }
        if ($seen.ContainsKey($full.ToLowerInvariant())) { continue }
        $seen[$full.ToLowerInvariant()] = $true
        $folder = ''
        $dir = [System.IO.Path]::GetDirectoryName($full).TrimEnd('\') + '\'
        if ($dir.StartsWith($kindRoot, [StringComparison]::OrdinalIgnoreCase)) { $folder = $dir.Substring($kindRoot.Length).TrimEnd('\').Replace('\', '/') }
        @{ file = $full; name = [System.IO.Path]::GetFileNameWithoutExtension($full); format = $format; folder = $folder; missing = -not (Test-Path -LiteralPath $full) }
    }
}

# Writes a .s7dcl with a lone LF as CRLF, every other byte as it was; the note for the result, $null when nothing changed.
# TIA takes the 8 spaces of the export off a body line only after a CRLF: a line after a lone LF keeps them, and the
# export adds 8 again, on every round trip (docs/agent/s7dcl-format.md section 10, measured 2026-11-02).
function Repair-DocumentLineEnds([string]$Path) {
    $bytes = [System.IO.File]::ReadAllBytes($Path)
    # UTF-16: its bytes are not its characters. Latin-1 maps every byte to one character and back.
    if ($bytes.Length -ge 2 -and (($bytes[0] -eq 0xFF -and $bytes[1] -eq 0xFE) -or ($bytes[0] -eq 0xFE -and $bytes[1] -eq 0xFF))) { return $null }
    $latin = [System.Text.Encoding]::GetEncoding(28591)
    $text = $latin.GetString($bytes)
    if ($text -notmatch '(?<!\r)\n') { return $null }
    [System.IO.File]::WriteAllBytes($Path, $latin.GetBytes(($text -replace '(?<!\r)\n', "`r`n")))
    "Line ends of $([System.IO.Path]::GetFileName($Path)) written as CRLF before the import: with LF, TIA indents an SCL body 8 deeper on every round trip ($(Get-GuidePath 's7dcl-format.md') section 10)."
}

# What may stand between the words of a .s7dcl's head. The gap is atomic: once read it is not given back. Otherwise a comment
# header with no keyword after it backtracks exponentially (\s and // both take the CR of a line end: 24 lines 21 s,
# doubling per line) and the import hangs in its plan.
$script:S7dclGap = '(?>(?:\s|//[^\n]*|\(\*.*?\*\)|/\*.*?\*/|\{(?>(?:[^"''}]|"[^"]*"|''[^''\r\n]*''|'')*)\})*)'
$script:S7dclName = '(?:"(?<quoted>(?:[^"]|"")*)"|(?<plain>[^\s":{;]+))'
$script:S7dclKeywords = 'FUNCTION_BLOCK|FUNCTION|ORGANIZATION_BLOCK|DATA_BLOCK|TYPE'
# Keywords in any case, as TIA is not known to refuse another case: read as a declaration, a lower-case keyword meets the
# guards under its object's name, not under the file's. Used with CultureInvariant, as "I" has another lower case by culture.
$script:S7dclHead = "(?s)\A$script:S7dclGap(?i:(?<keyword>$script:S7dclKeywords))\b"

function Get-S7dclName([System.Text.RegularExpressions.Match]$M) {
    if ($M.Groups['quoted'].Success) { $M.Groups['quoted'].Value -replace '""', '"' } else { $M.Groups['plain'].Value }
}

# A SimaticML read with no resolver: a document does not reach out of its file.
function Read-DocumentXml([string]$Path) {
    $doc = New-Object System.Xml.XmlDocument
    $doc.XmlResolver = $null
    $doc.Load($Path)
    $doc
}

# The objects of a SimaticML, under its root.
$script:DocumentObjectsXPath = "/Document/*[starts-with(name(), 'SW.') or starts-with(name(), 'Hmi.')]"

# The object name a document declares, '' when none can be read: of a .s7dcl the name after the block keyword, quoted or
# not, past a pragma block between them (docs/agent/s7dcl-format.md section 3: TYPE / { S7_Safety := "True" } /
# "Ns:Data" : STRUCT), of a SimaticML the block's Name. Anchored at the start of the text: a line of a pragma's
# value that starts with a keyword is no declaration. A file name cannot hold every object name, the declaration can.
function Get-DocumentDeclaredName([string]$Path) {
    try {
        if ([System.IO.Path]::GetExtension($Path) -eq '.s7dcl') {
            $m = [regex]::Match([System.IO.File]::ReadAllText($Path), "$script:S7dclHead$script:S7dclGap$script:S7dclName", 'CultureInvariant')
            if (-not $m.Success) { return '' }
            return Get-S7dclName $m
        }
        $node = (Read-DocumentXml $Path).SelectSingleNode("$script:DocumentObjectsXPath/AttributeList/Name")
        if ($node) { [string]$node.InnerText } else { '' }
    } catch { '' }
}

# What a document holds, for a new library type and the kind it belongs to: 'type' (a PLC data type), 'block' (an FB or
# FC), 'OB', 'DB', of a SimaticML also 'tags' (a PLC tag table) and 'HMI', or '' when it cannot be read. By the same anchored
# reading as Get-DocumentDeclaredName, as a word further down may name anything.
function Get-DocumentObjectClass([string]$Path) {
    try {
        if ([System.IO.Path]::GetExtension($Path) -eq '.s7dcl') {
            $m = [regex]::Match([System.IO.File]::ReadAllText($Path), $script:S7dclHead, 'CultureInvariant')
            if (-not $m.Success) { return '' }
            return $(switch ($m.Groups['keyword'].Value) { 'TYPE' { 'type' } 'ORGANIZATION_BLOCK' { 'OB' } 'DATA_BLOCK' { 'DB' } default { 'block' } })
        }
        $node = (Read-DocumentXml $Path).SelectSingleNode($script:DocumentObjectsXPath)
        if (-not $node) { return '' }
        $(switch -Regex ($node.Name) { '^Hmi\.' { 'HMI'; break } '^SW\.Tags\.' { 'tags'; break } '^SW\.Types\.' { 'type'; break } '^SW\.Blocks\.(FB|FC)$' { 'block'; break } '^SW\.Blocks\.OB$' { 'OB'; break } 'DB$' { 'DB'; break } default { '' } })
    } catch { '' }
}

# What a document declares beside its first object: the name, of a .s7dcl the keyword when no name can be read; '' for
# nothing or a document it cannot read. An export writes one object per document, and the guards go by that one. In a
# .s7dcl only the END of the first object opens the search, as its members may be called Type or Function; a TYPE may also
# list a second type after its first, which ends with its END_STRUCT or, outside a STRUCT, a semicolon. Comments, pragmas,
# texts and quoted names are read as one token each, so what they say counts for nothing. Each of them succeeds once begun,
# a text or quoted name ending with its line (REGION it's is no text) and the others with the document when never closed:
# a token that failed would be rescanned from its next opening, per line.
function Get-DocumentSecondDeclaration([string]$Path) {
    try {
        if ([System.IO.Path]::GetExtension($Path) -eq '.s7dcl') {
            $text = [System.IO.File]::ReadAllText($Path)
            $first = [regex]::Match($text, $script:S7dclHead, 'CultureInvariant')
            if (-not $first.Success) { return '' }
            $end = "END_$($first.Groups['keyword'].Value)"
            $listsTypes = $first.Groups['keyword'].Value -ieq 'TYPE'
            $token = [regex]::new(('(?s)//[^\n]*|\(\*.*?(?:\*\)|\z)|/\*.*?(?:\*/|\z)|\{(?>(?:[^"''}]|"[^"]*(?:"|\z)|''[^''\r\n]*''|'')*)(?:\}|\z)' +
                                   '|"[^"\r\n]*(?:"|(?=[\r\n])|\z)|''(?>(?:[^''$\r\n]|\$[^\r\n]?)*)(?:''|(?=[\r\n])|\z)' +
                                   "|(?<word>;)|\b(?i:(?<word>(?:END_)?(?:$script:S7dclKeywords|STRUCT)))\b"), 'CultureInvariant')
            $nameAt = [regex]::new("(?s)\G$script:S7dclGap;?$script:S7dclGap$script:S7dclName", 'CultureInvariant')
            $depth = 0; $ended = $false
            for ($m = $token.Match($text, $first.Index + $first.Length); $m.Success; $m = $m.NextMatch()) {
                $word = $m.Groups['word'].Value
                if (-not $word) { continue }
                if ($word -ieq 'STRUCT') { $depth++; continue }
                if ($word -ieq 'END_STRUCT') { $depth-- }
                if ($word -in ';', 'END_STRUCT') {
                    if (-not $listsTypes -or $ended -or $depth -ne 0) { continue }
                    $next = $nameAt.Match($text, $m.Index + $m.Length)
                    if ($next.Success -and (Get-S7dclName $next) -ine $end) { return Get-S7dclName $next }
                    continue
                }
                if (-not $ended) { $ended = $word -ieq $end; continue }
                if ($word -like 'END_*') { continue }
                $next = $nameAt.Match($text, $m.Index + $m.Length)
                return $(if ($next.Success) { Get-S7dclName $next } else { $word })
            }
            return ''
        }
        $objects = (Read-DocumentXml $Path).SelectNodes($script:DocumentObjectsXPath)
        if ($objects.Count -lt 2) { return '' }
        $node = $objects[1].SelectSingleNode('AttributeList/Name')
        if ($node) { [string]$node.InnerText } else { [string]$objects[1].Name }
    } catch { '' }
}

# yyyyMMddHHmmss from an archive name: tia-co-op-<project>-<yyyy-MM-dd>_<HHmmss>[-<reason>], tia-coop-... until
# 2026-11-01 (the prefix plays no part), or <yyyyMMdd_HHmmss>_<reason> (before 2026-10-06). $null for any other file.
function Get-ArchiveStamp([string]$Name) {
    if ($Name -match '-(\d{4})-(\d{2})-(\d{2})_(\d{6})(-|\.zap20$)') { return "$($Matches[1])$($Matches[2])$($Matches[3])$($Matches[4])" }
    if ($Name -match '^(\d{8})_(\d{6})_') { return "$($Matches[1])$($Matches[2])" }
    $null
}

# Keeps the newest N archives by the time in their names; files without one (archives the user put there) stay.
# Returns the removed paths.
function Remove-OldArchives([string]$Dir, [int]$Keep) {
    $all = @(Get-ChildItem $Dir -Filter *.zap20 -File -ErrorAction SilentlyContinue |
        Where-Object { Get-ArchiveStamp $_.Name } | Sort-Object { Get-ArchiveStamp $_.Name } -Descending)
    # at least the newest: the session archive just made, which the archive gate counts
    $old = @($all | Select-Object -Skip ([Math]::Max(1, $Keep)))
    foreach ($f in $old) { Remove-Item $f.FullName -Force }
    @($old | ForEach-Object FullName)
}
