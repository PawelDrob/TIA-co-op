$here = Split-Path -Parent $MyInvocation.MyCommand.Path
foreach ($f in 'Mcp.ps1', 'Tia.ps1', 'Repo.ps1', 'Rules.ps1', 'Guards.ps1', 'Bridge.ps1', 'Tools\Objects.ps1', 'Tools\Plc.ps1', 'Tools\Library.ps1', 'Tools\LibraryChange.ps1', 'Tools\FullExport.ps1') {
    . (Join-Path $here "..\$f")
}

# TIA ends its process seconds after a NonRecoverableException. A tool that catches it per item must still detach and
# refuse every TIA call until connect (Set-TiaEnded). Import, release chain and delete have their own tests.
if (-not ('FakeSiemens.NonRecoverableException' -as [type])) {
    Add-Type -TypeDefinition 'namespace FakeSiemens { public class NonRecoverableException : System.Exception { public NonRecoverableException(string m) : base(m) { } } }'
}
if (-not ('Siemens.Engineering.Library.Types.DeleteUnusedVersionsMode' -as [type])) {
    Add-Type -TypeDefinition @'
namespace Siemens.Engineering.Library.Types {
    public interface ILibraryTypeOrFolderSelection { }
    public class FakeTypeSelection : ILibraryTypeOrFolderSelection { }
    public enum DeleteUnusedVersionsMode { DoNotDelete }
    public enum UpdateCheckMode { ReportOutOfDateOnly }
}
'@
}

function New-Ending { [System.Management.Automation.MethodInvocationException]::new('outer', [FakeSiemens.NonRecoverableException]::new('Unexpected exception')) }

function Get-KindRoot { 'root' }
# like the real one: nothing to ask once the bridge has detached
function Test-TiaAlive { [bool]($script:Bridge.project -and -not $script:tiaGone) }
function Invoke-TiaWrite([string]$Description, [scriptblock]$Body, [switch]$NoTransaction, [scriptblock]$RollbackIf) {
    $out = @(& $Body)
    @{ output = $out; transaction = $true; rolledBack = $false; commitError = $null; note = $null }
}

function New-FakeProjectLibrary {
    $l = [pscustomobject]@{ }
    $l | Add-Member ScriptMethod UpdateCheck { param($p, $m) @{ } }
    $l
}

function Initialize-FakeBridge([switch]$Background) {
    Initialize-BridgeContext @{ maxResponseChars = 20000 }
    Set-BridgeProject -Name 'P' -Path 'C:\P.ap20' -Repo (Join-Path $TestDrive 'E')
    $script:Bridge.project = [pscustomobject]@{ ProjectLibrary = (New-FakeProjectLibrary) }
    if ($Background) { $script:Bridge.background = @{ write = $true; session = (New-SessionState) } }
    Register-Archive (Get-BridgeSession)
}

# The fake kind: Ends ends TIA, Bad fails, any other name works.
Register-ObjectKind 'fake' @{
    scope = 'plc'; dir = 'plc\fake'; defaultOverride = $true; description = 'test kind'
    items = { param($root) foreach ($n in $script:names) { @{ name = $n; folder = ''; obj = [pscustomobject]@{ Name = $n } } } }
    info = { param($e)
        if ($e.name -eq 'Ends') { throw (New-Ending) }
        if ($e.name -eq 'Bad') { throw [System.InvalidOperationException]::new('no info') }
        @{ fine = $true } }
    export = { param($e, $dir, $opt)
        $script:exported += @($e.name)
        if ($e.name -eq 'Ends') { throw (New-Ending) }
        if ($e.name -eq 'Bad') { throw [System.InvalidOperationException]::new('TIA said no') }
        @{ ok = $true; format = 'xml'; files = @() } }
}

Describe 'export that ends TIA' {
    function Invoke-FakeExport([string[]]$Names, [switch]$Background) {
        Initialize-FakeBridge -Background:$Background
        $script:names = $Names; $script:exported = @()
        Invoke-ExportTool ([pscustomobject]@{ kind = 'fake'; names = @('*') })
    }

    It 'returns the TIA-ended result, stops there and refuses TIA calls until connect' {
        $r = Invoke-FakeExport @('A', 'Ends', 'C')
        $r.ok | Should Be $false
        $r.tiaEnded | Should Be $true
        $r.kind | Should Be 'fake'
        $r.note | Should Match 'TIA Portal ended at Ends'
        $r.note | Should Match 'NonRecoverableException'
        $r.note | Should Match 'call connect'
        $script:exported -join ',' | Should Be 'A,Ends'
        { Get-TiaProject } | Should Throw 'call connect'
    }

    It 'keeps the objects exported before as they are: their files are in the repo, not lost' {
        $r = Invoke-FakeExport @('A', 'Ends')
        $r.items[0].ok | Should Be $true
        $r.items[0].Contains('lost') | Should Be $false
        $r.note | Should Not Match 'Nothing of the'
    }

    It 'says so as well when TIA does not answer after a failure' {
        $script:tiaGone = $true
        try { $r = Invoke-FakeExport @('Bad', 'C') } finally { $script:tiaGone = $false }
        $r.tiaEnded | Should Be $true
        $r.note | Should Match 'does not answer any more'
        @($r.items).Count | Should Be 1
        { Get-TiaProject } | Should Throw 'call connect'
    }

    It 'tells a background session to close and open again, and leaves the window session alone' {
        $r = Invoke-FakeExport @('Ends') -Background
        $r.note | Should Match 'background_close, then background_open'
        $script:Bridge.tiaEnded | Should BeNullOrEmpty
    }

    It 'goes on after a plain failure while TIA answers' {
        $r = Invoke-FakeExport @('Bad', 'C')
        $r.Contains('tiaEnded') | Should Be $false
        $script:exported -join ',' | Should Be 'Bad,C'
        $script:Bridge.tiaEnded | Should BeNullOrEmpty
    }
}

Describe 'full_export of a kind part that ends TIA' {
    It 'stops the part and refuses TIA calls until connect' {
        Initialize-FakeBridge
        $script:names = @('A', 'Ends', 'C'); $script:exported = @()
        $rec = @{ count = 0; exported = 0; written = (New-Object System.Collections.ArrayList); removed = (New-Object System.Collections.ArrayList)
                  fellBack = (New-Object System.Collections.ArrayList); knowHowProtected = (New-Object System.Collections.ArrayList); kept = (New-Object System.Collections.ArrayList)
                  notExported = (New-Object System.Collections.ArrayList); failed = (New-Object System.Collections.ArrayList) }
        Invoke-FullExportKindPart @{ name = 'fake'; kind = 'fake'; fallback = $true } 'root' '' $rec
        $rec.stopped | Should Be $true
        $script:exported -join ',' | Should Be 'A,Ends'
        { Get-TiaProject } | Should Throw 'call connect'
    }
}

Describe 'full_export that ends TIA' {
    Register-ObjectKind 'fakelist' @{
        scope = 'project'; dir = 'project\list'; description = 'test kind that fails at its list'
        items = { param($root) if ($script:goneAtList) { $script:tiaGone = $true }; throw $script:listFailure }
        export = { param($e, $dir, $opt) @{ ok = $true; format = 'xml'; files = @() } }
    }
    Register-ObjectKind 'fakenext' @{
        scope = 'project'; dir = 'project\next'; description = 'test kind of the part after'
        items = { param($root) $script:nextRan = $true; @() }
        export = { param($e, $dir, $opt) @{ ok = $true; format = 'xml'; files = @() } }
    }
    function Get-TiaSoftwareList { @() }
    $next = @{ name = 'next'; scope = 'project'; kind = 'fakenext' }
    function Invoke-FakeFullExport([object[]]$Parts) {
        Initialize-FakeBridge -Background:$script:inBackground
        $script:exported = @(); $script:nextRan = $false
        $saved = $script:FullExportParts
        $script:FullExportParts = $Parts
        try { Invoke-FullExportTool ([pscustomobject]@{ }) } finally { $script:FullExportParts = $saved }
    }
    function Assert-Ended($R) {
        $R.ok | Should Be $false
        $R.tiaEnded | Should Be $true
        $R.note | Should Match 'call connect'
        $R.stopped | Should Match 'no folder was mirrored'
        $script:nextRan | Should Be $false
        { Get-TiaProject } | Should Throw 'call connect'
    }

    It 'stops at an object that ends TIA, and says connect is next' {
        $script:names = @('A', 'Ends', 'C')
        $r = Invoke-FakeFullExport @(@{ name = 'objects'; scope = 'project'; kind = 'fake' }, $next)
        Assert-Ended $r
        $r.note | Should Match 'objects'
    }

    It 'stops at a list that ends TIA, although its process is still up' {
        $script:listFailure = New-Ending
        Assert-Ended (Invoke-FakeFullExport @(@{ name = 'listed'; scope = 'project'; kind = 'fakelist' }, $next))
    }

    It 'stops at a file part that ends TIA, although its process is still up' {
        Assert-Ended (Invoke-FakeFullExport @(@{ name = 'file'; scope = 'project'; dir = 'project\file'; file = { param($root, $partial) throw (New-Ending) } }, $next))
    }

    It 'stops when TIA does not answer after a plain failure' {
        $script:listFailure = [System.InvalidOperationException]::new('gone')
        $script:goneAtList = $true
        try { $r = Invoke-FakeFullExport @(@{ name = 'listed'; scope = 'project'; kind = 'fakelist' }, $next) } finally { $script:goneAtList = $false; $script:tiaGone = $false }
        Assert-Ended $r
        $r.note | Should Match 'does not answer'
    }

    It 'goes on after a plain failure while TIA answers' {
        $script:listFailure = [System.InvalidOperationException]::new('no list')
        $r = Invoke-FakeFullExport @(@{ name = 'listed'; scope = 'project'; kind = 'fakelist' }, $next)
        $r.ok | Should Be $false
        $r.Contains('tiaEnded') | Should Be $false
        $r.Contains('stopped') | Should Be $false
        $script:nextRan | Should Be $true
        $script:Bridge.tiaEnded | Should BeNullOrEmpty
    }

    It 'names background_close in a background session' {
        $script:inBackground = $true
        $script:listFailure = New-Ending
        try { $r = Invoke-FakeFullExport @(@{ name = 'listed'; scope = 'project'; kind = 'fakelist' }, $next) } finally { $script:inBackground = $false }
        $r.tiaEnded | Should Be $true
        $r.note | Should Match 'background_close'
    }
}

Describe 'list that ends TIA' {
    It 'reaches the dispatch instead of becoming the infoError of one entry' {
        Initialize-FakeBridge
        $script:names = @('A', 'Ends')
        $d = Invoke-BridgeTool 'list' { param($a) Invoke-ListTool $a } ([pscustomobject]@{ kind = 'fake' })
        $d.result.error.tiaEnded | Should Be $true
        $d.result.error.note | Should Match 'call connect'
        { Get-TiaProject } | Should Throw 'call connect'
    }

    It 'keeps a plain failure as the infoError of the entry' {
        Initialize-FakeBridge
        $script:names = @('A', 'Bad')
        $r = Invoke-ListTool ([pscustomobject]@{ kind = 'fake' })
        $r.ok | Should Be $true
        $r.items[1].infoError | Should Be 'no info'
    }
}

Describe 'library_update_usages when putting a left-out type in work ends TIA' {
    function Get-TiaLibrary { $l = [pscustomobject]@{ }; $l | Add-Member ScriptMethod UpdateProject { param($s, $sc, $m) }; $l }
    function Find-LibraryType { @{ name = 'T'; obj = [Siemens.Engineering.Library.Types.FakeTypeSelection]::new() } }
    function Get-UpdateScopes { @() }
    function Get-TiaSoftwareList { @(@{ device = 'PLC_1'; kind = 'plc' }) }
    function Get-SafetyAdministration { $null }
    function Get-InWorkTypes { @{ types = @(); complete = $true; walked = 0 } }
    function Add-LibraryLog { param($Line) $script:logged += @($Line) }
    function Get-LiveChange { [ordered]@{ id = 'c1'; root = 'T1'; types = [ordered]@{ T1 = @{ inWork = '' }; T2 = @{ inWork = '' }; T3 = @{ inWork = '' } } } }
    function Save-ChangeRecord { $script:saved++; 'library\changes\c1.md' }
    function Invoke-CompileTool { @{ items = @(@{ messages = @{ } }) } }
    function Get-CompileErrors { foreach ($n in 'T1', 'T2', 'T3') { @{ object = $n; description = 'incompatible changes' } } }
    function Set-TypeInWork($Library, [string]$Name) {
        $script:putInWork += @($Name)
        if ($Name -eq $script:failAt) {
            if ($script:goneAfter) { $script:tiaGone = $true }
            throw $script:failWith
        }
        '1.0.1'
    }

    function Invoke-FakeUpdate($FailAt, $FailWith, [switch]$Background, [switch]$GoneAfter) {
        Initialize-FakeBridge -Background:$Background
        $script:failAt = $FailAt; $script:failWith = $FailWith; $script:goneAfter = [bool]$GoneAfter
        $script:putInWork = @(); $script:saved = 0; $script:logged = @()
        try { Invoke-LibraryUpdateTool ([pscustomobject]@{ types = @('T1') }) } finally { $script:tiaGone = $false }
    }

    It 'returns the TIA-ended result, stops at that type and refuses TIA calls until connect' {
        $r = Invoke-FakeUpdate 'T2' (New-Ending)
        $r.ok | Should Be $false
        $r.tiaEnded | Should Be $true
        $r.note | Should Match 'TIA Portal ended at T2'
        $r.note | Should Match 'NonRecoverableException'
        $r.note | Should Match 'call connect'
        $r.summary | Should Be $r.note
        $r.items[0].type | Should Be 'T1'
        $r.items[0].lost | Should Be $true
        $r.items[1].error.tiaEnded | Should Be $true
        $script:putInWork -join ',' | Should Be 'T1,T2'
        { Get-TiaProject } | Should Throw 'call connect'
    }

    It 'leaves the change record as it is: nothing of the update is in TIA any more' {
        $null = Invoke-FakeUpdate 'T2' (New-Ending)
        $script:saved | Should Be 0
        $script:logged -join ' ' | Should Match 'TIA Portal ended at T2'
    }

    It 'says so as well when TIA does not answer after a failure' {
        $r = Invoke-FakeUpdate 'T1' ([System.InvalidOperationException]::new('TIA said no')) -GoneAfter
        $r.tiaEnded | Should Be $true
        $r.note | Should Match 'does not answer any more'
        { Get-TiaProject } | Should Throw 'call connect'
    }

    It 'tells a background session to close and open again, and leaves the window session alone' {
        $r = Invoke-FakeUpdate 'T1' (New-Ending) -Background
        $r.note | Should Match 'background_close, then background_open'
        $script:Bridge.tiaEnded | Should BeNullOrEmpty
    }

    It 'still reports a plain failure of one type, goes on with the next and saves the record' {
        $r = Invoke-FakeUpdate 'T2' ([System.InvalidOperationException]::new('TIA said no'))
        $r.ok | Should Be $false
        $r.Contains('tiaEnded') | Should Be $false
        $r.summary | Should Match 'could not put in work: T2 \(TIA said no\)'
        $script:putInWork -join ',' | Should Be 'T1,T2,T3'
        $script:saved | Should Not Be 0
        $script:Bridge.tiaEnded | Should BeNullOrEmpty
    }
}

Describe 'library_review when an export ends TIA' {
    function Find-LibraryType {
        $o = [pscustomobject]@{ }
        $o | Add-Member ScriptMethod GetSupportedExportFormats { @('SimaticSD', 'SimaticMLWithExportOptionsWithDefaults') }
        @{ name = 'T'; obj = $o }
    }
    function Export-LibraryTypeDocuments($Entry, [string]$Dir, [switch]$Released, [string]$Format = '', [string]$As = '') {
        $script:formats += @($Format)
        $f = $script:failures[$Format]
        if ($f) { throw $f }
    }

    It 'reaches the dispatch and does not export again on the TIA that is ending' {
        $script:formats = @(); $script:failures = @{ SimaticSD = (New-Ending) }
        { Export-ForReview 'lib' 'T' 'dir' } | Should Throw 'outer'
        $script:formats -join ',' | Should Be 'SimaticSD'
    }

    It 'reaches the dispatch when the SimaticML export after a refused SD export ends TIA' {
        $script:formats = @()
        $script:failures = @{ SimaticSD = [System.InvalidOperationException]::new('SD refused'); SimaticMLWithExportOptionsWithDefaults = (New-Ending) }
        { Export-ForReview 'lib' 'T' 'dir' } | Should Throw 'outer'
    }

    It 'keeps the fallback to SimaticML after a plain SD failure' {
        $script:formats = @(); $script:failures = @{ SimaticSD = [System.InvalidOperationException]::new('SD refused') }
        $r = Export-ForReview 'lib' 'T' 'dir'
        $r.ok | Should Be $true
        $r.format | Should Be 'xml'
        $r.note | Should Match 'SD refused'
    }
}
