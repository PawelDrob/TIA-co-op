# OkfBundle.ps1 - checks a documentation bundle against OKF v0.2 and the conventions in README.md, and writes its index.md files.
# OKF v0.2: https://github.com/GoogleCloudPlatform/open-knowledge-format/blob/main/SPEC.md

$script:Utf8NoBom = New-Object System.Text.UTF8Encoding $false
$script:Reserved = 'index.md', 'log.md'
$script:Statuses = 'draft', 'stable', 'deprecated'
$script:TimestampRx = '^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}(:\d{2}(\.\d+)?)?(Z|[+-]\d{2}:\d{2})$'
$script:ActorRx = '^((human|process|team):\S+|[^\s:/]+/[^\s/]+)$'
$script:FileNameRx = '^[a-z0-9]+(-[a-z0-9]+)*\.md$'
$script:TagRx = '^[a-z0-9]+(-[a-z0-9]+)*(/[a-z0-9]+(-[a-z0-9]+)*)*$'

#region YAML subset
# Frontmatter is read as a YAML subset: block maps and lists, flow maps and lists, plain and quoted scalars.
# Everything else (block scalars, anchors, tags, multi-line flows) throws, so it is reported instead of misread.
# Scalars stay strings: a timestamp is checked as written, not as whatever a YAML library would turn it into.

function Remove-YamlComment([string]$Text) {
    $q = $null
    for ($i = 0; $i -lt $Text.Length; $i++) {
        $c = $Text[$i]
        if ($q) { if ($c -eq $q) { $q = $null } }
        elseif ($c -eq '"' -or $c -eq "'") { $q = $c }
        elseif ($c -eq '#' -and ($i -eq 0 -or $Text[$i - 1] -match '\s')) { return $Text.Substring(0, $i).TrimEnd() }
    }
    $Text
}

function ConvertFrom-OkfYaml([string[]]$Lines, [int]$FirstLine = 1) {
    $items = New-Object System.Collections.ArrayList
    for ($i = 0; $i -lt $Lines.Count; $i++) {
        $l = $Lines[$i]
        if ($l -match '^\s*(#|$)') { continue }
        $n = $FirstLine + $i
        if ($l -match '^ *\t') { throw "line ${n}: tab in indentation" }
        $t = Remove-YamlComment $l.Trim()
        [void]$items.Add([pscustomobject]@{ indent = $l.Length - $l.TrimStart(' ').Length; text = $t; line = $n })
    }
    $map = [ordered]@{}
    if (-not $items.Count) { return $map }
    $pos = [ref]0
    if ($items[0].indent -ne 0 -or $items[0].text -match '^-( |$)') { throw "line $($items[0].line): frontmatter must be a map of keys" }
    $map = Read-YamlMap $items $pos 0
    if ($pos.Value -lt $items.Count) { throw "line $($items[$pos.Value].line): unexpected indentation" }
    $map
}

function Test-YamlListItem($Item) { $Item.text -match '^-( |$)' }

function Read-YamlBlock($Items, [ref]$Pos) {
    $first = $Items[$Pos.Value]
    if (Test-YamlListItem $first) { , (Read-YamlList $Items $Pos $first.indent) } else { Read-YamlMap $Items $Pos $first.indent }
}

function Read-YamlMap($Items, [ref]$Pos, [int]$Indent) {
    $map = [ordered]@{}
    while ($Pos.Value -lt $Items.Count) {
        $it = $Items[$Pos.Value]
        if ($it.indent -lt $Indent) { break }
        if ($it.indent -gt $Indent) { throw "line $($it.line): unexpected indentation" }
        if (Test-YamlListItem $it) { throw "line $($it.line): list item where a key was expected" }
        if ($it.text -notmatch '^([^\s:"''\[{#-][^:]*?|-[^\s:][^:]*?)\s*:(\s+(.*))?$') { throw "line $($it.line): expected 'key: value'" }
        $key = $Matches[1]; $raw = $Matches[3]
        if ($map.Contains($key)) { throw "line $($it.line): duplicate key '$key'" }
        $Pos.Value++
        $next = if ($Pos.Value -lt $Items.Count) { $Items[$Pos.Value] }
        if ($raw) { $map[$key] = ConvertFrom-YamlValue $raw $it.line }
        elseif ($next -and ($next.indent -gt $Indent -or ($next.indent -eq $Indent -and (Test-YamlListItem $next)))) { $map[$key] = Read-YamlBlock $Items $Pos }
        else { $map[$key] = $null }
    }
    $map
}

function Read-YamlList($Items, [ref]$Pos, [int]$Indent) {
    $list = New-Object System.Collections.ArrayList
    while ($Pos.Value -lt $Items.Count) {
        $it = $Items[$Pos.Value]
        if ($it.indent -lt $Indent -or ($it.indent -eq $Indent -and -not (Test-YamlListItem $it))) { break }
        if ($it.indent -gt $Indent) { throw "line $($it.line): unexpected indentation" }
        $rest = $it.text -replace '^-\s*', ''
        if (-not $rest) {
            $Pos.Value++
            $next = if ($Pos.Value -lt $Items.Count) { $Items[$Pos.Value] }
            if ($next -and $next.indent -gt $Indent) { [void]$list.Add((Read-YamlBlock $Items $Pos)) } else { [void]$list.Add($null) }
        }
        elseif ($rest -match '^[^\s:"''\[{#][^:]*?\s*:(\s|$)') {
            # "- key: value" opens a block map whose keys line up with "key".
            $offset = $it.indent + $it.text.Length - $rest.Length
            $Items[$Pos.Value] = [pscustomobject]@{ indent = $offset; text = $rest; line = $it.line }
            [void]$list.Add((Read-YamlMap $Items $Pos $offset))
        }
        else { $Pos.Value++; [void]$list.Add((ConvertFrom-YamlValue $rest $it.line)) }
    }
    , $list.ToArray()
}

function ConvertFrom-YamlValue([string]$Raw, [int]$Line) {
    $t = $Raw.Trim()
    if ($t -match '^[\[{]') {
        $p = [ref]0
        $v = Read-YamlFlow $t $p $Line
        if ($t.Substring($p.Value).Trim()) { throw "line ${Line}: text after the closing bracket" }
        return , $v
    }
    if ($t -match '^[|>&*!%@`]') { throw "line ${Line}: '$($t[0])' (block scalar, anchor, alias or tag) is outside the supported YAML subset" }
    ConvertFrom-YamlScalar $t $Line
}

function ConvertFrom-YamlScalar([string]$Text, [int]$Line) {
    if ($Text -match '^"(.*)"$') { return ($Matches[1] -replace '\\"', '"' -replace '\\\\', '\') }
    if ($Text -match "^'(.*)'$") { return ($Matches[1] -replace "''", "'") }
    if ($Text -match '^["'']') { throw "line ${Line}: unterminated quote" }
    if ($Text -match ':\s') { throw "line ${Line}: ': ' inside a plain value; quote the value" }
    $Text
}

function Skip-FlowSpace([string]$S, [ref]$P) { while ($P.Value -lt $S.Length -and $S[$P.Value] -match '\s') { $P.Value++ } }

function Read-YamlFlow([string]$S, [ref]$P, [int]$Line) {
    Skip-FlowSpace $S $P
    if ($P.Value -ge $S.Length) { throw "line ${Line}: flow value is not closed (flows must stay on one line)" }
    $open = $S[$P.Value]
    if ($open -eq '[' -or $open -eq '{') {
        $close = if ($open -eq '[') { ']' } else { '}' }
        $P.Value++
        $list = New-Object System.Collections.ArrayList
        $map = [ordered]@{}
        while ($true) {
            Skip-FlowSpace $S $P
            if ($P.Value -ge $S.Length) { throw "line ${Line}: flow value is not closed (flows must stay on one line)" }
            if ($S[$P.Value] -eq $close) { $P.Value++; break }
            if ($open -eq '[') { [void]$list.Add((Read-YamlFlow $S $P $Line)) }
            else {
                $key = Read-FlowScalar $S $P $Line $true
                Skip-FlowSpace $S $P
                if ($P.Value -ge $S.Length -or $S[$P.Value] -ne ':') { throw "line ${Line}: expected ':' after '$key'" }
                $P.Value++
                if ($map.Contains($key)) { throw "line ${Line}: duplicate key '$key'" }
                $map[$key] = Read-YamlFlow $S $P $Line
            }
            Skip-FlowSpace $S $P
            if ($P.Value -ge $S.Length) { throw "line ${Line}: flow value is not closed (flows must stay on one line)" }
            if ($S[$P.Value] -eq ',') { $P.Value++ }
            elseif ($S[$P.Value] -ne $close) { throw "line ${Line}: expected ',' or '$close'" }
        }
        if ($open -eq '[') { return , $list.ToArray() } else { return $map }
    }
    Read-FlowScalar $S $P $Line $false
}

function Read-FlowScalar([string]$S, [ref]$P, [int]$Line, [bool]$IsKey) {
    $start = $P.Value
    $q = $S[$start]
    if ($q -eq '"' -or $q -eq "'") {
        $i = $start + 1
        while ($i -lt $S.Length) {
            if ($S[$i] -eq '\' -and $q -eq '"') { $i += 2; continue }
            if ($S[$i] -eq $q) { if ($q -eq "'" -and $i + 1 -lt $S.Length -and $S[$i + 1] -eq "'") { $i += 2; continue } else { break } }
            $i++
        }
        if ($i -ge $S.Length) { throw "line ${Line}: unterminated quote" }
        $P.Value = $i + 1
        return ConvertFrom-YamlScalar $S.Substring($start, $i - $start + 1) $Line
    }
    $i = $start
    while ($i -lt $S.Length) {
        $c = $S[$i]
        if ($c -eq ',' -or $c -eq ']' -or $c -eq '}') { break }
        if ($IsKey -and $c -eq ':' -and ($i + 1 -ge $S.Length -or $S[$i + 1] -match '[\s,}\]]')) { break }
        $i++
    }
    $P.Value = $i
    $t = $S.Substring($start, $i - $start).Trim()
    if ($t -match '^[&*!|>%@`]') { throw "line ${Line}: '$($t[0])' is outside the supported YAML subset" }
    $t
}
#endregion

#region Reading
# Returns @{ meta; body; bodyLine (1-based line of the first body line); error; hasFrontmatter }.
function Read-OkfConcept([string]$Path) {
    $text = [System.IO.File]::ReadAllText($Path).TrimStart([char]0xFEFF)
    $lines = $text -split '\r?\n'
    $r = @{ meta = $null; body = $text; bodyLine = 1; error = $null; hasFrontmatter = $false }
    if ($lines[0] -ne '---') { $r.error = 'no frontmatter: the file must start with a --- line'; return $r }
    $end = -1
    for ($i = 1; $i -lt $lines.Count; $i++) { if ($lines[$i] -eq '---') { $end = $i; break } }
    if ($end -lt 0) { $r.error = 'frontmatter is not closed by a --- line'; return $r }
    $r.hasFrontmatter = $true
    $r.body = if ($end + 1 -lt $lines.Count) { $lines[($end + 1)..($lines.Count - 1)] -join "`n" } else { '' }
    $r.bodyLine = $end + 2
    $r.meta = [ordered]@{}
    if ($end -gt 1) {
        try { $r.meta = ConvertFrom-OkfYaml $lines[1..($end - 1)] 2 }
        catch { $r.meta = $null; $r.error = "frontmatter is not readable YAML: $($_.Exception.Message)" }
    }
    $r
}

# Blanks fenced code blocks and inline code, keeping line numbers, so links and markers inside code are ignored.
function Remove-MarkdownCode([string]$Body) {
    $out = New-Object System.Collections.ArrayList
    $fence = $null
    foreach ($l in ($Body -split '\r?\n')) {
        if ($fence) { if ($l -match "^\s*$fence") { $fence = $null }; [void]$out.Add(''); continue }
        if ($l -match '^\s*(```+|~~~+)') { $fence = [regex]::Escape($Matches[1]); [void]$out.Add(''); continue }
        [void]$out.Add(($l -replace '(`+)(?:(?!\1).)+?\1', ''))
    }
    , $out.ToArray()
}

# Returns one @{ target; line; image } per markdown link, reference definition or wikilink outside code.
function Get-MarkdownLinks([string]$Body, [int]$FirstLine) {
    $lines = Remove-MarkdownCode $Body
    for ($i = 0; $i -lt $lines.Count; $i++) {
        $l = $lines[$i]
        foreach ($m in [regex]::Matches($l, '(!?)\[[^\]]*\]\(\s*(<[^>]+>|[^)\s]+)(\s+"[^"]*")?\s*\)')) {
            @{ target = $m.Groups[2].Value.Trim('<', '>'); line = $FirstLine + $i; kind = 'link' }
        }
        if ($l -match '^\s{0,3}\[([^\]^][^\]]*)\]:\s*(<[^>]+>|\S+)') { @{ target = $Matches[2].Trim('<', '>'); line = $FirstLine + $i; kind = 'link' } }
        foreach ($m in [regex]::Matches($l, '\[\[([^\]]+)\]\]')) { @{ target = $m.Groups[1].Value; line = $FirstLine + $i; kind = 'wikilink' } }
    }
}

function Get-BundleFiles([string]$Root) {
    $rootFull = (Resolve-Path $Root).Path.TrimEnd('\')
    Get-ChildItem -Path $rootFull -Recurse -File -Filter *.md -Force | Where-Object {
        $rel = $_.FullName.Substring($rootFull.Length + 1)
        -not ($rel -split '\\' | Where-Object { $_ -like '.*' })
    } | Sort-Object FullName
}

function Get-RelativePath([string]$Root, [string]$Full) { $Full.Substring($Root.TrimEnd('\').Length + 1) -replace '\\', '/' }
#endregion

#region Checks
function New-Finding([string]$Level, [string]$Rule, [string]$File, [int]$Line, [string]$Message) {
    [pscustomobject]@{ level = $Level; rule = $Rule; file = $File; line = $Line; message = $Message }
}

function Test-Timestamp($Value) { $Value -is [string] -and $Value -match $script:TimestampRx }

function Get-AsList($Value) {
    if ($null -eq $Value) { return , @() }
    if ($Value -is [System.Collections.IDictionary] -or $Value -isnot [array]) { return , @($Value) }
    , $Value
}

# Errors are OKF v0.2 conformance (spec section 11) or rules of the conventions (README.md); warnings are drift worth fixing.
# -Types: the type vocabulary (types.md); a type outside it is a warning, since OKF itself allows any type.
function Test-OkfBundle([string]$Path, [string[]]$Types = @(), [datetime]$Now = [datetime]::UtcNow, [switch]$NoGit) {
    $root = (Resolve-Path $Path).Path.TrimEnd('\')
    $files = @(Get-BundleFiles $root)
    $concepts = @{}
    foreach ($f in $files) {
        $rel = Get-RelativePath $root $f.FullName
        if ($script:Reserved -contains $f.Name) { continue }
        $c = Read-OkfConcept $f.FullName
        $concepts[$rel] = $c
        if ($f.Name -cnotmatch $script:FileNameRx) { New-Finding Error file-name $rel 0 "file name must be kebab-case: lower-case letters, digits and single hyphens" }
        if ($c.error) { New-Finding Error frontmatter $rel 1 $c.error; continue }
        Test-ConceptMeta $rel $c $Types $Now
        Test-ConceptBody $root $f.FullName $rel $c
    }
    foreach ($f in $files | Where-Object { $_.Name -eq 'index.md' }) { Test-IndexFile $root $f.FullName $concepts }
    foreach ($f in $files | Where-Object { $_.Name -eq 'log.md' }) { Test-LogFile $root $f.FullName }
    foreach ($dir in Get-ConceptDirectories $root $files) {
        if (-not (Test-Path (Join-Path $dir 'index.md'))) {
            $d = if ($dir -eq $root) { '.' } else { Get-RelativePath $root $dir }
            New-Finding Warning index-absent "$d/index.md" 0 'folder has documents but no index.md (run with -WriteIndex)'
        }
    }
    if (-not $NoGit) {
        Clear-GitContext
        foreach ($rel in $concepts.Keys | Sort-Object) { Test-GeneratedUpdated $root $rel $concepts[$rel] }
    }
}

function Test-ConceptMeta([string]$Rel, $C, [string[]]$Types, [datetime]$Now) {
    $m = $C.meta
    $type = $m['type']
    if (-not ($type -is [string]) -or -not $type.Trim()) { New-Finding Error type $Rel 2 "'type' is missing or empty (the one field OKF requires)"; return }
    if ($Types.Count -and $Types -notcontains $type) { New-Finding Warning type-vocabulary $Rel 2 "type '$type' is not in types.md: $($Types -join ', ')" }
    if ($type -eq 'Template') {
        # A document made from the template keeps type Template until its author changes it.
        if ($Rel -notmatch '^templates/') { New-Finding Error template-type $Rel 2 "type 'Template' outside templates/: give the document its own type" }
        return
    }
    foreach ($k in 'title', 'description') {
        if (-not ($m[$k] -is [string]) -or -not $m[$k].Trim()) { New-Finding Error $k $Rel 2 "'$k' is required by the conventions (tools/okf/README.md)" }
    }
    if ($m.Contains('tags')) {
        foreach ($t in (Get-AsList $m['tags'])) { if (-not ($t -is [string]) -or $t -cnotmatch $script:TagRx) { New-Finding Warning tags $Rel 2 "tag '$t' must be kebab-case (tags.md)" } }
    }
    if ($m.Contains('status') -and $script:Statuses -notcontains $m['status']) { New-Finding Error status $Rel 2 "status '$($m['status'])' must be one of: $($script:Statuses -join ', ')" }
    $g = $m['generated']
    if (-not $m.Contains('generated')) { New-Finding Error generated $Rel 2 "'generated: { by, at }' is required by the conventions (tools/okf/README.md)" }
    elseif ($g -isnot [System.Collections.IDictionary]) { New-Finding Error generated $Rel 2 "'generated' must be a map { by, at }" }
    else {
        if ($g['by'] -notmatch $script:ActorRx) { New-Finding Error actor $Rel 2 "generated.by '$($g['by'])' is not an actor (human:<id>, process:<id>, <producer>/<version>)" }
        if (-not (Test-Timestamp $g['at'])) { New-Finding Error timestamp $Rel 2 "generated.at '$($g['at'])' must be an ISO 8601 datetime with an offset, e.g. 2026-10-04T00:00:00Z" }
    }
    if ($m.Contains('verified')) {
        foreach ($v in (Get-AsList $m['verified'])) {
            if ($v -isnot [System.Collections.IDictionary]) { New-Finding Error verified $Rel 2 "each 'verified' entry must be a map { by, at }"; continue }
            if ($v['by'] -notmatch $script:ActorRx) { New-Finding Error actor $Rel 2 "verified.by '$($v['by'])' is not an actor" }
            if (-not (Test-Timestamp $v['at'])) { New-Finding Error timestamp $Rel 2 "verified.at '$($v['at'])' must be an ISO 8601 datetime with an offset" }
        }
    }
    if ($m.Contains('stale_after')) {
        if (-not (Test-Timestamp $m['stale_after'])) { New-Finding Error timestamp $Rel 2 "stale_after '$($m['stale_after'])' must be an ISO 8601 datetime with an offset" }
        elseif ([datetimeoffset]::Parse($m['stale_after']).UtcDateTime -le $Now) { New-Finding Warning stale $Rel 2 "stale since $($m['stale_after']): review it, then move stale_after or deprecate it" }
    }
    $ids = @{}
    foreach ($s in (Get-AsList $m['sources'])) {
        if ($s -isnot [System.Collections.IDictionary] -or -not $s['resource']) { New-Finding Error sources $Rel 2 "each 'sources' entry must be a map with a 'resource'"; continue }
        if ($s['id']) { if ($ids.ContainsKey($s['id'])) { New-Finding Error sources $Rel 2 "duplicate source id '$($s['id'])'" } else { $ids[$s['id']] = $true } }
        if ($s.Contains('last_modified') -and -not (Test-Timestamp $s['last_modified'])) { New-Finding Error timestamp $Rel 2 "sources.last_modified '$($s['last_modified'])' must be an ISO 8601 datetime with an offset" }
        if ($s.Contains('author') -and $s['author'] -notmatch $script:ActorRx) { New-Finding Warning actor $Rel 2 "sources.author '$($s['author'])' is not an actor" }
    }
    $C.sourceIds = $ids
}

function Test-ConceptBody([string]$Root, [string]$Full, [string]$Rel, $C) {
    $lines = Remove-MarkdownCode $C.body
    $defs = @{}
    foreach ($l in $lines) { if ($l -match '^\[\^([^\]]+)\]:') { $defs[$Matches[1]] = $true } }
    for ($i = 0; $i -lt $lines.Count; $i++) {
        foreach ($m in [regex]::Matches($lines[$i], '\[\^([^\]]+)\](?!:)')) {
            $id = $m.Groups[1].Value
            if (-not ($C.sourceIds -and $C.sourceIds.ContainsKey($id))) { New-Finding Warning footnote $Rel ($C.bodyLine + $i) "footnote [^$id] has no 'sources' entry with id '$id'" }
        }
    }
    Test-Links $Root $Full $Rel $C.body $C.bodyLine
}

function Test-Links([string]$Root, [string]$Full, [string]$Rel, [string]$Body, [int]$FirstLine) {
    $dir = Split-Path -Parent $Full
    foreach ($l in (Get-MarkdownLinks $Body $FirstLine)) {
        $t = $l.target
        if ($l.kind -eq 'wikilink') { New-Finding Error link-style $Rel $l.line "[[${t}]] is a wikilink; use a relative markdown link (turn off 'Use [[Wikilinks]]' in Obsidian)"; continue }
        if ($t -match '^[a-zA-Z][a-zA-Z0-9+.-]*:' -or $t -match '^#') { continue }
        if ($t -match '^/') { New-Finding Error link-style $Rel $l.line "'$t' is bundle-absolute; the conventions use relative links (GitHub and VS Code read / as the repo root)"; continue }
        $p = [uri]::UnescapeDataString(($t -replace '[#?].*$', ''))
        if (-not $p) { continue }
        $target = Join-Path $dir ($p -replace '/', '\')
        if (-not (Test-Path -LiteralPath $target)) { New-Finding Error broken-link $Rel $l.line "link target '$t' does not exist" }
        elseif ((Test-Path -LiteralPath $target -PathType Container)) { New-Finding Warning folder-link $Rel $l.line "'$t' links a folder, which Obsidian cannot open; link its index.md" }
    }
}

function Get-ConceptDirectories([string]$Root, $Files) {
    $dirs = @{}
    foreach ($f in $Files) {
        $d = $f.DirectoryName
        while ($d.Length -ge $Root.Length) { $dirs[$d] = $true; if ($d -eq $Root) { break }; $d = Split-Path -Parent $d }
    }
    $dirs.Keys | Sort-Object
}

# index.md: no frontmatter except okf_version at the bundle root; headings and "* [Title](link) - description" lines.
function Test-IndexFile([string]$Root, [string]$Full, $Concepts) {
    $rel = Get-RelativePath $Root $Full
    $c = Read-OkfConcept $Full
    $isRoot = (Split-Path -Parent $Full) -eq $Root
    if ($c.hasFrontmatter) {
        if ($c.error) { New-Finding Error index-frontmatter $rel 1 $c.error }
        elseif (-not $isRoot) { New-Finding Error index-frontmatter $rel 1 'only the bundle-root index.md may have frontmatter (okf_version)' }
        else {
            foreach ($k in $c.meta.Keys) { if ($k -ne 'okf_version') { New-Finding Error index-frontmatter $rel 1 "index.md frontmatter may only hold okf_version, found '$k'" } }
        }
    }
    else { $c.body = [System.IO.File]::ReadAllText($Full).TrimStart([char]0xFEFF); $c.bodyLine = 1 }
    if ($isRoot -and -not ($c.meta -and $c.meta['okf_version'])) { New-Finding Warning okf-version $rel 1 "root index.md should declare okf_version: `"0.2`"" }
    $lines = $c.body -split '\r?\n'
    $linked = @{}
    $dir = Split-Path -Parent $Full
    for ($i = 0; $i -lt $lines.Count; $i++) {
        $l = $lines[$i]
        if ($l -match '^\s*$' -or $l -match '^#{1,6}\s') { continue }
        if ($l -notmatch '^\s*[*-]\s+\[([^\]]*)\]\(([^)\s]+)\)(\s+-\s+(.*))?\s*$') { New-Finding Warning index-structure $rel ($c.bodyLine + $i) 'index.md lines should be headings or "* [Title](link) - description" entries'; continue }
        $target = [uri]::UnescapeDataString($Matches[2]); $desc = $Matches[4]
        if ($target -match '^[a-zA-Z][a-zA-Z0-9+.-]*:') { continue }
        $entry = [System.IO.Path]::GetFullPath((Join-Path $dir ($target -replace '/', '\')))
        $linked[$entry.TrimEnd('\')] = $true
        $trel = if ($entry.StartsWith($Root + '\')) { Get-RelativePath $Root $entry }
        if ($trel -and $Concepts.ContainsKey($trel) -and $Concepts[$trel].meta) {
            $want = $Concepts[$trel].meta['description']
            if ($want -and $desc -ne $want) { New-Finding Warning index-description $rel ($c.bodyLine + $i) "entry for $trel does not carry its current description (run with -WriteIndex)" }
        }
    }
    Test-Links $Root $Full $rel $c.body $c.bodyLine
    foreach ($e in Get-IndexEntries $Root $dir $Concepts) {
        $key = $e.full.TrimEnd('\')
        $key2 = (Join-Path $e.full 'index.md')
        if (-not ($linked[$key] -or $linked[$key2])) { New-Finding Warning index-missing $rel 0 "$($e.link) is not listed (run with -WriteIndex)" }
    }
}

# log.md: "## YYYY-MM-DD" headings, newest first (spec section 9).
function Test-LogFile([string]$Root, [string]$Full) {
    $rel = Get-RelativePath $Root $Full
    $lines = [System.IO.File]::ReadAllText($Full).TrimStart([char]0xFEFF) -split '\r?\n'
    $prev = $null
    for ($i = 0; $i -lt $lines.Count; $i++) {
        if ($lines[$i] -notmatch '^##\s+(.*?)\s*$') { continue }
        $h = $Matches[1]
        if ($h -notmatch '^\d{4}-\d{2}-\d{2}$') { New-Finding Error log-date $rel ($i + 1) "log heading '$h' must be an ISO date YYYY-MM-DD"; continue }
        if ($prev -and $h -ge $prev) { New-Finding Error log-order $rel ($i + 1) "log dates must be newest first and unique ($h after $prev)" }
        $prev = $h
    }
    Test-Links $Root $Full $rel ($lines -join "`n") 1
}

# A parent (a hook, another git-aware tool) can leave these in the environment, and git prefers them to -C: the check
# would compare with the parent's repo.
function Clear-GitContext {
    foreach ($name in 'GIT_DIR', 'GIT_INDEX_FILE', 'GIT_WORK_TREE', 'GIT_PREFIX', 'GIT_COMMON_DIR') {
        [Environment]::SetEnvironmentVariable($name, $null)
    }
}

# A tracked concept whose body changed since HEAD but whose generated.at did not.
function Test-GeneratedUpdated([string]$Root, [string]$Rel, $C) {
    if (-not $C.meta -or $C.meta['generated'] -isnot [System.Collections.IDictionary]) { return }
    $full = Join-Path $Root ($Rel -replace '/', '\')
    $top = & git -C (Split-Path -Parent $full) rev-parse --show-toplevel 2>$null
    if ($LASTEXITCODE -or -not $top) { return }
    $top = [System.IO.Path]::GetFullPath($top)
    $inRepo = $full.Substring($top.TrimEnd('\').Length + 1) -replace '\\', '/'
    # git writes UTF-8; PowerShell decodes native output with the console encoding unless told otherwise.
    $enc = [Console]::OutputEncoding
    try { [Console]::OutputEncoding = New-Object System.Text.UTF8Encoding $false; $old = & git -C $top show "HEAD:$inRepo" 2>$null }
    finally { [Console]::OutputEncoding = $enc }
    if ($LASTEXITCODE -or -not $old) { return }
    $tmp = [System.IO.Path]::GetTempFileName()
    try {
        [System.IO.File]::WriteAllText($tmp, ($old -join "`n"), $script:Utf8NoBom)
        $prev = Read-OkfConcept $tmp
    }
    finally { Remove-Item $tmp -Force }
    if (-not $prev.meta -or $prev.error) { return }
    $norm = { param($t) ($t -replace '\r', '').Trim() }
    if ((& $norm $prev.body) -eq (& $norm $C.body)) { return }
    $pg = $prev.meta['generated']
    if ($pg -is [System.Collections.IDictionary] -and $pg['at'] -eq $C.meta['generated']['at']) {
        New-Finding Warning generated-not-updated $Rel 2 'the body changed since the last commit but generated.at did not: set generated to the writer and now (formatting-only edits are exempt)'
    }
}
#endregion

#region Index generation
function Get-IndexEntries([string]$Root, [string]$Dir, $Concepts) {
    foreach ($f in Get-ChildItem -Path $Dir -File -Filter *.md | Where-Object { $script:Reserved -notcontains $_.Name } | Sort-Object Name) {
        @{ full = $f.FullName; link = $f.Name; rel = Get-RelativePath $Root $f.FullName; folder = $false }
    }
    foreach ($d in Get-ChildItem -Path $Dir -Directory | Where-Object { $_.Name -notlike '.*' } | Sort-Object Name) {
        if (Get-ChildItem -Path $d.FullName -Recurse -File -Filter *.md | Select-Object -First 1) {
            @{ full = $d.FullName; link = "$($d.Name)/index.md"; rel = $null; folder = $true; name = $d.Name }
        }
    }
}

function Get-TypeHeading([string]$Type) { if ($Type -match 'y$') { $Type -replace 'y$', 'ies' } else { "${Type}s" } }

# Writes index.md in every folder that has documents: one section per type (in -Types order), then folders.
# Folder entries keep the title and description already written for them. Returns the paths it changed.
function Write-OkfIndex([string]$Path, [string[]]$Types = @(), [string]$OkfVersion = '0.2') {
    $root = (Resolve-Path $Path).Path.TrimEnd('\')
    $files = @(Get-BundleFiles $root)
    $concepts = @{}
    foreach ($f in $files | Where-Object { $script:Reserved -notcontains $_.Name }) { $concepts[(Get-RelativePath $root $f.FullName)] = Read-OkfConcept $f.FullName }
    foreach ($dir in Get-ConceptDirectories $root $files) {
        $indexPath = Join-Path $dir 'index.md'
        $known = @{}
        $version = $OkfVersion
        if (Test-Path $indexPath) {
            $old = Read-OkfConcept $indexPath
            if ($old.meta -and $old.meta['okf_version']) { $version = $old.meta['okf_version'] }
            foreach ($l in ([System.IO.File]::ReadAllText($indexPath) -split '\r?\n')) {
                if ($l -match '^\s*[*-]\s+\[([^\]]*)\]\(([^)\s]+)\)(\s+-\s+(.*))?\s*$') { $known[$Matches[2]] = @{ title = $Matches[1]; desc = $Matches[4] } }
            }
        }
        $groups = [ordered]@{}
        $folders = New-Object System.Collections.ArrayList
        foreach ($e in Get-IndexEntries $root $dir $concepts) {
            if ($e.folder) {
                $k = $known[$e.link]
                if (-not $k) { $k = $known["$($e.name)/"] }
                $title = if ($k -and $k.title) { $k.title } else { (Get-Culture).TextInfo.ToTitleCase(($e.name -replace '-', ' ')) }
                $line = "* [$title]($($e.link))"
                if ($k -and $k.desc) { $line += " - $($k.desc)" }
                [void]$folders.Add($line)
                continue
            }
            $m = $concepts[$e.rel].meta
            $type = if ($m -and $m['type']) { [string]$m['type'] } else { 'Other' }
            $title = if ($m -and $m['title']) { $m['title'] } else { $e.link -replace '\.md$', '' }
            $line = "* [$title]($($e.link))"
            if ($m -and $m['description']) { $line += " - $($m['description'])" }
            if (-not $groups.Contains($type)) { $groups[$type] = New-Object System.Collections.ArrayList }
            [void]$groups[$type].Add(@{ title = $title; line = $line })
        }
        $order = @($Types | Where-Object { $groups.Contains($_) }) + @($groups.Keys | Where-Object { $Types -notcontains $_ } | Sort-Object)
        $sb = New-Object System.Text.StringBuilder
        if ($dir -eq $root) { [void]$sb.Append("---`nokf_version: `"$version`"`n---`n`n") }
        foreach ($t in $order) {
            [void]$sb.Append("# $(Get-TypeHeading $t)`n`n")
            foreach ($g in ($groups[$t] | Sort-Object { $_.title })) { [void]$sb.Append("$($g.line)`n") }
            [void]$sb.Append("`n")
        }
        if ($folders.Count) { [void]$sb.Append("# Folders`n`n"); foreach ($l in $folders) { [void]$sb.Append("$l`n") }; [void]$sb.Append("`n") }
        $text = $sb.ToString().TrimEnd("`n") + "`n"
        $current = if (Test-Path $indexPath) { [System.IO.File]::ReadAllText($indexPath) -replace '\r', '' }
        if ($current -ne $text) { [System.IO.File]::WriteAllText($indexPath, $text, $script:Utf8NoBom); $indexPath }
    }
}
#endregion
