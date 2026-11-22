---
type: Guide
title: "TIA Openness V20 facts: failures, modal dialogs and project lifecycle"
description: "How TIA Portal Openness V20 calls fail, transactions, online mode, modal dialogs, names and files, archive, UMC, safety passwords, starting TIA, opening and closing projects, and STA/MTA hangs."
tags: [openness, tia-v20, failures, agents]
generated: { by: antigravity/gemini-4-neon, at: 2026-11-21T19:40:00-05:00 }
---

# TIA Openness V20 facts: failures, modal dialogs and project lifecycle

Part of the [TIA Openness V20 facts for agents](openness-v20.md): sections 4 and 5, failures and project lifecycle. A section keeps its number in the file that holds it; the table at the head of the guide names the file of a section cited by number, and its Sources section holds the citations `[n]`.

## 4. Failures

- **Exceptions.** `EngineeringException` and its subtypes are recoverable (`EngineeringTargetInvocationException`,
  `EngineeringNotSupportedException`, `EngineeringSecurityException`, `EngineeringObjectDisposedException`, ...);
  the message and its detail texts say what TIA refused. `NonRecoverableException` means TIA is gone [7]. After a TIA
  crash or a closed project every object throws `EngineeringObjectDisposedException` [7]. Quote them as the bridge
  gives them.
- **Result objects** can fail without an exception: document imports, library exports and compiles report through
  `State` [18][26].
- **Transactions.** A write runs in one transaction: one undo entry in TIA, and after a failed import TIA refuses the
  commit, so a batch is all or nothing `[PROBE]` [6]. Compile, save and opening or closing a library are not allowed
  inside one [6]; the bridge archives outside it too.
- **Online.** With a device online TIA refuses the transaction: *The operation is not permitted in online mode* (seen
  2026-11-05). Without a transaction nothing rolls a failed batch back, so the bridge refuses the write: "TIA is
  online: go offline first", nothing written. It refuses too when the transaction fails in other words, or the
  settings turn transactions off, and a device reads online; save and compile run online. `connect` and `tia_status`
  give each device's `online`: the `OnlineProvider` state of the device item that holds its software, in lower case,
  or `unknown` where none can be read. Which device items have one, an HMI's among them, is not probed `[INFERRED]`.
- **Modal dialogs.** A failing call can wait on a TIA message box for many minutes: when a write takes more than a
  minute, someone has to look at TIA `[PROBE]`. A TIA without window has none; the bridge answers its prompts.
  `full_export` waited 590 s behind an "Export Completed (0032:000002)" box in a TIA with a window. Without window that
  box arrives as a `Notification` and the part stays under 60 s `[PROBE]`. So in a TIA with a window `full_export`
  acknowledges, for the length of the call, the notifications with the icon `Success` or `Information`; `Warning` and
  `Error` boxes and every question stay with the person at TIA. All notifications are listed with their icon
  (`prompts`). With a window not probed: whether handling closes the box, what icon it carries, and whether a box of the
  person's own work during the call reaches the guard (the event is the portal's, not the call's).
- **Another name.** An import can land under another name with no message: a tag table deleted and imported straight
  after came back as `<name>_1`, and a second delete and import gave the right name `[PROBE]`. That was an HMI tag table, each
  time on three tries. A PLC tag table, import, delete, import in one session, kept its name `[PROBE]`; the HMI one was not tried again. TiaBridge compares the
  names TIA returns with the name the document declares: the result is not ok, with `importedAs` and `namedOtherwise`.
- **What TIA takes in a name** `[PROBE]`: `ImportFromDocuments` made a block of each of these names, and gave the name back as
  written: a blank inside, `.`, `-`, `_`, `:`, `/`, `\`, `*`, `?`, `<`, `>`, `|`, `#`, `%`, `&`, `(`, `)`, `[`, `]`, `{`, `}`,
  `~`, `+`, `=`, `,`, `;`, `'`, `$"` together (each alone was not tried; `$` may be the escape of the `"`), a dot or a blank at the end, a blank
  in front, two dots at the end. So nothing stops two such names from giving one file. `CreateFromDocuments` took a library type with a blank,
  `.`, `-`, `/`, `*`, `$"` too, and a dot at the end; a blank at the end was dropped: `zzT ` became the type `zzT`, with no message. An FC named with a `:` compiles with 0 errors; compiling
  the others was not tried, nor a letter outside ASCII.
- **Device names, control characters, case in a name** `[PROBE]`, FCs by `ImportFromDocuments`. `NUL`, `CON`, `COM1`, `LPT1`: made, their documents read `NUL_.s7dcl` and so on,
  and `NUL_.s7dcl` goes back; `NUL`, `CON` compile with 0 errors. A tab and U+0001 in a name: made, exported as `zz_Tab.s7dcl`, and the compile answers
  *Name: The name may only contain the characters "A-z", "0-9" or the underscore. Starting with a digit or ending with an underscore is not permitted.*
  Names differing only in case: `zzCaseABC` with `zzCaseAbc` in the project leaves one block, spelled `zzCaseABC`, with no message. Other kinds were not tried.
- **A property of a dead object raises nothing** `[PROBE]`. After `Project.Close()`, in Windows PowerShell 5.1 under `$ErrorActionPreference = 'Stop'`, reading `Name` or `Path`
  of the project or `Name` of a block returns `$null`, and no `catch` fires. The method `GetAttribute('Name')` throws: *Access to a disposed object of type
  'Siemens.Engineering.SW.Blocks.FC' is not possible. The object is no longer available.* So reading a property does not show that an object is alive. A getter that throws for another reason was not tried.
- **Names and files.** TiaBridge makes a name file-safe: the nine characters Windows forbids and control characters
  become `_`, so does a dot or space at the end, and a Windows device name gets `_` behind it (`NUL` -> `NUL_`). Names
  that give one file (`Ns:Block` and `Ns_Block`, or `Abc` and `ABC`) are refused by `export` and `full_export`: neither
  is exported and the files there stay. Rename one in TIA. Devices or global libraries whose names give one folder each
  get a folder with a mark of the exact name (`PLC_1~1a2b3c4d`), and the result says so; the HMI tools take that folder
  as the device. A device holding two software items of one kind (each has the device's name) is refused by `export`
  and `full_export`: nothing of it is exported and its files stay. Whether TIA can produce that is not probed. TIA goes by the
  declared name: with `zzNs:Plain` in the project, a document declaring `zzNs_Plain` made a second block beside it and replaced
  nothing, whatever the file was called, and `export` and `full_export` then refused both `[PROBE]`. With `zzCh:Six` and `zzCh_Six` both in the project, `zzCh_Six.s7dcl` declaring
  `zzCh:Six` replaced `zzCh:Six` and left `zzCh_Six` as it was; with `zzCh:Six` alone, a SimaticML file of that name did the same and no `zzCh_Six` came `[PROBE]`. So a guard reading the
  declared name looks at the right block.
- **Archive** refuses a project with unsaved changes `[PROBE]`. TIA can mark a project modified on opening, with no
  write made (seen without user interface, 2026-11-01), so it may need a save before its first archive `[PROBE]`.
- **UMC.** Without user interface, opening a UMC-protected project without a login fails after about 20 s ("The
  project is protected. You are not authorized to open the project in write mode."), without a prompt `[PROBE]`.
- **Safety.** A wrong safety password fails with "Wrong Safety Administration Editor password was supplied."
  `[PROBE]`.

## 5. Starting TIA, opening and closing a project

On copies of a test project, 2026-11-04 `[PROBE]`; the bridge's tools are `project_open` and `project_close`.

- **A TIA with a window outlives what started it.** Started through Openness (`new TiaPortal(WithUserInterface)`), or as the
  program, it stays open with its project when the starter is killed, when it exits with no `Dispose`, and after `Dispose`,
  which does end a TIA without window. Each `Dispose` of an attach leaves TIA as it is.
- **The TIA program with a path:** `Siemens.Automation.Portal.exe "<path>"`. The process started shows the project in its title
  and holds it in `GetProcesses` at about 15 s. It then has a child process of the same name, with no window; that one is not
  in `GetProcesses`, and its command line names no project (`-Name=SearchReplaceBackgroundProcess ...`). Behind a box there is
  no child yet. The started process keeps the path on its command line, which is how `project_open` finds one waiting, also
  after a bridge restart (2026-11-05).
- **A box at opening** stands in front of a process started that way, with no time limit: *Log on* for a protected project;
  *Open reference project (0100:000295)* for a project open in another TIA; *Open project (0025:000012)*, "Project not found",
  for a file that does not exist. Until it is answered the process is not in `GetProcesses`, though it runs and responds, so
  only the title of the box tells them apart (UI Automation). After the login the process holds the project and an attach
  reads it as any other. *Log on* closed with no login: the process stays, unlisted, behind *Open project (4600:000103)*
  (2026-11-05).
- **One project per process.** `Projects.Open` in a TIA that holds one is refused at once: "Unable to open project '...'.
  Another project is already open.", with no box. The program with another path starts a second TIA process and leaves the
  first as it was. That holds for a primary project: a second one opens read-only beside it as a secondary project
  (section 6).
- **`Project.Close()` through an attach** works: 1 s, and TIA stays open with its window and no project, still in `GetProcesses`
  with an empty path. `Projects.Open` through an attach then opens one in 2 s. It asks nothing: **with unsaved changes it
  closes in the same way and they are gone**, with no event. In PowerShell the old `Project` object answers afterwards: `Name`
  reads empty, with no exception.
- **A person's close with a script attached and idle** goes through, with no hang and no message. An older note has TIA unable
  to close a project with a bridge attached; neither a plain attach nor TiaBridge attached and idle shows that. A close
  through a second program does hang beside an idle STA client (next point); why a close in TIA's window does not is not known.
- **The access dialog** shows at the first attach of a program, until someone answers "Yes to all" for that program. An attach
  then takes about a second.
- **TIA waits on a client attached from an STA thread** `[PROBE]` (2026-11-12: stacks of TIA and the client at the hang, and
  `Siemens.Engineering.dll` read). When a list changes in TIA (a project closes, a block or a group is added), TIA calls back
  into every Openness session that has read that list (`PageEnumerator.EnumeratorInvalidated`), and its UI thread waits for the
  answer. A session attached from an STA thread keeps such call-backs in a queue that only its own next call empties, and
  nothing empties it on dispose; from an MTA thread a call-back runs at once. So beside an STA session that read the list, TIA
  waits for that session's next call, and for a disposed one until its process ends. Hangs on demand, each from STA and none
  from MTA: attach, read `Projects`, dispose, attach again, `Close()` (*Closing project...*); two live sessions, `Close()` through
  the second; block groups read in one session, a group created through the other. A session that reads nothing does not take
  part. A garbage collection does not release what a session read.
- **TiaBridge attaches from an MTA thread** of its own since then. The bridge of release 0.1.0 ran on the STA thread of `powershell.exe -STA`
  and hung TIA so, from 2026-10-19 on: after a switch to a project in a second TIA process and back (`connect` disposes the
  session it leaves), a `project_close` in *Closing project...* or an import with only the exclusive-access box; with the bridge
  idle; beside a second, stale bridge. Another program attached from an STA thread, a bridge of release 0.1.0 among them, still hangs
  TIA so. Stopping it frees TIA, mostly within seconds; once it did not within 30 s. `tia_status` names other bridges on the
  same TIA. From an MTA thread call-backs run while the bridge's own calls run, so TIA can change a list while the bridge
  reads it: the client's enumerator then throws `InvalidOperationException` "Collection was modified; enumeration operation
  may not execute." from `MoveNext`, a text of its own, not translated. Read again, at most three times in all: the objects
  of each kind, folder trees, the devices and their items, the projects and the global libraries. Not read again: other
  lists, such as the versions of a library type and their dependencies.
- **Not explained:** an import of OB `Main` (2026-11-08) that never returned, with one bridge attached once and no other program
  known; TIA ended when the bridge was stopped. No stack was taken.
