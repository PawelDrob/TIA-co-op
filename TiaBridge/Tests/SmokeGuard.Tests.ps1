# The smoke scripts refuse to start beside a live bridge bound to a TIA: each starts a bridge of its own, and two on one TIA have hung it.
$here = Split-Path -Parent $MyInvocation.MyCommand.Path
. (Join-Path $here 'SmokeGuard.ps1')

Describe 'Assert-NoBoundBridge' {
    $root = Join-Path $TestDrive 'projects'
    $dir = Join-Path $root '_bridge\sessions'
    New-Item -ItemType Directory -Force -Path $dir | Out-Null
    $settings = Join-Path $TestDrive 'settings.json'
    Set-Content $settings (ConvertTo-Json @{ projectsRoot = $root })
    # processes that run and are not this one: one stands for another bridge, one for its TIA
    $bridge = Start-Process -FilePath "$env:SystemRoot\System32\ping.exe" -ArgumentList '-n 60 127.0.0.1' -WindowStyle Hidden -PassThru
    $tia = Start-Process -FilePath "$env:SystemRoot\System32\ping.exe" -ArgumentList '-n 60 127.0.0.1' -WindowStyle Hidden -PassThru
    function Write-State($Tia) {
        Set-Content (Join-Path $dir "$($bridge.Id).json") (ConvertTo-Json @{ pid = $bridge.Id; started = (Get-Date).ToString('o'); project = 'ProjectA'; tia = $Tia })
    }

    It 'lets a run start with no bridge' {
        { Assert-NoBoundBridge $settings } | Should Not Throw
    }

    It 'refuses beside a live bridge bound to a live TIA, naming it' {
        Write-State @{ pid = $tia.Id; window = $true }
        { Assert-NoBoundBridge $settings } | Should Throw "bridge $($bridge.Id) on ProjectA"
    }

    It 'lets a run start beside a bridge bound to nothing' {
        Write-State $null
        { Assert-NoBoundBridge $settings } | Should Not Throw
    }

    It 'lets a run start beside a bridge whose TIA has ended' {
        $n = 999999; while (Get-Process -Id $n -ErrorAction SilentlyContinue) { $n-- }
        Write-State @{ pid = $n; window = $true }
        { Assert-NoBoundBridge $settings } | Should Not Throw
    }

    Context 'in a worktree, where first setup wrote no settings' {
        $main = Join-Path $TestDrive 'clone'
        $tree = Join-Path $TestDrive 'clone-worktrees\one'
        New-Item -ItemType Directory -Force -Path (Join-Path $main 'TiaBridge') | Out-Null
        Set-Content (Join-Path $main 'TiaBridge\kept.txt') 'x'
        git -C $main init -q 2>&1 | Out-Null
        git -C $main add TiaBridge 2>&1 | Out-Null
        git -C $main -c user.name=t -c user.email=t@example.com commit -q -m base 2>&1 | Out-Null
        git -C $main worktree add -q $tree 2>&1 | Out-Null
        $mainSettings = Join-Path $main 'TiaBridge\settings.json'
        $treeSettings = Join-Path $tree 'TiaBridge\settings.json'

        It 'refuses beside a bridge under the projects root of the main working tree' {
            Test-Path (Join-Path $tree 'TiaBridge\kept.txt') | Should Be $true
            Set-Content $mainSettings (ConvertTo-Json @{ projectsRoot = $root })
            Write-State @{ pid = $tia.Id; window = $true }
            { Assert-NoBoundBridge $treeSettings } | Should Throw "bridge $($bridge.Id) on ProjectA"
        }

        It 'refuses there too when the worktree has a root of its own' {
            Set-Content $mainSettings (ConvertTo-Json @{ projectsRoot = $root })
            Set-Content $treeSettings (ConvertTo-Json @{ projectsRoot = (Join-Path $TestDrive 'another') })
            Write-State @{ pid = $tia.Id; window = $true }
            { Assert-NoBoundBridge $treeSettings } | Should Throw "bridge $($bridge.Id) on ProjectA"
        }

        It 'refuses beside a bridge under its own root, the main working tree holding another' {
            Set-Content $treeSettings (ConvertTo-Json @{ projectsRoot = $root })
            Set-Content $mainSettings (ConvertTo-Json @{ projectsRoot = (Join-Path $TestDrive 'another') })
            Write-State @{ pid = $tia.Id; window = $true }
            { Assert-NoBoundBridge $treeSettings } | Should Throw "bridge $($bridge.Id) on ProjectA"
        }
    }

    It 'outside git, as a smoke script calls it, reads its own settings and stops at nothing' {
        Write-State $null
        $ErrorActionPreference = 'Stop'
        { Assert-NoBoundBridge $settings } | Should Not Throw
    }

    It 'stands in every smoke script, before its bridge starts' {
        foreach ($script in 'Smoke.ps1', 'LibrarySmoke.ps1', 'BackgroundSmoke.ps1') {
            $text = Get-Content (Join-Path $here $script) -Raw
            $text.IndexOf('Assert-NoBoundBridge') | Should BeGreaterThan 0
            $text.IndexOf('Assert-NoBoundBridge') | Should BeLessThan $text.IndexOf('Process]::Start')
        }
    }

    Stop-Process -Id $bridge.Id, $tia.Id -Force -ErrorAction SilentlyContinue
}
