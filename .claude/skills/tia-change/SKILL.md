---
name: tia-change
description: "Change a TIA Portal project through TiaBridge: PLC blocks, data types and DBs; HMI screens, tag tables and text lists; library types."
---

The order a change of a TIA project takes. The guides, and the tools' descriptions and results, hold the rest; a guide is the single source of truth for the work it covers. Steps 3 to 8 repeat per finished change; the archive is once per session.

Git in a project repo goes by `git -C "C:/<projects root>/<repo>"`: the results give backslash paths, and first setup's allow rules match the forward form only.

| Kind of work | Reference file |
|---|---|
| PLC block, data type, DB | [plc.md](plc.md) |
| HMI screens, templates, pop-ups, tag tables, text lists | [hmi.md](hmi.md) |
| Library types | [library.md](library.md) |

## Steps

1. **Bind.** `connect`. If the project is not open and the user named it, `project_open`, then `connect`. When the user asks for a background session, with the project closed in their TIA: `background_open(write: true)`. A device that reads `online: online` refuses changes: ask the user to go offline in TIA. Done when the result's `session.writesAllowed` is true and no device reads online.
   - **Once in your session,** after its first `connect` or `background_open`, not again when you connect later, and not where no person reads your messages (a subagent, a run with no chat): look as skill [tia-dashboard](../tia-dashboard/SKILL.md) looks first, and do what it says, except that where nothing answers you offer the TIA dashboard instead of starting it. In one sentence: the address, e.g. "You can watch what I do in TIA, and what needs you, on the TIA dashboard: http://127.0.0.1:<port>/", or the offer, e.g. "You can watch what I do in TIA, and what needs you, on the TIA dashboard, a local page: shall I start it?". On a yes, follow that skill. Start nothing and open no browser unasked; carry on without waiting. Done when your message holds what the look found, or no person reads it.
2. **Read the notes.** The file in `readFirst`. Done when read.
3. **Read for the work.** The reference file above, the guide it names, and what `standards` in the result says. Done when each is read.
4. **Commit the old state.** `git status` clean, `full_export` before each change, so a change somebody made in TIA to any object reaches the repo apart from this work. Commit what differs. Done when nothing is uncommitted.
   - Only if that commit changed or removed a tracked file of an object, not just the bridge's `tiabridge.json` or `logs\`: `change_report` on it, and give the user the page as changes already in TIA before this work; carry on without waiting. A first export only adds files, so it takes no report. Done when the page is given, or nothing tracked changed.
5. **The middle,** from the reference file. Done when each device written compiles with 0 errors and nothing of this session's stands in `failed`.
6. **Save.** `save(reason)`, after each finished change; quote `savedWith`. Done when saved.
7. **Commit.** `full_export`, per change, so each page holds what its own change touched: TIA changes objects no import named (a member of a data type renamed drops a DB's start value of it), and an import writes nothing of TIA to the repo. Then update the notes of step 2, `git add -A`, commit. Done when the repo is clean.
8. **Report.** `change_report`, after that commit; give the user the page. Done when the page exists.
9. **Hand over.** Say what is left for the user (the download). `background_close` in a background session; `project_close` only if the user asked. Where the user asks where to see what agents do: skill [tia-dashboard](../tia-dashboard/SKILL.md). Done when closed where asked.

## The full export

- **Cost:** about minutes per thousand objects, longer in a TIA with a window (openness-v20.md, Modal dialogs). After a full export of every part, its `totalMs` goes in the notes of step 2.
- **`parts`:** where the notes say a full export takes over 10 minutes, `parts` may hold it to the kinds the change can touch: the PLC parts (`blocks` to `external_sources`) for a PLC change, with the `hmi_` parts when it renames what an HMI reads, and with `library_types` for a library change. `parts` picks kinds, never a device: every PLC exports. Each report of the session then names the kinds left out in its `title`, e.g. "Changes already in TIA; HMI, project and library not exported".
- **The result:** before the commit, do what its `next` says, except under `removeErrors`. Where it is not `ok`:
  - `removeErrors`: files of objects TIA no longer has could not be removed, and a commit would keep them as if the objects stood. Fix what each line names and `full_export` again; when it stays, commit nothing and tell the user.
  - `stopped`: TIA ended mid-export. Commit nothing and tell the user; the session waits there until `full_export` runs through.
  - `failed` lines: what each names, an object, a part or a device, was not exported, and its files stay as they were. Commit, and name those lines in the commit message and to the user beside the page: a change there is on no page.
