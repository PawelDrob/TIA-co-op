# Guards.ps1 - checks the bridge makes before touching TIA.

# also here: tests load this file alone
. (Join-Path $PSScriptRoot 'Guides.ps1')
$script:ObS7dclReason = "OBs are exchanged as SimaticML only: the .s7dcl of an OB loses its event class ($(Get-GuidePath 's7dcl-format.md')). Use kind block with format xml."

# 's7dcl' or 'xml'. Requested: '' (choose), 's7dcl' or 'xml'.
function Select-BlockExportFormat([bool]$IsOb, [bool]$IsKnowHowProtected, [string]$Requested = '') {
    if ($Requested -eq 's7dcl') {
        if ($IsOb) { throw $script:ObS7dclReason }
        if ($IsKnowHowProtected) { throw 'A know-how protected block can only be exported as SimaticML (format xml).' }
        return 's7dcl'
    }
    if ($Requested -eq 'xml' -or $IsOb -or $IsKnowHowProtected) { return 'xml' }
    's7dcl'
}

# $null when the .s7dcl may be imported, else the reason.
function Test-S7dclImportAllowed([string]$Path) {
    # -LiteralPath: a name holding [ ] read as a wildcard matches no file, and that would pass the guard
    if (Select-String -LiteralPath $Path -Pattern '^\s*ORGANIZATION_BLOCK\b' -Quiet) { return $script:ObS7dclReason }
    $null
}

# Why TIA would refuse the SimaticML at Path for how it is written, or $null; every XML import asks it, before TIA does.
# Seen refused, and rolled back (2026-11-05): a declaration of encoding utf-8-sig, "System does not support 'utf-8-sig'
# encoding. Line 1, position 31."; an OB rewritten by Python's ElementTree, with its namespaces as prefixes (ns0:),
# "Cannot create the 'SW.Blocks.CompileUnit' object ... error in network ''" with no inner exception. Prefixes count in a
# block document only: what other documents do with them has not been tried. A document that cannot be read past its
# declaration is left to TIA.
function Get-XmlDocumentRefusal([string]$Path) {
    $how = "Write it as an export does: <?xml version=`"1.0`" encoding=`"utf-8`"?> and each namespace as the default (xmlns=`"...`") of the element that holds it, no prefix; $(Get-GuidePath 'openness-v20.md') section 1, Editing an OB's SimaticML."
    # the declaration up to its ?>, which XML lets run over several lines: the head of the file is enough for it
    $reader = New-Object System.IO.StreamReader($Path, $true)
    $buffer = New-Object char[] 4096
    try { $head = New-Object string($buffer, 0, $reader.ReadBlock($buffer, 0, $buffer.Length)) } finally { $reader.Dispose() }
    $declaration = [regex]::Match($head, '\A<\?xml\b(?:[^?]|\?(?!>))*?\bencoding\s*=\s*(["''])(?<encoding>[^"'']*)\1')
    $encoding = $declaration.Groups['encoding']
    if ($declaration.Success -and $encoding.Value -ne 'utf-8') {
        $line = 1 + ([regex]::Matches($head.Substring(0, $encoding.Index), '\n')).Count
        return "$Path line $line declares encoding '$($encoding.Value)': TiaBridge takes utf-8 only, as an export writes it; TIA refused utf-8-sig. $how"
    }
    $block = $false; $prefixed = $null
    $xml = New-Object System.Xml.XmlTextReader($Path)
    try {
        $xml.DtdProcessing = [System.Xml.DtdProcessing]::Prohibit
        $xml.XmlResolver = $null
        # the first prefix of the document, on an element or its attributes (xmlns:ns0 declares ns0; xml: is XML's own)
        while ($xml.Read()) {
            if ($xml.NodeType -ne [System.Xml.XmlNodeType]::Element) { continue }
            if ($xml.Depth -eq 1 -and $xml.LocalName -like 'SW.Blocks.*') { $block = $true }
            if (-not $prefixed) {
                $prefix = $xml.Prefix
                if (-not $prefix -and $xml.MoveToFirstAttribute()) {
                    do { $prefix = if ($xml.Prefix -eq 'xmlns') { $xml.LocalName } elseif ($xml.Prefix -ne 'xml') { $xml.Prefix } }
                    while (-not $prefix -and $xml.MoveToNextAttribute())
                }
                if ($prefix) { $prefixed = @{ line = $xml.LineNumber; prefix = $prefix } }
                [void]$xml.MoveToElement()
            }
            if ($block -and $prefixed) { break }
        }
    } catch { } finally { $xml.Close() }
    if ($block -and $prefixed) {
        return "$Path line $($prefixed.line) holds the namespace prefix '$($prefixed.prefix)': TIA refuses a block's SimaticML whose namespaces carry a prefix, as Python's ElementTree writes them. $how"
    }
    $null
}

# Which kind takes a document of each class of Get-DocumentObjectClass.
$script:DocumentClassKinds = @{
    block = @{ kind = 'block'; what = 'an FB or FC' }
    OB = @{ kind = 'block'; what = 'an OB' }
    DB = @{ kind = 'db'; what = 'a DB' }
    type = @{ kind = 'type'; what = 'a PLC data type' }
    tags = @{ kind = 'plc_tag_table'; what = 'a PLC tag table' }
    watch = @{ kind = 'watch_table'; what = 'a watch table' }
    HMI = @{ kind = 'hmi_*'; what = 'an HMI object' }
}

# Why the document at Path must not reach TIA under this kind, or $null. Each kind lists its own objects only, and TIA goes
# by the document: under the wrong kind no guard sees the object, and the test instance of a type in work holds TIA on a
# modal message. So refused: a file that is no document (Import reads any file as SimaticML, the guards by its extension);
# SimaticML TIA would refuse for how it is written (Get-XmlDocumentRefusal); a .s7dcl with a keyword whose object cannot be
# read, which would go by its file name; a second declaration; an OB's .s7dcl; and the document of another kind, under a
# kind of one class of documents. A document with no keyword or class passes: TIA judges it. A library type's path may be
# its .libinfo: then the documents beside it.
function Get-DocumentRefusal([string]$KindName, [string]$Path) {
    $base = Join-Path ([System.IO.Path]::GetDirectoryName($Path)) ([System.IO.Path]::GetFileNameWithoutExtension($Path))
    $extension = [System.IO.Path]::GetExtension($Path)
    $docs = if ($extension -in '.s7dcl', '.xml') { @($Path) }
            elseif ($extension -eq '.libinfo' -and $KindName -eq 'library_type') { @("$base.s7dcl", "$base.xml") }
            else { return "$Path is no document: PLC objects are imported from a .s7dcl or an .xml." }
    foreach ($doc in $docs) {
        if (-not (Test-Path -LiteralPath $doc)) { continue }
        $isSd = [System.IO.Path]::GetExtension($doc) -eq '.s7dcl'
        if (-not $isSd -and ($why = Get-XmlDocumentRefusal $doc)) { return $why }
        $name = Get-DocumentDeclaredName $doc
        if ($isSd -and -not $name -and (Select-String -LiteralPath $doc -Pattern "\b($script:S7dclKeywords)\b" -Quiet)) {
            return "$doc holds a block keyword, but the bridge cannot read the object it declares, so the guards would go by the file name. Write its head as an export does: at most comments and one pragma block in front of the keyword, then the name."
        }
        $second = Get-DocumentSecondDeclaration $doc
        if ($second) { return "$doc declares '$name' and also '$second'. The guards go by one object per document, as an export writes it: put each object in its own file." }
        $className = Get-DocumentObjectClass $doc
        $class = $script:DocumentClassKinds[$className]
        if (-not $class) { continue }
        if ($KindName -eq 'library_type') {
            if ($className -notin 'type', 'block') { return "$doc holds $($class.what): a library type is a PLC data type, an FB or an FC." }
            continue
        }
        if ($KindName -in 'block', 'db', 'type', 'plc_tag_table', 'watch_table' -and $class.kind -ne $KindName) {
            return "$doc holds $($class.what): import it with kind $($class.kind), not $KindName. Kind $KindName looks only at its own objects, so the guards would not see the object."
        }
        # by the keyword the name reader found: the line scan of Test-S7dclImportAllowed misses one after a comment on its line
        if ($isSd -and $className -eq 'OB') { return $script:ObS7dclReason }
    }
    $null
}

# An F-block by its ProgrammingLanguage (F_LAD, F_FBD, F_STL, F_DB, F_CALL, F_LAD_LIB, F_FBD_LIB, ...). Not FBD, FCP, FLD.
function Test-FBlockLanguage([string]$Language) { $Language -like 'F_*' }

# $true when the documents of Path are those of an F-block: the block attribute S7_Safety of the .s7dcl (read up to the
# block keyword only, the code below it may name anything; of a TYPE up to its name, its attributes come after the
# keyword), the F_ language of the SimaticML or the IsFailsafeCompliant of a UDT's. Reads the documents beside
# Path, so the path of an .s7res or a library type's .libinfo counts too. A document it cannot read throws: never a pass.
# ReadAllLines, not ReadLines: leaving a ReadLines loop early keeps the file locked until a garbage collection, and it is
# the agent's next edit and the next export's target. Keywords match in their exported upper case only, so a comment or
# a text starting with "Function" does not end the scan; a keyword in lower case reads on, which can only over-refuse.
function Test-FBlockDocument([string]$Path) {
    $base = Join-Path ([System.IO.Path]::GetDirectoryName($Path)) ([System.IO.Path]::GetFileNameWithoutExtension($Path))
    $sd = "$base.s7dcl"
    if (Test-Path -LiteralPath $sd) {
        foreach ($line in [System.IO.File]::ReadAllLines($sd)) {
            if ($line -cmatch '^\s*(FUNCTION_BLOCK|FUNCTION|ORGANIZATION_BLOCK|DATA_BLOCK)\b' -or $line -cmatch '^\s*(?:"[^"]*"|[^\s":{]+)\s*:\s*STRUCT\b') { break }
            if ($line -match '\bS7_Safety\s*:=\s*["'']?true["'']?') { return $true }
        }
    }
    $xml = "$base.xml"
    if (Test-Path -LiteralPath $xml) {
        if (Select-String -LiteralPath $xml -Pattern '<ProgrammingLanguage>\s*F_|<IsFailsafeCompliant>\s*true' -Quiet -ErrorAction Stop) { return $true }
    }
    $false
}

# The refusal of a write to an F-block or, by its document, an F-compliant PLC data type. A change to the safety program
# is the user's decision, also after safety_login, which lets every later call change F-blocks like any block.
# A library type can be either; the kind does not tell which.
function Get-FBlockRefusal([string]$KindName, [string]$Name, [string]$Write) {
    $what = switch ($KindName) { 'type' { 'an F-compliant PLC data type' } 'library_type' { 'an F-block or F-compliant PLC data type' } default { 'an F-block' } }
    "$KindName '$Name' is $what`: the $Write would change the safety program. Pass safety: true only when the user asked for this safety change; TIA also needs safety_login for it."
}

# The argument of every tool that can change F-blocks.
$script:SafetyArgument = @{ type = 'boolean'; description = 'allows the write to change F-blocks and F-compliant PLC data types (the safety program). Only when the user asked for this safety change; never to get past the refusal' }

# Why a write that cannot name the blocks it will change must not run, or $null: the same rule as for import and delete,
# per PLC instead of per block. Devices: the PLCs it writes to, default all. Asks TIA, so a login made in TIA's own window
# counts too. Only a password set and no login is closed (TIA then refuses the change itself): a safety program without
# a password needs no login, and a state TIA does not answer is never a pass. No SafetyAdministration: no safety program.
function Get-SafetyProgramRefusal([string]$Write, $Safety, [string[]]$Devices = @()) {
    if ($Safety -eq $true) { return $null }   # only a true opens the safety program, not the text 'false'
    $open = @(foreach ($s in Get-TiaSoftwareList) {
        if ($s.kind -ne 'plc' -or ($Devices.Count -and $Devices -notcontains $s.device)) { continue }
        $admin = Get-SafetyAdministration $s.software
        if (-not $admin) { continue }
        if ($admin.IsSafetyOfflineProgramPasswordSet -eq $true -and $admin.IsLoggedOnToSafetyOfflineProgram -eq $false) { continue }
        $s.device
    })
    if (-not $open.Count) { return $null }
    "$Write can change F-blocks, and TIA would let it change the safety program of $(@($open | Sort-Object -Unique) -join ', ') (logged on, or no password). Nothing was changed. Pass safety: true only when the user asked for this safety change; if they did not, ask them."
}

# The refusal of a write that removes the code of a know-how protected block (Write: delete, replace).
# Name: one name, or several joined by "', '"; More: how many protected objects the list leaves out.
function Get-KnowHowRefusal([string]$KindName, [string]$Name, [string]$Write, [int]$More = 0) {
    $verb = $(if ($More -or $Name.Contains("', '")) { 'are' } else { 'is' })
    "$KindName '$Name'$(if ($More) { " and $More more" }) $verb know-how protected: its code cannot be exported, so the repo holds no copy to restore it from, only a project archive can (the session archive, unless it was skipped). Pass knowhow: true only when the user asked for this $Write."
}

# The know-how protected objects a master copy with mode Replace may replace: those of its names, or for a master copy
# of a folder (IsGroup) every one, wherever it sits: what such a copy holds is not known before it is placed, and what
# TIA does with a same-named block in another folder is not probed. Entries: the items of the tree it goes into.
function Get-KnowHowReplaced([object[]]$Entries, [string[]]$Names, [bool]$IsGroup) {
    foreach ($e in $Entries) {
        if ($e.obj.IsKnowHowProtected -and ($IsGroup -or $Names -contains $e.name)) { $e.name }
    }
}

# FaceplateTypeName = _Library@$@<folder>@$@...@$@<type> V <x.y.z>  (docs/agent/wincc-comfort-openness.md 4.2)
function Get-FaceplateRefs([string]$Path) {
    [xml]$doc = Get-Content -LiteralPath $Path -Raw -Encoding UTF8
    foreach ($n in $doc.SelectNodes("//*[local-name()='FaceplateTypeName']")) {
        $raw = $n.InnerText.Trim()
        $parts = $raw -split '@\$@'
        $last = $parts[-1]
        $name = $last; $version = ''
        if ($last -match '^(.*) V (\d+(?:\.\d+)*)$') { $name = $Matches[1]; $version = $Matches[2] }
        $folder = ''
        if ($parts.Count -gt 2) { $folder = ($parts[1..($parts.Count - 2)]) -join '/' }
        @{ raw = $raw; name = $name; version = $version; folder = $folder }
    }
}

# LibraryTypes: @{ name; folder; versions[] } from the project library. Returns one problem per bad reference.
function Test-FaceplateRefs([object[]]$Refs, [object[]]$LibraryTypes) {
    foreach ($r in $Refs) {
        $types = @($LibraryTypes | Where-Object { $_.name -eq $r.name })
        if (-not $types.Count) {
            @{ type = $r.name; ref = $r.raw; reason = "Faceplate type '$($r.name)' is not in the project library."; available = @() }
            continue
        }
        $versions = @($types | ForEach-Object { $_.versions } | ForEach-Object { [string]$_ } | Sort-Object -Unique |
            Sort-Object { $v = $null; if ([version]::TryParse($(if ($_ -match '\.') { $_ } else { "$_.0" }), [ref]$v)) { $v } else { [version]'0.0' } })
        if ($versions -notcontains $r.version) {
            @{ type = $r.name; ref = $r.raw; reason = "Faceplate type '$($r.name)' V $($r.version) is not in the project library (importing it crashed TIA on 2026-10-02)."; available = $versions }
        }
    }
}
