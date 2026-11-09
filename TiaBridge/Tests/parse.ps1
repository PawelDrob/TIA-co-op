# Parses every bridge script with the PowerShell 5.1 parser (the closest thing to a typecheck). Exit 1 on errors.
$bad = 0
foreach ($f in Get-ChildItem (Join-Path $PSScriptRoot '..') -Recurse -Filter *.ps1) {
    $tokens = $null; $errors = $null
    [void][System.Management.Automation.Language.Parser]::ParseFile($f.FullName, [ref]$tokens, [ref]$errors)
    foreach ($e in $errors) { $bad++; "$($f.FullName):$($e.Extent.StartLineNumber): $($e.Message)" }
    $text = [IO.File]::ReadAllText($f.FullName)
    if ($text -match '[^\x00-\x7F]') { $bad++; "$($f.FullName): non-ASCII characters (Windows PowerShell 5.1 reads BOM-less files as ANSI)" }
    if ($text -match '[\x00-\x08\x0B\x0C\x0E-\x1F]') { $bad++; "$($f.FullName): control characters (an escape eaten by an editing tool?)" }
}
if ($bad) { exit 1 } else { 'parse OK' }
