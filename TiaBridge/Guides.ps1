# Guides.ps1 - what a session reads wherever it runs: the absolute path of a guide, from the bridge's own location, and the
# MCP instructions. A session may start in a project repo, so a relative path to a guide would not open.

function Get-BridgeRoot { Split-Path -Parent $PSScriptRoot }

# File: a guide's file name in docs\agent\.
function Get-GuidePath([string]$File) { Join-Path (Get-BridgeRoot) "docs\agent\$File" }

# Limits of a client: 4,096 characters in all; Codex reads the first 512. So the first paragraph holds the rules
# and the skill's name, with the skill's path last, and a cut takes only the end of that path. Instructions.Tests.ps1 holds both.
$script:BridgeInstructionsText = @'
TiaBridge changes TIA Portal V20 projects offline, through files in a git repo per project. The user owns downloads and online work. Only the user's own words allow what lifts a guard: safety, knowhow, override on an HMI import, archive skip, write, moved, discard, closing a project, a background session, approving the release of a library type. Start with connect. To change a project, follow skill tia-change, or read {root}\.claude\skills\tia-change\SKILL.md.

Guides, read before the work they cover:
- .s7dcl and .s7res files: {root}\docs\agent\s7dcl-format.md; run its section 9 checklist before every import.
- HMI screens, templates, pop-ups, tag tables, text lists: {root}\docs\agent\wincc-comfort-openness.md; screen objects: {root}\docs\agent\wincc-screen-objects.md.
- What Openness does with blocks, HMI objects and library types, and how it fails: {root}\docs\agent\openness-v20.md.

When something fails:
- Quote the Siemens exception type, message, detail texts and inner chain as the result gives them.
- A write that takes more than a minute: ask the user to look at TIA for an open message box. A background session has no window: quote the prompts its result lists.

Compare two archives or projects, when the user asks: from {root} run {root}\.venv\Scripts\python.exe -X utf8 -m TiaArchiveCompare.runner run --no-ask --before A --after B [--hmi] [--compile]. It starts its own TIA without a window and needs several GB of memory. Its last output line names the report; give the user that page. If it stops at a password, tell the user to run that comparison in the TIA Archive Compare window.

To start, open or show the TIA dashboard, the page of what agents do to the projects: {root}\.claude\skills\tia-dashboard\SKILL.md.

Unknown API: probe(object_path, member). Record what you find in the project's docs\project.md with [PROBE].
'@

function Get-BridgeInstructions([string]$Root = (Get-BridgeRoot)) { ($script:BridgeInstructionsText -replace '\r', '').Trim().Replace('{root}', $Root) }
