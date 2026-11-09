# Helpers of the bridge tests that more than one test file uses. Dot-source it after the bridge scripts.

# TIA's path limit for a test that makes its paths in $TestDrive. $TestDrive lies under TEMP, which may be long (an
# agent's scratch folder): the limit counts from it as from a root of C:\t, so that the guard refuses only what the
# test makes too long.
function Get-TestDrivePathLimit([int]$OfTia) { $OfTia + "$TestDrive".Length - 'C:\t'.Length }
