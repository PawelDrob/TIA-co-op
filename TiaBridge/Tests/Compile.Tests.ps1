$here = Split-Path -Parent $MyInvocation.MyCommand.Path
foreach ($f in 'Mcp.ps1', 'Tia.ps1', 'Repo.ps1', 'Rules.ps1', 'Guards.ps1', 'Bridge.ps1', 'Tools\Objects.ps1', 'Tools\Plc.ps1') { . (Join-Path $here "..\$f") }

if (-not ('Siemens.Engineering.Compiler.ICompilable' -as [type])) {
    Add-Type -TypeDefinition 'namespace Siemens.Engineering.Compiler { public interface ICompilable { object Compile(); } }'
}

# Stand-ins: a PLC with one FB and one UDT in a subfolder; each offers a compile service (a PLC data type does:
# probe of a PlcStruct on V20, 2026-10-08) that records the name it compiled.
function New-Compilable([string]$Name, [string]$Throws = '', [bool]$Consistent = $true) {
    $o = [pscustomobject]@{ Name = $Name; compiler = $null; IsConsistent = $Consistent }
    $c = [pscustomobject]@{ name = $Name; obj = $o; throws = $Throws }
    $c | Add-Member ScriptMethod Compile { $script:compiled += @($this.name); if ($this.throws) { throw $this.throws }; $this.obj.IsConsistent = $true; @{ errors = 0; warnings = 0 } }
    $o.compiler = $c
    $o
}
function Get-TiaSoftware { $script:plc }
function Get-TiaSoftwareList { @(@{ device = 'PLC_1'; kind = 'plc' }) }
function Get-TiaService($Obj, [type]$Type) { $Obj.compiler }
function ConvertTo-ResultTree($r) { $r }
function Test-TiaAlive { $true }
function Invoke-TiaWrite([string]$Description, [scriptblock]$Body, [switch]$NoTransaction, [scriptblock]$RollbackIf, [switch]$OnCopy) {
    $script:onCopy = [bool]$OnCopy
    @{ output = @(& $Body); transaction = $false; rolledBack = $false; commitError = $null; note = $null }
}

Describe 'what TIA holds not consistent after a compile' {
    # As seen on real blocks: the compile reports 0 errors and all up to date, and IsConsistent stays false.
    function New-StaysInconsistent([string]$Name) {
        $o = New-Compilable $Name
        $o.compiler | Add-Member ScriptMethod Compile { $script:compiled += @($this.name); $this.obj.IsConsistent = $false; @{ errors = 0; warnings = 0 } } -Force
        $o
    }
    function New-WriteSession {
        Initialize-BridgeContext @{ maxResponseChars = 20000 }
        Set-BridgeProject -Name 'P' -Path 'C:\P.ap20' -Repo (Join-Path $TestDrive 'R')
        $s = Get-BridgeSession
        Register-Archive $s
        Register-Write $s -Scope plc -Device PLC_1 -Items @(@{ name = 'First'; ok = $true }, @{ name = 'Last'; ok = $true })
        $script:compiled = @()
        $script:plc = [pscustomobject]@{
            BlockGroup = [pscustomobject]@{ Blocks = @((New-StaysInconsistent 'First'), (New-Compilable 'Last')); Groups = @() }
            TypeGroup = [pscustomobject]@{ Types = @(); Groups = @() }
        }
        $s
    }

    It 'names them in a write session, the compile stays ok and its writes cleared' {
        $s = New-WriteSession
        $r = Invoke-CompileTool ([pscustomobject]@{ scope = 'blocks'; names = @('First', 'Last') })
        $r.ok | Should Be $true
        $r.errors | Should Be 0
        @($r.failed) -join ',' | Should Be 'First'
        $r.note | Should Match 'whatever the compile reported'
        $s.pending.Count | Should Be 0
        @($s.notConsistent['plc@PLC_1']) -join ',' | Should Be 'First'
    }

    It 'a technology object left not consistent is named too, after the compile cleared its write, and at the save' {
        $s = New-WriteSession
        Register-Write $s -Scope plc -Device PLC_1 -Items @(@{ name = 'Enc1'; ok = $true })
        $script:plc | Add-Member NoteProperty TechnologicalObjectGroup ([pscustomobject]@{ TechnologicalObjects = @(); Groups = @(
            [pscustomobject]@{ Name = 'Axes'; TechnologicalObjects = @((New-Compilable 'Enc1' -Consistent $false), (New-Compilable 'Pid1')); Groups = @() }) })
        $r = Invoke-CompileTool ([pscustomobject]@{ scope = 'blocks'; names = @('First', 'Last') })
        (@($r.failed) | Sort-Object) -join ',' | Should Be 'Enc1,First'
        (@($s.notConsistent['plc@PLC_1']) | Sort-Object) -join ',' | Should Be 'Enc1,First'
        @(Get-SaveStanding $s)[0].notConsistent.names -contains 'Enc1' | Should Be $true
    }

    It 'a block left behind by another name is named too: TIA is asked about the whole PLC' {
        $s = New-WriteSession
        $r = Invoke-CompileTool ([pscustomobject]@{ scope = 'blocks'; names = @('Last') })
        @($r.failed) -join ',' | Should Be ''
        $script:plc.BlockGroup.Blocks[0].IsConsistent = $false
        $r = Invoke-CompileTool ([pscustomobject]@{ scope = 'blocks'; names = @('Last') })
        @($r.failed) -join ',' | Should Be 'First'
    }

    It 'says nothing when all is consistent, and a later compile clears the record' {
        $s = New-WriteSession
        Invoke-CompileTool ([pscustomobject]@{ scope = 'blocks'; names = @('First') }) | Out-Null
        $s.notConsistent.Count | Should Be 1
        $script:plc.BlockGroup.Blocks[0] = New-Compilable 'First'
        $r = Invoke-CompileTool ([pscustomobject]@{ scope = 'blocks'; names = @('First') })
        @($r.failed).Count | Should Be 0
        $r.ContainsKey('note') | Should Be $false
        $s.notConsistent.Count | Should Be 0
    }

    It 'a state it cannot read is said, keeps the record and does not fail the compile' {
        $s = New-WriteSession
        Invoke-CompileTool ([pscustomobject]@{ scope = 'blocks'; names = @('First') }) | Out-Null
        function Get-InconsistentPlcObjects($Plc) { throw 'Could not read it.' }
        $r = Invoke-CompileTool ([pscustomobject]@{ scope = 'blocks'; names = @('Last') })
        $r.ok | Should Be $true
        $r.ContainsKey('failed') | Should Be $false
        $r.consistencyUnread | Should Match 'Could not read it'
        @($s.notConsistent['plc@PLC_1']) -join ',' | Should Be 'First'
    }
}

Describe 'a long list of what TIA holds not consistent costs no answer' {
    function Get-CompileErrors($Tree) { @{ object = 'Bad'; description = 'The error this compile is for.' } }
    function New-Many([int]$Count) {
        Initialize-BridgeContext @{ maxResponseChars = 20000 }
        Set-BridgeProject -Name 'P' -Path 'C:\P.ap20' -Repo (Join-Path $TestDrive 'R')
        $s = Get-BridgeSession
        Register-Archive $s -Skipped
        $bad = New-Compilable 'Bad'
        $bad.compiler | Add-Member ScriptMethod Compile {
            $this.obj.IsConsistent = $false
            @{ errors = 1; warnings = 0; messages = @(@{ path = 'Network 1'; state = 'Error'; description = 'The error this compile is for.'; errors = 1; warnings = 0; messages = @() }) }
        } -Force
        $many = @(1..$Count | ForEach-Object { [pscustomobject]@{ Name = ('LongBlockNameOfAProject_{0:d5}' -f $_); IsConsistent = $false } })
        $script:plc = [pscustomobject]@{ BlockGroup = [pscustomobject]@{ Blocks = @(@($bad) + $many); Groups = @() }; TypeGroup = [pscustomobject]@{ Types = @(); Groups = @() } }
        $s
    }

    It 'compile: the first ten and a count, and its own error text stays in the response' {
        $s = New-Many 2000
        $r = Invoke-CompileTool ([pscustomobject]@{ scope = 'blocks'; names = @('Bad') })
        @($r.failed).Count | Should Be 10
        $r.failedTotal | Should Be 2001
        $r.note | Should Match 'first ten of failedTotal'
        $text = Limit-ToolResponse $r 20000
        $text.Length | Should BeLessThan 20001
        $text | Should Match 'The error this compile is for'
        $text | Should Not Match 'in the log file'
        @($s.notConsistent['plc@PLC_1']).Count | Should Be 2001
    }

    It 'what the session wrote or named comes first: its own block last by name stays in the ten' {
        $s = New-Many 30
        Register-Write $s -Scope plc -Device PLC_1 -Items @(@{ name = 'ZzMine'; ok = $true })
        $mine = New-Compilable 'ZzMine' -Consistent $false
        $mine.compiler | Add-Member ScriptMethod Compile { $this.obj.IsConsistent = $false; @{ errors = 0; warnings = 0 } } -Force
        $script:plc.BlockGroup.Blocks = @($script:plc.BlockGroup.Blocks) + @($mine)
        $r = Invoke-CompileTool ([pscustomobject]@{ scope = 'blocks'; names = @('Bad') })
        @($r.failed).Count | Should Be 10
        @($r.failed)[0..1] -join ',' | Should Be 'Bad,ZzMine'
        $r.failedTotal | Should Be 32
        $names = @(Get-SaveStanding $s)[0].notConsistent
        $names.count | Should Be 32
        @($names.names).Count | Should Be 10
        @($names.names)[0..1] -join ',' | Should Be 'Bad,ZzMine'
        $r.note | Should Match 'wrote or named first'
    }

    It 'a block only named, on a device not written, comes first too' {
        $s = New-Many 30
        $r = Invoke-CompileTool ([pscustomobject]@{ scope = 'blocks'; names = @('LongBlockNameOfAProject_00030') })
        @($r.failed)[0] | Should Be 'LongBlockNameOfAProject_00030'
        @(Get-SaveStanding $s)[0].notConsistent.names[0] | Should Be 'LongBlockNameOfAProject_00030'
    }

    It 'ten or fewer: all of them, no word about the rest' {
        New-Many 5 | Out-Null
        $r = Invoke-CompileTool ([pscustomobject]@{ scope = 'blocks'; names = @('Bad') })
        @($r.failed).Count | Should Be 6
        $r.failedTotal | Should Be 6
        $r.note | Should Not Match 'first ten'
    }

    It 'a refused save and saveBlockers keep every reason: a failed write beside the long list too' {
        $s = New-Many 2000
        Register-Write $s -Scope plc -Device PLC_1 -Items @(@(@{ name = 'Bad'; ok = $true }, @{ name = 'Broken'; ok = $false }) + @(1..2000 | ForEach-Object { @{ name = ('LongBlockNameOfAProject_{0:d5}' -f $_); ok = $true } }))
        Invoke-CompileTool ([pscustomobject]@{ scope = 'blocks'; names = @('Bad') }) | Out-Null
        $blockers = @(Test-SaveAllowed $s)
        $blockers.Count | Should Be 4
        $text = Limit-ToolResponse @{ ok = $false; refused = 'Save refused.'; blockers = $blockers; saveBlockers = $blockers } 20000
        $text | Should Not Match 'in the log file'
        $text | Should Match 'Broken'
        $text | Should Match 'and 1991 more, 2001 in all'
        $text.Length | Should BeLessThan 5000
    }

    It 'a long list of writes in a refusal is cut the same way' {
        $s = New-Many 1
        $items = @(1..2000 | ForEach-Object { @{ name = "W$_"; ok = $true } })
        Register-Write $s -Scope plc -Device PLC_1 -Items $items
        $text = @(Test-SaveAllowed $s) -join ' '
        $text | Should Match 'and 1990 more, 2000 in all'
    }

    It 'a session for export only keeps every name: TiaArchiveCompare reads them' {
        New-Many 12 | Out-Null
        $script:Bridge.background = @{ write = $false; plain = $true; session = (New-SessionState) }
        $r = Invoke-CompileTool ([pscustomobject]@{ scope = 'blocks'; names = @('Bad') })
        @($r.failed).Count | Should Be 13
        $r.ContainsKey('failedTotal') | Should Be $false
    }
}

Describe 'the save rules over what TIA holds not consistent' {
    function New-State { $s = New-SessionState; Register-Archive $s; $s }

    It 'with an archive the save goes through and names them, at most ten' {
        $s = New-State
        Register-Compile $s -Scope plc -Device PLC_1 -Names @('A') -ErrorCount 0 -NotConsistent ([string[]](1..12 | ForEach-Object { "B$_" }))
        @(Test-SaveAllowed $s).Count | Should Be 0
        $st = @(Get-SaveStanding $s)
        $st[0].device | Should Be 'plc@PLC_1'
        $st[0].notConsistent.count | Should Be 12
        @($st[0].notConsistent.names).Count | Should Be 10
        Register-Save $s
        @(Get-SaveStanding $s).Count | Should Be 0
    }

    It 'without an archive it refuses, naming them' {
        $s = New-SessionState
        Register-Archive $s -Skipped
        Register-Write $s -Scope plc -Device PLC_1 -Items @(@{ name = 'A'; ok = $true })
        Register-Compile $s -Scope plc -Device PLC_1 -Names @('A') -ErrorCount 0 -NotConsistent ([string[]]@('A'))
        (@(Test-SaveAllowed $s) -join ' ') | Should Match 'not consistent.*A\.'
        Register-Compile $s -Scope plc -Device PLC_1 -ErrorCount 0 -NotConsistent ([string[]]@())
        @(Test-SaveAllowed $s).Count | Should Be 0
    }

    It 'a device with no write since the last save does not refuse, and is still named' {
        $s = New-SessionState
        Register-Archive $s -Skipped
        Register-Write $s -Scope plc -Device PLC_1 -Items @(@{ name = 'A'; ok = $true })
        Register-Compile $s -Scope plc -Device PLC_1 -Names @('A') -ErrorCount 0 -NotConsistent ([string[]]@())
        Register-Compile $s -Scope plc -Device PLC_2 -ErrorCount 0 -NotConsistent ([string[]]@('Other'))
        @(Test-SaveAllowed $s).Count | Should Be 0
        @(Get-SaveStanding $s)[0].notConsistent.names -join ',' | Should Be 'Other'
    }

    It 'a compile just to look, with nothing written, does not refuse' {
        $s = New-SessionState
        Register-Archive $s -Skipped
        Register-Compile $s -Scope plc -Device PLC_1 -Names @('A') -ErrorCount 0 -NotConsistent ([string[]]@('A', 'B'))
        @(Test-SaveAllowed $s).Count | Should Be 0
    }

    It 'a write stays a write after its compile, until the save; a failed import of a new name is none' {
        $s = New-SessionState
        Register-Archive $s -Skipped
        Register-Write $s -Scope plc -Device PLC_1 -Items @(@{ name = 'A'; ok = $true })
        Register-Compile $s -Scope plc -Device plc_1 -Names @('A') -ErrorCount 0 -NotConsistent ([string[]]@('A'))
        @(Test-SaveAllowed $s).Count | Should Be 1
        Register-Save $s
        Register-Compile $s -Scope plc -Device PLC_1 -Names @('A') -ErrorCount 0 -NotConsistent ([string[]]@('A'))
        @(Test-SaveAllowed $s).Count | Should Be 0
        Register-Write $s -Scope plc -Device PLC_1 -Items @(@{ name = 'New'; ok = $false })
        Clear-ObjectWrites $s plc PLC_1 @('New')
        @(Test-SaveAllowed $s).Count | Should Be 0
    }

    It 'on a written device what it wrote or named refuses, another block is only named' {
        $s = New-SessionState
        Register-Archive $s -Skipped
        Register-Write $s -Scope plc -Device PLC_1 -Items @(@{ name = 'Mine'; ok = $true })
        Register-Compile $s -Scope plc -Device PLC_1 -Names @('Mine', 'Named') -ErrorCount 0 -NotConsistent ([string[]]@('Mine', 'Named', 'Others'))
        $text = @(Test-SaveAllowed $s) -join ' '
        $text | Should Match 'Mine, Named'
        $text | Should Not Match 'Others'
        @(Get-SaveStanding $s)[0].notConsistent.names -join ',' | Should Be 'Mine,Named,Others'
        Register-Compile $s -Scope plc -Device PLC_1 -ErrorCount 0 -NotConsistent ([string[]]@('Others'))
        @(Test-SaveAllowed $s).Count | Should Be 0
    }

    It 'a library type written counts by its own name' {
        $s = New-SessionState
        Register-Archive $s -Skipped
        Register-Write $s -Scope plc -Device PLC_1 -Items @(@{ name = 'type:Lib'; ok = $true })
        Register-Compile $s -Scope plc -Device PLC_1 -ErrorCount 0 -NotConsistent ([string[]]@('Lib'))
        (@(Test-SaveAllowed $s) -join ' ') | Should Match 'Lib'
    }

    It 'a device the project no longer has leaves nothing behind' {
        $s = New-SessionState
        Register-Archive $s -Skipped
        Register-Write $s -Scope plc -Device PLC_2 -Items @(@{ name = 'A'; ok = $true })
        Register-Compile $s -Scope plc -Device PLC_2 -Names @('A') -ErrorCount 0 -NotConsistent ([string[]]@('A'))
        $said = @(Remove-GoneDeviceKeys $s @(@{ kind = 'plc'; device = 'PLC_1' }))
        ($said -join ' ') | Should Match 'plc@PLC_2 not consistent: A'
        $s.notConsistent.Count + $s.written.Count + $s.named.Count | Should Be 0
        @(Test-SaveAllowed $s).Count | Should Be 0
    }

    It 'a compile that did not read it leaves the record, one device does not clear another' {
        $s = New-State
        Register-Compile $s -Scope plc -Device PLC_1 -ErrorCount 0 -NotConsistent ([string[]]@('A'))
        Register-Compile $s -Scope plc -Device PLC_1 -ErrorCount 0
        Register-Compile $s -Scope plc -Device PLC_2 -ErrorCount 0 -NotConsistent ([string[]]@())
        @($s.notConsistent['plc@PLC_1']) -join ',' | Should Be 'A'
    }

    It 'survives a new bridge process, and a session file from before it' {
        $repo = Join-Path $TestDrive 'Keep'
        New-Item -ItemType Directory -Path $repo | Out-Null
        $s = New-State
        Register-Compile $s -Scope plc -Device PLC_1 -ErrorCount 0 -NotConsistent ([string[]]@('A', 'B'))
        Save-SessionWrites $repo $s
        $back = New-SessionState
        Restore-SessionWrites $repo $back
        @($back.notConsistent['plc@PLC_1']) -join ',' | Should Be 'A,B'
        Register-Write $s -Scope plc -Device PLC_1 -Items @(@{ name = 'A'; ok = $true })
        Register-Compile $s -Scope plc -Device PLC_1 -Names @('A') -ErrorCount 0
        Save-SessionWrites $repo $s
        $back = New-SessionState
        Restore-SessionWrites $repo $back
        $back.pending.Count | Should Be 0
        @($back.written.Values) -join ',' | Should Be 'plc@PLC_1:A'
        @($back.named.Values) -join ',' | Should Be 'plc@PLC_1:A'
        Set-Content -LiteralPath (Join-Path $repo '.tiabridge-session.json') -Value '{"pending":{"plc@plc_1:p":"plc@PLC_1:P"},"failed":{},"compileErrors":{},"notConsistent":{"plc@PLC_1":["P"]}}'
        $older = New-SessionState
        Restore-SessionWrites $repo $older
        @($older.written.Values) -join ',' | Should Be 'plc@PLC_1:P'
        Set-Content -LiteralPath (Join-Path $repo '.tiabridge-session.json') -Value '{"pending":{},"failed":{},"compileErrors":{}}'
        $old = New-SessionState
        Restore-SessionWrites $repo $old
        $old.notConsistent.Count | Should Be 0
    }
}

Describe 'compile of single objects' {
    $script:plc = [pscustomobject]@{
        BlockGroup = [pscustomobject]@{ Blocks = @(New-Compilable 'UsesData'); Groups = @() }
        TypeGroup = [pscustomobject]@{ Types = @(); Groups = @([pscustomobject]@{ Name = 'Sub'; Types = @(New-Compilable 'Data_UDT'); Groups = @() }) } }

    function New-Session {
        Initialize-BridgeContext @{ maxResponseChars = 20000 }
        Set-BridgeProject -Name 'P' -Path 'C:\P.ap20' -Repo (Join-Path $TestDrive 'R')
        $s = Get-BridgeSession
        Register-Archive $s
        Register-Write $s -Scope plc -Device PLC_1 -Items @(@{ name = 'Data_UDT'; ok = $true }, @{ name = 'UsesData'; ok = $true })
        $script:compiled = @()
        $s
    }

    It 'compiles a PLC data type by name and clears its pending write' {
        $s = New-Session
        $r = Invoke-CompileTool ([pscustomobject]@{ scope = 'blocks'; names = @('Data_UDT', 'UsesData') })
        $r.ok | Should Be $true
        ($script:compiled -join ',') | Should Be 'Data_UDT,UsesData'
        $s.pending.Count | Should Be 0
    }

    It 'refuses a name that is neither a block nor a PLC data type' {
        New-Session | Out-Null
        $r = Invoke-CompileTool ([pscustomobject]@{ scope = 'blocks'; names = @('Data_UDT', 'Nothing') })
        $r.refused | Should Be 'No block or PLC data type named: Nothing.'
        $script:compiled.Count | Should Be 0
    }
}

Describe 'compile of the copy in a background session for export only' {
    $safety = 'The requested action cannot be performed because permission to modify the safety program is missing either on F-CPU or project level.'
    function Write-BridgeLog([string]$Text) { }
    function New-ExportOnly([string]$PlcThrows = '') {
        Initialize-BridgeContext @{ maxResponseChars = 20000 }
        $script:Bridge.projectName = 'Bg'
        $script:Bridge.background = @{ write = $false; plain = $true; session = (New-SessionState) }
        $script:compiled = @()
        $script:plc = New-Compilable 'PLC software' $PlcThrows
        $script:plc | Add-Member NoteProperty BlockGroup ([pscustomobject]@{ Blocks = @((New-Compilable 'Done_FB'), (New-Compilable 'Std_FB' -Consistent $false)); Groups = @(
            [pscustomobject]@{ Name = 'Safety'; Blocks = @(New-Compilable 'F_Main' $safety $false); Groups = @() }) })
        $script:plc | Add-Member NoteProperty TypeGroup ([pscustomobject]@{ Types = @(New-Compilable 'New_UDT' -Consistent $false); Groups = @() })
    }

    It 'compiles the copy, never saved, and names what is still not consistent' {
        New-ExportOnly
        $script:plc.BlockGroup.Groups[0].Blocks[0].compiler.throws = ''
        $script:plc.compiler | Add-Member ScriptMethod Compile { $script:compiled += @('PLC software'); @{ errors = 0; warnings = 0 } } -Force
        $r = Invoke-CompileTool ([pscustomobject]@{ scope = 'plc' })
        $script:onCopy | Should Be $true
        $r.ok | Should Be $true
        ($script:compiled -join ',') | Should Be 'PLC software'
        # the stand-in PLC compile does not touch the blocks: all three stay not consistent
        (@($r.failed) | Sort-Object) -join ',' | Should Be 'F_Main,New_UDT,Std_FB'
        $r.note | Should Match 'never saved'
        $r.ContainsKey('safetyLogin') | Should Be $false
    }

    It 'without the safety login compiles the blocks not consistent one by one; the F-block stays in failed' {
        New-ExportOnly $safety
        $r = Invoke-CompileTool ([pscustomobject]@{ scope = 'plc' })
        $r.ContainsKey('error') | Should Be $false
        $r.safetyLogin | Should Be $false
        $r.ok | Should Be $false
        $r.errors | Should Be 1
        (@($script:compiled) | Sort-Object) -join ',' | Should Be 'F_Main,New_UDT,PLC software,Std_FB'
        @($r.failed) -join ',' | Should Be 'F_Main'
        @($r.items | Where-Object { -not $_.ok } | ForEach-Object { $_.name }) -join ',' | Should Be 'F_Main'
        $r.note | Should Match 'one by one'
    }

    It 'without the safety login compiles a technology object not consistent one by one too, and names it while it stays so' {
        New-ExportOnly $safety
        $script:plc | Add-Member NoteProperty TechnologicalObjectGroup ([pscustomobject]@{ TechnologicalObjects = @(
            (New-Compilable 'Pid1' -Consistent $false), (New-Compilable 'Enc1' 'The input address of the encoder telegram is not set.' $false)); Groups = @() })
        $r = Invoke-CompileTool ([pscustomobject]@{ scope = 'plc' })
        (@($script:compiled) | Sort-Object) -join ',' | Should Be 'Enc1,F_Main,New_UDT,Pid1,PLC software,Std_FB'
        (@($r.failed) | Sort-Object) -join ',' | Should Be 'Enc1,F_Main'
        (@($r.items | Where-Object { -not $_.ok } | ForEach-Object { $_.name }) | Sort-Object) -join ',' | Should Be 'Enc1,F_Main'
    }

    It 'lets another compile failure through, and keeps the failure of a connect session as it was' {
        New-ExportOnly 'Something else broke.'
        { Invoke-CompileTool ([pscustomobject]@{ scope = 'plc' }) } | Should Throw 'Something else broke.'
        New-ExportOnly $safety
        $script:Bridge.background = $null
        Set-BridgeProject -Name 'P' -Path 'C:\P.ap20' -Repo (Join-Path $TestDrive 'R2')
        { Invoke-CompileTool ([pscustomobject]@{ scope = 'plc' }) } | Should Throw 'safety program'
        $script:onCopy | Should Be $false
    }

    It 'refuses scope hmi in export only, before the handler runs' {
        New-ExportOnly
        Get-BackgroundRefusal 'compile' ([pscustomobject]@{ scope = 'hmi' }) | Should Match 'scope plc or blocks'
        Get-BackgroundRefusal 'compile' ([pscustomobject]@{ scope = 'blocks'; names = @('Std_FB') }) | Should BeNullOrEmpty
        Get-BackgroundRefusal 'compile' ([pscustomobject]@{ scope = 'plc' }) | Should BeNullOrEmpty
    }
}
