# Tools\LibraryChange.ps1 - the reviewed library change (decided 2026-10-06).
# A change to one library type reaches every type containing it. Each of them is reviewed against its released
# version and approved per type before it is released, so the user sees the dependencies and nothing is released
# that does not match the intent of the change. One change = <repo>\library\changes\<id>.json (the record) and
# <id>.md (the report, one checkbox per type; the ticks there are the approvals).

# ------------------------------------------------------------------ rules (pure)

# Level of every type of the change: the changed type 0, any other 1 + the highest level of the change types it
# contains, so a level is released only after the levels below it.
function Get-ImpactLevels([hashtable]$DependsOn, [string]$Root, [string[]]$Dependents) {
    $set = @{}; $set[$Root] = $true
    foreach ($d in $Dependents) { if ($d) { $set[$d] = $true } }
    $level = @{}
    foreach ($n in (Get-ReleaseOrder -DependsOn $DependsOn -Names @($set.Keys))) {
        if ($n -eq $Root) { $level[$n] = 0; continue }
        $inner = @(@($DependsOn[$n]) | Where-Object { $set[$_] -and $level.ContainsKey($_) } | ForEach-Object { $level[$_] })
        $level[$n] = if ($inner.Count) { 1 + ($inner | Measure-Object -Maximum).Maximum } else { 1 }
    }
    $level
}

function Get-TypeKindLabel([string]$Class) {
    switch -Regex ($Class) {
        'Faceplate' { 'faceplate'; break }
        'CodeBlock' { 'code block'; break }
        'PlcType' { 'data type'; break }
        default { $Class }
    }
}

function New-ChangeId([string]$Root, [datetime]$At) { "$($At.ToString('yyyy-MM-dd_HHmm'))-$(ConvertTo-SafeFileName $Root)" -replace '\s', '_' }

# Types: @{ name; class; folder; released; inWork } for the root and every dependent.
function New-ChangeRecord([string]$Root, [string]$From, [string]$To, [object[]]$Types, [hashtable]$Levels, [datetime]$At) {
    $t = [ordered]@{}
    foreach ($x in $Types) {
        $t[$x.name] = [ordered]@{ level = [int]$Levels[$x.name]; kind = (Get-TypeKindLabel $x.class); folder = [string]$x.folder
                                 released = [string]$x.released; inWork = [string]$x.inWork
                                 inWorkBy = $(if ($x.name -eq $Root) { 'change' } elseif ($x.inWork) { 'before' } else { '' })
                                 review = $null; approved = $false; releasedAs = '' }
    }
    [ordered]@{ id = (New-ChangeId $Root $At); root = $Root; from = $From; to = $To; started = $At.ToString('yyyy-MM-dd HH:mm'); status = 'open'; types = $t }
}

# The one line of a type in the report. The changed type has no checkbox: library_release_type releases it.
function Format-ChangeTypeLine([string]$Name, $T, [bool]$Updated = $false) {
    $parts = @("``$Name``", $T.kind)
    $stale = @($T.stale | Where-Object { $_ })
    if ($T.releasedAs) { $parts += "released $($T.releasedAs)$(if ($T.releasedOutside) { ' in TIA' })" }
    elseif ($T.inWork) {
        $by = switch ($T.inWorkBy) { 'tia' { ' (by TIA)' } 'bridge' { ' (by the bridge)' } 'before' { ' (in work before this change)' } default { '' } }
        $parts += "$($T.released) -> $($T.inWork) in work$by"
    } elseif ($T.leftBehind -and -not $stale.Count) { $parts += "$($T.released), **LEFT ON OLD VERSIONS**, no instance in this project, on a type left on old versions itself: see below" }
    elseif ($stale.Count -and $T.noInstance) { $parts += "$($T.released), **LEFT ON OLD VERSIONS**, no instance in this project, so no update moved it: uses $($stale -join '; ') - see below" }
    elseif ($stale.Count -and $Updated) { $parts += "$($T.released), not put in work: **NOT USING THE DEFAULT VERSION** of $($stale -join '; ') - needs a new version" }
    # no update on record: nothing has left it out yet
    elseif ($stale.Count) { $parts += "$($T.released), not in work yet: **NOT USING THE DEFAULT VERSION** of $($stale -join '; ')" }
    elseif ($Updated) { $parts += "$($T.released), not put in work: keeps its version" }
    else { $parts += "$($T.released), not in work yet" }
    if ($T.review) {
        $r = $T.review
        switch ($r.verdict) {
            'reference-only' { $parts += "reference only: $(@($r.references) -join '; ')" }
            'unchanged' { $parts += 'no difference to the released version' }
            'flagged' {
                $why = @()
                $count = if ($r.contentCount) { [int]$r.contentCount } else { @($r.content).Count }
                if ($r.kind -eq 'setpoint-only') { $why += "only S7_Setpoint attributes, $count lines ($($r.diff))" }
                elseif ($count) { $why += "$count other lines differ ($($r.diff))" }
                if (@($r.unexpected).Count) { $why += "references outside the change: $(@($r.unexpected) -join '; ')" }
                $s = "**FLAGGED**: $($why -join '; ')"
                if (@($r.references).Count) { $s += "; references: $(@($r.references) -join '; ')" }
                $parts += $s
            }
            default { $parts += "not compared: $($r.note)" }
        }
        if ($r.format -eq 'xml') { $parts += 'compared as SimaticML (unverified)' }
    }
    $line = $parts -join ' - '
    if ($T.inWorkBy -eq 'change') { return "- $line (the change)" }
    if ($T.noInstance -or $T.leftBehind) { return "- $line" }   # nothing to approve
    $box = if ($T.approved -or $T.releasedAs) { 'x' } else { ' ' }
    "- [$box] $line"
}

# Whether what is not in work now was left out, not waiting: an update has run since the last release, or the change has ended. Test-ChangeDone reads
# updated itself: a release by name can be the last step of a change.
function Test-ChangeUpdatedSinceRelease($Record) {
    [bool]($Record.updated -and (-not $Record.releasedSinceUpdate -or $Record.status -in 'done', 'left-behind'))
}

function Format-ChangeReport($Record) {
    $sb = New-Object System.Text.StringBuilder
    [void]$sb.AppendLine($(if ($Record.root) { "# Library change: $($Record.root) $($Record.from) -> $($Record.to)" } else { '# Library change: types left on old versions' }))
    [void]$sb.AppendLine('')
    $n = @($Record.types.Keys).Count - $(if ($Record.root) { 1 } else { 0 })
    [void]$sb.AppendLine("Started $($Record.started). Status: $($Record.status). $n $(if ($Record.root) { 'dependent ' })library types.")
    if ($Record.updateOutstanding) { [void]$sb.AppendLine('The project is not updated to the released types: library_update_usages.') }
    if ($Record.staleUnread) { [void]$sb.AppendLine("Which types are left on old versions was not read, so this stays open: $($Record.staleUnread).") }
    [void]$sb.AppendLine('')
    [void]$sb.AppendLine('Tick a box to approve that type for release; the agent can tick them for you (library_approve). library_release_chain')
    [void]$sb.AppendLine('releases approved types only, contained types first; a type stays in work until it is approved, and so do the types')
    [void]$sb.AppendLine('containing it. A review compares the version in work with the released one: "reference only" means it differs')
    [void]$sb.AppendLine('only in the versions of the change types it uses; anything else is FLAGGED with its diff file.')
    $levels = @($Record.types.Values | ForEach-Object { [int]$_.level } | Sort-Object -Unique)
    foreach ($l in $levels) {
        [void]$sb.AppendLine('')
        [void]$sb.AppendLine($(if ($l -eq 0) { '## Level 0: the changed type' } else { "## Level $l" }))
        [void]$sb.AppendLine('')
        foreach ($name in @($Record.types.Keys | Where-Object { [int]$Record.types[$_].level -eq $l } | Sort-Object)) {
            [void]$sb.AppendLine((Format-ChangeTypeLine $name $Record.types[$name] (Test-ChangeUpdatedSinceRelease $Record)))
        }
    }
    $left = @($Record.leftBehind | Where-Object { $_ })
    if ($left.Count) {
        [void]$sb.AppendLine('')
        [void]$sb.AppendLine('## Left on old versions')
        [void]$sb.AppendLine('')
        $undecided = "They have no instance in this project, so no update moves them. $(Format-NotDecided)"
        $unasked = @(Get-LeftBehindUnasked $Record $left)
        [void]$sb.AppendLine($(if ($unasked.Count) { "Answered $($Record.leftBehindAnswer) before these came, so not decided yet: $(Format-NamesCapped $unasked). $undecided" }
            else { switch ([string]$Record.leftBehindAnswer) {
                'no' { 'The user chose to leave these. They have no instance in this project, so no update moves them.' }
                'yes' { 'The user chose to bring these up to date, and these are not: library_left_behind.' }
                default { $undecided }
            } }))
        [void]$sb.AppendLine('')
        foreach ($t in $left) {
            $why = $(if ($Record.leftBehindRefused -and $Record.leftBehindRefused[$t.type]) { " - refused: $($Record.leftBehindRefused[$t.type])" })
            [void]$sb.AppendLine("- ``$($t.type)`` $($t.version): uses $(@($t.uses) -join '; ')$why")
        }
    }
    if ($Record.temporaryFolder) {
        [void]$sb.AppendLine('')
        [void]$sb.AppendLine("Temporary folder: $($Record.temporaryFolder). Folders made for this work: $(Format-FoldersMade $Record). TIA removes the instances in them at an update once they are released; delete_folder takes what stands empty.")
    }
    if ($Record.foldersUnread) {
        [void]$sb.AppendLine('')
        [void]$sb.AppendLine("Whether the folders made for this work still stand was not read, so they stay named: $($Record.foldersUnread).")
    }
    $sb.ToString()
}

# Report text -> @{ type = ticked } for every checkbox line.
function Read-ReportApprovals([string]$Text) {
    $a = @{}
    foreach ($line in ($Text -split "`r?`n")) {
        if ($line -match '^\s*- \[([ xX])\] `([^`]+)`') { $a[$Matches[2]] = ($Matches[1] -ne ' ') }
    }
    $a
}

# .libint text -> @{ type = version } of its DependsOn list.
function Read-LibintDependsOn([string]$Text) {
    $d = @{}; $name = $null
    foreach ($line in ($Text -split "`r?`n")) {
        # YAML quotes a name with a colon: - TypeName: 'Lib:ClearDb' (2026-10-06)
        if ($line -match '^\s*- TypeName:\s*(.+?)\s*$') { $name = $Matches[1] -replace "^'(.*)'$", '$1' -replace "''", "'"; continue }
        if ($name -and $line -match '^\s*VersionNumber:\s*(\S+)') { $d[$name] = $Matches[1]; $name = $null }
    }
    $d
}

# SimaticML numbers its elements anew and stamps the export time on every export: both are left out, or two
# exports of the same content differ in hundreds of lines (2026-10-06, BaseDriveRead 1424 lines).
function Get-DocumentLines([string]$Path) {
    if (-not (Test-Path -LiteralPath $Path)) { return @() }
    $xml = $Path -like '*.xml'
    @((Get-Content -LiteralPath $Path -Encoding UTF8) | ForEach-Object {
        $l = ([string]$_).TrimStart([char]0xFEFF).TrimEnd()
        if ($xml) { if ($l -match '^\s*<Created>') { return }; $l = $l -replace ' ID="[0-9A-Fa-f]+"', '' }
        $l
    })
}

# Diff lines that are only S7_Setpoint attributes, or the pragma braces and S7_MLC lines rewritten around them.
function Test-SetpointOnly([string[]]$Content) {
    $texts = @($Content | ForEach-Object { ($_ -replace '^\S+ [+-]\s*', '').Trim() })
    $texts.Count -and -not @($texts | Where-Object {
        $_ -notmatch '^(\{ ?)?S7_Setpoint := "(True|False)";?( ?\})?$' -and $_ -notmatch '^[{}]$' -and $_ -notmatch '^(\{ )?S7_MLC := "MLC_\w+";?( \})?$' }).Count -and
        @($texts | Where-Object { $_ -match 'S7_Setpoint' }).Count
}

# Released export folder against the in-work export folder of one type (same format on both sides).
# The intended difference is the DependsOn version of a change type; any other difference is flagged.
# Returns @{ verdict (unchanged|reference-only|flagged); references; unexpected; content (diff lines) }.
function Compare-TypeDocuments([string]$ReleasedDir, [string]$WorkDir, [string[]]$ChangeTypes) {
    $libint = { param($dir) $f = @(Get-ChildItem -LiteralPath $dir -Filter *.libint -File -ErrorAction SilentlyContinue)
                if ($f.Count) { Read-LibintDependsOn (Get-Content -LiteralPath $f[0].FullName -Raw -Encoding UTF8) } else { @{} } }
    $old = & $libint $ReleasedDir; $new = & $libint $WorkDir
    $references = @(); $unexpected = @()
    foreach ($n in @(@($old.Keys) + @($new.Keys) | Sort-Object -Unique)) {
        if ($old[$n] -eq $new[$n]) { continue }
        $s = "$n $(if ($old[$n]) { $old[$n] } else { '(none)' }) -> $(if ($new[$n]) { $new[$n] } else { '(none)' })"
        if ($ChangeTypes -contains $n) { $references += $s } else { $unexpected += $s }
    }
    $content = New-Object System.Collections.ArrayList
    $files = @(@(Get-ChildItem -LiteralPath $ReleasedDir -File -ErrorAction SilentlyContinue) + @(Get-ChildItem -LiteralPath $WorkDir -File -ErrorAction SilentlyContinue) |
        Where-Object { $_.Extension -notin '.libinfo', '.libint' } | ForEach-Object { $_.Name } | Sort-Object -Unique)
    foreach ($f in $files) {
        $a = @(Get-DocumentLines (Join-Path $ReleasedDir $f)); $b = @(Get-DocumentLines (Join-Path $WorkDir $f))
        if (-not $a.Count -or -not $b.Count) {
            foreach ($l in $a) { [void]$content.Add("$f - $l") }
            foreach ($l in $b) { [void]$content.Add("$f + $l") }
            continue
        }
        foreach ($d in @(Compare-Object -ReferenceObject $a -DifferenceObject $b -SyncWindow ([Math]::Max($a.Count, $b.Count)) -CaseSensitive)) {
            [void]$content.Add("$f $(if ($d.SideIndicator -eq '=>') { '+' } else { '-' }) $($d.InputObject)")
        }
    }
    $verdict = if ($content.Count -or $unexpected.Count) { 'flagged' } elseif ($references.Count) { 'reference-only' } else { 'unchanged' }
    # S7_Setpoint appears in the export of a version in work and not in the released one: named, still flagged
    $kind = if ($verdict -eq 'flagged' -and -not $unexpected.Count -and (Test-SetpointOnly @($content))) { 'setpoint-only' } else { '' }
    @{ verdict = $verdict; kind = $kind; references = $references; unexpected = $unexpected; content = @($content) }
}

# Which approved types can be released now, in order. A type waits while a change type it contains is in work and
# not released in this run (not approved, or itself waiting): releasing it would build on a version not released.
# Returns @{ order; waiting (@{ type; for }); notApproved }.
function Get-ApprovedReleaseSet($Record, [hashtable]$DependsOn) {
    $types = $Record.types
    $candidates = @($types.Keys | Where-Object { $types[$_].inWorkBy -ne 'change' -and $types[$_].inWork -and -not $types[$_].releasedAs })
    $approved = @($candidates | Where-Object { $types[$_].approved })
    $notApproved = @($candidates | Where-Object { -not $types[$_].approved } | Sort-Object)
    $ok = @{}; $waiting = New-Object System.Collections.ArrayList
    foreach ($n in (Get-ReleaseOrder -DependsOn $DependsOn -Names $approved)) {
        $for = @(@($DependsOn[$n]) | Where-Object { $types.Contains($_) -and $types[$_].inWork -and -not $types[$_].releasedAs -and -not $ok[$_] } | Sort-Object)
        if ($for.Count) { [void]$waiting.Add(@{ type = $n; for = $for }) } else { $ok[$n] = $true }
    }
    @{ order = @(Get-ReleaseOrder -DependsOn $DependsOn -Names @($ok.Keys)); waiting = @($waiting); notApproved = $notApproved }
}

# Types whose default version uses another library type in a version that is not that type's default: the version
# in Dependencies names the version it was built with (faceplateDeskBOperate 0.0.2 -> typeHmiDeskB
# 0.0.1 while 0.0.2 is the default, 2026-10-06). Versions: @{ name; deps = @(@{ name; version }) };
# Defaults: type name -> default version. Returns name -> @("dep uses (default d)").
function Find-StaleDependencies([object[]]$Versions, [hashtable]$Defaults) {
    $stale = @{}
    foreach ($v in $Versions) {
        $old = @(foreach ($d in @($v.deps)) {
            $def = $Defaults[$d.name]
            if ($def -and [string]$d.version -ne [string]$def) { "$($d.name) (uses $($d.version), default $def)" }
        })
        if ($old.Count) { $stale[$v.name] = $old }
    }
    $stale
}

# ------------------------------------------------------------------ record files

function ConvertTo-PlainData($Value) {
    if ($null -eq $Value) { return $null }
    if ($Value -is [System.Management.Automation.PSCustomObject]) {
        $h = [ordered]@{}
        foreach ($p in $Value.PSObject.Properties) { $h[$p.Name] = ConvertTo-PlainData $p.Value }
        return $h
    }
    if ($Value -is [System.Collections.IList] -and $Value -isnot [string]) { return , @($Value | ForEach-Object { ConvertTo-PlainData $_ }) }
    $Value
}

function Get-ChangeDir([string]$Repo) { Join-Path $Repo 'library\changes' }

# A change id names files in library\changes. It comes from a tool argument or a record file, so '..\' would read and
# write outside that folder. Throws unless it is a plain file name.
function Assert-ChangeId([string]$Id) {
    if (-not $Id -or $Id -in '.', '..' -or $Id.IndexOfAny([System.IO.Path]::GetInvalidFileNameChars()) -ge 0) {
        throw "A library change id is a plain file name in library\changes, not a path: '$Id'."
    }
}

# Approvals ticked in the report win over the record: the report is where the user approves.
function Read-ChangeRecord([string]$Repo, [string]$Id) {
    Assert-ChangeId $Id
    $dir = Get-ChangeDir $Repo
    $json = Join-Path $dir "$Id.json"
    if (-not (Test-Path -LiteralPath $json)) { throw "No library change '$Id' in $dir." }
    $r = ConvertTo-PlainData (Get-Content -LiteralPath $json -Raw -Encoding UTF8 | ConvertFrom-Json)
    $md = Join-Path $dir "$Id.md"
    if (Test-Path -LiteralPath $md) {
        $ticks = Read-ReportApprovals (Get-Content -LiteralPath $md -Raw -Encoding UTF8)
        foreach ($n in $ticks.Keys) { if ($r.types.Contains($n) -and -not $r.types[$n].releasedAs) { $r.types[$n].approved = $ticks[$n] } }
    }
    $r
}

function Save-ChangeRecord([string]$Repo, $Record) {
    Assert-ChangeId $Record.id
    if ($Record.status -in 'open', 'done', 'left-behind') { $Record.status = Get-ChangeStatus $Record }
    $dir = Get-ChangeDir $Repo
    Write-TextFile (Join-Path $dir "$($Record.id).json") ($Record | ConvertTo-Json -Depth 10)
    Write-TextFile (Join-Path $dir "$($Record.id).md") (Format-ChangeReport $Record)
    "library\changes\$($Record.id).md"
}

# The open change that holds Name (any open one when Name is empty), newest first; $null when there is none.
function Find-OpenChange([string]$Repo, [string]$Name = '') {
    $dir = Get-ChangeDir $Repo
    foreach ($f in @(Get-ChildItem -LiteralPath $dir -Filter *.json -File -ErrorAction SilentlyContinue | Sort-Object Name -Descending)) {
        $r = Read-ChangeRecord $Repo $f.BaseName
        if ($r.status -eq 'open' -and (-not $Name -or $r.types.Contains($Name))) { return $r }
    }
    $null
}

# Open: there is work in it. Left-behind: its work is finished and types stand on old versions with no instance; it does not hold
# anything, but it does not read as done. Done: nothing left.
function Get-ChangeStatus($Record) {
    if (-not (Test-ChangeDone $Record)) { return 'open' }
    if (@($Record.leftBehind | Where-Object { $_ }).Count) { 'left-behind' } else { 'done' }
}

# ------------------------------------------------------------------ TIA side

# @{ name; class; folder; released; inWork } of the named types, in one walk of the library.
function Get-ChangeTypeInfo($Library, [string[]]$Names) {
    $want = @{}; foreach ($n in $Names) { $want[$n] = $true }
    foreach ($e in Get-GroupTree $Library.TypeFolder 'Types' 'Folders') {
        if (-not $want[$e.name]) { continue }
        $vs = @($e.obj.Versions)
        $w = Select-TypeVersion -Versions $vs -InWork
        $r = Select-TypeVersion -Versions $vs
        @{ name = $e.name; class = $e.obj.GetType().Name; folder = $e.folder; released = [string]$r.VersionNumber
           inWork = $(if ($w) { [string]$w.VersionNumber } else { '' }) }
    }
}

# Its version or a later one stands: a release can delete the version before it [PROBE], and that takes no change back.
function Test-VersionStands([object[]]$Versions, [string]$Number) {
    $want = $Number -as [version]
    if (-not $want) { return [bool]@(@($Versions) | Where-Object { [string]$_.VersionNumber -eq $Number }).Count }
    [bool]@(@($Versions) | Where-Object { ([string]$_.VersionNumber -as [version]) -ge $want }).Count
}

# A change whose new version of the changed type is gone from the library was discarded in TIA (project closed
# without saving): it is marked abandoned instead of being continued.
function Test-ChangeAlive($Library, $Record) {
    if (-not $Record.root) {
        # no changed type to go by: what it put in work or released is still there, or it had nothing yet
        $wanted = @($Record.types.Keys | Where-Object { $Record.types[$_].inWork -or $Record.types[$_].releasedAs })
        if (-not $wanted.Count) { return $true }
        $map = Get-LibraryTypeMap $Library
        foreach ($n in $wanted) {
            $number = $(if ($Record.types[$n].releasedAs) { $Record.types[$n].releasedAs } else { $Record.types[$n].inWork })
            if ($map[$n] -and (Test-VersionStands @($map[$n].Versions) $number)) { return $true }
        }
        return $false
    }
    $e = Get-GroupTree $Library.TypeFolder 'Types' 'Folders' | Where-Object { $_.name -eq $Record.root } | Select-Object -First 1
    [bool]($e -and (Test-VersionStands @($e.obj.Versions) ([string]$Record.to)))
}

# The open change holding Name that is still alive in TIA; discarded ones are marked abandoned on the way.
function Get-LiveChange($Library, [string]$Name = '', [string]$Id = '') {
    $repo = $script:Bridge.repo
    if (-not $repo) { return $null }
    if ($Id) {
        $r = Read-ChangeRecord $repo $Id
        $null = Clear-ChangeYesGone $Library $r
        return $r
    }
    while ($true) {
        $r = Find-OpenChange $repo $Name
        if (-not $r) { return $null }
        $null = Clear-ChangeYesGone $Library $r
        if (-not (Test-ChangeAlive $Library $r)) { Set-ChangeAbandoned $repo $r; continue }
        if ($r.status -eq 'open') { return $r }
    }
}

# The version the record holds of a type for a yes: what it has in work, or what it released of the types the answer put in work; '' when neither.
# A refused type was not put in work: a release of it is older than the yes. The changed type counts too: a yes puts it in work when it is on the list.
function Get-YesVersion($Record, [string]$Name) {
    $t = $Record.types[$Name]
    if ($t.inWork -and -not $t.releasedAs) { return [string]$t.inWork }
    $refused = $Record.leftBehindRefused -and $Record.leftBehindRefused.Contains($Name)
    if ($t.releasedAs -and -not $refused -and @($Record.leftBehindAsked) -contains $Name) { return [string]$t.releasedAs }
    ''
}

# What the record says it made and the PLC still holds: @{ folders; unread }. An earlier yes or library_edit_type may have made some, saved: those stay to be
# deleted. A read that fails keeps what it could not read, and is said.
function Read-FoldersStanding($Record) {
    $paths = @{}; $unread = @()
    $folders = @(foreach ($f in @($Record.foldersMade | Where-Object { $_ })) {
        $d = [string]$f.device
        if (-not $paths.ContainsKey($d)) {
            try { $paths[$d] = @(Get-PlcFolderPaths (Get-TiaSoftwareEntry 'plc' $d).software) }
            catch {
                if (Test-TiaEndedError $_) { throw }
                $paths[$d] = $null
                $unread += "$d`: $((ConvertTo-BridgeError $_).message)"
            }
        }
        if ($null -eq $paths[$d] -or $paths[$d] -contains "$($f.kind)`t$($f.folder)") { $f }
    })
    @{ folders = $folders; unread = ($unread -join '; ') }
}

# A yes put the changed type in work over its release, and holds that version in released: the type back to that release.
function Restore-RootAtYes($Record) {
    $t = $Record.types[$Record.root]
    $Record.to = [string]$t.released
    $t.inWork = [string]$t.released; $t.releasedAs = [string]$t.released; $t.inWorkBy = 'change'
    $t.released = [string]$Record.from; $t.approved = $false; $t.review = $null
}

# Takes a yes out of a record: the answer, what it holds in work or released (Stands: whether that version is in the library), and its folders the PLC no
# longer holds. A yes is refused while the change has work or an update outstanding, so an update owed now came after it. The caller saves.
function Remove-RecordYes($Record, [scriptblock]$Stands) {
    foreach ($n in @($Record.types.Keys)) {
        $t = $Record.types[$n]
        if ($n -eq $Record.root) {
            if (Get-YesVersion $Record $n) { Restore-RootAtYes $Record }
            continue
        }
        $releaseGone = $t.releasedAs -and -not (& $Stands $n $t.releasedAs)
        if ($releaseGone) { $t.releasedAs = '' }
        if ($releaseGone -or ($t.inWork -and -not $t.releasedAs)) { $t.inWork = ''; $t.inWorkBy = ''; $t.approved = $false; $t.review = $null }
    }
    $read = Read-FoldersStanding $Record
    $Record.foldersMade = @($read.folders)
    if (-not @($read.folders | Where-Object { $_.folder -eq $Record.temporaryFolder }).Count) { $Record.Remove('temporaryFolder') }
    if ($read.unread) {
        $Record.foldersUnread = $read.unread
        Add-LibraryLog "Library change $($Record.id): whether the folders made for it still stand was not read, so they stay named: $($read.unread)."
    }
    foreach ($k in 'leftBehindAnswer', 'leftBehindAsked', 'leftBehindRefused', 'usesOutside', 'updateOutstanding') { $Record.Remove($k) }
}

# A close without saving takes a yes out of the project and leaves it in the record, which would then speak for a user nobody asked. Gone: nothing the
# record holds of it stands in the library. A yes that put nothing in work (all refused) or that a discard took back says nothing about that, so its
# answer stays. A change with no changed type that holds nothing else then is abandoned. A list not fully read holds the change open, as for its own types
# (Set-RecordLeftBehind), until a read of it that is whole. Returns whether it cleared one.
function Clear-ChangeYesGone($Library, $Record, $Read = $null) {
    if ($Record.status -notin 'open', 'done', 'left-behind' -or [string]$Record.leftBehindAnswer -ne 'yes' -or -not $Record.temporaryFolder) { return $false }
    $held = @($Record.types.Keys | Where-Object { Get-YesVersion $Record $_ })
    if (-not $held.Count) { return $false }
    $map = Get-LibraryTypeMap $Library
    $stands = { param($Name, $Number) $map[$Name] -and (Test-VersionStands @($map[$Name].Versions) ([string]$Number)) }
    foreach ($n in $held) {
        if (& $stands $n (Get-YesVersion $Record $n)) { return $false }
    }
    Remove-RecordYes $Record $stands
    if (-not $Record.root -and -not @($Record.types.Values | Where-Object { $_.inWork -or $_.releasedAs }).Count) {
        Set-ChangeAbandoned $script:Bridge.repo $Record
        return $true
    }
    if (-not $Read) { $Read = Read-LeftBehind $Library }
    $null = Update-ChangeStale $Library $Record
    Set-RecordLeftBehind $Record $Read
    $null = Save-ChangeRecord $script:Bridge.repo $Record
    Add-LibraryLog "Library change $($Record.id): the yes to the types left on old versions is no longer in the project (closed without saving). It reads $($Record.status), not decided."
    $true
}

# The default (released) version of each named type (all when Names is empty) with the versions its Dependencies
# name, checked against the default versions of those types. Returns @{ stale (name -> @(...)); complete; walked }.
function Get-LibraryStale($Library, [string[]]$Names = @(), [int]$BudgetMs = $script:LibraryWalkBudgetMs) {
    $sw = [Diagnostics.Stopwatch]::StartNew()
    $want = @{}; foreach ($n in $Names) { $want[$n] = $true }
    $versions = New-Object System.Collections.ArrayList; $defaults = @{}; $walked = 0; $complete = $true; $depsOf = @{}
    foreach ($e in Get-GroupTree $Library.TypeFolder 'Types' 'Folders') {
        if ($want.Count -and -not $want[$e.name]) { continue }
        if ($sw.ElapsedMilliseconds -gt $BudgetMs) { $complete = $false; break }
        $v = Select-TypeVersion -Versions @($e.obj.Versions)
        if (-not $v) { continue }
        $deps = @(foreach ($d in @($v.Dependencies)) {
            $dn = [string]$d.TypeObject.Name
            if (-not $defaults.ContainsKey($dn)) { $defaults[$dn] = [string](Select-TypeVersion -Versions @($d.TypeObject.Versions)).VersionNumber }
            @{ name = $dn; version = [string]$d.VersionNumber }
        })
        [void]$versions.Add(@{ name = $e.name; deps = $deps })
        $depsOf[[string]$e.name] = @($deps | ForEach-Object { $_.name })
        $walked++
    }
    @{ stale = (Find-StaleDependencies @($versions) $defaults); complete = $complete; walked = $walked; deps = $depsOf }
}

# Marks the types of a change that kept their version but use an old version of another type (stale).
function Update-ChangeStale($Library, $Record) {
    # what cannot be read holds the change: nothing said it is done
    $Record.staleUnread = ''
    try { $s = Get-LibraryStale $Library @($Record.types.Keys) }
    catch {
        if (Test-TiaEndedError $_) { throw }
        $Record.staleUnread = (ConvertTo-BridgeError $_).message
        return @()
    }
    if (-not $s.complete) { $Record.staleUnread = "the library walk stopped after $($s.walked) types (time limit)" }
    $map = $null
    foreach ($n in @($Record.types.Keys)) {
        $t = $Record.types[$n]
        $t.stale = if ($t.inWork -and -not $t.releasedAs) { @() } else { @($s.stale[$n] | Where-Object { $_ }) }
        # an update removes the instance nothing uses, and with none a type cannot be put in work: it waits, the change does not
        $t.noInstance = $false
        if (-not @($t.stale | Where-Object { $_ }).Count) { continue }
        if ($null -eq $map) {   # one walk, however many are stale; what cannot be read counts as an instance, which keeps the change open
            try { $map = Get-LibraryTypeMap $Library }
            catch { if (Test-TiaEndedError $_) { throw }; $map = @{} }
        }
        $t.noInstance = [bool]($map[$n] -and -not (Test-TypeObjectHasInstance $map[$n]))
    }
    @($Record.types.Keys | Where-Object { @($Record.types[$_].stale | Where-Object { $_ }).Count -and -not $Record.types[$_].noInstance } | Sort-Object)
}

# Whether the type has an instance in this project; a read that fails counts as yes, which keeps the change open. Not through
# Get-TypeInstances, which takes a failing FindInstances for none. An HMI type always counts as yes: its instances are not
# known to be found this way, and the user updates it in TIA.
function Test-TypeHasInstance($Library, [string]$Name) {
    try { Test-TypeObjectHasInstance (Find-LibraryType $Library $Name).obj }
    catch { if (Test-TiaEndedError $_) { throw }; $true }
}

# Unread: a list that takes the name of a type whose read failed, for a caller who has to say so.
function Test-TypeObjectHasInstance($Type, [System.Collections.IList]$Unread = $null) {
    try {
        if ((Get-LibraryTypeScope $Type) -eq 'hmi') { return $true }
        foreach ($v in @($Type.Versions)) {
            foreach ($s in Get-TiaSoftwareList) { if (@($v.FindInstances($s.software)).Count) { return $true } }
        }
        $false
    }
    catch {
        if (Test-TiaEndedError $_) { throw }
        if ($null -ne $Unread) { [void]$Unread.Add("$($Type.Name): $((ConvertTo-BridgeError $_).message)") }
        $true
    }
}

# The types left on old versions with no instance, so no update can move them, in the whole library; not only of a change. A type
# with no instance on one of those counts too, though it uses that type's default version: it is on the old versions all the same.
# Returns @{ types = @(@{ type; version; uses }); complete; deps = type -> what its default version contains; unread = @(what could not be read) }.
function Get-TypesLeftBehind($Library) {
    $s = Get-LibraryStale $Library
    $map = $(if ($s.stale.Count) { Get-LibraryTypeMap $Library })   # one walk, however many are stale
    $found = [ordered]@{}
    $unread = New-Object System.Collections.ArrayList
    foreach ($n in @($s.stale.Keys | Sort-Object)) {
        $type = $map[$n]
        if ($type -and -not (Test-TypeObjectHasInstance $type $unread)) {
            $found[[string]$n] = @{ type = [string]$n; version = [string](Select-TypeVersion -Versions @($type.Versions)).VersionNumber; uses = @($s.stale[$n]) }
        }
    }
    $checked = @{}
    do {
        $more = $false
        foreach ($n in @(@($s.deps.Keys) | Sort-Object)) {
            if ($found.Contains([string]$n) -or $checked[$n] -or $s.stale.ContainsKey($n)) { continue }
            $on = @(@($s.deps[$n]) | Where-Object { $found.Contains([string]$_) })
            if (-not $on.Count) { continue }
            $checked[$n] = $true
            $type = $map[$n]
            if ($type -and -not (Test-TypeObjectHasInstance $type $unread)) {
                $found[[string]$n] = @{ type = [string]$n; version = [string](Select-TypeVersion -Versions @($type.Versions)).VersionNumber
                                        uses = @($on | ForEach-Object { "$_ (itself left on old versions)" }) }
                $more = $true
            }
        }
    } while ($more)
    @{ types = @($found.Values | Sort-Object { $_.type }); complete = [bool]$s.complete; deps = $s.deps; unread = @($unread) }
}

# What the library holds left behind, read once: @{ types; deps; unread; failed }. A read that stops short is said, not taken for none.
function Read-LeftBehind($Library) {
    try { $b = Get-TypesLeftBehind $Library }
    catch {
        if (Test-TiaEndedError $_) { throw }
        return @{ types = @(); deps = @{}; failed = $true; unread = (ConvertTo-BridgeError $_).message }
    }
    $why = @($(if (-not $b.complete) { 'the library walk stopped at its time limit' }))
    $notRead = @($b.unread | Where-Object { $_ })
    if ($notRead.Count) { $why += "could not read whether these have an instance: $(@($notRead | Select-Object -First 10 | ForEach-Object { Limit-Text $_ 150 }) -join '; ')$(if ($notRead.Count -gt 10) { " and $($notRead.Count - 10) more" })" }
    @{ types = @($b.types); deps = $b.deps; failed = $false; unread = (@($why | Where-Object { $_ }) -join '; ') }
}

# The list as it stands now goes into the record, also empty. What cannot be read holds the change, as for its own types.
function Set-RecordLeftBehind($Record, $Read) {
    if ($Read.unread) { $Record.staleUnread = [string]$Read.unread }
    if ($Read.failed) { return }
    $names = @($Read.types | ForEach-Object { $_.type })
    $Record.leftBehind = @($Read.types)
    foreach ($n in @($Record.types.Keys)) { $Record.types[$n].leftBehind = ($names -contains $n) }
    if ($Record.leftBehindRefused) {
        foreach ($n in @($Record.leftBehindRefused.Keys)) { if ($names -notcontains $n) { $Record.leftBehindRefused.Remove($n) } }
    }
}

# The change the question belongs to: the open one, else the newest that ended and is still in TIA; $null when there is none.
function Find-CurrentChange($Library) {
    $repo = $script:Bridge.repo
    if (-not $repo) { return $null }
    $open = Get-LiveChange $Library
    if ($open) { return $open }
    foreach ($f in @(Get-ChildItem -LiteralPath (Get-ChangeDir $repo) -Filter *.json -File -ErrorAction SilentlyContinue | Sort-Object Name -Descending)) {
        $r = Read-ChangeRecord $repo $f.BaseName
        if ($r.status -notin 'done', 'left-behind') { continue }
        $null = Clear-ChangeYesGone $Library $r
        if ($r.status -notin 'done', 'left-behind') { continue }
        if (Test-ChangeAlive $Library $r) { return $r }
        if ($r.status -eq 'left-behind') { Set-ChangeAbandoned $repo $r }
    }
    $null
}

# Its version is gone from the library, by default as the project was closed without saving: the record says so, and is not continued.
function Set-ChangeAbandoned([string]$Repo, $Record, [string]$Why = 'closed without saving') {
    if ($Why -eq 'closed without saving' -and [string]$Record.leftBehindAnswer -eq 'yes') { Remove-RecordYes $Record { $false } }
    $Record.status = 'abandoned'
    $null = Save-ChangeRecord $Repo $Record
    Add-LibraryLog "Library change $($Record.id) abandoned: $(if ($Record.root) { "$($Record.root) $($Record.to)" } else { 'what it held' }) is no longer in the library ($Why)."
}

# The list into the current change, and out of an older one for what is up to date now, so that a report says so for as long as
# they stand and no longer. Writes a record only when that changes it. Record: the change the caller is about, which is then the current one.
# Returns the current change or $null.
function Update-ChangesLeftBehind($Library, $Read, $Record = $null) {
    $repo = $script:Bridge.repo
    if (-not $repo -or $Read.failed) { return $null }
    $current = $(if ($Record) { $Record } else { Find-CurrentChange $Library })
    if ($Read.unread) { return $current }   # a walk cut short lists too few: it changes no record
    $names = @($Read.types | ForEach-Object { $_.type })
    foreach ($f in @(Get-ChildItem -LiteralPath (Get-ChangeDir $repo) -Filter *.json -File -ErrorAction SilentlyContinue)) {
        if ($current -and $f.BaseName -eq $current.id) { continue }
        $r = Read-ChangeRecord $repo $f.BaseName
        $null = Clear-ChangeYesGone $Library $r $Read
        if ($r.status -ne 'left-behind') { continue }
        if (-not (Test-ChangeAlive $Library $r)) { Set-ChangeAbandoned $repo $r; continue }
        $still = @($r.leftBehind | Where-Object { $_ -and $names -contains $_.type })
        if ($still.Count -ne @($r.leftBehind | Where-Object { $_ }).Count) {
            Set-RecordLeftBehind $r @{ types = $still; unread = $Read.unread; failed = $false }
            $null = Save-ChangeRecord $repo $r
        }
    }
    if ($current) {
        $was = ConvertTo-Json @($current.leftBehind | Where-Object { $_ } | ForEach-Object { "$($_.type) $($_.version) $(@($_.uses) -join ';')" })
        $status = $current.status
        Set-RecordLeftBehind $current $Read
        $now = ConvertTo-Json @($current.leftBehind | Where-Object { $_ } | ForEach-Object { "$($_.type) $($_.version) $(@($_.uses) -join ';')" })
        if ($was -ne $now -or $status -ne (Get-ChangeStatus $current)) { $null = Save-ChangeRecord $repo $current }
    }
    $current
}

function Format-TypesLeftBehind([object[]]$Types) {
    $names = @($Types | Select-Object -First 10 | ForEach-Object {
        $uses = @($_.uses)
        "$($_.type) $($_.version) (uses $(@($uses | Select-Object -First 2) -join '; ')$(if ($uses.Count -gt 2) { " and $($uses.Count - 2) more" }))"
    })
    $more = $(if (@($Types).Count -gt 10) { " and $(@($Types).Count - 10) more (typesLeftBehind)" })
    "Left on old versions, as they have no instance in this project and no update can move them: $($names -join ', ')$more."
}

# An answer covers the list as it stood: the types on the list now that nobody asked the user about. A record from before this was kept counts as asked.
function Get-LeftBehindUnasked($Record, [object[]]$Types) {
    if (-not $Record -or -not $Record.leftBehindAnswer -or $null -eq $Record.leftBehindAsked) { return @() }
    @(@($Types | Where-Object { $_ } | ForEach-Object { [string]$_.type }) | Where-Object { @($Record.leftBehindAsked) -notcontains $_ })
}

function Format-YesCost { 'A yes costs a new version of every type on the list, also of older changes and of a type that would move by itself, each through review and approval.' }

# One sentence for the report of a change and the results that speak from its record.
function Format-NotDecided { "Not decided yet: the user is asked whether to bring them up to date through a temporary folder (library_left_behind). $(Format-YesCost)" }

function Format-NamesCapped([string[]]$Names) {
    "$(@($Names | Select-Object -First 10) -join ', ')$(if (@($Names).Count -gt 10) { " and $(@($Names).Count - 10) more" })"
}

# What the agent does about the list; the question is the user's, once per change. Types: the list as it stands now.
function Format-LeftBehindAsk($Record, [object[]]$Types = @()) {
    $unasked = @(Get-LeftBehindUnasked $Record $Types)
    if (-not $unasked.Count) {
        switch ([string]$Record.leftBehindAnswer) {
            'no' { return 'The user chose to leave them: they stay listed, in the results, the report of the change and library_review, until they are up to date. library_left_behind with answer yes if that changes.' }
            'yes' {
                $refused = @($(if ($Record.leftBehindRefused) { @($Record.leftBehindRefused.Keys) }) | Where-Object { $_ } | Sort-Object)
                $why = @($refused | Select-Object -First 10 | ForEach-Object { "$_ ($(Limit-Text ([string]$Record.leftBehindRefused[$_]) 60))" }) -join '; '
                if ($refused.Count) { return "Refused on the way: $why$(if ($refused.Count -gt 10) { " and $($refused.Count - 10) more" }); the report has the reasons. Tell the user, who decides: library_left_behind with answer yes again once that is settled, or with answer no." }
                return 'The user chose to bring them up to date: library_left_behind with answer yes.'
            }
        }
    }
    if ($Record -and $Record.status -eq 'open') { return 'The user is asked about them when this change reaches its end.' }
    $ask = "$(Format-NotDecided) Ask the user, once, with this list: bring them up to date through a temporary folder, or leave them? Yes: library_left_behind with answer yes, and folder if the user names one. No: library_left_behind with answer no. Do not decide it for the user."
    if ($unasked.Count) { return "The user answered $($Record.leftBehindAnswer) before these came: $(Format-NamesCapped $unasked). $ask" }
    $ask
}

# Next step at the end of a change.
function Format-ChangeEndNext($Record) {
    if ($Record.status -eq 'done') { return "library change done: compile, save, then commit the project repo.$(Format-FolderCleanup $Record)" }
    if ([string]$Record.leftBehindAnswer -eq 'no' -and -not @(Get-LeftBehindUnasked $Record @($Record.leftBehind)).Count) { return "library change $($Record.id) ended with types left on old versions, as the user chose: compile, save, then commit the project repo.$(Format-FolderCleanup $Record)" }
    "the work of library change $($Record.id) is finished, but it is not done, as types are left on old versions: compile, then as follows."
}

function Format-FolderList([object[]]$Folders) {
    @(@($Folders | Where-Object { $_ }) | ForEach-Object { "$($_.kind) $($_.folder)" }) -join ', '
}

function Format-FoldersMade($Record) { Format-FolderList @($Record.foldersMade) }

# At most ten for a text; Where: where the rest stands.
function Format-FoldersCapped([object[]]$Folders, [string]$Where) {
    $all = @($Folders | Where-Object { $_ })
    "$(Format-FolderList @($all | Select-Object -First 10))$(if ($all.Count -gt 10) { " and $($all.Count - 10) more ($Where)" })"
}

function Add-ChangeFolders([string]$Id, [object[]]$Folders) {
    $rec = Read-ChangeRecord $script:Bridge.repo $Id
    $rec.foldersMade = @(@($rec.foldersMade | Where-Object { $_ }) + @($Folders))
    $null = Save-ChangeRecord $script:Bridge.repo $rec
}

function Format-FolderCleanup($Record) {
    $made = @($Record.foldersMade | Where-Object { $_ } | Sort-Object { ([string]$_.folder).Length } -Descending)
    if (-not $made.Count) { return '' }
    " The folders made for it stand empty once TIA has removed the temporary instances: delete_folder with $(@($made | Select-Object -First 10 | ForEach-Object { "kind $($_.kind), folder $($_.folder)" }) -join '; ')$(if ($made.Count -gt 10) { " and $($made.Count - 10) more (foldersMade in the report)" })."
}

# Says in any result what the library holds left behind. A read that fails is said, not taken for none.
# Read: what this call read already, so as not to walk the library twice. Record: the change this result is about: who decided is said from
# its record, not from whichever other change is read as the current one.
function Add-LeftBehindFacts($Result, $Library, $Read = $null, $Record = $null) {
    if (-not $Read) { $Read = Read-LeftBehind $Library }
    if ($Read.failed) {
        $Result.typesLeftBehindUnread = [string]$Read.unread
        $Result.summary = "$($Result.summary) Which types are left on old versions was not read: $($Result.typesLeftBehindUnread)".Trim()
        return
    }
    if ($Read.unread) {
        $Result.typesLeftBehindUnread = [string]$Read.unread
        $Result.summary = "$($Result.summary) Which types are left on old versions is not fully known: $($Read.unread).".Trim()
    }
    $record = Update-ChangesLeftBehind $Library $Read $Record
    if (@($Read.types).Count) {
        $Result.typesLeftBehind = @($Read.types)
        $text = "$(Format-TypesLeftBehind @($Read.types)) $(Format-LeftBehindAsk $record @($Read.types))"
        $Result.summary = "$($Result.summary) $text".Trim()
        if ($Result.Contains('next')) { $Result.next = "$($Result.next) $text" }
    }
}

# A type of the change whose default version moved on without the bridge releasing it was released in TIA
# (the user updated the ten faceplate types of 2026-10-06_1455 there). Info: @{ name; released; inWork }.
function Update-ChangeReleasedOutside($Record, [object[]]$Info) {
    foreach ($i in $Info) {
        if (-not $Record.types.Contains($i.name) -or $i.name -eq $Record.root) { continue }
        $t = $Record.types[$i.name]
        if (-not $t.releasedAs -and -not $i.inWork -and $i.released -and [string]$i.released -ne [string]$t.released) {
            $t.releasedAs = [string]$i.released; $t.releasedOutside = $true; $t.inWork = ''
        }
    }
}

# Names of the types of a change in work and not released.
function Get-ChangeTypesInWork($Record) { @($Record.types.Keys | Where-Object { $Record.types[$_].inWork -and -not $Record.types[$_].releasedAs }) }

# Record the in-work state TIA shows for the types of a change. By: who put a newly found one in work, or 'found' when that was not read.
function Update-ChangeInWork($Record, [object[]]$InWork, [string]$By) {
    foreach ($w in $InWork) {
        if (-not $Record.types.Contains($w.type)) { continue }
        $t = $Record.types[$w.type]
        if (-not $t.inWork -and -not $t.releasedAs) { $t.inWork = [string]$w.inWork; if (-not $t.inWorkBy) { $t.inWorkBy = $By } }
        # in work again after its release, on a change still open: it goes through review and approval again
        elseif ($t.releasedAs -and $w.type -ne $Record.root -and [version]$w.inWork -gt [version]$t.releasedAs) {
            $t.released = $t.releasedAs; $t.releasedAs = ''; $t.inWork = [string]$w.inWork; $t.inWorkBy = $By; $t.approved = $false; $t.review = $null
        }
    }
}

# A type the record has in work that TIA no longer has so, as the project was closed without saving: the record is not left waiting for
# it. The changed type has its own rule (Test-ChangeAlive). InWork: names of the types in work now.
function Clear-ChangeInWorkGone($Record, [string[]]$InWork) {
    foreach ($n in @($Record.types.Keys)) {
        $t = $Record.types[$n]
        if ($t.inWork -and -not $t.releasedAs -and $t.inWorkBy -ne 'change' -and $InWork -notcontains $n) { $t.inWork = ''; $t.inWorkBy = ''; $t.approved = $false; $t.review = $null }
    }
}

# Edit of the default version through the first project instance (Edit() without one fails on V20); the caller
# wraps it in a write.
function Set-TypeInWork($Library, [string]$Name) {
    $e = Find-LibraryType $Library $Name
    $from = Select-TypeVersion -Versions @($e.obj.Versions)
    $instances = @(Get-TypeInstances $from)
    if (-not $instances.Count) { throw "Type '$Name' V $($from.VersionNumber) has no instance in this project; it cannot be put in work." }
    $from.Edit($instances[0].info)
    [string](Select-TypeVersion -Versions @($e.obj.Versions) -InWork).VersionNumber
}

# Both versions of a type into Dir, in the same format: SimaticSD, else SimaticML when TIA refuses SD.
function Export-ForReview($Library, [string]$Name, [string]$Dir) {
    $e = Find-LibraryType $Library $Name
    $supported = @($e.obj.GetSupportedExportFormats() | ForEach-Object { [string]$_ })
    $format = Select-LibraryExportFormat $supported
    if (-not $format) { return @{ ok = $false; note = "faceplate type: Openness cannot export its contents ($(Get-GuidePath 'wincc-comfort-openness.md') section 6); compare it in TIA" } }
    $first = ''
    try {
        $null = Export-LibraryTypeDocuments $e $Dir -Format $format
        $null = Export-LibraryTypeDocuments $e $Dir -Released -Format $format
        return @{ ok = $true; format = $(if ($format -eq 'SimaticSD') { 'sd' } else { 'xml' }) }
    } catch {
        if (Test-TiaEndedError $_) { throw }
        $first = (ConvertTo-BridgeError $_).message
    }
    $ml = @($supported | Where-Object { $_ -like 'SimaticML*' } | Select-Object -First 1)
    if (-not $ml.Count -or $ml[0] -eq $format) { return @{ ok = $false; note = "export failed: $first" } }
    try {
        $null = Export-LibraryTypeDocuments $e $Dir -Format $ml[0]
        $null = Export-LibraryTypeDocuments $e $Dir -Released -Format $ml[0]
        @{ ok = $true; format = 'xml'; note = "SD export refused: $first" }
    } catch {
        if (Test-TiaEndedError $_) { throw }
        @{ ok = $false; note = "export failed: $first / $((ConvertTo-BridgeError $_).message)" }
    }
}

# The types of a yes on this change still in work, as TIA has them now.
function Get-YesTypesInWork($Library, $Record) {
    $inWork = { @($Record.types.Keys | Where-Object { $Record.types[$_].inWork -and -not $Record.types[$_].releasedAs } | Sort-Object) }
    if (-not @(& $inWork).Count) { return @() }
    $w = Get-InWorkTypes $Library
    if ($w.complete) {
        Clear-ChangeInWorkGone $Record @($w.types | ForEach-Object { $_.type })
        $null = Save-ChangeRecord $script:Bridge.repo $Record
    }
    @(& $inWork)
}

# What library_edit_type must not do while a yes is in work, or $null. An edit of the changed type of a released change starts a new change: that
# would leave the types and folders of the yes on the old record, and the chain would release them with no review or approval. An edit of a type
# they contain, outside their change, opens a second change, and the chain then stops at TIA's Error when calling method 'Release' [PROBE] (2026-11-03).
function Get-EditYesRefusal($Library, [string]$Name) {
    $repo = $script:Bridge.repo
    if (-not $repo) { return $null }
    $wayOut = 'Finish them first (library_review, the user''s approval, library_release_chain), or take each back with library_discard_type; then edit it.'
    $open = Get-LiveChange $Library $Name
    if ($open -and $open.root -eq $Name -and $open.types[$Name].releasedAs -and [string]$open.leftBehindAnswer -eq 'yes') {
        $busy = @(Get-YesTypesInWork $Library $open)
        if ($busy.Count) { return "Type '$Name' is the changed type of library change $($open.id), which holds the types of a yes in work: $($busy -join ', '). A new change now would lose them, and the folders of the yes. Nothing was put in work. $wayOut" }
    }
    $graph = $null
    foreach ($f in @(Get-ChildItem -LiteralPath (Get-ChangeDir $repo) -Filter *.json -File -ErrorAction SilentlyContinue | Sort-Object Name -Descending)) {
        $r = Read-ChangeRecord $repo $f.BaseName
        if ([string]$r.leftBehindAnswer -ne 'yes') { continue }
        # any record, also one that reads done: this edit may put a type in work on a number that yes released, and that would then read as standing
        if ((Clear-ChangeYesGone $Library $r) -or $r.status -ne 'open' -or $r.types.Contains($Name) -or -not (Test-ChangeAlive $Library $r)) { continue }
        $busy = @(Get-YesTypesInWork $Library $r)
        if (-not $busy.Count) { continue }
        if (-not $graph) { $graph = Get-LibraryDependsOn $Library }
        $over = @(Get-TypeDependents -DependsOn $graph.graph -Name $Name | Where-Object { $busy -contains $_ } | Sort-Object)
        if ($over.Count) { return "Type '$Name' is contained by $($over -join ', '), of the yes in work in library change $($r.id). A second change on it now would stop their release, with no reason from TIA. Nothing was put in work. $wayOut" }
        if (-not $graph.complete) { return "Whether type '$Name' is contained by $($busy -join ', '), of the yes in work in library change $($r.id), is not known: the library walk stopped at its time limit. A second change on it could stop their release. Nothing was put in work. Try again, or finish them first." }
    }
    $null
}

# library_edit_type: a type of an open change joins it (put in work by the bridge); a type with dependents that is
# in no open change starts one. Returns @{ id; report; joined } or $null.
function Register-ChangeOnEdit($Library, $Entry, [string]$From, [string]$To, $Graph, [string[]]$Dependents) {
    $repo = $script:Bridge.repo
    if (-not $repo) { return $null }
    $open = Get-LiveChange $Library $Entry.name
    # the changed type of an open change, in work again after its release: that is a new change, not more of the old one
    $superseded = New-Object System.Collections.ArrayList
    while ($open -and $open.root -eq $Entry.name -and $open.types[$open.root].releasedAs) {
        $open.status = 'superseded'
        $null = Save-ChangeRecord $repo $open
        [void]$superseded.Add(@{ id = $open.id; approvalsDropped = @(Get-ApprovalsLeft $open) })
        $open = Get-LiveChange $Library $Entry.name
    }
    if ($open) {
        $joined = $open.root -ne $Entry.name
        $t = $(if ($joined) { $open.types[$Entry.name] })
        $dropped = [bool]($t -and $t.approved -and $t.releasedAs)
        if ($joined) { Update-ChangeInWork $open @(@{ type = $Entry.name; inWork = $To }) 'bridge' }
        $result = @{ id = $open.id; report = (Save-ChangeRecord $repo $open); joined = $joined; superseded = @($superseded) }
        if ($dropped) { $result.approvalDropped = $Entry.name }
        return $result
    }
    # a type on the list leaves it as soon as it has an instance: without a record no change would hold it while it stands in work on old versions
    if (-not @($Dependents).Count -and -not (Test-TypeOnLeftBehindList $repo $Entry.name)) { return $(if ($superseded.Count) { @{ id = ''; report = ''; joined = $false; superseded = @($superseded) } }) }
    if (-not $Graph.complete) { return @{ id = ''; report = ''; joined = $false; superseded = @($superseded); note = 'No change report: the dependency graph stopped at its time limit.' } }
    $info = @(Get-ChangeTypeInfo $Library (@($Entry.name) + @($Dependents)))
    foreach ($i in $info) { if ($i.name -eq $Entry.name) { $i.released = $From; $i.inWork = $To } }
    $levels = Get-ImpactLevels -DependsOn $Graph.graph -Root $Entry.name -Dependents $Dependents
    $rec = New-ChangeRecord -Root $Entry.name -From $From -To $To -Types $info -Levels $levels -At (Get-Date)
    $rec.id = Get-FreeChangeId $repo $rec.id
    @{ id = $rec.id; report = (Save-ChangeRecord $repo $rec); joined = $false; superseded = @($superseded) }
}

function Test-TypeOnLeftBehindList([string]$Repo, [string]$Name) {
    foreach ($f in @(Get-ChildItem -LiteralPath (Get-ChangeDir $Repo) -Filter *.json -File -ErrorAction SilentlyContinue)) {
        $r = Read-ChangeRecord $Repo $f.BaseName
        if ($r.status -in 'open', 'left-behind' -and @($r.leftBehind | Where-Object { $_ -and $_.type -eq $Name }).Count) { return $true }
    }
    $false
}

# An id has the minute only: a change started in the same minute must not overwrite the record of the last one.
function Get-FreeChangeId([string]$Repo, [string]$Id) {
    $dir = Get-ChangeDir $Repo
    $free = $Id; $n = 2
    while (Test-Path -LiteralPath (Join-Path $dir "$free.json")) { $free = "$Id-$n"; $n++ }
    $free
}

# The types approved in a change and not released: what ends with it.
function Get-ApprovalsLeft($Record) {
    @($Record.types.Keys | Where-Object { $Record.types[$_].approved -and -not $Record.types[$_].releasedAs } | Sort-Object)
}

# What an edit did to changes and approvals, for its summary; '' when nothing.
function Format-EditChangeFacts($Change) {
    $parts = @(foreach ($s in @($Change.superseded | Where-Object { $_ })) {
        "Library change $($s.id) is superseded: its changed type was released and is in work again$(if (@($s.approvalsDropped).Count) { ", and the approvals of $(@($s.approvalsDropped) -join ', ') are dropped: they have to be given again, tell the user" })."
    })
    if ($Change.approvalDropped) { $parts += "The approval of $($Change.approvalDropped) is dropped: it goes through review and approval again." }
    $parts -join ' '
}

# library_release_type / library_release_chain: released types of the open change. The changed type's number
# replaces the proposed one (a version passed to the release may differ). Returns the report path or ''.
function Set-ChangeReleased($Library, [hashtable]$Released) {
    $rec = Update-ReleasedInRecord $Library $Released
    if (-not $rec) { return '' }
    Save-ChangeRecord $script:Bridge.repo $rec
}

# The open change holding what was released, marked, not saved; $null when there is none.
function Update-ReleasedInRecord($Library, [hashtable]$Released) {
    if (-not $script:Bridge.repo -or -not $Released.Count) { return $null }
    $rec = $null
    foreach ($n in $Released.Keys) { $rec = Get-LiveChange $Library $n; if ($rec) { break } }
    if (-not $rec) { return $null }
    foreach ($n in $Released.Keys) {
        if (-not $rec.types.Contains($n)) { continue }
        $rec.types[$n].releasedAs = [string]$Released[$n]
        if ($n -eq $rec.root) { $rec.to = [string]$Released[$n] }
    }
    $rec.releasedSinceUpdate = $true
    $rec
}

# library_release_type can be the last step of a change: it reads what is left as the chain does, or the record would say done over
# types left on old versions. InWork: what stands in work after it (the types of a Get-InWorkTypes). 'found': it was seen in work, not who did that,
# and it is no sign of an update (Test-ChangeDone). Returns @{ report; record; read }, or $null with no change.
function Update-ChangeAtRelease($Library, [hashtable]$Released, [object[]]$InWork = @()) {
    $rec = Update-ReleasedInRecord $Library $Released
    if (-not $rec) { return $null }
    Update-ChangeInWork $rec $InWork 'found'
    $null = Update-ChangeStale $Library $rec
    $read = Read-LeftBehind $Library
    Set-RecordLeftBehind $rec $read
    @{ report = (Save-ChangeRecord $script:Bridge.repo $rec); record = $rec; read = $read }
}

# After a compile: TIA can put types of the open change in work by then, and nothing else reads that before the review. It writes the record only when
# it finds one, and ends no change: a compile runs before the session archive, so a change no longer in TIA is left for the tools that mark it.
# Returns @{ id; report; inWork = @(@{ type; version }) }, or $null when there is no change or nothing new.
function Update-ChangeAtCompile($Library) {
    $rec = Find-OpenChange $script:Bridge.repo
    if (-not $rec -or -not (Test-ChangeAlive $Library $rec)) { return $null }
    $before = @(Get-ChangeTypesInWork $rec)
    Update-ChangeInWork $rec @(Get-ChangeTypeInfo $Library @($rec.types.Keys) | Where-Object { $_.inWork } | ForEach-Object { @{ type = $_.name; inWork = $_.inWork } }) 'found'
    $new = @(Get-ChangeTypesInWork $rec | Where-Object { $before -notcontains $_ } | Sort-Object)
    if (-not $new.Count) { return $null }
    $null = Update-ChangeStale $Library $rec
    @{ id = $rec.id; report = (Save-ChangeRecord $script:Bridge.repo $rec); inWork = @($new | ForEach-Object { @{ type = $_; version = [string]$rec.types[$_].inWork } }) }
}

# The compile tool: the compile, and what it finds of the open change beside it. A record that cannot be read costs the compile nothing. Not on the
# copy of an export-only session, which is never saved, nor after a refusal or a compile of the HMI, which has no scope of PLC types.
function Invoke-CompileAndReadChange($a) {
    $r = Invoke-CompileTool $a
    $export = [bool]($script:Bridge.background -and -not $script:Bridge.background.write)
    if ($r.scope -notin 'plc', 'blocks' -or $export -or -not $script:Bridge.repo) { return $r }
    try { $c = Update-ChangeAtCompile (Get-TiaLibrary) }
    catch {
        if (Test-TiaEndedError $_) { throw }
        $r.changeUnread = "Whether this compile put types of the open library change in work was not read: $((ConvertTo-BridgeError $_).message)"
        return $r
    }
    if (-not $c) { return $r }
    $said = "Library change $($c.id): in work now, not when its record was last read: $(Format-TypeVersionsCapped $c.inWork). Report: $($c.report)."
    $r.note = $(if ($r.note) { "$($r.note) $said" } else { $said })
    $r.alsoInWork = @($c.inWork)
    $r.report = $c.report
    Add-LibraryLog $said
    $r
}

# A discard can take the last work out of a change while its types stand on old versions: it reads what a release reads, or the record would say
# done until the next update. Returns @{ report; record; read; stale }.
function Update-ChangeAtDiscard($Library, $Record) {
    $stale = @(Update-ChangeStale $Library $Record)
    $read = Read-LeftBehind $Library
    Set-RecordLeftBehind $Record $read
    @{ report = (Save-ChangeRecord $script:Bridge.repo $Record); record = $Record; read = $read; stale = $stale }
}

function Format-ChangeAtDiscard($AtDiscard) {
    $rec = $AtDiscard.record
    $stale = @($AtDiscard.stale | Where-Object { $_ })
    if (-not $stale.Count) { return "Library change $($rec.id) reads $($rec.status)." }
    "Library change $($rec.id) stays open: on old versions, with their instances in the PLC: $(Format-NamesCapped $stale)." +
    $(if (@($rec.foldersMade | Where-Object { $_ }).Count) { " Folders made for it stand: $(Format-FoldersCapped @($rec.foldersMade) 'foldersMade in the report')." }) +
    ' library_update_usages removes an instance nothing uses, and the type is then on the list again.'
}

# Done: the changed type is released, the project was updated to it, and no type of the change is in work unreleased.
# Types TIA never put in work (faceplate types, 2026-10-06) keep their version; they need no new one.
function Test-ChangeDone($Record) {
    $root = $(if ($Record.root) { $Record.types[$Record.root] })
    # updated: set by library_update_usages; a type put in work by TIA or the bridge shows the same for older records
    $updated = $Record.updated -or @($Record.types.Values | Where-Object { $_.inWorkBy -in 'tia', 'bridge' }).Count
    # a type that kept its version but still uses an old version of a change type is not done either (stale)
    [bool](($updated -or -not $Record.root) -and -not $Record.updateOutstanding -and -not $Record.staleUnread -and ($root.releasedAs -or -not $Record.root) -and
        -not @($Record.types.Keys | Where-Object { $t = $Record.types[$_]; ($t.inWork -and -not $t.releasedAs) -or (@($t.stale | Where-Object { $_ }).Count -and -not $t.noInstance) }).Count)
}

# library_update_usages: note what TIA put in work, then put in work the library blocks of the change that TIA
# leaves out (they report "incompatible changes" in the compile). Returns @{ report; byTia (in work by this update); standing; byBridge; failed }, or
# @{ ended } with the TIA-ended result when that ended TIA (the record stays as it is: nothing of it is in TIA), or $null.
function Update-ChangeAfterUpdate($Library, [object[]]$InWork, [bool]$PutLeftOut, $Session) {
    $rec = Get-LiveChange $Library
    if (-not $rec) { return $null }
    $rec.updated = $true
    $rec.releasedSinceUpdate = $false
    $rec.updateOutstanding = $false
    $before = @(Get-ChangeTypesInWork $rec)
    Update-ChangeInWork $rec $InWork 'tia'
    $byTia = @(Get-ChangeTypesInWork $rec | Where-Object { $before -notcontains $_ })
    # seen in work at the release or a compile: not this update's doing, and who did that was not read
    $standing = @($before | Where-Object { $rec.types[$_].inWorkBy -eq 'found' } | Sort-Object)
    $byBridge = @(); $failed = @()
    if ($PutLeftOut) {
        $plcDevices = @(Get-TiaDeviceNames 'plc')
        $c = Invoke-CompileEveryDevice 'plc'
        $errors = @(foreach ($i in @($c.items)) { if ($i.messages) { Get-CompileErrors $i.messages } })
        $left = @($errors | Where-Object { $_.description -match 'incompatible changes' -and $rec.types.Contains($_.object) -and -not $rec.types[$_.object].inWork } |
            ForEach-Object { $_.object } | Sort-Object -Unique)
        $items = New-Object System.Collections.ArrayList
        foreach ($n in $left) {
            $item = [ordered]@{ type = $n }
            [void]$items.Add($item)
            try {
                $w = Invoke-TiaWrite "put library type $n in work" { Set-TypeInWork $Library $n }
                Update-ChangeInWork $rec @(@{ type = $n; inWork = [string]@($w.output)[-1] }) 'bridge'
                $byBridge += $n
                $item.ok = $true
                Register-LibraryTypeWrite $Session 'plc' $plcDevices "type:$n" $true
            } catch {
                # putting a type in work through Openness has crashed TIA (faceplate types, 2026-10-06)
                Set-ItemError $item $_
                $ended = Get-TiaEndedResult $items 'project update'
                if ($ended) { return @{ ended = $ended } }
                $failed += @{ type = $n; error = $item.error.message }
                Register-LibraryTypeWrite $Session 'plc' $plcDevices "type:$n" $false
            }
        }
    }
    $stale = @(Update-ChangeStale $Library $rec)
    $read = Read-LeftBehind $Library
    Set-RecordLeftBehind $rec $read
    $report = Save-ChangeRecord $script:Bridge.repo $rec
    @{ id = $rec.id; report = $report; byTia = $byTia; standing = $standing; byBridge = $byBridge; failed = $failed; status = $rec.status; stale = $stale; record = $rec; leftBehindRead = $read }
}

# Types of one change whose review documents would land on one path: name -> the others. Their comparison would read one
# type's documents as the other's, and an approval would rest on it. Case does not tell files apart here either.
function Get-ReviewNameClashes([string[]]$Names) {
    $clashes = New-Object System.Collections.Hashtable ([StringComparer]::Ordinal)
    foreach ($n in $Names) {
        $others = @(Get-FolderSharers $n $Names)
        if ($others.Count) { $clashes[$n] = $others }
    }
    $clashes
}

function Invoke-LibraryReviewTool($a) {
    $null = Get-BridgeSession
    $repo = $script:Bridge.repo
    $lib = Get-TiaLibrary
    $rec = Get-LiveChange $lib -Id ([string]$a.change)
    if (-not $rec) {
        $none = New-Refusal 'No open library change: library_edit_type on the type you change starts one.'
        Add-LeftBehindFacts $none $lib
        return $none
    }
    $info = @(Get-ChangeTypeInfo $lib @($rec.types.Keys))
    Update-ChangeInWork $rec @($info | Where-Object { $_.inWork } | ForEach-Object { @{ type = $_.name; inWork = $_.inWork } }) 'tia'
    Update-ChangeReleasedOutside $rec $info
    Clear-ChangeInWorkGone $rec @($info | Where-Object { $_.inWork } | ForEach-Object { $_.name })
    $stale = @(Update-ChangeStale $lib $rec)
    $again = Get-OptionalBool $a 'again' $false
    $names = if ($a.types) { @($a.types) } else {
        @($rec.types.Keys | Where-Object { $t = $rec.types[$_]; $t.inWork -and -not $t.releasedAs -and ($again -or -not $t.review) })
    }
    $dir = Join-Path (Get-ChangeDir $repo) "$($rec.id)\review"
    $changeTypes = @($rec.types.Keys)
    # a type left behind moves to the new versions of what it contains, whether or not this change released them
    $expected = @($changeTypes) + @($rec.usesOutside | Where-Object { $_ })
    $clashes = Get-ReviewNameClashes $changeTypes
    foreach ($n in $names) {
        if (-not $rec.types.Contains($n)) { continue }
        if ($clashes.ContainsKey($n)) {
            $rec.types[$n].review = @{ verdict = 'not-compared'; note = "Shares its file name with $(@($clashes[$n] | ForEach-Object { "'$_'" }) -join ' and '), so the documents would overwrite each other. Rename one in TIA, or compare them in TIA." }
            continue
        }
        $x = Export-ForReview $lib $n $dir
        if (-not $x.ok) { $rec.types[$n].review = @{ verdict = 'not-compared'; note = $x.note }; continue }
        $safe = ConvertTo-SafeFileName $n
        $c = Compare-TypeDocuments (Join-Path $dir "$safe.released") (Join-Path $dir $safe) $expected
        $diff = "library\changes\$($rec.id)\$safe.diff"
        $lines = @("$n released $($rec.types[$n].released) against in work $($rec.types[$n].inWork), compared as $($x.format): $($c.verdict)", '') +
                 @($c.references | ForEach-Object { "reference  $_" }) + @($c.unexpected | ForEach-Object { "UNEXPECTED $_" }) + @('') + @($c.content)
        Write-TextFile (Join-Path $repo $diff) (($lines -join "`r`n") + "`r`n")
        $rec.types[$n].review = @{ verdict = $c.verdict; kind = $c.kind; references = @($c.references); unexpected = @($c.unexpected)
                                   content = @($c.content | Select-Object -First 20); contentCount = @($c.content).Count; diff = $diff; format = $x.format; note = [string]$x.note }
    }
    $read = Read-LeftBehind $lib
    Set-RecordLeftBehind $rec $read
    $report = Save-ChangeRecord $repo $rec
    $reviewed = @($names | Where-Object { $rec.types.Contains($_) })
    $by = @{}
    foreach ($n in $reviewed) { $v = [string]$rec.types[$n].review.verdict; if (-not $by.ContainsKey($v)) { $by[$v] = @() }; $by[$v] += $n }
    # S7_Setpoint-only differences are offered to the user as one group per level (decided 2026-10-06)
    $setpointOnly = @($by['flagged'] | Where-Object { $_ -and $rec.types[$_].review.kind -eq 'setpoint-only' } | Sort-Object)
    $flagged = @($by['flagged'] | Where-Object { $_ -and $setpointOnly -notcontains $_ } | Sort-Object)
    $counts = (@($by.Keys | Sort-Object | ForEach-Object { "$(@($by[$_]).Count) $_" }) -join ', ')
    $summary = "Reviewed $($reviewed.Count) types of $(if ($rec.root) { "$($rec.root) $($rec.to)" } else { "change $($rec.id)" })$(if ($counts) { ": $counts" })."
    if ($setpointOnly.Count) { $summary += " $($setpointOnly.Count) of the flagged differ only in S7_Setpoint attributes (offer them as one group per level)." }
    if ($flagged.Count) { $summary += " Flagged for other differences, show the diff before asking: $($flagged -join ', ')." }
    if ($stale.Count -and (Test-ChangeUpdatedSinceRelease $rec)) { $summary += " $($stale.Count) types were not put in work and are not using the default version of a change type ($($stale -join ', ')): they need a new version too (PLC types: library_edit_type; faceplate types: the user in TIA, Openness crashed TIA on them)." }
    elseif ($stale.Count) { $summary += " $($stale.Count) types are not in work and not using the default version of a change type ($($stale -join ', ')): no update is on record since its last release. library_update_usages puts in work what it can; one it leaves needs a new version." }
    $summary += $(if ($rec.status -eq 'done') { " The change is done. Report: $report." }
                  elseif ($rec.status -eq 'left-behind') { " The work of the change is finished, but it is not done, as types are left on old versions. Report: $report." }
                  else { " Report: $report. Next: ask the user to approve per level (library_approve), then library_release_chain." })
    $levels = [ordered]@{}
    foreach ($n in @($rec.types.Keys | Where-Object { $t = $rec.types[$_]; $t.inWork -and -not $t.releasedAs -and $t.inWorkBy -ne 'change' } |
                     Sort-Object { [int]$rec.types[$_].level }, { $_ })) {
        $t = $rec.types[$n]
        $group = if (-not $t.review) { 'not reviewed' } elseif ($t.review.kind -eq 'setpoint-only') { 'setpoint-only' } else { [string]$t.review.verdict }
        $key = "level $($t.level)"
        if (-not $levels.Contains($key)) { $levels[$key] = [ordered]@{} }
        if (-not $levels[$key].Contains($group)) { $levels[$key][$group] = @() }
        $levels[$key][$group] += $n
    }
    $reviewedResult = @{ ok = $true; summary = $summary; change = $rec.id; report = $report; flagged = $flagged; setpointOnly = $setpointOnly; stale = $stale
                         notCompared = @($by['not-compared'] | Where-Object { $_ } | Sort-Object); toApprove = $levels }
    Add-LeftBehindFacts $reviewedResult $lib $read $rec
    Add-LibraryLog $reviewedResult.summary
    $reviewedResult
}

function Invoke-LibraryApproveTool($a) {
    $null = Get-BridgeSession
    $repo = $script:Bridge.repo
    $rec = Get-LiveChange (Get-TiaLibrary) -Id ([string]$a.change)
    if (-not $rec) { return New-Refusal 'No open library change.' }
    $approve = Get-OptionalBool $a 'approve' $true
    $unknown = @(); $done = @()
    foreach ($n in @($a.types)) {
        if (-not $rec.types.Contains($n) -or $rec.types[$n].inWorkBy -eq 'change') { $unknown += $n; continue }
        $rec.types[$n].approved = $approve; $done += $n
    }
    $report = Save-ChangeRecord $repo $rec
    $open = @($rec.types.Keys | Where-Object { $t = $rec.types[$_]; $t.inWorkBy -ne 'change' -and $t.inWork -and -not $t.releasedAs -and -not $t.approved } | Sort-Object)
    $summary = "$(if ($approve) { 'Approved' } else { 'Approval withdrawn for' }) $($done.Count) types. $($open.Count) types in work are not approved yet. Report: $report."
    if ($unknown.Count) { $summary += " Not types of the change (or the changed type itself): $($unknown -join ', ')." }
    Add-LibraryLog $summary
    @{ ok = -not $unknown.Count; summary = $summary; change = $rec.id; report = $report; notApproved = $open }
}

# A folder that holds only what this makes: a name either tree has already is taken, as TIA's own Find takes it, without case.
function Test-PlcFolderExists($Root, [string]$Path) {
    $g = $Root
    foreach ($part in ($Path -split '/' | Where-Object { $_ })) {
        $g = $g.Groups.Find($part)
        if (-not $g) { return $false }
    }
    $true
}

# The temporary folder: the one asked for, refused when it exists; else a free name. Mine: the folder an earlier call made for this change.
# Returns @{ folder } or @{ refused }. The same name in both trees: blocks in the program blocks, data types in the PLC data types.
function Resolve-TemporaryFolder($Software, [string]$Asked, [string]$Mine, [string[]]$Names = @()) {
    $taken = { param($p) (Test-PlcFolderExists $Software.BlockGroup $p) -or (Test-PlcFolderExists $Software.TypeGroup $p) -or ($Names -contains @($p -split '/')[-1]) }
    if ($Asked) {
        if ($Asked -ine $Mine -and (& $taken $Asked)) { return @{ refused = "The name '$Asked' is taken in this PLC, by a folder, an object or a type about to be made, and the temporary folder holds only what this makes. Name another, or leave folder out for a free name. Nothing was made." } }
        return @{ folder = $Asked }
    }
    if ($Mine) { return @{ folder = $Mine } }
    $free = 'LibraryUpdateTemp'; $n = 2
    while (& $taken $free) { $free = "LibraryUpdateTemp_$n"; $n++ }
    @{ folder = $free }
}

# Every user folder of a PLC, as kind + path: what a call makes shows in the difference.
function Get-PlcFolderPaths($Software) {
    foreach ($part in @(@('block', $Software.BlockGroup), @('type', $Software.TypeGroup))) {
        $stack = New-Object System.Collections.Stack
        foreach ($g in $part[1].Groups) { $stack.Push(@($g, [string]$g.Name)) }
        while ($stack.Count) {
            $e = $stack.Pop()
            "$($part[0])`t$($e[1])"
            foreach ($g in $e[0].Groups) { $stack.Push(@($g, "$($e[1])/$($g.Name)")) }
        }
    }
}

# What came since Before (Get-PlcFolderPaths), as the fields of foldersMade.
function Get-FoldersMadeSince([string[]]$Before, $Entry) {
    foreach ($f in @(Get-PlcFolderPaths $Entry.software)) {
        if ($Before -notcontains $f) { $k, $p = $f -split "`t", 2; @{ kind = $k; folder = $p; device = [string]$Entry.device } }
    }
}

# An F-compliant PLC data type is known by its document only: an export of the version, to look at it. A failure throws: never a pass.
function Test-FCompliantTypeVersion($Entry, $Version) {
    if (-not (Test-PlcDataLibraryType $Entry.obj)) { return $false }
    $dir = Join-Path ([System.IO.Path]::GetTempPath()) "TiaBridge-$([guid]::NewGuid().ToString('N'))"
    New-Item -ItemType Directory -Force -Path $dir | Out-Null
    try {
        $safe = ConvertTo-SafeFileName $Entry.name
        $null = $Version.ExportAsDocuments([System.IO.DirectoryInfo]::new($dir), $safe, 'SimaticSD', [Siemens.Engineering.Library.LibraryExportOptions]::None)
        Test-FBlockDocument (Join-Path $dir "$safe.s7dcl")
    }
    finally { Remove-Item -LiteralPath $dir -Recurse -Force -ErrorAction SilentlyContinue }
}

# Into the change: what was put in work, on the level above what it contains there. The types of the change hold most of them already.
function Add-ChangeLeftBehindTypes($Library, $Record, [string[]]$Names, [hashtable]$InWork, [string[]]$Order, [hashtable]$Deps) {
    $info = @{}; foreach ($i in @(Get-ChangeTypeInfo $Library $Names)) { $info[$i.name] = $i }
    foreach ($n in $Order) {
        if ($Names -notcontains $n) { continue }
        if (-not $Record.types.Contains($n)) {
            $levels = @(@($Deps[$n]) | Where-Object { $Record.types.Contains($_) } | ForEach-Object { [int]$Record.types[$_].level })
            $Record.types[$n] = [ordered]@{ level = $(if ($levels.Count) { 1 + ($levels | Measure-Object -Maximum).Maximum } else { 1 }); kind = (Get-TypeKindLabel $info[$n].class); folder = [string]$info[$n].folder
                                            released = [string]$info[$n].released; inWork = ''; inWorkBy = ''; review = $null; approved = $false; releasedAs = '' }
        }
        $t = $Record.types[$n]
        $t.released = [string]$info[$n].released; $t.inWork = [string]$InWork[$n]; $t.inWorkBy = 'bridge'; $t.releasedAs = ''; $t.approved = $false; $t.review = $null
        $t.stale = @(); $t.noInstance = $false; $t.leftBehind = $false
    }
    $Record.usesOutside = @(@($Record.usesOutside) + @($Names | ForEach-Object { @($Deps[$_]) }) | Where-Object { $_ -and -not $Record.types.Contains($_) } | Sort-Object -Unique)
}

# Yes: an instance of every type on the list, contained types first, as a type made before what it contains would bring that along
# in its library folder and not here; only then all of them in work, as one put in work first would come along as a copy under the
# next one [PROBE] (2026-11-03). A transaction per type: one refused stays on the list and takes along what contains it, the rest go on.
function Invoke-LeftBehindYes($Session, $Library, $Read, [string]$Asked, [string]$Device, [bool]$Safety) {
    $current = Find-CurrentChange $Library
    $entry = Get-TiaSoftwareEntry 'plc' $Device
    $deps = $Read.deps
    $names = @($Read.types | ForEach-Object { $_.type })
    # TIA refuses an object named as the folder it goes into ("An instance with the same name already exists") [PROBE]
    $taken = @($names) + @((Get-PlcObjectRecords).Values | ForEach-Object { $_.object })
    $folder = Resolve-TemporaryFolder $entry.software $Asked ([string]$current.temporaryFolder) $taken
    if ($folder.refused) { return New-Refusal $folder.refused }
    $order = @(Get-ReleaseOrder -DependsOn $deps -Names $names)
    $foldersBefore = @(Get-PlcFolderPaths $entry.software)
    $map = Get-LibraryTypeMap $Library
    $refused = [ordered]@{}
    $instanceStands = New-Object System.Collections.ArrayList
    $standing = New-Object System.Collections.ArrayList
    # without a transaction: named in this result, as the call goes on, and in that of a failure later in it
    $noteStanding = { param($objects)
        foreach ($o in @($objects | Where-Object { $_ })) { [void]$standing.Add($o) }
        if ($standing.Count) { Set-CommittedFact 'objectsStanding' @(ConvertTo-RemovedResult @($standing)) }
    }
    $made = New-Object System.Collections.ArrayList; $brought = New-Object System.Collections.ArrayList; $toEdit = New-Object System.Collections.ArrayList
    foreach ($n in $order) {
        $on = @(@($deps[$n]) | Where-Object { $refused.Contains([string]$_) })
        if ($on.Count) { $refused[$n] = "it contains $($on -join ', '), refused"; continue }
        $e = @{ name = $n; obj = $map[$n]; folder = '' }
        $version = Select-TypeVersion -Versions @($e.obj.Versions)
        try {
            if (Test-TypeObjectHasInstance $e.obj) { [void]$toEdit.Add($n); continue }   # came with what was made before it
            if (-not $Safety -and (Test-FCompliantTypeVersion $e $version)) { $refused[$n] = Get-FBlockRefusal 'library_type' $n 'instance of it'; continue }
            $m = New-TypeInstanceInWork $e $version $folder.folder $Device $Safety -Temporary
        }
        catch {
            if (Test-TiaEndedError $_) { throw }
            $refused[$n] = (ConvertTo-BridgeError $_).message
            # a transaction took it back; without one what it did stands, and the save rules hold it
            Register-ObjectsStanding $Session @{ standing = $_.Exception.Data['standing'] }
            & $noteStanding $_.Exception.Data['standing']
            if (Test-TypeObjectHasInstance $e.obj) { Register-LibraryTypeWrite $Session 'plc' @($entry.device) "type:$n" $false; [void]$instanceStands.Add([string]$n) }
            continue
        }
        if ($m.refused) {
            Register-ObjectsStanding $Session $m
            & $noteStanding $m.standing
            $refused[$n] = $m.refused
            if (@($m.standing | Where-Object { $_.type -eq $n }).Count) { [void]$instanceStands.Add([string]$n) }
            continue
        }
        if ($m.commitError) { $refused[$n] = "TIA refused the commit: $($m.commitError.message)"; continue }
        foreach ($o in $m.objects) { Register-Write $Session -Scope 'plc' -Device $o.device -Items @(@{ name = $o.object; ok = $true }) }
        [void]$made.Add($m.instance)
        foreach ($c in @($m.copies)) { [void]$brought.Add($c) }
        [void]$toEdit.Add($n)
    }
    $inWork = @{}
    foreach ($n in $toEdit) {
        $version = Select-TypeVersion -Versions @($map[$n].Versions)
        try {
            # Edit of a type that has a version in work ended TIA [PROBE] (2026-11-03): the version in work is the one to go on with
            if (-not (Select-TypeVersion -Versions @($map[$n].Versions) -InWork)) {
                $null = Invoke-TiaWrite "edit library type $n" { $version.Edit(@($version.FindInstances($entry.software))[0]) }
            }
            $work = Select-TypeVersion -Versions @($map[$n].Versions) -InWork
            $inWork[$n] = [string]$work.VersionNumber
            Register-LibraryTypeWrite $Session 'plc' @($entry.device) "type:$n" $true
        }
        catch {
            if (Test-TiaEndedError $_) { throw }
            $refused[$n] = "could not be put in work: $((ConvertTo-BridgeError $_).message)"
            [void]$instanceStands.Add([string]$n)
            Register-LibraryTypeWrite $Session 'plc' @($entry.device) "type:$n" $false
        }
    }
    $done = @($order | Where-Object { $inWork.ContainsKey($_) })
    $record = $current
    if (-not $record) { $record = New-LeftBehindRecord (Get-Date) }
    $record.leftBehindAnswer = 'yes'
    $record.leftBehindAsked = @($names)
    $record.leftBehindRefused = @{}; foreach ($n in $refused.Keys) { $record.leftBehindRefused[$n] = [string]$refused[$n] }
    if ($done.Count) {
        Add-ChangeLeftBehindTypes $Library $record $done $inWork $order $deps
        $record.temporaryFolder = $folder.folder
        $record.Remove('foldersUnread')
        $foldersNow = @(Get-PlcFolderPaths $entry.software)
        # what an earlier call made and a close without saving took back is no longer one to delete
        $kept = @(@($record.foldersMade | Where-Object { $_ }) | Where-Object { $foldersNow -contains "$($_.kind)`t$($_.folder)" })
        $keptKeys = @($kept | ForEach-Object { "$($_.kind)`t$($_.folder)" })
        $came = @(Get-FoldersMadeSince (@($foldersBefore) + @($keptKeys)) $entry)
        $record.foldersMade = @($kept) + $came
    }
    $read = Read-LeftBehind $Library
    Set-RecordLeftBehind $record $read
    $report = Save-ChangeRecord $script:Bridge.repo $record
    $moves = @(@($done | ForEach-Object { @($deps[$_]) }) + @($brought | ForEach-Object { $_.type }) | Where-Object { $_ -and $done -notcontains $_ } | Sort-Object -Unique)
    $list = @($done | Select-Object -First 10 | ForEach-Object { "'$_'" }) + @(if ($done.Count -gt 10) { "and $($done.Count - 10) more" })
    $movesShown = "types=[$(@($moves | Select-Object -First 10 | ForEach-Object { "'$_'" }) -join ', ')]$(if ($moves.Count -gt 10) { " and $($moves.Count - 10) more (updateTypes)" })"
    $next = $(if ($done.Count) {
        "compile, library_update_usages$(if ($moves.Count) { " with $movesShown" }), compile, library_review, ask the user to approve per level (library_approve), library_release_chain, until the change is done. " +
        'An export of one of them before that update reads the names of the copies. Once they are released TIA removes the temporary instances at the update, named in instancesRemoved.'
    } else { 'Nothing was put in work.' })
    $summary = "Answer yes to the types left on old versions: $($done.Count) of $($names.Count) in work$(if ($done.Count) { " ($($list -join ', ')), with their instances in the temporary folder $($folder.folder)" })."
    if ($brought.Count) { $summary += " Made with them, as they were built on older versions of what they contain: $(Format-RemovedList @($brought | Select-Object -First 10))$(if ($brought.Count -gt 10) { " and $($brought.Count - 10) more (copiesMade)" }); the project holds two versions of those until the update." }
    $summary += Format-NumbersMoved (@($made) + @($brought))
    $foldersNamed = @($record.foldersMade | Where-Object { $_ })
    if ($foldersNamed.Count) { $summary += " Folders made: $(Format-FoldersCapped $foldersNamed 'foldersMade')." }
    $sayRefused = { param($names) "$(@($names | Select-Object -First 10 | ForEach-Object { "$_ ($(Limit-Text ([string]$refused[$_]) 100))" }) -join '; ')$(if (@($names).Count -gt 10) { " and $(@($names).Count - 10) more (typesRefused)" })" }
    $staysListed = @($refused.Keys | Where-Object { $instanceStands -notcontains $_ })
    if ($staysListed.Count) { $summary += " Refused, they stay on the list and the change is not done: $(& $sayRefused $staysListed)." }
    if ($standing.Count) { $summary += " Without a transaction these stand, held for the save until each is deleted or written again: $(@($standing | Select-Object -First 10 | ForEach-Object { $_.object }) -join ', ')$(if ($standing.Count -gt 10) { " and $($standing.Count - 10) more (objectsStanding)" })." }
    if ($instanceStands.Count) { $summary += " Not put in work, though an instance stands, so off the list until an update moves or removes it: $(& $sayRefused @($instanceStands))." }
    $summary += " Report: $report. Next: $next"
    Add-LibraryLog $summary
    $r = [ordered]@{ ok = -not $refused.Count; summary = $summary; change = $record.id; report = $report; folder = $folder.folder; inWork = @($done | ForEach-Object { @{ type = $_; inWork = $inWork[$_] } })
                     instancesMade = @(ConvertTo-RemovedResult @($made)); next = $next }
    if ($brought.Count) { $r.copiesMade = @(ConvertTo-RemovedResult @($brought)) }
    if (@($record.foldersMade | Where-Object { $_ }).Count) { $r.foldersMade = @($record.foldersMade) }
    if ($moves.Count) { $r.updateTypes = @($moves) }
    if ($standing.Count) { $r.objectsStanding = @(ConvertTo-RemovedResult @($standing)) }
    if ($refused.Count) {
        $r.typesRefused = @($refused.Keys | ForEach-Object {
            $one = @{ type = [string]$_; why = [string]$refused[$_] }
            if ($instanceStands -contains $_) { $one.instanceStands = $true }
            $one
        })
    }
    Add-LeftBehindFacts $r $Library $read $record
    $r
}

function New-LeftBehindRecord([datetime]$At) {
    $r = [ordered]@{ id = (New-ChangeId 'left-behind' $At); root = ''; from = ''; to = ''; started = $At.ToString('yyyy-MM-dd HH:mm'); status = 'open'; updated = $true; types = [ordered]@{} }
    $r.id = Get-FreeChangeId $script:Bridge.repo $r.id
    $r
}

# The user's answer to the question a change ends with. The tool decides nothing: no answer, no call.
function Invoke-LibraryLeftBehindTool($a) {
    $session = Get-BridgeSession
    $gate = Test-WriteAllowed $session
    if ($gate) { return New-Refusal $gate }
    $answer = [string]$a.answer
    if ($answer -notin 'yes', 'no') { return New-Refusal "answer is required: yes or no, what the user said. Nothing was changed." }
    $null = Get-TiaProject   # binds the repo
    if (-not $script:Bridge.repo) { return New-Refusal 'A library change keeps its record in the project repo, and this session has none. Nothing was changed.' }
    $lib = Get-TiaLibrary
    $open = Get-LiveChange $lib
    if ($open) {
        $w = Get-InWorkTypes $lib
        if (-not $w.complete) { return New-Refusal "The library walk stopped after $($w.walked) types (time limit), so what is in work is not known. Nothing was changed." }
        Clear-ChangeInWorkGone $open @($w.types | ForEach-Object { $_.type })
        $null = Save-ChangeRecord $script:Bridge.repo $open
        # on what is still in work the instances would sit on versions about to go old
        $busy = @($open.types.Keys | Where-Object { $open.types[$_].inWork -and -not $open.types[$_].releasedAs } | Sort-Object)
        if ($busy.Count -or $open.updateOutstanding) {
            return New-Refusal "Library change $($open.id) has not reached its end$(if ($busy.Count) { ": in work unreleased: $($busy -join ', ')" } else { ': the project is not updated to the released types' }). The question is for its end. Nothing was changed."
        }
    }
    $read = Read-LeftBehind $lib
    if ($read.failed -or $read.unread) { return New-Refusal "Which types are left on old versions is not known: $($read.unread). Nothing was changed." }
    if (-not @($read.types).Count) {
        $null = Update-ChangesLeftBehind $lib $read
        return @{ ok = $true; summary = 'No type is left on old versions: nothing to do.' ; next = '' }
    }
    if ($answer -eq 'yes') { return Invoke-LeftBehindYes $session $lib $read ([string]$a.folder) ([string]$a.device) ($a.safety -eq $true) }
    $record = Find-CurrentChange $lib
    if (-not $record) { $record = New-LeftBehindRecord (Get-Date) }
    $record.leftBehindAnswer = 'no'
    $record.leftBehindAsked = @($read.types | ForEach-Object { $_.type })
    Set-RecordLeftBehind $record $read
    $report = Save-ChangeRecord $script:Bridge.repo $record
    $next = Format-ChangeEndNext $record
    $summary = "Answer no: library change $($record.id) ends with $(@($read.types).Count) types left on old versions. Report: $report. Next: $next"
    Add-LibraryLog $summary
    $r = [ordered]@{ ok = $true; summary = $summary; change = $record.id; report = $report; status = $record.status; next = $next }
    Add-LeftBehindFacts $r $lib $read $record
    $r
}

function Register-LibraryChangeTools {
    Register-McpTool -Name 'library_left_behind' -Handler { param($a) Invoke-LibraryLeftBehindTool $a } -Description (
        'The user''s answer to the question a library change ends with, when typesLeftBehind names types left on old versions: they have no instance, so no update moves them. Call it only with what the user said. ' +
        'A yes costs a new version of every type on the list, which is of the whole library, also of older changes and of a type that would move by itself, each through review and approval: say so when asking. ' +
        'answer yes: an instance of every type on the list goes into one temporary folder (folder, refused when it exists; default a free name, in the program blocks and, for data types, in the PLC data types) and each is put in work and joins the change; copies name_1 of what they contain come on old versions, in the library''s folder paths (copiesMade, foldersMade). Blocks of the user''s own are not touched: a call that would change one is taken back. ' +
        'Then compile, library_update_usages, compile, library_review, the user''s approvals, library_release_chain, as any reviewed change. Once they are released TIA removes the temporary instances at the update (instancesRemoved); delete_folder takes the empty folders. ' +
        'A type refused on the way (an F-block or F-compliant data type without safety: true, a know-how protected one, a failed write) and what contains it stay on the list (typesRefused), and the change is not done; one with instanceStands there has its instance and could not be put in work, so it is off the list until an update moves or removes it. updateTypes holds the types for the update when next names only ten. Without a transaction objectsStanding names what a refused type left in the PLC, held for the save. ' +
        'answer no: the change ends as left-behind, not done, and every result, its report and library_review list the types for as long as they stand. An answer covers the list as it stood: a type that comes on it later is asked about. A yes a close without saving took out of the project leaves the record: the question stands again. Refused while the change still has types in work.') -Schema @{
        type = 'object'; required = @('answer')
        properties = @{ answer = @{ type = 'string'; enum = @('yes', 'no'); description = 'what the user said' }
                        folder = @{ type = 'string'; description = 'answer yes: the temporary folder, with /, when the user names one; it must not exist' }
                        device = @{ type = 'string'; description = 'the PLC for the instances; needed only when the project has several' }
                        safety = $script:SafetyArgument } }

    Register-McpTool -Name 'library_review' -Handler { param($a) Invoke-LibraryReviewTool $a } -Description (
        'Review the types of the open library change: export the version in work and the released version of each type in work (SimaticSD, ' +
        'else SimaticML) and compare them. "reference only" = it differs only in the versions of change types it uses; anything else is flagged ' +
        'with a diff file. Writes the verdicts into the change report (library\changes\<id>.md). typesLeftBehind names the types with no instance still on old versions, also with no change open, and at the end of a change the user is asked about them (library_left_behind). Reviews the types not reviewed yet; again=true ' +
        'reviews all, types=[...] only those. Then ask the user to approve per type.') -Schema @{
        type = 'object'
        properties = @{ change = @{ type = 'string'; description = 'change id; default the open one' }
                        types = @{ type = 'array'; items = @{ type = 'string' } }; again = @{ type = 'boolean' } } }

    Register-McpTool -Name 'library_approve' -Handler { param($a) Invoke-LibraryApproveTool $a } -Description (
        'Approve types of the open library change for release (ticks their boxes in the change report), or withdraw it with approve=false. ' +
        'Only for types the user approved: ask the user per level, or let the user tick the report.') -Schema @{
        type = 'object'; required = @('types')
        properties = @{ types = @{ type = 'array'; items = @{ type = 'string' } }; approve = @{ type = 'boolean' }
                        change = @{ type = 'string'; description = 'change id; default the open one' } } }
}
