$here = Split-Path -Parent $MyInvocation.MyCommand.Path
. (Join-Path $here '..\OkfBundle.ps1')

$script:Good = @'
type: Guide
title: Good
description: A conformant concept.
generated: { by: claude-code/claude-opus-5-5, at: 2026-10-04T00:00:00Z }
'@

function New-Doc([string]$Root, [string]$Rel, [string]$Front, [string]$Body = "# Heading`n") {
    $p = Join-Path $Root ($Rel -replace '/', '\')
    New-Item -ItemType Directory -Force -Path (Split-Path -Parent $p) | Out-Null
    $text = if ($Front) { "---`n$Front`n---`n$Body" } else { $Body }
    [System.IO.File]::WriteAllText($p, $text, (New-Object System.Text.UTF8Encoding $false))
}

function New-Bundle([string]$Name) {
    $root = Join-Path $TestDrive $Name
    New-Item -ItemType Directory -Force -Path $root | Out-Null
    $root
}

function Get-Rules($Findings, [string]$Level = 'Error') { @($Findings | Where-Object { $_.level -eq $Level } | ForEach-Object { $_.rule }) }

Describe 'ConvertFrom-OkfYaml' {
    It 'reads scalars, quoted values, flow maps and flow lists as strings' {
        $m = ConvertFrom-OkfYaml @('type: Guide', 'title: "Incident: freshness"', "note: 'it''s'", 'tags: [plc, hmi]', 'generated: { by: human:alex, at: 2026-10-04T00:00:00Z }', 'url: https://x/y#z # comment')
        $m['type'] | Should Be 'Guide'
        $m['title'] | Should Be 'Incident: freshness'
        $m['note'] | Should Be "it's"
        $m['tags'].Count | Should Be 2
        $m['tags'][1] | Should Be 'hmi'
        $m['generated']['by'] | Should Be 'human:alex'
        $m['generated']['at'] | Should Be '2026-10-04T00:00:00Z'
        $m['url'] | Should Be 'https://x/y#z'
    }

    It 'reads block lists of maps and of flow maps, also at the key''s indent' {
        $m = ConvertFrom-OkfYaml @('sources:', '  - id: lad-doc', '    resource: https://example.com/a', '  - id: user', '    resource: observations in the TIA editor', 'verified:', '- { by: human:alex, at: 2026-09-28T00:00:00Z }', 'tags:', '  - one')
        $m['sources'].Count | Should Be 2
        $m['sources'][1]['resource'] | Should Be 'observations in the TIA editor'
        $m['verified'].Count | Should Be 1
        $m['verified'][0]['by'] | Should Be 'human:alex'
        $m['tags'].Count | Should Be 1
    }

    It 'reads nested block maps and empty values' {
        $m = ConvertFrom-OkfYaml @('executor:', '  resource: run.md', '  receipt: [job_id, result]', 'empty:')
        $m['executor']['receipt'][0] | Should Be 'job_id'
        $m.Contains('empty') | Should Be $true
        $m['empty'] | Should Be $null
    }

    It 'rejects YAML outside the subset and YAML errors' {
        { ConvertFrom-OkfYaml @('description: |', '  text') } | Should Throw 'outside the supported YAML subset'
        { ConvertFrom-OkfYaml @('type: a', 'type: b') } | Should Throw 'duplicate key'
        { ConvertFrom-OkfYaml @('title: Incident response: data') } | Should Throw 'quote the value'
        { ConvertFrom-OkfYaml @('tags: [a, b') } | Should Throw 'not closed'
        { ConvertFrom-OkfYaml @('type: a', '   bad: b') } | Should Throw 'unexpected indentation'
    }
}

Describe 'Test-OkfBundle conformance (OKF section 11)' {
    It 'passes a conformant bundle with index and log' {
        $r = New-Bundle 'clean'
        New-Doc $r 'guides/good.md' $script:Good "# Good`n`nSee [log](../log.md).`n"
        [System.IO.File]::WriteAllText((Join-Path $r 'index.md'), "---`nokf_version: `"0.2`"`n---`n`n# Folders`n`n* [Guides](guides/index.md) - Guides.`n")
        [System.IO.File]::WriteAllText((Join-Path $r 'guides\index.md'), "# Guides`n`n* [Good](good.md) - A conformant concept.`n")
        [System.IO.File]::WriteAllText((Join-Path $r 'log.md'), "# Log`n`n## 2026-10-04`n* **Creation**: x`n`n## 2026-10-01`n* y`n")
        $f = @(Test-OkfBundle -Path $r -Types @('Guide') -NoGit)
        ($f | ForEach-Object { "$($_.rule) $($_.message)" }) -join '; ' | Should Be ''
    }

    It 'reports a missing frontmatter, an unreadable one and an empty type' {
        $r = New-Bundle 'conf'
        New-Doc $r 'none.md' $null
        New-Doc $r 'bad.md' "type: [a"
        New-Doc $r 'empty.md' "type: ''`ntitle: x"
        $f = @(Test-OkfBundle -Path $r -NoGit)
        @($f | Where-Object { $_.file -eq 'none.md' -and $_.rule -eq 'frontmatter' }).Count | Should Be 1
        @($f | Where-Object { $_.file -eq 'bad.md' -and $_.rule -eq 'frontmatter' }).Count | Should Be 1
        @($f | Where-Object { $_.file -eq 'empty.md' -and $_.rule -eq 'type' }).Count | Should Be 1
    }

    It 'allows frontmatter only in the root index.md, and only okf_version' {
        $r = New-Bundle 'idx'
        New-Doc $r 'sub/good.md' $script:Good
        [System.IO.File]::WriteAllText((Join-Path $r 'index.md'), "---`nokf_version: `"0.2`"`ntitle: x`n---`n* [Sub](sub/index.md)`n")
        [System.IO.File]::WriteAllText((Join-Path $r 'sub\index.md'), "---`nokf_version: `"0.2`"`n---`n* [Good](good.md) - A conformant concept.`n")
        $f = @(Test-OkfBundle -Path $r -NoGit)
        @($f | Where-Object { $_.rule -eq 'index-frontmatter' }).Count | Should Be 2
    }

    It 'requires ISO date headings in log.md, newest first' {
        $r = New-Bundle 'log'
        New-Doc $r 'good.md' $script:Good
        [System.IO.File]::WriteAllText((Join-Path $r 'log.md'), "# Log`n`n## 2026-09-01`n* a`n`n## 2026-10-01`n* b`n`n## 04.10.2026`n* c`n")
        $rules = Get-Rules (Test-OkfBundle -Path $r -NoGit)
        $rules -contains 'log-order' | Should Be $true
        $rules -contains 'log-date' | Should Be $true
    }
}

Describe 'Test-OkfBundle conventions' {
    It 'requires title, description and generated, and checks status, actors and timestamps' {
        $r = New-Bundle 'meta'
        New-Doc $r 'bare.md' 'type: Guide'
        New-Doc $r 'wrong.md' "type: Guide`ntitle: t`ndescription: d`nstatus: final`ngenerated: { by: alex, at: 2026-10-04 }`nverified: { by: human:alex, at: 04.10.2026 }`nstale_after: 2026-10-04"
        $f = @(Test-OkfBundle -Path $r -NoGit)
        $bare = Get-Rules ($f | Where-Object { $_.file -eq 'bare.md' })
        $bare -contains 'title' | Should Be $true
        $bare -contains 'description' | Should Be $true
        $bare -contains 'generated' | Should Be $true
        $wrong = Get-Rules ($f | Where-Object { $_.file -eq 'wrong.md' })
        $wrong -contains 'status' | Should Be $true
        $wrong -contains 'actor' | Should Be $true
        @($wrong | Where-Object { $_ -eq 'timestamp' }).Count | Should Be 3
    }

    It 'warns on an unknown type, a past stale_after and a non-kebab tag' {
        $r = New-Bundle 'warn'
        New-Doc $r 'a.md' ($script:Good -replace 'Guide', 'Memo')
        New-Doc $r 'b.md' "$($script:Good)`nstale_after: 2026-01-01T00:00:00Z`ntags: [Bad_Tag]"
        $w = Get-Rules (Test-OkfBundle -Path $r -Types @('Guide') -NoGit) 'Warning'
        $w -contains 'type-vocabulary' | Should Be $true
        $w -contains 'stale' | Should Be $true
        $w -contains 'tags' | Should Be $true
    }

    It 'skips field checks for templates' {
        $r = New-Bundle 'tpl'
        New-Doc $r 'templates/concept.md' "type: Template`ngenerated: { by: human:alex, at: '{{date}}' }"
        Get-Rules (Test-OkfBundle -Path $r -NoGit) | Should BeNullOrEmpty
    }

    It 'reports a document that still has the template''s type' {
        $r = New-Bundle 'tpl2'
        New-Doc $r 'notes/new-note.md' "type: Template`ntitle: ''"
        Get-Rules (Test-OkfBundle -Path $r -NoGit) | Should Be 'template-type'
    }

    It 'requires kebab-case file names' {
        $r = New-Bundle 'names'
        New-Doc $r 'Some_Guide.md' $script:Good
        Get-Rules (Test-OkfBundle -Path $r -NoGit) | Should Be 'file-name'
    }

    It 'checks relative links, rejects bundle-absolute links and wikilinks, ignores code' {
        $r = New-Bundle 'links'
        New-Doc $r 'b.md' $script:Good
        $body = "[ok](b.md) [anchor](b.md#Some%20Heading) [web](https://x) [self](#top)`n[missing](c.md) [abs](/b.md) [[b]]`n``[not](code.md)```n" + '```' + "`n[not](fenced.md)`n" + '```' + "`n[ref]: d.md`n"
        New-Doc $r 'a.md' $script:Good $body
        $f = @(Test-OkfBundle -Path $r -NoGit | Where-Object { $_.file -eq 'a.md' })
        @($f | Where-Object { $_.rule -eq 'broken-link' }).Count | Should Be 2
        @($f | Where-Object { $_.rule -eq 'link-style' }).Count | Should Be 2
        @($f | Where-Object { $_.message -match 'code.md|fenced.md' }).Count | Should Be 0
    }

    It 'warns when a footnote has no matching source id' {
        $r = New-Bundle 'foot'
        New-Doc $r 'a.md' "$($script:Good)`nsources:`n  - id: lad-doc`n    resource: https://example.com" "Fact.[^lad-doc] Other.[^nope]`n`n[^lad-doc]: LAD`n[^nope]: x`n"
        $f = @(Test-OkfBundle -Path $r -NoGit | Where-Object { $_.rule -eq 'footnote' })
        $f.Count | Should Be 1
        $f[0].message | Should Match 'nope'
    }
}

Describe 'Write-OkfIndex' {
    $r = New-Bundle 'gen'
    New-Doc $r 'top.md' $script:Good
    New-Doc $r 'guides/one.md' ($script:Good -replace 'title: Good', 'title: One')
    New-Doc $r 'guides/two.md' ("type: Standard`ntitle: Two`ndescription: Second.`ngenerated: { by: human:alex, at: 2026-10-04T00:00:00Z }")
    New-Item -ItemType Directory -Force -Path (Join-Path $r 'assets') | Out-Null

    It 'writes an index per folder, grouped by type in vocabulary order, and the bundle passes' {
        $written = @(Write-OkfIndex -Path $r -Types @('Standard', 'Guide'))
        $written.Count | Should Be 2
        $sub = [System.IO.File]::ReadAllText((Join-Path $r 'guides\index.md'))
        $sub | Should Be "# Standards`n`n* [Two](two.md) - Second.`n`n# Guides`n`n* [One](one.md) - A conformant concept.`n"
        $top = [System.IO.File]::ReadAllText((Join-Path $r 'index.md'))
        $top | Should Match '^---\nokf_version: "0.2"\n---'
        $top | Should Match '\* \[Guides\]\(guides/index.md\)'
        $top | Should Not Match 'assets'
        @(Test-OkfBundle -Path $r -Types @('Standard', 'Guide') -NoGit).Count | Should Be 0
    }

    It 'keeps hand-written folder titles and descriptions and changes nothing on a second run' {
        $p = Join-Path $r 'index.md'
        [System.IO.File]::WriteAllText($p, ([System.IO.File]::ReadAllText($p) -replace '\[Guides\]\(guides/index.md\)', '[How we write](guides/index.md) - Formats and rules.'))
        @(Write-OkfIndex -Path $r -Types @('Standard', 'Guide')).Count | Should Be 0
        [System.IO.File]::ReadAllText($p) | Should Match '\* \[How we write\]\(guides/index.md\) - Formats and rules\.'
    }

    It 'reports an index that misses a document or carries an old description' {
        New-Doc $r 'guides/three.md' ($script:Good -replace 'title: Good', 'title: Three')
        New-Doc $r 'guides/one.md' ($script:Good -replace 'title: Good', 'title: One' -replace 'A conformant concept.', 'Changed.')
        $w = Get-Rules (Test-OkfBundle -Path $r -Types @('Standard', 'Guide') -NoGit) 'Warning'
        $w -contains 'index-missing' | Should Be $true
        $w -contains 'index-description' | Should Be $true
    }
}

Describe 'generated.at drift' {
    $r = New-Bundle 'git'
    & git -C $r init -q
    New-Doc $r 'a.md' $script:Good "# A`n`nFirst.`n"
    & git -C $r add -A
    & git -C $r -c user.name=t -c user.email=t@t commit -q -m init

    It 'warns when the body changed but generated.at did not' {
        New-Doc $r 'a.md' $script:Good "# A`n`nSecond.`n"
        (Get-Rules (Test-OkfBundle -Path $r) 'Warning') -contains 'generated-not-updated' | Should Be $true
    }

    It 'is quiet once generated.at moves, and for a frontmatter-only change' {
        New-Doc $r 'a.md' ($script:Good -replace '2026-10-04T00:00:00Z', '2026-10-05T00:00:00Z') "# A`n`nSecond.`n"
        (Get-Rules (Test-OkfBundle -Path $r) 'Warning') -contains 'generated-not-updated' | Should Be $false
        New-Doc $r 'a.md' "$($script:Good)`ntags: [x]" "# A`n`nFirst.`n"
        (Get-Rules (Test-OkfBundle -Path $r) 'Warning') -contains 'generated-not-updated' | Should Be $false
    }

    It 'compares with the repo of the bundle, with the git context of a parent inherited' {
        $parent = New-Bundle 'git-parent'
        & git -C $parent init -q
        & git -C $parent -c user.name=t -c user.email=t@t commit -q --allow-empty -m parent
        New-Doc $r 'a.md' $script:Good "# A`n`nSecond.`n"
        try {
            $env:GIT_DIR = Join-Path $parent '.git'
            $env:GIT_WORK_TREE = $parent
            $env:GIT_INDEX_FILE = Join-Path $parent '.git\index'
            (Get-Rules (Test-OkfBundle -Path $r) 'Warning') -contains 'generated-not-updated' | Should Be $true
        } finally { foreach ($n in 'GIT_DIR', 'GIT_WORK_TREE', 'GIT_INDEX_FILE') { Remove-Item "Env:$n" -ErrorAction SilentlyContinue } }
    }

    It 'clears every name git reads a repo from' {
        $names = @(& git rev-parse --local-env-vars)
        $names -contains 'GIT_DIR' | Should Be $true
        @($names | Where-Object { (Get-GitContextNames) -notcontains $_ }).Count | Should Be 0
    }

    It 'reads a committed non-ASCII document as unchanged' {
        New-Doc $r 'b.md' $script:Good "# B`n`nSee $([char]0x00A7)9 $([char]0x2192) $([char]0x201C)Delta$([char]0x201D) $([char]0x2013) Fl$([char]0x00F6)mbrik.`n"
        & git -C $r add -A
        & git -C $r -c user.name=t -c user.email=t@t commit -q -m b
        @(Test-OkfBundle -Path $r | Where-Object { $_.file -eq 'b.md' -and $_.rule -eq 'generated-not-updated' }).Count | Should Be 0
    }
}
