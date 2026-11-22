# Guides

* [SIMATIC SD (.s7dcl) authoring guide](s7dcl-format.md) - How to write SIMATIC SD (.s7dcl) PLC blocks for TIA Portal V20 and V21 that import cleanly, with every statement tagged by its source; the core every PLC change reads, and which part holds LAD networks, comments, data, instructions and import diagnostics.
* [SIMATIC SD guide: blocks, interfaces and data as exports write them](s7dcl-data.md) - How TIA Portal V20 exports write SIMATIC SD block headers, interfaces, data types, DBs, start values and retain, and how a classic SCL source maps to SD.
* [SIMATIC SD guide: comments and titles in the .s7res](s7dcl-resources.md) - How TIA Portal V20 writes the comments and titles of a SIMATIC SD block in its .s7res, and the import failures a resource file gave.
* [SIMATIC SD guide: import behavior and platform notes](s7dcl-import.md) - How TIA Portal V20 imports SIMATIC SD (.s7dcl) files, what its log messages mean and how to find a silent failure, and the platform notes of the Siemens readmes.
* [SIMATIC SD guide: instructions as exports write them](s7dcl-instructions.md) - How TIA Portal V20 writes instructions in SIMATIC SD (.s7dcl) and SimaticML where the names differ from its screen, and how extended, communication, Technology, Optional packages and F-LAD instructions go in.
* [SIMATIC SD guide: LAD networks](s7dcl-lad.md) - How LAD networks are written in SIMATIC SD (.s7dcl) files for TIA Portal V20: rungs, wires, contacts, coils, boxes, calls, program control and the Calculate box, with a complete example block and the instruction set.
* [TIA Openness V20 facts for agents](openness-v20.md) - What TIA Portal Openness V20 can and cannot do for the PLC blocks, HMI objects and library types an agent changes through TiaBridge, and how its failures look; index of parts and Siemens manual sources.
* [TIA Openness V20 facts: failures, modal dialogs and project lifecycle](openness-failures.md) - How TIA Portal Openness V20 calls fail, transactions, online mode, modal dialogs, names and files, archive, UMC, safety passwords, starting TIA, opening and closing projects, and STA/MTA hangs.
* [TIA Openness V20 facts: HMI (WinCC Comfort)](openness-hmi.md) - What TIA Portal Openness V20 can and cannot do with WinCC Comfort screens, screen numbers, templates, pop-ups, cycles, slide-ins, global screens, graphics, graphic lists, VB scripts, faceplates and HMI tag tables.
* [TIA Openness V20 facts: libraries](openness-libraries.md) - What TIA Portal Openness V20 does with project and global libraries, library types, reviewed changes, types left behind and master copies.
* [TIA Openness V20 facts: measurements, dates, software units and comparisons](openness-measurements.md) - TIA Portal Openness V20 probe measurements: export timing with a window, object dates and GetAttributes, software units and named value documents, and fingerprints and offline comparisons.
* [TIA Openness V20 facts: PLC blocks, OBs and compile](openness-plc-blocks.md) - What TIA Portal Openness V20 does with PLC blocks, data types, DBs, OBs (editing an OB's SimaticML), PLC tag tables, know-how protected blocks, F-blocks, F-LAD, SimaticML calls and compiles.
* [TIA Openness V20 facts: project texts and settings](openness-settings.md) - What TIA Portal Openness V20 does when importing project texts, alarm classes, system diagnostics settings and ProDiag supervisions.
* [TIA Openness V20 facts: watch and force tables, technology objects and folders](openness-plc-objects.md) - What TIA Portal Openness V20 does with PLC watch tables, force tables, technology objects and user folders.
* [WinCC Comfort screen generation with TIA Portal Openness](wincc-comfort-openness.md) - How to generate WinCC Comfort screens, pop-ups, tag tables and text lists as SimaticML and import them through TIA Portal Openness V20.
* [WinCC Comfort screen objects](wincc-screen-objects.md) - Every object of the WinCC Comfort toolbox with every option, its TIA display name and group, export name, default, allowed values and what the HMI preview draws; generated from TiaHmiGenerator/catalogue/catalogue.json.
* [WinCC Comfort: faceplates](wincc-comfort-faceplates.md) - What TIA Portal V20 Openness can and cannot do with WinCC Comfort faceplate types, and how a faceplate is built from a generated staging screen.
* [WinCC Comfort: the Openness API from PowerShell](wincc-comfort-api.md) - How the TIA Portal V20 Openness API loads in PowerShell 5.1 and where the HMI objects of a WinCC Comfort device are in it, as found by probes.

# Rationales

* [WinCC Comfort: history of the first runs](wincc-comfort-history.md) - The first WinCC Comfort generation and import runs on project B, 2026-10-01 to 2026-10-06, in order, with what each changed.
