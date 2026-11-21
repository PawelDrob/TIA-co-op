# Guides

* [SIMATIC SD (.s7dcl) authoring guide](s7dcl-format.md) - How to write SIMATIC SD (.s7dcl) PLC blocks for TIA Portal V20 and V21 that import cleanly, with every statement tagged by its source; the core every PLC change reads, and which part holds LAD networks, what exports showed and import diagnostics.
* [SIMATIC SD guide: import behavior and platform notes](s7dcl-import.md) - How TIA Portal V20 imports SIMATIC SD (.s7dcl) files, what its log messages mean and how to find a silent failure, and the platform notes of the Siemens readmes.
* [SIMATIC SD guide: LAD networks](s7dcl-lad.md) - How LAD networks are written in SIMATIC SD (.s7dcl) files for TIA Portal V20: rungs, wires, contacts, coils, boxes, calls, program control and the Calculate box, with a complete example block and the instruction set.
* [SIMATIC SD guide: what exports showed](s7dcl-exports.md) - What TIA Portal V20 exports of SIMATIC SD (.s7dcl, .s7res) files showed: instruction names, library and F-LAD instructions, DB, UDT and member shapes, the .s7res, and the import failures found in exported files.
* [TIA Openness V20 facts for agents](openness-v20.md) - What TIA Portal Openness V20 can and cannot do for the PLC blocks, HMI objects and library types an agent changes through TiaBridge, and how its failures look, with what its fingerprint and compare calls answer, cited to the Siemens manual and to probes on V20 Update 7.
* [WinCC Comfort screen generation with TIA Portal Openness](wincc-comfort-openness.md) - How to generate WinCC Comfort screens, pop-ups, tag tables and text lists as SimaticML and import them through TIA Portal Openness V20.
* [WinCC Comfort screen objects](wincc-screen-objects.md) - Every object of the WinCC Comfort toolbox with every option, its TIA display name and group, export name, default, allowed values and what the HMI preview draws; generated from TiaHmiGenerator/catalogue/catalogue.json.
* [WinCC Comfort: faceplates](wincc-comfort-faceplates.md) - What TIA Portal V20 Openness can and cannot do with WinCC Comfort faceplate types, and how a faceplate is built from a generated staging screen.
* [WinCC Comfort: the Openness API from PowerShell](wincc-comfort-api.md) - How the TIA Portal V20 Openness API loads in PowerShell 5.1 and where the HMI objects of a WinCC Comfort device are in it, as found by probes.

# Rationales

* [WinCC Comfort: history of the first runs](wincc-comfort-history.md) - The first WinCC Comfort generation and import runs on project B, 2026-10-01 to 2026-10-06, in order, with what each changed.
