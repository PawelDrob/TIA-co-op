# Rules.ps1 - per-project session state: the archive gate on writes (6.1) and the save rules (6.2).
# Scopes: 'plc' and 'hmi'. The rules count per device: object keys are '<scope>@<device>:<name>', compared
# case-insensitively; a compile clears and flags its own device only.

function New-SessionState {
    @{
        archived = $false; archiveSkipped = $false
        pending = @{}          # written, not compiled since
        failed = @{}           # write failed, not written successfully since
        compileErrors = @{}    # '<scope>@<device>' -> @{ errors; messages } of the last compile with errors, $false when clean
        notConsistent = @{}    # 'plc@<device>' -> names TIA held not consistent after the last compile, compile errors or none
        written = @{}          # as pending, but kept after the compile: what was written since the last save
        named = @{}            # as pending: what a compile by name named since the last save
        unreadable = $null     # why the session record cannot be read or relied on: all writes and saves refused (Restore-SessionWrites)
    }
}

# A project without unsaved changes holds no write of this session that a save could store: each was saved or
# discarded (closed without saving, 2026-10-06), so the save rules start afresh. The archive gate stays. A record that
# cannot be read has nothing to say about such a project either.
function Clear-SessionWrites($State) {
    $State.unreadable = $null
    $State.pending.Clear(); $State.failed.Clear(); $State.compileErrors.Clear(); $State.notConsistent.Clear()
    $State.written.Clear(); $State.named.Clear()
}

# The save rules hold since the last save, not since the bridge process started: the write part of the state is kept
# in the project repo and read back when a new bridge process binds to the project. Before, a /mcp reconnect in the
# middle of a library change forgot the uncompiled writes and would have allowed a save (2026-10-06).
$script:SessionFile = '.tiabridge-session.json'

# WriteUnderway: the write tool about to run. Stored before it runs, gone with the next store: while the file holds it, the file
# lacks what that write did, which may be a failed write, and a new process refuses on it (Restore-SessionWrites).
function Save-SessionWrites([string]$Repo, $State, [string]$WriteUnderway) {
    if ($State.unreadable) { return }   # what this session holds is not the whole record: the next process must find the damage too
    $d = [ordered]@{ pending = $State.pending; failed = $State.failed; compileErrors = $State.compileErrors; notConsistent = $State.notConsistent
                     written = $State.written; named = $State.named }
    if ($WriteUnderway) { $d.writeUnderway = $WriteUnderway }
    Write-TextFileAtomic (Join-Path $Repo $script:SessionFile) ($d | ConvertTo-Json -Depth 4)
}

# Why a session file does not hold a record, or the record. The first three parts are in every file ever written; the others
# came later, and a file from before has none of them.
function Read-SessionRecord([string]$File) {
    try { $text = [System.IO.File]::ReadAllText($File, [System.Text.Encoding]::UTF8) }
    catch { return @{ problem = $_.Exception.InnerException.Message } }
    if (-not $text.Trim()) { return @{ problem = 'it is empty' } }
    try { $d = ConvertFrom-Json -InputObject $text -ErrorAction Stop } catch { return @{ problem = 'not valid JSON' } }
    $objectType = [System.Management.Automation.PSCustomObject]
    if ($d -isnot $objectType) { return @{ problem = 'not a record' } }
    $bad = @(foreach ($part in 'pending', 'failed', 'compileErrors') { if ($d.$part -isnot $objectType) { $part } })
    $bad += @(foreach ($part in 'notConsistent', 'written', 'named') { if ($d.PSObject.Properties[$part] -and $d.$part -isnot $objectType) { $part } })
    if ($bad.Count) { return @{ problem = "$($bad -join ', ') missing or not an object" } }
    # every other part is read as it comes; these hold names, and Expand-OldSessionKeys cuts the scope off those of the old keys
    $noName = @(foreach ($part in 'pending', 'failed', 'written', 'named') {
        foreach ($p in $d.$part.PSObject.Properties) { if (-not (Test-SessionLabel $p.Name $p.Value)) { $part; break } }
    })
    if ($noName.Count) { return @{ problem = "$($noName -join ', ') holds a value that is not a name" } }
    @{ record = $d }
}

function Test-SessionLabel([string]$Key, $Value) {
    if ($Value -isnot [string] -or -not $Value) { return $false }
    if ($Key -notmatch '^(plc|hmi):') { return $true }
    $Value.StartsWith("$($Matches[1]):", [StringComparison]::OrdinalIgnoreCase)
}

function Format-RecordRefusal([string]$Why, [string]$ToDelete) {
    "$Why, so writes and save are refused; list, export, compile and archive still run. " +
        'With no unsaved changes in the project, connect ends this. With unsaved changes, ask the user to save in TIA or to close without saving, then connect. ' +
        "Deleting $ToDelete, then connect, also ends it: only when the user says so."
}

function Format-UnreadableRecord([string]$File, [string]$Problem, [string]$ToDelete) {
    Format-RecordRefusal "The session record $File cannot be read ($Problem), and it may name failed writes" $ToDelete
}

# A missing file with nothing beside it is no record. A file that holds none may have named failed writes, as may what a store
# that did not finish left in place of it, and a write still marked as underway may have been one: nothing is taken from any of
# them, and all writes and saves are refused until it is resolved, by the ways the text names (2026-11-04). Called again by
# connect while a refusal stands.
# Software: the project's devices (Get-TiaSoftwareList), for a file with the keys from before the rules counted per device.
function Restore-SessionWrites([string]$Repo, $State, [object[]]$Software = @()) {
    $State.unreadable = $null
    $f = Join-Path $Repo $script:SessionFile
    if (-not (Test-Path -LiteralPath $f)) {
        $left = @(Get-ChildItem -LiteralPath $Repo -Force -Filter $script:SessionTempIgnore -ErrorAction SilentlyContinue | ForEach-Object { $_.FullName })
        if ($left.Count) { $State.unreadable = Format-UnreadableRecord $f 'it is gone, and a store that did not finish left a temporary file' ($left -join ', ') }
        return
    }
    $read = Read-SessionRecord $f
    if ($read.problem) {
        $State.unreadable = Format-UnreadableRecord $f $read.problem 'the file'
        return
    }
    $d = $read.record
    if ($d.PSObject.Properties['writeUnderway']) {
        $before = @($d.failed.PSObject.Properties | ForEach-Object { $_.Value } | Sort-Object)
        $named = $(if ($before.Count) { " (failed before it: $(Format-FirstNames $before))" })
        $State.unreadable = Format-RecordRefusal "The session record $f lacks the result of a call of $($d.writeUnderway), which may be a failed write: the bridge stopped during it or could not store its result$named" 'the file'
        return
    }
    foreach ($part in 'pending', 'failed', 'compileErrors', 'notConsistent', 'written', 'named') {
        if ($d.$part) { foreach ($p in $d.$part.PSObject.Properties) { $State[$part][$p.Name] = $p.Value } }
    }
    Expand-OldSessionKeys $State $Software
    if ($null -eq $d.written) {     # a file from before written was kept: what is pending or failed there was written
        foreach ($part in 'pending', 'failed') { foreach ($k in @($State[$part].Keys)) { $State.written[$k] = $State[$part][$k] } }
    }
}

# Keys from before the rules counted per device ('plc:<name>', compile errors 'plc'): nothing says which device that
# write went to, so it counts for every device of the scope. With no such device it stays as it is, so it is not lost.
function Expand-OldSessionKeys($State, [object[]]$Software) {
    foreach ($scope in 'plc', 'hmi') {
        $devices = @($Software | Where-Object { $_.kind -eq $scope } | ForEach-Object { $_.device } | Sort-Object -Unique)
        if (-not $devices.Count) { continue }
        foreach ($part in 'pending', 'failed') {
            foreach ($key in @($State[$part].Keys | Where-Object { $_.StartsWith("${scope}:", [StringComparison]::OrdinalIgnoreCase) })) {
                $name = ([string]$State[$part][$key]).Substring($scope.Length + 1)
                foreach ($dev in $devices) { $State[$part]["${scope}@${dev}:$name".ToLowerInvariant()] = "${scope}@${dev}:$name" }
                $State[$part].Remove($key)
            }
        }
        if ($State.compileErrors.ContainsKey($scope)) {
            if ($State.compileErrors[$scope]) { foreach ($dev in $devices) { $State.compileErrors["${scope}@$dev"] = $true } }
            $State.compileErrors.Remove($scope)
        }
    }
}

# The keys of devices the project no longer has (renamed or deleted in TIA): no compile can clear them, so a save would
# stay refused for good. Removes them and returns what the save rules were holding; a clean compile flag goes unsaid.
# Software: the project's devices. Other keys ('library:...', the old 'plc:...') name no device and stay.
function Remove-GoneDeviceKeys($State, [object[]]$Software) {
    $devices = @($Software | ForEach-Object { "$($_.kind)@$($_.device)" })
    foreach ($part in 'pending', 'failed') {
        foreach ($key in @($State[$part].Keys | Where-Object { $_ -match '^(plc|hmi)@' })) {
            $k = [string]$key
            if (@($devices | Where-Object { $k.StartsWith("${_}:", [StringComparison]::OrdinalIgnoreCase) }).Count) { continue }
            $State[$part][$key]
            $State[$part].Remove($key)
        }
    }
    foreach ($key in @($State.compileErrors.Keys | Where-Object { $_ -match '^(plc|hmi)@' })) {
        if ($devices -contains $key) { continue }   # -contains ignores case
        if ($State.compileErrors[$key]) { $key }
        $State.compileErrors.Remove($key)
    }
    foreach ($key in @($State.notConsistent.Keys | Where-Object { $_ -match '^(plc|hmi)@' })) {
        if ($devices -contains $key) { continue }
        "$key not consistent: $(Format-FirstNames $State.notConsistent[$key])"
        $State.notConsistent.Remove($key)
    }
    foreach ($part in 'written', 'named') {     # said as pending or failed above when they still held anything
        foreach ($key in @($State[$part].Keys | Where-Object { $_ -match '^(plc|hmi)@' })) {
            $k = [string]$key
            if (-not @($devices | Where-Object { $k.StartsWith("${_}:", [StringComparison]::OrdinalIgnoreCase) }).Count) { $State[$part].Remove($key) }
        }
    }
}

# The first names and how many there are, so that a long list costs no answer its size (a response over the limit keeps a
# long value in the log only).
function Format-FirstNames([object[]]$Names, [int]$First = 10) {
    $all = @($Names)
    if ($all.Count -le $First) { return $all -join ', ' }
    "$(@($all | Select-Object -First $First) -join ', ') and $($all.Count - $First) more, $($all.Count) in all"
}

function Register-Archive($State, [switch]$Skipped) {
    if ($Skipped) { $State.archiveSkipped = $true } else { $State.archived = $true }
}

# $null when writes are allowed, else the reason.
function Test-WriteAllowed($State) {
    if ($State.unreadable) { return $State.unreadable }
    if ($State.archived -or $State.archiveSkipped) { return $null }
    'Writes are refused until the session archive exists: call archive(reason), or archive(skip=true, reason) if the user said to skip it.'
}

# Device: the device the tool resolved, also in a project with one device; several when the write touches several.
# A failed write put nothing in TIA to compile: it counts as failed only (rule 1), and a write before it stays pending.
function Register-Write($State, [string]$Scope, [string[]]$Device, [object[]]$Items) {
    if (-not @($Device | Where-Object { $_ }).Count) { throw "Register-Write of scope $Scope without a device." }
    foreach ($dev in $Device) {
        foreach ($i in $Items) {
            $label = "${Scope}@${dev}:$($i.name)"
            $key = $label.ToLowerInvariant()
            if ($i.ok) { $State.pending[$key] = $label; $State.failed.Remove($key) } else { $State.failed[$key] = $label }
            $State.written[$key] = $label
        }
    }
}

# A failed import of a name never created: nothing of it is there to compile or to store, and no compile by name could
# clear it, so nothing is held for it.
function Clear-ObjectWrites($State, [string]$Scope, [string[]]$Device, [string[]]$Names) {
    foreach ($dev in @($Device | Where-Object { $_ })) {
        foreach ($n in @($Names | Where-Object { $_ })) {
            $key = "${Scope}@${dev}:$n".ToLowerInvariant()
            $State.pending.Remove($key); $State.failed.Remove($key); $State.written.Remove($key)
        }
    }
}

# A write into a library that changes no project software (a master copy): only its failure counts (rule 1).
function Register-LibraryWrite($State, [string]$Name, [bool]$Ok) {
    $key = "library:$Name".ToLowerInvariant()
    if ($Ok) { $State.failed.Remove($key) } else { $State.failed[$key] = $Name }
}

# A write to a library type, which any device of its scope may use (Devices: all of them, read before the write, so
# a failure with TIA gone needs no call). A project without such a device has nothing to compile: rule 1 only.
function Register-LibraryTypeWrite($State, [string]$Scope, [string[]]$Devices, [string]$Name, [bool]$Ok) {
    if (@($Devices).Count) { Register-Write $State -Scope $Scope -Device $Devices -Items @(@{ name = $Name; ok = $Ok }) }
    else { Register-LibraryWrite $State -Name $Name -Ok $Ok }
}

# Names empty: the whole software of the scope on that device was compiled. Only a full compile clears the error flag
# of a device; a clean compile of some blocks says nothing about errors elsewhere. Other devices keep theirs.
# A name also clears the write of the library type of that name (type:<name>): on this device its instance was compiled.
# Messages: the errors as text. A whole compile replaces what the device has on record, as it saw everything; a compile by
# name adds to it, so it says nothing of errors elsewhere (its errors may be on record already: those texts do not count again).
# Only a clean compile by name takes back the errors on record of those very names: a save would quote what is gone.
# NotConsistent: what TIA holds not consistent now, read from the whole PLC, so it replaces the record of the device; $null: not read, the record stays.
function Register-Compile($State, [string]$Scope, [string]$Device, [string[]]$Names = @(), [int]$ErrorCount, [string[]]$Messages = @(), [string[]]$NotConsistent = $null) {
    if (-not $Device) { throw "Register-Compile of scope $Scope without a device." }
    $at = "${Scope}@$Device"
    if ($null -ne $NotConsistent) {
        if ($NotConsistent.Count) { $State.notConsistent[$at] = @($NotConsistent | Sort-Object) } else { $State.notConsistent.Remove($at) }
    }
    if ($ErrorCount -gt 0) {
        $known = $(if (@($Names).Count) { $State.compileErrors[$at] })
        $State.compileErrors[$at] = $(if (-not $known) { @{ errors = $ErrorCount; messages = @($Messages | Select-Object -Unique); occurrences = @($Messages) } }
                                      elseif ($known -is [bool]) { @{ errors = $null; messages = @($Messages | Select-Object -Unique); occurrences = @($Messages) } }
                                      else { Add-CompileErrors $known $ErrorCount $Messages })
    }
    elseif (-not @($Names).Count) { $State.compileErrors[$at] = $false }
    elseif ($State.compileErrors[$at] -and $State.compileErrors[$at] -isnot [bool]) {   # a record read back from the session file is no hashtable
        $known = Remove-CompileErrorsOf $State.compileErrors[$at] $Names
        if ($known) { $State.compileErrors[$at] = $known } else { $State.compileErrors.Remove($at) }
    }
    if (@($Names).Count) {
        foreach ($n in $Names) {
            $State.pending.Remove("${at}:$n".ToLowerInvariant())
            $State.pending.Remove("${at}:type:$n".ToLowerInvariant())
            $State.named["${at}:$n".ToLowerInvariant()] = "${at}:$n"
        }
    } else {
        $prefix = "${at}:".ToLowerInvariant()
        foreach ($k in @($State.pending.Keys | Where-Object { $_.StartsWith($prefix, [StringComparison]::Ordinal) })) { $State.pending.Remove($k) }
    }
}

# What a device has on record, with the errors of a compile by name added. Errors empty: an older record without a count.
function Add-CompileErrors($Known, [int]$ErrorCount, [string[]]$Messages) {
    $texts = @($Known.messages)
    $again = @($Messages | Where-Object { $texts -ccontains $_ }).Count
    @{ errors = $(if ($null -ne $Known.errors) { [int]$Known.errors + [Math]::Max(0, $ErrorCount - $again) })
       messages = @(@($texts) + @($Messages) | Where-Object { $_ } | Select-Object -Unique)
       occurrences = @(@(Get-CompileErrorOccurrences $Known) + @($Messages | Where-Object { $texts -cnotcontains $_ })) }
}

# Every error of a record by its text, the same text as often as it came (messages holds each text once). A record from
# before occurrences has only messages.
function Get-CompileErrorOccurrences($Known) { @($(if ($null -ne $Known.occurrences) { $Known.occurrences } else { $Known.messages })) }

# What a device has on record without the errors of these names, whose texts start "<name>: "; $null when nothing is left.
# A count that says more than the texts stays: what it counts is not known.
function Remove-CompileErrorsOf($Known, [string[]]$Names) {
    $prefixes = @($Names | ForEach-Object { "${_}: " })
    $isOther = { $m = [string]$_; -not @($prefixes | Where-Object { $m.StartsWith($_, [StringComparison]::OrdinalIgnoreCase) }).Count }
    $all = @(Get-CompileErrorOccurrences $Known)
    $leftAll = @($all | Where-Object $isOther)
    $errors = $(if ($null -ne $Known.errors) { [Math]::Max(0, [int]$Known.errors - ($all.Count - $leftAll.Count)) })
    if ($null -ne $errors -and $errors -eq 0) { return $null }
    @{ errors = $errors; messages = @(@($Known.messages) | Where-Object $isOther); occurrences = $leftAll }
}

function Register-Save($State) {
    $State.pending.Clear(); $State.failed.Clear(); $State.compileErrors.Clear(); $State.notConsistent.Clear()
    $State.written.Clear(); $State.named.Clear()
}

# The names on record for a device that refuse a save without an archive: on a device written since the last save, what this
# session wrote or named. Another block there can be the user's own, and clearing it can take a compile of the whole PLC: it
# is only named (Get-SaveStanding). A device with no write refuses for none of its blocks.
function Get-NotConsistentRefused($State, [string]$Device) {
    $prefix = "${Device}:".ToLowerInvariant()
    if (-not @($State.written.Keys | Where-Object { $_.StartsWith($prefix, [StringComparison]::Ordinal) }).Count) { return @() }
    $mine = @(Get-SessionOwnNames $State $Device)
    @(@($State.notConsistent[$Device]) | Where-Object { $mine -contains $_ })
}

# What this session wrote or named on a device since the last save, as names.
function Get-SessionOwnNames($State, [string]$Device) {
    $prefix = "${Device}:".ToLowerInvariant()
    @(@($State.written.Keys) + @($State.named.Keys) | Where-Object { $_.StartsWith($prefix, [StringComparison]::Ordinal) } |
      ForEach-Object { $_.Substring($prefix.Length) -replace '^type:', '' })
}

# The names on record for a device, what this session wrote or named first: a list cut to its first names keeps them.
function Get-NotConsistentOrdered($State, [string]$Device) {
    $mine = @(Get-SessionOwnNames $State $Device)
    $names = @($State.notConsistent[$Device])
    @($names | Where-Object { $mine -contains $_ }) + @($names | Where-Object { $mine -notcontains $_ })
}

# The reasons a save is refused; empty when it is allowed. A failed write always refuses. Writes not compiled and compile
# errors refuse only without an archive of this session (it was skipped; a failed one stops at the archive gate): with
# one there is a way back, the save goes through and its result names them (Get-SaveStanding).
function Test-SaveAllowed($State) {
    $reasons = @()
    if ($State.unreadable) { $reasons += $State.unreadable }
    if ($State.failed.Count) {
        $reasons += "A write failed and was not redone successfully: $(Format-FirstNames @($State.failed.Values | Sort-Object))."
    }
    if ($State.archived) { return $reasons }
    if ($State.pending.Count) {
        $reasons += "Written but not compiled since, and this session has no archive: $(Format-FirstNames @($State.pending.Values | Sort-Object)). Run compile for that scope on that device."
    }
    foreach ($scope in @($State.compileErrors.Keys | Sort-Object)) {
        if ($State.compileErrors[$scope]) { $reasons += "The last compile of '$scope' reported errors, and this session has no archive." }
    }
    foreach ($device in @($State.notConsistent.Keys | Sort-Object)) {
        $refused = @(Get-NotConsistentRefused $State $device)
        if ($refused.Count) {
            $reasons += "After the last compile of '$device' TIA holds these not consistent, which this session wrote or named, and this session has no archive: $(Format-FirstNames $refused). Fix what the compile reports and compile them; if a compile with 0 errors leaves them so, a compile of scope plc cleared that once, on a test project."
        }
    }
    $reasons
}

# What a save would store as it stands, per device: writes not compiled since (deletes too), and the errors on record since
# the last clean whole compile: their count, and the first ten texts (errors empty: a session file from before the count
# was kept), and what TIA held not consistent after the last compile: its count and the first ten names. Empty when all is
# compiled, clean and consistent.
function Get-SaveStanding($State) {
    $at = @{}
    foreach ($label in @($State.pending.Values)) {
        if (([string]$label) -notmatch '^([^:]+):(.*)$') { continue }
        $device = $Matches[1]; $name = $Matches[2]
        if (-not $at.ContainsKey($device)) { $at[$device] = @{ device = $device; notCompiled = @() } }
        $at[$device].notCompiled = @($at[$device].notCompiled) + $name
    }
    foreach ($device in @($State.compileErrors.Keys)) {
        $known = $State.compileErrors[$device]
        if (-not $known) { continue }
        if (-not $at.ContainsKey($device)) { $at[$device] = @{ device = $device; notCompiled = @() } }
        $at[$device].compileErrors = $(if ($known -is [bool]) { @{ errors = $null; messages = @() } }
                                       else { @{ errors = $known.errors; messages = @($known.messages | Select-Object -First 10) } })
    }
    foreach ($device in @($State.notConsistent.Keys)) {
        $names = @(Get-NotConsistentOrdered $State $device)
        if (-not $at.ContainsKey($device)) { $at[$device] = @{ device = $device; notCompiled = @() } }
        $at[$device].notConsistent = @{ count = $names.Count; names = @($names | Select-Object -First 10) }
    }
    foreach ($device in @($at.Keys | Sort-Object)) {
        $at[$device].notCompiled = @($at[$device].notCompiled | Sort-Object)
        $at[$device]
    }
}
