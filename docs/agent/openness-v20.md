---
type: Guide
title: TIA Openness V20 facts for agents
description: What TIA Portal Openness V20 can and cannot do for the PLC blocks, HMI objects and library types an agent changes through TiaBridge, and how its failures look; index of parts and Siemens manual sources.
tags: [openness, tia-v20, agents]
generated: { by: antigravity/gemini, at: 2026-11-21T19:40:00-05:00 }
---

# TIA Openness V20 facts for agents

What an agent needs to know about the Openness API behind TiaBridge's tools: what goes through it, what does not, and
how it fails. The file formats are in the [SIMATIC SD guide](s7dcl-format.md) and the
[WinCC Comfort guide](wincc-comfort-openness.md); the screen objects in [WinCC Comfort screen objects](wincc-screen-objects.md).

Target: TIA Portal V20 Update 7 (`PublicAPI\V20`, file version 2000.7.201.2). Citations `[n]` are the Siemens pages
and files at the end. Markers: `[PROBE]` found by calling or reflecting on the installed API, `[EXPORT]` / `[IMPORT]`
seen in an export / import, `[INFERRED]` follows from those, not verified by a round trip.

**This guide in parts.** A section keeps its number in the file that holds it, so a section cited by number, here or elsewhere, is in the file this table names. Read only the part your change needs; never read the whole set for one change.

| File | Sections | Read for |
|---|---|---|
| `openness-v20.md`, this file | Intro, Sources | Index of parts and Siemens manual citations `[n]` |
| [openness-plc-blocks.md](openness-plc-blocks.md) | 1 (blocks, OBs, F-blocks and compile) | PLC blocks, OBs (Editing an OB's SimaticML), know-how protection, F-blocks, F-LAD, SimaticML calls, compile and export after a batch |
| [openness-plc-objects.md](openness-plc-objects.md) | 1 (watch and force tables, technology objects and folders) | Watch and force tables, technology objects and deleting user folders |
| [openness-settings.md](openness-settings.md) | 1 (project texts and settings) | Project texts, alarm classes, system diagnostics settings and ProDiag supervisions |
| [openness-hmi.md](openness-hmi.md) | 2 | WinCC Comfort HMI screens, screen numbers, templates, pop-ups, cycles, slide-ins, global screens, graphics, graphic lists, VB scripts, faceplates and HMI tag tables |
| [openness-libraries.md](openness-libraries.md) | 3 | Project and global libraries, library types, reviewed changes, types left behind and master copies |
| [openness-failures.md](openness-failures.md) | 4, 5 | Failing or hanging calls, exceptions, transactions, online mode, modal dialogs, names and files, archive, UMC, safety password, `project_open`, `project_close` and STA/MTA hangs |
| [openness-measurements.md](openness-measurements.md) | 1 (export timing, dates and software units), 6 | Export timing with a window, object dates and `GetAttributes`, software units and named value documents, fingerprints and offline comparisons (not needed for routine TIA changes) |

## Sources

Siemens system manual V20, "TIA Portal Openness: API for automation of engineering workflows", 01/2025, at
`https://docs.tia.siemens.cloud/r/en-us/v20/` (`...` = `tia-portal-openness-api-for-automation-of-engineering-workflows`;
read 2026-10-08):

6. Transaction handling: `.../tia-portal-openness-api/general-functions/transaction-handling`
7. Handling exceptions: `.../tia-portal-openness-api/exceptions/handling-exceptions`
8. Readme TIA Portal Openness V20, notes on use: `readme-tia-portal-openness/readme`
12. Basic principles of importing/exporting: `.../export/import/overview/basic-principles-of-importing/exporting`
13. Version Specific Simatic ML Import: `.../export/import/overview/version-specific-simatic-ml-import`
14. Exporting blocks: `.../export/import/importing/exporting-data-of-a-plc-device/blocks/exporting-blocks`
15. Importing block: `.../export/import/importing/exporting-data-of-a-plc-device/blocks/importing-block`
16. Exporting failsafe blocks: `.../export/import/importing/exporting-data-of-a-plc-device/blocks/exporting-failsafe-blocks`
17. Exporting program block as document: `.../export/import/importing/exporting-data-of-a-plc-device/blocks/exporting-program-block-as-document`
18. Importing program block from document: `.../export/import/importing/exporting-data-of-a-plc-device/blocks/importing-program-block-from-document`
19. Compiling a project: `.../tia-portal-openness-api/functions-for-projects-and-project-data/compiling-a-project`
21. Overview of exportable screen objects: `.../export/import/importing/exporting-data-of-an-hmi-device/screens/overview-of-exportable-screen-objects`
22. Importing a screen with a faceplate instance: `.../export/import/importing/exporting-data-of-an-hmi-device/screens/importing-a-screen-with-a-faceplate-instance`
23. Editing library type version: `.../tia-portal-openness-api/functions-on-libraries/editing-library-type-version`
24. Releasing library type version: `.../tia-portal-openness-api/functions-on-libraries/releasing-library-type-version`
25. Updating type from document: `.../tia-portal-openness-api/functions-on-libraries/updating-type-from-document`
26. Exporting library type version as document: `.../tia-portal-openness-api/functions-on-libraries/exporting-library-type-version-as-document`
27. Accessing global libraries: `.../tia-portal-openness-api/functions-on-libraries/accessing-global-libraries`
28. Create an object from a master copy: `.../tia-portal-openness-api/functions-on-libraries/create-an-object-from-a-master-copy`

Installed with TIA Portal V20:

33. `PublicAPI\V20\Siemens.Engineering.xml`, the XML documentation of the V20 assembly (file version 2000.7.201.2).
