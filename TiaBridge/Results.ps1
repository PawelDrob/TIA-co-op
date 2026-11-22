# Results.ps1 - what a tool's result says to the agent: the result as its log holds it, made short. A result stays in the
# conversation and is read again by every later request, so what repeats is said once, what holds nothing is counted, and
# what only a reader of the log wants stays in the log. The log keeps everything (Bridge.ps1 writes it first); a failure
# keeps its Siemens type, message, detail texts and inner chain at its first of a kind.

# The clients that read the whole result, as before: programs of this repo that drive the bridge over MCP and read fields
# the short one leaves to the log (TiaArchiveCompare\runner\bridge.py: full_export details, background_open steps), by the
# name their initialize sends. A report run of the TIA dashboard (TiaBridge.ps1 -ReportRun) reads the whole one too.
# Tests\Results.Tests.ps1 holds the names against the clients' code.
$script:WholeResultClients = @('TiaArchiveCompare')

# A step of a background session this long is named in the short result; a minute is when the bridge's instructions
# ask the user to look at TIA.
$script:SlowStepMs = 60000

# The tools that give project and repo: their result says them always, every other one when they changed.
$script:GivesProject = @('connect', 'background_open', 'project_open')

function Test-WholeResultClient { [bool]($script:Bridge.reportRun -or $script:WholeResultClients -contains $script:McpClientName) }

# A copy of a dictionary, in its order, without the keys named.
function Copy-ResultFields([System.Collections.IDictionary]$Value, [string[]]$Without = @()) {
    $c = [ordered]@{}
    foreach ($k in $Value.Keys) { if ($Without -notcontains $k) { $c[$k] = $Value[$k] } }
    $c
}

function Test-EmptyValue($Value, [switch]$DropFalse) {
    if ($null -eq $Value) { return $true }
    if ($Value -is [string]) { return $Value.Length -eq 0 }
    if ($Value -is [bool]) { return $DropFalse -and -not $Value }
    if ($Value -is [System.Collections.IDictionary]) { return $Value.Count -eq 0 }
    if ($Value -is [System.Collections.IList]) { return $Value.Count -eq 0 }
    $false
}

# The value without null, empty texts, lists and dictionaries at any depth, and with DropFalse without false too: the reader
# loses nothing, an absent value reads as that. ok always stays; an element of a list is never left out.
function Remove-EmptyValues($Value, [switch]$DropFalse) {
    if ($Value -is [System.Collections.IDictionary]) {
        $c = [ordered]@{}
        foreach ($k in $Value.Keys) {
            $v = Remove-EmptyValues $Value[$k] -DropFalse:$DropFalse
            if ($k -eq 'ok' -or -not (Test-EmptyValue $v -DropFalse:$DropFalse)) { $c[$k] = $v }
        }
        return $c
    }
    if ($Value -is [System.Collections.IList] -and $Value -isnot [string]) {
        $list = @(foreach ($v in $Value) { , (Remove-EmptyValues $v -DropFalse:$DropFalse) })
        return , $list
    }
    $Value
}

# What makes two items' errors, notes or messages alike: the value as text, its strings with the item's name (as a whole
# word) taken out, the keys sorted. Two failures alike differ only where they name their object.
function Get-AlikeKey($Value, [string]$Name) {
    if ($null -eq $Value) { return 'null' }
    if ($Value -is [string]) {
        if (-not $Name) { return "'$Value'" }
        return "'$([regex]::Replace($Value, "(?<![\w])$([regex]::Escape($Name))(?![\w])", '{name}'))'"
    }
    if ($Value -is [System.Collections.IDictionary]) {
        $parts = foreach ($k in @($Value.Keys | Where-Object { $_ -notin 'at', 'alike' } | Sort-Object)) { "$k=$(Get-AlikeKey $Value[$k] $Name)" }
        return "{$($parts -join ',')}"
    }
    if ($Value -is [System.Collections.IList]) { return "[$((@(foreach ($v in $Value) { Get-AlikeKey $v $Name })) -join ',')]" }
    [string]$Value
}

# A Siemens error as the agent reads it: type, message, detail texts and inner chain as the log has them; the bridge's own
# code location (at), an empty inner chain and the flags that are false stay in the log.
function Get-ShortError($Err) {
    if ($Err -isnot [System.Collections.IDictionary]) { return $Err }
    $e = Copy-ResultFields $Err @('at')
    foreach ($k in 'tiaEnded', 'tiaDisconnected') { if ($e.Contains($k) -and -not $e[$k]) { $e.Remove($k) } }
    if ($e.Contains('inner') -and -not @($e.inner).Count) { $e.Remove('inner') }
    $e
}

# Items whose error, note or messages are alike an earlier item's say so ("as <that item>"); that earlier item's error
# counts them (alike). Items are copied, the ones given are not changed.
function Compress-ItemRepeats([object[]]$Items) {
    $seen = @{}
    $out = New-Object System.Collections.ArrayList
    foreach ($i in $Items) {
        if ($i -isnot [System.Collections.IDictionary]) { [void]$out.Add($i); continue }
        $c = Copy-ResultFields $i
        if ($c.Contains('error')) { $c.error = Get-ShortError $c.error }
        foreach ($k in 'error', 'note', 'messages') {
            if (-not $c.Contains($k) -or $null -eq $c[$k]) { continue }
            $key = "$k|$(Get-AlikeKey $c[$k] ([string]$c.name))"
            $first = $seen[$key]
            if ($first) {
                $c[$k] = "as $($first.name)"
                if ($k -eq 'error') {
                    if ($first.error -is [System.Collections.IDictionary]) { $first.error.alike = 1 + [int]$first.error.alike }
                }
            }
            else { $seen[$key] = $c }
        }
        [void]$out.Add($c)
    }
    , $out.ToArray()
}

# The steps of a background session: how many and how long, and each one of a minute or more.
function Get-StepsSummary([object[]]$Steps) {
    $ms = 0; foreach ($s in $Steps) { $ms += [int]$s.ms }
    $sum = [ordered]@{ count = @($Steps).Count; ms = $ms }
    $slow = @(foreach ($s in $Steps) { if ([int]$s.ms -ge $script:SlowStepMs) { [ordered]@{ step = $s.step; ms = [int]$s.ms } } })
    if ($slow.Count) { $sum.slow = $slow }
    $sum
}

# A part of full_export that holds nothing: no object, nothing failed, left out, removed or kept.
function Test-EmptyPart($Record) {
    if ($Record -isnot [System.Collections.IDictionary]) { return $false }
    if ($Record.listError -or $Record.stopped -or $Record.leftOut -or [int]$Record.count) { return $false }
    foreach ($k in 'failed', 'notExported', 'knowHowProtected', 'fellBack', 'removed', 'keptUncommitted', 'keptRepos') {
        if (@($Record[$k] | Where-Object { $null -ne $_ }).Count) { return $false }
    }
    $true
}

# The failed lines of a full_export, a failure that repeats said once: the first object's line as the log has it, with how
# many more are alike and their names. A part or a device that failed has its line of its own.
function Get-ShortExportFailures([object[]]$Details) {
    $groups = New-Object System.Collections.ArrayList
    $byKind = @{}
    foreach ($e in @(Get-FullExportFailures $Details)) {
        if (-not $e.failure) { [void]$groups.Add(@{ text = $e.text; alike = @() }); continue }
        $f = $e.failure
        $kind = if ($f.error) { Get-AlikeKey ([ordered]@{ type = $f.error.type; message = $f.error.message }) ([string]$f.name) }
                else { "state $($f.messages.state)" }
        $g = $byKind[$kind]
        if (-not $g) {
            $g = @{ text = $e.text; where = $e.where; alike = (New-Object System.Collections.ArrayList) }
            $byKind[$kind] = $g
            [void]$groups.Add($g)
        }
        else { [void]$g.alike.Add($(if ($e.where -eq $g.where) { $e.object } else { "$($e.where): $($e.object)" })) }
    }
    @(foreach ($g in $groups) {
        if (@($g.alike).Count) { "$($g.text) (+$(@($g.alike).Count) alike: $(@($g.alike) -join ', '))" } else { $g.text }
    })
}

function Get-ShortFullExport([System.Collections.IDictionary]$R) {
    $s = Copy-ResultFields $R @('details', 'limits', 'times', 'planMs', 'saveMs')
    foreach ($k in 'removed', 'keptUncommitted', 'keptRepos', 'failed') { if ($s.Contains($k) -and -not @($s[$k]).Count) { $s.Remove($k) } }
    $details = @($R.details)
    if ($R.Contains('details') -and $details.Count -eq @($R.parts).Count) {
        $lines = @($R.parts)
        $s.parts = @(for ($i = 0; $i -lt $lines.Count; $i++) { if (-not (Test-EmptyPart $details[$i])) { $lines[$i] } })
        $empty = $lines.Count - $s.parts.Count
        if ($empty) { $s.emptyParts = $empty }
        if (@($R.failed).Count) { $s.failed = @(Get-ShortExportFailures $details) }
    }
    $s
}

function Get-ShortBackground([System.Collections.IDictionary]$R) {
    $s = Copy-ResultFields $R
    if ($R.Contains('steps')) { $s.steps = Get-StepsSummary @($R.steps) }
    $s
}

# A compile message tree as a list: each error and warning with the path to it (' / ' between the levels); a message that
# repeats said once with every path. Seen: what earlier items said (state|description -> item name).
function Get-CompileMessageList($Tree, [hashtable]$Seen, [string]$ItemName) {
    $found = New-Object System.Collections.ArrayList
    $walk = {
        param($Node, [string[]]$Path)
        if ($Node -isnot [System.Collections.IDictionary]) { return }
        $p = @($Path) + @(if ($Node.path) { [string]$Node.path })
        $children = @($Node.messages | Where-Object { $null -ne $_ })
        if (@('Error', 'Warning') -contains [string]$Node.state -and ($Node.description -or -not $children.Count)) {
            [void]$found.Add(@{ path = ($p -join ' / '); state = [string]$Node.state; description = [string]$Node.description })
        }
        foreach ($c in $children) { & $walk $c $p }
    }
    & $walk $Tree @()
    $byKey = [ordered]@{}
    foreach ($m in $found) {
        $k = "$($m.state)|$($m.description)"
        if (-not $byKey.Contains($k)) { $byKey[$k] = New-Object System.Collections.ArrayList }
        [void]$byKey[$k].Add($m.path)
    }
    @(foreach ($k in $byKey.Keys) {
        $state, $description = $k -split '\|', 2
        $paths = @($byKey[$k])
        $e = [ordered]@{}
        if ($paths.Count -eq 1) { $e.path = $paths[0] } else { $e.paths = $paths }
        $e.state = $state
        $e.description = $(if ($Seen.ContainsKey($k)) { "as in $($Seen[$k])" } else { $Seen[$k] = $ItemName; $description })
        $e
    })
}

# compile: the items with errors or warnings, each message once, and how many items are clean.
function Get-ShortCompile([System.Collections.IDictionary]$R) {
    $s = Copy-ResultFields $R
    if (-not $R.Contains('items')) { return $s }
    $clean = 0
    $seen = @{}
    $s.items = @(foreach ($i in @($R.items)) {
        if ($i -isnot [System.Collections.IDictionary]) { $i; continue }
        if ($i.ok -and -not [int]$i.errors -and -not [int]$i.warnings -and -not $i.error -and -not $i.refused) { $clean++; continue }
        $c = Copy-ResultFields $i @('messages')
        if ($c.Contains('error')) { $c.error = Get-ShortError $c.error }
        if ($i.messages) {
            $list = @(Get-CompileMessageList $i.messages $seen ([string]$i.name))
            if ($list.Count) { $c.messages = $list }
        }
        $c
    })
    if ($clean) { $s.cleanItems = $clean }
    $s
}

# import, export, save: no empty values, and what repeats on every item said once.
function Get-ShortItems([System.Collections.IDictionary]$R) {
    $s = Copy-ResultFields $R
    foreach ($k in @($s.Keys)) {
        if ($k -in 'ok', 'items') { continue }
        $v = Remove-EmptyValues $s[$k]
        if (Test-EmptyValue $v) { $s.Remove($k) } else { $s[$k] = $v }
    }
    if ($s.Contains('items')) { $s.items = Compress-ItemRepeats @(foreach ($i in @($R.items)) { , (Remove-EmptyValues $i) }) }
    $s
}

# The short result of a tool, a new dictionary: the one given stays as the log has it. Said: what earlier short results
# gave the agent (project, repo), kept up to date here.
function Get-ShortResult([string]$Tool, [System.Collections.IDictionary]$Result, [System.Collections.IDictionary]$Said) {
    $s = switch ($Tool) {
        'full_export' { Get-ShortFullExport $Result }
        { $_ -in 'background_open', 'background_close' } { Get-ShortBackground $Result }
        'compile' { Get-ShortCompile $Result }
        'change_report' { Remove-EmptyValues $Result -DropFalse }
        { $_ -in 'import', 'export', 'save' } { Get-ShortItems $Result }
        default { Copy-ResultFields $Result }
    }
    # the envelope: a background session's step of this call is in the log and in the steps log of background_close
    if ($Tool -notlike 'background_*' -and $s.step -is [System.Collections.IDictionary]) { $s.Remove('step') }
    if ($s.Contains('times')) { $s.Remove('times') }
    if ($s.Contains('error')) { $s.error = Get-ShortError $s.error }
    if ($s.Contains('prompts')) { $s.prompts = @(foreach ($p in @($s.prompts)) { , (Remove-EmptyValues $p) }) }
    foreach ($k in 'project', 'repo') {
        if (-not $Result.Contains($k)) { continue }
        if ($script:GivesProject -notcontains $Tool -and $Said.Contains($k) -and $Said[$k] -ceq $Result[$k]) { $s.Remove($k) }
        else { $Said[$k] = $Result[$k] }
    }
    $s
}
