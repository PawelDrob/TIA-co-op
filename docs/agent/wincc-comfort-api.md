---
type: Guide
title: "WinCC Comfort: the Openness API from PowerShell"
description: How the TIA Portal V20 Openness API loads in PowerShell 5.1 and where the HMI objects of a WinCC Comfort device are in it, as found by probes.
tags: [tia-portal, hmi, wincc-comfort, openness, powershell, agents]
generated: { by: claude-code/claude-opus-5-5, at: 2026-11-21T16:19:37-05:00 }
sources:
  - id: import
    resource: Openness imports into project B (2026-10-01 and later)
    title: project B Openness imports
  - id: probe
    resource: ../../TiaBridge/Tools/Probe.ps1
    title: Reflection on and calls to the installed V20 Openness API
---

# WinCC Comfort: the Openness API from PowerShell

Part of the [WinCC Comfort guide](wincc-comfort-openness.md): sections 2.1 and 2.2, the PowerShell side of what TiaBridge does. A section keeps its number in the file that holds it; the guide's section 0 holds the confidence tags.

### 2.1 Loading the API from PowerShell `[PROBE]`

- TIA V20 installs the API versions side by side:
  `Portal V20\PublicAPI\V17 ... \V20\Siemens.Engineering.dll`. Load the
  `V20` folder explicitly. A search for "V20" in the path matches every
  folder, because the install folder is `Portal V20` (picked V19 once).
- `Add-Type -Path Siemens.Engineering.dll` fails with "Unable to load one or
  more of the requested types" (it enumerates all types). Use
  `[Reflection.Assembly]::LoadFrom()`.
- Dependencies are resolved by a small C# `AssemblyResolve` handler compiled
  with `Add-Type -TypeDefinition` (only `Siemens.*` names, only from the API
  folder, re-entry guard). A PowerShell script block as resolver recursed into
  itself: `StackOverflowException` on `Attach()`.
- Generic `GetService<T>()`: PowerShell 5.1 has no generic call syntax; use
  `[IEngineeringServiceProvider].GetMethod('GetService').MakeGenericMethod([T]).Invoke($obj, $null)`.
- Calling Openness methods through `MethodInfo.Invoke` with an argument array
  built in PowerShell fails ("PSObject cannot be converted to ExportOptions").
  Call the methods directly: `$v.Export([IO.FileInfo]::new($f), [Siemens.Engineering.ExportOptions]::None)`.
- `Attach()` raises the Openness access dialog in TIA; the Windows user must
  be in the local group "Siemens TIA Openness".

### 2.2 Navigation in the API `[PROBE]` `[IMPORT]`

```
TiaPortal.GetProcesses()[i].Attach().Projects[0]
Device (project.Devices, project.DeviceGroups recursively) -> DeviceItems (recursive)
  GetService<SoftwareContainer>().Software -> HmiTarget
HmiTarget.ScreenFolder.Screens / .Folders (Find, Create)       Screen.Export / Screens.Import
HmiTarget.ScreenTemplateFolder.ScreenTemplates / .Folders
HmiTarget.TextLists                                            TextList.Export / TextLists.Import
HmiTarget.TagFolder.TagTables
Project.ProjectLibrary.TypeFolder.Types / .Folders             LibraryType.Versions
```

Export options: `None` = minimal (only non-default attributes),
`WithDefaults | WithReadOnly` = everything (the only option used for screens,
templates and pop-ups, 2.3). Export refuses to overwrite a file;
delete it first. Imports use `ImportOptions.Override`.
