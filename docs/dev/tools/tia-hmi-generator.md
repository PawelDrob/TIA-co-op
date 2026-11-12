---
type: Guide
title: TiaHmiGenerator internals
description: How WinCC Comfort screens are generated with hmixml, what the validator checks, how the preview server works, and how the screen object catalogue is built.
tags: [dev, hmi, wincc-comfort]
status: draft
generated: { by: claude-code/claude-opus-5-5, at: 2026-11-12T17:14:31-05:00 }
---

# TiaHmiGenerator internals

Writes WinCC Comfort screens as SimaticML, checks them and shows them before they go into TIA. WinCC Comfort and Advanced on Comfort Panels; not Unified or Basic Panels. What it does for a user is in [its README](../../../TiaHmiGenerator/README.md). The document format and how to write a generator are in [the WinCC Comfort guide](../../agent/wincc-comfort-openness.md), and the objects in [WinCC Comfort screen objects](../../agent/wincc-screen-objects.md).

| Part | What |
|---|---|
| `hmixml.py` | The library a project's generator in `gen\` calls |
| `hmipreview\` | Validator, preview server, PNGs, diff and changes. Standard library only, with plain ES modules in the browser and no build step |
| `catalogue\` | Every object of the toolbox with its options |

## Generating: hmixml

Every object is copied from a full export or the catalogue's fixture. The generator sets geometry, names, texts, formats, links, animations and events, never a default of its own ([why](../decisions.md#hmi)). A run calls `begin` for the device and panel, `plan` and `add` for its items, then `finish`. The head of `hmixml.py` documents each call, when it raises, and the object dict.

`finish` validates before anything reaches the disk, in memory (`model.load` with an overlay), so the rest of the repo and its git history stay real and the preview never sees a refused run. With any error it raises `GenerationRefused`, and nothing is written. Otherwise it writes `hmi\[<device>\]generated\` with `screens\`, `templates\`, `popups\` and `textlists\`, `panel.json` when `panel=` declares the panel, `planned.json` (exactly this run's items) and `generated.json` (when each document was generated and which preset each object came from).

**Which documents count.** A generated document replaces the export of the same kind and name, by kind and name, not by path: this is the effective set. The folder tells "in TIA" from "not yet".

**Which device.** `--device`, else `hmiDevice` in `tiabridge.json`, else the only device folder (`model.select_device`). The exports of the other devices count as references for the vocabulary, but their screens are not links of this one.

## Validating

`hmipreview.validator.validate(repo, for_import=False, override=False, overlay=None, device=None)` returns findings of `severity`, `document`, `object`, `rule` and `message`. Three callers: `hmixml.finish`, the preview, and the bridge's import guard (`validate --json --import`). The rules read generated documents, as an export is in TIA already. Some read exports too: `document.not-full`, which tells that an export must be made again, `resolution.screen-size`, a warning on an export, and the `cycle` rules, which read only the cycle exports in `<hmi>\cycles`, as the bridge imports cycles from there.

A new rule group is a new file in `hmipreview\rules\` defining `check(repo, ctx)`. Rule ids are `<group>.<rule>`, and each module's head says what each finds and how severe it is.

| Group | Finds |
|---|---|
| `document` | An object lacking attributes every object of its type has; an export that is not full |
| `vocabulary` | An element type, attribute or value outside the catalogue and the exports |
| `resolution` | No known device, no device chosen, declared panel against hardware, screen size |
| `links` | A target that neither exists nor is planned; open planned items, an error at import |
| `geometry` | An object outside the screen; overlaps; an object hidden below another |
| `handbuilt` | A generated document replacing hand-built objects; overlap with them |
| `staleness` | A TIA export newer than the generated document, an error at import unless override is passed |
| `structure` | Grouped faceplates, duplicate names and screen numbers |
| `dependent` | A property that does not follow its main one (`catalogue\dependent.json`), which can end TIA |
| `iofield` | A format pattern with a decimal point on a tag not known to hold a float |
| `languages` | Texts missing a project language |
| `text` | A text that does not fit its box in a language |
| `tagtable` | A generated HMI tag table whose `Length` or `HmiDataType` does not fit its data type, which ended TIA |
| `cycle` | A cycle export that is not full or lacks `StartAtStartingPoint` (warning, an error at import); another object in the cycles folder |

**What makes an error** and what a warning: [decisions](../decisions.md#hmi).

## The preview

`python -m hmipreview` holds `validate`, `serve`, `diff`, `png`, `panel` and `changes`; the head of `__main__.py` has their options and exit codes.

`serve` answers on `127.0.0.1` and shows every HMI device of the repo. It draws the SimaticML that will be imported ([why](../decisions.md#hmi)).

- **Server** (`server.py`): `/api/screens`, `document`, `findings`, `planned`, `handbuilt`, `picture`, `pictures` and `events` (Server-Sent Events on a file change); `/api/tree` is in `treeapi.py` and `/api/diff` in `diffapi.py`. `screens`, `document`, `findings`, `planned`, `handbuilt` and `diff` take `?device=`; the project graphics and `events` are one for the repo. Requests answer for the repo as it is on disk.
- **Cache** (`repocache.py`): the loaded repo and its findings stay while the fingerprint of `hmi\`, `library\`, `tiabridge.json` and the git HEAD is unchanged.
- **Browser** (`static\`): `render.js` and `simaticml.js` draw; `diff.js` marks changes; `rail.js` is the project tree, shared with the report.
- **Comparison** (`changes.py`, `sides.py`, `diff.py`): the library the change report uses, on folders, revisions or the working tree, each side as TIA exports or generated documents.
- **PNGs** (`png.py`, `edge.py`): headless Edge or Chrome, at device resolution.

## The catalogue

`catalogue\build.py` builds `catalogue.json` (read by `hmixml` and the preview) and the generated page [WinCC Comfort screen objects](../../agent/wincc-screen-objects.md). `build.py --check` runs in the hook, so the page cannot drift.

| Input | What | Source |
|---|---|---|
| `toolbox.json` | The toolbox: display names, groups, greyed-row conditions, the repo's own descriptions | Kept by hand, from TIA's Properties window |
| `fixture\` | Full exports of every toolbox object dropped unchanged | TIA, decides attributes and defaults |
| `helpfacts.json` | Documented properties, values and ranges, with no help text | TIA's installed help |
| `seen.json` | What full exports use: names and spellings only | Project repos, refreshed with `--seen` |
| `enums.json` | TIA's own enum members | Reflection on TIA's HMI library |
| `roundtrip\` | Values sent to TIA on `zz` screens, and what came back | `roundtrip.py` and a person or agent with TIA |

`dependent.json`, which property follows which and what TIA was seen to refuse, is no input of the build: the validator and `roundtrip.py` read it (`hmipreview\catalogue.py`). A value that came back from the round trip is confirmed, and one that came back different is lost. Nothing of Siemens' text, fonts or images is stored.
