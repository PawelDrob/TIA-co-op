# Helpers of the bridge tests that more than one test file uses. Dot-source it after the bridge scripts.

# TIA's path limit for a test that makes its paths in $TestDrive. $TestDrive lies under TEMP, which may be long (an
# agent's scratch folder): the limit counts from it as from a root of C:\t, so that the guard refuses only what the
# test makes too long.
function Get-TestDrivePathLimit([int]$OfTia) { $OfTia + "$TestDrive".Length - 'C:\t'.Length }

# Test-TiaAlive of a fake TIA that answers until $script:tiaGone. Like the real one (Tia.ps1) it drops the kept yes first
# and keeps a new one for the bound project, so a test's call runs with the yes Get-TiaProject keeps (Test-TiaAliveInCall).
# A test file defines Test-TiaAlive { Test-FakeTiaAlive }.
function Test-FakeTiaAlive {
    $script:Bridge.aliveProject = $null
    if ($script:Bridge.project -and -not $script:tiaGone) { $script:Bridge.aliveProject = $script:Bridge.project }
    $null -ne $script:Bridge.aliveProject
}

# Binds project P as connect does: its path, and the TIA project Test-TiaAlive asks about.
function Set-TestBridgeProject([string]$Repo) {
    Set-BridgeProject -Name 'P' -Path 'C:\P.ap20' -Repo $Repo
    $script:Bridge.project = [pscustomobject]@{ Name = 'P' }
}

# A tool call's first read of the project, as the first path of a call makes it: TIA answers and its yes is kept for the
# call. A test of TIA ending in the call makes it before the tool, so that only where the bridge asks again sees the end.
function Read-CallFirstProject { $null = Get-TiaProject }

# A project's LanguageSettings as Openness gives it: each language a Culture. Active: culture names, in TIA's order.
function New-FakeLanguageSettings([string[]]$Active, [string]$Editing, [string]$Reference) {
    $l = { param($n) [pscustomobject]@{ Culture = [System.Globalization.CultureInfo]::GetCultureInfo($n) } }
    [pscustomobject]@{ ActiveLanguages = @($Active | ForEach-Object { & $l $_ }); EditingLanguage = (& $l $Editing); ReferenceLanguage = (& $l $Reference) }
}

# LanguageSettings whose ActiveLanguages throws when enumerated, as a list of Openness does: with a NonRecoverable
# exception (TIA ended) or another one.
if (-not ('TiaBridgeTest.UnreadableLanguages' -as [type])) {
    Add-Type -TypeDefinition @'
namespace TiaBridgeTest {
    public class NonRecoverableException : System.Exception { public NonRecoverableException(string m) : base(m) { } }
    public class UnreadableLanguages {
        bool ended;
        public UnreadableLanguages(bool ended) { this.ended = ended; }
        public System.Collections.Generic.IEnumerable<object> ActiveLanguages { get { return Items(); } }
        System.Collections.Generic.IEnumerable<object> Items() {
            if (ended) { throw new NonRecoverableException("Unexpected exception"); }
            throw new System.InvalidOperationException("Access to a disposed object");
#pragma warning disable 162
            yield break;
#pragma warning restore 162
        }
    }
}
'@
}
