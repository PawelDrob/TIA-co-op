---
type: Guide
title: TiaChangeReports internals
description: How the change report reads two states of a project (SIMATIC SD, SimaticML, HMI XML), what it compares, how LAD is diffed and drawn, and what the page holds.
tags: [dev, change-reports, plc, hmi]
status: draft
generated: { by: claude-code/claude-opus-5-5, at: 2026-11-18T13:16:38-05:00 }
---

# TiaChangeReports internals

Two states of a project go in, and one self-contained HTML page of what changed comes out. It never touches TIA. What it does for a user is in [its README](../../../TiaChangeReports/README.md), its options in the head of `__main__.py` and `--help`, and the rules it is reviewed against in `CODING_STANDARDS.md`, section Change reports. An example page is in [the user assets](../../user/assets/archive-compare-example.html).

## Inputs

| Input | Read by | Holds |
|---|---|---|
| `.s7dcl` + `.s7res` (SIMATIC SD) | `s7dcl.py` | FBs, FCs, DBs, UDTs; the supported format |
| `.xml` (SimaticML) | `simaticml.py` | OBs, know-how protected blocks and blocks TIA refused as SD; experimental for the rest |
| `.libinfo` beside a library type | `source.py` | Its version and in-work state |
| `plc\tags\*.xml` | `plctags.py` | PLC tag tables |
| `hmi\`, `project\graphics\` | `hmi.py`, through `hmipreview` | Screens, templates, pop-ups, slide-ins, global elements, tag tables, lists, cycles, connections, scripts, graphics |

Both block formats read into one model, so an OB compares and draws like any other block. Sides come as two files, two folders or two git revisions (`source.py`: a revision through one `git ls-tree` and `git cat-file --batch`).

**What counts in a project repo** is in [the Archive Compare README](../../../TiaArchiveCompare/README.md#what-it-does-not), Export folders; `source.py` holds it (`EXPORT_ROOTS`). `library\changes\` goes unnamed, as it holds a review's working copies.

## What it compares

**Pairing blocks.** By relative path, then file name, then kind and number or content for a rename. The extension does not count, so a block moved from XML to `.s7dcl` pairs.

| Part | How |
|---|---|
| Block properties | Apart from the interface: TIA raises the version on every edit, and that should not read as an interface change |
| Interface | One table as TIA's editor shows it. Members pair by name under their parent, then as a rename by comment or by place. Only a real one-to-one pairs: otherwise removed and added. A move between sections or structs reads "moved" |
| DB start values | Members of the same tree, also inside a UDT or array |
| Networks | Paired by title in sequence, then by content or the same logic. Untitled ones also by their content where that reads better: fewer networks listed, then fewer new or deleted, then pairs the same or alike rather than not alike, and fewer moved (an edit in place costs no more than a network deleted and another changed). At a tie the pairing by title stands |
| LAD | The logic diff below |
| SCL | A side-by-side line diff |
| Library type | Version before and after. A program block and its type with the same change show once, as the program block. If they differ, both show |
| HMI | Object by object through `hmipreview`, drawn with the preview's own JavaScript, so the two cannot drift apart |

**The LAD diff** (`diff.py`). A network is a graph: elements are edges between wire nodes, the rail and a sink. Series-parallel reduction turns it into a tree, and two trees are compared: series in order, parallel branches by the elements they share, box pins when their boxes pair. A change that merges two nodes reshapes the tree, so a repair pass works on the connections: identical elements pair again by their neighbours, same instructions become "changed", and identical ones with no neighbour in common "moved". Ties go in export order, so a report comes out the same every run.

**Moved, connected otherwise** (`NetDiff._reconnected`). Each node takes as its partner the node of the other version it shares the most with: the ends of paired elements and the pins of paired boxes. Where the elements that left their rung leave every node a partner once taken out, less those the rest does not need (a rung printed as two moves nothing), for no more than another pairing of equal elements would need, they are marked moved, as the text shows, and nothing else is tried; else the fewest elements, or pins, that do, with the wires they move whole. Both hold beside other changes in the network as alone. Taking an element out joins its two ends where both lead to one node of the other version, or one leads to none, never the rail with the end of the rungs: else one branch of an OR, taken out, would explain a rung that moved behind it. An element taken out at a point inside a series, where no pin reads, joins the elements before and after it. One whose two ends' links cross between the versions joins its ends too, wherever it stands: each end goes only to the other end, or, at the rail or the end of the rungs, to it among others (a contact moved off a tap). The search adds items one at a time while that costs less, tries any two near a node left, and tries each run of elements between two wires as one, since a run that moved whole is told only with all of it out. An element counts one, a pin of a box more than all of them, so two pins that exchange wires, of one call or of two, mark the wires, not the box. A pin that reads the same logic before and after (what feeds it, whatever its wire's name, which an edit renumbers) counts three times, and an element that feeds the same pins after, all of them reading the same logic, half more: such seldom moved; a box is marked when a wire has nothing of its own to show it, also beside other changes: in place of elements that stay by the rule of a plain swap (`_stays`), where its pins tell the rest, not of elements that left their rung where those tell it all. Rungs that share as many elements match by what they hold when telling which elements left their rung: the same shape (from the rail or a wire, the wires on its way, the end at a wire), then the same place. Rungs stand as one group where two share most with one rung only, each with the other, or where one is printed as rungs that hold its paired elements and no others; a rung's place is its group, or else the nearest group before it (or the start) and the paired elements in the rungs since, those of that group not counted. A rung added or removed on its own does not shift it, nor one printed as rungs that hold its paired elements, wherever they stand (a contact moved between those rungs does). A tie goes first to the elements that left their place in their rung (start, end, number among its elements), then to those whose rung reads otherwise. A swapped wire is marked whole, with a stem that also feeds a pin that stayed, not a stem of both wires, and no stem when its wire did not move whole; where the marks already there leave every node a partner, their wires move whole only with such a stem; and an element that feeds the pins it fed and kept its number among its rung's elements, or what ends where it starts, goes with no wire, as one beside contacts exchanged within the OR of one pin, the rung printed as two or not, unless an equal one feeds other pins. Two exchanges of equal elements tried at once are of four distinct elements: one FB instance may be called twice in a network. Two pins that exchange wires and nothing else is `_swapped_wires`. The shapes are the tests `SwappedPinWires`, `NotAPlainSwap`, `ConnectionsBesideAnotherChange`, `TheBoxBesideAnotherChange`, `OneReadingBesideAnotherChange`, `ContactsOffTheStemAtTheRail` and `TheSearchForMergedNodes` in `TiaChangeReports/tests/test_report_marks.py`.

**Reading SimaticML into rungs** (`simaticml.py`). A `FlgNet` is parts and wires. The elements are written back as rungs in the order the SD export uses, and names, pin order and templates are taken from what the SD export writes for the same instruction. `instructions*.py` hold what TIA's LAD editor draws per instruction, from exports and TIA's own screen.

**Drawing** (`render_lad.py`). Every element takes a cell; a wire node sits at the longest path from the rail; rows go in export order, first-fit below what they attach to. An FB or FC call lays out its pins from the called block's interface when the input holds it.

**Self-check** (`verify.py`). `Layout.wiring()` returns the drawn lines. `verify` rebuilds the nets from them and requires a one-to-one match with the parsed network, and reports crossings without a junction, loose lines, overlaps and lines through elements. It shows the drawing holds the logic of the code, however close it looks to TIA.

## What it leaves out

**Ignored as the export's own doing:** [the Archive Compare README, What it does not](../../../TiaArchiveCompare/README.md#what-it-does-not), the last row of its table.

**Unread:** whatever a reader does not read, in another language, or that the page cannot show. If the two files differ there, the page carries a note, also beside a change it shows: `beside.py` tries each part of a network that differs alone on the version before, and a part that reads the same there is the network's note. Limits on that note: [its README, What it does not](../../../TiaChangeReports/README.md#what-it-does-not).

## The two formats against each other

`twoformats.py` shows where the report reads a SimaticML export otherwise than the `.s7dcl` of the same block. Its input is a repo where every commit holds both formats of the same objects, as the two-format benchmark run's does: `.s7dcl` under `plc\` and `library\`, SimaticML under `simaticml\`. That repo is not in the clone. The bed reads its commits and changes nothing in it.

```
.venv\Scripts\python.exe -X utf8 -m TiaChangeReports.twoformats <repo> [--since REV] [--until REV] [--check nothing|same|both] [--json out.json]
```

Run it from the clone's folder, which `-m` needs. It starts at the first commit with a file under `simaticml\` unless `--since` names another, and ends at `--until`, by default the commit checked out (`HEAD`). It runs both checks unless `--check` names one.

- **Nothing changed:** per commit, the report from its `.s7dcl` to its SimaticML. Each object and network the report lists is a difference. Its first line names the first commit, the last and the one with the most objects, each with the objects and, in brackets, the networks listed. Per cause it then prints, at each of the three, the objects and networks, and in brackets the networks with no other cause.
- **The same change:** per commit, the report of the commit from `.s7dcl` and from SimaticML. Each object whose two reports differ is a difference. Per cause it prints the commits and the objects (an object counted once in each commit it differs in), and in brackets the commits where the cause is the only one.

Each cause prints with its kind: a reader that reads a format otherwise, a field only one format writes, the note, the drawing, the diff, or an object in one format only; what the bed cannot name, `unknown`. `--json` writes every difference with its causes, and for the second check the facts each report alone holds. Both checks over 530 commits take about half an hour in the foreground: a process started at low priority, as a background job may be, runs the first check several times slower.

**The sides.** Both are `GitSnapshot`s of one commit, restricted to `plc\blocks\`, `plc\types\` and `library\types\`: the folders both formats hold. The SimaticML side is the `simaticml\` folder, read whole (`_laid_out` off), as its root is no project repo's. The report is `compare_snapshots`, the same call the page makes.

**Facts.** A report is reduced to facts: per listed object its state, kind, declaration, note and library link; per interface row that differs its path, state and the fields that differ with their values (a start value apart), a member added or removed with its type, start value, comment, retain and attributes; per property its values; per network its state, language and tags, title and comment; per drawn LAD element its mark (the element as compared without its element id and wire names, its ENO included, the fill, and the areas marked from the element's own corner, from `Layout.marks`); per SCL or FBD network the lines that differ, all of them for a network added or removed. Two reports say the same when the facts are the same multiset. What that cannot see: which of two equal elements of a network carries a mark, where an element stands, the lines and wires drawn, the page's HTML, PLC tag tables and the HMI part; of a block listed by its heading alone (only its library version changed, or only its folder), what the page does not show either.

**Causes.** A cause has an id and a kind (`CAUSES`), named from what differs, never from the kind of object alone. For an element the two readers read otherwise, `element_causes` finds the fewest normalisations (`STEPS`: quotes around member names, pin case, pin direction, pin order, templates one side lacks, ENO) that make the two equal. A property is named by its values (`property_cause`): `DB retain` only where SimaticML has none. For a file one format moved and the other did not, and for a note one report has and the other not, `xml_moved` lists what differs in the SimaticML, order and ids left out, and `field_causes` names it from `XML_FIELDS`; a field the `.s7dcl` report shows and the SimaticML one leaves to its note from `XML_UNREAD`. An object with a file in one format only is `SimaticML missing` (SimaticML of it in another commit), `SimaticML never` or `.s7dcl missing`: what is seen, not why, which the run's log tells; so is an object a report joins to it (a rename, a move, its library type), and nothing else is looked for on it. Rung order names only marks of elements moved in a network tagged as in another order. An object or network both reports list in another state, kind or language, and a network title or comment that differs, is `unknown`; one a single report lists takes the causes of its other facts. What fits no rule has no kind: `unknown: ...`, or a field by its path (`SimaticML field: ...`, `SimaticML unread: ...`, `.s7dcl field: ...`). A field neither reader reads gives both reports the same note: the second check cannot see it, and in the first it is part of `note: files`.

**In the hook.** The full run takes half an hour and needs the benchmark repo: not in the hook. `tests\test_two_formats.py` runs it on three real commits from that repo, copied into `tests\fixtures\twoformats\`, in about three seconds.

## Files

| File | What |
|---|---|
| `__main__.py` | Command line; `--json` and `--png` |
| `source.py` | The sides: files, folders and git revisions; pairing |
| `s7dcl.py`, `simaticml.py`, `plctags.py` | Readers |
| `names.py` | An object's name as declared, and its file-safe form |
| `instructions.py`, `instructions_*.py` | The system instructions the report knows |
| `compare.py`, `diff.py`, `iface.py` | Networks and blocks, the LAD diff, interface and properties |
| `beside.py` | What a network's file holds and the report does not read, beside a change it shows |
| `render_lad.py`, `verify.py` | The drawing and its self-check |
| `page.py` | The page or fragment: summary, block sections, project tree, script |
| `hmi.py`, `hmi.js`, `hmi.css` | The HMI part |
| `twoformats.py` | The two formats against each other: facts of a report, the two checks, their causes |

## The page

A self-contained HTML file: nothing is fetched. A summary table and a project tree in TIA's folders lead to the block sections, with `Before` and `After` columns from their sources. The HMI part stores its documents gzipped and base64-encoded in the page, and draws an object when it opens. `--fragment` writes only the `<div class="ldiff">`, and `--png` a screenshot through headless Edge or Chrome.

## Who calls it

- **TiaBridge's `change_report`:** `--git <repo> REV1 REV2 --json`.
- **TiaArchiveCompare's runner:** two export folders, through junctions named after the inputs, as the report names a side by its folder.

`--json` prints one object: `page`, `before`, `after` and `blocks`, and where they apply `plcTags`, `hmi`, `skipped`, `unmatched` and `png`.

Exit codes, and what it skips rather than stops at: [its README, What it does not](../../../TiaChangeReports/README.md#what-it-does-not).
