# OkfViz.ps1 - writes a bundle's viz.html with the OKF reference viewer (viz\, Apache-2.0, see viz\NOTICE.txt).
# Derived from reference_agent/viewer/generator.py of the Open Knowledge Format reference implementation, Copyright
# 2026 Google LLC, Apache License 2.0 (viz\LICENSE.txt). Needs OkfBundle.ps1. Changed from it: templates are left out, nodes follow
# the type order of types.md, links are read outside code only, and the embedded bodies get relative links rewritten
# to the bundle-absolute form, the only form the viewer makes clickable. The documents themselves are not touched.

$script:VizDir = Join-Path $PSScriptRoot 'viz'
$script:VizDefaultColor = '#94a3b8'

# JSON with sorted-in-order keys and <, >, & escaped, so the output is stable and safe inside a <script> element.
function ConvertTo-OkfJson($Value) {
    if ($null -eq $Value) { return 'null' }
    if ($Value -is [bool]) { if ($Value) { return 'true' } else { return 'false' } }
    if ($Value -is [int] -or $Value -is [long]) { return [string]$Value }
    if ($Value -is [double]) { return $Value.ToString([System.Globalization.CultureInfo]::InvariantCulture) }
    if ($Value -is [string]) {
        $e = [regex]::Replace($Value, '[\x00-\x1f"\\<>&\u2028\u2029]', {
            param($m)
            switch ($m.Value) { '"' { '\"' } '\' { '\\' } "`n" { '\n' } "`r" { '\r' } "`t" { '\t' } default { '\u{0:x4}' -f [int][char]$m.Value } }
        })
        return '"' + $e + '"'
    }
    if ($Value -is [System.Collections.IDictionary]) {
        return '{' + (@(foreach ($k in $Value.Keys) { (ConvertTo-OkfJson ([string]$k)) + ':' + (ConvertTo-OkfJson $Value[$k]) }) -join ',') + '}'
    }
    if ($Value -is [System.Collections.IEnumerable]) {
        return '[' + (@(foreach ($v in $Value) { ConvertTo-OkfJson $v }) -join ',') + ']'
    }
    ConvertTo-OkfJson ([string]$Value)
}

# 'docs' says nothing in the viewer header: a bundle named docs is shown with its repo's name.
function Get-OkfBundleName([string]$Path) {
    $full = (Resolve-Path $Path).Path.TrimEnd('\')
    $leaf = Split-Path -Leaf $full
    if ($leaf -eq 'docs') { Split-Path -Leaf (Split-Path -Parent $full) } else { $leaf }
}

# Concept id (path without .md) of a relative .md link from $FromDir, or $null when it leaves the bundle.
function Resolve-OkfConceptLink([string]$Root, [string]$FromDir, [string]$Target) {
    if ($Target -match '^[a-zA-Z][a-zA-Z0-9+.-]*:' -or $Target -match '^[/#]') { return $null }
    $p = [uri]::UnescapeDataString(($Target -replace '[#?].*$', ''))
    if ($p -notmatch '\.md$') { return $null }
    $full = [System.IO.Path]::GetFullPath((Join-Path $FromDir ($p -replace '/', '\')))
    if (-not $full.StartsWith($Root + '\', [System.StringComparison]::OrdinalIgnoreCase)) { return $null }
    (Get-RelativePath $Root $full) -replace '\.md$', ''
}

# Rewrites [text](relative.md) to [text](/id.md) for known concepts, outside fenced code and inline code.
function ConvertTo-VizBody([string]$Root, [string]$FromDir, [string]$Body, $Ids) {
    $evaluator = {
        param($m)
        $id = Resolve-OkfConceptLink $Root $FromDir $m.Groups[2].Value
        if ($id -and $Ids.ContainsKey($id)) { "$($m.Groups[1].Value)(/$id.md)" } else { $m.Value }
    }
    $fence = $null
    $out = foreach ($l in ($Body -split "`n")) {
        if ($fence) { if ($l -match "^\s*$fence") { $fence = $null }; $l; continue }
        if ($l -match '^\s*(```+|~~~+)') { $fence = [regex]::Escape($Matches[1]); $l; continue }
        $parts = [regex]::Split($l, '((`+)(?:(?!\2).)+?\2)')
        $sb = New-Object System.Text.StringBuilder
        for ($i = 0; $i -lt $parts.Count; $i++) {
            # Split returns text, code span, backtick group, text, ...: rewrite only the text parts.
            if ($i % 3 -eq 0) { [void]$sb.Append([regex]::Replace($parts[$i], '(\[[^\]]*\])\(\s*([^)\s]+)\s*\)', $evaluator)) }
            elseif ($i % 3 -eq 1) { [void]$sb.Append($parts[$i]) }
        }
        $sb.ToString()
    }
    $out -join "`n"
}

# The viewer's data: nodes, edges, bodies, types, palette (generator.py _build_graph).
function Get-OkfVizData([string]$Path, [string[]]$Types = @(), $Palette = @{}, [datetime]$Now = [datetime]::UtcNow) {
    $root = (Resolve-Path $Path).Path.TrimEnd('\')
    $concepts = New-Object System.Collections.ArrayList
    foreach ($f in Get-BundleFiles $root) {
        if ($script:Reserved -contains $f.Name) { continue }
        $c = Read-OkfConcept $f.FullName
        if (-not $c.meta -or $c.error -or $c.meta['type'] -eq 'Template') { continue }
        $id = (Get-RelativePath $root $f.FullName) -replace '\.md$', ''
        [void]$concepts.Add(@{ id = $id; c = $c; dir = $f.DirectoryName; rank = [array]::IndexOf(@($Types), [string]$c.meta['type']) })
    }
    $ordered = @($concepts | Sort-Object @{ Expression = { if ($_.rank -lt 0) { [int]::MaxValue } else { $_.rank } } }, @{ Expression = { $_.id } })
    $ids = @{}
    foreach ($x in $ordered) { $ids[$x.id] = $true }
    $nodes = New-Object System.Collections.ArrayList
    $edges = New-Object System.Collections.ArrayList
    $bodies = [ordered]@{}
    $typeSet = @{}
    foreach ($x in $ordered) {
        $m = $x.c.meta
        $type = if ($m['type']) { [string]$m['type'] } else { 'Unknown' }
        $typeSet[$type] = $true
        $verified = @(foreach ($v in (Get-AsList $m["verified"])) { if ($v -is [System.Collections.IDictionary]) { $v } })
        $tier = if (-not $verified.Count) { 'unverified' } elseif (@($verified | Where-Object { "$($_['by'])" -like 'human:*' }).Count) { 'human-reviewed' } else { 'machine-confirmed' }
        $staleAfter = if ($m['stale_after']) { [string]$m['stale_after'] } else { '' }
        $stale = [bool]($staleAfter -match $script:TimestampRx -and [datetimeoffset]::Parse($staleAfter).UtcDateTime -le $Now)
        $color = if ($Palette -and $Palette[$type]) { [string]$Palette[$type] } else { $script:VizDefaultColor }
        $generated = if ($m['generated'] -is [System.Collections.IDictionary]) { $m['generated'] } else { [ordered]@{} }
        $body = $x.c.body
        [void]$nodes.Add([ordered]@{ data = [ordered]@{
            id = $x.id; label = $(if ($m['title']) { [string]$m['title'] } else { $x.id }); type = $type
            description = [string]$m['description']; resource = [string]$m['resource']; tags = @(foreach ($t in (Get-AsList $m["tags"])) { [string]$t })
            status = $(if ($m['status']) { [string]$m['status'] } else { 'stable' }); generated = $generated; verified = $verified
            stale_after = $staleAfter; sources = @(foreach ($s in (Get-AsList $m["sources"])) { if ($s -is [System.Collections.IDictionary]) { $s } })
            trust_tier = $tier; stale = $stale; color = $color; size = [int](30 + [math]::Min(60, [math]::Floor($body.Length / 200)))
        } })
        $seen = @{}
        foreach ($l in Get-MarkdownLinks $body $x.c.bodyLine) {
            if ($l.kind -ne 'link') { continue }
            $t = Resolve-OkfConceptLink $root $x.dir $l.target
            if (-not $t -or $t -eq $x.id -or -not $ids.ContainsKey($t) -or $seen.ContainsKey($t)) { continue }
            $seen[$t] = $true
            [void]$edges.Add([ordered]@{ data = [ordered]@{ id = "$($x.id)__$t"; source = $x.id; target = $t } })
        }
        $bodies[$x.id] = ConvertTo-VizBody $root $x.dir $body $ids
    }
    $pal = [ordered]@{}
    if ($Palette) { foreach ($k in $Palette.Keys) { $pal[$k] = $Palette[$k] } }
    [ordered]@{ nodes = $nodes.ToArray(); edges = $edges.ToArray(); bodies = $bodies; types = @($typeSet.Keys | Sort-Object { $_ } -CaseSensitive); palette = $pal }
}

function Read-VizAsset([string]$Name) { [System.IO.File]::ReadAllText((Join-Path $script:VizDir $Name), [System.Text.Encoding]::UTF8) -replace '\r', '' }

function New-OkfVizHtml([string]$Path, [string]$Name, [string[]]$Types = @(), $Palette = @{}, [datetime]$Now = [datetime]::UtcNow) {
    if (-not $Name) { $Name = Get-OkfBundleName $Path }
    $data = ConvertTo-OkfJson (Get-OkfVizData $Path $Types $Palette $Now)
    $html = (Read-VizAsset "viz.html").Replace("/*__VIZ_CSS__*/", (Read-VizAsset "viz.css")).Replace("/*__VIZ_JS__*/", (Read-VizAsset "viz.js"))
    $html.Replace("__BUNDLE_NAME__", (ConvertTo-OkfJson $Name)).Replace("__BUNDLE_DATA__", $data)
}

# Writes <bundle>\viz.html when it differs; returns its path when written.
function Write-OkfViz([string]$Path, [string]$Name, [string[]]$Types = @(), $Palette = @{}, [datetime]$Now = [datetime]::UtcNow) {
    $out = Join-Path (Resolve-Path $Path).Path 'viz.html'
    $html = New-OkfVizHtml $Path $Name $Types $Palette $Now
    if (-not (Test-OkfVizCurrent $out $html)) { [System.IO.File]::WriteAllText($out, $html, $script:Utf8NoBom); $out }
}

function Test-OkfVizCurrent([string]$File, [string]$Html) {
    (Test-Path $File) -and (([System.IO.File]::ReadAllText($File, [System.Text.Encoding]::UTF8) -replace '\r', '') -eq $Html)
}
