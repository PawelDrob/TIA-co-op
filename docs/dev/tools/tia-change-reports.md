---
type: Guide
title: TiaChangeReports internals
description: How the change report reads two states of a project (SIMATIC SD, SimaticML, HMI XML), what it compares, how LAD is diffed and drawn, and what the page holds.
tags: [dev, change-reports, plc, hmi]
status: draft
generated: { by: claude-code/claude-opus-5-5, at: 2026-11-24T17:16:30-05:00 }
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
| DB start values | Members of the same tree, also inside a UDT or array. An instance DB or a DB of a UDT: the start values it sets, read alike from `.s7dcl` and SimaticML; the members TIA writes into its SimaticML from the FB or UDT are not read, and a change of them is the note. From SimaticML not those of a member inside an array of struct, nor of an element under an array of a UDT, as no real export shows which path they would be read at: a change of them is the note, also beside a start value read under the same member |
| Networks | Paired by title in sequence, then by content or the same logic. Untitled ones also by their content where that reads better: fewer networks listed, then fewer new or deleted, then pairs the same or alike rather than not alike, and fewer moved (an edit in place costs no more than a network deleted and another changed). At a tie the pairing by title stands |
| LAD | The logic diff below |
| SCL | A side-by-side line diff, its words in the colours of TIA's SCL editor (below) |
| Library type | Version before and after. A program block and its type with the same change show once, as the program block. If they differ, both show |
| HMI | Object by object through `hmipreview`, drawn with the preview's own JavaScript, so the two cannot drift apart |

**The LAD diff** (`diff.py`). A network is a graph: elements are edges between wire nodes, the rail and a sink. Series-parallel reduction turns it into a tree, and two trees are compared: series in order, parallel branches by the elements they share, box pins when their boxes pair. An element compares as `Element.sig()`: its named pins by name in any order, as TIA's export writes one box's pins in another order between two exports of a block nobody changed and each pin is bound by its name; an instruction's pin name in any case, as the two formats write one otherwise (SimaticML `PV` where `.s7dcl` writes `pv`), a block call's as written, as both write it as the block declares it and a user may rename it in case (`Element.pin_as_compared`; the drawing marks the pin's name); its unnamed operands by their place. An operand of `.s7dcl` reads as the SimaticML reader writes it (`operand_text`): a part after a dot or a `#` without the quotes round a plain name, as SimaticML holds the name alone and `.s7dcl` writes it in quotes or not (`"zzInvBen"."step"`, `"zzInvBen".c[24]`); the name stays as written, and a name that is no identifier or is a keyword keeps its quotes in both (`part_text`). A coil's operand (its `operand`, `timer` or `counter`) reads as an output from SimaticML too, as `.s7dcl` writes it where the coil names its pins (`TP_Coil( timer => #t, pt := T#1s )`): SimaticML wires every pin of a coil as an input, and the instruction fixes the direction, so the arrow is never a change. A template at the value its instruction fixes, which SimaticML writes and `.s7dcl` leaves out, is left out from SimaticML too, in the element and in the network's part of the file the note compares, and from a `.s7dcl` that writes one, in the element and in the network's text as read, which its note, its units (`beside.py`) and the block's file note compare (`s7dcl.lad_read`, `s7dcl.text_as_read`; the rule: `instructions.left_out`): a type (`Instruction.fixed`: TUSEND's `value_type` UDInt, RDREC's `ptr_type` Variant), and the `Card` 2 of Sub, Div and Mod, which take two inputs only and which TIA writes in some exports and not in others; another value is read and compared. The diff pairs pins in any case (`pin_key`): the logic feeding a pin, and two networks by what they hold (`similarity`). A network's lines (`lad_lines`), which tell what no drawing reads, read their operands so and take the named pins of a box in that one order and case too, where all the lines between its `(` and `)` are named pins. Between two formats a network's lines are those as read (`compare._read_lines`): the rungs of each written by one writer (`simaticml.rungs_text`), a box's pragma on one line, its templates and its settings each in the order of their names, so that a pragma over several lines, an `S7_Templates` in brackets, `S7_Relation` beside it, a box's pins on one line and the jump label's line, which is compared apart, are no note. The settings in front of a box whose value no field takes are compared from both (`Element.settings`): an F-box's cards (`f_user_card`), which SimaticML writes as templates of those names; from `.s7dcl` also any other, such as an `S7_GenerateENO` of a value other than TRUE or FALSE. What the reader of an `.s7dcl` reads nothing from is compared too, and the other format has none (`Network.unread`): as written, a comment line, a line no element is read from, the pragmas after the last box, the rest of a line read in part (after a pragma's `}`, after a `RUNG`'s or `END_RUNG`'s wire, a pragma's or `S7_Templates`' part that names no setting or template); as `name := value`, a value a later one of its name overwrites. A change that merges two nodes reshapes the tree, so a repair pass works on the connections: identical elements pair again by their neighbours, same instructions become "changed", and identical ones with no neighbour in common "moved". Ties go in export order, so a report comes out the same every run.

**SCL colours** (`scl_colours.py`). The words of an SCL network take the colours TIA V20's SCL editor gives them, as read from pictures of the editor on a block that holds every kind (`TheKindsAsReadFromTia`). There are twelve kinds, the dict `KINDS` with the colour read for each (`test_each_kind_has_the_colour_read_from_tia`); the semicolon and a jump label are in the text's own black. One tokenizer reads the text of the lines, so a line reads in the same colours from `.s7dcl` and from SimaticML (`BothFormatsAlike`): the token kinds SimaticML carries are not used, as `.s7dcl` has none. The block's interface tells a local constant, a `#name` it declares in `VAR CONSTANT`, in any case; with no interface at hand no `#name` is a local constant (`LocalConstants`). Colouring changes no character, and the changed words keep their marks: a plain `<span>` round each, the colours as spans with a class inside it, and the page marks only a span with no class (`TextAndMarksUnchanged`).

The tokenizer works in two passes, which the module's doc writes as tables. The first cuts each line into whole tokens: the rules about a whole line first (a comment open from the line before, then the rest of a REGION line as the region's name), then token by token, a literal by one pattern per form of the list `LITERALS`, an address by the lists the comment over them names, a DB's data (`DBX0.0`) wherever it stands. A token of the list `WORD_LIKE` never ends inside a word: a letter, digit or `_` after a word, a `#name` (quoted or not), a literal other than a string, an address or a DB's data goes into it; a quoted name and a string end at their quote (`WhereATokenEnds`). Nothing inside a comment, string, quoted name or region's name is read again. The second is given the tokens only, never a line's text (`test_pass_2_reads_tokens_only`): a word, `#name`, quoted name or DB's data takes the first rule of the list `RULES` that applies, its own text (a word of the lists `REGION_WORDS`, `BOOLS`, `WORD_OPERATORS`, `KEYWORDS`) before the label, call and parameter rules; a DB's data is an operand after a `.`. A rule that goes by position reads the network's tokens in order over its own lines (each side's text, never the rows of a diff), past spaces, comments, pragmas and line ends; what a rule carries (the depth of open parentheses, a type test's open parentheses) ends at a `;` or a word of the list `STOPPERS`. A data type a type test compares with (`TypeOf(#x) = Int`, `= "Udt"`) is a constant, told by where it stands: after the `)` closing the parentheses of a word of the list `TYPE_TESTS`, and an `=` or `<>`. In a call after a dot (`#timer.TON(`) the called name is a block call. Both are as TIA colours them. What has no colour of its own stays black: a pragma, a character no token takes, a DB's data not after a dot, a word no rule names.

The tests follow those parts, each table from a whole list its docstring names: the tokenizer's own lists where it has them, the S7DCL format guide's section 5 for the literal forms, with the forms SCL has and the guide lacks. `WhereATokenEnds` cuts every pair of a token of those tables and an operator, a bracket or a comment; `TheLiteralsAsATable` holds each literal form and ANY pointer as one constant and each address as one operand; `TheRulesAsAGrid` holds each rule of `RULES` that goes by position (it fails for one without a row) across each gap that keeps it and breaks it across each that does not; `HalfWrittenNetworks` holds what follows something left open, with every stopper; `WhichLineRuleGoesFirst` meets the line rules on one line and over two.

Not coloured: STL, a LAD or FBD network shown as text, the interface, and the title and comment fields of every network (`WhatStaysInOneColour`), and the viewer's Source view, which shows the file as it is (`TheViewer`). Printed, the words keep their colours and the marks their backgrounds (the page's `print-color-adjust`). The module's doc lists what SCL's grammar sets with no picture of TIA yet, and what no picture has settled. Its address lists are those of the S7-1200 and S7-1500, with `:P`; the comment over them names the forms outside them, which `test_the_forms_outside_the_lists_stay_cut_as_they_are` holds as they are cut.

**Moved, connected otherwise** (`NetDiff._reconnected`). Each node takes as its partner the node of the other version it shares the most with: the ends of paired elements and the pins of paired boxes. Where the elements that left their rung leave every node a partner once taken out, less those the rest does not need (a rung printed as two moves nothing), for no more than another pairing of equal elements would need, they are marked moved, as the text shows, and nothing else is tried; else the fewest elements, or pins, that do, with the wires they move whole. Both hold beside other changes in the network as alone. Taking an element out joins its two ends where both lead to one node of the other version, or one leads to none, never the rail with the end of the rungs: else one branch of an OR, taken out, would explain a rung that moved behind it. An element taken out at a point inside a series, where no pin reads, joins the elements before and after it. One whose two ends' links cross between the versions joins its ends too, wherever it stands: each end goes only to the other end, or, at the rail or the end of the rungs, to it among others (a contact moved off a tap). The search adds items one at a time while that costs less, tries any two near a node left, and tries each run of elements between two wires as one, since a run that moved whole is told only with all of it out. An element counts one, a pin of a box more than all of them, so two pins that exchange wires, of one call or of two, mark the wires, not the box. A pin that reads the same logic before and after (what feeds it, whatever its wire's name, which an edit renumbers) counts three times, and an element that feeds the same pins after, all of them reading the same logic, half more: such seldom moved; a box is marked when a wire has nothing of its own to show it, also beside other changes: in place of elements that stay by the rule of a plain swap (`_stays`), where its pins tell the rest, not of elements that left their rung where those tell it all. Rungs that share as many elements match by what they hold when telling which elements left their rung: the same shape (from the rail or a wire, the wires on its way, the end at a wire), then the same place. Rungs stand as one group where two share most with one rung only, each with the other, or where one is printed as rungs that hold its paired elements and no others; a rung's place is its group, or else the nearest group before it (or the start) and the paired elements in the rungs since, those of that group not counted. A rung added or removed on its own does not shift it, nor one printed as rungs that hold its paired elements, wherever they stand (a contact moved between those rungs does). A tie goes first to the elements that left their place in their rung (start, end, number among its elements), then to those whose rung reads otherwise. A swapped wire is marked whole, with a stem that also feeds a pin that stayed, not a stem of both wires, and no stem when its wire did not move whole; where the marks already there leave every node a partner, their wires move whole only with such a stem; and an element that feeds the pins it fed and kept its number among its rung's elements, or what ends where it starts, goes with no wire, as one beside contacts exchanged within the OR of one pin, the rung printed as two or not, unless an equal one feeds other pins. Two exchanges of equal elements tried at once are of four distinct elements: one FB instance may be called twice in a network. Two pins that exchange wires and nothing else is `_swapped_wires`. The shapes are the tests `SwappedPinWires`, `NotAPlainSwap`, `ConnectionsBesideAnotherChange`, `TheBoxBesideAnotherChange`, `OneReadingBesideAnotherChange`, `ContactsOffTheStemAtTheRail` and `TheSearchForMergedNodes` in `TiaChangeReports/tests/test_report_marks.py`.

**Reading SimaticML into rungs** (`simaticml.py`). A `FlgNet` is parts and wires. The elements are written back as rungs in the order the SD export uses (the rungs that feed a box's pins in the order of its pins, not of the file's wires, which TIA's export varies), and names, pin order and templates are taken from what the SD export writes for the same instruction. `instructions*.py` hold what TIA's LAD editor draws per instruction, from exports and TIA's own screen.

**Drawing** (`render_lad.py`). Every element takes a cell; a wire node sits at the longest path from the rail; rows go in export order, first-fit below what they attach to. An FB or FC call lays out its pins from the called block's interface when the input holds it.

**Self-check** (`verify.py`). `Layout.wiring()` returns the drawn lines. `verify` rebuilds the nets from them and requires a one-to-one match with the parsed network, and reports crossings without a junction, loose lines, overlaps and lines through elements. TIA's end mark at a rung's end (`Layout.ends()`) is drawing, not a line: `verify` reports one that stands where no wire ends, touches any line but the end of the one it closes, or stands in an element of another rung. It shows the drawing holds the logic of the code, however close it looks to TIA.

## What it leaves out

**Ignored as the export's own doing:** [the Archive Compare README, What it does not](../../../TiaArchiveCompare/README.md#what-it-does-not), the last row of its table.

**Unread:** whatever a reader does not read, in another language, or that the page cannot show. If the two files differ there, the page carries a note, also beside a change it shows: `beside.py` tries each part of a network that differs alone on the version before, and a part that reads the same there is the network's note. A SimaticML LAD or FBD network's part of the file is compared as a graph (`simaticml._flgnet`): no object numbers, no order of its operands and wires or of a wire's ends after its first, and in LAD no numbers of the inputs of an O that only joins wires; TIA's export varies all of these for a network nobody changed. The parts and calls keep their order, which TIA moves only where a user changed the network, and the reader orders the rungs by the O's inputs where the drawing does. A wire tried alone in `beside.py` has its ends on the parts of the version before that hold the same; the fields of a wire and its ends are compared apart, each wire by what it connects wherever the file writes it, an O's input read as `_flgnet` reads it. Two wires that connect the same compare their fields; the wires a change of the logic rewires compare theirs as a multiset, repeats counted; a wire with fewer than two ends on the rail or on the parts, calls and operands the two versions pair (`_numbered_before`) came or went with the change, and comes with its fields, as a part does. For a field the report does not read on a wire, beside a shown change, some cases are known to come out wrong, a note missing or one too many. A field on a wire moved to another rewired wire is one; so are two parts of one content where one is taken away, a part changed while TIA writes the wires in another order, and a wire put in or taken away between parts both versions keep. Real exports hold no such field. Limits on that note: [its README, What it does not](../../../TiaChangeReports/README.md#what-it-does-not). The files of two formats are not compared (`compare.file_note`): a block read from `.s7dcl` on one side and SimaticML on the other rests on what the report reads of both, and the page and `--json` (`acrossFormats`) name it, with what that leaves out.

## The two formats against each other

`twoformats.py` shows where the report reads a SimaticML export otherwise than the `.s7dcl` of the same block. Its input is a repo where every commit holds both formats of the same objects, as the two-format benchmark run's does: `.s7dcl` under `plc\` and `library\`, SimaticML under `simaticml\`. That repo is not in the clone. The bed reads its commits and changes nothing in it.

From the clone's folder: `.venv\Scripts\python.exe -X utf8 -m TiaChangeReports.twoformats <repo>`; `--help` lists its options.

- **Nothing changed:** per commit, the report from its `.s7dcl` to its SimaticML. Each object and network the report lists is a difference, and each SCL network where a line of the same text in both is coloured otherwise (`scl_colours_differ`: `unknown: SCL colours`). Its first line names the first commit, the last and the one with the most objects, each with the objects and, in brackets, the networks listed. Per cause it then prints, at each of the three, the objects and networks, and in brackets the networks with no other cause.
- **The same change:** per commit, the report of the commit from `.s7dcl` and from SimaticML. Each object whose two reports differ is a difference. Per cause it prints the commits and the objects (an object counted once in each commit it differs in), and in brackets the commits where the cause is the only one.

Each cause prints with its kind: a reader that reads a format otherwise, a field only one format writes, the note, the drawing, the diff, or an object in one format only; what the bed cannot name, `unknown`. Both checks over 530 commits take about half an hour in the foreground: a process started at low priority, as a background job may be, runs the first check several times slower.

**The sides.** Both are `GitSnapshot`s of one commit, restricted to `plc\blocks\`, `plc\types\` and `library\types\`: the folders both formats hold. The SimaticML side is the `simaticml\` folder, read whole (`_laid_out` off), as its root is no project repo's. The report is `compare_snapshots`, the same call the page makes.

**Facts.** A report is reduced to facts: per listed object its state, kind, declaration, note and library link; per interface row that differs its path, state and the fields that differ with their values (a start value apart), a member added or removed with its type, start value, comment, retain and attributes; per property its values; per network its state, language and tags, title and comment; per drawn LAD element its mark (the element as compared without its element id and wire names, its ENO included, the fill, and the areas marked from the element's own corner, from `Layout.marks`); per SCL or FBD network the lines that differ, all of them for a network added or removed, an SCL line with the kind of each of its words (`scl_colours.lines`). Two reports say the same when the facts are the same multiset. What that cannot see: which of two equal elements of a network carries a mark, where an element stands, the lines and wires drawn, the page's HTML, PLC tag tables and the HMI part; of a block listed by its heading alone (only its library version changed, or only its folder), what the page does not show either.

**Causes.** A cause has an id and a kind (`CAUSES`), named from what differs, never from the kind of object alone. For an element the two readers read otherwise, `element_causes` finds the fewest normalisations (`STEPS`: quotes around member names, a block call's pin case, pin direction, pin order, templates one side lacks, ENO) that make the two equal. A property is named by its values (`property_cause`): `DB retain` only where SimaticML has none. For a file one format moved and the other did not, and for a note one report has and the other not, `xml_moved` lists what differs in the SimaticML, order and ids left out, and `field_causes` names it from `XML_FIELDS`; a field the `.s7dcl` report shows and the SimaticML one leaves to its note from `XML_UNREAD`. An object with a file in one format only is `SimaticML missing` (SimaticML of it in another commit), `SimaticML never` or `.s7dcl missing`: what is seen, not why, which the run's log tells; so is an object a report joins to it (a rename, a move, its library type), and nothing else is looked for on it. Rung order names only marks of elements moved in a network tagged as in another order. An object or network both reports list in another state, kind or language, and a network title or comment that differs, is `unknown`; one a single report lists takes the causes of its other facts. What fits no rule has no kind: `unknown: ...`, or a field by its path (`SimaticML field: ...`, `SimaticML unread: ...`, `.s7dcl field: ...`). A field neither reader reads gives both reports the same note: the second check cannot see it. Nor can the first: between two formats the block's note compares no files (`compare.file_note`), and the page names the block as compared across the formats; `note: files` stays a cause, its count 0.

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
| `scl_colours.py` | The words of an SCL line in the colours of TIA's SCL editor |
| `theme.py` | The palette's block for a page, a theme file read and checked |
| `hmi.py`, `hmi.js`, `hmi.css` | The HMI part |
| `twoformats.py` | The two formats against each other: facts of a report, the two checks, their causes |

## The page

A self-contained HTML file: nothing is fetched. A summary table and a project tree in TIA's folders lead to the block sections, with `Before` and `After` columns from their sources. The HMI part stores its documents gzipped and base64-encoded in the page, and draws an object when it opens. `--fragment` writes only the `<div class="ldiff">`, and `--png` a screenshot through headless Edge or Chrome.

## Colours and themes

Every colour the page, the fragment, the PNG and the block viewer draw is a name of one palette: a CSS custom property on `.ldiff`. The palette and TIA's native theme, its default, are one file, `TiaHmiGenerator\hmipreview\static\tia-theme.css`, beside `ldiff.css` and `rail.css` that the report shares with the HMI preview. It has a line for each name, saying what the name colours and which pairs a theme must keep readable. `theme.py` reads it and a theme of the user's own in its format, and writes the palette's block into a page's `<style>`. `test_theme.py` holds the rest to it: no colour stands outside that block, in any style or in the SVG. A property that takes only a colour (`color`, each `*-color`, `fill`, `stroke`) is found by its value, anything but a name of the palette, `none`, `transparent`, `currentColor` and `inherit`; a colour inside a shorthand or a gradient by its hex, its function or CSS Color 4's lists of named and system colours.

- **What the renderer writes holds names and no colour.** A ladder's parts carry classes (`l-wire`, `l-box`, `hl added`, ...), and `render_lad.CSS` gives each its `fill` or `stroke` from a name. So a theme changes only the palette's block: the same rendering serves every theme, and a cache of fragments needs no theme in its key. An SVG copied out of the page alone has no colours: its shapes and text fill black, its lines do not show. `--png` is the way to a picture.
- **The report's own values are written `:where(.ldiff)`,** specificity 0. In a page of its own they go on `:root` instead, so that the page's head and body take them too.
- **A theme of the user's own** (how it is given: the README and `--help`) is read in `theme.py` alone, so that every report draws in it, those the bridge, the dashboard and Archive Compare start too. Its values come after TIA's, inside `@media screen`: print takes TIA's values, paper being white. Its format and what is refused are at the head of `tia-theme.css`. A standalone page keeps the theme it was made with. The environment variable `TIA_CR_USER_THEME`, when set, is the path read in place of the user's file: the test packages of the report and of Archive Compare's runner set it, and so do the bridge's `Report.Tests.ps1` and `BackgroundSmoke.ps1` and Archive Compare's window `check.py`, so that no report a test or check starts, as a child process too, reads the user's file.
- **A host gives a theme** in its own stylesheet: `.ldiff { --name: value; ... }`. It wins over the report's values wherever it stands, the fragment's `<style>` included. A value in a host's stylesheet may be any CSS colour, `var(--vscode-...)` among them, as no name is mixed or computed from another (`test_theme.TheNames`). A theme file is such a stylesheet as it stands, but it takes plain colours only: `theme.py` refuses `var()` there.
- **The forms a theme file takes** are `#rgb`, `#rgba`, `#rrggbb`, `#rrggbbaa`, `rgb()`, `rgba()` and `transparent`, as CSS Color 4 writes them, in its ASCII digits, letters and white space. Colour names, `hsl()` and the rest of CSS Color are refused by their form.
- **No character of a theme file reaches the page.** A value the browser refused would leave the property that uses it unset, a wire's stroke `none`, and the drawing would lose the wire with nothing said. So `theme.py` reads each value into numbers (red, green, blue, alpha), as the browser reads it, and writes the page's block from them in one form, `rgba(r,g,b,alpha)`: red, green and blue whole numbers, the alpha kept in full and not rounded to 8 bits as a hex pair would be, so that TIA's `.25` is `0.25`. `test_theme.TheWrittenForm` holds that form to Edge: Edge takes each case of it and reads it as the colour the value was. `TheFormsOfColour` holds what a theme takes to Edge's `CSS.supports('color', ...)` over generated values near those forms, so that a theme refuses no value of those forms that the browser draws. A form added later wants its reading and both tests widened together.
- **What takes no theme.** The palette holds the report's own chrome, the project tree (`rail.css`) and the HMI part's (`hmi.css`) among it. An HMI screen and a value's colour swatch (`hmi.js`, `render.js`) are drawn in the project's colours. The HMI preview's own panels (`app.css`, `props.css`), which the report does not draw, keep their colours and take the palette's names only where they shared `ldiff.css`'s. Archive Compare's window (Qt) takes none.

### Following a VS Code theme

Following a VS Code theme is the VS Code extension's job; this table is what it maps from. A webview gets the running theme's colours as `var(--vscode-<id>)`, where `<id>` is a theme colour id with `.` as `-`, and a class on `body`: `vscode-light`, `vscode-dark` or `vscode-high-contrast`. That much is in [VS Code's webview guide](https://code.visualstudio.com/api/extension-guides/webview). The guide does not name `vscode-high-contrast-light`, which element carries the variables, or whether they change when the user switches theme. Those want checking in a running VS Code.

A webview gets no syntax colours: a theme's token colours are not among those variables. So LAD's and SCL's word colours have stand-ins at best (`symbolIcon.*`, `debugTokenExpression.*`). Where the table says *per kind*, no VS Code colour fits, and the extension needs a value of its own for light, dark and high contrast themes.

| Name | VS Code colour id |
|---|---|
| `--page` | `editor.background` |
| `--text` | `editor.foreground` |
| `--muted` | `descriptionForeground` |
| `--faint` | `editorLineNumber.foreground` |
| `--empty-field-text` | `input.placeholderForeground` |
| `--viewer-note` | `descriptionForeground` |
| `--link` | `textLink.foreground` |
| `--link-underline` | `textLink.foreground` |
| `--match` | `list.highlightForeground` |
| `--page-head` | `editorGroupHeader.tabsBackground` |
| `--page-head-line` | `editorGroupHeader.tabsBorder` |
| `--band` | `sideBarSectionHeader.background` |
| `--field` | `input.background` |
| `--row` | `editorWidget.background` |
| `--network-number` | `badge.background` |
| `--line` | `panel.border` |
| `--grid` | `tree.indentGuidesStroke` |
| `--edge` | `widget.border` |
| `--divider` | `panel.border` |
| `--no-line` | `diffEditor.diagonalFill` |
| `--opened-member` | `tree.tableOddRowsBackground` |
| `--added` | `gitDecoration.addedResourceForeground` |
| `--added-fill` | `diffEditor.insertedLineBackground` |
| `--added-word` | `diffEditor.insertedTextBackground` |
| `--removed` | `gitDecoration.deletedResourceForeground` |
| `--removed-fill` | `diffEditor.removedLineBackground` |
| `--removed-word` | `diffEditor.removedTextBackground` |
| `--changed` | `gitDecoration.modifiedResourceForeground` |
| `--changed-fill` | *per kind* |
| `--changed-row` | *per kind* |
| `--moved` | `gitDecoration.renamedResourceForeground` |
| `--moved-fill` | *per kind* |
| `--moved-row` | *per kind* |
| `--same` | `disabledForeground` |
| `--same-mark` | `editor.background` |
| `--version` | `descriptionForeground` |
| `--badge-text` | `badge.foreground` |
| `--mark-line` | `widget.border` |
| `--off-over-mark` | *per kind* |
| `--button` | `button.secondaryBackground` |
| `--button-hover` | `button.secondaryHoverBackground` |
| `--button-line` | `button.border` |
| `--button-text` | `button.secondaryForeground` |
| `--button-off-text` | `disabledForeground` |
| `--switch` | `button.secondaryBackground` |
| `--switch-on` | `inputOption.activeBackground` |
| `--input` | `input.background` |
| `--input-text` | `input.foreground` |
| `--focus` | `focusBorder` |
| `--hover` | `list.hoverBackground` |
| `--selected` | `list.activeSelectionBackground` |
| `--change-hover` | `list.hoverBackground` |
| `--icon` | `icon.foreground` |
| `--tree-icon` | `icon.foreground` |
| `--window-line` | `editorWidget.border` |
| `--shadow` | `widget.shadow` |
| `--backdrop` | *per kind* |
| `--minimap-view` | `minimapSlider.background` |
| `--minimap-view-line` | `minimapSlider.activeBackground` |
| `--error-fill` | `inputValidation.errorBackground` |
| `--error-line` | `inputValidation.errorBorder` |
| `--checkbox` | `checkbox.background` |
| `--checkbox-line` | `checkbox.border` |
| `--checkbox-on` | `button.background` |
| `--checkbox-on-line` | `button.background` |
| `--checkbox-tick` | `button.foreground` |
| `--checkbox-off` | `checkbox.disabled.background` |
| `--checkbox-off-line` | `checkbox.border` |
| `--checkbox-off-on` | `checkbox.disabled.background` |
| `--checkbox-off-on-line` | `checkbox.border` |
| `--checkbox-off-tick` | `checkbox.disabled.foreground` |
| `--wire` | `editor.foreground` |
| `--lad-text` | `editor.foreground` |
| `--lad-comment` | *per kind* |
| `--lad-value` | `debugTokenExpression.value` |
| `--lad-constant` | `debugTokenExpression.number` |
| `--lad-default` | `editorInlayHint.foreground` |
| `--lad-number` | `debugTokenExpression.number` |
| `--eno-off` | `disabledForeground` |
| `--pin-open` | `editorLineNumber.foreground` |
| `--box` | `editorWidget.background` |
| `--box-line` | `editorWidget.border` |
| `--box-head` | `sideBarSectionHeader.background` |
| `--box-cell-line` | `editorWidget.border` |
| `--compare-type` | `sideBarSectionHeader.background` |
| `--expression` | `input.background` |
| `--calculator` | `button.secondaryBackground` |
| `--calculator-line` | `icon.foreground` |
| `--conversion` | *per kind* |
| `--conversion-light` | *per kind* |
| `--jump-label` | *per kind* |
| `--jump-label-line` | `editor.foreground` |
| `--scl-keyword` | `symbolIcon.keywordForeground` |
| `--scl-region` | *per kind* |
| `--scl-constant` | `symbolIcon.constantForeground` |
| `--scl-comment` | *per kind* |
| `--scl-operand` | `symbolIcon.variableForeground` |
| `--scl-local-constant` | `symbolIcon.constantForeground` |
| `--scl-block-call` | `symbolIcon.functionForeground` |
| `--scl-instruction` | `symbolIcon.methodForeground` |
| `--scl-parameter` | `debugTokenExpression.name` |
| `--scl-operator` | `symbolIcon.operatorForeground` |
| `--screen-surround` | *per kind* |
| `--screen-edge` | `widget.border` |
| `--object-selected` | `focusBorder` |
| `--checker` | *per kind* |
| `--checker-light` | *per kind* |
| `--swatch-line` | `widget.border` |

The `diffEditor.*` backgrounds are translucent by VS Code's own description. Drawn over `--page`, as the report draws them, they read as VS Code's diff editor does.

## Who calls it

- **TiaBridge's `change_report`:** `--git <repo> REV1 REV2 --json`.
- **TiaArchiveCompare's runner:** two export folders, through junctions named after the inputs, as the report names a side by its folder.

`--json` prints one object: `page`, `before`, `after` and `blocks`, and where they apply `plcTags`, `hmi`, `skipped`, `unmatched` and `png`.

Exit codes, and what it skips rather than stops at: [its README, What it does not](../../../TiaChangeReports/README.md#what-it-does-not).
