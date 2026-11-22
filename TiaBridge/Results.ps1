# Results.ps1 - what a tool's result says to the agent: the result as its log holds it, made short. A result stays in the
# conversation and is read again by every later request, so what repeats is said once, what holds nothing is counted, and
# what only a reader of the log wants stays in the log. The log keeps everything (Bridge.ps1 writes it first); a failure
# keeps its Siemens type, message, detail texts and inner chain at its first of a kind.

# The clients that read the whole result: programs of this repo that drive the bridge over MCP and read fields
# the short one leaves to the log (TiaArchiveCompare\runner\bridge.py: full_export details, background_open steps), by the
# name their initialize sends. A report run of the TIA dashboard (TiaBridge.ps1 -ReportRun) reads the whole one too.
# Tests\Results.Tests.ps1 holds the names against the clients' code.
$script:WholeResultClients = @('TiaArchiveCompare')

# A step of a background session this long is named in the short result; a minute is when the bridge's instructions
# ask the user to look at TIA.
$script:SlowStepMs = 60000

# The tools that give project and repo: their result says them always, every other one when they changed. tia_status is
# the tool an agent asks when it is unsure where it stands, and a log's path in any answer is relative to the repo.
$script:GivesProject = @('connect', 'background_open', 'project_open', 'tia_status')

# Where the answer leaves a value out: the field, by its path in the result (items[].folder: the folder of each item), and
# the one value it is left out at, the value a reader takes for granted when the field is absent. Every other value stays:
# a false, an empty list or a zero that is the news is said. A change report never hides a change: of it only what has no
# value, a network's or tag's side it is not on, a title, comment or device it has not. '*': every tool. Why each:
# - prompts: the bridge writes "" for a text TIA's dialog did not have.
# - full_export removed, keptUncommitted, keptRepos, failed: their counts (removedCount, keptCount, failedCount) stay.
# - import findings[].object: null for a finding about the document as a whole, not one object of it.
# - change_report before, after: null on the side a new or removed network or tag is not on; its state says which. A
#   network's title emptied keeps the old one in was, a tag's comment added or removed is in its changes: both stay.
#   hmi[].device: "" for an HMI folder of no device.
$script:UsualValues = @{
    '*'           = @{ 'prompts[].caption' = ''; 'prompts[].text' = ''; 'prompts[].detail' = ''; 'prompts[].choices' = ''; 'prompts[].answer' = ''; 'prompts[].icon' = '' }
    full_export   = @{ removed = @(); keptUncommitted = @(); keptRepos = @(); failed = @() }
    import        = @{ 'items[].findings[].object' = $null }
    change_report = @{ 'blocks[].networks[].before' = $null; 'blocks[].networks[].after' = $null; 'blocks[].networks[].title' = ''
                       'plcTags[].rows[].before' = $null; 'plcTags[].rows[].after' = $null; 'plcTags[].rows[].before.comment' = ''
                       'plcTags[].rows[].after.comment' = ''; 'hmi[].device' = '' }
}

# The tools whose answer is made short field by field: their result is copied whole into dictionaries, a value at its usual
# one left out and every error made short. Every other tool's answer is its result, its error and prompts made short.
$script:ShortenedTools = @('full_export', 'background_open', 'background_close', 'compile', 'change_report', 'import', 'export', 'save')

# The fields only the log keeps: they are not copied at all (a full_export's details are the most of its result).
$script:LogOnlyFields = @{ '*' = @('times'); full_export = @('details', 'limits', 'planMs', 'saveMs') }

# A map whose keys are texts compared as they are: PowerShell's own ignore case, and two Siemens messages that differ only
# in case are not alike.
function New-OrdinalMap { New-Object System.Collections.Hashtable ([StringComparer]::Ordinal) }

# How many values a list holds, a null one not counted (@($null) holds one).
function Get-ValueCount($List) { @($List | Where-Object { $null -ne $_ }).Count }

function Test-WholeResultClient { [bool]($script:Bridge.reportRun -or $script:WholeResultClients -contains $script:McpClientName) }

# Whether a value is the usual one of its field (UsualValues): null, a text compared as it is, true or false, or a list
# with no value (null counts as one: a result without a list of its own may hold null).
function Test-UsualValue($Value, $Usual) {
    if ($null -eq $Usual) { return $null -eq $Value }
    if ($Usual -is [string]) { return $Value -is [string] -and $Value -ceq $Usual }
    if ($Usual -is [bool]) { return $Value -is [bool] -and $Value -eq $Usual }
    if ($Usual -is [System.Collections.IList]) { return $null -eq $Value -or ($Value -is [System.Collections.IList] -and -not (Get-ValueCount $Value)) }
    $false
}

# Puts Value into the answer's dictionary Into as Key, unless it is the usual value of its field at Path; an error made
# short. AsIs: the value as the result holds it, not copied.
function Add-AnswerField([System.Collections.IDictionary]$Into, [string]$Key, $Value, [System.Collections.IDictionary]$Usual, [string]$Path, [switch]$AsIs) {
    # assigned, not output: an empty list output is no value
    $v = $Value
    if (-not $AsIs) { $v = Copy-AnswerValue $Value $Usual $Path }
    if ($Usual.Contains($Path) -and (Test-UsualValue $v $Usual[$Path])) { return }
    if ($Key -eq 'error') { $v = Get-ShortError $v }
    $Into[$Key] = $v
}

# A copy of a value of a result as the answer holds it, at any depth: dictionaries for objects (ConvertFrom-Json gives the
# rows of a change report as objects), the fields at their usual value left out (Add-AnswerField). Path: where it is.
function Copy-AnswerValue($Value, [System.Collections.IDictionary]$Usual, [string]$Path) {
    if ($Value -is [System.Management.Automation.PSCustomObject]) {
        $d = [ordered]@{}
        foreach ($p in $Value.PSObject.Properties) { $d[$p.Name] = $p.Value }
        $Value = $d
    }
    if ($Value -is [System.Collections.IDictionary]) {
        $c = [ordered]@{}
        foreach ($k in $Value.Keys) { Add-AnswerField $c $k $Value[$k] $Usual "$Path.$k" }
        return $c
    }
    if ($Value -is [System.Collections.IList]) {
        $list = @(foreach ($v in $Value) { , (Copy-AnswerValue $v $Usual "$Path[]") })
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
    $e = [ordered]@{}
    foreach ($k in $Err.Keys) { if ($k -ne 'at') { $e[$k] = $Err[$k] } }
    foreach ($k in 'tiaEnded', 'tiaDisconnected') { if ($e.Contains($k) -and -not $e[$k]) { $e.Remove($k) } }
    if ($e.Contains('inner') -and -not (Get-ValueCount $e.inner)) { $e.Remove('inner') }
    $e
}

# Items whose error, note or messages are alike an earlier item's say so ("as <that item>"); that earlier item's error
# counts them (alike). Items: the answer's copies (Copy-AnswerValue), changed here.
function Compress-ItemRepeats([object[]]$Items) {
    $seen = New-OrdinalMap
    $out = New-Object System.Collections.ArrayList
    foreach ($c in $Items) {
        if ($c -isnot [System.Collections.IDictionary]) { [void]$out.Add($c); continue }
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
    $Steps = @($Steps | Where-Object { $null -ne $_ })
    $ms = 0; foreach ($s in $Steps) { $ms += [int]$s.ms }
    $sum = [ordered]@{ count = @($Steps).Count; ms = $ms }
    $slow = @(foreach ($s in $Steps) { if ([int]$s.ms -ge $script:SlowStepMs) { [ordered]@{ step = $s.step; ms = [int]$s.ms } } })
    if ($slow.Count) { $sum.slow = $slow }
    $sum
}

# The failed lines of a full_export, a failure that repeats said once: lines, the first object's line as the log has it,
# with how many more are alike and their names; errors, the first of each kind whole, as the agent quotes it: its
# Siemens error (the line cuts the message and has no detail texts or inner chain), or with none TIA's messages of the
# export. Alike: the same error or messages, the object's name taken out. A part that could not be listed is a failure
# of its own kind; a device refused has its line, whole.
function Get-ShortExportFailures([object[]]$Details) {
    $groups = New-Object System.Collections.ArrayList
    $errors = New-Object System.Collections.ArrayList
    $byKind = New-OrdinalMap
    foreach ($e in @(Get-FullExportFailures $Details)) {
        $f = $e.failure
        $whole = if ($f.error) { [ordered]@{ error = Get-ShortError $f.error } }
                 elseif ($f) { [ordered]@{ messages = $f.messages } }
                 elseif ($e.listError) { [ordered]@{ error = Get-ShortError $e.listError } }
        if (-not $whole) { [void]$groups.Add(@{ text = $e.text; alike = @() }); continue }
        $kind = "$(if ($f) { 'object' } else { 'part' })|$(Get-AlikeKey $whole ([string]$f.name))"
        $g = $byKind[$kind]
        if (-not $g) {
            $g = @{ text = $e.text; where = $e.where; alike = (New-Object System.Collections.ArrayList) }
            $byKind[$kind] = $g
            [void]$groups.Add($g)
            $first = [ordered]@{ object = "$($e.where): $($e.object)" }
            foreach ($k in $whole.Keys) { $first[$k] = $whole[$k] }
            [void]$errors.Add($first)
        }
        else { [void]$g.alike.Add($(if ($e.where -eq $g.where) { $e.object } else { "$($e.where): $($e.object)" })) }
    }
    $lines = @(foreach ($g in $groups) {
        if (@($g.alike).Count) { "$($g.text) (+$(@($g.alike).Count) alike: $(@($g.alike) -join ', '))" } else { $g.text }
    })
    @{ lines = $lines; errors = $errors.ToArray() }
}

# S: the answer as Get-ShortResult copied it; R: the result, whose details only the log keeps.
function Get-ShortFullExport([System.Collections.IDictionary]$S, [System.Collections.IDictionary]$R) {
    $details = @($R.details)
    if ($R.Contains('details') -and $details.Count -eq @($R.parts).Count) {
        $lines = @($R.parts)
        $S.parts = @(for ($i = 0; $i -lt $lines.Count; $i++) { if (-not (Test-EmptyPartRecord $details[$i])) { $lines[$i] } })
        $empty = $lines.Count - $S.parts.Count
        if ($empty) { $S.emptyParts = $empty }
        if (Get-ValueCount $R.failed) {
            $f = Get-ShortExportFailures $details
            $S.failed = $f.lines
            if ($f.errors.Count) { $S.failedErrors = $f.errors }
        }
    }
    $S
}

function Get-ShortBackground([System.Collections.IDictionary]$S) {
    if ($S.Contains('steps')) { $S.steps = Get-StepsSummary @($S.steps) }
    $S
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
    $byKey = New-Object System.Collections.Specialized.OrderedDictionary ([StringComparer]::Ordinal)
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
function Get-ShortCompile([System.Collections.IDictionary]$S) {
    if (-not $S.Contains('items')) { return $S }
    $clean = 0
    $seen = New-OrdinalMap
    $S.items = @(foreach ($i in @($S.items)) {
        if ($i -isnot [System.Collections.IDictionary]) { , $i; continue }
        if ($i.ok -and -not [int]$i.errors -and -not [int]$i.warnings -and -not $i.error -and -not $i.refused) { $clean++; continue }
        $tree = $i.messages
        $i.Remove('messages')
        if ($tree) {
            $list = @(Get-CompileMessageList $tree $seen ([string]$i.name))
            if ($list.Count) { $i.messages = $list }
        }
        $i
    })
    if ($clean) { $S.cleanItems = $clean }
    $S
}

# The short result of a tool, a new dictionary: the one given stays as the log has it. Given: what earlier short results
# gave the agent of the project (project, repo), kept up to date here.
function Get-ShortResult([string]$Tool, [System.Collections.IDictionary]$Result, [System.Collections.IDictionary]$Given) {
    $usual = @{}
    foreach ($t in '*', $Tool) { $u = $script:UsualValues[$t]; if ($u) { foreach ($k in $u.Keys) { $usual[$k] = $u[$k] } } }
    $logOnly = @($script:LogOnlyFields['*']) + @($script:LogOnlyFields[$Tool])
    $deep = $script:ShortenedTools -contains $Tool
    $s = [ordered]@{}
    foreach ($k in $Result.Keys) {
        if ($logOnly -contains $k) { continue }
        Add-AnswerField $s $k $Result[$k] $usual $k -AsIs:(-not $deep -and $k -notin 'error', 'prompts')
    }
    $s = switch ($Tool) {
        'full_export' { Get-ShortFullExport $s $Result }
        { $_ -in 'background_open', 'background_close' } { Get-ShortBackground $s }
        'compile' { Get-ShortCompile $s }
        { $_ -in 'import', 'export', 'save' } { if ($s.Contains('items')) { $s.items = Compress-ItemRepeats @($s.items) }; $s }
        default { $s }
    }
    # the envelope: a background session's step of this call is in the log and in the steps log of background_close
    if ($Tool -notlike 'background_*' -and $s.step -is [System.Collections.IDictionary]) { $s.Remove('step') }
    # last, after everything that could throw: an answer the dispatch drops for the whole one (Bridge.ps1) must not have
    # marked project and repo as given
    foreach ($k in 'project', 'repo') {
        if (-not $Result.Contains($k)) { continue }
        if ($script:GivesProject -notcontains $Tool -and $Given.Contains($k) -and $Given[$k] -ceq $Result[$k]) { $s.Remove($k) }
        else { $Given[$k] = $Result[$k] }
    }
    $s
}
