$here = Split-Path -Parent $MyInvocation.MyCommand.Path
foreach ($f in 'Mcp.ps1', 'Tia.ps1', 'Repo.ps1', 'Rules.ps1', 'Guards.ps1', 'Bridge.ps1', 'Tools\Objects.ps1', 'Tools\Plc.ps1', 'Tools\Hmi.ps1', 'Tools\Library.ps1', 'Tools\LibraryChange.ps1') {
    . (Join-Path $here "..\$f")
}

# library_update_usages, library_release_chain and master_copy_to_project cannot tell beforehand which blocks they change,
# so they need safety: true on a PLC whose safety program TIA would let them change. Import and delete have their own
# tests, by the block (Import.Tests.ps1, Delete.Tests.ps1). The fake Openness: one SafetyAdministration per PLC.
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

function Get-TiaSoftwareList { $script:devices }
function Get-TiaProject { $script:fakeProject }
function Get-SafetyAdministration($Plc) { $script:admins[[string]$Plc.Name] }
function ConvertTo-ResultTree($r) { $r }
function Test-TiaAlive { $true }
function Get-UpdateScopes { @() }
function Add-LibraryLog { param($Line) }
function Get-LiveChange { $null }
function Get-KindRoot { 'root' }
function Find-LibraryType { @{ name = 'T'; folder = ''; obj = [Siemens.Engineering.Library.Types.FakeTypeSelection]::new() } }
function Get-InWorkTypes { $script:touched++; @{ types = @($script:inWork); complete = $true; walked = 0 } }
function Get-LibraryDependsOn { @{ graph = @{ T = @() }; complete = $true; walked = 1 } }
function Get-ReleaseVersion { '1.0.1' }
function Get-CompileErrors { @() }
function Invoke-CompileEveryDevice { $script:touched++; @{ items = @(); errors = 0 } }
function Select-TypeVersion {
    $v = [pscustomobject]@{ VersionNumber = '1.0.0' }
    $v | Add-Member ScriptMethod Release { param($mode, $number, $author, $comment) }
    $v
}
function Get-TiaLibrary {
    $l = [pscustomobject]@{ }
    $l | Add-Member ScriptMethod UpdateProject { param($s, $sc, $m) $script:touched++ }
    $l
}
function Find-MasterCopy {
    @{ obj = [pscustomobject]@{ ContentDescriptions = @([pscustomobject]@{ ContentType = [pscustomobject]@{ Name = $script:content }; ContentName = 'New' }) } }
}
function Get-OrCreateGroup {
    $script:touched++
    $c = [pscustomobject]@{ }
    $c | Add-Member ScriptMethod Find { param($n) $null }
    $c | Add-Member ScriptMethod CreateFrom { param($mc) [pscustomobject]@{ Name = 'New' } }
    [pscustomobject]@{ Blocks = $c; Types = $c; Groups = $c; TagTables = $c; Screens = $c }
}
function Invoke-TiaWrite([string]$Description, [scriptblock]$Body, [switch]$NoTransaction, [scriptblock]$RollbackIf, [switch]$OnCopy) {
    $script:touched++
    @{ output = @(& $Body); transaction = $true; rolledBack = $false; commitError = $null; note = $null }
}

# PasswordSet and LoggedOn $null: a state TIA does not answer.
function New-Admin($PasswordSet, $LoggedOn) { [pscustomobject]@{ IsSafetyOfflineProgramPasswordSet = $PasswordSet; IsLoggedOnToSafetyOfflineProgram = $LoggedOn } }

# Admins: PLC name -> its SafetyAdministration; a PLC left out has no safety program.
function Initialize-Project([hashtable]$Admins = @{ }, [string[]]$Plcs = @('PLC_1'), [switch]$NoArchive) {
    $script:admins = $Admins
    $script:devices = @(foreach ($p in $Plcs) { @{ device = $p; kind = 'plc'; software = [pscustomobject]@{ Name = $p } } }) +
                      @(@{ device = 'HMI_1'; kind = 'hmi'; software = [pscustomobject]@{ Name = 'HMI_1' } })
    $script:touched = 0; $script:inWork = @(@{ type = 'T'; inWork = '1.0.1' }); $script:content = 'FB'
    $script:fakeProject = [pscustomobject]@{ ProjectLibrary = [pscustomobject]@{ } }
    $script:fakeProject.ProjectLibrary | Add-Member ScriptMethod UpdateCheck { param($p, $m) @{ } }
    Initialize-BridgeContext @{ maxResponseChars = 20000 }
    Set-BridgeProject -Name 'P' -Path 'C:\P.ap20' -Repo (Join-Path $TestDrive ('R' + [guid]::NewGuid().ToString('N')))
    if (-not $NoArchive) { Register-Archive (Get-BridgeSession) }
}

function Invoke-Guarded([string]$Tool, $Safety = $null, [string]$Device = '') {
    switch ($Tool) {
        'library_update_usages' { Invoke-LibraryUpdateTool ([pscustomobject]@{ types = @('T'); safety = $Safety }) }
        'library_release_chain' { Invoke-LibraryReleaseChainTool ([pscustomobject]@{ comment = 'c'; safety = $Safety }) }
        'master_copy_to_project' { Invoke-MasterCopyToProjectTool ([pscustomobject]@{ name = 'M'; folder = 'F'; device = $Device; safety = $Safety }) }
    }
}

foreach ($tool in 'library_update_usages', 'library_release_chain', 'master_copy_to_project') {
    Describe "$tool on a PLC with a safety program" {
        It 'is refused when logged on, names the PLC and the flag, and touches nothing in TIA' {
            Initialize-Project @{ PLC_1 = (New-Admin $true $true) }
            $r = Invoke-Guarded $tool
            $r.ok | Should Be $false
            $r.refused | Should Match 'F-blocks'
            $r.refused | Should Match 'PLC_1'
            $r.refused | Should Match 'safety: true'
            $r.refused | Should Match 'user asked'
            $script:touched | Should Be 0
            @((Get-BridgeSession).pending.Keys).Count | Should Be 0
        }

        It 'is refused when the safety program has no password: TIA asks for no login then' {
            Initialize-Project @{ PLC_1 = (New-Admin $false $false) }
            (Invoke-Guarded $tool).refused | Should Match 'F-blocks'
            $script:touched | Should Be 0
        }

        It 'is refused when TIA does not answer the login state' {
            Initialize-Project @{ PLC_1 = (New-Admin $null $null) }
            (Invoke-Guarded $tool).refused | Should Match 'F-blocks'
            $script:touched | Should Be 0
        }

        It 'runs with safety: true' {
            Initialize-Project @{ PLC_1 = (New-Admin $true $true) }
            (Invoke-Guarded $tool -Safety $true).ok | Should Be $true
            $script:touched | Should BeGreaterThan 0
        }

        It 'takes the text false as no' {
            Initialize-Project @{ PLC_1 = (New-Admin $true $true) }
            (Invoke-Guarded $tool -Safety 'false').refused | Should Match 'F-blocks'
            $script:touched | Should Be 0
        }

        It 'runs without the flag while TIA keeps the safety program closed (password set, not logged on)' {
            Initialize-Project @{ PLC_1 = (New-Admin $true $false) }
            (Invoke-Guarded $tool).ok | Should Be $true
        }

        It 'answers the archive gate first' {
            Initialize-Project @{ PLC_1 = (New-Admin $true $true) } -NoArchive
            (Invoke-Guarded $tool).refused | Should Not Match 'F-blocks'
            $script:touched | Should Be 0
        }
    }

    Describe "$tool in a project without a safety program" {
        It 'runs without the flag' {
            Initialize-Project
            (Invoke-Guarded $tool).ok | Should Be $true
        }
    }
}

Describe 'the library tools touch every PLC' {
    foreach ($tool in 'library_update_usages', 'library_release_chain') {
        It "$tool is refused when another PLC than the first has the open safety program, and names only that one" {
            Initialize-Project -Plcs 'PLC_1', 'PLC_2', 'PLC_3' -Admins @{ PLC_1 = (New-Admin $true $false); PLC_2 = (New-Admin $true $true) }
            $r = Invoke-Guarded $tool
            $r.refused | Should Match 'PLC_2'
            $r.refused | Should Not Match 'PLC_1'
            $r.refused | Should Not Match 'PLC_3'
        }
    }
}

Describe 'master_copy_to_project looks at what it places, and where' {
    It 'counts only the PLC it places on' {
        Initialize-Project -Plcs 'PLC_1', 'PLC_2' -Admins @{ PLC_2 = (New-Admin $true $true) }
        (Invoke-Guarded 'master_copy_to_project' -Device 'PLC_1').ok | Should Be $true
        (Invoke-Guarded 'master_copy_to_project' -Device 'PLC_2').refused | Should Match 'PLC_2'
    }

    foreach ($content in 'FC', 'OB', 'GlobalDB', 'InstanceDB', 'PlcBlockUserGroup', 'PlcType', 'PlcTypeUserGroup') {
        It "refuses $content`: it can hold or be part of the safety program" {
            Initialize-Project @{ PLC_1 = (New-Admin $true $true) }
            $script:content = $content
            (Invoke-Guarded 'master_copy_to_project').refused | Should Match 'F-blocks'
        }
    }

    foreach ($content in 'PlcTagTable', 'Screen') {
        It "places $content without the flag: it holds no F-block" {
            Initialize-Project @{ PLC_1 = (New-Admin $true $true) }
            $script:content = $content
            (Invoke-Guarded 'master_copy_to_project').ok | Should Be $true
        }
    }
}
