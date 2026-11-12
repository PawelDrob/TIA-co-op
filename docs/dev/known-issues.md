---
type: Guide
title: Known issues
description: What TIA Openness V20 cannot do and which problems of the tools are not solved, for anyone changing the tools.
tags: [dev, openness]
status: draft
generated: { by: claude-code/claude-opus-5-5, at: 2026-11-12T12:15:31-05:00 }
---

# Known issues

What a change has to reckon with. The evidence is in [the Openness facts](../agent/openness-v20.md) and [the WinCC Comfort guide](../agent/wincc-comfort-openness.md). What a user is told is in [the README](../../README.md#limitations), section Limitations, and in each tool's README.

## What Openness cannot do

The list is in [the README, Limitations](../../README.md#limitations), and what it leaves out of a report in [the Archive Compare README, What it does not](../../TiaArchiveCompare/README.md#what-it-does-not). What the tools do about it:

- **Faceplate type contents** do not export: a person builds the type in TIA from a staging screen.
- **Master copy contents** do not export: `full_export` lists each master copy and what it holds in `library\mastercopies\mastercopies.json`. Placing one in the project and making one from project objects work, for the PLC (`master_copy_to_project`, `master_copy_from_project`).
- **Blocks that are not consistent** can refuse their export: compile them first, on the project open in TIA after `connect` (its session archive is the way back) or in a background session on a copy.
- **The 14 screen objects TIA does not export,** such as the alarm view: an import over their screen deletes them with no message. Such screens go in `hmi\handbuilt.json`, and the validator refuses a generated document over them (`handbuilt.override`).
- **F-system blocks and the F-OB:** `full_export` lists them as left out.
- **Know-how protected blocks:** an import over one replaces it unprotected, with no message, so the bridge refuses it.
- **External source contents** do not export: counted only.

## What the tools leave out

- **A screen's number and its template:** not in a `list` result, only in its export.
- **The hardware configuration:** the bridge does not export it ([decisions](decisions.md#the-bridge)).

## TIA itself

- **TIA waits on an Openness client attached from an STA thread** ([the Openness facts](../agent/openness-v20.md), [the README, Limitations](../../README.md#limitations)). A change to a list a session read waits for that session's next call. The bridge runs on an MTA thread of its own (`TiaBridge.ps1`), so its call-backs run at once; a window it shows runs on an STA thread of its own (`Invoke-OnStaThread`), and a read of a list TIA changed meanwhile is read again (`Read-TiaList`): the objects of each kind, folder trees, devices, projects and global libraries, not other lists such as a library type's versions and dependencies. Another program attached from an STA thread, a bridge of release 0.1.0 among them, still hangs TIA. An import that never returned with one bridge attached is not explained.
- **TIA ends its own process after a `NonRecoverableException`,** for example on a refused HMI import whose dependent property does not follow its main one. Unsaved edits go with it. The result says `tiaEnded`, and the bridge refuses TIA calls until the next `connect`.
- **A failing call can wait behind a message box** for many minutes. In a TIA with no window, the bridge answers prompts Cancel or No and lists them. Whether TIA raises those events for every modal message is not proven.
- **A PLC with a safety program can need the safety login for a whole compile.** F-blocks imported as SimaticML answer "No safety license available" on a PC with no safety license; `.s7dcl` takes them.
- **`UpdateProject` removes every released library instance nothing uses,** and what only those use. TIA's own window does the same.
- **A library type with no instance stays on old versions,** as no update moves it. Results name such types in `typesLeftBehind`, and `library_left_behind` holds what a person can answer.
- **An HMI tag table imported right after its delete can come back as `<name>_1`.** The bridge compares the name TIA returns with the document's and reports `namedOtherwise`.

## Formats

- **The `.s7dcl` import keeps only the last index of a multi-dimensional operand** (`a[i, j]`). Seen in LAD; the export's note also warns of FBD networks. Such a type is changed as SimaticML.
- **Exports differ with no change.** SimaticML files carry a `<Created>` stamp, and `.xlsx` and `.dat` files change their bytes on every run. The report ignores what the export itself writes differently.
- **A commit that only switches a type's format can read as changes,** as the two readers do not agree on everything. Commit the switch on its own.

## The tools

What each tool does not do is in its README, under "What it does not". Beyond those:

- **The bridge, not run on content:** technology objects, PLC alarm text lists, graphic lists, VB scripts, connections, external sources. They are built from the API documentation.
- **The bridge does not reach software units:** their folders are a tree of their own.
- **A killed bridge leaves its background TIA and copy.** The next `background_open` removes copies of bridges that are gone and lists the TIA processes, which a person ends.
- **Logins of protected projects,** UMC included: [the Archive Compare README](../../TiaArchiveCompare/README.md#what-it-does-not), Protected projects.
- **The change report does not draw FBD:** it shows as text.
- **Some HMI drawings are inferred, not compared with TIA:** `EdgeStyle` Double, rectangle corner radii, gradient stops without offsets, Flat and Square line caps.
