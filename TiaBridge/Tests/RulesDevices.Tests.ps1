$here = Split-Path -Parent $MyInvocation.MyCommand.Path
foreach ($f in 'Mcp.ps1', 'Tia.ps1', 'Repo.ps1', 'Rules.ps1', 'Guards.ps1', 'Bridge.ps1', 'Tools\Objects.ps1', 'Tools\Plc.ps1', 'Tools\Library.ps1', 'Tools\LibraryChange.ps1', 'Tools\Session.ps1') {
    . (Join-Path $here "..\$f")
}

# The save rules count per device: each tool that writes or compiles names the device it resolved, and the library
# tools every device they touch. Rules.Tests.ps1 tests the rules themselves.
if (-not ('Siemens.Engineering.Compiler.ICompilable' -as [type])) {
    Add-Type -TypeDefinition 'namespace Siemens.Engineering.Compiler { public interface ICompilable { object Compile(); } }'
}
if (-not ('Siemens.Engineering.Library.Types.LibraryTypeInstanceInfo' -as [type])) {
    Add-Type -TypeDefinition 'namespace Siemens.Engineering.Library.Types { public class LibraryTypeInstanceInfo { } }'
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
if (-not ('Siemens.Engineering.Library.Types.CreateOrReleaseDependenciesMode' -as [type])) {
    Add-Type -TypeDefinition 'namespace Siemens.Engineering.Library.Types { public enum CreateOrReleaseDependenciesMode { AutomaticallyCreateOrReleaseDependenciesIfRequired, DoNotAutomaticallyCreateOrReleaseDependencies } }'
}
if (-not ('Siemens.Engineering.Library.MasterCopies.MasterCopyMode' -as [type])) {
    Add-Type -TypeDefinition 'namespace Siemens.Engineering.Library.MasterCopies { public enum MasterCopyMode { ThrowIfExists, Replace, Rename } }'
}

# Software of a device whose compile records the device, with the errors $script:errorsOn gives it.
function New-Software([string]$Device, [string[]]$Blocks = @()) {
    $sw = [pscustomobject]@{ Name = $Device; compiler = $null
        BlockGroup = [pscustomobject]@{ Blocks = @(); Groups = @() }
        TypeGroup = [pscustomobject]@{ Types = @(); Groups = @() } }
    $c = [pscustomobject]@{ device = $Device }
    $c | Add-Member ScriptMethod Compile { $script:compiled += @($this.device); @{ errors = [int]$script:errorsOn[$this.device]; warnings = 0 } }
    $sw.compiler = $c
    $sw.BlockGroup.Blocks = @(foreach ($b in $Blocks) {
        $bc = [pscustomobject]@{ device = "$Device/$b" }
        $bc | Add-Member ScriptMethod Compile { $script:compiled += @($this.device); @{ errors = 0; warnings = 0 } }
        [pscustomobject]@{ Name = $b; compiler = $bc; IsConsistent = $true }
    })
    $sw
}

function Get-TiaSoftwareList { $script:devices }
function Get-TiaProject { $script:fakeProject }
function Get-TiaService($Obj, [type]$Type) { if ($Type.Name -eq 'ICompilable') { $Obj.compiler } }
function ConvertTo-ResultTree($r) { $r }
function Test-TiaAlive { $true }
function Get-UpdateScopes { @() }
function Get-SafetyAdministration { $null }
function Add-LibraryLog { param($Line) }
function Invoke-TiaWrite([string]$Description, [scriptblock]$Body, [switch]$NoTransaction, [scriptblock]$RollbackIf, [switch]$OnCopy) {
    @{ output = @(& $Body); transaction = $true; rolledBack = $false; commitError = $null; note = $null }
}

function New-KindItems { foreach ($n in 'A', 'B') { $o = [pscustomobject]@{ Name = $n }; $o | Add-Member ScriptMethod Delete { }; @{ name = $n; folder = ''; obj = $o } } }
Register-ObjectKind 'fakeplc' @{
    scope = 'plc'; dir = 'plc\fake'; defaultOverride = $true; description = 'test PLC kind'
    items = { param($root) New-KindItems }
    import = { param($root, $folder, $file, $override) @{ ok = $true } }
    tree = { param($root) 'top' }; groups = 'Groups'
}
Register-ObjectKind 'fakehmi' @{
    scope = 'hmi'; dir = 'hmi\fake'; defaultOverride = $true; description = 'test HMI kind'
    items = { param($root) New-KindItems }
    import = { param($root, $folder, $file, $override) @{ ok = $true } }
}
Register-ObjectKind 'fakelib' @{
    scope = 'library'; dir = 'library\fake'; defaultOverride = $true; description = 'test library kind'
    items = { param($root) @() }
    import = { param($root, $folder, $file, $override) @{ ok = $true; scope = 'plc' } }
}

# Without a session archive unless Archived: the refusals of the save rules are those of such a session.
function Initialize-Project([object[]]$Devices, [switch]$Archived) {
    $script:devices = $Devices
    $script:compiled = @(); $script:errorsOn = @{}; $script:saved = 0
    $script:fakeProject = [pscustomobject]@{ ProjectLibrary = [pscustomobject]@{ } }
    $script:fakeProject.ProjectLibrary | Add-Member ScriptMethod UpdateCheck { param($p, $m) @{ } }
    $script:fakeProject | Add-Member ScriptMethod Save { $script:saved++ }
    Initialize-BridgeContext @{ maxResponseChars = 20000 }
    $repo = Join-Path $TestDrive ('R' + [guid]::NewGuid().ToString('N'))
    Set-BridgeProject -Name 'P' -Path 'C:\P.ap20' -Repo $repo
    Register-Archive (Get-BridgeSession) -Skipped:(-not $Archived)
    $repo
}
function New-TwoPlcs { Initialize-Project @(
    @{ device = 'PLC_1'; kind = 'plc'; software = (New-Software 'PLC_1' @('A', 'B')) },
    @{ device = 'PLC_2'; kind = 'plc'; software = (New-Software 'PLC_2' @('A', 'B')) }) }
function New-TwoPlcsTwoHmis { Initialize-Project @(
    @{ device = 'PLC_1'; kind = 'plc'; software = (New-Software 'PLC_1') },
    @{ device = 'PLC_2'; kind = 'plc'; software = (New-Software 'PLC_2') },
    @{ device = 'HMI_A'; kind = 'hmi'; software = (New-Software 'HMI_A') },
    @{ device = 'HMI_B'; kind = 'hmi'; software = (New-Software 'HMI_B') }) }
function Import-Into([string]$Repo, [string]$Kind, [string]$Dir, [string]$Device) {
    Write-TextFile (Join-Path $Repo "$Dir\A.xml") 'x'
    Invoke-ImportTool ([pscustomobject]@{ kind = $Kind; device = $Device; paths = @("$Dir\A.xml") })
}
function Get-Blockers { (Test-SaveAllowed (Get-BridgeSession)) -join ' ' }
function Get-Pending { @((Get-BridgeSession).pending.Values | Sort-Object) -join ',' }
function Get-Failed { @((Get-BridgeSession).failed.Values | Sort-Object) -join ',' }

Describe 'save with two PLCs' {
    It 'is refused after an import into PLC_2 and a clean compile of PLC_1, until PLC_2 compiles clean' {
        $repo = New-TwoPlcs
        (Import-Into $repo 'fakeplc' 'plc\PLC_2\fake' 'PLC_2').ok | Should Be $true
        (Invoke-CompileTool ([pscustomobject]@{ scope = 'plc'; device = 'PLC_1' })).ok | Should Be $true
        $script:compiled -join ',' | Should Be 'PLC_1'
        $r = Invoke-SaveTool ([pscustomobject]@{ reason = 'test' })
        $r.ok | Should Be $false
        @($r.blockers) -join ' ' | Should Match 'plc@PLC_2:A'
        $script:saved | Should Be 0
        (Invoke-CompileTool ([pscustomobject]@{ scope = 'plc'; device = 'PLC_2' })).ok | Should Be $true
        (Invoke-SaveTool ([pscustomobject]@{ reason = 'test' })).ok | Should Be $true
        $script:saved | Should Be 1
    }

    It 'is refused while the last compile of PLC_2 had errors, whatever PLC_1 compiles' {
        $null = New-TwoPlcs
        $script:errorsOn['PLC_2'] = 1
        (Invoke-CompileTool ([pscustomobject]@{ scope = 'plc'; device = 'PLC_2' })).ok | Should Be $false
        (Invoke-CompileTool ([pscustomobject]@{ scope = 'plc'; device = 'PLC_1' })).ok | Should Be $true
        $r = Invoke-SaveTool ([pscustomobject]@{ reason = 'test' })
        $r.ok | Should Be $false
        @($r.blockers) -join ' ' | Should Match "'plc@PLC_2' reported errors"
    }

    It 'counts a compile of blocks for the device passed, not for a block of that name on the other PLC' {
        $repo = New-TwoPlcs
        $null = Import-Into $repo 'fakeplc' 'plc\PLC_1\fake' 'PLC_1'
        $null = Import-Into $repo 'fakeplc' 'plc\PLC_2\fake' 'PLC_2'
        (Invoke-CompileTool ([pscustomobject]@{ scope = 'blocks'; names = @('A'); device = 'PLC_2' })).ok | Should Be $true
        $script:compiled -join ',' | Should Be 'PLC_2/A'
        Get-Pending | Should Be 'plc@PLC_1:A'
    }

    It 'without a session archive a delete counts for its device, and needs a compile of that device' {
        $null = New-TwoPlcs
        $r = Invoke-DeleteTool ([pscustomobject]@{ kind = 'fakeplc'; names = @('B'); device = 'PLC_2' })
        $r.ok | Should Be $true
        $r.next | Should Match 'compile the plc scope'
        Get-Pending | Should Be 'plc@PLC_2:B'
        $s = Invoke-SaveTool ([pscustomobject]@{ reason = 'test' })
        $s.ok | Should Be $false
        @($s.blockers) -join ' ' | Should Match 'plc@PLC_2:B'
        (Invoke-CompileTool ([pscustomobject]@{ scope = 'plc'; device = 'PLC_2' })).ok | Should Be $true
        (Invoke-SaveTool ([pscustomobject]@{ reason = 'test' })).ok | Should Be $true
    }

    It 'keeps the device name as TIA has it when the argument differs in case' {
        $repo = New-TwoPlcs
        $null = Import-Into $repo 'fakeplc' 'plc\PLC_2\fake' 'plc_2'
        Get-Pending | Should Be 'plc@PLC_2:A'
        $null = Invoke-CompileTool ([pscustomobject]@{ scope = 'plc'; device = 'PLC_2' })
        Get-Pending | Should Be ''
    }
}

Describe 'a failed import of a library type' {
    # TIA has T; the import throws while $script:libThrows, as CreateFromDocuments does, so the failure has no scope
    Register-ObjectKind 'fakelibt' @{
        scope = 'library'; dir = 'library\faket'; defaultOverride = $true; description = 'test library kind with a type'
        items = { param($root) @{ name = 'T'; folder = ''; obj = [pscustomobject]@{ Name = 'T' } } }
        import = { param($root, $folder, $file, $override) if ($script:libThrows) { throw 'broken document' }; @{ ok = $true; scope = 'plc' } }
    }
    function Import-Type([string]$Repo) {
        Write-TextFile (Join-Path $Repo 'library\faket\T.xml') 'x'
        Invoke-ImportTool ([pscustomobject]@{ kind = 'fakelibt'; paths = @('library\faket\T.xml') })
    }

    It 'is cleared by its good import, though that one has a scope and the failure had none' {
        $repo = New-TwoPlcs
        $script:libThrows = $true
        (Import-Type $repo).ok | Should Be $false
        Get-Failed | Should Be 'type:T'
        Get-Blockers | Should Match 'type:T'
        $script:libThrows = $false
        (Import-Type $repo).ok | Should Be $true
        Get-Failed | Should Be ''
        Get-Pending | Should Be 'plc@PLC_1:T,plc@PLC_2:T'
    }

    It 'refuses the save until then, also with a session archive, and not after' {
        $repo = Initialize-Project -Archived @(@{ device = 'PLC_1'; kind = 'plc'; software = (New-Software 'PLC_1') })
        $script:libThrows = $true
        $null = Import-Type $repo
        (Invoke-SaveTool ([pscustomobject]@{ reason = 'test' })).ok | Should Be $false
        $script:libThrows = $false
        $null = Import-Type $repo
        $r = Invoke-SaveTool ([pscustomobject]@{ reason = 'test' })
        $r.ok | Should Be $true
        @($r.savedWith[0].notCompiled) -join ',' | Should Be 'T'
    }
}

Describe 'a failed import' {
    # fails every file; TIA has A and B, plus what $script:leftBehind names (no transaction: the failure left it there)
    Register-ObjectKind 'fakefail' @{
        scope = 'plc'; dir = 'plc\fail'; defaultOverride = $true; description = 'test PLC kind that fails'
        items = { param($root) New-KindItems; foreach ($n in @($script:leftBehind)) { if ($script:failedOnce) { @{ name = $n; folder = ''; obj = $null } } } }
        import = { param($root, $folder, $file, $override) $script:failedOnce = $true; @{ ok = $false; error = 'broken' } }
    }
    function Import-Failing([string]$Repo, [string]$Name) {
        Write-TextFile (Join-Path $Repo "plc\fail\$Name.xml") 'x'
        Invoke-ImportTool ([pscustomobject]@{ kind = 'fakefail'; device = 'PLC_1'; paths = @("plc\fail\$Name.xml") })
    }
    function New-Failing { $script:leftBehind = @(); $script:failedOnce = $false; New-TwoPlcs }

    It 'of a name never created holds nothing, and says so' {
        $repo = New-Failing
        $r = Import-Failing $repo 'New'
        $r.ok | Should Be $false
        $r.next | Should Match 'Nothing of it is in TIA'
        Get-Pending | Should Be ''
        Get-Failed | Should Be ''
        Get-Blockers | Should Be ''
    }

    It 'of a name never created also drops what an older session held for it' {
        $repo = New-Failing
        Register-Write (Get-BridgeSession) 'plc' 'PLC_1' @(@{ name = 'New'; ok = $false })
        $null = Import-Failing $repo 'New'
        Get-Failed | Should Be ''
    }

    It 'that left the name there counts as failed' {
        $repo = New-Failing
        $script:leftBehind = @('New')
        $null = Import-Failing $repo 'New'
        Get-Failed | Should Be 'plc@PLC_1:New'
        Get-Pending | Should Be ''
    }

    It 'over an existing object counts as failed, not as pending' {
        $repo = New-Failing
        $null = Import-Failing $repo 'A'
        Get-Failed | Should Be 'plc@PLC_1:A'
        Get-Pending | Should Be ''
        Get-Blockers | Should Match 'failed'
    }

    It 'keeps a write before it pending' {
        $repo = New-Failing
        $null = Import-Into $repo 'fakeplc' 'plc\PLC_1\fake' 'PLC_1'
        $null = Import-Failing $repo 'A'
        Get-Pending | Should Be 'plc@PLC_1:A'
        Get-Failed | Should Be 'plc@PLC_1:A'
    }
}

Describe 'save with a session archive, errors elsewhere on the PLC' {
    function New-ArchivedPlcs { Initialize-Project -Archived @(
        @{ device = 'PLC_1'; kind = 'plc'; software = (New-Software 'PLC_1' @('A', 'B')) },
        @{ device = 'PLC_2'; kind = 'plc'; software = (New-Software 'PLC_2' @('A', 'B')) }) }

    It 'without an archive a block this session neither wrote nor named does not refuse: the save names it and says there is no way back' {
        New-TwoPlcs
        $s = Get-BridgeSession
        Register-Archive $s -Skipped
        Register-Write $s -Scope plc -Device PLC_1 -Items @(@{ name = 'Mine'; ok = $true })
        Register-Compile $s -Scope plc -Device PLC_1 -Names @('Mine') -ErrorCount 0 -NotConsistent ([string[]]@('Others'))
        $r = Invoke-SaveTool ([pscustomobject]@{ reason = 'test' })
        $r.ok | Should Be $true
        @($r.savedWith[0].notConsistent.names) -join ',' | Should Be 'Others'
        $r.note | Should Match 'no way back'
        $r.note | Should Not Match 'archives'
        $r.note | Should Match 'names shows at most ten, what this session wrote or named first, list shows them all'
        $r.note | Should Not Match 'messages and names'
    }

    It 'saves over a write not compiled and names it per device, once' {
        $repo = New-ArchivedPlcs
        $null = Import-Into $repo 'fakeplc' 'plc\PLC_2\fake' 'PLC_2'
        $r = Invoke-SaveTool ([pscustomobject]@{ reason = 'test' })
        $r.ok | Should Be $true
        $script:saved | Should Be 1
        @($r.savedWith).Count | Should Be 1
        $r.savedWith[0].device | Should Be 'plc@PLC_2'
        @($r.savedWith[0].notCompiled) -join ',' | Should Be 'A'
        $r.note | Should Match 'Quote it to the user'
        $again = Invoke-SaveTool ([pscustomobject]@{ reason = 'test' })
        $again.ok | Should Be $true
        $again.ContainsKey('savedWith') | Should Be $false
        $again.ContainsKey('note') | Should Be $false
    }

    It 'saves over a delete not compiled, and names it' {
        $null = New-ArchivedPlcs
        $null = Invoke-DeleteTool ([pscustomobject]@{ kind = 'fakeplc'; names = @('B'); device = 'PLC_2' })
        $r = Invoke-SaveTool ([pscustomobject]@{ reason = 'test' })
        $r.ok | Should Be $true
        $r.savedWith[0].device | Should Be 'plc@PLC_2'
        @($r.savedWith[0].notCompiled) -join ',' | Should Be 'B'
    }

    It 'says that the rest of the errors are in the compile logs' {
        $null = New-ArchivedPlcs
        Register-Compile (Get-BridgeSession) -Scope plc -Device PLC_1 -ErrorCount 12 -Messages @(1..12 | ForEach-Object { "e$_" })
        $r = Invoke-SaveTool ([pscustomobject]@{ reason = 'test' })
        $r.savedWith[0].compileErrors.errors | Should Be 12
        @($r.savedWith[0].compileErrors.messages).Count | Should Be 10
        $r.note | Should Match 'at most ten'
        $r.note | Should Match '_compile\.json'
    }

    It 'saves over the errors of a compile elsewhere, and names them with their text' {
        $null = New-ArchivedPlcs
        $script:errorsOn['PLC_1'] = 1
        function Get-CompileErrors { @{ object = 'Other'; description = 'broken'; path = 'Other' } }
        function Get-CompileErrorTexts { 'Other: broken' }
        (Invoke-CompileTool ([pscustomobject]@{ scope = 'plc'; device = 'PLC_1' })).ok | Should Be $false
        $status = Get-SessionSummary
        @($status.saveBlockers).Count | Should Be 0
        @($status.saveStanding)[0].device | Should Be 'plc@PLC_1'
        $r = Invoke-SaveTool ([pscustomobject]@{ reason = 'test' })
        $r.ok | Should Be $true
        $script:saved | Should Be 1
        $r.savedWith[0].compileErrors.errors | Should Be 1
        @($r.savedWith[0].compileErrors.messages) -join ',' | Should Be 'Other: broken'
    }

    It 'turns a compile tree and a refused item into one line each' {
        $tree = @{ messages = @(@{ path = 'Other (FB1)'; state = 'Error'; description = 'broken' }) }
        $items = @(@{ name = 'PLC software'; errors = 1; messages = $tree }, @{ name = 'X'; refused = 'no compile service' }, @{ name = 'Y'; errors = 0 })
        @(Get-CompileErrorTexts $items) -join '|' | Should Be 'Other: broken|X: no compile service'
    }

    It 'still refuses a failed write, without sending anyone to compile' {
        $null = New-ArchivedPlcs
        Register-Write (Get-BridgeSession) 'plc' 'PLC_1' @(@{ name = 'A'; ok = $false })
        $r = Invoke-SaveTool ([pscustomobject]@{ reason = 'test' })
        $r.ok | Should Be $false
        @($r.blockers) -join ' ' | Should Match 'plc@PLC_1:A'
        $r.hint | Should Not Match 'compile'
        $script:saved | Should Be 0
    }
}

Describe 'save with several HMI devices' {
    It 'is refused after an import into HMI_B and a clean compile of HMI_A, until HMI_B compiles clean' {
        $repo = New-TwoPlcsTwoHmis
        (Import-Into $repo 'fakehmi' 'hmi\HMI_B\fake' 'HMI_B').ok | Should Be $true
        $null = Invoke-CompileTool ([pscustomobject]@{ scope = 'hmi'; device = 'HMI_A' })
        Get-Blockers | Should Match 'hmi@HMI_B:A'
        $null = Invoke-CompileTool ([pscustomobject]@{ scope = 'hmi'; device = 'HMI_B' })
        Get-Blockers | Should Be ''
    }
}

Describe 'save in a project with one device' {
    It 'names the device, though the tools get no device argument' {
        $repo = Initialize-Project @(@{ device = 'PLC_1'; kind = 'plc'; software = (New-Software 'PLC_1') })
        Write-TextFile (Join-Path $repo 'plc\fake\A.xml') 'x'
        $null = Invoke-ImportTool ([pscustomobject]@{ kind = 'fakeplc'; paths = @('plc\fake\A.xml') })
        Get-Blockers | Should Match 'plc@PLC_1:A'
        $null = Invoke-CompileTool ([pscustomobject]@{ scope = 'plc' })
        Get-Blockers | Should Be ''
    }
}

Describe 'library writes count for every device of the scope' {
    function Get-TiaLibrary { $script:fakeLibrary }
    function New-FakeLibrary([string]$UpdateThrows = '') {
        $l = [pscustomobject]@{ throws = $UpdateThrows }
        $l | Add-Member ScriptMethod UpdateProject { param($s, $sc, $m) if ($this.throws) { throw $this.throws } }
        $script:fakeLibrary = $l
    }
    function Find-LibraryType { @{ name = 'T'; folder = ''; obj = [Siemens.Engineering.Library.Types.FakeTypeSelection]::new() } }
    function Get-InWorkTypes { @{ types = @($script:inWork); complete = $true; walked = 0 } }
    function Get-LibraryDependsOn { @{ graph = @{ T = @() }; complete = $true; walked = 1 } }
    function Get-LiveChange { $script:liveChange }
    function Get-VersionList { @() }
    function Format-Instances { @() }
    function Get-ReleaseVersion { '1.0.1' }
    function Update-ChangeAtRelease { $null }
    function Save-ChangeRecord { 'library\changes\c1.md' }
    function New-Version {
        $v = [pscustomobject]@{ VersionNumber = '1.0.0' }
        $v | Add-Member ScriptMethod Release { param($mode, $number, $author, $comment) }
        $v | Add-Member ScriptMethod Edit { param($info) if ($script:editThrows) { throw 'no edit' } }
        $v
    }
    $script:inWork = @(); $script:liveChange = $null; $script:editThrows = $false

    It 'import of library type documents' {
        $repo = New-TwoPlcsTwoHmis
        Write-TextFile (Join-Path $repo 'library\fake\T\T.s7dcl') 'x'
        (Invoke-ImportTool ([pscustomobject]@{ kind = 'fakelib'; paths = @('library\fake\T\T.s7dcl') })).ok | Should Be $true
        Get-Pending | Should Be 'plc@PLC_1:T,plc@PLC_2:T'
    }

    It 'library_update_usages: every device of every scope' {
        $null = New-TwoPlcsTwoHmis
        New-FakeLibrary
        (Invoke-LibraryUpdateTool ([pscustomobject]@{ types = @('T') })).ok | Should Be $true
        Get-Pending | Should Be 'hmi@HMI_A:library update,hmi@HMI_B:library update,plc@PLC_1:library update,plc@PLC_2:library update'
    }

    It 'library_update_usages that fails counts as failed on every device' {
        $null = New-TwoPlcsTwoHmis
        New-FakeLibrary -UpdateThrows 'TIA said no'
        { Invoke-LibraryUpdateTool ([pscustomobject]@{ types = @('T') }) } | Should Throw 'TIA said no'
        Get-Failed | Should Be 'hmi@HMI_A:library update,hmi@HMI_B:library update,plc@PLC_1:library update,plc@PLC_2:library update'
    }

    It 'library_update_usages compiles every PLC for a library change and counts the types it puts in work on each' {
        $null = New-TwoPlcs
        New-FakeLibrary
        $script:liveChange = [ordered]@{ id = 'c1'; root = 'T1'; types = [ordered]@{ T1 = @{ inWork = '' } } }
        function Get-CompileErrors { @{ object = 'T1'; description = 'incompatible changes' } }
        function Set-TypeInWork($Library, [string]$Name) { '1.0.1' }
        try { $r = Invoke-LibraryUpdateTool ([pscustomobject]@{ types = @('T') }) } finally { $script:liveChange = $null }
        $r.ok | Should Be $true
        (@($script:compiled) | Sort-Object) -join ',' | Should Be 'PLC_1,PLC_2'
        Get-Pending | Should Be 'plc@PLC_1:type:T1,plc@PLC_2:type:T1'
    }

    It 'library_release_type: every device of the type''s scope' {
        $null = New-TwoPlcsTwoHmis
        New-FakeLibrary
        function Select-TypeVersion { New-Version }
        (Invoke-LibraryReleaseTool ([pscustomobject]@{ name = 'T'; comment = 'c' })).ok | Should Be $true
        Get-Pending | Should Be 'plc@PLC_1:type:T,plc@PLC_2:type:T'
    }

    It 'library_edit_type: every device of the type''s scope; a failure counts on each' {
        $null = New-TwoPlcs
        New-FakeLibrary
        function Select-TypeVersion([object[]]$Versions, [switch]$InWork) { if ($InWork -and -not $script:edited) { return $null }; New-Version }
        function Get-TypeInstances { @{ device = 'PLC_2'; name = 'I'; info = 'info' } }
        function Register-ChangeOnEdit { $null }
        $script:edited = $false
        $script:editThrows = $true
        try { { Invoke-LibraryEditTool ([pscustomobject]@{ name = 'T' }) } | Should Throw 'no edit' } finally { $script:editThrows = $false }
        Get-Failed | Should Be 'plc@PLC_1:type:T,plc@PLC_2:type:T'
    }

    It 'library_release_chain compiles every PLC, and the save is allowed only after that' {
        $null = New-TwoPlcs
        New-FakeLibrary
        $script:inWork = @(@{ type = 'T'; inWork = '1.0.1' })
        function Select-TypeVersion { New-Version }
        function Get-CompileErrors { @() }
        try { $r = Invoke-LibraryReleaseChainTool ([pscustomobject]@{ comment = 'c' }) } finally { $script:inWork = @() }
        $r.ok | Should Be $true
        (@($script:compiled) | Sort-Object) -join ',' | Should Be 'PLC_1,PLC_1,PLC_2,PLC_2'
        Get-Blockers | Should Be ''
    }

    It 'library_release_chain stops on the compile errors of the second PLC' {
        $null = New-TwoPlcs
        New-FakeLibrary
        $script:inWork = @(@{ type = 'T'; inWork = '1.0.1' })
        $script:errorsOn['PLC_2'] = 1
        function Select-TypeVersion { New-Version }
        function Get-CompileErrors { @{ object = 'Other'; description = 'broken'; path = 'Other' } }
        try { $r = Invoke-LibraryReleaseChainTool ([pscustomobject]@{ comment = 'c' }) } finally { $script:inWork = @() }
        $r.ok | Should Be $false
        Get-Blockers | Should Match "'plc@PLC_2' reported errors"
    }

    It 'a library type of a scope the project has no device of counts only when it fails' {
        $null = Initialize-Project @(@{ device = 'PLC_1'; kind = 'plc'; software = (New-Software 'PLC_1') })
        New-FakeLibrary
        function Select-TypeVersion { New-Version }
        function Get-LibraryTypeScope { 'hmi' }
        (Invoke-LibraryReleaseTool ([pscustomobject]@{ name = 'T'; comment = 'c' })).ok | Should Be $true
        Get-Blockers | Should Be ''
    }

    It 'master_copy_to_project counts for the device it placed on' {
        $null = New-TwoPlcs
        function Find-MasterCopy { @{ obj = [pscustomobject]@{ ContentDescriptions = @([pscustomobject]@{ ContentType = [pscustomobject]@{ Name = 'FB' }; ContentName = 'New' }) } } }
        function Get-MasterCopyTarget { @{ kind = 'fakeplc'; composition = 'Blocks' } }
        function Get-OrCreateGroup {
            $c = [pscustomobject]@{ }
            $c | Add-Member ScriptMethod Find { param($n) $null }
            $c | Add-Member ScriptMethod CreateFrom { param($mc) [pscustomobject]@{ Name = 'New' } }
            [pscustomobject]@{ Blocks = $c }
        }
        (Invoke-MasterCopyToProjectTool ([pscustomobject]@{ name = 'M'; device = 'PLC_2' })).ok | Should Be $true
        Get-Pending | Should Be 'plc@PLC_2:mc:M'
    }
}

Describe 'a session file with the old keys, read when a project is bound' {
    It 'counts for every device the binding names' {
        $repo = Join-Path $TestDrive 'OldKeys'
        Write-TextFile (Join-Path $repo '.tiabridge-session.json') '{ "pending": { "plc:a": "plc:A" }, "failed": { }, "compileErrors": { "hmi": true } }'
        Initialize-BridgeContext @{ maxResponseChars = 20000 }
        Set-BridgeProject -Name 'P' -Path 'C:\P.ap20' -Repo $repo -Software @(@{ device = 'PLC_1'; kind = 'plc' }, @{ device = 'PLC_2'; kind = 'plc' }, @{ device = 'HMI_A'; kind = 'hmi' })
        Get-Pending | Should Be 'plc@PLC_1:A,plc@PLC_2:A'
        Get-Blockers | Should Match "'hmi@HMI_A' reported errors"
    }
}

Describe 'session keys of a device the project no longer has' {
    function Set-Project([string]$Name, [string]$Json, $Software) {
        $repo = Join-Path $TestDrive $Name
        Write-TextFile (Join-Path $repo '.tiabridge-session.json') $Json
        Initialize-BridgeContext @{ maxResponseChars = 20000 }
        if ($null -eq $Software) { return @(Set-BridgeProject -Name $Name -Path "C:\$Name.ap20" -Repo $repo) }
        @(Set-BridgeProject -Name $Name -Path "C:\$Name.ap20" -Repo $repo -Software $Software)
    }
    $one = @(@{ device = 'PLC_1'; kind = 'plc' }, @{ device = 'HMI_1'; kind = 'hmi' })
    $json = '{ "pending": { "plc@old:a": "plc@Old:A", "plc@plc_1:b": "plc@PLC_1:B", "plc@plc_1x:c": "plc@PLC_1x:C" }, ' +
            '"failed": { "hmi@gone:s": "hmi@Gone:S", "library:mc:m": "mc:M" }, "compileErrors": { "plc@Old": true, "plc@OldClean": false, "hmi@HMI_1": true } }'

    It 'drops them, keeps the rest, and returns what it dropped' {
        $dropped = Set-Project 'A' $json $one
        ($dropped | Sort-Object) -join ',' | Should Be 'hmi@Gone:S,plc@Old,plc@Old:A,plc@PLC_1x:C'
        $s = Get-BridgeSession
        @($s.pending.Values) -join ',' | Should Be 'plc@PLC_1:B'
        @($s.failed.Values) -join ',' | Should Be 'mc:M'
        @($s.compileErrors.Keys) -join ',' | Should Be 'hmi@HMI_1'
    }

    It 'lets a save through once the devices the project has are compiled' {
        $null = Set-Project 'B' '{ "pending": { "plc@old:a": "plc@Old:A" }, "failed": { }, "compileErrors": { "plc@Old": true } }' $one
        @(Test-SaveAllowed (Get-BridgeSession)).Count | Should Be 0
    }

    It 'knows the device whatever its case' {
        $null = Set-Project 'C' '{ "pending": { "plc@plc_1:b": "plc@PLC_1:B" }, "failed": { }, "compileErrors": { "plc@plc_1": true } }' $one
        (Get-BridgeSession).pending.Count | Should Be 1
        (Get-BridgeSession).compileErrors.Count | Should Be 1
    }

    It 'drops the keys of the only PLC when the project has none left' {
        $null = Set-Project 'D' '{ "pending": { "plc@plc_1:b": "plc@PLC_1:B" }, "failed": { }, "compileErrors": { } }' @(@{ device = 'HMI_1'; kind = 'hmi' })
        (Get-BridgeSession).pending.Count | Should Be 0
    }

    It 'leaves the keys alone when the devices are not known' {
        $dropped = Set-Project 'E' $json $null
        @($dropped).Count | Should Be 0
        (Get-BridgeSession).pending.Count | Should Be 3
    }

    It 'drops them also at a connect of the same bridge process, when the session is already held' {
        $null = Set-Project 'F' '{ "pending": { "plc@plc_2:b": "plc@PLC_2:B" }, "failed": { }, "compileErrors": { } }' @(@{ device = 'PLC_2'; kind = 'plc' })
        (Get-BridgeSession).pending.Count | Should Be 1
        $dropped = @(Set-BridgeProject -Name 'F' -Path 'C:\F.ap20' -Repo (Join-Path $TestDrive 'F') -Software $one)
        $dropped -join ',' | Should Be 'plc@PLC_2:B'
        (Get-BridgeSession).pending.Count | Should Be 0
    }
}
