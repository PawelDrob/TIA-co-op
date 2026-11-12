$here = Split-Path -Parent $MyInvocation.MyCommand.Path
foreach ($f in 'Mcp.ps1', 'Tia.ps1', 'Repo.ps1', 'Rules.ps1', 'Guards.ps1', 'Bridge.ps1', 'Tools\Objects.ps1', 'Tools\Plc.ps1', 'Tools\Library.ps1', 'Tools\Hmi.ps1', 'Tools\FullExport.ps1') { . (Join-Path $here "..\$f") }

# A batch import is all or nothing (decided 2026-10-05: FBs that depend on each other go in together).
# Stand-ins: a fake object kind, and Invoke-TiaWrite that runs the body and honours -RollbackIf like the real one.
function Get-KindRoot { 'root' }
function Get-TiaSoftwareList { @(@{ device = 'PLC_1'; kind = 'plc' }, @{ device = 'HMI_1'; kind = 'hmi' }) }
function Get-TiaService { $null }
function Test-TiaAlive { -not $script:tiaGone }
if (-not ('FakeSiemens.NonRecoverableException' -as [type])) {
    Add-Type -TypeDefinition 'namespace FakeSiemens { public class NonRecoverableException : System.Exception { public NonRecoverableException(string m) : base(m) { } } }'
}
if (-not ('Siemens.Engineering.ImportOptions' -as [type])) {
    Add-Type -TypeDefinition 'namespace Siemens.Engineering { public enum ImportOptions { None, Override } }'
}
function Invoke-TiaWrite([string]$Description, [scriptblock]$Body, [switch]$NoTransaction, [scriptblock]$RollbackIf) {
    $out = @(& $Body)
    $rb = [bool]($RollbackIf -and (& $RollbackIf))
    $script:committed = -not $rb
    @{ output = $out; transaction = $true; rolledBack = $rb; commitError = $null; note = $null }
}

Register-ObjectKind 'fake' @{
    scope = 'plc'; dir = 'plc\fake'; defaultOverride = $true; description = 'test kind'
    items = { param($root) @(@{ name = 'Exists'; folder = 'F'; obj = [pscustomobject]@{} }) }
    import = { param($root, $folder, $file, $override)
        $script:imported += @($file.name)
        if ($file.name -eq 'Bad') { throw [System.InvalidOperationException]::new('TIA said no') }
        if ($file.name -eq 'Ends') { throw [System.Management.Automation.MethodInvocationException]::new('outer', [FakeSiemens.NonRecoverableException]::new('The dependent property DialFillStyle has an invalid value.')) }
        if ($file.name -eq 'Partial') { return @{ ok = $false; messages = @{ state = 'Failure' } } }
        @{ ok = $true } }
}

Register-ObjectKind 'fakelib' @{
    scope = 'library'; dir = 'library\fake'; defaultOverride = $true; description = 'test library kind'
    items = { param($root) @() }
    import = { param($root, $folder, $file, $override) @{ ok = $true; scope = 'plc' } }
}

Describe 'import of a kind that has no import' {
    function Invoke-ImportOfKind([string]$Kind) {
        $repo = Join-Path $TestDrive "NoImport$Kind"
        $null = New-Item -ItemType Directory -Force $repo
        Initialize-BridgeContext @{ maxResponseChars = 20000 }
        Set-BridgeProject -Name 'P' -Path 'C:\P.ap20' -Repo $repo
        Register-Archive (Get-BridgeSession)
        Invoke-ImportTool ([pscustomobject]@{ kind = $Kind; paths = @('Any.xml') })
    }
    foreach ($kind in 'system_block', 'technology_object', 'graphic', 'hmi_slidein', 'hmi_screen_global', 'hmi_graphiclist', 'hmi_vbscript', 'hmi_connection') {
        It "$kind is export only, and no library tool is named as the way to change it" {
            $r = Invoke-ImportOfKind $kind
            $r.ok | Should Be $false
            $r.refused | Should Be "Kind $kind is export only; the bridge does not import it."
        }
    }
    It 'master_copy changes through the library tools, and says so' {
        $r = Invoke-ImportOfKind 'master_copy'
        $r.ok | Should Be $false
        $r.refused | Should Match '^Kind master_copy cannot be imported\. Library objects change through the library tools'
    }
}

Describe 'import of library type documents' {
    It 'counts as a write of the scope the type reports, so a compile of the PLC clears it' {
        $repo = Join-Path $TestDrive 'L'
        Write-TextFile (Join-Path $repo 'library\fake\T\T.s7dcl') 'x'
        Initialize-BridgeContext @{ maxResponseChars = 20000 }
        Set-BridgeProject -Name 'P' -Path 'C:\P.ap20' -Repo $repo
        Register-Archive (Get-BridgeSession)
        $r = Invoke-ImportTool ([pscustomobject]@{ kind = 'fakelib'; paths = @('library\fake\T\T.s7dcl') })
        $r.ok | Should Be $true
        $r.next | Should Match 'compile the plc scope'
        @((Get-BridgeSession).pending.Values) -join ' ' | Should Match 'plc@PLC_1:T'
    }
    function Add-LibraryLog { }
    It 'brings up what an import made in the PLC beside the type, in the fields and next' {
        Register-ObjectKind 'fakecopies' @{
            scope = 'library'; dir = 'library\fakecopies'; defaultOverride = $true; description = 'test library kind'
            items = { param($root) @() }
            import = { param($root, $folder, $file, $override) @{ ok = $true; scope = 'plc'; copiesBack = @(@{ object = 'S_1'; type = 'S' }) } }
            afterImport = { param($result, $items) Add-CopiesBackFacts $result $items }
        }
        $repo = Join-Path $TestDrive 'LC'
        Write-TextFile (Join-Path $repo 'library\fakecopies\T\T.s7dcl') 'x'
        Initialize-BridgeContext @{ maxResponseChars = 20000 }
        Set-BridgeProject -Name 'P' -Path 'C:\P.ap20' -Repo $repo
        Register-Archive (Get-BridgeSession)
        $r = Invoke-ImportTool ([pscustomobject]@{ kind = 'fakecopies'; paths = @('library\fakecopies\T\T.s7dcl') })
        @($r.copiesBack)[0].object | Should Be 'S_1'
        $r.next | Should Match 'compile the plc scope, then save'
        $r.next | Should Match 'The import brought these into the PLC: S_1'
    }
    It 'says nothing of them when the batch was rolled back' {
        Register-ObjectKind 'fakecopies2' @{
            scope = 'library'; dir = 'library\fakecopies2'; defaultOverride = $true; description = 'test library kind'
            items = { param($root) @() }
            import = { param($root, $folder, $file, $override)
                if ($file.name -eq 'Bad') { throw 'TIA said no' }
                @{ ok = $true; scope = 'plc'; copiesBack = @(@{ object = 'S_1'; type = 'S' }) } }
            afterImport = { param($result, $items) Add-CopiesBackFacts $result $items }
        }
        $repo = Join-Path $TestDrive 'LC2'
        foreach ($n in 'A', 'Bad') { Write-TextFile (Join-Path $repo "library\fakecopies2\$n\$n.s7dcl") 'x' }
        Initialize-BridgeContext @{ maxResponseChars = 20000 }
        Set-BridgeProject -Name 'P' -Path 'C:\P.ap20' -Repo $repo
        Register-Archive (Get-BridgeSession)
        $r = Invoke-ImportTool ([pscustomobject]@{ kind = 'fakecopies2'; paths = @('library\fakecopies2\A\A.s7dcl', 'library\fakecopies2\Bad\Bad.s7dcl') })
        $r.Contains('copiesBack') | Should Be $false
        $r.next | Should Not Match 'brought'
        foreach ($i in @($r.items)) { $i.Contains('copiesBack') | Should Be $false }
    }
}

Describe 'import of a batch' {
    $repo = Join-Path $TestDrive 'R'
    foreach ($n in 'A', 'Bad', 'Partial', 'C') { Write-TextFile (Join-Path $repo "plc\fake\$n.xml") 'x' }

    function Invoke-Batch([string[]]$Names) {
        Initialize-BridgeContext @{ maxResponseChars = 20000 }
        Set-BridgeProject -Name 'P' -Path 'C:\P.ap20' -Repo $repo
        Register-Archive (Get-BridgeSession)
        $script:imported = @(); $script:committed = $null
        Invoke-ImportTool ([pscustomobject]@{ kind = 'fake'; paths = @($Names | ForEach-Object { "plc\fake\$_.xml" }) })
    }

    It 'imports and commits a batch whose files all pass' {
        $r = Invoke-Batch @('A', 'C')
        $r.ok | Should Be $true
        ($script:imported -join ',') | Should Be 'A,C'
        $script:committed | Should Be $true
    }

    It 'stops at the first file TIA rejects and rolls the whole batch back' {
        $r = Invoke-Batch @('A', 'Bad', 'C')
        $r.ok | Should Be $false
        $r.rolledBack | Should Be $true
        ($script:imported -join ',') | Should Be 'A,Bad'
        $script:committed | Should Be $false
        $r.items[0].rolledBack | Should Be $true
        $r.items[1].error.message | Should Be 'TIA said no'
        $r.items[2].notAttempted | Should Be $true
    }

    It 'rolls back as well when a file fails without an exception' {
        $r = Invoke-Batch @('A', 'Partial', 'C')
        $r.rolledBack | Should Be $true
        $script:committed | Should Be $false
        $r.items[2].notAttempted | Should Be $true
    }

    It 'refuses a file its kind precheck rejects (the faceplate guard) before any write, with the precheck details' {
        Register-ObjectKind 'fakehmi' @{
            scope = 'hmi'; dir = 'plc\fake'; defaultOverride = $true; description = 'test kind with a precheck'
            items = { param($root) @() }
            precheck = { param($file, $cache) $cache.calls = [int]$cache.calls + 1
                if ($file.name -eq 'Bad') { @{ ok = $false; refused = 'Faceplate type check failed'; faceplates = @(@{ type = 'fp'; available = @('0.0.2') }) } } }
            import = { param($root, $folder, $file, $override) $script:imported += @($file.name); @{ ok = $true } }
        }
        Initialize-BridgeContext @{ maxResponseChars = 20000 }
        Set-BridgeProject -Name 'P' -Path 'C:\P.ap20' -Repo $repo
        Register-Archive (Get-BridgeSession)
        $script:imported = @(); $script:committed = $null
        $r = Invoke-ImportTool ([pscustomobject]@{ kind = 'fakehmi'; paths = @('plc\fake\A.xml', 'plc\fake\Bad.xml') })
        $r.ok | Should Be $false
        @($script:imported).Count | Should Be 0
        $script:committed | Should BeNullOrEmpty
        $r.items[1].refused | Should Match 'Faceplate'
        $r.items[1].faceplates[0].available[0] | Should Be '0.0.2'
    }

    It 'imports nothing when a file is refused before TIA, and says which' {
        $r = Invoke-Batch @('A', 'Missing', 'C')
        $r.ok | Should Be $false
        @($script:imported).Count | Should Be 0
        $r.items[1].refused | Should Match 'not found'
        $r.items[0].notAttempted | Should Be $true
        $r.refused | Should Match 'Missing'
    }
}

# A refused HMI import throws NonRecoverableException and TIA ends its process seconds later.
Describe 'import that ends TIA' {
    $repo = Join-Path $TestDrive 'E'
    foreach ($n in 'A', 'Ends', 'Bad', 'C') { Write-TextFile (Join-Path $repo "plc\fake\$n.xml") 'x' }

    function Invoke-Ending([string[]]$Names, [switch]$Background) {
        Initialize-BridgeContext @{ maxResponseChars = 20000 }
        Set-BridgeProject -Name 'P' -Path 'C:\P.ap20' -Repo $repo
        if ($Background) { $script:Bridge.background = @{ write = $true; session = (New-SessionState) } }
        Register-Archive (Get-BridgeSession)
        $script:imported = @(); $script:committed = $null
        Invoke-ImportTool ([pscustomobject]@{ kind = 'fake'; paths = @($Names | ForEach-Object { "plc\fake\$_.xml" }) })
    }

    It 'says TIA ended instead of rolled back, gives no next step and refuses TIA calls until connect' {
        $r = Invoke-Ending @('A', 'Ends', 'C')
        $r.ok | Should Be $false
        $r.tiaEnded | Should Be $true
        $r.Contains('next') | Should Be $false
        $r.Contains('rolledBack') | Should Be $false
        $r.note | Should Match 'TIA Portal ended at Ends'
        $r.note | Should Match 'NonRecoverableException'
        $r.note | Should Match 'call connect'
        $r.items[0].lost | Should Be $true
        $r.items[0].Contains('rolledBack') | Should Be $false
        $r.items[1].error.tiaEnded | Should Be $true
        $r.items[2].notAttempted | Should Be $true
        { Get-TiaProject } | Should Throw 'call connect'
        @((Get-BridgeSession).pending.Keys).Count | Should Be 0
    }

    It 'says so as well when TIA does not answer after a failure' {
        $script:tiaGone = $true
        try { $r = Invoke-Ending @('A', 'Bad') } finally { $script:tiaGone = $false }
        $r.tiaEnded | Should Be $true
        $r.note | Should Match 'does not answer any more'
    }

    It 'tells a background session to close and open again, and leaves the window session alone' {
        $r = Invoke-Ending @('Ends') -Background
        $r.note | Should Match 'background_close, then background_open'
        $r.note | Should Match 'last save'
        $script:Bridge.tiaEnded | Should BeNullOrEmpty
    }

    It 'still reports a plain failure as rolled back' {
        $r = Invoke-Ending @('A', 'Bad')
        $r.Contains('tiaEnded') | Should Be $false
        $r.rolledBack | Should Be $true
        $script:Bridge.tiaEnded | Should BeNullOrEmpty
    }
}

# F-blocks need safety: true; know-how protected blocks are not overwritten (an Override replaced such a block unprotected when tried).
Describe 'import of F-blocks and know-how protected blocks' {
    Register-ObjectKind 'fakeguard' @{
        scope = 'plc'; dir = 'plc\guard'; defaultOverride = $true; description = 'test kind with F and protected blocks'
        items = { param($root) @(
            @{ name = 'Ffb'; folder = ''; obj = [pscustomobject]@{ ProgrammingLanguage = 'F_LAD'; IsKnowHowProtected = $false } }
            @{ name = 'Khp'; folder = ''; obj = [pscustomobject]@{ ProgrammingLanguage = 'LAD'; IsKnowHowProtected = $true } }
            @{ name = 'Std'; folder = ''; obj = [pscustomobject]@{ ProgrammingLanguage = 'LAD'; IsKnowHowProtected = $false } }) }
        import = { param($root, $folder, $file, $override) $script:imported += @($file.name); @{ ok = $true } }
    }
    Register-ObjectKind 'fakeguardlib' @{
        scope = 'library'; dir = 'library\guard'; defaultOverride = $true; description = 'test library kind'
        items = { param($root) @() }
        import = { param($root, $folder, $file, $override) $script:imported += @($file.name); @{ ok = $true; scope = 'plc' } }
    }
    Register-ObjectKind 'fakeguardhmi' @{
        scope = 'hmi'; dir = 'hmi\guard'; defaultOverride = $true; description = 'test HMI kind'
        items = { param($root) @() }
        import = { param($root, $folder, $file, $override) $script:imported += @($file.name); @{ ok = $true } }
    }
    $repo = Join-Path $TestDrive 'G'
    $safe = "{ S7_Safety := `"True`" }`r`nFUNCTION_BLOCK `"X`"`r`nEND_FUNCTION_BLOCK"
    foreach ($n in 'Ffb', 'Khp', 'Std', 'NewStd') { Write-TextFile (Join-Path $repo "plc\guard\$n.s7dcl") "FUNCTION_BLOCK `"$n`"`r`nEND_FUNCTION_BLOCK" }
    Write-TextFile (Join-Path $repo 'plc\guard\NewF.s7dcl') $safe
    Write-TextFile (Join-Path $repo 'plc\guard\NewFXml.xml') '<Document><ProgrammingLanguage>F_FBD</ProgrammingLanguage></Document>'
    Write-TextFile (Join-Path $repo 'library\guard\TypeF\TypeF.s7dcl') $safe
    Write-TextFile (Join-Path $repo 'hmi\guard\Screen.xml') '<Document><ProgrammingLanguage>F_LAD</ProgrammingLanguage></Document>'

    function Invoke-Guarded([string[]]$Paths, $Extra = @{}, [string]$Kind = 'fakeguard') {
        Initialize-BridgeContext @{ maxResponseChars = 20000 }
        Set-BridgeProject -Name 'P' -Path 'C:\P.ap20' -Repo $repo
        Register-Archive (Get-BridgeSession)
        $script:imported = @(); $script:committed = $null
        $a = @{ kind = $Kind; paths = $Paths }
        foreach ($key in $Extra.Keys) { $a[$key] = $Extra[$key] }
        Invoke-ImportTool ([pscustomobject]$a)
    }

    It 'refuses a file over an existing F-block without safety, even when the file itself has no F mark' {
        $r = Invoke-Guarded @('plc\guard\Ffb.s7dcl')
        $r.ok | Should Be $false
        $r.items[0].refused | Should Match 'F-block'
        $r.items[0].refused | Should Match 'safety: true'
        @($script:imported).Count | Should Be 0
    }

    It 'refuses a new F-block by its .s7dcl or SimaticML document without safety' {
        (Invoke-Guarded @('plc\guard\NewF.s7dcl')).items[0].refused | Should Match 'safety: true'
        (Invoke-Guarded @('plc\guard\NewFXml.xml')).items[0].refused | Should Match 'safety: true'
        @($script:imported).Count | Should Be 0
    }

    It 'refuses the document of a library type that is an F-block, without safety' {
        (Invoke-Guarded @('library\guard\TypeF\TypeF.s7dcl') @{} 'fakeguardlib').items[0].refused | Should Match 'safety: true'
        @($script:imported).Count | Should Be 0
    }

    It 'imports nothing of a batch that holds an F-block without safety' {
        $r = Invoke-Guarded @('plc\guard\NewStd.s7dcl', 'plc\guard\NewF.s7dcl')
        $r.ok | Should Be $false
        $r.items[0].notAttempted | Should Be $true
        @($script:imported).Count | Should Be 0
    }

    It 'imports F-blocks with safety: true' {
        $r = Invoke-Guarded @('plc\guard\Ffb.s7dcl', 'plc\guard\NewF.s7dcl', 'plc\guard\NewFXml.xml') @{ safety = $true }
        $r.ok | Should Be $true
        $script:imported -join ',' | Should Be 'Ffb,NewF,NewFXml'
    }

    It 'takes safety false, or the text false, as no' {
        (Invoke-Guarded @('plc\guard\NewF.s7dcl') @{ safety = $false }).items[0].refused | Should Match 'safety: true'
        (Invoke-Guarded @('plc\guard\NewF.s7dcl') @{ safety = 'false' }).items[0].refused | Should Match 'safety: true'
        @($script:imported).Count | Should Be 0
    }

    It 'refuses override of a know-how protected block, and safety: true does not lift it' {
        $r = Invoke-Guarded @('plc\guard\Khp.s7dcl')
        $r.items[0].refused | Should Match 'know-how protected'
        (Invoke-Guarded @('plc\guard\Khp.s7dcl') @{ safety = $true }).items[0].refused | Should Match 'know-how protected'
        @($script:imported).Count | Should Be 0
    }

    It 'still imports standard blocks without safety, and does not read HMI documents for the guard' {
        $r = Invoke-Guarded @('plc\guard\Std.s7dcl', 'plc\guard\NewStd.s7dcl')
        $r.ok | Should Be $true
        $script:imported -join ',' | Should Be 'Std,NewStd'
        (Invoke-Guarded @('hmi\guard\Screen.xml') @{} 'fakeguardhmi').ok | Should Be $true
    }
}

# A refusal protected the object and changed nothing, so it holds nothing for the save rules.
Describe 'import the bridge refuses before TIA is asked, and the save' {
    Register-ObjectKind 'fakerefuse' @{
        scope = 'plc'; dir = 'plc\refuse'; defaultOverride = $true; description = 'test kind that refuses inside the write'
        items = { param($root) foreach ($n in 'No', 'Partial', 'Bad') { @{ name = $n; folder = ''; obj = [pscustomobject]@{ ProgrammingLanguage = 'LAD'; IsKnowHowProtected = $false } } } }
        import = { param($root, $folder, $file, $override)
            $script:imported += @($file.name)
            if ($file.name -in 'No', 'NewNo') { return @{ ok = $false; refused = 'Not in this format.' } }
            if ($file.name -eq 'Partial') { return @{ ok = $false; messages = @{ state = 'Failure' } } }
            if ($file.name -eq 'Bad') { throw 'TIA said no' }
            @{ ok = $true } }
    }
    Register-ObjectKind 'fakerefuselib' @{
        scope = 'library'; dir = 'library\refuse'; defaultOverride = $true; description = 'test library kind that refuses inside the write'
        items = { param($root) @(@{ name = 'T'; folder = ''; obj = [pscustomobject]@{ ProgrammingLanguage = 'LAD'; IsKnowHowProtected = $false } }) }
        import = { param($root, $folder, $file, $override) @{ ok = $false; refused = 'No version in work.' } }
    }
    $repo = Join-Path $TestDrive 'Refuse'
    foreach ($n in 'A', 'No', 'NewNo', 'Partial', 'Bad') { Write-TextFile (Join-Path $repo "plc\refuse\$n.xml") 'x' }
    Write-TextFile (Join-Path $repo 'library\refuse\T\T.xml') 'x'

    function Invoke-RefuseKindImport([string[]]$Names) {
        $script:imported = @()
        Invoke-ImportTool ([pscustomobject]@{ kind = 'fakerefuse'; paths = @($Names | ForEach-Object { "plc\refuse\$_.xml" }) })
    }
    BeforeEach {
        Initialize-BridgeContext @{ maxResponseChars = 20000 }
        Set-BridgeProject -Name 'P' -Path 'C:\P.ap20' -Repo $repo
        Register-Archive (Get-BridgeSession)
    }

    It 'holds nothing for an object the kind refused inside the write, and says TIA was not asked' {
        $r = Invoke-RefuseKindImport @('No')
        $s = Get-BridgeSession
        $r.ok | Should Be $false
        $r.items[0].refused | Should Be 'Not in this format.'
        @(Test-SaveAllowed $s).Count | Should Be 0
        $s.failed.Count | Should Be 0
        $s.pending.Count | Should Be 0
        $s.written.Count | Should Be 0
        $r.rolledBack | Should Be $false
        $r.note | Should Be 'Nothing imported: No was refused before TIA was asked.'
        $r.next | Should Match 'Nothing of it is in TIA'
    }

    It 'says what TIA did roll back when files before the refused one reached it' {
        $r = Invoke-RefuseKindImport @('A', 'No', 'Partial')
        $s = Get-BridgeSession
        ($script:imported -join ',') | Should Be 'A,No'
        $r.rolledBack | Should Be $true
        $r.items[0].rolledBack | Should Be $true
        $r.note | Should Be 'Nothing imported: No was refused before TIA was asked, and TIA rolled back the files before it.'
        @(Test-SaveAllowed $s).Count | Should Be 0
        $s.pending.Count | Should Be 0
    }

    It 'keeps what was on record for that object: a refusal is no write, good or bad' {
        $s = Get-BridgeSession
        Register-Write $s -Scope 'plc' -Device 'PLC_1' -Items @(@{ name = 'No'; ok = $false })
        Register-Write $s -Scope 'plc' -Device 'PLC_1' -Items @(@{ name = 'NewNo'; ok = $true })
        Invoke-RefuseKindImport @('No') | Out-Null
        @(Test-SaveAllowed $s) -join ' ' | Should Match 'plc@PLC_1:No'
        Invoke-RefuseKindImport @('NewNo') | Out-Null
        @($s.pending.Values) -join ' ' | Should Match 'plc@PLC_1:NewNo'
    }

    It 'holds nothing for a library type the kind refused' {
        $r = Invoke-ImportTool ([pscustomobject]@{ kind = 'fakerefuselib'; paths = @('library\refuse\T\T.xml') })
        $r.items[0].refused | Should Be 'No version in work.'
        @(Test-SaveAllowed (Get-BridgeSession)).Count | Should Be 0
    }

    It 'still refuses the save after a write that reached TIA and failed: <name>' -TestCases @(@{ name = 'Bad' }, @{ name = 'Partial' }) {
        param($name)
        $r = Invoke-RefuseKindImport @($name)
        $r.note | Should Match 'rolled the batch back'
        $r.rolledBack | Should Be $true
        @(Test-SaveAllowed (Get-BridgeSession)) -join ' ' | Should Match "A write failed and was not redone successfully: plc@PLC_1:$name"
    }

    Context 'without a transaction' {
        function Invoke-TiaWrite([string]$Description, [scriptblock]$Body, [switch]$NoTransaction, [scriptblock]$RollbackIf) {
            @{ output = @(& $Body); transaction = $false; rolledBack = $false; commitError = $null; note = $null }
        }

        It 'says only the refusal when it is the first file' {
            $r = Invoke-RefuseKindImport @('No')
            $r.note | Should Be 'Nothing imported: No was refused before TIA was asked.'
            $r.rolledBack | Should Be $false
            @(Test-SaveAllowed (Get-BridgeSession)).Count | Should Be 0
        }

        It 'says the files before it stay, and they count as written' {
            $r = Invoke-RefuseKindImport @('A', 'No')
            $r.note | Should Be 'No was refused before TIA was asked. No transaction: the files before it stay imported.'
            @((Get-BridgeSession).pending.Values) -join ' ' | Should Be 'plc@PLC_1:A'
            $r.next | Should Match 'compile the plc scope'
        }

        It 'still names a failure that reached TIA as before' {
            $r = Invoke-RefuseKindImport @('A', 'Bad')
            $r.note | Should Be 'No transaction: the files before the failure stay imported.'
        }
    }

    # new folders: a check inside the write ran after Get-OrCreateGroup had made the folder
    It 'makes no folder for a new block whose .s7dcl the line scan refuses, and holds nothing' {
        function Get-GroupTree { @() }
        function Get-OrCreateGroup { $script:groupsMade++; [pscustomobject]@{ Blocks = 'blocks' } }
        $script:groupsMade = 0
        Write-TextFile (Join-Path $repo 'plc\blocks\sub\New.s7dcl') "FUNCTION_BLOCK `"New`"`r`n/*`r`nORGANIZATION_BLOCK in a comment`r`n*/`r`nEND_FUNCTION_BLOCK"
        $r = Invoke-ImportTool ([pscustomobject]@{ kind = 'block'; paths = @('plc\blocks\sub\New.s7dcl') })
        $r.items[0].refused | Should Match 'event class'
        $script:groupsMade | Should Be 0
        @(Test-SaveAllowed (Get-BridgeSession)).Count | Should Be 0
    }

    It 'makes no folder for a new tag table that is no SimaticML' {
        function Get-GroupTree { @() }
        function Get-OrCreateGroup { $script:groupsMade++; [pscustomobject]@{ TagTables = 'tables' } }
        $script:groupsMade = 0
        Write-TextFile (Join-Path $repo 'plc\tags\sub\New.s7dcl') 'x'
        $r = Invoke-ImportTool ([pscustomobject]@{ kind = 'plc_tag_table'; paths = @('plc\tags\sub\New.s7dcl') })
        $r.items[0].refused | Should Match 'SimaticML'
        $script:groupsMade | Should Be 0
    }

    # the case first seen, and the two not tried then: the checks before the write
    It 'lets the save through after the .s7dcl of an OB, and after an F-block and a know-how protected block refused' {
        Register-ObjectKind 'fakerefuseplan' @{
            scope = 'plc'; dir = 'plc\plan'; defaultOverride = $true; description = 'test kind with an OB, an F-block and a protected block'
            items = { param($root) @(
                @{ name = 'SomeOb'; folder = ''; obj = [pscustomobject]@{ ProgrammingLanguage = 'LAD'; IsKnowHowProtected = $false } }
                @{ name = 'Ffb'; folder = ''; obj = [pscustomobject]@{ ProgrammingLanguage = 'F_LAD'; IsKnowHowProtected = $false } }
                @{ name = 'Khp'; folder = ''; obj = [pscustomobject]@{ ProgrammingLanguage = 'LAD'; IsKnowHowProtected = $true } }) }
            import = { param($root, $folder, $file, $override) $script:imported += @($file.name); @{ ok = $true } }
        }
        Write-TextFile (Join-Path $repo 'plc\plan\SomeOb.s7dcl') "ORGANIZATION_BLOCK `"SomeOb`"`r`nEND_ORGANIZATION_BLOCK"
        foreach ($n in 'Ffb', 'Khp') { Write-TextFile (Join-Path $repo "plc\plan\$n.s7dcl") "FUNCTION_BLOCK `"$n`"`r`nEND_FUNCTION_BLOCK" }
        $reasons = @{ SomeOb = 'event class'; Ffb = 'F-block'; Khp = 'know-how protected' }
        foreach ($n in $reasons.Keys) {
            $script:imported = @()
            $r = Invoke-ImportTool ([pscustomobject]@{ kind = 'fakerefuseplan'; paths = @("plc\plan\$n.s7dcl") })
            $r.items[0].refused | Should Match $reasons[$n]
            @($script:imported).Count | Should Be 0
            @(Test-SaveAllowed (Get-BridgeSession)).Count | Should Be 0
        }
    }
}

# A row naming a symbol the PLC does not have: TIA answers the import OK and leaves the table not consistent with no rows,
# the good ones gone too (docs\agent\openness-v20.md). The kind reads IsConsistent of what Import returned and
# fails the item, so the batch rolls back. It never reads Entries there: counting them inside the transaction ended TIA.
Describe 'import of watch tables' {
    $repo = Join-Path $TestDrive 'W'
    function Write-WatchTable([string]$Path, [string]$Name, [string]$Row = '"Tag_1"') {
        Write-TextFile (Join-Path $repo $Path) ("<?xml version=`"1.0`" encoding=`"utf-8`"?>`r`n<Document><SW.WatchAndForceTables.PlcWatchTable ID=`"0`">" +
            "<AttributeList><Name>$Name</Name></AttributeList><ObjectList><SW.WatchAndForceTables.PlcWatchTableEntry ID=`"1`" CompositionName=`"Entries`">" +
            "<AttributeList><Name>$Row</Name></AttributeList></SW.WatchAndForceTables.PlcWatchTableEntry></ObjectList></SW.WatchAndForceTables.PlcWatchTable></Document>")
    }
    Write-WatchTable 'plc\watchtables\Good.xml' 'Good'
    Write-WatchTable 'plc\watchtables\Broken.xml' 'Broken' '"Data".noSuchMember'
    Write-WatchTable 'plc\watchtables\GoodBroken.xml' 'Good' '"Data".noSuchMember'
    Write-WatchTable 'plc\watchtables\sub\New.xml' 'New'
    Write-TextFile (Join-Path $repo 'plc\watchtables\Fb1.xml') '<Document><SW.Blocks.FB ID="0"><AttributeList><Name>Fb1</Name></AttributeList></SW.Blocks.FB></Document>'
    Write-TextFile (Join-Path $repo 'plc\watchtables\Good.s7dcl') 'x'

    # a table as TIA returns it; reading its rows counts, and throws
    function New-WatchTable([string]$Name, [bool]$Consistent = $true) {
        $t = [pscustomobject]@{ Name = $Name; IsConsistent = $Consistent }
        Add-Member -InputObject $t ScriptProperty Entries { $script:entriesRead++; throw 'Entries read' }
        Add-Member -InputObject $t ScriptMethod Delete { $script:deleted += @($this.Name) }
        $t
    }
    # the PLC holds the table Good; an imported file whose row names noSuchMember comes back not consistent
    function Get-KindRoot {
        $tables = New-Object System.Collections.ArrayList
        [void]$tables.Add((New-WatchTable 'Good'))
        Add-Member -InputObject $tables ScriptMethod Import { param($file, $options)
            $text = [System.IO.File]::ReadAllText($file.FullName)
            $name = [regex]::Match($text, '<Name>([^<]*)</Name>').Groups[1].Value
            $script:imported += @("$name $options")
            , @(New-WatchTable $name ($text -notmatch 'noSuchMember')) }
        $groups = New-Object System.Collections.ArrayList
        Add-Member -InputObject $groups ScriptMethod Find { param($n) $null }
        Add-Member -InputObject $groups ScriptMethod Create { param($n) $script:groupsMade += @($n); [pscustomobject]@{ WatchTables = $script:tables; Groups = @() } }
        $script:tables = $tables
        [pscustomobject]@{ WatchAndForceTableGroup = [pscustomobject]@{ WatchTables = $tables; Groups = $groups } }
    }
    function Invoke-WatchImport([string[]]$Paths) {
        $script:imported = @(); $script:groupsMade = @(); $script:entriesRead = 0; $script:committed = $null
        Invoke-ImportTool ([pscustomobject]@{ kind = 'watch_table'; paths = $Paths })
    }
    BeforeEach {
        Initialize-BridgeContext @{ maxResponseChars = 20000 }
        Set-BridgeProject -Name 'P' -Path 'C:\P.ap20' -Repo $repo
        Register-Archive (Get-BridgeSession)
    }

    It 'imports a table over the existing one and a new one into the folder its path mirrors, with Override' {
        $r = Invoke-WatchImport @('plc\watchtables\Good.xml', 'plc\watchtables\sub\New.xml')
        $r.ok | Should Be $true
        $script:imported -join ',' | Should Be 'Good Override,New Override'
        $script:groupsMade -join ',' | Should Be 'sub'
        $r.items[1].folder | Should Be 'sub'
        $script:committed | Should Be $true
        $script:entriesRead | Should Be 0
    }

    It 'rolls back a table TIA leaves not consistent, names it and says why, and never reads its rows' {
        $r = Invoke-WatchImport @('plc\watchtables\Good.xml', 'plc\watchtables\Broken.xml')
        $r.ok | Should Be $false
        $r.rolledBack | Should Be $true
        $script:committed | Should Be $false
        $r.items[0].rolledBack | Should Be $true
        $r.items[1].error.message | Should Match "watch table 'Broken' not consistent, with none of its rows"
        $r.items[1].error.message | Should Match 'symbol the PLC does not have'
        $r.items[1].Contains('imported') | Should Be $false
        $r.note | Should Be 'Nothing imported: Broken failed and TIA rolled the batch back.'
        $script:entriesRead | Should Be 0
    }

    It 'goes by the name the document declares: a broken file over the existing table names that table' {
        $r = Invoke-WatchImport @('plc\watchtables\GoodBroken.xml')
        $r.rolledBack | Should Be $true
        $r.items[0].name | Should Be 'Good'
        $r.items[0].error.message | Should Match "watch table 'Good' not consistent"
    }

    It 'refuses the save after a rolled-back failure over the existing table too, until it is imported good' {
        $r = Invoke-WatchImport @('plc\watchtables\GoodBroken.xml')
        $r.rolledBack | Should Be $true
        @(Test-SaveAllowed (Get-BridgeSession)) -join ' ' | Should Match 'A write failed and was not redone successfully: plc@PLC_1:Good'
        $null = Invoke-WatchImport @('plc\watchtables\Good.xml')
        @(Test-SaveAllowed (Get-BridgeSession)) -join ' ' | Should Not Match 'failed'
    }

    It 'holds nothing for a new table rolled back: it is not in the project' {
        $r = Invoke-WatchImport @('plc\watchtables\Broken.xml')
        $r.rolledBack | Should Be $true
        $r.next | Should Match 'Nothing of it is in TIA'
        @(Test-SaveAllowed (Get-BridgeSession)).Count | Should Be 0
    }

    Context 'without a transaction' {
        function Invoke-TiaWrite([string]$Description, [scriptblock]$Body, [switch]$NoTransaction, [scriptblock]$RollbackIf) {
            @{ output = @(& $Body); transaction = $false; rolledBack = $false; commitError = $null; note = $null }
        }
        It 'refuses the save while the table TIA emptied is not imported good' {
            $r = Invoke-WatchImport @('plc\watchtables\GoodBroken.xml')
            $r.rolledBack | Should Be $false
            $r.items[0].error.message | Should Match "watch table 'Good' not consistent"
            @(Test-SaveAllowed (Get-BridgeSession)) -join ' ' | Should Match 'A write failed and was not redone successfully: plc@PLC_1:Good'
            $null = Invoke-WatchImport @('plc\watchtables\Good.xml')
            @(Test-SaveAllowed (Get-BridgeSession)) -join ' ' | Should Not Match 'failed'
        }
    }

    It 'refuses a file that is no SimaticML, and a block document, before TIA is asked' {
        $r = Invoke-WatchImport @('plc\watchtables\Good.s7dcl')
        $r.items[0].refused | Should Match 'SimaticML'
        $r = Invoke-WatchImport @('plc\watchtables\Fb1.xml')
        $r.items[0].refused | Should Match 'holds an FB or FC: import it with kind block, not watch_table'
        @($script:imported).Count | Should Be 0
    }

    It 'deletes a table by name' {
        $script:deleted = @()
        $r = Invoke-DeleteTool ([pscustomobject]@{ kind = 'watch_table'; names = @('Good') })
        $r.ok | Should Be $true
        $script:deleted -join ',' | Should Be 'Good'
    }
}

# A PLC has one force table, and TIA makes no other: a file of another name answers "'Create' is not supported by type
# '...PlcForceTableComposition'" (docs\agent\openness-v20.md). ForceIntention is read-only, so no file arms a force: the
# import writes the offline table only. The kind checks the table TIA returns as watch tables do.
Describe 'import of force tables' {
    $repo = Join-Path $TestDrive 'Fo'
    # Format: the row carries a DisplayFormat, as an export writes it
    function Write-ForceTable([string]$Path, [string]$Name, [string]$Row = '%Q0.0:P', [switch]$Format) {
        $f = if ($Format) { '<DisplayFormat>Bool</DisplayFormat>' }
        Write-TextFile (Join-Path $repo $Path) ("<?xml version=`"1.0`" encoding=`"utf-8`"?>`r`n<Document><SW.WatchAndForceTables.PlcForceTable ID=`"0`">" +
            "<AttributeList><Name>$Name</Name></AttributeList><ObjectList><SW.WatchAndForceTables.PlcForceTableEntry ID=`"1`" CompositionName=`"Entries`">" +
            "<AttributeList><Address>$Row</Address>$f<ForceValue>TRUE</ForceValue></AttributeList></SW.WatchAndForceTables.PlcForceTableEntry></ObjectList></SW.WatchAndForceTables.PlcForceTable></Document>")
    }
    Write-ForceTable 'plc\forcetables\Force table.xml' 'Force table'
    Write-ForceTable 'plc\forcetables\Broken.xml' 'Force table' '"Data".noSuchMember'
    Write-ForceTable 'plc\forcetables\BrokenFormat.xml' 'Force table' '"Data".noSuchMember' -Format
    Write-ForceTable 'plc\forcetables\Other.xml' 'Other'
    Write-TextFile (Join-Path $repo 'plc\forcetables\Watch1.xml') '<Document><SW.WatchAndForceTables.PlcWatchTable ID="0"><AttributeList><Name>Watch1</Name></AttributeList></SW.WatchAndForceTables.PlcWatchTable></Document>'
    Write-TextFile (Join-Path $repo 'plc\forcetables\Force table.s7dcl') 'x'
    Write-ForceTable 'plc\watchtables\Force table.xml' 'Force table'

    function New-ForceTable([string]$Name, [bool]$Consistent = $true) {
        $t = [pscustomobject]@{ Name = $Name; IsConsistent = $Consistent }
        Add-Member -InputObject $t ScriptProperty Entries { $script:entriesRead++; throw 'Entries read' }
        Add-Member -InputObject $t ScriptMethod Delete { $script:deleted += @($this.Name) }
        $t
    }
    # the PLC holds its one force table, 'Force table'; an imported file whose row names noSuchMember makes TIA throw when
    # the row has a DisplayFormat, and comes back not consistent when it has none
    function Get-KindRoot {
        $tables = New-Object System.Collections.ArrayList
        [void]$tables.Add((New-ForceTable 'Force table'))
        Add-Member -InputObject $tables ScriptMethod Import { param($file, $options)
            $text = [System.IO.File]::ReadAllText($file.FullName)
            $name = [regex]::Match($text, '<Name>([^<]*)</Name>').Groups[1].Value
            $script:imported += @("$name $options")
            if ($text -match 'noSuchMember' -and $text -match 'DisplayFormat') {
                throw [System.InvalidOperationException]::new("The attribute 'Siemens.Simatic.PlcLanguages.VatService.Openness.ForceTableEntry.DisplayFormat' cannot be set for '$name' because the assigned block is inconsistent.")
            }
            , @(New-ForceTable $name ($text -notmatch 'noSuchMember')) }
        $groups = New-Object System.Collections.ArrayList
        Add-Member -InputObject $groups ScriptMethod Find { param($n) $null }
        Add-Member -InputObject $groups ScriptMethod Create { param($n) $script:groupsMade += @($n); [pscustomobject]@{ ForceTables = $tables; WatchTables = @(); Groups = @() } }
        [pscustomobject]@{ WatchAndForceTableGroup = [pscustomobject]@{ ForceTables = $tables; WatchTables = @(); Groups = $groups } }
    }
    function Invoke-ForceImport([string[]]$Paths, [string]$Kind = 'force_table') {
        $script:imported = @(); $script:groupsMade = @(); $script:entriesRead = 0; $script:committed = $null
        Invoke-ImportTool ([pscustomobject]@{ kind = $Kind; paths = $Paths })
    }
    BeforeEach {
        Initialize-BridgeContext @{ maxResponseChars = 20000 }
        Set-BridgeProject -Name 'P' -Path 'C:\P.ap20' -Repo $repo
        Register-Archive (Get-BridgeSession)
    }

    It 'imports the PLC''s force table over itself, with Override, and says that nothing of it reaches the CPU' {
        $r = Invoke-ForceImport @('plc\forcetables\Force table.xml')
        $r.ok | Should Be $true
        $script:imported -join ',' | Should Be 'Force table Override'
        $script:groupsMade.Count | Should Be 0
        $script:committed | Should Be $true
        $script:entriesRead | Should Be 0
        $r.online | Should Match 'offline force table only, nothing in the CPU'
        $r.online | Should Match 'cannot set a force mark'
        $r.online | Should Match 'Forcing stays the user''s, online'
        $r.online | Should Match 'keeps its mark through an import was not tried'
    }

    It 'refuses a force table of another name before TIA is asked, naming the PLC''s one' {
        $r = Invoke-ForceImport @('plc\forcetables\Other.xml')
        $r.ok | Should Be $false
        $r.items[0].refused | Should Match "'Other' is not it"
        $r.items[0].refused | Should Match "'Force table'"
        @($script:imported).Count | Should Be 0
    }

    It 'rolls back a table TIA leaves not consistent, names it as a force table, and never reads its rows' {
        $r = Invoke-ForceImport @('plc\forcetables\Broken.xml')
        $r.ok | Should Be $false
        $r.rolledBack | Should Be $true
        $script:committed | Should Be $false
        $r.items[0].name | Should Be 'Force table'
        $r.items[0].error.type | Should Be 'TiaBridge.NotConsistent'
        $r.items[0].error.message | Should Match "force table 'Force table' not consistent: a row names a symbol"
        $r.items[0].Contains('imported') | Should Be $false
        $script:entriesRead | Should Be 0
    }

    It 'rolls back a row TIA throws on, says what the import does not do online, and refuses the save until the table is imported good' {
        $r = Invoke-ForceImport @('plc\forcetables\BrokenFormat.xml')
        $r.ok | Should Be $false
        $r.rolledBack | Should Be $true
        $script:committed | Should Be $false
        $r.items[0].name | Should Be 'Force table'
        $r.items[0].error.message | Should Match 'DisplayFormat'' cannot be set for ''Force table'' because the assigned block is inconsistent'
        $r.items[0].Contains('imported') | Should Be $false
        $r.online | Should Match 'nothing in the CPU'
        @(Test-SaveAllowed (Get-BridgeSession)) -join ' ' | Should Match 'A write failed and was not redone successfully: plc@PLC_1:Force table'
        $null = Invoke-ForceImport @('plc\forcetables\Force table.xml')
        @(Test-SaveAllowed (Get-BridgeSession)) -join ' ' | Should Not Match 'failed'
    }

    It 'refuses the save after a table TIA left not consistent is rolled back, until the table is imported good' {
        $r = Invoke-ForceImport @('plc\forcetables\Broken.xml')
        $r.rolledBack | Should Be $true
        @(Test-SaveAllowed (Get-BridgeSession)) -join ' ' | Should Match 'A write failed and was not redone successfully: plc@PLC_1:Force table'
        $null = Invoke-ForceImport @('plc\forcetables\Force table.xml')
        @(Test-SaveAllowed (Get-BridgeSession)) -join ' ' | Should Not Match 'failed'
    }

    Context 'without a transaction' {
        function Invoke-TiaWrite([string]$Description, [scriptblock]$Body, [switch]$NoTransaction, [scriptblock]$RollbackIf) {
            @{ output = @(& $Body); transaction = $false; rolledBack = $false; commitError = $null; note = $null }
        }
        It 'refuses the save while the table TIA left not consistent is not imported good' {
            $r = Invoke-ForceImport @('plc\forcetables\Broken.xml')
            $r.rolledBack | Should Be $false
            $r.items[0].error.message | Should Match "force table 'Force table' not consistent"
            @(Test-SaveAllowed (Get-BridgeSession)) -join ' ' | Should Match 'A write failed and was not redone successfully: plc@PLC_1:Force table'
            $null = Invoke-ForceImport @('plc\forcetables\Force table.xml')
            @(Test-SaveAllowed (Get-BridgeSession)) -join ' ' | Should Not Match 'failed'
        }
    }

    It 'refuses a file that is no SimaticML, and a watch table document, before TIA is asked; and a force table under watch_table' {
        $r = Invoke-ForceImport @('plc\forcetables\Force table.s7dcl')
        $r.items[0].refused | Should Match 'SimaticML'
        $r = Invoke-ForceImport @('plc\forcetables\Watch1.xml')
        $r.items[0].refused | Should Match 'holds a watch table: import it with kind watch_table, not force_table'
        $r = Invoke-ForceImport @('plc\watchtables\Force table.xml') 'watch_table'
        $r.items[0].refused | Should Match 'holds a force table: import it with kind force_table, not watch_table'
        @($script:imported).Count | Should Be 0
    }

    It 'does not delete the PLC''s force table' {
        $script:deleted = @()
        $r = Invoke-DeleteTool ([pscustomobject]@{ kind = 'force_table'; names = @('Force table') })
        $r.ok | Should Be $false
        $r.refused | Should Match 'one force table'
        @($script:deleted).Count | Should Be 0
    }
}
