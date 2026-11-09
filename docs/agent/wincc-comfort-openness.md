---
type: Guide
title: WinCC Comfort screen generation with TIA Portal Openness
description: How to generate WinCC Comfort screens, pop-ups, tag tables and text lists as SimaticML and import them through TIA Portal Openness V20.
tags: [tia-portal, hmi, wincc-comfort, openness, simatic-ml, agents]
generated: { by: claude-code/claude-opus-5-5, at: 2026-11-07T17:20:08-05:00 }
sources:
  - id: export
    resource: V20 Update 7 Openness exports of project B (2026-10-01), minimal and full
    title: project B Openness exports
  - id: import
    resource: Openness imports into project B (2026-10-01 and later)
    title: project B Openness imports
  - id: probe
    resource: ../../TiaBridge/Tools/Probe.ps1
    title: Reflection on and calls to the installed V20 Openness API
  - id: user
    resource: observations in the TIA editor
    title: Observed by the user in the TIA editor
---

# WinCC Comfort screen generation with TIA Portal Openness

Target: TIA Portal V20 Update 7, WinCC Comfort / Advanced ("WinCC (TIA Portal)",
not WinCC Unified), Comfort Panel TP1200 (1280 x 800). Companion to
[s7dcl-format.md](s7dcl-format.md): that one generates PLC blocks as SIMATIC SD files,
this one generates HMI screens as SimaticML XML through Openness.

## 0. Source basis and confidence tags

| Tag | Meaning |
|---|---|
| `[EXPORT]` | Seen in a V20 Update 7 Openness export of project B (2026-10-01), minimal and full exports. Outranks everything else, for the exact shape seen. |
| `[IMPORT]` | Imported successfully through Openness into project B (2026-10-01). |
| `[PROBE]` | Found by reflection on the installed V20 Openness API or by calling it (`FaceplateProbe.ps1`, 2026-10-01). |
| `[USER]` | Observed by the user in the TIA editor. |
| `[INFERRED]` | Follows from the above, not verified by a round trip. Verify before relying on it. |
| `[GAP]` | Not known. Do not guess: make a test object in TIA, export it, copy the shape. |

**Hard rule: never write an XML shape that is not in an export. Make the
object once in TIA, export it, and use that export as the template.** The
[screen object catalogue](wincc-screen-objects.md) is such an export of every
toolbox object (its fixture) with the values whose spelling is confirmed; the
validator holds generated screens to it.

---

## 1. What can and cannot be generated

| Object | Export | Import | Notes |
|---|---|---|---|
| Screens (incl. groups, animations, events) | yes `[EXPORT]` | yes `[IMPORT]` | `ImportOptions.Override` replaces a screen of the same name |
| Screen templates | yes `[EXPORT]` | yes `[IMPORT]` | `ScreenTemplateFolder.ScreenTemplates.Import`; the bridge refuses an existing template unless override is set; never over a template that holds an alarm view |
| Text lists (device) | yes `[EXPORT]` | yes `[IMPORT]` | |
| Faceplate instances on a screen | yes `[EXPORT]` | yes `[IMPORT]` | type referenced by name and version (`FaceplateTypeName` `_Library@$@<folder>@$@Faceplate@$@<name> V x.y.z`); copied (2026-10-01) and generated from scratch (49 tab screens, 2026-10-02); the version must be in the project library, else TIA crashes (7.2) |
| HMI tag tables | yes `[EXPORT]` | yes `[IMPORT]` | `TagFolder.TagTables.Import`; a tag of a PLC data type needs no member list; names with `+`, `-` import; TIA stores the controller tag unquoted. Links use `"Tag".member.member` |
| PLC data types, blocks | yes `[EXPORT]` | - | `PlcSoftware.TypeGroup` / `BlockGroup` (recursive), `Export` with all attributes; run 3 (2026-10-01). Know-how protected and inconsistent blocks fail |
| Pop-up screens | yes `[EXPORT]` | yes `[IMPORT]` (new 2026-10-01, Override over existing 2026-10-02) | `HmiTarget.ScreenPopupFolder.ScreenPopups` / `.Folders`; root `Hmi.Screen.ScreenPopup` (BackColor, Height, Name, Width; Layers only). Slide-in screens: `ScreenSlideinFolder` |
| Basic objects and elements (all 19), user view | yes `[EXPORT]` | not tried for the ellipse, polyline, graphic I/O field, date/time field, switch, symbol library, slider, gauge and user view | test screens with every toolbox object dropped, exported full on 2026-10-31: the fixture of the [screen object catalogue](wincc-screen-objects.md) |
| Global screen | yes `[PROBE]` (2.3, `hmi\global\`) | `[GAP]` | |
| **Faceplate types (contents)** | **no** `[PROBE]` | **no** `[PROBE]` | see section 6 |
| The 14 other controls: alarm view, trend view, HTML browser, watch table, Sm@rtClient view, recipe view, f(x) trend view, system diagnostics view, PLC code view, GRAPH overview, ProDiag overview, criteria analysis view, camera view, PDF view | **silently omitted** `[EXPORT]` | - | see 7.1; build them by hand in TIA |
| Graphics (pictures) | a screen links them by name (`Picture`, `PictureOff`) `[EXPORT]`; the project graphic exports as `project\graphics\<name>.xml` with its image in `<name> files\` (TiaBridge keeps the folder since 2026-10-31) `[PROBE]` | link only `[IMPORT]` (graphic views of the compass and logo, 2026-10-01) | the graphic must exist in the project |

---

## 2. Toolchain

Since 2026-10-06 export, import, compile and probe go through the TiaBridge MCP
server (`TiaBridge\`): the agent calls its
tools, the files sit in the project repo (`hmi\screens\`, `hmi\popups\`,
`hmi\templates\`, `hmi\tags\`, `hmi\textlists\`, generators in `gen\`), and every
call writes its full result to `logs\` there. The PowerShell scripts that did this
before (`Export.cmd`/`HmiExport.ps1`, `Import.cmd`/`ImportStaging.ps1`,
`Probe.cmd`/`FaceplateProbe.ps1`) were retired when the bridge took their place;
their findings stay in this guide, and the git history of this repo keeps them.

| Tool / file | Does |
|---|---|
| `export` / `import` / `delete` kinds `hmi_screen`, `hmi_popup`, `hmi_template`, `hmi_tag_table`, `hmi_textlist` | SimaticML out of and into TIA; exports go to `hmi\screens\`, `hmi\popups\`, ...; screens, pop-ups and templates are always exported full (section 2.3), tag tables and text lists minimal unless `options.full`; screens, pop-ups, templates and tag tables are imported only from `hmi\[<device>\]generated\<kind>\` (tag tables: `generated\tags\`) and only after the HMI validator passed (section 3); a new one goes to the folder its path there mirrors (`hmi\[<device>\]generated\screens\zzStaging\x.xml` -> `zzStaging`), an existing one is replaced where it is; faceplate guard before every screen import |
| `compile(hmi)` | the full compiler message tree |
| `list` / `export` kind `faceplate_type`, `probe` | faceplate type versions and metadata; reflection on any object |
| `TiaHmiGenerator\hmixml.py` | Python: builds screens and text lists from object dicts, using exported objects as templates, and tag tables from tag dicts, with `Length` and `HmiDataType` from the data type; writes only through a run (`begin` / `plan` / `add` / `finish`) into `hmi\[<device>\]generated\` |
| `TiaHmiGenerator\catalogue\` | the screen object catalogue: every toolbox object with every option, its TIA display name, default and allowed values (`catalogue.json`, read with `hmipreview.catalogue`); [WinCC Comfort screen objects](wincc-screen-objects.md). Its fixture is a full export of every object that goes through Openness, for `hmixml.load_shapes` |
| `TiaHmiGenerator\hmipreview\` | Python: `<py> -m hmipreview validate`, `serve`, `diff`, `png`, `panel`, `changes` (validator, preview server, change list, PNGs through headless Edge or Chrome, declared panel, the HMI changes between two revisions). Replaces `render.py` (retired 2026-10-06) |
| `TiaChangeReports\` | the change report: PLC blocks, PLC tag tables and HMI objects on one page, screens drawn before \| after; `--after-set generated` against the generated documents |

A project generator lives in the project repo's `gen\` and imports `hmixml.py`
from the tool repo (`<py> -I gen\x.py <tool repo>\TiaHmiGenerator <project repo>`, where `<py>` is
`<tool repo>\.venv\Scripts\python.exe -X utf8`, set up once with `uv sync` in the tool repo; never `python` from `PATH`).
It runs `hmixml.begin(repo)`, `plan` / `add` per item and `finish()`; the screen
size comes from the declared panel (`hmi\panel.json`). The preview commands run
from `TiaHmiGenerator\` with the project repo as argument (section 3).

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

### 2.3 Full exports only

Decided 2026-10-06: screens, templates and pop-ups are exported with
`WithDefaults | WithReadOnly` only; TiaBridge writes nothing else into
`hmi\screens\`, `hmi\templates\`, `hmi\popups\` and accepts `options.full`
without effect for them. A full export of a screen, renamed and imported
through TiaBridge, imported cleanly with its read-only attributes, compiled
with 0 errors and exported back byte-identical apart from the `Created` time
`[IMPORT]` (project B 2026-10-06); full files are about 19 % larger. The export
records its options in `DocumentInfo/ExportSetting` (`WithDefaults,
WithReadOnly` or `None`) `[EXPORT]`. A minimal export leaves defaults out, so
whoever reads it has to know TIA's defaults; the HMI preview no longer
guesses them: it draws what a document carries and reports a generated object
that lacks an attribute every full export of its type has
(`document.incomplete`), and a screen export that is not full
(`document.not-full`). Tag tables and text lists stay minimal by default: the
import of their full export is untested.

A project with several HMI devices (decided 2026-10-30):
each device's exports go to `hmi\<device>\screens\`, `hmi\<device>\tags\`, ...
(`export` with `device`, and `full_export`); a one-device repo keeps
`hmi\screens\`. The HMI preview, the generator and the import guard work on
one device at a time (`--device`, `hmixml.begin(device=...)`, else
`tiabridge.json` `hmiDevice`, else the only device folder): its exports, and
its generated documents in `hmi\[<device>\]generated\`. Slide-ins and the global elements and screen
overview export full too (`hmi\slideins\`, `hmi\global\`) `[PROBE]`. A slide-in has no name in Openness, only its panel
edge (`SlideinType`), so its file and its name in `list` are that edge: `hmi\slideins\Right.xml`. All four came out of one
export, `Top`, `Bottom`, `Left`, `Right`, each with its own edge in the file `[PROBE]`.

---

## 3. Workflow

1. **Reference export.** Build one of each object you need in TIA (a test
   screen), with the real styles, and export it (full, 2.3). These objects
   become the templates (`hmixml.load_templates`: every item whose
   `ObjectName` starts with `S-`); roots, layers, groups and graphic views are
   copied from the first exported object of their type (`hmixml.blank`,
   `load_shapes` for a template or pop-up export).
2. **Generate.** Describe the screen as object dicts (position, size, style,
   text, format, text list, animation, event); `hmixml.screen()` copies the
   template object and sets the attributes. A generator in the project repo's
   `gen\` runs `hmixml.begin(repo)`, `add()` per document and `finish()`:
   the documents go to `hmi\[<device>\]generated\<kind>\`, sized to the declared panel
   (`hmi\panel.json`, checked against the HMI device `connect` records). Anything
   the project does not have yet (a style preset, text list, template,
   picture, faceplate type version, screen) is declared with
   `hmixml.plan(kind, name, note)` next to the object that uses it.
3. **Check offline.** `finish()` runs the validator and prints its findings
   (screen, object, rule, reason); on an error it rolls the run back. Then
   look at the screens in the HMI preview:
   `<py> -m hmipreview serve <repo> --detach` from `TiaHmiGenerator\` prints
   the URL for the user, and the TIA dashboard links it while it runs (it
   draws screens, pop-ups, templates, and a text list as a table of its
   entries; no tag table);
   `<py> -m hmipreview png <repo> <name> <out.png>` draws a screen for the
   agent, the same way the browser does (`--kind popup|template`: a pop-up or
   template); `<py> -m hmipreview diff <repo> <name>` (`--kind` as for `png`,
   and `textlist`) lists the changes against the last commit (`--against export`: against TIA) for the run summary;
   `<py> TiaChangeReports --git <repo> HEAD --after-set generated --only hmi -o <page>`
   draws every changed screen before | after and lists every changed tag and
   list entry, TIA against generated, for the user. Hand-built
   objects (7.1) are listed once in `hmi\handbuilt.json` (screen, kind,
   rectangle). Each finding names its rule.
4. **Import** with TiaBridge `import`, after the user's yes to their preview
   (the stop: skill `tia-change`, `hmi.md`): tag tables, text lists and templates
   first, then pop-ups and screens. Screens, pop-ups and templates come from
   `hmi\[<device>\]generated\<kind>\`, tag tables from `generated\tags\`.
   An existing screen or pop-up is replaced where it is, an existing template only with `override: true`, an existing
   tag table not at all (7.2). A new screen, pop-up or template goes to the
   folder its path there mirrors, a screen into `zzStaging` only when the user
   asks for it or for a faceplate's staging screen (section 6). The bridge refuses a document with a validator
   error, an open planned item, or, for a screen, pop-up or template, a TIA export newer than the generated
   document (`override: true` to overwrite the TIA edits). A screen imported
   only to try something goes with TiaBridge `delete` (a write: compile
   afterwards), then a `zzStaging` left empty with TiaBridge `delete_folder`;
   it refuses a folder that holds anything.
5. **Never override a screen that holds objects the export cannot carry**
   (7.1). Generate new screens, or rebuild those objects by hand.
6. Faceplates: see section 6.

---

## 4. Document format `[EXPORT]`

```xml
<?xml version="1.0" encoding="utf-8"?>          (file in UTF-8 with BOM, CRLF)
<Document>
  <Engineering version="V20" />
  <DocumentInfo> ... copied from an export ... </DocumentInfo>
  <Hmi.Screen.Screen ID="0">
    <AttributeList> BackColor, Height, Name, Number, Width </AttributeList>
    <LinkList> <Template TargetID="@OpenLink"><Name>02_Template_Frame</Name></Template> </LinkList>
    <ObjectList>
      <Hmi.Event.Event CompositionName="Events"> (screen events, e.g. GenerateScreen)
      <MultilingualText CompositionName="HelpText"> ...
      <Hmi.Screen.ScreenLayer CompositionName="Layers">
        <AttributeList> Index, Name, VisibleES </AttributeList>
        <ObjectList> screen items, CompositionName="ScreenItems" </ObjectList>
```

Rules seen in every export:

- `ID` attributes: hexadecimal without prefix (`0 ... 9 A B ... 1A`), unique
  in the document, counted in document order. Renumber after building.
- `AttributeList` children in alphabetical order; `ObjectList` children
  ordered by `CompositionName` (`Animations`, `Events`, `Font`, `HelpText`,
  `Interface`, `Properties`, `TextOff`, `TextOn`). The generator keeps both
  orders; import accepted them `[IMPORT]` (other orders not tested).
- `LinkList` sits between `AttributeList` and `ObjectList`. A link to a
  project object: `<Kind TargetID="@OpenLink"><Name>name</Name></Kind>`
  (`Tag`, `TextList`, `Template`, `Picture`, `Authorization`, `StyleItem`,
  `Value`). `TargetID="#0"` points to the object with ID 0 in the same
  document (the screen itself, e.g. `ActivateScreen` to the own screen).
- Colours: `r, g, b` with spaces.
- Exports are full (2.3): every attribute is present, defaults and
  read-only ones included. Minimal documents (export option `None`) leave
  out defaults and also import `[IMPORT]`, but are no longer written or used
  as references.
- Screen `Number` must be unique in the device `[INFERRED]`. Generated
  staging screens use 9101 and up.
- The screen items of a layer or group stand in a list. The change report and `hmipreview diff` tell an object's
  position in that list, counted from 1, as `layerOrder`, old and new. On one layer of a screen TIA draws the first at
  the back and the last in front, and the editor's layer list shows them in the same order `[USER]`; a group, a template
  and a pop-up have not been looked at. No row does not mean the same position: most objects whose position differs were
  only shifted by another, so the row goes only where objects changed sides, on those with the most such pairs, ties all
  of them. Two that swap both have one, so one step past a neighbour reads as a swap; one that alone passed two or more
  others has the only one. An object whose number stays the same has none, so with objects new or gone in the same list
  the rows can stand on those it passed. The HMI preview and the report draw the list first to last, as TIA does on a
  layer of a screen. An import of a generated document that differs from a newer
  export only in this order is refused, as any other difference (`staleness.export-newer`).
- An object that stands directly in another group, or leaves or enters one, has the row `Group` in the change report
  and `hmipreview diff`, old and new, empty for no group; a group that holds other objects has the row `Members`, their
  names in order, a new or deleted one too on the report's page, as `hmipreview diff` and the preview's list give such
  a group one line. A group has no geometry, so its outline on the drawing is the box around its members. An import of
  a generated document that differs from a newer export only in this is refused too.

### 4.1 Texts and fonts

- Every text is a `MultilingualText` with one `MultilingualTextItem` per
  project language, an empty text too (`<Text />`) `[EXPORT]`. The generator
  writes the languages the project's exports carry (section 5, Languages).
- Rich text: `<Text><body><p>line 1<br />line 2</p></body></Text>`, on one
  line. Pretty-printing inside `<Text>` adds whitespace to the text: the
  generator indents everything except `Text` elements.
- An empty text: `<Text />`.
- Fonts: `MultiLingualFont` (`CompositionName="Font"`) with one `FontItem`
  per culture: `FontFamily`, `FontSize`, `FontStyle` (`Regular`, `Bold`).
- Text field composition `Text`; button `TextOff` and `TextOn`; symbolic I/O
  field `TextOff`/`TextOn` present too (`0`/`1`).

### 4.2 Screen items seen

| Element | Key attributes / children |
|---|---|
| `Hmi.Screen.Rectangle` | `BackColor`, `BorderColor`, `BorderWidth`, `RoundCornerHeight/Width`, `UseDesignColorSchema` |
| `Hmi.Screen.TextField` | `ForeColor`, `BackFillStyle` (`Transparent`), `HorizontalAlignment` (`Left` default, `Right`, `Center`), `VerticalAlignment` (`Top` default, `Middle`), `FitToLargest`, Font, Text |
| `Hmi.Screen.IOField` | `Mode` (`Input`, `Output`), `FormatPattern` (`s99.99`, `9999`), `FieldLength` = characters without the sign (`s99.99` -> 5, `9.99` -> 4), margins; `Properties/Hmi.Screen.Property Name=ProcessValue` -> `Hmi.Dynamic.TagConnectionDynamic` (`Indirect=false`) with the `Tag` link |
| `Hmi.Screen.SymbolicIOField` | `Mode` (`InOutput` is the default, `Output`), `TextList` link, `ProcessValue` as above |
| `Hmi.Screen.Button` | `Mode` (`Text`, `Graphic`, `Invisible`), `TextOff`, `TextOn`, Events |
| `Hmi.Screen.Polyline` | `Color`, `LineWidth`, `Points` = `﻿<Item>x, y</Item>...` as escaped text, **absolute** screen coordinates, starting with U+FEFF |
| `Hmi.Screen.Polygon`, `Circle`, `Line` | seen, not used by the generator yet |
| `Hmi.Screen.GraphicView` | `Picture` link by name |
| `Hmi.Screen.Group` | only `ObjectName`; members in its `ObjectList` as `ScreenItems`; no geometry |
| `Hmi.Screen.FaceplateInstance` | `FaceplateTypeName` = `_Library@$@<folder>@$@...@$@<type> V <x.y.z>`, `Resizing`; `Interface`: `Hmi.Screen.InterfacePropertySimple Name=<prop>` with a `TagConnectionDynamic` (tag) or a `Value` link (e.g. `Authorization` -> `Service`), `Hmi.Screen.InterfacePropertyText` with a `Text` |

Tag names: plain HMI tags by name (`G05HmiComputeTableHeight.status.angle`),
array elements quoted (`"HMIunits_fg[5]".mode`).

A decimal point in `FormatPattern`: the HMI compile refused an output I/O field with `DataFormat` Decimal, `99.99`,
`FieldLength` 5 and `ShiftDecimalPoint` 0 on an internal `Int` tag, "The format pattern of I/O field 'zzIO' is invalid.",
and compiled it with `9999` and `FieldLength` 4 (e2e run, 2026-11-04). `[GAP]` Why: no other pattern, tag type or
`ShiftDecimalPoint` was tried. The `s99.99` and `9.99` in the table show how `FieldLength` counts, not that they compile
on any tag. The validator warns on such a pattern when the tag tables do not name the tag `Real` or `LReal`
(`iofield.format-pattern`) and refuses nothing: the compile decides. Silence on `Real` and `LReal` is a choice against
noise, not a result: they were not tried either.

### 4.3 Animations

```xml
<Hmi.Dynamic.RangeAppearanceAnimation CompositionName="Animations">
  <AttributeList><Name>RangeAppearanceAnimation</Name></AttributeList>
  <ObjectList>
    <Hmi.Dynamic.TagElementTrigger CompositionName="RangeTag"> Tag link </...>
    <Hmi.Dynamic.Range CompositionName="RangeValues">
      BackColor, FlashingType (No), ForeColor, LowerLimit, UpperLimit
```

`ForeColor` of a rectangle range is its border colour.

```xml
<Hmi.Dynamic.VisibilityAnimation CompositionName="Animations">
  Name=VisibilityAnimation, RangeStart, RangeEnd, Visible (true)
  <Hmi.Dynamic.TagElementTrigger CompositionName="VisibilityTag"> Tag link </...>
```

A trigger without a tag is a self-closing `TagElementTrigger`; it imports
`[IMPORT]`.

### 4.4 Events and system functions

```xml
<Hmi.Event.Event CompositionName="Events"> Name = Press | Release | Click | GenerateScreen
  <Hmi.Event.FunctionListEventHandler CompositionName="EventHandler">
    <Hmi.Event.FunctionListEntry CompositionName="FunctionListEntries"> Name, Type=SystemFunction
      <Hmi.Event.FunctionListEntryParameter CompositionName="Parameters"> Name, Value or link
```

| Function | Parameters (name = value) |
|---|---|
| `SetBitWhileKeyPressed` | `Tag` (link), `Bit` = `<Value Type="System.Int32">0</Value>` |
| `ActivateScreen` | `Screen name` (`Value` link to the screen), `Object number` = 0 |
| `ActivatePreviousScreen` | - |
| `SetTag` | `Tag` (link), `Value` |
| `ShowPopupScreen` | `Name of the screen`, `X coordinate`, `Y coordinate`, `Display mode`, `Animation`, `Animation speed` |
| `Logoff`, `StopRuntime` (`Mode`), `GetUserName` (`Tag`), `ClearAlarmBuffer` (`Alarm class number`) | |

A function parameter without a tag: leave out its `LinkList` (imported
`[IMPORT]`).

### 4.5 Text lists `[EXPORT]` `[IMPORT]`

```xml
<Hmi.TextGraphicList.TextList ID="0">
  <AttributeList><Name>tlName</Name></AttributeList>
  <ObjectList>
    <MultilingualText CompositionName="Comment"> ...
    <Hmi.TextGraphicList.TextListEntry CompositionName="Entries">
      <AttributeList><From>1</From><To>1</To></AttributeList>
      <ObjectList><MultilingualText CompositionName="Text"> ...
```

Only value/range lists are seen; a bit list (`Bit` type) is `[GAP]`. A Bool
tag works with a range list 0/1.

---

## 5. The generator (`hmixml.py`)

- `load_templates(export.xml)`: template objects from a reference screen;
  the project's style presets (`S-Panel`, `S-Input`, ...) as built in TIA.
- `set_colours({key: (r, g, b)})`, `screen(name, number, objects)`,
  `textlist(name, [(value, text)])`; documents reach the disk only through a
  run (below), screens and templates take their size from it.
- `tag_table(name, [{name, data_type, cycle, plc_tag, connection, hmi_type}])`
  in a run: `Length` and `HmiDataType` from the data type (section 7.2); an internal
  tag goes without `cycle`, as its export has no `AcquisitionCycle`;
  `add('tagtable', doc)` writes `hmi\[<device>\]generated\tags\`.
- Object dict: `name, type, style, x, y, w, h, group, m` with
  `m.text, m.fmt, m.tl, m.mode, m.anim, m.vis, m.event, m.grp` (see the module
  docstring). Groups come from `group.key` or `m.grp`.
- It copies a template, removes the template's animations, events and
  properties, sets geometry, name and texts, adds animations and events
  without tags, sorts attributes and compositions, renumbers IDs.
- Tags are left open in `item()` (staging screens).
- **Languages** come from the project, never from the generator. `begin` reads the
  cultures of the exported screens, templates, pop-ups and text lists of every HMI
  device; only when those carry none, of the other exports under `hmi\` (tag tables:
  generators wrote them by hand into that folder before they went to `generated\tags\`,
  and such a file may still be there, so it does not add a language to the others). `hmi\references` and generated documents never count. With none, or outside a run, those
  of the exports loaded (`load_templates`, `load_shapes`), which may be another
  project's: the validator warns of that (`languages.no-export`). No language
  known: making a text or font raises `ValueError`; export a screen first. An object
  with neither needs no language.
  `hmixml.generated_cultures()` returns them. A language added in TIA counts once an
  exported screen, template, pop-up or text list carries it, and one removed counts until
  none of them does; exporting a tag table again is not enough. After changing the
  project's languages, export those again. Every text and font that
  `template`, `shape_item` and `ml_text` make, also inside a copied object, gets
  exactly these, in the order first seen: an item of another language goes, a
  missing one is a copy of the first item holding a text. `shape_item(...,
  cultures=)` overrides them, and a text built by hand keeps what it has: the
  validator refuses a generated text that lacks a language the exports carry
  (`languages.missing`, also on a document generated before that language came) and
  one that carries a language no export carries (`languages.unknown`: as TIA refuses it,
  section 7). A language added in TIA and in no export yet is refused until a screen is exported again. `hx.CULTURES = [...]`, which
  earlier generators set, has no effect and gives no error now: the variable is gone,
  and the project's languages count.
- **A generated text in a language it has no text for:** a text the generator sets
  (`m.text`, `set_text`, a text list entry) is given once and written in every
  language, the same words, so that language shows those words. There is no
  per-language text in a generator. A text it does not set stays as copied: a
  missing language gets a copy of the first item holding a text, but an item empty
  in the export stays empty, so a partly translated preset or `shape_item` shows an
  empty field in that language. `HelpText` and `Comment` of a new document are empty
  in every language. Translate in TIA afterwards; generating and importing the screen
  again with Override replaces those translations with the one text.
- **Preset names** are the project's. The generator knows the convention that an
  exported object named `S-...` is a preset, and no name of a project. Anything
  else a project calls its presets goes in `load_templates(path, aliases={...})`:
  `{'S-Lit': 'S-Button'}` a second name, `{'S-Title': 'txtTitleLarge'}` an
  object not named `S-...`, `{'S-Note': ('S-Title', {'VerticalAlignment':
  'Top'})}` a copy with attributes set. A symbolic I/O field keeps the `Mode` of its
  preset; `m.mode` sets another. Until 2026-11-04 a preset named `S-SymOut` forced
  `Output` and any other `InOutput`: a generator that relied on that has to set
  `m.mode`, and gets no error if it does not.
- Since 2026-10-01 (redesign), shapes taken from the project B exports: `tag_link`,
  `process_value` (I/O field, symbolic I/O field: `Hmi.Screen.Property`
  `ProcessValue` with `TagConnectionDynamic`), `appear_anim_tag` (several
  ranges), `vis_anim_tag`, `func` / `event` (system functions with link,
  Int32 or Double parameters: ActivateScreen, ActivatePreviousScreen,
  SetTag, SetBitWhileKeyPressed, ShowPopupScreen as on template 02),
  `graphic_view` (`Picture` link; `AutoSizing` default `StretchPicture`),
  `screen_doc` (screen or `Hmi.Screen.ScreenTemplate` from ready elements,
  with template link and screen events). A trigger or function parameter
  without a tag stays open (imported `[IMPORT]` for triggers).
- Imported `[IMPORT]` (project B 2026-10-01 / 2026-10-02): screen template documents,
  `DataFormat` `String` on an output I/O field (user name), the
  `Authorization` link on a generated button and as a faceplate interface
  Value, faceplate instances copied from an export or generated, Line,
  Circle, range appearance animations on Rectangle / Circle / transparent
  text field, ClearAlarmBuffer, ShowLogonDialog. Not tried: function
  parameters left open.
- Run API since 2026-10-06: `begin(repo)`, `plan(kind, name, note)`,
  `add(kind, doc, folder)`, `finish()` (writes `hmi\generated\`,
  `planned.json`, `generated.json`; it first validates the run in memory,
  as an overlay on the repo, and writes nothing when that finds errors); the
  direct `write(doc, path)` and the fixed 1280 x 800 outside a run are gone. The
  HMI preview draws the generated documents in the browser and replaces
  `render.py`.
- Device resolution: from the order number in the `TypeIdentifier` (table in
  `TiaHmiGenerator\hmipreview\resolution.py`). `[PROBE]` (project B 2026-10-06): the HMI device
  `+HM01-PF01` reads `OrderNumber:6AV2 124-0MC01-0AX0/17.0.0.0` (TP1200
  Comfort, firmware 17.0.0.0, landscape, no `//` part). The `HmiTarget`
  (software) has no `TypeIdentifier` (only `Author` and `Name`); it comes
  from the hardware device or its device items. A TP1200 screen exports with
  1280 x 800 (section 4), so the TP1200 row is confirmed; the other panels
  are from the operating instructions, and the `//Portrait` suffix is
  `[INFERRED]` until a portrait panel is seen.

---

## 6. Faceplates `[PROBE]` `[USER]`

- `FaceplateLibraryTypeVersion.Export(file, options)` writes only the version
  metadata (author, version number, comment), not the contents.
- `ExportAsDocuments(dir, name, format, options)`: format `''` -> "Cannot
  export a version without specifying an export format or with an invalid
  export format"; `SimaticML`, `Xml`, `Documents`, `s7dcl` -> "The type
  version could not be exported". `GetSupportedExportFormats()` returns an
  empty list.
- The type folder has `CreateFromDocuments(...)`; without an export there is
  nothing to feed it.
- Route used instead: generate a **staging screen** with the faceplate's
  objects at their final positions (styles, texts, formats, text lists,
  animations, events, groups), import it into `zzStaging`, select the objects, create the
  faceplate in TIA, then connect the tags to the interface. Creating the
  faceplate clears the tag connections `[USER]`, so the staging screens carry
  none.
- A faceplate's look only shows on an instance; check it on a screen.
- Faceplate instances on generated screens: copy the exported shape (4.2)
  with the type name and version of the released type.
- **Putting a faceplate type in work through Openness crashes TIA**:
  `FaceplateLibraryTypeVersion.Edit(LibraryTypeInstanceInfo)` (through an
  instance on a screen) ended TIA V20 Update 7 with
  `NonRecoverableException` "Unexpected exception - no exception message
  available" `[PROBE]` (project B 2026-10-06 16:04). TiaBridge refuses it; the user
  edits and updates faceplate types in TIA.
- A faceplate type that contains a PLC data type (its interface) keeps its
  version when that data type gets a new one, and is then **not using the
  default version** of it: `Dependencies` of the faceplate version names the
  version it was built with (`faceplateStation20Operate` 0.0.2 ->
  `typeHmiBench30` 0.0.1 while 0.0.2 is the default) `[PROBE]`
  (project B 2026-10-06). `library_update_usages` does not put the faceplate in
  work; TiaBridge reports it (`library_review`, `list`), and it needs a new
  version made in TIA.

---

## 7. Pitfalls

### 7.1 Objects the export leaves out `[EXPORT]`

The alarm list screen exports with its text field and buttons only; the
alarm view is missing. The diagnostics screen exports with its title only.
A test screen with all 15 controls of the toolbox dropped (2026-10-31)
exported the user view only, with its attributes and fonts. Treat every
other control (the 14 named in section 1, and the alarm window and
indicator) as invisible to Openness. Importing a
regenerated version of such a screen with `Override` would remove it
`[INFERRED]`. Keep such controls on screens that are never regenerated, and
compare the object count of a screen in TIA with its export before touching
it.

### 7.1a How the screen editor draws a screen `[USER]`

Thirteen editor shots of projects A and C, zoom 100 %, 2026-11-03, measured against the exports. The HMI preview and the
change report draw the same, except where noted. The template's half strength and the invisible button's frame are for
Inspect mode, PNGs and the change report; the preview's Run mode looks as the panel: full strength, no frames.

- A template's objects under a screen: at half strength over the screen's `BackColor` (white on a 224 grey gives 240).
  In the template's own view: in full.
- The grid: black dots (`GridColor`) 8 px apart, above the template and below the screen's objects. Not drawn by the
  preview.
- I/O field text: a zero per position of the pattern, also for hexadecimal, and a leading `s` as the sign:
  `????` and `FFFF` give `0000`, `999` gives `000`, `s99999` gives `+00000`. Inferred, no shot: the same rule with a
  decimal point or separator (`99.9`, `s9,999`). Any other pattern (`1111`, `123`) is written as it is. The preview and
  the report put a dashed violet mark on both kinds, so neither reads as a value. Patterns with a decimal point occur
  in a project repo; patterns written as they are occur in none of the repos checked (2026-11-03).
- Clock (digital): the dial colour, no border, `12/31/2000 10:59 AM`. Date/time field: `12/31/2000 10:59:39 AM`.
- Bar going up: limit ranges at 5, 20, 80 and 95 % of the range (the values are not in the export), the value marker
  at the middle, ten major ticks with `CountSubDivisions` minor ticks between them.
- Button: `BackFillStyle` decides the fill. `Solid` draws `BackColor` also with `UseFirstGradient` true.
- Invisible button: a black 1 px frame with dots 8 px apart inside.
- A pop-up: the editor's area is 6 px smaller than `Width` and `Height`, 3 px off each edge. Not drawn by the preview, which
  shows the whole document.
- Alarm views and faceplate contents are drawn by the editor; the export holds neither. A faceplate is a box labelled
  with its type. An alarm view is a labelled box only when `hmi\handbuilt.json` lists it; otherwise the preview shows
  nothing there.
- Project graphics export as JPG, PNG, BMP, SVG or EMF. No browser draws EMF, so a graphic view with one stays a labelled
  box in the preview and the report; a change of its image is still listed.

### 7.2 Other

- Copying another project's design (project C from project B, 2026-10-19): the validator then knew only values seen in
  the project's own exports, so project B's colours, fonts and the Clock were "not seen" in project C. Since 2026-10-31
  the screen object catalogue is the limit (any toolbox type that goes through Openness, any attribute and confirmed
  value), and the project's exports only widen it. Put the other project's
  full exports under `hmi\references\<source>\`: they feed the vocabulary and the
  known styles and authorizations, not the links to screens or pictures. A text list needs no such reference: the
  validator knows its shape. TiaBridge `import` with `override` does not pass validator errors (it only overrides
  staleness).
- Colours are free values (project C 2026-10-22): the validator does not compare an attribute named `...Color`
  with the exports, so a colour animation can use a colour no export has (project C 002: the zone tint 190, 215, 240 in a
  range). The element and the attribute still come from an export. One object coloured by a tag
  (`RangeAppearanceAnimation`, one per object, one tag) replaces a base part with coloured copies over it; it shows a
  single signal, so a part whose state needs two sensors is coloured by the sensor of its default position.
- An HMI tag of a PLC `Word` needs the HMI data type `UInt` (project B exports: `Word` -> `UInt`,
  `Array [0..22] of Word` -> `Array [0..22] of UInt`). A tag table generated with `HmiDataType` `Word` failed the
  import with "The HMI data type Word was not found" and TIA closed with a `NonRecoverableException` `[IMPORT]`
  (project C 2026-10-19).
- **A tag's `Length` is the size of its data type.** A tag table built by hand, an `Int` tag cloned from a `Bool` tag
  with `Length` 1 left as it was, ended TIA on import with `NonRecoverableException` "Cannot set the length for the
  ... tag because data of the connected data type would have to be overwritten. The length of the data type is 2, the
  HMI tag has the value 1." `[IMPORT]` (another project, 2026-11-05). Exports carry `Bool` 1, `Int` 2, `Word` 2,
  `DInt` 4 `[EXPORT]`. Build tag tables with `hmixml.tag_table` (section 5), which sets `Length` and `HmiDataType`
  from the data type; TiaBridge imports a tag table only from `hmi\[<device>\]generated\tags\`, after the validator
  passed. The validator refuses a generated tag whose `Length` is not the size of its data type (`tagtable.length`)
  and an `HmiDataType` other than the one TIA takes for its data type (`tagtable.hmi-data-type`). An elementary data
  type has a fixed size and HMI data type, which no file under `hmi\tags\` changes: hand-built tables were imported
  from there before, and the one that ended TIA was such a file. Seen `[EXPORT]`: `Bool` `Bool`, `Int` `Int`, `Word`
  `UInt`, `DInt` `DInt`. The others take the S7 size and their own name, a bit string the unsigned integer of its
  size (`Byte` `USInt`, `DWord` `UDInt`) `[INFERRED]`; such an HMI data type is accepted only once an export pairs it
  with the data type. An array of an elementary type takes the array of its HMI data type, and its number of
  elements times its element's size `[INFERRED]`; an array of `Bool`, or one whose bounds are no numbers or run
  backwards, is refused, as nothing shows how TIA counts its `Length`: make such a tag in TIA. The other S7 types of a
  fixed size (`Char`, `WChar`, `S5Time`, `Date`, `Time`, `Time_Of_Day`, `LTime`, `LTime_Of_Day`, `Date_And_Time`,
  `LDT`, `DTL`) take their S7 size too `[INFERRED]`, which no file changes; their HMI data type is the one an export
  pairs them with at that size, as nothing shows which TIA takes, and an array of one is refused. A file that pairs
  an elementary or fixed-size type with an HMI data type at another `Length` teaches nothing. Refused as well
  (`tagtable.data-type`), and taught by no file: an elementary or fixed-size type written in another case (`int`) or
  by another name (`TOD`; TIA's own name `[INFERRED]`), an array written otherwise than `Array [0..1] of Int`
  (`Array[0..1]of Int`; `, ` between dimensions `[INFERRED]`, as the exports show one dimension only), a data type
  with white space around it (`Int `, a pretty-printed file), the name of such a type in quotes (`"Int"`,
  `Array [0..1] of "Int"`), and any data type that is neither of these nor a string or a PLC data type (`Timer`,
  `HW_IO`): make such a tag in TIA. The size and HMI data type of a string or a PLC data type, or an array of one,
  come from the tag table files under `hmi\tags\`, so such a tag needs an exported tag of its type first. Nothing
  tells a bridge export there from a file built by hand, so a hand-built file teaches them too, a wrong `Length`
  included, and the HMI data type of a fixed-size type.
- **Dependent properties can end TIA.** Some properties follow a main property. A screen whose dependent property
  does not follow can be refused with `NonRecoverableException` "The dependent property X of object Y has an invalid
  value. The recommended value is V because the main property M has the value W", and TIA ends its process within
  seconds `[IMPORT]` (2026-10-31, seen twice: an I/O field whose `FieldLength` did not follow `FormatPattern`, the
  user's TIA; a gauge with `BackFillStyle` `Solid` and another `DialFillStyle`, a background TIA). Nothing since the
  last save survives. `TiaHmiGenerator\catalogue\dependent.json` holds more than those two, for example a binary I/O
  field's `FormatPattern` `1111` and `FieldLength` 4, a circle's `Radius` = half the `Width`, rounded down, a line's
  or polyline's box from its points; each row's `source` says what TIA was seen to do with it, and some are `not
  observed`. The validator is stricter than what TIA was seen to refuse: it refuses a generated document that breaks
  a pair or relation (`dependent.value`) and warns on values taken as not allowed on Comfort panels
  (`dependent.device`; no verdict from TIA). A generator that changes a main property sets its dependents too.
  TiaBridge reports such an import as "TIA Portal ended" and refuses TIA calls until `connect` (or `background_close`).

- Template areas: in project B the templates use y 0-80 (header) and 720-800
  (navigation); generated content must stay inside y 80-720 unless it is
  meant to cover the template.
- Linked objects (text lists, templates, pictures, tags, authorizations) must
  exist before the screen import, or come in the same run before the screens.
  A screen with a link to a missing tag, screen or pop-up imports
  `[IMPORT]` (project B test A, 2026-10-01). A link to a screen that does not exist
  yet is kept by name and resolves once the screen is there: two new screens
  linking each other (`ActivateScreen` on a button `Click`) imported in one
  pass, A before B, exported with the link and compiled without a message
  `[IMPORT]` (project B 2026-10-06, TiaBridge). A second import pass, as in
  ImportStaging.ps1, is not needed for such links.
- `ActivateScreen` is not allowed in the screen event `GenerateScreen` (the
  compiler calls it `Loaded`): "The parameter of a function is not available for
  trigger ..., event 'Loaded'. The selected function is not allowed at this
  usage location." `[IMPORT]` (the import passes, the compile fails; project B
  2026-10-06).
- A circle carries `Radius` beside `Left`/`Top`/`Width`/`Height`
  (`Radius` = `Width` / 2) `[EXPORT]`; a generator that changes the size sets
  both (hmixml.py since 2026-10-06; before, a copied circle kept the template's
  radius).
- A Comfort screen offers only `Name` through Openness: no number, no template
  `[PROBE]` (project B 2026-10-06, `GetAttributeInfos`). Read them from the export.
- HMI tag names are unique per device across all tag tables: a copy of a table
  needs new tag names too. A renamed copy of `HmiGeneral` imported as a new table
  and exported equal to the original but for the names `[IMPORT]` (project B
  2026-10-06).
- Override on a tag table that exists deletes the table first; in project B
  (2026-10-01) that Delete failed and TIA Portal closed during the import
  `[IMPORT]`. TiaBridge `import` refuses `override` for tag tables: delete the
  table in TIA and import it as new, or import new tags into a new table.
  ImportStaging.ps1 skips existing tag tables and stops at the first failure.
- An HMI tag table with broken tags does not export: `ASiDiagnostic` in
  Master_Template_X failed with "Access to a disposed object of type
  'Dummy' is not possible. The object is no longer available." `[EXPORT]`
  (2026-10-04, also on a fresh connection), while the table `PLC` of the same
  HMI exported. Its tags were the ones the HMI compile rejected ("The address
  of the tag ... cannot be determined ... connection name: 'HMI_Connection_3'",
  "Invalid symbol assignment"); that these tags are the cause is `[INFERRED]`.
  Fix the tags (or the connection) in TIA before exporting such a table.
- Faceplate instances must not be inside a group: "It is not allowed to
  import grouped Faceplate instances" `[IMPORT]` (project B 2026-10-01). Keep them as
  single screen items.
- A tag table imported as new (not existing) with structured tags, element
  limits and partial element lists imports `[IMPORT]` (project B Stations,
  2026-10-01); TIA completes a partial element list to the full data type and
  keeps the limits as written (checked in the export).
- A screen that exists is replaced in its own folder: find it first and
  import into that folder (`$InPlace` in ImportStaging.ps1); importing into
  another folder with Override is `[GAP]`.
- An HMI tag on a PLC tag of a UDT needs "Accessible from HMI" on the DB
  member and on the elements in the UDT itself. Without the UDT setting the
  tag imports, but a screen link to an element (`"Safe_G05+DR02-SG00".q`)
  fails at compile: "tag does not exist" `[USER]` (project B 2026-10-01, 107 errors,
  typeStopSw / typeCheckback). Check both before generating links to them.
- Faceplate instance generated from scratch `[EXPORT]` (1205, 2026-10-01):
  `FaceplateTypeName` `_Library@$@<folder>@$@...@$@<type> V x.y.z`, `Resizing`
  None, `TabIndex` -1; each interface property an
  `Hmi.Screen.InterfacePropertySimple` (tag: `TagConnectionDynamic` with
  `Indirect` false and a Tag link; Authorization: a Value link). Generated
  instances import `[IMPORT]` (project B 2026-10-02, 49 tab screens).
- The `@$@` parts of `FaceplateTypeName` are the library folder path, with
  `_Library` as the project library root `[EXPORT]` (project B 2026-10-06): the
  instance on `5051 - G05 Unit operation` names
  `_Library@$@_Customer@$@Faceplate@$@Operate@$@faceplateStation20Operate V 0.0.3`,
  and the TiaBridge `export` kind `faceplate_type` gives that type's folder as
  `_Library/_Customer/Faceplate/Operate` with version 0.0.3. Project B keeps its
  40 faceplate types in `_Library/_Customer/Faceplate` (with `Operate`,
  `Settings`) and `_Library/HmiTypes/Faceplate` (with `Vehicles`).
- Digital clock `Hmi.Screen.Clock` (`Analog` false) `[EXPORT]` (1205, 2026-10-01).
- Pop-up restyle: rebuild each object from the preset template and carry
  over geometry, name, texts, links (without `StyleItem`), animations,
  events and the functional attributes (Mode, FormatPattern, FieldLength,
  DataFormat); minimal exports leave defaults out, so patching the old
  attribute list would keep old non-default styles. Import over an existing
  pop-up with Override works `[IMPORT]` (project B 2026-10-02).
- Screen names with the number in front (`5051 - G05 ...`) keep the
  project tree sorted; an import with a new name is a new screen, and a
  number already used by another screen is `[GAP]` (project B run 4 stops
  before the screens if the old names still exist). Nested user folders:
  `Folders.Find` / `Folders.Create` level by level (ImportStaging.ps1
  `$ScreenFolderRules`; created `5000 - Unit screens/G05` ... in the
  import of 2026-10-02 `[IMPORT]`).
- Button feedback: a flat button (no gradients) shows no pressed state. An
  animation on the PLC bit the button sets does not work when the PLC clears
  the bit after reading it (the library block `Lib:PanelExchange` does, project B 2026-10-02): the
  bit may be 1 for one PLC cycle only. Project B run 6 used an internal HMI tag
  instead (Press: SetTag number, Release: SetTag 0; appearance on the tag);
  the extra tag was not wanted, so run 7 animates the bit the button
  writes with SetBitWhileKeyPressed again: in the simulation the button
  blinks briefly when pressed `[USER]` (project B 2026-10-02, accepted).
- Logged-on user in a tag: GetUserName on screen load or on the Release of
  a logon button runs before the logon dialog is closed, and misses an
  automatic logoff. A scheduled task (HMI device -> Scheduled tasks) with
  the trigger "User change" and the function GetUserName(tag) updates it on
  every change. Works `[USER]` (project B 2026-10-02, simulation; set up by hand).
- Flashing: basic objects have a static attribute `Flashing` (`None`,
  `Standard` seen on Circle, Polygon and Text field of the old 090
  `[EXPORT]`; Line carries the attribute too). A range of an appearance
  animation has `FlashingType` (only `No` seen; other values `[GAP]`). To
  flash only in one state, project B puts a grey copy with `Flashing Standard`
  over the red part and shows it with a visibility animation (2026-10-02); how
  Comfort draws Standard flashing is `[INFERRED]` until seen.
- Alarm view and buttons: in the editor the grey band under the alarm rows
  belongs to the alarm view; buttons placed there were invisible in the
  simulation (project B 010 / 011, 2026-10-02). Keep other objects outside the alarm
  view's rectangle (view drawn on top `[INFERRED]`).
- Faceplate instance with a type version that is not in the project library
  `[IMPORT]` (project B 2026-10-02, `... faceplatePump20Operate V 0.0.2`, library
  has V 0.0.3): "Cannot create the 'Hmi.Screen.FaceplateInstance' object with
  Simatic ML ID ..." on the instance element, and TIA Portal crashed. The
  message does not name the cause: check name, library path and version of
  `FaceplateTypeName` against the project library before an import.
- Internal HMI tag `[EXPORT]` (userName, project B run 3): Hmi.Tag.Tag with
  AcquisitionCycle, DataType and HmiDataType links only (no Connection, no
  ControllerTag).
- An output I/O field with `DataFormat String` and no `FormatPattern` gets
  `FormatPattern` `?` x `FieldLength` from TIA `[IMPORT]`.
- Tag limits `[EXPORT]` (project B run 6): on the element of a structured tag,
  `<Hmi.Tag.TagStructureMember><AttributeList><LimitLower2 Type="Siemens.Engineering.Hmi.ConstValue">1000</LimitLower2>`
  `<LimitUpper2 Type="Siemens.Engineering.Hmi.ConstValue">300000</LimitUpper2><Name>runtimeMax</Name>`;
  Time elements in ms. A tag table export lists every element of every tag
  (with an empty comment), nested as in the data type.
- `ShowPopupScreen` `[EXPORT]`: parameters Name of the screen, X, Y, Display
  mode (-1 toggle, 0 off, 1 on), Animation (-1), Animation speed (1). A
  pop-up closing itself links its own root: `<Value TargetID="#0" />`.
- System functions seen in exports: ActivateScreen, ActivatePreviousScreen,
  SetTag, SetBitWhileKeyPressed, ShowPopupScreen, GetUserName, Logoff,
  StopRuntime (Mode), ClearAlarmBuffer. `ShowLogonDialog` (no parameters)
  imports `[IMPORT]` (User pop-up, 2026-10-01).
- Minimal exports left out default values, also those a generated document
  wrote explicitly (zzStyles_Redesign: `BackFillStyle Solid`, margins 0,
  `UseFirstGradient false` came back absent; project B 2026-10-06: `Height 30`
  on 117 text fields, 22 symbolic and 1 I/O field came back absent)
  `[EXPORT]`. That is why exports are full only since 2026-10-06 (2.3); a
  full export carries every one of them, and the full exports are the
  reference for what an object of a type must carry.
- Names: object names must be unique per screen; screen names unique per
  device.
- Fonts: exports carry font per language. On import `[PROBE]` (a text field on a screen, a project with
  en-US and de-DE, V20 Update 7; section 5, Languages, says when the generator can write either):
  - **A text or font that lacks a language of the project** goes in with no message, and the HMI compiles with
    0 errors, 0 warnings. The language it lacks then reads the word `Text`, and its font is Tahoma 16 Regular, whatever
    the other language's text and font (Tahoma 17 Bold here) are. So does the first language of the project, in a
    document with de-DE only. So the operator sees `Text`: the validator refuses it (`languages.missing`).
    A text and a font lacking it each go by themselves. What is written stays as written.
  - **A culture the project does not have** is refused, and nothing of the import goes in, with or without a second
    language: *Cannot import multilingual text with culture 'fr-FR' at line number 121 at line position 20: the
    specified culture does not exist within the current project.* The language does not appear in the project (`ActiveLanguages`
    is the same afterwards). With exports that hold the project's languages, the validator refuses it first (`languages.unknown`). A document with a language the
    project has, and no export carries yet, goes into TIA.
- Screen numbers can be part of the PLC interface: a panel can change
  screens from the PLC (`screenSelect`), and the project B group overviews carry
  1000 + FG `[INFERRED]`. Regenerate such screens with the same name and
  number, or change the PLC with them.
- Regenerating a screen with Override replaces all of it: copy the objects
  that stay (faceplate instances, groups) from its export into the generated
  document, and never do it for screens with objects of 7.1.

---

## 8. Pre-import checklist

The validator checks items 1, 3 (the languages), 4, 5, 8 and 9 (and the device resolution,
hand-built rectangles, grouped faceplates, staleness); TiaBridge `import`
refuses on its errors. The rest stays manual.

1. Every shape copied from a full export (no invented elements or attributes, none left out): validator,
   `vocabulary.*`, `document.incomplete`; exports that are not full: `document.not-full`.
2. IDs renumbered, unique; attributes and compositions in export order.
3. Rich text on one line; every language of the project present: validator, `languages.*`.
4. Screen numbers unique (staging 9101+); object names unique per screen: validator, `structure.*`.
5. Linked text lists / templates / pictures / authorizations / faceplate versions exist or come first; no open
   planned item: validator, `links.*`. Faceplate versions are checked against the exported project library
   (`library\faceplates`, TiaBridge `export` kind `faceplate_type`): export it again before a run that uses a new
   version; without it every faceplate link is unknown.
6. Looked at in the HMI preview (a tag table or text list in the change report) and compared with the design; findings and warnings
   read; the user's yes to the preview (skill `tia-change`, `hmi.md`, step 3).
7. New screens in the folder their generated path names, `zzStaging` only when the user asked for it or for a
   faceplate's staging screen.
8. No `Override` of a screen with controls the export cannot carry (7.1): validator, `handbuilt.*`, once the
   controls are listed in `hmi\handbuilt.json`.
9. Dependent properties follow their main property (7.2; a refused one ends TIA): validator, `dependent.*`.

## 9. History

- 2026-10-01: first export / import round trip (project B): 11 staging screens
  for the configuration and operation faceplates and 8 text lists generated;
  text lists and the first staging screen imported without errors, then all
  11 staging screens in one run (`import_log.txt` 13:19, no errors).
  Audit of the whole HMI from the exports (`B\HmiProjectAudit_2026-10-01.md`);
  `HmiExport.ps1` extended for PLC types / blocks and HMI tag tables.
- 2026-10-01, later: full redesign imported in one run (third try), first
  compile: all safety element links failed until the UDT elements were made
  accessible from the HMI (7.2). Screen titles removed from the redesign.
- 2026-10-01, run 3 prepared: 49 tab screens with generated faceplate
  instances, restyled pop-ups (Override), jog buttons rebuilt from presets.
- 2026-10-02, run 4 prepared: help in one text style, tab screens renamed
  with numbers in per-station folders, mode button feedback, G00 system on.

- 2026-10-02, run 6 prepared: internal tag for button feedback, group
  overviews with the Modes row as group bar.
- 2026-10-02, run 7 prepared: feedback back on the button bit, safety device
  symbols from rectangles, circles and lines (Line: StartLeft / StartTop /
  EndLeft / EndTop; height 0 for a horizontal line, `[INFERRED]` until
  imported) as the source for faceplate types (staging screen), graphic
  view at the graphic's own size (a scaled 128 px PNG pixelates).
- 2026-10-02, run 8 prepared: range appearance animations on Rectangle and
  Circle (BackColor = fill, ForeColor taken as the border colour
  `[INFERRED]` until imported) and on a transparent text field for a red
  text (BackColor of the range unused); status symbols grey while OK.
- 2026-10-02, run 9 prepared: invisible link buttons on the Modes rows;
  user name through a scheduled task on "User change".
- 2026-10-02, run 10 prepared: GetUserName removed from the generated screen
  events and the User pop-up (generator filters it out of copied screen
  events); the scheduled task is the only writer of the user name tag.
- 2026-10-02: faceplate type version mismatch crashed TIA during an import
  (pitfall above).
- 2026-10-02: project B catch-up run imported (tag table, three pop-ups with
  Override, 65 screens in two passes, nested folders); authorizations set
  per object in the generator; ImportStaging.ps1 continues after a failed
  screen (`$StopOnError = $false`, `$ScreenSkip`, failure list at the end).
- 2026-10-06: HMI preview built (validator, preview server, browser app,
  diff, PNGs through headless Edge); `render.py` retired; the generator
  writes to `hmi\generated\` and validates; TiaBridge `import` refuses on
  validator errors. Not yet run on project B.
- 2026-10-06: full exports only (2.3): TiaBridge exports screens, templates
  and pop-ups full into `hmi\<kind dir>`; the HMI preview's default sizes,
  fallback margins and colours removed, `document.incomplete` /
  `document.not-full` added; renders of 040, 1005, 5051, 5052 and the
  template from the full exports show no incomplete object.
- 2026-10-06: probes on project B through TiaBridge: HMI
  `TypeIdentifier` from the hardware side (section 5), screen size in the
  minimal export (section 4), `FaceplateTypeName` folders = library folder
  path (7.2). The preview's faceplate link check dropped the `_Library` root
  and was fixed (`links.py`); `list` kind `hmi_screen` reported `infoError`
  for every screen and was fixed (`Objects.ps1`). Still `[INFERRED]`:
  text-fit font size in pixels, absent margins as 0, `Culture` inside
  `FontItem`, the `//Portrait` suffix.
