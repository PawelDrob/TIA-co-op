$here = Split-Path -Parent $MyInvocation.MyCommand.Path
. (Join-Path $here '..\OkfBundle.ps1')
. (Join-Path $here '..\OkfViz.ps1')

function New-Doc([string]$Root, [string]$Rel, [string]$Front, [string]$Body = "# Heading`n") {
    $p = Join-Path $Root ($Rel -replace '/', '\')
    New-Item -ItemType Directory -Force -Path (Split-Path -Parent $p) | Out-Null
    [System.IO.File]::WriteAllText($p, "---`n$Front`n---`n$Body", (New-Object System.Text.UTF8Encoding $false))
}

function Get-Front([string]$Type, [string]$Title, [string]$Extra = '') {
    "type: $Type`ntitle: $Title`ndescription: About $Title.`ngenerated: { by: human:alex, at: 2026-10-04T00:00:00Z }$Extra"
}

Describe 'ConvertTo-OkfJson' {
    It 'keeps key order, escapes for a script element, and writes numbers, booleans, null and nested values' {
        $v = [ordered]@{ b = 'x"y\z'; a = @(1, $true, $null); s = "</script>&`n"; e = @(); m = [ordered]@{ k = 2.5 } }
        ConvertTo-OkfJson $v | Should Be '{"b":"x\"y\\z","a":[1,true,null],"s":"\u003c/script\u003e\u0026\n","e":[],"m":{"k":2.5}}'
    }
}

Describe 'Get-OkfVizData' {
    $r = Join-Path $TestDrive 'b'
    New-Doc $r 'guides/one.md' (Get-Front Guide One "`ntags: [plc]`nverified: { by: human:alex, at: 2026-10-04T00:00:00Z }") "See [two](../standards/two.md), [two again](../standards/two.md#Rules), [self](one.md), [missing](nope.md), [web](https://x).`n``[code](../standards/two.md)```n"
    New-Doc $r 'standards/two.md' (Get-Front Standard Two "`nstatus: deprecated`nstale_after: 2026-01-01T00:00:00Z`nverified: [{ by: process:nightly, at: 2026-10-04T00:00:00Z }]") ("Back to [one](../guides/one.md).`n" + '```' + "`n[x](../guides/one.md)`n" + '```' + "`n")
    New-Doc $r 'overview.md' (Get-Front Overview Start)
    New-Doc $r 'templates/concept.md' 'type: Template'
    [System.IO.File]::WriteAllText((Join-Path $r 'index.md'), "* [One](guides/one.md)`n")
    [System.IO.File]::WriteAllText((Join-Path $r 'log.md'), "# Log`n")
    $d = Get-OkfVizData -Path $r -Types @('Overview', 'Standard', 'Guide') -Palette @{ Guide = '#10b981' } -Now ([datetime]'2026-10-04')

    It 'has one node per document except templates, index and log, in type order' {
        ($d.nodes | ForEach-Object { $_.data.id }) -join ',' | Should Be 'overview,standards/two,guides/one'
        $d.types -join ',' | Should Be 'Guide,Overview,Standard'
    }

    It 'derives trust tier, staleness, status and color like the reference viewer' {
        $one = $d.nodes[2].data; $two = $d.nodes[1].data
        $one.trust_tier | Should Be 'human-reviewed'
        $two.trust_tier | Should Be 'machine-confirmed'
        $d.nodes[0].data.trust_tier | Should Be 'unverified'
        $two.stale | Should Be $true
        $one.stale | Should Be $false
        $two.status | Should Be 'deprecated'
        $one.color | Should Be '#10b981'
        $two.color | Should Be '#94a3b8'
        $one.tags[0] | Should Be 'plc'
    }

    It 'draws one edge per linked document, from links outside code only' {
        ($d.edges | ForEach-Object { "$($_.data.source)>$($_.data.target)" }) -join ',' | Should Be 'standards/two>guides/one,guides/one>standards/two'
    }

    It 'rewrites relative links in the embedded bodies to the bundle-absolute form, leaving code and unknown targets' {
        $b = $d.bodies['guides/one']
        $b | Should Match ([regex]::Escape('[two](/standards/two.md), [two again](/standards/two.md), [self](/guides/one.md), [missing](nope.md), [web](https://x)'))
        $b | Should Match ([regex]::Escape('`[code](../standards/two.md)`'))
        $d.bodies['standards/two'] | Should Match ([regex]::Escape("```````n[x](../guides/one.md)"))
    }
}

Describe 'Write-OkfViz' {
    $r = Join-Path $TestDrive 'repo\docs'
    New-Doc $r 'a.md' (Get-Front Guide A)

    It 'writes viz.html from the template, named after the repo for a docs bundle, and only when it changes' {
        $p = @(Write-OkfViz -Path $r -Types @('Guide'))
        $p.Count | Should Be 1
        $html = [System.IO.File]::ReadAllText((Join-Path $r 'viz.html'))
        $html | Should Match 'window.BUNDLE_NAME = "repo";'
        $html | Should Match 'window.BUNDLE = \{"nodes":\[\{"data":\{"id":"a","label":"A"'
        $html | Should Not Match '__VIZ_JS__|__BUNDLE_DATA__'
        @(Write-OkfViz -Path $r -Types @('Guide')).Count | Should Be 0
    }

    It 'notices a document change' {
        New-Doc $r 'a.md' (Get-Front Guide 'A changed')
        Test-OkfVizCurrent (Join-Path $r 'viz.html') (New-OkfVizHtml -Path $r -Types @('Guide')) | Should Be $false
    }
}

Describe 'Test-OkfBundle.ps1 and the viewer' {
    $script = Join-Path $here '..\Test-OkfBundle.ps1'
    $r = Join-Path $TestDrive 'some-clone\docs'
    New-Doc $r 'a.md' (Get-Front Guide A)
    [System.IO.File]::WriteAllText((Join-Path $r 'log.md'), "# Log`n")
    & $script -Path $r -WriteIndex | Out-Null

    It 'makes no viz.html by itself' {
        & $script -Path $r | Out-Null
        Test-Path (Join-Path $r 'viz.html') | Should Be $false
    }

    It '-WriteViz makes it, with -Name in its header' {
        & $script -Path $r -WriteViz -Name 'Shown name' | Out-Null
        [System.IO.File]::ReadAllText((Join-Path $r 'viz.html')) | Should Match 'window.BUNDLE_NAME = "Shown name";'
    }

    It 'has no warning about a viz.html left behind, whatever it shows' {
        [System.IO.File]::WriteAllText((Join-Path $r 'viz.html'), 'an old viewer')
        (& $script -Path $r) -join "`n" | Should Match '0 error\(s\), 0 warning\(s\)'
    }
}
