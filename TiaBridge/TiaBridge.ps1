# TiaBridge.ps1 - MCP server giving a Claude Code agent access to the offline TIA Portal V20 project.
# First setup registers it (tools\setup\setup.ps1).
# Agent guides: docs\agent\. Settings: TiaBridge\settings.json (optional, gitignored).
param(
    [string]$ToolScript = '',   # tests: extra tool registrations dot-sourced after the bridge tools
    [switch]$NoTools,           # tests: register no bridge tools
    [string]$SettingsPath = "", # default: settings.json next to this script
    [switch]$ReportRun          # started by a report run of the TIA dashboard (TiaAgentStatus\reportrun.py): Bridge.ps1
)
$ErrorActionPreference = 'Stop'
foreach ($f in 'Guides.ps1', 'Mcp.ps1', 'Tia.ps1', 'Repo.ps1', 'Rules.ps1', 'Guards.ps1', 'Bridge.ps1', 'State.ps1',
               'Tools\Objects.ps1', 'Tools\Plc.ps1', 'Tools\Hmi.ps1', 'Tools\Library.ps1', 'Tools\LibraryChange.ps1',
               'Tools\Session.ps1', 'Tools\Probe.ps1', 'Tools\Report.ps1', 'Tools\Background.ps1', 'Tools\Safety.ps1',
               'Tools\FullExport.ps1') {
    . (Join-Path $PSScriptRoot $f)
}

if (-not $SettingsPath) { $SettingsPath = Join-Path $PSScriptRoot "settings.json" }
Initialize-BridgeContext (Get-BridgeSettings $SettingsPath)
$script:Bridge.reportRun = [bool]$ReportRun
Start-BridgeState $script:Bridge.settings.projectsRoot   # State.ps1: the state file for observers
$script:McpToolDispatch = { param($Name, $Handler, $Arguments) Invoke-BridgeTool $Name $Handler $Arguments }
$script:McpInstructions = Get-BridgeInstructions

if (-not $NoTools) {
    Register-SessionTools
    Register-ObjectTools
    Register-LibraryTools
    Register-LibraryChangeTools
    Register-ProbeTool
    Register-ReportTool
    Register-BackgroundTools
    Register-SafetyTool
    Register-FullExportTool
}
if ($ToolScript) { . $ToolScript }
Start-McpLoop
try { Stop-BackgroundOnExit } catch { Write-BridgeLog "Background session not closed: $($_.Exception.Message)" }
Stop-BridgeState
