# Checks a documentation bundle against OKF v0.2 and the conventions in README.md; exit 1 when there are errors.
# Run from the repo root:
#   powershell -NoProfile -File tools\okf\Test-OkfBundle.ps1 [-Path docs] [-WriteIndex] [-WriteViz] [-Name <title>] [-Quiet]
# -WriteIndex rewrites the index.md files and -WriteViz makes the bundle's viz.html, before the check; the check does not read it.
# -Name is the viz.html header (default: the bundle folder, or the repo folder for a bundle named docs). -Quiet prints errors only.
param([string]$Path = 'docs', [switch]$WriteIndex, [switch]$WriteViz, [string]$Name, [switch]$Quiet)
. (Join-Path $PSScriptRoot 'OkfBundle.ps1')
. (Join-Path $PSScriptRoot 'OkfViz.ps1')

if (-not (Test-Path $Path -PathType Container)) { Write-Output "No bundle folder at '$Path'."; exit 1 }
$vocabulary = (Read-OkfConcept (Join-Path $PSScriptRoot 'types.md')).meta
$types = @($vocabulary['types'])
$palette = $vocabulary['colors']
if ($WriteIndex) { foreach ($p in Write-OkfIndex -Path $Path -Types $types) { Write-Output "wrote $p" } }
if ($WriteViz) { foreach ($p in Write-OkfViz -Path $Path -Name $Name -Types $types -Palette $palette) { Write-Output "wrote $p" } }
$findings = @(Test-OkfBundle -Path $Path -Types $types)
$errors = @($findings | Where-Object { $_.level -eq 'Error' })
foreach ($f in $findings | Sort-Object file, line) {
    if ($Quiet -and $f.level -ne 'Error') { continue }
    $at = if ($f.line) { "$($f.file):$($f.line)" } else { $f.file }
    Write-Output ('{0,-7} {1,-22} {2}  {3}' -f $f.level.ToUpper(), $f.rule, $at, $f.message)
}
Write-Output "$($errors.Count) error(s), $($findings.Count - $errors.Count) warning(s) in $((Resolve-Path $Path).Path)"
if ($errors.Count) { exit 1 }
